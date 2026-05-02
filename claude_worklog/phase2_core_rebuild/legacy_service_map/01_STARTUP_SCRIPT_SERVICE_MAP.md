# Startup Script Service Map

Startup script readable: True

Extracted service phases:

- Phase 0: `redis-server` via `redis-server`
- Phase 0.5: `scripts/memory_monitor.py` via `scripts/memory_monitor.py`
- Phase 0.5: `scripts/monitor_trainer_predictions.py` via `scripts/monitor_trainer_predictions.py`
- Phase 0.5: `vpn_monitor.py` via `vpn_monitor.py`
- Phase 0.5: `system_telegram_monitor.py` via `system_telegram_monitor.py`
- Phase 0.5: `monitor_system_memory.py` via `monitor_system_memory.py`
- Phase 1: `live_binance.py` via `ingest/live_binance.py`
- Phase 1: `live_kucoin.py` via `ingest/live_kucoin.py`
- Phase 1: `live_coinank.py` via `ingest/live_coinank.py`
- Phase 1: `live_binance_liquidations.py` via `ingest/live_binance_liquidations.py`
- Phase 1: `liquidation_bridge.py` via `ingest/liquidation_bridge.py`
- Phase 1: `liquidation_levels_engine.py` via `ingest/liquidation_levels_engine.py`
- Phase 1: `realtime_price_provider.py` via `ingest/realtime_price_provider.py`
- Phase 1: `live_coinank_global_aggregator.py` via `ingest/live_coinank_global_aggregator.py`
- Phase 1: `ingest.live_coinapi_wsds` via `python3 -m ingest.live_coinapi_wsds`
- Phase 1: `ingest.live_coinapi_v1` via `python3 -m ingest.live_coinapi_v1`
- Phase 2: `ohlcv_resampler_hotfix.py` via `ohlcv_resampler_hotfix.py`
- Phase 2: `feature_pipeline.py` via `feature_pipeline.py`
- Phase 2.5: `live_technical_analysis.py` via `ingest/live_technical_analysis.py`
- Phase 3: `rl.hybrid_trainer` via `python3 -m rl.hybrid_trainer`
- Phase 3B: `rl.orchestrator_worker` via `python3 -m rl.orchestrator_worker`
- Phase 4B: `trading/trader.py` via `trading/trader.py`
- Phase 4B: `trading/trader-asjad.py` via `trading/trader-asjad.py`
- Phase 4C: `monitor_portfolio_primary.py` via `monitor_portfolio_primary.py`
- Phase 4C: `monitor_portfolio_asjad.py` via `monitor_portfolio_asjad.py`
- one-shot: `scripts/paralysis_detectors.py` via `scripts/paralysis_detectors.py`
- one-shot: `scripts/validate_symbol_universe_data.py` via `scripts/validate_symbol_universe_data.py`
- one-shot: `scripts/health_probe.py` via `scripts/health_probe.py`

Script notes:
- It has duplicate prevention and optional force-kill behavior; V2 must not invoke this.
- It includes Redis start/restart behavior; V2 must not restart Redis.
- It exports live feature flags and GPU trainer flags; V2 must preserve trainer/GPU assumptions.
- It starts `rl.orchestrator_worker` conditionally through `ORCHESTRATOR_WORKER_ENABLED`.
- Final display grep omits `orchestrator_worker`; treat that as a display bug only.
- `trading/signal_router.py`, `scripts/ingestors_watchdog.py`, and critical health monitor cron are removed/deprecated from this startup lane.

STARTUP_SCRIPT_SERVICE_MAP_READY
