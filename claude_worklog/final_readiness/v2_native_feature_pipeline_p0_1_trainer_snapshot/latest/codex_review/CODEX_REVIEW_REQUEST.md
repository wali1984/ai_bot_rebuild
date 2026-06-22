# Codex Review Request — V2 Native Feature Pipeline P0.1 Trainer-Consumable Snapshot

Task id: codex_review_v2_native_feature_pipeline_p0_1_trainer_consumable_snapshot
Status: PENDING_CODEX_REVIEW
Generated: 2026-05-16
Runtime gate: blocked_human_only. Runtime symbols: [].

## Scope

Adversarial review of the P0.1 trainer-consumable snapshot output contract.

Verify:

1. latest_feature_snapshot.json exists at both:
   v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json
   v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json
2. Both files share the same payload (schema v2_native_feature_snapshot_v1).
3. trainer_consumable=true in the emitted snapshot.
4. features dict is non-empty (>=10 entries in the default-input emission).
5. feature_snapshot_id format is v2_fsnap_<64-hex-sha256>.
6. missing_feature_flags and stale_feature_flags are explicit arrays.
7. feature_freshness_state is one of CURRENT / STALE / MISSING.
8. The service module does not import any redis / ccxt / binance / torch
   / stable_baselines3 client.
9. No old Redis writes attempted.
10. No exchange mutation reachable.
11. live_gate=blocked_human_only, live_symbols=[],
    approves_live/canary/legacy_shutdown all false.
12. CLI flag --emit-latest-snapshot works as specified.

## Codex blocking conditions

Block if any of:

- latest_feature_snapshot.json missing at either path.
- payload is status-only and not trainer-consumable.
- features dict empty.
- feature_snapshot_id missing.
- missing/stale flags hidden.
- trainer_consumable not true.
- Redis client imported.
- Old Redis write appears.
- Exchange mutation appears.
- live_gate changes.
- live_symbols not [].

## Expected outcome

CODEX_REVIEW.md placed in this directory with top-line:

GO_NO_GO_CODEX_REVIEW_V2_NATIVE_FEATURE_PIPELINE_P0_1_TRAINER_CONSUMABLE_SNAPSHOT_PASS_OR_FAIL

This review does not authorize live, canary, legacy shutdown, or Redis
trim.
