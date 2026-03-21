#!/bin/bash
# Hiddify VPN — точка входа installer
# GUI mode: копирует себя в /tmp и форкает wizard (терминал закрывается мгновенно)
# TTY mode: запускает terminal install.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -n "$DISPLAY" ] || [ -n "$WAYLAND_DISPLAY" ]; then
    # Desktop Mode — копируем в persistent /tmp чтобы makeself мог почистить свой tmpdir,
    # а wizard продолжил работу со своими файлами
    WORK_DIR="/tmp/hiddify-wizard"
    rm -rf "$WORK_DIR"
    cp -r "$SCRIPT_DIR/." "$WORK_DIR/"

    # Находим XAUTHORITY от живой KDE-сессии (нужен для X11 соединения)
    if [ -z "$XAUTHORITY" ]; then
        XAUTH_FOUND="$(ls /run/user/1000/xauth_* 2>/dev/null | head -1)"
        export XAUTHORITY="${XAUTH_FOUND:-$HOME/.Xauthority}"
    fi

    # Запускаем wizard в фоне и сразу выходим → терминал закрывается
    if [ "$EUID" -eq 0 ]; then
        # Запустили с sudo — wizard должен работать как deck
        XAUTH="$XAUTHORITY"
        sudo -u deck -E DISPLAY="$DISPLAY" XAUTHORITY="$XAUTH" \
            python3 "$WORK_DIR/wizard.py" "$WORK_DIR" >/dev/null 2>&1 &
    else
        DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" \
            python3 "$WORK_DIR/wizard.py" "$WORK_DIR" >/dev/null 2>&1 &
    fi

    # Терминал закрывается немедленно
    exit 0
else
    # SSH / TTY — terminal installation
    if [ "$EUID" -ne 0 ]; then
        exec sudo bash "$SCRIPT_DIR/install.sh"
    else
        exec bash "$SCRIPT_DIR/install.sh"
    fi
fi
