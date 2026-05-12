# Codex Parallel Review: Orchestrator Decision MVP

Generated: 2026-05-12

Scope: read-only inspection of `v2/backend/app`, `v2/backend/tests`, `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl`, and `claude_worklog/legacy_readonly_audit`.

Verdict: BLOCKED

## Findings

### Blocker 1 - Duplicate/out-of-order decisions are not fail-closed before risk allow

The orchestrator decision assembler derives `decision_id = "dec_" + prediction.prediction_id` and maps fresh, healthy, sufficiently confident `long`/`short` predictions directly to `open_long`/`open_short` (`v2/backend/app/services/orchestrator_decision/service.py:76-103`). The risk gateway then maps `open_long` and `open_short` to `allow` (`v2/backend/app/services/risk_gateway/service.py:49-54`).

The only dedupe/out-of-order model found is `DedupeDecisionRecord`, but its service takes an already assembled `RiskDecisionRecord` as `upstream_record` (`v2/backend/app/services/provenance_dedupe_attribution/dedupe_service.py:9-46`). That means duplicate or stale-out-of-order decisions can be labeled after a risk decision has already allowed the action. This does not satisfy the review check for stale/duplicate signal handling at the orchestrator/risk handoff boundary.

Concrete risk: a repeated fresh `prediction_id` or out-of-order signal that still passes freshness/health/confidence can produce the same `decision_id`, then a risk decision with `risk_action="allow"` before dedupe state is consulted.

Proposed non-live autofix task:
- Add a pre-risk, pure dedupe gate for orchestrator decisions that accepts the candidate `OrchestratorDecisionRecord` plus read-only prior-decision metadata supplied by the caller, and emits a fail-closed decision/gate record for `DEDUPE_DUPLICATE_OF_PRIOR` and `DEDUPE_STALE_OUT_OF_ORDER`.
- Wire the non-live composition/test harness so the risk gateway only receives decisions that passed the dedupe gate, or extend `RiskDecisionRecord` assembly to accept dedupe state and deny duplicates/out-of-order inputs.
- Add unit tests proving duplicate and stale-out-of-order open-long/open-short candidates cannot produce `risk_action="allow"`.

## Checks

decision_id lineage: PASS with caveat. `OrchestratorDecisionRecord` carries `decision_id`, `prediction_id`, and `feature_snapshot_id` (`v2/backend/app/domain/orchestrator_decision/record.py:73-86`). The service derives `decision_id` deterministically from `prediction_id` and propagates lineage fields into the risk gateway (`v2/backend/app/services/risk_gateway/service.py:67-78`).

risk gateway handoff completeness: PARTIAL. Handoff fields are complete for the current record shape, and stale/missing/worker/low-confidence abstains become risk denies. The handoff is incomplete for duplicate/out-of-order gating because dedupe occurs after risk decision assembly.

stale signal handling: PASS. `missing` and `stale` freshness are prioritized before worker health, confidence, and direction, and become `abstain_freshness_missing` / `abstain_freshness_stale` (`v2/backend/app/services/orchestrator_decision/service.py:77-82`).

duplicate signal handling: BLOCKED. No duplicate input, prior decision, signal id, or out-of-order gate is part of the orchestrator decision or risk gateway input path. Existing tests only cover stale freshness in orchestrator/risk suites; duplicate tests are confined to the later provenance/dedupe attribution model.

legacy orchestrator behavior mapping: PARTIAL. Legacy read-only evidence requires `decision_id`, risk gateway default-deny for stale/unsafe signals, paper ledger capture, and shadow comparison (`claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md:15-19`). The MVP covers decision IDs and stale abstain, but duplicate/out-of-order pre-risk blocking is not mapped.

no direct trade execution: PASS. The orchestrator decision package is pure assembly/composition and does not import exchange/order execution surfaces. `v2/backend/app/services/execution_router.py` remains a placeholder stating live order calls are blocked.

## Validation

No tests were run to preserve the requested read-only posture and avoid cache writes. Review evidence is from source and test inspection only.
