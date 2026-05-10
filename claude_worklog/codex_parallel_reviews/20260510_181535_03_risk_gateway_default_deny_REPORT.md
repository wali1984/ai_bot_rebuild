# Codex Parallel Review - Risk Gateway Default Deny MVP

Review timestamp: 2026-05-10 18:15:35

Verdict: BLOCKED

## Scope Inspected

- `v2/backend/app/domain/risk_gateway/record.py`
- `v2/backend/app/services/risk_gateway/service.py`
- `v2/backend/app/composition/risk_gateway/runtime.py`
- `v2/backend/app/services/orchestrator_decision/service.py`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`
- `v2/backend/app/proof/external_manual_position_quarantine.py`
- `v2/backend/tests/unit/services/risk_gateway/`
- `v2/backend/tests/unit/domain/risk_gateway/`
- `v2/backend/tests/unit/composition/risk_gateway/`
- `v2/backend/tests/unit/proof/`
- `v2/backend/tests/unit/replay_case_lab_hedge_unwind/`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/`
- `claude_worklog/phase2_core_rebuild/risk_gateway/`
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`

## Findings

### Blocker 1 - Risk gateway assembler is allow-by-orchestrator, not default-deny

`v2/backend/app/services/risk_gateway/service.py` maps `open_long` and `open_short` directly to `allow` at lines 49-54. There is no independent gateway policy input, no default-deny fallback for tradable intents, and no evaluation of freshness, exposure, quarantine, account state, or residual hedge context before allowing.

The domain supports `deny_default` in `v2/backend/app/domain/risk_gateway/record.py` lines 15 and 23-30, but the assembler never emits it for ordinary orchestrator inputs. This is locked in by `v2/backend/tests/unit/services/risk_gateway/test_assemble_never_emits_deny_default_for_orchestrator_inputs.py` lines 5-42.

Impact: the MVP cannot be called a Risk Gateway Default Deny MVP. It is currently a typed mirror of orchestrator decisions with `live_blocked=True`.

### Blocker 2 - Stale data blocks are upstream-dependent, not gateway-enforced

Stale and missing freshness are converted to orchestrator `abstain` in `v2/backend/app/services/orchestrator_decision/service.py` lines 77-82. The risk gateway only denies because it sees `decision_action == abstain` in `v2/backend/app/services/risk_gateway/service.py` lines 58-60.

Impact: a malformed, replayed, or future tradable `OrchestratorDecisionRecord` carrying stale lineage is not independently blocked by the gateway. The stale proof exists, but the default-deny gateway boundary does not enforce it.

### Blocker 3 - Hedge unwind residual exposure block is fixture/proof coverage, not gateway logic

The legacy LAB failure case requires blocking or reducing residual short exposure after closing a protective long hedge. The committed proof fixture includes `short_squeeze_and_hedge_unwind_residual_exposure` in `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py` lines 125-136, and the proof test asserts that reason at `v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py` lines 64-71.

The risk gateway service has no position/exposure input and cannot evaluate residual exposure. The replay case validates typed mirror ledger sequences, including a `mirror_deny_default` outcome, but it does not prove the gateway computes that block from hedge unwind state.

Impact: the LAB-like failure is represented, but not prevented by the risk gateway decision path under review.

### Blocker 4 - Manual/external quarantine is not integrated into gateway deny decisions

`v2/backend/app/proof/external_manual_position_quarantine.py` classifies manual, exchange-side protective, unknown, and duplicate positions as quarantined at lines 186-256. Its tests assert LAB quarantine and `risk_add` blocks at `v2/backend/tests/unit/proof/test_external_manual_position_quarantine.py` lines 94-100.

The risk gateway assembler does not accept quarantine state, account id, ownership classification, exchange order attribution, or blocked action context.

Impact: manual/external position quarantine evidence exists, but a gateway `open_long` or `open_short` can still be allowed solely because the orchestrator action is tradable.

## Positive Coverage Observed

- Risk decision records are frozen, validate allowed action/reason constants, and require `live_blocked=True`.
- Hold and abstain orchestrator decisions become gateway deny records.
- Stale/missing freshness is covered through orchestrator abstain propagation.
- LAB hedge unwind and stale-data scenarios are represented in deterministic proof fixtures.
- Manual/external position quarantine proof marks manual/external/unknown/duplicate positions as monitor-only and blocks risk-add actions.
- Composition root is side-effect-light and defers assembler invocation until evaluator call time.

## Proposed Non-Live Autofix Tasks

1. Add a gateway policy input dataclass for non-live evaluation only, carrying at minimum freshness flag, worker health, current net exposure, hedge leg close intent, residual exposure after proposed action, ownership/quarantine state, account id, symbol, and action type.
2. Change `assemble_risk_decision_record` so tradable orchestrator decisions default to `deny_default` unless explicit gateway policy checks pass.
3. Add stale/missing freshness deny checks inside the gateway even when the incoming orchestrator action is tradable.
4. Add LAB hedge-unwind residual exposure checks that deny protective hedge closes or risk-add actions leaving unprotected residual short/long exposure beyond configured fixture thresholds.
5. Integrate external/manual quarantine state into gateway policy evaluation so quarantined symbol/account pairs allow monitor-only and deny risk-add/open/increase actions.
6. Add unit tests proving stale tradable decisions, LAB residual hedge exposure, manual/external quarantines, missing policy context, and unknown policy fields all produce `deny_default`.
7. Keep all new tests deterministic and offline; do not connect to Redis, exchanges, live services, or order APIs.

## Safety Notes

This review was read-only except for writing this report and the requested GO/NO-GO marker. No Redis writes/deletes, service restarts, order placement/cancellation, leverage/margin changes, deployment, or live trading enablement were performed.

