"""Read provider feature payloads from Redis with freshness and PIT checks."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from .contracts import (
    COINGLASS_CANONICAL_FEATURE_MAP,
    COINGLASS_REDIS_KEY_CONTRACT,
    CONSUMER_ROLES,
    MORALIS_CANONICAL_FEATURE_MAP,
    MORALIS_REDIS_KEY_CONTRACT,
    endpoint_to_feature_mapping,
    provider_redis_key_contract,
)


@dataclass(frozen=True)
class ProviderFeatureSnapshot:
    provider: str
    symbol: str
    timeframe: str
    source_key: str
    status: str
    dashboard_color: str
    actual_payload_present: bool
    heartbeat_only: bool
    stale: bool
    excluded_from_features: bool
    exclusion_reasons: tuple[str, ...]
    ttl_remaining_seconds: int | None
    ttl_contract_valid: bool
    event_time: str | None
    available_at: str | None
    feature_cutoff: str | None
    generated_at: str | None
    endpoint_id: str | None
    feature_count: int
    features: dict[str, float]

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


class ProviderFeatureBridge:
    """Read provider features and produce non-blocking consumer contexts."""

    def __init__(self, redis_client: Any | None) -> None:
        self.redis_client = redis_client

    def read_symbol_features(
        self,
        *,
        symbol: str,
        timeframe: str = "1m",
        decision_time: str | int | float | datetime | None = None,
        required_providers: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        normalized_symbol = str(symbol).upper()
        rows = (
            self._read_provider(
                provider="coinglass",
                key=COINGLASS_REDIS_KEY_CONTRACT["features"].format(
                    symbol=normalized_symbol,
                    timeframe=timeframe,
                ),
                symbol=normalized_symbol,
                timeframe=timeframe,
                canonical_map=COINGLASS_CANONICAL_FEATURE_MAP,
                decision_time=decision_time,
            ),
            self._read_provider(
                provider="moralis",
                key=MORALIS_REDIS_KEY_CONTRACT["features"].format(
                    symbol=normalized_symbol,
                    timeframe=timeframe,
                ),
                symbol=normalized_symbol,
                timeframe=timeframe,
                canonical_map=MORALIS_CANONICAL_FEATURE_MAP,
                decision_time=decision_time,
            ),
        )
        merged_features: dict[str, float] = {}
        provider_payloads: dict[str, dict[str, Any]] = {}
        violations: list[str] = []
        missing_optional: list[str] = []
        core_blocking = False
        for row in rows:
            provider_payloads[row.provider] = row.to_payload()
            violations.extend(row.exclusion_reasons)
            if row.provider in required_providers and row.excluded_from_features:
                core_blocking = True
            elif row.excluded_from_features:
                missing_optional.append(row.provider)
            if row.excluded_from_features:
                continue
            for name, value in row.features.items():
                merged_features.setdefault(name, value)
        return {
            "schema_version": "provider_feature_context_v1",
            "symbol": normalized_symbol,
            "timeframe": timeframe,
            "decision_time": _iso_or_none(decision_time),
            "provider_features": merged_features,
            "provider_payloads": provider_payloads,
            "payloads_for_tensor": _payloads_for_tensor(merged_features),
            "feature_count": len(merged_features),
            "actual_provider_count": sum(
                1 for row in rows if row.actual_payload_present and not row.excluded_from_features
            ),
            "optional_provider_failures": sorted(set(missing_optional)),
            "required_providers": list(required_providers),
            "core_system_blocked": bool(core_blocking),
            "point_in_time_violations": [
                reason for reason in violations if "future_leak" in reason
            ],
            "ttl_contract_violations": [
                reason for reason in violations if "ttl_contract" in reason
            ],
            "heartbeat_only_green_allowed": False,
            "raw_key_exposed": False,
        }

    def actual_data_panel(
        self,
        *,
        symbol: str = "BTCUSDT",
        timeframe: str = "1m",
    ) -> dict[str, Any]:
        context = self.read_symbol_features(symbol=symbol, timeframe=timeframe)
        health = {
            "coinglass": self._read_json(COINGLASS_REDIS_KEY_CONTRACT["health"]),
            "moralis": self._read_json(MORALIS_REDIS_KEY_CONTRACT["health"]),
        }
        usage = {
            "coinglass": self._read_json(COINGLASS_REDIS_KEY_CONTRACT["usage"]),
            "moralis": self._read_json(MORALIS_REDIS_KEY_CONTRACT["usage"]),
        }
        endpoint_status = {
            "coinglass": self._read_json(COINGLASS_REDIS_KEY_CONTRACT["endpoint_status"]),
            "moralis": self._read_json(MORALIS_REDIS_KEY_CONTRACT["endpoint_status"]),
        }
        panels = {}
        for provider, row in context["provider_payloads"].items():
            panels[provider] = {
                "status": row["status"],
                "dashboard_color": row["dashboard_color"],
                "actual_payload_present": row["actual_payload_present"],
                "heartbeat_only": row["heartbeat_only"],
                "stale": row["stale"],
                "feature_count": row["feature_count"],
                "ttl_remaining_seconds": row["ttl_remaining_seconds"],
                "ttl_contract_valid": row["ttl_contract_valid"],
                "source_key": row["source_key"],
                "raw_key_exposed": False,
            }
        return {
            "schema_version": "provider_actual_data_panel_v1",
            "symbol": str(symbol).upper(),
            "timeframe": timeframe,
            "status": "PROVIDER_ACTUAL_DATA_PANEL_ACTIVE",
            "coinglass": panels.get("coinglass", {}),
            "moralis": panels.get("moralis", {}),
            "health": health,
            "usage": usage,
            "endpoint_status": endpoint_status,
            "redis_key_contract": provider_redis_key_contract(),
            "endpoint_to_feature_mapping": endpoint_to_feature_mapping(),
            "actual_provider_count": context["actual_provider_count"],
            "optional_provider_failures_core_blocking": False,
            "heartbeat_only_green_allowed": False,
            "raw_key_exposed": False,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }

    def _read_provider(
        self,
        *,
        provider: str,
        key: str,
        symbol: str,
        timeframe: str,
        canonical_map: Mapping[str, str],
        decision_time: str | int | float | datetime | None,
    ) -> ProviderFeatureSnapshot:
        payload = self._read_json(key)
        ttl = self._ttl(key)
        if not isinstance(payload, Mapping):
            return ProviderFeatureSnapshot(
                provider=provider,
                symbol=symbol,
                timeframe=timeframe,
                source_key=key,
                status="MISSING",
                dashboard_color="GRAY",
                actual_payload_present=False,
                heartbeat_only=True,
                stale=True,
                excluded_from_features=True,
                exclusion_reasons=(f"{provider}:missing_payload",),
                ttl_remaining_seconds=ttl,
                ttl_contract_valid=ttl is None or ttl > 0,
                event_time=None,
                available_at=None,
                feature_cutoff=None,
                generated_at=None,
                endpoint_id=None,
                feature_count=0,
                features={},
            )
        raw_features = payload.get("features") if isinstance(payload.get("features"), Mapping) else {}
        actual = bool(payload.get("actual_payload_present")) and bool(raw_features) and not bool(payload.get("heartbeat_only"))
        status = str(payload.get("subscription_status") or payload.get("status") or ("READY" if actual else "UNAVAILABLE"))
        available_at = _first_str(payload, "available_at", "generated_at", "generated_utc")
        feature_cutoff = _first_str(payload, "feature_cutoff", "event_time", "available_at")
        generated_at = _first_str(payload, "generated_at", "generated_utc")
        excluded: list[str] = []
        ttl_valid = ttl is None or ttl > 0
        if ttl == -1:
            ttl_valid = False
            excluded.append(f"{provider}:ttl_contract_violation:no_expiry:{key}")
        if not actual:
            excluded.append(f"{provider}:heartbeat_only_or_empty_payload")
        parsed_decision = _parse_time(decision_time)
        parsed_available = _parse_time(available_at)
        parsed_cutoff = _parse_time(feature_cutoff)
        if parsed_decision is not None:
            if parsed_available is not None and parsed_available > parsed_decision:
                excluded.append(f"{provider}:future_leak_available_at_after_decision_time")
            if parsed_cutoff is not None and parsed_cutoff > parsed_decision:
                excluded.append(f"{provider}:future_leak_feature_cutoff_after_decision_time")
        stale = bool(payload.get("stale") or payload.get("is_stale"))
        if status in {"RATE_LIMITED", "DEGRADED"}:
            stale = True
        features = _canonicalize_features(raw_features, canonical_map) if not excluded else {}
        color = _dashboard_color(
            enabled=True,
            status=status,
            actual=actual and not excluded,
            stale=stale or bool(excluded),
        )
        return ProviderFeatureSnapshot(
            provider=provider,
            symbol=symbol,
            timeframe=timeframe,
            source_key=key,
            status=status,
            dashboard_color=color,
            actual_payload_present=actual,
            heartbeat_only=not actual,
            stale=stale,
            excluded_from_features=bool(excluded),
            exclusion_reasons=tuple(excluded),
            ttl_remaining_seconds=ttl,
            ttl_contract_valid=ttl_valid,
            event_time=_first_str(payload, "event_time"),
            available_at=available_at,
            feature_cutoff=feature_cutoff,
            generated_at=generated_at,
            endpoint_id=None if payload.get("endpoint_id") is None else str(payload.get("endpoint_id")),
            feature_count=len(features),
            features=features,
        )

    def _read_json(self, key: str) -> dict[str, Any] | None:
        if self.redis_client is None:
            return None
        try:
            raw = self.redis_client.get(key)
        except Exception:
            return None
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        try:
            payload = json.loads(str(raw))
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _ttl(self, key: str) -> int | None:
        if self.redis_client is None or not hasattr(self.redis_client, "ttl"):
            return None
        try:
            return int(self.redis_client.ttl(key))
        except Exception:
            return None


def build_provider_consumer_context(
    redis_client: Any | None,
    *,
    role: str,
    symbol: str,
    timeframe: str = "1m",
    decision_time: str | int | float | datetime | None = None,
    required_providers: tuple[str, ...] = (),
) -> dict[str, Any]:
    normalized_role = str(role).strip().lower()
    if normalized_role not in CONSUMER_ROLES:
        normalized_role = "unknown"
    context = ProviderFeatureBridge(redis_client).read_symbol_features(
        symbol=symbol,
        timeframe=timeframe,
        decision_time=decision_time,
        required_providers=required_providers,
    )
    return {
        "schema_version": "provider_consumer_context_v1",
        "consumer_role": normalized_role,
        **context,
        "optional_provider_failures_core_blocking": False,
        "live_ready_from_probation_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
    }


def build_provider_actual_data_panel(
    redis_client: Any | None,
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "1m",
) -> dict[str, Any]:
    return ProviderFeatureBridge(redis_client).actual_data_panel(
        symbol=symbol,
        timeframe=timeframe,
    )


def _canonicalize_features(
    raw_features: Mapping[str, Any],
    canonical_map: Mapping[str, str],
) -> dict[str, float]:
    out: dict[str, float] = {}
    for raw_name, raw_value in raw_features.items():
        value = _float(raw_value)
        if value is None:
            continue
        name = str(raw_name)
        out[name] = value
        canonical = canonical_map.get(name)
        if canonical:
            out.setdefault(canonical, value)
    return out


def _payloads_for_tensor(features: Mapping[str, float]) -> dict[str, dict[str, float]]:
    return {
        "funding": _select(features, "funding_rate"),
        "open_interest": _select(features, "open_interest", "oi_change_pct"),
        "open_interest_hist": _select(features, "oi_change_pct"),
        "long_short": _select(
            features,
            "long_account_ratio",
            "short_account_ratio",
            "long_short_extreme_score",
        ),
        "liquidations": _select(
            features,
            "liquidation_buy_usd_1m",
            "liquidation_sell_usd_1m",
            "liquidation_imbalance_usd",
        ),
        "liquidation_levels": _select(
            features,
            "nearest_liquidation_level_above",
            "nearest_liquidation_level_below",
            "liquidation_level_distance_usd",
            "liquidation_cascade_risk",
        ),
        "orderbook": _select(features, "orderbook_depth_imbalance"),
        "microstructure": _select(
            features,
            "trade_imbalance",
            "liquidation_cascade_risk",
            "dex_flow_imbalance_usd",
        ),
        "smart_money": _select(
            features,
            "smart_money_whale_net_flow_usd",
            "smart_wallet_accumulation_score",
            "smart_money_net_exchange_flow_usd",
            "dex_flow_imbalance_usd",
            "onchain_risk_score",
        ),
    }


def _select(features: Mapping[str, float], *names: str) -> dict[str, float]:
    return {name: float(features[name]) for name in names if name in features}


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "" or isinstance(value, bool):
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or abs(parsed) == float("inf"):
        return None
    return parsed


def _dashboard_color(*, enabled: bool, status: str, actual: bool, stale: bool) -> str:
    if not enabled or status in {
        "CONFIGURED_BUT_UNAUTHORIZED_OR_UNSUBSCRIBED",
        "CONFIGURED_BUT_UNSUBSCRIBED_OR_FORBIDDEN",
        "CONFIGURED_NO_WATCHLIST",
    }:
        return "GRAY"
    if actual and status == "READY" and not stale:
        return "GREEN"
    if status in {"RATE_LIMITED", "DEGRADED"} or stale:
        return "YELLOW"
    return "GRAY"


def _first_str(payload: Mapping[str, Any], *fields: str) -> str | None:
    for field in fields:
        value = payload.get(field)
        if value not in (None, ""):
            return str(value)
    return None


def _parse_time(value: str | int | float | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw /= 1000.0
        try:
            parsed = datetime.fromtimestamp(raw, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_or_none(value: str | int | float | datetime | None) -> str | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")
