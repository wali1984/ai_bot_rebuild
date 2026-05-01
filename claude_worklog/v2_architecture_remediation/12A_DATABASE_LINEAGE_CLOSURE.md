# 12A Database Lineage Closure

## Gap statement
Prior to this update, `claude_worklog/v2_architecture/03_DATABASE_SCHEMA.md` declared the canonical chain
`feature_snapshot_id -> prediction_id -> signal_id -> decision_id -> risk_decision_id -> execution_intent_id`
only as a one-line "Lineage enforcement" stanza. Tables listed FKs without nullability, ON DELETE/ON UPDATE semantics, CHECK constraints, or audit indexes. Missing-attribution rejection was not specified at the database boundary, so application code was the only gate.

## What was added
1. **Enforceable FK chain.** Every hop in the chain is now a NOT NULL foreign key with `ON DELETE RESTRICT` and `ON UPDATE RESTRICT`, declared explicitly on `feature_values`, `prediction_events`, `confidence_events`, `signal_events`, `orchestrator_decisions`, `risk_decisions`, `execution_intents`, and `paper_trades`.
2. **Per-table nullability rules.** Every chain table now lists which columns are NOT NULL (PKs, parent FKs, attribution payload columns such as `raw_output_json`, `reason_json`, `policy_trace_json`, `policy_checks_json`) and which columns are conditionally nullable (`block_reason`, `executed_ts_ms`, `model_checkpoint`).
3. **CHECK constraints for business invariants.**
   - `signal_events.action IN ('long','short','flat','close')` and `confidence BETWEEN 0 AND 1`.
   - `orchestrator_decisions.decision_action IN ('forward','reject','defer','split')`.
   - `risk_decisions.allow_block IN ('allow','block')` paired with a CHECK that `(allow='allow' AND block_reason IS NULL) OR (allow='block' AND block_reason IS NOT NULL)`.
   - `execution_intents.mode IN ('paper','live')`, plus a trigger/CHECK that prevents an intent whose parent `risk_decisions.allow_block = 'block'`.
4. **Missing-attribution rejection at the database.** The schema document now states that the database is the authoritative rejection boundary: any INSERT whose parent FK is NULL or unresolved is rejected with an integrity error. Application code MAY pre-validate but cannot substitute for the constraint.
5. **Explicit index plan for explainability and audit.** Per-FK B-tree indexes plus `(parent_id, created_ts_ms)` and `(symbol, created_ts_ms)` covering indexes are listed for every chain table, guaranteeing that Signal Explainability, Audit Ledger, and Replay can walk the chain without table scans.
6. **Immutability policy.** Chain PKs are declared immutable; UPDATE on lineage columns is forbidden via `ON UPDATE RESTRICT`. DELETE on parents is forbidden via `ON DELETE RESTRICT` to preserve audit history.

## Why this closes the gap
- The chain is now expressible as a sequence of foreign-key constraints that the database itself enforces. There is no path by which a `prediction_events` row exists without a `feature_snapshots` parent, a `signal_events` row exists without a `prediction_events` parent, an `orchestrator_decisions` row exists without a `signal_events` parent, a `risk_decisions` row exists without an `orchestrator_decisions` parent, or an `execution_intents` row exists without an allowed `risk_decisions` parent.
- Missing-attribution rows are impossible by construction, not by convention.
- The audit and explainability surfaces declared in `CLAUDE.md` (Signal Explainability, Audit Ledger, Monitor Center) can resolve any leaf row back to its full chain via indexed joins.
- Live-readiness gating is reflected in the schema: `execution_intents.mode = 'live'` is rejectable by the database when the global live-block flag is set, consistent with the default `LIVE TRADING: BLOCKED` posture.

## Verification pointers
- File updated: `claude_worklog/v2_architecture/03_DATABASE_SCHEMA.md` — see sections "Lineage chain (canonical, enforceable)", every chain table block (`feature_snapshots`, `prediction_events`, `signal_events`, `orchestrator_decisions`, `risk_decisions`, `execution_intents`), and "Lineage enforcement".
- Task spec: `claude_worklog/agent_supervisor/tasks/012a_database_lineage_constraints.json`.
- Required outputs declared by task spec are both produced:
  - `claude_worklog/v2_architecture/03_DATABASE_SCHEMA.md`
  - `claude_worklog/v2_architecture_remediation/12A_DATABASE_LINEAGE_CLOSURE.md`

## Status
Database lineage architecture gap: CLOSED at the architecture-text level. Implementation will be performed in a later V2 build task and must materialize every NOT NULL, FK, CHECK, and index listed above; any deviation reopens this gap.
