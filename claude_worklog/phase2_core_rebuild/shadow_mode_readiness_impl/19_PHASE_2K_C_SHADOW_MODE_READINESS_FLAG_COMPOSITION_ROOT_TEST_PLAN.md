# Phase 2K.C — Shadow-Mode-Readiness Flag Composition Root Test Plan

All tests live under `v2/backend/tests/unit/composition/shadow_mode_readiness/`. Each test file contains exactly one test function whose name starts with `test_` and mirrors the file basename. No shared `conftest.py` is created or modified. Inline construction of the keyword arguments is required in each test that needs them; no helper module or fixture is added. Tests construct hand-written fakes inline. Tests MUST NOT import any 2J / 2I / 2H / 2G / 2F / 2E1 / 2E2 / 2E3 domain symbol; the 2K.C composition layer is decoupled from those upstream record types.

## Package marker

- `__init__.py` — empty file (zero bytes).

## Test files (exactly 22)

Surface tests:

1. `test_public_surface.py` — assert `__all__` of `v2.backend.app.composition.shadow_mode_readiness` equals `("build_shadow_mode_readiness_runtime", "ShadowModeReadinessRuntime", "ShadowModeReadinessRuntimeCompositionError")` exactly, including order; assert `build_shadow_mode_readiness_runtime` is callable; assert `ShadowModeReadinessRuntimeCompositionError` is a class and a subclass of `Exception` and is NOT a subclass of `ValueError`; assert `ShadowModeReadinessRuntime` is exported.

2. `test_errors_invariants.py` — instantiate `ShadowModeReadinessRuntimeCompositionError("some_code", field="some_field")`; assert `e.code == "some_code"`; assert `e.field == "some_field"`; assert `str(e) == "some_code (some_field)"`; assert calling without `field=` raises `TypeError` because `field` is required (no default); assert `repr(e) == "ShadowModeReadinessRuntimeCompositionError(code='some_code', field='some_field')"`.

3. `test_shadow_mode_readiness_runtime_class_invariants.py` — assert `ShadowModeReadinessRuntime.__slots__ == ("shadow_mode_readiness_now",)` exactly, including order; assert `hasattr(instance, "__dict__")` returns False on a constructed instance (confirming slotted-instance discipline); assert attaching a foreign attribute to a constructed instance raises `AttributeError`; assert the class has no class methods or static methods beyond `__init__` (compare against the public method introspection set); assert `ShadowModeReadinessRuntime` does NOT declare `__weakref__` in `__slots__`.

Import-clean tests (each test must reconstruct the forbidden literal at runtime via string concatenation so the test source file does not contain the bare token; each test launches a child interpreter via `subprocess.run([sys.executable, "-c", ...])`):

4. `test_init_module_does_not_load_redis.py` — purge any literal `"red" + "is"` prefixed and `v2.backend.app.composition.shadow_mode_readiness*` entries from `sys.modules` in the child interpreter, re-import the package, then assert no `sys.modules` key starts with the literal `"red" + "is"`.

5. `test_init_module_does_not_load_url_env.py` — purge any `v2.backend.app.adapters.redis_v2.url_env*` and `v2.backend.app.composition.shadow_mode_readiness*` entries from `sys.modules`, re-import the package, then assert no key containing the literal `"url" + "_env"` is present.

6. `test_init_module_does_not_register_fastapi_lifespan.py` — purge any `"fast" + "api"` prefixed and `v2.backend.app.composition.shadow_mode_readiness*` entries from `sys.modules`, re-import the package, then assert no `sys.modules` key starts with `"fast" + "api"`.

7. `test_runtime_module_does_not_load_redis_when_imported.py` — purge any `"red" + "is"` prefixed and `v2.backend.app.composition.shadow_mode_readiness.runtime` entries from `sys.modules`, then `import v2.backend.app.composition.shadow_mode_readiness.runtime`, then assert no `sys.modules` key starts with the literal `"red" + "is"`.

Forbidden-token scan tests:

8. `test_composition_milestone_forbidden_tokens.py` — read the bytes of `__init__.py`, `errors.py`, `runtime.py`. For each forbidden literal listed in spec 18 'Forbidden tokens in source files', reconstruct the literal at runtime via string concatenation and assert the literal does not appear in any of the three source files. Apply NO exemption. Reconstruction MUST cover `RiskDecisionRecord`, `OrchestratorDecisionRecord`, `RISK_DECISION_REASON_DENY_DEFAULT`, the lowercase `deny_default`, the literal `mirror_deny_default`, `PaperExecutionLedgerEntry`, `ReplayBacktestStep`, `ReplayBacktestSummary`, `ReplayBacktestRun`, `PaperModeFlag`, `sqlite`, `sqlalchemy`, `parquet`, the call-form token `ShadowModeReadinessFlag(`, the bare tokens `SHADOW_MODE_LIVE`, `SHADOW_MODE_LIVE_ENABLED`, `live_enabled`, `enable_live`, `shadow_decision_id`, and the harness framing tokens `BEGIN_FILE` and `END_FILE`.

9. `test_composition_does_not_import_url_env_directly.py` — open `runtime.py` and `__init__.py`, read source, assert neither file source contains the literal `"url" + "_env"` reconstructed at runtime.

Build-time validation tests for `now_ms_clock`:

10. `test_validates_now_ms_clock_callable.py` — call `build_shadow_mode_readiness_runtime(now_ms_clock=42)` and assert it raises `ShadowModeReadinessRuntimeCompositionError` with `code == "must_be_callable"` and `field == "now_ms_clock"`. Also pass `None` and re-assert the same exception, code, and field. Also pass the string `"not_callable"` and re-assert.

11. `test_returns_shadow_mode_readiness_runtime_instance.py` — pass `now_ms_clock=lambda: 123` and assert the return value is an instance of `ShadowModeReadinessRuntime`. Assert the returned object's `shadow_mode_readiness_now` attribute is callable. Assert the returned object's `shadow_mode_readiness_now` is NOT the input clock.

Build-time non-invocation tests:

12. `test_shadow_mode_readiness_now_not_invoked_at_build_time.py` — define a counter list `n=[0]` and a clock that increments it. Call `build_shadow_mode_readiness_runtime(now_ms_clock=...)`. Immediately after, assert `n == [0]` (the clock must NOT be called at build time). Also assert that no `ShadowModeReadinessFlag` was constructed at build time by checking that no flag-related side effect occurred.

Clock-identity sharing tests:

13. `test_shadow_mode_readiness_now_invokes_clock_exactly_once_per_call.py` — define a clock with a counter list. Build the runtime. Call `runtime.shadow_mode_readiness_now(requested_state="not_ready")` once. Assert the clock counter incremented to exactly 1, demonstrating the assembler ran exactly once and called the clock exactly once. Call again with `requested_state="ready"` and assert the counter increments to exactly 2.

14. `test_shadow_mode_readiness_now_returns_new_callable_not_input_clock.py` — pass `now_ms_clock_lambda=lambda: 999` (a uniquely identifiable lambda); build the runtime; assert `runtime.shadow_mode_readiness_now is not now_ms_clock_lambda` (the binder MUST return a NEW callable, not pass the clock through).

Step-assembler forwarding tests:

15. `test_shadow_mode_readiness_now_returns_shadow_mode_readiness_flag.py` — call `runtime.shadow_mode_readiness_now(requested_state="not_ready")` and assert the result is an instance of `ShadowModeReadinessFlag` (import `ShadowModeReadinessFlag` from `v2.backend.app.domain.shadow_mode_readiness`). Assert `result.state == "not_ready"` (the literal `"not_ready"` reconstructed at runtime via string concatenation if necessary), `result.live_blocked is True`, and `result.flag_emitted_ts_ms` equals the value returned by the captured clock at call time.

16. `test_shadow_mode_readiness_now_records_clock_into_flag_emitted_ts_ms.py` — pass `now_ms_clock=lambda: 1700000000000`, build the runtime, call `runtime.shadow_mode_readiness_now(requested_state="not_ready")`, assert `result.flag_emitted_ts_ms == 1700000000000`.

17. `test_shadow_mode_readiness_now_keyword_only_param.py` — call `runtime.shadow_mode_readiness_now("not_ready")` (one positional argument) and assert `TypeError` is raised, demonstrating the inner closure declares `requested_state` keyword-only.

18. `test_shadow_mode_readiness_now_does_not_mutate_supplied_input.py` — build with valid build args. Construct `requested_state = "not_ready"` and snapshot it. Call `runtime.shadow_mode_readiness_now(requested_state=requested_state)`. After the call, assert `requested_state == "not_ready"` and the original `id()` is preserved (strings are immutable, but the test asserts the inner closure does not rebind or coerce the supplied input).

Mirror-taxonomy mapping tests (exactly two valid states per the 2K.A constants `SHADOW_MODE_NOT_READY` and `SHADOW_MODE_READY`):

19. `test_shadow_mode_readiness_now_propagates_not_ready_state.py` — build the runtime with `now_ms_clock=lambda: 7`. Call `runtime.shadow_mode_readiness_now(requested_state="not_ready")`. Assert `result.state == "not_ready"`, `result.live_blocked is True`, `result.flag_emitted_ts_ms == 7`.

20. `test_shadow_mode_readiness_now_propagates_ready_state.py` — build the runtime with `now_ms_clock=lambda: 11`. Call `runtime.shadow_mode_readiness_now(requested_state="ready")`. Assert `result.state == "ready"`, `result.live_blocked is True`, `result.flag_emitted_ts_ms == 11`.

Error-propagation tests:

21. `test_shadow_mode_readiness_now_propagates_service_error_for_unrecognized_state.py` — build the runtime with valid build args; call `runtime.shadow_mode_readiness_now(requested_state="live")`; assert `ShadowModeReadinessServiceError` is raised with `code == "shadow_mode_readiness_service_unrecognized_requested_state"` and `field == "requested_state"`. Import `ShadowModeReadinessServiceError` from `v2.backend.app.services.shadow_mode_readiness`. The composition root MUST NOT catch or wrap the service error; the assertion verifies the service error class propagates unchanged. Also assert that the literals `"live_enabled"` and `"enable_live"` (reconstructed at runtime via string concatenation) are NOT accepted requested states (they raise the same service error), confirming there is no live-enable affordance at the composition layer.

22. `test_shadow_mode_readiness_now_propagates_service_error_for_non_string_state.py` — build the runtime with valid build args; call `runtime.shadow_mode_readiness_now(requested_state=123)`; assert `ShadowModeReadinessServiceError` is raised with `code == "must_be_str"` and `field == "requested_state"`. The composition root MUST NOT catch or wrap the service error.

## Test runner expectations

`.venv/bin/python -m pytest v2/backend/tests/unit/composition/shadow_mode_readiness/ -q` reports `22 passed` and exits 0 at implementation completion.

The 2K.B service suite, the 2K.A domain suite, the 2J.C composition suite, the 2J.B service suite, the 2J.A domain suite, the 2I.C composition suite, the 2I.B service suite, the 2I.A domain suite, the 2H.C composition suite, the 2H.B service suite, the 2H.A domain suite, the 2G.C composition suite, the 2G.B service suite, the 2G.A domain suite, the 2F.C composition suite, the 2F.B service suite, the 2F.A domain suite, and every 2E1 / 2E2 / 2E3 suite pass with zero regressions when run individually.

PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_TEST_PLAN_READY
