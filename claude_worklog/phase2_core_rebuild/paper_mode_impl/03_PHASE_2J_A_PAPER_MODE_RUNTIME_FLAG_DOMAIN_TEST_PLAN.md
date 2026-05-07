# Phase 2J.A — Paper-Mode Runtime-Flag Domain Test Plan

This document enumerates the exact test files emitted by Phase 2J.A under `v2/backend/tests/unit/domain/paper_mode/`. Each test file contains exactly one test function. There is no shared `conftest.py`. All `PaperModeFlag` instances are constructed by keyword. No fixture, no parametrize, no shared helper module.

## Test files (exactly 27, including a zero-byte `__init__.py`)

1. `__init__.py` — zero bytes.

### Public surface and module-load isolation (12)

2. `test_public_surface.py` — verifies `__all__` of `v2.backend.app.domain.paper_mode` equals the 4-tuple `("PaperModeDomainError", "PaperModeFlag", "PAPER_MODE_PAPER", "PAPER_MODE_LIVE_BLOCKED")`, in order, with no extras.
3. `test_init_module_does_not_load_redis.py` — subprocess `python -c "import sys; import v2.backend.app.domain.paper_mode; assert 'redis' not in sys.modules and 'redis.asyncio' not in sys.modules and 'aioredis' not in sys.modules and 'hiredis' not in sys.modules"`; asserts return code 0.
4. `test_init_module_does_not_load_url_env.py` — subprocess assertion that `'v2.backend.app.adapters.redis_v2.url_env'` is NOT in `sys.modules` after import.
5. `test_init_module_does_not_register_fastapi_lifespan.py` — subprocess assertion that `'fastapi'`, `'uvicorn'`, and `'starlette'` are NOT in `sys.modules` after import.
6. `test_flag_module_does_not_load_redis_when_imported.py` — subprocess assertion that importing `v2.backend.app.domain.paper_mode.flag` directly does NOT load redis/aioredis/hiredis.
7. `test_domain_module_does_not_import_paper_execution_ledger.py` — subprocess assertion that `'v2.backend.app.domain.paper_execution_ledger'` is NOT in `sys.modules` after importing the package.
8. `test_domain_module_does_not_import_replay_backtest_runner.py` — subprocess assertion that `'v2.backend.app.domain.replay_backtest_runner'` is NOT in `sys.modules` after import.
9. `test_domain_module_does_not_import_risk_gateway.py` — subprocess assertion that `'v2.backend.app.domain.risk_gateway'` is NOT in `sys.modules` after import.
10. `test_domain_module_does_not_import_orchestrator_decision.py` — subprocess assertion that `'v2.backend.app.domain.orchestrator_decision'` is NOT in `sys.modules` after import.
11. `test_domain_module_does_not_import_trainer_prediction_output.py` — subprocess assertion that `'v2.backend.app.domain.trainer_prediction_output'` is NOT in `sys.modules` after import.
12. `test_domain_module_does_not_import_replay_placeholder.py` — subprocess assertion that `'v2.backend.app.domain.replay'` is NOT in `sys.modules` after import.
13. `test_domain_module_does_not_import_execution_placeholder.py` — subprocess assertion that `'v2.backend.app.domain.execution'` is NOT in `sys.modules` after import.

### Forbidden-token scan and constants (4)

14. `test_forbidden_tokens_not_present.py` — for each forbidden token enumerated in spec section "Forbidden tokens in source files", reads the three authored source files via `pathlib.Path.read_text` and asserts the token (constructed at runtime via string concatenation) is NOT a substring. One token per assertion. The test file does NOT contain the bare forbidden token literals.
15. `test_no_live_enabled_constant_in_module.py` — asserts that `hasattr(v2.backend.app.domain.paper_mode, "PAPER_MODE_LIVE_ENABLED") is False` AND `hasattr(v2.backend.app.domain.paper_mode, "live_enabled") is False` AND `hasattr(v2.backend.app.domain.paper_mode, "PAPER_MODE_LIVE") is False` AND `"PAPER_MODE_LIVE_ENABLED" not in v2.backend.app.domain.paper_mode.__all__` AND `"live_enabled" not in v2.backend.app.domain.paper_mode.__all__` AND `"PAPER_MODE_LIVE" not in v2.backend.app.domain.paper_mode.__all__`.
16. `test_mode_constants_lowercase_and_unique.py` — asserts both mode constants equal their own `.lower()`, are non-empty `str`, and the 2-tuple `(PAPER_MODE_PAPER, PAPER_MODE_LIVE_BLOCKED)` has 2 distinct members.
17. `test_mode_constants_have_expected_string_values.py` — asserts `PAPER_MODE_PAPER == "paper"` AND `PAPER_MODE_LIVE_BLOCKED == "live_blocked"`.

### PaperModeFlag construction (10)

18. `test_flag_constructs_with_paper_mode.py` — constructs a flag with `mode="paper"`, `flag_emitted_ts_ms=1730000000000`, `live_blocked=True`; asserts no exception, field round-trip, and `dataclasses.FrozenInstanceError` on attempted mutation. Asserts that `flag.__class__.__dict__.get('__slots__')` is a non-empty tuple and that adding an unknown attribute via `setattr` raises `AttributeError`.
19. `test_flag_constructs_with_live_blocked_mode.py` — constructs a flag with `mode="live_blocked"`, `flag_emitted_ts_ms=1730000000000`, `live_blocked=True`; asserts success and field round-trip.
20. `test_flag_rejects_unknown_mode.py` — asserts `PaperModeDomainError` with `reason == "paper_mode_flag_unknown_mode"` and `field == "mode"` when `mode == "live"`.
21. `test_flag_rejects_live_enabled_mode.py` — asserts `PaperModeDomainError` with `reason == "paper_mode_flag_unknown_mode"` and `field == "mode"` when `mode == "live_enabled"`. The test exists explicitly to lock in the absence of any live-execution affordance at the 2J.A layer.
22. `test_flag_rejects_uppercase_mode.py` — asserts `PaperModeDomainError` with `field == "mode"` when `mode == "PAPER"` (must be lowercase string-literal match).
23. `test_flag_rejects_empty_mode.py` — asserts `PaperModeDomainError` with `field == "mode"` when `mode == ""`.
24. `test_flag_rejects_negative_flag_emitted_ts_ms.py` — asserts `PaperModeDomainError` with `reason == "paper_mode_flag_emitted_ts_ms_must_be_non_negative_int"` and `field == "flag_emitted_ts_ms"` when `flag_emitted_ts_ms == -1`.
25. `test_flag_rejects_bool_for_flag_emitted_ts_ms.py` — asserts `PaperModeDomainError` with `field == "flag_emitted_ts_ms"` when `flag_emitted_ts_ms is True`.
26. `test_flag_rejects_float_for_flag_emitted_ts_ms.py` — asserts `PaperModeDomainError` with `field == "flag_emitted_ts_ms"` when `flag_emitted_ts_ms == 1730000000000.5`.
27. `test_flag_rejects_live_blocked_false.py` — asserts `PaperModeDomainError` with `reason == "paper_mode_flag_requires_live_blocked_true"` and `field == "live_blocked"` when `live_blocked == False`.

## Properties enforced across the suite

- Frozen dataclass: a separate assertion inside `test_flag_constructs_with_paper_mode.py` attempts `flag.mode = "x"` and expects `dataclasses.FrozenInstanceError`. An equivalent assertion exists inside `test_flag_constructs_with_live_blocked_mode.py`.
- Slotted dataclass: each of the two valid-construction tests asserts that `flag.__class__.__dict__.get('__slots__')` is a non-empty tuple and that adding an unknown attribute via `setattr` raises `AttributeError`.
- Keyword-only construction: every test constructs via keyword.
- No shared `conftest.py`, no parametrize, no shared helper module. One test function per file.

## Validation commands the implementation task MUST run and capture

- `.venv/bin/python -m py_compile v2/backend/app/domain/paper_mode/__init__.py v2/backend/app/domain/paper_mode/errors.py v2/backend/app/domain/paper_mode/flag.py`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/paper_mode/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/replay_backtest_runner/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/paper_execution_ledger/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/risk_gateway/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/orchestrator_decision/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_prediction_output/ -q` (must remain green)
- For each forbidden token T from spec section "Forbidden tokens in source files": `rg --fixed-strings --case-sensitive T v2/backend/app/domain/paper_mode/` (must show zero matches per token; the test file uses runtime string concatenation so it does not contain the bare token)

PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_TEST_PLAN_READY
