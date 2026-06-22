# P0.2 Native RL/MASA/PPO Trainer Preparation Report

Generated: `2026-05-16T02:25:19Z`

GO/NO-GO: `V2_NATIVE_RL_MASA_PPO_P0_2_PREPARED_BLOCKED_ON_P0_1_FEATURE_SNAPSHOTS`

## Position

P0.2 is prepared as the native trainer-brain migration lane, but it is blocked from completion claims until P0.1 emits usable native feature snapshots. The current V2 `rl_core` status is `PARTIALLY_MIGRATED` and still lists missing native trainer components, so it cannot be marked migrated.

## Dependency Gate

- P0.1 native feature pipeline public status exists: `True`
- P0.1 status claims non-bridge feature-snapshot capability: `True`
- Usable native feature snapshot payload found: `False`
- Gate reason: `NO_NATIVE_FEATURE_SNAPSHOT_PAYLOAD_FOUND`

The existing `v2_feature_snapshot_builder` payload is not accepted as P0.1 native feature pipeline completion proof because it is the older snapshot builder path and only carries the previous feature groups.

## P0.2 Required Source Ownership

All required legacy trainer core files are owned in `v2/legacy_owned_runtime` with SHA256 citations. See `legacy_trainer_core_source_map.json` for exact paths and hashes.

## P0.2 Must Implement

- Native environment step/reset loop.
- Gymnasium wrapper parity.
- Full observation tensor assembly from P0.1 native feature snapshots.
- MASA/PPO policy network forward-pass parity.
- Enhanced architecture and GPU CNN policy forward-pass parity.
- Reward stack: base, constrained, fee-ratio, hedge reward functions.
- Checkpoint manager and safe weight loading.
- Confidence gates and calibrated confidence.
- Tiny CPU paper-only training loop.
- GPU paper-only training loop.
- Output contract with `feature_snapshot_id`, `trainer_source`, `checkpoint_id`, `expected_move_bps`, `expected_move_after_cost_bps`, `confidence_raw`, and `confidence_calibrated`.

## Codex Guardrail

Codex must fail P0.2 if it is wrapper-only, schema-only, smoke-only, or if it claims trainer parity without P0.1 feature snapshot inputs. Live remains `blocked_human_only`; `live_symbols` remains `[]`.
