"""
Microstructure Features for Sub-Minute Trading

Provides real-time microstructure features for detecting:
- Squeeze/pump patterns
- Rapid reversals
- Orderbook imbalances
- Liquidation bursts
- Volume spikes

These features update on tick/5s intervals, NOT candle closes.
Critical for sub-minute reaction times.
"""

import time
import logging
import numpy as np
import threading
from collections import deque
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class MicroBar:
    """5-second micro bar for high-frequency features"""
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    trade_count: int = 0
    
    @property
    def range_pct(self) -> float:
        if self.open == 0:
            return 0.0
        return (self.high - self.low) / self.open * 100
    
    @property
    def body_pct(self) -> float:
        if self.open == 0:
            return 0.0
        return (self.close - self.open) / self.open * 100
    
    @property
    def wick_ratio(self) -> float:
        """How much of the range is wick vs body"""
        total_range = self.high - self.low
        if total_range == 0:
            return 0.0
        body = abs(self.close - self.open)
        return 1.0 - (body / total_range)


@dataclass 
class MicrostructureState:
    """Current microstructure state for a symbol"""
    symbol: str
    last_update: float = 0.0
    
    # Price momentum (returns)
    ret_5s: float = 0.0
    ret_15s: float = 0.0
    ret_30s: float = 0.0
    ret_60s: float = 0.0
    
    # Acceleration (change in return)
    accel_5s: float = 0.0
    accel_15s: float = 0.0
    
    # Volatility
    volatility_30s: float = 0.0
    volatility_60s: float = 0.0
    range_60s: float = 0.0
    
    # Price structure
    wick_ratio: float = 0.0
    body_pct: float = 0.0
    
    # Orderbook
    bid_depth: float = 0.0
    ask_depth: float = 0.0
    orderbook_imbalance: float = 0.0  # -1 to +1 (negative = more asks/bearish)
    spread_bps: float = 0.0
    
    # Volume/trade flow
    volume_delta_5s: float = 0.0
    volume_delta_15s: float = 0.0
    trade_burst_count: int = 0
    buy_sell_ratio: float = 0.5  # 0-1 (0.5 = balanced)
    
    # Liquidation
    liq_burst_long_usd: float = 0.0
    liq_burst_short_usd: float = 0.0
    liq_distance_long_pct: float = 0.0
    liq_distance_short_pct: float = 0.0
    
    # Squeeze detection
    is_squeeze: bool = False
    squeeze_direction: int = 0  # -1, 0, +1
    squeeze_magnitude: float = 0.0
    
    def to_feature_vector(self) -> List[float]:
        """Convert to 30-dim feature vector for model input"""
        return [
            # Returns (4)
            self.ret_5s,
            self.ret_15s,
            self.ret_30s,
            self.ret_60s,
            # Acceleration (2)
            self.accel_5s,
            self.accel_15s,
            # Volatility (3)
            self.volatility_30s,
            self.volatility_60s,
            self.range_60s,
            # Price structure (2)
            self.wick_ratio,
            self.body_pct,
            # Orderbook (4)
            self.bid_depth / 1e6 if self.bid_depth else 0.0,  # Normalize to millions
            self.ask_depth / 1e6 if self.ask_depth else 0.0,
            self.orderbook_imbalance,
            self.spread_bps / 100.0,  # Normalize
            # Volume (4)
            self.volume_delta_5s,
            self.volume_delta_15s,
            float(self.trade_burst_count) / 100.0,  # Normalize
            self.buy_sell_ratio,
            # Liquidation (4)
            self.liq_burst_long_usd / 1e6,
            self.liq_burst_short_usd / 1e6,
            self.liq_distance_long_pct / 10.0,  # Normalize
            self.liq_distance_short_pct / 10.0,
            # Squeeze (3)
            float(self.is_squeeze),
            float(self.squeeze_direction),
            self.squeeze_magnitude,
            # Padding (4 for alignment to 30)
            0.0, 0.0, 0.0, 0.0
        ]


class MicrostructureFeatureExtractor:
    """
    Real-time microstructure feature extraction.
    
    Updates on:
    - Trades (via trade stream)
    - Orderbook updates (via depth stream)
    - Liquidations (via Redis)
    
    Features computed every 5 seconds for immediate reaction.
    """
    
    def __init__(
        self,
        symbols: List[str],
        redis_client=None,
        update_interval_ms: int = 5000,  # 5 second micro-bars
        lookback_bars: int = 60,  # 5 minutes of history
    ):
        self.symbols = symbols
        self.redis = redis_client
        self.update_interval_ms = update_interval_ms
        self.lookback_bars = lookback_bars
        
        # Per-symbol state
        self.states: Dict[str, MicrostructureState] = {
            s: MicrostructureState(symbol=s) for s in symbols
        }
        
        # Micro-bar history per symbol
        self.micro_bars: Dict[str, deque] = {
            s: deque(maxlen=lookback_bars) for s in symbols
        }
        
        # Trade accumulator for current micro-bar
        self._current_bar: Dict[str, MicroBar] = {}
        self._bar_start_time: Dict[str, float] = {}
        
        # Orderbook snapshots
        self._orderbook: Dict[str, Dict] = {}
        
        # Liquidation tracker
        self._liq_bursts: Dict[str, Dict] = {}
        
        # Background updater
        self._stop_event = threading.Event()
        self._update_thread = None
        
        logger.info(f"🔬 MicrostructureFeatureExtractor initialized for {len(symbols)} symbols")
        logger.info(f"   Update interval: {update_interval_ms}ms, Lookback: {lookback_bars} bars")
    
    def start(self):
        """Start background feature update thread"""
        if self._update_thread is not None:
            return
        
        self._stop_event.clear()
        self._update_thread = threading.Thread(target=self._update_loop, daemon=True)
        self._update_thread.start()
        logger.info("🔬 Microstructure feature updater started")
    
    def stop(self):
        """Stop background thread"""
        self._stop_event.set()
        if self._update_thread:
            self._update_thread.join(timeout=2)
        logger.info("🔬 Microstructure feature updater stopped")
    
    def _update_loop(self):
        """Background loop to compute features every interval"""
        while not self._stop_event.is_set():
            try:
                for symbol in self.symbols:
                    self._update_symbol_features(symbol)
            except Exception as e:
                logger.warning(f"Microstructure update error: {e}")
            
            # Sleep for update interval
            self._stop_event.wait(timeout=self.update_interval_ms / 1000.0)
    
    def _update_symbol_features(self, symbol: str):
        """Update all microstructure features for a symbol"""
        state = self.states[symbol]
        bars = self.micro_bars[symbol]
        
        # Get current price from Redis
        current_price = self._get_current_price(symbol)
        if current_price is None or current_price <= 0:
            return
        
        now = time.time()
        
        # Update returns
        if len(bars) >= 1:
            state.ret_5s = (current_price - bars[-1].close) / bars[-1].close * 100
        if len(bars) >= 3:
            state.ret_15s = (current_price - bars[-3].close) / bars[-3].close * 100
        if len(bars) >= 6:
            state.ret_30s = (current_price - bars[-6].close) / bars[-6].close * 100
        if len(bars) >= 12:
            state.ret_60s = (current_price - bars[-12].close) / bars[-12].close * 100
        
        # Update acceleration
        if len(bars) >= 2:
            prev_ret = (bars[-1].close - bars[-2].close) / bars[-2].close * 100 if bars[-2].close > 0 else 0
            state.accel_5s = state.ret_5s - prev_ret
        if len(bars) >= 4:
            prev_ret = (bars[-3].close - bars[-4].close) / bars[-4].close * 100 if bars[-4].close > 0 else 0
            state.accel_15s = state.ret_15s - prev_ret
        
        # Update volatility
        if len(bars) >= 6:
            returns = [(bars[i].close - bars[i-1].close) / bars[i-1].close 
                      for i in range(-5, 0) if bars[i-1].close > 0]
            state.volatility_30s = np.std(returns) * 100 if returns else 0.0
        
        if len(bars) >= 12:
            returns = [(bars[i].close - bars[i-1].close) / bars[i-1].close 
                      for i in range(-11, 0) if bars[i-1].close > 0]
            state.volatility_60s = np.std(returns) * 100 if returns else 0.0
            
            # Range over 60s
            highs = [b.high for b in list(bars)[-12:]]
            lows = [b.low for b in list(bars)[-12:]]
            if highs and lows and min(lows) > 0:
                state.range_60s = (max(highs) - min(lows)) / min(lows) * 100
        
        # Update price structure from latest bar
        if bars:
            latest = bars[-1]
            state.wick_ratio = latest.wick_ratio
            state.body_pct = latest.body_pct
        
        # Update orderbook features
        self._update_orderbook_features(symbol, state)
        
        # Update volume features
        self._update_volume_features(symbol, state, bars)
        
        # Update liquidation features
        self._update_liquidation_features(symbol, state, current_price)
        
        # Detect squeeze
        self._detect_squeeze(symbol, state)
        
        state.last_update = now
    
    def _get_current_price(self, symbol: str) -> Optional[float]:
        """Get current price from Redis"""
        if not self.redis:
            return None
        
        try:
            # Try ticker first
            ticker = self.redis.hget(f"ticker:{symbol}", "last")
            if ticker:
                return float(ticker)
            
            # Fallback to unified features
            price = self.redis.hget(f"unified_features:{symbol}:1m", "ccxt_close")
            if price:
                return float(price)
            
            return None
        except:
            return None
    
    def _update_orderbook_features(self, symbol: str, state: MicrostructureState):
        """Update orderbook-derived features"""
        if not self.redis:
            return
        
        try:
            # Get orderbook snapshot
            ob_key = f"orderbook:top:{symbol}"
            ob_data = self.redis.hgetall(ob_key)
            
            if ob_data:
                state.bid_depth = float(ob_data.get('bid_depth', 0))
                state.ask_depth = float(ob_data.get('ask_depth', 0))
                
                total_depth = state.bid_depth + state.ask_depth
                if total_depth > 0:
                    state.orderbook_imbalance = (state.bid_depth - state.ask_depth) / total_depth
                
                best_bid = float(ob_data.get('best_bid', 0))
                best_ask = float(ob_data.get('best_ask', 0))
                if best_bid > 0:
                    state.spread_bps = (best_ask - best_bid) / best_bid * 10000
        except Exception as e:
            logger.debug(f"Orderbook feature error for {symbol}: {e}")
    
    def _update_volume_features(self, symbol: str, state: MicrostructureState, bars: deque):
        """Update volume-derived features"""
        if len(bars) < 2:
            return
        
        try:
            # Volume delta
            current_vol = bars[-1].volume if bars else 0
            prev_vol = bars[-2].volume if len(bars) >= 2 else current_vol
            
            if prev_vol > 0:
                state.volume_delta_5s = (current_vol - prev_vol) / prev_vol
            
            if len(bars) >= 4:
                prev_vol_15s = bars[-4].volume
                if prev_vol_15s > 0:
                    state.volume_delta_15s = (current_vol - prev_vol_15s) / prev_vol_15s
            
            # Trade burst count (trades in last 15s above average)
            if len(bars) >= 12:
                avg_trades = np.mean([b.trade_count for b in list(bars)[-12:]])
                recent_trades = sum(b.trade_count for b in list(bars)[-3:])
                state.trade_burst_count = max(0, int(recent_trades - avg_trades * 3))
            
            # Buy/sell ratio
            recent_buy = sum(b.buy_volume for b in list(bars)[-3:]) if len(bars) >= 3 else 0
            recent_sell = sum(b.sell_volume for b in list(bars)[-3:]) if len(bars) >= 3 else 0
            total = recent_buy + recent_sell
            state.buy_sell_ratio = recent_buy / total if total > 0 else 0.5
            
        except Exception as e:
            logger.debug(f"Volume feature error for {symbol}: {e}")
    
    def _update_liquidation_features(self, symbol: str, state: MicrostructureState, current_price: float):
        """Update liquidation-derived features"""
        if not self.redis:
            return
        
        try:
            # Get liquidation bursts (last 60s)
            liq_key = f"liq:burst:{symbol}"
            liq_data = self.redis.hgetall(liq_key)
            
            if liq_data:
                state.liq_burst_long_usd = float(liq_data.get('long_usd_60s', 0))
                state.liq_burst_short_usd = float(liq_data.get('short_usd_60s', 0))
            
            # Get nearest liquidation levels
            liq_levels_key = f"liq:levels:{symbol}"
            levels = self.redis.zrangebyscore(liq_levels_key, '-inf', '+inf', withscores=True, start=0, num=10)
            
            if levels and current_price > 0:
                # Find nearest long liquidation (below current price)
                long_liqs = [(float(p), s) for p, s in levels if float(p) < current_price]
                if long_liqs:
                    nearest_long = max(long_liqs, key=lambda x: x[0])[0]
                    state.liq_distance_long_pct = (current_price - nearest_long) / current_price * 100
                
                # Find nearest short liquidation (above current price)
                short_liqs = [(float(p), s) for p, s in levels if float(p) > current_price]
                if short_liqs:
                    nearest_short = min(short_liqs, key=lambda x: x[0])[0]
                    state.liq_distance_short_pct = (nearest_short - current_price) / current_price * 100
                    
        except Exception as e:
            logger.debug(f"Liquidation feature error for {symbol}: {e}")
    
    def _detect_squeeze(self, symbol: str, state: MicrostructureState):
        """Detect squeeze/pump pattern"""
        # Squeeze criteria:
        # 1. Large return in short time (>0.5% in 15s)
        # 2. High acceleration
        # 3. Volume spike
        # 4. Orderbook imbalance
        
        squeeze_score = 0.0
        direction = 0
        
        # Return magnitude
        if abs(state.ret_15s) > 0.5:
            squeeze_score += 0.3
            direction = 1 if state.ret_15s > 0 else -1
        
        # Acceleration
        if abs(state.accel_15s) > 0.2:
            squeeze_score += 0.2
        
        # Volume burst
        if state.trade_burst_count > 50:
            squeeze_score += 0.2
        
        # Orderbook imbalance aligned with direction
        if direction != 0:
            if (direction > 0 and state.orderbook_imbalance > 0.3) or \
               (direction < 0 and state.orderbook_imbalance < -0.3):
                squeeze_score += 0.15
        
        # Liquidation cascade
        if direction > 0 and state.liq_burst_short_usd > 100000:
            squeeze_score += 0.15
        elif direction < 0 and state.liq_burst_long_usd > 100000:
            squeeze_score += 0.15
        
        state.is_squeeze = squeeze_score >= 0.5
        state.squeeze_direction = direction
        state.squeeze_magnitude = squeeze_score
    
    def on_trade(self, symbol: str, price: float, qty: float, is_buyer_maker: bool):
        """Process a single trade (call from trade stream)"""
        now = time.time()
        
        # Initialize current bar if needed
        if symbol not in self._current_bar or \
           (now - self._bar_start_time.get(symbol, 0)) * 1000 >= self.update_interval_ms:
            # Close previous bar and start new one
            if symbol in self._current_bar:
                self.micro_bars[symbol].append(self._current_bar[symbol])
            
            self._current_bar[symbol] = MicroBar(
                timestamp=now,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=qty,
                buy_volume=qty if not is_buyer_maker else 0,
                sell_volume=qty if is_buyer_maker else 0,
                trade_count=1
            )
            self._bar_start_time[symbol] = now
        else:
            # Update current bar
            bar = self._current_bar[symbol]
            bar.high = max(bar.high, price)
            bar.low = min(bar.low, price)
            bar.close = price
            bar.volume += qty
            bar.trade_count += 1
            if is_buyer_maker:
                bar.sell_volume += qty
            else:
                bar.buy_volume += qty
    
    def get_features(self, symbol: str) -> List[float]:
        """Get current microstructure feature vector for a symbol"""
        if symbol not in self.states:
            return [0.0] * 30
        
        return self.states[symbol].to_feature_vector()
    
    def get_all_features(self) -> Dict[str, List[float]]:
        """Get features for all symbols"""
        return {s: self.get_features(s) for s in self.symbols}
    
    def get_squeeze_alerts(self) -> List[Tuple[str, MicrostructureState]]:
        """Get list of symbols currently in squeeze state"""
        return [(s, state) for s, state in self.states.items() if state.is_squeeze]
    
    def get_stats(self) -> Dict:
        """Get extractor statistics"""
        squeeze_count = sum(1 for s in self.states.values() if s.is_squeeze)
        return {
            'symbols': len(self.symbols),
            'active_squeezes': squeeze_count,
            'update_interval_ms': self.update_interval_ms,
            'lookback_bars': self.lookback_bars,
        }


# Singleton instance
_extractor_instance: Optional[MicrostructureFeatureExtractor] = None


def get_microstructure_extractor(
    symbols: List[str] = None,
    redis_client=None,
) -> MicrostructureFeatureExtractor:
    """Get or create singleton microstructure extractor"""
    global _extractor_instance
    
    if _extractor_instance is None:
        if symbols is None:
            try:
                # Dynamic symbol loading - supports hot-reload without restart
                from utils.symbol_manager import get_symbols_cached
                symbols = get_symbols_cached()
            except ImportError:
                try:
                from config import SYMBOLS
                symbols = SYMBOLS
            except ImportError:
                symbols = ["BTCUSDT", "ETHUSDT"]
        
        _extractor_instance = MicrostructureFeatureExtractor(
            symbols=symbols,
            redis_client=redis_client,
        )
    
    return _extractor_instance


if __name__ == "__main__":
    """Test microstructure features"""
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("🔬 TESTING MICROSTRUCTURE FEATURES")
    print("=" * 60)
    
    # Create extractor
    extractor = MicrostructureFeatureExtractor(
        symbols=["BTCUSDT", "ETHUSDT"],
        redis_client=None,  # No Redis for test
    )
    
    # Simulate some trades
    import random
    base_price = 100000.0
    
    for i in range(100):
        price = base_price + random.uniform(-100, 100)
        qty = random.uniform(0.1, 2.0)
        is_buyer = random.random() > 0.5
        
        extractor.on_trade("BTCUSDT", price, qty, is_buyer)
        
        if i % 10 == 0:
            # Trigger feature update
            extractor._update_symbol_features("BTCUSDT")
    
    # Get features
    features = extractor.get_features("BTCUSDT")
    print(f"\nFeature vector (30 dims): {features[:10]}...")
    
    state = extractor.states["BTCUSDT"]
    print(f"\nState:")
    print(f"  ret_5s: {state.ret_5s:.4f}%")
    print(f"  ret_15s: {state.ret_15s:.4f}%")
    print(f"  volatility_30s: {state.volatility_30s:.4f}%")
    print(f"  is_squeeze: {state.is_squeeze}")
    print(f"  squeeze_magnitude: {state.squeeze_magnitude:.2f}")
    
    print("\n✅ Test complete!")


