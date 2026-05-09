# Codex Parallel Review - Historical PnL / Trade Audit Integration

Review timestamp: 2026-05-09
Review mode: read-only parallel review, except the two requested output artifacts.

## Result

CODEX_PARALLEL_REVIEW_BLOCKED

The current integration is safe and useful as non-live typed evidence plumbing, but it is not ready as a historical PnL / trade audit integration. The 30-day audit remains partial/local-only with no realized account-history rows, no PnL by symbol/day, and no fee/funding/commission rows. LAB hedge failure evidence is integrated as deterministic pointer and replay fixture evidence, but not yet as residual-exposure, hedge-state, squeeze-risk, fee/funding drag, or PnL-impact behavior.

## Scope inspected

- `claude_worklog/historical_pnl_audit`
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`
- `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind`
- `claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness`
- Relevant Phase 2 risk, replay/backtest, paper-ledger, and decision-explainability evidence references found under `claude_worklog/phase2_core_rebuild`

No `/home/wali/Desktop/AI BOT` mutation was performed. No Redis command was invoked. No Redis key was read, written, or deleted. No live service was restarted. No exchange order was placed or canceled. No leverage or margin setting was changed. Live trading was not enabled. No deployment was performed. No secret values were exposed.

## Evidence reviewed

### 30-day audit status

`claude_worklog/historical_pnl_audit/01_DATA_SOURCE_STATUS.md` records:

- `requested_days: 30`
- `binance_pull_requested: False`
- `binance_api_key_env_present: False`
- `binance_api_secret_env_present: False`
- `symbols_requested_for_trade_order_history: none`

`claude_worklog/historical_pnl_audit/02_BINANCE_READONLY_PULL_SUMMARY.md` records:

- `income_rows: 0`
- `trade_rows: 0`
- `order_rows: 0`
- gap: `BINANCE_PULL_NOT_REQUESTED`

`claude_worklog/historical_pnl_audit/10_GO_NO_GO.md` is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.

### PnL by symbol/day

`03_30D_REALIZED_PNL_BY_DAY.md` contains only `NO_DATA | 0`.

`04_30D_PNL_BY_SYMBOL.md` contains only `NO_DATA | 0`.

`06_LARGE_WINNERS_AND_LOSERS.md` contains only `NO_DATA | 0` for both largest losers and largest winners.

There is no populated 30-day symbol/day realized-PnL baseline to support repeated-loss detection, drawdown-day inspection, symbol concentration analysis, or large winner/loser ranking.

### Fee/funding drag

`05_30D_FEES_FUNDING_COMMISSION.md` contains only `NO_DATA | 0`.

There is no current evidence for gross PnL, net PnL, commission drag, funding drag, carry drag, or per-symbol/per-day fee attribution.

### Trainer / decision attribution

`07_LEGACY_TRAINER_DECISION_EVIDENCE.md` records `row_count: 0`, empty `count_by_symbol`, empty `quote_qty_by_symbol`, and empty `qty_by_symbol`.

There is no realized-outcome join to `prediction_id`, `decision_id`, `risk_decision_id`, `feature_snapshot_id`, confidence, feature freshness, or risk reason code.

### LAB hedge failure integration

`claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md` captures the critical failure: protective long closed around breakeven, short exposure left open, and LAB pumped approximately 80% against the remaining short.

Phase 2M has `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS` and materializes five deterministic typed replay outcomes: legacy, keep-hedge, close-short, reduce-short, and block-hedge-close. This is good traceability through the existing replay/backtest runner.

Phase 2P has `PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_CODEX_PASS` and includes a `LABUSDT` loser-short scenario with deterministic `legacy_realized_trade_evidence__lab_hedge_unwind_squeeze__step_N` pointers. This is useful pointer plumbing.

The behavioral gap remains explicit in the Phase 2M and Phase 2P packets: they intentionally do not model PnL, position size, fees, funding, hedge state, residual exposure, liquidation/OI/orderbook context, or squeeze risk. Phase 2M also documents that close-short and reduce-short collapse to the same typed mirror sequence at the current typed surface layer.

### V2 risk/backtest requirements derived from evidence

The documented requirements are directionally correct:

- `08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md` requires repeated realized-loss detection, fee/funding drag identification, large-loser comparison to trainer confidence and feature freshness, hedge-unwind residual-exposure detection, shorting-bottom/longing-top detection, default-deny stale/missing-data behavior, and replay/backtest cases for large-loser patterns.
- `09_V2_BUILD_IMPACT_MAP.md` maps realized PnL by symbol, fee/funding drag, large winners/losers, trainer/orchestrator evidence, and LAB hedge unwind into the paper/backtest MVP lane.
- Phase 2P historical-PnL replay wiring and Phase 2Q aggregate evidence roll-up provide non-live typed pointer/count plumbing over deterministic packs.

The gap is evidence depth. Current implemented fixtures are deterministic labels, pointers, and counters, not populated account-history/PnL integration.

## Blockers

1. No completed 30-day read-only account-history baseline exists. Income, trade, and order row counts are all zero.
2. PnL by day and PnL by symbol are unavailable beyond `NO_DATA`, so repeated loss clusters, symbol concentration, and drawdown days cannot be audited.
3. Fee/funding/commission drag is unavailable beyond `NO_DATA`, so net-vs-gross PnL and carry/commission impact cannot be audited.
4. Large winner/loser rankings are unavailable beyond deterministic fixture names; they are not derived from account-history rows.
5. Realized outcomes are not joined to trainer, decision, risk, or feature lineage.
6. LAB hedge failure is integrated as pointer/replay evidence, but there is no typed residual-exposure contract for hedge leg role, remaining net exposure, hedge kept vs hedge closed, adverse move, or PnL delta.
7. Current Phase 2P historical replay wiring intentionally forbids the market/outcome fields needed for this integration: PnL, quantity, price, fees, funding, hedge state, residual exposure, and squeeze risk.

## Proposed non-live autofix tasks

1. Add a local-only `HistoricalTradeOutcome` fixture/contract with source pointer, symbol, event timestamp, side/action/open-close marker, gross realized PnL, commission, funding, net PnL, quantity/notional or explicit unavailable markers, and optional lineage IDs.
2. Add a pure offline parser/aggregator for sanitized local CSV/JSON or markdown audit rows that emits 30-day PnL by day, by symbol, and by symbol/day, with row-count reconciliation.
3. Add a pure fee/funding/commission drag aggregator with gross PnL, total commission, total funding, net PnL, and drag ratio by symbol/day.
4. Add a realized winner/loser attribution report that joins outcome rows to `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, confidence/freshness, paper ledger action/reason, and replay step IDs where evidence exists; emit explicit `NO_JOIN_DATA` when unavailable.
5. Extend the LAB non-live replay fixture with hedge-leg role, net exposure before/after close, residual short marker, adverse move marker, protected-vs-unprotected outcome, and PnL delta of hedge kept vs hedge closed.
6. Update Phase 2P tests so Redis, network, exchange, secret, persistence, live-service, and live-gate behavior remain forbidden while pure deterministic PnL/outcome/residual-exposure fields are allowed and asserted.
7. Preserve a no-data regression fixture matching the current `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY` state so the system reports partial/local-only honestly until a separately authorized read-only account-history pull or sanitized local source is available.

## Passing safety evidence

- `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS` is present.
- `PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_CODEX_PASS` is present.
- `PHASE2Q_AGGREGATE_EVIDENCE_ROLLUP_HARNESS_CODEX_PASS` is referenced by Phase 2Q review evidence.
- Prior historical-PnL parallel reviews also concluded `CODEX_PARALLEL_REVIEW_BLOCKED` for the same account-history/PnL-data gap.
- The inspected Phase 2M/2P/2Q work is non-live, deterministic, and test-only, with inert evidence pointers/counts and no live/exchange/Redis behavior.
