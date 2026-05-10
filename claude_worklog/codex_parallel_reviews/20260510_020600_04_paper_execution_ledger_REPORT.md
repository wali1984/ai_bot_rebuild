# Paper Execution Ledger MVP Parallel Review

Verdict: BLOCKED.

## Scope Inspected

- `v2/backend/app/domain/paper_execution_ledger/`
- `v2/backend/app/services/paper_execution_ledger/`
- `v2/backend/app/composition/paper_execution_ledger/`
- `v2/backend/app/api/schemas/paper_trade.py`
- `v2/backend/app/api/schemas/execution_intent.py`
- `v2/backend/app/api/v1/paper.py`
- `v2/backend/app/api/v1/intents.py`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`
- `v2/backend/tests/unit/domain/paper_execution_ledger/`
- `v2/backend/tests/unit/services/paper_execution_ledger/`
- `v2/backend/tests/unit/composition/paper_execution_ledger/`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/`

## Verification

Read-only review only. I did not run tests, write Redis, touch live services, place or cancel orders, change leverage or margin, enable live trading, or deploy. I wrote only this report and the requested one-line GO/NO-GO file.

## What Passes

- The current paper ledger domain is pure and frozen.
- `PaperExecutionLedgerEntry` carries `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, timestamp, mirror action/reason, input risk action/reason, and `live_blocked`.
- The service maps risk decisions into paper ledger mirror records and hard-codes output `live_blocked=True`.
- The composition root only builds a callable around the pure assembler and an injected clock.
- No real exchange action path was found in the inspected paper ledger domain/service/composition package. The package does not import exchange clients, HTTP clients, Redis adapters, order routers, leverage, or margin controls.

## Blockers

1. The ledger does not model paper open/close/reduce/hedge/block events.
   - Evidence: `v2/backend/app/domain/paper_execution_ledger/record.py:8` through `v2/backend/app/domain/paper_execution_ledger/record.py:30` define only `record_allow`, `record_deny`, and five mirror risk reasons.
   - Evidence: `v2/backend/app/domain/paper_execution_ledger/record.py:130` through `v2/backend/app/domain/paper_execution_ledger/record.py:139` validate `ledger_action` and `ledger_reason_code` only against those narrow sets.
   - Evidence: `v2/backend/app/services/paper_execution_ledger/service.py:59` through `v2/backend/app/services/paper_execution_ledger/service.py:78` map risk reasons only to `record_allow` or `record_deny`.
   - Impact: the implementation can mirror risk allow/deny, but it cannot record the requested paper execution lifecycle events.

2. PnL accounting is absent from the ledger.
   - Evidence: `v2/backend/app/domain/paper_execution_ledger/record.py:90` through `v2/backend/app/domain/paper_execution_ledger/record.py:103` list the full ledger entry fields; there is no quantity, price, fee, slippage, realized PnL, unrealized PnL, or position state.
   - Evidence: `v2/backend/app/services/paper_execution_ledger/service.py:80` through `v2/backend/app/services/paper_execution_ledger/service.py:93` constructs only lineage, timestamp, mirror action/reason, risk input fields, and `live_blocked=True`.
   - Evidence: proof fixtures contain paper event types and PnL expectations, for example `close`, `block`, and `reduce` with `v2_paper_pnl` in `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:80` through `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:151`, but those are proof artifacts rather than ledger accounting behavior.
   - Impact: paper close/reduce/hedge accounting cannot be audited from the current ledger model.

3. `execution_intent_id` linkage is missing from the paper ledger.
   - Evidence: `v2/backend/app/domain/paper_execution_ledger/record.py:90` through `v2/backend/app/domain/paper_execution_ledger/record.py:103` include `risk_decision_id` but not `execution_intent_id`.
   - Evidence: `v2/backend/app/api/schemas/execution_intent.py:20` defines `execution_intent_id`, and `v2/backend/app/api/schemas/lineage.py:35` through `v2/backend/app/api/schemas/lineage.py:50` make it part of canonical lineage, but the paper ledger entry does not carry it.
   - Evidence: `v2/backend/app/api/v1/paper.py:20` through `v2/backend/app/api/v1/paper.py:27` and `v2/backend/app/api/v1/intents.py:22` through `v2/backend/app/api/v1/intents.py:29` list `execution_intent_id` as a required lineage-stage ID for those route skeletons.
   - Impact: a paper ledger record cannot be traced to the execution intent that caused it.

4. Risk decision linkage is present only at mirror-decision level.
   - Evidence: `v2/backend/app/services/paper_execution_ledger/service.py:80` through `v2/backend/app/services/paper_execution_ledger/service.py:91` propagate `risk_decision_id`, upstream lineage IDs, `risk_action`, and `risk_reason_code`.
   - Evidence: `v2/backend/app/domain/paper_execution_ledger/record.py:156` through `v2/backend/app/domain/paper_execution_ledger/record.py:223` enforce mirror action/reason consistency with input risk action/reason.
   - Impact: this is a useful foundation, but the linkage is not attached to actual paper open/close/reduce/hedge/block events.

5. No real exchange actions were found in the inspected ledger implementation.
   - Evidence: `v2/backend/app/composition/paper_execution_ledger/runtime.py:1` through `v2/backend/app/composition/paper_execution_ledger/runtime.py:27` import only typing, the paper ledger domain type, the risk decision type, the assembler, and local errors.
   - Evidence: `v2/backend/app/services/paper_execution_ledger/service.py:1` through `v2/backend/app/services/paper_execution_ledger/service.py:93` perform validation and value-object construction only.
   - Impact: safety check passes for this surface; the blocking issue is missing non-live functionality, not live exchange leakage.

## Proposed Non-Live Autofix Tasks

1. Add a pure paper execution event domain model with explicit event types `open`, `close`, `reduce`, `hedge`, and `block`. Include `paper_trade_id`, `execution_intent_id`, `risk_decision_id`, upstream lineage IDs, `symbol`, side/action, quantity, price, fees, slippage, realized PnL, unrealized PnL or position snapshot, event timestamp, reason, and `live_blocked=True`.
2. Add a pure paper accounting service that consumes validated execution intent plus risk decision plus an injected clock and emits non-persistent ledger events. It must not import Redis, HTTP clients, exchange clients, order routers, environment URL loaders, schedulers, or live-mode controls.
3. Add deterministic PnL tests for long and short open/close, partial reduce, hedge open/close or hedge block, blocked intent with zero fill and zero PnL, fees/slippage, rounding, and symbol/lineage mismatch rejection.
4. Add linkage tests proving every emitted paper event carries both `risk_decision_id` and `execution_intent_id`, and rejects missing or mismatched execution-intent lineage.
5. Add lifecycle fixture tests for at least `open -> reduce -> close`, one hedge scenario, and one blocked risk decision. Tie these to the existing historical proof expectations without using live exchange state.
6. Add forbidden-token tests over the new paper execution ledger packages for `create_order`, `cancel_order`, leverage/margin setters, `ccxt`, Binance order clients, Redis writes, HTTP clients, live trading enablement, deployment, and service restarts.

## Conclusion

The current implementation is a safe, narrow risk-decision mirror ledger. It is blocked for the requested Paper Execution Ledger MVP because it lacks paper execution lifecycle events, PnL accounting, and `execution_intent_id` linkage.
