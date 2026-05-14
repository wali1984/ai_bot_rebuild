"""
Advanced Risk Management System for Hybrid Trader
Implements dynamic stop-losses, scenario-based training, and portfolio protection

Features:
- Trailing stop-losses with ATR-based levels
- Dynamic take-profit targets
- Scenario-based risk training (flash crashes, liquidity events)
- Portfolio-level exposure limits
- Risk-weighted reward functions
"""

import torch
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from collections import deque
import time


@dataclass
class RiskLimits:
    """Portfolio risk limits"""
    max_portfolio_exposure: float = 0.8  # Max 80% of portfolio in trades
    max_single_position: float = 0.3  # Max 30% per position
    max_leverage: float = 20.0
    max_drawdown: float = 0.2  # 20% max drawdown before defensive mode
    max_daily_loss: float = 0.05  # 5% max daily loss
    max_correlated_exposure: float = 0.5  # Max exposure to correlated assets


@dataclass
class TradeRiskMetrics:
    """Risk metrics for a single trade"""
    entry_price: float
    current_price: float
    position_size: float
    leverage: float
    stop_loss: float
    take_profit: float
    unrealized_pnl: float
    risk_reward_ratio: float
    time_in_trade: float  # seconds


class TrailingStopLoss:
    """
    Dynamic trailing stop-loss system with ATR-based adjustment.
    
    Features:
    - Initial stop based on ATR (Average True Range)
    - Trails as price moves favorably
    - Tighter stops in high volatility
    - Wider stops in trending markets
    """
    
    def __init__(
        self,
        atr_multiplier: float = 2.5,
        trail_activation_pct: float = 0.05,  # Start trailing at 5% profit (was 2%)
        trail_step_pct: float = 0.02,  # Trail by 2% steps (was 1%)
        min_stop_pct: float = 0.02,  # Minimum 2% stop (was 0.5%)
        max_stop_pct: float = 0.2  # Maximum 20% stop (was 10%)
    ):
        """
        Args:
            atr_multiplier: Multiplier for ATR to set initial stop
            trail_activation_pct: Profit % to activate trailing
            trail_step_pct: Step size for trailing
            min_stop_pct: Minimum stop distance
            max_stop_pct: Maximum stop distance
        """
        self.atr_multiplier = atr_multiplier
        self.trail_activation_pct = trail_activation_pct
        self.trail_step_pct = trail_step_pct
        self.min_stop_pct = min_stop_pct
        self.max_stop_pct = max_stop_pct
        
        # Track stops for each position
        self.position_stops: Dict[str, float] = {}
        self.position_peaks: Dict[str, float] = {}  # Track peak profit
        
        print(f"✅ TrailingStopLoss initialized:")
        print(f"   - ATR multiplier: {atr_multiplier}")
        print(f"   - Trail activation: {trail_activation_pct*100}% profit")
        print(f"   - Trail step: {trail_step_pct*100}%")
    
    def calculate_initial_stop(
        self,
        entry_price: float,
        position_type: str,  # 'LONG' or 'SHORT'
        atr: float,
        volatility: Optional[float] = None
    ) -> float:
        """
        Calculate initial stop-loss level.
        
        Args:
            entry_price: Entry price
            position_type: 'LONG' or 'SHORT'
            atr: Average True Range
            volatility: Optional volatility adjustment (0-1)
        
        Returns:
            Stop-loss price
        """
        # Base stop distance from ATR
        stop_distance = atr * self.atr_multiplier
        
        # Adjust for volatility if provided
        if volatility is not None:
            # Higher volatility -> wider stops (up to 50% wider)
            vol_adjustment = 1.0 + (volatility * 0.5)
            stop_distance *= vol_adjustment
        
        # Convert to percentage
        stop_pct = stop_distance / entry_price
        stop_pct = max(self.min_stop_pct, min(stop_pct, self.max_stop_pct))
        
        # Calculate stop price
        if position_type == 'LONG':
            stop_price = entry_price * (1 - stop_pct)
        else:  # SHORT
            stop_price = entry_price * (1 + stop_pct)
        
        return stop_price
    
    def update_trailing_stop(
        self,
        position_id: str,
        entry_price: float,
        current_price: float,
        position_type: str,
        current_stop: float
    ) -> Tuple[float, bool]:
        """
        Update trailing stop based on price movement.
        
        Args:
            position_id: Unique position identifier
            entry_price: Entry price
            current_price: Current price
            position_type: 'LONG' or 'SHORT'
            current_stop: Current stop-loss level
        
        Returns:
            Tuple of (new_stop_price, stop_was_updated)
        """
        # Calculate current profit %
        if position_type == 'LONG':
            profit_pct = (current_price - entry_price) / entry_price
        else:  # SHORT
            profit_pct = (entry_price - current_price) / entry_price
        
        # Track peak profit
        if position_id not in self.position_peaks:
            self.position_peaks[position_id] = profit_pct
        else:
            self.position_peaks[position_id] = max(self.position_peaks[position_id], profit_pct)
        
        peak_profit = self.position_peaks[position_id]
        
        # Check if we should activate trailing
        if peak_profit < self.trail_activation_pct:
            # Not profitable enough to trail yet
            return current_stop, False
        
        # Calculate how far we should trail
        # Trail by steps as profit increases
        trail_distance_pct = self.trail_step_pct * int(peak_profit / self.trail_step_pct)
        
        # Calculate new stop level
        if position_type == 'LONG':
            new_stop = entry_price * (1 + trail_distance_pct)
            # Only move stop up, never down
            new_stop = max(new_stop, current_stop)
        else:  # SHORT
            new_stop = entry_price * (1 - trail_distance_pct)
            # Only move stop down, never up
            new_stop = min(new_stop, current_stop)
        
        updated = new_stop != current_stop
        
        if updated:
            self.position_stops[position_id] = new_stop
        
        return new_stop, updated
    
    def should_close(
        self,
        current_price: float,
        stop_price: float,
        position_type: str
    ) -> bool:
        """Check if stop-loss has been hit"""
        if position_type == 'LONG':
            return current_price <= stop_price
        else:  # SHORT
            return current_price >= stop_price
    
    def remove_position(self, position_id: str):
        """Remove position tracking"""
        self.position_stops.pop(position_id, None)
        self.position_peaks.pop(position_id, None)


class DynamicTakeProfit:
    """
    Dynamic take-profit system with partial exits.
    
    Strategy:
    - Take partial profits at multiple levels
    - Let winners run with trailing stops
    - Adjust targets based on trend strength
    """
    
    def __init__(
        self,
        initial_target_pct: float = 0.15,  # 15% initial target
        partial_exit_levels: List[float] = [0.10, 0.20, 0.40],  # 10%, 20%, 40% profit
        partial_exit_sizes: List[float] = [0.33, 0.33, 0.34],  # Take 1/3 at each level
        trend_extension_factor: float = 1.5  # Extend targets 50% in strong trends
    ):
        """
        Args:
            initial_target_pct: Initial take-profit target
            partial_exit_levels: Profit levels for partial exits
            partial_exit_sizes: How much to exit at each level (should sum to 1.0)
            trend_extension_factor: Factor to extend targets in trends
        """
        self.initial_target_pct = initial_target_pct
        self.partial_exit_levels = sorted(partial_exit_levels)
        self.partial_exit_sizes = partial_exit_sizes
        self.trend_extension_factor = trend_extension_factor
        
        # Track partial exits
        self.position_exits: Dict[str, List[float]] = {}
        
        print(f"✅ DynamicTakeProfit initialized:")
        print(f"   - Initial target: {initial_target_pct*100}%")
        print(f"   - Partial exits at: {[f'{p*100}%' for p in partial_exit_levels]}")
        print(f"   - Exit sizes: {[f'{s*100:.0f}%' for s in partial_exit_sizes]}")
    
    def calculate_targets(
        self,
        entry_price: float,
        position_type: str,
        trend_strength: float = 0.5  # 0 to 1
    ) -> List[Tuple[float, float]]:
        """
        Calculate take-profit targets.
        
        Args:
            entry_price: Entry price
            position_type: 'LONG' or 'SHORT'
            trend_strength: Trend strength (0=weak, 1=strong)
        
        Returns:
            List of (target_price, exit_size) tuples
        """
        targets = []
        
        # Adjust levels based on trend
        trend_multiplier = 1.0 + (trend_strength * (self.trend_extension_factor - 1.0))
        
        for level, size in zip(self.partial_exit_levels, self.partial_exit_sizes):
            adjusted_level = level * trend_multiplier
            
            if position_type == 'LONG':
                target_price = entry_price * (1 + adjusted_level)
            else:  # SHORT
                target_price = entry_price * (1 - adjusted_level)
            
            targets.append((target_price, size))
        
        return targets
    
    def check_targets(
        self,
        position_id: str,
        entry_price: float,
        current_price: float,
        position_type: str,
        remaining_size: float
    ) -> List[float]:
        """
        Check which targets have been hit and return exit sizes.
        
        Args:
            position_id: Position identifier
            entry_price: Entry price
            current_price: Current price
            position_type: 'LONG' or 'SHORT'
            remaining_size: Remaining position size (0-1)
        
        Returns:
            List of exit sizes to execute
        """
        # Calculate current profit
        if position_type == 'LONG':
            profit_pct = (current_price - entry_price) / entry_price
        else:
            profit_pct = (entry_price - current_price) / entry_price
        
        # Initialize tracking for this position
        if position_id not in self.position_exits:
            self.position_exits[position_id] = []
        
        executed_exits = self.position_exits[position_id]
        exits_to_execute = []
        
        # Check each level
        for level, size in zip(self.partial_exit_levels, self.partial_exit_sizes):
            if profit_pct >= level and level not in executed_exits:
                # Hit this target and haven't exited yet
                exit_size = size * remaining_size
                exits_to_execute.append(exit_size)
                executed_exits.append(level)
        
        return exits_to_execute


class ScenarioTrainer:
    """
    Train agent on rare but dangerous scenarios.
    
    Injects challenging market conditions into training:
    - Flash crashes (rapid 10-20% moves)
    - Liquidity droughts (wide spreads, slippage)
    - Volatility spikes
    - Coordinated liquidations
    
    This prepares the agent to handle extreme events.
    """
    
    def __init__(
        self,
        scenario_probability: float = 0.05,  # 5% of steps inject scenario
        crash_magnitude: Tuple[float, float] = (0.1, 0.3),  # 10-30% crash
        recovery_speed: Tuple[float, float] = (0.5, 2.0),  # 0.5-2.0 minutes
        liquidity_impact: float = 0.05  # 5% slippage in liquidity events
    ):
        """
        Args:
            scenario_probability: Probability of injecting scenario
            crash_magnitude: Range of crash magnitudes (fraction)
            recovery_speed: Range of recovery times (minutes)
            liquidity_impact: Slippage impact during liquidity events
        """
        self.scenario_probability = scenario_probability
        self.crash_magnitude_range = crash_magnitude
        self.recovery_speed_range = recovery_speed
        self.liquidity_impact = liquidity_impact
        
        # Scenario types
        self.scenarios = [
            'flash_crash',
            'flash_pump',
            'liquidity_drought',
            'volatility_spike',
            'coordinated_liquidation'
        ]
        
        print(f"✅ ScenarioTrainer initialized:")
        print(f"   - Scenario probability: {scenario_probability*100}%")
        print(f"   - Crash range: {crash_magnitude[0]*100}% to {crash_magnitude[1]*100}%")
        print(f"   - Scenarios: {len(self.scenarios)} types")
    
    def should_inject_scenario(self) -> bool:
        """Check if we should inject a scenario this step"""
        return np.random.random() < self.scenario_probability
    
    def generate_scenario(self) -> Dict:
        """
        Generate a random scenario.
        
        Returns:
            Dictionary with scenario parameters
        """
        scenario_type = np.random.choice(self.scenarios)
        
        if scenario_type == 'flash_crash':
            magnitude = np.random.uniform(*self.crash_magnitude_range)
            recovery_time = np.random.uniform(*self.recovery_speed_range)
            return {
                'type': 'flash_crash',
                'magnitude': -magnitude,  # Negative for crash
                'recovery_minutes': recovery_time,
                'slippage': self.liquidity_impact * 2  # Extra slippage
            }
        
        elif scenario_type == 'flash_pump':
            magnitude = np.random.uniform(*self.crash_magnitude_range)
            recovery_time = np.random.uniform(*self.recovery_speed_range)
            return {
                'type': 'flash_pump',
                'magnitude': magnitude,  # Positive for pump
                'recovery_minutes': recovery_time,
                'slippage': self.liquidity_impact
            }
        
        elif scenario_type == 'liquidity_drought':
            return {
                'type': 'liquidity_drought',
                'duration_minutes': np.random.uniform(5, 30),
                'slippage': self.liquidity_impact * 3,
                'spread_multiplier': 5.0  # Spreads 5× wider
            }
        
        elif scenario_type == 'volatility_spike':
            return {
                'type': 'volatility_spike',
                'volatility_multiplier': np.random.uniform(3, 10),
                'duration_minutes': np.random.uniform(10, 60)
            }
        
        elif scenario_type == 'coordinated_liquidation':
            return {
                'type': 'coordinated_liquidation',
                'cascade_magnitude': np.random.uniform(0.15, 0.4),
                'cascade_speed': np.random.uniform(1, 5),  # minutes
                'recovery_time': np.random.uniform(30, 120)
            }
        
        return {}
    
    def apply_scenario_to_price(
        self,
        current_price: float,
        scenario: Dict,
        time_in_scenario: float  # minutes
    ) -> float:
        """
        Apply scenario effects to price.
        
        Args:
            current_price: Current price
            scenario: Scenario dictionary
            time_in_scenario: Time since scenario started (minutes)
        
        Returns:
            Modified price
        """
        scenario_type = scenario.get('type')
        
        if scenario_type in ['flash_crash', 'flash_pump']:
            magnitude = scenario['magnitude']
            recovery_time = scenario['recovery_minutes']
            
            if time_in_scenario < 0.5:  # First 30 seconds - sharp move
                price_change = magnitude * (time_in_scenario / 0.5)
            elif time_in_scenario < recovery_time:  # Recovery phase
                # Partial recovery
                recovery_progress = (time_in_scenario - 0.5) / (recovery_time - 0.5)
                price_change = magnitude * (1 - recovery_progress * 0.7)  # Recover 70%
            else:
                price_change = magnitude * 0.3  # Residual 30% of move
            
            return current_price * (1 + price_change)
        
        elif scenario_type == 'coordinated_liquidation':
            cascade_mag = scenario['cascade_magnitude']
            cascade_speed = scenario['cascade_speed']
            recovery_time = scenario['recovery_time']
            
            if time_in_scenario < cascade_speed:
                # Cascade down
                progress = time_in_scenario / cascade_speed
                price_change = -cascade_mag * progress
            elif time_in_scenario < recovery_time:
                # Recovery
                recovery_progress = (time_in_scenario - cascade_speed) / (recovery_time - cascade_speed)
                price_change = -cascade_mag * (1 - recovery_progress * 0.8)
            else:
                price_change = -cascade_mag * 0.2
            
            return current_price * (1 + price_change)
        
        # For other scenarios, don't modify price directly (affects other metrics)
        return current_price


class RiskWeightedReward:
    """
    Reward function with heavy penalties for risky behavior.
    
    Rewards:
    - Early exit from losing trades (before hitting stop)
    - Defensive positioning in high uncertainty
    - Portfolio-level risk management
    
    Penalties:
    - Large drawdowns
    - Exceeding risk limits
    - Over-leveraging in volatile conditions
    """
    
    def __init__(
        self,
        early_exit_bonus: float = 0.3,
        risk_limit_penalty: float = 5.0,
        drawdown_penalty_multiplier: float = 10.0
    ):
        """
        Args:
            early_exit_bonus: Bonus for exiting losing trade early
            risk_limit_penalty: Penalty for exceeding risk limits
            drawdown_penalty_multiplier: Multiplier for drawdown penalties
        """
        self.early_exit_bonus = early_exit_bonus
        self.risk_limit_penalty = risk_limit_penalty
        self.drawdown_penalty_multiplier = drawdown_penalty_multiplier
        
        print(f"✅ RiskWeightedReward initialized:")
        print(f"   - Early exit bonus: {early_exit_bonus}")
        print(f"   - Risk limit penalty: {risk_limit_penalty}×")
        print(f"   - Drawdown penalty: {drawdown_penalty_multiplier}×")
    
    def calculate_reward(
        self,
        base_reward: float,
        trade_pnl: Optional[float] = None,
        stop_loss: Optional[float] = None,
        exit_price: Optional[float] = None,
        risk_limits: Optional[RiskLimits] = None,
        current_exposure: float = 0.0,
        current_drawdown: float = 0.0
    ) -> float:
        """
        Calculate risk-weighted reward.
        
        Args:
            base_reward: Base reward from P&L
            trade_pnl: Trade P&L if closed
            stop_loss: Stop-loss level
            exit_price: Exit price
            risk_limits: Risk limits
            current_exposure: Current portfolio exposure
            current_drawdown: Current drawdown level
        
        Returns:
            Modified reward
        """
        reward = base_reward
        
        # Early exit bonus
        if trade_pnl is not None and trade_pnl < 0 and stop_loss is not None and exit_price is not None:
            # Calculate how much of the potential loss was avoided
            potential_loss = abs(stop_loss - exit_price)
            actual_loss = abs(trade_pnl)
            
            if actual_loss < potential_loss:
                # Exited before stop - reward this
                avoidance_ratio = 1 - (actual_loss / potential_loss)
                reward += self.early_exit_bonus * avoidance_ratio
        
        # Risk limit penalties
        if risk_limits is not None:
            # Penalty for exceeding exposure limits
            if current_exposure > risk_limits.max_portfolio_exposure:
                excess = current_exposure - risk_limits.max_portfolio_exposure
                reward -= self.risk_limit_penalty * excess
        
        # Drawdown penalties (exponential - gets much worse as DD increases)
        if current_drawdown > 0:
            drawdown_penalty = -self.drawdown_penalty_multiplier * (current_drawdown ** 2)
            reward += drawdown_penalty
        
        return reward


# Export main components
__all__ = [
    'RiskLimits',
    'TradeRiskMetrics',
    'TrailingStopLoss',
    'DynamicTakeProfit',
    'ScenarioTrainer',
    'RiskWeightedReward'
]
