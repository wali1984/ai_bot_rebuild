# Phase 2K.B — Shadow-Mode-Readiness Flag Assembler Service Test Plan

This document enumerates the exact set of test files to be authored at `v2/backend/tests/unit/services/shadow_mode_readiness/`. The test package marker `__init__.py` is the 31st file. Each test file contains exactly one test function. There is no shared `conftest.py`. Test value-object construction is inline; no fixtures.

## Test files (exactly 30 plus a zero-byte `__init__.py`)

1. `__init__.py` (zero bytes)
2. `test_public_surface.py`
3. `test_assembler_service_does_not_import_redis.py`
4. `test_assembler_service_does_not_import_url_env.py`
5. `test_assembler_service_does_not_register_fastapi_lifespan.py`
6. `test_assembler_service_does_not_import_paper_mode.py`
7. `test_assembler_service_does_not_import_paper_execution_ledger.py`
8. `test_assembler_service_does_not_import_replay_backtest_runner.py`
9. `test_assembler_service_does_not_import_risk_gateway.py`
10. `test_assembler_service_does_not_import_orchestrator_decision.py`
11. `test_assembler_service_does_not_import_trainer_prediction_output.py`
12. `test_assembler_service_does_not_import_replay_placeholder.py`
13. `test_assembler_service_does_not_import_execution_placeholder.py`
14. `test_assembler_service_forbidden_tokens.py`
15. `test_errors_invariants.py`
16. `test_assemble_keyword_only_params.py`
17. `test_assemble_calls_clock_exactly_once.py`
18. `test_assemble_records_clock_into_flag_emitted_ts_ms.py`
19. `test_assemble_rejects_non_str_requested_state.py`
20. `test_assemble_rejects_bool_requested_state.py`
21. `test_assemble_rejects_non_callable_clock.py`
22. `test_assemble_rejects_clock_returning_non_int.py`
23. `test_assemble_rejects_clock_returning_bool.py`
24. `test_assemble_rejects_clock_returning_negative.py`
25. `test_assemble_returns_flag_for_not_ready_requested_state.py`
26. `test_assemble_returns_flag_for_ready_requested_state.py`
27. `test_assemble_returns_frozen_flag.py`
28. `test_assemble_rejects_unrecognized_requested_state.py`
29. `test_assemble_rejects_live_requested_state.py`
30. `test_assemble_rejects_live_enabled_requested_state.py`
31. `test_assemble_rejects_uppercase_requested_state.py`

## Test contracts (per file, one test function each)

### test_public_surface.py

Imports `v2.backend.app.services.shadow_mode_readiness` and asserts that `__all__` equals exactly the 2-tuple `("assemble_shadow_mode_readiness_flag", "ShadowModeReadinessServiceError")` in that order. Asserts the function name is callable. Asserts `ShadowModeReadinessServiceError` is a subclass of `ValueError`.

### test_assembler_service_does_not_import_redis.py

Spawns a fresh subprocess via `subprocess.run([sys.executable, "-c", ...])` that imports `v2.backend.app.services.shadow_mode_readiness` and prints a Python list of forbidden module names that appear in `sys.modules`. Forbidden names: `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`, `requests`, `fastapi`, `uvicorn`, `starlette`, `asyncio`, `threading`, and `v2.backend.app.adapters.redis_v2.url_env`. Asserts the printed list is empty.

### test_assembler_service_does_not_import_url_env.py

Spawns a fresh subprocess that imports the assembler package and asserts `v2.backend.app.adapters.redis_v2.url_env` is NOT in `sys.modules`.

### test_assembler_service_does_not_register_fastapi_lifespan.py

Spawns a fresh subprocess that imports the assembler package and asserts that `fastapi`, `uvicorn`, and `starlette` are NOT in `sys.modules` and that no module-level callable named `lifespan` exists in `v2.backend.app.services.shadow_mode_readiness`.

### test_assembler_service_does_not_import_paper_mode.py

Spawns a fresh subprocess that imports the assembler package and asserts `v2.backend.app.domain.paper_mode` is NOT in `sys.modules`.

### test_assembler_service_does_not_import_paper_execution_ledger.py

Spawns a fresh subprocess that imports the assembler package and asserts `v2.backend.app.domain.paper_execution_ledger` is NOT in `sys.modules`.

### test_assembler_service_does_not_import_replay_backtest_runner.py

Spawns a fresh subprocess that imports the assembler package and asserts `v2.backend.app.domain.replay_backtest_runner` is NOT in `sys.modules`.

### test_assembler_service_does_not_import_risk_gateway.py

Spawns a fresh subprocess that imports the assembler package and asserts `v2.backend.app.domain.risk_gateway` is NOT in `sys.modules`.

### test_assembler_service_does_not_import_orchestrator_decision.py

Spawns a fresh subprocess that imports the assembler package and asserts `v2.backend.app.domain.orchestrator_decision` is NOT in `sys.modules`.

### test_assembler_service_does_not_import_trainer_prediction_output.py

Spawns a fresh subprocess that imports the assembler package and asserts `v2.backend.app.domain.trainer_prediction_output` is NOT in `sys.modules`.

### test_assembler_service_does_not_import_replay_placeholder.py

Spawns a fresh subprocess that imports the assembler package and asserts `v2.backend.app.domain.replay` is NOT in `sys.modules`.

### test_assembler_service_does_not_import_execution_placeholder.py

Spawns a fresh subprocess that imports the assembler package and asserts `v2.backend.app.domain.execution` is NOT in `sys.modules`.

### test_assembler_service_forbidden_tokens.py

Reads `__init__.py`, `errors.py`, and `service.py` as text via `pathlib.Path.read_text`. For each forbidden token in spec section "Forbidden tokens in source files", asserts the token does NOT appear in any of the three files. Tokens are constructed at runtime via string concatenation. Includes a separate assertion that `rg`-equivalent substring search confirms both the bare token reconstructed at runtime as `"SHADOW_MODE_LIVE"` and the bare token reconstructed at runtime as `"SHADOW_MODE_LIVE_" + "ENABLED"` return zero matches.

### test_errors_invariants.py

Constructs `ShadowModeReadinessServiceError("must_be_str", field="requested_state")` and asserts `.code == "must_be_str"`, `.field == "requested_state"`, `str(e) == "must_be_str (requested_state)"`, `repr(e) == "ShadowModeReadinessServiceError(code='must_be_str', field='requested_state')"`, and `isinstance(e, ValueError) is True`.

### test_assemble_keyword_only_params.py

Asserts that `assemble_shadow_mode_readiness_flag("not_ready", lambda: 1)` (positional) raises `TypeError`. Asserts that the same call with all keyword arguments succeeds (using a happy-path `requested_state="not_ready"` and a lambda clock returning a fixed int that satisfies the non-negative guard).

### test_assemble_calls_clock_exactly_once.py

Constructs a counter clock that increments a list on each call and returns `1000` on the first call and `999_999_999` thereafter. Calls the assembler once with `requested_state="not_ready"` and asserts the counter list has length 1. Asserts the returned `flag_emitted_ts_ms == 1000`.

### test_assemble_records_clock_into_flag_emitted_ts_ms.py

Constructs a clock returning a fixed `42`. Calls the assembler with `requested_state="not_ready"`. Asserts the returned flag's `flag_emitted_ts_ms == 42`.

### test_assemble_rejects_non_str_requested_state.py

Calls the assembler with `requested_state=42` and `requested_state=None` and asserts each raises `ShadowModeReadinessServiceError` with `code="must_be_str"` and `field="requested_state"`.

### test_assemble_rejects_bool_requested_state.py

Calls the assembler with `requested_state=True` and `requested_state=False` and asserts each raises `ShadowModeReadinessServiceError` with `code="must_be_str"` and `field="requested_state"`. The test exists explicitly because `bool` is a subclass of `int` (not `str`); the rejection is by the `type(requested_state) is str` check, which excludes `bool`.

### test_assemble_rejects_non_callable_clock.py

Calls the assembler with `now_ms_clock=42` (non-callable) and asserts `ShadowModeReadinessServiceError` with `code="must_be_callable"` and `field="now_ms_clock"`.

### test_assemble_rejects_clock_returning_non_int.py

Calls the assembler with `now_ms_clock=lambda: 1.0` and asserts `ShadowModeReadinessServiceError` with `code="must_be_int"` and `field="now_ms_clock"`. Also tests `lambda: "100"`.

### test_assemble_rejects_clock_returning_bool.py

Calls the assembler with `now_ms_clock=lambda: True` and asserts `ShadowModeReadinessServiceError` with `code="must_be_int"` and `field="now_ms_clock"`. The test exists explicitly because `bool` is a subclass of `int`; the rejection is by the `isinstance(value, bool)` check that runs before the `type(value) is int` check.

### test_assemble_rejects_clock_returning_negative.py

Calls the assembler with `now_ms_clock=lambda: -1` and asserts `ShadowModeReadinessServiceError` with `code="must_be_nonnegative"` and `field="now_ms_clock"`.

### test_assemble_returns_flag_for_not_ready_requested_state.py

Constructs a clock returning `1000`. Calls the assembler with `requested_state="not_ready"`. Asserts the returned flag has `state == "not_ready"`, `flag_emitted_ts_ms == 1000`, and `live_blocked is True`. Asserts the returned object is an instance of `v2.backend.app.domain.shadow_mode_readiness.ShadowModeReadinessFlag`.

### test_assemble_returns_flag_for_ready_requested_state.py

Constructs a clock returning `2000`. Calls the assembler with `requested_state="ready"`. Asserts the returned flag has `state == "ready"`, `flag_emitted_ts_ms == 2000`, and `live_blocked is True`. Asserts the returned object is an instance of `v2.backend.app.domain.shadow_mode_readiness.ShadowModeReadinessFlag`.

### test_assemble_returns_frozen_flag.py

Calls the assembler with a happy-path `requested_state="not_ready"` and asserts that assignment to any field of the returned flag raises `dataclasses.FrozenInstanceError`. Asserts that `flag.__class__.__dict__.get('__slots__')` is a non-empty tuple and that adding an unknown attribute via `setattr` raises `AttributeError`.

### test_assemble_rejects_unrecognized_requested_state.py

Calls the assembler with `requested_state="foo_bar_synthetic"` and asserts `ShadowModeReadinessServiceError` with `code="shadow_mode_readiness_service_unrecognized_requested_state"` and `field="requested_state"`.

### test_assemble_rejects_live_requested_state.py

Calls the assembler with `requested_state="live"` and asserts `ShadowModeReadinessServiceError` with `code="shadow_mode_readiness_service_unrecognized_requested_state"` and `field="requested_state"`. The test exists explicitly to lock in the absence of any live-execution affordance at the 2K.B service layer.

### test_assemble_rejects_live_enabled_requested_state.py

Calls the assembler with the literal value reconstructed at runtime as `"live" + "_enabled"` and asserts `ShadowModeReadinessServiceError` with `code="shadow_mode_readiness_service_unrecognized_requested_state"` and `field="requested_state"`. The test exists explicitly to lock in the absence of any live-execution affordance at the 2K.B service layer; the source file does NOT contain the bare token `live_enabled`.

### test_assemble_rejects_uppercase_requested_state.py

Calls the assembler with `requested_state="NOT_READY"` and asserts `ShadowModeReadinessServiceError` with `code="shadow_mode_readiness_service_unrecognized_requested_state"` and `field="requested_state"`. Asserts the same outcome for `requested_state="READY"` and for `requested_state=""` (the empty string is rejected by the same allowed-set membership check).

## Properties enforced across the suite

- Frozen dataclass: a separate assertion inside `test_assemble_returns_frozen_flag.py` attempts `flag.state = "x"` and expects `dataclasses.FrozenInstanceError`.
- Slotted dataclass: the frozen-flag test asserts that `flag.__class__.__dict__.get('__slots__')` is a non-empty tuple and that adding an unknown attribute via `setattr` raises `AttributeError`.
- Keyword-only construction: every test constructs by keyword.
- No shared `conftest.py`, no `parametrize`, no shared helper module. One test function per file.
- Inline value-object construction. No fixtures.

## Validation commands the implementation task MUST run and capture

- `.venv/bin/python -m py_compile v2/backend/app/services/shadow_mode_readiness/__init__.py v2/backend/app/services/shadow_mode_readiness/errors.py v2/backend/app/services/shadow_mode_readiness/service.py`
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/shadow_mode_readiness/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/shadow_mode_readiness/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/paper_mode/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/paper_mode/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/replay_backtest_runner/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/paper_execution_ledger/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/risk_gateway/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/orchestrator_decision/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/trainer_prediction_output/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/replay_backtest_runner/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/paper_execution_ledger/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/risk_gateway/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/orchestrator_decision/ -q` (must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_prediction_output/ -q` (must remain green)
- For each forbidden token T from spec section "Forbidden tokens in source files": `rg --fixed-strings --case-sensitive T v2/backend/app/services/shadow_mode_readiness/` (must show zero matches per token; both `SHADOW_MODE_LIVE` and `SHADOW_MODE_LIVE_ENABLED` return zero matches; the test file uses runtime string concatenation so it does not contain the bare token).

PHASE2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_TEST_PLAN_READY
