# Codex Parallel Review - Risk Gateway Default Deny MVP

Review timestamp: 2026-05-11 05:25:47

Verdict: BLOCKED

Scope inspected:
- `v2/backend/app/domain/risk_gateway/`
- `v2/backend/app/services/risk_gateway/`
- `v2/backend/app/composition/risk_gateway/`
- `v2/backend/app/domain/orchestrator_decision/`
- `v2/backend/app/services/orchestrator_decision/`
- `v2/backend/app/domain/external_manual_position_quarantine/`
- `v2/backend/app/services/external_manual_position_quarantine/`
- `v2/backend/tests/unit/domain/risk_gateway/`
- `v2/backend/tests/unit/services/risk_gateway/`
- `v2/backend/tests/unit/composition/risk_gateway/`
- `v2/backend/tests/unit/replay_case_lab_hedge_unwind/`
- `v2/backend/tests/unit/services/external_manual_position_quarantine/`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/`
- `claude_worklog/phase2_core_rebuild/risk_gateway/`
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`

Validation run:
- Not run. This pass was read-only source/worklog inspection; no Redis, live services, orders, leverage, margin, deployment, or live-trading surfaces were touched.

## Findings

### BLOCKER 1 - Risk gateway still allows tradable inputs by action mirror, not by default-deny policy

`v2/backend/app/services/risk_gateway/service.py:49-60` maps `open_long` directly to `allow_proceed_long`, `open_short` directly to `allow_proceed_short`, `hold` to deny, and `abstain` to deny. There is no required risk context, policy bundle, stale/degraded source state, quarantine flag, current exposure, proposed exposure, or hedge-unwind context before an allow.

The behavior is intentional in the 2G.B spec: `claude_worklog/phase2_core_rebuild/risk_gateway_impl/10_PHASE_2G_B_RISK_GATEWAY_ASSEMBLER_SERVICE_SPEC.md:102-114` defines exactly that four-branch derivation table and explicitly says `deny_default` is not emitted. The test `v2/backend/tests/unit/services/risk_gateway/test_assemble_never_emits_deny_default_for_orchestrator_inputs.py:5-42` locks this in.

Impact: an upstream `OrchestratorDecisionRecord` with `open_long` or `open_short` is sufficient to produce a risk allow. That is not an enforceable default-deny gateway for the requested MVP checks.

### BLOCKER 2 - Stale data blocks are upstream-only and not independently enforced by risk gateway

The orchestrator service converts stale or missing trainer prediction freshness to `abstain` at `v2/backend/app/services/orchestrator_decision/service.py:77-82`, and the risk gateway then maps `abstain` to `deny_orchestrator_abstained` at `v2/backend/app/services/risk_gateway/service.py:58-60`.

The risk decision record itself carries only lineage IDs, symbol, risk action/reason, input decision action/reason, timestamp, and `live_blocked` at `v2/backend/app/domain/risk_gateway/record.py:56-68`. It does not carry freshness age, market-data source freshness, degraded/fail-closed state, or the original prediction freshness flag. The stale test `v2/backend/tests/unit/services/risk_gateway/test_assemble_deny_orchestrator_abstained_for_abstain_freshness_stale.py:5-24` proves only that an already-abstained stale decision is mirrored as deny.

Impact: risk gateway cannot independently block stale SMC/liquidation/OI/orderbook/market data, and it cannot detect a tradable orchestrator input whose stale context has been lost or bypassed.

### BLOCKER 3 - Hedge unwind residual exposure blocks are represented as replay evidence, not risk gateway policy

The legacy LAB failure requires V2 to evaluate remaining net exposure before closing a protective hedge leg and to keep hedge, reduce/close short, block hedge close, or mark the action unsafe (`claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md:25-56`).

The risk gateway has no fields for current position, hedge leg being closed, residual short exposure, net exposure before/after, squeeze/liquidity/OI/orderbook context, or proposed exposure (`v2/backend/app/domain/risk_gateway/record.py:56-68`). The assembler only evaluates `decision.decision_action` (`v2/backend/app/services/risk_gateway/service.py:49-60`).

The LAB replay tests assert typed paper/replay mirror sequences. `v2/backend/tests/unit/replay_case_lab_hedge_unwind/test_lab_hedge_unwind_replay_case.py:142-154` checks that a prebuilt `block_hedge_close` fixture has a third-step `mirror_deny_default`, but no test drives risk gateway with hedge exposure inputs and proves the gateway derives that block.

Impact: LAB-like coverage exists as non-live evidence/projection shape, but not as an enforceable risk-gateway decision path.

### BLOCKER 4 - Manual/external position quarantine does not feed risk gateway allow/deny

The quarantine service accepts a `RiskDecisionRecord` plus a `ManualPositionFlag` and returns a separate `ExternalPositionQuarantineRecord` at `v2/backend/app/services/external_manual_position_quarantine/service.py:12-48`. It mirrors the already-produced risk decision; it does not influence whether that risk decision is allow or deny.

The post-MVP audit already states that the Phase 2G risk-gateway base layer cannot satisfy manual/external position prohibition by itself because the reason taxonomy has no manual/external position member (`claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/03_PHASE_2W_NEXT_CONSOLIDATED_MILESTONE_RECOMMENDATION.md:8-14`). The same doc scopes 2X as typed contract and non-live unit tests only (`...RECOMMENDATION.md:28-35`).

Impact: quarantined manual/external/protective positions can be recorded separately, but risk gateway still allows `open_long`/`open_short` without consuming quarantine state.

### BLOCKER 5 - `deny_default` is reserved/constructible but not reachable from the risk gateway assembler

The domain allows `deny_default` for tradable input actions (`v2/backend/app/domain/risk_gateway/record.py:135-140`), which is useful for future fail-closed policy. But the service does not import or emit it (`v2/backend/app/services/risk_gateway/service.py:12-20`, `49-60`), and the regression test asserts it is never emitted for orchestrator inputs.

Impact: the exact reason needed for default-deny stale/quarantine/residual-exposure policy is present only as a value-object shape, not as runnable gateway behavior.

## Proposed non-live autofix tasks

1. Extend the risk gateway service/composition API with an explicit immutable policy input object carrying stale/degraded source state, manual/external quarantine state, current exposure, proposed exposure, and hedge/residual exposure context.
2. Change `open_long` and `open_short` handling to default to `deny_default` unless every required non-live policy input is present and passing.
3. Add risk-gateway tests where tradable orchestrator decisions are denied for stale/missing trainer freshness and stale/missing SMC/liquidation/OI/orderbook source state.
4. Add LAB hedge-unwind risk-gateway tests that drive the gateway with "close protective long while residual short remains" inputs and assert `deny_default` unless the proposal keeps hedge, closes short, or reduces residual short exposure.
5. Wire `ManualPositionFlag` or a minimal quarantine summary into risk gateway evaluation and add tests that quarantined manual/external/protective/unattributed/duplicate positions deny risk-add while monitor-only remains non-live.
6. Keep the autofix bounded to pure dataclasses/services/composition/tests and worklog evidence. Do not add Redis writes, exchange adapters, order placement/cancel, leverage/margin changes, live mode flips, service restarts, or deployment.

## Notes

The inspected code preserves non-live safety posture through `live_blocked=True` and pure unit-testable services. The blocker is functional scope: the current risk gateway is a lineage-preserving mirror of orchestrator action, not the default-deny policy layer required to block stale data, manual/external position risk-adds, or LAB hedge-unwind residual exposure.
