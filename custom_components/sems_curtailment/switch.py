"""Switch entities for GoodWe SEMS Curtailment.

Three switches, all plain on/off toggles that restore their state across a
restart (RestoreEntity) and default to OFF on first creation, so a fresh
install never starts moving the inverter on its own:

  - Automatic Curtailment - master switch. ON = the price-driven
    sems_curtailment automation runs continuously.
  - Curtailment Active - ON whenever the inverter is currently curtailed
    below 100%. Set automatically by sems_curtailment.yaml while Automatic
    Curtailment is on; toggle it by hand while Automatic Curtailment is off
    to drive curtailment manually - see sems_curtailment_manual.yaml.
  - Load Tracking - while Curtailment Active is on, fine-tunes the limit in
    real time as load/battery change, rather than only reacting to the next
    Amber price update.

These replace v1/early-v2's input_boolean helpers - they now live on the
integration's device page instead of Settings -> Helpers.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    KEY_AUTOMATIC_CURTAILMENT,
    KEY_CURTAILMENT_ACTIVE,
    KEY_LOAD_TRACKING,
)
from .entity import SemsEntity


@dataclass(frozen=True, kw_only=True)
class SemsSwitchDescription(SwitchEntityDescription):
    """Describes a SEMS switch entity."""


SWITCHES: tuple[SemsSwitchDescription, ...] = (
    SemsSwitchDescription(
        key=KEY_AUTOMATIC_CURTAILMENT,
        name="Automatic Curtailment",
        icon="mdi:solar-power",
    ),
    SemsSwitchDescription(
        key=KEY_CURTAILMENT_ACTIVE,
        name="Curtailment Active",
        icon="mdi:solar-power-variant",
    ),
    SemsSwitchDescription(
        key=KEY_LOAD_TRACKING,
        name="Load Tracking",
        icon="mdi:chart-line",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the three curtailment switches."""
    async_add_entities(SemsSwitch(entry, description) for description in SWITCHES)


class SemsSwitch(SemsEntity, SwitchEntity, RestoreEntity):
    """A plain on/off toggle that restores its state across a restart."""

    entity_description: SemsSwitchDescription
    _attr_is_on = False

    def __init__(self, entry: ConfigEntry, description: SemsSwitchDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._attr_is_on = last.state == "on"

    async def async_turn_on(self, **kwargs) -> None:
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._attr_is_on = False
        self.async_write_ha_state()
