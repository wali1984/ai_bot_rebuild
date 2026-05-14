"""
Auto-Contraction Mechanism
Automatically contracts symbol count back to base limits when safety conditions deteriorate
"""

import numpy as np
import logging
from typing import Dict, List, Optional, Tuple, Union, Set
from dataclasses import dataclass
from enum import Enum
import time
from collections import deque

logger = logging.getLogger(__name__)


class ContractionTrigger(Enum):
    """Triggers for auto-contraction"""
    CONFIDENCE_DROP = "confidence_drop"
    SAFETY_VIOLATION = "safety_violation"
    DRAWDOWN_LIMIT = "drawdown_limit"
    MARGIN_SHORTAGE = "margin_shortage"
    RISK_OVERLOAD = "risk_overload"
    MARKET_STRESS = "market_stress"
    MANUAL_TRIGGER = "manual_trigger"


class ContractionUrgency(Enum):
    """Urgency levels for contraction"""
    LOW = "low"         # Gradual reduction over time
    MEDIUM = "medium"   # Quick but orderly reduction
    HIGH = "high"       # Immediate emergency reduction
    CRITICAL = "critical"  # Force close all but core positions


@dataclass
class ContractionConfig:
    """Configuration for auto-contraction mechanism"""
    
    # Confidence thresholds for contraction
    confidence_contraction_threshold: float = 0.70  # Below this triggers contraction
    confidence_emergency_threshold: float = 0.50   # Below this triggers emergency contraction
    
    # Safety thresholds
    max_acceptable_drawdown: float = 0.05  # 5% max drawdown
    min_required_margin: float = 0.15     # 15% minimum free margin
    max_consecutive_losses: int = 4       # Max losses before contraction
    
    # Market stress indicators
    max_volatility_for_boost: float = 0.40  # Max volatility to maintain boost
    min_market_health: float = 0.40        # Min market health score
    
    # Contraction behavior
    gradual_contraction_steps: int = 3     # Steps to gradually reduce
    emergency_contraction_delay_seconds: int = 30  # Delay before emergency action
    
    # Cooldown periods
    contraction_cooldown_minutes: int = 15  # Min time between contractions
    reexpansion_cooldown_minutes: int = 60  # Min time before allowing re-expansion
    
    # Symbol priority for keeping during contraction
    core_symbols: List[str] = None  # Symbols to keep longest
    
    def __post_init__(self):
        if self.core_symbols is None:
            self.core_symbols = ["BTCUSDT", "ETHUSDT"]  # Default core symbols


class SymbolPrioritizer:
    """
    Prioritizes symbols for retention during contraction.
    
    Considers:
    - Profitability (PnL, Sharpe ratio)
    - Confidence scores
    - Liquidity and stability
    - Risk contribution
    - Core symbol status
    """
    
    def __init__(self, core_symbols: List[str] = None):
        """Initialize symbol prioritizer"""
        self.core_symbols = core_symbols or ["BTCUSDT", "ETHUSDT"]
    
    def prioritize_symbols_for_retention(
        self,
        portfolio_state: Dict,
        confidence_data: Dict,
        current_symbols: List[str]
    ) -> List[str]:
        """
        Prioritize symbols for retention during contraction.
        
        Args:
            portfolio_state: Current portfolio state
            confidence_data: Confidence scores per symbol
            current_symbols: Currently active symbols
            
        Returns:
            Symbols ordered by retention priority (highest first)
        """
        symbol_scores = {}
        
        for symbol in current_symbols:
            score = self._calculate_retention_score(
                symbol, portfolio_state, confidence_data
            )
            symbol_scores[symbol] = score
        
        # Sort by score (higher = keep longer)
        prioritized = sorted(
            symbol_scores.keys(),
            key=lambda s: symbol_scores[s],
            reverse=True
        )
        
        logger.info(f"Symbol retention priority: {prioritized}")
        
        return prioritized
    
    def _calculate_retention_score(
        self,
        symbol: str,
        portfolio_state: Dict,
        confidence_data: Dict
    ) -> float:
        """Calculate retention score for a symbol"""
        
        score = 0.0
        
        # Core symbol bonus (high priority)
        if symbol in self.core_symbols:
            score += 100.0
        
        # Position data
        positions = portfolio_state.get('positions', {})
        if symbol in positions:
            pos = positions[symbol]
            
            # PnL contribution (normalized)
            unrealized_pnl = pos.get('unrealized_pnl_long', 0) + pos.get('unrealized_pnl_short', 0)
            if unrealized_pnl > 0:
                score += min(unrealized_pnl / 100, 20.0)  # Cap at 20 points
            else:
                score += max(unrealized_pnl / 100, -20.0)  # Cap loss penalty at -20
            
            # Position health (margin efficiency)
            margin_used = pos.get('margin_used', 1)
            exposure = pos.get('total_exposure', 0)
            if margin_used > 0:
                efficiency = exposure / margin_used
                score += min(efficiency, 10.0)  # Cap at 10 points
        
        # Confidence score
        symbol_confidence = confidence_data.get(symbol, {})
        avg_confidence = symbol_confidence.get('average_confidence', 0.5)
        score += (avg_confidence - 0.5) * 40  # -20 to +20 points
        
        # Stability (inverse of volatility)
        volatility = symbol_confidence.get('confidence_volatility', 0.5)
        stability_bonus = max(0, (0.3 - volatility) * 20)  # Up to 6 points for low volatility
        score += stability_bonus
        
        # Recent performance trend
        recent_trend = symbol_confidence.get('confidence_trend', 0.0)
        score += recent_trend * 10  # -10 to +10 points
        
        return score


class AutoContractionManager:
    """
    Manages automatic symbol contraction based on deteriorating conditions.
    
    Monitors:
    - Confidence deterioration across symbols/timeframes
    - Safety limit violations
    - Market stress conditions
    - Risk accumulation
    
    Triggers graduated responses:
    1. Gradual contraction (reduce 1 symbol at a time)
    2. Quick contraction (reduce to base limits quickly)
    3. Emergency contraction (immediate reduction to core only)
    """
    
    def __init__(
        self,
        config: ContractionConfig = None,
        prioritizer: SymbolPrioritizer = None
    ):
        """
        Initialize auto-contraction manager.
        
        Args:
            config: Contraction configuration
            prioritizer: Symbol prioritizer
        """
        self.config = config or ContractionConfig()
        self.prioritizer = prioritizer or SymbolPrioritizer(self.config.core_symbols)
        
        # State tracking
        self.last_contraction_time = None
        self.contraction_in_progress = False
        self.contraction_triggers = deque(maxlen=10)  # Recent trigger history
        
        # Emergency state
        self.emergency_mode = False
        self.emergency_triggered_at = None
        
        logger.info("AutoContractionManager initialized")
    
    def evaluate_contraction_need(
        self,
        portfolio_state: Dict,
        confidence_data: Dict,
        current_symbols: List[str],
        market_conditions: Optional[Dict] = None
    ) -> Tuple[bool, ContractionUrgency, List[ContractionTrigger]]:
        """
        Evaluate if contraction is needed and determine urgency.
        
        Args:
            portfolio_state: Current portfolio state
            confidence_data: Confidence scores per symbol
            current_symbols: Currently active symbols
            market_conditions: Optional market condition data
            
        Returns:
            Tuple of (contraction_needed, urgency_level, triggered_reasons)
        """
        triggers = []
        urgency = ContractionUrgency.LOW
        
        # Check if in cooldown period
        if self._in_contraction_cooldown():
            return False, urgency, []
        
        # 1. Check confidence deterioration
        confidence_trigger, confidence_urgency = self._check_confidence_deterioration(
            confidence_data, current_symbols
        )
        if confidence_trigger:
            triggers.append(ContractionTrigger.CONFIDENCE_DROP)
            urgency = max(urgency, confidence_urgency, key=lambda x: x.value)
        
        # 2. Check safety violations
        safety_trigger, safety_urgency = self._check_safety_violations(portfolio_state)
        if safety_trigger:
            triggers.append(ContractionTrigger.SAFETY_VIOLATION)
            urgency = max(urgency, safety_urgency, key=lambda x: x.value)
        
        # 3. Check drawdown limits
        drawdown_trigger, drawdown_urgency = self._check_drawdown_limits(portfolio_state)
        if drawdown_trigger:
            triggers.append(ContractionTrigger.DRAWDOWN_LIMIT)
            urgency = max(urgency, drawdown_urgency, key=lambda x: x.value)
        
        # 4. Check margin situation
        margin_trigger, margin_urgency = self._check_margin_shortage(portfolio_state)
        if margin_trigger:
            triggers.append(ContractionTrigger.MARGIN_SHORTAGE)
            urgency = max(urgency, margin_urgency, key=lambda x: x.value)
        
        # 5. Check market stress
        market_trigger, market_urgency = self._check_market_stress(market_conditions)
        if market_trigger:
            triggers.append(ContractionTrigger.MARKET_STRESS)
            urgency = max(urgency, market_urgency, key=lambda x: x.value)
        
        contraction_needed = len(triggers) > 0
        
        if contraction_needed:
            logger.warning(f"Contraction triggered: {urgency.value} urgency, reasons: {[t.value for t in triggers]}")
        
        return contraction_needed, urgency, triggers
    
    def execute_contraction(
        self,
        urgency: ContractionUrgency,
        triggers: List[ContractionTrigger],
        portfolio_state: Dict,
        confidence_data: Dict,
        current_symbols: List[str]
    ) -> Tuple[List[str], Dict]:
        """
        Execute symbol contraction based on urgency level.
        
        Args:
            urgency: Contraction urgency level
            triggers: Triggers that caused contraction
            portfolio_state: Current portfolio state
            confidence_data: Confidence data
            current_symbols: Current symbols
            
        Returns:
            Tuple of (new_symbol_list, contraction_details)
        """
        contraction_details = {
            'urgency': urgency.value,
            'triggers': [t.value for t in triggers],
            'original_symbols': current_symbols.copy(),
            'removed_symbols': [],
            'retained_symbols': [],
            'target_count': 0,
            'execution_time': time.time()
        }
        
        # Determine target symbol count based on urgency
        if urgency == ContractionUrgency.CRITICAL:
            target_count = len(self.config.core_symbols)
        elif urgency == ContractionUrgency.HIGH:
            target_count = max(len(self.config.core_symbols), 2)
        elif urgency == ContractionUrgency.MEDIUM:
            target_count = max(3, len(current_symbols) - 2)  # Reduce by 2
        else:  # LOW
            target_count = max(3, len(current_symbols) - 1)  # Reduce by 1
        
        contraction_details['target_count'] = target_count
        
        # If already at or below target, no action needed
        if len(current_symbols) <= target_count:
            contraction_details['retained_symbols'] = current_symbols
            return current_symbols, contraction_details
        
        # Prioritize symbols for retention
        prioritized_symbols = self.prioritizer.prioritize_symbols_for_retention(
            portfolio_state, confidence_data, current_symbols
        )
        
        # Select symbols to retain
        retained_symbols = prioritized_symbols[:target_count]
        removed_symbols = [s for s in current_symbols if s not in retained_symbols]
        
        contraction_details['retained_symbols'] = retained_symbols
        contraction_details['removed_symbols'] = removed_symbols
        
        # Record contraction
        self._record_contraction(urgency, triggers)
        
        logger.warning(f"Executed {urgency.value} contraction: {len(current_symbols)} -> {len(retained_symbols)} symbols")
        logger.info(f"Removed symbols: {removed_symbols}")
        logger.info(f"Retained symbols: {retained_symbols}")
        
        return retained_symbols, contraction_details
    
    def _check_confidence_deterioration(
        self,
        confidence_data: Dict,
        current_symbols: List[str]
    ) -> Tuple[bool, ContractionUrgency]:
        """Check for confidence deterioration"""
        
        if not confidence_data:
            return False, ContractionUrgency.LOW
        
        low_confidence_count = 0
        critical_confidence_count = 0
        
        for symbol in current_symbols:
            symbol_conf = confidence_data.get(symbol, {})
            avg_confidence = symbol_conf.get('average_confidence', 1.0)
            
            if avg_confidence < self.config.confidence_emergency_threshold:
                critical_confidence_count += 1
            elif avg_confidence < self.config.confidence_contraction_threshold:
                low_confidence_count += 1
        
        # Determine urgency
        if critical_confidence_count >= 2:
            return True, ContractionUrgency.HIGH
        elif critical_confidence_count >= 1 or low_confidence_count >= 3:
            return True, ContractionUrgency.MEDIUM
        elif low_confidence_count >= 2:
            return True, ContractionUrgency.LOW
        
        return False, ContractionUrgency.LOW
    
    def _check_safety_violations(self, portfolio_state: Dict) -> Tuple[bool, ContractionUrgency]:
        """Check for safety limit violations"""
        
        violation_count = portfolio_state.get('violation_count', 0)
        consecutive_losses = portfolio_state.get('consecutive_losses', 0)
        circuit_breaker = portfolio_state.get('circuit_breaker_active', False)
        
        if circuit_breaker:
            return True, ContractionUrgency.CRITICAL
        elif violation_count >= 3:
            return True, ContractionUrgency.HIGH
        elif consecutive_losses > self.config.max_consecutive_losses:
            return True, ContractionUrgency.MEDIUM
        elif violation_count >= 2:
            return True, ContractionUrgency.LOW
        
        return False, ContractionUrgency.LOW
    
    def _check_drawdown_limits(self, portfolio_state: Dict) -> Tuple[bool, ContractionUrgency]:
        """Check drawdown limits"""
        
        daily_drawdown = abs(portfolio_state.get('daily_drawdown_pct', 0))
        max_drawdown = abs(portfolio_state.get('max_drawdown', 0))
        
        if daily_drawdown >= self.config.max_acceptable_drawdown * 1.5:  # 150% of limit
            return True, ContractionUrgency.CRITICAL
        elif daily_drawdown >= self.config.max_acceptable_drawdown:
            return True, ContractionUrgency.HIGH
        elif max_drawdown >= self.config.max_acceptable_drawdown * 2:
            return True, ContractionUrgency.MEDIUM
        
        return False, ContractionUrgency.LOW
    
    def _check_margin_shortage(self, portfolio_state: Dict) -> Tuple[bool, ContractionUrgency]:
        """Check margin shortage"""
        
        total_balance = portfolio_state.get('total_balance', 0)
        used_margin = portfolio_state.get('used_margin', 0)
        
        if total_balance <= 0:
            return False, ContractionUrgency.LOW
        
        free_margin_pct = (total_balance - used_margin) / total_balance
        
        if free_margin_pct < self.config.min_required_margin * 0.5:  # 50% of minimum
            return True, ContractionUrgency.CRITICAL
        elif free_margin_pct < self.config.min_required_margin:
            return True, ContractionUrgency.HIGH
        elif free_margin_pct < self.config.min_required_margin * 1.5:
            return True, ContractionUrgency.LOW
        
        return False, ContractionUrgency.LOW
    
    def _check_market_stress(
        self,
        market_conditions: Optional[Dict]
    ) -> Tuple[bool, ContractionUrgency]:
        """Check market stress conditions"""
        
        if not market_conditions:
            return False, ContractionUrgency.LOW
        
        volatility = market_conditions.get('market_volatility', 0)
        health_score = market_conditions.get('market_health_score', 1.0)
        
        if health_score < self.config.min_market_health * 0.5:
            return True, ContractionUrgency.HIGH
        elif volatility > self.config.max_volatility_for_boost:
            return True, ContractionUrgency.MEDIUM
        elif health_score < self.config.min_market_health:
            return True, ContractionUrgency.LOW
        
        return False, ContractionUrgency.LOW
    
    def _in_contraction_cooldown(self) -> bool:
        """Check if in cooldown period"""
        
        if not self.last_contraction_time:
            return False
        
        cooldown_elapsed = (time.time() - self.last_contraction_time) / 60
        return cooldown_elapsed < self.config.contraction_cooldown_minutes
    
    def _record_contraction(self, urgency: ContractionUrgency, triggers: List[ContractionTrigger]):
        """Record contraction occurrence"""
        
        self.last_contraction_time = time.time()
        self.contraction_triggers.append({
            'timestamp': self.last_contraction_time,
            'urgency': urgency,
            'triggers': triggers
        })
        
        logger.info(f"Contraction recorded: {urgency.value} urgency")
    
    def get_contraction_status(self) -> Dict:
        """Get current contraction manager status"""
        
        return {
            'emergency_mode': self.emergency_mode,
            'contraction_in_progress': self.contraction_in_progress,
            'last_contraction_time': self.last_contraction_time,
            'minutes_since_last_contraction': (
                (time.time() - self.last_contraction_time) / 60
                if self.last_contraction_time else float('inf')
            ),
            'recent_triggers': list(self.contraction_triggers),
            'config': {
                'confidence_threshold': self.config.confidence_contraction_threshold,
                'emergency_threshold': self.config.confidence_emergency_threshold,
                'max_drawdown': self.config.max_acceptable_drawdown,
                'min_margin': self.config.min_required_margin
            }
        }


if __name__ == "__main__":
    # Test auto-contraction mechanism
    logging.basicConfig(level=logging.INFO)
    
    print("🧪 Testing Auto-Contraction Mechanism...")
    
    # Initialize manager
    config = ContractionConfig(
        confidence_contraction_threshold=0.70,
        confidence_emergency_threshold=0.50,
        max_acceptable_drawdown=0.05
    )
    
    manager = AutoContractionManager(config)
    
    print(f"📊 Contraction Config:")
    print(f"  Confidence threshold: {config.confidence_contraction_threshold}")
    print(f"  Emergency threshold: {config.confidence_emergency_threshold}")
    print(f"  Max drawdown: {config.max_acceptable_drawdown:.1%}")
    
    # Test scenario with deteriorating conditions
    portfolio_state = {
        'total_balance': 10000,
        'used_margin': 8500,  # 85% used, only 15% free
        'daily_drawdown_pct': 0.06,  # 6% drawdown (exceeds 5% limit)
        'consecutive_losses': 5,
        'violation_count': 2,
        'circuit_breaker_active': False,
        'positions': {
            'BTCUSDT': {'unrealized_pnl_long': 200, 'margin_used': 3000},
            'ETHUSDT': {'unrealized_pnl_short': -100, 'margin_used': 2500},
            'SOLUSDT': {'unrealized_pnl_long': -300, 'margin_used': 2000},
            'ADAUSDT': {'unrealized_pnl_short': 50, 'margin_used': 1000}
        }
    }
    
    confidence_data = {
        'BTCUSDT': {'average_confidence': 0.85, 'confidence_volatility': 0.1},
        'ETHUSDT': {'average_confidence': 0.75, 'confidence_volatility': 0.2},
        'SOLUSDT': {'average_confidence': 0.45, 'confidence_volatility': 0.4},  # Low confidence
        'ADAUSDT': {'average_confidence': 0.60, 'confidence_volatility': 0.3}
    }
    
    current_symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'ADAUSDT']
    
    print(f"\n🔍 Evaluating Contraction Need...")
    print(f"  Current symbols: {len(current_symbols)} - {current_symbols}")
    
    contraction_needed, urgency, triggers = manager.evaluate_contraction_need(
        portfolio_state, confidence_data, current_symbols
    )
    
    print(f"  Contraction needed: {contraction_needed}")
    print(f"  Urgency level: {urgency.value if contraction_needed else 'N/A'}")
    print(f"  Triggers: {[t.value for t in triggers]}")
    
    if contraction_needed:
        print(f"\n⚠️  Executing Contraction...")
        
        new_symbols, details = manager.execute_contraction(
            urgency, triggers, portfolio_state, confidence_data, current_symbols
        )
        
        print(f"  Target symbol count: {details['target_count']}")
        print(f"  New symbol list: {len(new_symbols)} - {new_symbols}")
        print(f"  Removed symbols: {details['removed_symbols']}")
        
        # Show status
        status = manager.get_contraction_status()
        print(f"\n📊 Contraction Status:")
        print(f"  Minutes since last: {status['minutes_since_last_contraction']:.1f}")
        print(f"  Recent triggers: {len(status['recent_triggers'])}")
    
    print(f"\n✅ Auto-contraction mechanism ready!")
    print(f"  Core symbols: {config.core_symbols}")
    print(f"  Cooldown period: {config.contraction_cooldown_minutes} minutes")