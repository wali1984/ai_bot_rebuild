# Codex Parallel Review: Replay Backtest Runner MVP

Review timestamp: 2026-05-12 17:55:51 local request context
Mode: read-only parallel review, report artifacts only
Decision: BLOCKED

## Scope Reviewed

- `v2/backend/app/domain/replay_backtest_runner/`
- `v2/backend/app/services/replay_backtest_runner/`
- `v2/backend/app/composition/replay_backtest_runner/`
- `v2/backend/tests/unit/domain/replay_backtest_runner/`
- `v2/backend/tests/unit/services/replay_backtest_runner/`
- `v2/backend/tests/unit/composition/replay_backtest_runner/`
- `v2/backend/tests/unit/historical_pnl_replay_wiring/`
- `v2/backend/tests/unit/decision_explainability_replay_backtest_projection/`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/`
- `claude_worklog/historical_pnl_audit/`

## Verdict

BLOCKED for Replay Backtest Runner MVP readiness.

The current replay/backtest runner is a pure non-live mirror assembler over paper-ledger decisions. It validates lineage, run ids, symbols, timestamps, allow/deny actions, and reason-count partitions. It does not define replay inputs or outputs capable of calculating PnL, drawdown, historical PnL comparison, or large winner/loser attribution.

## Concrete Blockers

1. Backtest output metrics are count-only.

   Evidence:
   - `v2/backend/app/domain/replay_backtest_runner/summary.py:32` defines `ReplayBacktestSummary` with only ids, emitted timestamp, action counts, reason counts, and `live_blocked`.
   - `v2/backend/app/services/replay_backtest_runner/service.py:186` through `v2/backend/app/services/replay_backtest_runner/service.py:225` aggregates only total, allow/deny, and mirror reason counts.

   Required capability missing:
   - gross PnL, net PnL, fees, funding, slippage, win/loss counts, largest winner, largest loser, max drawdown, ending equity, and per-symbol attribution.

2. Replay input contracts do not carry market/fill data needed for PnL or drawdown.

   Evidence:
   - `v2/backend/app/services/replay_backtest_runner/service.py:112` through `v2/backend/app/services/replay_backtest_runner/service.py:128` copies paper trade lineage and action/reason fields into `ReplayBacktestStep`.
   - No reviewed replay runner domain/service/composition contract carries side, quantity, entry price, exit/mark price, commission, funding, slippage, realized PnL, equity, or balance.
   - `v2/backend/app/services/replay_backtest_runner/service.py:63` through `v2/backend/app/services/replay_backtest_runner/service.py:67` enforces `now_ms >= run_started_ts_ms`, but there is no `now_ms <= run_ended_ts_ms` step/window guard.

   Required capability missing:
   - deterministic offline fill/market event inputs with enough information to calculate net realized PnL and an equity curve inside the declared run window.

3. Historical PnL comparison evidence remains partial/no-data.

   Evidence:
   - `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md:1` is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.
   - `claude_worklog/historical_pnl_audit/01_DATA_SOURCE_STATUS.md:5` through `claude_worklog/historical_pnl_audit/01_DATA_SOURCE_STATUS.md:11` reports a 30-day request context but no Binance pull, no read-only credential env vars, and no requested trade/order symbols.
   - `claude_worklog/historical_pnl_audit/03_30D_REALIZED_PNL_BY_DAY.md:3` through `claude_worklog/historical_pnl_audit/03_30D_REALIZED_PNL_BY_DAY.md:5`, `04_30D_PNL_BY_SYMBOL.md:3` through `04_30D_PNL_BY_SYMBOL.md:5`, and `05_30D_FEES_FUNDING_COMMISSION.md:3` through `05_30D_FEES_FUNDING_COMMISSION.md:5` contain only `NO_DATA`.

   Required capability missing:
   - reproducible sanitized historical realized PnL fixtures or read-only pulled evidence that can be compared against replay/backtest outputs.

4. Large winner/loser attribution is label-only, not PnL-backed.

   Evidence:
   - `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md:3` through `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md:11` reports `NO_DATA` for largest losers and winners.
   - `v2/backend/tests/unit/historical_pnl_replay_wiring/fixtures.py:71` through `v2/backend/tests/unit/historical_pnl_replay_wiring/fixtures.py:120` creates scenario names for BTC/ETH winners, LAB loser, and SOL held, but those fixtures contain lineage and risk decisions only.
   - `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:157` through `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:162` explicitly asserts that replay records do not introduce PnL, size, price, fees, slippage, funding, or related market fields.
   - `v2/backend/tests/unit/decision_explainability_replay_backtest_projection/test_decision_explainability_replay_backtest_projection.py:266` through `v2/backend/tests/unit/decision_explainability_replay_backtest_projection/test_decision_explainability_replay_backtest_projection.py:332` forbids PnL, quantity, price, fee, funding, confidence, feature freshness, and related attribution fields in that projection harness.

   Required capability missing:
   - top winner/loser records tied to PnL components and decision lineage: symbol, side, quantity, net/gross PnL, fees/funding/slippage, prediction id, decision id, risk decision id, feature snapshot id, confidence/freshness where available, and scenario attribution.

## Non-Live Autofix Tasks

1. Add a pure offline replay fill/market-event contract.
   - Include run id, event id, symbol, side, quantity, entry price, exit/mark price, commission, funding, slippage, realized PnL, event timestamp, and lineage ids.
   - Enforce `run_started_ts_ms <= event_ts_ms <= run_ended_ts_ms`.
   - Keep it offline-only: no Redis, exchange adapters, HTTP, schedulers, order placement, or live execution imports.

2. Add deterministic money/PnL and drawdown domain logic.
   - Use `Decimal` or integer minor units, not floats.
   - Compute gross PnL, net PnL, fee/funding/slippage totals, equity curve, max drawdown, win/loss counts, largest winner, largest loser, and per-symbol metrics.
   - Add tests for long winner, short winner, long loser, short loser, fee/funding drag, zero-trade summaries, high-water-mark drawdown, malformed money values, and run-window rejection.

3. Extend replay/backtest summary outputs.
   - Keep existing allow/deny reason counts.
   - Add a separate metrics summary or versioned summary contract so existing mirror-count consumers do not silently receive incompatible fields.
   - Preserve lineage back to paper trade id, risk decision id, decision id, prediction id, and feature snapshot id.

4. Replace no-data historical audit placeholders with sanitized local fixtures.
   - Commit non-secret fixture inputs for realized PnL by day, PnL by symbol, fees/funding/commission, and large winners/losers.
   - Generate the audit markdown tables from those fixtures in a deterministic non-live proof/test path.
   - Keep the historical audit marker blocked/partial until the summaries are reproducible from committed evidence.

5. Add large winner/loser attribution checks.
   - Attribute top winners/losers to PnL components, symbol, side, risk/orchestrator reason, confidence/freshness fields when available, and lineage ids.
   - Include the LAB hedge-unwind/residual-exposure loser pattern from `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md:5` through `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md:11`.

## Verification

- Ran: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider v2/backend/tests/unit/domain/replay_backtest_runner v2/backend/tests/unit/services/replay_backtest_runner v2/backend/tests/unit/composition/replay_backtest_runner v2/backend/tests/unit/historical_pnl_replay_wiring v2/backend/tests/unit/decision_explainability_replay_backtest_projection -q`
- Result: `149 passed in 0.54s`
- Ran source/evidence scans for PnL, drawdown, winner/loser, fee/funding, price, quantity, and related attribution fields across the replay runner and relevant tests.

## Safety Notes

- No writes were made outside the two requested Codex parallel review artifacts.
- No Redis commands were run.
- No live services were restarted.
- No orders, leverage, margin, live trading, or deployment actions were performed.
- Pre-existing modified file observed and not touched: `claude_worklog/historical_pnl_audit/01_DATA_SOURCE_STATUS.md`.
