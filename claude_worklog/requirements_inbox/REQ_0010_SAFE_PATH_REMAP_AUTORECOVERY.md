# Requirement 0010 — Safe Path Remap Autorecovery

The supervisor/master planner must automatically recover known safe emitted-path layout mismatches before escalating to human_attention_required.

## Objective

Reduce manual intervention when Claude emits valid BEGIN_FILE content under an equivalent but wrong non-live V2 path.

## Safe remap examples

Allowed only when the canonical path is listed in required_output_files:

- `v2/app/domain/...` → `v2/backend/app/domain/...`
- `v2/tests/trainer_liveness/...` → `v2/backend/tests/unit/domain/trainer_liveness/...`
- `v2/tests/symbol_universe/...` → `v2/backend/tests/unit/symbol_universe/...`
- `v2/tests/feature_snapshots/...` → `v2/backend/tests/unit/feature_snapshots/...`

## Required safety rules

- Never remap outside `/home/wali/Desktop/AI BOT REBUILD`.
- Never remap into `/home/wali/Desktop/AI BOT`.
- Never remap Redis/live/exchange/deploy paths.
- Remap only if target canonical path is in `required_output_files`.
- Remap only for L1-L3 non-live tasks.
- Log every remap as `safe_path_remap_materialized`.
- Run compile/tests after remap.
- If validation fails, stop.
- If unknown path appears, stop.

## Codex integration

If a task fails only due a known safe remap, the supervisor should remap, validate, commit, and then continue to Codex review without human intervention.

REQ_SAFE_PATH_REMAP_AUTORECOVERY_READY
