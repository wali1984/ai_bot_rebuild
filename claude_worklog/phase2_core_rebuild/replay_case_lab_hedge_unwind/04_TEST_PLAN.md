# Phase 2M — Test Plan

## Test module

Path: `v2/backend/tests/unit/replay_case_lab_hedge_unwind/test_lab_hedge_unwind_replay_case.py`.

The test module imports `build_replay_backtest_runner` from `v2.backend.app.composition.replay_backtest_runner` and the fixture builders from `v2.backend.tests.unit.replay_case_lab_hedge_unwind.fixtures`. It is a stdlib + pytest module; no other imports are used.

## Per-outcome test functions

For each of the five outcome variants, the test module includes a test function with the naming pattern `test_lab_hedge_unwind_{outcome_slug}_replay_case_records_typed_mirror_sequence`.

Each test function performs the following steps:

1. Instantiate a deterministic monotonic test clock via `build_test_clock(start_ms=1_700_000_000_010, step_ms=1_000)`.
2. Build a `ReplayBacktestRunner` via `build_replay_backtest_runner(now_ms_clock=test_clock)`.
3. Call `build_{outcome_slug}_outcome()` to obtain `(replay_run, paper_ledger_entries)`.
4. For each `paper_ledger_entry` in the ordered tuple, call `runner.assemble_step(paper_ledger_entry=paper_ledger_entry, replay_run=replay_run)` and collect the resulting `ReplayBacktestStep` instances into a tuple.
5. Assert the typed mirror projection per `02_REPLAY_CASE_OUTCOME_MATRIX.md` for every step (action / reason / live_blocked / identifier carry-over).
6. Assert the per-outcome `ReplayBacktestSummary` produced by `runner.assemble_summary(replay_run=replay_run, steps=collected_steps)` has the expected `record_allow` / `record_deny` step counts.
7. Assert that `live_blocked is True` on the `replay_run`, every `paper_ledger_entry`, every `ReplayBacktestStep`, and the resulting `ReplayBacktestSummary`.

## Cross-outcome test functions

In addition, the test module includes the following cross-outcome test functions:

- `test_lab_hedge_unwind_outcomes_have_distinct_replay_run_ids` — asserts that the five outcomes' `replay_run_id` values are pairwise distinct.
- `test_lab_hedge_unwind_outcomes_have_distinct_paper_trade_ids` — asserts that the union of all `paper_trade_id` values across the five outcomes contains 15 unique strings (3 steps × 5 outcomes).
- `test_lab_hedge_unwind_close_short_and_reduce_short_have_identical_typed_mirror_sequences` — asserts that outcomes 3 and 4 produce the same typed mirror sequence (action × reason × input pairings) across their three steps, documenting the acknowledged typing limitation in `02_REPLAY_CASE_OUTCOME_MATRIX.md`.
- `test_lab_hedge_unwind_legacy_outcome_records_close_as_mirror_allow_proceed_long` — asserts that outcome 1's third step records a `mirror_allow_proceed_long` mirror reason, documenting the legacy bot's untyped close decision under the existing typed surfaces.
- `test_lab_hedge_unwind_block_hedge_close_outcome_records_third_step_as_mirror_deny_default` — asserts that outcome 5's third step records a `record_deny` × `mirror_deny_default` typed deny on the hedge close.

## Forbidden test content

- No mock / patch / monkeypatch of `build_replay_backtest_runner` or its dependencies. The composition root is exercised as authored.
- No use of `pytest.fixture` autouse to inject system clocks; the deterministic test clock is instantiated per test.
- No `time.time`, `time.monotonic`, `datetime.now`, `datetime.utcnow` invocation.
- No file I/O, network call, environment variable read, Redis client, CCXT client, or HTTP client.
- No assertion on PnL, position size, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, or squeeze risk — none of those are typed at consolidation HEAD.
- No assertion on `shadow_decision_id` or `execution_intent_id` (those lineage rows do not exist at consolidation HEAD).

## Local validation commands

The supervisor task runs the following validation commands in order:

1. `git status --porcelain` — must report clean before commit attempt.
2. `python -m pytest v2/backend/tests/unit/replay_case_lab_hedge_unwind/test_lab_hedge_unwind_replay_case.py -v --no-header` — all tests pass.
3. `git diff --stat HEAD -- v2/backend/app/` — must produce zero lines (no production code modified).
4. `git diff --stat HEAD -- /home/wali/Desktop/AI\ BOT` — must produce zero lines (no legacy mutation).
5. `test "$(cat claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/07_GO_NO_GO.md)" = "PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_IMPLEMENTATION_READY"` — marker body matches.
6. `test -f v2/backend/tests/unit/replay_case_lab_hedge_unwind/__init__.py` — package shim exists.
7. `test -f v2/backend/tests/unit/replay_case_lab_hedge_unwind/fixtures.py` — fixture module exists.
8. `test -f v2/backend/tests/unit/replay_case_lab_hedge_unwind/test_lab_hedge_unwind_replay_case.py` — test module exists.
9. `test -f claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/06_IMPLEMENTATION_REPORT.md` — implementation report exists.
10. High-confidence secret scan over the diff — must report zero high-confidence secret findings.

PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_TEST_PLAN_READY
