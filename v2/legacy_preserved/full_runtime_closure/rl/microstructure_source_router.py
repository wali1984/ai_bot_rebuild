"""
Microstructure Source Router
============================
Routes microstructure data from the best available source per symbol.

Sources (in priority order):
1. coinapi_wsds - CoinAPI WebSocket DS (primary, lowest latency)
2. coinapi_rest - CoinAPI REST (fallback)
3. binance_ws - Binance WebSocket (orderbook ingestor)
4. ccxt - CCXT unified features
5. coinank - Coinank OI/funding data

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

logger = logging.getLogger(__name__)


class MicroSource(Enum):
    """Available microstructure data sources."""
    COINAPI_WSDS = "coinapi_wsds"
    COINAPI_REST = "coinapi_rest"
    BINANCE_WS = "binance_ws"
    ORDERBOOK_INGESTOR = "orderbook_ingestor"
    CCXT = "ccxt"
    UNIFIED = "unified"
    NONE = "none"


@dataclass
class MicroSnapshot:
    """Unified microstructure snapshot."""
    symbol: str
    source: str
    updated_ts_ms: int = 0
    
    # Prices
    mid_px: float = 0.0
    best_bid_px: float = 0.0
    best_ask_px: float = 0.0
    best_bid_sz: float = 0.0
    best_ask_sz: float = 0.0
    spread: float = 0.0
    microprice: float = 0.0
    
    # Depth
    book_bid_sum_5: float = 0.0
    book_ask_sum_5: float = 0.0
    imbalance_5: float = 0.0
    
    # Derived scores
    churn_score: float = 0.0
    snapback_score: float = 0.0
    spoof_score: float = 0.0
    spoof_score_v1: float = 0.0
    spoof_score_v2: float = 0.0
    p_false_move: float = 0.0
    fast_move_score: float = 0.0
    fast_move_max_1m: float = 0.0  # Rolling max over 1 minute for trainer
    fast_move_max_5m: float = 0.0  # Rolling max over 5 minutes for trainer
    fast_move_max_15m: float = 0.0  # Rolling max over 15 minutes for trainer

    # Tape / executed flow (optional; 0 when trade feed disabled)
    trade_total_notional_1s: float = 0.0
    trade_imbalance_1s: float = 0.0
    impact_bps_1s: float = 0.0
    impact_per_musd_1s: float = 0.0
    
    # Quality
    src_quality_score: float = 0.0
    src_staleness_ms: int = 0
    is_healthy: bool = True
    health_reason: str = ""
    
    @classmethod
    def from_redis_hash(cls, symbol: str, data: Dict[str, str]) -> 'MicroSnapshot':
        """Create from Redis hash data."""
        now_ms = int(time.time() * 1000)
        
        updated_ts = int(float(data.get('updated_ts_ms', 0) or 0))
        staleness = now_ms - updated_ts if updated_ts > 0 else 999999
        
        snapshot = cls(
            symbol=symbol,
            source=data.get('source', 'unknown'),
            updated_ts_ms=updated_ts,
            mid_px=float(data.get('mid_px', 0) or 0),
            best_bid_px=float(data.get('best_bid_px', 0) or 0),
            best_ask_px=float(data.get('best_ask_px', 0) or 0),
            best_bid_sz=float(data.get('best_bid_sz', 0) or 0),
            best_ask_sz=float(data.get('best_ask_sz', 0) or 0),
            spread=float(data.get('spread', 0) or 0),
            microprice=float(data.get('microprice', 0) or 0),
            book_bid_sum_5=float(data.get('book_bid_sum_5', 0) or 0),
            book_ask_sum_5=float(data.get('book_ask_sum_5', 0) or 0),
            imbalance_5=float(data.get('imbalance_5', 0) or 0),
            churn_score=float(data.get('churn_score', 0) or 0),
            snapback_score=float(data.get('snapback_score', 0) or 0),
            spoof_score=float(data.get('spoof_score', 0) or 0),
            spoof_score_v1=float(data.get('spoof_score_v1', 0) or 0),
            spoof_score_v2=float(data.get('spoof_score_v2', 0) or 0),
            p_false_move=float(data.get('p_false_move', 0) or 0),
            fast_move_score=float(data.get('fast_move_score', 0) or 0),
            fast_move_max_1m=float(data.get('fast_move_max_1m', 0) or 0),
            fast_move_max_5m=float(data.get('fast_move_max_5m', 0) or 0),
            fast_move_max_15m=float(data.get('fast_move_max_15m', 0) or 0),
            trade_total_notional_1s=float(data.get('trade_total_notional_1s', 0) or 0),
            trade_imbalance_1s=float(data.get('trade_imbalance_1s', 0) or 0),
            impact_bps_1s=float(data.get('impact_bps_1s', 0) or 0),
            impact_per_musd_1s=float(data.get('impact_per_musd_1s', 0) or 0),
            src_quality_score=float(data.get('src_quality_score', 0) or 0),
            src_staleness_ms=staleness,
        )
        
        # Determine health
        if staleness > 10000:  # 10 seconds
            snapshot.is_healthy = False
            snapshot.health_reason = f"Stale: {staleness}ms"
        elif snapshot.best_bid_px <= 0 or snapshot.best_ask_px <= 0:
            snapshot.is_healthy = False
            snapshot.health_reason = "Missing prices"
        
        return snapshot
    
    def to_feature_dict(self) -> Dict[str, float]:
        """Convert to feature dict for trainer."""
        return {
            'micro_mid_px': self.mid_px,
            'micro_spread': self.spread,
            'micro_microprice': self.microprice,
            'micro_imbalance_5': self.imbalance_5,
            'micro_churn_score': self.churn_score,
            'micro_snapback_score': self.snapback_score,
            'micro_spoof_score': self.spoof_score,
            'micro_spoof_score_v2': self.spoof_score_v2 or self.spoof_score,
            'micro_p_false_move': self.p_false_move,
            'micro_fast_move_score': self.fast_move_score,
            'micro_trade_total_notional_1s': self.trade_total_notional_1s,
            'micro_trade_imbalance_1s': self.trade_imbalance_1s,
            'micro_impact_bps_1s': self.impact_bps_1s,
            'micro_impact_per_musd_1s': self.impact_per_musd_1s,
            'micro_staleness_ms': float(self.src_staleness_ms),
            'micro_quality_score': self.src_quality_score,
        }


@dataclass
class SourceConfig:
    """Configuration for a data source."""
    source: MicroSource
    redis_key_pattern: str  # Pattern with {symbol} placeholder
    priority: int  # Lower = higher priority
    max_staleness_ms: int  # Maximum acceptable staleness
    quality_multiplier: float  # Quality score multiplier (1.0 = best)


class MicrostructureSourceRouter:
    """
    Routes microstructure data from the best available source.
    
    Selection criteria:
    1. Lowest staleness (freshness)
    2. Completeness (required fields present)
    3. Source priority (coinapi_wsds > coinapi_rest > binance_ws > ccxt)
    """
    
    # Source configurations
    SOURCES = [
        SourceConfig(
            source=MicroSource.COINAPI_WSDS,
            redis_key_pattern="msnap:coinapi_wsds:{symbol}",
            priority=1,
            max_staleness_ms=1500,
            quality_multiplier=1.0,
        ),
        SourceConfig(
            source=MicroSource.COINAPI_REST,
            redis_key_pattern="msnap:coinapi_rest:{symbol}",
            priority=2,
            max_staleness_ms=5000,
            quality_multiplier=0.8,
        ),
        SourceConfig(
            source=MicroSource.BINANCE_WS,
            redis_key_pattern="orderbook:top:{symbol}",
            priority=3,
            max_staleness_ms=3000,
            quality_multiplier=0.9,
        ),
        SourceConfig(
            source=MicroSource.UNIFIED,
            redis_key_pattern="unified_features:{symbol}:5m",
            priority=4,
            max_staleness_ms=10000,
            quality_multiplier=0.6,
        ),
    ]
    
    # Required fields for a healthy snapshot
    REQUIRED_FIELDS = {'best_bid_px', 'best_ask_px', 'updated_ts_ms'}
    
    def __init__(self, redis_client: Any = None):
        self.redis = redis_client
        
        # Cache of last selected source per symbol
        self._source_cache: Dict[str, Tuple[MicroSource, float]] = {}  # symbol -> (source, ts)
        self._source_cache_ttl_sec = 5.0
        
        # Metrics
        self._source_hits: Dict[str, int] = {s.source.value: 0 for s in self.SOURCES}
        self._last_log_ts: float = 0
        
        logger.info("MicrostructureSourceRouter initialized")
    
    def _parse_redis_hash(self, key: str) -> Optional[Dict[str, str]]:
        """Parse Redis key to dict.

        Supports:
        - HASH (hgetall)  (msnap:* ingestors)
        - STRING JSON (orderbook:top:* from Binance orderbook ingestor)
        """
        if self.redis is None:
            return None
        try:
            raw = self.redis.hgetall(key)
            if raw:
                data: Dict[str, str] = {}
                for k, v in raw.items():
                    k_str = k.decode('utf-8') if isinstance(k, bytes) else k
                    v_str = v.decode('utf-8') if isinstance(v, bytes) else v
                    data[k_str] = v_str
                return data

            # Fallback: JSON string
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
                    return {str(k): str(v) for k, v in obj.items()}
            return None
        except Exception as e:
            logger.debug(f"[MICRO_ROUTER] Error reading {key}: {e}")
            return None
    
    def _convert_binance_to_msnap(self, data: Dict[str, str], symbol: str) -> Dict[str, str]:
        """Convert Binance orderbook format to msnap format."""
        now_ms = int(time.time() * 1000)
        
        best_bid = float(data.get('bid', 0) or data.get('bid_price', 0) or 0)
        best_ask = float(data.get('ask', 0) or data.get('ask_price', 0) or 0)
        best_bid_sz = float(
            data.get('best_bid_sz', 0) or
            data.get('bid_qty', 0) or
            data.get('bid_size', 0) or 0
        )
        best_ask_sz = float(
            data.get('best_ask_sz', 0) or
            data.get('ask_qty', 0) or
            data.get('ask_size', 0) or 0
        )
        
        mid_px = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else 0
        spread = (best_ask - best_bid) / mid_px * 10000 if mid_px > 0 else 0
        
        total_sz = best_bid_sz + best_ask_sz
        microprice = mid_px
        if total_sz > 0:
            microprice = (best_bid * best_ask_sz + best_ask * best_bid_sz) / total_sz
        
        imbalance = 0
        if total_sz > 0:
            imbalance = (best_bid_sz - best_ask_sz) / total_sz
        
        # Support multiple timestamp field names (orderbook workers often use ts/ts_ms)
        updated_ts = (
            data.get('updated_ts_ms', 0) or
            data.get('updated_ts', 0) or
            data.get('ts_ms', 0) or
            data.get('ts', 0) or
            data.get('timestamp', 0)
        )
        if updated_ts:
            ts_val = float(updated_ts)
            if ts_val < 1e12:
                ts_val = ts_val * 1000
            updated_ts_ms = int(ts_val)
        else:
            updated_ts_ms = now_ms

        # Depth sums (prefer top-5 sums if present)
        book_bid_sum_5 = float(data.get("book_bid_sum_5", 0) or 0)
        book_ask_sum_5 = float(data.get("book_ask_sum_5", 0) or 0)
        if book_bid_sum_5 <= 0:
            book_bid_sum_5 = best_bid_sz
        if book_ask_sum_5 <= 0:
            book_ask_sum_5 = best_ask_sz

        imb = 0.0
        tot5 = book_bid_sum_5 + book_ask_sum_5
        if tot5 > 0:
            imb = (book_bid_sum_5 - book_ask_sum_5) / tot5
        
        return {
            'source': 'binance_ws',
            'updated_ts_ms': str(updated_ts_ms),
            'mid_px': str(mid_px),
            'best_bid_px': str(best_bid),
            'best_ask_px': str(best_ask),
            'best_bid_sz': str(best_bid_sz),
            'best_ask_sz': str(best_ask_sz),
            'spread': str(spread),
            'microprice': str(microprice),
            'book_bid_sum_5': str(book_bid_sum_5),
            'book_ask_sum_5': str(book_ask_sum_5),
            'imbalance_5': str(imb),
            'churn_score': '0',
            'snapback_score': '0',
            'spoof_score': '0',
            'fast_move_score': '0',
            'src_quality_score': '0.9',
            'src_staleness_ms': '0',
        }
    
    def _convert_unified_to_msnap(self, data: Dict[str, str], symbol: str) -> Dict[str, str]:
        """Convert unified features format to msnap format."""
        now_ms = int(time.time() * 1000)
        
        best_bid = float(data.get('ob_bid_price', 0) or 0)
        best_ask = float(data.get('ob_ask_price', 0) or 0)
        best_bid_sz = float(data.get('ob_bid_depth', 0) or 0)
        best_ask_sz = float(data.get('ob_ask_depth', 0) or 0)
        spread = float(data.get('ob_spread', 0) or 0)
        imbalance = float(data.get('ob_imbalance', 0) or 0)
        
        mid_px = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else 0
        
        updated_ts = data.get('updated_ts', 0) or data.get('timestamp', 0)
        if updated_ts:
            ts_val = float(updated_ts)
            if ts_val < 1e12:
                ts_val = ts_val * 1000
            updated_ts_ms = int(ts_val)
        else:
            updated_ts_ms = now_ms
        
        return {
            'source': 'unified',
            'updated_ts_ms': str(updated_ts_ms),
            'mid_px': str(mid_px),
            'best_bid_px': str(best_bid),
            'best_ask_px': str(best_ask),
            'best_bid_sz': str(best_bid_sz),
            'best_ask_sz': str(best_ask_sz),
            'spread': str(spread),
            'microprice': str(mid_px),
            'book_bid_sum_5': str(best_bid_sz),
            'book_ask_sum_5': str(best_ask_sz),
            'imbalance_5': str(imbalance),
            'churn_score': '0',
            'snapback_score': '0',
            'spoof_score': '0',
            'fast_move_score': '0',
            'src_quality_score': '0.6',
            'src_staleness_ms': '0',
        }
    
    def _fetch_from_source(self, config: SourceConfig, symbol: str) -> Optional[Dict[str, str]]:
        """Fetch data from a specific source."""
        key = config.redis_key_pattern.format(symbol=symbol)
        data = self._parse_redis_hash(key)
        
        if not data:
            return None
        
        # Convert to standard msnap format if needed
        if config.source == MicroSource.BINANCE_WS:
            return self._convert_binance_to_msnap(data, symbol)
        elif config.source == MicroSource.UNIFIED:
            return self._convert_unified_to_msnap(data, symbol)
        
        return data
    
    def _score_snapshot(self, snapshot: MicroSnapshot, config: SourceConfig) -> float:
        """Score a snapshot for ranking."""
        # Base score from priority (lower priority = higher score)
        base_score = (10 - config.priority) * 10
        
        # Freshness score
        if snapshot.src_staleness_ms <= config.max_staleness_ms:
            freshness = 1.0 - (snapshot.src_staleness_ms / config.max_staleness_ms)
        else:
            freshness = 0.0
        
        # Completeness score
        completeness = 1.0 if snapshot.is_healthy else 0.5
        
        # Quality multiplier
        quality = config.quality_multiplier
        
        return base_score * freshness * completeness * quality
    
    def get_best_snapshot(self, symbol: str) -> Tuple[Optional[MicroSnapshot], MicroSource]:
        """
        Get the best available microstructure snapshot for a symbol.
        
        Returns:
            (snapshot, source) - snapshot may be None if no data available
        """
        candidates = []
        
        for config in self.SOURCES:
            data = self._fetch_from_source(config, symbol)
            if not data:
                continue
            
            snapshot = MicroSnapshot.from_redis_hash(symbol, data)
            
            # Skip if too stale
            if snapshot.src_staleness_ms > config.max_staleness_ms * 2:
                continue
            
            # Skip if missing required fields
            if not snapshot.is_healthy and snapshot.best_bid_px <= 0:
                continue
            
            score = self._score_snapshot(snapshot, config)
            candidates.append((score, snapshot, config.source))
        
        if not candidates:
            return None, MicroSource.NONE
        
        # Sort by score (descending)
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_score, best_snapshot, best_source = candidates[0]
        
        # Update metrics
        self._source_hits[best_source.value] = self._source_hits.get(best_source.value, 0) + 1
        
        return best_snapshot, best_source
    
    def get_snapshot_or_default(self, symbol: str) -> MicroSnapshot:
        """
        Get snapshot with default values if not available.
        
        Always returns a valid MicroSnapshot (may have is_healthy=False).
        """
        snapshot, source = self.get_best_snapshot(symbol)
        
        if snapshot is None:
            snapshot = MicroSnapshot(
                symbol=symbol,
                source='none',
                is_healthy=False,
                health_reason='No data available',
            )
        
        return snapshot
    
    def get_feature_vector(self, symbol: str) -> Dict[str, float]:
        """
        Get microstructure features for trainer feature pipeline.
        
        Returns a dict of feature_name -> value, with defaults for missing data.
        """
        snapshot = self.get_snapshot_or_default(symbol)
        features = snapshot.to_feature_dict()
        features['micro_is_healthy'] = 1.0 if snapshot.is_healthy else 0.0
        return features
    
    def get_health_report(self, symbols: List[str]) -> Dict[str, Any]:
        """Get health report for all symbols."""
        report = {
            'timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
            'symbols': {},
            'source_distribution': {},
            'unhealthy_count': 0,
        }
        
        source_counts = {s.value: 0 for s in MicroSource}
        
        for symbol in symbols:
            snapshot, source = self.get_best_snapshot(symbol)
            
            if snapshot:
                report['symbols'][symbol] = {
                    'source': source.value,
                    'staleness_ms': snapshot.src_staleness_ms,
                    'is_healthy': snapshot.is_healthy,
                    'quality_score': snapshot.src_quality_score,
                }
                source_counts[source.value] += 1
                if not snapshot.is_healthy:
                    report['unhealthy_count'] += 1
            else:
                report['symbols'][symbol] = {
                    'source': 'none',
                    'staleness_ms': -1,
                    'is_healthy': False,
                    'quality_score': 0,
                }
                report['unhealthy_count'] += 1
                source_counts['none'] += 1
        
        report['source_distribution'] = source_counts
        return report
    
    def log_health_summary(self, symbols: List[str]):
        """Log health summary periodically."""
        now = time.time()
        if now - self._last_log_ts < 60:  # Once per minute
            return
        
        self._last_log_ts = now
        report = self.get_health_report(symbols)
        
        total = len(symbols)
        healthy = total - report['unhealthy_count']
        
        source_str = ", ".join(f"{k}={v}" for k, v in report['source_distribution'].items() if v > 0)
        
        logger.info(
            f"MICRO_ROUTER_HEALTH | healthy={healthy}/{total} | sources=[{source_str}]"
        )


# Global instance
_source_router: Optional[MicrostructureSourceRouter] = None


def get_source_router(redis_client: Any = None, force_new: bool = False) -> MicrostructureSourceRouter:
    """Get global source router instance."""
    global _source_router
    if _source_router is None or force_new:
        _source_router = MicrostructureSourceRouter(redis_client=redis_client)
    elif redis_client is not None and _source_router.redis is None:
        _source_router.redis = redis_client
    return _source_router


def get_best_msnap(symbol: str, redis_client: Any = None) -> Tuple[Optional[MicroSnapshot], MicroSource]:
    """Convenience function to get best snapshot."""
    router = get_source_router(redis_client)
    return router.get_best_snapshot(symbol)

