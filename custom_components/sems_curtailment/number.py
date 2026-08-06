"""Number entities for GoodWe SEMS Curtailment.

Six numbers, all RestoreEntity so a value survives a restart:

  - Five sizing values, seeded from the config flow (config_flow.py) the
    first time each entity is ever created. After that, RestoreEntity wins
    on every subsequent restart - editing the entity directly (here, or via
    the options flow, which re-applies the config entry's current values)
    is what changes it from then on, not the config entry.
  - Current Power Limit, an internal value with no config-flow default,
    always starts at 100 (%) and is written by the curtailment automations
    via number.set_value whenever they change the inverter's actual output
    limit, so they can tell whether a change is actually needed before
    calling the SEMS API.

These replace v1/early-v2's input_number helpers - they now live on the
integration's device page instead of Settings -> Helpers.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_BATTERY_MAX_CHARGE_RATE_W,
    CONF_FULL_SOC_THRESHOLD,
    CONF_INVERTER_CAPACITY_W,
    CONF_LOAD_THRESHOLD_W,
    DEFAULT_BATTERY_MAX_CHARGE_RATE_W,
    DEFAULT_FULL_SOC_THRESHOLD,
    DEFAULT_INVERTER_CAPACITY_W,
    DEFAULT_LOAD_THRESHOLD_W,
    KEY_BATTERY_MAX_CHARGE_RATE_W,
    KEY_CURRENT_POWER_LIMIT,
    KEY_FULL_SOC_THRESHOLD,
    KEY_INVERTER_CAPACITY_W,
    KEY_LOAD_THRESHOLD_W,
    MAX_BATTERY_MAX_CHARGE_RATE_W,
    MAX_FULL_SOC_THRESHOLD,
    MAX_INVERTER_CAPACITY_W,
    MAX_LOAD_THRESHOLD_W,
    MIN_BATTERY_MAX_CHARGE_RATE_W,
    MIN_FULL_SOC_THRESHOLD,
    MIN_INVERTER_CAPACITY_W,
    MIN_LOAD_THRESHOLD_W,
)
from .entity import SemsEntity


@dataclass(frozen=True, kw_only=True)
class SemsNumberDescription(NumberEntityDescription):
    """Describes a SEMS number entity."""

    conf_key: str | None  # config entry key this seeds from, or None
    default: float


SIZING_NUMBERS: tuple[SemsNumberDescription, ...] = (
    SemsNumberDescription(
        key=KEY_INVERTER_CAPACITY_W,
        name="Inverter Capacity",
        icon="mdi:solar-power",
        native_min_value=MIN_INVERTER_CAPACITY_W,
        native_max_value=MAX_INVERTER_CAPACITY_W,
        native_step=100,
        native_unit_of_measurement="W",
        mode=NumberMode.BOX,
        conf_key=CONF_INVERTER_CAPACITY_W,
        default=DEFAULT_INVERTER_CAPACITY_W,
    ),
    SemsNumberDescription(
        key=KEY_BATTERY_MAX_CHARGE_RATE_W,
        name="Battery Max Charge Rate",
        icon="mdi:battery-charging-high",
        native_min_value=MIN_BATTERY_MAX_CHARGE_RATE_W,
        native_max_value=MAX_BATTERY_MAX_CHARGE_RATE_W,
        native_step=10,
        native_unit_of_measurement="W",
        mode=NumberMode.BOX,
        conf_key=CONF_BATTERY_MAX_CHARGE_RATE_W,
        default=DEFAULT_BATTERY_MAX_CHARGE_RATE_W,
    ),
    SemsNumberDescription(
        key=KEY_LOAD_THRESHOLD_W,
        name="Load Change Threshold",
        icon="mdi:swap-vertical",
        native_min_value=MIN_LOAD_THRESHOLD_W,
        native_max_value=MAX_LOAD_THRESHOLD_W,
        native_step=50,
        native_unit_of_measurement="W",
        mode=NumberMode.BOX,
        conf_key=CONF_LOAD_THRESHOLD_W,
        default=DEFAULT_LOAD_THRESHOLD_W,
    ),
    SemsNumberDescription(
        key=KEY_FULL_SOC_THRESHOLD,
        name="Full SOC Threshold",
        icon="mdi:battery-heart-variant",
        native_min_value=MIN_FULL_SOC_THRESHOLD,
        native_max_value=MAX_FULL_SOC_THRESHOLD,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        conf_key=CONF_FULL_SOC_THRESHOLD,
        default=DEFAULT_FULL_SOC_THRESHOLD,
    ),
)

CURRENT_POWER_LIMIT = SemsNumberDescription(
    key=KEY_CURRENT_POWER_LIMIT,
    # Solar output is adjusted to match load - shown as a slider (rather
    # than a box) so the current curtailment target is visually obvious at
    # a glance on the integration's device page. Not on the dashboard by
    # design - it's an internal value the automations track, not something
    # meant for everyday use; see lovelace/sems.yaml's Status card instead
    # for the human-readable "Curtailment OFF/ACTIVE - Solar at X%" line.
    name="Current Power Limit",
    icon="mdi:speedometer",
    native_min_value=0,
    native_max_value=100,
    native_step=1,
    native_unit_of_measurement=PERCENTAGE,
    mode=NumberMode.SLIDER,
    conf_key=None,
    default=100,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the sizing numbers and the internal power-limit tracker."""
    entities = [SemsNumber(entry, description) for description in SIZING_NUMBERS]
    entities.append(SemsNumber(entry, CURRENT_POWER_LIMIT))
    async_add_entities(entities)


class SemsNumber(SemsEntity, NumberEntity, RestoreEntity):
    """A stored numeric value that restores across a restart.

    Seeded from the config entry (entry.data[conf_key]) only when this
    entity is created for the very first time and has no prior restored
    state - every restart after that uses whatever RestoreEntity finds,
    same as the input_number helpers this replaces.
    """

    entity_description: SemsNumberDescription

    def __init__(self, entry: ConfigEntry, description: SemsNumberDescription) -> None:
        super().__init__(entry, description.key)
        self.entity_description = description
        self._attr_native_value = description.default

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("unknown", "unavailable", None):
            try:
                self._attr_native_value = float(last.state)
                return
            except ValueError:
                pass
        # No prior state - first-ever creation. Seed from the config entry
        # if this number has a conf_key (sizing values do; Current Power
        # Limit doesn't and just uses its hardcoded default of 100).
        conf_key = self.entity_description.conf_key
        if conf_key is not None and conf_key in self._entry.data:
            self._attr_native_value = self._entry.data[conf_key]

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
