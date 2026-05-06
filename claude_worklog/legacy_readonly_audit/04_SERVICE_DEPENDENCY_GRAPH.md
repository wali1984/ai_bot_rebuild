# Legacy Service Dependency Graph

Generated: 2026-05-06T20:40:01.144999+00:00

Evidence-based approximate graph from startup script and known running services.

```text
redis-server
  -> ingestors
      -> live_binance.py
      -> live_kucoin.py
      -> live_coinank.py
      -> live_binance_liquidations.py
      -> live_coinank_global_aggregator.py
      -> ingest.live_coinapi_wsds
      -> ingest.live_coinapi_v1
  -> market data bridges
      -> liquidation_bridge.py
      -> liquidation_levels_engine.py
      -> realtime_price_provider.py
  -> pipelines
      -> ohlcv_resampler_hotfix.py
      -> feature_pipeline.py
      -> live_technical_analysis.py
  -> trainer
      -> rl.hybrid_trainer
      -> monitor_trainer_predictions.py
      -> monitor_trainer_prices.py
  -> orchestrator
      -> rl.orchestrator_worker
  -> trader
      -> trading/trader.py
      -> trading/trader-asjad.py if enabled
  -> portfolio monitors
      -> monitor_portfolio_primary.py
      -> monitor_portfolio_asjad.py
```
