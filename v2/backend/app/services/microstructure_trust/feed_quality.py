"""Feed-quality and latency scoring for public orderbook inputs."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


def parse_time_ms(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric <= 0 or numeric != numeric:
            return None
        if numeric > 1_000_000_000_000_000:
            numeric /= 1_000_000.0
        elif numeric < 10_000_000_000:
            numeric *= 1000.0
        return int(numeric)
    text = str(value).strip()
    if not text:
        return None
    try:
        numeric = float(text)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.astimezone(timezone.utc).timestamp() * 1000)
    return parse_time_ms(numeric)


def utc_now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _rate(count: int, elapsed_ms: int | None) -> float:
    if elapsed_ms is None or elapsed_ms <= 0:
        return 0.0
    return float(count) / (elapsed_ms / 1000.0)


def evaluate_feed_quality(
    *,
    exchange: str,
    symbol: str,
    event_time: Any = None,
    transaction_time: Any = None,
    received_at: Any = None,
    available_at: Any = None,
    decision_time: Any = None,
    previous_received_at: Any = None,
    observed_local_latency_ms: Any = None,
    sequence_gap_count: int = 0,
    unrepaired_sequence_gap: bool = False,
    snapshot_repair_count: int = 0,
    stale_update_count: int = 0,
    out_of_order_count: int = 0,
    update_count: int = 1,
    trade_update_count: int = 0,
    book_ticker_update_count: int = 0,
    first_observed_at: Any = None,
    adaptive_latency_bound_ms: float = 750.0,
    stale_bound_ms: float = 1500.0,
) -> dict[str, Any]:
    now = utc_now_ms()
    event_ms = parse_time_ms(event_time)
    transaction_ms = parse_time_ms(transaction_time)
    received_input_ms = parse_time_ms(received_at)
    available_input_ms = parse_time_ms(available_at)
    decision_input_ms = parse_time_ms(decision_time)
    received_ms = received_input_ms or now
    available_ms = available_input_ms or received_ms
    decision_ms = decision_input_ms or now
    previous_received_ms = parse_time_ms(previous_received_at)
    first_observed_ms = parse_time_ms(first_observed_at) or previous_received_ms or received_ms

    exchange_latency_ms = None
    if event_ms is not None and transaction_ms is not None:
        exchange_latency_ms = max(0, transaction_ms - event_ms)
    local_reference_ms = transaction_ms if transaction_ms is not None else event_ms
    observed_latency_ms = _safe_float(observed_local_latency_ms)
    local_latency_ms = None if local_reference_ms is None else max(0, available_ms - local_reference_ms)
    local_latency_source = "timestamp_delta" if local_latency_ms is not None else "missing"
    if local_latency_ms is None and observed_latency_ms is not None and observed_latency_ms >= 0:
        local_latency_ms = observed_latency_ms
        local_latency_source = "observed_local_latency_ms"
    update_gap_ms = None if previous_received_ms is None else max(0, received_ms - previous_received_ms)
    book_update_age_ms = max(0, decision_ms - available_ms)
    elapsed_ms = max(1, received_ms - first_observed_ms)

    fail_reasons: list[str] = []
    if local_latency_ms is None:
        fail_reasons.append("LOCAL_LATENCY_MISSING")
    elif local_latency_ms > adaptive_latency_bound_ms:
        fail_reasons.append("LATENCY_ABOVE_ADAPTIVE_BOUND")
    if sequence_gap_count > 0 and unrepaired_sequence_gap:
        fail_reasons.append("UNREPAIRED_SEQUENCE_GAP")
    has_explicit_available_reference = available_input_ms is not None or received_input_ms is not None
    if has_explicit_available_reference and decision_input_ms is not None and available_ms > decision_ms:
        fail_reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
    if book_update_age_ms > stale_bound_ms:
        fail_reasons.append("BOOK_UPDATE_AGE_TOO_HIGH")
    if out_of_order_count > 0:
        fail_reasons.append("OUT_OF_ORDER_UPDATES_PRESENT")

    latency_for_score = local_latency_ms if local_latency_ms is not None else adaptive_latency_bound_ms * 2.0
    latency_score = max(0.0, min(1.0, 1.0 - (latency_for_score / max(1.0, adaptive_latency_bound_ms * 2.0))))
    gap_penalty = min(1.0, float(sequence_gap_count) * 0.35 + (0.5 if unrepaired_sequence_gap else 0.0))
    stale_penalty = min(1.0, float(stale_update_count) * 0.15 + (book_update_age_ms / max(1.0, stale_bound_ms * 3.0)))
    integrity_score = max(0.0, 1.0 - gap_penalty - (0.15 * out_of_order_count))
    freshness_score = max(0.0, 1.0 - stale_penalty)
    feed_quality_score = max(0.0, min(1.0, (latency_score * 0.35) + (integrity_score * 0.4) + (freshness_score * 0.25)))

    return {
        "schema_version": "microstructure_feed_quality_v1",
        "exchange": exchange,
        "symbol": symbol.upper(),
        "event_time": event_time,
        "transaction_time": transaction_time,
        "received_at": received_at,
        "available_at": available_at,
        "decision_time": decision_time,
        "exchange_latency_ms": exchange_latency_ms,
        "local_latency_ms": local_latency_ms,
        "local_latency_source": local_latency_source,
        "latency_ms": local_latency_ms,
        "update_gap_ms": update_gap_ms,
        "book_update_age_ms": book_update_age_ms,
        "sequence_gap_count": int(sequence_gap_count),
        "unrepaired_sequence_gap": bool(unrepaired_sequence_gap),
        "snapshot_repair_count": int(snapshot_repair_count),
        "stale_update_count": int(stale_update_count),
        "out_of_order_count": int(out_of_order_count),
        "depth_update_rate": _rate(int(update_count), elapsed_ms),
        "trade_update_rate": _rate(int(trade_update_count), elapsed_ms),
        "book_ticker_update_rate": _rate(int(book_ticker_update_count), elapsed_ms),
        "adaptive_latency_bound_ms": float(adaptive_latency_bound_ms),
        "stale_bound_ms": float(stale_bound_ms),
        "latency_score": round(latency_score, 8),
        "feed_integrity_score": round(integrity_score, 8),
        "freshness_score": round(freshness_score, 8),
        "feed_quality_score": round(feed_quality_score, 8),
        "fail_closed": bool(fail_reasons),
        "fail_reasons": fail_reasons,
        "generated_at": iso_now(),
    }


def summarize_feed_quality(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    typed = [row for row in rows if isinstance(row, Mapping)]
    score_values = [_safe_float(row.get("feed_quality_score")) for row in typed]
    score_values = [value for value in score_values if value is not None]
    return {
        "schema_version": "microstructure_feed_quality_summary_v1",
        "generated_at": iso_now(),
        "symbols": len({str(row.get("symbol") or "") for row in typed if row.get("symbol")}),
        "rows": len(typed),
        "fail_closed_rows": sum(1 for row in typed if row.get("fail_closed") is True),
        "sequence_gap_rows": sum(1 for row in typed if int(row.get("sequence_gap_count") or 0) > 0),
        "avg_feed_quality_score": round(sum(score_values) / len(score_values), 8) if score_values else None,
    }
