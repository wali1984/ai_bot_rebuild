# V2 Native RL MASA/PPO P0.2B — CPU Forward-Pass Policy

- Phase: `P0.2B`
- Sprint: `TWELVE_HOUR_NATIVE_CORE_MIGRATION_AND_SHUTDOWN_READINESS_SPRINT`
- Generated: `2026-05-16T03:45:00Z`
- Git HEAD at write time: `31a7fd70319f0d586c454b5ea2ea530ba9cb1541`

## What was built

- `v2/backend/app/services/rl_core/policy.py` — pure stdlib CPU
  forward-pass policy. 26-dim observation → 5-class action logits +
  expected-move scalar head. Deterministic for fixed seed.
- `v2/backend/app/services/rl_core/masa_adapter.py` — wraps the policy
  in a `get_action_and_value` surface that mirrors the legacy
  `MASAAgent`.
- `v2/backend/app/services/rl_core/ppo_policy.py` — wraps the policy in
  a `predict` surface that mirrors `HybridPPO.predict`.
- `v2/backend/tests/integration/cli/test_v2_rl_core_p0_2b_policy.py` —
  10 integration tests covering shape, determinism, hedge masking,
  forbidden-import scan, and invariants.
- `v2/backend/app/cli/v2_rl_core_worker.py` extended with
  `--p0-2b-policy-forward`; emits a `p0_2b_policy_forward` block in
  `v2/frontend/public/operator_runtime/v2_rl_core/latest/v2_rl_core_status.json`.

## Output contract (per forward pass)

- `policy_id` — sha256-prefixed deterministic ID derived from the
  fixed-seed weight tensors.
- `observation_feature_snapshot_id` — snapshot ID consumed.
- `action_logits` — 5 floats.
- `action_probabilities` — 5 floats summing to 1.0.
- `action_labels` — `["hold", "long", "short", "close", "hedge"]`.
- `selected_action` and `selected_action_index`.
- `expected_move_bps_head` — scalar bps computed by a real model head
  on the hidden layer (NOT a hardcoded constant; NOT legacy-log
  derived).
- `model_source_classification` —
  `V2_NATIVE_CPU_DETERMINISTIC_INIT_NO_CHECKPOINT`.
- `hedge_action_classification` —
  `FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE`.
- `missing_policy_components` — explicit array naming every gap.

## Permanent migration contract checklist

- Legacy source paths cited: yes
  (`masa_agent.py`, `enhanced_architectures.py`, `gpu_cnn_policy.py`,
  `hybrid_action_space.py`).
- SHA256 citations recorded: yes (see `legacy_behavior_mapping.json`).
- Dependency closure recorded: yes (see `LEGACY_BASELINE_ANALYSIS.md`).
- Config/env mapping recorded: yes (see `LEGACY_BASELINE_ANALYSIS.md`).
- Behavior mapping recorded: yes (see `legacy_behavior_mapping.json`).
- V2 implementation present: yes.
- Tests present: yes (10 passing).
- Public payload present: yes
  (`v2_rl_core_status.json` with `p0_2b_policy_forward` block).
- Codex review PASS: pending (awaiting Codex sweep).
- No old Redis writes: confirmed (no `import redis`).
- No exchange mutation: confirmed (no exchange SDK import).
- `live_gate == "blocked_human_only"`: confirmed.
- `live_symbols == []`: confirmed.

## What is NOT migrated (explicit blockers)

- PPO clip loss and GAE advantage estimation.
- Value function head separate from expected-move head.
- Lagrangian safety constraint state.
- Checkpoint weight loading (deferred to P0.2C).
- CPU PPO update loop (deferred to P0.2D).
- GPU training parity (deferred to P0.2E).
- Trainer output contract: expected_move_after_cost_bps,
  confidence_calibrated, feature attribution (deferred to P0.2F).

## Test summary

```
v2/backend/tests/integration/cli/test_v2_rl_core_p0_2b_policy.py
.......... 10 passed
```

## Decision

P0.2B is a partial native MASA/PPO migration milestone. It proves the
forward-pass surface plugs into the V2-native P0.1 → P0.2A pipeline
without touching torch, Redis, or the exchange. It does NOT replace
the legacy trainer for live trading.

GO/NO-GO recorded in this directory's `GO_NO_GO.md`.
