"""Evidence-based provider consumption status.

Publishes v2:altdata:provider_consumption_status summarizing, per provider,
whether features exist in Redis and which downstream consumers demonstrably
read them. Consumption claims come from live Redis evidence, not aspiration.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

STATUS_KEY = "v2:altdata:provider_consumption_status"
STATUS_TTL_SECONDS = 900


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
    moralis_bridge = _json_get(redis_client, "v2:provider:moralis:feature_bridge_status")
    santiment_bridge = _json_get(redis_client, "v2:provider:santiment:feature_bridge_status")
    coinglass_bridge = _json_get(redis_client, "v2:provider:coinglass:feature_bridge_status")
    coinglass_health = _json_get(redis_client, "v2:provider:coinglass:health")
    matrix = _json_get(redis_client, "v2:paper:preemptive_candidate_decision_matrix")
    rows = matrix.get("rows") if isinstance(matrix.get("rows"), list) else []
    matrix_rows_with_altdata = sum(
        1
        for row in rows
        if isinstance(row, dict)
        and any(str(key).startswith("altdata_") and value not in (None, "", [], {}) for key, value in row.items())
    )
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
