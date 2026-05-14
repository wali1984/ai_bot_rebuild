# -*- coding: utf-8 -*-
"""
Proactive Microstructure System - Multi-TF Market Detection
============================================================
Extends microstructure from protective-only to proactive trading.

Timeframe Roles:
- 1m: PROTECTIVE ONLY - boost exit urgency, never open
- 5m: TACTICAL - detect early reversals, take profits
- 1h: STRATEGIC - trend changes, regime shifts

Proactive Signals:
- TAKE_PROFIT_EARLY: Exit before manipulation completes
- REVERSAL_IMMINENT: Reduce exposure, tighten stops
- SQUEEZE_PEAK: Take profit at squeeze top/bottom
- STOP_HUNT_WARNING: Close before liquidation cascade

Author: WMA AI Trading System
Date: December 25, 2025
"""

import os
import time
import logging
import math
import bisect
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from collections import deque
from enum import Enum

logger = logging.getLogger(__name__)


class ProactiveSignal(Enum):
    """Proactive trading signals from microstructure."""
    NONE = "NONE"
    
    # Exit/Reduce signals (get out before trouble)
    TAKE_PROFIT_EARLY = "TAKE_PROFIT_EARLY"           # Exit before fade
    REVERSAL_IMMINENT = "REVERSAL_IMMINENT"           # Reduce exposure
    SQUEEZE_PEAK = "SQUEEZE_PEAK"                     # Top/bottom of squeeze
    STOP_HUNT_WARNING = "STOP_HUNT_WARNING"           # Liquidation cascade coming
    SPOOF_FADE_INCOMING = "SPOOF_FADE_INCOMING"       # Spoofer about to profit
    MOMENTUM_EXHAUSTION = "MOMENTUM_EXHAUSTION"       # Move losing steam
    SPOOF_EXIT_URGENT = "SPOOF_EXIT_URGENT"           # NEW: Exit immediately due to active spoofing
    MANIPULATION_EXIT = "MANIPULATION_EXIT"            # NEW: Exit due to detected manipulation
    
    # Entry enhancement signals (better timing)
    MANIPULATION_COMPLETE = "MANIPULATION_COMPLETE"    # Safe to enter after flush
    POST_SQUEEZE_ENTRY = "POST_SQUEEZE_ENTRY"         # Enter after squeeze
    SMART_MONEY_ACCUMULATION = "SMART_MONEY_ACCUMULATION"  # Follow the big players
    
    # Hedge signals (ALL TFs can generate these)
    HEDGE_OPEN_LONG = "HEDGE_OPEN_LONG"               # Open long hedge against short
    HEDGE_OPEN_SHORT = "HEDGE_OPEN_SHORT"             # Open short hedge against long
    HEDGE_CLOSE = "HEDGE_CLOSE"                       # Close existing hedge
    HEDGE_INCREASE = "HEDGE_INCREASE"                 # Increase hedge size


@dataclass
class ProactiveAlert:
    """A proactive trading alert from microstructure analysis."""
    symbol: str
    signal: ProactiveSignal
    timeframe: str
    confidence: float  # 0-1
    # Account scope (critical for multi-account systems). Empty means "unspecified".
    account_id: str = ""
    
    # Context
    current_pnl_pct: float = 0.0
    position_side: str = ""  # LONG, SHORT, or ""
    
    # Metrics that triggered the signal
    trigger_metrics: Dict[str, float] = field(default_factory=dict)
    
    # Recommended action
    suggested_action: str = ""  # e.g., "PARTIAL_CLOSE_50", "CLOSE_ALL", "REDUCE_SIZE"
    urgency: str = "NORMAL"  # LOW, NORMAL, HIGH, CRITICAL
    
    # Timing
    ts_ms: int = 0
    expires_ms: int = 0  # Signal validity window
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'symbol': self.symbol,
            'signal': self.signal.value,
            'timeframe': self.timeframe,
            'confidence': self.confidence,
            'account_id': self.account_id,
            'current_pnl_pct': self.current_pnl_pct,
            'position_side': self.position_side,
            'trigger_metrics': self.trigger_metrics,
            'suggested_action': self.suggested_action,
            'urgency': self.urgency,
            'ts_ms': self.ts_ms,
            'expires_ms': self.expires_ms,
        }
    
    def to_log_line(self) -> str:
        acct = f"{self.account_id}:" if self.account_id else ""
        return (
            f"PROACTIVE_SIGNAL | {acct}{self.symbol} | {self.signal.value} | "
            f"tf={self.timeframe} | conf={self.confidence:.2f} | "
            f"pnl={self.current_pnl_pct:.2f}% | side={self.position_side} | "
            f"action={self.suggested_action} | urgency={self.urgency}"
        )


class MicrostructureProactiveAnalyzer:
    """
    Multi-TF proactive microstructure analysis.
    
    Analyzes 1m, 5m, 15m, and 1h microstructure data to generate:
    1. Protective signals (existing) - boost exit urgency
    2. Proactive signals (NEW) - early exit, reversal detection
    3. Hedge signals - ALL TFs can open/close hedges
    
    TF Rules (PRODUCTION CONTRACT):
    - 1m: PROTECTIVE ONLY (no new entries, can manage existing + hedge)
    - 5m: Full trading (entries, exits, hedges, proactive)
    - 15m: Full trading (entries, exits, hedges, proactive) 
    - 1h: Full trading (entries, exits, hedges, proactive)
    - ALL TFs: Can open/close hedge positions for protection
    
    Proactive Entry TFs: 5m, 15m, 1h (NOT 1m)
    """
    
    # Thresholds for proactive signals
    DEFAULT_THRESHOLDS = {
        # Squeeze detection
        'squeeze_peak_threshold': 0.7,       # Squeeze score > this = potential peak
        'squeeze_exhaustion_ret': 0.3,       # Return slowing = exhaustion
        
        # Spoof-and-fade
        'spoof_fade_threshold': 0.6,         # Spoof score > this with reversal
        'imbalance_reversal_threshold': 0.4, # Imbalance flip magnitude
        
        # Stop hunt
        'liq_burst_warning_usd': 500000,     # Large liquidation = warning
        'liq_distance_danger_pct': 2.0,      # Close to liq cluster
        
        # Momentum
        'momentum_exhaustion_accel': -0.2,   # Negative acceleration
        'momentum_exhaustion_vol': 1.5,      # High vol with slowing returns
        
        # PnL-based urgency
        'profit_lock_pct': 2.0,              # Lock profits above this
        'loss_warning_pct': -1.5,            # Warning at this loss
    }
    
    def __init__(
        self,
        redis_client=None,
        thresholds: Dict[str, float] = None,
    ):
        self.redis = redis_client
        self.thresholds = {**self.DEFAULT_THRESHOLDS, **(thresholds or {})}
        
        # Per-symbol signal history (for debouncing)
        self._signal_history: Dict[str, deque] = {}
        self._signal_cooldown_ms = 60000  # 1 minute between same signals

        # Low-latency mid-price history (msnap) for quick returns/volatility estimates.
        # This allows the proactive module to operate even when microfeat:* is absent.
        self._mid_history: Dict[str, deque] = {}
        self._mid_history_maxlen = int(os.getenv("PROACTIVE_MID_HISTORY_MAXLEN", "600"))  # ~minutes of history
        self._mid_history_max_age_ms = int(os.getenv("PROACTIVE_MID_HISTORY_MAX_AGE_MS", "120000"))  # 2 minutes

        # Per-symbol/account hedge risk history (used to make hedge triggers adaptive to regime).
        # This avoids brittle static thresholds by ranking current risk versus recent history.
        self._hedge_risk_history: Dict[str, deque] = {}
        self._hedge_risk_history_maxlen = int(os.getenv("PROACTIVE_HEDGE_RISK_HISTORY_MAXLEN", "200"))
        
        # Load feature extractor
        self._feature_extractor = None
        self._overlay = None
        
        logger.info(f"[PROACTIVE] MicrostructureProactiveAnalyzer initialized")
    
    def _get_feature_extractor(self):
        """Lazy load feature extractor."""
        if self._feature_extractor is None:
            try:
                from rl.microstructure_features import get_microstructure_extractor
                self._feature_extractor = get_microstructure_extractor(redis_client=self.redis)
            except Exception as e:
                logger.debug(f"[PROACTIVE] Feature extractor not available: {e}")
        return self._feature_extractor
    
    def _get_overlay(self):
        """Lazy load microstructure overlay."""
        if self._overlay is None:
            try:
                from rl.microstructure_overlay import get_microstructure_overlay
                self._overlay = get_microstructure_overlay(redis_client=self.redis)
            except Exception as e:
                logger.debug(f"[PROACTIVE] Overlay not available: {e}")
        return self._overlay
    
    def _get_micro_state(self, symbol: str, tf: str) -> Optional[Dict[str, Any]]:
        """Get microstructure state from Redis or extractor."""
        if self.redis:
            try:
                key = f"microfeat:{symbol}:{tf}"
                data = self.redis.hgetall(key)
                if data:
                    out = {
                        (k.decode() if isinstance(k, bytes) else k): 
                        (v.decode() if isinstance(v, bytes) else v)
                        for k, v in data.items()
                    }
                    # ------------------------------------------------------------------
                    # Augment microfeat with msnap rolling max fields (when available).
                    #
                    # Trainer runs on ~30s cadence; CoinAPI WSDS publishes rolling
                    # fast_move_max_* so we can still react even if the instantaneous
                    # fast_move_score has already cooled off.
                    #
                    # We fold max_* into fast_move_score (best-effort) so downstream
                    # thresholds keep working without further changes.
                    # ------------------------------------------------------------------
                    try:
                        msnap_key = f"msnap:coinapi_wsds:{symbol}"
                        ms = self.redis.hgetall(msnap_key) or {}
                        if ms:
                            ms = {
                                (k.decode() if isinstance(k, bytes) else k):
                                (v.decode() if isinstance(v, bytes) else v)
                                for k, v in ms.items()
                            }
                            for f in ("fast_move_max_1m", "fast_move_max_5m", "fast_move_max_15m"):
                                if f in ms and ms.get(f) is not None:
                                    out[f] = ms.get(f)
                            # Fold into fast_move_score (use max of instantaneous + rolling maxes)
                            try:
                                f0 = float(out.get("fast_move_score", 0) or 0)
                                f1 = float(out.get("fast_move_max_1m", 0) or 0)
                                f5 = float(out.get("fast_move_max_5m", 0) or 0)
                                f15 = float(out.get("fast_move_max_15m", 0) or 0)
                                out["fast_move_score"] = str(max(f0, f1, f5, f15))
                            except Exception:
                                pass
                    except Exception:
                        pass
                    return out
            except Exception:
                pass

        # ------------------------------------------------------------------
        # Fallback: use best available msnap snapshot (CoinAPI WSDS/Binance WS)
        # and derive short-horizon returns from mid-price history.
        #
        # This is CRITICAL for live protection: if microfeat:* is not being
        # produced by a dedicated extractor, we still want proactive hedges
        # to trigger on fast moves and orderbook pressure.
        # ------------------------------------------------------------------
        try:
            if self.redis:
                from rl.microstructure_source_router import get_best_msnap
                snap, source = get_best_msnap(symbol, redis_client=self.redis)
                if snap and float(getattr(snap, "mid_px", 0) or 0) > 0:
                    now_ms = int(time.time() * 1000)
                    ts_ms = int(getattr(snap, "updated_ts_ms", 0) or now_ms)
                    mid_px = float(getattr(snap, "mid_px", 0) or 0)

                    # Maintain per-symbol history (timestamped mid prices)
                    hist = self._mid_history.get(symbol)
                    if hist is None:
                        hist = deque(maxlen=self._mid_history_maxlen)
                        self._mid_history[symbol] = hist

                    # Append only if monotonic timestamp (avoid duplicates/out-of-order)
                    try:
                        if not hist or ts_ms > int(hist[-1][0]):
                            hist.append((ts_ms, mid_px))
                    except Exception:
                        # Best-effort - do not block
                        hist.append((ts_ms, mid_px))

                    # Drop very old points (age cap)
                    try:
                        min_ts = now_ms - self._mid_history_max_age_ms
                        while hist and int(hist[0][0]) < min_ts:
                            hist.popleft()
                    except Exception:
                        pass

                    def _ret_pct(window_ms: int) -> float:
                        """Return % change from ~window_ms ago to now, using nearest past point."""
                        try:
                            if not hist:
                                return 0.0
                            target_ts = now_ms - int(window_ms)
                            past = None
                            # iterate from newest backwards to find first <= target
                            for t, px in reversed(hist):
                                if int(t) <= target_ts:
                                    past = (int(t), float(px))
                                    break
                            if past is None:
                                return 0.0
                            past_px = past[1]
                            if past_px <= 0:
                                return 0.0
                            return (mid_px - past_px) / past_px * 100.0
                        except Exception:
                            return 0.0

                    ret_5s = _ret_pct(5000)
                    ret_15s = _ret_pct(15000)
                    ret_30s = _ret_pct(30000)
                    ret_60s = _ret_pct(60000)
                    accel_15s = ret_5s - ret_15s

                    # Simple realized-vol proxy over recent returns (stddev of 5s returns over last ~30s)
                    vol_30s = 0.0
                    try:
                        # Build a few 5s returns from history if enough points exist
                        if len(hist) >= 6:
                            # sample up to last 7 points (~>30s if 5s spacing)
                            pts = list(hist)[-20:]
                            rets = []
                            for i in range(1, len(pts)):
                                t0, p0 = pts[i - 1]
                                t1, p1 = pts[i]
                                if float(p0) > 0 and (int(t1) - int(t0)) > 0:
                                    rets.append((float(p1) - float(p0)) / float(p0) * 100.0)
                            if rets:
                                # stddev as volatility proxy (percent)
                                m = sum(rets) / len(rets)
                                var = sum((x - m) ** 2 for x in rets) / max(1, (len(rets) - 1))
                                vol_30s = var ** 0.5
                    except Exception:
                        vol_30s = 0.0

                    # Approx squeeze heuristic (adaptive): large 60s move + high fast-move score
                    fast_move = float(getattr(snap, "fast_move_score", 0) or 0)
                    is_squeeze = bool(abs(ret_60s) > 0.6 and fast_move > 0.5)
                    squeeze_dir = 1 if ret_60s > 0 else -1 if ret_60s < 0 else 0
                    squeeze_mag = min(1.0, abs(ret_60s) / 2.0) if abs(ret_60s) > 0 else 0.0

                    return {
                        "source": f"msnap:{getattr(source, 'value', str(source))}",
                        "updated_ts_ms": ts_ms,
                        # Orderbook / microstructure metrics (CoinAPI WSDS contract fields)
                        "mid_px": mid_px,
                        "imbalance_5": float(getattr(snap, "imbalance_5", 0) or 0),
                        "orderbook_imbalance": float(getattr(snap, "imbalance_5", 0) or 0),
                        "churn_score": float(getattr(snap, "churn_score", 0) or 0),
                        "snapback_score": float(getattr(snap, "snapback_score", 0) or 0),
                        "spoof_score": float(getattr(snap, "spoof_score", 0) or 0),
                        "fast_move_score": fast_move,
                        "spread": float(getattr(snap, "spread", 0) or 0),
                        "micro_staleness_ms": float(getattr(snap, "src_staleness_ms", 0) or 0),
                        "micro_quality_score": float(getattr(snap, "src_quality_score", 0) or 0),
                        # Derived micro returns / accel / vol proxies
                        "ret_5s": ret_5s,
                        "ret_15s": ret_15s,
                        "ret_30s": ret_30s,
                        "ret_60s": ret_60s,
                        "accel_15s": accel_15s,
                        "volatility_30s": vol_30s,
                        # Squeeze heuristic
                        "is_squeeze": is_squeeze,
                        "squeeze_direction": squeeze_dir,
                        "squeeze_magnitude": squeeze_mag,
                    }
        except Exception:
            # Best-effort only; continue to extractor fallback
            pass
        
        # Fallback to extractor
        extractor = self._get_feature_extractor()
        if extractor and symbol in extractor.states:
            state = extractor.states[symbol]
            return {
                'ret_5s': state.ret_5s,
                'ret_15s': state.ret_15s,
                'ret_30s': state.ret_30s,
                'ret_60s': state.ret_60s,
                'accel_5s': state.accel_5s,
                'accel_15s': state.accel_15s,
                'volatility_30s': state.volatility_30s,
                'volatility_60s': state.volatility_60s,
                'orderbook_imbalance': state.orderbook_imbalance,
                'is_squeeze': state.is_squeeze,
                'squeeze_direction': state.squeeze_direction,
                'squeeze_magnitude': state.squeeze_magnitude,
                'liq_burst_long_usd': state.liq_burst_long_usd,
                'liq_burst_short_usd': state.liq_burst_short_usd,
                'liq_distance_long_pct': state.liq_distance_long_pct,
                'liq_distance_short_pct': state.liq_distance_short_pct,
            }
        
        return None
    
    def _get_overlay_scores(self, symbol: str) -> Tuple[float, float]:
        """Get spoof and fast-move scores from overlay."""
        overlay = self._get_overlay()
        if overlay:
            spoof = overlay.compute_spoof_score(symbol)
            fast = overlay.compute_fast_move_score(symbol)
            return (spoof.score if spoof.inputs_valid else 0.0,
                    fast.score if fast.inputs_valid else 0.0)
        return 0.0, 0.0

    def _resolve_scores(self, symbol: str, state: Optional[Dict[str, Any]]) -> Tuple[float, float]:
        """
        Resolve spoof/fast-move scores with safe fallbacks.

        Primary: microstructure overlay scores (when available/inputs healthy).
        Fallback: msnap-derived fields (CoinAPI WSDS/Binance WS) carried in `state`
        when microfeat:* is absent or overlay inputs are unavailable.
        """
        spoof_score, fast_move_score = self._get_overlay_scores(symbol)
        if not state:
            return spoof_score, fast_move_score

        try:
            s_spoof = float(state.get("spoof_score", 0) or 0)
        except Exception:
            s_spoof = 0.0
        try:
            s_fast = float(state.get("fast_move_score", 0) or 0)
        except Exception:
            s_fast = 0.0

        # Risk detection is "OR": if either source flags high risk, prefer the higher score.
        spoof_score = max(float(spoof_score or 0.0), float(s_spoof or 0.0))
        fast_move_score = max(float(fast_move_score or 0.0), float(s_fast or 0.0))
        return spoof_score, fast_move_score
    
    def _should_emit_signal(self, symbol: str, signal: ProactiveSignal) -> bool:
        """Check if signal should be emitted (debounce)."""
        now_ms = int(time.time() * 1000)
        
        if symbol not in self._signal_history:
            self._signal_history[symbol] = deque(maxlen=20)
        
        history = self._signal_history[symbol]
        
        # Check for recent same signal
        for prev_signal, prev_ts in history:
            if prev_signal == signal and (now_ms - prev_ts) < self._signal_cooldown_ms:
                return False
        
        # Record this signal
        history.append((signal, now_ms))
        return True
    
    def analyze_1m_protective(
        self,
        symbol: str,
        position_side: str,
        pnl_pct: float = 0.0,
        account_id: str = "",
    ) -> Optional[ProactiveAlert]:
        """
        1m PROTECTIVE analysis only.
        
        Does NOT generate entry signals.
        CAN generate:
        - Exit urgency boost
        - Stop hunt warnings
        - Squeeze peak detection (to exit)
        """
        if not position_side:
            return None  # No position, nothing to protect
        
        state = self._get_micro_state(symbol, '1m')
        if not state:
            return None

        spoof_score, fast_move_score = self._resolve_scores(symbol, state)
        now_ms = int(time.time() * 1000)
        
        # === STOP HUNT WARNING ===
        if position_side == 'LONG':
            liq_distance = float(state.get('liq_distance_long_pct', 100))
            liq_burst = float(state.get('liq_burst_long_usd', 0))
        else:
            liq_distance = float(state.get('liq_distance_short_pct', 100))
            liq_burst = float(state.get('liq_burst_short_usd', 0))
        
        if (liq_distance < self.thresholds['liq_distance_danger_pct'] and 
            liq_burst > self.thresholds['liq_burst_warning_usd']):
            
            scoped_sym = f"{account_id}:{symbol}" if account_id else symbol
            if self._should_emit_signal(scoped_sym, ProactiveSignal.STOP_HUNT_WARNING):
                return ProactiveAlert(
                    symbol=symbol,
                    signal=ProactiveSignal.STOP_HUNT_WARNING,
                    timeframe='1m',
                    confidence=min(0.9, 0.5 + liq_burst / 1000000),
                    account_id=account_id or "",
                    current_pnl_pct=pnl_pct,
                    position_side=position_side,
                    trigger_metrics={
                        'liq_distance_pct': liq_distance,
                        'liq_burst_usd': liq_burst,
                    },
                    suggested_action='CLOSE_ALL' if pnl_pct < 0 else 'PARTIAL_CLOSE_50',
                    urgency='CRITICAL',
                    ts_ms=now_ms,
                    expires_ms=now_ms + 30000,  # 30s validity
                )
        
        # === SQUEEZE PEAK (for exits) ===
        is_squeeze = bool(state.get('is_squeeze', False))
        squeeze_mag = float(state.get('squeeze_magnitude', 0))
        squeeze_dir = int(state.get('squeeze_direction', 0))
        
        # If in squeeze, aligned with position, and showing exhaustion
        if is_squeeze and squeeze_mag > self.thresholds['squeeze_peak_threshold']:
            accel = float(state.get('accel_15s', 0))
            
            # Squeeze in our favor + slowing = take profit
            position_aligned = (
                (position_side == 'LONG' and squeeze_dir > 0) or
                (position_side == 'SHORT' and squeeze_dir < 0)
            )
            
            if position_aligned and accel * squeeze_dir < 0:  # Acceleration opposite to direction
                scoped_sym = f"{account_id}:{symbol}" if account_id else symbol
                if self._should_emit_signal(scoped_sym, ProactiveSignal.SQUEEZE_PEAK):
                    return ProactiveAlert(
                        symbol=symbol,
                        signal=ProactiveSignal.SQUEEZE_PEAK,
                        timeframe='1m',
                        confidence=squeeze_mag,
                        account_id=account_id or "",
                        current_pnl_pct=pnl_pct,
                        position_side=position_side,
                        trigger_metrics={
                            'squeeze_magnitude': squeeze_mag,
                            'squeeze_direction': squeeze_dir,
                            'acceleration': accel,
                        },
                        suggested_action='PARTIAL_CLOSE_30' if pnl_pct > 0 else 'HOLD',
                        urgency='HIGH',
                        ts_ms=now_ms,
                        expires_ms=now_ms + 60000,
                    )
        
        # === SPOOF FADE INCOMING ===
        imbalance = float(state.get('orderbook_imbalance', 0))
        if spoof_score > self.thresholds['spoof_fade_threshold']:
            # High spoof + imbalance against our position = danger
            position_threatened = (
                (position_side == 'LONG' and imbalance < -0.3) or
                (position_side == 'SHORT' and imbalance > 0.3)
            )
            
            if position_threatened:
                scoped_sym = f"{account_id}:{symbol}" if account_id else symbol
                if self._should_emit_signal(scoped_sym, ProactiveSignal.SPOOF_FADE_INCOMING):
                    return ProactiveAlert(
                        symbol=symbol,
                        signal=ProactiveSignal.SPOOF_FADE_INCOMING,
                        timeframe='1m',
                        confidence=spoof_score,
                        account_id=account_id or "",
                        current_pnl_pct=pnl_pct,
                        position_side=position_side,
                        trigger_metrics={
                            'spoof_score': spoof_score,
                            'imbalance': imbalance,
                        },
                        suggested_action='CLOSE_ALL' if pnl_pct > 0 else 'REDUCE_STOP',
                        urgency='HIGH',
                        ts_ms=now_ms,
                        expires_ms=now_ms + 45000,
                    )
        
        return None
    
    def analyze_5m_tactical(
        self,
        symbol: str,
        position_side: str,
        pnl_pct: float = 0.0,
        model_action: str = "",
        model_confidence: float = 0.0,
        account_id: str = "",
    ) -> Optional[ProactiveAlert]:
        """
        5m TACTICAL analysis - both protective AND proactive.
        
        Can generate:
        - All protective signals from 1m
        - TAKE_PROFIT_EARLY
        - REVERSAL_IMMINENT
        - MOMENTUM_EXHAUSTION
        - POST_SQUEEZE_ENTRY (for timing entries)
        - SPOOF_EXIT_URGENT (aggressive spoof protection)
        - MANIPULATION_EXIT (book imbalance manipulation)
        """
        state = self._get_micro_state(symbol, '5m')
        state_1m = self._get_micro_state(symbol, '1m')
        
        if not state and not state_1m:
            return None
        
        # Use 5m state with 1m fallback
        state = state or state_1m or {}

        spoof_score, fast_move_score = self._resolve_scores(symbol, state)
        now_ms = int(time.time() * 1000)
        
        # First check protective signals (same as 1m)
        if position_side:
            protective = self.analyze_1m_protective(symbol, position_side, pnl_pct, account_id=account_id)
            if protective:
                protective.timeframe = '5m'  # Upgrade to 5m
                return protective
        
        # === NEW: SPOOF_EXIT_URGENT - Aggressive spoof detection for positions ===
        if position_side and spoof_score > 0.25:
            # Get additional manipulation indicators
            imbalance = float(state.get('imbalance_5', 0))
            churn_score = float(state.get('churn_score', 0))
            snapback_score = float(state.get('snapback_score', 0))
            ret_15s = float(state.get('ret_15s', 0))
            
            # Detect spoofing against our position
            spoof_against_position = (
                (position_side == 'LONG' and imbalance < -0.5) or  # Heavy sell imbalance vs LONG
                (position_side == 'SHORT' and imbalance > 0.5)     # Heavy buy imbalance vs SHORT
            )
            
            # Exit urgently if: spoof detected AND moving against us AND in loss
            if spoof_against_position and pnl_pct < 0:
                urgency = "CRITICAL" if (spoof_score > 0.4 or pnl_pct < -1.0) else "HIGH"
                scoped_sym = f"{account_id}:{symbol}" if account_id else symbol
                if self._should_emit_signal(scoped_sym, ProactiveSignal.SPOOF_EXIT_URGENT):
                    return ProactiveAlert(
                        symbol=symbol,
                        signal=ProactiveSignal.SPOOF_EXIT_URGENT,
                        timeframe='5m',
                        confidence=0.75 + min(0.2, spoof_score),
                        account_id=account_id or "",
                        current_pnl_pct=pnl_pct,
                        position_side=position_side,
                        trigger_metrics={
                            'spoof_score': spoof_score,
                            'imbalance': imbalance,
                            'churn_score': churn_score,
                            'snapback_score': snapback_score,
                            'ret_15s': ret_15s,
                        },
                        suggested_action='CLOSE_ALL' if pnl_pct < -1.5 else 'PARTIAL_CLOSE_70',
                        urgency=urgency,
                        ts_ms=now_ms,
                        expires_ms=now_ms + 30000,  # 30s validity - act fast
                    )
            
            # Even in profit, exit if manipulation is extreme
            elif spoof_against_position and spoof_score > 0.45:
                scoped_sym = f"{account_id}:{symbol}" if account_id else symbol
                if self._should_emit_signal(scoped_sym, ProactiveSignal.MANIPULATION_EXIT):
                    return ProactiveAlert(
                        symbol=symbol,
                        signal=ProactiveSignal.MANIPULATION_EXIT,
                        timeframe='5m',
                        confidence=0.70 + min(0.25, spoof_score),
                        account_id=account_id or "",
                        current_pnl_pct=pnl_pct,
                        position_side=position_side,
                        trigger_metrics={
                            'spoof_score': spoof_score,
                            'imbalance': imbalance,
                            'fast_move_score': fast_move_score,
                        },
                        suggested_action='PARTIAL_CLOSE_50',
                        urgency='HIGH',
                        ts_ms=now_ms,
                        expires_ms=now_ms + 60000,
                    )
        
        # === PROACTIVE: TAKE_PROFIT_EARLY ===
        if position_side and pnl_pct > self.thresholds['profit_lock_pct']:
            # In profit, check for reversal signs
            accel = float(state.get('accel_15s', 0))
            vol = float(state.get('volatility_30s', 0))
            
            # High volatility + decelerating = take profit
            if vol > self.thresholds['momentum_exhaustion_vol']:
                position_momentum = (
                    (position_side == 'LONG' and accel < self.thresholds['momentum_exhaustion_accel']) or
                    (position_side == 'SHORT' and accel > -self.thresholds['momentum_exhaustion_accel'])
                )
                
                if position_momentum:
                    scoped_sym = f"{account_id}:{symbol}" if account_id else symbol
                    if self._should_emit_signal(scoped_sym, ProactiveSignal.TAKE_PROFIT_EARLY):
                        return ProactiveAlert(
                            symbol=symbol,
                            signal=ProactiveSignal.TAKE_PROFIT_EARLY,
                            timeframe='5m',
                            confidence=0.6 + min(0.3, pnl_pct / 10),
                            account_id=account_id or "",
                            current_pnl_pct=pnl_pct,
                            position_side=position_side,
                            trigger_metrics={
                                'acceleration': accel,
                                'volatility': vol,
                                'pnl_pct': pnl_pct,
                            },
                            suggested_action='PARTIAL_CLOSE_50',
                            urgency='NORMAL',
                            ts_ms=now_ms,
                            expires_ms=now_ms + 120000,
                        )
        
        # === PROACTIVE: REVERSAL_IMMINENT ===
        is_squeeze = bool(state.get('is_squeeze', False))
        squeeze_dir = int(state.get('squeeze_direction', 0))
        ret_60s = float(state.get('ret_60s', 0))
        
        if is_squeeze and abs(ret_60s) > 1.0:
            # Big move in squeeze, check if reversing
            ret_5s = float(state.get('ret_5s', 0))
            
            # Direction changed
            if (squeeze_dir > 0 and ret_5s < -0.1) or (squeeze_dir < 0 and ret_5s > 0.1):
                scoped_sym = f"{account_id}:{symbol}" if account_id else symbol
                if self._should_emit_signal(scoped_sym, ProactiveSignal.REVERSAL_IMMINENT):
                    return ProactiveAlert(
                        symbol=symbol,
                        signal=ProactiveSignal.REVERSAL_IMMINENT,
                        timeframe='5m',
                        confidence=0.7,
                        account_id=account_id or "",
                        current_pnl_pct=pnl_pct,
                        position_side=position_side,
                        trigger_metrics={
                            'ret_60s': ret_60s,
                            'ret_5s': ret_5s,
                            'squeeze_direction': squeeze_dir,
                        },
                        suggested_action='REDUCE_50' if position_side else 'WAIT_ENTRY',
                        urgency='HIGH',
                        ts_ms=now_ms,
                        expires_ms=now_ms + 90000,
                    )
        
        # === PROACTIVE: POST_SQUEEZE_ENTRY (for timing) ===
        # NOTE: Only emit if model confidence is high enough to pass downstream gates
        # (CONTEXTUAL_CONF_BLOCK requires 0.80+ for unaligned stacks)
        if not position_side and model_action and 'OPEN' in model_action.upper() and model_confidence >= 0.75:
            # Model wants to enter with sufficient confidence, check if post-squeeze is safe
            squeeze_mag = float(state.get('squeeze_magnitude', 0))
            
            # Squeeze just ended (low magnitude after being high)
            if squeeze_mag < 0.3 and fast_move_score < 0.5 and spoof_score < 0.4:
                scoped_sym = f"{account_id}:{symbol}" if account_id else symbol
                if self._should_emit_signal(scoped_sym, ProactiveSignal.POST_SQUEEZE_ENTRY):
                    return ProactiveAlert(
                        symbol=symbol,
                        signal=ProactiveSignal.POST_SQUEEZE_ENTRY,
                        timeframe='5m',
                        confidence=model_confidence,  # Preserve original model confidence
                        account_id=account_id or "",
                        position_side="",
                        trigger_metrics={
                            'squeeze_magnitude': squeeze_mag,
                            'spoof_score': spoof_score,
                            'fast_move_score': fast_move_score,
                            'model_action': model_action,
                        },
                        suggested_action=model_action,
                        urgency='NORMAL',
                        ts_ms=now_ms,
                        expires_ms=now_ms + 60000,
                    )
        
        return None
    
    def analyze_15m_tactical(
        self,
        symbol: str,
        position_side: str,
        pnl_pct: float = 0.0,
        model_action: str = "",
        model_confidence: float = 0.0,
        account_id: str = "",
    ) -> Optional[ProactiveAlert]:
        """
        15m TACTICAL analysis - both protective AND proactive.
        
        Similar to 5m but with longer confirmation windows.
        
        Can generate:
        - All protective signals (stop hunt, squeeze peak, spoof fade)
        - TAKE_PROFIT_EARLY (with higher threshold)
        - REVERSAL_IMMINENT
        - MOMENTUM_EXHAUSTION
        - POST_SQUEEZE_ENTRY (for timing entries)
        - MANIPULATION_COMPLETE (post-flush entries)
        
        NOTE: 15m is a PROACTIVE TRADING TF (can open new risk when flat)
        """
        state = self._get_micro_state(symbol, '15m')
        state_5m = self._get_micro_state(symbol, '5m')
        
        if not state and not state_5m:
            return None
        
        # Use 15m state with 5m fallback
        state = state or state_5m or {}

        spoof_score, fast_move_score = self._resolve_scores(symbol, state)
        now_ms = int(time.time() * 1000)
        
        # First check protective signals (same as 1m) if we have position
        if position_side:
            protective = self.analyze_1m_protective(symbol, position_side, pnl_pct, account_id=account_id)
            if protective:
                protective.timeframe = '15m'  # Upgrade to 15m
                return protective
        
        # === PROACTIVE: TAKE_PROFIT_EARLY (higher threshold for 15m) ===
        if position_side and pnl_pct > self.thresholds['profit_lock_pct'] * 1.5:  # 3% instead of 2%
            accel = float(state.get('accel_15s', 0))
            vol = float(state.get('volatility_30s', 0))
            
            if vol > self.thresholds['momentum_exhaustion_vol']:
                position_momentum = (
                    (position_side == 'LONG' and accel < self.thresholds['momentum_exhaustion_accel']) or
                    (position_side == 'SHORT' and accel > -self.thresholds['momentum_exhaustion_accel'])
                )
                
                if position_momentum:
                    scoped_sym = f"{account_id}:{symbol}" if account_id else symbol
                    if self._should_emit_signal(scoped_sym, ProactiveSignal.TAKE_PROFIT_EARLY):
                        return ProactiveAlert(
                            symbol=symbol,
                            signal=ProactiveSignal.TAKE_PROFIT_EARLY,
                            timeframe='15m',
                            confidence=0.65 + min(0.25, pnl_pct / 12),
                            account_id=account_id or "",
                            current_pnl_pct=pnl_pct,
                            position_side=position_side,
                            trigger_metrics={
                                'acceleration': accel,
                                'volatility': vol,
                                'pnl_pct': pnl_pct,
                            },
                            suggested_action='PARTIAL_CLOSE_50',
                            urgency='NORMAL',
                            ts_ms=now_ms,
                            expires_ms=now_ms + 180000,  # 3 min validity for 15m
                        )
        
        # === PROACTIVE: REVERSAL_IMMINENT ===
        is_squeeze = bool(state.get('is_squeeze', False))
        squeeze_dir = int(state.get('squeeze_direction', 0))
        ret_60s = float(state.get('ret_60s', 0))
        
        if is_squeeze and abs(ret_60s) > 1.2:  # Slightly higher threshold for 15m
            ret_5s = float(state.get('ret_5s', 0))
            
            if (squeeze_dir > 0 and ret_5s < -0.15) or (squeeze_dir < 0 and ret_5s > 0.15):
                scoped_sym = f"{account_id}:{symbol}" if account_id else symbol
                if self._should_emit_signal(scoped_sym, ProactiveSignal.REVERSAL_IMMINENT):
                    return ProactiveAlert(
                        symbol=symbol,
                        signal=ProactiveSignal.REVERSAL_IMMINENT,
                        timeframe='15m',
                        confidence=0.72,
                        account_id=account_id or "",
                        current_pnl_pct=pnl_pct,
                        position_side=position_side,
                        trigger_metrics={
                            'ret_60s': ret_60s,
                            'ret_5s': ret_5s,
                            'squeeze_direction': squeeze_dir,
                        },
                        suggested_action='REDUCE_50' if position_side else 'WAIT_ENTRY',
                        urgency='HIGH',
                        ts_ms=now_ms,
                        expires_ms=now_ms + 120000,
                    )
        
        # === PROACTIVE: POST_SQUEEZE_ENTRY (15m entry timing) ===
        # NOTE: Only emit if model confidence is high enough to pass downstream gates
        if not position_side and model_action and 'OPEN' in model_action.upper() and model_confidence >= 0.75:
            squeeze_mag = float(state.get('squeeze_magnitude', 0))
            
            # Squeeze just ended (low magnitude after being high)
            if squeeze_mag < 0.3 and fast_move_score < 0.4 and spoof_score < 0.35:
                scoped_sym = f"{account_id}:{symbol}" if account_id else symbol
                if self._should_emit_signal(scoped_sym, ProactiveSignal.POST_SQUEEZE_ENTRY):
                    return ProactiveAlert(
                        symbol=symbol,
                        signal=ProactiveSignal.POST_SQUEEZE_ENTRY,
                        timeframe='15m',
                        confidence=model_confidence,  # Preserve original model confidence
                        account_id=account_id or "",
                        position_side="",
                        trigger_metrics={
                            'squeeze_magnitude': squeeze_mag,
                            'spoof_score': spoof_score,
                            'fast_move_score': fast_move_score,
                            'model_action': model_action,
                        },
                        suggested_action=model_action,
                        urgency='NORMAL',
                        ts_ms=now_ms,
                        expires_ms=now_ms + 180000,  # 3 min validity for 15m
                    )
        
        # === PROACTIVE: MANIPULATION_COMPLETE (safe entry after flush) ===
        if not position_side and fast_move_score < 0.3 and spoof_score < 0.3:
            liq_burst_long = float(state.get('liq_burst_long_usd', 0))
            liq_burst_short = float(state.get('liq_burst_short_usd', 0))
            
            # Recent liquidation burst now settling
            if liq_burst_long > 200000 or liq_burst_short > 200000:  # Higher threshold for 15m
                scoped_sym = f"{account_id}:{symbol}" if account_id else symbol
                if self._should_emit_signal(scoped_sym, ProactiveSignal.MANIPULATION_COMPLETE):
                    direction = "LONG" if liq_burst_long > liq_burst_short else "SHORT"
                    return ProactiveAlert(
                        symbol=symbol,
                        signal=ProactiveSignal.MANIPULATION_COMPLETE,
                        timeframe='15m',
                        confidence=0.65,
                        account_id=account_id or "",
                        position_side="",
                        trigger_metrics={
                            'liq_burst_long': liq_burst_long,
                            'liq_burst_short': liq_burst_short,
                            'spoof_score': spoof_score,
                            'fast_move_score': fast_move_score,
                        },
                        suggested_action=f"OPEN_{direction}",
                        urgency='LOW',
                        ts_ms=now_ms,
                        expires_ms=now_ms + 300000,  # 5 min validity
                    )
        
        return None
    
    def analyze_1h_strategic(
        self,
        symbol: str,
        position_side: str,
        pnl_pct: float = 0.0,
        trend_bias: str = "",  # "BULLISH", "BEARISH", "NEUTRAL"
        account_id: str = "",
    ) -> Optional[ProactiveAlert]:
        """
        1h STRATEGIC analysis - regime/trend level signals.
        
        Can generate:
        - MOMENTUM_EXHAUSTION (trend ending)
        - SMART_MONEY_ACCUMULATION (big players loading)
        - MANIPULATION_COMPLETE (safe to enter after flush)
        """
        state = self._get_micro_state(symbol, '1h')
        if not state:
            # Fall back to aggregated 5m data
            state = self._get_micro_state(symbol, '5m')
        
        if not state:
            return None
        
        now_ms = int(time.time() * 1000)
        spoof_score, fast_move_score = self._resolve_scores(symbol, state)
        
        # === MOMENTUM_EXHAUSTION (trend level) ===
        ret_60s = float(state.get('ret_60s', 0))
        vol = float(state.get('volatility_60s', 0))
        imbalance = float(state.get('orderbook_imbalance', 0))
        
        # High vol + flat returns + balanced book = exhaustion
        if vol > 0.5 and abs(ret_60s) < 0.1 and abs(imbalance) < 0.2:
            if position_side:  # We have a position
                scoped_sym = f"{account_id}:{symbol}" if account_id else symbol
                if self._should_emit_signal(scoped_sym, ProactiveSignal.MOMENTUM_EXHAUSTION):
                    return ProactiveAlert(
                        symbol=symbol,
                        signal=ProactiveSignal.MOMENTUM_EXHAUSTION,
                        timeframe='1h',
                        confidence=0.65,
                        account_id=account_id or "",
                        current_pnl_pct=pnl_pct,
                        position_side=position_side,
                        trigger_metrics={
                            'volatility': vol,
                            'return_60s': ret_60s,
                            'imbalance': imbalance,
                        },
                        suggested_action='PARTIAL_CLOSE_30',
                        urgency='NORMAL',
                        ts_ms=now_ms,
                        expires_ms=now_ms + 300000,  # 5 min validity
                    )
        
        # === MANIPULATION_COMPLETE (for entries) ===
        if not position_side and fast_move_score < 0.3 and spoof_score < 0.3:
            # Market calmed down after manipulation
            liq_burst_long = float(state.get('liq_burst_long_usd', 0))
            liq_burst_short = float(state.get('liq_burst_short_usd', 0))
            
            # Recent liquidation burst now settling
            if liq_burst_long > 100000 or liq_burst_short > 100000:
                # Flush happened, now safe to enter counter
                scoped_sym = f"{account_id}:{symbol}" if account_id else symbol
                if self._should_emit_signal(scoped_sym, ProactiveSignal.MANIPULATION_COMPLETE):
                    direction = "LONG" if liq_burst_long > liq_burst_short else "SHORT"
                    return ProactiveAlert(
                        symbol=symbol,
                        signal=ProactiveSignal.MANIPULATION_COMPLETE,
                        timeframe='1h',
                        confidence=0.6,
                        account_id=account_id or "",
                        position_side="",
                        trigger_metrics={
                            'liq_burst_long': liq_burst_long,
                            'liq_burst_short': liq_burst_short,
                            'spoof_score': spoof_score,
                            'fast_move_score': fast_move_score,
                        },
                        suggested_action=f"OPEN_{direction}",
                        urgency='LOW',
                        ts_ms=now_ms,
                        expires_ms=now_ms + 600000,  # 10 min validity
                    )
        
        return None
    
    def analyze_hedge_opportunity(
        self,
        symbol: str,
        position_side: str,
        pnl_pct: float,
        position_size_usd: float,
        timeframe: str = "1m",
        account_id: str = "",
    ) -> Optional[ProactiveAlert]:
        """
        Analyze hedge opportunity for ANY timeframe.
        
        ALL TFs can:
        - Open hedge positions for protection
        - Close existing hedges
        - Increase hedge size
        
        This is protective action allowed even on 1m.
        """
        if not position_side:
            return None  # No position to hedge

        # Single hedge opener policy (Jan 2026): only allow proactive hedge opens when selected.
        try:
            from config import HEDGE_OPEN_POLICY
            hop = str(HEDGE_OPEN_POLICY or "").strip().lower()
            if hop not in ("proactive_microstructure", "always_hedge"):
                return None
        except Exception:
            pass
        
        state = self._get_micro_state(symbol, timeframe)
        if not state:
            return None

        spoof_score, fast_move_score = self._resolve_scores(symbol, state)
        now_ms = int(time.time() * 1000)

        # ------------------------------------------------------------------
        # DYNAMIC HEDGE SCORING (no brittle static thresholds)
        # ------------------------------------------------------------------
        # We compute a continuous risk score from:
        # - manipulation signals (spoof/fast-move), staleness-aware
        # - fast move magnitude vs realized micro vol (ret vs vol)
        # - liquidation proximity + liquidation burst intensity
        # - loss severity (normalized by expected move)
        #
        # Then we derive hedge sizing as a smooth function of risk (non-linear),
        # and only emit a hedge when the notional is meaningful (>= exchange min).
        def _f(k: str, default: float = 0.0) -> float:
            try:
                v = state.get(k, default)
                return float(v) if v is not None else float(default)
            except Exception:
                return float(default)

        # Core micro returns/vol proxies (best-effort; may be 0 if insufficient history)
        ret_15s = _f("ret_15s", 0.0)
        ret_60s = _f("ret_60s", 0.0)
        accel_15s = _f("accel_15s", 0.0)
        vol_30s = _f("volatility_30s", _f("volatility_60s", 0.0))
        churn_score = _f("churn_score", 0.0)
        snapback_score = _f("snapback_score", 0.0)

        # Data freshness / quality (msnap router populates these when available)
        micro_quality = _f("micro_quality_score", 1.0)
        micro_quality = max(0.0, min(1.0, micro_quality))
        staleness_ms = _f("micro_staleness_ms", 0.0)
        # Fallback: derive staleness from updated_ts_ms if present
        if staleness_ms <= 0.0:
            try:
                updated_ts_ms = int(float(state.get("updated_ts_ms", 0) or 0))
                if updated_ts_ms > 0:
                    staleness_ms = float(max(0, now_ms - updated_ts_ms))
            except Exception:
                staleness_ms = 0.0
        freshness_decay = 1.0 / (1.0 + (max(0.0, staleness_ms) / 1000.0))
        data_quality = max(0.0, min(1.0, micro_quality * freshness_decay))

        # Liquidation context for the CURRENT position side
        if position_side == "LONG":
            liq_distance = _f("liq_distance_long_pct", 100.0)
            liq_burst = _f("liq_burst_long_usd", 0.0)
            ret_against = max(0.0, -ret_15s)
            against_dir = -1.0  # down move is against LONG
        else:
            liq_distance = _f("liq_distance_short_pct", 100.0)
            liq_burst = _f("liq_burst_short_usd", 0.0)
            ret_against = max(0.0, ret_15s)
            against_dir = 1.0  # up move is against SHORT

        pnl_loss = max(0.0, -float(pnl_pct or 0.0))

        # Noise / expected move scale (all in % units)
        noise_scale = max(abs(vol_30s), abs(ret_60s) / 4.0, 1e-9)
        expected_move = max(abs(ret_60s), abs(vol_30s) * 2.0, 1e-9)

        # Manipulation score (staleness-aware)
        manip_raw = max(float(spoof_score or 0.0), float(fast_move_score or 0.0))
        manip = max(0.0, min(1.0, float(manip_raw))) * float(data_quality)

        # Move-against severity (vs realized noise)
        move_ratio = float(ret_against) / float(noise_scale) if noise_scale > 0 else 0.0
        move_ratio = max(0.0, move_ratio)
        move_factor = move_ratio / (1.0 + move_ratio)  # smooth 0..1

        # Liquidation risk: proximity (vs expected move) × burst intensity (vs position size)
        liq_distance = max(0.0, float(liq_distance))
        liq_close = float(expected_move) / (float(expected_move) + float(liq_distance) + 1e-9)
        liq_close = max(0.0, min(1.0, liq_close))
        burst_scale = max(1.0, float(position_size_usd or 0.0))
        burst_factor = math.tanh(max(0.0, float(liq_burst)) / burst_scale)  # 0..1
        liq_factor = max(0.0, min(1.0, float(liq_close) * float(burst_factor)))

        # Loss severity vs expected move
        loss_factor = float(pnl_loss) / (float(pnl_loss) + float(expected_move) + 1e-9) if pnl_loss > 0 else 0.0
        loss_factor = max(0.0, min(1.0, loss_factor))

        # Acceleration against the position: accelerating moves are more likely to persist.
        accel_signed = float(accel_15s) * float(against_dir)
        accel_pos = max(0.0, accel_signed)
        accel_factor = float(accel_pos) / (float(accel_pos) + float(noise_scale) + 1e-9)  # 0..1
        accel_factor = max(0.0, min(1.0, accel_factor))

        # Fakeout dampener: snapback + deceleration (classic stop-hunt pattern).
        snapback = max(0.0, min(1.0, float(snapback_score)))
        churn = max(0.0, min(1.0, float(churn_score)))
        fakeout = max(0.0, min(1.0, (snapback * (1.0 - accel_factor)) + (0.5 * churn)))

        # Probabilistic OR to combine risks (continuous, no step gates)
        risk = 1.0 - ((1.0 - manip) * (1.0 - move_factor) * (1.0 - liq_factor) * (1.0 - loss_factor))
        risk = max(0.0, min(1.0, float(risk)))
        risk_adj = risk * (1.0 - (0.8 * fakeout))
        risk_adj = max(0.0, min(1.0, float(risk_adj)))

        # Track risk history (account-scoped) and derive urgency as a percentile rank.
        scoped_sym = f"{account_id}:{symbol}" if account_id else symbol
        hist = self._hedge_risk_history.get(scoped_sym)
        if hist is None:
            hist = deque(maxlen=self._hedge_risk_history_maxlen)
            self._hedge_risk_history[scoped_sym] = hist
        # Percentile rank vs recent history (adaptive regime-based urgency)
        if len(hist) >= 20:
            xs = sorted(hist)
            # fraction of values <= current
            rank = float(bisect.bisect_right(xs, risk_adj)) / float(len(xs))
        else:
            rank = float(risk_adj)  # bootstrap
        hist.append(float(risk_adj))

        # Map rank → urgency bucket (relative to recent regime, not absolute thresholds).
        if rank >= 0.90:
            hedge_urgency = "CRITICAL"
        elif rank >= 0.80:
            hedge_urgency = "HIGH"
        elif rank >= 0.60:
            hedge_urgency = "NORMAL"
        else:
            hedge_urgency = "LOW"

        # Hedge sizing: non-linear mapping (small risk -> tiny hedges, big risk -> meaningful coverage).
        try:
            from config import ADAPTIVE_HEDGE_MAX_SIZE_PCT
            max_pct = float(ADAPTIVE_HEDGE_MAX_SIZE_PCT)
        except Exception:
            max_pct = 50.0
        max_pct = max(0.0, min(100.0, float(max_pct)))
        # Allow liquidation-driven expansion (still capped) without hard thresholds.
        max_pct_eff = max_pct * (1.0 + 0.5 * float(liq_factor))
        max_pct_eff = max(0.0, min(100.0, float(max_pct_eff)))

        hedge_size_pct = float(max_pct_eff) * (float(risk_adj) ** 3.0)
        hedge_size_pct = max(0.0, min(100.0, hedge_size_pct))

        # Compute hedge notional
        try:
            pos_notional = float(position_size_usd or 0.0)
        except Exception:
            pos_notional = 0.0
        hedge_notional_usd = max(0.0, float(pos_notional) * (float(hedge_size_pct) / 100.0))

        # Exchange min notional guard (prevents trainer from bumping tiny hedges into existence on low-risk noise).
        effective_min_notional = 0.0
        try:
            from config import MIN_NOTIONAL_USD, BINANCE_FUTURES_MIN_NOTIONAL_USD_BY_SYMBOL
            sym_min = float((BINANCE_FUTURES_MIN_NOTIONAL_USD_BY_SYMBOL or {}).get(symbol, MIN_NOTIONAL_USD) or MIN_NOTIONAL_USD)
            effective_min_notional = max(float(MIN_NOTIONAL_USD or 0.0), float(sym_min or 0.0))
        except Exception:
            effective_min_notional = 0.0

        if hedge_urgency == "LOW":
            return None
        if pos_notional <= 0.0:
            return None
        if effective_min_notional > 0.0 and hedge_notional_usd < float(effective_min_notional):
            return None

        hedge_side = "SHORT" if position_side == "LONG" else "LONG"
        signal_type = ProactiveSignal.HEDGE_OPEN_SHORT if hedge_side == "SHORT" else ProactiveSignal.HEDGE_OPEN_LONG

        if self._should_emit_signal(scoped_sym, signal_type):
            hedge_reason = (
                f"dyn_risk:risk={risk_adj:.2f},rank={rank:.2f},"
                f"manip={manip:.2f},move={move_factor:.2f},liq={liq_factor:.2f},loss={loss_factor:.2f},"
                f"fakeout={fakeout:.2f},q={data_quality:.2f}"
            )
            return ProactiveAlert(
                symbol=symbol,
                signal=signal_type,
                timeframe=timeframe,
                confidence=max(0.0, min(0.95, 0.50 + 0.45 * float(risk_adj))),
                account_id=account_id or "",
                current_pnl_pct=pnl_pct,
                position_side=position_side,
                trigger_metrics={
                    # Raw scores
                    "spoof_score": float(spoof_score or 0.0),
                    "fast_move_score": float(fast_move_score or 0.0),
                    "snapback_score": float(snapback_score or 0.0),
                    "churn_score": float(churn_score or 0.0),
                    # Returns/vol (percent)
                    "ret_15s": float(ret_15s),
                    "ret_60s": float(ret_60s),
                    "accel_15s": float(accel_15s),
                    "volatility_30s": float(vol_30s),
                    # Quality
                    "micro_staleness_ms": float(staleness_ms),
                    "micro_quality_score": float(micro_quality),
                    "data_quality": float(data_quality),
                    # Liquidation
                    "liq_distance_pct": float(liq_distance),
                    "liq_burst_usd": float(liq_burst),
                    # Risk breakdown
                    "risk_raw": float(risk),
                    "risk_adj": float(risk_adj),
                    "risk_rank": float(rank),
                    "risk_manip": float(manip),
                    "risk_move": float(move_factor),
                    "risk_liq": float(liq_factor),
                    "risk_loss": float(loss_factor),
                    "fakeout": float(fakeout),
                    # Sizing outputs
                    "hedge_size_pct": float(hedge_size_pct),
                    "hedge_notional_usd": float(hedge_notional_usd),
                },
                # Use canonical trader-recognized action; sizing provided via trigger_metrics.
                suggested_action=f"OPEN_HEDGE_{hedge_side}",
                urgency=hedge_urgency,
                ts_ms=now_ms,
                expires_ms=now_ms + 30000,  # Short validity for hedges
            )
        
        return None
    
    def analyze_all_timeframes(
        self,
        symbol: str,
        position_side: str = "",
        pnl_pct: float = 0.0,
        model_action: str = "",
        model_confidence: float = 0.0,
        position_size_usd: float = 0.0,
        account_id: str = "",
    ) -> List[ProactiveAlert]:
        """
        Run full multi-TF analysis for a symbol.
        
        Returns list of all active proactive signals, sorted by urgency.
        
        TF Rules (PRODUCTION CONTRACT):
        - 1m: Protective + Hedge ONLY (never opens new risk when flat)
        - 5m: Protective + Hedge + Proactive (full trading)
        - 15m: Protective + Hedge + Proactive (full trading)
        - 1h: Protective + Hedge + Proactive (full trading)
        
        Proactive Entry TFs: 5m, 15m, 1h
        """
        alerts = []
        
        # === ALL TFs: Hedge analysis (highest priority) ===
        if position_side:
            # Prefer higher-quality TF context first; fall back to 1m only when others don't trigger.
            for tf in ['5m', '15m', '1h', '1m']:
                hedge_alert = self.analyze_hedge_opportunity(
                    symbol, position_side, pnl_pct, position_size_usd, tf, account_id=account_id
                )
                if hedge_alert:
                    alerts.append(hedge_alert)
                    break  # Only one hedge signal needed
        
        # === 1m: Protective only (highest priority for exits) ===
        if position_side:
            alert_1m = self.analyze_1m_protective(symbol, position_side, pnl_pct, account_id=account_id)
            if alert_1m:
                alerts.append(alert_1m)
        
        # === 5m: Tactical (protective + proactive + full trading) ===
        alert_5m = self.analyze_5m_tactical(
            symbol, position_side, pnl_pct, model_action, model_confidence, account_id=account_id
        )
        if alert_5m:
            alerts.append(alert_5m)
        
        # === 15m: Tactical (protective + proactive + full trading) ===
        alert_15m = self.analyze_15m_tactical(
            symbol, position_side, pnl_pct, model_action, model_confidence, account_id=account_id
        )
        if alert_15m:
            alerts.append(alert_15m)
        
        # === 1h: Strategic (trend level + full trading) ===
        alert_1h = self.analyze_1h_strategic(symbol, position_side, pnl_pct, account_id=account_id)
        if alert_1h:
            alerts.append(alert_1h)
        
        # Sort by urgency (CRITICAL first)
        urgency_order = {'CRITICAL': 0, 'HIGH': 1, 'NORMAL': 2, 'LOW': 3}
        alerts.sort(key=lambda a: urgency_order.get(a.urgency, 2))
        
        # Log alerts
        for alert in alerts:
            logger.info(alert.to_log_line())
        
        return alerts
    
    def get_highest_priority_action(
        self,
        symbol: str,
        position_side: str = "",
        pnl_pct: float = 0.0,
        model_action: str = "",
        model_confidence: float = 0.0,
        position_size_usd: float = 0.0,
        account_id: str = "",
    ) -> Optional[ProactiveAlert]:
        """
        Get the single highest priority proactive action for a symbol.
        
        Useful for integration with trainer/trader decision making.
        """
        alerts = self.analyze_all_timeframes(
            symbol, position_side, pnl_pct, model_action, model_confidence, position_size_usd, account_id=account_id
        )
        
        if alerts:
            return alerts[0]
        return None
    
    def publish_to_redis(self, alert: ProactiveAlert):
        """Publish proactive alert to Redis stream."""
        if not self.redis:
            return
        
        try:
            # Redis Streams require flat field->value pairs (values must be str/bytes/int/float).
            # `ProactiveAlert.to_dict()` contains a nested `trigger_metrics` dict, so we
            # serialize it to JSON to avoid silent publish failures.
            import json
            payload = alert.to_dict()
            flat = {}
            for k, v in (payload or {}).items():
                if isinstance(v, (dict, list, tuple)):
                    flat[k] = json.dumps(v, separators=(",", ":"))
                elif v is None:
                    flat[k] = ""
                else:
                    # Keep as-is for str/bytes/numbers; otherwise stringify.
                    flat[k] = v if isinstance(v, (str, bytes, int, float)) else str(v)
            self.redis.xadd(
                "signals:proactive:alerts",
                flat,
                maxlen=1000,
                approximate=True,
            )
        except Exception as e:
            logger.debug(f"[PROACTIVE] Failed to publish alert: {e}")


# Singleton instance
_proactive_analyzer: Optional[MicrostructureProactiveAnalyzer] = None


def get_proactive_analyzer(redis_client=None) -> MicrostructureProactiveAnalyzer:
    """Get or create the proactive analyzer singleton."""
    global _proactive_analyzer
    
    if _proactive_analyzer is None:
        _proactive_analyzer = MicrostructureProactiveAnalyzer(redis_client=redis_client)
    elif redis_client and _proactive_analyzer.redis is None:
        _proactive_analyzer.redis = redis_client
    
    return _proactive_analyzer


def is_proactive_enabled() -> bool:
    """Check if proactive microstructure is enabled."""
    # Use config.py value (default true) instead of hardcoded false
    return os.getenv("ENABLE_MICROSTRUCTURE_PROACTIVE", "true").lower() in ("1", "true", "yes")

