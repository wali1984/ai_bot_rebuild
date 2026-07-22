"""Typed contracts for prospective liquidation-surface inputs.

Every observation carries the clocks needed to prove point-in-time safety.
Provider fetch time is not interchangeable with the market event or candle
close time.  Publication availability is established later by a separate
post-commit read receipt and is therefore not represented as output authority
inside these source contracts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class CandleObservation:
    venue: str
    symbol: str
    timeframe: str
    open_time_ms: int
    close_time_ms: int
    event_time_ms: int
    ingested_at_ms: int
    available_at_ms: int
    is_final: bool
    open: float
    high: float
    low: float
    close: float
    quote_volume: float | None = None
    taker_buy_quote_volume: float | None = None
    source_key: str = ""
    source_sha256: str = ""


@dataclass(frozen=True)
class OpenInterestObservation:
    venue: str
    symbol: str
    timeframe: str
    feature_cutoff_ms: int
    event_time_ms: int
    ingested_at_ms: int
    available_at_ms: int
    is_final: bool
    value: float
    unit: str
    source_key: str = ""
    source_sha256: str = ""


@dataclass(frozen=True)
class MarkPriceObservation:
    venue: str
    symbol: str
    event_time_ms: int
    ingested_at_ms: int
    available_at_ms: int
    price: float
    source_key: str = ""
    source_sha256: str = ""


@dataclass(frozen=True)
class LeverageBracket:
    venue: str
    symbol: str
    bracket_id: int
    notional_floor: float
    notional_cap: float
    initial_leverage: int
    maintenance_margin_rate: float
    cumulative_maintenance_amount: float = 0.0
    fetched_at_ms: int = 0
    ingested_at_ms: int = 0
    available_at_ms: int = 0
    expires_at_ms: int = 0
    source_key: str = ""
    source_sha256: str = ""


@dataclass(frozen=True)
class OutcomeCalibration:
    """Causal weights learned from realized outcomes through one cutoff.

    Forced-liquidation events may inform these weights only after they occur;
    they never enter the prospective surface as still-open positions.
    """

    venue: str
    symbol: str
    timeframe: str
    feature_cutoff_ms: int
    ingested_at_ms: int
    available_at_ms: int
    leverage_weights: Mapping[int, float] = field(default_factory=dict)
    source_key: str = ""
    source_sha256: str = ""


@dataclass(frozen=True)
class SurfaceRequest:
    venue: str
    symbol: str
    timeframe: str
    as_of_time_ms: int
    generated_at_ms: int
    candles: tuple[CandleObservation, ...]
    mark_prices: tuple[MarkPriceObservation, ...] = ()
    open_interest: tuple[OpenInterestObservation, ...] = ()
    leverage_brackets: tuple[LeverageBracket, ...] = ()
    outcome_calibration: OutcomeCalibration | None = None
    tick_size: float | None = None
    # These are computational/output bounds, not market admission thresholds.
    max_cohorts: int = 256
    max_leverage_scenarios: int = 64
    max_levels_per_side: int = 64
    max_source_rows_per_family: int = 4_096
    max_expanded_candidates: int = 2_000_000
