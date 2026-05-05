# Phase 2E2.C — Worker Health Composition Root Test Plan

The test plan enumerates the canonical 20 test files under
`v2/backend/tests/unit/composition/trainer_worker_health/`. Each test
file contains exactly one test function whose name starts with
`test_` and mirrors the file basename. Tests use inline hand-written
fakes; no shared `conftest` is created or modified. No test file
imports `redis`, `aioredis`, `hiredis`, `redis.asyncio`,
`v2.backend.app.adapters.redis_v2.factory`, or
`v2.backend.app.adapters.redis_v2.url_env`.

## Required test files (20)

1. `test_public_surface.py` — imports `__all__` from
   `v2.backend.app.composition.trainer_worker_health`; asserts it is
   exactly the tuple
   `("build_trainer_worker_health_evaluator",
    "TrainerWorkerHealthEvaluator",
    "TrainerWorkerHealthCompositionError")` in that order; asserts
   each name is bound to the same object as the corresponding direct
   module attribute.

2. `test_errors_invariants.py` — constructs
   `TrainerWorkerHealthCompositionError("c1", field="f1")`; asserts
   `code == "c1"`, `field == "f1"`, `str(...) == "c1 (f1)"`. Then
   constructs `TrainerWorkerHealthCompositionError("c2")`; asserts
   `code == "c2"`, `field is None`, `str(...) == "c2"`. Asserts the
   class is a subclass of `Exception`.

3. `test_init_module_does_not_load_redis.py` — pops `redis`,
   `aioredis`, `hiredis`, `redis.asyncio` from `sys.modules` (any
   absent key is tolerated). Pops
   `v2.backend.app.composition.trainer_worker_health` and its
   `runtime` submodule. Imports
   `v2.backend.app.composition.trainer_worker_health`. Asserts that
   `redis`, `redis.asyncio`, `aioredis`, and `hiredis` are NOT in
   `sys.modules` after the import.

4. `test_init_module_does_not_load_url_env.py` — pops
   `v2.backend.app.adapters.redis_v2.url_env`,
   `v2.backend.app.adapters.redis_v2.factory`, and
   `v2.backend.app.composition.trainer_worker_health` from
   `sys.modules`. Imports
   `v2.backend.app.composition.trainer_worker_health`. Asserts that
   `v2.backend.app.adapters.redis_v2.url_env` is NOT in
   `sys.modules` and `v2.backend.app.adapters.redis_v2.factory` is
   NOT in `sys.modules`.

5. `test_init_module_does_not_register_fastapi_lifespan.py` — imports
   `v2.backend.app.composition.trainer_worker_health` and
   `v2.backend.app.composition.trainer_worker_health.runtime`.
   Iterates over each module's `dir(...)` listing and asserts no
   attribute name contains any of `lifespan`, `FastAPI`, `APIRouter`,
   `Depends`, `BackgroundTasks` as a substring.

6. `test_runtime_module_does_not_load_redis_when_imported.py` — pops
   `redis`, `aioredis`, `hiredis`, `redis.asyncio`,
   `v2.backend.app.adapters.redis_v2.factory`,
   `v2.backend.app.adapters.redis_v2.url_env`,
   `v2.backend.app.composition.trainer_worker_health`, and
   `v2.backend.app.composition.trainer_worker_health.runtime` from
   `sys.modules`. Imports
   `v2.backend.app.composition.trainer_worker_health.runtime`.
   Asserts that `redis`, `aioredis`, `hiredis`, `redis.asyncio`,
   `v2.backend.app.adapters.redis_v2.factory`, and
   `v2.backend.app.adapters.redis_v2.url_env` are all NOT in
   `sys.modules` after the import. This is the inverse-direction
   wiring assertion of the 2E1.E composition test.

7. `test_composition_milestone_forbidden_tokens.py` — builds every
   forbidden literal from spec 170 § "Forbidden tokens in source
   files" at runtime via string concatenation. Iterates over the three
   authored source files (`__init__.py`, `errors.py`, `runtime.py`)
   and the 19 sibling test files (this file is excluded from its own
   scan to avoid self-reference). For every `(file, token)` pair,
   asserts zero substring occurrences. NO exemption applies to any
   token in any file.

8. `test_composition_does_not_import_url_env_directly.py` — pops the
   relevant cache keys and imports the composition package. Reads
   `runtime.py` source via `inspect.getsource` and asserts the
   literal `url_env` does NOT appear. Also asserts
   `getattr(v2.backend.app.composition.trainer_worker_health.runtime,
   "url_env", None) is None`.

9. `test_validates_thresholds_must_be_worker_health_thresholds.py`
   — calls `build_trainer_worker_health_evaluator(thresholds=object(),
   now_ms_clock=lambda: 1)`. Asserts
   `TrainerWorkerHealthCompositionError("must_be_worker_health_thresholds",
   field="thresholds")` is raised.

10. `test_validates_now_ms_clock_callable.py` — constructs a valid
    `TrainerWorkerHealthThresholds` inline. Calls
    `build_trainer_worker_health_evaluator(thresholds=<valid>,
    now_ms_clock=42)`. Asserts
    `TrainerWorkerHealthCompositionError("must_be_callable",
    field="now_ms_clock")` is raised.

11. `test_returns_callable_evaluator.py` — constructs a valid
    `TrainerWorkerHealthThresholds` inline; calls
    `build_trainer_worker_health_evaluator(thresholds=<valid>,
    now_ms_clock=lambda: 1)`. Asserts the returned object is a
    callable per `callable(...)`.

12. `test_evaluator_forwards_snapshot_to_service.py` — monkeypatches
    `v2.backend.app.composition.trainer_worker_health.runtime.evaluate_worker_health`
    to a fake that records its leading positional argument and
    returns a sentinel `TrainerWorkerHealthSnapshot`. Constructs a
    valid `LivenessSignalSnapshot` inline. Builds the evaluator
    with valid thresholds and clock. Calls the evaluator with the
    snapshot. Asserts the captured leading-arg `id(...)` matches the
    snapshot's `id(...)`.

13. `test_evaluator_forwards_thresholds_to_service.py` —
    monkeypatches `evaluate_worker_health` to record its `thresholds`
    keyword argument and return a sentinel. Builds the evaluator
    with a sentinel-tagged `TrainerWorkerHealthThresholds`. Calls
    the evaluator with a valid snapshot. Asserts the captured
    `thresholds` kwarg `id(...)` matches the input
    `id(...)`.

14. `test_evaluator_forwards_clock_to_service.py` — monkeypatches
    `evaluate_worker_health` to record its `now_ms_clock` keyword
    argument and return a sentinel. Builds the evaluator with a
    sentinel `now_ms_clock` callable. Calls the evaluator. Asserts
    the captured `now_ms_clock` kwarg `id(...)` matches the input
    callable `id(...)`.

15. `test_evaluator_returns_service_result_unchanged.py` —
    monkeypatches `evaluate_worker_health` to return a sentinel
    `TrainerWorkerHealthSnapshot` instance. Calls the evaluator.
    Asserts the returned object is the same identity as the
    sentinel.

16. `test_evaluator_propagates_service_error.py` — monkeypatches
    `evaluate_worker_health` to raise
    `TrainerWorkerHealthServiceError("forced", field="snapshot")`.
    Calls the evaluator inside a
    `pytest.raises(TrainerWorkerHealthServiceError)` block. Asserts
    the caught exception's `code == "forced"` and
    `field == "snapshot"` post-catch.

17. `test_evaluator_does_not_mutate_supplied_snapshot.py` — captures
    the `LivenessSignalSnapshot`'s field values and `id(...)` before
    invoking the evaluator. Monkeypatches `evaluate_worker_health`
    to return a sentinel. Calls the evaluator. Asserts the original
    snapshot's field values and `id(...)` are unchanged.

18. `test_evaluator_does_not_mutate_supplied_thresholds.py` —
    captures the `TrainerWorkerHealthThresholds`'s field values and
    `id(...)` before invoking the evaluator. Monkeypatches
    `evaluate_worker_health` to return a sentinel. Calls the
    evaluator. Asserts the original thresholds object's field
    values and `id(...)` are unchanged.

19. `test_service_not_invoked_at_build_time.py` — monkeypatches
    `evaluate_worker_health` to a fake that increments a call
    counter. Calls
    `build_trainer_worker_health_evaluator(thresholds=<valid>,
    now_ms_clock=lambda: 1)` and binds the returned closure but does
    NOT invoke it. Asserts the call counter is exactly 0.

20. `test_evaluator_invokes_service_exactly_once_per_call.py` —
    monkeypatches `evaluate_worker_health` to a fake that increments
    a call counter and returns a sentinel snapshot. Builds the
    evaluator. Invokes the evaluator twice with valid snapshots.
    Asserts the call counter is exactly 2 after the second call.

## Validation commands (executed in this order; abort on first non-zero exit)

1. `python -m py_compile
   v2/backend/app/composition/trainer_worker_health/__init__.py
   v2/backend/app/composition/trainer_worker_health/errors.py
   v2/backend/app/composition/trainer_worker_health/runtime.py`
2. `.venv/bin/python -m pytest
   v2/backend/tests/unit/composition/trainer_worker_health/ -q`
   — expected: `20 passed`.
3. `.venv/bin/python -m pytest
   v2/backend/tests/unit/services/trainer_worker_health/ -q`
   — expected: existing 2E2.B suite must remain green.
4. `.venv/bin/python -m pytest
   v2/backend/tests/unit/domain/trainer_worker_health/ -q`
   — expected: existing 2E2.A suite must remain green.
5. `.venv/bin/python -m pytest
   v2/backend/tests/unit/composition/trainer_parity/ -q`
   — expected: existing 2E1.E suite must remain green.
6. `.venv/bin/python -m pytest
   v2/backend/tests/unit/services/trainer_parity/ -q`
   — expected: existing 2E1.D suite must remain green.
7. `git status -s
   v2/backend/app/composition/__init__.py
   v2/backend/app/composition/trainer_parity/
   v2/backend/app/services/
   v2/backend/app/adapters/
   v2/backend/app/domain/
   v2/backend/app/api/
   v2/backend/app/cli/
   v2/backend/app/jobs/
   v2/backend/app/main.py
   v2/frontend/
   v2/backend/tests/unit/__init__.py
   v2/backend/tests/unit/composition/__init__.py
   v2/backend/tests/unit/composition/trainer_parity/
   v2/backend/tests/unit/services/
   v2/backend/tests/unit/adapters/
   v2/backend/tests/unit/domain/
   v2/backend/tests/unit/feature_snapshots/
   v2/backend/tests/unit/symbol_universe/`
   — MUST return zero lines.
8. Forbidden-token self-grep loop:
   `rg --fixed-strings --case-sensitive '<TOKEN>'
   v2/backend/app/composition/trainer_worker_health/`
   for each token in spec 170 § "Forbidden tokens in source files".
   Every token must produce zero hits in every authored source file.
9. End-file marker self-scan:
   `rg "^END_FILE_SENTINEL:"
   v2/backend/app/composition/trainer_worker_health/
   v2/backend/tests/unit/composition/trainer_worker_health/
   claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/174_2E2C_WORKER_HEALTH_COMPOSITION_IMPLEMENTATION_REPORT.md
   claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/175_2E2C_WORKER_HEALTH_COMPOSITION_GO_NO_GO.md`
   — MUST return zero lines.

## Final test count addendum

The canonical authored test count is 20. The implementation report
(174) MUST list each test file basename and assert the disk count is
exactly 20.

PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_TEST_PLAN_READY
