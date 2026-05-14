"""
Ingestor Quality Router
========================
Scores and routes microstructure data from the most reliable feed per slice.

Slices:
- OHLCV: Price/volume data (ccxt_* fields)
- Orderbook: Depth/spread/imbalance (ob_* or orderbook:top:*)
- Liquidations: Long/short liquidation data
- Ticker: Best bid/ask, trades

Scoring: score = w1*freshness + w2*completeness + w3*nonzero_ratio + w4*monotonicity

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


class DataSlice(Enum):
    """Data slice types."""
    OHLCV = "ohlcv"
    ORDERBOOK = "orderbook"
    LIQUIDATIONS = "liquidations"
    TICKER = "ticker"


class DataSource(Enum):
    """Known data sources/ingestors."""
    CCXT = "ccxt"
    COINANK = "coinank"
    BINANCE_WS = "binance_ws"
    ORDERBOOK_INGESTOR = "orderbook_ingestor"
    UNIFIED = "unified"


@dataclass
class SliceConfig:
    """Configuration for a data slice."""
    name: DataSlice
    expected_fields: List[str]
    redis_key_patterns: List[str]  # Patterns to check for this slice
    field_prefix: str = ""
    max_staleness_ms: int = 60000


@dataclass
class SourceMetrics:
    """Quality metrics for a single source."""
    source: str
    slice_name: str
    freshness_score: float = 0.0  # 1.0 = fresh, 0.0 = stale
    completeness_score: float = 0.0  # Fraction of expected fields present
    nonzero_ratio: float = 0.0  # Fraction of fields with nonzero values
    monotonicity_score: float = 1.0  # Timestamp monotonicity (gaps = lower)
    staleness_ms: int = 0
    last_update_ts: float = 0.0
    fields_present: int = 0
    fields_expected: int = 0
    
    @property
    def total_score(self) -> float:
        """Compute weighted total score."""
        # Weights: freshness most important, then completeness, then nonzero
        w1, w2, w3, w4 = 0.4, 0.3, 0.2, 0.1
        return (
            w1 * self.freshness_score +
            w2 * self.completeness_score +
            w3 * self.nonzero_ratio +
            w4 * self.monotonicity_score
        )
    
    def to_dict(self) -> Dict:
        return {
            'source': self.source,
            'slice': self.slice_name,
            'total_score': round(self.total_score, 3),
            'freshness': round(self.freshness_score, 3),
            'completeness': round(self.completeness_score, 3),
            'nonzero_ratio': round(self.nonzero_ratio, 3),
            'staleness_ms': self.staleness_ms,
            'fields': f"{self.fields_present}/{self.fields_expected}",
        }


@dataclass
class SliceQuality:
    """Quality assessment for a data slice."""
    slice_name: str
    best_source: Optional[str] = None
    best_score: float = 0.0
    runner_up_source: Optional[str] = None
    runner_up_score: float = 0.0
    sources: Dict[str, SourceMetrics] = field(default_factory=dict)
    is_healthy: bool = True
    health_reason: str = ""
    
    def to_log_line(self) -> str:
        staleness = self.sources[self.best_source].staleness_ms if self.best_source and self.best_source in self.sources else 0
        completeness = self.sources[self.best_source].completeness_score if self.best_source and self.best_source in self.sources else 0
        return (
            f"INGESTOR_QUALITY | {self.slice_name} | best={self.best_source} | "
            f"score={self.best_score:.2f} | runner_up={self.runner_up_source} | "
            f"staleness_ms={staleness} | completeness={completeness:.1%}"
        )


# Slice configurations
SLICE_CONFIGS = {
    DataSlice.OHLCV: SliceConfig(
        name=DataSlice.OHLCV,
        expected_fields=['open', 'high', 'low', 'close', 'volume', 'timestamp'],
        redis_key_patterns=['unified_features:{symbol}:{tf}'],
        field_prefix='ccxt_',
        max_staleness_ms=120000,  # 2 minutes
    ),
    DataSlice.ORDERBOOK: SliceConfig(
        name=DataSlice.ORDERBOOK,
        expected_fields=['bid_price', 'ask_price', 'bid_depth', 'ask_depth', 'spread', 'imbalance'],
        redis_key_patterns=['orderbook:top:{symbol}', 'unified_features:{symbol}:{tf}'],
        field_prefix='ob_',
        max_staleness_ms=30000,  # 30 seconds
    ),
    DataSlice.LIQUIDATIONS: SliceConfig(
        name=DataSlice.LIQUIDATIONS,
        expected_fields=['long_liq', 'short_liq', 'liq_imbalance', 'total_liq'],
        redis_key_patterns=['unified_features:{symbol}:{tf}'],
        field_prefix='liquidation_',
        max_staleness_ms=60000,
    ),
    DataSlice.TICKER: SliceConfig(
        name=DataSlice.TICKER,
        expected_fields=['last_price', 'bid', 'ask', 'volume_24h'],
        redis_key_patterns=['ticker:{symbol}', 'orderbook:top:{symbol}'],
        field_prefix='',
        max_staleness_ms=10000,  # 10 seconds
    ),
}


class IngestorQualityRouter:
    """
    Routes microstructure data from the most reliable source per slice.
    
    Features:
    - Scores each source by freshness, completeness, nonzero ratio
    - Selects best source per slice
    - Optionally canonicalizes orderbook fields
    - Periodic logging and Redis cache of quality metrics
    """
    
    def __init__(
        self,
        redis_client: Any = None,
        update_interval_sec: int = 30,
        canonicalize_orderbook: bool = False,
    ):
        self.redis = redis_client
        self.update_interval_sec = update_interval_sec
        self.canonicalize_orderbook = canonicalize_orderbook
        
        # Load from env
        self.update_interval_sec = int(os.getenv("INGESTOR_QUALITY_UPDATE_INTERVAL_SEC", str(update_interval_sec)))
        self.canonicalize_orderbook = os.getenv("INGESTOR_QUALITY_CANONICALIZE_ORDERBOOK", "false").lower() == "true"
        
        # State
        self._last_update_ts: float = 0
        self._slice_quality: Dict[str, SliceQuality] = {}
        self._source_history: Dict[str, List[Tuple[float, float]]] = defaultdict(list)  # source -> [(ts, score)]
        
        logger.info(
            f"IngestorQualityRouter initialized | "
            f"update_interval={self.update_interval_sec}s | "
            f"canonicalize_orderbook={self.canonicalize_orderbook}"
        )
    
    def _parse_redis_hash(self, key: str) -> Optional[Dict[str, str]]:
        """Parse Redis key to dict.

        Supports both:
        - Redis HASH (hgetall)
        - Redis STRING containing JSON (get + json.loads)
        """
        if self.redis is None:
            return None
        try:
            # Prefer HASH (legacy + many ingestors write hashes)
            raw = self.redis.hgetall(key)
            if raw:
                data: Dict[str, str] = {}
                for k, v in raw.items():
                    k_str = k.decode('utf-8') if isinstance(k, bytes) else k
                    v_str = v.decode('utf-8') if isinstance(v, bytes) else v
                    data[k_str] = v_str
                return data

            # Fallback: STRING JSON (Binance orderbook ingestor writes orderbook:top as JSON)
            try:
                key_type = self.redis.type(key)
                key_type = key_type.decode() if isinstance(key_type, bytes) else key_type
            except Exception:
                key_type = None

            if key_type == "string":
                raw_s = self.redis.get(key)
                if not raw_s:
                    return None
                raw_str = raw_s.decode("utf-8") if isinstance(raw_s, (bytes, bytearray)) else str(raw_s)
                obj = json.loads(raw_str)
                if isinstance(obj, dict):
                    # Normalize to str->str
                    return {str(k): str(v) for k, v in obj.items()}
            return None
        except Exception as e:
            logger.debug(f"[INGESTOR_ROUTER] Error reading {key}: {e}")
            return None
    
    def _compute_freshness(self, staleness_ms: int, max_staleness_ms: int) -> float:
        """Compute freshness score (1.0 = fresh, 0.0 = very stale)."""
        if staleness_ms <= 0:
            return 1.0
        if staleness_ms >= max_staleness_ms:
            return 0.0
        # Linear decay
        return 1.0 - (staleness_ms / max_staleness_ms)
    
    def _score_source_for_slice(
        self,
        source_name: str,
        data: Dict[str, str],
        config: SliceConfig,
    ) -> SourceMetrics:
        """Score a source for a specific slice."""
        metrics = SourceMetrics(
            source=source_name,
            slice_name=config.name.value,
            fields_expected=len(config.expected_fields),
        )
        
        now_ms = int(time.time() * 1000)
        
        # Extract timestamp
        ts_field = (
            data.get('updated_ts_ms') or
            data.get('updated_ts') or
            data.get('timestamp') or
            data.get('ts_ms') or
            data.get('ts')
        )
        if ts_field:
            try:
                ts_val = float(ts_field)
                if ts_val > 1e12:
                    ts_val = ts_val / 1000  # Convert ms to seconds
                metrics.last_update_ts = ts_val
                metrics.staleness_ms = int(now_ms - ts_val * 1000)
            except (ValueError, TypeError):
                metrics.staleness_ms = config.max_staleness_ms  # Assume stale
        else:
            metrics.staleness_ms = config.max_staleness_ms
        
        # Freshness score
        metrics.freshness_score = self._compute_freshness(metrics.staleness_ms, config.max_staleness_ms)
        
        # Check expected fields
        fields_found = 0
        nonzero_count = 0
        
        for field in config.expected_fields:
            # Check with and without prefix
            key = f"{config.field_prefix}{field}"
            value = data.get(key) or data.get(field)
            
            if value is not None:
                fields_found += 1
                try:
                    if float(value) != 0:
                        nonzero_count += 1
                except (ValueError, TypeError):
                    pass  # Non-numeric field
        
        metrics.fields_present = fields_found
        metrics.completeness_score = fields_found / len(config.expected_fields) if config.expected_fields else 1.0
        metrics.nonzero_ratio = nonzero_count / fields_found if fields_found > 0 else 0.0
        
        return metrics
    
    def evaluate_slice(
        self,
        slice_type: DataSlice,
        symbol: str,
        timeframe: str = "5m",
    ) -> SliceQuality:
        """Evaluate quality for a slice across all sources."""
        config = SLICE_CONFIGS[slice_type]
        quality = SliceQuality(slice_name=slice_type.value)
        
        # Gather data from all potential sources
        sources_data = {}
        
        for pattern in config.redis_key_patterns:
            key = pattern.format(symbol=symbol, tf=timeframe)
            data = self._parse_redis_hash(key)
            if data:
                # Determine source from key pattern
                if 'orderbook:top' in pattern:
                    source_name = 'orderbook_ingestor'
                elif 'unified_features' in pattern:
                    source_name = 'unified'
                elif 'ticker' in pattern:
                    source_name = 'ticker_ingestor'
                else:
                    source_name = pattern.split(':')[0]
                sources_data[source_name] = data
        
        # Score each source
        for source_name, data in sources_data.items():
            metrics = self._score_source_for_slice(source_name, data, config)
            quality.sources[source_name] = metrics
        
        # Select best source
        if quality.sources:
            sorted_sources = sorted(
                quality.sources.items(),
                key=lambda x: x[1].total_score,
                reverse=True
            )
            
            quality.best_source = sorted_sources[0][0]
            quality.best_score = sorted_sources[0][1].total_score
            
            if len(sorted_sources) > 1:
                quality.runner_up_source = sorted_sources[1][0]
                quality.runner_up_score = sorted_sources[1][1].total_score
            
            # Health check
            best_metrics = sorted_sources[0][1]
            if best_metrics.freshness_score < 0.3:
                quality.is_healthy = False
                quality.health_reason = f"Best source stale: {best_metrics.staleness_ms}ms"
            elif best_metrics.completeness_score < 0.5:
                quality.is_healthy = False
                quality.health_reason = f"Best source incomplete: {best_metrics.completeness_score:.1%}"
        else:
            quality.is_healthy = False
            quality.health_reason = "No sources found"
        
        return quality
    
    def get_best_orderbook_source(self, symbol: str) -> Tuple[str, Optional[Dict[str, str]]]:
        """Get the best orderbook data for a symbol."""
        quality = self.evaluate_slice(DataSlice.ORDERBOOK, symbol)
        
        if not quality.best_source or not quality.is_healthy:
            return "", None
        
        # Fetch data from best source
        if quality.best_source == 'orderbook_ingestor':
            data = self._parse_redis_hash(f"orderbook:top:{symbol}")
        else:
            data = self._parse_redis_hash(f"unified_features:{symbol}:5m")
        
        return quality.best_source, data
    
    def get_canonical_orderbook(self, symbol: str) -> Dict[str, Any]:
        """
        Get canonical orderbook fields from the best source.
        
        Returns dict with: bid, ask, spread, bid_depth, ask_depth, imbalance, updated_ts
        """
        source, data = self.get_best_orderbook_source(symbol)
        
        canonical = {
            'source': source,
            'bid': 0.0,
            'ask': 0.0,
            'spread': 0.0,
            'bid_depth': 0.0,
            'ask_depth': 0.0,
            'imbalance': 0.0,
            'updated_ts': 0,
            'is_healthy': False,
        }
        
        if not data:
            return canonical
        
        try:
            # Map fields from various sources to canonical names
            canonical['bid'] = float(data.get('bid') or data.get('bid_price') or data.get('ob_bid_price') or 0)
            canonical['ask'] = float(data.get('ask') or data.get('ask_price') or data.get('ob_ask_price') or 0)
            canonical['bid_depth'] = float(data.get('bid_qty') or data.get('bid_depth') or data.get('ob_bid_depth') or 0)
            canonical['ask_depth'] = float(data.get('ask_qty') or data.get('ask_depth') or data.get('ob_ask_depth') or 0)
            canonical['spread'] = float(data.get('spread') or data.get('ob_spread') or 0)
            canonical['imbalance'] = float(data.get('imbalance') or data.get('ob_imbalance') or 0)
            
            ts = data.get('updated_ts') or data.get('timestamp')
            if ts:
                ts_val = float(ts)
                canonical['updated_ts'] = int(ts_val * 1000 if ts_val < 1e12 else ts_val)
            
            # Compute derived fields if missing
            if canonical['spread'] == 0 and canonical['bid'] > 0 and canonical['ask'] > 0:
                canonical['spread'] = (canonical['ask'] - canonical['bid']) / canonical['bid'] * 100
            
            if canonical['imbalance'] == 0 and (canonical['bid_depth'] + canonical['ask_depth']) > 0:
                total = canonical['bid_depth'] + canonical['ask_depth']
                canonical['imbalance'] = (canonical['bid_depth'] - canonical['ask_depth']) / total
            
            canonical['is_healthy'] = canonical['bid'] > 0 and canonical['ask'] > 0
            
        except Exception as e:
            logger.debug(f"[INGESTOR_ROUTER] Error parsing orderbook for {symbol}: {e}")
        
        return canonical
    
    def update_quality_cache(self, symbols: List[str], timeframe: str = "5m"):
        """Update quality cache for all slices and symbols."""
        now = time.time()
        if now - self._last_update_ts < self.update_interval_sec:
            return
        
        self._last_update_ts = now
        
        for slice_type in [DataSlice.ORDERBOOK, DataSlice.OHLCV]:
            for symbol in symbols[:5]:  # Sample first 5 symbols
                quality = self.evaluate_slice(slice_type, symbol, timeframe)
                self._slice_quality[f"{slice_type.value}:{symbol}"] = quality
                
                # Log quality
                logger.info(quality.to_log_line())
                
                # Cache to Redis
                if self.redis:
                    try:
                        cache_key = f"ingestor:quality:{slice_type.value}"
                        self.redis.hset(cache_key, symbol, json.dumps(quality.sources.get(quality.best_source, {}).to_dict() if quality.best_source and quality.best_source in quality.sources else {}))
                        self.redis.expire(cache_key, 60)
                    except Exception as e:
                        logger.debug(f"[INGESTOR_ROUTER] Failed to cache quality: {e}")
    
    def canonicalize_to_redis(self, symbol: str, timeframe: str = "5m"):
        """Write canonical orderbook fields to Redis."""
        if not self.canonicalize_orderbook or self.redis is None:
            return
        
        canonical = self.get_canonical_orderbook(symbol)
        if not canonical.get('is_healthy'):
            return
        
        try:
            key = f"unified_features:{symbol}:{timeframe}:latest"
            self.redis.hset(key, mapping={
                'ob_bid_price': str(canonical['bid']),
                'ob_ask_price': str(canonical['ask']),
                'ob_bid_depth': str(canonical['bid_depth']),
                'ob_ask_depth': str(canonical['ask_depth']),
                'ob_spread': str(canonical['spread']),
                'ob_imbalance': str(canonical['imbalance']),
                'ob_updated_ts': str(canonical['updated_ts']),
                'ob_source': canonical['source'],
            })
            self.redis.expire(key, 120)
        except Exception as e:
            logger.debug(f"[INGESTOR_ROUTER] Failed to canonicalize: {e}")
    
    def get_quality_report(self, symbols: List[str], timeframe: str = "5m") -> Dict[str, Any]:
        """Generate a quality report for all slices."""
        report = {
            'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
            'symbols': len(symbols),
            'slices': {},
        }
        
        for slice_type in DataSlice:
            slice_report = {
                'best_sources': {},
                'avg_freshness': 0.0,
                'avg_completeness': 0.0,
                'unhealthy_count': 0,
            }
            
            freshness_scores = []
            completeness_scores = []
            
            for symbol in symbols:
                quality = self.evaluate_slice(slice_type, symbol, timeframe)
                if quality.best_source:
                    slice_report['best_sources'][symbol] = quality.best_source
                    if quality.best_source in quality.sources:
                        metrics = quality.sources[quality.best_source]
                        freshness_scores.append(metrics.freshness_score)
                        completeness_scores.append(metrics.completeness_score)
                if not quality.is_healthy:
                    slice_report['unhealthy_count'] += 1
            
            if freshness_scores:
                slice_report['avg_freshness'] = sum(freshness_scores) / len(freshness_scores)
            if completeness_scores:
                slice_report['avg_completeness'] = sum(completeness_scores) / len(completeness_scores)
            
            report['slices'][slice_type.value] = slice_report
        
        return report


# Global instance
_ingestor_router: Optional[IngestorQualityRouter] = None


def get_ingestor_router(
    redis_client: Any = None,
    force_new: bool = False,
) -> IngestorQualityRouter:
    """Get global ingestor router instance."""
    global _ingestor_router
    if _ingestor_router is None or force_new:
        _ingestor_router = IngestorQualityRouter(redis_client=redis_client)
    elif redis_client is not None and _ingestor_router.redis is None:
        _ingestor_router.redis = redis_client
    return _ingestor_router


def get_canonical_orderbook(symbol: str, redis_client: Any = None) -> Dict[str, Any]:
    """Convenience function to get canonical orderbook."""
    router = get_ingestor_router(redis_client)
    return router.get_canonical_orderbook(symbol)

