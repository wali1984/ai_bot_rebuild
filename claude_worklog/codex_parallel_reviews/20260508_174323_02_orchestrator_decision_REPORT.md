# Codex Parallel Review - Orchestrator Decision MVP

Review timestamp: 2026-05-08 17:43:23 UTC

Verdict: BLOCKED

## Scope Reviewed

- `v2/backend/app/domain/orchestrator_decision/`
- `v2/backend/app/services/orchestrator_decision/`
- `v2/backend/app/composition/orchestrator_decision/`
- downstream handoff surfaces in `v2/backend/app/domain/risk_gateway/`, `v2/backend/app/services/risk_gateway/`, and `v2/backend/app/composition/risk_gateway/`
- focused tests under `v2/backend/tests/unit/domain/orchestrator_decision/`, `v2/backend/tests/unit/services/orchestrator_decision/`, `v2/backend/tests/unit/composition/orchestrator_decision/`, `v2/backend/tests/unit/services/risk_gateway/`, and `v2/backend/tests/unit/composition/risk_gateway/`
- orchestrator decision implementation notes under `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/`
- legacy runtime and impact notes under `claude_worklog/legacy_readonly_audit/`

## Validation Performed

- Static inspection of the orchestrator decision domain, service, and composition implementation.
- Static inspection of the risk gateway domain, service, and composition handoff implementation.
- Static inspection of unit tests covering lineage, stale/missing freshness, worker health, low confidence, risk gateway mappings, `live_blocked`, and forbidden imports.
- Forbidden live-action scan:
  - `rg -n "create_order|place_order|submit_order|cancel_order|set_leverage|set_margin|enable_live|live_trading|execution_router|PaperExecution|ExecutionIntent|risk_gateway|signal_publisher|Redis|redis|xadd|xread|delete\\(|flush" v2/backend/app/domain/orchestrator_decision v2/backend/app/services/orchestrator_decision v2/backend/app/composition/orchestrator_decision v2/backend/app/services/risk_gateway v2/backend/app/composition/risk_gateway`
  - result: only risk gateway import references in the risk gateway package itself; no order, leverage, margin, Redis command, live enablement, or execution-router calls in the reviewed orchestrator decision path.
- Targeted tests could not be executed in this environment:
  - `pytest` was not on PATH.
  - `python -m pytest` failed with `No module named pytest`.

## Findings

### PASS - decision_id lineage is deterministic and propagated

`assemble_orchestrator_decision_record` derives `decision_id = "dec_" + prediction.prediction_id`, enforces a 124-character prediction-id cap before derivation, and returns an `OrchestratorDecisionRecord` with `prediction_id`, `feature_snapshot_id`, `symbol`, input direction, confidence, freshness, and worker health copied from the input prediction.

The risk gateway handoff derives `risk_decision_id = "rd_" + decision.decision_id` and propagates `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, `input_decision_action`, and `input_decision_reason_code`.

Coverage evidence includes `test_assemble_decision_id_derived_from_prediction_id.py`, `test_assemble_propagates_input_lineage_fields.py`, `test_assemble_risk_decision_id_derived_from_decision_id.py`, and the risk gateway lineage propagation tests.

### PASS - risk gateway handoff maps every current orchestrator action

The risk gateway service maps:

- `open_long` / `proceed_long` to `allow` / `allow_proceed_long`
- `open_short` / `proceed_short` to `allow` / `allow_proceed_short`
- `hold` to `deny` / `deny_orchestrator_held`
- `abstain` to `deny` / `deny_orchestrator_abstained`

The domain invariants reject mismatched action/reason pairs, and the service has a test asserting it never emits the reserved `deny_default` for the current orchestrator input set.

Residual risk: this is a thin MVP handoff, not a full risk policy. It preserves `live_blocked=True`, but open-long/open-short still become risk `allow` records for downstream paper/shadow processing. That is acceptable only because downstream records also enforce non-live behavior.

### PASS - stale and missing prediction freshness default to abstain, then risk deny

The orchestrator assembler checks freshness before worker health, confidence, or direction:

- `missing` becomes `abstain_freshness_missing`
- `stale` becomes `abstain_freshness_stale`

Tests cover stale handling, missing-over-stale priority, and stale-over-worker priority. The risk gateway maps any orchestrator `abstain` to `deny_orchestrator_abstained`, so stale/missing prediction inputs do not become tradable risk approvals.

### BLOCKER - duplicate signal handling is not implemented or represented

The reviewed Orchestrator Decision MVP is prediction-driven and has no `signal_id`, signal timestamp, signal source cursor, idempotency key, duplicate-detection state, or duplicate rejection reason. The phase notes explicitly reserve `signal_id` for an upstream signal layer and state that decisions are not signals.

That may match the original 2F milestone scope, but it does not satisfy this parallel review checklist's stale/duplicate signal handling check. Legacy audit notes require the risk gateway to default-deny stale/unsafe signals, and duplicate signal replay is an unsafe/idempotency class unless a boundary explicitly proves it is handled upstream. No such proof is present in the Orchestrator Decision MVP artifacts reviewed here.

Concrete impact: repeated submission of the same `TrainerPredictionRecord.prediction_id` deterministically recreates the same `decision_id`. The pure assembler does not mark it duplicate, reject it, or emit a distinct non-live duplicate reason. There is also no test asserting that duplicate prediction/signal input is denied, idempotently reused, or delegated to a documented upstream dedup layer.

### PASS - legacy orchestrator behavior mapping is captured at the MVP safety level

Legacy evidence shows a live `rl.orchestrator_worker` and `trading/trader.py` process split, plus required V2 impacts: decisions need `decision_id`, stale/unsafe signals need risk-gateway denial, and downstream paper/shadow surfaces must preserve auditability.

The MVP maps the safe subset:

- explicit decision ID lineage exists
- stale/missing prediction freshness abstains
- hold/abstain become risk deny
- the decision record is not an execution intent
- risk records retain upstream decision and prediction lineage

The MVP does not attempt to port legacy strategy behavior, hedge handling, or trader execution behavior, which is consistent with the phase safety boundaries.

### PASS - no direct trade execution observed

The reviewed orchestrator decision packages do not import exchange adapters, execution routers, paper execution ledger code, signal publishers, Redis clients, FastAPI app surfaces, or live-mode controls. `live_blocked` is required to be `True` in both `OrchestratorDecisionRecord` and `RiskDecisionRecord`, and the assemblers construct records with literal `live_blocked=True`.

No Redis commands were run. No live services were restarted. No exchange, leverage, margin, or deployment actions were taken.

## Concrete Blockers

1. Duplicate signal handling is absent from the Orchestrator Decision MVP.
   - No `signal_id`, signal cursor, idempotency key, duplicate rejection reason, or explicit upstream dedup contract is present in the reviewed decision/risk handoff.
   - Duplicate `prediction_id` inputs deterministically recreate the same `decision_id` without any duplicate classification.

2. Tests do not cover duplicate signal or duplicate prediction behavior.
   - Existing tests cover stale/missing freshness and lineage, but none assert duplicate inputs are denied, idempotently reused, or outside scope by a documented upstream boundary.

3. The risk gateway handoff does not receive enough signal metadata to default-deny duplicate signals itself.
   - It can deny `abstain` and `hold`, but it cannot distinguish first-seen versus repeated signal/prediction events.

## Proposed Non-Live Autofix Tasks

1. Add a pure, no-I/O idempotency boundary spec for the orchestrator decision input contract:
   - Either document that duplicate signal handling is owned by an upstream signal layer and prove the decision MVP only accepts already-deduped `TrainerPredictionRecord` inputs.
   - Or extend the MVP with a non-live duplicate-aware input wrapper carrying `signal_id` or an equivalent idempotency key.

2. Add duplicate handling tests without Redis or live state:
   - duplicate `prediction_id` contract test
   - duplicate `signal_id` or idempotency-key contract test if the key is introduced
   - risk gateway test proving duplicate-classified inputs become `deny` with a duplicate-specific reason, or a test proving duplicates cannot reach the gateway by contract

3. If duplicate handling remains upstream, add a worklog artifact under the orchestrator decision implementation notes that names the upstream module, the exact dedup field, and the expected downstream invariant.

4. If duplicate handling is added locally, keep it pure and injectable:
   - no Redis writes
   - no mutable module-level cache
   - no background worker
   - no live trading or execution side effect
   - no change to leverage, margin, order placement, or deployment behavior

## Safety Statement

This review performed local read-only inspection plus attempted targeted test execution. The tests did not run because `pytest` is unavailable in this environment. No files under `/home/wali/Desktop/AI BOT` were modified. No Redis writes or deletes were performed. No live services were restarted. No exchange orders were placed or cancelled. No leverage or margin settings were changed. Live trading was not enabled. Nothing was deployed, and no secrets were exposed.
