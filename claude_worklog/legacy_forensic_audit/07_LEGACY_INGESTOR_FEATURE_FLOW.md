# 07 Legacy Ingestor Feature Flow

## Summary
Ingestor/feature pipeline mapping includes:
- Binance, KuCoin, CoinAPI, CoinAnk, liquidation streams.
- TA and realtime price providers.
- OHLCV resampler and feature pipeline outputs.
- Freshness/heartbeat patterns via Redis keys.

## Evidence samples
- Ingestor scripts (sample): ingest/alphavantage_client.py, ingest/alphavantage_normalizer.py, ingest/base_ingestor.py, ingest/ccxt_backfill.py, ingest/ccxt_historical.py, ingest/cdd_enhanced_slow.py, ingest/cdd_historical.py, ingest/cdd_to_jsonl.py, ingest/liquidation_bridge.py, ingest/liquidation_levels_engine.py, ingest/live_alphavantage_news.py, ingest/live_binance.py, ingest/live_binance_liquidations.py, ingest/live_ccxt.py, ingest/live_coinank.py
- Feature-related scripts (sample): analyze_comprehensive_features.py, analyze_feature_pipeline_bottleneck.py, comprehensive_feature_extractor.py, comprehensive_feature_service_fixed.py, debug_feature_pipeline_ohlcv.py, feature_pipeline.py, feature_pipeline_diagnostic.py, fix_feature_pipeline_performance.py, ingest/live_technical_analysis.py, ingest/technical_analysis.py
- Redis heartbeat/key references in ingestion routes: captured in REDIS_USAGE_MAP.

## Raw evidence pointers
- claude_worklog/coverage/TIER_A_RAW_REVIEW_PLAN.json
- claude_worklog/coverage/EXCHANGE_ACTION_MAP.json
- claude_worklog/coverage/REDIS_USAGE_MAP.json
- claude_worklog/trainer_atlas/HYBRID_TRAINER_COVERAGE_REPORT.md

## Source artifacts used
- claude_worklog/coverage/FILE_MANIFEST.json
- claude_worklog/coverage/SCRIPT_REGISTRY.json
- claude_worklog/coverage/SCRIPT_DEPENDENCY_GRAPH.json
- claude_worklog/coverage/STARTUP_PATH_MAP.json
- claude_worklog/coverage/RUNTIME_PROCESS_MAP.json
- claude_worklog/coverage/REDIS_USAGE_MAP.json
- claude_worklog/coverage/EXCHANGE_ACTION_MAP.json
- claude_worklog/coverage/CONFIG_ENV_MAP.json

## Verification commands
- python3 tools/show_file_range.py --file "./legacy_reference/rl/hybrid_trainer.py" --start 1 --end 80
- python3 tools/show_trainer_section.py --trainer-file ./legacy_reference/rl/hybrid_trainer.py --start 30000 --end 30120
- python3 tools/codex_adversarial_coverage_check.py

## Unresolved questions
- Which Tier A unresolved items need code-owner adjudication before production deprecation mapping?
- Which legacy scripts are wrappers only and can be archived in V2 migration phase?

## Confidence level
- Medium
