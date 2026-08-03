from __future__ import annotations

from .contracts import AllocationInput, RiskEnvelope


def available_symbol_budget_usdt(row: AllocationInput, envelope: RiskEnvelope) -> float:
    max_symbol = row.equity * max(0.0, envelope.max_single_symbol_exposure_pct)
    return max(0.0, max_symbol - max(0.0, row.symbol_exposure_usdt))


def available_total_budget_usdt(row: AllocationInput, envelope: RiskEnvelope) -> float:
    max_total = row.equity * max(0.0, envelope.max_total_portfolio_risk_pct)
    return max(0.0, max_total - max(0.0, row.total_exposure_usdt))


def available_margin_budget_usdt(row: AllocationInput, envelope: RiskEnvelope) -> float:
    usable = row.available_margin * max(0.0, 1.0 - envelope.min_available_margin_buffer_pct)
    return max(0.0, usable)


def risk_envelope_gross_notional_ceiling(row: AllocationInput, envelope: RiskEnvelope) -> float:
    ceiling = min(
        available_symbol_budget_usdt(row, envelope),
        available_total_budget_usdt(row, envelope),
    )
    if envelope.emergency_absolute_cap_usdt is not None:
        ceiling = min(ceiling, max(0.0, envelope.emergency_absolute_cap_usdt))
    return max(0.0, ceiling)


def risk_envelope_notional_ceiling(row: AllocationInput, envelope: RiskEnvelope) -> float:
    ceiling = min(
        available_symbol_budget_usdt(row, envelope),
        available_total_budget_usdt(row, envelope),
        available_margin_budget_usdt(row, envelope),
    )
    if envelope.emergency_absolute_cap_usdt is not None:
        ceiling = min(ceiling, max(0.0, envelope.emergency_absolute_cap_usdt))
    return max(0.0, ceiling)
