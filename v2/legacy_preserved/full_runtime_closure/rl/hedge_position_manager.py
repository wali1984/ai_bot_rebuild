"""
Hedge Position Manager
Manages simultaneous long & short positions per symbol with caps and safety limits
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Set
from dataclasses import dataclass
from enum import Enum
import time
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)


class PositionSide(Enum):
    """Position sides for hedge trading"""
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class HedgePosition:
    """Single hedge position (either long or short)"""
    symbol: str
    side: PositionSide
    quantity: float
    avg_price: float
    leverage: float
    unrealized_pnl: float
    margin_used: float
    entry_time: float
    last_update: float


@dataclass
class SymbolHedgeState:
    """Complete hedge state for a single symbol"""
    symbol: str
    long_position: Optional[HedgePosition]
    short_position: Optional[HedgePosition]
    net_exposure: float
    gross_exposure: float
    hedge_enabled: bool
    confidence_score: float
    last_action_time: float


class HedgePositionManager:
    """
    Manages hedge positions with simultaneous long & short per symbol.
    
    Key Features:
    - Up to 3 symbols (6 legs) in base mode
    - Up to 5 symbols (10 legs) with confidence gate
    - Per-symbol exposure limits
    - Minimum hold time enforcement
    - Auto-contraction on risk threshold breach
    """
    
    def __init__(
        self,
        max_symbols_base: int = 3,
        max_symbols_boost: int = 5,
        max_exposure_per_symbol: float = 0.30,  # 30% of portfolio
        min_hold_minutes: int = 20,
        confidence_boost_threshold: float = 0.85,
        daily_loss_limit: float = 0.05,  # 5%
        auto_contract_threshold: float = 0.75,
        max_portfolio_exposure: float = 0.60,
        stop_loss_pct: float = 0.08,
    ):
        """
        Initialize hedge position manager.
        
        Args:
            max_symbols_base: Base mode symbol limit (3)
            max_symbols_boost: Boosted mode symbol limit (5)
            max_exposure_per_symbol: Max exposure per symbol (30%)
            min_hold_minutes: Minimum hold time (20 min)
            confidence_boost_threshold: Confidence needed for boost mode
            daily_loss_limit: Daily loss limit for auto-contraction
            auto_contract_threshold: Confidence threshold for auto-contraction
        """
        self.max_symbols_base = max_symbols_base
        self.max_symbols_boost = max_symbols_boost
        self.max_exposure_per_symbol = max_exposure_per_symbol
        self.min_hold_minutes = min_hold_minutes
        self.confidence_boost_threshold = confidence_boost_threshold
        self.daily_loss_limit = daily_loss_limit
        self.auto_contract_threshold = auto_contract_threshold
        self.max_portfolio_exposure = max_portfolio_exposure
        self.stop_loss_pct = stop_loss_pct
        
        # Position tracking
        self.hedge_positions: Dict[str, SymbolHedgeState] = {}
        self.total_margin_used = 0.0
        self.daily_pnl = 0.0
        self.daily_start_balance = 0.0
        self.is_boost_mode = False
        self.boost_start_time = None
        self._last_reset_day = datetime.utcnow().date()
        
        logger.info(f"HedgePositionManager initialized: base={max_symbols_base}, boost={max_symbols_boost}")
    
    def get_active_symbols(self) -> Set[str]:
        """Get set of symbols with active positions"""
        return set(self.hedge_positions.keys())
    
    def get_symbol_count(self) -> int:
        """Get current number of active symbols"""
        return len(self.hedge_positions)
    
    def get_max_symbols(self) -> int:
        """Get current maximum symbols allowed"""
        return self.max_symbols_boost if self.is_boost_mode else self.max_symbols_base

    def maybe_reset_daily(self, current_balance: float):
        """Reset daily counters when date changes."""
        today = datetime.utcnow().date()
        if today != self._last_reset_day:
            logger.info("🔄 Resetting daily hedge counters")
            self._last_reset_day = today
            self.daily_start_balance = current_balance
            self.daily_pnl = 0.0
    
    def can_add_symbol(self, confidence_scores: List[float] = None) -> Tuple[bool, str]:
        """
        Check if we can add a new symbol.
        
        Args:
            confidence_scores: List of confidence scores for boost mode validation
            
        Returns:
            (can_add, reason)
        """
        current_count = self.get_symbol_count()
        
        # Check base limit
        if current_count >= self.max_symbols_base:
            # Need boost mode
            if not self._can_enter_boost_mode(confidence_scores):
                return False, "At base symbol limit, boost mode not available"
            
            # Enable boost mode if not already
            if not self.is_boost_mode:
                self._enable_boost_mode()
            
            # Check boost limit
            if current_count >= self.max_symbols_boost:
                return False, f"At maximum symbol limit ({self.max_symbols_boost})"
        
        return True, "Symbol addition allowed"
    
    def can_hedge_symbol(
        self, 
        symbol: str, 
        side: PositionSide,
        confidence: float,
        exposure_pct: float
    ) -> Tuple[bool, str]:
        """
        Check if we can open/increase a hedge position.
        
        Args:
            symbol: Trading symbol
            side: Position side (LONG/SHORT)
            confidence: Model confidence
            exposure_pct: Requested exposure as % of portfolio
            
        Returns:
            (can_hedge, reason)
        """
        # Check symbol exposure limit
        if symbol in self.hedge_positions:
            current_exposure = self.hedge_positions[symbol].gross_exposure
            if current_exposure + exposure_pct > self.max_exposure_per_symbol:
                return False, f"Would exceed symbol exposure limit ({self.max_exposure_per_symbol*100:.1f}%)"
        else:
            # New symbol
            can_add, reason = self.can_add_symbol()
            if not can_add:
                return False, reason
            
            if exposure_pct > self.max_exposure_per_symbol:
                return False, f"Initial exposure exceeds symbol limit ({self.max_exposure_per_symbol*100:.1f}%)"
        
        # Check minimum hold time if position exists
        if symbol in self.hedge_positions:
            state = self.hedge_positions[symbol]
            current_time = time.time()
            
            if side == PositionSide.LONG and state.long_position:
                time_held = (current_time - state.long_position.entry_time) / 60
                if time_held < self.min_hold_minutes:
                    return False, f"Long position under min hold time ({time_held:.1f}/{self.min_hold_minutes} min)"
            
            if side == PositionSide.SHORT and state.short_position:
                time_held = (current_time - state.short_position.entry_time) / 60
                if time_held < self.min_hold_minutes:
                    return False, f"Short position under min hold time ({time_held:.1f}/{self.min_hold_minutes} min)"
        
        return True, "Hedge position allowed"

    def enforce_risk_limits(self, equity: float) -> Tuple[bool, str]:
        """
        Enforce portfolio level exposure and daily loss caps.
        Returns (allowed, reason).
        """
        if equity is None or equity <= 0:
            logger.warning("⚠️ Risk limits blocked: equity missing (EQUITY_MISSING_BLOCK)")
            return False, "EQUITY_MISSING_BLOCK"

        exposure_pct = (self.total_margin_used / equity) if equity else 0.0
        if exposure_pct > self.max_portfolio_exposure:
            return False, f"Portfolio exposure {exposure_pct:.2f} exceeds cap {self.max_portfolio_exposure:.2f}"

        if self.daily_start_balance == 0:
            self.daily_start_balance = equity
        daily_loss_pct = abs(self.daily_pnl) / max(1e-6, self.daily_start_balance)
        if daily_loss_pct > self.daily_loss_limit:
            return False, f"Daily loss {daily_loss_pct:.2f} exceeds limit {self.daily_loss_limit:.2f}"

        return True, "Within risk limits"

    def _check_stop_loss(self, state: SymbolHedgeState, current_price: float) -> Optional[str]:
        """Check per-position stop loss threshold; return reason if triggered."""
        stop_reason = None
        if state.long_position:
            drop_pct = (current_price - state.long_position.avg_price) / max(1e-6, state.long_position.avg_price)
            if drop_pct < -self.stop_loss_pct:
                stop_reason = f"Long stop-loss {drop_pct:.2f} < -{self.stop_loss_pct}"
        if state.short_position:
            move_pct = (state.short_position.avg_price - current_price) / max(1e-6, state.short_position.avg_price)
            if move_pct < -self.stop_loss_pct:
                stop_reason = f"Short stop-loss {move_pct:.2f} < -{self.stop_loss_pct}"
        return stop_reason
    
    def open_hedge_position(
        self,
        symbol: str,
        side: PositionSide,
        quantity: float,
        price: float,
        leverage: float,
        confidence: float,
        equity: Optional[float] = None
    ) -> bool:
        """
        Open a new hedge position.
        
        Args:
            symbol: Trading symbol
            side: Position side
            quantity: Position quantity
            price: Entry price
            leverage: Position leverage
            confidence: Model confidence
            
        Returns:
            Success flag
        """
        if equity is not None:
            self.maybe_reset_daily(equity)
            allowed, reason = self.enforce_risk_limits(equity)
            if not allowed:
                logger.warning(f"Risk block opening {symbol}: {reason}")
                return False
        current_time = time.time()
        
        # Create position
        position = HedgePosition(
            symbol=symbol,
            side=side,
            quantity=quantity,
            avg_price=price,
            leverage=leverage,
            unrealized_pnl=0.0,
            margin_used=quantity * price / leverage,
            entry_time=current_time,
            last_update=current_time
        )
        
        # Update symbol state
        if symbol not in self.hedge_positions:
            self.hedge_positions[symbol] = SymbolHedgeState(
                symbol=symbol,
                long_position=None,
                short_position=None,
                net_exposure=0.0,
                gross_exposure=0.0,
                hedge_enabled=True,
                confidence_score=confidence,
                last_action_time=current_time
            )
        
        state = self.hedge_positions[symbol]
        
        if side == PositionSide.LONG:
            state.long_position = position
        else:
            state.short_position = position
        
        self._update_symbol_exposure(state)
        self.total_margin_used += position.margin_used
        
        logger.info(f"Opened {side.value} hedge position: {symbol} qty={quantity} price={price} leverage={leverage}x")
        return True
    
    def close_hedge_position(
        self,
        symbol: str,
        side: Optional[PositionSide] = None
    ) -> Dict[str, float]:
        """
        Close hedge position(s) for a symbol.
        
        Args:
            symbol: Trading symbol
            side: Specific side to close, or None to close both
            
        Returns:
            Dictionary with closed position PnLs
        """
        if symbol not in self.hedge_positions:
            return {}
        
        state = self.hedge_positions[symbol]
        closed_pnls = {}
        
        # Close specific side or both sides
        if side is None or side == PositionSide.LONG:
            if state.long_position:
                closed_pnls['long_pnl'] = state.long_position.unrealized_pnl
                self.total_margin_used -= state.long_position.margin_used
                state.long_position = None
        
        if side is None or side == PositionSide.SHORT:
            if state.short_position:
                closed_pnls['short_pnl'] = state.short_position.unrealized_pnl
                self.total_margin_used -= state.short_position.margin_used
                state.short_position = None
        
        # Remove symbol if no positions left
        if state.long_position is None and state.short_position is None:
            del self.hedge_positions[symbol]
            logger.info(f"Removed symbol {symbol} - no remaining positions")
        else:
            self._update_symbol_exposure(state)
        
        # Check for auto-contraction
        self._check_auto_contraction()
        
        return closed_pnls
    
    def close_all_positions(self) -> Dict[str, Dict[str, float]]:
        """
        Close all hedge positions (emergency function).
        
        Returns:
            Dictionary of all closed position PnLs by symbol
        """
        all_closed = {}
        symbols_to_close = list(self.hedge_positions.keys())
        
        for symbol in symbols_to_close:
            closed_pnls = self.close_hedge_position(symbol)
            if closed_pnls:
                all_closed[symbol] = closed_pnls
        
        logger.warning(f"CLOSE_ALL executed - closed positions in {len(all_closed)} symbols")
        return all_closed
    
    def update_position_pnl(
        self,
        symbol: str,
        current_price: float,
        equity: Optional[float] = None
    ):
        """Update unrealized PnL for symbol positions"""
        if symbol not in self.hedge_positions:
            return
        
        state = self.hedge_positions[symbol]
        current_time = time.time()
        if equity is not None:
            self.maybe_reset_daily(equity)
        
        # Update long position PnL
        if state.long_position:
            price_change = current_price - state.long_position.avg_price
            state.long_position.unrealized_pnl = (
                price_change * state.long_position.quantity
            )
            state.long_position.last_update = current_time
        
        # Update short position PnL
        if state.short_position:
            price_change = state.short_position.avg_price - current_price
            state.short_position.unrealized_pnl = (
                price_change * state.short_position.quantity
            )
            state.short_position.last_update = current_time
        
        self._update_symbol_exposure(state)
        stop_reason = self._check_stop_loss(state, current_price)
        if stop_reason:
            logger.warning(f"Stop-loss triggered for {symbol}: {stop_reason}")
        if equity is not None:
            # Daily PnL approximated from unrealized change
            symbol_pnl = 0.0
            if state.long_position:
                symbol_pnl += state.long_position.unrealized_pnl
            if state.short_position:
                symbol_pnl += state.short_position.unrealized_pnl
            self.daily_pnl = symbol_pnl
    
    def get_portfolio_summary(self) -> Dict:
        """Get comprehensive portfolio summary"""
        total_unrealized_pnl = 0.0
        total_long_exposure = 0.0
        total_short_exposure = 0.0
        symbol_details = {}
        
        for symbol, state in self.hedge_positions.items():
            long_qty = state.long_position.quantity if state.long_position else 0.0
            short_qty = state.short_position.quantity if state.short_position else 0.0
            long_pnl = state.long_position.unrealized_pnl if state.long_position else 0.0
            short_pnl = state.short_position.unrealized_pnl if state.short_position else 0.0
            
            total_unrealized_pnl += long_pnl + short_pnl
            total_long_exposure += abs(long_qty) * (state.long_position.avg_price if state.long_position else 0)
            total_short_exposure += abs(short_qty) * (state.short_position.avg_price if state.short_position else 0)
            
            symbol_details[symbol] = {
                'long_qty': long_qty,
                'short_qty': short_qty,
                'net_qty': long_qty + short_qty,
                'long_pnl': long_pnl,
                'short_pnl': short_pnl,
                'total_pnl': long_pnl + short_pnl,
                'gross_exposure': state.gross_exposure,
                'net_exposure': state.net_exposure
            }
        
        return {
            'symbol_count': len(self.hedge_positions),
            'max_symbols': self.get_max_symbols(),
            'is_boost_mode': self.is_boost_mode,
            'total_unrealized_pnl': total_unrealized_pnl,
            'total_margin_used': self.total_margin_used,
            'total_long_exposure': total_long_exposure,
            'total_short_exposure': total_short_exposure,
            'gross_exposure': total_long_exposure + total_short_exposure,
            'net_exposure': total_long_exposure - total_short_exposure,
            'daily_pnl': self.daily_pnl,
            'symbols': symbol_details
        }
    
    def _can_enter_boost_mode(self, confidence_scores: List[float] = None) -> bool:
        """Check if boost mode can be enabled"""
        if confidence_scores is None or len(confidence_scores) < 3:
            return False
        
        # Need 3 independent timeframes with high confidence
        high_conf_count = sum(1 for conf in confidence_scores if conf >= self.confidence_boost_threshold)
        return high_conf_count >= 3
    
    def _enable_boost_mode(self):
        """Enable boost mode"""
        self.is_boost_mode = True
        self.boost_start_time = time.time()
        logger.info("🚀 Boost mode ENABLED - increased to 5 symbol capacity")
    
    def _disable_boost_mode(self):
        """Disable boost mode"""
        self.is_boost_mode = False
        self.boost_start_time = None
        logger.info("⬇️ Boost mode DISABLED - back to 3 symbol capacity")
    
    def _update_symbol_exposure(self, state: SymbolHedgeState):
        """Update exposure calculations for a symbol"""
        long_exp = 0.0
        short_exp = 0.0
        
        if state.long_position:
            long_exp = state.long_position.quantity * state.long_position.avg_price
        
        if state.short_position:
            short_exp = state.short_position.quantity * state.short_position.avg_price
        
        state.gross_exposure = long_exp + short_exp
        state.net_exposure = long_exp - short_exp
    
    def _check_auto_contraction(self):
        """Check if auto-contraction should trigger"""
        # Check daily loss limit
        if self.daily_start_balance > 0:
            daily_loss_pct = abs(self.daily_pnl) / self.daily_start_balance
            if daily_loss_pct > self.daily_loss_limit:
                logger.warning(f"Daily loss limit breached: {daily_loss_pct*100:.1f}% > {self.daily_loss_limit*100:.1f}%")
                self._trigger_auto_contraction("daily_loss_limit")
                return
        
        # Check confidence degradation
        avg_confidence = sum(
            state.confidence_score for state in self.hedge_positions.values()
        ) / max(1, len(self.hedge_positions))
        
        if avg_confidence < self.auto_contract_threshold:
            logger.warning(f"Average confidence below threshold: {avg_confidence:.2f} < {self.auto_contract_threshold:.2f}")
            self._trigger_auto_contraction("low_confidence")
    
    def _trigger_auto_contraction(self, reason: str):
        """Trigger automatic position contraction"""
        if self.is_boost_mode:
            self._disable_boost_mode()
        
        # Close positions to get back to base limit
        current_count = self.get_symbol_count()
        if current_count > self.max_symbols_base:
            symbols_to_close = current_count - self.max_symbols_base
            
            # Close lowest confidence symbols first
            sorted_symbols = sorted(
                self.hedge_positions.items(),
                key=lambda x: x[1].confidence_score
            )
            
            for i in range(symbols_to_close):
                symbol = sorted_symbols[i][0]
                self.close_hedge_position(symbol)
                logger.warning(f"Auto-contracted: closed {symbol} (reason: {reason})")


if __name__ == "__main__":
    # Test the hedge position manager
    logging.basicConfig(level=logging.INFO)
    
    manager = HedgePositionManager()
    
    # Test opening positions
    print("🧪 Testing hedge position management...")
    
    # Open long BTC (smaller size)
    success = manager.open_hedge_position("BTCUSDT", PositionSide.LONG, 0.1, 50000, 5.0, 0.85)
    print(f"Opened BTC long: {success}")
    
    # Open short BTC (hedge) - should work now with smaller combined exposure
    can_hedge, reason = manager.can_hedge_symbol("BTCUSDT", PositionSide.SHORT, 0.8, 0.08)  # 8% exposure
    print(f"Can hedge BTC short: {can_hedge} - {reason}")
    
    if can_hedge:
        success = manager.open_hedge_position("BTCUSDT", PositionSide.SHORT, 0.15, 49500, 4.0, 0.8)
        print(f"Opened BTC short hedge: {success}")
    
    # Test adding more symbols
    print("\n🔄 Testing multi-symbol hedge capacity...")
    for i, symbol in enumerate(["ETHUSDT", "SOLUSDT", "ADAUSDT"]):
        can_add, reason = manager.can_add_symbol()
        print(f"Can add {symbol}: {can_add} - {reason}")
        if can_add:
            success = manager.open_hedge_position(symbol, PositionSide.LONG, 0.05, 1000 + i*100, 3.0, 0.75)
            print(f"  Added {symbol} long: {success}")
    
    # Test boost mode simulation (would need high confidence)
    print(f"\nBefore boost attempt: {manager.get_symbol_count()}/{manager.get_max_symbols()} symbols")
    can_boost = manager._can_enter_boost_mode([0.87, 0.89, 0.91])  # 3 high confidence scores
    print(f"Can enter boost mode: {can_boost}")
    if can_boost:
        manager._enable_boost_mode()
        print(f"After boost: {manager.get_symbol_count()}/{manager.get_max_symbols()} symbols")
    
    # Get portfolio summary
    summary = manager.get_portfolio_summary()
    print("\n📊 Portfolio Summary:")
    for key, value in summary.items():
        if key != 'symbols':
            print(f"  {key}: {value}")
    
    print("\n💰 Symbol Details:")
    for symbol, details in summary['symbols'].items():
        print(f"  {symbol}: net_qty={details['net_qty']:.3f}, pnl=${details['total_pnl']:.2f}")