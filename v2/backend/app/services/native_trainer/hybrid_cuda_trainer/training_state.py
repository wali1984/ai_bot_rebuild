"""Durable, non-serving trainer progress and exact-PPO consumption state.

This state is local to the paper/shadow trainer.  It never authorizes serving,
paper fills, leverage, margin, or live execution.  Its only purposes are to
retain forward-validated learning progress and to prevent the same finalized
behavior/outcome pair from being optimized repeatedly under one parent policy.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .confidence import (
    CONFIDENCE_FIT_PARTITION,
    CONFIDENCE_HEAD_ACTIONS,
    CONFIDENCE_LABEL_SEMANTICS,
    CONFIDENCE_UNCERTAINTY_EVIDENCE_SCHEMA_VERSION,
    CONFIDENCE_UNCERTAINTY_METHOD,
    confidence_uncertainty_evidence_digest,
    normalize_calibration_state,
)

PPO_CONSUMPTION_UPDATE_KEY_SCHEMA_VERSION = (
    "v2_exact_ppo_consumption_update_key_v1"
)
PPO_CONSUMPTION_LEDGER_SCHEMA_VERSION = "v2_exact_ppo_consumption_ledger_v4"
PPO_CONSUMPTION_LEDGER_PREVIOUS_SCHEMA_VERSIONS = frozenset(
    {
        "v2_exact_ppo_consumption_ledger_v2",
        "v2_exact_ppo_consumption_ledger_v3",
    }
)
PPO_RECEIPT_ARCHIVE_SYNC_SCHEMA_VERSION = (
    "v2_exact_ppo_receipt_archive_sync_v2"
)
PPO_RECEIPT_ARCHIVE_BINDING_SCHEMA_VERSION = (
    "v2_exact_ppo_receipt_archive_event_binding_v1"
)
PPO_TRAINING_PARTITION_SCHEMA_VERSION = "v2_exact_ppo_training_partition_v1"
CANDIDATE_PROGRESS_SCHEMA_VERSION = "v2_non_serving_candidate_progress_gate_v1"
CONFIDENCE_PROMOTION_GATE_SCHEMA_VERSION = (
    "v2_checkpoint_bound_confidence_promotion_gate_v1"
)


def _utc_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _finite(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _nonnegative_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(numeric) or numeric != float(parsed) or parsed < 0:
        return None
    return parsed


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def canonical_digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _sha256_hex(value: Any) -> bool:
    text = str(value or "")
    return len(text) == 64 and all(
        character in "0123456789abcdef" for character in text
    )


def ppo_consumption_update_key(
    *,
    receipt_hash: str,
    finalized_outcome_digest: str,
    parent_policy_fingerprint: str,
) -> str:
    """Bind one optimizer attempt to exact behavior, outcome, and parent weights."""
    values = {
        "schema_version": PPO_CONSUMPTION_UPDATE_KEY_SCHEMA_VERSION,
        "receipt_hash": str(receipt_hash or ""),
        "finalized_outcome_digest": str(finalized_outcome_digest or ""),
        "parent_policy_fingerprint": str(parent_policy_fingerprint or ""),
    }
    if any(
        len(value) != 64
        for field, value in values.items()
        if field != "schema_version"
    ):
        raise ValueError("ppo_consumption_update_key_sha256_binding_invalid")
    return canonical_digest(values)


def training_partition_digest(update_keys: Sequence[str]) -> str:
    keys = [str(value) for value in update_keys]
    if any(len(value) != 64 for value in keys):
        raise ValueError("training_partition_update_key_invalid")
    return canonical_digest(
        {
            "schema_version": PPO_TRAINING_PARTITION_SCHEMA_VERSION,
            "ordered_ppo_update_keys": keys,
        }
    )


def candidate_progress_decision(training_metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Allow non-serving persistence only on PIT-safe Pareto progress.

    There is no market threshold here.  The candidate must use an untouched
    chronological validation partition, perform a real parameter update, avoid
    regression in every available validation objective, and strictly improve at
    least one available objective.  Serving approval remains a separate gate.
    """

    metrics = dict(training_metrics)
    before_loss = _finite(metrics.get("validation_supervised_loss_before"))
    after_loss = _finite(metrics.get("validation_supervised_loss"))
    before_edge = _finite(
        metrics.get("validation_policy_edge_before_lower_confidence_bound_bps")
    )
    after_edge = _finite(
        metrics.get("validation_policy_edge_lower_confidence_bound_bps")
    )
    rejection_reasons: list[str] = []
    if metrics.get("validation_split_pit_safe") is not True:
        rejection_reasons.append("CANDIDATE_VALIDATION_SPLIT_PIT_UNSAFE")
    validation_rows = _nonnegative_int(metrics.get("validation_rows"))
    validation_edge_rows = _nonnegative_int(
        metrics.get("validation_policy_edge_rows_evaluated")
    )
    if (validation_rows or 0) <= 0 and (validation_edge_rows or 0) <= 0:
        rejection_reasons.append("CANDIDATE_UNTOUCHED_VALIDATION_ROWS_MISSING")
    optimizer_steps = _nonnegative_int(metrics.get("optimizer_steps_this_cycle"))
    if (optimizer_steps or 0) <= 0:
        rejection_reasons.append("CANDIDATE_OPTIMIZER_UPDATE_MISSING")
    if metrics.get("parameter_hash_before") in (None, "") or metrics.get(
        "parameter_hash_after"
    ) in (None, ""):
        rejection_reasons.append("CANDIDATE_PARAMETER_HASH_PROOF_MISSING")
    elif metrics.get("parameter_hash_before") == metrics.get("parameter_hash_after"):
        rejection_reasons.append("CANDIDATE_PARAMETERS_UNCHANGED")
    if before_loss is None or after_loss is None:
        rejection_reasons.append("CANDIDATE_VALIDATION_LOSS_UNAVAILABLE")

    loss_non_regression = (
        before_loss is not None and after_loss is not None and after_loss <= before_loss
    )
    loss_improved = (
        before_loss is not None and after_loss is not None and after_loss < before_loss
    )
    edge_comparable = before_edge is not None and after_edge is not None
    edge_non_regression = not edge_comparable or after_edge >= before_edge
    edge_improved = edge_comparable and after_edge > before_edge
    if before_loss is not None and after_loss is not None and not loss_non_regression:
        rejection_reasons.append("CANDIDATE_VALIDATION_LOSS_REGRESSED")
    if not edge_non_regression:
        rejection_reasons.append("CANDIDATE_VALIDATION_EDGE_LCB_REGRESSED")
    if not (loss_improved or edge_improved):
        rejection_reasons.append("CANDIDATE_NO_STRICT_FORWARD_VALIDATION_IMPROVEMENT")

    allowed = not rejection_reasons
    return {
        "schema_version": CANDIDATE_PROGRESS_SCHEMA_VERSION,
        "candidate_progress_allowed": allowed,
        "candidate_progress_rejected": not allowed,
        "candidate_progress_reason": (
            "PIT_SAFE_NON_SERVING_PARETO_PROGRESS"
            if allowed
            else rejection_reasons[0]
        ),
        "candidate_progress_rejection_reasons": rejection_reasons,
        "validation_supervised_loss_before": before_loss,
        "validation_supervised_loss_after": after_loss,
        "validation_policy_edge_lcb_before_bps": before_edge,
        "validation_policy_edge_lcb_after_bps": after_edge,
        "validation_loss_non_regression": loss_non_regression,
        "validation_loss_strictly_improved": loss_improved,
        "validation_edge_lcb_comparable": edge_comparable,
        "validation_edge_lcb_non_regression": edge_non_regression,
        "validation_edge_lcb_strictly_improved": edge_improved,
        "serving_authorized": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


def confidence_promotion_decision(
    *,
    training_metrics: Mapping[str, Any],
    calibration_state: Mapping[str, Any] | None,
    candidate_policy_fingerprint: str,
) -> dict[str, Any]:
    """Require honest, checkpoint-bound calibration on untouched forward rows.

    This gate has no market threshold.  It verifies identity, partition, class,
    direction, and same-row metric contracts, then requires calibration to be a
    non-regression versus the raw confidence head globally and for each action.
    It is necessary but never sufficient to authorize serving.
    """

    metrics = dict(training_metrics)
    state = normalize_calibration_state(calibration_state)
    fingerprint = str(candidate_policy_fingerprint or "").lower()
    reasons: list[str] = []

    if len(fingerprint) != 64 or any(
        character not in "0123456789abcdef" for character in fingerprint
    ):
        reasons.append("CONFIDENCE_CANDIDATE_POLICY_FINGERPRINT_INVALID")
    if state.get("fitted") is not True:
        reasons.append(
            str(state.get("reason") or "CONFIDENCE_CHECKPOINT_CALIBRATION_UNFITTED")
        )
    elif state.get("model_parameter_fingerprint") != fingerprint:
        reasons.append("CONFIDENCE_CALIBRATION_NOT_BOUND_TO_CANDIDATE_WEIGHTS")

    metric_fingerprint = str(
        metrics.get("confidence_calibration_model_parameter_fingerprint") or ""
    ).lower()
    if metric_fingerprint != fingerprint:
        reasons.append("CONFIDENCE_METRIC_FINGERPRINT_NOT_BOUND_TO_CANDIDATE")
    if metrics.get("confidence_calibration_fitted") is not True:
        reasons.append("CONFIDENCE_TRAIN_PARTITION_CALIBRATION_UNFITTED")
    if metrics.get("confidence_calibration_fit_partition") != CONFIDENCE_FIT_PARTITION:
        reasons.append("CONFIDENCE_FIT_PARTITION_NOT_PURGED_TRAIN_ONLY")
    calibration_validation_rows = _nonnegative_int(
        metrics.get("confidence_calibration_validation_rows_used")
    )
    if calibration_validation_rows != 0:
        reasons.append("CONFIDENCE_FORWARD_VALIDATION_USED_FOR_FIT")
    if metrics.get("confidence_calibration_label_semantics") != CONFIDENCE_LABEL_SEMANTICS:
        reasons.append("CONFIDENCE_TRAIN_LABEL_SEMANTICS_MISMATCH")
    if metrics.get("validation_confidence_label_semantics") != CONFIDENCE_LABEL_SEMANTICS:
        reasons.append("CONFIDENCE_VALIDATION_LABEL_SEMANTICS_MISMATCH")
    if metrics.get("validation_confidence_status") != (
        "EVALUATED_UNTOUCHED_FORWARD_PARTITION"
    ):
        reasons.append("CONFIDENCE_UNTOUCHED_FORWARD_EVALUATION_MISSING")
    if metrics.get("validation_confidence_partition_untouched") is not True:
        reasons.append("CONFIDENCE_FORWARD_PARTITION_TOUCHED")
    if metrics.get("validation_confidence_fit_validation_digest_disjoint") is not True:
        reasons.append("CONFIDENCE_FIT_VALIDATION_PARTITIONS_NOT_PROVEN_DISJOINT")
    validation_rows_used_for_fit = _nonnegative_int(
        metrics.get("validation_confidence_rows_used_for_fit")
    )
    if validation_rows_used_for_fit != 0:
        reasons.append("CONFIDENCE_VALIDATION_ROWS_USED_FOR_FIT")

    fit_digest = str(metrics.get("validation_confidence_fit_row_digest") or "")
    state_fit_digest = str(state.get("row_digest") or "")
    validation_digest = str(
        metrics.get("validation_confidence_eligible_row_digest") or ""
    )
    for name, digest in (
        ("FIT", fit_digest),
        ("STATE_FIT", state_fit_digest),
        ("VALIDATION", validation_digest),
    ):
        if len(digest) != 64 or any(
            character not in "0123456789abcdef" for character in digest.lower()
        ):
            reasons.append(f"CONFIDENCE_{name}_ROW_DIGEST_INVALID")
    if fit_digest and state_fit_digest and fit_digest != state_fit_digest:
        reasons.append("CONFIDENCE_FIT_ROW_DIGEST_STATE_MISMATCH")
    if fit_digest and validation_digest and fit_digest == validation_digest:
        reasons.append("CONFIDENCE_FIT_VALIDATION_ROW_DIGEST_COLLISION")

    rows = _nonnegative_int(metrics.get("validation_confidence_rows_evaluated"))
    direction_rows = {
        action: _nonnegative_int(
            metrics.get(f"validation_confidence_{action}_rows")
        )
        for action in CONFIDENCE_HEAD_ACTIONS
    }
    if rows is None or rows <= 0:
        reasons.append("CONFIDENCE_FORWARD_VALIDATION_ROWS_MISSING")
    if any(count is None or count <= 0 for count in direction_rows.values()):
        reasons.append("CONFIDENCE_FORWARD_DIRECTION_COVERAGE_MISSING")
    if (
        rows is not None
        and all(count is not None for count in direction_rows.values())
        and sum(count for count in direction_rows.values() if count is not None)
        != rows
    ):
        reasons.append("CONFIDENCE_FORWARD_DIRECTION_ROW_COUNT_MISMATCH")

    metric_pairs = [
        (
            "GLOBAL_BRIER",
            "validation_confidence_raw_brier",
            "validation_confidence_calibrated_brier",
        ),
        (
            "GLOBAL_ECE",
            "validation_confidence_raw_ece",
            "validation_confidence_calibrated_ece",
        ),
    ]
    for action in CONFIDENCE_HEAD_ACTIONS:
        metric_pairs.extend(
            (
                (
                    f"{action.upper()}_BRIER",
                    f"validation_confidence_{action}_raw_brier",
                    f"validation_confidence_{action}_calibrated_brier",
                ),
                (
                    f"{action.upper()}_ECE",
                    f"validation_confidence_{action}_raw_ece",
                    f"validation_confidence_{action}_calibrated_ece",
                ),
            )
        )
    comparisons: dict[str, dict[str, float | bool | None]] = {}
    for name, raw_field, calibrated_field in metric_pairs:
        raw = _finite(metrics.get(raw_field))
        calibrated = _finite(metrics.get(calibrated_field))
        non_regression = bool(
            raw is not None
            and calibrated is not None
            and 0.0 <= raw <= 1.0
            and 0.0 <= calibrated <= 1.0
            and calibrated <= raw
        )
        comparisons[name] = {
            "raw": raw,
            "calibrated": calibrated,
            "non_regression": non_regression,
        }
        if raw is None or calibrated is None:
            reasons.append(f"CONFIDENCE_{name}_METRIC_MISSING_OR_NONFINITE")
        elif not (0.0 <= raw <= 1.0 and 0.0 <= calibrated <= 1.0):
            reasons.append(f"CONFIDENCE_{name}_METRIC_OUT_OF_RANGE")
        elif calibrated > raw:
            reasons.append(f"CONFIDENCE_{name}_CALIBRATION_REGRESSED")

    uncertainty_comparisons: dict[str, dict[str, Any]] = {}
    for scope, scope_rows in (("GLOBAL", rows), *(
        (action.upper(), direction_rows[action])
        for action in CONFIDENCE_HEAD_ACTIONS
    )):
        scope_row_count = scope_rows if scope_rows is not None else 0
        field_scope = "" if scope == "GLOBAL" else f"{scope.lower()}_"
        prefix = f"validation_confidence_{field_scope}"
        paired_deltas = metrics.get(f"{prefix}paired_brier_delta_per_row")
        ece_loo_deltas = metrics.get(f"{prefix}ece_leave_one_out_delta")
        brier_mean = _finite(metrics.get(f"{prefix}paired_brier_delta_mean"))
        brier_se = _finite(
            metrics.get(f"{prefix}paired_brier_delta_standard_error")
        )
        brier_upper = _finite(
            metrics.get(
                f"{prefix}paired_brier_delta_one_standard_error_upper_bound"
            )
        )
        ece_delta = _finite(metrics.get(f"{prefix}ece_delta"))
        ece_se = _finite(
            metrics.get(f"{prefix}ece_jackknife_standard_error")
        )
        ece_upper = _finite(
            metrics.get(f"{prefix}ece_one_standard_error_upper_bound")
        )
        uncertainty_rows = _nonnegative_int(
            metrics.get(f"{prefix}uncertainty_row_count")
        )
        uncertainty_digest = str(
            metrics.get(f"{prefix}uncertainty_evidence_digest") or ""
        )
        uncertainty_schema = metrics.get(
            f"{prefix}uncertainty_evidence_schema_version"
        )
        uncertainty_scope = metrics.get(f"{prefix}uncertainty_scope")
        uncertainty_method = metrics.get(f"{prefix}uncertainty_method")
        scope_reasons: list[str] = []
        if uncertainty_schema != CONFIDENCE_UNCERTAINTY_EVIDENCE_SCHEMA_VERSION:
            scope_reasons.append("UNCERTAINTY_EVIDENCE_SCHEMA_INVALID")
        if uncertainty_scope != scope:
            scope_reasons.append("UNCERTAINTY_SCOPE_INVALID")
        if uncertainty_method != CONFIDENCE_UNCERTAINTY_METHOD:
            scope_reasons.append("UNCERTAINTY_METHOD_INVALID")
        if uncertainty_rows is None:
            scope_reasons.append("ROW_COUNT_INVALID")
        elif uncertainty_rows != scope_row_count:
            scope_reasons.append("ROW_COUNT_MISMATCH")
        if metrics.get(f"{prefix}uncertainty_minimum_not_configured") is not True:
            scope_reasons.append("CONFIGURED_MINIMUM_PRESENT")
        if metrics.get(f"{prefix}uncertainty_mathematical_minimum_rows") != 2:
            scope_reasons.append("MATHEMATICAL_MINIMUM_INVALID")
        if scope_row_count <= 1:
            scope_reasons.append("PAIRED_UNCERTAINTY_NOT_IDENTIFIABLE")
        if not isinstance(paired_deltas, list) or len(paired_deltas) != scope_row_count:
            scope_reasons.append("PAIRED_BRIER_DELTAS_MISSING")
            parsed_paired_deltas: list[float] = []
        else:
            parsed_paired_deltas = [
                value
                for value in (_finite(item) for item in paired_deltas)
                if value is not None
            ]
            if len(parsed_paired_deltas) != len(paired_deltas):
                scope_reasons.append("PAIRED_BRIER_DELTAS_NONFINITE")
        if not isinstance(ece_loo_deltas, list) or len(ece_loo_deltas) != scope_row_count:
            scope_reasons.append("ECE_JACKKNIFE_DELTAS_MISSING")
            parsed_ece_loo: list[float] = []
        else:
            parsed_ece_loo = [
                value
                for value in (_finite(item) for item in ece_loo_deltas)
                if value is not None
            ]
            if len(parsed_ece_loo) != len(ece_loo_deltas):
                scope_reasons.append("ECE_JACKKNIFE_DELTAS_NONFINITE")
        if any(
            value is None
            for value in (brier_mean, brier_se, brier_upper, ece_delta, ece_se, ece_upper)
        ):
            scope_reasons.append("UNCERTAINTY_METRIC_MISSING_OR_NONFINITE")
        if brier_se is not None and brier_se < 0.0:
            scope_reasons.append("PAIRED_BRIER_STANDARD_ERROR_NEGATIVE")
        if ece_se is not None and ece_se < 0.0:
            scope_reasons.append("ECE_JACKKNIFE_STANDARD_ERROR_NEGATIVE")
        if parsed_paired_deltas and brier_mean is not None:
            expected_mean = sum(parsed_paired_deltas) / len(parsed_paired_deltas)
            expected_se = math.sqrt(
                sum((value - expected_mean) ** 2 for value in parsed_paired_deltas)
                / (len(parsed_paired_deltas) - 1)
                / len(parsed_paired_deltas)
            ) if len(parsed_paired_deltas) > 1 else None
            if not math.isclose(brier_mean, expected_mean, rel_tol=1e-12, abs_tol=1e-12):
                scope_reasons.append("PAIRED_BRIER_MEAN_ARITHMETIC_MISMATCH")
            if expected_se is None or brier_se is None or not math.isclose(
                brier_se, expected_se, rel_tol=1e-12, abs_tol=1e-12
            ):
                scope_reasons.append("PAIRED_BRIER_SE_ARITHMETIC_MISMATCH")
        if (
            brier_mean is not None
            and brier_se is not None
            and (
                brier_upper is None
                or not math.isclose(
                    brier_upper,
                    brier_mean + brier_se,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                )
            )
        ):
            scope_reasons.append("PAIRED_BRIER_UPPER_BOUND_ARITHMETIC_MISMATCH")
        if parsed_ece_loo and ece_se is not None:
            loo_mean = sum(parsed_ece_loo) / len(parsed_ece_loo)
            expected_ece_se = math.sqrt(
                ((len(parsed_ece_loo) - 1) / len(parsed_ece_loo))
                * sum((value - loo_mean) ** 2 for value in parsed_ece_loo)
            )
            if not math.isclose(
                ece_se, expected_ece_se, rel_tol=1e-12, abs_tol=1e-12
            ):
                scope_reasons.append("ECE_JACKKNIFE_SE_ARITHMETIC_MISMATCH")
        if (
            ece_delta is not None
            and ece_se is not None
            and (
                ece_upper is None
                or not math.isclose(
                    ece_upper,
                    ece_delta + ece_se,
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                )
            )
        ):
            scope_reasons.append("ECE_UPPER_BOUND_ARITHMETIC_MISMATCH")
        brier_comparison = comparisons.get(f"{scope}_BRIER", {})
        ece_comparison = comparisons.get(f"{scope}_ECE", {})
        raw_brier = _finite(brier_comparison.get("raw"))
        calibrated_brier = _finite(brier_comparison.get("calibrated"))
        raw_ece = _finite(ece_comparison.get("raw"))
        calibrated_ece = _finite(ece_comparison.get("calibrated"))
        if (
            raw_brier is not None
            and calibrated_brier is not None
            and brier_mean is not None
            and not math.isclose(
                brier_mean,
                calibrated_brier - raw_brier,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ):
            scope_reasons.append("PAIRED_BRIER_POINT_METRIC_MISMATCH")
        if (
            raw_ece is not None
            and calibrated_ece is not None
            and ece_delta is not None
            and not math.isclose(
                ece_delta,
                calibrated_ece - raw_ece,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ):
            scope_reasons.append("ECE_POINT_METRIC_MISMATCH")
        if len(uncertainty_digest) != 64 or any(
            character not in "0123456789abcdef"
            for character in uncertainty_digest.lower()
        ):
            scope_reasons.append("UNCERTAINTY_EVIDENCE_DIGEST_INVALID")
        try:
            expected_uncertainty_digest = confidence_uncertainty_evidence_digest(
                scope=scope,
                evidence={
                    "paired_brier_delta_per_row": parsed_paired_deltas,
                    "paired_brier_delta_mean": brier_mean,
                    "paired_brier_delta_standard_error": brier_se,
                    "paired_brier_delta_one_standard_error_upper_bound": (
                        brier_upper
                    ),
                    "paired_brier_uncertainty_available": metrics.get(
                        f"{prefix}paired_brier_uncertainty_available"
                    ),
                    "paired_brier_non_regression_proven": metrics.get(
                        f"{prefix}paired_brier_non_regression_proven"
                    ),
                    "ece_delta": ece_delta,
                    "ece_leave_one_out_delta": parsed_ece_loo,
                    "ece_jackknife_standard_error": ece_se,
                    "ece_one_standard_error_upper_bound": ece_upper,
                    "ece_uncertainty_available": metrics.get(
                        f"{prefix}ece_uncertainty_available"
                    ),
                    "ece_non_regression_proven": metrics.get(
                        f"{prefix}ece_non_regression_proven"
                    ),
                    "uncertainty_row_count": uncertainty_rows,
                    "uncertainty_minimum_not_configured": metrics.get(
                        f"{prefix}uncertainty_minimum_not_configured"
                    ),
                    "uncertainty_mathematical_minimum_rows": metrics.get(
                        f"{prefix}uncertainty_mathematical_minimum_rows"
                    ),
                },
            )
        except (TypeError, ValueError):
            expected_uncertainty_digest = None
            scope_reasons.append("UNCERTAINTY_EVIDENCE_CANONICALIZATION_FAILED")
        if (
            expected_uncertainty_digest is not None
            and uncertainty_digest.lower() != expected_uncertainty_digest
        ):
            scope_reasons.append("UNCERTAINTY_EVIDENCE_DIGEST_MISMATCH")
        if metrics.get(f"{prefix}paired_brier_uncertainty_available") is not True:
            scope_reasons.append("PAIRED_BRIER_UNCERTAINTY_UNAVAILABLE")
        if metrics.get(f"{prefix}ece_uncertainty_available") is not True:
            scope_reasons.append("ECE_UNCERTAINTY_UNAVAILABLE")
        if brier_upper is None or brier_upper > 0.0 or metrics.get(
            f"{prefix}paired_brier_non_regression_proven"
        ) is not True:
            scope_reasons.append("PAIRED_BRIER_NON_REGRESSION_NOT_PROVEN")
        if ece_upper is None or ece_upper > 0.0 or metrics.get(
            f"{prefix}ece_non_regression_proven"
        ) is not True:
            scope_reasons.append("ECE_NON_REGRESSION_NOT_PROVEN")
        uncertainty_comparisons[scope] = {
            "rows": scope_row_count,
            "paired_brier_delta_mean": brier_mean,
            "paired_brier_standard_error": brier_se,
            "paired_brier_upper_bound": brier_upper,
            "ece_delta": ece_delta,
            "ece_jackknife_standard_error": ece_se,
            "ece_upper_bound": ece_upper,
            "non_regression_proven": not scope_reasons,
            "rejection_reasons": scope_reasons,
        }
        reasons.extend(
            f"CONFIDENCE_{scope}_{reason}" for reason in scope_reasons
        )

    passed = not reasons
    return {
        "schema_version": CONFIDENCE_PROMOTION_GATE_SCHEMA_VERSION,
        "confidence_promotion_gate_passed": passed,
        "confidence_promotion_gate_rejected": not passed,
        "confidence_promotion_reason": (
            "CHECKPOINT_BOUND_UNTOUCHED_FORWARD_CALIBRATION_PASS"
            if passed
            else reasons[0]
        ),
        "confidence_promotion_rejection_reasons": reasons,
        "candidate_policy_fingerprint": fingerprint,
        "calibration_policy_fingerprint": state.get(
            "model_parameter_fingerprint"
        ),
        "fit_row_digest": fit_digest or None,
        "validation_row_digest": validation_digest or None,
        "validation_rows": rows or 0,
        "validation_direction_rows": direction_rows,
        "same_row_metric_comparisons": comparisons,
        "paired_uncertainty_comparisons": uncertainty_comparisons,
        "serving_authorized": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }


class PPOConsumptionLedger:
    """Append-only SQLite audit ledger for exact PPO optimizer attempts."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ppo_attempts (
                    sequence INTEGER NOT NULL UNIQUE,
                    update_key TEXT PRIMARY KEY,
                    receipt_hash TEXT NOT NULL,
                    finalized_outcome_digest TEXT NOT NULL,
                    parent_policy_fingerprint TEXT NOT NULL,
                    child_policy_fingerprint TEXT NOT NULL,
                    disposition TEXT NOT NULL,
                    checkpoint_id TEXT,
                    checkpoint_path TEXT,
                    checkpoint_sha256 TEXT,
                    training_partition_digest TEXT NOT NULL,
                    recorded_utc TEXT NOT NULL,
                    previous_chain_hash TEXT NOT NULL,
                    chain_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ppo_claims (
                    update_key TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    receipt_hash TEXT NOT NULL,
                    finalized_outcome_digest TEXT NOT NULL,
                    parent_policy_fingerprint TEXT NOT NULL,
                    claimed_utc TEXT NOT NULL,
                    optimizer_started_utc TEXT,
                    optimizer_partition_digest TEXT,
                    optimizer_partition_index INTEGER
                );
                CREATE TABLE IF NOT EXISTS ppo_archive_sync_bindings (
                    sequence INTEGER PRIMARY KEY,
                    ledger_chain_hash TEXT NOT NULL,
                    receipt_hash TEXT NOT NULL,
                    trainer_consumed_event_hash TEXT NOT NULL,
                    previous_binding_chain_hash TEXT NOT NULL,
                    binding_chain_hash TEXT NOT NULL,
                    FOREIGN KEY(sequence) REFERENCES ppo_attempts(sequence)
                );
                """
            )
            connection.execute("BEGIN IMMEDIATE")
            claim_columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(ppo_claims)")
            }
            for column_name, column_type in (
                ("optimizer_started_utc", "TEXT"),
                ("optimizer_partition_digest", "TEXT"),
                ("optimizer_partition_index", "INTEGER"),
            ):
                if column_name not in claim_columns:
                    connection.execute(
                        f"ALTER TABLE ppo_claims ADD COLUMN {column_name} {column_type}"
                    )
            schema_row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
            source_schema = str(schema_row[0]) if schema_row is not None else None
            if source_schema is None:
                connection.execute(
                    "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
                    (PPO_CONSUMPTION_LEDGER_SCHEMA_VERSION,),
                )
            elif source_schema in PPO_CONSUMPTION_LEDGER_PREVIOUS_SCHEMA_VERSIONS:
                connection.execute(
                    "UPDATE metadata SET value = ? WHERE key = 'schema_version'",
                    (PPO_CONSUMPTION_LEDGER_SCHEMA_VERSION,),
                )
            elif source_schema != PPO_CONSUMPTION_LEDGER_SCHEMA_VERSION:
                raise RuntimeError("ppo_consumption_ledger_schema_not_migratable")
            connection.execute(
                "INSERT OR IGNORE INTO metadata(key, value) VALUES('row_count', '0')"
            )
            connection.execute(
                "INSERT OR IGNORE INTO metadata(key, value) VALUES('chain_tip', ?)",
                ("0" * 64,),
            )
            row_count_row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'row_count'"
            ).fetchone()
            row_count = int(row_count_row[0]) if row_count_row is not None else 0
            receipt_schema_row = connection.execute(
                "SELECT value FROM metadata "
                "WHERE key = 'receipt_archive_sync_schema_version'"
            ).fetchone()
            receipt_schema = (
                str(receipt_schema_row[0]) if receipt_schema_row is not None else None
            )
            initialize_archive_contract = receipt_schema is None
            migrate_unbound_archive_watermark = receipt_schema == (
                "v2_exact_ppo_receipt_archive_sync_v1"
            )
            if (
                initialize_archive_contract
                and source_schema in {
                    "v2_exact_ppo_consumption_ledger_v3",
                    PPO_CONSUMPTION_LEDGER_SCHEMA_VERSION,
                }
                and row_count > 0
            ):
                raise RuntimeError("ppo_receipt_archive_sync_metadata_missing")
            if (
                receipt_schema is not None
                and not migrate_unbound_archive_watermark
                and receipt_schema != PPO_RECEIPT_ARCHIVE_SYNC_SCHEMA_VERSION
            ):
                raise RuntimeError("ppo_receipt_archive_sync_schema_not_migratable")

            if initialize_archive_contract or migrate_unbound_archive_watermark:
                # A v2 ledger predates the receipt archive.  Its existing rows
                # remain explicitly legacy.  A v3 archive watermark, however,
                # named only a ledger chain hash and did not bind the immutable
                # TRAINER_CONSUMED event.  Reset that watermark to activation-1
                # so startup must re-read and bind every post-activation event.
                if migrate_unbound_archive_watermark:
                    activation_row = connection.execute(
                        "SELECT value FROM metadata "
                        "WHERE key = 'receipt_archive_activation_sequence'"
                    ).fetchone()
                    if activation_row is None:
                        raise RuntimeError(
                            "ppo_receipt_archive_activation_sequence_missing"
                        )
                    activation_sequence = int(activation_row[0])
                else:
                    activation_sequence = 1 if row_count == 0 else row_count + 1
                sync_sequence = activation_sequence - 1
                sync_chain_hash = "0" * 64
                if sync_sequence > 0:
                    sync_row = connection.execute(
                        "SELECT chain_hash FROM ppo_attempts WHERE sequence = ?",
                        (sync_sequence,),
                    ).fetchone()
                    if sync_row is None:
                        raise RuntimeError(
                            "ppo_receipt_archive_activation_ledger_row_missing"
                        )
                    sync_chain_hash = str(sync_row[0])
                binding_chain_tip = "0" * 64
                connection.execute("DELETE FROM ppo_archive_sync_bindings")
                sync_state = {
                    "schema_version": PPO_RECEIPT_ARCHIVE_SYNC_SCHEMA_VERSION,
                    "activation_sequence": activation_sequence,
                    "sync_sequence": sync_sequence,
                    "sync_chain_hash": sync_chain_hash,
                    "binding_chain_tip": binding_chain_tip,
                }
                for key, value in (
                    (
                        "receipt_archive_sync_schema_version",
                        PPO_RECEIPT_ARCHIVE_SYNC_SCHEMA_VERSION,
                    ),
                    (
                        "receipt_archive_activation_sequence",
                        str(activation_sequence),
                    ),
                    ("receipt_archive_sync_sequence", str(sync_sequence)),
                    ("receipt_archive_sync_chain_hash", sync_chain_hash),
                    (
                        "receipt_archive_sync_binding_chain_tip",
                        binding_chain_tip,
                    ),
                    (
                        "receipt_archive_sync_state_digest",
                        canonical_digest(sync_state),
                    ),
                ):
                    connection.execute(
                        "INSERT INTO metadata(key, value) VALUES(?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, value),
                    )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @staticmethod
    def _semantic_record(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            field: row.get(field)
            for field in (
                "sequence",
                "update_key",
                "receipt_hash",
                "finalized_outcome_digest",
                "parent_policy_fingerprint",
                "child_policy_fingerprint",
                "disposition",
                "checkpoint_id",
                "checkpoint_path",
                "checkpoint_sha256",
                "training_partition_digest",
                "recorded_utc",
                "previous_chain_hash",
            )
        }

    @staticmethod
    def _archive_binding_record(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": PPO_RECEIPT_ARCHIVE_BINDING_SCHEMA_VERSION,
            "sequence": row.get("sequence"),
            "ledger_chain_hash": row.get("ledger_chain_hash"),
            "receipt_hash": row.get("receipt_hash"),
            "trainer_consumed_event_hash": row.get(
                "trainer_consumed_event_hash"
            ),
            "previous_binding_chain_hash": row.get(
                "previous_binding_chain_hash"
            ),
        }

    def verify_integrity(self) -> dict[str, Any]:
        with self._connect() as connection:
            metadata = {
                str(row["key"]): str(row["value"])
                for row in connection.execute("SELECT key, value FROM metadata")
            }
            rows = connection.execute(
                "SELECT * FROM ppo_attempts ORDER BY sequence ASC"
            ).fetchall()
        reasons: list[str] = []
        if metadata.get("schema_version") != PPO_CONSUMPTION_LEDGER_SCHEMA_VERSION:
            reasons.append("PPO_LEDGER_SCHEMA_VERSION_MISMATCH")
        expected_previous = "0" * 64
        for expected_sequence, row in enumerate(rows, start=1):
            material = dict(row)
            if int(material["sequence"]) != expected_sequence:
                reasons.append("PPO_LEDGER_SEQUENCE_GAP")
                break
            if material["previous_chain_hash"] != expected_previous:
                reasons.append("PPO_LEDGER_PREVIOUS_CHAIN_MISMATCH")
                break
            expected_chain = canonical_digest(self._semantic_record(material))
            if material["chain_hash"] != expected_chain:
                reasons.append("PPO_LEDGER_CHAIN_HASH_MISMATCH")
                break
            expected_previous = expected_chain
        if int(metadata.get("row_count") or -1) != len(rows):
            reasons.append("PPO_LEDGER_ROW_COUNT_MISMATCH")
        if metadata.get("chain_tip") != expected_previous:
            reasons.append("PPO_LEDGER_CHAIN_TIP_MISMATCH")
        return {
            "schema_version": PPO_CONSUMPTION_LEDGER_SCHEMA_VERSION,
            "integrity_verified": not reasons,
            "integrity_rejection_reasons": reasons,
            "row_count": len(rows),
            "chain_tip": expected_previous,
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }

    def consumed_update_keys(self) -> set[str]:
        integrity = self.verify_integrity()
        if integrity["integrity_verified"] is not True:
            raise RuntimeError(
                "ppo_consumption_ledger_integrity_failed:"
                + ",".join(integrity["integrity_rejection_reasons"])
            )
        with self._connect() as connection:
            return {
                str(row[0])
                for row in connection.execute("SELECT update_key FROM ppo_attempts")
            }

    def attempt_rows(
        self,
        update_keys: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return integrity-verified terminal attempts in causal ledger order."""

        integrity = self.verify_integrity()
        if integrity["integrity_verified"] is not True:
            raise RuntimeError(
                "ppo_consumption_ledger_integrity_failed:"
                + ",".join(integrity["integrity_rejection_reasons"])
            )
        keys = (
            None
            if update_keys is None
            else list(dict.fromkeys(str(value) for value in update_keys))
        )
        if keys is not None and any(len(value) != 64 for value in keys):
            raise ValueError("ppo_attempt_lookup_update_key_invalid")
        with self._connect() as connection:
            if keys is None:
                rows = connection.execute(
                    "SELECT * FROM ppo_attempts ORDER BY sequence ASC"
                ).fetchall()
            else:
                rows = []
                for key in keys:
                    row = connection.execute(
                        "SELECT * FROM ppo_attempts WHERE update_key = ?",
                        (key,),
                    ).fetchone()
                    if row is not None:
                        rows.append(row)
                rows.sort(key=lambda row: int(row["sequence"]))
        return [dict(row) for row in rows]

    def archive_sync_status(self) -> dict[str, Any]:
        """Verify the durable receipt-archive activation and sync watermark."""

        integrity = self.verify_integrity()
        reasons = list(integrity.get("integrity_rejection_reasons") or ())
        with self._connect() as connection:
            metadata = {
                str(row["key"]): str(row["value"])
                for row in connection.execute("SELECT key, value FROM metadata")
            }
            attempts_by_sequence = {
                int(row["sequence"]): dict(row)
                for row in connection.execute(
                    "SELECT sequence, chain_hash, receipt_hash FROM ppo_attempts"
                )
            }
            binding_rows = [
                dict(row)
                for row in connection.execute(
                    "SELECT * FROM ppo_archive_sync_bindings "
                    "ORDER BY sequence ASC"
                )
            ]
        if metadata.get("receipt_archive_sync_schema_version") != (
            PPO_RECEIPT_ARCHIVE_SYNC_SCHEMA_VERSION
        ):
            reasons.append("PPO_RECEIPT_ARCHIVE_SYNC_SCHEMA_MISMATCH")
        try:
            activation = int(metadata["receipt_archive_activation_sequence"])
            sync_sequence = int(metadata["receipt_archive_sync_sequence"])
        except (KeyError, TypeError, ValueError, OverflowError):
            activation = -1
            sync_sequence = -1
            reasons.append("PPO_RECEIPT_ARCHIVE_SYNC_SEQUENCE_INVALID")
        row_count = int(integrity.get("row_count") or 0)
        if activation < 1 or activation > row_count + 1:
            reasons.append("PPO_RECEIPT_ARCHIVE_ACTIVATION_SEQUENCE_INVALID")
        if sync_sequence < activation - 1 or sync_sequence > row_count:
            reasons.append("PPO_RECEIPT_ARCHIVE_SYNC_WATERMARK_INVALID")
        expected_chain_hash = (
            "0" * 64
            if sync_sequence == 0
            else (
                attempts_by_sequence.get(sync_sequence) or {}
            ).get("chain_hash")
        )
        observed_chain_hash = metadata.get("receipt_archive_sync_chain_hash")
        if expected_chain_hash is None or observed_chain_hash != expected_chain_hash:
            reasons.append("PPO_RECEIPT_ARCHIVE_SYNC_CHAIN_HASH_MISMATCH")
        expected_binding_count = max(0, sync_sequence - activation + 1)
        if len(binding_rows) != expected_binding_count:
            reasons.append("PPO_RECEIPT_ARCHIVE_SYNC_BINDING_COUNT_MISMATCH")
        expected_binding_previous = "0" * 64
        for expected_sequence, binding in zip(
            range(activation, sync_sequence + 1),
            binding_rows,
            strict=False,
        ):
            attempt = attempts_by_sequence.get(expected_sequence)
            if (
                int(binding.get("sequence") or -1) != expected_sequence
                or attempt is None
            ):
                reasons.append("PPO_RECEIPT_ARCHIVE_SYNC_BINDING_SEQUENCE_GAP")
                break
            if binding.get("ledger_chain_hash") != attempt.get("chain_hash"):
                reasons.append(
                    "PPO_RECEIPT_ARCHIVE_SYNC_BINDING_LEDGER_HASH_MISMATCH"
                )
                break
            if binding.get("receipt_hash") != attempt.get("receipt_hash"):
                reasons.append(
                    "PPO_RECEIPT_ARCHIVE_SYNC_BINDING_RECEIPT_HASH_MISMATCH"
                )
                break
            if binding.get("previous_binding_chain_hash") != (
                expected_binding_previous
            ):
                reasons.append(
                    "PPO_RECEIPT_ARCHIVE_SYNC_BINDING_PREVIOUS_HASH_MISMATCH"
                )
                break
            event_hash = str(binding.get("trainer_consumed_event_hash") or "")
            if not _sha256_hex(event_hash):
                reasons.append(
                    "PPO_RECEIPT_ARCHIVE_SYNC_BINDING_EVENT_HASH_INVALID"
                )
                break
            expected_binding_hash = canonical_digest(
                self._archive_binding_record(binding)
            )
            if binding.get("binding_chain_hash") != expected_binding_hash:
                reasons.append("PPO_RECEIPT_ARCHIVE_SYNC_BINDING_HASH_MISMATCH")
                break
            expected_binding_previous = expected_binding_hash
        observed_binding_tip = metadata.get(
            "receipt_archive_sync_binding_chain_tip"
        )
        if observed_binding_tip != expected_binding_previous:
            reasons.append("PPO_RECEIPT_ARCHIVE_SYNC_BINDING_TIP_MISMATCH")
        state = {
            "schema_version": PPO_RECEIPT_ARCHIVE_SYNC_SCHEMA_VERSION,
            "activation_sequence": activation,
            "sync_sequence": sync_sequence,
            "sync_chain_hash": observed_chain_hash,
            "binding_chain_tip": observed_binding_tip,
        }
        try:
            expected_state_digest = canonical_digest(state)
        except (TypeError, ValueError):
            expected_state_digest = ""
            reasons.append("PPO_RECEIPT_ARCHIVE_SYNC_STATE_NOT_CANONICAL")
        if metadata.get("receipt_archive_sync_state_digest") != expected_state_digest:
            reasons.append("PPO_RECEIPT_ARCHIVE_SYNC_STATE_DIGEST_MISMATCH")
        reasons = list(dict.fromkeys(reasons))
        return {
            "schema_version": PPO_RECEIPT_ARCHIVE_SYNC_SCHEMA_VERSION,
            "archive_sync_integrity_verified": not reasons,
            "archive_sync_rejection_reasons": reasons,
            "activation_sequence": activation,
            "sync_sequence": sync_sequence,
            "sync_chain_hash": observed_chain_hash,
            "sync_state_digest": metadata.get(
                "receipt_archive_sync_state_digest"
            ),
            "binding_chain_tip": observed_binding_tip,
            "archive_event_binding_count": len(binding_rows),
            "ledger_row_count": row_count,
            "legacy_terminal_attempts_not_archive_bound": max(0, activation - 1),
            "unsynced_terminal_attempts": max(0, row_count - sync_sequence),
            "paper_only": True,
            "routes_to_live": False,
            "places_real_order": False,
        }

    def archive_sync_bindings(self) -> list[dict[str, Any]]:
        """Return every integrity-verified archive event binding in order."""

        status = self.archive_sync_status()
        if status["archive_sync_integrity_verified"] is not True:
            raise RuntimeError(
                "ppo_receipt_archive_sync_integrity_failed:"
                + ",".join(status["archive_sync_rejection_reasons"])
            )
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT b.*, a.update_key, a.finalized_outcome_digest, "
                "a.child_policy_fingerprint, a.disposition, a.checkpoint_id, "
                "a.recorded_utc "
                "FROM ppo_archive_sync_bindings AS b "
                "JOIN ppo_attempts AS a ON a.sequence = b.sequence "
                "ORDER BY b.sequence ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def unsynced_attempt_rows(self) -> list[dict[str, Any]]:
        """Return only post-activation attempts after the verified watermark."""

        status = self.archive_sync_status()
        if status["archive_sync_integrity_verified"] is not True:
            raise RuntimeError(
                "ppo_receipt_archive_sync_integrity_failed:"
                + ",".join(status["archive_sync_rejection_reasons"])
            )
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM ppo_attempts WHERE sequence > ? "
                "ORDER BY sequence ASC",
                (int(status["sync_sequence"]),),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_archive_synced(
        self,
        *,
        sequence: int,
        chain_hash: str,
        receipt_hash: str,
        trainer_consumed_event_hash: str,
    ) -> dict[str, Any]:
        """Advance only with an exact immutable TRAINER_CONSUMED event binding."""

        status = self.archive_sync_status()
        if status["archive_sync_integrity_verified"] is not True:
            raise RuntimeError("ppo_receipt_archive_sync_integrity_failed")
        requested_sequence = int(sequence)
        requested_chain_hash = str(chain_hash or "")
        requested_receipt_hash = str(receipt_hash or "")
        requested_event_hash = str(trainer_consumed_event_hash or "")
        if not all(
            _sha256_hex(value)
            for value in (
                requested_chain_hash,
                requested_receipt_hash,
                requested_event_hash,
            )
        ):
            raise ValueError("ppo_receipt_archive_sync_binding_hash_invalid")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            metadata = {
                str(row["key"]): str(row["value"])
                for row in connection.execute("SELECT key, value FROM metadata")
            }
            current_sequence = int(metadata["receipt_archive_sync_sequence"])
            current_hash = metadata["receipt_archive_sync_chain_hash"]
            if requested_sequence == current_sequence:
                existing = connection.execute(
                    "SELECT * FROM ppo_archive_sync_bindings WHERE sequence = ?",
                    (requested_sequence,),
                ).fetchone()
                if (
                    requested_chain_hash != current_hash
                    or existing is None
                    or str(existing["ledger_chain_hash"])
                    != requested_chain_hash
                    or str(existing["receipt_hash"]) != requested_receipt_hash
                    or str(existing["trainer_consumed_event_hash"])
                    != requested_event_hash
                ):
                    raise RuntimeError(
                        "ppo_receipt_archive_sync_idempotent_hash_conflict"
                    )
                connection.commit()
                return {**status, "watermark_advanced": False}
            if requested_sequence != current_sequence + 1:
                raise RuntimeError("ppo_receipt_archive_sync_sequence_not_contiguous")
            row = connection.execute(
                "SELECT chain_hash, receipt_hash FROM ppo_attempts "
                "WHERE sequence = ?",
                (requested_sequence,),
            ).fetchone()
            if (
                row is None
                or str(row["chain_hash"]) != requested_chain_hash
                or str(row["receipt_hash"]) != requested_receipt_hash
            ):
                raise RuntimeError("ppo_receipt_archive_sync_attempt_hash_mismatch")
            activation = int(metadata["receipt_archive_activation_sequence"])
            if requested_sequence < activation:
                raise RuntimeError("ppo_receipt_archive_sync_before_activation")
            previous_binding_chain_hash = metadata[
                "receipt_archive_sync_binding_chain_tip"
            ]
            binding_record = {
                "sequence": requested_sequence,
                "ledger_chain_hash": requested_chain_hash,
                "receipt_hash": requested_receipt_hash,
                "trainer_consumed_event_hash": requested_event_hash,
                "previous_binding_chain_hash": previous_binding_chain_hash,
            }
            binding_chain_hash = canonical_digest(
                self._archive_binding_record(binding_record)
            )
            connection.execute(
                "INSERT INTO ppo_archive_sync_bindings("
                "sequence, ledger_chain_hash, receipt_hash, "
                "trainer_consumed_event_hash, previous_binding_chain_hash, "
                "binding_chain_hash) VALUES(?, ?, ?, ?, ?, ?)",
                (
                    requested_sequence,
                    requested_chain_hash,
                    requested_receipt_hash,
                    requested_event_hash,
                    previous_binding_chain_hash,
                    binding_chain_hash,
                ),
            )
            state = {
                "schema_version": PPO_RECEIPT_ARCHIVE_SYNC_SCHEMA_VERSION,
                "activation_sequence": activation,
                "sync_sequence": requested_sequence,
                "sync_chain_hash": requested_chain_hash,
                "binding_chain_tip": binding_chain_hash,
            }
            connection.execute(
                "UPDATE metadata SET value = ? "
                "WHERE key = 'receipt_archive_sync_sequence'",
                (str(requested_sequence),),
            )
            connection.execute(
                "UPDATE metadata SET value = ? "
                "WHERE key = 'receipt_archive_sync_chain_hash'",
                (requested_chain_hash,),
            )
            connection.execute(
                "UPDATE metadata SET value = ? "
                "WHERE key = 'receipt_archive_sync_binding_chain_tip'",
                (binding_chain_hash,),
            )
            connection.execute(
                "UPDATE metadata SET value = ? "
                "WHERE key = 'receipt_archive_sync_state_digest'",
                (canonical_digest(state),),
            )
            connection.commit()
        updated = self.archive_sync_status()
        if updated["archive_sync_integrity_verified"] is not True:
            raise RuntimeError("ppo_receipt_archive_sync_post_commit_invalid")
        return {**updated, "watermark_advanced": True}

    def claims_for_update_keys(
        self,
        update_keys: Sequence[str],
    ) -> list[dict[str, Any]]:
        """Read exact claim semantics in caller-supplied update-key order."""
        keys = list(dict.fromkeys(str(value) for value in update_keys))
        if any(len(value) != 64 for value in keys):
            raise ValueError("ppo_claim_lookup_update_key_invalid")
        integrity = self.verify_integrity()
        if integrity["integrity_verified"] is not True:
            raise RuntimeError("ppo_consumption_ledger_integrity_failed")
        if not keys:
            return []
        with self._connect() as connection:
            rows: dict[str, dict[str, Any]] = {}
            for key in keys:
                row = connection.execute(
                    "SELECT * FROM ppo_claims WHERE update_key = ?",
                    (key,),
                ).fetchone()
                if row is not None:
                    rows[key] = dict(row)
        return [rows[key] for key in keys if key in rows]

    def reconcile_verified_checkpoint_attempts(
        self,
        *,
        checkpoint_load: Mapping[str, Any],
        disposition: str,
    ) -> dict[str, Any]:
        """Commit orphaned claims already present in one durable checkpoint.

        This closes the crash window between atomically persisting a child model
        and appending its optimizer-attempt rows to SQLite.  It must run before
        orphan-claim recovery.  A missing claim or a still-live owner fails
        closed; neither condition permits silently applying an update twice.
        """

        artifact_proven_without_mutation = bool(
            checkpoint_load.get("checkpoint_artifact_verified") is True
            and checkpoint_load.get("verification_is_non_mutating") is True
        )
        artifact_proven_by_reload = bool(
            checkpoint_load.get("latest_checkpoint_loadable") is True
            and checkpoint_load.get("model_state_restored") is True
        )
        required_truths = (
            "weight_file_sha256_verified",
            "model_parameter_fingerprint_verified",
            "checkpoint_evidence_verified",
            "checkpoint_identity_verified",
        )
        if (
            not (artifact_proven_without_mutation or artifact_proven_by_reload)
            or any(checkpoint_load.get(field) is not True for field in required_truths)
        ):
            raise RuntimeError("ppo_reconciliation_checkpoint_not_fully_verified")
        update_keys = list(
            dict.fromkeys(
                str(value)
                for value in (checkpoint_load.get("consumed_ppo_update_keys") or ())
            )
        )
        if any(len(value) != 64 for value in update_keys):
            raise RuntimeError("ppo_reconciliation_checkpoint_update_key_invalid")
        expected_partition = training_partition_digest(update_keys)
        partition = str(checkpoint_load.get("training_partition_digest") or "")
        if partition != expected_partition:
            raise RuntimeError("ppo_reconciliation_training_partition_digest_mismatch")
        if not update_keys:
            return {
                "checkpoint_consumed_update_keys": 0,
                "already_recorded_update_keys": 0,
                "reconciled_update_keys": 0,
            }

        child_fingerprint = str(
            checkpoint_load.get("model_parameter_fingerprint") or ""
        )
        checkpoint_id = str(checkpoint_load.get("checkpoint_id") or "")
        checkpoint_path = str(
            checkpoint_load.get("resolved_weight_file_path")
            or checkpoint_load.get("weight_file_path")
            or ""
        )
        checkpoint_sha256 = str(checkpoint_load.get("weight_file_sha256") or "")
        if (
            len(child_fingerprint) != 64
            or not checkpoint_id
            or not checkpoint_path
            or len(checkpoint_sha256) != 64
        ):
            raise RuntimeError("ppo_reconciliation_checkpoint_binding_incomplete")

        with self._connect() as connection:
            existing_rows: dict[str, dict[str, Any]] = {}
            for key in update_keys:
                row = connection.execute(
                    "SELECT * FROM ppo_attempts WHERE update_key = ?",
                    (key,),
                ).fetchone()
                if row is not None:
                    existing_rows[key] = dict(row)
        for row in existing_rows.values():
            for field, expected in (
                ("child_policy_fingerprint", child_fingerprint),
                ("disposition", str(disposition)),
                ("checkpoint_id", checkpoint_id),
                ("checkpoint_sha256", checkpoint_sha256),
                ("training_partition_digest", partition),
            ):
                if row.get(field) != expected:
                    raise RuntimeError(
                        "ppo_reconciliation_existing_attempt_checkpoint_conflict"
                    )

        pending_keys = [key for key in update_keys if key not in existing_rows]
        claims = self.claims_for_update_keys(pending_keys)
        claims_by_key = {str(claim["update_key"]): claim for claim in claims}
        if set(claims_by_key) != set(pending_keys):
            raise RuntimeError("ppo_reconciliation_orphan_claim_missing")
        attempts_by_owner: dict[str, list[dict[str, Any]]] = {}
        for key in pending_keys:
            claim = claims_by_key[key]
            owner_id = str(claim["owner_id"])
            if self._owner_is_alive(owner_id):
                raise RuntimeError("ppo_reconciliation_claim_owner_still_alive")
            if (
                claim.get("optimizer_started_utc") in (None, "")
                or claim.get("optimizer_partition_digest") != partition
                or _nonnegative_int(claim.get("optimizer_partition_index"))
                != update_keys.index(key)
            ):
                raise RuntimeError(
                    "ppo_reconciliation_optimizer_write_ahead_fence_missing"
                )
            attempts_by_owner.setdefault(owner_id, []).append(
                {
                    "update_key": key,
                    "receipt_hash": str(claim["receipt_hash"]),
                    "finalized_outcome_digest": str(
                        claim["finalized_outcome_digest"]
                    ),
                    "parent_policy_fingerprint": str(
                        claim["parent_policy_fingerprint"]
                    ),
                }
            )
        inserted = 0
        for owner_id, attempts in attempts_by_owner.items():
            result = self.record_attempts(
                attempts=attempts,
                child_policy_fingerprint=child_fingerprint,
                disposition=disposition,
                checkpoint_id=checkpoint_id,
                checkpoint_path=checkpoint_path,
                checkpoint_sha256=checkpoint_sha256,
                partition_digest=partition,
                owner_id=owner_id,
            )
            inserted += int(result.get("attempts_inserted") or 0)
        return {
            "checkpoint_consumed_update_keys": len(update_keys),
            "already_recorded_update_keys": len(existing_rows),
            "reconciled_update_keys": inserted,
        }

    @staticmethod
    def process_owner_id() -> str:
        """Return a host-local process identity immune to PID reuse."""
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(
            encoding="utf-8"
        ).strip()
        stat_fields = Path(f"/proc/{os.getpid()}/stat").read_text(
            encoding="utf-8"
        ).split()
        process_start_ticks = stat_fields[21]
        return f"{boot_id}:{os.getpid()}:{process_start_ticks}"

    @staticmethod
    def _owner_is_alive(owner_id: str) -> bool:
        parts = str(owner_id).split(":")
        if len(parts) != 3:
            return False
        boot_id, pid_text, start_ticks = parts
        try:
            current_boot = Path("/proc/sys/kernel/random/boot_id").read_text(
                encoding="utf-8"
            ).strip()
            stat_fields = Path(f"/proc/{int(pid_text)}/stat").read_text(
                encoding="utf-8"
            ).split()
        except (OSError, ValueError):
            return False
        return (
            current_boot == boot_id
            and len(stat_fields) > 21
            and stat_fields[21] == start_ticks
        )

    def recover_orphaned_claims(self) -> dict[str, int]:
        """Release only dead claims which never crossed the optimizer WAL fence."""
        released = 0
        active = 0
        optimizer_started_preserved = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            claims = connection.execute(
                "SELECT update_key, owner_id, optimizer_started_utc FROM ppo_claims"
            ).fetchall()
            for claim in claims:
                if self._owner_is_alive(str(claim["owner_id"])):
                    active += 1
                    continue
                if claim["optimizer_started_utc"] not in (None, ""):
                    optimizer_started_preserved += 1
                    continue
                connection.execute(
                    "DELETE FROM ppo_claims WHERE update_key = ?",
                    (claim["update_key"],),
                )
                released += 1
            connection.commit()
        return {
            "orphaned_claims_released": released,
            "active_claims_preserved": active,
            "optimizer_started_claims_preserved": optimizer_started_preserved,
        }

    def mark_optimizer_started(
        self,
        *,
        owner_id: str,
        update_keys: Sequence[str],
        partition_digest: str,
    ) -> dict[str, Any]:
        """Durably cross the no-replay fence immediately before optimizer entry."""
        keys = [str(value) for value in update_keys]
        if not keys or len(set(keys)) != len(keys):
            raise ValueError("ppo_optimizer_fence_keys_empty_or_duplicate")
        if training_partition_digest(keys) != str(partition_digest):
            raise ValueError("ppo_optimizer_fence_partition_digest_mismatch")
        started_utc = _utc_iso()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for index, key in enumerate(keys):
                claim = connection.execute(
                    "SELECT * FROM ppo_claims WHERE update_key = ?",
                    (key,),
                ).fetchone()
                if claim is None or str(claim["owner_id"]) != owner_id:
                    raise RuntimeError("ppo_optimizer_fence_claim_not_owned")
                if claim["optimizer_started_utc"] not in (None, ""):
                    if (
                        claim["optimizer_partition_digest"] != partition_digest
                        or _nonnegative_int(claim["optimizer_partition_index"])
                        != index
                    ):
                        raise RuntimeError("ppo_optimizer_fence_semantic_conflict")
                    continue
                connection.execute(
                    """
                    UPDATE ppo_claims
                    SET optimizer_started_utc = ?,
                        optimizer_partition_digest = ?,
                        optimizer_partition_index = ?
                    WHERE update_key = ? AND owner_id = ?
                    """,
                    (started_utc, partition_digest, index, key, owner_id),
                )
            connection.commit()
        return {
            "optimizer_write_ahead_fence_durable": True,
            "optimizer_started_utc": started_utc,
            "training_partition_digest": partition_digest,
            "ordered_update_keys": keys,
        }

    def release_optimizer_fence_without_step(
        self,
        *,
        owner_id: str,
        update_keys: Sequence[str],
        partition_digest: str,
    ) -> int:
        """Release a fenced partition after synchronous proof of zero updates."""
        keys = [str(value) for value in update_keys]
        if not keys or training_partition_digest(keys) != partition_digest:
            raise ValueError("ppo_no_step_release_partition_invalid")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for index, key in enumerate(keys):
                claim = connection.execute(
                    "SELECT * FROM ppo_claims WHERE update_key = ?",
                    (key,),
                ).fetchone()
                if (
                    claim is None
                    or str(claim["owner_id"]) != owner_id
                    or claim["optimizer_started_utc"] in (None, "")
                    or claim["optimizer_partition_digest"] != partition_digest
                    or _nonnegative_int(claim["optimizer_partition_index"])
                    != index
                ):
                    raise RuntimeError("ppo_no_step_release_fence_mismatch")
            released = 0
            for key in keys:
                cursor = connection.execute(
                    "DELETE FROM ppo_claims WHERE update_key = ? AND owner_id = ?",
                    (key, owner_id),
                )
                released += max(0, int(cursor.rowcount))
            connection.commit()
        return released

    def record_ambiguous_dead_optimizer_attempts(self) -> dict[str, int]:
        """Consume dead post-fence claims when no child artifact can prove state.

        A crash after the durable fence but before checkpoint persistence cannot
        reveal whether the first optimizer kernel ran.  Replaying those rows can
        apply an update twice, so recovery records a deliberately conservative,
        non-serving terminal disposition.  The parent fingerprint is retained in
        the legacy child-fingerprint column and the disposition states that the
        post-update child is unknown.
        """
        with self._connect() as connection:
            rows = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT * FROM ppo_claims
                    WHERE optimizer_started_utc IS NOT NULL
                    ORDER BY owner_id, optimizer_partition_digest,
                             optimizer_partition_index
                    """
                )
            ]
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        active_claims = 0
        for row in rows:
            owner_id = str(row["owner_id"])
            if self._owner_is_alive(owner_id):
                active_claims += 1
                continue
            partition = str(row.get("optimizer_partition_digest") or "")
            grouped.setdefault((owner_id, partition), []).append(row)

        consumed = 0
        for (owner_id, partition), claims in grouped.items():
            claims.sort(key=lambda row: int(row["optimizer_partition_index"]))
            keys = [str(row["update_key"]) for row in claims]
            indices = [
                _nonnegative_int(row.get("optimizer_partition_index"))
                for row in claims
            ]
            if (
                len(partition) != 64
                or indices != list(range(len(claims)))
                or training_partition_digest(keys) != partition
            ):
                raise RuntimeError("ppo_ambiguous_optimizer_partition_corrupt")
            parent_fingerprints = {
                str(row["parent_policy_fingerprint"]) for row in claims
            }
            if len(parent_fingerprints) != 1:
                raise RuntimeError("ppo_ambiguous_optimizer_parent_mixed")
            attempts = [
                {
                    "update_key": row["update_key"],
                    "receipt_hash": row["receipt_hash"],
                    "finalized_outcome_digest": row["finalized_outcome_digest"],
                    "parent_policy_fingerprint": row[
                        "parent_policy_fingerprint"
                    ],
                }
                for row in claims
            ]
            result = self.record_attempts(
                attempts=attempts,
                child_policy_fingerprint=next(iter(parent_fingerprints)),
                disposition=(
                    "CRASH_AMBIGUOUS_OPTIMIZER_ATTEMPT_CONSUMED_FAIL_CLOSED"
                ),
                checkpoint_id=None,
                checkpoint_path=None,
                checkpoint_sha256=None,
                partition_digest=partition,
                owner_id=owner_id,
            )
            consumed += int(result.get("attempts_inserted") or 0)
        return {
            "ambiguous_optimizer_attempts_consumed": consumed,
            "active_optimizer_started_claims_preserved": active_claims,
        }

    def claim_attempts(
        self,
        *,
        attempts: Sequence[Mapping[str, Any]],
        owner_id: str,
    ) -> dict[str, Any]:
        """Atomically fence exact optimizer inputs across trainer processes."""
        claimed: list[str] = []
        unavailable: list[str] = []
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for attempt in attempts:
                update_key = str(attempt.get("update_key") or "")
                receipt_hash = str(attempt.get("receipt_hash") or "")
                outcome_digest = str(attempt.get("finalized_outcome_digest") or "")
                parent_fingerprint = str(
                    attempt.get("parent_policy_fingerprint") or ""
                )
                expected_key = ppo_consumption_update_key(
                    receipt_hash=receipt_hash,
                    finalized_outcome_digest=outcome_digest,
                    parent_policy_fingerprint=parent_fingerprint,
                )
                if update_key != expected_key:
                    raise ValueError("ppo_claim_update_key_binding_mismatch")
                consumed = connection.execute(
                    "SELECT 1 FROM ppo_attempts WHERE update_key = ?",
                    (update_key,),
                ).fetchone()
                if consumed is not None:
                    unavailable.append(update_key)
                    continue
                existing = connection.execute(
                    "SELECT owner_id, optimizer_started_utc FROM ppo_claims "
                    "WHERE update_key = ?",
                    (update_key,),
                ).fetchone()
                if existing is not None:
                    if (
                        str(existing["owner_id"]) != owner_id
                        or existing["optimizer_started_utc"] not in (None, "")
                    ):
                        unavailable.append(update_key)
                        continue
                    claimed.append(update_key)
                    continue
                connection.execute(
                    """
                    INSERT OR IGNORE INTO ppo_claims(
                        update_key, owner_id, receipt_hash,
                        finalized_outcome_digest, parent_policy_fingerprint,
                        claimed_utc
                    ) VALUES(?, ?, ?, ?, ?, ?)
                    """,
                    (
                        update_key,
                        owner_id,
                        receipt_hash,
                        outcome_digest,
                        parent_fingerprint,
                        _utc_iso(),
                    ),
                )
                claimed.append(update_key)
            connection.commit()
        return {
            "owner_id": owner_id,
            "claimed_update_keys": claimed,
            "unavailable_update_keys": unavailable,
        }

    def release_claims(self, *, owner_id: str, update_keys: Sequence[str]) -> int:
        """Release pre-optimizer reservations; post-fence claims are irreversible."""
        if not update_keys:
            return 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            released = 0
            for update_key in update_keys:
                cursor = connection.execute(
                    "DELETE FROM ppo_claims WHERE update_key = ? AND owner_id = ? "
                    "AND optimizer_started_utc IS NULL",
                    (str(update_key), owner_id),
                )
                released += max(0, int(cursor.rowcount))
            connection.commit()
        return released

    def record_attempts(
        self,
        *,
        attempts: Sequence[Mapping[str, Any]],
        child_policy_fingerprint: str,
        disposition: str,
        checkpoint_id: str | None,
        checkpoint_path: str | None,
        checkpoint_sha256: str | None,
        partition_digest: str,
        owner_id: str | None = None,
    ) -> dict[str, Any]:
        if len(child_policy_fingerprint) != 64 or len(partition_digest) != 64:
            raise ValueError("ppo_ledger_fingerprint_or_partition_digest_invalid")
        if checkpoint_path in (None, ""):
            if checkpoint_id not in (None, "") or checkpoint_sha256 not in (None, ""):
                raise ValueError("ppo_ledger_checkpoint_identity_without_artifact")
        elif (
            checkpoint_id in (None, "")
            or checkpoint_sha256 in (None, "")
            or len(str(checkpoint_sha256)) != 64
        ):
            raise ValueError("ppo_ledger_durable_checkpoint_binding_incomplete")
        if checkpoint_path not in (None, ""):
            path = Path(str(checkpoint_path))
            if not path.is_file() or not checkpoint_sha256:
                raise RuntimeError("ppo_ledger_checkpoint_artifact_not_durable")
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != checkpoint_sha256:
                raise RuntimeError("ppo_ledger_checkpoint_sha256_mismatch")

        inserted = 0
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            metadata = {
                str(row["key"]): str(row["value"])
                for row in connection.execute("SELECT key, value FROM metadata")
            }
            sequence = int(metadata.get("row_count") or 0)
            chain_tip = metadata.get("chain_tip") or "0" * 64
            ordered_attempts = list(attempts)
            for attempt_index, attempt in enumerate(ordered_attempts):
                update_key = str(attempt.get("update_key") or "")
                receipt_hash = str(attempt.get("receipt_hash") or "")
                outcome_digest = str(attempt.get("finalized_outcome_digest") or "")
                parent_fingerprint = str(
                    attempt.get("parent_policy_fingerprint") or ""
                )
                expected_key = ppo_consumption_update_key(
                    receipt_hash=receipt_hash,
                    finalized_outcome_digest=outcome_digest,
                    parent_policy_fingerprint=parent_fingerprint,
                )
                if update_key != expected_key:
                    raise ValueError("ppo_ledger_update_key_binding_mismatch")
                existing = connection.execute(
                    "SELECT * FROM ppo_attempts WHERE update_key = ?",
                    (update_key,),
                ).fetchone()
                if existing is not None:
                    comparable = dict(existing)
                    for field, expected in (
                        ("receipt_hash", receipt_hash),
                        ("finalized_outcome_digest", outcome_digest),
                        ("parent_policy_fingerprint", parent_fingerprint),
                        ("child_policy_fingerprint", child_policy_fingerprint),
                        ("disposition", str(disposition)),
                        ("checkpoint_id", checkpoint_id),
                        ("checkpoint_path", checkpoint_path),
                        ("checkpoint_sha256", checkpoint_sha256),
                        ("training_partition_digest", partition_digest),
                    ):
                        actual_normalized = comparable.get(field)
                        if actual_normalized == "":
                            actual_normalized = None
                        expected_normalized = expected
                        if expected_normalized == "":
                            expected_normalized = None
                        if actual_normalized != expected_normalized:
                            raise RuntimeError("ppo_ledger_stable_key_semantic_conflict")
                    if owner_id:
                        connection.execute(
                            "DELETE FROM ppo_claims "
                            "WHERE update_key = ? AND owner_id = ?",
                            (update_key, owner_id),
                        )
                    continue
                if not owner_id:
                    raise RuntimeError("ppo_ledger_new_attempt_requires_claim_owner")
                claim = connection.execute(
                    "SELECT * FROM ppo_claims WHERE update_key = ?",
                    (update_key,),
                ).fetchone()
                if claim is None or str(claim["owner_id"]) != owner_id:
                    raise RuntimeError("ppo_ledger_attempt_not_owned_by_recorder")
                if (
                    claim["optimizer_started_utc"] in (None, "")
                    or claim["optimizer_partition_digest"] != partition_digest
                    or _nonnegative_int(claim["optimizer_partition_index"])
                    != attempt_index
                ):
                    raise RuntimeError(
                        "ppo_ledger_optimizer_write_ahead_fence_missing"
                    )
                for field, expected in (
                    ("receipt_hash", receipt_hash),
                    ("finalized_outcome_digest", outcome_digest),
                    ("parent_policy_fingerprint", parent_fingerprint),
                ):
                    if str(claim[field]) != expected:
                        raise RuntimeError("ppo_ledger_claim_semantic_conflict")
                sequence += 1
                recorded_utc = _utc_iso()
                semantic = {
                    "sequence": sequence,
                    "update_key": update_key,
                    "receipt_hash": receipt_hash,
                    "finalized_outcome_digest": outcome_digest,
                    "parent_policy_fingerprint": parent_fingerprint,
                    "child_policy_fingerprint": child_policy_fingerprint,
                    "disposition": str(disposition),
                    "checkpoint_id": checkpoint_id,
                    "checkpoint_path": checkpoint_path,
                    "checkpoint_sha256": checkpoint_sha256,
                    "training_partition_digest": partition_digest,
                    "recorded_utc": recorded_utc,
                    "previous_chain_hash": chain_tip,
                }
                chain_hash = canonical_digest(semantic)
                connection.execute(
                    """
                    INSERT INTO ppo_attempts(
                        sequence, update_key, receipt_hash,
                        finalized_outcome_digest, parent_policy_fingerprint,
                        child_policy_fingerprint, disposition, checkpoint_id,
                        checkpoint_path, checkpoint_sha256,
                        training_partition_digest, recorded_utc,
                        previous_chain_hash, chain_hash
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sequence,
                        update_key,
                        receipt_hash,
                        outcome_digest,
                        parent_fingerprint,
                        child_policy_fingerprint,
                        str(disposition),
                        checkpoint_id,
                        checkpoint_path,
                        checkpoint_sha256,
                        partition_digest,
                        recorded_utc,
                        chain_tip,
                        chain_hash,
                    ),
                )
                chain_tip = chain_hash
                inserted += 1
                if owner_id:
                    connection.execute(
                        "DELETE FROM ppo_claims WHERE update_key = ? AND owner_id = ?",
                        (update_key, owner_id),
                    )
            connection.execute(
                "UPDATE metadata SET value = ? WHERE key = 'row_count'",
                (str(sequence),),
            )
            connection.execute(
                "UPDATE metadata SET value = ? WHERE key = 'chain_tip'",
                (chain_tip,),
            )
            connection.commit()
        integrity = self.verify_integrity()
        if integrity["integrity_verified"] is not True:
            raise RuntimeError("ppo_consumption_ledger_post_commit_integrity_failed")
        return {**integrity, "attempts_inserted": inserted}
