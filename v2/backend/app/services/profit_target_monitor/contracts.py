"""Contracts for the V2 monthly profit-target monitor.

This module is intentionally free of Redis, exchange, trainer, and order
transport imports. It defines status vocabulary only.
"""

READY = "V2_MONTHLY_10K_PROFIT_TARGET_TRAINER_STRATEGY_HEDGE_MONITOR_READY"
BLOCKED = "V2_MONTHLY_10K_PROFIT_TARGET_TRAINER_STRATEGY_HEDGE_MONITOR_BLOCKED"

MONTHLY_TARGET_NET_USDT = 10_000.0
DAYS_PER_MONTH = 30.0
HOURS_PER_MONTH = 720.0

GOAL_STATUSES = {
    "ON_TRACK_FOR_10K_MONTHLY_PAPER",
    "NOT_ON_TRACK_FOR_10K_MONTHLY_PAPER",
    "INSUFFICIENT_SAMPLE_FOR_10K_TARGET",
    "LIVE_TARGET_NOT_EXECUTABLE_NO_CAPITAL",
    "RISK_TOO_HIGH_FOR_10K_TARGET",
}

TRAINER_CAPABILITY_STATUSES = {
    "TRAINER_CAPABLE_AND_LEARNING",
    "TRAINER_ACTIVE_BUT_INSUFFICIENT_FEEDBACK",
    "TRAINER_ACTIVE_BUT_LOW_EDGE",
    "TRAINER_ACTIVE_BUT_CALIBRATION_WEAK",
    "TRAINER_NOT_TRAINING_FAST_ENOUGH",
    "TRAINER_DATASET_TOO_SMALL",
}

HEDGE_STATUSES = {
    "HEDGING_READY_ADAPTIVE",
    "HEDGING_BLOCKED_NO_VALID_HEDGE_CONTEXT",
    "HEDGING_ACTIVE_BUT_NOT_PROVEN_PROFITABLE",
    "HEDGING_DISABLED_BY_RISK",
    "ACCIDENTAL_HEDGE_DETECTED_BLOCKED",
}

SIMULATION_STATUSES = {
    "GOAL_PLAUSIBLE_WITH_CURRENT_CAPITAL_AND_RISK",
    "GOAL_REQUIRES_MORE_CAPITAL",
    "GOAL_REQUIRES_UNACCEPTABLE_RISK",
    "GOAL_NOT_SUPPORTED_BY_CURRENT_EDGE",
    "INSUFFICIENT_EVIDENCE",
}

STRATEGY_FAMILIES = (
    "trend_following",
    "mean_reversion",
    "breakout",
    "momentum",
    "funding_oi_divergence",
    "liquidation_cascade",
    "orderbook_imbalance",
    "ta_confirmation",
    "volatility_regime",
    "public_intel_confirmation",
    "no_trade_preservation",
    "hedged_protection",
)

REQUIRED_TRAINER_FEEDBACK_FIELDS = (
    "strategy_id",
    "strategy_family",
    "hedge_state",
    "hedge_reason",
    "exit_reason",
    "realized_pnl_bps",
    "hold_time_seconds",
    "drawdown_at_entry",
    "market_regime_at_entry",
    "market_regime_at_exit",
)
