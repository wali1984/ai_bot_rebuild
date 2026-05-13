# CODEX_EMERGENCY_MIGRATION_REVIEW (aggregate)

This is the aggregate Codex audit placeholder. The per-worker Codex review tasks are queued under `claude_worklog/agent_supervisor/tasks/codex_review_v2_*.json` and emit their own per-worker review + GO/NO-GO files under `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/`.

## Aggregation rule

This aggregate review is `PASS` only if **all** P0 per-worker Codex GO/NO-GO files contain a `_CODEX_PASS` line. Any single `_CODEX_FAIL` blocks the aggregate.

| worker (P0) | codex review file | required pass token |
|---|---|---|
| risk gateway runtime worker | `codex_v2_risk_gateway_runtime_worker_go_no_go.md` | `V2_RISK_GATEWAY_RUNTIME_WORKER_CODEX_PASS` |
| paper execution worker | `codex_v2_paper_execution_worker_go_no_go.md` | `V2_PAPER_EXECUTION_WORKER_CODEX_PASS` |
| execution ledger worker | `codex_v2_execution_ledger_worker_go_no_go.md` | `V2_EXECUTION_LEDGER_WORKER_CODEX_PASS` |
| account/position monitor | `codex_v2_account_position_monitor_go_no_go.md` | `V2_ACCOUNT_POSITION_MONITOR_CODEX_PASS` |
| signal lineage worker | `codex_v2_signal_lineage_worker_go_no_go.md` | `V2_SIGNAL_LINEAGE_WORKER_CODEX_PASS` |
| feature snapshot builder | `codex_v2_feature_snapshot_builder_go_no_go.md` | `V2_FEATURE_SNAPSHOT_BUILDER_CODEX_PASS` |

P1 reviews follow the same rule but do not gate the P0 aggregate. P2 stub reviews must pass before any P2 stub ships.

## Aggregate failure conditions (any of these blocks PASS)

- Any P0 worker artifact missing (CLI, test, payload, report).
- Any P0 Codex GO/NO-GO file contains `_CODEX_FAIL`.
- Any worker writes old Redis, modifies legacy, places/cancels/modifies exchange orders, changes leverage or margin mode, or unlocks the live gate.
- Live gate not `blocked_human_only` in any worker payload.
- Final approval token created at `claude_worklog/approvals/APPROVED_FINAL_LIVE_TINY_CANARY_ONLY.md`.
- Redis trim approval token created.
- Any worker treats `STATIC_PROOF_FIXTURE`, `hist_*`, or paper simulations as real account/runtime evidence.
- Any worker hides MISSING_RUNTIME_EVIDENCE or MISSING_CREDENTIALS classification when applicable.
- Backlog or planning doc counted as migration.

## Current status

As of 2026-05-13 (this turn), zero P0 workers have been **implemented**. Six P0 task descriptors are queued. The aggregate Codex result is therefore **`EMERGENCY_V2_RUNTIME_MIGRATION_CODEX_FAIL`** until the queued worker tasks are picked up by sub-agents, implemented, audited, and pass.

See [CODEX_GO_NO_GO.md](CODEX_GO_NO_GO.md).
