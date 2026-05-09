# Codex Parallel Review - Risk Gateway Default Deny MVP

Verdict: BLOCKED.

## Scope Inspected

- `v2/backend/app/domain/risk_gateway/`
- `v2/backend/app/services/risk_gateway/`
- `v2/backend/app/composition/risk_gateway/`
- `v2/backend/tests/unit/domain/risk_gateway/`
- `v2/backend/tests/unit/services/risk_gateway/`
- `v2/backend/tests/unit/composition/risk_gateway/`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/`
- `claude_worklog/phase2_core_rebuild/risk_gateway/`
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`

## What Passes

- The risk-gateway value object enforces `live_blocked=True`.
- The assembler is pure, does not import Redis/live/exchange surfaces, and validates a real `OrchestratorDecisionRecord`.
- Orchestrator `hold` and `abstain` map to risk `deny`.
- Upstream stale/missing freshness can reach risk gateway as orchestrator `abstain`, and then maps to `deny_orchestrator_abstained`.
- Focused non-live unit verification passed:
  - `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/unit/domain/risk_gateway v2/backend/tests/unit/services/risk_gateway v2/backend/tests/unit/composition/risk_gateway`
  - Result: `85 passed in 0.23s`.

## Blockers

1. Default deny is not actually enforced for tradable actions at the risk gateway.
   - Evidence: `v2/backend/app/services/risk_gateway/service.py` maps `open_long` to `risk_action="allow"` and `allow_proceed_long`, and maps `open_short` to `risk_action="allow"` and `allow_proceed_short`.
   - The reserved `deny_default` reason exists only in the domain value object. The assembler deliberately never emits it, per the 2G.B spec and tests.
   - Result: a valid upstream `open_long` or `open_short` can pass the risk gateway without any gateway-local safety check.

2. Stale data blocking is upstream-dependent, not gateway-default-deny.
   - Evidence: stale/missing freshness is handled in `v2/backend/app/services/orchestrator_decision/service.py` by converting predictions to `abstain_*`; risk gateway only mirrors that abstain into `deny_orchestrator_abstained`.
   - There is no risk-gateway input carrying feature age, freshness provenance, source timestamps, or stale-data flags.
   - Result: risk gateway cannot independently default-deny stale data if an upstream component misclassifies or omits freshness state.

3. Hedge unwind residual exposure blocking is absent.
   - Evidence: no risk-gateway domain/service/composition fields or tests model current position, proposed close, protective hedge leg, net exposure before/after, liquidation/squeeze context, or residual short/long exposure.
   - The LAB failure case requires evaluating remaining net exposure before closing a protective hedge leg. The implemented gateway only receives an orchestrator decision record.
   - Result: the LAB-style failure can only be represented in proof fixtures, not blocked by the risk gateway implementation.

4. Manual/external position quarantine is absent.
   - Evidence: no risk-gateway input or test covers position provenance, external/manual detection, quarantine state, exchange-reconciled position snapshots, or unknown ownership.
   - Result: manually opened or externally modified positions cannot be quarantined by the gateway before allowing new risk decisions.

5. LAB-like failure coverage is proof-only, not gateway behavior coverage.
   - Evidence: `v2/backend/app/proof/non_live_operational_proof.py` and `historical_30d_replay_and_paper_proof.py` include LAB/hedge-unwind proof scenarios, but the focused risk-gateway tests only cover value-object invariants and orchestrator-action mapping.
   - Result: proof artifacts assert expected non-live outcomes, but no executable risk-gateway test fails if hedge-unwind residual exposure blocking is missing.

## Proposed Non-Live Autofix Tasks

1. Add a gateway-local risk input value object for non-live evaluation:
   - orchestrator decision
   - feature freshness/status metadata
   - reconciled position snapshot
   - proposed intent/action type
   - position provenance/quarantine state
   - hedge relationship and net exposure before/after

2. Extend risk reasons without enabling live behavior:
   - `deny_default`
   - `deny_stale_data`
   - `deny_manual_external_position_quarantine`
   - `deny_hedge_unwind_residual_exposure`
   - optional structured subreason fields for audit/proof.

3. Change the gateway assembler/evaluator to default-deny tradable actions unless all required non-live safety inputs are present, fresh, internally owned, and exposure-safe.

4. Add gateway unit tests for:
   - missing safety context denies by default
   - stale feature/source data denies
   - valid `open_long/open_short` only allows when all safety gates pass
   - manual/external position provenance denies
   - hedge-leg close that leaves naked residual exposure denies
   - LABUSDT hedge-unwind short-squeeze fixture denies

5. Add a non-live integration harness that runs the LAB fixture through the actual risk gateway code path, not only proof-summary builders.

## Safety Observations

- No legacy bot path was modified.
- No Redis command was executed.
- No live service restart, deployment, order action, leverage/margin change, or live-trading enablement was performed.

