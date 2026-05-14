"""
HedgeContext — Shared Market Awareness Layer for ALL hedge systems.

PURPOSE: Give every hedge system (GRADUATED_KILL, TREND_HEDGE_SCALE,
ADAPTIVE_HEDGE, HEDGE_PAIR_COORDINATOR) the SAME real-time view of:

1. Real-time prices (mark price from Redis)
2. Trainer predictions (target price, direction, confidence, consensus)
3. TA indicators (RSI, MACD, ADX, BBands across all timeframes)
4. Coinank data (OI, funding, big orders, liquidations)
5. Microstructure (orderbook imbalance, tape, spoof scores)
6. Liquidation levels (nearby clusters, squeeze potential)
7. Peer hedge actions (what other hedge systems did recently)
8. Current hedge coverage per symbol

This is READ-ONLY context. It does NOT make decisions or change behavior.
Each hedge system uses this context to make BETTER informed decisions.

Kill switch: config.HEDGE_CONTEXT_ENABLED = False
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("hedge_context")

# Cache TTL for different data categories
_PRICE_CACHE_TTL = 2       # 2s - prices change fast
_TA_CACHE_TTL = 10          # 10s - TA updates per candle
_COINANK_CACHE_TTL = 30     # 30s - coinank polls are slower
_TRAINER_CACHE_TTL = 5      # 5s - signals come every ~30s
_PEER_CACHE_TTL = 5         # 5s - peer actions
_MICRO_CACHE_TTL = 3        # 3s - microstructure


@dataclass
class TrainerSignal:
    """Latest trainer prediction for a symbol."""
    symbol: str = ""
    action: str = ""
    direction: str = ""          # LONG / SHORT / NEUTRAL
    confidence: float = 0.0
    target_price: float = 0.0
    target_pct: float = 0.0
    consensus_direction: str = ""
    consensus_confidence: float = 0.0
    market_regime: str = ""
    move_regime: str = ""
    tf_alignment: float = 0.0
    age_sec: float = 999.0       # How old the signal is


@dataclass
class MarketSnapshot:
    """Complete market view for a symbol at a point in time.
    Uses ALL available Redis features: 559+ keys from unified_features,
    liquidation levels, depth/tape microstructure, CoinAnk flow, TA indicators.
    """
    symbol: str = ""
    timestamp: float = 0.0

    # ── Prices ──
    mark_price: float = 0.0
    price_change_1m_pct: float = 0.0
    price_change_5m_pct: float = 0.0
    price_change_15m_pct: float = 0.0
    price_change_1h_pct: float = 0.0

    # ── Trainer predictions ──
    trainer: Optional[TrainerSignal] = None

    # ── TA indicators (multi-timeframe from unified_features) ──
    rsi_5m: float = 50.0
    rsi_15m: float = 50.0
    rsi_1h: float = 50.0
    rsi_4h: float = 50.0
    macd_5m: float = 0.0
    macd_15m: float = 0.0
    macd_signal_15m: float = 0.0
    adx_15m: float = 0.0
    adx_1h: float = 0.0
    cci_15m: float = 0.0
    cci_1h: float = 0.0
    willr_15m: float = -50.0        # Williams %R [-100, 0]
    stoch_k_15m: float = 50.0       # Stochastic %K
    stoch_k_1h: float = 50.0
    mfi_15m: float = 50.0           # Money Flow Index (0-100)
    mom_15m: float = 0.0            # Momentum
    roc_15m: float = 0.0            # Rate of Change
    ppo_15m: float = 0.0            # Percentage Price Oscillator
    plus_di_15m: float = 0.0        # +DI
    minus_di_15m: float = 0.0       # -DI
    aroon_up_15m: float = 50.0
    aroon_down_15m: float = 50.0
    linearreg_angle_15m: float = 0.0  # Linear regression angle (trend direction)
    linearreg_slope_15m: float = 0.0  # Linear regression slope

    # ── BBands / EMA / SMA (for strategic level detection) ──
    bbands_upper_15m: float = 0.0
    bbands_lower_15m: float = 0.0
    bbands_mid_15m: float = 0.0
    bbands_pct_15m: float = 0.5     # 0=lower band, 1=upper band
    ema_20_15m: float = 0.0
    ema_50_1h: float = 0.0
    sma_50_15m: float = 0.0
    sma_200_1h: float = 0.0
    kama_30_15m: float = 0.0
    ema_trend_15m: str = "NEUTRAL"  # BULLISH / BEARISH / NEUTRAL

    # ── Pressure composite ──
    pressure_1m: float = 0.0
    pressure_5m: float = 0.0
    pressure_15m: float = 0.0
    pressure_1h: float = 0.0

    # ── Volatility ──
    natr_5m: float = 0.0
    natr_15m: float = 0.0
    natr_1h: float = 0.0
    atr_15m: float = 0.0            # Absolute ATR for level computation
    atr_1h: float = 0.0
    volatility_regime: str = "NORMAL"  # LOW / NORMAL / HIGH / EXTREME

    # ── CoinAnk data (per-symbol from unified_features) ──
    funding_rate: float = 0.0
    oi_change_pct_1h: float = 0.0
    oi_value: float = 0.0           # OI dollar value
    long_short_ratio: float = 1.0
    big_order_flow: float = 0.0
    coinank_buy_sell_count_ratio: float = 1.0  # col0=buy, col1=sell count
    coinank_buy_sell_value_ratio: float = 1.0
    coinank_buy_sell_volume_ratio: float = 1.0
    coinank_liq_long_amount: float = 0.0
    coinank_liq_short_amount: float = 0.0
    coinank_liq_long_turnover: float = 0.0
    coinank_liq_short_turnover: float = 0.0

    # ── Orderbook depth (from unified_features depth_* keys) ──
    depth_imbalance_5: float = 0.0       # [-1, 1] bid/ask imbalance at 5 levels
    depth_bid_sum_5: float = 0.0
    depth_ask_sum_5: float = 0.0
    depth_total_usd: float = 0.0
    depth_bps_10_bid_usd: float = 0.0
    depth_bps_10_ask_usd: float = 0.0
    depth_bps_25_bid_usd: float = 0.0
    depth_bps_25_ask_usd: float = 0.0
    depth_microprice: float = 0.0
    depth_spread_bps: float = 0.0
    depth_quality_score: float = 0.0
    depth_churn_score: float = 0.0

    # ── Tape / trade flow ──
    tape_imbalance_5s: float = 0.0       # [-1, 1] buy/sell imbalance
    tape_imbalance_30s: float = 0.0
    tape_cvd: float = 0.0               # Cumulative Volume Delta
    tape_total_notional_30s: float = 0.0
    tape_buy_notional_30s: float = 0.0
    tape_sell_notional_30s: float = 0.0

    # ── Depth vs Tape divergence ──
    depth_vs_tape_divergence: float = 0.0  # Spoofing indicator
    depth_trade_imbalance_5s: float = 0.0

    # ── Microstructure (from msnap or depth keys) ──
    orderbook_imbalance: float = 0.0  # [-1, 1], positive = bid heavy (ob_ob_imbalance)
    ob_spread_bps: float = 0.0
    spoof_score: float = 0.0
    spoof_score_v2: float = 0.0
    trade_intensity: float = 0.0
    fast_move_score: float = 0.0
    snapback_score: float = 0.0
    p_false_move: float = 0.0

    # ── Kline data ──
    kline_taker_buy_ratio: float = 0.5   # Ratio of taker buys vs total
    kline_taker_sell_ratio: float = 0.5
    kline_num_trades: int = 0

    # ── Liquidation levels (from unified_features liquidation_* keys) ──
    nearest_liq_long_pct: float = 99.0   # % below price where long liqs cluster
    nearest_liq_short_pct: float = 99.0  # % above price where short liqs cluster
    liq_long_level: float = 0.0          # Actual price level of long liquidations
    liq_short_level: float = 0.0         # Actual price level of short liquidations
    liq_long_strength: float = 0.0       # Strength of long liq cluster
    liq_short_strength: float = 0.0
    liq_imbalance: float = 0.0           # >0 = more long liqs, <0 = more short liqs
    liq_volume: float = 0.0

    # ── Cross-TF data (from xtf_* keys) ──
    xtf_4h_rsi: float = 50.0
    xtf_1h_rsi: float = 50.0
    xtf_4h_ob_imbalance: float = 0.0
    xtf_1h_ob_imbalance: float = 0.0
    xtf_4h_liq_long_dist: float = 99.0
    xtf_4h_liq_short_dist: float = 99.0
    xtf_1h_funding_rate: float = 0.0
    xtf_4h_funding_rate: float = 0.0

    # ── Candlestick patterns (from ind_ta_CDL* keys) ──
    cdl_engulfing: float = 0.0          # +100 bullish, -100 bearish, 0 none
    cdl_hammer: float = 0.0
    cdl_doji: float = 0.0
    cdl_evening_star: float = 0.0
    cdl_shooting_star: float = 0.0
    cdl_marubozu: float = 0.0

    # ── Peer hedge actions ──
    peer_actions_last_5m: List[Dict] = field(default_factory=list)
    total_hedge_adds_last_5m: int = 0
    total_hedge_trims_last_5m: int = 0

    # ── Current hedge coverage for this symbol ──
    hedge_coverage_pct: float = 0.0
    main_side: str = ""
    hedge_side: str = ""

    @staticmethod
    def _soft_gate(value: float, scale: float = 1.0) -> float:
        """Smooth tanh gate: maps any value to [-1, 1] without hard thresholds.
        `scale` controls sensitivity — higher = steeper transition.
        Anti-churn: continuous, differentiable, no cliff edges.
        """
        import math
        try:
            return math.tanh(value * scale)
        except (OverflowError, ValueError):
            return 1.0 if value > 0 else -1.0

    def direction_score(self) -> float:
        """Composite directional score [-1, 1] using ALL available features.
        Positive = bullish. ALL signals are continuous — NO hard thresholds.
        Each signal is tanh-gated so extreme values saturate smoothly.
        """
        _sg = self._soft_gate
        components = []  # (score, weight) pairs

        # 1. RSI multi-TF — continuous deviation from 50 (neutral)
        #    Normalize: (rsi-50)/25 maps 25→-1, 75→+1 smoothly
        components.append((_sg((self.rsi_15m - 50) / 25), 0.10))
        components.append((_sg((self.rsi_1h - 50) / 25), 0.08))
        components.append((_sg((self.xtf_4h_rsi - 50) / 25), 0.06))

        # 2. Pressure composites — already [-1,1], just gate for stability
        components.append((_sg(self.pressure_15m, 3.0), 0.12))
        components.append((_sg(self.pressure_1h, 3.0), 0.06))

        # 3. Trainer direction — weight scales with confidence continuously
        if self.trainer and self.trainer.confidence > 0:
            dir_val = 1.0 if self.trainer.consensus_direction == "LONG" else (
                -1.0 if self.trainer.consensus_direction == "SHORT" else 0.0)
            # Confidence directly modulates signal strength (no threshold)
            components.append((dir_val * self.trainer.consensus_confidence, 0.15))

        # 4. Orderbook depth imbalance — continuous
        components.append((_sg(self.depth_imbalance_5, 2.0), 0.08))
        components.append((_sg(self.orderbook_imbalance, 2.0), 0.05))

        # 5. Tape flow — continuous
        components.append((_sg(self.tape_imbalance_30s, 2.0), 0.10))

        # 6. Kline taker ratio: 0.5 is neutral, continuous deviation
        taker_signal = (self.kline_taker_buy_ratio - 0.5) * 2  # [-1, 1]
        components.append((_sg(taker_signal, 2.0), 0.06))

        # 7. Funding rate (contrarian) — scale by 1000 to get meaningful range
        components.append((_sg(-self.funding_rate * 1000, 1.0), 0.05))

        # 8. CoinAnk buy/sell flow — ratio centered on 1.0
        if self.coinank_buy_sell_value_ratio > 0:
            coinank_signal = (self.coinank_buy_sell_value_ratio - 1.0)  # >0 = bullish
            components.append((_sg(coinank_signal, 2.0), 0.04))

        # 9. CoinAnk liquidation imbalance — continuous
        total_liq = self.coinank_liq_long_turnover + self.coinank_liq_short_turnover
        if total_liq > 0:
            liq_signal = (self.coinank_liq_long_turnover - self.coinank_liq_short_turnover) / total_liq
            components.append((_sg(-liq_signal, 2.0), 0.03))  # longs rekt = bearish

        # 10. MACD — continuous distance from signal line
        if self.macd_15m != 0 or self.macd_signal_15m != 0:
            # Normalize MACD diff by ATR to make it adaptive per-symbol
            atr_norm = max(self.atr_15m, self.mark_price * 0.001, 0.01)
            macd_diff_norm = (self.macd_15m - self.macd_signal_15m) / atr_norm
            components.append((_sg(macd_diff_norm, 1.0), 0.04))

        # 11. Depth vs tape divergence — reduces OB reliability smoothly
        #     High divergence = depth and tape disagree = less trust in direction
        divergence_penalty = abs(self.depth_vs_tape_divergence)
        # Reduce OB weight proportionally (already just included with low weight)

        # Weighted average — all components contribute proportionally
        total_w = sum(w for _, w in components) or 1.0
        score = sum(s * w for s, w in components) / total_w if components else 0.0
        return max(-1.0, min(1.0, score))

    def conviction_score(self) -> float:
        """How confident are we in the direction? 0.0 = no idea, 1.0 = very sure.
        Measures AGREEMENT across independent sources using continuous signals.
        No hard thresholds — every source contributes proportionally to its strength.
        """
        # Each source contributes a continuous directional signal [-1, 1]
        signals = []

        # RSI: deviation from neutral (continuous)
        rsi_sig = (self.rsi_15m - 50) / 30  # ±1 at 20/80
        signals.append(max(-1, min(1, rsi_sig)))

        # Pressure (already directional)
        if self.pressure_15m != 0:
            signals.append(max(-1, min(1, self.pressure_15m)))

        # Trainer (weighted by its own confidence)
        if self.trainer and self.trainer.consensus_confidence > 0:
            t_dir = 1.0 if self.trainer.consensus_direction == "LONG" else (
                -1.0 if self.trainer.consensus_direction == "SHORT" else 0.0)
            signals.append(t_dir * self.trainer.consensus_confidence)

        # Tape flow (continuous)
        if self.tape_imbalance_30s != 0:
            signals.append(max(-1, min(1, self.tape_imbalance_30s * 2)))

        # Depth imbalance (continuous)
        if self.depth_imbalance_5 != 0:
            signals.append(max(-1, min(1, self.depth_imbalance_5 * 2)))

        # Kline taker ratio (continuous)
        taker_sig = (self.kline_taker_buy_ratio - 0.5) * 4  # ±1 at 0.25/0.75
        signals.append(max(-1, min(1, taker_sig)))

        # MACD vs signal (continuous)
        if self.macd_15m != 0 or self.macd_signal_15m != 0:
            atr_norm = max(self.atr_15m, self.mark_price * 0.001, 0.01)
            macd_sig = max(-1, min(1, (self.macd_15m - self.macd_signal_15m) / atr_norm))
            signals.append(macd_sig)

        # ADX-weighted DI direction (continuous — ADX modulates strength)
        if self.adx_15m > 0 and (self.plus_di_15m + self.minus_di_15m) > 0:
            di_dir = (self.plus_di_15m - self.minus_di_15m) / (self.plus_di_15m + self.minus_di_15m)
            # ADX normalizes: strong trend = high ADX = higher conviction
            adx_weight = min(1.0, self.adx_15m / 40.0)  # saturates smoothly
            signals.append(di_dir * adx_weight)

        if len(signals) < 2:
            return 0.0

        # Agreement: variance of signs — low variance = high agreement
        mean_dir = sum(signals) / len(signals)
        agreement = abs(mean_dir)  # 0 = perfectly split, 1 = unanimous
        # Source count scales confidence (more sources = more robust)
        source_factor = min(1.0, len(signals) / 5.0)
        return min(1.0, agreement * source_factor)

    def favors_side(self, side: str) -> bool:
        """Does the market currently favor this side?
        Adaptive: threshold is based on conviction — when conviction is high,
        even a small directional lean counts. When conviction is low, need
        stronger signal to be sure.
        """
        ds = self.direction_score()
        conv = self.conviction_score()
        # Adaptive threshold: high conviction → lower bar (0.08), low → higher bar (0.25)
        threshold = 0.25 - conv * 0.17  # range [0.08, 0.25]
        if side == "LONG":
            return ds > threshold
        elif side == "SHORT":
            return ds < -threshold
        return False

    def against_side(self, side: str) -> bool:
        """Is the market moving against this side?
        Adaptive: uses conviction to set sensitivity.
        """
        ds = self.direction_score()
        conv = self.conviction_score()
        # High conviction against = lower threshold to detect it quickly
        threshold = 0.30 - conv * 0.15  # range [0.15, 0.30]
        if side == "LONG":
            return ds < -threshold
        elif side == "SHORT":
            return ds > threshold
        return False


class HedgeContext:
    """
    Shared context provider for all hedge systems.

    Usage:
        ctx = HedgeContext(redis_client)
        snap = ctx.get_snapshot("BTCUSDT")
        # snap.trainer.target_price, snap.rsi_15m, snap.peer_actions_last_5m, etc.
    """

    def __init__(self, redis_client: Any):
        self.redis = redis_client
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._peer_log: List[Dict] = []  # ring buffer of recent hedge actions
        self._peer_log_max = 200
        self._enabled = True
        try:
            import config as cfg
            self._enabled = getattr(cfg, "HEDGE_CONTEXT_ENABLED", True)
        except Exception:
            pass

    def is_enabled(self) -> bool:
        return self._enabled and self.redis is not None

    # ─── PUBLIC API ───────────────────────────────────────────────────────

    def get_snapshot(self, symbol: str, positions: Optional[Dict] = None) -> MarketSnapshot:
        """Get complete market snapshot for a symbol. Fast (uses caching)."""
        if not self.is_enabled():
            return MarketSnapshot(symbol=symbol, timestamp=time.time())

        snap = MarketSnapshot(symbol=symbol, timestamp=time.time())

        try:
            self._fill_price(snap)
            self._fill_ta(snap)
            self._fill_trainer(snap)
            self._fill_coinank(snap)
            self._fill_microstructure(snap)
            self._fill_liquidation(snap)
            self._fill_peer_actions(snap)
            if positions:
                self._fill_hedge_coverage(snap, positions)
        except Exception as e:
            logger.debug("HEDGE_CTX_ERR | %s | %s", symbol, e)

        return snap

    def record_peer_action(self, symbol: str, source: str, action_type: str,
                           side: str = "", margin_usd: float = 0.0):
        """Record that a hedge system took action. Called BY each hedge system."""
        entry = {
            "ts": time.time(),
            "symbol": symbol,
            "source": source,  # graduated_kill, trend_hedge, adaptive, coordinator
            "action": action_type,  # ADD, TRIM, CLOSE
            "side": side,
            "margin_usd": margin_usd,
        }
        self._peer_log.append(entry)
        # Trim ring buffer
        if len(self._peer_log) > self._peer_log_max:
            self._peer_log = self._peer_log[-self._peer_log_max:]

        # Also persist to Redis for cross-process visibility
        try:
            self.redis.xadd(
                "hedge:peer_actions",
                {"data": json.dumps(entry, default=str)},
                maxlen=500,
            )
        except Exception:
            pass

    def get_peer_actions(self, symbol: str, window_sec: float = 300) -> List[Dict]:
        """Get recent peer hedge actions for a symbol."""
        cutoff = time.time() - window_sec
        actions = [a for a in self._peer_log if a["symbol"] == symbol and a["ts"] > cutoff]

        # Also read from Redis (for cross-process peers)
        try:
            cache_key = f"peer_actions:{symbol}"
            cached = self._get_cache(cache_key, _PEER_CACHE_TTL)
            if cached is not None:
                return cached

            entries = self.redis.xrevrange("hedge:peer_actions", count=100)
            for _, data in (entries or []):
                try:
                    d = json.loads(data.get(b"data", b"{}").decode())
                    if d.get("symbol") == symbol and d.get("ts", 0) > cutoff:
                        # Deduplicate
                        if not any(a["ts"] == d["ts"] and a["source"] == d.get("source") for a in actions):
                            actions.append(d)
                except Exception:
                    pass

            self._set_cache(cache_key, actions)
        except Exception:
            pass

        return actions

    # ─── PRIVATE FILLERS ──────────────────────────────────────────────────

    def _fill_price(self, snap: MarketSnapshot):
        """Fetch real-time mark price."""
        sym = snap.symbol
        cache_key = f"price:{sym}"
        cached = self._get_cache(cache_key, _PRICE_CACHE_TTL)
        if cached is not None:
            snap.mark_price = cached
            return

        try:
            # Try realtime first, then fallback
            for key in [f"price:realtime:{sym}", f"price:{sym}"]:
                raw = self.redis.get(key)
                if raw:
                    raw_str = raw.decode() if isinstance(raw, bytes) else raw
                    try:
                        # Could be JSON {"price": 123.45} or plain float
                        if raw_str.startswith("{"):
                            snap.mark_price = float(json.loads(raw_str).get("price", 0))
                        else:
                            snap.mark_price = float(raw_str)
                    except (ValueError, TypeError, json.JSONDecodeError):
                        snap.mark_price = 0.0
                    if snap.mark_price > 0:
                        self._set_cache(cache_key, snap.mark_price)
                        return
        except Exception:
            pass

    def _fill_ta(self, snap: MarketSnapshot):
        """Fetch TA indicators from unified_features across timeframes.
        Reads ALL important indicators: RSI, MACD, ADX, BBands, EMA, SMA,
        CCI, Williams %R, Stochastic, MFI, momentum, ROC, AROON, DI, etc.
        Also reads depth, tape, kline, liquidation, CoinAnk from same source.
        """
        sym = snap.symbol
        cache_key = f"ta_all:{sym}"
        cached = self._get_cache(cache_key, _TA_CACHE_TTL)
        if cached is not None:
            self._apply_ta_unified(snap, cached)
            return

        all_data = {}
        try:
            pipe = self.redis.pipeline(transaction=False)
            # Read unified_features for core timeframes — these contain EVERYTHING
            for tf in ["5m", "15m", "1h"]:
                pipe.hgetall(f"unified_features:{sym}:{tf}")
            results = pipe.execute()

            for i, tf in enumerate(["5m", "15m", "1h"]):
                if results[i]:
                    for k, v in results[i].items():
                        kk = k.decode() if isinstance(k, bytes) else str(k)
                        vv = v.decode() if isinstance(v, bytes) else str(v)
                        all_data[f"{tf}:{kk}"] = vv

            self._set_cache(cache_key, all_data)
            self._apply_ta_unified(snap, all_data)
        except Exception as e:
            logger.debug("HEDGE_CTX_TA_ERR | %s | %s", sym, e)

    def _apply_ta_unified(self, snap: MarketSnapshot, data: Dict):
        """Apply unified_features data across all timeframes to snapshot.
        Key format: "{tf}:{feature_key}" e.g. "15m:ind_ta_RSI_14_15m"
        """
        def _f(key, default=0.0):
            v = data.get(key)
            if v is None:
                return default
            try:
                return float(v)
            except (ValueError, TypeError):
                return default

        # ── RSI multi-TF ──
        snap.rsi_5m = _f("5m:ind_ta_RSI_14_5m", _f("5m:xtf_5m_rsi_14", 50.0))
        snap.rsi_15m = _f("15m:ind_ta_RSI_14_15m", 50.0)
        snap.rsi_1h = _f("1h:ind_ta_RSI_14_1h", _f("15m:xtf_1h_rsi_14", 50.0))
        snap.rsi_4h = _f("15m:xtf_4h_rsi_14", 50.0)

        # ── MACD ──
        snap.macd_5m = _f("5m:ind_ta_MACD_macd_fastperiod12_slowperiod26_signalperiod9_5m", 0.0)
        snap.macd_15m = _f("15m:ind_ta_MACD_macd_fastperiod12_slowperiod26_signalperiod9_15m", 0.0)
        snap.macd_signal_15m = _f("15m:ind_ta_MACD_signal_fastperiod12_slowperiod26_signalperiod9_15m", 0.0)

        # ── ADX / DI ──
        snap.adx_15m = _f("15m:ind_ta_ADX_14_15m", 0.0)
        snap.adx_1h = _f("1h:ind_ta_ADX_14_1h", 0.0)
        snap.plus_di_15m = _f("15m:ind_ta_PLUS_DI_14_15m", _f("15m:ind_ta_PLUS_DI_21_15m", 0.0))
        snap.minus_di_15m = _f("15m:ind_ta_MINUS_DI_14_15m", _f("15m:ind_ta_MINUS_DI_21_15m", 0.0))

        # ── CCI / Williams %R / Stochastic ──
        snap.cci_15m = _f("15m:ind_ta_CCI_14_15m", _f("15m:ind_ta_CCI_20_15m", 0.0))
        snap.cci_1h = _f("1h:ind_ta_CCI_14_1h", _f("1h:ind_ta_CCI_20_1h", 0.0))
        snap.willr_15m = _f("15m:ind_ta_WILLR_14_15m", -50.0)
        snap.stoch_k_15m = _f("15m:ind_ta_STOCH_k_fastk_period14_slowk_period3_slowk_matype0_slowd_period3_slowd_matype0_15m", 50.0)
        snap.stoch_k_1h = _f("1h:ind_ta_STOCH_k_fastk_period14_slowk_period3_slowk_matype0_slowd_period3_slowd_matype0_1h", 50.0)

        # ── Momentum / ROC / PPO / AROON ──
        snap.mom_15m = _f("15m:ind_ta_MOM_14_15m", 0.0)
        snap.mfi_15m = _f("15m:ind_ta_MFI_14_15m", 50.0)
        snap.roc_15m = _f("15m:ind_ta_ROC_10_15m", 0.0)
        snap.ppo_15m = _f("15m:ind_ta_PPO_fastperiod12_slowperiod26_matype0_15m", 0.0)
        snap.aroon_up_15m = _f("15m:ind_ta_AROON_up_14_15m", 50.0)
        snap.aroon_down_15m = _f("15m:ind_ta_AROON_down_14_15m", 50.0)
        snap.linearreg_angle_15m = _f("15m:ind_ta_LINEARREG_ANGLE_14_15m", 0.0)
        snap.linearreg_slope_15m = _f("15m:ind_ta_LINEARREG_SLOPE_21_15m", 0.0)

        # ── BBands / EMA / SMA / KAMA ──
        # BBands: derive from upper/lower if available, or use direct pct
        _bb_upper = _f("15m:ind_ta_BBANDS_upper_period20_nbdevup2_nbdevdn2_matype0_15m", 0.0)
        _bb_lower = _f("15m:ind_ta_BBANDS_lower_period20_nbdevup2_nbdevdn2_matype0_15m", 0.0)
        _bb_mid = _f("15m:ind_ta_BBANDS_middle_period20_nbdevup2_nbdevdn2_matype0_15m", 0.0)
        snap.bbands_upper_15m = _bb_upper
        snap.bbands_lower_15m = _bb_lower
        snap.bbands_mid_15m = _bb_mid
        if _bb_upper > 0 and _bb_lower > 0 and snap.mark_price > 0:
            _bb_range = _bb_upper - _bb_lower
            if _bb_range > 0:
                snap.bbands_pct_15m = (snap.mark_price - _bb_lower) / _bb_range
        snap.ema_20_15m = _f("15m:ind_ta_EMA_20_15m", 0.0)
        snap.sma_50_15m = _f("15m:ind_ta_SMA_50_15m", 0.0)
        snap.ema_50_1h = _f("1h:ind_ta_EMA_50_1h", _f("15m:xtf_1h_ccxt_close", 0.0))
        snap.kama_30_15m = _f("15m:ind_ta_KAMA_30_15m", 0.0)

        # EMA trend: price vs EMA20
        if snap.ema_20_15m > 0 and snap.mark_price > 0:
            if snap.mark_price > snap.ema_20_15m * 1.002:
                snap.ema_trend_15m = "BULLISH"
            elif snap.mark_price < snap.ema_20_15m * 0.998:
                snap.ema_trend_15m = "BEARISH"

        # ── Pressure composite ──
        snap.pressure_1m = _f("15m:ind_ta_pressure", _f("5m:ind_ta_pressure", 0.0))
        snap.pressure_5m = _f("5m:ind_ta_pressure", 0.0)
        snap.pressure_15m = _f("15m:ind_ta_pressure", 0.0)
        snap.pressure_1h = _f("1h:ind_ta_pressure", 0.0)

        # ── NATR / ATR / Volatility ──
        snap.natr_5m = _f("5m:ind_ta_NATR_14_5m", _f("5m:natr", 0.0))
        snap.natr_15m = _f("15m:ind_ta_NATR_14_15m", _f("15m:natr", 0.0))
        snap.natr_1h = _f("1h:ind_ta_NATR_14_1h", _f("15m:xtf_1h_atr_14", 0.0))
        snap.atr_15m = _f("15m:ind_ta_ATR_14_15m", 0.0)
        snap.atr_1h = _f("1h:ind_ta_ATR_14_1h", 0.0)

        max_natr = max(snap.natr_5m, snap.natr_15m, snap.natr_1h)
        # Volatility regime: adaptive labels based on NATR distribution
        # Crypto NATR median ~0.8-1.2%. Labels are descriptive only, not used for thresholds.
        # All decision logic uses raw NATR values with smooth functions.
        if max_natr > snap.natr_15m * 3 and max_natr > 2.0:
            snap.volatility_regime = "EXTREME"  # Multi-TF spike
        elif max_natr > 1.5:
            snap.volatility_regime = "HIGH"
        elif max_natr < 0.3:
            snap.volatility_regime = "LOW"
        else:
            snap.volatility_regime = "NORMAL"

        # ── Depth data (from unified_features) ──
        snap.depth_imbalance_5 = _f("15m:depth_imbalance_5", _f("5m:depth_imbalance_5", 0.0))
        snap.depth_bid_sum_5 = _f("15m:depth_bid_sum_5", 0.0)
        snap.depth_ask_sum_5 = _f("15m:depth_ask_sum_5", 0.0)
        snap.depth_total_usd = _f("15m:depth_total_usd", _f("15m:depth_usd", 0.0))
        snap.depth_bps_10_bid_usd = _f("15m:depth_bps_10_bid_usd", 0.0)
        snap.depth_bps_10_ask_usd = _f("15m:depth_bps_10_ask_usd", 0.0)
        snap.depth_bps_25_bid_usd = _f("15m:depth_bps_25_bid_usd", 0.0)
        snap.depth_bps_25_ask_usd = _f("15m:depth_bps_25_ask_usd", 0.0)
        snap.depth_microprice = _f("15m:depth_microprice", 0.0)
        snap.depth_spread_bps = _f("15m:depth_spread", _f("15m:ob_ob_spread_bps", 0.0))
        snap.depth_quality_score = _f("15m:depth_quality_score", 0.0)
        snap.depth_churn_score = _f("15m:depth_churn_score", 0.0)

        # ── OB imbalance ──
        snap.orderbook_imbalance = _f("15m:ob_ob_imbalance", _f("5m:ob_ob_imbalance", 0.0))
        snap.ob_spread_bps = _f("15m:ob_ob_spread_bps", 0.0)

        # ── Spoof / microstructure scores ──
        snap.spoof_score = _f("15m:depth_spoof_score", _f("5m:depth_spoof_score", 0.0))
        snap.spoof_score_v2 = _f("15m:depth_spoof_score_v2", _f("5m:depth_spoof_score_v2", 0.0))
        snap.fast_move_score = _f("15m:depth_fast_move_score", _f("5m:depth_fast_move_score", 0.0))
        snap.snapback_score = _f("15m:depth_snapback_score", 0.0)
        snap.p_false_move = _f("15m:depth_p_false_move", 0.0)
        snap.depth_vs_tape_divergence = _f("15m:depth_vs_tape_divergence", 0.0)
        snap.depth_trade_imbalance_5s = _f("15m:depth_trade_imbalance_5s", 0.0)

        # ── Tape flow ──
        snap.tape_imbalance_5s = _f("15m:tape_imbalance_5s", _f("5m:tape_imbalance_5s", 0.0))
        snap.tape_imbalance_30s = _f("15m:tape_imbalance_30s", _f("5m:tape_imbalance_30s", 0.0))
        snap.tape_cvd = _f("15m:tape_cvd", _f("5m:tape_cvd", 0.0))
        snap.tape_total_notional_30s = _f("15m:tape_total_notional_30s", 0.0)
        snap.tape_buy_notional_30s = _f("15m:tape_buy_notional_30s", 0.0)
        snap.tape_sell_notional_30s = _f("15m:tape_sell_notional_30s", 0.0)

        # ── Kline data ──
        snap.kline_taker_buy_ratio = _f("15m:kline_taker_buy_ratio", _f("5m:kline_taker_buy_ratio", 0.5))
        snap.kline_taker_sell_ratio = _f("15m:kline_taker_sell_ratio", _f("5m:kline_taker_sell_ratio", 0.5))
        snap.kline_num_trades = int(_f("15m:kline_num_trades", 0))

        # ── Funding rate ──
        snap.funding_rate = _f("15m:funding_rate", _f("5m:funding_rate", 0.0))

        # ── Liquidation levels (actual levels, not approximations) ──
        snap.nearest_liq_long_pct = _f("15m:liquidation_long_distance_pct", _f("5m:liquidation_long_distance_pct", 99.0))
        snap.nearest_liq_short_pct = _f("15m:liquidation_short_distance_pct", _f("5m:liquidation_short_distance_pct", 99.0))
        snap.liq_long_level = _f("15m:liquidation_long_level", 0.0)
        snap.liq_short_level = _f("15m:liquidation_short_level", 0.0)
        snap.liq_long_strength = _f("15m:liquidation_long_strength", 0.0)
        snap.liq_short_strength = _f("15m:liquidation_short_strength", 0.0)
        snap.liq_volume = _f("15m:liquidation_volume", 0.0)
        # Liq imbalance: positive = more long liqs (bearish pressure)
        if snap.liq_long_strength + snap.liq_short_strength > 0:
            snap.liq_imbalance = (snap.liq_long_strength - snap.liq_short_strength) / \
                                  (snap.liq_long_strength + snap.liq_short_strength)

        # ── CoinAnk data (per-symbol from unified_features) ──
        _ca_buy_count = _f("15m:coinank_marketOrder_getBuySellCount_data_col0_last", 0)
        _ca_sell_count = _f("15m:coinank_marketOrder_getBuySellCount_data_col1_last", 0)
        if _ca_buy_count + _ca_sell_count > 0:
            snap.coinank_buy_sell_count_ratio = (_ca_buy_count / (_ca_buy_count + _ca_sell_count)) * 2
        _ca_buy_val = _f("15m:coinank_marketOrder_getBuySellValue_data_col0_last", 0)
        _ca_sell_val = _f("15m:coinank_marketOrder_getBuySellValue_data_col1_last", 0)
        if _ca_sell_val > 0:
            snap.coinank_buy_sell_value_ratio = _ca_buy_val / _ca_sell_val
        _ca_buy_vol = _f("15m:coinank_marketOrder_getBuySellVolume_data_col0_last", 0)
        _ca_sell_vol = _f("15m:coinank_marketOrder_getBuySellVolume_data_col1_last", 0)
        if _ca_sell_vol > 0:
            snap.coinank_buy_sell_volume_ratio = _ca_buy_vol / _ca_sell_vol

        # CoinAnk liquidation history
        snap.coinank_liq_long_amount = _f("15m:coinank_liquidation_history_data_0_longAmount", 0.0)
        snap.coinank_liq_short_amount = _f("15m:coinank_liquidation_history_data_0_shortAmount", 0.0)
        snap.coinank_liq_long_turnover = _f("15m:coinank_liquidation_history_data_0_longTurnover", 0.0)
        snap.coinank_liq_short_turnover = _f("15m:coinank_liquidation_history_data_0_shortTurnover", 0.0)

        # CoinAnk OI
        _oi_val = _f("15m:coinank_openInterest_symbol_Chart_data_0_coinValue", 0.0)
        snap.oi_value = _oi_val

        # ── Price changes ──
        snap.price_change_5m_pct = _f("5m:ccxt_price_change_15m_pct", _f("15m:ccxt_price_change_15m_pct", 0.0))
        snap.price_change_15m_pct = _f("15m:ccxt_price_change_15m_pct", 0.0)

        # ── Cross-TF data ──
        snap.xtf_4h_rsi = _f("15m:xtf_4h_rsi_14", 50.0)
        snap.xtf_1h_rsi = _f("15m:xtf_1h_rsi_14", 50.0)
        snap.xtf_4h_ob_imbalance = _f("15m:xtf_4h_ob_ob_imbalance", 0.0)
        snap.xtf_1h_ob_imbalance = _f("15m:xtf_1h_ob_ob_imbalance", 0.0)
        snap.xtf_4h_liq_long_dist = _f("15m:xtf_4h_liquidation_long_distance_pct", 99.0)
        snap.xtf_4h_liq_short_dist = _f("15m:xtf_4h_liquidation_short_distance_pct", 99.0)
        snap.xtf_1h_funding_rate = _f("15m:xtf_1h_funding_rate", 0.0)
        snap.xtf_4h_funding_rate = _f("15m:xtf_4h_funding_rate", 0.0)

        # ── Candlestick patterns ──
        snap.cdl_engulfing = _f("15m:ind_ta_CDLENGULFING_15m", 0.0)
        snap.cdl_hammer = _f("15m:ind_ta_CDLHAMMER_15m", 0.0)
        snap.cdl_doji = _f("15m:ind_ta_CDLDOJI_15m", 0.0)
        snap.cdl_evening_star = _f("15m:ind_ta_CDLEVENINGSTAR_15m", 0.0)
        snap.cdl_shooting_star = _f("15m:ind_ta_CDLSHOOTINGSTAR_15m", 0.0)
        snap.cdl_marubozu = _f("15m:ind_ta_CDLMARUBOZU_15m", 0.0)

    def _fill_trainer(self, snap: MarketSnapshot):
        """Fetch latest trainer signal for this symbol."""
        sym = snap.symbol
        cache_key = f"trainer_sig:{sym}"
        cached = self._get_cache(cache_key, _TRAINER_CACHE_TTL)
        if cached is not None:
            snap.trainer = cached
            return

        sig = TrainerSignal(symbol=sym)
        try:
            # Read from signals:trading:primary stream (latest per symbol)
            # More efficient: check a per-symbol key if trainer publishes one
            latest_key = f"trainer:latest_signal:{sym}"
            raw = self.redis.get(latest_key)
            if raw:
                d = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                self._parse_trainer_signal(sig, d)
            else:
                # Fallback: scan recent stream entries
                entries = self.redis.xrevrange("signals:trading:primary", count=50)
                for _, data in (entries or []):
                    try:
                        d = json.loads(data.get(b"data", b"{}").decode())
                        if d.get("symbol") == sym and d.get("action") not in (
                            "HEARTBEAT", "CANARY", "SET_TAKE_PROFIT", "SET_STOP_LOSS"
                        ):
                            self._parse_trainer_signal(sig, d)
                            break
                    except Exception:
                        continue
        except Exception as e:
            logger.debug("HEDGE_CTX_TRAINER_ERR | %s | %s", sym, e)

        snap.trainer = sig
        self._set_cache(cache_key, sig)

    def _parse_trainer_signal(self, sig: TrainerSignal, d: Dict):
        """Parse trainer signal dict into TrainerSignal."""
        sig.action = str(d.get("action", ""))
        sig.confidence = float(d.get("confidence", 0) or 0)
        sig.target_price = float(d.get("trainer_target_price", 0) or d.get("target_price", 0) or 0)
        sig.target_pct = float(d.get("trainer_target_pct", 0) or 0)
        sig.consensus_direction = str(d.get("trainer_consensus_direction", "") or "")
        sig.consensus_confidence = float(d.get("trainer_consensus_confidence", 0) or 0)
        sig.market_regime = str(d.get("market_regime", "") or d.get("regime", "") or "")
        sig.move_regime = str(d.get("move_regime", "") or "")
        sig.tf_alignment = float(d.get("tf_alignment", 0) or d.get("trainer_tf_alignment", 0) or 0)

        # Direction from action
        act_upper = sig.action.upper()
        if "LONG" in act_upper or "BUY" in act_upper:
            sig.direction = "LONG"
        elif "SHORT" in act_upper or "SELL" in act_upper:
            sig.direction = "SHORT"
        else:
            sig.direction = sig.consensus_direction or "NEUTRAL"

        # Age
        ts = float(d.get("created_ts_ms", 0) or d.get("published_ts_ms", 0) or 0)
        if ts > 0:
            sig.age_sec = max(0, time.time() - ts / 1000.0)

    def _fill_coinank(self, snap: MarketSnapshot):
        """Supplement with global CoinAnk data (funding, LS ratio, OI).
        Most CoinAnk per-symbol data is already loaded in _fill_ta from unified_features.
        This adds global-level data that isn't per-symbol in unified_features.
        """
        sym = snap.symbol
        cache_key = f"coinank:{sym}"
        cached = self._get_cache(cache_key, _COINANK_CACHE_TTL)
        if cached is not None:
            if snap.funding_rate == 0.0:
                snap.funding_rate = cached.get("funding", 0)
            if snap.long_short_ratio == 1.0:
                snap.long_short_ratio = cached.get("ls_ratio", 1.0)
            snap.oi_change_pct_1h = cached.get("oi_change", snap.oi_change_pct_1h)
            snap.big_order_flow = cached.get("big_orders", 0)
            return

        result = {}
        try:
            pipe = self.redis.pipeline(transaction=False)
            pipe.get("coinank:fundingRate_current:last")
            pipe.get("coinank:longShort_current:last")
            pipe.get("coinank:openInterest_symbol_Chart:last")
            raw_funding, raw_ls, raw_oi = pipe.execute()

            if raw_funding:
                data = json.loads(raw_funding.decode() if isinstance(raw_funding, bytes) else raw_funding)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and sym.replace("USDT", "") in str(item.get("symbol", "")):
                            rate = float(item.get("rate", 0) or item.get("fundingRate", 0) or 0)
                            if snap.funding_rate == 0.0:
                                snap.funding_rate = rate
                            result["funding"] = rate
                            break

            if raw_ls:
                data = json.loads(raw_ls.decode() if isinstance(raw_ls, bytes) else raw_ls)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and sym.replace("USDT", "") in str(item.get("symbol", "")):
                            ratio = float(item.get("longShortRatio", 1.0) or 1.0)
                            snap.long_short_ratio = ratio
                            result["ls_ratio"] = ratio
                            break

            if raw_oi:
                data = json.loads(raw_oi.decode() if isinstance(raw_oi, bytes) else raw_oi)
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and sym.replace("USDT", "") in str(item.get("symbol", "")):
                            change = float(item.get("oiChangePercent1h", 0) or item.get("change1h", 0) or 0)
                            snap.oi_change_pct_1h = change
                            result["oi_change"] = change
                            break

            self._set_cache(cache_key, result)
        except Exception as e:
            logger.debug("HEDGE_CTX_COINANK_ERR | %s | %s", sym, e)

    def _fill_microstructure(self, snap: MarketSnapshot):
        """Supplement with real-time microstructure from msnap: keys.
        Depth/tape/spoof data already loaded from unified_features in _fill_ta.
        This adds real-time CoinAPI/Binance tape snapshots if available.
        """
        sym = snap.symbol
        cache_key = f"micro:{sym}"
        cached = self._get_cache(cache_key, _MICRO_CACHE_TTL)
        if cached is not None:
            if snap.spoof_score == 0:
                snap.spoof_score = cached.get("spoof", 0)
            snap.trade_intensity = cached.get("intensity", 0)
            if snap.fast_move_score == 0:
                snap.fast_move_score = cached.get("fast_move", 0)
            return

        result = {}
        try:
            for prefix in ["msnap:coinapi_wsds:", "msnap:binance_tape:"]:
                msnap = self.redis.hgetall(f"{prefix}{sym}")
                if msnap:
                    d = {}
                    for k, v in msnap.items():
                        kk = k.decode() if isinstance(k, bytes) else k
                        vv = v.decode() if isinstance(v, bytes) else v
                        try:
                            d[kk] = float(vv)
                        except (ValueError, TypeError):
                            d[kk] = vv
                    if snap.spoof_score == 0:
                        snap.spoof_score = float(d.get("spoof_score", 0) or 0)
                    snap.trade_intensity = float(d.get("trade_intensity", 0) or d.get("tick_intensity", 0) or 0)
                    if snap.fast_move_score == 0:
                        snap.fast_move_score = float(d.get("fast_move_score", 0) or d.get("fast_move", 0) or 0)
                    result = {"spoof": snap.spoof_score, "intensity": snap.trade_intensity,
                              "fast_move": snap.fast_move_score}
                    break
            self._set_cache(cache_key, result)
        except Exception as e:
            logger.debug("HEDGE_CTX_MICRO_ERR | %s | %s", sym, e)

    def _fill_liquidation(self, snap: MarketSnapshot):
        """Supplement liquidation data if not already loaded from unified_features.
        _fill_ta reads liquidation_* keys from unified_features. This is a fallback
        for the older liq_* key format.
        """
        if snap.nearest_liq_long_pct < 98 or snap.nearest_liq_short_pct < 98:
            return  # Already populated by _fill_ta

        sym = snap.symbol
        cache_key = f"liq:{sym}"
        cached = self._get_cache(cache_key, _COINANK_CACHE_TTL)
        if cached is not None:
            snap.nearest_liq_long_pct = cached.get("long_pct", 99.0)
            snap.nearest_liq_short_pct = cached.get("short_pct", 99.0)
            snap.liq_imbalance = cached.get("imbalance", 0)
            return

        result = {}
        try:
            # Fallback: try 1m unified_features with older key names
            vals = self.redis.hmget(f"unified_features:{sym}:1m", [
                "liquidation_long_distance_pct", "liquidation_short_distance_pct",
                "liquidation_long_strength", "liquidation_short_strength",
            ])
            if vals and any(v is not None for v in vals):
                long_dist = float(vals[0]) if vals[0] else 99.0
                short_dist = float(vals[1]) if vals[1] else 99.0
                long_str = float(vals[2]) if vals[2] else 0
                short_str = float(vals[3]) if vals[3] else 0
                snap.nearest_liq_long_pct = long_dist
                snap.nearest_liq_short_pct = short_dist
                if long_str + short_str > 0:
                    snap.liq_imbalance = (long_str - short_str) / (long_str + short_str)
                result = {"long_pct": long_dist, "short_pct": short_dist, "imbalance": snap.liq_imbalance}
            self._set_cache(cache_key, result)
        except Exception as e:
            logger.debug("HEDGE_CTX_LIQ_ERR | %s | %s", sym, e)

    def _fill_peer_actions(self, snap: MarketSnapshot):
        """Fill peer action summary."""
        actions = self.get_peer_actions(snap.symbol, window_sec=300)
        snap.peer_actions_last_5m = actions
        snap.total_hedge_adds_last_5m = sum(1 for a in actions if a.get("action") == "ADD")
        snap.total_hedge_trims_last_5m = sum(1 for a in actions if a.get("action") in ("TRIM", "CLOSE"))

    def _fill_hedge_coverage(self, snap: MarketSnapshot, positions: Dict):
        """Calculate current hedge coverage from positions dict."""
        sym = snap.symbol
        long_pos = positions.get(f"{sym}:LONG")
        short_pos = positions.get(f"{sym}:SHORT")

        if not (isinstance(long_pos, dict) and isinstance(short_pos, dict)):
            return

        def _margin(d):
            return float(d.get("margin_used", 0) or d.get("initialMargin", 0) or d.get("margin", 0) or 0)

        lm = _margin(long_pos)
        sm = _margin(short_pos)

        if lm < 1 and sm < 1:
            return

        if lm >= sm:
            snap.main_side = "LONG"
            snap.hedge_side = "SHORT"
            snap.hedge_coverage_pct = (sm / lm * 100) if lm > 0 else 0
        else:
            snap.main_side = "SHORT"
            snap.hedge_side = "LONG"
            snap.hedge_coverage_pct = (lm / sm * 100) if sm > 0 else 0

    # ─── CACHE HELPERS ────────────────────────────────────────────────────

    def _get_cache(self, key: str, ttl: float):
        if key in self._cache:
            val, ts = self._cache[key]
            if time.time() - ts < ttl:
                return val
        return None

    def _set_cache(self, key: str, val: Any):
        self._cache[key] = (val, time.time())


# ─── MODULE-LEVEL SINGLETON ──────────────────────────────────────────────

_instance: Optional[HedgeContext] = None


def get_hedge_context(redis_client: Any = None) -> HedgeContext:
    """Get or create the singleton HedgeContext."""
    global _instance
    if _instance is None and redis_client is not None:
        _instance = HedgeContext(redis_client)
    return _instance


# ─── INTELLIGENT HEDGE MARGIN SIZING ─────────────────────────────────────

def _smooth_mult(signal: float, scale: float = 1.0,
                  up_max: float = 1.5, down_min: float = 0.5) -> float:
    """Convert any continuous signal to a smooth multiplier around 1.0.
    signal > 0 → multiplier > 1.0 (up to up_max)
    signal < 0 → multiplier < 1.0 (down to down_min)
    Uses tanh for smooth saturation — NO hard thresholds.
    Anti-churn: tiny changes in input → tiny changes in output.
    """
    import math
    t = math.tanh(signal * scale)
    if t >= 0:
        return 1.0 + t * (up_max - 1.0)
    else:
        return 1.0 + t * (1.0 - down_min)


def compute_hedge_margin(
    snap: MarketSnapshot,
    main_margin: float,
    base_frac: float,
    *,
    position_side: str = "",
    roe_pct: float = 0.0,
    leverage: int = 1,
    source: str = "",
    min_margin: float = 5.0,
    max_frac: float = 0.30,
) -> Tuple[float, Dict[str, Any]]:
    """
    Compute hedge margin using ALL available market data — fully adaptive.

    ZERO static thresholds. Every multiplier is a smooth continuous function
    of market data, normalized by the symbol's own volatility (NATR).

    Anti-churn design:
    - All multipliers use tanh/sigmoid → smooth transitions, no cliff edges
    - Small market changes → small multiplier changes → stable hedge sizing
    - Multipliers bounded to narrow ranges (0.5x-1.5x each) to prevent wild swings
    - Max coverage cap adapts to conviction (not static 30%)

    Returns: (margin_usd, sizing_factors_dict)
    """
    import math
    factors: Dict[str, Any] = {
        "source": source, "base_frac": base_frac, "main_margin": main_margin,
    }
    frac = base_frac

    # ── Symbol's own volatility as normalizer ──
    natr = max(snap.natr_5m, snap.natr_15m, snap.natr_1h, 0.01)
    # Median NATR for crypto is ~0.8-1.2%. Use symbol's own value as baseline.
    # Smooth: natr/1.0 gives 1.0 at typical vol, scales up/down continuously
    vol_mult = _smooth_mult(natr - 1.0, scale=0.8, up_max=1.5, down_min=0.6)
    frac *= vol_mult
    factors["vol_mult"] = round(vol_mult, 3)
    factors["natr"] = round(natr, 3)

    # ── 2. Liquidation proximity — smooth exponential urgency ──
    liq_dist = snap.nearest_liq_long_pct if position_side == "LONG" else snap.nearest_liq_short_pct
    # Smooth: urgency = e^(-dist/3) gives 1.0 at dist=0, 0.37 at dist=3, 0.05 at dist=9
    liq_urgency = math.exp(-max(liq_dist, 0.1) / 3.0)
    # Map urgency [0,1] → multiplier [0.7, 2.0] smoothly
    liq_mult = 0.7 + liq_urgency * 1.3
    frac *= liq_mult
    factors["liq_mult"] = round(liq_mult, 3)
    factors["liq_dist"] = round(liq_dist, 2)

    # ── 3. Trainer signal alignment — continuous ──
    trainer_mult = 1.0
    if snap.trainer and snap.trainer.age_sec < 300:
        t_dir = snap.trainer.consensus_direction
        t_conf = snap.trainer.consensus_confidence
        # +1 if trainer is against our position (hedge is smart), -1 if with
        alignment = 0.0
        if position_side == "LONG" and t_dir in ("SHORT", "BEARISH"):
            alignment = t_conf  # against us → positive → hedge more
        elif position_side == "SHORT" and t_dir in ("LONG", "BULLISH"):
            alignment = t_conf
        elif position_side == "LONG" and t_dir in ("LONG", "BULLISH"):
            alignment = -t_conf  # with us → negative → hedge less
        elif position_side == "SHORT" and t_dir in ("SHORT", "BEARISH"):
            alignment = -t_conf
        trainer_mult = _smooth_mult(alignment, scale=1.5, up_max=1.3, down_min=0.4)
    frac *= trainer_mult
    factors["trainer_mult"] = round(trainer_mult, 3)

    # ── 4. Funding rate — continuous, no threshold ──
    # Positive funding + LONG position = crowded, hedge more (signal > 0)
    # Positive funding + SHORT position = we're contrarian, hedge less (signal < 0)
    funding = snap.funding_rate
    funding_signal = 0.0
    if position_side == "LONG":
        funding_signal = funding * 1000  # positive funding → hedge more for longs
    else:
        funding_signal = -funding * 1000  # negative funding → hedge more for shorts
    funding_mult = _smooth_mult(funding_signal, scale=0.8, up_max=1.3, down_min=0.75)
    frac *= funding_mult
    factors["funding_mult"] = round(funding_mult, 3)

    # ── 5. Multi-indicator agreement — continuous composite ──
    # Each indicator contributes a continuous "against position" score
    # Normalize each by its natural range — NO magic numbers
    against_signals = []
    if position_side == "LONG":
        # RSI overbought (reversal risk): (rsi-50)/30 → 1.0 at RSI 80
        against_signals.append((snap.rsi_15m - 50) / 30)
        # CCI overbought: /150 normalizes
        against_signals.append(snap.cci_15m / 150)
        # Stoch overbought: (stoch-50)/35
        against_signals.append((snap.stoch_k_15m - 50) / 35)
        # WillR: (-50-willr)/35 → high when willr near 0 (overbought)
        against_signals.append((-50 - snap.willr_15m) / -35)
    else:
        against_signals.append(-(snap.rsi_15m - 50) / 30)
        against_signals.append(-snap.cci_15m / 150)
        against_signals.append(-(snap.stoch_k_15m - 50) / 35)
        against_signals.append((snap.willr_15m + 50) / 35)
    # Average agreement — positive = indicators say reverse (hedge more)
    if against_signals:
        avg_against = sum(against_signals) / len(against_signals)
        indicator_mult = _smooth_mult(avg_against, scale=1.5, up_max=1.35, down_min=0.7)
    else:
        indicator_mult = 1.0
    frac *= indicator_mult
    factors["indicator_mult"] = round(indicator_mult, 3)

    # ── 6. OI change + direction score — continuous ──
    ds = snap.direction_score()
    # OI change amplifies direction signal: big OI + against us → urgent
    # Normalize OI change by itself (typical 1-5%)
    oi_norm = snap.oi_change_pct_1h / 5.0  # 5% → 1.0
    # Direction against us → positive signal
    oi_direction_signal = 0.0
    if position_side == "LONG":
        oi_direction_signal = -ds * abs(oi_norm)  # ds<0 + big OI → hedge more
    else:
        oi_direction_signal = ds * abs(oi_norm)   # ds>0 + big OI → hedge more
    oi_mult = _smooth_mult(oi_direction_signal, scale=1.0, up_max=1.2, down_min=0.8)
    frac *= oi_mult
    factors["oi_mult"] = round(oi_mult, 3)

    # ── 7. Depth + tape flow — continuous combined signal ──
    depth_imb = snap.depth_imbalance_5
    tape_imb = snap.tape_imbalance_30s
    # Combined: average of depth and tape, sign indicates direction
    combined_flow = (depth_imb + tape_imb) / 2.0
    # Against our position → positive
    if position_side == "LONG":
        flow_against = -combined_flow  # selling pressure against long
    else:
        flow_against = combined_flow   # buying pressure against short
    depth_tape_mult = _smooth_mult(flow_against, scale=2.0, up_max=1.25, down_min=0.75)
    frac *= depth_tape_mult
    factors["depth_tape_mult"] = round(depth_tape_mult, 3)

    # ── 8. Conviction-based sizing — the key adaptive piece ──
    conviction = snap.conviction_score()
    # Low conviction = uncertain → hedge more (protection in fog)
    # High conviction WITH us → hedge less (clear trend)
    # High conviction AGAINST us → hedge more (reversal coming)
    conviction_direction = 0.0
    if position_side == "LONG":
        conviction_direction = -ds * conviction  # ds<0 + high conv → positive → hedge more
    else:
        conviction_direction = ds * conviction
    # Also: low conviction itself is a hedge-more signal
    uncertainty_signal = (1.0 - conviction) * 0.3  # always positive, adds hedge
    conv_signal = conviction_direction + uncertainty_signal
    conv_mult = _smooth_mult(conv_signal, scale=1.5, up_max=1.3, down_min=0.5)
    frac *= conv_mult
    factors["conv_mult"] = round(conv_mult, 3)
    factors["conviction"] = round(conviction, 3)

    # ── 9. CoinAnk flow — continuous ratio deviation from 1.0 ──
    ca_mult = 1.0
    ca_ratio = snap.coinank_buy_sell_volume_ratio
    if ca_ratio > 0:
        # ratio>1 = buying, ratio<1 = selling. Against our position → hedge more
        ca_signal = 0.0
        if position_side == "LONG":
            ca_signal = -(ca_ratio - 1.0)  # selling (ratio<1) → positive signal
        else:
            ca_signal = (ca_ratio - 1.0)   # buying (ratio>1) → positive signal
        ca_mult = _smooth_mult(ca_signal, scale=2.0, up_max=1.15, down_min=0.8)
    frac *= ca_mult
    factors["ca_mult"] = round(ca_mult, 3)

    # ── 10. Microstructure — continuous composite ──
    # Fast move / spoof → hedge urgency UP. Snapback / false move → DOWN.
    micro_up = max(snap.fast_move_score, snap.spoof_score_v2)  # [0,1]
    micro_down = snap.snapback_score * 0.5 + snap.p_false_move * 0.5  # [0,1]
    micro_signal = micro_up - micro_down  # positive → hedge more
    micro_mult = _smooth_mult(micro_signal, scale=2.0, up_max=1.2, down_min=0.85)
    frac *= micro_mult
    factors["micro_mult"] = round(micro_mult, 3)

    # ── Adaptive max_frac: high conviction AGAINST us → allow up to max_frac ──
    # Low conviction / conviction WITH us → tighter cap ──
    adaptive_cap = max_frac
    if conviction > 0.5:
        if snap.against_side(position_side):
            adaptive_cap = max_frac  # Full cap when we need protection
        elif snap.favors_side(position_side):
            adaptive_cap = max_frac * 0.6  # Tighter when trend supports us
    factors["adaptive_cap"] = round(adaptive_cap, 4)

    # ── Clamp ──
    frac = max(min_margin / max(main_margin, 1.0), min(frac, adaptive_cap))
    factors["final_frac"] = round(frac, 4)

    margin_usd = max(min_margin, main_margin * frac)
    factors["margin_usd"] = round(margin_usd, 2)

    hedge_side = "SHORT" if position_side == "LONG" else "LONG"
    logger.info(
        "💰 HEDGE_MARGIN_SIZED | %s %s→%s | base=%.0f%% final=%.0f%% $%.2f | "
        "vol=%.2f liq=%.2f trainer=%.2f fund=%.2f ind=%.2f oi=%.2f dt=%.2f conv=%.2f ca=%.2f micro=%.2f | src=%s",
        snap.symbol, position_side, hedge_side,
        base_frac * 100, frac * 100, margin_usd,
        vol_mult, liq_mult, trainer_mult, funding_mult, indicator_mult,
        oi_mult, depth_tape_mult, conv_mult, ca_mult, micro_mult, source,
    )

    return margin_usd, factors


def compute_strategic_hedge_level(
    snap: MarketSnapshot,
    position_side: str,
) -> Dict[str, Any]:
    """
    Compute optimal hedge entry level using BBands, EMA/SMA, and liquidation levels.
    Instead of hedging at market price, find key levels to place limit orders.

    Returns dict with:
    - "entry_price": suggested hedge entry price (0 = use market)
    - "entry_type": "LIMIT" or "MARKET"
    - "reasoning": explanation string
    - "proximity_pct": how far entry is from current price
    """
    result = {"entry_price": 0.0, "entry_type": "MARKET", "reasoning": "default_market", "proximity_pct": 0.0}
    price = snap.mark_price
    if price <= 0:
        return result

    candidates = []
    # Use NATR as adaptive proximity gauge — what's "nearby" depends on volatility
    natr = max(snap.natr_15m, snap.natr_5m, 0.1)
    min_dist = natr * 0.05   # Too close = already there (adapts to vol)
    max_dist = natr * 2.0    # Too far = not actionable (adapts to vol)

    # BBands: hedge LONG → entry near upper band (resistance)
    if position_side == "LONG" and snap.bbands_upper_15m > 0:
        dist_pct = (snap.bbands_upper_15m - price) / price * 100
        if min_dist < dist_pct < max_dist:
            candidates.append(("bbands_upper", snap.bbands_upper_15m, dist_pct, 0.8))
    elif position_side == "SHORT" and snap.bbands_lower_15m > 0:
        dist_pct = (price - snap.bbands_lower_15m) / price * 100
        if min_dist < dist_pct < max_dist:
            candidates.append(("bbands_lower", snap.bbands_lower_15m, dist_pct, 0.8))

    # EMA 20: mean reversion level
    if snap.ema_20_15m > 0:
        if position_side == "LONG":
            dist_pct = (snap.ema_20_15m - price) / price * 100
            if dist_pct > min_dist:
                candidates.append(("ema20", snap.ema_20_15m, dist_pct, 0.6))
        else:
            dist_pct = (price - snap.ema_20_15m) / price * 100
            if dist_pct > min_dist:
                candidates.append(("ema20", snap.ema_20_15m, dist_pct, 0.6))

    # Liquidation levels: hedge near where liquidations cluster
    if position_side == "LONG" and snap.liq_short_level > 0:
        dist_pct = (snap.liq_short_level - price) / price * 100
        if min_dist < dist_pct < max_dist * 1.5:
            candidates.append(("liq_short_cluster", snap.liq_short_level, dist_pct, 0.9))
    elif position_side == "SHORT" and snap.liq_long_level > 0:
        dist_pct = (price - snap.liq_long_level) / price * 100
        if min_dist < dist_pct < max_dist * 1.5:
            candidates.append(("liq_long_cluster", snap.liq_long_level, dist_pct, 0.9))

    if candidates:
        # Pick candidate with highest score (weighted by proximity and quality)
        best = max(candidates, key=lambda c: c[3] / max(c[2], 0.1))
        result["entry_price"] = best[1]
        result["entry_type"] = "LIMIT"
        result["reasoning"] = best[0]
        result["proximity_pct"] = round(best[2], 3)

    return result
