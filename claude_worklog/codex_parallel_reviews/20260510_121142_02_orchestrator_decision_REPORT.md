# Codex Parallel Review - Orchestrator Decision MVP

Generated: 2026-05-10

## Scope

Reviewed read-only, except writing this requested report pair:

- `v2/backend/app/domain/orchestrator_decision/`
- `v2/backend/app/services/orchestrator_decision/`
- `v2/backend/app/composition/orchestrator_decision/`
- `v2/backend/app/domain/risk_gateway/`
- `v2/backend/app/services/risk_gateway/`
- `v2/backend/app/composition/risk_gateway/`
- focused unit tests under `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/`
- `claude_worklog/legacy_readonly_audit/`

No `/home/wali/Desktop/AI BOT` files were modified. No Redis reads or writes, Redis key deletes, live-service restarts, order placement/cancellation, leverage/margin changes, live-trading enablement, deployment, or secret exposure were performed.

## Validation

- `PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/unit/domain/orchestrator_decision v2/backend/tests/unit/services/orchestrator_decision v2/backend/tests/unit/composition/orchestrator_decision v2/backend/tests/unit/domain/risk_gateway v2/backend/tests/unit/services/risk_gateway v2/backend/tests/unit/composition/risk_gateway`
- Result: `183 passed in 0.40s`

## Findings

### BLOCKER 1 - Risk gateway handoff can allow an unsafe manually constructed open decision

The orchestrator assembler correctly abstains missing and stale prediction freshness before any tradable direction branch:

- `v2/backend/app/services/orchestrator_decision/service.py:77-82`

It also abstains `CRITICAL`, `DEGRADED`, and `UNKNOWN` worker health before low-confidence and tradable direction handling:

- `v2/backend/app/services/orchestrator_decision/service.py:83-94`

However, `OrchestratorDecisionRecord` validates tradable actions only by action, reason, and input direction. It validates freshness and worker-health membership, but it does not enforce that `open_long` or `open_short` require `input_prediction_freshness_flag == "fresh"` and `input_worker_health_status == "HEALTHY"`:

- `v2/backend/app/domain/orchestrator_decision/record.py:146-187`

The risk gateway accepts any `OrchestratorDecisionRecord` and maps `open_long` and `open_short` directly to allow:

- `v2/backend/app/services/risk_gateway/service.py:49-54`

That leaves the orchestrator-to-risk handoff incomplete for the review requirement. The happy-path assembler avoids stale or unhealthy opens, but the boundary contract does not prevent an impossible-state decision record from being allowed by risk.

### BLOCKER 2 - Duplicate signal handling is not modeled

The review checklist explicitly includes stale/duplicate signal handling. Stale and missing prediction freshness are represented; duplicate handling is not.

No duplicate/deduplication input field, reason code, service branch, composition parameter, or targeted test exists in the inspected orchestrator decision MVP surface:

- `v2/backend/app/domain/orchestrator_decision/record.py:13-21` includes proceed, hold, low-confidence, freshness, and worker-health reasons only.
- `v2/backend/app/services/orchestrator_decision/service.py:77-103` has no duplicate-signal branch.
- `v2/backend/app/domain/trainer_prediction_output/record.py:90-106` has no `signal_id` or duplicate marker field available for this handoff.

The Phase 2F evidence review reserves `signal_id` for an upstream signal layer, but this review input requires duplicate signal handling. There is no ownership artifact or integration proof in the inspected paths showing duplicates are handled before an orchestrator decision is assembled.

### PASS - decision_id lineage is deterministic and propagated

The orchestrator service rejects overlong `prediction_id` values, derives `decision_id = "dec_" + prediction.prediction_id`, and propagates `prediction_id`, `feature_snapshot_id`, and `symbol` into the decision record:

- `v2/backend/app/services/orchestrator_decision/service.py:70-76`
- `v2/backend/app/services/orchestrator_decision/service.py:105-118`

The risk gateway rejects overlong incoming decision IDs before deriving `risk_decision_id = "rd_" + decision.decision_id`, and propagates `decision_id`, `prediction_id`, `feature_snapshot_id`, and `symbol`:

- `v2/backend/app/services/risk_gateway/service.py:43-47`
- `v2/backend/app/services/risk_gateway/service.py:67-79`

### PASS WITH GAP - Legacy orchestrator behavior mapping

The legacy read-only audit requires `decision_id`, risk default-deny for stale/unsafe signals, paper ledger lifecycle capture, and shadow comparison:

- `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md:13-17`

The LAB failure register also requires net exposure and market-context checks before hedge-leg close decisions:

- `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md:16-36`

The MVP maps stale/missing prediction freshness, worker-health abstain states, low confidence, flat hold, and long/short candidate decisions. It does not yet map duplicate signals or hedge-unwind/net-exposure context.

### PASS - No direct trade execution in reviewed path

Focused searches over the reviewed orchestrator decision and risk gateway domain/service/composition packages found no direct order, exchange, leverage, margin, execution adapter, Redis, HTTP, subprocess, socket, or FastAPI side-effect surface. The reviewed path returns frozen records and sets `live_blocked=True`:

- `v2/backend/app/services/orchestrator_decision/service.py:117`
- `v2/backend/app/services/risk_gateway/service.py:78`

## Proposed Non-Live Autofix Tasks

1. Add orchestrator decision domain cross-field invariants so `open_long` and `open_short` require `input_prediction_freshness_flag == "fresh"` and `input_worker_health_status == "HEALTHY"`. Add unit tests proving stale, missing, degraded, critical, and unknown open decisions cannot be constructed.
2. Add risk-gateway defensive tests for stale/missing/unhealthy decision inputs. If the domain remains the primary guard, tests should prove those records fail before the risk gateway can allow them.
3. Add a non-live duplicate-signal design slice: define ownership for `signal_id` deduplication upstream or add an explicit duplicate input contract, then add an `abstain_duplicate_signal` or equivalent deny path with unit/integration tests.
4. Add a non-live trainer prediction output -> orchestrator decision -> risk gateway integration test proving lineage preservation, stale/missing fail-closed behavior, duplicate ownership, and no live side effects.

## Verdict

CODEX_PARALLEL_REVIEW_BLOCKED
