#!/bin/bash
# Hiddify VPN clean installer entrypoint.
# GUI mode: launches the GTK wizard and forces a full clean reinstall.
# TTY mode: runs install.sh with HIDDIFY_CLEAN_INSTALL=1.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export HIDDIFY_CLEAN_INSTALL=1

if [ -n "$DISPLAY" ] || [ -n "$WAYLAND_DISPLAY" ]; then
    WORK_DIR="/tmp/hiddify-wizard"
    rm -rf "$WORK_DIR"
    cp -r "$SCRIPT_DIR/." "$WORK_DIR/"

    if [ -z "$XAUTHORITY" ]; then
        XAUTH_FOUND="$(ls /run/user/1000/xauth_* 2>/dev/null | head -1)"
        export XAUTHORITY="${XAUTH_FOUND:-$HOME/.Xauthority}"
    fi

    if [ "$EUID" -eq 0 ]; then
        XAUTH="$XAUTHORITY"
        sudo -u deck -E DISPLAY="$DISPLAY" XAUTHORITY="$XAUTH" HIDDIFY_CLEAN_INSTALL=1 \
            python3 "$WORK_DIR/wizard.py" "$WORK_DIR" >/dev/null 2>&1 &
    else
        DISPLAY="$DISPLAY" XAUTHORITY="$XAUTHORITY" HIDDIFY_CLEAN_INSTALL=1 \
            python3 "$WORK_DIR/wizard.py" "$WORK_DIR" >/dev/null 2>&1 &
    fi

    exit 0
else
    if [ "$EUID" -ne 0 ]; then
        exec sudo env HIDDIFY_CLEAN_INSTALL=1 bash "$SCRIPT_DIR/install.sh"
    else
        exec env HIDDIFY_CLEAN_INSTALL=1 bash "$SCRIPT_DIR/install.sh"
    fi
fi
