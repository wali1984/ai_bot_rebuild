from __future__ import annotations

from v2.backend.app.services.preemptive_edge_control.exit_feasibility import (
    assess_exit_feasibility,
)


def test_explicit_net_edge_is_not_charged_observed_cost_twice() -> None:
    result = assess_exit_feasibility(
        {
            "entry_atr_bps": 5.0,
            "stop_distance_bps": 10.0,
            "paper_only": True,
        },
        {
            "expected_edge_after_cost_bps": 10.0,
            "spread_slippage_funding_cost_bps": 20.0,
        },
    )

    assert result["exit_feasibility_score"] == 1.0
    assert "EXPECTED_EDGE_LESS_THAN_COST_TO_EXIT" not in result["exit_feasibility_reasons"]
    assert result["MFE_required_to_profit"] == 25.0


def test_existing_net_edge_to_stop_risk_guard_is_preserved() -> None:
    result = assess_exit_feasibility(
        {
            "entry_atr_bps": 5.0,
            "stop_distance_bps": 30.0,
            "paper_only": True,
        },
        {
            "expected_edge_after_cost_bps": 10.0,
            "spread_slippage_funding_cost_bps": 20.0,
        },
    )

    assert result["exit_feasibility_score"] == 0.4
    assert result["exit_feasibility_reasons"] == [
        "MFE_REQUIRED_UNREALISTIC_FOR_STOP_RISK"
    ]
