# Independent Migration Audit Reconciliation Report

Generated: 2026-05-15
Audit source: `migration-audit.md` (2026-05-15)
Contract: `claude_worklog/final_readiness/permanent_migration_runtime/latest/MIGRATION_COMPLETION_CONTRACT.md`

Live gate: `blocked_human_only`. Live symbols: `[]`. Final approval token: `absent`.

## Headline finding

**V2 is NOT fully migrated.** The independent audit confirms that the trainer
core, RL environment, MASA/PPO architecture, reward functions, native feature
computation, native ingestors, orchestrator arbitration, and stop/TP/stealth
exit engines are NOT native V2 services. The `worker_porting_state.json` that
lists 18 "completed_workers" overstates readiness for shutdown evaluation.

Under the migration completion contract, **0 components are
`MIGRATED_CODEX_PASS`**. Several are correctly `READONLY_BRIDGED`,
`PARTIALLY_MIGRATED`, `PAPER_ONLY`, `FAIL_CLOSED_STUB`, or `MISSING_IN_V2`.

## Why the audit and the porting state disagree

The `worker_porting_state.json` reflects whether a V2 worker exists, runs, and
publishes a payload. The audit asks whether the V2 worker reimplements legacy
behavior. The migration completion contract requires the audit's stricter
question for `MIGRATED_CODEX_PASS`.

This reconciliation downgrades all overbroad claims to the contract-correct
classification.

## Per-component reconciliation (13 downgrades)

| # | Component | Audit finding | Claimed | Correct | Blocker |
|---|-----------|---------------|---------|---------|---------|
| 1 | trainer_core_ppo_masa | Subprocess wrapper only; no native PPO+MASA, no GPU loop | "completed_worker" v2_trainer_bridge | `READONLY_BRIDGED` | Native trainer absent; clause 6/7 fail. |
| 2 | rl_environment_gymnasium_obs | env.py 1,455 / wrapper 343 / obs_schema 150 / unified_feature_builder 710 not ported | "completed_worker" v2_feature_snapshot_builder | `PARTIALLY_MIGRATED` | Domain models only; no tensor builder, no Gymnasium env. |
| 3 | masa_agent_and_policy | 0% migrated | implicit | `MISSING_IN_V2` | No PyTorch model, no SB3 policy, no CNN extractor. |
| 4 | reward_functions | 0% migrated | implicit | `MISSING_IN_V2` | No reward shaping, no constrained reward, no fee-ratio shaping. |
| 5 | feature_pipeline_computation | 1,437-line legacy daemon writes 2,000+ features; V2 has 15-line adapter | "completed_worker" v2_feature_pipeline_and_ta_worker_from_legacy_baseline | `READONLY_BRIDGED` | No native feature computation. |
| 6 | live_ingestors | 9 legacy ingestors run; V2 has CLI bridges only | "completed_workers" v2_market_ingestor / v2_coinank_and_liquidation_bridge | `READONLY_BRIDGED` | No native WebSocket/REST ingestors. |
| 7 | orchestrator_arbitration | rl/orchestrator_worker.py 10,523 lines + proposal_bus + tradeplan_orchestrator + intent_engine NOT ported | "completed_workers" v2_orchestrator_adapter / v2_signal_publisher | `PARTIALLY_MIGRATED` | Decision schema only; arbitration absent. |
| 8 | trading_execution_engine | 35 trading/ files including trader.py 18,000+; V2 paper intent + paper fill only; exchange adapters empty stubs | "completed_workers" v2_paper_execution_worker / v2_execution_ledger_worker / v2_p2_*_adapter_stub | `PAPER_ONLY` + `FAIL_CLOSED_STUB` | Live execution intentionally absent. |
| 9 | stop_tp_stealth_exit | stealth_stops.py, dynamic_tp_engine.py, dynamic_adaptive_stops.py, exit_coordinator.py, churn_prevention.py not ported | not claimed | `MISSING_IN_V2` | No paper-first stop/TP engine in V2. |
| 10 | risk_management_deep_logic | risk gateway framework exists; liquidation prevention, dynamic sizing, Kelly not ported | "completed_worker" v2_risk_gateway_runtime_worker | `PARTIALLY_MIGRATED` | Lane C confirmed 11 paths covered, 3 documented parity gaps. |
| 11 | config_unification | Legacy config.py 6,006 lines not formally ported | "completed_worker" v2_config_admin_manager | `PARTIALLY_MIGRATED` | Legacy config.py remains source of truth. |
| 12 | utils_remaining | ~5 of 21 utils ported; 14+ not | not specifically claimed | `PARTIALLY_MIGRATED` | Multiple utils unported. |
| 13 | hedge_and_dynamic_sizing | rl/hedge_*, trading/adaptive_hedge_*, rl/dynamic_position_sizing.py not ported | not claimed | `MISSING_IN_V2` | No V2 hedge construction or Kelly sizing. |

Full reconciliation rows in
[independent_audit_reconciliation_matrix.json](independent_audit_reconciliation_matrix.json).

## Components that were already honestly classified

These remain as-is; the existing classification matches the audit:

- `v2_account_position_monitor` — `READONLY_BRIDGED` / `FAIL_CLOSED_STUB` / `BLOCKED_BY_PERMISSION` (Lane E confirmed)
- `v2_p2_default_blocked_execution_adapter_stub` — `FAIL_CLOSED_STUB`
- `v2_p2_binance_usdm_adapter_stub` — `FAIL_CLOSED_STUB`
- `v2_p2_deployment_helpers` — local infrastructure helpers, not a runtime migration

## Implications for legacy shutdown

Legacy shutdown is **NOT safe**:

- Legacy ingestors must continue to run; V2 has no native ingestors.
- Legacy `feature_pipeline.py` must continue to run; V2 has no native feature
  computation.
- Legacy `hybrid_trainer.py` must continue to run; V2 has no native PPO+MASA.
- Legacy `orchestrator_worker.py` must continue to run; V2 has no native
  arbitration.
- Legacy `trader.py` being stopped is acceptable because V2 paper-only does not
  rely on live execution.

`approves_legacy_shutdown` remains `false`.

## Implications for live readiness

Live is **NOT ready**:

- Native trainer absent → V2 cannot drive live decisions.
- Native feature computation absent → V2 cannot derive evidence.
- Native orchestrator arbitration absent → V2 cannot arbitrate independently.
- Exchange adapters are empty stubs by design.
- Paper edge has zero safe threshold candidates across 72 replay rows (Lane A).
- Trade permission unknown / credentials missing (Lane E).

`live_gate` remains `blocked_human_only`. `live_symbols` remains `[]`.
`approves_live` remains `false`. `approves_canary` remains `false`.

## What this reconciliation IS

- A correction of the migration claim ledger to match independent audit
  evidence.
- A list of exact P0 implementation tasks to route through the permanent
  objective router.
- A frontend-truth update so the simple-English page stops calling
  bridge-only workers "complete".

## What this reconciliation IS NOT

- It is not a migration. It changes labels, not code.
- It does not authorize live, canary, legacy shutdown, or Redis trim.
- It does not produce any approval token.
- It does not modify the protected trainer venv or legacy services.

## GO/NO-GO

`INDEPENDENT_MIGRATION_AUDIT_RECONCILIATION_READY`

(Honest reconciliation is ready. Migration itself is NOT ready. Live remains
blocked.)
