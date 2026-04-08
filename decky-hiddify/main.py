import decky
import asyncio
import subprocess
import os
import json
import stat
import socket
import struct
import sqlite3

# Decky PluginLoader is a PyInstaller bundle that sets LD_LIBRARY_PATH to its
# own extracted libs dir (/tmp/_MEI.../). This leaks into every subprocess and
# causes systemctl (and other system binaries) to load the wrong libcrypto.so.3,
# producing: "version `OPENSSL_3.4.0' not found". Clear it at import time.
os.environ.pop("LD_LIBRARY_PATH", None)

INSTALL_DIR  = "/opt/hiddify"
CLI_PATH     = f"{INSTALL_DIR}/HiddifyCli"
GUI_PATH     = f"{INSTALL_DIR}/hiddify"
APP_DIR      = "/home/deck/.local/share/app.hiddify.com"
CONFIG_PATH  = f"{APP_DIR}/data/current-config.json"
PROFILES_DB  = f"{APP_DIR}/db.sqlite"
CONFIGS_DIR  = f"{APP_DIR}/configs"

GRPC_PORT = 17078  # GUI in-process gRPC port


class Plugin:
    _monitor_task = None
    _user_stopped  = False  # set True when user explicitly stops VPN via plugin

    # ── Minimal HTTP/2 gRPC helpers ────────────────────────────────────────────

    @staticmethod
    def _h2_frame(type_, flags, stream_id, payload=b''):
        return struct.pack('>I', len(payload))[1:] + bytes([type_, flags]) + struct.pack('>I', stream_id) + payload

    @staticmethod
    def _hpack_str(s):
        b = s.encode() if isinstance(s, str) else s
        return bytes([len(b)]) + b

    @staticmethod
    def _pb_string(field_num, value):
        """Encode a protobuf string field (wire type 2). Supports length up to 16383."""
        b = value.encode() if isinstance(value, str) else value
        tag = (field_num << 3) | 2
        n = len(b)
        if n < 128:
            length_bytes = bytes([n])
        else:
            length_bytes = bytes([(n & 0x7F) | 0x80, n >> 7])
        return bytes([tag]) + length_bytes + b

    def _grpc_call(self, method_path, request_body=b'', port=GRPC_PORT, timeout=5):
        """
        Send a single gRPC unary call using raw HTTP/2 sockets.
        Returns the gRPC response body bytes, or None on failure.
        """
        h2 = self._h2_frame
        hs = self._hpack_str
        authority = f'127.0.0.1:{port}'

        # HPACK encoded request headers
        hpack = (
            bytes([0x83])                          # :method: POST
            + bytes([0x86])                        # :scheme: http
            + bytes([0x44]) + hs(method_path)      # :path
            + bytes([0x41]) + hs(authority)        # :authority
            + bytes([0x40]) + hs('content-type') + hs('application/grpc')
            + bytes([0x40]) + hs('te')             + hs('trailers')
        )

        # gRPC message framing: 1 byte compressed flag + 4 byte length + body
        grpc_msg = b'\x00' + struct.pack('>I', len(request_body)) + request_body

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect(('127.0.0.1', port))

            # Send HTTP/2 connection preface + our SETTINGS
            s.sendall(b'PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n' + h2(0x04, 0x00, 0))

            # Read server SETTINGS and ACK it
            raw = b''
            try:
                raw = s.recv(4096)
            except socket.timeout:
                pass
            i = 0
            while i + 9 <= len(raw):
                frame_len = struct.unpack('>I', b'\x00' + raw[i:i+3])[0]
                frame_type = raw[i+3]
                frame_flags = raw[i+4]
                if frame_type == 0x04 and not (frame_flags & 0x01):
                    s.sendall(h2(0x04, 0x01, 0))  # SETTINGS_ACK
                i += 9 + frame_len

            # Send our request
            s.sendall(h2(0x01, 0x04, 1, hpack) + h2(0x00, 0x01, 1, grpc_msg))

            # Read response frames
            resp_raw = b''
            try:
                while True:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    resp_raw += chunk
            except socket.timeout:
                pass

            s.close()

            # Parse DATA frame from response
            i = 0
            while i + 9 <= len(resp_raw):
                frame_len = struct.unpack('>I', b'\x00' + resp_raw[i:i+3])[0]
                frame_type = resp_raw[i+3]
                payload = resp_raw[i+9:i+9+frame_len]
                if frame_type == 0x00 and len(payload) >= 5:  # DATA frame
                    grpc_len = struct.unpack('>I', payload[1:5])[0]
                    return payload[5:5+grpc_len]
                i += 9 + frame_len

            return b''

        except Exception as e:
            decky.logger.debug(f"_grpc_call({method_path}:{port}) error: {e}")
            return None

    def _is_grpc_up(self, port=GRPC_PORT) -> bool:
        """Check if the GUI's gRPC server is reachable."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect(('127.0.0.1', port))
            s.close()
            return True
        except Exception:
            return False

    def _grpc_stop(self) -> bool:
        """Call Core.Stop() on the running gRPC server. Returns True if sent."""
        result = self._grpc_call('/hcore.Core/Stop', b'', GRPC_PORT)
        if result is not None:
            decky.logger.info(f"gRPC Stop sent, response: {result.hex() if result else 'empty'}")
            return True
        return False

    def _grpc_start(self) -> bool:
        """Call Core.Start() on the running gRPC server with current config."""
        # Build StartRequest protobuf: config_path (field 1) + config_name (field 7)
        request = self._pb_string(1, CONFIG_PATH) + self._pb_string(7, "current-config")
        result = self._grpc_call('/hcore.Core/Start', request, GRPC_PORT)
        if result is not None:
            decky.logger.info(f"gRPC Start sent, response: {result.hex() if result else 'empty'}")
            return True
        return False

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
        # HiddifyCli always runs as gRPC server (app-hiddify@UUID.service from GUI).
        # VPN state is determined by tun0 only; process presence is irrelevant.
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

    def _disable_tun_ipv6(self):
        """Disable IPv6 on tun0.

        HiddifyCli's FakeDNS returns both A and AAAA (fc00::/18) records.
        The Shadowsocks proxy typically can't forward IPv6, so curl/apps try
        the IPv6 fake address first (Happy Eyeballs), wait for a full TCP
        timeout (~20s), then fall back to IPv4. Disabling IPv6 on tun0 makes
        the kernel reject IPv6 connections instantly (ENETUNREACH) → immediate
        fallback to IPv4, no delay.
        """
        subprocess.run(
            ["sysctl", "-w", "net.ipv6.conf.tun0.disable_ipv6=1"],
            capture_output=True,
        )
        decky.logger.info("IPv6 disabled on tun0 (proxy does not forward IPv6)")

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
            cols = {row[1] for row in db.execute("PRAGMA table_info(profile_entries)")}
            if "active" in cols:
                rows = db.execute(
                    "SELECT id, name, active FROM profile_entries ORDER BY name"
                ).fetchall()
                result = [{"id": r[0], "name": r[1], "active": bool(r[2])} for r in rows]
            else:
                rows = db.execute(
                    "SELECT id, name FROM profile_entries ORDER BY name"
                ).fetchall()
                result = [{"id": r[0], "name": r[1], "active": False} for r in rows]
            db.close()
            return result
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

    @staticmethod
    def _systemctl_user(args: list) -> subprocess.CompletedProcess:
        """Run systemctl --user with proper DBUS env (works from plugin subprocess)."""
        env = os.environ.copy()
        env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"
        env["XDG_RUNTIME_DIR"] = "/run/user/1000"
        return subprocess.run(
            ["systemctl", "--user"] + args,
            capture_output=True, text=True, env=env,
        )

    async def start_vpn(self) -> dict:
        decky.logger.info("start_vpn called")
        self._user_stopped = False

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

        # Path A: gRPC is available (GUI or its service holds port 17078)
        if self._is_grpc_up():
            decky.logger.info("gRPC up — starting via Core.Start")
            self._grpc_start()
            for i in range(10):
                await asyncio.sleep(1)
                if self._is_tun_up():
                    decky.logger.info(f"VPN up via gRPC after {i+1}s")
                    self._disable_tun_ipv6()
                    return {"success": True, "message": "VPN started"}
            # Retry: stop then start
            decky.logger.info("tun0 not up after 10s — retrying via gRPC Stop+Start")
            self._grpc_stop()
            await asyncio.sleep(2)
            self._grpc_start()
            for i in range(8):
                await asyncio.sleep(1)
                if self._is_tun_up():
                    decky.logger.info(f"VPN up via gRPC retry after {i+1}s")
                    self._disable_tun_ipv6()
                    return {"success": True, "message": "VPN started"}
            decky.logger.error("gRPC Start failed — tun0 not up after retry")
            return {"success": False, "message": "VPN did not start. Try restarting the Hiddify app."}

        # Path B: no gRPC → start via systemd user service
        decky.logger.info("No gRPC — starting via systemctl --user start hiddify")
        r = self._systemctl_user(["start", "hiddify"])
        if r.returncode != 0:
            decky.logger.error(f"systemctl start failed: {r.stderr.strip()}")
            return {"success": False, "message": f"Failed to start: {r.stderr.strip()}"}

        for i in range(15):
            await asyncio.sleep(1)
            if self._is_tun_up():
                decky.logger.info(f"VPN up via systemctl after {i+1}s")
                self._disable_tun_ipv6()
                return {"success": True, "message": "VPN started"}
            status = self._systemctl_user(["is-active", "hiddify"])
            if status.stdout.strip() not in ("active", "activating"):
                logs = self._systemctl_user(["status", "hiddify"]).stdout[-300:]
                decky.logger.error(f"service stopped early: {logs}")
                break

        return {"success": False, "message": "VPN did not start — check Hiddify config"}

    async def stop_vpn(self) -> dict:
        decky.logger.info("stop_vpn called")
        self._user_stopped = True
        try:
            # If GUI is running — send gRPC Stop (GUI stays open, only VPN disconnects)
            if self._is_grpc_up():
                decky.logger.info("GUI gRPC detected — stopping via gRPC Core.Stop")
                self._grpc_stop()
                await asyncio.sleep(3)
                if not self._is_tun_up():
                    decky.logger.info("VPN stopped via gRPC")
                    return {"success": True, "message": "VPN stopped"}
                decky.logger.warning("gRPC Stop sent but tun0 still up — falling back to systemctl")

            # Stop systemd user service (covers VPN started by plugin or systemd)
            self._systemctl_user(["stop", "hiddify"])
            await asyncio.sleep(2)

            if not self._is_tun_up():
                decky.logger.info("VPN stopped via systemctl")
                return {"success": True, "message": "VPN stopped"}

            # Last resort: kill any remaining HiddifyCli processes
            subprocess.run(["pkill", "-TERM", "-f", "HiddifyC[l]i"], capture_output=True)
            await asyncio.sleep(1)
            subprocess.run(["pkill", "-KILL", "-f", "HiddifyC[l]i"], capture_output=True)

            # Free gRPC port if still held by a stale process
            subprocess.run(["sudo", "fuser", "-k", "17078/tcp"], capture_output=True)

            # Force-remove tun0 if still present
            if self._is_tun_up():
                await asyncio.sleep(2)
            if self._is_tun_up():
                subprocess.run(["sudo", "ip", "link", "delete", "tun0"], capture_output=True)

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
                    decky.logger.info(f"VPN status changed: connected={tun_up} user_stopped={self._user_stopped}")
                    active = self._get_active_profile()

                    # VPN dropped unexpectedly — auto-reconnect if gRPC is still up
                    if prev_connected and not tun_up and not self._user_stopped:
                        decky.logger.info("VPN dropped (not by user) — checking if gRPC is up for auto-reconnect")
                        if self._is_grpc_up():
                            decky.logger.info("gRPC up — auto-reconnecting via Core.Start")
                            self._grpc_start()
                            await asyncio.sleep(3)
                            if self._is_tun_up():
                                decky.logger.info("Auto-reconnect succeeded")
                                self._disable_tun_ipv6()
                                prev_connected = True
                                await asyncio.sleep(5)
                                continue

                    await decky.emit("vpn_status_changed", {
                        "connected":      tun_up,
                        "running":        running,
                        "service_active": tun_up or running,
                        "vpn_ip":         self._get_vpn_ip() if tun_up else "",
                        "active_profile": active["name"] if active else "",
                        "dropped":        bool(prev_connected and not tun_up and not self._user_stopped),
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

        # /usr/share/polkit-1/rules.d is read-only on SteamOS (squashfs).
        # /etc/polkit-1/rules.d is on the writable partition and takes precedence.
        for polkit_dir in ("/etc/polkit-1/rules.d", "/usr/share/polkit-1/rules.d"):
            try:
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
        "org.freedesktop.NetworkManager.network-control",
        "org.freedesktop.NetworkManager.settings.modify.system",
        "org.freedesktop.NetworkManager.wifi.share.open",
        "net.hiddify.app",
        "com.hiddify.app",
    ];
    if (subject.user === "deck" && allowed.indexOf(action.id) !== -1) {
        return polkit.Result.YES;
    }
    if (subject.user === "deck" && action.id.indexOf("hiddify") !== -1) {
        return polkit.Result.YES;
    }
});
"""
                with open(f"{polkit_dir}/10-hiddify.rules", "w") as f:
                    f.write(polkit_rule)
                decky.logger.info(f"polkit rule written to {polkit_dir}")
                break  # success — no need to try fallback
            except Exception as e:
                decky.logger.warning(f"Could not write polkit rule to {polkit_dir}: {e}")

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
