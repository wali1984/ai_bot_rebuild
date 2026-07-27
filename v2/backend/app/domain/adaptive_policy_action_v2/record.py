from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, fields
from typing import Any

from .errors import AdaptivePolicyActionDomainError

ADAPTIVE_POLICY_ACTION_SCHEMA_VERSION = "AdaptivePolicyActionV2"

ACTION_DIRECTIONAL_TRADE = "directional_trade"
ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE = "market_neutral_or_hedged_trade"
ACTION_REDUCE_EXISTING_EXPOSURE = "reduce_existing_exposure"
ACTION_CLOSE_EXISTING_EXPOSURE = "close_existing_exposure"
ACTION_REMAIN_FLAT = "remain_flat"

POLICY_MODE_CHAMPION_EXPLOITATION = "champion_exploitation"
POLICY_MODE_BOUNDED_EXPLORATION = "bounded_information_seeking_exploration"
POLICY_MODE_POSITION_MANAGEMENT = "position_management"
POLICY_MODE_RISK_REDUCTION = "risk_reduction"

LIVE_GATE_BLOCKED_HUMAN_ONLY = "blocked_human_only"
UNIT_CONTRACT_USD_BPS_SECONDS_PROBABILITY = "USD_BPS_SECONDS_PROBABILITY_V1"

_ACTIONS = (
    ACTION_DIRECTIONAL_TRADE,
    ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE,
    ACTION_REDUCE_EXISTING_EXPOSURE,
    ACTION_CLOSE_EXISTING_EXPOSURE,
    ACTION_REMAIN_FLAT,
)
_ACTION_SET = frozenset(_ACTIONS)
_POLICY_MODES = frozenset(
    {
        POLICY_MODE_CHAMPION_EXPLOITATION,
        POLICY_MODE_BOUNDED_EXPLORATION,
        POLICY_MODE_POSITION_MANAGEMENT,
        POLICY_MODE_RISK_REDUCTION,
    }
)
_LEARNING_CONTINUATION_ACTIONS = frozenset(
    {
        "continue_champion_learning",
        "continue_position_management_learning",
        "evaluate_alternative_strategy_family",
        "expand_bounded_exploration",
        "label_and_evaluate_missed_opportunity",
        "mature_candidate_and_incremental_retrain",
        "promote_superior_challenger",
        "retrain_current_family",
    }
)
_PRIMARY_SIDES = frozenset({"long", "short", "flat", "hedged"})
_TRADE_SIDES = frozenset({"long", "short"})
_MARGIN_MODES = frozenset(
    {"isolated_paper_simulated", "cross_paper_simulated", "none"}
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PROBABILITY_SUM_TOLERANCE = 1e-9
_SEMANTIC_FINGERPRINT_EXCLUDED_FIELDS = frozenset(
    {
        "decision_id",
        "producer_generated_at_ms",
        "record_available_at_ms",
        "execution_time_ms",
    }
)


def _raise(reason: str, field: str) -> None:
    raise AdaptivePolicyActionDomainError(reason, field=field)


def _require_identifier(value: str, field: str, max_length: int = 160) -> None:
    if not isinstance(value, str):
        _raise("must_be_str", field)
    if not value:
        _raise("must_be_non_empty", field)
    if value.strip() != value or any(character.isspace() for character in value):
        _raise("must_not_have_whitespace", field)
    if len(value) > max_length:
        _raise(f"must_be_at_most_{max_length}_chars", field)


def _require_text(value: str, field: str, max_length: int = 512) -> None:
    if not isinstance(value, str):
        _raise("must_be_str", field)
    if not value.strip():
        _raise("must_be_non_blank", field)
    if value != value.strip():
        _raise("must_not_have_outer_whitespace", field)
    if len(value) > max_length:
        _raise(f"must_be_at_most_{max_length}_chars", field)


def _require_sha256(value: str, field: str) -> None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        _raise("must_be_lowercase_sha256", field)


def _require_int(value: int, field: str, *, minimum: int = 0) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        _raise("must_be_int", field)
    if value < minimum:
        _raise(f"must_be_at_least_{minimum}", field)


def _require_finite(value: float, field: str, *, minimum: float | None = None) -> None:
    if not isinstance(value, float) or isinstance(value, bool):
        _raise("must_be_float", field)
    if not math.isfinite(value):
        _raise("must_be_finite", field)
    if minimum is not None and value < minimum:
        _raise(f"must_be_at_least_{minimum}", field)


def _require_probability(value: float, field: str) -> None:
    _require_finite(value, field)
    if not 0.0 <= value <= 1.0:
        _raise("must_be_in_unit_interval", field)


def _require_stop_distance_matches_prices(
    *,
    reference_price: float,
    stop_price: float,
    stop_distance_bps: float,
    field: str,
) -> None:
    expected_distance_bps = abs(reference_price - stop_price) / reference_price * 10_000.0
    if not math.isclose(
        stop_distance_bps,
        expected_distance_bps,
        rel_tol=0.0,
        abs_tol=_PROBABILITY_SUM_TOLERANCE,
    ):
        _raise("must_equal_entry_to_stop_distance_bps", field)


def _require_exact_keys(
    value: object,
    expected: frozenset[str],
    field: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        _raise("must_be_object", field)
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        _raise(f"exact_keys_required:missing={missing}:extra={extra}", field)
    return value


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _raise("duplicate_json_key", key)
        result[key] = value
    return result


def _to_json_primitive(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {
            item.name: _to_json_primitive(getattr(value, item.name))
            for item in fields(value)
        }
    if isinstance(value, tuple | list):
        return [_to_json_primitive(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_json_primitive(item) for key, item in value.items()}
    return value


def _canonical_hash(material: Any, *, allow_nan: bool = False) -> str:
    try:
        encoded = json.dumps(
            _to_json_primitive(material),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=allow_nan,
        )
    except (TypeError, ValueError) as exc:
        raise AdaptivePolicyActionDomainError(
            "semantic_material_not_canonical_json",
            field="decision_id",
        ) from exc
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ActionProbabilityV2:
    action: str
    probability: float

    def __post_init__(self) -> None:
        if self.action not in _ACTION_SET:
            _raise("invalid_action", "action_distribution.action")
        _require_probability(self.probability, "action_distribution.probability")


@dataclass(frozen=True, slots=True)
class ReturnQuantileV2:
    probability: float
    return_bps: float

    def __post_init__(self) -> None:
        _require_probability(self.probability, "return_quantile.probability")
        if self.probability in {0.0, 1.0}:
            _raise("must_be_strictly_between_zero_and_one", "return_quantile.probability")
        _require_finite(self.return_bps, "return_quantile.return_bps")


@dataclass(frozen=True, slots=True)
class HorizonReturnDistributionV2:
    horizon_seconds: int
    expected_return_bps: float
    standard_deviation_bps: float
    quantiles: tuple[ReturnQuantileV2, ...]

    def __post_init__(self) -> None:
        _require_int(self.horizon_seconds, "return_distribution.horizon_seconds", minimum=1)
        _require_finite(self.expected_return_bps, "return_distribution.expected_return_bps")
        _require_finite(
            self.standard_deviation_bps,
            "return_distribution.standard_deviation_bps",
            minimum=0.0,
        )
        if type(self.quantiles) is not tuple or not self.quantiles:
            _raise("must_be_non_empty_tuple", "return_distribution.quantiles")
        for index, quantile in enumerate(self.quantiles):
            if not isinstance(quantile, ReturnQuantileV2):
                _raise(
                    "must_be_ReturnQuantileV2",
                    f"return_distribution.quantiles[{index}]",
                )
        probabilities = tuple(item.probability for item in self.quantiles)
        if probabilities != tuple(sorted(probabilities)):
            _raise("must_be_strictly_probability_ordered", "return_distribution.quantiles")
        if len(set(probabilities)) != len(probabilities):
            _raise("probabilities_must_be_unique", "return_distribution.quantiles")
        returns = tuple(item.return_bps for item in self.quantiles)
        if returns != tuple(sorted(returns)):
            _raise("returns_must_be_nondecreasing", "return_distribution.quantiles")


@dataclass(frozen=True, slots=True)
class EntryPolicyV2:
    active: bool
    style: str
    price_policy: str
    reference_price: float | None
    limit_price: float | None
    maximum_slippage_bps: float
    order_duration_policy: str
    duration_seconds: int
    post_only: bool

    def __post_init__(self) -> None:
        if not isinstance(self.active, bool) or not isinstance(self.post_only, bool):
            _raise("must_be_bool", "entry_policy")
        _require_text(self.style, "entry_policy.style")
        _require_text(self.price_policy, "entry_policy.price_policy")
        _require_text(self.order_duration_policy, "entry_policy.order_duration_policy")
        _require_finite(
            self.maximum_slippage_bps,
            "entry_policy.maximum_slippage_bps",
            minimum=0.0,
        )
        _require_int(self.duration_seconds, "entry_policy.duration_seconds")
        for field in ("reference_price", "limit_price"):
            value = getattr(self, field)
            if value is not None:
                _require_finite(value, f"entry_policy.{field}", minimum=0.0)
                if value == 0.0:
                    _raise("must_be_positive_or_none", f"entry_policy.{field}")
        if self.active:
            if self.reference_price is None or self.duration_seconds == 0:
                _raise("active_requires_reference_and_duration", "entry_policy")
        elif (
            self.style != "not_applicable"
            or self.price_policy != "not_applicable"
            or self.order_duration_policy != "not_applicable"
            or self.reference_price is not None
            or self.limit_price is not None
            or self.maximum_slippage_bps != 0.0
            or self.duration_seconds != 0
            or self.post_only
        ):
            _raise("inactive_requires_not_applicable_zero_state", "entry_policy")


@dataclass(frozen=True, slots=True)
class PartialReductionStepV2:
    trigger_return_bps: float
    fraction_of_open_quantity: float

    def __post_init__(self) -> None:
        _require_finite(self.trigger_return_bps, "partial_reduction.trigger_return_bps")
        _require_probability(
            self.fraction_of_open_quantity,
            "partial_reduction.fraction_of_open_quantity",
        )
        if self.fraction_of_open_quantity == 0.0:
            _raise("must_be_positive", "partial_reduction.fraction_of_open_quantity")


@dataclass(frozen=True, slots=True)
class ExitPolicyV2:
    active: bool
    protective_stop_policy: str
    stop_price: float | None
    stop_distance_bps: float
    partial_reduction_policy: str
    partial_reductions: tuple[PartialReductionStepV2, ...]
    profit_exit_policy: str
    profit_target_price: float | None
    time_exit_policy: str
    holding_horizon_seconds: int

    def __post_init__(self) -> None:
        if not isinstance(self.active, bool):
            _raise("must_be_bool", "exit_policy.active")
        for field in (
            "protective_stop_policy",
            "partial_reduction_policy",
            "profit_exit_policy",
            "time_exit_policy",
        ):
            _require_text(getattr(self, field), f"exit_policy.{field}")
        _require_finite(self.stop_distance_bps, "exit_policy.stop_distance_bps", minimum=0.0)
        _require_int(self.holding_horizon_seconds, "exit_policy.holding_horizon_seconds")
        for field in ("stop_price", "profit_target_price"):
            value = getattr(self, field)
            if value is not None:
                _require_finite(value, f"exit_policy.{field}", minimum=0.0)
                if value == 0.0:
                    _raise("must_be_positive_or_none", f"exit_policy.{field}")
        if type(self.partial_reductions) is not tuple:
            _raise("must_be_tuple", "exit_policy.partial_reductions")
        for index, step in enumerate(self.partial_reductions):
            if not isinstance(step, PartialReductionStepV2):
                _raise(
                    "must_be_PartialReductionStepV2",
                    f"exit_policy.partial_reductions[{index}]",
                )
        if math.fsum(step.fraction_of_open_quantity for step in self.partial_reductions) > 1.0:
            _raise("fractions_must_not_exceed_one", "exit_policy.partial_reductions")
        if self.active:
            if self.stop_price is None or self.stop_distance_bps == 0.0:
                _raise("active_requires_protective_stop", "exit_policy")
            if self.holding_horizon_seconds == 0:
                _raise("active_requires_positive_horizon", "exit_policy")
        elif (
            self.protective_stop_policy != "not_applicable"
            or self.partial_reduction_policy != "not_applicable"
            or self.profit_exit_policy != "not_applicable"
            or self.time_exit_policy != "not_applicable"
            or self.stop_price is not None
            or self.stop_distance_bps != 0.0
            or self.partial_reductions
            or self.profit_target_price is not None
            or self.holding_horizon_seconds != 0
        ):
            _raise("inactive_requires_not_applicable_zero_state", "exit_policy")


@dataclass(frozen=True, slots=True)
class ExpectedCostBreakdownV2:
    fee_bps: float
    spread_bps: float
    slippage_bps: float
    market_impact_bps: float
    funding_bps: float
    total_cost_bps: float

    def __post_init__(self) -> None:
        for field in ("fee_bps", "spread_bps", "slippage_bps", "market_impact_bps"):
            _require_finite(getattr(self, field), f"expected_cost_breakdown.{field}", minimum=0.0)
        _require_finite(self.funding_bps, "expected_cost_breakdown.funding_bps")
        _require_finite(self.total_cost_bps, "expected_cost_breakdown.total_cost_bps")
        expected_total = math.fsum(
            (
                self.fee_bps,
                self.spread_bps,
                self.slippage_bps,
                self.market_impact_bps,
                self.funding_bps,
            )
        )
        if not math.isclose(
            self.total_cost_bps,
            expected_total,
            rel_tol=0.0,
            abs_tol=_PROBABILITY_SUM_TOLERANCE,
        ):
            _raise("must_equal_component_sum", "expected_cost_breakdown.total_cost_bps")


@dataclass(frozen=True, slots=True)
class PositionAdjustmentV2:
    position_id: str
    current_exposure_usd: float
    target_exposure_usd: float
    reduction_notional_usd: float

    def __post_init__(self) -> None:
        _require_identifier(self.position_id, "position_adjustments.position_id", 160)
        _require_finite(self.current_exposure_usd, "position_adjustments.current_exposure_usd")
        _require_finite(self.target_exposure_usd, "position_adjustments.target_exposure_usd")
        _require_finite(
            self.reduction_notional_usd,
            "position_adjustments.reduction_notional_usd",
            minimum=0.0,
        )
        if self.current_exposure_usd == 0.0:
            _raise("current_exposure_must_be_nonzero", "position_adjustments.current_exposure_usd")
        if self.target_exposure_usd != 0.0 and math.copysign(
            1.0, self.target_exposure_usd
        ) != math.copysign(1.0, self.current_exposure_usd):
            _raise("target_must_not_flip_side", "position_adjustments.target_exposure_usd")
        if abs(self.target_exposure_usd) >= abs(self.current_exposure_usd):
            _raise("target_must_strictly_reduce", "position_adjustments.target_exposure_usd")
        expected_reduction = abs(self.current_exposure_usd) - abs(self.target_exposure_usd)
        if not math.isclose(
            self.reduction_notional_usd,
            expected_reduction,
            rel_tol=0.0,
            abs_tol=_PROBABILITY_SUM_TOLERANCE,
        ):
            _raise("must_equal_exposure_reduction", "position_adjustments.reduction_notional_usd")


@dataclass(frozen=True, slots=True)
class HedgeLegV2:
    leg_id: str
    symbol: str
    timeframe: str
    side: str
    target_exposure_usd: float
    target_notional_usd: float
    leverage: float
    margin_allocation_usd: float
    hedge_ratio: float
    entry_price_policy: str
    entry_policy: EntryPolicyV2
    protective_stop_policy: str
    stop_price: float
    exit_policy: ExitPolicyV2

    def __post_init__(self) -> None:
        _require_identifier(self.leg_id, "hedge_legs.leg_id", 128)
        _require_identifier(self.symbol, "hedge_legs.symbol", 32)
        if self.symbol != self.symbol.upper():
            _raise("must_be_uppercase", "hedge_legs.symbol")
        _require_identifier(self.timeframe, "hedge_legs.timeframe", 16)
        if self.side not in _TRADE_SIDES:
            _raise("must_be_long_or_short", "hedge_legs.side")
        _require_finite(self.target_exposure_usd, "hedge_legs.target_exposure_usd")
        if self.side == "long" and self.target_exposure_usd <= 0.0:
            _raise("long_requires_positive", "hedge_legs.target_exposure_usd")
        if self.side == "short" and self.target_exposure_usd >= 0.0:
            _raise("short_requires_negative", "hedge_legs.target_exposure_usd")
        _require_finite(
            self.target_notional_usd,
            "hedge_legs.target_notional_usd",
            minimum=0.0,
        )
        if not math.isclose(
            abs(self.target_exposure_usd),
            self.target_notional_usd,
            rel_tol=0.0,
            abs_tol=_PROBABILITY_SUM_TOLERANCE,
        ):
            _raise("absolute_exposure_must_equal_notional", "hedge_legs.target_exposure_usd")
        if self.target_notional_usd == 0.0:
            _raise("must_be_positive", "hedge_legs.target_notional_usd")
        _require_finite(self.leverage, "hedge_legs.leverage", minimum=0.0)
        if self.leverage == 0.0:
            _raise("must_be_positive", "hedge_legs.leverage")
        _require_finite(
            self.margin_allocation_usd,
            "hedge_legs.margin_allocation_usd",
            minimum=0.0,
        )
        if self.margin_allocation_usd == 0.0:
            _raise("must_be_positive", "hedge_legs.margin_allocation_usd")
        _require_finite(self.hedge_ratio, "hedge_legs.hedge_ratio", minimum=0.0)
        if self.hedge_ratio == 0.0:
            _raise("must_be_positive", "hedge_legs.hedge_ratio")
        _require_text(self.entry_price_policy, "hedge_legs.entry_price_policy")
        _require_text(self.protective_stop_policy, "hedge_legs.protective_stop_policy")
        _require_finite(self.stop_price, "hedge_legs.stop_price", minimum=0.0)
        if self.stop_price == 0.0:
            _raise("must_be_positive", "hedge_legs.stop_price")
        if not isinstance(self.entry_policy, EntryPolicyV2) or not self.entry_policy.active:
            _raise("requires_active_EntryPolicyV2", "hedge_legs.entry_policy")
        if not isinstance(self.exit_policy, ExitPolicyV2) or not self.exit_policy.active:
            _raise("requires_active_ExitPolicyV2", "hedge_legs.exit_policy")
        if self.entry_price_policy != self.entry_policy.price_policy:
            _raise("must_match_typed_entry_policy", "hedge_legs.entry_price_policy")
        if (
            self.protective_stop_policy != self.exit_policy.protective_stop_policy
            or self.stop_price != self.exit_policy.stop_price
        ):
            _raise("must_match_typed_exit_policy", "hedge_legs.protective_stop_policy")
        reference_price = self.entry_policy.reference_price
        if reference_price is None:
            _raise("reference_price_required", "hedge_legs.entry_policy")
        if self.side == "long" and self.stop_price >= reference_price:
            _raise("long_stop_must_be_below_entry", "hedge_legs.stop_price")
        if self.side == "short" and self.stop_price <= reference_price:
            _raise("short_stop_must_be_above_entry", "hedge_legs.stop_price")
        _require_stop_distance_matches_prices(
            reference_price=reference_price,
            stop_price=self.stop_price,
            stop_distance_bps=self.exit_policy.stop_distance_bps,
            field="hedge_legs.exit_policy.stop_distance_bps",
        )
        if not math.isclose(
            self.target_notional_usd / self.leverage,
            self.margin_allocation_usd,
            rel_tol=0.0,
            abs_tol=_PROBABILITY_SUM_TOLERANCE,
        ):
            _raise(
                "margin_must_equal_notional_divided_by_leverage",
                "hedge_legs.margin_allocation_usd",
            )


@dataclass(frozen=True, slots=True)
class AdaptivePolicyActionV2:
    decision_id: str
    state_id: str
    feature_snapshot_id: str
    checkpoint_generation: int
    checkpoint_id: str
    checkpoint_sha256: str
    feature_abi_sha256: str
    feature_builder_sha256: str
    policy_id: str
    policy_generation: int
    policy_mode: str
    policy_parameter_fingerprint: str
    calibration_sha256: str
    state_sha256: str
    source_receipt_sha256s: tuple[str, ...]
    selection_receipt_sha256: str
    state_event_time_ms: int
    state_ingested_at_ms: int
    source_available_at_ms: int
    feature_cutoff_ms: int
    producer_generated_at_ms: int
    record_available_at_ms: int
    decision_time_ms: int
    execution_time_ms: None
    latest_unclosed_kline_excluded: bool
    latest_unclosed_exclusion_method: str
    latest_unclosed_exclusion_decision_time_ms: int
    latest_closed_kline_close_time_ms: int

    primary_symbol: str
    primary_timeframe: str
    primary_side: str
    target_exposure_usd: float
    target_notional_usd: float
    leverage: float
    margin_mode_simulation: str
    margin_allocation_usd: float

    entry_style: str
    entry_price_policy: str
    maximum_entry_slippage: float
    order_duration_policy: str
    entry_policy: EntryPolicyV2

    protective_stop_policy: str
    stop_price: float | None
    stop_distance: float
    partial_reduction_policy: str
    profit_exit_policy: str
    time_exit_policy: str
    expected_holding_horizon: int
    exit_policy: ExitPolicyV2

    hedge_enabled: bool
    hedge_legs: tuple[HedgeLegV2, ...]
    hedge_ratios: tuple[float, ...]

    expected_before_cost_return: float
    expected_cost_breakdown: ExpectedCostBreakdownV2
    expected_after_cost_return: float
    expected_return_distribution: tuple[HorizonReturnDistributionV2, ...]
    policy_evaluation_horizon_seconds: int
    expected_drawdown_contribution: float
    expected_tail_loss: float
    expected_fill_probability: float
    expected_slippage: float
    expected_market_impact: float
    expected_adverse_selection: float
    expected_information_gain: float

    flat_probability: float
    selected_action: str
    action_distribution: tuple[ActionProbabilityV2, ...]
    policy_uncertainty: float
    decision_rationale_codes: tuple[str, ...]
    learning_continuation_action: str
    affected_position_ids: tuple[str, ...]
    position_adjustments: tuple[PositionAdjustmentV2, ...]
    reduce_only: bool

    operator_catastrophic_envelope_id: str
    operator_catastrophic_envelope_sha256: str
    integrity_evidence_sha256: str
    execution_domain: str
    policy_authority_scope: str
    requires_hard_validator: bool
    execution_authority: bool
    hard_validator_decision_id: None
    unit_contract: str
    paper_only: bool
    live_gate: str
    routes_to_live: bool
    places_real_order: bool
    exchange_action_taken: bool
    live_eligible: bool
    live_submission_ready: bool
    schema_version: str = ADAPTIVE_POLICY_ACTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self._validate_identity_and_time()
        self._validate_primary_action()
        self._validate_entry_exit_and_hedge()
        self._validate_estimates_and_distribution()
        self._validate_safety()
        self._validate_deterministic_identity()

    def _validate_identity_and_time(self) -> None:
        if self.schema_version != ADAPTIVE_POLICY_ACTION_SCHEMA_VERSION:
            _raise("invalid_schema_version", "schema_version")
        for field, value, length in (
            ("decision_id", self.decision_id, 160),
            ("state_id", self.state_id, 160),
            ("feature_snapshot_id", self.feature_snapshot_id, 160),
            ("checkpoint_id", self.checkpoint_id, 160),
            ("policy_id", self.policy_id, 160),
            ("primary_symbol", self.primary_symbol, 32),
            ("primary_timeframe", self.primary_timeframe, 16),
            (
                "operator_catastrophic_envelope_id",
                self.operator_catastrophic_envelope_id,
                160,
            ),
        ):
            _require_identifier(value, field, length)
        if self.primary_symbol != self.primary_symbol.upper():
            _raise("must_be_uppercase", "primary_symbol")
        _require_int(self.checkpoint_generation, "checkpoint_generation", minimum=1)
        _require_int(self.policy_generation, "policy_generation", minimum=1)
        if self.policy_mode not in _POLICY_MODES:
            _raise("invalid_policy_mode", "policy_mode")
        for field, value in (
            ("checkpoint_sha256", self.checkpoint_sha256),
            ("feature_abi_sha256", self.feature_abi_sha256),
            ("feature_builder_sha256", self.feature_builder_sha256),
            ("policy_parameter_fingerprint", self.policy_parameter_fingerprint),
            ("calibration_sha256", self.calibration_sha256),
            ("state_sha256", self.state_sha256),
            ("selection_receipt_sha256", self.selection_receipt_sha256),
            (
                "operator_catastrophic_envelope_sha256",
                self.operator_catastrophic_envelope_sha256,
            ),
            ("integrity_evidence_sha256", self.integrity_evidence_sha256),
        ):
            _require_sha256(value, field)
        if type(self.source_receipt_sha256s) is not tuple or not self.source_receipt_sha256s:
            _raise("must_be_non_empty_tuple", "source_receipt_sha256s")
        if len(set(self.source_receipt_sha256s)) != len(self.source_receipt_sha256s):
            _raise("must_be_unique", "source_receipt_sha256s")
        if self.source_receipt_sha256s != tuple(sorted(self.source_receipt_sha256s)):
            _raise("must_be_canonically_sorted", "source_receipt_sha256s")
        for index, receipt_sha in enumerate(self.source_receipt_sha256s):
            _require_sha256(receipt_sha, f"source_receipt_sha256s[{index}]")
        for field in (
            "state_event_time_ms",
            "state_ingested_at_ms",
            "source_available_at_ms",
            "feature_cutoff_ms",
            "producer_generated_at_ms",
            "record_available_at_ms",
            "decision_time_ms",
            "latest_unclosed_exclusion_decision_time_ms",
            "latest_closed_kline_close_time_ms",
        ):
            _require_int(getattr(self, field), field)
        if self.state_event_time_ms > self.state_ingested_at_ms:
            _raise("point_in_time_order_invalid", "state_ingested_at_ms")
        if self.state_event_time_ms > self.feature_cutoff_ms:
            _raise("point_in_time_order_invalid", "feature_cutoff_ms")
        if max(self.state_ingested_at_ms, self.feature_cutoff_ms) > self.source_available_at_ms:
            _raise("point_in_time_order_invalid", "source_available_at_ms")
        if self.source_available_at_ms > self.producer_generated_at_ms:
            _raise("point_in_time_order_invalid", "producer_generated_at_ms")
        if self.record_available_at_ms != max(
            self.source_available_at_ms, self.producer_generated_at_ms
        ):
            _raise("must_equal_effective_record_availability", "record_available_at_ms")
        if self.record_available_at_ms > self.decision_time_ms:
            _raise("point_in_time_order_invalid", "decision_time_ms")
        if self.execution_time_ms is not None:
            _raise("must_be_none_at_policy_stage", "execution_time_ms")
        if self.latest_unclosed_kline_excluded is not True:
            _raise("must_be_true", "latest_unclosed_kline_excluded")
        _require_text(
            self.latest_unclosed_exclusion_method,
            "latest_unclosed_exclusion_method",
        )
        if self.latest_unclosed_exclusion_decision_time_ms > self.decision_time_ms:
            _raise(
                "must_not_exceed_decision_time_ms",
                "latest_unclosed_exclusion_decision_time_ms",
            )
        if self.latest_closed_kline_close_time_ms > self.feature_cutoff_ms:
            _raise("must_not_exceed_feature_cutoff_ms", "latest_closed_kline_close_time_ms")

    def _validate_primary_action(self) -> None:
        if self.primary_side not in _PRIMARY_SIDES:
            _raise("invalid_primary_side", "primary_side")
        if self.margin_mode_simulation not in _MARGIN_MODES:
            _raise("invalid_margin_mode", "margin_mode_simulation")
        for field, value in (
            ("target_notional_usd", self.target_notional_usd),
            ("leverage", self.leverage),
            ("margin_allocation_usd", self.margin_allocation_usd),
        ):
            _require_finite(value, field, minimum=0.0)
        _require_finite(self.target_exposure_usd, "target_exposure_usd")
        if self.selected_action not in _ACTION_SET:
            _raise("invalid_selected_action", "selected_action")

        if self.selected_action == ACTION_DIRECTIONAL_TRADE:
            if self.primary_side not in _TRADE_SIDES:
                _raise("directional_trade_requires_long_or_short", "primary_side")
            if self.primary_side == "long" and self.target_exposure_usd <= 0.0:
                _raise("long_requires_positive", "target_exposure_usd")
            if self.primary_side == "short" and self.target_exposure_usd >= 0.0:
                _raise("short_requires_negative", "target_exposure_usd")
            if not math.isclose(
                abs(self.target_exposure_usd),
                self.target_notional_usd,
                rel_tol=0.0,
                abs_tol=_PROBABILITY_SUM_TOLERANCE,
            ):
                _raise("absolute_exposure_must_equal_notional", "target_exposure_usd")
            self._require_positive_new_exposure()
        elif self.selected_action == ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE:
            if self.primary_side not in _TRADE_SIDES:
                _raise("hedged_trade_requires_primary_long_or_short", "primary_side")
            if not self.hedge_enabled or not self.hedge_legs:
                _raise("hedged_trade_requires_enabled_hedge", "hedge_enabled")
            if self.primary_side == "long" and self.target_exposure_usd <= 0.0:
                _raise("long_requires_positive", "target_exposure_usd")
            if self.primary_side == "short" and self.target_exposure_usd >= 0.0:
                _raise("short_requires_negative", "target_exposure_usd")
            if not math.isclose(
                abs(self.target_exposure_usd),
                self.target_notional_usd,
                rel_tol=0.0,
                abs_tol=_PROBABILITY_SUM_TOLERANCE,
            ):
                _raise("absolute_exposure_must_equal_notional", "target_exposure_usd")
            self._require_positive_new_exposure()
        elif self.selected_action == ACTION_REMAIN_FLAT:
            if self.primary_side != "flat":
                _raise("remain_flat_requires_flat_side", "primary_side")
            for field in (
                "target_exposure_usd",
                "target_notional_usd",
                "leverage",
                "margin_allocation_usd",
            ):
                if getattr(self, field) != 0.0:
                    _raise("remain_flat_requires_zero", field)
            if self.margin_mode_simulation != "none":
                _raise("remain_flat_requires_none", "margin_mode_simulation")

    def _require_positive_new_exposure(self) -> None:
        for field in (
            "target_exposure_usd",
            "target_notional_usd",
            "leverage",
            "margin_allocation_usd",
        ):
            if getattr(self, field) == 0.0:
                _raise("new_exposure_requires_positive", field)
        if self.margin_mode_simulation == "none":
            _raise("new_exposure_requires_margin_mode", "margin_mode_simulation")
        if not math.isclose(
            self.target_notional_usd / self.leverage,
            self.margin_allocation_usd,
            rel_tol=0.0,
            abs_tol=_PROBABILITY_SUM_TOLERANCE,
        ):
            _raise("margin_must_equal_notional_divided_by_leverage", "margin_allocation_usd")

    def _validate_entry_exit_and_hedge(self) -> None:
        for field in (
            "entry_style",
            "entry_price_policy",
            "order_duration_policy",
            "protective_stop_policy",
            "partial_reduction_policy",
            "profit_exit_policy",
            "time_exit_policy",
        ):
            _require_text(getattr(self, field), field)
        _require_finite(self.maximum_entry_slippage, "maximum_entry_slippage", minimum=0.0)
        _require_finite(self.stop_distance, "stop_distance", minimum=0.0)
        _require_int(self.expected_holding_horizon, "expected_holding_horizon")
        if not isinstance(self.entry_policy, EntryPolicyV2):
            _raise("must_be_EntryPolicyV2", "entry_policy")
        if not isinstance(self.exit_policy, ExitPolicyV2):
            _raise("must_be_ExitPolicyV2", "exit_policy")
        if (
            self.entry_style != self.entry_policy.style
            or self.entry_price_policy != self.entry_policy.price_policy
            or self.maximum_entry_slippage != self.entry_policy.maximum_slippage_bps
            or self.order_duration_policy != self.entry_policy.order_duration_policy
        ):
            _raise("top_level_fields_must_match_typed_policy", "entry_policy")
        if (
            self.protective_stop_policy != self.exit_policy.protective_stop_policy
            or self.stop_price != self.exit_policy.stop_price
            or self.stop_distance != self.exit_policy.stop_distance_bps
            or self.partial_reduction_policy != self.exit_policy.partial_reduction_policy
            or self.profit_exit_policy != self.exit_policy.profit_exit_policy
            or self.time_exit_policy != self.exit_policy.time_exit_policy
            or self.expected_holding_horizon != self.exit_policy.holding_horizon_seconds
        ):
            _raise("top_level_fields_must_match_typed_policy", "exit_policy")
        if self.stop_price is not None:
            _require_finite(self.stop_price, "stop_price", minimum=0.0)
            if self.stop_price == 0.0:
                _raise("must_be_positive_or_none", "stop_price")

        opens_exposure = self.selected_action in {
            ACTION_DIRECTIONAL_TRADE,
            ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE,
        }
        if opens_exposure and not self.entry_policy.active:
            _raise("new_exposure_requires_active_entry_policy", "entry_policy")
        if opens_exposure and not self.exit_policy.active:
            _raise("new_exposure_requires_active_exit_policy", "exit_policy")
        if opens_exposure:
            reference_price = self.entry_policy.reference_price
            if reference_price is None or self.stop_price is None:
                _raise("new_exposure_requires_entry_and_stop_prices", "entry_policy")
            if self.primary_side == "long" and self.stop_price >= reference_price:
                _raise("long_stop_must_be_below_entry", "stop_price")
            if self.primary_side == "short" and self.stop_price <= reference_price:
                _raise("short_stop_must_be_above_entry", "stop_price")
            _require_stop_distance_matches_prices(
                reference_price=reference_price,
                stop_price=self.stop_price,
                stop_distance_bps=self.stop_distance,
                field="stop_distance",
            )
            profit_price = self.exit_policy.profit_target_price
            if profit_price is not None:
                if self.primary_side == "long" and profit_price <= reference_price:
                    _raise("long_profit_target_must_be_above_entry", "exit_policy")
                if self.primary_side == "short" and profit_price >= reference_price:
                    _raise("short_profit_target_must_be_below_entry", "exit_policy")
        if opens_exposure and (self.stop_price is None or self.stop_distance == 0.0):
            _raise("new_exposure_requires_protective_stop", "protective_stop_policy")
        if self.selected_action == ACTION_REMAIN_FLAT:
            if self.stop_price is not None or self.stop_distance != 0.0:
                _raise("remain_flat_requires_no_stop", "stop_price")
            if self.expected_holding_horizon != 0:
                _raise("remain_flat_requires_zero", "expected_holding_horizon")
            if self.entry_policy.active or self.exit_policy.active:
                _raise("remain_flat_requires_inactive_policies", "selected_action")

        if not isinstance(self.hedge_enabled, bool):
            _raise("must_be_bool", "hedge_enabled")
        if type(self.hedge_legs) is not tuple:
            _raise("must_be_tuple", "hedge_legs")
        if type(self.hedge_ratios) is not tuple:
            _raise("must_be_tuple", "hedge_ratios")
        if self.hedge_enabled:
            if not self.hedge_legs:
                _raise("enabled_requires_legs", "hedge_legs")
            if len(self.hedge_ratios) != len(self.hedge_legs):
                _raise("must_match_hedge_legs_length", "hedge_ratios")
            if self.selected_action != ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE:
                _raise("enabled_requires_hedged_selected_action", "hedge_enabled")
        elif self.hedge_legs or self.hedge_ratios:
            _raise("disabled_requires_empty_legs_and_ratios", "hedge_enabled")
        for index, ratio in enumerate(self.hedge_ratios):
            if not isinstance(self.hedge_legs[index], HedgeLegV2):
                _raise("must_be_HedgeLegV2", f"hedge_legs[{index}]")
            _require_finite(ratio, f"hedge_ratios[{index}]", minimum=0.0)
            if ratio == 0.0:
                _raise("must_be_positive", f"hedge_ratios[{index}]")
            if ratio != self.hedge_legs[index].hedge_ratio:
                _raise("must_match_leg_hedge_ratio", f"hedge_ratios[{index}]")
            expected_ratio = self.hedge_legs[index].target_notional_usd / self.target_notional_usd
            if not math.isclose(
                ratio,
                expected_ratio,
                rel_tol=0.0,
                abs_tol=_PROBABILITY_SUM_TOLERANCE,
            ):
                _raise("must_equal_leg_to_primary_notional_ratio", f"hedge_ratios[{index}]")
        hedge_symbols = tuple(leg.symbol for leg in self.hedge_legs)
        hedge_leg_ids = tuple(leg.leg_id for leg in self.hedge_legs)
        if len(set(hedge_leg_ids)) != len(hedge_leg_ids):
            _raise("leg_ids_must_be_unique", "hedge_legs")
        if hedge_leg_ids != tuple(sorted(hedge_leg_ids)):
            _raise("leg_ids_must_be_canonically_sorted", "hedge_legs")
        if len(set(hedge_symbols)) != len(hedge_symbols):
            _raise("symbols_must_be_unique", "hedge_legs")
        if self.primary_symbol in set(hedge_symbols):
            _raise("must_not_duplicate_primary_symbol", "hedge_legs")

    def _validate_estimates_and_distribution(self) -> None:
        _require_finite(self.expected_before_cost_return, "expected_before_cost_return")
        if not isinstance(self.expected_cost_breakdown, ExpectedCostBreakdownV2):
            _raise("must_be_ExpectedCostBreakdownV2", "expected_cost_breakdown")
        _require_finite(self.expected_after_cost_return, "expected_after_cost_return")
        if not math.isclose(
            self.expected_before_cost_return - self.expected_cost_breakdown.total_cost_bps,
            self.expected_after_cost_return,
            rel_tol=0.0,
            abs_tol=_PROBABILITY_SUM_TOLERANCE,
        ):
            _raise("before_cost_minus_total_must_equal_after_cost", "expected_after_cost_return")
        if self.expected_slippage != self.expected_cost_breakdown.slippage_bps:
            _raise("must_match_cost_breakdown", "expected_slippage")
        if self.expected_market_impact != self.expected_cost_breakdown.market_impact_bps:
            _raise("must_match_cost_breakdown", "expected_market_impact")
        for field in (
            "expected_drawdown_contribution",
            "expected_tail_loss",
            "expected_slippage",
            "expected_market_impact",
            "expected_information_gain",
        ):
            _require_finite(getattr(self, field), field, minimum=0.0)
        for field in (
            "expected_fill_probability",
            "expected_adverse_selection",
            "flat_probability",
            "policy_uncertainty",
        ):
            _require_probability(getattr(self, field), field)
        if (
            type(self.expected_return_distribution) is not tuple
            or not self.expected_return_distribution
        ):
            _raise("must_be_non_empty_tuple", "expected_return_distribution")
        for index, item in enumerate(self.expected_return_distribution):
            if not isinstance(item, HorizonReturnDistributionV2):
                _raise(
                    "must_be_HorizonReturnDistributionV2",
                    f"expected_return_distribution[{index}]",
                )
        horizons = tuple(item.horizon_seconds for item in self.expected_return_distribution)
        if len(set(horizons)) != len(horizons):
            _raise("horizons_must_be_unique", "expected_return_distribution")
        if horizons != tuple(sorted(horizons)):
            _raise("horizons_must_be_ascending", "expected_return_distribution")
        _require_int(
            self.policy_evaluation_horizon_seconds,
            "policy_evaluation_horizon_seconds",
            minimum=1,
        )
        if self.policy_evaluation_horizon_seconds not in set(horizons):
            _raise(
                "must_match_a_return_distribution_horizon",
                "policy_evaluation_horizon_seconds",
            )
        opens_exposure = self.selected_action in {
            ACTION_DIRECTIONAL_TRADE,
            ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE,
        }
        if (
            opens_exposure
            and self.policy_evaluation_horizon_seconds != self.expected_holding_horizon
        ):
            _raise(
                "must_equal_expected_holding_horizon_for_new_exposure",
                "policy_evaluation_horizon_seconds",
            )
        selected_distribution = next(
            item
            for item in self.expected_return_distribution
            if item.horizon_seconds == self.policy_evaluation_horizon_seconds
        )
        if not math.isclose(
            selected_distribution.expected_return_bps,
            self.expected_after_cost_return,
            rel_tol=0.0,
            abs_tol=_PROBABILITY_SUM_TOLERANCE,
        ):
            _raise(
                "must_equal_selected_after_cost_distribution_mean",
                "expected_after_cost_return",
            )

        if type(self.action_distribution) is not tuple:
            _raise("must_be_tuple", "action_distribution")
        for index, item in enumerate(self.action_distribution):
            if not isinstance(item, ActionProbabilityV2):
                _raise("must_be_ActionProbabilityV2", f"action_distribution[{index}]")
        actions = tuple(item.action for item in self.action_distribution)
        if len(actions) != len(_ACTIONS) or frozenset(actions) != _ACTION_SET:
            _raise("must_cover_each_schema_action_exactly_once", "action_distribution")
        if len(set(actions)) != len(actions):
            _raise("actions_must_be_unique", "action_distribution")
        if actions != _ACTIONS:
            _raise("must_use_canonical_action_order", "action_distribution")
        probability_by_action = {
            item.action: item.probability for item in self.action_distribution
        }
        if not math.isclose(
            math.fsum(probability_by_action.values()),
            1.0,
            rel_tol=0.0,
            abs_tol=_PROBABILITY_SUM_TOLERANCE,
        ):
            _raise("probabilities_must_sum_to_one", "action_distribution")
        if probability_by_action[self.selected_action] == 0.0:
            _raise("selected_action_probability_must_be_positive", "selected_action")
        if not math.isclose(
            self.flat_probability,
            probability_by_action[ACTION_REMAIN_FLAT],
            rel_tol=0.0,
            abs_tol=_PROBABILITY_SUM_TOLERANCE,
        ):
            _raise("must_equal_remain_flat_probability", "flat_probability")
        if type(self.decision_rationale_codes) is not tuple or not self.decision_rationale_codes:
            _raise("must_be_non_empty_tuple", "decision_rationale_codes")
        seen: set[str] = set()
        for code in self.decision_rationale_codes:
            _require_identifier(code, "decision_rationale_codes", 96)
            if code in seen:
                _raise("must_be_unique", "decision_rationale_codes")
            seen.add(code)
        _require_text(self.learning_continuation_action, "learning_continuation_action")
        if self.learning_continuation_action not in _LEARNING_CONTINUATION_ACTIONS:
            _raise("must_be_nonterminal_declared_learning_action", "learning_continuation_action")
        if type(self.affected_position_ids) is not tuple:
            _raise("must_be_tuple", "affected_position_ids")
        if len(set(self.affected_position_ids)) != len(self.affected_position_ids):
            _raise("must_be_unique", "affected_position_ids")
        if self.affected_position_ids != tuple(sorted(self.affected_position_ids)):
            _raise("must_be_canonically_sorted", "affected_position_ids")
        for position_id in self.affected_position_ids:
            _require_identifier(position_id, "affected_position_ids", 160)
        if type(self.position_adjustments) is not tuple:
            _raise("must_be_tuple", "position_adjustments")
        for index, adjustment in enumerate(self.position_adjustments):
            if not isinstance(adjustment, PositionAdjustmentV2):
                _raise(
                    "must_be_PositionAdjustmentV2",
                    f"position_adjustments[{index}]",
                )
        adjustment_ids = tuple(item.position_id for item in self.position_adjustments)
        if adjustment_ids != self.affected_position_ids:
            _raise("must_match_position_adjustment_ids", "affected_position_ids")
        if not isinstance(self.reduce_only, bool):
            _raise("must_be_bool", "reduce_only")
        manages_existing = self.selected_action in {
            ACTION_REDUCE_EXISTING_EXPOSURE,
            ACTION_CLOSE_EXISTING_EXPOSURE,
        }
        if manages_existing and (
            not self.reduce_only
            or not self.affected_position_ids
            or not self.position_adjustments
        ):
            _raise("existing_exposure_action_requires_reduce_only_lineage", "reduce_only")
        if not manages_existing and (
            self.reduce_only or self.affected_position_ids or self.position_adjustments
        ):
            _raise("new_or_flat_action_forbids_position_lineage", "reduce_only")
        if self.selected_action == ACTION_CLOSE_EXISTING_EXPOSURE:
            if any(item.target_exposure_usd != 0.0 for item in self.position_adjustments):
                _raise("close_requires_zero_position_targets", "position_adjustments")
            for field in (
                "target_exposure_usd",
                "target_notional_usd",
                "leverage",
                "margin_allocation_usd",
            ):
                if getattr(self, field) != 0.0:
                    _raise("close_requires_zero", field)
            if self.entry_policy.active or self.exit_policy.active:
                _raise("close_requires_inactive_policies", "selected_action")
        if self.selected_action == ACTION_REDUCE_EXISTING_EXPOSURE:
            if any(item.target_exposure_usd == 0.0 for item in self.position_adjustments):
                _raise("reduce_requires_nonzero_residual_target", "position_adjustments")
            residual_exposure = math.fsum(
                item.target_exposure_usd for item in self.position_adjustments
            )
            residual_notional = math.fsum(
                abs(item.target_exposure_usd) for item in self.position_adjustments
            )
            if not math.isclose(
                self.target_exposure_usd,
                residual_exposure,
                rel_tol=0.0,
                abs_tol=_PROBABILITY_SUM_TOLERANCE,
            ) or not math.isclose(
                self.target_notional_usd,
                residual_notional,
                rel_tol=0.0,
                abs_tol=_PROBABILITY_SUM_TOLERANCE,
            ):
                _raise("reduce_target_must_equal_residual_positions", "position_adjustments")
            if self.entry_policy.active or not self.exit_policy.active:
                _raise("reduce_requires_inactive_entry_active_exit", "selected_action")

    def _validate_safety(self) -> None:
        for field in (
            "paper_only",
            "routes_to_live",
            "places_real_order",
            "exchange_action_taken",
            "live_eligible",
            "live_submission_ready",
            "requires_hard_validator",
            "execution_authority",
        ):
            if not isinstance(getattr(self, field), bool):
                _raise("must_be_bool", field)
        if self.paper_only is not True:
            _raise("must_be_true", "paper_only")
        if self.execution_domain != "PAPER":
            _raise("must_be_paper", "execution_domain")
        if self.unit_contract != UNIT_CONTRACT_USD_BPS_SECONDS_PROBABILITY:
            _raise("invalid_unit_contract", "unit_contract")
        if self.policy_authority_scope != "trading_action_only":
            _raise("must_be_trading_action_only", "policy_authority_scope")
        if self.requires_hard_validator is not True:
            _raise("must_be_true", "requires_hard_validator")
        if self.execution_authority is not False:
            _raise("must_be_false", "execution_authority")
        if self.hard_validator_decision_id is not None:
            _raise("must_be_none_at_policy_stage", "hard_validator_decision_id")
        if self.live_gate != LIVE_GATE_BLOCKED_HUMAN_ONLY:
            _raise("must_be_blocked_human_only", "live_gate")
        for field in (
            "routes_to_live",
            "places_real_order",
            "exchange_action_taken",
            "live_eligible",
            "live_submission_ready",
        ):
            if getattr(self, field) is not False:
                _raise("must_be_false", field)

    def _semantic_payload(self) -> dict[str, Any]:
        return {
            item.name: _to_json_primitive(getattr(self, item.name))
            for item in fields(self)
            if item.name not in _SEMANTIC_FINGERPRINT_EXCLUDED_FIELDS
        }

    @property
    def action_fingerprint_sha256(self) -> str:
        return _canonical_hash(self._semantic_payload())

    @property
    def expected_decision_id(self) -> str:
        material = {
            "schema_version": self.schema_version,
            "state_id": self.state_id,
            "checkpoint_generation": self.checkpoint_generation,
            "policy_id": self.policy_id,
            "decision_time_ms": self.decision_time_ms,
            "selection_receipt_sha256": self.selection_receipt_sha256,
            "action_fingerprint_sha256": self.action_fingerprint_sha256,
        }
        return f"apa2_{_canonical_hash(material)}"

    def _validate_deterministic_identity(self) -> None:
        if self.decision_id != self.expected_decision_id:
            _raise("must_match_deterministic_identity", "decision_id")

    @classmethod
    def create(cls, **values: Any) -> AdaptivePolicyActionV2:
        """Create an action with deterministic semantic identity."""

        if "decision_id" in values or "action_fingerprint_sha256" in values:
            _raise("must_be_derived", "decision_id")
        material = dict(values)
        material.setdefault("schema_version", ADAPTIVE_POLICY_ACTION_SCHEMA_VERSION)
        expected_keys = frozenset(item.name for item in fields(cls)) - {"decision_id"}
        _require_exact_keys(material, expected_keys, "create")
        semantic = {
            name: _to_json_primitive(material[name])
            for name in expected_keys
            if name not in _SEMANTIC_FINGERPRINT_EXCLUDED_FIELDS
        }
        action_fingerprint = _canonical_hash(semantic, allow_nan=True)
        identity = {
            "schema_version": material["schema_version"],
            "state_id": material["state_id"],
            "checkpoint_generation": material["checkpoint_generation"],
            "policy_id": material["policy_id"],
            "decision_time_ms": material["decision_time_ms"],
            "selection_receipt_sha256": material["selection_receipt_sha256"],
            "action_fingerprint_sha256": action_fingerprint,
        }
        decision_id = f"apa2_{_canonical_hash(identity, allow_nan=True)}"
        return cls(decision_id=decision_id, **material)

    def to_payload(self) -> dict[str, Any]:
        """Return the deterministic transport payload for hashing and storage."""

        raw = asdict(self)
        raw["entry_policy"] = asdict(self.entry_policy)
        raw["exit_policy"] = {
            **asdict(self.exit_policy),
            "partial_reductions": [
                asdict(item) for item in self.exit_policy.partial_reductions
            ],
        }
        raw["expected_cost_breakdown"] = asdict(self.expected_cost_breakdown)
        raw["position_adjustments"] = [
            asdict(item) for item in self.position_adjustments
        ]
        raw["action_distribution"] = {
            item.action: item.probability
            for item in sorted(self.action_distribution, key=lambda item: item.action)
        }
        raw["hedge_legs"] = [asdict(item) for item in self.hedge_legs]
        raw["hedge_ratios"] = list(self.hedge_ratios)
        raw["source_receipt_sha256s"] = list(self.source_receipt_sha256s)
        raw["expected_return_distribution"] = [
            {
                "horizon_seconds": item.horizon_seconds,
                "expected_return_bps": item.expected_return_bps,
                "standard_deviation_bps": item.standard_deviation_bps,
                "quantiles": [asdict(quantile) for quantile in item.quantiles],
            }
            for item in self.expected_return_distribution
        ]
        raw["decision_rationale_codes"] = list(self.decision_rationale_codes)
        raw["affected_position_ids"] = list(self.affected_position_ids)
        raw["action_fingerprint_sha256"] = self.action_fingerprint_sha256
        return raw

    def canonical_json(self) -> str:
        return json.dumps(
            self.to_payload(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @classmethod
    def from_payload(cls, payload: object) -> AdaptivePolicyActionV2:
        """Strictly parse a stored payload without ignoring unknown fields."""

        expected_top_level = frozenset(item.name for item in fields(cls)) | {
            "action_fingerprint_sha256"
        }
        raw = dict(_require_exact_keys(payload, expected_top_level, "payload"))
        stored_action_fingerprint = raw.pop("action_fingerprint_sha256")
        _require_sha256(stored_action_fingerprint, "action_fingerprint_sha256")

        entry_keys = frozenset(item.name for item in fields(EntryPolicyV2))
        raw["entry_policy"] = EntryPolicyV2(
            **_require_exact_keys(raw["entry_policy"], entry_keys, "entry_policy")
        )
        exit_keys = frozenset(item.name for item in fields(ExitPolicyV2))
        partial_keys = frozenset(item.name for item in fields(PartialReductionStepV2))
        raw_exit = dict(_require_exact_keys(raw["exit_policy"], exit_keys, "exit_policy"))
        raw_partial = raw_exit["partial_reductions"]
        if not isinstance(raw_partial, list):
            _raise("must_be_list", "exit_policy.partial_reductions")
        raw_exit["partial_reductions"] = tuple(
            PartialReductionStepV2(
                **_require_exact_keys(
                    item,
                    partial_keys,
                    f"exit_policy.partial_reductions[{index}]",
                )
            )
            for index, item in enumerate(raw_partial)
        )
        raw["exit_policy"] = ExitPolicyV2(**raw_exit)

        cost_keys = frozenset(item.name for item in fields(ExpectedCostBreakdownV2))
        raw["expected_cost_breakdown"] = ExpectedCostBreakdownV2(
            **_require_exact_keys(
                raw["expected_cost_breakdown"],
                cost_keys,
                "expected_cost_breakdown",
            )
        )
        adjustment_keys = frozenset(item.name for item in fields(PositionAdjustmentV2))
        raw_adjustments = raw["position_adjustments"]
        if not isinstance(raw_adjustments, list):
            _raise("must_be_list", "position_adjustments")
        raw["position_adjustments"] = tuple(
            PositionAdjustmentV2(
                **_require_exact_keys(
                    item,
                    adjustment_keys,
                    f"position_adjustments[{index}]",
                )
            )
            for index, item in enumerate(raw_adjustments)
        )

        action_map = _require_exact_keys(
            raw["action_distribution"],
            _ACTION_SET,
            "action_distribution",
        )
        raw["action_distribution"] = tuple(
            ActionProbabilityV2(action, action_map[action]) for action in _ACTIONS
        )

        hedge_leg_keys = frozenset(item.name for item in fields(HedgeLegV2))
        raw_legs = raw["hedge_legs"]
        if not isinstance(raw_legs, list):
            _raise("must_be_list", "hedge_legs")
        parsed_legs: list[HedgeLegV2] = []
        for index, item in enumerate(raw_legs):
            leg = dict(
                _require_exact_keys(item, hedge_leg_keys, f"hedge_legs[{index}]")
            )
            leg["entry_policy"] = EntryPolicyV2(
                **_require_exact_keys(
                    leg["entry_policy"],
                    entry_keys,
                    f"hedge_legs[{index}].entry_policy",
                )
            )
            leg_exit = dict(
                _require_exact_keys(
                    leg["exit_policy"],
                    exit_keys,
                    f"hedge_legs[{index}].exit_policy",
                )
            )
            leg_partial = leg_exit["partial_reductions"]
            if not isinstance(leg_partial, list):
                _raise("must_be_list", f"hedge_legs[{index}].exit_policy.partial_reductions")
            leg_exit["partial_reductions"] = tuple(
                PartialReductionStepV2(
                    **_require_exact_keys(
                        step,
                        partial_keys,
                        f"hedge_legs[{index}].exit_policy.partial_reductions[{step_index}]",
                    )
                )
                for step_index, step in enumerate(leg_partial)
            )
            leg["exit_policy"] = ExitPolicyV2(**leg_exit)
            parsed_legs.append(HedgeLegV2(**leg))
        raw["hedge_legs"] = tuple(parsed_legs)

        distribution_keys = frozenset(item.name for item in fields(HorizonReturnDistributionV2))
        quantile_keys = frozenset(item.name for item in fields(ReturnQuantileV2))
        raw_distributions = raw["expected_return_distribution"]
        if not isinstance(raw_distributions, list):
            _raise("must_be_list", "expected_return_distribution")
        parsed_distributions: list[HorizonReturnDistributionV2] = []
        for index, item in enumerate(raw_distributions):
            distribution = dict(
                _require_exact_keys(
                    item,
                    distribution_keys,
                    f"expected_return_distribution[{index}]",
                )
            )
            raw_quantiles = distribution["quantiles"]
            if not isinstance(raw_quantiles, list):
                _raise(
                    "must_be_list",
                    f"expected_return_distribution[{index}].quantiles",
                )
            distribution["quantiles"] = tuple(
                ReturnQuantileV2(
                    **_require_exact_keys(
                        quantile,
                        quantile_keys,
                        f"expected_return_distribution[{index}].quantiles[{q_index}]",
                    )
                )
                for q_index, quantile in enumerate(raw_quantiles)
            )
            parsed_distributions.append(HorizonReturnDistributionV2(**distribution))
        raw["expected_return_distribution"] = tuple(parsed_distributions)

        for field in (
            "source_receipt_sha256s",
            "hedge_ratios",
            "decision_rationale_codes",
            "affected_position_ids",
        ):
            value = raw[field]
            if not isinstance(value, list):
                _raise("must_be_list", field)
            raw[field] = tuple(value)
        action = cls(**raw)
        if stored_action_fingerprint != action.action_fingerprint_sha256:
            _raise("must_match_semantic_payload", "action_fingerprint_sha256")
        return action

    @classmethod
    def from_json(cls, encoded: str) -> AdaptivePolicyActionV2:
        if not isinstance(encoded, str):
            _raise("must_be_str", "encoded")
        try:
            payload = json.loads(encoded, object_pairs_hook=_reject_duplicate_json_keys)
        except AdaptivePolicyActionDomainError:
            raise
        except (json.JSONDecodeError, ValueError) as exc:
            raise AdaptivePolicyActionDomainError("invalid_json", field="encoded") from exc
        return cls.from_payload(payload)

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


__all__ = (
    "ACTION_CLOSE_EXISTING_EXPOSURE",
    "ACTION_DIRECTIONAL_TRADE",
    "ACTION_MARKET_NEUTRAL_OR_HEDGED_TRADE",
    "ACTION_REDUCE_EXISTING_EXPOSURE",
    "ACTION_REMAIN_FLAT",
    "ADAPTIVE_POLICY_ACTION_SCHEMA_VERSION",
    "LIVE_GATE_BLOCKED_HUMAN_ONLY",
    "POLICY_MODE_BOUNDED_EXPLORATION",
    "POLICY_MODE_CHAMPION_EXPLOITATION",
    "POLICY_MODE_POSITION_MANAGEMENT",
    "POLICY_MODE_RISK_REDUCTION",
    "UNIT_CONTRACT_USD_BPS_SECONDS_PROBABILITY",
    "ActionProbabilityV2",
    "AdaptivePolicyActionV2",
    "EntryPolicyV2",
    "ExitPolicyV2",
    "ExpectedCostBreakdownV2",
    "HedgeLegV2",
    "HorizonReturnDistributionV2",
    "PartialReductionStepV2",
    "PositionAdjustmentV2",
    "ReturnQuantileV2",
)
