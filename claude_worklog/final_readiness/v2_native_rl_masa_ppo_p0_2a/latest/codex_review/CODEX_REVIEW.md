# Codex Review: V2 Native RL/MASA/PPO P0.2A Env/Obs/Reward

Generated: `2026-05-16T03:08:00Z`

GO/NO-GO: `V2_NATIVE_RL_MASA_PPO_P0_2A_CODEX_PASS`

## Scope Reviewed

This review covers P0.2A only: paper-only environment reset/step, observation tensor construction from the P0.1 trainer-consumable native feature snapshot, and reward-suite plumbing.

It does not approve full MASA/PPO parity, checkpoint parity, live trading, canary trading, legacy shutdown, or Redis trim.

## Evidence Checked

- P0.1 trainer-consumable snapshot consumed from `v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json`.
- Snapshot id matches the RL core rollout metadata: `v2_fsnap_98299c9f90d79b4b3d263eb86a2845cb24abe4739c56ed33764cf066d18f5ed6`.
- Snapshot is `trainer_consumable=true`, `feature_count=23`, and `feature_freshness_state=CURRENT`.
- RL rollout status path: `v2/frontend/public/operator_runtime/v2_rl_core/latest/v2_rl_core_status.json`.
- P0.2A rollout emitted `observation_tensor_shape=[26]`, `rollout_steps_run=7`, and `migration_classification=PARTIALLY_MIGRATED_P0_2A`.
- Missing/stale feature flags are preserved in observation metadata as explicit arrays.

## Code Review Findings

- `v2/backend/app/services/rl_core/environment.py` implements `PaperOnlyEnv.reset()`, `step()`, and `close()` with deterministic paper-only price dynamics.
- `v2/backend/app/services/rl_core/observation_builder.py` builds a fixed-order 26-value tuple from the P0.1 native snapshot. This is not schema-only.
- `v2/backend/app/services/rl_core/rewards.py` implements base PnL, fee-aware shaping, constrained safety penalty, and an inert hedge reward classified `FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE`.
- `v2/backend/app/cli/v2_rl_core_worker.py --p0-2a-rollout` reads the P0.1 latest snapshot, builds the observation tensor, runs the paper env, and attaches reward results to the payload.

## Legacy Citations

Legacy SHA256 citations are present for environment, Gymnasium wrapper, observation schema, unified feature builder, reward functions, constrained reward, fee-ratio reward shaping, and hedge reward functions.

## Validation Run

- `py_compile` for P0.2A active source: PASS.
- Focused tests: `51 passed`.
- JSON validation for P0.2A evidence and runtime payloads: PASS.
- Dry-run rollout with `--require-paper-only`: PASS.
- AST forbidden-call scan over active P0.2A source: no Redis write calls and no exchange mutation calls found.

## Safety State

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`

## Non-Approval Items

- Full MASA/PPO policy network is still missing.
- Full Gymnasium wrapper parity is still missing.
- Checkpoint weight loading/parity is still missing.
- GPU training loop is still missing.
- Full unified feature builder tensor parity is still missing.
- Hedge reward remains fail-closed until the paper hedge engine is ported.

## Decision

`V2_NATIVE_RL_MASA_PPO_P0_2A_CODEX_PASS`

P0.2A is acceptable as a partial native env/observation/reward milestone. It is not full trainer migration and does not change the live or shutdown blockers.
