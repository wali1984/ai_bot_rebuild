"""Publish data-plane-derived provider health for self-silent providers.

Providers like Binance/KuCoin/CoinAnk/TA never publish
``v2:provider:{name}:health`` themselves, so the control-center provider
cards rendered gray/CONNECTING forever even while thousands of live
data-plane keys proved actual payloads. This publisher derives truthful
health from capped key censuses + freshness samples and writes the same
health contract the snapshot builder already consumes.

Self-publishing providers (moralis, coinglass, santiment) are never
overwritten. Read-only against market data; writes only
``v2:provider:*:health`` keys. Never touches orders/leverage/margin.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from typing import Any

V2_PREFIX = "v2:"
HEALTH_KEY_TEMPLATE = "v2:provider:{provider}:health"
HEALTH_TTL_SECONDS = 300
SCAN_KEY_CAP = 1500
SCAN_TIME_BUDGET_SECONDS = 2.5
SOURCE_LABEL = "V2_PROVIDER_DATA_PLANE_HEALTH_PUBLISHER"

# provider -> (key prefixes, static consumer roles, feature-count probe field)
DATA_PLANE_PROVIDERS: dict[str, dict[str, Any]] = {
    "binance": {
        "patterns": ["v2:market:ohlcv:binance:*", "v2:orderbook:top:binance:*", "v2:market:prices:*"],
        "roles": ["trainer", "strategy_supply", "risk", "paper_loop", "market_pages"],
    },
    "kucoin": {
        "patterns": ["v2:market:kucoin:latest:*"],
        "roles": ["cross_venue_confirmation", "trust_gate"],
    },
    "coinank": {
        "patterns": ["v2:altdata:public_intel:symbol:*", "v2:altdata:symbol_score:*", "v2:liquidations:levels:*"],
        "roles": ["strategy_supply", "risk", "squeeze_context"],
    },
    "ta": {
        "patterns": ["v2:features:ta:*", "v2:features:ta_closed:*"],
        "roles": ["trainer", "strategy_supply"],
        "feature_count_field": "indicator_count",
    },
    "feature_snapshot_builder": {
        "patterns": ["v2:features:latest:*"],
        "roles": ["trainer", "rl_core", "paper_loop"],
        "feature_count_field": "feature_count",
    },
    "microstructure": {
        "patterns": ["v2:microstructure:trust_score:*", "v2:market:trade_tape_features:*"],
        "roles": ["trust_gate", "strategy_supply", "risk"],
    },
    "liquidations": {
        "patterns": ["v2:liquidations:levels:*"],
        "roles": ["strategy_supply", "risk", "squeeze_context"],
    },
    "orderbook": {
        "patterns": ["v2:orderbook:top:binance:*", "v2:orderbook:features:binance:*"],
        "roles": ["pricing", "trust_gate", "exit_engine"],
    },
    "trainer_feed": {
        "patterns": ["v2:trainer:hybrid_cuda:signals:paper:*"],
        "roles": ["paper_loop", "exploration", "ppo_lineage"],
    },
    "paper_loop": {
        "patterns": ["v2:paper:heartbeat", "v2:paper:ledger", "v2:paper:exploration:supply_status"],
        "roles": ["exploration", "lifecycle", "trainer_feedback"],
    },
    "portfolio_publisher": {
        "patterns": ["v2:paper:positions", "v2:paper:session"],
        "roles": ["portfolio_pages", "mobile"],
    },
    "live_canary": {
        "patterns": ["v2:live_canary:status", "v2:live_canary:heartbeat"],
        "roles": ["live_readiness_no_execute"],
    },
}

_TS_FIELDS = ("fetched_utc", "generated_utc", "created_at", "available_at", "generated_at")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis():
    try:
        import redis  # type: ignore

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def _census(client: Any, pattern: str) -> tuple[int, list[str]]:
    count = 0
    samples: list[str] = []
    started = time.time()
    try:
        for key in client.scan_iter(match=pattern, count=1000):
            count += 1
            if len(samples) < 3:
                samples.append(str(key))
            if count >= SCAN_KEY_CAP or time.time() - started > SCAN_TIME_BUDGET_SECONDS:
                break
    except Exception:
        return 0, []
    return count, samples


def _sample_payload(client: Any, key: str) -> dict[str, Any]:
    try:
        raw = client.get(key)
        payload = json.loads(raw) if raw else {}
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _freshness(payload: dict[str, Any]) -> tuple[str | None, float | None]:
    for field in _TS_FIELDS:
        value = payload.get(field)
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - parsed).total_seconds()
            return str(value), age
        except ValueError:
            continue
    return None, None


def _symbol_from_key(key: str) -> str | None:
    parts = key.split(":")
    for part in reversed(parts):
        if part.isupper() and part.endswith("USDT"):
            return part
    return None


def build_health_payload(client: Any, provider: str, spec: dict[str, Any]) -> dict[str, Any]:
    total = 0
    all_samples: list[str] = []
    per_pattern: dict[str, int] = {}
    for pattern in spec["patterns"]:
        count, samples = _census(client, pattern)
        per_pattern[pattern] = count
        total += count
        all_samples.extend(samples)
    sample_payload = _sample_payload(client, all_samples[0]) if all_samples else {}
    last_success_utc, age_seconds = _freshness(sample_payload)
    feature_count = 0
    probe_field = spec.get("feature_count_field")
    if probe_field and sample_payload:
        try:
            feature_count = int(sample_payload.get(probe_field) or 0)
        except (TypeError, ValueError):
            feature_count = 0
    symbols = sorted(
        {
            symbol
            for symbol in (_symbol_from_key(key) for key in all_samples)
            if symbol
        }
    )
    if total <= 0:
        status, color = "DOWN_NO_DATA_PLANE_KEYS", "red"
    elif age_seconds is not None and age_seconds > 900:
        status, color = "STALE", "yellow"
    else:
        # Data-plane keys carry their own TTLs, so key existence implies the
        # writer refreshed them recently even when payloads lack timestamps.
        status, color = "ACTIVE", "green"
    return {
        "schema_version": "provider_data_plane_health_v1",
        "provider": provider,
        "source": SOURCE_LABEL,
        "generated_utc": _utc_iso(),
        "status": status,
        "dashboard_color": color,
        "dashboard_color_reason": "data_plane_key_census",
        "actual_payload_count": total,
        "actual_payload_present": total > 0,
        "payload_count_capped_at": SCAN_KEY_CAP * len(spec["patterns"]),
        "per_pattern_counts": per_pattern,
        "sample_keys": all_samples[:3],
        "last_success_utc": last_success_utc,
        "source_lag_seconds": age_seconds,
        "freshness_basis": (
            "sample_payload_timestamp" if age_seconds is not None else "key_ttl_managed"
        ),
        "feature_count": feature_count,
        "consumer_roles": list(spec["roles"]),
        "consumer_count": len(spec["roles"]),
        "symbols_covered": symbols[:12],
        "heartbeat_only": False,
        "routes_to_live": False,
        "places_real_order": False,
        "live_gate": "blocked_human_only",
    }


def run_once(client: Any = None) -> dict[str, Any]:
    client = client if client is not None else _connect_redis()
    written: list[str] = []
    statuses: dict[str, str] = {}
    if client is None:
        return {"written": [], "error": "NO_REDIS"}
    for provider, spec in DATA_PLANE_PROVIDERS.items():
        payload = build_health_payload(client, provider, spec)
        key = HEALTH_KEY_TEMPLATE.format(provider=provider)
        if not key.startswith(V2_PREFIX):
            continue
        try:
            client.set(key, json.dumps(payload, default=str), ex=HEALTH_TTL_SECONDS)
            written.append(key)
            statuses[provider] = payload["status"]
        except Exception:
            continue
    return {
        "schema_version": "provider_data_plane_health_publisher_status_v1",
        "generated_utc": _utc_iso(),
        "written": written,
        "statuses": statuses,
        "self_publishing_providers_untouched": ["moralis", "coinglass", "santiment"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    while True:
        result = run_once()
        if args.json:
            print(json.dumps(result, default=str))
        if not args.loop:
            return 0 if result.get("written") else 1
        time.sleep(max(15, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
