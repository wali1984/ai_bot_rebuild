from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from v2.backend.app.services.adaptive_system.selected_action_venue_feasibility_v2 import (
    DECISION_BLOCK,
    DECISION_EXECUTABLE,
    SelectedActionVenueFeasibilityRequestV2,
    attest_selected_action_venue_feasibility,
)


def _request() -> SelectedActionVenueFeasibilityRequestV2:
    return SelectedActionVenueFeasibilityRequestV2(
        candidate_id="candidate-1",
        policy_action_sha256="a" * 64,
        venue_rules_receipt_sha256="b" * 64,
        capital_snapshot_sha256="c" * 64,
        catastrophic_envelope_receipt_sha256="d" * 64,
        side="LONG",
        selected_entry_price=Decimal("10.00"),
        selected_stop_price=Decimal("9.50"),
        selected_notional_usd=Decimal("20.00"),
        selected_leverage=Decimal("2"),
        selected_margin_usd=Decimal("10.00"),
        selected_round_trip_cost_bps=Decimal("10"),
        venue_price_tick=Decimal("0.01"),
        venue_min_notional_usd=Decimal("5"),
        venue_max_notional_usd=Decimal("1000"),
        venue_min_qty=Decimal("0.1"),
        venue_max_qty=Decimal("100"),
        venue_qty_step=Decimal("0.1"),
        catastrophic_max_notional_usd=Decimal("100"),
        catastrophic_max_loss_usd=Decimal("5"),
        catastrophic_max_margin_usd=Decimal("50"),
        catastrophic_max_leverage=Decimal("3"),
        remaining_catastrophic_notional_headroom_usd=Decimal("80"),
        remaining_catastrophic_loss_headroom_usd=Decimal("4"),
        available_collateral_usd=Decimal("100"),
        reserved_margin_usd=Decimal("20"),
    )


def test_attests_exact_policy_selection_without_resizing() -> None:
    result = attest_selected_action_venue_feasibility(_request())

    assert result.decision == DECISION_EXECUTABLE
    assert result.failed_checks == ()
    assert result.exact_selected_quantity == Decimal("2")
    assert result.exact_selected_notional_usd == Decimal("20.00")
    assert result.selected_action_unchanged is True
    assert result.policy_size_proposal is False
    assert result.execution_authority is False
    assert result.exchange_action_taken is False


def test_rejects_below_minimum_without_rounding_up() -> None:
    request = replace(
        _request(),
        selected_notional_usd=Decimal("4.00"),
        selected_margin_usd=Decimal("2.00"),
    )

    result = attest_selected_action_venue_feasibility(request)

    assert result.decision == DECISION_BLOCK
    assert "venue_notional_range" in result.failed_checks
    assert result.exact_selected_notional_usd == Decimal("4.00")
    assert result.policy_size_proposal is False


def test_rejects_non_step_quantity_instead_of_changing_selection() -> None:
    request = replace(
        _request(),
        selected_notional_usd=Decimal("20.50"),
        selected_margin_usd=Decimal("10.25"),
    )

    result = attest_selected_action_venue_feasibility(request)

    assert result.decision == DECISION_BLOCK
    assert "quantity_on_venue_step" in result.failed_checks
    assert result.exact_selected_quantity == Decimal("2.05")
    assert result.selected_action_unchanged is True


def test_rejects_catastrophic_loss_without_policy_override() -> None:
    request = replace(_request(), selected_stop_price=Decimal("7.00"))

    result = attest_selected_action_venue_feasibility(request)

    assert result.decision == DECISION_BLOCK
    assert "catastrophic_loss" in result.failed_checks
    assert result.execution_authority is False
