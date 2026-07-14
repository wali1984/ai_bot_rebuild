from __future__ import annotations

from v2.backend.app.services.preemptive_edge_control.cost_edge_validator import (
    assess_cost_edge,
)


def test_cost_edge_preserves_zero_cost_components_as_present() -> None:
    result = assess_cost_edge(
        {
            "actual_observed_spread_entry_bps": 0.0,
            "expected_slippage_bps": 0.0,
            "pre_trade_fee_bps": 0.0,
            "funding_bps": 0.0,
            "expected_move_bps": 1.5,
        }
    )

    assert result["spread_slippage_funding_cost_bps"] == 0.0
    assert result["expected_edge_after_cost_bps"] == 1.5
    assert "SPREAD_SLIPPAGE_FUNDING_COST_MISSING" not in result["cost_edge_reasons"]
    assert result["cost_edge_valid"] is True


def test_cost_edge_preserves_zero_gross_move_as_non_positive_edge() -> None:
    result = assess_cost_edge(
        {
            "actual_observed_spread_entry_bps": 0.0,
            "expected_slippage_bps": 0.0,
            "pre_trade_fee_bps": 0.0,
            "funding_bps": 0.0,
            "expected_move_bps": 0.0,
            "price_target_bps": 5.0,
        }
    )

    assert result["expected_edge_after_cost_bps"] == 0.0
    assert "EXPECTED_EDGE_AFTER_COST_NON_POSITIVE" in result["cost_edge_reasons"]
    assert result["cost_edge_valid"] is False
