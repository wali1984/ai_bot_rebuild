# Codex Parallel Review: Replay Backtest Runner MVP

Review timestamp: 2026-05-10 23:36:24 local request context
Mode: read-only parallel review; report artifacts only
Decision: BLOCKED

## Scope Reviewed

- `v2/backend/app/domain/replay_backtest_runner/`
- `v2/backend/app/services/replay_backtest_runner/`
- `v2/backend/app/composition/replay_backtest_runner/`
- `v2/backend/app/domain/paper_execution_ledger/`
- `v2/backend/app/proof/historical_30d_replay_and_paper_proof.py`
- `v2/backend/tests/unit/domain/replay_backtest_runner/`
- `v2/backend/tests/unit/services/replay_backtest_runner/`
- `v2/backend/tests/unit/composition/replay_backtest_runner/`
- `v2/backend/tests/unit/historical_pnl_replay_wiring/`
- `v2/backend/tests/unit/decision_explainability_replay_backtest_projection/`
- `v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py`
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/`
- `claude_worklog/historical_pnl_audit/`

## Verdict

BLOCKED for Replay Backtest Runner MVP readiness.

The implemented 2I runner is a pure, non-live mirror assembler from paper ledger rows into replay step value objects plus count-only summaries. That surface is import-clean and well-tested for lineage and allow/deny reason partitioning, but it is not yet a backtest runner for PnL, drawdown, historical PnL comparison, or large winner/loser attribution.

## Findings

### 1. Replay input contracts do not carry valuation inputs

`ReplayBacktestRun` contains only run id, mode, symbol, start/end timestamps, and `live_blocked` (`v2/backend/app/domain/replay_backtest_runner/run.py:31-38`). `ReplayBacktestStep` carries lineage ids, symbol, step timestamp, mirrored paper action/reason fields, and `live_blocked` (`v2/backend/app/domain/replay_backtest_runner/step.py:70-85`). It has no side, quantity, fill price, mark price, exit price, fee, funding, slippage, equity, or realized/unrealized PnL inputs.

The upstream `PaperExecutionLedgerEntry` has the same limitation: lineage, symbol, timestamp, action/reason, risk action/reason, and `live_blocked`, but no execution economics (`v2/backend/app/domain/paper_execution_ledger/record.py:91-103`).

Impact: replay input contracts can prove that a risk/paper decision was mirrored, but cannot replay fills or value outcomes.

### 2. Backtest output metrics are count-only

`ReplayBacktestSummary` exposes `total_steps_count`, allow/deny counts, mirror reason counts, timestamp, ids, and `live_blocked` (`v2/backend/app/domain/replay_backtest_runner/summary.py:32-45`). The assembler only derives those counts in a single pass (`v2/backend/app/services/replay_backtest_runner/service.py:186-225`).

Missing required metrics include gross PnL, net PnL, fees, funding, slippage, win/loss counts, largest winner, largest loser, equity curve, max drawdown, per-symbol PnL, and attribution from those metrics back to lineage ids.

### 3. PnL and drawdown calculation are absent and currently guarded out by tests

The 2I specs explicitly state the domain, service, and composition layers do not compute PnL, quantity, price, fees, slippage, risk-adjusted return, or persistence. Current tests reinforce that scope. The historical replay wiring test defines market/PnL fields as disallowed (`v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:33-49`) and asserts emitted records do not contain them (`v2/backend/tests/unit/historical_pnl_replay_wiring/test_historical_pnl_replay_wiring.py:157-162`). The replay explainability projection similarly restricts step and summary envelopes to lineage/count fields (`v2/backend/tests/unit/decision_explainability_replay_backtest_projection/test_decision_explainability_replay_backtest_projection.py:29-64`) and forbids PnL, quantity, price, fee, funding, confidence, feature freshness, and attribution fields (`v2/backend/tests/unit/decision_explainability_replay_backtest_projection/test_decision_explainability_replay_backtest_projection.py:66-85`, `:266-324`).

Impact: the current green test suite proves the lineage-only MVP shape, not the requested PnL/drawdown behavior.

### 4. Historical PnL comparison remains partial/local-only

The historical audit marker is `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY` (`claude_worklog/historical_pnl_audit/10_GO_NO_GO.md:1`). The realized PnL by day, PnL by symbol, fee/funding/commission, and large winner/loser artifacts all contain only `NO_DATA` rows:

- `claude_worklog/historical_pnl_audit/03_30D_REALIZED_PNL_BY_DAY.md`
- `claude_worklog/historical_pnl_audit/04_30D_PNL_BY_SYMBOL.md`
- `claude_worklog/historical_pnl_audit/05_30D_FEES_FUNDING_COMMISSION.md`
- `claude_worklog/historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md`

The 30D proof builds deterministic local fixtures and explicitly labels the mode as `offline_deterministic_historical_fixture` (`v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:191-210`). Its limitations say account-history credentials were unavailable and realized PnL values are fixture values for operator workflow validation (`v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:241-245`).

Impact: there is no populated historical baseline for a real replay-vs-history PnL comparison.

### 5. Large winner/loser attribution is fixture-described, not calculated

The historical audit large winner/loser report has no populated rows. The 30D proof classifies deterministic fixture winners and reduced/rejected losers (`v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:180-189`) and emits fixture paper ledger summaries (`v2/backend/app/proof/historical_30d_replay_and_paper_proof.py:212-224`), but those are not derived from populated realized PnL, fee/funding, and trade rows.

The test-only historical harness preserves evidence pointers and paper ledger entries (`v2/backend/tests/unit/historical_pnl_replay_wiring/harness.py:22-75`), but it does not attribute actual large PnL outcomes. The explainability projection carries LAB hedge-unwind evidence pointers (`v2/backend/tests/unit/decision_explainability_replay_backtest_projection/test_decision_explainability_replay_backtest_projection.py:210-228`) while forbidding the PnL and model/context fields needed for attribution.

Impact: the MVP cannot yet prove actual large winners were preserved or actual large losers were blocked/reduced with concrete PnL and model/risk lineage.

## Concrete Blockers

1. No replay fill/event input contract exists for non-live market outcomes.
2. No replay output contract contains PnL, fee/funding/slippage, equity, drawdown, win/loss, or per-symbol attribution metrics.
3. No deterministic PnL/drawdown calculator exists under the replay/backtest runner.
4. Historical PnL audit artifacts are partial local-only and contain `NO_DATA` for the requested comparison and winner/loser tables.
5. Current tests explicitly disallow the market, PnL, confidence, freshness, and attribution fields needed to satisfy this review topic.

## Proposed Non-Live Autofix Tasks

1. Add an offline replay fill/event value object with run id, event id, symbol, side, quantity, entry price, exit/mark price, commission, funding, slippage, realized PnL, event timestamp, and lineage ids. Keep `live_blocked=True` and reject events outside the run window.
2. Add a pure deterministic replay metrics service using `Decimal` or integer minor units. Compute gross/net PnL, fees, funding, slippage, wins, losses, largest winner, largest loser, equity curve, max drawdown, ending equity, and per-symbol attribution.
3. Extend replay summaries or add a metrics summary object while keeping the current mirror-count summary intact for lineage compatibility.
4. Replace the historical `NO_DATA` audit tables with sanitized local fixture input that produces realized PnL by day, PnL by symbol, fees/funding/commission, and large winner/loser tables without credentials or live reads.
5. Add attribution tests tying top winners/losers to symbol, side, quantity, PnL components, paper trade id, risk decision id, decision id, prediction id, feature snapshot id, confidence/freshness metadata where available, and the LAB hedge-unwind loser scenario.
6. Update current test guards so they require the new non-live financial fields in the metrics layer while still forbidding Redis writes, HTTP/exchange clients, live order placement/cancelation, leverage/margin changes, service restarts, and live trading enablement.

## Verification

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider v2/backend/tests/unit/domain/replay_backtest_runner v2/backend/tests/unit/services/replay_backtest_runner v2/backend/tests/unit/composition/replay_backtest_runner -q`
  - Result: `126 passed in 0.42s`
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider v2/backend/tests/unit/historical_pnl_replay_wiring v2/backend/tests/unit/decision_explainability_replay_backtest_projection v2/backend/tests/unit/proof/test_historical_30d_replay_and_paper_proof.py -q`
  - Result: `30 passed in 0.07s`

CODEX_PARALLEL_REVIEW_BLOCKED
