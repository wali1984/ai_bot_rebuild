"""Market State Brain — classifier that produces one of 12 market states
from feature snapshot data already available in Redis.

Design principles:
- Never calls exchange APIs.
- Uses only data already in v2:features:latest:{symbol}:{tf}.
- Every state decision carries an evidence_score [0-1] and a reason list.
- Default state is NO_TRADE (fail-closed) when evidence is insufficient.
- Read-only; places no orders.
"""
from __future__ import annotations

from enum import Enum
from typing import Any


class MarketState(str, Enum):
    NO_TRADE = "NO_TRADE"
    VOLATILITY_EXPANSION_UNSAFE = "VOLATILITY_EXPANSION_UNSAFE"
    DOUBLE_SIDED_LIQUIDATION_WHIPSAW = "DOUBLE_SIDED_LIQUIDATION_WHIPSAW"
    ORDERBOOK_TRAP_OR_SPOOF_RISK = "ORDERBOOK_TRAP_OR_SPOOF_RISK"
    EMERGENCY_DE_RISK = "EMERGENCY_DE_RISK"
    HEDGE_LOCK_MANAGEMENT = "HEDGE_LOCK_MANAGEMENT"
    BREAKOUT_SQUEEZE_LONG = "BREAKOUT_SQUEEZE_LONG"
    BREAKOUT_SQUEEZE_SHORT = "BREAKOUT_SQUEEZE_SHORT"
    LIQUIDITY_SWEEP_FALSE_BREAKOUT = "LIQUIDITY_SWEEP_FALSE_BREAKOUT"
    RANGE_MEAN_REVERSION = "RANGE_MEAN_REVERSION"
    TREND_CONTINUATION_LONG = "TREND_CONTINUATION_LONG"
    TREND_CONTINUATION_SHORT = "TREND_CONTINUATION_SHORT"


def _f(feature: dict[str, Any], key: str, default: float | None = None) -> float | None:
    v = feature.get(key)
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _b(feature: dict[str, Any], key: str) -> bool:
    return bool(feature.get(key))


class MarketStateBrainResult:
    __slots__ = ("state", "evidence_score", "reasons", "allowed_actions", "symbol", "timeframe", "raw")

    def __init__(
        self,
        state: MarketState,
        evidence_score: float,
        reasons: list[str],
        symbol: str,
        timeframe: str,
        raw: dict[str, Any] | None = None,
    ) -> None:
        self.state = state
        self.evidence_score = round(min(1.0, max(0.0, evidence_score)), 3)
        self.reasons = reasons
        self.symbol = symbol
        self.timeframe = timeframe
        self.raw = raw or {}
        self.allowed_actions = _allowed_actions_for_state(state)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "evidence_score": self.evidence_score,
            "reasons": self.reasons,
            "allowed_actions": self.allowed_actions,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "places_real_order": False,
        }


def _allowed_actions_for_state(state: MarketState) -> list[str]:
    mapping: dict[MarketState, list[str]] = {
        MarketState.NO_TRADE: [],
        MarketState.VOLATILITY_EXPANSION_UNSAFE: ["EXIT_ONLY"],
        MarketState.DOUBLE_SIDED_LIQUIDATION_WHIPSAW: ["EXIT_ONLY", "REDUCE_ONLY"],
        MarketState.ORDERBOOK_TRAP_OR_SPOOF_RISK: ["EXIT_ONLY"],
        MarketState.EMERGENCY_DE_RISK: ["EXIT_ONLY", "EMERGENCY_CLOSE"],
        MarketState.HEDGE_LOCK_MANAGEMENT: ["MANAGE_HEDGE_LOCK"],
        MarketState.BREAKOUT_SQUEEZE_LONG: ["LONG", "HEDGE_LOCK"],
        MarketState.BREAKOUT_SQUEEZE_SHORT: ["SHORT", "HEDGE_LOCK"],
        MarketState.LIQUIDITY_SWEEP_FALSE_BREAKOUT: ["COUNTER_TREND", "HEDGE_LOCK"],
        MarketState.RANGE_MEAN_REVERSION: ["LONG", "SHORT", "REDUCE_ONLY"],
        MarketState.TREND_CONTINUATION_LONG: ["LONG", "HEDGE_LOCK"],
        MarketState.TREND_CONTINUATION_SHORT: ["SHORT", "HEDGE_LOCK"],
    }
    return mapping.get(state, [])


def classify_market_state(
    *,
    symbol: str,
    timeframe: str,
    feature: dict[str, Any],
    hedge_lock_active: bool = False,
    account_drawdown_bps: float | None = None,
) -> MarketStateBrainResult:
    """Classify the current market state for a symbol/timeframe pair.

    Uses feature snapshot fields already populated by v2_feature_snapshot_builder.
    Returns NO_TRADE when evidence is insufficient — fail-closed.
    """
    reasons: list[str] = []
    score = 0.0

    # ── TIER 0: Emergency / hedge-lock override ────────────────────────────────
    if account_drawdown_bps is not None and account_drawdown_bps >= 300.0:
        return MarketStateBrainResult(
            MarketState.EMERGENCY_DE_RISK, 0.95,
            [f"ACCOUNT_DRAWDOWN_EMERGENCY:{account_drawdown_bps:.0f}bps"],
            symbol, timeframe,
        )

    if hedge_lock_active:
        return MarketStateBrainResult(
            MarketState.HEDGE_LOCK_MANAGEMENT, 1.0,
            ["HEDGE_LOCK_ACTIVE_FOR_SYMBOL"],
            symbol, timeframe,
        )

    # ── Extract key feature fields ─────────────────────────────────────────────
    spread_bps = _f(feature, "spread_bps")
    bid_ask_ratio = _f(feature, "bid_ask_ratio")
    volume_ratio_1m5m = _f(feature, "volume_ratio_1m_5m")
    oi_change_pct = _f(feature, "oi_change_pct") or _f(feature, "open_interest_change_pct")
    funding_rate = _f(feature, "funding_rate")
    long_short_ratio = _f(feature, "long_short_ratio")
    rsi = _f(feature, "rsi") or _f(feature, "rsi_14")
    macd_signal = _f(feature, "macd_signal") or _f(feature, "macd_signal_line")
    macd_hist = _f(feature, "macd_hist") or _f(feature, "macd_histogram")
    bb_percent = _f(feature, "bb_percent") or _f(feature, "bollinger_pct")
    close = _f(feature, "close") or _f(feature, "last_price")
    high = _f(feature, "high")
    low = _f(feature, "low")
    open_ = _f(feature, "open")
    volume = _f(feature, "volume") or _f(feature, "volume_base")
    avg_volume = _f(feature, "avg_volume_5") or _f(feature, "volume_ma_5")
    liq_distance_long = _f(feature, "liquidation_distance_long_bps")
    liq_distance_short = _f(feature, "liquidation_distance_short_bps")
    oi_value = _f(feature, "open_interest") or _f(feature, "oi_usdt")
    microstructure_toxicity = _f(feature, "microstructure_toxicity")

    # ── TIER 1: Unsafe volatility / spread ────────────────────────────────────
    spread_unsafe = spread_bps is not None and spread_bps > 80.0
    if spread_unsafe:
        return MarketStateBrainResult(
            MarketState.VOLATILITY_EXPANSION_UNSAFE, 0.9,
            [f"SPREAD_TOO_WIDE:{spread_bps:.1f}bps"],
            symbol, timeframe,
        )

    microstructure_unsafe = (
        microstructure_toxicity is not None and microstructure_toxicity > 0.80
    )
    if microstructure_unsafe:
        return MarketStateBrainResult(
            MarketState.VOLATILITY_EXPANSION_UNSAFE, 0.85,
            [f"MICROSTRUCTURE_TOXICITY:{microstructure_toxicity:.2f}"],
            symbol, timeframe,
        )

    # ── TIER 2: Whipsaw detection ──────────────────────────────────────────────
    whipsaw_score, whipsaw_reasons = _whipsaw_score(
        high=high, low=low, open_=open_, close=close,
        liq_distance_long=liq_distance_long,
        liq_distance_short=liq_distance_short,
    )
    if whipsaw_score >= 0.70:
        return MarketStateBrainResult(
            MarketState.DOUBLE_SIDED_LIQUIDATION_WHIPSAW, whipsaw_score,
            whipsaw_reasons, symbol, timeframe,
        )

    # ── TIER 3: False breakout / liquidity sweep detection ─────────────────────
    false_bo_score, false_bo_reasons = _false_breakout_score(
        high=high, low=low, open_=open_, close=close,
        volume=volume, avg_volume=avg_volume,
        oi_change_pct=oi_change_pct,
    )
    if false_bo_score >= 0.65:
        return MarketStateBrainResult(
            MarketState.LIQUIDITY_SWEEP_FALSE_BREAKOUT, false_bo_score,
            false_bo_reasons, symbol, timeframe,
        )

    # ── TIER 4: Squeeze / breakout detection ──────────────────────────────────
    squeeze_score, squeeze_dir, squeeze_reasons = _squeeze_score(
        rsi=rsi, macd_hist=macd_hist, bb_percent=bb_percent,
        volume=volume, avg_volume=avg_volume,
        oi_change_pct=oi_change_pct, funding_rate=funding_rate,
        long_short_ratio=long_short_ratio, close=close, open_=open_,
    )
    if squeeze_score >= 0.60:
        state = (
            MarketState.BREAKOUT_SQUEEZE_LONG
            if squeeze_dir == "long"
            else MarketState.BREAKOUT_SQUEEZE_SHORT
        )
        return MarketStateBrainResult(state, squeeze_score, squeeze_reasons, symbol, timeframe)

    # ── TIER 5: Trend continuation ─────────────────────────────────────────────
    trend_score, trend_dir, trend_reasons = _trend_score(
        rsi=rsi, macd_hist=macd_hist, macd_signal=macd_signal,
        close=close, open_=open_, high=high, low=low,
    )
    if trend_score >= 0.55:
        state = (
            MarketState.TREND_CONTINUATION_LONG
            if trend_dir == "long"
            else MarketState.TREND_CONTINUATION_SHORT
        )
        return MarketStateBrainResult(state, trend_score, trend_reasons, symbol, timeframe)

    # ── TIER 6: Range / mean reversion ────────────────────────────────────────
    range_score, range_reasons = _range_score(
        rsi=rsi, bb_percent=bb_percent, close=close, high=high, low=low,
    )
    if range_score >= 0.55:
        return MarketStateBrainResult(
            MarketState.RANGE_MEAN_REVERSION, range_score,
            range_reasons, symbol, timeframe,
        )

    # Default: insufficient evidence
    return MarketStateBrainResult(
        MarketState.NO_TRADE, 0.0,
        ["INSUFFICIENT_EVIDENCE_FOR_STATE_CLASSIFICATION"],
        symbol, timeframe,
    )


# ── Sub-scorers ────────────────────────────────────────────────────────────────

def _whipsaw_score(
    *,
    high: float | None,
    low: float | None,
    open_: float | None,
    close: float | None,
    liq_distance_long: float | None,
    liq_distance_short: float | None,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    if all(v is not None for v in (high, low, open_, close)) and close > 0:
        body = abs(close - open_)
        range_ = high - low
        if range_ > 0:
            wick_ratio = 1.0 - (body / range_)
            if wick_ratio > 0.80:
                score += 0.40
                reasons.append(f"LARGE_WICK_BOTH_SIDES:{wick_ratio:.2f}")
    if liq_distance_long is not None and liq_distance_short is not None:
        both_close = liq_distance_long < 200.0 and liq_distance_short < 200.0
        if both_close:
            score += 0.35
            reasons.append(
                f"LIQ_CLUSTER_BOTH_SIDES:long={liq_distance_long:.0f}bps,short={liq_distance_short:.0f}bps"
            )
    return min(1.0, score), reasons


def _false_breakout_score(
    *,
    high: float | None,
    low: float | None,
    open_: float | None,
    close: float | None,
    volume: float | None,
    avg_volume: float | None,
    oi_change_pct: float | None,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    # Candle closes back inside range after wick beyond
    if all(v is not None for v in (high, low, open_, close)) and high > low:
        upper_wick = high - max(open_, close)
        lower_wick = min(open_, close) - low
        range_ = high - low
        if range_ > 0:
            upper_wick_pct = upper_wick / range_
            lower_wick_pct = lower_wick / range_
            # One large wick = price broke out but closed back inside
            if upper_wick_pct > 0.45 and lower_wick_pct < 0.20:
                score += 0.35
                reasons.append(f"UPPER_WICK_REJECTION:{upper_wick_pct:.2f}")
            elif lower_wick_pct > 0.45 and upper_wick_pct < 0.20:
                score += 0.35
                reasons.append(f"LOWER_WICK_REJECTION:{lower_wick_pct:.2f}")
    # High volume on wick but OI did not expand = no follow-through
    if volume is not None and avg_volume is not None and avg_volume > 0:
        vol_spike = volume / avg_volume
        if vol_spike > 2.0 and score > 0:
            if oi_change_pct is not None and abs(oi_change_pct) < 0.5:
                score += 0.30
                reasons.append(f"VOLUME_SPIKE_NO_OI_EXPANSION:vol={vol_spike:.1f}x,oi_chg={oi_change_pct:.2f}%")
    return min(1.0, score), reasons


def _squeeze_score(
    *,
    rsi: float | None,
    macd_hist: float | None,
    bb_percent: float | None,
    volume: float | None,
    avg_volume: float | None,
    oi_change_pct: float | None,
    funding_rate: float | None,
    long_short_ratio: float | None,
    close: float | None,
    open_: float | None,
) -> tuple[float, str, list[str]]:
    long_score = 0.0
    short_score = 0.0
    reasons: list[str] = []

    if rsi is not None:
        if rsi > 60:
            long_score += 0.20
            reasons.append(f"RSI_BULLISH:{rsi:.1f}")
        elif rsi < 40:
            short_score += 0.20
            reasons.append(f"RSI_BEARISH:{rsi:.1f}")

    if macd_hist is not None:
        if macd_hist > 0:
            long_score += 0.15
        else:
            short_score += 0.15

    if volume is not None and avg_volume is not None and avg_volume > 0:
        vol_ratio = volume / avg_volume
        if vol_ratio > 2.5:
            # Volume spike — direction follows candle body
            if close is not None and open_ is not None:
                if close > open_:
                    long_score += 0.25
                    reasons.append(f"VOLUME_SQUEEZE_UP:{vol_ratio:.1f}x")
                else:
                    short_score += 0.25
                    reasons.append(f"VOLUME_SQUEEZE_DOWN:{vol_ratio:.1f}x")

    if oi_change_pct is not None and abs(oi_change_pct) > 1.5:
        # OI expanding = new money entering
        if close is not None and open_ is not None:
            if close > open_:
                long_score += 0.20
            else:
                short_score += 0.20
        reasons.append(f"OI_EXPANDING:{oi_change_pct:.2f}%")

    if funding_rate is not None:
        # Extreme negative funding = shorts paying longs = squeeze risk to upside
        if funding_rate < -0.0005:
            long_score += 0.10
            reasons.append(f"NEGATIVE_FUNDING_SQUEEZE:{funding_rate:.5f}")
        elif funding_rate > 0.001:
            short_score += 0.10
            reasons.append(f"POSITIVE_FUNDING_SQUEEZE:{funding_rate:.5f}")

    if bb_percent is not None:
        if bb_percent > 0.90:
            long_score += 0.10
        elif bb_percent < 0.10:
            short_score += 0.10

    max_score = max(long_score, short_score)
    direction = "long" if long_score >= short_score else "short"
    return min(1.0, max_score), direction, reasons


def _trend_score(
    *,
    rsi: float | None,
    macd_hist: float | None,
    macd_signal: float | None,
    close: float | None,
    open_: float | None,
    high: float | None,
    low: float | None,
) -> tuple[float, str, list[str]]:
    long_score = 0.0
    short_score = 0.0
    reasons: list[str] = []

    if rsi is not None:
        if 50 < rsi <= 70:
            long_score += 0.25
            reasons.append(f"RSI_BULLISH_ZONE:{rsi:.1f}")
        elif 30 <= rsi < 50:
            short_score += 0.25
            reasons.append(f"RSI_BEARISH_ZONE:{rsi:.1f}")

    if macd_hist is not None and macd_signal is not None:
        if macd_hist > 0 and macd_hist > macd_signal:
            long_score += 0.25
            reasons.append("MACD_BULLISH_CROSS")
        elif macd_hist < 0 and macd_hist < macd_signal:
            short_score += 0.25
            reasons.append("MACD_BEARISH_CROSS")

    if all(v is not None for v in (close, open_, high, low)) and high > low:
        body = close - open_
        range_ = high - low
        body_pct = abs(body) / range_ if range_ > 0 else 0
        if body_pct > 0.60:
            if body > 0:
                long_score += 0.15
                reasons.append(f"STRONG_BULL_BODY:{body_pct:.2f}")
            else:
                short_score += 0.15
                reasons.append(f"STRONG_BEAR_BODY:{body_pct:.2f}")

    max_score = max(long_score, short_score)
    direction = "long" if long_score >= short_score else "short"
    return min(1.0, max_score), direction, reasons


def _range_score(
    *,
    rsi: float | None,
    bb_percent: float | None,
    close: float | None,
    high: float | None,
    low: float | None,
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    if rsi is not None and 40 <= rsi <= 60:
        score += 0.30
        reasons.append(f"RSI_NEUTRAL_ZONE:{rsi:.1f}")

    if bb_percent is not None and 0.25 <= bb_percent <= 0.75:
        score += 0.30
        reasons.append(f"PRICE_MID_BAND:{bb_percent:.2f}")

    if all(v is not None for v in (close, high, low)) and high > low:
        mid = (high + low) / 2
        deviation_pct = abs(close - mid) / (high - low)
        if deviation_pct < 0.25:
            score += 0.25
            reasons.append(f"PRICE_NEAR_MIDPOINT:{deviation_pct:.2f}")

    return min(1.0, score), reasons
