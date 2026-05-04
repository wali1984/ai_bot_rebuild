# Phase 2E1.C.γ.real.factory — Test Plan

This document enumerates every test the implementer MUST author for
Phase 2E1.C.γ.real.factory. Each row is a separate file under
`v2/backend/tests/unit/adapters/redis_v2/`. Tests use hand-written
fakes; no real Redis connection is required at any point.

## New test files (exact set, no extras)

### `url_env.py` rubric

1. `test_url_env_reads_v2_redis_url_from_supplied_env.py` — supplied
   mapping with `V2_REDIS_URL=redis://localhost:6379/0` returns the
   value unchanged.
2. `test_url_env_accepts_redis_scheme.py` — `redis://...` accepted.
3. `test_url_env_accepts_rediss_scheme.py` — `rediss://...` accepted.
4. `test_url_env_accepts_unix_scheme.py` — `unix:///tmp/r.sock`
   accepted.
5. `test_url_env_rejects_http_scheme.py` — `http://localhost` raises
   `RedisStreamReaderError("must_use_allowed_scheme", field="V2_REDIS_URL")`.
6. `test_url_env_rejects_file_scheme.py` — `file:///etc/passwd` raises
   `must_use_allowed_scheme`.
7. `test_url_env_rejects_ftp_scheme.py` — `ftp://x` raises
   `must_use_allowed_scheme`.
8. `test_url_env_rejects_missing_var.py` — env without
   `V2_REDIS_URL` raises
   `RedisStreamReaderError("must_be_set", field="V2_REDIS_URL")`.
9. `test_url_env_rejects_non_str_value.py` — env with int/bytes value
   raises
   `RedisStreamReaderError("must_be_str", field="V2_REDIS_URL")`.
10. `test_url_env_rejects_empty_value.py` — empty string raises
    `RedisStreamReaderError("must_be_nonempty", field="V2_REDIS_URL")`.
11. `test_url_env_rejects_env_without_get.py` — env mapping lacking
    a callable `get` raises
    `RedisStreamReaderError("must_expose_get", field="env")`.
12. `test_url_env_uses_os_environ_when_env_none.py` — patch
    `os.environ` via `monkeypatch.setenv` and confirm the helper
    reads `V2_REDIS_URL` from `os.environ` when `env is None`.
13. `test_url_env_does_not_mutate_supplied_env.py` — round-trip
    confirmation that the supplied mapping is unchanged after the
    call.
14. `test_url_env_module_does_not_import_redis.py` — `inspect.getsource`
    on the `url_env` module contains no `import redis`, `from redis`,
    `redis.asyncio`, `aioredis`, or `hiredis` literal.

### `factory.py` rubric

15. `test_factory_constructs_reader_via_redis_from_url.py` — patch
    `v2.backend.app.adapters.redis_v2.factory.redis` with a fake
    module exposing a callable `Redis.from_url`. Call
    `make_real_redis_stream_latest_id_reader(url="redis://localhost:6379/0")`.
    Assert: the fake's `Redis.from_url` was called exactly once with
    the URL string; the return value is an instance of
    `RedisStreamLatestIdReader`; the reader's underlying client is the
    object returned by the fake `from_url`.
16. `test_factory_uses_url_env_when_url_none.py` — patch
    `read_v2_redis_url` to return `redis://x:1`; patch
    `factory.redis.Redis.from_url`; call
    `make_real_redis_stream_latest_id_reader()`. Assert the URL from
    the env helper is forwarded verbatim.
17. `test_factory_passes_explicit_url_verbatim.py` — patch
    `factory.redis.Redis.from_url`; call with
    `url="rediss://example:6380/2"`. Assert the URL is forwarded
    verbatim and `read_v2_redis_url` is NOT called.
18. `test_factory_rejects_non_str_url.py` — call with `url=123`;
    raises `RedisStreamReaderError("must_be_str", field="url")`.
19. `test_factory_rejects_empty_url.py` — call with `url=""`; raises
    `RedisStreamReaderError("must_be_nonempty_str", field="url")`.
20. `test_factory_does_not_call_redis_client_methods.py` — patch
    `factory.redis.Redis.from_url` to return a `MagicMock(spec=[])`
    or a hand-written fake that records every attribute access.
    Confirm the factory does not access any attribute of the
    constructed client beyond what is required to pass the
    `RedisStreamLatestIdReader.__init__` validation
    (`xrevrange`). The fake MUST record only `xrevrange` as the
    accessed callable attribute, and the factory MUST NOT call
    `xrevrange`.
21. `test_factory_returned_reader_satisfies_protocol.py` — confirm
    the returned reader satisfies
    `isinstance(reader, StreamLatestIdReader)` via the γ
    `runtime_checkable` Protocol.
22. `test_factory_only_uses_redis_module_from_url.py` — patch the
    `redis` module attribute of `factory` with a recording fake.
    After the factory call, assert the only attribute path accessed
    on the fake is `Redis.from_url`. No other attribute, method, or
    submodule access is observed.
23. `test_factory_does_not_perform_network_at_construction.py` — use
    a real `redis.Redis.from_url("redis://127.0.0.1:1/0")` (lazy
    construction). Assert no exception is raised at construction. Do
    NOT issue any command. The test passes purely on construction.
24. `test_factory_module_imports_redis_at_top.py` —
    `inspect.getsource(factory)` contains the literal text
    `import redis` at the top of the file (within the first 20
    lines, before any function definition).
25. `test_factory_module_does_not_import_aioredis_or_hiredis.py` —
    `inspect.getsource(factory)` contains no `aioredis`, no
    `redis.asyncio`, no `hiredis` literal.

### Public surface invariance

26. `test_init_module_unchanged_by_factory_milestone.py` — read
    `inspect.getsource(v2.backend.app.adapters.redis_v2)`; assert
    the source contains exactly the two imports and the `__all__`
    tuple `("RedisStreamReaderError", "RedisStreamLatestIdReader")`
    with no factory or url_env re-export, and no `import redis`
    literal. This guards the γ.real public-surface invariant.
27. `test_init_module_does_not_load_redis_when_imported.py` — clear
    `redis` from `sys.modules` (if present), import
    `v2.backend.app.adapters.redis_v2`, and assert
    `"redis" not in sys.modules`. Importing the package MUST NOT
    transitively load `redis`.

### Forbidden-token surface for the factory milestone

28. `test_factory_milestone_forbidden_tokens.py` — scan only the two
    new source files (`url_env.py`, `factory.py`) and the new test
    files listed above. The forbidden token list is the canonical
    list from spec 106 minus the two factory-permitted tokens
    (`im` + `port red` + `is` and `red` + `is.Redis.from_url(`),
    which are permitted ONLY in `factory.py`. Each token is built
    via runtime string concatenation so a grep over the test tree
    returns zero hits per literal.

## Validation commands

The implementation report MUST run and record the exit code of:

- `python -m py_compile v2/backend/app/adapters/redis_v2/url_env.py v2/backend/app/adapters/redis_v2/factory.py`
- `.venv/bin/python -m pytest v2/backend/tests/unit/adapters/redis_v2/ -q`
- `.venv/bin/python -m pytest v2/backend/tests/unit/domain/trainer_liveness/ v2/backend/tests/unit/domain/liveness_stream_growth/ v2/backend/tests/unit/domain/trainer_liveness_composition/ v2/backend/tests/unit/domain/trainer_liveness_observation_collector/ -q`
- `git status -s v2/backend/app/adapters/redis_v2/__init__.py v2/backend/app/adapters/redis_v2/errors.py v2/backend/app/adapters/redis_v2/stream_latest_id_reader.py v2/backend/app/adapters/redis_v2/client.py v2/backend/app/adapters/redis_v2/streams.py v2/backend/app/adapters/redis_v2/retention.py v2/backend/app/domain/trainer_liveness/ v2/backend/app/domain/liveness_stream_growth/ v2/backend/app/domain/trainer_liveness_composition/ v2/backend/app/domain/trainer_liveness_observation_collector/`
- For each forbidden token from spec 106 (excluding the two
  factory-permitted tokens applied only to `factory.py`),
  `rg --fixed-strings --case-sensitive <token>` over the new source
  and test files MUST return zero matches outside `factory.py`.
- `rg "^END_FILE:" v2/backend/app/adapters/redis_v2/url_env.py v2/backend/app/adapters/redis_v2/factory.py v2/backend/tests/unit/adapters/redis_v2/test_url_env_*.py v2/backend/tests/unit/adapters/redis_v2/test_factory_*.py v2/backend/tests/unit/adapters/redis_v2/test_init_module_unchanged_by_factory_milestone.py v2/backend/tests/unit/adapters/redis_v2/test_init_module_does_not_load_redis_when_imported.py v2/backend/tests/unit/adapters/redis_v2/test_factory_milestone_forbidden_tokens.py claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/108_2E1C_GAMMA_REAL_FACTORY_IMPLEMENTATION_REPORT.md claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/109_2E1C_GAMMA_REAL_FACTORY_GO_NO_GO.md` MUST return zero matches.

PHASE2E1C_GAMMA_REAL_FACTORY_TEST_PLAN_READY
