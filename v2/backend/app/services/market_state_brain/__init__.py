"""Market State Brain — classify every symbol/timeframe before any trade decision.

States (ordered by priority):
  NO_TRADE                          — default / insufficient evidence
  VOLATILITY_EXPANSION_UNSAFE       — bid/ask spread too wide, orderbook thin
  DOUBLE_SIDED_LIQUIDATION_WHIPSAW  — wicks both directions, both sides hunted
  ORDERBOOK_TRAP_OR_SPOOF_RISK      — anomalous wall/pull pattern
  EMERGENCY_DE_RISK                 — drawdown emergency or cascade active
  HEDGE_LOCK_MANAGEMENT             — active hedge lock pair on this symbol
  BREAKOUT_SQUEEZE_LONG             — confirmed long squeeze/breakout
  BREAKOUT_SQUEEZE_SHORT            — confirmed short squeeze/breakout
  LIQUIDITY_SWEEP_FALSE_BREAKOUT    — wick beyond level, closed back inside
  RANGE_MEAN_REVERSION              — oscillating range, mean-revert signal
  TREND_CONTINUATION_LONG           — trend up, continuation entry
  TREND_CONTINUATION_SHORT          — trend down, continuation entry
"""

from .classifier import MarketState, classify_market_state, MarketStateBrainResult

__all__ = ["MarketState", "classify_market_state", "MarketStateBrainResult"]
