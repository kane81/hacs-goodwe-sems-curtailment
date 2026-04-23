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
# User-configured helper values are never overwritten on update.
# =============================================================================

set -e

# Mode: "full" (default) runs full install. "sync" just copies files.
MODE=${1:-full}

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
# Load HA credentials — needed for all API calls below
# -----------------------------------------------------------------------------
SECRETS=/config/secrets.yaml
HA_URL=$(grep "^ha_url:" $SECRETS 2>/dev/null | sed 's/ha_url: *//' | tr -d '"' || echo "http://localhost:8123")
HA_TOKEN=$(grep "^ha_long_lived_token:" $SECRETS 2>/dev/null | sed 's/ha_long_lived_token: *//' | tr -d '"')

if [ -z "$HA_TOKEN" ]; then
    echo ""
    echo "⚠️  ha_long_lived_token not found in secrets.yaml"
    echo "   Skipping helper configuration — run install.sh again after adding your token."
fi

# -----------------------------------------------------------------------------
# Helper functions
# -----------------------------------------------------------------------------

# Get current state of an entity — returns empty string if unavailable
get_state() {
    local entity_id=$1
    [ -z "$HA_TOKEN" ] && echo "" && return
    curl -s \
        "$HA_URL/api/states/$entity_id" \
        -H "Authorization: Bearer $HA_TOKEN" | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('state',''))" 2>/dev/null || echo ""
}

# Set an input_number — only if current state is unavailable or matches default
set_number_if_default() {
    local entity_id=$1
    local default_value=$2
    local description=$3
    [ -z "$HA_TOKEN" ] && echo "   - $entity_id (skipped — no token)" && return

    current=$(get_state "$entity_id")
    if [ -z "$current" ] || [ "$current" = "unavailable" ] || [ "$current" = "unknown" ]; then
        # Entity has no stored state — first install, set default
        curl -s -o /dev/null -X POST \
            "$HA_URL/api/services/input_number/set_value" \
            -H "Authorization: Bearer $HA_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"entity_id\": \"$entity_id\", \"value\": $default_value}"
        echo "   ✅ $description set to $default_value (first install default)"
    else
        echo "   ⏭️  $description already set to $current — keeping user value"
    fi
}

# Set an input_datetime — only if no stored state
set_datetime_if_default() {
    local entity_id=$1
    local default_value=$2
    local description=$3
    [ -z "$HA_TOKEN" ] && echo "   - $entity_id (skipped — no token)" && return

    current=$(get_state "$entity_id")
    if [ -z "$current" ] || [ "$current" = "unavailable" ] || [ "$current" = "unknown" ]; then
        curl -s -o /dev/null -X POST \
            "$HA_URL/api/services/input_datetime/set_datetime" \
            -H "Authorization: Bearer $HA_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"entity_id\": \"$entity_id\", \"time\": \"$default_value\"}"
        echo "   ✅ $description set to $default_value (first install default)"
    else
        echo "   ⏭️  $description already set to $current — keeping user value"
    fi
}

# Set a boolean OFF — only on first install (no stored state)
set_boolean_off_if_new() {
    local entity_id=$1
    [ -z "$HA_TOKEN" ] && echo "   - $entity_id (skipped — no token)" && return

    current=$(get_state "$entity_id")
    if [ -z "$current" ] || [ "$current" = "unavailable" ] || [ "$current" = "unknown" ]; then
        curl -s -o /dev/null -X POST \
            "$HA_URL/api/services/input_boolean/turn_off" \
            -H "Authorization: Bearer $HA_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"entity_id\": \"$entity_id\"}"
        echo "   ✅ OFF: $entity_id (first install default)"
    else
        echo "   ⏭️  $entity_id already $current — keeping user value"
    fi
}

# Hide an entity in the HA UI
hide_entity() {
    local entity_id=$1
    [ -z "$HA_TOKEN" ] && echo "   - $entity_id (skipped — no token)" && return
    result=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH \
        "$HA_URL/api/config/entity_registry/$entity_id" \
        -H "Authorization: Bearer $HA_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"hidden_by": "user"}')
    if [ "$result" = "200" ]; then
        echo "   ✅ Hidden: $entity_id"
    else
        echo "   ⚠️  Could not hide $entity_id (HTTP $result)"
    fi
}

# -----------------------------------------------------------------------------
# Set automation enable booleans to OFF (first install only)
# -----------------------------------------------------------------------------
echo ""
echo "🔧 Setting automation enable booleans..."
set_boolean_off_if_new "input_boolean.sems_enable_power_limit"
set_boolean_off_if_new "input_boolean.sems_enable_load_tracking"

# -----------------------------------------------------------------------------
# Set default values for configurable helpers (first install / full mode only)
# Skipped on startup sync to avoid overwriting user values during HA boot
# -----------------------------------------------------------------------------
if [ "$MODE" = "full" ]; then
echo ""
echo "🔧 Setting default values for configurable helpers..."
set_number_if_default   "input_number.sems_inverter_capacity_w"  10000  "SEMS Inverter Capacity"
set_number_if_default   "input_number.sems_load_threshold_watts" 500    "SEMS Load Threshold"
set_number_if_default   "input_number.battery_capacity_kwh"      10     "Battery Capacity"
set_number_if_default   "input_number.battery_max_charge_rate_w" 3000   "Battery Max Charge Rate"
set_datetime_if_default "input_datetime.sems_curtailment_start"  "10:00:00" "Curtailment Start"
set_datetime_if_default "input_datetime.sems_curtailment_end"    "17:00:00" "Curtailment End"

fi  # end MODE=full

# -----------------------------------------------------------------------------
# Hide internal state flag helpers from the HA UI
# -----------------------------------------------------------------------------
echo ""
echo "🙈 Hiding internal state flag helpers..."
hide_entity "input_boolean.sems_curtailment_active"
hide_entity "input_number.sems_current_power_limit"

echo ""
echo "============================================="
echo " Checking configuration.yaml"
echo "============================================="
echo ""

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
    echo "  3. Configure sensor helpers via Overview → Devices → Helpers"
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
