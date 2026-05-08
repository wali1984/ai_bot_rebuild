BEGIN_FILE: claude_worklog/codex_parallel_reviews/20260508_230322_04_paper_execution_ledger_REPORT.md
# Codex Parallel Review: Paper Execution Ledger MVP

Review mode: read-only parallel review, with only this report and the requested GO/NO-GO artifact written.

Verdict: BLOCKED

The current implementation is a safe, pure risk-decision mirror ledger, but it is not yet a Paper Execution Ledger MVP for the requested topic. It records `record_allow` / `record_deny` entries derived from `RiskDecisionRecord`, with lineage back to risk/decision/prediction/feature snapshot. It does not model paper execution lifecycle events, execution intent linkage, or PnL accounting.

## Evidence Reviewed

- `v2/backend/app/domain/paper_execution_ledger/record.py`
- `v2/backend/app/services/paper_execution_ledger/service.py`
- `v2/backend/app/composition/paper_execution_ledger/runtime.py`
- `v2/backend/app/domain/paper_mode/flag.py`
- `v2/backend/app/services/paper_mode/service.py`
- `v2/backend/app/composition/paper_mode/runtime.py`
- `v2/backend/app/api/schemas/paper_trade.py`
- `v2/backend/app/api/v1/paper.py`
- `v2/backend/app/services/paper_loop.py`
- `v2/backend/app/services/execution_router.py`
- `v2/backend/tests/unit/domain/paper_execution_ledger/`
- `v2/backend/tests/unit/services/paper_execution_ledger/`
- `v2/backend/tests/unit/composition/paper_execution_ledger/`
- `v2/backend/tests/unit/domain/paper_mode/`
- `v2/backend/tests/unit/services/paper_mode/`
- `v2/backend/tests/unit/composition/paper_mode/`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/`

## Passing Checks

1. Risk decision linkage exists.
   - `PaperExecutionLedgerEntry` carries `risk_decision_id`, `decision_id`, `prediction_id`, and `feature_snapshot_id` in `v2/backend/app/domain/paper_execution_ledger/record.py:91`.
   - The assembler copies those fields from `RiskDecisionRecord` in `v2/backend/app/services/paper_execution_ledger/service.py:80`.

2. Block events are represented at the risk-mirror level.
   - Domain constants include `record_deny` plus mirror deny reasons for orchestrator abstained, orchestrator held, and default deny in `v2/backend/app/domain/paper_execution_ledger/record.py:9` and `v2/backend/app/domain/paper_execution_ledger/record.py:13`.
   - The assembler maps deny risk reasons to `record_deny` entries in `v2/backend/app/services/paper_execution_ledger/service.py:65`.

3. Allow events are represented at the risk-mirror level.
   - Domain constants include `record_allow` plus mirror allow reasons for proceed long and proceed short in `v2/backend/app/domain/paper_execution_ledger/record.py:8` and `v2/backend/app/domain/paper_execution_ledger/record.py:11`.
   - The assembler maps allow long/short risk reasons to `record_allow` entries in `v2/backend/app/services/paper_execution_ledger/service.py:59`.

4. No real exchange action was found in the reviewed paper ledger path.
   - The paper ledger domain/service/composition layers do not import exchange adapters, HTTP clients, Redis clients, or order routers.
   - `v2/backend/app/services/paper_loop.py` is only a placeholder.
   - `v2/backend/app/services/execution_router.py` is only a placeholder stating live order calls remain blocked.
   - `v2/backend/app/api/v1/paper.py` exposes route metadata only, not order placement behavior.

5. Paper mode remains live-blocked.
   - `PaperModeFlag` requires `live_blocked is True`.
   - Paper mode tests cover rejection of live/live-enabled requested modes and live-blocked invariants.

## Blockers

1. Missing paper open/close/reduce/hedge lifecycle ledger events.
   - `PaperExecutionLedgerEntry` has only `ledger_action` values `record_allow` and `record_deny`.
   - There are no action constants, fields, or tests for `open`, `close`, `reduce`, or `hedge`.
   - The assembler only mirrors `allow_proceed_long`, `allow_proceed_short`, and deny reasons. It does not consume position state or an execution intent, so it cannot decide whether a signal opens a new position, reduces an existing one, closes it, or creates a hedge.

2. Missing PnL accounting.
   - `PaperExecutionLedgerEntry` has no quantity, price, fees, slippage, realized PnL, unrealized PnL, average entry price, position notional, or equity/balance fields.
   - `v2/backend/app/api/schemas/paper_trade.py` has `fill_price` and `fill_qty`, but this schema is not connected to the paper ledger implementation and contains no PnL fields.
   - The phase 2H specs explicitly state that 2H.A/2H.B/2H.C do not compute PnL, quantity, price, fees, or slippage, so the current milestone artifacts intentionally stop short of the requested MVP behavior.

3. Missing `execution_intent_id` linkage.
   - `PaperExecutionLedgerEntry` carries `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, and `symbol`, but not `execution_intent_id`.
   - The paper ledger assembler accepts only `decision: RiskDecisionRecord` plus `now_ms_clock`; it cannot propagate or verify an execution intent.
   - The route metadata for `/paper-trades` declares `execution_intent_id` as a required lineage-stage ID, but the paper ledger domain/service/composition implementation does not enforce or store it.

4. Missing executable paper-trade ledger integration.
   - `v2/backend/app/api/v1/paper.py` is scaffold metadata only.
   - `v2/backend/app/services/paper_loop.py` is a no-behavior placeholder.
   - There is no persistence or in-memory ledger component that accepts execution intents, records fills, updates positions, and emits lifecycle ledger rows.

5. Tests cover the narrow mirror contract, not the requested MVP.
   - Existing tests validate `record_allow` / `record_deny`, risk lineage propagation, live-blocked invariants, and no Redis/FastAPI import side effects.
   - I did not find tests for open/close/reduce/hedge entries, PnL calculations, execution intent lineage, or no-exchange-call behavior around a paper fill processor.

## Proposed Non-Live Autofix Tasks

1. Add a paper execution domain model that is still pure and non-live:
   - Define paper ledger event types for `open`, `close`, `reduce`, `hedge`, and `block`.
   - Include `execution_intent_id`, `risk_decision_id`, upstream lineage IDs, symbol, side, qty, fill price, fees, slippage, position before/after, realized PnL, and unrealized PnL fields.
   - Keep `live_blocked=True` mandatory.

2. Add a pure paper execution service:
   - Input: validated execution intent, linked risk decision, prior paper position state, fill assumptions, and clock.
   - Output: immutable ledger event plus updated paper position snapshot.
   - Reject unlinked or mismatched `execution_intent_id` / `risk_decision_id` chains.
   - Compute PnL deterministically without exchange, Redis, HTTP, or live adapters.

3. Add a non-live paper ledger store boundary:
   - For MVP tests, use an explicit in-memory or repository protocol fake, not Redis and not real exchange adapters.
   - Ensure any future DB adapter is separated from the pure accounting service.

4. Add test coverage:
   - Opening long/short from flat creates `open`.
   - Same-side smaller opposing intent creates `reduce`.
   - Opposing intent that fully offsets creates `close`.
   - Opposing intent beyond flat creates close plus new open, or explicit `hedge`, depending on the chosen position-mode contract.
   - Denied risk decisions create `block` and never mutate position.
   - Realized PnL, fees, and average entry price are asserted with deterministic fixtures.
   - `execution_intent_id` is present and lineage mismatches are rejected.
   - Exchange adapters, CCXT, HTTP clients, Redis writes, order placement calls, leverage/margin changes, and live-mode affordances are not imported or invoked.

## Safety Notes

No live exchange action path was found in the reviewed implementation. The blocker is functional completeness for the requested Paper Execution Ledger MVP, not unsafe live behavior in the inspected paper ledger code.

END_FILE: claude_worklog/codex_parallel_reviews/20260508_230322_04_paper_execution_ledger_REPORT.md
