#!/bin/bash
# Hiddify Linux Installer
# Поддержка: Ubuntu 22.04+, Debian 12+, SteamOS (Steam Deck)
set -e

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

# Root check: при вызове из GUI wizard уже запущен через sudo -S
# При прямом запуске из терминала — проверяем
if [ "$EUID" -ne 0 ] && [ -z "$HIDDIFY_WIZARD" ]; then
    err "Запусти с правами root: sudo bash install.sh"
fi

# ── Платформа ──────────────────────────────────────────────────────────────────

IS_STEAMDECK=0
if [ -f /etc/os-release ]; then
    . /etc/os-release
    [[ "${ID:-}" == "steamos" ]] && IS_STEAMDECK=1
fi
[ $IS_STEAMDECK -eq 1 ] && info "Steam Deck обнаружен" || info "Платформа: ${PRETTY_NAME:-Linux}"

# ── Удаление (при втором запуске) ──────────────────────────────────────────────

if [ -d "$INSTALL_DIR" ] && [ -f "$INSTALL_DIR/HiddifyCli" ]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo -e "${YELLOW}Hiddify уже установлен в $INSTALL_DIR${NC}"
    echo ""
    echo "  [1] Переустановить (обновить)"
    echo "  [2] Удалить полностью"
    echo "  [3] Отмена"
    echo ""
    read -r -p "Выбор [1/2/3]: " CHOICE
    case "$CHOICE" in
        2)
            info "Удаление Hiddify..."

            # Остановить и удалить сервис
            if [ $IS_STEAMDECK -eq 1 ]; then
                su -l deck -c "XDG_RUNTIME_DIR=/run/user/1000 systemctl --user stop hiddify 2>/dev/null; systemctl --user disable hiddify 2>/dev/null" 2>/dev/null || true
                rm -f /home/deck/.config/systemd/user/hiddify.service
            else
                systemctl stop hiddify 2>/dev/null || true
                systemctl disable hiddify 2>/dev/null || true
                rm -f /etc/systemd/system/hiddify.service
                systemctl daemon-reload 2>/dev/null || true
            fi

            # Удалить файлы приложения
            rm -rf "$INSTALL_DIR"

            # Удалить desktop интеграцию
            if [ $IS_STEAMDECK -eq 1 ]; then
                rm -f /home/deck/.local/share/applications/hiddify.desktop
                rm -f /home/deck/.local/share/icons/hicolor/256x256/apps/hiddify.png
            else
                rm -f /usr/share/applications/hiddify.desktop
                rm -f /usr/share/icons/hicolor/256x256/apps/hiddify.png
                update-desktop-database /usr/share/applications 2>/dev/null || true
            fi

            echo ""
            echo -e "${GREEN}✓ Hiddify удалён.${NC}"
            exit 0
            ;;
        3)
            echo "Отмена."
            exit 0
            ;;
        *)
            info "Переустановка..."
            ;;
    esac
fi

# ── [1/5] Установка файлов ──────────────────────────────────────────────────────

echo ""
info "[1/5] Установка файлов в $INSTALL_DIR..."

# SteamOS: /usr — read-only filesystem, /opt живёт на отдельном разделе
if [ $IS_STEAMDECK -eq 1 ]; then
    steamos-readonly disable 2>/dev/null || true
fi

rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cp -r "$SCRIPT_DIR/." "$INSTALL_DIR/"

# Убираем служебные файлы инсталлятора
rm -f "$INSTALL_DIR/install.sh" "$INSTALL_DIR/hiddify.service" 2>/dev/null || true

# Убираем конфликтующие системные lib (libssl/libcrypto/libgcc конфликтуют)
for lib in libcrypto.so.3 libssl.so.3 libgcc_s.so.1; do
    rm -f "$INSTALL_DIR/lib/$lib" 2>/dev/null && warn "  удалён конфликтующий: $lib" || true
done

# Права: весь каталог читаемый для обычных пользователей
chmod -R a+rX "$INSTALL_DIR"
chmod +x "$INSTALL_DIR/hiddify" "$INSTALL_DIR/HiddifyCli" 2>/dev/null || true

ok "Файлы установлены"

# ── [2/5] patchelf + setcap ────────────────────────────────────────────────────

echo ""
info "[2/5] Применяем patchelf и capabilities..."

# Находим patchelf: bundled → system
if [ -f "$INSTALL_DIR/_tools/patchelf" ]; then
    PATCHELF="$INSTALL_DIR/_tools/patchelf"
    chmod +x "$PATCHELF"
elif command -v patchelf &>/dev/null; then
    PATCHELF=patchelf
else
    PATCHELF=""
    warn "patchelf не найден — бинарники работают только из $INSTALL_DIR"
fi

if [ -n "$PATCHELF" ]; then
    # HiddifyCli: заменяем ./lib/hiddify-core.so → hiddify-core.so + абсолютный RPATH
    # Это позволяет запускать из любой CWD (cache.db создаётся в CWD)
    "$PATCHELF" --replace-needed ./lib/hiddify-core.so hiddify-core.so \
        "$INSTALL_DIR/HiddifyCli" 2>/dev/null || true
    "$PATCHELF" --set-rpath "$INSTALL_DIR/lib:$INSTALL_DIR/usr/lib" \
        "$INSTALL_DIR/HiddifyCli" 2>/dev/null || true

    # hiddify GUI: абсолютный RPATH (нужен когда setcap сбрасывает LD_LIBRARY_PATH)
    "$PATCHELF" --set-rpath "$INSTALL_DIR/lib:$INSTALL_DIR/usr/lib" \
        "$INSTALL_DIR/hiddify" 2>/dev/null || true

    # libtray_manager_plugin.so: нужны ayatana libs из $INSTALL_DIR/lib
    # DT_RUNPATH главного бинарника не распространяется на косвенные зависимости
    "$PATCHELF" --set-rpath "$INSTALL_DIR/lib" \
        "$INSTALL_DIR/lib/libtray_manager_plugin.so" 2>/dev/null || true

    ok "patchelf применён (абсолютные RPATH)"
fi

# setcap: CAP_NET_ADMIN нужен для создания TUN интерфейса
# setcap нужно делать ПОСЛЕ patchelf (patchelf сбрасывает caps)
if command -v setcap &>/dev/null; then
    setcap 'cap_net_admin,cap_net_bind_service,cap_net_raw=+eip' "$INSTALL_DIR/HiddifyCli"
    setcap 'cap_net_admin,cap_net_bind_service,cap_net_raw=+eip' "$INSTALL_DIR/hiddify"
    ok "setcap применён (CAP_NET_ADMIN, CAP_NET_BIND_SERVICE, CAP_NET_RAW)"
else
    warn "setcap не найден — VPN требует root или AmbientCapabilities"
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

# GUI wrapper (для запуска из desktop shortcut)
cat > "$INSTALL_DIR/hiddify-gui" << 'WRAPPER'
#!/bin/bash
cd "$(dirname "$(readlink -f "$0")")"
exec ./hiddify "$@"
WRAPPER
chmod a+rx "$INSTALL_DIR/hiddify-gui"

# ── [3/5] systemd service ──────────────────────────────────────────────────────

echo ""
info "[3/5] Настройка systemd сервиса..."

if [ $IS_STEAMDECK -eq 1 ]; then
    # SteamOS: user service (живёт в /home — выживает при обновлениях)
    # HiddifyCli получает caps через setcap (user service не поддерживает AmbientCapabilities)
    SERVICE_DIR="/home/deck/.config/systemd/user"
    mkdir -p "$SERVICE_DIR"

    cat > "$SERVICE_DIR/hiddify.service" << EOF
[Unit]
Description=Hiddify VPN Core Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
# CWD: cache.db создаётся здесь (user-writable); hiddify-core.so найдётся через абсолютный RUNPATH
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

    ok "User systemd сервис настроен (Steam Deck)"
else
    # Обычный Linux: system service с AmbientCapabilities
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
    ok "System systemd сервис настроен"
fi

# ── [4/5] /dev/net/tun ────────────────────────────────────────────────────────

echo ""
info "[4/5] TUN устройство..."

modprobe tun 2>/dev/null || true
if [ ! -c /dev/net/tun ]; then
    mkdir -p /dev/net
    mknod /dev/net/tun c 10 200
    chmod 0666 /dev/net/tun
    ok "/dev/net/tun создан"
else
    ok "/dev/net/tun уже существует"
fi

# ── [5/5] Desktop интеграция ──────────────────────────────────────────────────

echo ""
info "[5/5] Desktop интеграция..."

if [ $IS_STEAMDECK -eq 1 ]; then
    DECK_HOME="/home/deck"
    mkdir -p "$DECK_HOME/.local/share/icons/hicolor/256x256/apps"
    mkdir -p "$DECK_HOME/.local/share/applications"

    # Иконка
    [ -f "$INSTALL_DIR/hiddify.png" ] && \
        cp "$INSTALL_DIR/hiddify.png" "$DECK_HOME/.local/share/icons/hicolor/256x256/apps/hiddify.png"

    # Создаём app data dir (нужен как CWD для HiddifyCli)
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

    # Ярлык на рабочем столе
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

    # Помечаем desktop-файл как доверенный (KDE Plasma требует для запуска с рабочего стола)
    chmod +x "$DECK_HOME/Desktop/hiddify.desktop"
    su -l deck -c "gio set ~/Desktop/hiddify.desktop metadata::trusted true 2>/dev/null" 2>/dev/null || true

    # Обновить кэш иконок KDE
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

ok "Desktop интеграция готова"

# ── Готово ────────────────────────────────────────────────────────────────────

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "${GREEN}✓ Hiddify установлен!${NC}"
echo ""
echo "Управление VPN:"
if [ $IS_STEAMDECK -eq 1 ]; then
    echo "  Запустить:  systemctl --user start hiddify"
    echo "  Остановить: systemctl --user stop hiddify"
    echo "  Статус:     systemctl --user status hiddify"
    echo ""
    echo "  Или используй плагин Decky в Quick Access (кнопка ···)"
else
    echo "  Запустить:  sudo systemctl start hiddify"
    echo "  Остановить: sudo systemctl stop hiddify"
    echo "  Статус:     sudo systemctl status hiddify"
fi
echo ""
echo "  GUI:  $INSTALL_DIR/hiddify-gui"
echo "  Логи: journalctl -u hiddify -f"
echo ""
[ $IS_STEAMDECK -eq 1 ] && echo "  Hiddify появится в меню приложений → Интернет"
