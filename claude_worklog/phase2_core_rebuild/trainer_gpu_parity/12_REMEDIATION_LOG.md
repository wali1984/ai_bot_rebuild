# Phase 2E Trainer GPU Parity Plan — Remediation Log

This log records the remediations applied in response to the Codex FAIL
verdict in `10_CODEX_REVIEW.md` / `11_CODEX_GO_NO_GO.md`. The original
review files are preserved unchanged for the audit trail.

## Codex findings remediated

### Finding 1 (Blocker): non-canonical semantic markers in 02–07

Required form: `PHASE2_TRAINER_GPU_PARITY_*_READY`.

| File | New marker |
| --- | --- |
| `02_GPU_AND_BATCHING_PARITY_REQUIREMENTS.md` | `PHASE2_TRAINER_GPU_PARITY_GPU_BATCHING_READY` |
| `03_CHECKPOINT_AND_MODEL_LOADING_PARITY.md` | `PHASE2_TRAINER_GPU_PARITY_CHECKPOINT_READY` |
| `04_REWARD_AND_CONFIDENCE_PARITY_MAP.md` | `PHASE2_TRAINER_GPU_PARITY_REWARD_CONFIDENCE_READY` |
| `05_PREDICTION_WORKER_LIVENESS_FIX_SPEC.md` | `PHASE2_TRAINER_GPU_PARITY_PREDICTION_WORKER_LIVENESS_READY` |
| `06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md` | `PHASE2_TRAINER_GPU_PARITY_OUTPUT_CONTRACT_READY` |
| `07_PROCESS_BOUNDARY_AND_SUBPROCESS_ADAPTER_SPEC.md` | `PHASE2_TRAINER_GPU_PARITY_PROCESS_BOUNDARY_READY` |

`00_SCOPE.md`, `01_LEGACY_HYBRID_TRAINER_BEHAVIOR_INVENTORY.md`,
`08_NON_LIVE_VALIDATION_PLAN.md`, and `09_GO_NO_GO.md` already carried
canonical markers and were not changed for this finding.

### Finding 2 (Blocker): prohibited literal operation phrases

Codex enforces a literal-text check that bans nine literal phrase classes
even when used inside a "do not" clause. Those phrase classes are
enumerated by supervisor task
`claude_worklog/agent_supervisor/tasks/051_trainer_gpu_parity_plan_codex_rerun.json`
and apply to plan documents `00`–`09`, `12`, `13`. Each occurrence inside
`00_SCOPE.md`, `07_PROCESS_BOUNDARY_AND_SUBPROCESS_ADAPTER_SPEC.md`, and
`08_NON_LIVE_VALIDATION_PLAN.md` was abstracted to one of the following
classification references:

- exchange-side write classified `exchange-write` per the legacy service
  map at `claude_worklog/phase2_core_rebuild/legacy_service_map/`.
- leverage/margin-config-write classified per the legacy service map at
  `claude_worklog/phase2_core_rebuild/legacy_service_map/`.
- switch from non-live to live operating mode (the CLAUDE.md default is
  `LIVE TRADING: BLOCKED`).
- Redis-mutating side effect classified `unsafe_write` per
  `claude_worklog/trainer_atlas/HYBRID_TRAINER_REDIS_WRITE_CLASSIFICATION.md`.
- Redis administration command-line tool classified per the trainer atlas
  Redis write classification.

The example "do not invoke" enumeration in `07` was abstracted to point
at the legacy service map and the Redis write classification rather than
naming each literal call.

### Finding 3 (Major): incomplete legacy-preservation explainability field set in 04

`claude_worklog/legacy_preservation/03_TRAINER_TRADER_PARITY_REQUIREMENTS.md`
requires the V2 trainer to emit:

- confidence_explainability
- top positive/negative feature contributors
- source key/pattern references
- freshness metadata
- stale/missing/unused flags

The previous `04_REWARD_AND_CONFIDENCE_PARITY_MAP.md` only named the
first two field groups. The remediated `04` now binds the **full** set:
`confidence_explainability`, `top_positive_features[]`,
`top_negative_features[]`, `source_key_references[]`,
`freshness_metadata`, `feature_status_flags` (with `stale[]`,
`missing[]`, `unused[]`). The output contract in
`06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md` was extended to enumerate
the same fields and to mark omission as a hard observability validation
failure.

## Files unchanged for this remediation

- `01_LEGACY_HYBRID_TRAINER_BEHAVIOR_INVENTORY.md` (already passes; cited
  trainer atlas with canonical sha256 and line/byte counts).
- `09_GO_NO_GO.md` (already contains exactly
  `PHASE2_TRAINER_GPU_PARITY_PLAN_READY_FOR_CODEX_REVIEW`).
- `10_CODEX_REVIEW.md` (preserved as audit record of the FAIL verdict).
- `11_CODEX_GO_NO_GO.md` (preserved as audit record of the FAIL verdict).

## Safety boundaries respected

- No `legacy_reference/**` modification.
- No `/home/wali/Desktop/AI BOT` access.
- No Redis-state modification.
- No live-service restart.
- No exchange-side write action.
- No leverage/margin-config-write action.
- No switch from non-live to live operating mode.
- No deployment, no production migration.
- No secret value emitted.

PHASE2_TRAINER_GPU_PARITY_PLAN_REMEDIATION_LOG_READY
