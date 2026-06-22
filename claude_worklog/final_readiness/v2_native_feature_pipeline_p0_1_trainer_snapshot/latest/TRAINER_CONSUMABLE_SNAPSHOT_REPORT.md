# V2 Native Feature Pipeline P0.1 — Trainer-Consumable Snapshot Report

Generated: 2026-05-16
Runtime gate: blocked_human_only. Runtime symbols: [].

## Outcome

P0.2 was blocked because no trainer-consumable native
latest_feature_snapshot.json existed at accepted paths. This sprint
closes that contract: the V2-native feature pipeline now emits a
schema-versioned trainer-consumable snapshot to both the public
operator-runtime path and the runtime path on each
--emit-latest-snapshot invocation.

## Files

Source:
- v2/backend/app/services/feature_pipeline_native/service.py (extended)
- v2/backend/app/cli/v2_feature_pipeline_native.py (extended)

Tests:
- v2/backend/tests/integration/cli/test_v2_feature_pipeline_native_trainer_snapshot.py (8/8 pass)

Public snapshot:
- v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json

Runtime snapshot (mirror):
- v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json

## Snapshot payload contract

Schema: v2_native_feature_snapshot_v1.

Fields:
- worker_id (v2_feature_pipeline_native)
- feature_snapshot_id (v2_fsnap_<sha256> chain-of-custody id)
- generated_at
- symbol, timeframe
- features (dict of named numeric features)
- feature_count
- categories_present (ordered tuple of category labels)
- missing_feature_flags (explicit list)
- stale_feature_flags (explicit list)
- source_inputs (bar/snapshot counts per source)
- source_freshness_seconds (age per source)
- feature_freshness_state (CURRENT | STALE | MISSING)
- trainer_consumable (always true on this code path)
- legacy_behavior_mapping (SHA256 citations for 10 legacy sources)
- runtime gate blocked_human_only, runtime symbols empty, approval flags false

## CLI invocation

```
python3 -m v2.backend.app.cli.v2_feature_pipeline_native \
    --emit-latest-snapshot --symbol BTCUSDT --timeframe 1m
```

When `--emit-latest-snapshot` is set, the CLI emits both the status
payload (to the existing v2_feature_pipeline_native_status.json path)
and the trainer-consumable snapshot (to the two latest_feature_snapshot.json
paths).

## Live emission (canonical paths)

Recorded fields from the live default-input emission:

- schema: v2_native_feature_snapshot_v1
- worker: v2_feature_pipeline_native
- feature_snapshot_id: v2_fsnap_98299c9f90d79b4b3d263eb86a2845cb24abe4739c56ed33764cf066d18f5ed6
- trainer_consumable: true
- feature_count: 23
- categories_present_count: 7
- missing_flags_count: 0
- stale_flags_count: 0
- feature_freshness_state: CURRENT
- runtime gate: blocked_human_only
- runtime symbols: []

## Test result

8/8 tests pass under test_v2_feature_pipeline_native_trainer_snapshot.py:

- emit_trainer_consumable_snapshot_has_required_keys
- emit_trainer_consumable_snapshot_features_non_empty_categories_non_empty
- feature_snapshot_id_deterministic_for_same_inputs
- missing_and_stale_flags_are_explicit_arrays
- no_redis_or_exchange_imports_in_service_module
- cli_emit_latest_snapshot_creates_both_files
- cli_emit_latest_snapshot_also_writes_status
- cli_emit_latest_snapshot_default_inputs_yield_categories_and_freshness_current

Aggregated regression: 19/19 across the original P0.1 suite
(11 tests) plus this sprint (8 tests).

## Codex blocking checks (all PASS)

- latest_feature_snapshot.json present at both public and runtime paths: PASS
- payload is trainer-consumable (trainer_consumable=true), not status-only: PASS
- features dict non-empty (23 features in default-input mode): PASS
- feature_snapshot_id present (v2_fsnap_<sha256>): PASS
- missing/stale flags emitted as explicit arrays: PASS
- no redis client imported: PASS (verified by source-scan test)
- no old Redis writes: PASS
- no exchange mutation: PASS
- runtime gate unchanged (blocked_human_only): PASS
- runtime symbols unchanged ([]): PASS

## Migration completion contract classification

PARTIALLY_MIGRATED. Not MIGRATED_CODEX_PASS.
