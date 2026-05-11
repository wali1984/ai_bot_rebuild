# Replay Backtest Runner MVP Parallel Review

Status: BLOCKED

Scope inspected:
- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl`
- `claude_worklog/historical_pnl_audit`

Verification run:
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider v2/backend/tests/unit/services/replay_backtest_runner v2/backend/tests/unit/composition/replay_backtest_runner v2/backend/tests/unit/historical_pnl_replay_wiring v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py -q`
- Result: `95 passed in 0.24s`

Summary:

The current Phase 2I replay backtest runner is a pure non-live mirror assembler. It validates replay run/step/summary value objects, maps paper ledger allow/deny reasons into replay step reasons, keeps `live_blocked=True`, and aggregates step/reason counts. That implementation is import-clean and covered by focused tests, but it is not sufficient for the requested Replay Backtest Runner MVP checks because it does not model trade economics, compute PnL or drawdown, compare against populated historical PnL, or attribute large winners/losers.

Findings by requested check:

1. Replay input contracts: BLOCKED
   - `ReplayBacktestRun` contains only `replay_run_id`, `run_mode`, `symbol`, run timestamps, and `live_blocked` (`v2/backend/app/domain/replay_backtest_runner/run.py:31`).
   - `ReplayBacktestStep` contains lineage IDs, symbol, step timestamp, mirrored action/reason fields, and `live_blocked` (`v2/backend/app/domain/replay_backtest_runner/step.py:70`).
   - The upstream `PaperExecutionLedgerEntry` likewise contains lineage, symbol, timestamp, action/reason, risk input fields, and `live_blocked`, but no side, quantity, entry/exit price, fee, funding, slippage, or realized PnL (`v2/backend/app/domain/paper_execution_ledger/record.py:90`).

2. Backtest output metrics: BLOCKED
   - `ReplayBacktestSummary` is count-only: total steps, allow/deny counts, mirrored reason counts, emitted timestamp, IDs, and `live_blocked` (`v2/backend/app/domain/replay_backtest_runner/summary.py:32`).
   - The service only aggregates those counts from steps (`v2/backend/app/services/replay_backtest_runner/service.py:186`).
   - Missing MVP metrics include gross PnL, net PnL, fees, funding, slippage, trade count, win/loss count, win rate, equity curve, max drawdown, per-symbol PnL, largest winner, largest loser, and attribution fields.

3. PnL and drawdown calculation: BLOCKED
   - No replay/backtest PnL or drawdown calculator exists in the runner service. `assemble_replay_backtest_step` derives a replay step from a paper ledger entry (`v2/backend/app/services/replay_backtest_runner/service.py:30`), and `assemble_replay_backtest_summary` derives count totals (`v2/backend/app/services/replay_backtest_runner/service.py:131`).
   - Existing historical replay wiring tests explicitly forbid PnL/market fields such as `pnl`, `realized_pnl`, `quantity`, `price`, `fees`, `slippage`, and `funding` on emitted records (`v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:33`, `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:157`).

4. Historical PnL comparison: BLOCKED
   - The committed historical audit marker is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY` (`claude_worklog/historical_pnl_audit/10_GO_NO_GO.md:1`).
   - The Binance read-only pull summary reports `income_rows: 0`, `trade_rows: 0`, and `order_rows: 0` with `BINANCE_PULL_NOT_REQUESTED` (`claude_worklog/historical_pnl_audit/02_BINANCE_READONLY_PULL_SUMMARY.md:7`).
   - Realized PnL by day, PnL by symbol, and fees/funding/commission tables contain only `NO_DATA` rows (`claude_worklog/historical_pnl_audit/03_30D_REALIZED_PNL_BY_DAY.md:5`, `claude_worklog/historical_pnl_audit/04_30D_PNL_BY_SYMBOL.md:5`, `claude_worklog/historical_pnl_audit/05_30D_FEES_FUNDING_COMMISSION.md:5`).
   - The proof module uses deterministic fixture strings and explicitly labels the mode `offline_deterministic_historical_fixture`; it also states realized PnL values are fixture values for operator workflow validation (`v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:191`, `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:241`).

5. Large winner/loser attribution: BLOCKED
   - The historical large winner/loser audit contains only `NO_DATA` for largest losers and winners (`claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md:6`, `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md:11`).
   - The proof module has deterministic fixture rows for preserved winners and reduced/rejected losses, but these are not calculated from populated trade/fill rows and are not produced by the replay backtest runner (`v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:80`, `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:180`).

Concrete blockers:

1. No replay economic input contract exists for fills/trades or equity points.
2. No replay output contract contains PnL, fees, funding, slippage, drawdown, win/loss, equity curve, or per-symbol attribution metrics.
3. No deterministic PnL/drawdown calculation service exists under the replay/backtest runner.
4. Current tests intentionally guard the historical replay wiring against PnL/market fields.
5. Historical PnL audit artifacts are partial/local-only and contain `NO_DATA`, so historical comparison and large winner/loser attribution cannot be validated from committed data.

Proposed non-live autofix tasks:

1. Add pure offline value objects for replay economic inputs, e.g. `ReplayBacktestFillInput` or `ReplayBacktestTradeInput`, with symbol, side, quantity, entry/exit or fill price, timestamp, commission, funding, slippage, source evidence pointer, lineage IDs, and mandatory `live_blocked=True`.
2. Add a pure metrics value object, e.g. `ReplayBacktestMetrics`, with gross/net PnL, fees, funding, slippage, trade count, win/loss count, win rate, largest winner, largest loser, equity points, peak/trough equity, max drawdown, ending equity, and per-symbol attribution.
3. Implement an in-memory deterministic metrics assembler using `Decimal` or integer minor units. It must consume only supplied local fixtures/audit rows and must not call Redis, exchanges, HTTP clients, order placement/cancelation, leverage/margin, service restart, deployment, or live-trading enablement surfaces.
4. Extend tests so the current lineage/count summary remains intact while the new metrics layer requires financial fields and verifies PnL, fee/funding subtraction, equity curve ordering, and max drawdown on small static fixtures.
5. Update historical comparison handling to emit an explicit blocked status when committed audit tables contain `NO_DATA`, instead of treating deterministic fixture PnL as a validated historical comparison.
6. Add attribution tests tying largest winners and losers to symbol, side, quantity, PnL components, paper trade ID, risk decision ID, decision ID, prediction ID, feature snapshot ID, and source evidence pointer, including the LAB hedge-unwind loser scenario.

Decision: `CODEX_PARALLEL_REVIEW_BLOCKED`
