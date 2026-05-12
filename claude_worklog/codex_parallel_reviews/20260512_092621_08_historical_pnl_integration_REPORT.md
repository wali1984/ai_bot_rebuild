# Codex Parallel Review - Historical PnL / Trade Audit Integration

Review timestamp: 2026-05-12 09:26:21 EDT

Decision: BLOCKED for historical PnL / trade-audit readiness.

## Scope

Read-only inputs inspected:

- `claude_worklog/historical_pnl_audit`
- `claude_worklog/legacy_failure_cases`
- `claude_worklog/phase2_core_rebuild`

No Redis command was run. No live service was restarted. No exchange order, leverage, margin, deployment, live-trading gate, secret, or `/home/wali/Desktop/AI BOT` mutation was touched.

## 30-Day Audit Status

BLOCKED. `claude_worklog/historical_pnl_audit/01_DATA_SOURCE_STATUS.md` records `requested_days: 30`, `binance_pull_requested: False`, no Binance API key/secret env presence, and no requested trade/order-history symbols. `02_BINANCE_READONLY_PULL_SUMMARY.md` records `income_rows: 0`, `trade_rows: 0`, `order_rows: 0`, and `BINANCE_PULL_NOT_REQUESTED`. `10_GO_NO_GO.md` remains `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.

## PnL By Symbol / Day

BLOCKED. `03_30D_REALIZED_PNL_BY_DAY.md` contains only `NO_DATA | 0`. `04_30D_PNL_BY_SYMBOL.md` contains only `NO_DATA | 0`. `06_LARGE_WINNERS_AND_LOSERS.md` contains only `NO_DATA | 0` for losers and winners. There is no populated 30-day realized-PnL baseline for repeated-loss detection, drawdown-day inspection, symbol concentration, winner/loser attribution, or symbol/day aggregation.

## Fee / Funding Drag

BLOCKED. `05_30D_FEES_FUNDING_COMMISSION.md` contains only `NO_DATA | 0`. There is no evidence-backed gross-vs-net PnL, commission drag, funding drag, carry cost, or per-symbol/per-day fee attribution.

## Trainer / Decision / Risk Join

BLOCKED. `07_LEGACY_TRAINER_DECISION_EVIDENCE.md` records `row_count: 0`, empty `count_by_symbol`, empty `quote_qty_by_symbol`, and empty `qty_by_symbol`. Realized outcomes are not joined to `prediction_id`, `decision_id`, `risk_decision_id`, `feature_snapshot_id`, confidence, feature freshness, risk reason code, paper-ledger action, replay step, or trainer lineage fields.

## LAB Hedge Failure Integration

PARTIAL PASS. `legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md` captures the LAB hedge-unwind failure: protective long closed around breakeven, residual short remained, and LAB pumped approximately 80% against the remaining short.

Phase 2M integrates the case as non-live typed replay fixtures with five variants: legacy action, keep hedge, close short, reduce short, and block hedge close. `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/09_CODEX_GO_NO_GO.md` contains `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS`.

The limitation remains material. `02_REPLAY_CASE_OUTCOME_MATRIX.md` explicitly says the current typed surfaces do not model hedge state, residual exposure, position size, PnL, slippage, fees, funding, OI, liquidation map, orderbook depth, or squeeze risk. Close-short and reduce-short still collapse to the same typed mirror sequence because partial-close size is not typed.

## V2 Risk / Backtest Requirements From Evidence

PARTIAL PASS. `08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md` derives V2 requirements for repeated realized-loss detection, fee/funding drag identification, large-loser comparison to trainer confidence and feature freshness, hedge-unwind residual-exposure detection, shorting-bottoms / longing-tops detection, stale/missing-data default-deny, and replay/backtest scenarios for large-loser patterns.

`09_V2_BUILD_IMPACT_MAP.md` maps realized PnL by symbol, fee/funding/commission drag, large winners/losers, trainer/orchestrator evidence, and LAB hedge unwind into the `paper_backtest_mvp` lane. Phase 2P historical-PnL replay wiring, Phase 2Q aggregate roll-up, Phase 2V trainer-lineage parity, and V2 backtest/paper MVP readiness have pass markers, but these are fixture/evidence-pointer integrations. They do not replace a populated 30-day account-history audit.

## Concrete Blockers

1. No completed 30-day read-only account-history baseline exists; income, trade, and order row counts are all zero.
2. PnL by day, symbol, and large winner/loser reports are placeholder-only.
3. Fee/funding/commission drag is placeholder-only, so net-vs-gross performance cannot be validated.
4. Realized historical outcomes are not joined to trainer, decision, risk, feature, paper-ledger, replay, or trainer-lineage evidence.
5. LAB hedge replay is integrated as pointer/mirror evidence, but residual exposure, hedge-leg role, partial-close ratio, adverse move, and PnL delta are not typed.
6. Current Phase 2M/2P/2Q surfaces explicitly defer the market/outcome fields this review needs: PnL, quantity, price, fees, funding, hedge state, residual exposure, and squeeze risk.

## Proposed Non-Live Autofix Tasks

1. Add a pure offline `HistoricalTradeOutcome` fixture/contract with source pointer, symbol, timestamp, side/action/open-close marker, gross realized PnL, commission, funding, net PnL, quantity/notional or explicit unavailable markers, and optional lineage IDs.
2. Add a local-only parser/aggregator for sanitized CSV/JSON/markdown account-history rows that emits 30-day PnL by day, by symbol, and by symbol/day with row-count reconciliation.
3. Add a fee/funding/commission drag aggregator with gross PnL, total commission, total funding, net PnL, and drag ratio by symbol/day.
4. Add a realized winner/loser attribution report that joins outcome rows to `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, confidence/freshness, paper-ledger action/reason, and replay step IDs where evidence exists; emit explicit `NO_JOIN_DATA` when unavailable.
5. Extend the LAB non-live fixture with hedge-leg role, net exposure before/after close, residual short marker, adverse move marker, protected-vs-unprotected outcome, partial-close ratio, and PnL delta of hedge kept versus hedge closed.
6. Keep all fixes offline/test-only: no Redis writes/deletes, no network calls, no Binance API calls, no exchange SDK use, no live services, no live-gate changes, no `/home/wali/Desktop/AI BOT` mutation.

CODEX_PARALLEL_REVIEW_HISTORICAL_PNL_INTEGRATION_REPORT_READY
