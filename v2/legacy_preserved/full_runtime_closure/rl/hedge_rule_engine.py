"""
Per-Symbol Hedge Rule Engine
Independent validation for long/short signals to enable simultaneous positions
"""

import logging
from typing import Dict, List, Optional, Tuple, NamedTuple
from dataclasses import dataclass
from enum import Enum
import time
import math
import numpy as np

logger = logging.getLogger(__name__)


class SignalDirection(Enum):
    """Signal direction for hedge validation"""
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class SignalStrength(Enum):
    """Signal strength levels"""
    WEAK = 0.3
    MODERATE = 0.6
    STRONG = 0.8


@dataclass
class SignalContext:
    """Context for a single trading signal"""
    symbol: str
    direction: SignalDirection
    strength: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    timeframe: str
    source: str  # "PPO", "MASA", "TA", etc.
    timestamp: float
    regime: str  # "trend", "range", "breakout", etc.
    momentum_score: float  # -1.0 to 1.0
    exhaustion_score: float  # 0.0 to 1.0


@dataclass
class HedgeValidationResult:
    """Result of hedge rule validation"""
    allowed: bool
    side: SignalDirection
    confidence: float
    strength: float
    reason: str
    risk_factors: List[str]
    supporting_signals: List[SignalContext]
    conflicting_signals: List[SignalContext]


class SymbolHedgeRuleEngine:
    """
    Rule engine for per-symbol hedge position validation.
    
    Key Rules:
    1. Independent signal validation per side
    2. Minimum confidence thresholds per timeframe
    3. Regime compatibility checks
    4. Multi-source agreement requirements
    5. Risk factor assessment
    """
    
    def __init__(
        self,
        min_confidence_threshold: float = 0.80,
        min_strength_threshold: float = 0.6,
        regime_compatibility: Dict[str, List[str]] = None,
        timeframe_weights: Dict[str, float] = None,
        source_weights: Dict[str, float] = None,
        max_conflicting_ratio: float = 0.3
    ):
        """
        Initialize hedge rule engine.
        
        Args:
            min_confidence_threshold: Minimum confidence for hedge validation
            min_strength_threshold: Minimum signal strength
            regime_compatibility: Compatible regimes for hedge positions
            timeframe_weights: Weights for different timeframes
            source_weights: Weights for different signal sources
            max_conflicting_ratio: Max ratio of conflicting signals allowed
        """
        self.min_confidence_threshold = min_confidence_threshold
        self.min_strength_threshold = min_strength_threshold
        
        # Default regime compatibility
        self.regime_compatibility = regime_compatibility or {
            "trend": ["LONG", "SHORT"],  # Trend regime allows both sides
            "range": ["LONG", "SHORT"],  # Range regime allows both sides
            "breakout": ["LONG", "SHORT"],  # Breakout can go either way
            "reversal": ["LONG", "SHORT"],  # Reversal allows both sides
            "exhaustion": ["SHORT"]  # Exhaustion typically favors short
        }
        
        # Timeframe weights (higher weight = more important)
        self.timeframe_weights = timeframe_weights or {
            "1m": 0.2,
            "5m": 0.3,
            "15m": 0.5,
            "1h": 0.8,
            "4h": 1.0,
            "1d": 0.9
        }
        
        # Source weights
        self.source_weights = source_weights or {
            "PPO": 1.0,
            "MASA": 1.0,
            "TA": 0.8,
            "TokenMetrics": 0.6,
            "Coinank": 0.7,
            "Binance": 0.5
        }
        
        self.max_conflicting_ratio = max_conflicting_ratio
        
        logger.info(f"SymbolHedgeRuleEngine initialized with confidence threshold {min_confidence_threshold}")
    
    def validate_hedge_signal(
        self,
        symbol: str,
        target_side: SignalDirection,
        signals: List[SignalContext],
        existing_positions: Dict[str, float] = None
    ) -> HedgeValidationResult:
        """
        Validate if a hedge signal is allowed for the given side.
        
        Args:
            symbol: Trading symbol
            target_side: Desired position side (LONG/SHORT)
            signals: List of available signals for the symbol
            existing_positions: Current positions {side: quantity}
            
        Returns:
            HedgeValidationResult with validation outcome
        """
        if existing_positions is None:
            existing_positions = {}
        
        # Filter signals for this symbol and side
        relevant_signals = [
            sig for sig in signals 
            if sig.symbol == symbol and sig.direction == target_side
        ]
        
        conflicting_signals = [
            sig for sig in signals 
            if sig.symbol == symbol and sig.direction != target_side and sig.direction != SignalDirection.NEUTRAL
        ]
        
        if not relevant_signals:
            return HedgeValidationResult(
                allowed=False,
                side=target_side,
                confidence=0.0,
                strength=0.0,
                reason="No relevant signals found",
                risk_factors=["no_signals"],
                supporting_signals=[],
                conflicting_signals=conflicting_signals
            )
        
        # 1. Calculate aggregate confidence and strength
        aggregate_confidence, aggregate_strength = self._calculate_aggregate_scores(relevant_signals)
        
        # 2. Check minimum thresholds
        if aggregate_confidence < self.min_confidence_threshold:
            return HedgeValidationResult(
                allowed=False,
                side=target_side,
                confidence=aggregate_confidence,
                strength=aggregate_strength,
                reason=f"Confidence below threshold: {aggregate_confidence:.2f} < {self.min_confidence_threshold}",
                risk_factors=["low_confidence"],
                supporting_signals=relevant_signals,
                conflicting_signals=conflicting_signals
            )
        
        if aggregate_strength < self.min_strength_threshold:
            return HedgeValidationResult(
                allowed=False,
                side=target_side,
                confidence=aggregate_confidence,
                strength=aggregate_strength,
                reason=f"Strength below threshold: {aggregate_strength:.2f} < {self.min_strength_threshold}",
                risk_factors=["weak_signal"],
                supporting_signals=relevant_signals,
                conflicting_signals=conflicting_signals
            )
        
        # 3. Check regime compatibility
        risk_factors = []
        regime_compatible = self._check_regime_compatibility(relevant_signals, target_side)
        if not regime_compatible:
            risk_factors.append("regime_incompatible")
        
        # 4. Check conflicting signals ratio
        total_signals = len(relevant_signals) + len(conflicting_signals)
        if total_signals > 0:
            conflicting_ratio = len(conflicting_signals) / total_signals
            if conflicting_ratio > self.max_conflicting_ratio:
                risk_factors.append("high_conflicting_ratio")
        
        # 5. Check timeframe coverage
        timeframe_coverage = self._check_timeframe_coverage(relevant_signals)
        if timeframe_coverage < 0.5:  # Need at least 50% timeframe coverage
            risk_factors.append("insufficient_timeframe_coverage")
        
        # 6. Check multi-source agreement
        source_agreement = self._check_source_agreement(relevant_signals)
        if source_agreement < 0.6:  # Need at least 60% source agreement
            risk_factors.append("low_source_agreement")
        
        # Final decision
        allowed = len(risk_factors) == 0 or (
            len(risk_factors) <= 2 and 
            aggregate_confidence > 0.9 and 
            aggregate_strength > 0.8
        )
        
        reason = "Validation passed" if allowed else f"Risk factors: {', '.join(risk_factors)}"
        
        return HedgeValidationResult(
            allowed=allowed,
            side=target_side,
            confidence=aggregate_confidence,
            strength=aggregate_strength,
            reason=reason,
            risk_factors=risk_factors,
            supporting_signals=relevant_signals,
            conflicting_signals=conflicting_signals
        )
    
    def validate_both_sides(
        self,
        symbol: str,
        signals: List[SignalContext],
        existing_positions: Dict[str, float] = None
    ) -> Dict[str, HedgeValidationResult]:
        """
        Validate both long and short sides independently.
        
        Args:
            symbol: Trading symbol
            signals: All available signals
            existing_positions: Current positions
            
        Returns:
            Dictionary with validation results for both sides
        """
        long_result = self.validate_hedge_signal(
            symbol, SignalDirection.LONG, signals, existing_positions
        )
        
        short_result = self.validate_hedge_signal(
            symbol, SignalDirection.SHORT, signals, existing_positions
        )
        
        return {
            "long": long_result,
            "short": short_result
        }
    
    def get_hedge_recommendation(
        self,
        symbol: str,
        signals: List[SignalContext],
        existing_positions: Dict[str, float] = None,
        portfolio_exposure: float = 0.0,
        max_symbol_exposure: float = 0.30
    ) -> Dict[str, any]:
        """
        Get comprehensive hedge recommendation for symbol.
        
        Args:
            symbol: Trading symbol
            signals: Available signals
            existing_positions: Current positions
            portfolio_exposure: Current portfolio exposure
            max_symbol_exposure: Maximum allowed symbol exposure
            
        Returns:
            Comprehensive recommendation dictionary
        """
        both_sides = self.validate_both_sides(symbol, signals, existing_positions)
        
        # Calculate recommended position sizes
        recommendations = {
            "symbol": symbol,
            "timestamp": time.time(),
            "long_allowed": both_sides["long"].allowed,
            "short_allowed": both_sides["short"].allowed,
            "hedge_mode": both_sides["long"].allowed and both_sides["short"].allowed,
            "recommendations": {}
        }
        
        # Long side recommendation
        if both_sides["long"].allowed:
            size_pct = self._calculate_position_size(
                both_sides["long"], portfolio_exposure, max_symbol_exposure
            )
            recommendations["recommendations"]["long"] = {
                "action": "OPEN_LONG",
                "confidence": both_sides["long"].confidence,
                "strength": both_sides["long"].strength,
                "size_pct": size_pct,
                "reason": both_sides["long"].reason,
                "supporting_signals": len(both_sides["long"].supporting_signals)
            }
        
        # Short side recommendation
        if both_sides["short"].allowed:
            size_pct = self._calculate_position_size(
                both_sides["short"], portfolio_exposure, max_symbol_exposure
            )
            recommendations["recommendations"]["short"] = {
                "action": "OPEN_SHORT",
                "confidence": both_sides["short"].confidence,
                "strength": both_sides["short"].strength,
                "size_pct": size_pct,
                "reason": both_sides["short"].reason,
                "supporting_signals": len(both_sides["short"].supporting_signals)
            }
        
        # Risk assessment
        all_risk_factors = set(both_sides["long"].risk_factors + both_sides["short"].risk_factors)
        recommendations["risk_assessment"] = {
            "total_risk_factors": len(all_risk_factors),
            "risk_factors": list(all_risk_factors),
            "risk_level": "low" if len(all_risk_factors) <= 1 else "medium" if len(all_risk_factors) <= 3 else "high"
        }
        
        return recommendations
    
    def _calculate_aggregate_scores(
        self, 
        signals: List[SignalContext]
    ) -> Tuple[float, float]:
        """Calculate weighted aggregate confidence and strength"""
        if not signals:
            return 0.0, 0.0
        
        total_confidence_weight = 0.0
        total_strength_weight = 0.0
        total_weight = 0.0

        def _clean(value: float) -> float:
            """Clamp and de-NaN a score into [0,1]"""
            if value is None or (isinstance(value, float) and math.isnan(value)):
                return 0.0
            if isinstance(value, np.ndarray):
                value = float(value.squeeze())
            return max(0.0, min(1.0, float(value)))
        
        for signal in signals:
            # Calculate weight based on timeframe and source
            tf_weight = self.timeframe_weights.get(signal.timeframe, 0.5)
            source_weight = self.source_weights.get(signal.source, 0.5)
            weight = tf_weight * source_weight
            
            conf = _clean(signal.confidence)
            strength = _clean(signal.strength)
            total_confidence_weight += conf * weight
            total_strength_weight += strength * weight
            total_weight += weight
        
        if total_weight == 0:
            return 0.0, 0.0
        
        aggregate_confidence = total_confidence_weight / total_weight
        aggregate_strength = total_strength_weight / total_weight
        if math.isnan(aggregate_confidence) or math.isnan(aggregate_strength):
            logger.debug("⚠️ [MASA] NaN encountered in aggregate scores, defaulting to 0")
            aggregate_confidence = 0.0
            aggregate_strength = 0.0
        logger.debug(
            f"[MASA] aggregate_conf={aggregate_confidence:.3f} aggregate_strength={aggregate_strength:.3f} "
            f"signals={len(signals)} weight={total_weight:.3f}"
        )
        
        return aggregate_confidence, aggregate_strength
    
    def _check_regime_compatibility(
        self, 
        signals: List[SignalContext], 
        target_side: SignalDirection
    ) -> bool:
        """Check if signals are compatible with target side given regimes"""
        if not signals:
            return False
        
        compatible_count = 0
        for signal in signals:
            regime_sides = self.regime_compatibility.get(signal.regime, [])
            if target_side.value in regime_sides:
                compatible_count += 1
        
        # Need at least 70% regime compatibility
        return (compatible_count / len(signals)) >= 0.7
    
    def _check_timeframe_coverage(self, signals: List[SignalContext]) -> float:
        """Check coverage across different timeframes"""
        if not signals:
            return 0.0
        
        covered_timeframes = set(signal.timeframe for signal in signals)
        total_timeframes = len(self.timeframe_weights)
        
        return len(covered_timeframes) / total_timeframes
    
    def _check_source_agreement(self, signals: List[SignalContext]) -> float:
        """Check agreement across different sources"""
        if not signals:
            return 0.0
        
        # Group by source and check consistency
        source_groups = {}
        for signal in signals:
            if signal.source not in source_groups:
                source_groups[signal.source] = []
            source_groups[signal.source].append(signal)
        
        # Check if sources agree on direction and strength
        agreeing_sources = 0
        for source, source_signals in source_groups.items():
            # Check if source signals are consistent
            avg_strength = sum(s.strength for s in source_signals) / len(source_signals)
            if avg_strength >= self.min_strength_threshold:
                agreeing_sources += 1
        
        return agreeing_sources / len(source_groups) if source_groups else 0.0
    
    def _calculate_position_size(
        self,
        validation_result: HedgeValidationResult,
        current_exposure: float,
        max_symbol_exposure: float
    ) -> float:
        """Calculate recommended position size based on validation result"""
        if not validation_result.allowed:
            return 0.0
        
        # Base size from signal strength and confidence
        base_size = (validation_result.strength + validation_result.confidence) / 2.0
        
        # Scale by available exposure capacity
        available_capacity = max_symbol_exposure - current_exposure
        capacity_factor = max(0.0, min(1.0, available_capacity / max_symbol_exposure))
        
        # Apply risk adjustment
        risk_adjustment = 1.0 - (len(validation_result.risk_factors) * 0.15)
        risk_adjustment = max(0.3, risk_adjustment)  # Don't go below 30%
        
        # Final size calculation
        final_size = base_size * capacity_factor * risk_adjustment * 0.08  # Max 8% base
        
        return min(final_size, 0.10)  # Cap at 10%


if __name__ == "__main__":
    # Test the hedge rule engine
    logging.basicConfig(level=logging.INFO)
    
    engine = SymbolHedgeRuleEngine()
    
    # Create test signals
    test_signals = [
        SignalContext(
            symbol="BTCUSDT",
            direction=SignalDirection.LONG,
            strength=0.85,
            confidence=0.82,
            timeframe="15m",
            source="PPO",
            timestamp=time.time(),
            regime="trend",
            momentum_score=0.7,
            exhaustion_score=0.2
        ),
        SignalContext(
            symbol="BTCUSDT",
            direction=SignalDirection.LONG,
            strength=0.78,
            confidence=0.86,
            timeframe="1h",
            source="MASA",
            timestamp=time.time(),
            regime="trend",
            momentum_score=0.6,
            exhaustion_score=0.1
        ),
        SignalContext(
            symbol="BTCUSDT",
            direction=SignalDirection.SHORT,
            strength=0.72,
            confidence=0.75,
            timeframe="5m",
            source="TA",
            timestamp=time.time(),
            regime="reversal",
            momentum_score=-0.3,
            exhaustion_score=0.6
        )
    ]
    
    print("🧪 Testing Hedge Rule Engine...")
    
    # Test both sides validation
    both_sides = engine.validate_both_sides("BTCUSDT", test_signals)
    
    print(f"\n🟢 Long Side Validation:")
    long_result = both_sides["long"]
    print(f"  Allowed: {long_result.allowed}")
    print(f"  Confidence: {long_result.confidence:.2f}")
    print(f"  Strength: {long_result.strength:.2f}")
    print(f"  Reason: {long_result.reason}")
    print(f"  Risk factors: {long_result.risk_factors}")
    
    print(f"\n🔴 Short Side Validation:")
    short_result = both_sides["short"]
    print(f"  Allowed: {short_result.allowed}")
    print(f"  Confidence: {short_result.confidence:.2f}")
    print(f"  Strength: {short_result.strength:.2f}")
    print(f"  Reason: {short_result.reason}")
    print(f"  Risk factors: {short_result.risk_factors}")
    
    # Test full recommendation
    recommendation = engine.get_hedge_recommendation("BTCUSDT", test_signals)
    
    print(f"\n📊 Full Hedge Recommendation:")
    print(f"  Hedge mode enabled: {recommendation['hedge_mode']}")
    print(f"  Risk level: {recommendation['risk_assessment']['risk_level']}")
    
    for side, rec in recommendation["recommendations"].items():
        print(f"  {side.upper()}: {rec['action']} size={rec['size_pct']*100:.1f}% conf={rec['confidence']:.2f}")