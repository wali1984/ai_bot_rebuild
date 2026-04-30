# Binance Connectivity Matrix

**Generated:** 2026-04-29T23:35 EDT  
**Public IP seen by Binance:** `98.116.148.30` (US IP — geo-blocked)  
**PIA VPN:** Connected to `dedicated-jp-tokyo` but tun0 metric=32000 causes all traffic to bypass VPN

## REST API Connectivity Matrix

| Python Executable | DNS (5 hosts) | TLS :443 (5 hosts) | REST (4 endpoints) | Public IP | Verdict |
|-------------------|---------------|--------------------|--------------------|-----------|---------|
| `/home/wali/Desktop/AI BOT/venv/bin/python3` | ✅ 0 fail | ✅ 0 fail | ❌ 4 fail (HTTP 451) | 98.116.148.30 | **FAIL** |
| `/home/wali/Desktop/AI BOT/venv/bin/python` | ✅ 0 fail | ✅ 0 fail | ❌ 4 fail (HTTP 451) | 98.116.148.30 | **FAIL** |
| `/usr/bin/python3` | ✅ 0 fail | ✅ 0 fail | ❌ 4 fail (HTTP 451) | 98.116.148.30 | **FAIL** |
| `/usr/bin/python3.12` | ✅ 0 fail | ✅ 0 fail | ❌ 4 fail (HTTP 451) | 98.116.148.30 | **FAIL** |
| `python3` (PATH) | ✅ 0 fail | ✅ 0 fail | ❌ 4 fail (HTTP 451) | 98.116.148.30 | **FAIL** |

## WebSocket TLS Port Connectivity

| Host | Port | TCP Reachable | TLS Verify | Result |
|------|------|---------------|------------|--------|
| stream.binance.com | 443 | ✅ | ✅ OK (verify=0) | **PASS** |
| stream.binance.com | 9443 | ❌ TIMEOUT | N/A | **FAIL** |
| fstream.binance.com | 443 | ✅ | ✅ OK | **PASS** |
| ws-api.binance.com | 443 | ✅ | ✅ OK | **PASS** |

## REST Error Detail (consistent across all Pythons)

```
HTTP Error 451: Unavailable For Legal Reasons
  - https://api.binance.com/api/v3/time
  - https://fapi.binance.com/fapi/v1/time
  - https://api.binance.com/api/v3/exchangeInfo
  - https://fapi.binance.com/fapi/v1/exchangeInfo
```

HTTP 451 = Binance geo-block for restricted regions (US). All traffic exits via IP `98.116.148.30`
regardless of Python runtime because the VPN tunnel (tun0) has metric 32000 vs ethernet metric 100.
