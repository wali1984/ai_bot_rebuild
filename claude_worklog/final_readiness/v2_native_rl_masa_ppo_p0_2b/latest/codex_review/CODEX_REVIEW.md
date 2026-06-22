# Codex Review: V2 Native RL/MASA/PPO P0.2B Policy Forward

Generated: `2026-05-16T03:58:00Z`

GO/NO-GO: `V2_NATIVE_RL_MASA_PPO_P0_2B_CODEX_PASS`

## Scope Reviewed

This review covers P0.2B only: a CPU-first deterministic policy forward pass over the P0.1 trainer-consumable feature snapshot and P0.2A observation tensor.

It does not approve full trainer migration, checkpoint parity, PPO training, GPU parity, live trading, canary trading, legacy shutdown, or Redis trim.

## Evidence Checked

- P0.1/P0.2A source path consumed: `v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json`
- P0.2B runtime payload path: `v2/frontend/public/operator_runtime/v2_rl_core/latest/v2_rl_core_status.json`
- Runtime payload includes `p0_2b_policy_forward`.
- Policy output includes `policy_id`, `action_logits`, `action_probabilities`, `action_labels`, `selected_action`, and `expected_move_bps_head`.
- Observation snapshot id consumed by the policy: `v2_fsnap_98299c9f90d79b4b3d263eb86a2845cb24abe4739c56ed33764cf066d18f5ed6`
- Model source classification: `V2_NATIVE_CPU_DETERMINISTIC_INIT_NO_CHECKPOINT`
- Migration classification: `PARTIALLY_MIGRATED_P0_2B`
- Hedge action remains fail-closed: `FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE`

## Code Review Findings

- `v2/backend/app/services/rl_core/policy.py` implements a deterministic stdlib CPU forward pass from 26 observation values to 5 action logits/probabilities and an expected-move scalar head.
- `v2/backend/app/services/rl_core/masa_adapter.py` exposes a MASA-shaped `get_action_and_value` surface without claiming full MASA parity.
- `v2/backend/app/services/rl_core/ppo_policy.py` exposes a PPO-shaped `predict` surface without loading checkpoints or running training.
- `v2/backend/app/cli/v2_rl_core_worker.py --p0-2b-policy-forward` loads the native snapshot, builds the observation tensor, runs the CPU policy, and emits the forward-pass block.

## Legacy Citations

SHA256 citations are present for:

- `rl/agents/masa_agent.py`
- `rl/enhanced_architectures.py`
- `rl/gpu_cnn_policy.py`
- `rl/hybrid_action_space.py`

Behavior gaps are explicitly recorded in `legacy_behavior_mapping.json`.

## Validation Run

- Focused tests: `10 passed`.
- `py_compile` for P0.2B active source: PASS.
- Dry-run forward pass with `--require-paper-only`: PASS.
- AST forbidden-call scan over active P0.2B source: no forbidden Redis, exchange, torch, SB3, gymnasium, or numpy imports/calls.

## Safety State

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`
- old Redis writes: `not found in active P0.2B source`
- exchange mutation: `not found in active P0.2B source`

## Non-Approval Items

- PPO clip loss is still missing.
- GAE advantage estimation is still missing.
- Lagrangian safety state is still missing.
- Checkpoint weight loading is deferred to P0.2C.
- Tiny CPU update loop is deferred to P0.2D.
- GPU parity is deferred to P0.2E.
- Trainer output contract is deferred to P0.2F.

## Decision

`V2_NATIVE_RL_MASA_PPO_P0_2B_CODEX_PASS`

P0.2B is acceptable as a partial native CPU policy-forward milestone. It is not full trainer migration and does not change live or legacy-shutdown blockers.
