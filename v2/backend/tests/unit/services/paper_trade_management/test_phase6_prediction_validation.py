"""Phase 6 — Prediction validation schema tests.

Validates:
 - enrich_prediction_for_phase6() adds all required fields
 - validate_phase6_schema() catches missing/null violations
 - backfill_realized_outcome() updates only realized_* fields
 - build_accuracy_report() groups by symbol/timeframe/direction/strategy_family
 - All required Phase 6 fields are non-null on enriched payload (except nullable ones)
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.services.paper_trade_management.prediction_accuracy_tracker import (
    NULLABLE_PHASE6_FIELDS,
    REQUIRED_PHASE6_FIELDS,
    AccuracyBucket,
    backfill_realized_outcome,
    build_accuracy_report,
    enrich_prediction_for_phase6,
    validate_phase6_schema,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_prediction(**overrides) -> dict:
    base = {
        "prediction_id": "pred_abc123",
        "symbol": "BTCUSDT",
        "timeframe": "1h",
        "selected_action": "short",
        "expected_move_bps": -120.0,
        "expected_move_after_cost_bps": -132.0,
        "confidence_raw": 1.0,
        "confidence_calibrated": 0.689,
        "data_coverage_percent": 77.03,
        "missing_feature_names": ["nansen_score", "lunarcrush_score"],
        "market_state_integrity_score": 96.25,
        "feature_freshness_state": "FRESH",
        "prediction_source_classification": "REAL_MODEL",
        "trainer_source": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER",
        "model_source": "v2_native_rl",
        "checkpoint_id": "ckpt_abc",
    }
    base.update(overrides)
    return base


# ── Required fields ───────────────────────────────────────────────────────────

def test_all_required_phase6_fields_present_after_enrichment() -> None:
    pred = _make_prediction()
    enriched = enrich_prediction_for_phase6(pred)
    missing = [f for f in REQUIRED_PHASE6_FIELDS if f not in enriched]
    assert missing == [], f"Fields missing after enrichment: {missing}"


def test_non_nullable_fields_are_not_none_after_enrichment() -> None:
    pred = _make_prediction()
    enriched = enrich_prediction_for_phase6(pred)
    violations = validate_phase6_schema(enriched)
    assert violations == [], f"Schema violations: {violations}"


def test_nullable_fields_may_be_none() -> None:
    pred = _make_prediction()
    enriched = enrich_prediction_for_phase6(pred)
    for f in NULLABLE_PHASE6_FIELDS:
        # These may be None — no violation expected
        pass
    violations = validate_phase6_schema(enriched)
    assert violations == []


# ── Direction derivation ──────────────────────────────────────────────────────

def test_direction_derived_from_selected_action_short() -> None:
    enriched = enrich_prediction_for_phase6(_make_prediction(selected_action="short"))
    assert enriched["direction"] == "short"


def test_direction_derived_from_selected_action_long() -> None:
    enriched = enrich_prediction_for_phase6(_make_prediction(selected_action="long"))
    assert enriched["direction"] == "long"


def test_direction_derived_from_hold_is_flat() -> None:
    enriched = enrich_prediction_for_phase6(_make_prediction(selected_action="hold"))
    assert enriched["direction"] == "flat"


def test_direction_not_overwritten_if_already_present() -> None:
    pred = _make_prediction()
    pred["direction"] = "long"
    enriched = enrich_prediction_for_phase6(pred)
    assert enriched["direction"] == "long"


# ── Strategy family ───────────────────────────────────────────────────────────

def test_strategy_family_is_trend_short_for_short_action() -> None:
    enriched = enrich_prediction_for_phase6(_make_prediction(selected_action="short"))
    assert enriched["strategy_family"] == "trend_short"


def test_strategy_family_is_exit_for_close_long() -> None:
    enriched = enrich_prediction_for_phase6(_make_prediction(selected_action="close_long"))
    assert enriched["strategy_family"] == "exit"


def test_strategy_family_is_neutral_for_hold() -> None:
    enriched = enrich_prediction_for_phase6(_make_prediction(selected_action="hold"))
    assert enriched["strategy_family"] == "neutral"


# ── Price target / coverage ───────────────────────────────────────────────────

def test_price_target_bps_derived_from_expected_move_bps() -> None:
    enriched = enrich_prediction_for_phase6(_make_prediction(expected_move_bps=-120.0))
    assert enriched["price_target_bps"] == -120.0


def test_data_coverage_pct_derived_from_data_coverage_percent() -> None:
    enriched = enrich_prediction_for_phase6(_make_prediction(data_coverage_percent=77.03))
    assert enriched["data_coverage_pct"] == 77.03


# ── Feature codes fallback ────────────────────────────────────────────────────

def test_top_feature_codes_empty_when_no_source() -> None:
    pred = _make_prediction()
    # No feature importance / SHAP data
    enriched = enrich_prediction_for_phase6(pred)
    assert isinstance(enriched["top_positive_feature_codes"], list)
    assert isinstance(enriched["top_negative_feature_codes"], list)


def test_top_feature_codes_used_from_existing_fields() -> None:
    pred = _make_prediction()
    pred["top_positive_feature_codes"] = ["funding_rate", "ob_imbalance"]
    enriched = enrich_prediction_for_phase6(pred)
    assert enriched["top_positive_feature_codes"] == ["funding_rate", "ob_imbalance"]


# ── Realized outcome (nullable back-fill) ────────────────────────────────────

def test_realized_fields_are_null_before_backfill() -> None:
    enriched = enrich_prediction_for_phase6(_make_prediction())
    assert enriched["realized_outcome_direction"] is None
    assert enriched["realized_outcome_bps"] is None
    assert enriched["realized_at_ms"] is None


def test_backfill_realized_outcome_updates_existing_key() -> None:
    pred = _make_prediction()
    enriched = enrich_prediction_for_phase6(pred)
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps(enriched)
    result = backfill_realized_outcome(
        symbol="BTCUSDT",
        timeframe="1h",
        prediction_id="pred_abc123",
        realized_outcome_direction="short",
        realized_outcome_bps=-42.5,
        realized_at_ms=1718000000000,
        redis_client=mock_redis,
    )
    assert result is True
    mock_redis.set.assert_called_once()
    written = json.loads(mock_redis.set.call_args[0][1])
    assert written["realized_outcome_direction"] == "short"
    assert written["realized_outcome_bps"] == -42.5
    assert written["realized_at_ms"] == 1718000000000


def test_backfill_returns_false_when_key_missing() -> None:
    mock_redis = MagicMock()
    mock_redis.get.return_value = None
    result = backfill_realized_outcome(
        symbol="BTCUSDT",
        timeframe="1h",
        prediction_id="pred_abc123",
        realized_outcome_direction="short",
        realized_outcome_bps=-42.5,
        realized_at_ms=1718000000000,
        redis_client=mock_redis,
    )
    assert result is False


def test_backfill_returns_false_when_prediction_id_mismatch() -> None:
    pred = _make_prediction()
    enriched = enrich_prediction_for_phase6(pred)
    mock_redis = MagicMock()
    mock_redis.get.return_value = json.dumps(enriched)
    result = backfill_realized_outcome(
        symbol="BTCUSDT",
        timeframe="1h",
        prediction_id="WRONG_ID",
        realized_outcome_direction="short",
        realized_outcome_bps=-42.5,
        realized_at_ms=1718000000000,
        redis_client=mock_redis,
    )
    assert result is False
    mock_redis.set.assert_not_called()


# ── Accuracy report ───────────────────────────────────────────────────────────

def test_accuracy_report_groups_by_symbol_tf_direction() -> None:
    predictions = [
        enrich_prediction_for_phase6(_make_prediction(symbol="BTCUSDT", timeframe="1h", selected_action="short")),
        enrich_prediction_for_phase6(_make_prediction(symbol="BTCUSDT", timeframe="1h", selected_action="short")),
        enrich_prediction_for_phase6(_make_prediction(symbol="BTCUSDT", timeframe="4h", selected_action="long")),
        enrich_prediction_for_phase6(_make_prediction(symbol="ETHUSDT", timeframe="1h", selected_action="short")),
    ]
    report = build_accuracy_report(predictions=predictions)
    assert report["total_predictions_processed"] == 4
    buckets = report["buckets"]
    assert len(buckets) == 3


def test_accuracy_report_win_rate_computed_from_realized() -> None:
    p1 = enrich_prediction_for_phase6(_make_prediction(selected_action="short"))
    p1["realized_outcome_direction"] = "short"
    p1["realized_outcome_bps"] = -30.0
    p2 = enrich_prediction_for_phase6(_make_prediction(selected_action="short"))
    p2["realized_outcome_direction"] = "long"
    p2["realized_outcome_bps"] = 15.0
    report = build_accuracy_report(predictions=[p1, p2])
    bucket = report["buckets"][0]
    assert bucket["realized_count"] == 2
    assert bucket["correct_direction_count"] == 1
    assert bucket["win_rate"] == 0.5


def test_accuracy_report_win_rate_none_when_no_realized() -> None:
    predictions = [enrich_prediction_for_phase6(_make_prediction())]
    report = build_accuracy_report(predictions=predictions)
    assert report["buckets"][0]["win_rate"] is None


def test_accuracy_report_has_schema_version() -> None:
    report = build_accuracy_report(predictions=[])
    assert report["schema_version"] == "v2_prediction_accuracy_report_v1"


# ── Schema validation ─────────────────────────────────────────────────────────

def test_validate_catches_missing_required_field() -> None:
    enriched = enrich_prediction_for_phase6(_make_prediction())
    del enriched["direction"]
    violations = validate_phase6_schema(enriched)
    assert any("direction" in v for v in violations)


def test_validate_catches_null_non_nullable_field() -> None:
    enriched = enrich_prediction_for_phase6(_make_prediction())
    enriched["direction"] = None
    violations = validate_phase6_schema(enriched)
    assert any("NULL_NON_NULLABLE" in v and "direction" in v for v in violations)


def test_validate_passes_with_all_fields() -> None:
    enriched = enrich_prediction_for_phase6(_make_prediction())
    violations = validate_phase6_schema(enriched)
    assert violations == []
