# Codex Parallel Review: Replay Backtest Runner MVP

Review timestamp: 2026-05-09T04:23:32-04:00

Scope inspected:
- `v2/backend/app/domain/replay_backtest_runner/`
- `v2/backend/app/services/replay_backtest_runner/`
- `v2/backend/app/composition/replay_backtest_runner/`
- `v2/backend/app/api/v1/replay.py`
- `v2/backend/app/services/replay_runner.py`
- `v2/backend/tests/unit/domain/replay_backtest_runner/`
- `v2/backend/tests/unit/services/replay_backtest_runner/`
- `v2/backend/tests/unit/composition/replay_backtest_runner/`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/`
- `claude_worklog/historical_pnl_audit/`

## Decision

CODEX_PARALLEL_REVIEW_BLOCKED

The implemented replay/backtest runner is not ready for the requested MVP acceptance scope. It is a pure value-object plus assembler/composition surface that mirrors paper execution ledger decisions into replay steps and count summaries. That narrow surface is consistent with the 2I.A/2I.B/2I.C planning specs, but the review topic asks for replay input contracts, backtest output metrics, PnL/drawdown calculation, historical PnL comparison, and large winner/loser attribution. Those accounting and comparison capabilities are absent.

No live service, Redis, order, leverage, deployment, or live-trading action was performed.

## Findings

### Blocker 1: Backtest output metrics do not include PnL, drawdown, fees, or return fields

Evidence:
- `v2/backend/app/domain/replay_backtest_runner/summary.py` defines only replay summary identifiers, timestamps, step counts, reason counts, and `live_blocked`.
- `v2/backend/app/services/replay_backtest_runner/service.py` aggregates only step/reason counts in `assemble_replay_backtest_summary`.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/02_PHASE_2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_SPEC.md`, `10_PHASE_2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_SPEC.md`, and `18_PHASE_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_SPEC.md` explicitly say this phase does not compute PnL, quantity, price, fees, slippage, or risk-adjusted return.

Impact:
- The MVP cannot report gross/net PnL, realized/unrealized PnL, fee/funding drag, win/loss totals, max drawdown, or equity curve values.

Proposed non-live autofix task:
- Add a new pure, fixture-driven backtest accounting domain/service under `v2/backend/app/domain/backtest_accounting/` and `v2/backend/app/services/backtest_accounting/` that accepts typed non-live fills or ledger events and returns frozen metrics including gross_pnl, net_pnl, fees, funding, commissions, equity_curve, max_drawdown, win_count, loss_count, largest_winner, largest_loser, and per-symbol aggregates. Do not wire to exchanges, Redis, or live execution.

### Blocker 2: Replay input contracts do not contain price, size, side, fee, funding, or close/open semantics needed for PnL

Evidence:
- `ReplayBacktestStep` fields are limited to lineage ids, symbol, timestamp, mirrored action/reason, input paper action/reason, and `live_blocked`.
- `PaperExecutionLedgerEntry` fields are also limited to lineage ids, symbol, ledger timestamp, mirrored allow/deny action/reason, input risk action/reason, and `live_blocked`.
- There is no typed input contract for fills, positions, mark prices, funding/commission income, or trade lifecycle events.

Impact:
- PnL and drawdown cannot be computed from the replay runner's current inputs without inventing data outside the contract.

Proposed non-live autofix task:
- Introduce a separate non-live `BacktestInputEvent` or `BacktestFillEvent` value object with required numeric fields for symbol, side, quantity, entry/exit/mark price, fee, funding, event timestamp, and lineage ids. Add strict decimal/string numeric validation and unit fixtures only.

### Blocker 3: Historical PnL comparison is unavailable because the audit data is partial/local-only and contains `NO_DATA`

Evidence:
- `claude_worklog/historical_pnl_audit/03_30D_REALIZED_PNL_BY_DAY.md` contains only `NO_DATA`.
- `claude_worklog/historical_pnl_audit/04_30D_PNL_BY_SYMBOL.md` contains only `NO_DATA`.
- `claude_worklog/historical_pnl_audit/05_30D_FEES_FUNDING_COMMISSION.md` contains only `NO_DATA`.
- `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md` is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.

Impact:
- There is no authoritative historical baseline for replay-vs-realized comparison, and no acceptance threshold can be evaluated.

Proposed non-live autofix task:
- Add fixture-based historical PnL comparison tests that consume sanitized local audit artifacts and explicitly skip or block when audit tables contain `NO_DATA`. Keep live Binance/API pulling out of the autofix path.

### Blocker 4: Large winner/loser attribution is not implemented

Evidence:
- `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md` contains only `NO_DATA`.
- Current replay steps preserve lineage ids (`paper_trade_id`, `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`) but no realized PnL amount, outcome rank, trainer confidence, feature freshness, or attribution reason.
- `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md` requires comparing large losers to trainer confidence and feature freshness and requiring replay/backtest scenarios for large loser patterns, but the implemented runner has no such scenario/accounting layer.

Impact:
- The MVP cannot explain which decisions produced the largest winners/losers, cannot rank outcomes by PnL, and cannot compare loss events to trainer or feature-state evidence.

Proposed non-live autofix task:
- Add a pure attribution report service that joins non-live backtest outcome rows to preserved lineage ids and emits largest winners/losers with symbol, pnl, fees, side, decision_id, prediction_id, feature_snapshot_id, risk_decision_id, and optional confidence/freshness fields when present in fixtures.

### Blocker 5: API and legacy replay runner surfaces remain scaffold-only

Evidence:
- `v2/backend/app/api/v1/replay.py` is an OPTIONS metadata shim with `milestone_d_status: skeleton`.
- `v2/backend/app/services/replay_runner.py` is a one-line placeholder.
- `v2/backend/app/domain/replay/deterministic.py` is a one-line placeholder.

Impact:
- There is no callable endpoint or runner orchestration that accepts replay inputs, executes a backtest pass, and emits the required output metrics. This may be acceptable for 2I.A-C, but it is not enough for the requested Replay Backtest Runner MVP review topic.

Proposed non-live autofix task:
- Add a non-live runner orchestration service that accepts in-memory fixture inputs, uses the existing replay step assembler for lineage/mirror counts, calls the new accounting service for metrics, and returns a typed report object. Keep API wiring separate until the pure service is validated.

## Positive observations

- The current 2I.A-C implementation keeps the live-blocked invariant explicit on run, step, summary, and composition surfaces.
- The assembler preserves core lineage ids from paper ledger entries into replay steps.
- The summary count partition invariants are enforced by the domain object and assembled deterministically.
- The current implementation does not import Redis or live exchange adapters in the replay_backtest_runner domain/service/composition layers.

## Verification notes

- I did not run tests, start services, touch Redis, or perform network/API actions in order to preserve read-only review constraints.
- Review was performed by static inspection of the requested source, test, and worklog paths.
