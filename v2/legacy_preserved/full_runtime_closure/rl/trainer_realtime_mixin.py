"""
Phase 3: Trainer Real-Time Awareness Enhancement
=================================================
Add real-time visibility into execution state for hybrid_trainer.py

This module provides methods to:
1. Subscribe to position updates from traders
2. Get real-time balance and P&L
3. Monitor trade execution and fills
4. Track execution lag and slippage
5. Publish enhanced signals with all execution parameters

Usage:
    from rl.trainer_realtime_mixin import TrainerRealtimeMixin
    
    class HybridTrainer(TrainerRealtimeMixin):
        ...
"""
import time
import json
import logging
from typing import Dict, Any, List, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class TrainerRealtimeMixin:
    """
    Mixin to add real-time awareness to hybrid trainer
    Provides methods to monitor execution state across all accounts
    """
    
    def init_realtime_monitoring(self):
        """Initialize real-time monitoring components"""
        # Position tracking
        self._realtime_positions = defaultdict(dict)  # {account_id: {symbol: position_data}}
        self._realtime_balances = {}  # {account_id: balance_data}
        self._realtime_fills = defaultdict(list)  # {account_id: [fill_data]}
        
        # Execution tracking
        self._signal_execution_map = {}  # {signal_id: execution_data}
        self._execution_lag = defaultdict(list)  # {account_id: [lag_times]}
        self._slippage_history = defaultdict(list)  # {symbol: [slippage_values]}
        
        # Last update times
        self._last_position_update = {}  # {account_id: timestamp}
        self._last_balance_update = {}  # {account_id: timestamp}
        
        logger.info("✅ Real-time monitoring initialized")
    
    def get_real_time_position(self, symbol: str, account_id: str = "primary") -> Optional[Dict[str, Any]]:
        """
        Get current position from trader for a symbol
        
        Args:
            symbol: Trading symbol (e.g., 'BTCUSDT')
            account_id: Account identifier
        
        Returns:
            Position dictionary or None if no position
        """
        try:
            key = f"wma:{account_id}:positions:{symbol}"
            position_data = self.redis.get(key)
            
            if not position_data:
                return None
            
            position = json.loads(position_data)
            
            # Update cache
            self._realtime_positions[account_id][symbol] = position
            self._last_position_update[account_id] = time.time()
            
            return position
            
        except Exception as e:
            logger.error(f"Failed to get real-time position for {symbol} ({account_id}): {e}")
            return self._realtime_positions.get(account_id, {}).get(symbol)
    
    def get_all_real_time_positions(self, account_id: str = "primary") -> Dict[str, Dict[str, Any]]:
        """
        Get all current positions for an account
        
        Args:
            account_id: Account identifier
        
        Returns:
            Dictionary of {symbol: position_data}
        """
        try:
            pattern = f"wma:{account_id}:positions:*"
            keys = self.redis.keys(pattern)
            
            positions = {}
            for key in keys:
                try:
                    position_data = self.redis.get(key)
                    if position_data:
                        position = json.loads(position_data)
                        symbol = position.get('symbol')
                        if symbol:
                            positions[symbol] = position
                except Exception as e:
                    logger.error(f"Error reading position from {key}: {e}")
            
            # Update cache
            self._realtime_positions[account_id] = positions
            self._last_position_update[account_id] = time.time()
            
            return positions
            
        except Exception as e:
            logger.error(f"Failed to get all positions for {account_id}: {e}")
            return self._realtime_positions.get(account_id, {})
    
    def get_real_time_balance(self, account_id: str = "primary") -> Optional[Dict[str, float]]:
        """
        Get current account balance
        
        Args:
            account_id: Account identifier
        
        Returns:
            Balance dictionary with balance, available, unrealized_pnl
        """
        try:
            key = f"wma:{account_id}:balance"
            balance_data = self.redis.get(key)
            
            if not balance_data:
                return None
            
            balance = json.loads(balance_data)
            
            # Update cache
            self._realtime_balances[account_id] = balance
            self._last_balance_update[account_id] = time.time()
            
            return balance
            
        except Exception as e:
            logger.error(f"Failed to get real-time balance for {account_id}: {e}")
            return self._realtime_balances.get(account_id)
    
    def subscribe_to_price_feed(self, symbol: str) -> Optional[float]:
        """
        Get current price for symbol
        
        Args:
            symbol: Trading symbol
        
        Returns:
            Current price or None
        """
        try:
            key = f"wma:price:{symbol}"
            price_data = self.redis.get(key)
            
            if not price_data:
                return None
            
            price_info = json.loads(price_data)
            return price_info.get('price')
            
        except Exception as e:
            logger.error(f"Failed to get price for {symbol}: {e}")
            return None
    
    def track_trade_execution(self, signal_id: str, account_id: str) -> Optional[Dict[str, Any]]:
        """
        Track execution of a signal
        
        Args:
            signal_id: Signal identifier
            account_id: Account identifier
        
        Returns:
            Execution status or None
        """
        try:
            # Check for fills related to this signal
            pattern = f"wma:{account_id}:fills:*"
            keys = self.redis.keys(pattern)
            
            for key in keys:
                try:
                    fill_data = self.redis.get(key)
                    if fill_data:
                        fill = json.loads(fill_data)
                        # Match fill to signal (simplified - could use signal_id in fill data)
                        if fill.get('timestamp', 0) > self._signal_execution_map.get(signal_id, {}).get('timestamp', 0):
                            return {
                                'status': 'filled',
                                'fill': fill,
                                'account_id': account_id
                            }
                except Exception as e:
                    logger.error(f"Error reading fill from {key}: {e}")
            
            return {'status': 'pending', 'account_id': account_id}
            
        except Exception as e:
            logger.error(f"Failed to track execution for signal {signal_id}: {e}")
            return None
    
    def calculate_execution_lag(self, signal_timestamp: float, execution_timestamp: float) -> float:
        """
        Calculate lag between signal generation and execution
        
        Args:
            signal_timestamp: When signal was generated
            execution_timestamp: When order was executed
        
        Returns:
            Lag in seconds
        """
        lag = execution_timestamp - signal_timestamp
        return lag
    
    def calculate_slippage(self, expected_price: float, actual_price: float, side: str) -> float:
        """
        Calculate slippage between expected and actual execution price
        
        Args:
            expected_price: Expected execution price
            actual_price: Actual execution price
            side: 'LONG' or 'SHORT'
        
        Returns:
            Slippage in percentage
        """
        if side == 'LONG':
            # For longs, higher actual price = negative slippage
            slippage = (actual_price - expected_price) / expected_price * 100
        else:
            # For shorts, lower actual price = negative slippage
            slippage = (expected_price - actual_price) / expected_price * 100
        
        return slippage
    
    def get_aggregated_state(self) -> Dict[str, Any]:
        """
        Get aggregated state from position reporter
        
        Returns:
            Aggregated state across all accounts
        """
        try:
            key = "wma:trainer:positions:all"
            state_data = self.redis.get(key)
            
            if not state_data:
                return None
            
            return json.loads(state_data)
            
        except Exception as e:
            logger.error(f"Failed to get aggregated state: {e}")
            return None
    
    def publish_enhanced_signal(self, signal: Dict[str, Any], account_id: str = "primary"):
        """
        Publish enhanced signal with all execution parameters
        
        Args:
            signal: Signal dictionary with decision and parameters
            account_id: Target account for execution
        
        Enhanced signal format:
        {
            'signal_id': 'uuid',
            'symbol': 'BTCUSDT',
            'action': 'OPEN_LONG' | 'OPEN_SHORT' | 'CLOSE' | 'HOLD',
            'leverage': 10,
            'position_size_pct': 0.1,
            'stop_loss': 42500.0,
            'take_profit': 45000.0,
            'confidence': 0.85,
            'reasoning': 'High momentum, low volatility',
            'market_regime': 'trending_bull',
            'risk_score': 0.3,
            'timestamp': 1696723200000,
            'trainer_state': {
                'current_balance': 10000.0,
                'open_positions': 2,
                'daily_pnl_pct': 0.023
            }
        }
        """
        try:
            # Add metadata
            signal['timestamp'] = time.time()
            signal['account_id'] = account_id
            
            # Add trainer state
            balance = self.get_real_time_balance(account_id)
            positions = self.get_all_real_time_positions(account_id)
            
            signal['trainer_state'] = {
                'current_balance': balance.get('balance', 0) if balance else 0,
                'open_positions': len([p for p in positions.values() if p.get('size', 0) > 0]),
                'unrealized_pnl': balance.get('unrealized_pnl', 0) if balance else 0
            }
            
            # Publish to account-specific stream
            stream_key = f"wma:signals:{account_id}"
            self.redis.xadd(
                stream_key,
                {'signal': json.dumps(signal)},
                maxlen=1000  # Keep last 1000 signals
            )
            
            # Track signal for execution monitoring
            signal_id = signal.get('signal_id', str(time.time()))
            self._signal_execution_map[signal_id] = {
                'signal': signal,
                'timestamp': time.time(),
                'account_id': account_id,
                'status': 'published'
            }
            
            logger.debug(f"📤 Published enhanced signal {signal_id} to {account_id}")
            
        except Exception as e:
            logger.error(f"Failed to publish enhanced signal: {e}")
    
    def get_execution_statistics(self, account_id: str = "primary") -> Dict[str, Any]:
        """
        Get execution statistics for an account
        
        Args:
            account_id: Account identifier
        
        Returns:
            Statistics dictionary
        """
        lag_times = self._execution_lag.get(account_id, [])
        
        stats = {
            'account_id': account_id,
            'last_position_update': self._last_position_update.get(account_id, 0),
            'last_balance_update': self._last_balance_update.get(account_id, 0),
            'average_execution_lag': sum(lag_times) / len(lag_times) if lag_times else 0,
            'max_execution_lag': max(lag_times) if lag_times else 0,
            'min_execution_lag': min(lag_times) if lag_times else 0,
            'total_fills': len(self._realtime_fills.get(account_id, [])),
            'open_positions': len([p for p in self._realtime_positions.get(account_id, {}).values() if p.get('size', 0) > 0])
        }
        
        return stats
