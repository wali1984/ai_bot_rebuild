# Phase 2E2.B — Worker Health Service Specification

## Position in Phase 2E2

Phase 2E2.B is the second sub-phase under
`140_PHASE_2E2_SUB_PHASE_BREAKDOWN.md`. Predecessor is Phase 2E2.A
(worker health domain) with terminal Codex marker
`PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_PASS` materialized at
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/152_2E2A_CODEX_REREVIEW_AFTER_ADDENDUM_GO_NO_GO.md`.
Successor is Phase 2E2.C (worker health composition root). 2E2.B does
not modify any 2E2.A artifact and does not modify any prior milestone.

## Surface authored in 2E2.B

Three source files under `v2/backend/app/services/trainer_worker_health/`:

- `__init__.py`
- `errors.py`
- `service.py`

One package marker plus the test files under
`v2/backend/tests/unit/services/trainer_worker_health/`. The
`v2/backend/tests/unit/services/__init__.py` package marker authored
in Phase 2E1.D is reused as-is and is NOT re-emitted by 2E2.B.

## Public surface

`v2/backend/app/services/trainer_worker_health/__init__.py` re-exports
exactly this two-name tuple in this exact order in `__all__`:

1. `evaluate_worker_health`
2. `TrainerWorkerHealthServiceError`

No other names are re-exported. No module-level globals are introduced
by `__init__.py` other than the two re-exports.

## TrainerWorkerHealthServiceError

Defined in `v2/backend/app/services/trainer_worker_health/errors.py`.

- Subclass of `ValueError`.
- `__init__(self, code: str, *, field: str)`.
- Stores `self.code` and `self.field`.
- `__str__` returns `f"{self.code} ({self.field})"`.
- `__repr__` returns `f"TrainerWorkerHealthServiceError(code={self.code!r}, field={self.field!r})"`.
- File imports nothing beyond `from __future__ import annotations`.

## evaluate_worker_health

Defined in `v2/backend/app/services/trainer_worker_health/service.py`.

Signature, in this exact order:

```
def evaluate_worker_health(
    snapshot: LivenessSignalSnapshot,
    *,
    thresholds: TrainerWorkerHealthThresholds,
    now_ms_clock: Callable[[], int],
) -> TrainerWorkerHealthSnapshot
```

Behavior contract, in this exact order:

1. If `snapshot` is not an instance of
   `v2.backend.app.domain.trainer_liveness.LivenessSignalSnapshot`,
   raise `TrainerWorkerHealthServiceError("must_be_liveness_signal_snapshot", field="snapshot")`.
2. If `thresholds` is not an instance of
   `v2.backend.app.domain.trainer_worker_health.TrainerWorkerHealthThresholds`,
   raise `TrainerWorkerHealthServiceError("must_be_worker_health_thresholds", field="thresholds")`.
3. If `now_ms_clock` is not callable,
   raise `TrainerWorkerHealthServiceError("must_be_callable", field="now_ms_clock")`.
4. Call `now_ms_clock()` exactly once and bind the result to `now_ms`.
5. If `type(now_ms)` is not exactly `int`,
   raise `TrainerWorkerHealthServiceError("must_be_int", field="now_ms_clock")`.
6. If `now_ms < 0`,
   raise `TrainerWorkerHealthServiceError("must_be_nonnegative", field="now_ms_clock")`.
7. If `now_ms < snapshot.observation_ts_ms`,
   raise `TrainerWorkerHealthServiceError("now_before_observation", field="now_ms_clock")`.
8. Delegate to
   `evaluate_trainer_worker_health(snapshot, thresholds, now_ms)`
   (imported from `v2.backend.app.domain.trainer_worker_health`) and
   return its result unchanged.

## Imports allowed in service.py

- `from __future__ import annotations`.
- `from collections.abc import Callable`.
- `from v2.backend.app.domain.trainer_liveness import LivenessSignalSnapshot`.
- `from v2.backend.app.domain.trainer_worker_health import (TrainerWorkerHealthSnapshot, TrainerWorkerHealthThresholds, evaluate_trainer_worker_health)`.
- `from .errors import TrainerWorkerHealthServiceError`.

No other import is permitted in `service.py`. No standard-library
import beyond `__future__` and `collections.abc`. No `typing` import.
No `dataclasses` import.

## Imports allowed in __init__.py

- `from .errors import TrainerWorkerHealthServiceError`.
- `from .service import evaluate_worker_health`.

No other import is permitted in `__init__.py`.

## Redis-clean invariant

The 2E2.B service must preserve the redis-clean import invariant
identical to Phase 2E1.D:

- No direct `redis` import.
- No `redis.asyncio` import.
- No `aioredis` import.
- No `hiredis` import.
- No `httpx` import.
- No `requests` import.
- No `v2.backend.app.adapters.redis_v2.url_env` import.
- No transitive load of `redis` or `url_env` when the service package
  is imported, asserted by a sys.modules guard test.

## Forbidden tokens in source files

The three authored source files must not contain any of the following
literal substrings, verified by `rg --fixed-strings --case-sensitive`:

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
- `datetime.now`
- `datetime.utcnow`
- `print(`
- `logging.`
- `FastAPI`
- `APIRouter`
- `lifespan`
- `Depends`
- `BackgroundTasks`
- `lru_cache`
- `cached_property`
- `threading.Lock`

## Module-level invariants

The three authored source files must not contain any of the following
at module scope:

- A FastAPI startup hook, lifespan handler, dependency, or router
  registration.
- A module-level singleton, cache, or lock.
- A wall-clock helper call (`time.time`, `time.monotonic`,
  `datetime.now`, `datetime.utcnow`).
- A logging call or stdout call.
- An `os.environ` read.
- A `subprocess` invocation or a `socket` use.
- A URL string, a token-shaped string, a key-shaped string, or any
  credential-shaped string.

## Cross-isolation invariants

Phase 2E2.B authors no file under any of the following paths and
modifies no byte of any prior-milestone file:

- `v2/backend/app/services/__init__.py`.
- `v2/backend/app/services/agent_supervisor_reader.py`.
- `v2/backend/app/services/audit_writer.py`.
- `v2/backend/app/services/discovery_runner.py`.
- `v2/backend/app/services/execution_router.py`.
- `v2/backend/app/services/feature_assembly.py`.
- `v2/backend/app/services/feature_snapshots/`.
- `v2/backend/app/services/hot_reload_orchestrator.py`.
- `v2/backend/app/services/monitor_runner.py`.
- `v2/backend/app/services/orchestrator_decision.py`.
- `v2/backend/app/services/paper_loop.py`.
- `v2/backend/app/services/prediction_ingest.py`.
- `v2/backend/app/services/replay_runner.py`.
- `v2/backend/app/services/risk_gateway.py`.
- `v2/backend/app/services/selection_runner.py`.
- `v2/backend/app/services/signal_publisher.py`.
- `v2/backend/app/services/symbol_universe/`.
- `v2/backend/app/services/trainer_parity/`.
- `v2/backend/app/adapters/`.
- `v2/backend/app/composition/`.
- `v2/backend/app/domain/`.
- `v2/backend/app/api/`.
- `v2/backend/app/cli/`.
- `v2/backend/app/jobs/`.
- `v2/backend/app/main.py`.
- `v2/frontend/`.
- `v2/backend/tests/unit/__init__.py`.
- `v2/backend/tests/unit/services/__init__.py`.
- `v2/backend/tests/unit/services/trainer_parity/`.
- `v2/backend/tests/unit/composition/`.
- `v2/backend/tests/unit/adapters/`.
- `v2/backend/tests/unit/domain/`.
- `v2/backend/tests/unit/feature_snapshots/`.
- `v2/backend/tests/unit/symbol_universe/`.

## Hard stops

The 2E2.B milestone must not:

- modify `/home/wali/Desktop/AI BOT`.
- modify any file under `v2/backend/app/domain/trainer_worker_health/`
  authored in Phase 2E2.A.
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

PHASE2E2B_TRAINER_WORKER_HEALTH_SERVICE_SPEC_READY
