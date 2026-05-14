"""
WMA AI Bot Trading Environment
Reinforcement Learning environment for crypto trading
"""
import json
import time
import redis  # For exception handling
import numpy as np
import threading
import multiprocessing
import hashlib
import os
from typing import Dict, List, Tuple, Any, Optional
import torch
import torch.nn as nn

# Add project root to path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Dynamic symbol loading - supports hot-reload without restart
try:
    from utils.symbol_manager import get_symbols_cached
    SYMBOLS = get_symbols_cached()
except ImportError:
    from config import SYMBOLS

from utils.redis_client import get_redis
from utils.logger import get_logger
from utils.data_manager import DataManager

# Import Phase 1A reward config + fee config
try:
    from config import (
        USE_RISK_ADJUSTED_REWARD,
        TRADE_PENALTY,
        DRAWDOWN_PENALTY,
        PNL_SCALE,
        EQUITY_CURVE_WINDOW,
        # Cost-aware reward shaping (design: reward = net_pnl - K*(fees+slippage_proxy))
        MIN_EDGE_MULTIPLE,
        # Fee awareness - use real Binance fee rates
        TAKER_FEE_PCT,
        ROUND_TRIP_FEE_PCT,
        # Persistent penalties (no-loss learning mode)
        TRAIN_PERSISTENT_PENALTIES_ENABLED,
        TRAIN_EQUITY_BELOW_BASELINE_PENALTY_K,
        TRAIN_NEG_LEG_PENALTY_K,
    )
    # Convert percentage to decimal (0.05% -> 0.0005)
    DEFAULT_TRANSACTION_COST = TAKER_FEE_PCT / 100  # Taker fee as decimal
    # Use the same K-multiplier as the edge gate (can be tuned via MIN_EDGE_MULTIPLE env).
    FEE_PENALTY_MULTIPLIER = max(1.0, float(MIN_EDGE_MULTIPLE))
except ImportError:
    # Fallback if config not updated yet
    USE_RISK_ADJUSTED_REWARD = False
    TRADE_PENALTY = 0.002
    DRAWDOWN_PENALTY = 0.1
    PNL_SCALE = 100.0
    EQUITY_CURVE_WINDOW = 1000
    DEFAULT_TRANSACTION_COST = 0.0005  # Legacy 0.05% default
    FEE_PENALTY_MULTIPLIER = 1.0
    TRAIN_PERSISTENT_PENALTIES_ENABLED = False
    TRAIN_EQUITY_BELOW_BASELINE_PENALTY_K = 0.0
    TRAIN_NEG_LEG_PENALTY_K = 0.0

# Import fee ratio reward shaping for training
try:
    from rl.fee_ratio_reward_shaping import (
        FeeRatioRewardShaper, 
        get_fee_ratio_features,
        FEE_RATIO_REWARD_SHAPING_ENABLED
    )
    FEE_RATIO_SHAPING_AVAILABLE = True
except ImportError:
    FEE_RATIO_SHAPING_AVAILABLE = False
    FEE_RATIO_REWARD_SHAPING_ENABLED = False

logger = get_logger("trading_environment")


class FeatureSnapshotCache:
    """
    Shared feature cache to eliminate per-step Redis calls in SubprocVecEnv workers.
    Uses pull-once-share-many pattern for multi-env performance.
    """
    
    def __init__(self, refresh_interval: float = 1.0, max_staleness: float = 5.0):
        self.refresh_interval = refresh_interval  # Pull from Redis every N seconds
        self.max_staleness = max_staleness       # Max age before features considered stale
        self.manager = multiprocessing.Manager()
        self.shared_features = self.manager.dict()
        self.shared_metadata = self.manager.dict()
        self.last_refresh = 0
        self.refresh_lock = threading.Lock()
        
        # Schema versioning for audit compliance
        self.schema_hash = self._calculate_schema_hash()
        logger.info(f"📊 [CACHE] Feature schema hash: {self.schema_hash[:8]}...")
    
    def _calculate_schema_hash(self) -> str:
        """Generate deterministic hash of feature schema for audit trail"""
        schema_data = {
            'symbols': sorted(SYMBOLS),
            'timeframes': ['1m', '5m', '15m', '1h', '4h', '1d'],
            'feature_types': ['rsi', 'sma', 'ema', 'bb_upper', 'bb_lower', 'volume', 'price', 'change', 'volatility'],
            'version': '1.0'
        }
        
        schema_str = json.dumps(schema_data, sort_keys=True)
        return hashlib.sha256(schema_str.encode()).hexdigest()
    
    def get_features(self, redis_client) -> Dict[str, float]:
        """Get features using snapshot cache to minimize Redis calls"""
        current_time = time.time()
        
        # Check if refresh needed
        if current_time - self.last_refresh > self.refresh_interval:
            with self.refresh_lock:
                if current_time - self.last_refresh > self.refresh_interval:
                    self._refresh_snapshot(redis_client, current_time)
        
        # Return cached features with staleness info
        if 'features' in self.shared_features and 'timestamp' in self.shared_metadata:
            age_seconds = current_time - self.shared_metadata['timestamp']
            is_stale = age_seconds > self.max_staleness
            
            features = dict(self.shared_features['features'])
            features.update({
                'is_stale': 1.0 if is_stale else 0.0,
                'age_ms': age_seconds * 1000,
                'schema_hash_match': 1.0
            })
            
            return features
        
        # Fallback if no cached data
        logger.warning("⚠️ [CACHE] No cached features available, using fallback")
        return self._get_fallback_features()
    
    def _refresh_snapshot(self, redis_client, current_time: float):
        """Refresh feature snapshot from Redis (called once per interval)"""
        try:
            unified_feature_keys = []
            for symbol in SYMBOLS[:5]:  # Limit for performance
                for tf in ['1m', '5m', '1h']:  # Key timeframes only
                    unified_feature_keys.append(f"unified_features:{symbol}:{tf}")
            
            pipeline = redis_client.pipeline()
            for key in unified_feature_keys:
                pipeline.exists(key)
                pipeline.hgetall(key)
            
            results = pipeline.execute()
            
            # Parse and store in shared memory
            parsed_features = {}
            for i in range(0, len(results), 2):
                exists = results[i]
                hash_data = results[i + 1] if i + 1 < len(results) else {}
                
                if exists and hash_data:
                    for field, value in hash_data.items():
                        if isinstance(field, bytes):
                            field = field.decode('utf-8')
                        if isinstance(value, bytes):
                            value = value.decode('utf-8')
                        try:
                            parsed_features[field] = float(value)
                        except (ValueError, TypeError):
                            continue
            
            # Update shared cache atomically
            self.shared_features['features'] = parsed_features
            self.shared_metadata.update({
                'timestamp': current_time,
                'feature_count': len(parsed_features),
                'schema_hash': self.schema_hash
            })
            
            self.last_refresh = current_time
            logger.debug(f"🔄 [CACHE] Refreshed {len(parsed_features)} features from Redis")
            
        except Exception as e:
            logger.error(f"❌ [CACHE] Failed to refresh snapshot: {e}")
    
    def _get_fallback_features(self) -> Dict[str, float]:
        """Generate fallback features when cache fails"""
        fallback_features = {}
        
        for symbol in SYMBOLS[:3]:
            for tf in ['1m', '5m', '1h']:
                base_key = f"{symbol}_{tf}"
                fallback_features.update({
                    f"{base_key}_rsi": 50.0,
                    f"{base_key}_sma": 100.0,
                    f"{base_key}_ema": 100.0,
                    f"{base_key}_bb_upper": 105.0,
                    f"{base_key}_bb_lower": 95.0,
                    f"{base_key}_volume": 1000.0,
                    f"{base_key}_price": 100.0,
                    'is_stale': 1.0,
                    'age_ms': 99999.0,
                    'schema_hash_match': 0.0
                })
        
        return fallback_features


class FeatureCache:
    """
    In-memory feature cache with timeframe-aware TTL
    Reduces Redis calls by caching recently fetched features
    """
    
    def __init__(self, enable_cache: bool = True):
        """
        Initialize feature cache
        
        Args:
            enable_cache: Whether to enable caching (can be toggled for A/B testing)
        """
        self.enabled = enable_cache
        self.cache = {}  # {key: value}
        self.timestamps = {}  # {key: timestamp}
        
        # TTL per timeframe (in seconds)
        # Lower timeframes need more frequent updates
        self.ttl_map = {
            '1m': 3,    # 3 seconds for 1-minute data
            '5m': 15,   # 15 seconds for 5-minute data
            '15m': 45,  # 45 seconds for 15-minute data
            '1h': 60,   # 1 minute for hourly data
            '4h': 240,  # 4 minutes for 4-hour data
            '1d': 600,  # 10 minutes for daily data
        }
        
        self.hits = 0
        self.misses = 0
        self.total_requests = 0
        
        logger.info(f"FeatureCache initialized (enabled={self.enabled})")
    
    def get_ttl(self, key: str) -> int:
        """
        Determine TTL based on key pattern
        Extracts timeframe from key like 'unified_features:BTCUSDT:5m'
        """
        for tf in self.ttl_map.keys():
            if f':{tf}' in key or f'_{tf}' in key:
                return self.ttl_map[tf]
        return 5  # Default 5 seconds for unknown keys
    
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache if valid, otherwise return None
        
        Returns:
            Cached value if valid, None if expired or not found
        """
        if not self.enabled:
            return None
        
        self.total_requests += 1
        
        if key in self.cache:
            age = time.time() - self.timestamps[key]
            ttl = self.get_ttl(key)
            
            if age < ttl:
                self.hits += 1
                return self.cache[key]
            else:
                # Expired - remove from cache
                del self.cache[key]
                del self.timestamps[key]
        
        self.misses += 1
        return None
    
    def set(self, key: str, value: Any):
        """
        Store value in cache with timestamp
        """
        if not self.enabled:
            return
        
        self.cache[key] = value
        self.timestamps[key] = time.time()
    
    def get_hit_rate(self) -> float:
        """
        Calculate cache hit rate percentage
        """
        if self.total_requests == 0:
            return 0.0
        return (self.hits / self.total_requests) * 100
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics
        """
        return {
            'enabled': self.enabled,
            'total_requests': self.total_requests,
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': self.get_hit_rate(),
            'cache_size': len(self.cache)
        }
    
    def clear(self):
        """
        Clear all cached data
        """
        self.cache.clear()
        self.timestamps.clear()
        logger.info("Feature cache cleared")


class TradingEnvironment:
    """
    Trading environment for RL agent
    """
    
    def __init__(self, 
                 initial_balance: float = 10000.0,
                 transaction_cost: float = None,  # None = use config TAKER_FEE_PCT
                 max_position: float = 1.0,
                 lookback_window: int = 10,
                 enable_feature_cache: bool = True,
                 min_hold_steps: int = 20,
                 trade_value_pct: float = 0.05,
                 trade_penalty_scale: float = 0.25):
        """
        Initialize trading environment
        
        Args:
            initial_balance: Starting portfolio value in USD
            transaction_cost: Trading fee as decimal (0.0005 = 0.05%). 
                             If None, uses TAKER_FEE_PCT from config
            max_position: Maximum position size as fraction of balance
            lookback_window: Number of past states to include in observation
            enable_feature_cache: Enable in-memory feature caching (reduces Redis load)
        """
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        # Fee awareness: use config value if not explicitly provided
        self.transaction_cost = transaction_cost if transaction_cost is not None else DEFAULT_TRANSACTION_COST
        self.max_position = max_position
        self.lookback_window = lookback_window
        self.min_hold_steps = min_hold_steps
        self.trade_value_pct = trade_value_pct
        self.trade_penalty = TRADE_PENALTY * trade_penalty_scale
        
        # FEE TRACKING: Track cumulative fees per episode and per symbol
        self.cumulative_fees = 0.0  # Total fees paid this episode
        self.fees_by_symbol = {symbol: 0.0 for symbol in SYMBOLS}  # Per-symbol fee tracking
        # Track last entry fee per symbol so we can score "trade cycles" net-after-fees.
        self.entry_fees_by_symbol = {symbol: 0.0 for symbol in SYMBOLS}
        self.trade_count = 0  # Number of trades this episode
        # Closed trades captured in the most recent step (for terminal bonus shaping).
        self._closed_trades_last_step: List[Dict[str, Any]] = []
        
        # Current positions
        self.positions = {symbol: 0.0 for symbol in SYMBOLS}  # Position sizes for ALL 10 symbols
        self.entry_prices = {symbol: 0.0 for symbol in SYMBOLS}  # Entry prices for ALL 10 symbols
        self.position_open_times = {symbol: 0 for symbol in SYMBOLS}  # Step count when position opened (Phase 4)
        
        # State tracking
        self.current_prices = {symbol: 0.0 for symbol in SYMBOLS}
        self.price_history = []  # Store recent price/feature history
        self.step_count = 0
        self.episode_start_balance = initial_balance
        
        # Redis: Store CONFIG (picklable), create client LAZILY per-process
        # This allows proper SubprocVecEnv spawning without pickle errors
        self.redis = None  # Created lazily in _ensure_redis()
        self.data_manager = None  # Created lazily with Redis
        try:
            from utils.redis_client import get_redis_config
            self._redis_cfg = get_redis_config()  # Picklable config dict
        except Exception:
            self._redis_cfg = None
        
        # 🔥 NEW: Feature cache for reduced Redis load
        self.feature_cache = FeatureCache(enable_cache=enable_feature_cache)
        
        # 🔥 NEW: Feature snapshot cache for multi-env performance
        self.feature_snapshot_cache = FeatureSnapshotCache(
            refresh_interval=1.0,  # Pull from Redis every 1 second
            max_staleness=5.0      # Consider stale after 5 seconds
        )
        
        # Initialize cache variables for non-blocking Redis access
        self._last_good_features = None
        self._last_good_ts = 0
        
        # 🔥 NEW: Required feature counts by source (for data completeness validation)
        self.required_sources = {
            'coinank': 115,      # Funding rates, OI, liquidations, long/short ratio, etc.
            'tokenmetrics': 122, # TM grades, tech/fund scores, AI signals, moonshots, etc.
            'talib': 920,        # 46 indicators × 10 symbols × 2 timeframes (estimated)
            'ccxt': 86           # OHLCV, order book, volume metrics
        }
        
        # Track missing data for logging
        self.missing_data_warnings = {}  # {source: count}
        self.last_validation_time = 0
        self.validation_interval = 60  # Validate every 60 seconds
        
        # Action space: 0=hold, 1=buy, 2=sell for each symbol
        self.action_space_size = 3 ** len(SYMBOLS)  # 3^10 = 59,049 possible actions
        self.n_symbols = len(SYMBOLS)
        
        logger.info(f"Trading environment initialized with {self.n_symbols} symbols (cache_enabled={enable_feature_cache})")
    
    def __getstate__(self):
        """Prepare state for pickling (SubprocVecEnv spawn compatibility)"""
        state = self.__dict__.copy()
        # Remove unpicklable Redis client (will be recreated from _redis_cfg)
        state['redis'] = None
        state['data_manager'] = None
        return state
    
    def __setstate__(self, state):
        """Restore state after unpickling (in SubprocVecEnv worker)"""
        self.__dict__.update(state)
        # Redis will be created lazily in _ensure_redis() from _redis_cfg
    
    def _ensure_redis(self):
        """Ensure Redis connection is available (multiprocessing-safe)"""
        if getattr(self, 'redis', None) is None:
            try:
                if getattr(self, '_redis_cfg', None):
                    from utils.redis_client import create_redis_from_config
                    self.redis = create_redis_from_config(self._redis_cfg)
                    self.data_manager = DataManager(redis_client=self.redis)
                    logger.debug(f"🔄 Redis created from config in PID {os.getpid()}")
                else:
                    self.redis = get_redis()
                    if self.redis:
                        self.data_manager = DataManager(redis_client=self.redis)
            except Exception as e:
                logger.warning(f"⚠️ Redis connection failed: {e}")
                self.redis = None
                self.data_manager = None
        return self.redis
    
    def _validate_features(self, features: Dict[str, float]) -> bool:
        """
        Validate feature completeness by counting features from each source.
        Warns if any data source is incomplete.
        
        Expected sources:
        - Coinank: 115 features (funding, OI, liquidations, ratios)
        - TokenMetrics: 122 features (grades, signals, predictions)
        - TA-Lib: 920 features (46 indicators across symbols/timeframes)
        - CCXT: 86 features (OHLCV, order book, volume)
        
        Returns:
            True if all sources meet minimum thresholds (80% complete)
        """
        # Only validate periodically to avoid spam
        current_time = time.time()
        if current_time - self.last_validation_time < self.validation_interval:
            return True
        
        self.last_validation_time = current_time
        
        # Count features by source prefix
        source_counts = {
            'coinank': 0,
            'tokenmetrics': 0,
            'talib': 0,
            'ccxt': 0
        }
        
        for key in features.keys():
            key_lower = key.lower()
            if 'coinank' in key_lower or 'funding' in key_lower or 'liquidation' in key_lower or 'oi_' in key_lower:
                source_counts['coinank'] += 1
            elif 'tokenmetrics' in key_lower or 'tm_' in key_lower or 'tech_grade' in key_lower or 'fund_grade' in key_lower:
                source_counts['tokenmetrics'] += 1
            elif any(ind in key_lower for ind in ['sma', 'ema', 'rsi', 'macd', 'bbands', 'stoch', 'adx', 'atr', 'cci', 'willr']):
                source_counts['talib'] += 1
            elif 'ccxt' in key_lower or any(x in key_lower for x in ['ohlcv', 'open', 'high', 'low', 'close', 'volume', 'orderbook']):
                source_counts['ccxt'] += 1
        
        # Check completeness (80% threshold)
        all_complete = True
        missing_sources = []
        
        for source, count in source_counts.items():
            required = self.required_sources[source]
            completeness = (count / required * 100) if required > 0 else 0
            
            if completeness < 80:  # Less than 80% of expected features
                all_complete = False
                missing_sources.append(f"{source} ({count}/{required} = {completeness:.1f}%)")
                
                # Track warnings
                if source not in self.missing_data_warnings:
                    self.missing_data_warnings[source] = 0
                self.missing_data_warnings[source] += 1
        
        if not all_complete:
            logger.warning(
                f"⚠️ Incomplete feature data detected:\n"
                f"   Missing/incomplete sources: {', '.join(missing_sources)}\n"
                f"   Total features: {len(features)}\n"
                f"   Coinank: {source_counts['coinank']}/{self.required_sources['coinank']}\n"
                f"   TokenMetrics: {source_counts['tokenmetrics']}/{self.required_sources['tokenmetrics']}\n"
                f"   TA-Lib: {source_counts['talib']}/{self.required_sources['talib']}\n"
                f"   CCXT: {source_counts['ccxt']}/{self.required_sources['ccxt']}"
            )
        else:
            logger.info(
                f"✅ Feature completeness validation passed:\n"
                f"   Coinank: {source_counts['coinank']}/{self.required_sources['coinank']} ({source_counts['coinank']/self.required_sources['coinank']*100:.1f}%)\n"
                f"   TokenMetrics: {source_counts['tokenmetrics']}/{self.required_sources['tokenmetrics']} ({source_counts['tokenmetrics']/self.required_sources['tokenmetrics']*100:.1f}%)\n"
                f"   TA-Lib: {source_counts['talib']}/{self.required_sources['talib']} ({source_counts['talib']/self.required_sources['talib']*100:.1f}%)\n"
                f"   CCXT: {source_counts['ccxt']}/{self.required_sources['ccxt']} ({source_counts['ccxt']/self.required_sources['ccxt']*100:.1f}%)"
            )
        
        return all_complete
    
    def get_current_features(self) -> Dict[str, float]:
        """
        Get current market features with hard time budget - NEVER blocks.
        Returns stale features on any Redis timeout/error to prevent worker hangs.
        """
        import time

        t0 = time.monotonic()

        # If debugging or no redis available, return deterministic fallback
        if self.debug_mode or self.redis is None:
            return self._get_fallback_features()

        try:
            # Hard time budget per step - never exceed this
            time_budget = 0.75  # seconds

            # Serve from cache if very fresh (<250ms)
            if hasattr(self, "_last_good_features") and hasattr(self, "_last_good_ts"):
                cache_age_ms = (time.time() * 1000) - self._last_good_ts
                if cache_age_ms < 250:
                    features = self._last_good_features.copy()
                    features.update({"is_stale": 0.0, "age_ms": cache_age_ms, "cache_hit": 1.0})
                    return features

            pipeline = self.redis.pipeline()
            for symbol in SYMBOLS[:3]:
                for tf in ["1m", "5m"]:
                    pipeline.hgetall(f"unified_features:{symbol}:{tf}")

            results = pipeline.execute()

            parsed_features = {}
            for hash_data in results:
                if not hash_data:
                    continue
                for field, value in hash_data.items():
                    if isinstance(field, bytes):
                        field = field.decode("utf-8")
                    if isinstance(value, bytes):
                        value = value.decode("utf-8")
                    try:
                        parsed_features[field] = float(value)
                    except (ValueError, TypeError):
                        continue

            elapsed = time.monotonic() - t0
            if elapsed > time_budget:
                raise TimeoutError(f"Feature fetch exceeded time budget: {elapsed:.3f}s")

            current_time_ms = time.time() * 1000
            self._last_good_features = parsed_features
            self._last_good_ts = current_time_ms

            parsed_features.update({
                "is_stale": 0.0,
                "age_ms": 0.0,
                "cache_hit": 0.0,
                "fetch_time_ms": elapsed * 1000,
            })

            return parsed_features

        except Exception as e:
            elapsed = time.monotonic() - t0
            if hasattr(self, "_last_good_features") and self._last_good_features:
                cache_age_ms = (time.time() * 1000) - getattr(self, "_last_good_ts", 0)
                features = self._last_good_features.copy()
                features.update({
                    "is_stale": 1.0,
                    "age_ms": cache_age_ms,
                    "error_type": type(e).__name__,
                    "fetch_time_ms": elapsed * 1000,
                })
                return features
            return self._get_fallback_features()

    def _get_fallback_features(self) -> Dict[str, float]:
        """
        Generate deterministic fallback features for debugging; bypass Redis entirely.
        """
        fallback_features = {}
        for symbol in SYMBOLS[:3]:
            for tf in ["1m", "5m", "1h"]:
                base_key = f"{symbol}_{tf}"
                fallback_features.update({
                    f"{base_key}_rsi": 50.0,
                    f"{base_key}_sma": 100.0,
                    f"{base_key}_ema": 100.0,
                    f"{base_key}_bb_upper": 105.0,
                    f"{base_key}_bb_lower": 95.0,
                    f"{base_key}_volume": 1000.0,
                    f"{base_key}_price": 100.0,
                    f"{base_key}_change": 0.5,
                    f"{base_key}_volatility": 2.0,
                })

        logger.debug(f"🔄 Generated {len(fallback_features)} fallback features for debugging")
        return fallback_features
    
    def _get_default_features(self) -> Dict[str, float]:
        """Get default features when data is unavailable"""
        features = {}
        for symbol in SYMBOLS:  # ALL 10 symbols
            # Price features for all timeframes
            for tf in ['1m', '5m', '15m', '1h', '4h', '1d']:
                features.update({
                    f"{symbol}_price_change_{tf}": 0.0,
                    f"{symbol}_volume_{tf}": 0.0,
                    f"{symbol}_volatility_{tf}": 0.0,
                })
            
            # Order book features
            features.update({
                f"{symbol}_ob_spread": 0.0,
                f"{symbol}_ob_imbalance": 0.0,
                f"{symbol}_ob_depth": 0.0,
                f"{symbol}_ob_bid_strength": 0.0,
                f"{symbol}_ob_ask_strength": 0.0,
            })
            
            # Liquidation features
            features.update({
                f"{symbol}_liquidations_long": 0.0,
                f"{symbol}_liquidations_short": 0.0,
            })
            
            # TokenMetrics features
            tm_features = [
                'tm_grades_FUNDAMENTAL_GRADE', 'tm_grades_TECHNICAL_GRADE', 'tm_grades_SOCIAL_GRADE',
                'tm_scores_OVERALL_SCORE', 'tm_scores_FUNDAMENTAL_SCORE', 'tm_scores_TECHNICAL_SCORE',
                'tm_scores_SOCIAL_SCORE', 'tm_momentum_MOMENTUM_SCORE', 'tm_momentum_PRICE_MOMENTUM',
                'tm_social_SOCIAL_VOLUME', 'tm_social_SOCIAL_SCORE', 'tm_volatility_VOLATILITY_SCORE',
                'tm_liquidity_LIQUIDITY_SCORE', 'tm_market_cap_MARKET_CAP', 'tm_volume_VOLUME_24H',
                'tm_price_PRICE_USD', 'tm_change_PRICE_CHANGE_24H', 'tm_sentiment_SENTIMENT_SCORE',
                'tm_network_NETWORK_ACTIVITY', 'tm_development_DEVELOPMENT_SCORE', 'tm_adoption_ADOPTION_SCORE',
                'tm_risk_RISK_SCORE', 'tm_correlation_CORRELATION_BTC', 'tm_whale_WHALE_ACTIVITY',
                'tm_technical_RSI', 'tm_technical_MACD'
            ]
            for tm_feature in tm_features:
                features[f"{symbol}_{tm_feature}"] = 0.0
            
            # CoinAnk features (comprehensive - matching extraction logic)
            # Series data
            coinank_series = [
                'coinank_oi', 'coinank_buyVol', 'coinank_sellVol', 'coinank_buysell_value', 
                'coinank_buysell_volume', 'coinank_funding', 'coinank_liq_breakdown'
            ]
            for ca_feature in coinank_series:
                features[f"{symbol}_{ca_feature}"] = 0.0
            
            # Liquidation data across timeframes
            liq_timeframes = ['1m', '5m', '15m', '30m', '1h', '4h', '8h', '1d']
            liq_metrics = ['buyLiq', 'sellLiq', 'totalLiq', 'liqRatio']
            for tf in liq_timeframes:
                for metric in liq_metrics:
                    features[f"{symbol}_coinank_liq_{tf}_{metric}"] = 0.0
            
            # Latest endpoint data
            coinank_endpoints = [
                'open_interest', 'funding', 'long_short', 'market_order_flow', 
                'indicators', 'liquidations', 'orderBook_v2_bySymbol'
            ]
            for endpoint in coinank_endpoints:
                for field_idx in range(5):
                    features[f"{symbol}_coinank_{endpoint}_field_{field_idx}"] = 0.0
            
            # Global and processed features
            global_features = [
                'coinank_fundingRate', 'coinank_netPositions', 'coinank_rsiMap', 
                'coinank_orderFlow', 'coinank_ls_exchange'
            ]
            for gf in global_features:
                features[f"{symbol}_{gf}"] = 0.0
            
            for feat_idx in range(10):
                features[f"{symbol}_coinank_features_feat_{feat_idx}"] = 0.0
            
            # Core features
            features.update({
                f"{symbol}_funding_rate": 0.0,
                f"{symbol}_coinank_long_short_ratio": 0.0,
                f"{symbol}_coinank_price": 0.0,
                f"{symbol}_coinank_volume": 0.0,
            })
                
        features['timestamp'] = str(int(time.time()))
        return features
    
    def get_state(self) -> np.ndarray:
        """
        Get current state representation for the RL agent
        
        Returns:
            State vector combining market features and portfolio state
        """
        # Get market features
        features = self.get_current_features()
        
        # Extract features for each symbol
        market_features = []
        for symbol in SYMBOLS:  # ALL 10 symbols
            symbol_features = []
            
            # Price features for ALL timeframes
            for tf in ['1m', '5m', '15m', '1h', '4h', '1d']:
                symbol_features.extend([
                    features.get(f"{symbol}_price_change_{tf}", 0.0),
                    features.get(f"{symbol}_volume_{tf}", 0.0) / 1e6,  # Normalize volume
                    features.get(f"{symbol}_volatility_{tf}", 0.0),
                ])
            
            # Order book features (extended)
            symbol_features.extend([
                features.get(f"{symbol}_ob_spread", 0.0) * 100,  # Convert to basis points
                features.get(f"{symbol}_ob_imbalance", 0.0),
                features.get(f"{symbol}_ob_depth", 0.0) / 1e6,  # Normalize depth
                features.get(f"{symbol}_ob_bid_strength", 0.0),
                features.get(f"{symbol}_ob_ask_strength", 0.0),
            ])
            
            # Liquidation features
            symbol_features.extend([
                features.get(f"{symbol}_liquidations_long", 0.0) / 1e6,
                features.get(f"{symbol}_liquidations_short", 0.0) / 1e6,
            ])
            
            # TokenMetrics features (comprehensive)
            tm_features = [
                'tm_grades_FUNDAMENTAL_GRADE', 'tm_grades_TECHNICAL_GRADE', 'tm_grades_SOCIAL_GRADE',
                'tm_scores_OVERALL_SCORE', 'tm_scores_FUNDAMENTAL_SCORE', 'tm_scores_TECHNICAL_SCORE',
                'tm_scores_SOCIAL_SCORE', 'tm_momentum_MOMENTUM_SCORE', 'tm_momentum_PRICE_MOMENTUM',
                'tm_social_SOCIAL_VOLUME', 'tm_social_SOCIAL_SCORE', 'tm_volatility_VOLATILITY_SCORE',
                'tm_liquidity_LIQUIDITY_SCORE', 'tm_market_cap_MARKET_CAP', 'tm_volume_VOLUME_24H',
                'tm_price_PRICE_USD', 'tm_change_PRICE_CHANGE_24H', 'tm_sentiment_SENTIMENT_SCORE',
                'tm_network_NETWORK_ACTIVITY', 'tm_development_DEVELOPMENT_SCORE', 'tm_adoption_ADOPTION_SCORE',
                'tm_risk_RISK_SCORE', 'tm_correlation_CORRELATION_BTC', 'tm_whale_WHALE_ACTIVITY',
                'tm_technical_RSI', 'tm_technical_MACD'
            ]
            for tm_feature in tm_features:
                symbol_features.append(features.get(f"{symbol}_{tm_feature}", 0.0) / 100.0)
            
            # CoinAnk features (comprehensive - all 42 endpoints)
            # Series data
            coinank_series = [
                'coinank_oi', 'coinank_buyVol', 'coinank_sellVol', 'coinank_buysell_value', 
                'coinank_buysell_volume', 'coinank_funding', 'coinank_liq_breakdown'
            ]
            for ca_feature in coinank_series:
                symbol_features.append(features.get(f"{symbol}_{ca_feature}", 0.0) / 1e9)
            
            # Liquidation data across timeframes (8 TFs x 4 metrics = 32 features)
            liq_timeframes = ['1m', '5m', '15m', '30m', '1h', '4h', '8h', '1d']
            liq_metrics = ['buyLiq', 'sellLiq', 'totalLiq', 'liqRatio']
            for tf in liq_timeframes:
                for metric in liq_metrics:
                    symbol_features.append(features.get(f"{symbol}_coinank_liq_{tf}_{metric}", 0.0) / 1e6)
            
            # Latest endpoint data (7 major categories)
            coinank_endpoints = [
                'open_interest', 'funding', 'long_short', 'market_order_flow', 
                'indicators', 'liquidations', 'orderBook_v2_bySymbol'
            ]
            # Each endpoint has multiple fields, conservatively 5 fields each = 35 features
            for endpoint in coinank_endpoints:
                for field_idx in range(5):  # Approximate field count per endpoint
                    symbol_features.append(features.get(f"{symbol}_coinank_{endpoint}_field_{field_idx}", 0.0))
            
            # Global CoinAnk features (market-wide metrics)
            global_features = [
                'coinank_fundingRate', 'coinank_netPositions', 'coinank_rsiMap', 
                'coinank_orderFlow', 'coinank_ls_exchange'
            ]
            for gf in global_features:
                symbol_features.append(features.get(f"{symbol}_{gf}", 0.0))
            
            # Features namespace processed data (conservatively 10 features)
            for feat_idx in range(10):
                symbol_features.append(features.get(f"{symbol}_coinank_features_feat_{feat_idx}", 0.0))
            
            # Core funding rate and ratios
            symbol_features.extend([
                features.get(f"{symbol}_funding_rate", 0.0) * 10000,  # Convert to basis points
                features.get(f"{symbol}_coinank_long_short_ratio", 0.0),
                features.get(f"{symbol}_coinank_price", 0.0),
                features.get(f"{symbol}_coinank_volume", 0.0) / 1e9,
            ])
            
            market_features.extend(symbol_features)
        
        # Portfolio features
        portfolio_features = [
            self.current_balance / self.initial_balance - 1.0,  # Normalized return
            sum(abs(pos) for pos in self.positions.values()),   # Total exposure
        ]
        
        # Enhanced position-aware features for each symbol (Phase 4 - Todo #11)
        for symbol in SYMBOLS:  # ALL 10 symbols
            position = self.positions[symbol]
            entry_price = self.entry_prices[symbol]
            current_price = self.current_prices[symbol]
            
            # 1. Position side: -1 (short), 0 (flat), +1 (long)
            position_side = np.sign(position)
            
            # 2. Position size as % of portfolio
            portfolio_value = self._compute_portfolio_value()
            size_pct = abs(position * current_price) / max(portfolio_value, 1e-8) if portfolio_value > 0 else 0.0
            
            # 3. Unrealized PnL as %
            if abs(position) > 1e-8 and entry_price > 1e-8:
                unrealized_pnl = position * (current_price - entry_price)
                unrealized_pnl_pct = unrealized_pnl / max(portfolio_value, 1e-8)
            else:
                unrealized_pnl_pct = 0.0
            
            # 4. Time in position (normalized to [0, 1], max 1 day = 1440 steps for 1m timeframe)
            if hasattr(self, 'position_open_times'):
                time_in_position = (self.step_count - self.position_open_times.get(symbol, self.step_count)) / 1440.0
                time_in_position = min(time_in_position, 1.0)  # Cap at 1.0
            else:
                time_in_position = 0.0
            
            # 5. Entry distance: % distance from entry price
            if entry_price > 1e-8:
                entry_distance = (current_price - entry_price) / entry_price
            else:
                entry_distance = 0.0
            
            # 6. Liquidation distance: % distance to estimated liquidation price
            # Assuming 5x leverage, liquidation at ~20% loss from entry
            if abs(position) > 1e-8 and entry_price > 1e-8:
                leverage = 5.0  # Assumed leverage for estimation
                if position > 0:  # Long position
                    liq_price = entry_price * (1 - 1/leverage)
                    liq_distance = (current_price - liq_price) / current_price if liq_price > 0 else 1.0
                else:  # Short position
                    liq_price = entry_price * (1 + 1/leverage)
                    liq_distance = (liq_price - current_price) / current_price if liq_price > 0 else 1.0
                liq_distance = max(liq_distance, 0.0)  # Ensure non-negative
            else:
                liq_distance = 1.0  # No position = far from liquidation
            
            # Add all position-aware features
            portfolio_features.extend([
                self.positions[symbol],     # Legacy: raw position (for backward compat)
                position_side,              # NEW: position direction
                size_pct,                   # NEW: position size %
                unrealized_pnl_pct,         # NEW: unrealized PnL %
                time_in_position,           # NEW: time in position
                entry_distance,             # NEW: distance from entry
                liq_distance,               # NEW: distance to liquidation
            ])
        
        # Combine all features
        state = np.array(market_features + portfolio_features, dtype=np.float32)
        
        # Add to history for lookback
        self.price_history.append(state)
        if len(self.price_history) > self.lookback_window:
            self.price_history.pop(0)
        
        # If we don't have enough history, pad with zeros
        while len(self.price_history) < self.lookback_window:
            self.price_history.insert(0, np.zeros_like(state))
        
        # Flatten history for final state
        final_state = np.concatenate(self.price_history)
        
        return final_state
    
    def decode_action(self, action: int) -> Dict[str, int]:
        """
        Decode action integer to individual symbol actions
        
        Args:
            action: Integer action (0 to action_space_size-1)
            
        Returns:
            Dictionary mapping symbol to action (0=hold, 1=buy, 2=sell)
        """
        symbol_actions = {}
        remaining = action
        
        for i, symbol in enumerate(SYMBOLS):  # ALL 10 symbols
            symbol_actions[symbol] = remaining % 3
            remaining //= 3
        
        return symbol_actions
    
    def execute_trades(self, symbol_actions: Dict[str, int]) -> Tuple[float, int]:
        """
        Execute trades based on actions and calculate transaction costs
        
        Args:
            symbol_actions: Dictionary mapping symbols to actions
            
        Returns:
            Total transaction cost, number of executed trades
        """
        total_cost = 0.0
        executed = 0
        # Capture closed trade outcomes for reward shaping / diagnostics
        self._closed_trades_last_step = []
        
        for symbol, action in symbol_actions.items():
            if action == 0:  # Hold
                continue
            
            current_price = self.current_prices.get(symbol, 0.0)
            if current_price <= 0:
                continue
            
            # Calculate trade size (simplified: fixed percentage of balance)
            trade_value = self.current_balance * self.trade_value_pct  # configurable % of balance per trade
            trade_size = trade_value / current_price
            
            if action == 1:  # Buy
                # Only buy if we're not already long
                if self.positions[symbol] <= 0:
                    # Enforce minimum hold time before reversing from short to long
                    if self.positions[symbol] < 0:
                        held_steps = self.step_count - self.position_open_times.get(symbol, 0)
                        if held_steps < self.min_hold_steps:
                            logger.debug(f"⏳ Skipping BUY for {symbol} - min hold {held_steps}/{self.min_hold_steps} steps")
                            continue
                        prev_pos = float(self.positions[symbol] or 0.0)
                        prev_entry = float(self.entry_prices.get(symbol, 0.0) or 0.0)
                        # Realize PnL on close (critical for correct reward accounting).
                        pnl_usd = prev_pos * (current_price - prev_entry) if prev_entry > 0 else 0.0
                        self.current_balance += pnl_usd
                        close_fee = abs(prev_pos) * current_price * self.transaction_cost
                        total_cost += close_fee
                        self.current_balance -= close_fee
                        # FEE TRACKING: Record fee for closing short
                        self.cumulative_fees += close_fee
                        self.fees_by_symbol[symbol] = self.fees_by_symbol.get(symbol, 0.0) + close_fee
                        # Net trade outcome after fees (entry fee paid earlier + close fee now)
                        entry_fee = float(self.entry_fees_by_symbol.get(symbol, 0.0) or 0.0)
                        net_trade = float(pnl_usd) - float(close_fee) - float(entry_fee)
                        self._closed_trades_last_step.append(
                            {
                                "symbol": symbol,
                                "closed_side": "SHORT",
                                "gross_pnl_usd": float(pnl_usd),
                                "entry_fee_usd": float(entry_fee),
                                "close_fee_usd": float(close_fee),
                                "net_pnl_usd": float(net_trade),
                            }
                        )
                        self.entry_fees_by_symbol[symbol] = 0.0
                        executed += 1
                    
                    # Open long position
                    self.positions[symbol] = trade_size
                    self.entry_prices[symbol] = current_price
                    self.position_open_times[symbol] = self.step_count  # Phase 4: Track when position opened
                    transaction_cost = trade_size * current_price * self.transaction_cost
                    total_cost += transaction_cost
                    self.current_balance -= transaction_cost
                    # FEE TRACKING: Record fee for opening long
                    self.cumulative_fees += transaction_cost
                    self.fees_by_symbol[symbol] = self.fees_by_symbol.get(symbol, 0.0) + transaction_cost
                    self.entry_fees_by_symbol[symbol] = float(transaction_cost)
                    self.trade_count += 1
                    executed += 1
                    
                    logger.debug(f"Bought {trade_size:.6f} {symbol} at {current_price:.2f}")
                    
            elif action == 2:  # Sell
                # Only sell if we're not already short
                if self.positions[symbol] >= 0:
                    # Enforce minimum hold time before reversing from long to short
                    if self.positions[symbol] > 0:
                        held_steps = self.step_count - self.position_open_times.get(symbol, 0)
                        if held_steps < self.min_hold_steps:
                            logger.debug(f"⏳ Skipping SELL for {symbol} - min hold {held_steps}/{self.min_hold_steps} steps")
                            continue
                        prev_pos = float(self.positions[symbol] or 0.0)
                        prev_entry = float(self.entry_prices.get(symbol, 0.0) or 0.0)
                        pnl_usd = prev_pos * (current_price - prev_entry) if prev_entry > 0 else 0.0
                        self.current_balance += pnl_usd
                        close_fee = abs(prev_pos) * current_price * self.transaction_cost
                        total_cost += close_fee
                        self.current_balance -= close_fee
                        # FEE TRACKING: Record fee for closing long
                        self.cumulative_fees += close_fee
                        self.fees_by_symbol[symbol] = self.fees_by_symbol.get(symbol, 0.0) + close_fee
                        entry_fee = float(self.entry_fees_by_symbol.get(symbol, 0.0) or 0.0)
                        net_trade = float(pnl_usd) - float(close_fee) - float(entry_fee)
                        self._closed_trades_last_step.append(
                            {
                                "symbol": symbol,
                                "closed_side": "LONG",
                                "gross_pnl_usd": float(pnl_usd),
                                "entry_fee_usd": float(entry_fee),
                                "close_fee_usd": float(close_fee),
                                "net_pnl_usd": float(net_trade),
                            }
                        )
                        self.entry_fees_by_symbol[symbol] = 0.0
                        executed += 1
                    
                    # Open short position
                    self.positions[symbol] = -trade_size
                    self.entry_prices[symbol] = current_price
                    self.position_open_times[symbol] = self.step_count  # Phase 4: Track when position opened
                    transaction_cost = trade_size * current_price * self.transaction_cost
                    total_cost += transaction_cost
                    self.current_balance -= transaction_cost
                    # FEE TRACKING: Record fee for opening short
                    self.cumulative_fees += transaction_cost
                    self.fees_by_symbol[symbol] = self.fees_by_symbol.get(symbol, 0.0) + transaction_cost
                    self.entry_fees_by_symbol[symbol] = float(transaction_cost)
                    self.trade_count += 1
                    executed += 1
                    
                    logger.debug(f"Sold {trade_size:.6f} {symbol} at {current_price:.2f}")
        
        return total_cost, executed
    
    def calculate_portfolio_value(self) -> float:
        """Calculate current portfolio value including unrealized PnL"""
        total_value = self.current_balance
        
        for symbol in SYMBOLS:  # ALL 10 symbols
            if self.positions[symbol] != 0:
                current_price = self.current_prices.get(symbol, 0.0)
                entry_price = self.entry_prices[symbol]
                
                if current_price > 0 and entry_price > 0:
                    # Calculate unrealized PnL
                    pnl = self.positions[symbol] * (current_price - entry_price)
                    total_value += pnl
        
        return total_value
    
    def step(self, action: int) -> Tuple[np.ndarray, float, bool, Dict[str, Any]]:
        """
        Execute one step in the environment
        
        Args:
            action: Integer action to take
            
        Returns:
            Tuple of (next_state, reward, done, info)
        """
        self.step_count += 1
        
        # Phase 1A: Track previous action for trade detection
        prev_action = getattr(self, '_prev_action', None)
        trade_executed = False
        self._prev_action = action
        
        # Update current prices from latest data
        features = self.get_current_features()
        for symbol in SYMBOLS:  # ALL 10 symbols
            # Get latest price from a price source (simplified)
            price_key = f"price:{symbol}:1m"
            try:
                price_data = self.redis.hgetall(price_key)
                if price_data and 'close' in price_data:
                    self.current_prices[symbol] = float(price_data['close'])
            except (redis.TimeoutError, redis.ConnectionError) as e:
                # Gracefully handle Redis timeouts - use last known price
                if symbol not in self.current_prices:
                    # Fallback: use a default price or skip this symbol
                    logger.warning(f"Redis timeout for {symbol}, using last known price")
                # Continue with last known price
                pass
            except Exception as e:
                logger.error(f"Unexpected error fetching price for {symbol}: {e}")
                pass
        
        # Decode and execute action
        symbol_actions = self.decode_action(action)
        transaction_cost, trades_executed = self.execute_trades(symbol_actions)
        trade_executed = trades_executed > 0
        
        # Determine action category for fee-aware reward shaping
        # Actions 0,2 = OPEN_RISK (opening positions), Action 1 = HOLD (PROTECTIVE)
        if isinstance(action, (int, np.integer)):
            action_category = "OPEN_RISK" if action in (0, 2) else "PROTECTIVE"
        else:
            action_category = "UNKNOWN"
        
        # Calculate portfolio value
        portfolio_value = self.calculate_portfolio_value()
        
        # Calculate base reward (change in portfolio value)
        prev_portfolio_value = getattr(self, '_prev_portfolio_value', self.initial_balance)
        base_reward = (portfolio_value - prev_portfolio_value) / self.initial_balance  # Normalized reward
        self._prev_portfolio_value = portfolio_value
        
        # Fees are already deducted from balance (and thus portfolio_value).
        # Only apply *extra* fee penalty above the 1x baseline to avoid double-counting.
        try:
            extra_fee_mult = max(0.0, float(FEE_PENALTY_MULTIPLIER or 1.0) - 1.0)
        except Exception:
            extra_fee_mult = 0.0
        if extra_fee_mult > 0 and transaction_cost:
            base_reward -= (transaction_cost / self.initial_balance) * float(extra_fee_mult)
        
        # Apply risk-adjusted reward shaping (Phase 1A + existing Phase 4 logic + Fee Ratio Awareness)
        reward = self._compute_risk_adjusted_reward(
            base_reward=base_reward,
            portfolio_value=portfolio_value,
            prev_portfolio_value=prev_portfolio_value,
            trade_executed=trade_executed,  # Pass trade flag
            action_category=action_category  # Pass category for fee-aware shaping
        )

        # Episode-aligned shaping (trade-cycle): when a leg is closed, add a small win bonus
        # and a bounded loss penalty to bias toward higher win rate (net-after-fees).
        try:
            win_bonus = float(os.getenv("SYMBOL_EPISODE_WIN_BONUS", "0.0005"))
            loss_penalty = float(os.getenv("SYMBOL_EPISODE_LOSS_PENALTY", "0.0010"))
            closed_trades = getattr(self, "_closed_trades_last_step", None) or []
            for tr in closed_trades:
                try:
                    net = float(tr.get("net_pnl_usd") or 0.0)
                except Exception:
                    net = 0.0
                if net > 0:
                    reward += win_bonus
                elif net < 0:
                    reward -= loss_penalty
        except Exception:
            pass
        
        # Get next state
        next_state = self.get_state()
        
        # Check if episode is done (simplified: after fixed number of steps)
        done = self.step_count >= 1000  # 1000 steps per episode
        
        # Phase 1A: Enhanced info dictionary with FEE AWARENESS
        info = {
            'portfolio_value': portfolio_value,
            'balance': self.current_balance,
            'positions': self.positions.copy(),
            'transaction_cost': transaction_cost,
            'step_count': self.step_count,
            'trade_executed': trade_executed,  # NEW
            'pnl_change': portfolio_value - prev_portfolio_value,  # NEW
            'drawdown': getattr(self, '_current_drawdown', 0.0),  # NEW
            'risk_adjusted_reward': reward,  # NEW
            'raw_reward': base_reward,  # NEW
            'symbol_actions': symbol_actions,
            # FEE AWARENESS: Track cumulative fees for trainer visibility
            'cumulative_fees': self.cumulative_fees,
            'fees_by_symbol': self.fees_by_symbol.copy(),
            'trade_count': self.trade_count,
            'fee_rate': self.transaction_cost,  # Expose fee rate for logging
            'fee_pct_of_balance': (self.cumulative_fees / self.initial_balance * 100) if self.initial_balance > 0 else 0.0
        }
        try:
            info['closed_trades_last_step'] = getattr(self, "_closed_trades_last_step", None)
        except Exception:
            info['closed_trades_last_step'] = None

        # Training-only diagnostics for persistent penalties
        try:
            info['persistent_penalties'] = getattr(self, '_persistent_penalty_debug', None)
        except Exception:
            info['persistent_penalties'] = None
        
        return next_state, reward, done, info
    
    def _compute_risk_adjusted_reward(self, base_reward: float, portfolio_value: float, 
                                      prev_portfolio_value: float, trade_executed: bool = False,
                                      action_category: str = "UNKNOWN") -> float:
        """
        Apply risk-adjusted reward shaping for smoother equity and higher win rate
        
        Phase 1A + Phase 4 Optimization: Combines overtrading penalty with drawdown/volatility penalties
        + Fee Ratio Awareness (Dec 29, 2025): Penalizes rewards when fee ratio is high
        
        Args:
            base_reward: Raw PnL-based reward
            portfolio_value: Current portfolio value
            prev_portfolio_value: Previous portfolio value
            trade_executed: Whether action changed (new in Phase 1A)
            action_category: OPEN_RISK, HEDGE, or PROTECTIVE for fee-aware shaping
            
        Returns:
            Risk-adjusted reward with penalties and bonuses
        """
        # Start with base reward
        reward = base_reward
        
        # Phase 1A: Trade Penalty (discourages overtrading)
        if USE_RISK_ADJUSTED_REWARD and trade_executed:
            reward -= self.trade_penalty
        
        # Legacy config fallback for Phase 4 parameters
        try:
            from config import get_live_config
            config = get_live_config()
            alpha = config.RISK_PENALTY_ALPHA  # Drawdown penalty weight
            beta = config.RISK_PENALTY_BETA    # Volatility penalty weight  
            gamma = config.PROFIT_LOCK_GAMMA   # Profit lock bonus
        except Exception:
            # Use Phase 1A config if available, otherwise fallback to defaults
            alpha = DRAWDOWN_PENALTY if USE_RISK_ADJUSTED_REWARD else 0.1
            beta = 0.05  # Keep volatility penalty low
            gamma = 1.5  # Profit lock bonus
        
        # 1. Drawdown Penalty: Penalize losses more than gains
        # Track rolling max portfolio value
        if not hasattr(self, '_max_portfolio_value'):
            self._max_portfolio_value = self.initial_balance
        self._max_portfolio_value = max(self._max_portfolio_value, portfolio_value)
        
        # Calculate drawdown from peak
        drawdown_pct = (self._max_portfolio_value - portfolio_value) / self._max_portfolio_value
        self._current_drawdown = drawdown_pct  # Store for info dict
        
        if USE_RISK_ADJUSTED_REWARD and drawdown_pct > 0:
            # Phase 1A: Use DRAWDOWN_PENALTY from config
            # Note: Phase 1A uses linear penalty, Phase 4 uses quadratic
            # We'll use Phase 1A approach when flag is enabled
            drawdown_penalty = -DRAWDOWN_PENALTY * drawdown_pct
            reward += drawdown_penalty
        elif drawdown_pct > 0:
            # Legacy Phase 4 approach (quadratic)
            drawdown_penalty = -alpha * (drawdown_pct ** 2)
            reward += drawdown_penalty
        
        # 2. Volatility Penalty: Penalize erratic equity swings
        # Track recent portfolio value changes
        if not hasattr(self, '_recent_pnl_changes'):
            self._recent_pnl_changes = []
        
        pnl_change_pct = abs(portfolio_value - prev_portfolio_value) / prev_portfolio_value if prev_portfolio_value > 0 else 0
        self._recent_pnl_changes.append(pnl_change_pct)
        
        # Keep last 20 changes for rolling volatility
        if len(self._recent_pnl_changes) > 20:
            self._recent_pnl_changes.pop(0)
        
        # Calculate volatility (standard deviation of returns)
        if len(self._recent_pnl_changes) >= 5:
            volatility = np.std(self._recent_pnl_changes)
            volatility_penalty = -beta * volatility
            reward += volatility_penalty
        
        # 3. Profit Lock Bonus: Reward realizing profits
        # Detect if we closed a profitable position
        total_pnl = portfolio_value - self.initial_balance
        if total_pnl > 0 and portfolio_value > prev_portfolio_value:
            # Bonus for moving equity upward when already profitable
            profit_bonus = gamma * base_reward
            reward += profit_bonus
        
        # 4. Profit Protection: Extra penalty for giving back gains
        if hasattr(self, '_prev_total_pnl'):
            prev_total_pnl = self._prev_total_pnl
            current_total_pnl = portfolio_value - self.initial_balance
            
            # If we were profitable but now less so, extra penalty
            if prev_total_pnl > 0 and current_total_pnl < prev_total_pnl:
                giveback_penalty = -alpha * abs(current_total_pnl - prev_total_pnl) / self.initial_balance
                reward += giveback_penalty
        
        self._prev_total_pnl = portfolio_value - self.initial_balance
        
        # 5. FEE RATIO AWARENESS (Dec 29, 2025): Penalize rewards when fee ratio is high
        # This teaches the model to trade less when fees are eating into profits
        if FEE_RATIO_SHAPING_AVAILABLE and FEE_RATIO_REWARD_SHAPING_ENABLED and trade_executed:
            try:
                # Use singleton shaper for efficiency
                if not hasattr(self, '_fee_ratio_shaper'):
                    self._fee_ratio_shaper = FeeRatioRewardShaper()
                
                shaped_result = self._fee_ratio_shaper.shape_reward(
                    base_reward=reward,
                    action_category=action_category,
                    trade_executed=trade_executed
                )
                
                # Use shaped reward
                old_reward = reward
                reward = shaped_result['shaped_reward']
                
                # Log periodically (every 100 steps)
                if not hasattr(self, '_fee_shape_log_counter'):
                    self._fee_shape_log_counter = 0
                self._fee_shape_log_counter += 1
                if self._fee_shape_log_counter % 100 == 0:
                    logger.debug(
                        f"[FEE_SHAPE] reward {old_reward:.4f} → {reward:.4f} | "
                        f"fee_ratio={shaped_result['fee_ratio']:.1%} | "
                        f"reason={shaped_result['penalty_reason']}"
                    )
            except Exception as e:
                logger.debug(f"[FEE_SHAPE] Error applying fee ratio shaping: {e}")

        # 6. PERSISTENT NEGATIVE EQUITY + NEGATIVE LEGS PENALTIES (operator requirement)
        # These penalties persist while:
        # - Overall equity is below baseline (episode start equity), and
        # - Any open legs are negative (unrealized PnL < 0).
        if bool(TRAIN_PERSISTENT_PENALTIES_ENABLED):
            try:
                baseline = float(getattr(self, "_equity_baseline", self.initial_balance) or self.initial_balance or 1.0)
                baseline = max(1.0, baseline)

                # (A) Equity below baseline penalty (normalized)
                equity_delta_pct = (float(portfolio_value) - baseline) / baseline
                if equity_delta_pct < 0.0:
                    reward -= float(TRAIN_EQUITY_BELOW_BASELINE_PENALTY_K or 0.0) * abs(equity_delta_pct)

                # (B) Negative legs penalty: sum negative unrealized PnL (USD), normalize by baseline.
                neg_unrealized_usd = 0.0
                neg_legs = 0
                try:
                    for sym in SYMBOLS:
                        pos_qty = float(self.positions.get(sym, 0.0) or 0.0)
                        if pos_qty == 0.0:
                            continue
                        px = float(self.current_prices.get(sym, 0.0) or 0.0)
                        ep = float(self.entry_prices.get(sym, 0.0) or 0.0)
                        if px <= 0.0 or ep <= 0.0:
                            continue
                        pnl = pos_qty * (px - ep)  # signed PnL in quote currency (USD for USDT pairs)
                        if pnl < 0.0:
                            neg_unrealized_usd += abs(pnl)
                            neg_legs += 1
                except Exception:
                    neg_unrealized_usd = 0.0
                    neg_legs = 0

                if neg_unrealized_usd > 0.0:
                    reward -= float(TRAIN_NEG_LEG_PENALTY_K or 0.0) * (neg_unrealized_usd / baseline)

                # Store for info/debugging
                self._persistent_penalty_debug = {
                    "baseline": baseline,
                    "equity_delta_pct": equity_delta_pct,
                    "neg_unrealized_usd": float(neg_unrealized_usd),
                    "neg_legs": int(neg_legs),
                }
            except Exception:
                # Fail-open: never break env step due to shaping
                pass
        
        return reward
    
    def reset(self, real_portfolio_data: Dict = None) -> np.ndarray:
        """
        Reset environment to initial state.
        
        Args:
            real_portfolio_data: Optional dict with real Binance account data:
                {
                    'balance': float,  # Current account equity
                    'positions': Dict[str, float],  # {symbol: quantity}
                    'entry_prices': Dict[str, float],  # {symbol: avg_entry_price}
                }
        """
        if real_portfolio_data:
            # Use REAL portfolio data from Binance
            self.current_balance = real_portfolio_data.get('balance', self.initial_balance)
            self.positions = real_portfolio_data.get('positions', {symbol: 0.0 for symbol in SYMBOLS})
            self.entry_prices = real_portfolio_data.get('entry_prices', {symbol: 0.0 for symbol in SYMBOLS})
            logger.info(f"🔄 [ENV-RESET] Using REAL portfolio: balance=${self.current_balance:.2f}, "
                       f"positions={sum(1 for p in self.positions.values() if abs(p) > 0)}")
        else:
            # Simulated reset
            self.current_balance = self.initial_balance
            self.positions = {symbol: 0.0 for symbol in SYMBOLS}  # ALL 10 symbols
            self.entry_prices = {symbol: 0.0 for symbol in SYMBOLS}  # ALL 10 symbols
        
        self.current_prices = {symbol: 0.0 for symbol in SYMBOLS}  # ALL 10 symbols
        self.position_open_times = {symbol: 0 for symbol in SYMBOLS}  # Phase 4: Track position open times
        self.price_history = []
        self.step_count = 0
        self.episode_start_balance = self.current_balance
        self._prev_portfolio_value = self.current_balance

        # Persistent penalty baselines (training-only): reset baseline to current equity/balance.
        # Penalties apply until equity recovers above this baseline.
        self._equity_baseline = float(self.current_balance or self.initial_balance or 1.0)
        
        # FEE TRACKING: Reset cumulative fees on episode reset
        self.cumulative_fees = 0.0
        self.fees_by_symbol = {symbol: 0.0 for symbol in SYMBOLS}
        self.entry_fees_by_symbol = {symbol: 0.0 for symbol in SYMBOLS}
        self.trade_count = 0
        self._closed_trades_last_step = []
        
        # Phase 1A: Reset tracking variables
        self._prev_action = None
        self._current_drawdown = 0.0
        self._max_portfolio_value = self.current_balance
        if hasattr(self, '_recent_pnl_changes'):
            self._recent_pnl_changes.clear()
        if hasattr(self, '_prev_total_pnl'):
            delattr(self, '_prev_total_pnl')
        
        if not real_portfolio_data:
            logger.info("Environment reset (simulated)")
        if USE_RISK_ADJUSTED_REWARD:
            logger.debug("Phase 1A risk-adjusted reward active")
        
        # Wait a moment for fresh data
        time.sleep(1)
        
        return self.get_state()
    
    def get_action_space_size(self) -> int:
        """Get the size of the action space"""
        return self.action_space_size
    
    def get_state_size(self) -> int:
        """Get the size of the state vector dynamically"""
        try:
            # Get a sample state to determine actual size
            sample_state = self.get_state()
            actual_size = len(sample_state)  # Remove lookback_window multiplication for now
            logger.info(f"Dynamic state size calculation: {len(sample_state)} features (lookback window not implemented yet)")
            return actual_size
        except Exception as e:
            # Fallback to estimated size if we can't get actual data
            logger.warning(f"Could not get dynamic state size, using fallback: {e}")
            # Use a reasonable estimate based on current feature counts (~1800 features)
            return 1800
