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
        temperature=1.0,
        calibration_fitted=True,
    )
    assert result["calibration_source"] == (
        "checkpoint_bound_train_only_logit_scale_probability"
    )
    # The fitted probability keeps one meaning. Data quality is a separate
    # admission score rather than silently rewriting that probability.
    assert result["confidence_calibrated"] == pytest.approx(0.63)
    assert 0.5 < result["confidence_quality_adjusted_for_admission"] < 0.63
    assert result["missing_penalty"] == pytest.approx(1.0 - (60 / 238), abs=1e-9)


def test_complete_missingness_fails_closed_without_a_static_floor() -> None:
    result = calibrate_confidence(
        raw_probability=0.9,
        data_coverage_percent=50.0,
        missing_feature_count=238,
        stale_feature_count=238,
        total_feature_count=238,
        temperature=1.0,
        calibration_fitted=True,
    )
    assert result["missing_penalty"] == 0.0
    assert result["stale_penalty"] == 0.0
    assert result["confidence_calibrated"] == pytest.approx(0.9)
    assert result["confidence_quality_adjusted_for_admission"] == 0.5


def test_missing_total_feature_count_fails_quality_admission_closed() -> None:
    legacy = calibrate_confidence(
        raw_probability=0.63,
        data_coverage_percent=75.0,
        missing_feature_count=60,
        stale_feature_count=0,
        temperature=1.0,
        calibration_fitted=True,
    )
    assert legacy["calibration_source"] == (
        "checkpoint_bound_train_only_logit_scale_probability"
    )
    assert legacy["missing_penalty"] == 0.0
    assert legacy["stale_penalty"] == 0.0
    assert legacy["confidence_calibrated"] == pytest.approx(0.63)
    assert legacy["confidence_quality_adjusted_for_admission"] == 0.5


def test_downrating_direction_monotonic_in_missing_fraction() -> None:
    low = calibrate_confidence(
        raw_probability=0.7, data_coverage_percent=90.0,
        missing_feature_count=10, stale_feature_count=0, total_feature_count=238,
        temperature=1.0, calibration_fitted=True,
    )
    high = calibrate_confidence(
        raw_probability=0.7, data_coverage_percent=90.0,
        missing_feature_count=120, stale_feature_count=0, total_feature_count=238,
        temperature=1.0, calibration_fitted=True,
    )
    assert high["confidence_calibrated"] == low["confidence_calibrated"]
    assert (
        high["confidence_quality_adjusted_for_admission"]
        < low["confidence_quality_adjusted_for_admission"]
    )
    assert high["confidence_quality_adjusted_for_admission"] > 0.5
