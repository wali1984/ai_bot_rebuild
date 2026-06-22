# V2 Native RL/MASA/PPO P0.2A Env/Obs/Reward — GO/NO_GO

Generated: 2026-05-16

## GO_NO_GO

V2_NATIVE_RL_MASA_PPO_P0_2A_ENV_OBS_REWARD_READY

## Milestone scope

P0.2A only: native environment, observation tensor, and reward suite.
NO MASA/PPO policy claim. NO checkpoint claim. NO trainer parity claim.

## Why READY

- PaperOnlyEnv with reset/step/close runs paper-only with deterministic
  price dynamics. Round-trip fee/slippage charged on close.
- Observation tensor built from the P0.1 trainer-consumable native
  snapshot. Fixed feature order (26 features); missing values map to 0
  with the snapshot's missing_feature_flags preserved.
- Observation metadata emits all required fields: feature_snapshot_id,
  feature_count, tensor_shape, missing_feature_flags,
  stale_feature_flags, feature_freshness_state, categories_present,
  symbol, timeframe, generated_at, legacy SHA256 citations.
- Reward suite emits all four required components: base PnL,
  fee-aware, constrained safety penalty, and hedge placeholder
  (inert; classified FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE).
- CLI flag --p0-2a-rollout runs the env+obs+reward loop and includes
  the rollout summary in the emitted status payload at the canonical
  operator-runtime path.
- 17 / 17 P0.2A tests pass. 51 / 51 combined.
- Zero forbidden imports in env / obs / rewards modules (no torch / SB3
  / gymnasium / redis / ccxt / binance), verified by a source-scan test.

## Codex blocking checks (all PASS)

- env reset/step loop runs paper-only: PASS
- observation tensor built from native snapshot: PASS
- observation output includes feature_snapshot_id, feature_count,
  tensor_shape, missing_feature_flags, stale_feature_flags,
  feature_freshness_state: PASS
- reward suite includes base PnL, fee-aware, constrained/safety,
  hedge placeholder classified FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE: PASS
- no MASA/PPO policy claim: CONFIRMED
- no checkpoint claim: CONFIRMED
- no live/canary/shutdown approval: CONFIRMED
- no old Redis writes: PASS
- no exchange mutation: PASS

## Live, canary, legacy shutdown, Redis trim

- live_gate: blocked_human_only
- live_symbols: []
- approves_live: false
- approves_canary: false
- approves_legacy_shutdown: false
- approves_redis_trim: false
- final_approval_token: absent
- redis_trim_approval_token: absent

## Migration completion contract classification

PARTIALLY_MIGRATED_P0_2A. Not full trainer migrated. Not
MIGRATED_CODEX_PASS.

## What this READY does NOT do

- Does NOT authorize live trading, canary, legacy shutdown, or Redis trim.
- Does NOT claim trainer parity. P0.2 still requires MASA/PPO policy,
  checkpoint loader, GPU training loop, and full env/obs parity.
- Does NOT activate the hedge reward component.

## Next P0.2 sub-milestones (per master roadmap)

- P0.2B — MASA/PPO policy network (CPU first, then GPU).
- P0.2C — Checkpoint metadata loader (no weights yet).
- P0.2D — End-to-end PPO update loop on a tiny dataset (no live).
- P0.2E — GPU training loop parity.

Runtime gate remains blocked_human_only.
