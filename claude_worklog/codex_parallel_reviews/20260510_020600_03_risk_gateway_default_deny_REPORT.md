# Codex Parallel Review - Risk Gateway Default Deny MVP

Verdict: BLOCKED.

## Scope Inspected

- `v2/backend/app/domain/risk_gateway/`
- `v2/backend/app/services/risk_gateway/`
- `v2/backend/app/composition/risk_gateway/`
- `v2/backend/app/services/orchestrator_decision/service.py`
- `v2/backend/app/proof/external_manual_position_quarantine.py`
- `v2/backend/app/services/external_manual_position_quarantine/`
- `v2/backend/tests/unit/domain/risk_gateway/`
- `v2/backend/tests/unit/services/risk_gateway/`
- `v2/backend/tests/unit/composition/risk_gateway/`
- `v2/backend/tests/unit/replay_case_lab_hedge_unwind/`
- `v2/backend/tests/unit/proof/test_external_manual_position_quarantine.py`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/`
- `claude_worklog/phase2_core_rebuild/risk_gateway/`
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`

## Verification

- Ran: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/unit/domain/risk_gateway v2/backend/tests/unit/services/risk_gateway v2/backend/tests/unit/composition/risk_gateway v2/backend/tests/unit/replay_case_lab_hedge_unwind v2/backend/tests/unit/proof/test_external_manual_position_quarantine.py`
- Result: `108 passed in 0.29s`

## What Passes

- `RiskDecisionRecord` is frozen and enforces `live_blocked=True`.
- The risk gateway service is pure and did not show Redis, exchange, live-order, deployment, or FastAPI side effects in the inspected implementation.
- Orchestrator `hold` maps to risk `deny` / `deny_orchestrator_held`.
- Orchestrator `abstain` maps to risk `deny` / `deny_orchestrator_abstained`.
- Stale and missing freshness are blocked when upstream orchestrator logic correctly converts them to `abstain_freshness_stale` or `abstain_freshness_missing`.
- Manual/external position quarantine proof code classifies manual, exchange-side protective, unknown, and duplicate-accounting rows as quarantined and monitor-only.
- LAB hedge-unwind replay tests cover typed mirror sequences for legacy, keep-hedge, close-short, reduce-short, and block-hedge-close outcomes.

## Blockers

1. Default deny is not gateway-local for tradable actions.
   - Evidence: `v2/backend/app/services/risk_gateway/service.py` maps `open_long` to `risk_action="allow"` / `allow_proceed_long` and `open_short` to `risk_action="allow"` / `allow_proceed_short`.
   - Evidence: `v2/backend/tests/unit/services/risk_gateway/test_assemble_never_emits_deny_default_for_orchestrator_inputs.py` asserts the assembler never emits `deny_default`.
   - Impact: a valid upstream tradable decision can pass the risk gateway without any gateway-local stale-data, exposure, ownership, or quarantine safety context.

2. Stale data blocks are upstream-dependent, not enforced by the risk gateway itself.
   - Evidence: stale/missing freshness is handled in `v2/backend/app/services/orchestrator_decision/service.py` before the risk gateway sees the decision.
   - Evidence: risk gateway inputs contain only an `OrchestratorDecisionRecord` and a clock; they do not include feature-source age, source timestamps, completeness, or freshness provenance.
   - Impact: if upstream misclassifies, omits, or bypasses freshness state, the risk gateway cannot independently default-deny stale data.

3. Hedge unwind residual exposure blocking is absent from the actual risk gateway path.
   - Evidence: `v2/backend/app/domain/risk_gateway/record.py`, `v2/backend/app/services/risk_gateway/service.py`, and `v2/backend/app/composition/risk_gateway/runtime.py` have no fields for current position, proposed close/reduce action, hedge relationship, net exposure before/after, liquidation/squeeze context, or residual exposure.
   - Evidence: LAB replay fixtures can represent `mirror_deny_default`, but they build paper ledger entries directly rather than driving a LAB residual-exposure input through `assemble_risk_decision_record`.
   - Impact: the legacy LAB failure mode can be documented and replayed, but the risk gateway implementation would not block a hedge-leg close that leaves unsafe residual exposure.

4. Manual/external position quarantine is not integrated into the risk gateway allow/deny decision.
   - Evidence: quarantine exists in proof and separate service/domain modules, but the risk gateway assembler accepts no `ManualPositionFlag`, ownership classification, reconciled exchange position snapshot, or quarantined symbol/account state.
   - Evidence: `assemble_external_position_quarantine_record` consumes a completed `RiskDecisionRecord`; it does not cause `assemble_risk_decision_record` to deny a tradable decision.
   - Impact: manual or exchange-side protective positions can be classified in non-live artifacts, but the risk gateway cannot quarantine them before producing an `allow`.

5. LAB-like failure case coverage is not risk-gateway behavior coverage.
   - Evidence: `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md` requires evaluating remaining net exposure before closing a protective hedge leg.
   - Evidence: current LAB tests assert replay/paper mirror sequences and summary counts, not a risk gateway decision produced from hedge-unwind exposure context.
   - Impact: tests can pass while the gateway still lacks the required residual exposure block.

## Proposed Non-Live Autofix Tasks

1. Add a non-live risk gateway context value object containing:
   - orchestrator decision
   - feature/source freshness metadata
   - reconciled position snapshot
   - position ownership/quarantine state
   - proposed intent/action type
   - hedge relationship
   - net exposure before and after the proposed action

2. Extend risk denial taxonomy and tests for:
   - `deny_stale_data`
   - `deny_manual_external_position_quarantine`
   - `deny_hedge_unwind_residual_exposure`
   - `deny_default` for missing or incomplete safety context

3. Change the risk gateway assembler/evaluator to deny tradable decisions unless every required non-live safety input is present, fresh, internally owned, not quarantined, and exposure-safe.

4. Add gateway-local unit tests proving:
   - missing safety context defaults to deny
   - stale source metadata denies even when the upstream action is tradable
   - manual/external/quarantined symbol-account state denies before any allow
   - closing a protective hedge leg that leaves residual exposure denies
   - the LABUSDT hedge-unwind fixture reaches a gateway `deny_hedge_unwind_residual_exposure` or equivalent non-live deny

5. Add a non-live integration harness that feeds the LAB failure fixture through the actual risk gateway code path before paper ledger/replay projection.

## Safety Notes

- Did not modify `/home/wali/Desktop/AI BOT`.
- Did not write Redis or delete Redis keys.
- Did not restart services, deploy, place/cancel orders, change leverage/margin, or enable live trading.
- Only the requested review artifacts under `claude_worklog/codex_parallel_reviews/` were written.
