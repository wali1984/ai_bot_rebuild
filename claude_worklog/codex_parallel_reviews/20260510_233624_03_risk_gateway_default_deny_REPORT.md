# Codex Parallel Review - Risk Gateway Default Deny MVP

Review timestamp: 2026-05-10 23:36:24

Verdict: BLOCKED

Scope inspected:
- `v2/backend/app/domain/risk_gateway/`
- `v2/backend/app/services/risk_gateway/`
- `v2/backend/app/composition/risk_gateway/`
- `v2/backend/tests/unit/domain/risk_gateway/`
- `v2/backend/tests/unit/services/risk_gateway/`
- `v2/backend/tests/unit/composition/risk_gateway/`
- `v2/backend/tests/unit/replay_case_lab_hedge_unwind/`
- `v2/backend/app/services/external_manual_position_quarantine/`
- `v2/backend/app/services/degraded_state_fail_closed_gates/`
- `v2/backend/app/proof/non_live_operational_proof.py`
- `v2/backend/app/proof/external_manual_position_quarantine.py`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/`
- `claude_worklog/phase2_core_rebuild/risk_gateway/`
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`

Validation run:
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider -q v2/backend/tests/unit/domain/risk_gateway v2/backend/tests/unit/services/risk_gateway v2/backend/tests/unit/composition/risk_gateway v2/backend/tests/unit/replay_case_lab_hedge_unwind`
- Result: `100 passed in 0.23s`

## Findings

### BLOCKER 1 - Risk gateway is not default-deny for tradable inputs

`v2/backend/app/services/risk_gateway/service.py:49-54` maps `open_long` directly to `allow_proceed_long` and `open_short` directly to `allow_proceed_short`. There is no policy bundle input, no required risk context, and no explicit "all checks passed" predicate before allow.

This is reinforced by `v2/backend/tests/unit/services/risk_gateway/test_assemble_never_emits_deny_default_for_orchestrator_inputs.py:5-42`, which asserts that open-long/open-short orchestrator inputs must not emit `deny_default`.

Impact: an upstream orchestrator `open_long` or `open_short` decision is sufficient to produce a risk allow. That is not a default-deny gateway.

### BLOCKER 2 - Stale data blocks depend entirely on upstream orchestrator abstain, not risk gateway enforcement

The risk gateway record carries only `risk_decision_id`, lineage IDs, symbol, risk action/reason, input decision action/reason, and `live_blocked` at `v2/backend/app/domain/risk_gateway/record.py:56-69`. It does not carry prediction freshness, feature age, market-data age, degraded source states, or a fail-closed flag.

Stale prediction handling exists upstream in `v2/backend/app/services/orchestrator_decision/service.py:77-82`, where stale or missing prediction freshness becomes orchestrator `abstain`. The risk gateway then merely maps `abstain` to `deny_orchestrator_abstained` at `v2/backend/app/services/risk_gateway/service.py:58-60`.

Impact: if a tradable orchestrator record is constructed with stale/missing context, or if market data such as SMC/liq/OI/orderbook is stale, risk gateway has no independent stale-data block.

### BLOCKER 3 - Degraded/fail-closed gates exist but are downstream/adjacent, not enforced by risk gateway

`v2/backend/app/domain/degraded_state_fail_closed_gates/degraded_state_record.py:15-72` and `v2/backend/app/services/degraded_state_fail_closed_gates/service.py:14-68` model per-source stale/missing states and derive `fail_closed`.

However, `rg` found no `DegradedStateRecord`, `fail_closed`, or degraded-state dependency in `v2/backend/app/domain/risk_gateway`, `v2/backend/app/services/risk_gateway`, `v2/backend/app/composition/risk_gateway`, or their risk-gateway unit tests.

Impact: default-deny stale-market-data semantics are not wired into the risk allow/deny decision.

### BLOCKER 4 - Hedge unwind residual exposure blocks are represented as proof/replay artifacts, not as risk gateway policy

The legacy failure case requires V2 to evaluate remaining net exposure before closing a protective hedge leg and to keep hedge, reduce/close short, block hedge close, or mark unsafe (`claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md:25-56`).

The risk gateway domain has no fields for current position, hedge leg, requested close action, net exposure before/after, squeeze risk, liquidation cluster, OI, orderbook, funding, or residual exposure (`v2/backend/app/domain/risk_gateway/record.py:56-69`). The service only evaluates `decision.decision_action` (`v2/backend/app/services/risk_gateway/service.py:49-60`).

LAB-like tests under `v2/backend/tests/unit/replay_case_lab_hedge_unwind/` are typed replay projections. They include a `block_hedge_close` fixture with `mirror_deny_default` (`fixtures.py:91-100`) and assert that projection (`test_lab_hedge_unwind_replay_case.py:142-154`), but they do not drive the risk gateway with hedge exposure inputs or prove that risk gateway blocks residual exposure.

Impact: the LAB failure case is covered as non-live evidence shape, but not as an enforceable risk gateway decision path.

### BLOCKER 5 - Manual/external position quarantine does not block risk gateway allows

Manual/external quarantine state exists separately. `ManualPositionFlag` allows `manual_position_quarantined` and `manual_position_not_present` at `v2/backend/app/domain/external_manual_position_quarantine/flag.py:8-16`, and quarantine proof states risk gateway policy `block_risk_add_on_quarantined_symbol_account` at `v2/backend/app/proof/external_manual_position_quarantine.py:275-287`.

The actual risk gateway package has no `ManualPositionFlag` or `ExternalPositionQuarantineRecord` dependency. `rg` returned no quarantine references in risk gateway domain/service/composition/tests.

Impact: a quarantined manual/external position can be recorded in a separate proof path, but risk gateway allow/deny is not conditioned on quarantine state.

## Proposed non-live autofix tasks

1. Extend the risk gateway domain with an explicit immutable policy input/decision model for default-deny checks: policy bundle id, check results, stale/degraded fail-closed state, manual/external quarantine state, position intent, current exposure, proposed exposure after action, and hedge/residual exposure context.
2. Change the risk gateway assembler/composition API so `open_long` and `open_short` default to `deny_default` unless every required non-live policy input is present and passing.
3. Add stale-data risk gateway tests that pass tradable orchestrator decisions with stale/missing prediction freshness and stale/missing SMC/liq/OI/orderbook state, and assert deny.
4. Add hedge unwind risk gateway tests for the LAB residual short exposure case: closing protective long while short remains must produce deny unless the proposed action also closes/reduces the residual short or preserves the hedge.
5. Wire `ManualPositionFlag` or an equivalent quarantine summary into risk gateway evaluation and add tests that quarantined manual/external/protective/duplicate/unattributed positions deny risk-add while monitor-only remains non-live.
6. Keep all autofix work non-live: pure dataclasses/services/tests only; no Redis writes, no order placement/cancel, no leverage/margin changes, no live-service restarts, no deployment.

## Notes

The current risk gateway suite passes, but it validates the present mirror-of-orchestrator MVP rather than the requested default-deny MVP. Because the requested checks are not enforceable in the risk gateway decision path, this review is blocked.
