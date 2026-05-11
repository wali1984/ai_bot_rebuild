# Codex Parallel Review: Orchestrator Decision MVP

Review date: 2026-05-11
Mode: read-only parallel review, except this report and GO/NO-GO artifact
Result: BLOCKED

## Scope inspected

- `v2/backend/app/domain/orchestrator_decision/`
- `v2/backend/app/services/orchestrator_decision/`
- `v2/backend/app/composition/orchestrator_decision/`
- Adjacent handoff surfaces:
  - `v2/backend/app/domain/risk_gateway/`
  - `v2/backend/app/services/risk_gateway/`
  - `v2/backend/app/composition/risk_gateway/`
  - `v2/backend/app/domain/provenance_dedupe_attribution/`
  - `v2/backend/app/services/provenance_dedupe_attribution/`
- `v2/backend/tests/unit/{domain,services,composition}/orchestrator_decision/`
- `v2/backend/tests/unit/{domain,services,composition}/risk_gateway/`
- `v2/backend/tests/unit/{domain,services}/provenance_dedupe_attribution/`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/`
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/`
- `claude_worklog/legacy_readonly_audit/`

## Findings

### BLOCKER 1: Duplicate signal handling is not available before risk-gateway allow/deny derivation

The orchestrator decision assembler accepts only a `TrainerPredictionRecord`, a low-confidence threshold, and a clock. It has no input for `signal_id`, dedupe state, `duplicate_of_decision_id`, stream sequence, source timestamp ordering, or upstream provenance. As a result, duplicate inputs that are otherwise fresh, healthy, confident, and directional can still become `open_long` or `open_short` candidate decisions.

Evidence:

- `v2/backend/app/services/orchestrator_decision/service.py:34-39` defines the service input as `prediction`, `low_confidence_threshold`, and `now_ms_clock` only.
- `v2/backend/app/services/orchestrator_decision/service.py:76-103` derives `decision_id` and then maps freshness, worker health, confidence, and direction, with no duplicate or stale-out-of-order branch.
- `v2/backend/app/services/orchestrator_decision/service.py:105-118` constructs the decision record without any duplicate/provenance field.
- `v2/backend/app/domain/orchestrator_decision/record.py:73-86` defines the value object fields; it carries prediction lineage and safety inputs but no dedupe context.
- `v2/backend/tests/unit/services/orchestrator_decision/` covers stale/missing freshness, worker health, confidence, and lineage propagation, but the source/test inspection found no orchestrator duplicate-default-deny coverage.

Impact:

- Duplicate candidate decisions can reach `assemble_risk_decision_record(...)` as ordinary `open_long` or `open_short` decisions.
- The risk gateway cannot deny duplicates because the `OrchestratorDecisionRecord` handoff does not carry duplicate context.
- This does not satisfy the requested stale/duplicate signal handling check for the risk handoff path.

Proposed non-live autofix tasks:

1. Add a pre-risk duplicate classification contract, either by extending the orchestrator input with immutable dedupe metadata or by introducing a small pre-risk wrapper record that carries `dedupe_state`, `duplicate_of_decision_id`, and stale-out-of-order context.
2. Add orchestrator decision reason constants for duplicate/stale-out-of-order default-deny cases, for example `abstain_duplicate_signal` and `abstain_stale_out_of_order_signal`.
3. Update the assembler so duplicate and stale-out-of-order states map to `abstain` before directional `open_long`/`open_short`.
4. Add non-live unit tests proving duplicate and stale-out-of-order inputs cannot produce candidate open decisions.

### BLOCKER 2: Existing provenance/dedupe attribution is downstream of the risk decision

The current dedupe service models duplicate attribution from a `RiskDecisionRecord`, so it records dedupe after the risk gateway has already mapped open-long/open-short decisions to `allow`.

Evidence:

- `v2/backend/app/services/provenance_dedupe_attribution/dedupe_service.py:9-20` requires `upstream_record: RiskDecisionRecord`.
- `v2/backend/app/services/provenance_dedupe_attribution/dedupe_service.py:27-46` mirrors `decision_id`, `prediction_id`, `feature_snapshot_id`, and `risk_decision_id` from an already-created risk decision.
- `v2/backend/app/services/risk_gateway/service.py:49-54` maps `open_long` and `open_short` to risk `allow` without any duplicate/provenance condition.
- `v2/backend/app/services/risk_gateway/service.py:67-78` emits `RiskDecisionRecord` with lineage but no dedupe state.

Impact:

- Dedupe attribution can explain duplicate status after the fact, but it cannot prevent a duplicate candidate decision from being marked risk-allowed.
- If duplicate handling is intended as a pre-live safety gate, the current ordering is too late.

Proposed non-live autofix tasks:

1. Move dedupe classification before `assemble_risk_decision_record(...)`, or add a risk-gateway input that includes a precomputed dedupe decision.
2. Extend risk-gateway default-deny mapping so duplicate/stale-out-of-order inputs always produce `deny_*` decisions.
3. Add a non-live integration-style test for prediction -> orchestrator decision -> risk gateway where duplicate input remains denied and preserves `decision_id`, `prediction_id`, and `feature_snapshot_id`.

## Passing checks

### decision_id lineage

PASS.

- `v2/backend/app/services/orchestrator_decision/service.py:70-76` caps `prediction_id` before deriving `decision_id = "dec_" + prediction.prediction_id`.
- `v2/backend/app/services/orchestrator_decision/service.py:105-118` propagates `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, input direction, calibrated confidence, freshness flag, worker health, and `live_blocked=True`.
- `v2/backend/app/domain/orchestrator_decision/record.py:73-204` freezes the value object and validates identifiers, timestamp, action/reason consistency, input lineage fields, and `live_blocked is True`.
- `v2/backend/app/services/risk_gateway/service.py:67-78` derives `risk_decision_id = "rd_" + decision.decision_id` and carries `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, input decision action/reason, and `live_blocked=True`.

### risk gateway handoff completeness

PARTIAL PASS.

The basic MVP handoff is complete for decision lineage and action/reason mapping, but incomplete for duplicate-signal default-deny context.

- `v2/backend/app/services/risk_gateway/service.py:25-29` accepts an `OrchestratorDecisionRecord`.
- `v2/backend/app/services/risk_gateway/service.py:49-60` maps `open_long`/`open_short` to `allow`, and `hold`/`abstain` to `deny`.
- `v2/backend/app/domain/risk_gateway/record.py:56-218` enforces lineage, action/reason, input decision, and `live_blocked=True` invariants.

### stale signal handling

PASS.

- `v2/backend/app/services/orchestrator_decision/service.py:77-82` maps missing and stale prediction freshness to `abstain_freshness_missing` and `abstain_freshness_stale` before worker health, confidence, or directional open checks.
- `v2/backend/app/services/orchestrator_decision/service.py:83-94` then fails closed for critical/degraded/unknown worker health and low confidence before any open decision.
- The test suite includes stale/missing freshness and priority coverage under `v2/backend/tests/unit/services/orchestrator_decision/`.

### legacy orchestrator behavior mapping

PARTIAL PASS.

- `claude_worklog/legacy_readonly_audit/04_SERVICE_DEPENDENCY_GRAPH.md:29-33` identifies separate legacy orchestrator and trader processes.
- `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md:13-17` requires decisions to include `decision_id` and requires risk gateway default-deny for stale/unsafe signals.
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/01_PHASE_2F_LEGACY_EVIDENCE_REVIEW.md:21-26` states Phase 2F maps behavior from the trainer prediction contract, lineage IDs, default-deny posture, freshness taxonomy, and worker-health taxonomy because legacy orchestrator audit payload was sparse.
- The implementation maps freshness, worker health, confidence, flat, long, and short as documented. Duplicate signal behavior remains unmapped before risk gateway handoff.

### no direct trade execution

PASS.

- Token scan over orchestrator decision and risk gateway source found no exchange/order APIs, leverage/margin mutation calls, Redis writes, live-trading enablement, service restart, or deployment surface.
- `v2/backend/app/services/orchestrator_decision/service.py` imports only pure domain/trainer types and constants, `Callable`, `math`, and local errors.
- `v2/backend/app/composition/orchestrator_decision/runtime.py` only validates/captures threshold and clock and delegates to the assembler.
- Both `OrchestratorDecisionRecord` and `RiskDecisionRecord` enforce `live_blocked=True`.

## Verification notes

I did not run pytest in this read-only review mode to avoid creating cache or bytecode artifacts. Evidence comes from source, test, and worklog inspection with read-only shell commands. I did not modify `/home/wali/Desktop/AI BOT`, write Redis, delete Redis keys, restart services, place/cancel orders, change leverage/margin, enable live trading, deploy, or expose secrets.

## Go/No-Go

CODEX_PARALLEL_REVIEW_BLOCKED
