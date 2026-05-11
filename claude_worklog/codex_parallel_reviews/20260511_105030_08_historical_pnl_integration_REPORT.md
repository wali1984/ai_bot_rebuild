# Codex Parallel Review - Historical PnL / Trade Audit Integration

Review date: 2026-05-11
Mode: read-only parallel review except requested artifact creation

## Decision

CODEX_PARALLEL_REVIEW_BLOCKED

The non-live Phase 2 fixture path is integrated, but the historical PnL/trade audit is not quantitatively ready. The current 30-day audit remains partial/local-only: no Binance read-only pull was requested, income/trade/order row counts are zero, PnL by day and symbol are `NO_DATA`, and fee/funding/commission drag is `NO_DATA`.

## Scope Inspected

- `claude_worklog/historical_pnl_audit`
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind`
- `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring`
- `claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness`
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready`
- prior Codex historical-PnL review artifacts for continuity

No `/home/wali/Desktop/AI BOT` mutation was performed. No Redis command was invoked. No Redis key was read, written, or deleted. No live service was restarted. No order was placed or canceled. No leverage or margin setting was changed. Live trading was not enabled. No deployment was performed. No secret values were exposed.

## Check Results

### 30-Day Audit Status

BLOCKED. `claude_worklog/historical_pnl_audit/01_DATA_SOURCE_STATUS.md` records `requested_days: 30`, `binance_pull_requested: False`, absent Binance API key/secret env presence, and no symbols requested for trade/order history. `02_BINANCE_READONLY_PULL_SUMMARY.md` records `income_rows: 0`, `trade_rows: 0`, `order_rows: 0`, and `BINANCE_PULL_NOT_REQUESTED`. `10_GO_NO_GO.md` contains `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.

### PnL By Symbol / Day

BLOCKED. `03_30D_REALIZED_PNL_BY_DAY.md` contains only `NO_DATA | 0`. `04_30D_PNL_BY_SYMBOL.md` contains only `NO_DATA | 0`. `06_LARGE_WINNERS_AND_LOSERS.md` contains only `NO_DATA | 0` for both largest losers and largest winners. There is no populated 30-day realized-PnL baseline for repeated-loss detection, symbol concentration, drawdown-day inspection, or winner/loser ranking.

### Fee / Funding Drag

BLOCKED. `05_30D_FEES_FUNDING_COMMISSION.md` contains only `NO_DATA | 0`. There is no gross-vs-net PnL, commission drag, funding drag, carry drag, or per-symbol/per-day fee attribution evidence.

### Trainer / Decision Attribution

BLOCKED. `07_LEGACY_TRAINER_DECISION_EVIDENCE.md` records `row_count: 0`, empty `count_by_symbol`, empty `quote_qty_by_symbol`, and empty `qty_by_symbol`. There is no realized-outcome join to `prediction_id`, `decision_id`, `risk_decision_id`, `feature_snapshot_id`, confidence, feature freshness, risk reason code, paper-ledger action, or replay-step ID.

### LAB Hedge Failure Integration

PARTIAL PASS. The LAB hedge-unwind / short-squeeze failure is captured in `legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`: protective long closed around breakeven, residual short remained, and LAB pumped approximately 80% against the remaining short.

Phase 2M integrates the failure as a non-live typed replay fixture with five variants: legacy action, keep hedge, close short, reduce short, and block hedge close. `replay_case_lab_hedge_unwind/09_CODEX_GO_NO_GO.md` contains `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS`.

The limitation is material: `replay_case_lab_hedge_unwind/02_REPLAY_CASE_OUTCOME_MATRIX.md` states the current typed surfaces do not model hedge state, residual exposure, position size, PnL, slippage, fees, funding, OI, liquidation map, orderbook depth, or squeeze risk. It also states close-short and reduce-short collapse to the same typed mirror sequence because partial-close size is not typed yet.

### V2 Risk / Backtest Requirements Derived From Evidence

PARTIAL PASS. `08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md` correctly derives the expected V2 requirements: repeated realized-loss detection, fee/funding drag identification, large-loser comparison to trainer confidence and feature freshness, hedge-unwind residual-exposure detection, shorting-bottoms / longing-tops detection, stale/missing-data default-deny, and replay/backtest scenarios for large loser patterns.

`09_V2_BUILD_IMPACT_MAP.md` maps realized PnL by symbol, fee/funding/commission drag, large winners/losers, trainer/orchestrator evidence, and LAB hedge unwind into the `paper_backtest_mvp` lane. Phase 2P and Phase 2Q pass markers confirm deterministic non-live replay wiring and aggregate roll-up harnesses, but those are fixture/evidence-pointer integrations. They do not replace a populated 30-day account-history audit.

## Concrete Blockers

1. No completed 30-day read-only account-history baseline exists; income, trade, and order row counts are all zero.
2. PnL by day and symbol are placeholder-only, so repeated loss clusters, symbol concentration, and drawdown days cannot be audited.
3. Fee/funding/commission drag is placeholder-only, so net-vs-gross and carry/commission impact cannot be validated from evidence.
4. Large winner/loser rankings are unavailable beyond empty audit tables and deterministic fixture labels.
5. Realized outcomes are not joined to trainer, decision, risk, feature, paper-ledger, or replay lineage.
6. LAB hedge failure is integrated as pointer/replay evidence, but there is no typed residual-exposure contract for hedge leg role, remaining net exposure, hedge kept versus hedge closed, adverse move, partial close ratio, or PnL delta.
7. Current Phase 2M/2P typed surfaces explicitly avoid the market/outcome fields required for this audit: PnL, quantity, price, fees, funding, hedge state, residual exposure, and squeeze risk.

## Proposed Non-Live Autofix Tasks

1. Add a local-only `HistoricalTradeOutcome` fixture/contract with source pointer, symbol, timestamp, side/action/open-close marker, gross realized PnL, commission, funding, net PnL, quantity/notional or explicit unavailable markers, and optional lineage IDs.
2. Add a pure offline parser/aggregator for sanitized local CSV/JSON/markdown audit rows that emits 30-day PnL by day, by symbol, and by symbol/day with row-count reconciliation.
3. Add a fee/funding/commission drag aggregator with gross PnL, total commission, total funding, net PnL, and drag ratio by symbol/day.
4. Add a realized winner/loser attribution report that joins outcome rows to `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, confidence/freshness, paper-ledger action/reason, and replay step IDs where evidence exists; emit explicit `NO_JOIN_DATA` when unavailable.
5. Extend the LAB non-live replay fixture with hedge-leg role, net exposure before/after close, residual short marker, adverse move marker, protected-vs-unprotected outcome, partial-close ratio, and PnL delta of hedge kept versus hedge closed.
6. Update Phase 2P tests so Redis, network, exchange, secret, persistence, live-service, and live-gate behavior remain forbidden while pure deterministic PnL/outcome/residual-exposure fields are allowed and asserted.
7. Preserve a no-data regression fixture matching `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY` so the system reports partial/local-only honestly until a separately authorized read-only account-history pull or sanitized local source is available.

## Passing Safety Evidence

- `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS` is present.
- `PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_CODEX_PASS` is present.
- `PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_CODEX_PASS` is present.
- `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS` is present.
- The inspected Phase 2M/2P/2Q work is non-live, deterministic, and test-only, with inert evidence pointers/counts and no live/exchange/Redis behavior.

CODEX_PARALLEL_REVIEW_BLOCKED
