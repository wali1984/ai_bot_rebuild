# Trader/Trainer API Error Post-Fix Report

Generated: 2026-04-30T04:07 UTC

---

## 1. Fresh Python Connectivity

| Check | Value | Status |
|-------|-------|--------|
| Python executable | /usr/bin/python3.12 | - |
| Python cgroup | net_cls:/piavpnonly | ✅ IN VPN CGROUP |
| Public IP | 181.214.244.184 | ✅ MATCHES PIA TOKYO |
| spot_status (api.binance.com) | 200 | ✅ PASS |
| futures_status (fapi.binance.com) | 200 | ✅ PASS |
| rest_ok | True | ✅ PASS |

**Fresh Python Connectivity: PASS**

---

## 2. Current Bot PID Cgroup Status

Total bot/python process PIDs inspected: 21 (python3.12 processes)

**Bot PIDs NOT in piavpnonly (bypassing VPN, using real IP):**

| PID | Process | Started | Cgroup |
|-----|---------|---------|--------|
| 5131 | python3 -m rl.orchestrator_worker | Apr25 | net_cls:/ (root) |
| 142712 | python3 ingest/live_binance.py | Apr26 | net_cls:/ (root) |
| 142970 | python3 ingest/live_binance_liquidations.py | Apr26 | net_cls:/ (root) |
| 143125 | python3 -m rl.hybrid_trainer | Apr26 | net_cls:/ (root) |
| 143308 | python3 trading/trader.py | Apr26 | net_cls:/ (root) |
| 146815 | python3 ingest/live_coinank.py | Apr26 | net_cls:/ (root) |
| 146816 | python3 ingest/liquidation_levels_engine.py | Apr26 | net_cls:/ (root) |
| 146817 | python3 ingest/live_technical_analysis.py | Apr26 | net_cls:/ (root) |
| 148574 | python3 scripts/ingestors_watchdog.py | Apr26 | net_cls:/ (root) |
| 148810 | python3 ingest/live_kucoin.py | Apr26 | net_cls:/ (root) |
| 148941 | python3 ingest/live_coinank_global_aggregator.py | Apr26 | net_cls:/ (root) |
| 148942 | python3 ingest/liquidation_bridge.py | Apr26 | net_cls:/ (root) |
| 148943 | python3 ingest/realtime_price_provider.py | Apr26 | net_cls:/ (root) |
| 149049 | python3 -m ingest.live_coinapi_wsds | Apr26 | net_cls:/ (root) |
| 149111 | python3 -m ingest.live_coinapi_v1 | Apr26 | net_cls:/ (root) |
| 149186 | python3 ohlcv_resampler_hotfix.py | Apr26 | net_cls:/ (root) |
| 149257 | python3 feature_pipeline.py | Apr26 | net_cls:/ (root) |

**Bot PIDs IN piavpnonly (correctly routed through VPN):**

| PID | Process | Started | Cgroup |
|-----|---------|---------|--------|
| 2254001 | python3 Desktop/AI BOT/monitor_portfolio_primary.py | Apr29 | net_cls:/piavpnonly |

**Summary: 17 critical bot processes NOT in piavpnonly / 1 in piavpnonly**

**Root cause**: All processes were started Apr25-Apr26, BEFORE the PIA GUI split tunnel fix was applied.
Running processes cannot be retroactively moved to piavpnonly by PIA — they must be restarted.

Note: EXE shows `/usr/bin/python3.12 (deleted)` for all Apr25-Apr26 processes — they were also
started before a Python package update replaced the binary on disk (processes still running from
the old inode in memory, separately from the cgroup issue).

---

## 3. Recent API Errors

| Log File | Timestamp Range | Error | Continuing? |
|----------|----------------|-------|-------------|
| .logs/trader-primary.log | 2026-04-29 23:46 → 2026-04-30 00:05+ | HTTP 451: Service unavailable from restricted location | YES - continuous |
| .logs/trader.log | Most recent tail | HTTP 451: Failed to sync positions / Error checking balance | YES - continuous |

**Error pattern**: `APIError(code=0): Service unavailable from a restricted location` on:
- `❌ Error checking balance` — private balance endpoint
- `❌ Failed to sync positions` — private futures positions endpoint

These calls use the real IP (98.116.148.30) because trader PID 143308 is NOT in piavpnonly.

Errors began: At least since 2026-04-29 23:46 (log line 142171 in trader-primary.log)
Last observed: 2026-04-30 00:05+ (continuing as of scan time)
Before/after fix: Errors are POST-fix time but pre-cgroup-remount fix (PIA cgroup was broken
by ExpressVPN uninstall between 23:46 and this session's cgroup remount at ~04:05 UTC)

Trainer log (.logs/hybrid_trainer.log): No HTTP 451 errors — trainer uses Redis market data
(not direct Binance API calls), so it's unaffected by VPN routing.

Live binance ingestor (.logs/live_binance.log): Shows "Starting Binance fetch cycle..." — public
OHLCV endpoint appears to be working, possibly Binance's geo-block is endpoint-type dependent.

---

## 4. Recommended Action

**CONTROLLED_RESTART_REQUIRED_FOR_EXISTING_PROCESSES**

Reason: All critical trading processes (trader, trainer, all ingestors, orchestrator) started
Apr25-Apr26 are in root cgroup (net_cls:/) and bypass PIA VPN routing. The trader is actively
logging HTTP 451 errors on every balance/position sync attempt. These processes need a controlled
restart to be spawned fresh into the piavpnonly cgroup.

Additionally: The PIA cgroup mount fix (replacing broken symlink to uninstalled ExpressVPN with
real mount) must be made persistent — see EXPRESSVPN_CONFLICT_PERSISTENCE_OPTIONS.md.

---

## 5. Additional Findings

- ExpressVPN uninstall removed the kernel net_cls cgroup v1 mount that PIA depended on
  (PIA's /opt/piavpn/etc/cgroup/net_cls was a symlink to /opt/expressvpn/etc/cgroup/net_cls)
- Temporary fix applied this session:
  sudo rm /opt/piavpn/etc/cgroup/net_cls (broken symlink)
  sudo mkdir /opt/piavpn/etc/cgroup/net_cls
  sudo mount -t cgroup -o net_cls none /opt/piavpn/etc/cgroup/net_cls/
  piactl disconnect && piactl connect
- This fix is NOT persistent across reboot — a fstab or systemd mount unit is required

BOT_BINANCE_CONNECTIVITY_NEEDS_PROCESS_RESTART
