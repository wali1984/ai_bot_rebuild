"""CoinGlass Redis publisher for endpoint payloads and feature rows."""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

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
REFRESH_DIAGNOSTIC_FIELDS = frozenset(
    {
        "first_observed_at",
        "last_observed_at",
        "last_observed_source_age_seconds",
        "duplicate_refresh_count",
        "deduplicated_refresh",
    }
)


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
    now = _now()
    now_dt = _parse_utc(now) or datetime.now(UTC)
    normalized = normalize_coinglass_payload(
        spec=spec,
        symbol=symbol,
        payload=payload,
        observed_at=now,
    )
    status = _status_from_response(http_status=http_status, error_class=error_class)
    actual = (
        normalized["actual_payload_present"] is True
        and normalized.get("temporal_contract_valid") is True
        and status == "READY"
    )
    freshness_deadline = _freshness_deadline(
        normalized,
        spec=spec,
        observed_at=now_dt,
    )
    if actual and spec.source_interval and (
        freshness_deadline is None or freshness_deadline <= now_dt
    ):
        actual = False
    admitted_ttl_seconds = (
        _remaining_seconds(freshness_deadline, observed_at=now_dt)
        if spec.source_interval
        else spec.ttl_seconds
    )
    feature_observation_hash = (
        _feature_observation_hash(
            endpoint_id=spec.endpoint_id,
            symbol=symbol,
            source_interval=normalized.get("source_interval"),
            feature_cutoff=normalized.get("feature_cutoff"),
            features=normalized.get("features"),
        )
        if actual
        else None
    )
    envelope = {
        **normalized,
        "timeframe": timeframe,
        "actual_payload_present": actual,
        "heartbeat_only": not actual,
        "available_at": now,
        "ingested_at": now,
        "generated_at": now,
        "first_observed_at": now,
        "last_observed_at": now,
        "last_observed_source_age_seconds": normalized.get("source_age_seconds"),
        "duplicate_refresh_count": 0,
        "deduplicated_refresh": False,
        "feature_observation_hash": feature_observation_hash,
        "expires_at": _iso_utc(freshness_deadline),
        "ttl_seconds": admitted_ttl_seconds,
        "stale_after": admitted_ttl_seconds,
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
    admitted_envelope = dict(envelope)
    if redis_client is not None:
        raw_key_template = RAW_KEY_BY_GROUP.get(spec.group)
        if raw_key_template:
            key = raw_key_template.format(symbol=symbol)
            raw_ttl = _raw_ttl_seconds(
                admitted_envelope,
                spec=spec,
                observed_at=now_dt,
            )
            if actual and raw_ttl is not None:
                admitted_envelope = _deduplicate_raw_envelope(
                    redis_client,
                    key,
                    envelope=admitted_envelope,
                    observed_at=now,
                )
                _set_json(
                    redis_client,
                    key,
                    admitted_envelope,
                    ex=raw_ttl,
                    expires_at=freshness_deadline if spec.source_interval else None,
                )
                keys_written.append(key)
            elif not spec.source_interval:
                _set_json(redis_client, key, admitted_envelope, ex=spec.ttl_seconds)
                keys_written.append(key)
        feature_key = f"v2:features:coinglass:{symbol}:{timeframe}"
        feature_payload, feature_ttl = _merge_feature_payload(
            redis_client,
            feature_key,
            envelope=admitted_envelope,
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
            "dashboard_color": admitted_envelope["dashboard_color"],
            "generated_utc": now,
            "feature_cutoff": admitted_envelope.get("feature_cutoff"),
            "feature_observation_hash": admitted_envelope.get(
                "feature_observation_hash"
            ),
            "source_interval": admitted_envelope.get("source_interval"),
            "bar_open": admitted_envelope.get("bar_open"),
            "bar_close": admitted_envelope.get("bar_close"),
            "is_closed": admitted_envelope.get("is_closed"),
            "source_age_seconds": admitted_envelope.get("source_age_seconds"),
            "max_source_age_seconds": admitted_envelope.get(
                "max_source_age_seconds"
            ),
            "source_fresh": admitted_envelope.get("source_fresh"),
            "history_row_admission": admitted_envelope.get(
                "history_row_admission"
            ),
            "temporal_contract_valid": admitted_envelope.get(
                "temporal_contract_valid"
            ),
            "first_observed_at": admitted_envelope.get("first_observed_at"),
            "last_observed_at": admitted_envelope.get("last_observed_at"),
            "duplicate_refresh_count": admitted_envelope.get(
                "duplicate_refresh_count"
            ),
            "deduplicated_refresh": admitted_envelope.get(
                "deduplicated_refresh"
            ),
            "expires_at": admitted_envelope.get("expires_at"),
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
                "enabled": str(env.get("COINGLASS_ENABLED", "1")).lower()
                not in {"0", "false", "no"},
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
        "feature_observation_hash": admitted_envelope.get(
            "feature_observation_hash"
        ),
        "last_observed_at": admitted_envelope.get("last_observed_at"),
        "duplicate_refresh_count": admitted_envelope.get(
            "duplicate_refresh_count"
        ),
        "deduplicated_refresh": admitted_envelope.get("deduplicated_refresh"),
        "keys_written": keys_written,
        "core_system_blocked": False,
        "raw_key_exposed": False,
    }


def _set_json(
    redis_client: Any,
    key: str,
    payload: Mapping[str, Any],
    *,
    ex: int,
    expires_at: datetime | None = None,
) -> None:
    encoded = json.dumps(dict(payload), sort_keys=True, default=str)
    if expires_at is not None:
        try:
            redis_client.set(key, encoded, exat=int(expires_at.timestamp()))
            return
        except TypeError:
            # Lightweight test doubles and older Redis wrappers may only
            # support relative EX; the floored fallback never exceeds by a
            # whole second.
            pass
    redis_client.set(key, encoded, ex=ex)


def _deduplicate_raw_envelope(
    redis_client: Any,
    key: str,
    *,
    envelope: Mapping[str, Any],
    observed_at: str,
) -> dict[str, Any]:
    candidate = dict(envelope)
    try:
        raw = redis_client.get(key)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        existing = json.loads(str(raw)) if raw else None
    except Exception:
        existing = None
    if isinstance(existing, Mapping) and _same_feature_observation(
        existing,
        candidate,
    ):
        return _preserve_duplicate_lineage(
            existing,
            candidate,
            observed_at=observed_at,
        )
    return candidate


def _preserve_duplicate_lineage(
    existing: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    observed_at: str,
) -> dict[str, Any]:
    deduplicated = dict(candidate)
    last_observed_source_age = deduplicated.get(
        "last_observed_source_age_seconds",
        deduplicated.get("source_age_seconds"),
    )
    for field in (
        "event_time",
        "available_at",
        "ingested_at",
        "generated_at",
        "source_age_seconds",
        "ttl_seconds",
        "stale_after",
    ):
        if existing.get(field) is not None:
            deduplicated[field] = existing.get(field)
    existing_refresh_count = _nonnegative_int(
        existing.get("duplicate_refresh_count")
    )
    candidate_refresh_count = _nonnegative_int(
        candidate.get("duplicate_refresh_count")
    )
    deduplicated.update(
        {
            "first_observed_at": (
                existing.get("first_observed_at")
                or existing.get("available_at")
                or candidate.get("first_observed_at")
            ),
            "last_observed_at": observed_at,
            "last_observed_source_age_seconds": last_observed_source_age,
            "duplicate_refresh_count": max(
                candidate_refresh_count,
                existing_refresh_count + 1,
            ),
            "deduplicated_refresh": True,
        }
    )
    return deduplicated


def _same_feature_observation(
    existing: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> bool:
    candidate_hash = candidate.get("feature_observation_hash")
    return bool(candidate_hash) and all(
        (
            str(existing.get("endpoint_id") or "")
            == str(candidate.get("endpoint_id") or ""),
            str(existing.get("symbol") or "") == str(candidate.get("symbol") or ""),
            str(existing.get("source_interval") or "")
            == str(candidate.get("source_interval") or ""),
            str(existing.get("feature_cutoff") or "")
            == str(candidate.get("feature_cutoff") or ""),
            _canonical_features(existing.get("features"))
            == _canonical_features(candidate.get("features")),
        )
    )


def _feature_observation_hash(
    *,
    endpoint_id: str,
    symbol: str,
    source_interval: Any,
    feature_cutoff: Any,
    features: Any,
) -> str | None:
    canonical_features = _canonical_features(features)
    if not feature_cutoff or not canonical_features:
        return None
    material = {
        "endpoint_id": str(endpoint_id),
        "symbol": str(symbol).upper(),
        "source_interval": str(source_interval or ""),
        "feature_cutoff": str(feature_cutoff),
        "features": canonical_features,
    }
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _mapping_hash(value: Mapping[str, Any]) -> str | None:
    if not value:
        return None
    encoded = json.dumps(
        dict(value),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_features(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    features: dict[str, float] = {}
    for name, raw in value.items():
        parsed = _finite_float(raw)
        if parsed is not None:
            features[str(name)] = parsed
    return features


def _freshness_deadline(
    payload: Mapping[str, Any],
    *,
    spec: CoinGlassEndpointSpec,
    observed_at: datetime,
) -> datetime | None:
    if not spec.source_interval:
        return observed_at + timedelta(seconds=spec.ttl_seconds)
    bar_close = _parse_utc(payload.get("bar_close"))
    max_source_age_seconds = _finite_float(payload.get("max_source_age_seconds"))
    if (
        bar_close is None
        or max_source_age_seconds is None
        or max_source_age_seconds <= 0.0
    ):
        return None
    return bar_close + timedelta(seconds=max_source_age_seconds)


def _raw_ttl_seconds(
    payload: Mapping[str, Any],
    *,
    spec: CoinGlassEndpointSpec,
    observed_at: datetime,
) -> int | None:
    if not spec.source_interval:
        return spec.ttl_seconds
    deadline = _parse_utc(payload.get("expires_at"))
    return _remaining_seconds(deadline, observed_at=observed_at)


def _remaining_seconds(
    deadline: datetime | None,
    *,
    observed_at: datetime,
) -> int | None:
    if deadline is None:
        return None
    remaining = math.floor((deadline - observed_at).total_seconds())
    return remaining if remaining > 0 else None


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _feature_bridge_status(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw_features = payload.get("features")
    features: Mapping[str, Any] = raw_features if isinstance(raw_features, Mapping) else {}
    feature_count = len(features)
    actual = (
        bool(payload.get("actual_payload_present"))
        and payload.get("decision_time_safe") is True
        and feature_count > 0
    )
    return {
        "schema_version": "coinglass_feature_bridge_status_v1",
        "provider": "coinglass",
        "generated_utc": payload.get("generated_at") or payload.get("available_at"),
        "symbol": payload.get("symbol"),
        "timeframe": payload.get("timeframe"),
        "available_at": payload.get("available_at"),
        "feature_cutoff": payload.get("feature_cutoff"),
        "feature_observation_hash": payload.get("feature_observation_hash"),
        "feature_observation_hashes": payload.get("feature_observation_hashes") or {},
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
    prior_payload: dict[str, Any] | None = None
    endpoint_payloads_changed = False
    now_dt = _parse_utc(now) or datetime.now(UTC)
    try:
        raw = redis_client.get(key)
        if raw:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            prior = json.loads(str(raw))
            if isinstance(prior, Mapping):
                prior_payload = dict(prior)
            prior_endpoints = prior.get("endpoint_payloads") if isinstance(prior, Mapping) else {}
            if isinstance(prior_endpoints, Mapping):
                for endpoint_id, row in prior_endpoints.items():
                    if not isinstance(row, Mapping):
                        endpoint_payloads_changed = True
                        continue
                    expires_at = _parse_utc(row.get("expires_at"))
                    if expires_at is None or expires_at <= now_dt:
                        stale_families.add(str(endpoint_id))
                        endpoint_payloads_changed = True
                        continue
                    if not _temporal_evidence_safe(row, decision_time=now_dt):
                        stale_families.add(str(endpoint_id))
                        endpoint_payloads_changed = True
                        continue
                    endpoint_payloads[str(endpoint_id)] = dict(row)
    except Exception:
        endpoint_payloads = {}

    if actual:
        expires_at = _parse_utc(envelope.get("expires_at")) or (
            now_dt + timedelta(seconds=spec.ttl_seconds)
        )
        candidate_endpoint_payload = {
            "endpoint_id": spec.endpoint_id,
            "feature_family": spec.group,
            "symbol": envelope.get("symbol"),
            "features": dict(envelope.get("features") or {}),
            "event_time": envelope.get("event_time"),
            "available_at": envelope.get("available_at"),
            "ingested_at": envelope.get("ingested_at"),
            "generated_at": envelope.get("generated_at"),
            "feature_cutoff": envelope.get("feature_cutoff"),
            "feature_observation_hash": envelope.get("feature_observation_hash"),
            "source_interval": envelope.get("source_interval"),
            "bar_open": envelope.get("bar_open"),
            "bar_close": envelope.get("bar_close"),
            "is_closed": envelope.get("is_closed"),
            "source_age_seconds": envelope.get("source_age_seconds"),
            "max_source_age_seconds": envelope.get("max_source_age_seconds"),
            "source_fresh": envelope.get("source_fresh"),
            "temporal_contract_valid": envelope.get("temporal_contract_valid"),
            "history_row_admission": envelope.get("history_row_admission"),
            "expires_at": expires_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "actual_payload_present": True,
            "status": status,
            "ttl_seconds": envelope.get("ttl_seconds"),
        }
        existing_endpoint_payload = endpoint_payloads.get(spec.endpoint_id)
        if existing_endpoint_payload is not None and _same_feature_observation(
            existing_endpoint_payload,
            candidate_endpoint_payload,
        ) and (
            existing_endpoint_payload.get("feature_observation_hash")
            == candidate_endpoint_payload.get("feature_observation_hash")
        ):
            candidate_endpoint_payload = dict(existing_endpoint_payload)
        else:
            endpoint_payloads_changed = True
        endpoint_payloads[spec.endpoint_id] = candidate_endpoint_payload

    merged_features: dict[str, float] = {}
    active_expires: list[datetime] = []
    event_times: list[str] = []
    available_times: list[str] = []
    ingested_times: list[str] = []
    generated_times: list[str] = []
    feature_cutoffs: list[str] = []
    source_intervals: dict[str, str] = {}
    feature_observation_hashes: dict[str, str] = {}
    for row in endpoint_payloads.values():
        if not _temporal_evidence_safe(row, decision_time=now_dt):
            continue
        features = row.get("features") if isinstance(row.get("features"), Mapping) else {}
        for name, value in features.items():
            try:
                parsed = float(value)
                if math.isfinite(parsed):
                    merged_features[str(name)] = parsed
            except (TypeError, ValueError):
                continue
        expires_at = _parse_utc(row.get("expires_at"))
        if expires_at is not None:
            active_expires.append(expires_at)
        if row.get("event_time"):
            event_times.append(str(row.get("event_time")))
        if row.get("available_at"):
            available_times.append(str(row.get("available_at")))
        if row.get("ingested_at"):
            ingested_times.append(str(row.get("ingested_at")))
        if row.get("generated_at"):
            generated_times.append(str(row.get("generated_at")))
        if row.get("feature_cutoff"):
            feature_cutoffs.append(str(row.get("feature_cutoff")))
        if row.get("source_interval"):
            source_intervals[str(row.get("endpoint_id"))] = str(row.get("source_interval"))
        if row.get("feature_observation_hash"):
            feature_observation_hashes[str(row.get("endpoint_id"))] = str(
                row.get("feature_observation_hash")
            )

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
    decision_time_safe = aggregate_actual and all(
        _temporal_evidence_safe(row, decision_time=now_dt)
        for row in endpoint_payloads.values()
    )
    ttl = spec.ttl_seconds
    if active_expires:
        # Keep the aggregate alive until the LAST family expires; per-row
        # expires_at pruning above already drops stale families on read.
        # Expiring at the soonest family made the whole key flap every time
        # a short-TTL family (60s trades/orderbook) lapsed between cadenced
        # refreshes, so consumers saw MISSING while funding/OI were valid.
        ttl = max(1, int((max(active_expires) - now_dt).total_seconds()))
    if (
        prior_payload is not None
        and not endpoint_payloads_changed
        and prior_payload.get("disabled_endpoints") == disabled_endpoints
    ):
        return prior_payload, ttl
    aggregate_status = "READY" if aggregate_actual else status
    aggregate_envelope = {
        key: value
        for key, value in envelope.items()
        if key not in REFRESH_DIAGNOSTIC_FIELDS
    }
    payload = {
        **aggregate_envelope,
        "schema_version": "coinglass_aggregated_feature_payload_v2",
        "endpoint_id": "coinglass_aggregate",
        "feature_family": "coinglass_aggregate",
        "event_time": max(event_times) if event_times else envelope.get("event_time"),
        "available_at": max(available_times) if available_times else envelope.get("available_at"),
        "ingested_at": max(ingested_times) if ingested_times else envelope.get("ingested_at"),
        "generated_at": max(generated_times) if generated_times else envelope.get("generated_at"),
        "feature_cutoff": (
            max(feature_cutoffs)
            if feature_cutoffs
            else envelope.get("feature_cutoff")
        ),
        "timeframe": envelope.get("timeframe"),
        "source_intervals": source_intervals,
        "feature_observation_hash": _mapping_hash(feature_observation_hashes),
        "feature_observation_hashes": feature_observation_hashes,
        "features": merged_features,
        "endpoint_payloads": endpoint_payloads,
        "actual_payload_endpoint_count": len(endpoint_payloads),
        "source_endpoint_count": len(endpoint_payloads),
        "missing_feature_flags": sorted(missing_flags),
        "stale_feature_flags": sorted(stale_flags),
        "disabled_endpoints": disabled_endpoints,
        "decision_time_safe": decision_time_safe,
        "temporal_contract_valid": decision_time_safe,
        "actual_payload_present": aggregate_actual and decision_time_safe,
        "heartbeat_only": not (aggregate_actual and decision_time_safe),
        "provider_ready": aggregate_actual and decision_time_safe,
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
    raw_endpoints = existing.get("endpoints")
    endpoints: dict[str, Any] = (
        dict(raw_endpoints) if isinstance(raw_endpoints, Mapping) else {}
    )
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
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


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


def _temporal_evidence_safe(
    row: Mapping[str, Any],
    *,
    decision_time: datetime,
) -> bool:
    if row.get("actual_payload_present") is not True:
        return False
    if row.get("temporal_contract_valid") is not True:
        return False
    available_at = _parse_utc(row.get("available_at"))
    feature_cutoff = _parse_utc(row.get("feature_cutoff"))
    if available_at is None or feature_cutoff is None:
        return False
    if available_at > decision_time or feature_cutoff > available_at:
        return False
    if not row.get("source_interval"):
        return True
    if row.get("is_closed") is not True:
        return False
    bar_open = _parse_utc(row.get("bar_open"))
    bar_close = _parse_utc(row.get("bar_close"))
    if bar_open is None or bar_close is None:
        return False
    source_age_seconds = _finite_float(row.get("source_age_seconds"))
    max_source_age_seconds = _finite_float(row.get("max_source_age_seconds"))
    effective_source_age_seconds = (decision_time - bar_close).total_seconds()
    reported_source_age_seconds = (available_at - bar_close).total_seconds()
    if (
        row.get("source_fresh") is not True
        or source_age_seconds is None
        or max_source_age_seconds is None
        or source_age_seconds < 0.0
        or max_source_age_seconds <= 0.0
        or abs(source_age_seconds - reported_source_age_seconds) > 1.0
        or effective_source_age_seconds < 0.0
        or effective_source_age_seconds > max_source_age_seconds
        or source_age_seconds > max_source_age_seconds
    ):
        return False
    return bar_open < bar_close and bar_close == feature_cutoff and bar_close <= available_at


def _finite_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
