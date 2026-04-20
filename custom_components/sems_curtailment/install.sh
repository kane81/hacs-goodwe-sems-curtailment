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


# -----------------------------------------------------------------------------
# Set automation enable booleans to OFF on first install
# -----------------------------------------------------------------------------
echo ""
echo "🔧 Setting automation enable booleans to OFF..."

set_boolean_off() {
    local entity_id=$1
    if [ -z "$HA_TOKEN" ]; then
        echo "   - $entity_id (skipped — no token yet)"
        return
    fi
    result=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
        "$HA_URL/api/services/input_boolean/turn_off" \
        -H "Authorization: Bearer $HA_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"entity_id\": \"$entity_id\"}")
    if [ "$result" = "200" ]; then
        echo "   ✅ OFF: $entity_id"
    else
        echo "   ⚠️  Could not set $entity_id (HTTP $result)"
    fi
}

set_boolean_off "input_boolean.sems_enable_power_limit"
set_boolean_off "input_boolean.sems_enable_load_tracking"

# -----------------------------------------------------------------------------
# Set default values for user-configurable helpers on first install
# Without initial: set, input_number defaults to min value on first load.
# The script sets sensible defaults via the HA API on first install.
# On subsequent restarts HA restores the user's last set value.
# -----------------------------------------------------------------------------
echo ""
echo "🔧 Setting default values for configurable helpers..."

set_number() {
    local entity_id=$1
    local value=$2
    if [ -z "$HA_TOKEN" ]; then
        echo "   - $entity_id = $value (skipped — no token yet)"
        return
    fi
    result=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
        "$HA_URL/api/services/input_number/set_value" \
        -H "Authorization: Bearer $HA_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"entity_id\": \"$entity_id\", \"value\": $value}")
    if [ "$result" = "200" ]; then
        echo "   ✅ $entity_id = $value"
    else
        echo "   ⚠️  Could not set $entity_id (HTTP $result)"
    fi
}

set_datetime() {
    local entity_id=$1
    local value=$2
    if [ -z "$HA_TOKEN" ]; then
        echo "   - $entity_id = $value (skipped — no token yet)"
        return
    fi
    result=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
        "$HA_URL/api/services/input_datetime/set_datetime" \
        -H "Authorization: Bearer $HA_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"entity_id\": \"$entity_id\", \"time\": \"$value\"}")
    if [ "$result" = "200" ]; then
        echo "   ✅ $entity_id = $value"
    else
        echo "   ⚠️  Could not set $entity_id (HTTP $result)"
    fi
}

set_number "input_number.sems_inverter_capacity_w" 10000
set_number "input_number.sems_load_threshold_watts" 500
set_number "input_number.battery_capacity_kwh" 10
set_number "input_number.battery_max_charge_rate_w" 3000
set_datetime "input_datetime.sems_curtailment_start" "10:00:00"
set_datetime "input_datetime.sems_curtailment_end" "17:00:00"

# -----------------------------------------------------------------------------
# Hide internal state flag helpers from the HA UI
# These are set/cleared by automations and should not be toggled manually.
# Hiding prevents user confusion — they still work, just not visible in Helpers.
# -----------------------------------------------------------------------------
echo ""
echo "🙈 Hiding internal state flag helpers..."

SECRETS=/config/secrets.yaml
HA_URL=$(grep "^ha_url:" $SECRETS 2>/dev/null | sed 's/ha_url: *//' | tr -d '"' || echo "http://localhost:8123")
HA_TOKEN=$(grep "^ha_long_lived_token:" $SECRETS | sed 's/ha_long_lived_token: *//' | tr -d '"')

if [ -z "$HA_TOKEN" ]; then
    echo "   ⚠️  ha_long_lived_token not found in secrets.yaml — skipping auto-hide"
    echo "   You can hide these manually via Settings → Entities → search → Hidden toggle:"
fi

hide_entity() {
    local entity_id=$1
    if [ -z "$HA_TOKEN" ]; then
        echo "   - $entity_id"
        return
    fi
    result=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH \
        "$HA_URL/api/config/entity_registry/$entity_id" \
        -H "Authorization: Bearer $HA_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"hidden_by": "user"}')
    if [ "$result" = "200" ]; then
        echo "   ✅ Hidden: $entity_id"
    else
        echo "   ⚠️  Could not hide $entity_id (HTTP $result) — hide manually if needed"
    fi
}
hide_entity "input_boolean.sems_curtailment_active"
hide_entity "input_number.sems_current_power_limit"

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
