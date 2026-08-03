from __future__ import annotations

import dataclasses
from decimal import Decimal, localcontext

import pytest

from v2.backend.app.services.adaptive_system.venue_aware_exploration_sizing_v2 import (
    PROPOSE_TO_HARD_VALIDATOR,
    SELECT_ANOTHER,
    ExplorationSizeProposal,
    ExplorationSizingContractError,
    ExplorationSizingRequestV2,
    propose_exploration_size,
)


def _d(value: str) -> Decimal:
    return Decimal(value)


def _sha(character: str) -> str:
    return character * 64


def _request(**overrides: object) -> ExplorationSizingRequestV2:
    values: dict[str, object] = {
        "candidate_id": "candidate_001",
        "policy_action_sha256": _sha("1"),
        "venue_rules_receipt_sha256": _sha("2"),
        "capital_snapshot_sha256": _sha("3"),
        "catastrophic_envelope_receipt_sha256": _sha("4"),
        "side": "LONG",
        "executable_entry_price": _d("0.63"),
        "venue_price_tick": _d("0.01"),
        "stop_distance_fraction": _d("0.02"),
        "venue_min_notional_usd": _d("5"),
        "venue_min_qty": _d("1"),
        "venue_qty_step": _d("1"),
        "policy_authorized_max_notional_usd": _d("10"),
        "policy_authorized_max_loss_usd": _d("1"),
        "policy_authorized_max_margin_usd": _d("10"),
        "effective_leverage": _d("1"),
        "catastrophic_max_leverage": _d("3"),
        "remaining_catastrophic_notional_headroom_usd": _d("100"),
        "remaining_catastrophic_loss_headroom_usd": _d("10"),
        "available_collateral_usd": _d("100"),
        "reserved_margin_usd": _d("0"),
        "fees_slippage_funding_gap_allowance_usd": _d("0.10"),
    }
    values.update(overrides)
    return ExplorationSizingRequestV2(**values)  # type: ignore[arg-type]


def test_exact_smallest_venue_size_is_only_a_hard_validator_proposal() -> None:
    proposal = propose_exploration_size(_request())
    assert proposal.decision == PROPOSE_TO_HARD_VALIDATOR
    assert proposal.final_quantity == _d("8")
    assert proposal.final_notional_usd == _d("5.04")
    assert proposal.required_margin_usd == _d("5.04")
    assert proposal.bounded_loss_with_cost_usd == _d("0.2008")
    assert proposal.paper_only is True
    assert proposal.execution_authority is False
    assert proposal.requires_hard_validator is True
    assert proposal.routes_to_live is False


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        (
            "policy_authorized_max_notional_usd",
            _d("0.65"),
            "POLICY_NOTIONAL_BUDGET",
        ),
        ("policy_authorized_max_loss_usd", _d("0.1"), "POLICY_LOSS_BUDGET"),
        (
            "remaining_catastrophic_notional_headroom_usd",
            _d("4"),
            "CATASTROPHIC_NOTIONAL_HEADROOM",
        ),
        (
            "remaining_catastrophic_loss_headroom_usd",
            _d("0.1"),
            "CATASTROPHIC_LOSS_HEADROOM",
        ),
        ("catastrophic_max_leverage", _d("0.5"), "LEVERAGE"),
        ("policy_authorized_max_margin_usd", _d("4"), "POLICY_MARGIN_BUDGET"),
        ("available_collateral_usd", _d("4"), "FREE_COLLATERAL"),
    ],
)
def test_every_policy_capital_and_hard_headroom_is_fail_closed(
    field: str,
    value: Decimal,
    reason: str,
) -> None:
    proposal = propose_exploration_size(_request(**{field: value}))
    assert proposal.decision == SELECT_ANOTHER
    assert proposal.venue_minimum_proposed is False
    assert reason in proposal.reason
    assert proposal.final_quantity is None


def test_decimal_ceiling_never_rounds_below_fractional_minimums() -> None:
    proposal = propose_exploration_size(
        _request(
            executable_entry_price=_d("1"),
            venue_price_tick=_d("1"),
            venue_min_notional_usd=_d("1.0000000005"),
            venue_min_qty=_d("1.0000000005"),
            venue_qty_step=_d("1"),
        )
    )
    assert proposal.decision == PROPOSE_TO_HARD_VALIDATOR
    assert proposal.final_quantity == _d("2")
    assert proposal.final_notional_usd == _d("2")


def test_step_larger_than_minimum_never_returns_zero() -> None:
    proposal = propose_exploration_size(
        _request(
            executable_entry_price=_d("1"),
            venue_price_tick=_d("1"),
            venue_min_notional_usd=_d("0.0000000005"),
            venue_min_qty=_d("0.0000000005"),
            venue_qty_step=_d("1"),
        )
    )
    assert proposal.final_quantity == _d("1")
    assert proposal.final_quantity > 0


def test_off_tick_executable_entry_price_fails_closed() -> None:
    proposal = propose_exploration_size(
        _request(executable_entry_price=_d("0.631"), venue_price_tick=_d("0.01"))
    )
    assert proposal.decision == SELECT_ANOTHER
    assert proposal.reason == "EXECUTABLE_PRICE_NOT_ON_VENUE_TICK"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("venue_qty_step", _d("1e25")),
        ("venue_min_qty", _d("1e-19")),
        ("executable_entry_price", _d("Infinity")),
    ],
)
def test_extreme_or_nonfinite_inputs_are_rejected_by_request(
    field: str,
    value: Decimal,
) -> None:
    with pytest.raises(ExplorationSizingContractError):
        _request(**{field: value})


def test_float_inputs_are_rejected_to_preserve_venue_precision() -> None:
    with pytest.raises(ExplorationSizingContractError, match="finite_Decimal"):
        _request(executable_entry_price=0.63)


def test_reserved_margin_is_deducted_from_collateral() -> None:
    proposal = propose_exploration_size(
        _request(available_collateral_usd=_d("10"), reserved_margin_usd=_d("6"))
    )
    assert proposal.decision == SELECT_ANOTHER
    assert proposal.reason == "VENUE_MINIMUM_EXCEEDS_FREE_COLLATERAL"


def test_nonterminating_margin_division_uses_stable_exact_context() -> None:
    proposal = propose_exploration_size(_request(effective_leverage=_d("2.3")))
    assert proposal.decision == PROPOSE_TO_HARD_VALIDATOR
    assert proposal.required_margin_usd is not None
    assert proposal.required_margin_usd > _d("0")


def test_cost_allowance_is_included_in_loss_budget() -> None:
    proposal = propose_exploration_size(
        _request(
            policy_authorized_max_loss_usd=_d("0.15"),
            fees_slippage_funding_gap_allowance_usd=_d("0.10"),
        )
    )
    assert proposal.decision == SELECT_ANOTHER
    assert proposal.reason == "VENUE_MINIMUM_EXCEEDS_POLICY_LOSS_BUDGET"


def test_proposal_identity_is_deterministic_and_context_bound() -> None:
    first = propose_exploration_size(_request())
    second = propose_exploration_size(_request())
    changed = propose_exploration_size(_request(candidate_id="candidate_002"))
    assert first == second
    assert first.proposal_id == second.proposal_id
    assert first.proposal_id != changed.proposal_id


def test_proposal_is_independent_of_ambient_decimal_precision() -> None:
    request = _request(
        executable_entry_price=_d("0.631234567890123456"),
        venue_price_tick=_d("0.000000000000000001"),
    )
    proposals = []
    for precision in (10, 28, 50):
        with localcontext() as context:
            context.prec = precision
            proposals.append(propose_exploration_size(request))
    assert proposals[0] == proposals[1] == proposals[2]


def test_maximum_accepted_input_precision_is_total_and_fail_closed() -> None:
    request = _request(
        executable_entry_price=_d("9999999999999999999999999.999999999999999999"),
        venue_price_tick=_d("0.000000000000000001"),
        venue_min_notional_usd=_d("1"),
        venue_min_qty=_d("1"),
        venue_qty_step=_d("1"),
        policy_authorized_max_notional_usd=_d("9999999999999999999999999.999999999999999999"),
        remaining_catastrophic_notional_headroom_usd=_d(
            "9999999999999999999999999.999999999999999999"
        ),
        policy_authorized_max_loss_usd=_d("9999999999999999999999999.999999999999999999"),
        remaining_catastrophic_loss_headroom_usd=_d("9999999999999999999999999.999999999999999999"),
        policy_authorized_max_margin_usd=_d("9999999999999999999999999.999999999999999999"),
        available_collateral_usd=_d("9999999999999999999999999.999999999999999999"),
        stop_distance_fraction=_d("0.000000000000000001"),
    )
    proposal = propose_exploration_size(request)
    assert proposal.decision == PROPOSE_TO_HARD_VALIDATOR
    assert proposal.final_quantity == _d("1")


def test_large_quantity_step_modulo_is_ambient_context_independent() -> None:
    maximum = _d("9999999999999999999999999.999999999999999999")
    request = _request(
        executable_entry_price=_d("1"),
        venue_price_tick=_d("1"),
        venue_min_notional_usd=_d("1"),
        venue_min_qty=maximum,
        venue_qty_step=_d("0.000000000000000001"),
        policy_authorized_max_notional_usd=maximum,
        remaining_catastrophic_notional_headroom_usd=maximum,
        policy_authorized_max_loss_usd=maximum,
        remaining_catastrophic_loss_headroom_usd=maximum,
        policy_authorized_max_margin_usd=maximum,
        available_collateral_usd=maximum,
        stop_distance_fraction=_d("0.000000000000000001"),
    )
    proposals = []
    for precision in (10, 28, 50, 120):
        with localcontext() as context:
            context.prec = precision
            proposals.append(propose_exploration_size(request))
    assert proposals[0] == proposals[1] == proposals[2] == proposals[3]
    assert proposals[0].decision == PROPOSE_TO_HARD_VALIDATOR


def test_near_cancellation_collateral_is_ambient_context_independent() -> None:
    available = _d("9999999999999999999999999.999999999999999999")
    reserved = _d("9999999999999999999999999.999999999999999998")
    request = _request(available_collateral_usd=available, reserved_margin_usd=reserved)
    proposals = []
    for precision in (10, 28, 50, 120):
        with localcontext() as context:
            context.prec = precision
            proposals.append(propose_exploration_size(request))
    assert proposals[0] == proposals[1] == proposals[2] == proposals[3]
    assert proposals[0].decision == SELECT_ANOTHER
    assert proposals[0].reason == "VENUE_MINIMUM_EXCEEDS_FREE_COLLATERAL"


def test_forged_authority_or_arithmetic_is_rejected() -> None:
    valid = propose_exploration_size(_request())
    with pytest.raises(ExplorationSizingContractError, match="must_be_false"):
        dataclasses.replace(valid, execution_authority=True)
    with pytest.raises(ExplorationSizingContractError, match="arithmetic_mismatch"):
        dataclasses.replace(valid, final_notional_usd=_d("5.05"))
    with pytest.raises(ExplorationSizingContractError, match="deterministic_identity"):
        dataclasses.replace(valid, proposal_id="ves2_forged")


def test_selection_failure_cannot_smuggle_a_quantity() -> None:
    failed = propose_exploration_size(_request(policy_authorized_max_notional_usd=_d("0.65")))
    with pytest.raises(ExplorationSizingContractError, match="null_values"):
        dataclasses.replace(failed, final_quantity=_d("8"))


def test_wrong_request_type_is_rejected() -> None:
    with pytest.raises(TypeError, match="ExplorationSizingRequestV2"):
        propose_exploration_size({})  # type: ignore[arg-type]


def test_direct_invalid_proposal_decision_is_rejected() -> None:
    valid = propose_exploration_size(_request())
    with pytest.raises(ExplorationSizingContractError, match="invalid_decision"):
        ExplorationSizeProposal(
            proposal_id=valid.proposal_id,
            request=valid.request,
            decision="EXECUTE_NOW",
            venue_minimum_proposed=True,
            final_notional_usd=valid.final_notional_usd,
            final_quantity=valid.final_quantity,
            required_margin_usd=valid.required_margin_usd,
            bounded_loss_with_cost_usd=valid.bounded_loss_with_cost_usd,
            reason="FORGED",
            paper_only=True,
            execution_authority=False,
            requires_hard_validator=True,
            routes_to_live=False,
            places_real_order=False,
            exchange_action_taken=False,
        )
