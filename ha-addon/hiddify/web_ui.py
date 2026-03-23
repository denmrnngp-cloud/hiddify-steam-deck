#!/usr/bin/env python3
"""
Hiddify VPN — ingress web dashboard.
Serves on :8080. Features:
  - Real-time uptime counter (HH:MM:SS), resets on VPN restart
  - RX / TX traffic from tun0 interface stats
  - VPN on/off toggle via supervisor API
  - Profile selector (reads profiles.json written by run.sh)
"""
import json
import os
import time
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

STATE_FILE    = "/data/hiddify/state.json"
PROFILES_FILE = "/data/hiddify/profiles.json"
TUN_STATS     = "/sys/class/net/tun0/statistics"
OPTIONS_FILE  = "/data/options.json"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def _net_bytes():
    rx = tx = 0
    try:
        rx = int(open(f"{TUN_STATS}/rx_bytes").read())
        tx = int(open(f"{TUN_STATS}/tx_bytes").read())
    except Exception:
        pass
    return rx, tx


def _stats():
    state = _read_json(STATE_FILE)
    rx, tx = _net_bytes()

    started_at = state.get("started_at")
    uptime_sec = 0
    if started_at and state.get("status") == "connected":
        try:
            uptime_sec = max(0, int(time.time() - float(started_at)))
        except (ValueError, TypeError):
            uptime_sec = 0

    profiles = _read_json(PROFILES_FILE, [])
    options  = _read_json(OPTIONS_FILE)
    current_idx = int(options.get("selected_profile", 0))

    return {
        "status":          state.get("status", "unknown"),
        "ip":              state.get("ip", ""),
        "profile":         state.get("profile", ""),
        "uptime_seconds":  uptime_sec,
        "rx_bytes":        rx,
        "tx_bytes":        tx,
        "profiles":        profiles,          # list of {index, name}
        "selected_profile": current_idx,
    }


def _addon_action(action):
    """Call ha supervisor CLI to start/stop/restart addon."""
    slug = os.environ.get("ADDON_SLUG", "self")
    cmd = ["ha", "apps", action, slug]
    try:
        subprocess.run(cmd, timeout=10, check=False)
        return True
    except Exception:
        return False


def _write_profile(idx):
    """Persist selected_profile to options.json and trigger restart."""
    opts = _read_json(OPTIONS_FILE)
    opts["selected_profile"] = int(idx)
    try:
        with open(OPTIONS_FILE, "w") as f:
            json.dump(opts, f)
        return True
    except Exception:
        return False


# ── HTML ───────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Hiddify VPN</title>
<style>
  :root {
    --bg:      #111318;
    --card:    #1c1f26;
    --border:  #2a2d36;
    --text:    #e8eaf0;
    --muted:   #7b7f8e;
    --green:   #4caf50;
    --yellow:  #ffc107;
    --red:     #f44336;
    --blue:    #2196f3;
    --r:       14px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    min-height: 100vh; display: flex;
    align-items: flex-start; justify-content: center;
    padding: 28px 16px;
  }
  .wrap { width: 100%; max-width: 580px; display: flex; flex-direction: column; gap: 14px; }

  /* header */
  .header { display: flex; align-items: center; gap: 14px; }
  .logo svg { width: 42px; height: 42px; }
  .title-block h1 { font-size: 20px; font-weight: 700; }
  .title-block p  { font-size: 12px; color: var(--muted); margin-top: 2px; }

  /* badge */
  .badge {
    display: inline-flex; align-items: center; gap: 7px;
    padding: 5px 13px; border-radius: 99px; font-size: 13px; font-weight: 600;
    background: var(--card); border: 1px solid var(--border); margin-left: auto;
  }
  .dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; box-shadow: 0 0 6px currentColor; }
  .connected    .dot { background: var(--green);  color: var(--green);  }
  .connecting   .dot { background: var(--yellow); color: var(--yellow); animation: pulse 1s infinite; }
  .disconnected .dot, .error .dot, .unknown .dot { background: var(--red); color: var(--red); }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }

  /* grid */
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: var(--r); padding: 18px 20px;
  }
  .card .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .8px; margin-bottom: 8px; }
  .card .value { font-size: 26px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .card .sub   { font-size: 12px; color: var(--muted); margin-top: 4px; }

  /* traffic */
  .card.traffic { grid-column: 1/-1; display: flex; padding: 0; overflow: hidden; }
  .th { flex: 1; padding: 18px 20px; }
  .th:first-child { border-right: 1px solid var(--border); }
  .rx .value { color: var(--blue);  }
  .tx .value { color: var(--green); }

  /* ip / profile full-width */
  .card.fw { grid-column: 1/-1; }
  .card.fw .value { font-size: 16px; word-break: break-all; }

  /* controls */
  .controls { display: flex; gap: 10px; flex-wrap: wrap; }
  .btn {
    flex: 1; min-width: 120px; padding: 13px 20px; border-radius: 10px;
    border: none; font-size: 14px; font-weight: 600; cursor: pointer;
    transition: filter .15s, transform .1s;
  }
  .btn:active { transform: scale(.97); }
  .btn-on  { background: var(--green); color: #fff; }
  .btn-off { background: var(--red);   color: #fff; }
  .btn-on:hover  { filter: brightness(1.15); }
  .btn-off:hover { filter: brightness(1.15); }
  .btn:disabled { opacity: .45; cursor: default; }

  /* profile selector */
  .profile-row { display: flex; align-items: center; gap: 10px; }
  select {
    flex: 1; background: var(--card); color: var(--text);
    border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 14px; font-size: 14px; cursor: pointer;
  }
  .btn-switch {
    padding: 10px 20px; border-radius: 8px; border: none;
    background: var(--blue); color: #fff; font-size: 14px; font-weight: 600;
    cursor: pointer;
  }
  .btn-switch:hover { filter: brightness(1.15); }
  .btn-switch:disabled { opacity: .4; cursor: default; }

  .msg { font-size: 13px; color: var(--muted); text-align: center; min-height: 20px; }
  .footer { text-align: center; font-size: 11px; color: var(--muted); padding-top: 2px; }
</style>
</head>
<body>
<div class="wrap">

  <!-- header -->
  <div class="header">
    <div class="logo">
      <svg viewBox="0 0 44 44" fill="none" xmlns="http://www.w3.org/2000/svg">
        <circle cx="22" cy="22" r="21" fill="#1c1f26" stroke="#2196f3" stroke-width="2"/>
        <path d="M22 10c-6.627 0-12 5.373-12 12s5.373 12 12 12 12-5.373 12-12S28.627 10 22 10zm0 4a8 8 0 0 1 7.924 6.857A5 5 0 0 0 22 17a5 5 0 0 0-4.995 4.562A8.001 8.001 0 0 1 22 14zm0 16a8 8 0 0 1-7.938-7H18a4 4 0 0 0 8 0h3.938A8 8 0 0 1 22 30z" fill="#2196f3"/>
      </svg>
    </div>
    <div class="title-block">
      <h1>Hiddify VPN</h1>
      <p>powered by sing-box</p>
    </div>
    <div id="badge" class="badge unknown">
      <span class="dot"></span>
      <span id="status-text">—</span>
    </div>
  </div>

  <!-- stats grid -->
  <div class="grid">
    <div class="card">
      <div class="label">Uptime</div>
      <div class="value" id="uptime">—</div>
      <div class="sub">since last connect</div>
    </div>
    <div class="card">
      <div class="label">External IP</div>
      <div class="value" id="ip" style="font-size:17px">—</div>
      <div class="sub">VPN exit node</div>
    </div>
    <div class="card traffic">
      <div class="th rx">
        <div class="label">↓ Download</div>
        <div class="value" id="rx">—</div>
        <div class="sub">received via tun0</div>
      </div>
      <div class="th tx">
        <div class="label">↑ Upload</div>
        <div class="value" id="tx">—</div>
        <div class="sub">sent via tun0</div>
      </div>
    </div>
    <div class="card fw">
      <div class="label">Active Profile</div>
      <div class="value" id="profile">—</div>
    </div>
  </div>

  <!-- controls -->
  <div class="card" style="display:flex;flex-direction:column;gap:12px">
    <div class="label" style="margin-bottom:0">VPN Control</div>
    <div class="controls">
      <button class="btn btn-on"  id="btn-start" onclick="vpnAction('start')">▶ Start VPN</button>
      <button class="btn btn-off" id="btn-stop"  onclick="vpnAction('stop')">■ Stop VPN</button>
    </div>

    <div class="label" style="margin-top:4px;margin-bottom:0">Profile</div>
    <div class="profile-row">
      <select id="profile-sel"></select>
      <button class="btn-switch" id="btn-switch" onclick="switchProfile()">Apply</button>
    </div>
    <div class="msg" id="msg"></div>
  </div>

  <div class="footer">Updates every 2 s · Hiddify VPN 1.7.0</div>
</div>

<script>
let _uptimeSec = 0;
let _tick = null;
let _lastStatus = "";

function fmt(b) {
  if (!b) return "0 B";
  if (b < 1024)       return b + " B";
  if (b < 1048576)    return (b/1024).toFixed(1) + " KB";
  if (b < 1073741824) return (b/1048576).toFixed(2) + " MB";
  return (b/1073741824).toFixed(2) + " GB";
}
function fmtT(s) {
  const h = String(Math.floor(s/3600)).padStart(2,"0");
  const m = String(Math.floor((s%3600)/60)).padStart(2,"0");
  const sc = String(s%60).padStart(2,"0");
  return `${h}:${m}:${sc}`;
}
function setMsg(t, ok=true) {
  const el = document.getElementById("msg");
  el.textContent = t;
  el.style.color = ok ? "var(--muted)" : "var(--red)";
  if (t) setTimeout(()=>{ if(el.textContent===t) el.textContent=""; }, 4000);
}

function updateProfiles(profiles, selected) {
  const sel = document.getElementById("profile-sel");
  if (!profiles || !profiles.length) {
    sel.innerHTML = '<option value="0">— no profiles —</option>';
    document.getElementById("btn-switch").disabled = true;
    return;
  }
  const cur = sel.value;
  sel.innerHTML = profiles.map(p =>
    `<option value="${p.index}" ${p.index==selected?"selected":""}>${p.name}</option>`
  ).join("");
  document.getElementById("btn-switch").disabled = false;
}

async function poll() {
  try {
    const r = await fetch("stats");
    if (!r.ok) throw new Error(r.status);
    const d = await r.json();

    // badge
    const badge = document.getElementById("badge");
    badge.className = "badge " + (d.status || "unknown");
    document.getElementById("status-text").textContent = d.status || "unknown";

    // ip / profile
    document.getElementById("ip").textContent      = d.ip      || "—";
    document.getElementById("profile").textContent = d.profile || "—";

    // traffic
    document.getElementById("rx").textContent = fmt(d.rx_bytes);
    document.getElementById("tx").textContent = fmt(d.tx_bytes);

    // uptime ticker
    _uptimeSec = d.uptime_seconds || 0;
    document.getElementById("uptime").textContent = fmtT(_uptimeSec);
    if (d.status === "connected") {
      if (!_tick) _tick = setInterval(()=>{ _uptimeSec++; document.getElementById("uptime").textContent=fmtT(_uptimeSec); }, 1000);
    } else {
      if (_tick) { clearInterval(_tick); _tick = null; }
      document.getElementById("uptime").textContent = "—";
    }

    // buttons
    const running = (d.status === "connected" || d.status === "connecting");
    document.getElementById("btn-start").disabled = running;
    document.getElementById("btn-stop").disabled  = !running;

    // profiles
    updateProfiles(d.profiles, d.selected_profile);

    _lastStatus = d.status;
  } catch(e) {
    document.getElementById("status-text").textContent = "unreachable";
  }
}

async function vpnAction(action) {
  document.getElementById("btn-start").disabled = true;
  document.getElementById("btn-stop").disabled  = true;
  setMsg(action === "start" ? "Starting VPN…" : "Stopping VPN…");
  try {
    const r = await fetch(`vpn/${action}`, {method:"POST"});
    const d = await r.json();
    setMsg(d.ok ? (action==="start"?"VPN starting…":"VPN stopped.") : ("Error: "+(d.error||"unknown")), d.ok);
  } catch(e) {
    setMsg("Request failed", false);
  }
  setTimeout(poll, 2000);
}

async function switchProfile() {
  const idx = document.getElementById("profile-sel").value;
  document.getElementById("btn-switch").disabled = true;
  setMsg("Switching profile…");
  try {
    const r = await fetch(`profile/set?index=${idx}`, {method:"POST"});
    const d = await r.json();
    setMsg(d.ok ? "Profile saved. VPN restarting…" : ("Error: "+(d.error||"")), d.ok);
  } catch(e) {
    setMsg("Request failed", false);
  }
  setTimeout(poll, 3000);
}

poll();
setInterval(poll, 2000);
</script>
</body>
</html>
"""


# ── Request handler ────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, body):
        b = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(b))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"

        if path in ("/", "/index.html"):
            self._html(HTML)

        elif path.endswith("/stats") or path == "/stats":
            self._json(200, _stats())

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")

        # VPN start / stop / restart
        if path.endswith("/vpn/start"):
            ok = _addon_action("start")
            self._json(200, {"ok": ok})

        elif path.endswith("/vpn/stop"):
            ok = _addon_action("stop")
            self._json(200, {"ok": ok})

        elif path.endswith("/vpn/restart"):
            ok = _addon_action("restart")
            self._json(200, {"ok": ok})

        # Profile switch
        elif path.endswith("/profile/set"):
            qs = parse_qs(urlparse(self.path).query)
            idx_list = qs.get("index", ["0"])
            try:
                idx = int(idx_list[0])
            except ValueError:
                self._json(400, {"ok": False, "error": "bad index"})
                return
            ok = _write_profile(idx)
            if ok:
                _addon_action("restart")
            self._json(200, {"ok": ok})

        else:
            self.send_response(404)
            self.end_headers()


# ── Entry ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("WEB_PORT", 8080))
    print(f"[web_ui] Listening on :{port}", flush=True)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
