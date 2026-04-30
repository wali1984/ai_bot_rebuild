# Binance Public Connectivity Report

**Generated:** 2026-04-29T23:38 EDT  
**Scope:** Post-PIA-VPN-install connectivity verification  
**Workspace:** `/home/wali/Desktop/AI BOT REBUILD`  
**Production Bot:** `/home/wali/Desktop/AI BOT` (NOT modified)

---

## Executive Summary

All 5 Python executables tested return **HTTP 451 (Unavailable For Legal Reasons)** on every
Binance public REST endpoint. This is a **Binance geo-block** caused by the bot's traffic
exiting through a US IP address (`98.116.148.30`) because PIA VPN routing is misconfigured.

---

## Findings

### 1. PIA VPN Is Connected But NOT Routing Traffic

PIA VPN is running (OpenVPN tunnel `tun0` is up, VPN IP = `181.214.244.184`, Japan Tokyo).
However the routing table shows:

```
default via 10.100.10.1 dev enp11s0  metric 100   ← WINS (lowest metric)
default via 10.178.18.1 dev tun0     metric 32000  ← LOSES (highest metric)
```

Linux uses the lowest-metric default route. All traffic bypasses `tun0` and exits via `enp11s0`
with the raw US IP `98.116.148.30`.

### 2. HTTP 451 on All REST Endpoints

Every REST call to `api.binance.com` and `fapi.binance.com` returns HTTP 451.
This is Binance's response to IPs in geo-restricted regions (including the US).
The error is **identical for all 5 Python runtimes** — it is a routing/IP problem, NOT a
Python or library issue.

### 3. DNS Resolution: PASS

All 5 Binance hostnames resolve correctly. DNS is functional.

### 4. TLS on Port 443: PASS

TLS handshakes succeed on port 443 for all 5 Binance hosts (TLSv1.2/1.3, cert `*.binance.com`).
The geo-block happens at the HTTP application layer (after TLS), not at TCP/TLS level.

### 5. WebSocket TLS Ports

| Host:Port | Result |
|-----------|--------|
| stream.binance.com:443 | ✅ PASS |
| stream.binance.com:9443 | ❌ FAIL (TCP timeout) |
| fstream.binance.com:443 | ✅ PASS |
| ws-api.binance.com:443 | ✅ PASS |

`stream.binance.com:9443` is unreachable from this IP — likely also geo-blocked or firewall-dropped.
The live bot uses port 443 WebSocket connections (confirmed from ingestor code), so this is not
an immediate operational issue.

### 6. Production Bot Impact Assessment

The production bot processes (`hybrid_trainer`, `trader.py`, ingestors) use `/usr/bin/python3.12`
(EXE shows `(deleted)` — started before a Python package update but still running). They connect
to Binance via the same network stack and will also be using IP `98.116.148.30`. 

**HOWEVER:** The live bot appears to still be running (143125 hybrid_trainer, 143308 trader.py,
142712 live_binance.py all active). This suggests one of:
- The bot uses the Binance Futures API authenticated with API keys which may bypass geo-block
- The bot's API keys are whitelisted or the geo-block only affects unauthenticated public endpoints
- WebSocket connections (which DO succeed on :443) are used for market data, and REST with auth headers bypass 451

---

## Root Cause

**PIA VPN metric too high (32000) vs ethernet (100).** Traffic never routes through tun0.

### Fix

To force traffic through PIA VPN:

```bash
# Option A: Lower tun0 metric (temporary, survives restart of piactl)
sudo ip route del default via 10.178.18.1 dev tun0
sudo ip route add default via 10.178.18.1 dev tun0 metric 50

# Option B: Use piactl to set as default route (proper method)
piactl set allowlan false        # Forces all traffic through VPN
# Or in PIA Settings → Network → "Route all traffic through VPN"

# Verify fix:
ip route show default
curl -s https://api.ipify.org   # Should show VPN IP 181.214.244.184
```

---

## Verdict

`BINANCE_CONNECTIVITY_FAIL`
