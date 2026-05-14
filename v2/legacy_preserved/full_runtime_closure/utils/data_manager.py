import json
import os
import time
from pathlib import Path
from typing import Optional, Any

class DataManager:
    """
    Data manager for handling Redis operations with the WMA bot data
    """
    
    def __init__(self, data_dir=None, redis_client=None):
        # File operations
        if data_dir:
            self.data_dir = Path(data_dir)
            self.data_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.data_dir = None
            
        # Redis operations
        if redis_client is None:
            from utils.redis_client import get_redis
            self.redis = get_redis()
        else:
            self.redis = redis_client
    
    def store_price_data(self, symbol: str, timeframe: str, data: dict):
        """Store price/candle data"""
        key = f"price:{symbol}:{timeframe}"
        self.redis.hset(key, mapping=data)
        self.redis.expire(key, 86400)  # 24 hours
    
    def store_orderbook_data(self, symbol: str, data: dict):
        """Store order book data"""
        key = f"orderbook:{symbol}"
        self.redis.hset(key, mapping=data)
        self.redis.expire(key, 300)  # 5 minutes
    
    def store_liquidation_data(self, symbol: str, data: dict):
        """Store liquidation data"""
        key = f"liquidations:{symbol}"
        self.redis.lpush(key, json.dumps(data))
        self.redis.ltrim(key, 0, 999)  # Keep last 1000 entries
        self.redis.expire(key, 3600)  # 1 hour
    
    def store_news_data(self, source: str, data: dict):
        """Store news data"""
        key = f"news:{source}"
        self.redis.lpush(key, json.dumps(data))
        self.redis.ltrim(key, 0, 99)  # Keep last 100 entries
        self.redis.expire(key, 86400)  # 24 hours
    
    def get_latest_price(self, symbol: str, timeframe: str = '1m'):
        """Get latest price data"""
        key = f"price:{symbol}:{timeframe}"
        return self.redis.hgetall(key)
    
    def get_orderbook(self, symbol: str):
        """Get latest orderbook"""
        key = f"orderbook:{symbol}"
        return self.redis.hgetall(key)
    
    def store_generic(self, key: str, data: dict, expire_seconds: int = 3600):
        """Store generic data with expiration"""
        if isinstance(data, dict):
            self.redis.hset(key, mapping=data)
        else:
            self.redis.set(key, json.dumps(data))
        self.redis.expire(key, expire_seconds)
    
    def heartbeat(self, component: str):
        """Update heartbeat for a component"""
        key = f"heartbeat:{component}"
        self.redis.set(key, str(int(time.time())))
        self.redis.expire(key, 120)  # 2 minutes
        
    def append_live_bar(self, symbol: str, timeframe: str, bar_data: dict):
        """Append OHLCV bar data to live data files"""
        if not self.data_dir:
            return
            
        filename = f"{symbol}_{timeframe}.jsonl"
        filepath = self.data_dir / filename
        
        try:
            # Ensure the bar data has required fields
            required_fields = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
            if not all(field in bar_data for field in required_fields):
                print(f"Warning: Missing required fields in bar data for {symbol} {timeframe}")
                return
                
            # Append to JSONL file
            with open(filepath, 'a', encoding='utf-8') as f:
                f.write(json.dumps(bar_data) + '\n')
                
        except Exception as e:
            print(f"Error writing to {filepath}: {e}")
