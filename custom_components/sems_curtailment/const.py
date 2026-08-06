"""Constants for the GoodWe SEMS Curtailment integration."""

from __future__ import annotations

DOMAIN = "sems_curtailment"
DEVICE_NAME = "SEMS Curtailment"

# -----------------------------------------------------------------------------
# Config entry data - collected once in config_flow.py during "Add
# Integration". Credentials are kept on the config entry and used directly
# by the set_power_limit service (see api.py / __init__.py) - nothing is
# written to secrets.yaml any more.
# -----------------------------------------------------------------------------
CONF_SEMS_EMAIL = "sems_email"
CONF_SEMS_PASSWORD = "sems_password"

# Discovered automatically from the SEMS Portal at setup time (and again
# whenever the Refresh Inverter Info button is pressed) rather than typed
# in by hand - see api.py's discover_inverter().
CONF_POWERSTATION_ID = "powerstation_id"
CONF_INVERTER_SN = "sems_inverter_sn"
CONF_STATION_NAME = "station_name"

# Last-checked inverter status. Lives in the per-entry RUNTIME store
# (hass.data[DOMAIN][entry_id]), not on the config entry - writing it to
# the entry would reload the whole integration on every status check.
# Updated only when the Check Inverter Status button is pressed (see
# button.py); never polled automatically, since the SEMS Portal API is
# unofficial and has been unreliable.
DATA_STATUS_CODE = "status_code"
DATA_STATUS_CHECKED_AT = "status_checked_at"

# Dispatcher signals - button.py sends, sensor.py listens. Formatted with
# the entry_id so multiple config entries don't cross-talk.
SIGNAL_STATUS_UPDATED = f"{DOMAIN}_status_updated_{{}}"
SIGNAL_INFO_UPDATED = f"{DOMAIN}_info_updated_{{}}"

CONF_INVERTER_CAPACITY_W = "inverter_capacity_w"
CONF_BATTERY_MAX_CHARGE_RATE_W = "battery_max_charge_rate_w"
CONF_LOAD_THRESHOLD_W = "load_threshold_w"
CONF_FULL_SOC_THRESHOLD = "full_soc_threshold"

DEFAULT_INVERTER_CAPACITY_W = 10000
DEFAULT_BATTERY_MAX_CHARGE_RATE_W = 4640
DEFAULT_LOAD_THRESHOLD_W = 500
DEFAULT_FULL_SOC_THRESHOLD = 98

MIN_INVERTER_CAPACITY_W = 1000
MAX_INVERTER_CAPACITY_W = 30000
MIN_BATTERY_MAX_CHARGE_RATE_W = 100
MAX_BATTERY_MAX_CHARGE_RATE_W = 10000
MIN_LOAD_THRESHOLD_W = 0
MAX_LOAD_THRESHOLD_W = 5000
MIN_FULL_SOC_THRESHOLD = 90
MAX_FULL_SOC_THRESHOLD = 100

# -----------------------------------------------------------------------------
# Entity keys - switch.py / number.py. Entity IDs are derived by HA from
# DEVICE_NAME + these names (has_entity_name pattern, same as the baseline
# Amber integration), e.g. switch.sems_curtailment_automatic_curtailment.
# -----------------------------------------------------------------------------
KEY_AUTOMATIC_CURTAILMENT = "automatic_curtailment"
KEY_CURTAILMENT_ACTIVE = "curtailment_active"
KEY_LOAD_TRACKING = "load_tracking"

KEY_INVERTER_CAPACITY_W = "inverter_capacity_w"
KEY_BATTERY_MAX_CHARGE_RATE_W = "battery_max_charge_rate_w"
KEY_LOAD_THRESHOLD_W = "load_threshold_w"
KEY_FULL_SOC_THRESHOLD = "full_soc_threshold"
KEY_CURRENT_POWER_LIMIT = "current_power_limit"

# button.py / sensor.py - inverter auto-discovery and status
KEY_REFRESH_INVERTER_INFO = "refresh_inverter_info"
KEY_INVERTER_SN_SENSOR = "inverter_serial_number"
KEY_STATION_NAME_SENSOR = "sems_station"
KEY_CHECK_INVERTER_STATUS = "check_inverter_status"
KEY_INVERTER_STATUS_SENSOR = "inverter_status"

# button.py - raw start/stop commands (SaveRemoteControlInverter with
# InverterStatusSettingMark/InverterStatus - see api.py's _set_status()).
KEY_START_INVERTER = "start_inverter"
KEY_STOP_INVERTER = "stop_inverter"

# Inverter status codes, as reported by GetInverterKvBySnForApp's "status"
# field. Undocumented (no official GoodWe reference), but these three
# values have been directly confirmed by observation rather than inferred.
INVERTER_STATUS_LABELS: dict[str, str] = {
    "-1": "Offline",
    "0": "Waiting",
    "1": "Working",
}

# InverterStatus values for the start/stop command (SaveRemoteControlInverter
# with InverterStatusSettingMark="1") - confirmed by direct observation.
# Distinct from INVERTER_STATUS_LABELS above, which decodes the READ status
# from GetInverterKvBySnForApp / monitor detail - same field name, different
# endpoint, not guaranteed to share the same code space one-for-one.
INVERTER_COMMAND_STOP = "2"
INVERTER_COMMAND_START = "4"

# -----------------------------------------------------------------------------
# Service - registered once, called by the automations/ YAML to change the
# inverter's output limit, instead of the shell_command + standalone
# script earlier versions used. Reads credentials from the config entry.
# -----------------------------------------------------------------------------
SERVICE_SET_POWER_LIMIT = "set_power_limit"
ATTR_LIMIT = "limit"

# SEMS Portal API (au.semsportal.com) - undocumented / reverse-engineered.
# See api.py.
SEMS_LOGIN_URL = "https://au.semsportal.com/api/v1/Common/CrossLogin"
SEMS_SET_POWER_URL = "https://au.semsportal.com/api/PowerStation/SaveRemoteControlInverter"
SEMS_STATION_LIST_URL = "https://au.semsportal.com/api/PowerStationMonitor/QueryPowerStationMonitorForAppDod"
SEMS_MONITOR_DETAIL_URL = "https://au.semsportal.com/api/v3/PowerStation/GetMonitorDetailByPowerstationId"
SEMS_INVERTER_KV_URL = "https://au.semsportal.com/api/v1/PowerStation/GetInverterKvBySnForApp"
