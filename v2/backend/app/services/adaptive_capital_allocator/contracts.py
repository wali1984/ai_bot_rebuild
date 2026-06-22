from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ADAPTIVE_CAPITAL_POLICY_VERSION = "ADAPTIVE_CAPITAL_ALLOCATOR_V1"


AllocationDecision = Literal[
    "ALLOW_WITH_SIZE",
    "REDUCE_SIZE",
    "BLOCK_NO_EDGE",
    "BLOCK_LOW_CONFIDENCE",
    "BLOCK_BAD_MARKET_STATE",
    "BLOCK_INSUFFICIENT_LIQUIDITY",
    "BLOCK_SPREAD_SLIPPAGE",
    "BLOCK_EXPOSURE_BUDGET",
    "BLOCK_DRAWDOWN_GUARD",
    "BLOCK_EXCHANGE_MIN_ORDER",
    "BLOCK_INSUFFICIENT_MARGIN",
    "BLOCK_LIQUIDATION_RISK",
]


@dataclass(frozen=True)
class RiskEnvelope:
    max_total_portfolio_risk_pct: float = 0.60
    max_single_symbol_exposure_pct: float = 0.08
    max_daily_drawdown_pct: float = 0.05
    max_loss_per_trade_pct: float = 0.01
    min_available_margin_buffer_pct: float = 0.15
    max_correlation_exposure_pct: float = 0.18
    min_liquidation_buffer_bps: float = 500.0
    max_effective_leverage: float = 3.0
    tail_loss_multiplier: float = 1.5
    emergency_absolute_cap_usdt: float | None = None


@dataclass(frozen=True)
class AllocationInput:
    symbol: str
    timeframe: str
    action: str
    price: float
    equity: float
    available_margin: float
    wallet_balance: float
    confidence_calibrated: float
    expected_move_after_cost_bps: float
    market_state_integrity_score: float
    volatility_bps: float = 50.0
    liquidity_score: float = 1.0
    spread_bps: float = 2.0
    slippage_bps: float = 2.0
    fee_bps: float = 4.0
    expected_funding_bps: float = 0.0
    stop_distance_bps: float | None = None
    maintenance_margin_rate: float = 0.005
    permitted_leverage_values: tuple[float, ...] = (1.0, 2.0, 3.0)
    hedge_budget_pct_of_risk: float = 0.0
    drawdown_bps: float = 0.0
    symbol_exposure_usdt: float = 0.0
    total_exposure_usdt: float = 0.0
    correlation_exposure_pct: float = 0.0
    regime_score: float = 1.0
    min_qty: float | None = None
    step_size: float | None = None
    min_notional: float | None = None
    ppo_action_probability: float | None = None
    masa_confidence: float | None = None
    lineage_ids: dict[str, Any] = field(default_factory=dict)
    risk_veto: bool = False
    risk_veto_reason: str | None = None


@dataclass(frozen=True)
class AllocationResult:
    adaptive_capital_policy_version: str
    allocation_id: str
    symbol: str
    timeframe: str
    action: str
    decision: AllocationDecision
    target_notional_usdt: float
    target_quantity: float
    risk_budget_usd: float
    gross_notional_usd: float
    allocated_margin_usd: float
    recommended_leverage: float
    effective_leverage: float
    recommended_margin_mode: str
    stop_distance_bps: float | None
    liquidation_price_estimate: float | None
    liquidation_buffer_bps: float | None
    expected_fees_usd: float
    expected_slippage_usd: float
    expected_funding_usd: float
    expected_net_pnl_usd: float
    expected_shortfall_usd: float
    hedge_budget_usd: float
    capital_allocation_reason: str
    risk_budget_pct_of_equity: float
    risk_budget_pct_of_available_margin: float
    confidence_calibrated: float
    expected_move_after_cost_bps: float
    market_state_integrity_score: float
    volatility_adjustment: float
    liquidity_adjustment: float
    spread_slippage_adjustment: float
    drawdown_adjustment: float
    exposure_adjustment: float
    correlation_adjustment: float
    regime_adjustment: float
    exchange_min_order_adjustment: float
    final_size_reason: str
    risk_veto_reason_if_blocked: str | None
    model_inputs: dict[str, Any]
    lineage_ids: dict[str, Any]

    def to_payload(self) -> dict[str, Any]:
        return {
            "adaptive_capital_policy_version": self.adaptive_capital_policy_version,
            "allocation_id": self.allocation_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "action": self.action,
            "allocator_decision": self.decision,
            "target_notional_usdt": self.target_notional_usdt,
            "target_quantity": self.target_quantity,
            "risk_budget_usd": self.risk_budget_usd,
            "gross_notional_usd": self.gross_notional_usd,
            "allocated_margin_usd": self.allocated_margin_usd,
            "recommended_leverage": self.recommended_leverage,
            "effective_leverage": self.effective_leverage,
            "recommended_margin_mode": self.recommended_margin_mode,
            "stop_distance_bps": self.stop_distance_bps,
            "liquidation_price_estimate": self.liquidation_price_estimate,
            "liquidation_buffer_bps": self.liquidation_buffer_bps,
            "expected_fees_usd": self.expected_fees_usd,
            "expected_slippage_usd": self.expected_slippage_usd,
            "expected_funding_usd": self.expected_funding_usd,
            "expected_net_pnl_usd": self.expected_net_pnl_usd,
            "expected_shortfall_usd": self.expected_shortfall_usd,
            "hedge_budget_usd": self.hedge_budget_usd,
            "capital_allocation_reason": self.capital_allocation_reason,
            "risk_budget_pct": self.risk_budget_pct_of_equity,
            "risk_budget_pct_of_equity": self.risk_budget_pct_of_equity,
            "risk_budget_pct_of_available_margin": self.risk_budget_pct_of_available_margin,
            "confidence_calibrated": self.confidence_calibrated,
            "expected_move_after_cost_bps": self.expected_move_after_cost_bps,
            "market_state_integrity_score": self.market_state_integrity_score,
            "volatility_adjustment": self.volatility_adjustment,
            "liquidity_adjustment": self.liquidity_adjustment,
            "spread_slippage_adjustment": self.spread_slippage_adjustment,
            "drawdown_adjustment": self.drawdown_adjustment,
            "exposure_adjustment": self.exposure_adjustment,
            "correlation_adjustment": self.correlation_adjustment,
            "regime_adjustment": self.regime_adjustment,
            "exchange_min_order_adjustment": self.exchange_min_order_adjustment,
            "final_size_reason": self.final_size_reason,
            "risk_veto_reason_if_blocked": self.risk_veto_reason_if_blocked,
            "model_inputs": self.model_inputs,
            "lineage_ids": self.lineage_ids,
        }
