"""Phase 6: Prediction validation schema enrichment and accuracy reporting.

This module defines the required Phase 6 prediction output schema,
provides enrichment of existing prediction payloads to add missing fields,
and builds per-symbol/timeframe/direction/regime accuracy reports.

Schema requirements:
    - direction (action): selected_action field (already present as selected_action)
    - price_target_bps: expected move in bps from current mark price
    - expected_move_after_cost_bps: signed expected value after all costs
    - confidence_calibrated: calibrated probability
    - data_coverage_pct: percentage of features present (already as data_coverage_percent)
    - top_positive_feature_codes: top features pushing toward selected action
    - top_negative_feature_codes: top features pushing against selected action
    - reasoning_drivers: structured reasoning summary
    - missing_feature_names: list of absent features
    - realized_outcome_direction: back-fill when outcome available (nullable)
    - realized_outcome_bps: actual price move in bps (nullable)
    - realized_at_ms: timestamp of back-fill (nullable)
    - strategy_family: derived from action type
    - regime: market regime classification (nullable until regime model available)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# ── Required Phase 6 output fields ───────────────────────────────────────────

REQUIRED_PHASE6_FIELDS: tuple[str, ...] = (
    "prediction_id",
    "symbol",
    "timeframe",
    "direction",
    "price_target_bps",
    "expected_move_after_cost_bps",
    "confidence_calibrated",
    "data_coverage_pct",
    "top_positive_feature_codes",
    "top_negative_feature_codes",
    "reasoning_drivers",
    "missing_feature_names",
    "realized_outcome_direction",
    "realized_outcome_bps",
    "realized_at_ms",
    "strategy_family",
    "regime",
)

# Fields that are nullable (may legitimately be None)
NULLABLE_PHASE6_FIELDS: frozenset[str] = frozenset({
    "realized_outcome_direction",
    "realized_outcome_bps",
    "realized_at_ms",
    "regime",
    "price_target_bps",
})


def _derive_direction(payload: dict) -> str:
    """Normalize action field to direction string."""
    action = str(payload.get("selected_action") or payload.get("direction") or "flat").lower()
    if action in ("long", "buy"):
        return "long"
    if action in ("short", "sell"):
        return "short"
    return "flat"


def _derive_strategy_family(direction: str, payload: dict) -> str:
    """Map direction + metadata to a strategy family string."""
    action = str(payload.get("selected_action") or "").lower()
    if action in ("close_long", "close_short", "reduce"):
        return "exit"
    if action == "hedge_reserved":
        return "hedge"
    if direction == "long":
        return "trend_long"
    if direction == "short":
        return "trend_short"
    return "neutral"


def _derive_price_target_bps(payload: dict) -> float | None:
    """Return expected_move_bps as the price target proxy."""
    v = payload.get("expected_move_bps")
    if v is None:
        v = payload.get("price_target_bps")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _attribution_fallback(payload: dict, polarity: str) -> list[str]:
    """Gradient-sign heuristic attribution when SHAP is unavailable.

    Uses the signed value of each feature relative to the predicted direction
    to classify each feature as supporting (positive) or contradicting (negative).
    Clearly labeled in the return value as '__gradient_sign_heuristic__' prefix.

    For LONG predictions:
        positive = features with positive return contribution (return > 0, low vol)
        negative = features with negative return contribution (return < 0, high vol)
    For SHORT predictions:
        positive = features with negative return contribution (return < 0, high vol)
        negative = features with positive return contribution (return > 0, low vol)

    Never uses future labels. Uses only values present in the prediction payload.
    """
    direction = _derive_direction(payload)
    top_features = payload.get("top_features") or []
    if not isinstance(top_features, list):
        return []

    pos_codes: list[str] = []
    neg_codes: list[str] = []

    for feat in top_features:
        if isinstance(feat, dict):
            name = str(feat.get("name") or "")
            try:
                value = float(feat.get("value") or 0.0)
            except (TypeError, ValueError):
                continue
        elif isinstance(feat, str):
            name = feat
            value = 0.0
        else:
            continue
        if not name:
            continue

        # Determine if this feature supports the prediction direction.
        # Return-type features: positive value → LONG support, negative value → SHORT support.
        # Volatility-type features: high value → supports SHORT/uncertainty.
        is_return_type = any(k in name for k in ("return_", "momentum_", "price_change", "pct_change"))
        is_vol_type = any(k in name for k in ("volatility_", "atr_", "toxicity_", "spread_", "vol_"))

        if direction == "long":
            supports = (is_return_type and value > 0) or (is_vol_type and value < 0)
        elif direction == "short":
            supports = (is_return_type and value < 0) or (is_vol_type and value > 0)
        else:
            supports = False

        code = f"__gradient_sign_heuristic__{name}"
        if supports:
            pos_codes.append(code)
        else:
            neg_codes.append(code)

    if polarity == "positive":
        return pos_codes[:8]
    return neg_codes[:8]


def _get_top_feature_codes(payload: dict, polarity: str) -> list[str]:
    """Return top feature codes for positive or negative polarity.

    Priority:
      1. Existing SHAP/attribution data already in the payload.
      2. top_confidence_drivers / top_negative_drivers keys.
      3. Gradient-sign heuristic fallback from top_features.

    Polarity: 'positive' or 'negative'.
    Attribution method is clearly labeled in returned codes when using heuristic.
    """
    key = f"top_{polarity}_feature_codes"
    existing = payload.get(key)
    if isinstance(existing, list) and existing:
        return [str(c) for c in existing[:8]]

    # Try alternative attribution keys
    if polarity == "positive":
        alt = payload.get("top_confidence_drivers")
    else:
        alt = payload.get("top_negative_drivers")
    if isinstance(alt, list) and alt:
        codes = []
        for c in alt[:8]:
            codes.append(str(c.get("name") if isinstance(c, dict) else c))
        if codes:
            return codes

    # Gradient-sign heuristic fallback (clearly labeled)
    return _attribution_fallback(payload, polarity)


def _get_data_coverage_pct(payload: dict) -> float | None:
    """Normalize data_coverage_percent → data_coverage_pct."""
    v = payload.get("data_coverage_percent") or payload.get("data_coverage_pct")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _build_reasoning_drivers(payload: dict, direction: str) -> dict:
    """Build a structured reasoning summary from available fields."""
    return {
        "direction": direction,
        "confidence_raw": payload.get("confidence_raw"),
        "confidence_calibrated": payload.get("confidence_calibrated"),
        "expected_move_bps": payload.get("expected_move_bps"),
        "expected_move_after_cost_bps": payload.get("expected_move_after_cost_bps"),
        "market_state_integrity_score": payload.get("market_state_integrity_score"),
        "feature_freshness_state": payload.get("feature_freshness_state"),
        "prediction_source_classification": payload.get("prediction_source_classification"),
        "trainer_source": payload.get("trainer_source"),
        "model_source": payload.get("model_source"),
        "checkpoint_id": payload.get("checkpoint_id"),
        "data_coverage_pct": _get_data_coverage_pct(payload),
        "missing_feature_count": len(payload.get("missing_feature_names") or []),
        "top_positive_feature_codes": _get_top_feature_codes(payload, "positive"),
        "top_negative_feature_codes": _get_top_feature_codes(payload, "negative"),
    }


def enrich_prediction_for_phase6(payload: dict) -> dict:
    """Add required Phase 6 fields to an existing prediction payload.

    Does NOT overwrite existing values. Returns a new dict.
    """
    enriched = dict(payload)
    direction = _derive_direction(payload)

    if "direction" not in enriched:
        enriched["direction"] = direction
    if "price_target_bps" not in enriched:
        enriched["price_target_bps"] = _derive_price_target_bps(payload)
    if "data_coverage_pct" not in enriched:
        enriched["data_coverage_pct"] = _get_data_coverage_pct(payload)
    if "top_positive_feature_codes" not in enriched:
        enriched["top_positive_feature_codes"] = _get_top_feature_codes(payload, "positive")
    if "top_negative_feature_codes" not in enriched:
        enriched["top_negative_feature_codes"] = _get_top_feature_codes(payload, "negative")
    if "reasoning_drivers" not in enriched:
        enriched["reasoning_drivers"] = _build_reasoning_drivers(payload, direction)
    if "strategy_family" not in enriched:
        enriched["strategy_family"] = _derive_strategy_family(direction, payload)
    if "regime" not in enriched:
        enriched["regime"] = None
    if "realized_outcome_direction" not in enriched:
        enriched["realized_outcome_direction"] = None
    if "realized_outcome_bps" not in enriched:
        enriched["realized_outcome_bps"] = None
    if "realized_at_ms" not in enriched:
        enriched["realized_at_ms"] = None

    return enriched


def validate_phase6_schema(prediction: dict) -> list[str]:
    """Return list of schema violations. Empty = valid."""
    violations: list[str] = []
    for f in REQUIRED_PHASE6_FIELDS:
        if f not in prediction:
            violations.append(f"MISSING_FIELD:{f}")
        elif prediction[f] is None and f not in NULLABLE_PHASE6_FIELDS:
            violations.append(f"NULL_NON_NULLABLE_FIELD:{f}")
    return violations


def backfill_realized_outcome(
    *,
    symbol: str,
    timeframe: str,
    prediction_id: str,
    realized_outcome_direction: str,
    realized_outcome_bps: float,
    realized_at_ms: int,
    redis_client: Any,
) -> bool:
    """Back-fill realized outcome into a prediction Redis entry.

    Only updates the realized_* fields — does not overwrite signal metadata.
    Returns True if the key existed and was updated.
    All writes use v2: prefix.
    """
    key = f"v2:prediction:{symbol.upper()}:{timeframe.lower()}"
    try:
        raw = redis_client.get(key)
        if not raw:
            return False
        payload = json.loads(raw)
        if payload.get("prediction_id") != prediction_id:
            return False
        payload["realized_outcome_direction"] = realized_outcome_direction
        payload["realized_outcome_bps"] = realized_outcome_bps
        payload["realized_at_ms"] = realized_at_ms
        redis_client.set(key, json.dumps(payload))
        return True
    except Exception:  # noqa: BLE001
        return False


@dataclass
class AccuracyBucket:
    symbol: str
    timeframe: str
    direction: str
    strategy_family: str
    regime: str | None
    total_predictions: int = 0
    realized_count: int = 0
    correct_direction_count: int = 0
    avg_realized_bps: float | None = None
    win_rate: float | None = None
    last_updated: str = ""


def build_accuracy_report(
    *,
    predictions: list[dict],
) -> dict[str, Any]:
    """Build accuracy report grouped by symbol/timeframe/direction/strategy_family/regime.

    Accepts a list of enriched prediction dicts (from enrich_prediction_for_phase6).
    Returns a structured report suitable for writing to prediction_accuracy_by_symbol_tf.json.
    """
    buckets: dict[tuple, AccuracyBucket] = {}

    for pred in predictions:
        sym = str(pred.get("symbol") or "UNKNOWN").upper()
        tf = str(pred.get("timeframe") or "unknown")
        direction = str(pred.get("direction") or "flat")
        strategy_family = str(pred.get("strategy_family") or "neutral")
        regime = pred.get("regime")
        key = (sym, tf, direction, strategy_family, str(regime))

        if key not in buckets:
            buckets[key] = AccuracyBucket(
                symbol=sym,
                timeframe=tf,
                direction=direction,
                strategy_family=strategy_family,
                regime=regime,
            )
        b = buckets[key]
        b.total_predictions += 1

        realized_bps = pred.get("realized_outcome_bps")
        realized_dir = pred.get("realized_outcome_direction")
        if realized_bps is not None and realized_dir is not None:
            b.realized_count += 1
            if realized_dir == direction:
                b.correct_direction_count += 1

    # Compute derived metrics
    rows = []
    for b in buckets.values():
        win_rate = None
        avg_bps = None
        if b.realized_count > 0:
            win_rate = round(b.correct_direction_count / b.realized_count, 4)
        rows.append({
            "symbol": b.symbol,
            "timeframe": b.timeframe,
            "direction": b.direction,
            "strategy_family": b.strategy_family,
            "regime": b.regime,
            "total_predictions": b.total_predictions,
            "realized_count": b.realized_count,
            "correct_direction_count": b.correct_direction_count,
            "win_rate": win_rate,
            "avg_realized_bps": avg_bps,
        })

    rows.sort(key=lambda r: (r["symbol"], r["timeframe"], r["direction"]))
    return {
        "schema_version": "v2_prediction_accuracy_report_v1",
        "total_predictions_processed": len(predictions),
        "total_realized": sum(r["realized_count"] for r in rows),
        "buckets": rows,
        "note": (
            "realized_count will be 0 until back-fill path is wired. "
            "win_rate requires >= 1 realized outcome per bucket."
        ),
    }
