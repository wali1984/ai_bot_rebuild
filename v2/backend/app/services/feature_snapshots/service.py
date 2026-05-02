from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any, Dict

from ...domain.features.freshness import (
    assess_freshness,
    missing_feature_names,
    stale_feature_names,
    unused_feature_names,
)
from ...domain.features.groups import group_features, required_feature_names
from ...domain.features.models import AttributionMetadata, FeatureSnapshot
from ...domain.features.validation import is_trainer_ready


TRAINER_INPUT_SCHEMA_VERSION = "trainer_features.v1"


def stable_snapshot_id(payload: Dict[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:24]
    return f"feature_snapshot_{digest}"


class FeatureSnapshotService:
    def build_snapshot(self, payload: Dict[str, Any]) -> FeatureSnapshot:
        generated_ts = payload.get("generated_ts") or dt.datetime.now(dt.timezone.utc).isoformat()
        feature_values = {str(k): float(v) for k, v in payload.get("feature_values", {}).items()}
        feature_to_source = {str(k): str(v) for k, v in payload.get("feature_to_source", {}).items()}
        freshness_by_source = {
            source: assess_freshness(
                source,
                source_payload.get("source_ts"),
                generated_ts,
                int(source_payload.get("max_age_ms", 60_000)),
            )
            for source, source_payload in payload.get("sources", {}).items()
        }
        groups = group_features(feature_values)
        required = required_feature_names()
        missing = missing_feature_names(required, feature_values)
        stale = stale_feature_names(feature_to_source, freshness_by_source)
        used = payload.get("used_features") or sorted(feature_values)
        unused = unused_feature_names(feature_values, used)
        attribution = AttributionMetadata(
            source_key_refs=list(payload.get("source_key_refs", [])),
            source_ingestor_refs=list(payload.get("source_ingestor_refs", [])),
            lineage_gap_reason=payload.get("lineage_gap_reason"),
            notes=dict(payload.get("attribution_notes", {})),
        )
        base = {
            "canonical_symbol_id": payload["canonical_symbol_id"],
            "legacy_symbol": payload["legacy_symbol"],
            "timeframe": payload["timeframe"],
            "generated_ts": generated_ts,
            "feature_values": feature_values,
            "source_snapshot_ids": list(payload.get("source_snapshot_ids", [])),
        }
        snapshot = FeatureSnapshot(
            feature_snapshot_id=payload.get("feature_snapshot_id") or stable_snapshot_id(base),
            canonical_symbol_id=payload["canonical_symbol_id"],
            legacy_symbol=payload["legacy_symbol"],
            timeframe=payload["timeframe"],
            generated_ts=generated_ts,
            source_snapshot_ids=list(payload.get("source_snapshot_ids", [])),
            source_key_refs=list(payload.get("source_key_refs", [])),
            source_ingestor_refs=list(payload.get("source_ingestor_refs", [])),
            feature_values=feature_values,
            feature_groups=groups,
            freshness_by_source=freshness_by_source,
            stale_features=stale,
            missing_features=missing,
            unused_features=unused,
            confidence_input_ready=not missing and not stale,
            trainer_input_schema_version=TRAINER_INPUT_SCHEMA_VERSION,
            attribution_metadata=attribution,
            lineage_gap_reason=payload.get("lineage_gap_reason"),
        )
        return FeatureSnapshot(**{**snapshot.__dict__, "confidence_input_ready": is_trainer_ready(snapshot)})

