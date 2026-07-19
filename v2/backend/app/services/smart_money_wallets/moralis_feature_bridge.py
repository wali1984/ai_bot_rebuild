"""Moralis smart-money feature payload builder."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

MORALIS_FEATURE_KEY = "v2:features:moralis:{symbol}:{timeframe}"
MORALIS_PROVIDER_FEATURE_KEY = "v2:features:provider:moralis:{symbol}:{timeframe}"
SMART_MONEY_SIGNAL_KEY = "v2:smart_money:signals:{symbol}"
MORALIS_FEATURE_BRIDGE_STATUS_KEY = "v2:provider:moralis:feature_bridge_status"
MORALIS_SYMBOL_SCORE_KEY = "v2:provider:moralis:symbol_score:{symbol}"

FEATURE_NAMES = (
    "moralis_whale_buy_usd",
    "moralis_whale_sell_usd",
    "moralis_whale_net_flow_usd",
    "moralis_exchange_inflow_usd",
    "moralis_exchange_outflow_usd",
    "moralis_net_exchange_flow_usd",
    "moralis_dex_buy_pressure_usd",
    "moralis_dex_sell_pressure_usd",
    "moralis_dex_flow_imbalance_usd",
    "moralis_smart_wallet_accumulation_score",
    "moralis_smart_wallet_distribution_score",
    "moralis_top_holder_concentration",
    "moralis_holder_count",
    "moralis_holder_delta",
    "moralis_onchain_risk_score",
)
REQUIRED_MORALIS_FEATURES = FEATURE_NAMES

FEATURE_ALIASES = {
    "moralis_holder_concentration_change": "moralis_top_holder_concentration",
    "moralis_token_holder_delta": "moralis_holder_delta",
}


def build_moralis_feature_payload(
    *,
    symbol: str,
    timeframe: str = "1m",
    features: Mapping[str, Any] | None = None,
    token_map_count: int = 0,
    wallet_watchlist_count: int = 0,
    actual_payload_present: bool = False,
    event_time: str | None = None,
    feature_cutoff: str | None = None,
    available_at: str | None = None,
    ttl_seconds: int = 3600,
    stale_after: int | None = None,
    compute_unit_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ttl = max(1, int(ttl_seconds))
    stale = max(1, int(stale_after or ttl))
    numeric = _numeric_subset(features or {})
    missing = [name for name in FEATURE_NAMES if name not in numeric]
    stale_flags: list[str] = []
    # ``generated_at`` is the completion time of this feature computation. It
    # must not be copied from a source observation or an earlier aggregate.
    generated_at = _now()
    publication_observed_at = _now()
    availability_input = publication_observed_at if available_at is None else available_at
    temporal = _validate_temporal_contract(
        event_time=event_time,
        feature_cutoff=feature_cutoff,
        generated_at=generated_at,
        available_at=availability_input,
        publication_observed_at=publication_observed_at,
        require_source_clocks=bool(actual_payload_present and numeric),
    )
    temporal_valid = not temporal["rejection_reasons"]
    has_lists = token_map_count > 0 and wallet_watchlist_count > 0
    has_actual = bool(actual_payload_present and numeric and temporal_valid)
    feature_bridge_ready = bool(has_lists and has_actual and not missing and not stale_flags)
    status = _status(
        has_lists=has_lists,
        has_actual=has_actual,
        temporal_rejected=bool(actual_payload_present and numeric and not temporal_valid),
        missing=missing,
        stale_flags=stale_flags,
        token_map_count=token_map_count,
        wallet_watchlist_count=wallet_watchlist_count,
    )
    return {
        "schema_version": "moralis_feature_bridge_v1",
        "provider": "moralis",
        "symbol": str(symbol).upper(),
        "timeframe": timeframe,
        "generated_at": temporal["generated_at"],
        "event_time": temporal["event_time"],
        "available_at": temporal["available_at"],
        "feature_cutoff": temporal["feature_cutoff"],
        "decision_time_safe": temporal_valid,
        "temporal_contract_version": "moralis_feature_temporal_contract_v2",
        "temporal_contract_valid": temporal_valid,
        "temporal_rejection_reasons": temporal["rejection_reasons"],
        "source_clock_inputs": {
            "event_time_input": event_time,
            "feature_cutoff_input": feature_cutoff,
            "available_at_input": available_at,
        },
        "ttl_seconds": ttl,
        "stale_after": stale,
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=ttl)).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "features": numeric if has_actual else {},
        "feature_names": list(FEATURE_NAMES),
        "required_feature_count": len(FEATURE_NAMES),
        "feature_count": len(numeric) if has_actual else 0,
        "missing_feature_flags": missing,
        "stale_feature_flags": stale_flags,
        "missing_mask": {name: name in missing for name in FEATURE_NAMES},
        "missing_mask_true": bool(missing),
        "stale_mask": {name: name in stale_flags for name in FEATURE_NAMES},
        "stale_mask_true": bool(stale_flags),
        "token_map_count": int(token_map_count),
        "wallet_watchlist_count": int(wallet_watchlist_count),
        "source_actual_payload_present": bool(actual_payload_present and numeric),
        "actual_payload_present": has_actual,
        "heartbeat_only": not has_actual,
        "provider_ready": feature_bridge_ready,
        "feature_bridge_ready": feature_bridge_ready,
        "dashboard_color": "GREEN" if feature_bridge_ready else ("YELLOW" if has_actual else "GRAY"),
        "status": status,
        "compute_unit_status": dict(compute_unit_status or {}),
        "daily_cu_used": _dig(compute_unit_status or {}, "compute_budget", "used_today"),
        "monthly_cu_used": _dig(compute_unit_status or {}, "compute_budget", "used_month"),
        "moralis_can_approve_trade_alone": False,
        "can_boost_confidence_modestly": feature_bridge_ready,
        "can_block_reduce_size_or_require_hedge": has_actual,
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
    feature_cutoff: str | None = None,
    available_at: str | None = None,
    ttl_seconds: int = 3600,
    stale_after: int | None = None,
    compute_unit_status: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = build_moralis_feature_payload(
        symbol=symbol,
        timeframe=timeframe,
        features=features,
        token_map_count=token_map_count,
        wallet_watchlist_count=wallet_watchlist_count,
        actual_payload_present=actual_payload_present,
        event_time=event_time,
        feature_cutoff=feature_cutoff,
        available_at=available_at,
        ttl_seconds=ttl_seconds,
        stale_after=stale_after,
        compute_unit_status=compute_unit_status,
    )
    symbol_upper = str(symbol).upper()
    feature_key = MORALIS_FEATURE_KEY.format(symbol=symbol_upper, timeframe=timeframe)
    provider_feature_key = MORALIS_PROVIDER_FEATURE_KEY.format(symbol=symbol_upper, timeframe=timeframe)
    signal_key = SMART_MONEY_SIGNAL_KEY.format(symbol=symbol_upper)
    score_key = MORALIS_SYMBOL_SCORE_KEY.format(symbol=symbol_upper)
    bridge_status = _feature_bridge_status(payload)
    symbol_score = _symbol_score_payload(payload)
    for key, value, ttl in (
        (feature_key, payload, ttl_seconds),
        (provider_feature_key, payload, ttl_seconds),
        (signal_key, payload, max(900, min(int(ttl_seconds), 21600))),
        (MORALIS_FEATURE_BRIDGE_STATUS_KEY, bridge_status, 3600),
        (score_key, symbol_score, ttl_seconds),
    ):
        redis_client.set(key, json.dumps(value, sort_keys=True, default=str), ex=max(1, int(ttl)))
    payload["keys_written"] = [
        feature_key,
        provider_feature_key,
        signal_key,
        MORALIS_FEATURE_BRIDGE_STATUS_KEY,
        score_key,
    ]
    return payload


def _numeric_subset(values: Mapping[str, Any]) -> dict[str, float]:
    canonical_values: dict[str, Any] = {}
    for name, value in values.items():
        canonical_values[FEATURE_ALIASES.get(str(name), str(name))] = value
    out: dict[str, float] = {}
    for name in FEATURE_NAMES:
        value = canonical_values.get(name)
        try:
            if value in (None, ""):
                continue
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed == parsed and abs(parsed) != float("inf"):
            out[name] = parsed
    return out


def _status(
    *,
    has_lists: bool,
    has_actual: bool,
    temporal_rejected: bool,
    missing: list[str],
    stale_flags: list[str],
    token_map_count: int,
    wallet_watchlist_count: int,
) -> str:
    if temporal_rejected:
        return "TEMPORAL_CONTRACT_REJECTED"
    if wallet_watchlist_count <= 0:
        return "CONFIGURED_NO_WATCHLIST"
    if token_map_count <= 0:
        return "CONFIGURED_NO_TOKEN_MAP"
    if not has_lists:
        return "CONFIGURED_INCOMPLETE_BOOTSTRAP"
    if not has_actual:
        return "PAYLOADS_PENDING"
    if stale_flags:
        return "PARTIAL_REQUIRED_FEATURES_STALE"
    if missing:
        return "PARTIAL_REQUIRED_FEATURES_MISSING"
    return "READY"


def _feature_bridge_status(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "moralis_feature_bridge_status_v1",
        "provider": "moralis",
        "generated_utc": payload.get("generated_at"),
        "symbol": payload.get("symbol"),
        "timeframe": payload.get("timeframe"),
        "available_at": payload.get("available_at"),
        "feature_cutoff": payload.get("feature_cutoff"),
        "decision_time_safe": payload.get("decision_time_safe"),
        "temporal_contract_version": payload.get("temporal_contract_version"),
        "temporal_contract_valid": payload.get("temporal_contract_valid"),
        "temporal_rejection_reasons": payload.get("temporal_rejection_reasons"),
        "ttl_seconds": payload.get("ttl_seconds"),
        "stale_after": payload.get("stale_after"),
        "status": payload.get("status"),
        "dashboard_color": payload.get("dashboard_color"),
        "feature_bridge_ready": payload.get("feature_bridge_ready"),
        "feature_count": payload.get("feature_count"),
        "required_feature_count": payload.get("required_feature_count"),
        "missing_feature_flags": payload.get("missing_feature_flags"),
        "stale_feature_flags": payload.get("stale_feature_flags"),
        "missing_mask": payload.get("missing_mask"),
        "missing_mask_true": payload.get("missing_mask_true"),
        "stale_mask": payload.get("stale_mask"),
        "stale_mask_true": payload.get("stale_mask_true"),
        "token_map_count": payload.get("token_map_count"),
        "wallet_watchlist_count": payload.get("wallet_watchlist_count"),
        "actual_payload_present": payload.get("actual_payload_present"),
        "heartbeat_only": payload.get("heartbeat_only"),
        "heartbeat_only_green_allowed": False,
        "trainer_consumption": True,
        "provider_tensor_consumption": True,
        "ppo_consumption": True,
        "masa_consumption": True,
        "risk_consumption": True,
        "orchestrator_consumption": True,
        "allocator_consumption": True,
        "paper_consumption": True,
        "live_dryrun_consumption": True,
        "feedback_attribution": True,
        "single_provider_can_approve": False,
        "provider_data_can_approve_trade_alone": False,
        "core_system_blocked": False,
        "raw_key_exposed": False,
    }


def _symbol_score_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    features = payload.get("features") if isinstance(payload.get("features"), Mapping) else {}
    score = 0.0
    if payload.get("feature_bridge_ready") is True and features:
        score = max(
            -1.0,
            min(
                1.0,
                float(features.get("moralis_whale_net_flow_usd") or 0.0) / 1_000_000.0
                + float(features.get("moralis_dex_flow_imbalance_usd") or 0.0) / 1_000_000.0
                - float(features.get("moralis_onchain_risk_score") or 0.0),
            ),
        )
    return {
        "schema_version": "moralis_symbol_score_v1",
        "provider": "moralis",
        "symbol": payload.get("symbol"),
        "timeframe": payload.get("timeframe"),
        "generated_utc": payload.get("generated_at"),
        "score": round(score, 8),
        "feature_bridge_ready": payload.get("feature_bridge_ready"),
        "status": payload.get("status"),
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }


def _validate_temporal_contract(
    *,
    event_time: str | None,
    feature_cutoff: str | None,
    generated_at: str,
    available_at: str,
    publication_observed_at: str,
    require_source_clocks: bool,
) -> dict[str, Any]:
    inputs = {
        "event_time": event_time,
        "feature_cutoff": feature_cutoff,
        "generated_at": generated_at,
        "available_at": available_at,
        "publication_observed_at": publication_observed_at,
    }
    parsed: dict[str, datetime] = {}
    reasons: list[str] = []
    for name, value in inputs.items():
        if value in (None, ""):
            if name in {"generated_at", "available_at", "publication_observed_at"} or (
                require_source_clocks and name in {"event_time", "feature_cutoff"}
            ):
                reasons.append(f"{name.upper()}_MISSING")
            continue
        clock = _parse_utc(value)
        if clock is None:
            reasons.append(f"{name.upper()}_NOT_STRICT_UTC")
            continue
        parsed[name] = clock

    _reject_inversion(
        parsed,
        earlier="event_time",
        later="feature_cutoff",
        reason="EVENT_TIME_AFTER_FEATURE_CUTOFF",
        reasons=reasons,
    )
    _reject_inversion(
        parsed,
        earlier="feature_cutoff",
        later="generated_at",
        reason="FEATURE_CUTOFF_AFTER_GENERATED_AT",
        reasons=reasons,
    )
    _reject_inversion(
        parsed,
        earlier="generated_at",
        later="available_at",
        reason="GENERATED_AT_AFTER_AVAILABLE_AT",
        reasons=reasons,
    )
    _reject_inversion(
        parsed,
        earlier="available_at",
        later="publication_observed_at",
        reason="AVAILABLE_AT_AFTER_PUBLICATION_OBSERVED_AT",
        reasons=reasons,
    )
    if "event_time" in parsed and "generated_at" in parsed:
        if parsed["event_time"] > parsed["generated_at"]:
            reasons.append("EVENT_TIME_AFTER_GENERATED_AT")

    valid = not reasons
    return {
        # Rejected source/publication clocks remain available in
        # ``source_clock_inputs`` but never occupy trusted clock fields.
        "event_time": _iso_utc(parsed.get("event_time")) if valid else None,
        "feature_cutoff": _iso_utc(parsed.get("feature_cutoff")) if valid else None,
        "generated_at": _iso_utc(parsed.get("generated_at")),
        "available_at": _iso_utc(parsed.get("available_at")) if valid else None,
        "rejection_reasons": sorted(set(reasons)),
    }


def _reject_inversion(
    parsed: Mapping[str, datetime],
    *,
    earlier: str,
    later: str,
    reason: str,
    reasons: list[str],
) -> None:
    if earlier in parsed and later in parsed and parsed[earlier] > parsed[later]:
        reasons.append(reason)


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _dig(mapping: Mapping[str, Any], *path: str) -> Any:
    cur: Any = mapping
    for item in path:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(item)
    return cur


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
