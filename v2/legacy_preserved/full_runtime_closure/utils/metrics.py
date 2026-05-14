from __future__ import annotations

import time

METRICS_KEY = "metrics:pipeline"


def incr(r, key: str, n: int = 1) -> None:
    try:
        r.hincrby(METRICS_KEY, key, int(n))
        r.hset(METRICS_KEY, "last_update_ms", int(time.time() * 1000))
    except Exception:
        pass


def setv(r, key: str, value) -> None:
    try:
        r.hset(METRICS_KEY, key, str(value))
        r.hset(METRICS_KEY, "last_update_ms", int(time.time() * 1000))
    except Exception:
        pass
