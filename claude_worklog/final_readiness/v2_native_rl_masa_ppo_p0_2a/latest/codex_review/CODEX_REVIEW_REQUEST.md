# Codex Review Request — V2 Native RL Core P0.2A (Env / Obs / Reward)

Task id: codex_review_v2_native_rl_masa_ppo_p0_2a
Status: PENDING_CODEX_REVIEW
Generated: 2026-05-16
Runtime gate: blocked_human_only. Runtime symbols: [].

## Scope

Adversarial review of the V2 RL core P0.2A milestone.

Verify:

1. PaperOnlyEnv reset/step/close runs entirely in paper simulation with
   no exchange call, no order placement, no live state mutation.
2. ObservationTensor is built from the trainer-consumable native feature
   snapshot at one of the canonical paths
   (v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json
   or the public mirror).
3. Observation output includes feature_snapshot_id, feature_count,
   tensor_shape, missing_feature_flags, stale_feature_flags, and
   feature_freshness_state.
4. Reward suite contains base PnL, fee-aware, constrained/safety
   penalty, and hedge placeholder. Hedge placeholder is inert and
   classified FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE.
5. No MASA/PPO policy claim, no checkpoint claim, no trainer parity
   claim is made in any emitted artifact.
6. No live/canary/legacy shutdown approval token.
7. No old Redis writes; no exchange mutation.
8. Runtime gate stays blocked_human_only; runtime symbols stays empty.
9. env / obs / rewards modules do not import torch / SB3 / gymnasium /
   redis / ccxt / binance.

## Codex blocking conditions

Block if any of:

- MASA/PPO policy claim appears.
- Checkpoint loader claim appears (weights, not metadata).
- Trainer parity claim appears.
- live/canary/legacy shutdown / Redis trim approval token appears.
- Hedge reward component is active (not classified FAIL_CLOSED).
- Observation output missing any required metadata field.
- env reaches a path that places or cancels exchange orders, changes
  leverage, or writes to legacy Redis.
- Migration classification differs from PARTIALLY_MIGRATED_P0_2A.

## Expected outcome

CODEX_REVIEW.md placed in this directory with top-line:

GO_NO_GO_CODEX_REVIEW_V2_NATIVE_RL_MASA_PPO_P0_2A_ENV_OBS_REWARD_PASS_OR_FAIL

This review does not authorize live trading, canary, legacy shutdown, or
Redis trim.
