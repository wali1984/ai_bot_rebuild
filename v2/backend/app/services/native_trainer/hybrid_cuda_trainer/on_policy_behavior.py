"""Exact paper-only categorical behavior-policy receipts.

This module is deliberately independent of Redis and paper execution.  It turns
one immutable native-policy forward pass into a self-authenticating receipt that
can be validated again at entry and training time.  The receipt never authorizes
live execution and never converts strategy-supply actions into policy samples.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from ..adaptive_sampling_plan_contract import (
    ADAPTIVE_ON_POLICY_ACTION_COUNT,
    ADAPTIVE_ON_POLICY_LANE_FORMULA,
    ADAPTIVE_ON_POLICY_LANE_SCHEMA_VERSION,
    U53_DENOMINATOR,
)
from ..adaptive_sampling_plan_contract import (
    adaptive_on_policy_lane_plan_rejection_reasons as _plan_rejection_reasons,
)
from ..adaptive_sampling_plan_contract import (
    is_content_addressed_checkpoint_id as _is_real_checkpoint_id,
)
from .config import ACTION_COUNT, ACTION_LABELS
from .training_state import ppo_consumption_update_key as _canonical_ppo_update_key

adaptive_on_policy_lane_plan_rejection_reasons = _plan_rejection_reasons

ON_POLICY_RECEIPT_SCHEMA_VERSION = "v2_positive_edge_on_policy_behavior_receipt_v1"
ON_POLICY_SAMPLING_MODE = "CATEGORICAL_SAMPLE"
ON_POLICY_DISTRIBUTION_CONTRACT = "POSITIVE_EDGE_MASKED_RAW_LOGITS_SOFTMAX_V1"
ON_POLICY_ACTION_SOURCE = "NATIVE_CUDA_POLICY_CATEGORICAL_SAMPLE"
ON_POLICY_MASK_SOURCE = "PIT_AFTER_COST_POSITIVE_ENTRY_ACTION_MASK_V1"
EXACT_COST_PROVENANCE_SCHEMA_VERSION = "v2_exact_adaptive_cost_provenance_v1"
EXACT_COST_ESTIMATOR_SCHEMA_VERSION = "adaptive_cost_estimate_payload_v1"
FINALIZED_OUTCOME_SCHEMA_VERSION = "v2_exact_ppo_finalized_outcome_v1"
FINALIZED_OUTCOME_REWARD_FORMULA = "realized_net_pnl_bps/100"
FINALIZED_OUTCOME_NET_FORMULA = (
    "realized_gross_pnl_usd - entry_fee_usd - exit_fee_usd - "
    "entry_slippage_usd - exit_slippage_usd + funding_pnl_usd"
)
FINALIZED_OUTCOME_COST_ACCOUNTING_VERSION = "PAPER_ROUND_TRIP_CLOSE_COST_V1"
FINALIZED_OUTCOME_COST_RATE_SCOPE = (
    "PER_SIDE_BPS_APPLIED_TO_CORRESPONDING_NOTIONAL"
)
FINALIZED_OUTCOME_ENTRY_COST_ACCOUNTING_VERSION = "PAPER_ENTRY_COST_BASIS_V1"
FINALIZED_OUTCOME_ENTRY_COST_ALLOCATION_METHOD = (
    "PRO_RATA_BY_CLOSED_QUANTITY_WITH_FINAL_CLOSE_REMAINDER"
)
FINALIZED_OUTCOME_ENTRY_COST_BASIS_STATUS = (
    "COMPLETE_ENTRY_FEE_AND_SLIPPAGE_USD_BASIS"
)
FINALIZED_OUTCOME_COST_PROVENANCE_STATUS = (
    "COMPLETE_ENTRY_AND_EXIT_COST_PROVENANCE"
)
FINALIZED_OUTCOME_EXIT_FEE_RATE_BASIS = (
    "ENTRY_BOUND_PER_SIDE_FEE_RATE_REUSED_FOR_PAPER_EXIT"
)
FINALIZED_OUTCOME_EXIT_SLIPPAGE_PROVENANCE_STATUS = (
    "EXIT_SPREAD_AVAILABLE_BY_CLOSE_TIME"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

BEHAVIOR_POLICY_LINEAGE_FIELDS = (
    "action_labels",
    "raw_action_logits",
    "raw_action_probabilities",
    "action_probabilities",
    "selected_action_index",
    "selected_action_probability",
    "selected_action_log_prob",
    "policy_value",
    "behavior_action_index",
    "behavior_action",
    "behavior_action_mask",
    "behavior_action_source",
    "behavior_policy_sampling_mode",
    "behavior_policy_distribution_contract",
    "behavior_policy_fingerprint",
    "behavior_policy_checkpoint_hash",
    "behavior_policy_checkpoint_evidence_digest",
    "behavior_policy_checkpoint_evidence_verified",
    "behavior_policy_checkpoint_identity_verified",
    "behavior_policy_cost_provenance",
    "behavior_policy_cost_payload_hash",
    "behavior_policy_receipt",
    "behavior_policy_receipt_hash",
    "behavior_policy_receipt_key",
    "behavior_policy_receipt_write_success",
    "on_policy_action_receipt_valid",
    "on_policy_sampling_selected",
    "on_policy_sampling_requested",
    "on_policy_sampling_plan_hash",
    "on_policy_sampling_plan_input_hash",
    "on_policy_sampling_lane",
    "on_policy_sampling_evidence_class",
    "on_policy_sampling_counts_as_a_plus_evidence",
    "on_policy_sampling_routes_to_live",
    "ppo_on_policy_entry_fields_present",
    "ppo_on_policy_ineligible_reason",
    "finalized_outcome_id",
    "finalized_outcome_digest",
    "finalized_outcome_schema_version",
    "finalized_outcome_finality_proven",
    "finalized_outcome_reward",
    "ppo_consumption_update_key",
    "ppo_consumption_ledger_eligible",
    "entry_policy_fields_source",
)


def canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _strict_aware_utc(value: Any) -> datetime | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _strict_source_utc(value: Any) -> datetime | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    if isinstance(value, int | float):
        number = _finite(value)
        if number is None:
            return None
        if abs(number) > 10_000_000_000:
            number /= 1000.0
        try:
            return datetime.fromtimestamp(number, tz=UTC)
        except (OSError, OverflowError, ValueError):
            return None
    return _strict_aware_utc(value)


def _finite(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _strict_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
        if float(value) != float(parsed):
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _numbers_close(left: Any, right: Any, *, tolerance: float = 5e-8) -> bool:
    left_value = _finite(left)
    right_value = _finite(right)
    return bool(
        left_value is not None
        and right_value is not None
        and math.isclose(
            left_value,
            right_value,
            rel_tol=tolerance,
            abs_tol=tolerance,
        )
    )


def build_exact_cost_provenance(
    *,
    source_key: str,
    source_payload: Mapping[str, Any],
    consumer_observed_at: Any,
) -> dict[str, Any]:
    """Normalize one fresh adaptive-cost publication into receipt evidence.

    Freshness is taken from the estimator's explicit status and source clocks;
    this consumer deliberately adds no fixed age threshold. Conservative-floor
    and reserve/fallback estimates remain usable by ordinary predictions but
    are never eligible for exact on-policy sampling.
    """

    if not isinstance(source_payload, Mapping):
        raise ValueError("exact_cost_source_payload_missing")
    payload = dict(source_payload)
    symbol = str(payload.get("symbol") or "").strip().upper()
    if not symbol:
        raise ValueError("exact_cost_symbol_missing")
    expected_source_key = f"v2:costs:round_trip_bps:{symbol}"
    if str(source_key or "") != expected_source_key:
        raise ValueError("exact_cost_source_key_mismatch")
    if payload.get("estimator_version") != "adaptive_cost_model_v1":
        raise ValueError("exact_cost_estimator_version_invalid")
    if payload.get("scope") != "PAPER_ONLY_ADAPTIVE_COST_MODEL":
        raise ValueError("exact_cost_scope_invalid")
    if payload.get("freshness_status") != "FRESH_ORDERBOOK":
        raise ValueError("exact_cost_freshness_status_not_fresh")
    if payload.get("conservative_floor_applied") is not False:
        raise ValueError("exact_cost_conservative_floor_applied")
    if payload.get("spread_source") != "orderbook_features_binance_live_spread_bps":
        raise ValueError("exact_cost_spread_source_not_live")
    if payload.get("impact_source") not in {
        "orderbook_estimated_price_impact_bps_scaled_linear",
        "notional_over_top5_depth_times_half_spread",
    }:
        raise ValueError("exact_cost_impact_source_not_depth_observed")
    expected_orderbook_key = f"v2:orderbook:features:binance:{symbol}"
    if payload.get("orderbook_key") != expected_orderbook_key:
        raise ValueError("exact_cost_orderbook_source_key_mismatch")

    generated_at = _strict_aware_utc(payload.get("computed_utc"))
    cost_available_at = _strict_aware_utc(payload.get("available_at"))
    consumer_observed = _strict_aware_utc(consumer_observed_at)
    expires_at = _strict_aware_utc(payload.get("expires_at"))
    orderbook_observed_at = _strict_aware_utc(
        payload.get("orderbook_observed_at")
    )
    orderbook_available_at = _strict_aware_utc(
        payload.get("orderbook_available_at")
    )
    orderbook_generated_at = _strict_aware_utc(
        payload.get("orderbook_generated_at")
    )
    spread_age_seconds = _finite(payload.get("spread_age_seconds"))
    adaptive_max_age_seconds = _finite(
        payload.get("adaptive_max_age_seconds")
    )
    adaptive_sample_count = _strict_int(
        payload.get("adaptive_freshness_sample_count")
    )
    publication_ttl_seconds = _strict_int(
        payload.get("publication_ttl_seconds")
    )
    fee_per_side = _finite(payload.get("taker_fee_bps_per_side"))
    spread_bps = _finite(payload.get("spread_bps"))
    impact_per_side_bps = _finite(payload.get("impact_per_side_bps"))
    depth_used_usd = _finite(payload.get("depth_used_usd"))
    notional_usd = _finite(payload.get("notional_usd_assumed"))
    round_trip_cost_bps = _finite(payload.get("round_trip_cost_bps"))
    if None in (
        generated_at,
        cost_available_at,
        expires_at,
        orderbook_observed_at,
        orderbook_available_at,
        orderbook_generated_at,
    ):
        raise ValueError("exact_cost_source_clock_lineage_not_strict_utc")
    if consumer_observed is None:
        raise ValueError("exact_cost_consumer_observed_at_not_strict_utc")
    assert generated_at is not None and cost_available_at is not None
    assert expires_at is not None and orderbook_observed_at is not None
    assert orderbook_available_at is not None
    assert orderbook_generated_at is not None
    if not (
        orderbook_observed_at
        <= orderbook_available_at
        <= orderbook_generated_at
        <= generated_at
        <= cost_available_at
        <= consumer_observed
        <= expires_at
    ):
        raise ValueError("exact_cost_source_clock_order_invalid")
    if (
        spread_age_seconds is None
        or spread_age_seconds < 0.0
        or not _numbers_close(
            spread_age_seconds,
            (generated_at - orderbook_available_at).total_seconds(),
            tolerance=1e-6,
        )
    ):
        raise ValueError("exact_cost_observation_age_invalid")
    if (
        payload.get("adaptive_freshness_proven") is not True
        or adaptive_max_age_seconds is None
        or adaptive_max_age_seconds <= 0.0
        or adaptive_sample_count is None
        or adaptive_sample_count < 3
        or payload.get("adaptive_freshness_method")
        != "RECENT_DISTINCT_SOURCE_INTERVAL_MEDIAN_PLUS_MAD"
    ):
        raise ValueError("exact_cost_adaptive_freshness_proof_invalid")
    if not _numbers_close(
        adaptive_max_age_seconds,
        (expires_at - orderbook_available_at).total_seconds(),
        tolerance=1e-6,
    ):
        raise ValueError("exact_cost_adaptive_expiry_arithmetic_mismatch")
    if spread_age_seconds > adaptive_max_age_seconds:
        raise ValueError("exact_cost_source_expired_before_estimation")
    remaining_freshness_seconds = (expires_at - generated_at).total_seconds()
    if (
        publication_ttl_seconds is None
        or publication_ttl_seconds <= 0
        or publication_ttl_seconds > math.ceil(remaining_freshness_seconds)
    ):
        raise ValueError("exact_cost_publication_ttl_exceeds_source_expiry")
    if payload.get("source_future_clock_invalid") is not False:
        raise ValueError("exact_cost_future_source_clock_not_disproven")
    if payload.get("orderbook_source_clock_field") != "available_at":
        raise ValueError("exact_cost_source_availability_clock_invalid")
    if payload.get("orderbook_sequence_gap_flag") is not False:
        raise ValueError("exact_cost_orderbook_sequence_continuity_invalid")

    orderbook_payload = payload.get("orderbook_source_payload")
    if not isinstance(orderbook_payload, Mapping):
        raise ValueError("exact_cost_orderbook_source_payload_missing")
    orderbook_payload = dict(orderbook_payload)
    orderbook_payload_hash = canonical_sha256(orderbook_payload)
    if payload.get("orderbook_source_payload_sha256") != orderbook_payload_hash:
        raise ValueError("exact_cost_orderbook_source_payload_hash_mismatch")
    orderbook_schema_version = str(
        payload.get("orderbook_schema_version") or ""
    )
    if orderbook_schema_version not in {
        "v2_orderbook_features_v1",
        "direct_orderbook_features_v1",
    } or orderbook_payload.get("schema_version") != orderbook_schema_version:
        raise ValueError("exact_cost_orderbook_schema_version_invalid")
    if str(orderbook_payload.get("symbol") or "").strip().upper() != symbol:
        raise ValueError("exact_cost_orderbook_symbol_mismatch")
    if orderbook_payload.get("sequence_gap_flag") not in (0, 0.0, False):
        raise ValueError("exact_cost_orderbook_payload_sequence_gap")
    nested_observed_at = _strict_source_utc(orderbook_payload.get("event_time"))
    nested_available_at = _strict_source_utc(
        orderbook_payload.get("available_at")
    )
    nested_generated_at = _strict_source_utc(
        orderbook_payload.get("generated_at")
        or orderbook_payload.get("generated_utc")
    )
    if (
        nested_observed_at != orderbook_observed_at
        or nested_available_at != orderbook_available_at
        or nested_generated_at != orderbook_generated_at
    ):
        raise ValueError("exact_cost_orderbook_embedded_clock_mismatch")
    fee_schedule_evidence = payload.get("fee_schedule_evidence")
    if not isinstance(fee_schedule_evidence, Mapping):
        raise ValueError("exact_cost_fee_schedule_evidence_missing")
    fee_schedule_evidence = dict(fee_schedule_evidence)
    fee_schedule_evidence_hash = canonical_sha256(fee_schedule_evidence)
    if (
        payload.get("fee_schedule_evidence_sha256")
        != fee_schedule_evidence_hash
        or fee_schedule_evidence.get("schema_version")
        != "paper_cost_fee_schedule_evidence_v1"
        or fee_schedule_evidence.get("configuration_kind")
        != "CONFIGURED_TAKER_FEE_BPS_PER_SIDE"
        or fee_schedule_evidence.get("fee_source") != payload.get("fee_source")
        or not _numbers_close(
            fee_schedule_evidence.get("taker_fee_bps_per_side"),
            fee_per_side,
            tolerance=1e-12,
        )
    ):
        raise ValueError("exact_cost_fee_schedule_evidence_invalid")
    notional_evidence = payload.get("notional_configuration_evidence")
    if not isinstance(notional_evidence, Mapping):
        raise ValueError("exact_cost_notional_configuration_evidence_missing")
    notional_evidence = dict(notional_evidence)
    notional_evidence_hash = canonical_sha256(notional_evidence)
    if (
        payload.get("notional_configuration_evidence_sha256")
        != notional_evidence_hash
        or notional_evidence.get("schema_version")
        != "paper_cost_notional_configuration_evidence_v1"
        or notional_evidence.get("configuration_kind")
        != "COST_MODEL_REFERENCE_NOTIONAL_USD"
        or not str(notional_evidence.get("notional_source") or "").strip()
        or not _numbers_close(
            notional_evidence.get("notional_usd"),
            notional_usd,
            tolerance=1e-12,
        )
    ):
        raise ValueError("exact_cost_notional_configuration_evidence_invalid")
    if fee_per_side is None or fee_per_side <= 0.0 or not payload.get("fee_source"):
        raise ValueError("exact_cost_fee_component_invalid")
    if spread_bps is None or spread_bps < 0.0:
        raise ValueError("exact_cost_spread_component_invalid")
    nested_spread_bps = _finite(orderbook_payload.get("spread_bps"))
    if nested_spread_bps is None or not _numbers_close(
        spread_bps, nested_spread_bps, tolerance=1e-12
    ):
        raise ValueError("exact_cost_spread_component_source_mismatch")
    if impact_per_side_bps is None or impact_per_side_bps < 0.0:
        raise ValueError("exact_cost_impact_component_invalid")
    if notional_usd is None or notional_usd <= 0.0:
        raise ValueError("exact_cost_notional_not_positive")
    if round_trip_cost_bps is None or round_trip_cost_bps <= 0.0:
        raise ValueError("exact_cost_round_trip_invalid")

    impact_source = str(payload.get("impact_source") or "")
    if impact_source == "orderbook_estimated_price_impact_bps_scaled_linear":
        source_impact_bps = _finite(
            orderbook_payload.get("estimated_price_impact_bps")
        )
        source_reference_notional = _finite(
            _first_present(
                orderbook_payload.get("price_impact_notional_usd"),
                orderbook_payload.get("impact_reference_notional_usd"),
            )
        )
        if (
            source_impact_bps is None
            or source_impact_bps < 0.0
            or source_reference_notional is None
            or source_reference_notional <= 0.0
        ):
            raise ValueError("exact_cost_exchange_impact_source_inputs_invalid")
        expected_impact_per_side_bps = source_impact_bps * (
            notional_usd / source_reference_notional
        )
        source_depth_total = _finite(orderbook_payload.get("depth_total_usd"))
        if source_depth_total is None:
            if payload.get("depth_used_usd") not in (None, ""):
                raise ValueError("exact_cost_exchange_impact_depth_source_mismatch")
        elif not _numbers_close(
            depth_used_usd, source_depth_total, tolerance=1e-12
        ):
            raise ValueError("exact_cost_exchange_impact_depth_source_mismatch")
    else:
        depth_bid = _finite(orderbook_payload.get("depth_5_bid_usd"))
        if depth_bid is None or depth_bid <= 0.0:
            depth_bid = _finite(orderbook_payload.get("depth_20_bid_usd"))
        depth_ask = _finite(orderbook_payload.get("depth_5_ask_usd"))
        if depth_ask is None or depth_ask <= 0.0:
            depth_ask = _finite(orderbook_payload.get("depth_20_ask_usd"))
        usable_depth = [
            value
            for value in (depth_bid, depth_ask)
            if value is not None and value > 0.0
        ]
        if not usable_depth:
            raise ValueError("exact_cost_depth_ratio_source_inputs_invalid")
        thin_side_depth = min(usable_depth)
        expected_impact_per_side_bps = (
            0.5 * nested_spread_bps * notional_usd / thin_side_depth
        )
        if not _numbers_close(
            depth_used_usd, thin_side_depth, tolerance=1e-12
        ):
            raise ValueError("exact_cost_depth_used_source_mismatch")
    if not _numbers_close(
        impact_per_side_bps,
        expected_impact_per_side_bps,
        tolerance=1e-12,
    ):
        raise ValueError("exact_cost_impact_component_source_mismatch")

    fee_round_trip_bps = 2.0 * fee_per_side
    spread_round_trip_bps = spread_bps
    impact_round_trip_bps = 2.0 * impact_per_side_bps
    arithmetic_cost_bps = (
        fee_round_trip_bps + spread_round_trip_bps + impact_round_trip_bps
    )
    if not _numbers_close(round_trip_cost_bps, arithmetic_cost_bps):
        raise ValueError("exact_cost_round_trip_arithmetic_mismatch")

    generated_iso = generated_at.isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    available_iso = cost_available_at.isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    observed_iso = orderbook_observed_at.isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    orderbook_available_iso = orderbook_available_at.isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    orderbook_generated_iso = orderbook_generated_at.isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    expires_iso = expires_at.isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    consumer_observed_iso = consumer_observed.isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
    payload_hash = canonical_sha256(payload)
    return {
        "schema_version": EXACT_COST_PROVENANCE_SCHEMA_VERSION,
        "estimator_schema_version": EXACT_COST_ESTIMATOR_SCHEMA_VERSION,
        "estimator_version": str(payload["estimator_version"]),
        "symbol": symbol,
        "source_key": expected_source_key,
        "orderbook_source_key": expected_orderbook_key,
        "orderbook_schema_version": orderbook_schema_version,
        "orderbook_source_payload_sha256": orderbook_payload_hash,
        "source_payload_sha256": payload_hash,
        "source_payload": payload,
        "fee_schedule_evidence_sha256": fee_schedule_evidence_hash,
        "notional_configuration_evidence_sha256": notional_evidence_hash,
        "generated_at": generated_iso,
        "observed_at": observed_iso,
        "orderbook_available_at": orderbook_available_iso,
        "orderbook_generated_at": orderbook_generated_iso,
        "available_at": available_iso,
        "consumer_observed_at": consumer_observed_iso,
        "expires_at": expires_iso,
        "adaptive_max_age_seconds": adaptive_max_age_seconds,
        "adaptive_freshness_sample_count": adaptive_sample_count,
        "adaptive_freshness_method": str(
            payload["adaptive_freshness_method"]
        ),
        "publication_ttl_seconds": publication_ttl_seconds,
        "freshness_proof": (
            "EXACT_SOURCE_KEY_REREAD_PLUS_HASHED_ORDERBOOK_ADAPTIVE_EXPIRY"
        ),
        "taker_fee_bps_per_side": fee_per_side,
        "fee_round_trip_bps": fee_round_trip_bps,
        "spread_bps": spread_bps,
        "spread_round_trip_bps": spread_round_trip_bps,
        "impact_per_side_bps": impact_per_side_bps,
        "depth_used_usd": depth_used_usd,
        "impact_round_trip_bps": impact_round_trip_bps,
        "notional_usd": notional_usd,
        "round_trip_cost_bps": round_trip_cost_bps,
        "arithmetic_round_trip_cost_bps": arithmetic_cost_bps,
        "arithmetic_formula": (
            "2*taker_fee_bps_per_side+spread_bps+2*impact_per_side_bps"
        ),
        "freshness_status": "FRESH_ORDERBOOK",
        "fallback_used": False,
        "conservative_floor_applied": False,
    }


def exact_cost_provenance_rejection_reasons(
    provenance: Any,
    *,
    expected_symbol: Any = None,
    expected_round_trip_cost_bps: Any = None,
    expected_decision_time: Any = None,
) -> list[str]:
    """Rebuild and bind exact adaptive-cost evidence without age constants."""

    if not isinstance(provenance, Mapping):
        return ["behavior_receipt_exact_cost_provenance_missing"]
    source_payload = provenance.get("source_payload")
    try:
        rebuilt = build_exact_cost_provenance(
            source_key=str(provenance.get("source_key") or ""),
            source_payload=source_payload,
            consumer_observed_at=provenance.get("consumer_observed_at"),
        )
    except (TypeError, ValueError) as exc:
        return [f"behavior_receipt_{exc}"]
    try:
        same_payload = canonical_sha256(provenance) == canonical_sha256(rebuilt)
    except (TypeError, ValueError):
        same_payload = False
    reasons: list[str] = []
    if not same_payload:
        reasons.append("behavior_receipt_exact_cost_provenance_mismatch")
    if expected_symbol not in (None, "") and rebuilt["symbol"] != str(
        expected_symbol
    ).strip().upper():
        reasons.append("behavior_receipt_exact_cost_symbol_binding_mismatch")
    if expected_round_trip_cost_bps not in (None, "") and not _numbers_close(
        rebuilt["round_trip_cost_bps"], expected_round_trip_cost_bps
    ):
        reasons.append("behavior_receipt_exact_cost_value_binding_mismatch")

    observed_at = _strict_aware_utc(rebuilt["observed_at"])
    orderbook_available_at = _strict_aware_utc(
        rebuilt["orderbook_available_at"]
    )
    orderbook_generated_at = _strict_aware_utc(
        rebuilt["orderbook_generated_at"]
    )
    generated_at = _strict_aware_utc(rebuilt["generated_at"])
    available_at = _strict_aware_utc(rebuilt["available_at"])
    consumer_observed_at = _strict_aware_utc(rebuilt["consumer_observed_at"])
    decision_time = _strict_aware_utc(expected_decision_time)
    expires_at = _strict_aware_utc(rebuilt["expires_at"])
    if None in (
        observed_at,
        orderbook_available_at,
        orderbook_generated_at,
        generated_at,
        available_at,
        consumer_observed_at,
        decision_time,
        expires_at,
    ):
        reasons.append("behavior_receipt_exact_cost_clock_binding_missing")
    else:
        assert observed_at is not None and generated_at is not None
        assert orderbook_available_at is not None
        assert orderbook_generated_at is not None
        assert available_at is not None and consumer_observed_at is not None
        assert decision_time is not None and expires_at is not None
        if not (
            observed_at
            <= orderbook_available_at
            <= orderbook_generated_at
            <= generated_at
            <= available_at
            <= consumer_observed_at
            <= decision_time
            <= expires_at
        ):
            reasons.append("behavior_receipt_exact_cost_temporal_order_invalid")
    return sorted(set(reasons))


def build_finalized_outcome_binding(row: Mapping[str, Any]) -> dict[str, Any]:
    """Build the canonical, after-cost terminal outcome used by exact PPO."""

    outcome_id = str(
        _first_present(row.get("finalized_outcome_id"), row.get("close_id")) or ""
    ).strip()
    close_id = str(row.get("close_id") or outcome_id).strip()
    if not outcome_id or not close_id or outcome_id != close_id:
        raise ValueError("finalized_outcome_identity_invalid")
    if row.get("outcome_availability_status") != "READY":
        raise ValueError("finalized_outcome_not_ready")
    decision_time = _strict_aware_utc(row.get("decision_time"))
    close_time = _strict_aware_utc(
        _first_present(row.get("close_event_time"), row.get("exit_time"))
    )
    generated_at = _strict_aware_utc(row.get("outcome_generated_at"))
    available_at = _strict_aware_utc(row.get("outcome_available_at"))
    if None in (decision_time, close_time, generated_at, available_at):
        raise ValueError("finalized_outcome_strict_utc_lineage_missing")
    assert decision_time is not None and close_time is not None
    assert generated_at is not None and available_at is not None
    if not decision_time < close_time <= generated_at <= available_at:
        raise ValueError("finalized_outcome_temporal_order_invalid")

    entry_price = _finite(row.get("entry_price"))
    exit_price = _finite(row.get("exit_price"))
    closed_quantity = _finite(row.get("closed_quantity"))
    if row.get("outcome_cost_unit") != "USD":
        raise ValueError("finalized_outcome_cost_unit_not_explicit_usd")
    if entry_price is None or entry_price <= 0.0:
        raise ValueError("finalized_outcome_entry_price_invalid")
    if exit_price is None or exit_price <= 0.0:
        raise ValueError("finalized_outcome_exit_price_invalid")
    if closed_quantity is None or closed_quantity <= 0.0:
        raise ValueError("finalized_outcome_closed_quantity_invalid")
    entry_notional_usd = entry_price * closed_quantity
    exit_notional_usd = exit_price * closed_quantity
    if entry_notional_usd <= 0.0:
        raise ValueError("finalized_outcome_entry_notional_not_positive")

    receipt_hash = str(row.get("behavior_policy_receipt_hash") or "")
    behavior_fingerprint = str(row.get("behavior_policy_fingerprint") or "")
    if not _SHA256_RE.fullmatch(receipt_hash):
        raise ValueError("finalized_outcome_receipt_hash_invalid")
    if not _SHA256_RE.fullmatch(behavior_fingerprint):
        raise ValueError("finalized_outcome_behavior_fingerprint_invalid")
    selected_action = str(
        _first_present(row.get("behavior_action"), row.get("selected_action")) or ""
    ).strip().lower()
    if selected_action not in {"long", "short"}:
        raise ValueError("finalized_outcome_action_invalid")
    side = str(row.get("side") or "").strip().lower()
    if side not in {"long", "short"}:
        raise ValueError("finalized_outcome_side_invalid")
    if side != selected_action:
        raise ValueError("finalized_outcome_side_action_mismatch")

    supplied_gross_pnl_usd = _finite(
        _first_present(
            row.get("gross_realized_pnl_usd"),
            row.get("realized_gross_pnl_usd"),
        )
    )
    recomputed_gross_pnl_usd = (
        (exit_price - entry_price) * closed_quantity
        if side == "long"
        else (entry_price - exit_price) * closed_quantity
    )
    if supplied_gross_pnl_usd is None:
        raise ValueError("finalized_outcome_gross_pnl_missing")
    if not _numbers_close(
        supplied_gross_pnl_usd,
        recomputed_gross_pnl_usd,
        tolerance=1e-9,
    ):
        raise ValueError("finalized_outcome_gross_pnl_price_arithmetic_mismatch")
    for gross_alias in (
        row.get("gross_realized_pnl_usd"),
        row.get("realized_gross_pnl_usd"),
    ):
        if gross_alias not in (None, "") and not _numbers_close(
            gross_alias,
            recomputed_gross_pnl_usd,
            tolerance=1e-9,
        ):
            raise ValueError("finalized_outcome_gross_pnl_alias_conflict")

    component_names = (
        "entry_fee_usd",
        "exit_fee_usd",
        "total_fees_usd",
        "fees_usd",
        "entry_slippage_usd",
        "exit_slippage_usd",
        "total_slippage_usd",
        "slippage_usd",
        "total_execution_costs_usd",
    )
    components = {name: _finite(row.get(name)) for name in component_names}
    if any(value is None for value in components.values()):
        raise ValueError("finalized_outcome_explicit_cost_components_missing")
    if any(float(value) < 0.0 for value in components.values() if value is not None):
        raise ValueError("finalized_outcome_cost_component_negative")
    entry_fee_usd = float(components["entry_fee_usd"])
    exit_fee_usd = float(components["exit_fee_usd"])
    total_fees_usd = float(components["total_fees_usd"])
    entry_slippage_usd = float(components["entry_slippage_usd"])
    exit_slippage_usd = float(components["exit_slippage_usd"])
    total_slippage_usd = float(components["total_slippage_usd"])
    total_execution_costs_usd = float(components["total_execution_costs_usd"])
    if not _numbers_close(
        total_fees_usd,
        entry_fee_usd + exit_fee_usd,
        tolerance=1e-12,
    ) or not _numbers_close(row.get("fees_usd"), total_fees_usd, tolerance=1e-12):
        raise ValueError("finalized_outcome_fee_component_arithmetic_mismatch")
    if not _numbers_close(
        total_slippage_usd,
        entry_slippage_usd + exit_slippage_usd,
        tolerance=1e-12,
    ) or not _numbers_close(
        row.get("slippage_usd"), total_slippage_usd, tolerance=1e-12
    ):
        raise ValueError("finalized_outcome_slippage_component_arithmetic_mismatch")
    if not _numbers_close(
        total_execution_costs_usd,
        total_fees_usd + total_slippage_usd,
        tolerance=1e-12,
    ):
        raise ValueError("finalized_outcome_execution_cost_arithmetic_mismatch")
    for alias, explicit in (
        (row.get("fees"), total_fees_usd),
        (row.get("slippage"), total_slippage_usd),
    ):
        if alias in (None, "") or not _numbers_close(
            alias, explicit, tolerance=1e-12
        ):
            raise ValueError("finalized_outcome_ambiguous_cost_alias_conflict")

    funding_usd = _finite(row.get("funding_usd"))
    funding_pnl_usd = _finite(row.get("funding_pnl_usd"))
    net_pnl_usd = _finite(row.get("realized_net_pnl_usd"))
    net_pnl_bps = _finite(row.get("realized_net_pnl_bps"))
    if None in (funding_usd, funding_pnl_usd, net_pnl_usd, net_pnl_bps):
        raise ValueError("finalized_outcome_economics_missing")
    assert funding_usd is not None and funding_pnl_usd is not None
    assert net_pnl_usd is not None and net_pnl_bps is not None
    if not _numbers_close(funding_usd, funding_pnl_usd, tolerance=1e-12):
        raise ValueError("finalized_outcome_funding_alias_conflict")
    if row.get("funding") in (None, "") or not _numbers_close(
        row.get("funding"), funding_usd, tolerance=1e-12
    ):
        raise ValueError("finalized_outcome_funding_alias_conflict")

    accounting_contract = {
        "paper_round_trip_cost_accounting_version": (
            FINALIZED_OUTCOME_COST_ACCOUNTING_VERSION
        ),
        "paper_cost_rate_scope": FINALIZED_OUTCOME_COST_RATE_SCOPE,
        "paper_net_pnl_formula": FINALIZED_OUTCOME_NET_FORMULA,
        "entry_cost_accounting_version": (
            FINALIZED_OUTCOME_ENTRY_COST_ACCOUNTING_VERSION
        ),
        "entry_cost_allocation_method": (
            FINALIZED_OUTCOME_ENTRY_COST_ALLOCATION_METHOD
        ),
        "entry_cost_basis_status": FINALIZED_OUTCOME_ENTRY_COST_BASIS_STATUS,
        "round_trip_cost_provenance_status": (
            FINALIZED_OUTCOME_COST_PROVENANCE_STATUS
        ),
        "exit_fee_rate_basis": FINALIZED_OUTCOME_EXIT_FEE_RATE_BASIS,
        "exit_slippage_provenance_status": (
            FINALIZED_OUTCOME_EXIT_SLIPPAGE_PROVENANCE_STATUS
        ),
    }
    for field_name, expected in accounting_contract.items():
        if row.get(field_name) != expected:
            raise ValueError(f"finalized_outcome_{field_name}_invalid")
    if row.get("round_trip_cost_fallback_used") is not False:
        raise ValueError("finalized_outcome_round_trip_cost_fallback_used")
    if row.get("entry_fee_fallback") is not False:
        raise ValueError("finalized_outcome_entry_fee_fallback_used")
    if row.get("entry_slippage_fallback") is not False:
        raise ValueError("finalized_outcome_entry_slippage_fallback_used")
    if row.get("exit_fee_fallback") is not False:
        raise ValueError("finalized_outcome_exit_fee_fallback_used")
    if row.get("exit_slippage_fallback") is not False:
        raise ValueError("finalized_outcome_exit_slippage_fallback_used")
    for field_name in (
        "entry_fee_source",
        "entry_slippage_source",
        "exit_fee_source",
        "exit_slippage_source",
    ):
        if not str(row.get(field_name) or "").strip():
            raise ValueError(f"finalized_outcome_{field_name}_missing")

    closed_entry_notional_usd = _finite(row.get("closed_entry_notional_usd"))
    closed_exit_notional_usd = _finite(row.get("closed_exit_notional_usd"))
    if not _numbers_close(
        closed_entry_notional_usd, entry_notional_usd, tolerance=1e-9
    ):
        raise ValueError("finalized_outcome_entry_notional_arithmetic_mismatch")
    if not _numbers_close(
        closed_exit_notional_usd, exit_notional_usd, tolerance=1e-9
    ):
        raise ValueError("finalized_outcome_exit_notional_arithmetic_mismatch")

    allocation_fraction = _finite(
        row.get("entry_cost_allocation_fraction_of_pre_close_position")
    )
    pre_close_quantity = _finite(row.get("entry_cost_pre_close_quantity"))
    allocated_closed_quantity = _finite(row.get("entry_cost_closed_quantity"))
    is_final_close = row.get("entry_cost_is_final_close")
    if (
        allocation_fraction is None
        or not 0.0 < allocation_fraction <= 1.0
        or pre_close_quantity is None
        or pre_close_quantity <= 0.0
        or allocated_closed_quantity is None
        or allocated_closed_quantity <= 0.0
        or not isinstance(is_final_close, bool)
    ):
        raise ValueError("finalized_outcome_entry_cost_allocation_invalid")
    if not _numbers_close(
        allocated_closed_quantity, closed_quantity, tolerance=1e-12
    ) or not _numbers_close(
        allocation_fraction,
        closed_quantity / pre_close_quantity,
        tolerance=1e-12,
    ):
        raise ValueError("finalized_outcome_entry_cost_allocation_arithmetic_mismatch")
    expected_final_close = _numbers_close(
        closed_quantity, pre_close_quantity, tolerance=1e-12
    )
    if is_final_close is not expected_final_close:
        raise ValueError("finalized_outcome_entry_cost_finality_mismatch")
    if is_final_close is not True:
        raise ValueError("finalized_outcome_partial_close_not_terminal")

    entry_fee_bps = _finite(row.get("entry_fee_bps_per_side"))
    exit_fee_bps = _finite(row.get("exit_fee_bps_per_side"))
    entry_slippage_bps = _finite(row.get("entry_slippage_bps_per_side"))
    exit_slippage_bps = _finite(row.get("exit_slippage_bps_per_side"))
    if any(
        value is None or value < 0.0
        for value in (
            entry_fee_bps,
            exit_fee_bps,
            entry_slippage_bps,
            exit_slippage_bps,
        )
    ):
        raise ValueError("finalized_outcome_per_side_cost_rate_invalid")
    assert entry_fee_bps is not None and exit_fee_bps is not None
    assert entry_slippage_bps is not None and exit_slippage_bps is not None
    for observed_bps, component_usd, notional_usd in (
        (entry_fee_bps, entry_fee_usd, entry_notional_usd),
        (exit_fee_bps, exit_fee_usd, exit_notional_usd),
        (entry_slippage_bps, entry_slippage_usd, entry_notional_usd),
        (exit_slippage_bps, exit_slippage_usd, exit_notional_usd),
    ):
        if not _numbers_close(
            observed_bps,
            component_usd / notional_usd * 10_000.0,
            tolerance=1e-9,
        ):
            raise ValueError("finalized_outcome_per_side_cost_rate_arithmetic_mismatch")
    if row.get("entry_fee_fallback_bps_per_side") not in (None, "") or row.get(
        "entry_slippage_fallback_bps_per_side"
    ) not in (None, ""):
        raise ValueError("finalized_outcome_unused_entry_fallback_rate_present")

    exit_slippage_available_at = _strict_aware_utc(
        row.get("exit_slippage_available_at")
    )
    if exit_slippage_available_at is None:
        raise ValueError("finalized_outcome_exit_slippage_available_at_invalid")
    if not decision_time <= exit_slippage_available_at <= close_time:
        raise ValueError("finalized_outcome_exit_slippage_temporal_order_invalid")

    recomputed_net_usd = (
        recomputed_gross_pnl_usd
        - entry_fee_usd
        - exit_fee_usd
        - entry_slippage_usd
        - exit_slippage_usd
        + funding_pnl_usd
    )
    recomputed_net_bps = recomputed_net_usd / entry_notional_usd * 10_000.0
    if not _numbers_close(net_pnl_usd, recomputed_net_usd, tolerance=1e-9):
        raise ValueError("finalized_outcome_net_usd_arithmetic_mismatch")
    if not _numbers_close(net_pnl_bps, recomputed_net_bps, tolerance=1e-9):
        raise ValueError("finalized_outcome_net_bps_arithmetic_mismatch")
    symbol = str(row.get("symbol") or "").strip().upper()
    prediction_id = str(row.get("prediction_id") or "").strip()
    position_id = str(row.get("position_id") or "").strip()
    if not symbol or not prediction_id or not position_id:
        raise ValueError("finalized_outcome_parent_identity_missing")

    reward = net_pnl_bps / 100.0
    material = {
        "schema_version": FINALIZED_OUTCOME_SCHEMA_VERSION,
        "finalized_outcome_id": outcome_id,
        "symbol": symbol,
        "prediction_id": prediction_id,
        "position_id": position_id,
        "selected_action": selected_action,
        "decision_time": decision_time.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
        "close_event_time": close_time.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
        "outcome_generated_at": generated_at.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z"),
        "outcome_available_at": available_at.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z"),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "side": side,
        "closed_quantity": closed_quantity,
        "entry_notional_usd": entry_notional_usd,
        "exit_notional_usd": exit_notional_usd,
        "gross_realized_pnl_usd": recomputed_gross_pnl_usd,
        "entry_fee_usd": entry_fee_usd,
        "exit_fee_usd": exit_fee_usd,
        "total_fees_usd": total_fees_usd,
        "entry_slippage_usd": entry_slippage_usd,
        "exit_slippage_usd": exit_slippage_usd,
        "total_slippage_usd": total_slippage_usd,
        "total_execution_costs_usd": total_execution_costs_usd,
        "funding_usd": funding_pnl_usd,
        "realized_net_pnl_usd": net_pnl_usd,
        "realized_net_pnl_bps": net_pnl_bps,
        **accounting_contract,
        "round_trip_cost_fallback_used": False,
        "entry_cost_allocation_fraction_of_pre_close_position": (
            allocation_fraction
        ),
        "entry_cost_pre_close_quantity": pre_close_quantity,
        "entry_cost_closed_quantity": allocated_closed_quantity,
        "entry_cost_is_final_close": is_final_close,
        "entry_fee_source": str(row.get("entry_fee_source")),
        "entry_fee_fallback": False,
        "entry_slippage_source": str(row.get("entry_slippage_source")),
        "entry_slippage_fallback": False,
        "exit_fee_source": str(row.get("exit_fee_source")),
        "exit_fee_fallback": False,
        "exit_slippage_source": str(row.get("exit_slippage_source")),
        "exit_slippage_available_at": (
            exit_slippage_available_at.isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            )
        ),
        "exit_slippage_fallback": False,
        "entry_fee_bps_per_side": entry_fee_bps,
        "exit_fee_bps_per_side": exit_fee_bps,
        "entry_slippage_bps_per_side": entry_slippage_bps,
        "exit_slippage_bps_per_side": exit_slippage_bps,
        "reward": reward,
        "net_formula": FINALIZED_OUTCOME_NET_FORMULA,
        "reward_formula": FINALIZED_OUTCOME_REWARD_FORMULA,
        "behavior_policy_receipt_hash": receipt_hash,
        "behavior_policy_fingerprint": behavior_fingerprint,
    }
    digest = canonical_sha256(material)
    return {
        "finalized_outcome_schema_version": FINALIZED_OUTCOME_SCHEMA_VERSION,
        "finalized_outcome_id": outcome_id,
        "finalized_outcome_digest": digest,
        "finalized_outcome_digest_material": material,
        "finalized_outcome_finality_proven": True,
        "finalized_outcome_reward": reward,
        "finalized_outcome_entry_notional_usd": entry_notional_usd,
        "outcome_finalized": True,
    }


def finalized_outcome_binding_rejection_reasons(row: Mapping[str, Any]) -> list[str]:
    try:
        expected = build_finalized_outcome_binding(row)
    except (TypeError, ValueError) as exc:
        return [str(exc)]
    reasons: list[str] = []
    for field in (
        "finalized_outcome_schema_version",
        "finalized_outcome_id",
        "finalized_outcome_digest",
        "finalized_outcome_finality_proven",
        "finalized_outcome_reward",
        "finalized_outcome_entry_notional_usd",
        "outcome_finalized",
    ):
        observed = row.get(field)
        wanted = expected[field]
        if isinstance(wanted, float):
            if not _numbers_close(observed, wanted, tolerance=1e-12):
                reasons.append(f"{field}_mismatch")
        elif observed != wanted:
            reasons.append(f"{field}_mismatch")
    material = row.get("finalized_outcome_digest_material")
    if not isinstance(material, Mapping):
        reasons.append("finalized_outcome_digest_material_missing")
    else:
        try:
            if canonical_sha256(material) != expected["finalized_outcome_digest"]:
                reasons.append("finalized_outcome_digest_material_hash_mismatch")
        except (TypeError, ValueError):
            reasons.append("finalized_outcome_digest_material_invalid")
    return sorted(set(reasons))


def build_ppo_consumption_update_key(
    *,
    behavior_policy_receipt_hash: Any,
    finalized_outcome_digest: Any,
    parent_behavior_fingerprint: Any,
) -> str:
    receipt_hash = str(behavior_policy_receipt_hash or "")
    outcome_digest = str(finalized_outcome_digest or "")
    parent_fingerprint = str(parent_behavior_fingerprint or "")
    if not all(
        _SHA256_RE.fullmatch(value)
        for value in (receipt_hash, outcome_digest, parent_fingerprint)
    ):
        raise ValueError("ppo_consumption_update_key_identity_invalid")
    return _canonical_ppo_update_key(
        receipt_hash=receipt_hash,
        finalized_outcome_digest=outcome_digest,
        parent_policy_fingerprint=parent_fingerprint,
    )


def ppo_consumption_update_key_from_row(row: Mapping[str, Any]) -> str:
    return build_ppo_consumption_update_key(
        behavior_policy_receipt_hash=row.get("behavior_policy_receipt_hash"),
        finalized_outcome_digest=row.get("finalized_outcome_digest"),
        parent_behavior_fingerprint=row.get("behavior_policy_fingerprint"),
    )


def _softmax(logits: Sequence[float], mask: Sequence[bool] | None = None) -> tuple[float, ...]:
    if len(logits) != ACTION_COUNT:
        raise ValueError("action_logits_length_mismatch")
    enabled = tuple(True for _ in logits) if mask is None else tuple(mask)
    if len(enabled) != ACTION_COUNT or not any(enabled):
        raise ValueError("behavior_action_mask_invalid")
    finite_logits = tuple(float(value) for value in logits)
    if any(not math.isfinite(value) for value in finite_logits):
        raise ValueError("action_logits_nonfinite")
    maximum = max(value for value, allowed in zip(finite_logits, enabled, strict=False) if allowed)
    weights = tuple(
        math.exp(value - maximum) if allowed else 0.0
        for value, allowed in zip(finite_logits, enabled, strict=False)
    )
    total = sum(weights)
    if not math.isfinite(total) or total <= 0.0:
        raise ValueError("behavior_distribution_not_normalizable")
    return tuple(value / total for value in weights)


def _positive_edge_entry_mask(
    *, expected_move_bps: float, round_trip_cost_bps: float
) -> tuple[bool, ...]:
    """Allow HOLD plus only entry actions with strictly positive after-cost edge."""
    mask = [False] * ACTION_COUNT
    mask[0] = True
    long_after_cost_bps = expected_move_bps - round_trip_cost_bps
    short_after_cost_bps = -expected_move_bps - round_trip_cost_bps
    if ACTION_COUNT > 1 and long_after_cost_bps > 0.0:
        mask[1] = True
    if ACTION_COUNT > 2 and short_after_cost_bps > 0.0:
        mask[2] = True
    return tuple(mask)


def _sample_index(probabilities: Sequence[float], draw_u53: int) -> int:
    if not 0 <= draw_u53 < U53_DENOMINATOR:
        raise ValueError("sample_draw_u53_out_of_range")
    draw = draw_u53 / U53_DENOMINATOR
    cumulative = 0.0
    last_positive: int | None = None
    for index, probability in enumerate(probabilities):
        value = float(probability)
        if value > 0.0:
            last_positive = index
        cumulative += value
        if draw < cumulative:
            return index
    if last_positive is None:
        raise ValueError("behavior_distribution_has_no_positive_action")
    return last_positive


def adaptive_on_policy_lane_plan(
    candidates: Sequence[Mapping[str, Any]],
    *,
    paper_margin_status: Mapping[str, Any] | None,
    paper_entry_freeze: Mapping[str, Any] | None,
    carry_in: Any = 0.0,
    single_candidate_ordinary_credit_in: Any = 0,
) -> dict[str, Any]:
    """Select a bounded adaptive paper sampling lane without market thresholds.

    The lane consumes a continuous token credit derived from current policy
    entropy, fitted profitability uncertainty, strictly positive after-cost
    edge quality, and canonical paper-margin headroom.  It never displaces the
    entire ordinary lane: multi-candidate cycles reserve at least one ordinary
    prediction, while single-candidate cycles require an ordinary cycle between
    samples.  Missing/failing safety truth yields zero sampled candidates while
    leaving ordinary predictions untouched.
    """

    if ACTION_COUNT != ADAPTIVE_ON_POLICY_ACTION_COUNT:
        raise ValueError("adaptive_on_policy_action_contract_count_mismatch")

    rows = [dict(candidate) for candidate in candidates]
    margin = dict(paper_margin_status or {})
    freeze = dict(paper_entry_freeze or {})
    carry = _finite(carry_in)
    carry = min(1.0, max(0.0, carry if carry is not None else 0.0))
    ordinary_credit = _strict_int(single_candidate_ordinary_credit_in)
    ordinary_credit = max(0, ordinary_credit if ordinary_credit is not None else 0)
    safety_reasons: list[str] = []
    if margin.get("invariant_holds") is not True:
        safety_reasons.append("paper_margin_invariant_not_proven")
    if margin.get("paper_only") is not True:
        safety_reasons.append("paper_margin_status_not_paper_only")
    if margin.get("routes_to_live") is not False:
        safety_reasons.append("paper_margin_status_live_route_not_false")
    if margin.get("places_real_order") is not False:
        safety_reasons.append("paper_margin_status_real_order_not_false")
    margin_base = _finite(margin.get("margin_base_usd"))
    free_after_buffer = _finite(margin.get("free_margin_after_buffer_usd"))
    if margin_base is None or margin_base <= 0.0:
        safety_reasons.append("paper_margin_base_not_positive")
    if free_after_buffer is None or free_after_buffer <= 0.0:
        safety_reasons.append("paper_free_margin_after_buffer_not_positive")
    if freeze.get("paper_new_entries_halted") is not False:
        safety_reasons.append("paper_entry_freeze_not_explicitly_clear")
    if freeze.get("new_entries_allowed") is not True:
        safety_reasons.append("paper_new_entries_not_explicitly_allowed")
    if freeze.get("paper_only") is not True:
        safety_reasons.append("paper_entry_gate_not_paper_only")
    if freeze.get("routes_to_live") is not False:
        safety_reasons.append("paper_entry_gate_live_route_not_false")
    if freeze.get("places_real_order") is not False:
        safety_reasons.append("paper_entry_gate_real_order_not_false")
    margin_headroom = (
        min(1.0, max(0.0, free_after_buffer / margin_base))
        if not safety_reasons and margin_base is not None and free_after_buffer is not None
        else 0.0
    )

    candidate_audit: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        reasons: list[str] = list(safety_reasons)
        cutoff = _strict_aware_utc(row.get("feature_cutoff"))
        available = _strict_aware_utc(row.get("available_at"))
        candle_close = _strict_aware_utc(row.get("candle_close_time"))
        decision = _strict_aware_utc(row.get("decision_time"))
        if row.get("candle_closed_confirmed") is not True:
            reasons.append("candle_finality_not_proven")
        if None in (cutoff, available, candle_close, decision):
            reasons.append("strict_utc_lineage_missing")
        else:
            assert cutoff is not None and available is not None
            assert candle_close is not None and decision is not None
            if (
                candle_close > cutoff
                or cutoff > available
                or available >= decision
                or candle_close >= decision
            ):
                reasons.append("temporal_order_invalid")
        row_classification = str(row.get("row_classification") or "").upper()
        if row_classification != "TRAINABLE":
            reasons.append("on_policy_learning_row_not_trainable")
        if row.get("served_policy_fingerprint_available") is not True:
            reasons.append("served_policy_fingerprint_unavailable")
        if not _SHA256_RE.fullmatch(
            str(row.get("served_policy_fingerprint") or "")
        ):
            reasons.append("served_policy_fingerprint_unavailable")
        if not _is_real_checkpoint_id(row.get("checkpoint_id")):
            reasons.append("real_checkpoint_generation_unavailable")
        if not _SHA256_RE.fullmatch(
            str(row.get("checkpoint_weight_sha256") or "")
        ):
            reasons.append("checkpoint_weight_hash_unavailable")
        if not _SHA256_RE.fullmatch(
            str(row.get("checkpoint_evidence_digest") or "")
        ):
            reasons.append("checkpoint_evidence_digest_unavailable")
        if row.get("checkpoint_evidence_verified") is not True:
            reasons.append("checkpoint_evidence_not_verified")
        if row.get("checkpoint_identity_verified") is not True:
            reasons.append("checkpoint_identity_not_verified")
        if not str(row.get("symbol") or "").strip():
            reasons.append("symbol_identity_missing")
        if not str(row.get("timeframe") or "").strip():
            reasons.append("timeframe_identity_missing")
        if row.get("exact_cost_provenance_valid") is not True:
            reasons.append("exact_adaptive_cost_provenance_unavailable")
        if row.get("confidence_calibration_fitted") is not True:
            reasons.append("profitability_calibration_not_fitted")
        confidence = _finite(row.get("confidence_calibrated"))
        if confidence is None or not 0.0 <= confidence <= 1.0:
            reasons.append("profitability_confidence_invalid")
        expected_move = _finite(row.get("expected_move_bps"))
        cost = _finite(row.get("round_trip_cost_bps"))
        if expected_move is None or cost is None or cost < 0.0:
            reasons.append("after_cost_edge_inputs_invalid")
            positive_edge = 0.0
            expected_confidence_action = None
        else:
            long_edge = expected_move - cost
            short_edge = -expected_move - cost
            positive_edge = max(0.0, long_edge, short_edge)
            if positive_edge <= 0.0:
                reasons.append("no_strictly_positive_after_cost_entry_action")
                expected_confidence_action = None
            else:
                expected_confidence_action = (
                    "long" if long_edge >= short_edge else "short"
                )
        observed_confidence_action = row.get("confidence_candidate_action")
        if observed_confidence_action != expected_confidence_action:
            reasons.append("confidence_candidate_action_invalid")
        raw_logits: tuple[float, ...] = ()
        sealed_raw_logits: list[float] = []
        try:
            raw_logits = tuple(float(value) for value in (row.get("raw_action_logits") or ()))
            raw_probabilities = _softmax(raw_logits)
            sealed_raw_logits = list(raw_logits)
            entropy = -sum(
                probability * math.log(probability)
                for probability in raw_probabilities
                if probability > 0.0
            ) / math.log(ACTION_COUNT)
            raw_policy_logits_hash = canonical_sha256({"raw_action_logits": list(raw_logits)})
        except (TypeError, ValueError):
            entropy = 0.0
            raw_policy_logits_hash = None
            reasons.append("raw_policy_distribution_invalid")
        uncertainty = (
            1.0 - abs((2.0 * confidence) - 1.0)
            if confidence is not None and 0.0 <= confidence <= 1.0
            else 0.0
        )
        edge_quality = (
            positive_edge / (positive_edge + abs(cost))
            if positive_edge > 0.0 and cost is not None and positive_edge + abs(cost) > 0.0
            else 0.0
        )
        adaptive_score = (
            max(0.0, entropy * uncertainty * edge_quality * margin_headroom) ** 0.25
            if not reasons
            else 0.0
        )
        candidate_credit = adaptive_score / (1.0 + adaptive_score) if adaptive_score > 0.0 else 0.0
        identity = {
            "index": index,
            "symbol": str(row.get("symbol") or "").upper(),
            "timeframe": str(row.get("timeframe") or ""),
            "feature_tensor_id": str(row.get("feature_tensor_id") or ""),
            "feature_cutoff": str(row.get("feature_cutoff") or ""),
            "available_at": str(row.get("available_at") or ""),
            "candle_close_time": str(row.get("candle_close_time") or ""),
            "candle_closed_confirmed": row.get("candle_closed_confirmed") is True,
            "decision_time": str(row.get("decision_time") or ""),
            "row_classification": str(row.get("row_classification") or ""),
            "confidence_candidate_action": (
                observed_confidence_action
                if observed_confidence_action in {"long", "short"}
                else None
            ),
            "served_policy_fingerprint": str(
                row.get("served_policy_fingerprint") or ""
            ),
            "served_policy_fingerprint_available": (
                row.get("served_policy_fingerprint_available") is True
            ),
            "exact_cost_provenance_valid": (
                row.get("exact_cost_provenance_valid") is True
            ),
            "confidence_calibration_fitted": (
                row.get("confidence_calibration_fitted") is True
            ),
            "raw_action_logits": sealed_raw_logits,
            "exact_cost_payload_hash": str(
                row.get("exact_cost_payload_hash") or ""
            ),
            "checkpoint_id": str(row.get("checkpoint_id") or ""),
            "checkpoint_weight_sha256": str(
                row.get("checkpoint_weight_sha256") or ""
            ),
            "checkpoint_evidence_digest": str(
                row.get("checkpoint_evidence_digest") or ""
            ),
            "checkpoint_evidence_verified": (
                row.get("checkpoint_evidence_verified") is True
            ),
            "checkpoint_identity_verified": (
                row.get("checkpoint_identity_verified") is True
            ),
        }
        candidate_audit.append(
            {
                **identity,
                "eligible": not reasons,
                "rejection_reasons": sorted(set(reasons)),
                "policy_entropy_normalized": entropy,
                "profitability_uncertainty": uncertainty,
                "profitability_confidence_calibrated": confidence,
                "expected_move_bps": expected_move,
                "round_trip_cost_bps": cost,
                "raw_policy_logits_hash": raw_policy_logits_hash,
                "positive_after_cost_edge_bps": positive_edge,
                "positive_edge_quality": edge_quality,
                "paper_margin_headroom": margin_headroom,
                "adaptive_score": adaptive_score,
                "candidate_token_credit": candidate_credit,
                "rank_tiebreak_hash": canonical_sha256(identity),
            }
        )

    eligible = [row for row in candidate_audit if row["eligible"] is True]
    token_budget = carry + sum(float(row["candidate_token_credit"]) for row in eligible)
    requested_count = int(math.floor(token_budget))
    candidate_count = len(rows)
    if candidate_count <= 0:
        max_sampled = 0
    elif candidate_count == 1:
        max_sampled = 1 if ordinary_credit >= 1 else 0
    else:
        max_sampled = max(0, candidate_count - 1)
    selected_count = min(requested_count, len(eligible), max_sampled)
    ranked = sorted(
        eligible,
        key=lambda row: (
            -float(row["adaptive_score"]),
            str(row["rank_tiebreak_hash"]),
        ),
    )
    selected_indices = sorted(int(row["index"]) for row in ranked[:selected_count])
    carry_out = min(1.0, max(0.0, token_budget - selected_count))
    if candidate_count == 1:
        ordinary_credit_out = 0 if selected_count else ordinary_credit + 1
    else:
        ordinary_credit_out = ordinary_credit
    paper_margin_inputs = {
        "schema_version": str(margin.get("schema_version") or ""),
        "generated_utc": str(margin.get("generated_utc") or ""),
        "status": str(margin.get("status") or ""),
        "invariant_holds": margin.get("invariant_holds") is True,
        "margin_base_usd": margin_base,
        "free_margin_after_buffer_usd": free_after_buffer,
        "paper_only": margin.get("paper_only") is True,
        "routes_to_live": margin.get("routes_to_live") is True,
        "places_real_order": margin.get("places_real_order") is True,
    }
    paper_entry_freeze_inputs = {
        field: freeze.get(field)
        for field in (
            "schema_version",
            "generated_utc",
            "paper_new_entries_halted",
            "new_entries_allowed",
            "paper_only",
            "routes_to_live",
            "places_real_order",
        )
    }
    input_material = {
        "schema_version": ADAPTIVE_ON_POLICY_LANE_SCHEMA_VERSION,
        "formula": ADAPTIVE_ON_POLICY_LANE_FORMULA,
        "carry_in": carry,
        "single_candidate_ordinary_credit_in": ordinary_credit,
        "paper_margin_inputs": paper_margin_inputs,
        "paper_entry_freeze_inputs": paper_entry_freeze_inputs,
        "candidate_audit": candidate_audit,
    }
    input_hash = canonical_sha256(input_material)
    result = {
        "schema_version": ADAPTIVE_ON_POLICY_LANE_SCHEMA_VERSION,
        "formula": ADAPTIVE_ON_POLICY_LANE_FORMULA,
        "input_hash": input_hash,
        "safety_gate_passed": not safety_reasons,
        "safety_rejection_reasons": sorted(set(safety_reasons)),
        "candidate_count": candidate_count,
        "eligible_candidate_count": len(eligible),
        "requested_sample_count": requested_count,
        "selected_sample_count": selected_count,
        "selected_indices": selected_indices,
        "ordinary_lane_reserved_count": candidate_count - selected_count,
        "structural_ordinary_lane_reservation": True,
        "market_static_sampling_threshold_used": False,
        "token_budget_before_selection": token_budget,
        "carry_in": carry,
        "carry_out": carry_out,
        "single_candidate_ordinary_credit_in": ordinary_credit,
        "single_candidate_ordinary_credit_out": ordinary_credit_out,
        # Carry the exact safety inputs in the signed plan.  The publisher can
        # therefore fail closed on margin/freeze drift instead of trusting only
        # a pre-computed boolean detached from its evidence.
        "paper_margin_inputs": paper_margin_inputs,
        "paper_entry_freeze_inputs": paper_entry_freeze_inputs,
        "candidate_audit": candidate_audit,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    result["plan_hash"] = canonical_sha256(result)
    return result


def model_parameter_fingerprint(model: Any) -> str:
    """Hash the exact in-memory parameters used for the serving forward pass."""
    digest = hashlib.sha256()
    digest.update(b"v2_in_memory_served_policy_parameters_v1\0")
    digest.update(str(getattr(model, "model_id", "")).encode("utf-8"))
    digest.update(b"\0")
    net = getattr(model, "net", None)
    if getattr(model, "torch_available", False) and net is not None:
        state = net.state_dict()
        for name in sorted(state):
            tensor = state[name].detach().cpu().contiguous()
            array = tensor.numpy()
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(array.dtype).encode("ascii"))
            digest.update(b"\0")
            digest.update(json.dumps(list(array.shape), separators=(",", ":")).encode("ascii"))
            digest.update(b"\0")
            digest.update(memoryview(array).cast("B"))
        return digest.hexdigest()
    fallback_weights = getattr(model, "_fallback_weights", None)
    if not isinstance(fallback_weights, list) or not fallback_weights:
        raise ValueError("served_policy_parameters_unavailable")
    for value in fallback_weights:
        parsed = _finite(value)
        if parsed is None:
            raise ValueError("served_policy_parameter_nonfinite")
        digest.update(struct.pack("!d", parsed))
    return digest.hexdigest()


def build_positive_edge_behavior_receipt(
    *,
    prediction_id: str,
    model_output: Any,
    symbol: str,
    timeframe: str,
    checkpoint_id: str,
    checkpoint_weight_sha256: str,
    checkpoint_evidence_digest: str,
    checkpoint_evidence_verified: bool,
    checkpoint_identity_verified: bool,
    served_policy_fingerprint: str,
    feature_tensor_id: str,
    feature_vector_hash: str,
    feature_cutoff: Any,
    available_at: Any,
    candle_close_time: Any,
    decision_time: Any,
    candle_closed_confirmed: Any,
    round_trip_cost_bps: Any,
    cost_provenance: Mapping[str, Any],
    draw_u53: int,
    sampling_plan_hash: str,
    sampling_plan_input_hash: str,
) -> dict[str, Any]:
    """Build and self-validate one exact masked categorical behavior receipt."""
    symbol_normalized = str(symbol or "").strip().upper()
    timeframe_normalized = str(timeframe or "").strip()
    if (
        not prediction_id
        or not symbol_normalized
        or not timeframe_normalized
        or not checkpoint_id
        or not feature_tensor_id
        or not feature_vector_hash
    ):
        raise ValueError("behavior_receipt_identity_missing")
    if not _is_real_checkpoint_id(checkpoint_id):
        raise ValueError("behavior_receipt_checkpoint_id_not_real_generation")
    if not _SHA256_RE.fullmatch(str(served_policy_fingerprint or "")):
        raise ValueError("served_policy_fingerprint_invalid")
    if not _SHA256_RE.fullmatch(str(sampling_plan_hash or "")):
        raise ValueError("on_policy_sampling_plan_hash_invalid")
    if not _SHA256_RE.fullmatch(str(sampling_plan_input_hash or "")):
        raise ValueError("on_policy_sampling_plan_input_hash_invalid")
    if not _SHA256_RE.fullmatch(str(checkpoint_weight_sha256 or "")):
        raise ValueError("checkpoint_weight_sha256_invalid")
    if not _SHA256_RE.fullmatch(str(checkpoint_evidence_digest or "")):
        raise ValueError("checkpoint_evidence_digest_invalid")
    if checkpoint_evidence_verified is not True:
        raise ValueError("checkpoint_evidence_not_verified")
    if checkpoint_identity_verified is not True:
        raise ValueError("checkpoint_identity_not_verified")
    cutoff = _strict_aware_utc(feature_cutoff)
    available = _strict_aware_utc(available_at)
    candle_close = _strict_aware_utc(candle_close_time)
    decision = _strict_aware_utc(decision_time)
    if None in (cutoff, available, candle_close, decision):
        raise ValueError("behavior_receipt_strict_utc_lineage_missing")
    assert cutoff is not None and available is not None
    assert candle_close is not None and decision is not None
    if candle_closed_confirmed is not True:
        raise ValueError("behavior_receipt_candle_finality_unproven")
    if candle_close > cutoff:
        raise ValueError("behavior_receipt_candle_close_after_feature_cutoff")
    if cutoff > available:
        raise ValueError("behavior_receipt_feature_cutoff_after_available_at")
    if available >= decision:
        raise ValueError("behavior_receipt_available_at_not_before_decision_time")
    if candle_close >= decision:
        raise ValueError("behavior_receipt_candle_close_not_before_decision_time")
    expected_move = _finite(getattr(model_output, "expected_move_bps", None))
    policy_value = _finite(getattr(model_output, "policy_value", None))
    cost = _finite(round_trip_cost_bps)
    if expected_move is None or policy_value is None or cost is None or cost < 0.0:
        raise ValueError("behavior_receipt_policy_or_cost_nonfinite")
    cost_reasons = exact_cost_provenance_rejection_reasons(
        cost_provenance,
        expected_symbol=symbol_normalized,
        expected_round_trip_cost_bps=cost,
        expected_decision_time=decision,
    )
    if cost_reasons:
        raise ValueError("behavior_receipt_exact_cost_invalid:" + ",".join(cost_reasons))
    logits = tuple(float(value) for value in getattr(model_output, "action_logits", ()))
    raw_probabilities = _softmax(logits)
    action_mask = _positive_edge_entry_mask(
        expected_move_bps=expected_move,
        round_trip_cost_bps=cost,
    )
    probabilities = _softmax(logits, action_mask)
    selected_index = _sample_index(probabilities, draw_u53)
    selected_probability = probabilities[selected_index]
    receipt: dict[str, Any] = {
        "schema_version": ON_POLICY_RECEIPT_SCHEMA_VERSION,
        "prediction_id": str(prediction_id),
        "symbol": symbol_normalized,
        "timeframe": timeframe_normalized,
        "decision_time": decision.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "feature_cutoff": cutoff.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "available_at": available.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "candle_close_time": candle_close.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        "candle_closed_confirmed": True,
        "feature_tensor_id": str(feature_tensor_id),
        "feature_vector_hash": str(feature_vector_hash),
        "model_id": str(getattr(model_output, "model_id", "")),
        "checkpoint_id": str(checkpoint_id),
        "checkpoint_weight_sha256": str(checkpoint_weight_sha256),
        "checkpoint_evidence_digest": str(checkpoint_evidence_digest),
        "checkpoint_evidence_verified": True,
        "checkpoint_identity_verified": True,
        "served_policy_fingerprint": str(served_policy_fingerprint),
        "behavior_policy_sampling_mode": ON_POLICY_SAMPLING_MODE,
        "behavior_policy_distribution_contract": ON_POLICY_DISTRIBUTION_CONTRACT,
        "behavior_action_source": ON_POLICY_ACTION_SOURCE,
        "behavior_action_mask_source": ON_POLICY_MASK_SOURCE,
        "on_policy_sampling_selected": True,
        "on_policy_sampling_lane": "ADAPTIVE_BOUNDED_PAPER_EXPLORATION",
        "on_policy_sampling_plan_hash": str(sampling_plan_hash),
        "on_policy_sampling_plan_input_hash": str(sampling_plan_input_hash),
        "on_policy_sampling_evidence_class": "PAPER_EXPLORATION_LEARNING_ONLY",
        "on_policy_sampling_counts_as_a_plus_evidence": False,
        "on_policy_sampling_routes_to_live": False,
        "action_labels": list(ACTION_LABELS),
        "raw_action_logits": list(logits),
        "raw_action_probabilities": list(raw_probabilities),
        "behavior_action_mask": list(action_mask),
        "action_probabilities": list(probabilities),
        "selected_action_index": selected_index,
        "selected_action": ACTION_LABELS[selected_index],
        "selected_action_probability": selected_probability,
        "selected_action_log_prob": math.log(selected_probability),
        "policy_value": policy_value,
        "expected_move_bps": expected_move,
        "round_trip_cost_bps": cost,
        "cost_provenance": dict(cost_provenance),
        "cost_source_payload_sha256": cost_provenance.get(
            "source_payload_sha256"
        ),
        "long_after_cost_bps": expected_move - cost,
        "short_after_cost_bps": -expected_move - cost,
        "positive_edge_required": True,
        "sample_draw_u53": int(draw_u53),
        "sample_draw_denominator": U53_DENOMINATOR,
        "strategy_supply_hypothesis": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    receipt["receipt_hash"] = canonical_sha256(receipt)
    reasons = behavior_receipt_rejection_reasons(receipt)
    if reasons:
        raise ValueError("behavior_receipt_self_validation_failed:" + ",".join(reasons))
    return receipt


def _sequence_close(left: Any, right: Sequence[float], *, tolerance: float = 1e-12) -> bool:
    if not isinstance(left, list | tuple) or len(left) != len(right):
        return False
    for observed, expected in zip(left, right, strict=False):
        parsed = _finite(observed)
        if parsed is None or not math.isclose(
            parsed,
            float(expected),
            rel_tol=tolerance,
            abs_tol=tolerance,
        ):
            return False
    return True


def behavior_receipt_rejection_reasons(
    receipt: Any,
    *,
    expected_prediction_id: Any = None,
    expected_symbol: Any = None,
    expected_timeframe: Any = None,
    expected_action: Any = None,
    expected_action_index: Any = None,
    expected_checkpoint_id: Any = None,
    expected_checkpoint_weight_sha256: Any = None,
    expected_checkpoint_evidence_digest: Any = None,
    expected_feature_tensor_id: Any = None,
    expected_feature_vector_hash: Any = None,
    expected_feature_cutoff: Any = None,
    expected_available_at: Any = None,
    expected_decision_time: Any = None,
    expected_policy_fingerprint: Any = None,
    expected_sampling_plan_hash: Any = None,
    expected_sampling_plan_input_hash: Any = None,
) -> list[str]:
    reasons: list[str] = []
    if not isinstance(receipt, Mapping):
        return ["behavior_policy_receipt_missing"]
    row = dict(receipt)
    receipt_hash = row.pop("receipt_hash", None)
    try:
        computed_hash = canonical_sha256(row)
    except (TypeError, ValueError):
        computed_hash = None
    if not _SHA256_RE.fullmatch(str(receipt_hash or "")) or receipt_hash != computed_hash:
        reasons.append("behavior_policy_receipt_hash_invalid")
    if receipt.get("schema_version") != ON_POLICY_RECEIPT_SCHEMA_VERSION:
        reasons.append("behavior_policy_receipt_schema_mismatch")
    for field, expected in (
        ("behavior_policy_sampling_mode", ON_POLICY_SAMPLING_MODE),
        ("behavior_policy_distribution_contract", ON_POLICY_DISTRIBUTION_CONTRACT),
        ("behavior_action_source", ON_POLICY_ACTION_SOURCE),
        ("behavior_action_mask_source", ON_POLICY_MASK_SOURCE),
        ("on_policy_sampling_lane", "ADAPTIVE_BOUNDED_PAPER_EXPLORATION"),
        (
            "on_policy_sampling_evidence_class",
            "PAPER_EXPLORATION_LEARNING_ONLY",
        ),
    ):
        if receipt.get(field) != expected:
            reasons.append(f"{field}_mismatch")
    for field, expected in (
        ("paper_only", True),
        ("routes_to_live", False),
        ("places_real_order", False),
        ("strategy_supply_hypothesis", False),
        ("candle_closed_confirmed", True),
        ("positive_edge_required", True),
        ("on_policy_sampling_selected", True),
        ("on_policy_sampling_counts_as_a_plus_evidence", False),
        ("on_policy_sampling_routes_to_live", False),
    ):
        if receipt.get(field) is not expected:
            reasons.append(f"{field}_mismatch")
    cutoff = _strict_aware_utc(receipt.get("feature_cutoff"))
    available = _strict_aware_utc(receipt.get("available_at"))
    candle_close = _strict_aware_utc(receipt.get("candle_close_time"))
    decision = _strict_aware_utc(receipt.get("decision_time"))
    if None in (cutoff, available, candle_close, decision):
        reasons.append("behavior_receipt_strict_utc_lineage_invalid")
    else:
        assert cutoff is not None and available is not None
        assert candle_close is not None and decision is not None
        if (
            candle_close > cutoff
            or cutoff > available
            or available >= decision
            or candle_close >= decision
        ):
            reasons.append("behavior_receipt_temporal_order_invalid")
    served_fingerprint = str(receipt.get("served_policy_fingerprint") or "")
    if not _SHA256_RE.fullmatch(served_fingerprint):
        reasons.append("served_policy_fingerprint_invalid")
    for field in (
        "on_policy_sampling_plan_hash",
        "on_policy_sampling_plan_input_hash",
    ):
        if not _SHA256_RE.fullmatch(str(receipt.get(field) or "")):
            reasons.append(f"{field}_invalid")
    checkpoint_hash = receipt.get("checkpoint_weight_sha256")
    if not _SHA256_RE.fullmatch(str(checkpoint_hash or "")):
        reasons.append("checkpoint_weight_sha256_invalid")
    if not _SHA256_RE.fullmatch(
        str(receipt.get("checkpoint_evidence_digest") or "")
    ):
        reasons.append("checkpoint_evidence_digest_invalid")
    if receipt.get("checkpoint_evidence_verified") is not True:
        reasons.append("checkpoint_evidence_not_verified")
    if receipt.get("checkpoint_identity_verified") is not True:
        reasons.append("checkpoint_identity_not_verified")
    if not receipt.get("prediction_id") or not _is_real_checkpoint_id(
        receipt.get("checkpoint_id")
    ):
        reasons.append("behavior_receipt_identity_missing")
    if not str(receipt.get("symbol") or "").strip() or not str(
        receipt.get("timeframe") or ""
    ).strip():
        reasons.append("behavior_receipt_market_identity_missing")
    if not receipt.get("feature_tensor_id") or not receipt.get("feature_vector_hash"):
        reasons.append("behavior_receipt_feature_identity_missing")
    if list(receipt.get("action_labels") or []) != list(ACTION_LABELS):
        reasons.append("behavior_receipt_action_labels_mismatch")
    logits_raw = receipt.get("raw_action_logits")
    try:
        logits = tuple(float(value) for value in logits_raw)
        raw_probabilities = _softmax(logits)
    except (TypeError, ValueError):
        logits = ()
        raw_probabilities = ()
        reasons.append("behavior_receipt_raw_logits_invalid")
    if raw_probabilities and not _sequence_close(
        receipt.get("raw_action_probabilities"), raw_probabilities
    ):
        reasons.append("behavior_receipt_raw_probabilities_mismatch")
    mask_raw = receipt.get("behavior_action_mask")
    mask = tuple(mask_raw) if isinstance(mask_raw, list | tuple) else ()
    if len(mask) != ACTION_COUNT or any(not isinstance(value, bool) for value in mask):
        reasons.append("behavior_receipt_action_mask_invalid")
    expected_move = _finite(receipt.get("expected_move_bps"))
    cost = _finite(receipt.get("round_trip_cost_bps"))
    if expected_move is None or cost is None or cost < 0.0:
        reasons.append("behavior_receipt_edge_inputs_invalid")
    else:
        expected_mask = _positive_edge_entry_mask(
            expected_move_bps=expected_move,
            round_trip_cost_bps=cost,
        )
        if mask != expected_mask:
            reasons.append("behavior_receipt_action_mask_edge_mismatch")
        if not math.isclose(
            _finite(receipt.get("long_after_cost_bps")) or 0.0,
            expected_move - cost,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            reasons.append("behavior_receipt_long_edge_mismatch")
        if not math.isclose(
            _finite(receipt.get("short_after_cost_bps")) or 0.0,
            -expected_move - cost,
            rel_tol=1e-12,
            abs_tol=1e-12,
        ):
            reasons.append("behavior_receipt_short_edge_mismatch")
        reasons.extend(
            exact_cost_provenance_rejection_reasons(
                receipt.get("cost_provenance"),
                expected_symbol=receipt.get("symbol"),
                expected_round_trip_cost_bps=cost,
                expected_decision_time=receipt.get("decision_time"),
            )
        )
        provenance = receipt.get("cost_provenance")
        provenance_hash = (
            provenance.get("source_payload_sha256")
            if isinstance(provenance, Mapping)
            else None
        )
        if receipt.get("cost_source_payload_sha256") != provenance_hash:
            reasons.append("behavior_receipt_cost_payload_hash_binding_mismatch")
    probabilities: tuple[float, ...] = ()
    if logits and len(mask) == ACTION_COUNT and all(isinstance(value, bool) for value in mask):
        try:
            probabilities = _softmax(logits, mask)
        except ValueError:
            reasons.append("behavior_receipt_masked_distribution_invalid")
    if probabilities and not _sequence_close(receipt.get("action_probabilities"), probabilities):
        reasons.append("behavior_receipt_action_probabilities_mismatch")
    draw = _strict_int(receipt.get("sample_draw_u53"))
    if receipt.get("sample_draw_denominator") != U53_DENOMINATOR:
        reasons.append("behavior_receipt_draw_denominator_mismatch")
    selected_index = _strict_int(receipt.get("selected_action_index"))
    if draw is None or not 0 <= draw < U53_DENOMINATOR:
        reasons.append("behavior_receipt_sample_draw_invalid")
    elif probabilities:
        try:
            recomputed_index = _sample_index(probabilities, draw)
        except ValueError:
            recomputed_index = None
        if selected_index != recomputed_index:
            reasons.append("behavior_receipt_sample_selection_mismatch")
    if selected_index is None or not 0 <= selected_index < ACTION_COUNT:
        reasons.append("behavior_receipt_selected_action_index_invalid")
    else:
        if receipt.get("selected_action") != ACTION_LABELS[selected_index]:
            reasons.append("behavior_receipt_selected_action_identity_mismatch")
        if len(mask) == ACTION_COUNT and mask[selected_index] is not True:
            reasons.append("behavior_receipt_selected_action_masked")
        if probabilities:
            selected_probability = probabilities[selected_index]
            observed_probability = _finite(receipt.get("selected_action_probability"))
            observed_log_probability = _finite(receipt.get("selected_action_log_prob"))
            if observed_probability is None or not math.isclose(
                observed_probability,
                selected_probability,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                reasons.append("behavior_receipt_selected_probability_mismatch")
            if observed_log_probability is None or not math.isclose(
                observed_log_probability,
                math.log(selected_probability),
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                reasons.append("behavior_receipt_selected_log_probability_mismatch")
    if _finite(receipt.get("policy_value")) is None:
        reasons.append("behavior_receipt_policy_value_invalid")
    for field, expected, observed in (
        ("prediction_id", expected_prediction_id, receipt.get("prediction_id")),
        ("symbol", expected_symbol, receipt.get("symbol")),
        ("timeframe", expected_timeframe, receipt.get("timeframe")),
        ("selected_action", expected_action, receipt.get("selected_action")),
        ("checkpoint_id", expected_checkpoint_id, receipt.get("checkpoint_id")),
        (
            "checkpoint_weight_sha256",
            expected_checkpoint_weight_sha256,
            receipt.get("checkpoint_weight_sha256"),
        ),
        (
            "checkpoint_evidence_digest",
            expected_checkpoint_evidence_digest,
            receipt.get("checkpoint_evidence_digest"),
        ),
        ("feature_tensor_id", expected_feature_tensor_id, receipt.get("feature_tensor_id")),
        ("feature_vector_hash", expected_feature_vector_hash, receipt.get("feature_vector_hash")),
        ("served_policy_fingerprint", expected_policy_fingerprint, served_fingerprint),
        (
            "on_policy_sampling_plan_hash",
            expected_sampling_plan_hash,
            receipt.get("on_policy_sampling_plan_hash"),
        ),
        (
            "on_policy_sampling_plan_input_hash",
            expected_sampling_plan_input_hash,
            receipt.get("on_policy_sampling_plan_input_hash"),
        ),
    ):
        if expected not in (None, "") and str(observed) != str(expected):
            reasons.append(f"behavior_receipt_{field}_binding_mismatch")
    if expected_action_index not in (None, ""):
        expected_index = _strict_int(expected_action_index)
        if expected_index is None or selected_index != expected_index:
            reasons.append("behavior_receipt_selected_action_index_binding_mismatch")
    for field, expected, observed in (
        ("feature_cutoff", expected_feature_cutoff, cutoff),
        ("available_at", expected_available_at, available),
        ("decision_time", expected_decision_time, decision),
    ):
        if expected in (None, ""):
            continue
        expected_time = _strict_aware_utc(expected)
        if expected_time is None or observed is None or observed != expected_time:
            reasons.append(f"behavior_receipt_{field}_binding_mismatch")
    return sorted(set(reasons))


def behavior_action_mask_from_row(row: Mapping[str, Any]) -> tuple[bool, ...]:
    """Return the exact PPO mask; non-masked legacy contracts use all actions."""
    contract = str(row.get("behavior_policy_distribution_contract") or "").upper()
    if contract != ON_POLICY_DISTRIBUTION_CONTRACT:
        return tuple(True for _ in range(ACTION_COUNT))
    receipt = row.get("behavior_policy_receipt")
    if behavior_receipt_rejection_reasons(receipt):
        raise ValueError("invalid_behavior_policy_receipt")
    assert isinstance(receipt, Mapping)
    return tuple(bool(value) for value in receipt["behavior_action_mask"])
