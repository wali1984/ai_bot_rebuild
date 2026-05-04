# Phase 2E1.C.γ.real.factory — Real-Redis Reader Factory Spec

This document is the authoring spec for Phase 2E1.C.γ.real.factory of
REQ_0006. It is the narrow successor to 2E1.C.γ.real, which already
landed the read-only `RedisStreamLatestIdReader` adapter. The factory
milestone is the first milestone in the trainer-parity stack that is
allowed to import the real `redis` client library. It is non-live,
non-Redis-write, non-network-at-construction, non-legacy-mutating, and
non-deploying.

The factory is the single, explicit gateway through which a real
`redis.Redis` instance is constructed and wrapped in the existing γ.real
`RedisStreamLatestIdReader`. No other module in the trainer-parity
stack is permitted to import `redis`.

## Predecessor gates

- 2E1.A subprocess adapter:
  `PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md`).
- 2E1.B trainer output contract:
  `PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/34_2E1B_CODEX_GO_NO_GO.md`).
- 2E1.C.α liveness signal snapshot:
  `PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/53_2E1C_ALPHA_CODEX_REREVIEW_GO_NO_GO.md`).
- 2E1.C.β stream-id growth domain:
  `PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/69_2E1C_BETA_FINAL_CODEX_GO_NO_GO.md`).
- 2E1.C.γ observation collector:
  `PHASE2E1C_GAMMA_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/95_2E1C_GAMMA_CODEX_GO_NO_GO.md`).
- 2E1.C.δ snapshot composition:
  `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/87_2E1C_DELTA_CODEX_GO_NO_GO.md`).
- 2E1.C.γ.real reader:
  `PHASE2E1C_GAMMA_REAL_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/103_2E1C_GAMMA_REAL_CODEX_GO_NO_GO.md`).

If any predecessor marker is absent, the supervisor MUST NOT dispatch
2E1.C.γ.real.factory. The implementation task encodes the γ.real Codex
pass as its primary additional marker.

## Scope (additive only — no edits to existing γ.real surface)

Files to create (exact set, no extras):

- `v2/backend/app/adapters/redis_v2/url_env.py` — `read_v2_redis_url`
  helper that reads `V2_REDIS_URL` from a supplied mapping (or
  `os.environ` by default) and validates the URL string.
- `v2/backend/app/adapters/redis_v2/factory.py` —
  `make_real_redis_stream_latest_id_reader` factory that constructs a
  `redis.Redis` instance via `redis.Redis.from_url(url)` and wraps it in
  the existing γ.real `RedisStreamLatestIdReader`.

Files that MUST NOT be modified:

- `v2/backend/app/adapters/redis_v2/__init__.py` (γ.real public surface)
- `v2/backend/app/adapters/redis_v2/errors.py`
- `v2/backend/app/adapters/redis_v2/stream_latest_id_reader.py`
- `v2/backend/app/adapters/redis_v2/client.py` (legacy scaffold)
- `v2/backend/app/adapters/redis_v2/streams.py` (legacy scaffold)
- `v2/backend/app/adapters/redis_v2/retention.py` (legacy scaffold)
- every existing file under `v2/backend/tests/unit/adapters/redis_v2/`
- every file under α, β, γ, δ source and test trees.

The factory milestone deliberately does NOT extend the public surface
of `v2.backend.app.adapters.redis_v2`. Importing the package itself
MUST remain free of `redis` import side-effects. Consumers that need
the factory call it via the explicit import:

```
from v2.backend.app.adapters.redis_v2.factory import (
    make_real_redis_stream_latest_id_reader,
)
```

This preserves the γ.real invariant that
`import v2.backend.app.adapters.redis_v2` performs no Redis client
import.

## `read_v2_redis_url` (`url_env.py`)

Signature:

```
def read_v2_redis_url(*, env: object | None = None) -> str
```

Behavior contract (executed in this exact order; deviation is a hard
fail):

1. Resolve `source`: if `env is None`, use `os.environ`; otherwise use
   `env`.
2. If `source` does not have a callable `get` attribute, raise
   `RedisStreamReaderError("must_expose_get", field="env")`.
3. Take `raw = source.get("V2_REDIS_URL")`.
4. If `raw is None`, raise
   `RedisStreamReaderError("must_be_set", field="V2_REDIS_URL")`.
5. If `raw` is not a `str`, raise
   `RedisStreamReaderError("must_be_str", field="V2_REDIS_URL")`.
6. If `raw == ""`, raise
   `RedisStreamReaderError("must_be_nonempty", field="V2_REDIS_URL")`.
7. If `raw` does not start with one of the literal prefixes
   `redis://`, `rediss://`, or `unix://`, raise
   `RedisStreamReaderError("must_use_allowed_scheme", field="V2_REDIS_URL")`.
8. Return `raw` unchanged.

`url_env.py` MUST NOT import `redis`, `aioredis`, `redis.asyncio`,
`hiredis`, or any third-party Redis client. `url_env.py` MUST NOT
log the URL, MUST NOT print the URL, MUST NOT include any string
matching the canonical secret-shaped tokens listed in spec 106.
`url_env.py` MUST NOT mutate the supplied `env` mapping.

## `make_real_redis_stream_latest_id_reader` (`factory.py`)

Signature:

```
def make_real_redis_stream_latest_id_reader(
    *,
    url: str | None = None,
    env: object | None = None,
) -> RedisStreamLatestIdReader
```

Behavior contract (executed in this exact order; deviation is a hard
fail):

1. If `url is None`, take
   `url = read_v2_redis_url(env=env)`.
2. If `url` is not a `str`, raise
   `RedisStreamReaderError("must_be_str", field="url")`.
3. If `url == ""`, raise
   `RedisStreamReaderError("must_be_nonempty_str", field="url")`.
4. Construct `client = redis.Redis.from_url(url)`. The factory MUST
   NOT call any other attribute of the `redis` module. The factory
   MUST NOT call `client.ping`, `client.execute_command`,
   `client.connection_pool.get_connection`, or any other method on
   the constructed client.
5. Return `RedisStreamLatestIdReader(client)`.

`factory.py` is the SINGLE module in the trainer-parity stack that is
permitted to contain the literal text `import redis`. `factory.py` MUST
NOT import `aioredis`, `redis.asyncio`, or `hiredis`. `factory.py` MUST
NOT call `time.time(`, `datetime.now(`, `datetime.utcnow(`, or any
wall-clock helper. `factory.py` MUST NOT call any Redis WRITE method
directly or transitively (no `xadd`, `xdel`, `xtrim`, `xgroup_*`,
`xack`, `set`, `hset`, `lpush`, `rpush`, `sadd`, `zadd`, `delete`,
`unlink`, `expire`, `pexpire`, `script_load`, `evalsha`, `eval`,
`flushdb`, `flushall`, `config_set`, `config_get`, `pubsub`,
`publish`).

`factory.py` MUST NOT log the URL, MUST NOT print the URL, MUST NOT
emit the URL into any returned object beyond the constructed
`redis.Redis` instance. The factory MUST NOT mutate the constructed
client. The factory MUST be referentially transparent with respect
to repeated calls with the same `url`.

`redis.Redis.from_url` is lazy in `redis-py>=5`: it constructs a
connection pool but performs no network I/O until the first command.
The factory relies on this property; the factory MUST NOT issue any
command at construction time.

## Cross-isolation

The factory milestone MUST NOT modify any file under
`v2/backend/app/domain/trainer_liveness/` (α),
`v2/backend/app/domain/liveness_stream_growth/` (β),
`v2/backend/app/domain/trainer_liveness_composition/` (δ),
`v2/backend/app/domain/trainer_liveness_observation_collector/` (γ),
`v2/backend/app/adapters/trainer/`, `v2/backend/app/adapters/codex/`,
`v2/backend/app/adapters/ollama/`,
`v2/backend/app/adapters/exchanges/`,
`v2/backend/app/adapters/symbol_sources/`,
`v2/backend/app/adapters/feature_pipeline/`,
`v2/backend/app/adapters/db/`, `v2/backend/app/adapters/evidence/`,
`v2/backend/app/services/`, `v2/backend/app/api/`,
`v2/backend/app/cli/`, `v2/backend/app/jobs/`,
`v2/backend/app/main.py`, or `v2/frontend/`.

The factory milestone MUST NOT modify any file under
`v2/backend/app/adapters/redis_v2/` other than the two new files
`url_env.py` and `factory.py`.

The factory milestone MUST NOT modify any file under
`v2/backend/tests/unit/adapters/redis_v2/` other than the new test
files enumerated in spec 105.

The factory milestone MUST NOT modify any file under
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
other than the implementer-authored
`108_2E1C_GAMMA_REAL_FACTORY_IMPLEMENTATION_REPORT.md` and
`109_2E1C_GAMMA_REAL_FACTORY_GO_NO_GO.md`.

After the factory is added, the existing α, β, γ, δ, and γ.real
pytest suites MUST remain green. Cross-isolation regression command:

```
.venv/bin/python -m pytest \
  v2/backend/tests/unit/domain/trainer_liveness/ \
  v2/backend/tests/unit/domain/liveness_stream_growth/ \
  v2/backend/tests/unit/domain/trainer_liveness_composition/ \
  v2/backend/tests/unit/domain/trainer_liveness_observation_collector/ \
  v2/backend/tests/unit/adapters/redis_v2/ \
  -q
```

`git status -s` over α, β, γ, δ, γ.real source trees, the three
existing scaffold files (`client.py`, `streams.py`, `retention.py`),
and every existing file under `v2/backend/tests/unit/adapters/redis_v2/`
that is not listed in spec 105 as new MUST return zero modified lines.

## Live-trading status

LIVE TRADING: BLOCKED. FINAL LIVE GATE: BLOCKED. No γ.real.factory
artifact may change either status. The factory constructs a Redis
client capable of READ commands only as exercised by γ.real
(`xrevrange`); no WRITE pathway is added to the trainer-parity stack
in this milestone.

PHASE2E1C_GAMMA_REAL_FACTORY_SPEC_READY
