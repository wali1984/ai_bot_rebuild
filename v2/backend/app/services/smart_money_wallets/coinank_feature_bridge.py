"""CoinAnk liquidation data to feature bridge mapper."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


COINANK_FEATURE_KEY = "v2:features:coinank:{symbol}:{timeframe}"
COINANK_LIQUIDATION_KEY = "v2:liquidations:levels:{symbol}"
COINANK_STATUS_KEY = "v2:provider:coinank:feature_bridge_status"


def build_coinank_feature_payload(
    *,
    symbol: str,
    timeframe: str = "1m",
    liquidation_levels: Mapping[str, Any] | None = None,
    funding_data: Mapping[str, Any] | None = None,
    ttl_seconds: int = 3600,
) -> dict[str, Any]:
    """Build CoinAnk liquidation features from liquidation levels data."""
    generated_at = _now()

    levels = liquidation_levels or {}
    funding = funding_data or {}

    # Extract liquidation features
    liq_long = float(levels.get("liquidation_long_total_usd") or 0.0)
    liq_short = float(levels.get("liquidation_short_total_usd") or 0.0)
    liq_long_count = int(levels.get("liquidation_long_count") or 0)
    liq_short_count = int(levels.get("liquidation_short_count") or 0)

    # Extract funding features
    funding_rate = float(funding.get("funding_rate") or 0.0)
    funding_rate_long = float(funding.get("funding_rate_long") or funding_rate)
    funding_rate_short = float(funding.get("funding_rate_short") or funding_rate)

    features = {
        "coinank_liquidation_long_usd": liq_long,
        "coinank_liquidation_short_usd": liq_short,
        "coinank_liquidation_net_imbalance_usd": liq_long - liq_short,
        "coinank_liquidation_long_count": float(liq_long_count),
        "coinank_liquidation_short_count": float(liq_short_count),
        "coinank_liquidation_total_count": float(liq_long_count + liq_short_count),
        "coinank_funding_rate_long": funding_rate_long,
        "coinank_funding_rate_short": funding_rate_short,
        "coinank_funding_rate_net": funding_rate_long - funding_rate_short,
    }

    has_data = bool(liq_long or liq_short or liq_long_count or liq_short_count)

    return {
        "schema_version": "coinank_feature_bridge_v1",
        "provider": "coinank",
        "symbol": str(symbol).upper(),
        "timeframe": timeframe,
        "generated_at": generated_at,
        "ttl_seconds": max(1, int(ttl_seconds)),
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "features": features,
        "feature_names": list(features.keys()),
        "feature_count": len(features),
        "actual_payload_present": has_data,
        "heartbeat_only": not has_data,
        "provider_ready": has_data,
        "feature_bridge_ready": has_data,
        "dashboard_color": "GREEN" if has_data else "GRAY",
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }


def publish_coinank_feature_payload(
    redis_client: Any,
    *,
    symbol: str,
    timeframe: str = "1m",
    liquidation_levels: Mapping[str, Any] | None = None,
    funding_data: Mapping[str, Any] | None = None,
    ttl_seconds: int = 3600,
) -> dict[str, Any]:
    """Publish CoinAnk features to Redis."""
    payload = build_coinank_feature_payload(
        symbol=symbol,
        timeframe=timeframe,
        liquidation_levels=liquidation_levels,
        funding_data=funding_data,
        ttl_seconds=ttl_seconds,
    )

    symbol_upper = str(symbol).upper()
    feature_key = COINANK_FEATURE_KEY.format(symbol=symbol_upper, timeframe=timeframe)

    redis_client.set(
        feature_key,
        json.dumps(payload, sort_keys=True, default=str),
        ex=max(1, int(ttl_seconds))
    )

    payload["keys_written"] = [feature_key]
    return payload


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
