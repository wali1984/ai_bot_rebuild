# Codex Parallel Review — Paper Execution Ledger MVP

Status: BLOCKED for the requested Paper Execution Ledger MVP scope.

Review mode: read-only. No Redis writes, no Redis key deletion, no live service restart, no exchange/order/leverage/margin action, no live-trading enablement, and no deploy action were performed.

## Scope Inspected

- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl`

## Findings

### BLOCKER 1 — Ledger does not model paper open/close/reduce/hedge lifecycle events

The implemented ledger taxonomy only supports two ledger actions:

- `record_allow`
- `record_deny`

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py:8-30` defines only `record_allow`, `record_deny`, and five mirror risk reasons.
- `v2/backend/app/domain/paper_execution_ledger/record.py:90-103` defines `PaperExecutionLedgerEntry` without event type, side, position delta, quantity, entry/exit/fill price, position id, or lifecycle fields.
- `v2/backend/app/services/paper_execution_ledger/service.py:59-78` maps risk reasons only to mirror allow/deny ledger actions.
- `v2/backend/app/services/paper_execution_ledger/service.py:80-92` constructs only the mirror ledger entry.

Impact:
- Open-long/open-short intent can be mirrored from risk, but there is no actual paper open event with quantity/fill/position state.
- There are no close, reduce, hedge, unwind, or position-adjustment ledger events.
- Block events are represented only as generic `record_deny`, not as a paper execution block event tied to an execution attempt or state transition.

### BLOCKER 2 — No PnL accounting exists

The reviewed ledger code contains no realized/unrealized PnL, cost basis, fees, slippage, mark price, entry/exit price, fill quantity, or position accounting.

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py:90-103` contains no PnL/accounting fields.
- `v2/backend/app/services/paper_execution_ledger/service.py:26-92` derives only ids, symbol, timestamp, mirror action/reason, input risk action/reason, and `live_blocked=True`.
- `v2/backend/app/domain/execution/paper.py:1` is still a placeholder.
- `v2/backend/app/services/paper_loop.py:1` is still a placeholder.
- Phase 2H/2J planning artifacts explicitly scoped out PnL, quantity, price, fees, and slippage for these subphases.

Impact:
- The MVP cannot answer realized PnL on close/reduce.
- It cannot track open position exposure, cost basis, hedge offsets, or paper equity changes.
- It cannot reconcile paper fills against risk decisions or later replay/backtest summaries as an execution ledger.

### BLOCKER 3 — `execution_intent_id` linkage is missing from the ledger record

The paper route metadata expects `execution_intent_id` as part of the paper-trade lineage, but the ledger entry cannot carry it.

Evidence:
- `v2/backend/app/api/v1/paper.py:20-27` lists `execution_intent_id` as a required stage id for paper trades.
- `v2/backend/app/domain/paper_execution_ledger/record.py:90-103` omits `execution_intent_id`.
- `v2/backend/app/services/paper_execution_ledger/service.py:80-92` cannot propagate `execution_intent_id` because it only accepts `RiskDecisionRecord`.
- `v2/backend/app/domain/execution/intent.py:1` is still a placeholder.

Impact:
- Paper ledger rows cannot be joined to execution intents.
- The requested execution-intent lineage cannot be proven for open/close/reduce/hedge/block events.
- Any future paper-trade API response would need to source `execution_intent_id` elsewhere, creating a ledger consistency gap.

### BLOCKER 4 — Risk decision linkage is only partial

The current implementation does preserve risk lineage for the narrow mirror record.

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py:92-102` includes `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, `input_risk_action`, and `input_risk_reason_code`.
- `v2/backend/app/services/paper_execution_ledger/service.py:80-91` propagates those fields from `RiskDecisionRecord`.

However, because there is no execution lifecycle model, this linkage only proves "risk decision was mirrored into a ledger entry." It does not prove that a paper open/close/reduce/hedge/block execution event was linked to the risk decision that authorized or blocked it.

### PASS — No real exchange actions observed in the reviewed ledger/paper-mode implementation

No exchange adapter, order placement, leverage/margin mutation, live-mode enablement, Redis write, scheduler, or live service restart path was observed in the reviewed paper execution ledger or paper mode source.

Evidence:
- `v2/backend/app/services/paper_execution_ledger/service.py:26-92` is a pure assembler and constructs `live_blocked=True`.
- `v2/backend/app/domain/paper_execution_ledger/record.py:151-154` rejects any ledger entry whose `live_blocked` is not `True`.
- `v2/backend/app/composition/paper_execution_ledger/runtime.py:15-27` only binds a clock and calls the pure assembler.
- `v2/backend/app/domain/execution/paper.py:1`, `v2/backend/app/domain/execution/intent.py:1`, and `v2/backend/app/services/paper_loop.py:1` remain placeholders rather than live execution paths.

## Test Coverage Observed

The available tests cover the implemented narrow mirror taxonomy:
- allow long/short risk reasons mirror to `record_allow`
- deny reasons mirror to `record_deny`
- lineage fields from `RiskDecisionRecord` are propagated
- `live_blocked=True` is enforced
- import/forbidden-token safety checks exist

The tests do not cover:
- open position creation
- close events
- reduce events
- hedge events
- explicit block execution events
- realized/unrealized PnL
- fees/slippage/cost basis
- `execution_intent_id` linkage
- paper position state transitions

## Proposed Non-Live Autofix Tasks

1. Define a non-live paper execution event domain object with explicit event types: `open`, `close`, `reduce`, `hedge`, and `block`.
2. Add `execution_intent_id` as a required ledger lineage field and propagate it from a typed execution-intent input.
3. Add paper accounting fields required for deterministic PnL: side, quantity, fill price, fee, slippage, position id, realized PnL, unrealized PnL basis/mark where applicable, and resulting paper position size.
4. Build a pure paper ledger assembler that accepts validated risk decision + execution intent + paper fill/accounting input and returns immutable ledger events without touching Redis, exchange adapters, files, HTTP, or live services.
5. Add unit tests for open/close/reduce/hedge/block events, risk-decision linkage, execution-intent linkage, PnL arithmetic, and `live_blocked=True`.
6. Add forbidden-import and forbidden-token tests proving the ledger assembler cannot call exchange adapters, place/cancel orders, change leverage/margin, write Redis, or enable live trading.
7. Keep persistence and live integration out of the autofix unless separately authorized; return value objects only.

## Decision

CODEX_PARALLEL_REVIEW_BLOCKED
