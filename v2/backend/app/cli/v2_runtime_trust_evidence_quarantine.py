"""Targeted runtime evidence quarantine for pipeline trust remediation.

This CLI is V2-only and Redis-only. It never touches live order state, live-gate
state, positions, or config keys. It copies unsafe ephemeral runtime records into
a quarantine namespace and then expires the original key so refreshed workers can
replace stale evidence with clean data.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from typing import Any, Iterable


PATTERNS: tuple[str, ...] = (
    "v2:market:kucoin:kline:*",
    "v2:features:microfeat:*",
    "v2:prediction:*",
    "v2:signals:paper:*",
    "v2:trainer:hybrid_cuda:signals:paper:*",
    "v2:trainer:hybrid_cuda:paper_signal_lineage_preview",
    "v2:trainer:hybrid_cuda:paper_intent_preview",
    "v2:risk:decisions",
    "v2:risk:gateway:decisions",
    "v2:orchestrator:decisions",
    "v2:paper:intents",
)

PROTECTED_PREFIXES: tuple[str, ...] = (
    "v2:paper:ledger",
    "v2:paper:positions",
    "v2:paper:position",
    "v2:live_order_transport:",
    "v2:live_gate:state",
    "v2:trader:execution_state",
    "v2:account:",
    "v2:exchange:",
    "v2:config",
)


def _utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _connect(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


def _parse_json_maybe(value: Any) -> Any:
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


def _read_value(client: Any, key: str) -> Any:
    value_type = client.type(key)
    if isinstance(value_type, bytes):
        value_type = value_type.decode("utf-8", errors="replace")
    if value_type == "string":
        return _parse_json_maybe(client.get(key))
    if value_type == "hash":
        return {field: _parse_json_maybe(value) for field, value in client.hgetall(key).items()}
    if value_type == "list":
        return [_parse_json_maybe(value) for value in client.lrange(key, 0, 999)]
    if value_type == "stream":
        return [
            {"id": item_id, **{k: _parse_json_maybe(v) for k, v in fields.items()}}
            for item_id, fields in client.xrevrange(key, count=1000)
        ]
    if value_type == "zset":
        return [_parse_json_maybe(value) for value in client.zrange(key, 0, 999)]
    if value_type == "set":
        return [_parse_json_maybe(value) for value in sorted(client.smembers(key))]
    return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_abnormal_ohlc(payload: dict[str, Any]) -> bool:
    open_ = _float(payload.get("open"))
    high = _float(payload.get("high"))
    low = _float(payload.get("low"))
    close = _float(payload.get("close"))
    if None in {open_, high, low, close}:
        return False
    assert open_ is not None and high is not None and low is not None and close is not None
    if min(open_, high, low, close) <= 0.0:
        return True
    if high < low:
        return True
    if not (low <= open_ <= high):
        return True
    return not (low <= close <= high)


def _requires_snapshot_evidence(payload: dict[str, Any]) -> bool:
    risk_action = str(payload.get("risk_action") or payload.get("risk_decision_action") or "").lower()
    decision_action = str(payload.get("decision_action") or payload.get("orchestrator_action") or "").lower()
    selected_action = str(payload.get("selected_action") or payload.get("requested_action") or "").lower()
    if bool(payload.get("paper_fill_allowed") or payload.get("routes_to_orchestrator") or payload.get("pre_trade_allowed")):
        return True
    if risk_action in {"allow", "approved", "open_long", "open_short"}:
        return True
    if decision_action in {"open_long", "open_short", "allow"}:
        return True
    return selected_action in {"long", "short", "open_long", "open_short", "close_long", "close_short"}


def _missing_runtime_linkage(payload: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if payload.get("feature_cutoff") in (None, ""):
        reasons.append("feature_cutoff_missing")
    if payload.get("input_feature_hash") in (None, "") and payload.get("feature_vector_hash") in (None, ""):
        reasons.append("input_feature_hash_missing")
    if payload.get("mtf_snapshot_id") in (None, ""):
        reasons.append("mtf_snapshot_id_missing")
    if payload.get("mtf_snapshot_valid") is not True:
        reasons.append("mtf_snapshot_invalid")
    if payload.get("replay_snapshot_id") in (None, "") and payload.get("replay_snapshot_key") in (None, ""):
        reasons.append("replay_snapshot_missing")
    candle_timestamps = payload.get("all_tf_candle_timestamps") or payload.get("source_candle_timestamps") or []
    if not isinstance(candle_timestamps, list) or not candle_timestamps:
        reasons.append("required_mtf_evidence_missing")
    return reasons


def _iter_payloads(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        return
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield item


def _quarantine_reason(key: str, value: Any) -> str | None:
    lowered = key.lower()
    if lowered.startswith("v2:market:kucoin:kline:"):
        if isinstance(value, dict) and _has_abnormal_ohlc(value):
            return "abnormal_ohlc"
        return None
    if lowered.startswith("v2:features:microfeat:"):
        if isinstance(value, dict) and (value.get("available_at") in (None, "") or value.get("feature_cutoff") in (None, "")):
            if value.get("available_at") in (None, "") and value.get("feature_cutoff") in (None, ""):
                return "missing_available_at_and_feature_cutoff"
            if value.get("available_at") in (None, ""):
                return "missing_available_at"
            return "missing_feature_cutoff"
        return None
    if (
        lowered.startswith("v2:prediction:")
        or lowered.startswith("v2:signals:paper:")
        or lowered.startswith("v2:trainer:hybrid_cuda:signals:paper:")
        or lowered in {
            "v2:trainer:hybrid_cuda:paper_signal_lineage_preview",
            "v2:trainer:hybrid_cuda:paper_intent_preview",
        }
    ):
        for payload in _iter_payloads(value):
            missing = _missing_runtime_linkage(payload)
            if missing:
                return ",".join(sorted(set(missing)))
        return None
    if lowered in {
        "v2:risk:decisions",
        "v2:risk:gateway:decisions",
        "v2:orchestrator:decisions",
        "v2:paper:intents",
    }:
        for payload in _iter_payloads(value):
            if not _requires_snapshot_evidence(payload):
                continue
            missing = _missing_runtime_linkage(payload)
            if missing:
                return ",".join(sorted(set(missing)))
        return None
    return None


def _protected(key: str) -> bool:
    return key.startswith(PROTECTED_PREFIXES)


def quarantine_runtime_evidence(
    *,
    client: Any,
    expire_seconds: int,
    quarantine_ttl_seconds: int,
    dry_run: bool,
) -> dict[str, Any]:
    stamp = _utc_stamp()
    affected: list[dict[str, str]] = []
    scanned = 0
    for pattern in PATTERNS:
        for key in client.scan_iter(match=pattern, count=250):
            key = str(key)
            scanned += 1
            if _protected(key):
                continue
            value = _read_value(client, key)
            reason = _quarantine_reason(key, value)
            if reason is None:
                continue
            quarantine_key = f"v2:quarantine:runtime_trust:{stamp}:{key}"
            affected.append({"key": key, "quarantine_key": quarantine_key, "reason": reason})
            if dry_run:
                continue
            client.set(
                quarantine_key,
                json.dumps(
                    {
                        "quarantined_at_utc": stamp,
                        "source_key": key,
                        "reason": reason,
                        "value": value,
                    },
                    sort_keys=True,
                    default=str,
                ),
                ex=int(quarantine_ttl_seconds),
            )
            client.expire(key, int(expire_seconds))
    return {
        "dry_run": dry_run,
        "scanned_keys": scanned,
        "quarantined_count": len(affected),
        "affected": affected,
        "expire_seconds": int(expire_seconds),
        "quarantine_ttl_seconds": int(quarantine_ttl_seconds),
        "patterns": list(PATTERNS),
        "protected_prefixes": list(PROTECTED_PREFIXES),
        "live_order_state_touched": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_runtime_trust_evidence_quarantine")
    parser.add_argument("--redis-url", required=True)
    parser.add_argument("--expire-seconds", type=int, default=60)
    parser.add_argument("--quarantine-ttl-seconds", type=int, default=86400)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    result = quarantine_runtime_evidence(
        client=_connect(args.redis_url),
        expire_seconds=max(1, int(args.expire_seconds)),
        quarantine_ttl_seconds=max(60, int(args.quarantine_ttl_seconds)),
        dry_run=not args.apply,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
