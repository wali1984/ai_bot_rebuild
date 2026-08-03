from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping


COINGLASS_HEALTH_KEY = "v2:provider:coinglass:health"
COINGLASS_FEATURES = (
    "funding",
    "open_interest",
    "long_short",
    "liquidations",
    "market_snapshots",
    "trades",
    "orderbook_if_plan_allows",
)
KEY_NAMES = ("COINGLASS_API_KEY", "COINGLASS_SECRET", "COINGLASS_PRO_API_KEY")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _has_key(env: Mapping[str, str | None]) -> bool:
    return any(bool(str(env.get(name) or "").strip()) for name in KEY_NAMES)


def build_coinglass_health(
    env: Mapping[str, str | None],
    *,
    last_http_status: int | None = None,
    last_error: str | None = None,
) -> dict[str, object]:
    configured = _has_key(env)
    if not configured:
        status = "NOT_CONFIGURED"
    elif last_http_status in {401, 402, 403}:
        status = "CONFIGURED_BUT_UNSUBSCRIBED_OR_FORBIDDEN"
    elif last_http_status is not None and 200 <= last_http_status < 300:
        status = "READY"
    else:
        status = "CONFIGURED_PENDING_SUBSCRIPTION_VALIDATION"

    return {
        "schema_version": "v2_coinglass_provider_health_v1",
        "redis_key": COINGLASS_HEALTH_KEY,
        "generated_utc": _utc_now(),
        "provider": "coinglass",
        "status": status,
        "configured": configured,
        "raw_key_exposed": False,
        "invalid_subscription_blocks_core_system": False,
        "provider_shown_green_when_forbidden": False,
        "features": list(COINGLASS_FEATURES),
        "last_http_status": last_http_status,
        "last_error_class": None if last_error is None else str(last_error).split(":", 1)[0][:80],
        "paper_only": True,
        "places_real_order": False,
    }
