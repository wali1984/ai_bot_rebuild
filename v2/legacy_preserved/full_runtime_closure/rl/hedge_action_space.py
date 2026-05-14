"""
7-Action Hedge Recovery System for WMA AI Bot
Implements hedge-mode trading with 7 distinct actions

Actions:
1. OPEN_LONG (0)
2. OPEN_SHORT (1)  
3. INCREASE_LONG (2)
4. INCREASE_SHORT (3)
5. DECREASE_LONG (4)
6. DECREASE_SHORT (5)
7. CLOSE_ALL (6)

Features:
- Categorical(7) action space (no MultiDiscrete)
- Hedge-mode: simultaneous long+short per symbol
- Portfolio-aware sizing and leverage
- Confidence-based action selection
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
from typing import Dict, Tuple, Optional, NamedTuple
from enum import IntEnum
from dataclasses import dataclass


class HedgeAction(IntEnum):
    """7-action hedge space for recovery plan"""
    OPEN_LONG = 0
    OPEN_SHORT = 1
    INCREASE_LONG = 2
    INCREASE_SHORT = 3
    DECREASE_LONG = 4
    DECREASE_SHORT = 5
    CLOSE_ALL = 6


@dataclass
class HedgeActionResult:
    """
    Result of decoded hedge action with continuous parameters.
    
    Attributes:
        action_enum: One of HedgeAction enum values (0-6)
        size_suggest: Suggested position size as % of portfolio (0.01 to 0.10)
        lev_suggest: Suggested leverage factor (1.0 to 15.0, symbol-dependent)
        confidence: Model confidence in this action (0.0 to 1.0)
        symbol: Target symbol for this action
        hedge_allowed: Whether hedge mode is active for this symbol
    """
    action_enum: HedgeAction
    size_suggest: float
    lev_suggest: float
    confidence: float
    symbol: str = ""
    hedge_allowed: bool = True
    
    def __str__(self):
        return (f"{self.action_enum.name} | Symbol: {self.symbol} | "
                f"Size: {self.size_suggest*100:.1f}% | Leverage: {self.lev_suggest:.1f}× | "
                f"Confidence: {self.confidence*100:.1f}% | Hedge: {self.hedge_allowed}")


class HedgeActionDecoder:
    """
    Decode 7-action Categorical output + continuous parameters.
    
    Network outputs:
    - Action logits: [batch, 7] for 7 categorical actions
    - Size output: [batch, 1] bounded continuous 
    - Leverage output: [batch, 1] bounded continuous
    
    No post-processing - direct action from policy.
    """
    
    def __init__(
        self,
        # NOTE: leverage caps are now derived from config.SYMBOL_LEVERAGE_CONFIG (tiered).
        # The legacy class-bucket caps (btc_eth/majors/others) were causing leverage drift vs operator config.
        min_position_size: float = 0.01,  # 1% default minimum (allow smaller sizing)
        max_position_size_base: float = 0.15,  # 15% base cap (was 8%)
        max_position_size_boosted: float = 0.25,  # 25% boosted cap (was 10%)
    ):
        """
        Args:
            min_leverage_btc_eth: Min leverage for BTC/ETH
            max_leverage_btc_eth: Max leverage for BTC/ETH  
            min_leverage_majors: Min leverage for major coins
            max_leverage_majors: Max leverage for major coins
            min_leverage_others: Min leverage for other coins
            max_leverage_others: Max leverage for other coins
            min_position_size: Min position size (% portfolio)
            max_position_size_base: Max position size (base state)
            max_position_size_boosted: Max position size (boosted state)
        """
        # Load per-symbol tier ranges from config (single source of truth).
        # If a symbol is not present, fall back to conservative 10-25x (tier-4 style).
        try:
            from config import SYMBOL_LEVERAGE_CONFIG
            self._symbol_leverage_cfg = dict(SYMBOL_LEVERAGE_CONFIG or {})
        except Exception:
            self._symbol_leverage_cfg = {}
        self._default_min_lev = float(self._symbol_leverage_cfg.get("default", {}).get("min_leverage", 10.0) or 10.0) if isinstance(self._symbol_leverage_cfg.get("default", {}), dict) else 10.0
        self._default_max_lev = float(self._symbol_leverage_cfg.get("default", {}).get("max_leverage", 25.0) or 25.0) if isinstance(self._symbol_leverage_cfg.get("default", {}), dict) else 25.0
        self.min_position_size = min_position_size
        self.max_position_size_base = max_position_size_base
        self.max_position_size_boosted = max_position_size_boosted
        
        print(f"✅ HedgeActionDecoder initialized:")
        try:
            # Print a short tier summary for operator confidence
            btc = (self._symbol_leverage_cfg.get("BTCUSDT") or {})
            eth = (self._symbol_leverage_cfg.get("ETHUSDT") or {})
            sol = (self._symbol_leverage_cfg.get("SOLUSDT") or {})
            print(f"   - BTCUSDT leverage: {btc.get('min_leverage','?')}× to {btc.get('max_leverage','?')}×")
            print(f"   - ETHUSDT leverage: {eth.get('min_leverage','?')}× to {eth.get('max_leverage','?')}×")
            print(f"   - SOLUSDT leverage: {sol.get('min_leverage','?')}× to {sol.get('max_leverage','?')}×")
        except Exception:
            pass
        print(f"   - Default leverage: {self._default_min_lev}× to {self._default_max_lev}× (unknown symbols)")
        print(f"   - Position size: {min_position_size*100}% to {max_position_size_base*100}% (boosted: {max_position_size_boosted*100}%)")

    def _get_symbol_leverage_range(self, symbol: str) -> Tuple[float, float]:
        """Return (min,max) leverage for symbol from config tiers; fallback to default."""
        try:
            s = (symbol or "").upper()
            cfg = self._symbol_leverage_cfg.get(s, self._symbol_leverage_cfg.get("default", {})) or {}
            if not isinstance(cfg, dict):
                cfg = {}
            mn = float(cfg.get("min_leverage", self._default_min_lev) or self._default_min_lev)
            mx = float(cfg.get("max_leverage", self._default_max_lev) or self._default_max_lev)
            mn = max(1.0, mn)
            mx = max(mn, mx)
            return mn, mx
        except Exception:
            return max(1.0, float(self._default_min_lev)), max(float(self._default_min_lev), float(self._default_max_lev))
    
    def _decode_action_7way(
        self,
        action_logits: torch.Tensor,
        size_output: torch.Tensor,
        leverage_output: torch.Tensor,
        symbol: str = "BTC",
        is_boosted: bool = False,
        deterministic: bool = False
    ) -> HedgeActionResult:
        """
        Core 7-way action decoder - produces actions directly from policy.
        
        Args:
            action_logits: Categorical logits [7] for 7 hedge actions
            size_output: Size output [1] (will be bounded)
            leverage_output: Leverage output [1] (will be bounded)  
            symbol: Target symbol for leverage caps
            is_boosted: Whether in boosted state (higher size limits)
            deterministic: Use argmax vs sampling
            
        Returns:
            HedgeActionResult with decoded action + parameters
        """
        # 1. Decode categorical action (0-6)
        action_probs = F.softmax(action_logits, dim=-1)
        
        if deterministic:
            action_idx = torch.argmax(action_probs).item()
        else:
            action_dist = torch.distributions.Categorical(action_probs)
            action_idx = action_dist.sample().item()
        
        action_enum = HedgeAction(action_idx)
        confidence = action_probs[action_idx].item()
        
        # 2. Decode position size (bounded to risk limits)
        # Apply sigmoid + scaling to get proper range
        size_sigmoid = torch.sigmoid(size_output).item()
        max_size = self.max_position_size_boosted if is_boosted else self.max_position_size_base
        size_suggest = self.min_position_size + size_sigmoid * (max_size - self.min_position_size)
        
        # 3. Decode leverage (symbol-tier dependent; config-driven)
        min_lev, max_lev = self._get_symbol_leverage_range(symbol)
        
        leverage_sigmoid = torch.sigmoid(leverage_output).item()
        lev_suggest = min_lev + leverage_sigmoid * (max_lev - min_lev)
        
        return HedgeActionResult(
            action_enum=action_enum,
            size_suggest=size_suggest,
            lev_suggest=lev_suggest,
            confidence=confidence,
            symbol=symbol,
            hedge_allowed=True  # Always allow hedge in recovery mode
        )


class HedgeActionHead(nn.Module):
    """
    7-action categorical head + 2 continuous heads for hedge recovery.
    
    Outputs:
    - action_logits: [batch, 7] categorical logits
    - size_output: [batch, 1] continuous position size 
    - leverage_output: [batch, 1] continuous leverage
    
    No MultiDiscrete - pure categorical + bounded continuous.
    """
    
    def __init__(self, feature_dim: int = 2048, hidden_dim: int = 512):
        """
        Args:
            feature_dim: Input feature dimension from backbone
            hidden_dim: Hidden layer dimension
        """
        super().__init__()
        
        # Shared feature processing
        self.shared = nn.Sequential(
            nn.Linear(feature_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Dropout(0.1)
        )
        
        # 7-action categorical head (replaces MultiDiscrete)
        self.action_head = nn.Linear(hidden_dim // 2, 7)
        
        # Continuous size head (bounded by sigmoid in decoder)
        self.size_head = nn.Linear(hidden_dim // 2, 1)
        
        # Continuous leverage head (bounded by sigmoid in decoder)  
        self.leverage_head = nn.Linear(hidden_dim // 2, 1)
        
        print(f"✅ HedgeActionHead initialized: {feature_dim} -> {hidden_dim} -> 7 actions + 2 continuous")
    
    def forward(self, features: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Forward pass through all heads.
        
        Args:
            features: Input features [batch, feature_dim]
            
        Returns:
            action_logits: [batch, 7] categorical logits
            size_output: [batch, 1] continuous size output
            leverage_output: [batch, 1] continuous leverage output
        """
        # Shared processing
        shared_features = self.shared(features)
        
        # Three separate heads
        action_logits = self.action_head(shared_features)
        size_output = self.size_head(shared_features)
        leverage_output = self.leverage_head(shared_features)
        
        return action_logits, size_output, leverage_output


class HedgeCalibrationHead(nn.Module):
    """
    Separate MLP head for confidence calibration.
    
    Maps logits + portfolio features -> calibrated confidence (0-1).
    Trained on historical realized outcomes for proper calibration.
    """
    
    def __init__(
        self, 
        logits_dim: int = 7,
        portfolio_features_dim: int = 20,  # Portfolio state features
        hidden_dim: int = 128
    ):
        """
        Args:
            logits_dim: Dimension of action logits (7)
            portfolio_features_dim: Number of portfolio state features
            hidden_dim: Hidden layer size
        """
        super().__init__()
        
        # Action confidence processor - responds to logit distribution
        self.action_processor = nn.Sequential(
            nn.Linear(logits_dim, 32),
            nn.ReLU(),
            nn.Linear(32, 16)
        )
        
        # Portfolio risk processor - responds to portfolio state
        self.portfolio_processor = nn.Sequential(
            nn.Linear(portfolio_features_dim, 32),
            nn.ReLU(), 
            nn.Linear(32, 16)
        )
        
        # Combined calibration network
        self.calibration_net = nn.Sequential(
            nn.Linear(32, 64),  # 16 + 16 = 32
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
            nn.Sigmoid()  # Output confidence in [0,1]
        )
        
        print(f"✅ HedgeCalibrationHead initialized: action({logits_dim}->16) + portfolio({portfolio_features_dim}->16) -> calibration(32->1)")
    
    def forward(
        self, 
        action_logits: torch.Tensor, 
        portfolio_features: torch.Tensor
    ) -> torch.Tensor:
        """
        Compute calibrated confidence.
        
        Args:
            action_logits: [batch, 7] raw action logits
            portfolio_features: [batch, portfolio_features_dim] portfolio state
            
        Returns:
            calibrated_confidence: [batch, 1] confidence in [0,1]
        """
        # Process action logits - extract confidence signal
        action_features = self.action_processor(action_logits)
        
        # Process portfolio features - extract risk signal  
        portfolio_features_processed = self.portfolio_processor(portfolio_features)
        
        # Combine and calibrate
        combined_features = torch.cat([action_features, portfolio_features_processed], dim=-1)
        calibrated_confidence = self.calibration_net(combined_features)
        
        return calibrated_confidence


# Action name mappings for Redis payload compatibility
HEDGE_ACTION_NAMES = {
    HedgeAction.OPEN_LONG: "OPEN_LONG",
    HedgeAction.OPEN_SHORT: "OPEN_SHORT", 
    HedgeAction.INCREASE_LONG: "INCREASE_LONG",
    HedgeAction.INCREASE_SHORT: "INCREASE_SHORT",
    HedgeAction.DECREASE_LONG: "DECREASE_LONG",
    HedgeAction.DECREASE_SHORT: "DECREASE_SHORT",
    HedgeAction.CLOSE_ALL: "CLOSE_ALL"
}


def hedge_action_to_name(action: HedgeAction) -> str:
    """Convert HedgeAction enum to string name for Redis payload"""
    return HEDGE_ACTION_NAMES.get(action, "UNKNOWN")


def name_to_hedge_action(name: str) -> HedgeAction:
    """Convert string name to HedgeAction enum"""
    for action, action_name in HEDGE_ACTION_NAMES.items():
        if action_name == name.upper():
            return action
    raise ValueError(f"Unknown hedge action name: {name}")