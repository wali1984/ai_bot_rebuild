"""
Enhanced Neural Network Architectures for Hybrid Trainer
Implements LSTM, Attention, and advanced model components for 1000× profitability goal

Key Features:
- Recurrent networks (LSTM/GRU) for temporal pattern recognition
- Multi-head attention for dynamic feature selection
- Sequence-based observation processing
- Memory-augmented decision making
"""

import logging
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.nn import MultiheadAttention
import numpy as np
from typing import Optional, Dict, Tuple
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor
from stable_baselines3.common.policies import ActorCriticPolicy
from gymnasium import spaces

logger = logging.getLogger(__name__)


class RecurrentFeatureExtractor(BaseFeaturesExtractor):
    """
    LSTM-based feature extractor with attention mechanism for temporal pattern recognition.
    
    Architecture:
    1. Input: Sequence of observations [batch, seq_len, features]
    2. LSTM layers: Capture temporal dependencies
    3. Multi-head attention: Focus on relevant features dynamically
    4. Output: Rich feature representation for policy/value networks
    
    Args:
        observation_space: Observation space (Box)
        features_dim: Output feature dimension
        lstm_hidden_size: Hidden units in LSTM layers
        lstm_num_layers: Number of LSTM layers
        attention_heads: Number of attention heads
        sequence_length: Length of observation history window
        dropout: Dropout rate for regularization
    """
    
    def __init__(
        self,
        observation_space: spaces.Box,
        features_dim: int = 2048,
        lstm_hidden_size: int = 512,
        lstm_num_layers: int = 2,
        attention_heads: int = 8,
        sequence_length: int = 10,
        dropout: float = 0.1
    ):
        # Call parent init FIRST - this sets self._features_dim
        super().__init__(observation_space, features_dim)
        
        self.input_dim = observation_space.shape[0]  # e.g., 1430 or 2000+
        self.lstm_hidden_size = lstm_hidden_size
        self.lstm_num_layers = lstm_num_layers
        self.sequence_length = sequence_length
        # Don't set self.features_dim here - parent already did it
        
        # LSTM for temporal pattern recognition
        # Input: [batch, seq_len, input_dim] -> Output: [batch, seq_len, hidden_size]
        self.lstm = nn.LSTM(
            input_size=self.input_dim,
            hidden_size=lstm_hidden_size,
            num_layers=lstm_num_layers,
            batch_first=True,
            dropout=dropout if lstm_num_layers > 1 else 0.0,
            bidirectional=False  # Keep unidirectional for causal temporal modeling
        )
        
        # Multi-head self-attention for dynamic feature selection
        # Allows model to focus on relevant features at each timestep
        self.attention = MultiheadAttention(
            embed_dim=lstm_hidden_size,
            num_heads=attention_heads,
            dropout=dropout,
            batch_first=True
        )
        
        # Layer normalization for training stability
        self.layer_norm1 = nn.LayerNorm(lstm_hidden_size)
        self.layer_norm2 = nn.LayerNorm(lstm_hidden_size)
        
        # Feed-forward network for feature transformation
        self.ffn = nn.Sequential(
            nn.Linear(lstm_hidden_size, lstm_hidden_size * 2),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(lstm_hidden_size * 2, lstm_hidden_size),
            nn.Dropout(dropout)
        )
        
        # Final projection to desired feature dimension
        self.output_projection = nn.Sequential(
            nn.Linear(lstm_hidden_size, features_dim),
            nn.ReLU(),
            nn.Dropout(dropout)
        )
        
        # Hidden state buffer for maintaining LSTM memory across steps
        # Use lstm_hidden_size (not lstm_output_size) for hidden/cell states
        self.register_buffer('lstm_hidden', torch.zeros(lstm_num_layers, 1, lstm_hidden_size))
        self.register_buffer('lstm_cell', torch.zeros(lstm_num_layers, 1, lstm_hidden_size))
        
        # Sequence buffer to maintain observation history
        self.register_buffer('obs_buffer', torch.zeros(1, sequence_length, self.input_dim))
        
        print(f"✅ RecurrentFeatureExtractor initialized:")
        print(f"   - Input dim: {self.input_dim}")
        print(f"   - LSTM: {lstm_num_layers} layers × {lstm_hidden_size} hidden units")
        print(f"   - Attention: {attention_heads} heads")
        print(f"   - Sequence length: {sequence_length} timesteps")
        print(f"   - Output features: {features_dim}")
    
    def reset_hidden_states(self, device: Optional[torch.device] = None, dtype: Optional[torch.dtype] = None) -> None:
        """
        Reset LSTM hidden states to zeros. Call this after checkpoint load or device changes.
        
        Args:
            device: Target device (defaults to current lstm_hidden device or cuda)
            dtype: Target dtype (defaults to float32)
        """
        if device is None:
            device = self.lstm_hidden.device if self.lstm_hidden is not None else torch.device('cuda')
        if dtype is None:
            dtype = torch.float32
            
        num_layers = self.lstm.num_layers
        hidden_size = self.lstm.hidden_size
        
        self.lstm_hidden = torch.zeros(num_layers, 1, hidden_size, device=device, dtype=dtype)
        self.lstm_cell = torch.zeros(num_layers, 1, hidden_size, device=device, dtype=dtype)
        logger.debug(f"[LSTM_RESET] Hidden states reset on {device}")
    
    def forward(self, observations: torch.Tensor) -> torch.Tensor:
        """
        Forward pass with temporal processing and attention.
        
        Args:
            observations: Current observations [batch, input_dim]
        
        Returns:
            features: Processed features [batch, features_dim]
        """
        # CRITICAL FIX: Ensure ALL submodules stay in training mode during training
        # This prevents "cudnn RNN backward can only be called in training mode" error
        # PyTorch's .train() doesn't override explicit .eval() calls on submodules,
        # so we must explicitly set training mode on every forward pass
        if self.training:
            # Core processing modules
            self.lstm.train()
            self.attention.train()
            # Normalization layers
            self.layer_norm1.train()
            self.layer_norm2.train()
            # Feed-forward and output
            self.ffn.train()
            self.output_projection.train()
        
        batch_size = observations.shape[0]
        
        # DEFENSIVE FIX: Reinitialize LSTM hidden states if they became None
        # This can happen after checkpoint saves that temporarily moved to CPU
        if self.lstm_hidden is None or self.lstm_cell is None:
            device = observations.device
            self.lstm_hidden = torch.zeros(
                self.lstm.num_layers, 1, self.lstm.hidden_size, 
                device=device, dtype=observations.dtype
            )
            self.lstm_cell = torch.zeros(
                self.lstm.num_layers, 1, self.lstm.hidden_size, 
                device=device, dtype=observations.dtype
            )
            logger.debug(f"[LSTM_REINIT] Reinitialized hidden states on {device}")
        
        # Handle sequence buffering
        if batch_size == 1:
            # Single observation - update buffer and maintain history
            # Shift buffer and add new observation
            # CRITICAL: Detach during training to avoid gradient contamination
            if self.training:
                self.obs_buffer = torch.cat([
                    self.obs_buffer[:, 1:, :].detach(),  # Remove oldest, detach
                    observations.unsqueeze(1)             # Add newest
                ], dim=1)
            else:
                self.obs_buffer = torch.cat([
                    self.obs_buffer[:, 1:, :],  # Remove oldest
                    observations.unsqueeze(1)    # Add newest
                ], dim=1)
            obs_sequence = self.obs_buffer
        else:
            # Batch of observations - create sequences by repeating
            # In training, we process batches without history (stateless)
            obs_sequence = observations.unsqueeze(1).repeat(1, self.sequence_length, 1)
        
        # Expand hidden states to match batch size
        # CRITICAL: Detach hidden states during training to avoid gradient issues
        # from previous eval mode passes
        if batch_size != self.lstm_hidden.shape[1]:
            if self.training:
                # During training, always start fresh to avoid gradient contamination
                lstm_hidden = self.lstm_hidden.detach().expand(-1, batch_size, -1).contiguous()
                lstm_cell = self.lstm_cell.detach().expand(-1, batch_size, -1).contiguous()
            else:
                # During inference, use existing hidden states
                lstm_hidden = self.lstm_hidden.expand(-1, batch_size, -1).contiguous()
                lstm_cell = self.lstm_cell.expand(-1, batch_size, -1).contiguous()
        else:
            if self.training:
                lstm_hidden = self.lstm_hidden.detach()
                lstm_cell = self.lstm_cell.detach()
            else:
                lstm_hidden = self.lstm_hidden
                lstm_cell = self.lstm_cell
        
        # LSTM processing: [batch, seq_len, input_dim] -> [batch, seq_len, hidden_size]
        # CRITICAL FIX: Disable cuDNN for LSTM to avoid "cudnn RNN backward can only be called in training mode"
        # This uses PyTorch's fallback implementation which properly handles train/eval mode switching
        cudnn_enabled = torch.backends.cudnn.enabled
        try:
            torch.backends.cudnn.enabled = False  # Temporarily disable cuDNN
            
            # Ensure LSTM is in correct mode right before forward pass
            if self.training:
                self.lstm.train()
            else:
                self.lstm.eval()
            
            lstm_out, (new_hidden, new_cell) = self.lstm(obs_sequence, (lstm_hidden, lstm_cell))
        finally:
            torch.backends.cudnn.enabled = cudnn_enabled  # Restore cuDNN setting
        
        # Update hidden states for next forward pass (only for single batch)
        if batch_size == 1:
            self.lstm_hidden = new_hidden.detach()
            self.lstm_cell = new_cell.detach()
        
        # Apply layer normalization
        lstm_out_norm = self.layer_norm1(lstm_out)
        
        # Multi-head self-attention: focus on relevant timesteps and features
        # Query, Key, Value all come from LSTM output
        attn_out, attn_weights = self.attention(
            lstm_out_norm,  # Query
            lstm_out_norm,  # Key
            lstm_out_norm   # Value
        )
        
        # Residual connection and normalization
        attn_out = self.layer_norm2(lstm_out_norm + attn_out)
        
        # Feed-forward network with residual connection
        ffn_out = self.ffn(attn_out)
        ffn_out = attn_out + ffn_out  # Residual
        
        # Take the last timestep output (most recent with full context)
        final_features = ffn_out[:, -1, :]  # [batch, hidden_size]
        
        # Project to desired feature dimension
        output_features = self.output_projection(final_features)  # [batch, features_dim]
        
        return output_features
    
    def reset_hidden_states(self):
        """Reset LSTM hidden states (call at episode start)"""
        self.lstm_hidden.zero_()
        self.lstm_cell.zero_()
        self.obs_buffer.zero_()


class RecurrentActorCriticPolicy(ActorCriticPolicy):
    """
    Actor-Critic policy using RecurrentFeatureExtractor.
    
    This policy uses LSTM + Attention for processing observations,
    enabling the agent to recognize temporal patterns and make
    memory-informed decisions.
    """
    
    def __init__(self, *args, **kwargs):
        # Extract custom kwargs
        lstm_hidden_size = kwargs.pop('lstm_hidden_size', 512)
        lstm_num_layers = kwargs.pop('lstm_num_layers', 2)
        attention_heads = kwargs.pop('attention_heads', 8)
        sequence_length = kwargs.pop('sequence_length', 10)
        dropout = kwargs.pop('dropout', 0.1)
        
        super().__init__(
            *args,
            **kwargs,
            features_extractor_class=RecurrentFeatureExtractor,
            features_extractor_kwargs={
                "features_dim": 2048,
                "lstm_hidden_size": lstm_hidden_size,
                "lstm_num_layers": lstm_num_layers,
                "attention_heads": attention_heads,
                "sequence_length": sequence_length,
                "dropout": dropout
            }
        )


class MarketRegimeObserver(nn.Module):
    """
    Market Regime Observer for adaptive strategy selection.
    
    Classifies market conditions into regimes:
    - Trending Bull: Strong upward momentum
    - Trending Bear: Strong downward momentum  
    - Volatile: High volatility, unclear direction
    - Calm: Low volatility, sideways/consolidation
    
    Outputs:
    - Regime classification (4 classes)
    - Uncertainty score (0-1)
    - Trend strength (-1 to +1)
    - Volatility level (0-1)
    
    This information is used to:
    1. Adjust MASA weight dynamically
    2. Modify risk parameters
    3. Adapt position sizing
    """
    
    def __init__(self, input_dim: int = 100, hidden_dim: int = 256):
        """
        Args:
            input_dim: Number of market features (volatility, volume, momentum indicators)
            hidden_dim: Hidden layer dimension
        """
        super().__init__()
        
        self.input_dim = input_dim
        
        # Feature extraction network
        self.feature_net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1)
        )
        
        # Regime classifier (4 classes: trending_bull, trending_bear, volatile, calm)
        self.regime_head = nn.Linear(hidden_dim, 4)
        
        # Uncertainty estimator (higher = more uncertain)
        self.uncertainty_head = nn.Sequential(
            nn.Linear(hidden_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
            nn.Sigmoid()  # Output 0-1
        )
        
        # Trend strength estimator (-1 to +1)
        self.trend_head = nn.Sequential(
            nn.Linear(hidden_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
            nn.Tanh()  # Output -1 to +1
        )
        
        # Volatility level estimator (0-1)
        self.volatility_head = nn.Sequential(
            nn.Linear(hidden_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 1),
            nn.Sigmoid()  # Output 0-1
        )
        
        print(f"✅ MarketRegimeObserver initialized:")
        print(f"   - Input: {input_dim} market features")
        print(f"   - Outputs: regime (4 classes), uncertainty, trend, volatility")
    
    def forward(self, market_features: torch.Tensor) -> Dict[str, torch.Tensor]:
        """
        Analyze market regime.
        
        Args:
            market_features: Market indicators [batch, input_dim]
        
        Returns:
            Dictionary with regime info:
            - regime_logits: Raw logits for 4 regimes [batch, 4]
            - regime_probs: Probabilities [batch, 4]
            - regime_class: Predicted regime [batch]
            - uncertainty: Uncertainty score [batch, 1]
            - trend_strength: Trend direction/strength [batch, 1]
            - volatility: Volatility level [batch, 1]
        """
        # Extract features
        features = self.feature_net(market_features)
        
        # Regime classification
        regime_logits = self.regime_head(features)
        regime_probs = F.softmax(regime_logits, dim=-1)
        regime_class = torch.argmax(regime_probs, dim=-1)
        
        # Market metrics
        uncertainty = self.uncertainty_head(features)
        trend_strength = self.trend_head(features)
        volatility = self.volatility_head(features)
        
        return {
            'regime_logits': regime_logits,
            'regime_probs': regime_probs,
            'regime_class': regime_class,
            'uncertainty': uncertainty,
            'trend_strength': trend_strength,
            'volatility': volatility
        }
    
    def get_masa_weight(self, uncertainty: torch.Tensor, base_weight: float = 0.6) -> torch.Tensor:
        """
        Calculate dynamic MASA weight based on market uncertainty.
        
        Higher uncertainty -> Higher MASA weight (more risk management)
        Lower uncertainty -> Lower MASA weight (more PPO exploration)
        
        Args:
            uncertainty: Uncertainty score [batch, 1]
            base_weight: Base MASA weight (default 0.6)
        
        Returns:
            Dynamic MASA weight [batch, 1]
        """
        # Weight ranges from 0.2 (low uncertainty) to 0.8 (high uncertainty)
        min_weight = 0.2
        max_weight = 0.8
        
        # Linear interpolation based on uncertainty
        dynamic_weight = min_weight + uncertainty * (max_weight - min_weight)
        
        return dynamic_weight


class EnhancedRewardFunction:
    """
    Enhanced reward function with risk-adjusted returns and Sharpe ratio components.
    
    Features:
    - Risk-adjusted rewards (penalize volatility and drawdowns)
    - Sharpe ratio components
    - Trade quality metrics (win rate, profit factor)
    - Drawdown penalties
    - Smooth profit curve rewards
    """
    
    def __init__(
        self,
        sharpe_weight: float = 0.3,
        drawdown_penalty: float = 2.0,
        volatility_penalty: float = 0.5,
        win_rate_bonus: float = 0.2,
        risk_free_rate: float = 0.0
    ):
        """
        Args:
            sharpe_weight: Weight for Sharpe ratio component
            drawdown_penalty: Penalty multiplier for drawdowns
            volatility_penalty: Penalty for high volatility
            win_rate_bonus: Bonus for high win rates
            risk_free_rate: Risk-free rate for Sharpe calculation
        """
        self.sharpe_weight = sharpe_weight
        self.drawdown_penalty = drawdown_penalty
        self.volatility_penalty = volatility_penalty
        self.win_rate_bonus = win_rate_bonus
        self.risk_free_rate = risk_free_rate
        
        # Rolling statistics
        self.recent_returns = []
        self.peak_equity = 0.0
        self.max_window = 100  # Last 100 steps
        
        print(f"✅ EnhancedRewardFunction initialized:")
        print(f"   - Sharpe weight: {sharpe_weight}")
        print(f"   - Drawdown penalty: {drawdown_penalty}×")
        print(f"   - Volatility penalty: {volatility_penalty}×")
    
    def calculate_reward(
        self,
        pnl: float,
        current_equity: float,
        action_taken: int,
        trade_closed: bool = False,
        trade_pnl: float = 0.0
    ) -> float:
        """
        Calculate risk-adjusted reward.
        
        Args:
            pnl: Step profit/loss
            current_equity: Current portfolio value
            action_taken: Action taken (0=hold, 1=long, 2=short, 3=close)
            trade_closed: Whether a trade was closed this step
            trade_pnl: P&L of closed trade
        
        Returns:
            Enhanced reward value
        """
        # Base reward from P&L
        base_reward = pnl / max(abs(pnl), 1.0)  # Normalized to [-1, 1]
        
        # Track returns for Sharpe calculation
        self.recent_returns.append(pnl)
        if len(self.recent_returns) > self.max_window:
            self.recent_returns.pop(0)
        
        # Calculate Sharpe ratio component (if enough data)
        sharpe_component = 0.0
        if len(self.recent_returns) >= 10:
            returns_array = np.array(self.recent_returns)
            mean_return = np.mean(returns_array)
            std_return = np.std(returns_array)
            
            if std_return > 0:
                sharpe_ratio = (mean_return - self.risk_free_rate) / std_return
                sharpe_component = self.sharpe_weight * np.tanh(sharpe_ratio)  # Bounded
        
        # Drawdown penalty
        self.peak_equity = max(self.peak_equity, current_equity)
        drawdown = (self.peak_equity - current_equity) / max(self.peak_equity, 1.0)
        drawdown_penalty = -self.drawdown_penalty * drawdown
        
        # Volatility penalty (discourage erratic performance)
        volatility_penalty = 0.0
        if len(self.recent_returns) >= 10:
            volatility = np.std(self.recent_returns)
            volatility_penalty = -self.volatility_penalty * volatility
        
        # Trade quality bonus (for closed trades)
        trade_bonus = 0.0
        if trade_closed:
            if trade_pnl > 0:
                # Reward profitable trades more
                trade_bonus = self.win_rate_bonus * min(trade_pnl / 100.0, 1.0)
            else:
                # Small penalty for losses (agent should learn to avoid)
                trade_bonus = -0.1 * abs(trade_pnl) / 100.0
        
        # Combine all components
        total_reward = (
            base_reward +
            sharpe_component +
            drawdown_penalty +
            volatility_penalty +
            trade_bonus
        )
        
        return total_reward
    
    def reset(self):
        """Reset statistics (call at episode start)"""
        self.recent_returns = []
        self.peak_equity = 0.0


def create_recurrent_policy_kwargs(
    lstm_hidden_size: int = 512,
    lstm_num_layers: int = 2,
    attention_heads: int = 8,
    sequence_length: int = 10,
    net_arch: Optional[list] = None
):
    """
    Create policy kwargs for recurrent (LSTM + Attention) architecture.
    
    Args:
        lstm_hidden_size: LSTM hidden units
        lstm_num_layers: Number of LSTM layers
        attention_heads: Number of attention heads
        sequence_length: Observation history length
        net_arch: Network architecture for policy/value heads
    
    Returns:
        Dictionary of policy kwargs
    """
    if net_arch is None:
        net_arch = [dict(pi=[1024, 512, 256], vf=[1024, 512, 256])]
    
    return {
        "features_extractor_class": RecurrentFeatureExtractor,
        "features_extractor_kwargs": {
            "features_dim": 2048,
            "lstm_hidden_size": lstm_hidden_size,
            "lstm_num_layers": lstm_num_layers,
            "attention_heads": attention_heads,
            "sequence_length": sequence_length,
            "dropout": 0.1
        },
        "net_arch": net_arch,
        "activation_fn": nn.ReLU
    }


# Export main components
__all__ = [
    'RecurrentFeatureExtractor',
    'RecurrentActorCriticPolicy',
    'MarketRegimeObserver',
    'EnhancedRewardFunction',
    'create_recurrent_policy_kwargs'
]
