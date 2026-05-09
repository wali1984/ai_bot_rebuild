# Codex Parallel Review: Replay Backtest Runner MVP

Review timestamp: 2026-05-09T09:37:07-04:00

Scope inspected:
- `v2/backend/app/domain/replay_backtest_runner/`
- `v2/backend/app/services/replay_backtest_runner/`
- `v2/backend/app/composition/replay_backtest_runner/`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`
- `v2/backend/tests/unit/domain/replay_backtest_runner/`
- `v2/backend/tests/unit/services/replay_backtest_runner/`
- `v2/backend/tests/unit/composition/replay_backtest_runner/`
- `v2/backend/tests/unit/historical_pnl_replay_wiring/`
- `v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/`
- `claude_worklog/historical_pnl_audit/`

## Decision

CODEX_PARALLEL_REVIEW_BLOCKED

The replay/backtest runner currently implements a pure lineage/counting surface: `ReplayBacktestRun`, `ReplayBacktestStep`, `ReplayBacktestSummary`, service assemblers, and a composition binder. That is consistent with the Phase 2I.A/2I.B/2I.C specs, but it is not sufficient for the requested MVP review checks: PnL/drawdown calculation, historical PnL comparison, and large winner/loser attribution are absent or fixture-only.

No live service, Redis, order, leverage, margin, deployment, or live-trading action was performed. I did not run tests because this was read-only review mode and pytest can write cache files.

## Blockers

### 1. Backtest output metrics are counts only, not financial metrics

Evidence:
- `v2/backend/app/domain/replay_backtest_runner/summary.py` defines only ids, timestamps, total step counts, allow/deny counts, mirror reason counts, and `live_blocked`.
- `v2/backend/app/services/replay_backtest_runner/service.py` computes only those count partitions in `assemble_replay_backtest_summary`.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/02_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_SPEC.md`, `10_PHASE_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_SPEC.md`, and `18_PHASE_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_SPEC.md` explicitly exclude PnL, quantity, price, fees, slippage, position sizing, and risk-adjusted return.

Impact:
- The runner cannot report gross PnL, net PnL, fees/funding/commission drag, realized/unrealized PnL, win/loss totals, equity curve, or max drawdown.

Proposed non-live autofix task:
- Add a pure `backtest_accounting` domain/service that accepts typed non-live fill or paper outcome fixtures and returns frozen metrics: gross_pnl, net_pnl, fee_total, funding_total, commission_total, equity_curve, max_drawdown, win_count, loss_count, largest_winner, largest_loser, and per-symbol aggregates. Keep it fixture/local-input only with no Redis, exchange, API, or execution adapter wiring.

### 2. Replay input contracts lack the data needed to calculate PnL or drawdown

Evidence:
- `ReplayBacktestStep` carries lineage ids, symbol, timestamp, mirrored action/reason, input paper action/reason, and `live_blocked`; it has no side, quantity, price, fee, funding, close/open state, or equity field.
- The assembler derives a replay step from `PaperExecutionLedgerEntry`, but the ledger entry is also a decision mirror rather than a fill/position/outcome record.
- `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py` explicitly asserts replay wiring records do not introduce `pnl`, `realized_pnl`, `size`, `quantity`, `price`, `fees`, `slippage`, `funding`, `oi`, `liquidation`, `orderbook`, `hedge_state`, `residual_exposure`, or `squeeze_risk` fields.

Impact:
- Any PnL or drawdown result would have to be invented outside the replay runner contract, so the MVP cannot be trusted as a backtest runner yet.

Proposed non-live autofix task:
- Add a separate non-live `BacktestInputEvent` or `BacktestFillEvent` value object with strict fields for event type, side, quantity, price, fee, funding, realized_pnl when precomputed, timestamp, symbol, and lineage ids. Use `Decimal` or validated decimal strings in tests to avoid float drift.

### 3. Historical PnL comparison is blocked by partial/no-data audit artifacts

Evidence:
- `claude_worklog/historical_pnl_audit/03_30D_REALIZED_PNL_BY_DAY.md` contains `NO_DATA`.
- `claude_worklog/historical_pnl_audit/04_30D_PNL_BY_SYMBOL.md` contains `NO_DATA`.
- `claude_worklog/historical_pnl_audit/05_30D_FEES_FUNDING_COMMISSION.md` contains `NO_DATA`.
- `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md` contains `NO_DATA`.
- `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md` is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.

Impact:
- There is no authoritative historical realized-PnL baseline for comparing replay/backtest output to actual 30-day account results.

Proposed non-live autofix task:
- Add a local-only historical comparison loader that consumes sanitized committed audit tables and blocks with an explicit status when they contain `NO_DATA`. Add fixture tables with known day/symbol/fee/winner/loser values for deterministic acceptance tests; do not perform live Binance/API pulling in the autofix.

### 4. Large winner/loser attribution is fixture-only and not connected to runner outputs

Evidence:
- The committed large winner/loser audit file has only `NO_DATA`.
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py` hardcodes deterministic fixture rows such as `day03_btc_winner_preserved`, `day21_lab_hedge_unwind_blocked`, and `day26_bnb_winner_preserved`.
- Those proof rows include `legacy_realized_pnl` and `v2_paper_pnl`, but they are not produced by the replay runner and are labeled as fixture values in the proof limitations.
- Current replay steps preserve lineage ids, but no realized outcome rank, PnL amount, trainer confidence attribution, feature freshness attribution, or largest-winner/largest-loser ranking is computed from runner output.

Impact:
- The system cannot explain which replayed decisions produced the largest wins/losses or tie those outcomes back to trainer confidence and feature freshness from actual historical evidence.

Proposed non-live autofix task:
- Add a pure attribution report service that joins non-live backtest outcome rows to lineage ids and emits largest winners/losers with symbol, side, pnl, fees, decision_id, prediction_id, feature_snapshot_id, risk_decision_id, confidence, freshness/staleness flags, and attribution reason.

### 5. Historical proof gives useful static dashboard artifacts but is not a replay/backtest runner

Evidence:
- `build_historical_30d_proof()` uses `deterministic_30d_fixtures()` and sums string fixture values via `_money()`.
- The proof limitations state that Binance account-history credentials were unavailable, the proof uses deterministic local fixtures plus committed audit markers, and realized PnL values are fixture values for operator workflow validation.
- The proof writes output artifacts, but it does not call `build_replay_backtest_runner`, `assemble_replay_backtest_step`, or `assemble_replay_backtest_summary`.

Impact:
- The proof can support operator workflow validation, but it does not validate that the replay/backtest runner computes correct PnL, drawdown, or attribution.

Proposed non-live autofix task:
- Wire a local fixture harness that runs replay decisions through the runner, passes resulting lineage into the new accounting service, and then generates the historical proof from computed non-live outputs rather than independent hardcoded PnL rows.

## Non-Blocker Notes

- The live-safety boundary is strong in the inspected replay runner code: the Phase 2I specs and implementation avoid Redis, exchange clients, FastAPI registration, live order terms, persistence, background work, and live trading enablement.
- The current runner contracts are useful as a lineage-preserving mirror of paper execution ledger decisions, but they should be treated as a precursor to accounting, not as the accounting layer itself.

## Gate

Blocked until non-live accounting inputs, financial metric outputs, drawdown math, historical comparison fixtures, and large winner/loser attribution are implemented and tested without live side effects.
