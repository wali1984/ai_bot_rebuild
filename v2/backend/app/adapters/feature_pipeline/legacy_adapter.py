from __future__ import annotations

from ...domain.features.models import FeatureSnapshot
from ...services.feature_snapshots.service import FeatureSnapshotService


class LegacyFeaturePipelineAdapter:
    name = "legacy_feature_pipeline_adapter"

    def __init__(self, service: FeatureSnapshotService | None = None) -> None:
        self.service = service or FeatureSnapshotService()

    def to_feature_snapshot(self, payload: dict) -> FeatureSnapshot:
        return self.service.build_snapshot(payload)

