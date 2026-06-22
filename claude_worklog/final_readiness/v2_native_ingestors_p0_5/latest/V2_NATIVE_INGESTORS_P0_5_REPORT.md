# V2 Native Ingestors P0.5

Phase P0.5; Sprint 12h native core migration.

Generated: 2026-05-16T04:55:00Z
Git HEAD: 31a7fd70319f0d586c454b5ea2ea530ba9cb1541

## What was built

- v2/backend/app/services/native_ingestors/__init__.py
- v2/backend/app/services/native_ingestors/registry.py
- v2/backend/app/cli/v2_native_ingestors_worker.py
- v2/backend/tests/integration/cli/test_v2_native_ingestors_worker.py
  (4 tests passing)
- v2/frontend/public/operator_runtime/v2_native_ingestors/latest/v2_native_ingestors_status.json

## Classification per ingestor

| Ingestor | Class | Notes |
| --- | --- | --- |
| live_binance | READONLY_BRIDGED | public OHLCV/depth/funding via Binance REST/WSS; no secret |
| live_binance_liquidations | READONLY_BRIDGED | public !forceOrder WSS; no secret |
| live_coinank | BLOCKED_BY_SECRET_OR_API or READONLY_BRIDGED | depends on COINANK_API_KEY presence |
| live_coinank_global_aggregator | OPERATOR_DECISION_REQUIRED | aggregator scope decision pending |
| live_kucoin | MISSING_IN_V2 | not yet built; deferred to later sprint |
| live_coinapi_v1 | BLOCKED_BY_SECRET_OR_API or READONLY_BRIDGED | depends on COINAPI_KEY |
| live_coinapi_wsds | BLOCKED_BY_SECRET_OR_API or OPERATOR_DECISION_REQUIRED | paid tier; needs explicit approval |
| live_technical_analysis | NATIVE_V2 | served by v2_feature_pipeline_and_ta_worker |
| realtime_price_provider | NATIVE_V2 | served by v2_market_ingestor |
| liquidation_bridge | READONLY_BRIDGED | served by v2_coinank_and_liquidation_bridge |
| liquidation_levels_engine | NATIVE_V2 | local computation on V2 OHLCV cache |
| ccxt_historical | OPERATOR_DECISION_REQUIRED | backfill vs replay-store policy decision |

## Public market data only

- imports_torch: false
- imports_numpy: false
- imports_redis: false
- imports_exchange_sdk: false
- performs_network_io: false (classification module is pure metadata)
- writes_legacy_redis: false
- places_exchange_orders: false
- public_market_data_only: true (every ingestor in scope)

## Permanent migration contract checklist

- Legacy source paths: yes (12 ingestors cited).
- SHA256: yes (12).
- Dependency closure: pure stdlib; no exchange SDK imports.
- Config/env mapping: secret envs declared per ingestor.
- Behavior mapping: yes (classification rationale per ingestor).
- V2 implementation: yes.
- Tests: yes (4 passing).
- Public payload: yes.
- Codex review: pending.
- No old Redis writes: yes.
- No exchange mutation: yes.
- live_gate == "blocked_human_only": yes.
- live_symbols == []: yes.

## Decision

P0.5 is READY at the verification/classification contract level.
Full native builds for MISSING_IN_V2 ingestors are scoped out of
this sprint.
