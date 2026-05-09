# Codex Parallel Review: Replay Backtest Runner MVP

Review timestamp: 2026-05-09 20:43:55 local request context
Mode: read-only parallel review, report artifacts only
Decision: BLOCKED

## Scope Reviewed

- `v2/backend/app/domain/replay_backtest_runner/`
- `v2/backend/app/services/replay_backtest_runner/service.py`
- `v2/backend/app/composition/replay_backtest_runner/runtime.py`
- `v2/backend/tests/unit/domain/replay_backtest_runner/`
- `v2/backend/tests/unit/services/replay_backtest_runner/`
- `v2/backend/tests/unit/composition/replay_backtest_runner/`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/`
- `claude_worklog/historical_pnl_audit/`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`

## Blockers

1. Replay/backtest output metrics do not include PnL, drawdown, fees, funding, equity curve, win/loss attribution, or historical comparison metrics.

   Evidence:
   - `v2/backend/app/domain/replay_backtest_runner/summary.py:32` defines `ReplayBacktestSummary` with count-only fields.
   - `v2/backend/app/services/replay_backtest_runner/service.py:186` through `v2/backend/app/services/replay_backtest_runner/service.py:225` only aggregates action and reason counts.
   - `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/02_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_SPEC.md:5` explicitly says this package does not compute PnL, quantity, price, fees, or slippage.

   Impact:
   - The current runner cannot satisfy the review checks for backtest output metrics or PnL/drawdown calculation.

2. Replay input contracts do not contain enough data to compute a replay backtest result.

   Evidence:
   - `v2/backend/app/services/replay_backtest_runner/service.py:30` accepts only `paper_ledger_entry`, `replay_run`, and `now_ms_clock` for each step.
   - `v2/backend/app/services/replay_backtest_runner/service.py:112` through `v2/backend/app/services/replay_backtest_runner/service.py:128` copies lineage/action fields into a step; no fill price, side quantity, mark/close price, commission, funding, slippage, or realized PnL input exists.
   - `v2/backend/app/services/replay_backtest_runner/service.py:63` only enforces `step_ts_ms >= run_started_ts_ms`; there is no `step_ts_ms <= run_ended_ts_ms` window guard.

   Impact:
   - The runner can mirror paper ledger decisions, but it cannot replay market outcomes or validate that steps belong inside the declared run window.

3. Historical PnL comparison is not backed by real historical PnL data in the committed audit artifacts.

   Evidence:
   - `claude_worklog/historical_pnl_audit/03_30D_REALIZED_PNL_BY_DAY.md:5` contains `NO_DATA`.
   - `claude_worklog/historical_pnl_audit/04_30D_PNL_BY_SYMBOL.md:10` contains `NO_DATA`.
   - `claude_worklog/historical_pnl_audit/05_30D_FEES_FUNDING_COMMISSION.md:15` contains `NO_DATA`.
   - `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md:1` is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.

   Impact:
   - The current evidence cannot support a meaningful historical PnL comparison gate.

4. Large winner/loser attribution is placeholder-only in the historical audit and fixture-only in the proof code.

   Evidence:
   - `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md:21` and `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md:26` contain `NO_DATA`.
   - `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:80` through `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:152` defines five deterministic local fixtures.
   - `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:241` through `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:245` states that credentials were unavailable and realized PnL values are fixture values.

   Impact:
   - The MVP cannot attribute large winners/losers against historical decisions beyond synthetic scenarios.

## Non-Live Autofix Tasks

1. Add a non-live replay metrics input contract.
   - Introduce frozen value objects for replay fills/events with `trade_id`, `symbol`, `side`, `quantity`, `entry_price`, `exit_price` or mark price, `commission`, `funding`, `slippage`, `realized_pnl`, and `event_ts_ms`.
   - Reject live adapters, Redis writes, order placement, and exchange mutation by construction.
   - Enforce `run_started_ts_ms <= event_ts_ms <= run_ended_ts_ms`.

2. Extend `ReplayBacktestSummary` or add a dedicated metrics summary.
   - Include gross PnL, net PnL, fees, funding, slippage, win count, loss count, largest winner, largest loser, max drawdown, ending equity, and per-symbol attribution.
   - Use `Decimal` or integer minor units for money values instead of float.
   - Keep lineage fields linking each metric row to paper trade, risk decision, decision, prediction, and feature snapshot ids.

3. Add deterministic unit tests for PnL and drawdown.
   - Cover long winner, short winner, long loser, short loser, fee/funding drag, zero-trade summary, equity high-water mark drawdown, and malformed money inputs.
   - Add tests proving no Redis, HTTP, exchange adapter, scheduler, or live execution import occurs.

4. Replace placeholder historical audit fixtures with committed non-secret local fixture artifacts.
   - Add sanitized CSV/JSON fixture files under the test/proof fixture tree, not live account pulls.
   - Generate day, symbol, fee/funding, and large winner/loser summaries from those files.
   - Update the historical audit marker only after fixture-backed summaries are reproducible locally.

5. Add large winner/loser attribution tests.
   - Attribute each top winner/loser to symbol, direction, reason code, prediction id, feature snapshot id, risk decision id, paper trade id, and PnL components.
   - Include LAB hedge unwind residual exposure as a deterministic loser scenario.

## Verification

No test suite was run. This was a read-only source and artifact review, followed only by writing the two requested Codex parallel review files.
