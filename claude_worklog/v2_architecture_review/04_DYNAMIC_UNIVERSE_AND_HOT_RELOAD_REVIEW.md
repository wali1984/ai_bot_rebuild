# 04 Dynamic Universe and Hot-Reload Review

## Scope
Verify dynamic symbol universe and hot-reload propagation cover all required behaviors.

## Inputs
- Architecture: 02, 03, 06, 07, 08
- Requirements: 11, 14, 19

## Universe layers
Required four-layer model is present and consistent across artifacts:
- `available_universe`
- `observed_universe`
- `training_universe`
- `trading_universe`

Mappings:
- Architecture file 07 defines all four layers explicitly.
- Domain model file 02 lists `available_universe_symbol`, `observed_universe_symbol`, `training_universe_symbol`, `trading_universe_symbol`.
- Database schema file 03 encodes layers via `universe_members.layer ∈ {available|observed|training|trading}` with `universe_versions` versioning.

## Add/remove/update without full restart
Required by requirement 11 and 14:
- GUI lifecycle CRUD documented in 06 Market Universe Manager page (add/remove/update + force apply/rollback admin path).
- Universe versioning encoded as `universe_versions` table (state machine `proposed|validated|approved|applied|verified`).
- Architecture file 08 defines hot-reload pipeline, explicitly: "No routine full restart allowed for universe updates."
- Requirement 14 reaffirms: "No full restart fallback is allowed for routine universe updates."

## Hot-reload propagation targets
Required eight targets:
1. ingestors
2. feature pipeline
3. trainer adapter
4. orchestrator
5. risk gateway
6. trader fleet
7. monitor
8. GUI

Architecture file 08 lists exactly these eight targets. Requirement 14 lists exactly these eight targets. The two lists match.

## State machine and rollback
- 5-state flow `proposed → validated → approved → applied → verified` is identical between architecture 08 and requirement 14.
- Rollback to last verified version is explicit in both, with audit and re-verification.

## Component acknowledgment
- Architecture file 08 mandates ack envelope (`component_id`, `applied_version`, `ack_ts_ms`, `validation_status`, `rollback_ready`).
- Requirement 14 mandates: missing ack triggers escalation; ack must include local apply ts, validation status, rollback readiness.
- Architecture preserves all required ack fields.

## Versioning, audit, evidence
- `universe_version` is immutable per requirement 14, encoded as PK in `universe_versions` (file 03).
- Pre-apply, post-apply, component health, diff/impact summaries listed in architecture 08.
- Audit linkage to ledger is encoded via `audit_events` and `ai_action_changes` (file 03 + 13).

## Selection-engine hot-reload integration
- Requirement 14 explicitly requires hot-reload to ingest adaptive-selection updates derived from passive discovery (requirement 19).
- Architecture file 07 defines the selection engine; architecture file 08 covers the propagation contract; database schema persists `symbol_scores` per `universe_version_id`.

## Risks and notes
- File 08 does not enumerate per-component validation policies (e.g., what counts as a successful trainer adapter ack). This is acceptable at architecture phase; build phase must define per-component success criteria.
- Override governance (manual include/exclude, force states) lives in requirement 19 + architecture 07, encoded as `symbol_overrides` in 03. This is sufficient.

## Verdict
Dynamic universe CRUD and hot-reload propagation across all eight required targets are fully represented. Restart-free updates with versioning, ack, audit, and rollback are covered.
