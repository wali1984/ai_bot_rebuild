"""PIT-valid prediction coverage counter for guardian holdout progress.

This module counts current prediction rows as Phase 3 holdout prediction
coverage only. It deliberately does not create A-grade economic evidence.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

DEFAULT_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h")
REQUIRED_ACTIONS: tuple[str, ...] = ("LONG", "SHORT", "NO_TRADE")
MINIMUM_PIT_VALID_PREDICTIONS = 50_000
MINIMUM_SYMBOL_COUNT = 100
REDIS_STATUS_KEY = "v2:guardian:pit_prediction_growth_status"
REDIS_APPEND_ONLY_OBSERVATION_KEY = "v2:guardian:pit_prediction_observations"
MAX_APPEND_ONLY_OBSERVATIONS_PER_CYCLE = 100_000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def canonical_utc(value: Any) -> str | None:
    parsed = parse_utc(value)
    if parsed is None:
        return None
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def stable_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def normalized_action(row: Mapping[str, Any]) -> str:
    raw = (
        row.get("selected_policy_action")
        or row.get("selected_action")
        or row.get("action")
        or row.get("side")
        or row.get("prediction_direction")
    )
    action = str(raw or "").strip().lower()
    if action in {"long", "buy", "bull", "up"}:
        return "LONG"
    if action in {"short", "sell", "bear", "down"}:
        return "SHORT"
    if action in {"hold", "flat", "none", "no_trade", "no-trade", "no trade", "0"}:
        return "NO_TRADE"
    return "UNKNOWN"


def _prediction_identity(row: Mapping[str, Any], *, redis_key: str) -> str:
    prediction_id = str(row.get("prediction_id") or "").strip()
    if prediction_id:
        return prediction_id
    return "pit_" + stable_hash(
        {
            "redis_key": redis_key,
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "decision_time": row.get("decision_time"),
            "feature_cutoff": row.get("feature_cutoff"),
            "selected_action": row.get("selected_action") or row.get("action"),
        }
    )[:24]


def validate_prediction_row(
    row: Mapping[str, Any],
    *,
    redis_key: str,
    allowed_timeframes: Sequence[str] = DEFAULT_TIMEFRAMES,
) -> tuple[dict[str, Any] | None, list[str]]:
    symbol = str(row.get("symbol") or "").strip().upper()
    timeframe = str(row.get("timeframe") or "").strip()
    action = normalized_action(row)
    feature_cutoff = canonical_utc(row.get("feature_cutoff") or row.get("ppo_feature_cutoff"))
    decision_time = canonical_utc(
        row.get("decision_time")
        or row.get("ppo_observation_time")
        or row.get("generated_at")
        or row.get("generated_est")
    )
    available_at = canonical_utc(row.get("available_at") or row.get("source_available_at"))
    generated_at = canonical_utc(row.get("generated_at") or row.get("generated_est"))
    prediction_id = _prediction_identity(row, redis_key=redis_key)

    reasons: list[str] = []
    if not symbol:
        reasons.append("MISSING_SYMBOL")
    if not timeframe:
        reasons.append("MISSING_TIMEFRAME")
    elif timeframe not in set(allowed_timeframes):
        reasons.append("UNSUPPORTED_TIMEFRAME")
    if not str(row.get("prediction_id") or "").strip():
        reasons.append("MISSING_PREDICTION_ID")
    if action == "UNKNOWN":
        reasons.append("UNKNOWN_SELECTED_POLICY_ACTION")
    if feature_cutoff is None:
        reasons.append("MISSING_FEATURE_CUTOFF")
    if decision_time is None:
        reasons.append("MISSING_DECISION_TIME")

    feature_dt = parse_utc(feature_cutoff)
    decision_dt = parse_utc(decision_time)
    available_dt = parse_utc(available_at)
    if feature_dt is not None and decision_dt is not None and feature_dt > decision_dt:
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if available_dt is not None and decision_dt is not None and available_dt > decision_dt:
        reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
    if row.get("future_labels_used_as_features") is True:
        reasons.append("FUTURE_LABELS_USED_AS_FEATURES")
    if row.get("stale_prediction") is True:
        reasons.append("STALE_PREDICTION")

    if reasons:
        return None, sorted(set(reasons))

    record = {
        "schema_version": "guardian_pit_prediction_observation_v1",
        "prediction_id": prediction_id,
        "redis_key": redis_key,
        "symbol": symbol,
        "timeframe": timeframe,
        "selected_policy_action": action,
        "decision_time": decision_time,
        "feature_cutoff": feature_cutoff,
        "available_at": available_at,
        "generated_at": generated_at,
        "feature_cutoff_before_or_at_decision_time": True,
        "available_at_before_or_at_decision_time": available_at is not None,
        "future_labels_used_as_features": False,
        "counts_as_a_grade_evidence": False,
        "counts_as_a_plus": False,
        "counts_as_live_ready": False,
        "counts_no_trade_as_win": False,
        "source_hash": stable_hash(
            {
                "prediction_id": prediction_id,
                "redis_key": redis_key,
                "symbol": symbol,
                "timeframe": timeframe,
                "decision_time": decision_time,
                "feature_cutoff": feature_cutoff,
                "selected_policy_action": action,
            }
        ),
    }
    return record, []


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def append_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    materialized = [dict(row) for row in rows]
    if not materialized:
        return 0
    with path.open("a", encoding="utf-8") as handle:
        for row in materialized:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), default=str))
            handle.write("\n")
    return len(materialized)


def collect_prediction_rows(
    client: Any,
    *,
    symbols: Sequence[str],
    timeframes: Sequence[str] = DEFAULT_TIMEFRAMES,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for symbol in sorted({str(item).strip().upper() for item in symbols if str(item).strip()}):
        for timeframe in timeframes:
            redis_key = f"v2:prediction:{symbol}:{timeframe}"
            try:
                raw = client.get(redis_key)
            except Exception as exc:  # noqa: BLE001
                rejected.append(
                    {
                        "redis_key": redis_key,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "reasons": [f"REDIS_GET_FAILED:{type(exc).__name__}"],
                    }
                )
                continue
            if raw is None:
                rejected.append(
                    {
                        "redis_key": redis_key,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "reasons": ["MISSING_PREDICTION_KEY"],
                    }
                )
                continue
            try:
                row = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                rejected.append(
                    {
                        "redis_key": redis_key,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "reasons": [f"PREDICTION_JSON_INVALID:{type(exc).__name__}"],
                    }
                )
                continue
            if not isinstance(row, dict):
                rejected.append(
                    {
                        "redis_key": redis_key,
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "reasons": ["PREDICTION_PAYLOAD_NOT_OBJECT"],
                    }
                )
                continue
            record, reasons = validate_prediction_row(row, redis_key=redis_key, allowed_timeframes=timeframes)
            if record is None:
                rejected.append(
                    {
                        "redis_key": redis_key,
                        "symbol": symbol or str(row.get("symbol") or "").upper(),
                        "timeframe": timeframe or str(row.get("timeframe") or ""),
                        "prediction_id": row.get("prediction_id"),
                        "decision_time": row.get("decision_time"),
                        "feature_cutoff": row.get("feature_cutoff"),
                        "selected_policy_action": normalized_action(row),
                        "reasons": reasons,
                    }
                )
                continue
            valid.append(record)
    return valid, rejected


def collect_append_only_prediction_rows(
    client: Any,
    *,
    timeframes: Sequence[str] = DEFAULT_TIMEFRAMES,
    redis_key: str = REDIS_APPEND_ONLY_OBSERVATION_KEY,
    max_rows: int = MAX_APPEND_ONLY_OBSERVATIONS_PER_CYCLE,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    valid: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    if not hasattr(client, "lrange"):
        return valid, rejected
    start = -max(1, int(max_rows))
    try:
        raw_rows = client.lrange(redis_key, start, -1)
    except Exception as exc:  # noqa: BLE001
        return [], [{"redis_key": redis_key, "reasons": [f"REDIS_LRANGE_FAILED:{type(exc).__name__}"]}]
    for index, raw in enumerate(raw_rows or []):
        try:
            row = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            rejected.append(
                {
                    "redis_key": redis_key,
                    "list_index": index,
                    "reasons": [f"APPEND_ONLY_PREDICTION_JSON_INVALID:{type(exc).__name__}"],
                }
            )
            continue
        if not isinstance(row, dict):
            rejected.append(
                {
                    "redis_key": redis_key,
                    "list_index": index,
                    "reasons": ["APPEND_ONLY_PREDICTION_PAYLOAD_NOT_OBJECT"],
                }
            )
            continue
        source_key = str(row.get("source_redis_key") or row.get("redis_key") or redis_key)
        record, reasons = validate_prediction_row(row, redis_key=source_key, allowed_timeframes=timeframes)
        if record is None:
            rejected.append(
                {
                    "redis_key": redis_key,
                    "source_redis_key": source_key,
                    "list_index": index,
                    "symbol": row.get("symbol"),
                    "timeframe": row.get("timeframe"),
                    "prediction_id": row.get("prediction_id"),
                    "decision_time": row.get("decision_time"),
                    "feature_cutoff": row.get("feature_cutoff"),
                    "selected_policy_action": normalized_action(row),
                    "reasons": reasons,
                }
            )
            continue
        record["append_only_redis_key"] = redis_key
        valid.append(record)
    return valid, rejected


def dedupe_records(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        identity = str(row.get("source_hash") or row.get("prediction_id") or "")
        if not identity or identity in seen:
            continue
        seen.add(identity)
        deduped.append(dict(row))
    return deduped


def dedupe_new_records(existing_rows: Sequence[Mapping[str, Any]], current_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen = {str(row.get("source_hash") or row.get("prediction_id") or "") for row in existing_rows}
    new_rows: list[dict[str, Any]] = []
    for row in current_rows:
        identity = str(row.get("source_hash") or row.get("prediction_id") or "")
        if not identity or identity in seen:
            continue
        seen.add(identity)
        new_rows.append(dict(row))
    return new_rows


def coverage_status(
    *,
    archive_rows: Sequence[Mapping[str, Any]],
    current_valid_rows: Sequence[Mapping[str, Any]],
    rejected_rows: Sequence[Mapping[str, Any]],
    new_rows_appended: int,
    generated_utc: str,
) -> dict[str, Any]:
    action_counts = Counter(str(row.get("selected_policy_action") or "UNKNOWN") for row in archive_rows)
    symbols = sorted({str(row.get("symbol") or "") for row in archive_rows if row.get("symbol")})
    timeframes = sorted({str(row.get("timeframe") or "") for row in archive_rows if row.get("timeframe")})
    rejection_counts: Counter[str] = Counter()
    for row in rejected_rows:
        rejection_counts.update(str(reason) for reason in row.get("reasons") or [])
    valid_count = len(archive_rows)
    missing_timeframes = [timeframe for timeframe in DEFAULT_TIMEFRAMES if timeframe not in set(timeframes)]
    missing_actions = [action for action in REQUIRED_ACTIONS if action_counts.get(action, 0) <= 0]
    return {
        "schema_version": "guardian_pit_prediction_growth_status_v1",
        "generated_utc": generated_utc,
        "status": (
            "READY_UNTOUCHED_HOLDOUT_PREDICTION_COVERAGE"
            if valid_count > 0
            else "BLOCKED_NO_UNTOUCHED_HOLDOUT_PIT_VALID_PREDICTIONS"
        ),
        "policy": (
            "Counts point-in-time-valid current prediction observations as guardian holdout "
            "prediction coverage only. This never counts as A-grade economic evidence and "
            "never counts NO_TRADE as an economic win."
        ),
        "point_in_time_valid_prediction_count": valid_count,
        "current_cycle_valid_prediction_count": len(current_valid_rows),
        "current_cycle_rejected_prediction_count": len(rejected_rows),
        "new_rows_appended": new_rows_appended,
        "symbol_count": len(symbols),
        "timeframe_count": len(timeframes),
        "selected_policy_action_counts": {action: int(action_counts.get(action, 0)) for action in REQUIRED_ACTIONS},
        "unknown_action_count": int(action_counts.get("UNKNOWN", 0)),
        "symbols": symbols,
        "timeframes": timeframes,
        "missing_timeframes": missing_timeframes,
        "missing_selected_policy_actions": missing_actions,
        "rejection_reason_counts": dict(sorted(rejection_counts.items())),
        "sample_valid_predictions": [dict(row) for row in list(current_valid_rows)[:20]],
        "sample_rejected_predictions": [dict(row) for row in list(rejected_rows)[:20]],
        "required_point_in_time_valid_prediction_count": MINIMUM_PIT_VALID_PREDICTIONS,
        "required_symbol_count": MINIMUM_SYMBOL_COUNT,
        "required_timeframes": list(DEFAULT_TIMEFRAMES),
        "required_selected_policy_actions": list(REQUIRED_ACTIONS),
        "remaining_point_in_time_valid_predictions": max(0, MINIMUM_PIT_VALID_PREDICTIONS - valid_count),
        "remaining_symbol_count": max(0, MINIMUM_SYMBOL_COUNT - len(symbols)),
        "cycles_to_minimum_at_current_append_rate": (
            None
            if new_rows_appended <= 0
            else int((max(0, MINIMUM_PIT_VALID_PREDICTIONS - valid_count) + new_rows_appended - 1) // new_rows_appended)
        ),
        "counts_as_a_grade_evidence": False,
        "counts_as_a_plus": False,
        "counts_as_live_ready": False,
        "counts_no_trade_as_win": False,
        "no_trade_counted_as_economic_win": False,
    }


def update_holdout_manifest(manifest_path: Path, status: Mapping[str, Any], *, generated_utc: str) -> dict[str, Any]:
    existing: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                existing = payload
        except json.JSONDecodeError:
            existing = {}
    updated = dict(existing)
    updated.setdefault("schema_version", "out_of_sample_holdout_reverify_manifest_v1")
    updated.setdefault("producer", "holdout")
    updated.setdefault("status", "NO_COUNTABLE_HOLDOUT_ROWS_APPENDED")
    updated["generated_utc"] = generated_utc
    updated["holdout_prediction_coverage_status"] = dict(status)
    updated["point_in_time_valid_prediction_count"] = status.get("point_in_time_valid_prediction_count")
    updated["counts_as_a_grade_evidence"] = False
    updated["counts_as_a_plus"] = False
    updated["counts_as_live_ready"] = False
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(updated, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return updated


def maturity_queue(status: Mapping[str, Any], *, archive_path: Path, generated_utc: str) -> dict[str, Any]:
    return {
        "schema_version": "guardian_holdout_maturity_queue_v1",
        "generated_utc": generated_utc,
        "status": (
            "PIT_PREDICTION_COVERAGE_GROWING"
            if int(status.get("new_rows_appended") or 0) > 0
            else "PIT_PREDICTION_COVERAGE_NO_NEW_ROWS_THIS_CYCLE"
        ),
        "archive_path": str(archive_path),
        "pending_prediction_coverage_rows": int(status.get("point_in_time_valid_prediction_count") or 0),
        "matured_economic_rows": 0,
        "counts_as_a_grade_evidence": False,
        "counts_as_a_plus": False,
        "next_required_step": "Run future-label maturation only after label windows close; do not use future labels as features.",
    }


def blocker_projection(status: Mapping[str, Any], *, generated_utc: str) -> dict[str, Any]:
    remaining = int(status.get("remaining_point_in_time_valid_predictions") or 0)
    return {
        "schema_version": "guardian_holdout_blocker_projection_v1",
        "generated_utc": generated_utc,
        "status": (
            "GUARDIAN_PIT_PREDICTION_GROWTH_IN_PROGRESS"
            if remaining > 0
            else "GUARDIAN_PIT_PREDICTION_MINIMUM_REACHED"
        ),
        "exact_blocker": "INSUFFICIENT_UNTOUCHED_HOLDOUT_PIT_VALID_PREDICTIONS" if remaining > 0 else None,
        "observed": int(status.get("point_in_time_valid_prediction_count") or 0),
        "required": MINIMUM_PIT_VALID_PREDICTIONS,
        "remaining": remaining,
        "cycles_to_minimum_at_current_append_rate": status.get("cycles_to_minimum_at_current_append_rate"),
        "counts_as_a_grade_evidence": False,
        "counts_as_a_plus": False,
        "counts_as_live_ready": False,
    }
