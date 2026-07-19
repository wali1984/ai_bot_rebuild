"""Moralis Redis publisher for endpoint payloads and features."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from app.services.smart_money_wallets.endpoint_registry import MoralisEndpointSpec
from app.services.smart_money_wallets.health import build_moralis_health
from app.services.smart_money_wallets.moralis_feature_bridge import (
    build_moralis_feature_payload,
    publish_moralis_feature_payload,
)
from app.services.smart_money_wallets.normalizer import normalize_moralis_payload
from app.services.smart_money_wallets.rate_limit import classify_status


def publish_moralis_result(
    redis_client: Any,
    *,
    env: Mapping[str, str | None],
    spec: MoralisEndpointSpec,
    chain: str,
    symbol: str | None = None,
    wallet: str | None = None,
    token: str | None = None,
    http_status: int | None,
    payload: Any,
    budget_status: Mapping[str, Any],
    error_class: str | None = None,
    timeframe: str = "1m",
    token_map_count: int = 0,
    wallet_watchlist_count: int = 0,
) -> dict[str, Any]:
    normalized = normalize_moralis_payload(
        spec=spec,
        symbol=symbol,
        chain=chain,
        wallet=wallet,
        token=token,
        payload=payload,
    )
    status = _status_from_response(http_status=http_status, error_class=error_class)
    actual = normalized["actual_payload_present"] is True and status == "READY"
    now = _now()
    envelope = {
        **normalized,
        # The normalized event is the source observation. The cutoff is the
        # latest source observation included in this endpoint feature family;
        # availability is assigned only when the completed envelope is about
        # to be published.
        "feature_cutoff": normalized.get("event_time"),
        "available_at": now,
        "ingested_at": now,
        "generated_at": now,
        "ttl_seconds": spec.ttl_seconds,
        "stale_after": spec.ttl_seconds,
        "provider_ready": actual,
        "subscription_status": status,
        "auth_status": status,
        "compute_budget_status": dict(budget_status),
        "last_http_status": http_status,
        "last_error_class": error_class,
        "dashboard_color": _dashboard_color(status=status, actual=actual),
    }
    keys_written: list[str] = []
    if redis_client is not None:
        for key in _raw_keys(spec, chain=chain, wallet=wallet, token=token, symbol=symbol):
            _set_json(redis_client, key, envelope, ex=spec.ttl_seconds)
            keys_written.append(key)
        if symbol:
            # The rolling per-endpoint aggregate lives on an INTERNAL key; the
            # canonical masked contract on v2:features:moralis:* is owned by
            # the feature bridge alone. Writing the raw aggregate to the
            # public feature key clobbered the bridge payload (masks, feature
            # counts, honesty flags) on every endpoint publish.
            aggregate_key = f"v2:moralis:feature_aggregate:{symbol}:{timeframe}"
            feature_payload, feature_ttl = _merge_feature_payload(
                redis_client,
                aggregate_key,
                envelope=envelope,
                spec=spec,
                status=status,
                actual=actual,
                now=now,
                token_map_count=token_map_count,
                wallet_watchlist_count=wallet_watchlist_count,
                budget_status=budget_status,
            )
            _set_json(redis_client, aggregate_key, feature_payload, ex=feature_ttl)
            keys_written.append(aggregate_key)
            bridge_payload = publish_moralis_feature_payload(
                redis_client,
                symbol=symbol,
                timeframe=timeframe,
                features=feature_payload.get("features") if isinstance(feature_payload.get("features"), Mapping) else {},
                token_map_count=token_map_count,
                wallet_watchlist_count=wallet_watchlist_count,
                actual_payload_present=feature_payload.get("actual_payload_present") is True,
                event_time=feature_payload.get("event_time"),
                feature_cutoff=feature_payload.get("feature_cutoff"),
                ttl_seconds=feature_ttl,
                stale_after=feature_payload.get("stale_after"),
                compute_unit_status=budget_status,
            )
            for key in bridge_payload.get("keys_written") or []:
                if key not in keys_written:
                    keys_written.append(str(key))
        _set_json(redis_client, "v2:provider:moralis:usage", budget_status, ex=3600)
        endpoint_row = {
            "schema_version": "moralis_endpoint_status_v1",
            "provider": "moralis",
            "endpoint_id": spec.endpoint_id,
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
            "v2:provider:moralis:endpoint_status",
            endpoint_id=spec.endpoint_id,
            row=endpoint_row,
            provider="moralis",
            generated_utc=now,
        )
        _set_json(redis_client, "v2:provider:moralis:endpoint_status", endpoint_status, ex=3600)
        endpoint_actual_count = int(endpoint_status.get("actual_payload_endpoint_count") or 0)
        feature_bridge_ready = False
        feature_bridge_color = "GRAY"
        bridge_status_payload: dict[str, Any] = {}
        try:
            bridge_raw = redis_client.get("v2:provider:moralis:feature_bridge_status")
            if bridge_raw:
                if isinstance(bridge_raw, bytes):
                    bridge_raw = bridge_raw.decode("utf-8", errors="replace")
                bridge_status_payload = json.loads(str(bridge_raw))
                feature_bridge_ready = bridge_status_payload.get("feature_bridge_ready") is True
                feature_bridge_color = str(bridge_status_payload.get("dashboard_color") or "GRAY")
        except Exception:
            feature_bridge_ready = False
            feature_bridge_color = "GRAY"
            bridge_status_payload = {}
        health_status = "READY" if feature_bridge_ready else (status if endpoint_actual_count <= 0 else "PARTIAL_REQUIRED_FEATURES_MISSING")
        health = build_moralis_health(env, last_http_status=http_status, last_error=error_class)
        health.update(
            {
                "status": health_status,
                "enabled": str(env.get("MORALIS_ENABLED", "1")).lower() not in {"0", "false", "no"},
                "subscription_status": health_status,
                "auth_status": health_status,
                "daily_cu_used": _dig(budget_status, "compute_budget", "used_today"),
                "monthly_cu_used": _dig(budget_status, "compute_budget", "used_month"),
                "actual_payload_count_5m": endpoint_actual_count,
                "actual_payload_count_1h": endpoint_actual_count,
                "last_success_at": now if endpoint_actual_count > 0 else None,
                "last_error_at": now if not actual and http_status is not None else None,
                "dashboard_color": "GREEN" if feature_bridge_ready else feature_bridge_color,
                "feature_bridge_ready": feature_bridge_ready,
                "feature_count": bridge_status_payload.get("feature_count"),
                "required_feature_count": bridge_status_payload.get("required_feature_count"),
                "missing_feature_flags": bridge_status_payload.get("missing_feature_flags"),
                "stale_feature_flags": bridge_status_payload.get("stale_feature_flags"),
                "missing_mask": bridge_status_payload.get("missing_mask"),
                "missing_mask_true": bridge_status_payload.get("missing_mask_true"),
                "stale_mask": bridge_status_payload.get("stale_mask"),
                "stale_mask_true": bridge_status_payload.get("stale_mask_true"),
                "token_map_count": bridge_status_payload.get("token_map_count"),
                "wallet_watchlist_count": bridge_status_payload.get("wallet_watchlist_count"),
                "actual_payload_present": bridge_status_payload.get("actual_payload_present"),
                "heartbeat_only": bridge_status_payload.get("heartbeat_only"),
                "heartbeat_only_green_allowed": False,
                "decision_time_safe": bridge_status_payload.get("decision_time_safe"),
                "core_system_blocked": False,
            }
        )
        _set_json(redis_client, "v2:provider:moralis:health", health, ex=3600)
        keys_written.extend(
            [
                "v2:provider:moralis:usage",
                "v2:provider:moralis:endpoint_status",
                "v2:provider:moralis:health",
            ]
        )
    return {
        "schema_version": "moralis_publish_result_v1",
        "provider": "moralis",
        "endpoint_id": spec.endpoint_id,
        "symbol": symbol,
        "status": status,
        "actual_payload_present": bool(actual),
        "heartbeat_only": not bool(actual),
        "keys_written": keys_written,
        "core_system_blocked": False,
        "raw_key_exposed": False,
    }


def _raw_keys(
    spec: MoralisEndpointSpec,
    *,
    chain: str,
    wallet: str | None,
    token: str | None,
    symbol: str | None,
) -> list[str]:
    if spec.group in {"wallet_balances", "wallet_token_balances_price", "wallet_networth"} and wallet:
        return [f"v2:moralis:wallet:{chain}:{wallet}"]
    if spec.group in {"wallet_history", "wallet_transactions", "wallet_address_transfers"} and wallet:
        return [f"v2:moralis:wallet_history:{chain}:{wallet}"]
    if spec.group in {"token_transfers", "token_address_transfers"} and token:
        return [f"v2:moralis:token_transfers:{chain}:{token}"]
    if spec.group == "token_holders" and token:
        return [f"v2:moralis:token_holders:{chain}:{token}"]
    if spec.group in {"swaps", "wallet_swaps"} and wallet:
        return [f"v2:moralis:swaps:{chain}:{wallet}"]
    if spec.group == "token_swaps" and token:
        return [f"v2:moralis:swaps:{chain}:{token}"]
    if spec.group in {"token_metadata", "token_price", "multiple_token_prices"} and token:
        return [f"v2:moralis:{spec.group}:{chain}:{token}"]
    if spec.group == "streams":
        return ["v2:provider:moralis:stream:webhook:latest"]
    return [f"v2:moralis:{spec.group}:{chain}:{symbol or token or wallet or 'unknown'}"]


def _dashboard_color(*, status: str, actual: bool) -> str:
    if status == "READY" and actual:
        return "GREEN"
    if status in {"RATE_LIMITED", "DEGRADED"}:
        return "YELLOW"
    return "GRAY"


def _merge_feature_payload(
    redis_client: Any,
    key: str,
    *,
    envelope: Mapping[str, Any],
    spec: MoralisEndpointSpec,
    status: str,
    actual: bool,
    now: str,
    token_map_count: int = 0,
    wallet_watchlist_count: int = 0,
    budget_status: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], int]:
    endpoint_payloads: dict[str, dict[str, Any]] = {}
    endpoint_temporal_rejections: list[str] = []
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
                        continue
                    temporal_reasons = _endpoint_temporal_rejection_reasons(
                        row,
                        observed_at=now_dt,
                    )
                    if temporal_reasons:
                        endpoint_temporal_rejections.extend(
                            f"{endpoint_id}:{reason}" for reason in temporal_reasons
                        )
                        continue
                    endpoint_payloads[str(endpoint_id)] = dict(row)
    except Exception:
        endpoint_payloads = {}

    if actual:
        expires_at = now_dt + timedelta(seconds=spec.ttl_seconds)
        endpoint_row = {
            "endpoint_id": spec.endpoint_id,
            "feature_family": spec.group,
            "features": dict(envelope.get("features") or {}),
            "event_time": envelope.get("event_time"),
            "available_at": envelope.get("available_at"),
            "feature_cutoff": envelope.get("feature_cutoff"),
            "generated_at": envelope.get("generated_at"),
            "expires_at": expires_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "actual_payload_present": True,
            "status": status,
            "ttl_seconds": spec.ttl_seconds,
        }
        temporal_reasons = _endpoint_temporal_rejection_reasons(
            endpoint_row,
            observed_at=now_dt,
        )
        if temporal_reasons:
            endpoint_temporal_rejections.extend(
                f"{spec.endpoint_id}:{reason}" for reason in temporal_reasons
            )
        else:
            endpoint_payloads[spec.endpoint_id] = endpoint_row

    merged_features: dict[str, float] = {}
    active_expires: list[datetime] = []
    event_times: list[str] = []
    feature_cutoffs: list[str] = []
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
        if row.get("feature_cutoff"):
            feature_cutoffs.append(str(row.get("feature_cutoff")))
        if row.get("available_at"):
            available_times.append(str(row.get("available_at")))

    aggregate_actual = bool(merged_features)
    ttl = spec.ttl_seconds
    if active_expires:
        ttl = max(1, int((min(active_expires) - now_dt).total_seconds()))
    aggregate_status = "READY" if aggregate_actual else status
    event_time = _latest_strict_utc(event_times) or envelope.get("event_time")
    feature_cutoff = _latest_strict_utc(feature_cutoffs) or envelope.get("feature_cutoff")
    source_available_at = _latest_strict_utc(available_times) or envelope.get("available_at")
    payload = build_moralis_feature_payload(
        symbol=str(envelope.get("symbol") or ""),
        timeframe=str(envelope.get("timeframe") or "1m"),
        features=merged_features,
        token_map_count=token_map_count,
        wallet_watchlist_count=wallet_watchlist_count,
        actual_payload_present=aggregate_actual,
        event_time=event_time,
        feature_cutoff=feature_cutoff,
        ttl_seconds=ttl,
        stale_after=ttl,
        compute_unit_status=budget_status or envelope.get("compute_budget_status") or {},
    )
    bridge_status = payload.get("status")
    bridge_dashboard_color = payload.get("dashboard_color")
    bridge_provider_ready = payload.get("provider_ready")
    bridge_feature_ready = payload.get("feature_bridge_ready")
    bridge_missing = payload.get("missing_feature_flags")
    bridge_stale = payload.get("stale_feature_flags")
    payload.update(
        {
            "chain": envelope.get("chain"),
            "wallet": envelope.get("wallet"),
            "token": envelope.get("token"),
            "ingested_at": envelope.get("ingested_at"),
            "source_available_at": source_available_at,
            "compute_budget_status": envelope.get("compute_budget_status"),
            "last_http_status": envelope.get("last_http_status"),
            "last_error_class": envelope.get("last_error_class"),
            "schema_version": "moralis_feature_bridge_v1",
            "endpoint_id": "moralis_aggregate",
            "feature_family": "moralis_aggregate",
            "features": payload.get("features", {}),
            "endpoint_payloads": endpoint_payloads,
            "actual_payload_endpoint_count": len(endpoint_payloads),
            "endpoint_temporal_rejection_reasons": sorted(
                set(endpoint_temporal_rejections)
            ),
            "rejected_endpoint_count": len(
                {
                    reason.split(":", 1)[0]
                    for reason in endpoint_temporal_rejections
                }
            ),
            "subscription_status": (
                aggregate_status
                if payload.get("actual_payload_present") is True
                else payload.get("status")
            ),
            "auth_status": status,
            "status": bridge_status,
            "dashboard_color": bridge_dashboard_color,
            "provider_ready": bridge_provider_ready,
            "feature_bridge_ready": bridge_feature_ready,
            "missing_feature_flags": bridge_missing,
            "stale_feature_flags": bridge_stale,
        }
    )
    return payload, ttl


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
        return "CONFIGURED_BUT_UNSUBSCRIBED_OR_FORBIDDEN"
    return status


def _dig(mapping: Mapping[str, Any], *path: str) -> Any:
    cur: Any = mapping
    for item in path:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(item)
    return cur


def _set_json(redis_client: Any, key: str, payload: Mapping[str, Any], *, ex: int) -> None:
    redis_client.set(key, json.dumps(dict(payload), sort_keys=True, default=str), ex=ex)


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
        "schema_version": "moralis_endpoint_status_v1",
        "provider": provider,
        "generated_utc": generated_utc,
        "endpoints": endpoints,
        "actual_payload_endpoint_count": actual_count,
        "heartbeat_only_green_allowed": False,
        "core_system_blocked": False,
        "raw_key_exposed": False,
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


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


def _latest_strict_utc(values: list[str]) -> str | None:
    parsed = [_parse_utc(value) for value in values]
    valid = [value for value in parsed if value is not None]
    if not valid:
        return None
    return max(valid).isoformat(timespec="seconds").replace("+00:00", "Z")


def _endpoint_temporal_rejection_reasons(
    row: Mapping[str, Any],
    *,
    observed_at: datetime,
) -> list[str]:
    parsed: dict[str, datetime] = {}
    reasons: list[str] = []
    for field in ("event_time", "feature_cutoff", "generated_at", "available_at"):
        value = row.get(field)
        if value in (None, ""):
            reasons.append(f"{field.upper()}_MISSING")
            continue
        clock = _parse_utc(value)
        if clock is None:
            reasons.append(f"{field.upper()}_NOT_STRICT_UTC")
            continue
        parsed[field] = clock
        if clock > observed_at:
            reasons.append(f"{field.upper()}_AFTER_OBSERVED_AT")

    for earlier, later, reason in (
        ("event_time", "feature_cutoff", "EVENT_TIME_AFTER_FEATURE_CUTOFF"),
        ("feature_cutoff", "generated_at", "FEATURE_CUTOFF_AFTER_GENERATED_AT"),
        ("generated_at", "available_at", "GENERATED_AT_AFTER_AVAILABLE_AT"),
    ):
        if earlier in parsed and later in parsed and parsed[earlier] > parsed[later]:
            reasons.append(reason)
    return sorted(set(reasons))
