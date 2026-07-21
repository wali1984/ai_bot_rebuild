"""Read provider feature payloads from Redis with freshness and PIT checks."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

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
    temporal_contract_valid: bool
    event_time: str | None
    ingested_at: str | None
    available_at: str | None
    feature_cutoff: str | None
    generated_at: str | None
    endpoint_id: str | None
    source_payload_sha256: str | None
    feature_count: int
    features: dict[str, float]

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class _TemporalEnvelope:
    event_time: str | None
    ingested_at: str | None
    available_at: str | None
    feature_cutoff: str | None
    generated_at: str | None
    reasons: tuple[str, ...]


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
        feature_source_lineage: dict[str, dict[str, Any]] = {}
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
                if name in merged_features:
                    continue
                merged_features[name] = value
                feature_source_lineage[name] = {
                    "provider": row.provider,
                    "source_key": row.source_key,
                    "source_payload_sha256": row.source_payload_sha256,
                    "endpoint_id": row.endpoint_id,
                    "feature_cutoff": row.feature_cutoff,
                    "available_at": row.available_at,
                }
        admitted_rows = tuple(row for row in rows if not row.excluded_from_features)
        resolved_decision_time = _iso_or_none(decision_time)
        event_time = _max_clock(row.event_time for row in admitted_rows)
        ingested_at = _max_clock(row.ingested_at for row in admitted_rows)
        available_at = _max_clock(row.available_at for row in admitted_rows)
        feature_cutoff = _max_clock(row.feature_cutoff for row in admitted_rows)
        generated_at = _max_clock(row.generated_at for row in admitted_rows)
        temporal_violations = sorted(
            {reason for reason in violations if ":temporal_contract:" in reason}
        )
        return {
            "schema_version": "provider_feature_context_v1",
            "temporal_contract_version": "provider_feature_temporal_contract_v2",
            "symbol": normalized_symbol,
            "timeframe": timeframe,
            "event_time": event_time,
            "ingested_at": ingested_at,
            "available_at": available_at,
            "feature_cutoff": feature_cutoff,
            "generated_at": generated_at,
            "decision_time": resolved_decision_time,
            "provider_features": merged_features,
            "provider_payloads": provider_payloads,
            "payloads_for_tensor": _payloads_for_tensor(
                merged_features,
                feature_cutoff=feature_cutoff,
                available_at=available_at,
                decision_time=resolved_decision_time,
            ),
            "feature_source_lineage": feature_source_lineage,
            "source_lineage": {
                row.provider: {
                    "provider": row.provider,
                    "source_key": row.source_key,
                    "source_payload_sha256": row.source_payload_sha256,
                    "endpoint_id": row.endpoint_id,
                    "temporal_contract_valid": row.temporal_contract_valid,
                    "excluded_from_features": row.excluded_from_features,
                    "exclusion_reasons": list(row.exclusion_reasons),
                    "event_time": row.event_time,
                    "ingested_at": row.ingested_at,
                    "generated_at": row.generated_at,
                    "feature_cutoff": row.feature_cutoff,
                    "available_at": row.available_at,
                }
                for row in rows
            },
            "feature_count": len(merged_features),
            "actual_provider_count": sum(
                1 for row in rows if row.actual_payload_present and not row.excluded_from_features
            ),
            "optional_provider_failures": sorted(set(missing_optional)),
            "required_providers": list(required_providers),
            "core_system_blocked": bool(core_blocking),
            "point_in_time_violations": temporal_violations,
            "temporal_contract_violations": temporal_violations,
            "temporal_contract_valid": bool(
                merged_features
                and resolved_decision_time
                and available_at
                and feature_cutoff
                and not temporal_violations
            ),
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
        context = self.read_symbol_features(
            symbol=symbol,
            timeframe=timeframe,
            decision_time=datetime.now(tz=UTC),
        )
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
                "temporal_contract_valid": row["temporal_contract_valid"],
                "exclusion_reasons": row["exclusion_reasons"],
                "source_key": row["source_key"],
                "source_payload_sha256": row["source_payload_sha256"],
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
                ttl_contract_valid=ttl is not None and ttl > 0,
                temporal_contract_valid=False,
                event_time=None,
                ingested_at=None,
                available_at=None,
                feature_cutoff=None,
                generated_at=None,
                endpoint_id=None,
                source_payload_sha256=None,
                feature_count=0,
                features={},
            )
        raw_features_value = payload.get("features")
        raw_features: Mapping[str, Any] = (
            raw_features_value if isinstance(raw_features_value, Mapping) else {}
        )
        actual_payload_flag = payload.get("actual_payload_present")
        heartbeat_only_flag = payload.get("heartbeat_only")
        actual = actual_payload_flag is True and heartbeat_only_flag is False and bool(raw_features)
        status = _provider_status(payload, actual=actual)
        temporal = _validate_temporal_contract(
            payload,
            provider=provider,
            decision_time=decision_time,
        )
        excluded: list[str] = []
        ttl_valid = ttl is not None and ttl > 0
        if not ttl_valid:
            if ttl is None:
                ttl_reason = "unverifiable"
            elif ttl == -1:
                ttl_reason = "no_expiry"
            else:
                ttl_reason = "expired_or_missing"
            excluded.append(f"{provider}:ttl_contract_violation:{ttl_reason}:{key}")
        if actual_payload_flag is not True:
            excluded.append(f"{provider}:actual_payload_present_not_literal_true")
        if heartbeat_only_flag is not False:
            excluded.append(f"{provider}:heartbeat_only_not_literal_false")
        if not actual:
            excluded.append(f"{provider}:heartbeat_only_or_empty_payload")
        excluded.extend(temporal.reasons)
        stale_reasons = [
            f"{provider}:stale_payload_flag:{field}"
            for field in ("stale", "is_stale")
            if _explicit_stale(payload.get(field))
        ]
        if status in {"RATE_LIMITED", "DEGRADED"}:
            stale_reasons.append(f"{provider}:stale_provider_status:{status}")
        elif status == "INVALID":
            stale_reasons.append(f"{provider}:provider_status_invalid")
        excluded.extend(stale_reasons)
        stale = bool(stale_reasons)
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
            temporal_contract_valid=not temporal.reasons,
            # Invalid source clocks are never re-emitted as trusted clock
            # fields. The immutable payload digest plus rejection reasons keep
            # the exact source lineage without allowing rejected diagnostics to
            # poison an otherwise causal optional provider context.
            event_time=temporal.event_time if not temporal.reasons else None,
            ingested_at=temporal.ingested_at if not temporal.reasons else None,
            available_at=temporal.available_at if not temporal.reasons else None,
            feature_cutoff=temporal.feature_cutoff if not temporal.reasons else None,
            generated_at=temporal.generated_at if not temporal.reasons else None,
            endpoint_id=(
                None if payload.get("endpoint_id") is None else str(payload.get("endpoint_id"))
            ),
            source_payload_sha256=_payload_sha256(payload),
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
        if name in _SOURCE_CLOCK_FIELDS:
            continue
        out[name] = value
        canonical = canonical_map.get(name)
        if canonical:
            out.setdefault(canonical, value)
    return out


def _payloads_for_tensor(
    features: Mapping[str, float],
    *,
    feature_cutoff: str | None,
    available_at: str | None,
    decision_time: str | None,
) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {
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
    for payload in payloads.values():
        if not payload:
            continue
        payload.update(
            {
                "feature_cutoff": feature_cutoff,
                "available_at": available_at,
                "decision_time": decision_time,
            }
        )
    return payloads


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


def _provider_status(payload: Mapping[str, Any], *, actual: bool) -> str:
    for field in ("subscription_status", "status"):
        if field not in payload:
            continue
        value = payload.get(field)
        if value is None or value == "":
            continue
        if not isinstance(value, str):
            return "INVALID"
        normalized = value.strip().upper()
        return normalized or "INVALID"
    return "READY" if actual else "UNAVAILABLE"


def _explicit_stale(value: Any) -> bool:
    """Interpret false spellings narrowly and fail closed on hostile values."""

    if value is None or value is False:
        return False
    if value is True:
        return True
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"", "0", "false", "no", "off"}:
            return False
        if normalized in {"1", "true", "yes", "on"}:
            return True
        return True
    if isinstance(value, int | float):
        return value != 0
    return True


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


_SOURCE_CLOCK_FIELDS: tuple[str, ...] = (
    "event_time",
    "source_event_time",
    "ingested_at",
    "received_at",
    "source_received_time",
    "available_at",
    "source_available_time",
    "generated_at",
    "generated_utc",
    "feature_cutoff",
    "decision_time",
    "execution_time",
)


def _validate_temporal_contract(
    payload: Mapping[str, Any],
    *,
    provider: str,
    decision_time: str | int | float | datetime | None,
) -> _TemporalEnvelope:
    """Validate literal source clocks and aggregate a conservative envelope.

    ``available_at`` and ``feature_cutoff`` are required on every mapping that
    actually carries provider features. They are never substituted from
    ``generated_at`` or ``event_time``. All nested endpoint rows are checked
    before any top-level feature can be admitted.
    """

    decision = _parse_time(decision_time)
    carries_features = _contains_feature_payload(payload)
    reasons: list[str] = []
    prefix = f"{provider}:temporal_contract"
    if carries_features:
        if decision_time in (None, ""):
            reasons.append(f"{prefix}:decision_time_missing")
        elif decision is None:
            reasons.append(f"{prefix}:decision_time_not_strict_utc")

    clocks: dict[str, list[datetime]] = {
        "event_time": [],
        "ingested_at": [],
        "available_at": [],
        "feature_cutoff": [],
        "generated_at": [],
    }

    def visit(node: Any, path: tuple[str, ...]) -> None:
        if isinstance(node, list | tuple):
            for index, item in enumerate(node):
                visit(item, (*path, str(index)))
            return
        if not isinstance(node, Mapping):
            return

        path_text = ".".join(path) if path else "root"
        feature_bearing = _feature_bearing_mapping(node)
        parsed: dict[str, datetime] = {}
        for field in _SOURCE_CLOCK_FIELDS:
            if field not in node or node.get(field) in (None, ""):
                continue
            value = _parse_time(node.get(field))
            if value is None:
                reasons.append(f"{prefix}:{path_text}:{field}_not_strict_utc")
                continue
            parsed[field] = value
            if decision is not None and value > decision:
                reasons.append(f"{prefix}:{path_text}:{field}_after_decision_time")

        if feature_bearing:
            if node.get("available_at") in (None, ""):
                reasons.append(f"{prefix}:{path_text}:available_at_missing")
            elif "available_at" not in parsed:
                # The parse rejection above is the authoritative reason.
                pass
            if node.get("feature_cutoff") in (None, ""):
                reasons.append(f"{prefix}:{path_text}:feature_cutoff_missing")

        event = _latest_clock(parsed, "event_time", "source_event_time")
        ingested = _latest_clock(
            parsed,
            "ingested_at",
            "received_at",
            "source_received_time",
        )
        available = _latest_clock(parsed, "available_at", "source_available_time")
        generated = _latest_clock(parsed, "generated_at", "generated_utc")
        cutoff = parsed.get("feature_cutoff")

        _reject_clock_alias_conflict(
            parsed,
            fields=("event_time", "source_event_time"),
            reason=f"{prefix}:{path_text}:event_time_alias_conflict",
            reasons=reasons,
        )
        _reject_clock_alias_conflict(
            parsed,
            fields=("ingested_at", "received_at", "source_received_time"),
            reason=f"{prefix}:{path_text}:ingested_at_alias_conflict",
            reasons=reasons,
        )
        _reject_clock_alias_conflict(
            parsed,
            fields=("available_at", "source_available_time"),
            reason=f"{prefix}:{path_text}:available_at_alias_conflict",
            reasons=reasons,
        )
        _reject_clock_alias_conflict(
            parsed,
            fields=("generated_at", "generated_utc"),
            reason=f"{prefix}:{path_text}:generated_at_alias_conflict",
            reasons=reasons,
        )

        _reject_inversion(
            earlier=event,
            later=cutoff,
            reason=f"{prefix}:{path_text}:event_time_after_feature_cutoff",
            reasons=reasons,
        )
        _reject_inversion(
            earlier=event,
            later=ingested,
            reason=f"{prefix}:{path_text}:event_time_after_ingested_at",
            reasons=reasons,
        )
        _reject_inversion(
            earlier=event,
            later=available,
            reason=f"{prefix}:{path_text}:event_time_after_available_at",
            reasons=reasons,
        )
        _reject_inversion(
            earlier=cutoff,
            later=generated,
            reason=f"{prefix}:{path_text}:feature_cutoff_after_generated_at",
            reasons=reasons,
        )
        _reject_inversion(
            earlier=cutoff,
            later=available,
            reason=f"{prefix}:{path_text}:feature_cutoff_after_available_at",
            reasons=reasons,
        )
        _reject_inversion(
            earlier=ingested,
            later=generated,
            reason=f"{prefix}:{path_text}:ingested_at_after_generated_at",
            reasons=reasons,
        )
        _reject_inversion(
            earlier=ingested,
            later=available,
            reason=f"{prefix}:{path_text}:ingested_at_after_available_at",
            reasons=reasons,
        )
        _reject_inversion(
            earlier=generated,
            later=available,
            reason=f"{prefix}:{path_text}:generated_at_after_available_at",
            reasons=reasons,
        )

        for name, value in (
            ("event_time", event),
            ("ingested_at", ingested),
            ("available_at", available),
            ("feature_cutoff", cutoff),
            ("generated_at", generated),
        ):
            if value is not None:
                clocks[name].append(value)

        for name, nested in node.items():
            # Feature values are required to be finite scalars by
            # _canonicalize_features. Temporal provenance belongs to the
            # feature-bearing wrapper, not to keys inside the numeric map.
            if name == "features":
                continue
            if isinstance(nested, Mapping | list | tuple):
                visit(nested, (*path, str(name)))

    visit(payload, ())
    return _TemporalEnvelope(
        event_time=_iso_latest(clocks["event_time"]),
        ingested_at=_iso_latest(clocks["ingested_at"]),
        available_at=_iso_latest(clocks["available_at"]),
        feature_cutoff=_iso_latest(clocks["feature_cutoff"]),
        generated_at=_iso_latest(clocks["generated_at"]),
        reasons=tuple(sorted(set(reasons))),
    )


def _contains_feature_payload(value: Any) -> bool:
    if isinstance(value, list | tuple):
        return any(_contains_feature_payload(item) for item in value)
    if not isinstance(value, Mapping):
        return False
    if _feature_bearing_mapping(value):
        return True
    return any(
        _contains_feature_payload(item) for name, item in value.items() if name != "features"
    )


def _feature_bearing_mapping(value: Mapping[str, Any]) -> bool:
    features = value.get("features")
    return bool(isinstance(features, Mapping) and features) or bool(
        value.get("actual_payload_present") is True
    )


def _latest_clock(parsed: Mapping[str, datetime], *fields: str) -> datetime | None:
    values = [parsed[field] for field in fields if field in parsed]
    return max(values) if values else None


def _reject_clock_alias_conflict(
    parsed: Mapping[str, datetime],
    *,
    fields: tuple[str, ...],
    reason: str,
    reasons: list[str],
) -> None:
    values = {parsed[field] for field in fields if field in parsed}
    if len(values) > 1:
        reasons.append(reason)


def _reject_inversion(
    *,
    earlier: datetime | None,
    later: datetime | None,
    reason: str,
    reasons: list[str],
) -> None:
    if earlier is not None and later is not None and earlier > later:
        reasons.append(reason)


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _iso_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _iso_latest(values: list[datetime]) -> str | None:
    return _iso_utc(max(values)) if values else None


def _max_clock(values: Any) -> str | None:
    parsed = [_parse_time(value) for value in values if value not in (None, "")]
    valid = [value for value in parsed if value is not None]
    return _iso_utc(max(valid)) if valid else None


def _parse_time(value: str | int | float | datetime | None) -> datetime | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, int | float):
        raw = float(value)
        if not math.isfinite(raw):
            return None
        if abs(raw) >= 10_000_000_000:
            raw /= 1000.0
        try:
            parsed = datetime.fromtimestamp(raw, tz=UTC)
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
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _iso_or_none(value: str | int | float | datetime | None) -> str | None:
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return _iso_utc(parsed)
