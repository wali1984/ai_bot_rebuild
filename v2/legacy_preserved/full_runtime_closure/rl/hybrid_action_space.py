"""
Enhanced Action Space for Hybrid Trader
Implements continuous position sizing and leverage control

Features:
- Discrete action selection (HOLD, LONG, SHORT, CLOSE, ADD, REDUCE)
- Continuous leverage factor (1× to 20×)
- Continuous position size percentage (1% to 100%)
- Confidence-based sizing
- Dynamic risk adjustment
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from typing import Dict, Tuple, Optional
from dataclasses import dataclass


@dataclass
class TradingAction:
    """
    Enhanced trading action with continuous parameters.
    
    Attributes:
        action_type: Discrete action (0=HOLD, 1=LONG, 2=SHORT, 3=CLOSE, 4=ADD, 5=REDUCE)
        leverage: Leverage factor (1.0 to 20.0)
        position_size: Position size as % of portfolio (0.01 to 1.0)
        confidence: Model confidence in this action (0.0 to 1.0)
    """
    action_type: int
    leverage: float
    position_size: float
    confidence: float
    
    def __str__(self):
        action_names = ['HOLD', 'LONG', 'SHORT', 'CLOSE', 'ADD', 'REDUCE']
        action_name = action_names[self.action_type] if 0 <= self.action_type < len(action_names) else 'UNKNOWN'
        return (f"{action_name} | Leverage: {self.leverage:.1f}× | "
                f"Size: {self.position_size*100:.1f}% | Confidence: {self.confidence*100:.1f}%")


class HybridActionDecoder:
    """
    Decode neural network outputs into trading actions.
    
    Network outputs:
    - Action logits: [batch, 6] for 6 discrete actions
    - Leverage mean/std: [batch, 1] each
    - Position size mean/std: [batch, 1] each
    
    This allows the agent to learn both what to trade (action)
    and how much to risk (leverage, size).
    """
    
    def __init__(
        self,
        min_leverage: float = 1.0,
        max_leverage: float = 20.0,
        min_position_size: float = 0.01,
        max_position_size: float = 1.0,
        confidence_sizing: bool = True
    ):
        """
        Args:
            min_leverage: Minimum leverage
            max_leverage: Maximum leverage
            min_position_size: Minimum position size (% of portfolio)
            max_position_size: Maximum position size
            confidence_sizing: Link position size to confidence
        """
        self.min_leverage = min_leverage
        self.max_leverage = max_leverage
        self.min_position_size = min_position_size
        self.max_position_size = max_position_size
        self.confidence_sizing = confidence_sizing
        
        print(f"✅ HybridActionDecoder initialized:")
        print(f"   - Leverage range: {min_leverage}× to {max_leverage}×")
        print(f"   - Position size range: {min_position_size*100}% to {max_position_size*100}%")
        print(f"   - Confidence-based sizing: {confidence_sizing}")
    
    def decode_action(
        self,
        action_logits: torch.Tensor,
        leverage_mean: torch.Tensor,
        leverage_std: torch.Tensor,
        size_mean: torch.Tensor,
        size_std: torch.Tensor,
        deterministic: bool = False,
        market_volatility: Optional[float] = None
    ) -> TradingAction:
        """
        Decode network outputs into a trading action.
        
        Args:
            action_logits: Action logits [6]
            leverage_mean: Mean leverage [1]
            leverage_std: Std deviation of leverage [1]
            size_mean: Mean position size [1]
            size_std: Std deviation of position size [1]
            deterministic: If True, use mean values; else sample
            market_volatility: Current market volatility (optional, for adjustment)
        
        Returns:
            TradingAction object
        """
        # Decode discrete action
        action_probs = F.softmax(action_logits, dim=-1)
        
        if deterministic:
            action_type = torch.argmax(action_probs).item()
        else:
            action_dist = torch.distributions.Categorical(action_probs)
            action_type = action_dist.sample().item()
        
        # Confidence from action probability
        confidence = action_probs[action_type].item()
        
        # Decode leverage (use normal distribution)
        if deterministic:
            leverage_raw = leverage_mean.item()
        else:
            leverage_dist = torch.distributions.Normal(leverage_mean, leverage_std.abs() + 1e-6)
            leverage_raw = leverage_dist.sample().item()
        
        # Decode position size
        if deterministic:
            size_raw = size_mean.item()
        else:
            size_dist = torch.distributions.Normal(size_mean, size_std.abs() + 1e-6)
            size_raw = size_dist.sample().item()
        
        # Apply sigmoid to get 0-1 range, then scale
        leverage = self.min_leverage + torch.sigmoid(torch.tensor(leverage_raw)).item() * (self.max_leverage - self.min_leverage)
        position_size = self.min_position_size + torch.sigmoid(torch.tensor(size_raw)).item() * (self.max_position_size - self.min_position_size)
        
        # Adjust leverage based on market volatility (if provided)
        if market_volatility is not None:
            # Higher volatility -> Lower leverage (risk management)
            volatility_factor = 1.0 - min(market_volatility, 1.0) * 0.5  # 50% reduction max
            leverage *= volatility_factor
            leverage = max(self.min_leverage, min(leverage, self.max_leverage))
        
        # Confidence-based sizing: higher confidence -> larger positions
        if self.confidence_sizing:
            # Scale position size by confidence (but keep minimum)
            confidence_factor = 0.3 + 0.7 * confidence  # Range: 0.3 to 1.0
            position_size *= confidence_factor
            position_size = max(self.min_position_size, min(position_size, self.max_position_size))
        
        return TradingAction(
            action_type=action_type,
            leverage=leverage,
            position_size=position_size,
            confidence=confidence
        )


class HybridActionHead(nn.Module):
    """
    Multi-head output network for hybrid action space.
    
    Takes feature representation and outputs:
    - Action logits (discrete)
    - Leverage parameters (continuous)
    - Position size parameters (continuous)
    
    This is used in the policy network.
    """
    
    def __init__(self, feature_dim: int = 256, hidden_dim: int = 128):
        """
        Args:
            feature_dim: Input feature dimension
            hidden_dim: Hidden layer dimension
        """
        super().__init__()
        
        # Shared layer
        self.shared = nn.Sequential(
            nn.Linear(feature_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1)
        )
        
        # Action head (discrete: 6 actions)
        self.action_head = nn.Linear(hidden_dim, 6)
        
        # Leverage head (continuous)
        self.leverage_mean_head = nn.Linear(hidden_dim, 1)
        self.leverage_std_head = nn.Sequential(
            nn.Linear(hidden_dim, 1),
            nn.Softplus()  # Ensure positive std
        )
        
        # Position size head (continuous)
        self.size_mean_head = nn.Linear(hidden_dim, 1)
        self.size_std_head = nn.Sequential(
            nn.Linear(hidden_dim, 1),
            nn.Softplus()  # Ensure positive std
        )
        
        print(f"✅ HybridActionHead initialized:")
        print(f"   - Input: {feature_dim} features")
        print(f"   - Outputs: action (6 classes), leverage (continuous), size (continuous)")
    
    def forward(self, features: torch.Tensor) -> Dict[str, torch.Tensor]:
        """
        Forward pass.
        
        Args:
            features: Feature tensor [batch, feature_dim]
        
        Returns:
            Dictionary with outputs:
            - action_logits: [batch, 6]
            - leverage_mean: [batch, 1]
            - leverage_std: [batch, 1]
            - size_mean: [batch, 1]
            - size_std: [batch, 1]
        """
        shared_features = self.shared(features)
        
        return {
            'action_logits': self.action_head(shared_features),
            'leverage_mean': self.leverage_mean_head(shared_features),
            'leverage_std': self.leverage_std_head(shared_features),
            'size_mean': self.size_mean_head(shared_features),
            'size_std': self.size_std_head(shared_features)
        }


class ConfidenceBasedSizer:
    """
    Position sizing algorithm based on model confidence and Kelly Criterion.
    
    Principles:
    - High confidence signals get larger positions
    - Low confidence signals get smaller positions
    - Never exceed safe leverage limits
    - Adapt to recent win rate
    """
    
    def __init__(
        self,
        base_size: float = 0.1,
        max_size: float = 0.5,
        kelly_fraction: float = 0.25,
        use_kelly: bool = True
    ):
        """
        Args:
            base_size: Base position size (% of portfolio)
            max_size: Maximum position size
            kelly_fraction: Fraction of Kelly criterion to use (0.25 = quarter Kelly)
            use_kelly: Whether to use Kelly criterion
        """
        self.base_size = base_size
        self.max_size = max_size
        self.kelly_fraction = kelly_fraction
        self.use_kelly = use_kelly
        
        # Track recent trades for Kelly calculation
        self.recent_trades = []
        self.max_history = 100
        
        print(f"✅ ConfidenceBasedSizer initialized:")
        print(f"   - Base size: {base_size*100}%")
        print(f"   - Max size: {max_size*100}%")
        print(f"   - Kelly fraction: {kelly_fraction}")
    
    def calculate_position_size(
        self,
        confidence: float,
        current_balance: float,
        recent_win_rate: Optional[float] = None,
        recent_avg_win: Optional[float] = None,
        recent_avg_loss: Optional[float] = None
    ) -> float:
        """
        Calculate optimal position size.
        
        Args:
            confidence: Model confidence (0-1)
            current_balance: Current portfolio balance
            recent_win_rate: Recent win rate (optional, for Kelly)
            recent_avg_win: Recent average win size (optional)
            recent_avg_loss: Recent average loss size (optional)
        
        Returns:
            Position size in currency units
        """
        # Start with base size scaled by confidence
        size_fraction = self.base_size * (0.5 + 0.5 * confidence)  # Range: 0.5×base to 1.0×base
        
        # Apply Kelly criterion if enabled and we have data
        if self.use_kelly and recent_win_rate is not None:
            if recent_win_rate > 0.5 and recent_avg_win and recent_avg_loss and recent_avg_loss > 0:
                # Kelly formula: f = (p*b - q) / b
                # where p = win probability, q = loss probability, b = win/loss ratio
                p = recent_win_rate
                q = 1 - p
                b = recent_avg_win / recent_avg_loss
                
                kelly_f = (p * b - q) / b
                kelly_f = max(0, kelly_f)  # Never negative
                
                # Use fraction of Kelly (full Kelly can be too aggressive)
                kelly_size = kelly_f * self.kelly_fraction
                
                # Blend with confidence-based size
                size_fraction = 0.5 * size_fraction + 0.5 * kelly_size
        
        # Cap at maximum
        size_fraction = min(size_fraction, self.max_size)
        
        # Convert to currency amount
        position_size = size_fraction * current_balance
        
        return position_size
    
    def record_trade(self, pnl: float):
        """Record trade outcome for Kelly calculation"""
        self.recent_trades.append(pnl)
        if len(self.recent_trades) > self.max_history:
            self.recent_trades.pop(0)
    
    def get_statistics(self) -> Dict[str, float]:
        """Get recent trading statistics"""
        if not self.recent_trades:
            return {
                'win_rate': 0.5,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 1.0
            }
        
        trades = np.array(self.recent_trades)
        wins = trades[trades > 0]
        losses = trades[trades < 0]
        
        win_rate = len(wins) / len(trades) if len(trades) > 0 else 0.5
        avg_win = np.mean(wins) if len(wins) > 0 else 0.0
        avg_loss = abs(np.mean(losses)) if len(losses) > 0 else 0.0
        profit_factor = (avg_win * len(wins)) / (avg_loss * len(losses)) if len(losses) > 0 else 1.0
        
        return {
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor
        }


class DynamicLeverageScheduler:
    """
    Adaptive leverage scheduler based on market conditions.
    
    Adjusts leverage based on:
    - Market volatility (higher vol -> lower leverage)
    - Drawdown level (in drawdown -> lower leverage)
    - Win streak (winning -> can increase slightly)
    - Time of day (certain hours more volatile)
    """
    
    def __init__(
        self,
        base_leverage: float = 10.0,
        min_leverage: float = 1.0,
        max_leverage: float = 20.0,
        volatility_adjustment: bool = True,
        drawdown_adjustment: bool = True
    ):
        """
        Args:
            base_leverage: Base leverage level
            min_leverage: Minimum allowed leverage
            max_leverage: Maximum allowed leverage
            volatility_adjustment: Adjust for volatility
            drawdown_adjustment: Reduce leverage in drawdown
        """
        self.base_leverage = base_leverage
        self.min_leverage = min_leverage
        self.max_leverage = max_leverage
        self.volatility_adjustment = volatility_adjustment
        self.drawdown_adjustment = drawdown_adjustment
        
        print(f"✅ DynamicLeverageScheduler initialized:")
        print(f"   - Base leverage: {base_leverage}×")
        print(f"   - Range: {min_leverage}× to {max_leverage}×")
        print(f"   - Volatility adjustment: {volatility_adjustment}")
    
    def calculate_leverage(
        self,
        base_leverage: float,
        market_volatility: float = 0.5,
        current_drawdown: float = 0.0,
        recent_win_rate: float = 0.5,
        confidence: float = 0.7
    ) -> float:
        """
        Calculate adaptive leverage.
        
        Args:
            base_leverage: Requested base leverage
            market_volatility: Market volatility (0-1, normalized)
            current_drawdown: Current drawdown as fraction (0-1)
            recent_win_rate: Recent win rate (0-1)
            confidence: Model confidence (0-1)
        
        Returns:
            Adjusted leverage
        """
        leverage = base_leverage
        
        # Volatility adjustment: higher volatility -> lower leverage
        if self.volatility_adjustment:
            # Reduce by up to 70% in high volatility
            vol_factor = 1.0 - (0.7 * market_volatility)
            leverage *= vol_factor
        
        # Drawdown adjustment: in drawdown -> much lower leverage
        if self.drawdown_adjustment and current_drawdown > 0:
            # Aggressive reduction in drawdown
            dd_factor = 1.0 - (current_drawdown * 2.0)  # 10% DD -> 80% leverage
            dd_factor = max(0.3, dd_factor)  # Minimum 30% of base
            leverage *= dd_factor
        
        # Win rate adjustment: if winning consistently, allow slightly higher
        if recent_win_rate > 0.6:
            win_bonus = 1.0 + (recent_win_rate - 0.6) * 0.5  # Up to +20% leverage
            leverage *= win_bonus
        elif recent_win_rate < 0.4:
            # If losing, reduce leverage
            loss_penalty = 0.7 + (recent_win_rate * 0.75)  # Down to 70% leverage
            leverage *= loss_penalty
        
        # Confidence adjustment: low confidence -> lower leverage
        if confidence < 0.7:
            conf_factor = 0.5 + (confidence / 0.7) * 0.5  # 50% to 100%
            leverage *= conf_factor
        
        # Clamp to limits
        leverage = max(self.min_leverage, min(leverage, self.max_leverage))
        
        return leverage


# Export main components
__all__ = [
    'TradingAction',
    'HybridActionDecoder',
    'HybridActionHead',
    'ConfidenceBasedSizer',
    'DynamicLeverageScheduler'
]
