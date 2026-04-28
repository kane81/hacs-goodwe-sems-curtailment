#!/bin/bash
# =============================================================================
# Home Assistant GoodWe SEMS Curtailment - Install Script
# =============================================================================
#
# Usage:
#   bash /config/custom_components/sems_curtailment/install.sh
#
# Mode: "full" (default) runs full install.
#       "sync" just copies files — used on HA startup.
# =============================================================================

set -e

MODE=${1:-full}
SRC=/config/custom_components/sems_curtailment
CONFIG=/config/configuration.yaml
ERRORS=0

echo "============================================="
echo " Home Assistant GoodWe SEMS Curtailment"
echo " Install Script"
echo "============================================="
echo ""

if [ "$MODE" = "sync" ]; then
    echo "⚡ Sync mode — skipping full install steps"
    echo ""
fi

# -----------------------------------------------------------------------------
# Copy files
# -----------------------------------------------------------------------------
echo "📋 Copying automations..."
mkdir -p /config/automations
cp -v $SRC/automations/*.yaml /config/automations/

echo ""
echo "🐍 Copying scripts..."
mkdir -p /config/scripts
cp -v $SRC/scripts/*.py /config/scripts/

echo ""
echo "📦 Copying package..."
mkdir -p /config/packages
cp -v $SRC/packages/sems.yaml /config/packages/

echo ""
echo "📄 Copying templates..."
mkdir -p /config/templates
cp -v $SRC/templates/*.yaml /config/templates/

# -----------------------------------------------------------------------------
# Load credentials
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

ha_post() {
    local endpoint=$1 data=$2
    curl -s -o /dev/null -w "%{http_code}" -X POST \
        "$HA_URL/api/$endpoint" \
        -H "Authorization: Bearer $HA_TOKEN" \
        -H "Content-Type: application/json" \
        -d "$data"
}

get_state() {
    local entity_id=$1
    [ -z "$HA_TOKEN" ] && echo "" && return
    curl -s \
        "$HA_URL/api/states/$entity_id" \
        -H "Authorization: Bearer $HA_TOKEN" | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('state',''))" 2>/dev/null || echo ""
}

number_needs_default() {
    local entity_id=$1 min_value=$2
    [ -z "$HA_TOKEN" ] && echo "yes" && return
    current=$(get_state "$entity_id")
    if [ -z "$current" ] || [ "$current" = "unavailable" ] || [ "$current" = "unknown" ] || \
       python3 -c "exit(0 if abs(float('${current:-0}') - float('$min_value')) < 0.0001 else 1)" 2>/dev/null; then
        echo "yes"
    else
        echo "no"
    fi
}

set_number_if_default() {
    local entity_id=$1 default_value=$2 description=$3 min_value=${4:-0}
    [ -z "$HA_TOKEN" ] && echo "   - $entity_id (skipped — no token)" && return
    if [ "$(number_needs_default "$entity_id" "$min_value")" = "yes" ]; then
        ha_post "services/input_number/set_value" "{\"entity_id\": \"$entity_id\", \"value\": $default_value}" > /dev/null
        echo "   ✅ $description set to $default_value"
    else
        current=$(get_state "$entity_id")
        echo "   ⏭️  $description already set to $current — keeping user value"
    fi
}

set_datetime_if_default() {
    local entity_id=$1 default_value=$2 description=$3
    [ -z "$HA_TOKEN" ] && echo "   - $entity_id (skipped — no token)" && return
    current=$(get_state "$entity_id")
    if [ -z "$current" ] || [ "$current" = "unavailable" ] || [ "$current" = "unknown" ] || \
       [ "$current" = "00:00:00" ]; then
        ha_post "services/input_datetime/set_datetime" "{\"entity_id\": \"$entity_id\", \"time\": \"$default_value\"}" > /dev/null
        echo "   ✅ $description set to $default_value"
    else
        echo "   ⏭️  $description already set to $current — keeping user value"
    fi
}

set_boolean_if_new() {
    local entity_id=$1 state=$2
    [ -z "$HA_TOKEN" ] && echo "   - $entity_id (skipped — no token)" && return
    current=$(get_state "$entity_id")
    if [ -z "$current" ] || [ "$current" = "unavailable" ] || [ "$current" = "unknown" ]; then
        ha_post "services/input_boolean/turn_${state}" "{\"entity_id\": \"$entity_id\"}" > /dev/null
        echo "   ✅ ${state^^}: $entity_id (first install default)"
    else
        echo "   ⏭️  $entity_id already $current — keeping user value"
    fi
}

reload_yaml() {
    [ -z "$HA_TOKEN" ] && return
    echo ""
    echo "🔄 Reloading HA YAML configuration..."
    result=$(ha_post "services/homeassistant/reload_all" "{}")
    if [ "$result" = "200" ]; then
        echo "   ✅ YAML reloaded — waiting 15 seconds for helpers to initialise..."
        sleep 15
    else
        echo "   ⚠️  Could not reload YAML (HTTP $result)"
    fi
}

# -----------------------------------------------------------------------------
# Create Solar dashboard (optional)
# -----------------------------------------------------------------------------
echo ""
echo "📊 Dashboard"
DASHBOARD_DIR="/config/lovelace"
DASHBOARD_FILE="$DASHBOARD_DIR/sems.yaml"
LOVELACE_SRC="$SRC/lovelace/sems.yaml"

mkdir -p "$DASHBOARD_DIR"

if [ -f "$DASHBOARD_FILE" ]; then
    echo "   ⏭️  Dashboard already exists — skipping"
    echo "   (Delete $DASHBOARD_FILE and re-run to recreate)"
else
    read -r -p "   Create Solar dashboard in sidebar? (Y/n): " create_dash
    if [[ ! "$create_dash" =~ ^[Nn]$ ]]; then
        if [ -f "$LOVELACE_SRC" ]; then
            cp "$LOVELACE_SRC" "$DASHBOARD_FILE"
            echo "   ✅ Dashboard created: $DASHBOARD_FILE"
        else
            echo "   ⚠️  Dashboard template not found: $LOVELACE_SRC"
        fi
    else
        echo "   Skipped — see Dashboard Card section in README to add manually later."
    fi
fi

# -----------------------------------------------------------------------------
# Update configuration.yaml
# -----------------------------------------------------------------------------
echo ""
echo "============================================="
echo " Checking configuration.yaml"
echo "============================================="
echo ""

if grep -q "include_dir_merge_list automations" $CONFIG; then
    echo "✅ automation: !include_dir_merge_list automations/ — found"
elif grep -q "automation: !include automations.yaml" $CONFIG; then
    sed -i "s|automation: !include automations.yaml|automation: !include_dir_merge_list automations/|g" $CONFIG
    echo "✅ automation: updated to !include_dir_merge_list automations/"
else
    echo "" >> $CONFIG
    echo "automation: !include_dir_merge_list automations/" >> $CONFIG
    echo "✅ automation: !include_dir_merge_list automations/ — added"
fi

if grep -q "include_dir_named packages" $CONFIG; then
    echo "✅ packages: !include_dir_named packages/ — found"
elif grep -q "^homeassistant:" $CONFIG; then
    sed -i "/^homeassistant:/a\\  packages: !include_dir_named packages/" $CONFIG
    echo "✅ packages: !include_dir_named packages/ — added"
else
    echo "" >> $CONFIG
    echo "homeassistant:" >> $CONFIG
    echo "  packages: !include_dir_named packages/" >> $CONFIG
    echo "✅ homeassistant: packages: — added"
fi

if grep -q "lovelace-solar" $CONFIG; then
    echo "✅ lovelace dashboard entry — found"
elif [ -f "$DASHBOARD_FILE" ]; then
    if grep -q "^lovelace:" $CONFIG; then
        sed -i "/^lovelace:/a\\  dashboards:\n    lovelace-solar:\n      mode: yaml\n      title: Solar\n      icon: mdi:solar-power\n      filename: lovelace/sems.yaml\n      show_in_sidebar: true" $CONFIG
    else
        echo "" >> $CONFIG
        echo "lovelace:" >> $CONFIG
        echo "  dashboards:" >> $CONFIG
        echo "    lovelace-solar:" >> $CONFIG
        echo "      mode: yaml" >> $CONFIG
        echo "      title: Solar" >> $CONFIG
        echo "      icon: mdi:solar-power" >> $CONFIG
        echo "      filename: lovelace/sems.yaml" >> $CONFIG
        echo "      show_in_sidebar: true" >> $CONFIG
    fi
    echo "✅ lovelace dashboard entry — added"
fi

if [ -f "/config/packages/amber.yaml" ]; then
    echo "✅ hacs-custom-amber-integration package found"
else
    echo "⚠️  hacs-custom-amber-integration NOT found!"
    echo "   Install it first: https://github.com/kane81/hacs-custom-amber-integration"
    ERRORS=$((ERRORS + 1))
fi

# -----------------------------------------------------------------------------
# Reload YAML then set defaults (full mode only)
# -----------------------------------------------------------------------------
if [ "$MODE" = "full" ]; then
    reload_yaml

    echo ""
    echo "🔧 Setting automation enable booleans..."
    set_boolean_if_new "input_boolean.sems_enable_power_limit"   "off"
    set_boolean_if_new "input_boolean.sems_enable_load_tracking" "off"

    echo ""
    echo "🔧 Setting default values for configurable helpers..."
    set_number_if_default   "input_number.sems_inverter_capacity_w"   10000     "SEMS Inverter Capacity"    0
    set_number_if_default   "input_number.sems_load_threshold_watts"  500       "SEMS Load Threshold"       0
    set_number_if_default   "input_number.battery_capacity_kwh"       10        "Battery Capacity"          0
    set_number_if_default   "input_number.battery_max_charge_rate_w"  3000      "Battery Max Charge Rate"   0
    set_datetime_if_default "input_datetime.sems_curtailment_start"   "09:00:00" "Curtailment Start"
    set_datetime_if_default "input_datetime.sems_curtailment_end"     "17:00:00" "Curtailment End"

    reload_yaml
fi

echo ""
echo "============================================="
if [ $ERRORS -eq 0 ]; then
    echo " ✅ Install complete!"
else
    echo " ⚠️  Install complete with $ERRORS warning(s) above."
fi
echo ""
echo " ⚡ Future HACS updates will run this script automatically"
echo "    via the sems_hacs_auto_install automation."
echo "============================================="
echo ""

if [ "$MODE" = "full" ]; then
    read -r -p "🔄 Restart Home Assistant now to apply all changes? (Y/n): " do_restart
    if [[ ! "$do_restart" =~ ^[Nn]$ ]]; then
        echo ""
        echo "   Restarting Home Assistant..."
        curl -s -o /dev/null -X POST \
            "$HA_URL/api/services/homeassistant/restart" \
            -H "Authorization: Bearer $HA_TOKEN" \
            -H "Content-Type: application/json"
        echo "   ✅ Restart initiated — HA will be back in about 30 seconds."
    else
        echo ""
        echo "   Remember to restart HA manually:"
        echo "   Settings → System → Restart"
    fi
fi
