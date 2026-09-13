"""Config flow for GoodWe SEMS Curtailment.

Collects the SEMS Portal login and the sizing values the curtailment
automations need, through Settings -> Devices & Services -> Add
Integration, rather than install.sh prompting for any of it at the
terminal.

Inverter discovery has two paths, tried in order:

  1. Full auto (api.py's discover_inverter()) - looks up the account's
     power stations, then the first station's inverter, giving us the
     serial number, rated capacity, AND a station name/id for a nicer
     title. This is the preferred path when it works.

  2. Manual serial number fallback (async_step_inverter_sn below, using
     api.py's discover_by_serial()) - used when step 1's login succeeds
     but the station-list lookup comes back with an empty list. This is a
     REAL, CONFIRMED failure mode (Sept 2026), not a hypothetical one: the
     account-level station list endpoint can return a clean empty
     response while device-level, serial-number-keyed endpoints (status,
     set_power_limit, start/stop) keep working fine. When this happens,
     the flow asks for the inverter's serial number directly (printed on
     the inverter's label, or visible in the SEMS+ app) and validates it
     via the still-working per-device endpoint instead. Only rated
     capacity comes back this way - no station name/id.

Only the sizing values that AREN'T discoverable either way (battery max
charge rate, load threshold, full SOC threshold) are asked for on the
first form. Battery capacity isn't asked for either - it's read live from
the baseline Amber integration's Battery Capacity sensor at automation
runtime, the same way state of charge is. A "Refresh Inverter Info" button
(button.py) re-runs discovery later, for the rare case the inverter is
swapped or the SEMS Portal starts reporting different values.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .api import SemsApi, SemsApiError, SemsAuthError
from .const import (
    CONF_BATTERY_MAX_CHARGE_RATE_W,
    CONF_FULL_SOC_THRESHOLD,
    CONF_INVERTER_CAPACITY_W,
    CONF_INVERTER_SN,
    CONF_LOAD_THRESHOLD_W,
    CONF_POWERSTATION_ID,
    CONF_SEMS_EMAIL,
    CONF_SEMS_PASSWORD,
    CONF_STATION_NAME,
    DEFAULT_BATTERY_MAX_CHARGE_RATE_W,
    DEFAULT_FULL_SOC_THRESHOLD,
    DEFAULT_LOAD_THRESHOLD_W,
    DOMAIN,
    MAX_BATTERY_MAX_CHARGE_RATE_W,
    MAX_FULL_SOC_THRESHOLD,
    MAX_LOAD_THRESHOLD_W,
    MIN_BATTERY_MAX_CHARGE_RATE_W,
    MIN_FULL_SOC_THRESHOLD,
    MIN_LOAD_THRESHOLD_W,
)
from .helpers import async_apply_sizing

_LOGGER = logging.getLogger(__name__)


def _build_schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    """Build the login + sizing form (inverter fields are discovered, not asked)."""
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_SEMS_EMAIL, default=d.get(CONF_SEMS_EMAIL, "")
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)
            ),
            vol.Required(
                CONF_SEMS_PASSWORD, default=d.get(CONF_SEMS_PASSWORD, "")
            ): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Required(
                CONF_BATTERY_MAX_CHARGE_RATE_W,
                default=d.get(
                    CONF_BATTERY_MAX_CHARGE_RATE_W, DEFAULT_BATTERY_MAX_CHARGE_RATE_W
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_BATTERY_MAX_CHARGE_RATE_W,
                    max=MAX_BATTERY_MAX_CHARGE_RATE_W,
                    step=10,
                    unit_of_measurement="W",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_LOAD_THRESHOLD_W,
                default=d.get(CONF_LOAD_THRESHOLD_W, DEFAULT_LOAD_THRESHOLD_W),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_LOAD_THRESHOLD_W,
                    max=MAX_LOAD_THRESHOLD_W,
                    step=50,
                    unit_of_measurement="W",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_FULL_SOC_THRESHOLD,
                default=d.get(CONF_FULL_SOC_THRESHOLD, DEFAULT_FULL_SOC_THRESHOLD),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_FULL_SOC_THRESHOLD,
                    max=MAX_FULL_SOC_THRESHOLD,
                    step=1,
                    unit_of_measurement="%",
                    mode=selector.NumberSelectorMode.SLIDER,
                )
            ),
        }
    )


def _serial_schema(default_sn: str = "") -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_INVERTER_SN, default=default_sn): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
            )
        }
    )


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    data = dict(user_input)
    data[CONF_SEMS_EMAIL] = data[CONF_SEMS_EMAIL].strip()
    return data


def _merge_discovered(data: dict[str, Any], discovered: dict[str, Any]) -> dict[str, Any]:
    return {
        **data,
        CONF_POWERSTATION_ID: discovered["powerstation_id"],
        CONF_STATION_NAME: discovered["station_name"],
        CONF_INVERTER_SN: discovered["inverter_sn"],
        CONF_INVERTER_CAPACITY_W: discovered["inverter_capacity_w"],
    }


async def _async_login_and_discover(
    hass, email: str, password: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Log in and discover the inverter via the full-auto (station-list)
    path. Returns (discovered, None) on success or (None, error_key) on
    failure. error_key "discovery_failed" specifically means login worked
    but the station list came back empty - callers should offer the manual
    serial-number fallback for that case rather than treating it as fatal.
    """
    if not email or not password:
        return None, "missing_fields"
    api = SemsApi(email, password)
    try:
        discovered = await hass.async_add_executor_job(api.discover_inverter)
    except SemsAuthError:
        return None, "invalid_auth"
    except SemsApiError as err:
        msg = str(err)
        if "timed out" in msg:
            # The SEMS Portal is known to be intermittently slow. Log at info
            # rather than warning so it doesn't pollute the log on every
            # transient hiccup, and give the user a clear retry message.
            _LOGGER.info("SEMS Portal timed out during setup: %s", msg)
            return None, "cannot_connect"
        _LOGGER.info("Station-list discovery failed, will offer manual serial entry: %s", msg)
        return None, "discovery_failed"
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unexpected error discovering SEMS inverter")
        return None, "unknown"
    return discovered, None


async def _async_discover_by_serial(
    hass, email: str, password: str, inverter_sn: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate a manually-entered serial number via the still-working
    per-device endpoint. Returns (discovered, None) or (None, error_key).
    """
    sn = inverter_sn.strip()
    if not sn:
        return None, "missing_serial"
    api = SemsApi(email, password)
    try:
        discovered = await hass.async_add_executor_job(api.discover_by_serial, sn)
    except SemsAuthError:
        return None, "invalid_auth"
    except SemsApiError as err:
        msg = str(err)
        if "timed out" in msg:
            _LOGGER.info("SEMS Portal timed out during serial lookup: %s", msg)
            return None, "cannot_connect"
        _LOGGER.warning("Manual serial number lookup failed: %s", err)
        return None, "serial_lookup_failed"
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unexpected error looking up SEMS inverter by serial")
        return None, "unknown"
    return discovered, None


class _InverterSnFallbackMixin:
    """Shared manual-serial-number step for both flows below.

    Subclasses store the already-validated email/password/sizing in
    self._pending_data before transitioning here, and implement
    _finalize(discovered) to turn a successful lookup into the flow's
    result (creating or updating the config entry).
    """

    _pending_data: dict[str, Any]
    hass: Any  # provided by ConfigFlow/OptionsFlow base classes

    async def async_step_inverter_sn(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            discovered, error = await _async_discover_by_serial(
                self.hass,
                self._pending_data[CONF_SEMS_EMAIL],
                self._pending_data[CONF_SEMS_PASSWORD],
                user_input[CONF_INVERTER_SN],
            )
            if error:
                errors["base"] = error
            else:
                assert discovered is not None
                return await self._finalize(discovered)  # type: ignore[attr-defined]

        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="inverter_sn",
            data_schema=_serial_schema((user_input or {}).get(CONF_INVERTER_SN, "")),
            errors=errors,
        )


class SemsCurtailmentConfigFlow(
    _InverterSnFallbackMixin, config_entries.ConfigFlow, domain=DOMAIN
):
    """Handle the initial setup - SEMS login and sizing; inverter is discovered."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            data = _clean(user_input)
            discovered, error = await _async_login_and_discover(
                self.hass, data[CONF_SEMS_EMAIL], data[CONF_SEMS_PASSWORD]
            )
            if error == "discovery_failed":
                self._pending_data = data
                return await self.async_step_inverter_sn()
            if error:
                errors["base"] = error
            else:
                assert discovered is not None
                self._pending_data = data
                return await self._finalize(discovered)

        return self.async_show_form(
            step_id="user", data_schema=_build_schema(user_input), errors=errors
        )

    async def _finalize(self, discovered: dict[str, Any]) -> config_entries.ConfigFlowResult:
        data = _merge_discovered(self._pending_data, discovered)
        await self.async_set_unique_id(discovered["inverter_sn"])
        self._abort_if_unique_id_configured()
        title = discovered["station_name"] or discovered["inverter_sn"]
        return self.async_create_entry(title=f"SEMS Curtailment ({title})", data=data)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> SemsCurtailmentOptionsFlow:
        return SemsCurtailmentOptionsFlow(config_entry)


class SemsCurtailmentOptionsFlow(_InverterSnFallbackMixin, config_entries.OptionsFlow):
    """Update SEMS login / sizing later, without deleting and re-adding the
    integration - e.g. after a SEMS Portal password change, or swapping in
    a bigger battery. Re-runs inverter discovery too (falling back to a
    manual serial number the same way initial setup does, if needed) - use
    the "Refresh Inverter Info" button instead if login is unchanged and
    you only want to re-check the inverter.
    """

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            data = _clean(user_input)
            discovered, error = await _async_login_and_discover(
                self.hass, data[CONF_SEMS_EMAIL], data[CONF_SEMS_PASSWORD]
            )
            if error == "discovery_failed":
                self._pending_data = data
                return await self.async_step_inverter_sn()
            if error:
                errors["base"] = error
            else:
                assert discovered is not None
                self._pending_data = data
                return await self._finalize(discovered)

        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(user_input or self._entry.data),
            errors=errors,
        )

    async def _finalize(self, discovered: dict[str, Any]) -> config_entries.ConfigFlowResult:
        data = _merge_discovered(self._pending_data, discovered)
        title = discovered["station_name"] or discovered["inverter_sn"]
        self.hass.config_entries.async_update_entry(
            self._entry, title=f"SEMS Curtailment ({title})", data=data
        )
        # Push the submitted sizing onto the number entities. Done here
        # rather than from a config-entry update listener so that only an
        # explicit form submission overwrites them - a listener would also
        # fire for the Refresh Inverter Info button and reset values the
        # user had hand-tuned.
        await async_apply_sizing(self.hass, self._entry)
        return self.async_create_entry(title="", data={})
