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
touch $SECRETS

HA_URL=$(grep "^ha_url:" $SECRETS 2>/dev/null | sed 's/ha_url: *//' | tr -d '"' || echo "http://localhost:8123")
HA_TOKEN=$(grep "^ha_long_lived_token:" $SECRETS 2>/dev/null | sed 's/ha_long_lived_token: *//' | tr -d '"')

# -----------------------------------------------------------------------------
# Prompt for SEMS credentials if not already set
# -----------------------------------------------------------------------------
if [ "$MODE" = "full" ]; then
    echo ""
    echo "🔑 Checking SEMS credentials in secrets.yaml..."

    prompt_if_missing() {
        local key=$1 label=$2
        if ! grep -q "^${key}:" $SECRETS; then
            echo ""
            echo -n "   Enter $label: "
            read -r value
            if [ -n "$value" ]; then
                echo "${key}: "${value}"" >> $SECRETS
                echo "   ✅ ${key} saved"
            else
                echo "   ⚠️  Skipped — add ${key} to secrets.yaml manually"
            fi
        else
            echo "   ⏭️  ${key} already set — skipping"
        fi
    }

    prompt_if_missing "sems_email"       "SEMS Portal login email"
    prompt_if_missing "sems_password"    "SEMS Portal password"
    prompt_if_missing "sems_inverter_sn" "Inverter serial number (on inverter label)"
fi

# Check if token is present (should be set by Amber install) — prompt if not
if [ "$MODE" = "full" ] && [ -z "$HA_TOKEN" ]; then
    echo ""
    echo "🔑 HA Long-Lived Access Token not found in secrets.yaml"
    echo "   This should have been set during the Amber integration install."
    echo "   To get a token: Profile avatar (bottom left) → Long-Lived Access Tokens → Create Token"
    echo ""
    read -r -p "   Enter your HA Long-Lived Access Token: " token_input
    if [ -n "$token_input" ]; then
        echo "ha_long_lived_token: \"${token_input}\"" >> $SECRETS
        HA_TOKEN="$token_input"
        echo "   ✅ Token saved to secrets.yaml"
    else
        echo "   ⚠️  Skipped — helper defaults cannot be set without a token"
    fi
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

set_text() {
    local entity_id=$1 value=$2
    [ -z "$HA_TOKEN" ] && return
    ha_post "services/input_text/set_value" "{\"entity_id\": \"$entity_id\", \"value\": \"$value\"}" > /dev/null
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
# Create SEMS dashboard (optional)
# -----------------------------------------------------------------------------
if [ "$MODE" = "full" ]; then
    echo ""
    echo "📊 Dashboard"
    DASHBOARD_DIR="/config/lovelace"
    DASHBOARD_FILE="$DASHBOARD_DIR/sems.yaml"
    LOVELACE_SRC="$SRC/lovelace/sems.yaml"

    mkdir -p "$DASHBOARD_DIR"

    if [ -f "$DASHBOARD_FILE" ]; then
        echo "   ℹ️  SEMS dashboard already exists."
        read -r -p "   Overwrite with default? This resets any customisations. (y/N): " overwrite_dash
        if [[ "$overwrite_dash" =~ ^[Yy]$ ]]; then
            if [ -f "$LOVELACE_SRC" ]; then
                cp "$LOVELACE_SRC" "$DASHBOARD_FILE"
                echo "   ✅ Dashboard overwritten: $DASHBOARD_FILE"
            else
                echo "   ⚠️  Dashboard template not found: $LOVELACE_SRC"
            fi
        else
            echo "   ⏭️  Keeping existing dashboard"
        fi
    else
        read -r -p "   Create SEMS dashboard in sidebar? (Y/n): " create_dash
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

if grep -q "lovelace-sems" $CONFIG; then
    echo "✅ lovelace dashboard entry — found"
elif [ -f "$DASHBOARD_FILE" ]; then
    if grep -q "lovelace-amber" $CONFIG; then
        # Amber already added lovelace: dashboards: — add SEMS entry under existing dashboards:
        sed -i "/lovelace-amber:/a\    lovelace-sems:\n      mode: yaml\n      title: SEMS\n      icon: mdi:solar-power\n      filename: lovelace/sems.yaml\n      show_in_sidebar: true" $CONFIG
        echo "✅ lovelace dashboard entry — added under existing Amber dashboards:"
    elif grep -q "^lovelace:" $CONFIG; then
        sed -i "/^lovelace:/a\  dashboards:\n    lovelace-sems:\n      mode: yaml\n      title: SEMS\n      icon: mdi:solar-power\n      filename: lovelace/sems.yaml\n      show_in_sidebar: true" $CONFIG
        echo "✅ lovelace dashboard entry — added"
    else
        echo "" >> $CONFIG
        echo "lovelace:" >> $CONFIG
        echo "  dashboards:" >> $CONFIG
        echo "    lovelace-sems:" >> $CONFIG
        echo "      mode: yaml" >> $CONFIG
        echo "      title: SEMS" >> $CONFIG
        echo "      icon: mdi:solar-power" >> $CONFIG
        echo "      filename: lovelace/sems.yaml" >> $CONFIG
        echo "      show_in_sidebar: true" >> $CONFIG
        echo "✅ lovelace dashboard entry — added"
    fi
fi

if [ -f "/config/packages/amber.yaml" ]; then
    echo "✅ hacs-custom-amber-integration package found"
else
    echo "⚠️  hacs-custom-amber-integration NOT found!"
    echo "   Install it first: https://github.com/kane81/hacs-custom-amber-integration"
    ERRORS=$((ERRORS + 1))
fi

# -----------------------------------------------------------------------------
# Reload YAML then configure (full mode only)
# -----------------------------------------------------------------------------
if [ "$MODE" = "full" ]; then
    reload_yaml

    # ── System settings ────────────────────────────────────────────────────
    echo ""
    echo "⚙️  Battery & Inverter Details"
    echo "   Press Enter to accept the default value shown in brackets."
    echo ""

    prompt_number() {
        local entity_id=$1 label=$2 default=$3 unit=$4 min_val=$5
        if [ "$(number_needs_default "$entity_id" "$min_val")" = "yes" ]; then
            read -r -p "   $label [$default $unit]: " num_val
            num_val=${num_val:-$default}
            ha_post "services/input_number/set_value" "{\"entity_id\": \"$entity_id\", \"value\": $num_val}" > /dev/null
            echo "   ✅ $label set to $num_val $unit"
        else
            current=$(get_state "$entity_id")
            echo "   ⏭️  $label already set to $current $unit — keeping"
        fi
    }

    prompt_number "input_number.sems_inverter_capacity_w"  \
        "Inverter rated capacity (e.g. GW10K-MS = 10000)" 10000 "W" 0
    prompt_number "input_number.battery_max_charge_rate_w" \
        "Battery max charge rate (AlphaESS Smile5 = 4640)" 3000 "W" 0
    prompt_number "input_number.battery_capacity_kwh"      \
        "Battery Capacity" 10 "kWh" 0
    prompt_number "input_number.sems_load_threshold_watts" \
        "Load change threshold (min watts change before API call)" 500 "W" 0

    # ── Sensor entity IDs ──────────────────────────────────────────────────
    echo ""
    echo "🔌 Battery Sensor Entity IDs"
    echo "   These tell the integration which sensors to read from your battery."
    echo "   Find your sensor IDs in Developer Tools → States."
    echo "   Press Enter to skip any sensor and configure it later in Overview → Devices → Helpers."
    echo ""

    prompt_sensor() {
        local entity_id=$1
        local label=$2
        local example=$3
        current=$(get_state "$entity_id")
        if [ -n "$current" ] && [ "$current" != "unavailable" ] && [ "$current" != "unknown" ]; then
            echo "   ⏭️  $label already set to '$current' — keeping"
        else
            echo "   $label"
            echo "   Example: $example"
            read -r -p "   Enter entity ID (or press Enter to skip): " sensor_val
            if [ -n "$sensor_val" ]; then
                set_text "$entity_id" "$sensor_val"
                echo "   ✅ $label set to $sensor_val"
            else
                echo "   ⏭️  Skipped"
            fi
            echo ""
        fi
    }

    prompt_sensor "input_text.sensor_battery_soc"  "Battery SOC sensor (0-100%)" \
        "sensor.al7011025073833_instantaneous_battery_soc"
    prompt_sensor "input_text.sensor_battery_io"   "Battery I/O Power (negative=charging)" \
        "sensor.al7011025073833_instantaneous_battery_i_o"
    prompt_sensor "input_text.sensor_load"         "House Load sensor (watts)" \
        "sensor.al7011025073833_instantaneous_load"
    prompt_sensor "input_text.sensor_solar"        "Solar Production sensor (watts)" \
        "sensor.al7011025073833_instantaneous_generation"
    prompt_sensor "input_text.sensor_grid"         "Grid Power sensor (negative=export)" \
        "sensor.al7011025073833_instantaneous_grid_i_o_total"

    # ── Enable booleans ────────────────────────────────────────────────────
    echo ""
    echo "🔧 Setting automation enable booleans..."
    set_boolean_if_new "input_boolean.sems_enable_power_limit"   "off"
    set_boolean_if_new "input_boolean.sems_enable_load_tracking" "off"

    # ── Curtailment times (silent defaults only) ───────────────────────────
    set_datetime_if_default "input_datetime.sems_curtailment_start" "09:00:00" "Curtailment Start"
    set_datetime_if_default "input_datetime.sems_curtailment_end"   "17:00:00" "Curtailment End"

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
echo ""
echo " 🔄 Restart Required"
echo "    Go to Settings → System → Restart to apply all changes."
echo "    After restart the SEMS dashboard will appear in your sidebar."
echo "============================================="
