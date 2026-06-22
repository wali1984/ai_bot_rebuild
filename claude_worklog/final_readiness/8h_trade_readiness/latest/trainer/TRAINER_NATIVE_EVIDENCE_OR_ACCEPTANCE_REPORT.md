# 8h Trainer Native Evidence Or Acceptance Report

Generated: `2026-05-15T21:31:00Z`

Status: `TRAINER_DERIVED_EVIDENCE_PAPER_ONLY_ACCEPTANCE_REQUIRED`

## Result

Claude child `1656876` produced no stdout, stderr, or required artifacts for nearly five minutes. Codex terminated only that V2 Claude child and consolidated the current trainer evidence from the V2 trainer bridge plus the existing trainer-derived evidence acceptance matrix.

Current trainer bridge evidence:

- prediction id: `legacy_redis_pred_d04be1dd5d0009f3fcab`
- feature snapshot id: `legacy_redis_feature_BTCUSDT_4h_1778880660`
- feature snapshot link mode: `DERIVED_FROM_LEGACY_LOG`
- confidence raw: `0.09812330454587936`
- confidence calibrated: `0.09812330454587936`
- confidence calibration mode: `DERIVED_FROM_LEGACY_LOG`
- expected move bps: `0.73592478`
- expected move after cost bps: `null`
- checkpoint id: `legacy_live_checkpoint_1778880589`
- checkpoint evidence: `PRESENT`
- model version: `legacy_hybrid_trainer_live_legacy`

## Classification

Native evidence remains incomplete:

- `feature_snapshot_id`: `DERIVED_FROM_LEGACY_LOG`
- `confidence_calibrated`: `DERIVED_FROM_LEGACY_LOG`
- `expected_move_bps`: `NATIVE_FIELD_PRESENT`
- `expected_move_after_cost_bps`: `MISSING_EVIDENCE`
- `top_positive_features`: `INCOMPLETE_ATTRIBUTION`
- `top_negative_features`: `INCOMPLETE_ATTRIBUTION`
- `missing/stale/unused flags`: `NATIVE_FIELD_PRESENT`
- `checkpoint_id`: `NATIVE_FIELD_PRESENT`

## Decision

Do not call this full trainer parity. Do not relabel derived evidence as native.

The paper-only acceptance packet remains required before trainer-derived evidence can be treated as acceptable for any paper-only shutdown evaluation. This does not support live/canary readiness.

Evidence paths:

- `v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/v2_trainer_bridge_status.json`
- `claude_worklog/final_readiness/trainer_derived_evidence_acceptance/latest/trainer_field_evidence_matrix.json`
- `claude_worklog/final_readiness/trainer_derived_evidence_acceptance/latest/TRAINER_DERIVED_EVIDENCE_PAPER_ONLY_ACCEPTANCE_PACKET.md`
