"""Small Redis-backed JSON usage ledger for provider budgets."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


class JsonUsageLedger:
    def __init__(self, redis_client: Any, *, prefix: str) -> None:
        if not prefix.startswith("v2:provider:"):
            raise ValueError("provider ledger prefix must be v2:provider:*")
        self.redis = redis_client
        self.prefix = prefix.rstrip(":")

    def day_key(self, provider: str, day: str | None = None) -> str:
        return f"{self.prefix}:{provider}:usage:{day or _utc_day()}"

    def read(self, provider: str, day: str | None = None) -> dict[str, Any]:
        if self.redis is None:
            return {}
        try:
            raw = self.redis.get(self.day_key(provider, day))
        except Exception:
            return {}
        if not raw:
            return {}
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            payload = json.loads(str(raw))
        except (TypeError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def write(self, provider: str, payload: dict[str, Any], *, ttl_seconds: int = 172800) -> bool:
        if self.redis is None:
            return False
        key = self.day_key(provider)
        safe_payload = {
            **payload,
            "provider": provider,
            "raw_key_exposed": False,
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        try:
            self.redis.set(key, json.dumps(safe_payload, sort_keys=True, default=str), ex=ttl_seconds)
            return True
        except Exception:
            return False


def _utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
