"""V2 native feature intelligence service.

Paper/shadow only. Computes microstructure features, freshness flags, and
a simple regime classifier from V2 inputs. Does not write to legacy Redis
and does not import exchange SDKs.
"""
from .service import (
    FEATURE_INTELLIGENCE_SCHEMA_VERSION,
    FeatureIntelligenceService,
    FeatureSnapshotIn,
    MicrostructureFeatures,
    RegimeLabel,
    classify_regime,
    compute_microstructure,
    feature_freshness_flag,
)

__all__ = [
    "FEATURE_INTELLIGENCE_SCHEMA_VERSION",
    "FeatureIntelligenceService",
    "FeatureSnapshotIn",
    "MicrostructureFeatures",
    "RegimeLabel",
    "classify_regime",
    "compute_microstructure",
    "feature_freshness_flag",
]
