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

The current implementation is non-live and keeps `live_blocked=True`, but it is not sufficient for the requested Risk Gateway Default Deny MVP safety checks. The production risk gateway only maps an already-formed `OrchestratorDecisionRecord` to a `RiskDecisionRecord`; it has no independent risk context gate for stale market/account state, manual/external position quarantine, or hedge-unwind residual exposure.

## Evidence

- `v2/backend/app/domain/risk_gateway/record.py`
  - `RiskDecisionRecord` is frozen/slotted and validates the risk action/reason taxonomy.
  - `deny_default` exists as a taxonomy member at lines 11-15 and is valid only with tradable input actions at lines 135-140.
  - `live_blocked` must be `True` at lines 214-218.
- `v2/backend/app/services/risk_gateway/service.py`
  - `open_long` maps directly to `allow` / `allow_proceed_long` at lines 49-51.
  - `open_short` maps directly to `allow` / `allow_proceed_short` at lines 52-54.
  - `hold` maps to `deny` / `deny_orchestrator_held` at lines 55-57.
  - `abstain` maps to `deny` / `deny_orchestrator_abstained` at lines 58-60.
  - Returned records always set `live_blocked=True` at line 78.
- `v2/backend/app/composition/risk_gateway/runtime.py`
  - The composition root is a pure binder around `assemble_risk_decision_record`; no Redis, exchange, order, leverage, margin, deploy, or live-trading side effect was observed.
- `v2/backend/app/services/orchestrator_decision/service.py`
  - Trainer freshness `missing` and `stale` are converted to abstain at lines 77-82, and the risk gateway later denies abstains. This is an upstream stale-data block, not an independent risk gateway freshness gate.
- `v2/backend/app/proof/non_live_operational_proof.py`
  - Static non-live proof scenarios include `stale_data_blocked`, `hedge_close_residual_exposure_blocked`, and `lab_hedge_unwind_short_squeeze` at lines 90-145.
  - `_risk_action()` denies those proof rows from fixture fields at lines 149-156; this is not the production risk gateway service.
- `v2/backend/tests/unit/replay_case_lab_hedge_unwind/test_lab_hedge_unwind_replay_case.py`
  - LAB-like replay tests assert typed mirror ledger/backtest sequences, including a `mirror_deny_default` blocked hedge-close outcome at lines 142-154.
  - The blocked outcome is fixture-authored from `fixtures.py` lines 91-100, not derived by the risk gateway from exposure inputs.
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`
  - The required behavior is to evaluate remaining net position before closing a protective hedge leg, with tests that keep hedge, reduce short, close short, block hedge close, or mark unsafe at lines 25-56.

## Check Results

Default deny behavior: partial pass. The domain rejects invalid records, `live_blocked=False` cannot be constructed, `hold` and `abstain` deny, and unrecognized service actions raise before a risk record is emitted. However, tradable `open_long` and `open_short` are allowed by default whenever the upstream orchestrator emitted them; missing risk context does not force `deny_default`.

Stale data blocks: partial pass. Trainer prediction stale/missing freshness is blocked upstream by the orchestrator abstain path. The risk gateway itself has no direct freshness or age input for feature, market, account, or position state.

Hedge unwind residual exposure blocks: blocked. The production risk gateway accepts only `decision` and `now_ms_clock`; it cannot evaluate protective-leg state, current net exposure, projected residual exposure after close, squeeze context, or whether a hedge-close request should be blocked.

Manual/external position quarantine: blocked. No reviewed risk gateway app/test surface implements manual or external account-position provenance quarantine. Search hits for manual/external are outside the risk gateway quarantine problem or proof-only evidence.

LAB-like failure case coverage: partial pass. The legacy failure case is documented and represented in non-live proof/replay fixtures, but coverage does not prove the production risk gateway derives the LAB block from risk/exposure inputs.

## Concrete Blockers

1. Tradable actions are allowed without required risk context.
   - Impact: `open_long` and `open_short` can become `allow` even if exposure, account, position, or market freshness context is absent.
   - Evidence: `v2/backend/app/services/risk_gateway/service.py` lines 49-54.

2. Manual/external position quarantine is missing.
   - Impact: out-of-band positions cannot force `deny_default` or a quarantine-specific deny before downstream paper/live-like surfaces consume the decision.
   - Evidence: no production risk gateway domain/service/composition input for position provenance, manual state, external state, or quarantine.

3. Hedge-unwind residual exposure policy is missing from the risk gateway boundary.
   - Impact: the LAB failure requirement is represented by static fixtures but not enforced by production risk-gateway logic.
   - Evidence: `assemble_risk_decision_record()` accepts only `decision` and `now_ms_clock`; LAB blocked outcomes are fixture-authored in replay/proof tests.

4. Stale data is not independently default-denied by the risk gateway.
   - Impact: stale data blocks depend on the upstream orchestrator correctly converting stale/missing trainer freshness to abstain; the risk gateway has no direct stale-context contract.
   - Evidence: orchestrator freshness handling is at `v2/backend/app/services/orchestrator_decision/service.py` lines 77-82; risk gateway service has no freshness context parameter.

## Proposed Non-Live Autofix Tasks

1. Add a pure risk context value object under `v2/backend/app/domain/risk_gateway/` with no I/O fields for feature freshness, market/account/position freshness, position provenance, protective hedge state, current net exposure, requested action kind, and projected exposure after action.

2. Extend the pure risk gateway service, or add a pure policy evaluator beside it, so tradable actions require risk context and fail closed to `deny_default` when context is missing, stale, quarantined, externally/manual-positioned, or unsafe.

3. Add explicit quarantine and hedge-residual deny reasons, or document and test `deny_default` as the interim MVP reason for those conditions.

4. Add focused non-live unit tests proving:
   - missing risk context blocks tradable actions;
   - stale feature/market/account/position context blocks tradable actions;
   - manual/external position provenance quarantines;
   - closing a protective hedge leg that leaves residual short exposure blocks;
   - the LAB fixture drives the real risk gateway policy rather than only a proof/replay fixture row.

5. Keep remediation non-live: no Redis writes, no exchange adapters, no order placement/cancelation, no leverage/margin changes, no live service restarts, no deploys, and no live-trading enablement.

## Verification

Read-only inspection only. I did not run pytest in this pass to avoid incidental cache or bytecode writes under read-only parallel review mode. I did not touch `/home/wali/Desktop/AI BOT`, Redis, live services, orders, leverage/margin, deployments, or live trading settings.
