# Phase 2E1.D — Trainer Parity Service Composition Safety Boundaries

This document is the binding safety contract for Phase 2E1.D of
REQ_0006. Every rule below is non-negotiable; violation is an
unconditional Codex FAIL with no autofix path and surfaces to human
attention.

## Live-action exclusions

The 2E1.D milestone MUST NOT:

- modify any file under `/home/wali/Desktop/AI BOT/`.
- write or delete any Redis key.
- read any Redis key at construction time, at module import, or at
  any time during a unit test (the service receives a reader through
  dependency injection; the unit-test fakes never touch Redis).
- restart the live trainer, the live trader, the live orchestrator,
  Redis, or VPN.
- place, modify, or cancel any exchange order.
- change leverage or margin mode on any exchange account.
- enable live trading.
- deploy any service.
- run any production migration.
- expose any secret value in source, tests, reports, or logs.
- commit any secret value.

## Import boundaries

`v2/backend/app/services/trainer_parity/` source files MUST NOT contain
the literal text:

- `import redis`
- `from redis`
- `import aioredis`
- `from aioredis`
- `import hiredis`
- `from hiredis`
- `redis.asyncio`
- `redis.Redis`
- `from v2.backend.app.adapters.redis_v2.factory`
- `from v2.backend.app.adapters.redis_v2.url_env`
- `import v2.backend.app.adapters.redis_v2.factory`
- `import v2.backend.app.adapters.redis_v2.url_env`

The factory remains the SINGLE trainer-parity module that imports
`redis`. The 2E1.D service is reached by an external composition root
(2E1.E or later) that constructs the reader via the factory and passes
it into `evaluate_trainer_liveness`.

The service MAY import the following names, and ONLY these names, from
prior milestones:

- From `v2.backend.app.domain.trainer_liveness`:
  - `LivenessSignalSnapshot`
- From `v2.backend.app.domain.liveness_stream_growth`:
  - `GrowthWindowConfig`
  - `StreamIdObservation`
- From `v2.backend.app.domain.trainer_liveness_composition`:
  - `LivenessSnapshotBaseInputs`
  - `compose_liveness_snapshot_with_growth`
- From `v2.backend.app.domain.trainer_liveness_observation_collector`:
  - `StreamLatestIdReader`
  - `collect_stream_id_observations`
  - `extend_observation_history`

Any other cross-package import from the service module is a hard fail.

## Time and I/O exclusions

The service MUST NOT call:

- `time.time(`
- `time.monotonic(`
- `time.perf_counter(`
- `datetime.now(`
- `datetime.utcnow(`
- any timezone-bound `datetime` constructor
- any `os.environ` read or write (the factory reads
  `V2_REDIS_URL`; the service does not)
- `subprocess.run`, `subprocess.Popen`, or any subprocess helper
- `socket.socket`, `socket.create_connection`, or any socket helper
- `urllib.request`, `urllib.parse`, `requests`, `httpx`, `aiohttp`, or
  any HTTP client
- `threading.Thread`, `threading.Timer`, `asyncio.create_task`,
  `asyncio.run`, or any concurrency helper
- `print(`, `sys.stdout.write`, `sys.stderr.write`,
  `logging.getLogger`, or any logger
- any FastAPI startup hook, lifespan handler, dependency, or router
  registration

The supplied `now_ms_clock` callable is the sole time source.

## Redis-command exclusions (defense in depth)

Even though the service does not import `redis`, the service file MUST
NOT contain the literal text of any Redis WRITE command:

- `xadd`, `xdel`, `xtrim`, `xgroup_create`, `xgroup_destroy`,
  `xgroup_setid`, `xack`, `xclaim`
- `set(`, `mset`, `setnx`, `setex`, `psetex`, `getset`
- `hset`, `hmset`, `hdel`, `hsetnx`
- `lpush`, `rpush`, `lpop`, `rpop`, `lrem`, `ltrim`
- `sadd`, `srem`, `smove`
- `zadd`, `zrem`, `zincrby`, `zremrangebyscore`, `zremrangebyrank`
- `delete`, `unlink`, `expire`, `pexpire`, `persist`
- `script_load`, `evalsha`, `eval(`
- `flushdb`, `flushall`
- `config_set`, `config_get`, `config_resetstat`
- `pubsub`, `publish(`
- `connection_pool`

The service file may contain neither the literal nor any string-built
construction of these tokens. The forbidden-token guard test asserts
this by string-concatenation reconstruction at runtime.

## Mutation exclusions

The service MUST NOT:

- mutate any supplied `tuple` (tuples are immutable in Python; assert
  identity and length stability of inputs in tests 14 and 28).
- mutate any supplied dataclass field (all dataclasses in the
  trainer-parity stack are `frozen=True`).
- write to any module-level variable after import (no module-level
  caches, no module-level singletons, no module-level locks).
- modify `sys.modules`.
- modify `sys.path`.
- monkeypatch any standard-library module.

## Cross-milestone exclusions

The 2E1.D milestone MUST NOT modify:

- any file under `v2/backend/app/adapters/`
- any file under `v2/backend/app/domain/`
- any file under `v2/backend/app/api/`
- any file under `v2/backend/app/cli/`
- any file under `v2/backend/app/jobs/`
- `v2/backend/app/main.py`
- any file under `v2/frontend/`
- any file under `v2/backend/tests/unit/adapters/`
- any file under `v2/backend/tests/unit/domain/`
- any file under `v2/backend/tests/unit/feature_snapshots/` or
  `v2/backend/tests/unit/symbol_universe/`
- any file under `v2/backend/app/services/` other than the new
  `services/trainer_parity/` subpackage
- any file under `claude_worklog/autonomous_control_plane/`
- any file under `claude_worklog/agent_supervisor/tasks/`

`git status -s` over the above paths MUST report zero lines after the
implementation task completes. Any non-zero result is a hard fail.

## Secret exclusions

The 2E1.D milestone MUST NOT introduce any string matching the
canonical secret-shaped tokens (the same list applied in spec 106 §
"Secret-shaped tokens"). The forbidden-token guard test does not need
to re-scan for these (the high-confidence secret scan handles that),
but the implementation report MUST attest that the new files contain
zero matches against the canonical list.

## Stop conditions

Codex review (092) MUST emit
`PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_CODEX_FAIL` with no
autofix path if any of the following is observed:

1. Any live-action exclusion is violated.
2. Any import-boundary exclusion is violated.
3. Any time / I/O exclusion is violated.
4. Any Redis-command literal appears in the service files.
5. Any mutation exclusion is violated.
6. Any cross-milestone path is modified.
7. Any secret-shaped string appears in the diff.
8. The forbidden-token guard test does not exist or is weakened.
9. The cross-isolation guard test does not exist or is weakened.
10. The `git status -s` cross-isolation check returns any line.

In any of these cases, Codex emits the FAIL marker, enumerates the
violation in 118, and surfaces to human attention. No REQ_0007 /
REQ_0014 autofix is permitted for safety violations of this milestone.
END_FILE: claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/114_PHASE_2E1D_SERVICE_COMPOSITION_SAFETY_BOUNDARIES.md
