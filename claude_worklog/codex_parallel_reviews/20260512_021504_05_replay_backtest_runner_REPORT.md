# Codex Parallel Review: Replay Backtest Runner MVP

Verdict: BLOCKED for the requested review checklist.

The implemented 2I replay/backtest runner is a pure non-live mirror assembler. It validates replay run/step/summary contracts, carries lineage from paper ledger entries, and aggregates allow/deny reason counts. It does not implement financial backtest mechanics: no price/quantity/fee/funding inputs, no PnL, no drawdown, no historical PnL comparison math, and no large winner/loser attribution.

Validation run:

- Command: `PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/domain/replay_backtest_runner v2/backend/tests/unit/services/replay_backtest_runner v2/backend/tests/unit/composition/replay_backtest_runner v2/backend/tests/unit/historical_pnl_replay_wiring v2/backend/tests/unit/replay_case_lab_hedge_unwind v2/backend/tests/unit/decision_explainability_replay_backtest_projection`
- Result: `164 passed in 0.46s`
- No Redis writes, service restarts, order placement, leverage/margin changes, live trading enablement, or deploy actions were performed.

## Scope reviewed

- `v2/backend/app/domain/replay_backtest_runner/{run.py,step.py,summary.py}`
- `v2/backend/app/services/replay_backtest_runner/service.py`
- `v2/backend/app/composition/replay_backtest_runner/runtime.py`
- `v2/backend/app/api/v1/replay.py`
- `v2/backend/app/services/replay_runner.py`
- Replay, historical PnL wiring, LAB hedge unwind, and decision explainability projection tests under `v2/backend/tests`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl`
- `claude_worklog/historical_pnl_audit`

## Findings

1. BLOCKER: Backtest output metrics are only taxonomy counts, not financial metrics.

   `ReplayBacktestSummary` contains `total_steps_count`, `record_allow_steps_count`, `record_deny_steps_count`, and mirror reason partitions only. It has no fields for gross/net PnL, realized/unrealized PnL, drawdown, win rate, expectancy, fees, funding, slippage, exposure, notional, or symbol-level aggregates. The assembler service correspondingly only counts step actions/reasons.

   Evidence:
   - `v2/backend/app/domain/replay_backtest_runner/summary.py`
   - `v2/backend/app/services/replay_backtest_runner/service.py`
   - `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/10_PHASE_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_SPEC.md` explicitly says the service does not compute PnL, quantity, price, fees, or slippage.
   - `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/18_PHASE_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_SPEC.md` explicitly excludes PnL, position sizing, fees, slippage, and risk-adjusted return.

2. BLOCKER: PnL and drawdown calculation are absent.

   No reviewed replay/backtest runner value object, service, composition root, or harness computes a PnL series or equity curve, so drawdown cannot be derived. The historical PnL wiring harness intentionally rejects market fields including `pnl`, `realized_pnl`, `size`, `quantity`, `price`, `fees`, `slippage`, and `funding`.

   Evidence:
   - `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py`
   - `v2/backend/tests/unit/decision_explainability_replay_backtest_projection/test_decision_explainability_replay_backtest_projection.py`

3. BLOCKER: Historical PnL comparison is fixture/pointer based, not numeric comparison.

   The historical wiring carries `legacy_realized_trade_evidence_pointer` alongside a V2 paper ledger entry. It does not compare legacy realized PnL values to V2 replay/backtest PnL values. Current audit artifacts are partial/local-only with `NO_DATA` for realized PnL by day, PnL by symbol, fees/funding/commission, and large winners/losers.

   Evidence:
   - `v2/backend/tests/unit/historical_pnl_replay_wiring/harness.py`
   - `claude_worklog/historical_pnl_audit/03_30D_REALIZED_PNL_BY_DAY.md`
   - `claude_worklog/historical_pnl_audit/04_30D_PNL_BY_SYMBOL.md`
   - `claude_worklog/historical_pnl_audit/05_30D_FEES_FUNDING_COMMISSION.md`
   - `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md`
   - `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md`

4. BLOCKER: Large winner/loser attribution is not implemented.

   Replay steps carry `paper_trade_id`, `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, symbol, timestamp, action, and reason. That is useful lineage, but there is no trade PnL, large winner/loser classification, feature attribution join, trainer confidence comparison, or freshness comparison. The audit requirements explicitly call for comparing large losers to trainer confidence and feature freshness and requiring replay/backtest scenarios for large loser patterns; the current artifacts do not satisfy that.

   Evidence:
   - `v2/backend/app/domain/replay_backtest_runner/step.py`
   - `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md`
   - `claude_worklog/historical_pnl_audit/09_V2_BUILD_IMPACT_MAP.md`

5. BLOCKER: There is no runnable replay API/service surface for input contract submission.

   The real `/replay` API remains scaffold-only OPTIONS metadata, and `v2/backend/app/services/replay_runner.py` is still a placeholder. The implemented runner can be called in-process through domain/service/composition modules, but there is no endpoint, request schema, persistence-free CLI, or application service accepting replay input contracts for a backtest run.

   Evidence:
   - `v2/backend/app/api/v1/replay.py`
   - `v2/backend/app/services/replay_runner.py`

## Passing coverage

- Replay input value objects enforce identifiers, uppercase symbol, timestamp sanity, run mode membership, live-blocked true, action/reason membership, and cross-field mirror invariants.
- Service layer validates paper ledger entry type, run type, clock behavior, symbol match, derived id lengths, step tuple type, step element type, and run id match.
- Composition root captures the clock and exposes `assemble_step` and `assemble_summary` closures without Redis/FastAPI side effects.
- LAB hedge unwind tests cover typed mirror sequences for legacy, keep hedge, close short, reduce short, and block hedge close outcomes.
- Historical PnL wiring tests prove lineage pointer carry-over into V2 paper ledger entries, but not numeric PnL comparison.

## Proposed non-live autofix tasks

1. Add non-live replay/backtest market input contracts.

   Create frozen value objects for historical replay bars/fills/trades with symbol, event timestamps, side/direction, quantity, entry/exit price, fees, funding, slippage, and legacy evidence pointer. Keep live-blocked true and forbid exchange/order side effects.

2. Add pure PnL and drawdown calculator service.

   Implement deterministic gross PnL, fee/funding/slippage-adjusted net PnL, cumulative equity curve, peak equity, max drawdown absolute/percent, win/loss counts, average win/loss, largest winner, and largest loser. Use `Decimal` or explicit integer quote units; avoid floats for money.

3. Extend replay summary with financial metrics or add a separate financial summary object.

   Preserve existing mirror summary compatibility, but add a non-live financial summary keyed by `replay_run_id` and symbol. Include per-symbol and aggregate totals plus lineage to source trade ids and decisions.

4. Add historical comparison records.

   Join legacy realized PnL evidence to V2 replay financial outputs and emit per-trade/per-symbol/per-day deltas. Include comparison status fields such as preserved_winner, reduced_loser, worsened_loser, missing_source, and no_data.

5. Add large winner/loser attribution.

   Classify top-N winners/losers from numeric PnL outputs and attach `prediction_id`, `decision_id`, `feature_snapshot_id`, model version/confidence/freshness fields where available. Add tests for stale features, low confidence, duplicate provenance, LAB hedge unwind residual exposure, and winner preservation.

6. Add a non-live runner facade.

   Implement a pure in-process runner or CLI that accepts replay input contracts and returns the mirror summary plus financial summary. Do not write Redis, place orders, change leverage/margin, restart services, or enable live trading.

7. Replace `NO_DATA` historical audit artifacts with deterministic local fixtures or readonly pulled evidence.

   Keep any exchange pull readonly and optional. For CI, use fixture files that contain realistic winners/losers, fees/funding, and daily/symbol PnL rows so the replay comparison can be tested without secrets or network access.
