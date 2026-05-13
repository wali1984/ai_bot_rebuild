# V2_WORKER_PORTING_SEQUENCE

Ordered porting sequence. P0 first, P1 next, P2 last. Within each tier, ordering follows the dependency chain.

## P0 (six workers; library code exists; CLI lift needed)

1. **`v2_feature_snapshot_builder`** — feeds everything downstream
2. **`v2_risk_gateway_runtime_worker`** — consumes orchestrator output; ensures fail-closed gate
3. **`v2_paper_execution_worker`** — consumes risk decisions
4. **`v2_execution_ledger_worker`** — consumes execution results
5. **`v2_signal_lineage_worker`** — assembles the full chain
6. **`v2_account_position_monitor`** — read-only; built from scratch (MISSING_IN_V2); independent of #1–#5 in terms of input chain

## P1 (eight workers; either missing or wrapper-only or stub)

7. **`v2_market_ingestor`** — durable market feed (replaces ad-hoc Binance public REST in paper online runtime)
8. **`v2_orchestrator_adapter`** — CLI lift of existing library
9. **`v2_replay_worker`** — CLI lift of existing library
10. **`v2_signal_publisher`** — fan-out layer above lineage
11. **`v2_coinank_liquidation_bridge`** — market intelligence (currently MISSING_IN_V2 beyond a symbol resolver)
12. **`v2_trainer_bridge`** — either subprocess wrapper around legacy trainer binary OR V2-native trainer service
13. **`v2_script_monitor`** — Monitor Center backend (replaces placeholder)
14. **`v2_config_admin_manager`** — runtime config CRUD with approval workflow (replaces OPTIONS skeletons)

## P2 (three fail-closed stubs)

15. **`v2_default_blocked_execution_adapter_stub`** — explicit BLOCKED_GATE_NOT_APPROVED-raising worker (above the existing middleware)
16. **`v2_binance_usdm_adapter_stub`** — exchange-specific fail-closed adapter; read-only paths only
17. **`v2_deployment_helpers`** — preflight + start + stop scripts; refuses to start if approval token present

## Dependency graph (abbreviated)

```
market_ingestor ─┐
                 ├─> feature_snapshot_builder ─> orchestrator_adapter ─┐
trainer_bridge ──┤                                                     │
coinank_bridge ──┘                                                     ├─> risk_gateway_runtime_worker ─> paper_execution_worker ─> execution_ledger_worker ─> signal_lineage_worker ─> signal_publisher
                                                                       │
account_position_monitor (independent read-only)                       │
script_monitor (cross-cutting)                                         │
config_admin_manager (cross-cutting; gates dangerous changes via approval token workflow)
```

## Concurrency rules

- Lane 1 (Claude implementation) implements workers strictly in the order above.
- Lane 2 (Codex review) audits each worker as soon as its artifacts land; never blocks Lane 1 from starting the next worker.
- Lane 3 (bootstrap) brings up each worker after its Codex review either PASSES or is explicitly BLOCKED-with-evidence.
- Lane 4 (GUI/Admin AI visibility) lags one worker behind; pauses on any conflict with Lane 1.
- Lane 5 (continuous evidence) covers all workers once started; first task is to restart the existing paper online runtime and paper shadow observer that are currently DOWN.

## Stopping condition

This sequence is **not** finished until at least workers 1–6 are MIGRATED_AND_RUNNING (or explicitly blocked with evidence), Codex aggregate is `EMERGENCY_V2_RUNTIME_MIGRATION_CODEX_PASS`, and bootstrap preflight passes. The live gate stays `blocked_human_only` throughout.
