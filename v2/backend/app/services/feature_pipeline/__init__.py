"""Feature pipeline adapters (V2-owned; paper/analytics only)."""

from .unified_feature_bridge import UNIFIED_FEATURE_KEY, build_unified_feature_payload

__all__ = [
    "UNIFIED_FEATURE_KEY",
    "build_unified_feature_payload",
]
