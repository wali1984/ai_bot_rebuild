"""Read-only runtime evidence exporter for pipeline trust verification."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Iterable

CATEGORY_PATTERNS: dict[str, tuple[str, ...]] = {
    "candles": (
        "v2:market:ohlcv_closed:*",
        "v2:market:kline_current:*",
        "v2:market:ohlcv:binance:*",
        "v2:market:*:ohlcv:*",
        "v2:market:ohlcv:*:source",
        "v2:market:kucoin:*",
        "v2:market:coinapi:*",
        "v2:market:coinank:*",
        "latest:coinank:*",
    ),
    "features": (
        "v2:features:latest:*",
        "v2:features:ta:*",
        "v2:features:ta_full:*",
        "v2:features:microfeat:*",
        "v2:technical_analysis:*",
        "v2:unified_features:*",
        "v2:trainer:hybrid_cuda:features:*",
    ),
    "predictions": (
        "v2:prediction:*",
    ),
    "masa_ppo": (
        "v2:signals:paper:*",
        "v2:rl_core:*",
        "v2:trainer:hybrid_cuda:status",
        "v2:trainer:hybrid_cuda:metrics",
    ),
    "training_samples": (
        "v2:trainer:dataset:*",
        "v2:trainer:samples:*",
        "v2:trainer:hybrid_cuda:*",
    ),
    "execution_records": (
        "v2:risk:decisions",
        "v2:risk:gateway:decisions",
        "v2:orchestrator:decisions",
        "v2:paper:ledger",
        "v2:paper:intents",
        "v2:paper:intents_held_by_paper_fill_gate",
        "v2:live_order_transport:*",
        "v2:live_canary:*",
    ),
    "positions": (
        "v2:paper:positions",
        "v2:paper:position*",
        "v2:account:*position*",
        "v2:exchange:*position*",
    ),
    "config_admin": (
        "v2:config*",
        "v2:operator_runtime:*",
        "v2:live_gate:state",
        "v2:trader:execution_state",
        "v2:risk:active_profile",
    ),
    "mtf_snapshots": (
        "v2:market:mtf_snapshot:*",
        "v2:decision:mtf_snapshot:*",
        "v2:mtf_snapshot:*",
    ),
    "replay_snapshots": (
        "v2:market:mtf_snapshot:*",
        "v2:decision:mtf_snapshot:*",
        "v2:mtf_snapshot:*",
        "v2:replay:snapshot*",
        "v2:replay:snapshots:*",
        "v2:market_state:replay*",
        "v2:decision:replay*",
    ),
}

OUTPUT_FILES = {
    "candles": "candles.jsonl",
    "features": "features.jsonl",
    "predictions": "predictions.jsonl",
    "masa_ppo": "masa_ppo.jsonl",
    "training_samples": "training_samples.jsonl",
    "execution_records": "execution_records.jsonl",
    "positions": "positions.jsonl",
    "config_admin": "config_admin.jsonl",
    "mtf_snapshots": "mtf_snapshots.jsonl",
    "replay_snapshots": "replay_snapshots.jsonl",
}

SECRET_TOKENS = ("secret", "token", "api_key", "apikey", "password", "credential", "signature")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="export_pipeline_trust_evidence")
    parser.add_argument("--redis-url", default=os.getenv("REDIS_URL", ""))
    parser.add_argument("--output-dir", default="pipeline_trust_evidence")
    parser.add_argument("--max-keys-per-category", type=int, default=5000)
    args = parser.parse_args(argv)
    if not args.redis_url:
        raise SystemExit("--redis-url or REDIS_URL is required")
    client = redis_client(args.redis_url)
    run_dir = export_pipeline_trust_evidence(
        client=client,
        redis_url=args.redis_url,
        output_root=Path(args.output_dir),
        max_keys_per_category=args.max_keys_per_category,
    )
    print(str(run_dir))
    return 0


def redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


def export_pipeline_trust_evidence(
    *,
    client: Any,
    redis_url: str,
    output_root: Path,
    max_keys_per_category: int = 1000,
) -> Path:
    now = dt.datetime.now(dt.timezone.utc)
    run_dir = output_root / now.strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    warnings: list[str] = []
    truncated_categories: list[str] = []
    scanned_patterns: dict[str, list[str]] = {}
    for category, patterns in CATEGORY_PATTERNS.items():
        scanned_patterns[category] = list(patterns)
        records = collect_category_records(client, category=category, patterns=patterns, max_keys=max_keys_per_category)
        if category == "config_admin":
            status = build_config_admin_status_safely()
            if status is not None:
                records.append({"redis_key": "local:config_admin:build_status", "category": category, "value": status})
        counts[category] = len(records)
        write_jsonl(run_dir / OUTPUT_FILES[category], records)
        if not records:
            warnings.append(f"missing_evidence:{category}")
        if len(records) >= int(max_keys_per_category):
            truncated_categories.append(category)
            warnings.append(f"possible_truncated_evidence:{category}:max_keys_per_category={max_keys_per_category}")
    manifest = {
        "export_timestamp_utc": now.isoformat(),
        "redis_url_redacted": redact_redis_url(redis_url),
        "key_patterns_scanned": scanned_patterns,
        "record_counts_by_file": {OUTPUT_FILES[k]: v for k, v in counts.items()},
        "missing_evidence_categories": [k for k, v in counts.items() if v == 0],
        "possible_truncated_categories": truncated_categories,
        "warnings": warnings,
        "no_secrets": True,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return run_dir


def collect_category_records(client: Any, *, category: str, patterns: Iterable[str], max_keys: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pattern in patterns:
        for key in client.scan_iter(match=pattern, count=250):
            if key in seen:
                continue
            seen.add(str(key))
            if len(records) >= max_keys:
                return records
            if category == "candles" and legacy_binance_candle_shadowed_by_canonical(client, str(key)):
                continue
            records.append(
                {
                    "redis_key": str(key),
                    "category": category,
                    "value": redact_value(read_redis_value(client, str(key))),
                }
            )
    return records


def legacy_binance_candle_shadowed_by_canonical(client: Any, key: str) -> bool:
    parts = key.split(":")
    if len(parts) != 6 or parts[:4] != ["v2", "market", "ohlcv", "binance"]:
        return False
    symbol = parts[4]
    timeframe = parts[5]
    canonical_key = f"v2:market:ohlcv_closed:binance:{symbol}:{timeframe}"
    try:
        return client.get(canonical_key) is not None
    except Exception:
        return False


def read_redis_value(client: Any, key: str) -> Any:
    value_type = client.type(key)
    if isinstance(value_type, bytes):
        value_type = value_type.decode("utf-8", errors="replace")
    if value_type == "string":
        return parse_json_maybe(client.get(key))
    if value_type == "hash":
        return {field: parse_json_maybe(value) for field, value in client.hgetall(key).items()}
    if value_type == "list":
        return [parse_json_maybe(value) for value in client.lrange(key, 0, 999)]
    if value_type == "stream":
        return [
            {"id": item_id, **{k: parse_json_maybe(v) for k, v in fields.items()}}
            for item_id, fields in client.xrevrange(key, count=1000)
        ]
    if value_type == "zset":
        return [parse_json_maybe(value) for value in client.zrange(key, 0, 999)]
    if value_type == "set":
        return [parse_json_maybe(value) for value in sorted(client.smembers(key))]
    return None


def parse_json_maybe(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{\"-0123456789tfn":
        return value
    try:
        return json.loads(text)
    except Exception:
        return value


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, child in value.items():
            lowered = str(key).lower()
            if any(token in lowered for token in SECRET_TOKENS):
                out[key] = "[REDACTED]"
            else:
                out[key] = redact_value(child)
        return out
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def redact_redis_url(redis_url: str) -> str:
    if "@" not in redis_url:
        return redis_url
    scheme, rest = redis_url.split("://", 1) if "://" in redis_url else ("redis", redis_url)
    return f"{scheme}://[REDACTED]@{rest.split('@', 1)[1]}"


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, default=str))
            handle.write("\n")


def build_config_admin_status_safely() -> dict[str, Any] | None:
    try:
        from app.cli.v2_config_admin_manager import build_status
    except Exception:
        return None
    try:
        return redact_value(build_status())
    except Exception:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
