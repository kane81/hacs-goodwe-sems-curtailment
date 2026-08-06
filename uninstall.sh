#!/bin/bash
# =============================================================================
# Home Assistant GoodWe SEMS Curtailment - Uninstall Script
# =============================================================================
#
# HACS only removes the custom_components folder when you uninstall.
# Run this script first to remove everything install.sh copied elsewhere.
#
# Usage:
#   bash /config/custom_components/sems_curtailment/uninstall.sh
#     Full uninstall - automations, package, scripts, templates, and
#     (if confirmed) the dashboard. Asks for confirmation first.
#
#   bash /config/custom_components/sems_curtailment/uninstall.sh dashboard
#     Dashboard only - removes /config/lovelace/sems.yaml and its
#     configuration.yaml registration, leaves everything else (automations,
#     entities, credentials) untouched. Use this if you built your own
#     UI-editable dashboard (see the README) and just want the
#     auto-installed one gone.
#
# After a full uninstall: remove the integration under Settings → Devices &
# Services (this removes the config entry along with every switch/number
# entity it created), then remove the HACS repository and restart HA.
# =============================================================================

MODE=${1:-full}
CONFIG=/config/configuration.yaml
DASH_FILE=/config/lovelace/sems.yaml

# -----------------------------------------------------------------------------
# Shared: remove the dashboard file and its configuration.yaml entry cleanly.
# Mirrors install.sh's insertion - removes the exact 6-line block by content
# match rather than blind sed, so it can't corrupt configuration.yaml the
# way blind append/removal did in an earlier version of this project.
# -----------------------------------------------------------------------------
remove_dashboard() {
    local removed_file=0
    if [ -f "$DASH_FILE" ]; then
        rm "$DASH_FILE"
        echo "   OK  removed: $DASH_FILE"
        removed_file=1
    fi

    if grep -q "lovelace-sems" "$CONFIG" 2>/dev/null; then
        python3 - "$CONFIG" << 'REMOVE'
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

removed = False
while True:
    i = find_block(lines)
    if i < 0:
        break
    del lines[i : i + len(BLOCK)]
    removed = True

if removed:
    # Drop a now-dangling blank-line pair left at end of file, same
    # cleanup install.sh's repair step does.
    while len(lines) >= 2 and lines[-1].strip() == "" and lines[-2].strip() == "":
        lines.pop()
    with open(path, "w") as f:
        f.writelines(lines)
    print("   OK  removed lovelace-sems entry from configuration.yaml")
REMOVE
        echo "   NOTE  the lovelace: block itself, and any other dashboards"
        echo "         registered in it (e.g. Amber's), are left in place."
    elif [ "$removed_file" -eq 1 ]; then
        echo "   NOTE  no lovelace-sems entry found in configuration.yaml"
        echo "         (already removed, or was never auto-registered)"
    fi

    # Validate before telling the user it's safe to restart - same check
    # install.sh runs after editing this file.
    python3 - "$CONFIG" << 'VALIDATE'
import re, sys
try:
    import yaml
except ImportError:
    sys.exit(0)
with open(sys.argv[1]) as f:
    text = re.sub(r"!\S+", "", f.read())
try:
    yaml.safe_load(text)
    print("   OK  configuration.yaml still parses")
except yaml.YAMLError as err:
    print("")
    print("   ERROR: configuration.yaml does not parse after editing:")
    print(f"          {err}")
    print("          Fix this before restarting Home Assistant.")
VALIDATE
}

# -----------------------------------------------------------------------------
# Dashboard-only mode
# -----------------------------------------------------------------------------
if [ "$MODE" = "dashboard" ]; then
    echo "============================================="
    echo " SEMS Curtailment - Remove Dashboard Only"
    echo "============================================="
    echo ""
    if [ ! -f "$DASH_FILE" ] && ! grep -q "lovelace-sems" "$CONFIG" 2>/dev/null; then
        echo "Nothing to do - no SEMS dashboard file or configuration.yaml"
        echo "entry was found. If you built your own via the Raw configuration"
        echo "editor (see the README), remove it from Settings > Dashboards"
        echo "instead - this script only knows about the auto-installed one."
        exit 0
    fi
    remove_dashboard
    echo ""
    echo "============================================="
    echo " Done - restart Home Assistant to apply:"
    echo "   Settings > System > Restart"
    echo "============================================="
    exit 0
fi

# -----------------------------------------------------------------------------
# Full uninstall
# -----------------------------------------------------------------------------
echo "============================================="
echo " Home Assistant GoodWe SEMS Curtailment"
echo " Uninstall Script"
echo "============================================="
echo ""
echo "This will remove all SEMS automations, the package, the reference"
echo "script, and (if you confirm) the dashboard."
echo ""
echo "To remove ONLY the dashboard and keep everything else, run instead:"
echo "  bash $0 dashboard"
echo ""
read -r -p "Are you sure you want to continue? (y/N): " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "Removing automations..."
for f in \
    sems_curtailment \
    sems_curtailment_enable \
    sems_curtailment_disable \
    sems_curtailment_manual \
    sems_load_tracking \
    sems_amber_dependency_check \
    sems_hacs_update; do
    if [ -f "/config/automations/${f}.yaml" ]; then
        rm "/config/automations/${f}.yaml"
        echo "   OK  removed: /config/automations/${f}.yaml"
    fi
done

echo ""
echo "Removing package..."
if [ -f "/config/packages/sems.yaml" ]; then
    rm /config/packages/sems.yaml
    echo "   OK  removed: /config/packages/sems.yaml"
fi

echo ""
echo "Removing scripts..."
for f in sems_cli.py sems_power.py; do
    # sems_power.py is a legacy artefact - only present on older installs
    if [ -f "/config/scripts/$f" ]; then
        rm "/config/scripts/$f"
        echo "   OK  removed: /config/scripts/$f"
    fi
done

echo ""
echo "Removing legacy template files (older installs only)..."
for f in solar.yaml battery.yaml; do
    if [ -f "/config/templates/$f" ]; then
        rm "/config/templates/$f"
        echo "   OK  removed: /config/templates/$f"
    fi
done

echo ""
echo "Dashboard"
if [ -f "$DASH_FILE" ] || grep -q "lovelace-sems" "$CONFIG" 2>/dev/null; then
    read -r -p "   Remove the SEMS dashboard too? (y/N): " remove_dash
    if [[ "$remove_dash" =~ ^[Yy]$ ]]; then
        remove_dashboard
    else
        echo "   Kept."
    fi
else
    echo "   None found."
fi

echo ""
echo "============================================="
echo " Uninstall complete!"
echo ""
echo " Next steps:"
echo "  1. Remove the integration: Settings > Devices & Services >"
echo "     GoodWe SEMS Curtailment > (menu) > Delete. This also deletes"
echo "     every switch/number entity it created and your stored SEMS"
echo "     login - nothing is left in secrets.yaml to clean up."
echo "  2. Remove the HACS repository: HACS > Integrations > SEMS > Remove"
echo "  3. Restart HA: Settings > System > Restart"
echo "============================================="
