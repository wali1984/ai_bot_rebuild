# Codex Parallel Review - Orchestrator Decision MVP

Review timestamp: 2026-05-12

## Scope Reviewed

- `v2/backend/app/domain/orchestrator_decision/`
- `v2/backend/app/services/orchestrator_decision/`
- `v2/backend/app/composition/orchestrator_decision/`
- Relevant downstream handoff surfaces in `v2/backend/app/domain/risk_gateway/` and `v2/backend/app/services/risk_gateway/`
- Relevant dedupe surfaces in `v2/backend/app/domain/provenance_dedupe_attribution/` and `v2/backend/app/services/provenance_dedupe_attribution/`
- `v2/backend/tests/unit/domain/orchestrator_decision/`
- `v2/backend/tests/unit/services/orchestrator_decision/`
- `v2/backend/tests/unit/composition/orchestrator_decision/`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/`
- `claude_worklog/legacy_readonly_audit/`

No live service, Redis, order, leverage, margin, deployment, or live-trading action was performed. Tests were not run to preserve read-only review posture and avoid cache writes.

## Findings

### BLOCKER: duplicate signal handling is not implemented in the Orchestrator Decision MVP

The review checklist requires stale/duplicate signal handling. Stale prediction handling is covered, but duplicate signal handling is not implemented in the orchestrator decision MVP itself.

Evidence:

- `v2/backend/app/services/orchestrator_decision/service.py:76` derives `decision_id = "dec_" + prediction.prediction_id`.
- `v2/backend/app/services/orchestrator_decision/service.py:77-103` handles freshness, worker health, confidence, and direction, but has no signal identity, prior-decision input, idempotency key, dedupe state, or duplicate/stale-out-of-order branch.
- `v2/backend/app/domain/orchestrator_decision/record.py:75-86` stores `decision_id`, `prediction_id`, and `feature_snapshot_id`, but no `signal_id`, source sequence, stream id, duplicate marker, or stale-out-of-order marker.
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/01_PHASE_2F_LEGACY_EVIDENCE_REVIEW.md:24` explicitly reserves `signal_id` for an upstream signal layer and does not introduce it in 2F.
- `v2/backend/app/services/provenance_dedupe_attribution/dedupe_service.py:8-44` can assemble a `DedupeDecisionRecord`, but it requires a caller-supplied `dedupe_state` and does not compute duplicate/stale status for orchestrator decisions.

Impact:

- Reprocessing the same prediction yields the same deterministic `decision_id`, but the orchestrator MVP does not explicitly classify that condition as duplicate or block it at the decision stage.
- A duplicated upstream signal/prediction can still produce an `open_long` or `open_short` candidate decision before any later dedupe stage is applied.
- The checklist item "stale/duplicate signal handling" is therefore only partially satisfied.

Proposed non-live autofix tasks:

1. Add a pure, non-I/O orchestrator decision dedupe/idempotency adapter or pre-gate that accepts the current prediction identity plus prior decision identity state supplied by the caller and returns `new`, `duplicate_of_prior`, or `stale_out_of_order`.
2. Extend orchestrator decision assembly or composition with an injected duplicate/stale classifier result and force `decision_action="abstain"` with explicit reason codes for duplicate and stale-out-of-order inputs.
3. Add unit tests proving duplicate predictions and stale out-of-order inputs cannot produce `open_long` or `open_short`.
4. Keep the implementation non-live: no Redis reads/writes, no service restarts, no execution routing, no exchange calls.

## Passing Checks

### decision_id lineage

Lineage is deterministic and propagated:

- `v2/backend/app/services/orchestrator_decision/service.py:70-76` validates prediction id length and derives `decision_id`.
- `v2/backend/app/services/orchestrator_decision/service.py:105-118` propagates `prediction_id`, `feature_snapshot_id`, `symbol`, and input decision facts into `OrchestratorDecisionRecord`.
- `v2/backend/app/services/risk_gateway/service.py:67-78` derives `risk_decision_id="rd_" + decision.decision_id` and propagates `decision_id`, `prediction_id`, and `feature_snapshot_id`.

### risk gateway handoff completeness

The handoff shape is present:

- `v2/backend/app/domain/risk_gateway/record.py:56-68` captures `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, symbol, risk action, input decision action, input decision reason, and `live_blocked`.
- `v2/backend/app/services/risk_gateway/service.py:49-60` maps `open_long` and `open_short` to allow decisions, and `hold` and `abstain` to deny decisions.
- `v2/backend/app/domain/risk_gateway/record.py:70-135` validates lineage, input action/reason, and allow/deny consistency.

### stale signal handling

Stale and missing prediction freshness are handled fail-closed:

- `v2/backend/app/services/orchestrator_decision/service.py:77-82` maps missing and stale freshness to `abstain`.
- `v2/backend/app/domain/orchestrator_decision/record.py:146-151` validates freshness values.
- `v2/backend/app/services/risk_gateway/service.py:58-60` maps abstain decisions to risk deny.

### legacy orchestrator behavior mapping

The legacy audit only provides process-level behavior and safety impacts, not detailed decision code mapping:

- `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md:16-18` requires `decision_id` and risk default-deny for stale/unsafe signals.
- `claude_worklog/legacy_readonly_audit/09_V2_BUILD_IMPACT_MAP.md:11` maps orchestrator/trader process evidence to `decision_id`, `risk_decision_id`, and `execution_intent_id`.
- The current MVP covers decision and risk decision lineage, but not duplicate signal classification.

### no direct trade execution

No direct execution surface was found in the orchestrator decision MVP:

- `v2/backend/app/domain/orchestrator_decision/`, `v2/backend/app/services/orchestrator_decision/`, and `v2/backend/app/composition/orchestrator_decision/` contain no exchange adapter, order placement, execution router, trader, leverage, margin, Redis write, or live-mode call.
- `v2/backend/app/services/orchestrator_decision/service.py:105-118` constructs only a value object and always sets `live_blocked=True`.
- `v2/backend/app/domain/orchestrator_decision/record.py:159-164` rejects records where `live_blocked` is not exactly `True`.

## Verdict

CODEX_PARALLEL_REVIEW_BLOCKED
