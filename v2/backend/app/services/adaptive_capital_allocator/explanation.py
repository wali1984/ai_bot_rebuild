from __future__ import annotations

from .contracts import AllocationResult


def explain_allocation(result: AllocationResult) -> str:
    if result.decision.startswith("BLOCK_"):
        return f"{result.decision}: {result.final_size_reason}"
    return (
        f"{result.decision}: target {result.target_notional_usdt:.4f} USDT "
        f"({result.risk_budget_pct_of_equity:.4%} equity) after confidence, edge, "
        "volatility, liquidity, drawdown, exposure, correlation, regime, and exchange-filter adjustments."
    )
