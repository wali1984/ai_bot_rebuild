"""Tests for the trainer leverage/margin exploration study (Workstream B)."""

from __future__ import annotations

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.leverage_margin_exploration import (
    evaluate_leverage_for_candidate,
    evaluate_leverage_margin_grid,
)


def test_positive_edge_explores_leverage_above_1x() -> None:
    out = evaluate_leverage_margin_grid(
        {"expected_move_after_cost_bps": 40.0, "stop_distance_bps": 20.0,
         "equity_usd": 200.0, "notional_usd": 60.0}
    )
    assert out["dynamic_not_static"] is True
    assert {row["leverage"] for row in out["per_leverage_breakdown"]} == {1.0, 2.0, 3.0}
    assert out["best_leverage"] >= 1.0
    assert out["best_risk_adjusted_score"] > 0.0


def test_non_positive_edge_never_levered() -> None:
    out = evaluate_leverage_margin_grid({"expected_move_after_cost_bps": -10.0})
    assert out["best_leverage"] == 1.0
    for row in out["per_leverage_breakdown"]:
        if row["leverage"] > 1.0:
            assert row["eligible"] is False


def test_expectancy_scales_with_leverage() -> None:
    lo = evaluate_leverage_for_candidate(expected_move_after_cost_bps=30.0, leverage=1.0)
    hi = evaluate_leverage_for_candidate(expected_move_after_cost_bps=30.0, leverage=3.0)
    assert hi["levered_expectancy_bps"] > lo["levered_expectancy_bps"]


def test_liquidation_buffer_shrinks_with_leverage() -> None:
    lo = evaluate_leverage_for_candidate(expected_move_after_cost_bps=30.0, leverage=1.0)
    hi = evaluate_leverage_for_candidate(expected_move_after_cost_bps=30.0, leverage=3.0)
    assert hi["liquidation_buffer_bps"] < lo["liquidation_buffer_bps"]


def test_max_loss_over_cap_rejects_leverage() -> None:
    row = evaluate_leverage_for_candidate(
        expected_move_after_cost_bps=40.0, stop_distance_bps=500.0,
        equity_usd=200.0, notional_usd=180.0, leverage=3.0,
    )
    assert row["eligible"] is False
    assert row["reject_reason"] == "MODELED_MAX_LOSS_EXCEEDS_PER_TRADE_CAP"


def test_study_never_routes_to_live() -> None:
    out = evaluate_leverage_margin_grid({"expected_move_after_cost_bps": 40.0})
    assert out["study_only"] is True
    assert out["routes_to_live"] is False
    assert out["places_real_order"] is False
    assert out["leverage_mutated"] is False
    assert out["margin_mutated"] is False
