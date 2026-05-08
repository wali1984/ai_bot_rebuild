# Codex Parallel Review - Replay Backtest Runner MVP

Review timestamp: 2026-05-08
Review mode: read-only parallel review, except this report and GO/NO-GO artifact.

## Scope inspected

- `v2/backend/app`
- `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl`
- `claude_worklog/historical_pnl_audit`

No Redis, live service, exchange, order, leverage, margin, deployment, or live-trading action was performed. Tests were not executed because this review mode was read-only and pytest would write cache/pyc artifacts.

## Result

CODEX_PARALLEL_REVIEW_BLOCKED

The implemented replay/backtest runner is safe, deterministic, and live-blocked for the narrower Phase 2I mirror/count contract. It is not sufficient for the requested Replay Backtest Runner MVP checks because it does not accept or emit realized market outcomes, PnL, drawdown, historical comparison metrics, or large winner/loser attribution.

## Findings

1. Replay input contracts do not include realized trade or market-result inputs.

   Evidence: `ReplayBacktestStep` carries IDs, symbol, step timestamp, action/reason mirrors, input paper action/reason, and `live_blocked`, but no price, quantity, realized PnL, fees, funding, slippage, source outcome row, or close/open state in `v2/backend/app/domain/replay_backtest_runner/step.py:70`. Step assembly derives only mirror action/reason from `PaperExecutionLedgerEntry.ledger_reason_code` and copies lineage fields in `v2/backend/app/services/replay_backtest_runner/service.py:79` and `v2/backend/app/services/replay_backtest_runner/service.py:113`.

2. Backtest output metrics are action/reason counts only.

   Evidence: `ReplayBacktestSummary` exposes summary ID, replay run ID, emitted timestamp, total/allow/deny/reason counts, and `live_blocked` in `v2/backend/app/domain/replay_backtest_runner/summary.py:32`. The assembler aggregates only `total_steps_count`, allow/deny counts, and five mirror reason counts in `v2/backend/app/services/replay_backtest_runner/service.py:186`. There is no net PnL, gross PnL, drawdown, return, fee/funding, win/loss, largest winner, largest loser, or per-symbol metric.

3. PnL/drawdown calculation is absent by design in the Phase 2I spec.

   Evidence: the Phase 2I.A, 2I.B, and 2I.C specs explicitly state that the domain, assembler, and composition layers do not compute PnL, quantity, price, fees, slippage, position sizing, or risk-adjusted return. The current implementation matches that narrower scope, but that means the reviewed MVP checks for PnL/drawdown cannot pass.

4. Historical PnL comparison has no usable baseline in the inspected audit artifacts.

   Evidence: `claude_worklog/historical_pnl_audit/01_DATA_SOURCE_STATUS.md` records `binance_pull_requested: False`, no API key/secret env presence, and no requested trade-order symbols. `claude_worklog/historical_pnl_audit/02_BINANCE_READONLY_PULL_SUMMARY.md` records `income_rows: 0`, `trade_rows: 0`, and `order_rows: 0`. `03_30D_REALIZED_PNL_BY_DAY.md`, `04_30D_PNL_BY_SYMBOL.md`, and `06_LARGE_WINNERS_AND_LOSERS.md` contain only `NO_DATA` rows.

5. Large winner/loser attribution is scenario-name-only, not outcome-based.

   Evidence: `v2/backend/tests/unit/historical_pnl_replay_wiring/fixtures.py` defines scenario slugs such as `historical_pnl_pack_btc_winner_long`, `historical_pnl_pack_eth_winner_short`, and `historical_pnl_pack_lab_loser_short`, but the input type contains only a legacy pointer plus `RiskDecisionRecord`. The harness comparison record stores only a legacy pointer and a `PaperExecutionLedgerEntry` in `v2/backend/tests/unit/historical_pnl_replay_wiring/harness.py`; it does not join signed PnL or rank winners/losers.

6. Existing tests explicitly forbid the missing MVP fields on historical replay wiring.

   Evidence: `DISALLOWED_MARKET_FIELDS` includes `pnl`, `realized_pnl`, `quantity`, `price`, `fees`, `slippage`, `funding`, `hedge_state`, `residual_exposure`, and `squeeze_risk` in `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:33`, and `test_harness_does_not_introduce_pnl_or_size_or_price_or_fees_or_funding_field` enforces that exclusion at `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:157`.

7. The historical audit requirements call for the missing behavior.

   Evidence: `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md` requires repeated realized loss identification, fee/funding drag, large-loser comparison to trainer confidence and feature freshness, residual exposure failure detection, and replay/backtest scenarios for large loser patterns. `claude_worklog/historical_pnl_audit/09_V2_BUILD_IMPACT_MAP.md` maps realized PnL, fee/funding net PnL accounting, and large winner/loser attribution to the `paper_backtest_mvp` lane.

## Concrete blockers

- No typed replay input for historical realized outcomes or market fills.
- No PnL/drawdown/netting calculation in the runner or summary contract.
- No historical PnL baseline rows in the inspected audit artifacts.
- No large winner/loser attribution output keyed by symbol, decision, prediction, feature snapshot, reason, or replay step.
- Existing historical replay tests currently assert that PnL/market fields must not exist.

## Proposed non-live autofix tasks

1. Add a pure value-object input contract for historical realized outcomes, including source evidence pointer, symbol, signed gross realized PnL, fees, funding, net PnL, quantity/notional or explicit unavailable markers, and event timestamp. Keep it Redis/network/file-write free.

2. Add a pure metrics assembler that consumes ordered replay steps plus historical outcome rows and emits net PnL, gross PnL, fees/funding totals, max drawdown, win/loss counts, largest winner/loser, and per-symbol aggregates.

3. Add deterministic local fixtures for zero-data, positive winner, negative loser, fee/funding drag, duplicate pointer rejection, missing pointer rejection, and tie handling. Do not use live exchange calls.

4. Add attribution records joining outcome rows to `replay_step_id`, `paper_trade_id`, `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, symbol, paper ledger reason, and replay reason.

5. Update historical replay wiring tests so they continue forbidding live/exchange/secret fields, but allow and assert the new pure PnL/result metrics.

6. Add a non-live historical comparison report generator that can emit explicit `NO_DATA` status when the audit baseline is absent and full comparison metrics when read-only baseline artifacts are present.

## Safety notes

The reviewed implementation preserves the live-blocked invariant and does not introduce Redis, HTTP, exchange, order, leverage, margin, deployment, or live-trading behavior. The block is functional completeness against the requested MVP review checks, not a live-safety violation.
