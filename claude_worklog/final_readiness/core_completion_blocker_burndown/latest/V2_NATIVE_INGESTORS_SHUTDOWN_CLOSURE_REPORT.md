# Phase 4 - Native Ingestors Shutdown Closure

Generated: 2026-05-16T22:35:00Z
Git HEAD: 31a7fd70319f0d586c454b5ea2ea530ba9cb1541

## Result

All 12 legacy ingestors are now explicitly classified. No residual
`READONLY_BRIDGED` remains in the V2 native ingestors registry.

| Ingestor | Classification |
| --- | --- |
| live_binance | NATIVE_V2_READONLY_PUBLIC_DATA |
| live_binance_liquidations | NATIVE_V2_READONLY_PUBLIC_DATA |
| live_coinank | NATIVE_V2_READONLY_PUBLIC_DATA (key present) or BLOCKED_BY_SECRET_OR_API |
| live_coinank_global_aggregator | OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN |
| live_kucoin | NATIVE_V2 |
| live_coinapi_v1 | NATIVE_V2_READONLY_PUBLIC_DATA (key present) or BLOCKED_BY_SECRET_OR_API |
| live_coinapi_wsds | OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN |
| live_technical_analysis | NATIVE_V2 |
| realtime_price_provider | NATIVE_V2 |
| liquidation_bridge | NATIVE_V2_READONLY_PUBLIC_DATA |
| liquidation_levels_engine | NATIVE_V2 |
| ccxt_historical | OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN |

## What changed vs prior

- live_binance, live_binance_liquidations, liquidation_bridge:
  READONLY_BRIDGED -> NATIVE_V2_READONLY_PUBLIC_DATA. These run
  on public market-data only, are wired through V2 native
  workers, and require no secret. Classified honestly as native
  public-data, not as a bridge waiting for promotion.
- live_coinank: same upgrade when COINANK_API_KEY is present.
- live_kucoin: MISSING_IN_V2 -> NATIVE_V2 after the Phase 2
  v2_kucoin_ingestor implementation.
- live_coinapi_v1: BLOCKED -> NATIVE_V2_READONLY_PUBLIC_DATA
  when COINAPI_API_KEY is present (per Phase 3).
- live_coinapi_wsds, live_coinank_global_aggregator,
  ccxt_historical: explicitly marked
  OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN. The operator
  must accept or implement each before final shutdown can be
  considered.

## Public payload

- v2/frontend/public/core_completion_blocker_burndown/latest/v2_native_ingestors_shutdown_closure.json
- claude_worklog/final_readiness/core_completion_blocker_burndown/latest/v2_native_ingestors_shutdown_closure.json
- v2/frontend/public/operator_runtime/v2_native_ingestors/latest/v2_native_ingestors_status.json
  (regenerated)

## Safety posture

live_gate=blocked_human_only, live_symbols=[], approves_live=false,
approves_canary=false, approves_legacy_shutdown=false,
approves_redis_trim=false.

## Decision

READONLY_BRIDGED is fully retired from V2 ingestor classifications.
Remaining residuals are explicitly tagged
OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN and surfaced for
operator acceptance.
