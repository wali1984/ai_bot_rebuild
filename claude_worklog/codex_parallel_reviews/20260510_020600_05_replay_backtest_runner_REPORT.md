# Codex Parallel Review: Replay Backtest Runner MVP

Review timestamp: 2026-05-10 02:06:00 local request context
Mode: read-only parallel review, report artifacts only
Decision: BLOCKED

## Scope Reviewed

- `v2/backend/app/domain/replay_backtest_runner/`
- `v2/backend/app/services/replay_backtest_runner/service.py`
- `v2/backend/app/composition/replay_backtest_runner/runtime.py`
- `v2/backend/tests/unit/domain/replay_backtest_runner/`
- `v2/backend/tests/unit/services/replay_backtest_runner/`
- `v2/backend/tests/unit/composition/replay_backtest_runner/`
- `v2/backend/app/proof/non_live_operational_proof.py`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/`
- `claude_worklog/historical_pnl_audit/`

## Verdict

BLOCKED for Replay Backtest Runner MVP readiness.

The implemented replay/backtest runner is a non-live, pure mirror-record assembler over paper ledger entries. That is useful infrastructure, but it does not yet provide a replay input contract capable of PnL calculation, backtest result metrics, drawdown, historical PnL comparison, or real large winner/loser attribution.

## Findings

1. Backtest output metrics are count-only.

   Evidence:
   - `v2/backend/app/domain/replay_backtest_runner/summary.py:32` defines `ReplayBacktestSummary` with only timestamp, total count, allow/deny count, reason count, and `live_blocked`.
   - `v2/backend/app/services/replay_backtest_runner/service.py:186` through `v2/backend/app/services/replay_backtest_runner/service.py:225` only aggregates action and reason counts.
   - `v2/backend/app/proof/non_live_operational_proof.py:271` and `v2/backend/app/proof/non_live_operational_proof.py:272` expose `gross_paper_pnl` as a hard-coded string and `max_drawdown_placeholder`.

   Impact:
   - The runner cannot satisfy backtest output metric requirements for net/gross PnL, fees, funding, slippage, equity curve, win/loss counts, largest winner, largest loser, or max drawdown.

2. Replay input contracts do not carry enough market or fill data to calculate PnL/drawdown.

   Evidence:
   - `v2/backend/app/domain/replay_backtest_runner/run.py:31` through `v2/backend/app/domain/replay_backtest_runner/run.py:38` stores only run id, mode, symbol, start/end timestamps, and `live_blocked`.
   - `v2/backend/app/domain/replay_backtest_runner/step.py:70` through `v2/backend/app/domain/replay_backtest_runner/step.py:85` stores lineage ids, symbol, timestamp, action/reason mirrors, and `live_blocked`.
   - `v2/backend/app/services/replay_backtest_runner/service.py:112` through `v2/backend/app/services/replay_backtest_runner/service.py:128` copies paper ledger lineage/action fields into a replay step; it has no side, quantity, entry price, exit/mark price, commission, funding, slippage, realized PnL, or equity input.
   - `v2/backend/app/services/replay_backtest_runner/service.py:63` through `v2/backend/app/services/replay_backtest_runner/service.py:67` enforces `now_ms >= run_started_ts_ms`, but there is no `now_ms <= run_ended_ts_ms` guard.

   Impact:
   - The current contract can mirror decisions but cannot replay market outcomes or compute a drawdown curve inside the declared run window.

3. Historical PnL comparison remains partial/local-only and fixture-backed.

   Evidence:
   - `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md:1` is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.
   - `claude_worklog/historical_pnl_audit/01_DATA_SOURCE_STATUS.md` reports `binance_pull_requested: False`, missing Binance read-only credential env vars, and no requested trade/order-history symbols.
   - `claude_worklog/historical_pnl_audit/02_BINANCE_READONLY_PULL_SUMMARY.md` reports `income_rows: 0`, `trade_rows: 0`, `order_rows: 0`, and `BINANCE_PULL_NOT_REQUESTED`.
   - `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:241` through `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:245` explicitly states that account-history credentials were unavailable and realized PnL values are fixture values.

   Impact:
   - The current evidence cannot support a meaningful historical PnL comparison gate beyond deterministic workflow fixtures.

4. Large winner/loser attribution is not backed by real historical winner/loser rows.

   Evidence:
   - `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md:3` through `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md:11` contains `NO_DATA` for both largest losers and largest winners.
   - `claude_worklog/historical_pnl_audit/07_LEGACY_TRAINER_DECISION_EVIDENCE.md` reports `row_count: 0`.
   - `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:334` through `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:362` attributes deterministic fixture rows to lineage ids, confidence, reasons, and feature flags, but those rows are not derived from the historical audit's winner/loser tables.

   Impact:
   - The MVP cannot yet prove that large historical winners were preserved or large historical losers were blocked/reduced against actual historical decision evidence.

## Non-Live Autofix Tasks

1. Add a non-live replay market-event/fill contract.
   - Include run id, event id, symbol, side, quantity, entry price, exit or mark price, commission, funding, slippage, realized PnL, event timestamp, and lineage ids.
   - Enforce `run_started_ts_ms <= event_ts_ms <= run_ended_ts_ms`.
   - Keep it pure and offline: no Redis writes, no exchange adapters, no order placement, no live service imports.

2. Add a replay/backtest metrics summary.
   - Include gross PnL, net PnL, fees, funding, slippage, win count, loss count, largest winner, largest loser, max drawdown, ending equity, and per-symbol attribution.
   - Use `Decimal` or integer minor units for money values.
   - Preserve lineage back to paper trade id, risk decision id, decision id, prediction id, and feature snapshot id.

3. Add deterministic PnL and drawdown tests.
   - Cover long winner, short winner, long loser, short loser, fee/funding drag, zero-trade summary, high-water-mark drawdown, malformed money values, and timestamp window rejection.
   - Include import-safety tests proving no Redis, HTTP, exchange adapter, scheduler, or live execution dependency is loaded.

4. Replace placeholder historical audit inputs with sanitized local fixtures.
   - Commit non-secret JSON/CSV fixtures under the test/proof fixture tree.
   - Generate realized PnL by day, PnL by symbol, fees/funding/commission, and large winner/loser tables from those fixtures.
   - Keep the marker partial until those summaries are reproducible from committed fixture input.

5. Add large winner/loser attribution checks.
   - Attribute top winners/losers to symbol, side, quantity, PnL components, reason code, confidence, feature freshness, prediction id, decision id, risk decision id, and paper trade id.
   - Include the LAB hedge unwind residual-exposure case as a deterministic loser scenario.

## Verification

No test suite was run. This was a read-only source and artifact review, followed only by writing the two requested Codex parallel review files.
