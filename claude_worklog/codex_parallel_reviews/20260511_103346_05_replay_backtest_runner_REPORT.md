# Codex Parallel Review: Replay Backtest Runner MVP

Status: BLOCKED

Scope reviewed:
- `v2/backend/app/domain/replay_backtest_runner/`
- `v2/backend/app/services/replay_backtest_runner/`
- `v2/backend/app/composition/replay_backtest_runner/`
- `v2/backend/app/api/v1/replay.py`
- `v2/backend/app/proof/non_live_operational_proof.py`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`
- `v2/backend/tests/unit/domain/replay_backtest_runner/`
- `v2/backend/tests/unit/services/replay_backtest_runner/`
- `v2/backend/tests/unit/composition/replay_backtest_runner/`
- `v2/backend/tests/unit/historical_pnl_replay_wiring/`
- `v2/backend/tests/unit/proof/`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/`
- `claude_worklog/historical_pnl_audit/`

Safety constraints honored:
- Did not modify `/home/wali/Desktop/AI BOT`.
- Did not write Redis.
- Did not delete Redis keys.
- Did not restart services.
- Did not place/cancel orders.
- Did not change leverage/margin.
- Did not enable live trading.
- Did not deploy.
- Did not expose secrets.
- Only wrote this report and the requested GO/NO-GO marker under `claude_worklog/codex_parallel_reviews/`.

## Summary

The implemented replay/backtest runner is a pure mirror-count assembler over `PaperExecutionLedgerEntry` inputs. It validates replay run/step/summary value objects, maps paper-ledger mirror reason codes to replay step reason codes, and emits action/reason count summaries.

That is narrower than the requested review topic. It does not implement replay input contracts for market fills/trade economics, backtest output metrics beyond counts, PnL or drawdown calculation, historical PnL comparison against the committed audit, or large winner/loser attribution. The surrounding proof harnesses use deterministic fixture strings and placeholders, and the historical audit itself is marked partial/local-only with `NO_DATA` PnL tables.

## Evidence

1. Replay summary output has only count metrics.
   - `v2/backend/app/domain/replay_backtest_runner/summary.py:32` defines `ReplayBacktestSummary`.
   - Fields at lines 34-45 are IDs, timestamps, action counts, reason counts, and `live_blocked`.
   - There are no fields for gross/net PnL, fees, funding, equity curve, max drawdown, win rate, trade returns, per-symbol PnL, or winner/loser attribution.

2. Service aggregation only counts actions and mirror reasons.
   - `v2/backend/app/services/replay_backtest_runner/service.py:186` sets `total_steps_count = len(steps)`.
   - Lines 187-210 increment only `record_allow`, `record_deny`, and mirror reason counters.
   - Lines 213-226 construct `ReplayBacktestSummary` from those counters only.

3. Step assembly has no trade economics input.
   - `v2/backend/app/services/replay_backtest_runner/service.py:30` accepts only `paper_ledger_entry`, `replay_run`, and `now_ms_clock`.
   - The returned step at lines 113-128 carries lineage and mirror action/reason fields only.
   - No price, quantity, side sizing, fill timestamp, commission, funding, slippage, realized PnL, or position state is accepted or produced.

4. Public replay API is still scaffold-only.
   - `v2/backend/app/api/v1/replay.py:1` describes `/replay/` as deterministic replay.
   - Lines 4-20 expose only an OPTIONS metadata shim with `milestone_d_status = "skeleton"`.
   - There is no endpoint contract for submitting replay inputs or retrieving backtest metrics.

5. Existing historical replay wiring tests explicitly prohibit market/PnL fields.
   - `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:33` defines `DISALLOWED_MARKET_FIELDS`.
   - Lines 35-48 include `pnl`, `realized_pnl`, `size`, `quantity`, `price`, `fees`, `slippage`, `funding`, `hedge_state`, `residual_exposure`, and `squeeze_risk`.
   - Lines 157-162 assert replay records are disjoint from those fields.

6. Non-live proof uses a drawdown placeholder, not a calculation.
   - `v2/backend/app/proof/non_live_operational_proof.py:263` builds `replay_result`.
   - Line 271 hard-codes `gross_paper_pnl` as `"+12.40"`.
   - Line 272 hard-codes `max_drawdown_placeholder` as `"0.00"`.

7. Historical 30D proof uses deterministic fixture PnL, not historical-audit-derived PnL.
   - `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:180` builds local deterministic fixtures.
   - Lines 187-189 sum fixture string fields.
   - Lines 241-245 disclose that account-history credentials were unavailable and realized PnL values are fixture values.

8. Historical audit source does not provide real comparison data.
   - `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md` contains `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.
   - `03_30D_REALIZED_PNL_BY_DAY.md`, `04_30D_PNL_BY_SYMBOL.md`, `05_30D_FEES_FUNDING_COMMISSION.md`, and `06_LARGE_WINNERS_AND_LOSERS.md` contain `NO_DATA` rows.

## Check Results

- Replay input contracts: BLOCKED. Current contracts cover replay IDs, symbols, timestamps, live-blocked flags, paper-ledger lineage, and mirror reason mapping. They do not define economic replay inputs such as fills, quantity, price, fees, funding, position state, or historical trade references needed for PnL replay.
- Backtest output metrics: BLOCKED. Current output is count-only. Required economics and performance metrics are absent.
- PnL/drawdown calculation: BLOCKED. No PnL engine or drawdown calculation exists in the replay/backtest runner. Proof code uses hard-coded fixture values and a `max_drawdown_placeholder`.
- Historical PnL comparison: BLOCKED. Historical audit data is partial/local-only and `NO_DATA`; proof comparison uses deterministic fixtures rather than audit-derived realized trade data.
- Large winner/loser attribution: BLOCKED. The replay runner has no attribution model, no realized trade linkage beyond pointer strings in test harnesses, and the historical audit winner/loser table is `NO_DATA`.

## Concrete Blockers

1. No economic replay input value object exists.
   - Impact: Cannot calculate PnL, drawdown, or attribution.
   - Evidence: Replay step and summary contracts contain no price/quantity/fee/funding/fill fields.

2. Replay/backtest summary is count-only.
   - Impact: Cannot satisfy backtest output metric requirements.
   - Evidence: `ReplayBacktestSummary` exposes only step counts and reason counts.

3. PnL and drawdown are placeholders/fixtures outside the replay runner.
   - Impact: Any reported profitability or drawdown is not produced by the runner under review.
   - Evidence: `gross_paper_pnl` and `max_drawdown_placeholder` are hard-coded in `non_live_operational_proof.py`.

4. Historical audit data is unavailable for real comparison.
   - Impact: Cannot validate historical PnL comparison or large winner/loser attribution against the committed audit.
   - Evidence: historical audit marker is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`; PnL tables show `NO_DATA`.

5. Tests lock in absence of market/PnL fields.
   - Impact: Existing test intent conflicts with the requested review criteria.
   - Evidence: historical PnL replay wiring tests assert no PnL, size, price, fee, funding, or hedge fields appear.

## Proposed Non-Live Autofix Tasks

1. Add a non-live `ReplayBacktestFillInput` / `ReplayBacktestTradeInput` domain contract with symbol, side, quantity, entry/exit price, fill timestamps, commission, funding, slippage, and lineage IDs. Keep `live_blocked=True` mandatory and avoid any exchange/Redis/service side effects.

2. Add a pure `ReplayBacktestMetrics` value object with gross PnL, net PnL, fees, funding, trade count, win/loss counts, win rate, largest winner, largest loser, cumulative equity points, peak equity, trough equity, and max drawdown.

3. Implement a pure in-memory metrics assembler that consumes only supplied non-live fixture/audit rows and returns `ReplayBacktestMetrics`. It must not call exchange APIs, Redis, files, wall clock, or order/risk mutation surfaces.

4. Replace `max_drawdown_placeholder` in the non-live proof with the pure metrics result, and update tests to assert a calculated drawdown from a small deterministic equity curve.

5. Add historical comparison fixtures generated from committed local audit files only. If audit files contain `NO_DATA`, the runner should emit an explicit `historical_comparison_status = "blocked_no_historical_pnl_data"` instead of pretending comparison succeeded.

6. Add large winner/loser attribution output keyed by trade ID, symbol, side, PnL, reason code, feature snapshot ID, prediction ID, decision ID, risk decision ID, and paper trade ID.

7. Update tests that currently prohibit PnL/market fields so they remain appropriate for the old wiring harness or move them behind a narrower fixture-only assertion, then add new tests for the economics-enabled replay/backtest contracts.

## Validation

No live or mutating validation commands were run. This was a read-only code and artifact review plus creation of the two requested review files.
