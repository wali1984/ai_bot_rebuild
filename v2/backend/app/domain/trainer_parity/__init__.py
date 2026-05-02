"""Trainer parity domain records and validators (Phase 2E1.B).

Pure domain layer with value objects and validators only.
This package re-exports exactly the nine public names enumerated in
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/26_PHASE_2E1B_DOMAIN_RECORD_SPEC.md`.

`ConfidenceExplainability` is intentionally not re-exported here; it lives at
module scope in `stage_a_record.py` as a constructor argument type for
`StageATrainerRecord`.
"""

from __future__ import annotations

from .errors import TrainerParityLineageError
from .explainability_validator import validate_stage_a_explainability
from .feature_status_flags import FeatureFreshnessEnvelope, FeatureStatusFlags
from .freshness_metadata import FreshnessMetadata
from .lineage_validator import validate_stage_a_lineage, validate_stage_b_lineage
from .stage_a_record import StageATrainerRecord
from .stage_b_record import StageBTrainerRecord

__all__ = [
    "FeatureFreshnessEnvelope",
    "FeatureStatusFlags",
    "FreshnessMetadata",
    "StageATrainerRecord",
    "StageBTrainerRecord",
    "TrainerParityLineageError",
    "validate_stage_a_explainability",
    "validate_stage_a_lineage",
    "validate_stage_b_lineage",
]
