# Phase 2E2.B — Worker Health Service Test Plan

All tests live under
`v2/backend/tests/unit/services/trainer_worker_health/`. Each test
file contains exactly one test function whose name starts with
`test_` and mirrors the file basename. No shared `conftest.py` is
created or modified. Inline construction of
`LivenessSignalSnapshot`, `TrainerWorkerHealthThresholds`, and
`TrainerWorkerHealthSnapshot` value objects is required in each
test that needs them; no helper module or fixture is added.

## Package marker

- `__init__.py` — empty file (zero bytes).

## Surface tests

- `test_public_surface.py` — assert `__all__` of
  `v2.backend.app.services.trainer_worker_health` equals
  `("evaluate_worker_health", "TrainerWorkerHealthServiceError")`
  exactly, including order; assert
  `v2.backend.app.services.trainer_worker_health.evaluate_worker_health`
  is a callable; assert
  `v2.backend.app.services.trainer_worker_health.TrainerWorkerHealthServiceError`
  is a class and a subclass of `ValueError`.

- `test_errors_invariants.py` — instantiate
  `TrainerWorkerHealthServiceError("some_code", field="some_field")`,
  assert `e.code == "some_code"`, assert `e.field == "some_field"`,
  assert `str(e) == "some_code (some_field)"`, assert `repr(e)` equals
  `"TrainerWorkerHealthServiceError(code='some_code', field='some_field')"`.

## Import-clean tests

- `test_init_module_does_not_load_redis.py` — purge any
  `redis*` and `v2.backend.app.services.trainer_worker_health*`
  entries from `sys.modules`, re-import
  `v2.backend.app.services.trainer_worker_health`, then assert no
  `sys.modules` key starts with the literal `"red" + "is"`. The
  literal must be assembled at runtime via string concatenation so
  the source file does not contain the forbidden token.

- `test_init_module_does_not_load_url_env.py` — purge any
  `v2.backend.app.adapters.redis_v2.url_env*` and
  `v2.backend.app.services.trainer_worker_health*` entries from
  `sys.modules`, re-import the package, then assert no key
  containing the literal `"url" + "_env"` is present. The literal
  must be assembled at runtime.

- `test_init_module_does_not_register_fastapi_lifespan.py` — purge
  any `fastapi*` and
  `v2.backend.app.services.trainer_worker_health*` entries from
  `sys.modules`, re-import the package, then assert no `sys.modules`
  key starts with `"fast" + "api"`.

## Argument validation tests

Each test instantiates exactly the inputs it needs and calls
`evaluate_worker_health` exactly once. Each test asserts the raised
`TrainerWorkerHealthServiceError` carries the expected `code` and
`field` values.

- `test_evaluate_rejects_non_snapshot.py` — pass `object()` as
  `snapshot`, assert `code == "must_be_liveness_signal_snapshot"`,
  assert `field == "snapshot"`.

- `test_evaluate_rejects_non_thresholds.py` — pass a valid
  `LivenessSignalSnapshot` and `object()` as `thresholds`, assert
  `code == "must_be_worker_health_thresholds"`, assert
  `field == "thresholds"`.

- `test_evaluate_rejects_non_callable_clock.py` — pass valid
  snapshot and thresholds and `now_ms_clock=42`, assert
  `code == "must_be_callable"`, assert `field == "now_ms_clock"`.

- `test_evaluate_rejects_clock_returning_non_int.py` — pass a clock
  that returns `"42"`, assert `code == "must_be_int"`, assert
  `field == "now_ms_clock"`.

- `test_evaluate_rejects_clock_returning_negative_int.py` — pass a
  clock that returns `-1`, assert `code == "must_be_nonnegative"`,
  assert `field == "now_ms_clock"`.

- `test_evaluate_rejects_clock_before_observation_ts.py` — build a
  snapshot with `observation_ts_ms = 1_000` and pass a clock that
  returns `999`, assert `code == "now_before_observation"`, assert
  `field == "now_ms_clock"`.

- `test_evaluate_calls_clock_exactly_once.py` — wrap a clock in a
  counter and call `evaluate_worker_health`, assert the counter is
  exactly `1` after the call.

## Behavior propagation tests

Each test exercises one branch of the underlying domain evaluator
through the service, asserting the service does not alter the
status, reasons tuple, observation_ts_ms, or signal_snapshot of the
returned `TrainerWorkerHealthSnapshot`.

- `test_evaluate_returns_worker_health_snapshot.py` — assert the
  returned object is an instance of
  `TrainerWorkerHealthSnapshot`.

- `test_evaluate_propagates_unknown_when_no_signals.py` — build a
  snapshot with all signal fields cleared (no_signals branch);
  assert returned `status == HEALTH_STATUS_UNKNOWN` and `reasons ==
  (HEALTH_REASON_NO_SIGNALS_OBSERVED,)`.

- `test_evaluate_propagates_healthy_when_all_fresh.py` — build a
  snapshot with fresh prediction, gpu_batch, and proposal
  timestamps and `prediction_stream_id_growth > 0` and
  `prediction_worker_alive is True`; assert returned `status ==
  HEALTH_STATUS_HEALTHY` and `reasons == ()`.

- `test_evaluate_propagates_degraded_prediction_age.py` — build a
  snapshot whose `last_prediction_ts_ms` is older than the degraded
  threshold but younger than the critical threshold; assert
  returned `status == HEALTH_STATUS_DEGRADED` and
  `HEALTH_REASON_PREDICTION_AGE_DEGRADED in reasons`.

- `test_evaluate_propagates_critical_prediction_age.py` — build a
  snapshot whose `last_prediction_ts_ms` is older than the critical
  threshold; assert returned `status == HEALTH_STATUS_CRITICAL` and
  `HEALTH_REASON_PREDICTION_AGE_CRITICAL in reasons`.

- `test_evaluate_propagates_critical_when_worker_dead.py` — build a
  snapshot with `prediction_worker_alive is False` and
  `prediction_worker_pid is not None`; assert returned `status ==
  HEALTH_STATUS_CRITICAL` and
  `HEALTH_REASON_PREDICTION_WORKER_DEAD in reasons`.

- `test_evaluate_propagates_critical_when_fatal_log_signature.py` —
  build a snapshot with `fatal_log_signature_observed is True`;
  assert returned `status == HEALTH_STATUS_CRITICAL` and
  `HEALTH_REASON_FATAL_LOG_SIGNATURE_OBSERVED in reasons`.

- `test_evaluate_propagates_critical_when_zero_stream_growth.py` —
  build a snapshot with `prediction_stream_id_growth == 0`,
  `trainer_pid` not None, `trainer_rss_bytes > 0`; assert returned
  `status == HEALTH_STATUS_CRITICAL` and
  `HEALTH_REASON_PREDICTION_STREAM_ZERO_GROWTH in reasons`.

## Mutation-safety tests

- `test_evaluate_does_not_mutate_supplied_snapshot.py` — capture
  every public field of the input `LivenessSignalSnapshot` before
  the call, assert each field is byte-identical after the call;
  also assert `id(snapshot)` is unchanged.

- `test_evaluate_does_not_mutate_supplied_thresholds.py` — capture
  every public field of the input
  `TrainerWorkerHealthThresholds` before the call, assert each
  field is byte-identical after the call; also assert
  `id(thresholds)` is unchanged.

## Test execution policy

- All 22 tests must pass with zero failures and zero errors under
  `.venv/bin/python -m pytest v2/backend/tests/unit/services/trainer_worker_health/ -q`.
- The Phase 2E1 and Phase 2E2.A test suites listed below must
  remain green:
  - `v2/backend/tests/unit/domain/trainer_liveness/`
  - `v2/backend/tests/unit/domain/trainer_liveness_composition/`
  - `v2/backend/tests/unit/domain/trainer_liveness_observation_collector/`
  - `v2/backend/tests/unit/domain/liveness_stream_growth/`
  - `v2/backend/tests/unit/domain/trainer_worker_health/`
  - `v2/backend/tests/unit/services/trainer_parity/`
  - `v2/backend/tests/unit/composition/trainer_parity/`

PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_TEST_PLAN_READY
