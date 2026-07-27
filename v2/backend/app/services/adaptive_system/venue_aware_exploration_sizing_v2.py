"""Exact, non-authoritative venue-minimum proposal for paper exploration."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from decimal import ROUND_CEILING, Decimal, DecimalException, localcontext

SCHEMA_VERSION = "venue_aware_exploration_sizing_v2"

PROPOSE_TO_HARD_VALIDATOR = "PROPOSE_VENUE_MINIMUM_TO_HARD_VALIDATOR"
SELECT_ANOTHER = "SELECT_ANOTHER_OPPORTUNITY"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ZERO = Decimal("0")
_USD_QUANTUM = Decimal("0.000000000000000001")
_DECIMAL_CONTEXT_PRECISION = 120


class ExplorationSizingContractError(ValueError):
    pass


def _raise(reason: str, field: str) -> None:
    raise ExplorationSizingContractError(f"{field}:{reason}")


def _require_identifier(value: object, field: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        _raise("must_be_non_empty_without_whitespace", field)


def _require_sha256(value: object, field: str) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        _raise("must_be_lowercase_sha256", field)


def _require_decimal(
    value: object,
    field: str,
    *,
    allow_zero: bool = False,
    minimum_exponent: int = -18,
) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        _raise("must_be_finite_Decimal", field)
    if value < _ZERO or (not allow_zero and value == _ZERO):
        _raise("must_be_nonnegative" if allow_zero else "must_be_positive", field)
    if value.as_tuple().exponent < minimum_exponent or value.adjusted() > 24:
        _raise("precision_or_magnitude_out_of_bounds", field)


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ExplorationSizingRequestV2:
    candidate_id: str
    policy_action_sha256: str
    venue_rules_receipt_sha256: str
    capital_snapshot_sha256: str
    catastrophic_envelope_receipt_sha256: str
    side: str
    executable_entry_price: Decimal
    venue_price_tick: Decimal
    stop_distance_fraction: Decimal
    venue_min_notional_usd: Decimal
    venue_min_qty: Decimal
    venue_qty_step: Decimal
    policy_authorized_max_notional_usd: Decimal
    policy_authorized_max_loss_usd: Decimal
    policy_authorized_max_margin_usd: Decimal
    effective_leverage: Decimal
    catastrophic_max_leverage: Decimal
    remaining_catastrophic_notional_headroom_usd: Decimal
    remaining_catastrophic_loss_headroom_usd: Decimal
    available_collateral_usd: Decimal
    reserved_margin_usd: Decimal
    fees_slippage_funding_gap_allowance_usd: Decimal
    paper_only: bool = True
    live_gate: str = "blocked_human_only"

    def __post_init__(self) -> None:
        _require_identifier(self.candidate_id, "candidate_id")
        for field in (
            "policy_action_sha256",
            "venue_rules_receipt_sha256",
            "capital_snapshot_sha256",
            "catastrophic_envelope_receipt_sha256",
        ):
            _require_sha256(getattr(self, field), field)
        if self.side not in {"LONG", "SHORT"}:
            _raise("must_be_LONG_or_SHORT", "side")
        for field in (
            "executable_entry_price",
            "venue_price_tick",
            "stop_distance_fraction",
            "venue_min_notional_usd",
            "venue_min_qty",
            "venue_qty_step",
            "policy_authorized_max_notional_usd",
            "policy_authorized_max_loss_usd",
            "policy_authorized_max_margin_usd",
            "effective_leverage",
            "catastrophic_max_leverage",
            "remaining_catastrophic_notional_headroom_usd",
            "remaining_catastrophic_loss_headroom_usd",
            "available_collateral_usd",
        ):
            _require_decimal(getattr(self, field), field)
        for field in (
            "reserved_margin_usd",
            "fees_slippage_funding_gap_allowance_usd",
        ):
            _require_decimal(getattr(self, field), field, allow_zero=True)
        if self.stop_distance_fraction > Decimal("1"):
            _raise("must_not_exceed_one", "stop_distance_fraction")
        if self.reserved_margin_usd > self.available_collateral_usd:
            _raise("must_not_exceed_available_collateral", "reserved_margin_usd")
        if self.paper_only is not True:
            _raise("must_be_true", "paper_only")
        if self.live_gate != "blocked_human_only":
            _raise("must_be_blocked_human_only", "live_gate")


@dataclass(frozen=True, slots=True)
class ExplorationSizeProposal:
    proposal_id: str
    request: ExplorationSizingRequestV2
    decision: str
    venue_minimum_proposed: bool
    final_notional_usd: Decimal | None
    final_quantity: Decimal | None
    required_margin_usd: Decimal | None
    bounded_loss_with_cost_usd: Decimal | None
    reason: str
    paper_only: bool
    execution_authority: bool
    requires_hard_validator: bool
    routes_to_live: bool
    places_real_order: bool
    exchange_action_taken: bool
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            _raise("invalid_schema_version", "schema_version")
        if not isinstance(self.request, ExplorationSizingRequestV2):
            _raise("must_be_ExplorationSizingRequestV2", "request")
        _require_identifier(self.proposal_id, "proposal_id")
        _require_identifier(self.reason, "reason")
        if self.decision not in {PROPOSE_TO_HARD_VALIDATOR, SELECT_ANOTHER}:
            _raise("invalid_decision", "decision")
        if self.venue_minimum_proposed is not (self.decision == PROPOSE_TO_HARD_VALIDATOR):
            _raise("must_match_decision", "venue_minimum_proposed")
        for field in (
            "paper_only",
            "requires_hard_validator",
        ):
            if getattr(self, field) is not True:
                _raise("must_be_true", field)
        for field in (
            "execution_authority",
            "routes_to_live",
            "places_real_order",
            "exchange_action_taken",
        ):
            if getattr(self, field) is not False:
                _raise("must_be_false", field)
        if self.paper_only is not self.request.paper_only:
            _raise("must_match_request", "paper_only")
        values = (
            self.final_notional_usd,
            self.final_quantity,
            self.required_margin_usd,
            self.bounded_loss_with_cost_usd,
        )
        if self.venue_minimum_proposed:
            if any(value is None for value in values):
                _raise("proposed_size_requires_all_values", "decision")
            _validate_proposed_values(self)
        elif any(value is not None for value in values):
            _raise("selection_failure_requires_null_values", "decision")
        if self.proposal_id != self.expected_proposal_id:
            _raise("must_match_deterministic_identity", "proposal_id")

    @property
    def expected_proposal_id(self) -> str:
        material = asdict(self)
        material.pop("proposal_id")
        return f"ves2_{_canonical_hash(material)}"


def _validate_proposed_values(proposal: ExplorationSizeProposal) -> None:
    request = proposal.request
    quantity = proposal.final_quantity
    notional = proposal.final_notional_usd
    margin = proposal.required_margin_usd
    bounded_loss = proposal.bounded_loss_with_cost_usd
    assert quantity is not None
    assert notional is not None
    assert margin is not None
    assert bounded_loss is not None
    for value, field in (
        (quantity, "final_quantity"),
        (notional, "final_notional_usd"),
        (margin, "required_margin_usd"),
        (bounded_loss, "bounded_loss_with_cost_usd"),
    ):
        _require_decimal(value, field, minimum_exponent=-50)
    with localcontext() as context:
        context.prec = _DECIMAL_CONTEXT_PRECISION
        quantity_step_remainder = quantity % request.venue_qty_step
        expected_notional = quantity * request.executable_entry_price
        expected_margin = (notional / request.effective_leverage).quantize(
            _USD_QUANTUM,
            rounding=ROUND_CEILING,
        )
        expected_loss = (
            notional * request.stop_distance_fraction
            + request.fees_slippage_funding_gap_allowance_usd
        ).quantize(_USD_QUANTUM, rounding=ROUND_CEILING)
        free_collateral = request.available_collateral_usd - request.reserved_margin_usd
    if quantity < request.venue_min_qty:
        _raise("below_venue_minimum", "final_quantity")
    if quantity_step_remainder != _ZERO:
        _raise("not_on_venue_step", "final_quantity")
    if notional != expected_notional:
        _raise("arithmetic_mismatch", "final_notional_usd")
    if notional < request.venue_min_notional_usd:
        _raise("below_venue_minimum", "final_notional_usd")
    if margin != expected_margin:
        _raise("arithmetic_mismatch", "required_margin_usd")
    if bounded_loss != expected_loss:
        _raise("arithmetic_mismatch", "bounded_loss_with_cost_usd")
    if notional > min(
        request.policy_authorized_max_notional_usd,
        request.remaining_catastrophic_notional_headroom_usd,
    ):
        _raise("notional_budget_exceeded", "final_notional_usd")
    if bounded_loss > min(
        request.policy_authorized_max_loss_usd,
        request.remaining_catastrophic_loss_headroom_usd,
    ):
        _raise("loss_budget_exceeded", "bounded_loss_with_cost_usd")
    if margin > min(request.policy_authorized_max_margin_usd, free_collateral):
        _raise("margin_budget_exceeded", "required_margin_usd")
    if request.effective_leverage > request.catastrophic_max_leverage:
        _raise("leverage_ceiling_exceeded", "effective_leverage")


def _failure(
    request: ExplorationSizingRequestV2,
    reason: str,
) -> ExplorationSizeProposal:
    values = {
        "request": request,
        "decision": SELECT_ANOTHER,
        "venue_minimum_proposed": False,
        "final_notional_usd": None,
        "final_quantity": None,
        "required_margin_usd": None,
        "bounded_loss_with_cost_usd": None,
        "reason": reason,
        "paper_only": True,
        "execution_authority": False,
        "requires_hard_validator": True,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "schema_version": SCHEMA_VERSION,
    }
    hash_material = dict(values)
    hash_material["request"] = asdict(request)
    return ExplorationSizeProposal(
        proposal_id=f"ves2_{_canonical_hash(hash_material)}",
        **values,
    )


def propose_exploration_size(
    request: ExplorationSizingRequestV2,
) -> ExplorationSizeProposal:
    """Propose the exact venue minimum only when every upstream budget permits it."""

    if not isinstance(request, ExplorationSizingRequestV2):
        raise TypeError("request must be ExplorationSizingRequestV2")
    try:
        with localcontext() as context:
            context.prec = _DECIMAL_CONTEXT_PRECISION
            if request.executable_entry_price % request.venue_price_tick != _ZERO:
                return _failure(request, "EXECUTABLE_PRICE_NOT_ON_VENUE_TICK")
            quantity_for_notional = request.venue_min_notional_usd / request.executable_entry_price
            minimum_quantity = max(request.venue_min_qty, quantity_for_notional)
            lot_count = (minimum_quantity / request.venue_qty_step).to_integral_value(
                rounding=ROUND_CEILING
            )
            final_quantity = lot_count * request.venue_qty_step
            final_notional = final_quantity * request.executable_entry_price
            required_margin = (final_notional / request.effective_leverage).quantize(
                _USD_QUANTUM,
                rounding=ROUND_CEILING,
            )
            bounded_loss = (
                final_notional * request.stop_distance_fraction
                + request.fees_slippage_funding_gap_allowance_usd
            ).quantize(_USD_QUANTUM, rounding=ROUND_CEILING)
    except (DecimalException, OverflowError, ValueError):
        return _failure(request, "VENUE_ARITHMETIC_INVALID")

    if (
        final_quantity <= _ZERO
        or final_quantity < request.venue_min_qty
        or final_quantity % request.venue_qty_step != _ZERO
        or final_notional < request.venue_min_notional_usd
    ):
        return _failure(request, "VENUE_MINIMUM_POSTCONDITION_FAILED")
    if final_notional > request.policy_authorized_max_notional_usd:
        return _failure(request, "VENUE_MINIMUM_EXCEEDS_POLICY_NOTIONAL_BUDGET")
    if final_notional > request.remaining_catastrophic_notional_headroom_usd:
        return _failure(request, "VENUE_MINIMUM_EXCEEDS_CATASTROPHIC_NOTIONAL_HEADROOM")
    if bounded_loss > request.policy_authorized_max_loss_usd:
        return _failure(request, "VENUE_MINIMUM_EXCEEDS_POLICY_LOSS_BUDGET")
    if bounded_loss > request.remaining_catastrophic_loss_headroom_usd:
        return _failure(request, "VENUE_MINIMUM_EXCEEDS_CATASTROPHIC_LOSS_HEADROOM")
    if request.effective_leverage > request.catastrophic_max_leverage:
        return _failure(request, "LEVERAGE_EXCEEDS_CATASTROPHIC_CEILING")
    if required_margin > request.policy_authorized_max_margin_usd:
        return _failure(request, "VENUE_MINIMUM_EXCEEDS_POLICY_MARGIN_BUDGET")
    free_collateral = request.available_collateral_usd - request.reserved_margin_usd
    if required_margin > free_collateral:
        return _failure(request, "VENUE_MINIMUM_EXCEEDS_FREE_COLLATERAL")

    values = {
        "request": request,
        "decision": PROPOSE_TO_HARD_VALIDATOR,
        "venue_minimum_proposed": True,
        "final_notional_usd": final_notional,
        "final_quantity": final_quantity,
        "required_margin_usd": required_margin,
        "bounded_loss_with_cost_usd": bounded_loss,
        "reason": "EXACT_VENUE_MINIMUM_WITHIN_POLICY_AND_HARD_HEADROOM",
        "paper_only": True,
        "execution_authority": False,
        "requires_hard_validator": True,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "schema_version": SCHEMA_VERSION,
    }
    hash_material = dict(values)
    hash_material["request"] = asdict(request)
    return ExplorationSizeProposal(
        proposal_id=f"ves2_{_canonical_hash(hash_material)}",
        **values,
    )


__all__ = (
    "PROPOSE_TO_HARD_VALIDATOR",
    "SCHEMA_VERSION",
    "SELECT_ANOTHER",
    "ExplorationSizeProposal",
    "ExplorationSizingContractError",
    "ExplorationSizingRequestV2",
    "propose_exploration_size",
)
