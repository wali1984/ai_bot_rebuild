"""Shared timestamp-safe helpers for market-structure feature producers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


CONSUMPTION_FLAGS: dict[str, bool] = {
    "trainer_consumes": True,
    "risk_consumes": True,
    "orchestrator_consumes": True,
    "allocator_consumes": True,
    "paper_consumes": True,
    "live_dry_run_consumes": True,
    "frontend_consumes": True,
    "ios_consumes": True,
}


def as_float(value: Any) -> float | None:
    try:
        if value is None or value == "" or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_time(value: Any) -> datetime | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number <= 0 or number != number:
            return None
        if number > 10_000_000_000:
            number /= 1000.0
        try:
            parsed = datetime.fromtimestamp(number, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def row_event_time(row: Mapping[str, Any]) -> datetime | None:
    return parse_time(
        row.get("event_time")
        or row.get("candle_close_time")
        or row.get("close_time")
        or row.get("closeTime")
        or row.get("T")
        or row.get("timestamp")
        or row.get("time")
    )


def row_available_at(row: Mapping[str, Any]) -> datetime | None:
    return parse_time(
        row.get("available_at")
        or row.get("source_available_time")
        or row.get("generated_at")
        or row.get("generated_utc")
        or row.get("ingested_at")
        or row.get("received_at")
        or row_event_time(row)
    )


def closed_rows_available_for_decision(
    rows: list[Any],
    *,
    decision_time: datetime | None,
    max_rows: int = 200,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return rows with explicit point-in-time availability.

    Rows whose ``available_at`` would be after ``decision_time`` are excluded
    and counted. This protects replay and live decision paths from future
    candles without fabricating neutral features.
    """

    accepted: list[dict[str, Any]] = []
    excluded_future = 0
    missing_available_at = 0
    for raw in rows or []:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        available_at = row_available_at(row)
        if available_at is None:
            missing_available_at += 1
            continue
        if decision_time is not None and available_at > decision_time:
            excluded_future += 1
            continue
        accepted.append(row)
    accepted.sort(key=lambda item: row_event_time(item) or row_available_at(item) or datetime.min.replace(tzinfo=timezone.utc))
    if max_rows > 0:
        accepted = accepted[-max_rows:]
    lineage = {
        "input_rows": len(rows or []),
        "usable_rows": len(accepted),
        "excluded_future_rows": excluded_future,
        "missing_available_at_rows": missing_available_at,
        "decision_time": iso_utc(decision_time),
        "future_leakage_prevented": excluded_future > 0,
    }
    return accepted, lineage


def payload_base(
    *,
    schema_version: str,
    feature_family: str,
    symbol: str,
    timeframe: str | None,
    decision_time: datetime | None,
    source: str,
    rows: list[dict[str, Any]],
    lineage: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    event_time = row_event_time(rows[-1]) if rows else None
    available_at = row_available_at(rows[-1]) if rows else None
    return {
        "schema_version": schema_version,
        "feature_family": feature_family,
        "symbol": symbol,
        "timeframe": timeframe,
        "event_time": iso_utc(event_time),
        "available_at": iso_utc(available_at),
        "decision_time": iso_utc(decision_time),
        "generated_utc": now.isoformat(),
        "source": source,
        "missing_mask": {},
        "stale_mask": {},
        "source_availability": {
            source: bool(rows),
            "timestamp_lineage_present": available_at is not None,
        },
        "timestamp_lineage": dict(lineage),
        "paper_only": True,
        "places_real_order": False,
        **CONSUMPTION_FLAGS,
    }


def bool_num(value: Any) -> float | None:
    if value is True:
        return 1.0
    if value is False:
        return 0.0
    return as_float(value)


def direction_code(value: Any) -> float | None:
    text = str(value or "").strip().lower()
    if text in {"up", "bull", "bullish", "long", "buy"}:
        return 1.0
    if text in {"down", "bear", "bearish", "short", "sell"}:
        return -1.0
    if text in {"none", "flat", "range", "ranging", "equilibrium"}:
        return 0.0
    return None


def zone_code(value: Any) -> float | None:
    text = str(value or "").strip().lower()
    if text == "premium":
        return 1.0
    if text == "discount":
        return -1.0
    if text == "equilibrium":
        return 0.0
    return None
