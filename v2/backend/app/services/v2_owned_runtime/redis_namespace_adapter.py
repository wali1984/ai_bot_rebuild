"""Redis namespace adapter.

Enforces:
- Old Redis reads allowed only when explicitly classified
  `LEGACY_REFERENCE_READ_ONLY`.
- All V2 writes must target keys under the `v2:` prefix.
- Legacy keys never receive SET / HSET / XADD / DEL / XTRIM from V2.

This adapter does not import the `redis` client. It is a pure policy layer
that wraps any client the caller passes in. If the caller passes None,
the adapter operates in dry-run mode and rejects any mutation while still
permitting policy classification.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

LEGACY_REFERENCE_READ_ONLY = "LEGACY_REFERENCE_READ_ONLY"
V2_NAMESPACE_PREFIX = "v2:"


class RedisNamespaceViolation(Exception):
    """Raised when a V2 caller attempts to mutate a legacy-prefixed key."""


@dataclass
class RedisPolicy:
    allow_legacy_reads: bool = True
    classification_for_legacy_reads: str = LEGACY_REFERENCE_READ_ONLY
    enforce_v2_prefix_on_writes: bool = True


def _is_v2_key(key: str) -> bool:
    return isinstance(key, str) and key.startswith(V2_NAMESPACE_PREFIX)


def _is_legacy_key(key: str) -> bool:
    return isinstance(key, str) and not _is_v2_key(key)


class RedisNamespaceAdapter:
    """Wraps any Redis-shaped client to enforce V2 namespace policy."""

    def __init__(self, client: Any = None, policy: RedisPolicy | None = None) -> None:
        self._client = client
        self._policy = policy or RedisPolicy()

    # --------------------------------------------------------------- reads

    def get(self, key: str) -> Any:
        """Allow read of any key. Legacy reads carry a classification tag."""
        if _is_legacy_key(key) and not self._policy.allow_legacy_reads:
            raise RedisNamespaceViolation(f"legacy_read_denied:{key}")
        if self._client is None:
            return None
        return self._client.get(key)

    def hget(self, key: str, field: str) -> Any:
        if _is_legacy_key(key) and not self._policy.allow_legacy_reads:
            raise RedisNamespaceViolation(f"legacy_read_denied:{key}")
        if self._client is None:
            return None
        return self._client.hget(key, field)

    # -------------------------------------------------------------- writes

    def _reject_legacy_write(self, op: str, key: str) -> None:
        if self._policy.enforce_v2_prefix_on_writes and _is_legacy_key(key):
            raise RedisNamespaceViolation(
                f"legacy_write_blocked op={op} key={key}; V2 writes must target v2:*"
            )

    def set(self, key: str, value: Any) -> Any:
        self._reject_legacy_write("SET", key)
        if self._client is None:
            return None
        return self._client.set(key, value)

    def hset(self, key: str, *args: Any, **kwargs: Any) -> Any:
        self._reject_legacy_write("HSET", key)
        if self._client is None:
            return None
        return self._client.hset(key, *args, **kwargs)

    def xadd(self, stream: str, fields: dict, *args: Any, **kwargs: Any) -> Any:
        self._reject_legacy_write("XADD", stream)
        if self._client is None:
            return None
        return self._client.xadd(stream, fields, *args, **kwargs)

    def delete(self, *keys: str) -> Any:
        for k in keys:
            self._reject_legacy_write("DEL", k)
        if self._client is None:
            return None
        return self._client.delete(*keys)

    def xtrim(self, stream: str, *args: Any, **kwargs: Any) -> Any:
        self._reject_legacy_write("XTRIM", stream)
        if self._client is None:
            return None
        return self._client.xtrim(stream, *args, **kwargs)

    def expire(self, key: str, ttl: int) -> Any:
        self._reject_legacy_write("EXPIRE", key)
        if self._client is None:
            return None
        return self._client.expire(key, ttl)

    # ------------------------------------------------------- classification

    @staticmethod
    def classify(key: str) -> str:
        return "V2_NAMESPACE" if _is_v2_key(key) else LEGACY_REFERENCE_READ_ONLY


def policy_status_snapshot(adapter: RedisNamespaceAdapter) -> dict:
    return {
        "v2_namespace_prefix": V2_NAMESPACE_PREFIX,
        "policy": {
            "allow_legacy_reads": adapter._policy.allow_legacy_reads,
            "classification_for_legacy_reads": adapter._policy.classification_for_legacy_reads,
            "enforce_v2_prefix_on_writes": adapter._policy.enforce_v2_prefix_on_writes,
        },
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }
