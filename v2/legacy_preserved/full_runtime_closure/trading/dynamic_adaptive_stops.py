#!/usr/bin/env python3
"""
Dynamic Adaptive Stops System
=============================

Calculates trailing stops and take profits dynamically based on:
- Microstructure data (order flow imbalance, spoof detection, fast moves)
- Liquidation levels and squeeze detection
- Volatility (ATR, realized vol, implied vol proxies)
- Open Interest changes
- TA-LIB indicators (RSI, MACD, Bollinger Bands, ADX, etc.)

This replaces static % stops with intelligent, market-adaptive protection.
"""

import os
import time
import logging
import json
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class AdaptiveStopLevels:
    """Computed stop levels with full context"""
    symbol: str
    side: str  # LONG or SHORT
    entry_price: float
    current_price: float
    
    # Computed levels
    stop_loss_price: float
    stop_loss_pct: float
    take_profit_price: float
    take_profit_pct: float
    trailing_activation_pct: float
    trailing_distance_pct: float
    
    # Context that influenced the decision
    volatility_regime: str  # LOW, MEDIUM, HIGH, EXTREME
    liquidation_risk: str  # LOW, MEDIUM, HIGH
    microstructure_signal: str  # FAVORABLE, NEUTRAL, ADVERSE
    trend_strength: str  # WEAK, MODERATE, STRONG
    
    # Risk-reward
    risk_reward_ratio: float
    recommended_action: str  # HOLD, TIGHTEN, WIDEN, HEDGE
    
    # Debug info
    factors: Dict[str, float] = field(default_factory=dict)


class DynamicAdaptiveStops:
    """
    Intelligent stop loss and take profit calculator.
    
    Integrates multiple data sources for market-adaptive protection:
    1. Microstructure: Order flow, spoofing, fast moves
    2. Liquidation: Nearby liq levels, squeeze potential
    3. Volatility: ATR, realized vol, regime detection
    4. Open Interest: OI changes, funding rates
    5. Technical: RSI, MACD, BBands, ADX trend strength
    """
    
    def __init__(self, redis_client=None, config=None):
        self.redis = redis_client
        self.config = config
        
        # Base parameters (with 10x leverage in mind)
        # These are PRICE %, not ROE %
        # FIXED 2026-03-19: Defaults aligned with config.py / .env wider values
        # per session_summary.md — no tight static thresholds
        self.base_sl_pct = float(os.getenv("ADAPTIVE_BASE_SL_PCT", "4.0"))  # 40% ROE at 10x - Room to breathe
        self.base_sl_pct_with_hedge = float(os.getenv("ADAPTIVE_BASE_SL_PCT_WITH_HEDGE", "5.0"))  # 50% ROE when hedged
        self.base_tp_pct = float(os.getenv("ADAPTIVE_BASE_TP_PCT", "6.0"))  # 60% ROE at 10x - Better R:R
        self.min_sl_pct = float(os.getenv("ADAPTIVE_MIN_SL_PCT", "2.0"))   # 20% ROE min - Allow room
        self.max_sl_pct = float(os.getenv("ADAPTIVE_MAX_SL_PCT", "10.0"))  # 100% ROE max (only with hedge)
        self.min_tp_pct = float(os.getenv("ADAPTIVE_MIN_TP_PCT", "3.0"))   # 30% ROE min - Don't take profits too early
        self.max_tp_pct = float(os.getenv("ADAPTIVE_MAX_TP_PCT", "20.0"))  # 200% ROE max - Allow big wins
        
        # Trailing parameters (ROE %) - IMPROVED: Later activation to let winners run
        self.base_trail_activation = float(os.getenv("ADAPTIVE_TRAIL_ACTIVATION", "15.0"))  # 15% ROE before trailing starts
        self.base_trail_distance = float(os.getenv("ADAPTIVE_TRAIL_DISTANCE", "8.0"))      # 8% ROE trail distance
        
        # Cache for expensive calculations
        self._cache = {}
        self._cache_ttl = 5  # seconds
        
        logger.info(f"DynamicAdaptiveStops initialized | base_sl={self.base_sl_pct}% (with_hedge={self.base_sl_pct_with_hedge}%) | base_tp={self.base_tp_pct}%")
    
    def _merge_redis_live_streams(self, symbol: str, features: Dict) -> Dict:
        """Overlay CoinAnk per-symbol hash + CoinAPI msnap into features for adaptive trails."""
        out = dict(features or {})
        if not self.redis or not symbol:
            return out
        sym = str(symbol).upper().strip()
        try:
            raw = self.redis.hgetall(f"coinank:{sym}")
            if raw:
                for k, v in raw.items():
                    ks = k.decode("utf-8", errors="ignore") if isinstance(k, (bytes, bytearray)) else str(k)
                    vs = v.decode("utf-8", errors="ignore") if isinstance(v, (bytes, bytearray)) else str(v)
                    if ks in (
                        "funding_rate",
                        "open_interest",
                        "oi_change_pct",
                        "open_interest_change",
                        "long_short_ratio",
                    ):
                        try:
                            out[f"live_coinank_{ks}"] = float(vs)
                        except (ValueError, TypeError):
                            pass
        except Exception:
            pass
        try:
            ms = self.redis.hgetall(f"msnap:coinapi_wsds:{sym}")
            if ms:
                for k, v in ms.items():
                    kk = k.decode("utf-8", errors="ignore") if isinstance(k, (bytes, bytearray)) else str(k)
                    vv = v.decode("utf-8", errors="ignore") if isinstance(v, (bytes, bytearray)) else str(v)
                    if kk in ("imbalance_5", "fast_move_score", "spread_bps", "microprice", "mid_px"):
                        try:
                            out[f"live_msnap_{kk}"] = float(vv)
                        except (ValueError, TypeError):
                            pass
        except Exception:
            pass
        return out

    def calculate_adaptive_stops(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        current_price: float,
        position_size_usd: float = 0,
        features: Optional[Dict] = None,
        microstructure: Optional[Dict] = None,
        liquidation_data: Optional[Dict] = None,
        has_hedge: bool = False,
        leverage: float = 1.0,
    ) -> AdaptiveStopLevels:
        """
        Calculate fully adaptive stop loss and take profit levels.
        
        LEVERAGE-AWARE: All config values (base_sl, base_tp, etc.) are defined
        as ROE % targets at 10x leverage.  This method converts them to actual
        PRICE % by dividing by effective leverage, so stops are always placed
        at realistic distances from entry.
        
        Example: base_tp=6.0% is "60% ROE at 10x".  At 75x leverage the
        system targets the SAME 60% ROE → 60/75 = 0.80% price distance.
        
        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            side: LONG or SHORT
            entry_price: Position entry price
            current_price: Current mark price
            position_size_usd: Position notional value
            features: Unified features dict (volatility, indicators, etc.)
            microstructure: Microstructure data (order flow, spoofing, etc.)
            liquidation_data: Liquidation level data
            has_hedge: Whether position has an active hedge (allows wider SL)
            leverage: Position leverage (1-125x). Critical for correct stop placement.
        
        Returns:
            AdaptiveStopLevels with computed values and context
        """
        features = features or {}
        features = self._merge_redis_live_streams(symbol, features)
        microstructure = microstructure or {}
        liquidation_data = liquidation_data or {}
        leverage = max(1.0, float(leverage or 1.0))
        
        # ====================================================================
        # LEVERAGE SCALING: Config values are ROE % at 10x reference leverage.
        # Convert to price % for the ACTUAL leverage of this position.
        # lev_scale < 1.0 at high leverage → tighter price % (same ROE target)
        # lev_scale > 1.0 at low leverage  → wider price % (same ROE target)
        # ====================================================================
        _ref_lev = 10.0  # Config values calibrated for 10x
        lev_scale = _ref_lev / leverage  # 75x → 0.133, 50x → 0.20, 10x → 1.0
        
        # Scale base values from config ROE targets to actual price %
        _raw_base_sl = self.base_sl_pct_with_hedge if has_hedge else self.base_sl_pct
        base_sl = _raw_base_sl * lev_scale
        
        # ── ATR-BASED SL FLOOR (replaces pure leverage formula) ──
        # SL must be >= 1.5x ATR_5m to survive normal candle noise.
        # At high leverage (75-100x), the old formula (100/lev * 0.60) gave
        # 0.4-0.8% SL which is noise-level for crypto. ATR floor fixes this.
        _atr_sl_floor = 0.0
        try:
            if self.redis:
                for _atr_tf in ('5m', '15m', '1h'):
                    _atr_raw = self.redis.hgetall(f"unified_features:{symbol}:{_atr_tf}")
                    if not _atr_raw:
                        continue
                    for _ak, _av in _atr_raw.items():
                        _aks = _ak.decode("utf-8") if isinstance(_ak, (bytes, bytearray)) else str(_ak)
                        _avs = _av.decode("utf-8") if isinstance(_av, (bytes, bytearray)) else str(_av)
                        _akl = _aks.lower()
                        if 'natr_14' in _akl or 'natr' in _akl:
                            try:
                                _natr = float(_avs)
                                if 0.01 < _natr < 50:  # NATR is already % of price
                                    _atr_sl_floor = max(_atr_sl_floor, _natr * 2.0)
                            except (ValueError, TypeError):
                                pass
                    # Do NOT break — check all TFs and take the max
        except Exception:
            pass
        
        # Use REAL liquidation wall distance from features if available,
        # fall back to theoretical 100/leverage
        _liq_dist_pct = 100.0 / leverage  # theoretical default
        try:
            _feat_liq_long = float(features.get('liquidation_long_distance_pct', 0) or
                                   liquidation_data.get('liquidation_long_distance_pct', 0) or 0)
            _feat_liq_short = float(features.get('liquidation_short_distance_pct', 0) or
                                    liquidation_data.get('liquidation_short_distance_pct', 0) or 0)
            if side == 'LONG' and _feat_liq_long > 0.1:
                _liq_dist_pct = _feat_liq_long  # Use real, not min
            elif side == 'SHORT' and _feat_liq_short > 0.1:
                _liq_dist_pct = _feat_liq_short  # Use real, not min
        except Exception:
            pass
        
        _min_sl_price_pct = _liq_dist_pct * 0.60  # SL must be within 60% of liq
        # Apply ATR floor: never let SL be tighter than 1.5x ATR
        if _atr_sl_floor > 0:
            _min_sl_price_pct = max(_min_sl_price_pct, _atr_sl_floor)
        base_sl = max(base_sl, _min_sl_price_pct)
        
        factors = {}
        if _atr_sl_floor > 0:
            factors['atr_sl_floor_pct'] = round(_atr_sl_floor, 4)
        
        # ========================================================================
        # 1. VOLATILITY ANALYSIS
        # ========================================================================
        vol_multiplier, vol_regime = self._analyze_volatility(symbol, features)
        factors['volatility_mult'] = vol_multiplier
        
        # ========================================================================
        # 2. LIQUIDATION RISK ANALYSIS
        # ========================================================================
        liq_multiplier, liq_risk = self._analyze_liquidation_risk(
            symbol, side, current_price, liquidation_data, features
        )
        factors['liquidation_mult'] = liq_multiplier
        
        # ========================================================================
        # 3. MICROSTRUCTURE ANALYSIS
        # ========================================================================
        micro_multiplier, micro_signal = self._analyze_microstructure(
            symbol, side, microstructure, features
        )
        factors['microstructure_mult'] = micro_multiplier
        
        # ========================================================================
        # 4. TECHNICAL INDICATOR ANALYSIS (TA-LIB)
        # ========================================================================
        ta_multiplier, trend_strength = self._analyze_technical_indicators(
            symbol, side, features
        )
        factors['technical_mult'] = ta_multiplier
        
        # ========================================================================
        # 5. OPEN INTEREST & FUNDING ANALYSIS
        # ========================================================================
        oi_multiplier = self._analyze_open_interest(symbol, side, features)
        factors['oi_mult'] = oi_multiplier
        
        # ========================================================================
        # COMPUTE FINAL STOP LEVELS
        # ========================================================================
        
        # Combine all factors
        combined_sl_mult = (
            vol_multiplier * 0.35 +      # 35% weight to volatility
            liq_multiplier * 0.20 +      # 20% weight to liquidation
            micro_multiplier * 0.20 +    # 20% weight to microstructure
            ta_multiplier * 0.15 +       # 15% weight to technicals
            oi_multiplier * 0.10         # 10% weight to OI
        )
        
        # Apply combined multiplier to base stops
        # Use wider SL if hedged (set in base_sl variable above)
        adaptive_sl_pct = base_sl * combined_sl_mult
        # Clamp range is also leverage-scaled (same ROE targets at any leverage)
        _min_sl_scaled = self.min_sl_pct * lev_scale
        _max_sl_scaled = self.max_sl_pct * lev_scale
        # Never let SL go beyond 80% of liquidation distance
        _max_sl_scaled = min(_max_sl_scaled, _liq_dist_pct * 0.80)
        # Absolute floor: at least 0.05% price distance (avoid trigger on noise)
        _min_sl_scaled = max(0.05, _min_sl_scaled)
        adaptive_sl_pct = max(_min_sl_scaled, min(adaptive_sl_pct, _max_sl_scaled))
        factors['has_hedge'] = has_hedge
        factors['base_sl_used'] = round(base_sl, 4)
        factors['leverage'] = leverage
        factors['lev_scale'] = round(lev_scale, 4)
        factors['liq_dist_pct'] = round(_liq_dist_pct, 4)
        
        # TP is inversely affected by adverse conditions
        # If SL is widened (bad conditions), TP should be tightened for faster exits
        tp_mult = 1.0 / combined_sl_mult if combined_sl_mult > 1.0 else combined_sl_mult
        # Scale base TP by leverage (same ROE target at any leverage)
        _base_tp_scaled = self.base_tp_pct * lev_scale
        adaptive_tp_pct = _base_tp_scaled * (0.7 + tp_mult * 0.6)  # Range: 0.7x to 1.3x base

        # Regime-aware TP widening: when regime is FAST/IMPULSE with strong trend
        # alignment, use a wider TP multiplier to capture larger moves.
        try:
            if self.redis:
                import json as _jtp
                _tp_rr = self.redis.get(f"regime:{symbol}")
                if _tp_rr:
                    _tp_rd = _jtp.loads(_tp_rr.decode("utf-8") if isinstance(_tp_rr, (bytes, bytearray)) else str(_tp_rr))
                    _tp_move = str(_tp_rd.get("move_regime", "")).upper()
                    _tp_trend = str(_tp_rd.get("trend_direction", "")).upper()
                    _tp_align = float(_tp_rd.get("tf_alignment", 0) or 0)
                    _tp_is_long = side.upper() == "LONG"
                    _tp_aligned = (
                        (_tp_is_long and _tp_trend in ("LONG", "BULLISH", "UP") and _tp_align > 0.3)
                        or (not _tp_is_long and _tp_trend in ("SHORT", "BEARISH", "DOWN") and _tp_align < -0.3)
                    )
                    if _tp_aligned and _tp_move in ("FAST", "IMPULSE", "TRENDING", "BREAKOUT"):
                        _pre_tp = adaptive_tp_pct
                        _tp_widen_mult = 1.3
                        try:
                            _vol_s = float(_tp_rd.get("volatility_score", 0.5) or 0.5)
                            _tp_widen_mult += max(0, min(0.5, _vol_s))
                            _liq_s = float(_tp_rd.get("liquidity_score", 0.5) or 0.5)
                            if _liq_s > 0.6:
                                _tp_widen_mult += 0.2
                            for _tpf_tf in ("15m", "5m", "1h"):
                                _tpf_raw = self.redis.hgetall(f"unified_features:{symbol}:{_tpf_tf}")
                                if not _tpf_raw:
                                    continue
                                _tpf = {(k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else str(k)): (v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else str(v)) for k, v in _tpf_raw.items()}
                                for _adxk in ("adx_14", "adx", "ind_ta_ADX_14"):
                                    if _adxk in _tpf:
                                        try:
                                            _tpf_adx = float(_tpf[_adxk])
                                            if _tpf_adx > 40: _tp_widen_mult += 0.6
                                            elif _tpf_adx > 25: _tp_widen_mult += 0.3
                                        except Exception: pass
                                        break
                                for _atrk in ("atr_pct", "atr_14", "ind_ta_ATR_14"):
                                    if _atrk in _tpf:
                                        try:
                                            _tpf_atr = float(_tpf[_atrk])
                                            if _tpf_atr > 4.0: _tp_widen_mult += 0.4
                                            elif _tpf_atr > 2.0: _tp_widen_mult += 0.2
                                        except Exception: pass
                                        break
                                break
                        except Exception:
                            pass
                        _tp_widen_mult = max(1.3, min(3.5, _tp_widen_mult))
                        adaptive_tp_pct = adaptive_tp_pct * _tp_widen_mult
                        factors["regime_tp_widen"] = True
                        factors["regime_tp_widen_mult"] = round(_tp_widen_mult, 2)
                        factors["regime_move"] = _tp_move
                        factors["regime_trend"] = _tp_trend
        except Exception:
            pass

        # ── Trainer target price attractor for initial TP ──
        # Pull TP toward the trainer's predicted target when the prediction
        # aligns with position direction and confidence is sufficient.
        try:
            if self.redis:
                from risk.trainer_alignment import get_trainer_view
                _tv = get_trainer_view(self.redis, symbol)
                if _tv and _tv.is_directional and _tv.best_target_price > 0:
                    _tgt = _tv.best_target_price
                    _tdir = _tv.consensus_direction.upper()
                    _tconf = min(1.0, max(0.0, _tv.consensus_confidence))
                    _is_long = side.upper() == "LONG"
                    _aligned = (
                        (_is_long and _tdir in ("LONG", "BULLISH", "UP"))
                        or (not _is_long and _tdir in ("SHORT", "BEARISH", "DOWN"))
                    )
                    if _aligned and _tconf >= 0.60 and entry_price > 0:
                        _trainer_tp_pct = abs(_tgt - entry_price) / entry_price * 100.0
                        if _trainer_tp_pct > adaptive_tp_pct:
                            _blend = min(0.4, _tconf * 0.4)
                            _pre = adaptive_tp_pct
                            adaptive_tp_pct += (_trainer_tp_pct - adaptive_tp_pct) * _blend
                            factors["trainer_tp_pull"] = True
                            factors["trainer_target"] = round(_tgt, 6)
                            factors["trainer_conf"] = round(_tconf, 3)
                            factors["trainer_tp_pct"] = round(_trainer_tp_pct, 3)
                            logger.info(
                                "ADAPTIVE_TRAINER_TP | sym=%s side=%s | pre=%.3f%% post=%.3f%% | "
                                "tgt=%.6f conf=%.2f trainer_pct=%.3f%%",
                                symbol, side, _pre, adaptive_tp_pct,
                                _tgt, _tconf, _trainer_tp_pct,
                            )
        except Exception:
            pass

        # Clamp TP range (leverage-scaled)
        _min_tp_scaled = max(0.05, self.min_tp_pct * lev_scale)
        _max_tp_scaled = self.max_tp_pct * lev_scale
        adaptive_tp_pct = max(_min_tp_scaled, min(adaptive_tp_pct, _max_tp_scaled))

        # MAX ROE CAP: Prevent TP from targeting unrealistic ROE at high leverage.
        # Even after all widen multipliers and trainer pulls, cap TP at 200% ROE.
        # At 94x: 200/94 = 2.13%p max.  At 21x: 200/21 = 9.52%p max.
        _max_tp_roe = 200.0
        _max_tp_by_roe = _max_tp_roe / max(1.0, leverage)
        adaptive_tp_pct = min(adaptive_tp_pct, _max_tp_by_roe)

        # ── FIX 1 (Redesign v2): ATR-Based TP Override ──────────────────────
        # If ATR data is available, override the leverage-scaled TP with an
        # ATR-based distance that respects actual volatility. This prevents
        # TPs from firing at 0.75% on a 47% move.
        try:
            from trading.redesign_v2_helpers import compute_atr_tp_distance
            _atr_tp = compute_atr_tp_distance(self.redis, symbol, entry_price, leverage)
            if _atr_tp is not None and _atr_tp > adaptive_tp_pct:
                _pre_atr = adaptive_tp_pct
                adaptive_tp_pct = _atr_tp
                factors["atr_tp_override"] = True
                factors["atr_tp_pct"] = round(_atr_tp, 3)
                factors["pre_atr_tp_pct"] = round(_pre_atr, 3)
                logger.info(
                    "ATR_TP_OVERRIDE | sym=%s side=%s | old_tp=%.3f%% → atr_tp=%.3f%% | lev=%.0fx",
                    symbol, side, _pre_atr, _atr_tp, leverage,
                )
        except Exception as _atr_err:
            logger.debug("ATR_TP_OVERRIDE_ERR | %s | %s", symbol, _atr_err)
        
        # Calculate actual price levels
        if side == 'LONG':
            sl_price = entry_price * (1 - adaptive_sl_pct / 100)
            tp_price = entry_price * (1 + adaptive_tp_pct / 100)
        else:  # SHORT
            sl_price = entry_price * (1 + adaptive_sl_pct / 100)
            tp_price = entry_price * (1 - adaptive_tp_pct / 100)
        
        # Trailing stop parameters (ROE-based)
        # LEVERAGE-AWARE: Higher leverage amplifies price moves into larger ROE.
        # At 75x, even 0.1% price move = 7.5% ROE. Trail activation must be lower
        # at high leverage so it arms proportionally to achievable price moves.
        # Scale: (reference_leverage / actual_leverage) ^ 0.4
        _lev_trail_scale = min(1.5, max(0.3, (20.0 / max(1.0, leverage)) ** 0.4))
        
        trail_activation = self.base_trail_activation * _lev_trail_scale * vol_multiplier
        trail_activation = max(3.0, min(trail_activation, 25.0))  # 3-25% ROE
        
        trail_distance = self.base_trail_distance * _lev_trail_scale * vol_multiplier
        trail_distance = max(2.0, min(trail_distance, 15.0))  # 2-15% ROE

        # Widen trailing activation/distance when live CoinAPI + CoinAnk flow aligns with the position.
        try:
            _imb = float(
                features.get("live_msnap_imbalance_5")
                or features.get("order_flow_imbalance")
                or features.get("bid_ask_imbalance")
                or 0.0
            )
            _fr = float(
                features.get("live_coinank_funding_rate")
                or features.get("funding_rate")
                or features.get("coinank_fundingRate_indicator_data_0_fundingRate")
                or 0.0
            )
            _widen = 1.0
            _side_u = str(side or "").upper()
            if _side_u == "LONG" and _imb > 0.06:
                _widen *= 1.12
            elif _side_u == "SHORT" and _imb < -0.06:
                _widen *= 1.12
            if _side_u == "LONG" and _fr < -0.0003:
                _widen *= 1.05
            elif _side_u == "SHORT" and _fr > 0.0003:
                _widen *= 1.05
            if _widen > 1.01:
                trail_distance = min(24.0, trail_distance * _widen)
                trail_activation = min(42.0, trail_activation * (1.0 + (_widen - 1.0) * 0.45))
                factors["live_stream_trail_widen"] = round(_widen, 4)
        except Exception:
            pass
        
        logger.info(
            "ADAPTIVE_STOP_CALC | sym=%s side=%s lev=%.0fx | "
            "sl=%.4f%%p (%.1f%% ROE) tp=%.4f%%p (%.1f%% ROE) | "
            "base_sl=%.3f%%p base_tp=%.3f%%p | lev_scale=%.4f | "
            "hedge=%s vol=%s liq=%s | trail_act=%.1f%% trail_dist=%.1f%%",
            symbol, side, leverage,
            adaptive_sl_pct, adaptive_sl_pct * leverage, adaptive_tp_pct, adaptive_tp_pct * leverage,
            base_sl, _base_tp_scaled, lev_scale,
            has_hedge, vol_regime, liq_risk,
            trail_activation, trail_distance,
        )
        
        # Risk-Reward ratio
        rr_ratio = adaptive_tp_pct / adaptive_sl_pct if adaptive_sl_pct > 0 else 0
        
        # Recommended action based on conditions
        recommended_action = self._determine_recommended_action(
            vol_regime, liq_risk, micro_signal, trend_strength, rr_ratio
        )
        
        factors['final_sl_pct'] = adaptive_sl_pct
        factors['final_tp_pct'] = adaptive_tp_pct
        factors['rr_ratio'] = rr_ratio
        
        return AdaptiveStopLevels(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            current_price=current_price,
            stop_loss_price=sl_price,
            stop_loss_pct=adaptive_sl_pct,
            take_profit_price=tp_price,
            take_profit_pct=adaptive_tp_pct,
            trailing_activation_pct=trail_activation,
            trailing_distance_pct=trail_distance,
            volatility_regime=vol_regime,
            liquidation_risk=liq_risk,
            microstructure_signal=micro_signal,
            trend_strength=trend_strength,
            risk_reward_ratio=rr_ratio,
            recommended_action=recommended_action,
            factors=factors
        )
    
    def _analyze_volatility(self, symbol: str, features: Dict) -> Tuple[float, str]:
        """
        Analyze volatility using ATR, realized vol, and regime detection.
        
        Returns:
            (multiplier, regime) where:
            - multiplier: 0.8 (low vol) to 1.5 (extreme vol)
            - regime: LOW, MEDIUM, HIGH, EXTREME
        """
        # Get various volatility measures
        atr_pct = float(features.get('atr_pct', features.get('atr_14', 0)) or 0)
        volatility_5m = float(features.get('volatility_5m', 0) or 0)
        volatility_1h = float(features.get('volatility_1h', 0) or 0)
        bbands_width = float(features.get('bbands_width', features.get('bb_width', 0)) or 0)
        
        # Normalize to 0-1 scale
        vol_score = 0.0
        
        # ATR contribution (typical crypto: 1-5% daily)
        if atr_pct > 0:
            if atr_pct < 1.0:
                vol_score += 0.2
            elif atr_pct < 2.0:
                vol_score += 0.4
            elif atr_pct < 3.5:
                vol_score += 0.6
            else:
                vol_score += 0.8
        
        # Realized vol contribution
        avg_vol = (volatility_5m + volatility_1h) / 2 if volatility_1h > 0 else volatility_5m
        if avg_vol > 0.03:  # >3% volatility
            vol_score += 0.3
        elif avg_vol > 0.02:
            vol_score += 0.2
        elif avg_vol > 0.01:
            vol_score += 0.1
        
        # BBands width contribution (typical: 2-8%)
        if bbands_width > 6:
            vol_score += 0.2
        elif bbands_width > 4:
            vol_score += 0.1
        
        # Normalize and determine regime
        vol_score = min(vol_score, 1.0)
        
        if vol_score < 0.25:
            regime = "LOW"
            multiplier = 0.8  # Tighter stops in low vol
        elif vol_score < 0.5:
            regime = "MEDIUM"
            multiplier = 1.0  # Normal stops
        elif vol_score < 0.75:
            regime = "HIGH"
            multiplier = 1.25  # Wider stops
        else:
            regime = "EXTREME"
            multiplier = 1.5  # Much wider stops
        
        return multiplier, regime
    
    def _analyze_liquidation_risk(
        self,
        symbol: str,
        side: str,
        current_price: float,
        liquidation_data: Dict,
        features: Dict
    ) -> Tuple[float, str]:
        """
        Analyze liquidation levels and squeeze potential.
        
        ENHANCED: Uses full liquidation level data for accurate risk assessment.
        
        Returns:
            (multiplier, risk_level) where:
            - multiplier: 0.9 (low risk) to 1.4 (high risk)
            - risk_level: LOW, MEDIUM, HIGH
        """
        # Get liquidation level data (from unified features or liquidation_data)
        liq_long_level = float(
            features.get('liquidation_long_level', 0) or 
            liquidation_data.get('liq_long_level', 0) or 0
        )
        liq_short_level = float(
            features.get('liquidation_short_level', 0) or 
            liquidation_data.get('liq_short_level', 0) or 0
        )
        liq_long_strength = float(
            features.get('liquidation_long_strength', 0) or 
            liquidation_data.get('liq_long_strength', 0) or 0
        )
        liq_short_strength = float(
            features.get('liquidation_short_strength', 0) or 
            liquidation_data.get('liq_short_strength', 0) or 0
        )
        
        # Calculate distances to liquidation levels
        liq_long_distance_pct = 100.0  # Default to far
        liq_short_distance_pct = 100.0
        
        if current_price > 0:
            if liq_long_level > 0:
                liq_long_distance_pct = abs(current_price - liq_long_level) / current_price * 100
            if liq_short_level > 0:
                liq_short_distance_pct = abs(liq_short_level - current_price) / current_price * 100
        
        # Get additional liquidation metrics
        liq_squeeze_score = float(features.get('liq_squeeze_score', features.get('squeeze_potential', 0)) or 0)
        funding_rate = float(features.get('funding_rate', features.get('coinank_funding_rate', 0)) or 0)
        liq_ratio = float(features.get('binance_liq_ratio', features.get('liq_ratio', 1.0)) or 1.0)
        liq_vol_long = float(features.get('binance_liq_volume_long_usd', 0) or 0)
        liq_vol_short = float(features.get('binance_liq_volume_short_usd', 0) or 0)
        
        risk_score = 0.0
        
        # ========================================================================
        # SIDE-SPECIFIC RISK ANALYSIS
        # For LONG: Worried about price dropping to long liq levels (cascade down)
        # For SHORT: Worried about price rising to short liq levels (squeeze up)
        # ========================================================================
        
        if side == 'LONG':
            # Adverse liq level (below current price, strong longs clustered there)
            adverse_distance = liq_long_distance_pct
            adverse_strength = liq_long_strength
            
            # Check if longs are getting liquidated heavily (bearish)
            if liq_ratio > 2.0:  # More longs liquidated than shorts
                risk_score += min(0.4, (liq_ratio - 1.0) * 0.2)
            
            # Check if there's a favorable squeeze opportunity (shorts above)
            favorable_distance = liq_short_distance_pct
            favorable_strength = liq_short_strength
        else:
            # For SHORT, reverse the logic
            adverse_distance = liq_short_distance_pct
            adverse_strength = liq_short_strength
            
            # Check if shorts are getting liquidated heavily (bullish)
            if liq_ratio < 0.5:  # More shorts liquidated than longs
                risk_score += min(0.4, (1.0 - liq_ratio) * 0.4)
            
            favorable_distance = liq_long_distance_pct
            favorable_strength = liq_long_strength
        
        # Adverse liquidation proximity risk
        if adverse_distance < 2.0 and adverse_strength > 0.5:
            risk_score += 0.5  # Very close to strong adverse cluster
        elif adverse_distance < 3.0 and adverse_strength > 0.3:
            risk_score += 0.3
        elif adverse_distance < 5.0:
            risk_score += 0.15
        
        # Squeeze potential (favorable liq cluster nearby)
        # This is opportunity, not risk - but we should be aware
        if favorable_distance < 3.0 and favorable_strength > 0.6:
            # High squeeze potential - might want tighter trailing to capture
            risk_score -= 0.1  # Slight reduction in risk multiplier
        
        # Funding rate pressure
        if abs(funding_rate) > 0.001:  # >0.1% funding
            if (side == 'LONG' and funding_rate > 0.001) or (side == 'SHORT' and funding_rate < -0.001):
                # Funding is against our position
                risk_score += 0.2
        
        # High liquidation volume (volatility indicator)
        total_liq_vol = liq_vol_long + liq_vol_short
        if total_liq_vol > 10_000_000:  # >$10M liquidated in last hour
            risk_score += 0.15  # High volatility environment
        elif total_liq_vol > 5_000_000:
            risk_score += 0.1
        
        # Determine risk level
        risk_score = max(0, min(risk_score, 1.0))  # Clamp to 0-1
        
        if risk_score < 0.25:
            return 0.9, "LOW"
        elif risk_score < 0.5:
            return 1.1, "MEDIUM"
        else:
            return 1.3 + (risk_score - 0.5) * 0.2, "HIGH"  # 1.3 to 1.4
    
    def _analyze_microstructure(
        self,
        symbol: str,
        side: str,
        microstructure: Dict,
        features: Dict
    ) -> Tuple[float, str]:
        """
        Analyze order flow, spoofing, and fast moves.
        
        Returns:
            (multiplier, signal) where:
            - multiplier: 0.85 (favorable) to 1.3 (adverse)
            - signal: FAVORABLE, NEUTRAL, ADVERSE
        """
        # Get microstructure signals
        spoof_score = float(microstructure.get('spoof_score', features.get('spoof_score', 0)) or 0)
        fast_move_score = float(microstructure.get('fast_move_score', features.get('fast_move_score', 0)) or 0)
        order_imbalance = float(features.get('order_imbalance', features.get('bid_ask_imbalance', 0)) or 0)
        trade_intensity = float(features.get('trade_intensity', 0) or 0)
        
        # Determine if conditions are for or against our position
        adverse_score = 0.0
        favorable_score = 0.0
        
        # Spoofing against us
        if spoof_score > 0.5:
            adverse_score += 0.3
        
        # Fast move — direction-aware: only widen SL when the move is against us
        if fast_move_score > 0.6:
            is_adverse_fast = (
                (side == 'LONG' and order_imbalance < -0.15)
                or (side == 'SHORT' and order_imbalance > 0.15)
            )
            if is_adverse_fast:
                adverse_score += 0.3
            elif (side == 'LONG' and order_imbalance > 0.15) or (side == 'SHORT' and order_imbalance < -0.15):
                favorable_score += 0.15
        
        # Order imbalance against us
        if side == 'LONG' and order_imbalance < -0.3:
            adverse_score += 0.2
        elif side == 'SHORT' and order_imbalance > 0.3:
            adverse_score += 0.2
        
        # High trade intensity (potential for rapid moves)
        if trade_intensity > 0.7:
            adverse_score += 0.1
        
        # Favorable conditions
        if side == 'LONG' and order_imbalance > 0.3:
            favorable_score += 0.2
        elif side == 'SHORT' and order_imbalance < -0.3:
            favorable_score += 0.2
        
        net_score = adverse_score - favorable_score
        
        if net_score < -0.1:
            return 0.85, "FAVORABLE"
        elif net_score < 0.2:
            return 1.0, "NEUTRAL"
        else:
            return 1.3, "ADVERSE"
    
    def _analyze_technical_indicators(
        self,
        symbol: str,
        side: str,
        features: Dict
    ) -> Tuple[float, str]:
        """
        Analyze TA-LIB indicators for trend and momentum.
        
        Uses: RSI, MACD, ADX, Bollinger Bands, etc.
        
        Returns:
            (multiplier, trend_strength) where:
            - multiplier: 0.85 (strong trend with us) to 1.25 (against us)
            - trend_strength: WEAK, MODERATE, STRONG
        """
        # RSI
        rsi = float(features.get('rsi_14', features.get('rsi', 50)) or 50)
        
        # MACD
        macd_hist = float(features.get('macd_histogram', features.get('macd_hist', 0)) or 0)
        
        # ADX (trend strength)
        adx = float(features.get('adx_14', features.get('adx', 20)) or 20)
        plus_di = float(features.get('plus_di', features.get('+di', 0)) or 0)
        minus_di = float(features.get('minus_di', features.get('-di', 0)) or 0)
        
        # Bollinger Bands position
        bb_pct = float(features.get('bb_percent', features.get('bbands_pct_b', 0.5)) or 0.5)
        
        # Trend alignment score
        alignment_score = 0.0
        
        # RSI: Overbought/oversold against position
        if side == 'LONG':
            if rsi > 75:  # Overbought - potential reversal
                alignment_score -= 0.2
            elif rsi < 30:  # Oversold - good for longs
                alignment_score += 0.2
            elif rsi > 50:
                alignment_score += 0.1
        else:  # SHORT
            if rsi < 25:  # Oversold - potential reversal
                alignment_score -= 0.2
            elif rsi > 70:  # Overbought - good for shorts
                alignment_score += 0.2
            elif rsi < 50:
                alignment_score += 0.1
        
        # MACD alignment
        if side == 'LONG' and macd_hist > 0:
            alignment_score += 0.2
        elif side == 'SHORT' and macd_hist < 0:
            alignment_score += 0.2
        elif (side == 'LONG' and macd_hist < 0) or (side == 'SHORT' and macd_hist > 0):
            alignment_score -= 0.2
        
        # ADX trend strength
        if adx > 25:  # Strong trend
            # Check if trend is in our favor
            if side == 'LONG' and plus_di > minus_di:
                alignment_score += 0.2
            elif side == 'SHORT' and minus_di > plus_di:
                alignment_score += 0.2
            else:
                alignment_score -= 0.3  # Strong trend against us
        
        # Bollinger Bands
        if side == 'LONG' and bb_pct < 0.2:  # Near lower band - bounce potential
            alignment_score += 0.1
        elif side == 'SHORT' and bb_pct > 0.8:  # Near upper band - reversal potential
            alignment_score += 0.1
        
        # Determine trend strength and multiplier
        if adx < 20:
            trend_strength = "WEAK"
        elif adx < 35:
            trend_strength = "MODERATE"
        else:
            trend_strength = "STRONG"
        
        # Convert alignment to multiplier
        if alignment_score > 0.3:
            multiplier = 0.85  # Good alignment - tighter stops OK
        elif alignment_score > 0:
            multiplier = 0.95
        elif alignment_score > -0.2:
            multiplier = 1.05
        else:
            multiplier = 1.25  # Bad alignment - wider stops needed
        
        return multiplier, trend_strength
    
    def _analyze_open_interest(self, symbol: str, side: str, features: Dict) -> float:
        """
        Analyze open interest changes and funding rates.
        
        Returns:
            multiplier: 0.9 to 1.2
        """
        oi_change = float(features.get('open_interest_change', features.get('oi_change', 0)) or 0)
        oi_change_24h = float(features.get('oi_change_24h', 0) or 0)
        funding_rate = float(features.get('funding_rate', 0) or 0)
        
        multiplier = 1.0
        
        # Rapid OI increase = potential for volatility
        if abs(oi_change) > 5:  # >5% OI change
            multiplier += 0.1
        
        # Extreme funding (crowded trade)
        if abs(funding_rate) > 0.001:  # >0.1%
            if (side == 'LONG' and funding_rate > 0) or (side == 'SHORT' and funding_rate < 0):
                # Funding against us - crowded trade risk
                multiplier += 0.1
        
        return min(max(multiplier, 0.9), 1.2)
    
    def _determine_recommended_action(
        self,
        vol_regime: str,
        liq_risk: str,
        micro_signal: str,
        trend_strength: str,
        rr_ratio: float
    ) -> str:
        """Determine recommended action based on all factors."""
        
        # Count adverse conditions
        adverse_count = 0
        if vol_regime in ("HIGH", "EXTREME"):
            adverse_count += 1
        if liq_risk == "HIGH":
            adverse_count += 1
        if micro_signal == "ADVERSE":
            adverse_count += 1
        if trend_strength == "STRONG" and rr_ratio < 1.0:
            adverse_count += 1
        
        # Determine action
        if adverse_count >= 3:
            return "HEDGE"  # Open protective hedge
        elif adverse_count >= 2:
            return "TIGHTEN"  # Tighten stops
        elif adverse_count == 0 and micro_signal == "FAVORABLE":
            return "WIDEN"  # Can afford wider stops
        else:
            return "HOLD"  # Maintain current levels
    
    def get_features_from_redis(self, symbol: str, timeframe: str = "5m") -> Dict:
        """Fetch unified features from Redis for a symbol/timeframe.

        NOTE: Our current feature store is `unified_features:{symbol}:{tf}` as a Redis HASH
        (plus optional normalized JSON mirrors). This helper keeps backwards-compatible
        fallbacks but prioritizes the live unified hash.
        """
        if not self.redis:
            return {}
        
        cache_key = f"features:{symbol}:{timeframe}"
        now = time.time()
        
        # Check cache
        if cache_key in self._cache:
            cached_data, cached_time = self._cache[cache_key]
            if now - cached_time < self._cache_ttl:
                return cached_data
        
        try:
            features: Dict[str, Any] = {}

            def _loads(raw):
                raw = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw
                if not raw:
                    return None
                try:
                    return json.loads(raw)
                except Exception:
                    return None

            def _merge_hash(h: Dict) -> None:
                if not isinstance(h, dict):
                    return
                for k, v in h.items():
                    k = k.decode("utf-8") if isinstance(k, (bytes, bytearray)) else k
                    v = v.decode("utf-8") if isinstance(v, (bytes, bytearray)) else v
                    features[k] = v

            # 1) Primary: unified_features hash (per symbol/timeframe)
            unified_key = f"unified_features:{symbol}:{timeframe}"
            try:
                h = self.redis.hgetall(unified_key)
                if h:
                    _merge_hash(h)
            except Exception:
                pass

            # 2) Optional normalized JSON mirrors (best-effort)
            for key in (
                f"features:unified:{symbol}:{timeframe}:normalized",
                f"features:unified:{symbol}:{timeframe}",
            ):
                try:
                    raw = self.redis.get(key)
                    parsed = _loads(raw)
                    if isinstance(parsed, dict):
                        features.update(parsed)
                except Exception:
                    continue

            # 3) TA indicators (legacy JSON key; best-effort)
            for ta_key in (f"ta:{symbol}:{timeframe}", f"ta:{symbol}:5m"):
                try:
                    raw = self.redis.get(ta_key)
                    parsed = _loads(raw)
                    if isinstance(parsed, dict):
                        features.update(parsed)
                        break
                except Exception:
                    continue

            # ------------------------------------------------------------------
            # Canonical convenience fields (computed from CoinAnk fields when present)
            # This makes downstream modules robust to endpoint-specific key names.
            # ------------------------------------------------------------------
            def _sf(*keys, default: float = 0.0) -> float:
                for k in keys:
                    if k in features:
                        try:
                            return float(features.get(k) or 0.0)
                        except Exception:
                            continue
                return float(default)

            # Funding rate
            if _sf("funding_rate", default=0.0) == 0.0:
                fr = _sf(
                    "coinank_fundingRate_indicator_data_0_fundingRate",
                    "coinank_fundingRate_indicator_data_0_fr",
                    "coinank_fundingRate_kline_data_0_close",
                    "coinank_fundingRate_kline_data_0_open",
                    "coinank_funding_rate",
                    default=0.0,
                )
                if fr != 0.0:
                    features["funding_rate"] = fr

            # Open interest change (% over the current interval)
            if _sf("open_interest_change", default=0.0) == 0.0:
                oi_open = _sf("coinank_openInterest_kline_data_0_open", "coinank_openInterest_kline_data_0_o", default=0.0)
                oi_close = _sf("coinank_openInterest_kline_data_0_close", "coinank_openInterest_kline_data_0_c", default=0.0)
                if oi_open > 0 and oi_close > 0:
                    oi_chg_pct = ((oi_close - oi_open) / oi_open) * 100.0
                    features["open_interest_change"] = oi_chg_pct
                    # Common alias used by some modules
                    features.setdefault("oi_change", oi_chg_pct)

            # Cache result
            self._cache[cache_key] = (features, now)
            return features

        except Exception as e:
            logger.debug(f"Failed to fetch features for {symbol}:{timeframe}: {e}")
            return {}


# Global instance
_adaptive_stops_instance = None


def get_adaptive_stops(redis_client=None) -> DynamicAdaptiveStops:
    """Get or create the global adaptive stops instance."""
    global _adaptive_stops_instance
    if _adaptive_stops_instance is None:
        _adaptive_stops_instance = DynamicAdaptiveStops(redis_client=redis_client)
    return _adaptive_stops_instance

