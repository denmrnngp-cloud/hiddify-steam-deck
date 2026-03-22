#!/usr/bin/env python3
"""
Parse subscription URL or direct proxy URL → sing-box config JSON.
Supports: vless://, vmess://, trojan://, ss://, hy2://, hysteria2://, tuic://
Subscription formats: base64 list, Clash YAML.
"""

import sys
import json
import base64
import re
import urllib.parse
import urllib.request
import ssl

# ── Helpers ────────────────────────────────────────────────────────────────────

def safe_b64decode(s):
    s = s.strip().replace('\n', '').replace(' ', '')
    pad = 4 - len(s) % 4
    if pad != 4:
        s += '=' * pad
    return base64.b64decode(s).decode('utf-8', errors='ignore')


def fetch_url(url, timeout=15):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers={'User-Agent': 'clash/1.0'})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read().decode('utf-8', errors='ignore')


# ── Protocol parsers ───────────────────────────────────────────────────────────

def parse_vless(url):
    """vless://uuid@host:port?params#name"""
    p = urllib.parse.urlparse(url)
    params = dict(urllib.parse.parse_qsl(p.query))
    name = urllib.parse.unquote(p.fragment) or "vless"
    out = {
        "type": "vless",
        "tag": name,
        "server": p.hostname,
        "server_port": p.port or 443,
        "uuid": p.username,
        "flow": params.get("flow", ""),
    }
    security = params.get("security", "")
    if security == "tls":
        out["tls"] = {
            "enabled": True,
            "server_name": params.get("sni", p.hostname),
            "insecure": params.get("allowInsecure", "0") == "1",
        }
    elif security == "reality":
        out["tls"] = {
            "enabled": True,
            "server_name": params.get("sni", p.hostname),
            "utls": {"enabled": True, "fingerprint": params.get("fp", "chrome")},
            "reality": {
                "enabled": True,
                "public_key": params.get("pbk", ""),
                "short_id": params.get("sid", ""),
            },
        }
    transport = params.get("type", "tcp")
    if transport == "ws":
        out["transport"] = {
            "type": "ws",
            "path": params.get("path", "/"),
            "headers": {"Host": params.get("host", p.hostname)},
        }
    elif transport == "grpc":
        out["transport"] = {"type": "grpc", "service_name": params.get("serviceName", "")}
    elif transport == "http":
        out["transport"] = {"type": "http", "path": params.get("path", "/")}
    return name, out


def parse_vmess(url):
    """vmess://base64(json)"""
    data = json.loads(safe_b64decode(url[8:]))
    name = data.get("ps", "vmess")
    port = int(data.get("port", 443))
    out = {
        "type": "vmess",
        "tag": name,
        "server": data.get("add", ""),
        "server_port": port,
        "uuid": data.get("id", ""),
        "alter_id": int(data.get("aid", 0)),
        "security": data.get("scy", "auto"),
    }
    tls_on = str(data.get("tls", "")).lower() in ("tls", "1", "true")
    if tls_on:
        out["tls"] = {
            "enabled": True,
            "server_name": data.get("sni", data.get("add", "")),
            "insecure": str(data.get("allowInsecure", "")).lower() in ("1", "true"),
        }
    net = data.get("net", "tcp")
    if net == "ws":
        out["transport"] = {
            "type": "ws",
            "path": data.get("path", "/"),
            "headers": {"Host": data.get("host", data.get("add", ""))},
        }
    elif net == "grpc":
        out["transport"] = {"type": "grpc", "service_name": data.get("path", "")}
    elif net in ("h2", "http"):
        out["transport"] = {"type": "http", "path": data.get("path", "/")}
    return name, out


def parse_trojan(url):
    """trojan://password@host:port?params#name"""
    p = urllib.parse.urlparse(url)
    params = dict(urllib.parse.parse_qsl(p.query))
    name = urllib.parse.unquote(p.fragment) or "trojan"
    out = {
        "type": "trojan",
        "tag": name,
        "server": p.hostname,
        "server_port": p.port or 443,
        "password": p.username or "",
        "tls": {
            "enabled": True,
            "server_name": params.get("sni", p.hostname),
            "insecure": params.get("allowInsecure", "0") == "1",
        },
    }
    return name, out


def parse_ss(url):
    """ss://base64(method:pass)@host:port#name  or  ss://base64(method:pass@host:port)#name"""
    name = urllib.parse.unquote(urllib.parse.urlparse(url).fragment) or "shadowsocks"
    # New format: ss://BASE64(method:pass)@host:port
    try:
        p = urllib.parse.urlparse(url)
        if p.hostname:
            cred = safe_b64decode(p.username or "")
            method, password = cred.split(":", 1)
            host, port = p.hostname, p.port or 443
        else:
            # Old format: ss://BASE64(method:pass@host:port)
            decoded = safe_b64decode(url[5:].split("#")[0])
            method_pass, hostport = decoded.rsplit("@", 1)
            method, password = method_pass.split(":", 1)
            host, port_s = hostport.rsplit(":", 1)
            port = int(port_s)
        out = {
            "type": "shadowsocks",
            "tag": name,
            "server": host,
            "server_port": port,
            "method": method,
            "password": password,
        }
        return name, out
    except Exception as e:
        raise ValueError(f"Cannot parse ss:// URL: {e}")


def parse_hy2(url):
    """hy2://password@host:port?params#name"""
    p = urllib.parse.urlparse(url)
    params = dict(urllib.parse.parse_qsl(p.query))
    name = urllib.parse.unquote(p.fragment) or "hysteria2"
    out = {
        "type": "hysteria2",
        "tag": name,
        "server": p.hostname,
        "server_port": p.port or 443,
        "password": p.username or "",
        "tls": {
            "enabled": True,
            "server_name": params.get("sni", p.hostname),
            "insecure": params.get("insecure", "0") == "1",
        },
    }
    if params.get("obfs") == "salamander":
        out["obfs"] = {"type": "salamander", "password": params.get("obfs-password", "")}
    return name, out


def parse_tuic(url):
    """tuic://uuid:password@host:port?params#name"""
    p = urllib.parse.urlparse(url)
    params = dict(urllib.parse.parse_qsl(p.query))
    name = urllib.parse.unquote(p.fragment) or "tuic"
    user_info = p.netloc.split("@")[0]
    uuid, password = user_info.split(":", 1) if ":" in user_info else (p.username, "")
    out = {
        "type": "tuic",
        "tag": name,
        "server": p.hostname,
        "server_port": p.port or 443,
        "uuid": uuid,
        "password": password,
        "congestion_control": params.get("congestion_control", "bbr"),
        "tls": {
            "enabled": True,
            "server_name": params.get("sni", p.hostname),
            "insecure": params.get("allowInsecure", "0") == "1",
            "alpn": params.get("alpn", "h3").split(","),
        },
    }
    return name, out


def parse_proxy_url(url):
    url = url.strip()
    if url.startswith("vless://"):
        return parse_vless(url)
    elif url.startswith("vmess://"):
        return parse_vmess(url)
    elif url.startswith("trojan://"):
        return parse_trojan(url)
    elif url.startswith("ss://"):
        return parse_ss(url)
    elif url.startswith(("hy2://", "hysteria2://")):
        return parse_hy2(url)
    elif url.startswith("tuic://"):
        return parse_tuic(url)
    else:
        raise ValueError(f"Unknown protocol: {url[:30]}")


# ── Subscription parser ────────────────────────────────────────────────────────

def parse_subscription(content):
    """Returns list of (name, outbound_dict)."""
    proxies = []

    # Try base64 decode → list of proxy URLs
    try:
        decoded = safe_b64decode(content)
        if any(decoded.startswith(p) for p in ("vless://", "vmess://", "trojan://", "ss://", "hy2://", "hysteria2://", "tuic://")):
            for line in decoded.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    proxies.append(parse_proxy_url(line))
                except Exception as e:
                    print(f"  skip: {e}", file=sys.stderr)
            return proxies
    except Exception:
        pass

    # Try plain list of proxy URLs
    lines = content.strip().splitlines()
    has_proxy_lines = any(
        l.strip().startswith(("vless://", "vmess://", "trojan://", "ss://", "hy2://", "hysteria2://", "tuic://"))
        for l in lines
    )
    if has_proxy_lines:
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                proxies.append(parse_proxy_url(line))
            except Exception as e:
                print(f"  skip: {e}", file=sys.stderr)
        return proxies

    # Try Clash YAML (basic extraction)
    try:
        import re
        proxy_blocks = re.findall(r'(?ms)^- name:.*?(?=^- name:|\Z)', content)
        for block in proxy_blocks:
            name_m = re.search(r'name:\s*(.+)', block)
            type_m = re.search(r'type:\s*(\S+)', block)
            server_m = re.search(r'server:\s*(.+)', block)
            port_m = re.search(r'port:\s*(\d+)', block)
            if name_m and type_m and server_m and port_m:
                name = name_m.group(1).strip().strip('"\'')
                ptype = type_m.group(1).strip().lower()
                server = server_m.group(1).strip()
                port = int(port_m.group(1))
                # Map Clash types to sing-box types
                type_map = {"vless": "vless", "vmess": "vmess", "trojan": "trojan",
                            "ss": "shadowsocks", "hy2": "hysteria2", "hysteria2": "hysteria2",
                            "tuic": "tuic"}
                if ptype in type_map:
                    proxies.append((name, {
                        "type": type_map[ptype],
                        "tag": name,
                        "server": server,
                        "server_port": port,
                    }))
    except Exception as e:
        print(f"Clash parse error: {e}", file=sys.stderr)

    return proxies


# ── Config builder ─────────────────────────────────────────────────────────────

def build_singbox_config(outbound, tun=True, log_level="info", proxy_domains=None):
    # Force the outbound tag to "proxy" so route rules work
    outbound = dict(outbound)
    outbound["tag"] = "proxy"

    # Route rules: private/multicast IPs → direct (these bypass TUN via route_exclude_address
    # but also listed here as safety). All other public traffic → proxy (VPN).
    # proxy_domains is kept for backwards compatibility but SNI sniffing is unreliable;
    # the reliable approach is to proxy ALL public traffic and exclude private ranges from TUN.
    route_rules = [
        {"ip_is_private": True, "outbound": "direct"},
    ]

    # Route to exclude from proxy (go direct even if public): user-specified domains
    # Note: SNI-based domain matching requires sniffing which may not always work.
    # The final "proxy" handles everything else (Spotify, etc.) via VPN.

    cfg = {
        "log": {"level": log_level, "output": ""},
        "dns": {
            "servers": [
                {"tag": "dns-direct", "address": "8.8.8.8"},
            ],
            "final": "dns-direct",
            "strategy": "prefer_ipv4",
        },
        "outbounds": [
            outbound,
            {"type": "direct", "tag": "direct"},
            {"type": "block",  "tag": "block"},
        ],
        "route": {
            "rules": route_rules,
            "final": "proxy",
            "auto_detect_interface": True,
        },
    }

    # Ranges excluded from TUN routing entirely (bypass TUN, go direct via host network).
    # This keeps local LAN, Docker networks, mDNS multicast, and loopback working normally.
    tun_exclude = [
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "224.0.0.0/4",   # multicast (mDNS, UPnP/SSDP, etc.)
        "240.0.0.0/4",   # reserved/broadcast
        "fc00::/7",
        "fe80::/10",
        "::1/128",
        "ff00::/8",      # IPv6 multicast
    ]

    if tun:
        cfg["inbounds"] = [{
            "type": "tun",
            "tag": "tun-in",
            "address": ["172.19.0.1/30", "fdfe:dcba:9876::1/126"],
            "mtu": 1500,
            "auto_route": True,
            "strict_route": False,
            "stack": "system",
            "sniff": True,
            "sniff_override_destination": True,
            "route_exclude_address": tun_exclude,
        }]
    else:
        cfg["inbounds"] = [
            {"type": "socks", "tag": "socks-in", "listen": "0.0.0.0", "listen_port": 2080},
            {"type": "http", "tag": "http-in",  "listen": "0.0.0.0", "listen_port": 2081},
        ]

    return cfg


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--url",            required=True, help="Subscription or proxy URL")
    ap.add_argument("--index",          type=int, default=0, help="Profile index (0 = first)")
    ap.add_argument("--tun",            action="store_true", default=True)
    ap.add_argument("--no-tun",         dest="tun", action="store_false")
    ap.add_argument("--log",            default="info")
    ap.add_argument("--out",            default="/data/hiddify/config.json")
    ap.add_argument("--list",           action="store_true", help="List profiles and exit")
    ap.add_argument("--proxy-domains",  default="", help="Comma-separated domain suffixes to route via proxy (default: all traffic)")
    args = ap.parse_args()

    url = args.url.strip()
    print(f"[parse_sub] URL: {url[:80]}...", file=sys.stderr)

    # Direct proxy URL?
    if any(url.startswith(p) for p in ("vless://", "vmess://", "trojan://", "ss://", "hy2://", "hysteria2://", "tuic://")):
        proxies = [parse_proxy_url(url)]
    else:
        print("[parse_sub] Fetching subscription...", file=sys.stderr)
        content = fetch_url(url)
        proxies = parse_subscription(content)

    if not proxies:
        print("ERROR: No proxies found", file=sys.stderr)
        sys.exit(1)

    print(f"[parse_sub] Found {len(proxies)} profile(s):", file=sys.stderr)
    for i, (name, _) in enumerate(proxies):
        marker = " ◄" if i == args.index else ""
        print(f"  [{i}] {name}{marker}", file=sys.stderr)

    if args.list:
        # Print JSON list for shell to consume
        print(json.dumps([name for name, _ in proxies]))
        return

    idx = min(args.index, len(proxies) - 1)
    name, outbound = proxies[idx]
    print(f"[parse_sub] Using profile [{idx}]: {name}", file=sys.stderr)

    proxy_domains = [d.strip() for d in args.proxy_domains.split(",") if d.strip()] if args.proxy_domains else None
    cfg = build_singbox_config(outbound, tun=args.tun, log_level=args.log, proxy_domains=proxy_domains)

    import os
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    print(f"[parse_sub] Config written to {args.out}", file=sys.stderr)

    # Output selected profile name for shell
    print(name)


if __name__ == "__main__":
    main()
