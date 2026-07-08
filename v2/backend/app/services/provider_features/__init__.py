"""Provider feature contracts and Redis bridge.

Optional providers enrich trainer/risk/orchestrator/paper surfaces but do not
become core blockers unless a caller explicitly marks them required.
"""

from .contracts import (
    CONSUMER_ROLES,
    COINGLASS_REDIS_KEY_CONTRACT,
    MORALIS_REDIS_KEY_CONTRACT,
    endpoint_to_feature_mapping,
    provider_redis_key_contract,
)
from .provider_feature_bridge import (
    ProviderFeatureBridge,
    ProviderFeatureSnapshot,
    build_provider_actual_data_panel,
    build_provider_consumer_context,
)

__all__ = [
    "CONSUMER_ROLES",
    "COINGLASS_REDIS_KEY_CONTRACT",
    "MORALIS_REDIS_KEY_CONTRACT",
    "ProviderFeatureBridge",
    "ProviderFeatureSnapshot",
    "build_provider_actual_data_panel",
    "build_provider_consumer_context",
    "endpoint_to_feature_mapping",
    "provider_redis_key_contract",
]
