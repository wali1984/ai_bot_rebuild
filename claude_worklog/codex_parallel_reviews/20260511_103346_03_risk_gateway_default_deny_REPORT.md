# Codex Parallel Review - Risk Gateway Default Deny MVP

Review date: 2026-05-11
Mode: read-only review, no live mutations
Result: BLOCKED

## Scope Inspected

- `v2/backend/app/domain/risk_gateway/`
- `v2/backend/app/services/risk_gateway/`
- `v2/backend/app/composition/risk_gateway/`
- `v2/backend/tests/unit/domain/risk_gateway/`
- `v2/backend/tests/unit/services/risk_gateway/`
- `v2/backend/tests/unit/composition/risk_gateway/`
- `v2/backend/app/services/orchestrator_decision/service.py`
- `v2/backend/app/services/external_manual_position_quarantine/service.py`
- `v2/backend/app/services/degraded_state_fail_closed_gates/service.py`
- `v2/backend/app/proof/non_live_operational_proof.py`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`
- `v2/backend/app/proof/external_manual_position_quarantine.py`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/`
- `claude_worklog/phase2_core_rebuild/risk_gateway/`
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`

Tests were not executed to preserve read-only review posture and avoid cache writes.

## Summary

The implemented Phase 2G default-deny MVP is a narrow pure mapper from `OrchestratorDecisionRecord` to `RiskDecisionRecord`. It correctly keeps `live_blocked=True`, has no Redis/API/live side effects in the inspected risk-gateway source, and denies upstream `hold` / `abstain` actions.

However, it is not ready for the requested Risk Gateway Default Deny safety bar. The risk gateway still allows upstream `open_long` and `open_short` solely from the orchestrator action, and it does not consume stale market-data source states, manual/external position quarantine state, hedge unwind residual exposure state, or LAB-like failure-case predicates. Some of those concepts exist as separate non-live proof or downstream record surfaces, but they are not enforced in the risk gateway decision path.

## Evidence

- `v2/backend/app/services/risk_gateway/service.py:49-60` maps `open_long` and `open_short` directly to `allow`, and only maps `hold` / `abstain` to `deny`.
- `v2/backend/app/services/risk_gateway/service.py:67-78` constructs `RiskDecisionRecord` with lineage and `live_blocked=True`, but has no inputs for degraded source state, quarantine state, position ownership, hedge state, net exposure, liquidation/OI/orderbook context, or residual exposure.
- `v2/backend/app/domain/risk_gateway/record.py:56-68` defines a compact value object without fields for stale data sources, manual/external ownership, hedge unwind, residual exposure, or LAB failure evidence.
- `v2/backend/app/domain/risk_gateway/record.py:135-140` reserves `deny_default`, but the assembler service intentionally never emits it for valid orchestrator inputs.
- `v2/backend/app/services/orchestrator_decision/service.py:77-82` converts stale or missing trainer prediction freshness to upstream `abstain`, which the risk gateway then denies. This covers only trainer prediction freshness propagated through the orchestrator, not stale SMC/liquidation/OI/orderbook data or stale exchange/account state at the gateway boundary.
- `v2/backend/app/services/degraded_state_fail_closed_gates/service.py:14-77` can derive a separate `DegradedStateRecord` from a risk decision plus source states, but it runs after/alongside the risk decision and does not alter the `RiskDecisionRecord` allow/deny result.
- `v2/backend/app/services/external_manual_position_quarantine/service.py:12-52` can assemble a separate quarantine record from an existing risk decision and manual flag, but it does not feed quarantine state into `assemble_risk_decision_record` before an allow is emitted.
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md` requires the risk gateway to evaluate remaining net position before closing a protective hedge leg and to keep/reduce/close/block/mark unsafe. The risk gateway surface has no input capable of representing this decision.

## Blockers

1. Default-deny is not enforced against unknown safety context.

   The gateway allows `open_long` and `open_short` whenever the upstream orchestrator emits those actions. There is no required safety context object and no fail-closed behavior when stale-source/quarantine/exposure inputs are missing. This is not default deny at the gateway boundary; it is default mirror of the orchestrator's tradeable actions.

2. Stale data blocks are incomplete.

   The path blocks stale or missing trainer prediction freshness only if the upstream orchestrator already produced `abstain_freshness_stale` or `abstain_freshness_missing`. The gateway does not directly block stale SMC, liquidation, OI, orderbook, account, position, or exchange source state. The separate degraded-state service records `fail_closed`, but it does not prevent a risk gateway allow.

3. Hedge unwind residual exposure is not enforceable.

   The LAB failure case requires evaluating net exposure after protective hedge close. `RiskDecisionRecord` and `assemble_risk_decision_record` have no fields for current position, hedge leg, proposed close, net exposure before/after, squeeze context, liquidation clusters, OI, funding/basis, volatility expansion, local structure, or paper/shadow alternative. The risk gateway cannot block the LAB hedge-unwind residual exposure scenario from its implemented inputs.

4. Manual/external position quarantine is not in the allow/deny path.

   Manual/external quarantine records exist downstream from a `RiskDecisionRecord`, and non-live proof fixtures describe monitor-only quarantine policy. But `assemble_risk_decision_record` does not accept a quarantine flag and can emit `allow` before quarantine classification is applied.

5. LAB-like coverage is proof-level, not gateway enforcement coverage.

   `v2/backend/app/proof/non_live_operational_proof.py`, `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`, and `v2/backend/app/proof/external_manual_position_quarantine.py` include deterministic LAB/quarantine/stale evidence. Those artifacts are useful, but they do not test the actual risk gateway service rejecting those scenarios.

## Proposed Non-Live Autofix Tasks

1. Add a pure risk-gateway safety context value object.

   Create a non-I/O domain record carrying source freshness states, manual/external quarantine state, position ownership, hedge/protective-leg state, net exposure before/after, and residual exposure classification. Default every missing or unknown required safety dimension to a deny reason.

2. Extend `assemble_risk_decision_record` or add a new pure evaluator wrapper to require the safety context.

   Preserve the existing simple mapper only as an internal helper if needed. The public gateway evaluator should emit `deny` for stale/missing data, quarantined symbol/account, external/manual ownership, unsafe hedge close, residual naked exposure, and unrecognized context before allowing any tradeable action.

3. Add explicit risk reason constants and invariants.

   Add deny reasons such as `deny_stale_safety_context`, `deny_manual_external_quarantine`, `deny_hedge_unwind_residual_exposure`, and `deny_unknown_safety_context`. Keep `live_blocked=True` mandatory.

4. Promote proof cases into gateway unit tests.

   Add unit tests that call the risk gateway evaluator directly for stale source states, missing safety context, manual/external LAB position, protective long close leaving short exposure, and LAB short-squeeze residual exposure. The assertions should verify `risk_action == "deny"` and the concrete deny reason.

5. Keep all fixes non-live.

   Do not add Redis, exchange, FastAPI, order placement, leverage, margin, deployment, or service restart behavior. Use frozen records and pure functions consistent with the existing Phase 2G style.

## Decision

CODEX_PARALLEL_REVIEW_BLOCKED
