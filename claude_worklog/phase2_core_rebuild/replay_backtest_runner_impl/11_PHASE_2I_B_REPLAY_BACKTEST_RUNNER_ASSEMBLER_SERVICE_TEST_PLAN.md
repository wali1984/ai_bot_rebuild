# Phase 2I.B — Replay/Backtest Runner Assembler Service Test Plan

This document enumerates the exact set of test files to be authored at `v2/backend/tests/unit/services/replay_backtest_runner/`. The test package marker `__init__.py` is the 41st file. Each test file contains exactly one test function. There is no shared `conftest.py`. Test value-object construction is inline; no fixtures.

## Test files (exactly 40 plus a zero-byte `__init__.py`)

1. `__init__.py` (zero bytes)
2. `test_public_surface.py`
3. `test_assembler_service_does_not_import_redis.py`
4. `test_assembler_service_does_not_import_url_env.py`
5. `test_assembler_service_does_not_register_fastapi_lifespan.py`
6. `test_assembler_service_forbidden_tokens.py`
7. `test_errors_invariants.py`
8. `test_assemble_step_keyword_only_params.py`
9. `test_assemble_step_calls_clock_exactly_once.py`
10. `test_assemble_step_records_clock_into_step_ts_ms.py`
11. `test_assemble_step_replay_step_id_derived_from_paper_trade_id.py`
12. `test_assemble_step_rejects_paper_ledger_entry_not_record.py`
13. `test_assemble_step_rejects_replay_run_not_record.py`
14. `test_assemble_step_rejects_non_callable_clock.py`
15. `test_assemble_step_rejects_clock_returning_non_int.py`
16. `test_assemble_step_rejects_clock_returning_negative.py`
17. `test_assemble_step_rejects_clock_returning_before_run_started_ts_ms.py`
18. `test_assemble_step_rejects_paper_trade_id_too_long_for_replay_step_id_derivation.py`
19. `test_assemble_step_rejects_paper_ledger_entry_symbol_mismatch.py`
20. `test_assemble_step_returns_replay_backtest_step.py`
21. `test_assemble_step_returns_frozen_record.py`
22. `test_assemble_step_record_allow_for_mirror_allow_proceed_long.py`
23. `test_assemble_step_record_allow_for_mirror_allow_proceed_short.py`
24. `test_assemble_step_record_deny_for_mirror_deny_orchestrator_held.py`
25. `test_assemble_step_record_deny_for_mirror_deny_orchestrator_abstained.py`
26. `test_assemble_step_record_deny_for_mirror_deny_default.py`
27. `test_assemble_step_propagates_input_lineage_fields.py`
28. `test_assemble_step_returned_record_is_live_blocked_true.py`
29. `test_assemble_step_exhaustive_over_paper_ledger_reasons.py`
30. `test_assemble_summary_keyword_only_params.py`
31. `test_assemble_summary_calls_clock_exactly_once.py`
32. `test_assemble_summary_records_clock_into_summary_emitted_ts_ms.py`
33. `test_assemble_summary_replay_summary_id_derived_from_replay_run_id.py`
34. `test_assemble_summary_rejects_replay_run_not_record.py`
35. `test_assemble_summary_rejects_steps_not_tuple.py`
36. `test_assemble_summary_rejects_step_element_not_record.py`
37. `test_assemble_summary_rejects_step_replay_run_id_mismatch.py`
38. `test_assemble_summary_rejects_clock_invalid.py`
39. `test_assemble_summary_rejects_replay_run_id_too_long_for_replay_summary_id_derivation.py`
40. `test_assemble_summary_zero_steps_zero_counts.py`
41. `test_assemble_summary_aggregates_counts_for_mixed_steps.py`

## Test contracts (per file, one test function each)

### test_public_surface.py

Imports `v2.backend.app.services.replay_backtest_runner` and asserts that `__all__` equals exactly the 3-tuple `("assemble_replay_backtest_step", "assemble_replay_backtest_summary", "ReplayBacktestRunnerServiceError")` in that order. Asserts both function names are callable. Asserts `ReplayBacktestRunnerServiceError` is a subclass of `ValueError`.

### test_assembler_service_does_not_import_redis.py

Spawns a fresh subprocess via `subprocess.run([sys.executable, "-c", ...])` that imports `v2.backend.app.services.replay_backtest_runner` and prints a Python list of forbidden module names that appear in `sys.modules`. Forbidden names: `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`, `requests`, `fastapi`, `uvicorn`, `starlette`, `asyncio`, `threading`, and `v2.backend.app.adapters.redis_v2.url_env`. Asserts the printed list is empty.

### test_assembler_service_does_not_import_url_env.py

Spawns a fresh subprocess that imports the assembler package and asserts `v2.backend.app.adapters.redis_v2.url_env` is NOT in `sys.modules`.

### test_assembler_service_does_not_register_fastapi_lifespan.py

Spawns a fresh subprocess that imports the assembler package and asserts that `fastapi`, `uvicorn`, and `starlette` are NOT in `sys.modules` and that no module-level callable named `lifespan` exists in `v2.backend.app.services.replay_backtest_runner`.

### test_assembler_service_forbidden_tokens.py

Reads `__init__.py`, `errors.py`, and `service.py` as text. For each forbidden token in spec section "Forbidden tokens in source files", asserts the token does NOT appear in any of the three files. Tokens are constructed at runtime via string concatenation.

### test_errors_invariants.py

Constructs `ReplayBacktestRunnerServiceError("must_be_int", field="now_ms_clock")` and asserts `.code == "must_be_int"`, `.field == "now_ms_clock"`, `str(e) == "must_be_int (now_ms_clock)"`, `repr(e) == "ReplayBacktestRunnerServiceError(code='must_be_int', field='now_ms_clock')"`, and `isinstance(e, ValueError) is True`.

### test_assemble_step_keyword_only_params.py

Asserts that `assemble_replay_backtest_step(paper_ledger_entry, replay_run, lambda: 1)` (positional) raises `TypeError`. Asserts that the same call with all keyword arguments succeeds (using a happy-path mirror_allow_proceed_long entry, a matching-symbol replay run, and a lambda clock returning a fixed int that satisfies `>= run_started_ts_ms`).

### test_assemble_step_calls_clock_exactly_once.py

Constructs a counter clock that increments a list on each call and returns `1000` on the first call and `999_999_999` thereafter. Calls the assembler once with `run_started_ts_ms=0` and asserts the counter list has length 1. Asserts the returned `step_ts_ms == 1000`.

### test_assemble_step_records_clock_into_step_ts_ms.py

Constructs a clock returning a fixed `42`. Calls the step assembler with a happy-path mirror_allow_proceed_long entry and a replay run with `run_started_ts_ms=0`. Asserts the returned step's `step_ts_ms == 42`.

### test_assemble_step_replay_step_id_derived_from_paper_trade_id.py

Constructs a `PaperExecutionLedgerEntry` with `paper_trade_id="pt_rd_dec_pred_abc"`. Calls the step assembler. Asserts the returned step's `replay_step_id == "rstep_pt_rd_dec_pred_abc"`.

### test_assemble_step_rejects_paper_ledger_entry_not_record.py

Calls the step assembler with `paper_ledger_entry=object()` and `paper_ledger_entry=None` and asserts each raises `ReplayBacktestRunnerServiceError` with `code="must_be_paper_execution_ledger_entry"` and `field="paper_ledger_entry"`.

### test_assemble_step_rejects_replay_run_not_record.py

Calls the step assembler with `replay_run=object()` and `replay_run=None` and asserts each raises `ReplayBacktestRunnerServiceError` with `code="must_be_replay_backtest_run"` and `field="replay_run"`.

### test_assemble_step_rejects_non_callable_clock.py

Calls the step assembler with `now_ms_clock=42` (non-callable) and asserts that `ReplayBacktestRunnerServiceError` is raised with `code="must_be_callable"` and `field="now_ms_clock"`.

### test_assemble_step_rejects_clock_returning_non_int.py

Calls the step assembler with `now_ms_clock=lambda: 1.0` and asserts `ReplayBacktestRunnerServiceError` with `code="must_be_int"` and `field="now_ms_clock"`. Also tests `lambda: True` and `lambda: "100"`.

### test_assemble_step_rejects_clock_returning_negative.py

Calls the step assembler with `now_ms_clock=lambda: -1` (and a `replay_run` whose `run_started_ts_ms == 0`) and asserts `ReplayBacktestRunnerServiceError` with `code="must_be_nonnegative"` and `field="now_ms_clock"`.

### test_assemble_step_rejects_clock_returning_before_run_started_ts_ms.py

Calls the step assembler with `replay_run.run_started_ts_ms=1000` and `now_ms_clock=lambda: 999`. Asserts `ReplayBacktestRunnerServiceError` with `code="must_be_at_or_after_run_started_ts_ms"` and `field="now_ms_clock"`.

### test_assemble_step_rejects_paper_trade_id_too_long_for_replay_step_id_derivation.py

Constructs a `PaperExecutionLedgerEntry` with `paper_trade_id` of length 123 (one above the 122 cap) using a 123-char alphanumeric ASCII string. Calls the step assembler and asserts `ReplayBacktestRunnerServiceError` with `code="paper_trade_id_too_long_for_replay_step_id_derivation"` and `field="paper_ledger_entry.paper_trade_id"`. Also asserts that `paper_trade_id` of length 122 succeeds.

### test_assemble_step_rejects_paper_ledger_entry_symbol_mismatch.py

Constructs a `PaperExecutionLedgerEntry` with `symbol="BTCUSDT"` and a `ReplayBacktestRun` with `symbol="ETHUSDT"`. Calls the step assembler and asserts `ReplayBacktestRunnerServiceError` with `code="paper_ledger_entry_symbol_must_match_replay_run_symbol"` and `field="paper_ledger_entry.symbol"`.

### test_assemble_step_returns_replay_backtest_step.py

Calls the step assembler with a happy-path mirror_allow_proceed_long entry and asserts the returned object is an instance of `v2.backend.app.domain.replay_backtest_runner.ReplayBacktestStep`.

### test_assemble_step_returns_frozen_record.py

Calls the step assembler with a happy-path mirror_allow_proceed_long entry and asserts that assignment to any field of the returned step raises `dataclasses.FrozenInstanceError`.

### test_assemble_step_record_allow_for_mirror_allow_proceed_long.py

Constructs a fresh `PaperExecutionLedgerEntry` with `ledger_action="record_allow"`, `ledger_reason_code="mirror_allow_proceed_long"`, `input_risk_action="allow"`, `input_risk_reason_code="allow_proceed_long"`. Calls the step assembler with a clock returning `1000`. Asserts `step_action == "step_record_allow"`, `step_reason_code == "step_mirror_allow_proceed_long"`, `step_ts_ms == 1000`, `replay_step_id == "rstep_" + paper_trade_id`, `live_blocked is True`, `input_paper_action == "record_allow"`, `input_paper_reason_code == "mirror_allow_proceed_long"`.

### test_assemble_step_record_allow_for_mirror_allow_proceed_short.py

Same as `_record_allow_for_mirror_allow_proceed_long` but with `ledger_reason_code="mirror_allow_proceed_short"`. Asserts `step_action == "step_record_allow"`, `step_reason_code == "step_mirror_allow_proceed_short"`, `input_paper_reason_code == "mirror_allow_proceed_short"`.

### test_assemble_step_record_deny_for_mirror_deny_orchestrator_held.py

Constructs a `PaperExecutionLedgerEntry` with `ledger_action="record_deny"`, `ledger_reason_code="mirror_deny_orchestrator_held"`. Asserts `step_action == "step_record_deny"`, `step_reason_code == "step_mirror_deny_orchestrator_held"`, `input_paper_action == "record_deny"`, `input_paper_reason_code == "mirror_deny_orchestrator_held"`, `live_blocked is True`.

### test_assemble_step_record_deny_for_mirror_deny_orchestrator_abstained.py

Analogous for `mirror_deny_orchestrator_abstained` / `step_mirror_deny_orchestrator_abstained`.

### test_assemble_step_record_deny_for_mirror_deny_default.py

Analogous for `mirror_deny_default` / `step_mirror_deny_default`. The literal `"deny_default"`-shaped substring MUST NOT appear in the test source file body except as a runtime string-concatenated literal.

### test_assemble_step_propagates_input_lineage_fields.py

Constructs a happy-path mirror_allow_proceed_long entry with distinct ids `paper_trade_id="pt_rd_dec_lineage_xyz"`, `risk_decision_id="rd_dec_lineage_xyz"`, `decision_id="dec_lineage_xyz"`, `prediction_id="pred_lineage_xyz"`, `feature_snapshot_id="snap_lineage_xyz"`, `symbol="ETHUSDT"`. Calls the step assembler. Asserts the returned step's `paper_trade_id == "pt_rd_dec_lineage_xyz"`, `risk_decision_id == "rd_dec_lineage_xyz"`, `decision_id == "dec_lineage_xyz"`, `prediction_id == "pred_lineage_xyz"`, `feature_snapshot_id == "snap_lineage_xyz"`, `symbol == "ETHUSDT"`, `replay_step_id == "rstep_pt_rd_dec_lineage_xyz"`, `replay_run_id == replay_run.replay_run_id`, `input_paper_action == "record_allow"`, `input_paper_reason_code == "mirror_allow_proceed_long"`, and `live_blocked is True`.

### test_assemble_step_returned_record_is_live_blocked_true.py

Calls the step assembler with a happy-path mirror_allow_proceed_long entry and asserts `returned_step.live_blocked is True` (identity check, not equality). Then asserts `returned_step.live_blocked == True` and `type(returned_step.live_blocked) is bool`.

### test_assemble_step_exhaustive_over_paper_ledger_reasons.py

Constructs the 5-row table of (input `ledger_reason_code`, expected `step_action`, expected `step_reason_code`) explicitly:

- `("mirror_allow_proceed_long", "step_record_allow", "step_mirror_allow_proceed_long")`
- `("mirror_allow_proceed_short", "step_record_allow", "step_mirror_allow_proceed_short")`
- `("mirror_deny_orchestrator_held", "step_record_deny", "step_mirror_deny_orchestrator_held")`
- `("mirror_deny_orchestrator_abstained", "step_record_deny", "step_mirror_deny_orchestrator_abstained")`
- `("mirror_deny_default", "step_record_deny", "step_mirror_deny_default")`

For each row, constructs a 2H.A-valid `PaperExecutionLedgerEntry`, calls the step assembler, asserts `step_action` and `step_reason_code` match, and asserts the table covers exactly the 5 members of the 2H.A `_ALLOWED_LEDGER_REASON_CODES` frozenset (length check). Constructs an unrecognized `ledger_reason_code` (`"mirror_unrecognized_synthetic"`) by using `object.__setattr__` on a frozen instance, calls the step assembler, and asserts `ReplayBacktestRunnerServiceError` with `code="unrecognized_paper_ledger_reason_code"` and `field="paper_ledger_entry.ledger_reason_code"`.

### test_assemble_summary_keyword_only_params.py

Asserts that `assemble_replay_backtest_summary(replay_run, (), lambda: 1)` (positional) raises `TypeError`. Asserts that the same call with all keyword arguments succeeds for an empty `steps` tuple.

### test_assemble_summary_calls_clock_exactly_once.py

Constructs a counter clock returning `1000` first then `999_999_999`. Calls the summary assembler once with empty `steps` and asserts the counter list has length 1 and `summary_emitted_ts_ms == 1000`.

### test_assemble_summary_records_clock_into_summary_emitted_ts_ms.py

Constructs a clock returning `42`. Calls the summary assembler with empty `steps` and `replay_run.run_started_ts_ms=0`. Asserts `summary_emitted_ts_ms == 42`.

### test_assemble_summary_replay_summary_id_derived_from_replay_run_id.py

Constructs a `ReplayBacktestRun` with `replay_run_id="run_xyz"`. Calls the summary assembler with empty `steps`. Asserts `replay_summary_id == "rsum_run_xyz"`.

### test_assemble_summary_rejects_replay_run_not_record.py

Calls the summary assembler with `replay_run=object()` and `replay_run=None`. Asserts each raises `ReplayBacktestRunnerServiceError` with `code="must_be_replay_backtest_run"` and `field="replay_run"`.

### test_assemble_summary_rejects_steps_not_tuple.py

Calls the summary assembler with `steps=[]` (list, not tuple) and `steps=None`. Asserts each raises `ReplayBacktestRunnerServiceError` with `code="must_be_tuple"` and `field="steps"`.

### test_assemble_summary_rejects_step_element_not_record.py

Calls the summary assembler with `steps=(object(),)` and asserts `ReplayBacktestRunnerServiceError` with `code="must_be_replay_backtest_step"` and `field="steps[0]"`.

### test_assemble_summary_rejects_step_replay_run_id_mismatch.py

Constructs a `ReplayBacktestStep` with `replay_run_id="run_a"` and a `ReplayBacktestRun` with `replay_run_id="run_b"`. Calls the summary assembler with `steps=(step,)`. Asserts `ReplayBacktestRunnerServiceError` with `code="step_replay_run_id_must_match_replay_run_id"` and `field="steps[0].replay_run_id"`.

### test_assemble_summary_rejects_clock_invalid.py

Single test function with four sub-assertions:
1. `now_ms_clock=42` raises `ReplayBacktestRunnerServiceError` with `code="must_be_callable"` and `field="now_ms_clock"`.
2. `now_ms_clock=lambda: 1.0` raises `code="must_be_int"`.
3. `now_ms_clock=lambda: -1` (with `run_started_ts_ms=0`) raises `code="must_be_nonnegative"`.
4. `now_ms_clock=lambda: 999` (with `run_started_ts_ms=1000`) raises `code="must_be_at_or_after_run_started_ts_ms"`.

### test_assemble_summary_rejects_replay_run_id_too_long_for_replay_summary_id_derivation.py

Constructs a `ReplayBacktestRun` with `replay_run_id` of length 124 (one above the 123 cap). Calls the summary assembler and asserts `ReplayBacktestRunnerServiceError` with `code="replay_run_id_too_long_for_replay_summary_id_derivation"` and `field="replay_run.replay_run_id"`. Also asserts that `replay_run_id` of length 123 succeeds.

### test_assemble_summary_zero_steps_zero_counts.py

Calls the summary assembler with `steps=()`. Asserts the returned summary has `total_steps_count=0`, `record_allow_steps_count=0`, `record_deny_steps_count=0`, all five subreason counts equal to 0, and `live_blocked is True`. Asserts the summary is an instance of `ReplayBacktestSummary` and is frozen.

### test_assemble_summary_aggregates_counts_for_mixed_steps.py

Constructs five `ReplayBacktestStep` instances, one per mirror case (1 long, 1 short, 1 held, 1 abstained, 1 default), all sharing the same `replay_run_id`. Calls the summary assembler. Asserts `total_steps_count == 5`, `record_allow_steps_count == 2`, `record_deny_steps_count == 3`, `mirror_allow_proceed_long_steps_count == 1`, `mirror_allow_proceed_short_steps_count == 1`, `mirror_deny_orchestrator_held_steps_count == 1`, `mirror_deny_orchestrator_abstained_steps_count == 1`, `mirror_deny_default_steps_count == 1`, `live_blocked is True`. Then constructs a second scenario with `(2, 0, 1, 1, 1)` (two long allows, no short, three denies of mixed sub-reasons) and verifies count math.

## Properties enforced across the suite

- Frozen dataclass: a separate assertion inside `test_assemble_step_returns_frozen_record.py` attempts `step.replay_step_id = "x"` and expects `dataclasses.FrozenInstanceError`.
- Keyword-only construction: every test constructs by keyword.
- No shared `conftest.py`, no `parametrize`, no shared helper module. One test function per file.
- Inline value-object construction. No fixtures.

## Validation commands the implementation task MUST run and capture

- `.venv/bin/python -m py_compile v2/backend/app/services/replay_backtest_runner/__init__.py v2/backend/app/services/replay_backtest_runner/errors.py v2/backend/app/services/replay_backtest_runner/service.py`
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/replay_backtest_runner/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/replay_backtest_runner/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/paper_execution_ledger/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/paper_execution_ledger/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/risk_gateway/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/risk_gateway/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/orchestrator_decision/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/orchestrator_decision/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_prediction_output/ -q` (must remain green)
- For each forbidden token T from spec section "Forbidden tokens in source files": `rg --fixed-strings --case-sensitive T v2/backend/app/services/replay_backtest_runner/` (must show zero matches per token)

PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_TEST_PLAN_READY
