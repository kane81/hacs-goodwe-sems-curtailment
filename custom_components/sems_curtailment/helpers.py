"""Shared helpers that both __init__.py and config_flow.py need.

Kept in a separate module to avoid the circular import that would occur if
config_flow.py imported from __init__.py (HA loads config_flow.py before
the integration's async_setup_entry runs, so __init__.py is mid-import
at that point).
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_BATTERY_MAX_CHARGE_RATE_W,
    CONF_FULL_SOC_THRESHOLD,
    CONF_INVERTER_CAPACITY_W,
    CONF_LOAD_THRESHOLD_W,
    DOMAIN,
    KEY_BATTERY_MAX_CHARGE_RATE_W,
    KEY_FULL_SOC_THRESHOLD,
    KEY_INVERTER_CAPACITY_W,
    KEY_LOAD_THRESHOLD_W,
)

_LOGGER = logging.getLogger(__name__)

# Which number entity each config-entry sizing value seeds.
SIZING_CONF_KEYS: dict[str, str] = {
    KEY_INVERTER_CAPACITY_W: CONF_INVERTER_CAPACITY_W,
    KEY_BATTERY_MAX_CHARGE_RATE_W: CONF_BATTERY_MAX_CHARGE_RATE_W,
    KEY_LOAD_THRESHOLD_W: CONF_LOAD_THRESHOLD_W,
    KEY_FULL_SOC_THRESHOLD: CONF_FULL_SOC_THRESHOLD,
}


async def async_apply_sizing(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Push the config entry's sizing values onto the number entities.

    Called only from the options flow, on explicit form submission - see
    __init__.py's module docstring for why this must not run on every setup.
    (The Refresh Inverter Info button updates the inverter capacity number too,
    but through its own capacity-only helper in button.py, deliberately not
    this function - refreshing discovery shouldn't reset the user's other
    hand-tuned values.)

    Entities are looked up via the registry by unique_id rather than by a
    guessed entity_id, since the user is free to rename them.
    """
    registry = er.async_get(hass)
    for entity_key, conf_key in SIZING_CONF_KEYS.items():
        if conf_key not in entry.data:
            continue
        entity_id = registry.async_get_entity_id(
            "number", DOMAIN, f"{entry.entry_id}_{entity_key}"
        )
        if entity_id is None:
            continue
        try:
            await hass.services.async_call(
                "number",
                "set_value",
                {"entity_id": entity_id, "value": entry.data[conf_key]},
                blocking=True,
            )
        except (HomeAssistantError, vol.Invalid):
            _LOGGER.warning("Could not apply sizing value to %s", entity_id)
