# V2 Native RL Core P0.2A Report

Generated: 2026-05-16
Runtime gate: blocked_human_only. Runtime symbols: [].

## Outcome

Delivered the env / observation tensor / reward suite layer for the V2
native RL core, consuming the P0.1 trainer-consumable snapshot. This is
P0.2A only; no MASA/PPO policy and no checkpoint claim.

## Files

- v2/backend/app/services/rl_core/environment.py (NEW; PaperOnlyEnv)
- v2/backend/app/services/rl_core/observation_builder.py (NEW; ObservationTensor + observation_metadata)
- v2/backend/app/services/rl_core/rewards.py (NEW; base/fee-aware/constrained/hedge-fail-closed)
- v2/backend/app/cli/v2_rl_core_worker.py (EXTENDED; --p0-2a-rollout flag)
- v2/backend/tests/integration/cli/test_v2_rl_core_p0_2a.py (NEW; 17 tests)
- v2/frontend/public/operator_runtime/v2_rl_core/latest/v2_rl_core_status.json (canonical emission with p0_2a_rollout block)

## Test result

17 / 17 P0.2A tests pass. 51 / 51 combined across P0.2A + prior rl_core
+ feature pipeline + trainer snapshot suites.

## Components ported

- PaperOnlyEnv reset / step / close (paper-only deterministic price ramp).
- ObservationTensor builder over the trainer-consumable native snapshot.
- observation_metadata side-band with all required fields.
- Reward suite: base PnL + fee-aware + constrained safety penalty +
  hedge placeholder (inert).
- env_invariants_snapshot and reward_invariants_snapshot.
- CLI rollout block: --p0-2a-rollout reads the snapshot, runs an env
  rollout, emits the rollout summary in the status payload.

## Components MISSING_IN_V2

- Full Gymnasium-compatible env loop.
- MASA/PPO policy network and checkpoint loading.
- GPU training loop.
- Unified feature builder for 2000+ obs dimensions.
- Lagrangian multiplier state persistence.
- Continuous learner / online learning.
- All hedge reward components beyond the inert placeholder.

## Safety invariants verified

- Runtime gate blocked_human_only.
- Runtime symbols empty.
- approves_live / approves_canary / approves_legacy_shutdown / approves_redis_trim all false.
- env / obs / rewards modules: zero forbidden imports (no torch / SB3 /
  gymnasium / redis / ccxt / binance) — verified by source-scan test.
- Hedge reward classification FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE.
- No old Redis writes.
- No exchange mutation reachable.

## Dependency closure

All-files unique top-level imports across new code: __future__,
argparse, dataclasses, datetime, json, math, pathlib, pytest,
subprocess, sys, typing, v2. Zero forbidden imports.

## Codex blocking checks (all PASS)

- env reset/step loop runs paper-only: PASS
- observation tensor built from native snapshot: PASS
- observation metadata includes all required fields
  (feature_snapshot_id, feature_count, tensor_shape,
  missing_feature_flags, stale_feature_flags,
  feature_freshness_state): PASS
- reward suite includes base PnL + fee-aware + constrained/safety +
  hedge placeholder classified FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE: PASS
- no MASA/PPO policy claim: CONFIRMED (components_missing lists policy)
- no checkpoint claim: CONFIRMED
- no live/canary/shutdown approval: CONFIRMED
- no old Redis writes: PASS
- no exchange mutation: PASS

## Migration completion contract classification

PARTIALLY_MIGRATED_P0_2A.

## GO/NO-GO

V2_NATIVE_RL_MASA_PPO_P0_2A_ENV_OBS_REWARD_READY
