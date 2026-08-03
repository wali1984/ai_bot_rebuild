from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def validate_event_time_alignment(row: dict[str, Any]) -> dict[str, Any]:
    decision = _parse_dt(
        row.get("decision_cutoff_time_est")
        or row.get("decision_time_est")
        or row.get("generated_est")
        or row.get("generated_utc")
        or row.get("generated_at")
    )
    source_event = _parse_dt(row.get("source_event_time_est") or row.get("source_event_time_utc"))
    source_available = _parse_dt(
        row.get("source_available_at_decision_time")
        or row.get("source_received_time_est")
        or row.get("received_at")
    )
    reasons: list[str] = []
    status = "TF_ALIGNED"
    if decision is None:
        status = "SOURCE_EVENT_TIME_MISSING"
        reasons.append("decision_cutoff_time_missing")
    if source_event is None:
        status = "SOURCE_EVENT_TIME_MISSING"
        reasons.append("source_event_time_missing")
    elif decision is not None and source_event > decision:
        status = "FUTURE_LEAKAGE"
        reasons.append("feature_timestamp_after_decision_cutoff")
    if source_available and decision and source_available > decision:
        status = "BACKFILLED_NOT_AVAILABLE_AT_DECISION_TIME"
        reasons.append("source_available_after_decision_cutoff")
    return {
        "status": status,
        "source_event_time_est": row.get("source_event_time_est"),
        "source_received_time_est": row.get("source_received_time_est") or row.get("received_at"),
        "source_available_at_decision_time": row.get("source_available_at_decision_time"),
        "decision_cutoff_time_est": row.get("decision_cutoff_time_est") or row.get("decision_time_est"),
        "reject_reasons": reasons,
    }


def validate_candle_completion(row: dict[str, Any]) -> dict[str, Any]:
    closed = row.get("candle_closed_confirmed")
    close_time = row.get("candle_close_time")
    open_time = row.get("candle_open_time")
    if closed is True:
        status = "CANDLE_CLOSED_CONFIRMED"
        reasons: list[str] = []
    elif closed is False:
        status = "UNCLOSED_CANDLE"
        reasons = ["UNCLOSED_CANDLE"]
    else:
        status = "CANDLE_COMPLETION_UNKNOWN"
        reasons = ["CANDLE_COMPLETION_UNKNOWN", "candle_closed_confirmed_missing"]
    if open_time is None or close_time is None:
        reasons.append("candle_open_or_close_time_missing")
        if status == "CANDLE_CLOSED_CONFIRMED":
            status = "CANDLE_COMPLETION_UNKNOWN"
    return {
        "status": status,
        "candle_open_time": open_time,
        "candle_close_time": close_time,
        "candle_closed_confirmed": closed,
        "reject_reasons": reasons,
    }
