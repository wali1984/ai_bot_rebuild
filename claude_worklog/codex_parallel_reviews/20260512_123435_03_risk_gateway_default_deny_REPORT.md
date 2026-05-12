# Codex Parallel Review - Risk Gateway Default Deny MVP

Review timestamp: 2026-05-12 12:34:35

Verdict: BLOCKED

## Scope Reviewed

- `v2/backend/app/domain/risk_gateway/record.py`
- `v2/backend/app/services/risk_gateway/service.py`
- `v2/backend/app/composition/risk_gateway/runtime.py`
- `v2/backend/app/services/orchestrator_decision/service.py`
- `v2/backend/app/services/external_manual_position_quarantine/service.py`
- `v2/backend/app/proof/external_manual_position_quarantine.py`
- `v2/backend/tests/unit/domain/risk_gateway/`
- `v2/backend/tests/unit/services/risk_gateway/`
- `v2/backend/tests/unit/composition/risk_gateway/`
- `v2/backend/tests/unit/replay_case_lab_hedge_unwind/`
- `v2/backend/tests/unit/proof/test_external_manual_position_quarantine.py`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/`
- `claude_worklog/phase2_core_rebuild/risk_gateway/`
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`

## Validation Run

Command:

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/pytest -q -p no:cacheprovider v2/backend/tests/unit/domain/risk_gateway v2/backend/tests/unit/services/risk_gateway v2/backend/tests/unit/composition/risk_gateway v2/backend/tests/unit/replay_case_lab_hedge_unwind v2/backend/tests/unit/proof/test_external_manual_position_quarantine.py`

Result: `108 passed in 0.27s`

## Findings

### BLOCKER 1 - Risk gateway does not enforce true default-deny at the risk boundary

`v2/backend/app/services/risk_gateway/service.py:49-60` maps orchestrator `open_long` directly to `allow_proceed_long` and `open_short` directly to `allow_proceed_short`. `deny_default` is explicitly reserved in the domain at `v2/backend/app/domain/risk_gateway/record.py:15`, but Phase 2G.B forbids the service from emitting it and documents that the assembler never emits `deny_default`.

This means the gateway is a mirror of an already-validated orchestrator action, not a risk gate that defaults to deny unless all independent risk predicates pass.

Non-live autofix task:

- Add a pure risk-gateway policy input/value object for required gate state, such as freshness status, quarantine status, residual exposure risk, and explicit allow eligibility. Change the assembler/evaluator so every missing, unknown, or unsafe gate produces `risk_action="deny"` with a deny reason. Keep it pure and unit-tested; do not connect Redis, exchange clients, or live execution.

### BLOCKER 2 - Stale data blocks are indirect only

Stale and missing prediction data are blocked upstream in `v2/backend/app/services/orchestrator_decision/service.py:77-82`, where freshness `missing` or `stale` becomes orchestrator `abstain`. The risk gateway then maps any `abstain` to `deny_orchestrator_abstained` at `v2/backend/app/services/risk_gateway/service.py:58-60`.

There is no risk-gateway-level freshness field or independent stale-data assertion in `RiskDecisionRecord` or `assemble_risk_decision_record`. A prebuilt `open_long` or `open_short` decision with no gateway freshness context will be allowed.

Non-live autofix task:

- Add risk-gateway unit tests proving stale/missing freshness is denied by the gateway itself, not only by orchestrator pre-filtering. Wire freshness metadata into the pure gateway input and assert open decisions with stale or missing data produce deny.

### BLOCKER 3 - Hedge unwind residual exposure blocks are not implemented in the gateway path

The legacy LAB failure requires evaluating remaining net exposure before closing a protective hedge leg. The failure note states V2 must check net exposure after close, confidence, freshness, liquidation/OI/orderbook/funding/volatility/sweep/structure context, and block/reduce/close/mark unsafe where needed.

Current LAB coverage in `v2/backend/tests/unit/replay_case_lab_hedge_unwind/` records typed paper/replay mirror sequences. It includes a `block_hedge_close` fixture using `mirror_deny_default`, but this is fixture-level replay evidence. It does not exercise `assemble_risk_decision_record` or `build_risk_decision_evaluator` with hedge state, protective-leg close intent, residual short exposure, or squeeze-risk inputs.

Non-live autofix task:

- Add a pure hedge-unwind risk policy module and tests that feed a LAB-like close-protective-long-while-short-remains case through the risk gateway. Required expected result: deny unless the proposed action reduces or neutralizes residual adverse exposure. Use deterministic fixtures only.

### BLOCKER 4 - Manual/external position quarantine is not integrated into risk gateway allow/deny

`v2/backend/app/proof/external_manual_position_quarantine.py:186-256` classifies manual, exchange-side protective, unknown, and duplicate rows as quarantined and lists blocked actions. `v2/backend/app/services/external_manual_position_quarantine/service.py:12-53` can derive an `ExternalPositionQuarantineRecord` from an existing risk decision.

However, risk decisions are still assembled first, and `v2/backend/app/services/risk_gateway/service.py` has no quarantine input. A symbol/account already classified as manual/external/quarantined cannot force the gateway to deny an otherwise-open decision.

Non-live autofix task:

- Add a quarantine-state input to the pure gateway evaluator and tests proving any quarantined symbol/account blocks risk-add, hedge, DCA, increase, or ownership-assumption decisions. Keep monitor-only evidence paths separate from live execution.

### BLOCKER 5 - LAB-like failure coverage is present but not end-to-end for the risk gateway

The LAB failure case is captured in `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`, and replay fixtures exist. The tests verify paper/replay typed mirror sequences and `live_blocked=True`, but they do not prove the gateway itself detects the legacy failure pattern or emits a deny from real risk inputs.

Non-live autofix task:

- Add an end-to-end non-live gateway test chain: trainer/orchestrator decision plus risk context plus quarantine/residual exposure fixtures produce a `RiskDecisionRecord` deny. Verify the record includes deterministic IDs, `live_blocked=True`, and a reason code specific enough to audit the LAB failure mode.

## Positive Evidence

- Risk domain records enforce frozen/slotted value objects, strict IDs, uppercase symbols, allowed action/reason taxonomies, and `live_blocked=True`.
- Risk service and composition surfaces are pure, clock-injected, and Redis/HTTP/FastAPI-clean.
- Upstream orchestrator blocks stale/missing prediction freshness by abstaining before risk assembly.
- External/manual quarantine proof classifies manual, exchange-side protective, unknown, and duplicate evidence as quarantined monitor-only.
- Targeted unit tests pass under read-only-style pytest execution with cache disabled.

## Go/No-Go

The implementation is not ready for the broader "Risk Gateway Default Deny MVP" review criteria. It is a clean foundation, but default-deny enforcement, stale-data checks, residual hedge exposure checks, and quarantine checks are not all enforced at the risk gateway boundary.

CODEX_PARALLEL_REVIEW_BLOCKED
