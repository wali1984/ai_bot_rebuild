"""Moralis smart-money feature payload builder."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping


MORALIS_FEATURE_KEY = "v2:features:moralis:{symbol}:{timeframe}"
SMART_MONEY_SIGNAL_KEY = "v2:smart_money:signals:{symbol}"
FEATURE_NAMES = (
    "moralis_exchange_inflow_usd",
    "moralis_exchange_outflow_usd",
    "moralis_net_exchange_flow_usd",
    "moralis_whale_buy_usd",
    "moralis_whale_sell_usd",
    "moralis_whale_net_flow_usd",
    "moralis_smart_wallet_accumulation_score",
    "moralis_smart_wallet_distribution_score",
    "moralis_holder_concentration_change",
    "moralis_token_holder_delta",
    "moralis_dex_buy_pressure_usd",
    "moralis_dex_sell_pressure_usd",
    "moralis_dex_flow_imbalance_usd",
    "moralis_onchain_risk_score",
    "moralis_contract_risk_penalty",
)


def build_moralis_feature_payload(
    *,
    symbol: str,
    timeframe: str = "1m",
    features: Mapping[str, Any] | None = None,
    token_map_count: int = 0,
    wallet_watchlist_count: int = 0,
    actual_payload_present: bool = False,
    event_time: str | None = None,
) -> dict[str, Any]:
    numeric = _numeric_subset(features or {})
    has_lists = token_map_count > 0 and wallet_watchlist_count > 0
    usable = bool(has_lists and actual_payload_present and numeric)
    missing = [name for name in FEATURE_NAMES if name not in numeric]
    return {
        "schema_version": "moralis_feature_bridge_payload_v1",
        "provider": "moralis",
        "symbol": str(symbol).upper(),
        "timeframe": timeframe,
        "generated_at": _now(),
        "event_time": event_time,
        "available_at": _now(),
        "feature_cutoff": event_time or _now(),
        "features": numeric if usable else {},
        "feature_names": list(FEATURE_NAMES),
        "missing_mask": {name: name in missing for name in FEATURE_NAMES},
        "missing_mask_true": bool(missing or not usable),
        "token_map_count": int(token_map_count),
        "wallet_watchlist_count": int(wallet_watchlist_count),
        "actual_payload_present": usable,
        "heartbeat_only": not usable,
        "provider_ready": usable,
        "dashboard_color": "GREEN" if usable else "GRAY",
        "status": "PAYLOADS_ACTIVE" if usable else "CONFIGURED_NO_WATCHLIST",
        "moralis_can_approve_trade_alone": False,
        "can_boost_confidence_modestly": usable,
        "can_block_reduce_size_or_require_hedge": True,
        "do_not_zero_fill_missing_smart_money": True,
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }


def publish_moralis_feature_payload(
    redis_client: Any,
    *,
    symbol: str,
    timeframe: str = "1m",
    features: Mapping[str, Any] | None = None,
    token_map_count: int = 0,
    wallet_watchlist_count: int = 0,
    actual_payload_present: bool = False,
    event_time: str | None = None,
    ttl_seconds: int = 3600,
) -> dict[str, Any]:
    payload = build_moralis_feature_payload(
        symbol=symbol,
        timeframe=timeframe,
        features=features,
        token_map_count=token_map_count,
        wallet_watchlist_count=wallet_watchlist_count,
        actual_payload_present=actual_payload_present,
        event_time=event_time,
    )
    feature_key = MORALIS_FEATURE_KEY.format(symbol=str(symbol).upper(), timeframe=timeframe)
    signal_key = SMART_MONEY_SIGNAL_KEY.format(symbol=str(symbol).upper())
    redis_client.set(feature_key, json.dumps(payload, sort_keys=True, default=str), ex=ttl_seconds)
    redis_client.set(signal_key, json.dumps(payload, sort_keys=True, default=str), ex=ttl_seconds)
    payload["keys_written"] = [feature_key, signal_key]
    return payload


def _numeric_subset(values: Mapping[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for name in FEATURE_NAMES:
        value = values.get(name)
        try:
            if value in (None, ""):
                continue
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed == parsed and abs(parsed) != float("inf"):
            out[name] = parsed
    return out


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
