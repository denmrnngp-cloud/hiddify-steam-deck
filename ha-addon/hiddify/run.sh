#!/usr/bin/env bash
set -euo pipefail

CONFIG_JSON="/data/options.json"
HIDDIFY_CONFIG="/data/hiddify/config.json"
HIDDIFY_BIN="/usr/local/bin/sing-box"
STATE_FILE="/data/hiddify/state.json"
LOG_FILE="/data/hiddify/hiddify.log"
HA_URL="http://supervisor/core/api"
HA_TOKEN="${SUPERVISOR_TOKEN:-}"

mkdir -p /data/hiddify

# ── Read add-on options ────────────────────────────────────────────────────────

SUB_URL=$(jq -r '.subscription_url // ""' "$CONFIG_JSON")
PROFILE_IDX=$(jq -r '.selected_profile // 0' "$CONFIG_JSON")
TUN_MODE=$(jq -r '.tun_mode // true' "$CONFIG_JSON")
LOG_LEVEL=$(jq -r '.log_level // "info"' "$CONFIG_JSON")
PROXY_DOMAINS=$(jq -r '.proxy_domains // ""' "$CONFIG_JSON")

echo "[hiddify] Starting Hiddify VPN add-on"
echo "[hiddify] Subscription: ${SUB_URL:0:60}..."
echo "[hiddify] Profile index: $PROFILE_IDX"
echo "[hiddify] TUN mode: $TUN_MODE"

# ── Validate ───────────────────────────────────────────────────────────────────

if [ -z "$SUB_URL" ]; then
    echo "[hiddify] ERROR: subscription_url is empty. Set it in add-on configuration."
    sleep 30
    exit 1
fi

# ── HA state helper ────────────────────────────────────────────────────────────

ha_state() {
    local status="$1"
    local ip="$2"
    local profile="$3"

    # started_at: set on first connect, cleared on disconnect
    local started_at=""
    if [ "$status" = "connected" ]; then
        # preserve existing started_at if already connected, else set now
        local prev_started
        prev_started=$(python3 -c "
import json,sys
try:
    d=json.load(open('$STATE_FILE'))
    print(d.get('started_at','') if d.get('status')=='connected' else '')
except: print('')
" 2>/dev/null || true)
        if [ -n "$prev_started" ]; then
            started_at="$prev_started"
        else
            started_at=$(date +%s)
        fi
    fi

    if [ -n "$HA_TOKEN" ]; then
        curl -s -X POST "$HA_URL/states/sensor.hiddify_status" \
            -H "Authorization: Bearer $HA_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"state\":\"$status\",\"attributes\":{\"friendly_name\":\"Hiddify VPN Status\",\"icon\":\"mdi:vpn\"}}" \
            >/dev/null 2>&1 || true

        curl -s -X POST "$HA_URL/states/sensor.hiddify_ip" \
            -H "Authorization: Bearer $HA_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"state\":\"$ip\",\"attributes\":{\"friendly_name\":\"Hiddify VPN IP\",\"icon\":\"mdi:ip-network\"}}" \
            >/dev/null 2>&1 || true

        curl -s -X POST "$HA_URL/states/sensor.hiddify_profile" \
            -H "Authorization: Bearer $HA_TOKEN" \
            -H "Content-Type: application/json" \
            -d "{\"state\":\"$profile\",\"attributes\":{\"friendly_name\":\"Hiddify Active Profile\",\"icon\":\"mdi:server-network\"}}" \
            >/dev/null 2>&1 || true
    fi

    # Save local state (read by web_ui.py)
    python3 -c "
import json, sys
d = {
    'status':     '$status',
    'ip':         '$ip',
    'profile':    '$profile',
    'started_at': '$started_at',
    'updated':    '$(date -Iseconds)',
}
with open('$STATE_FILE', 'w') as f:
    json.dump(d, f)
" 2>/dev/null || true
}

# ── TUN setup ──────────────────────────────────────────────────────────────────

setup_tun() {
    modprobe tun 2>/dev/null || true
    if [ ! -c /dev/net/tun ]; then
        mkdir -p /dev/net
        mknod /dev/net/tun c 10 200 2>/dev/null || true
        chmod 0666 /dev/net/tun
        echo "[hiddify] Created /dev/net/tun"
    fi
}

# ── Parse subscription ─────────────────────────────────────────────────────────

parse_config() {
    echo "[hiddify] Parsing subscription..."
    ha_state "connecting" "" "Fetching config..."

    TUN_FLAG="--tun"
    [ "$TUN_MODE" = "false" ] && TUN_FLAG="--no-tun"

    PROFILE_NAME=$(python3 /parse_sub.py \
        --url "$SUB_URL" \
        --index "$PROFILE_IDX" \
        $TUN_FLAG \
        --log "$LOG_LEVEL" \
        --proxy-domains "$PROXY_DOMAINS" \
        --out "$HIDDIFY_CONFIG" 2>&1 | tail -1) || {
        echo "[hiddify] ERROR: Failed to parse subscription"
        ha_state "error" "" "Failed to parse subscription"
        return 1
    }

    echo "[hiddify] Profile: $PROFILE_NAME"
    echo "$PROFILE_NAME"
}

# ── Get external IP ────────────────────────────────────────────────────────────

get_ip() {
    local ip
    ip=$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null || \
         curl -s --max-time 5 https://ifconfig.me 2>/dev/null || echo "")
    echo "$ip"
}

# ── Monitor loop ───────────────────────────────────────────────────────────────

monitor_loop() {
    local profile="$1"
    local prev_status=""

    while true; do
        sleep 10

        # Check if sing-box is still running
        if ! kill -0 "$HIDDIFY_PID" 2>/dev/null; then
            echo "[hiddify] Process died, restarting..."
            ha_state "disconnected" "" "$profile"
            return 1
        fi

        # Check TUN interface
        if [ "$TUN_MODE" = "true" ]; then
            if ip link show tun0 >/dev/null 2>&1; then
                if [ "$prev_status" != "connected" ]; then
                    VPN_IP=$(get_ip)
                    echo "[hiddify] Connected. IP: $VPN_IP  Profile: $profile"
                    ha_state "connected" "$VPN_IP" "$profile"
                    prev_status="connected"
                fi
            else
                if [ "$prev_status" != "connecting" ]; then
                    echo "[hiddify] TUN not up yet..."
                    ha_state "connecting" "" "$profile"
                    prev_status="connecting"
                fi
            fi
        fi
    done
}

# ── Cleanup ────────────────────────────────────────────────────────────────────

cleanup() {
    echo "[hiddify] Stopping..."
    ha_state "disconnected" "" ""
    [ -n "${HIDDIFY_PID:-}" ] && kill "$HIDDIFY_PID" 2>/dev/null || true
    wait "${HIDDIFY_PID:-}" 2>/dev/null || true
    [ -n "${WEB_PID:-}" ]  && kill "$WEB_PID"  2>/dev/null || true
    ip link delete tun0 2>/dev/null || true
    exit 0
}

trap cleanup SIGTERM SIGINT SIGQUIT

# ── Main ───────────────────────────────────────────────────────────────────────

[ "$TUN_MODE" = "true" ] && setup_tun

ha_state "connecting" "" "Starting..."

PROFILE_NAME=$(parse_config) || {
    sleep 60
    exit 1
}

echo "[hiddify] Starting sing-box..."
echo "[hiddify] Binary version: $("$HIDDIFY_BIN" version 2>&1 | head -1)"
echo "[hiddify] Config: $HIDDIFY_CONFIG"

export ENABLE_DEPRECATED_LEGACY_DNS_SERVERS=true

"$HIDDIFY_BIN" run \
    -c "$HIDDIFY_CONFIG" \
    2>&1 | while IFS= read -r line; do echo "[core] $line"; done &
HIDDIFY_PID=$!

echo "[hiddify] PID: $HIDDIFY_PID"
echo "[hiddify] /dev/net/tun: $(ls -la /dev/net/tun 2>&1)"
echo "[hiddify] Interfaces after Core.Start: $(ip -br link show 2>/dev/null | tr '\n' ' ')"

# Wait a moment for TUN to come up
sleep 8

echo "[hiddify] Interfaces after wait: $(ip -br link show 2>/dev/null | tr '\n' ' ')"

if [ "$TUN_MODE" = "true" ]; then
    if ip link show tun0 >/dev/null 2>&1; then
        VPN_IP=$(get_ip)
        echo "[hiddify] VPN up. External IP: $VPN_IP"
        ha_state "connected" "$VPN_IP" "$PROFILE_NAME"
    else
        echo "[hiddify] Waiting for TUN interface..."
        ha_state "connecting" "" "$PROFILE_NAME"
    fi
else
    ha_state "connected" "" "$PROFILE_NAME"
fi

# ── Start web dashboard ────────────────────────────────────────────────────────

echo "[hiddify] Starting web dashboard on :8080"
WEB_PORT=8080 python3 /web_ui.py 2>&1 | while IFS= read -r line; do echo "[web] $line"; done &
WEB_PID=$!

# Start monitor in background
monitor_loop "$PROFILE_NAME" &
MONITOR_PID=$!

# Wait for sing-box to exit
wait "$HIDDIFY_PID"
EXIT_CODE=$?

kill "$MONITOR_PID" 2>/dev/null || true
kill "$WEB_PID"     2>/dev/null || true
echo "[hiddify] sing-box exited with code $EXIT_CODE"
ha_state "disconnected" "" ""
exit "$EXIT_CODE"
