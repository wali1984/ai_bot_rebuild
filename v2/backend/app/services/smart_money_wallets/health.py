from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping


MORALIS_HEALTH_KEY = "v2:provider:moralis:health"
MORALIS_FEATURES = (
    "wallet_history",
    "wallet_transactions",
    "wallet_networth",
    "wallet_token_balances_price",
    "wallet_address_transfers",
    "wallet_swaps",
    "token_holders",
    "token_metadata",
    "token_address_transfers",
    "token_swaps",
    "token_price",
    "multiple_token_prices",
    "streams",
    "smart_wallet_candidate_scoring",
)
KEY_NAMES = ("MORALIS_API_KEY", "MORALIS_WEB3_API_KEY")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _has_key(env: Mapping[str, str | None]) -> bool:
    return any(bool(str(env.get(name) or "").strip()) for name in KEY_NAMES)


def build_moralis_health(
    env: Mapping[str, str | None],
    *,
    last_http_status: int | None = None,
    last_error: str | None = None,
    token_map_count: int = 0,
    wallet_watchlist_count: int = 0,
    smart_wallet_candidate_count: int = 0,
    stream_configured: bool = False,
    actual_payload_count_1h: int = 0,
) -> dict[str, object]:
    configured = _has_key(env)
    if not configured:
        status = "NOT_CONFIGURED"
    elif actual_payload_count_1h > 0:
        status = "READY"
    elif last_http_status in {401, 402, 403}:
        status = "CONFIGURED_BUT_UNSUBSCRIBED_OR_FORBIDDEN"
    elif last_http_status is not None and 200 <= last_http_status < 300:
        status = "CONFIGURED_NO_WATCHLIST" if wallet_watchlist_count <= 0 else "PAYLOADS_PENDING"
    else:
        status = "CONFIGURED_NO_WATCHLIST" if wallet_watchlist_count <= 0 else "CONFIGURED_PENDING_SUBSCRIPTION_VALIDATION"
    dashboard_color = "GREEN" if status == "READY" and actual_payload_count_1h > 0 else "GRAY"

    return {
        "schema_version": "v2_moralis_provider_health_v1",
        "redis_key": MORALIS_HEALTH_KEY,
        "generated_utc": _utc_now(),
        "provider": "moralis",
        "status": status,
        "configured": configured,
        "dashboard_color": dashboard_color,
        "token_map_count": int(token_map_count),
        "wallet_watchlist_count": int(wallet_watchlist_count),
        "smart_wallet_candidate_count": int(smart_wallet_candidate_count),
        "stream_configured": bool(stream_configured),
        "actual_payload_count_5m": int(actual_payload_count_1h),
        "actual_payload_count_1h": int(actual_payload_count_1h),
        "moralis_is_curated_smart_money": False,
        "configured_no_watchlist_is_green": False,
        "raw_key_exposed": False,
        "core_system_blocked": False,
        "invalid_subscription_blocks_core_system": False,
        "provider_shown_green_when_forbidden": False,
        "features": list(MORALIS_FEATURES),
        "last_http_status": last_http_status,
        "last_error_class": None if last_error is None else str(last_error).split(":", 1)[0][:80],
        "paper_only": True,
        "places_real_order": False,
    }
