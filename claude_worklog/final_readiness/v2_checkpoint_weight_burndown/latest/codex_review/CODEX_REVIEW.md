# Codex Review: V2 Checkpoint Weight Blob Burndown During Soak

Generated: `2026-05-17T02:31:56Z`

GO/NO-GO: `V2_CHECKPOINT_WEIGHT_BURNDOWN_CODEX_PASS_OPERATOR_REQUIRED`

## Decision

Codex passes this checkpoint-weight burndown at the operator-required scope. No compatible checkpoint weights were loaded into V2, no shape-compatible weight parity was proven, and no checkpoint parity is claimed. The current correct state remains `CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED`.

This review does not approve live trading, canary trading, exchange mutation, leverage/margin changes, legacy shutdown, Redis trim, or checkpoint promotion.

## Runtime Soak Continuity

- V2 runtime soak continued during the checkpoint review.
- Required V2 runtime processes running: `10/10`.
- No V2 loop was stopped.
- Legacy production/reference processes are still running; Codex did not stop legacy.
- Current soak status: `minutes_observed=27.23`, `soak_15m_ready=true`, `soak_1h_ready=false`, `soak_6h_ready=false`.
- V2 namespaces remain non-empty across `v2:market:*`, `v2:features:*`, `v2:prediction:*`, `v2:trainer:*`, `v2:orchestrator:*`, `v2:paper:*`, and `v2:risk:*`.

The soak governor was refreshed after a stale replacement-readiness scoreboard was found. It is now back to `CODEX_RUNTIME_SOAK_AND_PRODUCTION_EQUIVALENCE_GOVERNOR_READY`.

## Checkpoint Evidence

Reviewed:

- `claude_worklog/final_readiness/v2_native_rl_masa_ppo_p0_2c/latest/checkpoint_inventory.json`
- `claude_worklog/final_readiness/v2_native_rl_masa_ppo_p0_2c/latest/checkpoint_loading_status.json`
- `claude_worklog/final_readiness/core_completion_blocker_burndown/latest/checkpoint_weight_resolution.json`
- `v2/frontend/public/core_completion_blocker_burndown/latest/checkpoint_weight_resolution.json`
- `v2/frontend/public/operator_runtime/v2_rl_core/live/latest/v2_rl_core_live_status.json`

Findings:

- P0.2C inventory found checkpoint candidates, but the V2 control plane did not deserialize or load weights.
- `weight_loading_status=CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED`.
- `model_shape_status=MODEL_SHAPE_VERIFICATION_BLOCKED_NO_TORCH_LOAD_IN_V2`.
- Burndown candidate count for approved V2 checkpoint promotion remains `0`.
- Operator request is exact: provide an operator-approved checkpoint blob with sidecar metadata and authorize a shape-inspection path, or explicitly accept the checkpoint-weight limitation for paper-only shutdown.
- No checkpoint parity claim was found without compatible weights.

## Paper Gate

The strict P0.2F paper-fill gate remains tested and active. Focused regression tests covering checkpoint metadata and paper-fill gate behavior passed: `26 passed`.

Current live V2 prediction records may open the paper-only gate only when their own expected move after cost is positive and above threshold. That is not checkpoint parity: `checkpoint_id` remains absent and `checkpoint_weight_status` remains operator-required. Live trading remains blocked.

## Artifact Safety

- Raw checkpoint/model blob tracked files: none found for `.pt`, `.pth`, `.ckpt`, `.onnx`, `.pkl`, `.pickle`, `.joblib`, `.safetensors`, `.bin`, or `.zip`.
- Raw checkpoint/model blob staged or modified files: none found.
- High-confidence raw secret hits in reviewed worklog/public/runtime artifacts: `0`.
- Approval-token/live/canary/shutdown/Redis-trim scan: PASS.
- Active checkpoint/RL code exchange-mutation scan: PASS.
- Active checkpoint/RL code Redis write review: only guarded `v2:` namespace writes were found in the live inference loop; no old Redis write path was found.
- `git diff --check`: PASS.

## Safety State

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`

## Remaining Blocker

`CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED` remains unresolved. This is acceptable for this review only because the packet is honestly operator-required and does not claim compatible paper-only checkpoint loading.

## Final Decision

`V2_CHECKPOINT_WEIGHT_BURNDOWN_CODEX_PASS_OPERATOR_REQUIRED`
