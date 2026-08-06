#!/bin/bash
# =============================================================================
# Home Assistant GoodWe SEMS Curtailment - Install Script
# =============================================================================
#
# Copies into place:
#   - the automations        -> /config/automations/
#   - the command-line tool  -> /config/scripts/sems_cli.py
#   - the helper package     -> /config/packages/sems.yaml
#   - the dashboard          -> /config/lovelace/sems.yaml (optional, asks first)
#
# then checks configuration.yaml has the required include lines and the
# dashboard registration, repairs the broken lovelace entry an earlier
# version of this script could leave behind, validates the result parses,
# and restarts Home Assistant via `ha core restart` (Home Assistant OS /
# Supervised only - plain-container installs are told to restart manually).
#
# Your SEMS Portal login and sizing are NOT handled here - they are entered
# through the integration's own config flow: Settings > Devices & Services >
# Add Integration > "GoodWe SEMS Curtailment". No login, no token, no
# secrets.yaml.
#
# Usage:
#   bash /config/custom_components/sems_curtailment/install.sh
#
# Mode: "full" (default) also offers the dashboard and restarts at the end.
#       "sync" copies files only - used on HA startup and after HACS updates.
# =============================================================================

set -e

MODE=${1:-full}
SRC=/config/custom_components/sems_curtailment
CONFIG=/config/configuration.yaml

echo "============================================="
echo " Home Assistant GoodWe SEMS Curtailment"
echo " Install Script"
echo "============================================="
echo ""

if [ ! -d "$SRC/automations" ]; then
    echo "ERROR: automation files not found at $SRC/automations"
    echo "       Install the integration via HACS first."
    exit 1
fi

if [ "$MODE" = "sync" ]; then
    echo "Sync mode - copying files only"
    echo ""
fi

# -----------------------------------------------------------------------------
# Copy files
# -----------------------------------------------------------------------------
echo "Installing automations..."
mkdir -p /config/automations
for f in "$SRC"/automations/*.yaml; do
    name=$(basename "$f")
    dest="/config/automations/$name"
    if [ -f "$dest" ]; then
        if [ ! -t 0 ]; then
            # Non-interactive (HACS auto-update via shell_command) - overwrite
            # silently so updates actually land without a human in the loop.
            cp "$f" "$dest"
        else
            echo "  $name already exists."
            read -r -p "    Overwrite? Any changes made in the UI editor will be lost. (y/N): " ans
            if [[ "$ans" =~ ^[Yy]$ ]]; then
                cp "$f" "$dest"
                echo "    overwritten"
            else
                echo "    kept"
            fi
        fi
    else
        cp "$f" "$dest"
        echo "  created $name"
    fi
done

mkdir -p /config/scripts
cp "$SRC"/scripts/sems_cli.py /config/scripts/
echo "OK  command-line tool -> /config/scripts/sems_cli.py"

mkdir -p /config/packages
cp "$SRC"/packages/sems.yaml /config/packages/
echo "OK  package -> /config/packages/sems.yaml"

# Legacy cleanup: earlier versions shipped template sensors that nothing
# referenced - the automations compute the same values inline. Remove them
# if a previous install copied them; the templates/ directory itself and
# any template: include line in configuration.yaml are left alone, since
# both may be in use by things outside this project.
for f in /config/templates/battery.yaml /config/templates/solar.yaml; do
    if [ -f "$f" ]; then
        rm "$f"
        echo "OK  removed legacy template file $f"
    fi
done

# -----------------------------------------------------------------------------
# Dashboard (full mode only)
# -----------------------------------------------------------------------------
DASH_DIR=/config/lovelace
DASH_FILE="$DASH_DIR/sems.yaml"
DASH_SRC="$SRC/lovelace/sems.yaml"
mkdir -p "$DASH_DIR"

if [ "$MODE" = "full" ]; then
    echo ""
    if [ ! -t 0 ]; then
        # Non-interactive (e.g. run by the HACS auto-install automation via
        # shell_command - no TTY). Prompting would hit EOF and abort under
        # set -e, so instead: refresh the dashboard if previously installed,
        # skip if it wasn't - preserving the choice made at first install.
        if [ -f "$DASH_FILE" ]; then
            cp "$DASH_SRC" "$DASH_FILE"
            echo "OK  dashboard refreshed (non-interactive run)"
        else
            echo "    dashboard skipped - not previously installed (non-interactive run)"
        fi
    else
        if [ -f "$DASH_FILE" ]; then
            # Already installed - offer to update it to the current version.
            read -r -p "  Dashboard already installed. Update it to the current version? (Y/n): " dash_choice
            if [[ "$dash_choice" =~ ^[Nn]$ ]]; then
                echo "  Kept existing dashboard."
            else
                cp "$DASH_SRC" "$DASH_FILE"
                echo "OK  dashboard updated -> $DASH_FILE"
            fi
        else
            echo "  Two ways to get the dashboard:"
            echo ""
            echo "    1) Automatic - installs now, ready to use immediately. Can only"
            echo "       be edited afterward by editing the YAML file directly - Home"
            echo "       Assistant deliberately locks UI editing for this kind of"
            echo "       dashboard, so there's no drag-and-drop editor for it."
            echo "    2) Manual - skip this and build your own instead, via Settings >"
            echo "       Dashboards. More setup, but fully editable in the UI. See"
            echo "       dashboard_card.txt for the status card content, and the"
            echo "       README's 'Manually adding the dashboard' section for steps."
            echo ""
            read -r -p "  Install the dashboard automatically? (Y/n): " dash_choice
            if [[ "$dash_choice" =~ ^[Nn]$ ]]; then
                echo "  Skipped."
            else
                cp "$DASH_SRC" "$DASH_FILE"
                echo "OK  dashboard -> $DASH_FILE"
            fi
        fi
    fi
fi

# -----------------------------------------------------------------------------
# configuration.yaml
# -----------------------------------------------------------------------------
echo ""
echo "============================================="
echo " Checking configuration.yaml"
echo "============================================="
echo ""

# --- repair: an earlier version of this script appended the lovelace-sems
# entry at end-of-file when a lovelace: block already existed, which lands
# the keys outside the block and breaks the whole file ("mapping values are
# not allowed here"). The appended content was fixed and deterministic, so
# it can be located and removed exactly, then re-added correctly below.
python3 - "$CONFIG" << 'REPAIR'
import sys

path = sys.argv[1]
with open(path) as f:
    lines = f.readlines()

BLOCK = [
    "    lovelace-sems:\n",
    "      mode: yaml\n",
    "      title: SEMS\n",
    "      icon: mdi:solar-power\n",
    "      filename: lovelace/sems.yaml\n",
    "      show_in_sidebar: true\n",
]

def find_block(lines):
    for i in range(len(lines) - len(BLOCK) + 1):
        if lines[i : i + len(BLOCK)] == BLOCK:
            return i
    return -1

def inside_dashboards(lines, i):
    """Is the entry at index i actually under a dashboards: key?"""
    for j in range(i - 1, -1, -1):
        stripped = lines[j].strip()
        if not stripped or stripped.startswith("#"):
            continue
        return stripped == "dashboards:" or stripped.startswith("lovelace-")
    return False

removed = False
while True:
    i = find_block(lines)
    if i < 0:
        break
    if inside_dashboards(lines, i):
        break  # correctly placed - leave it alone
    del lines[i : i + len(BLOCK)]
    removed = True

if removed:
    # also drop a now-dangling blank line pair at EOF
    while len(lines) >= 2 and lines[-1].strip() == "" and lines[-2].strip() == "":
        lines.pop()
    with open(path, "w") as f:
        f.writelines(lines)
    print("OK  repaired a misplaced lovelace-sems entry left by an earlier install")
REPAIR

# --- automations/ directory include - preserves any existing
# automations.yaml rather than orphaning it.
if grep -q "include_dir_merge_list automations" "$CONFIG"; then
    echo "OK  automation: include already present"
elif [ -f /config/automations.yaml ]; then
    echo "    Found an existing automations.yaml - migrating it into automations/"
    mkdir -p /config/automations
    cp /config/automations.yaml /config/automations/automations_existing.yaml
    sed -i "s|automation: !include automations.yaml|automation: !include_dir_merge_list automations/|g" "$CONFIG"
    sed -i "s|^automation:$|automation: !include_dir_merge_list automations/|g" "$CONFIG"
    echo "OK  existing automations preserved as automations/automations_existing.yaml"
elif grep -q "^automation:" "$CONFIG"; then
    sed -i "s|^automation:.*|automation: !include_dir_merge_list automations/|g" "$CONFIG"
    echo "OK  automation: include updated"
else
    printf "\nautomation: !include_dir_merge_list automations/\n" >> "$CONFIG"
    echo "OK  automation: include added"
fi

# --- packages include
if grep -q "include_dir_named packages" "$CONFIG"; then
    echo "OK  packages: include already present"
elif grep -q "^homeassistant:" "$CONFIG"; then
    sed -i "/^homeassistant:/a\\  packages: !include_dir_named packages/" "$CONFIG"
    echo "OK  packages: include added under homeassistant:"
else
    printf "\nhomeassistant:\n  packages: !include_dir_named packages/\n" >> "$CONFIG"
    echo "OK  homeassistant: packages: include added"
fi

# --- lovelace dashboard entry. Three cases:
#   1. already registered            -> nothing to do
#   2. no lovelace: block at all     -> append a complete block (safe at EOF)
#   3. lovelace: block exists        -> insert the entry INSIDE its
#      dashboards: key, never appended at end-of-file - appending indented
#      keys after unrelated top-level keys is exactly the bug repaired above.
if grep -q "lovelace-sems" "$CONFIG"; then
    echo "OK  lovelace dashboard entry already present"
elif [ -f "$DASH_FILE" ]; then
    if ! grep -q "^lovelace:" "$CONFIG"; then
        cat >> "$CONFIG" << 'LOVELACE'

lovelace:
  dashboards:
    lovelace-sems:
      mode: yaml
      title: SEMS
      icon: mdi:solar-power
      filename: lovelace/sems.yaml
      show_in_sidebar: true
LOVELACE
        echo "OK  lovelace dashboard entry added (new lovelace block)"
    else
        python3 - "$CONFIG" << 'INSERT'
import sys

path = sys.argv[1]
with open(path) as f:
    lines = f.readlines()

ENTRY = [
    "    lovelace-sems:\n",
    "      mode: yaml\n",
    "      title: SEMS\n",
    "      icon: mdi:solar-power\n",
    "      filename: lovelace/sems.yaml\n",
    "      show_in_sidebar: true\n",
]

out = None
in_lovelace = False
for idx, line in enumerate(lines):
    if line.rstrip("\n") == "lovelace:":
        in_lovelace = True
        continue
    if in_lovelace:
        if line.strip() == "dashboards:":
            out = lines[: idx + 1] + ENTRY + lines[idx + 1 :]
            break
        if line.strip() and not line.startswith(" "):
            # lovelace: block ended without a dashboards: key -
            # add one (with the entry) at the top of the block
            for j in range(idx - 1, -1, -1):
                if lines[j].rstrip("\n") == "lovelace:":
                    out = lines[: j + 1] + ["  dashboards:\n"] + ENTRY + lines[j + 1 :]
                    break
            break

if out is None and in_lovelace:
    # lovelace: was the last block and had no dashboards: key
    out = lines + ["  dashboards:\n"] + ENTRY

if out is None:
    sys.exit("could not locate the lovelace block")

with open(path, "w") as f:
    f.writelines(out)
print("OK  lovelace dashboard entry inserted into existing lovelace block")
INSERT
    fi
fi

# --- validate the result actually parses before letting HA restart into it.
# HA-specific tags (!include etc.) are stripped for the check - structure is
# what the earlier bug broke, and structure is what this verifies.
python3 - "$CONFIG" << 'VALIDATE'
import re, sys

try:
    import yaml
except ImportError:
    sys.exit(0)  # no pyyaml on this host - skip silently

with open(sys.argv[1]) as f:
    text = re.sub(r"!\S+", "", f.read())
try:
    yaml.safe_load(text)
    print("OK  configuration.yaml parses")
except yaml.YAMLError as err:
    print("")
    print("ERROR: configuration.yaml does not parse after editing:")
    print(f"       {err}")
    print("       NOT restarting - fix the file before restarting Home Assistant.")
    sys.exit(1)
VALIDATE

# -----------------------------------------------------------------------------
# Done
# -----------------------------------------------------------------------------
echo ""
echo "============================================="
echo " Done"
echo "============================================="
echo ""
echo " If you haven't already, add the integration:"
echo "   Settings > Devices & Services > Add Integration"
echo "   > \"GoodWe SEMS Curtailment\""
echo " That is where your SEMS Portal login and sizing are entered."
echo ""

if [ "$MODE" = "sync" ]; then
    exit 0
fi

# `ha core restart` only exists on Home Assistant OS / Supervised, via the
# Supervisor - it's not present in a plain container. A script running
# inside a plain container has no supervisor socket to restart itself from
# the inside, so that case still needs the manual step.
if command -v ha >/dev/null 2>&1; then
    echo " Restarting Home Assistant now..."
    ha core restart
else
    echo " Restart Home Assistant to load everything:"
    echo "   Settings > System > Restart"
    echo ""
    echo " (couldn't restart automatically - the 'ha' command isn't available"
    echo " here, which is normal for a plain container install rather than"
    echo " Home Assistant OS or Supervised)"
fi
