"""
Trade Outcome Feedback System

This module implements:
1. Real-time trade outcome tracking from executed signals
2. Reward adjustment based on actual PnL (not simulated)
3. Signal validation before going live (backtesting gate)
4. Model performance tracking per symbol/timeframe

Author: WMA AI Trading System
"""

import json
import time
import threading
import logging
import os
from collections import deque, defaultdict
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
import numpy as np

# Use hybrid_trainer logger to ensure logs appear in hybrid_trainer.log
logger = logging.getLogger('hybrid_trainer.trade_feedback')
logger.setLevel(logging.INFO)

# Also ensure propagation to root
logger.propagate = True


@dataclass
class TradeOutcome:
    """Represents the outcome of a single trade"""
    symbol: str
    action: str  # OPEN_LONG, CLOSE_SHORT, etc.
    entry_price: float
    exit_price: Optional[float] = None
    entry_time: float = field(default_factory=time.time)
    exit_time: Optional[float] = None
    quantity: float = 0.0
    pnl_usd: float = 0.0
    pnl_pct: float = 0.0
    signal_confidence: float = 0.0
    timeframe: str = "1h"
    is_closed: bool = False
    hold_duration_hours: float = 0.0
    
    def calculate_pnl(self, current_price: float) -> Tuple[float, float]:
        """Calculate unrealized PnL"""
        if self.quantity == 0:
            return 0.0, 0.0
        
        is_long = "LONG" in self.action.upper()
        if is_long:
            pnl_usd = (current_price - self.entry_price) * self.quantity
        else:
            pnl_usd = (self.entry_price - current_price) * self.quantity
        
        pnl_pct = (pnl_usd / (self.entry_price * self.quantity)) * 100 if self.entry_price > 0 else 0
        return pnl_usd, pnl_pct


class TradeOutcomeTracker:
    """
    Tracks trade outcomes and calculates performance metrics
    Used to adjust training rewards based on actual results
    """
    
    def __init__(self, max_history: int = 1000, redis_client=None):
        self.redis = redis_client
        self.max_history = max_history
        
        # Trade outcome storage
        self.open_trades: Dict[str, TradeOutcome] = {}  # symbol -> active trade
        self.closed_trades: deque = deque(maxlen=max_history)
        
        # Performance metrics per symbol and timeframe
        self.performance_by_symbol: Dict[str, Dict] = defaultdict(lambda: {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_pnl_usd': 0.0,
            'avg_pnl_pct': 0.0,
            'win_rate': 0.0,
            'avg_hold_hours': 0.0,
            'last_10_pnl': deque(maxlen=10)
        })
        
        self.performance_by_timeframe: Dict[str, Dict] = defaultdict(lambda: {
            'total_trades': 0,
            'winning_trades': 0,
            'total_pnl_usd': 0.0,
            'win_rate': 0.0
        })
        
        # Overall metrics
        self.total_trades = 0
        self.total_pnl = 0.0
        self.winning_trades = 0
        self.losing_trades = 0
        
        # Reward adjustment factors
        self.symbol_reward_multipliers: Dict[str, float] = defaultdict(lambda: 1.0)
        
        # Thread safety
        self._lock = threading.RLock()
        
        logger.info("[TRADE-FEEDBACK] TradeOutcomeTracker initialized")
    
    def record_trade_open(self, symbol: str, action: str, entry_price: float, 
                          quantity: float, confidence: float, timeframe: str = "1h"):
        """Record when a trade is opened"""
        with self._lock:
            trade = TradeOutcome(
                symbol=symbol,
                action=action,
                entry_price=entry_price,
                quantity=quantity,
                signal_confidence=confidence,
                timeframe=timeframe,
                entry_time=time.time()
            )
            
            # Store by symbol-side key to handle hedging
            side = "LONG" if "LONG" in action.upper() else "SHORT"
            key = f"{symbol}_{side}"
            self.open_trades[key] = trade
            
            logger.info(f"[TRADE-FEEDBACK] 📈 Opened: {symbol} {action} @ {entry_price:.4f} (conf: {confidence:.2f})")
    
    def record_trade_close(self, symbol: str, action: str, exit_price: float,
                           quantity: float = None) -> Optional[TradeOutcome]:
        """Record when a trade is closed and calculate PnL"""
        with self._lock:
            # Determine side from action
            if "CLOSE_LONG" in action.upper() or "SELL" in action.upper():
                side = "LONG"
            elif "CLOSE_SHORT" in action.upper() or "BUY" in action.upper():
                side = "SHORT"
            else:
                # Try to find matching open trade
                side = "LONG" if f"{symbol}_LONG" in self.open_trades else "SHORT"
            
            key = f"{symbol}_{side}"
            
            if key not in self.open_trades:
                logger.debug(f"[TRADE-FEEDBACK] No matching open trade for {key}")
                return None
            
            trade = self.open_trades.pop(key)
            trade.exit_price = exit_price
            trade.exit_time = time.time()
            trade.is_closed = True
            trade.hold_duration_hours = (trade.exit_time - trade.entry_time) / 3600
            
            # Calculate actual PnL
            if side == "LONG":
                trade.pnl_usd = (exit_price - trade.entry_price) * trade.quantity
            else:
                trade.pnl_usd = (trade.entry_price - exit_price) * trade.quantity
            
            notional = trade.entry_price * trade.quantity
            trade.pnl_pct = (trade.pnl_usd / notional * 100) if notional > 0 else 0
            
            # Update metrics
            self._update_metrics(trade)
            
            # Store in history
            self.closed_trades.append(trade)
            
            result = "✅ WIN" if trade.pnl_usd > 0 else "❌ LOSS"
            logger.info(f"[TRADE-FEEDBACK] {result}: {symbol} {side} PnL: ${trade.pnl_usd:.2f} ({trade.pnl_pct:.2f}%) "
                       f"held {trade.hold_duration_hours:.1f}h, conf was {trade.signal_confidence:.2f}")
            
            return trade
    
    def _update_metrics(self, trade: TradeOutcome):
        """Update performance metrics after a trade closes"""
        symbol = trade.symbol
        tf = trade.timeframe
        
        # Update symbol metrics
        sym_metrics = self.performance_by_symbol[symbol]
        sym_metrics['total_trades'] += 1
        sym_metrics['total_pnl_usd'] += trade.pnl_usd
        sym_metrics['last_10_pnl'].append(trade.pnl_pct)
        
        if trade.pnl_usd > 0:
            sym_metrics['winning_trades'] += 1
            self.winning_trades += 1
        else:
            sym_metrics['losing_trades'] += 1
            self.losing_trades += 1
        
        # Calculate running averages
        total = sym_metrics['total_trades']
        sym_metrics['win_rate'] = sym_metrics['winning_trades'] / total if total > 0 else 0
        sym_metrics['avg_pnl_pct'] = np.mean(list(sym_metrics['last_10_pnl'])) if sym_metrics['last_10_pnl'] else 0
        sym_metrics['avg_hold_hours'] = (sym_metrics['avg_hold_hours'] * (total - 1) + trade.hold_duration_hours) / total
        
        # Update timeframe metrics
        tf_metrics = self.performance_by_timeframe[tf]
        tf_metrics['total_trades'] += 1
        tf_metrics['total_pnl_usd'] += trade.pnl_usd
        if trade.pnl_usd > 0:
            tf_metrics['winning_trades'] += 1
        tf_metrics['win_rate'] = tf_metrics['winning_trades'] / tf_metrics['total_trades']
        
        # Update overall
        self.total_trades += 1
        self.total_pnl += trade.pnl_usd
        
        # Update reward multiplier based on recent performance
        self._update_reward_multiplier(symbol)
    
    def _update_reward_multiplier(self, symbol: str):
        """
        Adjust reward multiplier based on recent performance.
        
        If a symbol is consistently losing, reduce its reward weight
        so the model learns to avoid it or improve signals.
        """
        metrics = self.performance_by_symbol[symbol]
        
        if metrics['total_trades'] < 5:
            # Not enough data, use default
            self.symbol_reward_multipliers[symbol] = 1.0
            return
        
        win_rate = metrics['win_rate']
        avg_pnl = metrics['avg_pnl_pct']
        
        # Calculate multiplier based on performance
        if win_rate >= 0.6 and avg_pnl > 0.5:
            # Performing well - boost rewards
            multiplier = 1.2
        elif win_rate >= 0.5 and avg_pnl > 0:
            # Okay performance
            multiplier = 1.0
        elif win_rate >= 0.4 or avg_pnl > -0.5:
            # Below average - slight penalty
            multiplier = 0.8
        else:
            # Poor performance - significant penalty
            multiplier = 0.5
        
        self.symbol_reward_multipliers[symbol] = multiplier
        logger.debug(f"[TRADE-FEEDBACK] {symbol} reward multiplier: {multiplier:.2f} "
                    f"(win_rate={win_rate:.2f}, avg_pnl={avg_pnl:.2f}%)")
    
    def get_reward_adjustment(self, symbol: str, base_reward: float) -> float:
        """
        Adjust training reward based on actual trade outcomes.
        
        CRITICAL: Uses REAL PnL from executed trades instead of simulated rewards
        when recent trade data is available.
        
        Args:
            symbol: Trading symbol
            base_reward: The reward from simulated environment
            
        Returns:
            Adjusted reward incorporating real-world performance
        """
        with self._lock:
            # Check for recently closed trades (last 5 trades) for this symbol
            recent_pnl_list = []
            for trade in list(self.closed_trades)[-20:]:  # Check last 20 closed trades
                if trade.symbol == symbol and trade.is_closed:
                    recent_pnl_list.append(trade.pnl_pct / 100.0)  # Convert % to decimal
            
            if recent_pnl_list:
                # Use ACTUAL PnL from recent trades as primary signal
                # Average last 3 trades to smooth volatility
                avg_recent_pnl = np.mean(recent_pnl_list[-3:]) if len(recent_pnl_list) >= 3 else recent_pnl_list[-1]
                
                # Scale by magnitude to emphasize wins/losses
                magnitude_scale = abs(avg_recent_pnl) if abs(avg_recent_pnl) > 0.01 else 1.0
                real_reward = avg_recent_pnl * magnitude_scale * 10.0  # Scale up for learning
                
                # Blend 80% real PnL + 20% simulated for stability
                adjusted_reward = (0.8 * real_reward) + (0.2 * base_reward)
                
                logger.debug(f"[REWARD-FEEDBACK] {symbol}: REAL PnL {avg_recent_pnl:.4f}, "
                           f"sim={base_reward:.4f}, final={adjusted_reward:.4f} "
                           f"(recent trades: {len(recent_pnl_list)})")
                return adjusted_reward
            else:
                # No recent trades - use multiplier approach as fallback
                multiplier = self.symbol_reward_multipliers.get(symbol, 1.0)
                return base_reward * multiplier
    
    def get_symbol_performance(self, symbol: str) -> Dict:
        """Get performance metrics for a symbol"""
        with self._lock:
            return dict(self.performance_by_symbol[symbol])
    
    def get_overall_performance(self) -> Dict:
        """Get overall performance summary"""
        with self._lock:
            win_rate = self.winning_trades / self.total_trades if self.total_trades > 0 else 0
            return {
                'total_trades': self.total_trades,
                'winning_trades': self.winning_trades,
                'losing_trades': self.losing_trades,
                'total_pnl_usd': self.total_pnl,
                'win_rate': win_rate,
                'symbols_tracked': len(self.performance_by_symbol),
                'open_trades': len(self.open_trades)
            }
    
    def get_recent_pnl_for_training(self, lookback: int = 50) -> List[Dict]:
        """
        Get recent PnL data for direct training reward injection.
        
        Returns list of {symbol, pnl_usd, pnl_pct, timestamp} for last N trades.
        This allows trainer to bypass simulated rewards entirely.
        """
        with self._lock:
            recent = []
            for trade in list(self.closed_trades)[-lookback:]:
                recent.append({
                    'symbol': trade.symbol,
                    'pnl_usd': trade.pnl_usd,
                    'pnl_pct': trade.pnl_pct,
                    'timestamp': trade.exit_time,
                    'action': trade.action,
                    'confidence': trade.signal_confidence,
                    'hold_hours': trade.hold_duration_hours
                })
            return recent
    
    def should_allow_signal(self, symbol: str, action: str, confidence: float) -> Tuple[bool, str]:
        """
        Validate if a signal should be allowed based on historical performance.
        
        This implements a "circuit breaker" pattern - if a symbol is losing
        too much, we block new signals until performance improves.
        
        Returns:
            (allowed, reason)
        """
        metrics = self.performance_by_symbol.get(symbol)
        
        if not metrics or metrics['total_trades'] < 3:
            # Not enough data, allow
            return True, "Insufficient history"
        
        win_rate = metrics['win_rate']
        avg_pnl = metrics['avg_pnl_pct']
        recent_pnl = list(metrics['last_10_pnl'])
        
        # Block if: last 3 trades all losses AND avg pnl < -1%
        if len(recent_pnl) >= 3:
            last_3_all_losses = all(p < 0 for p in recent_pnl[-3:])
            if last_3_all_losses and avg_pnl < -1.0:
                return False, f"⛔ BLOCKED: {symbol} lost last 3 trades (avg PnL: {avg_pnl:.2f}%)"
        
        # Block if: win rate < 30% with 10+ trades
        if metrics['total_trades'] >= 10 and win_rate < 0.3:
            return False, f"⛔ BLOCKED: {symbol} win rate only {win_rate:.1%} over {metrics['total_trades']} trades"
        
        # Allow with warning if performance is borderline
        if win_rate < 0.4 and metrics['total_trades'] >= 5:
            return True, f"⚠️ WARNING: {symbol} win rate {win_rate:.1%} - proceed with caution"
        
        return True, "✅ Performance acceptable"


class SignalValidator:
    """
    Validates signals before they go live using historical backtesting.
    
    Implements:
    1. Quick lookback validation (did this signal work in past 24h?)
    2. Similar condition matching (what happened in similar market conditions?)
    3. Confidence calibration (is 90% confidence really 90% accurate?)
    """
    
    def __init__(self, redis_client=None, min_backtest_samples: int = 10):
        self.redis = redis_client
        self.min_backtest_samples = min_backtest_samples

        # Optional precision-oriented admission controls (config-driven, kill-switchable)
        try:
            from config import (
                SIGNAL_VALIDATOR_PRECISION_MODE,
                SIGNAL_VALIDATOR_TARGET_WIN_RATE,
                SIGNAL_VALIDATOR_RECENT_WINDOW,
                SIGNAL_VALIDATOR_MIN_BIN_SAMPLES,
                SIGNAL_VALIDATOR_WINRATE_CONF_SLOPE,
                SIGNAL_VALIDATOR_COLDSTART_MIN_CONF,
                SIGNAL_VALIDATOR_HOT_MIN_CONF,
                SIGNAL_VALIDATOR_HIGH_PRECISION_PROFILE_ENABLED,
                SIGNAL_VALIDATOR_HIGH_PRECISION_TFS,
                SIGNAL_VALIDATOR_HIGH_PRECISION_MIN_CONF,
            )
            self.precision_mode_enabled = bool(SIGNAL_VALIDATOR_PRECISION_MODE)
            self.target_win_rate = max(0.0, min(1.0, float(SIGNAL_VALIDATOR_TARGET_WIN_RATE)))
            self.recent_window = max(5, int(SIGNAL_VALIDATOR_RECENT_WINDOW))
            self.min_bin_samples = max(3, int(SIGNAL_VALIDATOR_MIN_BIN_SAMPLES))
            self.winrate_conf_slope = max(0.0, float(SIGNAL_VALIDATOR_WINRATE_CONF_SLOPE))
            self.coldstart_min_conf = max(0.0, min(0.999, float(SIGNAL_VALIDATOR_COLDSTART_MIN_CONF)))
            self.hot_min_conf = max(0.0, min(0.999, float(SIGNAL_VALIDATOR_HOT_MIN_CONF)))
            self.high_precision_profile_enabled = bool(SIGNAL_VALIDATOR_HIGH_PRECISION_PROFILE_ENABLED)
            self.high_precision_tfs = {str(x).strip() for x in (SIGNAL_VALIDATOR_HIGH_PRECISION_TFS or []) if str(x).strip()}
            self.high_precision_min_conf = max(0.0, min(0.999, float(SIGNAL_VALIDATOR_HIGH_PRECISION_MIN_CONF)))
        except Exception:
            self.precision_mode_enabled = True
            self.target_win_rate = 0.90
            self.recent_window = 20
            self.min_bin_samples = 8
            self.winrate_conf_slope = 0.35
            self.coldstart_min_conf = 0.93
            self.hot_min_conf = 0.90
            self.high_precision_profile_enabled = False
            self.high_precision_tfs = {"4h"}
            self.high_precision_min_conf = 0.90
        
        # Signal outcome history for confidence calibration
        self.signal_outcomes: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        # Format: symbol -> [(confidence, actual_pnl_pct, was_correct), ...]
        
        # Confidence calibration data
        self.confidence_calibration: Dict[str, Dict] = defaultdict(lambda: {
            'bins': {0.5: [], 0.6: [], 0.7: [], 0.8: [], 0.9: []},  # confidence bin -> [actual outcomes]
            'true_accuracy': {}  # confidence bin -> actual accuracy
        })
        
        self._lock = threading.RLock()
        logger.info("[SIGNAL-VALIDATOR] SignalValidator initialized")

    @staticmethod
    def skip_code_from_reason(reason: str) -> str:
        """Map validator human-readable reason to a stable skip/telemetry code."""
        r = str(reason or "")
        for marker in (
            "HP_TF_FILTER",
            "HP_CONF_FILTER",
            "COLDSTART_PRECISION_CONF",
            "HOT_PRECISION_CONF",
            "PRECISION_GATE",
            "BIN_PRECISION_GATE",
        ):
            if marker in r:
                return marker
        if "BACKTEST FAIL" in r:
            return "BACKTEST_FAIL"
        if "OVERCONFIDENT" in r:
            return "OVERCONFIDENT"
        return "VALIDATOR_BLOCK"

    def _is_exposure_increasing_action(self, action: str) -> bool:
        """True for actions that add/increase directional exposure."""
        a = str(action or "").upper()
        if not a:
            return False
        if "CLOSE" in a or "REDUCE" in a or "EXIT" in a:
            return False
        if a in {"HOLD", "WAIT", "NONE", "HEARTBEAT"}:
            return False
        if "OPEN" in a or "FLIP" in a or "INCREASE" in a:
            return True
        # Protective hedges are risk-adds for margin: same precision admission as entries.
        if "HEDGE" in a and ("ADD_" in a or "OPEN_" in a or a.startswith("ADD_HEDGE") or a.startswith("OPEN_HEDGE")):
            return True
        # Compatibility: some payloads send action-like LONG/SHORT without OPEN_ prefix
        return ("LONG" in a or "SHORT" in a)
    
    def record_signal_outcome(self, symbol: str, predicted_action: str, 
                               confidence: float, actual_pnl_pct: float):
        """Record the outcome of a signal for calibration"""
        with self._lock:
            was_correct = actual_pnl_pct > 0
            self.signal_outcomes[symbol].append((confidence, actual_pnl_pct, was_correct))
            
            # Update confidence calibration
            conf_bin = self._get_confidence_bin(confidence)
            cal_data = self.confidence_calibration[symbol]
            cal_data['bins'][conf_bin].append(was_correct)
            
            # Recalculate true accuracy for this bin
            outcomes = cal_data['bins'][conf_bin]
            if len(outcomes) >= 5:
                cal_data['true_accuracy'][conf_bin] = sum(outcomes) / len(outcomes)
    
    def _get_confidence_bin(self, confidence: float) -> float:
        """Map confidence to nearest bin"""
        bins = [0.5, 0.6, 0.7, 0.8, 0.9]
        for b in reversed(bins):
            if confidence >= b:
                return b
        return 0.5
    
    def get_calibrated_confidence(self, symbol: str, raw_confidence: float) -> float:
        """
        Get calibrated confidence based on historical accuracy.
        
        If model says 90% confidence but only 60% of those trades are profitable,
        return 60% as the true confidence.
        """
        with self._lock:
            cal_data = self.confidence_calibration.get(symbol)
            if not cal_data:
                return raw_confidence
            
            conf_bin = self._get_confidence_bin(raw_confidence)
            true_acc = cal_data['true_accuracy'].get(conf_bin)
            
            if true_acc is not None:
                # Blend raw confidence with calibrated accuracy
                calibrated = (raw_confidence + true_acc) / 2
                if abs(calibrated - raw_confidence) > 0.1:
                    logger.info(f"[CALIBRATION] {symbol}: Raw conf {raw_confidence:.2f} -> "
                               f"Calibrated {calibrated:.2f} (true accuracy: {true_acc:.2f})")
                return calibrated
            
            return raw_confidence
    
    def validate_signal(self, symbol: str, action: str, confidence: float,
                        market_features: Dict = None) -> Tuple[bool, str, float]:
        """
        Validate a signal before it goes live.
        
        Returns:
            (should_execute, reason, adjusted_confidence)
        """
        with self._lock:
            # Get calibrated confidence
            calibrated_conf = self.get_calibrated_confidence(symbol, confidence)
            
            # Check if we have enough history
            outcomes = self.signal_outcomes.get(symbol, [])

            # Strict confidence floors for exposure-increasing actions
            if self.precision_mode_enabled and self._is_exposure_increasing_action(action):
                # Optional profile lock for paper/high-precision mode.
                if self.high_precision_profile_enabled:
                    tf = str((market_features or {}).get("timeframe") or "").strip()
                    if self.high_precision_tfs and tf and tf not in self.high_precision_tfs:
                        return False, (
                            f"⛔ HP_TF_FILTER: {symbol} tf={tf} not in {sorted(self.high_precision_tfs)}"
                        ), calibrated_conf
                    if calibrated_conf < self.high_precision_min_conf:
                        return False, (
                            f"⛔ HP_CONF_FILTER: {symbol} calibrated {calibrated_conf:.3f} "
                            f"< hp_min {self.high_precision_min_conf:.3f}"
                        ), calibrated_conf

                if len(outcomes) < self.min_backtest_samples:
                    if calibrated_conf < self.coldstart_min_conf:
                        return False, (
                            f"⛔ COLDSTART_PRECISION_CONF: {symbol} calibrated {calibrated_conf:.3f} "
                            f"< floor {self.coldstart_min_conf:.3f}"
                        ), calibrated_conf
                elif calibrated_conf < self.hot_min_conf:
                    return False, (
                        f"⛔ HOT_PRECISION_CONF: {symbol} calibrated {calibrated_conf:.3f} "
                        f"< floor {self.hot_min_conf:.3f}"
                    ), calibrated_conf
            
            if len(outcomes) < self.min_backtest_samples:
                return True, f"Insufficient history ({len(outcomes)}/{self.min_backtest_samples})", calibrated_conf
            
            # Calculate recent win rate for this confidence level
            conf_bin = self._get_confidence_bin(confidence)
            recent_similar = [o for o in outcomes if self._get_confidence_bin(o[0]) == conf_bin]

            # Precision mode: exposure-increasing actions are admitted only when
            # recent realized outcomes support high precision.
            if self.precision_mode_enabled and self._is_exposure_increasing_action(action):
                # 1) Overall recent symbol precision gate
                recent_all = list(outcomes)[-self.recent_window:]
                if len(recent_all) >= max(self.min_bin_samples, self.min_backtest_samples):
                    recent_wins_all = sum(1 for _, _, correct in recent_all if correct)
                    recent_wr_all = recent_wins_all / len(recent_all)
                    if recent_wr_all < self.target_win_rate:
                        wr_gap = self.target_win_rate - recent_wr_all
                        required_conf = min(0.995, confidence + (wr_gap * self.winrate_conf_slope))
                        if calibrated_conf < required_conf:
                            return False, (
                                f"⛔ PRECISION_GATE: {symbol} recent WR {recent_wr_all:.0%} "
                                f"< target {self.target_win_rate:.0%}; calibrated {calibrated_conf:.3f} "
                                f"< req {required_conf:.3f}"
                            ), calibrated_conf

                # 2) Confidence-bin local precision gate
                if len(recent_similar) >= self.min_bin_samples:
                    local = recent_similar[-self.recent_window:]
                    local_wins = sum(1 for _, _, correct in local if correct)
                    local_wr = local_wins / len(local)
                    if local_wr < self.target_win_rate:
                        return False, (
                            f"⛔ BIN_PRECISION_GATE: {symbol} conf-bin {conf_bin:.0%} "
                            f"WR {local_wr:.0%} < target {self.target_win_rate:.0%}"
                        ), calibrated_conf
            
            if len(recent_similar) >= 5:
                recent_wins = sum(1 for _, _, correct in recent_similar[-10:] if correct)
                recent_win_rate = recent_wins / min(10, len(recent_similar))
                
                if recent_win_rate < 0.35:
                    return False, f"⛔ BACKTEST FAIL: {symbol} @ {conf_bin:.0%} conf only {recent_win_rate:.0%} win rate", calibrated_conf
            
            # Check for confidence inflation
            if calibrated_conf < confidence - 0.15:
                return False, f"⚠️ OVERCONFIDENT: Raw {confidence:.0%} but calibrated {calibrated_conf:.0%}", calibrated_conf
            
            return True, "✅ Backtest validation passed", calibrated_conf
    
    def get_calibration_report(self, symbol: str = None) -> Dict:
        """Get confidence calibration report"""
        with self._lock:
            if symbol:
                cal_data = self.confidence_calibration.get(symbol, {})
                return {
                    'symbol': symbol,
                    'calibration': cal_data.get('true_accuracy', {}),
                    'sample_counts': {k: len(v) for k, v in cal_data.get('bins', {}).items()}
                }
            
            # Overall report
            report = {}
            for sym, data in self.confidence_calibration.items():
                if data.get('true_accuracy'):
                    report[sym] = {
                        'calibration': data['true_accuracy'],
                        'samples': sum(len(v) for v in data['bins'].values())
                    }
            return report


class ExecutionFeedbackConsumer:
    """
    Consumes execution feedback from Redis and updates TradeOutcomeTracker.
    
    Uses Redis consumer groups for idempotent processing:
    - No duplicate processing on restart
    - Persistent offset tracking
    - Dedupe keys with TTL to prevent double-processing
    
    Runs in a background thread, listening to 'executed_signals' stream.
    """
    
    def __init__(self, redis_client, outcome_tracker: TradeOutcomeTracker,
                 signal_validator: SignalValidator):
        self.redis = redis_client
        self.outcome_tracker = outcome_tracker
        self.signal_validator = signal_validator

        self._running = False
        self._thread = None
        
        # Consumer group configuration for idempotency
        self.stream_name = 'executed_signals'
        self.consumer_group = 'feedback_processors'
        self.consumer_name = f'trainer_{os.getpid()}'  # Unique per process
        
        # Dedupe configuration
        self.dedupe_ttl_sec = 300  # 5 minutes TTL for dedupe keys

        # Persist last processed ID for safe resume on restart
        self._last_id_key = f"feedback:last_id:{self.consumer_group}"
        self._last_id = None
        
        # Initialize consumer group (create if doesn't exist)
        self._init_consumer_group()
        
        logger.info(f"[EXEC-FEEDBACK-CONSUMER] Initialized with consumer group '{self.consumer_group}', consumer '{self.consumer_name}'")
    
    def _init_consumer_group(self):
        """
        Initialize Redis consumer group for idempotent processing.
        Creates the group if it doesn't exist, starting from the current stream position.
        """
        try:
            # Try to create consumer group starting from '0' (beginning)
            # This allows catching up on recent history on first initialization
            self.redis.xgroup_create(
                name=self.stream_name,
                groupname=self.consumer_group,
                id='0',  # Start from beginning for initial catchup
                mkstream=True
            )
            logger.info(f"[EXEC-FEEDBACK-CONSUMER] Created new consumer group '{self.consumer_group}' starting from beginning")
        except Exception as e:
            # Group already exists - this is normal on restart
            if 'BUSYGROUP' in str(e):
                logger.info(f"[EXEC-FEEDBACK-CONSUMER] Consumer group '{self.consumer_group}' already exists (resuming from last position)")
            else:
                logger.warning(f"[EXEC-FEEDBACK-CONSUMER] Error initializing consumer group: {e}")
    
    def _is_duplicate(self, execution_id: str) -> bool:
        """
        Check if execution has already been processed using dedupe key.
        
        Args:
            execution_id: Unique identifier for the execution
            
        Returns:
            True if already processed, False otherwise
        """
        dedupe_key = f"feedback:dedupe:{execution_id}"
        
        # Try to set the key with NX (only if not exists)
        result = self.redis.set(dedupe_key, '1', nx=True, ex=self.dedupe_ttl_sec)
        
        # If result is None, key already existed (duplicate)
        if result is None:
            return True
        
        return False
    
    def start(self):
        """Start the background consumer thread.
        
        The consume loop handles pending message draining internally
        (starts with ID '0' to drain all pending, then switches to '>').
        No need to restore a specific message ID here.
        """
        if self._running:
            return
        
        self._running = True
        self._thread = threading.Thread(target=self._consume_loop, daemon=True)
        self._thread.start()
        logger.info("[EXEC-FEEDBACK-CONSUMER] Started background thread")
    
    def stop(self):
        """Stop the consumer"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
    
    def _consume_loop(self):
        """
        Main consumption loop using Redis consumer groups for idempotency.
        
        Uses XREADGROUP to ensure:
        - No duplicate processing on restart
        - Persistent offset tracking
        - Automatic recovery from crashes
        """
        logger.info("[EXEC-FEEDBACK-CONSUMER] ✅ Consumer loop started with idempotent processing")
        processed_count = 0
        duplicate_count = 0
        # Phase 1: drain any pending (unACK'd) messages from previous crash.
        # Use '0' to read all pending messages for this consumer.
        # Phase 2: switch to '>' for new messages once pending is drained.
        _reading_pending = True
        _pending_start_id = '0'
        
        while self._running:
            try:
                # When reading pending messages, use the stored start_id.
                # When reading new messages, use '>' to get undelivered messages.
                if _reading_pending:
                    start_id = _pending_start_id
                else:
                    start_id = '>'
                result = self.redis.xreadgroup(
                    groupname=self.consumer_group,
                    consumername=self.consumer_name,
                    streams={self.stream_name: start_id},
                    count=50,  # Process in smaller batches for better responsiveness
                    block=1000  # Block for 1 second waiting for new messages
                )
                
                # If we were reading pending and got nothing, all pending are drained.
                # Switch to reading new messages with '>'.
                if _reading_pending:
                    has_messages = result and any(len(msgs) > 0 for _, msgs in result)
                    if not has_messages:
                        _reading_pending = False
                        logger.info("[EXEC-FEEDBACK-CONSUMER] ✅ All pending messages drained — switching to '>' for new messages")
                        continue

                if result:
                    for stream_name, messages in result:
                        logger.debug(f"[EXEC-FEEDBACK-CONSUMER] 📬 Processing {len(messages)} new trades")
                        
                        for message_id, message_data in messages:
                            try:
                                # Extract execution_id for deduplication
                                data_str = message_data.get(b'data') or message_data.get('data')
                                if isinstance(data_str, bytes):
                                    data_str = data_str.decode()
                                execution = json.loads(data_str)
                                
                                # Create unique execution_id from message
                                execution_id = execution.get('execution_id') or f"{execution.get('symbol')}_{execution.get('action')}_{message_id}"
                                
                                # Check for duplicates
                                if self._is_duplicate(execution_id):
                                    duplicate_count += 1
                                    logger.debug(f"[EXEC-FEEDBACK-CONSUMER] ⏭️ Skipping duplicate execution: {execution_id}")
                                    # Still ACK the message to remove it from pending
                                    self.redis.xack(self.stream_name, self.consumer_group, message_id)
                                    continue
                                
                                # Process the execution
                                self._process_execution(message_data)
                                processed_count += 1
                                
                                # ACK the message to mark it as processed
                                self.redis.xack(self.stream_name, self.consumer_group, message_id)
                                # Persist last processed ID for crash-safe resume
                                try:
                                    self._last_id = message_id
                                    self.redis.set(self._last_id_key, message_id, ex=3600)
                                except Exception:
                                    pass
                                
                                if processed_count % 10 == 0:
                                    logger.info(f"[EXEC-FEEDBACK-CONSUMER] 📊 Stats: {processed_count} processed, {duplicate_count} duplicates skipped")
                                
                            except Exception as e:
                                logger.error(f"[EXEC-FEEDBACK-CONSUMER] Failed to process message {message_id}: {e}")
                                # Don't ACK failed messages - they'll be reprocessed
                
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"[EXEC-FEEDBACK-CONSUMER] Error in consume loop: {e}")
                time.sleep(1)
    
    def _process_execution(self, message_data: dict):
        """Process a single execution message"""
        try:
            data_str = message_data.get(b'data') or message_data.get('data')
            if isinstance(data_str, bytes):
                data_str = data_str.decode()

            execution = json.loads(data_str)

            symbol = execution.get('symbol')
            action = execution.get('action', '')
            success = execution.get('success', False)
            executed_price = float(execution.get('executed_price', 0))
            executed_qty = float(execution.get('executed_qty', 0))

            if not success:
                logger.debug(f"[EXEC-FEEDBACK] Skipping failed execution: {symbol} {action}")
                return
            
            # Allow 0 price for failed closes (position already closed)
            if executed_price == 0 and 'CLOSE' not in action.upper():
                logger.debug(f"[EXEC-FEEDBACK] Skipping zero-price non-close: {symbol} {action}")
                return
            
            # Determine if this is an open or close
            action_upper = action.upper()
            
            if 'OPEN' in action_upper or (('LONG' in action_upper or 'SHORT' in action_upper) 
                                           and 'CLOSE' not in action_upper):
                # Opening a position
                confidence = execution.get('confidence', execution.get('model_confidence', 0.5))
                timeframe = execution.get('timeframe', '1h')
                self.outcome_tracker.record_trade_open(
                    symbol=symbol,
                    action=action,
                    entry_price=executed_price,
                    quantity=executed_qty,
                    confidence=confidence,
                    timeframe=timeframe
                )
            
            elif 'CLOSE' in action_upper:
                # Closing a position
                trade = self.outcome_tracker.record_trade_close(
                    symbol=symbol,
                    action=action,
                    exit_price=executed_price,
                    quantity=executed_qty
                )
                
                if trade:
                    # Update signal validator with outcome
                    self.signal_validator.record_signal_outcome(
                        symbol=symbol,
                        predicted_action=action,
                        confidence=trade.signal_confidence,
                        actual_pnl_pct=trade.pnl_pct
                    )
        
        except Exception as e:
            logger.error(f"[EXEC-FEEDBACK-CONSUMER] Failed to process execution: {e}")


# Global instances (initialized by trainer)
_outcome_tracker: Optional[TradeOutcomeTracker] = None
_signal_validator: Optional[SignalValidator] = None
_feedback_consumer: Optional[ExecutionFeedbackConsumer] = None


def initialize_feedback_system(redis_client) -> Tuple[TradeOutcomeTracker, SignalValidator, ExecutionFeedbackConsumer]:
    """
    Initialize the complete feedback system with singleton pattern.
    
    Ensures only ONE feedback consumer runs per trainer process.
    Uses PID-based guard to prevent duplicate initialization across worker spawns.
    
    Call this from the trainer during initialization.
    """
    global _outcome_tracker, _signal_validator, _feedback_consumer
    
    # Singleton guard: Check if already initialized in this process
    if _feedback_consumer is not None and _feedback_consumer._running:
        logger.info(f"🎯 [TRADE-FEEDBACK] Already initialized in PID {os.getpid()}, reusing existing instance")
        return _outcome_tracker, _signal_validator, _feedback_consumer
    
    # Initialize components
    _outcome_tracker = TradeOutcomeTracker(redis_client=redis_client)
    _signal_validator = SignalValidator(redis_client=redis_client)
    _feedback_consumer = ExecutionFeedbackConsumer(
        redis_client=redis_client,
        outcome_tracker=_outcome_tracker,
        signal_validator=_signal_validator
    )
    
    # Start the consumer (only once per process)
    _feedback_consumer.start()
    
    logger.info(f"🎯 [TRADE-FEEDBACK] Complete feedback system initialized and running in PID {os.getpid()}")
    
    return _outcome_tracker, _signal_validator, _feedback_consumer


def get_outcome_tracker() -> Optional[TradeOutcomeTracker]:
    return _outcome_tracker


def get_signal_validator() -> Optional[SignalValidator]:
    return _signal_validator


