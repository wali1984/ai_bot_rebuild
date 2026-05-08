# Codex Parallel Review - Historical PnL / Trade Audit Integration

Review timestamp: 2026-05-08
Review mode: read-only parallel review, except this report and GO/NO-GO artifact.

## Scope inspected

- `claude_worklog/historical_pnl_audit`
- `claude_worklog/legacy_failure_cases`
- `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind`
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready`
- Relevant V2 test-only replay fixtures under `v2/backend/tests/unit/historical_pnl_replay_wiring` and `v2/backend/tests/unit/replay_case_lab_hedge_unwind`

No Redis, live service, exchange, order, leverage, margin, deployment, live-trading, or secret action was performed. Tests were not executed because this review mode is read-only and pytest may write cache/pyc artifacts.

## Result

CODEX_PARALLEL_REVIEW_BLOCKED

The current packet is safe and useful as non-live pointer mirroring, but it is not ready as a historical PnL / trade audit integration. The 30-day audit has no realized rows, symbol rows, fee/funding rows, trade rows, or order rows, and the Phase 2P harness intentionally excludes the PnL, market-result, residual-exposure, and squeeze-risk fields needed by this review topic.

## Evidence reviewed

- 30-day audit status: `claude_worklog/historical_pnl_audit/01_DATA_SOURCE_STATUS.md` records `requested_days: 30`, `binance_pull_requested: False`, missing Binance API env names, and no requested symbols. `02_BINANCE_READONLY_PULL_SUMMARY.md` records `income_rows: 0`, `trade_rows: 0`, `order_rows: 0`, with gap `BINANCE_PULL_NOT_REQUESTED`. `10_GO_NO_GO.md` is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.
- PnL by symbol/day: `03_30D_REALIZED_PNL_BY_DAY.md` and `04_30D_PNL_BY_SYMBOL.md` contain only `NO_DATA` rows.
- Fee/funding drag: `05_30D_FEES_FUNDING_COMMISSION.md` contains only `NO_DATA`.
- Large winners/losers and trainer join: `06_LARGE_WINNERS_AND_LOSERS.md` contains only `NO_DATA`; `07_LEGACY_TRAINER_DECISION_EVIDENCE.md` records `row_count: 0`.
- Required V2 evidence: `08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md` requires repeated loss identification, fee/funding drag identification, large-loser comparison to trainer confidence and feature freshness, residual exposure failure detection, and replay/backtest scenarios for large loser patterns. `09_V2_BUILD_IMPACT_MAP.md` maps realized PnL, fee/funding net PnL accounting, large winner/loser attribution, and LAB residual exposure to the paper/backtest MVP lane.
- LAB hedge failure: `legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md` captures the protective long close, residual short exposure, and approximately 80% pump. Phase 2M maps the case into five typed mirror outcomes, but its outcome matrix states that hedge state, residual exposure, PnL, fees, funding, OI, liquidation map, orderbook depth, and squeeze risk are not modeled yet.
- Phase 2P integration: `historical_pnl_replay_wiring/01_LEGACY_FAILURE_EVIDENCE.md` says the richer historical-PnL audit work, including read-only Binance account-history pull, per-trade aggregation, per-day/per-symbol buckets, fees/funding/commission aggregation, large winner/loser buckets, confidence-bucket comparison, trainer-decision join, and balance snapshots, is explicitly out of scope. The harness stores only `(legacy_realized_trade_evidence_pointer, PaperExecutionLedgerEntry)` comparison rows.
- Test evidence: `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py` defines disallowed market fields including `pnl`, `realized_pnl`, `quantity`, `price`, `fees`, `funding`, `hedge_state`, `residual_exposure`, and `squeeze_risk`, then asserts the harness does not introduce them.

## Findings

1. The 30-day audit is partial/local-only, not a completed 30-day trade audit.

   The audit explicitly has no read-only Binance pull, no income rows, no trade rows, and no order rows. This blocks any claim that V2 requirements are derived from a complete 30-day realized-trade evidence set.

2. PnL by symbol/day is unavailable.

   The day and symbol tables contain only `NO_DATA`, so repeated realized losses, per-symbol concentration, and day-level drawdown or loss clustering cannot be verified.

3. Fee/funding drag is unavailable.

   The fee/funding/commission artifact contains only `NO_DATA`; there is no net PnL accounting evidence or basis for fee/funding drag requirements beyond a stated requirement.

4. Large winner/loser and trainer-decision attribution is not integrated.

   The current artifacts do not join realized outcomes to `prediction_id`, `decision_id`, `risk_decision_id`, `feature_snapshot_id`, confidence, freshness, or reason codes. Scenario names such as BTC winner, ETH winner, and LAB loser are deterministic fixture labels, not outcome-derived rankings.

5. LAB hedge failure is captured but not behaviorally modeled.

   Phase 2M documents the required variants and emits typed mirror replay rows, but explicitly defers hedge state, residual exposure, position size, partial close, PnL, fee/funding, OI, liquidation, orderbook, and squeeze-risk modeling. That is enough for traceability, not enough for a residual-exposure risk/backtest requirement proof.

6. Current Phase 2P tests enforce the absence of fields needed for this integration.

   The historical replay wiring harness is intentionally a pure pointer-to-paper-ledger projection. It is safe and deterministic, but its test contract currently blocks PnL, fees, funding, residual exposure, and squeeze-risk fields.

## Concrete blockers

- No completed 30-day read-only audit baseline: `income_rows`, `trade_rows`, and `order_rows` are all zero.
- No PnL by day or PnL by symbol data beyond `NO_DATA`.
- No fee/funding/commission aggregation beyond `NO_DATA`.
- No realized large winner/loser ranking joined to trainer, decision, risk, or feature lineage.
- No typed historical outcome contract for gross PnL, fees, funding, net PnL, timestamp, quantity/notional, or unavailable markers.
- No typed LAB residual-exposure contract for hedge leg, remaining net exposure, partial/full close, squeeze/liquidity warnings, or alternate paper outcome.
- Existing historical replay tests assert that the required market and residual-exposure fields must not exist.

## Proposed non-live autofix tasks

1. Add a non-live `HistoricalTradeOutcome` value object in test/domain scope with source pointer, symbol, event timestamp, side/action/open-close marker, signed gross realized PnL, fees, funding, net PnL, quantity/notional or explicit unavailable markers, and lineage IDs where available.

2. Add a pure aggregation assembler for per-day PnL, per-symbol PnL, fee/funding/commission drag, largest winners/losers, and no-data status. It must operate only on local deterministic fixtures or supplied read-only artifact rows.

3. Add a pure attribution assembler joining historical outcomes to `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, trainer confidence/freshness, paper ledger action/reason, and replay step IDs.

4. Extend LAB replay fixtures with a non-live residual-exposure outcome model: hedge leg role, close intent, net exposure before/after close, residual short size marker, adverse move marker, and expected safe alternatives. Keep all values deterministic and fixture-local.

5. Update historical replay wiring tests to continue forbidding Redis, network, exchange, secret, and live-gate behavior while allowing and asserting the new pure PnL/outcome/residual-exposure fields.

6. Add a no-data regression fixture matching the current audit artifacts so the integration reports `partial/local-only` honestly when no read-only baseline exists, and add separate populated fixtures for symbol/day PnL, fee/funding drag, large loser attribution, and LAB hedge failure.

7. Add a read-only artifact parser task that consumes existing `claude_worklog/historical_pnl_audit/*.md` tables without contacting Binance, mutating Redis, or touching `/home/wali/Desktop/AI BOT`, then emits deterministic integration evidence under the rebuild worklog.

## Safety notes

The block is functional completeness, not a live-safety failure. The inspected Phase 2M and Phase 2P work preserves non-live boundaries, uses deterministic fixtures, and does not introduce exchange, Redis, live service, deployment, leverage, margin, or live-trading behavior.
