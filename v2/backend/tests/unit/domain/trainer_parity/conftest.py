"""Shared fixtures for trainer_parity domain tests."""

from __future__ import annotations

import sys
from typing import Callable

import pytest

sys.path.insert(0, "")

from v2.backend.app.domain.trainer_parity.feature_status_flags import (
    FeatureFreshnessEnvelope,
    FeatureStatusFlags,
)
from v2.backend.app.domain.trainer_parity.freshness_metadata import FreshnessMetadata
from v2.backend.app.domain.trainer_parity.stage_a_record import (
    ConfidenceExplainability,
    StageATrainerRecord,
)
from v2.backend.app.domain.trainer_parity.stage_b_record import StageBTrainerRecord


@pytest.fixture()
def valid_feature_status_flags() -> FeatureStatusFlags:
    return FeatureStatusFlags(
        stale=("stale_feat",),
        missing=("missing_feat",),
        unused=("unused_feat",),
    )


@pytest.fixture()
def valid_feature_freshness_envelope() -> FeatureFreshnessEnvelope:
    return FeatureFreshnessEnvelope(
        per_source_freshness_ms=(("source_a", 100), ("source_b", 250)),
        oldest_source_age_ms=250,
        oldest_source_name="source_b",
    )


@pytest.fixture()
def valid_freshness_metadata() -> FreshnessMetadata:
    return FreshnessMetadata(
        per_feature_last_update_ms=(("feat_a", 1_000), ("feat_b", 1_500)),
        per_feature_age_ms=(("feat_a", 50), ("feat_b", 25)),
        per_feature_status=(("feat_a", "fresh"), ("feat_b", "warning")),
    )


@pytest.fixture()
def valid_confidence_explainability() -> ConfidenceExplainability:
    return ConfidenceExplainability(
        confidence_components=(("base_score", 0.7), ("calibration_offset", 0.05)),
        confidence_floor_applied=False,
        confidence_ceiling_applied=False,
        calibration_model_version="cal-v1",
        calibration_method="isotonic",
    )


@pytest.fixture()
def valid_stage_a_record(
    valid_feature_status_flags: FeatureStatusFlags,
    valid_feature_freshness_envelope: FeatureFreshnessEnvelope,
    valid_freshness_metadata: FreshnessMetadata,
    valid_confidence_explainability: ConfidenceExplainability,
) -> StageATrainerRecord:
    return StageATrainerRecord(
        prediction_id="pred-1",
        feature_snapshot_id="snap-1",
        symbol="BTCUSDT",
        model_version="m-v1",
        checkpoint_id="ckpt-1",
        prediction_ts_ms=10_000,
        confidence_raw=0.75,
        confidence_calibrated=0.70,
        confidence_explainability=valid_confidence_explainability,
        top_positive_features=("feat_a",),
        top_negative_features=("feat_b",),
        source_key_references=("source_a", "source_b"),
        feature_status_flags=valid_feature_status_flags,
        freshness_metadata=valid_freshness_metadata,
        feature_freshness_envelope=valid_feature_freshness_envelope,
        worker_id="worker-1",
        worker_health_status="healthy",
    )


@pytest.fixture()
def valid_stage_b_record(
    valid_stage_a_record: StageATrainerRecord,
) -> Callable[[StageATrainerRecord], StageBTrainerRecord]:
    def _builder(stage_a: StageATrainerRecord = valid_stage_a_record) -> StageBTrainerRecord:
        return StageBTrainerRecord(
            signal_id="sig-1",
            prediction_id=stage_a.prediction_id,
            feature_snapshot_id=stage_a.feature_snapshot_id,
            symbol=stage_a.symbol,
            action="buy",
            action_type="open_long",
            confidence=0.65,
            signal_ts_ms=stage_a.prediction_ts_ms + 100,
        )

    return _builder
