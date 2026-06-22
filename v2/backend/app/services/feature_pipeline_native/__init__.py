"""V2-native feature pipeline service package.

Paper/shadow only. Computes feature snapshots from raw OHLCV + orderbook +
funding/OI/liquidation inputs. Does not read legacy `features:*` Redis
keys as authoritative; legacy reads (when used) are tagged
`LEGACY_REFERENCE_READ_ONLY`. Does not write to legacy Redis. Does not
mutate exchange state.
"""
from .service import (
    FEATURE_PIPELINE_NATIVE_SCHEMA_VERSION,
    FeaturePipelineNativeService,
    FeatureSnapshotResult,
    NativeFeatureInputs,
    compute_feature_snapshot,
    feature_snapshot_id,
)

__all__ = [
    "FEATURE_PIPELINE_NATIVE_SCHEMA_VERSION",
    "FeaturePipelineNativeService",
    "FeatureSnapshotResult",
    "NativeFeatureInputs",
    "compute_feature_snapshot",
    "feature_snapshot_id",
]
