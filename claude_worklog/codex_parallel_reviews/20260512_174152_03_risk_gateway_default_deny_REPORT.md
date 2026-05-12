# Codex Parallel Review - Risk Gateway Default Deny MVP

Review timestamp: 2026-05-12 17:41:52

Scope inspected:
- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl`
- `claude_worklog/phase2_core_rebuild/risk_gateway`
- `claude_worklog/legacy_failure_cases`

Commands run:
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider v2/backend/tests/unit/domain/risk_gateway v2/backend/tests/unit/services/risk_gateway v2/backend/tests/unit/composition/risk_gateway v2/backend/tests/unit/composition/external_manual_position_quarantine v2/backend/tests/unit/services/external_manual_position_quarantine v2/backend/tests/unit/replay_case_lab_hedge_unwind v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py v2/backend/tests/unit/proof/test_external_manual_position_quarantine.py -q`
- Result: `132 passed in 0.33s`

## Verdict

CODEX_PARALLEL_REVIEW_BLOCKED

The implemented Phase 2G risk gateway MVP is live-safe and deterministic for its narrow contract, but it is not ready for the broader "default deny" claim in this review topic. The current executable risk gateway only maps an already-formed `OrchestratorDecisionRecord` into a `RiskDecisionRecord`. It does not directly consume stale source-state gates, hedge-unwind residual exposure state, or manual/external position quarantine state.

## Passing Evidence

Default-deny/live-block invariants are present in the value object:
- `v2/backend/app/domain/risk_gateway/record.py` requires `live_blocked is True`.
- Allow records require `allow_` reason codes and deny records require `deny_` reason codes.
- `deny_default` is reserved and constrained to tradable upstream actions.

Assembler behavior is deterministic and side-effect free:
- `v2/backend/app/services/risk_gateway/service.py` validates the input decision, calls the supplied clock once, derives `rd_` risk decision IDs, maps `hold`/`abstain` to deny, maps `open_long`/`open_short` to allow, and always emits `live_blocked=True`.
- The service and composition test suites check public surface, import isolation, clock behavior, lineage propagation, live-block enforcement, stale/freshness abstain propagation, and that the assembler does not emit reserved `deny_default`.

Stale prediction data is blocked when it reaches the risk gateway as an orchestrator abstain:
- `v2/backend/app/services/orchestrator_decision/service.py` maps `freshness_flag == stale` to `decision_action=abstain` and `decision_reason_code=abstain_freshness_stale`.
- `v2/backend/app/services/risk_gateway/service.py` maps any `abstain` to `risk_action=deny` and `risk_reason_code=deny_orchestrator_abstained`.

Adjacent proof and composition suites exist:
- Manual/external position quarantine domain/service/composition records enforce `live_blocked=True`.
- Degraded-state records derive `fail_closed=True` from stale or missing per-source states.
- LAB hedge-unwind replay/proof suites model the legacy failure and include blocked/reduced alternatives.

## Blockers

1. Risk gateway does not fail closed for stale source-state gates directly.

The current risk gateway accepts only `decision` and `now_ms_clock`. It can deny stale predictions only after the orchestrator already converted stale freshness into `abstain`. The separate degraded-state fail-closed module can detect stale/missing SMC/LIQ/OI/orderbook states, but the risk gateway assembler is not wired to consume that record or force a deny when it is fail-closed.

Concrete risk: a tradable `open_long`/`open_short` decision with missing or stale downstream market/exposure inputs still maps to `allow` inside `assemble_risk_decision_record`.

2. Hedge unwind residual exposure is covered by replay fixtures, not by executable gateway policy.

The legacy LAB failure requires checking net exposure after a hedge leg close and blocking/reducing unsafe residual exposure. The current risk gateway input model has no residual exposure, hedge-leg, net-position, squeeze, OI/liquidity, or reduce-only fields. The LAB replay tests prove typed paper/replay mirror sequences, including a `mirror_deny_default` scenario, but they do not exercise the risk gateway service deciding from residual-exposure inputs because those inputs do not exist in the service contract.

Concrete risk: the gateway cannot distinguish a safe open/close action from a hedge-unwind action that leaves adverse residual exposure.

3. Manual/external position quarantine is downstream/adjacent, not a risk gateway deny input.

Manual/external quarantine artifacts classify and block monitor-only actions, and the quarantine service emits `live_blocked=True`. However, quarantine state is not an input to `assemble_risk_decision_record`; a quarantined symbol/account can still have the risk gateway emit `risk_action=allow` if the upstream orchestrator decision is `open_long` or `open_short`.

Concrete risk: the record chain can represent a later quarantine, but the risk decision itself does not default-deny risk-add on quarantined positions.

4. `deny_default` is reserved in the service path that needs it for these failure modes.

The domain supports `deny_default`, and replay fixtures use mirror deny-default. The service suite explicitly asserts the risk gateway assembler never emits `deny_default` for orchestrator inputs. That is correct for the narrow 2G.B contract, but it is a blocker for this broader review topic because stale external gates, quarantine, and residual exposure need an executable deny reason that is not just upstream `hold`/`abstain`.

## Proposed Non-Live Autofix Tasks

1. Add a non-live policy input object for risk gateway gating.

Create a pure, frozen input type that carries optional fail-closed gate state: degraded source state, manual position quarantine flag, residual exposure/hedge-unwind assessment, and any required policy bundle ID. Keep it offline and side-effect free.

2. Extend the risk gateway assembler with explicit fail-closed checks.

Before allowing `open_long` or `open_short`, deny when:
- any required stale/missing data gate is fail-closed,
- manual/external/quarantined ownership is present for the symbol/account,
- hedge-unwind residual exposure is unsafe or unknown,
- required policy inputs are absent.

3. Add exact non-live tests for the missing blocks.

Add unit tests proving:
- stale source state plus tradable upstream decision emits deny,
- missing source state plus tradable upstream decision emits deny,
- quarantined manual/external symbol/account plus tradable upstream decision emits deny,
- LAB hedge-close residual short exposure emits deny or a typed safe alternative,
- all deny outputs preserve `live_blocked=True`, lineage, and operator-visible reason codes.

4. Connect LAB replay fixtures to the risk gateway service contract.

Replace pure paper-ledger mirror assertions for the key blocked LAB case with at least one test that invokes the risk gateway assembler on the residual-exposure policy input and asserts the returned `RiskDecisionRecord` denies the unsafe hedge unwind.

5. Keep all autofix work non-live.

Do not write Redis, touch exchanges, place/cancel orders, change leverage/margin, restart services, deploy, or enable live trading. The proposed changes are pure domain/service/test additions under `v2/backend/app` and `v2/backend/tests`.
