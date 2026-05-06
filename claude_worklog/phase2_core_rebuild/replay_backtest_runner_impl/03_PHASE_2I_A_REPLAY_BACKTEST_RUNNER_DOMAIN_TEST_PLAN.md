# Phase 2I.A — Replay/Backtest Runner Domain Test Plan

This document enumerates the exact test files emitted by Phase 2I.A under `v2/backend/tests/unit/domain/replay_backtest_runner/`. Each test file contains exactly one test function. There is no shared `conftest.py`. All `ReplayBacktestRun`, `ReplayBacktestStep`, and `ReplayBacktestSummary` instances are constructed by keyword. No fixture, no parametrize, no shared helper module.

## Test files (exactly 52, including a zero-byte `__init__.py`)

1. `__init__.py` — zero bytes.

### Public surface and module-load isolation (13)

2. `test_public_surface.py` — verifies `__all__` of `v2.backend.app.domain.replay_backtest_runner` equals the 13-tuple from spec section "Public surface", in order, with no extras.
3. `test_init_module_does_not_load_redis.py` — subprocess `python -c "import sys; import v2.backend.app.domain.replay_backtest_runner; assert 'redis' not in sys.modules and 'redis.asyncio' not in sys.modules and 'aioredis' not in sys.modules and 'hiredis' not in sys.modules"`; asserts return code 0.
4. `test_init_module_does_not_load_url_env.py` — subprocess assertion that `'v2.backend.app.adapters.redis_v2.url_env'` is NOT in `sys.modules` after import.
5. `test_init_module_does_not_register_fastapi_lifespan.py` — subprocess assertion that `'fastapi'`, `'uvicorn'`, and `'starlette'` are NOT in `sys.modules` after import.
6. `test_run_module_does_not_load_redis_when_imported.py` — subprocess assertion that importing `v2.backend.app.domain.replay_backtest_runner.run` directly does NOT load redis/aioredis/hiredis.
7. `test_step_module_does_not_load_redis_when_imported.py` — subprocess assertion that importing `v2.backend.app.domain.replay_backtest_runner.step` directly does NOT load redis/aioredis/hiredis.
8. `test_summary_module_does_not_load_redis_when_imported.py` — subprocess assertion that importing `v2.backend.app.domain.replay_backtest_runner.summary` directly does NOT load redis/aioredis/hiredis.
9. `test_domain_module_does_not_import_paper_execution_ledger.py` — subprocess assertion that `'v2.backend.app.domain.paper_execution_ledger'` is NOT in `sys.modules` after importing the package.
10. `test_domain_module_does_not_import_risk_gateway.py` — subprocess assertion that `'v2.backend.app.domain.risk_gateway'` is NOT in `sys.modules` after import.
11. `test_domain_module_does_not_import_orchestrator_decision.py` — subprocess assertion that `'v2.backend.app.domain.orchestrator_decision'` is NOT in `sys.modules` after import.
12. `test_domain_module_does_not_import_trainer_prediction_output.py` — subprocess assertion that `'v2.backend.app.domain.trainer_prediction_output'` is NOT in `sys.modules` after import.
13. `test_domain_module_does_not_import_replay_placeholder.py` — subprocess assertion that `'v2.backend.app.domain.replay'` is NOT in `sys.modules` after import.
14. `test_domain_module_does_not_import_execution_placeholder.py` — subprocess assertion that `'v2.backend.app.domain.execution'` is NOT in `sys.modules` after import.

### Forbidden-token scan and constants (5)

15. `test_forbidden_tokens_not_present.py` — for each forbidden token enumerated in spec section "Forbidden tokens in source files", reads the five authored source files via `pathlib.Path.read_text` and asserts the token (constructed at runtime via string concatenation) is NOT a substring. One token per assertion. The test file does NOT contain the bare forbidden token literals.
16. `test_run_mode_constants_lowercase_and_unique.py` — asserts both run-mode constants equal their own `.lower()`, are non-empty `str`, and the 2-tuple `(RUN_MODE_REPLAY, RUN_MODE_BACKTEST)` has 2 distinct members.
17. `test_step_action_constants_lowercase_and_unique.py` — asserts both step-action constants equal their own `.lower()`, are non-empty `str`, and the 2-tuple `(STEP_ACTION_RECORD_ALLOW, STEP_ACTION_RECORD_DENY)` has 2 distinct members.
18. `test_step_reason_constants_lowercase_and_unique.py` — asserts all five step-reason constants equal their own `.lower()`, are non-empty `str`, and the 5-tuple has 5 distinct members.
19. `test_step_reason_constants_carry_correct_prefix.py` — asserts every `STEP_REASON_MIRROR_ALLOW_*` value starts with `"step_mirror_allow_"` and every `STEP_REASON_MIRROR_DENY_*` value starts with `"step_mirror_deny_"`.

### ReplayBacktestRun construction (11)

20. `test_run_constructs_with_valid_inputs_replay_mode.py` — constructs a run with `run_mode="replay"`, `live_blocked=True`; asserts no exception, field round-trip, and `dataclasses.FrozenInstanceError` on attempted mutation.
21. `test_run_constructs_with_valid_inputs_backtest_mode.py` — constructs a run with `run_mode="backtest"`, `live_blocked=True`; asserts success and field round-trip.
22. `test_run_rejects_unknown_run_mode.py` — asserts `ReplayBacktestRunnerDomainError` with `field == "run_mode"` when `run_mode == "shadow"`.
23. `test_run_rejects_empty_replay_run_id.py` — asserts `ReplayBacktestRunnerDomainError` with `field == "replay_run_id"` when `replay_run_id == ""`.
24. `test_run_rejects_whitespace_replay_run_id.py` — asserts `ReplayBacktestRunnerDomainError` with `field == "replay_run_id"` when `replay_run_id` contains internal whitespace.
25. `test_run_rejects_too_long_replay_run_id.py` — asserts `ReplayBacktestRunnerDomainError` with `field == "replay_run_id"` when `len(replay_run_id) == 129`.
26. `test_run_rejects_invalid_symbol_lowercase.py` — asserts `ReplayBacktestRunnerDomainError` with `field == "symbol"` when `symbol == "btcusdt"`.
27. `test_run_rejects_negative_run_started_ts_ms.py` — asserts `ReplayBacktestRunnerDomainError` with `field == "run_started_ts_ms"` when `run_started_ts_ms == -1`.
28. `test_run_rejects_bool_for_run_started_ts_ms.py` — asserts `ReplayBacktestRunnerDomainError` with `field == "run_started_ts_ms"` when `run_started_ts_ms is True`.
29. `test_run_rejects_run_ended_ts_ms_before_run_started_ts_ms.py` — asserts `ReplayBacktestRunnerDomainError` with `reason == "run_ended_ts_ms_must_be_ge_run_started_ts_ms"` and `field == "run_ended_ts_ms"` when `run_ended_ts_ms < run_started_ts_ms`.
30. `test_run_rejects_live_blocked_false.py` — asserts `ReplayBacktestRunnerDomainError` with `reason == "replay_backtest_run_requires_live_blocked_true"` and `field == "live_blocked"` when `live_blocked == False`.

### ReplayBacktestStep construction (14)

31. `test_step_constructs_with_valid_inputs_record_allow_long.py` — constructs a step with `step_action="step_record_allow"`, `step_reason_code="step_mirror_allow_proceed_long"`, `input_paper_action="record_allow"`, `input_paper_reason_code="mirror_allow_proceed_long"`, `live_blocked=True`; asserts success, frozen, slotted (assertion that `entry.__class__.__dict__.get('__slots__')` is a non-empty tuple and that adding an unknown attribute via `setattr` raises `AttributeError`).
32. `test_step_constructs_with_valid_inputs_record_allow_short.py` — analogous for `step_mirror_allow_proceed_short` / `mirror_allow_proceed_short`; asserts success.
33. `test_step_constructs_with_valid_inputs_record_deny_orchestrator_held.py` — analogous for `step_mirror_deny_orchestrator_held` / `mirror_deny_orchestrator_held`; asserts success.
34. `test_step_constructs_with_valid_inputs_record_deny_orchestrator_abstained.py` — analogous for `step_mirror_deny_orchestrator_abstained` / `mirror_deny_orchestrator_abstained`; asserts success.
35. `test_step_constructs_with_valid_inputs_record_deny_default.py` — analogous for `step_mirror_deny_default` / `mirror_deny_default`; asserts success.
36. `test_step_rejects_empty_replay_step_id.py` — asserts `ReplayBacktestRunnerDomainError` with `field == "replay_step_id"` when `replay_step_id == ""`.
37. `test_step_rejects_whitespace_replay_step_id.py` — asserts `ReplayBacktestRunnerDomainError` with `field == "replay_step_id"` when `replay_step_id` contains internal whitespace.
38. `test_step_rejects_unknown_step_action.py` — asserts `ReplayBacktestRunnerDomainError` with `field == "step_action"` when `step_action == "step_record_skip"`.
39. `test_step_rejects_unknown_step_reason_code.py` — asserts `ReplayBacktestRunnerDomainError` with `field == "step_reason_code"` when `step_reason_code == "step_mirror_unknown"`.
40. `test_step_rejects_step_record_allow_with_step_mirror_deny_reason.py` — asserts `ReplayBacktestRunnerDomainError` with `reason == "step_record_allow_requires_step_mirror_allow_prefix_reason"` when `step_action == "step_record_allow"` and `step_reason_code == "step_mirror_deny_orchestrator_held"`.
41. `test_step_rejects_step_record_deny_with_step_mirror_allow_reason.py` — asserts `ReplayBacktestRunnerDomainError` with `reason == "step_record_deny_requires_step_mirror_deny_prefix_reason"` when `step_action == "step_record_deny"` and `step_reason_code == "step_mirror_allow_proceed_long"`.
42. `test_step_rejects_step_mirror_allow_proceed_long_with_wrong_input_reason.py` — asserts `ReplayBacktestRunnerDomainError` with `reason == "step_mirror_allow_proceed_long_requires_mirror_allow_proceed_long_input_reason"` when `step_reason_code == "step_mirror_allow_proceed_long"` but `input_paper_reason_code == "mirror_allow_proceed_short"`.
43. `test_step_rejects_step_mirror_deny_default_with_wrong_input_reason.py` — asserts `ReplayBacktestRunnerDomainError` with `reason == "step_mirror_deny_default_requires_mirror_deny_default_input_reason"` when `step_reason_code == "step_mirror_deny_default"` but `input_paper_reason_code == "mirror_deny_orchestrator_held"`.
44. `test_step_rejects_live_blocked_false.py` — asserts `ReplayBacktestRunnerDomainError` with `reason == "replay_backtest_step_requires_live_blocked_true"` and `field == "live_blocked"` when `live_blocked == False`.

### ReplayBacktestSummary construction (8)

45. `test_summary_constructs_with_valid_inputs_zero_steps.py` — constructs a summary with all step counts equal to 0 and `live_blocked=True`; asserts success, frozen, slotted.
46. `test_summary_constructs_with_valid_inputs_mixed_steps.py` — constructs a summary with `total_steps_count=5`, `record_allow_steps_count=2`, `record_deny_steps_count=3`, allow-subreason counts `(1, 1, 0)` summing to 2 across `(long, short)`, deny-subreason counts `(1, 1, 1)` summing to 3 across `(held, abstained, default)`, and `live_blocked=True`; asserts success and field round-trip.
47. `test_summary_rejects_empty_replay_summary_id.py` — asserts `ReplayBacktestRunnerDomainError` with `field == "replay_summary_id"` when `replay_summary_id == ""`.
48. `test_summary_rejects_negative_total_steps_count.py` — asserts `ReplayBacktestRunnerDomainError` with `field == "total_steps_count"` when `total_steps_count == -1`.
49. `test_summary_rejects_partition_sum_action_mismatch.py` — asserts `ReplayBacktestRunnerDomainError` with `reason == "action_partition_sum_must_equal_total_steps_count"` and `field == "total_steps_count"` when `record_allow_steps_count + record_deny_steps_count != total_steps_count`.
50. `test_summary_rejects_partition_sum_allow_subreason_mismatch.py` — asserts `ReplayBacktestRunnerDomainError` with `reason == "allow_subreason_partition_sum_must_equal_record_allow_steps_count"` and `field == "record_allow_steps_count"` when allow-subreason counts do not sum to `record_allow_steps_count`.
51. `test_summary_rejects_partition_sum_deny_subreason_mismatch.py` — asserts `ReplayBacktestRunnerDomainError` with `reason == "deny_subreason_partition_sum_must_equal_record_deny_steps_count"` and `field == "record_deny_steps_count"` when deny-subreason counts do not sum to `record_deny_steps_count`.
52. `test_summary_rejects_live_blocked_false.py` — asserts `ReplayBacktestRunnerDomainError` with `reason == "replay_backtest_summary_requires_live_blocked_true"` and `field == "live_blocked"` when `live_blocked == False`.

## Properties enforced across the suite

- Frozen dataclass: a separate assertion inside `test_run_constructs_with_valid_inputs_replay_mode.py` attempts `run.replay_run_id = "x"` and expects `dataclasses.FrozenInstanceError`. Equivalent assertions exist inside `test_step_constructs_with_valid_inputs_record_allow_long.py` and `test_summary_constructs_with_valid_inputs_zero_steps.py`.
- Slotted dataclass: each of the three valid-construction tests (one per value object) asserts that `entry.__class__.__dict__.get('__slots__')` is a non-empty tuple and that adding an unknown attribute via `setattr` raises `AttributeError`.
- Keyword-only construction: every test constructs via keyword.
- No shared `conftest.py`, no parametrize, no shared helper module. One test function per file.

## Validation commands the implementation task MUST run and capture

- `.venv/bin/python -m py_compile v2/backend/app/domain/replay_backtest_runner/__init__.py v2/backend/app/domain/replay_backtest_runner/errors.py v2/backend/app/domain/replay_backtest_runner/run.py v2/backend/app/domain/replay_backtest_runner/step.py v2/backend/app/domain/replay_backtest_runner/summary.py`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/replay_backtest_runner/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/paper_execution_ledger/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/risk_gateway/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/orchestrator_decision/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_prediction_output/ -q` (must remain green)
- For each forbidden token T from spec section "Forbidden tokens in source files": `rg --fixed-strings --case-sensitive T v2/backend/app/domain/replay_backtest_runner/` (must show zero matches per token; the test file uses runtime string concatenation so it does not contain the bare token)

PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_TEST_PLAN_READY
