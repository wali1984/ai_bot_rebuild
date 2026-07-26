"""Pure same-cycle paper resource reservation contracts.

The allocator evaluates one candidate at a time.  This module makes the
resources consumed by candidates already accepted in the same loop explicit,
without reading Redis, the filesystem, clocks, or exchange state.  A caller
builds a snapshot before allocation, places ``snapshot_hash`` in the
allocator's lineage, and then builds a commit receipt before appending the
candidate to the accepted list.

Only dynamic limits supplied by the caller are used.  There are deliberately
no policy defaults in this module.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    Underflow,
    localcontext,
)
from typing import Any

CYCLE_RESERVATION_SNAPSHOT_SCHEMA_VERSION = "paper_cycle_reservation_snapshot_v1"
CYCLE_RESERVATION_COMMIT_SCHEMA_VERSION = "paper_cycle_reservation_commit_v1"
CYCLE_RESERVATION_LINEAGE_KEY = "paper_cycle_reservation_snapshot_hash"
CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY = (
    "paper_allocator_arithmetic_receipt"
)
CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_SCHEMA_VERSION = (
    "paper_allocator_arithmetic_receipt_v1"
)
CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_VERSION = "adaptive_capital_allocator_binary64_arithmetic_v1"
CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_FORMULA = (
    "raw_post_step_notional=abs(binary64(raw_post_step_quantity)*"
    "binary64(input_price));raw_allocated_margin=raw_post_step_notional/"
    "binary64(selected_leverage);publish=round(quantity,12),round(notional,8),"
    "round(leverage,8),round(margin,8)"
)
CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_IDENTITY = (
    f"{CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_SCHEMA_VERSION}:"
    f"{CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_VERSION}:"
    f"{CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_FORMULA}"
)
# Compatibility names remain importable, but now identify the raw receipt
# contract rather than attempting to replay from lossy published aliases.
CYCLE_RESERVATION_ALLOCATOR_MARGIN_REPLAY_FORMULA = CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_FORMULA
CYCLE_RESERVATION_ALLOCATOR_MARGIN_REPLAY_VERSION = CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_VERSION
CYCLE_RESERVATION_ALLOCATOR_MARGIN_REPLAY_IDENTITY = CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_IDENTITY

_FINAL_ADMISSION_SCHEMA_VERSION = "paper_final_admission_contract_v3"
_REVOCABLE_CONTROL_COMMIT_SCHEMA_VERSION = "paper_revocable_control_commit_revalidation_v1"
_ALLOCATION_INPUT_SCHEMA_VERSION = "adaptive_capital_allocation_input_v1"
_ALLOCATION_INPUT_HASH_ALGORITHM = "sha256(canonical-json-v1)"
_SIZABLE_ALLOCATOR_DECISIONS = frozenset({"ALLOW_WITH_SIZE", "REDUCE_SIZE"})
_GUARDIAN_TTL_REQUIRED_RANGE_SECONDS = (1, 180)
_ALLOCATOR_QUANTITY_QUANTUM = Decimal("1E-12")
_ALLOCATOR_USD_QUANTUM = Decimal("1E-8")
_ALLOCATOR_LEVERAGE_QUANTUM = Decimal("1E-8")
_ALLOCATOR_ARITHMETIC_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "arithmetic_version",
        "formula",
        "raw_post_step_quantity_binary64_hex",
        "input_price_binary64_hex",
        "raw_post_step_notional_binary64_hex",
        "selected_leverage_binary64_hex",
        "receipt_sha256",
    }
)
_ALLOCATOR_ARITHMETIC_RECEIPT_HEX_FIELDS = (
    "raw_post_step_quantity_binary64_hex",
    "input_price_binary64_hex",
    "raw_post_step_notional_binary64_hex",
    "selected_leverage_binary64_hex",
)
_MAX_CANONICAL_BINARY64_HEX_BYTES = 32
_BASIS_POINTS_PER_UNIT = Decimal(10_000)
_EXECUTABLE_PAPER_TIERS = frozenset(
    {
        "A_GRADE_EXECUTION_PAPER",
        "A_PLUS_BOOTSTRAP_REDUCED_SIZE_PAPER_ONLY",
        "B_GRADE_EXPLORATION_PAPER",
        "POSITIVE_EDGE_PROBATION_PAPER",
        "PAPER_RISK_CONTROLLER_EXPLORATION",
    }
)
_GUARDIAN_REQUIRED_PAPER_TIERS = frozenset(
    {
        "A_GRADE_EXECUTION_PAPER",
        "A_PLUS_BOOTSTRAP_REDUCED_SIZE_PAPER_ONLY",
    }
)
_FREEZE_OVERRIDE_PAPER_TIERS = frozenset(
    {
        "POSITIVE_EDGE_PROBATION_PAPER",
        "PAPER_RISK_CONTROLLER_EXPLORATION",
    }
)
_REVOCABLE_SOURCE_STATUS_BY_ROLE = {
    "continuous_edge_guardian": frozenset({"READY"}),
    "paper_entry_freeze_source": frozenset({"READY", "MISSING"}),
    "portfolio_state_source": frozenset({"READY"}),
    "adaptive_tuning_source": frozenset({"READY"}),
    "paper_session_source": frozenset({"READY"}),
    "paper_position_or_ledger_source": frozenset({"READY"}),
    "paper_closed_trades_source": frozenset({"READY"}),
}
_REVOCABLE_SOURCE_KEYS_BY_ROLE = {
    "continuous_edge_guardian": frozenset({"v2:continuous_edge_guardian:a_grade_execution_gate"}),
    "paper_entry_freeze_source": frozenset({"v2:paper:entry_freeze"}),
    "portfolio_state_source": frozenset({"v2:portfolio:state"}),
    "adaptive_tuning_source": frozenset({"v2:orchestrator:adaptive_gate_tuning_state"}),
    "paper_session_source": frozenset({"v2:paper:session"}),
    "paper_position_or_ledger_source": frozenset({"v2:paper:positions", "v2:paper:ledger"}),
    "paper_closed_trades_source": frozenset({"v2:paper:closed_trades"}),
}
_RUNTIME_OWNER_REQUIRED_PASS_CONDITIONS = (
    "canonical_paper_writer_count_eq_1",
    "canonical_service_scope_writer_count_eq_1",
    "current_process_is_only_canonical_writer",
    "forbidden_entry_process_count_zero",
    "duplicate_paper_writer_count_zero",
    "paper_online_runtime_active_false",
    "paper_online_runtime_enabled_false",
    "canonical_paper_runtime_enabled_true",
    "toy_momentum_entry_writer_active_false",
    "active_new_entry_owner_is_v2_trade_management_paper_loop",
)
_PERSISTED_ROW_PROJECTION_SCHEMA_VERSION = "paper_persisted_admission_projection_v1"
_ORDINARY_PAPER_ROUTER_PROOF_SHA256_FIELD = (
    "ordinary_paper_strategy_router_interpretation_proof_sha256"
)

# Immutable safety/resource-integrity ceilings.  These bounds constrain parser,
# hashing, Decimal, and accepted-prefix work only.  They do not select a market,
# signal, threshold, leverage, position size, or risk outcome.
MAX_CYCLE_RESERVATION_CANONICAL_JSON_BYTES = 16 * 1024 * 1024
MAX_CYCLE_RESERVATION_JSON_DEPTH = 64
MAX_CYCLE_RESERVATION_JSON_NODES = 1_000_000
MAX_CYCLE_RESERVATION_JSON_STRING_BYTES = 1 * 1024 * 1024
MAX_CYCLE_RESERVATION_TEXT_BYTES = 4 * 1024
MAX_CYCLE_RESERVATION_PRIOR_ACCEPTED_ROWS = 64
MAX_CYCLE_RESERVATION_JSON_INTEGER_DIGITS = 4_096
MAX_CYCLE_RESERVATION_DECIMAL_INPUT_BYTES = 8 * 1024
MAX_CYCLE_RESERVATION_DECIMAL_RESULT_BYTES = 64 * 1024
MAX_CYCLE_RESERVATION_DECIMAL_INPUT_DIGITS = 4_096
MAX_CYCLE_RESERVATION_DECIMAL_INPUT_ADJUSTED_EXPONENT = 4_096
MAX_CYCLE_RESERVATION_DECIMAL_RESULT_DIGITS = 32_768
MAX_CYCLE_RESERVATION_DECIMAL_RESULT_ADJUSTED_EXPONENT = 8_192
MAX_CYCLE_RESERVATION_DECIMAL_OPERATION_PRECISION = 32_768
CYCLE_RESERVATION_DECIMAL_DIVISION_PRECISION = 28

CYCLE_RESERVATION_IMMUTABLE_BOUND_CLASSIFICATION = {
    "canonical_json_bytes": "RESOURCE_INTEGRITY_SAFETY_NOT_MARKET_POLICY",
    "json_depth": "RESOURCE_INTEGRITY_SAFETY_NOT_MARKET_POLICY",
    "json_nodes": "RESOURCE_INTEGRITY_SAFETY_NOT_MARKET_POLICY",
    "json_string_bytes": "RESOURCE_INTEGRITY_SAFETY_NOT_MARKET_POLICY",
    "structural_text_bytes": "RESOURCE_INTEGRITY_SAFETY_NOT_MARKET_POLICY",
    "prior_accepted_rows": "RESOURCE_INTEGRITY_SAFETY_NOT_MARKET_POLICY",
    "decimal_input_bytes": "NUMERIC_RESOURCE_INTEGRITY_NOT_MARKET_POLICY",
    "decimal_result_bytes": "NUMERIC_RESOURCE_INTEGRITY_NOT_MARKET_POLICY",
    "decimal_input_digits": "NUMERIC_RESOURCE_INTEGRITY_NOT_MARKET_POLICY",
    "decimal_adjusted_exponent": "NUMERIC_RESOURCE_INTEGRITY_NOT_MARKET_POLICY",
    "decimal_operation_precision": "NUMERIC_RESOURCE_INTEGRITY_NOT_MARKET_POLICY",
    "decimal_division_precision": "NUMERIC_DETERMINISM_SAFETY_NOT_MARKET_POLICY",
}

_PERSISTED_ADMISSION_COMPONENT_TIME_FIELDS = (
    "paper_allocation_decision_time",
    "paper_precycle_exposure_snapshot_started_at",
    "paper_precycle_exposure_snapshot_completed_at",
    "normal_adaptive_allocation_decision_time",
    "normal_adaptive_allocator_economic_contract_sealed_at",
    "normal_adaptive_allocation_contract_sealed_at",
    "paper_reduced_allocation_decision_time",
    "advanced_indicator_event_time",
    "advanced_indicator_available_at",
    "advanced_indicator_source_decision_time",
    "advanced_indicator_generated_at",
    "advanced_indicator_input_cutoff",
    "advanced_indicator_decision_time",
    "advanced_indicator_lookup_observed_at",
    "altdata_feature_cutoff",
    "altdata_generated_at",
    "altdata_available_at",
    "altdata_lookup_observed_at",
    "mark_index_event_time",
    "mark_index_generated_at",
    "mark_index_available_at",
    "mark_index_observed_at",
    "long_short_event_time",
    "long_short_available_at",
    "long_short_captured_at",
    "long_short_decision_time",
    "long_short_lookup_observed_at",
    "a_plus_context_snapshot_observed_at",
    "a_plus_gate_evaluated_at",
    "paper_entry_gate_snapshot_observed_at",
    "paper_entry_gate_evaluated_at",
    "paper_pre_cycle_control_snapshot_observed_at",
    "runtime_cost_capture_decision_time",
    "cost_source_timestamp",
    "source_timestamp",
    "preemptive_decision_time",
    "maintenance_bracket_available_at",
    "maintenance_bracket_expires_at",
    "maintenance_bracket_consumer_observed_at",
    "paper_allocator_economic_contract_sealed_at",
    "paper_exchange_filter_available_at",
    "paper_exchange_filter_observed_at",
)

_PERSISTED_ADMISSION_CRITICAL_FIELDS = (
    "intent_id",
    "signal_id",
    "prediction_id",
    "risk_decision_id",
    "orchestrator_decision_id",
    "allocation_id",
    "preemptive_decision_id",
    "symbol",
    "timeframe",
    "side",
    "paper_opportunity_tier",
    "paper_opportunity_tier_reason",
    "paper_fill_allowed_source",
    "calibration_label_purpose",
    "decision",
    "paper_fill_allowed",
    "valid_for_paper",
    "raw_paper_fill_allowed_upstream",
    "ordinary_paper_fill_allowed_at_boundary",
    "ordinary_scale_free_paper_admission_revalidated",
    "ordinary_paper_admission_evidence_sha256",
    "publisher_paper_quality_sizing_weight",
    "ordinary_paper_effective_sizing_weight",
    "ordinary_paper_final_boundary_revalidated",
    "ordinary_paper_final_boundary_evidence_sha256",
    "ordinary_paper_final_boundary_effective_sizing_weight",
    _ORDINARY_PAPER_ROUTER_PROOF_SHA256_FIELD,
    "ordinary_paper_strategy_router_interpretation_applied",
    "ordinary_paper_strategy_router_trade_allowed",
    "ordinary_paper_strategy_router_effective_mode",
    "ordinary_paper_strategy_router_continuous_weight",
    "ordinary_paper_strategy_router_continuous_formula",
    "ordinary_paper_strategy_router_final_boundary_revalidated",
    "ordinary_paper_strategy_router_final_boundary_continuous_weight",
    "paper_allocator_ordinary_paper_strategy_router_interpretation_sha256",
    "paper_allocator_ordinary_paper_absolute_contracted_weight",
    "paper_reduced_budget_allocator_recomputed",
    "risk_budget_fraction_of_normal_adaptive",
    "normal_adaptive_allocation_id",
    "normal_adaptive_allocation_input_hash",
    "normal_adaptive_allocator_economic_contract_hash",
    "normal_adaptive_allocator_economic_contract_receipt_hash",
    "normal_adaptive_allocator_economic_contract_sealed_at",
    "normal_adaptive_allocation_point_in_time_evidence_hash",
    "normal_adaptive_allocation_contract_hash",
    "paper_reduced_allocation_point_in_time_evidence_hash",
    "quantity",
    "target_quantity",
    "fill_price",
    "entry_price",
    "notional",
    "target_notional_usd",
    "target_notional_usdt",
    "gross_notional_usd",
    "recommended_leverage",
    "effective_leverage",
    "allocated_margin_usd",
    "margin_mode_simulated",
    "recommended_margin_mode",
    "paper_only",
    "routes_to_live",
    "places_real_order",
    "live_order",
    "test_order",
    "order_submitted",
    "test_order_submitted",
    "leverage_mutated",
    "margin_mutated",
    "counts_as_a_grade_evidence",
    "counts_as_A_plus",
    "counts_as_final_a_plus",
    "counts_as_live_ready",
    "mandatory_size_haircut",
    "no_static_dollar_notional",
    "no_leverage_increase_to_compensate_for_lower_trust",
    "risk_decision_record_hash",
    "orchestrator_decision_record_hash",
    "preemptive_input_hash",
    "adaptive_tuning_state_hash",
    "paper_pre_cycle_control_snapshot_hash",
    "a_plus_context_snapshot_hash",
    "paper_entry_gate_snapshot_hash",
    "paper_entry_gate_evaluation_hash",
    "a_plus_gate_evaluation_hash",
    "paper_exchange_filter_snapshot_hash",
    "paper_allocator_economic_contract_hash",
    "paper_allocator_economic_contract_receipt_hash",
    "paper_precycle_current_mark_exposure_snapshot_hash",
    "paper_cycle_base_resource_evidence_hash",
    "paper_dynamic_envelope_reservation_evidence_hash",
    "paper_cycle_reservation_snapshot_hash",
    "paper_cycle_reservation_status",
    "paper_cycle_reservation_commit_receipt_hash",
    "paper_cycle_reservation_commit_status",
    "paper_revocable_control_commit_revalidation_receipt_hash",
    "paper_revocable_control_commit_revalidation_status",
    "maintenance_bracket_evidence_checksum_sha256",
    "maintenance_bracket_evidence_hmac_sha256",
    "maintenance_bracket_id",
    "maintenance_bracket_maint_margin_ratio",
    "maintenance_bracket_cum",
    "maintenance_bracket_max_initial_leverage",
    "maintenance_bracket_account_binding_id",
    "maintenance_bracket_environment_id",
    "maintenance_bracket_key_id",
    "maintenance_bracket_source",
    "maintenance_bracket_available_at",
    "maintenance_bracket_expires_at",
    "maintenance_bracket_consumer_observed_at",
)

_PERSISTED_ADMISSION_NESTED_FIELDS = (
    "adaptive_allocation",
    "paper_normal_adaptive_allocation_contract",
    "paper_allocator_economic_contract",
    "paper_pre_cycle_control_snapshot",
    "a_plus_context_snapshot",
    "paper_entry_gate_snapshot",
    "paper_entry_gate_evaluation",
    "a_plus_gate_evaluation",
    "preemptive_edge_control",
    "paper_exchange_filter_snapshot",
    "paper_precycle_current_mark_exposure_snapshot",
    "paper_cycle_base_resource_evidence",
    "paper_dynamic_envelope_reservation_evidence",
    "paper_cycle_reservation_snapshot",
    "paper_cycle_reservation_commit_receipt",
    "paper_revocable_control_commit_revalidation",
    "paper_maintenance_margin_bracket_evidence",
    "maintenance_bracket_evidence",
    "mark_index_source_material",
    "long_short_source_material",
    "ordinary_paper_admission_evidence",
    "ordinary_paper_strategy_router_interpretation_proof",
    "microstructure_trust_evidence",
)

_FINAL_TIER_CONTRACT_FIELDS = (
    "paper_opportunity_tier",
    "paper_opportunity_tier_reason",
    "paper_fill_allowed_source",
    "calibration_label_purpose",
    "decision",
    "paper_fill_allowed",
    "valid_for_paper",
    "paper_reduced_budget_allocator_recomputed",
    "risk_budget_fraction_of_normal_adaptive",
    "mandatory_size_haircut",
    "no_static_dollar_notional",
    "no_leverage_increase_to_compensate_for_lower_trust",
    "counts_as_a_grade_evidence",
    "counts_as_A_plus",
    "counts_as_final_a_plus",
    "counts_as_live_ready",
    "a_plus_reduced_size_bootstrap_budget_cap_applied",
    "b_grade_exploration_budget_cap_applied",
    "positive_edge_probation_budget_cap_applied",
    "paper_risk_controller_exploration_budget_cap_applied",
)

_FINAL_ROW_SAFETY_FIELDS = (
    "paper_only",
    "routes_to_live",
    "places_real_order",
    "live_order",
    "test_order",
    "order_submitted",
    "test_order_submitted",
    "leverage_mutated",
    "margin_mutated",
)

_FINAL_ALLOCATION_SAFETY_FIELDS = (
    "paper_only",
    "routes_to_live",
    "places_real_order",
    "live_order",
    "test_order",
    "leverage_mutation",
    "margin_mode_mutation",
)


class CycleReservationError(ValueError):
    """Raised when reservation evidence is structurally unsafe to consume."""

    def __init__(self, *reasons: str) -> None:
        normalized = tuple(sorted({str(reason) for reason in reasons if reason}))
        self.reasons = normalized or ("CYCLE_RESERVATION_EVIDENCE_INVALID",)
        super().__init__(";".join(self.reasons))


def _json_integer_digit_count(value: int) -> int:
    """Return a bounded exact decimal width without converting a huge integer."""

    bit_count = value.bit_length()
    if bit_count == 0:
        return 1
    minimum_digits = ((bit_count - 1) * 30_102) // 100_000 + 1
    if minimum_digits > MAX_CYCLE_RESERVATION_JSON_INTEGER_DIGITS:
        raise CycleReservationError("CYCLE_RESERVATION_JSON_INTEGER_LIMIT_EXCEEDED")
    try:
        digits = len(str(abs(value)))
    except (MemoryError, RecursionError, ValueError) as exc:
        raise CycleReservationError("CYCLE_RESERVATION_JSON_INTEGER_LIMIT_EXCEEDED") from exc
    if digits > MAX_CYCLE_RESERVATION_JSON_INTEGER_DIGITS:
        raise CycleReservationError("CYCLE_RESERVATION_JSON_INTEGER_LIMIT_EXCEEDED")
    return digits


def _validate_strict_json_value(
    value: Any,
    *,
    depth: int = 0,
    remaining_nodes: list[int] | None = None,
) -> None:
    """Enforce the deterministic allocator-compatible JSON hashing domain."""

    if remaining_nodes is None:
        remaining_nodes = [MAX_CYCLE_RESERVATION_JSON_NODES]
    remaining_nodes[0] -= 1
    if remaining_nodes[0] < 0:
        raise CycleReservationError("CYCLE_RESERVATION_JSON_NODE_LIMIT_EXCEEDED")
    if depth > MAX_CYCLE_RESERVATION_JSON_DEPTH:
        raise CycleReservationError("CYCLE_RESERVATION_JSON_DEPTH_LIMIT_EXCEEDED")
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        _json_integer_digit_count(value)
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise CycleReservationError("CYCLE_RESERVATION_CANONICAL_JSON_INVALID")
        return
    if type(value) is str:
        if len(value) > MAX_CYCLE_RESERVATION_JSON_STRING_BYTES:
            raise CycleReservationError("CYCLE_RESERVATION_JSON_STRING_LIMIT_EXCEEDED")
        try:
            byte_count = len(value.encode("utf-8", errors="surrogatepass"))
        except (MemoryError, RecursionError, UnicodeError) as exc:
            raise CycleReservationError("CYCLE_RESERVATION_JSON_STRING_LIMIT_EXCEEDED") from exc
        if byte_count > MAX_CYCLE_RESERVATION_JSON_STRING_BYTES:
            raise CycleReservationError("CYCLE_RESERVATION_JSON_STRING_LIMIT_EXCEEDED")
        return
    # ``dataclasses.asdict(AllocationInput)`` preserves the allocator's
    # ``permitted_leverage_values`` tuple.  The allocator's canonical encoder
    # has always represented that exact built-in tuple as a JSON array, so only
    # built-in list/tuple containers are admitted with those same digest bytes.
    if type(value) in (list, tuple):
        if len(value) > remaining_nodes[0]:
            raise CycleReservationError("CYCLE_RESERVATION_JSON_NODE_LIMIT_EXCEEDED")
        for item in value:
            _validate_strict_json_value(
                item,
                depth=depth + 1,
                remaining_nodes=remaining_nodes,
            )
        return
    if type(value) is dict:
        if len(value) > remaining_nodes[0]:
            raise CycleReservationError("CYCLE_RESERVATION_JSON_NODE_LIMIT_EXCEEDED")
        try:
            items = tuple(value.items())
        except (MemoryError, RecursionError, RuntimeError) as exc:
            raise CycleReservationError("CYCLE_RESERVATION_CANONICAL_JSON_INVALID") from exc
        if len(items) != len(value):
            raise CycleReservationError("CYCLE_RESERVATION_CANONICAL_JSON_INVALID")
        for key, item in items:
            if type(key) is not str:
                raise CycleReservationError("CYCLE_RESERVATION_JSON_OBJECT_KEY_INVALID")
            _validate_strict_json_value(key, depth=depth + 1, remaining_nodes=remaining_nodes)
            _validate_strict_json_value(
                item,
                depth=depth + 1,
                remaining_nodes=remaining_nodes,
            )
        return
    raise CycleReservationError("CYCLE_RESERVATION_CANONICAL_JSON_TYPE_INVALID")


def _strict_json_sha256(value: Any, *, compact: bool) -> str:
    """Hash the bounded compatible domain while preserving allocator bytes."""

    try:
        _validate_strict_json_value(value)
        encoder_options: dict[str, Any] = {
            "allow_nan": False,
            "ensure_ascii": True,
            "sort_keys": True,
        }
        if compact:
            encoder_options["separators"] = (",", ":")
        encoder = json.JSONEncoder(**encoder_options)
        digest = hashlib.sha256()
        byte_count = 0
        for chunk in encoder.iterencode(value):
            encoded = chunk.encode("ascii", errors="strict")
            byte_count += len(encoded)
            if byte_count > MAX_CYCLE_RESERVATION_CANONICAL_JSON_BYTES:
                raise CycleReservationError("CYCLE_RESERVATION_CANONICAL_JSON_SIZE_LIMIT_EXCEEDED")
            digest.update(encoded)
        if byte_count <= 0:
            raise CycleReservationError("CYCLE_RESERVATION_CANONICAL_JSON_INVALID")
        return digest.hexdigest()
    except CycleReservationError:
        raise
    except (
        MemoryError,
        OverflowError,
        RecursionError,
        RuntimeError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise CycleReservationError("CYCLE_RESERVATION_CANONICAL_JSON_INVALID") from exc


def _canonical_sha256(value: Any) -> str:
    return _strict_json_sha256(value, compact=True)


def _type_exact_json_equal(left: Any, right: Any) -> bool:
    """Compare bounded JSON-compatible values without Python bool/int aliasing."""

    try:
        _validate_strict_json_value(left)
        _validate_strict_json_value(right)
    except CycleReservationError:
        return False
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        if left.keys() != right.keys():
            return False
        return all(_type_exact_json_equal(left[key], right[key]) for key in left)
    if type(left) in (list, tuple):
        return len(left) == len(right) and all(
            _type_exact_json_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return bool(left == right)


def _allocator_quantize(value: Decimal, quantum: Decimal, field: str) -> Decimal:
    """Apply the allocator's published decimal-place ABI with no tolerance."""

    quantum_exponent = quantum.as_tuple().exponent
    if type(quantum_exponent) is not int:
        raise CycleReservationError(f"CYCLE_RESERVATION_ALLOCATOR_QUANTIZATION_INVALID:{field}")
    precision = max(
        1,
        len(value.as_tuple().digits),
        value.adjusted() - quantum_exponent + 2,
    )
    try:
        with localcontext(_decimal_operation_context(precision)):
            result = value.quantize(quantum, rounding=ROUND_HALF_EVEN)
    except CycleReservationError:
        raise
    except (DecimalException, MemoryError, OverflowError, ValueError) as exc:
        raise CycleReservationError(
            f"CYCLE_RESERVATION_ALLOCATOR_QUANTIZATION_INVALID:{field}"
        ) from exc
    return _validate_decimal_resource(result, field, input_value=False)


def _validate_decimal_resource(
    value: Decimal,
    field: str,
    *,
    input_value: bool,
) -> Decimal:
    if not value.is_finite():
        raise CycleReservationError(f"CYCLE_RESERVATION_NUMERIC_INVALID:{field}")
    try:
        decimal_tuple = value.as_tuple()
        digit_count = len(decimal_tuple.digits)
        adjusted = value.adjusted() if value != 0 else 0
    except (DecimalException, MemoryError, OverflowError, ValueError) as exc:
        raise CycleReservationError(
            f"CYCLE_RESERVATION_NUMERIC_RESOURCE_LIMIT_EXCEEDED:{field}"
        ) from exc
    digit_limit = (
        MAX_CYCLE_RESERVATION_DECIMAL_INPUT_DIGITS
        if input_value
        else MAX_CYCLE_RESERVATION_DECIMAL_RESULT_DIGITS
    )
    exponent_limit = (
        MAX_CYCLE_RESERVATION_DECIMAL_INPUT_ADJUSTED_EXPONENT
        if input_value
        else MAX_CYCLE_RESERVATION_DECIMAL_RESULT_ADJUSTED_EXPONENT
    )
    if digit_count > digit_limit or abs(adjusted) > exponent_limit:
        raise CycleReservationError(f"CYCLE_RESERVATION_NUMERIC_RESOURCE_LIMIT_EXCEEDED:{field}")
    return value


def _valid_sha256(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _decimal(value: Any, field: str, *, input_value: bool = True) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise CycleReservationError(f"CYCLE_RESERVATION_NUMERIC_INVALID:{field}")
    if type(value) is Decimal:
        return _validate_decimal_resource(value, field, input_value=input_value)
    if type(value) is int:
        try:
            digit_count = _json_integer_digit_count(value)
        except CycleReservationError as exc:
            raise CycleReservationError(
                f"CYCLE_RESERVATION_NUMERIC_RESOURCE_LIMIT_EXCEEDED:{field}"
            ) from exc
        if input_value and digit_count > MAX_CYCLE_RESERVATION_DECIMAL_INPUT_DIGITS:
            raise CycleReservationError(
                f"CYCLE_RESERVATION_NUMERIC_RESOURCE_LIMIT_EXCEEDED:{field}"
            )
        raw = str(value)
    elif type(value) is float:
        if not math.isfinite(value):
            raise CycleReservationError(f"CYCLE_RESERVATION_NUMERIC_INVALID:{field}")
        raw = str(value)
    elif type(value) is str:
        byte_limit = (
            MAX_CYCLE_RESERVATION_DECIMAL_INPUT_BYTES
            if input_value
            else MAX_CYCLE_RESERVATION_DECIMAL_RESULT_BYTES
        )
        if len(value) > byte_limit:
            raise CycleReservationError(
                f"CYCLE_RESERVATION_NUMERIC_RESOURCE_LIMIT_EXCEEDED:{field}"
            )
        if not value.strip():
            raise CycleReservationError(f"CYCLE_RESERVATION_NUMERIC_INVALID:{field}")
        try:
            raw_byte_count = len(value.encode("ascii", errors="strict"))
        except UnicodeError as exc:
            raise CycleReservationError(f"CYCLE_RESERVATION_NUMERIC_INVALID:{field}") from exc
        if raw_byte_count > byte_limit:
            raise CycleReservationError(
                f"CYCLE_RESERVATION_NUMERIC_RESOURCE_LIMIT_EXCEEDED:{field}"
            )
        raw = value
    else:
        raise CycleReservationError(f"CYCLE_RESERVATION_NUMERIC_INVALID:{field}")
    try:
        parsed = Decimal(raw)
    except (DecimalException, MemoryError, OverflowError, TypeError, ValueError) as exc:
        raise CycleReservationError(f"CYCLE_RESERVATION_NUMERIC_INVALID:{field}") from exc
    return _validate_decimal_resource(parsed, field, input_value=input_value)


def _nonnegative_decimal(value: Any, field: str) -> Decimal:
    parsed = _decimal(value, field)
    if parsed < 0:
        raise CycleReservationError(f"CYCLE_RESERVATION_NUMERIC_NEGATIVE:{field}")
    return parsed


def _positive_decimal(value: Any, field: str) -> Decimal:
    parsed = _decimal(value, field)
    if parsed <= 0:
        raise CycleReservationError(f"CYCLE_RESERVATION_NUMERIC_NOT_POSITIVE:{field}")
    return parsed


def _optional_nonnegative_decimal(value: Any, field: str) -> Decimal | None:
    if value is None:
        return None
    return _nonnegative_decimal(value, field)


def _nonnegative_ratio(value: Any, field: str) -> Decimal:
    """Return a caller-owned ratio without introducing a policy ceiling."""

    return _nonnegative_decimal(value, field)


def _number(value: Decimal, field: str = "derived") -> float:
    """Project an exact Decimal into a finite JSON-number compatibility alias.

    JSON numbers are retained for existing paper-loop consumers, but they are
    never the authority for reservation arithmetic.  Every persisted resource
    boundary also carries canonical Decimal material and replay starts from
    that material.  A non-zero Decimal that underflows to a zero float is
    rejected because such an alias would be actively misleading.
    """

    _validate_decimal_resource(value, field, input_value=False)
    try:
        result = float(value)
    except (DecimalException, MemoryError, OverflowError, ValueError) as exc:
        raise CycleReservationError(f"CYCLE_RESERVATION_DERIVED_NUMERIC_INVALID:{field}") from exc
    if not math.isfinite(result):
        raise CycleReservationError(f"CYCLE_RESERVATION_DERIVED_NUMERIC_INVALID:{field}")
    if value != 0 and result == 0.0:
        raise CycleReservationError(f"CYCLE_RESERVATION_NUMERIC_UNREPRESENTABLE:{field}")
    return 0.0 if result == 0.0 else result


def _canonical_decimal(value: Decimal, field: str) -> str:
    """Return one canonical, exponent-safe spelling for an exact Decimal."""

    _validate_decimal_resource(value, field, input_value=False)
    if value == 0:
        return "0E+0"
    precision = max(1, len(value.as_tuple().digits))
    try:
        with localcontext(_decimal_operation_context(precision)):
            return format(value.normalize(), "E")
    except (DecimalException, MemoryError, OverflowError, ValueError) as exc:
        raise CycleReservationError(f"CYCLE_RESERVATION_DECIMAL_OPERATION_INVALID:{field}") from exc


def _exact_decimal_from_material(
    *,
    numeric_alias: Any,
    exact_material: Any,
    field: str,
    derived_material: bool = False,
) -> Decimal:
    """Validate a JSON-number alias against its canonical Decimal authority."""

    if type(exact_material) is not str:
        raise CycleReservationError(f"CYCLE_RESERVATION_EXACT_DECIMAL_MATERIAL_MISSING:{field}")
    material_byte_limit = (
        MAX_CYCLE_RESERVATION_DECIMAL_RESULT_BYTES
        if derived_material
        else MAX_CYCLE_RESERVATION_DECIMAL_INPUT_BYTES
    )
    if len(exact_material) <= material_byte_limit and not exact_material.strip():
        raise CycleReservationError(f"CYCLE_RESERVATION_EXACT_DECIMAL_MATERIAL_MISSING:{field}")
    exact = _decimal(
        exact_material,
        f"{field}.exact_decimal",
        input_value=not derived_material,
    )
    if exact_material != _canonical_decimal(exact, field):
        raise CycleReservationError(
            f"CYCLE_RESERVATION_EXACT_DECIMAL_MATERIAL_NONCANONICAL:{field}"
        )
    if isinstance(numeric_alias, bool) or not isinstance(numeric_alias, int | float):
        raise CycleReservationError(f"CYCLE_RESERVATION_EXACT_DECIMAL_ALIAS_INVALID:{field}")
    expected_alias = _number(exact, field)
    try:
        observed_alias = _number(_decimal(numeric_alias, f"{field}.numeric_alias"), field)
    except CycleReservationError as exc:
        raise CycleReservationError(*exc.reasons) from exc
    if observed_alias != expected_alias:
        raise CycleReservationError(f"CYCLE_RESERVATION_EXACT_DECIMAL_ALIAS_MISMATCH:{field}")
    return exact


def _addition_precision(values: Sequence[Decimal]) -> int:
    """Return enough Decimal precision for an exact finite add/subtract."""

    nonzero = [value for value in values if value != 0]
    if not nonzero:
        return 1
    exponents = [value.as_tuple().exponent for value in nonzero]
    if not all(isinstance(exponent, int) for exponent in exponents):
        raise CycleReservationError("CYCLE_RESERVATION_INTERNAL_DECIMAL_EXPONENT_INVALID")
    minimum_exponent = min(exponent for exponent in exponents if isinstance(exponent, int))
    maximum_adjusted = max(value.adjusted() for value in nonzero)
    carry_digits = len(str(len(nonzero) + 1))
    precision = max(1, maximum_adjusted - minimum_exponent + carry_digits + 2)
    if precision > MAX_CYCLE_RESERVATION_DECIMAL_OPERATION_PRECISION:
        raise CycleReservationError("CYCLE_RESERVATION_DECIMAL_OPERATION_RESOURCE_LIMIT_EXCEEDED")
    return precision


def _decimal_operation_context(precision: int) -> Context:
    if (
        type(precision) is not int
        or precision <= 0
        or precision > MAX_CYCLE_RESERVATION_DECIMAL_OPERATION_PRECISION
    ):
        raise CycleReservationError("CYCLE_RESERVATION_DECIMAL_OPERATION_RESOURCE_LIMIT_EXCEEDED")
    return Context(
        prec=precision,
        rounding=ROUND_HALF_EVEN,
        Emin=-MAX_CYCLE_RESERVATION_DECIMAL_RESULT_ADJUSTED_EXPONENT,
        Emax=MAX_CYCLE_RESERVATION_DECIMAL_RESULT_ADJUSTED_EXPONENT,
        capitals=1,
        clamp=0,
        traps=[InvalidOperation, DivisionByZero, Overflow, Underflow],
    )


def _decimal_operation_failure(field: str) -> CycleReservationError:
    return CycleReservationError(f"CYCLE_RESERVATION_DECIMAL_OPERATION_INVALID:{field}")


def _exact_add(*values: Decimal) -> Decimal:
    try:
        with localcontext(_decimal_operation_context(_addition_precision(values))):
            result = sum(values, Decimal(0))
    except CycleReservationError:
        raise
    except (DecimalException, MemoryError, OverflowError, ValueError) as exc:
        raise _decimal_operation_failure("addition") from exc
    return _validate_decimal_resource(result, "addition", input_value=False)


def _exact_subtract(left: Decimal, *right: Decimal) -> Decimal:
    # Decimal unary minus observes the ambient context and can round/trap.
    # copy_negate is exact and context-free; _exact_add supplies our context.
    return _exact_add(left, *(value.copy_negate() for value in right))


def _exact_multiply(left: Decimal, right: Decimal) -> Decimal:
    precision = max(
        1,
        len(left.as_tuple().digits) + len(right.as_tuple().digits) + 1,
    )
    try:
        with localcontext(_decimal_operation_context(precision)):
            result = left * right
    except CycleReservationError:
        raise
    except (DecimalException, MemoryError, OverflowError, ValueError) as exc:
        raise _decimal_operation_failure("multiplication") from exc
    return _validate_decimal_resource(result, "multiplication", input_value=False)


def _deterministic_divide(left: Decimal, right: Decimal, field: str) -> Decimal:
    if right == 0:
        raise CycleReservationError(f"CYCLE_RESERVATION_DECIMAL_OPERATION_INVALID:{field}")
    try:
        with localcontext(_decimal_operation_context(CYCLE_RESERVATION_DECIMAL_DIVISION_PRECISION)):
            result = left / right
    except CycleReservationError:
        raise
    except (DecimalException, MemoryError, OverflowError, ValueError) as exc:
        raise _decimal_operation_failure(field) from exc
    return _validate_decimal_resource(result, field, input_value=False)


def _require_binary64_platform(field: str) -> None:
    if sys.float_info.radix != 2 or sys.float_info.mant_dig != 53 or sys.float_info.max_exp != 1024:
        raise CycleReservationError(
            f"CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_PLATFORM_INVALID:{field}"
        )


def _canonical_positive_binary64_hex(value: Any, field: str) -> float:
    """Parse one exact ``float.hex`` spelling and reject every alternate form."""

    _require_binary64_platform(field)
    if type(value) is not str or len(value) > _MAX_CANONICAL_BINARY64_HEX_BYTES:
        raise CycleReservationError(
            f"CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_BINARY64_HEX_INVALID:{field}"
        )
    try:
        encoded = value.encode("ascii", errors="strict")
        parsed = float.fromhex(value)
    except (MemoryError, OverflowError, TypeError, UnicodeError, ValueError) as exc:
        raise CycleReservationError(
            f"CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_BINARY64_HEX_INVALID:{field}"
        ) from exc
    if (
        len(encoded) > _MAX_CANONICAL_BINARY64_HEX_BYTES
        or not math.isfinite(parsed)
        or parsed <= 0.0
        or parsed.hex() != value
    ):
        raise CycleReservationError(
            f"CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_BINARY64_HEX_INVALID:{field}"
        )
    return parsed


def _validated_allocator_arithmetic_receipt(
    value: Any,
) -> tuple[dict[str, Any], dict[str, float]]:
    """Validate the exact bounded/hash-bound producer arithmetic receipt."""

    if type(value) is not dict:
        raise CycleReservationError("CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_TYPE_INVALID")
    receipt = dict(value)
    reasons: list[str] = []
    if set(receipt) != _ALLOCATOR_ARITHMETIC_RECEIPT_FIELDS:
        reasons.append("CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_FIELDS_INVALID")
    if (
        type(receipt.get("schema_version")) is not str
        or receipt.get("schema_version")
        != CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_SCHEMA_VERSION
    ):
        reasons.append("CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_SCHEMA_INVALID")
    if (
        type(receipt.get("arithmetic_version")) is not str
        or receipt.get("arithmetic_version") != CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_VERSION
    ):
        reasons.append("CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_VERSION_INVALID")
    if (
        type(receipt.get("formula")) is not str
        or receipt.get("formula") != CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_FORMULA
    ):
        reasons.append("CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_FORMULA_INVALID")
    material = dict(receipt)
    claimed_hash = material.pop("receipt_sha256", None)
    try:
        recomputed_hash = _canonical_sha256(material)
    except CycleReservationError:
        recomputed_hash = None
    if not _valid_sha256(claimed_hash) or claimed_hash != recomputed_hash:
        reasons.append("CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_HASH_INVALID")

    parsed: dict[str, float] = {}
    for field in _ALLOCATOR_ARITHMETIC_RECEIPT_HEX_FIELDS:
        try:
            parsed[field] = _canonical_positive_binary64_hex(receipt.get(field), field)
        except CycleReservationError as exc:
            reasons.extend(exc.reasons)
    if reasons:
        raise CycleReservationError(*reasons)
    return receipt, parsed


def _allocator_binary64_round_decimal(value: float, digits: int, field: str) -> Decimal:
    """Apply the producer's sole publication result, with no alternatives."""

    _require_binary64_platform(field)
    try:
        rounded_binary64 = round(value, digits)
    except (ArithmeticError, MemoryError, OverflowError, ValueError) as exc:
        raise CycleReservationError(
            f"CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_ROUND_INVALID:{field}"
        ) from exc
    if not math.isfinite(rounded_binary64):
        raise CycleReservationError(f"CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_ROUND_INVALID:{field}")
    try:
        replayed = Decimal(str(rounded_binary64))
    except (DecimalException, MemoryError, OverflowError, TypeError, ValueError) as exc:
        raise CycleReservationError(
            f"CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_DECIMAL_INVALID:{field}"
        ) from exc
    return _validate_decimal_resource(replayed, field, input_value=False)


def _text(value: Any, field: str) -> str:
    if type(value) is not str:
        raise CycleReservationError(f"CYCLE_RESERVATION_TEXT_INVALID:{field}")
    if len(value) > MAX_CYCLE_RESERVATION_TEXT_BYTES:
        raise CycleReservationError(f"CYCLE_RESERVATION_TEXT_RESOURCE_LIMIT_EXCEEDED:{field}")
    normalized = value.strip()
    if not normalized:
        raise CycleReservationError(f"CYCLE_RESERVATION_TEXT_INVALID:{field}")
    try:
        byte_count = len(value.encode("utf-8", errors="strict"))
    except (MemoryError, RecursionError, UnicodeError) as exc:
        raise CycleReservationError(f"CYCLE_RESERVATION_TEXT_INVALID:{field}") from exc
    if byte_count > MAX_CYCLE_RESERVATION_TEXT_BYTES:
        raise CycleReservationError(f"CYCLE_RESERVATION_TEXT_RESOURCE_LIMIT_EXCEEDED:{field}")
    return normalized


def _sha256_text(value: Any, field: str) -> str:
    normalized = _text(value, field)
    if not _valid_sha256(normalized):
        raise CycleReservationError(f"CYCLE_RESERVATION_HASH_INVALID:{field}")
    return normalized


def _symbol(value: Any, field: str = "candidate_symbol") -> str:
    normalized = _text(value, field).upper()
    if any(character.isspace() for character in normalized):
        raise CycleReservationError(f"CYCLE_RESERVATION_SYMBOL_INVALID:{field}")
    return normalized


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CycleReservationError(f"CYCLE_RESERVATION_MAPPING_INVALID:{field}")
    return value


def _bounded_prior_sequence_copy(value: Any, *, projection: bool = False) -> list[Any]:
    """Materialize one bounded prefix and use that exact copy for replay."""

    invalid_reason = (
        "CYCLE_RESERVATION_PRIOR_PROJECTION_SEQUENCE_INVALID"
        if projection
        else "CYCLE_RESERVATION_PRIOR_ROWS_SEQUENCE_INVALID"
    )
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise CycleReservationError(invalid_reason)
    try:
        count = len(value)
    except (MemoryError, OverflowError, RecursionError, TypeError, ValueError) as exc:
        raise CycleReservationError(invalid_reason) from exc
    if count > MAX_CYCLE_RESERVATION_PRIOR_ACCEPTED_ROWS:
        raise CycleReservationError("CYCLE_RESERVATION_PRIOR_ROW_LIMIT_EXCEEDED")
    copied: list[Any] = []
    try:
        for item in value:
            if len(copied) >= MAX_CYCLE_RESERVATION_PRIOR_ACCEPTED_ROWS:
                raise CycleReservationError("CYCLE_RESERVATION_PRIOR_ROW_LIMIT_EXCEEDED")
            copied.append(item)
    except CycleReservationError:
        raise
    except (
        MemoryError,
        OverflowError,
        RecursionError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        raise CycleReservationError(invalid_reason) from exc
    if len(copied) != count:
        raise CycleReservationError(invalid_reason)
    return copied


def _equal_decimal(left: Any, right: Any, left_field: str, right_field: str) -> bool:
    return _decimal(left, left_field) == _decimal(right, right_field)


def _aware_datetime(value: Any, field: str) -> datetime:
    if type(value) is not str:
        raise CycleReservationError(f"CYCLE_RESERVATION_TIME_INVALID:{field}")
    if len(value) > MAX_CYCLE_RESERVATION_TEXT_BYTES:
        raise CycleReservationError(f"CYCLE_RESERVATION_TIME_RESOURCE_LIMIT_EXCEEDED:{field}")
    raw = value.strip()
    if not raw:
        raise CycleReservationError(f"CYCLE_RESERVATION_TIME_INVALID:{field}")
    try:
        parsed = datetime.fromisoformat(f"{raw[:-1]}+00:00" if raw.endswith("Z") else raw)
    except ValueError as exc:
        raise CycleReservationError(f"CYCLE_RESERVATION_TIME_INVALID:{field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CycleReservationError(f"CYCLE_RESERVATION_TIME_NOT_AWARE:{field}")
    return parsed.astimezone(UTC)


def cycle_reservation_persisted_row_projection(
    row: Mapping[str, Any],
) -> dict[str, Any]:
    """Rebuild the paper loop's canonical immutable-row projection.

    Keeping this pure projection next to prior-row replay prevents that replay
    from trusting a coherently rehashed final contract whose top-level row was
    changed after the allocator/cycle snapshot was sealed.
    """

    return {
        "schema_version": _PERSISTED_ROW_PROJECTION_SCHEMA_VERSION,
        "critical_fields": {
            field: row.get(field)
            for field in (
                *_PERSISTED_ADMISSION_CRITICAL_FIELDS,
                *_PERSISTED_ADMISSION_COMPONENT_TIME_FIELDS,
            )
        },
        "nested_payload_hashes": {
            field: _canonical_sha256(row.get(field)) for field in _PERSISTED_ADMISSION_NESTED_FIELDS
        },
    }


def _allocation_economics(
    allocation_value: Any,
    *,
    expected_symbol: str,
    required_snapshot_hash: str | None,
) -> dict[str, Any]:
    """Validate canonical allocator identity and extract exact resource fields."""

    allocation = _mapping(allocation_value, "adaptive_allocation")
    reasons: list[str] = []
    allocation_symbol = allocation.get("symbol")
    allocation_timeframe = allocation.get("timeframe")
    allocation_action = allocation.get("action")
    if type(allocation_symbol) is not str or allocation_symbol != expected_symbol:
        reasons.append("CYCLE_RESERVATION_ALLOCATION_SYMBOL_MISMATCH")
    if (
        type(allocation_timeframe) is not str
        or not allocation_timeframe
        or allocation_timeframe != allocation_timeframe.strip()
    ):
        reasons.append("CYCLE_RESERVATION_ALLOCATION_TIMEFRAME_INVALID")
    if type(allocation_action) is not str or allocation_action not in {"long", "short"}:
        reasons.append("CYCLE_RESERVATION_ALLOCATION_ACTION_INVALID")
    if (
        type(allocation.get("allocator_decision")) is not str
        or allocation.get("allocator_decision") not in _SIZABLE_ALLOCATOR_DECISIONS
    ):
        reasons.append("CYCLE_RESERVATION_ALLOCATION_NOT_SIZABLE")
    if allocation.get("paper_only") is not True or any(
        allocation.get(field) is not False
        for field in (
            "routes_to_live",
            "places_real_order",
            "live_order",
            "test_order",
            "leverage_mutation",
            "margin_mode_mutation",
        )
    ):
        reasons.append("CYCLE_RESERVATION_ALLOCATION_PAPER_SAFETY_FLAGS_INVALID")

    input_material = allocation.get("allocation_input_material")
    material = input_material if type(input_material) is dict else {}
    allocation_input = material.get("allocation_input")
    input_row = allocation_input if type(allocation_input) is dict else {}
    input_hash = allocation.get("allocation_input_hash")
    if (
        allocation.get("allocation_input_schema_version") != _ALLOCATION_INPUT_SCHEMA_VERSION
        or allocation.get("allocation_input_hash_algorithm") != _ALLOCATION_INPUT_HASH_ALGORITHM
        or material.get("schema_version") != _ALLOCATION_INPUT_SCHEMA_VERSION
        or material.get("mode") != "paper"
        or not _valid_sha256(input_hash)
        or input_hash != _canonical_sha256(material)
    ):
        reasons.append("CYCLE_RESERVATION_ALLOCATION_INPUT_IDENTITY_INVALID")
    allocation_id = allocation.get("allocation_id")
    if type(allocation_id) is not str or allocation_id != f"alloc_{str(input_hash)[:24]}":
        reasons.append("CYCLE_RESERVATION_ALLOCATION_ID_INVALID")
    for field, output_value in (
        ("symbol", allocation_symbol),
        ("timeframe", allocation_timeframe),
        ("action", allocation_action),
    ):
        input_value = input_row.get(field)
        if (
            type(input_value) is not str
            or type(output_value) is not str
            or input_value != output_value
        ):
            reasons.append(f"CYCLE_RESERVATION_ALLOCATION_INPUT_{field.upper()}_MISMATCH")
    if input_row.get("symbol") != expected_symbol:
        reasons.append("CYCLE_RESERVATION_ALLOCATION_INPUT_SYMBOL_MISMATCH")

    output_lineage = allocation.get("lineage_ids")
    input_lineage = input_row.get("lineage_ids")
    if type(output_lineage) is not dict or type(input_lineage) is not dict:
        reasons.append("CYCLE_RESERVATION_ALLOCATION_LINEAGE_MISSING")
    elif not _type_exact_json_equal(output_lineage, input_lineage):
        reasons.append("CYCLE_RESERVATION_ALLOCATION_LINEAGE_MISMATCH")
    if required_snapshot_hash is not None and (
        type(output_lineage) is not dict
        or output_lineage.get(CYCLE_RESERVATION_LINEAGE_KEY) != required_snapshot_hash
        or type(input_lineage) is not dict
        or input_lineage.get(CYCLE_RESERVATION_LINEAGE_KEY) != required_snapshot_hash
    ):
        reasons.append("CYCLE_RESERVATION_ALLOCATION_SNAPSHOT_LINEAGE_MISMATCH")

    model_inputs_value = allocation.get("model_inputs")
    model_inputs = model_inputs_value if type(model_inputs_value) is dict else {}
    if (
        not model_inputs
        or model_inputs.get("allocation_input_schema_version") != _ALLOCATION_INPUT_SCHEMA_VERSION
        or model_inputs.get("allocation_input_hash_algorithm") != _ALLOCATION_INPUT_HASH_ALGORITHM
        or model_inputs.get("allocation_input_hash") != input_hash
        or model_inputs.get("paper_post_quantization_exchange_filter_status") != "PASS"
        or model_inputs.get("paper_margin_configuration_uses_post_quantization_notional")
        is not True
    ):
        reasons.append("CYCLE_RESERVATION_ALLOCATION_UPSTREAM_QUANTIZATION_RECEIPT_INVALID")

    arithmetic_receipt: dict[str, Any] = {}
    arithmetic_operands: dict[str, float] = {}
    permitted_binary64_hex: set[str] = set()
    try:
        arithmetic_receipt, arithmetic_operands = _validated_allocator_arithmetic_receipt(
            model_inputs.get(CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY)
        )
    except CycleReservationError as exc:
        reasons.extend(exc.reasons)

    def positive_output(value: Any, field: str) -> Decimal:
        if isinstance(value, bool) or type(value) not in (int, float):
            reasons.append(f"CYCLE_RESERVATION_ALLOCATION_OUTPUT_NUMERIC_TYPE_INVALID:{field}")
            return Decimal(0)
        try:
            return _positive_decimal(value, field)
        except CycleReservationError as exc:
            reasons.extend(exc.reasons)
            return Decimal(0)

    try:
        notional = positive_output(
            allocation.get("gross_notional_usd"),
            "adaptive_allocation.gross_notional_usd",
        )
        notional_aliases: dict[str, Decimal] = {}
        for alias in ("target_notional_usdt", "target_notional_usd"):
            alias_value = positive_output(allocation.get(alias), f"adaptive_allocation.{alias}")
            notional_aliases[alias] = alias_value
            if alias_value != notional:
                reasons.append(f"CYCLE_RESERVATION_ALLOCATION_NOTIONAL_ALIAS_MISMATCH:{alias}")
        margin = positive_output(
            allocation.get("allocated_margin_usd"),
            "adaptive_allocation.allocated_margin_usd",
        )
        max_loss = positive_output(
            allocation.get("max_loss_if_stop_hit"),
            "adaptive_allocation.max_loss_if_stop_hit",
        )
        max_loss_alias = positive_output(
            allocation.get("max_loss_usd"),
            "adaptive_allocation.max_loss_usd",
        )
        if max_loss_alias != max_loss:
            reasons.append("CYCLE_RESERVATION_ALLOCATION_MAX_LOSS_ALIAS_MISMATCH")
        quantity = positive_output(
            allocation.get("target_quantity"),
            "adaptive_allocation.target_quantity",
        )
        leverage = positive_output(
            allocation.get("effective_leverage"),
            "adaptive_allocation.effective_leverage",
        )
        recommended_leverage = positive_output(
            allocation.get("recommended_leverage"),
            "adaptive_allocation.recommended_leverage",
        )
        input_price_value = input_row.get("price")
        positive_output(
            input_price_value,
            "adaptive_allocation.allocation_input.price",
        )
        upstream_quantity = positive_output(
            model_inputs.get("paper_target_quantity_after_step_quantization"),
            "adaptive_allocation.model_inputs.paper_target_quantity_after_step_quantization",
        )
        upstream_notional = positive_output(
            model_inputs.get("paper_target_notional_after_step_quantization_usd"),
            "adaptive_allocation.model_inputs.paper_target_notional_after_step_quantization_usd",
        )
        upstream_max_loss = positive_output(
            model_inputs.get("max_loss_usd"),
            "adaptive_allocation.model_inputs.max_loss_usd",
        )
        upstream_loss_bps = positive_output(
            model_inputs.get("paper_modeled_loss_bps"),
            "adaptive_allocation.model_inputs.paper_modeled_loss_bps",
        )
        upstream_selected_leverage_value = model_inputs.get("selected_leverage")
        upstream_selected_leverage = positive_output(
            upstream_selected_leverage_value,
            "adaptive_allocation.model_inputs.selected_leverage",
        )
        upstream_selected_margin_value = model_inputs.get("selected_allocated_margin_usd")
        upstream_selected_margin = positive_output(
            upstream_selected_margin_value,
            "adaptive_allocation.model_inputs.selected_allocated_margin_usd",
        )
        if recommended_leverage != leverage:
            reasons.append("CYCLE_RESERVATION_ALLOCATION_LEVERAGE_ALIAS_MISMATCH")
        if (
            type(upstream_selected_leverage_value) is not type(allocation.get("effective_leverage"))
            or upstream_selected_leverage != leverage
        ):
            reasons.append("CYCLE_RESERVATION_ALLOCATION_UPSTREAM_SELECTED_LEVERAGE_MISMATCH")
        if (
            type(upstream_selected_margin_value) is not type(allocation.get("allocated_margin_usd"))
            or upstream_selected_margin != margin
        ):
            reasons.append("CYCLE_RESERVATION_ALLOCATION_UPSTREAM_SELECTED_MARGIN_MISMATCH")
        if quantity != upstream_quantity:
            reasons.append("CYCLE_RESERVATION_ALLOCATION_QUANTITY_UPSTREAM_MISMATCH")
        if notional != upstream_notional:
            reasons.append("CYCLE_RESERVATION_ALLOCATION_NOTIONAL_UPSTREAM_MISMATCH")
        if max_loss != upstream_max_loss:
            reasons.append("CYCLE_RESERVATION_ALLOCATION_MAX_LOSS_UPSTREAM_MISMATCH")
        if _allocator_quantize(quantity, _ALLOCATOR_QUANTITY_QUANTUM, "quantity") != quantity:
            reasons.append("CYCLE_RESERVATION_ALLOCATION_QUANTITY_QUANTIZATION_INVALID")
        if _allocator_quantize(notional, _ALLOCATOR_USD_QUANTUM, "notional") != notional:
            reasons.append("CYCLE_RESERVATION_ALLOCATION_NOTIONAL_QUANTIZATION_INVALID")
        if _allocator_quantize(margin, _ALLOCATOR_USD_QUANTUM, "margin") != margin:
            reasons.append("CYCLE_RESERVATION_ALLOCATION_MARGIN_QUANTIZATION_INVALID")
        if _allocator_quantize(leverage, _ALLOCATOR_LEVERAGE_QUANTUM, "leverage") != leverage:
            reasons.append("CYCLE_RESERVATION_ALLOCATION_LEVERAGE_QUANTIZATION_INVALID")
        if _allocator_quantize(max_loss, _ALLOCATOR_USD_QUANTUM, "max_loss") != max_loss:
            reasons.append("CYCLE_RESERVATION_ALLOCATION_MAX_LOSS_QUANTIZATION_INVALID")
        if arithmetic_operands:
            raw_quantity = arithmetic_operands["raw_post_step_quantity_binary64_hex"]
            receipt_price = arithmetic_operands["input_price_binary64_hex"]
            raw_notional = arithmetic_operands["raw_post_step_notional_binary64_hex"]
            raw_leverage = arithmetic_operands["selected_leverage_binary64_hex"]
            permitted_leverage_values = input_row.get("permitted_leverage_values")
            if (
                not isinstance(permitted_leverage_values, list | tuple)
                or not permitted_leverage_values
            ):
                reasons.append("CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_PERMITTED_LEVERAGE_INVALID")
            else:
                for permitted_value in permitted_leverage_values:
                    if type(permitted_value) is int:
                        try:
                            permitted_binary64 = float(permitted_value)
                        except (MemoryError, OverflowError, TypeError, ValueError):
                            permitted_binary64 = 0.0
                    elif type(permitted_value) is float:
                        permitted_binary64 = permitted_value
                    else:
                        permitted_binary64 = 0.0
                    if not math.isfinite(permitted_binary64) or permitted_binary64 < 1.0:
                        reasons.append(
                            "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_PERMITTED_LEVERAGE_INVALID"
                        )
                    else:
                        permitted_binary64_hex.add(permitted_binary64.hex())
            if raw_leverage.hex() not in permitted_binary64_hex:
                reasons.append(
                    "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_SELECTED_LEVERAGE_NOT_PERMITTED"
                )
            bound_input_price = 0.0
            if type(input_price_value) is int:
                try:
                    bound_input_price = float(input_price_value)
                except (MemoryError, OverflowError, TypeError, ValueError):
                    pass
            elif type(input_price_value) is float:
                bound_input_price = input_price_value
            else:
                reasons.append("CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_INPUT_PRICE_TYPE_INVALID")
            if (
                not math.isfinite(bound_input_price)
                or bound_input_price <= 0.0
                or bound_input_price.hex() != receipt_price.hex()
            ):
                reasons.append("CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_INPUT_PRICE_MISMATCH")
            try:
                recomputed_raw_notional = abs(raw_quantity * receipt_price)
            except (ArithmeticError, MemoryError, OverflowError, ValueError):
                recomputed_raw_notional = 0.0
            if (
                not math.isfinite(recomputed_raw_notional)
                or recomputed_raw_notional <= 0.0
                or recomputed_raw_notional != raw_notional
            ):
                reasons.append("CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RAW_NOTIONAL_MISMATCH")

            expected_quantity = _allocator_binary64_round_decimal(
                raw_quantity,
                12,
                "allocator_published_quantity",
            )
            expected_notional = _allocator_binary64_round_decimal(
                raw_notional,
                8,
                "allocator_published_notional",
            )
            expected_leverage = _allocator_binary64_round_decimal(
                raw_leverage,
                8,
                "allocator_published_leverage",
            )
            try:
                raw_margin = raw_notional / raw_leverage
            except (ArithmeticError, MemoryError, OverflowError, ValueError):
                raw_margin = 0.0
            if not math.isfinite(raw_margin) or raw_margin <= 0.0:
                reasons.append("CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_MARGIN_INVALID")
                expected_margin = Decimal(0)
            else:
                expected_margin = _allocator_binary64_round_decimal(
                    raw_margin,
                    8,
                    "allocator_published_margin",
                )

            for alias, observed in (
                ("target_quantity", quantity),
                ("model_inputs.paper_target_quantity_after_step_quantization", upstream_quantity),
            ):
                if observed != expected_quantity:
                    reasons.append(
                        f"CYCLE_RESERVATION_ALLOCATION_QUANTITY_RECEIPT_MISMATCH:{alias}"
                    )
            for alias, observed in (
                ("gross_notional_usd", notional),
                ("target_notional_usdt", notional_aliases["target_notional_usdt"]),
                ("target_notional_usd", notional_aliases["target_notional_usd"]),
                (
                    "model_inputs.paper_target_notional_after_step_quantization_usd",
                    upstream_notional,
                ),
            ):
                if observed != expected_notional:
                    reasons.append(
                        f"CYCLE_RESERVATION_ALLOCATION_NOTIONAL_RECEIPT_MISMATCH:{alias}"
                    )
            for alias, observed in (
                ("effective_leverage", leverage),
                ("recommended_leverage", recommended_leverage),
                ("model_inputs.selected_leverage", upstream_selected_leverage),
            ):
                if observed != expected_leverage:
                    reasons.append(
                        f"CYCLE_RESERVATION_ALLOCATION_LEVERAGE_RECEIPT_MISMATCH:{alias}"
                    )
            for alias, observed in (
                ("allocated_margin_usd", margin),
                ("model_inputs.selected_allocated_margin_usd", upstream_selected_margin),
            ):
                if observed != expected_margin:
                    reasons.append(f"CYCLE_RESERVATION_ALLOCATION_MARGIN_RECEIPT_MISMATCH:{alias}")
        modeled_loss = _allocator_quantize(
            _deterministic_divide(
                _exact_multiply(notional, upstream_loss_bps),
                _BASIS_POINTS_PER_UNIT,
                "allocator_modeled_max_loss",
            ),
            _ALLOCATOR_USD_QUANTUM,
            "allocator_modeled_max_loss",
        )
        if modeled_loss != max_loss:
            reasons.append("CYCLE_RESERVATION_ALLOCATION_MAX_LOSS_AUTHORITY_INVALID")
    except CycleReservationError as exc:
        reasons.extend(exc.reasons)
        notional = margin = max_loss = Decimal(0)

    if reasons:
        raise CycleReservationError(*reasons)
    return {
        "allocation_id": allocation_id,
        "allocation_input_hash": str(input_hash),
        "allocation_hash": _canonical_sha256(allocation),
        "allocator_arithmetic_receipt_sha256": arithmetic_receipt["receipt_sha256"],
        "symbol": expected_symbol,
        "timeframe": allocation_timeframe,
        "action": allocation_action,
        "gross_notional_usd": _number(notional, "candidate.gross_notional_usd"),
        "allocated_margin_usd": _number(margin, "candidate.allocated_margin_usd"),
        "max_loss_if_stop_hit_usd": _number(
            max_loss,
            "candidate.max_loss_if_stop_hit_usd",
        ),
        "exact_decimal_material": {
            "allocator_arithmetic_identity": CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_IDENTITY,
            "allocator_arithmetic_receipt_schema_version": arithmetic_receipt["schema_version"],
            "allocator_arithmetic_version": arithmetic_receipt["arithmetic_version"],
            "allocator_arithmetic_formula": arithmetic_receipt["formula"],
            "allocator_arithmetic_receipt_sha256": arithmetic_receipt["receipt_sha256"],
            "raw_post_step_quantity_binary64_hex": arithmetic_receipt[
                "raw_post_step_quantity_binary64_hex"
            ],
            "input_price_binary64_hex": arithmetic_receipt["input_price_binary64_hex"],
            "raw_post_step_notional_binary64_hex": arithmetic_receipt[
                "raw_post_step_notional_binary64_hex"
            ],
            "selected_leverage_binary64_hex": arithmetic_receipt["selected_leverage_binary64_hex"],
            "permitted_leverage_values_binary64_hex": sorted(permitted_binary64_hex),
            "gross_notional_usd": _canonical_decimal(
                notional,
                "candidate.gross_notional_usd",
            ),
            "allocated_margin_usd": _canonical_decimal(
                margin,
                "candidate.allocated_margin_usd",
            ),
            "max_loss_if_stop_hit_usd": _canonical_decimal(
                max_loss,
                "candidate.max_loss_if_stop_hit_usd",
            ),
        },
        "_gross_notional_decimal": notional,
        "_allocated_margin_decimal": margin,
        "_max_loss_if_stop_hit_decimal": max_loss,
    }


def _revocable_control_receipt_rejection_reasons(
    value: Any,
    *,
    final_decision_time: Any,
    final_validation_started_at: Any,
    paper_opportunity_tier: Any,
) -> tuple[str, ...]:
    """Validate the self-contained safety envelope on a revocable receipt."""

    try:
        receipt = _mapping(value, "revocable_control_commit_revalidation")
        material = dict(receipt)
        receipt_hash = material.pop("receipt_hash", None)
        reasons: list[str] = []
        if receipt.get("schema_version") != _REVOCABLE_CONTROL_COMMIT_SCHEMA_VERSION:
            reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_SCHEMA_INVALID")
        if receipt.get("status") != "PASS" or receipt.get("rejection_reasons") != []:
            reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_STATUS_INVALID")
        if (
            receipt.get("paper_only") is not True
            or receipt.get("routes_to_live") is not False
            or receipt.get("places_real_order") is not False
            or receipt.get("cross_process_atomic") is not False
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_SAFETY_FLAGS_INVALID")
        if (
            not isinstance(receipt.get("residual_toctou_risk"), str)
            or not str(receipt.get("residual_toctou_risk")).strip()
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_RESIDUAL_RISK_MISSING")
        parsed_times: dict[str, datetime] = {}
        for field, raw in (
            ("validation_started_at", receipt.get("validation_started_at")),
            ("checked_at", receipt.get("checked_at")),
            ("final_decision_time", final_decision_time),
            ("final_validation_started_at", final_validation_started_at),
        ):
            try:
                parsed_times[field] = _aware_datetime(raw, field)
            except CycleReservationError as exc:
                reasons.extend(exc.reasons)
        if receipt.get("validation_started_at") != final_validation_started_at:
            reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_VALIDATION_START_MISMATCH")
        started = parsed_times.get("validation_started_at")
        checked = parsed_times.get("checked_at")
        decision = parsed_times.get("final_decision_time")
        if (
            started is not None
            and checked is not None
            and decision is not None
            and not started <= checked <= decision
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_CLOCK_ORDER_INVALID")
        for field in (
            "source_revalidation",
            "guardian",
            "effective_entry_freeze",
            "current_risk_state",
            "runtime_owner",
        ):
            if not isinstance(receipt.get(field), Mapping):
                reasons.append(f"CYCLE_RESERVATION_PRIOR_REVOCABLE_FIELD_MISSING:{field}")

        tier = paper_opportunity_tier
        if type(tier) is not str or tier not in _EXECUTABLE_PAPER_TIERS:
            reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_PAPER_TIER_INVALID")

        source_value = receipt.get("source_revalidation")
        sources = source_value if type(source_value) is dict else {}
        if set(sources) != set(_REVOCABLE_SOURCE_STATUS_BY_ROLE):
            reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_SOURCE_ROLE_SET_INVALID")
        for role, allowed_statuses in _REVOCABLE_SOURCE_STATUS_BY_ROLE.items():
            source_value_for_role = sources.get(role)
            source = source_value_for_role if type(source_value_for_role) is dict else {}
            if not source:
                reasons.append(f"CYCLE_RESERVATION_PRIOR_REVOCABLE_SOURCE_RECEIPT_INVALID:{role}")
                continue
            read_status = source.get("read_status")
            source_key = source.get("source_key")
            present_expected = read_status == "READY"
            if (
                type(read_status) is not str
                or read_status not in allowed_statuses
                or source.get("source_kind") != "REDIS_EXACT_KEY"
                or type(source_key) is not str
                or source_key not in _REVOCABLE_SOURCE_KEYS_BY_ROLE[role]
                or source.get("present") is not present_expected
            ):
                reasons.append(f"CYCLE_RESERVATION_PRIOR_REVOCABLE_SOURCE_STATUS_INVALID:{role}")
            if (
                source.get("exact_match") is not True
                or source.get("source_label_match") is not True
                or not _valid_sha256(source.get("frozen_hash"))
                or source.get("frozen_hash") != source.get("current_hash")
            ):
                reasons.append(
                    f"CYCLE_RESERVATION_PRIOR_REVOCABLE_SOURCE_EXACT_MATCH_INVALID:{role}"
                )

        session_source = sources.get("paper_session_source")
        session = session_source if type(session_source) is dict else {}
        resolved_session_id = session.get("resolved_paper_session_id")
        if (
            type(resolved_session_id) is not str
            or not resolved_session_id
            or session.get("semantic_status") != "PASS"
            or not _type_exact_json_equal(
                session.get("semantic_rejection_reasons"),
                [],
            )
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_SESSION_SEMANTIC_INVALID")

        def tuning_semantic_receipt(
            field: str,
            *,
            status_field: str,
            hash_field: str,
        ) -> tuple[Mapping[str, Any], datetime | None, datetime | None, datetime | None]:
            tuning_source_value = sources.get("adaptive_tuning_source")
            tuning_source = tuning_source_value if type(tuning_source_value) is dict else {}
            semantic_value = tuning_source.get(field)
            semantic = semantic_value if type(semantic_value) is dict else {}
            semantic_material = dict(semantic)
            semantic_hash = semantic_material.pop("receipt_hash", None)
            if (
                not semantic
                or semantic.get("schema_version") != "paper_adaptive_tuning_semantic_validation_v1"
                or semantic.get("status") != "PASS"
                or semantic.get("rejection_reasons") != []
                or tuning_source.get(status_field) != "PASS"
                or not _valid_sha256(semantic_hash)
                or semantic_hash != _canonical_sha256(semantic_material)
                or semantic_hash != tuning_source.get(hash_field)
                or semantic.get("canonical_redis_key")
                != "v2:orchestrator:adaptive_gate_tuning_state"
                or not _valid_sha256(semantic.get("state_payload_hash"))
                or semantic.get("current_paper_session_id") != resolved_session_id
                or semantic.get("state_paper_session_id") != resolved_session_id
                or type(semantic.get("policy_id")) is not str
                or not semantic.get("policy_id")
                or type(semantic.get("producer")) is not str
                or not semantic.get("producer")
            ):
                reasons.append(f"CYCLE_RESERVATION_PRIOR_REVOCABLE_TUNING_SEMANTIC_INVALID:{field}")
            semantic_times: dict[str, datetime | None] = {}
            for time_field in ("available_at", "observed_at", "expires_at"):
                try:
                    semantic_times[time_field] = _aware_datetime(
                        semantic.get(time_field),
                        f"adaptive_tuning_source.{field}.{time_field}",
                    )
                except CycleReservationError as exc:
                    reasons.extend(exc.reasons)
                    semantic_times[time_field] = None
            available = semantic_times["available_at"]
            observed = semantic_times["observed_at"]
            expires = semantic_times["expires_at"]
            if (
                available is not None
                and observed is not None
                and expires is not None
                and decision is not None
                and started is not None
                and not available <= observed < expires
            ):
                reasons.append(f"CYCLE_RESERVATION_PRIOR_REVOCABLE_TUNING_CLOCK_INVALID:{field}")
            if (
                observed is not None
                and decision is not None
                and started is not None
                and not started <= observed <= decision
            ):
                reasons.append(
                    f"CYCLE_RESERVATION_PRIOR_REVOCABLE_TUNING_REREAD_CLOCK_INVALID:{field}"
                )
            if expires is not None and decision is not None and expires <= decision:
                reasons.append(f"CYCLE_RESERVATION_PRIOR_REVOCABLE_TUNING_EXPIRED:{field}")
            return semantic, available, observed, expires

        tuning_initial, _, tuning_initial_observed, _ = tuning_semantic_receipt(
            "semantic_validation",
            status_field="semantic_validation_status",
            hash_field="semantic_validation_receipt_hash",
        )
        tuning_commit, _, tuning_commit_observed, _ = tuning_semantic_receipt(
            "commit_clock_semantic_validation",
            status_field="commit_clock_semantic_validation_status",
            hash_field="commit_clock_semantic_validation_receipt_hash",
        )
        if (
            tuning_initial.get("state_payload_hash") != tuning_commit.get("state_payload_hash")
            or (
                tuning_initial_observed is not None
                and tuning_commit_observed is not None
                and tuning_initial_observed > tuning_commit_observed
            )
            or tuning_commit.get("observed_at") != receipt.get("checked_at")
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_TUNING_COMMIT_BINDING_INVALID")

        guardian_value = receipt.get("guardian")
        guardian = guardian_value if isinstance(guardian_value, Mapping) else {}
        ttl = guardian.get("ttl_remaining_seconds")
        ttl_range = guardian.get("ttl_required_range_seconds")
        guardian_allows = guardian.get("currently_allows_execution_tier")
        if type(guardian_allows) is not bool or (
            tier in _GUARDIAN_REQUIRED_PAPER_TIERS and guardian_allows is not True
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_GUARDIAN_BLOCKED")
        if (
            not isinstance(ttl, int)
            or isinstance(ttl, bool)
            or type(ttl_range) is not list
            or len(ttl_range) != 2
            or any(type(item) is not int for item in ttl_range)
            or tuple(ttl_range) != _GUARDIAN_TTL_REQUIRED_RANGE_SECONDS
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_GUARDIAN_TTL_INVALID")
        elif not (
            _GUARDIAN_TTL_REQUIRED_RANGE_SECONDS[0]
            <= ttl
            <= _GUARDIAN_TTL_REQUIRED_RANGE_SECONDS[1]
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_GUARDIAN_TTL_INVALID")
        if guardian.get("ttl_valid") is not True:
            reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_GUARDIAN_TTL_INVALID")

        freeze_value = receipt.get("effective_entry_freeze")
        freeze = freeze_value if isinstance(freeze_value, Mapping) else {}
        freeze_halted = freeze.get("paper_new_entries_halted")
        freeze_nonoverridable = freeze.get("nonoverridable")
        freeze_override_allowed = freeze.get("tier_override_allowed")
        if (
            freeze.get("exact_match") is not True
            or not _valid_sha256(freeze.get("frozen_hash"))
            or freeze.get("frozen_hash") != freeze.get("current_hash")
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_FREEZE_EXACT_MATCH_INVALID")
        if not all(
            isinstance(flag, bool)
            for flag in (
                freeze_halted,
                freeze_nonoverridable,
                freeze_override_allowed,
            )
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_FREEZE_FLAGS_INVALID")
        else:
            if freeze_halted is True and freeze_nonoverridable is True:
                reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_NONOVERRIDABLE_FREEZE_ACTIVE")
            if freeze_halted is True and freeze_override_allowed is not True:
                reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_FREEZE_OVERRIDE_NOT_AUTHORIZED")
            if freeze_halted is False and (
                freeze_nonoverridable is not False or freeze_override_allowed is not False
            ):
                reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_FREEZE_FLAGS_CONTRADICTORY")
            if freeze_override_allowed is True and tier not in _FREEZE_OVERRIDE_PAPER_TIERS:
                reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_FREEZE_TIER_UNAUTHORIZED")

        risk_value = receipt.get("current_risk_state")
        risk = risk_value if isinstance(risk_value, Mapping) else {}
        if (
            risk.get("exact_match") is not True
            or not _valid_sha256(risk.get("frozen_hash"))
            or risk.get("frozen_hash") != risk.get("current_hash")
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_RISK_EXACT_MATCH_INVALID")

        owner_value = receipt.get("runtime_owner")
        owner = owner_value if isinstance(owner_value, Mapping) else {}
        owner_projection_value = owner.get("current_projection")
        owner_projection = owner_projection_value if type(owner_projection_value) is dict else {}
        owner_conditions_value = owner_projection.get("pass_conditions")
        owner_conditions = owner_conditions_value if type(owner_conditions_value) is dict else {}
        owner_count_fields = (
            "canonical_paper_writer_count",
            "canonical_service_scope_writer_count",
            "forbidden_entry_process_count",
            "duplicate_paper_writer_count",
        )
        owner_projection_allows = bool(
            owner_projection.get("schema_version") == "paper_runtime_owner_minimal_projection_v1"
            and owner_projection.get("status") == "PASS_ACTIVE_RUNTIME_OWNER_VALIDATION"
            and owner_projection.get("active_new_entry_owner") == "v2_trade_management_paper_loop"
            and type(owner_projection.get("canonical_paper_writer_count")) is int
            and owner_projection.get("canonical_paper_writer_count") == 1
            and type(owner_projection.get("canonical_service_scope_writer_count")) is int
            and owner_projection.get("canonical_service_scope_writer_count") == 1
            and type(owner_projection.get("forbidden_entry_process_count")) is int
            and owner_projection.get("forbidden_entry_process_count") == 0
            and type(owner_projection.get("duplicate_paper_writer_count")) is int
            and owner_projection.get("duplicate_paper_writer_count") == 0
            and owner_projection.get("current_process_is_only_canonical_writer") is True
            and owner_projection.get("paper_online_runtime_active") is False
            and owner_projection.get("paper_online_runtime_enabled") is False
            and owner_projection.get("canonical_paper_runtime_enabled") is True
            and owner_projection.get("toy_momentum_entry_writer_active") is False
            and owner_projection.get("paper_only") is True
            and owner_projection.get("routes_to_live") is False
            and owner_projection.get("places_real_order") is False
            and set(owner_conditions) == set(_RUNTIME_OWNER_REQUIRED_PASS_CONDITIONS)
            and all(value is True for value in owner_conditions.values())
        )
        if (
            owner.get("exact_match") is not True
            or not _valid_sha256(owner.get("frozen_hash"))
            or owner.get("frozen_hash") != owner.get("current_hash")
            or owner.get("current_projection_allows") is not True
            or not owner_projection
            or owner.get("current_hash") != _canonical_sha256(owner_projection)
            or not owner_projection_allows
            or any(type(owner_projection.get(field)) is not int for field in owner_count_fields)
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_RUNTIME_EXACT_MATCH_INVALID")
        if not _valid_sha256(receipt_hash) or receipt_hash != _canonical_sha256(material):
            reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_RECEIPT_HASH_INVALID")
        return tuple(sorted(set(reasons)))
    except CycleReservationError as exc:
        return exc.reasons


def _prior_economic_alias_rejection_reasons(
    *,
    row: Mapping[str, Any],
    allocation: Mapping[str, Any],
    sizing: Mapping[str, Any],
    economics: Mapping[str, Any],
) -> tuple[str, ...]:
    """Replay every persisted sizing alias against allocator-owned economics."""

    reasons: list[str] = []

    def positive(value: Any, field: str) -> Decimal | None:
        try:
            return _positive_decimal(value, field)
        except CycleReservationError as exc:
            reasons.extend(exc.reasons)
            return None

    notional = positive(
        economics.get("gross_notional_usd"),
        "prior_allocation.gross_notional_usd",
    )
    margin = positive(
        economics.get("allocated_margin_usd"),
        "prior_allocation.allocated_margin_usd",
    )
    allocation_quantity = positive(
        allocation.get("target_quantity"),
        "prior_allocation.target_quantity",
    )
    allocation_leverage = positive(
        allocation.get("effective_leverage"),
        "prior_allocation.effective_leverage",
    )
    allocation_recommended_leverage = positive(
        allocation.get("recommended_leverage"),
        "prior_allocation.recommended_leverage",
    )
    sizing_fill_price = positive(
        sizing.get("fill_price"),
        "prior_final_admission.sizing.fill_price",
    )

    aliases: tuple[tuple[str, Any, Decimal | None], ...] = (
        ("quantity", row.get("quantity"), allocation_quantity),
        ("target_quantity", row.get("target_quantity"), allocation_quantity),
        ("fill_price", row.get("fill_price"), sizing_fill_price),
        ("entry_price", row.get("entry_price"), sizing_fill_price),
        ("notional", row.get("notional"), notional),
        ("target_notional_usd", row.get("target_notional_usd"), notional),
        ("target_notional_usdt", row.get("target_notional_usdt"), notional),
        ("gross_notional_usd", row.get("gross_notional_usd"), notional),
        (
            "recommended_leverage",
            row.get("recommended_leverage"),
            allocation_recommended_leverage,
        ),
        ("effective_leverage", row.get("effective_leverage"), allocation_leverage),
        ("allocated_margin_usd", row.get("allocated_margin_usd"), margin),
    )
    for field, raw, expected in aliases:
        observed = positive(raw, f"prior_row.{field}")
        if observed is not None and expected is not None and observed != expected:
            reasons.append(f"CYCLE_RESERVATION_PRIOR_ROW_ECONOMIC_ALIAS_MISMATCH:{field}")

    sizing_aliases: tuple[tuple[str, Any, Decimal | None], ...] = (
        ("quantity", sizing.get("quantity"), allocation_quantity),
        ("notional", sizing.get("notional"), notional),
        ("effective_leverage", sizing.get("effective_leverage"), allocation_leverage),
        ("allocated_margin_usd", sizing.get("allocated_margin_usd"), margin),
    )
    for field, raw, expected in sizing_aliases:
        observed = positive(raw, f"prior_final_admission.sizing.{field}")
        if observed is not None and expected is not None and observed != expected:
            reasons.append(f"CYCLE_RESERVATION_PRIOR_FINAL_SIZING_ALIAS_MISMATCH:{field}")

    expected_margin_mode = (
        str(allocation.get("recommended_margin_mode") or allocation.get("margin_mode") or "")
        .strip()
        .lower()
    )
    if not expected_margin_mode or any(
        str(value or "").strip().lower() != expected_margin_mode
        for value in (
            row.get("margin_mode_simulated"),
            row.get("recommended_margin_mode"),
            allocation.get("margin_mode"),
            sizing.get("margin_mode"),
        )
    ):
        reasons.append("CYCLE_RESERVATION_PRIOR_ROW_MARGIN_MODE_ALIAS_MISMATCH")

    if row.get("paper_only") is not True or any(
        row.get(field) is not False
        for field in (
            "routes_to_live",
            "places_real_order",
            "live_order",
            "test_order",
            "order_submitted",
            "test_order_submitted",
            "leverage_mutated",
            "margin_mutated",
        )
    ):
        reasons.append("CYCLE_RESERVATION_PRIOR_ROW_PAPER_SAFETY_FLAGS_INVALID")
    if allocation.get("paper_only") is not True or any(
        allocation.get(field) is not False
        for field in (
            "routes_to_live",
            "places_real_order",
            "live_order",
            "test_order",
            "leverage_mutation",
            "margin_mode_mutation",
        )
    ):
        reasons.append("CYCLE_RESERVATION_PRIOR_ALLOCATION_PAPER_SAFETY_FLAGS_INVALID")
    return tuple(sorted(set(reasons)))


def _decision_record_sha256(record: Mapping[str, Any]) -> str:
    """Mirror the per-ID decision-record hash contract used by the paper loop."""

    try:
        material = dict(record)
        return _strict_json_sha256(material, compact=False)
    except CycleReservationError:
        raise
    except (
        MemoryError,
        OverflowError,
        RecursionError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        raise CycleReservationError(
            "CYCLE_RESERVATION_PRIOR_DECISION_RECORD_CANONICAL_JSON_INVALID"
        ) from exc


def _normalized_side(value: Any, field: str) -> str:
    side = _text(value, field).lower()
    normalized = {"buy": "long", "sell": "short"}.get(side, side)
    if normalized not in {"long", "short"}:
        raise CycleReservationError(f"CYCLE_RESERVATION_SIDE_INVALID:{field}")
    return normalized


def _prior_authoritative_identity_binding_rejection_reasons(
    *,
    row: Mapping[str, Any],
    bound: Mapping[str, Any],
    allocation: Mapping[str, Any],
) -> tuple[str, ...]:
    """Cross-bind persisted identity copies without claiming authentication.

    The accepted row was authenticated against current Redis records at its
    original final-admission boundary.  This historical replay has only the
    persisted records and plain SHA-256 receipts.  It can prove that those
    independently stored copies still agree and are semantically well formed;
    it cannot prove source provenance against a writer capable of replacing
    every copy and coherently resealing every hash before this snapshot.
    """

    reasons: list[str] = []
    try:
        expected = {
            "signal_id": _text(row.get("signal_id"), "prior_row.signal_id"),
            "prediction_id": _text(
                row.get("prediction_id"),
                "prior_row.prediction_id",
            ),
            "risk_decision_id": _text(
                row.get("risk_decision_id"),
                "prior_row.risk_decision_id",
            ),
            "orchestrator_decision_id": _text(
                row.get("orchestrator_decision_id"),
                "prior_row.orchestrator_decision_id",
            ),
            "preemptive_decision_id": _text(
                row.get("preemptive_decision_id"),
                "prior_row.preemptive_decision_id",
            ),
            "symbol": _symbol(row.get("symbol"), "prior_row.symbol"),
            "timeframe": _text(row.get("timeframe"), "prior_row.timeframe"),
            "side": _normalized_side(row.get("side"), "prior_row.side"),
        }
    except CycleReservationError as exc:
        return exc.reasons

    material_value = allocation.get("allocation_input_material")
    material = material_value if isinstance(material_value, Mapping) else {}
    allocation_input_value = material.get("allocation_input")
    allocation_input = allocation_input_value if isinstance(allocation_input_value, Mapping) else {}
    output_lineage_value = allocation.get("lineage_ids")
    input_lineage_value = allocation_input.get("lineage_ids")
    output_lineage = output_lineage_value if isinstance(output_lineage_value, Mapping) else {}
    input_lineage = input_lineage_value if isinstance(input_lineage_value, Mapping) else {}
    if not allocation_input:
        reasons.append("CYCLE_RESERVATION_PRIOR_ALLOCATION_INPUT_MATERIAL_MISSING")
    for field in ("signal_id", "prediction_id", "risk_decision_id", "orchestrator_decision_id"):
        if (
            output_lineage.get(field) != expected[field]
            or input_lineage.get(field) != expected[field]
        ):
            reasons.append(f"CYCLE_RESERVATION_PRIOR_ALLOCATION_LINEAGE_ID_MISMATCH:{field}")
    allocation_identity = {
        "symbol": str(allocation.get("symbol") or "").strip().upper(),
        "timeframe": str(allocation.get("timeframe") or "").strip(),
        "side": str(allocation.get("action") or allocation.get("side") or "").strip().lower(),
    }
    input_identity = {
        "symbol": str(allocation_input.get("symbol") or "").strip().upper(),
        "timeframe": str(allocation_input.get("timeframe") or "").strip(),
        "side": str(allocation_input.get("action") or allocation_input.get("side") or "")
        .strip()
        .lower(),
    }
    expected_candidate = {
        "symbol": expected["symbol"],
        "timeframe": expected["timeframe"],
        "side": expected["side"],
    }
    if allocation_identity != expected_candidate:
        reasons.append("CYCLE_RESERVATION_PRIOR_ALLOCATION_CANDIDATE_IDENTITY_MISMATCH")
    if input_identity != expected_candidate:
        reasons.append("CYCLE_RESERVATION_PRIOR_ALLOCATION_INPUT_CANDIDATE_IDENTITY_MISMATCH")

    canonical_value = bound.get("canonical_decision_contract")
    canonical = canonical_value if isinstance(canonical_value, Mapping) else {}
    reread_value = canonical.get("final_reread")
    reread = reread_value if isinstance(reread_value, Mapping) else {}
    if not canonical:
        reasons.append("CYCLE_RESERVATION_PRIOR_CANONICAL_DECISION_CONTRACT_MISSING")
    final_decision_time = bound.get("final_decision_time")
    final_decision_utc: datetime | None = None
    try:
        final_decision_utc = _aware_datetime(
            final_decision_time,
            "prior_final_admission.final_decision_time",
        )
    except CycleReservationError as exc:
        reasons.extend(exc.reasons)

    for label in ("risk", "orchestrator"):
        id_field = f"{label}_decision_id"
        hash_field = f"{label}_decision_record_hash"
        record_field = f"{label}_decision_record"
        key_field = f"{label}_decision_record_key"
        source_field = f"{label}_decision_source"
        resolved_field = f"{label}_decision_record_resolved"
        record_value = row.get(record_field)
        record = record_value if isinstance(record_value, Mapping) else {}
        expected_id = expected[id_field]
        expected_key = f"v2:decision:{label}:{expected_id}"
        expected_schema = (
            "v2_per_id_risk_decision_record_v1"
            if label == "risk"
            else "v2_per_id_orchestrator_decision_record_v1"
        )
        expected_producer = (
            "v2_risk_gateway_live_loop" if label == "risk" else "v2_orchestrator_arbitration_loop"
        )
        if not record:
            reasons.append(f"CYCLE_RESERVATION_PRIOR_{label.upper()}_DECISION_RECORD_MISSING")
            continue
        try:
            record_hash = _decision_record_sha256(record)
        except CycleReservationError as exc:
            reasons.extend(exc.reasons)
            record_hash = ""
        if (
            not _valid_sha256(row.get(hash_field))
            or row.get(hash_field) != record_hash
            or canonical.get(hash_field) != record_hash
        ):
            reasons.append(f"CYCLE_RESERVATION_PRIOR_{label.upper()}_DECISION_RECORD_HASH_MISMATCH")
        if canonical.get(id_field) != expected_id:
            reasons.append(
                f"CYCLE_RESERVATION_PRIOR_{label.upper()}_CANONICAL_DECISION_ID_MISMATCH"
            )
        if (
            row.get(resolved_field) is not True
            or row.get(source_field) != "PER_ID_DECISION_RECORD"
            or row.get(key_field) != expected_key
            or record.get("schema_version") != expected_schema
            or record.get("producer") != expected_producer
            or record.get("_decision_record_key") != expected_key
            or record.get("_decision_record_store") != "PER_ID_DECISION_RECORD"
            or record.get(id_field) != expected_id
        ):
            reasons.append(
                f"CYCLE_RESERVATION_PRIOR_{label.upper()}_DECISION_RECORD_AUTHORITY_MISMATCH"
            )
        record_identity = {
            "symbol": str(record.get("symbol") or "").strip().upper(),
            "timeframe": str(record.get("timeframe") or "").strip(),
            "side": str(record.get("side") or "").strip().lower(),
            "prediction_id": str(record.get("prediction_id") or "").strip(),
            "signal_id": str(record.get("signal_id") or "").strip(),
        }
        expected_record_identity = {
            "symbol": expected["symbol"],
            "timeframe": expected["timeframe"],
            "side": expected["side"],
            "prediction_id": expected["prediction_id"],
            "signal_id": expected["signal_id"],
        }
        if record_identity != expected_record_identity:
            reasons.append(
                f"CYCLE_RESERVATION_PRIOR_{label.upper()}_DECISION_RECORD_IDENTITY_MISMATCH"
            )
        if (
            label == "risk"
            and record.get("orchestrator_decision_id") != expected["orchestrator_decision_id"]
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_RISK_DECISION_ORCHESTRATOR_ID_MISMATCH")
        if (
            record.get("paper_only") is not True
            or record.get("routes_to_live") is not False
            or record.get("places_real_order") is not False
            or record.get("live_gate") != "BLOCKED"
        ):
            reasons.append(
                f"CYCLE_RESERVATION_PRIOR_{label.upper()}_DECISION_RECORD_SAFETY_INVALID"
            )
        reread_value_for_label = reread.get(label)
        reread_receipt = (
            reread_value_for_label if isinstance(reread_value_for_label, Mapping) else {}
        )
        if (
            reread_receipt.get("source_key") != expected_key
            or reread_receipt.get("record_hash") != record_hash
            or reread_receipt.get("exact_match") is not True
        ):
            reasons.append(f"CYCLE_RESERVATION_PRIOR_{label.upper()}_FINAL_REREAD_BINDING_INVALID")
        try:
            reread_observed = _aware_datetime(
                reread_receipt.get("observed_at"),
                f"prior_final_admission.{label}_reread_observed_at",
            )
            if final_decision_utc is not None and reread_observed > final_decision_utc:
                reasons.append(
                    f"CYCLE_RESERVATION_PRIOR_{label.upper()}_FINAL_REREAD_CLOCK_INVALID"
                )
        except CycleReservationError as exc:
            reasons.extend(exc.reasons)

    preemptive_value = row.get("preemptive_edge_control")
    preemptive = preemptive_value if isinstance(preemptive_value, Mapping) else {}
    bound_preemptive = bound.get("preemptive_contract")
    preemptive_material_value = preemptive.get("preemptive_input_material")
    preemptive_material = (
        preemptive_material_value if isinstance(preemptive_material_value, Mapping) else {}
    )
    candidate_value = preemptive_material.get("candidate")
    candidate = candidate_value if isinstance(candidate_value, Mapping) else {}
    preemptive_hash = preemptive.get("preemptive_input_hash")
    if not preemptive or bound_preemptive != preemptive_value:
        reasons.append("CYCLE_RESERVATION_PRIOR_PREEMPTIVE_CONTRACT_BINDING_INVALID")
    if (
        preemptive.get("preemptive_decision_id") != expected["preemptive_decision_id"]
        or not _valid_sha256(preemptive_hash)
        or not preemptive_material
        or preemptive_material.get("schema_version") != "preemptive_edge_control_input_v2"
        or preemptive_hash != _canonical_sha256(preemptive_material)
        or row.get("preemptive_input_hash") != preemptive_hash
    ):
        reasons.append("CYCLE_RESERVATION_PRIOR_PREEMPTIVE_RECEIPT_IDENTITY_INVALID")
    preemptive_candidate_identity = {
        "symbol": str(candidate.get("symbol") or "").strip().upper(),
        "timeframe": str(
            candidate.get("timeframe") or candidate.get("thesis_timeframe") or ""
        ).strip(),
        "side": str(
            candidate.get("side")
            or candidate.get("action")
            or candidate.get("selected_action")
            or ""
        )
        .strip()
        .lower(),
        "prediction_id": str(
            candidate.get("prediction_id") or candidate.get("source_prediction_id") or ""
        ).strip(),
        "signal_id": str(candidate.get("signal_id") or "").strip(),
        "risk_decision_id": str(candidate.get("risk_decision_id") or "").strip(),
        "orchestrator_decision_id": str(candidate.get("orchestrator_decision_id") or "").strip(),
    }
    expected_preemptive_identity = {
        field: expected[field]
        for field in (
            "symbol",
            "timeframe",
            "side",
            "prediction_id",
            "signal_id",
            "risk_decision_id",
            "orchestrator_decision_id",
        )
    }
    if preemptive_candidate_identity != expected_preemptive_identity:
        reasons.append("CYCLE_RESERVATION_PRIOR_PREEMPTIVE_CANDIDATE_IDENTITY_MISMATCH")
    return tuple(sorted(set(reasons)))


def _prior_final_v3_semantic_rejection_reasons(
    *,
    row: Mapping[str, Any],
    contract: Mapping[str, Any],
    bound: Mapping[str, Any],
    allocation: Mapping[str, Any],
) -> tuple[str, ...]:
    """Replay the non-negotiable executable semantics of one final-v3 row."""

    reasons: list[str] = []
    tier = row.get("paper_opportunity_tier")
    if type(tier) is not str or tier not in _EXECUTABLE_PAPER_TIERS:
        reasons.append("CYCLE_RESERVATION_PRIOR_FINAL_EXECUTABLE_TIER_INVALID")
    if row.get("decision") != "ACCEPTED_PAPER_FILL":
        reasons.append("CYCLE_RESERVATION_PRIOR_FINAL_EXECUTABLE_DECISION_INVALID")
    if row.get("paper_fill_allowed") is not True:
        reasons.append("CYCLE_RESERVATION_PRIOR_FINAL_PAPER_FILL_ALLOWED_NOT_TRUE")
    if row.get("valid_for_paper") is not True:
        reasons.append("CYCLE_RESERVATION_PRIOR_FINAL_VALID_FOR_PAPER_NOT_TRUE")

    tier_contract_value = bound.get("tier_contract")
    tier_contract = tier_contract_value if type(tier_contract_value) is dict else {}
    expected_tier_contract = {field: row.get(field) for field in _FINAL_TIER_CONTRACT_FIELDS}
    if not _type_exact_json_equal(tier_contract, expected_tier_contract):
        reasons.append("CYCLE_RESERVATION_PRIOR_FINAL_TIER_CONTRACT_MISMATCH")

    safety_value = bound.get("safety_contract")
    safety = safety_value if type(safety_value) is dict else {}
    expected_safety = {
        "intent": {field: row.get(field) for field in _FINAL_ROW_SAFETY_FIELDS},
        "allocator": {field: allocation.get(field) for field in _FINAL_ALLOCATION_SAFETY_FIELDS},
    }
    if not _type_exact_json_equal(safety, expected_safety):
        reasons.append("CYCLE_RESERVATION_PRIOR_FINAL_SAFETY_CONTRACT_MISMATCH")

    canonical_value = bound.get("canonical_decision_contract")
    canonical = canonical_value if type(canonical_value) is dict else {}
    final_reread_value = canonical.get("final_reread")
    final_reread = final_reread_value if type(final_reread_value) is dict else {}
    contract_reread = contract.get("canonical_decision_record_revalidation")
    if not _type_exact_json_equal(contract_reread, final_reread):
        reasons.append("CYCLE_RESERVATION_PRIOR_FINAL_DECISION_REREAD_COPY_MISMATCH")

    expected_actions = {
        "risk": "allow",
        "orchestrator": f"proceed_{str(row.get('side') or '').lower()}",
    }
    for label, expected_action in expected_actions.items():
        action_field = f"{label}_action"
        record_value = row.get(f"{label}_decision_record")
        record = record_value if type(record_value) is dict else {}
        receipt_value = final_reread.get(label)
        receipt = receipt_value if type(receipt_value) is dict else {}
        if canonical.get(action_field) != expected_action:
            reasons.append(f"CYCLE_RESERVATION_PRIOR_FINAL_{label.upper()}_ACTION_INVALID")
        top_action_field = (
            "risk_controller_decision" if label == "risk" else "orchestrator_decision"
        )
        top_action_value = row.get(top_action_field)
        normalized_top_action = (
            top_action_value.strip().lower() if type(top_action_value) is str else ""
        )
        top_action_allows = bool(
            normalized_top_action.startswith(("pass", "allow", "approve"))
            or normalized_top_action in {"open_long", "open_short", "proceed_long", "proceed_short"}
        )
        if not top_action_allows:
            reasons.append(
                f"CYCLE_RESERVATION_PRIOR_FINAL_{label.upper()}_TOP_LEVEL_ACTION_INVALID"
            )
        record_action_field = "risk_action" if label == "risk" else "orchestrator_action"
        if record.get(record_action_field) != expected_action:
            reasons.append(f"CYCLE_RESERVATION_PRIOR_{label.upper()}_DECISION_ACTION_INVALID")
        if receipt.get("exact_match") is not True:
            reasons.append(f"CYCLE_RESERVATION_PRIOR_{label.upper()}_SEMANTIC_REVALIDATION_INVALID")

    preemptive_value = contract.get("preemptive_semantic_revalidation")
    bound_preemptive_value = bound.get("preemptive_semantic_revalidation")
    preemptive = preemptive_value if type(preemptive_value) is dict else {}
    if (
        not _type_exact_json_equal(preemptive_value, bound_preemptive_value)
        or preemptive.get("status") != "PASS"
        or not _type_exact_json_equal(preemptive.get("mismatch_fields"), [])
        or not _valid_sha256(preemptive.get("replay_projection_hash"))
    ):
        reasons.append("CYCLE_RESERVATION_PRIOR_PREEMPTIVE_SEMANTIC_REVALIDATION_INVALID")
    return tuple(sorted(set(reasons)))


def _prior_final_v3_point_in_time_rejection_reasons(
    *,
    row: Mapping[str, Any],
    contract: Mapping[str, Any],
    bound: Mapping[str, Any],
    revocable: Mapping[str, Any],
) -> tuple[str, ...]:
    """Replay persisted final-v3 clock ordering without consulting wall time."""

    reasons: list[str] = []
    parsed: dict[str, datetime] = {}

    def parse(field: str, value: Any, *, required: bool = True) -> datetime | None:
        if value in (None, "") and not required:
            return None
        try:
            parsed[field] = _aware_datetime(value, field)
            return parsed[field]
        except CycleReservationError as exc:
            reasons.extend(exc.reasons)
            return None

    validation_started = parse(
        "prior_final_admission.validation_started_at",
        contract.get("validation_started_at"),
    )
    final_decision = parse(
        "prior_final_admission.final_decision_time",
        contract.get("final_decision_time"),
    )
    component_value = bound.get("component_times")
    component_times = component_value if type(component_value) is dict else {}
    expected_component_times = {
        field: row.get(field) for field in _PERSISTED_ADMISSION_COMPONENT_TIME_FIELDS
    }
    if not _type_exact_json_equal(component_times, expected_component_times):
        reasons.append("CYCLE_RESERVATION_PRIOR_FINAL_COMPONENT_TIME_COPY_MISMATCH")
    if not _type_exact_json_equal(
        contract.get("component_time_fields_checked"),
        list(_PERSISTED_ADMISSION_COMPONENT_TIME_FIELDS),
    ):
        reasons.append("CYCLE_RESERVATION_PRIOR_FINAL_COMPONENT_TIME_ABI_INVALID")

    start = parse(
        "paper_precycle_exposure_snapshot_started_at",
        row.get("paper_precycle_exposure_snapshot_started_at"),
    )
    complete = parse(
        "paper_precycle_exposure_snapshot_completed_at",
        row.get("paper_precycle_exposure_snapshot_completed_at"),
    )
    allocation_time = parse(
        "paper_allocation_decision_time",
        row.get("paper_allocation_decision_time"),
    )
    if (
        start is not None
        and complete is not None
        and allocation_time is not None
        and final_decision is not None
        and not start <= complete <= allocation_time <= final_decision
    ):
        reasons.append("CYCLE_RESERVATION_PRIOR_FINAL_PRE_CYCLE_CLOCK_ORDER_INVALID")

    for field in _PERSISTED_ADMISSION_COMPONENT_TIME_FIELDS:
        if "available_at" not in field and "observed_at" not in field:
            continue
        component_time = parse(field, row.get(field), required=False)
        if (
            component_time is not None
            and final_decision is not None
            and component_time > final_decision
        ):
            reasons.append(f"CYCLE_RESERVATION_PRIOR_FINAL_COMPONENT_AFTER_DECISION:{field}")

    def validate_reread(field: str, value: Any) -> None:
        reread_time = parse(field, value)
        if (
            reread_time is not None
            and validation_started is not None
            and final_decision is not None
            and not validation_started <= reread_time <= final_decision
        ):
            reasons.append(f"CYCLE_RESERVATION_PRIOR_FINAL_REREAD_CLOCK_INVALID:{field}")

    decision_revalidation_value = contract.get("canonical_decision_record_revalidation")
    decision_revalidation = (
        decision_revalidation_value if type(decision_revalidation_value) is dict else {}
    )
    for label in ("risk", "orchestrator"):
        receipt_value = decision_revalidation.get(label)
        receipt = receipt_value if type(receipt_value) is dict else {}
        validate_reread(
            f"canonical_decision_record_revalidation.{label}.observed_at",
            receipt.get("observed_at"),
        )
    for contract_field in (
        "exchange_filter_revalidation",
        "maintenance_bracket_revalidation",
    ):
        receipt_value = contract.get(contract_field)
        receipt = receipt_value if type(receipt_value) is dict else {}
        if receipt.get("observed_at") not in (None, ""):
            validate_reread(
                f"{contract_field}.observed_at",
                receipt.get("observed_at"),
            )
    validate_reread("revocable_control.checked_at", revocable.get("checked_at"))
    sources_value = revocable.get("source_revalidation")
    sources = sources_value if type(sources_value) is dict else {}
    tuning_value = sources.get("adaptive_tuning_source")
    tuning = tuning_value if type(tuning_value) is dict else {}
    for field in (
        "semantic_validation",
        "commit_clock_semantic_validation",
    ):
        semantic_value = tuning.get(field)
        semantic = semantic_value if type(semantic_value) is dict else {}
        validate_reread(
            f"revocable_control.adaptive_tuning_source.{field}.observed_at",
            semantic.get("observed_at"),
        )
    return tuple(sorted(set(reasons)))


def _prior_reservation(row_value: Any, *, sequence_index: int) -> dict[str, Any]:
    """Normalize a prior only after replaying every admission proof it binds."""

    row = _mapping(row_value, f"prior_accepted_rows[{sequence_index}]")
    contract = row.get("paper_final_admission_contract")
    if not isinstance(contract, Mapping):
        raise CycleReservationError("CYCLE_RESERVATION_PRIOR_FINAL_CONTRACT_MISSING")

    reasons: list[str] = []
    contract_material = dict(contract)
    receipt_hash = contract_material.pop("receipt_hash", None)
    if (
        contract.get("schema_version") != _FINAL_ADMISSION_SCHEMA_VERSION
        or contract.get("status") != "PASS"
        or contract.get("rejection_reasons") != []
        or not _valid_sha256(receipt_hash)
        or receipt_hash != _canonical_sha256(contract_material)
        or receipt_hash != row.get("paper_final_admission_receipt_hash")
        or row.get("paper_final_admission_status") != "PASS"
    ):
        reasons.append("CYCLE_RESERVATION_PRIOR_FINAL_RECEIPT_INVALID")

    bound_material = contract.get("bound_material")
    bound = bound_material if isinstance(bound_material, Mapping) else {}
    bound_hash = contract.get("bound_material_hash")
    if (
        not bound
        or not _valid_sha256(bound_hash)
        or bound_hash != _canonical_sha256(bound)
        or bound_hash != row.get("paper_final_admission_bound_material_hash")
    ):
        reasons.append("CYCLE_RESERVATION_PRIOR_FINAL_BOUND_MATERIAL_INVALID")

    cycle_snapshot_value = row.get("paper_cycle_reservation_snapshot")
    cycle_snapshot = cycle_snapshot_value if isinstance(cycle_snapshot_value, Mapping) else {}
    cycle_snapshot_hash = row.get("paper_cycle_reservation_snapshot_hash")
    if not cycle_snapshot:
        reasons.append("CYCLE_RESERVATION_PRIOR_CYCLE_SNAPSHOT_MISSING")
    else:
        snapshot_reasons = cycle_reservation_snapshot_rejection_reasons(cycle_snapshot)
        if snapshot_reasons:
            reasons.append("CYCLE_RESERVATION_PRIOR_CYCLE_SNAPSHOT_INVALID")
            reasons.extend(snapshot_reasons)
    if not _valid_sha256(cycle_snapshot_hash) or cycle_snapshot_hash != cycle_snapshot.get(
        "snapshot_hash"
    ):
        reasons.append("CYCLE_RESERVATION_PRIOR_CYCLE_SNAPSHOT_HASH_MISMATCH")

    cycle_identity = str(cycle_snapshot.get("cycle_identity") or "").strip()
    cycle_commit_value = row.get("paper_cycle_reservation_commit_receipt")
    cycle_commit = cycle_commit_value if isinstance(cycle_commit_value, Mapping) else {}
    cycle_commit_hash = row.get("paper_cycle_reservation_commit_receipt_hash")
    cycle_commit_status = row.get("paper_cycle_reservation_commit_status")
    if not cycle_commit:
        reasons.append("CYCLE_RESERVATION_PRIOR_CYCLE_COMMIT_MISSING")
    if not _valid_sha256(cycle_commit_hash) or cycle_commit_hash != cycle_commit.get(
        "receipt_hash"
    ):
        reasons.append("CYCLE_RESERVATION_PRIOR_CYCLE_COMMIT_HASH_MISMATCH")
    if cycle_commit_status != "PASS" or cycle_commit.get("status") != "PASS":
        reasons.append("CYCLE_RESERVATION_PRIOR_CYCLE_COMMIT_STATUS_INVALID")

    cycle_bound_value = bound.get("cycle_reservation_contract")
    cycle_bound = cycle_bound_value if isinstance(cycle_bound_value, Mapping) else {}
    expected_cycle_bound = {
        "paper_cycle_reservation_snapshot": cycle_snapshot_value,
        "paper_cycle_reservation_snapshot_hash": cycle_snapshot_hash,
        "paper_cycle_reservation_commit_receipt": cycle_commit_value,
        "paper_cycle_reservation_commit_receipt_hash": cycle_commit_hash,
        "paper_cycle_reservation_commit_status": cycle_commit_status,
        "cycle_identity": cycle_identity,
    }
    if not cycle_bound or not _type_exact_json_equal(cycle_bound, expected_cycle_bound):
        reasons.append("CYCLE_RESERVATION_PRIOR_CYCLE_BOUND_MATERIAL_MISMATCH")

    revocable_value = row.get("paper_revocable_control_commit_revalidation")
    revocable = revocable_value if isinstance(revocable_value, Mapping) else {}
    revocable_hash = row.get("paper_revocable_control_commit_revalidation_receipt_hash")
    revocable_status = row.get("paper_revocable_control_commit_revalidation_status")
    if not revocable:
        reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_RECEIPT_MISSING")
    else:
        reasons.extend(
            _revocable_control_receipt_rejection_reasons(
                revocable,
                final_decision_time=contract.get("final_decision_time"),
                final_validation_started_at=contract.get("validation_started_at"),
                paper_opportunity_tier=row.get("paper_opportunity_tier"),
            )
        )
    if not _valid_sha256(revocable_hash) or revocable_hash != revocable.get("receipt_hash"):
        reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_RECEIPT_HASH_MISMATCH")
    if revocable_status != "PASS" or revocable.get("status") != "PASS":
        reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_STATUS_MISMATCH")
    if not _type_exact_json_equal(
        contract.get("revocable_control_commit_revalidation"),
        revocable_value,
    ) or not _type_exact_json_equal(
        bound.get("revocable_control_commit_revalidation"),
        revocable_value,
    ):
        reasons.append("CYCLE_RESERVATION_PRIOR_REVOCABLE_BOUND_MATERIAL_MISMATCH")

    identity = bound.get("identity")
    identity_map = identity if isinstance(identity, Mapping) else {}
    intent_id = str(identity_map.get("intent_id") or "").strip()
    symbol_value = str(identity_map.get("symbol") or "")
    expected_identity = {
        field: row.get(field)
        for field in (
            "intent_id",
            "signal_id",
            "prediction_id",
            "risk_decision_id",
            "orchestrator_decision_id",
            "allocation_id",
            "preemptive_decision_id",
            "symbol",
            "timeframe",
            "side",
        )
    }
    if not _type_exact_json_equal(identity_map, expected_identity):
        reasons.append("CYCLE_RESERVATION_PRIOR_FINAL_IDENTITY_MISMATCH")
    allocation_value = row.get("adaptive_allocation")
    allocation = allocation_value if isinstance(allocation_value, Mapping) else {}
    try:
        prior_symbol = _symbol(symbol_value, "prior_final_admission.identity.symbol")
        economics = _allocation_economics(
            allocation,
            expected_symbol=prior_symbol,
            required_snapshot_hash=(
                str(cycle_snapshot_hash) if _valid_sha256(cycle_snapshot_hash) else None
            ),
        )
    except CycleReservationError as exc:
        reasons.extend(exc.reasons)
        prior_symbol = str(symbol_value).strip().upper()
        economics = {}
    reasons.extend(
        _prior_authoritative_identity_binding_rejection_reasons(
            row=row,
            bound=bound,
            allocation=allocation,
        )
    )
    reasons.extend(
        _prior_final_v3_semantic_rejection_reasons(
            row=row,
            contract=contract,
            bound=bound,
            allocation=allocation,
        )
    )
    reasons.extend(
        _prior_final_v3_point_in_time_rejection_reasons(
            row=row,
            contract=contract,
            bound=bound,
            revocable=revocable,
        )
    )

    if cycle_commit:
        commit_reasons = intrinsic_candidate_commit_receipt_rejection_reasons(
            snapshot=cycle_snapshot,
            adaptive_allocation=allocation,
            receipt=cycle_commit,
        )
        if commit_reasons:
            reasons.append("CYCLE_RESERVATION_PRIOR_CYCLE_COMMIT_REPLAY_INVALID")
            reasons.extend(commit_reasons)

    if not intent_id:
        reasons.append("CYCLE_RESERVATION_PRIOR_INTENT_ID_MISSING")
    allocation_lineage_value = allocation.get("lineage_ids")
    allocation_lineage = (
        allocation_lineage_value if isinstance(allocation_lineage_value, Mapping) else {}
    )
    if allocation_lineage.get("intent_id") != intent_id or allocation_lineage.get(
        "intent_id"
    ) != row.get("intent_id"):
        reasons.append("CYCLE_RESERVATION_PRIOR_INTENT_LINEAGE_MISMATCH")
    if identity_map.get("allocation_id") != economics.get("allocation_id"):
        reasons.append("CYCLE_RESERVATION_PRIOR_FINAL_ALLOCATION_ID_MISMATCH")
    if str(row.get("symbol") or "").strip().upper() != prior_symbol:
        reasons.append("CYCLE_RESERVATION_PRIOR_ROW_SYMBOL_MISMATCH")
    if row.get("allocation_id") != economics.get("allocation_id"):
        reasons.append("CYCLE_RESERVATION_PRIOR_ROW_ALLOCATION_ID_MISMATCH")
    if not _type_exact_json_equal(
        row.get("paper_final_admission_decision_time"),
        contract.get("final_decision_time"),
    ) or not _type_exact_json_equal(
        bound.get("final_decision_time"),
        contract.get("final_decision_time"),
    ):
        reasons.append("CYCLE_RESERVATION_PRIOR_FINAL_TIME_MISMATCH")

    allocator_contract = bound.get("allocator_contract")
    allocator_bound = allocator_contract if isinstance(allocator_contract, Mapping) else {}
    if (
        bound.get("adaptive_allocation_hash") != economics.get("allocation_hash")
        or allocator_bound.get("allocation_hash") != economics.get("allocation_hash")
        or allocator_bound.get("allocation_id") != economics.get("allocation_id")
        or allocator_bound.get("allocation_input_hash") != economics.get("allocation_input_hash")
        or not _type_exact_json_equal(
            allocator_bound.get("allocation_input_material"),
            allocation.get("allocation_input_material"),
        )
    ):
        reasons.append("CYCLE_RESERVATION_PRIOR_FINAL_ALLOCATION_HASH_MISMATCH")

    sizing = bound.get("sizing")
    sizing_map = sizing if isinstance(sizing, Mapping) else {}
    try:
        if not _equal_decimal(
            sizing_map.get("notional"),
            economics.get("gross_notional_usd"),
            "prior_final_admission.sizing.notional",
            "prior_allocation.gross_notional_usd",
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_FINAL_NOTIONAL_MISMATCH")
        if not _equal_decimal(
            sizing_map.get("allocated_margin_usd"),
            economics.get("allocated_margin_usd"),
            "prior_final_admission.sizing.allocated_margin_usd",
            "prior_allocation.allocated_margin_usd",
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_FINAL_MARGIN_MISMATCH")
    except CycleReservationError as exc:
        reasons.extend(exc.reasons)
    reasons.extend(
        _prior_economic_alias_rejection_reasons(
            row=row,
            allocation=allocation,
            sizing=sizing_map,
            economics=economics,
        )
    )

    sealed_projection_value = bound.get("persisted_row_projection")
    sealed_projection = (
        sealed_projection_value if isinstance(sealed_projection_value, Mapping) else {}
    )
    sealed_projection_hash = bound.get("persisted_row_projection_hash")
    current_projection = cycle_reservation_persisted_row_projection(row)
    if (
        not sealed_projection
        or not _valid_sha256(sealed_projection_hash)
        or sealed_projection_hash != _canonical_sha256(sealed_projection)
        or not _type_exact_json_equal(sealed_projection, current_projection)
        or sealed_projection_hash != _canonical_sha256(current_projection)
    ):
        reasons.append("CYCLE_RESERVATION_PRIOR_PERSISTED_ROW_PROJECTION_INVALID")

    if reasons:
        raise CycleReservationError(*reasons)
    return {
        "schema_version": "paper_cycle_prior_reservation_v1",
        "sequence_index": sequence_index,
        "intent_id": intent_id,
        "symbol": prior_symbol,
        "allocation_id": economics["allocation_id"],
        "allocation_input_hash": economics["allocation_input_hash"],
        "adaptive_allocation_hash": economics["allocation_hash"],
        "allocator_arithmetic_receipt_sha256": economics["allocator_arithmetic_receipt_sha256"],
        "cycle_identity": cycle_identity,
        "cycle_reservation_snapshot_hash": cycle_snapshot_hash,
        "cycle_reservation_commit_receipt_hash": cycle_commit_hash,
        "revocable_control_commit_revalidation_receipt_hash": revocable_hash,
        "final_admission_receipt_hash": receipt_hash,
        "final_admission_bound_material_hash": bound_hash,
        "persisted_row_projection_hash": sealed_projection_hash,
        "final_decision_time": contract.get("final_decision_time"),
        "gross_notional_usd": economics["gross_notional_usd"],
        "allocated_margin_usd": economics["allocated_margin_usd"],
        "max_loss_if_stop_hit_usd": economics["max_loss_if_stop_hit_usd"],
        "resource_exact_decimal_material": dict(
            _mapping(
                economics.get("exact_decimal_material"),
                "prior.exact_decimal_material",
            )
        ),
        "resource_numeric_aliases_are_non_authoritative": True,
        "persisted_integrity_scope": (
            "SEMANTIC_REPLAY_AND_CROSS_BOUND_PLAIN_SHA256;NOT_SOURCE_AUTHENTICATION"
        ),
        "coherent_pre_snapshot_reseal_detectable": False,
    }


def _normalized_prior_reservation(value: Any, *, sequence_index: int) -> dict[str, Any]:
    reservation = _mapping(value, f"prior_reservations[{sequence_index}]")
    reasons: list[str] = []
    if reservation.get("schema_version") != "paper_cycle_prior_reservation_v1":
        reasons.append("CYCLE_RESERVATION_PRIOR_PROJECTION_SCHEMA_INVALID")
    supplied_sequence_index = reservation.get("sequence_index")
    if (
        not isinstance(supplied_sequence_index, int)
        or isinstance(supplied_sequence_index, bool)
        or supplied_sequence_index != sequence_index
    ):
        reasons.append("CYCLE_RESERVATION_PRIOR_SEQUENCE_INVALID")
    for field in (
        "intent_id",
        "allocation_id",
        "allocation_input_hash",
        "adaptive_allocation_hash",
        "allocator_arithmetic_receipt_sha256",
        "cycle_identity",
        "cycle_reservation_snapshot_hash",
        "cycle_reservation_commit_receipt_hash",
        "revocable_control_commit_revalidation_receipt_hash",
        "final_admission_receipt_hash",
        "final_admission_bound_material_hash",
        "persisted_row_projection_hash",
    ):
        value_at_field = reservation.get(field)
        if field.endswith("_hash") or field.endswith("_sha256"):
            if not _valid_sha256(value_at_field):
                reasons.append(f"CYCLE_RESERVATION_PRIOR_PROJECTION_HASH_INVALID:{field}")
        elif not isinstance(value_at_field, str) or not value_at_field.strip():
            reasons.append(f"CYCLE_RESERVATION_PRIOR_PROJECTION_TEXT_INVALID:{field}")
    try:
        resource_exact = _mapping(
            reservation.get("resource_exact_decimal_material"),
            "prior.resource_exact_decimal_material",
        )
        if resource_exact.get("allocator_arithmetic_identity") != (
            CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_IDENTITY
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_ALLOCATOR_ARITHMETIC_IDENTITY_INVALID")
        exact_arithmetic_receipt = {
            "schema_version": resource_exact.get("allocator_arithmetic_receipt_schema_version"),
            "arithmetic_version": resource_exact.get("allocator_arithmetic_version"),
            "formula": resource_exact.get("allocator_arithmetic_formula"),
            "raw_post_step_quantity_binary64_hex": resource_exact.get(
                "raw_post_step_quantity_binary64_hex"
            ),
            "input_price_binary64_hex": resource_exact.get("input_price_binary64_hex"),
            "raw_post_step_notional_binary64_hex": resource_exact.get(
                "raw_post_step_notional_binary64_hex"
            ),
            "selected_leverage_binary64_hex": resource_exact.get("selected_leverage_binary64_hex"),
            "receipt_sha256": resource_exact.get("allocator_arithmetic_receipt_sha256"),
        }
        _, exact_arithmetic_operands = _validated_allocator_arithmetic_receipt(
            exact_arithmetic_receipt
        )
        permitted_hex_value = resource_exact.get("permitted_leverage_values_binary64_hex")
        if type(permitted_hex_value) is not list or not permitted_hex_value:
            raise CycleReservationError(
                "CYCLE_RESERVATION_PRIOR_ALLOCATOR_PERMITTED_LEVERAGE_BINDING_INVALID"
            )
        normalized_permitted_hex: list[str] = []
        for permitted_hex in permitted_hex_value:
            parsed_permitted = _canonical_positive_binary64_hex(
                permitted_hex,
                "prior.permitted_leverage_values_binary64_hex",
            )
            if parsed_permitted < 1.0:
                raise CycleReservationError(
                    "CYCLE_RESERVATION_PRIOR_ALLOCATOR_PERMITTED_LEVERAGE_BINDING_INVALID"
                )
            normalized_permitted_hex.append(parsed_permitted.hex())
        if permitted_hex_value != sorted(set(normalized_permitted_hex)):
            raise CycleReservationError(
                "CYCLE_RESERVATION_PRIOR_ALLOCATOR_PERMITTED_LEVERAGE_BINDING_INVALID"
            )
        if (
            exact_arithmetic_receipt["selected_leverage_binary64_hex"]
            not in normalized_permitted_hex
        ):
            raise CycleReservationError(
                "CYCLE_RESERVATION_PRIOR_ALLOCATOR_SELECTED_LEVERAGE_NOT_PERMITTED"
            )
        if (
            reservation.get("allocator_arithmetic_receipt_sha256")
            != (exact_arithmetic_receipt["receipt_sha256"])
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_ALLOCATOR_ARITHMETIC_HASH_MISMATCH")
        exact_notional = _exact_decimal_from_material(
            numeric_alias=reservation.get("gross_notional_usd"),
            exact_material=resource_exact.get("gross_notional_usd"),
            field="prior.gross_notional_usd",
        )
        exact_margin = _exact_decimal_from_material(
            numeric_alias=reservation.get("allocated_margin_usd"),
            exact_material=resource_exact.get("allocated_margin_usd"),
            field="prior.allocated_margin_usd",
        )
        exact_max_loss = _exact_decimal_from_material(
            numeric_alias=reservation.get("max_loss_if_stop_hit_usd"),
            exact_material=resource_exact.get("max_loss_if_stop_hit_usd"),
            field="prior.max_loss_if_stop_hit_usd",
        )
        raw_quantity = exact_arithmetic_operands["raw_post_step_quantity_binary64_hex"]
        input_price = exact_arithmetic_operands["input_price_binary64_hex"]
        raw_notional = exact_arithmetic_operands["raw_post_step_notional_binary64_hex"]
        raw_leverage = exact_arithmetic_operands["selected_leverage_binary64_hex"]
        replayed_raw_notional = abs(raw_quantity * input_price)
        if (
            not math.isfinite(replayed_raw_notional)
            or replayed_raw_notional <= 0.0
            or replayed_raw_notional != raw_notional
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_ALLOCATOR_RAW_NOTIONAL_MISMATCH")
        if (
            _allocator_binary64_round_decimal(
                raw_notional,
                8,
                "prior.allocator_published_notional",
            )
            != exact_notional
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_ALLOCATOR_NOTIONAL_RECEIPT_MISMATCH")
        raw_margin = raw_notional / raw_leverage
        if (
            not math.isfinite(raw_margin)
            or raw_margin <= 0.0
            or _allocator_binary64_round_decimal(
                raw_margin,
                8,
                "prior.allocator_published_margin",
            )
            != exact_margin
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_ALLOCATOR_MARGIN_RECEIPT_MISMATCH")
        for field, exact_value in (
            ("gross_notional_usd", exact_notional),
            ("allocated_margin_usd", exact_margin),
            ("max_loss_if_stop_hit_usd", exact_max_loss),
        ):
            if exact_value <= 0:
                reasons.append(f"CYCLE_RESERVATION_NUMERIC_NOT_POSITIVE:prior.{field}")
        if reservation.get("resource_numeric_aliases_are_non_authoritative") is not True:
            reasons.append("CYCLE_RESERVATION_PRIOR_EXACT_DECIMAL_AUTHORITY_INVALID")
        if reservation.get("persisted_integrity_scope") != (
            "SEMANTIC_REPLAY_AND_CROSS_BOUND_PLAIN_SHA256;NOT_SOURCE_AUTHENTICATION"
        ):
            reasons.append("CYCLE_RESERVATION_PRIOR_INTEGRITY_SCOPE_INVALID")
        if reservation.get("coherent_pre_snapshot_reseal_detectable") is not False:
            reasons.append("CYCLE_RESERVATION_PRIOR_RESEAL_SCOPE_INVALID")
        normalized = {
            "schema_version": "paper_cycle_prior_reservation_v1",
            "sequence_index": sequence_index,
            "intent_id": _text(reservation.get("intent_id"), "prior.intent_id"),
            "symbol": _symbol(reservation.get("symbol"), "prior.symbol"),
            "allocation_id": _text(reservation.get("allocation_id"), "prior.allocation_id"),
            "allocation_input_hash": str(reservation.get("allocation_input_hash") or ""),
            "adaptive_allocation_hash": str(reservation.get("adaptive_allocation_hash") or ""),
            "allocator_arithmetic_receipt_sha256": str(
                reservation.get("allocator_arithmetic_receipt_sha256") or ""
            ),
            "cycle_identity": _text(reservation.get("cycle_identity"), "prior.cycle_identity"),
            "cycle_reservation_snapshot_hash": str(
                reservation.get("cycle_reservation_snapshot_hash") or ""
            ),
            "cycle_reservation_commit_receipt_hash": str(
                reservation.get("cycle_reservation_commit_receipt_hash") or ""
            ),
            "revocable_control_commit_revalidation_receipt_hash": str(
                reservation.get("revocable_control_commit_revalidation_receipt_hash") or ""
            ),
            "final_admission_receipt_hash": str(
                reservation.get("final_admission_receipt_hash") or ""
            ),
            "final_admission_bound_material_hash": str(
                reservation.get("final_admission_bound_material_hash") or ""
            ),
            "persisted_row_projection_hash": str(
                reservation.get("persisted_row_projection_hash") or ""
            ),
            "final_decision_time": _text(
                reservation.get("final_decision_time"),
                "prior.final_decision_time",
            ),
            "gross_notional_usd": _number(exact_notional, "prior.gross_notional_usd"),
            "allocated_margin_usd": _number(exact_margin, "prior.allocated_margin_usd"),
            "max_loss_if_stop_hit_usd": _number(
                exact_max_loss,
                "prior.max_loss_if_stop_hit_usd",
            ),
            "resource_exact_decimal_material": {
                "allocator_arithmetic_identity": (CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_IDENTITY),
                "allocator_arithmetic_receipt_schema_version": (
                    exact_arithmetic_receipt["schema_version"]
                ),
                "allocator_arithmetic_version": exact_arithmetic_receipt["arithmetic_version"],
                "allocator_arithmetic_formula": exact_arithmetic_receipt["formula"],
                "allocator_arithmetic_receipt_sha256": exact_arithmetic_receipt["receipt_sha256"],
                "raw_post_step_quantity_binary64_hex": exact_arithmetic_receipt[
                    "raw_post_step_quantity_binary64_hex"
                ],
                "input_price_binary64_hex": exact_arithmetic_receipt["input_price_binary64_hex"],
                "raw_post_step_notional_binary64_hex": exact_arithmetic_receipt[
                    "raw_post_step_notional_binary64_hex"
                ],
                "selected_leverage_binary64_hex": exact_arithmetic_receipt[
                    "selected_leverage_binary64_hex"
                ],
                "permitted_leverage_values_binary64_hex": normalized_permitted_hex,
                "gross_notional_usd": _canonical_decimal(
                    exact_notional,
                    "prior.gross_notional_usd",
                ),
                "allocated_margin_usd": _canonical_decimal(
                    exact_margin,
                    "prior.allocated_margin_usd",
                ),
                "max_loss_if_stop_hit_usd": _canonical_decimal(
                    exact_max_loss,
                    "prior.max_loss_if_stop_hit_usd",
                ),
            },
            "resource_numeric_aliases_are_non_authoritative": True,
            "persisted_integrity_scope": (
                "SEMANTIC_REPLAY_AND_CROSS_BOUND_PLAIN_SHA256;NOT_SOURCE_AUTHENTICATION"
            ),
            "coherent_pre_snapshot_reseal_detectable": False,
        }
    except CycleReservationError as exc:
        reasons.extend(exc.reasons)
        normalized = {}
    if reasons:
        raise CycleReservationError(*reasons)
    _aware_datetime(
        normalized["final_decision_time"],
        "prior.final_decision_time",
    )
    if dict(reservation) != normalized:
        raise CycleReservationError("CYCLE_RESERVATION_PRIOR_PROJECTION_EXTRA_OR_MUTATED")
    return normalized


def _prior_append_chain_rejection_reasons(
    *,
    prior_accepted_rows: Sequence[Mapping[str, Any]],
    reservations: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Prove that every accepted row was appended after its exact prefix."""

    reasons: list[str] = []
    previous_decision_time: datetime | None = None
    expected_prefix: list[dict[str, Any]] = []
    for index, (row_value, reservation) in enumerate(
        zip(prior_accepted_rows, reservations, strict=True)
    ):
        row = _mapping(row_value, f"prior_accepted_rows[{index}]")
        snapshot_value = row.get("paper_cycle_reservation_snapshot")
        snapshot = snapshot_value if isinstance(snapshot_value, Mapping) else {}
        prior_count = snapshot.get("prior_accepted_count")
        if (
            not isinstance(prior_count, int)
            or isinstance(prior_count, bool)
            or prior_count != index
            or snapshot.get("prior_reservations") != expected_prefix
        ):
            reasons.append(f"CYCLE_RESERVATION_PRIOR_APPEND_CHAIN_PREFIX_MISMATCH:{index}")
        expected_prefix.append(dict(reservation))
        try:
            decision_time = _aware_datetime(
                reservation.get("final_decision_time"),
                f"prior_accepted_rows[{index}].final_decision_time",
            )
        except CycleReservationError as exc:
            reasons.extend(exc.reasons)
            continue
        if previous_decision_time is not None and decision_time < previous_decision_time:
            reasons.append(f"CYCLE_RESERVATION_PRIOR_APPEND_CHAIN_TIME_ORDER_INVALID:{index}")
        previous_decision_time = decision_time
    return tuple(sorted(set(reasons)))


def _snapshot_material(
    *,
    cycle_identity: str,
    candidate_symbol: str,
    base_resource_evidence_hash: str,
    precycle_exposure_snapshot_hash: str,
    dynamic_envelope_evidence_hash: str,
    base_equity_usd: Decimal,
    base_available_margin_usd: Decimal,
    realized_drawdown_fraction_of_equity: Decimal,
    precycle_total_notional_usd: Decimal,
    precycle_symbol_current_mark_notional_usd: Decimal,
    precycle_open_projected_max_loss_usd: Decimal,
    max_total_portfolio_risk_pct: Decimal,
    max_single_symbol_exposure_pct: Decimal,
    min_available_margin_buffer_pct: Decimal,
    max_daily_drawdown_pct: Decimal,
    max_loss_per_trade_pct: Decimal,
    emergency_absolute_cap_usdt: Decimal | None,
    prior_reservations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    # Decimal material, not the compatibility float aliases, is authoritative
    # for all arithmetic and replay.  This keeps sub-float deltas visible in
    # the receipt instead of silently folding them into an IEEE-754 alias.
    def prior_resource(row: Mapping[str, Any], field: str) -> Decimal:
        exact_material = _mapping(
            row.get("resource_exact_decimal_material"),
            "prior.resource_exact_decimal_material",
        )
        return _exact_decimal_from_material(
            numeric_alias=row.get(field),
            exact_material=exact_material.get(field),
            field=f"prior.{field}",
        )

    prior_total = _exact_add(
        *(prior_resource(row, "gross_notional_usd") for row in prior_reservations)
    )
    prior_same_symbol = _exact_add(
        *(
            prior_resource(row, "gross_notional_usd")
            for row in prior_reservations
            if row["symbol"] == candidate_symbol
        )
    )
    prior_other_symbol = _exact_subtract(prior_total, prior_same_symbol)
    prior_margin = _exact_add(
        *(prior_resource(row, "allocated_margin_usd") for row in prior_reservations)
    )
    prior_max_loss = _exact_add(
        *(prior_resource(row, "max_loss_if_stop_hit_usd") for row in prior_reservations)
    )

    total_limit = _exact_multiply(base_equity_usd, max_total_portfolio_risk_pct)
    percentage_symbol_limit = _exact_multiply(
        base_equity_usd,
        max_single_symbol_exposure_pct,
    )
    symbol_limit = (
        min(percentage_symbol_limit, emergency_absolute_cap_usdt)
        if emergency_absolute_cap_usdt is not None
        else percentage_symbol_limit
    )
    total_before = _exact_add(precycle_total_notional_usd, prior_total)
    symbol_before = _exact_add(
        precycle_symbol_current_mark_notional_usd,
        prior_same_symbol,
    )
    remaining_total = max(Decimal(0), _exact_subtract(total_limit, total_before))
    remaining_symbol = max(Decimal(0), _exact_subtract(symbol_limit, symbol_before))

    margin_buffer = _exact_multiply(
        base_available_margin_usd,
        min_available_margin_buffer_pct,
    )
    remaining_margin = max(
        Decimal(0),
        _exact_subtract(base_available_margin_usd, margin_buffer, prior_margin),
    )
    realized_drawdown_usd = _exact_multiply(
        base_equity_usd,
        realized_drawdown_fraction_of_equity,
    )
    stress_limit = _exact_multiply(base_equity_usd, max_daily_drawdown_pct)
    stress_before = _exact_add(
        realized_drawdown_usd,
        precycle_open_projected_max_loss_usd,
        prior_max_loss,
    )
    remaining_stress = max(Decimal(0), _exact_subtract(stress_limit, stress_before))
    per_trade_limit = _exact_multiply(base_equity_usd, max_loss_per_trade_pct)
    remaining_candidate_risk = min(per_trade_limit, remaining_stress)
    remaining_candidate_risk_fraction_of_per_trade_limit = (
        _deterministic_divide(
            remaining_candidate_risk,
            per_trade_limit,
            "remaining_candidate_risk_fraction_of_per_trade_limit",
        )
        if per_trade_limit > 0
        else Decimal(0)
    )
    allocator_available_margin_input = (
        _deterministic_divide(
            remaining_margin,
            _exact_subtract(Decimal(1), min_available_margin_buffer_pct),
            "allocator_available_margin_input",
        )
        if min_available_margin_buffer_pct < 1
        else Decimal(0)
    )

    input_exact_decimals = {
        "base_equity_usd": _canonical_decimal(base_equity_usd, "base_equity_usd"),
        "base_available_margin_usd": _canonical_decimal(
            base_available_margin_usd,
            "base_available_margin_usd",
        ),
        "realized_drawdown_fraction_of_equity": _canonical_decimal(
            realized_drawdown_fraction_of_equity,
            "realized_drawdown_fraction_of_equity",
        ),
        "precycle_total_notional_usd": _canonical_decimal(
            precycle_total_notional_usd,
            "precycle_total_notional_usd",
        ),
        "precycle_symbol_current_mark_notional_usd": _canonical_decimal(
            precycle_symbol_current_mark_notional_usd,
            "precycle_symbol_current_mark_notional_usd",
        ),
        "precycle_open_projected_max_loss_usd": _canonical_decimal(
            precycle_open_projected_max_loss_usd,
            "precycle_open_projected_max_loss_usd",
        ),
    }
    limit_exact_decimals = {
        "max_total_portfolio_risk_pct": _canonical_decimal(
            max_total_portfolio_risk_pct,
            "max_total_portfolio_risk_pct",
        ),
        "max_single_symbol_exposure_pct": _canonical_decimal(
            max_single_symbol_exposure_pct,
            "max_single_symbol_exposure_pct",
        ),
        "min_available_margin_buffer_pct": _canonical_decimal(
            min_available_margin_buffer_pct,
            "min_available_margin_buffer_pct",
        ),
        "max_daily_drawdown_pct": _canonical_decimal(
            max_daily_drawdown_pct,
            "max_daily_drawdown_pct",
        ),
        "max_loss_per_trade_pct": _canonical_decimal(
            max_loss_per_trade_pct,
            "max_loss_per_trade_pct",
        ),
        "emergency_absolute_cap_usdt": (
            _canonical_decimal(
                emergency_absolute_cap_usdt,
                "emergency_absolute_cap_usdt",
            )
            if emergency_absolute_cap_usdt is not None
            else None
        ),
    }
    inputs = {
        "base_equity_usd": _number(base_equity_usd, "base_equity_usd"),
        "base_available_margin_usd": _number(
            base_available_margin_usd,
            "base_available_margin_usd",
        ),
        "realized_drawdown_fraction_of_equity": _number(
            realized_drawdown_fraction_of_equity,
            "realized_drawdown_fraction_of_equity",
        ),
        "precycle_total_notional_usd": _number(
            precycle_total_notional_usd,
            "precycle_total_notional_usd",
        ),
        "precycle_symbol_current_mark_notional_usd": _number(
            precycle_symbol_current_mark_notional_usd,
            "precycle_symbol_current_mark_notional_usd",
        ),
        "precycle_open_projected_max_loss_usd": _number(
            precycle_open_projected_max_loss_usd,
            "precycle_open_projected_max_loss_usd",
        ),
        "exact_decimal_material": input_exact_decimals,
        "numeric_aliases_are_non_authoritative": True,
        "dynamic_envelope_limits": {
            "max_total_portfolio_risk_pct": _number(
                max_total_portfolio_risk_pct,
                "max_total_portfolio_risk_pct",
            ),
            "max_single_symbol_exposure_pct": _number(
                max_single_symbol_exposure_pct,
                "max_single_symbol_exposure_pct",
            ),
            "min_available_margin_buffer_pct": _number(
                min_available_margin_buffer_pct,
                "min_available_margin_buffer_pct",
            ),
            "max_daily_drawdown_pct": _number(
                max_daily_drawdown_pct,
                "max_daily_drawdown_pct",
            ),
            "max_loss_per_trade_pct": _number(
                max_loss_per_trade_pct,
                "max_loss_per_trade_pct",
            ),
            "emergency_absolute_cap_usdt": (
                _number(emergency_absolute_cap_usdt, "emergency_absolute_cap_usdt")
                if emergency_absolute_cap_usdt is not None
                else None
            ),
            "exact_decimal_material": limit_exact_decimals,
            "numeric_aliases_are_non_authoritative": True,
        },
    }
    derived_values = {
        "realized_drawdown_usd": realized_drawdown_usd,
        "prior_reserved_total_notional_usd": prior_total,
        "prior_reserved_same_symbol_notional_usd": prior_same_symbol,
        "prior_reserved_other_symbol_notional_usd": prior_other_symbol,
        "prior_reserved_margin_usd": prior_margin,
        "prior_reserved_max_loss_usd": prior_max_loss,
        "effective_total_notional_before_candidate_usd": total_before,
        "effective_symbol_notional_before_candidate_usd": symbol_before,
        "total_notional_limit_usd": total_limit,
        "remaining_total_notional_usd": remaining_total,
        "symbol_notional_limit_usd": symbol_limit,
        "percentage_symbol_notional_limit_usd": percentage_symbol_limit,
        "remaining_symbol_notional_usd": remaining_symbol,
        "margin_buffer_usd": margin_buffer,
        "remaining_margin_after_buffer_usd": remaining_margin,
        "allocator_available_margin_input_usd": allocator_available_margin_input,
        "projected_stress_drawdown_limit_usd": stress_limit,
        "projected_stress_drawdown_before_candidate_usd": stress_before,
        "projected_stress_drawdown_before_candidate_fraction_of_equity": (
            _deterministic_divide(
                stress_before,
                base_equity_usd,
                "projected_stress_drawdown_before_candidate_fraction_of_equity",
            )
        ),
        "remaining_projected_stress_loss_usd": remaining_stress,
        "per_candidate_max_loss_limit_usd": per_trade_limit,
        "remaining_per_candidate_risk_budget_usd": remaining_candidate_risk,
        "remaining_per_candidate_risk_budget_fraction_of_equity": (
            _deterministic_divide(
                remaining_candidate_risk,
                base_equity_usd,
                "remaining_per_candidate_risk_budget_fraction_of_equity",
            )
        ),
        "remaining_candidate_risk_fraction_of_per_trade_limit": (
            remaining_candidate_risk_fraction_of_per_trade_limit
        ),
    }
    derived: dict[str, Any] = {
        field: _number(value, f"derived.{field}") for field, value in derived_values.items()
    }
    derived.update(
        {
            "exact_decimal_material": {
                field: _canonical_decimal(value, f"derived.{field}")
                for field, value in derived_values.items()
            },
            "numeric_aliases_are_non_authoritative": True,
        }
    )
    return {
        "schema_version": CYCLE_RESERVATION_SNAPSHOT_SCHEMA_VERSION,
        "status": "PASS",
        "cycle_identity": cycle_identity,
        "candidate_symbol": candidate_symbol,
        "evidence_bindings": {
            "base_resource_evidence_hash": base_resource_evidence_hash,
            "precycle_exposure_snapshot_hash": precycle_exposure_snapshot_hash,
            "dynamic_envelope_evidence_hash": dynamic_envelope_evidence_hash,
            "hash_contract": "sha256(canonical-json-v1)",
        },
        "inputs": inputs,
        "prior_accepted_count": len(prior_reservations),
        "prior_reservations": [dict(row) for row in prior_reservations],
        "derived": derived,
        "accounting_semantics": {
            "precycle_total_includes_precycle_symbol": True,
            "precycle_total_valuation_basis": "CURRENT_MARK_GROSS_NOTIONAL",
            "precycle_symbol_valuation_basis": "CURRENT_MARK_GROSS_NOTIONAL",
            "prior_reservations_are_not_in_precycle_total": True,
            "prior_same_symbol_counted_once_in_total_and_once_in_symbol_envelope": True,
            "total_limit_interpretation": (
                "MAX_TOTAL_PORTFOLIO_RISK_PCT_AS_GROSS_NOTIONAL_FRACTION_OF_BASE_EQUITY"
            ),
            "symbol_limit_interpretation": (
                "MIN_OF_DYNAMIC_SYMBOL_PERCENT_LIMIT_AND_OPTIONAL_EMERGENCY_ABSOLUTE_CAP"
            ),
            "realized_drawdown_is_not_prior_projected_loss": True,
            "precycle_open_projected_loss_is_counted_once": True,
            "margin_buffer_basis": "BASE_AVAILABLE_MARGIN_BEFORE_CURRENT_CYCLE_RESERVATIONS",
            "allocator_margin_adapter_semantics": (
                "INPUT_TIMES_ONE_MINUS_BUFFER_EQUALS_REMAINING_MARGIN_AFTER_BUFFER"
            ),
            "allocator_risk_adapter_semantics": (
                "REMAINING_CANDIDATE_RISK_DIVIDED_BY_DYNAMIC_PER_TRADE_LIMIT"
            ),
            "policy_limits_source": "CALLER_SUPPLIED_DYNAMIC_ENVELOPE_ONLY",
            "resource_arithmetic_authority": "CANONICAL_DECIMAL_MATERIAL",
            "json_number_aliases_are_authoritative": False,
            "persisted_hashes_authenticate_source_provenance": False,
            "persisted_hash_scope": "INTEGRITY_AND_SEMANTIC_CROSS_BINDING_ONLY",
            "coherent_pre_snapshot_nested_reseal_detectable": False,
            "coherent_pre_snapshot_nested_reseal_limitation": (
                "A_WRITER_THAT_CAN_REPLACE_EVERY_PERSISTED_SOURCE_RECORD_AND_RESEAL_"
                "EVERY_PLAIN_SHA256_BEFORE_THIS_SNAPSHOT_CANNOT_BE_DETECTED_HERE"
            ),
        },
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "rejection_reasons": [],
    }


def build_cycle_reservation_snapshot(
    *,
    cycle_identity: str,
    candidate_symbol: str,
    base_resource_evidence_hash: str,
    precycle_exposure_snapshot_hash: str,
    dynamic_envelope_evidence_hash: str,
    base_equity_usd: Any,
    base_available_margin_usd: Any,
    realized_drawdown_fraction_of_equity: Any,
    precycle_total_notional_usd: Any,
    precycle_symbol_current_mark_notional_usd: Any,
    precycle_open_projected_max_loss_usd: Any,
    max_total_portfolio_risk_pct: Any,
    max_single_symbol_exposure_pct: Any,
    min_available_margin_buffer_pct: Any,
    max_daily_drawdown_pct: Any,
    max_loss_per_trade_pct: Any,
    emergency_absolute_cap_usdt: Any,
    prior_accepted_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a canonical pre-allocation snapshot from explicit cycle evidence.

    ``prior_accepted_rows`` must contain rows that already passed the canonical
    final-admission contract.  Any missing, stale-shaped, or tampered receipt
    raises :class:`CycleReservationError`; callers must treat that as a block.
    """

    cycle = _text(cycle_identity, "cycle_identity")
    symbol = _symbol(candidate_symbol)
    base_evidence_hash = _sha256_text(
        base_resource_evidence_hash,
        "base_resource_evidence_hash",
    )
    exposure_evidence_hash = _sha256_text(
        precycle_exposure_snapshot_hash,
        "precycle_exposure_snapshot_hash",
    )
    envelope_evidence_hash = _sha256_text(
        dynamic_envelope_evidence_hash,
        "dynamic_envelope_evidence_hash",
    )
    prior_rows = _bounded_prior_sequence_copy(prior_accepted_rows)
    equity = _positive_decimal(base_equity_usd, "base_equity_usd")
    available_margin = _nonnegative_decimal(base_available_margin_usd, "base_available_margin_usd")
    realized_drawdown = _nonnegative_ratio(
        realized_drawdown_fraction_of_equity,
        "realized_drawdown_fraction_of_equity",
    )
    precycle_total = _nonnegative_decimal(
        precycle_total_notional_usd, "precycle_total_notional_usd"
    )
    precycle_symbol = _nonnegative_decimal(
        precycle_symbol_current_mark_notional_usd,
        "precycle_symbol_current_mark_notional_usd",
    )
    precycle_open_projected_loss = _nonnegative_decimal(
        precycle_open_projected_max_loss_usd,
        "precycle_open_projected_max_loss_usd",
    )
    if precycle_symbol > precycle_total:
        raise CycleReservationError("CYCLE_RESERVATION_PRE_CYCLE_SYMBOL_EXCEEDS_TOTAL_NOTIONAL")
    total_limit_fraction = _nonnegative_ratio(
        max_total_portfolio_risk_pct, "max_total_portfolio_risk_pct"
    )
    symbol_limit_fraction = _nonnegative_ratio(
        max_single_symbol_exposure_pct, "max_single_symbol_exposure_pct"
    )
    margin_buffer_fraction = _nonnegative_ratio(
        min_available_margin_buffer_pct, "min_available_margin_buffer_pct"
    )
    drawdown_limit_fraction = _nonnegative_ratio(max_daily_drawdown_pct, "max_daily_drawdown_pct")
    loss_limit_fraction = _nonnegative_ratio(max_loss_per_trade_pct, "max_loss_per_trade_pct")
    emergency_cap = _optional_nonnegative_decimal(
        emergency_absolute_cap_usdt,
        "emergency_absolute_cap_usdt",
    )

    priors = [_prior_reservation(row, sequence_index=index) for index, row in enumerate(prior_rows)]
    receipt_hashes = [row["final_admission_receipt_hash"] for row in priors]
    allocation_ids = [row["allocation_id"] for row in priors]
    if len(receipt_hashes) != len(set(receipt_hashes)):
        raise CycleReservationError("CYCLE_RESERVATION_DUPLICATE_PRIOR_FINAL_RECEIPT")
    if len(allocation_ids) != len(set(allocation_ids)):
        raise CycleReservationError("CYCLE_RESERVATION_DUPLICATE_PRIOR_ALLOCATION")
    append_chain_reasons = _prior_append_chain_rejection_reasons(
        prior_accepted_rows=prior_rows,
        reservations=priors,
    )
    if append_chain_reasons:
        raise CycleReservationError(*append_chain_reasons)

    material = _snapshot_material(
        cycle_identity=cycle,
        candidate_symbol=symbol,
        base_resource_evidence_hash=base_evidence_hash,
        precycle_exposure_snapshot_hash=exposure_evidence_hash,
        dynamic_envelope_evidence_hash=envelope_evidence_hash,
        base_equity_usd=equity,
        base_available_margin_usd=available_margin,
        realized_drawdown_fraction_of_equity=realized_drawdown,
        precycle_total_notional_usd=precycle_total,
        precycle_symbol_current_mark_notional_usd=precycle_symbol,
        precycle_open_projected_max_loss_usd=precycle_open_projected_loss,
        max_total_portfolio_risk_pct=total_limit_fraction,
        max_single_symbol_exposure_pct=symbol_limit_fraction,
        min_available_margin_buffer_pct=margin_buffer_fraction,
        max_daily_drawdown_pct=drawdown_limit_fraction,
        max_loss_per_trade_pct=loss_limit_fraction,
        emergency_absolute_cap_usdt=emergency_cap,
        prior_reservations=priors,
    )
    return {**material, "snapshot_hash": _canonical_sha256(material)}


def _replay_snapshot(snapshot_value: Any) -> dict[str, Any]:
    snapshot = _mapping(snapshot_value, "cycle_reservation_snapshot")
    inputs_value = snapshot.get("inputs")
    inputs = _mapping(inputs_value, "cycle_reservation_snapshot.inputs")
    limits_value = inputs.get("dynamic_envelope_limits")
    limits = _mapping(limits_value, "cycle_reservation_snapshot.dynamic_envelope_limits")
    bindings = _mapping(
        snapshot.get("evidence_bindings"),
        "cycle_reservation_snapshot.evidence_bindings",
    )
    if bindings.get("hash_contract") != "sha256(canonical-json-v1)":
        raise CycleReservationError("CYCLE_RESERVATION_EVIDENCE_HASH_CONTRACT_INVALID")
    priors_value = snapshot.get("prior_reservations")
    priors_sequence = _bounded_prior_sequence_copy(priors_value, projection=True)
    priors = [
        _normalized_prior_reservation(row, sequence_index=index)
        for index, row in enumerate(priors_sequence)
    ]
    input_exact = _mapping(
        inputs.get("exact_decimal_material"),
        "cycle_reservation_snapshot.inputs.exact_decimal_material",
    )
    limit_exact = _mapping(
        limits.get("exact_decimal_material"),
        "cycle_reservation_snapshot.dynamic_envelope_limits.exact_decimal_material",
    )
    if (
        inputs.get("numeric_aliases_are_non_authoritative") is not True
        or limits.get("numeric_aliases_are_non_authoritative") is not True
    ):
        raise CycleReservationError("CYCLE_RESERVATION_EXACT_DECIMAL_AUTHORITY_INVALID")

    def exact_input(field: str) -> Decimal:
        return _exact_decimal_from_material(
            numeric_alias=inputs.get(field),
            exact_material=input_exact.get(field),
            field=field,
        )

    def exact_limit(field: str) -> Decimal:
        return _exact_decimal_from_material(
            numeric_alias=limits.get(field),
            exact_material=limit_exact.get(field),
            field=field,
        )

    equity = exact_input("base_equity_usd")
    available_margin = exact_input("base_available_margin_usd")
    realized_drawdown = exact_input("realized_drawdown_fraction_of_equity")
    precycle_total = exact_input("precycle_total_notional_usd")
    precycle_symbol = exact_input("precycle_symbol_current_mark_notional_usd")
    precycle_open_projected_loss = exact_input("precycle_open_projected_max_loss_usd")
    total_limit_fraction = exact_limit("max_total_portfolio_risk_pct")
    symbol_limit_fraction = exact_limit("max_single_symbol_exposure_pct")
    margin_buffer_fraction = exact_limit("min_available_margin_buffer_pct")
    drawdown_limit_fraction = exact_limit("max_daily_drawdown_pct")
    loss_limit_fraction = exact_limit("max_loss_per_trade_pct")
    emergency_exact = limit_exact.get("emergency_absolute_cap_usdt")
    emergency_alias = limits.get("emergency_absolute_cap_usdt")
    if emergency_exact is None and emergency_alias is None:
        emergency_cap = None
    elif emergency_exact is None or emergency_alias is None:
        raise CycleReservationError(
            "CYCLE_RESERVATION_EXACT_DECIMAL_ALIAS_MISMATCH:emergency_absolute_cap_usdt"
        )
    else:
        emergency_cap = _exact_decimal_from_material(
            numeric_alias=emergency_alias,
            exact_material=emergency_exact,
            field="emergency_absolute_cap_usdt",
        )
    if equity <= 0:
        raise CycleReservationError("CYCLE_RESERVATION_NUMERIC_NOT_POSITIVE:base_equity_usd")
    for field, value in (
        ("base_available_margin_usd", available_margin),
        ("realized_drawdown_fraction_of_equity", realized_drawdown),
        ("precycle_total_notional_usd", precycle_total),
        ("precycle_symbol_current_mark_notional_usd", precycle_symbol),
        ("precycle_open_projected_max_loss_usd", precycle_open_projected_loss),
        ("max_total_portfolio_risk_pct", total_limit_fraction),
        ("max_single_symbol_exposure_pct", symbol_limit_fraction),
        ("min_available_margin_buffer_pct", margin_buffer_fraction),
        ("max_daily_drawdown_pct", drawdown_limit_fraction),
        ("max_loss_per_trade_pct", loss_limit_fraction),
    ):
        if value < 0:
            raise CycleReservationError(f"CYCLE_RESERVATION_NUMERIC_NEGATIVE:{field}")
    if emergency_cap is not None and emergency_cap < 0:
        raise CycleReservationError(
            "CYCLE_RESERVATION_NUMERIC_NEGATIVE:emergency_absolute_cap_usdt"
        )
    if precycle_symbol > precycle_total:
        raise CycleReservationError("CYCLE_RESERVATION_PRE_CYCLE_SYMBOL_EXCEEDS_TOTAL_NOTIONAL")
    material = _snapshot_material(
        cycle_identity=_text(snapshot.get("cycle_identity"), "cycle_identity"),
        candidate_symbol=_symbol(snapshot.get("candidate_symbol")),
        base_resource_evidence_hash=_sha256_text(
            bindings.get("base_resource_evidence_hash"),
            "base_resource_evidence_hash",
        ),
        precycle_exposure_snapshot_hash=_sha256_text(
            bindings.get("precycle_exposure_snapshot_hash"),
            "precycle_exposure_snapshot_hash",
        ),
        dynamic_envelope_evidence_hash=_sha256_text(
            bindings.get("dynamic_envelope_evidence_hash"),
            "dynamic_envelope_evidence_hash",
        ),
        base_equity_usd=equity,
        base_available_margin_usd=available_margin,
        realized_drawdown_fraction_of_equity=realized_drawdown,
        precycle_total_notional_usd=precycle_total,
        precycle_symbol_current_mark_notional_usd=precycle_symbol,
        precycle_open_projected_max_loss_usd=precycle_open_projected_loss,
        max_total_portfolio_risk_pct=total_limit_fraction,
        max_single_symbol_exposure_pct=symbol_limit_fraction,
        min_available_margin_buffer_pct=margin_buffer_fraction,
        max_daily_drawdown_pct=drawdown_limit_fraction,
        max_loss_per_trade_pct=loss_limit_fraction,
        emergency_absolute_cap_usdt=emergency_cap,
        prior_reservations=priors,
    )
    prior_count = snapshot.get("prior_accepted_count")
    if (
        not isinstance(prior_count, int)
        or isinstance(prior_count, bool)
        or prior_count != len(priors)
    ):
        raise CycleReservationError("CYCLE_RESERVATION_PRIOR_COUNT_MISMATCH")
    return material


def cycle_reservation_snapshot_rejection_reasons(snapshot_value: Any) -> tuple[str, ...]:
    """Return semantic/hash violations; an empty tuple means the snapshot is valid."""

    try:
        snapshot = _mapping(snapshot_value, "cycle_reservation_snapshot")
        expected_material = _replay_snapshot(snapshot)
        supplied_material = dict(snapshot)
        supplied_hash = supplied_material.pop("snapshot_hash", None)
        reasons: list[str] = []
        if snapshot.get("schema_version") != CYCLE_RESERVATION_SNAPSHOT_SCHEMA_VERSION:
            reasons.append("CYCLE_RESERVATION_SNAPSHOT_SCHEMA_INVALID")
        if snapshot.get("status") != "PASS" or snapshot.get("rejection_reasons") != []:
            reasons.append("CYCLE_RESERVATION_SNAPSHOT_STATUS_INVALID")
        if (
            not _valid_sha256(supplied_hash)
            or supplied_hash != _canonical_sha256(supplied_material)
            or supplied_hash != _canonical_sha256(expected_material)
        ):
            reasons.append("CYCLE_RESERVATION_SNAPSHOT_HASH_INVALID")
        if supplied_material != expected_material:
            reasons.append("CYCLE_RESERVATION_SNAPSHOT_SEMANTIC_REPLAY_MISMATCH")
        return tuple(sorted(set(reasons)))
    except CycleReservationError as exc:
        return exc.reasons


def _validated_snapshot(snapshot_value: Any) -> Mapping[str, Any]:
    reasons = cycle_reservation_snapshot_rejection_reasons(snapshot_value)
    if reasons:
        raise CycleReservationError(*reasons)
    return _mapping(snapshot_value, "cycle_reservation_snapshot")


def _current_prior_reservations(
    prior_accepted_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Revalidate the exact accepted-list prefix at the commit boundary."""

    prior_rows = _bounded_prior_sequence_copy(prior_accepted_rows)
    reservations = [
        _prior_reservation(row, sequence_index=index) for index, row in enumerate(prior_rows)
    ]
    receipt_hashes = [row["final_admission_receipt_hash"] for row in reservations]
    allocation_ids = [row["allocation_id"] for row in reservations]
    if len(receipt_hashes) != len(set(receipt_hashes)):
        raise CycleReservationError("CYCLE_RESERVATION_DUPLICATE_PRIOR_FINAL_RECEIPT")
    if len(allocation_ids) != len(set(allocation_ids)):
        raise CycleReservationError("CYCLE_RESERVATION_DUPLICATE_PRIOR_ALLOCATION")
    append_chain_reasons = _prior_append_chain_rejection_reasons(
        prior_accepted_rows=prior_rows,
        reservations=reservations,
    )
    if append_chain_reasons:
        raise CycleReservationError(*append_chain_reasons)
    return reservations


def cycle_reservation_prior_rows_rejection_reasons(
    *,
    snapshot: Mapping[str, Any],
    prior_accepted_rows: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return violations when the accepted-list prefix changed after snapshot.

    The signal loop is currently sequential, but this comparison makes that
    ordering an enforced contract instead of an implementation assumption.
    A row added, removed, reordered, mutated, or resealed between allocation
    and commit invalidates the candidate's remaining-capacity calculation.
    """

    try:
        validated_snapshot = _validated_snapshot(snapshot)
        current = _current_prior_reservations(prior_accepted_rows)
        snapshotted = validated_snapshot.get("prior_reservations")
        if not isinstance(snapshotted, list) or current != snapshotted:
            return ("CYCLE_RESERVATION_ACCEPTED_PREFIX_CHANGED_AFTER_SNAPSHOT",)
        return ()
    except CycleReservationError as exc:
        return tuple(
            sorted(set(exc.reasons) | {"CYCLE_RESERVATION_ACCEPTED_PREFIX_CHANGED_AFTER_SNAPSHOT"})
        )


def _build_candidate_commit_receipt_intrinsic(
    *,
    snapshot: Mapping[str, Any],
    adaptive_allocation: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a commit from only the immutable snapshot and allocation."""

    validated_snapshot = _validated_snapshot(snapshot)
    snapshot_hash = str(validated_snapshot["snapshot_hash"])
    canonical_snapshot = {
        **_replay_snapshot(validated_snapshot),
        "snapshot_hash": snapshot_hash,
    }
    candidate_symbol = str(canonical_snapshot["candidate_symbol"])
    economics = _allocation_economics(
        adaptive_allocation,
        expected_symbol=candidate_symbol,
        required_snapshot_hash=snapshot_hash,
    )
    derived = _mapping(canonical_snapshot.get("derived"), "snapshot.derived")
    inputs = _mapping(canonical_snapshot.get("inputs"), "snapshot.inputs")
    limits = _mapping(inputs.get("dynamic_envelope_limits"), "snapshot.dynamic_limits")
    input_exact = _mapping(inputs.get("exact_decimal_material"), "snapshot.inputs.exact")
    derived_exact = _mapping(
        derived.get("exact_decimal_material"),
        "snapshot.derived.exact",
    )

    def exact_derived(field: str) -> Decimal:
        return _exact_decimal_from_material(
            numeric_alias=derived.get(field),
            exact_material=derived_exact.get(field),
            field=f"derived.{field}",
            derived_material=True,
        )

    notional = economics["_gross_notional_decimal"]
    margin = economics["_allocated_margin_decimal"]
    max_loss = economics["_max_loss_if_stop_hit_decimal"]
    if not all(isinstance(value, Decimal) for value in (notional, margin, max_loss)):
        raise CycleReservationError("CYCLE_RESERVATION_INTERNAL_DECIMAL_AUTHORITY_INVALID")
    equity = _exact_decimal_from_material(
        numeric_alias=inputs.get("base_equity_usd"),
        exact_material=input_exact.get("base_equity_usd"),
        field="base_equity_usd",
    )
    total_before = exact_derived("effective_total_notional_before_candidate_usd")
    symbol_before = exact_derived("effective_symbol_notional_before_candidate_usd")
    margin_remaining = exact_derived("remaining_margin_after_buffer_usd")
    total_limit = exact_derived("total_notional_limit_usd")
    symbol_limit = exact_derived("symbol_notional_limit_usd")
    stress_before = exact_derived("projected_stress_drawdown_before_candidate_usd")
    stress_limit = exact_derived("projected_stress_drawdown_limit_usd")
    risk_remaining = exact_derived("remaining_per_candidate_risk_budget_usd")

    total_after = _exact_add(total_before, notional)
    symbol_after = _exact_add(symbol_before, notional)
    stress_after = _exact_add(stress_before, max_loss)
    candidate_risk_fraction = _deterministic_divide(
        max_loss,
        equity,
        "candidate.risk_fraction_of_equity",
    )
    stress_after_fraction = _deterministic_divide(
        stress_after,
        equity,
        "projected.projected_stress_drawdown_fraction_of_equity",
    )
    remaining_margin_after_candidate = max(
        Decimal(0),
        _exact_subtract(margin_remaining, margin),
    )
    checks = {
        "allocation_lineage_binds_snapshot": True,
        "adaptive_total_notional_limit_holds": total_after <= total_limit,
        "adaptive_symbol_notional_limit_holds": symbol_after <= symbol_limit,
        "adaptive_margin_buffer_limit_holds": margin <= margin_remaining,
        "adaptive_per_candidate_risk_budget_holds": max_loss <= risk_remaining,
        "adaptive_projected_stress_drawdown_limit_holds": stress_after <= stress_limit,
    }
    reason_by_check = {
        "adaptive_total_notional_limit_holds": "CYCLE_RESERVATION_TOTAL_NOTIONAL_LIMIT_EXCEEDED",
        "adaptive_symbol_notional_limit_holds": "CYCLE_RESERVATION_SYMBOL_NOTIONAL_LIMIT_EXCEEDED",
        "adaptive_margin_buffer_limit_holds": "CYCLE_RESERVATION_MARGIN_BUFFER_LIMIT_EXCEEDED",
        "adaptive_per_candidate_risk_budget_holds": (
            "CYCLE_RESERVATION_CANDIDATE_RISK_BUDGET_EXCEEDED"
        ),
        "adaptive_projected_stress_drawdown_limit_holds": (
            "CYCLE_RESERVATION_PROJECTED_STRESS_DRAWDOWN_LIMIT_EXCEEDED"
        ),
    }
    reasons = sorted(
        reason for check, reason in reason_by_check.items() if checks.get(check) is not True
    )
    material = {
        "schema_version": CYCLE_RESERVATION_COMMIT_SCHEMA_VERSION,
        "status": "PASS" if not reasons else "BLOCKED",
        "cycle_identity": canonical_snapshot["cycle_identity"],
        "candidate_symbol": candidate_symbol,
        "cycle_reservation_snapshot_hash": snapshot_hash,
        "allocation_id": economics["allocation_id"],
        "allocation_input_hash": economics["allocation_input_hash"],
        "adaptive_allocation_hash": economics["allocation_hash"],
        "candidate_resources": {
            "allocator_arithmetic_receipt_schema_version": (
                CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_SCHEMA_VERSION
            ),
            "allocator_arithmetic_version": CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_VERSION,
            "allocator_arithmetic_formula": CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_FORMULA,
            "allocator_arithmetic_receipt_sha256": economics["allocator_arithmetic_receipt_sha256"],
            "gross_notional_usd": economics["gross_notional_usd"],
            "allocated_margin_usd": economics["allocated_margin_usd"],
            "max_loss_if_stop_hit_usd": economics["max_loss_if_stop_hit_usd"],
            "risk_fraction_of_equity": _number(
                candidate_risk_fraction,
                "candidate.risk_fraction_of_equity",
            ),
            "exact_decimal_material": {
                **dict(
                    _mapping(
                        economics.get("exact_decimal_material"),
                        "candidate.exact_decimal_material",
                    )
                ),
                "risk_fraction_of_equity": _canonical_decimal(
                    candidate_risk_fraction,
                    "candidate.risk_fraction_of_equity",
                ),
            },
            "numeric_aliases_are_non_authoritative": True,
        },
        "capacity_before_candidate": {
            "remaining_total_notional_usd": derived["remaining_total_notional_usd"],
            "remaining_symbol_notional_usd": derived["remaining_symbol_notional_usd"],
            "remaining_margin_after_buffer_usd": derived["remaining_margin_after_buffer_usd"],
            "allocator_available_margin_input_usd": derived["allocator_available_margin_input_usd"],
            "remaining_projected_stress_loss_usd": derived["remaining_projected_stress_loss_usd"],
            "per_candidate_max_loss_limit_usd": derived["per_candidate_max_loss_limit_usd"],
            "remaining_per_candidate_risk_budget_usd": derived[
                "remaining_per_candidate_risk_budget_usd"
            ],
            "remaining_per_candidate_risk_budget_fraction_of_equity": derived[
                "remaining_per_candidate_risk_budget_fraction_of_equity"
            ],
            "remaining_candidate_risk_fraction_of_per_trade_limit": derived[
                "remaining_candidate_risk_fraction_of_per_trade_limit"
            ],
            "exact_decimal_material": {
                field: derived_exact[field]
                for field in (
                    "remaining_total_notional_usd",
                    "remaining_symbol_notional_usd",
                    "remaining_margin_after_buffer_usd",
                    "allocator_available_margin_input_usd",
                    "remaining_projected_stress_loss_usd",
                    "per_candidate_max_loss_limit_usd",
                    "remaining_per_candidate_risk_budget_usd",
                    "remaining_per_candidate_risk_budget_fraction_of_equity",
                    "remaining_candidate_risk_fraction_of_per_trade_limit",
                )
            },
            "numeric_aliases_are_non_authoritative": True,
        },
        "projected_after_candidate": {
            "total_notional_usd": _number(
                total_after,
                "projected.total_notional_usd",
            ),
            "symbol_notional_usd": _number(
                symbol_after,
                "projected.symbol_notional_usd",
            ),
            "remaining_available_margin_after_buffer_usd": _number(
                remaining_margin_after_candidate,
                "projected.remaining_available_margin_after_buffer_usd",
            ),
            "projected_stress_drawdown_usd": _number(
                stress_after,
                "projected.projected_stress_drawdown_usd",
            ),
            "projected_stress_drawdown_fraction_of_equity": _number(
                stress_after_fraction,
                "projected.projected_stress_drawdown_fraction_of_equity",
            ),
            "exact_decimal_material": {
                "total_notional_usd": _canonical_decimal(
                    total_after,
                    "projected.total_notional_usd",
                ),
                "symbol_notional_usd": _canonical_decimal(
                    symbol_after,
                    "projected.symbol_notional_usd",
                ),
                "remaining_available_margin_after_buffer_usd": _canonical_decimal(
                    remaining_margin_after_candidate,
                    "projected.remaining_available_margin_after_buffer_usd",
                ),
                "projected_stress_drawdown_usd": _canonical_decimal(
                    stress_after,
                    "projected.projected_stress_drawdown_usd",
                ),
                "projected_stress_drawdown_fraction_of_equity": _canonical_decimal(
                    stress_after_fraction,
                    "projected.projected_stress_drawdown_fraction_of_equity",
                ),
            },
            "numeric_aliases_are_non_authoritative": True,
        },
        "dynamic_envelope_limits": deepcopy(dict(limits)),
        "invariant_checks": checks,
        "rejection_reasons": reasons,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "integrity_scope": (
            "SEMANTIC_REPLAY_AND_CROSS_BOUND_PLAIN_SHA256;NOT_SOURCE_AUTHENTICATION"
        ),
    }
    return {**material, "receipt_hash": _canonical_sha256(material)}


def build_candidate_commit_receipt(
    *,
    snapshot: Mapping[str, Any],
    adaptive_allocation: Mapping[str, Any],
    prior_accepted_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a commit after enforcing the live accepted-prefix boundary."""

    validated_snapshot = _validated_snapshot(snapshot)
    prefix_reasons = cycle_reservation_prior_rows_rejection_reasons(
        snapshot=validated_snapshot,
        prior_accepted_rows=prior_accepted_rows,
    )
    if prefix_reasons:
        raise CycleReservationError(*prefix_reasons)
    return _build_candidate_commit_receipt_intrinsic(
        snapshot=validated_snapshot,
        adaptive_allocation=adaptive_allocation,
    )


def _candidate_allocator_arithmetic_contract_rejection_reasons(
    receipt: Mapping[str, Any],
) -> tuple[str, ...]:
    resources = receipt.get("candidate_resources")
    resource_fields = resources if isinstance(resources, Mapping) else {}
    reasons: list[str] = []
    expected_top_level = {
        "allocator_arithmetic_receipt_schema_version": (
            CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_SCHEMA_VERSION
        ),
        "allocator_arithmetic_version": CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_VERSION,
        "allocator_arithmetic_formula": CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_FORMULA,
    }
    for field, expected in expected_top_level.items():
        if type(resource_fields.get(field)) is not str or resource_fields.get(field) != expected:
            reasons.append(f"CYCLE_RESERVATION_COMMIT_{field.upper()}_INVALID")
    exact_value = resource_fields.get("exact_decimal_material")
    exact = exact_value if isinstance(exact_value, Mapping) else {}
    if exact.get("allocator_arithmetic_identity") != (
        CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_IDENTITY
    ):
        reasons.append("CYCLE_RESERVATION_COMMIT_ALLOCATOR_ARITHMETIC_IDENTITY_INVALID")
    reconstructed_receipt = {
        "schema_version": exact.get("allocator_arithmetic_receipt_schema_version"),
        "arithmetic_version": exact.get("allocator_arithmetic_version"),
        "formula": exact.get("allocator_arithmetic_formula"),
        "raw_post_step_quantity_binary64_hex": exact.get("raw_post_step_quantity_binary64_hex"),
        "input_price_binary64_hex": exact.get("input_price_binary64_hex"),
        "raw_post_step_notional_binary64_hex": exact.get("raw_post_step_notional_binary64_hex"),
        "selected_leverage_binary64_hex": exact.get("selected_leverage_binary64_hex"),
        "receipt_sha256": exact.get("allocator_arithmetic_receipt_sha256"),
    }
    try:
        _validated_allocator_arithmetic_receipt(reconstructed_receipt)
    except CycleReservationError as exc:
        reasons.extend(exc.reasons)
    if (
        resource_fields.get("allocator_arithmetic_receipt_sha256")
        != reconstructed_receipt["receipt_sha256"]
    ):
        reasons.append("CYCLE_RESERVATION_COMMIT_ALLOCATOR_ARITHMETIC_HASH_BINDING_INVALID")
    return tuple(sorted(set(reasons)))


def intrinsic_candidate_commit_receipt_rejection_reasons(
    *,
    snapshot: Mapping[str, Any],
    adaptive_allocation: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> tuple[str, ...]:
    """Replay a persisted commit without consulting a mutable accepted list.

    This is the persistence/audit validation surface.  It proves that the
    supplied snapshot, allocation, and commit are an exact self-contained
    chain.  The strict public builder and validator separately retain the
    accepted-prefix check required immediately before an in-process append.
    """

    try:
        expected = _build_candidate_commit_receipt_intrinsic(
            snapshot=snapshot,
            adaptive_allocation=adaptive_allocation,
        )
        supplied = _mapping(receipt, "candidate_commit_receipt")
        supplied_material = dict(supplied)
        supplied_hash = supplied_material.pop("receipt_hash", None)
        reasons = list(_candidate_allocator_arithmetic_contract_rejection_reasons(supplied))
        if supplied.get("schema_version") != CYCLE_RESERVATION_COMMIT_SCHEMA_VERSION:
            reasons.append("CYCLE_RESERVATION_COMMIT_SCHEMA_INVALID")
        if not _valid_sha256(supplied_hash) or supplied_hash != _canonical_sha256(
            supplied_material
        ):
            reasons.append("CYCLE_RESERVATION_COMMIT_RECEIPT_HASH_INVALID")
        if dict(supplied) != expected:
            reasons.append("CYCLE_RESERVATION_COMMIT_SEMANTIC_REPLAY_MISMATCH")
        return tuple(sorted(set(reasons)))
    except CycleReservationError as exc:
        return exc.reasons


def candidate_commit_receipt_rejection_reasons(
    *,
    snapshot: Mapping[str, Any],
    adaptive_allocation: Mapping[str, Any],
    prior_accepted_rows: Sequence[Mapping[str, Any]],
    receipt: Mapping[str, Any],
) -> tuple[str, ...]:
    """Return receipt integrity/replay violations; policy BLOCKED is still valid."""

    try:
        expected = build_candidate_commit_receipt(
            snapshot=snapshot,
            adaptive_allocation=adaptive_allocation,
            prior_accepted_rows=prior_accepted_rows,
        )
        supplied = _mapping(receipt, "candidate_commit_receipt")
        supplied_material = dict(supplied)
        supplied_hash = supplied_material.pop("receipt_hash", None)
        reasons = list(_candidate_allocator_arithmetic_contract_rejection_reasons(supplied))
        if supplied.get("schema_version") != CYCLE_RESERVATION_COMMIT_SCHEMA_VERSION:
            reasons.append("CYCLE_RESERVATION_COMMIT_SCHEMA_INVALID")
        if not _valid_sha256(supplied_hash) or supplied_hash != _canonical_sha256(
            supplied_material
        ):
            reasons.append("CYCLE_RESERVATION_COMMIT_RECEIPT_HASH_INVALID")
        if dict(supplied) != expected:
            reasons.append("CYCLE_RESERVATION_COMMIT_SEMANTIC_REPLAY_MISMATCH")
        return tuple(sorted(set(reasons)))
    except CycleReservationError as exc:
        return exc.reasons


def validate_intrinsic_candidate_commit_receipt(
    *,
    snapshot: Mapping[str, Any],
    adaptive_allocation: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> bool:
    """Return true only for an exact, self-contained PASS commit chain."""

    return (
        not intrinsic_candidate_commit_receipt_rejection_reasons(
            snapshot=snapshot,
            adaptive_allocation=adaptive_allocation,
            receipt=receipt,
        )
        and receipt.get("status") == "PASS"
    )


def validate_candidate_commit_receipt(
    *,
    snapshot: Mapping[str, Any],
    adaptive_allocation: Mapping[str, Any],
    prior_accepted_rows: Sequence[Mapping[str, Any]],
    receipt: Mapping[str, Any],
) -> bool:
    """Return true only for an exact, replayable PASS commit receipt."""

    return (
        not candidate_commit_receipt_rejection_reasons(
            snapshot=snapshot,
            adaptive_allocation=adaptive_allocation,
            prior_accepted_rows=prior_accepted_rows,
            receipt=receipt,
        )
        and receipt.get("status") == "PASS"
    )


__all__ = [
    "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_FORMULA",
    "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_IDENTITY",
    "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_MODEL_INPUT_KEY",
    "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_RECEIPT_SCHEMA_VERSION",
    "CYCLE_RESERVATION_ALLOCATOR_ARITHMETIC_VERSION",
    "CYCLE_RESERVATION_ALLOCATOR_MARGIN_REPLAY_FORMULA",
    "CYCLE_RESERVATION_ALLOCATOR_MARGIN_REPLAY_IDENTITY",
    "CYCLE_RESERVATION_ALLOCATOR_MARGIN_REPLAY_VERSION",
    "CYCLE_RESERVATION_IMMUTABLE_BOUND_CLASSIFICATION",
    "CYCLE_RESERVATION_COMMIT_SCHEMA_VERSION",
    "CYCLE_RESERVATION_DECIMAL_DIVISION_PRECISION",
    "CYCLE_RESERVATION_LINEAGE_KEY",
    "CYCLE_RESERVATION_SNAPSHOT_SCHEMA_VERSION",
    "MAX_CYCLE_RESERVATION_CANONICAL_JSON_BYTES",
    "MAX_CYCLE_RESERVATION_JSON_DEPTH",
    "MAX_CYCLE_RESERVATION_JSON_NODES",
    "MAX_CYCLE_RESERVATION_PRIOR_ACCEPTED_ROWS",
    "MAX_CYCLE_RESERVATION_TEXT_BYTES",
    "CycleReservationError",
    "build_candidate_commit_receipt",
    "build_cycle_reservation_snapshot",
    "candidate_commit_receipt_rejection_reasons",
    "cycle_reservation_persisted_row_projection",
    "cycle_reservation_prior_rows_rejection_reasons",
    "cycle_reservation_snapshot_rejection_reasons",
    "intrinsic_candidate_commit_receipt_rejection_reasons",
    "validate_candidate_commit_receipt",
    "validate_intrinsic_candidate_commit_receipt",
]
