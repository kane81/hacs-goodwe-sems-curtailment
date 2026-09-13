# Home Assistant GoodWe SEMS Curtailment

Curtail a GoodWe solar inverter from Home Assistant when [Amber Electric](https://www.amber.com.au/) prices go negative — automatic price-driven output limiting, manual curtailment, and direct inverter start/stop.

> **This project uses GoodWe's SEMS Portal API, which is not publicly documented or officially supported.** GoodWe may change or remove it at any time. Use at your own risk.

⚡ Requires the companion project [hacs-custom-amber-integration](https://github.com/kane81/hacs-custom-amber-integration) ([releases](https://github.com/kane81/hacs-custom-amber-integration/releases)) installed and signed in first — this project reads its price and battery sensors.

---

## How It Works

The integration authenticates with your SEMS Portal email and password, the same credentials used by the SEMS app. When the Amber buy or feed-in price goes negative, the curtailment automation calculates a target output percentage from battery state of charge and house load, and applies it to the inverter. When prices recover, output is restored to 100%. Curtailment runs all day — there is no time window.

---

## What You Get

### Part 1 — The Integration (required)

Switches, sizing controls, diagnostic sensors, and inverter commands, configured entirely through the Home Assistant UI with a SEMS Portal login. The inverter's serial number and rated capacity are discovered automatically; battery capacity is read from the Amber integration.

### Part 2 — Automations and Dashboard (optional)

The price-driven curtailment automations, plus a dashboard.

|                     | Part 1                            | Part 2                          |
| ------------------- | ---------------------------------- | -------------------------------- |
| **What it is**      | A normal HA integration           | Automations + a dashboard file  |
| **Install via**     | HACS → restart → Add Integration  | One shell command               |
| **You need**        | SEMS Portal email + password      | Nothing extra                   |
| **Required?**       | Yes                                | No — Part 1 works standalone    |

---

## Requirements

- The **[baseline Amber integration](https://github.com/kane81/hacs-custom-amber-integration)** installed and signed in
- A **GoodWe inverter** registered on the SEMS Portal (au.semsportal.com), with remote control enabled on the account — check the **Remote Control Enabled** sensor after setup if commands don't seem to be taking effect; see [Troubleshooting](#troubleshooting)
- **Home Assistant 2024.1** or newer, with [HACS](https://hacs.xyz/) installed
- A **terminal client** — Advanced SSH & Web Terminal add-on, or `docker exec` — required for Part 2's `install.sh` and the command-line tool
- *Optional* — the Amber integration's Power sensors configured, for accurate SOC-based curtailment sizing. See [Power sensors](#power-sensors) in the appendix.

---

## Part 1 — Install the Integration

### 1. Add the repository to HACS

**HACS** → **⋮** → **Custom repositories** → paste this repository's URL → Category **Integration** → **Add**.

### 2. Download it, then restart Home Assistant

**HACS** → search *GoodWe SEMS Curtailment* → **Download**, then **Settings → System → Restart**.

### 3. Add the integration

**Settings → Devices & Services → Add Integration** → search *Goodwe* → select **Home Assistant GoodWe SEMS Curtailment**.

If a dialog offers a different integration first, select **Cancel**, search again, and select this one from the results.

### 4. Complete the form

| Field                   | What it is                                          |
| ----------------------- | ---------------------------------------------------- |
| SEMS Portal email       | Your `au.semsportal.com` / SEMS app login           |
| SEMS Portal password    | Your SEMS Portal password                            |
| Battery max charge rate | e.g. `4640` W for an AlphaESS Smile5                 |
| Load change threshold   | Minimum watt change before Load Tracking re-adjusts  |
| Full SOC threshold      | See below                                            |

**Full SOC threshold** — the battery percentage above which the battery is treated as full. As a battery approaches full, its charge rate tapers, so the headroom curtailment reserves for charging shrinks with it. Above this threshold, curtailment targets house load only.

The login is verified against the SEMS Portal before the entry is created. The inverter serial number and rated capacity are then usually discovered automatically, and battery capacity is read live from `sensor.amber_smart_shift_battery_capacity` — none of these are entered by hand. If automatic inverter lookup fails (a known intermittent SEMS Portal issue — the account-level station list can return an empty result even while the inverter itself is reachable), you'll be asked for the serial number directly on a second screen; it's printed on the inverter's label, or visible in the SEMS+ app. To update the login, sizing, or inverter later, open the integration's card and select **Configure**.

---

## Part 2 — Automations and Dashboard (optional)

Part 1 must be installed and configured first.

### Install

From **Advanced SSH & Web Terminal**, or `docker exec -it homeassistant bash`:

```
bash /config/custom_components/sems_curtailment/install.sh
```

The installer copies the automations, helper package, and command-line tool, prompts for automatic or manual dashboard installation, verifies `configuration.yaml`, and restarts Home Assistant (HA OS/Supervised; container installs are told to restart manually). It re-runs automatically after HACS updates.

**Everything is installed switched off.** The curtailment automations check the Automatic Curtailment switch before acting, and it defaults to off.

### The dashboard

The status panel reports prices, power flow, and what curtailment is doing:

```
☀️ Curtailment OFF — Solar at 100%
🟢 Automatic Curtailment
🟢 SEMS Load Realtime Adj - Threshold 500W
🟢 Curtailment Active
```

🟢 active · 🔴 enabled, waiting · 🚫 disabled · ⚠️ curtailment currently limiting output

**Auto-installed dashboards cannot be edited in the UI.** `install.sh` registers a `mode: yaml` dashboard, which Home Assistant deliberately makes read-only in the frontend. Changes require editing `/config/lovelace/sems.yaml` directly, and re-running `install.sh` overwrites it with the shipped version. For a version you can edit through the UI, see [Building a UI-editable dashboard](#building-a-ui-editable-dashboard) below.

### The switches

**Automatic Curtailment** is the master switch — on, the price-driven logic runs continuously; off, nothing moves and the inverter is restored to 100%. **Curtailment Active** indicates the inverter is currently curtailed; while Automatic Curtailment is off it can be toggled by hand to curtail or restore immediately, using the same SOC-based calculation. **Load Tracking** fine-tunes the limit in real time as load and battery change while curtailment is active.

### Building a UI-editable dashboard

The auto-installed dashboard is fixed once installed — it's a `mode: yaml` file, and Home Assistant deliberately makes those read-only in the frontend. To get the same dashboard in a form you can rearrange, resize, and edit through the normal UI editor:

1. **Settings → Dashboards → + Add Dashboard** → *New dashboard from scratch* → name it and save
2. Open it → **⋮ → Edit Dashboard → ⋮ → Raw configuration editor**
3. Delete the placeholder content, paste in the contents of [`lovelace/sems.yaml`](https://github.com/kane81/hacs-goodwe-sems-curtailment/blob/main/lovelace/sems.yaml) → **Save**

Done — a fully UI-editable dashboard with the same layout as the auto-installed one.

### Command-line tool

`scripts/sems_cli.py` calls the SEMS Portal directly from a terminal — the same API operations the integration uses, without Home Assistant in the loop. Standard library only; runs anywhere with Python 3.9+.

```
export SEMS_EMAIL='you@example.com'
export SEMS_PASSWORD='your sems portal password'

python3 sems_cli.py discover     # station + inverter serial, model, capacity
python3 sems_cli.py stations     # every power station on the account
python3 sems_cli.py status       # Working / Waiting / Offline + remote control check
python3 sems_cli.py detail       # live PV/battery/grid/load snapshot
python3 sems_cli.py limit 50     # set output limit to 50%
python3 sems_cli.py stop --yes   # stop the inverter (asks first without --yes)
python3 sems_cli.py start        # start the inverter
python3 sems_cli.py raw inverter '{"sn": "..."}'   # dump a raw response
```

**Use single quotes around the password, not double quotes.** In bash/zsh, a `$` inside double quotes tries to expand a variable — a password like `VJ9CeF05e$rkm5F` silently becomes `VJ9CeF05e` (everything from the `$` onward just disappears), with no error, just a confusing login failure. Single quotes disable that expansion entirely.

Optionally `export SEMS_INVERTER_SN='...'` to skip the station lookup on commands that need a serial number, or `discover <serial_number>` to look one up directly if the station-list lookup returns nothing (see [Troubleshooting](#troubleshooting)). `limit`, `start`, and `stop` change the inverter's actual behaviour; a limit set here may be overwritten by Automatic Curtailment on its next evaluation.

### Send Start/Stop Inverter Command

Two buttons on the integration's device page (not the dashboard) for directly starting or stopping the inverter, independent of curtailment — neither changes the curtailment switches, and a stopped inverter stays stopped until started again. Stopping takes effect quickly; starting can take a few minutes to complete (grid-sync/ramp-up), so allow time before expecting **Inverter Status** to show *Working* — confirm with **Check Inverter Status**.

---

## Troubleshooting

**No entities on the device page** — setup did not complete. Open the integration's card; if it shows an error state, select **Configure** and re-enter the SEMS Portal credentials.

**Setup asks for the inverter serial number instead of finding it automatically** — this is expected, not an error. The SEMS Portal's account-level station list can return an empty result intermittently while everything else keeps working fine. Enter the serial number from the inverter's label or the SEMS+ app and setup continues normally with full functionality — only the automatic station name/id lookup is skipped.

**"Missing Dependency" notification** — the baseline Amber integration is not installed or not yet providing price data.

**"Power Sensors Not Configured" notification** — the Amber integration's Power sensor helpers are blank. See [Power sensors](#power-sensors).

**Curtailment never triggers** — confirm Automatic Curtailment is on and `sensor.amber_smart_shift_sell_price` is actually negative (**Developer Tools → States**).

**SEMS API calls failing** — press **Refresh Inverter Info** on the device page, or re-enter the SEMS Portal password via **Configure** if it has changed.

**Curtailment/limit/start/stop commands return success but the inverter doesn't respond** — press **Check Inverter Status** and look at the **Remote Control Enabled** sensor. If it shows *Disabled*, this is the cause: the SEMS Portal accepts and acknowledges the command without ever forwarding it to the inverter, and there's no error for this project to catch on its end. This is an account/inverter permission set on GoodWe's side, not a setting in Home Assistant — contact your installer or GoodWe support to have remote control enabled for the device. The command-line tool's `status` command shows the same thing and prints a warning automatically when it's off.

**Restart blocked by an invalid configuration.yaml** — re-run `install.sh`; it detects and repairs the misplaced dashboard entry an earlier version of the installer could leave behind, and validates the file before restarting.

---

## Uninstalling

```
bash /config/custom_components/sems_curtailment/uninstall.sh
```

Then remove the integration under **Settings → Devices & Services** (this deletes the stored credentials and all entities) and remove the repository from HACS.

---

## Appendix

### Entities

#### Switches

- `switch.sems_curtailment_automatic_curtailment` — master switch for price-driven curtailment
- `switch.sems_curtailment_curtailment_active` — on while the inverter is curtailed; manual toggle when Automatic Curtailment is off
- `switch.sems_curtailment_load_tracking` — real-time limit adjustment while curtailment is active

#### Numbers

- `number.sems_curtailment_inverter_capacity` — discovered from the SEMS Portal; refreshed by the Refresh Inverter Info button
- `number.sems_curtailment_battery_max_charge_rate`
- `number.sems_curtailment_load_change_threshold`
- `number.sems_curtailment_full_soc_threshold`
- `number.sems_curtailment_current_power_limit` — the current curtailment target, tracked by the automations; not edited by hand

#### Sensors

- `sensor.sems_curtailment_inverter_serial_number`
- `sensor.sems_curtailment_sems_station`
- `sensor.sems_curtailment_inverter_status` — *Unknown* until Check Inverter Status is pressed; never polled automatically
- `sensor.sems_curtailment_remote_control_enabled` — whether the SEMS Portal will actually relay commands to this inverter; see [Troubleshooting](#troubleshooting) above if it shows *Disabled*

#### Buttons

- `button.sems_curtailment_refresh_inverter_info` — re-runs discovery
- `button.sems_curtailment_check_inverter_status` — on-demand online/offline check
- `button.sems_curtailment_send_start_inverter_command`
- `button.sems_curtailment_send_stop_inverter_command`

#### Service

- `sems_curtailment.set_power_limit` — `limit: 0-100`; returns `{success, message}` when called with a response

### Power sensors

Battery, solar, load, and grid readings are read from the baseline Amber integration's Power sensor text helpers (`text.amber_smart_shift_power_*`), configured there rather than in this project. Battery capacity comes from `sensor.amber_smart_shift_battery_capacity`. Without the Power sensors, curtailment still operates on price alone, but load and battery read as 0 W, so SOC-based sizing and Load Tracking are inaccurate.

---

## Credits

Uses the SEMS Portal API (au.semsportal.com), reverse-engineered from the SEMS app. Not affiliated with or endorsed by GoodWe.

## License

See `LICENSE`.

## Contributing

Issues and pull requests are welcome.
