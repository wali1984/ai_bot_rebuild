# Risk Gateway Default Deny MVP Parallel Review

Review date: 2026-05-08

Scope inspected:
- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl`
- `claude_worklog/phase2_core_rebuild/risk_gateway`
- `claude_worklog/legacy_failure_cases`

## Verdict

CODEX_PARALLEL_REVIEW_BLOCKED

The current Risk Gateway Default Deny MVP is safe as a pure non-live derivation surface, but it is not ready for the full requested safety bar. It does not yet model hedge unwind residual exposure or manual/external position quarantine, and the LAB-like failure coverage is currently replay/ledger evidence rather than an executable risk-gateway block.

## Evidence Reviewed

- `v2/backend/app/domain/risk_gateway/record.py`
  - Defines frozen `RiskDecisionRecord`.
  - Enforces `live_blocked is True`.
  - Defines `deny_default` as a valid taxonomy member, with a cross-field rule requiring `open_long` or `open_short` input.
- `v2/backend/app/services/risk_gateway/service.py`
  - Maps `open_long` to `allow_proceed_long`.
  - Maps `open_short` to `allow_proceed_short`.
  - Maps `hold` to `deny_orchestrator_held`.
  - Maps `abstain` to `deny_orchestrator_abstained`.
  - Never emits `deny_default` for orchestrator inputs.
- `v2/backend/app/composition/risk_gateway/runtime.py`
  - Pure binder around the assembler.
  - No Redis, HTTP, exchange, FastAPI, order, leverage, margin, or live-trading behavior.
- `v2/backend/app/services/orchestrator_decision/service.py`
  - Converts stale or missing prediction freshness into `abstain_freshness_stale` / `abstain_freshness_missing`.
  - Risk gateway then converts those abstains into risk denies.
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`
  - Requires V2 to evaluate remaining net exposure before closing a protective hedge leg.
  - Requires keep-hedge, reduce-short, close-short, block-hedge-close, or unsafe marking behavior.
- `v2/backend/tests/unit/replay_case_lab_hedge_unwind/test_lab_hedge_unwind_replay_case.py`
  - Verifies typed replay/ledger mirror sequences for LAB outcomes.
  - Does not exercise the risk gateway assembler against hedge state, residual exposure, price pump, liquidation/OI/orderbook context, or manual/external positions.

## Checks

### Default Deny Behavior

Partial pass.

Implemented:
- `RiskDecisionRecord.live_blocked` must be `True`; constructing with `False` fails closed.
- Invalid risk action/reason combinations fail at domain construction.
- `hold` and `abstain` become typed risk denies.
- Unknown orchestrator action has a defensive service fallback, though normal construction of `OrchestratorDecisionRecord` prevents such values.

Gap:
- Tradable orchestrator actions are allowed by default. `open_long` and `open_short` are not subjected to any risk policy gate beyond upstream orchestrator freshness/health/confidence.
- `deny_default` exists only as a domain taxonomy member and paper/replay mirror reason; the 2G.B assembler intentionally does not emit it.

### Stale Data Blocks

Pass for the current staged path.

Evidence:
- Orchestrator decision service maps stale prediction freshness to `decision_action="abstain"` and `decision_reason_code="abstain_freshness_stale"`.
- Risk gateway service maps that abstain to `risk_action="deny"` and `risk_reason_code="deny_orchestrator_abstained"`.
- Targeted stale tests passed.

Residual gap:
- The risk gateway itself has no independent stale-source age, feature age, market-data age, or policy-bundle freshness check. It relies entirely on the upstream `OrchestratorDecisionRecord`.

### Hedge Unwind Residual Exposure Blocks

Blocker.

The reviewed risk gateway inputs do not include:
- current position state
- hedge state
- residual exposure before/after a proposed close
- protective-leg identity
- reduce-only or close-only intent
- liquidation/OI/orderbook/funding/volatility/liquidity-sweep context
- proposed execution intent type such as hedge close versus open/add

Because `assemble_risk_decision_record` only accepts an `OrchestratorDecisionRecord`, it cannot detect that closing a long hedge leaves residual short exposure. It will allow any upstream `open_long` / `open_short` action and deny only `hold` / `abstain`.

### Manual / External Position Quarantine

Blocker.

No reviewed risk gateway domain, service, or composition surface models:
- manual position source
- external exchange position source
- unsynced account position
- quarantined symbol/account state
- manual override quarantine reason
- external-position block reason

Search results only show unrelated symbol-universe manual overrides and evidence harness fields. There is no risk-gateway quarantine gate.

### LAB-Like Failure Case Coverage

Partial pass, but blocked for risk-gateway readiness.

Implemented:
- A LAB hedge-unwind replay case exists.
- It records typed mirror sequences for legacy, keep-hedge, close-short, reduce-short, and block-hedge-close outcomes.
- The replay case covers `mirror_deny_default` as a paper/replay artifact.

Gap:
- The LAB test does not prove that the risk gateway can compute or enforce the safe outcome.
- It does not feed residual exposure or hedge-close context into risk gateway because that input surface does not exist.
- It allows the legacy all-allow outcome as a valid typed mirror sequence, which is useful evidence capture but not a failing safety regression.

## Verification Run

Commands run:
- `.venv/bin/python -m pytest -q v2/backend/tests/unit/domain/risk_gateway v2/backend/tests/unit/services/risk_gateway v2/backend/tests/unit/composition/risk_gateway`
  - Result: `85 passed in 0.25s`
- `.venv/bin/python -m pytest -q v2/backend/tests/unit/services/orchestrator_decision/test_assemble_abstain_freshness_stale.py v2/backend/tests/unit/services/orchestrator_decision/test_assemble_priority_freshness_missing_over_stale.py v2/backend/tests/unit/services/risk_gateway/test_assemble_deny_orchestrator_abstained_for_abstain_freshness_stale.py v2/backend/tests/unit/replay_case_lab_hedge_unwind/test_lab_hedge_unwind_replay_case.py`
  - Result: `18 passed in 0.04s`

No Redis writes, Redis deletes, service restarts, live orders, leverage/margin changes, live trading enablement, deployments, or secret exposure were performed.

## Concrete Blockers

1. Hedge unwind residual exposure cannot be blocked by the current risk gateway API.
   - Current cause: `assemble_risk_decision_record` accepts only `decision` and `now_ms_clock`.
   - Required for readiness: a non-live risk context or separate pure policy input that can represent hedge state and post-action residual exposure.

2. Manual/external position quarantine cannot be enforced by the current risk gateway API.
   - Current cause: no position-source or quarantine-state fields exist in the risk gateway domain/service/composition surface.
   - Required for readiness: explicit typed quarantine inputs and deny reasons for manual/external/unsynced positions.

3. LAB coverage is evidence capture, not an executable risk-gateway safety assertion.
   - Current cause: LAB replay fixtures hand-author paper ledger outcomes instead of deriving a block from risk gateway residual-exposure logic.
   - Required for readiness: a non-live unit/integration test where a hedge-close proposal with residual short exposure is denied or marked unsafe by the risk gateway path.

## Proposed Non-Live Autofix Tasks

1. Add a pure `RiskGatewayPolicyContext` value object under `v2/backend/app/domain/risk_gateway/`.
   - Fields should include position source, quarantine state, hedge state, current net exposure, projected net exposure after proposed action, protective-leg close flag, freshness status, and deterministic reason fields.
   - Keep `live_blocked=True`; no Redis, exchange, order, leverage, or HTTP dependencies.

2. Extend the assembler with a non-live enriched function, or add a sibling pure policy evaluator.
   - It should emit `deny_default` or more specific deny reasons when tradable inputs fail residual-exposure, stale-context, or quarantine checks.
   - Preserve the existing simple MVP assembler for compatibility if downstream milestones depend on it.

3. Add tests for residual exposure blocks.
   - Hedge close leaves residual short exposure: deny.
   - Hedge close with paired short close/reduce: allow or mark safe according to spec.
   - Missing/stale exposure context: deny.
   - Residual exposure with squeeze/liquidity warning fields: deny.

4. Add tests for manual/external quarantine.
   - Manual position present on same symbol/account: deny.
   - External unsynced exchange position present: deny.
   - Quarantine cleared only by explicit non-live state input: allow normal policy evaluation.

5. Upgrade LAB replay coverage from mirror-only to policy-derived.
   - Build a LAB fixture that passes hedge state and projected residual exposure into the risk gateway policy evaluator.
   - Assert the legacy all-allow sequence fails the safety test.
   - Assert keep-hedge, close-short, reduce-short, or block-hedge-close satisfies the non-live safety invariant.

RISK_GATEWAY_DEFAULT_DENY_MVP_PARALLEL_REVIEW_BLOCKED
