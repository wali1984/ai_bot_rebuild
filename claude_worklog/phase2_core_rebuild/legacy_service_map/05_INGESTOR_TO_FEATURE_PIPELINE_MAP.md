# Ingestor to Feature Pipeline Map

Ingestors and bridges:
- `live_binance.py`
- `live_kucoin.py`
- `live_coinank.py`
- `live_binance_liquidations.py`
- `liquidation_bridge.py`
- `liquidation_levels_engine.py`
- `realtime_price_provider.py`
- `live_coinank_global_aggregator.py`
- `ingest.live_coinapi_wsds`
- `ingest.live_coinapi_v1`

Feature stages:
- `ohlcv_resampler_hotfix.py`
- `feature_pipeline.py`
- `live_technical_analysis.py`

V2 strategy:
- Preserve ingestor behavior first.
- `live_coinank.py` remains copy-as-is with hash match required.
- Build wrappers/adapters before enhancement.
- Add `feature_snapshot_id`, source key references, freshness metadata, stale/missing/unused flags, and attribution only after parity baselines exist.

INGESTOR_TO_FEATURE_PIPELINE_MAP_READY
