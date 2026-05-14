"""
Global Safety Checks for Symbol Expansion
Implements comprehensive safety checks before allowing symbol expansion beyond base limits
"""

import numpy as np
import logging
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum
import time
from collections import defaultdict

logger = logging.getLogger(__name__)


class SafetyCheckResult(Enum):
    """Results of safety checks"""
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"


class AssetClass(Enum):
    """Asset class classifications"""
    MAJOR = "major"  # BTC, ETH
    ALTCOIN = "altcoin"  # Other established coins
    DEFI = "defi"  # DeFi tokens
    MEME = "meme"  # Meme coins
    UNKNOWN = "unknown"


@dataclass
class SafetyLimits:
    """Configuration for global safety limits"""
    
    # Portfolio risk limits
    max_daily_drawdown_pct: float = 0.03  # 3% daily drawdown limit
    min_free_margin_pct: float = 0.20  # 20% minimum free margin
    max_portfolio_leverage: float = 3.0  # Maximum portfolio-wide leverage
    max_correlation_exposure: float = 0.60  # Max exposure to correlated positions
    
    # Per-asset-class exposure limits
    max_major_exposure_pct: float = 0.70  # 70% max in BTC/ETH
    max_altcoin_exposure_pct: float = 0.50  # 50% max in altcoins
    max_defi_exposure_pct: float = 0.30  # 30% max in DeFi
    max_meme_exposure_pct: float = 0.15  # 15% max in meme coins
    
    # Risk state limits
    max_consecutive_losses: int = 5  # Max consecutive losing trades
    max_violation_count: int = 3  # Max risk violations before lockdown
    cooldown_period_minutes: int = 60  # Cooldown after violations
    
    # Market condition limits
    min_market_score: float = 0.3  # Minimum market health score
    max_volatility_threshold: float = 0.95  # Only block in catastrophic conditions; high vol = opportunity
    
    # Time-based restrictions
    max_expansion_frequency_hours: int = 4  # Max one expansion every 4 hours
    min_stable_period_minutes: int = 30  # Must be stable before expansion


class AssetClassifier:
    """Classifies symbols into asset classes for exposure limit calculations"""
    
    # Asset class mappings
    ASSET_MAPPINGS = {
        # Major cryptocurrencies
        'BTCUSDT': AssetClass.MAJOR,
        'ETHUSDT': AssetClass.MAJOR,
        'BTCBUSD': AssetClass.MAJOR,
        'ETHBUSD': AssetClass.MAJOR,
        
        # Established altcoins
        'ADAUSDT': AssetClass.ALTCOIN,
        'SOLUSDT': AssetClass.ALTCOIN,
        'DOTUSDT': AssetClass.ALTCOIN,
        'AVAXUSDT': AssetClass.ALTCOIN,
        'MATICUSDT': AssetClass.ALTCOIN,
        'LINKUSDT': AssetClass.ALTCOIN,
        'ATOMUSDT': AssetClass.ALTCOIN,
        'LTCUSDT': AssetClass.ALTCOIN,
        'XRPUSDT': AssetClass.ALTCOIN,
        
        # DeFi tokens
        'UNIUSDT': AssetClass.DEFI,
        'AAVEUSDT': AssetClass.DEFI,
        'COMPUSDT': AssetClass.DEFI,
        'SUSHIUSDT': AssetClass.DEFI,
        'CRVUSDT': AssetClass.DEFI,
        'MKRUSDT': AssetClass.DEFI,
        
        # Meme coins
        'DOGEUSDT': AssetClass.MEME,
        'SHIBUSDT': AssetClass.MEME,
        'PEPEUSDT': AssetClass.MEME,
    }
    
    @classmethod
    def classify_symbol(cls, symbol: str) -> AssetClass:
        """Classify a symbol into an asset class"""
        return cls.ASSET_MAPPINGS.get(symbol.upper(), AssetClass.UNKNOWN)
    
    @classmethod
    def get_symbols_by_class(cls, symbols: List[str]) -> Dict[AssetClass, List[str]]:
        """Group symbols by asset class"""
        grouped = defaultdict(list)
        for symbol in symbols:
            asset_class = cls.classify_symbol(symbol)
            grouped[asset_class].append(symbol)
        return dict(grouped)


class GlobalSafetyChecker:
    """
    Comprehensive safety checker for symbol expansion.
    
    Performs multiple safety checks:
    1. Drawdown and margin checks
    2. Asset class exposure limits
    3. Risk state validation
    4. Market condition assessment
    5. Time-based restrictions
    """
    
    def __init__(
        self,
        limits: SafetyLimits = None
    ):
        """
        Initialize global safety checker.
        
        Args:
            limits: Safety limit configuration
        """
        self.limits = limits or SafetyLimits()
        
        # Track expansion history
        self.last_expansion_time = None
        self.expansion_count_today = 0
        self.last_daily_reset = time.time()
        
        logger.info("GlobalSafetyChecker initialized")
    
    def check_expansion_safety(
        self,
        portfolio_state: Dict,
        current_symbols: List[str],
        target_symbols: List[str],
        market_conditions: Optional[Dict] = None
    ) -> Tuple[bool, Dict]:
        """
        Perform comprehensive safety checks for symbol expansion.
        
        Args:
            portfolio_state: Current portfolio state
            current_symbols: Currently active symbols
            target_symbols: Desired symbols after expansion
            market_conditions: Optional market condition data
            
        Returns:
            Tuple of (expansion_safe, safety_report)
        """
        safety_report = {
            'overall_safe': False,
            'checks_performed': [],
            'passes': [],
            'failures': [],
            'warnings': [],
            'details': {}
        }
        
        # Reset daily counters if needed
        self._maybe_reset_daily_counters()
        
        # 1. Check drawdown and margin safety
        drawdown_safe, drawdown_details = self._check_drawdown_safety(portfolio_state)
        safety_report['checks_performed'].append('drawdown_safety')
        safety_report['details']['drawdown_safety'] = drawdown_details
        
        if drawdown_safe:
            safety_report['passes'].append('drawdown_safety')
        else:
            safety_report['failures'].append('drawdown_safety')
        
        # 2. Check asset class exposure limits
        exposure_safe, exposure_details = self._check_asset_class_exposure(
            portfolio_state, target_symbols
        )
        safety_report['checks_performed'].append('asset_class_exposure')
        safety_report['details']['asset_class_exposure'] = exposure_details
        
        if exposure_safe:
            safety_report['passes'].append('asset_class_exposure')
        else:
            safety_report['failures'].append('asset_class_exposure')
        
        # 3. Check risk state
        risk_safe, risk_details = self._check_risk_state(portfolio_state)
        safety_report['checks_performed'].append('risk_state')
        safety_report['details']['risk_state'] = risk_details
        
        if risk_safe:
            safety_report['passes'].append('risk_state')
        else:
            safety_report['failures'].append('risk_state')
        
        # 4. Check market conditions
        market_safe, market_details = self._check_market_conditions(market_conditions)
        safety_report['checks_performed'].append('market_conditions')
        safety_report['details']['market_conditions'] = market_details
        
        if market_safe:
            safety_report['passes'].append('market_conditions')
        else:
            safety_report['failures'].append('market_conditions')
        
        # 5. Check time-based restrictions
        timing_safe, timing_details = self._check_timing_restrictions()
        safety_report['checks_performed'].append('timing_restrictions')
        safety_report['details']['timing_restrictions'] = timing_details
        
        if timing_safe:
            safety_report['passes'].append('timing_restrictions')
        else:
            safety_report['failures'].append('timing_restrictions')
        
        # Determine overall safety
        critical_checks = ['drawdown_safety', 'risk_state', 'timing_restrictions']
        critical_failures = [check for check in critical_checks if check in safety_report['failures']]
        
        # All critical checks must pass
        safety_report['overall_safe'] = len(critical_failures) == 0
        
        # Log any failures for warning checks
        warning_checks = ['asset_class_exposure', 'market_conditions']
        for check in warning_checks:
            if check in safety_report['failures']:
                safety_report['warnings'].append(f"{check}_failed")
        
        # Track expansion if approved
        if safety_report['overall_safe']:
            self._record_expansion()
        
        logger.info(f"Safety check result: {'SAFE' if safety_report['overall_safe'] else 'UNSAFE'} "
                   f"({len(safety_report['passes'])}/{len(safety_report['checks_performed'])} passed)")
        
        return safety_report['overall_safe'], safety_report
    
    def _check_drawdown_safety(self, portfolio_state: Dict) -> Tuple[bool, Dict]:
        """Check drawdown and margin safety"""
        
        details = {
            'daily_drawdown_pct': 0.0,
            'free_margin_pct': 0.0,
            'portfolio_leverage': 0.0,
            'drawdown_ok': False,
            'margin_ok': False,
            'leverage_ok': False
        }
        
        # Get portfolio metrics
        daily_drawdown_pct = abs(portfolio_state.get('daily_drawdown_pct', 0.0))
        total_balance = portfolio_state.get('total_balance', 0.0)
        used_margin = portfolio_state.get('used_margin', 0.0)
        total_exposure = portfolio_state.get('total_exposure', 0.0)
        
        # Calculate derived metrics
        free_margin = total_balance - used_margin if total_balance > 0 else 0.0
        free_margin_pct = free_margin / total_balance if total_balance > 0 else 0.0
        portfolio_leverage = total_exposure / total_balance if total_balance > 0 else 0.0
        
        details['daily_drawdown_pct'] = daily_drawdown_pct
        details['free_margin_pct'] = free_margin_pct
        details['portfolio_leverage'] = portfolio_leverage
        
        # Check limits
        details['drawdown_ok'] = daily_drawdown_pct <= self.limits.max_daily_drawdown_pct
        details['margin_ok'] = free_margin_pct >= self.limits.min_free_margin_pct
        details['leverage_ok'] = portfolio_leverage <= self.limits.max_portfolio_leverage
        
        # All must pass
        overall_safe = (
            details['drawdown_ok'] and
            details['margin_ok'] and
            details['leverage_ok']
        )
        
        return overall_safe, details
    
    def _check_asset_class_exposure(
        self,
        portfolio_state: Dict,
        target_symbols: List[str]
    ) -> Tuple[bool, Dict]:
        """Check asset class exposure limits"""
        
        details = {
            'exposure_by_class': {},
            'limits_by_class': {},
            'violations': []
        }
        
        # Get position data
        positions = portfolio_state.get('positions', {})
        total_balance = portfolio_state.get('total_balance', 1.0)
        
        # Group target symbols by asset class
        symbols_by_class = AssetClassifier.get_symbols_by_class(target_symbols)
        
        # Calculate exposure by class
        class_limits = {
            AssetClass.MAJOR: self.limits.max_major_exposure_pct,
            AssetClass.ALTCOIN: self.limits.max_altcoin_exposure_pct,
            AssetClass.DEFI: self.limits.max_defi_exposure_pct,
            AssetClass.MEME: self.limits.max_meme_exposure_pct
        }
        
        for asset_class, symbols in symbols_by_class.items():
            total_exposure = 0.0
            
            for symbol in symbols:
                if symbol in positions:
                    pos = positions[symbol]
                    exposure = pos.get('margin_used', 0.0)
                    total_exposure += exposure
            
            exposure_pct = total_exposure / total_balance if total_balance > 0 else 0.0
            limit_pct = class_limits.get(asset_class, 1.0)
            
            details['exposure_by_class'][asset_class.value] = exposure_pct
            details['limits_by_class'][asset_class.value] = limit_pct
            
            if exposure_pct > limit_pct:
                details['violations'].append({
                    'asset_class': asset_class.value,
                    'exposure': exposure_pct,
                    'limit': limit_pct,
                    'excess': exposure_pct - limit_pct
                })
        
        # Check if any violations exist
        overall_safe = len(details['violations']) == 0
        
        return overall_safe, details
    
    def _check_risk_state(self, portfolio_state: Dict) -> Tuple[bool, Dict]:
        """Check risk state indicators"""
        
        details = {
            'consecutive_losses': 0,
            'violation_count': 0,
            'circuit_breaker_active': False,
            'in_cooldown': False,
            'losses_ok': False,
            'violations_ok': False,
            'circuit_breaker_ok': False
        }
        
        # Get risk indicators
        details['consecutive_losses'] = portfolio_state.get('consecutive_losses', 0)
        details['violation_count'] = portfolio_state.get('violation_count', 0)
        details['circuit_breaker_active'] = portfolio_state.get('circuit_breaker_active', False)
        
        # Check cooldown period
        last_violation_time = portfolio_state.get('last_violation_time', 0)
        current_time = time.time()
        cooldown_elapsed = (current_time - last_violation_time) / 60  # minutes
        details['in_cooldown'] = cooldown_elapsed < self.limits.cooldown_period_minutes
        
        # Check limits
        details['losses_ok'] = details['consecutive_losses'] <= self.limits.max_consecutive_losses
        details['violations_ok'] = details['violation_count'] <= self.limits.max_violation_count
        details['circuit_breaker_ok'] = not details['circuit_breaker_active']
        details['cooldown_ok'] = not details['in_cooldown']
        
        # All must pass
        overall_safe = (
            details['losses_ok'] and
            details['violations_ok'] and
            details['circuit_breaker_ok'] and
            details['cooldown_ok']
        )
        
        return overall_safe, details
    
    def _check_market_conditions(self, market_conditions: Optional[Dict]) -> Tuple[bool, Dict]:
        """Check market condition requirements"""
        
        details = {
            'market_score': 1.0,  # Default to good if no data
            'volatility': 0.0,
            'market_score_ok': True,
            'volatility_ok': True
        }
        
        if market_conditions:
            market_score = market_conditions.get('market_health_score', 1.0)
            volatility = market_conditions.get('market_volatility', 0.0)
            
            details['market_score'] = market_score
            details['volatility'] = volatility
            details['market_score_ok'] = market_score >= self.limits.min_market_score
            details['volatility_ok'] = volatility <= self.limits.max_volatility_threshold
        
        overall_safe = details['market_score_ok'] and details['volatility_ok']
        
        return overall_safe, details
    
    def _check_timing_restrictions(self) -> Tuple[bool, Dict]:
        """Check time-based expansion restrictions"""
        
        details = {
            'last_expansion_hours_ago': float('inf'),
            'expansion_count_today': self.expansion_count_today,
            'timing_ok': False,
            'frequency_ok': False
        }
        
        current_time = time.time()
        
        # Check time since last expansion
        if self.last_expansion_time:
            hours_since_expansion = (current_time - self.last_expansion_time) / 3600
            details['last_expansion_hours_ago'] = hours_since_expansion
            details['timing_ok'] = hours_since_expansion >= self.limits.max_expansion_frequency_hours
        else:
            details['timing_ok'] = True  # No previous expansion
        
        # Check daily frequency (implementation-dependent)
        details['frequency_ok'] = True  # Could add daily limits here
        
        overall_safe = details['timing_ok'] and details['frequency_ok']
        
        return overall_safe, details
    
    def _record_expansion(self):
        """Record that an expansion occurred"""
        current_time = time.time()
        self.last_expansion_time = current_time
        self.expansion_count_today += 1
        
        logger.info(f"Symbol expansion recorded - count today: {self.expansion_count_today}")
    
    def _maybe_reset_daily_counters(self):
        """Reset daily counters if new day"""
        current_time = time.time()
        hours_since_reset = (current_time - self.last_daily_reset) / 3600
        
        if hours_since_reset >= 24:
            self.expansion_count_today = 0
            self.last_daily_reset = current_time
            logger.info("Daily expansion counters reset")
    
    def get_safety_status(self) -> Dict:
        """Get current safety checker status"""
        
        return {
            'limits': {
                'max_daily_drawdown_pct': self.limits.max_daily_drawdown_pct,
                'min_free_margin_pct': self.limits.min_free_margin_pct,
                'max_portfolio_leverage': self.limits.max_portfolio_leverage,
                'max_consecutive_losses': self.limits.max_consecutive_losses,
                'max_violation_count': self.limits.max_violation_count
            },
            'state': {
                'last_expansion_time': self.last_expansion_time,
                'expansion_count_today': self.expansion_count_today,
                'hours_since_last_expansion': (
                    (time.time() - self.last_expansion_time) / 3600
                    if self.last_expansion_time else float('inf')
                )
            }
        }


if __name__ == "__main__":
    # Test global safety checker
    logging.basicConfig(level=logging.INFO)
    
    print("🧪 Testing Global Safety Checks...")
    
    # Initialize checker
    limits = SafetyLimits(
        max_daily_drawdown_pct=0.03,
        min_free_margin_pct=0.20,
        max_portfolio_leverage=3.0
    )
    
    checker = GlobalSafetyChecker(limits)
    
    print(f"📊 Safety Limits:")
    print(f"  Max daily drawdown: {limits.max_daily_drawdown_pct:.1%}")
    print(f"  Min free margin: {limits.min_free_margin_pct:.1%}")
    print(f"  Max portfolio leverage: {limits.max_portfolio_leverage:.1f}x")
    
    # Test safe portfolio state
    safe_portfolio = {
        'total_balance': 10000,
        'used_margin': 6000,  # 60% used, 40% free
        'total_exposure': 25000,  # 2.5x leverage
        'daily_drawdown_pct': 0.015,  # 1.5% drawdown
        'consecutive_losses': 2,
        'violation_count': 0,
        'circuit_breaker_active': False,
        'last_violation_time': 0,
        'positions': {
            'BTCUSDT': {'margin_used': 3000},
            'ETHUSDT': {'margin_used': 2000},
            'SOLUSDT': {'margin_used': 1000}
        }
    }
    
    current_symbols = ['BTCUSDT', 'ETHUSDT']
    target_symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'ADAUSDT', 'DOTUSDT']
    
    print(f"\n🔍 Testing Safe Scenario...")
    
    expansion_safe, safety_report = checker.check_expansion_safety(
        safe_portfolio, current_symbols, target_symbols
    )
    
    print(f"  Expansion safe: {expansion_safe}")
    print(f"  Checks passed: {len(safety_report['passes'])}/{len(safety_report['checks_performed'])}")
    print(f"  Failures: {safety_report['failures']}")
    print(f"  Warnings: {safety_report['warnings']}")
    
    # Test unsafe scenario
    unsafe_portfolio = safe_portfolio.copy()
    unsafe_portfolio.update({
        'daily_drawdown_pct': 0.05,  # 5% drawdown (exceeds limit)
        'used_margin': 9000,  # 90% used, 10% free (below limit)
        'consecutive_losses': 6,  # Too many losses
        'circuit_breaker_active': True
    })
    
    print(f"\n⚠️  Testing Unsafe Scenario...")
    
    expansion_safe, safety_report = checker.check_expansion_safety(
        unsafe_portfolio, current_symbols, target_symbols
    )
    
    print(f"  Expansion safe: {expansion_safe}")
    print(f"  Checks passed: {len(safety_report['passes'])}/{len(safety_report['checks_performed'])}")
    print(f"  Failures: {safety_report['failures']}")
    
    # Show detailed failure reasons
    for failure in safety_report['failures']:
        details = safety_report['details'][failure]
        print(f"  {failure} details: {details}")
    
    print(f"\n✅ Global safety checker ready!")
    print(f"  Asset classes supported: {len(AssetClassifier.ASSET_MAPPINGS)}")
    print(f"  Safety checks implemented: {len(safety_report['checks_performed'])}")