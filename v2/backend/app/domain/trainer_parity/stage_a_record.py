"""Stage A trainer-inference record dataclass and ConfidenceExplainability."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import TrainerParityLineageError
from .feature_status_flags import FeatureFreshnessEnvelope, FeatureStatusFlags
from .freshness_metadata import FreshnessMetadata


@dataclass(frozen=True, slots=True)
class ConfidenceExplainability:
    """Mandatory legacy-preservation explainability bundle for a prediction.

    The constructor enforces only the invariants that make the payload
    constructible-but-malformed impossible (empty component name, non-finite
    contribution). Duplicate-name, empty-set, and empty-calibration checks live
    in `validate_stage_a_explainability` for defense-in-depth.
    """

    confidence_components: tuple[tuple[str, float], ...]
    confidence_floor_applied: bool
    confidence_ceiling_applied: bool
    calibration_model_version: str
    calibration_method: str

    def __post_init__(self) -> None:
        for component_name, contribution in self.confidence_components:
            if not component_name:
                raise TrainerParityLineageError(
                    "confidence_explainability component name must be non-empty",
                    field="confidence_explainability.confidence_components",
                )
            if not math.isfinite(contribution):
                raise TrainerParityLineageError(
                    (
                        f"confidence_explainability component {component_name!r} "
                        "contribution must be finite"
                    ),
                    field="confidence_explainability.confidence_components",
                )


@dataclass(frozen=True, slots=True)
class StageATrainerRecord:
    """Trainer-inference record (Stage A) for V2 GPU parity."""

    prediction_id: str
    feature_snapshot_id: str
    symbol: str
    model_version: str
    checkpoint_id: str
    prediction_ts_ms: int
    confidence_raw: float
    confidence_calibrated: float
    confidence_explainability: ConfidenceExplainability
    top_positive_features: tuple[str, ...]
    top_negative_features: tuple[str, ...]
    source_key_references: tuple[str, ...]
    feature_status_flags: FeatureStatusFlags
    freshness_metadata: FreshnessMetadata
    feature_freshness_envelope: FeatureFreshnessEnvelope
    worker_id: str
    worker_health_status: str

    def __post_init__(self) -> None:
        for field_name, value in (
            ("prediction_id", self.prediction_id),
            ("feature_snapshot_id", self.feature_snapshot_id),
            ("symbol", self.symbol),
            ("model_version", self.model_version),
            ("checkpoint_id", self.checkpoint_id),
            ("worker_id", self.worker_id),
            ("worker_health_status", self.worker_health_status),
        ):
            if not value:
                raise TrainerParityLineageError(
                    f"stage_a.{field_name} must be non-empty",
                    field=f"stage_a.{field_name}",
                )

        if self.prediction_ts_ms < 0:
            raise TrainerParityLineageError(
                "stage_a.prediction_ts_ms must be >= 0",
                field="stage_a.prediction_ts_ms",
            )

        if not 0.0 <= self.confidence_raw <= 1.0:
            raise TrainerParityLineageError(
                "stage_a.confidence_raw must be in [0.0, 1.0]",
                field="stage_a.confidence_raw",
            )
        if not 0.0 <= self.confidence_calibrated <= 1.0:
            raise TrainerParityLineageError(
                "stage_a.confidence_calibrated must be in [0.0, 1.0]",
                field="stage_a.confidence_calibrated",
            )

        for tuple_name, tuple_values in (
            ("top_positive_features", self.top_positive_features),
            ("top_negative_features", self.top_negative_features),
            ("source_key_references", self.source_key_references),
        ):
            if len(set(tuple_values)) != len(tuple_values):
                raise TrainerParityLineageError(
                    f"stage_a.{tuple_name} contains duplicate entries",
                    field=f"stage_a.{tuple_name}",
                )
