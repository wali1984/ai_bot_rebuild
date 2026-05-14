# -*- coding: utf-8 -*-
"""
Microstructure TF Aggregator
============================
Aggregates CoinAPI microstructure data (order book, trades) into timeframe-aligned features.

This module:
1. Consumes msnap (market snapshot) data from Redis
2. Maintains rolling windows for 1m/5m/15m/1h timeframes
3. Emits aggregated microstructure features per TF

Feature flags:
- ENABLE_MICROSTRUCTURE_TF_AGG: Enable/disable aggregation
- ENABLE_MICROSTRUCTURE_FEATURES_IN_OBS: Include in observation tensor
"""

import os
import time
import json
import logging
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from collections import deque
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MicroAggregate:
    """Aggregated microstructure features for a specific timeframe."""
    symbol: str
    timeframe: str
    timestamp_ms: int = 0
    samples: int = 0
    
    # Spread metrics
    spread_mean: float = 0.0
    spread_p95: float = 0.0
    spread_trend: float = 0.0  # Positive = widening
    
    # Order book imbalance
    imbalance_mean: float = 0.0
    imbalance_std: float = 0.0
    imbalance_flip_rate: float = 0.0  # How often imbalance flips sign
    
    # Trade flow
    trade_imbalance: float = 0.0  # (buy_vol - sell_vol) / total_vol
    buy_flow: float = 0.0
    sell_flow: float = 0.0
    flow_impulse: float = 0.0  # Sudden flow spikes
    
    # Manipulation detection
    cancel_ratio_top: float = 0.0  # Cancel ratio in top levels
    refill_velocity: float = 0.0  # How fast orders refill after execution
    pressure_persistence: float = 0.0  # How long pressure lasts
    
    # Volatility proxies
    microprice_jump_max: float = 0.0
    rv_1m: float = 0.0  # Realized volatility (1 min)
    rv_5m: float = 0.0  # Realized volatility (5 min)
    
    # Spoof/Fast-move scores
    spoof_score_max: float = 0.0
    spoof_score_mean: float = 0.0
    fast_move_score_max: float = 0.0
    fast_move_score_mean: float = 0.0
    
    # Data quality
    staleness_ms: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    def to_feature_vector(self) -> np.ndarray:
        """Convert to feature vector for observation tensor."""
        return np.array([
            self.spread_mean,
            self.spread_p95,
            self.spread_trend,
            self.imbalance_mean,
            self.imbalance_std,
            self.imbalance_flip_rate,
            self.trade_imbalance,
            self.flow_impulse,
            self.cancel_ratio_top,
            self.refill_velocity,
            self.pressure_persistence,
            self.microprice_jump_max,
            self.rv_1m,
            self.rv_5m,
            self.spoof_score_max,
            self.spoof_score_mean,
            self.fast_move_score_max,
            self.fast_move_score_mean,
        ], dtype=np.float32)


@dataclass
class MSnapSample:
    """Single market snapshot sample."""
    timestamp_ms: int
    bid: float
    ask: float
    spread: float
    mid: float
    microprice: float
    imbalance: float
    bid_depth: float
    ask_depth: float
    spoof_score: float = 0.0
    fast_move_score: float = 0.0
    buy_volume: float = 0.0
    sell_volume: float = 0.0


class MicrostructureAggregator:
    """
    Aggregates microstructure data into timeframe-aligned features.
    
    Architecture:
    - Consumes msnap data from Redis (msnap:coinapi_wsds:{symbol} or msnap:{symbol})
    - Maintains rolling windows per symbol per timeframe
    - Periodically computes and publishes aggregates to Redis
    """
    
    TF_WINDOWS_SEC = {
        '1m': 60,
        '5m': 300,
        '15m': 900,
        '1h': 3600,
    }
    
    def __init__(self, redis_client=None, symbols: List[str] = None):
        self.redis = redis_client
        self.symbols = symbols or []
        
        # Rolling windows: {symbol: {tf: deque of MSnapSample}}
        self._windows: Dict[str, Dict[str, deque]] = {}
        
        # Latest aggregates: {symbol: {tf: MicroAggregate}}
        self._aggregates: Dict[str, Dict[str, MicroAggregate]] = {}
        
        # Background thread for periodic aggregation
        self._running = False
        self._thread: Optional[threading.Thread] = None
        
        # Stats
        self._samples_processed = 0
        self._last_aggregate_ts = 0
        
        self._init_windows()
        logger.info(f"[MICRO_AGG] Initialized for {len(self.symbols)} symbols")
    
    def _init_windows(self):
        """Initialize rolling windows for all symbols and timeframes."""
        for symbol in self.symbols:
            self._windows[symbol] = {}
            self._aggregates[symbol] = {}
            for tf in self.TF_WINDOWS_SEC.keys():
                # Max samples based on 1-second cadence
                max_samples = self.TF_WINDOWS_SEC[tf] * 2  # 2x buffer
                self._windows[symbol][tf] = deque(maxlen=max_samples)
                self._aggregates[symbol][tf] = MicroAggregate(symbol=symbol, timeframe=tf)
    
    def add_sample(self, symbol: str, sample: MSnapSample):
        """Add a new market snapshot sample."""
        if symbol not in self._windows:
            self._init_symbol(symbol)
        
        # Add to all TF windows (they filter by time internally)
        for tf in self.TF_WINDOWS_SEC.keys():
            self._windows[symbol][tf].append(sample)
        
        self._samples_processed += 1
    
    def _init_symbol(self, symbol: str):
        """Initialize windows for a new symbol."""
        self._windows[symbol] = {}
        self._aggregates[symbol] = {}
        for tf in self.TF_WINDOWS_SEC.keys():
            max_samples = self.TF_WINDOWS_SEC[tf] * 2
            self._windows[symbol][tf] = deque(maxlen=max_samples)
            self._aggregates[symbol][tf] = MicroAggregate(symbol=symbol, timeframe=tf)
    
    def parse_msnap(self, msnap_data: Dict[str, Any]) -> Optional[MSnapSample]:
        """Parse msnap data into a sample."""
        try:
            ts_ms = int(msnap_data.get('ts_ms') or msnap_data.get('timestamp_ms') or time.time() * 1000)
            bid = float(msnap_data.get('bid', 0) or msnap_data.get('best_bid', 0) or 0)
            ask = float(msnap_data.get('ask', 0) or msnap_data.get('best_ask', 0) or 0)
            
            if bid <= 0 or ask <= 0:
                return None
            
            mid = (bid + ask) / 2
            spread = ask - bid
            
            # Parse depths
            bid_depth = float(msnap_data.get('bid_depth', 0) or msnap_data.get('bid_qty', 0) or 0)
            ask_depth = float(msnap_data.get('ask_depth', 0) or msnap_data.get('ask_qty', 0) or 0)
            
            # Compute imbalance and microprice
            total_depth = bid_depth + ask_depth
            if total_depth > 0:
                imbalance = (bid_depth - ask_depth) / total_depth
                microprice = (bid * ask_depth + ask * bid_depth) / total_depth
            else:
                imbalance = 0.0
                microprice = mid
            
            # Parse scores from microstructure overlay if present
            spoof_score = float(msnap_data.get('spoof_score', 0) or 0)
            fast_move_score = float(msnap_data.get('fast_move_score', 0) or 0)
            
            # Parse volumes
            # Trade flow is optional. Prefer notional windows from msnap when present.
            buy_volume = float(
                msnap_data.get('buy_volume', 0) or
                msnap_data.get('buy_flow', 0) or
                msnap_data.get('trade_buy_notional_5s', 0) or
                msnap_data.get('trade_buy_notional_1s', 0) or 0
            )
            sell_volume = float(
                msnap_data.get('sell_volume', 0) or
                msnap_data.get('sell_flow', 0) or
                msnap_data.get('trade_sell_notional_5s', 0) or
                msnap_data.get('trade_sell_notional_1s', 0) or 0
            )
            
            return MSnapSample(
                timestamp_ms=ts_ms,
                bid=bid,
                ask=ask,
                spread=spread,
                mid=mid,
                microprice=microprice,
                imbalance=imbalance,
                bid_depth=bid_depth,
                ask_depth=ask_depth,
                spoof_score=spoof_score,
                fast_move_score=fast_move_score,
                buy_volume=buy_volume,
                sell_volume=sell_volume,
            )
        except Exception as e:
            logger.debug(f"[MICRO_AGG] Failed to parse msnap: {e}")
            return None
    
    def compute_aggregate(self, symbol: str, tf: str) -> MicroAggregate:
        """Compute aggregate features for a symbol/timeframe."""
        window = self._windows.get(symbol, {}).get(tf, deque())
        now_ms = int(time.time() * 1000)
        window_ms = self.TF_WINDOWS_SEC[tf] * 1000
        cutoff_ms = now_ms - window_ms
        
        # Filter samples within the window
        samples = [s for s in window if s.timestamp_ms >= cutoff_ms]
        
        agg = MicroAggregate(symbol=symbol, timeframe=tf, timestamp_ms=now_ms)
        
        if not samples:
            agg.staleness_ms = window_ms
            return agg
        
        agg.samples = len(samples)
        agg.staleness_ms = now_ms - samples[-1].timestamp_ms
        
        # Spread metrics
        spreads = [s.spread for s in samples]
        agg.spread_mean = np.mean(spreads)
        agg.spread_p95 = np.percentile(spreads, 95) if len(spreads) > 1 else spreads[0]
        if len(spreads) >= 2:
            agg.spread_trend = (spreads[-1] - spreads[0]) / max(spreads[0], 1e-9)
        
        # Imbalance metrics
        imbalances = [s.imbalance for s in samples]
        agg.imbalance_mean = np.mean(imbalances)
        agg.imbalance_std = np.std(imbalances) if len(imbalances) > 1 else 0.0
        # Flip rate: count sign changes
        if len(imbalances) >= 2:
            flips = sum(1 for i in range(1, len(imbalances)) 
                       if imbalances[i] * imbalances[i-1] < 0)
            agg.imbalance_flip_rate = flips / (len(imbalances) - 1)
        
        # Trade flow
        total_buy = sum(s.buy_volume for s in samples)
        total_sell = sum(s.sell_volume for s in samples)
        agg.buy_flow = total_buy
        agg.sell_flow = total_sell
        if total_buy + total_sell > 0:
            agg.trade_imbalance = (total_buy - total_sell) / (total_buy + total_sell)
        
        # Flow impulse: max flow in any 5-second window
        if len(samples) >= 5:
            window_flows = []
            for i in range(len(samples) - 4):
                window_flow = sum(s.buy_volume + s.sell_volume for s in samples[i:i+5])
                window_flows.append(window_flow)
            if window_flows:
                avg_flow = np.mean(window_flows)
                agg.flow_impulse = max(window_flows) / max(avg_flow, 1e-9) - 1.0
        
        # Microprice jumps
        if len(samples) >= 2:
            microprices = [s.microprice for s in samples]
            jumps = [abs(microprices[i] - microprices[i-1]) / max(microprices[i-1], 1e-9) 
                    for i in range(1, len(microprices))]
            agg.microprice_jump_max = max(jumps) if jumps else 0.0
            
            # Realized volatility (annualized)
            returns = [np.log(microprices[i] / microprices[i-1]) 
                      for i in range(1, len(microprices)) if microprices[i-1] > 0]
            if returns:
                rv = np.std(returns) * np.sqrt(len(returns))
                if tf == '1m':
                    agg.rv_1m = rv
                elif tf == '5m':
                    agg.rv_5m = rv
        
        # Spoof/Fast-move scores
        spoof_scores = [s.spoof_score for s in samples if s.spoof_score > 0]
        if spoof_scores:
            agg.spoof_score_max = max(spoof_scores)
            agg.spoof_score_mean = np.mean(spoof_scores)
        
        fast_move_scores = [s.fast_move_score for s in samples if s.fast_move_score > 0]
        if fast_move_scores:
            agg.fast_move_score_max = max(fast_move_scores)
            agg.fast_move_score_mean = np.mean(fast_move_scores)
        
        # Cache the aggregate
        self._aggregates[symbol][tf] = agg
        
        return agg
    
    def get_aggregate(self, symbol: str, tf: str) -> Optional[MicroAggregate]:
        """Get the latest aggregate for a symbol/timeframe."""
        return self._aggregates.get(symbol, {}).get(tf)
    
    def publish_aggregates_to_redis(self):
        """Publish all aggregates to Redis."""
        if not self.redis:
            return
        
        for symbol in self.symbols:
            for tf in self.TF_WINDOWS_SEC.keys():
                agg = self.compute_aggregate(symbol, tf)
                key = f"microfeat:{symbol}:{tf}"
                try:
                    self.redis.hset(key, mapping={
                        k: str(v) if not isinstance(v, (int, float)) else v 
                        for k, v in agg.to_dict().items()
                    })
                    self.redis.expire(key, self.TF_WINDOWS_SEC[tf] * 2)
                except Exception as e:
                    logger.debug(f"[MICRO_AGG] Failed to publish {key}: {e}")
        
        self._last_aggregate_ts = time.time()
    
    def consume_msnap_stream(self, timeout_ms: int = 1000) -> int:
        """Consume msnap data from Redis streams."""
        if not self.redis:
            return 0
        
        consumed = 0
        for symbol in self.symbols:
            # Try CoinAPI WSDS first, then fallback
            keys_to_try = [
                f"msnap:coinapi_wsds:{symbol}",
                f"msnap:{symbol}",
            ]
            
            for key in keys_to_try:
                try:
                    data = self.redis.hgetall(key)
                    if data:
                        # Parse and add sample
                        parsed = {k.decode() if isinstance(k, bytes) else k: 
                                 v.decode() if isinstance(v, bytes) else v 
                                 for k, v in data.items()}
                        sample = self.parse_msnap(parsed)
                        if sample:
                            self.add_sample(symbol, sample)
                            consumed += 1
                        break
                except Exception as e:
                    logger.debug(f"[MICRO_AGG] Failed to read {key}: {e}")
        
        return consumed
    
    def start_background_aggregation(self, interval_sec: float = 5.0):
        """Start background thread for periodic aggregation."""
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(
            target=self._aggregation_loop,
            args=(interval_sec,),
            daemon=True
        )
        self._thread.start()
        logger.info(f"[MICRO_AGG] Background aggregation started (interval={interval_sec}s)")
    
    def stop(self):
        """Stop background aggregation."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        logger.info("[MICRO_AGG] Stopped")
    
    def _aggregation_loop(self, interval_sec: float):
        """Background aggregation loop."""
        while self._running:
            try:
                # Consume latest msnap data
                consumed = self.consume_msnap_stream()
                
                # Compute and publish aggregates
                self.publish_aggregates_to_redis()
                
                if consumed > 0:
                    logger.debug(f"[MICRO_AGG] Processed {consumed} samples, total={self._samples_processed}")
                
            except Exception as e:
                logger.error(f"[MICRO_AGG] Aggregation loop error: {e}")
            
            time.sleep(interval_sec)


# Singleton instance
_aggregator_instance: Optional[MicrostructureAggregator] = None
_aggregator_lock = threading.Lock()


def get_microstructure_aggregator(redis_client=None, symbols: List[str] = None) -> Optional[MicrostructureAggregator]:
    """Get or create the microstructure aggregator singleton."""
    global _aggregator_instance
    
    from config import ENABLE_MICROSTRUCTURE_TF_AGG
    if not ENABLE_MICROSTRUCTURE_TF_AGG:
        return None
    
    with _aggregator_lock:
        if _aggregator_instance is None:
            if symbols is None:
                # Dynamic symbol loading - supports hot-reload without restart
                try:
                    from utils.symbol_manager import get_symbols_cached
                    symbols = get_symbols_cached()
                except ImportError:
                from config import SYMBOLS
                symbols = SYMBOLS
            _aggregator_instance = MicrostructureAggregator(
                redis_client=redis_client,
                symbols=symbols
            )
        return _aggregator_instance


def start_aggregator_if_enabled(redis_client=None, symbols: List[str] = None) -> Optional[MicrostructureAggregator]:
    """Start the aggregator if enabled."""
    agg = get_microstructure_aggregator(redis_client, symbols)
    if agg:
        agg.start_background_aggregation()
    return agg

