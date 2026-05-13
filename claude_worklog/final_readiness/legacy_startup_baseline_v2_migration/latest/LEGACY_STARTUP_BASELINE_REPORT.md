# LEGACY_STARTUP_BASELINE_REPORT — Phase B

Authoritative parse of `scripts/start_all_services_production.sh` (932 lines, 43 KB) under the operator-shut-down legacy root.

## Phase-by-phase summary

| phase | purpose | key scripts | wait / gates |
|---|---|---|---|
| **0** preflight | `FORCE_KILL_ALL_BOT_PY` guard; clears Redis ingestor locks if forced; checks VRAM ≥ 3 GB, RAM ≥ 10 GB, disk < 85 %, `redis-server` alive, `nvidia-smi -pm 1` | none (env + shell) | aborts on duplicates or insufficient VRAM |
| **0.5** monitoring | `vpn_monitor.py`, `system_telegram_monitor.py`, `monitor_system_memory.py`, `scripts/memory_monitor.py`, `scripts/monitor_trainer_predictions.py`; gnome-terminal `scripts/check_services_detailed.sh` + `scripts/monitor_dashboard.sh` | each `nohup … &` with `logs/*.{log,pid}` | none |
| **1** ingestors | `ingest/live_binance.py`, `ingest/live_kucoin.py`, `ingest/live_coinank.py`, `ingest/live_coinank_global_aggregator.py`, `ingest/live_binance_liquidations.py`, `ingest/liquidation_bridge.py`, `ingest/liquidation_levels_engine.py`, `ingest/realtime_price_provider.py`, `ingest/live_coinapi_wsds.py`, `ingest/live_coinapi_v1.py` | `nice -n 10 taskset -c 0-7 python3 …` → 15 s warmup → `scripts/paralysis_detectors.py --minutes 5` |
| **2** feature pipeline | `ohlcv_resampler_hotfix.py`, `feature_pipeline.py` | 20 s wait, memory check ≤ 85 % |
| **2.5** TA | `ingest/live_technical_analysis.py` (PID file at `run/live_technical_analysis.pid`) | redis PING preflight; 10 s warmup; HGET `ta:ETHUSDT:1m` heartbeat probe |
| **2.9** validation gate | `scripts/validate_symbol_universe_data.py` | retries `STARTUP_VALIDATE_RETRIES` (default 10) × `STARTUP_VALIDATE_SLEEP_SEC` (default 15s) — fails closed on persistent failure |
| **3** trainer | `python3 -m rl.hybrid_trainer --mode hybrid --training-mode <real-mode> --enhanced-features` | 45 s init + 9 × 5 s memory polling; OOM score +200 set on trainer PID; reads canonical signal streams |
| **3B** orchestrator worker | `python3 -m rl.orchestrator_worker [--shadow]` (controlled by `ORCHESTRATOR_WORKER_ENABLED` + `ORCHESTRATOR_WORKER_MODE` from `config.py`) | consumer group `orchestrator_workers`, proposal stream `wma:proposals` |
| **4B** traders | `trading/trader.py`, `trading/trader-asjad.py` | **V2 must never start these — fail-closed stub only at P2** |
| **4C** portfolio monitors | `monitor_portfolio_primary.py`, `monitor_portfolio_asjad.py` | 10 s after traders |
| **5** health | `scripts/health_probe.py` → grep `GO FOR LAUNCH` | logs to `/tmp/health_check.log` |

## Env variables exported by the script

`ENABLE_SIGNAL_DECONFLICTION`, `ENABLE_GPU_BATCH_INFERENCE`, `ENABLE_EXECUTION_FEEDBACK`, `GPU_BATCH_SIZE` (when `--section7`); `ADAPTIVE_HEDGE_V2_ENABLED`, `LEG_INDEPENDENT_ENABLED`, `MARGIN_85_ENABLED`, `BINANCE_LIQ_PRIMARY`, `DEPTH_EXECUTION_GATE_ENABLED`; `DISABLE_BINANCE_OHLCV`, `COINAPI_SUBSCRIBE_DATA_TYPES`, `COINAPI_ALLOW_TRADE`, `COINAPI_ALLOW_FULL_BOOK`; `PYTHONPATH`.

## Redis streams the legacy stack reads/writes

Legacy writers (V2 must NOT replicate these writes):

- `trainer:predictions` (trainer writer)
- `wma:proposals` (proposal/orchestrator consumer-producer chain)
- canonical signals stream (orchestrator publisher)
- per-account signals streams
- `market:{symbol}:{tf}` (ingestor writers)
- `ta:{symbol}:{tf}` (TA writer)
- ingestor single-instance lock keys

V2 stance: **read-only references only**. V2 workers write V2-namespaced streams (`v2:*`) and never write any of the above.

## Cross-cutting safety checks (any of these blocks startup)

- duplicate bot py3 worker processes detected without `FORCE_KILL_ALL_BOT_PY=1`
- VRAM < 3 GB (even after killing trainer + feature_pipeline)
- RAM < 10 GB (interactive prompt)
- `redis-server` not pgrep-alive
- pre-trainer memory > 80 %
- mid-trainer memory ≥ 95 % (kernel-side OOM avoidance)
- universe validation persistently fails (10 retries × 15 s)
- paralysis detectors with `STARTUP_PARALYSIS_DETECTORS_STRICT=1` reports alerts

## Implicit dependencies (inferred from the script)

- `config.py` is imported via `python3 -c "from config import ORCHESTRATOR_WORKER_ENABLED ..."` — must be in PYTHONPATH; expected at `BASE_DIR/config.py`
- `venv/bin/activate` — legacy expects its own venv; V2 will use `.venv/bin/python3` instead
- `logs/` directory must exist (script writes `logs/*.log`, `logs/*.pid`)
- `run/` directory must exist (TA PID file)
- `scripts/stop_all_services_production.sh` (referenced as cleanup) and `scripts/stop_ingestors.sh` (fallback)

## How this baseline maps to V2 priorities

| legacy phase | V2 P0 worker | V2 P1 worker |
|---|---|---|
| 1 ingestors (binance + kucoin + coinapi + realtime price provider) | `v2_market_ingestor_from_legacy_baseline` | — |
| 1 ingestors (coinank + coinank_global + binance_liquidations + liquidation_bridge + liquidation_levels_engine) | `v2_coinank_and_liquidation_bridge_from_legacy_baseline` | — |
| 2 / 2.5 / 2.9 feature pipeline + TA + universe validation | `v2_feature_pipeline_and_ta_worker_from_legacy_baseline` | — |
| 3 trainer | — | `v2_trainer_bridge_from_legacy_hybrid_trainer` |
| 3B orchestrator | — | `v2_orchestrator_adapter_from_legacy_worker` |
| 4B trader (DO NOT START) | — | `v2_trader_fail_closed_stub_from_legacy_trader` (P2, fail-closed) |
| 4C portfolio monitors | `v2_account_position_readonly_monitor` | — |
| 5 health probe | — | `v2_script_monitor` consumes it |
| pre-existing risk gateway / paper execution / execution ledger / signal lineage / feature snapshot builder | P0 (no direct legacy 1:1 — V2-native gates) | — |

## Required copy set (Phase C input — 30 files)

See [legacy_startup_baseline_matrix.json](legacy_startup_baseline_matrix.json) and [copied_baseline_manifest.json](copied_baseline_manifest.json) (produced after Phase C completes).
