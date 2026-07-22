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
from .source_adapters import (
    BINANCE_USDM_VENUE,
    COINANK_OPEN_INTEREST_ENDPOINT,
    MAX_RAW_REDIS_BYTES,
    MAX_SOURCE_ROWS,
    RawRedisEvidence,
    SourceAdapterError,
    adapt_binance_finalized_candles,
    adapt_binance_mark_price,
    adapt_coinank_plan3_open_interest,
)

__all__ = [
    "MODEL_VERSION",
    "BINANCE_USDM_VENUE",
    "COINANK_OPEN_INTEREST_ENDPOINT",
    "MAX_RAW_REDIS_BYTES",
    "MAX_SOURCE_ROWS",
    "CandleObservation",
    "LeverageBracket",
    "MarkPriceObservation",
    "OpenInterestObservation",
    "OutcomeCalibration",
    "RawRedisEvidence",
    "SourceAdapterError",
    "SurfaceContractError",
    "SurfaceRequest",
    "adapt_binance_finalized_candles",
    "adapt_binance_mark_price",
    "adapt_coinank_plan3_open_interest",
    "build_liquidation_surface",
    "isolated_liquidation_price",
]
