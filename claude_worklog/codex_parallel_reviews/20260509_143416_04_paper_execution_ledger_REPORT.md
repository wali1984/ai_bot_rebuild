# Paper Execution Ledger MVP Read-Only Review

Status: BLOCKED

Scope inspected:
- `v2/backend/app/domain/paper_execution_ledger/record.py`
- `v2/backend/app/services/paper_execution_ledger/service.py`
- `v2/backend/app/composition/paper_execution_ledger/runtime.py`
- relevant `v2/backend/tests/unit/{domain,services,composition}/paper_execution_ledger`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl`

I did not modify files, write Redis, delete Redis keys, restart services, place/cancel orders, change leverage/margin, enable live trading, deploy, or inspect/expose secrets.

## Findings

BLOCKER 1: Ledger events are not paper execution events.

The current domain only permits two ledger actions:
- `record_allow`
- `record_deny`

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py:8-20`
- `v2/backend/app/services/paper_execution_ledger/service.py:59-73`

The requested MVP check requires paper open/close/reduce/hedge/block ledger events. There is no domain or service support for `open`, `close`, `reduce`, `hedge`, or `block` as ledger event types. `block` is represented indirectly as `record_deny`, and allow paths are represented only as `record_allow`, so the ledger cannot distinguish a paper open from a close, reduce, or hedge.

BLOCKER 2: PnL accounting is absent from the ledger.

`PaperExecutionLedgerEntry` has identifiers, symbol, timestamp, action/reason, risk inputs, and `live_blocked`, but no price, quantity, side, position delta, fees, slippage, realized PnL, unrealized PnL, cumulative PnL, or account/equity field.

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py:90-103`
- `v2/backend/app/services/paper_execution_ledger/service.py:80-93`

The historical proof module contains fixture PnL strings (`legacy_realized_pnl`, `v2_paper_pnl`), but those are proof fixture values, not ledger accounting:
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:42-43`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:80-151`

Prior 2H docs explicitly scoped PnL out, so this is not a regression against that narrower milestone, but it blocks the broader MVP requested here.

BLOCKER 3: `execution_intent_id` is not linked into paper ledger entries.

The ledger entry carries:
- `paper_trade_id`
- `risk_decision_id`
- `decision_id`
- `prediction_id`
- `feature_snapshot_id`

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py:92-96`
- `v2/backend/app/services/paper_execution_ledger/service.py:81-85`

There is no `execution_intent_id` field in the ledger record or assembler input/output. The proof fixture can derive an `execution_intent_id`, but that value is not part of the paper ledger path:
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:67-73`

PASS: Risk decision linkage exists.

The assembler requires a `RiskDecisionRecord`, derives `paper_trade_id` from `risk_decision_id`, and propagates `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, `risk_action`, and `risk_reason_code`.

Evidence:
- `v2/backend/app/services/paper_execution_ledger/service.py:26-30`
- `v2/backend/app/services/paper_execution_ledger/service.py:80-92`

PASS: No real exchange actions observed in the inspected paper ledger implementation.

The inspected paper ledger domain/service/composition code is pure derivation. It does not import exchange adapters, Redis, HTTP clients, FastAPI, or order-placement code. The composition root only binds a clock and forwards a `RiskDecisionRecord`.

Evidence:
- `v2/backend/app/composition/paper_execution_ledger/runtime.py:1-18`
- `v2/backend/app/services/paper_execution_ledger/service.py:1-23`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/21_PHASE_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_SAFETY_BOUNDARIES.md` explicitly forbids exchange actions and PnL/execution expansion for 2H.C.

## Verification

Attempted targeted unit tests with:
`PYTHONDONTWRITEBYTECODE=1 python -B -m pytest -q v2/backend/tests/unit/domain/paper_execution_ledger v2/backend/tests/unit/services/paper_execution_ledger v2/backend/tests/unit/composition/paper_execution_ledger -p no:cacheprovider`

Result: blocked by local environment, `/usr/bin/python: No module named pytest`.

## Proposed Non-Live Autofix Tasks

1. Extend the paper ledger domain with a non-live `PaperExecutionLedgerEvent` or versioned replacement that includes `event_type` values for `open`, `close`, `reduce`, `hedge`, and `block`.

2. Add `execution_intent_id` as a required lineage field and validate it with the same identifier discipline as the existing lineage IDs.

3. Add deterministic PnL accounting fields using `Decimal` or integer minor units: entry price, exit/mark price where applicable, quantity, realized PnL, fees, slippage, and cumulative paper PnL. Keep all inputs caller-supplied or fixture-supplied; do not call exchange APIs.

4. Update the assembler to accept a non-live execution intent/fill/accounting input object plus the existing `RiskDecisionRecord`, then produce event-specific paper ledger entries without Redis, adapters, order placement, or live service calls.

5. Add unit tests for all required event types: open, close, reduce, hedge, block. Include PnL arithmetic tests, risk-decision lineage propagation tests, `execution_intent_id` propagation tests, and forbidden-import/no-exchange-action tests.

6. Keep live safety invariant: every ledger event must require `live_blocked is True`, and no public API should accept a caller-provided live-enabled mode.
