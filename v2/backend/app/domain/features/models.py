from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class FeatureSourceRef:
    source_name: str
    source_type: str
    source_key: str
    source_snapshot_id: Optional[str] = None
    ingestor_ref: Optional[str] = None


@dataclass(frozen=True)
class FeatureFreshness:
    source_name: str
    source_ts: Optional[str]
    observed_ts: str
    max_age_ms: int
    age_ms: Optional[int]
    stale: bool
    missing: bool


@dataclass(frozen=True)
class FeatureGroup:
    name: str
    feature_names: List[str]
    required_for_trainer: bool = False
    description: str = ""


@dataclass(frozen=True)
class AttributionMetadata:
    source_key_refs: List[str]
    source_ingestor_refs: List[str]
    lineage_gap_reason: Optional[str] = None
    notes: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeatureSnapshot:
    feature_snapshot_id: str
    canonical_symbol_id: str
    legacy_symbol: str
    timeframe: str
    generated_ts: str
    source_snapshot_ids: List[str]
    source_key_refs: List[str]
    source_ingestor_refs: List[str]
    feature_values: Dict[str, float]
    feature_groups: List[FeatureGroup]
    freshness_by_source: Dict[str, FeatureFreshness]
    stale_features: List[str]
    missing_features: List[str]
    unused_features: List[str]
    confidence_input_ready: bool
    trainer_input_schema_version: str
    attribution_metadata: AttributionMetadata
    lineage_gap_reason: Optional[str] = None

    def trainer_payload(self) -> Dict[str, Any]:
        return {
            "feature_snapshot_id": self.feature_snapshot_id,
            "canonical_symbol_id": self.canonical_symbol_id,
            "legacy_symbol": self.legacy_symbol,
            "timeframe": self.timeframe,
            "generated_ts": self.generated_ts,
            "trainer_input_schema_version": self.trainer_input_schema_version,
            "feature_values": dict(self.feature_values),
            "confidence_input_ready": self.confidence_input_ready,
            "stale_features": list(self.stale_features),
            "missing_features": list(self.missing_features),
            "unused_features": list(self.unused_features),
            "source_snapshot_ids": list(self.source_snapshot_ids),
            "source_key_refs": list(self.source_key_refs),
            "source_ingestor_refs": list(self.source_ingestor_refs),
            "lineage_gap_reason": self.lineage_gap_reason,
        }

