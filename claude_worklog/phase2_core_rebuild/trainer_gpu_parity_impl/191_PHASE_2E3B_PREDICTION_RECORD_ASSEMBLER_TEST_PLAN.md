# Phase 2E3.B — Trainer Prediction Record Assembler Service Test Plan

All tests live under
`v2/backend/tests/unit/services/trainer_prediction_output/`. Each
test file contains exactly one test function whose name starts with
`test_` and mirrors the file basename. No shared `conftest.py` is
created or modified. Inline construction of the keyword arguments
to `assemble_prediction_record(...)` is required in each test that
needs them; no helper module or fixture is added.

## Package marker

- `__init__.py` — empty file (zero bytes).

## Test files (exactly 22)

Surface tests:

1. `test_public_surface.py` — assert `__all__` of
   `v2.backend.app.services.trainer_prediction_output` equals
   `("assemble_prediction_record", "TrainerPredictionOutputServiceError")`
   exactly, including order; assert
   `assemble_prediction_record` is a callable; assert
   `TrainerPredictionOutputServiceError` is a class and a subclass
   of `ValueError`.

2. `test_errors_invariants.py` — instantiate
   `TrainerPredictionOutputServiceError("some_code", field="some_field")`,
   assert `e.code == "some_code"`, assert `e.field == "some_field"`,
   assert `str(e) == "some_code (some_field)"`, assert `repr(e)`
   equals
   `"TrainerPredictionOutputServiceError(code='some_code', field='some_field')"`.

Import-clean tests (each test must reconstruct the forbidden
literal at runtime via string concatenation so the test source
file does not contain the bare token; each test launches a child
interpreter via `subprocess.run([sys.executable, "-c", ...])`):

3. `test_init_module_does_not_load_redis.py` — purge any
   `red` + `is*` and
   `v2.backend.app.services.trainer_prediction_output*` entries
   from `sys.modules` in the child interpreter, re-import the
   package, then assert no `sys.modules` key starts with the
   literal `"red" + "is"`.

4. `test_init_module_does_not_load_url_env.py` — purge any
   `v2.backend.app.adapters.redis_v2.url_env*` and
   `v2.backend.app.services.trainer_prediction_output*` entries
   from `sys.modules`, re-import the package, then assert no key
   containing the literal `"url" + "_env"` is present.

5. `test_init_module_does_not_register_fastapi_lifespan.py` —
   purge any `fastapi*` and
   `v2.backend.app.services.trainer_prediction_output*` entries
   from `sys.modules`, re-import the package, then assert no
   `sys.modules` key starts with `"fast" + "api"`.

Argument and clock validation tests (each test instantiates
exactly the inputs it needs and calls
`assemble_prediction_record` exactly once):

6. `test_assemble_rejects_non_callable_clock.py` — pass
   `now_ms_clock=42`, assert raised
   `TrainerPredictionOutputServiceError` carries
   `code == "must_be_callable"` and `field == "now_ms_clock"`.

7. `test_assemble_rejects_clock_returning_non_int.py` — three
   sub-asserts inside the single test function: clocks returning
   `"42"`, `42.0`, and a stub object that is not an `int`
   subclass each raise
   `TrainerPredictionOutputServiceError("must_be_int",
   field="now_ms_clock")`. Booleans are also asserted: a clock
   returning `True` raises `must_be_int` because
   `type(True) is not int`.

8. `test_assemble_rejects_clock_returning_negative.py` — pass a
   clock returning `-1`, assert raised
   `TrainerPredictionOutputServiceError` carries
   `code == "must_be_nonnegative"` and
   `field == "now_ms_clock"`.

9. `test_assemble_calls_clock_exactly_once.py` — wrap a clock in
   a closure-counter and call `assemble_prediction_record`,
   assert the counter is exactly `1` after the call.

10. `test_assemble_records_clock_into_prediction_ts_ms.py` —
    use a clock that returns `1_700_000_000_123`; assert the
    returned record's `prediction_ts_ms == 1_700_000_000_123`.

11. `test_assemble_zero_clock_passes.py` — use a clock that
    returns `0`; assert no exception is raised and the returned
    record's `prediction_ts_ms == 0`.

Return-shape tests:

12. `test_assemble_returns_trainer_prediction_record.py` —
    assert the returned object is an instance of
    `v2.backend.app.domain.trainer_prediction_output.TrainerPredictionRecord`.

13. `test_assemble_returns_frozen_record.py` — capture the
    returned record, assert that mutating any field via
    `setattr` raises `dataclasses.FrozenInstanceError`.

14. `test_assemble_keyword_only_params.py` — call
    `assemble_prediction_record(<positional args>)`; assert the
    call raises `TypeError` because every parameter is
    keyword-only.

Happy-path tests (each builds a fully valid argument set inline
and asserts no exception, plus field round-trip equality on the
returned record):

15. `test_assemble_happy_path_long.py` — full valid LONG
    record with `direction == "long"`,
    `confidence_raw == 0.7`, `confidence_calibrated == 0.65`,
    `freshness_flag == "fresh"`,
    `source_freshness_age_ms == 250`, `worker_health_status ==
    "HEALTHY"`, non-empty disjoint top-K tuples; assert every
    record field equals the supplied value (with
    `prediction_ts_ms` equal to the clock return value).

16. `test_assemble_happy_path_short.py` — full valid SHORT
    record with `direction == "short"`,
    `confidence_raw == 0.4`, `confidence_calibrated == 0.42`,
    `freshness_flag == "stale"`,
    `source_freshness_age_ms == 9_000`, `worker_health_status ==
    "DEGRADED"`, disjoint top-K tuples; assert field round-trip.

17. `test_assemble_happy_path_flat_missing_freshness.py` —
    full valid FLAT record with `direction == "flat"`,
    `confidence_raw == 0.0`, `confidence_calibrated == 0.0`,
    `freshness_flag == "missing"`,
    `source_freshness_age_ms is None`, `worker_health_status ==
    "UNKNOWN"`, both top-K tuples empty; assert field round-trip.

Domain-error propagation tests (each uses a valid clock and varies
exactly one field to a value that the 2E3.A
`TrainerPredictionRecord.__post_init__` rejects; each test asserts
that the exception bubbling out of
`assemble_prediction_record` is an instance of
`TrainerPredictionDomainError` (NOT
`TrainerPredictionOutputServiceError`) and carries the expected
`reason` and `field`):

18. `test_assemble_propagates_domain_error_prediction_id.py` —
    pass `prediction_id=""`; assert raised
    `TrainerPredictionDomainError` has
    `reason == "must_be_non_empty"` and
    `field == "prediction_id"`.

19. `test_assemble_propagates_domain_error_symbol.py` —
    pass `symbol="btcusdt"`; assert raised
    `TrainerPredictionDomainError` has
    `reason == "must_be_uppercase"` and `field == "symbol"`.

20. `test_assemble_propagates_domain_error_direction.py` —
    pass `direction="diagonal"`; assert raised
    `TrainerPredictionDomainError` has
    `reason == "invalid_direction"` and
    `field == "direction"`.

21. `test_assemble_propagates_domain_error_disjoint.py` —
    pass `top_positive_feature_codes=("alpha", "beta")` and
    `top_negative_feature_codes=("beta", "gamma")`; assert
    raised `TrainerPredictionDomainError` has
    `reason == "must_be_disjoint_from_top_positive"` and
    `field == "top_negative_feature_codes"`.

Forbidden-token scan test:

22. `test_service_forbidden_tokens.py` — for each forbidden
    literal listed in spec §"Forbidden tokens in source files",
    scan the THREE authored source files (`__init__.py`,
    `errors.py`, `service.py`) and assert zero matches. Each
    forbidden literal is constructed at runtime via string
    concatenation so the test file itself does not contain the
    bare token. NO exemption applies.

## Validation commands run by `113`

The implementation task runs these commands and captures stdout
plus exit code into
`194_2E3B_PREDICTION_RECORD_ASSEMBLER_IMPLEMENTATION_REPORT.md`:

1. `.venv/bin/python -m pytest v2/backend/tests/unit/services/trainer_prediction_output/ -q`
   (REQUIRED RESULT: 22 passed, zero failures, zero errors).
2. `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_prediction_output/ -q`
   (regression: 31 tests still pass).
3. `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_worker_health/ -q`
   (regression).
4. `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_liveness/ -q`
   (regression).
5. `.venv/bin/python -m pytest v2/backend/tests/unit/services/trainer_worker_health/ -q`
   (regression).
6. `.venv/bin/python -m pytest v2/backend/tests/unit/composition/trainer_worker_health/ -q`
   (regression).
7. `.venv/bin/python -m pytest v2/backend/tests/unit/services/trainer_parity/ -q`
   (regression).
8. `.venv/bin/python -m pytest v2/backend/tests/unit/composition/trainer_parity/ -q`
   (regression).
9. `python -m py_compile v2/backend/app/services/trainer_prediction_output/__init__.py v2/backend/app/services/trainer_prediction_output/errors.py v2/backend/app/services/trainer_prediction_output/service.py`
   (REQUIRED RESULT: exit code zero).
10. `git status -s` over the cross-isolation paths declared in
    `192` (REQUIRED RESULT: zero lines).
11. `rg --fixed-strings --case-sensitive <token> v2/backend/app/services/trainer_prediction_output/`
    for each forbidden token from spec §"Forbidden tokens in
    source files" (REQUIRED RESULT: zero matches per token).

PHASE2E3B_TRAINER_PREDICTION_RECORD_ASSEMBLER_TEST_PLAN_READY
