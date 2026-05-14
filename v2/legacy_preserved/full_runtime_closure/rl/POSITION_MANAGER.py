"""
Position Manager - Strict margin allocation and position limits
Ensures disciplined trading with proper risk management
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from collections import defaultdict
import time

logger = logging.getLogger(__name__)


class PositionManager:
    """
    Manages position limits and margin allocation across both accounts.
    
    Rules:
    - Max 40% margin for LONG positions
    - Max 40% margin for SHORT positions (hedge)
    - Max 10 positions total (5 per side, +3 for high confidence >95%)
    - Replace lower confidence positions with higher confidence signals
    """
    
    def __init__(self, portfolio_tracker=None):
        self.portfolio_tracker = portfolio_tracker
        
        # Position limits
        self.MAX_POSITIONS_PER_SIDE = 5
        self.MAX_HIGH_CONF_EXTRA = 3  # Extra positions for >95% confidence
        self.MAX_TOTAL_POSITIONS = 10
        
        # Margin allocation (as percentage of available margin)
        self.MAX_MARGIN_PER_SIDE = 0.40  # 40%
        self.RESERVE_MARGIN = 0.20  # 20% kept in reserve
        
        # High confidence threshold for extra positions
        self.HIGH_CONFIDENCE_THRESHOLD = 0.95
        
        # Current positions tracking
        self.long_positions = {}  # {symbol: {'confidence': float, 'margin_used': float, 'timestamp': float}}
        self.short_positions = {}
        
        logger.info(f"🎯 PositionManager initialized: {self.MAX_POSITIONS_PER_SIDE}+{self.MAX_HIGH_CONF_EXTRA} per side, {self.MAX_MARGIN_PER_SIDE*100}% margin limit")
    
    def sync_positions(self) -> Dict[str, Any]:
        """Sync current positions from portfolio tracker"""
        if not self.portfolio_tracker:
            return {'long': {}, 'short': {}, 'total_long_margin': 0, 'total_short_margin': 0}
        
        try:
            combined_state = self.portfolio_tracker.sync_all_accounts()
            
            # Reset tracking
            self.long_positions = {}
            self.short_positions = {}
            
            total_long_margin = 0
            total_short_margin = 0
            
            # Process positions from both accounts
            for account_name, account_data in combined_state.get('accounts', {}).items():
                for pos in account_data.get('positions', []):
                    symbol = pos['symbol']
                    side = pos['side']
                    margin = abs(pos.get('entry_price', 0) * pos.get('size', 0))
                    
                    pos_info = {
                        'confidence': 0.75,  # Default, will be updated from Redis if available
                        'margin_used': margin,
                        'timestamp': time.time(),
                        'pnl_pct': pos.get('pnl_pct', 0),
                        'account': account_name
                    }
                    
                    if side == 'LONG':
                        self.long_positions[symbol] = pos_info
                        total_long_margin += margin
                    else:
                        self.short_positions[symbol] = pos_info
                        total_short_margin += margin
            
            return {
                'long': self.long_positions,
                'short': self.short_positions,
                'total_long_margin': total_long_margin,
                'total_short_margin': total_short_margin,
                'available_margin': combined_state.get('total_available_margin', 0)
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to sync positions: {e}")
            return {'long': {}, 'short': {}, 'total_long_margin': 0, 'total_short_margin': 0}
    
    def can_open_position(
        self,
        symbol: str,
        side: str,
        confidence: float,
        estimated_margin: float,
        available_margin: float
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Check if we can open a new position.
        
        Returns:
            (can_open, reason, symbol_to_close)
        """
        # Sync current positions
        state = self.sync_positions()
        
        positions = self.long_positions if side == 'LONG' else self.short_positions
        opposite_positions = self.short_positions if side == 'LONG' else self.long_positions
        
        current_count = len(positions)
        total_margin_used = state['total_long_margin'] if side == 'LONG' else state['total_short_margin']
        
        # Check if position already exists
        if symbol in positions:
            return False, f"Position already exists for {symbol} {side}", None
        
        # Calculate margin limits
        max_margin_allowed = available_margin * self.MAX_MARGIN_PER_SIDE
        margin_after_open = total_margin_used + estimated_margin
        
        # Check margin limit
        if margin_after_open > max_margin_allowed:
            margin_pct = (margin_after_open / available_margin) * 100
            return False, f"Would exceed {self.MAX_MARGIN_PER_SIDE*100}% margin limit ({margin_pct:.1f}%)", None
        
        # Check position limits
        base_limit = self.MAX_POSITIONS_PER_SIDE
        high_conf_limit = base_limit + self.MAX_HIGH_CONF_EXTRA
        
        # High confidence (>95%) or squeeze gets extra slots
        is_high_confidence = confidence >= self.HIGH_CONFIDENCE_THRESHOLD
        
        if current_count >= high_conf_limit:
            return False, f"Max positions reached ({high_conf_limit})", None
        
        if current_count >= base_limit and not is_high_confidence:
            # Can't open more unless high confidence
            # Try to replace lower confidence position
            lowest_conf_symbol = self._find_lowest_confidence_position(positions, confidence)
            if lowest_conf_symbol:
                return True, f"Will replace {lowest_conf_symbol} (lower confidence)", lowest_conf_symbol
            else:
                return False, f"At limit ({base_limit}) - need >{self.HIGH_CONFIDENCE_THRESHOLD*100}% confidence", None
        
        # Check total positions across both sides
        total_positions = len(self.long_positions) + len(self.short_positions)
        if total_positions >= self.MAX_TOTAL_POSITIONS:
            return False, f"Max total positions reached ({self.MAX_TOTAL_POSITIONS})", None
        
        # All checks passed
        return True, f"OK: {current_count+1}/{high_conf_limit} positions, {(margin_after_open/available_margin)*100:.1f}% margin", None
    
    def _find_lowest_confidence_position(self, positions: Dict, new_confidence: float) -> Optional[str]:
        """Find the position with lowest confidence that's lower than new signal"""
        if not positions:
            return None
        
        lowest_symbol = None
        lowest_conf = new_confidence
        
        for symbol, info in positions.items():
            if info['confidence'] < lowest_conf:
                lowest_conf = info['confidence']
                lowest_symbol = symbol
        
        return lowest_symbol
    
    def should_close_for_better_signal(
        self,
        symbol: str,
        side: str,
        new_confidence: float
    ) -> Tuple[bool, str]:
        """Check if we should close existing position for better signal"""
        positions = self.long_positions if side == 'LONG' else self.short_positions
        
        if symbol not in positions:
            return False, "No existing position"
        
        current_conf = positions[symbol]['confidence']
        
        # Only replace if new confidence is significantly higher (>5% better)
        if new_confidence > current_conf + 0.05:
            return True, f"Higher confidence: {new_confidence:.1%} vs {current_conf:.1%}"
        
        return False, f"Not enough improvement: {new_confidence:.1%} vs {current_conf:.1%}"
    
    def get_position_stats(self) -> Dict[str, Any]:
        """Get current position statistics"""
        state = self.sync_positions()
        
        long_count = len(self.long_positions)
        short_count = len(self.short_positions)
        total_count = long_count + short_count
        
        available_margin = state.get('available_margin', 0)
        long_margin_pct = (state['total_long_margin'] / available_margin * 100) if available_margin > 0 else 0
        short_margin_pct = (state['total_short_margin'] / available_margin * 100) if available_margin > 0 else 0
        
        return {
            'long_positions': long_count,
            'short_positions': short_count,
            'total_positions': total_count,
            'long_margin_pct': long_margin_pct,
            'short_margin_pct': short_margin_pct,
            'long_margin_used': state['total_long_margin'],
            'short_margin_used': state['total_short_margin'],
            'available_margin': available_margin,
            'can_open_long': long_count < (self.MAX_POSITIONS_PER_SIDE + self.MAX_HIGH_CONF_EXTRA),
            'can_open_short': short_count < (self.MAX_POSITIONS_PER_SIDE + self.MAX_HIGH_CONF_EXTRA),
            'long_at_margin_limit': long_margin_pct >= (self.MAX_MARGIN_PER_SIDE * 100),
            'short_at_margin_limit': short_margin_pct >= (self.MAX_MARGIN_PER_SIDE * 100)
        }
    
    def log_stats(self):
        """Log current position statistics"""
        stats = self.get_position_stats()
        
        logger.info("=" * 70)
        logger.info("📊 POSITION MANAGER STATS")
        logger.info(f"   LONG: {stats['long_positions']}/{self.MAX_POSITIONS_PER_SIDE}+{self.MAX_HIGH_CONF_EXTRA} positions, "
                   f"{stats['long_margin_pct']:.1f}% margin (limit: {self.MAX_MARGIN_PER_SIDE*100}%)")
        logger.info(f"   SHORT: {stats['short_positions']}/{self.MAX_POSITIONS_PER_SIDE}+{self.MAX_HIGH_CONF_EXTRA} positions, "
                   f"{stats['short_margin_pct']:.1f}% margin (limit: {self.MAX_MARGIN_PER_SIDE*100}%)")
        logger.info(f"   TOTAL: {stats['total_positions']}/{self.MAX_TOTAL_POSITIONS} positions")
        logger.info(f"   Available margin: ${stats['available_margin']:.2f}")
        logger.info("=" * 70)
    
    def get_margin_for_new_position(self, available_margin: float, side: str) -> float:
        """Calculate how much margin we can use for a new position"""
        state = self.sync_positions()
        
        max_margin_allowed = available_margin * self.MAX_MARGIN_PER_SIDE
        current_margin_used = state['total_long_margin'] if side == 'LONG' else state['total_short_margin']
        
        remaining_margin = max_margin_allowed - current_margin_used
        
        return max(0, remaining_margin)


def create_position_manager(portfolio_tracker=None):
    """Create and initialize position manager"""
    manager = PositionManager(portfolio_tracker=portfolio_tracker)
    logger.info("🎯 Position Manager created with strict limits")
    return manager

