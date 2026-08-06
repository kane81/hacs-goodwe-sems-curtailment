"""Button entities for GoodWe SEMS Curtailment.

Four buttons, all plain "do something now" actions, deliberately kept off
the dashboard - they live on the integration's device page under Settings
-> Devices & Services -> GoodWe SEMS Curtailment.

  - Refresh Inverter Info - re-runs discovery (see api.py's
    discover_inverter()). Inverter serial number and rated capacity are
    fixed hardware facts that essentially never change, so this is here
    for the rare case they do (inverter swapped, or the SEMS Portal starts
    reporting something different) - not something to press routinely.

  - Check Inverter Status - queries whether the inverter is currently
    online (see api.py's get_inverter_status()). NOT polled automatically
    anywhere - the SEMS Portal API is unofficial and has been unreliable,
    so checking it on a schedule risks nuisance failures for little
    benefit. Press this when you actually want to know.

  - Send Start Inverter Command / Send Stop Inverter Command - plain button
    presses, not toggles, since starting and stopping the inverter aren't
    symmetric: stopping takes effect quickly, but starting a stopped
    inverter can take a few minutes (grid-sync/ramp-up), so there's no
    single on/off state that stays accurate the instant you press it.
    Independent of curtailment - pressing Send Start Inverter Command does
    not turn Automatic Curtailment or Curtailment Active on, and a stopped
    inverter will just stay stopped through the curtailment automations
    until you either press this or the inverter's own logic brings it back.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import SemsApi, SemsApiError, SemsAuthError
from .const import (
    CONF_INVERTER_CAPACITY_W,
    CONF_INVERTER_SN,
    CONF_POWERSTATION_ID,
    CONF_SEMS_EMAIL,
    CONF_SEMS_PASSWORD,
    CONF_STATION_NAME,
    DATA_STATUS_CHECKED_AT,
    DATA_STATUS_CODE,
    DOMAIN,
    KEY_CHECK_INVERTER_STATUS,
    KEY_INVERTER_CAPACITY_W,
    KEY_REFRESH_INVERTER_INFO,
    KEY_START_INVERTER,
    KEY_STOP_INVERTER,
    SIGNAL_INFO_UPDATED,
    SIGNAL_STATUS_UPDATED,
)
from .entity import SemsEntity

_LOGGER = logging.getLogger(__name__)

REFRESH_INVERTER_INFO = ButtonEntityDescription(
    key=KEY_REFRESH_INVERTER_INFO,
    name="Refresh Inverter Info",
    icon="mdi:refresh",
    entity_category=EntityCategory.CONFIG,
)
CHECK_INVERTER_STATUS = ButtonEntityDescription(
    key=KEY_CHECK_INVERTER_STATUS,
    name="Check Inverter Status",
    icon="mdi:list-status",
    entity_category=EntityCategory.CONFIG,
)
START_INVERTER = ButtonEntityDescription(
    key=KEY_START_INVERTER,
    name="Send Start Inverter Command",
    icon="mdi:play-circle",
    entity_category=EntityCategory.CONFIG,
)
STOP_INVERTER = ButtonEntityDescription(
    key=KEY_STOP_INVERTER,
    name="Send Stop Inverter Command",
    icon="mdi:stop-circle",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the SEMS Portal action buttons."""
    async_add_entities(
        [
            SemsRefreshInverterButton(hass, entry),
            SemsCheckInverterStatusButton(hass, entry),
            SemsStartInverterButton(hass, entry),
            SemsStopInverterButton(hass, entry),
        ]
    )


class _SemsApiButton(SemsEntity, ButtonEntity):
    """Base for buttons that need a SemsApi built from the config entry."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, key: str) -> None:
        super().__init__(entry, key)
        self._hass = hass

    def _api(self) -> SemsApi:
        return SemsApi(
            self._entry.data[CONF_SEMS_EMAIL], self._entry.data[CONF_SEMS_PASSWORD]
        )


class SemsRefreshInverterButton(_SemsApiButton):
    """Re-runs SEMS Portal discovery and updates the config entry."""

    entity_description = REFRESH_INVERTER_INFO

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, REFRESH_INVERTER_INFO.key)

    async def async_press(self) -> None:
        try:
            discovered = await self._hass.async_add_executor_job(
                self._api().discover_inverter
            )
        except SemsAuthError as err:
            raise HomeAssistantError(f"SEMS login failed: {err}") from err
        except SemsApiError as err:
            raise HomeAssistantError(f"Could not refresh inverter info: {err}") from err

        old_sn = self._entry.data.get(CONF_INVERTER_SN)
        old_capacity = self._entry.data.get(CONF_INVERTER_CAPACITY_W)

        self._hass.config_entries.async_update_entry(
            self._entry,
            data={
                **self._entry.data,
                CONF_POWERSTATION_ID: discovered["powerstation_id"],
                CONF_STATION_NAME: discovered["station_name"],
                CONF_INVERTER_SN: discovered["inverter_sn"],
                CONF_INVERTER_CAPACITY_W: discovered["inverter_capacity_w"],
            },
        )

        # Push the freshly-discovered capacity onto its number entity.
        # Necessary because that entity restores its own last value on
        # reload - without writing the new value through first, a rediscovered
        # capacity would be immediately overwritten by the stale restored one.
        # Only this one value is applied: the other sizing numbers are the
        # user's to tune, and this button has no business resetting them.
        if discovered["inverter_capacity_w"] != old_capacity:
            await self._async_apply_capacity(discovered["inverter_capacity_w"])
            _LOGGER.info(
                "SEMS inverter capacity changed from %sW to %sW on refresh",
                old_capacity,
                discovered["inverter_capacity_w"],
            )

        if discovered["inverter_sn"] != old_sn:
            _LOGGER.warning(
                "SEMS inverter serial number changed from %s to %s on refresh",
                old_sn,
                discovered["inverter_sn"],
            )

        # Tell the info sensors to re-read the entry. No config entry
        # reload: a reload would tear down this very button mid-press, and
        # isn't needed since every entity here reads entry.data live.
        async_dispatcher_send(self._hass, SIGNAL_INFO_UPDATED.format(self._entry.entry_id))

    async def _async_apply_capacity(self, value: int) -> None:
        registry = er.async_get(self._hass)
        entity_id = registry.async_get_entity_id(
            "number", DOMAIN, f"{self._entry.entry_id}_{KEY_INVERTER_CAPACITY_W}"
        )
        if entity_id is None:
            return
        await self._hass.services.async_call(
            "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
        )


class SemsCheckInverterStatusButton(_SemsApiButton):
    """Checks whether the inverter is currently online, on demand only."""

    entity_description = CHECK_INVERTER_STATUS

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, CHECK_INVERTER_STATUS.key)

    async def async_press(self) -> None:
        inverter_sn = self._entry.data[CONF_INVERTER_SN]
        try:
            result = await self._hass.async_add_executor_job(
                self._api().get_inverter_status, inverter_sn
            )
        except SemsAuthError as err:
            raise HomeAssistantError(f"SEMS login failed: {err}") from err
        except SemsApiError as err:
            raise HomeAssistantError(f"Could not check inverter status: {err}") from err

        # Stored in the runtime store, not on the config entry: writing to
        # the entry would reload the whole integration on every status
        # check, which is far too heavy for what is just a read.
        store = self._hass.data[DOMAIN][self._entry.entry_id]
        store[DATA_STATUS_CODE] = result["status_code"]
        store[DATA_STATUS_CHECKED_AT] = datetime.now(timezone.utc).isoformat()
        async_dispatcher_send(
            self._hass, SIGNAL_STATUS_UPDATED.format(self._entry.entry_id)
        )


class SemsStartInverterButton(_SemsApiButton):
    """Sends a start command (SaveRemoteControlInverter, InverterStatus=4).

    Starting a stopped inverter is expected to take a few minutes to
    complete (grid-sync/ramp-up) - this call itself returns as soon as the
    SEMS Portal accepts the command, not once the inverter is actually back
    online. Press Check Inverter Status a few minutes later to confirm.
    """

    entity_description = START_INVERTER

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, START_INVERTER.key)

    async def async_press(self) -> None:
        inverter_sn = self._entry.data[CONF_INVERTER_SN]
        try:
            await self._hass.async_add_executor_job(
                self._api().start_inverter, inverter_sn
            )
        except SemsAuthError as err:
            raise HomeAssistantError(f"SEMS login failed: {err}") from err
        except SemsApiError as err:
            raise HomeAssistantError(f"Could not send start command: {err}") from err
        _LOGGER.info(
            "Start command sent for %s. Starting can take a few minutes to "
            "complete - check Inverter Status shortly to confirm.",
            inverter_sn,
        )


class SemsStopInverterButton(_SemsApiButton):
    """Sends a stop command (SaveRemoteControlInverter, InverterStatus=2).

    Expected to take effect quickly, unlike Send Start Inverter Command.
    """

    entity_description = STOP_INVERTER

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, entry, STOP_INVERTER.key)

    async def async_press(self) -> None:
        inverter_sn = self._entry.data[CONF_INVERTER_SN]
        try:
            await self._hass.async_add_executor_job(
                self._api().stop_inverter, inverter_sn
            )
        except SemsAuthError as err:
            raise HomeAssistantError(f"SEMS login failed: {err}") from err
        except SemsApiError as err:
            raise HomeAssistantError(f"Could not send stop command: {err}") from err
        _LOGGER.info("Stop command sent for %s.", inverter_sn)
