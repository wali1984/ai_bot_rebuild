"""F013 regression: proportional data-quality downrating in confidence calibration.

The legacy absolute penalty (1 - 0.015 * missing_count) saturated to zero at 67
missing features. After the A+ feature-spec expansion (203 -> 238 features)
typical live tensors carry 40-70 masked optional/alt-data fields, which
collapsed EVERY calibrated confidence to exactly the 0.5 neutral point and
deadlocked all confidence-floor gates (side floors 0.55, exploration 0.54).
"""
from __future__ import annotations

import pytest

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (
    calibrate_confidence,
)


def test_proportional_penalty_does_not_collapse_at_high_missing_count() -> None:
    result = calibrate_confidence(
        raw_probability=0.63,
        data_coverage_percent=75.0,
        missing_feature_count=60,
        stale_feature_count=0,
        total_feature_count=238,
    )
    assert result["calibration_source"] == "temperature_plus_proportional_data_quality_downrating"
    # 60/238 missing must degrade, not erase: strictly between 0.5 and raw.
    assert 0.5 < result["confidence_calibrated"] < 0.63
    assert result["missing_penalty"] == pytest.approx(1.0 - 0.75 * (60 / 238), abs=1e-9)


def test_proportional_penalty_floors_at_quarter_never_zero() -> None:
    result = calibrate_confidence(
        raw_probability=0.9,
        data_coverage_percent=50.0,
        missing_feature_count=238,
        stale_feature_count=238,
        total_feature_count=238,
    )
    assert result["missing_penalty"] == 0.25
    assert result["stale_penalty"] >= 0.25
    assert result["confidence_calibrated"] > 0.5  # degraded, not neutralized


def test_legacy_absolute_penalty_preserved_without_total() -> None:
    legacy = calibrate_confidence(
        raw_probability=0.63,
        data_coverage_percent=75.0,
        missing_feature_count=60,
        stale_feature_count=0,
    )
    assert legacy["calibration_source"] == "temperature_plus_data_quality_downrating"
    # Documents the saturation defect the proportional form fixes.
    assert legacy["missing_penalty"] == pytest.approx(0.1)
    assert legacy["confidence_calibrated"] == pytest.approx(0.5, abs=0.02)


def test_downrating_direction_monotonic_in_missing_fraction() -> None:
    low = calibrate_confidence(
        raw_probability=0.7, data_coverage_percent=90.0,
        missing_feature_count=10, stale_feature_count=0, total_feature_count=238,
    )
    high = calibrate_confidence(
        raw_probability=0.7, data_coverage_percent=90.0,
        missing_feature_count=120, stale_feature_count=0, total_feature_count=238,
    )
    assert high["confidence_calibrated"] < low["confidence_calibrated"]
    assert high["confidence_calibrated"] > 0.5
