"""Config flow for GoodWe SEMS Curtailment.

Collects the SEMS Portal login and the sizing values the curtailment
automations need, through Settings -> Devices & Services -> Add
Integration, rather than install.sh prompting for any of it at the
terminal.

The inverter serial number and rated capacity are no longer typed in by
hand - login succeeds, then api.py's discover_inverter() finds the
account's power station and inverter automatically (see api.py for the two
SEMS Portal endpoints this uses). Only the sizing values that AREN'T
discoverable this way (battery max charge rate, load threshold, full SOC
threshold) are still asked for on the form. Battery capacity isn't asked
for either - it's read live from the baseline Amber integration's Battery
Capacity sensor at automation runtime, the same way state of charge is. A "Refresh
Inverter Info" button (button.py) re-runs discovery later, for the rare
case the inverter is swapped or the SEMS Portal starts reporting different
values.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .api import SemsApi, SemsApiError, SemsAuthError
from .helpers import async_apply_sizing
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


def _clean(user_input: dict[str, Any]) -> dict[str, Any]:
    data = dict(user_input)
    data[CONF_SEMS_EMAIL] = data[CONF_SEMS_EMAIL].strip()
    return data


async def _async_login_and_discover(
    hass, email: str, password: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Log in and discover the inverter. Returns (discovered, None) on
    success or (None, error_key) on failure."""
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
        _LOGGER.warning("SEMS Portal discovery failed: %s", msg)
        return None, "discovery_failed"
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unexpected error discovering SEMS inverter")
        return None, "unknown"
    return discovered, None


class SemsCurtailmentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
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
            if error:
                errors["base"] = error
            else:
                assert discovered is not None
                data.update(
                    {
                        CONF_POWERSTATION_ID: discovered["powerstation_id"],
                        CONF_STATION_NAME: discovered["station_name"],
                        CONF_INVERTER_SN: discovered["inverter_sn"],
                        CONF_INVERTER_CAPACITY_W: discovered["inverter_capacity_w"],
                    }
                )
                await self.async_set_unique_id(discovered["inverter_sn"])
                self._abort_if_unique_id_configured()
                title = discovered["station_name"] or discovered["inverter_sn"]
                return self.async_create_entry(
                    title=f"SEMS Curtailment ({title})", data=data
                )

        return self.async_show_form(
            step_id="user", data_schema=_build_schema(user_input), errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> SemsCurtailmentOptionsFlow:
        return SemsCurtailmentOptionsFlow(config_entry)


class SemsCurtailmentOptionsFlow(config_entries.OptionsFlow):
    """Update SEMS login / sizing later, without deleting and re-adding the
    integration - e.g. after a SEMS Portal password change, or swapping in
    a bigger battery. Re-runs inverter discovery too, same as initial setup
    (use the "Refresh Inverter Info" button instead if login is unchanged
    and you only want to re-check the inverter).
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
            if error:
                errors["base"] = error
            else:
                assert discovered is not None
                data.update(
                    {
                        CONF_POWERSTATION_ID: discovered["powerstation_id"],
                        CONF_STATION_NAME: discovered["station_name"],
                        CONF_INVERTER_SN: discovered["inverter_sn"],
                        CONF_INVERTER_CAPACITY_W: discovered["inverter_capacity_w"],
                    }
                )
                title = discovered["station_name"] or discovered["inverter_sn"]
                self.hass.config_entries.async_update_entry(
                    self._entry, title=f"SEMS Curtailment ({title})", data=data
                )
                # Push the submitted sizing onto the number entities. Done
                # here rather than from a config-entry update listener so
                # that only an explicit form submission overwrites them -
                # a listener would also fire for the Refresh Inverter Info
                # button and reset values the user had hand-tuned.
                await async_apply_sizing(self.hass, self._entry)
                return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(user_input or self._entry.data),
            errors=errors,
        )
