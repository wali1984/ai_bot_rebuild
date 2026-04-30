# PIA VPN Status & Public IP

**Generated:** 2026-04-29T23:30 EDT

## PIA VPN Daemon Status

| Field | Value |
|-------|-------|
| Connection State | **Connected** |
| Region | `dedicated-jp-tokyo-181.214.244.184` |
| VPN IP (assigned) | `181.214.244.184` |
| tun0 IP | `10.178.18.2/24` |
| PIA daemon PIDs | 2292179 (pia-daemon), 2292182 (pia-client), 2350248 (pia-openvpn) |

## Active Routing Table (ip route show default)

```
default via 10.100.10.1 dev enp11s0 proto dhcp src 10.100.10.10 metric 100   ← LOWEST metric = WINS
default via 192.168.1.1 dev wlp8s0  proto dhcp src 192.168.1.105 metric 600
default via 10.178.18.1 dev tun0    metric 32000                              ← VPN (highest metric = IGNORED)
```

## Public IP (as seen by Binance)

```
98.116.148.30   ← US-based IP — routes via enp11s0, NOT through tun0
```

## Root Cause

PIA is connected (tun0 up, openvpn running) but the VPN route on `tun0` has **metric 32000**,
much higher than the direct ethernet route (metric 100). As a result, **all traffic bypasses
the VPN** and exits through the raw ISP connection with a US IP (`98.116.148.30`).

Binance returns **HTTP 451 "Unavailable For Legal Reasons"** for US-sourced requests to its
public REST API — this is a geo-block affecting all Python executables equally.

## PureVPN (separate, also running)

PureVPN GUI processes are also visible (`/opt/PureVPN/purevpn`), but contribute no active tunnel.
