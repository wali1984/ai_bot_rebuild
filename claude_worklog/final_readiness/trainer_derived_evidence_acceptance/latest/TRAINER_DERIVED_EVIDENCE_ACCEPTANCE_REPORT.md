# Trainer Derived Evidence Acceptance Report

Generated: 2026-05-15T11:00:37Z

Result: V2_TRAINER_DERIVED_EVIDENCE_PAPER_ONLY_ACCEPTANCE_REQUIRED

This refresh uses the current trainer bridge payload generated at `2026-05-15T11:00:24Z`. It does not relabel derived evidence as native.

Current native evidence found:
- `confidence_raw`: `0.9349589347839355` from the read-only legacy prediction bridge.
- `expected_move_bps`: `7.01219201` with mode `NATIVE_FIELD_PRESENT` and source `native_legacy_trainer_price_target`.
- missing/stale/unused feature flag lists are present from V2 feature payloads.

Remaining derived/incomplete evidence:
- `feature_snapshot_id`: `legacy_redis_feature_BTCUSDT_1h_1778842806` remains `DERIVED_FROM_LEGACY_LOG`.
- `confidence_calibrated`: `0.9349589347839355` remains `DERIVED_FROM_LEGACY_LOG` because no separate native calibrated runtime field is present.
- `top_positive_features`: incomplete attribution.
- `top_negative_features`: incomplete attribution.

Shutdown impact:
- Native trainer parity evidence is not ready.
- Derived evidence can be considered only for V2 paper-only shutdown if the operator explicitly accepts the limitation.
- Derived evidence is not acceptable as live or canary readiness.
- This packet does not approve shutdown.
- This packet does not enable live.

Safety:
- `live_gate` remains `blocked_human_only`.
- `live_symbols` remains `[]`.
- Final approval token remains absent.
- Redis trim approval remains absent.
- No old Redis write evidence was introduced.
- No exchange mutation evidence was introduced.
