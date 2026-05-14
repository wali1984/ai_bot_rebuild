#!/usr/bin/env python3
"""
Dynamic Take Profit Engine
==========================

Fully adaptive, feature-driven take profit system that:
1. Continuously recalculates TP levels based on 200+ market features
2. Uses liquidation levels, funding rates, OI changes for optimal exits
3. Implements intelligent trailing that adapts to volatility and momentum
4. Detects "ride-the-move" scenarios to let winners run
5. Integrates microstructure data (spoofing, order flow) for timing

This replaces static % TP with market-adaptive profit optimization.

Key Features:
- ATR-based TP targets (wider in volatile markets)
- Liquidation squeeze detection (tighter TP when squeeze potential)
- Momentum continuation detection (suppress TP, trail instead)
- Order flow alignment (widen TP when favorable flow)
- Multi-timeframe trend confirmation

Author: WMA AI Trading System
Date: January 10, 2026
"""

import os
import time
import json
import logging
from typing import Dict, Optional, Tuple, Any, List
from dataclasses import dataclass, field
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


@dataclass
class DynamicTPDecision:
    """
    Decision output from the Dynamic TP Engine.
    
    The engine evaluates all available market data and produces:
    - A concrete TP price target (or 0 if suppressed)
    - Whether to use trailing instead of static TP
    - Trail parameters if trailing is recommended
    - The reasoning and confidence level
    """
    symbol: str
    side: str
    entry_price: float
    current_price: float
    
    # TP Decision
    tp_price: float
    tp_pct: float  # TP as % from entry
    tp_decision: str  # STATIC_TP, TRAIL_TP, SUPPRESS_TP, WIDEN_TP, TIGHTEN_TP
    
    # Trailing parameters (when tp_decision involves trailing)
    use_trailing: bool
    trail_activation_pct: float  # ROE % to activate trailing
    trail_distance_pct: float    # Trail distance as ROE %
    trail_callback_pct: float    # Callback trigger %
    
    # Market context that drove the decision
    volatility_regime: str       # LOW, MEDIUM, HIGH, EXTREME
    momentum_score: float        # -1.0 to 1.0 (aligned with position = positive)
    squeeze_potential: float     # 0.0 to 1.0
    microstructure_signal: str   # FAVORABLE, NEUTRAL, ADVERSE
    
    # Decision confidence and reasoning
    confidence: float            # 0.0 to 1.0
    reasons: List[str] = field(default_factory=list)
    features_used: int = 0
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'side': self.side,
            'entry_price': self.entry_price,
            'current_price': self.current_price,
            'tp_price': self.tp_price,
            'tp_pct': self.tp_pct,
            'tp_decision': self.tp_decision,
            'use_trailing': self.use_trailing,
            'trail_activation_pct': self.trail_activation_pct,
            'trail_distance_pct': self.trail_distance_pct,
            'trail_callback_pct': self.trail_callback_pct,
            'volatility_regime': self.volatility_regime,
            'momentum_score': self.momentum_score,
            'squeeze_potential': self.squeeze_potential,
            'microstructure_signal': self.microstructure_signal,
            'confidence': self.confidence,
            'reasons': self.reasons,
            'features_used': self.features_used,
        }


class DynamicTPEngine:
    """
    Intelligent Take Profit Engine.
    
    Instead of static % targets, this engine continuously evaluates:
    
    1. VOLATILITY (ATR, BBands, realized vol):
       - High vol → Wider TP targets (let winners run)
       - Low vol → Tighter TP targets (take profits quickly)
    
    2. MOMENTUM (MACD, RSI, ADX, price velocity):
       - Strong aligned momentum → Suppress static TP, use trailing
       - Weakening momentum → Tighten TP, take profits
       - Counter momentum → Emergency TP, exit now
    
    3. LIQUIDATION LEVELS (from CoinAnk/Binance):
       - Squeeze potential detected → Let position ride to liquidation cluster
       - Adverse liquidation cascade → Tighten TP before cascade hits
    
    4. MICROSTRUCTURE (order flow, spoofing, fast moves):
       - Favorable flow → Widen TP, more room to run
       - Spoofing detected → Tighten TP, protect gains
       - Fast move in our direction → Switch to trailing
    
    5. FUNDING & OI:
       - High funding against position → Tighten TP
       - OI increasing in our direction → Widen TP
    """
    
    def __init__(self, redis_client=None, account_id: str = "primary"):
        self.redis = redis_client
        self.account_id = account_id
        
        # Legacy anchors kept for fallback only (Addendum v3 uses distribution-driven TP)
        self.base_tp_pct = float(os.getenv("DYNAMIC_TP_BASE_PCT", "3.0"))
        self.min_tp_pct = float(os.getenv("DYNAMIC_TP_MIN_PCT", "1.5"))
        self.max_tp_pct = float(os.getenv("DYNAMIC_TP_MAX_PCT", "15.0"))
        
        # Trailing defaults (adjusted by market conditions)
        self.base_trail_activation = float(os.getenv("DYNAMIC_TP_TRAIL_ACTIVATION", "8.0"))  # 8% ROE (was 2% — too early)
        self.base_trail_distance = float(os.getenv("DYNAMIC_TP_TRAIL_DISTANCE", "5.0"))      # 5% ROE (was 1.5% — too tight)
        
        # Momentum regime: wider TP/trail when alt-season surges detected
        self._momentum_regime_cache: Dict[str, Tuple[bool, float]] = {}  # symbol -> (active, cached_ts)
        
        # Feature weights for TP calculation
        self.vol_weight = 0.30       # 30% volatility impact
        self.momentum_weight = 0.25  # 25% momentum impact  
        self.liq_weight = 0.20       # 20% liquidation impact
        self.micro_weight = 0.15     # 15% microstructure impact
        self.oi_weight = 0.10        # 10% OI/funding impact
        
        # Cache for expensive feature fetches
        # IMPORTANT: Keep this bounded. A time-bucketed cache key will grow without limit
        # (new key every TTL interval per symbol) and can lead to multi-GB RSS over time.
        # Cache format: symbol -> (features_dict, cached_ts)
        self._feature_cache: Dict[str, Tuple[Dict[str, float], float]] = {}
        self._cache_ttl = 10  # seconds
        self._cache_last_stats_ts = 0.0

        # In-memory rolling price history for range-aware TP tightening.
        # Key: "{account}:{symbol}" -> deque[(ts, price)]
        self._price_mem: Dict[str, Any] = {}
        
        logger.info(
            "DynamicTPEngine initialized | distribution_mode=on "
            f"| fallback_base={self.base_tp_pct}% min={self.min_tp_pct}% max={self.max_tp_pct}%"
        )

    # ──────────────────────────────────────────────────────────────────────
    # MOMENTUM REGIME DETECTION (Alt-Season Mode, Apr 2026)
    # Checks Redis flag set by trainer/trader for per-symbol momentum surge.
    # When active: raises TP cap, widens trail, extends ride-move, etc.
    # ──────────────────────────────────────────────────────────────────────
    def _is_momentum_regime(self, symbol: str) -> bool:
        """Check if symbol is in momentum regime (alt-season surge detected)."""
        try:
            from config import MOMENTUM_REGIME_ENABLED
            if not MOMENTUM_REGIME_ENABLED:
                return False
        except ImportError:
            return False

        # Cache for 30s to avoid Redis spam
        now = time.time()
        cached = self._momentum_regime_cache.get(symbol)
        if cached and (now - cached[1]) < 30.0:
            return cached[0]

        active = False
        if self.redis:
            try:
                flag = self.redis.get(f"wma:momentum_regime:{symbol}")
                active = bool(flag)
            except Exception:
                pass

        self._momentum_regime_cache[symbol] = (active, now)
        return active

    def _get_effective_tp_limits(self, symbol: str) -> Tuple[float, float]:
        """Return (min_tp_pct, max_tp_pct) adjusted for momentum regime."""
        if self._is_momentum_regime(symbol):
            try:
                from config import MOMENTUM_TP_MAX_PCT, MOMENTUM_TP_MIN_PCT
                return float(MOMENTUM_TP_MIN_PCT), float(MOMENTUM_TP_MAX_PCT)
            except ImportError:
                return self.min_tp_pct, 80.0  # safe fallback
        return self.min_tp_pct, self.max_tp_pct

    def _get_effective_trail_params(self, symbol: str, base_activation: float,
                                     base_distance: float, base_callback: float
                                     ) -> Tuple[float, float, float]:
        """Return (activation, distance, callback) adjusted for momentum regime."""
        if self._is_momentum_regime(symbol):
            try:
                from config import MOMENTUM_TRAIL_DISTANCE_MULT, MOMENTUM_TRAIL_ACTIVATION_MULT
                act_mult = float(MOMENTUM_TRAIL_ACTIVATION_MULT)
                dist_mult = float(MOMENTUM_TRAIL_DISTANCE_MULT)
            except ImportError:
                act_mult, dist_mult = 2.0, 2.5
            return (
                base_activation * act_mult,
                base_distance * dist_mult,
                base_callback * dist_mult,  # callback scales with distance
            )
        return base_activation, base_distance, base_callback
    
    def calculate_dynamic_tp(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        current_price: float,
        position_size_usd: float = 0,
        current_roi_pct: float = 0,
        existing_tp_price: float = 0,
        leverage: float = 0,
    ) -> DynamicTPDecision:
        """
        Calculate fully dynamic TP based on all available market data.
        
        This is the main entry point. Call this periodically (every cycle) to get
        updated TP recommendations that adapt to changing market conditions.
        
        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            side: LONG or SHORT
            entry_price: Position entry price
            current_price: Current mark price
            position_size_usd: Position notional value
            current_roi_pct: Current ROE % (for trailing decisions)
            existing_tp_price: Current TP price (to detect if update needed)
        
        Returns:
            DynamicTPDecision with recommended TP and reasoning
        """
        reasons = []
        
        # Fetch all market features
        features = self._fetch_all_features(symbol)
        features_used = len(features)
        
        # Inject leverage into features for trail calculations
        if leverage > 0:
            features['leverage'] = float(leverage)
        
        if features_used < 5:
            # Not enough data - use conservative defaults
            reasons.append("INSUFFICIENT_DATA")
            return self._create_fallback_decision(symbol, side, entry_price, current_price, reasons)
        
        # ====================================================================
        # 1. VOLATILITY ANALYSIS → Base TP Width
        # ====================================================================
        vol_multiplier, vol_regime, vol_reasons = self._analyze_volatility_for_tp(features)
        reasons.extend(vol_reasons)
        
        # ====================================================================
        # 2. MOMENTUM ANALYSIS → Trail vs Static TP
        # ====================================================================
        momentum_score, use_trailing, momentum_reasons = self._analyze_momentum_for_tp(
            symbol, side, features, current_roi_pct
        )
        reasons.extend(momentum_reasons)
        
        # ====================================================================
        # 3. LIQUIDATION ANALYSIS → Squeeze Potential
        # ====================================================================
        squeeze_potential, liq_adjustment, liq_reasons = self._analyze_liquidation_for_tp(
            symbol, side, current_price, features
        )
        reasons.extend(liq_reasons)
        
        # ====================================================================
        # 4. MICROSTRUCTURE ANALYSIS → Order Flow Signal
        # ====================================================================
        micro_signal, micro_adjustment, micro_reasons = self._analyze_microstructure_for_tp(
            symbol, side, features
        )
        reasons.extend(micro_reasons)
        
        # ====================================================================
        # 5. FUNDING & OI ANALYSIS → Pressure Direction
        # ====================================================================
        oi_adjustment, oi_reasons = self._analyze_oi_funding_for_tp(symbol, side, features)
        reasons.extend(oi_reasons)
        
        # ====================================================================
        # COMPUTE FINAL TP TARGET (Distribution-driven, Addendum v3)
        # ====================================================================
        adaptive_tp_pct = self._compute_tp_distribution(
            side=side,
            entry_price=entry_price,
            current_price=current_price,
            features=features,
            vol_multiplier=vol_multiplier,
            momentum_score=momentum_score,
            liq_adjustment=liq_adjustment,
            micro_adjustment=micro_adjustment,
            oi_adjustment=oi_adjustment,
            reasons=reasons,
        )
        
        # Calculate TP price
        if side == 'LONG':
            tp_price = entry_price * (1 + adaptive_tp_pct / 100)
        else:
            tp_price = entry_price * (1 - adaptive_tp_pct / 100)
        
        # Determine TP decision type — ALL SMOOTH, no hard thresholds
        # Every factor contributes continuously via tanh blending
        import math as _m_tp_dec
        use_trailing = True  # Always-on trailing as profit protection
        
        # Smooth blending of squeeze widen + momentum tighten + trail
        # Instead of if/else: compute continuous weights
        _trail_weight = _m_tp_dec.tanh((current_roi_pct - self.base_trail_activation) / 3.0)  # [-1,1]
        _squeeze_weight = squeeze_potential  # Already [0,1]
        _mom_tighten = max(0.0, -momentum_score)  # 0 when positive, up to 1 when very negative
        _mom_widen = max(0.0, momentum_score)  # 0 when negative, up to 1 when positive
        
        # Determine dominant signal for decision label
        if _trail_weight > 0.3:
            tp_decision = "TRAIL_TP"
            reasons.append(f"TRAILING_ACTIVE:ROI={current_roi_pct:.1f}% weight={_trail_weight:.2f}")
        elif _squeeze_weight > _mom_tighten and _squeeze_weight > 0.2:
            tp_decision = "WIDEN_TP"
        elif _mom_tighten > 0.25:
            tp_decision = "TIGHTEN_TP"
        elif _mom_widen > 0.3 and current_roi_pct > 0.5:
            tp_decision = "SUPPRESS_TP"
        else:
            tp_decision = "STATIC_TP"
        
        # Apply smooth adjustments (not gated by decision type)
        # Squeeze widen: continuous contribution proportional to squeeze_potential
        _squeeze_mult = 1.0 + _squeeze_weight * 0.40  # [1.0, 1.4]
        # Momentum tighten/widen: tanh-smoothed
        _mom_mult = 1.0 + _m_tp_dec.tanh(momentum_score * 1.2) * 0.20  # [0.80, 1.20]
        # Combined
        adaptive_tp_pct *= _squeeze_mult * _mom_mult
        tp_price = entry_price * (1 + adaptive_tp_pct / 100) if side == 'LONG' else entry_price * (1 - adaptive_tp_pct / 100)
        reasons.append(f"TP_BLEND:squeeze_m={_squeeze_mult:.3f} mom_m={_mom_mult:.3f}")

        # ====================================================================
        # TRAINER INTENT TP DEFERENCE (gate TIGHTEN decisions)
        # If position aligns with trainer's high-confidence directional intent,
        # override TIGHTEN_TP → STATIC_TP (no tightening) and skip RANGE_TIGHTEN.
        # This prevents the dynamic TP engine from tightening TP against the
        # trainer's view, which causes premature closes.
        # ====================================================================
        _trainer_intent_aligned = False
        try:
            from config import TRAINER_INTENT_TP_DEFERENCE_ENABLED, TRAINER_INTENT_TP_MIN_CONFIDENCE
            if bool(TRAINER_INTENT_TP_DEFERENCE_ENABLED) and self.redis:
                from risk.trainer_intent import get_intent
                _ti = get_intent(self.redis, symbol)
                if (_ti is not None
                    and not _ti.is_stale
                    and _ti.is_directional
                    and _ti.confidence >= float(TRAINER_INTENT_TP_MIN_CONFIDENCE)
                    and _ti.aligns_with_position(side)):
                    _trainer_intent_aligned = True
                    if tp_decision == "TIGHTEN_TP":
                        # Revert tightening — trainer still wants this direction
                        tp_decision = "STATIC_TP"
                        adaptive_tp_pct = self._compute_tp_distribution(
                            side=side, entry_price=entry_price, current_price=current_price,
                            features=features, vol_multiplier=vol_multiplier,
                            momentum_score=momentum_score, liq_adjustment=liq_adjustment,
                            micro_adjustment=micro_adjustment, oi_adjustment=oi_adjustment,
                            reasons=[],
                        )
                        if side == 'LONG':
                            tp_price = entry_price * (1 + adaptive_tp_pct / 100)
                        else:
                            tp_price = entry_price * (1 - adaptive_tp_pct / 100)
                        reasons.append(
                            f"TRAINER_INTENT_OVERRIDE_TIGHTEN:dir={_ti.direction} "
                            f"conf={_ti.confidence:.2f} age={_ti.age_seconds:.0f}s"
                        )
                        logger.info(
                            "DYNAMIC_TP_INTENT_OVERRIDE | sym=%s side=%s | "
                            "TIGHTEN→STATIC_TP | trainer_dir=%s conf=%.3f",
                            symbol, side, _ti.direction, _ti.confidence,
                        )
        except Exception as _ti_err:
            logger.debug("DYNAMIC_TP_INTENT_CHECK | error: %s", _ti_err)

        # ====================================================================
        # TRAINER PREDICTION ALIGNMENT (Mar 2026): Use actual prediction data
        # to refine TP when trainer_intent keys are not populated.
        # ====================================================================
        if not _trainer_intent_aligned:
            try:
                from risk.trainer_alignment import get_trainer_view
                _tv = get_trainer_view(self.redis, symbol) if self.redis else None
                if _tv and not _tv.stale and _tv.is_directional:
                    if _tv.consensus_direction == side and _tv.consensus_confidence > 0.3:
                        _trainer_intent_aligned = True
                        if tp_decision == "TIGHTEN_TP":
                            tp_decision = "STATIC_TP"
                            reasons.append(
                                f"TRAINER_PRED_OVERRIDE_TIGHTEN:dir={_tv.consensus_direction} "
                                f"conf={_tv.consensus_confidence:.2f}"
                            )
                    if _tv.best_target_price > 0 and side in ("LONG", "SHORT"):
                        _tw = min(0.70, 0.20 + 0.50 * max(0.0, min(1.0, _tv.consensus_confidence)))
                        _dw = 1.0 - _tw
                        if side == "LONG" and _tv.best_target_price > tp_price and tp_price > 0:
                            tp_price = tp_price * _dw + _tv.best_target_price * _tw
                            reasons.append(f"TP_BLEND_TRAINER_TARGET:{_tv.best_target_price:.6f}_w={_tw:.2f}")
                        elif side == "SHORT" and _tv.best_target_price < tp_price and tp_price > 0:
                            tp_price = tp_price * _dw + _tv.best_target_price * _tw
                            reasons.append(f"TP_BLEND_TRAINER_TARGET:{_tv.best_target_price:.6f}_w={_tw:.2f}")
            except Exception as _ta_err:
                logger.debug("DYNAMIC_TP_TRAINER_ALIGN | error: %s", _ta_err)

        # ====================================================================
        # RANGE-AWARE TP TIGHTENING (Jan 2026, Adaptive v2):
        # Fully adaptive to live market data: ATR, ADX, regime, liq clusters,
        # microstructure. No static thresholds — all derived from data.
        # - Choppy/ranging: tighten near range extreme (capture small profits)
        # - Trending/breakout: skip tightening (hold for big moves)
        # - Favorable liq clusters nearby: skip (potential cascade in our favor)
        # ====================================================================
        try:
            # ── Kill switch: revert to legacy behavior if disabled ──
            _adaptive_rt_enabled = True
            try:
                from config import ADAPTIVE_RANGE_TIGHTEN_ENABLED
                _adaptive_rt_enabled = bool(ADAPTIVE_RANGE_TIGHTEN_ENABLED)
            except Exception:
                pass

            k = f"{str(self.account_id).lower()}:{str(symbol).upper()}"
            dq = self._price_mem.get(k)
            if dq is None:
                dq = deque(maxlen=420)  # ~3.5h at 30s cadence
                self._price_mem[k] = dq
            now = time.time()
            if current_price and current_price > 0:
                dq.append((now, float(current_price)))
            try:
                win_sec = int(os.getenv("DYNAMIC_TP_RANGE_WINDOW_SEC", "7200"))
            except Exception:
                win_sec = 7200
            win_sec = max(900, min(6 * 3600, int(win_sec)))
            while dq and (now - float(dq[0][0])) > win_sec:
                dq.popleft()
            vals = [float(p) for (_t, p) in dq if p and p > 0]

            # ── Fetch live market data for adaptive thresholds ──
            _adx_rt = 0.0
            _atr_pct_rt = 0.0
            _regime_rt = "UNKNOWN"
            _liq_boost_rt = 0.0
            _fast_move_rt = 0.0
            _is_long_rt = (str(side).upper() == "LONG")

            if _adaptive_rt_enabled and self.redis:
                # Regime
                try:
                    _regime_raw_rt = self.redis.get(f"regime:{symbol}")
                    if _regime_raw_rt:
                        import json as _json_rt
                        _regime_data_rt = _json_rt.loads(
                            _regime_raw_rt.decode("utf-8") if isinstance(_regime_raw_rt, (bytes, bytearray)) else str(_regime_raw_rt)
                        )
                        _regime_rt = str(_regime_data_rt.get("move_regime", "UNKNOWN")).upper()
                except Exception:
                    pass

                # ATR, ADX from unified features
                for _tf_rt in ("15m", "5m", "1h"):
                    try:
                        _feat_raw_rt = self.redis.hgetall(f"unified_features:{symbol}:{_tf_rt}")
                        if not _feat_raw_rt:
                            continue
                        _feat_rt = {(kk.decode() if isinstance(kk, bytes) else kk): (vv.decode() if isinstance(vv, bytes) else vv) for kk, vv in _feat_raw_rt.items()}
                        for _kn in ("ta_ADX_14", "ta_ADX_21", "adx_14", "adx"):
                            _v = float(_feat_rt.get(_kn, 0) or 0)
                            if _v > _adx_rt:
                                _adx_rt = _v
                        for _kn in ("atr_pct", "atr_14", "ind_ta_NATR_14"):
                            _v = float(_feat_rt.get(_kn, 0) or 0)
                            if _v > _atr_pct_rt:
                                _atr_pct_rt = _v
                        # Liq clusters (opposite side = favorable)
                        _ld_k = "liquidation_short_distance_pct" if _is_long_rt else "liquidation_long_distance_pct"
                        _ls_k = "liquidation_short_strength" if _is_long_rt else "liquidation_long_strength"
                        _ld = float(_feat_rt.get(_ld_k, 100) or 100)
                        _ls = float(_feat_rt.get(_ls_k, 0) or 0)
                        if _ld < 3.0 and _ls > 0.3:
                            _liq_boost_rt = max(_liq_boost_rt, min(0.5, (3.0 - _ld) / 3.0 * _ls))
                    except Exception:
                        continue

                # Microstructure fast_move
                try:
                    _msnap_raw_rt = self.redis.hgetall(f"msnap:coinapi_wsds:{symbol}")
                    if _msnap_raw_rt:
                        _msnap_rt = {(kk.decode() if isinstance(kk, bytes) else kk): (vv.decode() if isinstance(vv, bytes) else vv) for kk, vv in _msnap_raw_rt.items()}
                        _fast_move_rt = float(_msnap_rt.get("fast_move_score", 0) or 0)
                except Exception:
                    pass

            # ── Adaptive decision: should we even attempt range tightening? ──
            # Skip if: strong trend, breakout regime, favorable liq, or fast move
            _skip_range_tighten = False
            if _adaptive_rt_enabled:
                # Smooth skip probability: high ADX, trending regime, liq boost, fast move
                # Each contributes via tanh; sum > 0.5 → skip
                import math as _m_rt
                _skip_score = (
                    _m_rt.tanh((_adx_rt - 20.0) / 8.0) * 0.35  # ADX contribution
                    + (0.30 if _regime_rt in ("TRENDING", "BREAKOUT", "FAST", "IMPULSE") else 0.0)
                    + _m_rt.tanh(_liq_boost_rt * 3.0) * 0.20  # Liq cluster nearby
                    + _m_rt.tanh(_fast_move_rt * 2.0) * 0.15  # Fast move
                )
                _skip_range_tighten = _skip_score > 0.40

            # ── Adaptive momentum bounds (data-driven, not static) ──
            # Low ADX → only tighten in truly flat conditions (tight momentum window)
            # Higher ADX → wider window but skip_range_tighten will catch strong trends
            if _adaptive_rt_enabled and _adx_rt > 0:
                _mom_bound_rt = min(0.50, max(0.20, 0.25 + (25.0 - min(_adx_rt, 25.0)) / 50.0))
            else:
                _mom_bound_rt = 0.45  # legacy fallback

            # ── Adaptive minimum ROI (ATR-scaled, not static 0.2%) ──
            # Low-vol (ATR 0.3%): min_roi ~0.15% (capture small profits in calm)
            # Med-vol (ATR 1.5%): min_roi ~0.45% (need meaningful profit)
            # High-vol (ATR 4%): min_roi ~1.2% (hold through noise)
            if _adaptive_rt_enabled and _atr_pct_rt > 0:
                _adaptive_min_roi = max(0.30, _atr_pct_rt * 0.5)  # Raised floor from 0.15 to 0.30, factor from 0.3 to 0.5
            else:
                _adaptive_min_roi = 0.8  # safe fallback if no ATR data (was 0.5 — too easy to trigger)

            if (len(vals) >= 20
                    and not _skip_range_tighten
                    and float(momentum_score) < _mom_bound_rt
                    and float(momentum_score) > -_mom_bound_rt
                    and not use_trailing):
                hi = max(vals)
                lo = min(vals)
                mid = (hi + lo) / 2.0 if (hi > 0 and lo > 0) else 0.0
                if mid > 0 and hi > lo:
                    rng_pct = ((hi - lo) / mid) * 100.0
                    # Adaptive min range width: scale with ATR (low-vol → smaller range is significant)
                    if _adaptive_rt_enabled and _atr_pct_rt > 0:
                        _min_rng_rt = max(0.30, _atr_pct_rt * 0.6)
                    else:
                        try:
                            _min_rng_rt = float(os.getenv("DYNAMIC_TP_RANGE_MIN_WIDTH_PCT", "1.20"))
                        except Exception:
                            _min_rng_rt = 1.20
                    _min_rng_rt = max(0.30, min(10.0, float(_min_rng_rt)))
                    if float(rng_pct) >= float(_min_rng_rt):
                        pos = (float(current_price) - float(lo)) / (float(hi) - float(lo))
                        pos = max(0.0, min(1.0, float(pos)))
                        eps = float(os.getenv("DYNAMIC_TP_RANGE_EPS", "0.001"))  # 0.1% inside the extreme
                        eps = max(0.0, min(0.01, float(eps)))

                        # TRAINER INTENT GATE: Skip range tightening if aligned
                        if _trainer_intent_aligned:
                            reasons.append("RANGE_TIGHTEN_SKIPPED:trainer_intent_aligned")
                            logger.debug(
                                "DYNAMIC_TP_RANGE_SKIP | sym=%s side=%s | "
                                "range tightening suppressed by trainer intent",
                                symbol, side,
                            )
                        else:
                            if str(side).upper() == "LONG" and pos >= 0.70 and current_roi_pct > _adaptive_min_roi:
                                tight_tp = float(hi) * (1.0 - eps)
                                if tight_tp > 0 and tight_tp < float(tp_price):
                                    tp_price = float(tight_tp)
                                    adaptive_tp_pct = max(self.min_tp_pct, ((tp_price / entry_price) - 1.0) * 100.0)
                                    tp_decision = "TIGHTEN_TP"
                                    reasons.append(
                                        f"RANGE_TIGHTEN:hi={hi:.2f} pos={pos:.2f} rng={rng_pct:.2f}% "
                                        f"adx={_adx_rt:.1f} atr={_atr_pct_rt:.3f}% min_roi={_adaptive_min_roi:.3f}"
                                    )

                            if str(side).upper() == "SHORT" and pos <= 0.30 and current_roi_pct > _adaptive_min_roi:
                                tight_tp = float(lo) * (1.0 + eps)
                                if tight_tp > 0 and tight_tp > float(tp_price):
                                    tp_price = float(tight_tp)
                                    adaptive_tp_pct = max(self.min_tp_pct, (1.0 - (tp_price / entry_price)) * 100.0)
                                    tp_decision = "TIGHTEN_TP"
                                    reasons.append(
                                        f"RANGE_TIGHTEN:lo={lo:.2f} pos={pos:.2f} rng={rng_pct:.2f}% "
                                        f"adx={_adx_rt:.1f} atr={_atr_pct_rt:.3f}% min_roi={_adaptive_min_roi:.3f}"
                                    )
        except Exception:
            pass
        
        # Calculate trailing parameters — ADAPTIVE to leverage and stress
        # Higher leverage = position more sensitive to price moves = lower ROE activation
        _lev_for_trail = float(features.get('leverage', 20) or 20)
        if _lev_for_trail < 1:
            _lev_for_trail = 20.0
        # Leverage scaling: at 10x base stays, at 75x reduce by ~60%
        # Formula: scale = (reference_lev / actual_lev) ^ 0.4
        _lev_trail_scale = min(1.5, max(0.3, (20.0 / _lev_for_trail) ** 0.4))
        
        trail_activation = self.base_trail_activation * _lev_trail_scale * (1.0 + (vol_multiplier - 1.0) * 0.3)
        # STRESS-AWARE: Smooth momentum adjustment — no threshold gates
        # Negative momentum → lower activation (arm earlier to protect)
        # Positive momentum → slightly raise (give room to run)
        import math as _m_trail
        _stress_activation = 1.0 + _m_trail.tanh(momentum_score * 1.5) * 0.25  # [0.75, 1.25]
        trail_activation *= _stress_activation
        trail_activation = max(2.0, min(15.0, trail_activation))
        
        trail_distance = self.base_trail_distance * _lev_trail_scale * vol_multiplier
        # STRESS-AWARE: Smooth — negative momentum tightens, positive widens
        _stress_distance = 1.0 + _m_trail.tanh(momentum_score * 1.2) * 0.20  # [0.80, 1.20]
        trail_distance *= _stress_distance
        trail_distance = max(1.5, min(10.0, trail_distance))
        
        # Widen trailing when trainer intent aligns (let position ride further)
        if _trainer_intent_aligned:
            try:
                from config import TRAINER_INTENT_TRAIL_WIDEN_MULT
                _widen = float(TRAINER_INTENT_TRAIL_WIDEN_MULT)
            except Exception:
                _widen = 1.8
            trail_distance *= _widen
            trail_distance = min(20.0, trail_distance)  # Cap at 20% ROE (was 8% — too restrictive)
            reasons.append(f"TRAIL_WIDENED_BY_INTENT:x{_widen:.1f}")
        
        trail_callback = trail_distance * 0.5  # 50% of distance
        
        # ── MOMENTUM REGIME BOOST (Alt-Season, Apr 2026) ──
        # When momentum regime is active for this symbol, widen all TP/trail params
        if self._is_momentum_regime(symbol):
            _eff_min_tp, _eff_max_tp = self._get_effective_tp_limits(symbol)
            # Re-clamp TP to wider limits
            adaptive_tp_pct = max(_eff_min_tp, min(_eff_max_tp, adaptive_tp_pct))
            # Recalculate TP price with wider TP
            if side == 'LONG':
                tp_price = entry_price * (1 + adaptive_tp_pct / 100)
            else:
                tp_price = entry_price * (1 - adaptive_tp_pct / 100)
            # Widen trail params
            trail_activation, trail_distance, trail_callback = self._get_effective_trail_params(
                symbol, trail_activation, trail_distance, trail_callback
            )
            # Extend clamp ranges
            trail_activation = max(2.0, min(40.0, trail_activation))
            trail_distance = max(1.5, min(25.0, trail_distance))
            reasons.append(f"MOMENTUM_REGIME:tp_max={_eff_max_tp:.0f}% trail_dist={trail_distance:.1f}%")
            logger.info(
                "🚀 MOMENTUM_REGIME_TP | sym=%s side=%s | tp=%.1f%% trail_act=%.1f%% trail_dist=%.1f%% | "
                "letting winners run wider",
                symbol, side, adaptive_tp_pct, trail_activation, trail_distance,
            )

        # ====================================================================
        # MARKET INTELLIGENCE MULTIPLIER (Apr 2026)
        # Final adjustment based on unified market context:
        # liq clusters, trend, momentum, orderbook, funding, spoof risk
        # Extends TP when market favors continuation, tightens when adverse.
        # ====================================================================
        _mi_ctx = None
        try:
            from trading.market_intelligence import get_adaptive_tp_multiplier, get_market_context
            _mi_mult, _mi_reason = get_adaptive_tp_multiplier(
                self.redis, symbol, side,
            )
            if abs(_mi_mult - 1.0) > 0.05:  # Only apply if meaningful
                _old_tp_pct = adaptive_tp_pct
                adaptive_tp_pct *= _mi_mult
                adaptive_tp_pct = max(0.5, min(25.0, adaptive_tp_pct))
                if side == 'LONG':
                    tp_price = entry_price * (1 + adaptive_tp_pct / 100)
                else:
                    tp_price = entry_price * (1 - adaptive_tp_pct / 100)
                # Also scale trail distance
                trail_distance *= min(2.0, max(0.5, _mi_mult))
                trail_distance = max(1.5, min(25.0, trail_distance))
                reasons.append(
                    f"INTEL_TP_MULT:{_mi_mult:.2f}x ({_old_tp_pct:.1f}→{adaptive_tp_pct:.1f}%) | {_mi_reason}"
                )
                logger.info(
                    "🧠 INTEL_TP_ADJUST | sym=%s side=%s | mult=%.2f | "
                    "tp %.1f%%→%.1f%% trail_dist=%.1f%% | %s",
                    symbol, side, _mi_mult, _old_tp_pct, adaptive_tp_pct,
                    trail_distance, _mi_reason,
                )

            # ── DEEP MI CONTEXT: tape, orderbook, reversal risk, spoof ──
            # Consult full MarketContext for nuanced TP adjustments
            _mi_ctx = get_market_context(self.redis, symbol, position_side=side)
            if _mi_ctx and not _mi_ctx.is_stale:
                _side_mult = 1.0 if side.upper() == "LONG" else -1.0

                # Tape pressure aligned = let TP run wider
                _tape_favor = _mi_ctx.tape_pressure * _side_mult
                if _tape_favor > 0.3:
                    _tape_widen = 1.0 + min(0.15, _tape_favor * 0.2)
                    adaptive_tp_pct *= _tape_widen
                    trail_distance *= _tape_widen
                    reasons.append(f"TAPE_WIDEN:{_tape_widen:.2f}x tape={_tape_favor:.2f}")

                # Orderbook pressure aligned (and no spoof) = widen TP
                _ob_favor = _mi_ctx.orderbook_pressure * _side_mult
                if _ob_favor > 0.2 and _mi_ctx.spoof_risk < 0.3:
                    _ob_widen = 1.0 + min(0.10, _ob_favor * 0.15)
                    adaptive_tp_pct *= _ob_widen
                    reasons.append(f"OB_WIDEN:{_ob_widen:.2f}x ob={_ob_favor:.2f}")
                elif _mi_ctx.spoof_risk > 0.5:
                    # Spoof detected: tighten TP — book is unreliable
                    _spoof_tight = max(0.85, 1.0 - _mi_ctx.spoof_risk * 0.2)
                    adaptive_tp_pct *= _spoof_tight
                    reasons.append(f"SPOOF_TIGHT:{_spoof_tight:.2f}x risk={_mi_ctx.spoof_risk:.2f}")

                # Reversal risk: high reversal → tighten TP to lock profits sooner
                if _mi_ctx.reversal_risk > 0.45 and current_roi_pct > 0.5:
                    _rev_tight = max(0.80, 1.0 - _mi_ctx.reversal_risk * 0.25)
                    adaptive_tp_pct *= _rev_tight
                    trail_distance *= _rev_tight
                    reasons.append(f"REVERSAL_TIGHT:{_rev_tight:.2f}x rev={_mi_ctx.reversal_risk:.2f}")

                # Recalc TP price after all MI adjustments
                adaptive_tp_pct = max(0.5, min(25.0, adaptive_tp_pct))
                trail_distance = max(1.5, min(25.0, trail_distance))
                if side == 'LONG':
                    tp_price = entry_price * (1 + adaptive_tp_pct / 100)
                else:
                    tp_price = entry_price * (1 - adaptive_tp_pct / 100)
        except ImportError:
            pass
        except Exception as _mi_tp_err:
            logger.debug("INTEL_TP_ERR | %s | %s", symbol, _mi_tp_err)

        # Confidence based on data quality and signal alignment
        confidence = min(1.0, features_used / 20.0)  # More features = more confidence
        if momentum_score > 0.3 and micro_signal == "FAVORABLE":
            confidence = min(1.0, confidence + 0.2)
        
        decision = DynamicTPDecision(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            current_price=current_price,
            tp_price=tp_price,
            tp_pct=adaptive_tp_pct,
            tp_decision=tp_decision,
            use_trailing=use_trailing,
            trail_activation_pct=trail_activation,
            trail_distance_pct=trail_distance,
            trail_callback_pct=trail_callback,
            volatility_regime=vol_regime,
            momentum_score=momentum_score,
            squeeze_potential=squeeze_potential,
            microstructure_signal=micro_signal,
            confidence=confidence,
            reasons=reasons,
            features_used=features_used,
        )
        try:
            from config import DECISION_TRACE_ENABLED, DECISION_TRACE_STREAM
        except Exception:
            DECISION_TRACE_ENABLED = False
            DECISION_TRACE_STREAM = "wma:traces"
        if DECISION_TRACE_ENABLED and self.redis:
            try:
                from rl.decision_trace import build_trace, emit_trace
                trace = build_trace(
                    trace_id=None,
                    account_id=str(self.account_id),
                    symbol=str(symbol),
                    phase="DYNAMIC_TP",
                    module="dynamic_tp_engine",
                    payload={
                        "side": side,
                        "tp_pct": decision.tp_pct,
                        "tp_price": decision.tp_price,
                        "decision": decision.tp_decision,
                        "trail_activation": decision.trail_activation_pct,
                        "trail_distance": decision.trail_distance_pct,
                        "reasons": decision.reasons[:10],
                    },
                )
                emit_trace(self.redis, stream=str(DECISION_TRACE_STREAM), trace=trace)
            except Exception:
                pass
        return decision

    def apply_exit_profile_scaling(self, decision: 'DynamicTPDecision', exit_profile: dict) -> 'DynamicTPDecision':
        """Apply TF-scaled exit profile multipliers to a DynamicTPDecision.
        
        The exit_profile comes from the trainer signal and contains per-TF scaling:
          tp_mult: scales TP% (>1 = wider target for HTF, <1 = tighter for LTF)
          trail_mult: scales trail distance (>1 = more room to breathe)
          trail_activation_mult: scales trail activation threshold
          min_hold_sec: minimum hold time (informational, used by trader hold logic)
          htf_aligned: whether signal aligns with 4h bias (additional widening)
        
        Backward compatible: if exit_profile is None/empty, returns decision unchanged.
        Kill switch: TF_EXIT_PROFILE_ENABLED in config (checked by caller).
        
        Args:
            decision: DynamicTPDecision from calculate_dynamic_tp()
            exit_profile: dict from signal payload's "exit_profile" key
            
        Returns:
            Modified DynamicTPDecision with scaled TP/trail params
        """
        if not exit_profile or not isinstance(exit_profile, dict):
            return decision
        
        try:
            tp_mult = float(exit_profile.get("tp_mult", 1.0))
            trail_mult = float(exit_profile.get("trail_mult", 1.0))
            activation_mult = float(exit_profile.get("trail_activation_mult", 1.0))
            
            # Clamp multipliers to sane range to prevent runaway values
            tp_mult = max(0.3, min(3.0, tp_mult))
            trail_mult = max(0.3, min(3.0, trail_mult))
            activation_mult = max(0.5, min(2.0, activation_mult))
            
            # Scale TP%
            new_tp_pct = decision.tp_pct * tp_mult
            _eff_min_tp, _eff_max_tp = self._get_effective_tp_limits(decision.symbol)
            new_tp_pct = max(_eff_min_tp, min(_eff_max_tp, new_tp_pct))
            
            # Recalculate TP price from scaled %
            if decision.side == 'LONG':
                new_tp_price = decision.entry_price * (1 + new_tp_pct / 100)
            else:
                new_tp_price = decision.entry_price * (1 - new_tp_pct / 100)
            
            # Scale trailing params
            new_trail_distance = decision.trail_distance_pct * trail_mult
            new_trail_distance = max(0.5, min(10.0, new_trail_distance))
            
            new_trail_activation = decision.trail_activation_pct * activation_mult
            new_trail_activation = max(1.0, min(8.0, new_trail_activation))
            
            new_trail_callback = new_trail_distance * 0.5  # Maintain 50% ratio
            
            # Build scaled reasons
            scaled_reasons = list(decision.reasons)
            scaled_reasons.append(
                f"TF_EXIT_PROFILE:tp_mult={tp_mult:.2f},trail_mult={trail_mult:.2f},"
                f"htf_aligned={exit_profile.get('htf_aligned', False)}"
            )
            
            logger.debug(
                f"[TF_EXIT_SCALE] {decision.symbol} {decision.side}: "
                f"tp={decision.tp_pct:.1f}%→{new_tp_pct:.1f}% "
                f"trail_dist={decision.trail_distance_pct:.1f}%→{new_trail_distance:.1f}% "
                f"trail_act={decision.trail_activation_pct:.1f}%→{new_trail_activation:.1f}% "
                f"| profile={exit_profile.get('description', 'unknown')}"
            )
            
            return DynamicTPDecision(
                symbol=decision.symbol,
                side=decision.side,
                entry_price=decision.entry_price,
                current_price=decision.current_price,
                tp_price=new_tp_price,
                tp_pct=new_tp_pct,
                tp_decision=decision.tp_decision,
                use_trailing=decision.use_trailing,
                trail_activation_pct=new_trail_activation,
                trail_distance_pct=new_trail_distance,
                trail_callback_pct=new_trail_callback,
                volatility_regime=decision.volatility_regime,
                momentum_score=decision.momentum_score,
                squeeze_potential=decision.squeeze_potential,
                microstructure_signal=decision.microstructure_signal,
                confidence=decision.confidence,
                reasons=scaled_reasons,
                features_used=decision.features_used,
            )
        except Exception as e:
            logger.warning(f"[TF_EXIT_SCALE] Error scaling {decision.symbol}: {e}")
            return decision  # Fail-safe: return unmodified

    def _compute_tp_distribution(
        self,
        *,
        side: str,
        entry_price: float,
        current_price: float,
        features: Dict[str, float],
        vol_multiplier: float,
        momentum_score: float,
        liq_adjustment: float,
        micro_adjustment: float,
        oi_adjustment: float,
        reasons: List[str],
    ) -> float:
        """
        Distribution-based TP sizing (Addendum v3).
        Uses ATR / vol / liquidation distance to derive TP without static anchors.
        """
        px = float(current_price or entry_price or 0.0)
        if px <= 0:
            reasons.append("TP_DISTRIBUTION_FALLBACK_PRICE")
            return max(self.min_tp_pct, min(self.max_tp_pct, self.base_tp_pct))

        def _pct(val: float) -> float:
            return max(0.0, float(val or 0.0))

        # Primary dispersion signals
        atr_pct = _pct(features.get("atr_pct"))
        if atr_pct <= 0 and features.get("atr"):
            atr_pct = _pct(features.get("atr")) / px * 100.0
        if atr_pct <= 0 and features.get("atr_14"):
            atr_pct = _pct(features.get("atr_14")) / px * 100.0
        vol_pct = _pct(features.get("volatility_1h") or features.get("volatility"))
        bb_width_pct = _pct(features.get("bb_width_pct"))
        if bb_width_pct <= 0 and features.get("bb_width"):
            bb_width_pct = _pct(features.get("bb_width"))
            if bb_width_pct < 1.0:
                bb_width_pct *= 100.0

        # Base distribution estimate
        candidates = [c for c in (atr_pct * 1.4, vol_pct * 1.0, bb_width_pct * 0.7) if c > 0]
        base_tp = sum(candidates) / max(1, len(candidates)) if candidates else 0.0

        if base_tp <= 0:
            reasons.append("TP_DISTRIBUTION_FALLBACK_BASE")
            return max(self.min_tp_pct, min(self.max_tp_pct, self.base_tp_pct))

        # Context adjustments (continuation vs micro/tox)
        cont = _pct(features.get("continuation_risk"))
        tox = _pct(features.get("toxicity"))
        cont_adj = 1.0 + min(0.35, cont * 0.4)
        tox_adj = 1.0 - min(0.25, tox * 0.35)

        # Include other analysis adjustments (bounded)
        combined = (
            vol_multiplier * self.vol_weight +
            (1.0 + momentum_score * 0.3) * self.momentum_weight +
            liq_adjustment * self.liq_weight +
            micro_adjustment * self.micro_weight +
            oi_adjustment * self.oi_weight
        )
        combined = max(0.8, min(1.6, combined))

        tp_pct = base_tp * combined * cont_adj * tox_adj

        # Cap TP by nearest liquidation clusters if present
        liq_cap_pct = None
        try:
            if side == "LONG":
                liq_short = float(features.get("liq_short_level") or 0.0)
                if liq_short > px:
                    liq_cap_pct = ((liq_short - px) / px) * 100.0
            else:
                liq_long = float(features.get("liq_long_level") or 0.0)
                if liq_long > 0 and liq_long < px:
                    liq_cap_pct = ((px - liq_long) / px) * 100.0
        except Exception:
            liq_cap_pct = None

        if liq_cap_pct and liq_cap_pct > 0:
            tp_pct = min(tp_pct, liq_cap_pct * 0.85)
            reasons.append(f"TP_LIQ_CAP:{liq_cap_pct:.2f}%")

        # Guardrails (distribution-based, not static anchors)
        tp_pct = max(0.75, min(20.0, tp_pct))
        reasons.append(f"TP_DISTRIBUTION:{tp_pct:.2f}%")
        return tp_pct
    
    def _fetch_all_features(self, symbol: str) -> Dict[str, float]:
        """
        Fetch ALL available market features for this symbol.
        
        Sources (in priority order):
        1. unified_features:{symbol}:{tf} - comprehensive feature set
        2. msnap:coinapi_wsds:{symbol} - real-time microstructure
        3. binance_liq:{symbol} - liquidation data
        4. coinank_features:{symbol} - funding/OI from CoinAnk
        """
        now = time.time()
        sym = str(symbol or "").upper().strip()
        cached = self._feature_cache.get(sym)
        if cached:
            cached_features, cached_ts = cached
            if (now - cached_ts) < float(self._cache_ttl):
                return cached_features
        
        features = {}
        
        if not self.redis:
            return features
        
        try:
            # 1. Unified features (200+ features across timeframes)
            for tf in ['5m', '15m', '1h', '4h']:
                key = f"unified_features:{symbol}:{tf}"
                try:
                    raw_data = self.redis.hgetall(key)
                    if raw_data:
                        if isinstance(list(raw_data.keys())[0], bytes):
                            raw_data = {k.decode('utf-8'): v.decode('utf-8') for k, v in raw_data.items()}
                        
                        # Extract all numeric features
                        for field, val in raw_data.items():
                            if field not in features:  # Prefer shorter TF
                                try:
                                    features[f"{field}_{tf}"] = float(val)
                                    features[field] = float(val)  # Also store without TF suffix
                                except:
                                    pass
                except Exception as e:
                    logger.debug(f"Error fetching unified_features for {symbol}:{tf}: {e}")
            
            # 2. Microstructure from msnap
            try:
                msnap_key = f"msnap:coinapi_wsds:{symbol}"
                msnap_data = self.redis.hgetall(msnap_key)
                if msnap_data:
                    if isinstance(list(msnap_data.keys())[0], bytes):
                        msnap_data = {k.decode('utf-8'): v.decode('utf-8') for k, v in msnap_data.items()}
                    for field in ['bid_ask_imbalance', 'order_flow_imbalance', 'spread_bps', 
                                  'spoof_score', 'fast_move_score', 'trade_intensity']:
                        if field in msnap_data:
                            try:
                                features[f"msnap_{field}"] = float(msnap_data[field])
                            except:
                                pass
            except Exception as e:
                logger.debug(f"Error fetching msnap for {symbol}: {e}")
            
            # 3. Liquidation data
            try:
                liq_key = f"binance_liq:{symbol}"
                liq_data = self.redis.hgetall(liq_key)
                if liq_data:
                    if isinstance(list(liq_data.keys())[0], bytes):
                        liq_data = {k.decode('utf-8'): v.decode('utf-8') for k, v in liq_data.items()}
                    for field in ['liq_long_level', 'liq_short_level', 'liq_long_strength', 
                                  'liq_short_strength', 'liq_ratio', 'liq_volume_long', 'liq_volume_short']:
                        if field in liq_data:
                            try:
                                features[field] = float(liq_data[field])
                            except:
                                pass
            except Exception as e:
                logger.debug(f"Error fetching liq data for {symbol}: {e}")
            
            # 4. CoinAnk features (funding, OI)
            try:
                coinank_key = f"coinank:{symbol}"
                coinank_data = self.redis.hgetall(coinank_key)
                if coinank_data:
                    if isinstance(list(coinank_data.keys())[0], bytes):
                        coinank_data = {k.decode('utf-8'): v.decode('utf-8') for k, v in coinank_data.items()}
                    for field in ['funding_rate', 'open_interest', 'oi_change_24h', 'long_short_ratio']:
                        if field in coinank_data:
                            try:
                                features[f"coinank_{field}"] = float(coinank_data[field])
                            except:
                                pass
            except Exception as e:
                logger.debug(f"Error fetching coinank for {symbol}: {e}")
            
            # Cache the result (bounded per symbol)
            self._feature_cache[sym] = (features, now)
            # Defensive bound: if symbols list ever explodes, cap cache size.
            # Evict oldest entries (simple O(n) scan; safe due to small expected size).
            max_entries = int(os.getenv("DYNAMIC_TP_FEATURE_CACHE_MAX", "500"))
            if max_entries > 0 and len(self._feature_cache) > max_entries:
                try:
                    oldest_sym, _ = min(self._feature_cache.items(), key=lambda kv: kv[1][1])
                    self._feature_cache.pop(oldest_sym, None)
                except Exception:
                    pass

            # Optional proof log for cache growth (default OFF)
            if os.getenv("DYNAMIC_TP_LOG_CACHE_STATS", "false").lower() in ("1", "true", "yes", "on"):
                stats_interval_s = float(os.getenv("DYNAMIC_TP_CACHE_STATS_INTERVAL_S", "300"))
                if (now - float(self._cache_last_stats_ts or 0.0)) >= stats_interval_s:
                    try:
                        cache_entries = len(self._feature_cache)
                        logger.info(
                            f"[DYNAMIC_TP_CACHE] account={self.account_id} entries={cache_entries} ttl_s={self._cache_ttl}"
                        )
                    except Exception:
                        pass
                    self._cache_last_stats_ts = now
            
        except Exception as e:
            logger.warning(f"Error fetching features for {symbol}: {e}")
        
        return features
    
    def _analyze_volatility_for_tp(self, features: Dict) -> Tuple[float, str, List[str]]:
        """
        Analyze volatility to determine TP width.
        ALL SMOOTH — no static if/else thresholds. Uses tanh for continuous mapping.
        
        Returns:
            (multiplier, regime_label, reasons) where multiplier is ~0.7-1.5
        """
        import math
        reasons = []
        
        # ── Gather raw volatility signals ──
        atr_pct = float(features.get('ind_ta_NATR_14_5m', 0) or features.get('ind_ta_NATR_14', 0) or
                        features.get('atr_pct', 0) or features.get('natr', 0) or 0)
        if 0 < atr_pct < 1:
            atr_pct *= 100.0  # decimal → %
        volatility_5m = float(features.get('ccxt_volatility_5m', 0) or features.get('volatility_5m', 0) or 0)
        volatility_1h = float(features.get('ccxt_volatility_1h', 0) or features.get('volatility_1h', 0) or 0)
        bbands_width = float(features.get('ind_ta_BBANDS_width', 0) or features.get('bbands_width', 0) or
                             features.get('bb_width', 0) or 0)
        
        # ── Smooth continuous vol score [0, 1] ──
        # Each component maps through tanh: 0 at baseline, saturates at ~1
        # ATR: crypto baseline ~1.5%, high ~4%+. tanh((atr-1.5)/2.0) smoothly 0→~0.85
        atr_signal = math.tanh(max(0.0, atr_pct - 1.0) / 2.5) * 0.45 if atr_pct > 0 else 0.0
        # CCXT vol: baseline ~0.004, high ~0.015+. Scale by 100 to get percentage-like
        avg_vol = max(float(volatility_5m), float(volatility_1h))
        vol_signal = math.tanh(max(0.0, avg_vol - 0.003) * 120.0) * 0.35
        # BBands: baseline ~3, high ~7+. tanh((bb-3)/3)
        bb_signal = math.tanh(max(0.0, bbands_width - 2.5) / 3.0) * 0.20 if bbands_width > 0 else 0.0
        
        vol_score = min(1.0, atr_signal + vol_signal + bb_signal)
        
        # ── Smooth multiplier: vol_score [0,1] → multiplier [0.75, 1.45] ──
        multiplier = 0.75 + vol_score * 0.70
        
        # ── Descriptive regime label (for logging only, not decision-making) ──
        if vol_score < 0.25:
            regime = "LOW"
        elif vol_score < 0.50:
            regime = "MEDIUM"
        elif vol_score < 0.75:
            regime = "HIGH"
        else:
            regime = "EXTREME"
        
        reasons.append(f"VOL_SMOOTH:score={vol_score:.3f} atr={atr_pct:.2f}% vol={avg_vol*100:.2f}% bb={bbands_width:.1f} mult={multiplier:.3f}")
        return multiplier, regime, reasons
    
    def _analyze_momentum_for_tp(
        self, 
        symbol: str, 
        side: str, 
        features: Dict,
        current_roi_pct: float
    ) -> Tuple[float, bool, List[str]]:
        """
        Analyze momentum — ALL SMOOTH, no static thresholds.
        Uses tanh for continuous scoring.
        
        Returns:
            (momentum_score [-1,1], use_trailing, reasons)
        """
        import math
        reasons = []
        _sg = math.tanh  # smooth gate shorthand
        
        # ── Gather indicators ──
        rsi = float(features.get('ind_ta_RSI_14_5m', 0) or features.get('ind_ta_RSI_14', 0) or
                    features.get('rsi_14', 0) or features.get('rsi', 50) or 50)
        macd_hist = float(features.get('ind_ta_MACD_hist_5m', 0) or features.get('ind_ta_MACD_histogram', 0) or
                         features.get('macd_histogram', 0) or features.get('macd_hist', 0) or 0)
        adx = float(features.get('ind_ta_ADX_14_5m', 0) or features.get('ind_ta_ADX_14', 0) or
                    features.get('adx_14', 0) or features.get('adx', 20) or 20)
        plus_di = float(features.get('ind_ta_PLUS_DI_14_5m', 0) or features.get('ind_ta_PLUS_DI', 0) or
                       features.get('plus_di', 0) or features.get('+di', 0) or 0)
        minus_di = float(features.get('ind_ta_MINUS_DI_14_5m', 0) or features.get('ind_ta_MINUS_DI', 0) or
                        features.get('minus_di', 0) or features.get('-di', 0) or 0)
        price_velocity = float(features.get('ccxt_price_velocity', 0) or features.get('price_velocity', 0) or
                              features.get('fast_move_score', 0) or 0)
        # Additional momentum from tape/taker/stoch
        stoch_k = float(features.get('ind_ta_STOCH_K', 0) or features.get('stoch_k', 50) or 50)
        willr = float(features.get('ind_ta_WILLR', 0) or features.get('willr', -50) or -50)
        mfi = float(features.get('ind_ta_MFI', 0) or features.get('mfi', 50) or 50)
        tape_imb = float(features.get('tape_imbalance_30s', 0) or features.get('tape_imbalance', 0) or 0)
        taker_ratio = float(features.get('kline_taker_buy_ratio', 0) or features.get('taker_buy_ratio', 0.5) or 0.5)
        
        # ── Side multiplier: +1 for LONG alignment, -1 for SHORT ──
        sm = 1.0 if side == 'LONG' else -1.0
        
        # ── Smooth continuous components (each → [-1, 1]) ──
        # RSI: (rsi-50)/20 → tanh → aligned with side
        rsi_signal = _sg((rsi - 50.0) / 20.0) * sm * 0.25
        # MACD hist: normalize by ATR to be scale-invariant
        atr_norm = float(features.get('atr_pct', 0) or features.get('ind_ta_NATR_14', 0) or 1.0)
        if atr_norm <= 0: atr_norm = 1.0
        macd_signal = _sg(macd_hist / max(0.001, atr_norm * float(features.get('current_price', 1) or 1) * 0.01)) * sm * 0.20
        # ADX-weighted DI differential: smooth ADX contribution via min(1, adx/35)
        adx_weight = min(1.0, adx / 35.0)
        di_diff = (plus_di - minus_di) * sm  # positive = aligned
        di_signal = _sg(di_diff / 20.0) * adx_weight * 0.25
        # Stoch: (stoch-50)/25
        stoch_signal = _sg((stoch_k - 50.0) / 25.0) * sm * 0.05
        # WillR: (willr+50)/25 (willr is -100 to 0, -50 = neutral)
        willr_signal = _sg((willr + 50.0) / 25.0) * sm * 0.05
        # MFI: (mfi-50)/20
        mfi_signal = _sg((mfi - 50.0) / 20.0) * sm * 0.05
        # Tape imbalance: direct, already [-1,1]-ish
        tape_signal = _sg(tape_imb * 3.0) * sm * 0.08
        # Taker ratio: (ratio-0.5)*4 → centered at 0.5
        taker_signal = _sg((taker_ratio - 0.5) * 4.0) * sm * 0.07
        
        momentum_score = rsi_signal + macd_signal + di_signal + stoch_signal + willr_signal + mfi_signal + tape_signal + taker_signal
        momentum_score = max(-1.0, min(1.0, momentum_score))
        
        # ── Trailing decision: smooth blend of momentum + ROI ──
        # trail_urgency smoothly increases with both momentum and ROI
        trail_urgency = _sg(momentum_score * 2.0) * _sg((current_roi_pct - 1.0) / 3.0)
        use_trailing = trail_urgency > 0.15  # Very smooth — near-zero around breakeven
        
        reasons.append(
            f"MOM_SMOOTH:score={momentum_score:.3f} rsi={rsi:.0f} adx={adx:.0f} "
            f"di_diff={di_diff:.1f} tape={tape_imb:.2f} trail_urg={trail_urgency:.3f}"
        )
        if use_trailing:
            reasons.append(f"USE_TRAILING:urgency={trail_urgency:.3f}")
        
        return momentum_score, use_trailing, reasons
    
    def _analyze_liquidation_for_tp(
        self,
        symbol: str,
        side: str,
        current_price: float,
        features: Dict
    ) -> Tuple[float, float, List[str]]:
        """
        Analyze liquidation levels for squeeze potential — ALL SMOOTH.
        Uses exponential proximity decay and tanh-scaled strength.
        
        Returns:
            (squeeze_potential [0,1], adjustment_mult, reasons)
        """
        import math
        _sg = math.tanh
        reasons = []
        
        # ── Raw data ──
        liq_long_level = float(features.get('liq_long_level', 0) or features.get('liquidation_long_level', 0) or 0)
        liq_short_level = float(features.get('liq_short_level', 0) or features.get('liquidation_short_level', 0) or 0)
        _raw_long_str = float(features.get('liq_long_strength', 0) or features.get('liquidation_long_strength', 0) or 0)
        _raw_short_str = float(features.get('liq_short_strength', 0) or features.get('liquidation_short_strength', 0) or 0)
        liq_squeeze_score = float(features.get('liq_squeeze_score', 0) or features.get('squeeze_potential', 0) or 0)
        # Also use distance % from unified_features if available
        liq_long_dist = float(features.get('liquidation_long_distance_pct', 100) or 100)
        liq_short_dist = float(features.get('liquidation_short_distance_pct', 100) or 100)
        
        # Normalize strength (raw volumes or 0-1)
        long_str = min(1.0, _raw_long_str / 1e8) if _raw_long_str > 1.0 else min(1.0, max(0.0, _raw_long_str))
        short_str = min(1.0, _raw_short_str / 1e8) if _raw_short_str > 1.0 else min(1.0, max(0.0, _raw_short_str))
        liq_squeeze_score = min(1.0, max(0.0, liq_squeeze_score))
        
        if current_price <= 0:
            return 0.0, 1.0, reasons
        
        # ── Compute distance-based proximity for favorable side ──
        # LONG: shorts above us = favorable squeeze target
        # SHORT: longs below us = favorable squeeze target
        if side == 'LONG':
            # Use pre-computed distance if available, else compute
            if liq_short_level > current_price:
                dist_pct = (liq_short_level - current_price) / current_price * 100.0
            else:
                dist_pct = liq_short_dist
            fav_strength = short_str
        else:
            if 0 < liq_long_level < current_price:
                dist_pct = (current_price - liq_long_level) / current_price * 100.0
            else:
                dist_pct = liq_long_dist
            fav_strength = long_str
        
        # ── Smooth proximity: exp(-dist/2.5) → 1.0 when very close, ~0 when far ──
        proximity = math.exp(-max(0.0, dist_pct) / 2.5)
        
        # ── Squeeze potential: proximity * strength, boosted by general squeeze score ──
        squeeze_potential = min(1.0, proximity * fav_strength * 1.5 + liq_squeeze_score * 0.3)
        
        # ── Smooth adjustment: squeeze [0,1] → mult [1.0, 1.35] ──
        adjustment = 1.0 + squeeze_potential * 0.35
        
        reasons.append(
            f"LIQ_SMOOTH:squeeze={squeeze_potential:.3f} dist={dist_pct:.1f}% "
            f"strength={fav_strength:.3f} proximity={proximity:.3f} adj={adjustment:.3f}"
        )
        return squeeze_potential, adjustment, reasons
    
    def _analyze_microstructure_for_tp(
        self,
        symbol: str,
        side: str,
        features: Dict
    ) -> Tuple[str, float, List[str]]:
        """
        Analyze order flow and microstructure — ALL SMOOTH, no thresholds.
        
        Returns:
            (signal_label, adjustment_mult, reasons)
        """
        import math
        _sg = math.tanh
        reasons = []
        sm = 1.0 if side == 'LONG' else -1.0
        
        # ── Raw signals ──
        order_imb = float(features.get('order_imbalance', 0) or features.get('bid_ask_imbalance', 0) or
                         features.get('msnap_bid_ask_imbalance', 0) or 0)
        spoof = float(features.get('spoof_score', 0) or features.get('msnap_spoof_score', 0) or 0)
        fast_move = float(features.get('fast_move_score', 0) or features.get('msnap_fast_move_score', 0) or 0)
        trade_int = float(features.get('trade_intensity', 0) or features.get('msnap_trade_intensity', 0) or 0)
        depth_imb = float(features.get('depth_imbalance_5', 0) or features.get('depth_imbalance', 0) or 0)
        depth_vs_tape = float(features.get('depth_vs_tape_divergence', 0) or 0)
        
        # ── Smooth net flow score [-1, 1]: positive = favorable for our side ──
        # Order imbalance aligned with side
        flow_aligned = _sg(order_imb * 3.0) * sm * 0.35
        # Depth imbalance aligned
        depth_aligned = _sg(depth_imb * 3.0) * sm * 0.20
        # Spoof penalty (always negative, proportional)
        spoof_penalty = -_sg(spoof * 2.0) * 0.20
        # Trade intensity boost (high activity in our direction)
        intensity_boost = _sg((trade_int - 0.5) * 2.0) * 0.10
        # Depth-vs-tape divergence: negative = tape disagrees with book = adverse
        div_signal = _sg(depth_vs_tape * 2.0) * sm * 0.15
        
        net_score = flow_aligned + depth_aligned + spoof_penalty + intensity_boost + div_signal
        net_score = max(-1.0, min(1.0, net_score))
        
        # ── Smooth adjustment: net_score [-1,1] → mult [0.82, 1.18] ──
        adjustment = 1.0 + net_score * 0.18
        
        # ── Label (for logging only) ──
        if net_score > 0.1:
            signal = "FAVORABLE"
        elif net_score < -0.1:
            signal = "ADVERSE"
        else:
            signal = "NEUTRAL"
        
        reasons.append(
            f"MICRO_SMOOTH:net={net_score:.3f} flow={order_imb:.2f} depth={depth_imb:.2f} "
            f"spoof={spoof:.2f} intensity={trade_int:.2f} adj={adjustment:.3f}"
        )
        return signal, adjustment, reasons
    
    def _analyze_oi_funding_for_tp(
        self,
        symbol: str,
        side: str,
        features: Dict
    ) -> Tuple[float, List[str]]:
        """
        Analyze OI + Funding — ALL SMOOTH, no static thresholds.
        
        Returns:
            (adjustment_mult, reasons)
        """
        import math
        _sg = math.tanh
        reasons = []
        sm = 1.0 if side == 'LONG' else -1.0
        
        funding = float(features.get('funding_rate', 0) or features.get('coinank_funding_rate', 0) or 0)
        oi_change = float(features.get('oi_change_24h', 0) or features.get('coinank_oi_change_24h', 0) or
                         features.get('open_interest_change', 0) or 0)
        ls_ratio = float(features.get('long_short_ratio', 0) or features.get('coinank_long_short_ratio', 1.0) or 1.0)
        oi_weighted = float(features.get('coinank_oi_weighted_funding', 0) or 0)
        
        # ── Funding pressure: positive funding * LONG → paying (against) ──
        # funding * sm > 0 means we're paying → adverse. Scale by 1000 (funding ~0.0001-0.001)
        funding_signal = -_sg(funding * sm * 1000.0) * 0.10  # Negative = tighten
        
        # ── OI change: increasing OI → more conviction → widen ──
        oi_signal = _sg(oi_change / 8.0) * 0.08
        
        # ── L/S ratio: crowding risk. Deviation from 1.0 on our side = adverse ──
        # LONG: ratio > 1 = crowded longs (squeeze risk against us)
        crowd_signal = -_sg((ls_ratio - 1.0) * sm * 2.0) * 0.07
        
        # ── OI-weighted funding (if available from CoinAnk) ──
        oi_fund_signal = -_sg(oi_weighted * sm * 500.0) * 0.05
        
        net = funding_signal + oi_signal + crowd_signal + oi_fund_signal
        adjustment = 1.0 + max(-0.15, min(0.15, net))  # Bounded [0.85, 1.15]
        
        reasons.append(
            f"OI_FUND_SMOOTH:adj={adjustment:.3f} funding={funding*100:.4f}% "
            f"oi_chg={oi_change:.1f}% ls_ratio={ls_ratio:.2f}"
        )
        return adjustment, reasons
    
    def _create_fallback_decision(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        current_price: float,
        reasons: List[str]
    ) -> DynamicTPDecision:
        """Create a conservative fallback decision when data is insufficient."""
        
        # Use default 3% TP
        tp_pct = self.base_tp_pct
        if side == 'LONG':
            tp_price = entry_price * (1 + tp_pct / 100)
        else:
            tp_price = entry_price * (1 - tp_pct / 100)
        
        return DynamicTPDecision(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            current_price=current_price,
            tp_price=tp_price,
            tp_pct=tp_pct,
            tp_decision="STATIC_TP",
            use_trailing=False,
            trail_activation_pct=self.base_trail_activation,
            trail_distance_pct=self.base_trail_distance,
            trail_callback_pct=self.base_trail_distance * 0.5,
            volatility_regime="UNKNOWN",
            momentum_score=0.0,
            squeeze_potential=0.0,
            microstructure_signal="NEUTRAL",
            confidence=0.3,
            reasons=reasons,
            features_used=0,
        )
    
    def should_update_tp(
        self,
        current_tp: float,
        new_tp: float,
        min_change_pct: float = 0.5
    ) -> bool:
        """
        Determine if TP should be updated.
        
        Avoids excessive updates for minor changes.
        """
        if current_tp <= 0:
            return True
        
        change_pct = abs(new_tp - current_tp) / current_tp * 100
        return change_pct >= min_change_pct
