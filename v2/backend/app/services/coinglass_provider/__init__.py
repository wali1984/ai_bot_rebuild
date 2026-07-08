"""CoinGlass provider readiness contract.

This package does not perform exchange actions and does not print API keys.
It only classifies configured/unsubscribed/active states for runtime health and
future automatic ingestion when the subscription is valid.
"""

from .endpoint_registry import CoinGlassEndpointSpec, coinglass_endpoint_registry, registry_payload
from .health import COINGLASS_HEALTH_KEY, build_coinglass_health
from .rate_limit import CoinGlassRateLimiter, resolve_coinglass_limit

__all__ = [
    "COINGLASS_HEALTH_KEY",
    "CoinGlassEndpointSpec",
    "CoinGlassRateLimiter",
    "build_coinglass_health",
    "coinglass_endpoint_registry",
    "registry_payload",
    "resolve_coinglass_limit",
]
