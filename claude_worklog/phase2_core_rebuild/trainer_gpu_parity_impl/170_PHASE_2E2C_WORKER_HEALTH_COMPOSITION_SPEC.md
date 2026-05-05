# Phase 2E2.C — Worker Health Composition Root Spec

This document is the authoring spec for Phase 2E2.C of REQ_0006. It is
the closing wiring milestone of the trainer-worker-health assembly
stack: it joins the 2E2.B redis-clean worker-health service callable
(`evaluate_worker_health`) to a static-config-bound evaluator closure
that takes a single `LivenessSignalSnapshot` and returns a
`TrainerWorkerHealthSnapshot`.

The composition root preserves the redis-clean invariant of the 2E2.B
service. The 2E2.B service itself takes no Redis-backed dependency
(its sole inputs are `snapshot`, `thresholds`, and `now_ms_clock`),
so the 2E2.C composition root inherits a fully redis-clean import
graph. Importing
`v2.backend.app.composition.trainer_worker_health` MUST NOT pull
`redis`, `redis.asyncio`, `aioredis`, `hiredis`, or
`v2.backend.app.adapters.redis_v2.url_env` into `sys.modules`. This
is the inverse of the 2E1.E composition root, which DOES load Redis
because the underlying 2E1.D service consumes a Redis-backed reader.

## Position in Phase 2E2

Phase 2E2.C is the third sub-phase under
`140_PHASE_2E2_SUB_PHASE_BREAKDOWN.md`. Predecessor is Phase 2E2.B
(worker health service) with terminal Codex marker
`PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_CODEX_PASS` materialized at
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/169_2E2B_CODEX_REREVIEW_AFTER_AUTOFIX_GO_NO_GO.md`.
2E2.C does not modify any 2E2.A or 2E2.B artifact and does not modify
any prior milestone.

Phase 2E2.B artifacts that 2E2.C reads as a stable contract:

- `v2/backend/app/services/trainer_worker_health/__init__.py`
- `v2/backend/app/services/trainer_worker_health/errors.py`
- `v2/backend/app/services/trainer_worker_health/service.py`

Phase 2E2.A artifacts that 2E2.C reads as a stable contract:

- `v2/backend/app/domain/trainer_worker_health/__init__.py`
- `v2/backend/app/domain/trainer_worker_health/health_snapshot.py`
- `v2/backend/app/domain/trainer_worker_health/health_thresholds.py`

Phase 2E1.C.α artifact that 2E2.C reads as a stable contract:

- `v2/backend/app/domain/trainer_liveness/signal_snapshot.py`
  (the `LivenessSignalSnapshot` value object).

## Surface authored in 2E2.C

Three source files under `v2/backend/app/composition/trainer_worker_health/`:

- `__init__.py`
- `errors.py`
- `runtime.py`

One package marker plus the test files under
`v2/backend/tests/unit/composition/trainer_worker_health/`. The
existing `v2/backend/app/composition/__init__.py` and
`v2/backend/tests/unit/composition/__init__.py` package markers
authored in Phase 2E1.E are reused as-is and are NOT re-emitted by
2E2.C.

## Public surface

`v2/backend/app/composition/trainer_worker_health/__init__.py`
re-exports exactly this three-name tuple in this exact order in
`__all__`:

1. `build_trainer_worker_health_evaluator`
2. `TrainerWorkerHealthEvaluator`
3. `TrainerWorkerHealthCompositionError`

No other names are re-exported. The `__init__.py` MUST NOT introduce
any module-level globals beyond the three re-exports.

## TrainerWorkerHealthCompositionError

Defined in `v2/backend/app/composition/trainer_worker_health/errors.py`.

- Subclass of `Exception`.
- `__init__(self, code: str, *, field: str | None = None) -> None`.
- Stores `self.code` and `self.field`.
- Calls `super().__init__(str(self))`.
- `__str__` returns `f"{self.code} ({self.field})"` when `field is
  not None`, else returns `self.code`.
- File imports nothing beyond `from __future__ import annotations`.
- File MUST NOT import any `v2/` module, `redis`, `aioredis`,
  `hiredis`, `redis.asyncio`, the gamma.real factory, or
  `url_env`.

## TrainerWorkerHealthEvaluator

Defined in `v2/backend/app/composition/trainer_worker_health/runtime.py`
as a `Callable` type alias:

```
TrainerWorkerHealthEvaluator = Callable[
    [LivenessSignalSnapshot],
    TrainerWorkerHealthSnapshot,
]
```

The alias is defined at module scope, exported via `__init__.py`, and
is NOT a runtime class. Tests asserting "callable" use
`callable(evaluator)`.

## build_trainer_worker_health_evaluator

Defined in `v2/backend/app/composition/trainer_worker_health/runtime.py`.

Signature, in this exact order (the leading `*` enforces keyword-only):

```
def build_trainer_worker_health_evaluator(
    *,
    thresholds: TrainerWorkerHealthThresholds,
    now_ms_clock: Callable[[], int],
) -> TrainerWorkerHealthEvaluator
```

Behavior contract, in this exact order (deviation is a hard fail):

1. If `thresholds` is not an instance of
   `TrainerWorkerHealthThresholds`, raise
   `TrainerWorkerHealthCompositionError("must_be_worker_health_thresholds",
   field="thresholds")`.
2. If `now_ms_clock` is not callable, raise
   `TrainerWorkerHealthCompositionError("must_be_callable",
   field="now_ms_clock")`.
3. Capture the static config locally:
   `_thresholds = thresholds`,
   `_now_ms_clock = now_ms_clock`.
4. Define and return a closure
   `def _evaluator(snapshot)` that:
   - forwards the supplied `snapshot` as the leading positional
     argument to `evaluate_worker_health`;
   - forwards `_thresholds` and `_now_ms_clock` as the
     corresponding keyword arguments;
   - returns the resulting `TrainerWorkerHealthSnapshot` unchanged.
   Any `TrainerWorkerHealthServiceError` from the service propagates
   unchanged. Any `TrainerWorkerHealthDomainError` from deeper layers
   also propagates unchanged.

`runtime.py` MUST NOT call `now_ms_clock()` itself. The clock is a
forwarded kwarg, invoked exactly once per evaluator call by the
underlying `evaluate_worker_health` service per its 2E2.B contract.

## Imports allowed in runtime.py

- `from __future__ import annotations`.
- `from collections.abc import Callable`.
- `from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot`.
- `from v2.backend.app.domain.trainer_worker_health import (TrainerWorkerHealthSnapshot, TrainerWorkerHealthThresholds)`.
- `from v2.backend.app.services.trainer_worker_health import evaluate_worker_health`.
- `from .errors import TrainerWorkerHealthCompositionError`.

No other import is permitted in `runtime.py`. No `typing` import. No
`dataclasses` import. No standard-library import beyond `__future__`
and `collections.abc`. No third-party import. No
`v2.backend.app.adapters.redis_v2.factory` import. No
`v2.backend.app.adapters.redis_v2.url_env` import. No `redis`,
`redis.asyncio`, `aioredis`, `hiredis`, `httpx`, or `requests`
import.

## Imports allowed in __init__.py

- `from .errors import TrainerWorkerHealthCompositionError`.
- `from .runtime import TrainerWorkerHealthEvaluator, build_trainer_worker_health_evaluator`.

No other import is permitted in `__init__.py`.

## Redis-clean invariant (inherited from 2E2.B)

The 2E2.C composition root MUST preserve the redis-clean import
invariant identical to Phase 2E1.D and Phase 2E2.B:

- No direct `redis` import.
- No `redis.asyncio` import.
- No `aioredis` import.
- No `hiredis` import.
- No `httpx` import.
- No `requests` import.
- No `v2.backend.app.adapters.redis_v2.factory` import.
- No `v2.backend.app.adapters.redis_v2.url_env` import.
- No transitive load of `redis`, `aioredis`, `hiredis`,
  `redis.asyncio`, the gamma.real factory, or `url_env` when the
  composition package is imported, asserted by a `sys.modules`
  guard test.

## Forbidden tokens in source files

The three authored source files (`__init__.py`, `errors.py`,
`runtime.py`) MUST NOT contain any of the following literal
substrings, verified by `rg --fixed-strings --case-sensitive`:

- `redis`
- `Redis`
- `REDIS`
- `aioredis`
- `hiredis`
- `httpx`
- `requests`
- `url_env`
- `URL_ENV`
- `os.environ`
- `getenv`
- `subprocess`
- `socket`
- `time.time`
- `time.monotonic`
- `time.perf_counter`
- `time.process_time`
- `datetime.now`
- `datetime.utcnow`
- `print(`
- `logging.`
- `logger.`
- `FastAPI`
- `APIRouter`
- `lifespan`
- `Depends`
- `BackgroundTasks`
- `lru_cache`
- `cached_property`
- `threading.Lock`
- `xadd`
- `xdel`
- `xtrim`
- `xgroup_`
- `xack`
- `flushdb`
- `flushall`
- `script_load`
- `evalsha`
- `pubsub`
- `publish(`
- `connection_pool`
- `redis.Redis(`
- `redis.Redis.from_url(`
- `import redis`
- `from redis`
- `urllib.request`
- `urllib.parse`
- `aiohttp.`
- `factory.make_real_redis_stream_latest_id_reader`
- `make_real_redis_stream_latest_id_reader`

The forbidden-token guard test
(`test_composition_milestone_forbidden_tokens.py`) constructs every
literal at runtime via string concatenation and scans the three
authored source files plus the 19 sibling test files (the guard test
itself is excluded from its own scan to avoid self-reference). NO
exemption applies to any token in any scanned file.

## Module-level invariants

The three authored source files MUST NOT contain any of the
following at module scope:

- A FastAPI startup hook, lifespan handler, dependency, or router
  registration.
- A module-level singleton, cache, or lock.
- A wall-clock helper call (`time.time`, `time.monotonic`,
  `datetime.now`, `datetime.utcnow`).
- A logging call or stdout call (`print(`, `logger.`, `logging.`).
- An `os.environ` read.
- A `subprocess` invocation or a `socket` use.
- A URL string, a token-shaped string, a key-shaped string, or any
  credential-shaped string.

## Cross-isolation invariants

Phase 2E2.C authors no file under any of the following paths and
modifies no byte of any prior-milestone file:

- `v2/backend/app/composition/__init__.py` (existing 2E1.E marker;
  reused as-is, NOT re-emitted).
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
- `v2/backend/tests/unit/composition/__init__.py` (existing 2E1.E
  marker; reused as-is, NOT re-emitted).
- `v2/backend/tests/unit/composition/trainer_parity/`.
- `v2/backend/tests/unit/services/`.
- `v2/backend/tests/unit/adapters/`.
- `v2/backend/tests/unit/domain/`.
- `v2/backend/tests/unit/feature_snapshots/`.
- `v2/backend/tests/unit/symbol_universe/`.

The implementation task `git status -s` zero-line gate covers every
cross-isolation path above.

## Hard stops

The 2E2.C milestone MUST NOT:

- modify `/home/wali/Desktop/AI BOT`.
- modify any file under `v2/backend/app/services/trainer_worker_health/`
  authored in Phase 2E2.B.
- modify any file under `v2/backend/app/domain/trainer_worker_health/`
  authored in Phase 2E2.A.
- modify any file under `v2/backend/app/composition/trainer_parity/`
  authored in Phase 2E1.E.
- modify any file under `v2/backend/app/services/trainer_parity/`
  authored in Phase 2E1.D.
- read or write any Redis key.
- invoke any Redis command.
- restart any live service.
- place or cancel any exchange order.
- change leverage or margin.
- enable live trading.
- ship to anywhere.
- run any production migration.
- expose or commit any credential.
- approve the live gate.

## Markers

Implementation gate (after 108):
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/175_2E2C_WORKER_HEALTH_COMPOSITION_GO_NO_GO.md`
contains
`PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`.

Codex gate (after 109):
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/177_2E2C_WORKER_HEALTH_COMPOSITION_CODEX_GO_NO_GO.md`
contains
`PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_CODEX_PASS`.

PHASE2E2C_TRAINER_WORKER_HEALTH_COMPOSITION_ROOT_SPEC_READY
