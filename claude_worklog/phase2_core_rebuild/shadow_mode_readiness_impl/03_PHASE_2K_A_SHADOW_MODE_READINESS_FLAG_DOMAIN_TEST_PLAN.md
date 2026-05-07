# Phase 2K.A — Shadow-Mode-Readiness Flag Domain Test Plan

This document enumerates the exact test files emitted by Phase 2K.A under `v2/backend/tests/unit/domain/shadow_mode_readiness/`. Each test file contains exactly one test function. There is no shared `conftest.py`. All `ShadowModeReadinessFlag` instances are constructed by keyword. No fixture, no parametrize, no shared helper module.

## Test files (exactly 27, including a zero-byte `__init__.py`)

1. `__init__.py` — zero bytes.

### Public surface and module-load isolation (12)

2. `test_public_surface.py` — verifies `__all__` of `v2.backend.app.domain.shadow_mode_readiness` equals the 4-tuple `("ShadowModeReadinessDomainError", "ShadowModeReadinessFlag", "SHADOW_MODE_NOT_READY", "SHADOW_MODE_READY")`, in order, with no extras.
3. `test_init_module_does_not_load_redis.py` — subprocess `python -c "import sys; import v2.backend.app.domain.shadow_mode_readiness; assert 'redis' not in sys.modules and 'redis.asyncio' not in sys.modules and 'aioredis' not in sys.modules and 'hiredis' not in sys.modules"`; asserts return code 0.
4. `test_init_module_does_not_load_url_env.py` — subprocess assertion that `'v2.backend.app.adapters.redis_v2.url_env'` is NOT in `sys.modules` after import.
5. `test_init_module_does_not_register_fastapi_lifespan.py` — subprocess assertion that `'fastapi'`, `'uvicorn'`, and `'starlette'` are NOT in `sys.modules` after import.
6. `test_flag_module_does_not_load_redis_when_imported.py` — subprocess assertion that importing `v2.backend.app.domain.shadow_mode_readiness.flag` directly does NOT load redis/aioredis/hiredis.
7. `test_domain_module_does_not_import_paper_mode.py` — subprocess assertion that `'v2.backend.app.domain.paper_mode'` is NOT in `sys.modules` after importing the package.
8. `test_domain_module_does_not_import_paper_execution_ledger.py` — subprocess assertion that `'v2.backend.app.domain.paper_execution_ledger'` is NOT in `sys.modules` after import.
9. `test_domain_module_does_not_import_replay_backtest_runner.py` — subprocess assertion that `'v2.backend.app.domain.replay_backtest_runner'` is NOT in `sys.modules` after import.
10. `test_domain_module_does_not_import_risk_gateway.py` — subprocess assertion that `'v2.backend.app.domain.risk_gateway'` is NOT in `sys.modules` after import.
11. `test_domain_module_does_not_import_orchestrator_decision.py` — subprocess assertion that `'v2.backend.app.domain.orchestrator_decision'` is NOT in `sys.modules` after import.
12. `test_domain_module_does_not_import_trainer_prediction_output.py` — subprocess assertion that `'v2.backend.app.domain.trainer_prediction_output'` is NOT in `sys.modules` after import.
13. `test_domain_module_does_not_import_replay_or_execution_placeholder.py` — subprocess assertion that `'v2.backend.app.domain.replay'` is NOT in `sys.modules` AND `'v2.backend.app.domain.execution'` is NOT in `sys.modules` after import.

### Forbidden-token scan and constants (4)

14. `test_forbidden_tokens_not_present.py` — for each forbidden token enumerated in spec section "Forbidden tokens in source files", reads the three authored source files via `pathlib.Path.read_text` and asserts the token (constructed at runtime via string concatenation) is NOT a substring. One token per assertion. The test file does NOT contain the bare forbidden token literals.
15. `test_no_live_enabled_constant_in_module.py` — asserts that `hasattr(v2.backend.app.domain.shadow_mode_readiness, "SHADOW_MODE_LIVE_ENABLED") is False` AND `hasattr(v2.backend.app.domain.shadow_mode_readiness, "live_enabled") is False` AND `hasattr(v2.backend.app.domain.shadow_mode_readiness, "SHADOW_MODE_LIVE") is False` AND `"SHADOW_MODE_LIVE_ENABLED" not in v2.backend.app.domain.shadow_mode_readiness.__all__` AND `"live_enabled" not in v2.backend.app.domain.shadow_mode_readiness.__all__` AND `"SHADOW_MODE_LIVE" not in v2.backend.app.domain.shadow_mode_readiness.__all__`.
16. `test_state_constants_lowercase_and_unique.py` — asserts both state constants equal their own `.lower()`, are non-empty `str`, and the 2-tuple `(SHADOW_MODE_NOT_READY, SHADOW_MODE_READY)` has 2 distinct members.
17. `test_state_constants_have_expected_string_values.py` — asserts `SHADOW_MODE_NOT_READY == "not_ready"` AND `SHADOW_MODE_READY == "ready"`.

### ShadowModeReadinessFlag construction (10)

18. `test_flag_constructs_with_not_ready_state.py` — constructs a flag with `state="not_ready"`, `flag_emitted_ts_ms=1730000000000`, `live_blocked=True`; asserts no exception, field round-trip, and `dataclasses.FrozenInstanceError` on attempted mutation. Asserts that `flag.__class__.__dict__.get('__slots__')` is a non-empty tuple and that adding an unknown attribute via `setattr` raises `AttributeError`.
19. `test_flag_constructs_with_ready_state.py` — constructs a flag with `state="ready"`, `flag_emitted_ts_ms=1730000000000`, `live_blocked=True`; asserts success, field round-trip, `FrozenInstanceError` on attempted mutation, and the slot/setattr properties.
20. `test_flag_rejects_unknown_state.py` — asserts `ShadowModeReadinessDomainError` with `reason == "shadow_mode_readiness_flag_unknown_state"` and `field == "state"` when `state == "live"`.
21. `test_flag_rejects_live_enabled_state.py` — asserts `ShadowModeReadinessDomainError` with `reason == "shadow_mode_readiness_flag_unknown_state"` and `field == "state"` when `state == "live_enabled"`. The test exists explicitly to lock in the absence of any live-execution affordance at the 2K.A layer.
22. `test_flag_rejects_uppercase_state.py` — asserts `ShadowModeReadinessDomainError` with `field == "state"` when `state == "READY"` (must be lowercase string-literal match).
23. `test_flag_rejects_empty_state.py` — asserts `ShadowModeReadinessDomainError` with `field == "state"` when `state == ""`.
24. `test_flag_rejects_negative_flag_emitted_ts_ms.py` — asserts `ShadowModeReadinessDomainError` with `reason == "shadow_mode_readiness_flag_emitted_ts_ms_must_be_non_negative_int"` and `field == "flag_emitted_ts_ms"` when `flag_emitted_ts_ms == -1`.
25. `test_flag_rejects_bool_for_flag_emitted_ts_ms.py` — asserts `ShadowModeReadinessDomainError` with `field == "flag_emitted_ts_ms"` when `flag_emitted_ts_ms is True`.
26. `test_flag_rejects_float_for_flag_emitted_ts_ms.py` — asserts `ShadowModeReadinessDomainError` with `field == "flag_emitted_ts_ms"` when `flag_emitted_ts_ms == 1730000000000.5`.
27. `test_flag_rejects_live_blocked_false.py` — asserts `ShadowModeReadinessDomainError` with `reason == "shadow_mode_readiness_flag_requires_live_blocked_true"` and `field == "live_blocked"` when `live_blocked == False`.

## Properties enforced across the suite

- Frozen dataclass: a separate assertion inside `test_flag_constructs_with_not_ready_state.py` attempts `flag.state = "x"` and expects `dataclasses.FrozenInstanceError`. An equivalent assertion exists inside `test_flag_constructs_with_ready_state.py`.
- Slotted dataclass: each of the two valid-construction tests asserts that `flag.__class__.__dict__.get('__slots__')` is a non-empty tuple and that adding an unknown attribute via `setattr` raises `AttributeError`.
- Keyword-only construction: every test constructs via keyword.
- No shared `conftest.py`, no parametrize, no shared helper module. One test function per file.

## Validation commands the implementation task MUST run and capture

- `.venv/bin/python -m py_compile v2/backend/app/domain/shadow_mode_readiness/__init__.py v2/backend/app/domain/shadow_mode_readiness/errors.py v2/backend/app/domain/shadow_mode_readiness/flag.py`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/shadow_mode_readiness/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/paper_mode/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/replay_backtest_runner/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/paper_execution_ledger/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/risk_gateway/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/orchestrator_decision/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_prediction_output/ -q` (must remain green)
- For each forbidden token T from spec section "Forbidden tokens in source files": `rg --fixed-strings --case-sensitive T v2/backend/app/domain/shadow_mode_readiness/` (must show zero matches per token; the test file uses runtime string concatenation so it does not contain the bare token)

PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_TEST_PLAN_READY
