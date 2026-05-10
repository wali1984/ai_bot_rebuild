# Risk Gateway Default Deny MVP Parallel Review

## Scope

Read-only review of:

- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl`
- `claude_worklog/phase2_core_rebuild/risk_gateway`
- `claude_worklog/legacy_failure_cases`

No live services, Redis, orders, leverage/margin, deployment, or `/home/wali/Desktop/AI BOT` mutation were used. I did not run pytest because this was requested as read-only parallel review mode; findings are from source and artifact inspection.

## Verdict

CODEX_PARALLEL_REVIEW_BLOCKED

The narrow Phase 2G risk-gateway assembler matches its authored MVP spec, but the requested review topic is broader than that spec. Stale predictions are blocked through orchestrator abstain, and every risk record is hard `live_blocked=True`. However, hedge-unwind residual exposure and manual/external position quarantine are not enforced by the risk gateway path. They exist as value-object/proof/replay fixtures, not as inputs to `assemble_risk_decision_record`.

## Evidence Reviewed

- Risk domain constants and invariants: `v2/backend/app/domain/risk_gateway/record.py:8-218`
- Risk service assembler: `v2/backend/app/services/risk_gateway/service.py:25-79`
- Risk composition root: `v2/backend/app/composition/risk_gateway/runtime.py:15-27`
- Orchestrator stale-to-abstain behavior: `v2/backend/app/services/orchestrator_decision/service.py:76-82`
- Risk service stale-deny tests: `v2/backend/tests/unit/services/risk_gateway/test_assemble_deny_orchestrator_abstained_for_abstain_freshness_stale.py`
- LAB legacy failure case: `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md:25-56`
- LAB replay fixtures/tests: `v2/backend/tests/unit/replay_case_lab_hedge_unwind/fixtures.py:91-155`, `v2/backend/tests/unit/replay_case_lab_hedge_unwind/test_lab_hedge_unwind_replay_case.py:142-196`
- Manual/external quarantine proof logic: `v2/backend/app/proof/external_manual_position_quarantine.py:186-256`, `v2/backend/app/proof/external_manual_position_quarantine.py:433-451`
- Quarantine service: `v2/backend/app/services/external_manual_position_quarantine/service.py:12-49`

## Passing Checks

- Default live-deny safety exists at the record layer: `RiskDecisionRecord` rejects `live_blocked=False` in `record.py:214-218`, and the assembler always constructs records with `live_blocked=True` in `service.py:67-79`.
- Stale data blocks are covered through the upstream orchestrator: stale prediction freshness becomes `decision_action="abstain"` and `decision_reason_code="abstain_freshness_stale"` in `orchestrator_decision/service.py:76-82`; the risk assembler maps all abstain decisions to `risk_action="deny"` and `risk_reason_code="deny_orchestrator_abstained"` in `risk_gateway/service.py:58-60`.
- The domain reserves `deny_default` and constrains it to tradable input actions in `record.py:135-140`, which is useful for future default-deny gates.
- Manual/external quarantine proof artifacts classify manual, exchange-side protective, unknown, and duplicate-accounted positions as quarantined and monitor-only in `external_manual_position_quarantine.py:186-256`.
- LAB replay fixtures include a `block_hedge_close` alternative whose third step is `mirror_deny_default`, with test assertions in `test_lab_hedge_unwind_replay_case.py:142-196`.

## Blockers

1. Hedge-unwind residual exposure is not enforced by the risk gateway.

   The legacy failure case requires V2 to evaluate remaining net exposure before closing a protective hedge leg and to keep hedge, reduce/close short, block hedge close, or mark unsafe. The current risk assembler accepts only `decision` and `now_ms_clock` (`risk_gateway/service.py:25-29`). It has no current position, hedge state, residual exposure, intent type, or market-risk context. As a result, `open_long` and `open_short` are always allowed by the risk gateway (`service.py:49-54`) unless the upstream orchestrator already abstained/held. The LAB `block_hedge_close` coverage is fixture-level paper/replay projection, not an end-to-end risk-gateway decision derived from residual exposure.

2. Manual/external position quarantine is not wired into the risk gateway decision path.

   Quarantine logic can create `ManualPositionFlag` and `ExternalPositionQuarantineRecord`, and proof code blocks risk-add/hedge/DCA in generated artifact rows. But `assemble_risk_decision_record` does not receive a quarantine flag or position ownership classification, and there is no test showing a quarantined LAB symbol/account turns an otherwise tradable orchestrator decision into `deny_default`. This means quarantine is documented/proved separately but not enforced in the default-deny gateway MVP.

3. `deny_default` is reserved but intentionally unreachable from the current assembler.

   The Phase 2G.B spec explicitly says `deny_default` is not emitted by the assembler, and tests assert the assembler never emits it for orchestrator inputs. That is compatible with the narrow authored 2G.B contract, but it blocks the broader requested readiness check for residual exposure and quarantine default-deny gates because both need a tradable input action to be denied.

## Proposed Non-Live Autofix Tasks

1. Add a pure, non-I/O `RiskGatewaySafetyContext` value object under `v2/backend/app/domain/risk_gateway/` with fields for `manual_position_state`, `ownership_classification`, `hedge_state`, `residual_exposure_state`, and `live_blocked=True`.

2. Extend the risk assembler with an additive keyword-only function, for example `assemble_risk_decision_record_with_context(decision=..., safety_context=..., now_ms_clock=...)`, leaving the existing MVP function intact for backward compatibility.

3. Implement ordered default-deny gates before allow mapping:

   - quarantined/manual/external/protective/unknown/duplicate ownership plus tradable decision -> `deny`, `deny_default`
   - hedge close or risk-add that leaves unsafe residual exposure -> `deny`, `deny_default`
   - stale/held/abstain behavior remains as currently implemented

4. Add unit tests proving:

   - stale prediction still reaches `deny_orchestrator_abstained`
   - quarantined LAB manual/external position plus `open_short` or hedge/DCA intent emits `deny_default`
   - LAB hedge close with residual short exposure emits `deny_default`
   - clean non-quarantined `open_long/open_short` still allows
   - no Redis, HTTP, exchange, filesystem, service restart, or live-trading side effects are introduced

5. Convert the existing LAB fixture from paper-ledger-only projection into a risk-gateway input/output test where residual exposure context causes the risk gateway itself to emit the block.

## Review Marker

RISK_GATEWAY_DEFAULT_DENY_MVP_PARALLEL_REVIEW_BLOCKED
