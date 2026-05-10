# Paper Execution Ledger MVP Parallel Review

Verdict: BLOCKED.

## Scope Inspected

- `v2/backend/app/domain/paper_execution_ledger/`
- `v2/backend/app/services/paper_execution_ledger/`
- `v2/backend/app/composition/paper_execution_ledger/`
- `v2/backend/app/domain/paper_mode/`
- `v2/backend/app/services/paper_mode/`
- `v2/backend/app/composition/paper_mode/`
- Relevant lineage/API scaffolds under `v2/backend/app/api/`
- `v2/backend/tests/unit/domain/paper_execution_ledger/`
- `v2/backend/tests/unit/services/paper_execution_ledger/`
- `v2/backend/tests/unit/composition/paper_execution_ledger/`
- `v2/backend/tests/unit/domain/paper_mode/`
- `v2/backend/tests/unit/services/paper_mode/`
- `v2/backend/tests/unit/composition/paper_mode/`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/`

## Review Method

Read-only static review plus report emission only. I did not run tests, write Redis, delete Redis keys, touch live services, place or cancel orders, change leverage or margin, enable live trading, deploy, or inspect secrets. I wrote only this report and the requested one-line GO/NO-GO file.

## What Passes

- The implemented paper ledger surface is pure and narrow. The domain record is a frozen value object, the service is a deterministic assembler, and the composition root only binds an injected clock.
- Risk decision linkage is present at the mirror-record layer: `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, `input_risk_action`, and `input_risk_reason_code` are propagated from `RiskDecisionRecord`.
- Paper-mode surfaces reject live-like requested modes and construct flags with `live_blocked=True`.
- No real exchange action path was found in the inspected paper ledger or paper-mode implementation. The reviewed packages do not import exchange clients, HTTP clients, Redis adapters, order routers, leverage/margin controls, schedulers, or live-trading enablement.

## Blockers

1. The ledger does not model paper open/close/reduce/hedge/block lifecycle events.
   - Evidence: `v2/backend/app/domain/paper_execution_ledger/record.py:8` through `v2/backend/app/domain/paper_execution_ledger/record.py:30` define only `record_allow`, `record_deny`, and five mirror risk reason constants.
   - Evidence: `v2/backend/app/domain/paper_execution_ledger/record.py:90` through `v2/backend/app/domain/paper_execution_ledger/record.py:103` list the complete ledger entry fields; there is no paper event type, side effect category, position action, fill state, close/reduce/hedge target, or block event payload.
   - Evidence: `v2/backend/app/services/paper_execution_ledger/service.py:59` through `v2/backend/app/services/paper_execution_ledger/service.py:78` map risk reasons only to `record_allow` or `record_deny`.
   - Impact: the implementation can mirror risk allow/deny decisions, but cannot record the requested paper execution lifecycle.

2. PnL accounting is absent.
   - Evidence: `v2/backend/app/domain/paper_execution_ledger/record.py:90` through `v2/backend/app/domain/paper_execution_ledger/record.py:103` contain no quantity, entry price, exit price, mark price, fees, slippage, realized PnL, unrealized PnL, or position snapshot fields.
   - Evidence: `v2/backend/app/services/paper_execution_ledger/service.py:80` through `v2/backend/app/services/paper_execution_ledger/service.py:93` construct only lineage, timestamp, mirror action/reason, input risk fields, and `live_blocked=True`.
   - Evidence: the 2H specs explicitly scoped out PnL and fills: `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/02_PHASE_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_SPEC.md:3` through `:5`, `11_PHASE_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_SPEC.md:3` through `:5`, and `19_PHASE_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_SPEC.md:3` through `:5`.
   - Impact: paper closes, reduces, hedges, and blocked fills cannot be audited for PnL correctness from the current ledger.

3. `execution_intent_id` linkage is missing from the paper ledger.
   - Evidence: `v2/backend/app/domain/paper_execution_ledger/record.py:90` through `v2/backend/app/domain/paper_execution_ledger/record.py:103` include `risk_decision_id` but not `execution_intent_id`.
   - Evidence: `v2/backend/app/services/paper_execution_ledger/service.py:26` through `v2/backend/app/services/paper_execution_ledger/service.py:30` accept only `decision: RiskDecisionRecord` plus `now_ms_clock`; no execution intent input is available to propagate.
   - Evidence: canonical lineage includes `execution_intent_id` at `v2/backend/app/api/schemas/lineage.py:35` through `v2/backend/app/api/schemas/lineage.py:50`, and execution-intent payloads define `execution_intent_id`, `qty`, `order_type`, `mode`, and lineage at `v2/backend/app/api/schemas/execution_intent.py:15` through `v2/backend/app/api/schemas/execution_intent.py:26`.
   - Evidence: the paper route scaffold marks `execution_intent_id` as a required stage ID at `v2/backend/app/api/v1/paper.py:20` through `v2/backend/app/api/v1/paper.py:27`.
   - Impact: a paper ledger record cannot be traced to the execution intent that caused it.

4. Risk decision linkage is present but attached only to mirror decisions, not paper execution events.
   - Evidence: `v2/backend/app/services/paper_execution_ledger/service.py:80` through `v2/backend/app/services/paper_execution_ledger/service.py:91` propagate the risk decision and upstream lineage fields unchanged.
   - Evidence: `v2/backend/app/domain/paper_execution_ledger/record.py:156` through `v2/backend/app/domain/paper_execution_ledger/record.py:223` enforce consistency between mirror ledger action/reason and input risk action/reason.
   - Impact: this is a useful foundation, but the reviewed implementation still lacks the actual event records needed to explain open/close/reduce/hedge/block outcomes.

5. There is no real exchange action leakage in the inspected implementation, but the safety property is achieved partly because the ledger has no executor/accounting behavior.
   - Evidence: `v2/backend/app/composition/paper_execution_ledger/runtime.py:1` through `v2/backend/app/composition/paper_execution_ledger/runtime.py:27` only import typing, the paper ledger domain type, the risk decision type, the assembler, and local errors.
   - Evidence: `v2/backend/app/services/paper_execution_ledger/service.py:1` through `v2/backend/app/services/paper_execution_ledger/service.py:93` perform validation and value-object construction only.
   - Evidence: `v2/backend/app/services/execution_router.py:1` through `v2/backend/app/services/execution_router.py:4` remains a placeholder stating live order calls are blocked until a future milestone.
   - Impact: the no-live-action check passes for this surface; the blocking issue is missing non-live functionality.

## Proposed Non-Live Autofix Tasks

1. Add a pure paper execution event domain model with explicit event types `open`, `close`, `reduce`, `hedge`, and `block`. Include `paper_trade_id`, `execution_intent_id`, `risk_decision_id`, upstream lineage IDs, `symbol`, side/action, quantity, prices, fees, slippage, realized PnL, unrealized PnL or position snapshot, event timestamp, reason, and `live_blocked=True`.
2. Add a pure assembler/accounting service that consumes a validated execution intent, a validated risk decision, prior paper position state, market/fill inputs supplied as deterministic values, and an injected clock. It should emit non-persistent ledger events only.
3. Add deterministic PnL tests for long and short open/close, partial reduce, hedge open/close or hedge block, blocked intent with zero fill and zero PnL, fees/slippage, rounding, and symbol/lineage mismatch rejection.
4. Add linkage tests proving every emitted paper event carries both `risk_decision_id` and `execution_intent_id`, and rejects missing or mismatched execution-intent lineage.
5. Add lifecycle fixture tests for at least `open -> reduce -> close`, one hedge scenario, and one blocked risk decision. Keep the fixtures pure and local; do not read live exchange state.
6. Add forbidden-token tests over the new paper ledger/accounting packages for `create_order`, `cancel_order`, `place_order`, leverage/margin setters, `ccxt`, Binance order clients, Redis writes, HTTP clients, live-trading enablement, deployment, service restarts, and environment URL loaders.

## Conclusion

The current implementation is a safe, narrow risk-decision mirror ledger. It is blocked for the requested Paper Execution Ledger MVP review because it lacks paper execution lifecycle events, PnL accounting, and `execution_intent_id` linkage.
