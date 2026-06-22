# V2 Native Feature Pipeline (P0.1) — GO/NO_GO

Generated: 2026-05-16

## GO_NO_GO

V2_NATIVE_FEATURE_PIPELINE_P0_READY

## Why READY

The V2-native feature pipeline computes feature snapshots from raw
inputs and meets every acceptance criterion:

- Computational (not bridge-only). The service does NOT read legacy
  features:* Redis keys as authoritative and does NOT import any Redis
  client. Verified by the dependency-closure file and by a dedicated
  test that scans the service source for forbidden imports.
- Every required category is implemented natively: ohlcv_derived,
  ta_indicators, multi_timeframe, microstructure,
  funding_oi_liquidation, portfolio_aware, freshness.
- feature_snapshot_id is emitted per snapshot
  (v2_fsnap_<sha256> chain-of-custody integrity over the sorted payload).
- Stale and missing flags are emitted explicitly. Absent inputs are
  reported as named missing_feature_flags rather than zero-filled.
- SHA256 citations for all ten consulted legacy sources are recorded in
  the service module docstring, in legacy_behavior_mapping.json, and in
  the emitted snapshot payload.
- Runtime gate blocked_human_only. Runtime symbols empty. No approval
  tokens. No legacy Redis writes. No exchange mutation paths.

## Tests

11 / 11 pass under
v2/backend/tests/integration/cli/test_v2_feature_pipeline_native.py:

- snapshot id format and determinism
- full-input snapshot emits all categories
- missing inputs produce explicit missing flags (not fabricated zeros)
- stale inputs produce stale flags
- short OHLCV window does not compute long TA
- orderbook present emits microstructure features
- MACD components present for long windows
- service status payload holds safety invariants and categories
- service compute returns full schema including mapping
- service source has no forbidden imports (redis, ccxt, binance)

## Codex blocking checks (all PASS)

- implementation is not bridge-only: PASS
- legacy Redis features are not treated as native computation: PASS
- SHA256 citations present in service docstring and mapping JSON: PASS
- feature categories not silently dropped: PASS (explicit categories_present)
- stale/missing flags not hidden: PASS (explicit flag lists)
- feature_snapshot_id present: PASS
- old Redis writes appear: NONE
- exchange mutation appears: NONE
- runtime gate changes: NONE

## Migration completion contract classification

Subproject is PARTIALLY_MIGRATED. The contract requires native ports of
the full unified_feature_builder.py (2000+ feature dimensions), regime
state machine, and the native WebSocket/REST ingestor layer before
MIGRATED_CODEX_PASS can be claimed.

## Live, canary, legacy shutdown, Redis trim

- live_gate: blocked_human_only
- live_symbols: []
- approves_live: false
- approves_canary: false
- approves_legacy_shutdown: false
- approves_redis_trim: false
- final_approval_token: absent
- redis_trim_approval_token: absent

## What this READY does NOT do

- Does not authorize live trading, canary, legacy shutdown, or Redis trim.
- Does not claim full 2000+ feature parity with legacy.
- Does not replace the legacy feature_pipeline.py daemon at the legacy
  bot path (legacy continues to run; this V2 service is paper/shadow
  only).
- Does not start any WebSocket / REST ingestor. The native ingestor
  layer is a separate P0.

## Next P0 steps (per master roadmap)

1. Native V2 RL / MASA / PPO / reward stack
2. Native V2 orchestrator arbitration
3. Native V2 stop / TP / stealth / hedge paper engine
4. Native V2 ingestor verification / build

Runtime gate remains blocked_human_only.
