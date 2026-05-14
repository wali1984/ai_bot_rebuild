"""
Phase 3: Walk-Forward Validation Framework
30-day train / 7-day validate rolling window backtest
"""
import redis
import json
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import time


class WalkForwardValidator:
    """Walk-forward validation for time-series backtesting"""
    
    def __init__(
        self, 
        redis_client: redis.Redis,
        train_days: int = 30,
        validate_days: int = 7
    ):
        self.redis = redis_client
        self.train_days = train_days
        self.validate_days = validate_days
        self.window_days = train_days + validate_days
    
    def create_validation_windows(
        self, 
        start_date: datetime, 
        end_date: datetime
    ) -> List[Tuple[datetime, datetime, datetime, datetime]]:
        """
        Create rolling train/validate windows
        Returns: [(train_start, train_end, val_start, val_end), ...]
        """
        windows = []
        current_date = start_date
        
        while current_date + timedelta(days=self.window_days) <= end_date:
            train_start = current_date
            train_end = current_date + timedelta(days=self.train_days)
            val_start = train_end
            val_end = val_start + timedelta(days=self.validate_days)
            
            windows.append((train_start, train_end, val_start, val_end))
            
            # Roll forward by validate_days (no gap, continuous walk-forward)
            current_date = val_start
        
        return windows
    
    def run_backtest_window(
        self,
        train_start: datetime,
        train_end: datetime,
        val_start: datetime,
        val_end: datetime,
        model_path: Optional[str] = None
    ) -> Dict:
        """
        Run one walk-forward window
        1. Train model on [train_start, train_end]
        2. Validate on [val_start, val_end]
        3. Return metrics
        """
        window_id = f"{train_start.strftime('%Y%m%d')}_{val_end.strftime('%Y%m%d')}"
        
        print(f"\n{'='*70}")
        print(f"Window {window_id}")
        print(f"  Train: {train_start.date()} → {train_end.date()} ({self.train_days}d)")
        print(f"  Val:   {val_start.date()} → {val_end.date()} ({self.validate_days}d)")
        print(f"{'='*70}")
        
        # TODO: Actual training/validation logic
        # For now, simulate metrics
        train_metrics = {
            'num_trades': np.random.randint(50, 200),
            'win_rate': np.random.uniform(0.5, 0.7),
            'sharpe': np.random.uniform(0.5, 2.0),
            'max_drawdown': np.random.uniform(-15, -5)
        }
        
        val_metrics = {
            'num_trades': np.random.randint(10, 50),
            'win_rate': np.random.uniform(0.45, 0.65),
            'sharpe': np.random.uniform(0.3, 1.5),
            'max_drawdown': np.random.uniform(-20, -8),
            'ece': np.random.uniform(0.02, 0.10),
            'accuracy': np.random.uniform(0.50, 0.70)
        }
        
        result = {
            'window_id': window_id,
            'train_start': train_start.isoformat(),
            'train_end': train_end.isoformat(),
            'val_start': val_start.isoformat(),
            'val_end': val_end.isoformat(),
            'train_metrics': train_metrics,
            'val_metrics': val_metrics,
            'timestamp': time.time()
        }
        
        # Store in Redis
        self.redis.hset(
            "rl:metrics:backtest",
            window_id,
            json.dumps(result)
        )
        
        print(f"\n📊 Train Metrics:")
        print(f"   Trades: {train_metrics['num_trades']}")
        print(f"   Win Rate: {train_metrics['win_rate']:.2%}")
        print(f"   Sharpe: {train_metrics['sharpe']:.2f}")
        print(f"   Max DD: {train_metrics['max_drawdown']:.2f}%")
        
        print(f"\n📈 Validation Metrics:")
        print(f"   Trades: {val_metrics['num_trades']}")
        print(f"   Win Rate: {val_metrics['win_rate']:.2%}")
        print(f"   Sharpe: {val_metrics['sharpe']:.2f}")
        print(f"   Max DD: {val_metrics['max_drawdown']:.2f}%")
        print(f"   ECE: {val_metrics['ece']:.4f}")
        print(f"   Accuracy: {val_metrics['accuracy']:.2%}")
        
        return result
    
    def run_full_backtest(
        self,
        start_date: datetime,
        end_date: datetime,
        model_path: Optional[str] = None
    ) -> List[Dict]:
        """Run full walk-forward backtest"""
        windows = self.create_validation_windows(start_date, end_date)
        
        print(f"\n🚀 Starting Walk-Forward Backtest")
        print(f"   Total Windows: {len(windows)}")
        print(f"   Train Period: {self.train_days} days")
        print(f"   Validate Period: {self.validate_days} days")
        print(f"   Date Range: {start_date.date()} → {end_date.date()}")
        
        results = []
        for i, (train_start, train_end, val_start, val_end) in enumerate(windows, 1):
            print(f"\n[{i}/{len(windows)}]", end='')
            result = self.run_backtest_window(
                train_start, train_end, val_start, val_end, model_path
            )
            results.append(result)
        
        # Aggregate results
        self._aggregate_results(results)
        
        return results
    
    def _aggregate_results(self, results: List[Dict]):
        """Aggregate and store overall backtest metrics"""
        if not results:
            return
        
        val_metrics = [r['val_metrics'] for r in results]
        
        aggregate = {
            'num_windows': len(results),
            'avg_win_rate': np.mean([m['win_rate'] for m in val_metrics]),
            'avg_sharpe': np.mean([m['sharpe'] for m in val_metrics]),
            'avg_max_drawdown': np.mean([m['max_drawdown'] for m in val_metrics]),
            'avg_ece': np.mean([m['ece'] for m in val_metrics]),
            'avg_accuracy': np.mean([m['accuracy'] for m in val_metrics]),
            'total_trades': sum([m['num_trades'] for m in val_metrics]),
            'timestamp': time.time()
        }
        
        self.redis.hset("rl:metrics:backtest:aggregate", mapping={
            k: json.dumps(v) if isinstance(v, (dict, list)) else v 
            for k, v in aggregate.items()
        })
        
        print(f"\n{'='*70}")
        print("📊 AGGREGATE VALIDATION METRICS")
        print(f"{'='*70}")
        print(f"   Windows: {aggregate['num_windows']}")
        print(f"   Avg Win Rate: {aggregate['avg_win_rate']:.2%}")
        print(f"   Avg Sharpe: {aggregate['avg_sharpe']:.2f}")
        print(f"   Avg Max DD: {aggregate['avg_max_drawdown']:.2f}%")
        print(f"   Avg ECE: {aggregate['avg_ece']:.4f}")
        print(f"   Avg Accuracy: {aggregate['avg_accuracy']:.2%}")
        print(f"   Total Trades: {aggregate['total_trades']}")
        print(f"{'='*70}\n")


def run_walk_forward_validation(
    start_date_str: str = None,
    end_date_str: str = None,
    train_days: int = 30,
    validate_days: int = 7
):
    """Run walk-forward validation from command line"""
    r = redis.Redis(host='localhost', port=6379, db=0)
    validator = WalkForwardValidator(r, train_days, validate_days)
    
    # Default to last 3 months
    if not end_date_str:
        end_date = datetime.now()
    else:
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
    
    if not start_date_str:
        start_date = end_date - timedelta(days=90)
    else:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
    
    results = validator.run_full_backtest(start_date, end_date)
    
    return results


if __name__ == "__main__":
    import sys
    
    # Command line arguments: start_date end_date train_days validate_days
    if len(sys.argv) > 1:
        start_date = sys.argv[1]
        end_date = sys.argv[2] if len(sys.argv) > 2 else None
        train_days = int(sys.argv[3]) if len(sys.argv) > 3 else 30
        validate_days = int(sys.argv[4]) if len(sys.argv) > 4 else 7
    else:
        start_date = None
        end_date = None
        train_days = 30
        validate_days = 7
    
    run_walk_forward_validation(start_date, end_date, train_days, validate_days)
