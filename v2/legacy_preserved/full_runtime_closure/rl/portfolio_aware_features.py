"""
Portfolio-Aware Model Features
Enhanced model inputs that include current portfolio state for hedge-aware decision making
"""

import torch
import torch.nn as nn
import numpy as np
import logging
from typing import Dict, List, Optional, Tuple, Union
from dataclasses import dataclass
from enum import Enum
import time

logger = logging.getLogger(__name__)


@dataclass
class PortfolioFeatureConfig:
    """Configuration for portfolio feature dimensions"""
    # Per-symbol features (repeated for each active symbol)
    per_symbol_features: int = 12  # long_qty, short_qty, avg_entry_long, avg_entry_short, unrealized_pnl_long, unrealized_pnl_short, margin_used, exposure_pct, hold_time_long, hold_time_short, last_action, confidence_score
    
    # Global portfolio features
    global_features: int = 15  # total_balance, available_margin, used_margin, total_exposure, num_symbols, daily_pnl, max_drawdown, win_rate, avg_hold_time, leverage_ratio, var_95, sharpe_ratio, volatility, correlation_score, risk_score
    
    # Risk state features
    risk_features: int = 8  # daily_loss_pct, loss_streak, violation_count, circuit_breaker_active, boost_mode_active, confidence_avg, signal_quality, market_regime
    
    # Maximum symbols to track
    max_symbols: int = 5  # For boost mode
    
    @property
    def total_per_symbol_features(self) -> int:
        """Total features for all symbols"""
        return self.per_symbol_features * self.max_symbols
    
    @property
    def total_portfolio_features(self) -> int:
        """Total portfolio-aware features"""
        return self.total_per_symbol_features + self.global_features + self.risk_features


class PortfolioFeatureExtractor:
    """
    Extracts portfolio-aware features for model input.
    
    Features include:
    - Per-symbol position state (long/short quantities, PnL, etc.)
    - Global portfolio metrics (balance, exposure, risk metrics)
    - Risk state indicators (daily loss, violations, etc.)
    """
    
    def __init__(
        self,
        config: PortfolioFeatureConfig = None,
        device: str = "cuda" if torch.cuda.is_available() else "cpu"
    ):
        """
        Initialize portfolio feature extractor.
        
        Args:
            config: Feature configuration
            device: PyTorch device
        """
        self.config = config or PortfolioFeatureConfig()
        self.device = torch.device(device)
        
        # Symbol ordering for consistent feature layout
        self.symbol_order = []  # Will be populated dynamically
        
        logger.info(f"PortfolioFeatureExtractor initialized: {self.config.total_portfolio_features} features")
    
    def extract_portfolio_features(
        self,
        portfolio_state: Dict,
        symbol_focus: Optional[str] = None,
        timestamp: Optional[float] = None
    ) -> torch.Tensor:
        """
        Extract complete portfolio feature vector.
        
        Args:
            portfolio_state: Portfolio state from PortfolioState service
            symbol_focus: Primary symbol for action decision (optional)
            timestamp: Current timestamp
            
        Returns:
            Portfolio feature tensor [total_portfolio_features]
        """
        if timestamp is None:
            timestamp = time.time()
        
        # Extract feature components
        per_symbol_features = self._extract_per_symbol_features(
            portfolio_state, symbol_focus, timestamp
        )
        global_features = self._extract_global_features(portfolio_state, timestamp)
        risk_features = self._extract_risk_features(portfolio_state, timestamp)
        
        # Concatenate all features
        portfolio_features = torch.cat([
            per_symbol_features,
            global_features,
            risk_features
        ], dim=0)
        
        return portfolio_features.to(self.device)
    
    def extract_batch_portfolio_features(
        self,
        portfolio_states: List[Dict],
        symbol_focus_list: Optional[List[str]] = None,
        timestamps: Optional[List[float]] = None
    ) -> torch.Tensor:
        """
        Extract portfolio features for a batch.
        
        Args:
            portfolio_states: List of portfolio states
            symbol_focus_list: List of focus symbols for each batch item
            timestamps: List of timestamps
            
        Returns:
            Batched portfolio feature tensor [batch_size, total_portfolio_features]
        """
        batch_size = len(portfolio_states)
        
        if symbol_focus_list is None:
            symbol_focus_list = [None] * batch_size
        
        if timestamps is None:
            timestamps = [time.time()] * batch_size
        
        batch_features = []
        
        for i in range(batch_size):
            features = self.extract_portfolio_features(
                portfolio_states[i],
                symbol_focus_list[i],
                timestamps[i]
            )
            batch_features.append(features)
        
        return torch.stack(batch_features, dim=0)
    
    def _extract_per_symbol_features(
        self,
        portfolio_state: Dict,
        symbol_focus: Optional[str],
        timestamp: float
    ) -> torch.Tensor:
        """Extract per-symbol position features"""
        
        # Get active symbols from portfolio
        active_symbols = list(portfolio_state.get('positions', {}).keys())
        
        # Ensure symbol_focus is included if provided
        if symbol_focus and symbol_focus not in active_symbols:
            active_symbols.append(symbol_focus)
        
        # Update symbol ordering
        self._update_symbol_order(active_symbols, symbol_focus)
        
        # Initialize feature matrix [max_symbols, per_symbol_features]
        symbol_features = torch.zeros(
            self.config.max_symbols, 
            self.config.per_symbol_features,
            device=self.device
        )
        
        positions = portfolio_state.get('positions', {})
        
        for i, symbol in enumerate(self.symbol_order[:self.config.max_symbols]):
            if symbol in positions:
                pos_data = positions[symbol]
                
                # Extract per-symbol features
                features = [
                    pos_data.get('long_qty', 0.0),
                    pos_data.get('short_qty', 0.0),
                    pos_data.get('avg_entry_long', 0.0),
                    pos_data.get('avg_entry_short', 0.0),
                    pos_data.get('unrealized_pnl_long', 0.0),
                    pos_data.get('unrealized_pnl_short', 0.0),
                    pos_data.get('margin_used', 0.0),
                    pos_data.get('exposure_pct', 0.0),
                    pos_data.get('hold_time_long_hours', 0.0),
                    pos_data.get('hold_time_short_hours', 0.0),
                    pos_data.get('last_action_code', 0.0),  # Encoded action
                    pos_data.get('confidence_score', 0.0)
                ]
                
                symbol_features[i] = torch.tensor(
                    features, dtype=torch.float32, device=self.device
                )
        
        # Flatten to 1D
        return symbol_features.flatten()
    
    def _extract_global_features(
        self,
        portfolio_state: Dict,
        timestamp: float
    ) -> torch.Tensor:
        """Extract global portfolio features"""
        
        # Global portfolio metrics
        features = [
            portfolio_state.get('total_balance', 0.0),
            portfolio_state.get('available_margin', 0.0),
            portfolio_state.get('used_margin', 0.0),
            portfolio_state.get('total_exposure', 0.0),
            portfolio_state.get('num_symbols', 0.0),
            portfolio_state.get('daily_pnl', 0.0),
            portfolio_state.get('max_drawdown', 0.0),
            portfolio_state.get('win_rate', 0.0),
            portfolio_state.get('avg_hold_time_hours', 0.0),
            portfolio_state.get('leverage_ratio', 1.0),
            portfolio_state.get('var_95', 0.0),
            portfolio_state.get('sharpe_ratio', 0.0),
            portfolio_state.get('volatility', 0.0),
            portfolio_state.get('correlation_score', 0.0),
            portfolio_state.get('risk_score', 0.0)
        ]
        
        return torch.tensor(features, dtype=torch.float32, device=self.device)
    
    def _extract_risk_features(
        self,
        portfolio_state: Dict,
        timestamp: float
    ) -> torch.Tensor:
        """Extract risk state features"""
        
        # Risk and control features
        features = [
            portfolio_state.get('daily_loss_pct', 0.0),
            portfolio_state.get('loss_streak', 0.0),
            portfolio_state.get('violation_count', 0.0),
            float(portfolio_state.get('circuit_breaker_active', False)),
            float(portfolio_state.get('boost_mode_active', False)),
            portfolio_state.get('confidence_avg', 0.0),
            portfolio_state.get('signal_quality', 0.0),
            portfolio_state.get('market_regime_code', 0.0)  # Encoded regime
        ]
        
        return torch.tensor(features, dtype=torch.float32, device=self.device)
    
    def _update_symbol_order(self, active_symbols: List[str], symbol_focus: Optional[str]):
        """Update symbol ordering for consistent feature layout"""
        
        # Prioritize focus symbol first
        new_order = []
        if symbol_focus and symbol_focus in active_symbols:
            new_order.append(symbol_focus)
        
        # Add other active symbols
        for symbol in sorted(active_symbols):  # Sort for consistency
            if symbol != symbol_focus:
                new_order.append(symbol)
        
        # Keep existing symbols that are still relevant
        for symbol in self.symbol_order:
            if symbol in active_symbols and symbol not in new_order:
                new_order.append(symbol)
        
        self.symbol_order = new_order
    
    def get_feature_names(self) -> List[str]:
        """Get human-readable feature names for debugging"""
        names = []
        
        # Per-symbol feature names
        per_symbol_names = [
            'long_qty', 'short_qty', 'avg_entry_long', 'avg_entry_short',
            'unrealized_pnl_long', 'unrealized_pnl_short', 'margin_used',
            'exposure_pct', 'hold_time_long_hours', 'hold_time_short_hours',
            'last_action_code', 'confidence_score'
        ]
        
        for i in range(self.config.max_symbols):
            for name in per_symbol_names:
                names.append(f"symbol_{i}_{name}")
        
        # Global feature names
        global_names = [
            'total_balance', 'available_margin', 'used_margin', 'total_exposure',
            'num_symbols', 'daily_pnl', 'max_drawdown', 'win_rate',
            'avg_hold_time_hours', 'leverage_ratio', 'var_95', 'sharpe_ratio',
            'volatility', 'correlation_score', 'risk_score'
        ]
        names.extend(global_names)
        
        # Risk feature names
        risk_names = [
            'daily_loss_pct', 'loss_streak', 'violation_count',
            'circuit_breaker_active', 'boost_mode_active', 'confidence_avg',
            'signal_quality', 'market_regime_code'
        ]
        names.extend(risk_names)
        
        return names


class PortfolioAwareModelHead(nn.Module):
    """
    Model head that processes portfolio-aware features alongside market features.
    
    Combines:
    - Market features (technical indicators, orderbook, etc.) 
    - Portfolio features (positions, PnL, risk state)
    """
    
    def __init__(
        self,
        market_features_dim: int,
        portfolio_features_dim: int,
        hidden_dim: int = 256,
        dropout: float = 0.1,
        device: str = "cuda" if torch.cuda.is_available() else "cpu"
    ):
        """
        Initialize portfolio-aware model head.
        
        Args:
            market_features_dim: Dimension of market features
            portfolio_features_dim: Dimension of portfolio features
            hidden_dim: Hidden layer dimension
            dropout: Dropout rate
            device: PyTorch device
        """
        super().__init__()
        
        self.market_features_dim = market_features_dim
        self.portfolio_features_dim = portfolio_features_dim
        self.device = torch.device(device)
        
        # Market feature processor
        self.market_processor = nn.Sequential(
            nn.Linear(market_features_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim // 2)
        )
        
        # Portfolio feature processor
        self.portfolio_processor = nn.Sequential(
            nn.Linear(portfolio_features_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim // 2)
        )
        
        # Combined feature processor
        combined_dim = hidden_dim  # hidden_dim//2 + hidden_dim//2
        self.combined_processor = nn.Sequential(
            nn.Linear(combined_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim)
        )
        
        self.output_dim = hidden_dim
        
        # Move to device
        self.to(self.device)
        
        logger.info(f"PortfolioAwareModelHead initialized: market({market_features_dim}) + portfolio({portfolio_features_dim}) -> {hidden_dim} on {device}")
    
    def forward(
        self,
        market_features: torch.Tensor,
        portfolio_features: torch.Tensor
    ) -> torch.Tensor:
        """
        Forward pass combining market and portfolio features.
        
        Args:
            market_features: [batch, market_features_dim]
            portfolio_features: [batch, portfolio_features_dim]
            
        Returns:
            Combined features: [batch, output_dim]
        """
        # Process market features
        market_processed = self.market_processor(market_features)
        
        # Process portfolio features
        portfolio_processed = self.portfolio_processor(portfolio_features)
        
        # Combine features
        combined = torch.cat([market_processed, portfolio_processed], dim=-1)
        
        # Final processing
        output = self.combined_processor(combined)
        
        return output


if __name__ == "__main__":
    # Test portfolio feature extraction
    logging.basicConfig(level=logging.INFO)
    
    # Create test portfolio state
    test_portfolio = {
        'positions': {
            'BTCUSDT': {
                'long_qty': 0.1,
                'short_qty': 0.05,
                'avg_entry_long': 50000,
                'avg_entry_short': 49800,
                'unrealized_pnl_long': 200,
                'unrealized_pnl_short': -50,
                'margin_used': 1500,
                'exposure_pct': 0.15,
                'hold_time_long_hours': 2.5,
                'hold_time_short_hours': 1.0,
                'last_action_code': 2,  # INCREASE_LONG
                'confidence_score': 0.85
            },
            'ETHUSDT': {
                'long_qty': 0.0,
                'short_qty': 2.0,
                'avg_entry_long': 0,
                'avg_entry_short': 3200,
                'unrealized_pnl_long': 0,
                'unrealized_pnl_short': 150,
                'margin_used': 800,
                'exposure_pct': 0.08,
                'hold_time_long_hours': 0,
                'hold_time_short_hours': 0.5,
                'last_action_code': 1,  # OPEN_SHORT
                'confidence_score': 0.78
            }
        },
        'total_balance': 15000,
        'available_margin': 12700,
        'used_margin': 2300,
        'total_exposure': 0.23,
        'num_symbols': 2,
        'daily_pnl': 300,
        'max_drawdown': -0.02,
        'win_rate': 0.65,
        'avg_hold_time_hours': 1.5,
        'leverage_ratio': 3.2,
        'var_95': -150,
        'sharpe_ratio': 1.8,
        'volatility': 0.15,
        'correlation_score': 0.3,
        'risk_score': 0.4,
        'daily_loss_pct': 0.0,
        'loss_streak': 0,
        'violation_count': 0,
        'circuit_breaker_active': False,
        'boost_mode_active': True,
        'confidence_avg': 0.815,
        'signal_quality': 0.8,
        'market_regime_code': 1.0  # Trend
    }
    
    print("🧪 Testing Portfolio Feature Extractor...")
    
    # Initialize extractor
    extractor = PortfolioFeatureExtractor()
    
    # Extract features
    features = extractor.extract_portfolio_features(test_portfolio, symbol_focus="BTCUSDT")
    
    print(f"\n📊 Portfolio Features:")
    print(f"  Feature vector shape: {features.shape}")
    print(f"  Total features: {extractor.config.total_portfolio_features}")
    print(f"  Per-symbol features: {extractor.config.total_per_symbol_features}")
    print(f"  Global features: {extractor.config.global_features}")
    print(f"  Risk features: {extractor.config.risk_features}")
    
    # Test batch processing
    batch_features = extractor.extract_batch_portfolio_features(
        [test_portfolio, test_portfolio],
        symbol_focus_list=["BTCUSDT", "ETHUSDT"]
    )
    
    print(f"\n🔄 Batch Processing:")
    print(f"  Batch features shape: {batch_features.shape}")
    
    # Test portfolio-aware model head
    print(f"\n🧠 Testing Portfolio-Aware Model Head...")
    
    market_dim = 137  # From unified feature builder
    portfolio_dim = extractor.config.total_portfolio_features
    device = extractor.device
    
    model_head = PortfolioAwareModelHead(market_dim, portfolio_dim, device=device)
    
    # Create mock market features on same device
    mock_market_features = torch.randn(2, market_dim, device=device)
    
    # Forward pass
    combined_output = model_head(mock_market_features, batch_features)
    
    print(f"  Market features shape: {mock_market_features.shape}")
    print(f"  Portfolio features shape: {batch_features.shape}")
    print(f"  Combined output shape: {combined_output.shape}")
    print(f"  Model output dim: {model_head.output_dim}")
    
    print(f"\n✅ Portfolio-aware features successfully integrated!")