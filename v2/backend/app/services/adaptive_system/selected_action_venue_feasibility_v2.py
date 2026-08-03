"""Physical feasibility attestation for an already-selected adaptive action.

This validator does not choose, resize, round, or repair a trading action.  It
only proves whether the exact policy-selected price, quantity-equivalent
notional, leverage, margin, and stop are executable within venue and operator
catastrophic constraints.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, localcontext

SCHEMA_VERSION = "selected_action_venue_feasibility_v2"
DECISION_EXECUTABLE = "SELECTED_ACTION_EXECUTABLE_UNCHANGED"
DECISION_BLOCK = "BLOCK_SELECTED_ACTION_UNEXECUTABLE"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ZERO = Decimal("0")


class SelectedActionVenueFeasibilityError(ValueError):
    pass


def _fail(reason: str, field: str) -> None:
    raise SelectedActionVenueFeasibilityError(f"{field}:{reason}")


def _identifier(value: object, field: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        _fail("identifier_required", field)


def _sha(value: object, field: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        _fail("lowercase_sha256_required", field)


def _positive(value: object, field: str, *, allow_zero: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        _fail("finite_Decimal_required", field)
    if value < _ZERO or (not allow_zero and value == _ZERO):
        _fail("nonnegative_required" if allow_zero else "positive_required", field)
    # A real tick-aligned stop divided by its entry price can be recurring.
    # The evaluator uses a fixed 120-digit context, so retain that deterministic
    # precision instead of rounding the bounded-loss proof before validation.
    if value.as_tuple().exponent < -256 or value.adjusted() > 24:
        _fail("precision_or_magnitude_out_of_bounds", field)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class SelectedActionVenueFeasibilityRequestV2:
    candidate_id: str
    policy_action_sha256: str
    venue_rules_receipt_sha256: str
    capital_snapshot_sha256: str
    catastrophic_envelope_receipt_sha256: str
    side: str
    selected_entry_price: Decimal
    selected_stop_price: Decimal
    selected_notional_usd: Decimal
    selected_leverage: Decimal
    selected_margin_usd: Decimal
    selected_round_trip_cost_bps: Decimal
    venue_price_tick: Decimal
    venue_min_notional_usd: Decimal
    venue_max_notional_usd: Decimal
    venue_min_qty: Decimal
    venue_max_qty: Decimal
    venue_qty_step: Decimal
    catastrophic_max_notional_usd: Decimal
    catastrophic_max_loss_usd: Decimal
    catastrophic_max_margin_usd: Decimal
    catastrophic_max_leverage: Decimal
    remaining_catastrophic_notional_headroom_usd: Decimal
    remaining_catastrophic_loss_headroom_usd: Decimal
    available_collateral_usd: Decimal
    reserved_margin_usd: Decimal
    paper_only: bool = True
    live_gate: str = "blocked_human_only"

    def __post_init__(self) -> None:
        _identifier(self.candidate_id, "candidate_id")
        for field in (
            "policy_action_sha256",
            "venue_rules_receipt_sha256",
            "capital_snapshot_sha256",
            "catastrophic_envelope_receipt_sha256",
        ):
            _sha(getattr(self, field), field)
        if self.side not in {"LONG", "SHORT"}:
            _fail("LONG_or_SHORT_required", "side")
        for field in (
            "selected_entry_price",
            "selected_stop_price",
            "selected_notional_usd",
            "selected_leverage",
            "selected_margin_usd",
            "venue_price_tick",
            "venue_min_notional_usd",
            "venue_max_notional_usd",
            "venue_min_qty",
            "venue_max_qty",
            "venue_qty_step",
            "catastrophic_max_notional_usd",
            "catastrophic_max_loss_usd",
            "catastrophic_max_margin_usd",
            "catastrophic_max_leverage",
            "remaining_catastrophic_notional_headroom_usd",
            "remaining_catastrophic_loss_headroom_usd",
            "available_collateral_usd",
        ):
            _positive(getattr(self, field), field)
        for field in ("selected_round_trip_cost_bps", "reserved_margin_usd"):
            _positive(getattr(self, field), field, allow_zero=True)
        if self.selected_round_trip_cost_bps > Decimal("10000"):
            _fail("must_not_exceed_10000_bps", "selected_round_trip_cost_bps")
        if self.venue_min_notional_usd > self.venue_max_notional_usd:
            _fail("minimum_exceeds_maximum", "venue_min_notional_usd")
        if self.venue_min_qty > self.venue_max_qty:
            _fail("minimum_exceeds_maximum", "venue_min_qty")
        if self.reserved_margin_usd > self.available_collateral_usd:
            _fail("exceeds_available_collateral", "reserved_margin_usd")
        if self.side == "LONG" and self.selected_stop_price >= self.selected_entry_price:
            _fail("long_stop_must_be_below_entry", "selected_stop_price")
        if self.side == "SHORT" and self.selected_stop_price <= self.selected_entry_price:
            _fail("short_stop_must_be_above_entry", "selected_stop_price")
        if self.paper_only is not True or self.live_gate != "blocked_human_only":
            _fail("paper_only_human_block_required", "safety")


@dataclass(frozen=True, slots=True)
class SelectedActionVenueFeasibilityV2:
    attestation_id: str
    request: SelectedActionVenueFeasibilityRequestV2
    decision: str
    failed_checks: tuple[str, ...]
    checks: tuple[tuple[str, bool], ...]
    exact_selected_quantity: Decimal
    exact_selected_notional_usd: Decimal
    exact_selected_margin_usd: Decimal
    exact_selected_bounded_loss_usd: Decimal
    selected_action_unchanged: bool
    policy_size_proposal: bool
    execution_authority: bool
    paper_only: bool
    live_gate: str
    routes_to_live: bool
    places_real_order: bool
    exchange_action_taken: bool
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            _fail("invalid_schema_version", "schema_version")
        if not isinstance(self.request, SelectedActionVenueFeasibilityRequestV2):
            _fail("structured_request_required", "request")
        _identifier(self.attestation_id, "attestation_id")
        if self.decision not in {DECISION_EXECUTABLE, DECISION_BLOCK}:
            _fail("invalid_decision", "decision")
        if self.checks != tuple(sorted(self.checks)) or len(dict(self.checks)) != len(self.checks):
            _fail("sorted_unique_checks_required", "checks")
        expected_failures = tuple(name for name, passed in self.checks if not passed)
        if self.failed_checks != expected_failures:
            _fail("must_match_failed_checks", "failed_checks")
        if (self.decision == DECISION_EXECUTABLE) is not (not self.failed_checks):
            _fail("must_match_checks", "decision")
        for field in (
            "exact_selected_quantity",
            "exact_selected_notional_usd",
            "exact_selected_margin_usd",
            "exact_selected_bounded_loss_usd",
        ):
            _positive(getattr(self, field), field)
        if self.selected_action_unchanged is not True or self.policy_size_proposal is not False:
            _fail("validator_cannot_change_or_propose_action", "authority")
        if self.execution_authority is not False:
            _fail("must_be_false", "execution_authority")
        if self.paper_only is not True or self.live_gate != "blocked_human_only":
            _fail("paper_only_human_block_required", "safety")
        if any((self.routes_to_live, self.places_real_order, self.exchange_action_taken)):
            _fail("no_live_or_exchange_authority", "safety")
        if self.attestation_id != self.expected_attestation_id:
            _fail("deterministic_identity_mismatch", "attestation_id")

    @property
    def expected_attestation_id(self) -> str:
        material = asdict(self)
        material.pop("attestation_id")
        return f"savf2_{_canonical_sha256(material)}"


def attest_selected_action_venue_feasibility(
    request: SelectedActionVenueFeasibilityRequestV2,
) -> SelectedActionVenueFeasibilityV2:
    """Attest the exact selection; never create a replacement selection."""

    if not isinstance(request, SelectedActionVenueFeasibilityRequestV2):
        raise TypeError("request must be SelectedActionVenueFeasibilityRequestV2")
    with localcontext() as context:
        context.prec = 120
        quantity = request.selected_notional_usd / request.selected_entry_price
        exact_notional = quantity * request.selected_entry_price
        exact_margin = request.selected_notional_usd / request.selected_leverage
        stop_fraction = abs(request.selected_entry_price - request.selected_stop_price) / (
            request.selected_entry_price
        )
        bounded_loss = request.selected_notional_usd * (
            stop_fraction + request.selected_round_trip_cost_bps / Decimal("10000")
        )
        free_collateral = request.available_collateral_usd - request.reserved_margin_usd
        checks = {
            "catastrophic_leverage": (
                request.selected_leverage <= request.catastrophic_max_leverage
            ),
            "catastrophic_loss": bounded_loss
            <= min(
                request.catastrophic_max_loss_usd,
                request.remaining_catastrophic_loss_headroom_usd,
            ),
            "catastrophic_margin": request.selected_margin_usd
            <= min(request.catastrophic_max_margin_usd, free_collateral),
            "catastrophic_notional": request.selected_notional_usd
            <= min(
                request.catastrophic_max_notional_usd,
                request.remaining_catastrophic_notional_headroom_usd,
            ),
            "entry_on_price_tick": request.selected_entry_price % request.venue_price_tick == _ZERO,
            "margin_arithmetic_exact": request.selected_margin_usd == exact_margin,
            "notional_arithmetic_exact": request.selected_notional_usd == exact_notional,
            "quantity_on_venue_step": quantity % request.venue_qty_step == _ZERO,
            "stop_on_price_tick": request.selected_stop_price % request.venue_price_tick == _ZERO,
            "venue_notional_range": request.venue_min_notional_usd
            <= request.selected_notional_usd
            <= request.venue_max_notional_usd,
            "venue_quantity_range": request.venue_min_qty <= quantity <= request.venue_max_qty,
        }
    ordered_checks = tuple(sorted(checks.items()))
    failed = tuple(name for name, passed in ordered_checks if not passed)
    values = {
        "request": request,
        "decision": DECISION_EXECUTABLE if not failed else DECISION_BLOCK,
        "failed_checks": failed,
        "checks": ordered_checks,
        "exact_selected_quantity": quantity,
        "exact_selected_notional_usd": exact_notional,
        "exact_selected_margin_usd": exact_margin,
        "exact_selected_bounded_loss_usd": bounded_loss,
        "selected_action_unchanged": True,
        "policy_size_proposal": False,
        "execution_authority": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "schema_version": SCHEMA_VERSION,
    }
    hash_values = dict(values)
    hash_values["request"] = asdict(request)
    return SelectedActionVenueFeasibilityV2(
        attestation_id=f"savf2_{_canonical_sha256(hash_values)}",
        **values,
    )


__all__ = (
    "DECISION_BLOCK",
    "DECISION_EXECUTABLE",
    "SelectedActionVenueFeasibilityError",
    "SelectedActionVenueFeasibilityRequestV2",
    "SelectedActionVenueFeasibilityV2",
    "attest_selected_action_venue_feasibility",
)
