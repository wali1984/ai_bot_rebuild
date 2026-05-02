from __future__ import annotations

from typing import List

from .models import FeatureSnapshot


def validate_trainer_input(snapshot: FeatureSnapshot) -> List[str]:
    errors: List[str] = []
    if not snapshot.feature_snapshot_id:
        errors.append("missing_feature_snapshot_id")
    if not snapshot.canonical_symbol_id:
        errors.append("missing_canonical_symbol_id")
    if not snapshot.trainer_input_schema_version:
        errors.append("missing_trainer_input_schema_version")
    if snapshot.missing_features:
        errors.append("missing_required_features")
    if snapshot.stale_features:
        errors.append("stale_features_present")
    if not snapshot.confidence_input_ready:
        errors.append("confidence_input_not_ready")
    if not snapshot.source_key_refs:
        errors.append("missing_source_key_refs")
    return errors


def is_trainer_ready(snapshot: FeatureSnapshot) -> bool:
    return not validate_trainer_input(snapshot)

