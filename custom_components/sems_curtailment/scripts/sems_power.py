# =============================================================================
# SEMS Portal - Inverter Power Limit Controller
# =============================================================================
# Controls the active power output limit of a GoodWe solar inverter via the
# SEMS Portal API (au.semsportal.com). Replicates the API calls the SEMS+ app
# makes internally to change the inverter's power output limit.
#
# Use Case:
#   Used with Amber Electric price automations to curtail solar export when
#   the feed-in (sell) price becomes negative or when battery is charging.
#
# Power limit examples (10kW inverter):
#   100% = 10.0kW max output  (full power)
#    50% =  5.0kW max output
#     0% =  0.0kW max output  (effectively off)
#
# Usage:
#   python3 sems_power.py <limit_percent>
#   e.g. python3 sems_power.py 50   → limits inverter to 50% output
#        python3 sems_power.py 100  → restores inverter to full output
#
# HA Setup:
#   shell_command:
#     sems_set_power: "python3 /config/scripts/sems_power.py {{ limit }}"
#
# Credentials:
#   Read from /config/secrets.yaml
#   sems_email:       your SEMS Portal login email
#   sems_password:    your SEMS Portal login password
#   sems_inverter_sn: your inverter serial number (on inverter label)
#
# Requirements:
#   Python 3.x — no third-party libraries required, standard library only
#
# Change Log:
#   v1.0    2026-03-25    Kane Li    - Initial version
# =============================================================================

import urllib.request
import urllib.error
import json
import ssl
import sys
import re
from datetime import datetime

SECRETS_PATH = "/config/secrets.yaml"


def load_secrets(secrets_path=SECRETS_PATH):
    """
    Reads credentials from HA secrets.yaml.
    Handles simple key: value pairs, ignores comments and blank lines.

    Args:
        secrets_path (str): Path to secrets.yaml

    Returns:
        dict: Parsed secrets key/value pairs
    """
    secrets = {}
    with open(secrets_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.match(r'^(\w+)\s*:\s*(.+)$', line)
            if match:
                key   = match.group(1)
                value = match.group(2).strip().strip('"').strip("'")
                secrets[key] = value
    return secrets


def set_power_limit(limit_percent, email, password, inverter_sn):
    """
    Authenticates with the SEMS Portal and sets the inverter's active power
    limit to the specified percentage.

    Args:
        limit_percent (int): Power output limit as a percentage (0-100)
        email (str):         SEMS Portal account email address
        password (str):      SEMS Portal account password
        inverter_sn (str):   Inverter serial number (printed on inverter label)

    Returns:
        bool: True if the command was accepted by the API, False otherwise
    """
    # Disable SSL certificate verification — required for SEMS Portal API
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # -------------------------------------------------------------------------
    # Step 1: Login — obtain an authenticated session token from SEMS Portal
    # -------------------------------------------------------------------------

    # Initial unauthenticated token required by the login endpoint
    login_token = '{"uid":"","timestamp":0,"token":"","client":"ios","version":"v3.7.9","language":"en"}'

    login_body = json.dumps({
        "account":  email,
        "pwd":      password,
        "is_local": False   # False = connect via cloud, not local network
    }).encode()

    login_req = urllib.request.Request(
        "https://au.semsportal.com/api/v1/Common/CrossLogin",
        data=login_body,
        headers={
            "Content-Type": "application/json",
            "Token":        login_token
        }
    )

    with urllib.request.urlopen(login_req, context=ctx) as resp:
        login_data = json.loads(resp.read())

    # API returns code 0 on success
    if login_data["code"] != 0:
        print(f"Login failed: {login_data['msg']}")
        return False

    uid       = login_data["data"]["uid"]
    token     = login_data["data"]["token"]
    timestamp = login_data["data"]["timestamp"]

    # -------------------------------------------------------------------------
    # Step 2: Set Power Limit — send remote control command to the inverter
    # -------------------------------------------------------------------------

    auth_token = json.dumps({
        "uid":       uid,
        "timestamp": timestamp,
        "token":     token,
        "client":    "ios",
        "version":   "v3.7.9",
        "language":  "en"
    })

    # API requires date in MM/DD/YYYY HH:MM:SS format with escaped slashes
    date_str = datetime.now().strftime("%m\\/%d\\/%Y %H:%M:%S")

    cmd_body = json.dumps({
        "InverterSN":                    inverter_sn,
        "InverterRemotingLastSetDate":   date_str,
        "ActivePowerLimit":              str(limit_percent),  # Must be a string
        "ActivePowerLimitSettingMark":   "1"                  # Required to apply
    }).encode()

    cmd_req = urllib.request.Request(
        "https://au.semsportal.com/api/PowerStation/SaveRemoteControlInverter",
        data=cmd_body,
        headers={
            "Content-Type": "application/json",
            "Token":        auth_token
        }
    )

    with urllib.request.urlopen(cmd_req, context=ctx) as resp:
        cmd_data = json.loads(resp.read())

    print(f"Result: {cmd_data}")
    return cmd_data["code"] == 0


# -----------------------------------------------------------------------------
# Entry Point
# -----------------------------------------------------------------------------
if __name__ == "__main__":

    if len(sys.argv) != 2:
        print("Usage: python3 sems_power.py <limit_percent>")
        print("Example: python3 sems_power.py 50")
        sys.exit(1)

    limit = int(sys.argv[1])

    print(f"Loading credentials from {SECRETS_PATH}...")
    try:
        secrets = load_secrets()
    except FileNotFoundError:
        print(f"ERROR: secrets.yaml not found at {SECRETS_PATH}")
        sys.exit(1)

    email       = secrets.get("sems_email")
    password    = secrets.get("sems_password")
    inverter_sn = secrets.get("sems_inverter_sn")

    if not email:
        print("ERROR: sems_email not found in secrets.yaml")
        sys.exit(1)
    if not password:
        print("ERROR: sems_password not found in secrets.yaml")
        sys.exit(1)
    if not inverter_sn:
        print("ERROR: sems_inverter_sn not found in secrets.yaml")
        sys.exit(1)

    print(f"Credentials loaded. Inverter SN: {inverter_sn}")
    success = set_power_limit(limit, email, password, inverter_sn)
    sys.exit(0 if success else 1)
