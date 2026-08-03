"""Read-only high-confidence loss mining for Phase 3 recovery."""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Mapping


SCHEMA_VERSION = "phase3_high_confidence_loss_miner_v1"
DEFAULT_HIGH_CONFIDENCE = 0.55
DEFAULT_QUARANTINE_MIN_COUNT = 2


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_time(value: Any) -> datetime | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            return None
        if number > 10_000_000_000:
            number /= 1000.0
        try:
            return datetime.fromtimestamp(number, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
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


def _trust_reject_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    decision_time = _parse_time(row.get("decision_time") or row.get("decision_time_est"))
    available_at = _parse_time(row.get("available_at"))
    feature_cutoff = _parse_time(row.get("feature_cutoff"))
    if available_at is not None and decision_time is not None and available_at > decision_time:
        reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
    if feature_cutoff is not None and decision_time is not None and feature_cutoff > decision_time:
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    candle_closed = row.get("candle_closed_confirmed")
    if candle_closed is False:
        reasons.append("UNFINISHED_CANDLE")
    return reasons


def _side(row: Mapping[str, Any]) -> str:
    return str(
        row.get("selected_action")
        or row.get("counterfactual_side")
        or row.get("action")
        or row.get("side")
        or "unknown"
    ).lower()


def _regime(row: Mapping[str, Any]) -> str:
    return str(
        row.get("market_regime")
        or row.get("market_regime_at_entry")
        or row.get("strategy_market_regime")
        or "UNKNOWN"
    )


def _strategy(row: Mapping[str, Any]) -> str:
    return str(
        row.get("strategy_id")
        or row.get("strategy_mode")
        or row.get("strategy_family")
        or "UNKNOWN"
    )


def _bucket_key(row: Mapping[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("symbol") or "UNKNOWN").upper(),
            str(row.get("timeframe") or "UNKNOWN"),
            _strategy(row),
            _regime(row),
            _side(row),
        ]
    )


def _realized_bps(row: Mapping[str, Any]) -> float | None:
    for key in (
        "realized_after_cost_return_bps",
        "realized_net_pnl_bps",
        "realized_pnl_bps",
        "pnl_effect_bps",
    ):
        value = _float(row.get(key))
        if value is not None:
            return value
    outcome = _as_dict(_as_dict(row.get("outcome_windows")).get(row.get("primary_outcome_window") or "5m"))
    return _float(outcome.get("after_cost_return_bps"))


def _is_completed(row: Mapping[str, Any]) -> bool:
    return _realized_bps(row) is not None


def _is_wrong_or_loss(row: Mapping[str, Any]) -> bool:
    classification = str(row.get("classification") or "").lower()
    if classification in {"false_positive", "false_negative"}:
        return True
    realized = _realized_bps(row)
    return realized is not None and realized < 0.0


def _is_atr_stop(row: Mapping[str, Any]) -> bool:
    text = " ".join(
        str(row.get(key) or "")
        for key in ("exit_reason", "close_reason", "paper_ledger_reason", "risk_reason")
    ).upper()
    return "ATR" in text and "STOP" in text


def _trim_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "prediction_id": row.get("prediction_id") or row.get("entry_prediction_id"),
        "symbol": row.get("symbol"),
        "timeframe": row.get("timeframe"),
        "side": _side(row),
        "strategy_id": _strategy(row),
        "market_regime": _regime(row),
        "confidence_calibrated": row.get("confidence_calibrated"),
        "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
        "realized_after_cost_return_bps": _realized_bps(row),
        "classification": row.get("classification"),
        "exit_reason": row.get("exit_reason") or row.get("close_reason"),
        "bucket_key": _bucket_key(row),
        "trust_reject_reasons": _trust_reject_reasons(row),
    }


def mine_high_confidence_losses(
    rows: list[Mapping[str, Any]],
    *,
    min_confidence: float = DEFAULT_HIGH_CONFIDENCE,
    quarantine_min_count: int = DEFAULT_QUARANTINE_MIN_COUNT,
) -> dict[str, Any]:
    """Classify high-confidence wrong/loss rows without mutating runtime state."""
    normalized = [_as_dict(row) for row in rows]
    completed = [row for row in normalized if _is_completed(row)]
    high_confidence = [
        row
        for row in completed
        if (_float(row.get("confidence_calibrated")) or 0.0) >= min_confidence
    ]
    high_confidence_wrong = [row for row in high_confidence if _is_wrong_or_loss(row)]
    atr_stop_losses = [row for row in high_confidence_wrong if _is_atr_stop(row)]
    bucket_counts = Counter(_bucket_key(row) for row in high_confidence_wrong)
    quarantined = [
        {
            "bucket_key": bucket,
            "high_confidence_loss_count": count,
            "quarantine_recommended": True,
            "quarantine_reason": "HIGH_CONFIDENCE_LOSS_CLUSTER",
        }
        for bucket, count in sorted(bucket_counts.items())
        if count >= quarantine_min_count
    ]
    trust_violations = [
        reason
        for row in high_confidence_wrong
        for reason in _trust_reject_reasons(row)
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "HIGH_CONFIDENCE_LOSS_MINING_READY",
        "row_count": len(normalized),
        "completed_outcome_count": len(completed),
        "high_confidence_threshold": min_confidence,
        "high_confidence_row_count": len(high_confidence),
        "high_confidence_wrong_count": len(high_confidence_wrong),
        "high_confidence_loss_rate": (
            len(high_confidence_wrong) / len(high_confidence) if high_confidence else None
        ),
        "atr_stop_high_confidence_loss_count": len(atr_stop_losses),
        "bucket_loss_counts": dict(sorted(bucket_counts.items())),
        "quarantined_buckets": quarantined,
        "quarantine_min_count": quarantine_min_count,
        "sample_rows": [_trim_row(row) for row in high_confidence_wrong[:50]],
        "pit_trust_violation_counts": dict(Counter(trust_violations)),
        "no_live_mutation": True,
        "runtime_thresholds_changed": False,
    }
