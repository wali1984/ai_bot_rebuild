"""
Phase 1C: Extended Redis Metrics Tracker
Tracks max_drawdown, win_rate, sharpe_like for dashboards
"""
import redis
import json
import time
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from collections import deque


@dataclass
class TradeRecord:
    """Record of a completed trade"""
    symbol: str
    entry_time: float
    exit_time: float
    entry_price: float
    exit_price: float
    side: str  # LONG or SHORT
    pnl: float
    pnl_pct: float
    confidence: float
    timeframe: str


class MetricsTracker:
    """Extended metrics tracker for risk-adjusted performance"""
    
    def __init__(self, redis_client: redis.Redis, window_size: int = 1000):
        self.redis = redis_client
        self.window_size = window_size
        
        # In-memory buffers for fast calculation
        self.equity_curve = deque(maxlen=window_size)
        self.trade_history = deque(maxlen=window_size)
        self.returns = deque(maxlen=window_size)
        
        # Load existing data from Redis
        self._load_from_redis()
    
    def _load_from_redis(self):
        """Load existing metrics from Redis"""
        try:
            # Load equity curve
            equity_data = self.redis.lrange("rl:metrics:equity_curve", -self.window_size, -1)
            self.equity_curve.extend([float(x) for x in equity_data])
            
            # Load trade history
            trade_data = self.redis.lrange("rl:metrics:trade_history", -self.window_size, -1)
            for td in trade_data:
                try:
                    trade_dict = json.loads(td)
                    self.trade_history.append(TradeRecord(**trade_dict))
                except:
                    pass
        except Exception as e:
            print(f"Warning: Could not load metrics from Redis: {e}")
    
    def record_trade(self, trade: TradeRecord):
        """Record a completed trade and update all metrics"""
        self.trade_history.append(trade)
        self.returns.append(trade.pnl_pct)
        
        # Calculate new equity
        if self.equity_curve:
            new_equity = self.equity_curve[-1] * (1 + trade.pnl_pct / 100)
        else:
            new_equity = 10000 * (1 + trade.pnl_pct / 100)  # Starting capital
        
        self.equity_curve.append(new_equity)
        
        # Persist to Redis
        self.redis.rpush("rl:metrics:equity_curve", new_equity)
        self.redis.rpush("rl:metrics:trade_history", json.dumps(asdict(trade)))
        
        # Trim to window size
        self.redis.ltrim("rl:metrics:equity_curve", -self.window_size, -1)
        self.redis.ltrim("rl:metrics:trade_history", -self.window_size, -1)
        
        # Update all metrics
        self._update_metrics()
    
    def _update_metrics(self):
        """Calculate and push all metrics to Redis"""
        if not self.trade_history:
            return
        
        metrics = {
            'max_drawdown': self._calculate_max_drawdown(),
            'win_rate': self._calculate_win_rate(),
            'sharpe_like': self._calculate_sharpe_like(),
            'total_trades': len(self.trade_history),
            'avg_pnl_pct': np.mean([t.pnl_pct for t in self.trade_history]),
            'total_pnl': sum([t.pnl for t in self.trade_history]),
            'current_equity': self.equity_curve[-1] if self.equity_curve else 10000,
            'timestamp': time.time()
        }
        
        # Push to continuous metrics
        self.redis.hset("rl:metrics:continuous", mapping={
            k: json.dumps(v) if isinstance(v, (dict, list)) else v 
            for k, v in metrics.items()
        })
        
        # Push per-timeframe metrics
        for tf in ['1m', '5m', '15m', '1h', '4h']:
            tf_trades = [t for t in self.trade_history if t.timeframe == tf]
            if tf_trades:
                tf_metrics = {
                    'max_drawdown': self._calculate_max_drawdown(tf_trades),
                    'win_rate': self._calculate_win_rate(tf_trades),
                    'sharpe_like': self._calculate_sharpe_like(tf_trades),
                    'total_trades': len(tf_trades),
                    'avg_pnl_pct': np.mean([t.pnl_pct for t in tf_trades]),
                    'timestamp': time.time()
                }
                self.redis.hset(f"rl:metrics:{tf}", mapping={
                    k: json.dumps(v) if isinstance(v, (dict, list)) else v 
                    for k, v in tf_metrics.items()
                })
    
    def _calculate_max_drawdown(self, trades: Optional[List[TradeRecord]] = None) -> float:
        """Calculate maximum drawdown percentage"""
        if trades is None:
            equity = list(self.equity_curve)
        else:
            # Build equity curve for subset
            equity = [10000]
            for t in trades:
                equity.append(equity[-1] * (1 + t.pnl_pct / 100))
        
        if len(equity) < 2:
            return 0.0
        
        equity = np.array(equity)
        running_max = np.maximum.accumulate(equity)
        drawdown = (equity - running_max) / running_max * 100
        return float(np.min(drawdown))
    
    def _calculate_win_rate(self, trades: Optional[List[TradeRecord]] = None) -> float:
        """Calculate win rate percentage"""
        if trades is None:
            trades = list(self.trade_history)
        
        if not trades:
            return 0.0
        
        winning_trades = sum(1 for t in trades if t.pnl > 0)
        return winning_trades / len(trades) * 100
    
    def _calculate_sharpe_like(self, trades: Optional[List[TradeRecord]] = None) -> float:
        """Calculate Sharpe-like ratio (mean return / std return)"""
        if trades is None:
            returns = list(self.returns)
        else:
            returns = [t.pnl_pct for t in trades]
        
        if len(returns) < 2:
            return 0.0
        
        returns = np.array(returns)
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        
        if std_return == 0:
            return 0.0
        
        # Annualized Sharpe-like (assuming ~250 trading days)
        return float(mean_return / std_return * np.sqrt(250))
    
    def get_metrics(self, timeframe: Optional[str] = None) -> Dict:
        """Get current metrics"""
        if timeframe:
            key = f"rl:metrics:{timeframe}"
        else:
            key = "rl:metrics:continuous"
        
        metrics = self.redis.hgetall(key)
        return {k.decode(): json.loads(v) if v.startswith(b'{') or v.startswith(b'[') else float(v) 
                for k, v in metrics.items()}


if __name__ == "__main__":
    # Test the metrics tracker
    r = redis.Redis(host='localhost', port=6379, db=0)
    tracker = MetricsTracker(r)
    
    # Simulate some trades
    import random
    for i in range(50):
        trade = TradeRecord(
            symbol="BTCUSDT",
            entry_time=time.time() - 3600 * i,
            exit_time=time.time() - 3600 * i + 1800,
            entry_price=50000 + random.uniform(-1000, 1000),
            exit_price=50000 + random.uniform(-1000, 1000),
            side="LONG" if random.random() > 0.5 else "SHORT",
            pnl=random.uniform(-100, 150),
            pnl_pct=random.uniform(-2, 3),
            confidence=random.uniform(0.7, 0.95),
            timeframe="1h"
        )
        tracker.record_trade(trade)
    
    print("Continuous Metrics:")
    print(json.dumps(tracker.get_metrics(), indent=2))
    print("\n1h Metrics:")
    print(json.dumps(tracker.get_metrics('1h'), indent=2))
