# Shadow Mode Readiness Parallel Review

Review timestamp: 2026-05-08T17:43:23-04:00

Verdict: BLOCKED for full shadow-mode readiness.

## Scope Inspected

- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl`
- `claude_worklog/legacy_readonly_audit`

No live service, Redis key, exchange order, leverage, margin, deployment, or `/home/wali/Desktop/AI BOT` mutation was performed.

## Findings

### BLOCKER 1 - No app-level legacy-vs-V2 shadow comparison surface

The legacy audit explicitly requires shadow mode to compare legacy vs V2 (`claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md:18`). The implemented Phase 2K work intentionally stops at a typed readiness flag and states that it does not introduce a shadow-decision record or execution/comparison surface (`claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/01_PHASE_2K_LEGACY_EVIDENCE_REVIEW.md:47`, `:51`). The actual app implementation matches that limited scope: `v2/backend/app/services/shadow_mode_readiness/service.py:98` only assembles `ShadowModeReadinessFlag`, and `v2/backend/app/composition/shadow_mode_readiness/runtime.py:161` only binds a clocked `shadow_mode_readiness_now` closure.

There is a unit harness under `v2/backend/tests/unit/shadow_mode_evidence_collection_harness/`, but it is test-only and pairs a legacy evidence pointer string with a V2 `RiskDecisionRecord`; it is not an app service, domain contract, persisted audit event, or runtime comparator (`v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py:21-76`).

Required non-live autofix task: add a pure, offline `shadow_comparison` domain/service package that accepts typed legacy decision evidence and V2 decision/risk records, emits immutable comparison records, and remains free of Redis, HTTP, exchange, scheduler, execution, and live-mode dependencies.

### BLOCKER 2 - Same-symbol same-snapshot comparison is not enforceable

Current V2 records carry lineage fields (`symbol`, `feature_snapshot_id`, `decision_id`, `prediction_id`) and preserve them through orchestrator and risk surfaces (`v2/backend/app/domain/orchestrator_decision/record.py:73-86`, `v2/backend/app/services/risk_gateway/service.py:607-618`). However, the shadow evidence harness only stores `legacy_action_evidence_pointer: str` next to the V2 record (`v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py:21-25`). The legacy side has no typed `symbol`, `feature_snapshot_id`, snapshot timestamp, or source snapshot identity to validate same-symbol/same-snapshot matching.

The tests assert that V2 risk lineage matches the V2 input decision (`v2/backend/tests/unit/shadow_mode_evidence_collection_harness/test_shadow_mode_evidence_collection_harness.py:391-407`), but they do not prove that the legacy decision and V2 decision were evaluated on the same symbol and same snapshot.

Required non-live autofix task: introduce a typed `LegacyDecisionEvidenceRecord` fixture/domain object with `symbol`, `feature_snapshot_id` or legacy snapshot id, observation timestamp, legacy action, and evidence pointer; reject comparisons unless legacy and V2 symbol plus snapshot lineage match exactly.

### BLOCKER 3 - No divergence audit output

The audit area exists as general scaffold (`v2/backend/app/api/v1/audit.py`, `v2/backend/app/domain/governance/audit_chain.py`, `v2/backend/app/adapters/db/repositories/audit_events.py`), but the inspected app code has no shadow divergence event type, divergence summary, or append-only offline output for legacy-vs-V2 mismatches. The existing shadow harness computes projected V2 risk actions but does not classify `match`, `divergent_action`, `divergent_reason`, missing legacy evidence, or missing V2 evidence (`v2/backend/tests/unit/shadow_mode_evidence_collection_harness/harness.py:57-76`).

Required non-live autofix task: add an offline divergence audit writer/test harness that serializes comparison outputs to a local test artifact or in-memory append-only record list, with fields for legacy action/reason, V2 action/reason, symbol, snapshot ids, divergence code, and `live_blocked=True`. Do not write Redis or live audit sinks.

### BLOCKER 4 - Readiness flag can say ready without verifying upstream comparison prerequisites

`assemble_shadow_mode_readiness_flag` accepts `requested_state="ready"` and returns a flag with `live_blocked=True` after only validating the requested string and clock (`v2/backend/app/services/shadow_mode_readiness/service.py:98-133`). It does not check that comparison inputs exist, that legacy evidence is typed, that same-symbol/same-snapshot validation passed, or that divergence audit output is configured. The Phase 2K docs describe this as a precondition flag, not a complete readiness gate (`claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/00_PHASE_2K_SUB_PHASE_BREAKDOWN.md:3`, `:56`).

Required non-live autofix task: add a separate offline readiness evaluator that derives `ready` only from pure in-memory prerequisite booleans: typed legacy evidence present, V2 records present, same-symbol/same-snapshot validator passing, divergence audit sink available, and live gate blocked.

## Safety Checks

- Shadow readiness flag does not affect live execution: `ShadowModeReadinessFlag` requires `live_blocked is True` (`v2/backend/app/domain/shadow_mode_readiness/flag.py:14-55`), and the service always emits `live_blocked=True` (`v2/backend/app/services/shadow_mode_readiness/service.py:129-133`).
- Orchestrator and risk records also require or emit `live_blocked=True` (`v2/backend/app/domain/orchestrator_decision/record.py:159-164`, `v2/backend/app/services/orchestrator_decision/service.py:309-322`, `v2/backend/app/domain/risk_gateway/record.py:536-540`, `v2/backend/app/services/risk_gateway/service.py:607-618`).
- `/api/v1/live` remains scaffold-blocked/default-deny: `v2/backend/app/api/v1/live_mode.py:1-25` documents default deny and `v2/backend/app/api/middleware/live_block_guard.py` is the blocking middleware referenced by app wiring.
- The live-readiness state machine, kill switch, and risk phases are placeholders only (`v2/backend/app/domain/risk/live_readiness_state.py`, `v2/backend/app/domain/risk/kill_switch.py`, `v2/backend/app/domain/risk/phases.py`).

## Proposed Non-Live Autofix Plan

1. Add typed legacy evidence records in tests and pure domain code; no Redis, files, HTTP, exchange, or live service access.
2. Add a pure comparator service that enforces same `symbol` and same snapshot lineage before comparing legacy and V2 actions/reasons.
3. Add divergence classification and an offline audit projection object with deterministic IDs and `live_blocked=True`.
4. Add tests for matched comparison, divergent action, divergent reason, mismatched symbol rejection, mismatched snapshot rejection, missing legacy evidence rejection, missing V2 evidence rejection, and live-gate-blocked invariant.
5. Keep `/live` default-deny untouched and avoid adding any router, scheduler, order placement, cancellation, leverage, margin, or deployment path.

CODEX_PARALLEL_REVIEW_BLOCKED
