# Codex Parallel Review: Replay Backtest Runner MVP

Review timestamp: 2026-05-09 14:50:09
Mode: read-only parallel review, except for this requested report artifact.

## Verdict

CODEX_PARALLEL_REVIEW_BLOCKED

The current replay backtest runner is not ready for the requested MVP checks. It provides a non-live, pure value-object and assembler surface that mirrors paper ledger allow/deny records into replay steps and action-count summaries, but it does not implement replay input ingestion, backtest PnL metrics, drawdown, historical PnL comparison, or large winner/loser attribution.

## Inputs Inspected

- `v2/backend/app/domain/replay_backtest_runner/`
- `v2/backend/app/services/replay_backtest_runner/`
- `v2/backend/app/composition/replay_backtest_runner/`
- `v2/backend/app/api/v1/replay.py`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`
- `v2/backend/tests/unit/domain/replay_backtest_runner/`
- `v2/backend/tests/unit/services/replay_backtest_runner/`
- `v2/backend/tests/unit/composition/replay_backtest_runner/`
- `v2/backend/tests/unit/historical_pnl_replay_wiring/`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/`
- `claude_worklog/historical_pnl_audit/`
- `claude_worklog/final_readiness/historical_30d_replay_and_paper_proof/latest/`

No live services were restarted, no Redis writes/deletes were performed, and no live trading operations were touched.

## Findings

### Blocker 1: backtest output metrics are only replay action counts

`ReplayBacktestSummary` contains count fields only: total steps, allow/deny step counts, and mirror reason counts. It has no realized PnL, net PnL, gross PnL, fee/funding/commission, return, equity curve, win rate, payoff, drawdown, exposure, or per-symbol metrics.

Evidence:
- `v2/backend/app/domain/replay_backtest_runner/summary.py:32` defines the summary dataclass with only count fields.
- `v2/backend/app/services/replay_backtest_runner/service.py:186` through `v2/backend/app/services/replay_backtest_runner/service.py:225` aggregates only action/reason counts into `ReplayBacktestSummary`.
- The 2I specs explicitly say the milestone does not compute PnL, quantity, price, fees, slippage, or risk-adjusted return.

Impact: the runner cannot satisfy the requested backtest output metrics, PnL/drawdown calculation, or historical PnL comparison checks.

### Blocker 2: no PnL or drawdown calculation exists in the runner path

The runner maps a `PaperExecutionLedgerEntry` to a `ReplayBacktestStep` and copies lineage/action fields. There is no market input, fill input, position accounting, fee/funding input, equity curve, or drawdown reducer.

Evidence:
- `v2/backend/app/services/replay_backtest_runner/service.py:30` accepts only `paper_ledger_entry`, `replay_run`, and `now_ms_clock`.
- `v2/backend/app/services/replay_backtest_runner/service.py:112` through `v2/backend/app/services/replay_backtest_runner/service.py:128` constructs a step from paper ledger lineage and reason fields only.
- `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:157` asserts the harness does not introduce PnL, size, price, fees, funding, or similar market fields.

Impact: even a syntactically valid replay run cannot produce the MVP financial metrics needed to compare strategy behavior.

### Blocker 3: `/replay` remains scaffold-only and is not wired to the runner

The FastAPI route file exposes only route metadata via an OPTIONS shim. There is no endpoint for submitting replay inputs, no persistence or artifact read path, and no runner invocation.

Evidence:
- `v2/backend/app/api/v1/replay.py:1` describes the module as scaffold-only.
- `v2/backend/app/api/v1/replay.py:14` through `v2/backend/app/api/v1/replay.py:25` returns static route metadata only.
- `v2/backend/app/services/replay_runner.py` is still a placeholder.

Impact: replay input contracts are not available as an API or runner contract beyond manually constructed domain/service objects.

### Blocker 4: historical PnL audit data is partial local-only and contains no real PnL rows

The historical audit tables for realized PnL by day, PnL by symbol, fees/funding/commission, and large winners/losers all contain `NO_DATA`. The audit marker is partial local-only.

Evidence:
- `claude_worklog/historical_pnl_audit/03_30D_REALIZED_PNL_BY_DAY.md:3` through line 5 contains `NO_DATA`.
- `claude_worklog/historical_pnl_audit/04_30D_PNL_BY_SYMBOL.md:3` through line 5 contains `NO_DATA`.
- `claude_worklog/historical_pnl_audit/05_30D_FEES_FUNDING_COMMISSION.md:3` through line 5 contains `NO_DATA`.
- `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md:3` through line 11 contains `NO_DATA` for both losers and winners.
- `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md:1` is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.

Impact: the runner cannot be validated against actual historical PnL, actual fees/funding, or actual large winner/loser attribution from the inspected audit inputs.

### Blocker 5: historical proof values are deterministic fixtures, not runner-derived backtest results

There is a later historical proof generator, but it uses hard-coded fixture trades and explicitly states that realized PnL values are fixture values for operator workflow validation. It is not wired into the replay backtest runner implementation.

Evidence:
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:80` through `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:152` defines fixed fixture scenarios and fixed PnL strings.
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:187` through line 208 sums fixture PnL values into summary fields.
- `claude_worklog/final_readiness/historical_30d_replay_and_paper_proof/latest/limitations_and_data_gaps.md:3` through line 6 says account-history credentials were unavailable, proof uses deterministic local fixtures, and realized PnL values are fixture values.

Impact: the deterministic proof can support workflow/demo evidence, but it does not prove that the replay backtest runner computes PnL/drawdown or attributes actual historical winners/losers.

## Contract Checks

- Replay input contracts: partially present at value-object/service level. `ReplayBacktestRun`, `ReplayBacktestStep`, and `ReplayBacktestSummary` enforce identifier, symbol, timestamp, live-blocked, and action/reason partition invariants. Missing: API/input schema for replay datasets, trade/fill/market-data input contracts, and historical PnL fixture ingestion into the runner.
- Backtest output metrics: blocked. Only allow/deny/reason counts are emitted.
- PnL/drawdown calculation: blocked. No financial accounting surface exists in the runner path.
- Historical PnL comparison: blocked. Historical audit has `NO_DATA`; deterministic proof is fixture-based and separate.
- Large winner/loser attribution: blocked. Audit large winner/loser tables are `NO_DATA`, and runner steps do not carry PnL or attribution dimensions beyond lineage IDs and mirror reasons.

## Proposed Non-Live Autofix Tasks

1. Add a pure, non-live backtest metrics domain package that models trade/fill inputs, fees/funding, realized/net PnL, equity curve points, max drawdown, per-symbol totals, and winner/loser attribution. Keep it free of Redis, exchange clients, order placement, schedulers, and live adapters.
2. Extend the replay backtest service with a pure metrics assembler that consumes immutable replay steps plus explicit offline fill/price/PnL inputs and returns a metrics summary. Do not read exchange APIs or Redis inside the assembler.
3. Add deterministic unit fixtures for PnL/drawdown math, including long/short winners, losers, flat/denied steps, fees/funding drag, max drawdown, and large winner/loser ranking.
4. Add a historical-audit adapter that reads committed local audit artifacts only and refuses `NO_DATA` as a ready state for historical PnL comparison.
5. Wire the deterministic historical proof to the same metrics types or clearly rename it as workflow-only evidence so it cannot be mistaken for runner-derived PnL proof.
6. Add API schemas or CLI-only contracts for offline replay input bundles after the pure metrics layer is covered, with live-mode and exchange-operation guards preserved.

## Final Status

Blocked until the non-live runner can emit financial metrics and compare them to non-empty historical PnL evidence, or until the MVP scope is explicitly narrowed to action-count replay summaries only.
