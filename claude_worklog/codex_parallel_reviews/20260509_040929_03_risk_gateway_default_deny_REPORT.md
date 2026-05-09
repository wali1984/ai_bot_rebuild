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

The Risk Gateway Default Deny MVP remains non-live and fail-closed at the record/live-blocking layer, but it is not ready for the requested safety bar. The implemented gateway accepts only an `OrchestratorDecisionRecord` and a clock, maps tradable orchestrator decisions directly to allow, and has no input surface for hedge residual exposure or manual/external position quarantine.

## Evidence Reviewed

- `v2/backend/app/domain/risk_gateway/record.py`
  - `RiskDecisionRecord` is frozen and slotted.
  - `live_blocked` must be `True` (`_validate_live_blocked`, lines 214-218).
  - `deny_default` exists as a valid taxonomy member and is restricted to tradable inputs (`open_long` / `open_short`) at lines 135-140.
- `v2/backend/app/services/risk_gateway/service.py`
  - `open_long` maps to `allow_proceed_long` at lines 49-51.
  - `open_short` maps to `allow_proceed_short` at lines 52-54.
  - `hold` maps to `deny_orchestrator_held` at lines 55-57.
  - `abstain` maps to `deny_orchestrator_abstained` at lines 58-60.
  - Returned records always set `live_blocked=True` at line 78.
- `v2/backend/app/composition/risk_gateway/runtime.py`
  - Pure binder around `assemble_risk_decision_record`.
  - No Redis, exchange, HTTP, order, leverage, margin, deployment, or live-trading behavior observed.
- `v2/backend/app/services/orchestrator_decision/service.py`
  - Stale/missing prediction freshness becomes abstain at lines 77-82.
  - That abstain is denied by the risk gateway path.
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`
  - Requires evaluating remaining net exposure before closing a protective hedge leg.
  - Required tests include keep hedge, reduce short, close short, block hedge close, or mark unsafe.
- `v2/backend/tests/unit/replay_case_lab_hedge_unwind/`
  - Contains LAB replay/ledger mirror outcomes, including `block_hedge_close`.
  - The fixtures hand-author paper ledger sequences; they do not derive a residual-exposure block from the risk gateway.
- `v2/backend/app/proof/non_live_operational_proof.py`
  - Contains non-live proof scenarios for stale data and hedge residual exposure.
  - This is a proof harness artifact, not the implemented risk gateway service/composition gate.

## Checks

### Default Deny Behavior

Partial pass.

Implemented:
- `RiskDecisionRecord.live_blocked` is mandatory true.
- Invalid risk action/reason combinations fail domain construction.
- `hold` and `abstain` become typed denies.
- Unrecognized decision action has a defensive service error path, though normal `OrchestratorDecisionRecord` validation prevents such values.

Blocking gap:
- Tradable actions are allowed by default. The service maps `open_long` and `open_short` straight to allow without an independent risk policy gate.
- `deny_default` is present in the domain taxonomy but the assembler intentionally never emits it for orchestrator inputs; this is also asserted by `test_assemble_never_emits_deny_default_for_orchestrator_inputs.py`.

### Stale Data Blocks

Pass for the staged prediction-to-orchestrator-to-risk path.

Evidence:
- Orchestrator service maps stale prediction freshness to `decision_action="abstain"` and `decision_reason_code="abstain_freshness_stale"`.
- Risk gateway maps abstain to `risk_action="deny"` and `risk_reason_code="deny_orchestrator_abstained"`.
- Service tests cover stale and missing freshness abstains.

Residual gap:
- The risk gateway itself has no independent feature-age, market-data-age, account-state-age, or policy-context freshness input. It relies entirely on upstream orchestrator freshness classification.

### Hedge Unwind Residual Exposure Blocks

Blocked.

The reviewed risk gateway API cannot represent:
- current position state
- manual/external exchange position state
- hedge state
- protective-leg identity
- proposed action type such as `close_protective_long`
- net exposure before and after the proposed action
- residual exposure threshold
- squeeze/liquidity/OI/funding/orderbook context

Because `assemble_risk_decision_record` accepts only `decision` and `now_ms_clock`, it cannot know that closing a long hedge would leave naked residual short exposure. A tradable upstream action remains an allow.

### Manual / External Position Quarantine

Blocked.

No reviewed risk gateway domain, service, composition, or focused test surface models:
- manual position source
- external exchange position source
- unsynced account position
- quarantined symbol/account state
- quarantine clear/active state
- quarantine deny reason

Focused search over risk gateway source and tests returned no `manual`, `external`, or `quarantine` matches.

### LAB-Like Failure Case Coverage

Partial pass, blocked for readiness.

Implemented:
- The legacy LAB failure case is documented.
- Replay fixtures cover legacy, keep-hedge, close-short, reduce-short, and block-hedge-close outcome shapes.
- Non-live proof scenarios include `lab_hedge_unwind_short_squeeze`.

Blocking gap:
- The LAB replay tests verify typed mirror sequences, not risk gateway enforcement.
- The legacy all-allow outcome is still a valid replay sequence for evidence capture.
- No test feeds hedge state plus projected residual exposure into the risk gateway and asserts a risk-derived deny/unsafe result.

## Verification

Read-only inspection only. I did not run tests because this review mode requested read-only behavior and pytest may write cache or bytecode artifacts unless specially constrained.

No Redis writes, Redis deletes, service restarts, live orders, leverage/margin changes, live trading enablement, deployments, or secret exposure were performed.

## Concrete Blockers

1. Hedge unwind residual exposure cannot be blocked by the current risk gateway API.
   - Current cause: `assemble_risk_decision_record` accepts only `decision` and `now_ms_clock`.
   - Required for readiness: a pure non-live risk context or policy evaluator that can represent hedge state and projected residual exposure.

2. Manual/external position quarantine cannot be enforced by the current risk gateway API.
   - Current cause: no position-source, account-sync, or quarantine-state fields exist in risk gateway domain/service/composition.
   - Required for readiness: explicit typed quarantine inputs and deny reasons for manual/external/unsynced positions.

3. LAB coverage is evidence capture, not executable risk-gateway safety coverage.
   - Current cause: LAB replay fixtures hand-author paper ledger outcomes instead of deriving a block from risk gateway policy.
   - Required for readiness: a non-live test where a hedge-close proposal with residual short exposure is denied or marked unsafe by the risk gateway path.

## Proposed Non-Live Autofix Tasks

1. Add a pure risk gateway policy input value object.
   - Include position source, account sync/quarantine state, hedge state, proposed intent, current net exposure, projected net exposure, protective-leg close flag, and context freshness.
   - Keep it deterministic and dependency-free: no Redis, exchange, HTTP, order, leverage, margin, or live execution dependencies.

2. Add an enriched pure policy evaluator or sibling assembler.
   - Preserve the existing simple assembler for compatibility.
   - Emit deny/unsafe for stale context, active quarantine, manual/external unsynced positions, and hedge-close residual exposure.

3. Add residual exposure tests.
   - Hedge close leaves residual short exposure: deny/unsafe.
   - Hedge close with paired short close/reduce: allow or safe according to spec.
   - Missing/stale exposure context: deny.
   - Squeeze/liquidity warning context plus residual exposure: deny.

4. Add quarantine tests.
   - Manual position present on same symbol/account: deny.
   - External unsynced exchange position present: deny.
   - Quarantine active: deny.
   - Quarantine cleared by explicit non-live state: continue normal policy evaluation.

5. Upgrade LAB coverage to policy-derived assertions.
   - Feed LAB hedge state and projected residual exposure into the risk gateway policy evaluator.
   - Assert the legacy all-allow hedge-close path fails safety.
   - Assert keep-hedge, close-short, reduce-short, or block-hedge-close satisfies the non-live safety invariant.

RISK_GATEWAY_DEFAULT_DENY_MVP_PARALLEL_REVIEW_BLOCKED
