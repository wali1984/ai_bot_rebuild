# Phase 2E1.C.γ.real — Real-Redis StreamLatestIdReader Adapter Spec

This document is the authoring spec for Phase 2E1.C.γ.real of REQ_0006.

It is the first non-pure-domain trainer-parity milestone. It is
non-live, non-Redis-write, non-subprocess, non-network-helper-imported,
non-legacy-mutating, and non-deploying. The artifact authored here is a
single read-only adapter that satisfies the γ `StreamLatestIdReader`
Protocol via Redis `XREVRANGE COUNT 1`, plus a domain-specific error
type and a public surface re-export.

The adapter does NOT construct a Redis client. The Redis client is
injected by the caller. Constructing a real `redis.Redis` instance and
wiring the URL into FastAPI startup is deferred to a separate later
sub-phase named γ.real.factory under its own spec turn.

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
- 2E1.C.δ snapshot composition:
  `PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/87_2E1C_DELTA_CODEX_GO_NO_GO.md`).
- 2E1.C.γ observation collector:
  `PHASE2E1C_GAMMA_TRAINER_PARITY_IMPL_CODEX_PASS`
  (`trainer_gpu_parity_impl/95_2E1C_GAMMA_CODEX_GO_NO_GO.md`).

If any predecessor marker is absent, the supervisor MUST NOT dispatch
2E1.C.γ.real. The implementation task encodes the γ Codex pass as its
primary additional marker.

## Position in 2E1.C breakdown

- 2E1.C.α — liveness snapshot dataclass plus evaluator. Done.
- 2E1.C.β — stream-id growth window calculator. Done.
- 2E1.C.δ — snapshot composition (α plus β) layer. Done.
- 2E1.C.γ — pure-domain observation collector adapter port. Done.
- 2E1.C.γ.real — real-Redis StreamLatestIdReader implementation
  (this spec).
- 2E1.C.γ.real.factory — future, separately-spec'd sub-phase that
  wires `redis.Redis.from_url(...)` from `V2_REDIS_URL` at FastAPI
  startup, plus a small env-mapping URL helper. Out of scope here.

## Surface to create

Package: `v2/backend/app/adapters/redis_v2/`

Existing scaffold files in this package MUST remain unmodified:

- `client.py` (placeholder docstring, untouched)
- `streams.py` (placeholder docstring, untouched)

Files to create or overwrite (exact set, no extras):

- `__init__.py` — overwrite the empty placeholder with a public
  surface that re-exports exactly the two new public symbols listed
  below. The new `__init__.py` MUST NOT re-export anything from
  `client.py` or `streams.py`.
- `errors.py` — `RedisStreamReaderError` exception type.
- `stream_latest_id_reader.py` — `RedisStreamLatestIdReader`
  implementation of the γ `StreamLatestIdReader` Protocol.

Tests live in `v2/backend/tests/unit/adapters/redis_v2/`. The
`__init__.py` for the test package MUST be created.

The γ.real adapter MAY import:

- `from v2.backend.app.adapters.redis_v2.errors import RedisStreamReaderError`
- `from v2.backend.app.domain.trainer_liveness_observation_collector import StreamLatestIdReader`
  (only for the optional `runtime_checkable` isinstance check; this
  import does NOT establish a static base class).

γ.real MUST NOT import from α
(`v2.backend.app.domain.trainer_liveness`), β
(`v2.backend.app.domain.liveness_stream_growth`), or δ
(`v2.backend.app.domain.trainer_liveness_composition`).

γ.real MUST NOT modify α, β, γ, or δ source trees, MUST NOT modify
`v2/backend/app/adapters/redis_v2/client.py` or `streams.py`, MUST NOT
modify any other adapter package, and MUST NOT add files under
`v2/backend/app/services/`, `v2/backend/app/api/`,
`v2/backend/app/cli/`, `v2/backend/app/jobs/`, `v2/backend/app/main.py`,
or `v2/frontend/`.

## Public surface (`__init__.py` re-exports — exactly these names)

1. `RedisStreamReaderError`
2. `RedisStreamLatestIdReader`

No other names are re-exported. No re-export of submodules. No
re-export of internal `_`-prefixed helpers. No re-export of γ public
symbols. The `__init__.py` MUST declare an explicit `__all__` tuple
containing exactly these two names in this exact order.

## `RedisStreamReaderError` (`errors.py`)

A `class RedisStreamReaderError(Exception)` whose
`__init__(self, code: str, *, field: str | None = None) -> None`
stores `code` and `field` on `self` and forwards a single human-shaped
string to `super().__init__`. `__str__` returns
`f"{code} ({field})"` when `field` is non-None, else just `code`. No
inheritance from γ `ObservationCollectorError`, β
`LivenessStreamGrowthDomainError`, α `LivenessDomainError`, or δ
`TrainerLivenessCompositionError`.

## `RedisStreamLatestIdReader` (`stream_latest_id_reader.py`)

`class RedisStreamLatestIdReader`:

- `__init__(self, redis_client: object) -> None`
  - If `redis_client` does not have a callable attribute named
    `xrevrange`, raise
    `RedisStreamReaderError("must_expose_xrevrange", field="redis_client")`.
  - Store `self._client = redis_client`. The class MUST use
    `__slots__ = ("_client",)`. No other attributes are stored.
- `latest_stream_id(self, stream_name: str) -> str | None`

Behavior contract for `latest_stream_id` (executed in this exact
order; deviation is a hard fail):

1. If `stream_name` is not a `str` or is empty, raise
   `RedisStreamReaderError("must_be_nonempty_str", field="stream_name")`.
2. Call `result = self._client.xrevrange(stream_name, max="+", min="-", count=1)`.
   The adapter MUST pass `count=1` exactly. The adapter MUST NOT use
   any other `redis-py`-shaped method on `self._client` (no `xadd`,
   `xdel`, `xtrim`, `xgroup_*`, `xack`, `xrange`, `xread`, `xreadgroup`,
   `xlen`, `xinfo_*`, `set`, `hset`, `lpush`, `rpush`, `sadd`, `zadd`,
   `delete`, `unlink`, `expire`, `pexpire`, `script_load`, `evalsha`,
   `eval`, `flushdb`, `flushall`, `config_set`, `config_get`,
   `pubsub`, `publish`).
3. If `result` is falsy (None, empty list, empty tuple), return
   `None`.
4. If `result` is not a `list` or `tuple`, raise
   `RedisStreamReaderError("xrevrange_returned_unexpected_type", field="result")`.
5. Take `first = result[0]`. If `first` is not a `list` or `tuple`,
   or `len(first) < 1`, raise
   `RedisStreamReaderError("xrevrange_entry_malformed", field="result")`.
6. Take `raw_id = first[0]`. If `raw_id` is `bytes`, return
   `raw_id.decode("ascii")`. If `raw_id` is `str`, return `raw_id`
   unchanged. Otherwise raise
   `RedisStreamReaderError("xrevrange_entry_id_not_str_or_bytes", field="result")`.

The adapter MUST be referentially transparent with respect to its
inputs: it MUST NOT mutate `redis_client`, `stream_name`, or any
returned object.

The adapter MUST NOT log secrets, MUST NOT log the raw redis URL,
MUST NOT log API keys, MUST NOT include any string matching the
canonical secret-shaped tokens listed in spec 98.

The adapter MUST NOT import `redis`, `aioredis`, `redis.asyncio`,
`hiredis`, or any third-party Redis client. The injected
`redis_client` may be a real `redis.Redis` instance constructed by
the future γ.real.factory milestone, or a hand-written test fake.

The adapter MUST NOT call `time.time(`, `datetime.now(`,
`datetime.utcnow(`, or any wall-clock helper. There is no clock
dependency in this milestone.

## `__init__.py`

Overwrite the existing one-line placeholder with:

```
from v2.backend.app.adapters.redis_v2.errors import RedisStreamReaderError
from v2.backend.app.adapters.redis_v2.stream_latest_id_reader import (
    RedisStreamLatestIdReader,
)

__all__ = (
    "RedisStreamReaderError",
    "RedisStreamLatestIdReader",
)
```

No other imports. No side effects at import. No clock reads. No env
reads. No network reads. No Redis client construction.

## Cross-isolation

γ.real MUST NOT modify any file under
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

γ.real MUST NOT modify
`v2/backend/app/adapters/redis_v2/client.py` or
`v2/backend/app/adapters/redis_v2/streams.py`.

γ.real MUST NOT modify any file under
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`
other than the implementer-authored
`100_2E1C_GAMMA_REAL_GO_NO_GO.md` and
`101_2E1C_GAMMA_REAL_IMPLEMENTATION_REPORT.md`.

After γ.real is added, the existing α, β, γ, and δ pytest suites
MUST remain green. Cross-isolation regression command:

```
.venv/bin/python -m pytest \
  v2/backend/tests/unit/domain/trainer_liveness/ \
  v2/backend/tests/unit/domain/liveness_stream_growth/ \
  v2/backend/tests/unit/domain/trainer_liveness_composition/ \
  v2/backend/tests/unit/domain/trainer_liveness_observation_collector/ \
  -q
```

`git status -s` over the α, β, γ, and δ source trees, plus
`v2/backend/app/adapters/redis_v2/client.py` and
`v2/backend/app/adapters/redis_v2/streams.py`, MUST return zero
modified lines.

## Live-trading status

LIVE TRADING: BLOCKED. FINAL LIVE GATE: BLOCKED. No γ.real artifact
may change either status.

PHASE2E1C_GAMMA_REAL_REDIS_READER_SPEC_READY
