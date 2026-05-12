# Codex Parallel Review - Paper Execution Ledger MVP

Review timestamp: 2026-05-12 17:26:53 local lane packet
Scope inspected:
- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl`
- `claude_worklog/phase2_core_rebuild/paper_mode_impl`

Verdict: BLOCKED

## Summary

The implementation is non-live and carries risk-decision lineage in the narrow 2H paper-ledger mirror path, but it does not satisfy the requested Paper Execution Ledger MVP checks as a canonical ledger.

The canonical `PaperExecutionLedgerEntry` only records `record_allow` / `record_deny` mirror events from `RiskDecisionRecord`. It has no open, close, reduce, hedge, or block event taxonomy; no `execution_intent_id`; and no PnL, quantity, price, fee, or slippage fields. Those richer fields appear only in fixture/proof or CLI payloads, not in the domain/service/composition ledger contract.

## Findings

### BLOCKER 1 - Canonical ledger lacks open/close/reduce/hedge/block lifecycle events

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py:8-15` defines only `PAPER_LEDGER_ACTION_RECORD_ALLOW`, `PAPER_LEDGER_ACTION_RECORD_DENY`, and five mirror reason constants.
- `v2/backend/app/domain/paper_execution_ledger/record.py:17-31` restricts allowed ledger actions/reasons to those mirror values.
- `v2/backend/app/services/paper_execution_ledger/service.py:59-78` maps risk reasons only to `record_allow` / `record_deny`.

Impact:
- The requested open/close/reduce/hedge/block ledger event coverage is not present in the canonical ledger MVP.
- Fixture proof has `open`, `close`, `reduce`, and `block` rows in `v2/backend/app/proof/non_live_operational_proof.py:185-198`, but that is not wired through `PaperExecutionLedgerEntry`.
- No canonical hedge ledger event was found.

Non-live autofix task:
- Extend `PaperExecutionLedgerEntry` with an explicit `ledger_event_type` taxonomy containing `open`, `close`, `reduce`, `hedge`, and `block`, plus tests for each event type.
- Keep the implementation pure and non-live; do not add adapters, persistence, Redis, or exchange clients.

### BLOCKER 2 - Canonical ledger has no PnL accounting contract

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py:90-103` lists the full dataclass fields and contains no PnL/accounting fields.
- `v2/backend/app/services/paper_execution_ledger/service.py:80-93` constructs entries without realized PnL, unrealized PnL, notional, quantity, price, fees, slippage, or account equity.
- The 2H specs explicitly state no PnL computation in the paper-ledger domain/service/composition.

Impact:
- Fixture proof computes/summarizes PnL in `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:187-223`, and the online CLI has a paper-only account calculation in `v2/backend/app/cli/paper_online_runtime.py:376-422`, but neither is the canonical Paper Execution Ledger MVP object.

Non-live autofix task:
- Add a pure accounting value object or ledger extension for `paper_pnl`, `realized_pnl`, `unrealized_pnl`, `notional`, `quantity`, `fill_price`, `fee`, and `slippage`, with deterministic tests for open, close, reduce, hedge, and block/no-fill behavior.
- Use fixture inputs only; do not call exchanges or Redis.

### BLOCKER 3 - Canonical ledger does not link `execution_intent_id`

Evidence:
- `v2/backend/app/domain/paper_execution_ledger/record.py:90-103` includes `paper_trade_id`, `risk_decision_id`, `decision_id`, `prediction_id`, and `feature_snapshot_id`, but no `execution_intent_id`.
- `v2/backend/app/services/paper_execution_ledger/service.py:80-93` derives `paper_trade_id` from `risk_decision_id` and does not accept or propagate execution intent.
- Existing execution-domain files under `v2/backend/app/domain/execution/` are placeholders only.

Impact:
- The requested `execution_intent_id` linkage is not enforced in the canonical paper ledger.
- Fixture/proof payloads include `execution_intent_id` in `v2/backend/app/proof/non_live_operational_proof.py:106-129` and `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:334-376`, but this does not close the domain/service/composition gap.

Non-live autofix task:
- Introduce a pure `ExecutionIntentRecord` or pass a validated `execution_intent_id` into the paper-ledger assembler.
- Add cross-field tests that every ledger entry links `risk_decision_id` and `execution_intent_id` and rejects missing or mismatched IDs.

### PASS - Risk decision linkage exists in the narrow mirror ledger

Evidence:
- `PaperExecutionLedgerEntry` carries `risk_decision_id`, `input_risk_action`, and `input_risk_reason_code` in `v2/backend/app/domain/paper_execution_ledger/record.py:90-103`.
- The assembler propagates those fields from `RiskDecisionRecord` in `v2/backend/app/services/paper_execution_ledger/service.py:80-93`.
- The domain enforces allow/deny and reason consistency in `v2/backend/app/domain/paper_execution_ledger/record.py:156-223`.

Residual risk:
- This linkage is only for mirror allow/deny records, not lifecycle execution events.

### PASS - No real exchange actions found in reviewed paper-ledger path

Evidence:
- The 2H paper-ledger domain/service/composition files contain no exchange adapter, Redis, HTTP, order placement, leverage, or margin behavior.
- `v2/backend/app/services/execution_router.py` and `v2/backend/app/services/paper_loop.py` are placeholders with no executable live behavior.
- `v2/backend/app/proof/readonly_market_exchange_data_plane.py:38-48` enumerates forbidden mutation methods, and `v2/backend/app/proof/readonly_market_exchange_data_plane.py:89-108` fail-closes order/leverage/margin mutation methods.
- `v2/backend/app/cli/paper_online_runtime.py:474-521` marks `exchange_orders`, `leverage_changes`, and `margin_mode_changes` false and reports orders as `BLOCKED_NO_EXCHANGE_MUTATION`.

## Proposed Non-Live Autofix Plan

1. Add a pure execution intent record and validation tests.
2. Extend the canonical paper ledger record with lifecycle `ledger_event_type`, `execution_intent_id`, and paper accounting fields.
3. Update the assembler to accept risk decision plus execution intent plus deterministic fill/accounting inputs.
4. Add exhaustive tests for open, close, reduce, hedge, and block events, including PnL and no-fill block accounting.
5. Preserve all current hard safety boundaries: no Redis writes/deletes, no exchange mutation calls, no service restarts, no live trading enablement, no deployment.

## Validation Notes

No live services were restarted. No Redis commands were run. No orders, leverage, margin, deployment, or live-trading changes were attempted.
