# Codex Parallel Review - Historical PnL / Trade Audit Integration

Review date: 2026-05-12
Mode: read-only parallel review except requested artifact creation

## Decision

CODEX_PARALLEL_REVIEW_BLOCKED

The Phase 2 non-live integration scaffolding is present and reviewed as passing for LAB replay-case authoring and historical-PnL replay wiring. The historical audit itself is not evidence-ready: the 30-day Binance read-only pull was not requested, income/trade/order row counts are zero, PnL by day and symbol are `NO_DATA`, fee/funding/commission drag is `NO_DATA`, and realized outcomes are not joined to trainer, risk, ledger, or replay lineage.

## Scope Inspected

- `claude_worklog/historical_pnl_audit`
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind`
- `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring`
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready`
- `claude_worklog/phase2_core_rebuild/automation_reliability/codex_recover_169_*`
- `claude_worklog/phase2_core_rebuild/automation_reliability/codex_recover_170_*`

No `/home/wali/Desktop/AI BOT` mutation was performed. No Redis command was invoked. No Redis key was read, written, or deleted. No live service was restarted. No order was placed or canceled. No leverage or margin setting was changed. Live trading was not enabled. No deployment was performed. No secret values were exposed.

## Check Results

### 30-Day Audit Status

BLOCKED. `01_DATA_SOURCE_STATUS.md` records `requested_days: 30`, `binance_pull_requested: False`, no Binance API key/secret environment presence, and no symbols requested for trade/order history. `02_BINANCE_READONLY_PULL_SUMMARY.md` records `income_rows: 0`, `trade_rows: 0`, `order_rows: 0`, and `BINANCE_PULL_NOT_REQUESTED`. `10_GO_NO_GO.md` contains `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.

### PnL By Symbol / Day

BLOCKED. `03_30D_REALIZED_PNL_BY_DAY.md` contains only `NO_DATA | 0`. `04_30D_PNL_BY_SYMBOL.md` contains only `NO_DATA | 0`. `06_LARGE_WINNERS_AND_LOSERS.md` is not backed by populated 30-day realized-trade rows. There is no usable baseline for repeated-loss detection, symbol concentration, drawdown-day review, or winner/loser ranking.

### Fee / Funding Drag

BLOCKED. `05_30D_FEES_FUNDING_COMMISSION.md` contains only `NO_DATA | 0`. There is no gross-vs-net PnL, commission drag, funding drag, carry drag, or per-symbol/per-day fee attribution evidence.

### LAB Hedge Failure Integration

PARTIAL PASS. `legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md` captures the failure: protective long closed around breakeven, residual short remained, and LAB pumped approximately 80% against the remaining short.

Phase 2M integrates that failure as a non-live typed replay fixture with five variants: legacy action, keep hedge, close short, reduce short, and block hedge close. `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/09_CODEX_GO_NO_GO.md` contains `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS`.

The limitation remains material: the current typed replay surfaces do not model hedge state, residual exposure, partial-close size, realized PnL delta, slippage, fees, funding, OI, liquidation map, orderbook depth, or squeeze risk. Phase 2P includes the LAB case as a deterministic evidence pointer only.

### V2 Risk / Backtest Requirements Derived From Evidence

PARTIAL PASS. `08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md` names the right V2 requirements: repeated realized-loss detection, fee/funding drag identification, large-loser comparison to trainer confidence and feature freshness, hedge-unwind residual-exposure detection, shorting-bottoms / longing-tops detection, stale/missing-data default-deny, and replay/backtest cases for large loser patterns.

`09_V2_BUILD_IMPACT_MAP.md` maps realized PnL by symbol, fee/funding/commission drag, large winners/losers, trainer/orchestrator evidence, and LAB hedge unwind into the `paper_backtest_mvp` lane. Phase 2P provides deterministic non-live replay wiring and `09_CODEX_GO_NO_GO.md` contains `PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_CODEX_PASS`, but it remains fixture/pointer integration. It explicitly does not perform a Binance read-only pull, PnL aggregation, fee/funding accounting, trainer outcome join, or residual-exposure modeling.

## Concrete Blockers

1. No completed 30-day read-only account-history baseline exists; income, trade, and order row counts are all zero.
2. PnL by day and PnL by symbol are placeholder-only, so repeated loss clusters, symbol concentration, and drawdown days cannot be audited.
3. Fee/funding/commission drag is placeholder-only, so net-vs-gross and carry/commission impact cannot be validated from evidence.
4. Large winner/loser rankings are unavailable beyond empty audit tables and deterministic fixture labels.
5. Realized outcomes are not joined to `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, trainer confidence, feature freshness, paper-ledger action/reason, or replay-step lineage.
6. LAB hedge failure is integrated as pointer/replay evidence, but there is no typed residual-exposure contract for hedge-leg role, remaining net exposure, hedge kept versus hedge closed, adverse move, partial-close ratio, or PnL delta.
7. Phase 2M/2P surfaces intentionally forbid or omit the market/outcome fields needed for this audit: PnL, quantity, price, fees, funding, hedge state, residual exposure, and squeeze risk.

## Proposed Non-Live Autofix Tasks

1. Add a local-only `HistoricalTradeOutcome` fixture/contract with source pointer, symbol, timestamp, side/action/open-close marker, gross realized PnL, commission, funding, net PnL, quantity/notional or explicit unavailable markers, and optional lineage IDs.
2. Add a pure offline parser/aggregator for sanitized local CSV/JSON/markdown audit rows that emits 30-day PnL by day, by symbol, and by symbol/day with row-count reconciliation.
3. Add a fee/funding/commission drag aggregator with gross PnL, total commission, total funding, net PnL, and drag ratio by symbol/day.
4. Add a realized winner/loser attribution report that joins outcome rows to `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, confidence/freshness, paper-ledger action/reason, and replay step IDs where evidence exists; emit explicit `NO_JOIN_DATA` when unavailable.
5. Extend the LAB non-live replay fixture with hedge-leg role, net exposure before/after close, residual short marker, adverse move marker, protected-vs-unprotected outcome, partial-close ratio, and PnL delta of hedge kept versus hedge closed.
6. Keep Redis, network, exchange, secret, persistence, live-service, leverage/margin, and live-gate behavior forbidden while allowing pure deterministic PnL/outcome/residual-exposure fields in test-only audit fixtures.
7. Preserve a no-data regression fixture matching `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY` so the system reports partial/local-only honestly until a separately authorized read-only account-history pull or sanitized local source is available.

## Passing Safety Evidence

- `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS` is present.
- `PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_CODEX_PASS` is present.
- `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS` is present.
- The inspected Phase 2M/2P work is non-live, deterministic, and test-only, with inert evidence pointers/counts and no live, exchange, Redis, or deployment behavior.

CODEX_PARALLEL_REVIEW_BLOCKED
