"""CoinGlass Redis publisher for endpoint payloads and feature rows."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from app.services.coinglass_provider.endpoint_registry import (
    CoinGlassEndpointSpec,
    coinglass_endpoint_registry,
)
from app.services.coinglass_provider.health import build_coinglass_health
from app.services.coinglass_provider.normalizer import normalize_coinglass_payload
from app.services.coinglass_provider.rate_limit import classify_status, dashboard_color


RAW_KEY_BY_GROUP = {
    "funding_rate": "v2:coinglass:funding:{symbol}",
    "open_interest": "v2:coinglass:open_interest:{symbol}",
    "long_short_ratio": "v2:coinglass:long_short:{symbol}",
    "liquidation_orders": "v2:coinglass:liquidations:{symbol}",
    "liquidation_heatmap_or_levels": "v2:coinglass:liquidation_levels:{symbol}",
    "market_snapshot": "v2:coinglass:market_snapshot:{symbol}",
    "trades": "v2:coinglass:trades:{symbol}",
    "orderbook_l2_l3": "v2:coinglass:orderbook:{symbol}",
}


def publish_coinglass_result(
    redis_client: Any,
    *,
    env: Mapping[str, str | None],
    spec: CoinGlassEndpointSpec,
    symbol: str,
    http_status: int | None,
    payload: Any,
    rate_limit_status: Mapping[str, Any],
    error_class: str | None = None,
    timeframe: str = "1m",
) -> dict[str, Any]:
    normalized = normalize_coinglass_payload(spec=spec, symbol=symbol, payload=payload)
    status = _status_from_response(http_status=http_status, error_class=error_class)
    actual = normalized["actual_payload_present"] is True and status == "READY"
    now = _now()
    envelope = {
        **normalized,
        "available_at": now,
        "ingested_at": now,
        "generated_at": now,
        "ttl_seconds": spec.ttl_seconds,
        "stale_after": spec.ttl_seconds,
        "provider_ready": actual,
        "subscription_status": status,
        "auth_status": status,
        "rate_limit_status": rate_limit_status,
        "last_http_status": http_status,
        "last_error_class": error_class,
        "dashboard_color": dashboard_color(
            provider_enabled=True,
            auth_status=status,
            actual_payload_count=1 if actual else 0,
        ),
    }
    keys_written: list[str] = []
    if redis_client is not None:
        raw_key_template = RAW_KEY_BY_GROUP.get(spec.group)
        if raw_key_template:
            key = raw_key_template.format(symbol=symbol)
            _set_json(redis_client, key, envelope, ex=spec.ttl_seconds)
            keys_written.append(key)
        feature_key = f"v2:features:coinglass:{symbol}:{timeframe}"
        feature_payload, feature_ttl = _merge_feature_payload(
            redis_client,
            feature_key,
            envelope=envelope,
            spec=spec,
            status=status,
            actual=actual,
            now=now,
        )
        _set_json(redis_client, feature_key, feature_payload, ex=feature_ttl)
        keys_written.append(feature_key)
        _set_json(
            redis_client,
            "v2:provider:coinglass:feature_bridge_status",
            _feature_bridge_status(feature_payload),
            ex=3600,
        )
        keys_written.append("v2:provider:coinglass:feature_bridge_status")
        _set_json(redis_client, "v2:provider:coinglass:usage", rate_limit_status, ex=3600)
        endpoint_row = {
            "schema_version": "coinglass_endpoint_status_v1",
            "provider": "coinglass",
            "endpoint_id": spec.endpoint_id,
            "symbol": symbol,
            "status": status,
            "actual_payload_present": bool(actual),
            "heartbeat_only": not bool(actual),
            "dashboard_color": envelope["dashboard_color"],
            "generated_utc": now,
            "core_system_blocked": False,
            "raw_key_exposed": False,
        }
        endpoint_status = _merge_endpoint_status(
            redis_client,
            "v2:provider:coinglass:endpoint_status",
            endpoint_id=spec.endpoint_id,
            row=endpoint_row,
            provider="coinglass",
            generated_utc=now,
        )
        _set_json(redis_client, "v2:provider:coinglass:endpoint_status", endpoint_status, ex=3600)
        endpoint_actual_count = int(endpoint_status.get("actual_payload_endpoint_count") or 0)
        health_status = "READY" if endpoint_actual_count > 0 else status
        health = build_coinglass_health(env, last_http_status=http_status, last_error=error_class)
        health.update(
            {
                "status": health_status,
                "enabled": str(env.get("COINGLASS_ENABLED", "1")).lower() not in {"0", "false", "no"},
                "subscription_status": health_status,
                "auth_status": health_status,
                "rate_limit_status": dict(rate_limit_status),
                "actual_payload_count_5m": endpoint_actual_count,
                "actual_payload_count_1h": endpoint_actual_count,
                "last_success_at": now if endpoint_actual_count > 0 else None,
                "last_error_at": now if not actual and http_status is not None else None,
                "dashboard_color": dashboard_color(
                    provider_enabled=True,
                    auth_status=health_status,
                    actual_payload_count=endpoint_actual_count,
                ),
                "core_system_blocked": False,
            }
        )
        _set_json(redis_client, "v2:provider:coinglass:health", health, ex=3600)
        keys_written.extend(
            [
                "v2:provider:coinglass:usage",
                "v2:provider:coinglass:endpoint_status",
                "v2:provider:coinglass:health",
            ]
        )
    return {
        "schema_version": "coinglass_publish_result_v1",
        "provider": "coinglass",
        "endpoint_id": spec.endpoint_id,
        "symbol": symbol,
        "status": status,
        "actual_payload_present": bool(actual),
        "heartbeat_only": not bool(actual),
        "keys_written": keys_written,
        "core_system_blocked": False,
        "raw_key_exposed": False,
    }


def _set_json(redis_client: Any, key: str, payload: Mapping[str, Any], *, ex: int) -> None:
    redis_client.set(key, json.dumps(dict(payload), sort_keys=True, default=str), ex=ex)


def _feature_bridge_status(payload: Mapping[str, Any]) -> dict[str, Any]:
    features = payload.get("features") if isinstance(payload.get("features"), Mapping) else {}
    feature_count = len(features)
    actual = bool(payload.get("actual_payload_present")) and feature_count > 0
    return {
        "schema_version": "coinglass_feature_bridge_status_v1",
        "provider": "coinglass",
        "generated_utc": payload.get("generated_at") or payload.get("available_at"),
        "symbol": payload.get("symbol"),
        "timeframe": payload.get("timeframe"),
        "available_at": payload.get("available_at"),
        "feature_cutoff": payload.get("feature_cutoff"),
        "decision_time_safe": payload.get("decision_time_safe"),
        "status": payload.get("subscription_status") or ("READY" if actual else "PAYLOADS_PENDING"),
        "feature_bridge_ready": actual,
        "feature_count": feature_count,
        "missing_feature_flags": payload.get("missing_feature_flags") or [],
        "stale_feature_flags": payload.get("stale_feature_flags") or [],
        "missing_mask": payload.get("missing_mask") or {},
        "missing_mask_true": bool(payload.get("missing_feature_flags")),
        "stale_mask": payload.get("stale_mask") or {},
        "stale_mask_true": bool(payload.get("stale_feature_flags")),
        "actual_payload_present": actual,
        "heartbeat_only": not actual,
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


def _merge_feature_payload(
    redis_client: Any,
    key: str,
    *,
    envelope: Mapping[str, Any],
    spec: CoinGlassEndpointSpec,
    status: str,
    actual: bool,
    now: str,
) -> tuple[dict[str, Any], int]:
    endpoint_payloads: dict[str, dict[str, Any]] = {}
    stale_families: set[str] = set()
    now_dt = _parse_utc(now) or datetime.now(timezone.utc)
    try:
        raw = redis_client.get(key)
        if raw:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            prior = json.loads(str(raw))
            prior_endpoints = prior.get("endpoint_payloads") if isinstance(prior, Mapping) else {}
            if isinstance(prior_endpoints, Mapping):
                for endpoint_id, row in prior_endpoints.items():
                    if not isinstance(row, Mapping):
                        continue
                    expires_at = _parse_utc(row.get("expires_at"))
                    if expires_at is None or expires_at <= now_dt:
                        stale_families.add(str(endpoint_id))
                        continue
                    endpoint_payloads[str(endpoint_id)] = dict(row)
    except Exception:
        endpoint_payloads = {}

    if actual:
        expires_at = now_dt + timedelta(seconds=spec.ttl_seconds)
        endpoint_payloads[spec.endpoint_id] = {
            "endpoint_id": spec.endpoint_id,
            "feature_family": spec.group,
            "features": dict(envelope.get("features") or {}),
            "event_time": envelope.get("event_time"),
            "available_at": envelope.get("available_at"),
            "feature_cutoff": envelope.get("event_time") or envelope.get("available_at"),
            "expires_at": expires_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "actual_payload_present": True,
            "status": status,
            "ttl_seconds": spec.ttl_seconds,
        }

    merged_features: dict[str, float] = {}
    active_expires: list[datetime] = []
    event_times: list[str] = []
    available_times: list[str] = []
    for row in endpoint_payloads.values():
        features = row.get("features") if isinstance(row.get("features"), Mapping) else {}
        for name, value in features.items():
            try:
                merged_features[str(name)] = float(value)
            except (TypeError, ValueError):
                continue
        expires_at = _parse_utc(row.get("expires_at"))
        if expires_at is not None:
            active_expires.append(expires_at)
        if row.get("event_time"):
            event_times.append(str(row.get("event_time")))
        if row.get("available_at"):
            available_times.append(str(row.get("available_at")))

    disabled_endpoints = sorted(
        item.strip()
        for item in os.environ.get("COINGLASS_DISABLED_ENDPOINTS", "").split(",")
        if item.strip()
    )
    stale_families.discard(spec.endpoint_id)
    stale_families.difference_update(endpoint_payloads)
    missing_flags: list[str] = []
    stale_flags: list[str] = []
    for registry_spec in coinglass_endpoint_registry():
        if registry_spec.group == "exchange_metadata":
            continue
        if registry_spec.endpoint_id in stale_families:
            stale_flags.extend(registry_spec.feature_outputs)
        elif (
            registry_spec.endpoint_id not in endpoint_payloads
            and registry_spec.endpoint_id not in disabled_endpoints
        ):
            missing_flags.extend(registry_spec.feature_outputs)

    aggregate_actual = bool(merged_features)
    ttl = spec.ttl_seconds
    if active_expires:
        # Keep the aggregate alive until the LAST family expires; per-row
        # expires_at pruning above already drops stale families on read.
        # Expiring at the soonest family made the whole key flap every time
        # a short-TTL family (60s trades/orderbook) lapsed between cadenced
        # refreshes, so consumers saw MISSING while funding/OI were valid.
        ttl = max(1, int((max(active_expires) - now_dt).total_seconds()))
    aggregate_status = "READY" if aggregate_actual else status
    payload = {
        **dict(envelope),
        "schema_version": "coinglass_aggregated_feature_payload_v1",
        "endpoint_id": "coinglass_aggregate",
        "feature_family": "coinglass_aggregate",
        "event_time": max(event_times) if event_times else envelope.get("event_time"),
        "available_at": max(available_times) if available_times else envelope.get("available_at"),
        "feature_cutoff": max(event_times) if event_times else envelope.get("event_time") or envelope.get("available_at"),
        "features": merged_features,
        "endpoint_payloads": endpoint_payloads,
        "actual_payload_endpoint_count": len(endpoint_payloads),
        "source_endpoint_count": len(endpoint_payloads),
        "missing_feature_flags": sorted(missing_flags),
        "stale_feature_flags": sorted(stale_flags),
        "disabled_endpoints": disabled_endpoints,
        "decision_time_safe": aggregate_actual,
        "actual_payload_present": aggregate_actual,
        "heartbeat_only": not aggregate_actual,
        "provider_ready": aggregate_actual,
        "subscription_status": aggregate_status,
        "auth_status": aggregate_status,
        "dashboard_color": dashboard_color(
            provider_enabled=True,
            auth_status=aggregate_status,
            actual_payload_count=1 if aggregate_actual else 0,
        ),
    }
    return payload, ttl


def _merge_endpoint_status(
    redis_client: Any,
    key: str,
    *,
    endpoint_id: str,
    row: Mapping[str, Any],
    provider: str,
    generated_utc: str,
) -> dict[str, Any]:
    existing: dict[str, Any] = {}
    try:
        raw = redis_client.get(key)
        if raw:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            parsed = json.loads(str(raw))
            if isinstance(parsed, dict):
                existing = parsed
    except Exception:
        existing = {}
    endpoints = existing.get("endpoints") if isinstance(existing.get("endpoints"), dict) else {}
    endpoints = dict(endpoints)
    endpoints[endpoint_id] = dict(row)
    actual_count = sum(
        1
        for item in endpoints.values()
        if isinstance(item, Mapping) and item.get("actual_payload_present") is True
    )
    return {
        "schema_version": "coinglass_endpoint_status_v1",
        "provider": provider,
        "generated_utc": generated_utc,
        "endpoints": endpoints,
        "actual_payload_endpoint_count": actual_count,
        "heartbeat_only_green_allowed": False,
        "core_system_blocked": False,
        "raw_key_exposed": False,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _status_from_response(*, http_status: int | None, error_class: str | None) -> str:
    status = classify_status(http_status)
    error = str(error_class or "").upper()
    if any(
        marker in error
        for marker in (
            "API_KEY_MISSING",
            "IN_BODY_401",
            "IN_BODY_402",
            "IN_BODY_403",
            "UNAUTHORIZED",
            "UNSUBSCRIBED",
            "FORBIDDEN",
        )
    ):
        return "CONFIGURED_BUT_UNAUTHORIZED_OR_UNSUBSCRIBED"
    return status


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
