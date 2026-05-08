# Codex Parallel Review - Historical PnL / Trade Audit Integration

## Review Result

BLOCKED. The Phase 2 historical-PnL integration is present only as non-live typed mirror fixtures and evidence pointers. It does not yet integrate actual 30-day account-history PnL, symbol/day buckets, fee/funding/commission drag, or realized-trade rows into V2 risk/backtest evidence.

## Scope Inspected

- `claude_worklog/historical_pnl_audit/00_AUDIT_INDEX.md` through `10_GO_NO_GO.md`
- `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md`
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/03_LEGACY_EVIDENCE_AND_FAILURE_MAPPING.md`
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/06_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/08_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/01_LEGACY_FAILURE_EVIDENCE.md`
- `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/02_TYPED_INPUT_FIXTURE_SPEC.md`
- `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/06_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/historical_pnl_replay_wiring/08_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/01_LEGACY_FAILURE_EVIDENCE.md`
- `claude_worklog/phase2_core_rebuild/aggregate_evidence_rollup_harness/08_CODEX_REVIEW.md`
- `v2/backend/tests/unit/historical_pnl_replay_wiring/fixtures.py`
- `v2/backend/tests/unit/historical_pnl_replay_wiring/harness.py`
- `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py`

## Findings

### 1. 30-day audit is partial local-only, not account-history backed

`claude_worklog/historical_pnl_audit/01_DATA_SOURCE_STATUS.md` reports:

- `requested_days: 30`
- `binance_pull_requested: False`
- `binance_api_key_env_present: False`
- `binance_api_secret_env_present: False`
- `symbols_requested_for_trade_order_history: none`

`02_BINANCE_READONLY_PULL_SUMMARY.md` reports zero income, trade, and order rows, with `BINANCE_PULL_NOT_REQUESTED`. `10_GO_NO_GO.md` is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.

Impact: the review cannot certify the 30-day historical audit as integrated evidence. The current packet is an index and local-evidence scaffold, not a completed 30-day realized-trade audit.

### 2. PnL by symbol/day has no usable evidence rows

`03_30D_REALIZED_PNL_BY_DAY.md` contains only `NO_DATA | 0`. `04_30D_PNL_BY_SYMBOL.md` contains only `NO_DATA | 0`. `06_LARGE_WINNERS_AND_LOSERS.md` contains only `NO_DATA | 0` for both largest losers and largest winners.

Impact: V2 cannot derive symbol risk, loss-streak behavior, winner/loser replay cases, or confidence/performance joins from actual 30-day realized PnL. The current Phase 2P fixture names scenarios such as BTC winner, ETH winner, and LAB loser, but those are deterministic labels, not audited account-history buckets.

### 3. Fee/funding/commission drag is not integrated

`05_30D_FEES_FUNDING_COMMISSION.md` contains only `NO_DATA | 0`. Phase 2P explicitly forbids PnL, fees, funding, sizing, price, and market-microstructure fields in the test-only historical-PnL replay wiring. The unit test `test_harness_does_not_introduce_pnl_or_size_or_price_or_fees_or_funding_field` enforces that absence.

Impact: paper ledger and replay outputs currently cannot answer whether fees, funding, or commissions explain material net-PnL drag. This is a direct gap against the review topic.

### 4. LAB hedge failure is integrated as a pointer/replay fixture, not as residual-exposure risk logic

The LAB failure case is captured in `claude_worklog/legacy_failure_cases/2026_05_LAB_HEDGE_UNWIND_SHORT_SQUEEZE_FAILURE.md` and Phase 2M has a passing typed replay fixture. Phase 2P also includes a `LABUSDT` loser-short historical-PnL scenario with deterministic `legacy_realized_trade_evidence__lab_hedge_unwind_squeeze__step_N` pointers.

However, Phase 2M and Phase 2P both state that they do not introduce PnL, hedge state, residual exposure, or squeeze-risk computation. Phase 2M also documents the current typed limitation that close-short and reduce-short collapse to the same typed mirror sequence.

Impact: LAB failure integration is sufficient as non-live regression evidence, but insufficient as risk/backtest behavior proving V2 can quantify or block the residual short exposure after protective hedge close.

### 5. V2 risk/backtest requirements are derived from evidence, but remain mostly future work for real PnL

`08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md` correctly identifies repeated losses, fee/funding drag, trainer-confidence comparison, hedge-unwind residual exposure, shorting bottoms / longing tops, default-deny stale-data behavior, and replay/backtest large-loser scenarios. `09_V2_BUILD_IMPACT_MAP.md` maps realized PnL by symbol, fee/funding drag, large winners/losers, trainer/orchestrator evidence, and LAB hedge unwind into the paper/backtest MVP lane.

Phase 2P and Phase 2Q preserve typed lineage and cross-source evidence rollups, but their own specs explicitly exclude real PnL aggregation, fee/funding aggregation, confidence-bucket performance joins, account-history pulls, and hedge/residual-exposure modeling.

Impact: the requirements are documented and directionally correct, but the implemented evidence is not yet strong enough to certify historical PnL / trade audit integration.

## Passing Evidence

- `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS` is present.
- `PHASE2P_HISTORICAL_PNL_REPLAY_WIRING_CODEX_PASS` is present.
- `V2_BACKTEST_AND_PAPER_MVP_READY` and `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS` are present.
- Historical-PnL replay wiring is non-live, deterministic, test-only, paper-mode gated, and preserves lineage through `RiskDecisionRecord` and `PaperExecutionLedgerEntry`.
- No live action, Redis mutation, service restart, exchange call, leverage/margin change, deployment, or live gate flip was observed in this review.

## Blockers

1. No completed read-only 30-day account-history pull is present in `historical_pnl_audit`.
2. PnL by day and PnL by symbol are `NO_DATA`, so no actual historical performance buckets are available.
3. Fee/funding/commission drag is `NO_DATA`, so net-vs-gross PnL drag cannot be audited.
4. Phase 2P historical-PnL replay wiring uses deterministic pointer fixtures only and does not ingest audited trade/income rows.
5. LAB hedge-unwind is replayed as a typed fixture but not yet modeled with residual exposure, hedge-state, squeeze-risk, or PnL impact of hedge kept vs hedge closed.

## Proposed Non-Live Autofix Tasks

1. Add a read-only historical account-history import artifact under `claude_worklog/historical_pnl_audit/` that records the source file path or sanitized pull summary, row counts, date range, symbol set, and schema for income/trade/order rows. Do not call live endpoints unless explicitly authorized by the planner/human read-only policy.
2. Add an offline parser/aggregator test harness that consumes sanitized local CSV/JSON fixtures and emits 30-day realized PnL by day, by symbol, and by symbol/day, with row-count reconciliation back to the source fixture.
3. Add a fee/funding/commission drag aggregator over the same local fixtures, including gross PnL, total commission, total funding, net PnL, and drag ratio by symbol and day.
4. Extend the historical-PnL replay fixture contract to include sanitized realized-trade evidence records in a test-only package, then map each row into `RiskDecisionRecord` / `PaperExecutionLedgerEntry` comparisons without Redis, exchange clients, persistence, or live services.
5. Add a LAB hedge-unwind non-live risk/backtest fixture with explicit before/after net exposure, hedge leg state, protected-vs-unprotected outcome, and PnL delta of hedge kept vs hedge closed. Keep it test-only until the typed domain surface for residual exposure is approved.
6. Add a trainer/decision join report that links realized losers/winners to `prediction_id`, `feature_snapshot_id`, confidence/freshness status, and risk decision reason where evidence exists; emit `NO_JOIN_DATA` explicitly when the source rows cannot support the join.

CODEX_PARALLEL_REVIEW_BLOCKED
