# Risk Gateway Default Deny MVP Parallel Review

Review date: 2026-05-09

Scope inspected:
- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl`
- `claude_worklog/phase2_core_rebuild/risk_gateway`
- `claude_worklog/legacy_failure_cases`

## Verdict

CODEX_PARALLEL_REVIEW_BLOCKED

The current Risk Gateway Default Deny MVP is non-live and fail-closed for `live_blocked`, but it does not meet the requested safety bar. The implemented gateway only maps an `OrchestratorDecisionRecord` plus a clock into a `RiskDecisionRecord`; it has no input or policy surface for manual/external position quarantine or hedge-unwind residual exposure. Stale data blocks are covered through the upstream orchestrator abstain path, not by an independent risk gateway freshness gate.

## Evidence

- `v2/backend/app/domain/risk_gateway/record.py`
  - `RiskDecisionRecord` is frozen/slotted and validates action/reason taxonomy.
  - `live_blocked` must be `True` at lines 214-218.
  - `deny_default` is valid only with tradable input actions at lines 135-140.
- `v2/backend/app/services/risk_gateway/service.py`
  - `open_long` maps directly to `allow` / `allow_proceed_long` at lines 49-51.
  - `open_short` maps directly to `allow` / `allow_proceed_short` at lines 52-54.
  - `hold` maps to `deny` / `deny_orchestrator_held` at lines 55-57.
  - `abstain` maps to `deny` / `deny_orchestrator_abstained` at lines 58-60.
  - Returned records always set `live_blocked=True` at line 78.
- `v2/backend/app/composition/risk_gateway/runtime.py`
  - Pure binder around `assemble_risk_decision_record`; no Redis, exchange, order, leverage, margin, deployment, or live-trading behavior observed.
- `v2/backend/app/services/orchestrator_decision/service.py`
  - Stale/missing freshness becomes `abstain` at lines 77-82, which the risk gateway later denies.
- `v2/backend/app/proof/non_live_operational_proof.py`
  - Static non-live proof scenarios include `stale_data_blocked`, `hedge_close_residual_exposure_blocked`, and `lab_hedge_unwind_short_squeeze` at lines 90-145.
  - `_risk_action()` denies proof rows based on fixture fields at lines 149-156; this is not the production risk gateway service.
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`
  - Requires net-exposure evaluation before closing a protective hedge leg and tests that keep hedge, reduce short, close short, block hedge close, or mark unsafe.

## Checks

Default deny behavior: partial pass. `hold`, `abstain`, invalid records, and live blocking are fail-closed. Tradable `open_long` and `open_short` are still allowed by default without a risk context gate.

Stale data blocks: pass only through upstream orchestrator classification. Stale/missing trainer freshness becomes abstain and risk gateway denies abstains. The gateway itself does not inspect feature age or market/account state freshness.

Hedge unwind residual exposure blocks: blocked. The risk gateway cannot represent current position state, protective leg state, net exposure after close, squeeze context, or an unsafe hedge-close request.

Manual/external position quarantine: blocked. Static search found no risk gateway quarantine surface for manual or external positions. Existing `manual` references are symbol-universe overrides, not account-position quarantine.

LAB-like failure case coverage: partial. Non-live proof fixtures and historical proof tests contain LAB hedge-unwind evidence, but the block is fixture-authored rather than derived by the risk gateway from exposure inputs.

## Verification

Ran:

`PYTHONPATH=/home/wali/Desktop/AI\ BOT\ REBUILD PYTHONDONTWRITEBYTECODE=1 ./.venv/bin/pytest -q -p no:cacheprovider v2/backend/tests/unit/services/risk_gateway v2/backend/tests/unit/composition/risk_gateway v2/backend/tests/unit/domain/risk_gateway v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py`

Result: `99 passed in 0.29s`.

## Concrete Blockers

1. Risk gateway allows tradable actions without independent risk context.
   - Impact: `open_long` and `open_short` can produce `allow` even if account/position/exposure context is unavailable.
   - Evidence: `service.py` lines 49-54.

2. No manual/external position quarantine gate exists.
   - Impact: out-of-band positions cannot force `deny_default` or a quarantine-specific deny before paper/live execution surfaces consume the decision.
   - Evidence: no risk gateway app/test hits for `manual`, `external`, or `quarantine`; only symbol-universe manual override references were found.

3. No hedge-unwind residual exposure gate exists at the risk gateway boundary.
   - Impact: the LAB failure requirement is represented by proof fixtures but not enforced by the risk gateway implementation.
   - Evidence: risk gateway service signature accepts only `decision` and `now_ms_clock`; proof harness rows hand-author hedge block outcomes.

4. Stale data is not independently default-denied by the risk gateway.
   - Impact: stale data is blocked only if upstream orchestrator correctly maps it to abstain; the risk gateway has no direct stale/missing input contract.
   - Evidence: orchestrator freshness checks at `orchestrator_decision/service.py` lines 77-82; risk gateway service has no freshness context parameter.

## Proposed Non-Live Autofix Tasks

1. Add a pure risk context value object under `v2/backend/app/domain/risk_gateway/`, with fields for feature freshness, market/account state freshness, position provenance, hedge/protective-leg state, current net exposure, and projected net exposure after requested action.

2. Extend `assemble_risk_decision_record()` or add a new pure policy evaluator to require risk context for tradable actions and fail closed to `deny_default` when context is missing, stale, externally/manual-positioned, or unsafe.

3. Add explicit deny reason constants for quarantine and hedge residual exposure, or document and test `deny_default` as the interim MVP reason for those cases.

4. Add unit tests proving:
   - missing risk context blocks tradable actions;
   - stale feature/market/account state blocks tradable actions;
   - manual/external positions quarantine;
   - closing a protective hedge leg that leaves residual short exposure blocks;
   - the LAB fixture drives the real risk gateway policy, not only a proof-harness row.

5. Keep all remediation non-live: no Redis writes, no exchange adapters, no order placement/cancelation, no leverage/margin changes, no service restarts, and no deployment.
