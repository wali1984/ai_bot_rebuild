# Codex Parallel Review - Replay Backtest Runner MVP

Review timestamp: 2026-05-08
Review mode: read-only parallel review, except this report and GO/NO-GO artifact.

## Scope Inspected

- `v2/backend/app/domain/replay_backtest_runner/`
- `v2/backend/app/services/replay_backtest_runner/`
- `v2/backend/app/composition/replay_backtest_runner/`
- `v2/backend/tests/unit/domain/replay_backtest_runner/`
- `v2/backend/tests/unit/services/replay_backtest_runner/`
- `v2/backend/tests/unit/composition/replay_backtest_runner/`
- `v2/backend/tests/unit/historical_pnl_replay_wiring/`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/`
- `claude_worklog/historical_pnl_audit/`

No Redis, live service, exchange, order, leverage, margin, deployment, or live-trading action was performed. Tests were not executed to preserve read-only review posture and avoid cache writes.

## Result

CODEX_PARALLEL_REVIEW_BLOCKED

The implemented replay/backtest runner is a pure lineage/action mirror and count aggregator. It is safe and deterministic for its narrower 2I contract, but it does not satisfy the requested Replay Backtest Runner MVP review checks for PnL/drawdown, historical PnL comparison, or large winner/loser attribution.

## Concrete Blockers

1. Backtest output metrics do not include PnL, drawdown, fees, funding, price, quantity, sizing, return, win/loss, or attribution fields.

   Evidence: `ReplayBacktestSummary` only exposes emitted timestamp, total/action/reason counts, and `live_blocked` at `v2/backend/app/domain/replay_backtest_runner/summary.py:33`. The assembler computes only `total_steps_count`, allow/deny counts, and reason counts at `v2/backend/app/services/replay_backtest_runner/service.py:186`.

2. Replay steps do not carry any market or realized-result input contract.

   Evidence: `ReplayBacktestStep` carries lineage IDs, symbol, timestamp, action/reason mirror fields, and `live_blocked`, but no realized trade outcome or market context at `v2/backend/app/domain/replay_backtest_runner/step.py:70`. Step assembly derives action/reason only from `PaperExecutionLedgerEntry.ledger_reason_code` at `v2/backend/app/services/replay_backtest_runner/service.py:79`, then copies lineage fields at `v2/backend/app/services/replay_backtest_runner/service.py:113`.

3. Historical PnL evidence is partial local-only and contains no real comparison baseline.

   Evidence: `claude_worklog/historical_pnl_audit/01_DATA_SOURCE_STATUS.md:5` says 30 days were requested, but `binance_pull_requested: False` is recorded at line 6 and credentials are absent at lines 7-10. Realized PnL by day and symbol are `NO_DATA` at `03_30D_REALIZED_PNL_BY_DAY.md:5` and `04_30D_PNL_BY_SYMBOL.md:5`. The audit GO/NO-GO is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY` at `10_GO_NO_GO.md:1`.

4. Large winner/loser attribution is not implemented.

   Evidence: the large winners/losers audit has only `NO_DATA` rows at `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md:3` and `:8`. The historical replay wiring fixtures name winner/loser scenarios at `v2/backend/tests/unit/historical_pnl_replay_wiring/fixtures.py:71` and `:93`, but those are scenario slugs and risk decisions, not realized winner/loser measurements. The harness comparison record stores only a legacy pointer plus a paper ledger entry at `v2/backend/tests/unit/historical_pnl_replay_wiring/harness.py:23`.

5. The current tests explicitly prevent the missing MVP metrics from appearing in the historical replay wiring surface.

   Evidence: `DISALLOWED_MARKET_FIELDS` includes `pnl`, `realized_pnl`, `price`, `fees`, `funding`, `hedge_state`, `residual_exposure`, and `squeeze_risk` at `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:33`, and `test_harness_does_not_introduce_pnl_or_size_or_price_or_fees_or_funding_field` enforces that exclusion at line 157.

6. The historical audit requirements call for exactly the missing work.

   Evidence: the audit requires repeated-loss, fee/funding drag, large-loser confidence/freshness comparison, residual exposure, and replay/backtest scenarios for large loser patterns at `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md:5`. The impact map assigns realized PnL, net PnL accounting, and large winner/loser attribution to the `paper_backtest_mvp` lane at `claude_worklog/historical_pnl_audit/09_V2_BUILD_IMPACT_MAP.md:7`.

## Non-Live Autofix Tasks Proposed

1. Add a pure, test-only/domain-level `ReplayBacktestMarketResult` or equivalent value object with realized PnL, fees, funding, net PnL, notional/quantity, entry/exit timestamps or prices where available, and source evidence pointer. Keep it file/Redis/network free.

2. Extend the replay/backtest summary contract with net realized PnL, gross realized PnL, total fees/funding, max drawdown over ordered closed outcomes, winner/loser counts, largest winner, largest loser, and per-symbol aggregates. Gate with unit tests over deterministic in-memory fixtures.

3. Replace scenario-name-only historical replay wiring with typed historical PnL inputs that include signed realized outcome rows and expected attribution fields. Keep fixtures local and synthetic unless a separate read-only pull artifact is explicitly available.

4. Add a pure attribution helper that joins replay steps to historical outcome rows by evidence pointer and lineage IDs, then emits large winner/loser attribution by symbol, decision_id, prediction_id, feature_snapshot_id, risk reason, and replay reason.

5. Update tests that currently forbid PnL/market fields so they forbid live/exchange/secret fields while allowing the new pure result metrics.

6. Add regression tests for drawdown ordering, fees/funding netting, zero-data behavior, duplicate pointer rejection, missing pointer rejection, largest winner/loser tie handling, and symbol-level PnL aggregation.

## Safety Notes

The existing 2I runner remains live-blocked and does not import Redis or HTTP surfaces in the reviewed implementation. The block is functional completeness against the requested MVP checks, not a live-safety violation.
