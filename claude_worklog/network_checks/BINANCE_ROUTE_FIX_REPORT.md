# Binance Route Fix Report

**Generated:** 2026-04-29T23:50 EDT  
**Workspace:** `/home/wali/Desktop/AI BOT REBUILD`  

---

## PIA Connection State

| Field | Value |
|-------|-------|
| Connection State | **Connected** |
| Region | `dedicated-jp-tokyo-181.214.244.184` |
| VPN IP | `181.214.244.184` |
| PIA pubip (shell) | `98.116.148.30` (ISP — VPN NOT routing shell traffic) |
| Protocol | `openvpn` |
| defaultRoute | `false` (split-tunnel mode) |
| splitTunnelEnabled | `true` |
| splitTunnelDNS | `true` |
| allowLAN | `true` |

---

## Routing Table Analysis

```
default via 10.100.10.1 dev enp11s0  metric 100   ← ACTIVE DEFAULT (ISP)
default via 192.168.1.1 dev wlp8s0   metric 600
default via 10.178.18.1 dev tun0     metric 32000  ← VPN (only used by cgroup marks)
```

PIA ip rules present: `piavpnrt`, `piavpnOnlyrt`, `piavpnFwdrt`, `evpnFwdrt`  
`piavpnOnlyrt` default: `dev tun0 scope link` ← correct VPN-only route table  
`piavpnrt` default: `via 10.100.10.1 dev enp11s0` ← regular internet fallback

Packet marking chain: process in `piavpnonly` cgroup → classid 1384 → nft/iptables sets fwmark 0x3212 → ip rule 100 → lookup `piavpnOnlyrt` → routed via tun0.

---

## Python Public IP Matrix

| Python | Realpath | Public IP | Spot HTTP | Futures HTTP | Verdict |
|--------|----------|-----------|-----------|--------------|---------|
| `/home/wali/Desktop/AI BOT/venv/bin/python3` | `/usr/bin/python3.12` | 98.116.148.30 | **451** | **451** | ❌ FAIL |
| `/home/wali/Desktop/AI BOT/venv/bin/python` | `/usr/bin/python3.12` | 98.116.148.30 | **451** | **451** | ❌ FAIL |
| `/home/wali/Desktop/AI BOT/venv/bin/python3.12` | `/usr/bin/python3.12` | 98.116.148.30 | **451** | **451** | ❌ FAIL |
| `/usr/bin/python3` | `/usr/bin/python3.12` | 98.116.148.30 | **451** | **451** | ❌ FAIL |
| `/usr/bin/python3.12` | `/usr/bin/python3.12` | 98.116.148.30 | **451** | **451** | ❌ FAIL |

All Python executables: using ISP IP, receiving HTTP 451 geo-block from Binance.

---

## DNS / TLS / WebSocket Results

| Check | Result |
|-------|--------|
| DNS — all 4 Binance hosts | ✅ PASS |
| TLS :443 — api.binance.com | ✅ TLSv1.3 |
| TLS :443 — fapi.binance.com | ✅ TLSv1.3 |
| TLS :443 — stream.binance.com | ✅ TLSv1.3 |
| TLS :443 — fstream.binance.com | ✅ TLSv1.3 |
| TLS :443 — ws-api.binance.com | ✅ TLSv1.2 |
| TCP port 9443 — stream.binance.com | ❌ FAIL (timeout/blocked) |
| REST spot_time | ❌ HTTP 451 |
| REST futures_time | ❌ HTTP 451 |

---

## Root Cause Analysis

### Why split tunnel is not working

**PIA split tunnel is configured but not applied.**

Evidence:
```
/opt/piavpn/etc/cgroup/net_cls/piavpnonly/tasks  →  0 lines (EMPTY)
```

No process is in the VPN cgroup. The PIA packet marking chain therefore never fires.

### Cause 1 — Missing `/usr/bin/python3.12` in split tunnel rules

PIA's process monitor matches processes by their kernel `exe` path (from `/proc/PID/exe`).
All Python executables on this system are symlinks to `/usr/bin/python3.12`:

```
/home/wali/Desktop/AI BOT/venv/bin/python3  → /usr/bin/python3.12
/home/wali/Desktop/AI BOT/venv/bin/python   → /usr/bin/python3.12
/usr/bin/python3                             → /usr/bin/python3.12
```

PIA's split tunnel rules include `/usr/bin/python3` but **not `/usr/bin/python3.12`**.
When the kernel starts any Python process, the EXE in `/proc/PID/exe` is `/usr/bin/python3.12`.
PIA does not match this against its rule for `/usr/bin/python3` (symlink).

### Cause 2 — Pre-existing processes not in cgroup

PIA's daemon only classifies processes into the VPN cgroup at launch (via `execve` interception).
All bot processes (PIDs 5131, 142712, 143125, 143308, etc.) were started before PIA's current
split tunnel configuration was applied. PIA cannot retroactively add them.

### Cause 3 — System uses cgroup v2 (unified hierarchy)

```
/sys/fs/cgroup: cgroup2 (unified)
none on /opt/expressvpn/etc/cgroup/net_cls type cgroup (rw,relatime,net_cls)
```

PIA's cgroup net_cls for split tunnel is a cgroup v1 sub-mount under `/opt/piavpn/etc/cgroup/net_cls/`.
This appears to be mounted correctly, but the cgroup v2 primary hierarchy may interfere with
PIA's ability to automatically track new process spawns on this kernel version.

---

## Required Actions

### Action 1 (GUI, no restart needed) — Add `/usr/bin/python3.12` to split tunnel

In PIA GUI → Settings → Split Tunnel, add `/usr/bin/python3.12` as **Only VPN**.
Then reconnect VPN.

### Action 2 (sudo, immediate for running processes) — Manually place PIDs in VPN cgroup

```bash
sudo bash -c '
CGROUP=/opt/piavpn/etc/cgroup/net_cls/piavpnonly/tasks
for pid in 5131 142712 142970 143125 143308 146815 146816 146817 148574 148810 148941 148942 148943 149049 149111 149186 149257 2254001; do
  kill -0 $pid 2>/dev/null && echo $pid > "$CGROUP" && echo "Added $pid" || echo "PID $pid gone"
done
'
```

### Verify after fix

```bash
"/home/wali/Desktop/AI BOT/venv/bin/python3" \
  "$HOME/Desktop/AI BOT REBUILD/tools/check_python_route_to_binance.py" \
  2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['summary'])"
# Expected: public_ip=181.214.244.184, spot_status=200
```

---

## Conclusion

`PIA_APP_SPLIT_TUNNEL_NOT_APPLIED`

PIA split tunnel is configured but not functional because:
1. `/usr/bin/python3.12` (the actual realpath) is missing from split tunnel rules
2. Existing running processes are not in the VPN cgroup (`piavpnonly/tasks` = 0 PIDs)
3. The cgroup tasks file requires root to write, so auto-fix is not possible without sudo

Binance HTTP 451 is a consequence: traffic exits via ISP IP 98.116.148.30 (US geo-block).
DNS and TLS are fully functional. The problem is purely routing/IP geo-restriction.

`BINANCE_ROUTE_FIX_FAIL`
