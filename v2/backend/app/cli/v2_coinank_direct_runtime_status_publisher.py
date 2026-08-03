"""CoinAnk direct-runtime status publisher.

Reads direct legacy-owned CoinAnk ingestor keys and writes the current website
payload. This is status publication only: no exchange mutation and no Redis
writes. The actual ingestors are the direct scripts under
``v2/legacy_owned_runtime/ingest``.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

OUT_DIR = Path("v2/frontend/public/operator_runtime/coinank_market_intelligence/latest")
DEFAULT_OUT = OUT_DIR / "coinank_market_intelligence_status.json"

GLOBAL_KEYS = {
    "total_oi": "features:global_coinank:total_oi:latest",
    "total_volume": "features:global_coinank:total_volume:latest",
    "total_liquidations": "features:global_coinank:total_liquidations:latest",
    "long_short_ratio": "features:global_coinank:long_short_ratio:latest",
    "funding_rate_avg": "features:global_coinank:funding_rate_avg:latest",
    "btc_dominance": "features:global_coinank:btc_dominance:latest",
    "eth_dominance": "features:global_coinank:eth_dominance:latest",
    "alt_season_index": "features:global_coinank:alt_season_index:latest",
    "fear_greed": "features:global_coinank:fear_greed:latest",
    "market_sentiment": "features:global_coinank:market_sentiment:latest",
    "volatility_index": "features:global_coinank:volatility_index:latest",
}

INTENTIONALLY_DISABLED_ENDPOINTS = {
    "orderBook_v2_bySymbol": "disabled: price/orderbook is owned by Binance/KuCoin/CoinAPI public market feeds",
    "instruments_getLastPrice": "disabled by default: price is owned by Binance/KuCoin/CoinAPI public market feeds",
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _est_iso() -> str:
    return datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _json(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if raw is None:
        return None
    try:
        return json.loads(str(raw))
    except Exception:
        return None


def _json_get(r, key: str) -> Any:
    if not r:
        return None
    try:
        return _json(r.get(key))
    except Exception:
        return None


def _age_seconds_from_ms(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed > 10_000_000_000:
        parsed /= 1000.0
    return max(0.0, datetime.now(timezone.utc).timestamp() - parsed)


def _float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _global_value(r, key: str) -> tuple[float | None, float | None, dict[str, Any]]:
    payload = _json_get(r, key)
    if isinstance(payload, Mapping):
        value = _float(payload.get("value"))
        age = _age_seconds_from_ms(payload.get("ts_ms") or payload.get("timestamp"))
        return value, age, dict(payload)
    return None, None, {}


def _scan_count(r, pattern: str, limit: int = 100_000) -> int:
    if not r:
        return 0
    count = 0
    try:
        for _ in r.scan_iter(match=pattern, count=1000):
            count += 1
            if count >= limit:
                break
    except Exception:
        return count
    return count


def _call_log_summary(r, *, limit: int = 300, freshness_seconds: int = 900) -> dict[str, Any]:
    if not r:
        return {
            "sample_size": 0,
            "recent_sample_size": 0,
            "recent_success_count": 0,
            "recent_error_count": 0,
            "recent_empty_count": 0,
            "recent_success_endpoints": [],
            "recent_error_examples": [],
        }
    rows: list[dict[str, Any]] = []
    try:
        raw_rows = r.lrange("coinank:call_log", 0, max(0, int(limit) - 1))
    except Exception:
        raw_rows = []
    now_ms = int(time.time() * 1000)
    cutoff_ms = now_ms - max(1, int(freshness_seconds)) * 1000
    for raw in raw_rows:
        parsed = _json(raw)
        if isinstance(parsed, Mapping):
            rows.append(dict(parsed))
    recent = [
        row for row in rows
        if isinstance(row.get("ts"), (int, float)) and float(row.get("ts")) >= cutoff_ms
    ]
    success_rows = [row for row in recent if row.get("status") == "success"]
    error_rows = [row for row in recent if row.get("status") == "error"]
    empty_rows = [row for row in recent if row.get("status") == "empty"]
    return {
        "sample_size": len(rows),
        "recent_sample_size": len(recent),
        "recent_window_seconds": freshness_seconds,
        "recent_success_count": len(success_rows),
        "recent_error_count": len(error_rows),
        "recent_empty_count": len(empty_rows),
        "recent_success_endpoints": sorted({str(row.get("endpoint")) for row in success_rows if row.get("endpoint")}),
        "recent_empty_endpoints": sorted({str(row.get("endpoint")) for row in empty_rows if row.get("endpoint")}),
        "recent_error_examples": [
            {
                "endpoint": str(row.get("endpoint")),
                "status": row.get("status"),
                "code": row.get("code"),
                "params": row.get("params"),
            }
            for row in error_rows[:12]
        ],
    }


def run_once() -> dict[str, Any]:
    r = _connect_redis()
    generated = _utc_iso()
    generated_est = _est_iso()
    heartbeat = _json_get(r, "heartbeat:IngestCoinAnk") if r else None
    metrics = _json_get(r, "coinank:metrics") if r else None
    endpoints = _json_get(r, "coinank:endpoints") if r else None
    runtime = _json_get(r, "coinank:runtime") if r else None

    global_result: dict[str, Any] = {
        "classification": "DIRECT_COINANK_GLOBAL_AGGREGATE_MISSING",
        "source": "direct_legacy_owned_runtime_live_coinank_global_aggregator",
    }
    freshness_values: list[float] = []
    for name, key in GLOBAL_KEYS.items():
        value, age, raw = _global_value(r, key)
        global_result[name] = value
        global_result[f"{name}_source_key"] = key
        if age is not None:
            freshness_values.append(age)
        if raw.get("n") is not None:
            global_result[f"{name}_n"] = raw.get("n")
    if any(global_result.get(name) is not None for name in GLOBAL_KEYS):
        global_result["classification"] = "DIRECT_COINANK_GLOBAL_AGGREGATE_OK"

    endpoints_count = len(endpoints) if isinstance(endpoints, list) else 0
    metrics_count = len(metrics) if isinstance(metrics, Mapping) else 0
    endpoint_success_count = 0
    endpoint_error_count = 0
    endpoint_empty_count = 0
    top_error_endpoints: list[dict[str, Any]] = []
    if isinstance(metrics, Mapping):
        rows: list[tuple[str, int, int, int]] = []
        for name, raw in metrics.items():
            if not isinstance(raw, Mapping):
                continue
            succ = int(_float(raw.get("succ")) or 0)
            err = int(_float(raw.get("err")) or 0)
            empty = int(_float(raw.get("empty")) or 0)
            endpoint_success_count += succ
            endpoint_error_count += err
            endpoint_empty_count += empty
            if err:
                rows.append((str(name), succ, err, empty))
        rows.sort(key=lambda item: item[2], reverse=True)
        top_error_endpoints = [
            {"endpoint": name, "success": succ, "errors": err, "empty": empty}
            for name, succ, err, empty in rows[:12]
        ]
    never_successful_active_endpoints: list[str] = []
    if isinstance(metrics, Mapping):
        for name, raw in metrics.items():
            if name in INTENTIONALLY_DISABLED_ENDPOINTS or not isinstance(raw, Mapping):
                continue
            succ = int(_float(raw.get("succ")) or 0)
            if succ == 0:
                never_successful_active_endpoints.append(str(name))
    latest_count = _scan_count(r, "latest:coinank:*", limit=200_000)
    features_count = _scan_count(r, "features:coinank:*", limit=200_000)
    global_count = _scan_count(r, "features:global_coinank:*", limit=10_000)
    last_update = _json_get(r, "coinank:cycle_complete") or runtime or heartbeat or {}
    last_ts = None
    if isinstance(last_update, Mapping):
        last_ts = last_update.get("ts_ms") or last_update.get("timestamp") or last_update.get("cycle_completed_ts_ms")

    call_log = _call_log_summary(r)
    current_error_count = int(call_log.get("recent_error_count") or 0)
    current_success_count = int(call_log.get("recent_success_count") or 0)
    status_ok = isinstance(heartbeat, Mapping) or global_result["classification"].endswith("_OK")
    api_error_blockers: list[str] = []
    if current_error_count:
        api_error_blockers.append("COINANK_DIRECT_API_CURRENT_ENDPOINT_ERRORS")
    if never_successful_active_endpoints:
        api_error_blockers.append("COINANK_DIRECT_ACTIVE_ENDPOINTS_NEVER_SUCCESSFUL")
    if endpoint_error_count and endpoint_success_count == 0:
        api_error_blockers.append("COINANK_DIRECT_API_ALL_CURRENT_ENDPOINT_CALLS_FAILING")
    elif endpoint_error_count:
        api_error_blockers.append("COINANK_DIRECT_API_HISTORICAL_ENDPOINT_ERRORS")
    if top_error_endpoints:
        api_error_blockers.append("COINANK_DIRECT_HISTORICAL_NON_200_SEE_CALL_LOG")
    classification = "DIRECT_COINANK_RUNTIME_OK"
    if not status_ok:
        classification = "DIRECT_COINANK_RUNTIME_STALE_OR_MISSING"
    elif current_error_count:
        classification = "DIRECT_COINANK_RUNTIME_DEGRADED_API_ERRORS"
    elif never_successful_active_endpoints:
        classification = "DIRECT_COINANK_RUNTIME_PARTIAL_ACTIVE_ENDPOINT_GAPS"
    elif endpoint_error_count:
        classification = "DIRECT_COINANK_RUNTIME_OK_WITH_HISTORICAL_ERRORS"
    payload: dict[str, Any] = {
        "schema_version": "coinank_direct_runtime_status_v1",
        "worker_id": "v2_coinank_direct_runtime_status_publisher",
        "generated_utc": generated,
        "generated_est": generated_est,
        "classification": classification,
        "runtime_mode": "DIRECT_LEGACY_OWNED_COINANK_INGESTORS_NO_V2_BRIDGE_WRAPPER",
        "ingestor_bridge_active": False,
        "direct_ingestor_service": "ai-bot-v2-coinank-live-direct.service",
        "direct_global_aggregator_service": "ai-bot-v2-coinank-global-aggregator-direct.service",
        "source_scripts": [
            "v2/legacy_owned_runtime/ingest/live_coinank.py",
            "v2/legacy_owned_runtime/ingest/live_coinank_global_aggregator.py",
        ],
        "heartbeat_present": isinstance(heartbeat, Mapping),
        "heartbeat_ttl_seconds": r.ttl("heartbeat:IngestCoinAnk") if r else -2,
        "last_update_age_seconds": _age_seconds_from_ms(last_ts),
        "freshness_seconds": min(freshness_values) if freshness_values else _age_seconds_from_ms(last_ts),
        "endpoints_count": endpoints_count,
        "metrics_count": metrics_count,
        "endpoint_success_count": endpoint_success_count,
        "endpoint_error_count": endpoint_error_count,
        "endpoint_empty_count": endpoint_empty_count,
        "current_call_log_health": call_log,
        "current_endpoint_success_count": current_success_count,
        "current_endpoint_error_count": current_error_count,
        "never_successful_active_endpoints": sorted(never_successful_active_endpoints),
        "intentionally_disabled_endpoints": INTENTIONALLY_DISABLED_ENDPOINTS,
        "top_error_endpoints": top_error_endpoints,
        "latest_error_evidence": {
            "redis_key": "coinank:call_log",
            "redacted_error_shape": "status=error code=non_200; stderr currently shows HTTP 401 code -4",
            "raw_credentials_exposed": False,
        },
        "direct_key_counts": {
            "latest_coinank": latest_count,
            "features_coinank": features_count,
            "features_global_coinank": global_count,
        },
        "v2_redis_global_write_enabled": False,
        "direct_legacy_key_write_enabled": True,
        "legacy_key_contract_is_current_source": True,
        "global_aggregate_result": global_result,
        "v2_redis_feature_input": {
            "enabled": True,
            "source": "direct_coinank_legacy_keys",
            "read_key_count": latest_count + features_count + global_count,
            "symbols_requested": None,
            "symbols_with_any_input": None,
        },
        "missing_api_blockers": api_error_blockers if status_ok else ["DIRECT_COINANK_HEARTBEAT_MISSING"],
        "safety": {
            "status_publisher_only": True,
            "real_orders": False,
            "test_order": False,
            "leverage_margin_mutation": False,
            "raw_credentials": False,
        },
    }
    return payload


def write_payload(payload: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_coinank_direct_runtime_status_publisher")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    if args.loop:
        while True:
            payload = run_once()
            write_payload(payload, args.out)
            write_payload(payload, OUT_DIR / "operator_dashboard_payload.json")
            time.sleep(max(5, args.interval_seconds))
    payload = run_once()
    write_payload(payload, args.out)
    write_payload(payload, OUT_DIR / "operator_dashboard_payload.json")
    print(json.dumps({"classification": payload["classification"], "freshness_seconds": payload["freshness_seconds"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
