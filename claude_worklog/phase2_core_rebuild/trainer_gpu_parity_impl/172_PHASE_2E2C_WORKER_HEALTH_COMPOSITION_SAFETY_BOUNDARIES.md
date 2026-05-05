# Phase 2E2.C — Worker Health Composition Root Safety Boundaries

This document is the canonical safety surface for Phase 2E2.C. The
implementation task (108) and the Codex review task (109) MUST treat
every clause below as a hard contract. Any violation is an
unconditional FAIL with no autofix path; surface to human attention.

## Hard-stop list (no autofix, surface to human)

- any modification to `/home/wali/Desktop/AI BOT`.
- any read or write of any Redis key inside this milestone's diff.
  No Redis I/O is permitted at import time, build-time construction,
  inside the returned evaluator closure, or in any unit test. The
  2E2.B service consumes no Redis-backed dependency, so the 2E2.C
  composition root has no permitted Redis call path of any kind.
- any restart of the live trainer / trader / orchestrator / Redis /
  VPN service.
- any exchange action (placement, cancellation).
- any change of leverage or margin.
- any enabling of live trading.
- any deploy intent.
- any production migration.
- any secret-shaped string committed to the diff.
- any modification of any prior-milestone source file under
  `v2/backend/app/services/trainer_worker_health/`,
  `v2/backend/app/domain/trainer_worker_health/`,
  `v2/backend/app/services/trainer_parity/`,
  `v2/backend/app/composition/trainer_parity/`,
  `v2/backend/app/adapters/redis_v2/`, or
  `v2/backend/app/domain/`.
- any modification of any existing test file under
  `v2/backend/tests/unit/services/`,
  `v2/backend/tests/unit/domain/`,
  `v2/backend/tests/unit/adapters/`,
  `v2/backend/tests/unit/composition/trainer_parity/`,
  `v2/backend/tests/unit/feature_snapshots/`, or
  `v2/backend/tests/unit/symbol_universe/`.

## Forbidden tokens (canonical list)

Per spec 170 § "Forbidden tokens in source files". The
forbidden-token guard test
(`test_composition_milestone_forbidden_tokens.py`) MUST construct
every literal at runtime via string concatenation. The guard MUST
scan the three authored source files
(`v2/backend/app/composition/trainer_worker_health/__init__.py`,
`errors.py`, `runtime.py`) and the 19 sibling test files (excluding
the guard test itself, to avoid self-reference). NO exemption
applies in this milestone — the 2E2.C composition root has zero
permitted Redis-related imports.

## Time and I/O exclusions

Source files (`__init__.py`, `errors.py`, `runtime.py`) MUST NOT
contain or invoke:

- `time.time(`, `time.monotonic(`, `time.perf_counter(`,
  `time.process_time(`.
- `datetime.now(`, `datetime.utcnow(`, `datetime.datetime.now(`,
  `datetime.datetime.utcnow(`.
- `os.environ`, `os.getenv(`.
- any `subprocess.` invocation.
- any `socket.` invocation.
- `requests.`, `httpx.`, `aiohttp.`, `urllib.request`,
  `urllib.parse`.
- any file read (`open(`, `pathlib.Path(`'s `read_text` or
  `read_bytes`).
- any logging call (`logger.`, `logging.`, `print(`).
- any FastAPI / Starlette / ASGI lifespan hook, dependency, router,
  middleware, or background task.

The supplied `now_ms_clock` is the sole time source the closure is
allowed to forward. The closure MUST NOT call `now_ms_clock()`
itself; it forwards the callable as a kwarg to
`evaluate_worker_health`, which invokes it exactly once per call per
the 2E2.B contract.

## Redis-command and import exclusions

Source files MUST NOT contain or invoke any of:

- `xadd`, `xdel`, `xtrim`, `xgroup_*`, `xack`.
- `delete`, `unlink`.
- `flushdb`, `flushall`.
- `script_load`, `evalsha`, `eval(`.
- `pubsub`, `publish(`.
- `connection_pool`.
- `redis.Redis(`, `redis.Redis.from_url(`.
- `import redis`, `from redis`, `redis.asyncio`, `aioredis`,
  `hiredis`.
- `from v2.backend.app.adapters.redis_v2.factory`.
- `from v2.backend.app.adapters.redis_v2.url_env`.
- `v2.backend.app.adapters.redis_v2.factory`.
- `v2.backend.app.adapters.redis_v2.url_env`.
- `make_real_redis_stream_latest_id_reader`.

The 2E2.C composition root has zero Redis import surface. Importing
the package MUST NOT pull `redis`, `aioredis`, `hiredis`,
`redis.asyncio`, the gamma.real factory, or `url_env` into
`sys.modules`. This is asserted by
`test_init_module_does_not_load_redis.py`,
`test_init_module_does_not_load_url_env.py`, and
`test_runtime_module_does_not_load_redis_when_imported.py`.

## Import boundaries

`v2/backend/app/composition/trainer_worker_health/__init__.py`:
- imports `TrainerWorkerHealthCompositionError` from `.errors`.
- imports `TrainerWorkerHealthEvaluator` and
  `build_trainer_worker_health_evaluator` from `.runtime`.
- defines `__all__` as the exact 3-tuple in the order specified in
  spec 170 § "Public surface".
- no other imports.

`v2/backend/app/composition/trainer_worker_health/errors.py`:
- imports only `from __future__ import annotations`.
- defines `TrainerWorkerHealthCompositionError(Exception)`.
- no `v2/` imports.
- no third-party imports.
- no standard-library imports beyond `__future__`.

`v2/backend/app/composition/trainer_worker_health/runtime.py`:
- imports `from __future__ import annotations`.
- imports `Callable` from `collections.abc`.
- imports `LivenessSignalSnapshot` from
  `v2.backend.app.domain.trainer_liveness`.
- imports `TrainerWorkerHealthSnapshot` and
  `TrainerWorkerHealthThresholds` from
  `v2.backend.app.domain.trainer_worker_health`.
- imports `evaluate_worker_health` from
  `v2.backend.app.services.trainer_worker_health`.
- imports `TrainerWorkerHealthCompositionError` from `.errors`.
- no other imports.
- in particular: NO
  `v2.backend.app.adapters.redis_v2.factory` import, NO
  `v2.backend.app.adapters.redis_v2.url_env` import, NO `redis`
  import, NO direct Redis client construction, NO `typing` import,
  NO `dataclasses` import.

## Cross-isolation `git status -s` paths

The implementation task (108) MUST run `git status -s` over each of
these paths and require zero lines on the post-implementation
working tree:

- `v2/backend/app/composition/__init__.py`.
- `v2/backend/app/composition/trainer_parity/`.
- `v2/backend/app/services/`.
- `v2/backend/app/adapters/`.
- `v2/backend/app/domain/`.
- `v2/backend/app/api/`.
- `v2/backend/app/cli/`.
- `v2/backend/app/jobs/`.
- `v2/backend/app/main.py`.
- `v2/frontend/`.
- `v2/backend/tests/unit/__init__.py`.
- `v2/backend/tests/unit/composition/__init__.py`.
- `v2/backend/tests/unit/composition/trainer_parity/`.
- `v2/backend/tests/unit/services/`.
- `v2/backend/tests/unit/adapters/`.
- `v2/backend/tests/unit/domain/`.
- `v2/backend/tests/unit/feature_snapshots/`.
- `v2/backend/tests/unit/symbol_universe/`.

If any line is returned over any of those paths, the implementation
emits the FAIL marker and the supervisor surfaces to human attention.

## Stop conditions

The implementation task and the Codex review task MUST stop and emit
the FAIL marker (no autofix permitted) on any of:

- live behavior detected.
- Redis read or write of any kind in any authored file.
- Redis command at construction or import time.
- legacy mutation.
- release intent.
- modification of any prior-milestone source or test file.
- FastAPI startup hook / lifespan registration in any authored file.
- module-level singleton, cache, or lock in any authored file.
- wall-clock helper call in any authored file.
- direct `url_env` import in any authored file.
- direct `redis` import in any authored file.
- direct gamma.real factory import in any authored file.
- secret-shaped string in the milestone diff.
- forbidden-token violation (no exemption applies in 2E2.C).

Codex MAY autofix concrete non-safety blockers (test count
mismatches, prose inconsistencies, missing assertions, reorderings)
under REQ_0007 / REQ_0014 inside the three authored source files
plus the 20 new test files only. Codex MAY NOT autofix any
prior-milestone file or any cross-isolation path.

PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_SAFETY_BOUNDARIES_READY
