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
#
# After running: remove the integration under Settings → Devices & Services
# (this removes the config entry along with every switch/number entity it
# created), then remove the HACS repository and restart HA.
# =============================================================================

echo "============================================="
echo " Home Assistant GoodWe SEMS Curtailment"
echo " Uninstall Script"
echo "============================================="
echo ""
echo "⚠️  This will remove all SEMS automations, the package, the reference"
echo "    script, and (if you confirm) the dashboard."
echo ""
read -r -p "Are you sure you want to uninstall? (y/N): " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "🗑️  Removing automations..."
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
        echo "   ✅ Removed: /config/automations/${f}.yaml"
    fi
done

echo ""
echo "🗑️  Removing package..."
if [ -f "/config/packages/sems.yaml" ]; then
    rm /config/packages/sems.yaml
    echo "   ✅ Removed: /config/packages/sems.yaml"
fi

echo ""
echo "🗑️  Removing scripts..."
for f in sems_cli.py sems_power.py; do
    # sems_power.py is a legacy artefact - only present on older installs
    if [ -f "/config/scripts/$f" ]; then
        rm "/config/scripts/$f"
        echo "   ✅ Removed: /config/scripts/$f"
    fi
done

echo ""
echo "🗑️  Removing legacy template files (older installs only)..."
for f in solar.yaml battery.yaml; do
    if [ -f "/config/templates/$f" ]; then
        rm "/config/templates/$f"
        echo "   ✅ Removed: /config/templates/$f"
    fi
done

echo ""
echo "🗑️  Dashboard"
if [ -f "/config/lovelace/sems.yaml" ]; then
    read -r -p "   Remove the SEMS dashboard file too? (y/N): " remove_dash
    if [[ "$remove_dash" =~ ^[Yy]$ ]]; then
        rm /config/lovelace/sems.yaml
        echo "   ✅ Removed: /config/lovelace/sems.yaml"
        echo "   ℹ️  The lovelace-sems entry in configuration.yaml is left in place -"
        echo "      remove it by hand if you want the sidebar entry gone too."
    else
        echo "   Skipped."
    fi
else
    echo "   None found."
fi

echo ""
echo "============================================="
echo " ✅ Uninstall complete!"
echo ""
echo " Next steps:"
echo "  1. Remove the integration: Settings → Devices & Services →"
echo "     GoodWe SEMS Curtailment → ⋮ → Delete. This also deletes every"
echo "     switch/number entity it created and your stored SEMS login -"
echo "     nothing is left in secrets.yaml to clean up."
echo "  2. Remove the HACS repository: HACS → Integrations → SEMS → Remove"
echo "  3. Restart HA: Settings → System → Restart"
echo "============================================="
