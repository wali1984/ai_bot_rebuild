"""
Target Exposure Controller
==========================
Replaces simple "duplicate suppression" with intelligent exposure management.

Instead of blocking signals when position already exists, this controller:
1. Computes a target exposure (side + size) from multi-TF votes and confidence
2. Compares to current exposure
3. Emits at most ONE action per symbol: OPEN, INCREASE, DECREASE, CLOSE, FLIP, or HOLD

Key Features:
- Anti-churn: Min interval between INCREASE/DECREASE, min delta threshold
- TF-weighted voting: Higher TFs stabilize, lower TFs for quick protection
- Single action per symbol per cycle (no signal spam)
- Full telemetry and reason codes
- Integration with risk gates (SAFE_MODE, feature health, portfolio policy, caution mode)
- 1m protection-only: 1m signals can only manage/protect, not open new risk

Author: WMA AI Trading System
Date: December 24, 2025
"""

import os
import time
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from collections import defaultdict

logger = logging.getLogger(__name__)


class TargetSide(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"
    NEUTRAL = "NEUTRAL"  # HOLD with position = don't vote for any direction change


class ExposureAction(Enum):
    """Possible actions from target exposure comparison."""
    HOLD = "HOLD"
    OPEN_LONG = "OPEN_LONG"
    OPEN_SHORT = "OPEN_SHORT"
    # Hedge entries for balanced hedge positions (adds to specific leg)
    OPEN_HEDGE_LONG = "OPEN_HEDGE_LONG"
    OPEN_HEDGE_SHORT = "OPEN_HEDGE_SHORT"
    INCREASE_LONG = "INCREASE_LONG"
    INCREASE_SHORT = "INCREASE_SHORT"
    DECREASE_LONG = "DECREASE_LONG"
    DECREASE_SHORT = "DECREASE_SHORT"
    PARTIAL_CLOSE_LONG = "PARTIAL_CLOSE_LONG"
    PARTIAL_CLOSE_SHORT = "PARTIAL_CLOSE_SHORT"
    CLOSE_LONG = "CLOSE_LONG"
    CLOSE_SHORT = "CLOSE_SHORT"
    FLIP_TO_LONG = "FLIP_TO_LONG"
    FLIP_TO_SHORT = "FLIP_TO_SHORT"
    # Hedge suggestions when DECREASE blocked due to insufficient profit
    BUILD_HEDGE_SHORT = "BUILD_HEDGE_SHORT"  # Build hedge instead of decreasing LONG
    BUILD_HEDGE_LONG = "BUILD_HEDGE_LONG"    # Build hedge instead of decreasing SHORT


class SkipReason(Enum):
    """Skip reason codes for telemetry."""
    TARGET_DELTA_TOO_SMALL = "TARGET_DELTA_TOO_SMALL"
    TARGET_COOLDOWN = "TARGET_COOLDOWN"
    FLIP_PREFLIGHT_FAILED = "FLIP_PREFLIGHT_FAILED"
    NO_ACTION_NEEDED = "NO_ACTION_NEEDED"
    SAFE_MODE_NO_CHECKPOINT = "SAFE_MODE_NO_CHECKPOINT"
    FEATURE_HEALTH_BLOCK = "FEATURE_HEALTH_BLOCK"
    PORTFOLIO_SLOT_BLOCK = "PORTFOLIO_SLOT_BLOCK"
    PORTFOLIO_BUDGET_BLOCK = "PORTFOLIO_BUDGET_BLOCK"
    PORTFOLIO_RESERVE_BLOCK = "PORTFOLIO_RESERVE_BLOCK"  # Reserve requires high conf
    CAUTION_MODE = "CAUTION_MODE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    LEARNING_TF_FLAT = "LEARNING_TF_FLAT"  # 1m trying to open when flat (legacy)
    ONE_MIN_FLAT_ENTRY_BLOCK = "ONE_MIN_FLAT_ENTRY_BLOCK"  # CRITICAL: 1m cannot open new risk when flat
    DECREASE_PROFIT_CHECK_FAILED = "DECREASE_PROFIT_CHECK_FAILED"  # Position not profitable enough to decrease
    CLOSE_PROFIT_CHECK_FAILED = "CLOSE_PROFIT_CHECK_FAILED"  # No-loss gating: close blocked because position not profitable
    CLOSE_QUORUM_NOT_MET = "CLOSE_QUORUM_NOT_MET"  # Not enough TFs voted FLAT to justify closing


@dataclass
class ExposureVote:
    """A single timeframe's vote on target exposure."""
    timeframe: str
    side: TargetSide
    confidence: float
    weight: float = 1.0
    timestamp_ms: int = 0
    action_raw: str = ""  # Original action string


@dataclass
class TargetExposureResult:
    """Result of target exposure computation."""
    symbol: str
    target_side: TargetSide
    target_exposure_pct: float = 0.0
    current_side: Optional[str] = None
    current_exposure_pct: float = 0.0
    current_pnl_pct: float = 0.0  # Current position PnL percentage
    delta_pct: float = 0.0
    action: ExposureAction = ExposureAction.HOLD
    skip_reason: Optional[SkipReason] = None
    skip_detail: str = ""
    votes: List[ExposureVote] = field(default_factory=list)
    weighted_confidence: float = 0.0
    is_blocked: bool = False
    size_multiplier: float = 1.0  # Applied by overlay if present
    hedge_suggestion: bool = False  # True if DECREASE blocked and hedge recommended
    
    def to_log_line(self) -> str:
        tf_votes_str = ",".join(f"{v.timeframe}:{v.side.value}:{v.confidence:.2f}" for v in self.votes)
        skip_str = f" | blocked={self.skip_reason.value}" if self.skip_reason else ""
        pnl_str = f" | pnl={self.current_pnl_pct:.1f}%" if self.current_pnl_pct != 0 else ""
        hedge_str = " | HEDGE_SUGGESTED" if self.hedge_suggestion else ""
        return (
            f"TARGET_EXPOSURE | {self.symbol} | tf_votes=[{tf_votes_str}] | "
            f"conf={self.weighted_confidence:.3f} | "
            f"current={self.current_exposure_pct:.1f}% | target={self.target_exposure_pct:.1f}% | "
            f"delta={self.delta_pct:.1f}% | action={self.action.value}{pnl_str}{skip_str}{hedge_str}"
        )
    
    def to_skip_event(self) -> Dict[str, Any]:
        """Generate skip event for Redis."""
        return {
            "symbol": self.symbol,
            "action": self.action.value,
            "reason_code": self.skip_reason.value if self.skip_reason else "NONE",
            "reason_detail": self.skip_detail,
            "target_exposure_pct": round(self.target_exposure_pct, 2),
            "delta_pct": round(self.delta_pct, 2),
            "ts_ms": int(time.time() * 1000),
        }


class TargetExposureController:
    """
    Computes target exposure and action for each symbol based on multi-TF signals.
    
    Flow:
    1. Collect TF votes for each symbol
    2. Compute weighted target direction and exposure
    3. Compare to current position
    4. Consult risk gates (safe mode, feature health, portfolio, caution)
    5. Emit single action with anti-churn controls
    """
    
    # Timeframe weights (higher = more stabilizing influence)
    TF_WEIGHTS = {
        '1m': 0.1,   # Protective only, low weight for direction
        '5m': 0.5,   # Short-term signals
        '15m': 1.0,  # Primary trading TF
        '1h': 1.5,   # Strong stabilizer
        '4h': 2.0,   # Major trend
    }
    
    # Learning-only timeframes: Can manage, cannot open new risk when flat
    LEARNING_TIMEFRAMES = frozenset(['1m'])
    
    def __init__(
        self,
        redis_client: Any = None,
        min_delta_pct: float = 2.0,
        min_interval_sec: int = 120,
        min_conf_entry: float = 0.70,
        max_exposure_pct: float = 10.0,
        min_exposure_pct: float = 2.0,
        min_profit_for_decrease: float = 15.0,  # Min profit % required for DECREASE actions
        min_profit_for_close: float = 0.0,      # Min profit % required for CLOSE actions (no-loss gating)
    ):
        self.redis = redis_client
        self.min_delta_pct = min_delta_pct
        self.min_interval_sec = min_interval_sec
        self.min_conf_entry = min_conf_entry
        self.max_exposure_pct = max_exposure_pct
        self.min_exposure_pct = min_exposure_pct
        self.min_profit_for_decrease = min_profit_for_decrease
        self.min_profit_for_close = min_profit_for_close
        
        # Load from env if available
        self.min_delta_pct = float(os.getenv("TARGET_MIN_DELTA_PCT", str(min_delta_pct)))
        self.min_interval_sec = int(os.getenv("TARGET_MIN_INTERVAL_SEC", str(min_interval_sec)))
        self.max_exposure_pct = float(os.getenv("TARGET_MAX_EXPOSURE_PCT", str(max_exposure_pct)))
        self.min_exposure_pct = float(os.getenv("TARGET_MIN_EXPOSURE_PCT", str(min_exposure_pct)))
        # Fix S: Allow env override of min_conf_entry (default 0.70 → align with MIN_CONF_EXIT for position mgmt)
        self.min_conf_entry = float(os.getenv("TARGET_MIN_CONF_ENTRY", str(min_conf_entry)))
        # CRITICAL: Min profit required to allow DECREASE/partial close
        # If position is not this profitable, suggest hedge building instead
        self.min_profit_for_decrease = float(os.getenv("TARGET_MIN_PROFIT_FOR_DECREASE", str(min_profit_for_decrease)))

        # Optional "no-loss" system gate:
        # - Block CLOSE_* when PnL < min_profit_for_close
        # - Convert into BUILD_HEDGE_* (which emits OPEN_HEDGE_* downstream)
        try:
            import config as _cfg
        except Exception:
            _cfg = None
        if _cfg is not None:
            self.enable_no_loss_gating = bool(getattr(_cfg, "ENABLE_NO_LOSS_GATING", False))
            try:
                self.min_profit_for_close = float(getattr(_cfg, "TARGET_MIN_PROFIT_FOR_CLOSE", self.min_profit_for_close))
            except Exception:
                self.min_profit_for_close = self.min_profit_for_close
        else:
            self.enable_no_loss_gating = os.getenv("ENABLE_NO_LOSS_GATING", "true").lower() in ("1", "true", "yes")
            self.min_profit_for_close = float(os.getenv("TARGET_MIN_PROFIT_FOR_CLOSE", str(min_profit_for_close)))
        
        # Per-symbol last action tracking for cooldown
        self._last_action_ts: Dict[str, int] = {}

        # Per-symbol last state (for adaptive, event-driven anti-churn)
        # symbol -> dict(last_ts_ms, last_action, last_conf, last_target_side, last_target_pct, last_headroom)
        self._last_state: Dict[str, Dict[str, Any]] = {}
        
        # Dedupe tracking (symbol -> (action, ts))
        self._last_intent: Dict[str, Tuple[str, int]] = {}
        self._dedupe_window_ms = 60000  # 60s dedupe
        
        logger.info(
            f"TargetExposureController initialized | "
            f"min_delta={self.min_delta_pct}% | min_interval={self.min_interval_sec}s | "
            f"max_exposure={self.max_exposure_pct}% | min_exposure={self.min_exposure_pct}% | "
            f"min_profit_for_decrease={self.min_profit_for_decrease}% | "
            f"no_loss={'on' if self.enable_no_loss_gating else 'off'} | "
            f"min_profit_for_close={self.min_profit_for_close}%"
        )
    
    def _get_tf_weight(self, tf: str) -> float:
        """Get weight for timeframe."""
        return self.TF_WEIGHTS.get(tf, 0.5)
    
    def _classify_side(self, action, has_position: bool = False) -> TargetSide:
        """Classify action into target side.
        
        This classifies the MODEL'S intended direction, not the resulting action.
        - "LONG" or "OPEN_LONG" -> LONG (model wants long exposure)
        - "SHORT" or "OPEN_SHORT" -> SHORT (model wants short exposure)  
        - "HOLD" with NO position -> FLAT (stay flat)
        - "HOLD" WITH position -> NEUTRAL (keep current position, don't vote)
        - "FLAT" -> FLAT (model wants no exposure)
        
        Note: CLOSE_LONG still contains LONG, so for close actions use FLAT explicitly.
        
        Args:
            action: The action from the model
            has_position: Whether there's an existing position (CRITICAL for HOLD interpretation)
        """
        # Handle integer actions from MultiDiscrete: 0=SHORT, 1=HOLD, 2=LONG
        if isinstance(action, (int, float)):
            action_idx = int(action)
            if action_idx == 0 or action_idx == -1:
                return TargetSide.SHORT
            elif action_idx == 2 or action_idx == 1:  # 1=HOLD -> context-dependent, 2=LONG
                if action_idx == 2:
                    return TargetSide.LONG
                # action_idx == 1 is HOLD - depends on position state
                return TargetSide.NEUTRAL if has_position else TargetSide.FLAT
            return TargetSide.FLAT
        
        action_upper = str(action).upper()
        # Explicit FLAT first (always means want no exposure)
        if action_upper == 'FLAT':
            return TargetSide.FLAT
        # HOLD/NONE/WAIT - context-dependent
        # CRITICAL FIX (2025-12-29): HOLD with position = NEUTRAL (keep position)
        # HOLD without position = FLAT (stay flat)
        if action_upper in {'HOLD', 'NONE', 'WAIT'}:
            if has_position:
                return TargetSide.NEUTRAL  # Don't vote for direction change
            return TargetSide.FLAT
        # Fix S (2026-02-21): FLIP actions must be classified by their TARGET direction
        # CLOSE_SHORT_OPEN_LONG → target is LONG (close short, open long)
        # CLOSE_LONG_OPEN_SHORT → target is SHORT (close long, open short)
        # Must check BEFORE reduce tokens, since flips contain "CLOSE" keyword
        if ('CLOSE' in action_upper and 'OPEN' in action_upper) or 'FLIP' in action_upper:
            if 'LONG' in action_upper.split('OPEN')[-1] if 'OPEN' in action_upper else 'LONG' in action_upper:
                return TargetSide.LONG
            elif 'SHORT' in action_upper.split('OPEN')[-1] if 'OPEN' in action_upper else 'SHORT' in action_upper:
                return TargetSide.SHORT
            # Explicit flip naming: FLIP_TO_LONG, FLIP_LONG, etc.
            if 'LONG' in action_upper:
                return TargetSide.LONG
            if 'SHORT' in action_upper:
                return TargetSide.SHORT
        # Close/reduce/protective actions want FLAT (reduced or no exposure)
        # CRITICAL FIX (2026-02-21): PARTIAL_CLOSE_SHORT was falling through to
        # 'SHORT' in action_upper → classified as SHORT → caused INCREASE_SHORT
        # instead of DECREASE. Must check ALL close/reduce/protective patterns
        # BEFORE the directional 'LONG'/'SHORT' keyword check.
        _REDUCE_TOKENS = ('CLOSE', 'PARTIAL', 'DECREASE', 'REDUCE',
                          'TAKE_PROFIT', 'STOP_LOSS', 'TP_', 'SL_', 'EXIT')
        if any(action_upper.startswith(tok) or tok in action_upper for tok in _REDUCE_TOKENS):
            return TargetSide.FLAT
        # Direction-carrying actions (entries, increases, hedges)
        if 'LONG' in action_upper or action_upper == 'BUY':
            return TargetSide.LONG
        elif 'SHORT' in action_upper or action_upper == 'SELL':
            return TargetSide.SHORT
        return TargetSide.FLAT
    
    def _is_learning_tf(self, tf: str) -> bool:
        """Check if timeframe is learning-only."""
        return tf in self.LEARNING_TIMEFRAMES
    
    def compute_target_exposure(
        self,
        symbol: str,
        tf_signals: List[Dict[str, Any]],
        current_position: Optional[Dict[str, Any]] = None,
        now_ms: Optional[int] = None,
        # Risk gate flags
        safe_mode: bool = False,
        feature_health_ok: bool = True,
        portfolio_policy_ok: bool = True,
        caution_mode: bool = False,
        portfolio_block_reason: str = "",
    ) -> TargetExposureResult:
        """
        Compute target exposure from multi-TF signals.
        
        Args:
            symbol: Trading symbol
            tf_signals: List of signal dicts with 'timeframe', 'action', 'confidence'
            current_position: Current position dict with 'side', 'exposure_pct', 'margin_pct', 'pnl_pct'
            now_ms: Current timestamp (for cooldown checks)
            safe_mode: If True, block entry/increase/flip actions
            feature_health_ok: If False, block entry/increase/flip actions
            portfolio_policy_ok: If False, block entry/increase/flip actions
            caution_mode: If True, block exposure-increasing actions
            portfolio_block_reason: Specific portfolio block reason
            
        Returns:
            TargetExposureResult with computed action
        """
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        
        result = TargetExposureResult(symbol=symbol, target_side=TargetSide.FLAT)
        
        # Extract PnL from current position for DECREASE profit check
        if current_position:
            result.current_pnl_pct = float(current_position.get('pnl_pct', 0) or 
                                          current_position.get('unrealizedProfit', 0) or 
                                          current_position.get('roe', 0) or 0)
        
        if not tf_signals:
            result.action = ExposureAction.HOLD
            result.skip_reason = SkipReason.NO_ACTION_NEEDED
            return result
        
        # Convert signals to votes
        votes = []
        has_position = current_position and float(current_position.get('exposure_pct', 0) or current_position.get('margin_pct', 0) or 0) > 0
        
        for sig in tf_signals:
            tf = sig.get('timeframe', '5m')
            # DEBUG: Log raw action values before normalization
            raw_action = sig.get('action')
            raw_action_name = sig.get('action_name')
            raw_predicted = sig.get('predicted_action')
            
            # Prefer action_name over action (action may be int)
            action = sig.get('action_name') or sig.get('predicted_action') or sig.get('action') or 'HOLD'
            
            conf = float(sig.get('confidence', sig.get('model_confidence', 0)) or 0)
            weight = self._get_tf_weight(tf)
            # CRITICAL: Pass has_position so HOLD is interpreted correctly
            side = self._classify_side(action, has_position=has_position)
            
            # Log for debugging (after side is computed)
            logger.info(f"[TARGET_EXPOSURE_DEBUG] {symbol}:{tf} action_raw={raw_action}, action_name={raw_action_name}, predicted={raw_predicted}, using={action}, side={side.value}")
            
            # 1m rule: If flat and 1m wants to open, treat as FLAT vote
            # CRITICAL: ONE_MIN_FLAT_ENTRY_BLOCK - 1m can NEVER open new risk when flat
            if self._is_learning_tf(tf) and not has_position and side != TargetSide.FLAT:
                logger.info(f"ONE_MIN_FLAT_ENTRY_BLOCK | {symbol} | 1m entry suppressed (position flat) -> FLAT vote | action_raw={action}")
                side = TargetSide.FLAT
            
            votes.append(ExposureVote(
                timeframe=tf,
                side=side,
                confidence=conf,
                weight=weight,
                timestamp_ms=int(sig.get('ts_ms', now_ms) or now_ms),
                action_raw=str(action),
            ))
        
        result.votes = votes
        
        # Check if 1m is the ONLY TF voting and position is flat
        # In that case, force HOLD - 1m cannot open new risk
        non_learning_votes = [v for v in votes if not self._is_learning_tf(v.timeframe)]
        if not non_learning_votes and not has_position:
            # Only 1m votes when flat = force HOLD
            result.action = ExposureAction.HOLD
            result.skip_reason = SkipReason.ONE_MIN_FLAT_ENTRY_BLOCK
            result.skip_detail = "1m is only TF voting and position is flat - cannot open new risk"
            logger.info(f"ONE_MIN_FLAT_ENTRY_BLOCK | {symbol} | 1m-only vote blocked (flat)")
            return result
        
        # Weighted vote aggregation
        # CRITICAL: NEUTRAL votes (HOLD with position) do NOT participate in direction voting
        long_score = sum(v.confidence * v.weight for v in votes if v.side == TargetSide.LONG)
        short_score = sum(v.confidence * v.weight for v in votes if v.side == TargetSide.SHORT)
        flat_score = sum(v.confidence * v.weight for v in votes if v.side == TargetSide.FLAT)
        neutral_count = sum(1 for v in votes if v.side == TargetSide.NEUTRAL)
        
        # Only count non-NEUTRAL votes in total weight for direction decision
        directional_votes = [v for v in votes if v.side != TargetSide.NEUTRAL]
        total_weight = sum(v.weight for v in directional_votes) or 1.0
        
        # If ALL votes are NEUTRAL (all TFs say HOLD with existing position), keep position
        # CRITICAL FIX (2025-12-29): When ALL votes are NEUTRAL, maintain current exposure exactly
        # Do NOT compute new target_pct from confidence - that causes spurious DECREASE signals
        if neutral_count == len(votes) and has_position:
            # All TFs agree to HOLD - maintain current exposure EXACTLY
            if current_position:
                current_side = current_position.get('side', '').upper()
                current_pct = float(current_position.get('exposure_pct', 0) or 
                                   current_position.get('margin_pct', 0) or 0)
                if current_side == 'LONG':
                    result.target_side = TargetSide.LONG
                    result.target_exposure_pct = current_pct  # KEEP CURRENT EXPOSURE
                elif current_side == 'SHORT':
                    result.target_side = TargetSide.SHORT
                    result.target_exposure_pct = current_pct  # KEEP CURRENT EXPOSURE
                else:
                    result.target_side = TargetSide.FLAT
                    result.target_exposure_pct = 0.0
                # Use max confidence from NEUTRAL votes
                result.weighted_confidence = max((v.confidence for v in votes), default=0.0)
                result.current_side = current_side
                result.current_exposure_pct = current_pct
                result.delta_pct = 0.0  # NO CHANGE
                result.action = ExposureAction.HOLD
                result.skip_reason = SkipReason.NO_ACTION_NEEDED
                result.skip_detail = "ALL_NEUTRAL: all TFs voted HOLD - maintaining current position"
                logger.info(f"[TARGET_EXPOSURE] {symbol} ALL_NEUTRAL: keeping {result.target_side.value} position at {current_pct:.1f}% (all TFs voted HOLD)")
                return result  # EARLY RETURN - skip all further processing
            else:
                result.target_side = TargetSide.FLAT
                result.weighted_confidence = 0.0
        # If no directional votes, default based on current position
        # CRITICAL: Also maintain current exposure exactly - don't trigger DECREASE
        elif not directional_votes:
            if has_position and current_position:
                current_side = current_position.get('side', '').upper()
                current_pct = float(current_position.get('exposure_pct', 0) or 
                                   current_position.get('margin_pct', 0) or 0)
                if current_side == 'LONG':
                    result.target_side = TargetSide.LONG
                    result.target_exposure_pct = current_pct  # KEEP CURRENT
                elif current_side == 'SHORT':
                    result.target_side = TargetSide.SHORT
                    result.target_exposure_pct = current_pct  # KEEP CURRENT
                else:
                    result.target_side = TargetSide.FLAT
                    result.target_exposure_pct = 0.0
                result.weighted_confidence = max((v.confidence for v in votes), default=0.0)
                result.current_side = current_side
                result.current_exposure_pct = current_pct
                result.delta_pct = 0.0  # NO CHANGE
                result.action = ExposureAction.HOLD
                result.skip_reason = SkipReason.NO_ACTION_NEEDED
                result.skip_detail = "NO_DIRECTIONAL_VOTES: maintaining current position"
                logger.info(f"[TARGET_EXPOSURE] {symbol} NO_DIRECTIONAL_VOTES: keeping {result.target_side.value} position at {current_pct:.1f}%")
                return result  # EARLY RETURN
            else:
                result.target_side = TargetSide.FLAT
                result.weighted_confidence = 0.0
        # Determine target side from scores
        elif long_score > short_score and long_score > flat_score:
            result.target_side = TargetSide.LONG
            result.weighted_confidence = long_score / total_weight
        elif short_score > long_score and short_score > flat_score:
            result.target_side = TargetSide.SHORT
            result.weighted_confidence = short_score / total_weight
        else:
            result.target_side = TargetSide.FLAT
            result.weighted_confidence = flat_score / total_weight if flat_score else 0.0
        
        # Compute target exposure percentage from confidence
        # target_pct = clip(MIN_PCT + (conf - MIN_CONF) * SCALE, 0, MAX_PCT)
        if result.target_side != TargetSide.FLAT and result.weighted_confidence >= self.min_conf_entry:
            conf_excess = result.weighted_confidence - self.min_conf_entry
            scale = (self.max_exposure_pct - self.min_exposure_pct) / (1.0 - self.min_conf_entry)
            result.target_exposure_pct = self.min_exposure_pct + conf_excess * scale
            result.target_exposure_pct = min(self.max_exposure_pct, max(0.0, result.target_exposure_pct))
        else:
            result.target_exposure_pct = 0.0
        
        # Get current position state
        if current_position:
            result.current_side = current_position.get('side', '').upper() or None
            result.current_exposure_pct = float(current_position.get('exposure_pct', 0) or 
                                                 current_position.get('margin_pct', 0) or 0)
        
        # Compute delta and action
        result = self._compute_action(result, now_ms)
        
        # Apply risk gate checks
        result = self._apply_risk_gates(
            result, 
            safe_mode=safe_mode,
            feature_health_ok=feature_health_ok,
            portfolio_policy_ok=portfolio_policy_ok,
            caution_mode=caution_mode,
            portfolio_block_reason=portfolio_block_reason,
        )
        
        # Check dedupe
        result = self._check_dedupe(result, now_ms)
        
        return result
    
    def _compute_action(self, result: TargetExposureResult, now_ms: int) -> TargetExposureResult:
        """Compute the action based on target vs current exposure."""
        target_side = result.target_side
        target_pct = result.target_exposure_pct
        current_side = result.current_side
        current_pct = result.current_exposure_pct

        # ------------------------------------------------------------------
        # Compute _no_loss_override ONCE at function top so both DECREASE
        # and CLOSE branches can reference it.  Sources that represent risk
        # management (deleverage, health_monitor, governor, proactive) are
        # allowed to realise losses; normal trainer signals are not.
        # ------------------------------------------------------------------
        _no_loss_override = False
        _override_source = ""
        if hasattr(result, '_signal_meta') and isinstance(getattr(result, '_signal_meta', None), dict):
            _src = str(result._signal_meta.get("source", "")).lower()
            if any(tok in _src for tok in ("deleverage", "health_monitor", "governor", "proactive")):
                _no_loss_override = True
                _override_source = _src
            if result._signal_meta.get("override_profit_guard"):
                _no_loss_override = True
                _override_source = _src or "override_profit_guard"
        if _no_loss_override:
            logger.info(
                f"[TARGET_EXPOSURE][NO_LOSS_OVERRIDE] {result.symbol} "
                f"source={_override_source} → loss realisation allowed"
            )

        # ========================================================================
        # HEDGE MODE FIX (Jan 2026): Handle NEUTRAL side (balanced hedge)
        # When _get_current_position returns side="NEUTRAL", it means the symbol
        # has BOTH LONG and SHORT legs with similar size (hedged/balanced).
        # In this case, allow new OPEN signals to add to the dominant direction
        # (which the model is predicting) instead of blocking with NO_ACTION_NEEDED.
        # ========================================================================
        is_balanced_hedge = (current_side == "NEUTRAL")
        
        # No position case - use 0.01% threshold to handle floating point issues
        # CRITICAL: Must check BOTH current_side being empty AND current_pct being ~0
        # Otherwise stale current_side values can cause spurious CLOSE actions
        # HEDGE FIX: Treat NEUTRAL (balanced hedge) as effectively flat for new entries
        effectively_flat = (not current_side) or (current_pct <= 0.01) or is_balanced_hedge
        
        if effectively_flat:
            if is_balanced_hedge:
                logger.info(f"[TARGET_EXPOSURE][HEDGE_FLAT] {result.symbol} treating balanced hedge (NEUTRAL) as flat for new {target_side.value} entry")
            
            if target_side == TargetSide.LONG and target_pct >= self.min_exposure_pct:
                # For balanced hedge: OPEN_HEDGE_LONG adds to the LONG leg
                if is_balanced_hedge:
                    result.action = ExposureAction.OPEN_HEDGE_LONG
                    logger.info(f"[TARGET_EXPOSURE][HEDGE_ADD] {result.symbol} balanced hedge → OPEN_HEDGE_LONG (adding to LONG leg)")
                else:
                    result.action = ExposureAction.OPEN_LONG
                result.delta_pct = target_pct
                self._record_action(result.symbol, now_ms)
            elif target_side == TargetSide.SHORT and target_pct >= self.min_exposure_pct:
                # For balanced hedge: OPEN_HEDGE_SHORT adds to the SHORT leg
                if is_balanced_hedge:
                    result.action = ExposureAction.OPEN_HEDGE_SHORT
                    logger.info(f"[TARGET_EXPOSURE][HEDGE_ADD] {result.symbol} balanced hedge → OPEN_HEDGE_SHORT (adding to SHORT leg)")
                else:
                    result.action = ExposureAction.OPEN_SHORT
                result.delta_pct = target_pct
                self._record_action(result.symbol, now_ms)
            else:
                result.action = ExposureAction.HOLD
                result.skip_reason = SkipReason.NO_ACTION_NEEDED
                result.skip_detail = f"No position and target is FLAT or below min exposure"
            return result
        
        # Same side case - check for INCREASE/DECREASE
        if current_side == target_side.value:
            result.delta_pct = target_pct - current_pct
            
            # Adaptive, event-driven anti-churn (CRITICAL):
            # The old static min_interval_sec created "stuck" behavior where OPEN_RISK never resumes even under high headroom.
            # We still prevent spam, but we make the cooldown depend on *state changes*:
            # - headroom (more headroom => allow faster adjustments)
            # - confidence change (bigger change => allow now)
            # - delta magnitude (bigger delta => allow now)
            # - action change (different action => allow now)
            _pnl = result.current_pnl_pct or 0.0
            _will_become_hedge = self.enable_no_loss_gating and _pnl < -1.0 and result.delta_pct < -self.min_delta_pct
            if not _will_become_hedge and not self._adaptive_cooldown_allows(result, now_ms):
                result.action = ExposureAction.HOLD
                result.skip_reason = SkipReason.TARGET_COOLDOWN
                result.skip_detail = "Adaptive cooldown active (no material change)"
                return result
            
            if result.delta_pct > self.min_delta_pct:
                # INCREASE
                if target_side == TargetSide.LONG:
                    result.action = ExposureAction.INCREASE_LONG
                else:
                    result.action = ExposureAction.INCREASE_SHORT
                self._record_action(result.symbol, now_ms)
            elif result.delta_pct < -self.min_delta_pct:
                # DECREASE (partial close) - HARD NO-LOSS RULE
                # Only block DECREASE when the position is in loss (pnl < 0).
                # EXCEPTION: deleverage/health_monitor/governor sources bypass no-loss.
                pnl_pct = result.current_pnl_pct or 0.0

                if self.enable_no_loss_gating and pnl_pct < 0.0 and not _no_loss_override:
                    # Position is losing - suggest hedge instead
                    if target_side == TargetSide.LONG:
                        result.action = ExposureAction.BUILD_HEDGE_SHORT
                    else:
                        result.action = ExposureAction.BUILD_HEDGE_LONG
                    result.hedge_suggestion = True
                    result.skip_reason = SkipReason.DECREASE_PROFIT_CHECK_FAILED
                    result.skip_detail = (
                        f"DECREASE blocked (no-loss): PnL {pnl_pct:.1f}% < 0.0%. Suggesting hedge instead."
                    )
                    logger.info(
                        f"[TARGET_EXPOSURE][HEDGE_SUGGEST] {result.symbol} {current_side} position "
                        f"PnL={pnl_pct:.1f}% < 0.0% → BUILD_HEDGE instead of DECREASE"
                    )
                else:
                    # Position is profitable enough - allow DECREASE (partial take profit)
                    if target_side == TargetSide.LONG:
                        result.action = ExposureAction.DECREASE_LONG
                    else:
                        result.action = ExposureAction.DECREASE_SHORT
                    logger.info(
                        f"[TARGET_EXPOSURE][PARTIAL_TP] {result.symbol} {current_side} position "
                        f"PnL={pnl_pct:.1f}% >= 0.0% → DECREASE allowed"
                    )
                self._record_action(result.symbol, now_ms)
            else:
                # Delta too small
                result.action = ExposureAction.HOLD
                result.skip_reason = SkipReason.TARGET_DELTA_TOO_SMALL
                result.skip_detail = f"Delta {result.delta_pct:.1f}% < min {self.min_delta_pct}%"
            return result
        
        # Target is FLAT and we have position - CLOSE
        # CRITICAL FIX (2025-12-29): Verify current_pct > 0 before generating CLOSE
        # Without this, we'd generate CLOSE_LONG/SHORT for positions that don't exist,
        # bleeding fees/commissions for no-op trades
        if target_side == TargetSide.FLAT:
            # Safety check: if current_pct is effectively 0, there's nothing to close
            if current_pct <= 0.01:  # 0.01% threshold to handle floating point
                result.action = ExposureAction.HOLD
                result.skip_reason = SkipReason.NO_ACTION_NEEDED
                result.skip_detail = f"No position to close (current_pct={current_pct:.2f}%)"
                logger.debug(f"[TARGET_EXPOSURE] {result.symbol} FLAT target but no position to close (current_pct={current_pct:.2f}%)")
                return result
            
            # Multi-TF quorum for CLOSE: require multiple TFs to vote FLAT
            try:
                from config import TARGET_CLOSE_QUORUM_TFS
            except Exception:
                TARGET_CLOSE_QUORUM_TFS = 2
            _flat_tfs = set()
            for _v in (result.votes or []):
                if _v.side == TargetSide.FLAT and not self._is_learning_tf(_v.timeframe):
                    _flat_tfs.add(_v.timeframe)
            if len(_flat_tfs) < TARGET_CLOSE_QUORUM_TFS:
                result.action = ExposureAction.HOLD
                result.skip_reason = SkipReason.CLOSE_QUORUM_NOT_MET if hasattr(SkipReason, 'CLOSE_QUORUM_NOT_MET') else SkipReason.NO_ACTION_NEEDED
                result.skip_detail = (
                    f"CLOSE quorum not met: {len(_flat_tfs)} TFs voted FLAT "
                    f"(need {TARGET_CLOSE_QUORUM_TFS}). TFs: {sorted(_flat_tfs)}"
                )
                logger.info(
                    f"[TARGET_EXPOSURE][CLOSE_QUORUM] {result.symbol} CLOSE blocked: "
                    f"{len(_flat_tfs)}/{TARGET_CLOSE_QUORUM_TFS} TFs voted FLAT ({sorted(_flat_tfs)})"
                )
                return result
            
            result.delta_pct = -current_pct
            # Optional no-loss gating: do not close losing positions; build a hedge instead.
            # _no_loss_override is computed at the top of _compute_action().

            if self.enable_no_loss_gating and not _no_loss_override:
                pnl_pct = result.current_pnl_pct or 0.0
                # HARD RULE: only block CLOSE when pnl < 0
                if pnl_pct < 0.0:
                    if current_side == 'LONG':
                        result.action = ExposureAction.BUILD_HEDGE_SHORT
                    else:
                        result.action = ExposureAction.BUILD_HEDGE_LONG
                    result.hedge_suggestion = True
                    result.skip_reason = SkipReason.CLOSE_PROFIT_CHECK_FAILED
                    result.skip_detail = (
                        f"CLOSE blocked (no-loss): PnL {pnl_pct:.1f}% < 0.0%. Suggesting hedge instead."
                    )
                    logger.info(
                        f"[TARGET_EXPOSURE][NO_LOSS] {result.symbol} CLOSE blocked at PnL={pnl_pct:.1f}% "
                        f"(<0.0%) → BUILD_HEDGE"
                    )
                    return result

            if current_side == 'LONG':
                result.action = ExposureAction.CLOSE_LONG
            else:
                result.action = ExposureAction.CLOSE_SHORT
            return result
        
        # Opposite side - FLIP (requires preflight check downstream)
        if current_side == 'LONG' and target_side == TargetSide.SHORT:
            result.action = ExposureAction.FLIP_TO_SHORT
            result.delta_pct = -(current_pct + target_pct)  # Close + open
        elif current_side == 'SHORT' and target_side == TargetSide.LONG:
            result.action = ExposureAction.FLIP_TO_LONG
            result.delta_pct = -(current_pct + target_pct)
        else:
            result.action = ExposureAction.HOLD
            result.skip_reason = SkipReason.NO_ACTION_NEEDED
        
        return result
    
    def _apply_risk_gates(
        self,
        result: TargetExposureResult,
        safe_mode: bool,
        feature_health_ok: bool,
        portfolio_policy_ok: bool,
        caution_mode: bool,
        portfolio_block_reason: str,
    ) -> TargetExposureResult:
        """Apply risk gate checks and block if necessary."""
        
        # Classify action type
        action = result.action
        is_entry = action in {
            ExposureAction.OPEN_LONG, ExposureAction.OPEN_SHORT,
            ExposureAction.OPEN_HEDGE_LONG, ExposureAction.OPEN_HEDGE_SHORT,  # Hedge entries for balanced positions
            ExposureAction.INCREASE_LONG, ExposureAction.INCREASE_SHORT,
            ExposureAction.FLIP_TO_LONG, ExposureAction.FLIP_TO_SHORT,
        }
        is_protective = action in {
            ExposureAction.CLOSE_LONG, ExposureAction.CLOSE_SHORT,
            ExposureAction.DECREASE_LONG, ExposureAction.DECREASE_SHORT,
            ExposureAction.PARTIAL_CLOSE_LONG, ExposureAction.PARTIAL_CLOSE_SHORT,
        }
        
        # Protective actions always pass
        if is_protective or action == ExposureAction.HOLD:
            return result
        
        # Check safe mode
        if safe_mode and is_entry:
            result.action = ExposureAction.HOLD
            result.skip_reason = SkipReason.SAFE_MODE_NO_CHECKPOINT
            result.skip_detail = "SAFE_MODE active: blocking exposure-increasing action"
            result.is_blocked = True
            return result
        
        # Check feature health
        if not feature_health_ok and is_entry:
            result.action = ExposureAction.HOLD
            result.skip_reason = SkipReason.FEATURE_HEALTH_BLOCK
            result.skip_detail = "Feature health check failed"
            result.is_blocked = True
            return result
        
        # Check portfolio policy
        if not portfolio_policy_ok and is_entry:
            result.action = ExposureAction.HOLD
            if 'slot' in portfolio_block_reason.lower():
                result.skip_reason = SkipReason.PORTFOLIO_SLOT_BLOCK
            elif 'budget' in portfolio_block_reason.lower():
                result.skip_reason = SkipReason.PORTFOLIO_BUDGET_BLOCK
            else:
                result.skip_reason = SkipReason.PORTFOLIO_SLOT_BLOCK
            result.skip_detail = portfolio_block_reason or "Portfolio policy check failed"
            result.is_blocked = True
            return result
        
        # Check caution mode
        if caution_mode and is_entry:
            result.action = ExposureAction.HOLD
            result.skip_reason = SkipReason.CAUTION_MODE
            result.skip_detail = "Caution mode active: blocking exposure-increasing action"
            result.is_blocked = True
            return result
        
        return result
    
    def _check_cooldown(self, symbol: str, now_ms: int) -> bool:
        """Check if cooldown has elapsed for INCREASE/DECREASE."""
        last_ts = self._last_action_ts.get(symbol, 0)
        elapsed_ms = now_ms - last_ts
        return elapsed_ms >= self.min_interval_sec * 1000

    def _adaptive_cooldown_allows(self, result: TargetExposureResult, now_ms: int) -> bool:
        """
        Event-driven cooldown:
        - If action/target materially changes, allow immediately.
        - Otherwise apply an effective interval that shrinks with headroom and grows when confidence is low.

        This avoids the "always blocked by TARGET_COOLDOWN" deadlock in high-headroom, no-loss systems.
        """
        sym = result.symbol
        last = self._last_state.get(sym) or {}

        # Extract dynamic context (provided by caller when available)
        # headroom_pct: 0..1 (available_margin / equity)
        headroom = 0.0
        try:
            headroom = float(last.get("last_headroom", 0.0) or 0.0)
        except Exception:
            headroom = 0.0
        headroom = max(0.0, min(1.0, headroom))

        try:
            cur_conf = float(result.weighted_confidence or 0.0)
        except Exception:
            cur_conf = 0.0
        cur_conf = max(0.0, min(1.0, cur_conf))

        try:
            last_conf = float(last.get("last_conf", 0.0) or 0.0)
        except Exception:
            last_conf = 0.0
        last_conf = max(0.0, min(1.0, last_conf))

        last_ts = int(last.get("last_ts_ms", 0) or 0)
        elapsed_ms = max(0, int(now_ms) - int(last_ts))

        # Material change checks (no static thresholds; relative to last state)
        # 1) Target side changed -> allow immediately
        if str(last.get("last_target_side") or "") and str(last.get("last_target_side")) != str(result.target_side.value):
            return True

        # 2) Confidence improved significantly relative to remaining range -> allow immediately
        # (e.g., if last_conf was 0.60, remaining is 0.40; require a meaningful fraction of that)
        remaining = max(1e-9, 1.0 - last_conf)
        if (cur_conf - last_conf) > 0.25 * remaining:
            return True

        # 3) Delta magnitude increased relative to last delta -> allow immediately
        try:
            last_delta = float(last.get("last_delta_pct", 0.0) or 0.0)
        except Exception:
            last_delta = 0.0
        if abs(float(result.delta_pct or 0.0)) > max(abs(last_delta), 0.0) * 1.5 and abs(float(result.delta_pct or 0.0)) > 0.0:
            return True

        # Otherwise apply effective interval:
        # - base interval = min_interval_sec
        # - shrink with headroom (more room => quicker)
        # - grow as confidence decreases (low confidence => slower)
        base_ms = max(0.0, float(self.min_interval_sec) * 1000.0)
        # If base is 0, always allow.
        if base_ms <= 0:
            return True
        # headroom factor: 1.0 at 0 headroom, down to 0.2 at high headroom
        headroom_factor = 1.0 - 0.8 * headroom
        # confidence factor: 1.0 at high conf, up to 2.0 at very low conf
        conf_factor = 1.0 + (1.0 - cur_conf)
        eff_ms = base_ms * headroom_factor * conf_factor
        return elapsed_ms >= eff_ms
    
    def _record_action(self, symbol: str, now_ms: int):
        """Record action timestamp for cooldown tracking."""
        self._last_action_ts[symbol] = now_ms

        # Best-effort: keep last_state timestamp too (other fields updated in _check_dedupe)
        try:
            st = self._last_state.get(symbol) or {}
            st["last_ts_ms"] = int(now_ms)
            self._last_state[symbol] = st
        except Exception:
            pass
    
    def _check_dedupe(self, result: TargetExposureResult, now_ms: int) -> TargetExposureResult:
        """Check for duplicate intent within dedupe window."""
        if result.action == ExposureAction.HOLD or result.is_blocked:
            return result
        
        symbol = result.symbol
        action_str = result.action.value
        
        last_intent = self._last_intent.get(symbol)
        if last_intent:
            last_action, last_ts = last_intent
            _is_hedge_build = action_str.startswith("BUILD_HEDGE")
            _hedge_losing = _is_hedge_build and result.hedge_suggestion and (result.current_pnl_pct or 0.0) < -1.0
            if last_action == action_str and (now_ms - last_ts) < self._dedupe_window_ms and not _hedge_losing:
                result.action = ExposureAction.HOLD
                result.skip_reason = SkipReason.TARGET_COOLDOWN
                result.skip_detail = f"Dedupe: same intent {action_str} within {self._dedupe_window_ms}ms"
                result.is_blocked = True
                return result
        
        # Record this intent + state snapshot for adaptive cooldown decisions
        self._last_intent[symbol] = (action_str, now_ms)
        try:
            st = self._last_state.get(symbol) or {}
            st["last_ts_ms"] = int(now_ms)
            st["last_action"] = str(action_str)
            st["last_conf"] = float(result.weighted_confidence or 0.0)
            st["last_target_side"] = str(result.target_side.value)
            st["last_target_pct"] = float(result.target_exposure_pct or 0.0)
            st["last_delta_pct"] = float(result.delta_pct or 0.0)
            # Caller may optionally populate current_position.headroom_pct; carry it forward if present.
            try:
                # (This is set by the trainer in current_position; we store best-effort.)
                st["last_headroom"] = float(getattr(result, "headroom_pct", st.get("last_headroom", 0.0)) or st.get("last_headroom", 0.0) or 0.0)
            except Exception:
                pass
            self._last_state[symbol] = st
        except Exception:
            pass
        return result
    
    def action_to_signal_action_name(
        self, 
        action: ExposureAction, 
        target_pct: float,
        current_pct: float,
    ) -> Tuple[str, float]:
        """
        Convert ExposureAction to signal action_name and position_size_pct.
        
        Returns:
            (action_name, position_size_pct)
        """
        action_map = {
            ExposureAction.HOLD: ("HOLD", 0),
            ExposureAction.OPEN_LONG: ("OPEN_LONG", target_pct),
            ExposureAction.OPEN_SHORT: ("OPEN_SHORT", target_pct),
            # Direct hedge entries for balanced hedge positions (adds to specific leg)
            ExposureAction.OPEN_HEDGE_LONG: ("OPEN_HEDGE_LONG", target_pct),
            ExposureAction.OPEN_HEDGE_SHORT: ("OPEN_HEDGE_SHORT", target_pct),
            ExposureAction.INCREASE_LONG: ("INCREASE_LONG", target_pct - current_pct),
            ExposureAction.INCREASE_SHORT: ("INCREASE_SHORT", target_pct - current_pct),
            ExposureAction.DECREASE_LONG: ("DECREASE_LONG", abs(target_pct - current_pct)),
            ExposureAction.DECREASE_SHORT: ("DECREASE_SHORT", abs(target_pct - current_pct)),
            ExposureAction.PARTIAL_CLOSE_LONG: ("PARTIAL_CLOSE", abs(target_pct - current_pct)),
            ExposureAction.PARTIAL_CLOSE_SHORT: ("PARTIAL_CLOSE", abs(target_pct - current_pct)),
            ExposureAction.CLOSE_LONG: ("CLOSE_LONG", current_pct),
            ExposureAction.CLOSE_SHORT: ("CLOSE_SHORT", current_pct),
            ExposureAction.FLIP_TO_LONG: ("CLOSE_SHORT_AND_OPEN_LONG", target_pct),
            ExposureAction.FLIP_TO_SHORT: ("CLOSE_LONG_AND_OPEN_SHORT", target_pct),
            # Hedge suggestions - emit explicit hedge opens sized to the *would-be reduction*.
            # This supports the "no-loss" system: when closing/reducing is blocked, hedge instead.
            ExposureAction.BUILD_HEDGE_SHORT: ("OPEN_HEDGE_SHORT", abs(target_pct - current_pct)),
            ExposureAction.BUILD_HEDGE_LONG: ("OPEN_HEDGE_LONG", abs(target_pct - current_pct)),
        }
        
        return action_map.get(action, ("HOLD", 0))
    
    def process_symbol_signals(
        self,
        symbol: str,
        tf_signals: List[Dict[str, Any]],
        current_position: Optional[Dict[str, Any]] = None,
        # Risk gate flags
        safe_mode: bool = False,
        feature_health_ok: bool = True,
        portfolio_policy_ok: bool = True,
        caution_mode: bool = False,
        portfolio_block_reason: str = "",
    ) -> Tuple[Optional[Dict[str, Any]], TargetExposureResult]:
        """
        Process signals for a symbol and return a single modified signal payload.
        
        Returns:
            (payload_or_none, result) - payload is None if action is HOLD or blocked
        """
        result = self.compute_target_exposure(
            symbol, 
            tf_signals, 
            current_position,
            safe_mode=safe_mode,
            feature_health_ok=feature_health_ok,
            portfolio_policy_ok=portfolio_policy_ok,
            caution_mode=caution_mode,
            portfolio_block_reason=portfolio_block_reason,
        )
        
        # Log result
        logger.info(result.to_log_line())
        
        if result.action == ExposureAction.HOLD or result.is_blocked:
            if result.skip_reason:
                logger.debug(f"[TARGET_EXPOSURE] {symbol} skipped: {result.skip_reason.value}")
            
            # Publish skip event if blocked
            if result.is_blocked and self.redis:
                self._publish_skip_event(result)
            
            return None, result
        
        # Build modified payload from the highest-weighted signal
        best_signal = max(tf_signals, key=lambda s: (
            self._get_tf_weight(s.get('timeframe', '5m')) * 
            float(s.get('confidence', s.get('model_confidence', 0)) or 0)
        ))
        
        payload = dict(best_signal)
        action_name, delta_pct = self.action_to_signal_action_name(
            result.action, result.target_exposure_pct, result.current_exposure_pct
        )
        
        # Apply size multiplier if set (from overlay)
        effective_delta = delta_pct * result.size_multiplier
        effective_target = result.target_exposure_pct * result.size_multiplier
        
        payload['action_name'] = action_name
        payload['final_action'] = action_name
        payload['predicted_action'] = action_name.split('_')[0] if '_' in action_name else action_name
        payload['target_exposure_pct'] = effective_target
        payload['delta_exposure_pct'] = effective_delta
        payload['position_size_pct'] = effective_delta if effective_delta > 0 else effective_target
        payload['exposure_controller'] = True
        payload['weighted_confidence'] = result.weighted_confidence
        payload['tf_votes'] = len(result.votes)
        payload['timeframe'] = 'multi'  # Indicate this is deconflicted
        payload['size_multiplier'] = result.size_multiplier
        
        return payload, result
    
    def _publish_skip_event(self, result: TargetExposureResult):
        """Publish skip event to Redis."""
        if self.redis is None:
            return
        
        try:
            self.redis.xadd(
                "signals:execution:skips",
                result.to_skip_event(),
                maxlen=5000,
                approximate=True,
            )
        except Exception as e:
            logger.debug(f"[TARGET_EXPOSURE] Failed to publish skip event: {e}")


# Global instance
_target_exposure_controller: Optional[TargetExposureController] = None


def get_target_exposure_controller(
    redis_client: Any = None,
    force_new: bool = False,
) -> TargetExposureController:
    """Get global target exposure controller instance."""
    global _target_exposure_controller
    if _target_exposure_controller is None or force_new:
        _target_exposure_controller = TargetExposureController(redis_client=redis_client)
    elif redis_client is not None and _target_exposure_controller.redis is None:
        _target_exposure_controller.redis = redis_client
    return _target_exposure_controller


def is_target_exposure_enabled() -> bool:
    """Check if target exposure controller is enabled."""
    return os.getenv("ENABLE_TARGET_EXPOSURE_CONTROLLER", "true").lower() == "true"
