#!/bin/bash
# =============================================================================
# Home Assistant GoodWe SEMS Curtailment - Uninstall Script
# =============================================================================
#
# HACS only removes the custom_components folder when you uninstall.
# Run this script to fully remove all integration files and helpers.
#
# Usage:
#   bash /config/custom_components/sems_curtailment/uninstall.sh
#
# After running, restart HA to apply changes.
# =============================================================================

echo "============================================="
echo " Home Assistant GoodWe SEMS Curtailment"
echo " Uninstall Script"
echo "============================================="
echo ""
echo "⚠️  This will remove all SEMS integration files."
echo "    Your secrets.yaml credentials will NOT be removed."
echo ""
read -r -p "Are you sure you want to uninstall? (y/N): " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
    echo "Aborted."
    exit 0
fi

echo ""
echo "🗑️  Removing automations..."
for f in \
    sems_power_limit \
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
if [ -f "/config/scripts/sems_power.py" ]; then
    rm /config/scripts/sems_power.py
    echo "   ✅ Removed: /config/scripts/sems_power.py"
fi

echo ""
echo "🗑️  Removing templates..."
for f in solar.yaml battery.yaml; do
    if [ -f "/config/templates/$f" ]; then
        rm "/config/templates/$f"
        echo "   ✅ Removed: /config/templates/$f"
    fi
done

echo ""
echo "============================================="
echo " ✅ Uninstall complete!"
echo ""
echo " Next steps:"
echo "  1. Remove HACS integration: HACS → Integrations → SEMS → Remove"
echo "  2. Restart HA: Settings → System → Restart"
echo "  3. Optionally remove credentials from /config/secrets.yaml:"
echo "     sems_email, sems_password, sems_inverter_sn"
echo "============================================="
