"""V2 ingestors status publisher — collects live ingestor heartbeats from Redis
and writes a single JSON payload to the public frontend path.

Writes V2 namespace ONLY. No legacy Redis writes. No exchange mutation.
Live gate remains blocked_human_only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

V2_REDIS_PREFIX = "v2:"
PUBLIC_ROOT = Path("v2/frontend/public")
DEFAULT_PAYLOAD_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_ingestors_status/latest/v2_ingestors_status.json"
)
PUBLIC_STATUS_PATHS = {
    "kucoin": PUBLIC_ROOT / "operator_runtime/v2_kucoin_ingestor/latest/v2_kucoin_ingestor_status.json",
    "coinapi_rest": PUBLIC_ROOT
    / "operator_runtime/v2_coinapi_rest_ingestor/latest/v2_coinapi_rest_ingestor_status.json",
    "coinapi_wsds": PUBLIC_ROOT / "operator_runtime/v2_coinapi_wsds/latest/v2_coinapi_wsds_status.json",
    "binance_kline_wss": PUBLIC_ROOT
    / "operator_runtime/v2_binance_kline_wss/latest/v2_binance_kline_wss_status.json",
    "coinank": PUBLIC_ROOT
    / "operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json",
    "liquidation_wss": PUBLIC_ROOT
    / "operator_runtime/v2_liquidation_wss/latest/v2_liquidation_wss_status.json",
    "liquidation_levels": PUBLIC_ROOT
    / "operator_runtime/v2_liquidation_levels_engine/latest/v2_liquidation_levels_engine_status.json",
    "liquidation_runtime": PUBLIC_ROOT
    / "operator_runtime/v2_liquidation_runtime_status/latest/v2_liquidation_runtime_status.json",
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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


def _get_json(r, key: str) -> dict | None:
    try:
        raw = r.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return None


def _read_public_status(name: str) -> dict | None:
    path = PUBLIC_STATUS_PATHS.get(name)
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _mapping(payload: dict | None, key: str) -> dict:
    value = payload.get(key) if isinstance(payload, dict) else None
    return value if isinstance(value, dict) else {}


def _number(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, list):
        return len(value)
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _max_number(*values) -> int:
    nums = [number for number in (_number(value) for value in values) if number is not None]
    return max(nums) if nums else 0


def _first_text(*values) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _payload_symbols_count(payload: dict | None) -> int:
    if not isinstance(payload, dict):
        return 0
    fetch = _mapping(payload, "fetch")
    public_rest_fetch = _mapping(payload, "public_rest_fetch")
    feature_input = _mapping(payload, "v2_redis_feature_input")
    aggregate = _mapping(payload, "global_aggregate_result")
    return _max_number(
        payload.get("symbols"),
        payload.get("symbols_v2"),
        payload.get("symbol_count"),
        payload.get("symbols_count"),
        fetch.get("symbols_requested"),
        fetch.get("symbols_fetched"),
        public_rest_fetch.get("symbols_requested"),
        public_rest_fetch.get("symbols_fetched"),
        feature_input.get("symbols_requested"),
        feature_input.get("symbols_with_any_input"),
        aggregate.get("n_symbols_observed"),
    )


def _payload_keys_written_count(payload: dict | None) -> int:
    if not isinstance(payload, dict):
        return 0
    stats = _mapping(payload, "stats")
    aggregate = _mapping(payload, "global_aggregate_result")
    return _max_number(
        payload.get("v2_market_keys_written"),
        payload.get("v2_features_keys_written"),
        payload.get("v2_redis_keys_written"),
        payload.get("v2_redis_global_keys_written"),
        payload.get("keys_written"),
        payload.get("successful_symbol_count"),
        payload.get("v2_market_keys_written_count"),
        payload.get("v2_features_keys_written_count"),
        payload.get("v2_redis_keys_written_count"),
        payload.get("v2_redis_global_keys_written_count"),
        payload.get("keys_written_count"),
        stats.get("snapshots_written"),
        stats.get("microfeatures_written"),
        stats.get("ohlcv_keys_written"),
        stats.get("source_keys_written"),
        stats.get("messages_received"),
        aggregate.get("v2_keys_written"),
    )


def _payload_generated_utc(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    stats = _mapping(payload, "stats")
    fetch = _mapping(payload, "fetch")
    public_rest_fetch = _mapping(payload, "public_rest_fetch")
    return _first_text(
        payload.get("generated_utc"),
        payload.get("generated_at"),
        payload.get("heartbeat_at"),
        payload.get("last_run_ts"),
        fetch.get("finished_utc"),
        public_rest_fetch.get("finished_utc"),
        stats.get("last_snapshot_utc"),
        stats.get("last_message_utc"),
    )


def _payload_is_recent(payload: dict | None, *, max_age_seconds: int = 900) -> bool:
    generated = _payload_generated_utc(payload)
    if not generated:
        return False
    try:
        parsed = datetime.fromisoformat(generated.replace("Z", "+00:00"))
    except ValueError:
        return False
    age_seconds = (datetime.now(timezone.utc) - parsed).total_seconds()
    return -60 <= age_seconds <= max_age_seconds


def _payload_status(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    if str(payload.get("runtime_mode") or "").startswith("DIRECT_LEGACY_OWNED_COINANK"):
        return _first_text(payload.get("classification"), payload.get("status"))
    if isinstance(payload.get("global_aggregate_result"), dict):
        blockers = payload.get("missing_api_blockers")
        return "V2_COINANK_GLOBAL_AGGREGATE_PARTIAL" if blockers else "V2_COINANK_GLOBAL_AGGREGATE_OK"
    source_counts = payload.get("source_status_counts")
    if isinstance(source_counts, dict) and source_counts:
        source_status = next((str(key) for key in source_counts.keys() if key), "")
        if source_status.startswith("API_PAYMENT_REQUIRED"):
            return f"PROVIDER_PLAN_REQUIRED_{source_status}"
        if source_status.startswith("API_FORBIDDEN"):
            return f"PROVIDER_AUTH_FORBIDDEN_{source_status}"
        if source_status.startswith("API_RATE_LIMIT") or source_status.startswith("API_429"):
            return f"PROVIDER_RATE_LIMITED_{source_status}"
        if source_status:
            return f"PROVIDER_CURRENT_{source_status}"
    return _first_text(payload.get("classification"), payload.get("status"), payload.get("source"), payload.get("current_gate_state"))


def _ingestor_entry(
    name: str,
    service: str,
    heartbeat_key: str,
    status_key: str | None,
    r,
    *,
    control_enabled: bool = True,
    control_group: str = "market_data_ingestor",
    evidence_payloads: list[dict | None] | None = None,
) -> dict:
    hb = _get_json(r, heartbeat_key) if r else None
    evidence = [payload for payload in ([hb] + (evidence_payloads or [])) if isinstance(payload, dict)]
    status_val = r.get(status_key) if (r and status_key) else None
    # For non-string keys (stream, hash, etc.) ttl still works; for missing keys
    # redis returns -2. For keys with no TTL set, returns -1 (treat as stale but
    # present sentinel check via .exists()).
    ttl = r.ttl(heartbeat_key) if (r and heartbeat_key) else -2
    exists = bool(r.exists(heartbeat_key)) if r else False
    active = ttl > 0 or (exists and ttl == -1) or any(_payload_is_recent(payload) for payload in evidence)
    last_generated = None
    if isinstance(hb, dict):
        last_generated = hb.get("finished_at") or hb.get("generated_utc") or hb.get("started_at")
    for payload in evidence:
        last_generated = last_generated or _payload_generated_utc(payload)
    keys_written_count = 0
    for payload in evidence:
        for field in (
            "v2_market_keys_written",
            "v2_features_keys_written",
            "v2_redis_keys_written",
            "v2_redis_global_keys_written",
            "keys_written",
        ):
            value = payload.get(field)
            if isinstance(value, list):
                keys_written_count = max(keys_written_count, len(value))
        for field in (
            "v2_market_keys_written_count",
            "v2_features_keys_written_count",
            "v2_redis_keys_written_count",
            "v2_redis_global_keys_written_count",
            "keys_written_count",
        ):
            try:
                keys_written_count = max(keys_written_count, int(payload.get(field) or 0))
            except (TypeError, ValueError):
                pass
        keys_written_count = max(keys_written_count, _payload_keys_written_count(payload))
    symbols_count = max((_payload_symbols_count(payload) for payload in evidence), default=0)
    worker_id = None
    for payload in evidence:
        worker_id = worker_id or payload.get("worker_id")
    payload_status = None
    status_evidence = [payload for payload in (evidence_payloads or []) if isinstance(payload, dict)]
    if isinstance(hb, dict):
        status_evidence.append(hb)
    for payload in status_evidence:
        payload_status = payload_status or _payload_status(payload)
    return {
        "name": name,
        "service": service,
        "heartbeat_key": heartbeat_key,
        "status": status_val or payload_status or ("ALIVE" if active else "STALE_OR_MISSING"),
        "active": active,
        "heartbeat_ttl_seconds": ttl,
        "last_generated_utc": last_generated,
        "symbols_count": symbols_count,
        "keys_written_count": keys_written_count,
        "worker_id": worker_id,
        "control_enabled": bool(control_enabled),
        "control_group": control_group,
        "allowed_control_actions": ["start", "stop", "restart"] if control_enabled else [],
        "control_endpoint": f"/api/v1/ingestors/{service}/control" if control_enabled else None,
        "runtime_mode": (
            "LIVE_DATA_AND_LIVE_DECISION_INPUTS_TRADER_EXECUTION_DISABLED"
        ),
        "trader_execution_enabled": False,
        "dynamic_symbol_refresh_enabled": True,
    }


def run_once() -> dict:
    r = _connect_redis()
    public_status = {name: _read_public_status(name) for name in PUBLIC_STATUS_PATHS}

    ingestors = [
        _ingestor_entry(
            "Native Ingestors (Binance USDM)",
            "ai-bot-v2-native-ingestors-live-loop.service",
            f"{V2_REDIS_PREFIX}market:ingestor:heartbeat",
            f"{V2_REDIS_PREFIX}market:ingestor:status",
            r,
        ),
        _ingestor_entry(
            "Feature Pipeline (TA + Features)",
            "ai-bot-v2-feature-pipeline-native-loop.service",
            f"{V2_REDIS_PREFIX}features:pipeline:heartbeat",
            None,
            r,
        ),
        _ingestor_entry(
            "Full TA-Lib Compatibility",
            "ai-bot-v2-full-talib-ta-loop.service",
            f"{V2_REDIS_PREFIX}features:ta:heartbeat",
            None,
            r,
        ),
        _ingestor_entry(
            "KuCoin Native Public REST",
            "ai-bot-v2-kucoin-public-rest-loop.service",
            f"{V2_REDIS_PREFIX}market:kucoin:heartbeat",
            None,
            r,
            evidence_payloads=[public_status["kucoin"]],
        ),
        _ingestor_entry(
            "CoinAPI Native OHLCV",
            "ai-bot-v2-coinapi-rest-fallback-loop.service",
            f"{V2_REDIS_PREFIX}market:coinapi:ohlcv:heartbeat",
            None,
            r,
            evidence_payloads=[public_status["coinapi_rest"]],
        ),
        _ingestor_entry(
            "CoinAPI Native REST Orderbook",
            "ai-bot-v2-coinapi-rest-fallback-loop.service",
            f"{V2_REDIS_PREFIX}market:coinapi:rest:heartbeat",
            None,
            r,
            evidence_payloads=[public_status["coinapi_rest"]],
        ),
        _ingestor_entry(
            "CoinAPI Native WSDS",
            "ai-bot-v2-coinapi-wsds-loop.service",
            f"{V2_REDIS_PREFIX}market:coinapi:wsds:heartbeat",
            None,
            r,
            evidence_payloads=[public_status["coinapi_wsds"]],
        ),
        _ingestor_entry(
            "Binance USD-M Kline WSS",
            "ai-bot-v2-binance-kline-wss-loop.service",
            f"{V2_REDIS_PREFIX}market:ohlcv:binance:kline_wss:heartbeat",
            None,
            r,
            evidence_payloads=[public_status["binance_kline_wss"]],
        ),
        _ingestor_entry(
            "CoinAnk Direct Live Ingestor",
            "ai-bot-v2-coinank-live-direct.service",
            "heartbeat:IngestCoinAnk",
            None,
            r,
            evidence_payloads=[public_status["coinank"]],
        ),
        _ingestor_entry(
            "CoinAnk Direct Global Aggregator",
            "ai-bot-v2-coinank-global-aggregator-direct.service",
            "meta:coinank_global:last_update",
            None,
            r,
            evidence_payloads=[public_status["coinank"]],
        ),
        _ingestor_entry(
            "Liquidation WSS Client",
            "ai-bot-v2-liquidation-wss-paper-shadow.service",
            f"{V2_REDIS_PREFIX}market:liquidations:heartbeat",
            None,
            r,
            evidence_payloads=[public_status["liquidation_wss"]],
        ),
        _ingestor_entry(
            "Native Liquidation Levels Engine",
            "ai-bot-v2-liquidation-levels-engine.service",
            f"{V2_REDIS_PREFIX}liquidations:levels:heartbeat",
            None,
            r,
            evidence_payloads=[public_status["liquidation_levels"]],
        ),
        _ingestor_entry(
            "Liquidation Runtime Status Publisher",
            "ai-bot-v2-liquidation-runtime-status-publisher.service",
            f"{V2_REDIS_PREFIX}liquidations:levels:heartbeat",
            None,
            r,
            control_group="runtime_status",
            evidence_payloads=[public_status["liquidation_runtime"]],
        ),
        _ingestor_entry(
            "Public Intel Free-Tier",
            "ai-bot-v2-public-intel-free-tier-loop.service",
            f"{V2_REDIS_PREFIX}altdata:public_intel:status",
            None,
            r,
            control_group="altdata_ingestor",
        ),
        _ingestor_entry(
            "Alt-Data Symbol Scoring",
            "ai-bot-v2-alt-data-symbol-scoring-loop.service",
            f"{V2_REDIS_PREFIX}symbol_universe:altdata_candidates",
            None,
            r,
            control_group="altdata_scoring",
        ),
        _ingestor_entry(
            "Alt-Data Candidate Publisher",
            "ai-bot-v2-alt-data-candidate-publisher-loop.service",
            f"{V2_REDIS_PREFIX}altdata:candidate_publisher:status",
            None,
            r,
            control_group="altdata_scoring",
        ),
        _ingestor_entry(
            "Alternative-Data Provider Registry Status",
            "ai-bot-v2-alternative-data-status-loop.service",
            f"{V2_REDIS_PREFIX}altdata:provider_status",
            None,
            r,
            control_group="altdata_status",
        ),
        _ingestor_entry(
            "Dynamic Symbol Discovery",
            "ai-bot-v2-dynamic-symbol-discovery-loop.service",
            f"{V2_REDIS_PREFIX}symbol_universe:dynamic_discovery_status",
            None,
            r,
            control_group="symbol_universe",
        ),
    ]

    # Redis market data freshness summary
    freshness: dict = {}
    if r:
        for pat, label in [
            (f"{V2_REDIS_PREFIX}market:prices:*", "prices"),
            (f"{V2_REDIS_PREFIX}market:ohlcv:*", "ohlcv"),
            (f"{V2_REDIS_PREFIX}market:ohlcv:binance:*:source", "ohlcv_binance_kline_wss_sources"),
            (f"{V2_REDIS_PREFIX}market:orderbook:*", "orderbook"),
            (f"{V2_REDIS_PREFIX}features:latest:*", "features_latest"),
            (f"{V2_REDIS_PREFIX}technical_analysis:*", "technical_analysis"),
            (f"{V2_REDIS_PREFIX}market:kucoin:*", "kucoin_market"),
            (f"{V2_REDIS_PREFIX}features:kucoin:*", "kucoin_features"),
            (f"{V2_REDIS_PREFIX}market:coinapi:rest:*", "coinapi_rest"),
            (f"{V2_REDIS_PREFIX}market:coinapi:ohlcv:*", "coinapi_ohlcv"),
            (f"{V2_REDIS_PREFIX}market:coinapi:wsds:*", "coinapi_wsds"),
            (f"{V2_REDIS_PREFIX}features:microfeat:*", "coinapi_wsds_microfeatures"),
            (f"{V2_REDIS_PREFIX}latest:coinapi:ohlcv:*", "coinapi_ohlcv_latest"),
            (f"{V2_REDIS_PREFIX}liquidations:levels:*", "liquidation_levels"),
            (f"{V2_REDIS_PREFIX}market:liquidations:*", "liquidation_market"),
            (f"{V2_REDIS_PREFIX}altdata:public_intel:*", "public_intel_altdata"),
            (f"{V2_REDIS_PREFIX}altdata:whale_walls:*", "whale_wall_altdata"),
            (f"{V2_REDIS_PREFIX}altdata:symbol_score:*", "altdata_symbol_scores"),
            (f"{V2_REDIS_PREFIX}symbol_universe:altdata_candidates", "altdata_candidates"),
            (f"{V2_REDIS_PREFIX}symbol_universe:dynamic_*", "dynamic_symbol_universe"),
        ]:
            try:
                keys = r.keys(pat)
                fresh = sum(1 for k in keys if r.ttl(k) > 0)
                freshness[label] = {"total": len(keys), "fresh_ttl_positive": fresh}
            except Exception:
                freshness[label] = {"total": 0, "fresh_ttl_positive": 0}

    active_count = sum(1 for i in ingestors if i["active"])
    payload = {
        "schema_version": "v2_ingestors_status_v1",
        "worker_id": "v2_ingestors_status_publisher",
        "generated_utc": _utc_iso(),
        "runtime_mode": "LIVE_DATA_AND_LIVE_DECISION_INPUTS_BALANCE_HELD",
        "live_data_enabled": True,
        "live_decision_input_enabled": True,
        "trainer_orchestrator_risk_path_enabled": True,
        "trader_execution_enabled": False,
        "execution_live_symbols": [],
        "live_gate": "enabled_operator_approved",
        "dynamic_symbol_universe_enabled": True,
        "dynamic_symbol_refresh_without_restart": True,
        "symbol_universe_source": "v2_symbol_runtime_universe.resolve_symbols",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "writes_legacy_redis": False,
        "exchange_action_taken": False,
        "adapter_runtime_allowed": False,
        "legacy_ingest_runtime_allowed": True,
        "legacy_ingest_runtime_mode": "DIRECT_LEGACY_OWNED_INGESTOR_PATHS_ONLY_NO_V2_BRIDGE_WRAPPERS",
        "website_control_surface": {
            "enabled": True,
            "endpoint_prefix": "/api/v1/ingestors",
            "allowed_actions": ["start", "stop", "restart", "status"],
            "blocked_actions": [
                "place_order",
                "cancel_order",
                "enable_trader",
                "enable_canary",
                "change_leverage",
                "change_margin",
                "modify_trainer",
            ],
        },
        "ingestors": ingestors,
        "active_count": active_count,
        "total_count": len(ingestors),
        "redis_freshness": freshness,
        "classification": "INGESTORS_OK" if active_count >= 4 else "INGESTORS_DEGRADED",
    }
    return payload


def write_payload(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_ingestors_status_publisher")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=30)
    parser.add_argument("--out", type=Path, default=DEFAULT_PAYLOAD_PATH)
    args = parser.parse_args(argv)
    if args.loop:
        while True:
            payload = run_once()
            write_payload(payload, args.out)
            time.sleep(max(5, args.interval_seconds))
    payload = run_once()
    write_payload(payload, args.out)
    print(json.dumps({"classification": payload["classification"], "active_count": payload["active_count"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
