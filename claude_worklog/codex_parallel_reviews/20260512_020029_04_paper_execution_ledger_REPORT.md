# Codex Parallel Review: Paper Execution Ledger MVP

Verdict: BLOCKED.

## Scope Reviewed

- `v2/backend/app/domain/paper_execution_ledger/`
- `v2/backend/app/services/paper_execution_ledger/`
- `v2/backend/app/composition/paper_execution_ledger/`
- matching unit tests under `v2/backend/tests/unit/{domain,services,composition}/paper_execution_ledger/`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/`
- related execution-intent placeholders and proof fixtures where discoverable by text search

I did not modify `/home/wali/Desktop/AI BOT`, did not write Redis, did not delete Redis keys, did not restart services, did not place or cancel orders, did not change leverage or margin, did not enable live trading, and did not deploy.

## Findings

### BLOCKER 1 - Ledger does not model paper open/close/reduce/hedge/block lifecycle events

The implemented `PaperExecutionLedgerEntry` allows only two ledger actions: `record_allow` and `record_deny` (`v2/backend/app/domain/paper_execution_ledger/record.py:8-30`). The service maps risk reasons to those two mirror actions only (`v2/backend/app/services/paper_execution_ledger/service.py:59-78`).

This does not satisfy the requested MVP checks for paper open, close, reduce, hedge, and block ledger events. There is no event type, side/effect, position delta, quantity, entry/exit price, fill basis, hedge relationship, reduce semantics, or block event taxonomy in the production ledger domain/service/composition surface.

The phase specs confirm this narrow behavior was deliberate for Phase 2H: the domain, service, and composition specs explicitly exclude PnL, quantity, price, fees, slippage, position sizing, persistence, and execution behavior. That makes the current code a risk-decision mirror record, not a Paper Execution Ledger MVP as requested here.

### BLOCKER 2 - PnL accounting is absent from the ledger implementation

`PaperExecutionLedgerEntry` has no realized PnL, unrealized PnL, fees, slippage, average price, mark price, notional, quantity, or currency fields (`v2/backend/app/domain/paper_execution_ledger/record.py:90-103`). The assembler simply records a timestamp and mirrors risk metadata (`v2/backend/app/services/paper_execution_ledger/service.py:80-93`).

Proof modules contain fixture-level paper PnL strings, but those are not part of the paper execution ledger domain/service/composition implementation under review. They do not provide ledger accounting semantics or reusable production invariants.

### BLOCKER 3 - `execution_intent_id` linkage is missing

The ledger entry carries `paper_trade_id`, `risk_decision_id`, `decision_id`, `prediction_id`, and `feature_snapshot_id`, but no `execution_intent_id` (`v2/backend/app/domain/paper_execution_ledger/record.py:90-103`). The assembler derives `paper_trade_id` from `risk_decision_id` and does not accept or propagate an execution intent (`v2/backend/app/services/paper_execution_ledger/service.py:26-93`).

`v2/backend/app/domain/execution/intent.py` and `v2/backend/app/domain/execution/paper.py` are placeholders only. The API schema has an `execution_intent_id`, but it is not wired into the paper ledger path.

### PASS - Risk decision linkage exists for the narrow mirror-ledger scope

The current ledger requires a `RiskDecisionRecord` input in the service layer and composition recorder (`v2/backend/app/services/paper_execution_ledger/service.py:26-35`, `v2/backend/app/composition/paper_execution_ledger/runtime.py:24-25`). It propagates `risk_decision_id`, `risk_action`, and `risk_reason_code` into the ledger entry (`v2/backend/app/services/paper_execution_ledger/service.py:80-93`). Domain invariants enforce the action/reason mirror mapping (`v2/backend/app/domain/paper_execution_ledger/record.py:156-220`).

### PASS - No real exchange actions observed in the reviewed ledger code

The reviewed ledger packages are pure value-object/assembler/composition surfaces. They do not import exchange clients, Redis adapters, HTTP clients, FastAPI routers, schedulers, or live-service mutation paths. The composition recorder only forwards a `RiskDecisionRecord` and injected clock to the assembler (`v2/backend/app/composition/paper_execution_ledger/runtime.py:15-27`). The service constructs an in-memory `PaperExecutionLedgerEntry` with `live_blocked=True` (`v2/backend/app/services/paper_execution_ledger/service.py:80-93`).

## Proposed Non-Live Autofix Tasks

1. Add a new pure paper ledger domain record for lifecycle events, with an explicit event/action enum covering `paper_open`, `paper_close`, `paper_reduce`, `paper_hedge`, and `paper_block`. Keep it frozen, slotted, import-clean, and `live_blocked=True`.

2. Add `execution_intent_id` as a required ledger linkage field and propagate it through service/composition tests. Do not call exchange APIs; consume only validated in-memory intent/risk records.

3. Add deterministic PnL accounting fields and invariants for paper-only events: quantity, signed position delta, entry/exit/mark price inputs, fees/slippage if in scope, realized PnL for close/reduce, and zero/none accounting for block events. Use integer/decimal-safe accounting rather than floats if money precision matters.

4. Add a pure assembler that maps validated risk decisions plus execution intents into lifecycle ledger events. It should fail closed for missing intent linkage, risk mismatch, symbol mismatch, non-paper mode, or `live_blocked != True`.

5. Add non-live unit tests for each event type: open, close, reduce, hedge, block; PnL edge cases; risk decision linkage; `execution_intent_id` linkage; and forbidden real-exchange actions/imports.

6. Keep persistence, Redis writes, live exchange adapters, leverage/margin changes, and service restarts out of the autofix. The autofix should be domain/service/composition-only until a later explicit non-live storage milestone.

## Validation

No pytest run was performed during this read-only review to avoid incidental cache writes. Review evidence came from source and artifact inspection only.
