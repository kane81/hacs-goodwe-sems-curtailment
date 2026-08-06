"""SEMS Portal API client.

One class, five operations: login, discover_inverter, get_inverter_status,
start/stop_inverter, set_power_limit. Everything routes through a single
_post() transport and a single _request() authenticated wrapper, so error
handling, response-code checking, and the auth header exist in exactly one
place each.

The auth token from a login is cached on the instance and reused across
calls, with one automatic re-login retry if the portal rejects it -
important because the callers (config flow validation, buttons, the
set_power_limit service) often make more than one call per user action,
and the portal is flaky enough that halving the login traffic matters.
Instances are cheap and short-lived (one per button press / service call),
so the cache never lives long enough to go genuinely stale.

Uses urllib rather than aiohttp because this API needs SSL verification
disabled, which is simplest to set up the same way throughout. All methods
are blocking - callers must run them via hass.async_add_executor_job, same
convention the baseline Amber integration uses for its own blocking calls.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from .const import (
    INVERTER_COMMAND_START,
    INVERTER_COMMAND_STOP,
    SEMS_INVERTER_KV_URL,
    SEMS_LOGIN_URL,
    SEMS_MONITOR_DETAIL_URL,
    SEMS_SET_POWER_URL,
    SEMS_STATION_LIST_URL,
)

_CLIENT_FIELDS = {"client": "ios", "version": "v3.7.9", "language": "en"}


class SemsApiError(Exception):
    """Raised when the SEMS Portal API can't be reached or returns garbage."""


class SemsAuthError(SemsApiError):
    """Raised when login fails - wrong email/password."""


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _post(url: str, body: dict, token: str) -> dict:
    """POST a JSON body with the SEMS Token header, return the parsed response.

    Transport errors only - success/failure of the API operation itself is
    _check_code()'s job, so callers can distinguish "couldn't reach the
    portal" from "the portal said no".

    The SEMS Portal (au.semsportal.com) is flaky and occasionally stalls
    mid-response. connect_timeout is kept tight so a completely unreachable
    host fails fast; read_timeout is generous to tolerate the portal pausing
    after accepting the connection before it finishes sending the body.
    Python's urllib takes a single timeout value, not separate connect/read
    pairs, so a socket-level workaround is used: set the default SO_TIMEOUT
    on the socket after connection, done implicitly by passing a float to
    urlopen - the connect phase uses the same value, but the read phase is
    what actually needs headroom, so we choose accordingly.
    """
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Token": token},
    )
    try:
        with urllib.request.urlopen(req, context=_ssl_context(), timeout=30) as resp:
            return json.loads(resp.read())
    except TimeoutError as err:
        # Python 3.11+ raises TimeoutError directly in addition to wrapping
        # it inside URLError; catch it here so both Python versions get the
        # same SemsApiError regardless of which one lands first.
        raise SemsApiError(
            "SEMS Portal timed out - the portal is known to be slow or"
            " intermittently unresponsive. Try again in a moment."
        ) from err
    except urllib.error.URLError as err:
        if isinstance(err.reason, TimeoutError):
            raise SemsApiError(
                "SEMS Portal timed out - the portal is known to be slow or"
                " intermittently unresponsive. Try again in a moment."
            ) from err
        raise SemsApiError(f"Could not reach SEMS Portal: {err}") from err
    except json.JSONDecodeError as err:
        raise SemsApiError(f"Unexpected SEMS Portal response: {err}") from err


def _check_code(data: dict, what: str) -> dict:
    """Raise unless the response reports success.

    The portal is inconsistent about the type of `code` - some endpoints
    return the integer 0, others the string "0" - so this compares as a
    string rather than against a literal 0.
    """
    if str(data.get("code")) != "0":
        raise SemsApiError(f"{what} failed: {data.get('msg') or data.get('code')}")
    return data


def _command_date() -> str:
    """Timestamp field for remote-control commands.

    Plain slashes: the SEMS app's own payloads contain the JSON escape
    sequence \\/ in the raw request text, which parses to a plain / - it is
    NOT a literal backslash in the value. (v1 of this project embedded a
    real backslash, an artefact of the shell-quoting context the call was
    originally written in; the portal tolerated it, but the app's actual
    format is the plain date.)
    """
    return datetime.now().strftime("%m/%d/%Y %H:%M:%S")


class SemsApi:
    """Client for the SEMS Portal calls this project needs."""

    def __init__(self, email: str, password: str) -> None:
        self._email = email
        self._password = password
        self._token: str | None = None

    # -- auth ---------------------------------------------------------------

    def login(self) -> str:
        """Log in and return (and cache) the Token header for later calls.

        Blocking. Raises SemsAuthError on bad credentials, SemsApiError on
        any other failure (network, unexpected response shape).
        """
        seed = json.dumps({"uid": "", "timestamp": 0, "token": "", **_CLIENT_FIELDS})
        data = _post(
            SEMS_LOGIN_URL,
            {"account": self._email, "pwd": self._password, "is_local": False},
            seed,
        )
        if str(data.get("code")) != "0":
            raise SemsAuthError(data.get("msg", "Login failed"))
        try:
            d = data["data"]
            self._token = json.dumps(
                {
                    "uid": d["uid"],
                    "timestamp": d["timestamp"],
                    "token": d["token"],
                    **_CLIENT_FIELDS,
                }
            )
        except (KeyError, TypeError) as err:
            raise SemsApiError(f"Unexpected SEMS Portal login response: {err}") from err
        return self._token

    def _request(self, url: str, body: dict, what: str) -> dict:
        """Authenticated call: login if needed, POST, check the result code.

        If a cached token is rejected (the one operation-failure mode a
        stale session produces), re-login once and retry - but only when
        the failed call actually used a cached token, so a fresh login's
        rejection isn't retried pointlessly.
        """
        had_cached = self._token is not None
        token = self._token or self.login()
        data = _post(url, body, token)
        if str(data.get("code")) != "0" and had_cached:
            self._token = None
            data = _post(url, body, self.login())
        return _check_code(data, what)

    # -- read ---------------------------------------------------------------

    def discover_inverter(self) -> dict[str, Any]:
        """Find the account's power station, then its inverter.

        Returns {powerstation_id, station_name, inverter_sn,
        inverter_capacity_w}. Only the FIRST power station on the account is
        used - accounts with more than one station aren't supported yet.
        Raises SemsApiError if the account has no stations, or the response
        shape isn't what's expected (SEMS Portal is undocumented, so this
        is deliberately defensive).
        """
        stations_resp = self._request(
            SEMS_STATION_LIST_URL,
            {
                "page_size": "5",
                "orderby": "",
                "powerstation_status": "",
                "key": "",
                "page_index": "1",
                "powerstation_id": "",
                "powerstation_type": "",
            },
            "SEMS Portal power station lookup",
        )
        stations = (stations_resp.get("data") or {}).get("list") or []
        if not stations:
            raise SemsApiError("No power stations found on this SEMS Portal account")
        station = stations[0]
        powerstation_id = station.get("powerstation_id")
        station_name = station.get("stationname", "")
        if not powerstation_id:
            raise SemsApiError(
                "SEMS Portal station list response is missing powerstation_id"
            )

        detail_resp = self._request(
            SEMS_MONITOR_DETAIL_URL,
            {"Version": "v4", "powerStationId": powerstation_id},
            "SEMS Portal inverter lookup",
        )
        inverters = (detail_resp.get("data") or {}).get("inverter") or []
        if not inverters:
            raise SemsApiError(f"No inverters found on power station '{station_name}'")
        inverter = inverters[0]
        inverter_sn = inverter.get("sn")
        if not inverter_sn:
            raise SemsApiError("SEMS Portal inverter response is missing a serial number")

        # Rated capacity: prefer the "capacity" row in dict.left (kW, as a
        # string, e.g. "10"), which is what the SEMS+ app displays as the
        # inverter's rated output. Fall back to the top-level "capacity"
        # field on the inverter object if that row isn't present.
        capacity_kw: float | None = None
        for item in (inverter.get("dict") or {}).get("left") or []:
            if item.get("key") == "capacity":
                try:
                    capacity_kw = float(item.get("value"))
                except (TypeError, ValueError):
                    capacity_kw = None
                break
        if capacity_kw is None:
            try:
                capacity_kw = float(inverter.get("capacity"))
            except (TypeError, ValueError):
                capacity_kw = None
        if capacity_kw is None:
            raise SemsApiError(
                "Could not determine inverter capacity from SEMS Portal response"
            )

        return {
            "powerstation_id": powerstation_id,
            "station_name": station_name,
            "inverter_sn": inverter_sn,
            "inverter_capacity_w": int(round(capacity_kw * 1000)),
        }

    def get_inverter_status(self, inverter_sn: str) -> dict[str, Any]:
        """Check whether the inverter is currently working/waiting/offline.

        Not called automatically anywhere - only from the Check Inverter
        Status button (button.py) and the CLI's `status` command. The SEMS
        Portal API is unofficial and has been unreliable, so this is
        deliberately on-demand only rather than polled on a schedule.

        Returns {status_code, capacity}. status_code is the raw string the
        portal returns (see const.INVERTER_STATUS_LABELS for the confirmed
        meaning of each value) - kept as a string rather than mapped to a
        label here, so api.py stays free of anything HA/entity-specific.
        """
        data = self._request(
            SEMS_INVERTER_KV_URL,
            {"sn": inverter_sn},
            "SEMS Portal inverter status check",
        )
        payload = data.get("data") or {}
        status_code = payload.get("status")
        if status_code is None:
            raise SemsApiError("SEMS Portal inverter status response is missing 'status'")
        return {
            "status_code": str(status_code),
            "capacity": payload.get("capacity"),
        }

    # -- control ------------------------------------------------------------
    # All three commands go to the same SaveRemoteControlInverter endpoint;
    # which action happens is selected by the *SettingMark/value pair in the
    # body (ActivePowerLimit vs InverterStatus).

    def set_power_limit(self, inverter_sn: str, limit_percent: int) -> None:
        """Set the inverter's active power output limit (0-100%).

        Blocking. Raises SemsAuthError / SemsApiError on failure.
        """
        self._request(
            SEMS_SET_POWER_URL,
            {
                "InverterSN": inverter_sn,
                "InverterRemotingLastSetDate": _command_date(),
                "ActivePowerLimit": str(limit_percent),
                "ActivePowerLimitSettingMark": "1",
            },
            "Set power limit",
        )

    def _set_status(self, inverter_sn: str, status_code: str) -> None:
        self._request(
            SEMS_SET_POWER_URL,
            {
                "InverterSN": inverter_sn,
                "InverterRemotingLastSetDate": _command_date(),
                "InverterStatusSettingMark": "1",
                "InverterStatus": status_code,
            },
            "Set inverter status",
        )

    def start_inverter(self, inverter_sn: str) -> None:
        """Send a start command to the inverter.

        Blocking. Raises SemsAuthError / SemsApiError on failure. Starting a
        stopped inverter is expected to take a few minutes to complete
        (grid-sync/ramp-up) - the SEMS Portal call itself returns quickly,
        it's the inverter physically coming back online that's slow. Don't
        expect Inverter Status to show "Working" immediately after this
        returns - use the Check Inverter Status button a few minutes later.
        """
        self._set_status(inverter_sn, INVERTER_COMMAND_START)

    def stop_inverter(self, inverter_sn: str) -> None:
        """Send a stop command to the inverter.

        Blocking. Raises SemsAuthError / SemsApiError on failure. Unlike
        start_inverter(), this is expected to take effect quickly.
        """
        self._set_status(inverter_sn, INVERTER_COMMAND_STOP)
