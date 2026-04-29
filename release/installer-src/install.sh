#!/bin/bash
# Hiddify Linux Installer
# Supported: Ubuntu 22.04+, Debian 12+, SteamOS (Steam Deck)
set -e

# Ensure valid CWD (makeself may clean up its tmpdir before we run)
cd /tmp 2>/dev/null || cd / 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="/opt/hiddify"
APP_DIR="/home/deck/.local/share/app.hiddify.com"
SYSTEM_APP_DIR="/var/lib/hiddify"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}!${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*"; exit 1; }
info() { echo -e "${BLUE}→${NC} $*"; }

echo ""
echo "  ██╗  ██╗██╗██████╗ ██████╗ ██╗███████╗██╗   ██╗"
echo "  ██║  ██║██║██╔══██╗██╔══██╗██║██╔════╝╚██╗ ██╔╝"
echo "  ███████║██║██║  ██║██║  ██║██║█████╗   ╚████╔╝ "
echo "  ██╔══██║██║██║  ██║██║  ██║██║██╔══╝    ╚██╔╝  "
echo "  ██║  ██║██║██████╔╝██████╔╝██║██║        ██║   "
echo "  ╚═╝  ╚═╝╚═╝╚═════╝ ╚═════╝ ╚═╝╚═╝        ╚═╝   "
echo ""

# Root check: when called from GUI wizard it is already running via sudo -S
# When launched directly (double-click / xterm) — re-exec with sudo automatically
if [ "$EUID" -ne 0 ] && [ -z "$HIDDIFY_WIZARD" ]; then
    echo "Requesting root privileges..."
    exec sudo bash "$0" "$@"
fi

# ── Platform detection ──────────────────────────────────────────────────────────

IS_STEAMDECK=0
if [ -f /etc/os-release ]; then
    . /etc/os-release
    [[ "${ID:-}" == "steamos" ]] && IS_STEAMDECK=1
fi
[ $IS_STEAMDECK -eq 1 ] && info "Steam Deck detected" || info "Platform: ${PRETTY_NAME:-Linux}"

if [ $IS_STEAMDECK -eq 1 ]; then
    INSTALL_LOG="/home/deck/.local/share/app.hiddify.com/install-debug.log"
else
    INSTALL_LOG="/tmp/hiddify-install-debug.log"
fi
mkdir -p "$(dirname "$INSTALL_LOG")" 2>/dev/null || true
touch "$INSTALL_LOG" 2>/dev/null || true
exec > >(tee -a "$INSTALL_LOG") 2>&1
info "Installer debug log: $INSTALL_LOG"

# ── Uninstall menu (shown when already installed) ───────────────────────────────

uninstall_hiddify() {
    info "Uninstalling Hiddify..."

    # ── 1. Stop all processes ───────────────────────────────────────────────

    info "  Stopping all Hiddify processes..."

    # Stop system service (may have been created by the GUI app)
    systemctl stop hiddify.service 2>/dev/null || true
    systemctl disable hiddify.service 2>/dev/null || true
    rm -f /etc/systemd/system/hiddify.service
    systemctl daemon-reload 2>/dev/null || true

    # Stop user service (used by Decky plugin)
    su -l deck -c "XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus systemctl --user stop hiddify 2>/dev/null; systemctl --user disable hiddify 2>/dev/null; systemctl --user daemon-reload 2>/dev/null" 2>/dev/null || true
    rm -f /home/deck/.config/systemd/user/hiddify.service

    # Kill GUI process (may be launched as ./hiddify — match by process name)
    pkill -TERM -x hiddify 2>/dev/null || true
    sleep 1
    pkill -KILL -x hiddify 2>/dev/null || true

    # Kill CLI (HiddifyCli run / any variant)
    pkill -TERM -f "HiddifyC[l]i" 2>/dev/null || true
    sleep 1
    pkill -KILL -f "HiddifyC[l]i" 2>/dev/null || true

    # Stop transient GUI-managed services (app-hiddify@<uuid>.service)
    su -l deck -c "XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus systemctl --user list-units 'app-hiddify@*.service' --no-legend --plain --no-pager 2>/dev/null" 2>/dev/null \
        | awk '{print $1}' \
        | while read -r unit; do
            [ -n "$unit" ] && su -l deck -c "XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus systemctl --user stop '$unit' 2>/dev/null" 2>/dev/null || true
          done

    # Free gRPC port and remove tun0 interface
    fuser -k 17078/tcp 2>/dev/null || true
    ip link delete tun0 2>/dev/null || true

    # ── 2. Remove Decky plugin ──────────────────────────────────────────────

    PLUGIN_DIR="/home/deck/homebrew/plugins/decky-hiddify"
    if [ -d "$PLUGIN_DIR" ]; then
        info "  Removing Decky plugin..."
        rm -rf "$PLUGIN_DIR"
        systemctl restart plugin_loader 2>/dev/null || true
        ok "Decky plugin removed"
    fi

    # ── 3. Remove sudoers and polkit rules ──────────────────────────────────
    rm -f /etc/sudoers.d/hiddify /etc/sudoers.d/zz-hiddify /etc/sudoers.d/zz-deck-nopasswd
    rm -f /etc/polkit-1/rules.d/10-hiddify.rules
    rm -f /usr/share/polkit-1/rules.d/10-hiddify.rules
    systemctl restart polkit 2>/dev/null || true

    # ── 4. Remove application files and persistent state ────────────────────
    rm -rf "$INSTALL_DIR"
    rm -rf "$APP_DIR"
    rm -rf "$SYSTEM_APP_DIR"

    # ── 5. Remove desktop integration ───────────────────────────────────────
    if [ $IS_STEAMDECK -eq 1 ]; then
        rm -f /home/deck/.local/share/applications/hiddify.desktop
        rm -f /home/deck/Desktop/hiddify.desktop
        rm -f /home/deck/.local/share/icons/hicolor/256x256/apps/hiddify.png
        su -l deck -c "gtk-update-icon-cache ~/.local/share/icons/hicolor/ 2>/dev/null" 2>/dev/null || true
        steamos-readonly enable 2>/dev/null || true
    else
        rm -f /usr/share/applications/hiddify.desktop
        rm -f /usr/share/icons/hicolor/256x256/apps/hiddify.png
        update-desktop-database /usr/share/applications 2>/dev/null || true
    fi

    echo ""
    echo -e "${GREEN}✓ Hiddify fully removed (client, plugin, services, saved state).${NC}"
}

if [ -d "$INSTALL_DIR" ] && [ -f "$INSTALL_DIR/HiddifyCli" ]; then
    if [ "${HIDDIFY_CLEAN_INSTALL:-0}" = "1" ]; then
        info "Clean install requested — removing previous Hiddify installation first..."
        uninstall_hiddify
    else
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${YELLOW}Hiddify is already installed in $INSTALL_DIR${NC}"
    echo ""
    echo "  [1] Reinstall (update)"
    echo "  [2] Uninstall completely"
    echo "  [3] Cancel"
    echo ""
    read -r -p "Choice [1/2/3]: " CHOICE
    case "$CHOICE" in
        2)
            uninstall_hiddify
            exit 0
            ;;
        3)
            echo "Cancelled."
            exit 0
            ;;
        *)
            info "Reinstalling..."
            ;;
    esac
    fi
fi

# ── [1/6] Install files ─────────────────────────────────────────────────────────

echo ""
info "[1/6] Installing files to $INSTALL_DIR..."

# SteamOS: /usr is a read-only filesystem; /opt lives on a separate persistent partition
if [ $IS_STEAMDECK -eq 1 ]; then
    steamos-readonly disable 2>/dev/null || true
fi

rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR/." "$INSTALL_DIR/"

# Remove installer-only files from the install directory
rm -f "$INSTALL_DIR/install.sh" \
      "$INSTALL_DIR/setup.sh" \
      "$INSTALL_DIR/setup-clean.sh" \
      "$INSTALL_DIR/wizard.py" \
      "$INSTALL_DIR/hiddify.service" 2>/dev/null || true

# Remove conflicting system libs (libssl/libcrypto/libgcc conflict with system versions)
for lib in libcrypto.so.3 libssl.so.3 libgcc_s.so.1; do
    rm -f "$INSTALL_DIR/lib/$lib" 2>/dev/null && warn "  removed conflicting lib: $lib" || true
done

# Set permissions: directory readable by regular users
chmod -R a+rX "$INSTALL_DIR"
chmod +x "$INSTALL_DIR/hiddify" "$INSTALL_DIR/HiddifyCli" 2>/dev/null || true

ok "Files installed"

# ── [2/6] patchelf + setcap ────────────────────────────────────────────────────

echo ""
info "[2/6] Applying patchelf and capabilities..."

# Find patchelf: bundled first, then system
if [ -f "$INSTALL_DIR/_tools/patchelf" ]; then
    PATCHELF="$INSTALL_DIR/_tools/patchelf"
    chmod +x "$PATCHELF"
elif command -v patchelf &>/dev/null; then
    PATCHELF=patchelf
else
    PATCHELF=""
    warn "patchelf not found — binaries will only work from $INSTALL_DIR"
fi

if [ -n "$PATCHELF" ]; then
    # HiddifyCli: replace relative ./lib/hiddify-core.so with bare name + absolute RPATH
    # This allows running from any CWD (cache.db is created in CWD)
    "$PATCHELF" --replace-needed ./lib/hiddify-core.so hiddify-core.so \
        "$INSTALL_DIR/HiddifyCli" 2>/dev/null || true
    "$PATCHELF" --set-rpath "$INSTALL_DIR/lib:$INSTALL_DIR/usr/lib" \
        "$INSTALL_DIR/HiddifyCli" 2>/dev/null || true

    # hiddify GUI: absolute RPATH (required when setcap strips LD_LIBRARY_PATH)
    "$PATCHELF" --set-rpath "$INSTALL_DIR/lib:$INSTALL_DIR/usr/lib" \
        "$INSTALL_DIR/hiddify" 2>/dev/null || true

    # libtray_manager_plugin.so: needs ayatana libs from $INSTALL_DIR/lib
    # DT_RUNPATH of the main binary does not propagate to indirect dependencies
    "$PATCHELF" --set-rpath "$INSTALL_DIR/lib" \
        "$INSTALL_DIR/lib/libtray_manager_plugin.so" 2>/dev/null || true

    ok "patchelf applied (absolute RPATH)"
fi

# setcap: CAP_NET_ADMIN is required to create the TUN interface
# Must be applied AFTER patchelf (patchelf resets capabilities)
if command -v setcap &>/dev/null; then
    setcap 'cap_net_admin,cap_net_bind_service,cap_net_raw=+eip' "$INSTALL_DIR/HiddifyCli"
    setcap 'cap_net_admin,cap_net_bind_service,cap_net_raw=+eip' "$INSTALL_DIR/hiddify"
    ok "setcap applied (CAP_NET_ADMIN, CAP_NET_BIND_SERVICE, CAP_NET_RAW)"
else
    warn "setcap not found — VPN requires root or AmbientCapabilities"
fi

# Passwordless sudo for HiddifyCli and cleanup helpers used by the Decky plugin
SUDOERS_FILE="/etc/sudoers.d/zz-hiddify"
cat > "$SUDOERS_FILE" <<EOF
deck ALL=(ALL) NOPASSWD: $INSTALL_DIR/HiddifyCli *
deck ALL=(ALL) NOPASSWD: /usr/bin/ip *
deck ALL=(ALL) NOPASSWD: /usr/bin/fuser *
EOF
chmod 0440 "$SUDOERS_FILE"
ok "Passwordless sudo configured for HiddifyCli and cleanup helpers"

# Polkit rule — allow deck user to configure DNS/routes without password prompts.
# Written to /etc/polkit-1/rules.d/ which is on the writable partition and
# survives SteamOS A/B updates (unlike /usr/share which is squashfs).
# The plugin also re-applies this rule on every load as a belt-and-suspenders.
mkdir -p /etc/polkit-1/rules.d
POLKIT_TMP="/etc/polkit-1/rules.d/.10-hiddify.rules.tmp"
cat > "$POLKIT_TMP" << 'POLKIT'
polkit.addRule(function(action, subject) {
    var YES = polkit.Result.YES;
    var permission = {
        "org.freedesktop.resolve1.set-domains": YES,
        "org.freedesktop.resolve1.set-default-route": YES,
        "org.freedesktop.resolve1.set-dns-servers": YES,
        "org.freedesktop.resolve1.set-dns-over-tls": YES,
        "org.freedesktop.resolve1.set-dnssec": YES,
        "org.freedesktop.resolve1.set-dnssec-negative-trust-anchors": YES,
        "org.freedesktop.resolve1.set-llmnr": YES,
        "org.freedesktop.resolve1.set-mdns": YES,
        "org.freedesktop.resolve1.revert": YES,
        "org.freedesktop.NetworkManager.network-control": YES,
        "org.freedesktop.NetworkManager.reload": YES,
        "org.freedesktop.NetworkManager.settings.modify.global-dns": YES,
        "org.freedesktop.NetworkManager.settings.modify.system": YES,
        "org.freedesktop.NetworkManager.wifi.share.open": YES
    };
    if (subject.user == "deck") {
        return permission[action.id];
    }
});
POLKIT
chmod 0644 "$POLKIT_TMP"
mv -f "$POLKIT_TMP" /etc/polkit-1/rules.d/10-hiddify.rules
systemctl restart polkit 2>/dev/null || true
ok "Polkit rule configured (no password for DNS/route/NM changes)"

# GUI wrapper script (used by the desktop shortcut)
cat > "$INSTALL_DIR/hiddify-gui" << 'WRAPPER'
#!/bin/bash
cd "$(dirname "$(readlink -f "$0")")"
exec ./hiddify "$@"
WRAPPER
chmod a+rx "$INSTALL_DIR/hiddify-gui"

# ── [3/6] systemd service ──────────────────────────────────────────────────────

echo ""
info "[3/6] Configuring systemd service..."

if [ $IS_STEAMDECK -eq 1 ]; then
    # SteamOS: user service (lives in /home — survives OS A/B updates)
    # HiddifyCli gets caps via setcap (user services don't support AmbientCapabilities)
    SERVICE_DIR="/home/deck/.config/systemd/user"
    mkdir -p "$APP_DIR" "$SYSTEM_APP_DIR"
    if [ -d "$APP_DIR/data" ] && [ ! -L "$APP_DIR/data" ]; then
        mkdir -p "$SYSTEM_APP_DIR/data"
        cp -a "$APP_DIR/data/." "$SYSTEM_APP_DIR/data/" 2>/dev/null || true
        rm -rf "$APP_DIR/data"
    fi
    if [ ! -e "$APP_DIR/data" ]; then
        mkdir -p "$SYSTEM_APP_DIR/data"
        ln -s "$SYSTEM_APP_DIR/data" "$APP_DIR/data"
    fi
    if [ -d "$APP_DIR/configs" ] && [ ! -L "$APP_DIR/configs" ]; then
        mkdir -p "$SYSTEM_APP_DIR/configs"
        cp -a "$APP_DIR/configs/." "$SYSTEM_APP_DIR/configs/" 2>/dev/null || true
        rm -rf "$APP_DIR/configs"
    fi
    if [ ! -e "$APP_DIR/configs" ]; then
        mkdir -p "$SYSTEM_APP_DIR/configs"
        ln -s "$SYSTEM_APP_DIR/configs" "$APP_DIR/configs"
    fi
    if [ -f "$APP_DIR/db.sqlite" ] && [ ! -L "$APP_DIR/db.sqlite" ]; then
        cp -a "$APP_DIR/db.sqlite" "$SYSTEM_APP_DIR/db.sqlite" 2>/dev/null || true
        rm -f "$APP_DIR/db.sqlite"
    fi
    if [ ! -e "$APP_DIR/db.sqlite" ]; then
        touch "$SYSTEM_APP_DIR/db.sqlite"
        ln -s "$SYSTEM_APP_DIR/db.sqlite" "$APP_DIR/db.sqlite"
    fi
    mkdir -p "$SERVICE_DIR"

    HIDDIFY_SETTINGS_PATH="$APP_DIR/data/decky-hiddify-settings.json"
    cat > "$HIDDIFY_SETTINGS_PATH" << 'JSON'
{
  "region": "ru",
  "balancer-strategy": "round-robin",
  "block-ads": false,
  "use-xray-core-when-possible": false,
  "execute-config-as-is": false,
  "log-level": "warn",
  "resolve-destination": false,
  "ipv6-mode": "ipv4_only",
  "remote-dns-address": "tcp://8.8.8.8",
  "remote-dns-domain-strategy": "",
  "direct-dns-address": "1.1.1.1",
  "direct-dns-domain-strategy": "",
  "mixed-port": 12334,
  "tproxy-port": 12335,
  "direct-port": 12337,
  "redirect-port": 12336,
  "tun-implementation": "gvisor",
  "mtu": 9000,
  "strict-route": true,
  "connection-test-url": "http://captive.apple.com/hotspot-detect.html",
  "url-test-interval": 600,
  "enable-clash-api": true,
  "clash-api-port": 16756,
  "enable-tun": true,
  "set-system-proxy": false,
  "bypass-lan": false,
  "allow-connection-from-lan": false,
  "enable-fake-dns": false,
  "independent-dns-cache": true,
  "rules": [],
  "tls-tricks": {
    "enable-fragment": false,
    "fragment-size": "10-30",
    "fragment-sleep": "2-8",
    "mixed-sni-case": false,
    "enable-padding": false,
    "padding-size": "1-1500"
  },
  "warp": {
    "enable": false,
    "mode": "warp_over_proxy",
    "wireguard-config": "",
    "license-key": "",
    "account-id": "",
    "access-token": "",
    "clean-ip": "auto",
    "clean-port": 0,
    "noise": "1-3",
    "noise-size": "10-30",
    "noise-delay": "10-30",
    "noise-mode": "m4"
  },
  "warp2": {
    "enable": false,
    "mode": "warp_over_proxy",
    "wireguard-config": "",
    "license-key": "",
    "account-id": "",
    "access-token": "",
    "clean-ip": "auto",
    "clean-port": 0,
    "noise": "1-3",
    "noise-size": "10-30",
    "noise-delay": "10-30",
    "noise-mode": "m4"
  }
}
JSON

    cat > "$SERVICE_DIR/hiddify.service" << EOF
[Unit]
Description=Hiddify VPN Core Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
# CWD: cache.db is created here (user-writable); hiddify-core.so is found via absolute RUNPATH
WorkingDirectory=/home/deck/.local/share/app.hiddify.com
Environment=HOME=/home/deck USER=deck
ExecStart=$INSTALL_DIR/HiddifyCli run -c /home/deck/.local/share/app.hiddify.com/data/current-config.json --tun -d /home/deck/.local/share/app.hiddify.com/data/decky-hiddify-settings.json
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

    chown deck:deck "$SERVICE_DIR/hiddify.service"
    export XDG_RUNTIME_DIR="/run/user/1000"
    su -l deck -c "XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus systemctl --user daemon-reload && systemctl --user enable hiddify" 2>/dev/null || true
    chown -R deck:deck "$APP_DIR" "$SYSTEM_APP_DIR" 2>/dev/null || true

    ok "User systemd service configured (Steam Deck)"
else
    # Regular Linux: system service with AmbientCapabilities
    CURRENT_USER="${SUDO_USER:-$(logname 2>/dev/null || echo root)}"
    USER_HOME=$(eval echo "~$CURRENT_USER")
    USER_DATA_DIR="$USER_HOME/.local/share/app.hiddify.com"

    cat > "/etc/systemd/system/hiddify.service" << EOF
[Unit]
Description=Hiddify VPN Core Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$USER_DATA_DIR
Environment=HOME=$USER_HOME USER=$CURRENT_USER
ExecStart=$INSTALL_DIR/HiddifyCli run -c $USER_DATA_DIR/data/current-config.json --tun
Restart=on-failure
RestartSec=5
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_NET_RAW
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_NET_RAW

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable hiddify
    ok "System systemd service configured"
fi

# ── [4/6] /dev/net/tun ────────────────────────────────────────────────────────

echo ""
info "[4/6] TUN device..."

modprobe tun 2>/dev/null || true
if [ ! -c /dev/net/tun ]; then
    mkdir -p /dev/net
    mknod /dev/net/tun c 10 200
    chmod 0666 /dev/net/tun
    ok "/dev/net/tun created"
else
    ok "/dev/net/tun already exists"
fi

# ── [5/6] Desktop integration ──────────────────────────────────────────────────

echo ""
info "[5/6] Desktop integration..."

if [ $IS_STEAMDECK -eq 1 ]; then
    DECK_HOME="/home/deck"
    mkdir -p "$DECK_HOME/.local/share/icons/hicolor/256x256/apps"
    mkdir -p "$DECK_HOME/.local/share/applications"

    # Application icon
    [ -f "$INSTALL_DIR/hiddify.png" ] && \
        cp "$INSTALL_DIR/hiddify.png" "$DECK_HOME/.local/share/icons/hicolor/256x256/apps/hiddify.png"

    # Create app data directory (required as CWD for HiddifyCli)
    mkdir -p "$DECK_HOME/.local/share/app.hiddify.com/data"

    cat > "$DECK_HOME/.local/share/applications/hiddify.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Hiddify
Exec=$INSTALL_DIR/hiddify-gui
Icon=hiddify
Terminal=false
StartupWMClass=app.hiddify.com
Categories=Network;Internet;
MimeType=x-scheme-handler/hiddify;x-scheme-handler/v2ray;x-scheme-handler/sing-box;
EOF

    # Desktop shortcut
    mkdir -p "$DECK_HOME/Desktop"
    cat > "$DECK_HOME/Desktop/hiddify.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Hiddify
Exec=$INSTALL_DIR/hiddify-gui
Icon=hiddify
Terminal=false
StartupWMClass=app.hiddify.com
Categories=Network;Internet;
MimeType=x-scheme-handler/hiddify;x-scheme-handler/v2ray;x-scheme-handler/sing-box;
EOF

    chown -R deck:deck \
        "$DECK_HOME/.local/share/icons/hicolor/256x256/apps/hiddify.png" \
        "$DECK_HOME/.local/share/applications/hiddify.desktop" \
        "$DECK_HOME/Desktop/hiddify.desktop" \
        "$DECK_HOME/.local/share/app.hiddify.com" 2>/dev/null || true

    # Mark desktop file as trusted (KDE Plasma requires this to launch from desktop)
    chmod +x "$DECK_HOME/Desktop/hiddify.desktop"
    su -l deck -c "gio set ~/Desktop/hiddify.desktop metadata::trusted true 2>/dev/null" 2>/dev/null || true

    # Update KDE icon cache
    su -l deck -c "gtk-update-icon-cache ~/.local/share/icons/hicolor/ 2>/dev/null" 2>/dev/null || true

    steamos-readonly enable 2>/dev/null || true

else
    install -Dm644 "$INSTALL_DIR/hiddify.png" \
        "/usr/share/icons/hicolor/256x256/apps/hiddify.png" 2>/dev/null || true

    cat > "/usr/share/applications/hiddify.desktop" << EOF
[Desktop Entry]
Type=Application
Name=Hiddify
Exec=$INSTALL_DIR/hiddify-gui
Icon=hiddify
Terminal=false
StartupWMClass=app.hiddify.com
Categories=Network;Internet;
MimeType=x-scheme-handler/hiddify;x-scheme-handler/v2ray;x-scheme-handler/sing-box;
EOF

    update-desktop-database /usr/share/applications 2>/dev/null || true
    gtk-update-icon-cache /usr/share/icons/hicolor/ 2>/dev/null || true
fi

ok "Desktop integration done"

# ── [6/6] Decky plugin ────────────────────────────────────────────────────────

if [ $IS_STEAMDECK -eq 1 ]; then
    echo ""
    info "[6/6] Updating Decky plugin..."

    PLUGINS_DIR="/home/deck/homebrew/plugins"
    PLUGIN_DIR="$PLUGINS_DIR/decky-hiddify"
    PLUGIN_ZIP="$INSTALL_DIR/decky-hiddify.zip"
    TMP_PLUGIN_DIR="/tmp/hiddify-decky-plugin"

    if [ ! -d "$PLUGINS_DIR" ]; then
        warn "Decky Loader plugins directory not found — skipping plugin install"
    elif [ ! -f "$PLUGIN_ZIP" ]; then
        warn "Bundled decky-hiddify.zip not found — skipping plugin install"
    elif ! command -v unzip >/dev/null 2>&1; then
        warn "unzip is not installed — skipping plugin install"
    else
        rm -rf "$TMP_PLUGIN_DIR"
        mkdir -p "$TMP_PLUGIN_DIR"

        if unzip -oq "$PLUGIN_ZIP" -d "$TMP_PLUGIN_DIR"; then
            rm -rf "$PLUGIN_DIR"

            if [ -d "$TMP_PLUGIN_DIR/decky-hiddify" ]; then
                mv "$TMP_PLUGIN_DIR/decky-hiddify" "$PLUGIN_DIR"
            else
                mkdir -p "$PLUGIN_DIR"
                cp -r "$TMP_PLUGIN_DIR/." "$PLUGIN_DIR/"
            fi

            chown -R deck:deck "$PLUGIN_DIR" 2>/dev/null || true
            chown -R deck:deck "$APP_DIR" 2>/dev/null || true
            find "$PLUGIN_DIR" -type d -exec chmod 755 {} + 2>/dev/null || true
            find "$PLUGIN_DIR" -type f -exec chmod 644 {} + 2>/dev/null || true
            chmod +x "$PLUGIN_DIR/main.py" 2>/dev/null || true

            systemctl restart plugin_loader 2>/dev/null || true
            ok "Decky plugin updated from bundled ZIP"
        else
            warn "Failed to extract decky-hiddify.zip — plugin left unchanged"
        fi

        rm -rf "$TMP_PLUGIN_DIR"
    fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
ok "Debug logs: $INSTALL_LOG and /home/deck/.local/share/app.hiddify.com/decky-debug.log"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}✓ Hiddify installed!${NC}"
echo ""
echo "VPN control:"
if [ $IS_STEAMDECK -eq 1 ]; then
    echo "  Start:   systemctl --user start hiddify"
    echo "  Stop:    systemctl --user stop hiddify"
    echo "  Status:  systemctl --user status hiddify"
    echo ""
    echo "  Or use the Decky plugin in Quick Access (··· button)"
else
    echo "  Start:   sudo systemctl start hiddify"
    echo "  Stop:    sudo systemctl stop hiddify"
    echo "  Status:  sudo systemctl status hiddify"
fi
echo ""
echo "  GUI:   $INSTALL_DIR/hiddify-gui"
echo "  Logs:  journalctl -u hiddify -f"
echo ""
[ $IS_STEAMDECK -eq 1 ] && echo "  Hiddify will appear in the application menu → Internet"
