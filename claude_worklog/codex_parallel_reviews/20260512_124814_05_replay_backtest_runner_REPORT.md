BEGIN_FILE: claude_worklog/codex_parallel_reviews/20260512_124814_05_replay_backtest_runner_REPORT.md
# Replay Backtest Runner MVP Parallel Review

Verdict: BLOCKED for Replay Backtest Runner MVP readiness under the requested checks.

Scope inspected:
- `v2/backend/app/domain/replay_backtest_runner`
- `v2/backend/app/services/replay_backtest_runner`
- `v2/backend/app/composition/replay_backtest_runner`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`
- `v2/backend/tests/unit/domain/replay_backtest_runner`
- `v2/backend/tests/unit/services/replay_backtest_runner`
- `v2/backend/tests/unit/composition/replay_backtest_runner`
- `v2/backend/tests/unit/historical_pnl_replay_wiring`
- `v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl`
- `claude_worklog/historical_pnl_audit`

## Passing findings

- Live side effects remain blocked in the reviewed runner path. `ReplayBacktestRun`, `ReplayBacktestStep`, and `ReplayBacktestSummary` all require `live_blocked=True`, and the assembler hard-codes `live_blocked=True` when constructing replay step and summary records.
- Replay input shape is deterministic for the current mirror-ledger layer. `assemble_replay_backtest_step` accepts only a validated `PaperExecutionLedgerEntry`, a validated `ReplayBacktestRun`, and an injected clock; it rejects symbol mismatches and derives `replay_step_id` from `paper_trade_id`.
- Summary count partitioning is covered. `ReplayBacktestSummary` validates total allow/deny counts and allow/deny reason-subpartition counts, and the service aggregates those counts from replay steps.
- The historical proof remains non-live and fixture-scoped. `historical_30d_replay_and_paper_proof.py` emits local artifacts only under allowlisted output prefixes and labels its data mode as `offline_deterministic_historical_fixture`.
- Large winner/loser fixture rows exist in the historical proof. The fixture includes two preserved winner rows and three reduced-or-rejected loser rows, including the LAB hedge-unwind case.

## Blockers

1. The replay/backtest runner does not implement backtest output metrics beyond mirror counts.
   - `v2/backend/app/domain/replay_backtest_runner/summary.py` only defines step counts and mirror reason counts. It has no fields for realized PnL, unrealized PnL, fees, funding, net PnL, equity curve, max drawdown, win rate, average winner/loser, largest winner, largest loser, or per-symbol attribution.
   - `v2/backend/app/services/replay_backtest_runner/service.py` only maps paper-ledger action/reason into replay-step action/reason and then counts those steps. It does not consume fills, prices, quantities, fees, funding, position state, or equity snapshots.

2. PnL and drawdown calculation are explicitly absent from the Phase 2I implementation contract.
   - The Phase 2I domain, service, and composition specs state that this milestone does not compute PnL, quantity, price, fees, slippage, or risk-adjusted return.
   - The current tests reinforce that absence: `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py` marks `pnl`, `realized_pnl`, `size`, `quantity`, `price`, `fees`, `slippage`, `funding`, and related market fields as disallowed for the wiring harness.
   - Because those fields are absent by design, the runner cannot validate requested PnL/drawdown correctness.

3. Historical PnL comparison is fixture-only, not a comparison against committed historical audit data.
   - `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py` uses hard-coded `HistoricalTradeFixture` rows for legacy and V2 PnL values.
   - The same proof labels its limitations: Binance account-history credentials were unavailable and realized PnL values are fixture values for operator workflow validation.
   - `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md` is only `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`, and `06_LARGE_WINNERS_AND_LOSERS.md` contains `NO_DATA` for both largest losers and largest winners.

4. Large winner/loser attribution is not grounded in actual audited winners/losers.
   - The historical proof attributes fixture rows by `reason`, `confidence`, lineage ids, and paper event type, but it does not link to real historical trade ids, fill ids, execution prices, sizes, fees, funding, or realized-income records.
   - The reviewed runner surface does not carry attribution fields needed to explain winner/loser size: entry/exit price, direction lifecycle, quantity, fee/funding components, holding interval, drawdown path, or model-vs-risk contribution.

5. Replay input contracts are too narrow for a Backtest Runner MVP with PnL/drawdown obligations.
   - Current replay steps are built from `PaperExecutionLedgerEntry`, which itself records lineage and allow/deny mirroring, not market execution data.
   - There is no typed offline backtest input contract for historical fills, candles/marks, funding, fee schedule, starting equity, position state, or mark-to-market cadence.

## Proposed non-live autofix tasks

1. Add a new offline-only backtest metrics domain under `v2/backend/app/domain/replay_backtest_metrics/` with frozen records for `BacktestFill`, `BacktestEquityPoint`, `BacktestTradeAttribution`, and `BacktestMetricsSummary`. Keep `live_blocked=True` required and forbid Redis/exchange imports.

2. Add a pure metrics assembler under `v2/backend/app/services/replay_backtest_metrics/` that accepts tuple-only deterministic inputs: fills, fees/funding adjustments, and mark/equity points. Compute gross/net realized PnL, cumulative PnL, max drawdown, win/loss counts, largest winner, largest loser, and per-symbol totals using Decimal or integer minor units.

3. Extend the non-live historical proof to load committed local audit artifacts when present and emit a `comparison_source` field distinguishing `historical_audit_data` from `deterministic_fixture`. Do not use exchange APIs, Redis, or live services.

4. Replace `NO_DATA` large winner/loser audit placeholders with a local fixture-backed attribution artifact if no real audit data is present. Include explicit `data_gap_reason` and keep GO/NO-GO blocked until real or approved fixture evidence exists.

5. Add unit tests for PnL/drawdown edge cases: flat zero-trade run, long win, short win, partial close, fee-only loser, funding adjustment, equity peak-to-trough drawdown, multi-symbol attribution, and largest winner/loser tie-breaking.

6. Add an integration-style non-live harness that connects replay mirror steps to offline metrics by lineage id without changing paper ledger records. This keeps Phase 2I mirror contracts stable while adding a separate metrics layer for backtest readiness.

## Review notes

- I did not run tests in this read-only review pass to avoid cache/artifact writes.
- No live services, Redis writes, Redis deletes, orders, leverage/margin changes, deployment, or live-trading toggles were used.
