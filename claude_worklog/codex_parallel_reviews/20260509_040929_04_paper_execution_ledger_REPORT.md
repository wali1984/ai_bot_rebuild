BEGIN_FILE: claude_worklog/codex_parallel_reviews/20260509_040929_04_paper_execution_ledger_REPORT.md
# Codex Parallel Review: Paper Execution Ledger MVP

Review mode: read-only parallel review. I inspected the requested `v2/backend/app`, `v2/backend/tests`, `paper_execution_ledger_impl`, and `paper_mode_impl` inputs and wrote only this requested report plus the requested one-line GO/NO-GO artifact. I did not write Redis, delete Redis keys, restart services, place/cancel orders, change leverage/margin, enable live trading, or deploy.

Verdict: BLOCKED

The implementation is safe and non-live, but it is still a risk-decision mirror ledger rather than a Paper Execution Ledger MVP. It records immutable `record_allow` / `record_deny` entries linked to a `RiskDecisionRecord`; it does not yet model paper execution lifecycle events, execution intent linkage, or PnL accounting in the product ledger path.

## Evidence Reviewed

- `v2/backend/app/domain/paper_execution_ledger/record.py`
- `v2/backend/app/services/paper_execution_ledger/service.py`
- `v2/backend/app/composition/paper_execution_ledger/runtime.py`
- `v2/backend/app/domain/risk_gateway/record.py`
- `v2/backend/app/services/risk_gateway/service.py`
- `v2/backend/app/domain/paper_mode/flag.py`
- `v2/backend/app/services/paper_mode/service.py`
- `v2/backend/app/composition/paper_mode/runtime.py`
- `v2/backend/app/api/schemas/execution_intent.py`
- `v2/backend/app/api/schemas/paper_trade.py`
- `v2/backend/app/api/v1/paper.py`
- `v2/backend/app/services/execution_router.py`
- `v2/backend/app/services/paper_loop.py`
- `v2/backend/app/proof/non_live_operational_proof.py`
- `v2/backend/tests/unit/domain/paper_execution_ledger/`
- `v2/backend/tests/unit/services/paper_execution_ledger/`
- `v2/backend/tests/unit/composition/paper_execution_ledger/`
- `v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/`

## Passing Checks

1. Risk decision linkage exists in the narrow mirror ledger.
   - `PaperExecutionLedgerEntry` carries `risk_decision_id`, `decision_id`, `prediction_id`, and `feature_snapshot_id` in `v2/backend/app/domain/paper_execution_ledger/record.py:90`.
   - `assemble_paper_execution_ledger_entry` copies those fields from `RiskDecisionRecord` in `v2/backend/app/services/paper_execution_ledger/service.py:80`.

2. Risk allow/block decisions are mirrored.
   - Domain action constants are only `record_allow` and `record_deny` in `v2/backend/app/domain/paper_execution_ledger/record.py:8`.
   - The service maps allow long/short and deny reasons to those mirror actions in `v2/backend/app/services/paper_execution_ledger/service.py:59`.

3. Live execution remains blocked in the reviewed ledger path.
   - `PaperExecutionLedgerEntry` requires `live_blocked is True` in `v2/backend/app/domain/paper_execution_ledger/record.py:151`.
   - The assembler hardcodes `live_blocked=True` in `v2/backend/app/services/paper_execution_ledger/service.py:92`.
   - `execution_router.py` and `paper_loop.py` are placeholders with no order behavior.

4. Fixture-level proof data demonstrates intended non-live examples, but not product ledger implementation.
   - The proof harness emits fixture `open`, `close`, `reduce`, and `block` events in `v2/backend/app/proof/non_live_operational_proof.py:240`.
   - Its tests assert those fixture event types in `v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py:46`.

## Blockers

1. Missing paper open/close/reduce/hedge/block product ledger events.
   - The product ledger accepts only `record_allow` and `record_deny`; there are no product action constants or record fields for `open`, `close`, `reduce`, `hedge`, or `block`.
   - The proof harness has fixture `open`, `close`, `reduce`, and `block` rows, but those are generated dictionaries, not `PaperExecutionLedgerEntry` product events.
   - I found no `hedge` product ledger event implementation or test.

2. Missing PnL accounting.
   - `PaperExecutionLedgerEntry` has no fill price, quantity, fee, slippage, realized PnL, unrealized PnL, average entry price, position before/after, or balance/equity fields.
   - `PaperTradeAck` has `fill_price` and `fill_qty`, but it is a scaffold schema and is not wired into the ledger service.
   - The proof harness stores string fixture values such as `+12.40` and `legacy_loss_avoided`; it does not provide deterministic product accounting.

3. Missing `execution_intent_id` linkage in the product ledger.
   - `PaperExecutionLedgerEntry` does not include `execution_intent_id`.
   - `assemble_paper_execution_ledger_entry` accepts only `decision: RiskDecisionRecord` and `now_ms_clock`, so it cannot validate or propagate an execution intent.
   - `ExecutionIntentSubmit` and route metadata name `execution_intent_id`, but that lineage is not enforced by the paper ledger implementation.

4. Missing executable paper ledger integration.
   - `/paper-trades` is scaffold metadata only.
   - `paper_loop.py` has no behavior.
   - There is no pure paper fill processor, paper position state transition, or ledger repository boundary that records paper lifecycle events while proving no exchange adapter is invoked.

5. Tests cover the mirror contract, not the requested MVP.
   - Existing paper ledger unit tests validate allow/deny mirror taxonomy, risk lineage propagation, clock handling, frozen records, live-blocked invariants, and import-safety constraints.
   - I did not find product tests for open/close/reduce/hedge/block lifecycle entries, PnL calculations, execution-intent linkage rejection on mismatches, or no-exchange-call assertions around paper fill handling.

## Proposed Non-Live Autofix Tasks

1. Add pure product paper execution ledger domain records.
   - Define event types `open`, `close`, `reduce`, `hedge`, and `block`.
   - Include `execution_intent_id`, `risk_decision_id`, upstream lineage IDs, symbol, side, quantity, fill price, fees, slippage, position before/after, realized PnL, unrealized PnL, and mandatory `live_blocked=True`.

2. Add a pure paper accounting service.
   - Input: execution intent, linked risk decision, prior paper position snapshot, deterministic fill assumption, fee/slippage assumptions, and clock.
   - Output: immutable lifecycle ledger event plus updated paper position snapshot.
   - Reject missing or mismatched `execution_intent_id` / `risk_decision_id` / `symbol` / side lineage.

3. Keep the implementation non-live by construction.
   - Use only in-memory fakes or explicit repository protocols in tests.
   - Do not import exchange clients, CCXT, HTTP clients, Redis clients, live order routers, leverage/margin helpers, schedulers, or service restart hooks.

4. Add focused tests.
   - Flat plus allowed long/short creates `open`.
   - Opposing smaller intent creates `reduce`.
   - Opposing equal intent creates `close`.
   - Hedge-mode contract creates `hedge`, or single-position mode explicitly rejects/blocks hedge attempts.
   - Denied risk creates `block` and does not mutate position.
   - Realized/unrealized PnL, fees, average entry, and position state are deterministic.
   - `execution_intent_id` is present and lineage mismatches fail closed.
   - No exchange action, Redis write/delete, leverage/margin change, live-mode flag, or deployment path is imported or invoked.

## Safety Notes

No real exchange action path was found in the reviewed paper ledger implementation. The blocker is functional completeness for the requested Paper Execution Ledger MVP, not unsafe live behavior in the inspected code.

END_FILE: claude_worklog/codex_parallel_reviews/20260509_040929_04_paper_execution_ledger_REPORT.md
