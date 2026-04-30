# 03 Schema and Data Model Review

## Scope
Review schema adequacy for required entities and enforceable lineage.

## Required domain coverage check
All required domains are represented in architecture schema directly or via normalized tables:
- exchanges, exchange_connectors, exchange_symbols
- available/observed/training/trading universe (encoded via `universe_members.layer`)
- universe_versions, symbol_scores, symbol_overrides
- feature_snapshots, feature_values
- prediction_events, confidence_events, signal_events
- orchestrator_decisions, risk_decisions, execution_intents
- trader_instances, trader_assignments
- audit_events, ai_action_changes, config_versions
- monitor_snapshots, evidence_packets, redis_key_observations, heartbeat_events
- replay_runs, paper_trades
- users, roles, approvals

## Lineage enforceability check (hard gate)
Required chain:
`feature_snapshot_id -> prediction_id -> signal_id -> decision_id -> risk_decision_id -> execution_intent_id`

Result: **PASS (modeled)**
- Chain appears in domain model and schema.
- Parent-child FK progression is represented.

## Adversarial findings
1. **Universe layer persistence ambiguity (MEDIUM)**
   - Four layers are normalized into one `universe_members` table with `layer` enum.
   - This is valid, but architecture does not define uniqueness constraints for `(universe_version_id, layer, exchange_symbol_id)` and force-state exclusivity rules.

2. **Lineage tuple redundancy policy missing (MEDIUM)**
   - Requirements call for full upstream tuple on downstream records.
   - Architecture includes FK chain but does not explicitly mandate tuple materialization strategy (denormalized cache columns vs view-only derivation).

3. **Governance approvals linkage depth is partial (MEDIUM)**
   - `approvals` table exists, but architecture does not require explicit FK links from each high-risk mutable domain event to an approval record.

4. **Schema-level constraints for explainability cardinality are missing (LOW)**
   - Minimum top-positive/top-negative contributor cardinality is required in requirements but not represented as schema or validation contract.

## Verdict
Data model breadth is strong and lineage intent is present. However, several constraint-level details remain under-specified for deterministic scaffold and automated validation.
