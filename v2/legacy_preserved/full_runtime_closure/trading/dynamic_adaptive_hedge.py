#!/usr/bin/env python3
"""
Dynamic Adaptive Hedge System
=============================

Intelligent hedge building driven by multiple data sources:
- Microstructure (order flow, spoofing, fast moves, trade intensity)
- Liquidation levels and squeeze potential
- Volatility (ATR, realized vol, regime detection)
- Open Interest and Funding Rate
- TA-LIB indicators (RSI, MACD, ADX, BBands, etc.)
- Unified features from Redis
- Live websocket data (mark price, depth, trades)

This creates protective hedges dynamically based on market conditions,
not just static ROE thresholds.
"""

import os
import time
import json
import logging
from typing import Dict, Optional, Tuple, List, Any
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum

logger = logging.getLogger(__name__)


class HedgeUrgency(Enum):
    """Urgency level for hedge action"""
    NONE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


class HedgeReason(Enum):
    """Reason for hedge recommendation"""
    NONE = "none"
    ROE_LOSS = "roe_loss"
    ROE_PROFIT_LOCK = "roe_profit_lock"
    VOLATILITY_SPIKE = "volatility_spike"
    LIQUIDATION_RISK = "liquidation_risk"
    MICROSTRUCTURE_ADVERSE = "microstructure_adverse"
    FAST_MOVE_AGAINST = "fast_move_against"
    TECHNICAL_REVERSAL = "technical_reversal"
    FUNDING_EXTREME = "funding_extreme"
    OI_SURGE = "oi_surge"
    SQUEEZE_POTENTIAL = "squeeze_potential"
    TREND_REVERSAL = "trend_reversal"


@dataclass
class HedgeRecommendation:
    """Recommendation from the adaptive hedge system"""
    symbol: str
    position_side: str  # LONG or SHORT
    should_hedge: bool
    hedge_side: str  # Side to open hedge (opposite of position)
    hedge_size_pct: float  # % of position to hedge (dynamic 0-~max)
    urgency: HedgeUrgency
    primary_reason: HedgeReason
    secondary_reasons: List[HedgeReason] = field(default_factory=list)
    
    # Context
    current_roe_pct: float = 0.0
    risk_score: float = 0.0  # 0-1 composite risk score
    confidence: float = 0.0  # 0-1 confidence in recommendation
    
    # Timing
    cooldown_remaining_sec: int = 0
    recommended_ttl_sec: int = 300  # How long hedge should remain
    
    # Debug
    factors: Dict[str, float] = field(default_factory=dict)
    
    def to_log_line(self) -> str:
        reasons = [self.primary_reason.value]
        if self.secondary_reasons:
            reasons.extend([r.value for r in self.secondary_reasons[:2]])
        return (
            f"HEDGE_REC | {self.symbol} {self.position_side} | "
            f"hedge={self.should_hedge} | size={self.hedge_size_pct:.0f}% | "
            f"urgency={self.urgency.name} | roe={self.current_roe_pct:.1f}% | "
            f"risk={self.risk_score:.2f} | reasons={','.join(reasons)}"
        )


class DynamicAdaptiveHedge:
    """
    Intelligent hedge building system.
    
    Analyzes multiple data sources to determine:
    1. WHEN to open a hedge (timing based on conditions)
    2. HOW MUCH to hedge (sizing based on risk level)
    3. HOW LONG to hold the hedge (TTL based on conditions)
    4. WHEN to close the hedge (condition-based unwinding)
    """
    
    def __init__(self, redis_client=None, config=None):
        self.redis = redis_client
        self.config = config
        
        # Load config
        self.enabled = os.getenv("ADAPTIVE_HEDGE_ENABLED", "true").lower() in ["1", "true", "yes"]
        self.max_size_pct = float(os.getenv("ADAPTIVE_HEDGE_MAX_SIZE_PCT", "50.0"))
        # NOTE: Historically we used a static 10% minimum hedge size. This caused
        # over-hedging in calm regimes and unnecessary fees.
        #
        # Keep the env var for backwards compatibility, but default to 0.0 and
        # do NOT enforce it. Hedge sizing is now continuous/dynamic.
        try:
            self.min_size_pct = float(os.getenv("ADAPTIVE_HEDGE_MIN_SIZE_PCT", "0.0"))
        except Exception:
            self.min_size_pct = 0.0
        # NOTE: We intentionally avoid static ROE thresholds in the hedge engine.
        # Unwind decisions should be derived from the same dynamic risk model used for opening.
        # Keep the env var for backwards compatibility, but default to 0.0 and do not use it as a gate.
        try:
            self.unwind_roe = float(os.getenv("ADAPTIVE_HEDGE_UNWIND_ROE", "0.0"))
        except Exception:
            self.unwind_roe = 0.0
        self.cooldown_sec = int(os.getenv("ADAPTIVE_HEDGE_COOLDOWN_SEC", "60"))
        # Emergency-only mode:
        # When enabled, we ONLY open/size hedges off emergency drivers:
        # - liquidation risk
        # - microstructure adverse
        # - adverse trend pressure
        #
        # We explicitly do NOT open hedges solely because the position is underwater (roe_loss),
        # as that tends to create chronic over-hedging / 1:1 cages in trending markets.
        self.emergency_only = os.getenv("ADAPTIVE_HEDGE_EMERGENCY_ONLY", "true").lower() in ["1", "true", "yes"]
        
        # SAFETY HEDGE (fully dynamic)
        # We do NOT use static thresholds like "-45% ROE". Instead, we compute risk from:
        # - volatility (NATR / realized vol)
        # - liquidation buffer (distance-to-liquidation vs expected move)
        # - trend pressure & microstructure (fast moves / imbalance / spoof)
        #
        # Noise tolerance: treat tiny deltas as already hedged.
        try:
            self.safety_hedge_min_delta_pct = float(os.getenv("SAFETY_HEDGE_MIN_DELTA_PCT", "0.25"))
        except Exception:
            self.safety_hedge_min_delta_pct = 0.25
        
        # State tracking
        self._last_hedge_action: Dict[str, float] = {}  # symbol -> timestamp
        self._active_hedges: Dict[str, Dict] = {}  # symbol -> hedge_info
        self._cache: Dict[str, Tuple[Any, float]] = {}  # cache for expensive lookups
        self._cache_ttl = 2  # seconds
        
        # Intelligence engine integration
        self._intelligence_engine = None
        self._use_intelligence_engine = os.getenv("USE_HEDGE_INTELLIGENCE_ENGINE", "true").lower() in ["1", "true", "yes"]
        
        logger.info(
            f"DynamicAdaptiveHedge initialized | enabled={self.enabled} | "
            f"max_size={self.max_size_pct}% | "
            f"intelligence_engine={self._use_intelligence_engine} | "
            f"emergency_only={self.emergency_only}"
        )
    
    def evaluate_hedge(
        self,
        symbol: str,
        position_side: str,
        entry_price: float,
        current_price: float,
        position_size: float,
        position_notional_usd: float,
        leverage: int = 10,
        features: Optional[Dict] = None,
        microstructure: Optional[Dict] = None,
        liquidation_data: Optional[Dict] = None,
        websocket_data: Optional[Dict] = None,
        is_already_hedged: bool = False,
        opposite_side_size: float = 0.0,
    ) -> HedgeRecommendation:
        """
        Evaluate whether to open/adjust a hedge for the position.
        
        Args:
            symbol: Trading pair
            position_side: LONG or SHORT
            entry_price: Position entry price
            current_price: Current mark price
            position_size: Position quantity
            position_notional_usd: Position value in USD
            leverage: Position leverage
            features: Unified features from Redis
            microstructure: Microstructure data
            liquidation_data: Liquidation level data
            websocket_data: Live websocket data
            is_already_hedged: True if symbol already has opposite position
            opposite_side_size: Size of existing hedge (opposite side)
        
        Returns:
            HedgeRecommendation with decision and sizing
        """
        if not self.enabled:
            return self._no_hedge_recommendation(symbol, position_side)

        # Current hedge coverage (if already hedged). We no longer hard-skip at a
        # fixed percentage; instead we compute a dynamic TARGET hedge coverage and
        # only add the delta needed to reach it.
        hedge_coverage_pct = 0.0
        try:
            if is_already_hedged and opposite_side_size > 0 and position_size > 0:
                hedge_coverage_pct = (float(opposite_side_size) / float(position_size)) * 100.0
        except Exception:
            hedge_coverage_pct = 0.0
        
        features = features or self._get_features_from_redis(symbol)
        microstructure = microstructure or {}
        liquidation_data = liquidation_data or {}
        websocket_data = websocket_data or {}
        
        # Calculate current ROE
        if position_side == 'LONG':
            price_pnl_pct = (current_price - entry_price) / entry_price * 100
        else:
            price_pnl_pct = (entry_price - current_price) / entry_price * 100
        
        roe_pct = price_pnl_pct * leverage
        
        # Check cooldown
        last_action = self._last_hedge_action.get(symbol, 0)
        cooldown_remaining = max(0, int(self.cooldown_sec - (time.time() - last_action)))
        
        factors = {'roe_pct': roe_pct, 'price_pnl_pct': price_pnl_pct}
        factors['hedge_coverage_pct'] = float(hedge_coverage_pct)
        reasons = []
        risk_score = 0.0

        # ── SHARED CONTEXT: enrich factors with market-wide awareness ──
        try:
            from trading.hedge_context import get_hedge_context
            _hctx = get_hedge_context(self.redis)
            if _hctx and _hctx.is_enabled():
                _snap = _hctx.get_snapshot(symbol)
                factors['ctx_mark_price'] = _snap.mark_price
                factors['ctx_direction_score'] = _snap.direction_score()
                factors['ctx_rsi_15m'] = _snap.rsi_15m
                factors['ctx_natr_15m'] = _snap.natr_15m
                factors['ctx_funding_rate'] = _snap.funding_rate
                factors['ctx_oi_change_1h'] = _snap.oi_change_pct_1h
                factors['ctx_ob_imbalance'] = _snap.orderbook_imbalance
                factors['ctx_peer_adds_5m'] = _snap.total_hedge_adds_last_5m
                factors['ctx_peer_trims_5m'] = _snap.total_hedge_trims_last_5m
                factors['ctx_volatility_regime'] = _snap.volatility_regime
                if _snap.trainer:
                    factors['ctx_trainer_direction'] = _snap.trainer.consensus_direction
                    factors['ctx_trainer_confidence'] = _snap.trainer.consensus_confidence
                    factors['ctx_trainer_target_price'] = _snap.trainer.target_price
                    factors['ctx_trainer_age_sec'] = _snap.trainer.age_sec
                logger.debug(
                    "🧠 ADAPTIVE_HEDGE_CTX | %s %s | dir_score=%.2f rsi=%.0f natr=%.2f "
                    "funding=%.5f peer_adds=%d vol=%s trainer=%s",
                    symbol, position_side, _snap.direction_score(), _snap.rsi_15m,
                    _snap.natr_15m, _snap.funding_rate, _snap.total_hedge_adds_last_5m,
                    _snap.volatility_regime,
                    _snap.trainer.consensus_direction if _snap.trainer else "N/A",
                )
        except Exception as _ctx_err:
            logger.debug("ADAPTIVE_HEDGE_CTX_LOAD_ERR | %s | %s", symbol, _ctx_err)

        # ========================================================================
        # ANALYZE ALL DATA SOURCES (dynamic, no static thresholds)
        # ========================================================================

        def _to_float(x, default=0.0) -> float:
            try:
                if x is None or x == "":
                    return float(default)
                return float(x)
            except Exception:
                return float(default)

        # Volatility proxy (prefer NATR which is already in % units).
        atr_candidates = [
            _to_float(features.get("ind_ta_NATR_14_15m", 0.0)),
            _to_float(features.get("ind_ta_NATR_14_1h", 0.0)),
            _to_float(features.get("ind_ta_NATR_14_5m", 0.0)),
            _to_float(features.get("ind_ta_NATR_14_1m", 0.0)),
        ]
        atr_pct = max([v for v in atr_candidates if v > 0.0] or [0.0])
        # Fallback: realized vol fields are typically fractions (e.g. 0.005 => 0.5%).
        if atr_pct <= 0.0:
            vol_fallback = max(
                _to_float(features.get("ccxt_volatility_1h", 0.0)),
                _to_float(features.get("ccxt_volatility_5m", 0.0)),
                _to_float(features.get("ind_ta_volatility_1h", 0.0)),
                _to_float(features.get("ind_ta_volatility_5m", 0.0)),
            )
            if vol_fallback > 0:
                atr_pct = vol_fallback * 100.0
        factors["atr_pct"] = float(atr_pct)

        # Trend pressure ([-1,1]) – adverse direction increases hedge risk.
        pressure = _to_float(features.get("ind_ind_15m_pressure", features.get("ind_ta_pressure", 0.0)), 0.0)
        try:
            pressure = max(-1.0, min(1.0, float(pressure)))
        except Exception:
            pressure = 0.0
        if position_side == "SHORT":
            trend_risk = max(0.0, pressure)  # bullish pressure hurts shorts
        else:
            trend_risk = max(0.0, -pressure)  # bearish pressure hurts longs
        trend_risk = max(0.0, min(1.0, float(trend_risk)))
        factors["trend_pressure"] = float(pressure)
        factors["trend_risk"] = float(trend_risk)

        # Microstructure risk (0..1): prefer live msnap scores if present.
        #
        # CRITICAL (Jan 2026):
        # We must treat micro signals as **directional**. Using |imbalance| can create
        # "mystery hedges" where we hedge even when the book pressure is in our favor.
        #
        # - Spoof score: always treated as risk (manipulation)
        # - Imbalance: risk only when it is *against* the current position
        # - Fast-move: risk only when the short-horizon return is *against* the position
        fm0 = _to_float(microstructure.get("fast_move_score", 0.0), 0.0)
        fm1 = _to_float(microstructure.get("fast_move_max_1m", 0.0), 0.0)
        fm5 = _to_float(microstructure.get("fast_move_max_5m", 0.0), 0.0)
        fm15 = _to_float(microstructure.get("fast_move_max_15m", 0.0), 0.0)
        fmf = _to_float(features.get("fast_move_score", 0.0), 0.0)
        fast_move = max(float(fm0), float(fm1), float(fm5), float(fm15), float(fmf))

        spoof = _to_float(microstructure.get("spoof_score", features.get("spoof_score", 0.0)), 0.0)

        # Prefer the overlay/book imbalance field; fall back to msnap imbalance_5 if present.
        raw_imb = _to_float(
            features.get("ob_ob_imbalance", microstructure.get("imbalance_5", features.get("imbalance_5", 0.0))),
            0.0,
        )
        try:
            raw_imb_f = float(raw_imb)
        except Exception:
            raw_imb_f = 0.0
        if position_side == "LONG":
            adverse_imb = max(0.0, -raw_imb_f)
        else:
            adverse_imb = max(0.0, raw_imb_f)
        # imbalance is typically in [-1, +1]
        adverse_imb = max(0.0, min(1.0, float(adverse_imb)))

        # Short-horizon direction: if we have micro returns, use them; otherwise fall back
        # to the current price change sign (best-effort).
        ret_15s = _to_float(microstructure.get("ret_15s", features.get("ret_15s", 0.0)), 0.0)
        if position_side == "LONG":
            adverse_dir = 1.0 if float(ret_15s) < 0.0 else 0.0
        else:
            adverse_dir = 1.0 if float(ret_15s) > 0.0 else 0.0
        fast_move_risk = max(0.0, min(1.0, float(fast_move))) * float(adverse_dir)

        micro_risk = max(0.0, min(1.0, max(float(spoof), float(adverse_imb), float(fast_move_risk))))
        # Staleness-aware dampening for micro signals (avoid false urgency on stale snapshots).
        #
        # IMPORTANT:
        # `src_staleness_ms` stored in Redis is computed at *publish time* by the ingestor.
        # If the feed stalls, that field does NOT update and may remain "0" forever.
        #
        # Therefore we always recompute effective staleness from `updated_ts_ms` when available.
        staleness_ms = _to_float(features.get("src_staleness_ms", 0.0), 0.0)
        try:
            updated_ts_ms = _to_float(features.get("updated_ts_ms", 0.0), 0.0)
            if updated_ts_ms > 0:
                now_ms = float(time.time() * 1000.0)
                staleness_ms = max(0.0, float(now_ms - float(updated_ts_ms)))
        except Exception:
            pass

        quality = _to_float(features.get("src_quality_score", 1.0), 1.0)
        try:
            quality = max(0.0, min(1.0, float(quality)))
        except Exception:
            quality = 1.0
        # Continuous decay: 0ms -> 1.0, 1000ms -> 0.5, 5000ms -> ~0.17
        micro_decay = 1.0 / (1.0 + (max(0.0, staleness_ms) / 1000.0))
        micro_risk = micro_risk * quality * micro_decay
        micro_risk = max(0.0, min(1.0, float(micro_risk)))
        factors["micro_fast_move_score"] = float(fast_move)
        factors["micro_spoof_score"] = float(spoof)
        factors["micro_imbalance_raw"] = float(raw_imb_f)
        factors["micro_imbalance_adverse"] = float(adverse_imb)
        factors["micro_ret_15s"] = float(ret_15s)
        factors["micro_fast_move_adverse_dir"] = float(adverse_dir)
        factors["micro_risk"] = float(micro_risk)

        # Loss severity vs volatility (0..1).
        loss_pct = max(0.0, -float(price_pnl_pct))
        denom = max(1e-9, float(atr_pct))
        loss_risk = loss_pct / (loss_pct + denom) if loss_pct > 0 else 0.0
        loss_risk = max(0.0, min(1.0, float(loss_risk)))
        factors["loss_pct"] = float(loss_pct)
        factors["loss_risk"] = float(loss_risk)

        # Liquidation buffer risk (0..1): compare expected move (atr_pct) vs distance-to-liquidation.
        liq_price = _to_float(
            (liquidation_data or {}).get("liquidation_price")
            or (liquidation_data or {}).get("liquidationPrice")
            or (liquidation_data or {}).get("liq_price")
            or 0.0,
            0.0,
        )
        liq_buffer_pct = None
        if liq_price > 0 and current_price and current_price > 0:
            try:
                if position_side == "LONG":
                    liq_buffer_pct = ((float(current_price) - float(liq_price)) / float(current_price)) * 100.0
                else:
                    liq_buffer_pct = ((float(liq_price) - float(current_price)) / float(current_price)) * 100.0
            except Exception:
                liq_buffer_pct = None
        if liq_buffer_pct is not None:
            try:
                liq_buffer_pct = max(0.0, float(liq_buffer_pct))
            except Exception:
                liq_buffer_pct = 0.0
            liq_risk = float(atr_pct) / (float(atr_pct) + float(liq_buffer_pct) + 1e-9) if float(atr_pct) > 0 else 0.0
            liq_risk = max(0.0, min(1.0, float(liq_risk)))
        else:
            liq_risk = 0.0
        factors["liquidation_price"] = float(liq_price)
        factors["liq_buffer_pct"] = float(liq_buffer_pct or 0.0)
        factors["liq_risk"] = float(liq_risk)

        # Combine risks without static thresholds (probabilistic OR).
        total_risk_score = 1.0 - ((1.0 - loss_risk) * (1.0 - liq_risk) * (1.0 - micro_risk) * (1.0 - trend_risk))
        total_risk_score = max(0.0, min(1.0, float(total_risk_score)))
        factors["total_risk_score"] = float(total_risk_score)

        # Emergency-only risk score ignores underwater-only loss to prevent 1:1 hedge spirals.
        emergency_risk_score = 1.0 - ((1.0 - liq_risk) * (1.0 - micro_risk) * (1.0 - trend_risk))
        emergency_risk_score = max(0.0, min(1.0, float(emergency_risk_score)))
        factors["emergency_risk_score"] = float(emergency_risk_score)

        # Use emergency-only score for sizing/decision if enabled.
        risk_score = float(emergency_risk_score if self.emergency_only else total_risk_score)
        factors["effective_risk_score"] = float(risk_score)

        # Reasons (best-effort): whichever component dominates.
        # Dominant driver for urgency/reason:
        # In emergency-only mode, do NOT let loss dominate (it should not trigger hedges).
        dom = max(
            ("liq", liq_risk),
            ("micro", micro_risk),
            ("trend", trend_risk),
            (("loss", loss_risk) if not self.emergency_only else ("loss", -1.0)),
            key=lambda x: float(x[1]),
        )[0]
        if dom == "liq":
            reasons.append(HedgeReason.LIQUIDATION_RISK)
        elif dom == "micro":
            reasons.append(HedgeReason.MICROSTRUCTURE_ADVERSE if micro_risk > 0 else HedgeReason.NONE)
        elif dom == "trend":
            reasons.append(HedgeReason.TREND_REVERSAL)
        else:
            reasons.append(HedgeReason.ROE_LOSS if loss_risk > 0 else HedgeReason.NONE)
        
        # ========================================================================
        # DETERMINE HEDGE DECISION
        # ========================================================================
        
        # Target hedge coverage is continuous (0..max_size_pct) derived from risk_score.
        target_total_hedge_pct = max(0.0, min(float(self.max_size_pct), float(self.max_size_pct) * float(risk_score)))

        # ── CONTEXT-DRIVEN SIZE SCALING ──
        # Scale the target coverage using market data (vol regime, liq proximity, trainer)
        try:
            _ctx_vol_mult = factors.get("vol_mult", 1.0)  # Already set if context loaded
            _ctx_liq_mult = factors.get("liq_mult", 1.0)
            # Derive multipliers from context snapshot if available
            ctx_natr = factors.get("ctx_natr_15m", 0.0)
            ctx_vol = (factors.get("ctx_volatility_regime") or "NORMAL").upper()
            if ctx_vol == "EXTREME" or ctx_natr > 3.0:
                _ctx_vol_mult = 1.4
            elif ctx_vol == "HIGH" or ctx_natr > 1.5:
                _ctx_vol_mult = 1.2
            elif ctx_vol == "LOW" or (0 < ctx_natr < 0.3):
                _ctx_vol_mult = 0.7

            # Trainer opposing position → hedge more; trainer agreeing → hedge less
            _ctx_trainer_mult = 1.0
            _t_dir = factors.get("ctx_trainer_direction", "NEUTRAL")
            _t_conf = factors.get("ctx_trainer_confidence", 0.0)
            _t_age = factors.get("ctx_trainer_age_sec", 9999)
            if _t_age < 300 and _t_conf > 0.5:
                if (position_side == "LONG" and _t_dir in ("SHORT", "BEARISH")) or \
                   (position_side == "SHORT" and _t_dir in ("LONG", "BULLISH")):
                    _ctx_trainer_mult = 1.0 + (_t_conf - 0.5) * 0.5
                elif (position_side == "LONG" and _t_dir in ("LONG", "BULLISH")) or \
                     (position_side == "SHORT" and _t_dir in ("SHORT", "BEARISH")):
                    _ctx_trainer_mult = max(0.6, 1.0 - (_t_conf - 0.5) * 0.4)

            _size_mult = _ctx_vol_mult * _ctx_trainer_mult
            _size_mult = max(0.5, min(_size_mult, 2.0))
            target_total_hedge_pct = min(float(self.max_size_pct), target_total_hedge_pct * _size_mult)
            factors["ctx_size_mult"] = round(_size_mult, 3)
        except Exception:
            pass

        factors["target_total_hedge_pct"] = float(target_total_hedge_pct)

        hedge_size_pct = max(0.0, float(target_total_hedge_pct) - float(hedge_coverage_pct))
        factors["hedge_delta_pct"] = float(hedge_size_pct)

        # Noise tolerance: do not hedge tiny deltas (precision drift / dust).
        delta_eps = max(0.0, float(getattr(self, "safety_hedge_min_delta_pct", 0.0) or 0.0))
        if hedge_size_pct > 0.0 and hedge_size_pct < delta_eps:
            hedge_size_pct = 0.0
            factors["hedge_delta_suppressed_eps_pct"] = float(delta_eps)

        should_hedge = hedge_size_pct > 0.0
        # Emergency-only enforcement: never open hedges solely for underwater ROE loss.
        if self.emergency_only and should_hedge:
            try:
                pr = reasons[0] if reasons else HedgeReason.NONE
            except Exception:
                pr = HedgeReason.NONE
            if pr == HedgeReason.ROE_LOSS:
                should_hedge = False
                factors["suppressed_by_emergency_only"] = 1.0

        # ====================================================================
        # CONTEXT-DRIVEN CONFIRMATION GATE (market-data validated hedging)
        # Uses: trainer signals, coinank funding/OI, peer awareness, TA
        # Purpose: suppress hedges when market data DISAGREES, boost when it AGREES
        # ====================================================================
        if should_hedge:
            try:
                ctx_dir = factors.get("ctx_direction_score", 0.0)
                ctx_funding = factors.get("ctx_funding_rate", 0.0)
                ctx_oi_chg = factors.get("ctx_oi_change_1h", 0.0)
                ctx_peer_adds = factors.get("ctx_peer_adds_5m", 0)
                ctx_rsi = factors.get("ctx_rsi_15m", 50.0)
                ctx_trainer_dir = factors.get("ctx_trainer_direction", "NEUTRAL")
                ctx_trainer_conf = factors.get("ctx_trainer_confidence", 0.0)
                ctx_trainer_age = factors.get("ctx_trainer_age_sec", 9999)

                # hedge_side is opposite of position_side
                # direction_score > 0 = bullish, < 0 = bearish
                # If position is LONG, hedge_side=SHORT → market going DOWN supports the hedge
                hedge_favored_dir = -1.0 if hedge_side == "SHORT" else 1.0

                # --- Trainer signal gate ---
                # If trainer STRONGLY agrees with the POSITION (not the hedge),
                # suppress non-critical hedges (trainer says position direction is correct)
                trainer_agrees_position = False
                if ctx_trainer_age < 300 and ctx_trainer_conf >= 0.65:
                    if position_side == "LONG" and ctx_trainer_dir in ("LONG", "BULLISH"):
                        trainer_agrees_position = True
                    elif position_side == "SHORT" and ctx_trainer_dir in ("SHORT", "BEARISH"):
                        trainer_agrees_position = True

                if trainer_agrees_position and urgency not in (HedgeUrgency.CRITICAL, HedgeUrgency.HIGH):
                    should_hedge = False
                    factors["ctx_suppressed_trainer_agrees_position"] = 1.0
                    logger.info(
                        "🧠 CTX_GATE_SUPPRESS | %s | trainer=%s conf=%.2f AGREES with %s position → skip %s hedge",
                        symbol, ctx_trainer_dir, ctx_trainer_conf, position_side, urgency.name if urgency else "NONE",
                    )

                # --- Coinank funding rate confirmation ---
                # Extreme funding AGAINST position supports the hedge (crowd is overleveraged our way)
                if should_hedge and abs(ctx_funding) > 0.0005:
                    funding_supports_hedge = (
                        (position_side == "LONG" and ctx_funding > 0.0005) or  # longs pay shorts, crowded long
                        (position_side == "SHORT" and ctx_funding < -0.0005)
                    )
                    if funding_supports_hedge:
                        risk_score = min(1.0, risk_score * 1.15)
                        factors["ctx_funding_boost"] = 1.15
                    # Don't suppress based on funding alone — it's just one signal

                # --- OI surge confirmation ---
                # Big OI increase + adverse direction = confirmation for hedge
                if should_hedge and abs(ctx_oi_chg) > 3.0:
                    oi_adverse = (
                        (position_side == "LONG" and ctx_dir < -0.2 and ctx_oi_chg > 3.0) or
                        (position_side == "SHORT" and ctx_dir > 0.2 and ctx_oi_chg > 3.0)
                    )
                    if oi_adverse:
                        risk_score = min(1.0, risk_score * 1.10)
                        factors["ctx_oi_surge_adverse_boost"] = 1.10

                # --- Peer pile-on prevention ---
                # If peers already added 3+ hedges in last 5 min, slow down (not CRITICAL)
                if should_hedge and ctx_peer_adds >= 3 and urgency != HedgeUrgency.CRITICAL:
                    should_hedge = False
                    factors["ctx_suppressed_peer_pile_on"] = int(ctx_peer_adds)
                    logger.info(
                        "🧠 CTX_GATE_SUPPRESS | %s | %d peer hedge adds in 5m → skip pile-on",
                        symbol, ctx_peer_adds,
                    )

                # --- RSI extreme confirmation ---
                # If RSI is extreme AGAINST position, boost confidence
                if should_hedge:
                    rsi_extreme_against = (
                        (position_side == "LONG" and ctx_rsi > 75) or  # overbought → reversal risk
                        (position_side == "SHORT" and ctx_rsi < 25)   # oversold → reversal risk
                    )
                    if rsi_extreme_against:
                        risk_score = min(1.0, risk_score * 1.10)
                        factors["ctx_rsi_extreme_boost"] = ctx_rsi

            except Exception as _ctx_gate_err:
                logger.debug("CTX_GATE_ERR | %s | %s", symbol, _ctx_gate_err)

        # Don't hedge if on cooldown (unless CRITICAL)
        urgency = HedgeUrgency.NONE
        if should_hedge:
            # Dynamic urgency: whichever risk component dominates.
            if dom == "liq":
                urgency = HedgeUrgency.CRITICAL
            elif dom == "micro":
                urgency = HedgeUrgency.HIGH
            elif dom == "trend":
                urgency = HedgeUrgency.MEDIUM
            else:
                urgency = HedgeUrgency.LOW
        if cooldown_remaining > 0 and urgency != HedgeUrgency.CRITICAL:
            should_hedge = False
        
        # Determine hedge side (opposite of position)
        hedge_side = 'SHORT' if position_side == 'LONG' else 'LONG'
        
        # Primary reason is the highest risk contributor
        primary_reason = HedgeReason.NONE
        if reasons:
            primary_reason = reasons[0]
            secondary_reasons = reasons[1:3] if len(reasons) > 1 else []
        else:
            secondary_reasons = []
        
        # Calculate confidence
        confidence = max(0.0, min(1.0, float(risk_score)))
        
        recommendation = HedgeRecommendation(
            symbol=symbol,
            position_side=position_side,
            should_hedge=should_hedge,
            hedge_side=hedge_side,
            hedge_size_pct=hedge_size_pct,
            urgency=urgency,
            primary_reason=primary_reason,
            secondary_reasons=secondary_reasons,
            current_roe_pct=roe_pct,
            risk_score=risk_score,
            confidence=confidence,
            cooldown_remaining_sec=cooldown_remaining,
            recommended_ttl_sec=int(60 + (540 * float(risk_score))),
            factors=factors
        )
        
        # ========================================================================
        # INTELLIGENCE ENGINE ENHANCEMENT (Dec 30, 2025)
        # Consult HedgeIntelligenceEngine for multi-source validation
        # Considers: CoinAPI data, anti-MM patterns, fast moves, counter-algo signals
        # ========================================================================
        if should_hedge and self._use_intelligence_engine:
            try:
                intel_should_hedge, intel_reason, intel_details = self._consult_intelligence_engine(
                    symbol=symbol,
                    position_side=position_side,
                    roe_pct=roe_pct,
                    entry_price=entry_price,
                    current_price=current_price,
                    leverage=leverage,
                    base_should_hedge=should_hedge
                )
                
                # Enhance recommendation with intelligence
                if intel_should_hedge:
                    # Add intelligence factors to recommendation
                    factors['intelligence_reason'] = intel_reason
                    factors['intelligence_factors'] = intel_details.get('decision_factors', [])
                    
                    # Boost urgency if multiple intelligence factors agree
                    if intel_details.get('factor_count', 0) >= 3:
                        if urgency == HedgeUrgency.LOW:
                            urgency = HedgeUrgency.MEDIUM
                        elif urgency == HedgeUrgency.MEDIUM:
                            urgency = HedgeUrgency.HIGH
                    
                    # Add urgency boost from intelligence
                    urgency_boost = intel_details.get('urgency_boost', 0)
                    if urgency_boost > 0.2 and urgency == HedgeUrgency.LOW:
                        urgency = HedgeUrgency.MEDIUM
                elif not intel_should_hedge and intel_details.get('factor_count', 0) == 0:
                    # Intelligence says don't hedge (insufficient factors)
                    # But still hedge if liquidation buffer is tight (liq-risk dominates)
                    if dom != "liq":
                        should_hedge = False
                        factors['intelligence_override'] = intel_reason
                        
            except ImportError:
                # Intelligence engine not available - use base recommendation
                pass
            except Exception as intel_err:
                logger.debug(f"[ADAPTIVE-HEDGE] Intelligence engine error: {intel_err}")
        
        # Rebuild recommendation with updated values
        recommendation = HedgeRecommendation(
            symbol=symbol,
            position_side=position_side,
            should_hedge=should_hedge,
            hedge_side=hedge_side,
            hedge_size_pct=hedge_size_pct,
            urgency=urgency,
            primary_reason=primary_reason,
            secondary_reasons=secondary_reasons,
            current_roe_pct=roe_pct,
            risk_score=risk_score,
            confidence=confidence,
            cooldown_remaining_sec=cooldown_remaining,
            recommended_ttl_sec=300 if urgency == HedgeUrgency.CRITICAL else 600,
            factors=factors
        )
        
        if should_hedge:
            logger.info(recommendation.to_log_line())
        
        return recommendation
    
    def _consult_intelligence_engine(
        self,
        symbol: str,
        position_side: str,
        roe_pct: float,
        entry_price: float,
        current_price: float,
        leverage: int,
        base_should_hedge: bool
    ) -> Tuple[bool, str, Dict]:
        """Consult HedgeIntelligenceEngine for enhanced decision making."""
        from trading.hedge_intelligence_engine import get_hedge_intelligence_engine
        
        if self._intelligence_engine is None:
            self._intelligence_engine = get_hedge_intelligence_engine(self.redis)
        
        return self._intelligence_engine.should_open_hedge(
            symbol=symbol,
            position_side=position_side,
            roe_pct=roe_pct,
            entry_price=entry_price,
            current_price=current_price,
            leverage=leverage,
            base_recommendation_should_hedge=base_should_hedge
        )
    
    def _analyze_roe_risk(self, roe_pct: float, position_side: str) -> Tuple[float, Optional[HedgeReason]]:
        """Analyze ROE-based risk."""
        abs_roe = abs(roe_pct)
        
        if roe_pct < -30:  # Heavy loss
            return 1.0, HedgeReason.ROE_LOSS
        elif roe_pct < -20:
            return 0.8, HedgeReason.ROE_LOSS
        elif roe_pct < -10:
            return 0.5, HedgeReason.ROE_LOSS
        elif roe_pct > 40:  # Large profit - lock it in
            return 0.6, HedgeReason.ROE_PROFIT_LOCK
        elif roe_pct > 25:
            return 0.4, HedgeReason.ROE_PROFIT_LOCK
        else:
            return 0.0, None
    
    def _analyze_volatility_risk(self, symbol: str, features: Dict) -> Tuple[float, Optional[HedgeReason]]:
        """Analyze volatility-based risk."""
        atr_pct = float(features.get('atr_pct', features.get('atr_14', 0)) or 0)
        volatility_5m = float(features.get('volatility_5m', 0) or 0)
        volatility_1h = float(features.get('volatility_1h', 0) or 0)
        
        vol_score = 0.0
        
        # High ATR indicates potential for large moves
        if atr_pct > 4:
            vol_score = 0.9
        elif atr_pct > 3:
            vol_score = 0.6
        elif atr_pct > 2:
            vol_score = 0.3
        
        # Sudden volatility spike (5m much higher than 1h)
        if volatility_1h > 0 and volatility_5m > volatility_1h * 2:
            vol_score = max(vol_score, 0.7)
        
        if vol_score >= 0.6:
            return vol_score, HedgeReason.VOLATILITY_SPIKE
        return vol_score, None
    
    def _analyze_liquidation_risk(
        self, symbol: str, position_side: str, current_price: float,
        liquidation_data: Dict, features: Dict
    ) -> Tuple[float, Optional[HedgeReason]]:
        """Analyze liquidation-based risk."""
        liq_imbalance = float(features.get('liquidation_imbalance', 0) or 0)
        liq_squeeze = float(features.get('liq_squeeze_score', 0) or 0)
        
        risk_score = 0.0
        reason = None
        
        # Squeeze potential
        if liq_squeeze > 0.7:
            risk_score = 0.9
            reason = HedgeReason.SQUEEZE_POTENTIAL
        elif liq_squeeze > 0.5:
            risk_score = 0.5
            reason = HedgeReason.SQUEEZE_POTENTIAL
        
        # Liquidation imbalance against our position
        if position_side == 'LONG' and liq_imbalance < -0.5:
            risk_score = max(risk_score, 0.7)
            reason = reason or HedgeReason.LIQUIDATION_RISK
        elif position_side == 'SHORT' and liq_imbalance > 0.5:
            risk_score = max(risk_score, 0.7)
            reason = reason or HedgeReason.LIQUIDATION_RISK
        
        return risk_score, reason
    
    def _analyze_microstructure_risk(
        self, symbol: str, position_side: str,
        microstructure: Dict, features: Dict, websocket_data: Dict
    ) -> Tuple[float, Optional[HedgeReason]]:
        """Analyze microstructure-based risk."""
        spoof_score = float(microstructure.get('spoof_score', features.get('spoof_score', 0)) or 0)
        fast_move = float(microstructure.get('fast_move_score', features.get('fast_move_score', 0)) or 0)
        order_imbalance = float(features.get('order_imbalance', features.get('bid_ask_imbalance', 0)) or 0)
        trade_intensity = float(features.get('trade_intensity', 0) or 0)
        
        # Recent price returns from websocket
        ret_15s = float(websocket_data.get('ret_15s', features.get('ret_15s', 0)) or 0)
        ret_60s = float(websocket_data.get('ret_60s', features.get('ret_60s', 0)) or 0)
        
        risk_score = 0.0
        reason = None
        
        # Fast move against position
        move_against = (
            (position_side == 'LONG' and ret_15s < -0.3) or
            (position_side == 'SHORT' and ret_15s > 0.3)
        )
        
        if move_against and fast_move > 0.6:
            risk_score = 0.9
            reason = HedgeReason.FAST_MOVE_AGAINST
        elif move_against:
            risk_score = 0.5
            reason = HedgeReason.FAST_MOVE_AGAINST
        
        # Spoofing detected
        if spoof_score > 0.7:
            risk_score = max(risk_score, 0.7)
            reason = reason or HedgeReason.MICROSTRUCTURE_ADVERSE
        
        # Order imbalance against us
        if position_side == 'LONG' and order_imbalance < -0.5:
            risk_score = max(risk_score, 0.5)
            reason = reason or HedgeReason.MICROSTRUCTURE_ADVERSE
        elif position_side == 'SHORT' and order_imbalance > 0.5:
            risk_score = max(risk_score, 0.5)
            reason = reason or HedgeReason.MICROSTRUCTURE_ADVERSE
        
        return risk_score, reason
    
    def _analyze_technical_risk(
        self, symbol: str, position_side: str, features: Dict
    ) -> Tuple[float, Optional[HedgeReason]]:
        """Analyze technical indicator risk."""
        rsi = float(features.get('rsi_14', features.get('rsi', 50)) or 50)
        macd_hist = float(features.get('macd_histogram', features.get('macd_hist', 0)) or 0)
        adx = float(features.get('adx_14', features.get('adx', 20)) or 20)
        plus_di = float(features.get('plus_di', 0) or 0)
        minus_di = float(features.get('minus_di', 0) or 0)
        
        risk_score = 0.0
        reason = None
        
        # RSI extremes suggesting reversal
        if position_side == 'LONG' and rsi > 80:
            risk_score = 0.6
            reason = HedgeReason.TECHNICAL_REVERSAL
        elif position_side == 'SHORT' and rsi < 20:
            risk_score = 0.6
            reason = HedgeReason.TECHNICAL_REVERSAL
        
        # Strong trend against position (ADX + DI)
        if adx > 30:  # Strong trend
            if position_side == 'LONG' and minus_di > plus_di:
                risk_score = max(risk_score, 0.7)
                reason = reason or HedgeReason.TECHNICAL_REVERSAL
            elif position_side == 'SHORT' and plus_di > minus_di:
                risk_score = max(risk_score, 0.7)
                reason = reason or HedgeReason.TECHNICAL_REVERSAL
        
        # MACD divergence
        if position_side == 'LONG' and macd_hist < -0.5:
            risk_score = max(risk_score, 0.4)
        elif position_side == 'SHORT' and macd_hist > 0.5:
            risk_score = max(risk_score, 0.4)
        
        return risk_score, reason
    
    def _analyze_oi_funding_risk(
        self, symbol: str, position_side: str, features: Dict
    ) -> Tuple[float, Optional[HedgeReason]]:
        """Analyze open interest and funding rate risk."""
        oi_change = float(features.get('open_interest_change', features.get('oi_change', 0)) or 0)
        funding_rate = float(features.get('funding_rate', 0) or 0)
        
        risk_score = 0.0
        reason = None
        
        # Extreme funding (crowded trade)
        if abs(funding_rate) > 0.002:  # >0.2% funding
            if (position_side == 'LONG' and funding_rate > 0) or \
               (position_side == 'SHORT' and funding_rate < 0):
                risk_score = 0.7
                reason = HedgeReason.FUNDING_EXTREME
        elif abs(funding_rate) > 0.001:  # >0.1%
            if (position_side == 'LONG' and funding_rate > 0) or \
               (position_side == 'SHORT' and funding_rate < 0):
                risk_score = 0.4
                reason = HedgeReason.FUNDING_EXTREME
        
        # Large OI change (potential for squeeze)
        if abs(oi_change) > 10:  # >10% OI change
            risk_score = max(risk_score, 0.6)
            reason = reason or HedgeReason.OI_SURGE
        elif abs(oi_change) > 5:
            risk_score = max(risk_score, 0.3)
        
        return risk_score, reason
    
    def _get_features_from_redis(self, symbol: str) -> Dict:
        """Fetch unified features from Redis."""
        if not self.redis:
            return {}
        
        cache_key = f"hedge_features:{symbol}"
        now = time.time()
        
        if cache_key in self._cache:
            cached, cached_time = self._cache[cache_key]
            if now - cached_time < self._cache_ttl:
                return cached
        
        try:
            features = {}
            
            # --------------------------------------------------------------------
            # Unified features (LEGACY JSON keys) - keep for backwards compatibility
            # --------------------------------------------------------------------
            for key_pattern in [f"features:unified:{symbol}", f"unified_features:{symbol}"]:
                try:
                    data = self.redis.get(key_pattern)
                except Exception:
                    data = None
                if data:
                    try:
                        features.update(json.loads(data))
                    except Exception:
                        pass

            # --------------------------------------------------------------------
            # Unified features (CURRENT) - Redis HASH: unified_features:{symbol}:1m
            # We intentionally fetch only a small whitelist of fields needed for
            # dynamic hedging to avoid pulling multi-thousand-field hashes per tick.
            # --------------------------------------------------------------------
            hkey = f"unified_features:{symbol}:1m"
            try:
                if self.redis.exists(hkey):
                    ts_key = f"ind_ind_{symbol}_timestamp"
                    wanted = [
                        # Volatility (NATR in %)
                        "ind_ta_NATR_14_1m",
                        "ind_ta_NATR_14_5m",
                        "ind_ta_NATR_14_15m",
                        "ind_ta_NATR_14_1h",
                        # Realized vol fallbacks (fractions)
                        "ccxt_volatility_1m",
                        "ccxt_volatility_5m",
                        "ccxt_volatility_1h",
                        "ind_ta_volatility_5m",
                        "ind_ta_volatility_1h",
                        "ind_ta_volatility_4h",
                        # Trend pressure ([-1,1])
                        "ind_ta_pressure",
                        "ind_ind_1m_pressure",
                        "ind_ind_5m_pressure",
                        "ind_ind_15m_pressure",
                        "ind_ind_1h_pressure",
                        # Orderbook imbalance ([-1,1])
                        "ob_ob_imbalance",
                        # Freshness / provenance
                        ts_key,
                        "liquidation_updated_ts",
                        "ohlcv_source",
                    ]
                    vals = self.redis.hmget(hkey, wanted)
                    for k, v in zip(wanted, vals):
                        if v is None:
                            continue
                        try:
                            features[k] = float(v)
                        except Exception:
                            features[k] = v
            except Exception:
                pass
            
            # TA indicators
            for tf in ['5m', '15m', '1h']:
                ta_key = f"ta:{symbol}:{tf}"
                ta_data = None
                # Some deployments store TA as JSON string; others as a Redis hash. Support both.
                try:
                    data = self.redis.get(ta_key)
                    if data:
                        ta_data = json.loads(data)
                except Exception:
                    ta_data = None
                if not ta_data:
                    try:
                        h = self.redis.hgetall(ta_key)
                        if h:
                            ta_data = h
                    except Exception:
                        ta_data = None
                if ta_data:
                    # Prefix with timeframe to avoid collisions
                    for k, v in (ta_data or {}).items():
                        try:
                            kk = f"{tf}_{k}" if k not in features else k
                            if kk in features:
                                continue
                            try:
                                features[kk] = float(v)
                            except Exception:
                                features[kk] = v
                        except Exception:
                            continue
            
            # Microstructure snapshot
            msnap_key = f"msnap:coinapi_wsds:{symbol}"
            msnap = self.redis.hgetall(msnap_key)
            if msnap:
                for k, v in msnap.items():
                    k = k.decode() if isinstance(k, bytes) else k
                    v = v.decode() if isinstance(v, bytes) else v
                    try:
                        features[k] = float(v)
                    except:
                        features[k] = v
            
            self._cache[cache_key] = (features, now)
            return features
            
        except Exception as e:
            logger.debug(f"Failed to fetch features for {symbol}: {e}")
            return {}
    
    def _no_hedge_recommendation(self, symbol: str, position_side: str, factors: Optional[Dict] = None) -> HedgeRecommendation:
        """Return a no-hedge recommendation."""
        return HedgeRecommendation(
            symbol=symbol,
            position_side=position_side,
            should_hedge=False,
            hedge_side='SHORT' if position_side == 'LONG' else 'LONG',
            hedge_size_pct=0.0,
            urgency=HedgeUrgency.NONE,
            primary_reason=HedgeReason.NONE,
            current_roe_pct=0.0,
            risk_score=0.0,
            confidence=0.0,
            factors=factors or {}
        )
    
    def record_hedge_action(self, symbol: str, side: str = "", margin_usd: float = 0.0) -> None:
        """Record that a hedge action was taken (for cooldown tracking)."""
        self._last_hedge_action[symbol] = time.time()
        # Notify peer awareness layer
        try:
            from trading.hedge_context import get_hedge_context
            _hctx = get_hedge_context(self.redis)
            if _hctx:
                _hctx.record_peer_action(symbol, "adaptive_hedge", "ADD", side, margin_usd)
        except Exception:
            pass
    
    def should_unwind_hedge(
        self, symbol: str, position_side: str, current_roe_pct: float,
        features: Optional[Dict] = None
    ) -> Tuple[bool, str]:
        """
        Check if an existing hedge should be unwound.
        
        Returns:
            (should_unwind, reason)
        """
        # Intentionally conservative: we avoid static thresholds for hedge unwinds.
        #
        # Unwinding is handled by the trader's dynamic unwind loop (which can
        # incorporate hedge locks, profit-first logic, and account/margin context).
        #
        # Returning False here prevents the hedge engine from making unilateral
        # unwind decisions based on brittle static cutoffs.
        _ = features or self._get_features_from_redis(symbol)
        return False, ""


# Global instance
_adaptive_hedge_instance = None


def get_adaptive_hedge(redis_client=None) -> DynamicAdaptiveHedge:
    """Get or create the global adaptive hedge instance."""
    global _adaptive_hedge_instance
    if _adaptive_hedge_instance is None:
        _adaptive_hedge_instance = DynamicAdaptiveHedge(redis_client=redis_client)
    return _adaptive_hedge_instance

