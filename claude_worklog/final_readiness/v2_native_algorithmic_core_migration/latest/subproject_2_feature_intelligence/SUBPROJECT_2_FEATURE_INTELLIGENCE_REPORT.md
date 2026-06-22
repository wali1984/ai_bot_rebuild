# Subproject 2 — Feature Intelligence Report

Generated: 2026-05-15
Live gate: `blocked_human_only`. Live symbols: `[]`.

## Outcome

Subproject 2 delivered a V2-native, paper/shadow-only feature intelligence
service. Eight behavior categories are PORTED; five are honestly classified
MISSING_IN_V2.

## Test result

16/16 tests pass under `v2/backend/tests/integration/cli/test_v2_feature_intelligence_worker.py`.

## Components ported (V2-native)

- Microstructure: bid/ask spread (bps), depth imbalance, micro price.
- Realized volatility (pct) from a window of recent log-returns.
- Toxicity proxy from normalized spread and abs-depth-imbalance.
- Feature freshness flag (FRESH / STALE / MISSING) with configurable max
  age.
- Stateless regime classifier (TRENDING_UP / TRENDING_DOWN / RANGING /
  VOLATILE / UNCERTAIN).
- Explicit missing-input labels.
- `FeatureIntelligenceService.current_paper_only_status()` payload with
  safety invariants.
- CLI worker that emits the public status payload.

## Components missing (under contract)

- Full `unified_feature_builder` (2,000+ derived features).
- Cross-timeframe aggregations.
- Funding/OI derived features.
- Native WebSocket/REST ingestor layer.
- Regime hysteresis state machine.

## Migration completion contract classification

`PARTIALLY_MIGRATED`. NOT `MIGRATED_CODEX_PASS`.

## Safety invariants verified

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live` / `approves_canary` / `approves_legacy_shutdown` /
  `approves_redis_trim`: all `false`
- No old Redis writes.
- No exchange mutation.
- No network IO in tests.

## GO/NO-GO

`SUBPROJECT_2_FEATURE_INTELLIGENCE_PARTIALLY_MIGRATED_PAPER_ONLY`
