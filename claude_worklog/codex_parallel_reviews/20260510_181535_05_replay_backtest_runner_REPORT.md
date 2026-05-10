# Codex Parallel Review - Replay Backtest Runner MVP

Review timestamp: 2026-05-10 18:15:35
Reviewer: local Codex CLI
Scope: read-only review of `v2/backend/app`, `v2/backend/tests`, `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl`, and `claude_worklog/historical_pnl_audit`.

## Decision

BLOCKED for Replay Backtest Runner MVP readiness.

The implemented replay runner is non-live and deterministic, and its own unit coverage passes. However, the reviewed surface is only a paper-ledger mirror/count assembler. It does not implement the requested MVP checks for backtest output metrics, PnL/drawdown calculation, historical PnL comparison against real audit rows, or large winner/loser attribution.

## Evidence Reviewed

- `v2/backend/app/domain/replay_backtest_runner/run.py`
- `v2/backend/app/domain/replay_backtest_runner/step.py`
- `v2/backend/app/domain/replay_backtest_runner/summary.py`
- `v2/backend/app/services/replay_backtest_runner/service.py`
- `v2/backend/app/composition/replay_backtest_runner/runtime.py`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`
- `v2/backend/tests/unit/domain/replay_backtest_runner/`
- `v2/backend/tests/unit/services/replay_backtest_runner/`
- `v2/backend/tests/unit/composition/replay_backtest_runner/`
- `v2/backend/tests/unit/historical_pnl_replay_wiring/`
- `v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/`
- `claude_worklog/historical_pnl_audit/`

## Passing Observations

- Replay input contracts enforce typed frozen value objects, uppercase symbol validation, run time monotonicity, identifier constraints, and `live_blocked=True`.
- Step assembly preserves lineage from paper ledger entries: `paper_trade_id`, `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`, and `symbol`.
- Summary assembly deterministically aggregates step counts and enforces partition-sum invariants.
- Non-live safety posture is strong for the reviewed runner surface: no Redis, HTTP, FastAPI registration, exchange order placement, leverage/margin mutation, or live enablement was observed.
- Verification command passed: `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider v2/backend/tests/unit/domain/replay_backtest_runner v2/backend/tests/unit/services/replay_backtest_runner v2/backend/tests/unit/composition/replay_backtest_runner v2/backend/tests/unit/historical_pnl_replay_wiring v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py -q` -> `146 passed in 0.46s`.

## Blockers

1. No backtest PnL or drawdown output exists in the replay runner contract.
   - `ReplayBacktestSummary` contains only count fields: `total_steps_count`, allow/deny counts, and mirror reason counts in `v2/backend/app/domain/replay_backtest_runner/summary.py:32`.
   - `assemble_replay_backtest_summary` only counts step actions/reasons and emits those counts in `v2/backend/app/services/replay_backtest_runner/service.py:186`.
   - There are no fields for realized PnL, cumulative PnL, fees, funding, drawdown, equity curve, win rate, loss rate, expectancy, average winner, average loser, profit factor, max consecutive losses, or per-symbol PnL.

2. PnL/drawdown calculation is explicitly out of scope in the implementation specs.
   - Phase 2I.A states the package does not compute PnL, quantity, price, fees, or slippage in `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/02_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_SPEC.md:5`.
   - Phase 2I.B repeats that the assembler service does not compute PnL, quantity, price, fees, or slippage in `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/10_PHASE_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_SPEC.md:9`.
   - The historical PnL wiring tests explicitly disallow `pnl`, `realized_pnl`, `price`, `fees`, `slippage`, `funding`, `hedge_state`, `residual_exposure`, and `squeeze_risk` fields in `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:33` and assert the fields are absent at line 157.

3. Historical PnL comparison is fixture-only and not tied to actual historical audit data.
   - The historical audit reports `NO_DATA` for realized PnL by day, PnL by symbol, largest losers, and largest winners in `claude_worklog/historical_pnl_audit/03_30D_REALIZED_PNL_BY_DAY.md:3`, `04_30D_PNL_BY_SYMBOL.md:8`, and `06_LARGE_WINNERS_AND_LOSERS.md:13`.
   - The audit marker is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY` in `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md:1`.
   - `build_historical_30d_proof` uses deterministic fixture rows and states the mode is `offline_deterministic_historical_fixture` in `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:191`.
   - The proof limitations state Binance account-history credentials were unavailable and realized PnL values are fixture values in `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:241`.

4. Large winner/loser attribution is insufficient for MVP review.
   - The fixture proof marks preserved winners and reduced/rejected losers, but attribution is limited to string reasons, confidence, and lineage IDs in `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:80`.
   - There is no computed attribution tying large winners/losers to trainer confidence, feature freshness, fees/funding drag, drawdown contribution, regime, duplicate signal, hedge residual exposure, or per-symbol contribution.
   - The historical audit requirement says to compare large losers to trainer confidence and feature freshness and require replay/backtest scenarios for large loser patterns in `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md:26`, but the current runner does not implement those metrics.

5. The replay runner is not yet a backtest runner in the operational sense.
   - Steps mirror paper ledger decisions and reason codes, but they do not replay market prices, fills, position state, exposure, entry/exit pairs, or account equity.
   - The backtest output can currently answer "what would have been allowed or denied by the paper/risk path"; it cannot answer "what PnL, drawdown, and large-trade attribution did the strategy produce."

## Proposed Non-Live Autofix Tasks

1. Add an offline-only backtest metrics domain package.
   - Create immutable value objects for `BacktestTradePnL`, `BacktestEquityPoint`, `BacktestDrawdown`, `BacktestAttributionRow`, and `BacktestMetricsSummary`.
   - Include fields for gross PnL, fees, funding, net PnL, cumulative PnL, peak equity, drawdown absolute/percent, win/loss counts, average winner/loser, profit factor, and per-symbol aggregation.
   - Keep `live_blocked=True` and forbid Redis, HTTP, exchange clients, live adapters, order placement, leverage, and margin changes.

2. Add an offline metrics assembler that consumes explicit fixture inputs only.
   - Inputs should be typed historical trade/fill rows with symbol, side, quantity, entry/exit price, realized PnL components, fees, funding, timestamps, and lineage IDs.
   - Compute net PnL and drawdown deterministically using Decimal, not float.
   - Reject missing lineage and invalid timestamps before computing metrics.

3. Extend historical PnL comparison beyond marker-only fixtures.
   - Parse committed historical audit tables when present and fail closed when audit rows are `NO_DATA`.
   - Emit comparison rows for legacy realized PnL vs V2 paper/backtest PnL by trade, day, and symbol.
   - Preserve the current no-credential behavior, but mark comparison quality as `fixture_only`, `partial_local_only`, or `audit_backed`.

4. Add large winner/loser attribution outputs.
   - Emit top-N winners and losers with contribution to net PnL, drawdown contribution, symbol, side, trainer confidence, feature freshness flags, decision/risk IDs, and reason codes.
   - Add tests for LAB hedge-unwind loser attribution and preserved winner attribution.

5. Add MVP readiness tests.
   - Unit-test PnL arithmetic, fee/funding treatment, drawdown peak/trough detection, per-symbol aggregation, large winner/loser ranking, and historical audit `NO_DATA` blocked readiness.
   - Keep tests non-live and run them with cache disabled where possible.

## Safety Notes

No live services were restarted. No Redis writes or key deletes were performed. No orders were placed or cancelled. No leverage or margin settings were changed. No live trading was enabled. No deployment was performed. Secrets were not exposed.
