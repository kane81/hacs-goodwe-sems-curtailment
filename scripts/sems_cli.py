#!/usr/bin/env python3
# =============================================================================
# sems_cli.py - Standalone GoodWe SEMS Portal API tool
# =============================================================================
#
# A developer/debugging tool for making ad-hoc calls against GoodWe's SEMS
# Portal API - the same one this project's Home Assistant integration uses,
# but callable directly from a terminal without going through HA at all.
# Nothing in this project depends on this script; it exists purely for
# exploring the API and testing things by hand.
#
# Every endpoint below is the same one used by
# custom_components/sems_curtailment/api.py (the code your installed
# integration actually runs). This file deliberately duplicates that logic
# rather than importing it, so it can be copied to any machine and run on
# its own - the tradeoff is that if api.py's endpoints ever change, this
# will drift out of sync; check api.py first if a command here starts
# behaving differently from the integration.
#
# -----------------------------------------------------------------------------
# Setup
#
# No dependencies - standard library only, Python 3.9+.
#
# Credentials come from environment variables, not a config file or a
# command-line argument, so they don't end up in your shell history or in a
# process list. Use SINGLE quotes, not double quotes:
#   export SEMS_EMAIL='you@example.com'
#   export SEMS_PASSWORD='your sems portal password'
#
# Why single quotes: in bash/zsh, a $ inside DOUBLE quotes tries to expand a
# variable. A password like 'VJ9CeF05e$rkm5F' silently becomes
# 'VJ9CeF05eF' (bash treats $rkm5F as an undefined variable and expands it
# to empty) - no error, just a corrupted password and a confusing login
# failure. Single quotes disable that expansion entirely, so the password
# is used exactly as typed no matter what characters it contains.
#
# Optional - skips the station/inverter lookup on commands that need a
# serial number, saving two API calls per invocation:
#   export SEMS_INVERTER_SN='5010KMST226W0066'
#
# -----------------------------------------------------------------------------
# Usage:
#   python3 sems_cli.py <command> [args]
#
# Commands:
#   discover [serial_number] - Power station and inverter this account
#                            owns: station name/id, inverter serial, model
#                            and rated capacity. Same lookup the
#                            integration's config flow and Refresh Inverter
#                            Info button do. If the account-level station
#                            list comes back empty (a known, confirmed
#                            intermittent SEMS Portal issue), pass the
#                            serial number directly (from the inverter's
#                            label or the SEMS+ app) to look it up without
#                            the station list at all.
#   stations              - List every power station on the account (the
#                            integration only ever uses the first).
#   status                - Whether the inverter is online, plus model,
#                            capacity and when it last reported in.
#   detail                - Live snapshot: PV/battery/grid/load power, SOC,
#                            today's and total generation, and the current
#                            curtailment (power limit) state.
#   limit <percent>       - Set the inverter's active power output limit,
#                            0-100. This is the same call the integration's
#                            curtailment automations make.
#   start                 - Send a start command. Asks for confirmation
#                            first (skip with -y/--yes).
#   stop                  - Send a stop command. Asks for confirmation
#                            first (skip with -y/--yes).
#   raw <endpoint> [json] - POST an arbitrary body to one of the known
#                            endpoint names (login, stations, detail,
#                            inverter, setpower) and pretty-print the raw
#                            JSON response. For poking at fields this tool
#                            doesn't surface yet.
#
# WARNING: "limit", "start" and "stop" change your inverter's actual
# behaviour. "limit 0" does not switch the inverter off - it drops output
# to near zero, and a small amount of power still passes through; "stop"
# is the actual off switch. None of these tell Home Assistant about the
# change, so if the curtailment automations are running they may overwrite
# a limit you set here on their next evaluation - turn Automatic
# Curtailment off first if you want it to stick. Starting a stopped
# inverter can take a few minutes to complete; stopping is quick.
#
# Examples:
#   python3 sems_cli.py discover
#   python3 sems_cli.py discover 5010KMST226W0066   # station list is empty
#   python3 sems_cli.py status
#   python3 sems_cli.py detail
#   python3 sems_cli.py limit 50
#   python3 sems_cli.py stop --yes
#   python3 sems_cli.py raw inverter '{"sn": "5010KMST226W0066"}'
#
# DISCLAIMER: The SEMS Portal API is not publicly documented or officially
# supported by GoodWe, and may change or be withdrawn without notice.
# =============================================================================

from __future__ import annotations

import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime

# -----------------------------------------------------------------------------
# Endpoints - kept identical to const.py's SEMS_* URLs.
# -----------------------------------------------------------------------------

LOGIN_URL = "https://au.semsportal.com/api/v1/Common/CrossLogin"
SET_POWER_URL = "https://au.semsportal.com/api/PowerStation/SaveRemoteControlInverter"
STATION_LIST_URL = "https://au.semsportal.com/api/PowerStationMonitor/QueryPowerStationMonitorForAppDod"
MONITOR_DETAIL_URL = "https://au.semsportal.com/api/v3/PowerStation/GetMonitorDetailByPowerstationId"
INVERTER_KV_URL = "https://au.semsportal.com/api/v1/PowerStation/GetInverterKvBySnForApp"

RAW_ENDPOINTS = {
    "login": LOGIN_URL,
    "stations": STATION_LIST_URL,
    "detail": MONITOR_DETAIL_URL,
    "inverter": INVERTER_KV_URL,
    "setpower": SET_POWER_URL,
}

# Inferred, not documented - matches const.INVERTER_STATUS_LABELS.
STATUS_LABELS = {"-1": "Offline", "0": "Waiting", "1": "Working"}

# InverterStatus values for the start/stop command - distinct from
# STATUS_LABELS above, which decodes the READ status from a different
# endpoint. Same field name, not guaranteed to share the same code space.
COMMAND_STOP = "2"
COMMAND_START = "4"

CLIENT_HEADER = {"client": "ios", "version": "v3.7.9", "language": "en"}


# -----------------------------------------------------------------------------
# Transport
# -----------------------------------------------------------------------------


def _ssl_context() -> ssl.SSLContext:
    """SEMS Portal needs certificate verification disabled."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def post(url: str, body: dict, token: str) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Token": token},
    )
    try:
        with urllib.request.urlopen(req, context=_ssl_context(), timeout=30) as resp:
            return json.loads(resp.read())
    except (TimeoutError, urllib.error.URLError) as err:
        reason = err if isinstance(err, TimeoutError) else err
        if isinstance(err, urllib.error.URLError) and isinstance(err.reason, TimeoutError):
            reason = err.reason
        if isinstance(reason, TimeoutError):
            die("SEMS Portal timed out. The portal is known to be intermittently"
                " slow - wait a moment and try again.")
        die(f"Could not reach SEMS Portal: {err}")
    except json.JSONDecodeError as err:
        die(f"SEMS Portal returned something that isn't JSON: {err}")


def check(data: dict, what: str) -> dict:
    """The portal returns `code` as int 0 on some endpoints, string "0" on
    others, so this compares as a string."""
    if str(data.get("code")) != "0":
        die(f"{what} failed: {data.get('msg') or data.get('code')}")
    return data


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def confirm(action: str) -> None:
    """Ask before a command that changes real inverter behaviour.

    Skipped with -y/--yes anywhere on the command line, for scripting or if
    you'd rather not be asked. start/stop don't consume any other
    positional arguments, so this doesn't need to be stripped from argv
    before dispatch - if that ever changes, revisit this.
    """
    if "-y" in sys.argv or "--yes" in sys.argv:
        return
    reply = input(f"About to {action}. Continue? [y/N]: ").strip().lower()
    if reply != "y":
        print("Aborted.")
        sys.exit(0)


def login(email: str, password: str) -> str:
    """Return the Token header value for subsequent calls."""
    seed = json.dumps({"uid": "", "timestamp": 0, "token": "", **CLIENT_HEADER})
    data = post(LOGIN_URL, {"account": email, "pwd": password, "is_local": False}, seed)
    if str(data.get("code")) != "0":
        # Deliberately NOT conditional on "$" appearing in `password` here:
        # if a double-quoted export already corrupted it, the $ and
        # everything after it is gone by the time Python sees this value -
        # there is no way to detect the corruption after the fact, so the
        # only useful thing to do is always mention it as a possibility.
        die(
            f"Login failed: {data.get('msg')} - check SEMS_EMAIL and "
            f"SEMS_PASSWORD. If your password contains '$', make sure you "
            f"exported it with SINGLE quotes (export SEMS_PASSWORD='...') - "
            f"double quotes let the shell silently eat part of it."
        )
    d = data["data"]
    return json.dumps(
        {"uid": d["uid"], "timestamp": d["timestamp"], "token": d["token"], **CLIENT_HEADER}
    )


# -----------------------------------------------------------------------------
# Lookups
# -----------------------------------------------------------------------------


def get_stations(token: str) -> list[dict]:
    body = {
        "page_size": "10",
        "orderby": "",
        "powerstation_status": "",
        "key": "",
        "page_index": "1",
        "powerstation_id": "",
        "powerstation_type": "",
    }
    data = check(post(STATION_LIST_URL, body, token), "Power station lookup")
    return (data.get("data") or {}).get("list") or []


def get_detail(token: str, powerstation_id: str) -> dict:
    data = check(
        post(MONITOR_DETAIL_URL, {"Version": "v4", "powerStationId": powerstation_id}, token),
        "Monitor detail lookup",
    )
    return data.get("data") or {}


def get_inverter_kv(token: str, sn: str) -> dict:
    data = check(post(INVERTER_KV_URL, {"sn": sn}, token), "Inverter status check")
    return data.get("data") or {}


def dict_value(inverter: dict, key: str) -> str | None:
    """Pull a value out of the inverter's dict.left/right key-value lists."""
    for side in ("left", "right"):
        for item in (inverter.get("dict") or {}).get(side) or []:
            if item.get("key") == key:
                return item.get("value")
    return None


def discover_by_serial(token: str, sn: str) -> dict:
    """Capacity + model directly by serial number, without the station
    list. Fallback for when the station list returns empty - a real,
    confirmed SEMS Portal failure mode (Sept 2026), not hypothetical: this
    endpoint is keyed purely by serial number and keeps working regardless
    of whether the account-level station list is behaving.
    """
    kv = get_inverter_kv(token, sn)
    capacity_kw = None
    capacity_str = kv.get("capacity")
    if capacity_str:
        m = re.match(r"\s*([\d.]+)\s*kW", capacity_str, re.IGNORECASE)
        if m:
            try:
                capacity_kw = float(m.group(1))
            except ValueError:
                capacity_kw = None
    return {
        "station_name": None,
        "powerstation_id": None,
        "address": None,
        "inverter_sn": sn,
        "model": kv.get("model"),
        "capacity_kw": capacity_kw,
    }


def discover(token: str) -> dict:
    """Station + first inverter, mirroring api.py's discover_inverter()."""
    stations = get_stations(token)
    if not stations:
        die("No power stations found on this SEMS Portal account")
    station = stations[0]
    detail = get_detail(token, station["powerstation_id"])
    inverters = detail.get("inverter") or []
    if not inverters:
        die(f"No inverters found on power station '{station.get('stationname')}'")
    inverter = inverters[0]

    capacity_kw = dict_value(inverter, "capacity")
    try:
        capacity_kw = float(capacity_kw)
    except (TypeError, ValueError):
        try:
            capacity_kw = float(inverter.get("capacity"))
        except (TypeError, ValueError):
            capacity_kw = None

    return {
        "powerstation_id": station["powerstation_id"],
        "station_name": station.get("stationname", ""),
        "address": (detail.get("info") or {}).get("address", ""),
        "inverter_sn": inverter.get("sn"),
        "model": inverter.get("type") or dict_value(inverter, "dmDeviceType"),
        "capacity_kw": capacity_kw,
        "detail": detail,
        "inverter": inverter,
    }


def resolve_sn(token: str) -> str:
    """Inverter serial from the environment if set, else via discovery."""
    sn = os.environ.get("SEMS_INVERTER_SN")
    if sn:
        return sn.strip()
    return discover(token)["inverter_sn"]


# -----------------------------------------------------------------------------
# Actions
# -----------------------------------------------------------------------------


def _command_date() -> str:
    """Plain slashes: the SEMS app's own payloads show the JSON escape \\/
    in the raw request text, which parses to a plain / - not a literal
    backslash in the value."""
    return datetime.now().strftime("%m/%d/%Y %H:%M:%S")


def set_power_limit(token: str, sn: str, percent: int) -> dict:
    body = {
        "InverterSN": sn,
        "InverterRemotingLastSetDate": _command_date(),
        "ActivePowerLimit": str(percent),
        "ActivePowerLimitSettingMark": "1",
    }
    response = post(SET_POWER_URL, body, token)
    check(response, "Set power limit")
    return response


def _set_status(token: str, sn: str, status_code: str) -> dict:
    body = {
        "InverterSN": sn,
        "InverterRemotingLastSetDate": _command_date(),
        "InverterStatusSettingMark": "1",
        "InverterStatus": status_code,
    }
    response = post(SET_POWER_URL, body, token)
    check(response, "Set inverter status")
    return response


def start_inverter(token: str, sn: str) -> dict:
    """Starting a stopped inverter can take a few minutes to complete
    (grid-sync/ramp-up) - this call returns as soon as the portal accepts
    it, not once the inverter is actually back online."""
    return _set_status(token, sn, COMMAND_START)


def stop_inverter(token: str, sn: str) -> dict:
    """Expected to take effect quickly, unlike start_inverter()."""
    return _set_status(token, sn, COMMAND_STOP)


# -----------------------------------------------------------------------------
# Output helpers
# -----------------------------------------------------------------------------


def fmt(label: str, value) -> None:
    print(f"{label + ':':<22}{value}")


def cmd_discover(token: str, sn_arg: str | None = None) -> None:
    if sn_arg:
        d = discover_by_serial(token, sn_arg.strip())
        print("(using serial-number-only lookup - station list not queried)")
    else:
        try:
            d = discover(token)
        except SystemExit:
            print(
                "\nAutomatic discovery failed. If you already know your inverter's "
                "serial number (on the inverter's label, or in the SEMS+ app), try:\n"
                f"  python3 {os.path.basename(sys.argv[0])} discover <serial_number>"
            )
            raise
    if d["station_name"]:
        fmt("Station", d["station_name"])
    if d["powerstation_id"]:
        fmt("Station ID", d["powerstation_id"])
    if d.get("address"):
        fmt("Address", d["address"])
    fmt("Inverter SN", d["inverter_sn"])
    fmt("Model", d["model"] or "unknown")
    if d["capacity_kw"] is not None:
        fmt("Rated capacity", f"{d['capacity_kw']:g} kW ({int(d['capacity_kw'] * 1000)} W)")
    else:
        fmt("Rated capacity", "could not determine")


def cmd_stations(token: str) -> None:
    stations = get_stations(token)
    if not stations:
        print("No power stations on this account.")
        return
    print(f"{len(stations)} power station(s):")
    for i, s in enumerate(stations):
        marker = "  <- used by the integration" if i == 0 else ""
        print(f"\n  {s.get('stationname')}{marker}")
        print(f"    id:       {s.get('powerstation_id')}")
        print(f"    capacity: {s.get('capacity')} kW")
        print(f"    status:   {STATUS_LABELS.get(str(s.get('status')), s.get('status'))}")
        print(f"    location: {s.get('location', '')}")


def cmd_status(token: str) -> None:
    sn = resolve_sn(token)
    kv = get_inverter_kv(token, sn)
    code = str(kv.get("status"))
    remote_control = kv.get("canStartIV")
    fmt("Inverter SN", sn)
    fmt("Status", f"{STATUS_LABELS.get(code, 'Unknown')} (code {code})")
    fmt(
        "Remote control",
        "Unknown" if remote_control is None else ("Enabled" if remote_control else "Disabled"),
    )
    fmt("Model", kv.get("model"))
    fmt("Capacity", kv.get("capacity"))
    fmt("Last reported", kv.get("last_refresh_time"))
    for col in kv.get("cols") or []:
        if col.get("key") in ("Power", "Total Generation", "Fault Message"):
            fmt(col["key"], col.get("value"))
    if code == "-1":
        print(
            "\nNote: an offline inverter usually just means it isn't generating "
            "(overnight, or no sun) - the SEMS datalogger stops reporting. It "
            "does not on its own indicate a fault."
        )
    if remote_control is False:
        print(
            "\nWARNING: Remote control is DISABLED for this inverter on your "
            "SEMS Portal account. 'limit', 'start' and 'stop' will likely "
            "return success from the portal without the command ever "
            "reaching the inverter - this is a known silent-failure mode, "
            "not a bug in this tool. Contact your installer or GoodWe "
            "support to have remote control enabled for this device."
        )


def cmd_detail(token: str) -> None:
    d = discover(token)
    detail = d["detail"]
    inverter = d["inverter"]
    flow = detail.get("powerflow") or {}
    kpi = detail.get("kpi") or {}

    fmt("Station", d["station_name"])
    fmt("Inverter SN", d["inverter_sn"])
    fmt("Status", STATUS_LABELS.get(str(inverter.get("status")), inverter.get("status")))
    print()
    fmt("PV", flow.get("pv"))
    fmt("Battery", flow.get("bettery"))  # sic - the portal's own spelling
    fmt("Battery SOC", flow.get("socText"))
    fmt("Load", flow.get("load"))
    fmt("Grid", flow.get("grid"))
    print()
    fmt("Generation today", f"{kpi.get('power', 0)} kWh")
    fmt("Generation total", f"{kpi.get('total_power', 0)} kWh")
    fmt("Income today", f"{kpi.get('day_income', 0)} {kpi.get('currency', '')}")
    print()
    fmt("Power limit state", detail.get("powercontrol_status"))
    fmt("Last reported", inverter.get("last_refresh_time"))


def _print_response_and_check_remote_control(token: str, sn: str, response: dict) -> None:
    """Print a command's raw response, then check whether it likely
    actually reached the inverter.

    The portal can return a clean success response for a command that
    never reaches the inverter - a successful response here only means
    the portal ACCEPTED the request, not that the inverter obeyed it.
    canStartIV is the one flag that's actually diagnostic: if it's false,
    the command above almost certainly did nothing, no matter what the
    response says.
    """
    print("Raw response:")
    print(json.dumps(response, indent=2, ensure_ascii=False))
    try:
        kv = get_inverter_kv(token, sn)
    except SystemExit:
        print(
            "\n(Could not fetch remote-control status to double-check this - "
            "run 'status' separately.)"
        )
        return
    remote_control = kv.get("canStartIV")
    if remote_control is False:
        print(
            "\nWARNING: Remote control is DISABLED for this inverter on this "
            "SEMS Portal account. The response above is a real success from "
            "the portal's point of view, but it almost certainly did NOT "
            "reach the inverter - this is a known silent-failure mode, not a "
            "bug in this tool. Contact the account's installer or GoodWe "
            "support to have remote control enabled for this device."
        )
    elif remote_control is None:
        print(
            "\n(Could not determine remote-control status from this account - "
            "run 'status' to check separately.)"
        )


def cmd_limit(token: str, percent_arg: str) -> None:
    try:
        percent = int(percent_arg)
    except ValueError:
        die(f"'{percent_arg}' isn't a number - limit takes 0-100")
    if not 0 <= percent <= 100:
        die("Limit must be between 0 and 100")
    sn = resolve_sn(token)
    print(f"Setting inverter {sn} to {percent}%...")
    response = set_power_limit(token, sn, percent)
    _print_response_and_check_remote_control(token, sn, response)
    print("Done.")
    if percent == 0:
        print(
            "Note: 0% is near-zero output, not off - a small amount of power "
            "still passes through."
        )


def cmd_raw(token: str, name: str, body_arg: str | None) -> None:
    if name not in RAW_ENDPOINTS:
        die(f"Unknown endpoint '{name}'. Known: {', '.join(sorted(RAW_ENDPOINTS))}")
    try:
        body = json.loads(body_arg) if body_arg else {}
    except json.JSONDecodeError as err:
        die(f"Body isn't valid JSON: {err}")
    print(json.dumps(post(RAW_ENDPOINTS[name], body, token), indent=2, ensure_ascii=False))


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

COMMANDS = "discover, stations, status, detail, limit, start, stop, raw"


def main() -> None:
    email = os.environ.get("SEMS_EMAIL")
    password = os.environ.get("SEMS_PASSWORD")
    if not email or not password:
        print("ERROR: Set SEMS_EMAIL and SEMS_PASSWORD environment variables first.")
        print("  export SEMS_EMAIL='you@example.com'")
        print("  export SEMS_PASSWORD='your sems portal password'")
        print(
            "  (use SINGLE quotes - a $ in a double-quoted password gets "
            "expanded by the shell and silently corrupts it)"
        )
        sys.exit(1)

    if len(sys.argv) < 2:
        print(f"Usage: python3 {os.path.basename(sys.argv[0])} <command> [args]")
        print(f"Commands: {COMMANDS}")
        sys.exit(1)

    command = sys.argv[1].lower()
    print("Logging in...")
    token = login(email, password)

    if command == "discover":
        cmd_discover(token, sys.argv[2] if len(sys.argv) > 2 else None)
    elif command == "stations":
        cmd_stations(token)
    elif command == "status":
        cmd_status(token)
    elif command == "detail":
        cmd_detail(token)
    elif command == "limit":
        if len(sys.argv) < 3:
            die("limit needs a percentage, e.g. 'limit 50'")
        cmd_limit(token, sys.argv[2])
    elif command == "start":
        sn = resolve_sn(token)
        confirm(f"send a START command to inverter {sn}")
        response = start_inverter(token, sn)
        _print_response_and_check_remote_control(token, sn, response)
        print(f"Start command sent for {sn}. Grid-sync can take a few minutes.")
    elif command == "stop":
        sn = resolve_sn(token)
        confirm(f"send a STOP command to inverter {sn}")
        response = stop_inverter(token, sn)
        _print_response_and_check_remote_control(token, sn, response)
        print(f"Stop command sent for {sn}.")
    elif command == "raw":
        if len(sys.argv) < 3:
            die(f"raw needs an endpoint name. Known: {', '.join(sorted(RAW_ENDPOINTS))}")
        cmd_raw(token, sys.argv[2].lower(), sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        print(f"Unknown command: {command}")
        print(f"Commands: {COMMANDS}")
        sys.exit(1)


if __name__ == "__main__":
    main()
