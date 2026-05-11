# Codex Parallel Review: Orchestrator Decision MVP

Review date: 2026-05-11

Scope inspected:
- `v2/backend/app/domain/orchestrator_decision/`
- `v2/backend/app/services/orchestrator_decision/`
- `v2/backend/app/composition/orchestrator_decision/`
- adjacent risk gateway handoff code in `v2/backend/app/services/risk_gateway/` and `v2/backend/app/composition/risk_gateway/`
- `v2/backend/tests/unit/domain|services|composition/orchestrator_decision/`
- `v2/backend/tests/unit/domain|services|composition/risk_gateway/`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/`
- `claude_worklog/legacy_readonly_audit/`

## Verdict

READY.

No blocking issue was found for the Orchestrator Decision MVP scope. The implementation is pure, non-live, deterministic, Redis-clean, and hands off complete decision lineage to the risk gateway layer.

## Checks

### decision_id lineage

PASS.

- `v2/backend/app/services/orchestrator_decision/service.py:70-76` enforces the source `prediction_id` length cap and derives `decision_id = "dec_" + prediction.prediction_id`.
- `v2/backend/app/services/orchestrator_decision/service.py:105-117` propagates `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, input direction, calibrated confidence, freshness flag, worker health, and `live_blocked=True` into the frozen decision record.
- `v2/backend/app/domain/orchestrator_decision/record.py:73-204` enforces frozen value-object shape, identifier validation, allowed actions/reasons, input lineage fields, and `live_blocked is True`.
- Tests cover deterministic derivation and propagation: `test_assemble_decision_id_derived_from_prediction_id.py`, `test_assemble_propagates_input_lineage_fields.py`, and composition propagation tests.

### risk gateway handoff completeness

PASS.

- `v2/backend/app/services/risk_gateway/service.py:25-47` accepts only an `OrchestratorDecisionRecord`, validates its own clock, and caps derived risk ID length.
- `v2/backend/app/services/risk_gateway/service.py:49-60` maps `open_long`/`open_short` to allow decisions and maps `hold`/`abstain` to deny decisions.
- `v2/backend/app/services/risk_gateway/service.py:67-78` derives `risk_decision_id = "rd_" + decision.decision_id` and carries `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, input decision action/reason, and `live_blocked=True`.
- Risk gateway tests passed together with orchestrator tests.

### stale/duplicate signal handling

PASS for MVP scope.

- Stale and missing prediction freshness are explicit default-deny abstains: `service.py:77-82`, with tests for `abstain_freshness_missing`, `abstain_freshness_stale`, and priority over worker state.
- Duplicate handling in this MVP is deterministic/idempotent lineage, not stateful Redis/database dedupe: the same `prediction_id` always derives the same `decision_id`. This is consistent with the 2F specs, which reserve signal/provenance dedupe outside the orchestrator decision package.
- No Redis or mutable cache is introduced, so duplicate suppression is not implemented by hidden local state.

### legacy orchestrator behavior mapping

PASS.

- `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md` requires `decision_id` and default-deny stale/unsafe signals.
- The 2F docs map legacy gaps into an explicit abstain/hold/open taxonomy, with `live_blocked=True` and risk-gateway default-deny handoff.
- The implementation matches that mapping: missing/stale freshness, unhealthy/unknown worker status, and low confidence abstain before any directional open; flat becomes hold.

### no direct trade execution

PASS.

- Orchestrator decision source imports only domain constants/types, trainer prediction record, `Callable`, `math`, and local errors.
- Composition source only binds threshold/clock and forwards to the assembler.
- Token scan over orchestrator decision and risk gateway source/tests found no exchange/order execution APIs, no leverage/margin mutations, no Redis writes, and no live-trading enablement.
- `live_blocked=True` is literal in both orchestrator decision and risk gateway records.

## Validation Run

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider v2/backend/tests/unit/domain/orchestrator_decision v2/backend/tests/unit/services/orchestrator_decision v2/backend/tests/unit/composition/orchestrator_decision -q`
  - Result: `98 passed in 0.24s`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider v2/backend/tests/unit/domain/risk_gateway v2/backend/tests/unit/services/risk_gateway v2/backend/tests/unit/composition/risk_gateway -q`
  - Result: `85 passed in 0.21s`

## Blockers

None.

## Proposed non-live follow-up tasks

- Add an explicit non-live contract test documenting duplicate/idempotent behavior: two calls with the same `prediction_id` derive the same `decision_id` and perform no stateful dedupe.
- Add an integration-style non-live test for prediction -> orchestrator decision -> risk gateway lineage propagation across both evaluators.
