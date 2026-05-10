# Codex Parallel Review: Orchestrator Decision MVP

Review date: 2026-05-10
Mode: read-only parallel review, except this report and GO/NO-GO artifact
Result: BLOCKED

## Scope inspected

- `v2/backend/app/domain/orchestrator_decision/`
- `v2/backend/app/services/orchestrator_decision/`
- `v2/backend/app/composition/orchestrator_decision/`
- Adjacent risk handoff and dedupe surfaces:
  - `v2/backend/app/services/risk_gateway/service.py`
  - `v2/backend/app/domain/risk_gateway/record.py`
  - `v2/backend/app/services/provenance_dedupe_attribution/dedupe_service.py`
  - `v2/backend/app/domain/trainer_prediction_output/record.py`
- Tests under `v2/backend/tests/unit/{domain,services,composition}/orchestrator_decision/`
- Planning/audit inputs under:
  - `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/`
  - `claude_worklog/legacy_readonly_audit/`

## Findings

### BLOCKER 1: Duplicate signal handling is absent before risk-gateway handoff

The orchestrator decision assembler consumes only `TrainerPredictionRecord`, which carries `prediction_id`, `feature_snapshot_id`, model/checkpoint metadata, direction, confidence, worker health, and freshness. It does not carry `signal_id`, upstream signal provenance, sequence number, stream id, dedupe state, or `duplicate_of_decision_id`.

Evidence:

- `v2/backend/app/domain/trainer_prediction_output/record.py:90-107` defines `TrainerPredictionRecord` without a signal/provenance/dedupe input field.
- `v2/backend/app/services/orchestrator_decision/service.py:34-39` accepts only `prediction`, `low_confidence_threshold`, and `now_ms_clock`.
- `v2/backend/app/services/orchestrator_decision/service.py:76-118` derives a decision without any duplicate check or duplicate abstain reason.
- `v2/backend/tests/unit/services/orchestrator_decision/` contains freshness and worker-health tests, but `rg` found no duplicate/dedupe coverage in the orchestrator decision test set.

Impact:

- Duplicate signals/predictions can still become `open_long` or `open_short` orchestrator decisions if they are fresh, healthy, and above threshold.
- The risk gateway then sees only an already-formed `OrchestratorDecisionRecord`; it has no duplicate context to deny on that basis.
- This does not satisfy the requested stale/duplicate signal handling check for this review topic.

Proposed non-live autofix tasks:

1. Add a pre-risk duplicate/default-deny contract to the orchestrator decision path: either extend the upstream prediction/provenance input with dedupe metadata or introduce a wrapper input that includes `dedupe_state` and `duplicate_of_decision_id`.
2. Add explicit orchestrator decision reason constants such as `abstain_duplicate_signal` and `abstain_stale_out_of_order_signal`, then map duplicate/stale-out-of-order states to `DECISION_ACTION_ABSTAIN`.
3. Add unit tests proving duplicate and stale-out-of-order inputs cannot produce `open_long` or `open_short`.
4. Add risk-gateway tests proving duplicate-derived abstain decisions are denied and preserve `decision_id` lineage.

### BLOCKER 2: Existing dedupe service is downstream of risk decisions, not a pre-risk duplicate gate

`assemble_dedupe_decision_record(...)` requires a `RiskDecisionRecord` as `upstream_record`, so it cannot prevent a duplicate candidate from reaching risk-gateway allow/deny derivation.

Evidence:

- `v2/backend/app/services/provenance_dedupe_attribution/dedupe_service.py:9-20` takes `upstream_record: RiskDecisionRecord`.
- `v2/backend/app/services/provenance_dedupe_attribution/dedupe_service.py:28-46` records dedupe after risk lineage already exists.
- `v2/backend/app/services/risk_gateway/service.py:49-54` allows `open_long` and `open_short` orchestrator decisions without a duplicate/provenance condition.

Impact:

- A duplicate open decision can be marked `allow` by the risk gateway before dedupe attribution is assembled.
- The current ordering is unsuitable if duplicate handling is intended as a risk-gateway handoff precondition.

Proposed non-live autofix tasks:

1. Move duplicate classification before `assemble_risk_decision_record(...)`, or add a risk-gateway input that carries a precomputed dedupe decision.
2. Ensure duplicate decisions default-deny before any risk action can be `allow`.
3. Add a non-live integration test for `prediction -> orchestrator decision -> risk decision` where duplicate input remains denied.

## Passing Checks

### decision_id lineage

PASS with caveat. Orchestrator decision lineage is deterministic and preserved for prediction and feature snapshot lineage.

Evidence:

- `v2/backend/app/services/orchestrator_decision/service.py:70-76` caps `prediction_id` and derives `decision_id = "dec_" + prediction.prediction_id`.
- `v2/backend/app/services/orchestrator_decision/service.py:105-118` propagates `prediction_id`, `feature_snapshot_id`, `symbol`, prediction direction/confidence/freshness, worker health, and `live_blocked=True`.
- `v2/backend/app/services/risk_gateway/service.py:67-79` derives `risk_decision_id="rd_" + decision.decision_id` and propagates `decision_id`, `prediction_id`, `feature_snapshot_id`, and `symbol`.

Caveat:

- There is no `signal_id` in this MVP surface. The Phase 2F legacy review explicitly reserves `signal_id` for an upstream layer, but duplicate signal handling cannot be verified without an equivalent provenance key.

### risk gateway handoff completeness

PARTIAL PASS. The type-level handoff from orchestrator decision to risk gateway exists and carries the necessary lineage and action/reason fields, but it does not carry duplicate/provenance context.

Evidence:

- `v2/backend/app/services/risk_gateway/service.py:25-29` consumes `OrchestratorDecisionRecord`.
- `v2/backend/app/services/risk_gateway/service.py:49-60` maps `open_long/open_short` to allow and `hold/abstain` to deny.
- `v2/backend/app/domain/risk_gateway/record.py` validates input decision action/reason and `live_blocked=True`.

### stale signal handling

PASS for freshness stale/missing prediction inputs.

Evidence:

- `v2/backend/app/services/orchestrator_decision/service.py:77-82` maps `freshness_flag == missing` and `freshness_flag == stale` to abstain before worker health, confidence, or direction branches.
- Tests include `test_assemble_abstain_freshness_stale.py`, `test_assemble_abstain_freshness_missing.py`, and freshness priority tests.

### legacy orchestrator behavior mapping

PARTIAL PASS. The mapping is constrained by sparse legacy evidence.

Evidence:

- `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md:13-17` requires `decision_id`, risk default-deny for stale/unsafe signals, paper ledger coverage, and shadow-mode comparison.
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/01_PHASE_2F_LEGACY_EVIDENCE_REVIEW.md:15-26` states the legacy runtime audit files were stubs and Phase 2F derives behavior from `TrainerPredictionRecord`, lineage requirements, default-deny posture, freshness, and worker health.

The implemented MVP covers the documented decision id and stale/unsafe defaults but does not cover duplicate signal behavior.

### no direct trade execution

PASS.

Evidence:

- Orchestrator decision domain/service/composition files contain no exchange adapter imports, execution router calls, order placement calls, Redis writes, FastAPI registration, or live service lifecycle hooks.
- `v2/backend/app/services/execution_router.py` remains a placeholder with live order calls documented as blocked until a later milestone.
- `live_blocked` is required to be `True` in `OrchestratorDecisionRecord` and is constructed as literal `True` by the assembler.

## Verification Notes

I did not run pytest in this read-only review mode to avoid writing cache or bytecode artifacts. Review evidence is from source and test inspection using read-only shell commands.

## Go/No-Go

CODEX_PARALLEL_REVIEW_BLOCKED
