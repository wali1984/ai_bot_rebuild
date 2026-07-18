from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import IntegrityThresholds
from .scoring import score_market_state


TRAINING_MISSING_MASK_TOLERATED_REASONS = {
    "MISSING_CRITICAL_FEATURE_FAMILY",
    "MARKET_STATE_INTEGRITY_SCORE_BELOW_TRAINING_MIN",
}

TRAINING_MISSING_MASK_HARD_REJECT_REASONS = {
    "AVAILABLE_AT_AFTER_DECISION_TIME",
    "BACKFILLED_NOT_AVAILABLE_AT_DECISION_TIME",
    "CANDLE_COMPLETION_UNKNOWN",
    "FEATURE_CUTOFF_AFTER_DECISION_TIME",
    "STALE_FEATURE_FAMILY",
    "UNCLOSED_CANDLE",
    "candle_closed_confirmed_missing",
    "candle_not_closed_confirmed",
    "decision_cutoff_time_missing",
    "feature_timestamp_after_decision_cutoff",
    "source_available_after_decision_cutoff",
    "source_event_time_missing",
}

CORE_PRICE_MISSING_NAMES = {
    "critical_family_absent:ohlcv_core",
    "open",
    "high",
    "low",
    "close",
    "ohlcv_open",
    "ohlcv_high",
    "ohlcv_low",
    "ohlcv_close",
}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    if isinstance(value, Mapping):
        return [name for name, flagged in value.items() if flagged]
    if value in (None, ""):
        return []
    return [value]


def missing_mask_training_override_status(
    row: Mapping[str, Any],
    reject_reasons: list[str] | None = None,
) -> dict[str, Any]:
    """Trainer-only allowance for PIT-safe historical missing masks.

    Live/risk/prediction scoring stays strict. This helper only permits replay
    samples whose absent feature families are explicitly masked and whose stale,
    finality, and future-leak checks are clean.
    """

    reasons = {str(reason) for reason in (reject_reasons or []) if str(reason)}
    missing_names = [str(name) for name in _as_list(row.get("missing_feature_names"))]
    stale_names = [str(name) for name in _as_list(row.get("stale_feature_names"))]
    row_source = str(
        row.get("row_source")
        or row.get("trainer_feedback_source")
        or row.get("update_lane")
        or ""
    ).upper()
    classification = str(row.get("row_classification") or "").upper()
    source_availability = row.get("source_availability")
    source_availability_recorded = bool(
        row.get("source_availability_recorded") is True
        or row.get("source_availability_preserved") is True
        or isinstance(source_availability, (Mapping, list, tuple))
    )
    lineage_mask_present = bool(
        row.get("lineage_mask_present") is True
        or row.get("tensor_missing_mask_preserved") is True
        or "missing_mask" in row
        or "missing_feature_names" in row
    )
    classification_mask_present = bool(
        row.get("classification_mask_present") is True
        or classification in {"TRAINABLE", "MISSING_MASKED", "STALE_MASKED"}
    )
    historical_or_replay = bool(
        row.get("feature_family_introduced_after_snapshot_time") is True
        or row.get("historical_replay_row") is True
        or row.get("trusted_replay_row") is True
        or row.get("safe_missing_mask_training_scope") == "HISTORICAL_REPLAY_ONLY"
        or "TRUSTED_REPLAY" in row_source
        or "DURABLE_FEATURE_SNAPSHOT" in row_source
        or "OUTCOME_SUPERVISED_TRUSTED_REPLAY" in row_source
    )
    hard_reasons = sorted(reasons.intersection(TRAINING_MISSING_MASK_HARD_REJECT_REASONS))
    core_missing = sorted(
        name for name in missing_names if name.lower() in CORE_PRICE_MISSING_NAMES
    )
    critical_family_missing = sorted(
        name
        for name in missing_names
        if name.strip().lower().startswith("critical_family_absent:")
    )
    stale_count = int(row.get("stale_feature_count") or len(stale_names) or 0)

    unsafe_reason = None
    if row.get("safe_to_train_with_missing_mask") is not True:
        unsafe_reason = "SAFE_MISSING_MASK_FLAG_NOT_SET"
    elif not historical_or_replay:
        unsafe_reason = "NOT_HISTORICAL_REPLAY_SCOPE"
    elif classification not in {"MISSING_MASKED", "TRAINABLE"}:
        unsafe_reason = "ROW_CLASSIFICATION_NOT_RECONSTRUCTABLE"
    elif not lineage_mask_present:
        unsafe_reason = "LINEAGE_MASK_MISSING"
    elif not classification_mask_present:
        unsafe_reason = "CLASSIFICATION_MASK_MISSING"
    elif not source_availability_recorded:
        unsafe_reason = "SOURCE_AVAILABILITY_MISSING"
    elif stale_count > 0 or stale_names:
        unsafe_reason = "STALE_FEATURE_FAMILY"
    elif core_missing:
        unsafe_reason = "CRITICAL_CORE_PRICE_FAMILY_MISSING"
    elif critical_family_missing:
        unsafe_reason = "CRITICAL_FEATURE_FAMILY_MISSING"
    elif hard_reasons:
        unsafe_reason = hard_reasons[0]
    elif reasons and not reasons.issubset(TRAINING_MISSING_MASK_TOLERATED_REASONS):
        unsafe_reason = "UNSAFE_REJECT_REASONS_PRESENT"

    safe = unsafe_reason is None
    return {
        "safe_to_train_with_missing_mask": safe,
        "unsafe_to_train_reason": None if safe else unsafe_reason,
        "row_source": row_source or None,
        "missing_feature_families": missing_names,
        "masked_feature_families": missing_names,
        "stale_feature_families": stale_names,
        "critical_missing_vs_optional_missing": (
            "HISTORICAL_SCHEMA_MISSING_MASKED"
            if safe
            else "UNSAFE_OR_UNPROVEN_MISSING_MASK"
        ),
        "feature_family_introduced_after_snapshot_time": bool(
            row.get("feature_family_introduced_after_snapshot_time")
        ),
        "source_availability": source_availability if source_availability_recorded else {},
        "source_availability_recorded": source_availability_recorded,
        "lineage_mask_present": lineage_mask_present,
        "classification_mask_present": classification_mask_present,
        "classification_reconstructable": classification
        in {"MISSING_MASKED", "TRAINABLE"},
    }


def classify_training_sample(row: dict[str, Any], thresholds: IntegrityThresholds | None = None) -> dict[str, Any]:
    score = score_market_state(row, thresholds=thresholds)
    accepted = score.valid_for_training
    reasons = list(score.reject_reasons)
    if score.market_state_integrity_score < (thresholds or IntegrityThresholds()).training_min_score:
        reasons.append("MARKET_STATE_INTEGRITY_SCORE_BELOW_TRAINING_MIN")
    missing_mask_override = missing_mask_training_override_status(row, reasons)
    if missing_mask_override["safe_to_train_with_missing_mask"]:
        accepted = True
        reasons = [
            reason
            for reason in reasons
            if reason not in TRAINING_MISSING_MASK_TOLERATED_REASONS
        ]
    elif missing_mask_override["unsafe_to_train_reason"] in {
        "CRITICAL_CORE_PRICE_FAMILY_MISSING",
        "CRITICAL_FEATURE_FAMILY_MISSING",
    }:
        # The explicit critical-family prefix is authoritative.  A producer's
        # stale ``accepted_for_training`` flag or otherwise complete core-price
        # payload cannot self-attest around the missing critical family.
        accepted = False
        reasons.append("MISSING_CRITICAL_FEATURE_FAMILY")
    return {
        "market_state_id": score.market_state_id,
        "feature_snapshot_id": row.get("feature_snapshot_id"),
        "prediction_id": row.get("prediction_id"),
        "accepted_for_training": accepted,
        "market_state_integrity_score": score.market_state_integrity_score,
        "valid_for_training": accepted,
        "reject_reasons": sorted(set(reasons)),
        "source_lineage": score.source_lineage,
        "missing_mask_training_override": missing_mask_override,
        "safe_to_train_with_missing_mask": missing_mask_override[
            "safe_to_train_with_missing_mask"
        ],
        "unsafe_to_train_reason": missing_mask_override["unsafe_to_train_reason"],
    }
