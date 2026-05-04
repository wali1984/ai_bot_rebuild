# Phase 2E1.C.γ.real — Test Plan

The γ.real adapter is unit-tested without any real Redis dependency.
Every test exercises the adapter against a hand-written fake client
that records every call. No test imports `redis`, `aioredis`,
`redis.asyncio`, `hiredis`, or any third-party Redis client.

## Test package layout

`v2/backend/tests/unit/adapters/redis_v2/`

- `__init__.py` — empty package marker.
- `test_public_surface.py`
- `test_errors_format.py`
- `test_reader_validates_client_has_xrevrange.py`
- `test_reader_satisfies_stream_latest_id_reader_protocol.py`
- `test_reader_validates_stream_name_is_str.py`
- `test_reader_validates_stream_name_nonempty.py`
- `test_reader_returns_none_when_xrevrange_returns_none.py`
- `test_reader_returns_none_when_xrevrange_returns_empty_list.py`
- `test_reader_returns_str_id_when_xrevrange_returns_bytes.py`
- `test_reader_returns_str_id_when_xrevrange_returns_str.py`
- `test_reader_passes_count_one_to_xrevrange.py`
- `test_reader_passes_min_dash_and_max_plus_to_xrevrange.py`
- `test_reader_does_not_call_any_other_method.py`
- `test_reader_raises_on_xrevrange_unexpected_type.py`
- `test_reader_raises_on_xrevrange_entry_malformed.py`
- `test_reader_raises_on_xrevrange_entry_id_wrong_type.py`
- `test_reader_does_not_mutate_inputs.py`
- `test_reader_does_not_import_redis.py`
- `test_init_module_does_not_import_redis.py`
- `test_errors_module_does_not_import_redis.py`
- `test_forbidden_tokens.py`

## Test rubric (one rubric row per test file)

1. `test_public_surface` — `from v2.backend.app.adapters.redis_v2
   import RedisStreamReaderError, RedisStreamLatestIdReader`
   succeeds; `__all__` equals
   `("RedisStreamReaderError", "RedisStreamLatestIdReader")`; no
   other public names beyond `__all__` are exported (use `dir(mod)`
   filtered to names not starting with `_` and assert it is the
   exact set above).
2. `test_errors_format` — `RedisStreamReaderError("c").__str__()` is
   `"c"`; `RedisStreamReaderError("c", field="f").__str__()` is
   `"c (f)"`; `RedisStreamReaderError` does NOT subclass any γ/β/α/δ
   error type.
3. `test_reader_validates_client_has_xrevrange` — constructing the
   reader with an object that has no `xrevrange` attribute raises
   `RedisStreamReaderError("must_expose_xrevrange", field="redis_client")`.
4. `test_reader_satisfies_stream_latest_id_reader_protocol` —
   `from v2.backend.app.domain.trainer_liveness_observation_collector
   import StreamLatestIdReader; assert isinstance(reader, StreamLatestIdReader)`.
5. `test_reader_validates_stream_name_is_str` — calling
   `latest_stream_id(123)` raises
   `RedisStreamReaderError("must_be_nonempty_str", field="stream_name")`.
6. `test_reader_validates_stream_name_nonempty` — calling
   `latest_stream_id("")` raises
   `RedisStreamReaderError("must_be_nonempty_str", field="stream_name")`.
7. `test_reader_returns_none_when_xrevrange_returns_none` — fake
   client returns `None`; reader returns `None`.
8. `test_reader_returns_none_when_xrevrange_returns_empty_list` —
   fake client returns `[]`; reader returns `None`.
9. `test_reader_returns_str_id_when_xrevrange_returns_bytes` — fake
   returns `[(b"1700000000000-0", {b"k": b"v"})]`; reader returns
   `"1700000000000-0"`.
10. `test_reader_returns_str_id_when_xrevrange_returns_str` — fake
    returns `[("1700000000000-0", {"k": "v"})]`; reader returns
    `"1700000000000-0"`.
11. `test_reader_passes_count_one_to_xrevrange` — inspect the fake's
    recorded call; assert `count == 1`.
12. `test_reader_passes_min_dash_and_max_plus_to_xrevrange` — assert
    the recorded call passed `max="+"` and `min="-"`.
13. `test_reader_does_not_call_any_other_method` — fake client
    records calls to a wide method list (`xadd`, `xdel`, `xtrim`,
    `xrange`, `xread`, `xreadgroup`, `xlen`, `xinfo_stream`,
    `xinfo_groups`, `xinfo_consumers`, `set`, `hset`, `lpush`,
    `rpush`, `sadd`, `zadd`, the canonical token whose four ASCII
    letters are `d`, `e`, `l`, `e`, `t`, `e` assembled at runtime,
    `unlink`, `expire`, `pexpire`, `script_load`, `evalsha`, `eval`,
    `flushdb`, `flushall`, `config_set`, `config_get`, `pubsub`,
    `publish`). Calling `latest_stream_id("s")` MUST cause the fake
    to record exactly one call and that call's name MUST be
    `xrevrange`.
14. `test_reader_raises_on_xrevrange_unexpected_type` — fake returns
    `42`; reader raises
    `RedisStreamReaderError("xrevrange_returned_unexpected_type", field="result")`.
15. `test_reader_raises_on_xrevrange_entry_malformed` — fake returns
    `[()]`; reader raises
    `RedisStreamReaderError("xrevrange_entry_malformed", field="result")`.
16. `test_reader_raises_on_xrevrange_entry_id_wrong_type` — fake
    returns `[(123, {})]`; reader raises
    `RedisStreamReaderError("xrevrange_entry_id_not_str_or_bytes", field="result")`.
17. `test_reader_does_not_mutate_inputs` — pass an explicit
    `stream_name` literal and a fake whose `xrevrange` returns a
    list owned by the test; assert neither the literal nor the list
    is mutated, and the fake's `_calls` recording is the only side
    effect. Reader instance MUST NOT add attributes beyond `_client`.
18. `test_reader_does_not_import_redis` — `inspect.getsource(
    stream_latest_id_reader)` does NOT contain `import redis`,
    `from redis`, `redis.asyncio`, `aioredis`, or `hiredis`.
19. `test_init_module_does_not_import_redis` — same source-level
    assertion against `v2.backend.app.adapters.redis_v2` `__init__`.
20. `test_errors_module_does_not_import_redis` — same source-level
    assertion against `v2.backend.app.adapters.redis_v2.errors`.
21. `test_forbidden_tokens` — every token from the canonical
    forbidden-token list (defined below) MUST NOT appear in the
    γ.real source tree (`v2/backend/app/adapters/redis_v2/__init__.py`,
    `errors.py`, `stream_latest_id_reader.py`) and MUST NOT appear
    in the γ.real test tree
    (`v2/backend/tests/unit/adapters/redis_v2/`) when the test
    references the token via runtime fragment concatenation. The test
    walks every `.py` file in those two scopes and asserts each
    forbidden token's literal substring is absent. The test MUST
    construct each forbidden token at test runtime using string
    concatenation, joining, or character-list assembly so that no
    forbidden token literal appears in the test source itself.

## Canonical forbidden tokens (for tests 18–21)

Source-tree forbidden imports (γ.real source MUST NOT contain any of
these literal substrings):

- `import redis`
- `from redis`
- `import aioredis`
- `from aioredis`
- `redis.asyncio`
- `import hiredis`
- `from hiredis`
- `import subprocess`
- `from subprocess`
- `import socket`
- `from socket`
- `import urllib`
- `from urllib`
- `import requests`
- `from requests`
- `import httpx`
- `from httpx`
- `import aiohttp`
- `from aiohttp`
- `import numpy`
- `from numpy`
- `import torch`
- `from torch`
- `import tensorflow`
- `from tensorflow`
- `time.time(`
- `datetime.now(`
- `datetime.utcnow(`
- `legacy_reference`
- `/home/wali/Desktop/AI BOT`
- `BINANCE_API_KEY`
- `BINANCE_API_SECRET`
- `live_trading_enabled = true`
- `live_trading_enabled=true`

Source-tree forbidden Redis-write/admin command literals (γ.real
source MUST NOT contain any of these literal substrings):

- `xadd`
- `xdel`
- `xtrim`
- `xgroup`
- `xack`
- the four-letter literal that, in lowercase, spells the verb meaning
  "remove" (the verb appears in `redis-py` as a method name; γ.real
  source MUST NOT contain that literal as a substring; the test
  constructs it via `"d" + "e" + "l" + "e" + "t" + "e"` and checks)
- `unlink`
- `flushdb`
- `flushall`
- `lpush`
- `rpush`
- `sadd`
- `zadd`
- `expire`
- `pexpire`
- `script_load`
- `evalsha`
- `config_set`
- `config_get`
- `pubsub`
- `publish`

Note: `set` and `hset` are common Python identifiers (`set()` builtin,
`__hset__` is not real, etc.). The forbidden-token test for these two
verbs uses the full method-call shape literals
`.set(`, `.hset(`, `.lpush(`, `.rpush(`, `.sadd(`, `.zadd(`,
`.script_load(`, `.evalsha(`, `.config_set(`, `.config_get(`,
`.pubsub(`, `.publish(`, plus a separate scan for `redis_client.set`,
`redis_client.hset` (etc.) where applicable. The test source MUST
construct these substrings via runtime concatenation so a grep over
the test tree returns zero hits for each forbidden literal.

## END_FILE marker self-check

The implementation report (`101`) and the GO/NO-GO file (`100`) MUST
NOT contain any `END_FILE:` marker line in their bodies. The γ.real
source tree and γ.real test tree MUST NOT contain any `END_FILE:`
marker line anywhere. Validation:

```
rg "^END_FILE:" v2/backend/app/adapters/redis_v2/
rg "^END_FILE:" v2/backend/tests/unit/adapters/redis_v2/
rg "^END_FILE:" claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/100_2E1C_GAMMA_REAL_GO_NO_GO.md
rg "^END_FILE:" claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/101_2E1C_GAMMA_REAL_IMPLEMENTATION_REPORT.md
```

Each invocation MUST return zero matches. Do NOT widen the scan
beyond these four narrow scopes; older planner directives in the
broader trainer_gpu_parity_impl tree are out of scope for this
milestone.

## Cross-isolation regression command

```
.venv/bin/python -m pytest \
  v2/backend/tests/unit/domain/trainer_liveness/ \
  v2/backend/tests/unit/domain/liveness_stream_growth/ \
  v2/backend/tests/unit/domain/trainer_liveness_composition/ \
  v2/backend/tests/unit/domain/trainer_liveness_observation_collector/ \
  -q
```

All four predecessor suites MUST exit 0 with zero failures and zero
errors after γ.real is added.

## γ.real suite command

```
.venv/bin/python -m pytest v2/backend/tests/unit/adapters/redis_v2/ -q
```

MUST exit 0 with zero failures and zero errors.

## py_compile self-check

```
python -m py_compile \
  v2/backend/app/adapters/redis_v2/__init__.py \
  v2/backend/app/adapters/redis_v2/errors.py \
  v2/backend/app/adapters/redis_v2/stream_latest_id_reader.py
```

MUST exit 0.

PHASE2E1C_GAMMA_REAL_REDIS_READER_TEST_PLAN_READY
