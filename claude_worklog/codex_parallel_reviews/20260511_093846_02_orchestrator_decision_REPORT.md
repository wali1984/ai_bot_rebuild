# Codex Parallel Review: Orchestrator Decision MVP

Review date: 2026-05-11

Scope inspected:
- `v2/backend/app/domain/orchestrator_decision/`
- `v2/backend/app/services/orchestrator_decision/`
- `v2/backend/app/composition/orchestrator_decision/`
- adjacent risk gateway handoff code in `v2/backend/app/services/risk_gateway/` and `v2/backend/app/composition/risk_gateway/`
- `v2/backend/app/domain/provenance_dedupe_attribution/` and `v2/backend/app/services/provenance_dedupe_attribution/` for duplicate-signal attribution boundary
- `v2/backend/tests/unit/domain/orchestrator_decision/`
- `v2/backend/tests/unit/services/orchestrator_decision/`
- `v2/backend/tests/unit/composition/orchestrator_decision/`
- `v2/backend/tests/unit/services/risk_gateway/`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/`
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/`
- `claude_worklog/legacy_readonly_audit/`

## Verdict

READY.

No blocking issue was found for the Orchestrator Decision MVP scope. The implementation is pure, deterministic, non-live, Redis-clean, and hands complete MVP decision lineage to the risk gateway layer. Duplicate signal suppression is not implemented inside the orchestrator decision package, but the inspected design keeps duplicate attribution in the later provenance/dedupe layer and the orchestrator remains idempotent by deterministic `decision_id` derivation.

## Checks

### decision_id lineage

PASS.

- `v2/backend/app/services/orchestrator_decision/service.py:70-76` enforces the source `prediction_id` length cap before deriving `decision_id = "dec_" + prediction.prediction_id`.
- `v2/backend/app/services/orchestrator_decision/service.py:105-118` propagates `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, input direction, calibrated confidence, freshness flag, worker health, and literal `live_blocked=True`.
- `v2/backend/app/domain/orchestrator_decision/record.py:73-204` freezes the value object and enforces identifier, timestamp, action/reason, input lineage, and `live_blocked is True` invariants.
- Unit coverage includes deterministic derivation and propagation in `test_assemble_decision_id_derived_from_prediction_id.py` and `test_assemble_propagates_input_lineage_fields.py`.

### risk gateway handoff completeness

PASS.

- `v2/backend/app/services/risk_gateway/service.py:25-47` accepts only an `OrchestratorDecisionRecord`, validates the clock, and caps `decision_id` for safe `risk_decision_id` derivation.
- `v2/backend/app/services/risk_gateway/service.py:49-60` maps `open_long` and `open_short` to allow decisions, while `hold` and `abstain` become deny decisions.
- `v2/backend/app/services/risk_gateway/service.py:67-78` derives `risk_decision_id = "rd_" + decision.decision_id` and carries `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, input decision action/reason, and literal `live_blocked=True`.
- `v2/backend/app/domain/risk_gateway/record.py:56-218` enforces the downstream lineage and action/reason cross-field invariants.

### stale/duplicate signal handling

PASS for MVP scope.

- Stale and missing prediction freshness fail closed at orchestrator assembly: `v2/backend/app/services/orchestrator_decision/service.py:77-82` emits `abstain_freshness_missing` before `abstain_freshness_stale`.
- Worker-health and low-confidence checks run before any directional open at `v2/backend/app/services/orchestrator_decision/service.py:83-94`.
- Duplicate handling is deterministic/idempotent at this layer: the same `prediction_id` produces the same `decision_id`, and no Redis/cache/database state is introduced.
- Explicit duplicate attribution is modeled outside this MVP in `v2/backend/app/domain/provenance_dedupe_attribution/dedupe_decision_record.py:15-20` with `DEDUPE_NEW`, `DEDUPE_DUPLICATE_OF_PRIOR`, and `DEDUPE_STALE_OUT_OF_ORDER`; `v2/backend/app/services/provenance_dedupe_attribution/dedupe_service.py:9-55` mirrors `decision_id`, `prediction_id`, `feature_snapshot_id`, and `risk_decision_id` from the risk decision.

### legacy orchestrator behavior mapping

PASS.

- `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md` requires decisions to include `decision_id` and risk gateway default-deny for stale/unsafe signals.
- `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` records the LAB hedge unwind failure as a risk/trading failure requiring stronger risk checks, not direct orchestrator execution.
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/00_PHASE_2F_SUB_PHASE_BREAKDOWN.md` scopes the MVP to an orchestrator decision surface feeding risk gateway, explicitly excluding execution, risk subsystem expansion, FastAPI, and strategy-library behavior.
- The implementation maps missing/stale freshness, unhealthy/unknown worker state, and low confidence to `abstain`; flat to `hold`; and eligible long/short predictions to candidate open decisions for risk-gateway review.

### no direct trade execution

PASS.

- Token scan over `v2/backend/app/domain/orchestrator_decision`, `v2/backend/app/services/orchestrator_decision`, `v2/backend/app/composition/orchestrator_decision`, `v2/backend/app/services/risk_gateway`, and `v2/backend/app/composition/risk_gateway` found no exchange/order execution APIs, leverage/margin mutation, Redis writes, or live-trading enablement.
- Orchestrator decision service imports only pure domain types/constants, trainer prediction record types/constants, `Callable`, `math`, and local errors.
- Risk gateway service constructs a frozen decision record only; it does not place or route orders.
- Both orchestrator and risk gateway records force `live_blocked=True`.

## Validation Run

- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/orchestrator_decision v2/backend/tests/unit/services/orchestrator_decision v2/backend/tests/unit/composition/orchestrator_decision v2/backend/tests/unit/services/risk_gateway -q`
  - Result: `127 passed in 0.32s`

## Blockers

None.

## Proposed Non-Live Autofix Tasks

- Add an explicit non-live duplicate/idempotency contract test proving two calls with the same `prediction_id` derive the same `decision_id` and perform no stateful dedupe.
- Add an integration-style non-live test for prediction -> orchestrator decision -> risk gateway lineage propagation across both evaluators.
- Add a boundary test documenting that duplicate-signal attribution remains in provenance/dedupe and is not silently handled by orchestrator-local mutable state.
