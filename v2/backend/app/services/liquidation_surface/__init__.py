"""Prospective market-liquidation surface calculation.

The package is intentionally separate from forced-liquidation ingestion.
Forced orders are realized outcomes; this package models still-open position
cohorts and the prices at which those cohorts could be liquidated.
"""

from .contracts import (
    CandleObservation,
    LeverageBracket,
    MarkPriceObservation,
    OpenInterestObservation,
    OutcomeCalibration,
    SurfaceRequest,
)
from .model import (
    MODEL_VERSION,
    SurfaceContractError,
    build_liquidation_surface,
    isolated_liquidation_price,
)

__all__ = [
    "MODEL_VERSION",
    "CandleObservation",
    "LeverageBracket",
    "MarkPriceObservation",
    "OpenInterestObservation",
    "OutcomeCalibration",
    "SurfaceContractError",
    "SurfaceRequest",
    "build_liquidation_surface",
    "isolated_liquidation_price",
]
