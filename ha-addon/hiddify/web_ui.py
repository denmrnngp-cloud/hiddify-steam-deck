#!/usr/bin/env python3
"""
Hiddify VPN — ingress web dashboard.
Serves on :8080. Shows real-time uptime, traffic (rx/tx), status, profile, IP.
"""
import json
import os
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

STATE_FILE = "/data/hiddify/state.json"
TUN_STATS  = "/sys/class/net/tun0/statistics"


def _read_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _net_bytes():
    rx = tx = 0
    try:
        rx = int(open(f"{TUN_STATS}/rx_bytes").read())
        tx = int(open(f"{TUN_STATS}/tx_bytes").read())
    except Exception:
        pass
    return rx, tx


def _stats_json():
    state = _read_state()
    rx, tx = _net_bytes()
    started_at = state.get("started_at")
    uptime_sec = 0
    if started_at and state.get("status") == "connected":
        uptime_sec = max(0, int(time.time() - float(started_at)))
    return json.dumps({
        "status":         state.get("status", "unknown"),
        "ip":             state.get("ip", ""),
        "profile":        state.get("profile", ""),
        "uptime_seconds": uptime_sec,
        "rx_bytes":       rx,
        "tx_bytes":       tx,
    })


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Hiddify VPN</title>
<style>
  :root {
    --bg:       #111318;
    --card:     #1c1f26;
    --border:   #2a2d36;
    --text:     #e8eaf0;
    --muted:    #7b7f8e;
    --green:    #4caf50;
    --yellow:   #ffc107;
    --red:      #f44336;
    --blue:     #2196f3;
    --radius:   14px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    min-height: 100vh;
    display: flex;
    align-items: flex-start;
    justify-content: center;
    padding: 32px 16px;
  }
  .wrap { width: 100%; max-width: 560px; display: flex; flex-direction: column; gap: 16px; }

  /* header */
  .header { display: flex; align-items: center; gap: 14px; }
  .logo { width: 44px; height: 44px; }
  .title-block h1 { font-size: 20px; font-weight: 700; letter-spacing: 0.3px; }
  .title-block p  { font-size: 13px; color: var(--muted); margin-top: 2px; }

  /* status badge */
  .badge {
    display: inline-flex; align-items: center; gap: 7px;
    padding: 5px 14px; border-radius: 99px;
    font-size: 13px; font-weight: 600;
    background: var(--card); border: 1px solid var(--border);
    margin-top: 4px;
  }
  .dot {
    width: 9px; height: 9px; border-radius: 50%;
    flex-shrink: 0;
    box-shadow: 0 0 6px currentColor;
  }
  .connected   .dot { background: var(--green);  color: var(--green);  }
  .connecting  .dot { background: var(--yellow); color: var(--yellow); }
  .disconnected .dot, .error .dot, .unknown .dot {
    background: var(--red); color: var(--red);
  }

  /* grid cards */
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 18px 20px;
  }
  .card .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 8px; }
  .card .value { font-size: 26px; font-weight: 700; font-variant-numeric: tabular-nums; letter-spacing: 1px; }
  .card .sub   { font-size: 12px; color: var(--muted); margin-top: 4px; }

  /* traffic card spans full width */
  .card.traffic { grid-column: 1 / -1; display: flex; gap: 0; padding: 0; overflow: hidden; }
  .traffic-half { flex: 1; padding: 18px 20px; }
  .traffic-half:first-child { border-right: 1px solid var(--border); }
  .traffic-half .arrow { font-size: 18px; margin-right: 6px; }
  .rx .value { color: var(--blue);  }
  .tx .value { color: var(--green); }

  .card.profile .value { font-size: 16px; word-break: break-all; }

  .footer { text-align: center; font-size: 11px; color: var(--muted); padding-top: 4px; }
</style>
</head>
<body>
<div class="wrap">

  <div class="header">
    <svg class="logo" viewBox="0 0 44 44" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="22" cy="22" r="21" fill="#1c1f26" stroke="#2196f3" stroke-width="2"/>
      <path d="M22 10c-6.627 0-12 5.373-12 12s5.373 12 12 12 12-5.373 12-12S28.627 10 22 10zm0 4a8 8 0 0 1 7.924 6.857A5 5 0 0 0 22 17a5 5 0 0 0-4.995 4.562A8.001 8.001 0 0 1 22 14zm0 16a8 8 0 0 1-7.938-7H18a4 4 0 0 0 8 0h3.938A8 8 0 0 1 22 30z" fill="#2196f3"/>
    </svg>
    <div class="title-block">
      <h1>Hiddify VPN</h1>
      <p>powered by sing-box</p>
    </div>
    <div id="badge" class="badge unknown" style="margin-left:auto">
      <span class="dot"></span>
      <span id="status-text">—</span>
    </div>
  </div>

  <div class="grid">

    <div class="card">
      <div class="label">Uptime</div>
      <div class="value" id="uptime">00:00:00</div>
      <div class="sub" id="uptime-sub">since last connect</div>
    </div>

    <div class="card">
      <div class="label">External IP</div>
      <div class="value" id="ip" style="font-size:18px">—</div>
      <div class="sub" id="ip-sub">VPN exit node</div>
    </div>

    <div class="card traffic">
      <div class="traffic-half rx">
        <div class="label">↓ Download</div>
        <div class="value" id="rx">0 B</div>
        <div class="sub">received via tun0</div>
      </div>
      <div class="traffic-half tx">
        <div class="label">↑ Upload</div>
        <div class="value" id="tx">0 B</div>
        <div class="sub">sent via tun0</div>
      </div>
    </div>

    <div class="card profile" style="grid-column:1/-1">
      <div class="label">Active Profile</div>
      <div class="value" id="profile">—</div>
    </div>

  </div>

  <div class="footer">Updates every second · Hiddify VPN 1.6.0</div>
</div>

<script>
let _uptimeSec = 0;
let _interval  = null;

function fmt(bytes) {
  if (bytes < 1024)       return bytes + " B";
  if (bytes < 1048576)    return (bytes/1024).toFixed(1) + " KB";
  if (bytes < 1073741824) return (bytes/1048576).toFixed(2) + " MB";
  return (bytes/1073741824).toFixed(2) + " GB";
}

function fmtTime(s) {
  const h = String(Math.floor(s/3600)).padStart(2,"0");
  const m = String(Math.floor((s%3600)/60)).padStart(2,"0");
  const sec = String(s%60).padStart(2,"0");
  return `${h}:${m}:${sec}`;
}

function startTick() {
  if (_interval) clearInterval(_interval);
  _interval = setInterval(() => {
    _uptimeSec++;
    document.getElementById("uptime").textContent = fmtTime(_uptimeSec);
  }, 1000);
}

async function poll() {
  try {
    const r   = await fetch("/api/hiddify/stats");
    const d   = await r.json();

    const badge = document.getElementById("badge");
    badge.className = "badge " + (d.status || "unknown");
    document.getElementById("status-text").textContent = d.status || "unknown";

    document.getElementById("ip").textContent      = d.ip      || "—";
    document.getElementById("profile").textContent = d.profile || "—";
    document.getElementById("rx").textContent      = fmt(d.rx_bytes || 0);
    document.getElementById("tx").textContent      = fmt(d.tx_bytes || 0);

    _uptimeSec = d.uptime_seconds || 0;
    document.getElementById("uptime").textContent = fmtTime(_uptimeSec);

    if (d.status === "connected") {
      if (!_interval) startTick();
    } else {
      if (_interval) { clearInterval(_interval); _interval = null; }
    }
  } catch(e) {
    document.getElementById("status-text").textContent = "unreachable";
  }
}

poll();
setInterval(poll, 2000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # suppress request logs

    def do_GET(self):
        if self.path == "/api/hiddify/stats":
            body = _stats_json().encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)
        else:
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)


if __name__ == "__main__":
    port = int(os.environ.get("WEB_PORT", 8080))
    print(f"[web_ui] Listening on :{port}", flush=True)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
