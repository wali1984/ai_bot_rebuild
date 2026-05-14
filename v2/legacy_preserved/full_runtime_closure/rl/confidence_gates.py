"""
Confidence Gates for Symbol Expansion
Implements intelligent symbol expansion from 3->5 symbols based on confidence and agreement thresholds
"""

import torch
import numpy as np
import logging
from typing import Dict, List, Optional, Tuple, Union, Set
from dataclasses import dataclass
from enum import Enum
import time
import redis
import json
from collections import defaultdict, deque

logger = logging.getLogger(__name__)


class ModelType(Enum):
    """Model types for consensus checking"""
    PPO = "ppo"
    MASA = "masa"


class MarketRegime(Enum):
    """Market regime classifications"""
    TREND = "trend"
    RANGE = "range"  
    VOLATILITY = "volatility"
    UNKNOWN = "unknown"


@dataclass
class ConfidenceGateConfig:
    """Configuration for confidence-based symbol expansion"""
    
    # Confidence thresholds
    min_confidence_for_boost: float = 0.85  # Minimum confidence to allow boost
    min_timeframes_required: int = 3  # Number of timeframes that must agree
    consensus_agreement_threshold: float = 0.80  # PPO/MASA agreement threshold
    
    # Symbol limits
    base_symbols: int = 3
    boost_symbols: int = 5
    
    # Timeframe requirements
    required_timeframes: List[str] = None  # Will default to ["1m", "5m", "15m"]
    timeframe_confidence_window: int = 10  # Number of recent predictions to consider
    
    # Regime agreement
    require_regime_agreement: bool = True
    regime_agreement_threshold: float = 0.70  # Fraction of timeframes in same regime
    
    # Safety checks
    enable_safety_checks: bool = True
    
    def __post_init__(self):
        if self.required_timeframes is None:
            self.required_timeframes = ["1m", "5m", "15m"]


class SymbolConfidenceTracker:
    """
    Tracks confidence scores and model agreement for each symbol across timeframes.
    
    Maintains rolling windows of:
    - Model confidence scores per (symbol, timeframe)
    - PPO vs MASA agreement rates
    - Market regime classifications
    """
    
    def __init__(
        self,
        config: ConfidenceGateConfig,
        redis_client: Optional[redis.Redis] = None
    ):
        """
        Initialize symbol confidence tracker.
        
        Args:
            config: Confidence gate configuration
            redis_client: Optional Redis client for persistence
        """
        self.config = config
        self.redis_client = redis_client
        
        # Rolling confidence data: symbol -> timeframe -> deque of (timestamp, confidence, ppo_logit, masa_logit, regime)
        self.confidence_history = defaultdict(lambda: defaultdict(
            lambda: deque(maxlen=config.timeframe_confidence_window)
        ))
        
        # Current boost status
        self.boost_enabled = False
        self.boost_enabled_since = None
        
        logger.info(f"SymbolConfidenceTracker initialized with {config.base_symbols}->{config.boost_symbols} expansion")
    
    def add_prediction(
        self,
        symbol: str,
        timeframe: str,
        confidence: float,
        ppo_logit: float,
        masa_logit: float,
        regime: MarketRegime,
        timestamp: Optional[float] = None
    ):
        """
        Add a new prediction sample for confidence tracking.
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe of prediction
            confidence: Model confidence score (0-1)
            ppo_logit: PPO model logit
            masa_logit: MASA model logit  
            regime: Market regime classification
            timestamp: Prediction timestamp
        """
        if timestamp is None:
            timestamp = time.time()
        
        # Validate inputs
        confidence = np.clip(confidence, 0.0, 1.0)
        
        # Add to rolling history
        prediction_data = (timestamp, confidence, ppo_logit, masa_logit, regime)
        self.confidence_history[symbol][timeframe].append(prediction_data)
        
        # Cache in Redis if available
        if self.redis_client:
            self._cache_prediction(symbol, timeframe, prediction_data)
    
    def check_boost_eligibility(self, target_symbols: List[str]) -> Tuple[bool, Dict]:
        """
        Check if boost mode should be enabled based on confidence gates.
        
        Args:
            target_symbols: Symbols to check for boost eligibility
            
        Returns:
            Tuple of (boost_allowed, details_dict)
        """
        details = {
            'symbols_checked': len(target_symbols),
            'confidence_passed': [],
            'agreement_passed': [],
            'regime_passed': [],
            'overall_eligible': False,
            'reasons': []
        }
        
        eligible_symbols = []
        
        for symbol in target_symbols:
            symbol_eligible, symbol_details = self._check_symbol_eligibility(symbol)
            
            if symbol_eligible:
                eligible_symbols.append(symbol)
                details['confidence_passed'].append(symbol)
                details['agreement_passed'].append(symbol)
                details['regime_passed'].append(symbol)
            else:
                # Track which checks failed
                if not symbol_details.get('confidence_ok'):
                    details['reasons'].append(f"{symbol}: insufficient confidence")
                if not symbol_details.get('agreement_ok'):
                    details['reasons'].append(f"{symbol}: poor PPO/MASA agreement")
                if not symbol_details.get('regime_ok'):
                    details['reasons'].append(f"{symbol}: regime disagreement")
        
        # Determine if boost should be enabled
        min_eligible = min(self.config.base_symbols, len(target_symbols))
        boost_allowed = len(eligible_symbols) >= min_eligible
        
        details['eligible_symbols'] = eligible_symbols
        details['overall_eligible'] = boost_allowed
        
        if not boost_allowed:
            details['reasons'].append(
                f"Only {len(eligible_symbols)}/{min_eligible} symbols meet boost criteria"
            )
        
        logger.info(f"Boost eligibility check: {boost_allowed} ({len(eligible_symbols)}/{len(target_symbols)} eligible)")
        
        return boost_allowed, details
    
    def _check_symbol_eligibility(self, symbol: str) -> Tuple[bool, Dict]:
        """Check if a single symbol meets boost eligibility criteria"""
        
        symbol_details = {
            'confidence_ok': False,
            'agreement_ok': False,
            'regime_ok': False,
            'timeframes_data': {}
        }
        
        if symbol not in self.confidence_history:
            return False, symbol_details
        
        # Check each required timeframe
        timeframes_passed = 0
        regime_votes = []
        
        for timeframe in self.config.required_timeframes:
            tf_data = self.confidence_history[symbol].get(timeframe, deque())
            
            if len(tf_data) == 0:
                continue
            
            # Get recent data
            recent_data = list(tf_data)[-self.config.timeframe_confidence_window:]
            
            if not recent_data:
                continue
            
            # Check confidence threshold
            confidences = [data[1] for data in recent_data]
            avg_confidence = np.mean(confidences)
            confidence_ok = avg_confidence >= self.config.min_confidence_for_boost
            
            # Check PPO/MASA agreement
            agreements = []
            regimes = []
            
            for _, conf, ppo_logit, masa_logit, regime in recent_data:
                # Calculate agreement (higher is better agreement)
                if not (np.isnan(ppo_logit) or np.isnan(masa_logit)):
                    # Simple agreement: both predict same direction
                    ppo_dir = 1 if ppo_logit > 0 else -1
                    masa_dir = 1 if masa_logit > 0 else -1
                    agreement = 1.0 if ppo_dir == masa_dir else 0.0
                    agreements.append(agreement)
                
                regimes.append(regime)
            
            agreement_rate = np.mean(agreements) if agreements else 0.0
            agreement_ok = agreement_rate >= self.config.consensus_agreement_threshold
            
            # Collect regime data
            regime_votes.extend(regimes)
            
            # Track timeframe details
            symbol_details['timeframes_data'][timeframe] = {
                'confidence': avg_confidence,
                'confidence_ok': confidence_ok,
                'agreement_rate': agreement_rate,
                'agreement_ok': agreement_ok,
                'samples': len(recent_data)
            }
            
            # Count passing timeframes
            if confidence_ok and agreement_ok:
                timeframes_passed += 1
        
        # Check if minimum timeframes passed
        symbol_details['confidence_ok'] = timeframes_passed >= self.config.min_timeframes_required
        symbol_details['agreement_ok'] = symbol_details['confidence_ok']  # Already checked above
        
        # Check regime agreement
        if self.config.require_regime_agreement and regime_votes:
            regime_counts = defaultdict(int)
            for regime in regime_votes:
                regime_counts[regime] += 1
            
            if regime_counts:
                dominant_regime_count = max(regime_counts.values())
                regime_agreement_rate = dominant_regime_count / len(regime_votes)
                symbol_details['regime_ok'] = regime_agreement_rate >= self.config.regime_agreement_threshold
            else:
                symbol_details['regime_ok'] = False
        else:
            symbol_details['regime_ok'] = True  # Skip regime check
        
        # Symbol is eligible if all checks pass
        symbol_eligible = (
            symbol_details['confidence_ok'] and
            symbol_details['agreement_ok'] and
            symbol_details['regime_ok']
        )
        
        return symbol_eligible, symbol_details
    
    def get_current_symbol_limit(self) -> int:
        """Get current symbol limit (base or boosted)"""
        return self.config.boost_symbols if self.boost_enabled else self.config.base_symbols
    
    def enable_boost_mode(self):
        """Enable boost mode"""
        if not self.boost_enabled:
            self.boost_enabled = True
            self.boost_enabled_since = time.time()
            logger.info("Boost mode ENABLED - symbol limit raised to 5")
    
    def disable_boost_mode(self):
        """Disable boost mode"""
        if self.boost_enabled:
            self.boost_enabled = False
            self.boost_enabled_since = None
            logger.info("Boost mode DISABLED - symbol limit reduced to 3")
    
    def get_boost_status(self) -> Dict:
        """Get current boost status and metrics"""
        
        return {
            'boost_enabled': self.boost_enabled,
            'boost_enabled_since': self.boost_enabled_since,
            'current_symbol_limit': self.get_current_symbol_limit(),
            'base_limit': self.config.base_symbols,
            'boost_limit': self.config.boost_symbols,
            'symbols_tracked': list(self.confidence_history.keys()),
            'timeframes_tracked': self.config.required_timeframes
        }
    
    def _cache_prediction(self, symbol: str, timeframe: str, prediction_data: Tuple):
        """Cache prediction in Redis"""
        
        try:
            cache_key = f"confidence_tracker:{symbol}:{timeframe}"
            
            # Convert data to JSON-serializable format
            timestamp, confidence, ppo_logit, masa_logit, regime = prediction_data
            
            cached_data = {
                'timestamp': timestamp,
                'confidence': confidence,
                'ppo_logit': ppo_logit,
                'masa_logit': masa_logit,
                'regime': regime.value if isinstance(regime, MarketRegime) else regime
            }
            
            # Store with expiration
            self.redis_client.setex(
                cache_key,
                3600,  # 1 hour expiry
                json.dumps(cached_data)
            )
            
        except Exception as e:
            logger.warning(f"Failed to cache prediction data: {e}")


class ConfidenceGateManager:
    """
    Main manager for confidence-based symbol expansion.
    
    Orchestrates:
    - Confidence tracking across symbols and timeframes
    - Boost eligibility determination
    - Automatic enable/disable of boost mode
    - Integration with portfolio limits
    """
    
    def __init__(
        self,
        config: ConfidenceGateConfig = None,
        redis_client: Optional[redis.Redis] = None
    ):
        """
        Initialize confidence gate manager.
        
        Args:
            config: Configuration for confidence gates
            redis_client: Optional Redis client
        """
        self.config = config or ConfidenceGateConfig()
        self.tracker = SymbolConfidenceTracker(self.config, redis_client)
        
        # Auto-management state
        self.auto_boost_enabled = True
        self.last_boost_check = 0
        self.boost_check_interval = 60  # Check every 60 seconds
        
        logger.info("ConfidenceGateManager initialized")
    
    def update_symbol_prediction(
        self,
        symbol: str,
        timeframe: str,
        confidence: float,
        ppo_logit: float,
        masa_logit: float,
        regime: Union[MarketRegime, str],
        timestamp: Optional[float] = None
    ):
        """Update prediction data for a symbol"""
        
        # Convert string regime to enum if needed
        if isinstance(regime, str):
            try:
                regime = MarketRegime(regime.lower())
            except ValueError:
                regime = MarketRegime.UNKNOWN
        
        self.tracker.add_prediction(
            symbol, timeframe, confidence, ppo_logit, masa_logit, regime, timestamp
        )
        
        # Check if boost status should be updated
        if self.auto_boost_enabled:
            self._maybe_update_boost_status()
    
    def check_symbol_expansion_allowed(
        self,
        current_symbols: List[str],
        target_symbols: List[str]
    ) -> Tuple[bool, List[str], Dict]:
        """
        Check if symbol expansion is allowed based on confidence gates.
        
        Args:
            current_symbols: Currently active symbols
            target_symbols: Desired symbols to trade
            
        Returns:
            Tuple of (expansion_allowed, approved_symbols, details)
        """
        current_limit = self.tracker.get_current_symbol_limit()
        
        # If we're not expanding beyond current limit, allow
        if len(target_symbols) <= current_limit:
            return True, target_symbols[:current_limit], {'reason': 'within_limit'}
        
        # Check if boost eligibility criteria are met
        boost_allowed, details = self.tracker.check_boost_eligibility(target_symbols)
        
        if boost_allowed:
            # Enable boost if not already enabled
            if not self.tracker.boost_enabled:
                self.tracker.enable_boost_mode()
            
            approved_symbols = target_symbols[:self.config.boost_symbols]
        else:
            # Stick to base limit
            approved_symbols = target_symbols[:self.config.base_symbols]
        
        details['approved_symbols'] = approved_symbols
        details['expansion_allowed'] = len(approved_symbols) > len(current_symbols)
        
        return details['expansion_allowed'], approved_symbols, details
    
    def force_boost_enable(self):
        """Manually enable boost mode (overrides auto-management)"""
        self.tracker.enable_boost_mode()
        logger.info("Boost mode manually ENABLED")
    
    def force_boost_disable(self):
        """Manually disable boost mode"""
        self.tracker.disable_boost_mode()
        logger.info("Boost mode manually DISABLED")
    
    def get_confidence_summary(self, symbols: Optional[List[str]] = None) -> Dict:
        """Get comprehensive confidence summary"""
        
        if symbols is None:
            symbols = list(self.tracker.confidence_history.keys())
        
        summary = {
            'boost_status': self.tracker.get_boost_status(),
            'symbols': {}
        }
        
        for symbol in symbols:
            eligible, details = self.tracker._check_symbol_eligibility(symbol)
            summary['symbols'][symbol] = {
                'eligible': eligible,
                'details': details
            }
        
        return summary
    
    def _maybe_update_boost_status(self):
        """Check if boost status should be updated based on recent data"""
        
        current_time = time.time()
        
        if current_time - self.last_boost_check < self.boost_check_interval:
            return
        
        self.last_boost_check = current_time
        
        # Get all tracked symbols
        tracked_symbols = list(self.tracker.confidence_history.keys())
        
        if not tracked_symbols:
            return
        
        # Check if boost should be enabled/disabled
        boost_allowed, details = self.tracker.check_boost_eligibility(tracked_symbols)
        
        if boost_allowed and not self.tracker.boost_enabled:
            self.tracker.enable_boost_mode()
        elif not boost_allowed and self.tracker.boost_enabled:
            self.tracker.disable_boost_mode()


if __name__ == "__main__":
    # Test confidence gates system
    logging.basicConfig(level=logging.INFO)
    
    print("🧪 Testing Confidence Gates for Symbol Expansion...")
    
    # Initialize manager
    config = ConfidenceGateConfig(
        min_confidence_for_boost=0.85,
        min_timeframes_required=2,  # Reduced for testing
        consensus_agreement_threshold=0.70
    )
    
    manager = ConfidenceGateManager(config)
    
    print(f"📊 Configuration:")
    print(f"  Base symbols: {config.base_symbols}")
    print(f"  Boost symbols: {config.boost_symbols}")
    print(f"  Min confidence: {config.min_confidence_for_boost}")
    print(f"  Required timeframes: {config.min_timeframes_required}")
    
    # Simulate predictions for multiple symbols and timeframes
    test_symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
    timeframes = ['1m', '5m', '15m']
    
    print(f"\n🔄 Simulating predictions...")
    
    # Add high-confidence predictions for first two symbols
    for i in range(15):
        timestamp = time.time() - (15-i) * 60  # 1 minute intervals
        
        for symbol in test_symbols[:2]:  # First 2 symbols get good predictions
            for tf in timeframes:
                # High confidence, good agreement
                confidence = 0.88 + np.random.normal(0, 0.02)
                ppo_logit = np.random.normal(2.0, 0.5)  # Positive bias
                masa_logit = ppo_logit + np.random.normal(0, 0.3)  # Similar to PPO
                regime = MarketRegime.TREND
                
                manager.update_symbol_prediction(
                    symbol, tf, confidence, ppo_logit, masa_logit, regime, timestamp
                )
        
        # Add poor predictions for third symbol
        symbol = test_symbols[2]
        for tf in timeframes:
            # Low confidence, poor agreement
            confidence = 0.65 + np.random.normal(0, 0.05)
            ppo_logit = np.random.normal(0, 1.0)  # Random
            masa_logit = np.random.normal(0, 1.0)  # Random
            regime = MarketRegime.RANGE
            
            manager.update_symbol_prediction(
                symbol, tf, confidence, ppo_logit, masa_logit, regime, timestamp
            )
    
    # Test symbol expansion
    print(f"\n🎯 Testing Symbol Expansion...")
    
    current_symbols = ['BTCUSDT', 'ETHUSDT']
    target_symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'ADAUSDT', 'DOTUSDT']
    
    expansion_allowed, approved_symbols, details = manager.check_symbol_expansion_allowed(
        current_symbols, target_symbols
    )
    
    print(f"  Current symbols: {len(current_symbols)}")
    print(f"  Target symbols: {len(target_symbols)}")
    print(f"  Expansion allowed: {expansion_allowed}")
    print(f"  Approved symbols: {len(approved_symbols)} - {approved_symbols}")
    
    # Get confidence summary
    summary = manager.get_confidence_summary(test_symbols)
    
    print(f"\n📈 Confidence Summary:")
    print(f"  Boost enabled: {summary['boost_status']['boost_enabled']}")
    print(f"  Current limit: {summary['boost_status']['current_symbol_limit']}")
    
    for symbol, data in summary['symbols'].items():
        print(f"  {symbol}: eligible={data['eligible']}")
        if data['details']['timeframes_data']:
            avg_conf = np.mean([tf['confidence'] for tf in data['details']['timeframes_data'].values()])
            print(f"    Avg confidence: {avg_conf:.3f}")
    
    print(f"\n✅ Confidence gates system ready!")
    print(f"  Boost status: {'ENABLED' if manager.tracker.boost_enabled else 'DISABLED'}")
    print(f"  Eligible for boost: {len([s for s, d in summary['symbols'].items() if d['eligible']])}/{len(test_symbols)} symbols")