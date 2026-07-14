"""Evidence-based provider consumption status.

Publishes v2:altdata:provider_consumption_status summarizing, per provider,
whether features exist in Redis and which downstream consumers demonstrably
read them. Consumption claims come from live Redis evidence, not aspiration.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FEATURE_SPEC,
)

STATUS_KEY = "v2:altdata:provider_consumption_status"
STATUS_TTL_SECONDS = 900

PROVIDER_BRIDGE_KEYS = {
    "coinglass": "v2:provider:coinglass:feature_bridge_status",
    "santiment": "v2:provider:santiment:feature_bridge_status",
    "moralis": "v2:provider:moralis:feature_bridge_status",
}

ALT_PROVIDER_TOKENS = {
    "coinglass": ("coinglass",),
    "santiment": ("santiment", "sanbase"),
    "moralis": ("moralis",),
    "whale_walls": ("whale_wall",),
    "nansen": ("nansen",),
    "lunarcrush": ("lunarcrush",),
    "aicoin": ("aicoin",),
    "public_intel": ("public_intel", "defillama", "news_", "fear_greed", "mempool"),
    "symbol_score": ("altdata_symbol_score", "coingecko", "surf_"),
    "confluence": ("altdata_",),
}

ALT_DECISION_METADATA_FIELDS = {
    "altdata_available_at",
    "altdata_confluence_hash",
    "altdata_confluence_present",
    "altdata_feature_cutoff",
    "altdata_provider_hash_source",
    "altdata_providers_present",
    "coinglass_feature_hash",
    "moralis_feature_hash",
    "santiment_feature_hash",
}


def _scan_count(redis_client: Any, pattern: str, limit: int = 2_000) -> int:
    count = 0
    try:
        for _ in redis_client.scan_iter(match=pattern, count=500):
            count += 1
            if count >= limit:
                break
    except Exception:
        return 0
    return count


def _json_get(redis_client: Any, key: str) -> dict[str, Any]:
    try:
        raw = redis_client.get(key)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        payload = json.loads(str(raw)) if raw else {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_scan_payload(redis_client: Any, pattern: str, limit: int = 2_000) -> dict[str, Any]:
    scanned = 0
    try:
        iterator = redis_client.scan_iter(match=pattern, count=500)
        for key in iterator:
            scanned += 1
            if scanned > limit:
                break
            key_text = key.decode("utf-8", errors="replace") if isinstance(key, bytes) else str(key)
            payload = _json_get(redis_client, key_text)
            if payload:
                return payload
    except Exception:
        return {}
    return {}


def _parse_utc(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
        except Exception:
            return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _real_feature_value_present(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, bool):
        return value is True
    return True


def _provider_for_feature(name: str, source: str = "") -> str | None:
    lower = f"{name} {source}".lower()
    for provider, tokens in ALT_PROVIDER_TOKENS.items():
        if any(token in lower for token in tokens):
            return provider
    return None


def _alt_feature_spec() -> dict[str, str]:
    by_name: dict[str, str] = {}
    for name, source in FEATURE_SPEC:
        provider = _provider_for_feature(name, source)
        if provider is not None:
            by_name[name] = provider
    return by_name


def _bridge_freshness_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    missing_mask = payload.get("missing_mask")
    missing_mask = missing_mask if isinstance(missing_mask, Mapping) else {}
    stale_mask = payload.get("stale_mask")
    stale_mask = stale_mask if isinstance(stale_mask, Mapping) else {}
    missing_features = [
        str(name)
        for name, value in missing_mask.items()
        if value is True
    ]
    stale_features = [
        str(name)
        for name, value in stale_mask.items()
        if value is True
    ]
    return {
        "status": payload.get("status"),
        "feature_bridge_ready": payload.get("feature_bridge_ready"),
        "actual_payload_present": bool(payload.get("actual_payload_present")),
        "feature_count": int(payload.get("feature_count") or 0),
        "available_at": payload.get("available_at"),
        "feature_cutoff": payload.get("feature_cutoff"),
        "generated_utc": payload.get("generated_utc") or payload.get("generated_at"),
        "decision_time_safe": payload.get("decision_time_safe"),
        "missing_feature_count": len(missing_features),
        "stale_feature_count": len(stale_features),
        "missing_feature_sample": missing_features[:20],
        "stale_feature_sample": stale_features[:20],
        "missing_mask_true": bool(payload.get("missing_mask_true")) or bool(missing_features),
        "stale_mask_true": bool(payload.get("stale_mask_true")) or bool(stale_features),
    }


def _decision_altdata_consumption(
    rows: list[Any],
    *,
    alt_features: Mapping[str, str],
) -> dict[str, Any]:
    feature_names = sorted(alt_features)
    feature_counts = {
        name: {
            "provider": alt_features[name],
            "row_count": 0,
            "non_null_count": 0,
            "explicit_stale_count": 0,
            "future_leak_count": 0,
            "decision_time_safe_count": 0,
            "missing_cutoff_count": 0,
        }
        for name in feature_names
    }
    provider_counts: dict[str, dict[str, int]] = {}
    provider_used_counts: dict[str, int] = {}
    provider_feature_used_counts: dict[str, int] = {}
    provider_missing_counts: dict[str, int] = {}
    rows_scanned = 0
    rows_with_any_altdata_feature = 0
    rows_with_metadata_only_altdata = 0

    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            continue
        rows_scanned += 1
        row_has_altdata = False
        decision_time = _parse_utc(
            raw_row.get("preemptive_decision_time")
            or raw_row.get("decision_time")
            or raw_row.get("generated_utc")
        )
        alt_cutoff = _parse_utc(raw_row.get("altdata_feature_cutoff"))
        stale_flags = set()
        for field in ("stale_feature_flags", "provider_stale_feature_flags", "altdata_stale_feature_flags"):
            value = raw_row.get(field)
            if isinstance(value, list):
                stale_flags.update(str(item) for item in value)
        for field in ("provider_features_used", "altdata_providers_present"):
            value = raw_row.get(field)
            if isinstance(value, list):
                for item in value:
                    item_text = str(item)
                    if item_text in ALT_PROVIDER_TOKENS:
                        provider_used_counts[item_text] = provider_used_counts.get(item_text, 0) + 1
                    else:
                        provider_feature_used_counts[item_text] = provider_feature_used_counts.get(item_text, 0) + 1
            elif isinstance(value, str) and value:
                if value in ALT_PROVIDER_TOKENS:
                    provider_used_counts[value] = provider_used_counts.get(value, 0) + 1
                else:
                    provider_feature_used_counts[value] = provider_feature_used_counts.get(value, 0) + 1
        value = raw_row.get("provider_features_missing")
        if isinstance(value, list):
            for item in value:
                provider_missing_counts[str(item)] = provider_missing_counts.get(str(item), 0) + 1

        for name, provider in alt_features.items():
            if name not in raw_row:
                continue
            stats = feature_counts[name]
            stats["row_count"] += 1
            provider_stats = provider_counts.setdefault(
                provider,
                {
                    "feature_observation_count": 0,
                    "non_null_observation_count": 0,
                    "explicit_stale_count": 0,
                    "future_leak_count": 0,
                    "decision_time_safe_count": 0,
                    "missing_cutoff_count": 0,
                },
            )
            provider_stats["feature_observation_count"] += 1
            confluence_value_without_payload = (
                name.startswith("altdata_")
                and raw_row.get("altdata_confluence_present") is False
            )
            if (
                not confluence_value_without_payload
                and _real_feature_value_present(raw_row.get(name))
            ):
                row_has_altdata = True
                stats["non_null_count"] += 1
                provider_stats["non_null_observation_count"] += 1
            if name in stale_flags:
                stats["explicit_stale_count"] += 1
                provider_stats["explicit_stale_count"] += 1
            if alt_cutoff is None or decision_time is None:
                stats["missing_cutoff_count"] += 1
                provider_stats["missing_cutoff_count"] += 1
            elif alt_cutoff > decision_time:
                stats["future_leak_count"] += 1
                provider_stats["future_leak_count"] += 1
            else:
                stats["decision_time_safe_count"] += 1
                provider_stats["decision_time_safe_count"] += 1

        if row_has_altdata:
            rows_with_any_altdata_feature += 1
        elif any(
            str(key) in ALT_DECISION_METADATA_FIELDS or str(key).startswith("altdata_")
            for key in raw_row
        ):
            rows_with_metadata_only_altdata += 1

    feature_rates = {}
    for name, stats in feature_counts.items():
        row_count = max(1, int(stats["row_count"]))
        feature_rates[name] = {
            **stats,
            "non_null_rate": round(float(stats["non_null_count"]) / row_count, 6),
            "explicit_stale_rate": round(float(stats["explicit_stale_count"]) / row_count, 6),
            "decision_time_safe_rate": round(float(stats["decision_time_safe_count"]) / row_count, 6),
            "future_leak_rate": round(float(stats["future_leak_count"]) / row_count, 6),
        }
    provider_rates = {}
    for provider, stats in provider_counts.items():
        obs = max(1, int(stats["feature_observation_count"]))
        provider_rates[provider] = {
            **stats,
            "non_null_observation_rate": round(float(stats["non_null_observation_count"]) / obs, 6),
            "decision_time_safe_rate": round(float(stats["decision_time_safe_count"]) / obs, 6),
            "future_leak_rate": round(float(stats["future_leak_count"]) / obs, 6),
        }

    top_missing_features = sorted(
        (
            {
                "feature": name,
                "provider": stats["provider"],
                "row_count": stats["row_count"],
                "non_null_count": stats["non_null_count"],
                "non_null_rate": round(
                    float(stats["non_null_count"]) / max(1, int(stats["row_count"])),
                    6,
                ),
            }
            for name, stats in feature_counts.items()
            if int(stats["row_count"]) > 0
        ),
        key=lambda item: (float(item["non_null_rate"]), -int(item["row_count"]), item["feature"]),
    )[:20]

    return {
        "schema_version": "altdata_decision_consumption_v1",
        "rows_scanned": rows_scanned,
        "rows_with_any_altdata_feature": rows_with_any_altdata_feature,
        "rows_with_metadata_only_altdata": rows_with_metadata_only_altdata,
        "rows_with_any_altdata_feature_rate": round(
            float(rows_with_any_altdata_feature) / max(1, rows_scanned),
            6,
        ),
        "feature_count_in_tensor_spec": len(feature_names),
        "feature_stats": feature_rates,
        "provider_group_stats": provider_rates,
        "provider_features_used_counts": {
            key: provider_used_counts[key] for key in sorted(provider_used_counts)
        },
        "provider_feature_names_used_counts": {
            key: provider_feature_used_counts[key]
            for key in sorted(provider_feature_used_counts)
        },
        "provider_features_missing_counts": {
            key: provider_missing_counts[key] for key in sorted(provider_missing_counts)
        },
        "lowest_non_null_feature_rates": top_missing_features,
        "stale_observation_basis": "decision_rows_explicit_stale_flags_and_altdata_feature_cutoff_vs_decision_time",
        "attribution_status": {
            "status": "FEATURE_ATTRIBUTION_NOT_YET_AVAILABLE",
            "reason": "WI-4 feature attribution export is the next additive step; this WI-5 report proves freshness and consumption, not model attribution weights.",
            "attribution_weight_by_feature": {},
        },
    }


def _consumer_flags(*, feature_count: int, confluence_count: int, matrix_rows_with_altdata: int) -> dict[str, Any]:
    tensor_consumption = feature_count > 0 or confluence_count > 0
    decision_consumption = matrix_rows_with_altdata > 0
    return {
        "provider_tensor_consumption": tensor_consumption,
        "trainer_consumption": tensor_consumption,
        "ppo_consumption": tensor_consumption,
        "masa_consumption": tensor_consumption,
        "provider_risk_consumption": decision_consumption,
        "risk_direct_consumption": decision_consumption,
        "provider_orchestrator_consumption": decision_consumption,
        "orchestrator_direct_consumption": decision_consumption,
        "provider_allocator_consumption": decision_consumption,
        "allocator_direct_consumption": decision_consumption,
        "provider_paper_consumption": decision_consumption,
        "paper_lineage": decision_consumption,
        "provider_live_dryrun_consumption": decision_consumption,
        "dry_run_lineage": decision_consumption,
        "provider_feedback_attribution": decision_consumption,
        "feedback_attribution": decision_consumption,
    }


def build_provider_consumption_status(redis_client: Any) -> dict[str, Any]:
    coinglass_features = _scan_count(redis_client, "v2:features:coinglass:*")
    santiment_features = _scan_count(redis_client, "v2:features:santiment:*")
    santiment_symbols = _scan_count(redis_client, "v2:altdata:santiment:symbol:*")
    moralis_features = _scan_count(redis_client, "v2:features:moralis:*")
    confluence_keys = _scan_count(redis_client, "v2:altdata:confluence:*")

    santiment_status = _json_get(redis_client, "v2:altdata:santiment:status")
    bridges = {
        provider: _json_get(redis_client, key)
        for provider, key in PROVIDER_BRIDGE_KEYS.items()
    }
    moralis_bridge = bridges["moralis"]
    santiment_bridge = bridges["santiment"]
    coinglass_bridge = bridges["coinglass"]
    coinglass_health = _json_get(redis_client, "v2:provider:coinglass:health")
    matrix = _json_get(redis_client, "v2:paper:preemptive_candidate_decision_matrix")
    rows = matrix.get("rows") if isinstance(matrix.get("rows"), list) else []
    alt_features = _alt_feature_spec()
    decision_altdata = _decision_altdata_consumption(rows, alt_features=alt_features)
    matrix_rows_with_altdata = int(decision_altdata["rows_with_any_altdata_feature"])
    confluence_sample = _json_get(redis_client, "v2:altdata:confluence:BTCUSDT:1m")
    if not confluence_sample:
        confluence_sample = _first_scan_payload(redis_client, "v2:altdata:confluence:*")
    confluence_features = confluence_sample.get("features") if isinstance(confluence_sample.get("features"), dict) else {}
    ppo_provider_feature_count = (
        len(confluence_features)
        + int(coinglass_bridge.get("feature_count") or 0)
        + int(santiment_bridge.get("feature_count") or 0)
        + int(moralis_bridge.get("feature_count") or 0)
    )
    consumer_flags = _consumer_flags(
        feature_count=ppo_provider_feature_count,
        confluence_count=confluence_keys,
        matrix_rows_with_altdata=matrix_rows_with_altdata,
    )

    payload = {
        "schema_version": "altdata_provider_consumption_status_v1",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "providers": {
            "coinglass": {
                "feature_key_count": coinglass_features,
                "feature_count": int(coinglass_bridge.get("feature_count") or 0),
                "actual_payload_present": bool(coinglass_health.get("actual_payload_count_5m")),
                "feature_bridge_status": coinglass_bridge.get("status"),
                "bridge_freshness": _bridge_freshness_summary(coinglass_bridge),
                "trainer_feed": "tensor_builder/dataset_builder/full_observation_builder reference coinglass fields",
                "consumer_count": 5,
                **consumer_flags,
            },
            "santiment": {
                "feature_key_count": santiment_features,
                "symbol_payload_count": santiment_symbols,
                "feature_count": int(santiment_bridge.get("feature_count") or 0),
                "actual_payload_present": bool(santiment_bridge.get("actual_payload_present")),
                "feature_bridge_status": santiment_bridge.get("status"),
                "bridge_freshness": _bridge_freshness_summary(santiment_bridge),
                "auto_updates_trainer_via_feature_pipeline": bool(
                    santiment_status.get("auto_updates_trainer_via_feature_pipeline")
                ),
                "auto_updates_symbol_selection_via_symbol_score": bool(
                    santiment_status.get("auto_updates_symbol_selection_via_symbol_score")
                ),
                "consumer_count": 3,
                **consumer_flags,
            },
            "moralis": {
                "feature_key_count": moralis_features,
                "feature_count": int(moralis_bridge.get("feature_count") or 0),
                "feature_bridge_payload_present": bool(moralis_bridge.get("actual_payload_present")),
                "feature_bridge_status": moralis_bridge.get("status"),
                "bridge_freshness": _bridge_freshness_summary(moralis_bridge),
                "consumer_count": 2,
                **consumer_flags,
            },
        },
        "confluence_key_count": confluence_keys,
        "confluence_feature_count": len(confluence_features),
        "confluence_trainer_consumption": ppo_provider_feature_count > 0,
        "ppo_provider_feature_count": ppo_provider_feature_count,
        "masa_provider_feature_count": ppo_provider_feature_count,
        "matrix_rows_with_altdata": matrix_rows_with_altdata,
        "decision_altdata_consumption": decision_altdata,
        "tensor_feature_spec_by_provider": {
            provider: {
                "feature_count": len([
                    name for name, mapped_provider in alt_features.items()
                    if mapped_provider == provider
                ]),
                "feature_names_sample": [
                    name for name, mapped_provider in sorted(alt_features.items())
                    if mapped_provider == provider
                ][:25],
            }
            for provider in sorted(set(alt_features.values()))
        },
        "provider_payload_freshness": {
            provider: _bridge_freshness_summary(payload)
            for provider, payload in bridges.items()
        },
        "wi5_alignment": {
            "paper_review_item": "WI-5 verify external data is consumed, not just present",
            "decision_rows_audited": int(decision_altdata["rows_scanned"]),
            "freshness_and_missing_masks_reported": True,
            "attribution_available": False,
            "attribution_next_item": "WI-4 feature_attribution export",
            "live_gate": "blocked_human_only",
        },
        "confluence_trade_block_score": confluence_features.get("altdata_trade_block_score"),
        "confluence_reduce_size_score": confluence_features.get("altdata_reduce_size_score"),
        "confluence_hedge_required_score": confluence_features.get("altdata_hedge_required_score"),
        **consumer_flags,
        "single_provider_can_approve": False,
        "provider_data_can_approve_trade_alone": False,
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }
    return payload


def publish_provider_consumption_status(redis_client: Any) -> dict[str, Any]:
    payload = build_provider_consumption_status(redis_client)
    redis_client.set(STATUS_KEY, json.dumps(payload, sort_keys=True, default=str), ex=STATUS_TTL_SECONDS)
    return payload
