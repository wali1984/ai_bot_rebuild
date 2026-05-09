# Codex Parallel Review - Orchestrator Decision MVP

Generated: 2026-05-09

## Scope

Reviewed read-only, except this requested report pair:

- `v2/backend/app/domain/orchestrator_decision/`
- `v2/backend/app/services/orchestrator_decision/`
- `v2/backend/app/composition/orchestrator_decision/`
- `v2/backend/app/domain/risk_gateway/`
- `v2/backend/app/services/risk_gateway/`
- `v2/backend/app/composition/risk_gateway/`
- `v2/backend/tests/unit/domain/orchestrator_decision/`
- `v2/backend/tests/unit/services/orchestrator_decision/`
- `v2/backend/tests/unit/composition/orchestrator_decision/`
- `v2/backend/tests/unit/domain/risk_gateway/`
- `v2/backend/tests/unit/services/risk_gateway/`
- `v2/backend/tests/unit/composition/risk_gateway/`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/`
- `claude_worklog/legacy_readonly_audit/`

No `/home/wali/Desktop/AI BOT` files were modified. No Redis reads or writes, Redis key deletes, live-service restarts, order placement/cancellation, leverage/margin changes, live-trading enablement, deployment, or secret exposure were performed.

## Findings

### BLOCKER 1 - Risk gateway handoff can allow an unsafe manually constructed open decision

`assemble_orchestrator_decision_record` correctly abstains stale or missing prediction freshness before producing open actions:

- `v2/backend/app/services/orchestrator_decision/service.py:77-82`

However, `OrchestratorDecisionRecord` itself validates `open_long` and `open_short` only by action/reason/direction. It validates freshness and worker-health membership, but does not enforce that tradable actions require `input_prediction_freshness_flag == "fresh"` and `input_worker_health_status == "HEALTHY"`:

- `v2/backend/app/domain/orchestrator_decision/record.py:146-157`
- `v2/backend/app/domain/orchestrator_decision/record.py:166-187`

The risk gateway accepts any `OrchestratorDecisionRecord` and maps open actions directly to allow:

- `v2/backend/app/services/risk_gateway/service.py:49-54`

That leaves the handoff incomplete: the pure assembler happy path avoids stale opens, but the boundary contract does not prevent an impossible-state record from being allowed by risk. This violates the review check that stale/unsafe signal defense survive the orchestrator-to-risk handoff.

### BLOCKER 2 - Duplicate signal handling is not modeled

The orchestrator decision MVP has no duplicate/deduplication input field, reason code, service branch, composition parameter, or targeted test:

- `v2/backend/app/domain/orchestrator_decision/record.py:13-21` includes proceed, hold, low-confidence, freshness, and worker-health reasons only.
- `v2/backend/app/services/orchestrator_decision/service.py:77-103` has no duplicate-signal branch.
- `rg` over the orchestrator decision domain/service/composition code and tests found no `duplicate`, `dedupe`, or `dedup` handling in the MVP surface.

The current review explicitly requires stale/duplicate signal handling. Stale/missing freshness is represented; duplicates are not.

### PASS - decision_id lineage is deterministic and propagated

The orchestrator service derives `decision_id = "dec_" + prediction.prediction_id`, rejects overlong prediction IDs before derivation, and propagates `prediction_id`, `feature_snapshot_id`, and `symbol`:

- `v2/backend/app/services/orchestrator_decision/service.py:70-76`
- `v2/backend/app/services/orchestrator_decision/service.py:105-118`

The risk gateway derives `risk_decision_id = "rd_" + decision.decision_id` and propagates `decision_id`, `prediction_id`, `feature_snapshot_id`, and `symbol`:

- `v2/backend/app/services/risk_gateway/service.py:43-47`
- `v2/backend/app/services/risk_gateway/service.py:67-79`

### PASS WITH GAP - Legacy orchestrator behavior mapping

The legacy read-only audit evidence calls out the required V2 impacts: decisions need `decision_id`, risk must default-deny stale/unsafe signals, paper ledger must capture lifecycle events, and shadow mode must compare legacy vs V2:

- `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md:13-17`
- `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md:16-23`

The MVP maps freshness abstain, worker-health abstain, low-confidence abstain, flat hold, and long/short proceed behavior. It does not yet map duplicate signals or hedge-unwind/net-exposure context.

### PASS - No direct trade execution in reviewed path

Focused searches over the orchestrator decision and risk gateway domain/service/composition packages found no direct order, exchange, leverage, margin, execution adapter, Redis, HTTP, subprocess, socket, or FastAPI side-effect surface. The reviewed assembly path returns frozen records and sets `live_blocked=True`:

- `v2/backend/app/services/orchestrator_decision/service.py:117`
- `v2/backend/app/services/risk_gateway/service.py:78`

## Proposed Non-Live Autofix Tasks

1. Add domain cross-field invariants so `open_long` and `open_short` require fresh prediction freshness and healthy worker status. Add unit tests proving stale, missing, degraded, critical, and unknown open decisions cannot be constructed.
2. Add risk-gateway defensive coverage for stale/missing/unsafe decision inputs. If the domain remains the primary guard, tests should prove those records fail before the risk gateway can allow them.
3. Add a non-live duplicate-signal design slice: introduce a duplicate/dedup input contract or upstream adapter field, add an `abstain_duplicate_signal` or equivalent deny path, and cover service derivation plus risk handoff with unit tests.
4. Keep fixes pure and local to domain/service/composition/tests. Do not read or write Redis, do not call live services, do not touch execution adapters, and do not enable live trading.

## Verdict

CODEX_PARALLEL_REVIEW_BLOCKED
