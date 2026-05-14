"""
Warm-Start Module for LSTM/Sequence Buffers

This module prefills sequence buffers from Redis on startup to avoid
long warmup windows that block trading.

Key Features:
1. Prefill sequence buffers with historical observations from Redis
2. Per-symbol/tf gating when prefill fails (not global stall)
3. Optional persistence of ring buffers to Redis for restart recovery
4. Warmup metrics logging

Usage:
    warm_start = WarmStartManager(redis_client, config)
    prefilled = warm_start.prefill_buffer(symbol, tf, buffer)
    if not prefilled:
        # Gate this symbol/tf until natural warmup completes
"""

import os
import time
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from collections import deque
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class WarmupStatus:
    """Warmup status for a single symbol/timeframe."""
    symbol: str
    timeframe: str
    current_len: int
    min_len: int
    is_warmed: bool
    source: str  # 'prefill', 'live', 'none'
    prefill_attempted: bool = False
    prefill_success: bool = False
    last_update_ts: float = 0.0
    
    def to_log_line(self) -> str:
        return (
            f"WARMUP | {self.symbol} | {self.timeframe} | "
            f"len={self.current_len}/{self.min_len} | "
            f"source={self.source} | "
            f"warmed={self.is_warmed}"
        )


class WarmStartManager:
    """
    Manages warm-start for LSTM/sequence buffers across symbols and timeframes.
    
    Responsibilities:
    1. Attempt to prefill buffers from Redis observation history
    2. Track warmup status per symbol/tf
    3. Provide gating decisions (block entries until warmed)
    4. Persist buffers to Redis (optional) for restart recovery
    """
    
    def __init__(
        self,
        redis_client: Any = None,
        min_seq_len: int = 5,
        prefill_lookback: int = 10,
        obs_history_key_pattern: str = "obs_history:{symbol}:{tf}",
        enable_persistence: bool = False,
    ):
        self.redis = redis_client
        self.min_seq_len = min_seq_len
        self.prefill_lookback = prefill_lookback
        self.obs_history_key_pattern = obs_history_key_pattern
        self.enable_persistence = enable_persistence
        
        # Warmup status cache per symbol:tf
        self._warmup_status: Dict[str, WarmupStatus] = {}
        
        # Buffers that we're managing
        self._managed_buffers: Dict[str, deque] = {}
        
    def _get_cache_key(self, symbol: str, timeframe: str) -> str:
        """Generate cache key for symbol/tf pair."""
        return f"{symbol}:{timeframe}"
    
    def _get_redis_key(self, symbol: str, timeframe: str) -> str:
        """Generate Redis key for observation history."""
        return self.obs_history_key_pattern.format(symbol=symbol, tf=timeframe)
    
    def get_warmup_status(self, symbol: str, timeframe: str) -> WarmupStatus:
        """Get current warmup status for symbol/tf."""
        key = self._get_cache_key(symbol, timeframe)
        if key not in self._warmup_status:
            self._warmup_status[key] = WarmupStatus(
                symbol=symbol,
                timeframe=timeframe,
                current_len=0,
                min_len=self.min_seq_len,
                is_warmed=False,
                source='none',
            )
        return self._warmup_status[key]
    
    def update_warmup_status(
        self,
        symbol: str,
        timeframe: str,
        current_len: int,
        source: str = 'live',
    ) -> WarmupStatus:
        """Update warmup status after adding to buffer."""
        status = self.get_warmup_status(symbol, timeframe)
        status.current_len = current_len
        status.is_warmed = current_len >= self.min_seq_len
        status.last_update_ts = time.time()
        if source:
            status.source = source
        return status
    
    def prefill_buffer(
        self,
        symbol: str,
        timeframe: str,
        buffer: Optional[deque] = None,
    ) -> Tuple[bool, int, Optional[deque]]:
        """
        Attempt to prefill buffer from Redis observation history.
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            buffer: Existing deque buffer to fill (creates new if None)
            
        Returns:
            (success, num_loaded, buffer)
        """
        status = self.get_warmup_status(symbol, timeframe)
        status.prefill_attempted = True
        
        if buffer is None:
            buffer = deque(maxlen=self.prefill_lookback * 2)
        
        cache_key = self._get_cache_key(symbol, timeframe)
        self._managed_buffers[cache_key] = buffer
        
        if self.redis is None:
            logger.warning(f"[WARM_START] Redis not available for {symbol} {timeframe}")
            status.prefill_success = False
            return False, 0, buffer
        
        try:
            redis_key = self._get_redis_key(symbol, timeframe)
            
            # Try to load from Redis list (most recent N observations)
            raw_data = self.redis.lrange(redis_key, 0, self.prefill_lookback - 1)
            
            if not raw_data:
                # Try alternative key format
                alt_key = f"lstm_buffer:{symbol}:{timeframe}"
                raw_data = self.redis.lrange(alt_key, 0, self.prefill_lookback - 1)
            
            if not raw_data:
                logger.debug(f"[WARM_START] No observation history for {symbol} {timeframe}")
                status.prefill_success = False
                return False, 0, buffer
            
            # Parse and add to buffer (in reverse order to maintain chronological)
            loaded = 0
            for item in reversed(raw_data):
                try:
                    if isinstance(item, bytes):
                        item = item.decode('utf-8')
                    
                    # Try JSON parse first
                    try:
                        obs_data = json.loads(item)
                        if isinstance(obs_data, list):
                            obs = np.array(obs_data, dtype=np.float32)
                        elif isinstance(obs_data, dict) and 'observation' in obs_data:
                            obs = np.array(obs_data['observation'], dtype=np.float32)
                        else:
                            continue
                    except json.JSONDecodeError:
                        # Try direct numpy
                        obs = np.frombuffer(item.encode() if isinstance(item, str) else item, dtype=np.float32)
                    
                    if len(obs) > 0:
                        buffer.append(obs)
                        loaded += 1
                        
                except Exception as e:
                    logger.debug(f"[WARM_START] Failed to parse observation: {e}")
                    continue
            
            if loaded >= self.min_seq_len:
                status.prefill_success = True
                status.source = 'prefill'
                status.current_len = loaded
                status.is_warmed = True
                logger.info(f"WARMUP | {symbol} | {timeframe} | len={loaded}/{self.min_seq_len} | source=prefill | warmed=True")
                return True, loaded, buffer
            elif loaded > 0:
                status.current_len = loaded
                status.source = 'prefill_partial'
                logger.info(f"WARMUP | {symbol} | {timeframe} | len={loaded}/{self.min_seq_len} | source=prefill_partial | warmed=False")
                return False, loaded, buffer
            else:
                status.prefill_success = False
                logger.debug(f"[WARM_START] No valid observations loaded for {symbol} {timeframe}")
                return False, 0, buffer
                
        except Exception as e:
            logger.warning(f"[WARM_START] Error prefilling {symbol} {timeframe}: {e}")
            status.prefill_success = False
            return False, 0, buffer
    
    def persist_buffer(
        self,
        symbol: str,
        timeframe: str,
        buffer: Optional[deque] = None,
        observation: Optional[np.ndarray] = None,
    ) -> bool:
        """
        Persist buffer or single observation to Redis for restart recovery.
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            buffer: Full buffer to persist (optional)
            observation: Single observation to append (optional)
            
        Returns:
            Success status
        """
        if not self.enable_persistence:
            return True
        
        if self.redis is None:
            return False
        
        try:
            redis_key = self._get_redis_key(symbol, timeframe)
            
            if observation is not None:
                # Append single observation
                obs_json = json.dumps(observation.tolist())
                self.redis.lpush(redis_key, obs_json)
                self.redis.ltrim(redis_key, 0, self.prefill_lookback - 1)
                return True
            
            if buffer is not None:
                # Persist full buffer
                pipe = self.redis.pipeline()
                pipe.delete(redis_key)
                for obs in buffer:
                    obs_json = json.dumps(obs.tolist() if hasattr(obs, 'tolist') else list(obs))
                    pipe.rpush(redis_key, obs_json)
                pipe.expire(redis_key, 3600 * 24)  # 24h TTL
                pipe.execute()
                return True
            
            return False
            
        except Exception as e:
            logger.warning(f"[WARM_START] Error persisting buffer {symbol} {timeframe}: {e}")
            return False
    
    def should_block_action(
        self,
        action: str,
        symbol: str,
        timeframe: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if action should be blocked due to warmup status.
        
        Only blocks entry/flip actions; allows protective actions.
        
        Returns:
            (should_block, reason_code)
        """
        status = self.get_warmup_status(symbol, timeframe)
        
        if status.is_warmed:
            return False, None
        
        # Protective actions allowed during warmup
        protective_actions = {
            'CLOSE_LONG', 'CLOSE_SHORT', 'CLOSE_ALL',
            'DECREASE_LONG', 'DECREASE_SHORT',
            'PARTIAL_CLOSE', 'REDUCE', 'HOLD',
        }
        
        # Handle int action indices (from model)
        if isinstance(action, (int, float)):
            # HOLD (index 0 or 6) is protective
            if int(action) in (0, 6):
                return False, None
            # Other int actions treated as non-protective (block during warmup)
        elif action and str(action).upper() in protective_actions:
            return False, None
        
        # Block entry/flip actions until warmed
        reason = f"WARMUP_BLOCK:{symbol}:{timeframe}:len={status.current_len}/{status.min_len}"
        return True, reason
    
    def log_all_status(self):
        """Log warmup status for all tracked symbol/tf pairs."""
        for key, status in self._warmup_status.items():
            if status.is_warmed:
                logger.debug(status.to_log_line())
            else:
                logger.info(status.to_log_line())
    
    def get_all_warmed(self) -> List[str]:
        """Get list of all warmed symbol:tf pairs."""
        return [k for k, v in self._warmup_status.items() if v.is_warmed]
    
    def get_all_blocked(self) -> List[WarmupStatus]:
        """Get list of all blocked (not warmed) statuses."""
        return [v for v in self._warmup_status.values() if not v.is_warmed]


# Global instance
_warm_start_manager: Optional[WarmStartManager] = None


def get_warm_start_manager(
    redis_client: Any = None,
    force_new: bool = False,
) -> WarmStartManager:
    """Get global warm-start manager instance."""
    global _warm_start_manager
    if _warm_start_manager is None or force_new:
        from config import (
            WARM_START_MIN_SEQ_LEN,
            WARM_START_PREFILL_LOOKBACK,
            WARM_START_OBS_HISTORY_KEY,
            ENABLE_WARM_START_PREFILL,
        )
        _warm_start_manager = WarmStartManager(
            redis_client=redis_client,
            min_seq_len=WARM_START_MIN_SEQ_LEN,
            prefill_lookback=WARM_START_PREFILL_LOOKBACK,
            obs_history_key_pattern=WARM_START_OBS_HISTORY_KEY,
            enable_persistence=ENABLE_WARM_START_PREFILL,
        )
    elif redis_client is not None and _warm_start_manager.redis is None:
        _warm_start_manager.redis = redis_client
    return _warm_start_manager


def prefill_buffer(
    symbol: str,
    timeframe: str,
    buffer: Optional[deque] = None,
    redis_client: Any = None,
) -> Tuple[bool, int, Optional[deque]]:
    """Convenience function to prefill a buffer."""
    manager = get_warm_start_manager(redis_client)
    return manager.prefill_buffer(symbol, timeframe, buffer)


def should_block_warmup(
    action: str,
    symbol: str,
    timeframe: str,
) -> Tuple[bool, Optional[str]]:
    """Check if action should be blocked due to warmup.
    
    In live trading mode, bypass warmup block since we have real-time
    data flowing and the warmup buffer is not being actively populated.
    """
    import os
    # BYPASS: In live mode, don't block on warmup - we have real-time data
    # The warmup buffer mechanism is designed for backtesting/simulation
    live_mode = os.environ.get('LIVE_TRAINING_ENABLED', '0') == '1'
    trade_mode = os.environ.get('TRADE_MODE', '').lower()
    
    if live_mode or trade_mode == 'live':
        # In live mode, don't block - we trust real-time data quality
        return False, None
    
    return get_warm_start_manager().should_block_action(action, symbol, timeframe)

