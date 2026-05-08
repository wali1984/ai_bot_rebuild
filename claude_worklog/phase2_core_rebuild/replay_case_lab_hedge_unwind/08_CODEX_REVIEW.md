# Phase 2M LAB Hedge-Unwind Replay Case Codex Review

PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_REVIEW_READY

## Decision

PASS. The Phase 2M packet materializes the REQ_0022 LAB hedge-unwind / short-squeeze case as a non-live typed mirror replay fixture and pytest harness through the existing `ReplayBacktestRunner` composition root.

## Scope Reviewed

- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/00_SCOPE.md`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/01_LEGACY_FAILURE_EVIDENCE.md`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/02_REPLAY_CASE_OUTCOME_MATRIX.md`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/03_TYPED_INPUT_FIXTURE_SPEC.md`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/04_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/05_GO_NO_GO_REQUEST.md`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/06_IMPLEMENTATION_REPORT.md`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/07_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/PLANNER_TURN_2M_OPEN_CODEX_REVIEW.md`
- `v2/backend/tests/unit/replay_case_lab_hedge_unwind/__init__.py`
- `v2/backend/tests/unit/replay_case_lab_hedge_unwind/fixtures.py`
- `v2/backend/tests/unit/replay_case_lab_hedge_unwind/test_lab_hedge_unwind_replay_case.py`
- Existing typed surfaces under `v2/backend/app/domain/replay_backtest_runner/`, `v2/backend/app/domain/paper_execution_ledger/`, `v2/backend/app/services/replay_backtest_runner/`, and `v2/backend/app/composition/replay_backtest_runner/`.

## Findings

No blocking findings.

The implementation is test-only, builds the five required outcome variants, preserves distinct `replay_run_id` and `paper_trade_id` namespaces, projects the expected `record_allow` / `record_deny` mirror rows, and asserts the documented Phase 2M limitation that close-short and reduce-short collapse to the same typed mirror sequence at the current typed surface layer.

The pytest harness exercises `build_replay_backtest_runner(now_ms_clock=...)` directly with a deterministic clock and does not mock, patch, or monkeypatch the composition root or its dependencies.

The fixture and test files do not introduce wall-clock calls, file I/O, network clients, Redis clients, exchange SDKs, environment-variable reads, FastAPI/Starlette/pydantic imports, or heavyweight numerics/ML imports.

The packet does not modify `v2/backend/app/`, does not add execution-side surfaces, does not add persistence, does not introduce `shadow_decision_id` or `execution_intent_id`, and does not introduce PnL, sizing, price, fees, slippage, funding, OI, liquidation-map, orderbook-depth, hedge-state, residual-exposure, or squeeze-risk computation.

## Validation

- `/usr/bin/python -m pytest v2/backend/tests/unit/replay_case_lab_hedge_unwind/test_lab_hedge_unwind_replay_case.py -v --no-header`: blocked because `/usr/bin/python` has no `pytest` module in this environment.
- `.venv/bin/python -m pytest v2/backend/tests/unit/replay_case_lab_hedge_unwind/test_lab_hedge_unwind_replay_case.py -v --no-header`: 15 passed.
- `git diff --stat HEAD -- v2/backend/app/`: no output.
- `git diff --stat HEAD -- v2/backend/tests/unit/replay_case_lab_hedge_unwind/`: no output at review start; task 164 review did not modify test files.
- `test "$(cat claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/07_GO_NO_GO.md)" = "PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_IMPLEMENTATION_READY"`: passed.
- `test "$(cat claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md)" = "V2_BACKTEST_AND_PAPER_MVP_READY"`: passed.
- `test "$(cat claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md)" = "V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS"`: passed.
- Forbidden-token scan over `v2/backend/tests/unit/replay_case_lab_hedge_unwind/`: no matches.

## Safety

No Redis command was invoked. No live service was restarted. No exchange order, leverage change, or margin change was made. Live trading remains disabled. No deployment, production migration, credential exposure, or live-readiness gate flip was performed. The separate `/home/wali/Desktop/AI BOT` tree was not modified.
