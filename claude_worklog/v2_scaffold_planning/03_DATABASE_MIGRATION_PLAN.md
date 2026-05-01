# 03 — Database Migration Plan

## 1. Authority
The schema authority is `claude_worklog/v2_architecture/03_DATABASE_SCHEMA.md` together with `claude_worklog/v2_architecture_remediation/12A_DATABASE_LINEAGE_CLOSURE.md`. This plan does not redefine the schema; it sequences its materialization for milestone C. Migration files are NOT written by milestone B; only the Alembic harness and the migration sequence plan are scaffolded.

## 2. Migration tooling
- Alembic with the SQLAlchemy 2.0 declarative base.
- Postgres 15+. Foreign key actions use `ON DELETE RESTRICT` and `ON UPDATE RESTRICT` per the lineage rule.
- One migration per logical group; squashing forbidden until the schema is frozen by `18_ARCHITECTURE_REVIEW_GO_NO_GO.md`.
- Each migration is reversible. Down-revisions are mandatory and verified in CI by `ops/ci/schema_drift_check.py`.

## 3. Migration sequence (milestone C)
The migrations are applied in the order below. Each row names the migration label, the tables created, and the constraint focus. The constraint focus is the smallest set of architectural NOT NULL/FK/CHECK/index obligations that the migration must satisfy. The validation artifact `claude_worklog/v2_build/C_DATABASE_VALIDATION.md` carries one row per constraint with a `psql \d+` line proving its existence.

| Order | Label | Tables | Constraint focus |
|------|-------|--------|------------------|
| 1 | `0001_identity` | `accounts`, `sessions`, `tokens`, `revoked_tokens`, `mfa_assertions` | session/token uniqueness, revocation chain, hash-chained auth audit |
| 2 | `0002_governance` | `governance_levels`, `approvals`, `approval_subjects`, `audit_events`, `audit_chain` | L0–L5 taxonomy, single-use consumption, monotonic sequence, tamper-evident hash chain |
| 3 | `0003_exchanges_universe` | `exchanges`, `exchange_connectors`, `exchange_symbols`, `universe_versions`, `universe_members`, `symbol_scores`, `symbol_overrides` | universe state machine `proposed|validated|approved|applied|verified`, layer enum, override approval state |
| 4 | `0004_features` | `feature_snapshots`, `feature_values`, `feature_set_manifests` | source-grounding tuple NOT NULL, freshness manifest NOT NULL, snapshot immutability |
| 5 | `0005_lineage_chain` | `prediction_events`, `signal_events`, `orchestrator_decisions`, `risk_decisions`, `execution_intents`, `paper_trades` | every parent FK NOT NULL, ON DELETE RESTRICT, ON UPDATE RESTRICT, indexed on `(parent_id, created_ts_ms)` |
| 6 | `0006_confidence_explainability` | `confidence_explainability_blocks`, `top_contributors`, `calibration_records` | ≥3 contributors with explicit placeholders when fewer real contributors exist; rejection-class enum |
| 7 | `0007_risk_policy` | `risk_policy_bundles`, `risk_phase_outcomes`, `kill_switch_events`, `live_readiness_state` | policy bundle state machine, deterministic phase order, kill-switch persistence |
| 8 | `0008_hot_reload` | `hot_reload_rollouts`, `hot_reload_targets`, `hot_reload_events`, `hot_reload_acks`, `hot_reload_dead_letters` | ack binding, retry/dead-letter behavior, rollback state machine |
| 9 | `0009_evidence` | `evidence_packets`, `validation_runs`, `dimension_status_history`, `packet_rejections` | six-packet model, twenty-plus envelope fields, six rejection classes, run-age windowing |
| 10 | `0010_indexes_audit` | n/a (indexes only) | covering indexes per `(parent_id, created_ts_ms)`, audit indexes, partial indexes for live-block invariants |

The down-migration of each step DROPs only what it created; cross-step dependencies are honored by Alembic's revision graph.

## 4. Lineage chain enforcement (milestone C must produce)
Per `12A_DATABASE_LINEAGE_CLOSURE.md`, every link of `feature_snapshot_id -> prediction_id -> signal_id -> decision_id -> risk_decision_id -> execution_intent_id` MUST be:

- a NOT NULL FK on the downstream table
- ON DELETE RESTRICT
- ON UPDATE RESTRICT
- backed by `idx_<child>_<parent>` on the FK column
- backed by `idx_<child>_<parent>_ts (parent_id, created_ts_ms)` for replay ordering
- enforced by a database CHECK or NOT NULL — NOT by application code only

The constraint-coverage matrix in `C_DATABASE_VALIDATION.md` MUST list one row per architectural constraint and one `psql \d+` line proving it materialized. Any missing row reopens `12A`.

## 5. CHECK constraints (non-exhaustive, must be exhaustive in C)
- `model_version` and `checkpoint` non-empty on `prediction_events`.
- `mode IN ('paper','live')` on `execution_intents`. The default value is `'paper'`. `'live'` insertions are rejected unless `live_readiness_state.state = 'active'` AND a corresponding `approvals` row of level `L5` is referenced.
- `policy_bundle_state IN ('proposed','validated','approved','active','retired')` on `risk_policy_bundles`.
- `lineage_gap_reason IN ('upstream_missing','downstream_not_yet_emitted','ingest_pre_attribution','replay_partial')` when any chain field is NULL on a stage where it should be present.
- `top_contributor_count >= 3` on `confidence_explainability_blocks`; rows with fewer real contributors must use named placeholder rows in `top_contributors` per `12C` closure §4.

## 6. Idempotency and concurrency
- `idempotency_keys (key, actor_subject, body_hash, response_id, created_ts_ms)` table, unique on `(key, actor_subject, body_hash)` per `05_API_CONTRACTS.md` §1.4.
- Optimistic concurrency on every versioned resource via `etag` column + `If-Match` header. The `etag` is a deterministic hash of `(version_id, updated_ts_ms)`.

## 7. Audit ledger
- `audit_events` is append-only. INSERT trigger forbids UPDATE/DELETE. Hash chain link uses prior row's `event_hash`. The chain head is verified at startup; mismatch raises `audit.chain_break` and refuses to start the API.

## 8. Retention
- Retention policies live in `redis_v2/retention.py` and as Postgres partition rules where applicable. No retention rule may delete an `audit_events` row. Snapshot rows are retained ≥ 90 days by default; configurable per `v2_requirements/05_REDIS_MEMORY_AND_RETENTION_POLICY.md`.

## 9. Test surface produced in milestone C
- `backend/tests/integration/test_lineage_constraints.py` — proves every FK rejects the orphan INSERT.
- `backend/tests/integration/test_audit_chain.py` — proves UPDATE/DELETE of `audit_events` is rejected.
- `backend/tests/integration/test_live_block.py` — proves `mode='live'` INSERT is rejected without an active `live_readiness_state` and an `L5` approval row.

## 10. Status
DATABASE MIGRATION SEQUENCE: PLANNED. MIGRATION FILES: NOT YET WRITTEN. Authoring belongs to milestone C, gated by milestone B completion + `12A` closure verification.