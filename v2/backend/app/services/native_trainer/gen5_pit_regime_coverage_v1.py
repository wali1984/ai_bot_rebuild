"""Point-in-time regime coverage proof for a serving-compatible dataset.

The regime assignment is evaluation metadata, not a model input or trading
authority.  Its only fitted value is the true-range median computed from the
training split; validation and holdout rows cannot influence that threshold.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "gen5_pit_regime_coverage_v1"
REGIME_FEATURES = ("ema_12", "ema_26", "true_range_pct")
SPLITS = ("train", "validation", "holdout")
REGIMES = (
    "DOWN_HIGH_VOL",
    "DOWN_LOW_VOL",
    "UP_HIGH_VOL",
    "UP_LOW_VOL",
)
MINIMUM_ROWS_PER_REGIME_SPLIT = 5


class Gen5RegimeCoverageError(ValueError):
    """Raised when regime evidence is malformed or not point-in-time safe."""


def _sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _utc(value: object, *, reason: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise Gen5RegimeCoverageError(reason)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Gen5RegimeCoverageError(reason) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise Gen5RegimeCoverageError(reason)
    return parsed.astimezone(UTC)


def _finite(value: object, *, reason: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise Gen5RegimeCoverageError(reason)
    result = float(value)
    if not math.isfinite(result):
        raise Gen5RegimeCoverageError(reason)
    return result


def _verified_projection(
    row: Mapping[str, Any],
    *,
    indexes: Mapping[str, int],
    feature_count: int,
) -> dict[str, Any]:
    values = row.get("feature_values")
    mask = row.get("missing_mask")
    if (
        not isinstance(values, list)
        or len(values) != feature_count
        or not isinstance(mask, list)
        or len(mask) != feature_count
    ):
        raise Gen5RegimeCoverageError("REGIME_FEATURE_VECTOR_INVALID")
    if any(bool(mask[indexes[name]]) for name in REGIME_FEATURES):
        raise Gen5RegimeCoverageError("REGIME_REQUIRED_FEATURE_MISSING")
    feature_cutoff = _utc(row.get("feature_cutoff"), reason="FEATURE_CUTOFF_INVALID")
    record_available_at = _utc(row.get("record_available_at"), reason="RECORD_AVAILABLE_AT_INVALID")
    decision_time = _utc(row.get("decision_time"), reason="DECISION_TIME_INVALID")
    if not feature_cutoff <= record_available_at <= decision_time:
        raise Gen5RegimeCoverageError("REGIME_POINT_IN_TIME_ORDER_INVALID")
    latest_closed = row.get("latest_closed_kline_close_time_ms")
    exclusion_decision = row.get("latest_unclosed_exclusion_decision_time_ms")
    decision_ms = int(decision_time.timestamp() * 1_000)
    if (
        row.get("latest_unclosed_kline_excluded") is not True
        or type(latest_closed) is not int
        or type(exclusion_decision) is not int
        or not latest_closed <= exclusion_decision <= decision_ms
    ):
        raise Gen5RegimeCoverageError("REGIME_FEATURE_FINALITY_INVALID")
    split = row.get("split")
    if split not in SPLITS:
        raise Gen5RegimeCoverageError("REGIME_SPLIT_INVALID")
    row_id = row.get("row_id")
    if not isinstance(row_id, str) or not row_id:
        raise Gen5RegimeCoverageError("REGIME_ROW_ID_INVALID")
    return {
        "row_id": row_id,
        "split": split,
        "decision_time": row["decision_time"],
        "ema_12": _finite(values[indexes["ema_12"]], reason="REGIME_EMA_12_INVALID"),
        "ema_26": _finite(values[indexes["ema_26"]], reason="REGIME_EMA_26_INVALID"),
        "true_range_pct": _finite(
            values[indexes["true_range_pct"]], reason="REGIME_TRUE_RANGE_INVALID"
        ),
    }


def build_pit_regime_coverage_v1(dataset: Mapping[str, Any]) -> dict[str, Any]:
    """Build deterministic train-fit regime coverage evidence."""

    names = dataset.get("ordered_feature_names")
    rows = dataset.get("rows")
    if (
        not isinstance(names, list)
        or not names
        or len(names) != len(set(names))
        or not isinstance(rows, list)
        or not rows
    ):
        raise Gen5RegimeCoverageError("REGIME_DATASET_INVALID")
    if any(name not in names for name in REGIME_FEATURES):
        raise Gen5RegimeCoverageError("REGIME_FEATURE_SET_MISSING")
    indexes = {name: names.index(name) for name in REGIME_FEATURES}
    projections = [
        _verified_projection(row, indexes=indexes, feature_count=len(names))
        for row in rows
        if isinstance(row, Mapping)
    ]
    if len(projections) != len(rows):
        raise Gen5RegimeCoverageError("REGIME_ROW_NOT_OBJECT")
    train = [row for row in projections if row["split"] == "train"]
    if not train or any(not any(row["split"] == split for row in projections) for split in SPLITS):
        raise Gen5RegimeCoverageError("REGIME_SPLIT_EMPTY")
    volatility_threshold = float(statistics.median(row["true_range_pct"] for row in train))
    counts: dict[str, dict[str, int]] = {}
    assigned: list[dict[str, Any]] = []
    for row in projections:
        trend = "UP" if row["ema_12"] >= row["ema_26"] else "DOWN"
        volatility = "HIGH_VOL" if row["true_range_pct"] >= volatility_threshold else "LOW_VOL"
        regime = f"{trend}_{volatility}"
        assigned.append({**row, "regime": regime})
    for split in SPLITS:
        split_counts = Counter(row["regime"] for row in assigned if row["split"] == split)
        counts[split] = {regime: int(split_counts.get(regime, 0)) for regime in REGIMES}
    minimum_satisfied = all(
        counts[split][regime] >= MINIMUM_ROWS_PER_REGIME_SPLIT
        for split in SPLITS
        for regime in REGIMES
    )
    train_fit_rows = [row for row in projections if row["split"] == "train"]
    material: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": dataset.get("dataset_id"),
        "dataset_sha256": dataset.get("dataset_sha256"),
        "feature_abi_sha256": dataset.get("feature_abi_sha256"),
        "purpose": "COVERAGE_EVALUATION_ONLY_NOT_MODEL_INPUT_OR_TRADING_AUTHORITY",
        "regime_features": list(REGIME_FEATURES),
        "regime_feature_positions": indexes,
        "trend_semantics": "UP_IF_EMA_12_GTE_EMA_26_ELSE_DOWN",
        "volatility_semantics": "HIGH_IF_TRUE_RANGE_PCT_GTE_TRAIN_MEDIAN_ELSE_LOW",
        "threshold_fit_split": "train",
        "volatility_threshold": volatility_threshold,
        "threshold_fit_row_count": len(train_fit_rows),
        "threshold_fit_rows_sha256": _sha256(train_fit_rows),
        "all_evaluation_rows_sha256": _sha256(projections),
        "regime_counts_by_split": counts,
        "minimum_rows_per_regime_per_split": MINIMUM_ROWS_PER_REGIME_SPLIT,
        "all_four_regimes_present_in_every_split": all(
            counts[split][regime] > 0 for split in SPLITS for regime in REGIMES
        ),
        "minimum_regime_rows_satisfied": minimum_satisfied,
        "point_in_time_and_finality_reverified": True,
        "holdout_influences_threshold": False,
        "regime_coverage_proven": minimum_satisfied,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }
    return {**material, "evidence_sha256": _sha256(material)}


__all__ = [
    "Gen5RegimeCoverageError",
    "MINIMUM_ROWS_PER_REGIME_SPLIT",
    "build_pit_regime_coverage_v1",
]
