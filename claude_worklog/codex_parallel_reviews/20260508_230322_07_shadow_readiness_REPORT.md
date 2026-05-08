# Codex Parallel Review - Shadow Mode Readiness

Review date: 2026-05-08

Verdict: BLOCKED

## Scope Reviewed

- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl`
- `claude_worklog/legacy_readonly_audit`

## Findings

### Blocker 1 - No true legacy-vs-V2 divergence audit output

The shadow readiness implementation is a readiness flag boundary only. `v2/backend/app/domain/shadow_mode_readiness/flag.py` defines `ShadowModeReadinessFlag(state, flag_emitted_ts_ms, live_blocked)` and enforces `live_blocked is True`; `v2/backend/app/services/shadow_mode_readiness/service.py` only accepts `not_ready` and `ready`; `v2/backend/app/composition/shadow_mode_readiness/runtime.py` only binds the assembler to an injected clock.

The test-only shadow evidence harness pairs a `legacy_action_evidence_pointer` with a produced V2 `RiskDecisionRecord` in `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py`, but the comparison record has only:

- `legacy_action_evidence_pointer`
- `v2_risk_decision_record`

It does not include legacy action, legacy symbol, legacy feature snapshot id, comparison status, divergence reason, or audit-event rows. The related explainability projection tests explicitly forbid `paper_shadow_legacy_comparison` and `audit_timeline` fields in the current envelopes, so there is no inspected audit surface for divergence output.

Impact: the system cannot yet prove or emit auditable divergence between legacy and V2 shadow decisions.

### Blocker 2 - Same-symbol same-snapshot comparison is not established against legacy evidence

The harness verifies V2 lineage carry-over from `OrchestratorDecisionRecord` into `RiskDecisionRecord`, including `decision_id`, `prediction_id`, `feature_snapshot_id`, and `symbol`. That is useful V2 internal lineage, but the legacy side is only an opaque pointer string. There is no typed legacy row carrying symbol/snapshot/action fields, and no assertion that the legacy row and V2 row are compared on the same symbol and same feature snapshot.

Impact: the review requirement for same-symbol same-snapshot legacy-vs-V2 comparison is not met.

### Passing Safety Evidence

- Shadow readiness flags always require `live_blocked=True` in `v2/backend/app/domain/shadow_mode_readiness/flag.py`.
- The service rejects `live_enabled`, `live`, uppercase, bool, and unknown requested states in `v2/backend/tests/unit/services/shadow_mode_readiness/`.
- The composition root has no Redis, HTTP, FastAPI, execution, paper ledger, replay, persistence, or live-trading dependency.
- The test-only shadow evidence harness drives V2 risk decisions and does not place orders, write Redis, restart services, change leverage/margin, or enable live trading.
- Legacy readonly audit states that shadow mode must compare legacy vs V2, but the inspected V2 implementation does not yet provide the required concrete comparison/audit surface.

## Proposed Non-Live Autofix Tasks

1. Add a test-only typed legacy comparison fixture under `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/` with fields for `legacy_symbol`, `legacy_feature_snapshot_id`, `legacy_action`, and `legacy_action_evidence_pointer`.
2. Extend the test-only `ShadowModeComparisonRecord` to include V2 symbol/snapshot/action, legacy symbol/snapshot/action, `comparison_status`, and `divergence_reason_code`, while preserving `live_blocked=True` and no execution side effects.
3. Add unit tests that reject or flag mismatched legacy/V2 symbol and mismatched legacy/V2 snapshot before any comparison is counted as ready.
4. Add a non-live divergence audit envelope in tests, emitted as deterministic in-memory records only, with no Redis, DB, file write, order, exchange, or service restart path.
5. Keep the production readiness flag surface unchanged unless a later milestone explicitly opens a real non-live shadow comparison package; do not add live-enable states or execution intents.

## Go/No-Go

CODEX_PARALLEL_REVIEW_BLOCKED
