# Phase 2E1.C.γ.real.factory — Safety Boundaries

This document enumerates the hard safety boundaries for Phase
2E1.C.γ.real.factory. Every boundary is unconditional: a single
violation MUST result in `_BLOCKED` outcome with no autofix path,
surfaced to human attention via 108 and 109.

## Hard boundaries

1. MUST NOT modify `/home/wali/Desktop/AI BOT`.
2. MUST NOT modify `legacy_reference/`.
3. MUST NOT write Redis. MUST NOT delete Redis keys. MUST NOT
   call any Redis WRITE method directly or transitively (no
   `xadd`, `xdel`, `xtrim`, `xgroup_*`, `xack`, `set`, `hset`,
   `lpush`, `rpush`, `sadd`, `zadd`, `delete`, `unlink`,
   `expire`, `pexpire`, `script_load`, `evalsha`, `eval`,
   `flushdb`, `flushall`, `config_set`, `config_get`,
   `pubsub`, `publish`).
4. MUST NOT issue any Redis command at construction time. The
   factory relies on `redis.Redis.from_url` lazy connection-pool
   semantics. No `ping`, no `execute_command`, no
   `connection_pool.get_connection`.
5. MUST NOT import `aioredis`, `redis.asyncio`, or `hiredis`
   anywhere.
6. MUST NOT contain `import redis` or `from redis` outside
   `factory.py`. `url_env.py` and every test file MUST NOT
   contain those literals.
7. MUST NOT modify the γ.real public surface
   (`v2/backend/app/adapters/redis_v2/__init__.py`).
8. MUST NOT modify the γ.real reader
   (`v2/backend/app/adapters/redis_v2/stream_latest_id_reader.py`).
9. MUST NOT modify the γ.real error type
   (`v2/backend/app/adapters/redis_v2/errors.py`).
10. MUST NOT modify the three legacy scaffold files
    (`client.py`, `streams.py`, `retention.py`).
11. MUST NOT modify any existing file under
    `v2/backend/tests/unit/adapters/redis_v2/`. New test files
    MUST be added with the names enumerated in spec 105.
12. MUST NOT modify α, β, γ, δ, or γ.real source or test trees.
13. MUST NOT add files under `v2/backend/app/services/`,
    `v2/backend/app/api/`, `v2/backend/app/cli/`,
    `v2/backend/app/jobs/`, `v2/backend/app/main.py`,
    `v2/backend/app/adapters/trainer/`,
    `v2/backend/app/adapters/codex/`,
    `v2/backend/app/adapters/ollama/`,
    `v2/backend/app/adapters/exchanges/`,
    `v2/backend/app/adapters/symbol_sources/`,
    `v2/backend/app/adapters/feature_pipeline/`,
    `v2/backend/app/adapters/db/`,
    `v2/backend/app/adapters/evidence/`, or `v2/frontend/`.
14. MUST NOT log, print, or otherwise emit the URL string. The
    URL is treated as an opaque secret-shaped token even though
    `V2_REDIS_URL` itself is non-secret in the dev environment.
15. MUST NOT contain any of the canonical secret-shaped tokens
    listed below.
16. MUST NOT call `time.time(`, `datetime.now(`,
    `datetime.utcnow(`, or any wall-clock helper. There is no
    clock dependency in this milestone.
17. MUST NOT add a FastAPI startup hook, lifespan handler, or any
    process-level singleton wiring. The factory is a pure
    callable; consumers are responsible for lifetime management.
18. MUST NOT introduce any subprocess, socket, urllib, requests,
    httpx, or aiohttp call.
19. MUST NOT introduce any environment write (no
    `os.environ[...] =` and no `os.environ.update(...)`).
20. MUST NOT introduce any new `redis_v2` module beyond
    `url_env.py` and `factory.py`.

## Canonical secret-shaped tokens

Every authored file (source and test) MUST be free of the
following literal substrings:

- `BINANCE_API_KEY`
- `BINANCE_API_SECRET`
- `KUCOIN_API_KEY`
- `KUCOIN_API_SECRET`
- `COINANK_API_KEY`
- `COINAPI_API_KEY`
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `live_trading_enabled = true`
- `live_trading_enabled=true`
- `legacy_reference`
- `/home/wali/Desktop/AI BOT` (the legacy bot path)

## Canonical forbidden-token list (spec 105 row 28)

The following tokens MUST be absent from `url_env.py`, every new
test file, and the factory milestone test
`test_factory_milestone_forbidden_tokens.py`. Tokens marked
[FACTORY-PERMITTED] are allowed ONLY in `factory.py`.

- `import redis` — [FACTORY-PERMITTED]
- `from redis` — [FACTORY-PERMITTED]
- `redis.Redis.from_url(` — [FACTORY-PERMITTED]
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
- `xadd`
- `xdel`
- `xtrim`
- `xgroup`
- `xack`
- `.set(`
- `.hset(`
- `.lpush(`
- `.rpush(`
- `.sadd(`
- `.zadd(`
- `delete`
- `unlink`
- `flushdb`
- `flushall`
- `expire`
- `pexpire`
- `script_load`
- `evalsha`
- `config_set`
- `config_get`
- `pubsub`
- `publish`
- `.ping(`
- `.execute_command(`
- `connection_pool.get_connection(`

## Live-trading status

LIVE TRADING: BLOCKED. FINAL LIVE GATE: BLOCKED. The factory
milestone does not change either status. The constructed
`redis.Redis` instance is a READ-ONLY consumer in the trainer-parity
stack. WRITE pathways are out of scope and remain blocked.

PHASE2E1C_GAMMA_REAL_FACTORY_SAFETY_BOUNDARIES_READY
