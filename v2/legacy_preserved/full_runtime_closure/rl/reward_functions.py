"""
Enhanced Reward Functions for Reinforcement Learning
Multi-objective reward calculation with realistic trading simulation
"""
import numpy as np
import logging
from typing import Dict, Optional, Tuple
from collections import deque

logger = logging.getLogger(__name__)


class AdvancedRewardCalculator:
    """
    Multi-objective reward function for trading RL.
    Balances profit, risk, costs, and trade duration.
    """
    
    def __init__(
        self,
        profit_weight: float = 1.0,
        risk_weight: float = 0.5,
        cost_weight: float = 0.3,
        duration_weight: float = 0.1,
        sharpe_weight: float = 0.3,
        use_sharpe_reward: bool = True
    ):
        """
        Initialize reward calculator.
        
        Args:
            profit_weight: Weight for profit component
            risk_weight: Weight for risk penalty
            cost_weight: Weight for trading cost penalty
            duration_weight: Weight for trade duration penalty
            sharpe_weight: Weight for Sharpe ratio component
            use_sharpe_reward: Include Sharpe-based reward
        """
        self.profit_weight = profit_weight
        self.risk_weight = risk_weight
        self.cost_weight = cost_weight
        self.duration_weight = duration_weight
        self.sharpe_weight = sharpe_weight
        self.use_sharpe_reward = use_sharpe_reward
        
        # Performance tracking
        self.returns_history = deque(maxlen=252)  # 1 year
        self.drawdown_history = deque(maxlen=100)
        
        logger.info("AdvancedRewardCalculator initialized")
    
    def calculate_reward(
        self,
        pnl: float,
        position_size: float,
        entry_price: float,
        current_price: float,
        trading_costs: float,
        duration_hours: float,
        portfolio_value: float,
        max_drawdown: float = 0.0,
        volatility: float = 0.02
    ) -> Dict[str, float]:
        """
        Calculate multi-objective reward.
        
        Args:
            pnl: Profit/loss from trade
            position_size: Position size (in base currency)
            entry_price: Entry price
            current_price: Current price
            trading_costs: Total trading costs (fees + slippage)
            duration_hours: Trade duration in hours
            portfolio_value: Current portfolio value
            max_drawdown: Current maximum drawdown
            volatility: Recent volatility estimate
            
        Returns:
            Dictionary with reward components and total reward
        """
        # 1. Profit component (normalized by portfolio value)
        profit_return = pnl / portfolio_value if portfolio_value > 0 else 0
        profit_reward = profit_return * self.profit_weight
        
        # 2. Risk penalty (drawdown and volatility)
        risk_penalty = self._calculate_risk_penalty(
            max_drawdown,
            volatility,
            position_size,
            portfolio_value
        )
        
        # 3. Cost penalty (trading costs hurt reward)
        cost_return = trading_costs / portfolio_value if portfolio_value > 0 else 0
        cost_penalty = cost_return * self.cost_weight
        
        # 4. Duration penalty (encourage efficient trades)
        duration_penalty = self._calculate_duration_penalty(
            duration_hours,
            pnl,
            position_size
        )
        
        # 5. Sharpe-based reward (reward consistency)
        sharpe_reward = 0
        if self.use_sharpe_reward:
            sharpe_reward = self._calculate_sharpe_reward(profit_return)
        
        # Total reward
        total_reward = (
            profit_reward
            - risk_penalty
            - cost_penalty
            - duration_penalty
            + sharpe_reward
        )
        
        # Record for Sharpe calculation
        self.returns_history.append(profit_return)
        self.drawdown_history.append(max_drawdown)
        
        return {
            'profit_reward': float(profit_reward),
            'risk_penalty': float(risk_penalty),
            'cost_penalty': float(cost_penalty),
            'duration_penalty': float(duration_penalty),
            'sharpe_reward': float(sharpe_reward),
            'total_reward': float(total_reward)
        }
    
    def _calculate_risk_penalty(
        self,
        max_drawdown: float,
        volatility: float,
        position_size: float,
        portfolio_value: float
    ) -> float:
        """
        Calculate risk penalty from drawdown and volatility.
        
        Args:
            max_drawdown: Maximum drawdown (negative value)
            volatility: Recent volatility
            position_size: Current position size
            portfolio_value: Portfolio value
            
        Returns:
            Risk penalty (positive value to subtract from reward)
        """
        # Drawdown penalty (exponential penalty for large drawdowns)
        dd_penalty = 0
        if max_drawdown < 0:
            # Penalize drawdowns > 5% heavily
            if abs(max_drawdown) > 0.05:
                dd_penalty = np.exp(abs(max_drawdown) * 10) - 1
            else:
                dd_penalty = abs(max_drawdown) * 2
        
        # Volatility penalty (penalize high volatility)
        vol_penalty = max(0, (volatility - 0.02) / 0.02)  # Penalty if vol > 2%
        
        # Position size risk (penalize oversized positions)
        position_ratio = position_size / portfolio_value if portfolio_value > 0 else 0
        size_penalty = max(0, (position_ratio - 0.3) * 2)  # Penalty if > 30% of portfolio
        
        total_penalty = (
            dd_penalty * 0.5 +
            vol_penalty * 0.3 +
            size_penalty * 0.2
        ) * self.risk_weight
        
        return total_penalty
    
    def _calculate_duration_penalty(
        self,
        duration_hours: float,
        pnl: float,
        position_size: float
    ) -> float:
        """
        Calculate penalty for trade duration.
        
        Args:
            duration_hours: Trade duration in hours
            pnl: Profit/loss
            position_size: Position size
            
        Returns:
            Duration penalty
        """
        # No penalty for winning trades
        if pnl > 0:
            return 0
        
        # Penalize holding losing positions for too long
        # Penalty increases exponentially after 24 hours
        if duration_hours > 24:
            excess_hours = duration_hours - 24
            penalty = (excess_hours / 24) ** 1.5 * 0.1  # Escalating penalty
        else:
            penalty = 0
        
        return penalty * self.duration_weight
    
    def _calculate_sharpe_reward(self, current_return: float) -> float:
        """
        Calculate reward component based on Sharpe ratio.
        
        Args:
            current_return: Current return
            
        Returns:
            Sharpe-based reward
        """
        if len(self.returns_history) < 30:
            return 0  # Need sufficient history
        
        returns = np.array(self.returns_history)
        
        # Calculate rolling Sharpe ratio
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        
        if std_return == 0:
            return 0
        
        sharpe = mean_return / std_return * np.sqrt(252)  # Annualized
        
        # Reward high Sharpe ratios
        # Sharpe > 1.5 is good, > 2.0 is excellent
        if sharpe > 1.5:
            sharpe_reward = (sharpe - 1.5) * 0.1
        elif sharpe > 1.0:
            sharpe_reward = (sharpe - 1.0) * 0.05
        else:
            sharpe_reward = 0
        
        return sharpe_reward * self.sharpe_weight
    
    def get_performance_metrics(self) -> Dict[str, float]:
        """
        Get current performance metrics.
        
        Returns:
            Dictionary of performance metrics
        """
        if len(self.returns_history) < 2:
            return {
                'sharpe_ratio': 0,
                'mean_return': 0,
                'volatility': 0,
                'max_drawdown': 0
            }
        
        returns = np.array(self.returns_history)
        
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        sharpe = (mean_return / std_return * np.sqrt(252)) if std_return > 0 else 0
        max_dd = min(self.drawdown_history) if self.drawdown_history else 0
        
        return {
            'sharpe_ratio': float(sharpe),
            'mean_return': float(mean_return),
            'volatility': float(std_return),
            'max_drawdown': float(max_dd),
            'sample_count': len(returns)
        }


class RealisticTradingSimulator:
    """
    Realistic trading environment simulator with slippage, fees, and latency.
    """
    
    def __init__(
        self,
        maker_fee: float = 0.0002,  # 0.02%
        taker_fee: float = 0.0004,  # 0.04%
        slippage_bps: float = 5.0,  # 5 basis points
        latency_ms: float = 100.0,  # 100ms average latency
        use_realistic_fills: bool = True
    ):
        """
        Initialize realistic trading simulator.
        
        Args:
            maker_fee: Maker fee rate
            taker_fee: Taker fee rate
            slippage_bps: Slippage in basis points
            latency_ms: Average latency in milliseconds
            use_realistic_fills: Use realistic fill simulation
        """
        self.maker_fee = maker_fee
        self.taker_fee = taker_fee
        self.slippage_bps = slippage_bps
        self.latency_ms = latency_ms
        self.use_realistic_fills = use_realistic_fills
        
        logger.info("RealisticTradingSimulator initialized")
    
    def simulate_order_execution(
        self,
        action: str,  # 'buy' or 'sell'
        size: float,
        current_price: float,
        volatility: float,
        order_type: str = 'market',  # 'market' or 'limit'
        urgency: float = 1.0  # 0-1, higher = more aggressive
    ) -> Tuple[float, float, Dict[str, float]]:
        """
        Simulate realistic order execution.
        
        Args:
            action: 'buy' or 'sell'
            size: Order size
            current_price: Current market price
            volatility: Current volatility estimate
            order_type: 'market' or 'limit'
            urgency: Execution urgency (affects slippage)
            
        Returns:
            (execution_price, total_cost, details)
        """
        # 1. Calculate slippage
        slippage = self._calculate_slippage(
            size,
            current_price,
            volatility,
            action,
            urgency
        )
        
        # 2. Apply latency impact
        latency_drift = self._calculate_latency_drift(
            current_price,
            volatility,
            self.latency_ms
        )
        
        # 3. Calculate execution price
        if action == 'buy':
            execution_price = current_price + slippage + latency_drift
        else:  # sell
            execution_price = current_price - slippage - latency_drift
        
        # 4. Calculate fees
        is_maker = (order_type == 'limit')
        fee_rate = self.maker_fee if is_maker else self.taker_fee
        fee = size * execution_price * fee_rate
        
        # 5. Total cost
        total_cost = fee + (slippage * size)
        
        details = {
            'slippage': float(slippage),
            'slippage_bps': float(slippage / current_price * 10000),
            'latency_drift': float(latency_drift),
            'fee': float(fee),
            'fee_rate': float(fee_rate),
            'execution_price': float(execution_price),
            'total_cost': float(total_cost),
            'is_maker': is_maker
        }
        
        return execution_price, total_cost, details
    
    def _calculate_slippage(
        self,
        size: float,
        price: float,
        volatility: float,
        action: str,
        urgency: float
    ) -> float:
        """
        Calculate realistic slippage based on market conditions.
        
        Args:
            size: Order size
            price: Current price
            volatility: Market volatility
            action: 'buy' or 'sell'
            urgency: Execution urgency
            
        Returns:
            Slippage amount
        """
        # Base slippage from spread
        base_slippage = price * (self.slippage_bps / 10000)
        
        # Size impact (larger orders = more slippage)
        # Assume 1% price impact for $100k order
        order_value = size * price
        size_impact = (order_value / 100000) * 0.01 * price
        
        # Volatility impact (higher vol = wider spreads)
        vol_multiplier = 1 + (volatility / 0.02)  # 2% vol = 1x, 4% = 2x
        
        # Urgency impact (aggressive = more slippage)
        urgency_multiplier = 0.5 + (urgency * 0.5)  # 0.5x to 1.0x
        
        total_slippage = (
            base_slippage +
            size_impact
        ) * vol_multiplier * urgency_multiplier
        
        return total_slippage
    
    def _calculate_latency_drift(
        self,
        price: float,
        volatility: float,
        latency_ms: float
    ) -> float:
        """
        Calculate price drift during order latency.
        
        Args:
            price: Current price
            volatility: Volatility
            latency_ms: Latency in milliseconds
            
        Returns:
            Price drift amount
        """
        # Convert latency to fraction of day
        latency_days = latency_ms / (1000 * 60 * 60 * 24)
        
        # Expected drift based on volatility
        # drift = volatility * sqrt(time)
        drift_std = volatility * np.sqrt(latency_days)
        
        # Random drift (can be positive or negative)
        drift = np.random.normal(0, drift_std) * price
        
        return abs(drift)  # Always costs money
    
    def simulate_partial_fill(
        self,
        requested_size: float,
        available_liquidity: float,
        volatility: float
    ) -> Tuple[float, bool]:
        """
        Simulate partial fill scenario.
        
        Args:
            requested_size: Requested order size
            available_liquidity: Available liquidity
            volatility: Market volatility
            
        Returns:
            (filled_size, is_complete)
        """
        if not self.use_realistic_fills:
            return requested_size, True
        
        # High volatility = lower fill rate
        fill_probability = 1.0 - min(volatility / 0.1, 0.5)  # Max 50% reduction
        
        # Liquidity constraint
        liquidity_ratio = min(available_liquidity / requested_size, 1.0)
        
        # Combined fill rate
        fill_rate = fill_probability * liquidity_ratio
        
        # Simulate fill
        if np.random.random() < fill_rate:
            filled_size = requested_size * np.random.uniform(0.8, 1.0)
        else:
            filled_size = requested_size * np.random.uniform(0.3, 0.7)
        
        is_complete = (filled_size >= requested_size * 0.95)
        
        return filled_size, is_complete


class HoldTimeRewardShaper:
    """
    Option 5: Hold Time Reward Shaping (Dec 28, 2025 Enhancement)
    
    Problem: No incentive to hold positions. Agent flips rapidly.
    Solution: Add holding bonus that grows with profitable hold time + quick flip penalty.
    
    Impact: Agent learns to ride winners instead of taking quick profits.
    
    Reward Modifiers:
    - Quick flip (<5 min): 0.5x penalty (halve reward)
    - Short hold (5-15 min): 0.5x to 1.0x (linear scale)
    - Normal hold (15-30 min): 1.0x (no modifier)
    - Long profitable hold (30+ min): 1.0x to 1.2x bonus (linear scale up to 2 hours)
    """
    
    def __init__(
        self,
        quick_flip_penalty: float = 0.5,      # Multiply reward by 0.5 if closed < 5min
        min_hold_minutes: int = 15,           # Below this = penalty
        hold_bonus_start_minutes: int = 30,   # Start bonus after this
        hold_bonus_max_hours: float = 2.0,    # Max bonus at this duration  
        hold_bonus_max_pct: float = 0.20,     # Max 20% bonus for long holds
        trading_cost_weight: float = 1.0      # Weight for trading costs in reward
    ):
        self.quick_flip_penalty = quick_flip_penalty
        self.min_hold_minutes = min_hold_minutes
        self.hold_bonus_start_minutes = hold_bonus_start_minutes
        self.hold_bonus_max_hours = hold_bonus_max_hours
        self.hold_bonus_max_pct = hold_bonus_max_pct
        self.trading_cost_weight = trading_cost_weight
        
        # Statistics
        self.stats = {
            'total_shaped': 0,
            'quick_flip_count': 0,
            'short_hold_count': 0,
            'normal_hold_count': 0,
            'long_hold_count': 0,
            'total_bonus_applied': 0.0,
            'total_penalty_applied': 0.0
        }
        
        logger.info(f"HoldTimeRewardShaper initialized: quick_flip_penalty={quick_flip_penalty}, "
                   f"min_hold={min_hold_minutes}min, bonus_start={hold_bonus_start_minutes}min, "
                   f"max_bonus={hold_bonus_max_pct:.0%}")
    
    def compute_hold_modifier(
        self,
        pnl: float,
        hold_time_minutes: float,
        is_profitable: bool = None
    ) -> Tuple[float, str]:
        """
        Compute reward modifier based on hold time.
        
        Args:
            pnl: Profit/loss from trade
            hold_time_minutes: How long position was held
            is_profitable: Whether trade was profitable (auto-detected if None)
            
        Returns:
            (modifier, reason) - modifier is multiplied with base reward
        """
        if is_profitable is None:
            is_profitable = pnl > 0
        
        # 1. Quick flip penalty (< 5 min)
        if hold_time_minutes < 5:
            self.stats['quick_flip_count'] += 1
            self.stats['total_penalty_applied'] += (1.0 - self.quick_flip_penalty)
            return self.quick_flip_penalty, f"QUICK_FLIP_PENALTY: held only {hold_time_minutes:.1f}min"
        
        # 2. Below minimum hold (5-15 min) - partial penalty
        if hold_time_minutes < self.min_hold_minutes:
            self.stats['short_hold_count'] += 1
            # Linear scale from quick_flip_penalty to 1.0
            ratio = (hold_time_minutes - 5) / (self.min_hold_minutes - 5)
            modifier = self.quick_flip_penalty + ratio * (1.0 - self.quick_flip_penalty)
            penalty = 1.0 - modifier
            self.stats['total_penalty_applied'] += penalty
            return modifier, f"SHORT_HOLD: {hold_time_minutes:.1f}min < {self.min_hold_minutes}min"
        
        # 3. Hold bonus for profitable positions held longer
        if is_profitable and hold_time_minutes > self.hold_bonus_start_minutes:
            self.stats['long_hold_count'] += 1
            # Bonus grows linearly with hold time, capped at max
            hours_held = hold_time_minutes / 60
            hours_start = self.hold_bonus_start_minutes / 60
            bonus_ratio = min(
                (hours_held - hours_start) / (self.hold_bonus_max_hours - hours_start),
                1.0
            )
            bonus = bonus_ratio * self.hold_bonus_max_pct
            modifier = 1.0 + bonus
            self.stats['total_bonus_applied'] += bonus
            return modifier, f"HOLD_BONUS: {hold_time_minutes:.1f}min → +{bonus:.1%}"
        
        # 4. Normal hold (15-30 min) - no modifier
        self.stats['normal_hold_count'] += 1
        return 1.0, f"NORMAL_HOLD: {hold_time_minutes:.1f}min"
    
    def shape_reward(
        self,
        base_pnl: float,
        hold_time_minutes: float,
        trading_costs: float = 0,
        use_net_pnl: bool = True
    ) -> Dict[str, float]:
        """
        Apply full reward shaping with hold time modifiers.
        
        Args:
            base_pnl: Raw profit/loss from trade
            hold_time_minutes: How long position was held
            trading_costs: Total trading costs (fees + slippage)
            use_net_pnl: Whether to subtract costs before shaping
            
        Returns:
            Dict with all reward components
        """
        self.stats['total_shaped'] += 1
        
        # Calculate net PnL
        net_pnl = base_pnl - (trading_costs * self.trading_cost_weight) if use_net_pnl else base_pnl
        is_profitable = net_pnl > 0
        
        # Get hold time modifier
        modifier, reason = self.compute_hold_modifier(net_pnl, hold_time_minutes, is_profitable)
        
        # Apply modifier to base PnL (not net, to preserve cost penalty)
        shaped_pnl = base_pnl * modifier
        shaped_net = shaped_pnl - trading_costs if use_net_pnl else shaped_pnl
        
        return {
            'base_pnl': float(base_pnl),
            'trading_costs': float(trading_costs),
            'net_pnl': float(net_pnl),
            'hold_time_minutes': float(hold_time_minutes),
            'hold_modifier': float(modifier),
            'hold_reason': reason,
            'shaped_pnl': float(shaped_pnl),
            'shaped_net': float(shaped_net),
            'is_profitable': is_profitable,
            'final_reward': float(shaped_net)  # This is what goes to the RL agent
        }
    
    def get_statistics(self) -> Dict[str, float]:
        """Get shaping statistics"""
        total = self.stats['total_shaped']
        if total == 0:
            return self.stats
        
        return {
            **self.stats,
            'quick_flip_pct': (self.stats['quick_flip_count'] / total) * 100,
            'short_hold_pct': (self.stats['short_hold_count'] / total) * 100,
            'normal_hold_pct': (self.stats['normal_hold_count'] / total) * 100,
            'long_hold_pct': (self.stats['long_hold_count'] / total) * 100,
            'avg_bonus': self.stats['total_bonus_applied'] / max(1, self.stats['long_hold_count']),
            'avg_penalty': self.stats['total_penalty_applied'] / max(1, self.stats['quick_flip_count'] + self.stats['short_hold_count'])
        }


class TransactionCostAwareReward:
    """
    Option 1: Train With Real Transaction Costs (Fundamental Fix)
    
    Problem: The RL agent learns to churn because it doesn't "feel" fees during training.
    Solution: Bake fees + slippage + spread into the reward function at training time.
    
    Impact: Agent learns that frequent trading destroys returns. Will naturally hold longer.
    """
    
    def __init__(
        self,
        taker_fee_pct: float = 0.05,      # 0.05% per side
        maker_fee_pct: float = 0.02,      # 0.02% per side
        slippage_pct: float = 0.02,       # 0.02% typical slippage
        spread_pct: float = 0.03,         # 0.03% typical spread
        fee_penalty_weight: float = 1.0   # How much to penalize fees (1.0 = full cost)
    ):
        self.taker_fee_pct = taker_fee_pct
        self.maker_fee_pct = maker_fee_pct
        self.slippage_pct = slippage_pct
        self.spread_pct = spread_pct
        self.fee_penalty_weight = fee_penalty_weight
        
        # Round-trip costs (entry + exit)
        self.round_trip_taker = (taker_fee_pct + slippage_pct + spread_pct) * 2
        self.round_trip_maker = (maker_fee_pct + slippage_pct + spread_pct) * 2
        
        logger.info(f"TransactionCostAwareReward initialized: "
                   f"taker={self.round_trip_taker:.2f}%, maker={self.round_trip_maker:.2f}%")
    
    def compute_reward(
        self,
        pnl_pct: float,          # PnL as percentage of position
        notional_usd: float,     # Position size in USD
        use_maker: bool = False, # Whether maker order was used
        is_round_trip: bool = True  # Full entry+exit or just one side
    ) -> Dict[str, float]:
        """
        Compute transaction-cost-aware reward.
        
        Args:
            pnl_pct: Raw PnL as percentage (e.g., 1.0 = 1% profit)
            notional_usd: Position size in USD
            use_maker: Whether maker order was used
            is_round_trip: Whether this is a full trade (entry + exit)
            
        Returns:
            Dict with reward components
        """
        # Select cost basis
        if use_maker:
            cost_pct = self.round_trip_maker if is_round_trip else self.maker_fee_pct + self.slippage_pct + self.spread_pct
        else:
            cost_pct = self.round_trip_taker if is_round_trip else self.taker_fee_pct + self.slippage_pct + self.spread_pct
        
        # Calculate values
        gross_pnl_usd = notional_usd * (pnl_pct / 100)
        cost_usd = notional_usd * (cost_pct / 100) * self.fee_penalty_weight
        net_pnl_usd = gross_pnl_usd - cost_usd
        net_pnl_pct = (net_pnl_usd / notional_usd) * 100 if notional_usd > 0 else 0
        
        # The reward the agent sees
        reward = net_pnl_pct
        
        return {
            'gross_pnl_pct': float(pnl_pct),
            'gross_pnl_usd': float(gross_pnl_usd),
            'cost_pct': float(cost_pct),
            'cost_usd': float(cost_usd),
            'net_pnl_pct': float(net_pnl_pct),
            'net_pnl_usd': float(net_pnl_usd),
            'reward': float(reward),
            'use_maker': use_maker,
            'is_round_trip': is_round_trip
        }
    
    def minimum_profitable_move(self, use_maker: bool = False) -> float:
        """
        Calculate minimum price move needed to be profitable.
        
        Returns percentage move needed to break even after costs.
        """
        cost_pct = self.round_trip_maker if use_maker else self.round_trip_taker
        return cost_pct


class OnlineRewardShaper:
    """
    Adaptive reward shaping that learns from trading experience.
    """
    
    def __init__(self, learning_rate: float = 0.01):
        """
        Initialize online reward shaper.
        
        Args:
            learning_rate: Learning rate for weight updates
        """
        self.learning_rate = learning_rate
        
        # Adaptive weights (start with balanced weights)
        self.weights = {
            'profit': 1.0,
            'risk': 0.5,
            'cost': 0.3,
            'duration': 0.1,
            'sharpe': 0.3
        }
        
        # Performance tracking
        self.weight_history = []
        self.performance_by_weight = {k: [] for k in self.weights.keys()}
        
        # Add hold time shaper as component
        self.hold_shaper = HoldTimeRewardShaper()
        
        # Add transaction cost awareness
        self.cost_shaper = TransactionCostAwareReward()
        
        logger.info("OnlineRewardShaper initialized with hold time and cost awareness")
    
    def update_weights(
        self,
        reward_components: Dict[str, float],
        actual_performance: float
    ):
        """
        Update reward weights based on actual performance.
        
        Args:
            reward_components: Individual reward components
            actual_performance: Actual trading performance
        """
        # Calculate gradient for each component
        for key in self.weights.keys():
            component_key = f'{key}_reward' if key in ['profit', 'sharpe'] else f'{key}_penalty'
            component_value = reward_components.get(component_key, 0)
            
            # Gradient = component_value * performance
            gradient = component_value * actual_performance
            
            # Update weight
            self.weights[key] += self.learning_rate * gradient
            
            # Clip to reasonable range
            self.weights[key] = np.clip(self.weights[key], 0.1, 2.0)
        
        # Normalize weights
        total = sum(self.weights.values())
        for key in self.weights:
            self.weights[key] /= total
        
        # Record
        self.weight_history.append(self.weights.copy())
    
    def get_current_weights(self) -> Dict[str, float]:
        """Get current adaptive weights."""
        return self.weights.copy()


if __name__ == '__main__':
    # Test advanced reward calculator
    logging.basicConfig(level=logging.INFO)
    
    calc = AdvancedRewardCalculator()
    
    # Simulate a profitable trade
    reward_components = calc.calculate_reward(
        pnl=500,
        position_size=10000,
        entry_price=50000,
        current_price=50500,
        trading_costs=20,
        duration_hours=12,
        portfolio_value=50000,
        max_drawdown=-0.02,
        volatility=0.02
    )
    
    print("Profitable trade reward components:")
    for key, value in reward_components.items():
        print(f"  {key}: {value:.6f}")
    
    # Test realistic trading simulator
    simulator = RealisticTradingSimulator()
    
    exec_price, total_cost, details = simulator.simulate_order_execution(
        action='buy',
        size=0.5,  # 0.5 BTC
        current_price=50000,
        volatility=0.03,
        order_type='market',
        urgency=0.8
    )
    
    print(f"\nOrder execution simulation:")
    print(f"  Execution price: ${exec_price:,.2f}")
    print(f"  Total cost: ${total_cost:.2f}")
    print(f"  Details: {details}")
    
    # Test Hold Time Reward Shaper (Option 5)
    print("\n" + "=" * 60)
    print("HOLD TIME REWARD SHAPING TESTS (Option 5)")
    print("=" * 60)
    
    hold_shaper = HoldTimeRewardShaper()
    
    test_cases = [
        # (base_pnl, hold_time_minutes, trading_costs)
        (50, 3, 5),    # Quick flip - should get penalty
        (50, 10, 5),   # Short hold - partial penalty
        (50, 20, 5),   # Normal hold - no modifier
        (50, 45, 5),   # Long hold, profitable - should get bonus
        (50, 120, 5),  # Very long hold - max bonus
        (-20, 60, 5),  # Long hold but losing - no bonus
    ]
    
    print("\nHold Time Shaping Results:")
    print("-" * 80)
    for pnl, hold_min, costs in test_cases:
        result = hold_shaper.shape_reward(pnl, hold_min, costs)
        print(f"PnL=${pnl:+.0f}, Hold={hold_min:3}min: modifier={result['hold_modifier']:.2f}, "
              f"final=${result['final_reward']:.2f} ({result['hold_reason']})")
    
    print("\nHold Time Statistics:")
    for k, v in hold_shaper.get_statistics().items():
        if isinstance(v, float):
            print(f"  {k}: {v:.2f}")
        else:
            print(f"  {k}: {v}")
    
    # Test Transaction Cost Aware Reward (Option 1)
    print("\n" + "=" * 60)
    print("TRANSACTION COST AWARE REWARD TESTS (Option 1)")
    print("=" * 60)
    
    cost_shaper = TransactionCostAwareReward()
    
    print(f"\nMinimum profitable move (taker): {cost_shaper.minimum_profitable_move(use_maker=False):.2f}%")
    print(f"Minimum profitable move (maker): {cost_shaper.minimum_profitable_move(use_maker=True):.2f}%")
    
    print("\nCost-Aware Reward Examples:")
    print("-" * 80)
    
    examples = [
        # (pnl_pct, notional, use_maker)
        (0.5, 1000, False),   # Small profit, taker - likely negative after costs
        (0.5, 1000, True),    # Small profit, maker - might be positive
        (1.0, 1000, False),   # Larger profit, taker
        (1.0, 1000, True),    # Larger profit, maker
        (2.0, 1000, False),   # Good profit, taker
        (-0.3, 1000, False),  # Small loss + costs
    ]
    
    for pnl_pct, notional, use_maker in examples:
        result = cost_shaper.compute_reward(pnl_pct, notional, use_maker)
        print(f"PnL={pnl_pct:+.1f}%, notional=${notional}, {'maker' if use_maker else 'taker'}: "
              f"costs={result['cost_pct']:.2f}%, net={result['net_pnl_pct']:+.2f}%, "
              f"reward=${result['net_pnl_usd']:+.2f}")
