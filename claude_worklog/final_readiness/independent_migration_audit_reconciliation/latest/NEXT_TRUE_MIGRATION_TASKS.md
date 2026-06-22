# Next True Migration Tasks

Generated: 2026-05-15
Live gate: `blocked_human_only`. Live symbols: `[]`.

These tasks reflect what real migration requires, not what bridge-only workers
can hand-wave. The permanent objective router should route them in this order
until each artifact set passes Codex review against the migration completion
contract.

## P0 — Required before any legacy shutdown evaluation can advance

### P0.1 — `claude_rebuild_v2_native_feature_pipeline_worker_from_legacy`

Port `feature_pipeline.py` (1,437 lines) into a native V2 worker that:

- Reads raw ingestor data (ideally from native V2 ingestors when P0.5 is done;
  in the interim from legacy Redis under a documented bridge adapter).
- Computes derived features and cross-timeframe aggregations.
- Normalizes and writes V2-prefixed feature keys (NOT legacy Redis keys).
- Publishes `feature_snapshot_id` (sha256 of payload) with freshness/age.
- Exposes a CLI runner, tests, public payload, and Codex review under the
  migration completion contract.

Artifacts required:
- `v2/backend/app/services/feature_pipeline_native/service.py`
- `v2/backend/app/cli/v2_feature_pipeline_native.py`
- `v2/backend/tests/integration/cli/test_v2_feature_pipeline_native.py`
- `v2/frontend/public/operator_runtime/v2_feature_pipeline_native/latest/v2_feature_pipeline_native_status.json`
- Codex PASS file under
  `claude_worklog/final_readiness/v2_feature_pipeline_native/latest/codex_review/CODEX_REVIEW.md`

### P0.2 — `claude_rebuild_v2_trainer_full_rl_masa_ppo_reward_stack`

Port the trainer core:

- `rl/environment.py` (1,455) — Gymnasium env (step/reset/reward).
- `rl/gymnasium_wrapper.py` (343) — env factory.
- `rl/obs_schema.py` (~150) — observation tensor schema.
- `rl/unified_feature_builder.py` (710) — tensor assembly from features.
- `rl/agents/masa_agent.py` (520) — MASA + Hybrid PPO + dual-head policy.
- `rl/enhanced_architectures.py` (~600) — CNN/attention feature extractor.
- `rl/gpu_cnn_policy.py` (~400) — GPU CNN policy.
- `rl/reward_functions.py` (902) + `constrained_reward.py` + `fee_ratio_reward_shaping.py` + `hedge_reward_functions.py`.

This is a major effort. Initial milestones:
1. Environment + observation tensor without the policy.
2. Reward function suite in isolation, tested against legacy reward outputs.
3. MASA policy import test (load legacy checkpoint, forward pass parity).
4. End-to-end training loop on a tiny subset (CPU first).
5. GPU training loop parity once CPU loop is stable.

Each milestone is its own Codex review.

### P0.3 — `claude_rebuild_v2_orchestrator_arbitration_from_legacy`

Port `rl/orchestrator_worker.py` (10,523 lines) signal scoring / regime
filtering / signal routing logic plus `proposal_bus.py`, `tradeplan_orchestrator.py`,
`intent_engine.py`. V2 currently has decision record schema and API only; the
arbitration engine is missing.

Recommended chunking:
1. Decompose orchestrator_worker.py into functional groups (10-15 modules).
2. Port each group with a behavior-parity test against the legacy snapshot in
   `v2/legacy_preserved/full_runtime_closure/rl/`.
3. Replace the current `v2_orchestrator_adapter` PARTIALLY_MIGRATED status
   group by group, never wholesale.

### P0.4 — `claude_rebuild_v2_stop_tp_stealth_exit_engine_paper_first`

Port the trading exit machinery PAPER-FIRST:

- `trading/stealth_stops.py`
- `trading/dynamic_adaptive_stops.py`
- `trading/dynamic_tp_engine.py`
- `trading/stealth_dynamic_integration.py`
- `trading/exit_coordinator.py`
- `trading/churn_prevention.py`

In V2 paper mode only. Live execution remains a fail-closed stub.

### P0.5 — `claude_verify_v2_ingestors_are_native_or_downgrade_to_bridge`

For each of the 9 live ingestors (Binance, Binance liquidations, CoinAnk,
KuCoin, TA, realtime price, CoinAPI v1, CoinAPI WSDS, TokenMetrics):

1. Verify whether the V2 worker actually opens its own WebSocket/REST
   connection or reads legacy Redis output.
2. If bridge-only, downgrade the worker's classification to `READONLY_BRIDGED`
   in `worker_porting_state.json`.
3. Build a native V2 ingestor where feasible. Reuse legacy code under
   `v2/legacy_preserved/` for behavior reference, not as a runtime
   dependency.

## P1 — After P0 progress is visible

### P1.1 — Frontend pages showing exact migration gaps

Extend the simple-English frontend (`/admin/permanent-migration`,
`/status-simple`) with a per-component "is it migrated?" card that uses the
reconciliation matrix JSON as its source. Show:

- audit_finding
- correct_state
- exact_blocker
- next_claude_task
- next_codex_review

### P1.2 — Replay comparison for migrated modules

For each module that reaches `MIGRATED_CODEX_PASS`:

- Add a legacy-vs-V2 replay comparator under
  `v2/backend/app/services/legacy_v2_replay_comparison/`.
- Compare outputs over a held-out window.
- Publish a public payload + Codex review.

## Hard rules during every task

- Do not modify `/home/wali/Desktop/AI BOT`.
- Do not start legacy services.
- Do not write to legacy Redis from V2.
- Do not place, cancel, or modify exchange orders.
- Do not change leverage or margin mode.
- Do not enable live trading.
- Do not create the final approval token.
- Do not create a Redis trim approval token.
- Live gate stays `blocked_human_only`.
- Live symbols stays `[]`.

## Router behavior

The permanent objective router will route P0.1 through P0.5 in order, then
P1.1 and P1.2. It will continue to dispatch the current selected blocker
(`PAPER_EDGE_UNPROVEN`) until each P0 artifact set passes Codex review.
