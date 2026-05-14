"""
Portfolio State Features for Model Input
Expands portfolio-aware features with comprehensive risk state indicators
"""

import torch
import numpy as np
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import time
import redis
import json
from collections import deque

logger = logging.getLogger(__name__)


@dataclass
class RiskStateFeatures:
    """Risk state feature configuration and calculation"""
    
    # Lookback periods for rolling metrics
    daily_pnl_window: int = 1440  # 24 hours in minutes
    drawdown_window: int = 7200   # 5 days in minutes
    slippage_window: int = 60     # 1 hour for recent slippage
    
    # Risk thresholds
    max_daily_loss_pct: float = 0.05  # 5% daily loss limit
    max_drawdown_pct: float = 0.15    # 15% max drawdown
    high_slippage_threshold: float = 0.002  # 0.2% slippage considered high
    
    # Feature dimensions
    risk_metrics_features: int = 12  # Extended risk metrics
    
    @property
    def total_risk_features(self) -> int:
        """Total risk state features"""
        return self.risk_metrics_features


class RiskStateCalculator:
    """
    Calculates comprehensive risk state metrics for model input.
    
    Features include:
    - Daily PnL tracking and rolling metrics
    - Maximum drawdown calculation
    - Recent trading costs (slippage, fees)
    - Risk state indicators
    - Volatility and correlation metrics
    """
    
    def __init__(
        self,
        config: RiskStateFeatures = None,
        redis_client: Optional[redis.Redis] = None
    ):
        """
        Initialize risk state calculator.
        
        Args:
            config: Risk feature configuration
            redis_client: Redis client for historical data
        """
        self.config = config or RiskStateFeatures()
        self.redis_client = redis_client
        
        # Internal state for rolling calculations
        self._pnl_history = deque(maxlen=self.config.daily_pnl_window)
        self._balance_history = deque(maxlen=self.config.drawdown_window)
        self._slippage_history = deque(maxlen=self.config.slippage_window)
        self._fee_history = deque(maxlen=self.config.slippage_window)
        
        logger.info(f"RiskStateCalculator initialized with {self.config.total_risk_features} features")
    
    def calculate_risk_features(
        self,
        portfolio_state: Dict,
        current_timestamp: Optional[float] = None
    ) -> torch.Tensor:
        """
        Calculate comprehensive risk state features.
        
        Args:
            portfolio_state: Current portfolio state
            current_timestamp: Current timestamp
            
        Returns:
            Risk feature tensor [risk_metrics_features]
        """
        if current_timestamp is None:
            current_timestamp = time.time()
        
        # Update historical data
        self._update_histories(portfolio_state, current_timestamp)
        
        # Calculate risk metrics
        risk_features = self._calculate_risk_metrics(portfolio_state, current_timestamp)
        
        return torch.tensor(risk_features, dtype=torch.float32)
    
    def _update_histories(self, portfolio_state: Dict, timestamp: float):
        """Update rolling history data"""
        
        # Update PnL history
        current_pnl = portfolio_state.get('current_pnl', 0.0)
        self._pnl_history.append((timestamp, current_pnl))
        
        # Update balance history
        current_balance = portfolio_state.get('total_balance', 0.0)
        self._balance_history.append((timestamp, current_balance))
        
        # Update trading costs if available
        recent_slippage = portfolio_state.get('recent_slippage', 0.0)
        recent_fees = portfolio_state.get('recent_fees', 0.0)
        
        if recent_slippage > 0:
            self._slippage_history.append((timestamp, recent_slippage))
        if recent_fees > 0:
            self._fee_history.append((timestamp, recent_fees))
    
    def _calculate_risk_metrics(self, portfolio_state: Dict, timestamp: float) -> List[float]:
        """Calculate comprehensive risk metrics"""
        
        features = []
        
        # 1. Daily PnL metrics
        daily_pnl, daily_pnl_pct = self._calculate_daily_pnl()
        features.extend([daily_pnl, daily_pnl_pct])
        
        # 2. Drawdown metrics
        current_drawdown, max_drawdown = self._calculate_drawdown()
        features.extend([current_drawdown, max_drawdown])
        
        # 3. Trading cost metrics
        recent_slippage_avg, recent_fees_avg = self._calculate_trading_costs()
        features.extend([recent_slippage_avg, recent_fees_avg])
        
        # 4. Risk state indicators
        loss_streak = self._calculate_loss_streak()
        violation_count = portfolio_state.get('violation_count', 0)
        circuit_breaker_active = float(portfolio_state.get('circuit_breaker_active', False))
        features.extend([loss_streak, violation_count, circuit_breaker_active])
        
        # 5. Portfolio health metrics
        sharpe_ratio = self._calculate_rolling_sharpe()
        volatility = self._calculate_rolling_volatility()
        var_95 = self._calculate_var_95()
        features.extend([sharpe_ratio, volatility, var_95])
        
        return features
    
    def _calculate_daily_pnl(self) -> Tuple[float, float]:
        """Calculate daily PnL absolute and percentage"""
        
        if len(self._pnl_history) < 2:
            return 0.0, 0.0
        
        # Get 24-hour window
        current_time = time.time()
        daily_cutoff = current_time - 24 * 3600  # 24 hours ago
        
        # Filter to daily window
        daily_pnls = [pnl for ts, pnl in self._pnl_history if ts >= daily_cutoff]
        
        if not daily_pnls:
            return 0.0, 0.0
        
        # Calculate daily change
        daily_pnl = daily_pnls[-1] - daily_pnls[0] if len(daily_pnls) > 1 else daily_pnls[0]
        
        # Calculate percentage
        initial_balance = daily_pnls[0] if daily_pnls[0] > 0 else 10000  # Fallback
        daily_pnl_pct = daily_pnl / initial_balance if initial_balance > 0 else 0.0
        
        return daily_pnl, daily_pnl_pct
    
    def _calculate_drawdown(self) -> Tuple[float, float]:
        """Calculate current and maximum drawdown"""
        
        if len(self._balance_history) < 2:
            return 0.0, 0.0
        
        balances = [balance for _, balance in self._balance_history]
        
        # Calculate running maximum (peak)
        peak = balances[0]
        current_drawdown = 0.0
        max_drawdown = 0.0
        
        for balance in balances:
            if balance > peak:
                peak = balance
            
            drawdown = (peak - balance) / peak if peak > 0 else 0.0
            current_drawdown = drawdown  # Current drawdown from peak
            max_drawdown = max(max_drawdown, drawdown)
        
        return current_drawdown, max_drawdown
    
    def _calculate_trading_costs(self) -> Tuple[float, float]:
        """Calculate recent average slippage and fees"""
        
        # Recent slippage average
        if self._slippage_history:
            recent_slippages = [slip for _, slip in self._slippage_history]
            slippage_avg = np.mean(recent_slippages)
        else:
            slippage_avg = 0.0
        
        # Recent fees average
        if self._fee_history:
            recent_fees = [fee for _, fee in self._fee_history]
            fees_avg = np.mean(recent_fees)
        else:
            fees_avg = 0.0
        
        return slippage_avg, fees_avg
    
    def _calculate_loss_streak(self) -> float:
        """Calculate current consecutive loss streak"""
        
        if len(self._pnl_history) < 2:
            return 0.0
        
        # Look at recent PnL changes
        loss_streak = 0
        
        for i in range(len(self._pnl_history) - 1, 0, -1):
            current_pnl = self._pnl_history[i][1]
            prev_pnl = self._pnl_history[i-1][1]
            
            if current_pnl < prev_pnl:  # Loss
                loss_streak += 1
            else:
                break
        
        return float(loss_streak)
    
    def _calculate_rolling_sharpe(self) -> float:
        """Calculate rolling Sharpe ratio"""
        
        if len(self._balance_history) < 30:  # Need some history
            return 0.0
        
        balances = [balance for _, balance in self._balance_history]
        returns = []
        
        for i in range(1, len(balances)):
            if balances[i-1] > 0:
                ret = (balances[i] - balances[i-1]) / balances[i-1]
                returns.append(ret)
        
        if not returns:
            return 0.0
        
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        
        if std_return > 0:
            sharpe = mean_return / std_return * np.sqrt(252)  # Annualized
        else:
            sharpe = 0.0
        
        return sharpe
    
    def _calculate_rolling_volatility(self) -> float:
        """Calculate rolling volatility"""
        
        if len(self._balance_history) < 10:
            return 0.0
        
        balances = [balance for _, balance in self._balance_history]
        returns = []
        
        for i in range(1, len(balances)):
            if balances[i-1] > 0:
                ret = (balances[i] - balances[i-1]) / balances[i-1]
                returns.append(ret)
        
        if not returns:
            return 0.0
        
        volatility = np.std(returns) * np.sqrt(252)  # Annualized
        return volatility
    
    def _calculate_var_95(self) -> float:
        """Calculate 95% Value at Risk"""
        
        if len(self._balance_history) < 20:
            return 0.0
        
        balances = [balance for _, balance in self._balance_history]
        returns = []
        
        for i in range(1, len(balances)):
            if balances[i-1] > 0:
                ret = (balances[i] - balances[i-1]) / balances[i-1]
                returns.append(ret)
        
        if not returns:
            return 0.0
        
        var_95 = np.percentile(returns, 5)  # 5th percentile (95% VaR)
        return var_95


class EnhancedPortfolioStateService:
    """
    Enhanced portfolio state service with comprehensive risk state features.
    
    Extends the basic portfolio state with:
    - Real-time risk metrics calculation
    - Historical PnL tracking
    - Trading cost analysis
    - Risk state indicators
    """
    
    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        risk_config: RiskStateFeatures = None
    ):
        """
        Initialize enhanced portfolio state service.
        
        Args:
            redis_client: Redis client for caching
            risk_config: Risk feature configuration
        """
        self.redis_client = redis_client
        self.risk_calculator = RiskStateCalculator(risk_config, redis_client)
        
        logger.info("EnhancedPortfolioStateService initialized")
    
    def get_enhanced_portfolio_features(
        self,
        portfolio_state: Dict,
        timestamp: Optional[float] = None
    ) -> Dict:
        """
        Get portfolio state enhanced with comprehensive risk features.
        
        Args:
            portfolio_state: Base portfolio state
            timestamp: Current timestamp
            
        Returns:
            Enhanced portfolio state with risk features
        """
        if timestamp is None:
            timestamp = time.time()
        
        # Calculate risk features
        risk_features = self.risk_calculator.calculate_risk_features(
            portfolio_state, timestamp
        )
        
        # Create enhanced state
        enhanced_state = portfolio_state.copy()
        
        # Add individual risk metrics for interpretability
        risk_feature_names = [
            'daily_pnl', 'daily_pnl_pct', 'current_drawdown', 'max_drawdown',
            'recent_slippage_avg', 'recent_fees_avg', 'loss_streak',
            'violation_count', 'circuit_breaker_active', 'sharpe_ratio',
            'volatility', 'var_95'
        ]
        
        for i, name in enumerate(risk_feature_names):
            if i < len(risk_features):
                enhanced_state[f'risk_{name}'] = float(risk_features[i])
        
        # Add risk feature tensor
        enhanced_state['risk_features_tensor'] = risk_features
        
        return enhanced_state
    
    def cache_enhanced_state(self, enhanced_state: Dict, symbol: str):
        """Cache enhanced portfolio state in Redis"""
        
        if not self.redis_client:
            return
        
        cache_key = f"enhanced_portfolio_state:{symbol}"
        
        try:
            # Convert tensors to lists for JSON serialization
            cached_state = enhanced_state.copy()
            if 'risk_features_tensor' in cached_state:
                cached_state['risk_features_tensor'] = cached_state['risk_features_tensor'].tolist()
            
            self.redis_client.setex(
                cache_key,
                300,  # 5 minute expiry
                json.dumps(cached_state, default=str)
            )
            
        except Exception as e:
            logger.warning(f"Failed to cache enhanced portfolio state: {e}")


if __name__ == "__main__":
    # Test enhanced portfolio state features
    logging.basicConfig(level=logging.INFO)
    
    # Create test portfolio state with risk data
    test_portfolio = {
        'positions': {
            'BTCUSDT': {
                'long_qty': 0.1,
                'short_qty': 0.0,
                'unrealized_pnl_long': 200,
                'unrealized_pnl_short': 0,
                'margin_used': 1500,
            }
        },
        'total_balance': 15000,
        'current_pnl': 200,
        'daily_pnl': 300,
        'recent_slippage': 0.001,
        'recent_fees': 15.0,
        'violation_count': 0,
        'circuit_breaker_active': False
    }
    
    print("🧪 Testing Enhanced Portfolio State Features...")
    
    # Initialize services
    risk_calculator = RiskStateCalculator()
    enhanced_service = EnhancedPortfolioStateService()
    
    # Simulate some historical data
    print("📊 Simulating historical data...")
    for i in range(50):
        timestamp = time.time() - (50-i) * 60  # 1 minute intervals
        balance = 15000 + np.random.normal(0, 100) * i  # Random walk
        pnl = np.random.normal(50, 100)  # Random PnL
        
        sim_state = test_portfolio.copy()
        sim_state['total_balance'] = balance
        sim_state['current_pnl'] = pnl
        
        risk_calculator._update_histories(sim_state, timestamp)
    
    # Calculate risk features
    risk_features = risk_calculator.calculate_risk_features(test_portfolio)
    
    print(f"📈 Risk Features:")
    print(f"  Risk feature vector shape: {risk_features.shape}")
    print(f"  Total risk features: {risk_calculator.config.total_risk_features}")
    
    # Test enhanced portfolio state
    enhanced_state = enhanced_service.get_enhanced_portfolio_features(test_portfolio)
    
    print(f"\n🔍 Enhanced Portfolio State:")
    risk_keys = [k for k in enhanced_state.keys() if k.startswith('risk_')]
    for key in risk_keys[:8]:  # Show first 8
        print(f"  {key}: {enhanced_state[key]:.4f}")
    
    print(f"\n✅ Enhanced portfolio state features ready!")
    print(f"  Base portfolio keys: {len([k for k in enhanced_state.keys() if not k.startswith('risk_')])}")
    print(f"  Risk feature keys: {len(risk_keys)}")
    print(f"  Risk tensor shape: {enhanced_state['risk_features_tensor'].shape}")