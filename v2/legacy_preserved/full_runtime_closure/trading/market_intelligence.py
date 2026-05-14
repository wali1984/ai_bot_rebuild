"""
MarketIntelligence — Unified market context for ALL trading decisions.

Every component (stealth_stops, dynamic_tp, trailing profit, hedge unwind)
calls `get_market_context(symbol)` and gets back a MarketContext object with
scores derived from ALL data sources:
  - Trainer predictions (direction, confidence)
  - Liquidation levels (cluster proximity, magnet direction, strength)
  - Orderbook depth (imbalance, spoofing, depth at price)
  - TA indicators (ADX, RSI, ATR, MACD across timeframes)
  - CoinAnk (OI, funding, L/S ratio)
  - Tape flow (CVD, imbalance, volume)
  - Regime detection (momentum, trending, ranging)

NO STATIC THRESHOLDS — everything is derived from live data relationships.

Usage:
    from trading.market_intelligence import get_market_context
    ctx = get_market_context(redis_client, "ETHUSDT")
    # ctx.trend_score         → -1.0 to +1.0 (bearish to bullish)
    # ctx.trend_strength      → 0.0 to 1.0 (weak to strong)
    # ctx.reversal_risk       → 0.0 to 1.0 (low to high)
    # ctx.liq_magnet_direction→ "LONG", "SHORT", "NEUTRAL"
    # ctx.liq_magnet_strength → 0.0 to 1.0
    # ctx.liq_nearest_long_pct→ distance to nearest long liq cluster
    # ctx.liq_nearest_short_pct → distance to nearest short liq cluster
    # ctx.volatility_regime   → "CALM", "NORMAL", "HIGH", "EXTREME"
    # ctx.volatility_norm     → 0.0 to 1.0 (normalized volatility)
    # ctx.momentum_score      → -1.0 to +1.0 (negative = fading, positive = accelerating)
    # ctx.funding_pressure    → -1.0 to +1.0 (neg = shorts pay, pos = longs pay)
    # ctx.oi_velocity         → -1.0 to +1.0 (neg = deleveraging, pos = leveraging up)
    # ctx.orderbook_pressure  → -1.0 to +1.0 (neg = sell pressure, pos = buy pressure)
    # ctx.tape_pressure       → -1.0 to +1.0 (neg = selling, pos = buying)
    # ctx.spoof_risk          → 0.0 to 1.0
    # ctx.trainer_direction   → "LONG", "SHORT", None
    # ctx.trainer_confidence  → 0.0 to 1.0
    # ctx.regime              → str (from regime detection)
    # ctx.hold_score          → 0.0 to 1.0 (how much evidence says HOLD position)
    # ctx.exit_score          → 0.0 to 1.0 (how much evidence says EXIT now)
    # ctx.extend_score        → 0.0 to 1.0 (how much evidence says LET IT RUN)
    # ctx.raw                 → dict of all raw values for logging

Apr 2026 — No new packages. Redis-only reads.
"""
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# MarketContext dataclass — the single object every consumer reads
# ──────────────────────────────────────────────────────────────

@dataclass
class MarketContext:
    symbol: str = ""
    ts: float = 0.0

    # Trend: how strongly is price trending and in what direction?
    # Derived from: ADX (multi-TF), MACD alignment, price change alignment, trainer direction
    trend_score: float = 0.0        # -1.0 (strong bearish) to +1.0 (strong bullish)
    trend_strength: float = 0.0     # 0.0 (no trend) to 1.0 (powerful trend)

    # Reversal risk: is the current move likely to reverse?
    # Derived from: RSI extremes, funding against move, tape divergence, spoof score
    reversal_risk: float = 0.0      # 0.0 (safe) to 1.0 (reversal imminent)

    # Liquidation magnet: where is price likely to be pulled?
    # Derived from: liq cluster proximity, liq strength ratios, price direction
    liq_magnet_direction: str = "NEUTRAL"  # "LONG" (price hunting longs), "SHORT", "NEUTRAL"
    liq_magnet_strength: float = 0.0       # 0.0 to 1.0
    liq_nearest_long_pct: float = 99.0     # % distance to nearest long liq cluster
    liq_nearest_short_pct: float = 99.0    # % distance to nearest short liq cluster

    # Volatility: how volatile is the market right now?
    # Derived from: ATR (multi-TF), BBands width, fast_move_score, historical ATR percentile
    volatility_regime: str = "NORMAL"  # CALM, NORMAL, HIGH, EXTREME
    volatility_norm: float = 0.5       # 0.0 (dead) to 1.0 (extreme)

    # Momentum: is the move accelerating or fading?
    # Derived from: MACD histogram slope, volume profile, tape CVD, price velocity
    momentum_score: float = 0.0     # -1.0 (fading fast) to +1.0 (accelerating hard)

    # Funding: who's paying who?
    # Derived from: funding rate, L/S ratio, OI-weighted funding pressure
    funding_pressure: float = 0.0   # -1.0 (extreme short-pay) to +1.0 (extreme long-pay)

    # OI dynamics: is the market leveraging up or deleveraging?
    # Derived from: OI changes, coinank OI data, volume context
    oi_velocity: float = 0.0        # -1.0 (rapid deleveraging) to +1.0 (rapid leveraging)

    # Orderbook: where is the real weight?
    # Derived from: depth imbalance (multi-level), bid/ask USD depth
    orderbook_pressure: float = 0.0  # -1.0 (sell walls) to +1.0 (buy walls)

    # Tape: what are real trades doing?
    # Derived from: tape imbalance (1s/5s/30s), CVD, taker ratio
    tape_pressure: float = 0.0     # -1.0 (heavy selling) to +1.0 (heavy buying)

    # Spoof risk: how much of the orderbook is fake?
    spoof_risk: float = 0.0        # 0.0 (clean book) to 1.0 (heavily spoofed)

    # Trainer prediction (if available)
    trainer_direction: Optional[str] = None  # "LONG", "SHORT", None
    trainer_confidence: float = 0.0

    # Regime
    regime: str = "UNKNOWN"
    is_momentum_regime: bool = False

    # ── COMPOSITE SCORES (the main outputs for consumers) ──
    # These combine all the above into actionable decisions.

    # hold_score: how strongly should we hold the current position?
    # High when: trend strong + momentum accelerating + liq magnet favorable + no reversal signals
    hold_score: float = 0.5

    # exit_score: how strongly should we exit/unwind now?
    # High when: reversal risk high + momentum fading + funding against + liq magnet adverse
    exit_score: float = 0.5

    # extend_score: how far should TP/trail targets extend?
    # High when: strong trend + liq clusters far + momentum building + vol expanding
    extend_score: float = 0.5

    # Raw data for logging/debugging
    raw: Dict[str, Any] = field(default_factory=dict)

    # Staleness
    data_age_ms: float = 0.0
    is_stale: bool = False


# ──────────────────────────────────────────────────────────────
# Subsystem Intelligence Gate
# Called by per_leg_roi_kill, graduated_kill, trend_hedge_scale,
# warn_proactive_hedge BEFORE they act. Uses real market data.
# ──────────────────────────────────────────────────────────────

def should_allow_kill(
    redis_client,
    symbol: str,
    position_side: str,
    roi_pct: float = 0.0,
) -> tuple:
    """
    Should we allow a per-leg ROI kill or graduated kill?

    Comprehensive check using ALL available data sources:
      - OHLCV klines: trend (ADX, MACD, price alignment) + momentum (RSI, velocity)
      - CoinAnk: funding pressure, OI velocity, L/S ratio
      - CoinAPI: tape flow (CVD, taker ratio, imbalance)
      - Liquidation levels: cluster proximity + magnet direction
      - Orderbook: depth imbalance, spoof detection
      - Reversal risk: composite from RSI extremes + funding divergence

    If price is recovering or reversal signals are strong,
    defer the kill — the loss may shrink or swing to profit.

    Returns: (allow: bool, reason: str, ctx: MarketContext)
    """
    ctx = get_market_context(redis_client, symbol, position_side=position_side)
    if ctx.is_stale:
        return True, "stale_data_allow_kill", ctx

    side_mult = 1.0 if position_side.upper() == "LONG" else -1.0
    trend_favor = ctx.trend_score * side_mult
    momentum_favor = ctx.momentum_score * side_mult
    tape_favor = ctx.tape_pressure * side_mult
    ob_favor = ctx.orderbook_pressure * side_mult
    funding_favor = ctx.funding_pressure * side_mult

    # Recovery signal: weighted composite from ALL data sources
    recovery_score = (
        max(0, trend_favor) * 0.25 +        # OHLCV klines: multi-TF trend
        max(0, momentum_favor) * 0.20 +      # OHLCV: MACD/RSI/velocity
        max(0, tape_favor) * 0.20 +          # CoinAPI: real trade flow
        max(0, ob_favor) * 0.10 +            # Binance orderbook depth
        max(0, funding_favor) * 0.10         # CoinAnk: funding pressure
    )

    # Liquidation magnet: is price being pulled in our direction?
    liq_bonus = 0.0
    if position_side.upper() == "LONG" and ctx.liq_magnet_direction == "SHORT":
        # Short liquidations above = price magnet upward (favors LONG)
        liq_bonus = ctx.liq_magnet_strength * 0.10
    elif position_side.upper() == "SHORT" and ctx.liq_magnet_direction == "LONG":
        # Long liquidations below = price magnet downward (favors SHORT)
        liq_bonus = ctx.liq_magnet_strength * 0.10
    recovery_score += liq_bonus

    # Reversal risk: if the adverse move is showing exhaustion
    if ctx.reversal_risk > 0.3:
        recovery_score += ctx.reversal_risk * 0.15

    # OI deleveraging: if market is rapidly deleveraging, volatility may compress
    if ctx.oi_velocity < -0.3:
        recovery_score += 0.05  # Deleveraging often precedes reversals

    # If loss is truly catastrophic (ROI < -90%), allow kill regardless
    if roi_pct <= -90.0:
        return True, f"catastrophic_roi={roi_pct:.0f}%", ctx

    # Strong recovery: multiple sources confirm favorable move
    if recovery_score > 0.25 and roi_pct > -70.0:
        return False, (
            f"recovery(score={recovery_score:.2f} "
            f"trend={trend_favor:.2f} mom={momentum_favor:.2f} "
            f"tape={tape_favor:.2f} ob={ob_favor:.2f} "
            f"fund={funding_favor:.2f} liq={liq_bonus:.2f} "
            f"rev_risk={ctx.reversal_risk:.2f})"
        ), ctx

    # Moderate recovery with mild loss
    if recovery_score > 0.15 and roi_pct > -50.0:
        return False, (
            f"mild_recovery(score={recovery_score:.2f} roi={roi_pct:.1f}%)"
        ), ctx

    return True, f"no_recovery(score={recovery_score:.2f})", ctx


def should_allow_hedge(
    redis_client,
    symbol: str,
    hedge_side: str,
    source: str = "",
) -> tuple:
    """
    Should we allow adding a hedge position on this side?

    Comprehensive check using ALL data sources:
      - OHLCV: trend direction + strength (multi-TF ADX/MACD)
      - CoinAnk: funding/OI alignment with hedge direction
      - CoinAPI: tape flow confirms real buying/selling
      - Liquidation: clusters support directional move
      - Orderbook: depth supports the hedge side
      - Reversal risk: don't hedge into an exhausted move

    Returns: (allow: bool, reason: str, ctx: MarketContext)
    """
    ctx = get_market_context(redis_client, symbol, position_side=hedge_side)
    if ctx.is_stale:
        return True, "stale_data_allow_hedge", ctx

    side_mult = 1.0 if hedge_side.upper() == "LONG" else -1.0
    trend_favor = ctx.trend_score * side_mult
    momentum_favor = ctx.momentum_score * side_mult
    ob_favor = ctx.orderbook_pressure * side_mult
    tape_favor = ctx.tape_pressure * side_mult
    funding_favor = ctx.funding_pressure * side_mult

    # Composite: does the market support this hedge direction?
    support_score = (
        trend_favor * 0.30 +        # OHLCV klines
        momentum_favor * 0.25 +     # OHLCV momentum
        tape_favor * 0.20 +         # CoinAPI trade flow
        ob_favor * 0.15 +           # Binance orderbook
        funding_favor * 0.10        # CoinAnk funding
    )

    # Liquidation magnet bonus: clusters pulling price in hedge direction
    liq_support = 0.0
    if hedge_side.upper() == "LONG" and ctx.liq_magnet_direction == "SHORT":
        liq_support = ctx.liq_magnet_strength * 0.10
    elif hedge_side.upper() == "SHORT" and ctx.liq_magnet_direction == "LONG":
        liq_support = ctx.liq_magnet_strength * 0.10
    support_score += liq_support

    # Block if market is clearly against the hedge direction
    if support_score < -0.15:
        return False, (
            f"market_against(support={support_score:.2f} "
            f"trend={trend_favor:.2f} mom={momentum_favor:.2f} "
            f"tape={tape_favor:.2f} ob={ob_favor:.2f} "
            f"fund={funding_favor:.2f} liq={liq_support:.2f})"
        ), ctx

    # Block if high reversal risk AND weak support — don't hedge into exhausted move
    if ctx.reversal_risk > 0.5 and support_score < 0.10:
        return False, (
            f"high_reversal({ctx.reversal_risk:.2f})+weak_support({support_score:.2f})"
        ), ctx

    # Block if trend is strong AGAINST hedge direction (trend_strength > 0.4 opposing)
    if ctx.trend_strength > 0.4 and trend_favor < -0.2:
        return False, (
            f"strong_opposing_trend(strength={ctx.trend_strength:.2f} "
            f"favor={trend_favor:.2f})"
        ), ctx

    return True, f"market_supports(score={support_score:.2f})", ctx


# ──────────────────────────────────────────────────────────────
# Cache to avoid hammering Redis every tick
# ──────────────────────────────────────────────────────────────
_cache: Dict[str, tuple] = {}  # {symbol: (MarketContext, timestamp)}
_CACHE_TTL_SEC = 2.0  # Refresh every 2 seconds


def get_market_context(
    redis_client,
    symbol: str,
    position_side: Optional[str] = None,
    force_refresh: bool = False,
) -> MarketContext:
    """
    Get comprehensive market intelligence for a symbol.

    All consumers call this single function. It reads from Redis once,
    computes all scores, and returns a MarketContext.

    Args:
        redis_client: Redis connection
        symbol: e.g. "ETHUSDT"
        position_side: "LONG" or "SHORT" — affects directional scoring
        force_refresh: bypass cache
    """
    now = time.time()
    cache_key = f"{symbol}:{position_side or 'X'}"

    if not force_refresh:
        cached = _cache.get(cache_key)
        if cached and (now - cached[1]) < _CACHE_TTL_SEC:
            return cached[0]

    ctx = MarketContext(symbol=symbol, ts=now)

    if not redis_client:
        ctx.is_stale = True
        return ctx

    try:
        # ── Read all data sources in one batch ──
        pipe = redis_client.pipeline(transaction=False)

        # Unified features (5m is the primary execution timeframe)
        pipe.hgetall(f"unified_features:{symbol}:5m")     # 0
        pipe.hgetall(f"unified_features:{symbol}:15m")    # 1
        pipe.hgetall(f"unified_features:{symbol}:1h")     # 2
        pipe.hgetall(f"unified_features:{symbol}:4h")     # 3

        # Trainer prediction
        pipe.get(f"prediction:{symbol}:latest")            # 4

        # Momentum regime flag
        pipe.get(f"wma:momentum_regime:{symbol}")          # 5

        # Current price
        pipe.get(f"price:{symbol}")                        # 6

        results = pipe.execute()

        uf_5m = _decode_hash(results[0])
        uf_15m = _decode_hash(results[1])
        uf_1h = _decode_hash(results[2])
        uf_4h = _decode_hash(results[3])
        pred_raw = _decode_str(results[4])
        mom_regime = _decode_str(results[5])
        price_raw = _decode_str(results[6])

        # Parse trainer prediction
        pred = {}
        if pred_raw:
            try:
                pred = json.loads(pred_raw)
            except Exception:
                pass

        # Parse price
        current_price = 0.0
        if price_raw:
            try:
                p = json.loads(price_raw) if price_raw.startswith("{") else {"price": price_raw}
                current_price = float(p.get("price", 0) or p.get("mark_price", 0) or price_raw or 0)
            except Exception:
                try:
                    current_price = float(price_raw)
                except Exception:
                    pass

        # Check data freshness
        ts_ms = _gf(uf_5m, "ts_ms", 0)
        if ts_ms > 0:
            ctx.data_age_ms = (now * 1000) - ts_ms
            ctx.is_stale = ctx.data_age_ms > 60_000  # >60s = stale

        # ════════════════════════════════════════════════════
        # 1. TREND ANALYSIS (multi-TF ADX + price alignment)
        # ════════════════════════════════════════════════════
        _compute_trend(ctx, uf_5m, uf_15m, uf_1h, uf_4h, pred)

        # ════════════════════════════════════════════════════
        # 2. LIQUIDATION MAGNET
        # ════════════════════════════════════════════════════
        _compute_liquidation_magnet(ctx, uf_5m, current_price)

        # ════════════════════════════════════════════════════
        # 3. VOLATILITY
        # ════════════════════════════════════════════════════
        _compute_volatility(ctx, uf_5m, uf_15m, uf_1h, uf_4h)

        # ════════════════════════════════════════════════════
        # 4. MOMENTUM (acceleration/deceleration)
        # ════════════════════════════════════════════════════
        _compute_momentum(ctx, uf_5m, uf_15m, uf_1h)

        # ════════════════════════════════════════════════════
        # 5. FUNDING & OI
        # ════════════════════════════════════════════════════
        _compute_funding_oi(ctx, uf_5m, uf_1h)

        # ════════════════════════════════════════════════════
        # 6. ORDERBOOK PRESSURE
        # ════════════════════════════════════════════════════
        _compute_orderbook(ctx, uf_5m)

        # ════════════════════════════════════════════════════
        # 7. TAPE FLOW
        # ════════════════════════════════════════════════════
        _compute_tape(ctx, uf_5m)

        # ════════════════════════════════════════════════════
        # 8. TRAINER PREDICTION
        # ════════════════════════════════════════════════════
        if pred:
            ctx.trainer_direction = str(pred.get("direction", "") or "").upper() or None
            ctx.trainer_confidence = float(pred.get("confidence", 0) or 0)

        # ════════════════════════════════════════════════════
        # 9. REGIME
        # ════════════════════════════════════════════════════
        ctx.is_momentum_regime = bool(mom_regime and str(mom_regime).strip().lower() not in ("0", "false", ""))
        # Try to get regime from unified_features
        regime_str = uf_5m.get("regime", "") or uf_5m.get("market_regime", "")
        if not regime_str:
            regime_str = uf_1h.get("regime", "") or uf_1h.get("market_regime", "")
        ctx.regime = str(regime_str).upper() if regime_str else "UNKNOWN"

        # ════════════════════════════════════════════════════
        # 10. COMPOSITE SCORES
        # ════════════════════════════════════════════════════
        _compute_composites(ctx, position_side)

        # Store raw data for debugging
        ctx.raw = {
            "price": current_price,
            "adx_5m": _gf(uf_5m, "ind_ta_ADX_14_5m", 0),
            "adx_1h": _gf(uf_1h, "ind_ta_ADX_14_1h", 0),
            "adx_4h": _gf(uf_4h, "ind_ta_ADX_14_4h", 0),
            "rsi_5m": _gf(uf_5m, "ind_ta_RSI_14_5m", 50),
            "rsi_1h": _gf(uf_1h, "ind_ta_RSI_14_1h", 50),
            "rsi_4h": _gf(uf_4h, "ind_ta_RSI_14_4h", 50),
            "natr_5m": _gf(uf_5m, "ind_ta_NATR_14_5m", 0),
            "natr_1h": _gf(uf_1h, "ind_ta_NATR_14_1h", 0),
            "funding": _gf(uf_5m, "funding_rate", 0),
            "liq_long_dist": ctx.liq_nearest_long_pct,
            "liq_short_dist": ctx.liq_nearest_short_pct,
            "liq_magnet": ctx.liq_magnet_direction,
            "tape_imb_30s": _gf(uf_5m, "tape_imbalance_30s", 0),
            "depth_imb": _gf(uf_5m, "depth_imbalance_5", 0),
            "spoof": _gf(uf_5m, "depth_spoof_score", 0),
            "trainer_dir": ctx.trainer_direction,
            "trainer_conf": ctx.trainer_confidence,
            "momentum_regime": ctx.is_momentum_regime,
        }

    except Exception as e:
        logger.warning("MARKET_INTELLIGENCE_ERR | %s | %s", symbol, e)
        ctx.is_stale = True

    # Cache the result
    _cache[cache_key] = (ctx, now)
    return ctx


# ──────────────────────────────────────────────────────────────
# Internal computation functions
# ──────────────────────────────────────────────────────────────

def _compute_trend(ctx: MarketContext, uf5, uf15, uf1h, uf4h, pred: dict):
    """
    Trend score from multi-TF ADX alignment + price direction + MACD + trainer.
    No static ADX threshold — we use relative strengths.
    """
    # ADX values across timeframes (higher = stronger trend)
    adx_5m = _gf(uf5, "ind_ta_ADX_14_5m", 15)
    adx_15m = _gf(uf15, "ind_ta_ADX_14_15m", 15)
    # Cross-TF fields from 5m hash for convenience
    adx_1h = _gf(uf1h, "ind_ta_ADX_14_1h", 0) or _gf(uf5, "xtf_1h_atr_14", 15)
    adx_4h = _gf(uf4h, "ind_ta_ADX_14_4h", 0) or 15.0

    # Weighted ADX — higher TFs carry more weight for trend direction
    # 4h is the bias TF, 1h is confirm, 15m is trigger, 5m is execution
    weighted_adx = (adx_4h * 0.35 + adx_1h * 0.30 + adx_15m * 0.20 + adx_5m * 0.15)

    # Trend strength: normalize ADX to 0-1 range
    # ADX < 15 = no trend, ADX 15-25 = developing, 25-40 = strong, 40+ = very strong
    # We use a smooth sigmoid-like mapping instead of buckets
    ctx.trend_strength = min(1.0, max(0.0, (weighted_adx - 12.0) / 35.0))

    # Price direction across TFs
    pchg_5m = _gf(uf5, "ccxt_price_change_5m_pct", 0) or _gf(uf5, "xtf_5m_price_change_pct", 0)
    pchg_15m = _gf(uf5, "xtf_15m_price_change_pct", 0)
    pchg_1h = _gf(uf5, "xtf_1h_price_change_pct", 0)
    pchg_4h = _gf(uf5, "xtf_4h_price_change_pct", 0)

    # MACD histogram direction (positive = bullish momentum)
    macd_5m = _gf(uf5, "ind_ta_MACD_hist_fastperiod12_slowperiod26_signalperiod9_5m", 0)
    macd_1h = _gf(uf1h, "ind_ta_MACD_hist_fastperiod12_slowperiod26_signalperiod9_1h", 0)

    # Direction scoring: weighted average of price changes (sign-preserving)
    # Higher TFs weigh more because they indicate true direction
    dir_raw = (
        _sign_clamp(pchg_4h, 3.0) * 0.35 +
        _sign_clamp(pchg_1h, 2.0) * 0.30 +
        _sign_clamp(pchg_15m, 1.5) * 0.20 +
        _sign_clamp(pchg_5m, 1.0) * 0.15
    )

    # MACD adds directional conviction
    macd_dir = (
        _sign_clamp(macd_1h, 5.0) * 0.6 +
        _sign_clamp(macd_5m, 2.0) * 0.4
    )

    # Trainer adds conviction if available
    trainer_dir = 0.0
    if pred:
        td = str(pred.get("direction", "")).upper()
        tc = float(pred.get("confidence", 0) or 0)
        if td == "LONG":
            trainer_dir = tc
        elif td == "SHORT":
            trainer_dir = -tc

    # Combine: price direction (40%) + MACD (30%) + trainer (30%)
    trainer_weight = 0.30 if abs(trainer_dir) > 0.3 else 0.10
    macd_weight = 0.30
    price_weight = 1.0 - trainer_weight - macd_weight

    trend_raw = dir_raw * price_weight + macd_dir * macd_weight + trainer_dir * trainer_weight
    ctx.trend_score = max(-1.0, min(1.0, trend_raw))


def _compute_liquidation_magnet(ctx: MarketContext, uf5: dict, current_price: float):
    """
    Liquidation magnet: where are the liquidity clusters and which direction
    is price likely to be pulled towards?

    Price hunts liquidity. Large liq clusters act as magnets.
    """
    # Distance to nearest clusters (% from current price)
    long_dist = _gf(uf5, "liquidation_long_distance_pct", 99.0)
    short_dist = _gf(uf5, "liquidation_short_distance_pct", 99.0)

    # Strength of clusters (notional USD)
    long_str = _gf(uf5, "liquidation_long_strength", 0)
    short_str = _gf(uf5, "liquidation_short_strength", 0)

    # Multi-TF liquidation data (higher TFs have more accumulated clusters)
    long_str_1h = _gf(uf5, "xtf_1h_liquidation_long_strength", 0)
    short_str_1h = _gf(uf5, "xtf_1h_liquidation_short_strength", 0)
    long_dist_1h = _gf(uf5, "xtf_1h_liquidation_long_distance_pct", 99.0)
    short_dist_1h = _gf(uf5, "xtf_1h_liquidation_short_distance_pct", 99.0)

    ctx.liq_nearest_long_pct = min(long_dist, long_dist_1h) if long_dist_1h < 99 else long_dist
    ctx.liq_nearest_short_pct = min(short_dist, short_dist_1h) if short_dist_1h < 99 else short_dist

    # Magnet direction: price is pulled toward the LARGER cluster that is CLOSER
    # Combine strength and proximity into a "pull" score for each direction
    # Pull = strength / (distance^2 + 0.1) — inverse square law like gravity
    long_pull = (long_str + long_str_1h * 0.5) / (max(long_dist, 0.01) ** 2 + 0.1)
    short_pull = (short_str + short_str_1h * 0.5) / (max(short_dist, 0.01) ** 2 + 0.1)

    total_pull = long_pull + short_pull
    if total_pull > 0:
        # Normalize: >0 means price is pulled toward SHORT liq (price going UP to hunt shorts)
        # <0 means price pulled toward LONG liq (price going DOWN to hunt longs)
        pull_ratio = (short_pull - long_pull) / total_pull
        if pull_ratio > 0.15:
            ctx.liq_magnet_direction = "SHORT"  # Price hunting SHORT liquidations (bullish)
        elif pull_ratio < -0.15:
            ctx.liq_magnet_direction = "LONG"   # Price hunting LONG liquidations (bearish)
        else:
            ctx.liq_magnet_direction = "NEUTRAL"

        # Strength: how strong is the magnet pull? Based on absolute cluster sizes
        # relative to typical ranges
        max_pull = max(long_pull, short_pull)
        ctx.liq_magnet_strength = min(1.0, max_pull / (max_pull + 1e6))

    # Parse detailed liq levels JSON for richer data
    try:
        liq_json = uf5.get("liquidation_levels_json", "")
        if liq_json:
            liq_data = json.loads(liq_json)
            # Count how many clusters are within 2% of price on each side
            top_long = liq_data.get("top_long", [])
            top_short = liq_data.get("top_short", [])
            if current_price > 0:
                nearby_long_str = sum(
                    c.get("strength", 0) for c in top_long
                    if abs(c.get("price", 0) - current_price) / current_price * 100 < 2.0
                )
                nearby_short_str = sum(
                    c.get("strength", 0) for c in top_short
                    if abs(c.get("price", 0) - current_price) / current_price * 100 < 2.0
                )
                # Refine magnet with nearby cluster data
                if nearby_short_str > nearby_long_str * 3:
                    ctx.liq_magnet_direction = "SHORT"
                    ctx.liq_magnet_strength = max(ctx.liq_magnet_strength, 0.7)
                elif nearby_long_str > nearby_short_str * 3:
                    ctx.liq_magnet_direction = "LONG"
                    ctx.liq_magnet_strength = max(ctx.liq_magnet_strength, 0.7)
    except Exception:
        pass


def _compute_volatility(ctx: MarketContext, uf5, uf15, uf1h, uf4h):
    """
    Volatility regime from ATR across timeframes.
    Uses relative ATR (NATR) which is already %-normalized, avoiding static buckets.
    """
    natr_5m = _gf(uf5, "ind_ta_NATR_14_5m", 0.3)
    natr_1h = _gf(uf1h, "ind_ta_NATR_14_1h", 0) or _gf(uf5, "xtf_1h_atr_14", 0)
    natr_4h = _gf(uf4h, "ind_ta_NATR_14_4h", 0)

    # Fast move score from microstructure
    fast_move = _gf(uf5, "depth_fast_move_score", 0)
    fast_move_5m = _gf(uf5, "depth_fast_move_5m", 0)
    fast_move_15m = _gf(uf5, "depth_fast_move_15m", 0)

    # Composite volatility: weight higher TFs more
    # NATR is already in % (e.g., 0.3 = 0.3% per bar)
    # For 5m NATR ~0.1-0.5 is normal, 0.5-1.0 is high, >1.0 is extreme
    # For 1h NATR ~0.5-1.5 is normal, 1.5-3.0 is high, >3.0 is extreme
    # Normalize each to 0-1 scale using their typical ranges
    vol_5m = min(1.0, natr_5m / 1.0)       # 1.0% NATR on 5m = max
    vol_1h = min(1.0, natr_1h / 3.0) if natr_1h > 0 else vol_5m  # 3.0% on 1h = max
    vol_4h = min(1.0, natr_4h / 5.0) if natr_4h > 0 else vol_1h  # 5.0% on 4h = max

    # Fast move adds acute volatility
    acute_vol = max(fast_move, fast_move_5m, fast_move_15m)

    # Weighted composite
    ctx.volatility_norm = min(1.0, (
        vol_4h * 0.30 +
        vol_1h * 0.30 +
        vol_5m * 0.25 +
        acute_vol * 0.15
    ))

    # Regime labels
    if ctx.volatility_norm < 0.15:
        ctx.volatility_regime = "CALM"
    elif ctx.volatility_norm < 0.35:
        ctx.volatility_regime = "NORMAL"
    elif ctx.volatility_norm < 0.65:
        ctx.volatility_regime = "HIGH"
    else:
        ctx.volatility_regime = "EXTREME"


def _compute_momentum(ctx: MarketContext, uf5, uf15, uf1h):
    """
    Momentum: is the move accelerating or decelerating?
    Positive = accelerating in current direction, negative = fading.
    Uses MACD histogram, RSI velocity, tape CVD, volume.
    """
    # MACD histogram — positive and increasing = bullish momentum
    macd_5m = _gf(uf5, "ind_ta_MACD_hist_fastperiod12_slowperiod26_signalperiod9_5m", 0)
    macd_1h = _gf(uf1h, "ind_ta_MACD_hist_fastperiod12_slowperiod26_signalperiod9_1h", 0)

    # RSI — > 50 is bullish, < 50 is bearish; distance from 50 = momentum strength
    rsi_5m = _gf(uf5, "ind_ta_RSI_14_5m", 50)
    rsi_1h = _gf(uf1h, "ind_ta_RSI_14_1h", 50)

    # Tape CVD (cumulative volume delta) — positive = net buying
    tape_imb_30s = _gf(uf5, "tape_imbalance_30s", 0)
    tape_imb_5s = _gf(uf5, "tape_imbalance_5s", 0)

    # Price change velocity (bigger = more momentum)
    pchg_5m = _gf(uf5, "xtf_5m_price_change_pct", 0) or _gf(uf5, "ccxt_price_change_5m_pct", 0)
    pchg_1h = _gf(uf5, "xtf_1h_price_change_pct", 0)

    # MACD direction and magnitude (normalized to approx -1..+1 range)
    macd_score = (
        _sign_clamp(macd_1h, 5.0) * 0.6 +
        _sign_clamp(macd_5m, 2.0) * 0.4
    )

    # RSI momentum (how far from neutral 50, directional)
    rsi_score = (
        ((rsi_1h - 50.0) / 40.0) * 0.6 +
        ((rsi_5m - 50.0) / 40.0) * 0.4
    )

    # Tape momentum
    tape_score = (
        tape_imb_30s * 0.6 +
        tape_imb_5s * 0.4
    )

    # Price velocity
    vel_score = (
        _sign_clamp(pchg_1h, 2.0) * 0.6 +
        _sign_clamp(pchg_5m, 1.0) * 0.4
    )

    # Combine: MACD(30%) + RSI(25%) + Tape(25%) + Velocity(20%)
    raw_momentum = (
        macd_score * 0.30 +
        rsi_score * 0.25 +
        tape_score * 0.25 +
        vel_score * 0.20
    )
    ctx.momentum_score = max(-1.0, min(1.0, raw_momentum))


def _compute_funding_oi(ctx: MarketContext, uf5: dict, uf1h: dict):
    """
    Funding pressure and OI velocity.
    Funding > 0 = longs pay shorts (bullish crowded), < 0 = shorts pay longs.
    """
    funding = _gf(uf5, "funding_rate", 0)

    # Normalize funding: typical range is -0.001 to +0.001 (extreme)
    # Map to -1..+1 with smooth scaling
    ctx.funding_pressure = max(-1.0, min(1.0, funding / 0.0005))

    # OI from CoinAnk (if available)
    oi_close = _gf(uf5, "coinank_openInterest_kline_data_0_close", 0)
    # We don't have historical OI readily, so we use funding + L/S ratio as proxy
    # for leveraging direction
    ls_ratio = _gf(uf5, "coinank_ls_global_account_ratio_longShortRatio_mean", 1.0)

    # OI velocity proxy: extreme L/S ratio = crowded trade = potential squeeze
    if ls_ratio > 0:
        ls_norm = (ls_ratio - 1.0) / 1.0  # >1 = more longs, <1 = more shorts
        ctx.oi_velocity = max(-1.0, min(1.0, ls_norm * 0.5))


def _compute_orderbook(ctx: MarketContext, uf5: dict):
    """
    Orderbook pressure from depth imbalance and USD depth.
    """
    imbalance_5 = _gf(uf5, "depth_imbalance_5", 0)
    ob_imbalance = _gf(uf5, "ob_ob_imbalance", 0)

    # Spoof detection
    spoof = _gf(uf5, "depth_spoof_score", 0)
    spoof_v2 = _gf(uf5, "depth_spoof_score_v2", 0)
    ctx.spoof_risk = max(spoof, spoof_v2)

    # Multi-TF orderbook imbalance (weighted)
    imb_15m = _gf(uf5, "xtf_15m_ob_ob_imbalance", 0)
    imb_1h = _gf(uf5, "xtf_1h_ob_ob_imbalance", 0)

    # Composite: depth_imbalance_5 is real-time (neg = sell side heavier)
    # ob_ob_imbalance is from Binance REST (updates less frequently)
    raw_pressure = (
        imbalance_5 * 0.30 +
        ob_imbalance * 0.20 +
        imb_15m * 0.25 +
        imb_1h * 0.25
    )

    # Discount if spoofed — can't trust the book
    if ctx.spoof_risk > 0.3:
        raw_pressure *= (1.0 - ctx.spoof_risk * 0.5)

    ctx.orderbook_pressure = max(-1.0, min(1.0, raw_pressure))


def _compute_tape(ctx: MarketContext, uf5: dict):
    """
    Tape analysis from real-time trade flow.
    """
    imb_1s = _gf(uf5, "tape_imbalance_1s", 0)
    imb_5s = _gf(uf5, "tape_imbalance_5s", 0)
    imb_30s = _gf(uf5, "tape_imbalance_30s", 0)

    # Longer windows are more reliable
    ctx.tape_pressure = max(-1.0, min(1.0, (
        imb_30s * 0.50 +
        imb_5s * 0.30 +
        imb_1s * 0.20
    )))


def _compute_composites(ctx: MarketContext, position_side: Optional[str]):
    """
    Compute the three main composite scores that consumers use:
    - hold_score: should we hold the position?
    - exit_score: should we exit now?
    - extend_score: should TP/trail targets be further out?

    These are RELATIVE to the position_side if provided.
    """
    side_mult = 1.0  # +1 for LONG, -1 for SHORT
    if position_side:
        side_mult = 1.0 if position_side.upper() == "LONG" else -1.0

    # ── HOLD SCORE ──
    # High when: trend is in our direction + momentum building + no reversal signals
    trend_favor = ctx.trend_score * side_mult         # >0 when trend matches our side
    momentum_favor = ctx.momentum_score * side_mult   # >0 when momentum matches
    tape_favor = ctx.tape_pressure * side_mult        # >0 when tape supports us

    # Liq magnet alignment: if price is being pulled TOWARDS shorts and we're LONG, that's good
    liq_favor = 0.0
    if ctx.liq_magnet_direction == "SHORT" and side_mult > 0:
        liq_favor = ctx.liq_magnet_strength * 0.5
    elif ctx.liq_magnet_direction == "LONG" and side_mult < 0:
        liq_favor = ctx.liq_magnet_strength * 0.5
    elif ctx.liq_magnet_direction == "SHORT" and side_mult < 0:
        liq_favor = -ctx.liq_magnet_strength * 0.5
    elif ctx.liq_magnet_direction == "LONG" and side_mult > 0:
        liq_favor = -ctx.liq_magnet_strength * 0.5

    # Funding: if funding is against us (we're paying), that's a hold-negative
    funding_favor = -ctx.funding_pressure * side_mult  # Neg funding for longs = good for longs

    hold_raw = (
        max(0, trend_favor) * 0.30 +     # Trend in our direction
        max(0, momentum_favor) * 0.25 +   # Momentum building
        max(0, tape_favor) * 0.15 +        # Tape confirms
        max(0, liq_favor) * 0.15 +         # Liq clusters support
        max(0, funding_favor) * 0.10 +     # Funding not against us
        ctx.trend_strength * 0.05          # Strong trend = hold regardless of direction
    )
    ctx.hold_score = max(0.0, min(1.0, hold_raw))

    # ── EXIT SCORE ──
    # High when: reversal signals + momentum fading + adversarial conditions
    # Reversal risk from RSI extremes
    reversal_signals = ctx.reversal_risk

    # Trend against us
    trend_against = max(0, -trend_favor)
    momentum_against = max(0, -momentum_favor)
    tape_against = max(0, -tape_favor)
    liq_against = max(0, -liq_favor)

    # Spoof risk increases exit urgency
    spoof_penalty = ctx.spoof_risk * 0.3

    exit_raw = (
        reversal_signals * 0.25 +
        trend_against * 0.20 +
        momentum_against * 0.20 +
        liq_against * 0.15 +
        tape_against * 0.10 +
        spoof_penalty * 0.10
    )
    ctx.exit_score = max(0.0, min(1.0, exit_raw))

    # ── EXTEND SCORE ──
    # High when: strong trend + momentum building + liq targets ahead + vol expanding
    extend_raw = (
        max(0, trend_favor) * 0.25 +
        ctx.trend_strength * 0.20 +
        max(0, momentum_favor) * 0.20 +
        max(0, liq_favor) * 0.15 +
        ctx.volatility_norm * 0.10 +        # Higher vol = wider targets
        (1.0 - ctx.reversal_risk) * 0.10    # Low reversal risk = safe to extend
    )
    ctx.extend_score = max(0.0, min(1.0, extend_raw))

    # ── REVERSAL RISK (compute here with full context) ──
    # This was partially set but now refined with all data
    _compute_reversal_risk(ctx, side_mult)


def _compute_reversal_risk(ctx: MarketContext, side_mult: float):
    """
    Reversal risk assessment combining multiple signals.
    """
    risk = 0.0

    # 1. Momentum fading (momentum against our direction)
    if ctx.momentum_score * side_mult < -0.3:
        risk += abs(ctx.momentum_score * side_mult) * 0.3

    # 2. Tape diverging from trend (tape selling while trend up, or vice versa)
    if ctx.tape_pressure * side_mult < -0.2 and ctx.trend_score * side_mult > 0.2:
        risk += 0.2  # Tape disagrees with trend

    # 3. Liq magnet pulling against us
    if (ctx.liq_magnet_direction == "LONG" and side_mult > 0) or \
       (ctx.liq_magnet_direction == "SHORT" and side_mult < 0):
        risk += ctx.liq_magnet_strength * 0.2

    # 4. Funding extremely against us
    funding_against = ctx.funding_pressure * side_mult
    if funding_against > 0.5:  # We're heavily crowded
        risk += funding_against * 0.15

    # 5. Spoof risk (book might be fake)
    risk += ctx.spoof_risk * 0.15

    ctx.reversal_risk = max(0.0, min(1.0, risk))


# ──────────────────────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────────────────────

def _gf(d: dict, key: str, default: float = 0.0) -> float:
    """Get float from dict, handling bytes/str/None safely."""
    if not d:
        return default
    val = d.get(key)
    if val is None:
        return default
    try:
        if isinstance(val, bytes):
            val = val.decode()
        return float(val)
    except (ValueError, TypeError):
        return default


def _sign_clamp(val: float, scale: float) -> float:
    """Normalize a value to -1..+1 range, preserving sign. Scale is the 'typical max'."""
    if scale <= 0:
        return 0.0
    return max(-1.0, min(1.0, val / scale))


def _decode_hash(raw) -> dict:
    """Decode a Redis hash result (bytes keys/values to str)."""
    if not raw:
        return {}
    out = {}
    for k, v in raw.items():
        key = k.decode() if isinstance(k, bytes) else str(k)
        val = v.decode() if isinstance(v, bytes) else str(v)
        out[key] = val
    return out


def _decode_str(raw) -> str:
    """Decode a Redis string result."""
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        return raw.decode()
    return str(raw)


# ──────────────────────────────────────────────────────────────
# Convenience functions for specific use cases
# ──────────────────────────────────────────────────────────────

def should_allow_close(
    redis_client,
    symbol: str,
    position_side: str,
    close_source: str = "trainer",
    roe_pct: float = 0.0,
    unrealized_pnl: float = 0.0,
    confidence: float = 0.0,
) -> tuple:
    """
    Intelligence-driven gate: should we allow this position close?

    Consults ALL data sources before permitting any close:
      1. Trainer predictions (direction + confidence)
      2. CoinAnk data (OI, funding rate, L/S ratio)
      3. OHLCV multi-TF klines (ADX trend, MACD, RSI, price change alignment)
      4. Liquidation levels (cluster proximity, magnet direction)
      5. Tape flow (CVD, imbalance, taker ratio)
      6. Orderbook depth (imbalance, spoof detection)

    Differentiates between:
      - Profitable closes: allow if move is exhausting (reversal signals)
      - Losing closes: block unless strong multi-source confirmation says exit

    Returns: (allow: bool, reason: str, hold_score: float)
        allow=True  → proceed with close
        allow=False → DEFER close, market says hold

    Kill switch: config.INTELLIGENCE_CLOSE_GATE_ENABLED (default True)
    """
    try:
        import config as _icg_cfg
        if not bool(getattr(_icg_cfg, "INTELLIGENCE_CLOSE_GATE_ENABLED", True)):
            return True, "kill_switch_off", 0.0
    except Exception:
        pass

    ctx = get_market_context(redis_client, symbol, position_side=position_side)

    if ctx.is_stale:
        # Stale data → fail-safe: allow the close (don't block on bad data)
        return True, "stale_data_allow", 0.0

    side_mult = 1.0 if position_side.upper() == "LONG" else -1.0
    reasons = []
    hold_reasons = []
    exit_reasons = []
    data_sources = 0

    # ═══════════════════════════════════════════
    # SOURCE 1: OHLCV KLINES (multi-TF trend + momentum)
    # ═══════════════════════════════════════════
    # Is trend still in our direction? If so, closing cuts the winner short.
    trend_favor = ctx.trend_score * side_mult
    if abs(ctx.trend_score) > 0.05:
        data_sources += 1

    if trend_favor > 0.25:
        hold_reasons.append(f"trend_favoring({trend_favor:.2f})")
    elif trend_favor < -0.25:
        exit_reasons.append(f"trend_against({trend_favor:.2f})")

    # Trend STRENGTH: strong trend in our direction = definitely hold
    if ctx.trend_strength > 0.4 and trend_favor > 0.15:
        hold_reasons.append(f"strong_trend({ctx.trend_strength:.2f})")

    # ═══════════════════════════════════════════
    # SOURCE 2: MOMENTUM (MACD + RSI + velocity)
    # ═══════════════════════════════════════════
    momentum_favor = ctx.momentum_score * side_mult
    if abs(ctx.momentum_score) > 0.05:
        data_sources += 1

    if momentum_favor > 0.2:
        hold_reasons.append(f"momentum_building({momentum_favor:.2f})")
    elif momentum_favor < -0.2:
        exit_reasons.append(f"momentum_fading({momentum_favor:.2f})")

    # ═══════════════════════════════════════════
    # SOURCE 3: COINANK (OI, funding, L/S ratio)
    # ═══════════════════════════════════════════
    if abs(ctx.funding_pressure) > 0.01:
        data_sources += 1

    # Funding against us = argument to close (we're paying to hold)
    funding_against = ctx.funding_pressure * side_mult
    if funding_against > 0.3:
        exit_reasons.append(f"funding_against({funding_against:.2f})")
    elif funding_against < -0.3:
        hold_reasons.append(f"funding_favorable({funding_against:.2f})")

    # OI velocity: rapid deleveraging in our direction = everyone leaving
    if abs(ctx.oi_velocity) > 0.01:
        data_sources += 1
    oi_favor = ctx.oi_velocity * side_mult
    if oi_favor < -0.3:
        exit_reasons.append(f"oi_deleveraging({oi_favor:.2f})")

    # ═══════════════════════════════════════════
    # SOURCE 4: LIQUIDATION LEVELS
    # ═══════════════════════════════════════════
    if ctx.liq_magnet_strength > 0.01:
        data_sources += 1

    # Liq magnet pulling price in our direction = hold for the cascade
    liq_favor = 0.0
    if (ctx.liq_magnet_direction == "SHORT" and side_mult > 0):
        liq_favor = ctx.liq_magnet_strength
        hold_reasons.append(f"liq_hunt_ahead({ctx.liq_magnet_direction},{liq_favor:.2f})")
    elif (ctx.liq_magnet_direction == "LONG" and side_mult < 0):
        liq_favor = ctx.liq_magnet_strength
        hold_reasons.append(f"liq_hunt_ahead({ctx.liq_magnet_direction},{liq_favor:.2f})")
    elif (ctx.liq_magnet_direction == "SHORT" and side_mult < 0):
        liq_favor = -ctx.liq_magnet_strength
        exit_reasons.append(f"liq_against({ctx.liq_magnet_direction},{ctx.liq_magnet_strength:.2f})")
    elif (ctx.liq_magnet_direction == "LONG" and side_mult > 0):
        liq_favor = -ctx.liq_magnet_strength
        exit_reasons.append(f"liq_against({ctx.liq_magnet_direction},{ctx.liq_magnet_strength:.2f})")

    # ═══════════════════════════════════════════
    # SOURCE 5: TAPE FLOW (real trades)
    # ═══════════════════════════════════════════
    tape_favor = ctx.tape_pressure * side_mult
    if abs(ctx.tape_pressure) > 0.01:
        data_sources += 1

    if tape_favor > 0.2:
        hold_reasons.append(f"tape_supporting({tape_favor:.2f})")
    elif tape_favor < -0.2:
        exit_reasons.append(f"tape_against({tape_favor:.2f})")

    # ═══════════════════════════════════════════
    # SOURCE 6: ORDERBOOK DEPTH
    # ═══════════════════════════════════════════
    ob_favor = ctx.orderbook_pressure * side_mult
    if abs(ctx.orderbook_pressure) > 0.01:
        data_sources += 1

    if ob_favor > 0.2 and ctx.spoof_risk < 0.4:
        hold_reasons.append(f"ob_supporting({ob_favor:.2f})")
    elif ob_favor < -0.2 and ctx.spoof_risk < 0.4:
        exit_reasons.append(f"ob_against({ob_favor:.2f})")

    # Spoof risk: can't trust the book
    if ctx.spoof_risk > 0.4:
        exit_reasons.append(f"spoof_risk({ctx.spoof_risk:.2f})")

    # ═══════════════════════════════════════════
    # SOURCE 7: TRAINER PREDICTION
    # ═══════════════════════════════════════════
    if ctx.trainer_direction and ctx.trainer_confidence > 0.1:
        data_sources += 1
        trainer_favor = 0.0
        if ctx.trainer_direction == position_side.upper():
            trainer_favor = ctx.trainer_confidence
            hold_reasons.append(f"trainer_agrees({ctx.trainer_direction},{ctx.trainer_confidence:.2f})")
        else:
            trainer_favor = -ctx.trainer_confidence
            exit_reasons.append(f"trainer_disagrees({ctx.trainer_direction},{ctx.trainer_confidence:.2f})")

    # ═══════════════════════════════════════════
    # REVERSAL RISK (composite)
    # ═══════════════════════════════════════════
    if ctx.reversal_risk > 0.4:
        exit_reasons.append(f"reversal_risk({ctx.reversal_risk:.2f})")

    # ═══════════════════════════════════════════
    # DECISION LOGIC — different for profitable vs losing positions
    # ═══════════════════════════════════════════
    n_hold = len(hold_reasons)
    n_exit = len(exit_reasons)
    is_profitable = (roe_pct > 0.5 or unrealized_pnl > 0.5)

    # Minimum data sources required (fail-safe: if too few sources, allow close)
    min_sources = 2
    try:
        import config as _ms_cfg
        min_sources = int(getattr(_ms_cfg, "INTELLIGENCE_CLOSE_GATE_MIN_SOURCES", 2))
    except Exception:
        pass

    if data_sources < min_sources:
        return True, f"insufficient_data_sources({data_sources}<{min_sources})", ctx.hold_score

    # ── PROFITABLE CLOSE: Only block if strong multi-source evidence says HOLD ──
    if is_profitable:
        # Profitable position: the close is taking profit.
        # Block ONLY if: (a) composite hold_score is high AND (b) more hold reasons than exit
        # AND (c) momentum still building AND (d) no strong reversal risk
        if (ctx.hold_score > 0.50
            and n_hold >= 3
            and n_hold > n_exit
            and momentum_favor > 0.1
            and ctx.reversal_risk < 0.4):
            reason = f"HOLD_PROFITABLE: hold={ctx.hold_score:.2f} exit={ctx.exit_score:.2f} sources={data_sources} | " + \
                     " | ".join(hold_reasons[:4])
            return False, reason, ctx.hold_score

        # Special: momentum regime + profitable = definitely hold
        if ctx.is_momentum_regime and momentum_favor > 0.15:
            reason = f"MOMENTUM_REGIME_HOLD: mom={momentum_favor:.2f} | " + " | ".join(hold_reasons[:3])
            return False, reason, ctx.hold_score

    # ── LOSING CLOSE: Block unless multiple sources confirm exit ──
    else:
        # Losing position: the close would realize a loss.
        # Block (DEFER) if: hold evidence >= exit evidence AND trend still favorable
        # The system should NOT close losses unless overwhelming evidence says get out.

        # Strong hold signal from data = defer the loss close
        if (ctx.hold_score > 0.35
            and n_hold >= 2
            and trend_favor > 0.1
            and momentum_favor > -0.15):
            reason = f"DEFER_LOSS_CLOSE: hold={ctx.hold_score:.2f} exit={ctx.exit_score:.2f} " + \
                     f"trend_favor={trend_favor:.2f} mom={momentum_favor:.2f} sources={data_sources} | " + \
                     " | ".join(hold_reasons[:4])
            return False, reason, ctx.hold_score

        # Even if hold_score is moderate, if trend + momentum are both favorable, defer
        if trend_favor > 0.2 and momentum_favor > 0.1 and n_exit < 2:
            reason = f"TREND_MOM_DEFER: trend={trend_favor:.2f} mom={momentum_favor:.2f} exits={n_exit} | " + \
                     " | ".join(hold_reasons[:3])
            return False, reason, ctx.hold_score

        # Liq magnet strongly in our direction = price will snap back
        if liq_favor > 0.4:
            reason = f"LIQ_MAGNET_DEFER: liq_favor={liq_favor:.2f} dir={ctx.liq_magnet_direction} | " + \
                     " | ".join(hold_reasons[:3])
            return False, reason, ctx.hold_score

    # ── ALLOW CLOSE: insufficient hold evidence or exit evidence dominates ──
    all_reasons = exit_reasons if exit_reasons else ["no_hold_signal"]
    reason = f"ALLOW: hold={ctx.hold_score:.2f} exit={ctx.exit_score:.2f} " + \
             f"sources={data_sources} holds={n_hold} exits={n_exit} | " + \
             " | ".join(all_reasons[:4])
    return True, reason, ctx.hold_score


def should_close_hedge_loser(
    redis_client,
    symbol: str,
    loser_side: str,
    winner_roi: float,
    loser_roi: float,
    net_pnl: float,
    net_roi: float,
) -> tuple:
    """
    Intelligence-driven decision: should we close the losing hedge leg?

    Returns: (should_close: bool, reason: str, confidence: float)

    STRICT REQUIREMENTS (all must pass before scoring):
    1. Winner must actually be profitable (ROI > 0%) OR much better than loser (spread > 15%)
    2. Clear ROI separation between legs (> 10% spread) — nearly equal ROIs = hold hedge
    3. Trend must favor the winner direction (no guessing on flat trends)
    4. No recent selective unwind on this symbol (cooldown check)
    """
    winner_side = "SHORT" if loser_side.upper() == "LONG" else "LONG"
    ctx = get_market_context(redis_client, symbol, position_side=winner_side)

    reasons = []
    vetoes = []  # Hard vetoes that block the unwind
    score = 0.0  # Positive = close loser, negative = hold both

    # ═══════════════════════════════════════════
    # HARD PREREQUISITES — fail any = reject
    # ═══════════════════════════════════════════

    # P1: ROI spread between legs must be meaningful (at least 10%)
    roi_spread = winner_roi - loser_roi
    if roi_spread < 10.0:
        vetoes.append(f"roi_spread_too_small({roi_spread:.1f}%<10%)")

    # P2: Winner must be profitable OR loser must be deeply underwater (< -15% ROI)
    if winner_roi <= 0 and loser_roi > -15.0:
        vetoes.append(f"no_clear_winner(winner={winner_roi:.1f}%,loser={loser_roi:.1f}%)")

    # P3: Trend must favor the winner direction (minimum threshold)
    trend_favor = ctx.trend_score * (1.0 if winner_side == "LONG" else -1.0)
    if trend_favor < 0.1:
        vetoes.append(f"trend_not_favoring_winner({trend_favor:.2f})")

    # P4: Check cooldown — don't do selective unwind if we just did one recently
    try:
        cooldown_key = f"wma:hedge_unwind_cooldown:{symbol}"
        cooldown_val = redis_client.get(cooldown_key)
        if cooldown_val:
            vetoes.append(f"cooldown_active")
    except Exception:
        pass

    # If any veto fires, reject immediately
    if vetoes:
        reason = "VETO: " + " | ".join(vetoes)
        return False, reason, 0.0

    # ═══════════════════════════════════════════
    # SCORING — only reached if prerequisites pass
    # ═══════════════════════════════════════════

    # 1. Trend alignment: if trend supports the winner, close the loser
    if trend_favor > 0.2:
        score += trend_favor * 0.20
        reasons.append(f"trend_favors_winner({trend_favor:.2f})")

    # 2. Momentum: building momentum in winner direction = close loser
    mom_favor = ctx.momentum_score * (1.0 if winner_side == "LONG" else -1.0)
    if mom_favor > 0.2:
        score += mom_favor * 0.15
        reasons.append(f"momentum_building({mom_favor:.2f})")

    # 3. Liq magnet: if liq clusters ahead in winner direction = huge upside potential
    if (ctx.liq_magnet_direction == "SHORT" and winner_side == "LONG") or \
       (ctx.liq_magnet_direction == "LONG" and winner_side == "SHORT"):
        score += ctx.liq_magnet_strength * 0.15
        reasons.append(f"liq_magnet_favors_winner({ctx.liq_magnet_direction},{ctx.liq_magnet_strength:.2f})")

    # 4. Tape flow: real trades supporting winner direction
    tape_favor = ctx.tape_pressure * (1.0 if winner_side == "LONG" else -1.0)
    if tape_favor > 0.15:
        score += tape_favor * 0.10
        reasons.append(f"tape_supports_winner({tape_favor:.2f})")

    # 5. Volatility: high vol = more potential upside if trend is right
    if ctx.volatility_norm > 0.3 and trend_favor > 0:
        score += 0.08
        reasons.append(f"vol_expanding({ctx.volatility_norm:.2f})")

    # 6. Winner ROI already substantial = the move is real
    if winner_roi > 10.0:
        score += 0.15
        reasons.append(f"winner_roi_very_strong({winner_roi:.1f}%)")
    elif winner_roi > 5.0:
        score += 0.10
        reasons.append(f"winner_roi_strong({winner_roi:.1f}%)")

    # 7. Net PnL positive = we can afford to cut the loser
    if net_pnl > 0:
        score += 0.10
        reasons.append(f"net_positive(${net_pnl:.2f})")

    # 8. ROI spread bonus — bigger spread = more conviction
    if roi_spread > 30.0:
        score += 0.10
        reasons.append(f"roi_spread_wide({roi_spread:.1f}%)")
    elif roi_spread > 20.0:
        score += 0.05
        reasons.append(f"roi_spread_good({roi_spread:.1f}%)")

    # 9. Reversal risk: if high, DO NOT cut loser (it's your hedge!)
    if ctx.reversal_risk > 0.4:
        score -= ctx.reversal_risk * 0.25
        reasons.append(f"reversal_risk({ctx.reversal_risk:.2f})")

    # 10. Spoof risk: if book is fake, be cautious
    if ctx.spoof_risk > 0.3:
        score -= ctx.spoof_risk * 0.15
        reasons.append(f"spoof_risk({ctx.spoof_risk:.2f})")

    # Decision threshold: RAISED to 0.55 (was 0.35 — way too aggressive)
    should_close = score > 0.55
    confidence = min(1.0, abs(score))
    reason = " | ".join(reasons) if reasons else "insufficient_signals"

    return should_close, reason, confidence


def should_close_both_legs(
    redis_client,
    symbol: str,
    winner_roi: float,
    loser_roi: float,
    net_pnl: float,
    net_roi: float,
) -> tuple:
    """
    Intelligence-driven decision: should we close BOTH hedge legs?

    This is the nuclear option — only when:
    - Trend is unclear/ranging (no edge keeping either leg)
    - Momentum is fading on both sides
    - Net profit is substantial enough to justify exiting
    - No strong liq magnet to chase

    Returns: (should_close: bool, reason: str, confidence: float)
    """
    ctx = get_market_context(redis_client, symbol)

    reasons = []
    score = 0.0

    # 1. Trend weakness: low trend strength = no edge, take the money
    if ctx.trend_strength < 0.25:
        score += (0.25 - ctx.trend_strength) * 0.30
        reasons.append(f"weak_trend({ctx.trend_strength:.2f})")

    # 2. Momentum fading: near zero = consolidation = take profit
    if abs(ctx.momentum_score) < 0.15:
        score += 0.20
        reasons.append(f"momentum_flat({ctx.momentum_score:.2f})")

    # 3. No strong liq magnet to chase
    if ctx.liq_magnet_strength < 0.3:
        score += 0.15
        reasons.append(f"no_liq_target({ctx.liq_magnet_strength:.2f})")

    # 4. Net profit substantial (relative to margin)
    if net_roi > 5.0:
        score += 0.15
        reasons.append(f"good_net_roi({net_roi:.1f}%)")
    if net_pnl > 10.0:
        score += 0.10
        reasons.append(f"good_net_pnl(${net_pnl:.2f})")

    # 5. Reversal risk high = take the money and run
    if ctx.reversal_risk > 0.5:
        score += ctx.reversal_risk * 0.15
        reasons.append(f"reversal_risk({ctx.reversal_risk:.2f})")

    # 6. CALM volatility = market going sideways, no edge
    if ctx.volatility_regime == "CALM":
        score += 0.10
        reasons.append("vol_calm")

    # Penalty: if trend is strong and momentum building, don't close both
    if ctx.trend_strength > 0.5 and abs(ctx.momentum_score) > 0.3:
        score -= 0.30
        reasons.append(f"strong_trend_momentum({ctx.trend_strength:.2f},{ctx.momentum_score:.2f})")

    should_close = score > 0.45  # Higher bar than selective unwind
    confidence = min(1.0, abs(score))
    reason = " | ".join(reasons) if reasons else "insufficient_signals"

    return should_close, reason, confidence


def get_adaptive_tp_multiplier(redis_client, symbol: str, position_side: str) -> tuple:
    """
    Get intelligence-driven TP distance multiplier.

    Returns: (multiplier: float, reason: str)
        multiplier > 1.0 = extend TP further
        multiplier < 1.0 = tighten TP closer

    Called by DynamicTPEngine to adjust TP targets based on live conditions.
    """
    ctx = get_market_context(redis_client, symbol, position_side=position_side)

    mult = 1.0
    reasons = []

    # Strong trend in our direction = extend TP
    if ctx.extend_score > 0.5:
        extension = 1.0 + (ctx.extend_score - 0.5) * 1.5  # Up to 1.75x
        mult *= extension
        reasons.append(f"extend({ctx.extend_score:.2f}→{extension:.2f}x)")

    # Liq clusters ahead in favorable direction = extend TP past them
    side_mult = 1.0 if position_side.upper() == "LONG" else -1.0
    if (ctx.liq_magnet_direction == "SHORT" and side_mult > 0) or \
       (ctx.liq_magnet_direction == "LONG" and side_mult < 0):
        liq_ext = 1.0 + ctx.liq_magnet_strength * 0.5  # Up to 1.5x
        mult *= liq_ext
        reasons.append(f"liq_ahead({ctx.liq_magnet_direction},{liq_ext:.2f}x)")

    # High volatility = wider targets achievable
    if ctx.volatility_norm > 0.4:
        vol_ext = 1.0 + (ctx.volatility_norm - 0.4) * 0.8  # Up to 1.48x
        mult *= vol_ext
        reasons.append(f"high_vol({ctx.volatility_norm:.2f}→{vol_ext:.2f}x)")

    # Reversal risk = tighten TP
    if ctx.reversal_risk > 0.4:
        rev_tighten = 1.0 - (ctx.reversal_risk - 0.4) * 0.5  # Down to 0.7x
        mult *= max(0.5, rev_tighten)
        reasons.append(f"reversal_risk({ctx.reversal_risk:.2f}→{rev_tighten:.2f}x)")

    # Spoof risk = don't trust the move, tighten
    if ctx.spoof_risk > 0.5:
        spoof_tighten = 1.0 - (ctx.spoof_risk - 0.5) * 0.4
        mult *= max(0.6, spoof_tighten)
        reasons.append(f"spoof({ctx.spoof_risk:.2f}→{spoof_tighten:.2f}x)")

    # Momentum regime = let it run much further
    if ctx.is_momentum_regime:
        mult *= 1.5
        reasons.append("momentum_regime(1.5x)")

    # Clamp
    mult = max(0.5, min(3.0, mult))
    reason = " | ".join(reasons) if reasons else "neutral"

    return mult, reason


def get_adaptive_trail_params(redis_client, symbol: str, position_side: str) -> dict:
    """
    Get intelligence-driven trail parameters.

    Returns dict with:
        trail_distance_mult: float  — multiply base trail distance by this
        trail_activation_mult: float — multiply base activation by this
        min_profit_lock_pct: float   — minimum % of profit to lock
        reason: str
    """
    ctx = get_market_context(redis_client, symbol, position_side=position_side)

    trail_dist_mult = 1.0
    trail_act_mult = 1.0
    min_lock_pct = 50.0  # default: lock 50% of peak profit
    reasons = []

    # Strong trend in our direction = widen trail (let it run)
    if ctx.extend_score > 0.5:
        widen = 1.0 + (ctx.extend_score - 0.5) * 2.0  # Up to 2.0x wider trail
        trail_dist_mult *= widen
        trail_act_mult *= 1.0 + (ctx.extend_score - 0.5) * 0.5  # Later activation
        min_lock_pct = max(25.0, min_lock_pct - (ctx.extend_score - 0.5) * 40)
        reasons.append(f"trend_extend({widen:.2f}x)")

    # High reversal risk = tighten trail (protect profits)
    if ctx.reversal_risk > 0.4:
        tighten = 1.0 - (ctx.reversal_risk - 0.4) * 0.6  # Down to 0.64x
        trail_dist_mult *= max(0.4, tighten)
        min_lock_pct = min(80.0, min_lock_pct + (ctx.reversal_risk - 0.4) * 40)
        reasons.append(f"reversal_tighten({tighten:.2f}x)")

    # Liq clusters ahead = widen trail to capture the cascade
    side_mult = 1.0 if position_side.upper() == "LONG" else -1.0
    if (ctx.liq_magnet_direction == "SHORT" and side_mult > 0) or \
       (ctx.liq_magnet_direction == "LONG" and side_mult < 0):
        liq_widen = 1.0 + ctx.liq_magnet_strength * 0.8
        trail_dist_mult *= liq_widen
        reasons.append(f"liq_ahead({liq_widen:.2f}x)")

    # EXTREME volatility = wider trail to avoid noise stop-outs
    if ctx.volatility_norm > 0.5:
        vol_widen = 1.0 + (ctx.volatility_norm - 0.5) * 1.0
        trail_dist_mult *= vol_widen
        reasons.append(f"high_vol({vol_widen:.2f}x)")

    # Momentum regime = much wider trail
    if ctx.is_momentum_regime:
        trail_dist_mult *= 1.5
        trail_act_mult *= 1.3
        min_lock_pct = max(20.0, min_lock_pct - 15)
        reasons.append("momentum(1.5x_trail)")

    # Spoof risk = tighten (can't trust the support levels)
    if ctx.spoof_risk > 0.5:
        trail_dist_mult *= max(0.6, 1.0 - ctx.spoof_risk * 0.4)
        reasons.append(f"spoof_tighten({ctx.spoof_risk:.2f})")

    # Clamp
    trail_dist_mult = max(0.4, min(3.5, trail_dist_mult))
    trail_act_mult = max(0.5, min(2.5, trail_act_mult))
    min_lock_pct = max(15.0, min(85.0, min_lock_pct))

    return {
        "trail_distance_mult": trail_dist_mult,
        "trail_activation_mult": trail_act_mult,
        "min_profit_lock_pct": min_lock_pct,
        "reason": " | ".join(reasons) if reasons else "neutral",
        "ctx": ctx,
    }


def get_adaptive_sl_params(redis_client, symbol: str, position_side: str) -> dict:
    """
    Get intelligence-driven stop-loss parameters.

    Returns dict with:
        sl_distance_mult: float — multiply base SL distance by this
        breakeven_activation_mult: float — multiply base BE activation by this
        profit_lock_pct: float — % of profit to lock at profit-lock level
        reason: str
    """
    ctx = get_market_context(redis_client, symbol, position_side=position_side)

    sl_mult = 1.0
    be_act_mult = 1.0
    profit_lock = 40.0
    reasons = []

    # High volatility = wider SL to avoid noise
    if ctx.volatility_norm > 0.3:
        vol_widen = 1.0 + (ctx.volatility_norm - 0.3) * 1.2
        sl_mult *= vol_widen
        be_act_mult *= 1.0 + (ctx.volatility_norm - 0.3) * 0.5
        reasons.append(f"vol_widen({vol_widen:.2f}x)")

    # Strong trend in our direction = wider SL (give room to breathe)
    side_mult = 1.0 if position_side.upper() == "LONG" else -1.0
    trend_favor = ctx.trend_score * side_mult
    if trend_favor > 0.3:
        trend_widen = 1.0 + trend_favor * 0.4
        sl_mult *= trend_widen
        reasons.append(f"trend_widen({trend_widen:.2f}x)")

    # Liq clusters NEAR us on our side = SL must clear them
    if position_side.upper() == "LONG" and ctx.liq_nearest_long_pct < 3.0:
        # Long liq cluster below us — our SL could trigger cascade
        sl_mult *= 1.3
        reasons.append(f"liq_near_our_side({ctx.liq_nearest_long_pct:.1f}%)")
    elif position_side.upper() == "SHORT" and ctx.liq_nearest_short_pct < 3.0:
        sl_mult *= 1.3
        reasons.append(f"liq_near_our_side({ctx.liq_nearest_short_pct:.1f}%)")

    # High reversal risk = tighter SL (protect capital)
    if ctx.reversal_risk > 0.5:
        sl_mult *= max(0.7, 1.0 - (ctx.reversal_risk - 0.5) * 0.4)
        profit_lock = min(70.0, profit_lock + (ctx.reversal_risk - 0.5) * 40)
        reasons.append(f"reversal_tighten({ctx.reversal_risk:.2f})")

    # Funding heavily against us = tighter SL (we're paying to hold)
    funding_against = ctx.funding_pressure * side_mult
    if funding_against > 0.5:
        sl_mult *= max(0.8, 1.0 - funding_against * 0.2)
        reasons.append(f"funding_against({funding_against:.2f})")

    # Spoof risk = can't trust depth for SL placement
    if ctx.spoof_risk > 0.4:
        sl_mult *= 1.15  # Wider to avoid fake walls
        reasons.append(f"spoof_widen({ctx.spoof_risk:.2f})")

    # Clamp
    sl_mult = max(0.5, min(2.5, sl_mult))
    be_act_mult = max(0.5, min(2.0, be_act_mult))
    profit_lock = max(20.0, min(80.0, profit_lock))

    return {
        "sl_distance_mult": sl_mult,
        "breakeven_activation_mult": be_act_mult,
        "profit_lock_pct": profit_lock,
        "reason": " | ".join(reasons) if reasons else "neutral",
        "ctx": ctx,
    }


def should_bypass_hedge_protection(
    redis_client,
    symbol: str,
    stop_side: str,
    stop_pnl: float,
) -> tuple:
    """
    Intelligence-driven decision: should we allow closing a losing hedge leg
    even though HEDGE-PROTECTION would normally block it?

    Returns: (should_bypass: bool, reason: str)
    """
    ctx = get_market_context(redis_client, symbol, position_side=stop_side)

    side_mult = 1.0 if stop_side.upper() == "LONG" else -1.0
    reasons = []
    score = 0.0

    # If trend is strongly AGAINST this leg, let it close (it'll only get worse)
    trend_against = -(ctx.trend_score * side_mult)
    if trend_against > 0.3:
        score += trend_against * 0.30
        reasons.append(f"trend_against({trend_against:.2f})")

    # Momentum against this leg
    mom_against = -(ctx.momentum_score * side_mult)
    if mom_against > 0.2:
        score += mom_against * 0.25
        reasons.append(f"momentum_against({mom_against:.2f})")

    # Liq clusters pulling price further against us
    if (ctx.liq_magnet_direction == "LONG" and stop_side.upper() == "LONG"):
        score += ctx.liq_magnet_strength * 0.20
        reasons.append(f"liq_hunting_us({ctx.liq_magnet_strength:.2f})")
    elif (ctx.liq_magnet_direction == "SHORT" and stop_side.upper() == "SHORT"):
        score += ctx.liq_magnet_strength * 0.20
        reasons.append(f"liq_hunting_us({ctx.liq_magnet_strength:.2f})")

    # Funding punishing us
    funding_penalty = ctx.funding_pressure * side_mult
    if funding_penalty > 0.3:
        score += 0.10
        reasons.append(f"funding_against({funding_penalty:.2f})")

    # Loss is deepening rapidly (high exit_score)
    if ctx.exit_score > 0.5:
        score += 0.15
        reasons.append(f"exit_urgency({ctx.exit_score:.2f})")

    should_bypass = score > 0.40
    reason = " | ".join(reasons) if reasons else "no_clear_signal"

    return should_bypass, reason


# ──────────────────────────────────────────────────────────────
# Post-unwind protection: cooldowns after selective unwind
# ──────────────────────────────────────────────────────────────

_UNWIND_COOLDOWN_SEC = 600  # 10 minutes: don't close remaining leg immediately


def set_selective_unwind_cooldown(redis_client, symbol: str, remaining_side: str):
    """
    After a selective unwind closes one leg, set a cooldown to protect
    the remaining leg from immediate CLOSE signals.

    This prevents the cascade: unhedge loser → trainer sends CLOSE → remaining leg closed at loss.
    """
    try:
        cooldown_key = f"wma:hedge_unwind_cooldown:{symbol}"
        protection_key = f"wma:hedge_unwind_protected:{symbol}"
        redis_client.setex(cooldown_key, _UNWIND_COOLDOWN_SEC, remaining_side)
        redis_client.setex(protection_key, _UNWIND_COOLDOWN_SEC, remaining_side)
        logger.info(
            "🛡️ UNWIND_PROTECTION_SET | sym=%s | remaining=%s | cooldown=%ds",
            symbol, remaining_side, _UNWIND_COOLDOWN_SEC,
        )
    except Exception as e:
        logger.warning("UNWIND_PROTECTION_SET_ERR | %s | %s", symbol, e)


def is_protected_after_unwind(redis_client, symbol: str, side: str) -> bool:
    """
    Check if a position side is protected after a selective unwind.
    Returns True if this side should NOT be closed by trainer signals right now.
    """
    try:
        protection_key = f"wma:hedge_unwind_protected:{symbol}"
        protected_side = redis_client.get(protection_key)
        if protected_side:
            ps = protected_side.decode() if isinstance(protected_side, bytes) else str(protected_side)
            return ps.upper() == side.upper()
    except Exception:
        pass
    return False


# ═══════════════════════════════════════════════════════════════
#  CROSS-SUBSYSTEM COORDINATION (Apr 2026)
#  Publish subsystem decisions to Redis so other subsystems can
#  detect conflicts and coordinate (e.g., TP engine shouldn't
#  widen when SL engine is tightening on the same symbol).
# ═══════════════════════════════════════════════════════════════

def publish_subsystem_state(
    redis_client,
    symbol: str,
    subsystem: str,
    decision: str,
    details: dict = None,
    ttl_sec: int = 30,
):
    """
    Publish a subsystem's latest decision to Redis for cross-subsystem awareness.

    Key: wma:subsys:{symbol}:{subsystem}
    Fields: decision, ts_ms, details (JSON)

    Subsystems: stealth_stops, dynamic_tp, adaptive_thresholds, icg
    Decisions: TIGHTEN, WIDEN, DEFER, ALLOW, TRAIL, HOLD, KILL
    """
    try:
        import json as _j
        key = f"wma:subsys:{symbol}:{subsystem}"
        payload = {
            "decision": str(decision),
            "ts_ms": str(int(time.time() * 1000)),
            "details": _j.dumps(details or {}, separators=(",", ":")),
        }
        redis_client.hset(key, mapping=payload)
        redis_client.expire(key, ttl_sec)
    except Exception:
        pass


def get_subsystem_state(redis_client, symbol: str, subsystem: str) -> dict:
    """
    Read another subsystem's latest decision.
    Returns dict with 'decision', 'ts_ms', 'details' or empty dict if unavailable/stale.
    """
    try:
        import json as _j
        key = f"wma:subsys:{symbol}:{subsystem}"
        raw = redis_client.hgetall(key)
        if not raw:
            return {}
        out = {}
        for k, v in raw.items():
            kk = k.decode() if isinstance(k, bytes) else str(k)
            vv = v.decode() if isinstance(v, bytes) else str(v)
            out[kk] = vv
        # Check freshness (30s max)
        ts_ms = int(out.get("ts_ms", 0) or 0)
        if ts_ms > 0 and (time.time() * 1000 - ts_ms) > 35_000:
            return {}  # Stale
        if "details" in out:
            try:
                out["details"] = _j.loads(out["details"])
            except Exception:
                out["details"] = {}
        return out
    except Exception:
        return {}


def check_subsystem_conflict(
    redis_client,
    symbol: str,
    my_subsystem: str,
    my_decision: str,
) -> tuple:
    """
    Check if other subsystems have conflicting decisions for this symbol.

    Returns: (has_conflict: bool, conflicting_subsystem: str, their_decision: str)

    Conflict examples:
    - TP engine wants WIDEN but SL engine says TIGHTEN → conflict
    - ICG says DEFER but stealth wants ALLOW → conflict
    """
    _opposing = {
        "WIDEN": {"TIGHTEN", "KILL"},
        "TIGHTEN": {"WIDEN"},
        "ALLOW": {"DEFER", "HOLD"},
        "DEFER": {"ALLOW", "KILL"},
        "HOLD": {"ALLOW", "KILL"},
        "KILL": {"WIDEN", "HOLD", "DEFER"},
    }
    try:
        _others = ["stealth_stops", "dynamic_tp", "adaptive_thresholds", "icg"]
        _my_conflicts = _opposing.get(my_decision.upper(), set())
        for sub in _others:
            if sub == my_subsystem:
                continue
            state = get_subsystem_state(redis_client, symbol, sub)
            if not state:
                continue
            their = state.get("decision", "").upper()
            if their in _my_conflicts:
                return True, sub, their
    except Exception:
        pass
    return False, "", ""
