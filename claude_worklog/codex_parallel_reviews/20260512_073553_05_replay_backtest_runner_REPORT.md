# Codex Parallel Review: Replay Backtest Runner MVP

Review status: BLOCKED

## Scope inspected

- `v2/backend/app/domain/replay_backtest_runner/`
- `v2/backend/app/services/replay_backtest_runner/`
- `v2/backend/app/composition/replay_backtest_runner/`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`
- `v2/backend/tests/unit/domain/replay_backtest_runner/`
- `v2/backend/tests/unit/services/replay_backtest_runner/`
- `v2/backend/tests/unit/composition/replay_backtest_runner/`
- `v2/backend/tests/unit/historical_pnl_replay_wiring/`
- `v2/backend/tests/unit/decision_explainability_replay_backtest_projection/`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/`
- `claude_worklog/historical_pnl_audit/`

No live services, Redis writes/deletes, order placement, leverage/margin changes, deployments, or live-trading toggles were performed.

## Findings

### BLOCKER 1: replay/backtest output metrics are count-only, not backtest metrics

`ReplayBacktestSummary` exposes only run IDs, emitted timestamp, action counts, reason counts, and `live_blocked` (`v2/backend/app/domain/replay_backtest_runner/summary.py:32`). The assembler summary likewise aggregates only `total_steps_count`, allow/deny counts, and mirror-reason counts (`v2/backend/app/services/replay_backtest_runner/service.py:186`).

The review topic requires backtest output metrics, PnL/drawdown calculation, historical PnL comparison, and large winner/loser attribution. None of these are represented in the replay runner summary contract. There is no realized PnL, net PnL, fee/funding drag, equity curve, peak/trough, max drawdown, win/loss count, largest winner, largest loser, or attribution payload in the runner domain/service/composition surface.

### BLOCKER 2: PnL and drawdown calculation are absent by design in Phase 2I.A-C

The Phase 2I specs explicitly scoped the runner as a pure mirror/count assembler and excluded PnL, quantity, price, fees, slippage, and risk-adjusted returns. The implemented code follows that scope. This is acceptable for the narrow Phase 2I assembler milestone, but it is insufficient for "Replay Backtest Runner MVP" as reviewed here.

The historical replay wiring tests reinforce the gap by treating market/PnL fields as disallowed fields: `pnl`, `realized_pnl`, `size`, `quantity`, `price`, `fees`, `slippage`, and `funding` are explicitly forbidden in the harness records (`v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:33`). That prevents the current harness from proving the requested PnL/drawdown behavior.

### BLOCKER 3: historical PnL comparison is fixture-only and not connected to replay runner outputs

`historical_30d_replay_and_paper_proof.py` contains deterministic local fixture rows with hard-coded legacy/v2 PnL strings (`v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:80`) and computes fixture sums (`v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:187`). This proves an offline dashboard/proof shape, but it does not consume `ReplayBacktestStep` or `ReplayBacktestSummary` and does not validate runner-calculated PnL.

The committed historical audit currently has no usable 30-day PnL source data: realized PnL by day, PnL by symbol, fees/funding/commission, and large winners/losers all contain only `NO_DATA` rows (`claude_worklog/historical_pnl_audit/03_30D_REALIZED_PNL_BY_DAY.md:5`, `04_30D_PNL_BY_SYMBOL.md:10`, `05_30D_FEES_FUNDING_COMMISSION.md:15`, `06_LARGE_WINNERS_AND_LOSERS.md:21`). `10_GO_NO_GO.md` is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`, so a historical comparison can only be fixture/local partial evidence at this point.

### BLOCKER 4: large winner/loser attribution is not available from runner output

The runner step record carries lineage IDs and mirrored paper-ledger action/reason codes (`v2/backend/app/services/replay_backtest_runner/service.py:113`), which is useful for joining back to prediction/risk evidence. It does not carry trade outcome, PnL contribution, confidence, feature freshness flags, feature attribution, regime context, or winner/loser ranking.

The projection harness intentionally allows only lineage/count fields and excludes attribution-like fields including confidence, feature freshness, regime context, model/checkpoint version, risk check lists, and audit timeline (`v2/backend/tests/unit/decision_explainability_replay_backtest_projection/test_decision_explainability_replay_backtest_projection.py:69`). Therefore large winner/loser attribution cannot be verified from the current runner MVP surface.

## Passing observations

- Replay input contracts are strict for the narrow current contract: run IDs, symbols, timestamps, live-blocked invariants, paper-ledger entry type, replay run type, clock type/value, and symbol matching are validated.
- Step assembly preserves core lineage: paper trade, risk decision, orchestrator decision, prediction, feature snapshot, and symbol.
- Summary count partitions are enforced by domain invariants and built by the service.
- The runner is non-live and pure at the inspected layers; no Redis/exchange/order path was found in the replay runner domain/service/composition surface.

## Proposed non-live autofix tasks

1. Add an offline-only `ReplayBacktestMetricInput` / `ReplayBacktestMetricSummary` contract under the replay backtest runner domain or a sibling metrics package. Include realized gross PnL, fees, funding, net PnL, cumulative equity, max drawdown, win/loss counts, largest winner/loser, and per-symbol/day partitions. Keep `live_blocked=True` and no adapters, Redis, exchange clients, or live order APIs.

2. Add a pure metrics assembler that consumes deterministic replay trade outcome fixtures or paper-ledger outcome rows and computes net PnL and drawdown using Decimal-safe arithmetic. Add tests for positive/negative trades, zero-trade runs, fees/funding drag, peak-to-trough drawdown, partition sums, and bool/int rejection.

3. Wire historical PnL comparison through offline fixture/audit inputs into the metrics summary. The proof should compare legacy realized PnL vs V2 paper/replay net PnL from the same summary object instead of hard-coded strings only.

4. Add large winner/loser attribution envelopes that join runner lineage to non-live prediction/risk evidence: symbol, side, confidence, feature snapshot ID, freshness flags, reason codes, legacy evidence pointer, net PnL, and rank. Keep joins explicit and fixture-backed.

5. Replace or supplement the current historical replay wiring tests that forbid PnL fields with a metrics-specific test suite. Keep the existing pure-lineage tests, but do not use them as evidence that backtest metrics are complete.

6. Add a final non-live integration harness that emits one aggregate `ReplayBacktestMetricSummary` and asserts historical comparison totals, max drawdown, largest winner, largest loser, and attribution rows without writing Redis or calling external services.

## Verdict

The inspected replay runner is ready only as a pure lineage/count assembler. It is not ready as a Replay Backtest Runner MVP for the requested review criteria because PnL, drawdown, historical PnL comparison, and large winner/loser attribution are missing from the runner output contract and tests.
