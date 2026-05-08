# Codex Parallel Review - Risk Gateway Default Deny MVP

Review mode: read-only parallel review, except for this requested report artifact and matching GO/NO-GO artifact.

Scope inspected:
- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl`
- `claude_worklog/phase2_core_rebuild/risk_gateway`
- `claude_worklog/legacy_failure_cases`

Validation run:
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider v2/backend/tests/unit/domain/risk_gateway v2/backend/tests/unit/services/risk_gateway v2/backend/tests/unit/composition/risk_gateway v2/backend/tests/unit/replay_case_lab_hedge_unwind -q`
- Result: 100 passed in 0.26s.

Decision: BLOCKED.

## Findings

### BLOCKER 1 - Default deny is not enforced for tradable orchestrator decisions

`v2/backend/app/services/risk_gateway/service.py:49-60` maps `open_long` directly to `allow_proceed_long` and `open_short` directly to `allow_proceed_short`. There is no independent risk-gateway gate between an orchestrator proceed decision and a risk allow.

`v2/backend/app/domain/risk_gateway/record.py:15` reserves `deny_default`, and `record.py:135-140` validates that `deny_default` can pair with tradable inputs. However, the assembler does not emit it.

The test suite locks this gap in place: `v2/backend/tests/unit/services/risk_gateway/test_assemble_never_emits_deny_default_for_orchestrator_inputs.py:5-42` asserts that all normal orchestrator inputs never produce `deny_default`.

Impact: the "default deny behavior" requested for this review is only a taxonomy placeholder plus `live_blocked=True`, not an actual default-deny risk decision for tradable requests that lack an explicit risk allow condition.

### BLOCKER 2 - Stale data blocks are delegated upstream, not enforced by the risk gateway

`v2/backend/app/services/orchestrator_decision/service.py:77-82` converts missing or stale prediction freshness into orchestrator abstain decisions. The risk gateway then maps any abstain to `deny_orchestrator_abstained` at `v2/backend/app/services/risk_gateway/service.py:58-60`.

The risk gateway record only preserves `input_decision_reason_code`; it does not carry freshness age, per-source freshness, feature freshness, or any independent stale-data threshold. If a caller supplies a valid `open_long` or `open_short` `OrchestratorDecisionRecord`, the risk gateway has no stale-data context with which to block it.

Impact: stale data blocks exist only if the upstream orchestrator already abstained. The risk gateway itself is not default-denying stale data.

### BLOCKER 3 - Hedge unwind residual exposure blocking is not implemented in the risk gateway

The legacy LAB failure case requires V2 to evaluate remaining net exposure before closing a protective hedge leg and to keep/reduce/close/block/mark unsafe when residual exposure is dangerous. See `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md:25-56`.

The risk gateway input surface is only `decision` plus `now_ms_clock` (`v2/backend/app/services/risk_gateway/service.py:25-29`). `RiskDecisionRecord` has no position, hedge state, residual exposure, order intent, close-leg intent, or net-after-close fields (`v2/backend/app/domain/risk_gateway/record.py:56-68`).

There are LAB replay tests, but they use synthetic paper ledger outcomes. `v2/backend/tests/unit/replay_case_lab_hedge_unwind/test_lab_hedge_unwind_replay_case.py:142-154` proves a prebuilt block-hedge-close scenario can be represented as `mirror_deny_default`; it does not prove the risk gateway detects residual exposure or emits the block.

Impact: the LAB hedge unwind failure is covered as replay evidence, not as an enforced risk-gateway default-deny behavior.

### BLOCKER 4 - Manual/external position quarantine is absent

Searches across `v2/backend/app` and relevant tests found no risk-gateway quarantine model for manual or external positions. The only manual-position-adjacent code found is symbol-universe manual override logic, not position quarantine.

The risk gateway has no account position snapshot, position provenance, reconciliation state, quarantine flag, or deny reason for external/manual exposure. Current allowed risk reasons are only `allow_proceed_long`, `allow_proceed_short`, `deny_orchestrator_abstained`, `deny_orchestrator_held`, and `deny_default` (`v2/backend/app/domain/risk_gateway/record.py:11-15`).

Impact: a valid orchestrator proceed decision can be risk-allowed without proving positions are V2-owned or unquarantined.

## Passing Evidence

- Domain, service, composition, and LAB replay tests pass in the narrow run above.
- `live_blocked=True` is enforced in the risk gateway domain at `v2/backend/app/domain/risk_gateway/record.py:214-218`.
- The live API surface remains scaffold/default blocked; `/risk-decisions` and `/risk` are metadata-only in `v2/backend/app/api/v1/risk_decisions.py` and `v2/backend/app/api/v1/risk.py`.
- No Redis write, live restart, live trading enablement, order placement, leverage/margin mutation, or deployment action was performed during this review.

## Proposed Non-Live Autofix Tasks

1. Add a non-live `RiskGatewayContext` or equivalent value object consumed by `assemble_risk_decision_record`, carrying at minimum freshness status/age, position provenance/quarantine status, hedge state, net exposure before/after, and proposed intent type.
2. Change the risk gateway assembler to fail closed for tradable `open_long`/`open_short` unless all required context gates are explicitly healthy. Emit `deny_default` or more specific deny reasons for blocked tradable inputs.
3. Add domain constants and tests for stale-data risk-gateway denies, manual/external position quarantine denies, and hedge-unwind residual-exposure denies.
4. Convert the LAB replay case from synthetic ledger projection only into a service/composition test that feeds a hedge-close context with residual short exposure into the risk gateway and asserts a deny/unsafe result.
5. Keep all fixes non-live: no Redis writes, no live exchange adapters, no live order placement, no leverage/margin changes, no service restart, and no deployment.

CODEX_PARALLEL_REVIEW_RISK_GATEWAY_DEFAULT_DENY_BLOCKED
