from __future__ import annotations

import pytest

from v2.backend.app.services.adaptive_capital_allocator import (
    AllocationInput,
    allocate_paper_candidate,
)
from v2.backend.app.services.adaptive_capital_allocator.exchange_filters import (
    paper_execution_minimum,
    round_down_to_step_exact,
)


def _allocation_row(**overrides: object) -> AllocationInput:
    values: dict[str, object] = {
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "action": "long",
        "price": 100.0,
        "equity": 10_000.0,
        "available_margin": 5_000.0,
        "wallet_balance": 10_000.0,
        "confidence_calibrated": 0.8,
        "expected_move_after_cost_bps": 80.0,
        "market_state_integrity_score": 95.0,
        "liquidity_score": 1.0,
        "maintenance_margin_rate": 0.005,
        "stop_distance_bps": 100.0,
        "min_qty": 0.01,
        "step_size": 0.01,
        "max_qty": 100.0,
        "min_notional": 5.0,
    }
    values.update(overrides)
    return AllocationInput(**values)  # type: ignore[arg-type]


def test_minimum_notional_dominates_and_ceil_rounds_to_step() -> None:
    result = paper_execution_minimum(
        mark_price=3.0,
        min_qty=0.1,
        min_notional=5.0,
        step_size=0.1,
        max_qty=100.0,
    )

    assert result["status"] == "PASS"
    assert result["quantity_for_min_notional"] == pytest.approx(1.7)
    assert result["minimum_executable_quantity"] == pytest.approx(1.7)
    assert result["minimum_executable_notional"] == pytest.approx(5.1)


def test_minimum_quantity_dominates() -> None:
    result = paper_execution_minimum(
        mark_price=100.0,
        min_qty=0.1,
        min_notional=5.0,
        step_size=0.01,
        max_qty=100.0,
    )

    assert result["minimum_executable_quantity"] == pytest.approx(0.1)
    assert result["minimum_executable_notional"] == pytest.approx(10.0)


def test_exact_step_round_down_never_rounds_up() -> None:
    assert round_down_to_step_exact(1.999999, 0.1) == pytest.approx(1.9)
    assert round_down_to_step_exact(2.0, 0.1) == pytest.approx(2.0)
    assert round_down_to_step_exact(2.000001, 0.1) == pytest.approx(2.0)


def test_minimum_above_maximum_quantity_fails_closed() -> None:
    result = paper_execution_minimum(
        mark_price=1.0,
        min_qty=1.0,
        min_notional=100.0,
        step_size=1.0,
        max_qty=50.0,
    )

    assert result["status"] == "BLOCKED"
    assert result["rejection_reasons"] == ["MINIMUM_EXECUTABLE_QUANTITY_ABOVE_MAXIMUM_QUANTITY"]


def test_exactly_feasible_target_is_authorized_without_budget_increase() -> None:
    result = allocate_paper_candidate(
        _allocation_row(paper_quality_sizing_weight=0.5, min_notional=400.0)
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.gross_notional_usd == pytest.approx(400.0)
    minimum = result.model_inputs["paper_execution_minimum"]
    assert minimum["minimum_executable_notional"] == pytest.approx(400.0)
    assert minimum["final_target_notional"] == pytest.approx(400.0)
    assert minimum["execution_headroom_usd"] == pytest.approx(0.0)
    assert minimum["feasible"] is True


def test_liquidity_quality_reduction_can_make_candidate_infeasible() -> None:
    before_reduction = allocate_paper_candidate(
        _allocation_row(paper_quality_sizing_weight=1.0, min_notional=500.0)
    )
    after_reduction = allocate_paper_candidate(
        _allocation_row(paper_quality_sizing_weight=0.5, min_notional=500.0)
    )

    assert before_reduction.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert after_reduction.decision == ("BLOCK_RISK_BUDGET_BELOW_EXECUTABLE_MINIMUM")
    assert after_reduction.model_inputs["paper_execution_minimum"]["feasible"] is False


@pytest.mark.parametrize(
    ("action", "expected_move_after_cost_bps"),
    [("long", 80.0), ("short", -80.0)],
)
def test_execution_minimum_has_long_short_parity(
    action: str,
    expected_move_after_cost_bps: float,
) -> None:
    result = allocate_paper_candidate(
        _allocation_row(
            action=action,
            expected_move_after_cost_bps=expected_move_after_cost_bps,
            min_notional=500.0,
        )
    )

    assert result.decision in {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
    assert result.model_inputs["paper_execution_minimum"][
        "minimum_executable_notional"
    ] == pytest.approx(500.0)
