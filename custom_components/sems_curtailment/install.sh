#!/bin/bash
# =============================================================================
# Home Assistant GoodWe SEMS Curtailment - Install Script
# =============================================================================
#
# Run this after every HACS install or update to copy integration files
# into their correct /config/ locations.
#
# Usage:
#   bash /config/custom_components/sems_curtailment/install.sh
#
# Safe to re-run — existing files are overwritten, nothing is deleted.
# =============================================================================

set -e

SRC=/config/custom_components/sems_curtailment
CONFIG=/config/configuration.yaml
ERRORS=0

echo "============================================="
echo " Home Assistant GoodWe SEMS Curtailment"
echo " Install Script"
echo "============================================="
echo ""

# Automations
echo "📋 Copying automations..."
mkdir -p /config/automations
cp -v $SRC/automations/*.yaml /config/automations/

# Scripts
echo ""
echo "🐍 Copying scripts..."
mkdir -p /config/scripts
cp -v $SRC/scripts/*.py /config/scripts/

# Package
echo ""
echo "📦 Copying package..."
mkdir -p /config/packages
cp -v $SRC/packages/sems.yaml /config/packages/

# Templates
echo ""
echo "📄 Copying templates..."
mkdir -p /config/templates
cp -v $SRC/templates/*.yaml /config/templates/

echo ""
echo "============================================="
echo " Checking configuration.yaml"
echo "============================================="
echo ""

# Check automation dir merge line
if grep -q "include_dir_merge_list automations" $CONFIG; then
    echo "✅ automation: !include_dir_merge_list automations/ — found"
else
    echo "⚠️  MISSING — automation directory not configured!"
    echo ""
    echo "   Add this line to $CONFIG:"
    echo "   automation: !include_dir_merge_list automations/"
    echo ""
    echo "   If you already have 'automation: !include automations.yaml'"
    echo "   replace that line with the one above."
    ERRORS=$((ERRORS + 1))
fi

# Check packages line
if grep -q "include_dir_named packages" $CONFIG; then
    echo "✅ packages: !include_dir_named packages/ — found"
else
    echo "⚠️  MISSING — packages directory not configured!"
    echo ""
    echo "   Add these lines to $CONFIG under homeassistant::"
    echo "   homeassistant:"
    echo "     packages: !include_dir_named packages/"
    ERRORS=$((ERRORS + 1))
fi

# Check Amber dependency
echo ""
echo "============================================="
echo " Checking Amber dependency"
echo "============================================="
echo ""

if [ -f "/config/packages/amber.yaml" ]; then
    echo "✅ hacs-custom-amber-integration package found"
else
    echo "⚠️  hacs-custom-amber-integration NOT found!"
    echo ""
    echo "   This integration requires hacs-custom-amber-integration."
    echo "   Install it first from HACS:"
    echo "   https://github.com/kane81/hacs-custom-amber-integration"
    ERRORS=$((ERRORS + 1))
fi

echo ""
echo "============================================="

if [ $ERRORS -eq 0 ]; then
    echo " ✅ Install complete!"
    echo ""
    echo " Next steps:"
    echo "  1. Add your SEMS credentials to /config/secrets.yaml"
    echo "  2. Reload: Developer Tools → YAML → Reload All"
    echo "     Or restart: Settings → System → Restart"
    echo "  3. Configure sensor helpers via Settings → Helpers"
    echo "  4. Test: python3 /config/scripts/sems_power.py 100"
    echo ""
    echo " ⚡ Future HACS updates will run this script automatically"
    echo "    via the sems_hacs_auto_install automation."
else
    echo " ⚠️  Install complete with $ERRORS warning(s) above."
    echo ""
    echo " Fix the issues listed above before proceeding."
fi

echo "============================================="
