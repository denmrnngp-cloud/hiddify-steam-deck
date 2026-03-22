# Hiddify VPN — Home Assistant Add-on

Routes traffic through a VPN using [sing-box](https://github.com/SagerNet/sing-box).

## Setup

1. Add this repository to Home Assistant:
   **Settings → Add-ons → Add-on Store → ⋮ → Repositories** → paste the URL

2. Install **Hiddify VPN** from the list

3. Open **Configuration** and set:
   - `subscription_url` — your VPN subscription link or a direct proxy URL
   - `selected_profile` — profile index from the subscription (0 = first)
   - `tun_mode` — `true` routes all traffic, `false` = SOCKS5 :2080 / HTTP :2081 only

4. Start the add-on

## Configuration

```yaml
subscription_url: "https://example.com/sub?token=xxx"
selected_profile: 0
tun_mode: true
log_level: "info"
```

### subscription_url

Accepts:
- **Subscription URL** — `https://` link that returns a list of proxies (base64, Clash YAML)
- **Direct proxy URL** — `vless://`, `vmess://`, `trojan://`, `ss://`, `hy2://`, `tuic://`

### selected_profile

Index of the proxy to use from the subscription list (starting at 0).

### tun_mode

- `true` — creates a TUN interface, all traffic from the HA host is routed through VPN
- `false` — SOCKS5 proxy on port `2080`, HTTP proxy on port `2081`

## Home Assistant Entities

After the add-on starts, these sensors appear automatically:

| Entity | Description |
|---|---|
| `sensor.hiddify_status` | `connected` / `connecting` / `disconnected` / `error` |
| `sensor.hiddify_ip` | External IP address when connected |
| `sensor.hiddify_profile` | Name of the active profile |

## Supported Protocols

VLESS · VLESS+Reality · VMess · Trojan · Shadowsocks · Hysteria2 · TUIC
