# Phase 2E2.A — Trainer Worker Health Domain Safety Boundaries

This document is the canonical safety surface for Phase 2E2.A. The
implementation task (`100`) and the Codex review task (`101`) MUST
treat every clause below as a hard contract. Any violation is an
unconditional FAIL with no autofix path; surface to human attention.

## Hard-stop list (no autofix, surface to human)

- any modification to `/home/wali/Desktop/AI BOT`
- any read or write of any Redis key, anywhere in the milestone diff
  (no `redis` import is permitted in any authored file; the entire
  worker-health domain layer is Redis-clean)
- any restart of the live trainer / trader / orchestrator / Redis /
  VPN service
- any exchange action (placement, cancellation)
- any change of leverage or margin
- any enabling of live trading
- any deploy intent
- any production migration
- any secret-shaped string committed to the diff
- any modification of any prior-milestone source file under
  `v2/backend/app/services/trainer_parity/`,
  `v2/backend/app/adapters/redis_v2/`,
  `v2/backend/app/composition/trainer_parity/`, or
  `v2/backend/app/domain/trainer_liveness/`,
  `v2/backend/app/domain/trainer_liveness_composition/`,
  `v2/backend/app/domain/trainer_liveness_observation_collector/`,
  `v2/backend/app/domain/liveness_stream_growth/`
- any modification of any existing test file under
  `v2/backend/tests/unit/services/`,
  `v2/backend/tests/unit/adapters/`,
  `v2/backend/tests/unit/composition/`,
  `v2/backend/tests/unit/domain/trainer_liveness/`,
  `v2/backend/tests/unit/domain/trainer_liveness_composition/`,
  `v2/backend/tests/unit/domain/trainer_liveness_observation_collector/`,
  `v2/backend/tests/unit/domain/liveness_stream_growth/`,
  `v2/backend/tests/unit/feature_snapshots/`, or
  `v2/backend/tests/unit/symbol_universe/`

## Forbidden tokens (canonical list)

Per spec `141 §"Forbidden tokens"`. The forbidden-token guard tests
MUST construct every literal at runtime via string concatenation.
The guard tests scan the six authored source files only. The guard
tests skip themselves and the other 22 test files when scanning, by
limiting the scan to files under
`v2/backend/app/domain/trainer_worker_health/`.

For every (source file, token) pair, the guard MUST assert zero
occurrences. There is no exemption. The worker-health domain layer
is fully Redis-clean and adapter-clean.

## Time and I/O exclusions

Source files MUST NOT:

- read `os.environ` or any environment variable
- call `time.time(`, `time.monotonic(`, `datetime.now(`,
  `datetime.utcnow(`, or any other wall-clock helper
- open any socket
- run any subprocess
- import `redis`, `redis.asyncio`, `aioredis`, `hiredis`, `httpx`,
  `requests`, `pickle`, `json` at module top-level (json may be
  imported only if a JSON serialization helper is added; this
  milestone does not add such a helper, so json is forbidden too)
- log via `logging.*`
- call `print(`
- import any module under `v2.backend.app.adapters`,
  `v2.backend.app.services`, or `v2.backend.app.composition`

## Redis-command exclusions

Source files MUST NOT contain any of the following Redis literals,
regardless of whether they are wrapped in a try/except or guarded by
a feature flag:

- `xrevrange`, `xadd`, `xread`, `xlen`, `xinfo`, `xgroup`, `xack`,
  `xpending`, `xrange`, `xtrim`, `xautoclaim`
- `pipeline`
- `execute_command`
- `pubsub`, `publish`, `subscribe`
- `client.set`, `client.get`, `client.hset`, `client.hget`,
  `client.delete`, `client.expire`

## Import boundaries

The six authored source files import:

- `errors.py`: only the Python standard library.
- `health_status.py`: only the Python standard library.
- `health_thresholds.py`: only the Python standard library and the
  in-package `errors.py`.
- `health_snapshot.py`: the Python standard library; the in-package
  `errors.py`; the in-package `health_status.py` (constants and the
  two module-private frozensets); and the absolute path
  `v2.backend.app.domain.trainer_liveness.LivenessSignalSnapshot`.
- `health_evaluator.py`: the Python standard library; the in-package
  `errors.py`; the in-package `health_status.py`; the in-package
  `health_thresholds.py`; the in-package `health_snapshot.py`; and
  the absolute path
  `v2.backend.app.domain.trainer_liveness.LivenessSignalSnapshot`.
- `__init__.py`: only the in-package modules listed above. No
  external imports beyond what `health_evaluator.py` transitively
  pulls.

The package import MUST NOT transitively load `redis`,
`v2.backend.app.adapters.redis_v2`, or
`v2.backend.app.adapters.redis_v2.url_env`. This invariant is
asserted in `test_worker_health_domain_does_not_import_redis.py` and
`test_worker_health_domain_does_not_import_url_env.py`.

## Determinism and frozen-dataclass discipline

- All public dataclasses (`TrainerWorkerHealthThresholds`,
  `TrainerWorkerHealthSnapshot`) MUST be `@dataclass(frozen=True,
  slots=True)`.
- The evaluator MUST be a pure function: same inputs → same outputs,
  no module-level state, no global counters, no class-level mutable
  default arguments.
- The evaluator MUST NOT mutate any field of `snapshot` or
  `thresholds`. It MUST NOT mutate any tuple it receives.

## Stop conditions for the implementation task

The implementation task `100` MUST emit `146` with marker
`PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_IMPL_AND_VALIDATION_FAIL` and
stop on any of:

- predecessor marker missing or wrong
- any source file fails py_compile
- any test in the new suite fails
- any cross-isolation test suite (2E1.A through 2E1.E) regresses
- any cross-isolation `git status -s` returns at least one line
- any forbidden-token guard test fails
- any redis-import or url_env-import guard test fails
- any of the hard-stop list violations above is observed during
  authoring

## Stop conditions for the Codex review task

The Codex review task `101` MUST emit `148` with marker
`PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_CODEX_FAIL` and stop on any
hard-stop list violation, any forbidden-token violation, any
prior-milestone modification, or any safety-review row that is not
"none observed". Concrete non-safety blockers from `101` route to a
narrow REQ_0007 / REQ_0014 autofix task scoped to the six authored
source files plus the 24 new test files only; no autofix is
permitted on prior-milestone files.

PHASE2E2A_TRAINER_WORKER_HEALTH_DOMAIN_SAFETY_BOUNDARIES_READY
