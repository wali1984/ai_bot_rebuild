# REMAINING_BLOCKERS — Emergency V2 Runtime Migration

This is the list of concrete blockers that prevent `EMERGENCY_V2_RUNTIME_MIGRATION_AND_ONLINE_BOOTSTRAP_READY` from being declared. Each blocker maps to a queued task descriptor.

## P0 blockers (must clear before READY)

| # | blocker | task descriptor (queued) | what unblocks |
|---|---|---|---|
| 1 | risk gateway has no standalone CLI worker | `claude_port_v2_risk_gateway_runtime_worker.json` | CLI implemented, tests pass, Codex review PASS |
| 2 | paper execution has no standalone CLI worker | `claude_port_v2_paper_execution_worker.json` | CLI implemented, no-real-exchange invariant test passes |
| 3 | execution ledger has no standalone CLI worker | `claude_port_v2_execution_ledger_worker.json` | append-only ledger CLI implemented |
| 4 | account/position monitor MISSING_IN_V2 | `claude_port_v2_account_position_monitor.json` | read-only monitor implemented with MISSING_CREDENTIALS path |
| 5 | signal lineage hard-coded in paper online runtime | `claude_port_v2_signal_lineage_worker.json` | lifted into standalone worker; signal_publisher.py becomes real |
| 6 | feature snapshot builder embedded in paper online runtime | `claude_port_v2_feature_snapshot_builder.json` | lifted into standalone CLI |
| 7 | paper online runtime currently DOWN | bootstrap step 1 in [V2_LOCAL_ONLINE_BOOTSTRAP.md](V2_LOCAL_ONLINE_BOOTSTRAP.md) | restart succeeds; payload fresh < 60s |
| 8 | automation supervisors (agent_supervisor / parallel_capacity_scheduler / codex_non_live_watchdog / always_on_objective_runner) currently DOWN | bootstrap step 4 | wrappers re-launched; loops emit events |

## P1 blockers (do not block READY but block independent paper-shadow runtime)

| # | blocker | task descriptor |
|---|---|---|
| 9 | market ingestor MISSING_IN_V2 | `claude_port_v2_market_ingestor.json` |
| 10 | CoinAnk bridge MISSING_IN_V2 (only resolver exists) | `claude_port_v2_coinank_liquidation_bridge.json` |
| 11 | trainer bridge is read-only on legacy Redis only | `claude_port_v2_trainer_bridge.json` |
| 12 | orchestrator adapter library-only | `claude_port_v2_orchestrator_adapter.json` |
| 13 | signal publisher placeholder | `claude_port_v2_signal_publisher.json` |
| 14 | replay/backtest runner library-only | `claude_port_v2_replay_worker.json` |
| 15 | script monitor placeholder | `claude_port_v2_script_monitor.json` |
| 16 | config admin manager OPTIONS skeletons only | `claude_port_v2_config_admin_manager.json` |

## P2 blockers (safety/exchange stubs; do not block paper-shadow READY)

| # | blocker | task descriptor |
|---|---|---|
| 17 | no explicit fail-closed execution-adapter worker stub above middleware | `claude_port_v2_p2_default_blocked_execution_adapter_stub.json` |
| 18 | no Binance USD-M adapter stub | `claude_port_v2_p2_binance_usdm_adapter_stub.json` |
| 19 | no deployment helpers / preflight | `claude_port_v2_p2_deployment_helpers.json` |

## Cross-cutting safety blockers

- **Live gate** must remain `blocked_human_only` in every emitted worker payload. Already enforced in library code; verify on each Codex review.
- **Final approval token absent** at `claude_worklog/approvals/APPROVED_FINAL_LIVE_TINY_CANARY_ONLY.md`. Currently absent (verified Phase A).
- **Redis trim approval absent**. Currently absent (verified Phase A).
- **Legacy paths untouched** — `/home/wali/Desktop/AI BOT` is frozen reference; never edited.

## When this list will reach zero

- After Lane 1 implements the six P0 worker task descriptors above.
- After Lane 2 publishes `EMERGENCY_V2_RUNTIME_MIGRATION_CODEX_PASS`.
- After Lane 3 bootstrap succeeds with fresh payloads under `v2/frontend/public/operator_runtime/<each P0 worker>/latest/`.
- After the four automation supervisors restart and continue emitting events.

This task descriptor itself does not implement workers; it dispatches them. The remaining-blockers count therefore stays positive until Lane 1 picks up the queued P0 tasks.
