"""
Stealth Stops + Dynamic/Trailing Stops Integration
Ensures both systems work together without conflicts
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class StealthDynamicIntegration:
    """
    Coordinates between stealth stops (execution layer) and 
    dynamic/trailing stops (calculation layer)
    
    ARCHITECTURE:
    ============
    
    Dynamic/Trailing System → Calculates optimal stop levels
            ↓
    StealthDynamicIntegration → Updates stealth stops
            ↓
    Stealth Monitor → Executes when price hits trigger
    
    This ensures:
    - Stealth stops reflect current dynamic/trailing levels
    - No conflicts between systems
    - Dynamic adjustments propagate to execution layer
    """
    
    def __init__(self, stealth_monitor):
        """
        Args:
            stealth_monitor: StealthStopMonitor instance
        """
        self.stealth_monitor = stealth_monitor
        
        # Track last update times to avoid thrashing
        self.last_updates: Dict[str, float] = {}  # position_id -> timestamp
        
        logger.info("🔗 StealthDynamicIntegration initialized")
    
    def update_trailing_stop(
        self,
        symbol: str,
        side: str,
        new_stop_price: float,
        position_size: float,
        account_id: str = "primary",
        reason: str = "Trailing stop updated"
    ) -> bool:
        """
        Update stealth stop when trailing stop adjusts
        
        Args:
            symbol: Trading symbol
            side: Position side (LONG/SHORT)
            new_stop_price: New stop-loss price from trailing logic
            position_size: Position size
            account_id: Account identifier
            reason: Reason for update
            
        Returns:
            True if updated successfully
        """
        import time
        from trading.stealth_stops import StealthStop
        
        position_id = f"{symbol}_{side}_{account_id}"
        current_time = time.time()
        
        # Throttle updates (max once per 10 seconds to avoid thrashing)
        last_update = self.last_updates.get(position_id, 0)
        if current_time - last_update < 10:
            logger.debug(f"[STEALTH-DYNAMIC] Throttling update for {position_id} "
                        f"(last update {current_time - last_update:.1f}s ago)")
            return False
        
        try:
            # Create stealth stop with updated price
            stop = StealthStop(
                symbol=symbol,
                side=side,
                stop_type='STOP_LOSS',
                trigger_price=new_stop_price,
                position_size=position_size,
                close_percentage=100.0,
                account_id=account_id,
                reason=reason
            )
            
            # Update stealth monitor
            self.stealth_monitor.add_stop(stop, source="trailing")
            
            self.last_updates[position_id] = current_time
            
            logger.info(f"🔗 [STEALTH-DYNAMIC] Updated trailing stop for {symbol} {side}: "
                       f"new stop @ {new_stop_price:.2f}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ [STEALTH-DYNAMIC] Failed to update trailing stop: {e}")
            return False
    
    def update_dynamic_take_profit(
        self,
        symbol: str,
        side: str,
        new_tp_price: float,
        position_size: float,
        close_percentage: float = 100.0,
        account_id: str = "primary",
        reason: str = "Dynamic take profit updated"
    ) -> bool:
        """
        Update stealth stop when dynamic take profit adjusts
        
        Args:
            symbol: Trading symbol
            side: Position side (LONG/SHORT)
            new_tp_price: New take-profit price from dynamic logic
            position_size: Position size
            close_percentage: Percentage of position to close (50-100)
            account_id: Account identifier
            reason: Reason for update
            
        Returns:
            True if updated successfully
        """
        import time
        from trading.stealth_stops import StealthStop
        
        position_id = f"{symbol}_{side}_{account_id}_TP"
        current_time = time.time()
        
        # Throttle updates
        last_update = self.last_updates.get(position_id, 0)
        if current_time - last_update < 10:
            logger.debug(f"[STEALTH-DYNAMIC] Throttling TP update for {position_id}")
            return False
        
        try:
            # Create stealth stop for take profit
            stop = StealthStop(
                symbol=symbol,
                side=side,
                stop_type='TAKE_PROFIT',
                trigger_price=new_tp_price,
                position_size=position_size,
                close_percentage=close_percentage,
                account_id=account_id,
                reason=reason
            )
            
            # Update stealth monitor
            self.stealth_monitor.add_stop(stop, source="dynamic")
            
            self.last_updates[position_id] = current_time
            
            logger.info(f"🔗 [STEALTH-DYNAMIC] Updated dynamic TP for {symbol} {side}: "
                       f"new TP @ {new_tp_price:.2f} ({close_percentage}%)")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ [STEALTH-DYNAMIC] Failed to update dynamic TP: {e}")
            return False
    
    def remove_dynamic_stops(
        self,
        symbol: str,
        side: str,
        account_id: str = "primary"
    ) -> bool:
        """
        Remove stealth stops when position is closed or dynamic stops disabled
        
        Args:
            symbol: Trading symbol
            side: Position side
            account_id: Account identifier
            
        Returns:
            True if removed successfully
        """
        try:
            self.stealth_monitor.remove_stop(symbol, side, 'STOP_LOSS')
            self.stealth_monitor.remove_stop(symbol, side, 'TAKE_PROFIT')
            
            # Clear tracking
            position_id_sl = f"{symbol}_{side}_{account_id}"
            position_id_tp = f"{symbol}_{side}_{account_id}_TP"
            self.last_updates.pop(position_id_sl, None)
            self.last_updates.pop(position_id_tp, None)
            
            logger.info(f"🔗 [STEALTH-DYNAMIC] Removed dynamic stops for {symbol} {side}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ [STEALTH-DYNAMIC] Failed to remove stops: {e}")
            return False


def create_stealth_dynamic_integration(stealth_monitor) -> Optional[StealthDynamicIntegration]:
    """
    Factory function to create integration
    
    Args:
        stealth_monitor: StealthStopMonitor instance
        
    Returns:
        StealthDynamicIntegration instance or None if stealth_monitor is None
    """
    if stealth_monitor is None:
        logger.warning("⚠️ Stealth monitor not available - integration disabled")
        return None
    
    return StealthDynamicIntegration(stealth_monitor)

