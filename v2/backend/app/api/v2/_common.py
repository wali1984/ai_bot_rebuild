"""Shared helpers for the V2 landing routes.

Read-only conveniences ONLY. Anything that could mutate state lives behind
an explicit allow-list. None of these helpers are allowed to:
- place exchange orders or change leverage / margin
- write to legacy (non-`v2:` / non-`audit:`) Redis keys
- import trainer modules into the FastAPI process

Helpers:
- `get_redis()` — returns a decode-responses Redis client or `None` if the
  client is unavailable, mis-configured, or the server is unreachable. All
  callers must tolerate `None` and return their documented "missing" shape.
- `TtlCache` — tiny in-process TTL cache (1-2s) used to avoid Redis hammer.
- `require_min_role(min_role)` — FastAPI dependency that enforces a minimum
  RBAC role from the `X-Role` header. Unknown / missing → `public`.
- `write_audit_trainer_read()` — single helper for the `audit:trainer:reads`
  stream. Refuses to write unless all six canonical fields are present.
"""

from __future__ import annotations

import os
import time
from typing import Any, Iterable

from fastapi import Header, HTTPException, status

# RBAC role hierarchy. Matches v2/frontend/src/auth/rbac.ts.
ROLE_RANK: dict[str, int] = {
    "public": 0,
    "observer": 1,
    "operator": 2,
    "admin": 3,
    "trusted": 4,
}


_LOCAL_REDIS_DEFAULT = "redis://127.0.0.1:6379/0"


def _redis_url_from_env() -> str:
    """Resolve a Redis URL from env (V2_REDIS_URL, REDIS_URL, LEGACY_REDIS_URL).

    Falls back to local Redis when no env var is configured — all V2 CLI
    workers use 127.0.0.1:6379/0 as their default so the API should too.
    """
    for key in ("V2_REDIS_URL", "REDIS_URL", "LEGACY_REDIS_URL"):
        v = os.environ.get(key, "").strip()
        if v:
            return v
    return _LOCAL_REDIS_DEFAULT


def get_redis() -> Any:  # pragma: no cover - exercised in integration only
    """Return a redis client with decode_responses=True, or None.

    Never raises. Used by every read-only route in this package.
    """
    url = _redis_url_from_env()
    if not url:
        return None
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=1.0)
        # Cheap liveness check; if PING fails, treat as unavailable.
        client.ping()
        return client
    except Exception:
        return None


class TtlCache:
    """Tiny in-process TTL cache keyed by string. Not thread-safe by design;
    FastAPI's default event loop is single-threaded per worker.
    """

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = float(ttl_seconds)
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if (time.monotonic() - ts) > self._ttl:
            # Expired; lazy-evict.
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic(), value)


def require_min_role(min_role: str):
    """FastAPI dependency factory enforcing RBAC by role hierarchy.

    The role is taken from the `X-Role` request header (lowercased). Anything
    unknown or absent defaults to `public`. The actual session resolution
    will land with the real auth layer (see middleware/rbac.py); for the
    landing routes a header-driven check is sufficient and is testable.
    """
    if min_role not in ROLE_RANK:
        raise ValueError(f"unknown role: {min_role}")
    threshold = ROLE_RANK[min_role]

    async def _dep(x_role: str | None = Header(default=None)) -> str:
        role = (x_role or "public").strip().lower()
        rank = ROLE_RANK.get(role, 0)
        if rank < threshold:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"rbac_denied: required min_role={min_role}, have={role}",
            )
        return role

    return _dep


# ---------------------------------------------------------------------------
# Audit ledger helpers
# ---------------------------------------------------------------------------

# The legacy ledger may have streams under various names; we never write to
# those. The trainer-reads audit stream is V2-owned and lives under
# `audit:trainer:reads`, which we DO write to (it's a v2-namespace stream
# even though it doesn't start with `v2:`). The RedisNamespaceAdapter is
# strict about `v2:` prefix; for the trainer-reads stream we use a direct
# XADD on a `redis` client which is policy-equivalent for this specific
# audit-only stream.

AUDIT_LEDGER_STREAM_CANDIDATES: tuple[str, ...] = (
    "audit:ledger",
    "audit:ledger:stream",
    "audit:ledger:events",
    "v2:audit:ledger",
)


def discover_audit_ledger_streams(r: Any) -> list[str]:
    """Return the list of audit-ledger streams that actually exist in Redis.

    Returns [] if `r` is None or `KEYS audit:ledger*` fails. We use `scan`
    rather than `KEYS` to avoid blocking on huge keyspaces.
    """
    if r is None:
        return []
    found: list[str] = []
    try:
        for key in r.scan_iter(match="audit:ledger*", count=100):
            found.append(key)
            if len(found) > 50:
                break
        # Always also try the v2-prefixed variant.
        for key in r.scan_iter(match="v2:audit:ledger*", count=100):
            found.append(key)
            if len(found) > 100:
                break
    except Exception:
        return []
    # Stable order for predictable tests.
    return sorted(set(found))


def required_audit_fields() -> Iterable[str]:
    return ("actor", "source", "prior_state_hash", "payload", "decision_id", "chain_pointer")


def write_audit_trainer_read(
    r: Any,
    *,
    actor: str,
    source: str,
    prior_state_hash: str,
    payload: str,
    decision_id: str,
    chain_pointer: str,
    extra_fields: dict[str, str] | None = None,
) -> str | None:
    """Append a single event to the `audit:trainer:reads` stream.

    Refuses to write unless all six canonical fields are present and
    non-empty. Returns the new stream entry id, or `None` on any failure.
    """
    fields: dict[str, str] = {
        "actor": actor,
        "source": source,
        "prior_state_hash": prior_state_hash,
        "payload": payload,
        "decision_id": decision_id,
        "chain_pointer": chain_pointer,
    }
    for k in required_audit_fields():
        if not fields.get(k):
            return None
    if extra_fields:
        for k, v in extra_fields.items():
            # Defensive: never let extra fields overwrite the six required.
            if k in fields:
                continue
            fields[k] = str(v)
    if r is None:
        return None
    try:
        return r.xadd("audit:trainer:reads", fields, maxlen=10000, approximate=True)
    except Exception:
        return None
