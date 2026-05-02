"""Pure-function explainability validator for Stage A trainer records.

Enforces the mandatory legacy-preservation explainability field set described
in `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/04_REWARD_AND_CONFIDENCE_PARITY_MAP.md`.
Missing or malformed fields raise `TrainerParityLineageError`.
"""

from __future__ import annotations

import math

from .errors import TrainerParityLineageError
from .stage_a_record import StageATrainerRecord


def validate_stage_a_explainability(record: StageATrainerRecord) -> None:
    explain = record.confidence_explainability

    if not explain.confidence_components:
        raise TrainerParityLineageError(
            "confidence_components must be non-empty",
            field="confidence_explainability.confidence_components",
        )

    seen_names: set[str] = set()
    for component_name, contribution in explain.confidence_components:
        if not component_name:
            raise TrainerParityLineageError(
                "confidence_components contains empty component name",
                field="confidence_explainability.confidence_components",
            )
        if not math.isfinite(contribution):
            raise TrainerParityLineageError(
                (
                    f"confidence_components component {component_name!r} "
                    "contribution must be finite"
                ),
                field="confidence_explainability.confidence_components",
            )
        if component_name in seen_names:
            raise TrainerParityLineageError(
                f"confidence_components contains duplicate component name {component_name!r}",
                field="confidence_explainability.confidence_components",
            )
        seen_names.add(component_name)

    if not explain.calibration_model_version:
        raise TrainerParityLineageError(
            "calibration_model_version must be non-empty",
            field="confidence_explainability.calibration_model_version",
        )
    if not explain.calibration_method:
        raise TrainerParityLineageError(
            "calibration_method must be non-empty",
            field="confidence_explainability.calibration_method",
        )

    if not record.top_positive_features and not record.top_negative_features:
        raise TrainerParityLineageError(
            "top_positive_features and top_negative_features cannot both be empty",
            field="explainability.top_features",
        )
    if not record.source_key_references:
        raise TrainerParityLineageError(
            "source_key_references must be non-empty",
            field="explainability.source_key_references",
        )

    fm = record.freshness_metadata
    if (
        not fm.per_feature_last_update_ms
        and not fm.per_feature_age_ms
        and not fm.per_feature_status
    ):
        raise TrainerParityLineageError(
            "freshness_metadata must be non-empty",
            field="explainability.freshness_metadata",
        )
