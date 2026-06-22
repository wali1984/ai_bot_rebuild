from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_MAX_SINGLE_SYMBOL_EXPOSURE_PCT = 0.08
DEFAULT_MAX_TOTAL_PAPER_EXPOSURE_PCT = 0.60
DEFAULT_MAX_OPEN_POSITIONS_TOTAL = 32
DEFAULT_MAX_OPEN_POSITIONS_PER_SYMBOL = 1

PAPER_SYMBOL_NOTIONAL_CAP_BLOCK = "PAPER_SYMBOL_NOTIONAL_CAP_BLOCK"
PAPER_TOTAL_EXPOSURE_CAP_BLOCK = "PAPER_TOTAL_EXPOSURE_CAP_BLOCK"
PAPER_MAX_POSITION_COUNT_BLOCK = "PAPER_MAX_POSITION_COUNT_BLOCK"
PAPER_EQUITY_EVIDENCE_MISSING_BLOCK = "PAPER_EQUITY_EVIDENCE_MISSING_BLOCK"


@dataclass(frozen=True)
class PaperExposureCaps:
    max_single_symbol_exposure_pct: float = DEFAULT_MAX_SINGLE_SYMBOL_EXPOSURE_PCT
    max_total_paper_exposure_pct: float = DEFAULT_MAX_TOTAL_PAPER_EXPOSURE_PCT
    max_open_positions_total: int = DEFAULT_MAX_OPEN_POSITIONS_TOTAL
    max_open_positions_per_symbol: int = DEFAULT_MAX_OPEN_POSITIONS_PER_SYMBOL
    emergency_absolute_cap_usdt: float | None = None


def evaluate_exposure_caps(
    *,
    positions: dict[str, Any],
    symbol: str,
    candidate_notional: float,
    caps: PaperExposureCaps,
    portfolio_equity_usdt: float | None,
) -> dict[str, Any]:
    symbol = symbol.upper()
    if portfolio_equity_usdt is None or portfolio_equity_usdt <= 0:
        return {
            "allowed": False,
            "blockers": [PAPER_EQUITY_EVIDENCE_MISSING_BLOCK],
            "symbol": symbol,
            "candidate_notional": candidate_notional,
            "portfolio_equity_usdt": portfolio_equity_usdt,
            "operator_envelope_type": "PERCENTAGE_BASED_EQUITY_ENVELOPE",
        }
    max_symbol_notional = portfolio_equity_usdt * max(0.0, caps.max_single_symbol_exposure_pct)
    max_total_notional = portfolio_equity_usdt * max(0.0, caps.max_total_paper_exposure_pct)
    if caps.emergency_absolute_cap_usdt is not None:
        max_symbol_notional = min(max_symbol_notional, max(0.0, caps.emergency_absolute_cap_usdt))
    current_symbol_notional = sum(
        abs(float(getattr(pos, "notional", 0.0)))
        for pos in positions.values()
        if str(getattr(pos, "symbol", "")).upper() == symbol
    )
    total_open_notional = sum(abs(float(getattr(pos, "notional", 0.0))) for pos in positions.values())
    open_symbol_count = sum(1 for pos in positions.values() if str(getattr(pos, "symbol", "")).upper() == symbol)
    blockers: list[str] = []
    if current_symbol_notional + candidate_notional > max_symbol_notional + 1e-9:
        blockers.append(PAPER_SYMBOL_NOTIONAL_CAP_BLOCK)
    if total_open_notional + candidate_notional > max_total_notional + 1e-9:
        blockers.append(PAPER_TOTAL_EXPOSURE_CAP_BLOCK)
    if symbol not in positions and len(positions) + 1 > caps.max_open_positions_total:
        blockers.append(PAPER_MAX_POSITION_COUNT_BLOCK)
    if symbol not in positions and open_symbol_count + 1 > caps.max_open_positions_per_symbol:
        blockers.append(PAPER_MAX_POSITION_COUNT_BLOCK)
    return {
        "allowed": not blockers,
        "blockers": blockers,
        "symbol": symbol,
        "candidate_notional": candidate_notional,
        "current_symbol_notional": current_symbol_notional,
        "total_open_notional": total_open_notional,
        "portfolio_equity_usdt": portfolio_equity_usdt,
        "max_single_symbol_exposure_pct": caps.max_single_symbol_exposure_pct,
        "max_total_paper_exposure_pct": caps.max_total_paper_exposure_pct,
        "computed_max_symbol_notional_usdt": max_symbol_notional,
        "computed_max_total_notional_usdt": max_total_notional,
        "max_open_positions_total": caps.max_open_positions_total,
        "max_open_positions_per_symbol": caps.max_open_positions_per_symbol,
        "operator_envelope_type": "PERCENTAGE_BASED_EQUITY_ENVELOPE",
        "emergency_absolute_cap_usdt": caps.emergency_absolute_cap_usdt,
    }
