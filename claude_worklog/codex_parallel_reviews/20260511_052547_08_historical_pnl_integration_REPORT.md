# Codex Parallel Review - Historical PnL / Trade Audit Integration

## Decision

BLOCKED for quantitative historical PnL integration readiness.

The non-live Phase 2 fixture path is integrated and reviewed, but the 30-day exchange audit itself is not populated. The audit artifacts still record a local-only partial state with zero Binance income/trade/order rows, so V2 cannot yet derive real PnL by day, PnL by symbol, fee/funding/commission drag, large winners/losers, or trainer-vs-realized-trade conclusions from actual 30-day account history.

## Evidence Reviewed

- `claude_worklog/historical_pnl_audit/00_AUDIT_INDEX.md`
- `claude_worklog/historical_pnl_audit/01_DATA_SOURCE_STATUS.md`
- `claude_worklog/historical_pnl_audit/02_BINANCE_READONLY_PULL_SUMMARY.md`
- `claude_worklog/historical_pnl_audit/03_30D_REALIZED_PNL_BY_DAY.md`
- `claude_worklog/historical_pnl_audit/04_30D_PNL_BY_SYMBOL.md`
- `claude_worklog/historical_pnl_audit/05_30D_FEES_FUNDING_COMMISSION.md`
- `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md`
- `claude_worklog/historical_pnl_audit/07_LEGACY_TRAINER_DECISION_EVIDENCE.md`
- `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md`
- `claude_worklog/historical_pnl_audit/09_V2_BUILD_IMPACT_MAP.md`
- `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md`
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/02_REPLAY_CASE_OUTCOME_MATRIX.md`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/08_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/09_CODEX_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/06_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/08_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/09_CODEX_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/08_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/09_CODEX_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/03_LEGACY_EVIDENCE_AND_FAILURE_MAPPING.md`
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md`
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/09_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md`

## Check Results

### 30-Day Audit Status

BLOCKED. `01_DATA_SOURCE_STATUS.md` records `requested_days: 30`, `binance_pull_requested: False`, no Binance API key/secret env presence, and no requested symbols for trade/order history. `02_BINANCE_READONLY_PULL_SUMMARY.md` records `income_rows: 0`, `trade_rows: 0`, `order_rows: 0`, and the gap `BINANCE_PULL_NOT_REQUESTED`. `10_GO_NO_GO.md` is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.

### PnL By Symbol / Day

BLOCKED. `03_30D_REALIZED_PNL_BY_DAY.md` contains only `NO_DATA | 0`. `04_30D_PNL_BY_SYMBOL.md` contains only `NO_DATA | 0`. No real per-day or per-symbol 30-day realized PnL evidence is available to validate symbol risk, loss streaks, large loser replay cases, or trainer attribution against realized trades.

### Fee / Funding Drag

BLOCKED. `05_30D_FEES_FUNDING_COMMISSION.md` contains only `NO_DATA | 0`. No real fee, funding, or commission drag can be assessed. Current Phase 2 paper-ledger and replay artifacts explicitly avoid introducing fee/funding/PnL computation at this stage.

### LAB Hedge Failure Integration

PARTIAL PASS. The LAB hedge-unwind / short-squeeze failure is captured in `legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`, including the residual short after protective long close and the approximately 80% adverse pump. Phase 2M integrates it as a non-live typed replay fixture with five outcome variants: legacy action, keep hedge, close short, reduce short, and block hedge close. `replay_case_lab_hedge_unwind/09_CODEX_GO_NO_GO.md` contains `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS`.

The limitation is explicit and still material: Phase 2M typed surfaces do not model hedge state, residual exposure, position size, PnL, slippage, fees, funding, OI, liquidation map, orderbook depth, or squeeze risk. Outcomes `close short` and `reduce short` collapse to the same typed mirror sequence, distinguished only by replay-run namespacing.

### V2 Risk / Backtest Requirements Derived From Evidence

PARTIAL PASS. `08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md` correctly lists required V2 requirements: repeated realized losses, fee/funding drag, comparison of large losers to trainer confidence and feature freshness, hedge-unwind residual exposure detection, shorting bottoms / longing tops, default-deny on stale/missing data, and replay/backtest cases for large loser patterns.

`09_V2_BUILD_IMPACT_MAP.md` maps realized PnL by symbol, fees/funding/commission drag, large winners/losers, trainer/orchestrator evidence, and LAB hedge unwind into the `paper_backtest_mvp` lane. The consolidation packet confirms the typed surfaces needed for non-live replay and paper proof are present, and Phase 2P / 2Q certify deterministic replay wiring and aggregate roll-up harnesses.

The missing piece is still evidence depth, not fixture plumbing: no populated 30-day realized-trade dataset exists to prove the requirements against actual historical account behavior.

## Concrete Blockers

1. The 30-day Binance read-only pull has not been performed or materialized: zero income, trade, and order rows.
2. Per-day and per-symbol PnL tables are placeholders only, so no real symbol/day loss concentration can be reviewed.
3. Fee/funding/commission drag is placeholder-only, so net PnL accounting requirements cannot be validated from evidence.
4. Large winners/losers and trainer decision evidence are placeholder-only, so V2 cannot yet compare trainer confidence, feature freshness, and realized outcomes.
5. LAB integration is fixture-complete but not quantitatively complete because current typed surfaces do not express residual exposure, hedge state, partial close size, squeeze risk, or PnL impact.

## Proposed Non-Live Autofix Tasks

1. Add a read-only historical audit ingestion task that only consumes sanitized offline exports or explicitly authorized read-only API output, then writes local audit artifacts without Redis, live services, orders, leverage, margin, or live-gate changes.
2. Add deterministic parser tests for Binance income/trade/order export fixtures covering realized PnL, commission, funding fee, symbol, side, quantity, order id, trade id, and timestamp normalization.
3. Regenerate `03_30D_REALIZED_PNL_BY_DAY.md`, `04_30D_PNL_BY_SYMBOL.md`, `05_30D_FEES_FUNDING_COMMISSION.md`, and `06_LARGE_WINNERS_AND_LOSERS.md` from sanitized fixture data, preserving a clear `NO_DATA` state when inputs are absent.
4. Extend the non-live historical-PnL replay fixture with typed net-PnL summary fields only after the parser fixtures exist: gross realized PnL, commission, funding, net PnL, day bucket, symbol bucket, and evidence pointer.
5. Open a later hedge-risk typing milestone for LAB-specific fields: hedge role, net exposure before/after close, residual short quantity, partial-close ratio, squeeze-risk flags, and hedge-kept versus hedge-closed PnL delta.
6. Add a non-live requirement traceability test proving every row in `08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md` maps to either an implemented typed proof, an explicit out-of-scope marker, or a queued non-live follow-up artifact.

## Safety

This review did not modify `/home/wali/Desktop/AI BOT`, did not read or write Redis, did not restart services, did not place or cancel orders, did not change leverage or margin, did not enable live trading, did not deploy, and did not expose secrets.

CODEX_PARALLEL_REVIEW_BLOCKED
