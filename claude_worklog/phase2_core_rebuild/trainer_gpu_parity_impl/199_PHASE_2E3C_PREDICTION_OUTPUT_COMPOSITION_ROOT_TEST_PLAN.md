# Phase 2E3.C — Trainer Prediction Output Composition Root Test Plan

All tests live under `v2/backend/tests/unit/composition/trainer_prediction_output/`. Each test file contains exactly one test function whose name starts with `test_` and mirrors the file basename. No shared `conftest.py` is created or modified. Inline construction of the keyword arguments is required in each test that needs them; no helper module or fixture is added. Tests construct hand-written fakes inline.

## Package marker

- `__init__.py` — empty file (zero bytes).

## Test files (exactly 20)

Surface tests:

1. `test_public_surface.py` — assert `__all__` of `v2.backend.app.composition.trainer_prediction_output` equals `("build_trainer_prediction_output_evaluator", "TrainerPredictionOutputEvaluator", "TrainerPredictionOutputCompositionError")` exactly, including order; assert `build_trainer_prediction_output_evaluator` is callable; assert `TrainerPredictionOutputCompositionError` is a class and a subclass of `Exception`; assert `TrainerPredictionOutputEvaluator` is exported.

2. `test_errors_invariants.py` — instantiate `TrainerPredictionOutputCompositionError("some_code", field="some_field")`; assert `e.code == "some_code"`; assert `e.field == "some_field"`; assert `str(e) == "some_code (some_field)"`. Also instantiate with `field=None` and assert `str(e) == "some_code"`.

Import-clean tests (each test must reconstruct the forbidden literal at runtime via string concatenation so the test source file does not contain the bare token; each test launches a child interpreter via `subprocess.run([sys.executable, "-c", ...])`):

3. `test_init_module_does_not_load_redis.py` — purge any `red` + `is*` and `v2.backend.app.composition.trainer_prediction_output*` entries from `sys.modules` in the child interpreter, re-import the package, then assert no `sys.modules` key starts with the literal `"red" + "is"`.

4. `test_init_module_does_not_load_url_env.py` — purge any `v2.backend.app.adapters.redis_v2.url_env*` and `v2.backend.app.composition.trainer_prediction_output*` entries from `sys.modules`, re-import the package, then assert no key containing the literal `"url" + "_env"` is present.

5. `test_init_module_does_not_register_fastapi_lifespan.py` — purge any `fast` + `api*` and `v2.backend.app.composition.trainer_prediction_output*` entries from `sys.modules`, re-import the package, then assert no `sys.modules` key starts with `"fast" + "api"`.

6. `test_runtime_module_does_not_load_redis_when_imported.py` — purge any `red` + `is*` and `v2.backend.app.composition.trainer_prediction_output.runtime` entries from `sys.modules`, then `import v2.backend.app.composition.trainer_prediction_output.runtime`, then assert no `sys.modules` key starts with the literal `"red" + "is"`.

Forbidden-token scan tests:

7. `test_composition_milestone_forbidden_tokens.py` — read the bytes of `__init__.py`, `errors.py`, `runtime.py`. For each forbidden literal listed in spec 198 'Forbidden tokens in source files', reconstruct the literal at runtime via string concatenation and assert the literal does not appear in any of the three source files. Apply NO exemption.

8. `test_composition_does_not_import_url_env_directly.py` — open `runtime.py` and `__init__.py`, read source, assert neither file source contains the literal `"url" + "_env"` reconstructed at runtime.

Build-time validation tests:

9. `test_validates_now_ms_clock_callable.py` — call `build_trainer_prediction_output_evaluator(now_ms_clock=42)` and assert it raises `TrainerPredictionOutputCompositionError` with `code == "must_be_callable"` and `field == "now_ms_clock"`. Also pass `None` and re-assert the same exception, code, and field.

10. `test_returns_callable_evaluator.py` — pass a valid `now_ms_clock=lambda: 123` and assert the return value is callable. Assert the returned object is not the input clock (the binder MUST return a NEW callable, not pass the clock through).

Build-time non-invocation tests:

11. `test_assembler_not_invoked_at_build_time.py` — define a counter list `n=[0]` and a clock that increments it. Call `build_trainer_prediction_output_evaluator(now_ms_clock=...)`. Immediately after, assert `n == [0]` (the clock must NOT be called at build time). Also assert that no `TrainerPredictionRecord` was constructed at build time by checking that no record-related side effect occurred (no `feature_snapshot_id` round-trip).

Evaluator forwarding tests (each constructs a counter-equipped clock, builds the evaluator, calls it once, and asserts both behavior and forwarding):

12. `test_evaluator_invokes_assembler_exactly_once_per_call.py` — define a clock with a single-shot counter. Build the evaluator. Call the evaluator once with valid kwargs. Assert the clock counter incremented to exactly 1, demonstrating the assembler ran exactly once and called the clock exactly once.

13. `test_evaluator_returns_trainer_prediction_record.py` — call the evaluator with valid kwargs and assert `isinstance(result, TrainerPredictionRecord)` is true (import `TrainerPredictionRecord` from `v2.backend.app.domain.trainer_prediction_output`).

14. `test_evaluator_returns_assembler_result_unchanged.py` — call the evaluator with valid kwargs. Assert the returned record's 15 fields (the 14 lineage fields plus `prediction_ts_ms`) equal the kwargs supplied (with `prediction_ts_ms` equal to the clock return value). The evaluator must not mutate or transform the assembler result.

15. `test_evaluator_records_clock_into_prediction_ts_ms.py` — pass `now_ms_clock=lambda: 1700000000000`, call the evaluator with valid kwargs, assert `result.prediction_ts_ms == 1700000000000`.

16. `test_evaluator_keyword_only_params.py` — call the evaluator with one positional argument and assert `TypeError` is raised, demonstrating the inner function declares all parameters keyword-only.

Error propagation tests:

17. `test_evaluator_propagates_service_error_for_non_int_clock.py` — pass `now_ms_clock=lambda: 1.5`, build the evaluator, call it with valid kwargs, assert `TrainerPredictionOutputServiceError` is raised with `code == "must_be_int"` and `field == "now_ms_clock"`. The composition root MUST NOT catch or wrap the service error; the assertion verifies the service error class propagates unchanged.

18. `test_evaluator_propagates_service_error_for_negative_clock.py` — pass `now_ms_clock=lambda: -1`, build the evaluator, call it with valid kwargs, assert `TrainerPredictionOutputServiceError` is raised with `code == "must_be_nonnegative"` and `field == "now_ms_clock"`.

19. `test_evaluator_propagates_domain_error_disjoint.py` — build with a valid clock; call the evaluator with `top_positive_feature_codes=("a", "b")` and `top_negative_feature_codes=("b", "c")`; assert `TrainerPredictionDomainError` is raised with `reason == "must_be_disjoint_from_top_positive"` and `field == "top_negative_feature_codes"` (import `TrainerPredictionDomainError` from `v2.backend.app.domain.trainer_prediction_output`).

20. `test_evaluator_does_not_mutate_supplied_inputs.py` — build with a valid clock. Construct two tuples for `top_positive_feature_codes` and `top_negative_feature_codes` and a string for `prediction_id`. Call the evaluator with valid kwargs. After the call, assert the two original tuples and the original `prediction_id` string are byte-identical to their pre-call values, demonstrating the evaluator did not mutate caller-supplied inputs.

## Inline fakes

Test files MUST construct hand-written fakes inline (a tiny callable returning a fixed int or sequence of ints). No `unittest.mock`. No third-party fakes.

## Test runner expectations

`.venv/bin/python -m pytest v2/backend/tests/unit/composition/trainer_prediction_output/ -q` must report `20 passed` with zero failures and zero errors. The 2E3.B service suite (`v2/backend/tests/unit/services/trainer_prediction_output/`), the 2E3.A domain suite (`v2/backend/tests/unit/domain/trainer_prediction_output/`), the 2E2 worker health suites, and the 2E1 trainer parity / liveness suites must all continue to pass with zero regressions when run individually.

PHASE2E3C_TRAINER_PREDICTION_OUTPUT_COMPOSITION_ROOT_TEST_PLAN_READY
