"""Contracts for production-equivalent major-move candidate detection.

Architecture principle:
    Major-move detection runs in paper execution mode but uses the full
    production feature context. No simplified paper-only subset.
    The same context would be required for live execution.

Feature coverage gate:
    When require_full_feature_coverage=True (default), detection returns
    FEATURE_COVERAGE_INSUFFICIENT if any required feature family is absent.
    Required families: mark_price, closed_candles, volume, atr, orderbook,
    oi_funding, liquidation, correlation_anchor.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CandleInput:
    symbol: str
    timeframe: str
    open_time_ms: int
    close_time_ms: int
    available_at_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    closed: bool

    @classmethod
    def from_mapping(cls, row: dict[str, Any], *, symbol: str, timeframe: str) -> "CandleInput":
        open_time = row.get("candle_open_time") or row.get("open_time") or row.get("ts")
        close_time = row.get("candle_close_time") or row.get("close_time")
        available_at = row.get("available_at") or row.get("source_available_time") or close_time
        return cls(
            symbol=str(row.get("symbol") or symbol),
            timeframe=str(row.get("timeframe") or timeframe),
            open_time_ms=int(float(open_time)),
            close_time_ms=int(float(close_time)),
            available_at_ms=int(float(available_at)),
            open=float(row.get("open")),
            high=float(row.get("high")),
            low=float(row.get("low")),
            close=float(row.get("close")),
            volume=float(row.get("volume") or 0.0),
            closed=bool(
                row.get("candle_closed_confirmed") is True
                or row.get("closed_candle") is True
                or row.get("is_closed") is True
            ),
        )


# Feature families required for a production-grade major-move decision.
# Present in production context; must not be omitted in paper mode.
REQUIRED_FEATURE_FAMILIES: tuple[str, ...] = (
    "mark_price",          # current market price (not entry price)
    "closed_candles",      # confirmed closed candle history
    "volume",              # volume acceleration anchor
    "atr",                 # ATR / range expansion
    "orderbook",           # orderbook imbalance / depth
    "oi_funding",          # open interest and funding rate
    "liquidation",         # liquidation pressure / cluster proximity
    "correlation_anchor",  # BTC/ETH/SOL regime confirmation
)


@dataclass(frozen=True)
class DetectionContext:
    decision_time_ms: int
    spread_bps: float | None = None
    slippage_bps: float | None = None
    orderbook_imbalance: float | None = None
    liquidation_pressure: float | None = None
    oi_change_pct: float | None = None
    funding_rate: float | None = None
    long_short_ratio: float | None = None
    public_intel_score: float | None = None
    correlated_regime_confirmed: bool = False
    # Full production feature context — presence flags for each required family.
    # A family is "present" when at least one non-None input from that family
    # reached the detection layer. Detection gates on these when
    # require_full_feature_coverage=True.
    feature_families_present: frozenset[str] = field(default_factory=frozenset)
    require_full_feature_coverage: bool = False

    def missing_feature_families(self) -> list[str]:
        """Return required families absent from this context."""
        return sorted(f for f in REQUIRED_FEATURE_FAMILIES if f not in self.feature_families_present)

    def feature_coverage_sufficient(self) -> bool:
        if not self.require_full_feature_coverage:
            return True
        return len(self.missing_feature_families()) == 0

    @classmethod
    def from_full_production_context(
        cls,
        *,
        decision_time_ms: int,
        spread_bps: float | None = None,
        slippage_bps: float | None = None,
        orderbook_imbalance: float | None = None,
        liquidation_pressure: float | None = None,
        oi_change_pct: float | None = None,
        funding_rate: float | None = None,
        long_short_ratio: float | None = None,
        public_intel_score: float | None = None,
        correlated_regime_confirmed: bool = False,
        mark_price_present: bool = False,
        closed_candles_present: bool = False,
        volume_present: bool = False,
        atr_present: bool = False,
        require_full_feature_coverage: bool = True,
    ) -> "DetectionContext":
        """Construct a context from production feature inputs.

        Automatically populates feature_families_present from provided flags
        and non-None optional fields, enabling the gate to verify full coverage.
        """
        families: set[str] = set()
        if mark_price_present:
            families.add("mark_price")
        if closed_candles_present:
            families.add("closed_candles")
        if volume_present:
            families.add("volume")
        if atr_present:
            families.add("atr")
        if orderbook_imbalance is not None:
            families.add("orderbook")
        if oi_change_pct is not None or funding_rate is not None:
            families.add("oi_funding")
        if liquidation_pressure is not None:
            families.add("liquidation")
        if correlated_regime_confirmed:
            families.add("correlation_anchor")
        return cls(
            decision_time_ms=decision_time_ms,
            spread_bps=spread_bps,
            slippage_bps=slippage_bps,
            orderbook_imbalance=orderbook_imbalance,
            liquidation_pressure=liquidation_pressure,
            oi_change_pct=oi_change_pct,
            funding_rate=funding_rate,
            long_short_ratio=long_short_ratio,
            public_intel_score=public_intel_score,
            correlated_regime_confirmed=correlated_regime_confirmed,
            feature_families_present=frozenset(families),
            require_full_feature_coverage=require_full_feature_coverage,
        )


@dataclass(frozen=True)
class BreakoutSqueezeSignal:
    major_move_signal_id: str
    symbol: str
    timeframe: str
    direction: str
    move_probability: float
    expected_move_after_cost_bps: float
    confidence: float
    evidence_score: float
    regime: str
    reasons: tuple[str, ...]
    reject_reasons: tuple[str, ...] = field(default_factory=tuple)
    paper_only: bool = True
    live_allowed: bool = False

    def to_jsonable(self) -> dict[str, Any]:
        return asdict(self)
