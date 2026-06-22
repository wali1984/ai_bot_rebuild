# Codex Review Request — V2 Native Feature Pipeline (P0.1)

Status: PENDING_CODEX_REVIEW
Generated: 2026-05-16
Runtime gate: blocked_human_only. Runtime symbols: [].

## Scope

Adversarial review of the V2 native feature pipeline subproject.

Verify:

1. Service module computes features natively (does NOT read legacy
   features:* Redis keys as authoritative).
2. SHA256 citations for all ten consulted legacy sources are present in
   the service docstring and in legacy_behavior_mapping.json, matching
   the actual file hashes under v2/legacy_owned_runtime.
3. Feature snapshot id (v2_fsnap_<sha256>) is emitted per snapshot.
4. Every feature category (ohlcv_derived, ta_indicators,
   multi_timeframe, microstructure, funding_oi_liquidation,
   portfolio_aware, freshness) is implemented natively and not silently
   dropped.
5. Missing inputs produce explicit named missing_feature_flags rather
   than zero-fill.
6. Stale inputs produce explicit named stale_feature_flags.
7. The service module imports no redis / ccxt / binance / torch /
   stable_baselines3.
8. The CLI emits a public status payload at
   v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/
   v2_feature_pipeline_native_status.json.
9. No approval token (live, canary, legacy shutdown, Redis trim) appears.
10. Runtime gate stays blocked_human_only; runtime symbols stay empty.

## Codex blocking conditions

Block if any of:

- Implementation is bridge-only.
- Legacy features:* Redis keys are treated as authoritative.
- SHA256 citations missing or do not match v2/legacy_owned_runtime files.
- Feature categories silently dropped.
- Stale or missing flags hidden.
- feature_snapshot_id absent.
- Old Redis writes appear.
- Exchange mutation appears.
- Runtime gate changes.

## Expected outcome

CODEX_REVIEW.md placed in this directory with top-line:

GO_NO_GO_CODEX_REVIEW_V2_NATIVE_FEATURE_PIPELINE_P0_PASS_OR_FAIL

This review does not authorize live trading, canary, legacy shutdown,
or Redis trim.
