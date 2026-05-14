"""
Win Rate Optimizer - Adaptive Confidence System
Target: Maximize win rate through strict quality filters
"""

import logging
import time
from typing import Dict, Any, Optional, Tuple
from collections import deque
import json

# ── Strict mode config (Apr 2026 Audit) ──────────────────────────────
# When WIN_RATE_STRICT_MODE=true: high WR → tighten confidence (not relax),
# and HighQualitySignalFilter will actually BLOCK below-threshold signals.
try:
    from config import (
        WIN_RATE_STRICT_MODE as _WR_STRICT,
        WIN_RATE_STRICT_TARGET as _WR_STRICT_TARGET,
        WIN_RATE_STRICT_CONF_FLOOR as _WR_STRICT_FLOOR,
    )
    _WR_STRICT = bool(_WR_STRICT)
    _WR_STRICT_TARGET = float(_WR_STRICT_TARGET)
    _WR_STRICT_FLOOR = float(_WR_STRICT_FLOOR)
except Exception:
    _WR_STRICT = False
    _WR_STRICT_TARGET = 0.90
    _WR_STRICT_FLOOR = 0.90

logger = logging.getLogger(__name__)


class WinRateTracker:
    """
    Tracks win rate per symbol, timeframe, and overall.
    Adjusts confidence thresholds dynamically to maintain high win rate.
    """
    
    def __init__(self, target_win_rate: float = 0.65):
        self.target_win_rate = target_win_rate
        
        # Track trades per symbol
        self.trades_by_symbol = {}  # {symbol: {'wins': 0, 'losses': 0, 'total': 0, 'pnl': 0.0}}
        
        # Track trades per timeframe
        self.trades_by_tf = {}  # {tf: {'wins': 0, 'losses': 0, 'total': 0}}
        
        # Track recent trades (last 100)
        self.recent_trades = deque(maxlen=100)
        
        # Adaptive confidence thresholds - RELAXED
        self.min_confidence = 0.75  # Start more relaxed
        self.current_confidence = 0.75
        
        # Performance windows
        self.last_10_trades = deque(maxlen=10)
        self.last_50_trades = deque(maxlen=50)
        
        logger.info(f"🎯 WinRateTracker initialized: Target={target_win_rate:.1%}, Min Confidence={self.min_confidence:.1%}")
    
    def record_trade(self, symbol: str, timeframe: str, is_win: bool, pnl_pct: float, confidence: float):
        """Record trade outcome and update statistics"""
        trade_record = {
            'symbol': symbol,
            'timeframe': timeframe,
            'is_win': is_win,
            'pnl_pct': pnl_pct,
            'confidence': confidence,
            'timestamp': time.time()
        }
        
        self.recent_trades.append(trade_record)
        self.last_10_trades.append(is_win)
        self.last_50_trades.append(is_win)
        
        # Update per-symbol stats
        if symbol not in self.trades_by_symbol:
            self.trades_by_symbol[symbol] = {'wins': 0, 'losses': 0, 'total': 0}
        
        self.trades_by_symbol[symbol]['total'] += 1
        self.trades_by_symbol[symbol]['pnl'] += pnl_pct
        if is_win:
            self.trades_by_symbol[symbol]['wins'] += 1
        else:
            self.trades_by_symbol[symbol]['losses'] += 1
        
        # Update per-timeframe stats
        if timeframe not in self.trades_by_tf:
            self.trades_by_tf[timeframe] = {'wins': 0, 'losses': 0, 'total': 0}
        
        self.trades_by_tf[timeframe]['total'] += 1
        if is_win:
            self.trades_by_tf[timeframe]['wins'] += 1
        else:
            self.trades_by_tf[timeframe]['losses'] += 1
        
        # Adjust confidence threshold
        self._adjust_confidence_threshold()
        
        logger.info(f"📊 Trade recorded: {symbol} {timeframe} {'WIN' if is_win else 'LOSS'} ({pnl_pct:+.2f}%) | Recent WR: {self.get_recent_win_rate():.1%}")
    
    def _adjust_confidence_threshold(self):
        """Dynamically adjust confidence threshold based on recent win rate and PNL.
        
        STRICT MODE (Apr 2026 Audit): Inverts logic — good WR → tighten confidence
        to maintain quality, instead of relaxing. Floor = WIN_RATE_STRICT_CONF_FLOOR.
        """
        if len(self.last_10_trades) >= 5:
            recent_wr = sum(self.last_10_trades) / len(self.last_10_trades)
            
            if _WR_STRICT:
                # ── STRICT MODE: tighten on success, raise hard on failure ──
                if recent_wr < 0.40:
                    self.current_confidence = max(_WR_STRICT_FLOOR, 0.92)
                    logger.warning(
                        f"⚠️ [WR_STRICT_TIGHTEN] Win rate critical ({recent_wr:.1%}) "
                        f"- Confidence raised to {self.current_confidence:.1%}"
                    )
                elif recent_wr < 0.50:
                    self.current_confidence = max(_WR_STRICT_FLOOR, 0.90)
                    logger.info(
                        f"📊 [WR_STRICT_TIGHTEN] Win rate below 50% ({recent_wr:.1%}) "
                        f"- Confidence at {self.current_confidence:.1%}"
                    )
                elif recent_wr >= _WR_STRICT_TARGET:
                    # Excellent WR → tighten further (+2%) to preserve quality
                    self.current_confidence = min(0.98, self.current_confidence + 0.02)
                    self.current_confidence = max(_WR_STRICT_FLOOR, self.current_confidence)
                    logger.info(
                        f"✅ [WR_STRICT_TIGHTEN] Win rate excellent ({recent_wr:.1%}) "
                        f"- Tightening confidence to {self.current_confidence:.1%} (preserve quality)"
                    )
                else:
                    self.current_confidence = max(_WR_STRICT_FLOOR, 0.88)
                    logger.debug(
                        f"[WR_STRICT_TIGHTEN] Win rate normal ({recent_wr:.1%}) "
                        f"- Confidence at {self.current_confidence:.1%}"
                    )
            else:
                # ── RELAXED MODE (original behavior) ──
                if recent_wr < 0.40:
                    self.current_confidence = 0.85
                    logger.warning(f"⚠️ Win rate very low ({recent_wr:.1%}) - Increasing confidence to {self.current_confidence:.1%}")
                elif recent_wr < 0.50:
                    self.current_confidence = 0.80
                    logger.info(f"📊 Win rate below 50% ({recent_wr:.1%}) - Confidence at {self.current_confidence:.1%}")
                elif recent_wr >= 0.70:
                    self.current_confidence = max(0.70, self.current_confidence - 0.02)
                    logger.info(f"✅ Win rate strong ({recent_wr:.1%}) - Confidence at {self.current_confidence:.1%}")
                else:
                    self.current_confidence = 0.75
    
    def get_recent_win_rate(self) -> float:
        """Get win rate from last 10 trades"""
        if len(self.last_10_trades) == 0:
            return 0.0
        return sum(self.last_10_trades) / len(self.last_10_trades)
    
    def get_overall_win_rate(self) -> float:
        """Get overall win rate"""
        total_wins = sum(stats['wins'] for stats in self.trades_by_symbol.values())
        total_trades = sum(stats['total'] for stats in self.trades_by_symbol.values())
        return total_wins / total_trades if total_trades > 0 else 0.0
    
    def get_symbol_win_rate(self, symbol: str) -> float:
        """Get win rate for specific symbol"""
        if symbol not in self.trades_by_symbol:
            return 0.0
        stats = self.trades_by_symbol[symbol]
        return stats['wins'] / stats['total'] if stats['total'] > 0 else 0.0
    
    def should_trade_symbol(self, symbol: str, min_trades: int = 10) -> Tuple[bool, str]:
        """Check if symbol is profitable (NO BLOCKING, just info)"""
        if symbol not in self.trades_by_symbol:
            return True, "New symbol - allowed"
        
        stats = self.trades_by_symbol[symbol]
        if stats['total'] < min_trades:
            return True, f"Learning: {symbol} ({stats['total']} trades)"
        
        win_rate = stats['wins'] / stats['total']
        total_pnl = stats.get('pnl', 0.0)
        
        # NO BLOCKING - just provide information
        if total_pnl > 0:
            return True, f"Profitable: {symbol} WR={win_rate:.1%}, PNL={total_pnl:+.2f}%"
        else:
            return True, f"Learning: {symbol} WR={win_rate:.1%}, PNL={total_pnl:+.2f}%"
    
    def get_required_confidence(self) -> float:
        """Get current required confidence threshold"""
        return self.current_confidence
    
    def get_stats_summary(self) -> Dict[str, Any]:
        """Get comprehensive statistics"""
        return {
            'overall_win_rate': self.get_overall_win_rate(),
            'recent_win_rate_10': self.get_recent_win_rate(),
            'recent_win_rate_50': sum(self.last_50_trades) / len(self.last_50_trades) if len(self.last_50_trades) > 0 else 0.0,
            'current_confidence_threshold': self.current_confidence,
            'total_trades': sum(stats['total'] for stats in self.trades_by_symbol.values()),
            'best_symbols': self._get_best_symbols(3),
            'worst_symbols': self._get_worst_symbols(3)
        }
    
    def _get_best_symbols(self, n: int = 3):
        """Get top N symbols by win rate"""
        symbols_with_wr = []
        for symbol, stats in self.trades_by_symbol.items():
            if stats['total'] >= 3:  # Minimum trades for consideration
                wr = stats['wins'] / stats['total']
                symbols_with_wr.append((symbol, wr, stats['total']))
        
        symbols_with_wr.sort(key=lambda x: x[1], reverse=True)
        return symbols_with_wr[:n]
    
    def _get_worst_symbols(self, n: int = 3):
        """Get bottom N symbols by win rate"""
        symbols_with_wr = []
        for symbol, stats in self.trades_by_symbol.items():
            if stats['total'] >= 3:
                wr = stats['wins'] / stats['total']
                symbols_with_wr.append((symbol, wr, stats['total']))
        
        symbols_with_wr.sort(key=lambda x: x[1])
        return symbols_with_wr[:n]


class HighQualitySignalFilter:
    """
    Ultra-strict signal filtering to maximize win rate.
    Only allows highest-quality signals.
    """
    
    def __init__(self, win_rate_tracker: WinRateTracker):
        self.win_rate_tracker = win_rate_tracker
        logger.info("🔍 HighQualitySignalFilter initialized")
    
    def should_execute_signal(
        self,
        symbol: str,
        timeframe: str,
        action: str,
        confidence: float,
        multi_tf_agreement: float = 0.5,  # % of TFs that agree
        trend_strength: float = 0.5,
        position_quality_score: float = 0.5  # 0-1 score based on various factors
    ) -> Tuple[bool, str]:
        """
        Signal quality filter.
        
        RELAXED MODE (default): NO BLOCKING, only confidence-based adjustment.
        STRICT MODE (WIN_RATE_STRICT_MODE=true): Actually blocks below-threshold signals.
        
        Returns (should_execute, reason)
        """
        
        # 1. Check required confidence threshold
        required_conf = self.win_rate_tracker.get_required_confidence()
        if confidence < required_conf:
            if _WR_STRICT:
                # ── STRICT: hard block ──
                logger.warning(
                    f"🚫 [WR_STRICT_BLOCK] {symbol} {action} | "
                    f"conf={confidence:.1%} < required={required_conf:.1%} — signal blocked"
                )
                return False, f"[WR_STRICT_BLOCK] conf={confidence:.1%} < required={required_conf:.1%}"
            else:
                # RELAXED: allow but note it
                return True, f"Below adaptive threshold ({confidence:.1%} < {required_conf:.1%}) - monitoring"
        
        # 2. Get symbol info (NO BLOCKING, just logging)
        should_trade, symbol_reason = self.win_rate_tracker.should_trade_symbol(symbol)
        
        # 3. Quality scoring
        quality_notes = []
        
        if multi_tf_agreement >= 0.60:
            quality_notes.append(f"TF={multi_tf_agreement:.0%}")
        
        if trend_strength >= 0.40:
            quality_notes.append(f"trend={trend_strength:.2f}")
        
        if position_quality_score >= 0.60:
            quality_notes.append(f"quality={position_quality_score:.2f}")
        
        quality_str = ", ".join(quality_notes) if quality_notes else "learning"
        return True, f"✅ Allowed: conf={confidence:.1%} ({quality_str}) | {symbol_reason}"


class AdaptiveRiskManager:
    """
    Adjusts position sizing and risk based on win rate performance.
    """
    
    def __init__(self, win_rate_tracker: WinRateTracker):
        self.win_rate_tracker = win_rate_tracker
        self.base_position_size = 0.10  # 10% of equity per position
        logger.info("💰 AdaptiveRiskManager initialized")
    
    def get_position_size(self, confidence: float) -> float:
        """
        Calculate position size based on confidence and recent performance.
        Returns fraction of equity (0.0-1.0)
        """
        recent_wr = self.win_rate_tracker.get_recent_win_rate()
        
        # Reduce size if recent performance is poor
        if recent_wr < 0.70:
            size_multiplier = 0.5  # Half size
        elif recent_wr < 0.80:
            size_multiplier = 0.75
        elif recent_wr >= 0.90:
            size_multiplier = 1.2  # Slightly larger when doing well
        else:
            size_multiplier = 1.0
        
        # Also scale by confidence
        confidence_multiplier = confidence  # 90% conf = 0.9x, 95% = 0.95x
        
        final_size = self.base_position_size * size_multiplier * confidence_multiplier
        
        # Cap at 15% of equity
        return min(final_size, 0.15)
    
    def should_take_profit_early(self, current_pnl_pct: float, recent_wr: float) -> Tuple[bool, str]:
        """
        If win rate is suffering, take profits earlier to lock in wins.
        """
        recent_wr = self.win_rate_tracker.get_recent_win_rate()
        
        if recent_wr < 0.70:
            # In slump - take profits early
            if current_pnl_pct >= 1.0:
                return True, f"Take profit early (WR={recent_wr:.1%}, profit={current_pnl_pct:.1f}%)"
        elif recent_wr < 0.80:
            if current_pnl_pct >= 2.0:
                return True, f"Take profit conservatively (WR={recent_wr:.1%}, profit={current_pnl_pct:.1f}%)"
        
        return False, "Let it run"


class WinRateMonitor:
    """
    Monitors and logs win rate statistics periodically.
    Alerts if win rate drops below target.
    """
    
    def __init__(self, win_rate_tracker: WinRateTracker):
        self.win_rate_tracker = win_rate_tracker
        self.last_report_time = 0
        self.report_interval = 300  # 5 minutes
        logger.info("📊 WinRateMonitor initialized")
    
    def check_and_report(self):
        """Check win rate and report if needed"""
        now = time.time()
        if now - self.last_report_time < self.report_interval:
            return
        
        self.last_report_time = now
        
        stats = self.win_rate_tracker.get_stats_summary()
        
        overall_wr = stats['overall_win_rate']
        recent_wr = stats['recent_win_rate_10']
        
        # Log report
        logger.info("=" * 70)
        logger.info(f"📊 WIN RATE REPORT")
        logger.info(f"   Overall: {overall_wr:.1%} | Recent (10): {recent_wr:.1%} | Recent (50): {stats['recent_win_rate_50']:.1%}")
        logger.info(f"   Total Trades: {stats['total_trades']}")
        logger.info(f"   Current Confidence Threshold: {stats['current_confidence_threshold']:.1%}")
        
        if stats['best_symbols']:
            logger.info(f"   Best Symbols: {', '.join([f'{s}:{wr:.1%}' for s, wr, _ in stats['best_symbols']])}")
        
        if stats['worst_symbols']:
            logger.warning(f"   Worst Symbols: {', '.join([f'{s}:{wr:.1%}' for s, wr, _ in stats['worst_symbols']])}")
        
        # Alert if below target
        if overall_wr < 0.70:
            logger.error(f"🚨 WIN RATE CRITICAL: {overall_wr:.1%} - System restricting trades!")
        elif overall_wr < 0.80:
            logger.warning(f"⚠️ WIN RATE BELOW TARGET: {overall_wr:.1%} - Increasing quality filters")
        elif overall_wr >= 0.90:
            logger.info(f"🎯 WIN RATE TARGET MET: {overall_wr:.1%} - Excellent!")
        
        logger.info("=" * 70)


# Integration helper
def create_win_rate_system(target_win_rate: float = 0.65):
    """
    Create all win rate optimization components.
    
    Args:
        target_win_rate: Target win rate (default 90%)
        
    Returns:
        tuple: (tracker, filter, risk_manager, monitor)
    """
    tracker = WinRateTracker(target_win_rate=target_win_rate)
    signal_filter = HighQualitySignalFilter(tracker)
    risk_manager = AdaptiveRiskManager(tracker)
    monitor = WinRateMonitor(tracker)
    
    logger.info(f"🎯 Win Rate Optimization System initialized: Target={target_win_rate:.1%}")
    
    return tracker, signal_filter, risk_manager, monitor

