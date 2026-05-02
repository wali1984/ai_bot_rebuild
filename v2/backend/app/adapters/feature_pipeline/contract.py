from __future__ import annotations

from typing import Protocol

from ...domain.features.models import FeatureSnapshot


class FeaturePipelineAdapter(Protocol):
    name: str

    def to_feature_snapshot(self, payload: dict) -> FeatureSnapshot:
        ...

