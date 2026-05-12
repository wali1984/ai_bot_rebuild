# Codex Parallel Review - Orchestrator Decision MVP

Review timestamp: 2026-05-12 16:31:46 America/New_York

Scope inspected:
- `v2/backend/app/domain/orchestrator_decision/`
- `v2/backend/app/services/orchestrator_decision/`
- `v2/backend/app/composition/orchestrator_decision/`
- Related risk gateway and provenance/dedupe source and tests under `v2/backend/app` and `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/`
- `claude_worklog/legacy_readonly_audit/`

Verdict: READY

## Findings

No blocking defect found for the Orchestrator Decision MVP as specified in Phase 2F.

## Check Results

### decision_id lineage

PASS. The assembler derives `decision_id` deterministically as `dec_` plus `prediction.prediction_id`, after enforcing the 124-character input cap that keeps the derived ID inside the 128-character domain limit. Evidence: `v2/backend/app/services/orchestrator_decision/service.py:70-76`.

PASS. The returned `OrchestratorDecisionRecord` carries the upstream `prediction_id`, `feature_snapshot_id`, `symbol`, prediction direction, calibrated confidence, freshness flag, and worker health status without transformation. Evidence: `v2/backend/app/services/orchestrator_decision/service.py:105-117`.

PASS. The domain object validates non-empty, whitespace-free IDs for `decision_id`, `prediction_id`, and `feature_snapshot_id`, and enforces upper-case symbol and valid timestamp/action/reason fields. Evidence: `v2/backend/app/domain/orchestrator_decision/record.py:88-164`.

### risk gateway handoff completeness

PASS. The risk gateway accepts only an `OrchestratorDecisionRecord`, derives `risk_decision_id` as `rd_` plus the orchestrator `decision_id`, and mirrors `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, input decision action, and input decision reason. Evidence: `v2/backend/app/services/risk_gateway/service.py:25-79`.

PASS. Orchestrator abstain and hold decisions become risk denies, while open-long and open-short candidates become risk allows for the next non-live/paper layer. Evidence: `v2/backend/app/services/risk_gateway/service.py:49-60`.

PASS. Both orchestrator and risk records force `live_blocked=True`. Evidence: `v2/backend/app/services/orchestrator_decision/service.py:117`, `v2/backend/app/domain/orchestrator_decision/record.py:159-164`, and `v2/backend/app/services/risk_gateway/service.py:78`.

### stale/duplicate signal handling

PASS for stale and missing freshness. The orchestrator derivation table gives freshness the first priority: `missing` becomes `abstain_freshness_missing`; `stale` becomes `abstain_freshness_stale`; both happen before worker health, confidence, or direction can produce an open candidate. Evidence: `v2/backend/app/services/orchestrator_decision/service.py:77-82`.

PASS for domain representation of freshness. `OrchestratorDecisionRecord` accepts only `fresh`, `stale`, or `missing` as the input prediction freshness flag and rejects unknown values. Evidence: `v2/backend/app/domain/orchestrator_decision/record.py:44-47` and `v2/backend/app/domain/orchestrator_decision/record.py:146-157`.

NON-BLOCKING SCOPE NOTE for duplicate signals. Phase 2F does not model `signal_id`, duplicate classification, or out-of-order source ordering inside the orchestrator decision record. The Phase 2F legacy evidence review explicitly reserves `signal_id` for an upstream signal layer rather than introducing it in 2F. The later provenance/dedupe layer has `DEDUPE_NEW`, `DEDUPE_DUPLICATE_OF_PRIOR`, and `DEDUPE_STALE_OUT_OF_ORDER` records that mirror `decision_id`, `prediction_id`, `feature_snapshot_id`, and `risk_decision_id`; this is attribution/classification, not a pre-risk orchestrator gate. Evidence: `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/01_PHASE_2F_LEGACY_EVIDENCE_REVIEW.md` and `v2/backend/app/domain/provenance_dedupe_attribution/dedupe_decision_record.py`.

Recommended non-live follow-up, if pre-risk duplicate blocking is now required: add a new pure pre-risk dedupe gate or extend the orchestrator input contract with an explicit duplicate/out-of-order classification, then test duplicate inputs produce `abstain_*`/deny behavior before paper ledger projection. Do not implement this as a live Redis lookup or live service side effect.

### legacy orchestrator behavior mapping

PASS. Legacy read-only evidence identifies a running `rl.orchestrator_worker` and `trading/trader.py`, and the required V2 impact states that decisions must include `decision_id` and the risk gateway must default-deny stale/unsafe signals. Evidence: `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md:7-18`.

PASS with documented limitation. The Phase 2F legacy evidence review records that earlier legacy runtime audit files were read-only stubs with no concrete decision-behavior payload, so 2F intentionally mapped behavior from the validated trainer prediction output contract and REQ_0017 default-deny posture. Evidence: `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/01_PHASE_2F_LEGACY_EVIDENCE_REVIEW.md`.

### no direct trade execution

PASS. The orchestrator domain, service, and composition packages are pure value/assembler/binder surfaces. Static scan found no implementation references to exchange order calls, leverage/margin mutation, Redis clients, HTTP clients, FastAPI registration, paper execution ledger, or legacy trader paths in the orchestrator implementation packages. Matches in the scan were limited to test names and constructed forbidden-token test lists.

PASS. The orchestrator assembler returns only `OrchestratorDecisionRecord`; the composition root only forwards to the assembler; neither imports an execution router, adapter, exchange client, Redis, or HTTP client.

## Validation

Targeted tests passed:

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/home/wali/Desktop/AI\ BOT\ REBUILD ./.venv/bin/pytest -q -p no:cacheprovider v2/backend/tests/unit/domain/orchestrator_decision v2/backend/tests/unit/services/orchestrator_decision v2/backend/tests/unit/composition/orchestrator_decision v2/backend/tests/unit/services/risk_gateway v2/backend/tests/unit/composition/risk_gateway`

Result: `151 passed in 0.45s`.

Note: an initial direct `pytest` invocation failed because `pytest` was not on PATH; using the repo venv and explicit `PYTHONPATH` produced the passing result above.

