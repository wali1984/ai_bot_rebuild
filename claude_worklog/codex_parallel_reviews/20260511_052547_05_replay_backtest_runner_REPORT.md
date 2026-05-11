# Codex Parallel Review: Replay Backtest Runner MVP

Review status: BLOCKED

Scope inspected:
- `v2/backend/app/domain/replay_backtest_runner/`
- `v2/backend/app/services/replay_backtest_runner/`
- `v2/backend/app/composition/replay_backtest_runner/`
- `v2/backend/app/api/v1/replay.py`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`
- `v2/backend/app/proof/non_live_operational_proof.py`
- `v2/backend/tests/unit/domain/replay_backtest_runner/`
- `v2/backend/tests/unit/services/replay_backtest_runner/`
- `v2/backend/tests/unit/composition/replay_backtest_runner/`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/`
- `claude_worklog/historical_pnl_audit/`

Safety constraints honored:
- Did not modify `/home/wali/Desktop/AI BOT`.
- Did not write Redis, delete Redis keys, restart services, place/cancel orders, change leverage/margin, enable live trading, or deploy.
- Did not run validation commands because this was requested as read-only review mode and pytest/compile can create cache artifacts. Only these review artifacts were written.

## Findings

### 1. Runner output metrics are count-only, not backtest financial metrics

`ReplayBacktestSummary` only contains step counts and mirror-reason partitions:
- `total_steps_count`
- `record_allow_steps_count`
- `record_deny_steps_count`
- per-reason allow/deny counts

Evidence:
- `v2/backend/app/domain/replay_backtest_runner/summary.py:33`
- `v2/backend/app/domain/replay_backtest_runner/summary.py:37`
- `v2/backend/app/domain/replay_backtest_runner/summary.py:90`
- `v2/backend/app/services/replay_backtest_runner/service.py:186`
- `v2/backend/app/services/replay_backtest_runner/service.py:213`

There are no output fields for gross PnL, net PnL, realized PnL, fees, funding, commission, equity curve, max drawdown, win rate, average win/loss, largest winner, largest loser, or symbol/day attribution.

Impact: the implemented runner cannot satisfy the review checks for backtest output metrics, PnL/drawdown calculation, historical PnL comparison, or large winner/loser attribution.

### 2. Replay input contract accepts paper ledger entries, not historical replay market/trade inputs

`assemble_replay_backtest_step` accepts a `PaperExecutionLedgerEntry`, a `ReplayBacktestRun`, and a clock. It mirrors paper ledger allow/deny reasons into replay steps. It does not accept entry/exit price, quantity, side, fee/funding rows, fill timestamps, mark-to-market series, or historical realized-PnL rows.

Evidence:
- `v2/backend/app/services/replay_backtest_runner/service.py:30`
- `v2/backend/app/services/replay_backtest_runner/service.py:32`
- `v2/backend/app/services/replay_backtest_runner/service.py:79`
- `v2/backend/app/services/replay_backtest_runner/service.py:112`

Impact: the current input contract is valid for a mirror-taxonomy assembler, but it is not sufficient for replay backtest PnL/drawdown calculation.

### 3. PnL/drawdown is explicitly out of scope in the Phase 2I runner specs

The Phase 2I domain, service, and composition specs state that this runner does not compute PnL, quantity, price, fees, slippage, position sizing, or risk-adjusted return.

Evidence:
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/02_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_SPEC.md`: domain does not compute PnL, quantity, price, fees, or slippage.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/10_PHASE_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_SPEC.md`: service does not compute PnL, quantity, price, fees, or slippage.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/18_PHASE_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_SPEC.md`: composition does not compute PnL, position sizing, quantity, price, fees, slippage, risk-adjusted return, or persistence.

Impact: the implementation appears aligned with its narrow Phase 2I specs, but those specs do not satisfy the broader Replay Backtest Runner MVP review topic.

### 4. Historical PnL audit data is partial/local-only and contains no usable actuals

The historical audit marker is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`. Realized PnL by day, PnL by symbol, fees/funding/commission, and large winners/losers all contain `NO_DATA`.

Evidence:
- `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md`
- `claude_worklog/historical_pnl_audit/03_30D_REALIZED_PNL_BY_DAY.md`
- `claude_worklog/historical_pnl_audit/04_30D_PNL_BY_SYMBOL.md`
- `claude_worklog/historical_pnl_audit/05_30D_FEES_FUNDING_COMMISSION.md`
- `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md`

Impact: the runner cannot be approved for historical PnL comparison against real historical winners/losers because the available audit evidence has no actual comparison rows.

### 5. Historical proof uses deterministic fixture PnL, separate from the runner

`historical_30d_replay_and_paper_proof.py` has deterministic fixtures with two preserved winners and three blocked/reduced losers. It sums fixture strings for `legacy_realized_pnl_fixture_sum`, `v2_paper_pnl_fixture_sum`, and `estimated_loss_avoided_by_v2`.

Evidence:
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:80`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:187`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:191`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:241`

The same module states that historical Binance account-history credentials were unavailable and that realized PnL values are fixture values for operator workflow validation.

Impact: this is useful non-live evidence, but it is not an actual backtest runner calculation and should not be treated as historical PnL parity.

### 6. Non-live operational proof still has a drawdown placeholder

`build_non_live_proof()` emits `gross_paper_pnl: "+12.40"` and `max_drawdown_placeholder: "0.00"`.

Evidence:
- `v2/backend/app/proof/non_live_operational_proof.py:263`
- `v2/backend/app/proof/non_live_operational_proof.py:271`
- `v2/backend/app/proof/non_live_operational_proof.py:272`

Impact: drawdown is not calculated from an equity curve.

### 7. API replay route is scaffold-only

`v2/backend/app/api/v1/replay.py` exposes only route metadata via an OPTIONS shim and marks itself as `milestone_d_status: skeleton`.

Impact: there is no request/response contract for submitting a replay run or retrieving backtest metrics through the API.

## Concrete Blockers

1. Missing financial backtest output model:
   - No net/gross PnL, fees/funding/commission, equity curve, drawdown, win/loss, or attribution fields exist in `ReplayBacktestSummary`.

2. Missing replay financial input contract:
   - No typed input object exists for historical trades/fills/positions with side, quantity, prices, timestamps, fees, funding, and source lineage.

3. Missing PnL and drawdown calculation:
   - The runner only counts mirrored paper ledger decisions. It does not calculate realized or mark-to-market PnL, cumulative equity, peak equity, or max drawdown.

4. Missing historical actual comparison:
   - Historical audit files are partial/local-only and contain `NO_DATA`, while the proof module uses deterministic fixture values.

5. Missing large winner/loser attribution in the runner:
   - Fixture proof rows carry winner/reduced flags, but the runner output does not attribute winners/losers by trade, symbol, reason, feature snapshot, prediction, decision, or risk decision.

6. Missing test coverage for the requested MVP checks:
   - Existing replay runner tests cover value-object invariants, mirror mapping, clock handling, count partitions, and import cleanliness. They do not test PnL, drawdown, historical comparison, or large winner/loser attribution.

## Proposed Non-Live Autofix Tasks

1. Add a pure domain input contract:
   - Create immutable `ReplayBacktestInputTrade` or equivalent with `trade_id`, `symbol`, `side`, `entry_ts_ms`, `exit_ts_ms`, `entry_price`, `exit_price`, `quantity`, `fee`, `funding`, `prediction_id`, `decision_id`, `risk_decision_id`, `feature_snapshot_id`, and `source`.
   - Keep `live_blocked=True` and no I/O/import side effects.

2. Add a pure metrics output contract:
   - Extend or add `ReplayBacktestMetrics` with `gross_pnl`, `net_pnl`, `fees_total`, `funding_total`, `trade_count`, `win_count`, `loss_count`, `max_drawdown`, `largest_winner`, `largest_loser`, and attribution partitions.

3. Implement a pure calculator service:
   - Calculate per-trade realized PnL from side/quantity/entry/exit.
   - Calculate net PnL after fees/funding.
   - Build cumulative equity and max drawdown from ordered closed-trade results.
   - Return deterministic value objects only. No Redis, files, network, exchange APIs, or live execution.

4. Add historical comparison adapter using local artifacts only:
   - Read committed local audit/proof artifacts only when explicitly invoked by a CLI/proof module, not during domain/service import.
   - Fail closed with an explicit `historical_actuals_unavailable` status when audit rows are `NO_DATA` or marker is partial.

5. Add large winner/loser attribution:
   - Emit top winners/losers by trade and symbol with lineage fields and reason codes.
   - Include preserved-winner and reduced/rejected-loser counts derived from actual calculated trade results, not only fixture flags.

6. Add focused tests:
   - Long and short PnL math.
   - Fee/funding netting.
   - Equity curve and max drawdown.
   - Largest winner/largest loser attribution.
   - Historical `NO_DATA` fail-closed comparison.
   - Import-clean and no-live side-effect guards matching existing Phase 2I style.

## Recommendation

CODEX_PARALLEL_REVIEW_BLOCKED

The current Phase 2I implementation is a safe, pure, non-live mirror-count assembler, not a complete Replay Backtest Runner MVP for PnL/drawdown and historical winner/loser attribution.
