"""
Continuous Learning Framework
Automated retraining pipeline with performance monitoring
"""
import os
import logging
import json
import time
import schedule
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import pickle
import threading

logger = logging.getLogger(__name__)


class ContinuousLearner:
    """
    Manages automated model retraining and performance monitoring.
    Implements walk-forward optimization and regime detection.
    """
    
    def __init__(
        self,
        model_dir: str = 'models',
        performance_threshold: float = 0.8,
        retraining_interval_days: int = 7,
        min_samples: int = 1000
    ):
        """
        Initialize continuous learner.
        
        Args:
            model_dir: Directory for model storage
            performance_threshold: Minimum acceptable Sharpe ratio
            retraining_interval_days: Days between scheduled retraining
            min_samples: Minimum samples required for retraining
        """
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(exist_ok=True)
        
        self.performance_threshold = performance_threshold
        self.retraining_interval_days = retraining_interval_days
        self.min_samples = min_samples
        
        # Performance tracking
        self.performance_history = []
        self.last_retrain_time = None
        self.current_model_version = None
        self._retrain_lock = threading.Lock()
        self._retrain_in_progress = False
        self._last_trigger_reason: Optional[str] = None
        
        # Regime detection
        self.regime_window = 30  # days
        self.regime_shift_threshold = 2.0  # std devs
        
        logger.info("ContinuousLearner initialized")
    
    def should_retrain(
        self,
        recent_performance: Dict[str, float],
        sample_count: int
    ) -> Tuple[bool, str]:
        """
        Determine if retraining is needed.
        
        Args:
            recent_performance: Recent trading performance metrics
            sample_count: Number of available training samples
            
        Returns:
            (should_retrain, reason)
        """
        reasons = []
        if sample_count < self.min_samples:
            return False, f"Insufficient samples ({sample_count} < {self.min_samples})"
        
        # Check 1: Scheduled retraining
        if self.last_retrain_time is None:
            return True, "Initial training required"
        
        days_since_retrain = (datetime.now() - self.last_retrain_time).days
        if days_since_retrain >= self.retraining_interval_days:
            reasons.append(f"Scheduled retrain ({days_since_retrain} days)")
        
        # Check 2: Performance degradation
        current_sharpe = recent_performance.get('sharpe_ratio', 0)
        if current_sharpe < self.performance_threshold:
            reasons.append(f"Poor performance (Sharpe={current_sharpe:.2f})")
        
        # Check 3: Significant performance drop
        if len(self.performance_history) >= 7:
            recent_avg = np.mean([p['sharpe_ratio'] for p in self.performance_history[-7:]])
            if current_sharpe < recent_avg * 0.7:  # 30% drop
                reasons.append(f"Performance drop (current={current_sharpe:.2f}, avg={recent_avg:.2f})")
        
        # Check 4: Market regime shift
        if self._detect_regime_shift(recent_performance):
            reasons.append("Market regime shift detected")
        
        # Check 5: Sufficient new data
        if reasons:
            return True, "; ".join(reasons)
        else:
            return False, "No retraining needed"
    
    def _detect_regime_shift(self, recent_performance: Dict[str, float]) -> bool:
        """
        Detect significant market regime change.
        
        Args:
            recent_performance: Recent performance metrics
            
        Returns:
            True if regime shift detected
        """
        if len(self.performance_history) < self.regime_window:
            return False
        
        try:
            # Compare recent volatility to historical
            recent_vol = recent_performance.get('volatility', 0)
            historical_vols = [p.get('volatility', 0) for p in self.performance_history[-self.regime_window:]]
            
            mean_vol = np.mean(historical_vols)
            std_vol = np.std(historical_vols)
            
            if std_vol > 0:
                z_score = abs(recent_vol - mean_vol) / std_vol
                if z_score > self.regime_shift_threshold:
                    logger.info(f"Regime shift detected: volatility z-score={z_score:.2f}")
                    return True
            
            # Compare recent returns distribution
            recent_returns = recent_performance.get('daily_returns', [])
            historical_returns = []
            for p in self.performance_history[-self.regime_window:]:
                historical_returns.extend(p.get('daily_returns', []))
            
            if len(recent_returns) >= 30 and len(historical_returns) >= 100:
                recent_mean = np.mean(recent_returns)
                historical_mean = np.mean(historical_returns)
                historical_std = np.std(historical_returns)
                
                if historical_std > 0:
                    returns_z = abs(recent_mean - historical_mean) / historical_std
                    if returns_z > self.regime_shift_threshold:
                        logger.info(f"Regime shift detected: returns z-score={returns_z:.2f}")
                        return True
        
        except Exception as e:
            logger.warning(f"Error detecting regime shift: {e}")
        
        return False
    
    def record_performance(self, performance: Dict[str, float]):
        """
        Record performance metrics for monitoring.
        
        Args:
            performance: Performance metrics dictionary
        """
        performance['timestamp'] = datetime.now().isoformat()
        self.performance_history.append(performance)
        
        # Keep last 90 days
        cutoff = datetime.now() - timedelta(days=90)
        self.performance_history = [
            p for p in self.performance_history
            if datetime.fromisoformat(p['timestamp']) > cutoff
        ]
        
        # Save to disk
        history_file = self.model_dir / 'performance_history.json'
        with open(history_file, 'w') as f:
            json.dump(self.performance_history, f, indent=2)
    
    def get_performance_trend(self, days: int = 7) -> Dict[str, float]:
        """
        Calculate performance trend over recent period.
        
        Args:
            days: Number of days to analyze
            
        Returns:
            Trend statistics
        """
        if len(self.performance_history) < 2:
            return {'trend': 0, 'volatility': 0, 'consistency': 0}
        
        cutoff = datetime.now() - timedelta(days=days)
        recent = [
            p for p in self.performance_history
            if datetime.fromisoformat(p['timestamp']) > cutoff
        ]
        
        if len(recent) < 2:
            return {'trend': 0, 'volatility': 0, 'consistency': 0}
        
        sharpes = [p['sharpe_ratio'] for p in recent]
        
        # Calculate trend (linear regression slope)
        x = np.arange(len(sharpes))
        coeffs = np.polyfit(x, sharpes, 1)
        trend = coeffs[0]  # Slope
        
        # Calculate volatility
        volatility = np.std(sharpes) if len(sharpes) > 1 else 0
        
        # Calculate consistency (inverse of coefficient of variation)
        mean_sharpe = np.mean(sharpes)
        consistency = 1.0 / (1.0 + abs(volatility / mean_sharpe)) if mean_sharpe != 0 else 0
        
        return {
            'trend': float(trend),
            'volatility': float(volatility),
            'consistency': float(consistency),
            'mean_sharpe': float(mean_sharpe),
            'samples': len(recent)
        }
    
    def mark_retrain_complete(self, version: str):
        """
        Mark retraining as complete.
        
        Args:
            version: Model version identifier
        """
        self.last_retrain_time = datetime.now()
        self.current_model_version = version
        
        metadata = {
            'version': version,
            'timestamp': self.last_retrain_time.isoformat(),
            'performance_history_size': len(self.performance_history)
        }
        
        metadata_file = self.model_dir / f'retrain_metadata_{version}.json'
        with open(metadata_file, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        logger.info(f"Retraining complete: version {version}")
    
    def load_state(self):
        """Load learner state from disk."""
        try:
            # Load performance history
            history_file = self.model_dir / 'performance_history.json'
            if history_file.exists():
                with open(history_file, 'r') as f:
                    self.performance_history = json.load(f)
            
            # Find latest retrain metadata
            metadata_files = list(self.model_dir.glob('retrain_metadata_*.json'))
            if metadata_files:
                latest_file = max(metadata_files, key=lambda p: p.stat().st_mtime)
                with open(latest_file, 'r') as f:
                    metadata = json.load(f)
                    self.current_model_version = metadata['version']
                    self.last_retrain_time = datetime.fromisoformat(metadata['timestamp'])
            
            logger.info(f"Loaded learner state: {len(self.performance_history)} performance records")
        
        except Exception as e:
            logger.warning(f"Error loading learner state: {e}")

    def trigger_retrain_if_ready(
        self,
        recent_performance: Dict[str, float],
        sample_count: int,
        force: bool = False
    ) -> Tuple[bool, str]:
        """
        Evaluate triggers and mark retrain as pending if criteria met.
        Provides a lock to avoid overlapping retrain jobs.
        """
        if self._retrain_in_progress:
            return False, "Retrain already in progress"

        should, reason = self.should_retrain(recent_performance, sample_count)
        if not should and not force:
            return False, f"Skip retrain: {reason}"

        acquired = self._retrain_lock.acquire(blocking=False)
        if not acquired:
            return False, "Retrain lock busy"

        self._retrain_in_progress = True
        self._last_trigger_reason = "force" if force else reason
        logger.info(f"📈 Retrain scheduled (reason: {self._last_trigger_reason})")
        return True, self._last_trigger_reason

    def retrain_model(
        self,
        trainer,
        data_loader=None,
        replay_buffer=None,
        dry_run: bool = False,
        pause_trading: Optional[callable] = None,
        resume_trading: Optional[callable] = None,
    ) -> bool:
        """
        Execute retraining flow with pause/resume hooks and error handling.
        """
        if not self._retrain_in_progress:
            logger.info("retrain_model called without pending trigger; starting anyway")
            acquired = self._retrain_lock.acquire(blocking=False)
            if not acquired:
                logger.warning("Retrain skipped: lock busy")
                return False
            self._retrain_in_progress = True

        try:
            if pause_trading:
                pause_trading()

            logger.info("🔄 Starting retrain pass (dry_run=%s)", dry_run)
            # Load latest data if provided
            training_data = None
            if replay_buffer is not None:
                training_data = replay_buffer
            elif data_loader is not None:
                training_data = data_loader()

            if dry_run:
                logger.info("Dry-run retrain: data length=%s", getattr(training_data, "shape", None))
                return True

            # Minimal training invocation; trainer is expected to expose a fit/update method
            if hasattr(trainer, "fine_tune"):
                trainer.fine_tune(training_data)
            elif hasattr(trainer, "train"):
                trainer.train(training_data)
            else:
                raise AttributeError("Trainer missing fine_tune/train for retrain_model")

            # Persist metadata
            version_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.mark_retrain_complete(version_tag)
            logger.info("✅ Retrain completed, version=%s", version_tag)
            return True

        except Exception as exc:
            logger.error(f"❌ Retrain failed: {exc}")
            return False
        finally:
            if resume_trading:
                try:
                    resume_trading()
                except Exception as resume_err:
                    logger.warning(f"Resume trading hook failed: {resume_err}")
            self._retrain_in_progress = False
            if self._retrain_lock.locked():
                self._retrain_lock.release()


class WalkForwardOptimizer:
    """
    Implements walk-forward optimization for model validation.
    """
    
    def __init__(
        self,
        train_window_days: int = 90,
        test_window_days: int = 30,
        step_days: int = 30
    ):
        """
        Initialize walk-forward optimizer.
        
        Args:
            train_window_days: Training window size
            test_window_days: Testing window size
            step_days: Step size between windows
        """
        self.train_window = train_window_days
        self.test_window = test_window_days
        self.step = step_days
        
        logger.info(f"WalkForwardOptimizer initialized: train={train_window_days}d, test={test_window_days}d")
    
    def generate_windows(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> List[Tuple[datetime, datetime, datetime, datetime]]:
        """
        Generate walk-forward windows.
        
        Args:
            start_date: Start of data range
            end_date: End of data range
            
        Returns:
            List of (train_start, train_end, test_start, test_end) tuples
        """
        windows = []
        current = start_date
        
        while current + timedelta(days=self.train_window + self.test_window) <= end_date:
            train_start = current
            train_end = current + timedelta(days=self.train_window)
            test_start = train_end
            test_end = test_start + timedelta(days=self.test_window)
            
            windows.append((train_start, train_end, test_start, test_end))
            
            current += timedelta(days=self.step)
        
        logger.info(f"Generated {len(windows)} walk-forward windows")
        return windows
    
    def evaluate_window(
        self,
        trainer,
        train_data,
        test_data,
        window_idx: int
    ) -> Dict[str, float]:
        """
        Train and evaluate on a single window.
        
        Args:
            trainer: Model trainer instance
            train_data: Training data
            test_data: Testing data
            window_idx: Window index
            
        Returns:
            Performance metrics for this window
        """
        logger.info(f"Evaluating walk-forward window {window_idx}")
        
        try:
            # Train on window
            trainer.train(train_data)
            
            # Test on window
            predictions = trainer.predict(test_data)
            
            # Calculate metrics
            returns = self._calculate_returns(predictions, test_data)
            sharpe = self._calculate_sharpe(returns)
            max_dd = self._calculate_max_drawdown(returns)
            win_rate = self._calculate_win_rate(returns)
            
            metrics = {
                'window': window_idx,
                'sharpe_ratio': sharpe,
                'max_drawdown': max_dd,
                'win_rate': win_rate,
                'total_return': np.sum(returns),
                'samples': len(test_data)
            }
            
            logger.info(f"Window {window_idx}: Sharpe={sharpe:.2f}, DD={max_dd:.2%}, WR={win_rate:.2%}")
            
            return metrics
        
        except Exception as e:
            logger.error(f"Error evaluating window {window_idx}: {e}")
            return {
                'window': window_idx,
                'sharpe_ratio': 0,
                'max_drawdown': 0,
                'win_rate': 0,
                'total_return': 0,
                'samples': 0,
                'error': str(e)
            }
    
    def _calculate_returns(self, predictions, data):
        """Calculate trading returns from predictions."""
        # Simplified - implement based on your prediction format
        returns = []
        for pred, actual in zip(predictions, data):
            ret = pred * actual  # Placeholder logic
            returns.append(ret)
        return np.array(returns)
    
    def _calculate_sharpe(self, returns: np.ndarray, risk_free: float = 0.02) -> float:
        """Calculate annualized Sharpe ratio."""
        if len(returns) == 0:
            return 0
        
        excess_returns = returns - (risk_free / 252)  # Daily risk-free rate
        if np.std(excess_returns) == 0:
            return 0
        
        sharpe = np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(252)
        return float(sharpe)
    
    def _calculate_max_drawdown(self, returns: np.ndarray) -> float:
        """Calculate maximum drawdown."""
        cumulative = np.cumprod(1 + returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) / running_max
        return float(np.min(drawdown))
    
    def _calculate_win_rate(self, returns: np.ndarray) -> float:
        """Calculate win rate."""
        if len(returns) == 0:
            return 0
        wins = np.sum(returns > 0)
        return float(wins / len(returns))


class FeedbackCollector:
    """
    Collects trading feedback for continuous learning.
    """
    
    def __init__(self, feedback_file: str = 'trading_feedback.json'):
        """
        Initialize feedback collector.
        
        Args:
            feedback_file: File to store feedback
        """
        self.feedback_file = Path(feedback_file)
        self.feedback_buffer = []
        self.buffer_size = 1000
        
        # Load existing feedback
        self.load_feedback()
        
        logger.info("FeedbackCollector initialized")
    
    def record_trade(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool,
        metadata: Optional[Dict] = None
    ):
        """
        Record a trading step for learning.
        
        Args:
            state: Pre-action state
            action: Action taken
            reward: Reward received
            next_state: Post-action state
            done: Episode done flag
            metadata: Additional metadata
        """
        feedback = {
            'timestamp': datetime.now().isoformat(),
            'state_shape': state.shape,
            'action': int(action),
            'reward': float(reward),
            'next_state_shape': next_state.shape,
            'done': bool(done),
            'metadata': metadata or {}
        }
        
        self.feedback_buffer.append(feedback)
        
        # Auto-save when buffer is full
        if len(self.feedback_buffer) >= self.buffer_size:
            self.save_feedback()
    
    def save_feedback(self):
        """Save feedback buffer to disk."""
        try:
            # Load existing
            existing = []
            if self.feedback_file.exists():
                with open(self.feedback_file, 'r') as f:
                    existing = json.load(f)
            
            # Append new
            existing.extend(self.feedback_buffer)
            
            # Keep last 10k entries
            if len(existing) > 10000:
                existing = existing[-10000:]
            
            # Save
            with open(self.feedback_file, 'w') as f:
                json.dump(existing, f)
            
            logger.info(f"Saved {len(self.feedback_buffer)} feedback entries")
            self.feedback_buffer = []
        
        except Exception as e:
            logger.error(f"Error saving feedback: {e}")
    
    def load_feedback(self):
        """Load feedback from disk."""
        try:
            if self.feedback_file.exists():
                with open(self.feedback_file, 'r') as f:
                    data = json.load(f)
                    logger.info(f"Loaded {len(data)} feedback entries")
        except Exception as e:
            logger.warning(f"Error loading feedback: {e}")
    
    def get_recent_feedback(self, count: int = 1000) -> List[Dict]:
        """
        Get recent feedback entries.
        
        Args:
            count: Number of recent entries
            
        Returns:
            List of feedback dictionaries
        """
        try:
            if self.feedback_file.exists():
                with open(self.feedback_file, 'r') as f:
                    data = json.load(f)
                    return data[-count:]
        except Exception as e:
            logger.error(f"Error getting feedback: {e}")
        
        return []


if __name__ == '__main__':
    # Test continuous learner
    logging.basicConfig(level=logging.INFO)
    
    learner = ContinuousLearner(model_dir='test_models')
    
    # Test performance recording
    for i in range(10):
        performance = {
            'sharpe_ratio': 1.5 + np.random.randn() * 0.3,
            'volatility': 0.15 + np.random.randn() * 0.02,
            'daily_returns': list(np.random.randn(30) * 0.01)
        }
        learner.record_performance(performance)
    
    # Test retraining decision
    recent_perf = {
        'sharpe_ratio': 0.5,  # Poor performance
        'volatility': 0.25,   # High volatility
        'daily_returns': list(np.random.randn(30) * 0.02)
    }
    
    should_retrain, reason = learner.should_retrain(recent_perf, sample_count=2000)
    print(f"\nShould retrain: {should_retrain}")
    print(f"Reason: {reason}")
    
    # Test trend analysis
    trend = learner.get_performance_trend(days=7)
    print(f"\nPerformance trend: {trend}")
    
    # Test walk-forward optimizer
    wf_optimizer = WalkForwardOptimizer(train_window_days=90, test_window_days=30)
    windows = wf_optimizer.generate_windows(
        start_date=datetime(2023, 1, 1),
        end_date=datetime(2024, 1, 1)
    )
    print(f"\nGenerated {len(windows)} walk-forward windows")
