"""Neutral contract for adaptive paper-only on-policy sampling plans.

The hybrid trainer produces the plan, while publishers and durable evidence
consumers need to validate it without importing the trainer implementation.
This module therefore depends only on the Python standard library.  It does not
perform inference, write evidence, submit orders, or authorize a live route.

The authenticated envelope deliberately uses a deterministic plan-instance ID
for each ``(process_instance_id, cycle_id)`` pair.  Two different envelopes for
the same cycle consequently collide on the same identity instead of looking
like two legitimate plan instances; a create-or-identical durable store can
then reject the conflict.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

ADAPTIVE_ON_POLICY_LANE_SCHEMA_VERSION = (
    "v2_adaptive_on_policy_paper_lane_plan_v1"
)
ADAPTIVE_ON_POLICY_LANE_FORMULA = (
    "candidate_credit=geometric_mean(policy_entropy,profitability_uncertainty,"
    "positive_edge_quality,paper_margin_headroom)/(1+geometric_mean);"
    "token_budget=floor(carry_in+sum(candidate_credit));"
    "ordinary_lane_reserved_each_multi_candidate_cycle_and_between_single_candidate_samples"
)
U53_DENOMINATOR = 1 << 53
# Version-one plans are bound to the seven-action native policy contract.  This
# is a schema cardinality, not a market threshold.
ADAPTIVE_ON_POLICY_ACTION_COUNT = 7

SAMPLING_PLAN_ENVELOPE_SCHEMA_VERSION = (
    "v2_authenticated_sampling_plan_envelope_v1"
)
SAMPLING_PLAN_INSTANCE_SCHEMA_VERSION = (
    "v2_cycle_unique_sampling_plan_instance_v1"
)
SAMPLING_PLAN_CYCLE_BINDING_SCHEMA_VERSION = (
    "v2_authenticated_sampling_plan_cycle_binding_v1"
)
SAMPLING_PLAN_AUTH_ALGORITHM = "HMAC-SHA256"
SAMPLING_PLAN_AUTH_DOMAIN = "v2/native-trainer/on-policy-sampling-plan/v1"
SAMPLING_PLAN_AUTH_DOMAIN_SEPARATOR = (
    SAMPLING_PLAN_AUTH_DOMAIN.encode("ascii") + b"\0"
)

# These are immutable cryptographic/serialization bounds, not market gates.
MIN_SAMPLING_PLAN_HMAC_KEY_BYTES = 32
MAX_OPAQUE_ID_BYTES = 256

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HMAC_TAG_RE = _SHA256_RE
_SAFE_AUTH_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_.:@/-]{1,128}$")
_SAFE_OPAQUE_ID_RE = re.compile(r"^[!-~]{1,256}$")
_CONTENT_ADDRESSED_CHECKPOINT_ID_RE = re.compile(
    r"^v2_hybrid_ckpt_(?:[0-9a-f]{8}_[0-9a-f]{16}_[0-9a-f]{12}|"
    r"[0-9a-f]{12}_[0-9a-f]{20})$"
)

_PLAN_FIELDS = frozenset(
    {
        "schema_version",
        "formula",
        "input_hash",
        "safety_gate_passed",
        "safety_rejection_reasons",
        "candidate_count",
        "eligible_candidate_count",
        "requested_sample_count",
        "selected_sample_count",
        "selected_indices",
        "ordinary_lane_reserved_count",
        "structural_ordinary_lane_reservation",
        "market_static_sampling_threshold_used",
        "token_budget_before_selection",
        "carry_in",
        "carry_out",
        "single_candidate_ordinary_credit_in",
        "single_candidate_ordinary_credit_out",
        "paper_margin_inputs",
        "paper_entry_freeze_inputs",
        "candidate_audit",
        "paper_only",
        "routes_to_live",
        "places_real_order",
        "plan_hash",
    }
)
_ENVELOPE_FIELDS = frozenset(
    {
        "schema_version",
        "plan_instance_id",
        "cycle_binding_id",
        "cycle_id",
        "process_instance_id",
        "parent_policy_fingerprint",
        "checkpoint_id",
        "checkpoint_weight_sha256",
        "sampling_plan_hash",
        "sampling_plan_input_hash",
        "sampling_plan",
        "selected_index_draws",
        "selected_draw_count",
        "sealed_at",
        "auth_algorithm",
        "auth_key_id",
        "auth_domain",
        "paper_only",
        "routes_to_live",
        "places_real_order",
        "auth_tag",
    }
)
_CANDIDATE_AUDIT_FIELDS = frozenset(
    {
        "adaptive_score",
        "available_at",
        "candidate_token_credit",
        "candle_close_time",
        "candle_closed_confirmed",
        "checkpoint_evidence_digest",
        "checkpoint_evidence_verified",
        "checkpoint_id",
        "checkpoint_identity_verified",
        "checkpoint_weight_sha256",
        "confidence_calibration_fitted",
        "confidence_candidate_action",
        "decision_time",
        "eligible",
        "exact_cost_payload_hash",
        "exact_cost_provenance_valid",
        "expected_move_bps",
        "feature_cutoff",
        "feature_tensor_id",
        "index",
        "paper_margin_headroom",
        "policy_entropy_normalized",
        "positive_after_cost_edge_bps",
        "positive_edge_quality",
        "profitability_confidence_calibrated",
        "profitability_uncertainty",
        "rank_tiebreak_hash",
        "raw_action_logits",
        "raw_policy_logits_hash",
        "rejection_reasons",
        "round_trip_cost_bps",
        "row_classification",
        "served_policy_fingerprint",
        "served_policy_fingerprint_available",
        "symbol",
        "timeframe",
    }
)
_PAPER_MARGIN_INPUT_FIELDS = frozenset(
    {
        "schema_version",
        "generated_utc",
        "status",
        "invariant_holds",
        "margin_base_usd",
        "free_margin_after_buffer_usd",
        "paper_only",
        "routes_to_live",
        "places_real_order",
    }
)
_PAPER_ENTRY_FREEZE_INPUT_FIELDS = frozenset(
    {
        "schema_version",
        "generated_utc",
        "paper_new_entries_halted",
        "new_entries_allowed",
        "paper_only",
        "routes_to_live",
        "places_real_order",
    }
)

_KNOWN_CANDIDATE_REJECTIONS = frozenset(
    {
        "paper_margin_invariant_not_proven",
        "paper_margin_status_not_paper_only",
        "paper_margin_status_live_route_not_false",
        "paper_margin_status_real_order_not_false",
        "paper_margin_base_not_positive",
        "paper_free_margin_after_buffer_not_positive",
        "paper_entry_freeze_not_explicitly_clear",
        "paper_new_entries_not_explicitly_allowed",
        "paper_entry_gate_not_paper_only",
        "paper_entry_gate_live_route_not_false",
        "paper_entry_gate_real_order_not_false",
        "candle_finality_not_proven",
        "strict_utc_lineage_missing",
        "temporal_order_invalid",
        "on_policy_learning_row_not_trainable",
        "served_policy_fingerprint_unavailable",
        "real_checkpoint_generation_unavailable",
        "checkpoint_weight_hash_unavailable",
        "checkpoint_evidence_digest_unavailable",
        "checkpoint_evidence_not_verified",
        "checkpoint_identity_not_verified",
        "symbol_identity_missing",
        "timeframe_identity_missing",
        "exact_adaptive_cost_provenance_unavailable",
        "profitability_calibration_not_fitted",
        "profitability_confidence_invalid",
        "after_cost_edge_inputs_invalid",
        "no_strictly_positive_after_cost_entry_action",
        "raw_policy_distribution_invalid",
        "confidence_candidate_action_invalid",
    }
)


class AdaptiveSamplingPlanContractError(ValueError):
    """Raised when a plan or authenticated envelope fails closed."""


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AdaptiveSamplingPlanContractError(
            "adaptive_sampling_non_canonical_payload"
        ) from exc


def canonical_sha256(payload: Mapping[str, Any]) -> str:
    """Return the repository's canonical mapping SHA-256 representation."""

    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _json_copy(payload: Mapping[str, Any]) -> dict[str, Any]:
    return dict(json.loads(_canonical_bytes(payload)))


def _finite(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _strict_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _strict_aware_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _canonical_utc(value: Any) -> str | None:
    parsed = _strict_aware_utc(value)
    if parsed is None:
        return None
    return parsed.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _safe_opaque_id(value: Any) -> str | None:
    if not isinstance(value, str) or value != value.strip():
        return None
    if len(value.encode("utf-8")) > MAX_OPAQUE_ID_BYTES:
        return None
    return value if _SAFE_OPAQUE_ID_RE.fullmatch(value) else None


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def is_content_addressed_checkpoint_id(value: Any) -> bool:
    """Return whether ``value`` names an immutable native checkpoint."""

    return isinstance(value, str) and bool(
        _CONTENT_ADDRESSED_CHECKPOINT_ID_RE.fullmatch(value)
    )


def _append_once(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _safety_rejection_reasons(plan: Mapping[str, Any]) -> tuple[list[str], float]:
    margin = plan.get("paper_margin_inputs")
    freeze = plan.get("paper_entry_freeze_inputs")
    reasons: list[str] = []
    if not isinstance(margin, Mapping):
        margin = {}
        reasons.append("paper_margin_invariant_not_proven")
    if not isinstance(freeze, Mapping):
        freeze = {}
        reasons.append("paper_entry_freeze_not_explicitly_clear")
    if margin.get("invariant_holds") is not True:
        reasons.append("paper_margin_invariant_not_proven")
    if margin.get("paper_only") is not True:
        reasons.append("paper_margin_status_not_paper_only")
    if margin.get("routes_to_live") is not False:
        reasons.append("paper_margin_status_live_route_not_false")
    if margin.get("places_real_order") is not False:
        reasons.append("paper_margin_status_real_order_not_false")
    margin_base = _finite(margin.get("margin_base_usd"))
    free_after_buffer = _finite(margin.get("free_margin_after_buffer_usd"))
    if margin_base is None or margin_base <= 0.0:
        reasons.append("paper_margin_base_not_positive")
    if free_after_buffer is None or free_after_buffer <= 0.0:
        reasons.append("paper_free_margin_after_buffer_not_positive")
    if freeze.get("paper_new_entries_halted") is not False:
        reasons.append("paper_entry_freeze_not_explicitly_clear")
    if freeze.get("new_entries_allowed") is not True:
        reasons.append("paper_new_entries_not_explicitly_allowed")
    if freeze.get("paper_only") is not True:
        reasons.append("paper_entry_gate_not_paper_only")
    if freeze.get("routes_to_live") is not False:
        reasons.append("paper_entry_gate_live_route_not_false")
    if freeze.get("places_real_order") is not False:
        reasons.append("paper_entry_gate_real_order_not_false")
    unique = sorted(set(reasons))
    margin_headroom = (
        min(1.0, max(0.0, free_after_buffer / margin_base))
        if not unique
        and margin_base is not None
        and free_after_buffer is not None
        else 0.0
    )
    return unique, margin_headroom


def _candidate_identity(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "index": candidate.get("index"),
        "symbol": candidate.get("symbol"),
        "timeframe": candidate.get("timeframe"),
        "feature_tensor_id": candidate.get("feature_tensor_id"),
        "feature_cutoff": candidate.get("feature_cutoff"),
        "available_at": candidate.get("available_at"),
        "candle_close_time": candidate.get("candle_close_time"),
        "candle_closed_confirmed": candidate.get("candle_closed_confirmed"),
        "decision_time": candidate.get("decision_time"),
        "row_classification": candidate.get("row_classification"),
        "confidence_candidate_action": candidate.get(
            "confidence_candidate_action"
        ),
        "served_policy_fingerprint": candidate.get(
            "served_policy_fingerprint"
        ),
        "served_policy_fingerprint_available": candidate.get(
            "served_policy_fingerprint_available"
        ),
        "exact_cost_provenance_valid": candidate.get(
            "exact_cost_provenance_valid"
        ),
        "confidence_calibration_fitted": candidate.get(
            "confidence_calibration_fitted"
        ),
        "raw_action_logits": candidate.get("raw_action_logits"),
        "exact_cost_payload_hash": candidate.get("exact_cost_payload_hash"),
        "checkpoint_id": candidate.get("checkpoint_id"),
        "checkpoint_weight_sha256": candidate.get(
            "checkpoint_weight_sha256"
        ),
        "checkpoint_evidence_digest": candidate.get(
            "checkpoint_evidence_digest"
        ),
        "checkpoint_evidence_verified": candidate.get(
            "checkpoint_evidence_verified"
        ),
        "checkpoint_identity_verified": candidate.get(
            "checkpoint_identity_verified"
        ),
    }


def _raw_distribution_evidence(
    candidate: Mapping[str, Any],
) -> tuple[str, float] | None:
    raw = candidate.get("raw_action_logits")
    if not isinstance(raw, list) or len(raw) != ADAPTIVE_ON_POLICY_ACTION_COUNT:
        return None
    logits: list[float] = []
    for value in raw:
        parsed = _finite(value)
        if parsed is None:
            return None
        logits.append(parsed)
    maximum = max(logits)
    weights = [math.exp(value - maximum) for value in logits]
    total = sum(weights)
    if not math.isfinite(total) or total <= 0.0:
        return None
    probabilities = [weight / total for weight in weights]
    entropy = -sum(
        probability * math.log(probability)
        for probability in probabilities
        if probability > 0.0
    ) / math.log(ADAPTIVE_ON_POLICY_ACTION_COUNT)
    return canonical_sha256({"raw_action_logits": logits}), entropy


def _observable_candidate_rejections(
    candidate: Mapping[str, Any],
    *,
    safety_reasons: list[str],
) -> list[str]:
    reasons = list(safety_reasons)
    cutoff = _strict_aware_utc(candidate.get("feature_cutoff"))
    available = _strict_aware_utc(candidate.get("available_at"))
    candle_close = _strict_aware_utc(candidate.get("candle_close_time"))
    decision = _strict_aware_utc(candidate.get("decision_time"))
    if candidate.get("candle_closed_confirmed") is not True:
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
    if str(candidate.get("row_classification") or "").upper() != "TRAINABLE":
        reasons.append("on_policy_learning_row_not_trainable")
    if candidate.get("served_policy_fingerprint_available") is not True:
        reasons.append("served_policy_fingerprint_unavailable")
    if not _valid_sha256(candidate.get("served_policy_fingerprint")):
        reasons.append("served_policy_fingerprint_unavailable")
    if not is_content_addressed_checkpoint_id(candidate.get("checkpoint_id")):
        reasons.append("real_checkpoint_generation_unavailable")
    if not _valid_sha256(candidate.get("checkpoint_weight_sha256")):
        reasons.append("checkpoint_weight_hash_unavailable")
    if not _valid_sha256(candidate.get("checkpoint_evidence_digest")):
        reasons.append("checkpoint_evidence_digest_unavailable")
    if candidate.get("checkpoint_evidence_verified") is not True:
        reasons.append("checkpoint_evidence_not_verified")
    if candidate.get("checkpoint_identity_verified") is not True:
        reasons.append("checkpoint_identity_not_verified")
    if not str(candidate.get("symbol") or "").strip():
        reasons.append("symbol_identity_missing")
    if not str(candidate.get("timeframe") or "").strip():
        reasons.append("timeframe_identity_missing")
    if not _valid_sha256(candidate.get("exact_cost_payload_hash")):
        reasons.append("exact_adaptive_cost_provenance_unavailable")
    if candidate.get("exact_cost_provenance_valid") is not True:
        reasons.append("exact_adaptive_cost_provenance_unavailable")
    if candidate.get("confidence_calibration_fitted") is not True:
        reasons.append("profitability_calibration_not_fitted")
    confidence = _finite(candidate.get("profitability_confidence_calibrated"))
    if confidence is None or not 0.0 <= confidence <= 1.0:
        reasons.append("profitability_confidence_invalid")
    expected_move = _finite(candidate.get("expected_move_bps"))
    cost = _finite(candidate.get("round_trip_cost_bps"))
    if expected_move is None or cost is None or cost < 0.0:
        reasons.append("after_cost_edge_inputs_invalid")
        expected_confidence_action = None
    else:
        long_edge = expected_move - cost
        short_edge = -expected_move - cost
        if max(long_edge, short_edge) <= 0.0:
            reasons.append("no_strictly_positive_after_cost_entry_action")
            expected_confidence_action = None
        else:
            expected_confidence_action = (
                "long" if long_edge >= short_edge else "short"
            )
    if candidate.get("confidence_candidate_action") != expected_confidence_action:
        reasons.append("confidence_candidate_action_invalid")
    if _raw_distribution_evidence(candidate) is None:
        reasons.append("raw_policy_distribution_invalid")
    return sorted(set(reasons))


def adaptive_on_policy_lane_plan_rejection_reasons(
    plan: Mapping[str, Any] | None,
) -> list[str]:
    """Recompute all adaptive-plan semantics supported by sealed evidence."""

    if not isinstance(plan, Mapping):
        return ["adaptive_sampling_plan_missing"]
    reasons: list[str] = []
    try:
        row = _json_copy(plan)
    except AdaptiveSamplingPlanContractError:
        return ["adaptive_sampling_plan_not_canonical"]
    if set(row) != _PLAN_FIELDS:
        _append_once(reasons, "adaptive_sampling_plan_shape_invalid")
    supplied_plan_hash = str(row.pop("plan_hash", ""))
    try:
        observed_plan_hash = canonical_sha256(row)
    except AdaptiveSamplingPlanContractError:
        observed_plan_hash = ""
    if not _valid_sha256(supplied_plan_hash) or observed_plan_hash != supplied_plan_hash:
        _append_once(reasons, "adaptive_sampling_plan_hash_invalid")
    if row.get("schema_version") != ADAPTIVE_ON_POLICY_LANE_SCHEMA_VERSION:
        _append_once(reasons, "adaptive_sampling_plan_schema_invalid")
    if row.get("formula") != ADAPTIVE_ON_POLICY_LANE_FORMULA:
        _append_once(reasons, "adaptive_sampling_plan_formula_invalid")
    if (
        row.get("paper_only") is not True
        or row.get("routes_to_live") is not False
        or row.get("places_real_order") is not False
    ):
        _append_once(reasons, "adaptive_sampling_plan_paper_safety_invalid")
    if row.get("market_static_sampling_threshold_used") is not False:
        _append_once(
            reasons, "adaptive_sampling_plan_static_market_threshold_invalid"
        )
    if row.get("structural_ordinary_lane_reservation") is not True:
        _append_once(
            reasons, "adaptive_sampling_plan_ordinary_reservation_invalid"
        )

    audit = row.get("candidate_audit")
    selected = row.get("selected_indices")
    candidate_count = _strict_int(row.get("candidate_count"))
    selected_count = _strict_int(row.get("selected_sample_count"))
    if (
        not isinstance(audit, list)
        or candidate_count is None
        or candidate_count < 0
        or len(audit) != candidate_count
    ):
        _append_once(reasons, "adaptive_sampling_plan_candidate_count_invalid")
        audit = []
        candidate_count = 0
    if (
        not isinstance(selected, list)
        or any(_strict_int(value) is None for value in selected)
        or selected != sorted(set(selected))
        or any(value < 0 or value >= candidate_count for value in selected)
        or selected_count != len(selected)
    ):
        _append_once(reasons, "adaptive_sampling_plan_selection_shape_invalid")
        selected = []

    input_material = {
        "schema_version": row.get("schema_version"),
        "formula": row.get("formula"),
        "carry_in": row.get("carry_in"),
        "single_candidate_ordinary_credit_in": row.get(
            "single_candidate_ordinary_credit_in"
        ),
        "paper_margin_inputs": row.get("paper_margin_inputs"),
        "paper_entry_freeze_inputs": row.get("paper_entry_freeze_inputs"),
        "candidate_audit": audit,
    }
    supplied_input_hash = row.get("input_hash")
    try:
        observed_input_hash = canonical_sha256(input_material)
    except AdaptiveSamplingPlanContractError:
        observed_input_hash = ""
    if not _valid_sha256(supplied_input_hash) or observed_input_hash != supplied_input_hash:
        _append_once(reasons, "adaptive_sampling_plan_input_hash_invalid")

    computed_safety_reasons, expected_margin_headroom = _safety_rejection_reasons(row)
    margin_inputs = row.get("paper_margin_inputs")
    freeze_inputs = row.get("paper_entry_freeze_inputs")
    if (
        not isinstance(margin_inputs, Mapping)
        or set(margin_inputs) != _PAPER_MARGIN_INPUT_FIELDS
        or not isinstance(freeze_inputs, Mapping)
        or set(freeze_inputs) != _PAPER_ENTRY_FREEZE_INPUT_FIELDS
    ):
        _append_once(reasons, "adaptive_sampling_plan_safety_input_shape_invalid")
    supplied_safety_reasons = row.get("safety_rejection_reasons")
    if (
        not isinstance(supplied_safety_reasons, list)
        or any(not isinstance(reason, str) for reason in supplied_safety_reasons)
        or supplied_safety_reasons != sorted(set(supplied_safety_reasons))
        or supplied_safety_reasons != computed_safety_reasons
    ):
        _append_once(reasons, "adaptive_sampling_plan_safety_reasons_invalid")
    if row.get("safety_gate_passed") is not (not computed_safety_reasons):
        _append_once(reasons, "adaptive_sampling_plan_safety_gate_inconsistent")

    eligible: list[Mapping[str, Any]] = []
    total_credit = 0.0
    for expected_index, candidate in enumerate(audit):
        if (
            not isinstance(candidate, Mapping)
            or _strict_int(candidate.get("index")) != expected_index
        ):
            _append_once(reasons, "adaptive_sampling_plan_candidate_identity_invalid")
            continue
        if set(candidate) != _CANDIDATE_AUDIT_FIELDS:
            _append_once(reasons, "adaptive_sampling_plan_candidate_shape_invalid")
        candidate_rejections = candidate.get("rejection_reasons")
        if (
            not isinstance(candidate_rejections, list)
            or any(not isinstance(reason, str) for reason in candidate_rejections)
            or candidate_rejections != sorted(set(candidate_rejections))
            or any(
                reason not in _KNOWN_CANDIDATE_REJECTIONS
                for reason in candidate_rejections
            )
        ):
            _append_once(
                reasons, "adaptive_sampling_plan_candidate_rejections_invalid"
            )
            candidate_rejections = []
        observable_rejections = _observable_candidate_rejections(
            candidate,
            safety_reasons=computed_safety_reasons,
        )
        if candidate_rejections != observable_rejections:
            _append_once(
                reasons, "adaptive_sampling_plan_candidate_rejections_mismatch"
            )
        eligible_value = candidate.get("eligible")
        eligible_flag = eligible_value is True
        if not isinstance(eligible_value, bool) or eligible_flag != (
            not candidate_rejections
        ):
            _append_once(
                reasons, "adaptive_sampling_plan_candidate_eligibility_inconsistent"
            )
        identity = _candidate_identity(candidate)
        if canonical_sha256(identity) != candidate.get("rank_tiebreak_hash"):
            _append_once(
                reasons, "adaptive_sampling_plan_candidate_rank_hash_invalid"
            )

        entropy = _finite(candidate.get("policy_entropy_normalized"))
        uncertainty = _finite(candidate.get("profitability_uncertainty"))
        confidence = _finite(
            candidate.get("profitability_confidence_calibrated")
        )
        edge_quality = _finite(candidate.get("positive_edge_quality"))
        margin_headroom = _finite(candidate.get("paper_margin_headroom"))
        positive_edge = _finite(candidate.get("positive_after_cost_edge_bps"))
        expected_move = _finite(candidate.get("expected_move_bps"))
        cost = _finite(candidate.get("round_trip_cost_bps"))
        observed_score = _finite(candidate.get("adaptive_score"))
        observed_credit = _finite(candidate.get("candidate_token_credit"))
        raw_distribution = _raw_distribution_evidence(candidate)
        if raw_distribution is None:
            expected_logits_hash = None
            expected_entropy = 0.0
        else:
            expected_logits_hash, expected_entropy = raw_distribution
        components = (entropy, uncertainty, edge_quality, margin_headroom)
        if any(value is None or not 0.0 <= value <= 1.0 for value in components):
            _append_once(
                reasons, "adaptive_sampling_plan_candidate_components_invalid"
            )
            continue
        assert entropy is not None and uncertainty is not None
        assert edge_quality is not None and margin_headroom is not None
        expected_uncertainty = (
            1.0 - abs((2.0 * confidence) - 1.0)
            if confidence is not None and 0.0 <= confidence <= 1.0
            else 0.0
        )
        expected_positive_edge = (
            max(0.0, expected_move - cost, -expected_move - cost)
            if expected_move is not None and cost is not None and cost >= 0.0
            else 0.0
        )
        expected_edge_quality = (
            expected_positive_edge / (expected_positive_edge + abs(cost))
            if expected_positive_edge > 0.0
            and cost is not None
            and expected_positive_edge + abs(cost) > 0.0
            else 0.0
        )
        if (
            candidate.get("raw_policy_logits_hash") != expected_logits_hash
            or not math.isclose(
                entropy, expected_entropy, rel_tol=1e-12, abs_tol=1e-12
            )
            or (
                eligible_flag
                and (
                    candidate.get("served_policy_fingerprint_available") is not True
                    or candidate.get("exact_cost_provenance_valid") is not True
                    or candidate.get("confidence_calibration_fitted") is not True
                    or raw_distribution is None
                )
            )
        ):
            _append_once(
                reasons, "adaptive_sampling_plan_candidate_distribution_invalid"
            )
        if (
            positive_edge is None
            or not math.isclose(
                positive_edge, expected_positive_edge, rel_tol=1e-12, abs_tol=1e-12
            )
            or not math.isclose(
                uncertainty, expected_uncertainty, rel_tol=1e-12, abs_tol=1e-12
            )
            or not math.isclose(
                edge_quality, expected_edge_quality, rel_tol=1e-12, abs_tol=1e-12
            )
            or not math.isclose(
                margin_headroom,
                expected_margin_headroom,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ):
            _append_once(
                reasons, "adaptive_sampling_plan_candidate_components_invalid"
            )
        expected_score = (
            max(0.0, entropy * uncertainty * edge_quality * margin_headroom)
            ** 0.25
            if eligible_flag
            else 0.0
        )
        expected_credit = (
            expected_score / (1.0 + expected_score)
            if expected_score > 0.0
            else 0.0
        )
        if (
            observed_score is None
            or observed_credit is None
            or not math.isclose(
                observed_score, expected_score, rel_tol=1e-12, abs_tol=1e-12
            )
            or not math.isclose(
                observed_credit, expected_credit, rel_tol=1e-12, abs_tol=1e-12
            )
        ):
            _append_once(reasons, "adaptive_sampling_plan_candidate_score_invalid")
        if eligible_flag:
            eligible.append(candidate)
            total_credit += expected_credit

    eligible_count = _strict_int(row.get("eligible_candidate_count"))
    if eligible_count != len(eligible):
        _append_once(reasons, "adaptive_sampling_plan_eligible_count_invalid")
    carry = _finite(row.get("carry_in"))
    ordinary_credit = _strict_int(row.get("single_candidate_ordinary_credit_in"))
    if (
        carry is None
        or not 0.0 <= carry <= 1.0
        or ordinary_credit is None
        or ordinary_credit < 0
    ):
        _append_once(reasons, "adaptive_sampling_plan_carry_invalid")
        carry = 0.0
        ordinary_credit = 0
    token_budget = carry + total_credit
    requested_count = int(math.floor(token_budget))
    if candidate_count <= 0:
        max_sampled = 0
    elif candidate_count == 1:
        max_sampled = 1 if ordinary_credit >= 1 else 0
    else:
        max_sampled = max(0, candidate_count - 1)
    expected_selected_count = min(requested_count, len(eligible), max_sampled)
    ranked = sorted(
        eligible,
        key=lambda candidate: (
            -float(_finite(candidate.get("adaptive_score")) or 0.0),
            str(candidate["rank_tiebreak_hash"]),
        ),
    )
    expected_selected = sorted(
        int(candidate["index"])
        for candidate in ranked[:expected_selected_count]
    )
    if selected != expected_selected:
        _append_once(reasons, "adaptive_sampling_plan_selection_semantics_invalid")
    observed_budget = _finite(row.get("token_budget_before_selection"))
    observed_carry_out = _finite(row.get("carry_out"))
    expected_carry_out = min(
        1.0, max(0.0, token_budget - expected_selected_count)
    )
    if (
        _strict_int(row.get("requested_sample_count")) != requested_count
        or observed_budget is None
        or not math.isclose(
            observed_budget, token_budget, rel_tol=1e-12, abs_tol=1e-12
        )
        or observed_carry_out is None
        or not math.isclose(
            observed_carry_out,
            expected_carry_out,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        or _strict_int(row.get("ordinary_lane_reserved_count"))
        != candidate_count - expected_selected_count
    ):
        _append_once(reasons, "adaptive_sampling_plan_budget_semantics_invalid")
    expected_ordinary_credit_out = (
        0
        if candidate_count == 1 and expected_selected_count
        else ordinary_credit + 1
        if candidate_count == 1
        else ordinary_credit
    )
    if (
        _strict_int(row.get("single_candidate_ordinary_credit_out"))
        != expected_ordinary_credit_out
    ):
        _append_once(reasons, "adaptive_sampling_plan_ordinary_credit_invalid")
    return sorted(reasons)


def validated_adaptive_on_policy_lane_plan(
    plan: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return a detached plan copy or raise with all deterministic reasons."""

    reasons = adaptive_on_policy_lane_plan_rejection_reasons(plan)
    if reasons:
        raise AdaptiveSamplingPlanContractError(
            "adaptive_sampling_plan_invalid:" + ",".join(reasons)
        )
    assert isinstance(plan, Mapping)
    return _json_copy(plan)


def sampling_plan_instance_id(*, cycle_id: str, process_instance_id: str) -> str:
    """Return the one canonical plan-instance identity for a process cycle."""

    cycle = _safe_opaque_id(cycle_id)
    process = _safe_opaque_id(process_instance_id)
    if cycle is None:
        raise AdaptiveSamplingPlanContractError("sampling_plan_cycle_id_invalid")
    if process is None:
        raise AdaptiveSamplingPlanContractError(
            "sampling_plan_process_instance_id_invalid"
        )
    return canonical_sha256(
        {
            "schema_version": SAMPLING_PLAN_INSTANCE_SCHEMA_VERSION,
            "cycle_id": cycle,
            "process_instance_id": process,
        }
    )


def _validated_hmac_key(hmac_key: Any) -> bytes:
    if not isinstance(hmac_key, bytes | bytearray | memoryview):
        raise AdaptiveSamplingPlanContractError(
            "sampling_plan_hmac_key_must_be_bytes"
        )
    key = bytes(hmac_key)
    if len(key) < MIN_SAMPLING_PLAN_HMAC_KEY_BYTES:
        raise AdaptiveSamplingPlanContractError("sampling_plan_hmac_key_too_short")
    return key


def _validated_draws(
    selected_index_draws: Mapping[int, int] | Any,
    *,
    selected_indices: list[int],
) -> list[dict[str, int]]:
    if not isinstance(selected_index_draws, Mapping):
        raise AdaptiveSamplingPlanContractError(
            "sampling_plan_selected_draws_invalid"
        )
    normalized: dict[int, int] = {}
    for index, draw in selected_index_draws.items():
        if _strict_int(index) is None or _strict_int(draw) is None:
            raise AdaptiveSamplingPlanContractError(
                "sampling_plan_selected_draws_invalid"
            )
        if index in normalized or not 0 <= draw < U53_DENOMINATOR:
            raise AdaptiveSamplingPlanContractError(
                "sampling_plan_selected_draws_invalid"
            )
        normalized[index] = draw
    if sorted(normalized) != selected_indices:
        raise AdaptiveSamplingPlanContractError(
            "sampling_plan_selected_draw_set_incomplete"
        )
    return [
        {
            "selected_index": index,
            "draw_u53": normalized[index],
            "draw_denominator": U53_DENOMINATOR,
        }
        for index in selected_indices
    ]


def _draw_records_rejection_reasons(
    records: Any,
    *,
    selected_indices: list[int],
    selected_draw_count: Any,
) -> list[str]:
    if not isinstance(records, list):
        return ["sampling_plan_selected_draws_invalid"]
    indices: list[int] = []
    for record in records:
        if not isinstance(record, Mapping) or set(record) != {
            "selected_index",
            "draw_u53",
            "draw_denominator",
        }:
            return ["sampling_plan_selected_draws_invalid"]
        index = _strict_int(record.get("selected_index"))
        draw = _strict_int(record.get("draw_u53"))
        if (
            index is None
            or draw is None
            or not 0 <= draw < U53_DENOMINATOR
            or record.get("draw_denominator") != U53_DENOMINATOR
        ):
            return ["sampling_plan_selected_draws_invalid"]
        indices.append(index)
    reasons: list[str] = []
    if indices != selected_indices or indices != sorted(set(indices)):
        reasons.append("sampling_plan_selected_draw_set_incomplete")
    if _strict_int(selected_draw_count) != len(records):
        reasons.append("sampling_plan_selected_draw_count_invalid")
    return reasons


def _plan_clock_rejection_reasons(
    plan: Mapping[str, Any], *, sealed_at: Any
) -> list[str]:
    sealed_canonical = _canonical_utc(sealed_at)
    if sealed_canonical is None or sealed_at != sealed_canonical:
        return ["sampling_plan_sealed_at_invalid"]
    sealed_time = _strict_aware_utc(sealed_canonical)
    assert sealed_time is not None
    causal_clocks: list[datetime] = []
    for candidate in plan.get("candidate_audit", []):
        if not isinstance(candidate, Mapping):
            return ["sampling_plan_candidate_clock_invalid"]
        decision_time = _strict_aware_utc(candidate.get("decision_time"))
        if decision_time is None:
            return ["sampling_plan_candidate_clock_invalid"]
        causal_clocks.append(decision_time)
    for inputs_field in ("paper_margin_inputs", "paper_entry_freeze_inputs"):
        inputs = plan.get(inputs_field)
        if not isinstance(inputs, Mapping):
            return ["sampling_plan_safety_clock_invalid"]
        generated = inputs.get("generated_utc")
        if generated not in (None, ""):
            generated_time = _strict_aware_utc(generated)
            if generated_time is None:
                return ["sampling_plan_safety_clock_invalid"]
            causal_clocks.append(generated_time)
    if causal_clocks and sealed_time < max(causal_clocks):
        return ["sampling_plan_sealed_before_inputs"]
    return []


def _cycle_binding_id(material: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            "schema_version": SAMPLING_PLAN_CYCLE_BINDING_SCHEMA_VERSION,
            **dict(material),
        }
    )


def build_authenticated_sampling_plan_envelope(
    *,
    sampling_plan: Mapping[str, Any],
    cycle_id: str,
    process_instance_id: str,
    parent_policy_fingerprint: str,
    checkpoint_id: str,
    checkpoint_weight_sha256: str,
    selected_index_draws: Mapping[int, int],
    sealed_at: str,
    auth_key_id: str,
    hmac_key: bytes | bytearray | memoryview,
) -> dict[str, Any]:
    """Validate and authenticate one complete paper sampling-plan commitment."""

    plan = validated_adaptive_on_policy_lane_plan(sampling_plan)
    cycle = _safe_opaque_id(cycle_id)
    process = _safe_opaque_id(process_instance_id)
    if cycle is None:
        raise AdaptiveSamplingPlanContractError("sampling_plan_cycle_id_invalid")
    if process is None:
        raise AdaptiveSamplingPlanContractError(
            "sampling_plan_process_instance_id_invalid"
        )
    if not _valid_sha256(parent_policy_fingerprint):
        raise AdaptiveSamplingPlanContractError(
            "sampling_plan_parent_policy_fingerprint_invalid"
        )
    if not is_content_addressed_checkpoint_id(checkpoint_id):
        raise AdaptiveSamplingPlanContractError(
            "sampling_plan_checkpoint_id_invalid"
        )
    if not _valid_sha256(checkpoint_weight_sha256):
        raise AdaptiveSamplingPlanContractError(
            "sampling_plan_checkpoint_hash_invalid"
        )
    if not isinstance(auth_key_id, str) or not _SAFE_AUTH_KEY_ID_RE.fullmatch(
        auth_key_id
    ):
        raise AdaptiveSamplingPlanContractError(
            "sampling_plan_auth_key_id_invalid"
        )
    key = _validated_hmac_key(hmac_key)
    selected_indices = list(plan["selected_indices"])
    for selected_index in selected_indices:
        candidate = plan["candidate_audit"][selected_index]
        if (
            candidate.get("checkpoint_id") != checkpoint_id
            or candidate.get("checkpoint_weight_sha256")
            != checkpoint_weight_sha256
        ):
            raise AdaptiveSamplingPlanContractError(
                "sampling_plan_checkpoint_binding_mismatch"
            )
        if (
            candidate.get("served_policy_fingerprint_available") is not True
            or candidate.get("served_policy_fingerprint")
            != parent_policy_fingerprint
            or candidate.get("exact_cost_provenance_valid") is not True
            or candidate.get("confidence_calibration_fitted") is not True
            or _raw_distribution_evidence(candidate) is None
        ):
            raise AdaptiveSamplingPlanContractError(
                "sampling_plan_selected_candidate_evidence_invalid"
            )
    draws = _validated_draws(
        selected_index_draws,
        selected_indices=selected_indices,
    )
    canonical_sealed_at = _canonical_utc(sealed_at)
    if canonical_sealed_at is None:
        raise AdaptiveSamplingPlanContractError("sampling_plan_sealed_at_invalid")
    clock_reasons = _plan_clock_rejection_reasons(
        plan, sealed_at=canonical_sealed_at
    )
    if clock_reasons:
        raise AdaptiveSamplingPlanContractError(clock_reasons[0])
    plan_instance = sampling_plan_instance_id(
        cycle_id=cycle,
        process_instance_id=process,
    )
    binding_material = {
        "plan_instance_id": plan_instance,
        "cycle_id": cycle,
        "process_instance_id": process,
        "parent_policy_fingerprint": parent_policy_fingerprint,
        "checkpoint_id": checkpoint_id,
        "checkpoint_weight_sha256": checkpoint_weight_sha256,
        "sampling_plan_hash": plan["plan_hash"],
        "sampling_plan_input_hash": plan["input_hash"],
        "selected_index_draws": draws,
    }
    cycle_binding = _cycle_binding_id(binding_material)
    material: dict[str, Any] = {
        "schema_version": SAMPLING_PLAN_ENVELOPE_SCHEMA_VERSION,
        "plan_instance_id": plan_instance,
        "cycle_binding_id": cycle_binding,
        "cycle_id": cycle,
        "process_instance_id": process,
        "parent_policy_fingerprint": parent_policy_fingerprint,
        "checkpoint_id": checkpoint_id,
        "checkpoint_weight_sha256": checkpoint_weight_sha256,
        "sampling_plan_hash": plan["plan_hash"],
        "sampling_plan_input_hash": plan["input_hash"],
        "sampling_plan": plan,
        "selected_index_draws": draws,
        "selected_draw_count": len(draws),
        "sealed_at": canonical_sealed_at,
        "auth_algorithm": SAMPLING_PLAN_AUTH_ALGORITHM,
        "auth_key_id": auth_key_id,
        "auth_domain": SAMPLING_PLAN_AUTH_DOMAIN,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    tag = hmac.new(
        key,
        SAMPLING_PLAN_AUTH_DOMAIN_SEPARATOR + _canonical_bytes(material),
        hashlib.sha256,
    ).hexdigest()
    return {**material, "auth_tag": tag}


def authenticated_sampling_plan_envelope_rejection_reasons(
    envelope: Mapping[str, Any] | None,
    *,
    hmac_key: bytes | bytearray | memoryview,
    expected_cycle_id: str | None = None,
    expected_process_instance_id: str | None = None,
    expected_parent_policy_fingerprint: str | None = None,
    expected_checkpoint_id: str | None = None,
    expected_checkpoint_weight_sha256: str | None = None,
    expected_auth_key_id: str | None = None,
    expected_plan_instance_id: str | None = None,
) -> list[str]:
    """Verify authentication, semantics, exact draws, clocks, and bindings."""

    if not isinstance(envelope, Mapping):
        return ["sampling_plan_envelope_missing"]
    try:
        key = _validated_hmac_key(hmac_key)
    except AdaptiveSamplingPlanContractError as exc:
        return [str(exc)]
    try:
        row = _json_copy(envelope)
    except AdaptiveSamplingPlanContractError:
        return ["sampling_plan_envelope_not_canonical"]
    reasons: list[str] = []
    if set(row) != _ENVELOPE_FIELDS:
        _append_once(reasons, "sampling_plan_envelope_shape_invalid")
    supplied_tag = str(row.pop("auth_tag", ""))
    expected_tag = hmac.new(
        key,
        SAMPLING_PLAN_AUTH_DOMAIN_SEPARATOR + _canonical_bytes(row),
        hashlib.sha256,
    ).hexdigest()
    # compare_digest is required even for a malformed tag so comparison of a
    # supplied 64-hex value never falls back to normal string equality.
    tag_matches = hmac.compare_digest(expected_tag, supplied_tag)
    if not _HMAC_TAG_RE.fullmatch(supplied_tag) or not tag_matches:
        _append_once(reasons, "sampling_plan_envelope_authentication_invalid")
    if row.get("schema_version") != SAMPLING_PLAN_ENVELOPE_SCHEMA_VERSION:
        _append_once(reasons, "sampling_plan_envelope_schema_invalid")
    if (
        row.get("auth_algorithm") != SAMPLING_PLAN_AUTH_ALGORITHM
        or row.get("auth_domain") != SAMPLING_PLAN_AUTH_DOMAIN
        or not isinstance(row.get("auth_key_id"), str)
        or not _SAFE_AUTH_KEY_ID_RE.fullmatch(row["auth_key_id"])
    ):
        _append_once(reasons, "sampling_plan_envelope_auth_metadata_invalid")
    if (
        row.get("paper_only") is not True
        or row.get("routes_to_live") is not False
        or row.get("places_real_order") is not False
    ):
        _append_once(reasons, "sampling_plan_envelope_paper_safety_invalid")

    cycle = _safe_opaque_id(row.get("cycle_id"))
    process = _safe_opaque_id(row.get("process_instance_id"))
    if cycle is None or process is None:
        _append_once(reasons, "sampling_plan_envelope_cycle_identity_invalid")
        canonical_instance = None
    else:
        canonical_instance = sampling_plan_instance_id(
            cycle_id=cycle,
            process_instance_id=process,
        )
        if row.get("plan_instance_id") != canonical_instance:
            _append_once(reasons, "sampling_plan_envelope_instance_id_invalid")
    if not _valid_sha256(row.get("parent_policy_fingerprint")):
        _append_once(reasons, "sampling_plan_parent_policy_fingerprint_invalid")
    if not is_content_addressed_checkpoint_id(row.get("checkpoint_id")):
        _append_once(reasons, "sampling_plan_checkpoint_id_invalid")
    if not _valid_sha256(row.get("checkpoint_weight_sha256")):
        _append_once(reasons, "sampling_plan_checkpoint_hash_invalid")

    plan_raw = row.get("sampling_plan")
    plan_reasons = adaptive_on_policy_lane_plan_rejection_reasons(
        plan_raw if isinstance(plan_raw, Mapping) else None
    )
    if plan_reasons:
        _append_once(reasons, "sampling_plan_envelope_plan_invalid")
        plan: Mapping[str, Any] = {}
        selected_indices: list[int] = []
    else:
        assert isinstance(plan_raw, Mapping)
        plan = plan_raw
        selected_indices = list(plan["selected_indices"])
        if (
            row.get("sampling_plan_hash") != plan.get("plan_hash")
            or row.get("sampling_plan_input_hash") != plan.get("input_hash")
        ):
            _append_once(reasons, "sampling_plan_envelope_plan_binding_invalid")
        for selected_index in selected_indices:
            candidate = plan["candidate_audit"][selected_index]
            if (
                candidate.get("checkpoint_id") != row.get("checkpoint_id")
                or candidate.get("checkpoint_weight_sha256")
                != row.get("checkpoint_weight_sha256")
            ):
                _append_once(
                    reasons, "sampling_plan_checkpoint_binding_mismatch"
                )
            if (
                candidate.get("served_policy_fingerprint_available") is not True
                or candidate.get("served_policy_fingerprint")
                != row.get("parent_policy_fingerprint")
                or candidate.get("exact_cost_provenance_valid") is not True
                or candidate.get("confidence_calibration_fitted") is not True
                or _raw_distribution_evidence(candidate) is None
            ):
                _append_once(
                    reasons,
                    "sampling_plan_selected_candidate_evidence_invalid",
                )
    for draw_reason in _draw_records_rejection_reasons(
        row.get("selected_index_draws"),
        selected_indices=selected_indices,
        selected_draw_count=row.get("selected_draw_count"),
    ):
        _append_once(reasons, draw_reason)
    for clock_reason in _plan_clock_rejection_reasons(
        plan, sealed_at=row.get("sealed_at")
    ):
        _append_once(reasons, clock_reason)

    if canonical_instance is not None:
        binding_material = {
            "plan_instance_id": canonical_instance,
            "cycle_id": cycle,
            "process_instance_id": process,
            "parent_policy_fingerprint": row.get("parent_policy_fingerprint"),
            "checkpoint_id": row.get("checkpoint_id"),
            "checkpoint_weight_sha256": row.get("checkpoint_weight_sha256"),
            "sampling_plan_hash": row.get("sampling_plan_hash"),
            "sampling_plan_input_hash": row.get("sampling_plan_input_hash"),
            "selected_index_draws": row.get("selected_index_draws"),
        }
        if row.get("cycle_binding_id") != _cycle_binding_id(binding_material):
            _append_once(reasons, "sampling_plan_envelope_cycle_binding_invalid")

    expected_bindings = (
        ("cycle_id", expected_cycle_id),
        ("process_instance_id", expected_process_instance_id),
        ("parent_policy_fingerprint", expected_parent_policy_fingerprint),
        ("checkpoint_id", expected_checkpoint_id),
        ("checkpoint_weight_sha256", expected_checkpoint_weight_sha256),
        ("auth_key_id", expected_auth_key_id),
        ("plan_instance_id", expected_plan_instance_id),
    )
    for field, expected in expected_bindings:
        if expected is not None and row.get(field) != expected:
            _append_once(reasons, f"sampling_plan_envelope_expected_{field}_mismatch")
    return sorted(reasons)


def verify_authenticated_sampling_plan_envelope(
    envelope: Mapping[str, Any] | None,
    *,
    hmac_key: bytes | bytearray | memoryview,
    expected_cycle_id: str | None = None,
    expected_process_instance_id: str | None = None,
    expected_parent_policy_fingerprint: str | None = None,
    expected_checkpoint_id: str | None = None,
    expected_checkpoint_weight_sha256: str | None = None,
    expected_auth_key_id: str | None = None,
    expected_plan_instance_id: str | None = None,
) -> dict[str, Any]:
    """Return a detached verified envelope or raise a fail-closed error."""

    reasons = authenticated_sampling_plan_envelope_rejection_reasons(
        envelope,
        hmac_key=hmac_key,
        expected_cycle_id=expected_cycle_id,
        expected_process_instance_id=expected_process_instance_id,
        expected_parent_policy_fingerprint=expected_parent_policy_fingerprint,
        expected_checkpoint_id=expected_checkpoint_id,
        expected_checkpoint_weight_sha256=expected_checkpoint_weight_sha256,
        expected_auth_key_id=expected_auth_key_id,
        expected_plan_instance_id=expected_plan_instance_id,
    )
    if reasons:
        raise AdaptiveSamplingPlanContractError(
            "authenticated_sampling_plan_envelope_invalid:" + ",".join(reasons)
        )
    assert isinstance(envelope, Mapping)
    return _json_copy(envelope)


__all__ = (
    "ADAPTIVE_ON_POLICY_LANE_FORMULA",
    "ADAPTIVE_ON_POLICY_LANE_SCHEMA_VERSION",
    "ADAPTIVE_ON_POLICY_ACTION_COUNT",
    "AdaptiveSamplingPlanContractError",
    "MIN_SAMPLING_PLAN_HMAC_KEY_BYTES",
    "SAMPLING_PLAN_AUTH_ALGORITHM",
    "SAMPLING_PLAN_AUTH_DOMAIN",
    "SAMPLING_PLAN_AUTH_DOMAIN_SEPARATOR",
    "SAMPLING_PLAN_ENVELOPE_SCHEMA_VERSION",
    "U53_DENOMINATOR",
    "adaptive_on_policy_lane_plan_rejection_reasons",
    "authenticated_sampling_plan_envelope_rejection_reasons",
    "build_authenticated_sampling_plan_envelope",
    "canonical_sha256",
    "is_content_addressed_checkpoint_id",
    "sampling_plan_instance_id",
    "validated_adaptive_on_policy_lane_plan",
    "verify_authenticated_sampling_plan_envelope",
)
