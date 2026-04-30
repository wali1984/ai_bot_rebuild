# PIA GUI Split Tunnel Fix — Verification Report

**Date:** 2026-04-30T03:59 UTC  
**Branch:** stabilize/hedge-7actions

## Fix Applied
User added `/usr/bin/python3.12` to PIA GUI → Split Tunnel → "Only VPN" list and reconnected.

## Additional Fix Required (ExpressVPN daemon conflict)
The ExpressVPN daemon (PID 1908) was running in the background with a leftover iptables REJECT rule:
```
Chain evpn.r.340.blockVpnOnly:
REJECT all -- cgroup 1384 reject-with icmp-port-unreachable
```
This rule blocked ALL outbound traffic from PIA's piavpnonly cgroup (classid 1384), causing
`ConnectionRefusedError(111)` for every Python TCP connection even though the cgroup/routing
was correctly configured.

**Fix:** `sudo iptables -D evpn.r.340.blockVpnOnly 1`

## Verification Results

| Check | Result |
|-------|--------|
| Python executable | `/usr/bin/python3.12` |
| Python cgroup | `net_cls:/piavpnonly` (PIA VPN-only cgroup) |
| PIA VPN IP | `181.214.244.184` (dedicated-jp-tokyo) |
| Python public IP | `181.214.244.184` ✅ matches VPN IP |
| spot_status (api.binance.com) | **200 OK** ✅ |
| futures_status (fapi.binance.com) | **200 OK** ✅ |
| TLS (api.binance.com) | TLSv1.3 ✅ |
| TLS (fapi.binance.com) | TLSv1.3 ✅ |
| TLS (fstream.binance.com) | TLSv1.3 ✅ |
| DNS resolution (all 4 hosts) | ✅ |

## Root Cause Chain (complete)
1. PIA split tunnel was missing `/usr/bin/python3.12` → piavpnonly/tasks=0 → HTTP 451 geo-block
2. After GUI fix: cgroup assignment worked BUT ExpressVPN daemon's leftover iptables rule
   `REJECT cgroup 1384` blocked all outbound TCP from PIA VPN-only cgroup
3. After deleting that one iptables rule: Python routes correctly through tun0 (PIA Tokyo)

## Important: Persistence Warning
The `sudo iptables -D evpn.r.340.blockVpnOnly 1` fix is **not persistent** across reboots or
if the ExpressVPN daemon re-applies its rules. To make permanent:
- Option A: Uninstall ExpressVPN if not in use
- Option B: Add the delete to a startup script (e.g., `/etc/rc.local` or systemd unit)
- Option C: Use `iptables-save` after fix + `iptables-restore` on boot

PIA_GUI_FIX_PASS
