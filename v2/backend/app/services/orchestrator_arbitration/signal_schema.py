"""V2 signal schema (PaperOnly).

Defines the canonical ``V2Signal`` dataclass and ``validate_signal``. The
schema mirrors the input-side fields required by the legacy orchestrator
worker (``rl/orchestrator_worker.py``) but is V2-native and free of any
Redis/exchange coupling.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Tuple

V2SIGNAL_SIDE_LONG = "long"
V2SIGNAL_SIDE_SHORT = "short"
V2SIGNAL_ALLOWED_SIDES: Tuple[str, ...] = (V2SIGNAL_SIDE_LONG, V2SIGNAL_SIDE_SHORT)

V2SIGNAL_REQUIRED_FIELDS: Tuple[str, ...] = (
    "signal_id",
    "symbol",
    "side",
    "confidence_raw",
    "confidence_calibrated",
    "expected_move_after_cost_bps",
    "source_prediction_id",
    "feature_snapshot_id",
    "generated_utc",
    "freshness_seconds",
    "model_version",
)


@dataclass(frozen=True)
class V2Signal:
    signal_id: str
    symbol: str
    side: str
    confidence_raw: float
    confidence_calibrated: float
    expected_move_after_cost_bps: float
    source_prediction_id: str
    feature_snapshot_id: str
    generated_utc: str
    freshness_seconds: float
    model_version: str


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _check_unit_interval(name: str, value: Any) -> float:
    if not _is_finite_number(value):
        raise ValueError(f"{name} must be a finite number")
    f_value = float(value)
    if not 0.0 <= f_value <= 1.0:
        raise ValueError(f"{name} must be in [0.0, 1.0]")
    return f_value


def _check_non_empty_string(name: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{name} must be non-empty")
    return stripped


def validate_signal(payload: Dict[str, Any]) -> V2Signal:
    """Validate a raw dict and return a frozen ``V2Signal``.

    Raises ``ValueError`` with an explicit field reason on any failure.
    """
    if not isinstance(payload, dict):
        raise ValueError("signal payload must be a dict")

    missing = [key for key in V2SIGNAL_REQUIRED_FIELDS if key not in payload]
    if missing:
        raise ValueError(
            "missing_required_fields:" + ",".join(sorted(missing))
        )

    signal_id = _check_non_empty_string("signal_id", payload["signal_id"])
    symbol = _check_non_empty_string("symbol", payload["symbol"]).upper()
    side = _check_non_empty_string("side", payload["side"]).lower()
    if side not in V2SIGNAL_ALLOWED_SIDES:
        raise ValueError(
            f"side must be one of {V2SIGNAL_ALLOWED_SIDES}"
        )

    confidence_raw = _check_unit_interval(
        "confidence_raw", payload["confidence_raw"]
    )
    confidence_calibrated = _check_unit_interval(
        "confidence_calibrated", payload["confidence_calibrated"]
    )

    expected_move = payload["expected_move_after_cost_bps"]
    if not _is_finite_number(expected_move):
        raise ValueError("expected_move_after_cost_bps must be a finite number")

    source_prediction_id = _check_non_empty_string(
        "source_prediction_id", payload["source_prediction_id"]
    )
    feature_snapshot_id = _check_non_empty_string(
        "feature_snapshot_id", payload["feature_snapshot_id"]
    )
    generated_utc = _check_non_empty_string(
        "generated_utc", payload["generated_utc"]
    )

    freshness_seconds = payload["freshness_seconds"]
    if not _is_finite_number(freshness_seconds) or float(freshness_seconds) < 0.0:
        raise ValueError("freshness_seconds must be a finite non-negative number")

    model_version = _check_non_empty_string(
        "model_version", payload["model_version"]
    )

    return V2Signal(
        signal_id=signal_id,
        symbol=symbol,
        side=side,
        confidence_raw=confidence_raw,
        confidence_calibrated=confidence_calibrated,
        expected_move_after_cost_bps=float(expected_move),
        source_prediction_id=source_prediction_id,
        feature_snapshot_id=feature_snapshot_id,
        generated_utc=generated_utc,
        freshness_seconds=float(freshness_seconds),
        model_version=model_version,
    )
