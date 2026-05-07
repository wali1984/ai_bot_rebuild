# Phase 2J.C — Paper Mode Runtime Flag Composition Root Test Plan

All tests live under `v2/backend/tests/unit/composition/paper_mode/`. Each test file contains exactly one test function whose name starts with `test_` and mirrors the file basename. No shared `conftest.py` is created or modified. Inline construction of the keyword arguments is required in each test that needs them; no helper module or fixture is added. Tests construct hand-written fakes inline. Tests MUST NOT import any 2I / 2H / 2G / 2F / 2E1 / 2E2 / 2E3 domain symbol; the 2J.C composition layer is decoupled from those upstream record types.

## Package marker

- `__init__.py` — empty file (zero bytes).

## Test files (exactly 22)

Surface tests:

1. `test_public_surface.py` — assert `__all__` of `v2.backend.app.composition.paper_mode` equals `("build_paper_mode_runtime", "PaperModeRuntime", "PaperModeRuntimeCompositionError")` exactly, including order; assert `build_paper_mode_runtime` is callable; assert `PaperModeRuntimeCompositionError` is a class and a subclass of `Exception` and is NOT a subclass of `ValueError`; assert `PaperModeRuntime` is exported.

2. `test_errors_invariants.py` — instantiate `PaperModeRuntimeCompositionError("some_code", field="some_field")`; assert `e.code == "some_code"`; assert `e.field == "some_field"`; assert `str(e) == "some_code (some_field)"`; assert calling without `field=` raises `TypeError` because `field` is required (no default); assert `repr(e) == "PaperModeRuntimeCompositionError(code='some_code', field='some_field')"`.

3. `test_paper_mode_runtime_class_invariants.py` — assert `PaperModeRuntime.__slots__ == ("paper_mode_now",)` exactly, including order; assert `hasattr(instance, "__dict__")` returns False on a constructed instance (confirming slotted-instance discipline); assert attaching a foreign attribute to a constructed instance raises `AttributeError`; assert the class has no class methods or static methods beyond `__init__` (compare against the public method introspection set); assert `PaperModeRuntime` does NOT declare `__weakref__` in `__slots__`.

Import-clean tests (each test must reconstruct the forbidden literal at runtime via string concatenation so the test source file does not contain the bare token; each test launches a child interpreter via `subprocess.run([sys.executable, "-c", ...])`):

4. `test_init_module_does_not_load_redis.py` — purge any literal `"red" + "is"` prefixed and `v2.backend.app.composition.paper_mode*` entries from `sys.modules` in the child interpreter, re-import the package, then assert no `sys.modules` key starts with the literal `"red" + "is"`.

5. `test_init_module_does_not_load_url_env.py` — purge any `v2.backend.app.adapters.redis_v2.url_env*` and `v2.backend.app.composition.paper_mode*` entries from `sys.modules`, re-import the package, then assert no key containing the literal `"url" + "_env"` is present.

6. `test_init_module_does_not_register_fastapi_lifespan.py` — purge any `"fast" + "api"` prefixed and `v2.backend.app.composition.paper_mode*` entries from `sys.modules`, re-import the package, then assert no `sys.modules` key starts with `"fast" + "api"`.

7. `test_runtime_module_does_not_load_redis_when_imported.py` — purge any `"red" + "is"` prefixed and `v2.backend.app.composition.paper_mode.runtime` entries from `sys.modules`, then `import v2.backend.app.composition.paper_mode.runtime`, then assert no `sys.modules` key starts with the literal `"red" + "is"`.

Forbidden-token scan tests:

8. `test_composition_milestone_forbidden_tokens.py` — read the bytes of `__init__.py`, `errors.py`, `runtime.py`. For each forbidden literal listed in spec 18 'Forbidden tokens in source files', reconstruct the literal at runtime via string concatenation and assert the literal does not appear in any of the three source files. Apply NO exemption. Reconstruction MUST cover `RiskDecisionRecord`, `OrchestratorDecisionRecord`, `RISK_DECISION_REASON_DENY_DEFAULT`, the lowercase `deny_default`, the literal `mirror_deny_default`, `PaperExecutionLedgerEntry`, `ReplayBacktestStep`, `ReplayBacktestSummary`, `ReplayBacktestRun`, `sqlite`, `sqlalchemy`, `parquet`, the call-form token `PaperModeFlag(`, and the harness framing tokens `BEGIN_FILE` and `END_FILE`.

9. `test_composition_does_not_import_url_env_directly.py` — open `runtime.py` and `__init__.py`, read source, assert neither file source contains the literal `"url" + "_env"` reconstructed at runtime.

Build-time validation tests for `now_ms_clock`:

10. `test_validates_now_ms_clock_callable.py` — call `build_paper_mode_runtime(now_ms_clock=42)` and assert it raises `PaperModeRuntimeCompositionError` with `code == "must_be_callable"` and `field == "now_ms_clock"`. Also pass `None` and re-assert the same exception, code, and field. Also pass the string `"not_callable"` and re-assert.

11. `test_returns_paper_mode_runtime_instance.py` — pass `now_ms_clock=lambda: 123` and assert the return value is an instance of `PaperModeRuntime`. Assert the returned object's `paper_mode_now` attribute is callable. Assert the returned object's `paper_mode_now` is NOT the input clock.

Build-time non-invocation tests:

12. `test_paper_mode_now_not_invoked_at_build_time.py` — define a counter list `n=[0]` and a clock that increments it. Call `build_paper_mode_runtime(now_ms_clock=...)`. Immediately after, assert `n == [0]` (the clock must NOT be called at build time). Also assert that no `PaperModeFlag` was constructed at build time by checking that no flag-related side effect occurred.

Clock-identity sharing tests:

13. `test_paper_mode_now_invokes_clock_exactly_once_per_call.py` — define a clock with a counter list. Build the runtime. Call `runtime.paper_mode_now(requested_mode="paper")` once. Assert the clock counter incremented to exactly 1, demonstrating the assembler ran exactly once and called the clock exactly once. Call again with `requested_mode="live_blocked"` and assert the counter increments to exactly 2.

14. `test_paper_mode_now_returns_new_callable_not_input_clock.py` — pass `now_ms_clock_lambda=lambda: 999` (a uniquely identifiable lambda); build the runtime; assert `runtime.paper_mode_now is not now_ms_clock_lambda` (the binder MUST return a NEW callable, not pass the clock through).

Step-assembler forwarding tests:

15. `test_paper_mode_now_returns_paper_mode_flag.py` — call `runtime.paper_mode_now(requested_mode="paper")` and assert the result is an instance of `PaperModeFlag` (import `PaperModeFlag` from `v2.backend.app.domain.paper_mode`). Assert `result.mode == "paper"` (the literal `"paper"` reconstructed at runtime via string concatenation if necessary), `result.live_blocked is True`, and `result.flag_emitted_ts_ms` equals the value returned by the captured clock at call time.

16. `test_paper_mode_now_records_clock_into_flag_emitted_ts_ms.py` — pass `now_ms_clock=lambda: 1700000000000`, build the runtime, call `runtime.paper_mode_now(requested_mode="paper")`, assert `result.flag_emitted_ts_ms == 1700000000000`.

17. `test_paper_mode_now_keyword_only_param.py` — call `runtime.paper_mode_now("paper")` (one positional argument) and assert `TypeError` is raised, demonstrating the inner closure declares `requested_mode` keyword-only.

18. `test_paper_mode_now_does_not_mutate_supplied_input.py` — build with valid build args. Construct `requested_mode = "paper"` and snapshot it. Call `runtime.paper_mode_now(requested_mode=requested_mode)`. After the call, assert `requested_mode == "paper"` and the original `id()` is preserved (strings are immutable, but the test asserts the inner closure does not rebind or coerce the supplied input).

Mirror-taxonomy mapping tests (exactly two valid modes per the 2J.A constants `PAPER_MODE_PAPER` and `PAPER_MODE_LIVE_BLOCKED`):

19. `test_paper_mode_now_propagates_paper_mode.py` — build the runtime with `now_ms_clock=lambda: 7`. Call `runtime.paper_mode_now(requested_mode="paper")`. Assert `result.mode == "paper"`, `result.live_blocked is True`, `result.flag_emitted_ts_ms == 7`.

20. `test_paper_mode_now_propagates_live_blocked_mode.py` — build the runtime with `now_ms_clock=lambda: 11`. Call `runtime.paper_mode_now(requested_mode="live_blocked")`. Assert `result.mode == "live_blocked"`, `result.live_blocked is True`, `result.flag_emitted_ts_ms == 11`.

Error-propagation tests:

21. `test_paper_mode_now_propagates_service_error_for_unrecognized_mode.py` — build the runtime with valid build args; call `runtime.paper_mode_now(requested_mode="live")`; assert `PaperModeServiceError` is raised with `code == "paper_mode_service_unrecognized_requested_mode"` and `field == "requested_mode"`. Import `PaperModeServiceError` from `v2.backend.app.services.paper_mode`. The composition root MUST NOT catch or wrap the service error; the assertion verifies the service error class propagates unchanged. Also assert that the literal `"live_enabled"` and `"enable_live"` (reconstructed at runtime via string concatenation) are NOT accepted modes (they raise the same service error), confirming there is no live-enable affordance at the composition layer.

22. `test_paper_mode_now_propagates_service_error_for_non_string_mode.py` — build the runtime with valid build args; call `runtime.paper_mode_now(requested_mode=123)`; assert `PaperModeServiceError` is raised with `code == "must_be_str"` and `field == "requested_mode"`. The composition root MUST NOT catch or wrap the service error.

## Test runner expectations

`.venv/bin/python -m pytest v2/backend/tests/unit/composition/paper_mode/ -q` reports `22 passed` and exits 0 at implementation completion.

The 2J.B service suite, the 2J.A domain suite, the 2I.C composition suite, the 2I.B service suite, the 2I.A domain suite, the 2H.C composition suite, the 2H.B service suite, the 2H.A domain suite, the 2G.C composition suite, the 2G.B service suite, the 2G.A domain suite, the 2F.C composition suite, the 2F.B service suite, the 2F.A domain suite, and every 2E1 / 2E2 / 2E3 suite pass with zero regressions when run individually.

PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_TEST_PLAN_READY
