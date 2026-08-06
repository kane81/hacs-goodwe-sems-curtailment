"""Home Assistant GoodWe SEMS Curtailment integration.

Controls GoodWe solar inverter output via the SEMS Portal API based on
Amber Electric pricing, preventing unwanted solar export when prices are
negative.

Requires the baseline Amber integration to be installed and running - the
curtailment automations read Amber price sensors that project provides.

Everything you can see or change lives on this integration's device page:
Settings -> Devices & Services -> GoodWe SEMS Curtailment -> Configuration.
Four platforms are set up here:

  - switch.py: Automatic Curtailment, Curtailment Active, Load Tracking
  - number.py: the five sizing values plus an internal Current Power Limit
    tracker (shown as a slider - see number.py)
  - sensor.py: read-only Inverter Serial Number / SEMS Station / Inverter
    Status
  - button.py: Refresh Inverter Info, Check Inverter Status, Send Start/Stop
    Inverter Command - all on-demand only, none of them polled or shown on
    the dashboard

The config flow (config_flow.py) collects your SEMS Portal login and the
sizing values that AREN'T discoverable (max charge rate, load threshold,
full SOC threshold). Battery capacity is neither typed in nor stored here
- it's read live from the baseline Amber integration's Battery Capacity
sensor at automation runtime. The inverter serial number and rated
capacity are found automatically via api.py's discover_inverter() - see
button.py for how they get refreshed later without re-running the whole
config flow. Credentials stay on the config entry and are used directly by
the set_power_limit service below - nothing is written to secrets.yaml.

install.sh only installs the automations (which call this integration's
services and entities) and, optionally, the dashboard.

Note on where sizing values live: the config entry is only ever the SEED
for the number entities, never an authoritative mirror of them. Once an
entity exists it owns its own value (RestoreEntity), so hand-editing a
number on the device page sticks. async_apply_sizing() below deliberately
runs ONLY when the user explicitly submits the options flow - calling it
on every setup would silently reset hand-tuned values back to whatever was
last typed into that form.
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .api import SemsApi, SemsApiError, SemsAuthError
from .const import (
    ATTR_LIMIT,
    CONF_BATTERY_MAX_CHARGE_RATE_W,
    CONF_FULL_SOC_THRESHOLD,
    CONF_INVERTER_CAPACITY_W,
    CONF_INVERTER_SN,
    CONF_LOAD_THRESHOLD_W,
    CONF_SEMS_EMAIL,
    CONF_SEMS_PASSWORD,
    DOMAIN,
    KEY_BATTERY_MAX_CHARGE_RATE_W,
    KEY_FULL_SOC_THRESHOLD,
    KEY_INVERTER_CAPACITY_W,
    KEY_LOAD_THRESHOLD_W,
    SERVICE_SET_POWER_LIMIT,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

SET_POWER_LIMIT_SCHEMA = vol.Schema(
    {vol.Required(ATTR_LIMIT): vol.All(vol.Coerce(int), vol.Range(min=0, max=100))}
)

# Which number entity each config-entry sizing value seeds. Keyed by entity
# key, valued by config key - both taken from const.py rather than repeated
# as literals, so a rename in one place can't silently desync the two.
SIZING_CONF_KEYS: dict[str, str] = {
    KEY_INVERTER_CAPACITY_W: CONF_INVERTER_CAPACITY_W,
    KEY_BATTERY_MAX_CHARGE_RATE_W: CONF_BATTERY_MAX_CHARGE_RATE_W,
    KEY_LOAD_THRESHOLD_W: CONF_LOAD_THRESHOLD_W,
    KEY_FULL_SOC_THRESHOLD: CONF_FULL_SOC_THRESHOLD,
}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SEMS Curtailment from a config entry."""
    # Runtime store, per entry. Currently just the last inverter status
    # check (see button.py / sensor.py) - deliberately NOT on the config
    # entry, since writing there would trigger a reload on every status
    # check. Also doubles as the "is this entry loaded" marker that
    # async_unload_entry checks before tearing the shared service down.
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        # Only drop the shared service once the LAST entry goes away -
        # previously this checked a dict that was never populated, so it
        # fired on any unload and broke the service for remaining entries.
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_SET_POWER_LIMIT)
    return unloaded


async def async_apply_sizing(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Push the config entry's sizing values onto the number entities.

    Called only from the options flow, on explicit form submission - see
    the module docstring for why this must not run on every setup. (The
    Refresh Inverter Info button updates the inverter capacity number too,
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


def _async_register_services(hass: HomeAssistant) -> None:
    """Register set_power_limit, once, shared by every config entry."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_POWER_LIMIT):
        return

    async def handle_set_power_limit(call: ServiceCall) -> dict | None:
        limit = call.data[ATTR_LIMIT]
        entries = [
            e
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id in hass.data.get(DOMAIN, {})
        ]
        if not entries:
            raise HomeAssistantError(
                "No GoodWe SEMS Curtailment integration is configured"
            )
        entry = entries[0]
        api = SemsApi(entry.data[CONF_SEMS_EMAIL], entry.data[CONF_SEMS_PASSWORD])
        try:
            await hass.async_add_executor_job(
                api.set_power_limit, entry.data[CONF_INVERTER_SN], limit
            )
        except SemsApiError as err:
            # SemsAuthError is a SemsApiError subclass, so both land here.
            message = (
                f"SEMS login failed: {err}"
                if isinstance(err, SemsAuthError)
                else str(err)
            )
            if call.return_response:
                return {"success": False, "message": message}
            # Fire-and-forget caller: returning a dict nobody reads would
            # swallow the failure invisibly - raise so it lands in the
            # automation trace and the log instead.
            raise HomeAssistantError(message) from err
        if call.return_response:
            return {"success": True, "message": f"Inverter limit set to {limit}%"}
        return None

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_POWER_LIMIT,
        handle_set_power_limit,
        schema=SET_POWER_LIMIT_SCHEMA,
        # OPTIONAL, not ONLY: with ONLY, Home Assistant rejects any call
        # that doesn't ask for a response, which broke the one automation
        # (sems_curtailment_disable) that fires and forgets.
        supports_response=SupportsResponse.OPTIONAL,
    )
