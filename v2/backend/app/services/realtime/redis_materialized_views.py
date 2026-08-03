"""Read-only access to UI materialized views in Redis."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .resource_registry import resource_key


def _json_object(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def read_materialized_view(client: Any, resource: str) -> tuple[dict[str, Any] | None, str | None]:
    key = resource_key(resource)
    if client is None or key is None:
        return None, key
    try:
        payload = _json_object(client.get(key))
    except Exception:
        return None, key
    return payload, key


def payload_age_seconds(payload: dict[str, Any] | None) -> float | None:
    if not payload:
        return None
    raw = payload.get("generated_utc") or payload.get("generated_at") or payload.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return round(max(0.0, (datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds()), 3)
