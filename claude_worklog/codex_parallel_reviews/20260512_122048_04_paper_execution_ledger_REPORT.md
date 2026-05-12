# Codex Parallel Review - Paper Execution Ledger MVP

Review mode: read-only inspection of `v2/backend/app`, `v2/backend/tests`, `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl`, and `claude_worklog/phase2_core_rebuild/paper_mode_impl`.

Verdict: BLOCKED for the requested Paper Execution Ledger MVP checklist.

## Scope Observed

The implemented paper execution ledger is a narrow risk-decision mirror:

- Domain constants only allow `record_allow` and `record_deny` ledger actions in `v2/backend/app/domain/paper_execution_ledger/record.py:8-21`.
- Domain reasons only mirror five risk-gateway reasons: allow long, allow short, deny held, deny abstained, and deny default in `v2/backend/app/domain/paper_execution_ledger/record.py:11-30`.
- The ledger entry carries `paper_trade_id`, `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, timestamp, ledger action/reason, input risk action/reason, and `live_blocked` in `v2/backend/app/domain/paper_execution_ledger/record.py:90-103`.
- The service maps a `RiskDecisionRecord` into those mirror actions/reasons and derives `paper_trade_id="pt_" + risk_decision_id` in `v2/backend/app/services/paper_execution_ledger/service.py:26-92`.
- The composition root returns a callable recorder that accepts only `decision: RiskDecisionRecord` and returns the assembled entry in `v2/backend/app/composition/paper_execution_ledger/runtime.py:15-27`.

The phase planning artifacts confirm this narrow scope was intentional for Phase 2H: the sub-phase breakdown explicitly says Phase 2H must not expand into a PnL/position-sizing subsystem, execution-side surface, paper trader process, or persistent ledger storage, and the assembler does not compute PnL or carry quantity/price/fees (`claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/00_PHASE_2H_SUB_PHASE_BREAKDOWN.md:3` and `:20-28`).

## Passing Checks

- Risk decision linkage is present: `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, `input_risk_action`, and `input_risk_reason_code` are propagated into the ledger entry in `v2/backend/app/services/paper_execution_ledger/service.py:80-91`.
- Risk decision mirroring is fail-closed for the known current risk reason vocabulary: unrecognized risk reasons raise `PaperExecutionLedgerServiceError("unrecognized_risk_reason_code")` in `v2/backend/app/services/paper_execution_ledger/service.py:74-78`.
- The ledger is non-live by construction: domain validation requires `live_blocked is True` in `v2/backend/app/domain/paper_execution_ledger/record.py:151-154`, and the service hard-codes `live_blocked=True` in `v2/backend/app/services/paper_execution_ledger/service.py:92`.
- No real exchange action was found in the paper execution ledger implementation. The related `execution_router.py` and `paper_loop.py` files remain placeholders with no behavior.
- The inspected paper-mode implementation also preserves a non-live posture; no evidence was found that it enables live trading, order placement, leverage/margin changes, Redis writes, or service restarts.

## Blockers

1. Missing paper open/close/reduce/hedge/block execution-event ledger taxonomy.

Evidence: the only ledger actions are `record_allow` and `record_deny` (`record.py:8-21`). There are no ledger actions or tests for paper open, close, reduce, hedge, or block events. The service only mirrors risk reasons into allow/deny records (`service.py:59-78`).

Impact: the requested MVP cannot represent paper lifecycle events beyond "risk allowed" or "risk denied". It cannot distinguish an allowed open from an actual paper open event, and it cannot record closes, reductions, hedge activity, or explicit block events as first-class ledger entries.

2. Missing PnL accounting.

Evidence: `PaperExecutionLedgerEntry` has no fields for side, quantity, entry price, exit price, realized PnL, unrealized PnL, fees, slippage, balance/equity, or position state (`record.py:90-103`). The service computes no PnL and only returns lineage plus mirror action/reason (`service.py:80-92`). The Phase 2H planning file explicitly excludes PnL, quantity, price, fees, and position sizing from the implementation (`00_PHASE_2H_SUB_PHASE_BREAKDOWN.md:20-21`).

Impact: the ledger cannot validate or report paper PnL for open/close/reduce events, nor can replay/backtest consumers reconcile paper fills against accounting state.

3. Missing `execution_intent_id` linkage.

Evidence: no inspected paper ledger source or tests reference `execution_intent_id`. The ledger entry fields stop at `risk_decision_id`, `decision_id`, `prediction_id`, and `feature_snapshot_id` (`record.py:90-103`). `v2/backend/app/domain/execution/intent.py` is still a placeholder module with no intent record.

Impact: paper ledger entries cannot be joined to execution intents. This breaks the requested execution-intent lineage check and makes it impossible to distinguish multiple execution intents derived from the same upstream risk decision.

4. No integration point records actual paper execution outcomes.

Evidence: `paper_loop.py` is a one-line placeholder, `execution_router.py` is a placeholder, and the composition recorder accepts only a `RiskDecisionRecord` (`runtime.py:24-25`). There is no paper fill/position state input at the ledger boundary.

Impact: even when risk allows a decision, the system records only that allowance, not a paper execution outcome or blocked execution outcome.

## Proposed Non-Live Autofix Tasks

1. Extend the paper execution ledger domain with a non-live execution event model:
   - Add first-class actions or event types for `paper_open`, `paper_close`, `paper_reduce`, `paper_hedge`, and `paper_block`.
   - Add `execution_intent_id` as a required validated lineage field.
   - Preserve `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, `symbol`, and mandatory `live_blocked=True`.

2. Add deterministic paper accounting fields and invariants:
   - Include side, quantity, price basis, realized PnL, fees, slippage, and resulting position quantity where needed.
   - Use integer or decimal-safe accounting inputs rather than floats for core PnL math.
   - Add tests for long and short open/close/reduce flows, partial reduce, full close, hedge/block events, zero/negative invalid quantities, and fee/slippage effects.

3. Add an assembler service that accepts validated non-live execution intent plus risk decision plus paper fill/accounting inputs:
   - Require matching `risk_decision_id` and `execution_intent_id` lineage.
   - Fail closed when the risk decision is deny, stale, mismatched, or missing.
   - Emit a block event instead of an execution event for denied decisions.

4. Add composition tests proving no real exchange actions:
   - Keep the paper recorder free of exchange adapters, Redis writes, order placement/cancellation, leverage/margin changes, and live-trading enablement.
   - Add forbidden-token/import tests for exchange mutation verbs and live execution clients in the paper ledger modules.

5. Add replay-facing tests:
   - Verify every paper execution ledger event has risk-decision and execution-intent linkage.
   - Verify PnL totals reconcile across open, reduce, close, hedge, and block scenarios.
   - Verify blocked events carry no fill/PnL mutation except explicit no-op accounting fields.

## Safety Notes

This review did not modify `/home/wali/Desktop/AI BOT`, did not write Redis, did not delete Redis keys, did not restart live services, did not place or cancel orders, did not change leverage or margin, did not enable live trading, and did not deploy.
