# Phase 2E2.A — Trainer Worker Health Domain Test Plan

The test plan enumerates the canonical 24 test files plus the
package marker under
`v2/backend/tests/unit/domain/trainer_worker_health/`. Each test
file contains exactly one test function whose name starts with
`test_` and mirrors the file basename. Tests use inline hand-written
`LivenessSignalSnapshot` and `TrainerWorkerHealthThresholds` objects
constructed directly via their dataclass constructors. No shared
`conftest.py` is created. No fixture is shared.

## Required test files (24 plus package marker)

0. `__init__.py` — empty package marker (single newline).

1. `test_public_surface.py` — imports `__all__` from
   `v2.backend.app.domain.trainer_worker_health`; asserts it equals
   the 18-name tuple in `141 §"Public surface"` in that exact order;
   asserts each name resolves to the same object as the corresponding
   direct module attribute.

2. `test_errors_invariants.py` — constructs
   `TrainerWorkerHealthDomainError("foo")` and
   `TrainerWorkerHealthDomainError("foo", field="bar")`; asserts
   `.reason == "foo"`, `.field is None` and `.field == "bar"`,
   `str(err) == "foo"` and `str(err) == "bar: foo"`; asserts the
   class is a subclass of `ValueError`.

3. `test_health_status_constants.py` — asserts each status constant
   equals the exact string value listed in `141 §"Status constants"`;
   asserts each reason constant equals the exact string value listed
   in `141 §"Status constants"`; asserts the four status values are
   distinct; asserts the ten reason values are distinct; asserts the
   ten reason values are disjoint from the four status values.

4. `test_health_thresholds_invariants_must_be_int.py` — for each of
   the six fields, constructs a thresholds dataclass with that field
   set to `1.0` (float); asserts `TrainerWorkerHealthDomainError`
   with `reason == "must_be_int"` and `field == <field_name>`.
   Repeats with `True` (bool) for one field to confirm `bool` is
   rejected as not-`int`.

5. `test_health_thresholds_invariants_must_be_at_least_one.py` —
   for each of the six fields, constructs a thresholds dataclass
   with that field set to `0`, then `-1`; asserts
   `TrainerWorkerHealthDomainError` with
   `reason == "must_be_at_least_one"` and
   `field == <field_name>`.

6. `test_health_thresholds_invariants_critical_must_be_greater_than_degraded.py`
   — for each of the three pairs (prediction, gpu_batch, proposal),
   constructs a thresholds dataclass with `degraded_ms == critical_ms`
   then with `degraded_ms > critical_ms`; asserts
   `TrainerWorkerHealthDomainError` with
   `reason == "critical_must_be_greater_than_degraded"` and
   `field == <critical_field_name>`.

7. `test_health_snapshot_invariants_status_in_allowed.py` —
   constructs a snapshot with `status = "INVALID"`; asserts
   `TrainerWorkerHealthDomainError` with
   `reason == "invalid_status"` and `field == "status"`.

8. `test_health_snapshot_invariants_observation_ts_must_match.py` —
   constructs a snapshot with `observation_ts_ms = 999` against a
   `signal_snapshot.observation_ts_ms = 1000`; asserts
   `TrainerWorkerHealthDomainError` with
   `reason == "must_match_snapshot"` and
   `field == "observation_ts_ms"`.

9. `test_health_snapshot_invariants_reasons_unique.py` — constructs
   a CRITICAL snapshot whose `reasons` tuple contains the same
   reason twice; asserts `TrainerWorkerHealthDomainError` with
   `reason == "duplicate_reasons"` and `field == "reasons"`.

10. `test_health_snapshot_invariants_healthy_requires_empty.py` —
    constructs a snapshot with `status = HEALTH_STATUS_HEALTHY` and
    a non-empty reasons tuple; asserts
    `TrainerWorkerHealthDomainError` with
    `reason == "healthy_requires_empty_reasons"` and
    `field == "reasons"`.

11. `test_health_snapshot_invariants_unknown_requires_no_signals_reason.py`
    — constructs a snapshot with
    `status = HEALTH_STATUS_UNKNOWN` and a reasons tuple equal to
    `(HEALTH_REASON_PREDICTION_WORKER_DEAD,)`; asserts
    `TrainerWorkerHealthDomainError` with
    `reason == "unknown_requires_no_signals_reason"` and
    `field == "reasons"`.

12. `test_evaluator_healthy_when_all_fresh.py` — builds a
    `LivenessSignalSnapshot` with a present trainer pid (123),
    `trainer_rss_bytes=4096`, `prediction_worker_pid=456`,
    `prediction_worker_alive=True`, all three age timestamps within
    the degraded thresholds, `prediction_stream_id_growth=5`,
    `proposal_stream_id_growth=5`, `fatal_log_signature_observed=False`.
    Calls the evaluator with `now_ms = observation_ts_ms`. Asserts
    `status == HEALTH_STATUS_HEALTHY` and `reasons == ()`.

13. `test_evaluator_unknown_when_no_signals.py` — builds a snapshot
    with all None timestamps, `prediction_worker_alive=False` and
    `prediction_worker_pid=None`, growth values both 0, fatal log
    False, trainer pid/rss/heartbeat None. Calls the evaluator with
    `now_ms == observation_ts_ms == 0`. Asserts
    `status == HEALTH_STATUS_UNKNOWN` and
    `reasons == (HEALTH_REASON_NO_SIGNALS_OBSERVED,)`.

14. `test_evaluator_degraded_prediction_age.py` — builds a fresh
    snapshot but sets `last_prediction_ts_ms = now_ms - (degraded_ms + 1)`
    (i.e., age strictly greater than degraded threshold) and below
    the critical threshold. Asserts `status == HEALTH_STATUS_DEGRADED`
    and `reasons == (HEALTH_REASON_PREDICTION_AGE_DEGRADED,)`.

15. `test_evaluator_degraded_gpu_batch_age.py` — same pattern for the
    gpu_batch age signal in isolation.

16. `test_evaluator_degraded_proposal_age.py` — same pattern for the
    proposal age signal in isolation.

17. `test_evaluator_critical_prediction_age.py` — sets
    `last_prediction_ts_ms = now_ms - (critical_ms + 1)`. Asserts
    `status == HEALTH_STATUS_CRITICAL` and
    `reasons == (HEALTH_REASON_PREDICTION_AGE_CRITICAL,)`.

18. `test_evaluator_critical_gpu_batch_age.py` — same pattern for
    gpu_batch in isolation.

19. `test_evaluator_critical_proposal_age.py` — same pattern for
    proposal in isolation.

20. `test_evaluator_critical_when_worker_dead.py` — fresh snapshot
    but `prediction_worker_alive = False` and
    `prediction_worker_pid = 456`. Asserts
    `status == HEALTH_STATUS_CRITICAL` and
    `reasons == (HEALTH_REASON_PREDICTION_WORKER_DEAD,)`.

21. `test_evaluator_critical_when_fatal_log_signature.py` — fresh
    snapshot but `fatal_log_signature_observed = True`. Asserts
    `status == HEALTH_STATUS_CRITICAL` and
    `reasons == (HEALTH_REASON_FATAL_LOG_SIGNATURE_OBSERVED,)`.

22. `test_evaluator_critical_when_zero_stream_growth_with_alive_parent.py`
    — fresh snapshot but `prediction_stream_id_growth = 0` while
    `trainer_pid = 123` and `trainer_rss_bytes = 4096`. Asserts
    `status == HEALTH_STATUS_CRITICAL` and
    `reasons == (HEALTH_REASON_PREDICTION_STREAM_ZERO_GROWTH,)`.

23. `test_evaluator_status_precedence_critical_over_degraded.py` —
    sets BOTH the prediction age into the critical band AND the
    gpu_batch age into the degraded band. Asserts
    `status == HEALTH_STATUS_CRITICAL`. Asserts the reasons tuple
    equals
    `(HEALTH_REASON_PREDICTION_AGE_CRITICAL, HEALTH_REASON_GPU_BATCH_AGE_DEGRADED)`
    (critical first, then degraded). Asserts the prediction age
    contributes the critical reason and NOT the degraded reason
    (i.e., `HEALTH_REASON_PREDICTION_AGE_DEGRADED` is NOT in the
    reasons tuple).

24. `test_evaluator_threshold_boundary_strict.py` — single test that
    asserts the strict comparison at every boundary by exercising
    four sub-cases inline:
    - prediction age `== degraded_ms` exactly: HEALTHY.
    - prediction age `== degraded_ms + 1`: DEGRADED.
    - prediction age `== critical_ms` exactly: DEGRADED (not yet
      critical).
    - prediction age `== critical_ms + 1`: CRITICAL.

25. `test_evaluator_now_before_observation_rejected.py` — calls the
    evaluator with `now_ms = snapshot.observation_ts_ms - 1`;
    asserts `TrainerWorkerHealthDomainError` with
    `reason == "now_before_observation"` and `field == "now_ms"`.

26. `test_evaluator_does_not_mutate_inputs.py` — captures
    `id(snapshot)` and `id(thresholds)` before the call; asserts
    both ids and the underlying field values are unchanged after
    the call (snapshot is a frozen dataclass; this confirms no
    aliasing or replacement).

27. `test_worker_health_domain_does_not_import_redis.py` — opens
    each of the six authored source files and reads the source via
    `inspect.getsource` after importing the module; asserts the
    forbidden literals (constructed at runtime via string
    concatenation) `import redis`, `from redis`, `redis.asyncio`,
    `hiredis`, `aioredis`, `xrevrange`, `xadd`, `xread`, `xlen`,
    `pipeline`, `httpx`, `requests` do NOT appear in any of the six
    source files. Also asserts after `popping
    'v2.backend.app.domain.trainer_worker_health'` and re-importing,
    `redis` is NOT in `sys.modules` (the package import does not
    transitively load redis).

28. `test_worker_health_domain_does_not_import_url_env.py` — opens
    each of the six authored source files via `inspect.getsource`;
    asserts the forbidden literals
    `from v2.backend.app.adapters`, `url_env`, `os.environ`,
    `subprocess`, `socket.socket`, `time.time(`, `time.monotonic(`,
    `datetime.now(`, `datetime.utcnow(`, `print(`, `logging.`,
    `from v2.backend.app.services`,
    `from v2.backend.app.composition`,
    `from v2.backend.app.adapters.redis_v2` do NOT appear in any
    of the six source files. Asserts after re-importing the
    package, `v2.backend.app.adapters.redis_v2.url_env` is NOT in
    `sys.modules`.

The 24-test count above is enumerated as items 1-28 in this
document. Five of those numbers are not test files (item 0 is the
package marker; items 25-28 are listed in sequence). The total
authored test file count is 24 distinct test files plus one
`__init__.py` package marker.

## Validation commands the implementation task MUST run

In order, abort on first non-zero exit:

- `python -m py_compile v2/backend/app/domain/trainer_worker_health/__init__.py v2/backend/app/domain/trainer_worker_health/errors.py v2/backend/app/domain/trainer_worker_health/health_status.py v2/backend/app/domain/trainer_worker_health/health_thresholds.py v2/backend/app/domain/trainer_worker_health/health_snapshot.py v2/backend/app/domain/trainer_worker_health/health_evaluator.py`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_worker_health/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_liveness/ -q`
  (cross-isolation regression check; existing 2E1 alpha tests must
  remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/composition/trainer_parity/ -q`
  (cross-isolation regression check; existing 2E1.E composition
  tests must remain green)
- `.venv/bin/python -m pytest v2/backend/tests/unit/services/trainer_parity/ -q`
  (cross-isolation regression check; existing 2E1.D service tests
  must remain green)
- `git status -s v2/backend/app/services/ v2/backend/app/adapters/ v2/backend/app/composition/ v2/backend/app/api/ v2/backend/app/cli/ v2/backend/app/jobs/ v2/backend/app/main.py v2/frontend/ v2/backend/tests/unit/services/ v2/backend/tests/unit/adapters/ v2/backend/tests/unit/composition/ v2/backend/tests/unit/feature_snapshots/ v2/backend/tests/unit/symbol_universe/ v2/backend/app/domain/trainer_liveness/ v2/backend/app/domain/trainer_liveness_composition/ v2/backend/app/domain/trainer_liveness_observation_collector/ v2/backend/app/domain/liveness_stream_growth/ v2/backend/tests/unit/domain/trainer_liveness/`

The last command MUST return zero lines. Any line is a hard fail.

PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_TEST_PLAN_READY
