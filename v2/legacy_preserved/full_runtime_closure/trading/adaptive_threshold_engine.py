#!/usr/bin/env python3
"""
Adaptive Threshold Engine
=========================
Replaces ALL static loss/kill/hedge thresholds with real-time adaptive values
computed from:
  - ATR (volatility) across 1m/5m/15m/1h/4h
  - Liquidation distances + strengths (from ingestors)
  - Orderbook imbalance + depth (CoinAPI microstructure)
  - Funding rate + OI pressure (CoinAnk)
  - CoinAPI fast_move_score, spoof_score, snapback_score

Every threshold is computed PER SYMBOL, PER SIDE, PER LEVERAGE on each call.
No static percentages survive — everything adapts to current market conditions.

Kill switch: ADAPTIVE_THRESHOLDS_ENABLED (config.py / .env). When OFF, falls
back to config.py static defaults — backward compatible.
"""

import os
import time
import logging
import math
from typing import Dict, Optional, Tuple, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AdaptiveThresholds:
    """All dynamic thresholds for a symbol+side+leverage combo."""
    symbol: str
    side: str
    leverage: float

    # ── Loss thresholds (ROE %) ──
    per_leg_kill_roe: float        # PER_LEG_ROI_KILL: adaptive (replaces static -30% → dynamic)
    per_leg_warn_roe: float        # PER_LEG_ROI_WARN: adaptive (replaces static -15% → dynamic)
    deep_loss_bypass_roe: float    # NO_LOSS_GUARD_DEEP_LOSS_BYPASS: adaptive (replaces static -5%)

    # ── Hedge-first thresholds ──
    hedge_trigger_roe: float       # When to start hedging instead of closing (replaces static -2%)
    hedge_max_loss_roe: float      # Beyond this ROE, close outright (replaces static -15%)
    hedge_first_min_conf: float    # Min confidence to allow loss-close (replaces static 0.80)

    # ── Breakout loss accept (ROE %) ──
    breakout_min_loss_roe: float   # Min loss for breakout accept (replaces static -40%)
    breakout_max_loss_roe: float   # Max loss ceiling (replaces static -70%)

    # ── Combined hedge protection ──
    combined_hedge_max_loss_usd: float  # Max combined loss on both legs before emergency
    whipsaw_detected: bool         # True if market is choppy (suppress close signals)

    # ── Context ──
    natr_pct: float               # Current ATR as % of price
    liq_distance_pct: float       # Distance to nearest liquidation wall
    volatility_regime: str        # LOW / MEDIUM / HIGH / EXTREME
    ob_imbalance: float           # Orderbook imbalance (-1 to +1)
    funding_rate: float           # Current funding rate
    fast_move_score: float        # CoinAPI fast move detection
    snapback_score: float         # CoinAPI snapback probability
    computation_ts: float         # When this was computed

    # Debug
    factors: Dict[str, float] = field(default_factory=dict)


class AdaptiveThresholdEngine:
    """
    Computes ALL loss/kill/hedge thresholds dynamically from real-time data.
    
    Replaces hardcoded static % thresholds with market-adaptive values.
    Every call reads fresh Redis data for the requested symbol.
    
    Architecture:
    - Volatility (NATR) → widens thresholds in volatile markets
    - Liquidation distance → tightens when close to liq walls  
    - Orderbook imbalance → adjusts based on support/resistance
    - Funding rate → adjusts for carry cost pressure
    - Fast moves → widens to avoid false triggers during spikes
    - Snapback score → suppresses close signals when bounce likely
    """

    # Cache TTL in seconds
    CACHE_TTL = 5.0

    def __init__(self, redis_client=None):
        self.redis = redis_client
        self._cache: Dict[str, Tuple[float, AdaptiveThresholds]] = {}
        # Fallback static values (from config.py defaults) — used when Redis unavailable
        try:
            import config
            self._fb_kill_roe = float(getattr(config, 'PER_LEG_ROI_KILL_PCT', -30.0))
            self._fb_warn_roe = float(getattr(config, 'PER_LEG_ROI_WARN_PCT', -15.0))
            self._fb_deep_loss = float(getattr(config, 'NO_LOSS_GUARD_DEEP_LOSS_BYPASS_PCT', -5.0))
            self._fb_hedge_trigger = float(getattr(config, 'HEDGE_INSTEAD_OF_CLOSE_LOSS_THRESHOLD', -2.0))
            self._fb_hedge_max = float(getattr(config, 'HEDGE_MAX_LOSS_FOR_RECOVERY', -15.0))
            self._fb_hedge_min_conf = float(getattr(config, 'HEDGE_FIRST_ON_LOSING_CLOSE_MIN_CONF', 0.80))
            self._fb_breakout_min = float(getattr(config, 'BREAKOUT_LOSS_ACCEPT_MIN_LOSS_PCT', -40.0))
            self._fb_breakout_max = float(getattr(config, 'BREAKOUT_LOSS_ACCEPT_MAX_LOSS_PCT', -70.0))
            self._fb_kill_max_scale = float(getattr(config, 'PER_LEG_ROI_KILL_MAX_SCALE', 3.0))
            self._fb_kill_ref_lev = float(getattr(config, 'PER_LEG_ROI_KILL_REFERENCE_LEVERAGE', 20.0))
        except Exception:
            self._fb_kill_roe = -30.0
            self._fb_warn_roe = -15.0
            self._fb_deep_loss = -5.0
            self._fb_hedge_trigger = -2.0
            self._fb_hedge_max = -15.0
            self._fb_hedge_min_conf = 0.80
            self._fb_breakout_min = -40.0
            self._fb_breakout_max = -70.0
            self._fb_kill_max_scale = 3.0
            self._fb_kill_ref_lev = 20.0

        logger.info("[ADAPTIVE_THRESHOLDS] Engine initialized | fallback_kill=%.1f%% warn=%.1f%%",
                     self._fb_kill_roe, self._fb_warn_roe)

    def get_thresholds(
        self,
        symbol: str,
        side: str,
        leverage: float,
        equity_usd: float = 0.0,
    ) -> AdaptiveThresholds:
        """
        Get fully adaptive thresholds for a symbol+side+leverage.
        
        Uses cached result if fresh enough (< CACHE_TTL seconds).
        Falls back to config.py static values if Redis unavailable.
        """
        cache_key = f"{symbol}:{side}:{leverage:.0f}"
        now = time.time()

        # Check cache
        if cache_key in self._cache:
            ts, cached = self._cache[cache_key]
            if now - ts < self.CACHE_TTL:
                return cached

        # Compute fresh
        result = self._compute(symbol, side, leverage, equity_usd)
        self._cache[cache_key] = (now, result)
        return result

    def _read_redis_float(self, key: str, field: str, default: float = 0.0) -> float:
        """Safely read a float from a Redis hash."""
        if not self.redis:
            return default
        try:
            raw = self.redis.hget(key, field)
            if raw is None:
                return default
            val = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
            return float(val)
        except Exception:
            return default

    def _read_market_data(self, symbol: str) -> Dict[str, float]:
        """Read all relevant real-time market data from Redis."""
        data: Dict[str, float] = {}
        if not self.redis:
            return data

        sym = symbol.upper().strip()
        feat_key = f"unified_features:{sym}:5m"
        msnap_key = f"msnap:coinapi_wsds:{sym}"

        # ── ATR / Volatility ──
        for tf in ('5m', '15m', '1h'):
            k = f"unified_features:{sym}:{tf}"
            for field_name in ('ind_ta_NATR_14_5m', f'ind_ta_NATR_14_{tf}',
                               f'ind_ind_{sym}_ta_NATR_14_{tf}', 'volatility_pct', 'volatility'):
                v = self._read_redis_float(k, field_name)
                if v > 0:
                    data[f'natr_{tf}'] = max(data.get(f'natr_{tf}', 0), v)

        # ── Liquidation distances + strengths ──
        data['liq_long_dist'] = self._read_redis_float(feat_key, 'liquidation_long_distance_pct')
        data['liq_short_dist'] = self._read_redis_float(feat_key, 'liquidation_short_distance_pct')
        data['liq_long_strength'] = self._read_redis_float(feat_key, 'liquidation_long_strength')
        data['liq_short_strength'] = self._read_redis_float(feat_key, 'liquidation_short_strength')

        # Cross-TF liquidation (wider view)
        for tf in ('15m', '1h', '4h'):
            pfx = f'xtf_{tf}_'
            data[f'liq_long_dist_{tf}'] = self._read_redis_float(feat_key, f'{pfx}liquidation_long_distance_pct')
            data[f'liq_short_dist_{tf}'] = self._read_redis_float(feat_key, f'{pfx}liquidation_short_distance_pct')
            data[f'liq_long_str_{tf}'] = self._read_redis_float(feat_key, f'{pfx}liquidation_long_strength')
            data[f'liq_short_str_{tf}'] = self._read_redis_float(feat_key, f'{pfx}liquidation_short_strength')

        # ── Orderbook ──
        data['ob_imbalance'] = self._read_redis_float(feat_key, 'ob_ob_imbalance')
        data['depth_imbalance'] = self._read_redis_float(feat_key, 'depth_imbalance_5')
        data['ob_spread_bps'] = self._read_redis_float(feat_key, 'ob_ob_spread_bps')

        # ── CoinAPI Microstructure (msnap) ──
        data['fast_move_score'] = self._read_redis_float(msnap_key, 'fast_move_score')
        data['snapback_score'] = self._read_redis_float(msnap_key, 'snapback_score')
        data['spoof_score'] = self._read_redis_float(msnap_key, 'spoof_score')
        data['msnap_imbalance'] = self._read_redis_float(msnap_key, 'imbalance_5')
        data['spread_bps'] = self._read_redis_float(msnap_key, 'spread')
        data['p_false_move'] = self._read_redis_float(msnap_key, 'p_false_move')

        # ── Depth-vs-Tape Divergence (spoof detection from feature_pipeline) ──
        data['depth_vs_tape_divergence'] = self._read_redis_float(feat_key, 'depth_vs_tape_divergence')
        data['tape_imbalance_5s'] = self._read_redis_float(feat_key, 'tape_imbalance_5s')
        data['tape_imbalance_30s'] = self._read_redis_float(feat_key, 'tape_imbalance_30s')

        # ── Funding rate ──
        data['funding_rate'] = self._read_redis_float(feat_key, 'funding_rate')

        # ── Volatility (direct) ──
        data['volatility'] = self._read_redis_float(feat_key, 'volatility')
        data['volatility_pct'] = self._read_redis_float(feat_key, 'volatility_pct')

        return data

    def _classify_volatility(self, natr: float) -> Tuple[str, float]:
        """
        Classify volatility regime from NATR and return a scaling multiplier.
        
        NATR (Normalized ATR as % of price):
          <0.5%  → LOW (tight, calm)     → mult 0.8
          0.5-1.5% → MEDIUM (normal)     → mult 1.0
          1.5-3.0% → HIGH (volatile)     → mult 1.4
          >3.0%  → EXTREME (chaos)       → mult 1.8
        """
        if natr <= 0:
            return "MEDIUM", 1.0
        if natr < 0.5:
            return "LOW", 0.8
        if natr < 1.5:
            return "MEDIUM", 1.0
        if natr < 3.0:
            return "HIGH", 1.4
        return "EXTREME", 1.8

    def _compute(
        self,
        symbol: str,
        side: str,
        leverage: float,
        equity_usd: float,
    ) -> AdaptiveThresholds:
        """Core computation: all thresholds from real-time data."""
        leverage = max(1.0, float(leverage or 1.0))
        data = self._read_market_data(symbol)
        factors: Dict[str, float] = {}

        # ================================================================
        # 1. NATR (best available across timeframes)
        # ================================================================
        natr = max(
            data.get('natr_5m', 0),
            data.get('natr_15m', 0),
            data.get('natr_1h', 0),
        )
        if natr <= 0:
            natr = data.get('volatility_pct', 0) or data.get('volatility', 0) or 0.5
        factors['natr_pct'] = natr

        vol_regime, vol_mult = self._classify_volatility(natr)
        factors['vol_mult'] = vol_mult

        # ================================================================
        # 2. LIQUIDATION DISTANCE (side-specific)
        # ================================================================
        if side.upper() == 'LONG':
            liq_dist = data.get('liq_long_dist', 0)
            liq_strength = data.get('liq_long_strength', 0)
            # Also check wider TF liq walls
            for tf in ('15m', '1h', '4h'):
                td = data.get(f'liq_long_dist_{tf}', 0)
                if td > 0:
                    liq_dist = max(liq_dist, td)  # Use widest view
        else:
            liq_dist = data.get('liq_short_dist', 0)
            liq_strength = data.get('liq_short_strength', 0)
            for tf in ('15m', '1h', '4h'):
                td = data.get(f'liq_short_dist_{tf}', 0)
                if td > 0:
                    liq_dist = max(liq_dist, td)

        if liq_dist <= 0:
            liq_dist = 100.0 / leverage  # Theoretical fallback

        factors['liq_dist_pct'] = liq_dist
        factors['liq_strength'] = liq_strength

        # Liquidation proximity multiplier:
        # Close to liq → tighter kill (save position before liquidation)
        # Far from liq → wider kill (more room to recover)
        liq_mult = 1.0
        liq_dist_at_leverage = liq_dist  # Already in price %
        if liq_dist_at_leverage < 1.0:
            liq_mult = 0.6   # Very close — tighten hard
        elif liq_dist_at_leverage < 2.0:
            liq_mult = 0.75
        elif liq_dist_at_leverage < 5.0:
            liq_mult = 0.9
        elif liq_dist_at_leverage > 10.0:
            liq_mult = 1.3   # Far from liq — can afford wider
        factors['liq_mult'] = liq_mult

        # ================================================================
        # 3. ORDERBOOK + MICROSTRUCTURE
        # ================================================================
        ob_imbalance = data.get('ob_imbalance', 0) or data.get('depth_imbalance', 0) or 0
        msnap_imb = data.get('msnap_imbalance', 0)
        # Blend orderbook and microstructure imbalances
        effective_imbalance = ob_imbalance * 0.6 + msnap_imb * 0.4 if msnap_imb != 0 else ob_imbalance

        fast_move = data.get('fast_move_score', 0)
        snapback = data.get('snapback_score', 0)
        p_false_move = data.get('p_false_move', 0)
        spoof_score = data.get('spoof_score', 0)
        funding = data.get('funding_rate', 0)

        factors['ob_imbalance'] = effective_imbalance
        factors['fast_move_score'] = fast_move
        factors['snapback_score'] = snapback
        factors['p_false_move'] = p_false_move
        factors['spoof_score'] = spoof_score
        factors['funding_rate'] = funding

        # Depth-vs-Tape divergence (spoof detection upgrade)
        dvt_divergence = data.get('depth_vs_tape_divergence', 0)
        tape_imbalance_5s = data.get('tape_imbalance_5s', 0)
        factors['depth_vs_tape_divergence'] = dvt_divergence
        factors['tape_imbalance_5s'] = tape_imbalance_5s

        # ================================================================
        # 4. WHIPSAW DETECTION
        # High fast_move + high snapback + high p_false_move = choppy
        # depth_vs_tape_divergence: when depth and tape disagree = manipulation
        # ================================================================
        whipsaw_score = (
            min(1.0, fast_move) * 0.25 +
            min(1.0, snapback) * 0.25 +
            min(1.0, p_false_move) * 0.20 +
            min(1.0, spoof_score) * 0.10 +
            min(1.0, dvt_divergence) * 0.20  # NEW: tape-vs-depth divergence
        )
        whipsaw_detected = whipsaw_score > 0.5
        factors['whipsaw_score'] = whipsaw_score
        factors['whipsaw_detected'] = float(whipsaw_detected)

        # ================================================================
        # 5. SUPPORT/RESISTANCE from imbalance (side-aware)
        # ================================================================
        # Positive imbalance = more bids = bullish support
        # For LONG: positive imbalance = favorable → widen thresholds
        # For SHORT: negative imbalance = favorable → widen thresholds
        side_upper = side.upper()
        support_mult = 1.0
        if side_upper == 'LONG':
            if effective_imbalance > 0.15:
                support_mult = 1.2   # Strong bid support → wider kills
            elif effective_imbalance > 0.05:
                support_mult = 1.1
            elif effective_imbalance < -0.15:
                support_mult = 0.8   # Adverse — tighten
            elif effective_imbalance < -0.05:
                support_mult = 0.9
        else:
            if effective_imbalance < -0.15:
                support_mult = 1.2   # Strong ask wall → wider kills for SHORT
            elif effective_imbalance < -0.05:
                support_mult = 1.1
            elif effective_imbalance > 0.15:
                support_mult = 0.8   # Adverse
            elif effective_imbalance > 0.05:
                support_mult = 0.9
        factors['support_mult'] = support_mult

        # Depth-vs-Tape override: If depth says "support" but tape says "selling",
        # don't trust the depth-based widening. Spoofers WANT you to trust the book.
        if dvt_divergence > 0.4 and support_mult > 1.0:
            support_mult = max(1.0, support_mult - dvt_divergence * 0.3)
            factors['support_mult'] = support_mult
            factors['support_mult_dvt_override'] = 1.0

        # ================================================================
        # 6. FAST-MOVE WIDEN (don't kill during spikes)
        # ================================================================
        spike_mult = 1.0
        if fast_move > 0.6 and snapback > 0.3:
            # Fast move WITH snapback likelihood → widen to survive the bounce
            spike_mult = 1.3 + min(0.5, snapback * 0.5)
        elif fast_move > 0.4:
            spike_mult = 1.15
        if p_false_move > 0.4:
            spike_mult = max(spike_mult, 1.2)
        # Depth-vs-Tape divergence: if high, tighten kills (spoofed depth is
        # unreliable support — don't rely on "buy wall" that's actually spoofed)
        if dvt_divergence > 0.5:
            spike_mult = min(spike_mult, 1.0)  # Cap: don't widen during confirmed spoofs
        elif dvt_divergence > 0.3:
            spike_mult *= 0.9  # Reduce widening when moderate divergence
        factors['spike_mult'] = spike_mult

        # ================================================================
        # 7. FUNDING PRESSURE
        # ================================================================
        funding_mult = 1.0
        if side_upper == 'LONG' and funding > 0.0005:
            funding_mult = 0.9   # Paying high funding, tighten kills
        elif side_upper == 'SHORT' and funding < -0.0005:
            funding_mult = 0.9
        elif side_upper == 'LONG' and funding < -0.0003:
            funding_mult = 1.1   # Earning funding, widen
        elif side_upper == 'SHORT' and funding > 0.0003:
            funding_mult = 1.1
        factors['funding_mult'] = funding_mult

        # ================================================================
        # COMPOSITE MULTIPLIER
        # ================================================================
        composite = (
            vol_mult * 0.30 +        # Volatility is primary driver
            liq_mult * 0.25 +        # Liquidation proximity is critical
            support_mult * 0.20 +    # Orderbook support/resistance
            spike_mult * 0.15 +      # Fast move protection
            funding_mult * 0.10      # Funding pressure
        )
        factors['composite_mult'] = composite

        # ================================================================
        # 8. MARKET INTELLIGENCE OVERLAY (Trainer + Momentum + MI Context)
        # When MI is available, use trainer prediction alignment & momentum
        # to widen thresholds for positions the trainer still supports.
        # Kill switch: INTELLIGENCE_ADAPTIVE_THRESHOLD_ENABLED (config.py)
        # ================================================================
        mi_alignment_mult = 1.0
        try:
            _mi_enabled = True
            try:
                import config as _at_cfg
                _mi_enabled = bool(getattr(_at_cfg, 'INTELLIGENCE_ADAPTIVE_THRESHOLD_ENABLED', True))
            except Exception:
                pass

            if _mi_enabled and self.redis:
                # ── Trainer prediction: if trainer agrees with position, widen ──
                try:
                    _pred_raw = self.redis.hgetall(f"prediction:{symbol}")
                    if _pred_raw:
                        _pred = {}
                        for _pk, _pv in _pred_raw.items():
                            _pk = _pk.decode() if isinstance(_pk, bytes) else str(_pk)
                            _pv = _pv.decode() if isinstance(_pv, bytes) else str(_pv)
                            _pred[_pk] = _pv
                        _pred_dir = str(_pred.get('direction', '')).upper().strip()
                        _pred_action = str(_pred.get('action_name', _pred.get('action', ''))).upper().strip()
                        _pred_conf = float(_pred.get('confidence', 0) or 0)
                        # Infer direction from action if not explicit
                        if not _pred_dir:
                            if 'LONG' in _pred_action:
                                _pred_dir = 'LONG'
                            elif 'SHORT' in _pred_action:
                                _pred_dir = 'SHORT'
                        _trainer_aligned = (_pred_dir == side_upper and _pred_conf >= 0.50)
                        _trainer_opposed = (_pred_dir != side_upper and _pred_dir in ('LONG', 'SHORT') and _pred_conf >= 0.60)
                        if _trainer_aligned:
                            # Trainer supports this position → widen kills (more room to recover)
                            mi_alignment_mult = 1.0 + min(0.25, _pred_conf * 0.30)
                            factors['trainer_aligned'] = 1.0
                            factors['trainer_conf'] = _pred_conf
                        elif _trainer_opposed:
                            # Trainer wants opposite side → tighten kills (don't hold against trainer)
                            mi_alignment_mult = max(0.80, 1.0 - _pred_conf * 0.20)
                            factors['trainer_opposed'] = 1.0
                            factors['trainer_conf'] = _pred_conf
                except Exception:
                    pass

                # ── Momentum indicators: RSI, MACD from unified features ──
                try:
                    _uf_5m = self.redis.hgetall(f"unified_features:{symbol}:5m") or {}
                    if _uf_5m:
                        _uf = {}
                        for _uk, _uv in _uf_5m.items():
                            _uk = _uk.decode() if isinstance(_uk, bytes) else str(_uk)
                            _uv = _uv.decode() if isinstance(_uv, bytes) else str(_uv)
                            _uf[_uk] = _uv
                        # RSI: oversold for LONG or overbought for SHORT → widen
                        _rsi = 0.0
                        for _rk in ('rsi_14', 'ind_ta_RSI_14_5m', 'ta_RSI_14'):
                            try:
                                _rv = float(_uf.get(_rk, 0) or 0)
                                if _rv > 0:
                                    _rsi = _rv
                                    break
                            except Exception:
                                continue
                        if _rsi > 0:
                            factors['rsi'] = _rsi
                            if side_upper == 'LONG' and _rsi < 35:
                                mi_alignment_mult *= 1.08  # Oversold → widen for recovery
                            elif side_upper == 'SHORT' and _rsi > 65:
                                mi_alignment_mult *= 1.08  # Overbought → widen for drop

                        # MACD histogram alignment
                        _macd_h = 0.0
                        for _mk in ('macd_histogram', 'ind_ta_MACD_hist_12_26_9_5m', 'MACD_hist'):
                            try:
                                _mv = float(_uf.get(_mk, 0) or 0)
                                if abs(_mv) > 0:
                                    _macd_h = _mv
                                    break
                            except Exception:
                                continue
                        if _macd_h != 0:
                            factors['macd_hist'] = _macd_h
                            _macd_aligned = (side_upper == 'LONG' and _macd_h > 0) or \
                                            (side_upper == 'SHORT' and _macd_h < 0)
                            if _macd_aligned:
                                mi_alignment_mult *= 1.05  # Momentum agrees → slightly widen

                        # CoinAnk L/S ratio from features
                        _ls = 0.0
                        for _lk in ('long_short_ratio', 'coinank_ls_ratio', 'long_short_account_ratio'):
                            try:
                                _lv = float(_uf.get(_lk, 0) or 0)
                                if _lv > 0:
                                    _ls = _lv
                                    break
                            except Exception:
                                continue
                        if _ls > 0:
                            factors['ls_ratio'] = _ls
                            # Contrarian signal: crowded longs → tighten for longs
                            if side_upper == 'LONG' and _ls > 2.0:
                                mi_alignment_mult *= 0.95
                            elif side_upper == 'SHORT' and _ls < 0.5:
                                mi_alignment_mult *= 0.95

                        # OI change: rapid deleveraging = danger
                        _oi_chg = 0.0
                        for _ok in ('oi_change_pct', 'open_interest_change', 'oi_change'):
                            try:
                                _ov = float(_uf.get(_ok, 0) or 0)
                                if abs(_ov) > 0:
                                    _oi_chg = _ov
                                    break
                            except Exception:
                                continue
                        if _oi_chg != 0:
                            factors['oi_change'] = _oi_chg
                            if _oi_chg < -5.0:
                                mi_alignment_mult *= 0.93  # Mass deleveraging → tighten
                except Exception:
                    pass

                # Cap alignment multiplier to sane range
                mi_alignment_mult = max(0.70, min(1.35, mi_alignment_mult))
                factors['mi_alignment_mult'] = mi_alignment_mult

        except Exception:
            mi_alignment_mult = 1.0

        # Apply MI alignment to composite
        composite *= mi_alignment_mult
        factors['composite_mult_post_mi'] = composite

        # ================================================================
        # 8b. PERSISTENT EXTREME-VOL ADVERSE-STATE DE-RISKING
        # When EXTREME vol + adverse microstructure + weak trainer alignment
        # persist across multiple reads, tighten thresholds so symbols like
        # RAVEUSDT de-risk faster instead of waiting for a clean reversal.
        # ================================================================
        derisk_tighten = 0.0
        try:
            import config as _cfg

            derisk_enabled = bool(getattr(_cfg, 'EXTREME_VOL_DERISK_PERSIST_ENABLED', True))
            min_streak = max(1, int(getattr(_cfg, 'EXTREME_VOL_DERISK_MIN_STREAK', 3) or 3))
            streak_ttl = max(30, int(getattr(_cfg, 'EXTREME_VOL_DERISK_TTL_SECONDS', 180) or 180))
            max_tighten = max(0.0, min(0.60, float(getattr(_cfg, 'EXTREME_VOL_DERISK_MAX_TIGHTEN', 0.35) or 0.35)))
            weak_align_max = float(getattr(_cfg, 'EXTREME_VOL_DERISK_WEAK_ALIGN_MAX', 0.93) or 0.93)
            adverse_micro_min = float(getattr(_cfg, 'EXTREME_VOL_DERISK_ADVERSE_MICRO_MIN', 0.45) or 0.45)

            adverse_book = max(0.0, -effective_imbalance) if side_upper == 'LONG' else max(0.0, effective_imbalance)
            adverse_micro_score = min(
                1.5,
                adverse_book
                + 0.35 * min(1.0, max(0.0, fast_move))
                + 0.25 * min(1.0, max(0.0, spoof_score))
                + 0.20 * min(1.0, max(0.0, p_false_move)),
            )
            factors['extreme_adverse_micro_score'] = adverse_micro_score

            weak_alignment = mi_alignment_mult <= weak_align_max
            persistent_derisk = (
                derisk_enabled
                and self.redis is not None
                and vol_regime == 'EXTREME'
                and adverse_micro_score >= adverse_micro_min
                and weak_alignment
            )
            factors['extreme_derisk_candidate'] = float(bool(persistent_derisk))

            streak = 0
            streak_key = f"adaptive:derisk:streak:{symbol}:{side_upper}"
            if persistent_derisk:
                streak = int(self.redis.incr(streak_key))
                self.redis.expire(streak_key, streak_ttl)
            elif self.redis is not None:
                self.redis.delete(streak_key)

            factors['extreme_derisk_streak'] = float(streak)
            if persistent_derisk and streak >= min_streak:
                derisk_tighten = min(
                    max_tighten,
                    0.10 + 0.06 * float(streak - min_streak + 1) + 0.12 * min(1.0, adverse_micro_score),
                )
        except Exception:
            derisk_tighten = 0.0

        factors['extreme_derisk_tighten'] = derisk_tighten

        # ================================================================
        # LEVERAGE-AWARE BASE THRESHOLDS
        # ================================================================
        lev_scale = max(1.0, leverage / self._fb_kill_ref_lev)
        lev_scale = min(lev_scale, self._fb_kill_max_scale)
        factors['lev_scale'] = lev_scale

        # ================================================================
        # COMPUTE ADAPTIVE THRESHOLDS
        # ================================================================

        # ── PER_LEG_ROI_KILL: Base / lev_scale * composite ──
        # At 100x: base -30 / 3.0 = -10%, then * composite
        # In HIGH vol with support: -10 * 1.3 = -13% (wider, survive spikes)
        # In LOW vol near liq: -10 * 0.7 = -7% (tighter, protect capital)
        raw_kill = self._fb_kill_roe / lev_scale
        adaptive_kill = raw_kill * composite

        # ATR floor: kill threshold must be at least 3x NATR * leverage
        # (so normal candle noise doesn't trigger kill)
        atr_floor_roe = -(natr * 3.0 * leverage)  # e.g., 0.5% NATR * 3 * 100x = -150% (won't bind)
        # But cap it: floor can't be wider than -60% ROE
        atr_floor_roe = max(atr_floor_roe, -60.0)
        # Floor can't be tighter than -5% ROE (absolute safety minimum)
        adaptive_kill = min(adaptive_kill, max(atr_floor_roe, -5.0))
        # Ceiling: never wider than base (unscaled) value
        adaptive_kill = max(adaptive_kill, self._fb_kill_roe)
        factors['adaptive_kill_roe'] = adaptive_kill

        # ── PER_LEG_ROI_WARN: 50% of kill threshold ──
        adaptive_warn = adaptive_kill * 0.5
        factors['adaptive_warn_roe'] = adaptive_warn

        # ── DEEP LOSS BYPASS: scales with volatility ──
        # In HIGH vol: -5% * 1.4 = -7% (wider bypass — don't close in vol)
        # In LOW vol: -5% * 0.8 = -4% (tighter — less noise tolerance)
        raw_deep = self._fb_deep_loss
        adaptive_deep = raw_deep * vol_mult
        # Clamp: never tighter than -3% or wider than -15%
        adaptive_deep = max(min(adaptive_deep, -3.0), -15.0)
        factors['adaptive_deep_loss'] = adaptive_deep

        # ── HEDGE TRIGGER: when to hedge instead of close ──
        # In HIGH vol: -2% * 1.4 = -2.8% (wait longer before hedging, normal swings)
        # In LOW vol: -2% * 0.8 = -1.6% (hedge sooner, unusual move)
        adaptive_hedge_trigger = self._fb_hedge_trigger * vol_mult
        adaptive_hedge_trigger = max(min(adaptive_hedge_trigger, -1.0), -5.0)
        factors['adaptive_hedge_trigger'] = adaptive_hedge_trigger

        # ── HEDGE MAX LOSS: beyond this, close outright ──
        # Scale with composite: wider when conditions support recovery
        adaptive_hedge_max = self._fb_hedge_max * composite
        adaptive_hedge_max = max(min(adaptive_hedge_max, -8.0), -30.0)
        factors['adaptive_hedge_max'] = adaptive_hedge_max

        # ── HEDGE FIRST MIN CONF: lower in volatile markets ──
        # In HIGH vol: require HIGHER conf to close at loss (0.80 → 0.90)
        # This means more closes get converted to hedges in volatile markets
        adaptive_hedge_conf = self._fb_hedge_min_conf
        if vol_regime in ("HIGH", "EXTREME"):
            adaptive_hedge_conf = min(0.95, adaptive_hedge_conf + 0.10)
        if whipsaw_detected:
            adaptive_hedge_conf = min(0.97, adaptive_hedge_conf + 0.05)
        if snapback > 0.4:
            adaptive_hedge_conf = min(0.97, adaptive_hedge_conf + 0.05)

        if derisk_tighten > 0.0:
            tighten_mult = max(0.35, 1.0 - derisk_tighten)
            adaptive_kill *= tighten_mult
            adaptive_warn *= tighten_mult
            adaptive_deep *= tighten_mult
            adaptive_hedge_trigger *= tighten_mult
            adaptive_hedge_max *= tighten_mult
            adaptive_hedge_conf = max(0.55, adaptive_hedge_conf - (derisk_tighten * 0.20))
            factors['extreme_derisk_applied'] = 1.0
            factors['extreme_derisk_mult'] = tighten_mult

        factors['adaptive_hedge_conf'] = adaptive_hedge_conf

        # ── BREAKOUT LOSS ACCEPT: scale with volatility ──
        adaptive_breakout_min = self._fb_breakout_min * vol_mult
        adaptive_breakout_min = max(min(adaptive_breakout_min, -25.0), -60.0)
        adaptive_breakout_max = self._fb_breakout_max * vol_mult
        adaptive_breakout_max = max(min(adaptive_breakout_max, -50.0), -85.0)
        factors['adaptive_breakout_min'] = adaptive_breakout_min
        factors['adaptive_breakout_max'] = adaptive_breakout_max

        # ── COMBINED HEDGE MAX LOSS USD ──
        # If both legs are losing, cap total loss at 5% of equity (adaptive)
        combined_max_pct = 5.0 * vol_mult  # 4-9% depending on vol
        combined_max_usd = equity_usd * combined_max_pct / 100.0 if equity_usd > 0 else 50.0
        combined_max_usd = max(combined_max_usd, 10.0)  # At least $10
        factors['combined_max_usd'] = combined_max_usd

        result = AdaptiveThresholds(
            symbol=symbol,
            side=side,
            leverage=leverage,
            per_leg_kill_roe=round(adaptive_kill, 2),
            per_leg_warn_roe=round(adaptive_warn, 2),
            deep_loss_bypass_roe=round(adaptive_deep, 2),
            hedge_trigger_roe=round(adaptive_hedge_trigger, 2),
            hedge_max_loss_roe=round(adaptive_hedge_max, 2),
            hedge_first_min_conf=round(adaptive_hedge_conf, 3),
            breakout_min_loss_roe=round(adaptive_breakout_min, 2),
            breakout_max_loss_roe=round(adaptive_breakout_max, 2),
            combined_hedge_max_loss_usd=round(combined_max_usd, 2),
            whipsaw_detected=whipsaw_detected,
            natr_pct=round(natr, 4),
            liq_distance_pct=round(liq_dist, 4),
            volatility_regime=vol_regime,
            ob_imbalance=round(effective_imbalance, 4),
            funding_rate=round(funding, 8),
            fast_move_score=round(fast_move, 4),
            snapback_score=round(snapback, 4),
            computation_ts=time.time(),
            factors=factors,
        )

        logger.info(
            "ADAPTIVE_THRESHOLDS | %s %s lev=%.0f | "
            "kill=%.1f%% warn=%.1f%% deep=%.1f%% | "
            "hedge_trig=%.1f%% hedge_max=%.1f%% hedge_conf=%.3f | "
            "vol=%s natr=%.3f%% liq_dist=%.2f%% | "
            "whipsaw=%s composite=%.3f",
            symbol, side, leverage,
            result.per_leg_kill_roe, result.per_leg_warn_roe, result.deep_loss_bypass_roe,
            result.hedge_trigger_roe, result.hedge_max_loss_roe, result.hedge_first_min_conf,
            vol_regime, natr, liq_dist,
            whipsaw_detected, composite,
        )

        return result

    # ── Progressive hedge layer lookup ──
    def get_progressive_hedge_ratio(
        self, current_roe: float, position_margin: float, leverage: float = 1.0,
    ) -> tuple:
        """
        Get progressive hedge ratio and max USD based on current ROE.

        Returns (hedge_ratio, max_usd) tuple.
        Falls back to flat FRH_HEDGE_RATIO if progressive is disabled.
        """
        try:
            from config import PROGRESSIVE_HEDGE_ENABLED, PROGRESSIVE_HEDGE_LAYERS_PARSED
            if PROGRESSIVE_HEDGE_ENABLED and PROGRESSIVE_HEDGE_LAYERS_PARSED:
                for layer_roe, layer_ratio, layer_max_usd in PROGRESSIVE_HEDGE_LAYERS_PARSED:
                    if current_roe <= layer_roe:
                        return (layer_ratio, layer_max_usd)
        except Exception:
            pass
        # Fallback
        try:
            from config import FRH_HEDGE_RATIO, FRH_HEDGE_MAX_USD
            return (float(FRH_HEDGE_RATIO), float(FRH_HEDGE_MAX_USD))
        except Exception:
            return (0.40, 150.0)


# ── Module-level singleton (lazy init) ──
_engine_instance: Optional[AdaptiveThresholdEngine] = None


def get_adaptive_engine(redis_client=None) -> AdaptiveThresholdEngine:
    """Get or create the singleton AdaptiveThresholdEngine."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = AdaptiveThresholdEngine(redis_client=redis_client)
    elif redis_client is not None and _engine_instance.redis is None:
        _engine_instance.redis = redis_client
    return _engine_instance
