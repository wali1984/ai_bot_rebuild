# V2 Native RL Core P0.2A — Legacy Baseline Analysis

Generated: 2026-05-16
Runtime gate: blocked_human_only. Runtime symbols: [].
Contract: claude_worklog/final_readiness/permanent_migration_runtime/latest/MIGRATION_COMPLETION_CONTRACT.md.

## Legacy sources consulted (read-only V2-owned mirrors)

| Legacy path | SHA256 | Size (bytes) | V2-owned path |
|-------------|--------|---------------|---------------|
| rl/environment.py | 39866005417554c7f9552a64eddc14ec1024db7e22b432c844cfd1a8e7800b1d | 66775 | v2/legacy_owned_runtime/rl/environment.py |
| rl/gymnasium_wrapper.py | 61a086cb4a0a406ca67fe2035cf776b0c991bb9d7391572ce86e77aea0a16574 | 14062 | v2/legacy_owned_runtime/rl/gymnasium_wrapper.py |
| rl/obs_schema.py | 9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f | 17346 | v2/legacy_owned_runtime/rl/obs_schema.py |
| rl/unified_feature_builder.py | 2af5c68d812c0a0a5db2e037204f0b2165d9084dea983d1737e09034e8c739a5 | 29925 | v2/legacy_owned_runtime/rl/unified_feature_builder.py |
| rl/reward_functions.py | 87ef4602012cbbd944bdf506fb8f1646375e7732c3a93e87b0946db7a1cca853 | 31805 | v2/legacy_owned_runtime/rl/reward_functions.py |
| rl/constrained_reward.py | 69ff3c75b53d8d3d7844894954cf9d16f334e79e0c1bd39e9624a4482a459b2e | 10861 | v2/legacy_owned_runtime/rl/constrained_reward.py |
| rl/fee_ratio_reward_shaping.py | e7edce3e29a6bf7236329245ba4a14436dc6f6b0a249ad0ad3d05760570bfc06 | 19427 | v2/legacy_owned_runtime/rl/fee_ratio_reward_shaping.py |
| rl/hedge_reward_functions.py | 54c1a5748ca61da84d3e697cf5260251f15cc802281c951f18b902bf522b41c9 | 16526 | v2/legacy_owned_runtime/rl/hedge_reward_functions.py |

## Behaviors PORTED (native V2, paper-only)

1. PaperOnlyEnv reset / step / close loop with deterministic sinusoid +
   linear price ramp. Actions: hold / long / short / close. Round-trip
   cost (fee + slippage) is charged on close.
2. ObservationTensor builder over the trainer-consumable native feature
   snapshot. Fixed feature order; flat tuple of 26 floats; missing values
   map to 0.0 with the snapshot's missing_feature_flags preserved.
3. observation_metadata side-band: schema_version, feature_snapshot_id,
   feature_count, tensor_shape, missing_feature_flags,
   stale_feature_flags, feature_freshness_state, categories_present,
   symbol, timeframe, generated_at, legacy SHA256 citations.
4. Reward suite:
   - base_pnl_reward (realized_bps + 0.5 * unrealized_bps)
   - fee_aware_reward (round-trip cost on close, plus shaping penalty
     when fee/expected_move ratio exceeds max_ratio)
   - constrained_safety_penalty (drawdown / time-in-trade / position-size
     overrun penalties)
   - hedge_reward_placeholder (inert; FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE)
   - compute_reward_suite combines all four with a hard clamp.
5. env_invariants_snapshot and reward_invariants_snapshot exposing the
   safety contract.
6. CLI flag --p0-2a-rollout that loads the trainer-consumable snapshot,
   builds the observation, runs a scripted N-step rollout, and includes
   the rollout summary in the emitted status payload.

## Behaviors PARTIALLY_PORTED

- Env step loop: legacy environment.py is ~1,455 LOC after expansion
  with regime-driven step dynamics, hidden orderbook simulation, fees,
  funding accrual, and slippage curves. V2 P0.2A captures only the
  core action / position / realized / unrealized accounting.
- Observation tensor: legacy unified_feature_builder.py emits 2,000+
  dimensions. V2 P0.2A is a fixed 26-feature tensor aligned to P0.1
  output. The remaining dimensions remain MISSING_IN_V2.
- Reward suite: legacy reward_functions.py + constrained_reward.py +
  fee_ratio_reward_shaping.py + hedge_reward_functions.py span ~78KB
  with several reward classes. V2 P0.2A implements one composable
  suite with the four named components above.

## Behaviors MISSING_IN_V2 (still)

- Full Gymnasium-compatible env loop (1,455 LOC).
- MASA / PPO policy network and checkpoint loading.
- GPU training loop.
- Unified feature builder for 2000+ obs dimensions.
- Lagrangian multiplier state persistence.
- Continuous learner / online learning.
- All hedge reward components beyond the inert placeholder.

## Config / env mapping (informational)

| V2 parameter | Default | Purpose |
|--------------|---------|---------|
| max_steps (env) | 64 | rollout horizon |
| fee_bps_per_side (env, reward) | 5.0 | fee model |
| slippage_bps_per_side (env, reward) | 1.0 | slippage model |
| unrealized_discount (reward) | 0.5 | open-position credit |
| max_ratio (reward) | 0.5 | fee / expected_move shaping threshold |
| max_drawdown_bps (reward) | 200.0 | safety penalty threshold |
| max_time_in_trade_seconds (reward) | 3600 | safety penalty threshold |
| max_position_size (reward) | 1.0 | safety penalty threshold |
| hard_clamp_bps (reward) | 1000.0 | reward clamp |

## Intentional V2 changes

- Env action space is a small finite set (hold / long / short / close)
  rather than the legacy continuous action ontology. Full action
  ontology is later work.
- Observation tensor is a flat tuple of floats (stdlib only) instead of
  a numpy ndarray, to avoid the numpy dependency at the env layer.
- Hedge reward is explicitly inert. Hedge engine port is separate work.

## Deprecated legacy behavior

- The legacy Redis-coupled env step (which read features from Redis on
  every step) is intentionally NOT replicated. The V2 env reads features
  once per rollout from the snapshot path.

## Migration completion contract classification

PARTIALLY_MIGRATED_P0_2A. Not MIGRATED_CODEX_PASS.

Runtime gate stays blocked_human_only.
