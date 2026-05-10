# Codex Parallel Review - Paper Execution Ledger MVP

Verdict: BLOCKED

Scope inspected:
- `v2/backend/app/domain/paper_execution_ledger/`
- `v2/backend/app/services/paper_execution_ledger/`
- `v2/backend/app/composition/paper_execution_ledger/`
- relevant `v2/backend/tests/unit/...paper_execution_ledger...`
- `v2/backend/app/domain/execution/`
- `v2/backend/app/services/paper_loop.py`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/`

Validation run:
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest v2/backend/tests/unit/domain/paper_execution_ledger v2/backend/tests/unit/services/paper_execution_ledger v2/backend/tests/unit/composition/paper_execution_ledger -q -p no:cacheprovider`
- Result: `83 passed in 0.31s`

## Findings

### 1. Blocker: paper lifecycle ledger events are absent

The current domain exposes only two ledger actions:
- `record_allow`
- `record_deny`

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py:8-15` defines only `PAPER_LEDGER_ACTION_RECORD_ALLOW`, `PAPER_LEDGER_ACTION_RECORD_DENY`, and mirror allow/deny reason constants.
- `v2/backend/app/domain/paper_execution_ledger/record.py:17-31` allows only those two actions and five mirror reasons.
- `v2/backend/app/services/paper_execution_ledger/service.py:59-73` maps risk reasons only to `record_allow` or `record_deny`.

Required review topic coverage is missing for paper open, close, reduce, hedge, and block ledger events. The only "block-like" behavior is a deny mirror row; there is no explicit paper block execution event with execution-state fields.

### 2. Blocker: PnL accounting is absent and currently disallowed by tests/specs

No ledger fields exist for position quantity, entry/exit price, fees, funding, realized PnL, unrealized PnL, or cumulative paper account state.

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py:91-103` defines the full `PaperExecutionLedgerEntry` field set, and it contains no PnL, price, quantity, fee, funding, or position fields.
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/02_PHASE_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_SPEC.md:5` explicitly says the domain does not compute PnL, quantity, price, fees, or slippage.
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/11_PHASE_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_SPEC.md:5` repeats that the service does not compute PnL, quantity, price, fees, or slippage.
- `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:33-49` defines PnL and market fields as disallowed.
- `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:157-162` asserts those fields are absent.

This is incompatible with the requested Paper Execution Ledger MVP check for PnL accounting.

### 3. Blocker: execution_intent_id linkage is absent

The ledger links to risk decision lineage but does not carry `execution_intent_id`.

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py:91-103` has no `execution_intent_id` field.
- `v2/backend/app/services/paper_execution_ledger/service.py:80-93` constructs a ledger entry from `RiskDecisionRecord` fields only and never accepts or derives an execution intent id.
- `v2/backend/app/domain/execution/intent.py` is still a placeholder: `"""Execution intent domain placeholder. Pure module."""`
- `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:32` marks `execution_intent_id` as a disallowed lineage field for that harness.
- `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:147-154` asserts replay records do not emit `execution_intent_id`.

### 4. Pass: risk decision linkage exists

The current mirror ledger does preserve risk-decision lineage.

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py:92-103` includes `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, `input_risk_action`, and `input_risk_reason_code`.
- `v2/backend/app/services/paper_execution_ledger/service.py:80-92` copies those fields from `RiskDecisionRecord`.
- `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:75-88` asserts lineage fields match the input risk decision.
- `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:125-134` asserts risk action and reason propagate.

### 5. Pass: no real exchange actions observed in the paper ledger implementation

No order placement, cancel, leverage, margin, live exchange mutation, Redis write, or live service restart behavior was found in the paper ledger domain/service/composition source. The implementation is pure construction of frozen value objects.

Evidence:
- `v2/backend/app/services/paper_execution_ledger/service.py:26-93` validates a `RiskDecisionRecord`, calls an injected clock, maps to a ledger row, and returns `PaperExecutionLedgerEntry`.
- `v2/backend/app/composition/paper_execution_ledger/runtime.py` only builds a recorder closure that calls the pure assembler.
- Source scan over `v2/backend/app/domain/paper_execution_ledger`, `v2/backend/app/services/paper_execution_ledger`, `v2/backend/app/composition/paper_execution_ledger`, `v2/backend/app/services/paper_loop.py`, and `v2/backend/app/domain/execution` found no real exchange mutation APIs or Redis write/delete calls. The only scan hits were function names containing `recorder`, not order placement.

## Concrete blockers

1. The ledger taxonomy must be expanded beyond `record_allow` / `record_deny` to represent paper execution events: open, close, reduce, hedge, and block.
2. The ledger record must carry enough non-live paper execution state to account for PnL: side, quantity, entry/exit/mark prices as applicable, fees/funding/slippage model fields if in scope, realized PnL, unrealized PnL, and cumulative position/account state.
3. The execution intent domain is still a placeholder and the ledger has no `execution_intent_id` field or invariant.
4. Current historical PnL/replay tests explicitly disallow `execution_intent_id` and PnL/market fields, so the test contract must be updated before implementation can satisfy the MVP checklist.

## Proposed non-live autofix tasks

1. Add a pure execution intent value object under `v2/backend/app/domain/execution/intent.py` with `execution_intent_id`, `risk_decision_id`, action, side, symbol, requested quantity/notional, and `live_blocked=True`. Add unit tests proving no exchange/Redis imports.
2. Replace or extend `PaperExecutionLedgerEntry` with explicit event taxonomy constants for `paper_open`, `paper_close`, `paper_reduce`, `paper_hedge`, and `paper_block`, with cross-field invariants tying block events to deny/default risk decisions.
3. Add a pure paper position/PnL calculator service that consumes prior in-memory position state plus a paper event input and returns a new ledger row plus new state. Keep it dependency-injected and side-effect free; no Redis, exchange clients, files, HTTP, or live services.
4. Add tests for long and short open/close PnL, partial reduce average-cost behavior, hedge event accounting, block event accounting with zero exchange action, and risk decision plus execution intent lineage.
5. Update historical PnL/replay harness tests to require, not reject, `execution_intent_id` and paper PnL fields once the non-live model is introduced.
6. Add source scans and import-clean tests proving the new implementation still has no `create_order`, `cancel_order`, leverage/margin mutation, Redis write/delete, live trading enablement, deployment hook, or live service restart path.

CODEX_PARALLEL_REVIEW_BLOCKED
