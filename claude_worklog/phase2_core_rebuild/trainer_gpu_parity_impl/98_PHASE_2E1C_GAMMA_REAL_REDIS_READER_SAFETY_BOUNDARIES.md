# Phase 2E1.C.gamma.real - Safety Boundaries

This document defines the safety boundary for the non-live Redis-backed
StreamLatestIdReader adapter milestone.

## Scope

This milestone may implement only:

- `v2/backend/app/adapters/redis_v2/__init__.py`
- `v2/backend/app/adapters/redis_v2/errors.py`
- `v2/backend/app/adapters/redis_v2/stream_latest_id_reader.py`
- unit tests under `v2/backend/tests/unit/adapters/redis_v2/`
- local validation docs `100` and `101`

The adapter is read-only. It accepts an injected Redis-shaped client and may
call only `xrevrange(stream_name, max="+", min="-", count=1)`.

## Explicitly Forbidden

The milestone must not:

- modify `/home/wali/Desktop/AI BOT`
- modify `legacy_reference/`
- write Redis
- delete Redis keys
- restart live services
- place or cancel orders
- change leverage or margin
- enable live trading
- deploy
- run production migrations
- expose or commit secrets
- construct a Redis client
- read Redis URLs or environment variables
- add FastAPI startup wiring
- add factory wiring
- import `redis`, `redis.asyncio`, `aioredis`, or `hiredis`
- import subprocess, socket, HTTP, ML, or legacy modules
- modify alpha, beta, gamma, or delta domain source trees
- modify `v2/backend/app/adapters/redis_v2/client.py`
- modify `v2/backend/app/adapters/redis_v2/streams.py`

## Allowed Redis Operation Shape

The only Redis-shaped operation permitted is a single injected-client call:

`xrevrange(stream_name, max="+", min="-", count=1)`

No other Redis-shaped method may be called or referenced in source.

## Secret Policy

No secret-shaped strings may appear in source, tests, or docs. The milestone
must pass the high-confidence secret scan before commit.

## Live Gate

Live trading remains blocked. This milestone does not grant live authority,
deployment authority, Redis-write authority, or exchange authority.

PHASE2E1C_GAMMA_REAL_REDIS_READER_SAFETY_BOUNDARIES_READY
