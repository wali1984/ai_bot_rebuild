"""V2 native trade-management paper engine.

Paper/shadow only. Implements stealth-stop schedules, dynamic ATR-based
stops, dynamic take-profit ladders, churn veto, fee-ratio gate, and a
fail-closed hedge/DCA evaluator. Does not place, cancel, or modify exchange
orders. Does not change leverage or margin.
"""
from .service import (
    TRADE_MANAGEMENT_PAPER_SCHEMA_VERSION,
    ChurnVetoResult,
    DynamicStopPlan,
    DynamicTakeProfitLadder,
    FeeRatioGateResult,
    HedgeDcaEvaluation,
    PaperPositionSnapshot,
    StealthStopSchedule,
    TradeManagementPaperService,
    churn_veto,
    compute_dynamic_stop_plan,
    compute_dynamic_take_profit_ladder,
    compute_stealth_stop_schedule,
    evaluate_fee_ratio_gate,
    evaluate_hedge_dca,
)

__all__ = [
    "TRADE_MANAGEMENT_PAPER_SCHEMA_VERSION",
    "ChurnVetoResult",
    "DynamicStopPlan",
    "DynamicTakeProfitLadder",
    "FeeRatioGateResult",
    "HedgeDcaEvaluation",
    "PaperPositionSnapshot",
    "StealthStopSchedule",
    "TradeManagementPaperService",
    "churn_veto",
    "compute_dynamic_stop_plan",
    "compute_dynamic_take_profit_ladder",
    "compute_stealth_stop_schedule",
    "evaluate_fee_ratio_gate",
    "evaluate_hedge_dca",
]
