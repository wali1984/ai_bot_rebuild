#!/usr/bin/env python3
"""
OHLCV Resampler Hotfix - Sidecar Service
=========================================

Purpose: Ensures unified_features:{symbol}:{tf} always has fresh OHLCV + ts_ms
         for higher timeframes (5m/15m/1h/4h) by reading from market:{symbol}:{tf}

Why: Unblocks trainer from skipping higher TFs due to missing/stale OHLCV data
     while the slow-lane pipeline issue is being root-caused.

Design:
  - Reads market:{symbol}:{tf} JSON (already populated by live_binance)
  - Writes only 6 fields to unified_features:{symbol}:{tf}:
    open, high, low, close, volume, ts_ms
  - Does NOT touch indicator fields (leaves them intact)
  - Runs every 10-15 seconds in a loop
  - Safe to run alongside feature_pipeline

Author: AI Trading Bot Team
Date: 2024-10-11
"""

import redis
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'logs/ohlcv_resampler_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)

logger = logging.getLogger(__name__)

# Configuration
DEFAULT_SYMBOLS = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'DOGEUSDT',
    'LINKUSDT', 'UNIUSDT', 'LTCUSDT'
]
DEFAULT_TIMEFRAMES = ['5m', '15m', '1h', '4h']  # Skip 1m (fast lane handles it)

SYMBOLS = DEFAULT_SYMBOLS
TIMEFRAMES = DEFAULT_TIMEFRAMES

# Prefer config.py so the resampler stays aligned with the live trading universe.
try:
    import config as _config
    SYMBOLS = list(getattr(_config, "SYMBOLS", SYMBOLS))
    cfg_tfs = list(getattr(_config, "TIMEFRAMES", []))
    if cfg_tfs:
        TIMEFRAMES = [tf for tf in cfg_tfs if tf in set(DEFAULT_TIMEFRAMES)]
except Exception as _e:
    logger.warning(f"Falling back to default SYMBOLS/TIMEFRAMES (config import failed): {_e}")

REDIS_HOST = 'localhost'
REDIS_PORT = 6379
REDIS_DB = 0

UPDATE_INTERVAL = 12  # seconds

class OHLCVResampler:
    """
    Lightweight sidecar that ensures OHLCV freshness for higher timeframes
    """
    
    def __init__(self):
        self.redis = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True
        )
        self.running = True
        self.cycle_count = 0
        
        logger.info("=" * 80)
        logger.info("🔄 OHLCV RESAMPLER HOTFIX - Starting")
        logger.info("=" * 80)
        logger.info(f"Symbols: {len(SYMBOLS)}")
        logger.info(f"Timeframes: {TIMEFRAMES}")
        logger.info(f"Total combinations: {len(SYMBOLS) * len(TIMEFRAMES)}")
        logger.info(f"Update interval: {UPDATE_INTERVAL}s")
        logger.info("=" * 80)
    
    def extract_ohlcv(self, market_data: Dict) -> Optional[Dict[str, str]]:
        """
        Extract OHLCV + timestamp from market data JSON
        
        Returns: Dict with 6 fields as strings, or None if invalid
        """
        try:
            # Validate required fields exist
            required_fields = ['open', 'high', 'low', 'close', 'volume', 'timestamp']
            if not all(field in market_data for field in required_fields):
                return None
            
            # Extract and convert to strings (Redis hash values must be strings)
            ohlcv = {
                'open': str(market_data['open']),
                'high': str(market_data['high']),
                'low': str(market_data['low']),
                'close': str(market_data['close']),
                'volume': str(market_data['volume']),
                'ts_ms': str(market_data['timestamp'])  # Already in milliseconds
            }
            
            return ohlcv
            
        except Exception as e:
            logger.warning(f"Failed to extract OHLCV: {e}")
            return None
    
    def process_combination(self, symbol: str, tf: str) -> bool:
        """
        Process one symbol/timeframe combination
        
        Returns: True if successfully updated, False otherwise
        """
        try:
            # Read source data
            market_key = f"market:{symbol}:{tf}"
            market_json = self.redis.get(market_key)
            
            if not market_json:
                logger.debug(f"⚠️  {symbol}/{tf}: No market data")
                return False
            
            # Parse JSON
            market_data = json.loads(market_json)
            
            # Extract OHLCV fields
            ohlcv = self.extract_ohlcv(market_data)
            if not ohlcv:
                logger.debug(f"⚠️  {symbol}/{tf}: Invalid market data structure")
                return False
            
            # Write to unified_features (only these 6 fields)
            unified_key = f"unified_features:{symbol}:{tf}"
            self.redis.hset(unified_key, mapping=ohlcv)
            
            # Set expiry based on timeframe
            expiry_map = {'5m': 600, '15m': 1800, '1h': 7200, '4h': 28800}
            expiry = expiry_map.get(tf, 3600)
            self.redis.expire(unified_key, expiry)
            
            return True
            
        except json.JSONDecodeError as e:
            logger.warning(f"❌ {symbol}/{tf}: Invalid JSON - {e}")
            return False
        except redis.exceptions.RedisError as e:
            logger.error(f"❌ {symbol}/{tf}: Redis error - {e}")
            return False
        except Exception as e:
            logger.error(f"❌ {symbol}/{tf}: Unexpected error - {e}")
            return False
    
    def run_cycle(self) -> Tuple[int, int]:
        """
        Run one update cycle for all combinations
        
        Returns: (success_count, total_count)
        """
        self.cycle_count += 1
        start_time = time.time()
        
        success_count = 0
        total_count = 0
        
        for symbol in SYMBOLS:
            for tf in TIMEFRAMES:
                total_count += 1
                if self.process_combination(symbol, tf):
                    success_count += 1
        
        duration = time.time() - start_time
        
        # Update heartbeat
        try:
            now_ms = int(time.time() * 1000)
            self.redis.set('features:resampler:last_run_ms', now_ms)
            if success_count == total_count:
                self.redis.set('features:resampler:last_success_ms', now_ms)
        except Exception as e:
            logger.warning(f"Failed to update heartbeat: {e}")
        
        return success_count, total_count, duration
    
    def run(self):
        """
        Main loop - runs continuously until stopped
        """
        logger.info("🚀 Resampler loop started")
        
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 10
        
        while self.running:
            try:
                success, total, duration = self.run_cycle()
                
                if success == total:
                    logger.info(f"✅ Cycle #{self.cycle_count}: {success}/{total} updated in {duration:.2f}s")
                    consecutive_errors = 0
                else:
                    logger.warning(f"⚠️  Cycle #{self.cycle_count}: {success}/{total} updated in {duration:.2f}s")
                    consecutive_errors += 1
                
                # Check error threshold
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.critical(f"❌ {MAX_CONSECUTIVE_ERRORS} consecutive partial failures! Exiting...")
                    self.running = False
                    break
                
                # Sleep until next cycle
                time.sleep(UPDATE_INTERVAL)
                
            except KeyboardInterrupt:
                logger.info("🛑 Keyboard interrupt received")
                self.running = False
                break
            except Exception as e:
                logger.error(f"❌ Cycle error: {e}", exc_info=True)
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.critical("❌ Too many errors! Exiting...")
                    self.running = False
                    break
                time.sleep(5)  # Back off on errors
        
        logger.info(f"🛑 Resampler stopped after {self.cycle_count} cycles")


def main():
    """Entry point"""
    logger.info("Starting OHLCV Resampler Hotfix...")
    
    resampler = OHLCVResampler()
    
    try:
        resampler.run()
    except Exception as e:
        logger.critical(f"Fatal error: {e}", exc_info=True)
        return 1
    
    return 0


if __name__ == '__main__':
    exit(main())
