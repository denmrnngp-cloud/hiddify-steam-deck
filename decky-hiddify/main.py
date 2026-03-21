import decky
import asyncio
import subprocess
import os
import json
import signal
import stat
import sqlite3

INSTALL_DIR  = "/opt/hiddify"
CLI_PATH     = f"{INSTALL_DIR}/HiddifyCli"
GUI_PATH     = f"{INSTALL_DIR}/hiddify"
APP_DIR      = "/home/deck/.local/share/app.hiddify.com"
CONFIG_PATH  = f"{APP_DIR}/data/current-config.json"
PROFILES_DB  = f"{APP_DIR}/db.sqlite"
CONFIGS_DIR  = f"{APP_DIR}/configs"


class Plugin:
    _process      = None
    _monitor_task = None

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _check_caps(self) -> bool:
        if not os.path.exists(CLI_PATH):
            return False
        r = subprocess.run(["getcap", CLI_PATH], capture_output=True, text=True)
        return "cap_net_admin" in r.stdout

    def _is_tun_up(self) -> bool:
        try:
            r = subprocess.run(["ip", "link", "show", "tun0"], capture_output=True, text=True)
            return r.returncode == 0 and "tun0" in r.stdout
        except Exception:
            return False

    def _get_vpn_ip(self) -> str:
        try:
            r = subprocess.run(["ip", "-j", "addr", "show", "tun0"], capture_output=True, text=True)
            if r.returncode == 0:
                data = json.loads(r.stdout)
                if data and data[0].get("addr_info"):
                    return data[0]["addr_info"][0].get("local", "")
        except Exception:
            pass
        return ""

    def _process_running(self) -> bool:
        if self._process and self._process.poll() is None:
            return True
        try:
            r = subprocess.run(["pgrep", "-f", "HiddifyC[l]i"], capture_output=True, text=True)
            if r.stdout.strip():
                return True
        except Exception:
            pass
        return False

    def _gui_running(self) -> bool:
        try:
            r = subprocess.run(["pgrep", "-f", "/opt/hiddify/hiddif[y]"], capture_output=True, text=True)
            return bool(r.stdout.strip())
        except Exception:
            return False

    # ── TUN / caps ─────────────────────────────────────────────────────────────

    def _apply_caps(self):
        if os.path.exists(CLI_PATH):
            subprocess.run(
                ["setcap", "cap_net_admin,cap_net_bind_service,cap_net_raw=+eip", CLI_PATH],
                capture_output=True,
            )

    def _ensure_tun(self):
        subprocess.run(["modprobe", "tun"], capture_output=True)
        if not os.path.exists("/dev/net/tun"):
            os.makedirs("/dev/net", exist_ok=True)
            os.mknod("/dev/net/tun", 0o666 | stat.S_IFCHR, os.makedev(10, 200))
            os.chmod("/dev/net/tun", 0o666)

    # ── Install state ──────────────────────────────────────────────────────────

    def _get_install_state(self) -> tuple[str, str]:
        if not os.path.exists(CLI_PATH):
            return "not_installed", "Hiddify is not installed"
        if not self._check_caps():
            return "needs_repair", "setcap missing — click Repair"
        return "ready", "Ready"

    # ── Profile helpers ────────────────────────────────────────────────────────

    def _read_profiles(self) -> list:
        try:
            db = sqlite3.connect(PROFILES_DB)
            db.row_factory = sqlite3.Row
            rows = db.execute(
                "SELECT id, name, active FROM profile_entries ORDER BY name"
            ).fetchall()
            db.close()
            return [{"id": r["id"], "name": r["name"], "active": bool(r["active"])} for r in rows]
        except Exception as e:
            decky.logger.error(f"_read_profiles: {e}")
            return []

    def _get_active_profile(self) -> dict | None:
        for p in self._read_profiles():
            if p["active"]:
                return p
        profiles = self._read_profiles()
        return profiles[0] if profiles else None

    def _rebuild_config(self, profile_id: str) -> bool:
        """Replace outbounds in current-config.json with those from profile config."""
        profile_config_path = os.path.join(CONFIGS_DIR, f"{profile_id}.json")
        if not os.path.exists(profile_config_path):
            decky.logger.error(f"Profile config not found: {profile_config_path}")
            return False
        if not os.path.exists(CONFIG_PATH):
            decky.logger.error(f"current-config.json not found")
            return False

        with open(profile_config_path) as f:
            profile_data = json.load(f)
        profile_outbounds = profile_data.get("outbounds", [])
        if not profile_outbounds:
            return False

        with open(CONFIG_PATH) as f:
            current = json.load(f)

        # Keep system outbounds: §hide§ tag or fundamental types
        system_obs = [
            ob for ob in current.get("outbounds", [])
            if "§hide§" in ob.get("tag", "")
            or ob.get("type") in ("direct", "block", "dns")
        ]

        proxy_tags = [ob["tag"] for ob in profile_outbounds]
        new_selector = {
            "type": "selector",
            "tag": "select",
            "outbounds": proxy_tags,
            "default": proxy_tags[0],
            "interrupt_exist_connections": True,
        }
        current["outbounds"] = [new_selector] + profile_outbounds + system_obs

        with open(CONFIG_PATH, "w") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)

        return True

    # ── Plugin API: status ─────────────────────────────────────────────────────

    async def get_install_status(self) -> dict:
        state, message = self._get_install_state()
        return {
            "state":         state,
            "message":       message,
            "cli_exists":    os.path.exists(CLI_PATH),
            "config_exists": os.path.exists(CONFIG_PATH),
        }

    async def get_status(self) -> dict:
        tun_up  = self._is_tun_up()
        running = self._process_running()
        state, _ = self._get_install_state()
        active = self._get_active_profile()
        return {
            "connected":      tun_up,
            "running":        running,
            "service_active": tun_up or running,
            "vpn_ip":         self._get_vpn_ip() if tun_up else "",
            "install_state":  state,
            "active_profile": active["name"] if active else "",
        }

    # ── Plugin API: profiles ────────────────────────────────────────────────────

    async def get_profiles(self) -> list:
        return self._read_profiles()

    async def switch_profile(self, profile_id: str) -> dict:
        if self._is_tun_up() or self._process_running():
            return {"success": False, "message": "Stop VPN before switching profile"}
        try:
            if not self._rebuild_config(profile_id):
                return {"success": False, "message": "Failed to rebuild config"}

            db = sqlite3.connect(PROFILES_DB)
            db.execute("UPDATE profile_entries SET active = 0")
            db.execute("UPDATE profile_entries SET active = 1 WHERE id = ?", (profile_id,))
            db.commit()
            db.close()

            profiles = self._read_profiles()
            name = next((p["name"] for p in profiles if p["id"] == profile_id), profile_id)
            decky.logger.info(f"Switched to profile: {name}")
            return {"success": True, "message": f"Profile: {name}"}
        except Exception as e:
            decky.logger.error(f"switch_profile: {e}")
            return {"success": False, "message": str(e)}

    # ── Plugin API: repair ─────────────────────────────────────────────────────

    async def repair(self) -> dict:
        try:
            self._apply_caps()
            self._ensure_tun()
            return {"success": True, "message": "Permissions restored"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    # ── Plugin API: VPN ────────────────────────────────────────────────────────

    async def start_vpn(self) -> dict:
        if self._is_tun_up():
            return {"success": True, "message": "Already running"}

        state, _ = self._get_install_state()
        if state != "ready":
            return {"success": False, "message": "Install Hiddify first"}

        if not os.path.exists(CONFIG_PATH):
            return {"success": False, "message": "Config not found. Open Hiddify GUI and set up a profile."}

        self._ensure_tun()
        if not self._check_caps():
            self._apply_caps()

        try:
            env = os.environ.copy()
            env["HOME"] = "/home/deck"
            env["USER"] = "deck"

            log_path = os.path.join(decky.DECKY_PLUGIN_LOG_DIR, "hiddify.log")
            cmd = [CLI_PATH, "run", "-c", CONFIG_PATH, "--tun"]
            decky.logger.info(f"Starting: {' '.join(cmd)}")

            with open(log_path, "a") as log_f:
                self._process = subprocess.Popen(
                    cmd,
                    stdout=log_f, stderr=log_f,
                    env=env,
                    preexec_fn=os.setsid,
                    cwd=APP_DIR,
                )

            for _ in range(15):
                await asyncio.sleep(1)
                if self._is_tun_up():
                    decky.logger.info("VPN up (tun0 appeared)")
                    return {"success": True, "message": "VPN started"}
                if self._process and self._process.poll() is not None:
                    decky.logger.error("HiddifyCli exited early")
                    break

            return {"success": False, "message": "VPN did not start — check config in Hiddify GUI"}

        except Exception as e:
            decky.logger.error(f"start_vpn error: {e}")
            return {"success": False, "message": str(e)}

    async def stop_vpn(self) -> dict:
        try:
            # Stop our subprocess
            if self._process and self._process.poll() is None:
                try:
                    os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
                    await asyncio.sleep(2)
                    if self._process.poll() is None:
                        os.killpg(os.getpgid(self._process.pid), signal.SIGKILL)
                except Exception:
                    pass
            self._process = None

            # Stop GUI-managed VPN (Flutter app embeds hiddify-core.so)
            if self._gui_running() or self._is_tun_up():
                # systemctl --user needs DBUS + XDG_RUNTIME_DIR
                dbus_env = os.environ.copy()
                dbus_env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"
                dbus_env["XDG_RUNTIME_DIR"] = "/run/user/1000"
                # Get exact unit names (glob doesn't work with systemctl stop)
                r = subprocess.run(
                    ["systemctl", "--user", "list-units", "app-hiddify@*.service",
                     "--no-legend", "--plain", "--no-pager"],
                    capture_output=True, text=True, env=dbus_env,
                )
                decky.logger.info(f"list-units output: {repr(r.stdout)}")
                for line in r.stdout.splitlines():
                    unit = line.split()[0] if line.split() else ""
                    if unit.startswith("app-hiddify@"):
                        subprocess.run(["systemctl", "--user", "stop", unit],
                                       capture_output=True, env=dbus_env)
                        decky.logger.info(f"Stopped unit: {unit}")
                # Kill GUI process by specific path (won't match plugin itself)
                subprocess.run(["pkill", "-TERM", "-f", "/opt/hiddify/hiddif[y]"], capture_output=True)
                await asyncio.sleep(2)

            # Kill any remaining HiddifyCli
            for sig in ["-TERM", "-KILL"]:
                subprocess.run(["pkill", sig, "-f", "HiddifyC[l]i"], capture_output=True)
                if sig == "-TERM":
                    await asyncio.sleep(1)

            decky.logger.info(f"stop_vpn done, tun_up={self._is_tun_up()}")
            return {"success": True, "message": "VPN stopped"}
        except Exception as e:
            decky.logger.error(f"stop_vpn error: {e}")
            return {"success": False, "message": str(e)}

    async def get_logs(self) -> str:
        log_path = os.path.join(decky.DECKY_PLUGIN_LOG_DIR, "hiddify.log")
        try:
            if os.path.exists(log_path):
                with open(log_path) as f:
                    lines = f.readlines()
                return "".join(lines[-40:])
        except Exception as e:
            return f"Error: {e}"
        return ""

    # ── Background monitor ─────────────────────────────────────────────────────

    async def _monitor_loop(self):
        prev_connected = None
        while True:
            try:
                tun_up  = self._is_tun_up()
                running = self._process_running()

                if tun_up != prev_connected:
                    decky.logger.info(f"VPN status changed: connected={tun_up}")
                    active = self._get_active_profile()
                    await decky.emit("vpn_status_changed", {
                        "connected":      tun_up,
                        "running":        running,
                        "service_active": tun_up or running,
                        "vpn_ip":         self._get_vpn_ip() if tun_up else "",
                        "active_profile": active["name"] if active else "",
                    })
                    prev_connected = tun_up

                await asyncio.sleep(5)
            except asyncio.CancelledError:
                break
            except Exception as e:
                decky.logger.error(f"Monitor error: {e}")
                await asyncio.sleep(5)

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def _main(self):
        decky.logger.info(f"Hiddify VPN plugin loaded — uid={os.getuid()}")
        os.makedirs(decky.DECKY_PLUGIN_SETTINGS_DIR, exist_ok=True)

        # Re-apply sudoers + polkit on every load (survives SteamOS A/B updates)
        try:
            sudoers_path = "/etc/sudoers.d/hiddify"
            with open(sudoers_path, "w") as f:
                f.write(f"deck ALL=(ALL) NOPASSWD: {CLI_PATH} *\n")
            os.chmod(sudoers_path, 0o440)
        except Exception as e:
            decky.logger.warning(f"Could not write sudoers: {e}")

        try:
            polkit_dir = "/usr/share/polkit-1/rules.d"
            os.makedirs(polkit_dir, exist_ok=True)
            polkit_rule = """\
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
"""
            with open(f"{polkit_dir}/10-hiddify.rules", "w") as f:
                f.write(polkit_rule)
        except Exception as e:
            decky.logger.warning(f"Could not write polkit rule: {e}")

        if os.path.exists(CLI_PATH) and not self._check_caps():
            self._apply_caps()

        self._ensure_tun()
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def _unload(self):
        decky.logger.info("Hiddify VPN plugin unloading")
        if self._monitor_task:
            self._monitor_task.cancel()

    async def _uninstall(self):
        await self.stop_vpn()
