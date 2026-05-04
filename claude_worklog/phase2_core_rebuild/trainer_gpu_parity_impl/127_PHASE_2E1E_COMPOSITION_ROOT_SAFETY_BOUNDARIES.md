# Phase 2E1.E — Trainer Parity Composition Root Safety Boundaries

This document is the canonical safety surface for Phase 2E1.E. The
implementation task (096) and the Codex review task (097) MUST treat
every clause below as a hard contract. Any violation is an
unconditional FAIL with no autofix path; surface to human attention.

## Hard-stop list (no autofix, surface to human)

- any modification to `/home/wali/Desktop/AI BOT`
- any read or write of any Redis key inside this milestone's diff
  (the only Redis read that may occur is at runtime, when an
  application calls the evaluator and the underlying
  `RedisStreamLatestIdReader.latest_stream_id` issues an `xrevrange`;
  no Redis I/O is permitted at import time, build-time construction,
  or in any unit test)
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
  `v2/backend/app/adapters/redis_v2/`, or `v2/backend/app/domain/`
- any modification of any existing test file under
  `v2/backend/tests/unit/services/`,
  `v2/backend/tests/unit/adapters/`,
  `v2/backend/tests/unit/domain/`,
  `v2/backend/tests/unit/feature_snapshots/`, or
  `v2/backend/tests/unit/symbol_universe/`

## Forbidden tokens (canonical list)

Per spec 125 § "Forbidden tokens". The forbidden-token guard test
(`test_composition_milestone_forbidden_tokens.py`) MUST construct
every literal at runtime via string concatenation. The guard MUST
scan the three authored source files
(`v2/backend/app/composition/trainer_parity/__init__.py`, `errors.py`,
`runtime.py`) and the 24 sibling test files (excluding the guard test
itself, to avoid self-reference). The guard MUST apply the single
explicit `from v2.backend.app.adapters.redis_v2.factory` exemption in
`runtime.py` only, by asserting that literal occurs exactly 1 time
in `runtime.py` and zero times in every other scanned file.

## Time and I/O exclusions

Source files (`__init__.py`, `errors.py`, `runtime.py`) MUST NOT
contain or invoke:

- `time.time(`, `time.monotonic(`, `time.perf_counter(`,
  `time.process_time(`
- `datetime.now(`, `datetime.utcnow(`, `datetime.datetime.now(`,
  `datetime.datetime.utcnow(`
- `os.environ`, `os.getenv(`
- any `subprocess.` invocation
- any `socket.` invocation
- `requests.`, `httpx.`, `aiohttp.`, `urllib.request`, `urllib.parse`
- any file read (`open(`, `pathlib.Path(`'s `read_text` or
  `read_bytes`)
- any logging call (`logger.`, `logging.`, `print(`)
- any FastAPI / Starlette / ASGI lifespan hook, dependency, router,
  middleware, or background task

The supplied `now_ms_clock` is the sole time source the runtime is
allowed to use, and it is forwarded as a kwarg to
`evaluate_trainer_liveness` in step 11 of the spec contract — NOT
called inside `runtime.py` itself.

## Redis-command exclusions

Source files MUST NOT contain or invoke any of:

- `xadd`, `xdel`, `xtrim`, `xgroup_*`, `xack`
- `delete`, `unlink`
- `flushdb`, `flushall`
- `script_load`, `evalsha`, `eval(`
- `pubsub`, `publish(`
- `connection_pool`
- `redis.Redis(`, `redis.Redis.from_url(`
- `import redis`, `from redis`, `redis.asyncio`, `aioredis`,
  `hiredis`

The composition root MUST delegate every Redis-related concern to the
γ.real factory and the γ.real reader. The composition root itself
calls only `make_real_redis_stream_latest_id_reader(url=..., env=...)`
and stores the returned reader; it does NOT touch Redis primitives.

## Import boundaries

`v2/backend/app/composition/__init__.py`:
- empty package marker; no imports beyond `from __future__ import
  annotations` if needed.

`v2/backend/app/composition/trainer_parity/__init__.py`:
- imports `build_trainer_liveness_evaluator` and
  `TrainerLivenessEvaluator` from `.runtime`
- imports `TrainerParityCompositionError` from `.errors`
- defines `__all__` as the exact 3-tuple
- no other imports

`v2/backend/app/composition/trainer_parity/errors.py`:
- imports only the standard library
- defines `TrainerParityCompositionError(Exception)`
- no `v2/` imports

`v2/backend/app/composition/trainer_parity/runtime.py`:
- imports `from __future__ import annotations`
- imports `Callable` from `collections.abc`
- imports `make_real_redis_stream_latest_id_reader` from
  `v2.backend.app.adapters.redis_v2.factory` (exactly once; this is
  the single forbidden-token-guard exemption)
- imports `LivenessSnapshotBaseInputs` from
  `v2.backend.app.domain.trainer_liveness_composition`
- imports `GrowthWindowConfig`, `StreamIdObservation` from
  `v2.backend.app.domain.liveness_stream_growth`
- imports `evaluate_trainer_liveness`, `TrainerLivenessEvaluation`
  from `v2.backend.app.services.trainer_parity`
- imports `TrainerParityCompositionError` from `.errors`
- no other imports
- in particular: NO `v2.backend.app.adapters.redis_v2.url_env` import,
  NO `redis` import, NO direct Redis client construction

## Cross-isolation `git status -s` paths

The implementation task (096) MUST run
`git status -s` over each of these paths and require zero lines on
the post-implementation working tree:

- `v2/backend/app/services/`
- `v2/backend/app/adapters/`
- `v2/backend/app/domain/`
- `v2/backend/app/api/`
- `v2/backend/app/cli/`
- `v2/backend/app/jobs/`
- `v2/backend/app/main.py`
- `v2/frontend/`
- `v2/backend/tests/unit/services/`
- `v2/backend/tests/unit/adapters/`
- `v2/backend/tests/unit/domain/`
- `v2/backend/tests/unit/feature_snapshots/`
- `v2/backend/tests/unit/symbol_universe/`

If any line is returned over any of those paths, the implementation
emits the FAIL marker and the supervisor surfaces to human attention.

## Stop conditions

The implementation task and the Codex review task MUST stop and emit
the FAIL marker (no autofix permitted) on any of:

- live behavior detected
- Redis read or write detected outside the gated reader path
- Redis command at construction or import time
- legacy mutation
- release intent
- modification of any prior-milestone source or test file
- FastAPI startup hook / lifespan registration in any authored file
- module-level singleton, cache, or lock in any authored file
- wall-clock helper call in any authored file
- direct `url_env` import in any authored file
- direct `redis` import in any authored file
- secret-shaped string in the milestone diff
- forbidden-token violation (with the single documented exemption)

Codex MAY autofix concrete non-safety blockers (test count
mismatches, prose inconsistencies, missing assertions, reorderings)
under REQ_0007 / REQ_0014 inside the three authored source files
plus the 25 new test files only. Codex MAY NOT autofix any
prior-milestone file or any cross-isolation path.

PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_SAFETY_BOUNDARIES_READY
