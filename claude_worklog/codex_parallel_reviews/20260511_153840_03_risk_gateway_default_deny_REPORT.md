# Codex Parallel Review - Risk Gateway Default Deny MVP

Review date: 2026-05-11
Mode: read-only parallel review; no Redis, no live services, no orders, no leverage/margin changes
Result: BLOCKED

## Scope Inspected

- `v2/backend/app/domain/risk_gateway/`
- `v2/backend/app/services/risk_gateway/`
- `v2/backend/app/composition/risk_gateway/`
- `v2/backend/app/proof/non_live_operational_proof.py`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`
- `v2/backend/app/proof/external_manual_position_quarantine.py`
- `v2/backend/tests/unit/domain/risk_gateway/`
- `v2/backend/tests/unit/services/risk_gateway/`
- `v2/backend/tests/unit/composition/risk_gateway/`
- `v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py`
- `v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py`
- `v2/backend/tests/unit/proof/test_external_manual_position_quarantine.py`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/`
- `claude_worklog/phase2_core_rebuild/risk_gateway/`
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`

## Summary

The current risk gateway MVP is a pure orchestrator-decision mapper. It preserves `live_blocked=True`, has no observed Redis/exchange/live side effects in the risk-gateway package, and denies upstream `hold` or `abstain` decisions.

It does not meet the requested Risk Gateway Default Deny safety bar. Valid upstream `open_long` and `open_short` decisions are converted directly to `allow` without a required safety context. Stale data, hedge-unwind residual exposure, manual/external quarantine, and the LAB short-squeeze failure case are represented in separate deterministic proof fixtures, but they are not enforced by the risk gateway decision path.

## Evidence

- `v2/backend/app/services/risk_gateway/service.py:49-60` maps `open_long` and `open_short` to `allow`; only `hold` and `abstain` map to `deny`.
- `v2/backend/app/services/risk_gateway/service.py:67-78` emits a `RiskDecisionRecord` with lineage and `live_blocked=True`, but accepts no source freshness, position, quarantine, hedge, residual exposure, or squeeze context.
- `v2/backend/app/domain/risk_gateway/record.py:56-68` defines the risk decision record fields. There are no fields for stale source state, exchange/account state, position ownership, manual/external quarantine, hedge state, or net exposure before/after.
- `v2/backend/app/domain/risk_gateway/record.py:135-140` supports `deny_default` only as a domain reason for tradable inputs.
- `v2/backend/tests/unit/services/risk_gateway/test_assemble_never_emits_deny_default_for_orchestrator_inputs.py:5-42` explicitly verifies that the assembler never emits `deny_default` for valid orchestrator inputs.
- `v2/backend/app/proof/non_live_operational_proof.py:100-118` includes a deterministic stale-data block fixture, and `v2/backend/app/proof/non_live_operational_proof.py:138-175` includes hedge residual exposure and LAB fixtures.
- `v2/backend/app/proof/non_live_operational_proof.py:179-186` computes deny for those proof fixtures from fixture attributes, not by invoking the actual risk gateway assembler.
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md` requires V2 to evaluate remaining net exposure before closing a protective hedge leg and to keep, reduce, close, block, or mark unsafe. The implemented risk gateway has no input capable of making that decision.

## Check Results

- Default deny behavior: BLOCKED. The gateway has a `deny_default` reason constant, but the service directly allows upstream `open_long` and `open_short` and intentionally never emits `deny_default` for valid orchestrator records.
- Stale data blocks: PARTIAL/BLOCKED. Stale trainer prediction freshness can be denied if the orchestrator first emits `abstain_freshness_stale`, but the gateway itself does not require or evaluate stale market, SMC, liquidation, OI, orderbook, account, exchange, or position-source state.
- Hedge unwind residual exposure blocks: BLOCKED. The risk gateway cannot represent `close_protective_long`, remaining short exposure, net exposure after close, or short-squeeze context.
- Manual/external position quarantine: BLOCKED. Quarantine proof code exists, but quarantine state is not an input to `assemble_risk_decision_record` and cannot prevent an `allow` at the gateway boundary.
- LAB-like failure case coverage: PARTIAL/BLOCKED. LAB appears in non-live proof fixtures and tests, but those tests validate fixture-generated proof payloads rather than direct risk gateway enforcement.

## Verification

Command run:

`PYTHONPATH=. .venv/bin/python -m pytest -q v2/backend/tests/unit/domain/risk_gateway v2/backend/tests/unit/services/risk_gateway v2/backend/tests/unit/composition/risk_gateway v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py v2/backend/tests/unit/proof/test_external_manual_position_quarantine.py v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py`

Result: 106 passed, 1 failed.

Failure:

- `v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py::test_harness_does_not_use_live_side_effect_terms` fails because its broad scan of `v2/backend/app/proof` finds `create_order`, `cancel_order`, `change_leverage`, and `change_margin` strings in `v2/backend/app/proof/readonly_market_exchange_data_plane.py`.

## Concrete Blockers

1. The risk gateway allows tradable actions without a required fail-closed safety context.
2. `deny_default` is reserved but not emitted by the service for valid orchestrator inputs.
3. Stale-data enforcement is delegated upstream or to proof fixtures, not enforced at the gateway boundary for all required source classes.
4. Hedge close and residual exposure state cannot be expressed in the implemented risk gateway API.
5. Manual/external quarantine state cannot be expressed in the implemented risk gateway API.
6. LAB failure coverage is proof-level and fixture-derived, not direct gateway unit coverage.
7. The relevant proof test slice has a current safety-token failure.

## Proposed Non-Live Autofix Tasks

1. Add a pure `RiskGatewaySafetyContext` domain record with required fields for source freshness, account/position snapshot freshness, quarantine classification, ownership, requested position action, hedge/protective-leg state, net exposure before/after, residual exposure, and squeeze/liquidity warning flags.
2. Add a pure evaluator that requires this context before any tradable allow. Missing, unknown, stale, quarantined, manual/external, unsafe hedge-close, or residual naked exposure context should emit `deny` with a concrete reason.
3. Add deny reason constants such as `deny_stale_safety_context`, `deny_missing_safety_context`, `deny_manual_external_quarantine`, `deny_hedge_unwind_residual_exposure`, and `deny_unknown_safety_context`.
4. Promote the stale-data, quarantine, hedge residual exposure, and LAB scenarios from proof fixtures into direct risk gateway unit tests that call the evaluator and assert `risk_action == "deny"` with the expected reason.
5. Keep all fixes pure and non-live: no Redis writes, exchange clients, FastAPI lifecycle registration, order placement/canceling, leverage/margin changes, service restarts, or deployments.
6. Fix the proof safety-token test non-live by narrowing its scan or renaming/splitting forbidden stub method tokens in `readonly_market_exchange_data_plane.py` without adding any live exchange capability.

## Decision

CODEX_PARALLEL_REVIEW_BLOCKED
