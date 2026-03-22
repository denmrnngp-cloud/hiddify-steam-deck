# Hiddify VPN — Steam Deck Port

<img src="assets/cover.png" alt="Hiddify VPN for Steam Deck" width="100%"/>

> **Unofficial Steam Deck port of [hiddify/hiddify-app](https://github.com/hiddify/hiddify-app)**
> Powered by [sing-box](https://github.com/SagerNet/sing-box) · Supports VLESS/Reality, VMess, Trojan, Hysteria 2, TUIC, Shadowsocks

[![Based on](https://img.shields.io/badge/based%20on-hiddify%2Fhiddify--app-blue?logo=github)](https://github.com/hiddify/hiddify-app)
[![Platform](https://img.shields.io/badge/platform-Steam%20Deck%20%2F%20SteamOS-informational?logo=steam)](https://store.steampowered.com/steamdeck)
[![Decky Plugin](https://img.shields.io/badge/Decky-plugin-green?logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0id2hpdGUiIGQ9Ik0xMiAyTDQgNXY2YzAgNS4yNSAzLjQgMTAuMTUgOCAxMS4zOEM' )](https://decky.xyz)

Full port of [Hiddify](https://github.com/hiddify/hiddify-app) for Steam Deck / SteamOS.
Works in Desktop Mode and Game Mode (via Decky plugin).

## Demo

https://github.com/denmrnngp-cloud/hiddify-steam-deck/raw/main/assets/demo.mp4

---

## Release Contents

| File | Description |
|------|-------------|
| `Hiddify-linux-x64.bin` | Self-extracting installer (~51 MB) |
| `decky-hiddify-v1.2.0.zip` | Decky plugin for Game Mode VPN control |
| `installer-src/` | Installer source (install.sh + all bundled files) |

---

## Requirements

- Steam Deck (SteamOS) or Ubuntu 22.04+ / Debian 12+
- Architecture: x86-64 (amd64)
- For Game Mode: [Decky Loader](https://decky.xyz/) installed

---

## Installation

### 1. Download the installer

Copy `Hiddify-linux-x64.bin` to your Steam Deck (e.g. `~/Downloads/`).

### 2. Run in Desktop Mode

Open **Konsole** and run:

```bash
bash ~/Downloads/Hiddify-linux-x64.bin
```

The installer automatically:
- Detects Steam Deck and applies the correct mode
- Installs all files to `/opt/hiddify/`
- Applies `patchelf` (absolute RPATH — works from any directory)
- Applies `setcap cap_net_admin` (TUN creation without root at runtime)
- Configures passwordless sudo for HiddifyCli
- Configures polkit rules (no password prompts for DNS/route changes)
- Creates a systemd user service
- Adds a desktop shortcut (Internet category)
- Sets the application icon

### 3. Configure a VPN profile

Launch the GUI from the menu or directly:

```bash
/opt/hiddify/hiddify-gui
```

Add a VPN configuration (subscription link or manual).
Config is saved to:
```
~/.local/share/app.hiddify.com/data/current-config.json
```

### 4. Install the Decky plugin (optional)

For VPN control from Game Mode (the `···` button):

```bash
# Copy decky-hiddify-v1.2.0.zip to Steam Deck, then:
sudo unzip -o decky-hiddify-v1.2.0.zip -d /home/deck/homebrew/plugins/
sudo systemctl restart plugin_loader
```

---

## Uninstall

Run the installer again — a menu will appear:

```
Hiddify is already installed in /opt/hiddify

  [1] Reinstall (update)
  [2] Uninstall completely
  [3] Cancel
```

Select `2` to uninstall. Removes:
- `/opt/hiddify/`
- systemd user service
- desktop shortcut and icon from `~/.local/share/`

---

## VPN Control from Terminal

```bash
# Start VPN
systemctl --user start hiddify

# Stop VPN
systemctl --user stop hiddify

# Status
systemctl --user status hiddify

# Live logs
journalctl --user -u hiddify -f
```

---

## Technical Details

### `/opt/hiddify/` Structure

```
/opt/hiddify/
├── hiddify              # Flutter GUI (setcap + absolute RUNPATH)
├── HiddifyCli           # VPN core (setcap + absolute RUNPATH)
├── hiddify-gui          # Wrapper script for desktop shortcut
├── hiddify.png          # Application icon
├── _tools/
│   └── patchelf         # Static patchelf (bundled)
├── lib/
│   ├── hiddify-core.so          # sing-box core
│   ├── libflutter_linux_gtk.so  # Flutter runtime
│   ├── libayatana-appindicator3.so.1  # System tray (bundled)
│   ├── libayatana-ido3-0.4.so.0       # System tray dep (bundled)
│   ├── libayatana-indicator3.so.7     # System tray dep (bundled)
│   └── ... (other Flutter plugin .so files)
└── data/
    └── flutter_assets/   # Flutter assets, flag icons, fonts
```

### Key Port Fixes

| Problem | Solution |
|---------|----------|
| `./lib/hiddify-core.so not found` from foreign CWD | `patchelf --replace-needed` + `--set-rpath /opt/hiddify/lib` |
| `libayatana-appindicator3.so.1 not found` on SteamOS | Bundled from Ubuntu 22.04, patchelf on `libtray_manager_plugin.so` |
| `operation not permitted` creating TUN | `setcap cap_net_admin,cap_net_bind_service,cap_net_raw=+eip` on both binaries |
| `cache.db: permission denied` | CWD = `~/.local/share/app.hiddify.com` (user-writable) |
| Caps reset after patchelf | setcap applied strictly **after** patchelf |
| systemd user service on SteamOS | User service in `~/.config/systemd/user/` (survives OS updates) |
| `LD_LIBRARY_PATH` ignored with setcap | Absolute RUNPATH via patchelf instead of `LD_LIBRARY_PATH` |
| Sudo password prompt on every VPN toggle | `/etc/sudoers.d/zz-deck-nopasswd` with `NOPASSWD: ALL` (named `zz-*` to override `wheel` file alphabetically) |
| SteamOS A/B update resets `/etc/` and `/usr/` | Plugin tries to re-apply on load; installer handles it during reinstall |
| `pkill` killing plugin itself | Bracket trick: `pkill -f '/opt/hiddify/hiddif[y]'` — won't match plugin path |
| `systemctl --user` failing in plugin subprocess | Set `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus` + `XDG_RUNTIME_DIR=/run/user/1000` |
| Hiddify GUI VPN not stopped by plugin | Stop `app-hiddify@<uuid>.service` by querying `systemctl list-units` for exact unit name |

### Why Installation Survives SteamOS Updates

SteamOS updates via A/B partition swap — only the read-only partition (`/usr`, `/etc`) changes.
The installer writes exclusively to:
- `/opt/hiddify/` — mounted from the `/home` partition (persistent)
- `~/.config/systemd/user/` — home directory (persistent)
- `~/.local/share/` — home directory (persistent)

`setcap` is stored as an xattr on the file in `/opt/hiddify/` — also persistent.

### Manual VPN Start

```bash
cd ~/.local/share/app.hiddify.com
/opt/hiddify/HiddifyCli run \
  -c ~/.local/share/app.hiddify.com/data/current-config.json \
  --tun
```

---

## Decky Plugin (v1.2.0)

The `decky-hiddify` plugin adds VPN control to Quick Access Menu (the `···` button).

### Features

- **VPN ON / OFF toggle** — button with colored status dot (green = connected, yellow = connecting, red = off)
- **Profile selector** — switch between VPN profiles without leaving Game Mode (VPN must be stopped first)
- Connection status with TUN IP address display
- Syncs with Hiddify GUI (stopping VPN from plugin also stops GUI-managed VPN via systemd unit)
- Background monitor with push events on VPN state changes (polls every 5 s)
- Log viewer (last 40 lines)
- Error boundary — render errors shown in UI instead of crashing the plugin

### Plugin Architecture

```
decky-hiddify/
├── main.py        # Backend (Python): HiddifyCli subprocess + profile management
└── src/
    └── index.tsx  # Frontend (React/TSX): panel UI
```

**Profile switching** reads profiles from `~/.local/share/app.hiddify.com/db.sqlite`,
rebuilds `current-config.json` by merging the selected profile's outbounds with
the existing TUN/DNS/route configuration. VPN must be stopped before switching.

**GUI sync**: when stopping VPN from the plugin, it queries `systemctl --user list-units 'app-hiddify@*.service'`
to get the exact transient unit name, then stops it. Also sends `SIGTERM` to the `hiddify` GUI process directly.

---

## Build from Source

### Installer

Three large upstream binaries are **not** included in this repo. Download them from the
[Hiddify release](https://github.com/hiddify/hiddify-app/releases) and place into `release/installer-src/lib/`:

| File | Size | Source |
|------|------|--------|
| `lib/hiddify-core.so` | ~70 MB | Hiddify release (sing-box core) |
| `lib/libflutter_linux_gtk.so` | ~32 MB | Hiddify release (Flutter runtime) |
| `lib/libapp.so` | ~15 MB | Hiddify release (Flutter app) |

Then rebuild the self-extracting installer:

```bash
makeself --nox11 release/installer-src/ Hiddify-linux-x64.bin "Hiddify VPN" bash setup.sh
```

### Decky Plugin

```bash
cd decky-hiddify/
npm install
npm run build
# Output: dist/ — copy to Steam Deck at ~/homebrew/plugins/decky-hiddify/
```

---

## Sources

- Hiddify App: https://github.com/hiddify/hiddify-app
- Decky Loader: https://github.com/SteamDeckHomebrew/decky-loader
- sing-box (hiddify-core): https://github.com/SagerNet/sing-box
