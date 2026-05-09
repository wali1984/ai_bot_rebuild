# Codex Parallel Review - Orchestrator Decision MVP

Generated: 2026-05-09

## Scope

Reviewed, read-only except this report pair:

- `v2/backend/app/domain/orchestrator_decision/`
- `v2/backend/app/services/orchestrator_decision/`
- `v2/backend/app/composition/orchestrator_decision/`
- `v2/backend/app/domain/risk_gateway/`
- `v2/backend/app/services/risk_gateway/`
- `v2/backend/tests/unit/domain/orchestrator_decision/`
- `v2/backend/tests/unit/services/orchestrator_decision/`
- `v2/backend/tests/unit/composition/orchestrator_decision/`
- `v2/backend/tests/unit/domain/risk_gateway/`
- `v2/backend/tests/unit/services/risk_gateway/`
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/`
- `claude_worklog/legacy_readonly_audit/`

No `/home/wali/Desktop/AI BOT` files were modified. No Redis access, Redis writes, service restarts, orders, leverage or margin changes, live-trading enablement, deployment, or secret exposure were performed.

## Validation Run

- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/orchestrator_decision v2/backend/tests/unit/services/orchestrator_decision v2/backend/tests/unit/composition/orchestrator_decision -q` -> `98 passed`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/risk_gateway v2/backend/tests/unit/services/risk_gateway -q` -> `61 passed`

## Findings

### BLOCKER 1 - Risk gateway can allow a stale manually constructed open decision

`OrchestratorDecisionRecord` validates open decisions only by action/reason/direction. It does not enforce that tradable actions require `input_prediction_freshness_flag == "fresh"` or `input_worker_health_status == "HEALTHY"`:

- `v2/backend/app/domain/orchestrator_decision/record.py:166-187` enforces `open_long/open_short` reason and direction only.
- `v2/backend/app/domain/orchestrator_decision/record.py:146-157` validates freshness and worker-health membership, not action compatibility.

The service assembler does abstain stale/missing predictions before open actions:

- `v2/backend/app/services/orchestrator_decision/service.py:77-82`

But the risk gateway trusts any `OrchestratorDecisionRecord` instance and maps open actions directly to allow:

- `v2/backend/app/services/risk_gateway/service.py:49-54`

Confirmed locally with a pure in-process value-object check: a record with `decision_action="open_long"`, `decision_reason_code="proceed_long"`, `input_prediction_direction="long"`, and `input_prediction_freshness_flag="stale"` assembled to `risk_action="allow"` and `risk_reason_code="allow_proceed_long"`.

This violates the review check that the risk gateway handoff be complete for stale/unsafe signal defense. It is not enough that the happy-path orchestrator assembler avoids producing this state; the handoff boundary accepts the domain object directly.

### BLOCKER 2 - Duplicate signal handling is not modeled

No duplicate/deduplication field, reason code, service branch, composition parameter, or test exists in the orchestrator decision MVP surface:

- `v2/backend/app/domain/orchestrator_decision/record.py:13-21` reason taxonomy contains freshness, worker-health, low-confidence, hold, and proceed reasons only.
- `v2/backend/app/services/orchestrator_decision/service.py:77-103` derivation table has no duplicate-signal branch.
- `rg` over the orchestrator decision domain/service/composition test paths found no duplicate/dedupe handling.

Legacy review inputs call out duplicate handling as a required safety concern in later proof material and the current review topic explicitly asks for stale/duplicate signal handling. Stale is represented; duplicate is not.

### PASS - decision_id lineage is deterministic and propagated

The orchestrator service derives `decision_id = "dec_" + prediction.prediction_id` and propagates `prediction_id`, `feature_snapshot_id`, and `symbol` into the decision record:

- `v2/backend/app/services/orchestrator_decision/service.py:70-76`
- `v2/backend/app/services/orchestrator_decision/service.py:105-118`

The risk gateway derives `risk_decision_id = "rd_" + decision.decision_id` and propagates `decision_id`, `prediction_id`, `feature_snapshot_id`, and `symbol`:

- `v2/backend/app/services/risk_gateway/service.py:43-47`
- `v2/backend/app/services/risk_gateway/service.py:67-79`

### PASS - No direct trade execution in reviewed orchestrator/risk path

Searches over the reviewed orchestrator and risk packages found no direct order, exchange, leverage, margin, Binance, ccxt, execution-router, or trade-placement tokens. The orchestrator decision packages are pure value/service/composition surfaces and set `live_blocked=True` when constructing records:

- `v2/backend/app/services/orchestrator_decision/service.py:117`
- `v2/backend/app/services/risk_gateway/service.py:78`

### PASS WITH GAP - Legacy behavior mapping

Legacy audit evidence confirms only high-level requirements: decisions require `decision_id`, risk gateway must default-deny stale/unsafe signals, paper ledger must capture trade lifecycle, and shadow mode must compare legacy vs V2:

- `claude_worklog/legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md`
- `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md`

The MVP maps stale/missing prediction freshness, worker-health degradation, unknown/critical worker status, low confidence, flat hold, and long/short proceed. It does not yet model duplicate signals or hedge-unwind/net-exposure context.

## Proposed Non-Live Autofix Tasks

1. Add domain cross-field invariants so `open_long` and `open_short` require `input_prediction_freshness_flag == "fresh"` and `input_worker_health_status == "HEALTHY"`; add unit tests that stale/missing/degraded/critical/unknown open decisions are rejected before risk gateway handoff.
2. Add risk-gateway defensive deny tests for stale/missing/unsafe decision inputs. If domain invariants remain the primary guard, include explicit tests proving impossible states cannot be constructed.
3. Add a non-live duplicate-signal design slice: introduce a duplicate/dedupe signal attribute or upstream decision input contract, add `abstain_duplicate_signal` or an equivalent deny reason, and cover the service derivation and risk handoff with unit tests.
4. Keep all fixes pure and local to domain/service/composition/tests. Do not read or write Redis, do not call live services, do not touch execution adapters, and do not enable live trading.

## Verdict

CODEX_PARALLEL_REVIEW_BLOCKED
