from __future__ import annotations

from types import SimpleNamespace

from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop
from v2.backend.app.services.paper_trade_management.caps import (
    PAPER_TOTAL_EXPOSURE_CAP_BLOCK,
    evaluate_exposure_caps,
)


def test_lifecycle_backstop_uses_contracted_dynamic_envelope() -> None:
    caps = paper_loop._paper_lifecycle_exposure_caps_from_dynamic_envelope(  # noqa: SLF001
        SimpleNamespace(
            max_single_symbol_exposure_pct=0.016,
            max_total_portfolio_risk_pct=0.12,
            emergency_absolute_cap_usdt=None,
        )
    )

    result = evaluate_exposure_caps(
        positions={},
        symbol="BTCUSDT",
        candidate_notional=1_300.0,
        caps=caps,
        portfolio_equity_usdt=10_000.0,
    )

    assert caps.max_single_symbol_exposure_pct == 0.016
    assert caps.max_total_paper_exposure_pct == 0.12
    assert result["allowed"] is False
    assert PAPER_TOTAL_EXPOSURE_CAP_BLOCK in result["blockers"]


def test_lifecycle_backstop_fails_closed_for_invalid_dynamic_caps() -> None:
    caps = paper_loop._paper_lifecycle_exposure_caps_from_dynamic_envelope(  # noqa: SLF001
        SimpleNamespace(
            max_single_symbol_exposure_pct=float("nan"),
            max_total_portfolio_risk_pct=None,
            emergency_absolute_cap_usdt=float("inf"),
        )
    )

    assert caps.max_single_symbol_exposure_pct == 0.0
    assert caps.max_total_paper_exposure_pct == 0.0
    assert caps.emergency_absolute_cap_usdt is None
