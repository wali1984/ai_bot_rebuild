"""Run a proven legacy ingestor script inside V2 with a v2:-prefixing Redis.

The legacy ingest scripts under ``v2/legacy_owned_runtime/ingest/`` are the
configured-and-working data collectors, but they write **un-prefixed** keys
(``kc:*``, ``orderbook:top:*`` ...). CLAUDE.md forbids writing those legacy
keys. This adapter reuses the legacy fetch/compute logic verbatim while forcing
every Redis write into the ``v2:`` namespace via a transparent proxy, so:

- NO bare/legacy Redis key can ever be written (structurally guaranteed).
- API keys come from env.local / .local_secrets (bootstrapped by the cli pkg).
- The legacy code is NOT modified on disk.

Read-only w.r.t. exchanges: these are data ingestors (no order/leverage/margin).
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
LEGACY_ROOT = REPO / "v2" / "legacy_owned_runtime"
LEGACY_INGEST = LEGACY_ROOT / "ingest"
V2_PREFIX = "v2:"

# redis-py commands whose FIRST positional arg is the key (subset used by the
# legacy ingestors). Every write goes through one of these; prefixing arg0
# guarantees the stored key lives under v2:.
KEY_FIRST_CMDS = {
    "get", "set", "setex", "setnx", "getset", "append", "strlen", "incr",
    "incrby", "decr", "expire", "pexpire", "ttl", "pttl", "exists", "delete",
    "type", "persist", "dump",
    "hget", "hset", "hmset", "hgetall", "hdel", "hkeys", "hvals", "hlen",
    "hexists", "hincrby", "hsetnx",
    "rpush", "lpush", "lrange", "llen", "ltrim", "lindex", "lpop", "rpop",
    "lset", "lrem",
    "sadd", "srem", "smembers", "scard", "sismember",
    "zadd", "zrange", "zrem", "zcard", "zscore", "zrangebyscore",
    "xadd", "xlen", "xrange", "xrevrange", "xread",
}


class PrefixedRedis:
    """Transparent proxy that prepends ``v2:`` to every key argument.

    Idempotent: a key that already begins with ``v2:`` is left as-is, so the
    proxy is safe even if a caller passes an already-namespaced key.
    """

    def __init__(self, real, prefix: str = V2_PREFIX):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_prefix", prefix)
        object.__setattr__(self, "written_keys", set())

    def _pfx(self, key):
        if isinstance(key, (bytes, bytearray)):
            key = key.decode("utf-8", "replace")
        if isinstance(key, str):
            return key if key.startswith(self._prefix) else self._prefix + key
        return key

    def pipeline(self, *a, **k):
        return _PrefixedPipeline(self._real.pipeline(*a, **k), self._prefix, self)

    def __getattr__(self, name):
        attr = getattr(self._real, name)
        if name not in KEY_FIRST_CMDS or not callable(attr):
            return attr

        def wrapped(*args, **kwargs):
            if args and isinstance(args[0], (str, bytes, bytearray)):
                pk = self._pfx(args[0])
                if name in ("set", "setex", "hset", "hmset", "rpush", "lpush",
                            "sadd", "zadd", "xadd", "incr", "setnx", "hsetnx"):
                    self.written_keys.add(pk if isinstance(pk, str) else str(pk))
                args = (pk,) + args[1:]
            return attr(*args, **kwargs)

        return wrapped


class _PrefixedPipeline:
    def __init__(self, real_pipe, prefix, parent):
        self._real = real_pipe
        self._prefix = prefix
        self._parent = parent

    def _pfx(self, key):
        return self._parent._pfx(key)

    def execute(self, *a, **k):
        return self._real.execute(*a, **k)

    def __getattr__(self, name):
        attr = getattr(self._real, name)
        if name not in KEY_FIRST_CMDS or not callable(attr):
            return attr

        def wrapped(*args, **kwargs):
            if args and isinstance(args[0], (str, bytes, bytearray)):
                args = (self._pfx(args[0]),) + args[1:]
            res = attr(*args, **kwargs)
            return self if res is self._real else res

        return wrapped


def _connect_real_redis():
    import redis
    real = redis.Redis if not hasattr(redis.Redis, "_v2_orig") else redis.Redis._v2_orig
    return real(
        host=os.getenv("REDIS_HOST", "127.0.0.1"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        db=int(os.getenv("REDIS_DB", "0")),
        decode_responses=True,
    )


def install_redis_prefix_patch():
    """Wrap redis.Redis / StrictRedis / from_url so EVERY client a legacy
    script creates (module-global or local) writes only under ``v2:``.

    Returns a shared key-tracking PrefixedRedis-less set is not used; instead
    each wrapped client tracks its own written keys, aggregated via the global
    ``_WRITTEN``.
    """
    import redis

    if getattr(redis.Redis, "_v2_patched", False):
        return
    orig_redis = redis.Redis
    orig_strict = getattr(redis, "StrictRedis", redis.Redis)
    orig_from_url = redis.from_url

    def _wrap(client):
        proxy = PrefixedRedis(client)
        proxy.written_keys = _WRITTEN  # share the global set
        return proxy

    def patched_redis(*a, **k):
        return _wrap(orig_redis(*a, **k))

    def patched_from_url(*a, **k):
        return _wrap(orig_from_url(*a, **k))

    patched_redis._v2_orig = orig_redis  # type: ignore[attr-defined]
    patched_redis._v2_patched = True  # type: ignore[attr-defined]
    redis.Redis = patched_redis  # type: ignore[assignment]
    redis.StrictRedis = patched_redis  # type: ignore[assignment]
    redis.from_url = patched_from_url  # type: ignore[assignment]


_WRITTEN: set = set()


# Per-module knobs. mode: "sync" (call entry()) or "async_bounded" (asyncio
# run entry() with a timeout, for long-running WS streamers). force_attrs are
# set on the module after import (e.g. enable flags). env sets process env
# (e.g. constrain symbols) before the legacy code reads it.
LEGACY_MODULES = {
    "kucoin": {
        "module": "live_kucoin",
        "mode": "sync",
        "entry": "main",
        "argv": ["--once"],
        "force_attrs": {"KUCOIN_ENABLED": 1},
        "env": {},
    },
    "coinapi_v1": {
        "module": "live_coinapi_v1",
        "mode": "async_bounded",
        "entry": "main",
        "argv": [],
        "force_attrs": {},
        "env": {
            "COINAPI_V1_SYMBOLS": "BTCUSDT,ETHUSDT,SOLUSDT",
            "COINAPI_V1_TIMEFRAMES": "1m,5m",
        },
        "bounded_seconds": 60,
    },
}


def run_legacy(name: str, *, loop: bool, dry_run: bool, seconds: int | None) -> int:
    spec = LEGACY_MODULES.get(name)
    if not spec:
        print(f"ERROR: unknown legacy module {name!r}. "
              f"Known: {sorted(LEGACY_MODULES)}", file=sys.stderr)
        return 2

    for p in (str(LEGACY_INGEST), str(LEGACY_ROOT)):
        if p not in sys.path:
            sys.path.insert(0, p)

    import v2.backend.app.cli  # noqa: F401  (bootstrap data-provider keys)
    for k, v in spec.get("env", {}).items():
        os.environ.setdefault(k, v)

    # Universal safety: wrap redis at the library level BEFORE importing the
    # legacy module, so every client it creates (global or local) is prefixed.
    install_redis_prefix_patch()

    if dry_run:
        proxy = PrefixedRedis(_connect_real_redis())
        proxy.written_keys = _WRITTEN
        proxy.set("selftest:adapter", "ok", ex=30)
        print(f"[dry-run] module={spec['module']} mode={spec['mode']} "
              f"redis library-patched; proxy self-test wrote {sorted(_WRITTEN)} "
              f"(all v2:: {all(k.startswith('v2:') for k in _WRITTEN)})")
        return 0

    mod = importlib.import_module(spec["module"])
    for attr, val in spec["force_attrs"].items():
        setattr(mod, attr, val)
    entry = getattr(mod, spec["entry"])

    if spec["mode"] == "async_bounded":
        import asyncio
        if loop:
            # Continuous service: run the streamer unbounded (systemd Restart
            # handles failures). All writes still go through the v2: proxy.
            print(f"[{name}] running unbounded async streamer (--loop).")
            asyncio.run(entry())
        else:
            budget = seconds or spec.get("bounded_seconds", 60)

            async def _bounded():
                try:
                    await asyncio.wait_for(entry(), timeout=budget)
                except asyncio.TimeoutError:
                    print(f"[{name}] bounded run hit {budget}s budget; stopping.")
            asyncio.run(_bounded())
    else:
        argv = spec["argv"] if not loop else [a for a in spec["argv"] if a != "--once"]
        old_argv = sys.argv
        sys.argv = [spec["module"]] + argv
        try:
            entry()
        finally:
            sys.argv = old_argv

    wrote = sorted(_WRITTEN)
    print(f"[{name}] legacy run complete; v2-namespaced keys written: {len(wrote)}")
    for k in wrote[:25]:
        print("  ", k)
    bad = [k for k in wrote if not k.startswith("v2:")]
    print(f"[{name}] NON-v2 keys written: {len(bad)} (must be 0)")
    return 0 if not bad else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="v2_legacy_ingestor_adapter")
    ap.add_argument("name", choices=sorted(LEGACY_MODULES))
    ap.add_argument("--loop", action="store_true", help="continuous (default: one cycle)")
    ap.add_argument("--dry-run", action="store_true",
                    help="prove proxy namespacing without running legacy code")
    ap.add_argument("--seconds", type=int, default=None,
                    help="bounded run budget for async streamers")
    args = ap.parse_args(argv)
    return run_legacy(args.name, loop=args.loop, dry_run=args.dry_run, seconds=args.seconds)


if __name__ == "__main__":
    sys.exit(main())
