#!/bin/bash
# Hiddify Linux Installer
# Supported: Ubuntu 22.04+, Debian 12+, SteamOS (Steam Deck)
set -e

# Ensure valid CWD (makeself may clean up its tmpdir before we run)
cd /tmp 2>/dev/null || cd / 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="/opt/hiddify"

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
# When launched directly from terminal — check here
if [ "$EUID" -ne 0 ] && [ -z "$HIDDIFY_WIZARD" ]; then
    err "Run with root privileges: sudo bash install.sh"
fi

# ── Platform detection ──────────────────────────────────────────────────────────

IS_STEAMDECK=0
if [ -f /etc/os-release ]; then
    . /etc/os-release
    [[ "${ID:-}" == "steamos" ]] && IS_STEAMDECK=1
fi
[ $IS_STEAMDECK -eq 1 ] && info "Steam Deck detected" || info "Platform: ${PRETTY_NAME:-Linux}"

# ── Uninstall menu (shown when already installed) ───────────────────────────────

if [ -d "$INSTALL_DIR" ] && [ -f "$INSTALL_DIR/HiddifyCli" ]; then
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
            info "Uninstalling Hiddify..."

            # ── 1. Stop all processes ───────────────────────────────────────────

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

            # ── 2. Remove Decky plugin ──────────────────────────────────────────

            PLUGIN_DIR="/home/deck/homebrew/plugins/decky-hiddify"
            if [ -d "$PLUGIN_DIR" ]; then
                info "  Removing Decky plugin..."
                rm -rf "$PLUGIN_DIR"
                # Restart plugin_loader so it unloads the plugin
                systemctl restart plugin_loader 2>/dev/null || true
                ok "Decky plugin removed"
            fi

            # ── 3. Remove sudoers and polkit rules ──────────────────────────────
            rm -f /etc/sudoers.d/hiddify /etc/sudoers.d/zz-deck-nopasswd
            rm -f /usr/share/polkit-1/rules.d/10-hiddify.rules

            # ── 4. Remove application files ─────────────────────────────────────
            rm -rf "$INSTALL_DIR"

            # ── 5. Remove desktop integration ───────────────────────────────────
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
            echo -e "${GREEN}✓ Hiddify fully removed (client, plugin, services).${NC}"
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

# ── [1/5] Install files ─────────────────────────────────────────────────────────

echo ""
info "[1/5] Installing files to $INSTALL_DIR..."

# SteamOS: /usr is a read-only filesystem; /opt lives on a separate persistent partition
if [ $IS_STEAMDECK -eq 1 ]; then
    steamos-readonly disable 2>/dev/null || true
fi

rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR/." "$INSTALL_DIR/"

# Remove installer-only files from the install directory
rm -f "$INSTALL_DIR/install.sh" "$INSTALL_DIR/hiddify.service" 2>/dev/null || true

# Remove conflicting system libs (libssl/libcrypto/libgcc conflict with system versions)
for lib in libcrypto.so.3 libssl.so.3 libgcc_s.so.1; do
    rm -f "$INSTALL_DIR/lib/$lib" 2>/dev/null && warn "  removed conflicting lib: $lib" || true
done

# Set permissions: directory readable by regular users
chmod -R a+rX "$INSTALL_DIR"
chmod +x "$INSTALL_DIR/hiddify" "$INSTALL_DIR/HiddifyCli" 2>/dev/null || true

ok "Files installed"

# ── [2/5] patchelf + setcap ────────────────────────────────────────────────────

echo ""
info "[2/5] Applying patchelf and capabilities..."

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

# Passwordless sudo for HiddifyCli
SUDOERS_FILE="/etc/sudoers.d/hiddify"
echo "deck ALL=(ALL) NOPASSWD: $INSTALL_DIR/HiddifyCli *" > "$SUDOERS_FILE"
chmod 0440 "$SUDOERS_FILE"
ok "Passwordless sudo configured for HiddifyCli"

# Polkit rule — allow deck user to configure DNS/routes via systemd-resolved without password
# These are the 3 dialogs Hiddify shows on every VPN connect:
#   "Authentication is required to set domains/default route/DNS servers"
mkdir -p /usr/share/polkit-1/rules.d
cat > /usr/share/polkit-1/rules.d/10-hiddify.rules << 'POLKIT'
polkit.addRule(function(action, subject) {
    var allowed = [
        "org.freedesktop.resolve1.set-domains",
        "org.freedesktop.resolve1.set-default-route",
        "org.freedesktop.resolve1.set-dns-servers",
        "org.freedesktop.resolve1.set-dns-over-tls",
        "org.freedesktop.resolve1.set-dnssec",
        "org.freedesktop.resolve1.set-nta",
    ];
    if (subject.user === "deck" && allowed.indexOf(action.id) !== -1) {
        return polkit.Result.YES;
    }
});
POLKIT
ok "Polkit rule configured (no password for DNS/route changes)"

# GUI wrapper script (used by the desktop shortcut)
cat > "$INSTALL_DIR/hiddify-gui" << 'WRAPPER'
#!/bin/bash
cd "$(dirname "$(readlink -f "$0")")"
exec ./hiddify "$@"
WRAPPER
chmod a+rx "$INSTALL_DIR/hiddify-gui"

# ── [3/5] systemd service ──────────────────────────────────────────────────────

echo ""
info "[3/5] Configuring systemd service..."

if [ $IS_STEAMDECK -eq 1 ]; then
    # SteamOS: user service (lives in /home — survives OS A/B updates)
    # HiddifyCli gets caps via setcap (user services don't support AmbientCapabilities)
    SERVICE_DIR="/home/deck/.config/systemd/user"
    mkdir -p "$SERVICE_DIR"

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
ExecStart=$INSTALL_DIR/HiddifyCli run -c /home/deck/.local/share/app.hiddify.com/data/current-config.json --tun
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

    chown deck:deck "$SERVICE_DIR/hiddify.service"
    export XDG_RUNTIME_DIR="/run/user/1000"
    su -l deck -c "XDG_RUNTIME_DIR=/run/user/1000 systemctl --user daemon-reload && systemctl --user enable hiddify" 2>/dev/null || true

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

# ── [4/5] /dev/net/tun ────────────────────────────────────────────────────────

echo ""
info "[4/5] TUN device..."

modprobe tun 2>/dev/null || true
if [ ! -c /dev/net/tun ]; then
    mkdir -p /dev/net
    mknod /dev/net/tun c 10 200
    chmod 0666 /dev/net/tun
    ok "/dev/net/tun created"
else
    ok "/dev/net/tun already exists"
fi

# ── [5/5] Desktop integration ──────────────────────────────────────────────────

echo ""
info "[5/5] Desktop integration..."

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

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
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
