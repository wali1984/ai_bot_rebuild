"""
Dynamic Runner + Hedge Overlay
==============================
Implements dynamic profit-taking and hedging logic to let winners run
while protecting against reversals.

Key Features:
- 20% ROE hedge trigger (green or red)
- Adaptive trailing stops based on ATR/volatility
- MFE-anchored profit protection (don't let green turn red)
- Anti-churn controls (min intervals, state machine)
- 1m/5m hot monitor lane for active positions

This overlay is INDEPENDENT from PPO/MASA - it's an execution overlay
that manages positions after entry.

Author: WMA AI Trading System
Date: December 24, 2025
"""

import os
import time
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple, Any, Set
from enum import Enum
from collections import defaultdict
import uuid

logger = logging.getLogger(__name__)


class RunnerMode(Enum):
    """Runner state machine states."""
    NONE = "NONE"                    # Position not in runner mode
    RUNNER_ACTIVE = "RUNNER_ACTIVE"  # Tracking peak/trough, trailing
    HEDGE_ARMED = "HEDGE_ARMED"      # About to open hedge (hysteresis)
    HEDGED = "HEDGED"                # Hedge is active
    COOLING_DOWN = "COOLING_DOWN"    # Just acted, waiting


class HedgeState(Enum):
    """Hedge lifecycle states."""
    NONE = "NONE"
    HEDGE_OPEN = "HEDGE_OPEN"
    HEDGE_SCALED = "HEDGE_SCALED"
    HEDGE_UNWIND = "HEDGE_UNWIND"


class OverlayAction(Enum):
    """Overlay intent actions."""
    PARTIAL_CLOSE = "PARTIAL_CLOSE"
    DECREASE_LONG = "DECREASE_LONG"
    DECREASE_SHORT = "DECREASE_SHORT"
    CLOSE_LONG = "CLOSE_LONG"
    CLOSE_SHORT = "CLOSE_SHORT"
    CLOSE_ALL = "CLOSE_ALL"
    OPEN_HEDGE_LONG = "OPEN_HEDGE_LONG"
    OPEN_HEDGE_SHORT = "OPEN_HEDGE_SHORT"
    SCALE_HEDGE = "SCALE_HEDGE"
    UNWIND_HEDGE = "UNWIND_HEDGE"
    TIGHTEN_TRAILING = "TIGHTEN_TRAILING"
    NOOP = "NOOP"


class CloseReasonCode(Enum):
    """Close reason codes for telemetry."""
    TAKE_PROFIT_DYNAMIC = "TAKE_PROFIT_DYNAMIC"
    TRAILING_PROTECT = "TRAILING_PROTECT"
    HEDGE_TRIGGER_20PCT = "HEDGE_TRIGGER_20PCT"
    LOSS_HEDGE_20PCT = "LOSS_HEDGE_20PCT"
    PROFIT_LOCK_RETRACE = "PROFIT_LOCK_RETRACE"
    MFE_PROTECT = "MFE_PROTECT"
    REVERSAL_DETECTED = "REVERSAL_DETECTED"
    MANUAL_CLOSE = "MANUAL_CLOSE"


@dataclass
class RunnerState:
    """Per-symbol runner state tracking."""
    symbol: str
    side: str  # 'LONG' or 'SHORT'
    entry_price: float = 0.0
    entry_ts_ms: int = 0
    
    # Excursion tracking
    mfe_pct: float = 0.0  # Max favorable excursion
    mae_pct: float = 0.0  # Max adverse excursion
    current_pnl_pct: float = 0.0
    
    # Peak/trough tracking for trailing
    last_peak_price: float = 0.0
    last_trough_price: float = float('inf')
    
    # Virtual trailing stop
    trailing_stop_price: float = 0.0
    trailing_width_pct: float = 2.0  # Dynamic width
    
    # Profit lock floor
    profit_lock_floor_pct: float = 0.0
    last_profit_take_ts_ms: int = 0
    
    # State machine
    runner_mode: RunnerMode = RunnerMode.NONE
    cooldown_until_ms: int = 0
    
    # Action tracking
    actions_in_window: int = 0
    last_action_ts_ms: int = 0
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'side': self.side,
            'entry_price': self.entry_price,
            'entry_ts_ms': self.entry_ts_ms,
            'mfe_pct': round(self.mfe_pct, 4),
            'mae_pct': round(self.mae_pct, 4),
            'current_pnl_pct': round(self.current_pnl_pct, 4),
            'trailing_stop_price': round(self.trailing_stop_price, 6),
            'trailing_width_pct': round(self.trailing_width_pct, 4),
            'runner_mode': self.runner_mode.value,
            'cooldown_until_ms': self.cooldown_until_ms,
        }


@dataclass
class HedgePosition:
    """Hedge position tracking."""
    symbol: str
    hedge_side: str  # Opposite of main position
    hedge_active: bool = False
    hedge_entry_price: float = 0.0
    hedge_size_pct_equity: float = 0.0
    hedge_margin_usd: float = 0.0
    hedge_anchor_pct: float = 20.0  # Trigger at ±20%
    hedge_step: int = 0  # 0=none, 1=initial, 2=scaled
    last_hedge_adjust_ts_ms: int = 0
    hedge_cooldown_until_ms: int = 0
    state: HedgeState = HedgeState.NONE
    
    def to_dict(self) -> Dict:
        return {
            'symbol': self.symbol,
            'hedge_side': self.hedge_side,
            'hedge_active': self.hedge_active,
            'hedge_size_pct_equity': round(self.hedge_size_pct_equity, 4),
            'state': self.state.value,
        }


@dataclass
class OverlayIntent:
    """Overlay action intent."""
    signal_id: str
    symbol: str
    action: OverlayAction
    source: str = "overlay_runner_hedge"
    decision_source: str = "runner_hedge_overlay"
    
    # Sizing (for reduce/hedge open)
    close_pct: float = 0.0  # Partial close %
    hedge_size_pct: float = 0.0  # Hedge size as % of main position
    margin_usd: float = 0.0
    notional_usd: float = 0.0
    leverage: float = 1.0
    
    # Context
    pnl_pct: float = 0.0
    roe_pct: float = 0.0
    mfe_pct: float = 0.0
    mae_pct: float = 0.0
    retrace_pct: float = 0.0
    trailing_width_pct: float = 0.0
    
    # Reason
    close_reason_code: Optional[CloseReasonCode] = None
    reason_detail: str = ""
    
    # Blocking
    blocked: bool = False
    blocked_reason: str = ""
    
    timestamp_ms: int = 0
    
    def to_dict(self) -> Dict:
        return {
            'signal_id': self.signal_id,
            'symbol': self.symbol,
            'action': self.action.value,
            'source': self.source,
            'decision_source': self.decision_source,
            'close_pct': round(self.close_pct, 4),
            'hedge_size_pct': round(self.hedge_size_pct, 4),
            'margin_usd': round(self.margin_usd, 2),
            'notional_usd': round(self.notional_usd, 2),
            'leverage': self.leverage,
            'pnl_pct': round(self.pnl_pct, 4),
            'roe_pct': round(self.roe_pct, 4),
            'mfe_pct': round(self.mfe_pct, 4),
            'mae_pct': round(self.mae_pct, 4),
            'retrace_pct': round(self.retrace_pct, 4),
            'trailing_width_pct': round(self.trailing_width_pct, 4),
            'close_reason_code': self.close_reason_code.value if self.close_reason_code else None,
            'reason_detail': self.reason_detail,
            'blocked': self.blocked,
            'blocked_reason': self.blocked_reason,
            'timestamp_ms': self.timestamp_ms,
        }
    
    def to_log_line(self, pos_side: str = 'UNKNOWN', pos_qty: float = 0.0) -> str:
        """Generate structured log line with position proof (flat=false verification)."""
        is_flat = abs(pos_qty) < 1e-9
        return (
            f"OVERLAY_INTENT | {self.symbol} | {self.action.value} | "
            f"pos_side={pos_side} | pos_qty={pos_qty:.4f} | flat={is_flat} | "
            f"close_pct={self.close_pct:.1f}% | hedge_size={self.hedge_size_pct:.1f}% | "
            f"reason={self.close_reason_code.value if self.close_reason_code else 'N/A'} | "
            f"pnl%={self.pnl_pct:.2f} | retrace%={self.retrace_pct:.2f} | "
            f"trailing_width%={self.trailing_width_pct:.2f} | "
            f"blocked={self.blocked_reason if self.blocked else 'no'}"
        )


class DynamicRunnerHedgeManager:
    """
    Manages dynamic profit-taking and hedging for active positions.
    
    This is an EXECUTION OVERLAY - it monitors positions and generates
    protective intents that can be executed by the trader.
    
    Features:
    - Runner mode activation at configurable profit threshold
    - Adaptive trailing stops based on volatility
    - 20% ROE hedge triggers (profit or loss protection)
    - Anti-churn controls (rate limits, cooldowns, state machine)
    - MFE-anchored profit lock (don't let green turn red)
    - 1m/5m protection-only mode (NEVER opens new risk from flat)
    
    CRITICAL: Overlay must ONLY run for symbols with active positions.
    It can NEVER create a fresh position from flat - that's model territory.
    """
    
    def __init__(
        self,
        redis_client: Any = None,
        config: Any = None,
        enable_execute: bool = False,
        allow_hedge_open: bool = False,
    ):
        self.redis = redis_client
        
        # Feature flags
        self.enable_execute = enable_execute
        self.allow_hedge_open = allow_hedge_open
        
        # Load config
        if config is None:
            try:
                from config import get_live_config
                config = get_live_config()
            except ImportError:
                config = None
        
        # Configuration
        self.runner_activation_pct = float(os.getenv("RUNNER_ACTIVATION_PCT", "5.0"))
        self.hedge_trigger_pct = float(os.getenv("RUNNER_HEDGE_ROE_THRESHOLD_PCT", "20.0"))
        self.hysteresis_seconds = int(os.getenv("RUNNER_HEDGE_HYSTERESIS_SECONDS", "30"))
        self.hedge_unwind_roe_pct = float(os.getenv("RUNNER_HEDGE_UNWIND_ROE_PCT", "12.0"))
        
        # Hedge sizing by ROE tier
        self.hedge_size_20pct = float(os.getenv("RUNNER_HEDGE_SIZE_20PCT_ROE", "0.15"))
        self.hedge_size_40pct = float(os.getenv("RUNNER_HEDGE_SIZE_40PCT_ROE", "0.30"))
        self.hedge_size_80pct = float(os.getenv("RUNNER_HEDGE_SIZE_80PCT_ROE", "0.50"))
        
        # Anti-churn (loaded from config with defaults)
        self.min_action_interval_sec = int(os.getenv("DYNAMIC_RUNNER_HEDGE_MIN_SECONDS_BETWEEN_ACTIONS", "60"))
        self.max_actions_per_10min = int(os.getenv("DYNAMIC_RUNNER_HEDGE_MAX_ACTIONS_PER_SYMBOL_PER_10MIN", "3"))
        self.min_delta_close_pct = float(os.getenv("DYNAMIC_RUNNER_HEDGE_MIN_DELTA_CLOSE_PCT", "0.10"))
        self.hedge_state_min_interval_sec = 120
        
        # Hedge sizing limits
        self.min_hedge_notional_usd = float(os.getenv("DYNAMIC_RUNNER_HEDGE_MIN_HEDGE_NOTIONAL_USD", "10"))
        self.max_hedge_margin_pct_equity = float(os.getenv("DYNAMIC_RUNNER_HEDGE_MAX_HEDGE_MARGIN_PCT_EQUITY", "2.5"))
        self.max_hedge_gross_pct_equity = float(os.getenv("DYNAMIC_RUNNER_HEDGE_MAX_HEDGE_GROSS_PCT_EQUITY", "10.0"))
        
        # Canary mode
        self.canary_only = os.getenv("DYNAMIC_RUNNER_HEDGE_CANARY_ONLY", "false").lower() == "true"
        
        # State tracking
        self._runner_states: Dict[str, RunnerState] = {}
        self._hedge_states: Dict[str, HedgePosition] = {}
        self._action_window: Dict[str, List[int]] = defaultdict(list)  # symbol -> list of action timestamps
        
        # Logging
        self.log_interval_sec = int(os.getenv("DYNAMIC_RUNNER_HEDGE_LOG_INTERVAL_SEC", "60"))
        self._last_log_ts = 0
        
        logger.info(
            f"DynamicRunnerHedgeManager initialized | "
            f"runner_activation={self.runner_activation_pct}% | "
            f"hedge_trigger={self.hedge_trigger_pct}% | "
            f"execute={self.enable_execute} | "
            f"allow_hedge_open={self.allow_hedge_open}"
        )
    
    def _get_runner_state(self, symbol: str) -> RunnerState:
        """Get or create runner state for symbol."""
        if symbol not in self._runner_states:
            self._runner_states[symbol] = RunnerState(symbol=symbol, side='')
        return self._runner_states[symbol]
    
    def _get_hedge_state(self, symbol: str) -> HedgePosition:
        """Get or create hedge state for symbol."""
        if symbol not in self._hedge_states:
            self._hedge_states[symbol] = HedgePosition(symbol=symbol, hedge_side='')
        return self._hedge_states[symbol]
    
    def should_evaluate(self, symbol: str, position: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
        """
        Check if overlay should evaluate for this symbol.
        
        Returns (should_run, skip_reason).
        
        CRITICAL: Overlay must NEVER run when flat. It can only manage
        existing positions, never create new risk from flat.
        """
        # Must have a position
        if position is None:
            return False, "no_position_data"
        
        # Position must be non-zero
        pos_amt = float(position.get('positionAmt', 0) or position.get('size', 0) or position.get('qty', 0) or 0)
        if abs(pos_amt) < 1e-9:
            return False, "position_flat"
        
        # Must have valid side
        side = str(position.get('side', '') or position.get('positionSide', '')).upper()
        if side not in ('LONG', 'SHORT', 'BUY', 'SELL'):
            return False, "invalid_side"
        
        return True, ""
    
    def update_position_context(
        self,
        symbol: str,
        position: Dict[str, Any],
        features_1m: Optional[Dict] = None,
        features_5m: Optional[Dict] = None,
        now_ms: Optional[int] = None,
    ) -> RunnerState:
        """
        Update position context and compute runner metrics.
        
        Call this on each monitoring cycle to update MFE/MAE and trailing stops.
        """
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        
        state = self._get_runner_state(symbol)
        
        # Extract position info
        side = str(position.get('side', '') or position.get('positionSide', '')).upper()
        if side in ['LONG', 'BUY']:
            side = 'LONG'
        elif side in ['SHORT', 'SELL']:
            side = 'SHORT'
        else:
            return state  # No valid position
        
        state.side = side
        
        entry_price = float(position.get('entryPrice', 0) or position.get('entry_price', 0) or 0)
        mark_price = float(position.get('markPrice', 0) or position.get('mark_price', 0) or entry_price)
        leverage = float(position.get('leverage', 1) or 1)  # CRITICAL: Get leverage for ROE calculation
        unrealized_pnl_pct = float(position.get('unrealized_pnl_pct', 0) or position.get('unRealizedProfit', 0) / max(float(position.get('initialMargin', 1)), 1) * 100)
        
        if entry_price <= 0:
            return state
        
        state.entry_price = entry_price
        state.leverage = leverage  # Store leverage in state
        
        # Calculate ROE % (PnL % * leverage) - CRITICAL FIX: Must include leverage!
        # ROE = (mark - entry) / entry * 100 * leverage
        if side == 'LONG':
            pnl_pct = (mark_price - entry_price) / entry_price * 100 * leverage
        else:
            pnl_pct = (entry_price - mark_price) / entry_price * 100 * leverage
        
        state.current_pnl_pct = pnl_pct
        
        # Update MFE/MAE
        if pnl_pct > state.mfe_pct:
            state.mfe_pct = pnl_pct
        if pnl_pct < state.mae_pct:
            state.mae_pct = pnl_pct
        
        # Update peak/trough for trailing
        if side == 'LONG':
            if mark_price > state.last_peak_price:
                state.last_peak_price = mark_price
        else:
            if mark_price < state.last_trough_price:
                state.last_trough_price = mark_price
        
        # Extract volatility from features for dynamic trailing width
        atr_pct = 2.0  # Default 2%
        if features_5m:
            atr_pct = float(features_5m.get('atr_pct', 2.0) or 2.0)
        
        # Dynamic trailing width: clamp(a*ATR + b*vol, min, max)
        min_width = 1.0
        max_width = 5.0
        state.trailing_width_pct = max(min_width, min(max_width, atr_pct * 1.5))
        
        # Update virtual trailing stop
        if side == 'LONG' and state.last_peak_price > 0:
            state.trailing_stop_price = state.last_peak_price * (1 - state.trailing_width_pct / 100)
        elif side == 'SHORT' and state.last_trough_price < float('inf'):
            state.trailing_stop_price = state.last_trough_price * (1 + state.trailing_width_pct / 100)
        
        # Runner mode activation
        if state.runner_mode == RunnerMode.NONE and pnl_pct >= self.runner_activation_pct:
            state.runner_mode = RunnerMode.RUNNER_ACTIVE
            logger.info(f"OVERLAY_STATE | {symbol} | RUNNER_ACTIVE | pnl%={pnl_pct:.2f} | mfe%={state.mfe_pct:.2f}")
        
        return state
    
    def evaluate_actions(
        self,
        symbol: str,
        position: Dict[str, Any],
        portfolio_ctx: Optional[Dict] = None,
        risk_ctx: Optional[Dict] = None,
        now_ms: Optional[int] = None,
        promotion_controller: Optional[Any] = None,
    ) -> List[OverlayIntent]:
        """
        Evaluate and return overlay action intents for a position.
        
        This is the main decision function that generates protective intents.
        
        CRITICAL: Only runs for EXISTING positions. Never creates new risk from flat.
        """
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        
        intents = []
        
        # CRITICAL: Only evaluate if position exists (never when flat)
        should_run, skip_reason = self.should_evaluate(symbol, position)
        if not should_run:
            logger.debug(f"[OVERLAY] {symbol} skip evaluate: {skip_reason}")
            return intents
        
        # CRITICAL FIX: Must update position context BEFORE reading state!
        # This populates entry_price, pnl_pct, mfe_pct from the position data
        state = self.update_position_context(symbol, position, now_ms=now_ms)
        hedge = self._get_hedge_state(symbol)
        
        # Anti-churn: Check cooldown
        if state.cooldown_until_ms > now_ms:
            return intents
        
        # Anti-churn: Rate limit
        if not self._check_rate_limit(symbol, now_ms):
            return intents
        
        # ====================================================================
        # TRAINER SIGNAL CHECK: Read trainer's latest prediction for this symbol.
        # If trainer has high-confidence signal aligned with current position,
        # suppress partial closes that would fight the trainer's conviction.
        # Hedge opens are NOT suppressed (protective).
        # ====================================================================
        trainer_action = ""
        trainer_conf = 0.0
        try:
            if self.redis and symbol:
                _pred_raw = self.redis.hgetall(f"prediction:{symbol}")
                if _pred_raw:
                    trainer_action = str(
                        _pred_raw.get("action_name") or _pred_raw.get(b"action_name", b"")
                    ).upper().strip()
                    if isinstance(trainer_action, bytes):
                        trainer_action = trainer_action.decode()
                    try:
                        trainer_conf = float(_pred_raw.get("confidence") or _pred_raw.get(b"confidence", 0))
                    except Exception:
                        trainer_conf = 0.0
        except Exception:
            pass
        
        side = state.side
        pnl_pct = state.current_pnl_pct
        mfe_pct = state.mfe_pct
        entry_price = state.entry_price
        
        # Log ROE for observability
        if abs(pnl_pct) >= 5.0:  # Log when ROE is significant (>5%)
            logger.info(f"[OVERLAY_ROE] {symbol} | side={side} | ROE={pnl_pct:.2f}% | entry={entry_price:.4f} | leverage={state.leverage}x | hedge_active={hedge.hedge_active}")
        
        if not side or entry_price <= 0:
            logger.debug(f"[OVERLAY] {symbol} skip: invalid state side={side} entry={entry_price}")
            return intents
        
        # Calculate retracement
        retrace_pct = 0.0
        if mfe_pct > 0:
            retrace_pct = mfe_pct - pnl_pct
        
        # ========================================================================
        # A) Check 20% ROE hedge trigger (profit OR loss)
        # ========================================================================
        # IMPORTANT:
        # Overlay hedge opens are disabled by default in config (single hedge opener rule).
        # If `allow_hedge_open` is false, we skip hedge arming entirely to avoid
        # confusing state/logs and ensure hedge decisions come from the unified hedge engine.
        if self.allow_hedge_open:
            logger.debug(f"[OVERLAY_CHECK] {symbol} | pnl={pnl_pct:.2f}% | trigger={self.hedge_trigger_pct}% | mode={state.runner_mode} | hedge_active={hedge.hedge_active}")
            if abs(pnl_pct) >= self.hedge_trigger_pct:
                logger.info(f"[OVERLAY_TRIGGER] {symbol} | ROE {pnl_pct:.2f}% >= threshold {self.hedge_trigger_pct}% | mode={state.runner_mode}")
                if not hedge.hedge_active:
                    # Arm hedge (apply hysteresis)
                    if state.runner_mode != RunnerMode.HEDGE_ARMED:
                        state.runner_mode = RunnerMode.HEDGE_ARMED
                        state.last_action_ts_ms = now_ms  # CRITICAL: Set timestamp when arming
                        logger.info(f"OVERLAY_STATE | {symbol} | HEDGE_ARMED | pnl%={pnl_pct:.2f}")
                    else:
                        # Already armed, check if hysteresis passed
                        time_armed_ms = now_ms - state.last_action_ts_ms
                        logger.info(f"[OVERLAY_HYST] {symbol} | armed_for={time_armed_ms/1000:.1f}s | need={self.hysteresis_seconds}s | allow_open={self.allow_hedge_open}")
                        if time_armed_ms >= self.hysteresis_seconds * 1000:
                            logger.info(f"[OVERLAY_HEDGE] {symbol} | Opening hedge after {time_armed_ms/1000:.1f}s hysteresis | ROE={pnl_pct:.1f}%")
                            # Generate hedge open intent
                            hedge_size = self._calculate_hedge_size(pnl_pct)
                            hedge_action = OverlayAction.OPEN_HEDGE_SHORT if side == 'LONG' else OverlayAction.OPEN_HEDGE_LONG
                            reason = CloseReasonCode.HEDGE_TRIGGER_20PCT if pnl_pct > 0 else CloseReasonCode.LOSS_HEDGE_20PCT
                            
                            intent = OverlayIntent(
                                signal_id=str(uuid.uuid4()),
                                symbol=symbol,
                                action=hedge_action,
                                hedge_size_pct=hedge_size * 100,
                                pnl_pct=pnl_pct,
                                roe_pct=pnl_pct,
                                mfe_pct=mfe_pct,
                                mae_pct=state.mae_pct,
                                retrace_pct=retrace_pct,
                                trailing_width_pct=state.trailing_width_pct,
                                close_reason_code=reason,
                                reason_detail=f"ROE {pnl_pct:.1f}% triggers hedge",
                                timestamp_ms=now_ms,
                            )
                            intents.append(intent)
                            state.runner_mode = RunnerMode.HEDGED
                            hedge.state = HedgeState.HEDGE_OPEN
                            hedge.hedge_active = True
                            hedge.hedge_side = 'SHORT' if side == 'LONG' else 'LONG'
        
        # ========================================================================
        # B) Trailing stop trigger
        # ========================================================================
        mark_price = float(position.get('markPrice', 0) or position.get('mark_price', 0) or entry_price)
        if state.trailing_stop_price > 0:
            triggered = False
            if side == 'LONG' and mark_price <= state.trailing_stop_price:
                triggered = True
            elif side == 'SHORT' and mark_price >= state.trailing_stop_price:
                triggered = True
            
            if triggered and state.runner_mode in [RunnerMode.RUNNER_ACTIVE, RunnerMode.HEDGED]:
                intent = OverlayIntent(
                    signal_id=str(uuid.uuid4()),
                    symbol=symbol,
                    action=OverlayAction.PARTIAL_CLOSE,
                    close_pct=20.0,  # Close 20% on trailing trigger
                    pnl_pct=pnl_pct,
                    roe_pct=pnl_pct,
                    mfe_pct=mfe_pct,
                    mae_pct=state.mae_pct,
                    retrace_pct=retrace_pct,
                    trailing_width_pct=state.trailing_width_pct,
                    close_reason_code=CloseReasonCode.TRAILING_PROTECT,
                    reason_detail=f"Trailing stop triggered at {mark_price:.4f}",
                    timestamp_ms=now_ms,
                )
                intents.append(intent)
        
        # ========================================================================
        # C) Don't let green turn red (MFE protection)
        # ========================================================================
        if mfe_pct >= 10.0 and pnl_pct < 2.0 and pnl_pct < mfe_pct * 0.3:
            # Big winner dropping - tighten protection
            intent = OverlayIntent(
                signal_id=str(uuid.uuid4()),
                symbol=symbol,
                action=OverlayAction.PARTIAL_CLOSE,
                close_pct=25.0,  # Close 25% to lock profit
                pnl_pct=pnl_pct,
                roe_pct=pnl_pct,
                mfe_pct=mfe_pct,
                mae_pct=state.mae_pct,
                retrace_pct=retrace_pct,
                trailing_width_pct=state.trailing_width_pct,
                close_reason_code=CloseReasonCode.MFE_PROTECT,
                reason_detail=f"MFE protect: was {mfe_pct:.1f}%, now {pnl_pct:.1f}%",
                timestamp_ms=now_ms,
            )
            intents.append(intent)
        
        # ========================================================================
        # D) Retracement trigger
        # ========================================================================
        if retrace_pct > state.trailing_width_pct and mfe_pct >= 5.0:
            intent = OverlayIntent(
                signal_id=str(uuid.uuid4()),
                symbol=symbol,
                action=OverlayAction.PARTIAL_CLOSE,
                close_pct=15.0,
                pnl_pct=pnl_pct,
                roe_pct=pnl_pct,
                mfe_pct=mfe_pct,
                mae_pct=state.mae_pct,
                retrace_pct=retrace_pct,
                trailing_width_pct=state.trailing_width_pct,
                close_reason_code=CloseReasonCode.PROFIT_LOCK_RETRACE,
                reason_detail=f"Retrace {retrace_pct:.1f}% > trailing {state.trailing_width_pct:.1f}%",
                timestamp_ms=now_ms,
            )
            intents.append(intent)
        
        # Filter out micro partial closes
        filtered_intents = []
        for intent in intents:
            if intent.action == OverlayAction.PARTIAL_CLOSE:
                if intent.close_pct < self.min_delta_close_pct * 100:
                    logger.debug(f"[OVERLAY] {symbol} skip micro close: {intent.close_pct:.1f}% < {self.min_delta_close_pct*100:.1f}%")
                    continue
            filtered_intents.append(intent)
        
        # ====================================================================
        # TRAINER DEFERENCE: If trainer has high-confidence signal aligned with
        # current position side, suppress partial closes (let winners run).
        # Hedge opens are NEVER suppressed (always protective).
        # ====================================================================
        trainer_filtered = []
        for intent in filtered_intents:
            is_close_intent = intent.action in (
                OverlayAction.PARTIAL_CLOSE, OverlayAction.DECREASE_LONG,
                OverlayAction.DECREASE_SHORT,
            )
            if is_close_intent and trainer_conf >= 0.92:
                pos_side_u = str(state.side or "").upper()
                trainer_agrees = (
                    (pos_side_u == "LONG" and trainer_action in ("OPEN_LONG", "INCREASE_LONG"))
                    or (pos_side_u == "SHORT" and trainer_action in ("OPEN_SHORT", "INCREASE_SHORT"))
                )
                if trainer_agrees:
                    logger.info(
                        f"[OVERLAY_TRAINER_DEFER] {symbol} | Suppressing {intent.action.value} | "
                        f"trainer_action={trainer_action} conf={trainer_conf:.3f} | Let winner run"
                    )
                    continue  # Skip this close intent — trainer wants to keep position
            trainer_filtered.append(intent)
        
        # Dedupe intents
        seen_actions: Set[str] = set()
        unique_intents = []
        for intent in trainer_filtered:
            key = f"{intent.action.value}"
            if key not in seen_actions:
                seen_actions.add(key)
                unique_intents.append(intent)
        
        # Apply anti-churn: only allow one action per cycle
        if unique_intents:
            final_intent = unique_intents[0]  # Take highest priority
            self._record_action(symbol, now_ms)
            state.cooldown_until_ms = now_ms + self.min_action_interval_sec * 1000
            return [final_intent]
        
        return []
    
    def _check_rate_limit(self, symbol: str, now_ms: int) -> bool:
        """Check if action is allowed by rate limit."""
        window_start = now_ms - 10 * 60 * 1000  # 10 minute window
        self._action_window[symbol] = [
            ts for ts in self._action_window[symbol]
            if ts > window_start
        ]
        return len(self._action_window[symbol]) < self.max_actions_per_10min
    
    def _record_action(self, symbol: str, now_ms: int):
        """Record an action for rate limiting."""
        self._action_window[symbol].append(now_ms)
        state = self._get_runner_state(symbol)
        state.actions_in_window = len(self._action_window[symbol])
        state.last_action_ts_ms = now_ms
    
    def _calculate_hedge_size(self, roe_pct: float) -> float:
        """Calculate hedge size as fraction of main position."""
        abs_roe = abs(roe_pct)
        if abs_roe >= 80:
            return self.hedge_size_80pct
        elif abs_roe >= 40:
            return self.hedge_size_40pct
        else:
            return self.hedge_size_20pct
    
    def record_intent(
        self,
        symbol: str,
        intent: OverlayIntent,
        outcome: Optional[str] = None,
    ):
        """Record intent outcome for telemetry."""
        logger.info(intent.to_log_line())
        
        if outcome:
            logger.info(f"OVERLAY_OUTCOME | {symbol} | {intent.action.value} | outcome={outcome}")
    
    def log_state(self, symbol: str):
        """Log current overlay state for telemetry."""
        state = self._get_runner_state(symbol)
        hedge = self._get_hedge_state(symbol)
        
        logger.info(
            f"OVERLAY_STATE | {symbol} | {state.side} | "
            f"pnl%={state.current_pnl_pct:.2f} | mfe%={state.mfe_pct:.2f} | mae%={state.mae_pct:.2f} | "
            f"mode={state.runner_mode.value} | hedge_active={hedge.hedge_active} | "
            f"trailing_stop={state.trailing_stop_price:.6f}"
        )
    
    def log_all_states(self):
        """Log all active runner states periodically."""
        now = time.time()
        if now - self._last_log_ts < self.log_interval_sec:
            return
        
        self._last_log_ts = now
        
        active_states = [s for s in self._runner_states.values() if s.runner_mode != RunnerMode.NONE]
        if active_states:
            for state in active_states:
                self.log_state(state.symbol)
    
    def get_state_json(self, symbol: str) -> str:
        """Get state as JSON for Redis persistence."""
        state = self._get_runner_state(symbol)
        hedge = self._get_hedge_state(symbol)
        return json.dumps({
            'runner': state.to_dict(),
            'hedge': hedge.to_dict(),
        })
    
    def clear_state(self, symbol: str):
        """Clear state for a symbol (on position close)."""
        if symbol in self._runner_states:
            del self._runner_states[symbol]
        if symbol in self._hedge_states:
            del self._hedge_states[symbol]
        if symbol in self._action_window:
            del self._action_window[symbol]
        logger.debug(f"[OVERLAY] Cleared state for {symbol}")


# Global instance
_dynamic_runner_manager: Optional[DynamicRunnerHedgeManager] = None


def get_dynamic_runner_manager(
    redis_client: Any = None,
    force_new: bool = False,
) -> DynamicRunnerHedgeManager:
    """Get global dynamic runner manager instance."""
    global _dynamic_runner_manager
    if _dynamic_runner_manager is None or force_new:
        from config import (
            ENABLE_DYNAMIC_RUNNER_HEDGE,
        )
        enable_execute = os.getenv("ENABLE_DYNAMIC_RUNNER_HEDGE_EXECUTE", "false").lower() == "true"
        allow_hedge_open = os.getenv("DYNAMIC_HEDGE_ALLOW_OPEN", "false").lower() == "true"
        
        _dynamic_runner_manager = DynamicRunnerHedgeManager(
            redis_client=redis_client,
            enable_execute=enable_execute,
            allow_hedge_open=allow_hedge_open,
        )
    return _dynamic_runner_manager
