# Codex Parallel Review: Replay Backtest Runner MVP

Review timestamp: 2026-05-10 12:11:42 local request context
Mode: read-only parallel review; report artifacts only
Decision: BLOCKED

## Scope Reviewed

- `v2/backend/app/domain/replay_backtest_runner/`
- `v2/backend/app/services/replay_backtest_runner/`
- `v2/backend/app/composition/replay_backtest_runner/`
- `v2/backend/tests/unit/domain/replay_backtest_runner/`
- `v2/backend/tests/unit/services/replay_backtest_runner/`
- `v2/backend/tests/unit/composition/replay_backtest_runner/`
- `v2/backend/tests/unit/historical_pnl_replay_wiring/`
- `v2/backend/tests/unit/decision_explainability_replay_backtest_projection/`
- `v2/backend/app/proof/non_live_operational_proof.py`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/`
- `claude_worklog/historical_pnl_audit/`

## Verdict

BLOCKED for Replay Backtest Runner MVP readiness.

The implemented 2I replay/backtest runner is a non-live mirror assembler over paper ledger entries. It correctly preserves lineage and allow/deny reason counts, but it is not yet a backtest runner capable of replay input valuation, PnL/drawdown calculation, historical PnL comparison, or real large winner/loser attribution.

## Findings

1. Replay input contracts do not contain market, fill, or valuation inputs.

   Evidence:
   - `v2/backend/app/domain/replay_backtest_runner/run.py` defines only run id, mode, symbol, start/end timestamps, and `live_blocked`.
   - `v2/backend/app/domain/replay_backtest_runner/step.py` defines lineage ids, symbol, step timestamp, mirrored action/reason fields, and `live_blocked`.
   - `v2/backend/app/domain/paper_execution_ledger/record.py` likewise has no side, quantity, entry price, exit price, mark price, commission, funding, slippage, realized PnL, or equity field.
   - `v2/backend/app/services/replay_backtest_runner/service.py` derives `ReplayBacktestStep` by copying paper ledger lineage and mapping paper ledger reasons into step reasons.

   Impact:
   - The runner can mirror paper ledger decisions, but it cannot replay fills or calculate outcome values.

2. Backtest output metrics are count-only.

   Evidence:
   - `v2/backend/app/domain/replay_backtest_runner/summary.py` exposes total steps, allow/deny counts, reason-partition counts, timestamp, run id, and `live_blocked`.
   - `v2/backend/app/services/replay_backtest_runner/service.py` aggregates only those counts.
   - `v2/backend/app/proof/non_live_operational_proof.py` uses a hard-coded `gross_paper_pnl` string and `max_drawdown_placeholder`.

   Impact:
   - Required backtest metrics such as gross/net PnL, fee/funding drag, slippage, win/loss counts, largest winner, largest loser, equity curve, max drawdown, and per-symbol attribution are absent.

3. PnL and drawdown calculation are intentionally out of 2I scope and have not been added elsewhere in the runner.

   Evidence:
   - The 2I.A, 2I.B, and 2I.C specs explicitly state that these layers do not compute PnL, quantity, price, fees, slippage, risk-adjusted return, or persistence.
   - `v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py` asserts that the historical wiring harness does not introduce `pnl`, `realized_pnl`, `size`, `quantity`, `price`, `fees`, `slippage`, or `funding` fields.
   - `v2/backend/tests/unit/decision_explainability_replay_backtest_projection/test_decision_explainability_replay_backtest_projection.py` forbids `pnl`, `quantity`, `price`, `fee`, `funding`, and related market/context fields from the replay projection envelopes.

   Impact:
   - Current tests protect the lineage-only MVP shape, not the PnL/drawdown requirements in this review topic.

4. Historical PnL comparison remains partial/local-only and fixture-backed.

   Evidence:
   - `claude_worklog/historical_pnl_audit/10_GO_NO_GO.md` contains `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY`.
   - `claude_worklog/historical_pnl_audit/03_30D_REALIZED_PNL_BY_DAY.md`, `04_30D_PNL_BY_SYMBOL.md`, and `05_30D_FEES_FUNDING_COMMISSION.md` contain only `NO_DATA` rows.
   - `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py` states that historical account credentials were unavailable and realized PnL values are deterministic fixture values for workflow validation.

   Impact:
   - The system cannot yet compare replay/backtest output against a reproducible historical PnL baseline.

5. Large winner/loser attribution is not backed by real historical winner/loser rows.

   Evidence:
   - `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md` reports `NO_DATA` for both largest losers and largest winners.
   - `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py` includes deterministic fixture winners and losers, including the LAB hedge unwind case, but those values are not derived from populated historical PnL audit tables.
   - The decision explainability replay projection carries scenario slug and legacy evidence pointers, but deliberately omits confidence, feature freshness, PnL, sizing, and market attribution fields.

   Impact:
   - The MVP cannot prove that actual large historical winners are preserved or actual large historical losers are blocked/reduced with complete attribution.

## Concrete Blockers

- No replay event/fill input contract exists for non-live market outcomes.
- No PnL, fee/funding/slippage, equity, or drawdown fields exist in replay outputs.
- No deterministic PnL/drawdown calculation service exists under the replay/backtest runner.
- Historical audit artifacts are partial local-only and contain `NO_DATA` for PnL by day, PnL by symbol, fees/funding/commission, and large winners/losers.
- Large winner/loser attribution is fixture-described, not calculated from historical rows with model/risk lineage.

## Proposed Non-Live Autofix Tasks

1. Add an offline replay fill/event contract.
   - Include run id, event id, symbol, side, quantity, entry price, exit/mark price, commission, funding, slippage, realized PnL, event timestamp, and lineage ids.
   - Enforce `run_started_ts_ms <= event_ts_ms <= run_ended_ts_ms`.
   - Keep it pure: no Redis writes, HTTP clients, exchange adapters, live order paths, or service restarts.

2. Add a deterministic replay metrics calculator.
   - Produce gross PnL, net PnL, total fees, funding, slippage, win count, loss count, largest winner, largest loser, max drawdown, ending equity, and per-symbol attribution.
   - Use integer minor units or `Decimal` for money values.
   - Preserve lineage to paper trade id, risk decision id, decision id, prediction id, and feature snapshot id.

3. Add non-live PnL/drawdown tests.
   - Cover long winner, short winner, long loser, short loser, fee/funding drag, zero-trade summary, high-water-mark drawdown, malformed money values, and timestamp-window rejection.
   - Keep import-safety tests proving no Redis, HTTP, exchange, scheduler, or live execution dependency is loaded.

4. Replace `NO_DATA` historical audit artifacts with sanitized committed fixture input.
   - Generate realized PnL by day, PnL by symbol, fees/funding/commission, and large winner/loser tables from local fixture files.
   - Keep any real credential pull out of this autofix; use non-secret sanitized fixtures only.

5. Add large winner/loser attribution checks.
   - Attribute top winners/losers to symbol, side, quantity, PnL components, reason code, confidence/freshness metadata where available, prediction id, decision id, risk decision id, and paper trade id.
   - Include the LAB hedge unwind residual-exposure case as a deterministic loser scenario.

## Verification

No test suite was run. This was a read-only source and artifact review followed only by writing the two requested Codex parallel review files.
