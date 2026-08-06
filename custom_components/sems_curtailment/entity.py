"""Shared entity base for the GoodWe SEMS Curtailment integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DEVICE_NAME, DOMAIN


class SemsEntity(Entity):
    """Base entity - groups every switch/number under one SEMS device."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, key: str) -> None:
        self._entry = entry
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=DEVICE_NAME,
            manufacturer="GoodWe",
            model="SEMS Curtailment",
            configuration_url="https://au.semsportal.com",
        )
