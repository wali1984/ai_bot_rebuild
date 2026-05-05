# Phase 2F.C — Orchestrator Decision Composition Root Test Plan

All tests live under `v2/backend/tests/unit/composition/orchestrator_decision/`. Each test file contains exactly one test function whose name starts with `test_` and mirrors the file basename. No shared `conftest.py` is created or modified. Inline construction of the keyword arguments and `TrainerPredictionRecord` instances is required in each test that needs them; no helper module or fixture is added. Tests construct hand-written fakes inline.

## Package marker

- `__init__.py` — empty file (zero bytes).

## Test files (exactly 28)

Surface tests:

1. `test_public_surface.py` — assert `__all__` of `v2.backend.app.composition.orchestrator_decision` equals `("build_orchestrator_decision_evaluator", "OrchestratorDecisionEvaluator", "OrchestratorDecisionCompositionError")` exactly, including order; assert `build_orchestrator_decision_evaluator` is callable; assert `OrchestratorDecisionCompositionError` is a class and a subclass of `Exception` and is NOT a subclass of `ValueError`; assert `OrchestratorDecisionEvaluator` is exported.

2. `test_errors_invariants.py` — instantiate `OrchestratorDecisionCompositionError("some_code", field="some_field")`; assert `e.code == "some_code"`; assert `e.field == "some_field"`; assert `str(e) == "some_code (some_field)"`; assert calling without `field=` raises `TypeError` because `field` is required (no default).

Import-clean tests (each test must reconstruct the forbidden literal at runtime via string concatenation so the test source file does not contain the bare token; each test launches a child interpreter via `subprocess.run([sys.executable, "-c", ...])`):

3. `test_init_module_does_not_load_redis.py` — purge any literal `"red" + "is"` prefixed and `v2.backend.app.composition.orchestrator_decision*` entries from `sys.modules` in the child interpreter, re-import the package, then assert no `sys.modules` key starts with the literal `"red" + "is"`.

4. `test_init_module_does_not_load_url_env.py` — purge any `v2.backend.app.adapters.redis_v2.url_env*` and `v2.backend.app.composition.orchestrator_decision*` entries from `sys.modules`, re-import the package, then assert no key containing the literal `"url" + "_env"` is present.

5. `test_init_module_does_not_register_fastapi_lifespan.py` — purge any `"fast" + "api"` prefixed and `v2.backend.app.composition.orchestrator_decision*` entries from `sys.modules`, re-import the package, then assert no `sys.modules` key starts with `"fast" + "api"`.

6. `test_runtime_module_does_not_load_redis_when_imported.py` — purge any `"red" + "is"` prefixed and `v2.backend.app.composition.orchestrator_decision.runtime` entries from `sys.modules`, then `import v2.backend.app.composition.orchestrator_decision.runtime`, then assert no `sys.modules` key starts with the literal `"red" + "is"`.

Forbidden-token scan tests:

7. `test_composition_milestone_forbidden_tokens.py` — read the bytes of `__init__.py`, `errors.py`, `runtime.py`. For each forbidden literal listed in spec 18 'Forbidden tokens in source files', reconstruct the literal at runtime via string concatenation and assert the literal does not appear in any of the three source files. Apply NO exemption.

8. `test_composition_does_not_import_url_env_directly.py` — open `runtime.py` and `__init__.py`, read source, assert neither file source contains the literal `"url" + "_env"` reconstructed at runtime.

Build-time validation tests for `low_confidence_threshold`:

9. `test_validates_low_confidence_threshold_not_float.py` — call `build_orchestrator_decision_evaluator(low_confidence_threshold=0, now_ms_clock=lambda: 0)` and assert it raises `OrchestratorDecisionCompositionError` with `code == "must_be_float"` and `field == "low_confidence_threshold"`. Also pass `"0.5"` (string) and re-assert the same exception, code, and field.

10. `test_validates_low_confidence_threshold_not_bool.py` — call `build_orchestrator_decision_evaluator(low_confidence_threshold=True, now_ms_clock=lambda: 0)` and assert it raises `OrchestratorDecisionCompositionError` with `code == "must_be_float"` and `field == "low_confidence_threshold"`. Also pass `False` and re-assert.

11. `test_validates_low_confidence_threshold_not_finite.py` — call `build_orchestrator_decision_evaluator(low_confidence_threshold=float("inf"), now_ms_clock=lambda: 0)` and assert it raises `OrchestratorDecisionCompositionError` with `code == "must_be_finite"` and `field == "low_confidence_threshold"`. Also pass `float("nan")` and `float("-inf")` and re-assert.

12. `test_validates_low_confidence_threshold_below_zero.py` — call `build_orchestrator_decision_evaluator(low_confidence_threshold=-0.0001, now_ms_clock=lambda: 0)` and assert it raises `OrchestratorDecisionCompositionError` with `code == "must_be_in_unit_interval"` and `field == "low_confidence_threshold"`.

13. `test_validates_low_confidence_threshold_above_one.py` — call `build_orchestrator_decision_evaluator(low_confidence_threshold=1.0001, now_ms_clock=lambda: 0)` and assert it raises `OrchestratorDecisionCompositionError` with `code == "must_be_in_unit_interval"` and `field == "low_confidence_threshold"`.

14. `test_threshold_zero_accepted_at_build.py` — call `build_orchestrator_decision_evaluator(low_confidence_threshold=0.0, now_ms_clock=lambda: 0)` and assert the call returns a callable without raising.

15. `test_threshold_one_accepted_at_build.py` — call `build_orchestrator_decision_evaluator(low_confidence_threshold=1.0, now_ms_clock=lambda: 0)` and assert the call returns a callable without raising.

Build-time validation tests for `now_ms_clock`:

16. `test_validates_now_ms_clock_callable.py` — call `build_orchestrator_decision_evaluator(low_confidence_threshold=0.5, now_ms_clock=42)` and assert it raises `OrchestratorDecisionCompositionError` with `code == "must_be_callable"` and `field == "now_ms_clock"`. Also pass `None` and re-assert the same exception, code, and field.

17. `test_returns_callable_evaluator.py` — pass `low_confidence_threshold=0.5` and `now_ms_clock=lambda: 123` and assert the return value is callable. Assert the returned object is not the input clock (the binder MUST return a NEW callable, not pass the clock through).

Build-time non-invocation tests:

18. `test_assembler_not_invoked_at_build_time.py` — define a counter list `n=[0]` and a clock that increments it. Call `build_orchestrator_decision_evaluator(low_confidence_threshold=0.5, now_ms_clock=...)`. Immediately after, assert `n == [0]` (the clock must NOT be called at build time). Also assert that no `OrchestratorDecisionRecord` was constructed at build time by checking that no record-related side effect occurred (the test does not need to construct a TrainerPredictionRecord at build-time observation, only confirm the clock counter remains zero).

Evaluator forwarding tests (each constructs a counter-equipped clock, builds the evaluator, calls it once with an inline-constructed valid `TrainerPredictionRecord`, and asserts both behavior and forwarding):

19. `test_evaluator_invokes_assembler_exactly_once_per_call.py` — define a clock with a single-shot counter. Build the evaluator with `low_confidence_threshold=0.5`. Call the evaluator once with a valid `prediction=TrainerPredictionRecord(...)` whose `direction` is `flat`, `confidence_calibrated` is above the threshold, `freshness_flag` is `fresh`, and `worker_health_status` is `OK`. Assert the clock counter incremented to exactly 1, demonstrating the assembler ran exactly once and called the clock exactly once.

20. `test_evaluator_returns_orchestrator_decision_record.py` — call the evaluator with valid kwargs and assert `isinstance(result, OrchestratorDecisionRecord)` is true (import `OrchestratorDecisionRecord` from `v2.backend.app.domain.orchestrator_decision`).

21. `test_evaluator_records_clock_into_decision_ts_ms.py` — pass `low_confidence_threshold=0.5` and `now_ms_clock=lambda: 1700000000000`, call the evaluator with a valid `prediction`, assert `result.decision_ts_ms == 1700000000000`.

22. `test_evaluator_uses_captured_threshold.py` — build the evaluator with `low_confidence_threshold=0.7`. Call the evaluator with a `prediction` whose `confidence_calibrated == 0.65`, `direction == "long"`, `freshness_flag == "fresh"`, and `worker_health_status == "OK"`. Assert `result.decision_action == "abstain"` and `result.decision_reason_code == "abstain_low_confidence"`, demonstrating the binder captured the threshold at build time. Also build a second evaluator with `low_confidence_threshold=0.5`, call with the same `prediction`, and assert `result.decision_action == "open_long"` and `result.decision_reason_code == "proceed_long"`, demonstrating threshold capture is per-binder.

23. `test_evaluator_keyword_only_params.py` — call the evaluator with one positional argument and assert `TypeError` is raised, demonstrating the inner function declares the `prediction` parameter keyword-only.

Error propagation tests:

24. `test_evaluator_propagates_service_error_for_non_int_clock.py` — pass `low_confidence_threshold=0.5` and `now_ms_clock=lambda: 1.5`, build the evaluator, call it with a valid `prediction`, assert `OrchestratorDecisionServiceError` is raised with `code == "must_be_int"` and `field == "now_ms_clock"`. The composition root MUST NOT catch or wrap the service error; the assertion verifies the service error class propagates unchanged. Import `OrchestratorDecisionServiceError` from `v2.backend.app.services.orchestrator_decision`.

25. `test_evaluator_propagates_service_error_for_negative_clock.py` — pass `low_confidence_threshold=0.5` and `now_ms_clock=lambda: -1`, build the evaluator, call it with a valid `prediction`, assert `OrchestratorDecisionServiceError` is raised with `code == "must_be_nonnegative"` and `field == "now_ms_clock"`.

26. `test_evaluator_propagates_service_error_for_non_record_prediction.py` — build the evaluator with valid build args, call the evaluator with `prediction="not a record"`, assert `OrchestratorDecisionServiceError` is raised with `code == "must_be_trainer_prediction_record"` and `field == "prediction"`.

27. `test_evaluator_propagates_service_error_for_long_prediction_id.py` — construct a `TrainerPredictionRecord` whose `prediction_id` is 125 characters long (one past the 124 limit). Build the evaluator with valid build args, call the evaluator with the long-id prediction, assert `OrchestratorDecisionServiceError` is raised with `code == "prediction_id_too_long_for_decision_id_derivation"` and `field == "prediction.prediction_id"`.

28. `test_evaluator_does_not_mutate_supplied_inputs.py` — build with valid build args. Construct a valid `TrainerPredictionRecord` and snapshot all 14 input lineage fields before the call. Call the evaluator. After the call, assert each of the 14 fields on the original record is byte-identical to its pre-call value (records are frozen, but the test asserts equality via attribute access on the same object). Also assert the original `prediction` reference is unchanged.

## Inline fakes

Test files MUST construct hand-written fakes inline (a tiny callable returning a fixed int or sequence of ints; a hand-built `TrainerPredictionRecord` per the 2E3.A constructor surface). No `unittest.mock`. No third-party fakes.

## Test runner expectations

`.venv/bin/python -m pytest v2/backend/tests/unit/composition/orchestrator_decision/ -q` must report `28 passed` with zero failures and zero errors. The 2F.B service suite (`v2/backend/tests/unit/services/orchestrator_decision/`), the 2F.A domain suite (`v2/backend/tests/unit/domain/orchestrator_decision/`), the 2E3.C composition suite (`v2/backend/tests/unit/composition/trainer_prediction_output/`), the 2E3.B service suite (`v2/backend/tests/unit/services/trainer_prediction_output/`), the 2E3.A domain suite (`v2/backend/tests/unit/domain/trainer_prediction_output/`), and all 2E2 and 2E1 suites must continue to pass with zero regressions when run individually.

PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_TEST_PLAN_READY
