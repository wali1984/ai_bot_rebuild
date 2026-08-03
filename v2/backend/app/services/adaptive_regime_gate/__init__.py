"""Adaptive regime gate ahead of strategy/router (Phase 3, paper-safe, read-only)."""
from .classifier import (
    REGIME_GATE_REDIS_KEY_TEMPLATE,
    REGIMES,
    classify_regime,
)
from .permission_matrix import (
    STRATEGY_REGIME_PERMISSION_MATRIX,
    strategy_allowed_in_regime,
)

__all__ = [
    "REGIME_GATE_REDIS_KEY_TEMPLATE",
    "REGIMES",
    "classify_regime",
    "STRATEGY_REGIME_PERMISSION_MATRIX",
    "strategy_allowed_in_regime",
]
