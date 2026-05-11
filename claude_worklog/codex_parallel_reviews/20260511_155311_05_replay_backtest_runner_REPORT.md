# Codex Parallel Review: Replay Backtest Runner MVP

Status: BLOCKED

Scope reviewed:
- `v2/backend/app/domain/replay_backtest_runner/`
- `v2/backend/app/services/replay_backtest_runner/`
- `v2/backend/app/composition/replay_backtest_runner/`
- `v2/backend/app/domain/replay/`
- `v2/backend/app/services/replay_runner.py`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`
- `v2/backend/tests/unit/domain/replay_backtest_runner/`
- `v2/backend/tests/unit/services/replay_backtest_runner/`
- `v2/backend/tests/unit/composition/replay_backtest_runner/`
- `v2/backend/tests/unit/historical_pnl_replay_wiring/`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/`
- `claude_worklog/historical_pnl_audit/`

Safety constraints honored:
- Did not modify `/home/wali/Desktop/AI BOT`.
- Did not write Redis or delete Redis keys.
- Did not restart live services.
- Did not place or cancel orders.
- Did not change leverage or margin.
- Did not enable live trading.
- Did not deploy.
- Did not expose secrets.
- Only wrote this report and the requested GO/NO-GO marker under `claude_worklog/codex_parallel_reviews/`.

## Summary

The current Replay Backtest Runner MVP is a pure, non-live mirror assembler over `PaperExecutionLedgerEntry` records. It validates replay run/step/summary value objects, maps paper-ledger mirror reasons into replay step reasons, and emits count-only summaries.

That implementation is safe for its declared Phase 2I scope, but it is not sufficient for the review checks requested here. It does not define economic replay inputs, does not output PnL/performance metrics, does not calculate drawdown, does not compare against usable historical PnL, and does not attribute large winners/losers. The committed historical audit data is also unavailable for those checks: Binance read-only pull rows are zero and the PnL/winner-loser tables contain `NO_DATA`.

## Check Results

- Replay input contracts: BLOCKED. Current contracts cover IDs, symbol, timestamps, `live_blocked`, paper-ledger lineage, and mirror reason mapping. They do not cover fill/trade economics such as side, quantity, entry/exit price, fees, funding, slippage, or position state.
- Backtest output metrics: BLOCKED. `ReplayBacktestSummary` contains only step counts and reason counts; no gross/net PnL, fees, funding, win/loss stats, equity curve, drawdown, or attribution fields exist.
- PnL/drawdown calculation: BLOCKED. No PnL engine or drawdown calculation exists in the replay/backtest runner. The historical proof path uses deterministic fixture strings rather than runner-computed economics.
- Historical PnL comparison: BLOCKED. The historical audit is partial/local-only and contains `NO_DATA`; `02_BINANCE_READONLY_PULL_SUMMARY.md` reports `income_rows: 0`, `trade_rows: 0`, and `order_rows: 0`.
- Large winner/loser attribution: BLOCKED. The historical winner/loser table is `NO_DATA`, and the runner has no realized trade economics or attribution model.

## Evidence

1. `v2/backend/app/domain/replay_backtest_runner/summary.py:32` defines `ReplayBacktestSummary`; fields at lines 34-45 are IDs, emitted timestamp, action/reason counts, and `live_blocked` only.
2. `v2/backend/app/services/replay_backtest_runner/service.py:30` accepts only `paper_ledger_entry`, `replay_run`, and `now_ms_clock` for step assembly; lines 113-128 return lineage plus mirror action/reason fields only.
3. `v2/backend/app/services/replay_backtest_runner/service.py:186` starts summary aggregation with `total_steps_count = len(steps)`; lines 187-210 increment only allow/deny and mirror reason counters; lines 213-226 return those counters.
4. `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:33` defines `DISALLOWED_MARKET_FIELDS`; lines 35-48 include `pnl`, `realized_pnl`, `size`, `quantity`, `price`, `fees`, `slippage`, `funding`, `hedge_state`, `residual_exposure`, and `squeeze_risk`; lines 157-162 assert replay records are disjoint from those fields.
5. `claude_worklog/historical_pnl_audit/02_BINANCE_READONLY_PULL_SUMMARY.md:7` reports `income_rows: 0`; lines 8-9 report `trade_rows: 0` and `order_rows: 0`; line 14 records `BINANCE_PULL_NOT_REQUESTED`.
6. `claude_worklog/historical_pnl_audit/03_30D_REALIZED_PNL_BY_DAY.md:5` contains `NO_DATA`.
7. `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md:6` and line 11 contain `NO_DATA` for largest losers and winners.
8. `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md` contains `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.

## Concrete Blockers

1. No economic replay input contract exists.
   - Impact: PnL, drawdown, historical comparison, and attribution cannot be calculated.
   - Evidence: Current runner inputs do not include price, quantity, fee, funding, slippage, fill timestamp, or position state.

2. Backtest output metrics are count-only.
   - Impact: The runner cannot satisfy backtest output metric requirements beyond mirror action/reason counts.
   - Evidence: `ReplayBacktestSummary` has no PnL, drawdown, equity, fee/funding, win/loss, or winner/loser fields.

3. Existing historical replay wiring tests intentionally prohibit market/PnL fields.
   - Impact: The test contract currently locks in the absence of the exact fields needed for this review topic.
   - Evidence: `DISALLOWED_MARKET_FIELDS` includes PnL and market economics, and the test asserts no such fields are emitted.

4. Historical PnL evidence is unavailable.
   - Impact: Historical PnL comparison and winner/loser attribution cannot be validated against committed data.
   - Evidence: Binance pull summary has zero rows and the audit tables show `NO_DATA`.

## Proposed Non-Live Autofix Tasks

1. Add a pure `ReplayBacktestTradeInput` or `ReplayBacktestFillInput` value object with symbol, side, quantity, entry/exit price, fill timestamps, commission, funding, slippage, source evidence pointer, and lineage IDs. Keep `live_blocked=True` mandatory.
2. Add a pure `ReplayBacktestMetrics` value object with gross PnL, net PnL, fees, funding, trade count, win/loss count, win rate, largest winner, largest loser, cumulative equity points, peak/trough equity, and max drawdown.
3. Implement an in-memory metrics assembler that consumes only supplied fixture/audit rows and returns `ReplayBacktestMetrics`. It must not call exchange APIs, Redis, files, wall clock, order placement, leverage/margin, or deployment surfaces.
4. Replace placeholder/fixture-only proof outputs with metrics produced by the pure assembler, and add deterministic tests for PnL and drawdown from small static trade/equity fixtures.
5. Add historical comparison status handling: when committed audit files contain `NO_DATA`, emit an explicit blocked status such as `historical_comparison_status = "blocked_no_historical_pnl_data"` instead of reporting a successful comparison.

CODEX_PARALLEL_REVIEW_BLOCKED
