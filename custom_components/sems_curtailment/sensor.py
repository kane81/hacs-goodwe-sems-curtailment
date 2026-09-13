"""Diagnostic sensors for GoodWe SEMS Curtailment.

Four read-only sensors. None of them poll - each re-renders when told to
via a dispatcher signal from button.py:

  - Inverter Serial Number / SEMS Station: read live from the config
    entry, which discover_inverter() populates at setup and the Refresh
    Inverter Info button updates later.
  - Inverter Status / Remote Control Enabled: read from the per-entry
    runtime store, which only the Check Inverter Status button writes.
    Restores its last value across a restart (RestoreEntity) so a reboot
    doesn't throw away the last known status - the runtime store itself is
    memory-only.

Remote Control Enabled exists because of a real, confirmed failure mode:
the SEMS Portal can return a clean success response for a command
(set_power_limit, start_inverter, stop_inverter) that never actually
reaches the inverter - there's no error to catch, because the portal
genuinely did accept the command, it just didn't forward it. The portal's
own "canStartIV" flag on the account/inverter appears to gate this, and
this sensor is the only warning you'll get before assuming a command
worked when it didn't.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_INVERTER_SN,
    CONF_STATION_NAME,
    DATA_REMOTE_CONTROL_ENABLED,
    DATA_STATUS_CHECKED_AT,
    DATA_STATUS_CODE,
    DOMAIN,
    INVERTER_STATUS_LABELS,
    KEY_INVERTER_SN_SENSOR,
    KEY_INVERTER_STATUS_SENSOR,
    KEY_STATION_NAME_SENSOR,
    SIGNAL_INFO_UPDATED,
    SIGNAL_STATUS_UPDATED,
)
from .entity import SemsEntity

ATTR_STATUS_CODE = "status_code"
ATTR_CHECKED_AT = "checked_at"
STATUS_UNKNOWN = "Unknown"
KEY_REMOTE_CONTROL_SENSOR = "remote_control_enabled"


@dataclass(frozen=True, kw_only=True)
class SemsSensorDescription(SensorEntityDescription):
    """Describes a SEMS diagnostic sensor."""

    conf_key: str


INFO_SENSORS: tuple[SemsSensorDescription, ...] = (
    SemsSensorDescription(
        key=KEY_INVERTER_SN_SENSOR,
        name="Inverter Serial Number",
        icon="mdi:identifier",
        entity_category=EntityCategory.DIAGNOSTIC,
        conf_key=CONF_INVERTER_SN,
    ),
    SemsSensorDescription(
        key=KEY_STATION_NAME_SENSOR,
        name="SEMS Station",
        icon="mdi:map-marker",
        entity_category=EntityCategory.DIAGNOSTIC,
        conf_key=CONF_STATION_NAME,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the discovery-info sensors and the two on-demand sensors."""
    entities: list[SensorEntity] = [
        SemsInfoSensor(entry, description) for description in INFO_SENSORS
    ]
    entities.append(SemsInverterStatusSensor(hass, entry))
    entities.append(SemsRemoteControlEnabledSensor(hass, entry))
    async_add_entities(entities)


class SemsInfoSensor(SemsEntity, SensorEntity):
    """Reflects one value from the config entry's last discovery result."""

    entity_description: SemsSensorDescription

    def __init__(self, entry: ConfigEntry, description: SemsSensorDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_INFO_UPDATED.format(self._entry.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        return self._entry.data.get(self.entity_description.conf_key)


class SemsInverterStatusSensor(SemsEntity, SensorEntity, RestoreEntity):
    """Shows the inverter's status as of the last Check Inverter Status press.

    "Unknown" until that button has been pressed at least once - there is
    no automatic value, by design.
    """

    _attr_name = "Inverter Status"
    _attr_icon = "mdi:list-status"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(entry, KEY_INVERTER_STATUS_SENSOR)
        self._store: dict[str, Any] = hass.data[DOMAIN][entry.entry_id]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Seed the (memory-only) runtime store from the last restored
        # state, so a restart shows the last known status rather than
        # resetting to Unknown until the button is pressed again.
        if DATA_STATUS_CODE not in self._store:
            last = await self.async_get_last_state()
            if last is not None and last.state != STATUS_UNKNOWN:
                code = last.attributes.get(ATTR_STATUS_CODE)
                if code is not None:
                    self._store[DATA_STATUS_CODE] = code
                    self._store[DATA_STATUS_CHECKED_AT] = last.attributes.get(
                        ATTR_CHECKED_AT
                    )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_STATUS_UPDATED.format(self._entry.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        code = self._store.get(DATA_STATUS_CODE)
        if code is None:
            return STATUS_UNKNOWN
        return INVERTER_STATUS_LABELS.get(code, f"{STATUS_UNKNOWN} ({code})")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            ATTR_STATUS_CODE: self._store.get(DATA_STATUS_CODE),
            ATTR_CHECKED_AT: self._store.get(DATA_STATUS_CHECKED_AT),
        }


class SemsRemoteControlEnabledSensor(SemsEntity, SensorEntity, RestoreEntity):
    """Whether the SEMS Portal has remote control enabled for this inverter.

    "Unknown" until Check Inverter Status has been pressed at least once,
    same as Inverter Status - see the module docstring for why this
    sensor exists at all: it's the one warning available for a command
    that the portal accepts and acknowledges but never actually delivers.
    """

    _attr_name = "Remote Control Enabled"
    _attr_icon = "mdi:remote"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(entry, KEY_REMOTE_CONTROL_SENSOR)
        self._store: dict[str, Any] = hass.data[DOMAIN][entry.entry_id]

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if DATA_REMOTE_CONTROL_ENABLED not in self._store:
            last = await self.async_get_last_state()
            if last is not None and last.state != STATUS_UNKNOWN:
                self._store[DATA_REMOTE_CONTROL_ENABLED] = last.state == "Enabled"
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_STATUS_UPDATED.format(self._entry.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> str:
        value = self._store.get(DATA_REMOTE_CONTROL_ENABLED)
        if value is None:
            return STATUS_UNKNOWN
        return "Enabled" if value else "Disabled"
