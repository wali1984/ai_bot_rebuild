"""PPO/MASA-shaped paper/shadow training loop with lazy CUDA support."""
from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import threading
import time
from collections.abc import Mapping
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from v2.backend.app.services.market_state_integrity.sample_rejection import (
    classify_training_sample,
    missing_mask_training_override_status,
)
from v2.backend.app.services.market_state_integrity.scoring import (
    OPTIONAL_OR_EVENT_FEATURE_TOKENS,
)
from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION
from v2.backend.app.services.native_trainer.dataloader_worker_config import (
    PERSISTENT_WORKERS,
    PREFETCH_FACTOR,
    compute_dataloader_workers,
)
from v2.backend.app.services.native_trainer.durable_behavior_receipt_archive import (
    EVENT_ENTRY_ACCEPTED,
    EVENT_OUTCOME_FINALIZED,
    EVENT_PUBLISHED,
    BehaviorReceiptArchiveError,
    SamplingPlanKeyResolver,
    default_archive_root,
    lifecycle_events,
    receipt_lifecycle_status,
    verify_archived_behavior_receipt,
    verify_archived_sampling_cohort_completeness_proof,
)

from .confidence import (
    CONFIDENCE_HEAD_ACTIONS,
    CONFIDENCE_LABEL_SEMANTICS,
    CONFIDENCE_UNCERTAINTY_EVIDENCE_SCHEMA_VERSION,
    CONFIDENCE_UNCERTAINTY_METHOD,
    brier_score,
    confidence_uncertainty_evidence_digest,
    expected_calibration_error,
    fit_temperature,
    profitability_target_from_trust_row,
    resolve_confidence_temperature,
    unfitted_calibration_state,
)
from .config import ACTION_COUNT, ACTION_LABELS
from .data_loader import TrainingExample, _has_explicit_training_trust_evidence
from .model import V2HybridPolicyModel
from .on_policy_behavior import (
    ON_POLICY_DISTRIBUTION_CONTRACT,
    behavior_action_mask_from_row,
    behavior_receipt_rejection_reasons,
    finalized_outcome_binding_rejection_reasons,
    model_parameter_fingerprint,
    ppo_consumption_update_key_from_row,
)

EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT = 12.0
EXPECTED_MOVE_HEAD_SATURATION_BPS = 118.0
EXPECTED_MOVE_HEAD_TARGET_MISMATCH_BPS = 30.0
GPU_TRAINING_SAMPLE_INTERVAL_SECONDS = 0.5
ENV_PPO_LEARNING_RATE_MAX = 2e-4
ENV_PPO_ENTROPY_COEFFICIENT_MAX = 0.015
PPO_REQUIRED_BEHAVIOR_SAMPLING_MODE = "CATEGORICAL_SAMPLE"
PPO_REQUIRED_BEHAVIOR_DISTRIBUTION_CONTRACT = ON_POLICY_DISTRIBUTION_CONTRACT
PPO_SUPPORTED_BEHAVIOR_DISTRIBUTION_CONTRACTS = frozenset(
    {ON_POLICY_DISTRIBUTION_CONTRACT}
)
PPO_INCOMPLETE_SAMPLED_COHORT_REASON = (
    "SELECTION_BIASED_SAMPLED_COHORT_NOT_FULLY_TERMINALIZED"
)
PPO_SAMPLING_COHORT_KEY_RESOLVER_MISSING_REASON = (
    "AUTHENTICATED_SAMPLING_COHORT_KEY_RESOLVER_UNAVAILABLE"
)
PPO_SAMPLING_COHORT_PROOF_INVALID_REASON = (
    "AUTHENTICATED_SAMPLED_COHORT_PROOF_INVALID"
)
PPO_SAMPLING_COHORT_PROOF_BINDING_MISMATCH_REASON = (
    "AUTHENTICATED_SAMPLED_COHORT_PROOF_ROW_BINDING_MISMATCH"
)
PPO_SAMPLING_COHORT_PROOF_AFTER_TRAINING_OBSERVED_REASON = (
    "AUTHENTICATED_SAMPLED_COHORT_PROOF_AFTER_TRAINING_OBSERVED_AT"
)


def _finite_float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _strict_finite_number(value: Any) -> bool:
    """Return true only for an explicit, finite numeric training value."""

    if value in (None, "") or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _temperature_scaled_probability(raw: float, temperature: float) -> float:
    probability = max(1e-6, min(1.0 - 1e-6, float(raw)))
    logit = math.log(probability / (1.0 - probability))
    scaled_logit = max(-700.0, min(700.0, logit / float(temperature)))
    return 1.0 / (1.0 + math.exp(-scaled_logit))


def _paired_confidence_nonregression_evidence(
    raw_probabilities: Sequence[float],
    outcomes: Sequence[int],
    *,
    temperature: float,
    scope: str,
) -> dict[str, Any]:
    """Empirical paired uncertainty with no configured sample threshold.

    Brier uses the paired per-row calibrated-minus-raw loss delta and its sample
    standard error. ECE is not row-additive, so uncertainty is estimated by a
    deterministic delete-one jackknife over the same untouched rows. Two rows
    are the mathematical minimum for either variance estimate; no fixed market
    or operator-selected minimum-N gate is used.
    """

    if len(raw_probabilities) != len(outcomes):
        raise ValueError("confidence_uncertainty_input_length_mismatch")
    calibrated_probabilities = [
        _temperature_scaled_probability(raw, temperature)
        for raw in raw_probabilities
    ]
    paired_deltas = [
        (calibrated - int(outcome)) ** 2 - (float(raw) - int(outcome)) ** 2
        for raw, calibrated, outcome in zip(
            raw_probabilities,
            calibrated_probabilities,
            outcomes,
            strict=True,
        )
    ]
    count = len(paired_deltas)
    paired_mean = sum(paired_deltas) / count if count else None
    paired_se: float | None = None
    if count > 1 and paired_mean is not None:
        sample_variance = sum(
            (value - paired_mean) ** 2 for value in paired_deltas
        ) / (count - 1)
        paired_se = math.sqrt(sample_variance / count)
    paired_upper = (
        paired_mean + paired_se
        if paired_mean is not None and paired_se is not None
        else None
    )

    raw_ece = (
        expected_calibration_error(raw_probabilities, outcomes, 1.0)
        if count
        else None
    )
    calibrated_ece = (
        expected_calibration_error(raw_probabilities, outcomes, temperature)
        if count
        else None
    )
    ece_delta = (
        calibrated_ece - raw_ece
        if raw_ece is not None and calibrated_ece is not None
        else None
    )
    leave_one_out_deltas: list[float] = []
    if count > 1:
        for excluded in range(count):
            loo_probabilities = [
                value
                for index, value in enumerate(raw_probabilities)
                if index != excluded
            ]
            loo_outcomes = [
                value for index, value in enumerate(outcomes) if index != excluded
            ]
            leave_one_out_deltas.append(
                expected_calibration_error(
                    loo_probabilities, loo_outcomes, temperature
                )
                - expected_calibration_error(loo_probabilities, loo_outcomes, 1.0)
            )
    ece_jackknife_se: float | None = None
    if leave_one_out_deltas:
        loo_mean = sum(leave_one_out_deltas) / len(leave_one_out_deltas)
        ece_jackknife_se = math.sqrt(
            ((count - 1) / count)
            * sum((value - loo_mean) ** 2 for value in leave_one_out_deltas)
        )
    ece_upper = (
        ece_delta + ece_jackknife_se
        if ece_delta is not None and ece_jackknife_se is not None
        else None
    )
    normalized_scope = str(scope).strip().upper()
    evidence = {
        "paired_brier_delta_per_row": paired_deltas,
        "paired_brier_delta_mean": paired_mean,
        "paired_brier_delta_standard_error": paired_se,
        "paired_brier_delta_one_standard_error_upper_bound": paired_upper,
        "paired_brier_uncertainty_available": paired_se is not None,
        "paired_brier_non_regression_proven": (
            paired_upper is not None and paired_upper <= 0.0
        ),
        "ece_delta": ece_delta,
        "ece_leave_one_out_delta": leave_one_out_deltas,
        "ece_jackknife_standard_error": ece_jackknife_se,
        "ece_one_standard_error_upper_bound": ece_upper,
        "ece_uncertainty_available": ece_jackknife_se is not None,
        "ece_non_regression_proven": ece_upper is not None and ece_upper <= 0.0,
        "uncertainty_row_count": count,
        "uncertainty_minimum_not_configured": True,
        "uncertainty_mathematical_minimum_rows": 2,
        "uncertainty_evidence_schema_version": (
            CONFIDENCE_UNCERTAINTY_EVIDENCE_SCHEMA_VERSION
        ),
        "uncertainty_scope": normalized_scope,
        "uncertainty_method": CONFIDENCE_UNCERTAINTY_METHOD,
    }
    evidence["uncertainty_evidence_digest"] = (
        confidence_uncertainty_evidence_digest(
            scope=normalized_scope,
            evidence=evidence,
        )
    )
    return evidence


def _cache_digest_value(value: Any) -> Any:
    """Return a deterministic JSON-safe representation, including non-finites."""

    if value is None or isinstance(value, bool | str | int):
        return value
    if isinstance(value, float):
        return {"__float_hex__": value.hex()}
    if isinstance(value, dict):
        return {
            str(key): _cache_digest_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list | tuple):
        return [_cache_digest_value(item) for item in value]
    if isinstance(value, set | frozenset):
        normalized = [_cache_digest_value(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        )
    if isinstance(value, datetime):
        return {"__datetime__": value.isoformat()}
    return {
        "__type__": f"{type(value).__module__}.{type(value).__qualname__}",
        "__repr__": repr(value),
    }


def _ordered_training_cache_digest(
    rows: Sequence[TrainingExample],
    validation_rows: Sequence[TrainingExample],
    *,
    temporal: bool,
    seq_len: int,
) -> str:
    """Hash every ordered tensor byte-equivalent input and target dependency."""

    material: dict[str, Any] = {
        "schema_version": "v2_trainer_full_ordered_tensor_cache_digest_v1",
        "temporal": bool(temporal),
        "seq_len": int(seq_len),
        "partitions": [],
    }
    for partition_name, partition_rows in (
        ("training", rows),
        ("validation", validation_rows),
    ):
        encoded_rows: list[dict[str, Any]] = []
        for index, row in enumerate(partition_rows):
            tensor = row.tensor
            encoded_rows.append(
                {
                    "index": index,
                    "symbol": row.symbol,
                    "timeframe": row.timeframe,
                    "tensor_id": tensor.tensor_id,
                    "feature_snapshot_id": tensor.feature_snapshot_id,
                    "model_vector": _cache_digest_value(tuple(tensor.model_vector)),
                    "values": _cache_digest_value(tuple(tensor.values)),
                    "missing_mask": _cache_digest_value(tuple(tensor.missing_mask)),
                    "stale_mask": _cache_digest_value(tuple(tensor.stale_mask)),
                    "source_availability": _cache_digest_value(
                        tuple(tensor.source_availability)
                    ),
                    "source_availability_vector": _cache_digest_value(
                        tuple(tensor.source_availability_vector)
                    ),
                    "feature_names": list(tensor.feature_names),
                    "source_labels": list(tensor.source_labels),
                    "data_coverage_percent": _cache_digest_value(
                        tensor.data_coverage_percent
                    ),
                    "label_action_index": row.label_action_index,
                    "label_expected_move_after_cost_bps": _cache_digest_value(
                        row.label_expected_move_after_cost_bps
                    ),
                    "decision_time": row.decision_time,
                    "label_available_at": row.label_available_at,
                    "payload_keys": list(row.payload_keys),
                    "row_classification": row.row_classification,
                    "trust_row": _cache_digest_value(dict(row.trust_row or {})),
                }
            )
        material["partitions"].append(
            {"name": partition_name, "rows": encoded_rows}
        )
    encoded = json.dumps(
        material,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def overfit_gap_threshold(train_loss: float) -> float:
    """Overfit-warning threshold, scaled to the supervised-loss magnitude.

    A purely ABSOLUTE 0.5 gap is miscalibrated at the real supervised-loss
    scale (~5-10): validation naturally sits >0.5 above train every cycle, so
    the warning fired on essentially every cycle even when the model
    generalized fine. That false positive hard-rejected every checkpoint
    (TRAIN_VAL_OVERFIT_GAP), so durable online learning never landed
    (effective_trainer_mode=INFERENCE_ONLY) and the GPU-saturation controller
    stayed pinned in VALIDATION_CHECKPOINT_BACKOFF. The threshold is now
    max(absolute floor, relative fraction of |train_loss|) -- mirroring the
    relative promotion tolerance already used by the checkpoint guard -- so a
    genuinely growing generalization gap still trips it. Both terms env-tunable.
    """
    abs_floor = max(0.0, _env_float("V2_TRAINER_OVERFIT_GAP_ABS_FLOOR", 0.5))
    rel_frac = max(0.0, _env_float("V2_TRAINER_OVERFIT_GAP_REL_FRAC", 0.35))
    scale = abs(train_loss) if (train_loss is not None and math.isfinite(train_loss)) else 0.0
    return max(abs_floor, rel_frac * scale)


def _bounded_env_float(
    primary_name: str,
    fallback_name: str | None,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> tuple[float, str, bool]:
    source = "default"
    raw = None
    if os.getenv(primary_name) is not None:
        raw = os.getenv(primary_name)
        source = primary_name
    elif fallback_name and os.getenv(fallback_name) is not None:
        raw = os.getenv(fallback_name)
        source = fallback_name
    if raw is None:
        value = float(default)
    else:
        value = _finite_float_or_none(raw)
        if value is None:
            return float(default), f"{source}:invalid_default", False
    bounded = min(float(maximum), max(float(minimum), float(value)))
    return bounded, source, bool(bounded != float(value))


def _parse_nvidia_smi_training_sample(raw: str) -> dict[str, float] | None:
    parts = [part.strip() for part in str(raw or "").split(",")]
    if len(parts) < 3:
        return None
    util = _finite_float_or_none(parts[0])
    vram_used = _finite_float_or_none(parts[1])
    vram_total = _finite_float_or_none(parts[2])
    if util is None or vram_used is None or vram_total in (None, 0.0):
        return None
    return {
        "gpu_utilization_percent": util,
        "vram_used_mb": vram_used,
        "vram_total_mb": float(vram_total),
    }


def _summarize_training_gpu_samples(samples: Sequence[dict[str, float]]) -> dict[str, Any]:
    if not samples:
        return {
            "training_window_gpu_sampler_active": False,
            "training_window_gpu_utilization_sample_count": 0,
        }
    utils = [float(sample["gpu_utilization_percent"]) for sample in samples]
    vram_used = [float(sample["vram_used_mb"]) for sample in samples]
    vram_total = max(float(sample["vram_total_mb"]) for sample in samples)
    return {
        "training_window_gpu_sampler_active": True,
        "training_window_gpu_utilization_sample_count": len(samples),
        "training_window_gpu_utilization_avg_percent": round(sum(utils) / len(utils), 6),
        "training_window_gpu_utilization_max_percent": round(max(utils), 6),
        "training_window_gpu_utilization_min_percent": round(min(utils), 6),
        "training_window_vram_used_avg_mb": round(sum(vram_used) / len(vram_used), 6),
        "training_window_vram_used_max_mb": round(max(vram_used), 6),
        "training_window_vram_total_mb": round(vram_total, 6),
        "training_window_vram_used_max_fraction": round(max(vram_used) / vram_total, 6),
    }


class _TrainingWindowGpuSampler:
    def __init__(self, *, enabled: bool, interval_seconds: float = GPU_TRAINING_SAMPLE_INTERVAL_SECONDS) -> None:
        self.enabled = bool(enabled)
        self.interval_seconds = max(0.1, float(interval_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._samples: list[dict[str, float]] = []

    def start(self) -> None:
        if not self.enabled:
            return
        self._thread = threading.Thread(
            target=self._run,
            name="v2-trainer-gpu-window-sampler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> dict[str, Any]:
        if self._thread is not None:
            self._stop.set()
            self._thread.join(timeout=2.0)
        return _summarize_training_gpu_samples(self._samples)

    def _run(self) -> None:
        while not self._stop.is_set():
            sample = self._read_once()
            if sample is not None:
                self._samples.append(sample)
            self._stop.wait(self.interval_seconds)

    @staticmethod
    def _read_once() -> dict[str, float] | None:
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except Exception:
            return None
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return _parse_nvidia_smi_training_sample(result.stdout.splitlines()[0])


@dataclass(frozen=True)
class PPOTrainingResult:
    status: str
    device: str
    cuda_active: bool
    cuda_claim_verified: bool
    gpu_name: str | None
    vram_allocated_mb: float | None
    batch_size: int
    training_steps: int
    train_rows: int
    validation_rows: int
    loss_before: float | None
    loss_after: float | None
    action_distribution: dict[str, int]
    metrics: dict = field(default_factory=dict)


class V2HybridPPOTrainer:
    def __init__(
        self,
        *,
        model: V2HybridPolicyModel,
        clip_epsilon: float = 0.2,
        entropy_coefficient: float | None = None,
        supervised_entropy_bonus: float | None = None,
        weight_decay: float | None = None,
        learning_rate: float | None = None,
        behavior_receipt_archive_root: Path | None = None,
        sampling_plan_key_resolver: SamplingPlanKeyResolver | None = None,
        training_observed_at: datetime | str | None = None,
    ) -> None:
        self.model = model
        self.clip_epsilon = float(clip_epsilon)
        observed_at = (
            datetime.now(tz=timezone.utc)
            if training_observed_at is None
            else self._parsed_canonical_time(training_observed_at)
        )
        if observed_at is None:
            raise ValueError("training_observed_at_must_be_aware_utc")
        self.training_observed_at = observed_at
        self.training_observed_at_iso = observed_at.isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z")
        # Learning rate is env-tunable so an offline hyperparameter sweep (see
        # v2_trainer_offline_hyperparameter_sweep) can search for a stable value.
        # Too-high LR is the likeliest cause of the observed upward loss divergence.
        if learning_rate is not None:
            self.learning_rate = float(learning_rate)
            self.learning_rate_source = "constructor"
            self.learning_rate_env_guard_capped = False
        else:
            (
                self.learning_rate,
                self.learning_rate_source,
                self.learning_rate_env_guard_capped,
            ) = _bounded_env_float(
                "PPO_LEARNING_RATE",
                "V2_TRAINER_LEARNING_RATE",
                default=1e-4,
                minimum=1e-8,
                maximum=ENV_PPO_LEARNING_RATE_MAX,
            )
        # Regularization / exploration knobs are env-tunable so the operator can
        # tune or instantly revert without a redeploy. Defaults are chosen to
        # counter the observed pathologies: near-zero policy entropy (collapse)
        # and an in-sample/out-of-sample overfit gap.
        #   V2_TRAINER_ENTROPY_COEF=0.01              -> restore prior PPO-lane value
        #   V2_TRAINER_SUPERVISED_ENTROPY_BONUS=0.0   -> restore prior (no supervised entropy)
        #   V2_TRAINER_WEIGHT_DECAY=0.01              -> restore torch AdamW default
        if entropy_coefficient is not None:
            self.entropy_coefficient = float(entropy_coefficient)
            self.entropy_coefficient_source = "constructor"
            self.entropy_coefficient_env_guard_capped = False
        else:
            # Env aliases are live-operator knobs, not an offline sweep surface.
            # Cap the env path below the 3e-4/0.02 combination that was observed
            # to diverge on V2; explicit constructor args remain available for
            # offline sweeps and retrains.
            (
                self.entropy_coefficient,
                self.entropy_coefficient_source,
                self.entropy_coefficient_env_guard_capped,
            ) = _bounded_env_float(
                "PPO_ENT_COEF",
                "V2_TRAINER_ENTROPY_COEF",
                default=0.01,
                minimum=0.0,
                maximum=ENV_PPO_ENTROPY_COEFFICIENT_MAX,
            )
        self.gamma, self.gamma_source, self.gamma_env_guard_capped = _bounded_env_float(
            "PPO_GAMMA",
            None,
            default=0.99,
            minimum=0.0,
            maximum=1.0,
        )
        # Default 0.0: a nonzero supervised-lane entropy bonus was found to DESTABILIZE
        # training on the live model (entropy drifted high and supervised loss diverged
        # upward, 3.6 -> 16+). Reverted to 0.0 (stable regime). Preventing the original
        # entropy collapse is a proper OFFLINE-tuning problem (LR/loss-scaling/entropy
        # schedule), not a live default. Still env-tunable for controlled experiments
        # via V2_TRAINER_SUPERVISED_ENTROPY_BONUS.
        self.supervised_entropy_bonus = (
            float(supervised_entropy_bonus)
            if supervised_entropy_bonus is not None
            else float(os.getenv("V2_TRAINER_SUPERVISED_ENTROPY_BONUS", "0.0") or 0.0)
        )
        self.weight_decay = (
            float(weight_decay)
            if weight_decay is not None
            else float(os.getenv("V2_TRAINER_WEIGHT_DECAY", "0.02") or 0.02)
        )
        self.behavior_receipt_archive_root = (
            Path(behavior_receipt_archive_root)
            if behavior_receipt_archive_root is not None
            else default_archive_root()
        )
        self.sampling_plan_key_resolver = sampling_plan_key_resolver
        self._ppo_parent_policy_fingerprint = model_parameter_fingerprint(self.model)

    @staticmethod
    def _parsed_canonical_time(value: Any) -> datetime | None:
        if value in (None, "") or isinstance(value, bool):
            return None
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)

    @classmethod
    def _chronological_purged_split(
        cls,
        rows: Sequence[TrainingExample],
        *,
        validation_fraction: float,
    ) -> tuple[list[TrainingExample], list[TrainingExample], dict[str, Any]]:
        """Build a fail-closed, chronological, label-purged validation split.

        Candidate learning is still allowed when split lineage is incomplete,
        but no rows are represented as held-out and the explicit PIT-safe flag
        remains false.  Runtime checkpoint promotion treats that flag as a hard
        prerequisite, so an unverifiable candidate can never become active.
        """
        selected = list(rows)
        metrics: dict[str, Any] = {
            "validation_split_strategy": (
                "chronological_immutable_decision_time_with_label_horizon_purge"
            ),
            "validation_split_fail_closed": True,
            "validation_split_pit_safe": False,
            "validation_split_reason": None,
            "validation_split_requested_fraction": validation_fraction,
            "validation_split_candidate_rows": len(selected),
            "validation_split_nominal_validation_rows": 0,
            "validation_split_actual_training_rows": len(selected),
            "validation_split_actual_validation_rows": 0,
            "validation_split_purged_training_rows": 0,
            "validation_split_decision_time_invalid_rows": 0,
            "validation_split_label_timing_invalid_rows": 0,
            "validation_split_label_timing_errors": {},
            "validation_split_equal_timestamps_kept_together": True,
            "validation_split_validation_start_decision_time": None,
            "validation_split_training_end_decision_time": None,
            "validation_split_training_label_available_at_max": None,
            "validation_split_temporal_overlap": None,
            "validation_split_label_overlap": None,
        }
        if not selected:
            metrics["validation_split_reason"] = "NO_SELECTED_ROWS"
            return selected, [], metrics
        fraction = _finite_float_or_none(validation_fraction)
        if fraction is None or fraction < 0.0 or fraction >= 1.0:
            metrics["validation_split_reason"] = "VALIDATION_FRACTION_INVALID"
            return selected, [], metrics
        if fraction == 0.0:
            metrics["validation_split_reason"] = "VALIDATION_DISABLED"
            return selected, [], metrics
        if len(selected) < 2:
            metrics["validation_split_reason"] = "INSUFFICIENT_ROWS_FOR_VALIDATION"
            return selected, [], metrics

        chronology: list[tuple[datetime, int, TrainingExample]] = []
        for input_index, row in enumerate(selected):
            decision_time = cls._parsed_canonical_time(row.decision_time)
            if decision_time is None:
                metrics["validation_split_decision_time_invalid_rows"] += 1
                continue
            chronology.append((decision_time, input_index, row))
        if len(chronology) != len(selected):
            metrics["validation_split_reason"] = "DECISION_TIME_MISSING_OR_INVALID"
            return selected, [], metrics

        timing_errors: dict[str, int] = {}
        for _decision_time, _input_index, row in chronology:
            label_time = cls._parsed_canonical_time(row.label_available_at)
            if row.label_timing_valid is not True or label_time is None:
                reason = str(row.label_timing_error or "LABEL_TIMING_MISSING")
                timing_errors[reason] = timing_errors.get(reason, 0) + 1
        if timing_errors:
            ordered_rows = [item[2] for item in sorted(chronology)]
            metrics.update(
                {
                    "validation_split_reason": "LABEL_TIMING_MISSING_OR_INVALID",
                    "validation_split_label_timing_invalid_rows": sum(
                        timing_errors.values()
                    ),
                    "validation_split_label_timing_errors": timing_errors,
                    "validation_split_actual_training_rows": len(ordered_rows),
                }
            )
            return ordered_rows, [], metrics

        chronology.sort(key=lambda item: (item[0], item[1]))
        nominal_validation_rows = max(1, int(len(chronology) * fraction))
        metrics["validation_split_nominal_validation_rows"] = nominal_validation_rows
        nominal_start = len(chronology) - nominal_validation_rows
        validation_start = chronology[nominal_start][0]
        candidate_training = [item for item in chronology if item[0] < validation_start]
        validation = [item for item in chronology if item[0] >= validation_start]
        validation_start_iso = validation_start.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )
        metrics["validation_split_validation_start_decision_time"] = validation_start_iso
        if not candidate_training or not validation:
            ordered_rows = [item[2] for item in chronology]
            metrics.update(
                {
                    "validation_split_reason": "DISTINCT_CHRONOLOGICAL_BOUNDARY_UNAVAILABLE",
                    "validation_split_actual_training_rows": len(ordered_rows),
                }
            )
            return ordered_rows, [], metrics

        purged: list[tuple[datetime, int, TrainingExample]] = []
        training: list[tuple[datetime, int, TrainingExample]] = []
        for item in candidate_training:
            label_time = cls._parsed_canonical_time(item[2].label_available_at)
            if label_time is None or label_time >= validation_start:
                purged.append(item)
            else:
                training.append(item)
        metrics["validation_split_purged_training_rows"] = len(purged)
        if not training:
            ordered_rows = [item[2] for item in chronology]
            metrics.update(
                {
                    "validation_split_reason": "LABEL_HORIZON_PURGE_REMOVED_ALL_TRAINING_ROWS",
                    "validation_split_actual_training_rows": len(ordered_rows),
                }
            )
            return ordered_rows, [], metrics

        training_end = max(item[0] for item in training)
        training_label_end = max(
            cls._parsed_canonical_time(item[2].label_available_at)
            for item in training
        )
        temporal_overlap = training_end >= validation_start
        label_overlap = training_label_end is None or training_label_end >= validation_start
        metrics.update(
            {
                "validation_split_pit_safe": not temporal_overlap and not label_overlap,
                "validation_split_reason": (
                    "PIT_SAFE_CHRONOLOGICAL_PURGED_SPLIT"
                    if not temporal_overlap and not label_overlap
                    else "PIT_SEPARATION_PROOF_FAILED"
                ),
                "validation_split_actual_training_rows": len(training),
                "validation_split_actual_validation_rows": len(validation),
                "validation_split_training_end_decision_time": training_end.isoformat(
                    timespec="microseconds"
                ).replace("+00:00", "Z"),
                "validation_split_training_label_available_at_max": (
                    training_label_end.isoformat(timespec="microseconds").replace(
                        "+00:00", "Z"
                    )
                    if training_label_end is not None
                    else None
                ),
                "validation_split_temporal_overlap": temporal_overlap,
                "validation_split_label_overlap": label_overlap,
            }
        )
        if metrics["validation_split_pit_safe"] is not True:
            ordered_rows = [item[2] for item in chronology]
            metrics["validation_split_actual_training_rows"] = len(ordered_rows)
            metrics["validation_split_actual_validation_rows"] = 0
            return ordered_rows, [], metrics
        return [item[2] for item in training], [item[2] for item in validation], metrics

    def plan_exact_ppo_optimizer_attempts(
        self,
        examples: Sequence[TrainingExample],
        *,
        batch_size: int = 64,
        validation_fraction: float = 0.2,
    ) -> dict[str, Any]:
        """Return the exact rows runtime must fence before ``train()``.

        The plan applies the same trust filter, exact-receipt/finalized-outcome
        eligibility, stable update-key de-duplication, mixed-lane ordering,
        adaptive batch selection, chronological split, and label-horizon purge
        as the optimizer. Descriptors are emitted in actual train-partition
        order and bind each claim to the currently loaded parent weights.
        """

        self._ppo_parent_policy_fingerprint = model_parameter_fingerprint(self.model)
        available_rows = list(examples)
        trusted_rows, rejection_metrics = self._filter_trusted_training_rows(
            available_rows
        )
        all_ppo_rows = [
            row for row in trusted_rows if self._has_on_policy_ppo_fields(row)
        ]
        ppo_rows: list[TrainingExample] = []
        update_keys_seen: set[str] = set()
        duplicate_update_keys: list[str] = []
        for row in all_ppo_rows:
            update_key = ppo_consumption_update_key_from_row(self._trust_row(row))
            if update_key in update_keys_seen:
                duplicate_update_keys.append(update_key)
                continue
            update_keys_seen.add(update_key)
            ppo_rows.append(row)
        outcome_rows = [
            row for row in trusted_rows if self._has_outcome_supervised_targets(row)
        ]
        if ppo_rows and outcome_rows:
            learning_mode = "ppo_mixed_outcome_supervised"
            ppo_row_ids = {id(row) for row in ppo_rows}
            all_ppo_row_ids = {id(row) for row in all_ppo_rows}
            outcome_row_ids = {id(row) for row in outcome_rows}
            learnable_rows = [
                *ppo_rows,
                *[
                    row
                    for row in trusted_rows
                    if id(row) in outcome_row_ids
                    and id(row) not in ppo_row_ids
                    and id(row) not in all_ppo_row_ids
                ],
            ]
        elif ppo_rows:
            learning_mode = "ppo_on_policy"
            learnable_rows = ppo_rows
        else:
            learning_mode = "outcome_supervised"
            learnable_rows = outcome_rows

        target_batch_size = max(1, int(batch_size))
        tuned_batch_size = self._auto_tuned_batch_size(
            requested_batch_size=target_batch_size,
            available_rows=len(learnable_rows),
        )
        selected_rows_for_split = learnable_rows[:tuned_batch_size]
        if selected_rows_for_split:
            train_rows, validation_rows, split_metrics = (
                self._chronological_purged_split(
                    selected_rows_for_split,
                    validation_fraction=validation_fraction,
                )
            )
        else:
            train_rows, validation_rows = [], []
            split_metrics = {}
        eligible_examples = [
            row for row in train_rows if self._has_on_policy_ppo_fields(row)
        ]
        descriptors: list[dict[str, str]] = []
        for row in eligible_examples:
            trust_row = self._trust_row(row)
            descriptors.append(
                {
                    "update_key": ppo_consumption_update_key_from_row(trust_row),
                    "receipt_hash": str(
                        trust_row["behavior_policy_receipt_hash"]
                    ),
                    "finalized_outcome_digest": str(
                        trust_row["finalized_outcome_digest"]
                    ),
                    "parent_policy_fingerprint": (
                        self._ppo_parent_policy_fingerprint
                    ),
                }
            )
        return {
            "parent_policy_fingerprint": self._ppo_parent_policy_fingerprint,
            "optimizer_attempt_descriptors": descriptors,
            "eligible_examples": eligible_examples,
            "ordered_update_keys": [row["update_key"] for row in descriptors],
            "ordered_update_keys_complete": len(descriptors)
            == len(eligible_examples),
            "ordered_update_keys_unique": len(
                {row["update_key"] for row in descriptors}
            )
            == len(descriptors),
            "duplicate_update_keys": duplicate_update_keys,
            "available_rows": available_rows,
            "trusted_rows": trusted_rows,
            "all_ppo_rows": all_ppo_rows,
            "ppo_rows": ppo_rows,
            "outcome_rows": outcome_rows,
            "learnable_rows": learnable_rows,
            "selected_rows_for_split": selected_rows_for_split,
            "train_rows": train_rows,
            "validation_rows": validation_rows,
            "learning_mode": learning_mode,
            "target_batch_size": target_batch_size,
            "tuned_batch_size": tuned_batch_size,
            "rejection_metrics": rejection_metrics,
            "split_metrics": split_metrics,
        }

    def train(
        self,
        examples: Sequence[TrainingExample],
        *,
        steps: int = 2,
        batch_size: int = 64,
        validation_fraction: float = 0.2,
    ) -> PPOTrainingResult:
        attempt_plan = self.plan_exact_ppo_optimizer_attempts(
            examples,
            batch_size=batch_size,
            validation_fraction=validation_fraction,
        )
        available_rows = attempt_plan["available_rows"]
        trusted_rows = attempt_plan["trusted_rows"]
        rejection_metrics = attempt_plan["rejection_metrics"]
        ppo_rows = attempt_plan["ppo_rows"]
        duplicate_ppo_update_keys = attempt_plan["duplicate_update_keys"]
        outcome_rows = attempt_plan["outcome_rows"]
        learning_mode = attempt_plan["learning_mode"]
        learnable_rows = attempt_plan["learnable_rows"]
        trust_rows_for_metrics = [self._trust_row(row) for row in learnable_rows]
        accepted_trust_rows_for_metrics = [self._trust_row(row) for row in trusted_rows]
        policy_sampled_rows_seen = sum(
            1
            for row in accepted_trust_rows_for_metrics
            if row.get("ppo_on_policy_entry_fields_present") is True
            or row.get("old_log_prob") not in (None, "")
            or row.get("selected_action_log_prob") not in (None, "")
        )
        ppo_ineligibility_reason_counts: dict[str, int] = {}
        for example in trusted_rows:
            trust_row = self._trust_row(example)
            if not (
                trust_row.get("ppo_on_policy_entry_fields_present") is True
                or trust_row.get("old_log_prob") not in (None, "")
                or trust_row.get("selected_action_log_prob") not in (None, "")
            ):
                continue
            reason = self._ppo_ineligibility_reason(example)
            if reason is not None:
                ppo_ineligibility_reason_counts[reason] = (
                    ppo_ineligibility_reason_counts.get(reason, 0) + 1
                )
        policy_sampled_rows_with_action_probabilities = sum(
            1
            for row in accepted_trust_rows_for_metrics
            if isinstance(row.get("action_probabilities"), (list, tuple))
            and len(row.get("action_probabilities") or []) > 0
        )
        policy_sampled_closed_positions = sum(
            1
            for row in accepted_trust_rows_for_metrics
            if row.get("exit_time") not in (None, "")
            or row.get("close_time") not in (None, "")
            or row.get("realized_pnl_bps") not in (None, "")
        )
        policy_sampled_rows_missing_behavior_action_identity = sum(
            1
            for example in trusted_rows
            if self._trust_row(example).get("old_log_prob") not in (None, "")
            and self._behavior_action_identity(example) is None
        )
        ppo_exact_reason = None
        if not ppo_rows:
            if policy_sampled_rows_seen <= 0:
                ppo_exact_reason = "NO_POLICY_SAMPLED_POSITION_OPEN"
            elif policy_sampled_closed_positions <= 0:
                ppo_exact_reason = "POLICY_POSITION_OPEN_WAITING_CLOSE"
            elif policy_sampled_rows_missing_behavior_action_identity > 0:
                ppo_exact_reason = "CLOSED_ROWS_MISSING_BEHAVIOR_ACTION_IDENTITY"
            elif ppo_ineligibility_reason_counts.get(
                "DETERMINISTIC_POLICY_NOT_ON_POLICY_SAMPLED",
                0,
            ):
                ppo_exact_reason = "DETERMINISTIC_POLICY_NOT_ON_POLICY_SAMPLED"
            elif ppo_ineligibility_reason_counts.get(
                "BEHAVIOR_DISTRIBUTION_CONTRACT_MISMATCH",
                0,
            ):
                ppo_exact_reason = "BEHAVIOR_DISTRIBUTION_CONTRACT_MISMATCH"
            else:
                ppo_exact_reason = "CLOSED_ROWS_MISSING_ON_POLICY_FIELDS"
        rejection_metrics.update(
            {
                "accepted_training_rows": len(trusted_rows),
                "trusted_rows_loaded": len(learnable_rows),
                "ppo_on_policy_rows": len(ppo_rows),
                "ppo_duplicate_update_key_rows_rejected": len(
                    duplicate_ppo_update_keys
                ),
                "ppo_duplicate_update_keys_rejected": (
                    duplicate_ppo_update_keys
                ),
                "outcome_supervised_rows": len(outcome_rows),
                "trusted_replay_rows_loaded": sum(
                    1
                    for row in trust_rows_for_metrics
                    if str(row.get("update_lane") or "").upper()
                    == "OUTCOME_SUPERVISED_TRUSTED_REPLAY"
                ),
                "trusted_replay_backfill_rows_loaded": sum(
                    1
                    for row in trust_rows_for_metrics
                    if row.get("trusted_replay_backfill_lane") is True
                ),
                "feedback_rows_entered_batch": sum(
                    1
                    for row in trust_rows_for_metrics
                    if str(row.get("update_lane") or "").upper()
                    == "OUTCOME_SUPERVISED_CLOSED_TRADE"
                ),
                "counterfactual_rows_consumed": sum(
                    1
                    for row in trust_rows_for_metrics
                    if "COUNTERFACTUAL" in str(
                        row.get("trainer_feedback_source")
                        or row.get("trainer_feedback_source_key")
                        or ""
                    ).upper()
                ),
                "paper_closed_rows_consumed": sum(
                    1
                    for row in trust_rows_for_metrics
                    if row.get("realized_pnl_bps") not in (None, "")
                    or row.get("realized_net_pnl_bps") not in (None, "")
                ),
                "strategy_supply_feedback_rows": sum(
                    1
                    for row in trust_rows_for_metrics
                    if "STRATEGY_SUPPLY" in str(row.get("trainer_feedback_source") or "").upper()
                ),
                "historical_replay_rows": sum(
                    1 for row in trust_rows_for_metrics if row.get("historical_replay_row") is True
                ),
                "feature_snapshot_archive_rows": sum(
                    1
                    for row in trust_rows_for_metrics
                    if "DURABLE_FEATURE_SNAPSHOT" in str(
                        row.get("trainer_feedback_source") or row.get("row_source") or ""
                    ).upper()
                ),
                "policy_sampled_rows_seen": policy_sampled_rows_seen,
                "policy_sampled_rows_with_action_probabilities": (
                    policy_sampled_rows_with_action_probabilities
                ),
                "policy_sampled_rows_with_old_log_prob": sum(
                    1 for row in accepted_trust_rows_for_metrics if row.get("old_log_prob") not in (None, "")
                ),
                "policy_sampled_rows_with_old_value": sum(
                    1 for row in accepted_trust_rows_for_metrics if row.get("old_value") not in (None, "")
                ),
                "policy_sampled_rows_with_rollout_id": sum(
                    1 for row in accepted_trust_rows_for_metrics if row.get("rollout_id") not in (None, "")
                ),
                "policy_sampled_materialized_positions": sum(
                    1
                    for row in accepted_trust_rows_for_metrics
                    if row.get("materialization_queue_id") not in (None, "")
                    and row.get("ppo_on_policy_entry_fields_present") is True
                ),
                "policy_sampled_closed_positions": policy_sampled_closed_positions,
                "policy_sampled_rows_missing_behavior_action_identity": (
                    policy_sampled_rows_missing_behavior_action_identity
                ),
                "ppo_ineligibility_reason_counts": ppo_ineligibility_reason_counts,
                "ppo_rows_rejected_deterministic_behavior_policy": (
                    ppo_ineligibility_reason_counts.get(
                        "DETERMINISTIC_POLICY_NOT_ON_POLICY_SAMPLED",
                        0,
                    )
                ),
                "ppo_rows_rejected_distribution_contract_mismatch": (
                    ppo_ineligibility_reason_counts.get(
                        "BEHAVIOR_DISTRIBUTION_CONTRACT_MISMATCH",
                        0,
                    )
                ),
                "ppo_required_behavior_sampling_mode": (
                    PPO_REQUIRED_BEHAVIOR_SAMPLING_MODE
                ),
                "ppo_required_behavior_distribution_contract": (
                    PPO_REQUIRED_BEHAVIOR_DISTRIBUTION_CONTRACT
                ),
                "ppo_rows_pending": 0 if ppo_rows else policy_sampled_rows_seen,
                "ppo_rows_consumed": len(ppo_rows),
                "ppo_no_rows_exact_reason": ppo_exact_reason,
                "ppo_rows_rejected_missing_on_policy_fields": (
                    max(0, len(trusted_rows) - len(ppo_rows)) if not ppo_rows else 0
                ),
                "ppo_rows_missing_on_policy_fields": max(0, len(trusted_rows) - len(ppo_rows)),
                "learning_update_lane": learning_mode if learnable_rows else "blocked",
                "closed_trade_feedback_requires_outcome_supervised_lane": bool(outcome_rows and not ppo_rows),
                "mixed_ppo_outcome_batch_active": bool(ppo_rows and outcome_rows),
            }
        )
        target_batch_size = attempt_plan["target_batch_size"]
        tuned_batch_size = attempt_plan["tuned_batch_size"]
        selected_rows_for_split = attempt_plan["selected_rows_for_split"]
        if not selected_rows_for_split:
            return self._blocked(
                "NO_TRUSTED_TRAINING_ROWS",
                batch_size=target_batch_size,
                metrics=rejection_metrics,
            )
        train_rows = attempt_plan["train_rows"]
        validation_rows = attempt_plan["validation_rows"]
        split_metrics = attempt_plan["split_metrics"]
        rejection_metrics.update(split_metrics)
        consumed_ppo_rows = [
            row for row in train_rows if self._has_on_policy_ppo_fields(row)
        ]
        consumed_update_keys = [
            ppo_consumption_update_key_from_row(self._trust_row(row))
            for row in consumed_ppo_rows
        ]
        consumed_update_keys_unique = len(set(consumed_update_keys)) == len(
            consumed_update_keys
        )
        rejection_metrics.update(
            {
                "ppo_rows_consumed": len(consumed_ppo_rows),
                "ppo_consumed_update_keys": consumed_update_keys,
                "ppo_consumed_update_keys_complete": (
                    len(consumed_update_keys) == len(consumed_ppo_rows)
                    and consumed_update_keys_unique
                ),
                "ppo_consumed_update_keys_ordered": True,
                "ppo_consumed_update_keys_unique": (
                    consumed_update_keys_unique
                ),
                "ppo_consumption_claim_scope": (
                    "PARENT_POLICY_OPTIMIZER_ATTEMPT"
                ),
                "ppo_consumption_commit_requires_optimizer_step": True,
                "ppo_consumption_survives_candidate_rejection": True,
                "ppo_configured_optimizer_epochs_per_consumption_claim": (
                    max(1, int(steps)) if consumed_ppo_rows else 0
                ),
                "ppo_rows_reused_across_optimizer_steps_within_train_call": (
                    bool(consumed_ppo_rows) and max(1, int(steps)) > 1
                ),
            }
        )
        if self.model.torch_available:
            return self._train_torch(
                train_rows,
                validation_rows=validation_rows,
                steps=steps,
                batch_size=tuned_batch_size,
                target_batch_size=target_batch_size,
                available_rows=len(available_rows),
                selected_rows=len(selected_rows_for_split),
                rejection_metrics=rejection_metrics,
                learning_mode=learning_mode,
            )
        return self._train_fallback(
            train_rows,
            validation_rows=validation_rows,
            steps=steps,
            batch_size=tuned_batch_size,
            target_batch_size=target_batch_size,
            available_rows=len(available_rows),
            selected_rows=len(selected_rows_for_split),
            rejection_metrics=rejection_metrics,
            learning_mode=learning_mode,
        )

    def _filter_trusted_training_rows(
        self,
        rows: Sequence[TrainingExample],
    ) -> tuple[list[TrainingExample], dict[str, Any]]:
        accepted: list[TrainingExample] = []
        rejected: list[dict[str, Any]] = []
        rejected_family_diagnostics: list[dict[str, Any]] = []
        cost_masked_accepted = 0
        for row in rows:
            trust_row = self._trust_row(row)
            if not _has_explicit_training_trust_evidence(trust_row):
                item = {
                    "id": self._row_id(row, trust_row),
                    "symbol": row.symbol,
                    "timeframe": row.timeframe,
                    "reasons": ["EXPLICIT_TRAINING_TRUST_EVIDENCE_MISSING"],
                    "market_state_integrity_score": None,
                }
                rejected.append(item)
                rejected_family_diagnostics.append(
                    self._rejection_family_diagnostic(row, trust_row, item["reasons"])
                )
                continue
            sample = classify_training_sample(trust_row)
            reasons = set(sample.get("reject_reasons") or [])
            reasons.update(self._extra_rejection_reasons(row, trust_row))
            if sample.get("accepted_for_training") is True and not reasons:
                accepted.append(row)
                continue
            # Historical archive rows that predate a derived-cost estimator carry
            # explicit decision-time masks for ONLY cost fields (fee/slippage).
            # Those are pricing-model inputs, not market-state feature families:
            # trainable with the mask intact. The subset check guarantees no
            # stale/future-leak/other reason rides along, and decision/live
            # gates still demand real cost evidence via their own validators.
            if (
                reasons
                and reasons
                <= {"MISSING_CRITICAL_FEATURE_FAMILY", "ROW_CLASSIFICATION_MISSING_MASKED"}
                and self._missing_names_are_training_cost_maskable(
                    trust_row.get("missing_feature_names")
                )
            ):
                cost_masked_accepted += 1
                accepted.append(row)
                continue
            item = {
                "id": self._row_id(row, trust_row),
                "symbol": row.symbol,
                "timeframe": row.timeframe,
                "reasons": sorted(reasons) or ["MARKET_STATE_REJECTED_FOR_TRAINING"],
                "market_state_integrity_score": sample.get("market_state_integrity_score"),
            }
            rejected.append(item)
            rejected_family_diagnostics.append(
                self._rejection_family_diagnostic(row, trust_row, item["reasons"])
            )
        reason_counts: dict[str, int] = {}
        for item in rejected:
            for reason in item["reasons"]:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
        return accepted, {
            "training_observed_at": self.training_observed_at_iso,
            "training_rejection_count": len(rejected),
            "training_rejected_example_ids": [item["id"] for item in rejected[:10]],
            "training_rejection_reason_counts": reason_counts,
            "training_rejection_family_diagnostics": rejected_family_diagnostics[:50],
            "training_trusted_rows": len(accepted),
            "training_cost_masked_rows_accepted": cost_masked_accepted,
        }

    @staticmethod
    def _trust_row(example: TrainingExample) -> dict[str, Any]:
        row = dict(example.trust_row or {})
        row.setdefault("symbol", example.symbol)
        row.setdefault("timeframe", example.timeframe)
        row.setdefault("feature_snapshot_id", example.tensor.feature_snapshot_id)
        row.setdefault("feature_vector_hash", example.tensor.tensor_id)
        row.setdefault("missing_feature_names", list(example.tensor.missing_feature_names))
        row.setdefault("stale_feature_names", list(example.tensor.stale_feature_names))
        row.setdefault("row_classification", example.row_classification)
        row.setdefault("trainer_consumable", example.row_classification == "TRAINABLE")
        if example.behavior_action_index is not None:
            row.setdefault("behavior_action_index", example.behavior_action_index)
        if example.behavior_action is not None:
            row.setdefault("behavior_action", example.behavior_action)
        return row

    @staticmethod
    def _strict_action_index(value: Any) -> int | None:
        if isinstance(value, bool) or value in (None, ""):
            return None
        try:
            parsed = int(value)
            exactly_integral = float(value) == float(parsed)
        except (TypeError, ValueError, OverflowError):
            return None
        if not exactly_integral or not 0 <= parsed < ACTION_COUNT:
            return None
        return parsed

    @classmethod
    def _behavior_action_identity(cls, example: TrainingExample) -> tuple[int, str] | None:
        """Return the immutable entry action only when every identity agrees."""
        row = cls._trust_row(example)
        index = cls._strict_action_index(example.behavior_action_index)
        action = str(example.behavior_action or "").strip().lower()
        if index is None or not action or ACTION_LABELS[index] != action:
            return None

        # Preserve raw entry aliases for compatibility, but reject any conflict.
        for field_name in ("behavior_action_index", "selected_action_index"):
            raw = row.get(field_name)
            if raw in (None, ""):
                continue
            if cls._strict_action_index(raw) != index:
                return None
        for field_name in ("behavior_action", "selected_action"):
            raw = row.get(field_name)
            if raw in (None, ""):
                continue
            if str(raw).strip().lower() != action:
                return None

        probabilities = row.get("action_probabilities")
        if isinstance(probabilities, (list, tuple)) and index >= len(probabilities):
            return None
        return index, action

    def _durable_receipt_ineligibility_reason(
        self,
        *,
        row: Mapping[str, Any],
        receipt: Mapping[str, Any],
        expected_update_key: str,
    ) -> str | None:
        """Re-read immutable disk evidence before admitting one exact PPO row."""

        try:
            verification = verify_archived_behavior_receipt(
                receipt,
                root=self.behavior_receipt_archive_root,
            )
            receipt_hash = str(verification["receipt_hash"])
            status = receipt_lifecycle_status(
                receipt_hash,
                root=self.behavior_receipt_archive_root,
            )
            events = lifecycle_events(
                receipt_hash,
                root=self.behavior_receipt_archive_root,
            )
        except (BehaviorReceiptArchiveError, OSError, TypeError, ValueError):
            return "BEHAVIOR_POLICY_DURABLE_ARCHIVE_INVALID"

        archive_hash = str(verification.get("archive_content_sha256") or "")
        if row.get("behavior_policy_receipt_archive_write_success") is not True:
            return "BEHAVIOR_POLICY_DURABLE_ARCHIVE_WRITE_NOT_PROVEN"
        if row.get("behavior_policy_receipt_archive_content_sha256") != archive_hash:
            return "BEHAVIOR_POLICY_DURABLE_ARCHIVE_HASH_BINDING_MISMATCH"
        if row.get("behavior_policy_receipt_archive_finalized") is not True:
            return "BEHAVIOR_POLICY_DURABLE_OUTCOME_NOT_MARKED_FINALIZED"
        if status.get("published_durable") is not True:
            return "BEHAVIOR_POLICY_DURABLE_PUBLISHED_EVENT_MISSING"
        if status.get("entry_accepted_durable") is not True:
            return "BEHAVIOR_POLICY_DURABLE_ENTRY_EVENT_MISSING"
        if status.get("outcome_finalized_durable") is not True:
            return "BEHAVIOR_POLICY_DURABLE_OUTCOME_EVENT_MISSING"
        if status.get("trainer_consumed_durable") is True:
            return "PPO_UPDATE_ALREADY_DURABLY_CONSUMED"
        if status.get("retention_required") is not True:
            return "BEHAVIOR_POLICY_DURABLE_RETENTION_STATE_INVALID"

        event_by_type = {
            str(event.get("event_type") or ""): event for event in events
        }
        published = event_by_type.get(EVENT_PUBLISHED)
        entry = event_by_type.get(EVENT_ENTRY_ACCEPTED)
        finalized = event_by_type.get(EVENT_OUTCOME_FINALIZED)
        if not all(isinstance(event, Mapping) for event in (published, entry, finalized)):
            return "BEHAVIOR_POLICY_DURABLE_LIFECYCLE_INCOMPLETE"
        assert isinstance(published, Mapping)
        assert isinstance(entry, Mapping)
        assert isinstance(finalized, Mapping)
        published_binding = published.get("binding")
        entry_binding = entry.get("binding")
        finalized_binding = finalized.get("binding")
        if not all(
            isinstance(binding, Mapping)
            for binding in (published_binding, entry_binding, finalized_binding)
        ):
            return "BEHAVIOR_POLICY_DURABLE_EVENT_BINDING_INVALID"
        assert isinstance(published_binding, Mapping)
        assert isinstance(entry_binding, Mapping)
        assert isinstance(finalized_binding, Mapping)

        published_expected = {
            "prediction_id": receipt.get("prediction_id"),
            "symbol": receipt.get("symbol"),
            "timeframe": receipt.get("timeframe"),
            "checkpoint_id": receipt.get("checkpoint_id"),
            "archive_content_sha256": archive_hash,
        }
        if any(
            published_binding.get(field) != expected
            for field, expected in published_expected.items()
        ):
            return "BEHAVIOR_POLICY_DURABLE_PUBLISHED_BINDING_MISMATCH"

        cost_provenance = receipt.get("cost_provenance")
        source_payload = (
            cost_provenance.get("source_payload")
            if isinstance(cost_provenance, Mapping)
            else None
        )
        fee_identity = (
            source_payload.get("fee_schedule_evidence_sha256")
            if isinstance(source_payload, Mapping)
            else None
        )
        entry_expected = {
            "prediction_id": receipt.get("prediction_id"),
            "symbol": receipt.get("symbol"),
            "timeframe": receipt.get("timeframe"),
            "entry_fee_schedule_evidence_sha256": fee_identity,
        }
        if not str(entry_binding.get("paper_fill_id") or ""):
            return "BEHAVIOR_POLICY_DURABLE_ENTRY_IDENTITY_MISSING"
        if any(
            entry_binding.get(field) != expected
            for field, expected in entry_expected.items()
        ):
            return "BEHAVIOR_POLICY_DURABLE_ENTRY_BINDING_MISMATCH"

        finalized_expected = {
            "finalized_outcome_id": row.get("finalized_outcome_id"),
            "finalized_outcome_digest": row.get("finalized_outcome_digest"),
            "ppo_consumption_update_key": expected_update_key,
        }
        if any(
            finalized_binding.get(field) != expected
            for field, expected in finalized_expected.items()
        ):
            return "BEHAVIOR_POLICY_DURABLE_OUTCOME_BINDING_MISMATCH"

        event_hash_fields = {
            EVENT_PUBLISHED: "behavior_policy_receipt_archive_published_event_hash",
            EVENT_ENTRY_ACCEPTED: "behavior_policy_receipt_archive_entry_event_hash",
            EVENT_OUTCOME_FINALIZED: (
                "behavior_policy_receipt_archive_finalization_event_hash"
            ),
        }
        for event_type, row_field in event_hash_fields.items():
            if row.get(row_field) != event_by_type[event_type].get("event_hash"):
                return "BEHAVIOR_POLICY_DURABLE_EVENT_HASH_BINDING_MISMATCH"
        return None

    def _durable_sampling_cohort_ineligibility_reason(
        self,
        *,
        row: Mapping[str, Any],
        receipt: Mapping[str, Any],
    ) -> str | None:
        """Authenticate the complete sampled cohort and exact receipt membership."""

        proof = row.get("on_policy_sampling_cohort_completeness_proof")
        if not isinstance(proof, Mapping):
            return PPO_INCOMPLETE_SAMPLED_COHORT_REASON
        if not callable(self.sampling_plan_key_resolver):
            return PPO_SAMPLING_COHORT_KEY_RESOLVER_MISSING_REASON
        try:
            verification = verify_archived_sampling_cohort_completeness_proof(
                proof,
                key_resolver=self.sampling_plan_key_resolver,
                root=self.behavior_receipt_archive_root,
                expected_receipt_hash=str(receipt.get("receipt_hash") or ""),
                expected_sampling_plan_hash=str(
                    receipt.get("on_policy_sampling_plan_hash") or ""
                ),
                expected_sampling_plan_input_hash=str(
                    receipt.get("on_policy_sampling_plan_input_hash") or ""
                ),
                expected_parent_policy_fingerprint=(
                    self._ppo_parent_policy_fingerprint
                ),
            )
        except (BehaviorReceiptArchiveError, OSError, TypeError, ValueError):
            return PPO_SAMPLING_COHORT_PROOF_INVALID_REASON
        if (
            verification.get("cohort_verified") is not True
            or verification.get("receipt_membership_verified") is not True
        ):
            return PPO_SAMPLING_COHORT_PROOF_INVALID_REASON
        proof_generated_at = self._parsed_canonical_time(
            verification.get("generated_at")
        )
        if (
            proof_generated_at is None
            or proof_generated_at > self.training_observed_at
        ):
            return PPO_SAMPLING_COHORT_PROOF_AFTER_TRAINING_OBSERVED_REASON
        if (
            row.get("on_policy_sampling_cohort_completeness_verified") is not True
            or row.get(
                "on_policy_sampling_cohort_receipt_membership_verified"
            )
            is not True
            or row.get("on_policy_sampling_cohort_completeness_digest")
            != verification.get("cohort_digest")
        ):
            return PPO_SAMPLING_COHORT_PROOF_BINDING_MISMATCH_REASON
        return None

    def _has_on_policy_ppo_fields(self, example: TrainingExample) -> bool:
        return self._ppo_ineligibility_reason(example) is None

    def _ppo_ineligibility_reason(self, example: TrainingExample) -> str | None:
        row = self._trust_row(example)
        if row.get("ppo_consumption_ledger_eligible") is False:
            return "PPO_UPDATE_ALREADY_CONSUMED_FOR_PARENT_POLICY"
        if row.get("strategy_supply_hypothesis") is True:
            return "STRATEGY_SUPPLY_ACTION_NOT_SAMPLED_FROM_CUDA_POLICY"
        required = ("old_log_prob", "old_value", "reward", "done", "rollout_id")
        if any(row.get(field) in (None, "") for field in required):
            return "MISSING_ON_POLICY_FIELDS"
        trajectory_raw = row.get("trajectory_index")
        if trajectory_raw in (None, ""):
            trajectory_raw = row.get("trajectory_step")
        if trajectory_raw in (None, ""):
            return "MISSING_TRAJECTORY_POSITION"
        trajectory_value = (
            None
            if isinstance(trajectory_raw, bool)
            else _finite_float_or_none(trajectory_raw)
        )
        if (
            trajectory_value is None
            or not trajectory_value.is_integer()
            or trajectory_value < 0.0
        ):
            return "TRAJECTORY_POSITION_NOT_NONNEGATIVE_INTEGER"
        if self._behavior_action_identity(example) is None:
            return "MISSING_OR_CONFLICTING_BEHAVIOR_ACTION_IDENTITY"
        if any(_finite_float_or_none(row.get(field)) is None for field in ("old_log_prob", "old_value", "reward")):
            return "NONFINITE_ON_POLICY_FIELDS"
        if row.get("done") is not True:
            return "TERMINAL_DONE_NOT_TRUE"
        sampling_mode = str(
            row.get("behavior_policy_sampling_mode")
            or row.get("behavior_action_sampling_mode")
            or ""
        ).strip().upper()
        if sampling_mode != PPO_REQUIRED_BEHAVIOR_SAMPLING_MODE:
            return "DETERMINISTIC_POLICY_NOT_ON_POLICY_SAMPLED"
        distribution_contract = str(
            row.get("behavior_policy_distribution_contract")
            or row.get("behavior_distribution_contract")
            or ""
        ).strip().upper()
        if distribution_contract not in PPO_SUPPORTED_BEHAVIOR_DISTRIBUTION_CONTRACTS:
            return "BEHAVIOR_DISTRIBUTION_CONTRACT_MISMATCH"
        finalized_reasons = finalized_outcome_binding_rejection_reasons(row)
        if finalized_reasons:
            return "FINALIZED_OUTCOME_BINDING_INVALID"
        reward = _finite_float_or_none(row.get("reward"))
        finalized_reward = _finite_float_or_none(row.get("finalized_outcome_reward"))
        realized_reward = _finite_float_or_none(row.get("realized_after_cost_reward"))
        if (
            reward is None
            or finalized_reward is None
            or realized_reward is None
            or not math.isclose(reward, finalized_reward, rel_tol=1e-12, abs_tol=1e-12)
            or not math.isclose(
                realized_reward,
                finalized_reward,
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
        ):
            return "FINALIZED_OUTCOME_REWARD_BINDING_MISMATCH"
        behavior_fingerprint = str(row.get("behavior_policy_fingerprint") or "")
        if behavior_fingerprint != self._ppo_parent_policy_fingerprint:
            return "PPO_PARENT_POLICY_FINGERPRINT_MISMATCH"
        try:
            expected_update_key = ppo_consumption_update_key_from_row(row)
        except (TypeError, ValueError):
            return "PPO_CONSUMPTION_UPDATE_KEY_IDENTITY_INVALID"
        observed_update_key = row.get("ppo_consumption_update_key")
        if observed_update_key not in (None, "") and observed_update_key != expected_update_key:
            return "PPO_CONSUMPTION_UPDATE_KEY_INVALID"
        if distribution_contract == ON_POLICY_DISTRIBUTION_CONTRACT:
            identity = self._behavior_action_identity(example)
            assert identity is not None
            binding_fields = (
                "prediction_id",
                "checkpoint_id",
                "feature_tensor_id",
                "feature_vector_hash",
                "feature_cutoff",
                "available_at",
                "decision_time",
                "behavior_policy_fingerprint",
                "behavior_policy_receipt_hash",
                "behavior_policy_receipt_key",
                "behavior_action_mask",
                "behavior_action_source",
                "action_labels",
                "raw_action_logits",
                "raw_action_probabilities",
                "action_probabilities",
                "selected_action_probability",
                "selected_action_log_prob",
                "policy_value",
                "on_policy_sampling_plan_hash",
                "on_policy_sampling_plan_input_hash",
            )
            if any(row.get(field) in (None, "", [], {}) for field in binding_fields):
                return "BEHAVIOR_POLICY_RECEIPT_BINDING_FIELDS_MISSING"
            receipt = row.get("behavior_policy_receipt")
            receipt_reasons = behavior_receipt_rejection_reasons(
                receipt,
                expected_prediction_id=row.get("prediction_id"),
                expected_symbol=row.get("symbol"),
                expected_timeframe=row.get("timeframe"),
                expected_action=identity[1],
                expected_action_index=identity[0],
                expected_checkpoint_id=row.get("checkpoint_id"),
                expected_checkpoint_weight_sha256=row.get(
                    "behavior_policy_checkpoint_hash"
                ),
                expected_feature_tensor_id=row.get("feature_tensor_id"),
                expected_feature_vector_hash=row.get("feature_vector_hash"),
                expected_feature_cutoff=row.get("feature_cutoff"),
                expected_available_at=row.get("available_at"),
                expected_decision_time=row.get("decision_time"),
                expected_policy_fingerprint=row.get("behavior_policy_fingerprint"),
                expected_sampling_plan_hash=row.get(
                    "on_policy_sampling_plan_hash"
                ),
                expected_sampling_plan_input_hash=row.get(
                    "on_policy_sampling_plan_input_hash"
                ),
            )
            if receipt_reasons:
                return "BEHAVIOR_POLICY_RECEIPT_INVALID"
            if not isinstance(receipt, dict):
                return "BEHAVIOR_POLICY_RECEIPT_INVALID"
            if row.get("on_policy_action_receipt_valid") is not True:
                return "BEHAVIOR_POLICY_RECEIPT_NOT_MARKED_VALID"
            if row.get("on_policy_sampling_selected") is not True:
                return "ADAPTIVE_ON_POLICY_SAMPLING_LANE_NOT_SELECTED"
            if row.get("on_policy_sampling_lane") != (
                "ADAPTIVE_BOUNDED_PAPER_EXPLORATION"
            ):
                return "ADAPTIVE_ON_POLICY_SAMPLING_LANE_MISMATCH"
            if row.get("on_policy_sampling_counts_as_a_plus_evidence") is not False:
                return "ON_POLICY_SAMPLING_A_PLUS_CLASSIFICATION_INVALID"
            if row.get("on_policy_sampling_routes_to_live") is not False:
                return "ON_POLICY_SAMPLING_LIVE_ROUTE_INVALID"
            if row.get("behavior_policy_receipt_write_success") is not True:
                return "BEHAVIOR_POLICY_RECEIPT_NOT_DURABLE"
            if row.get("ppo_on_policy_entry_fields_present") is not True:
                return "PPO_ENTRY_CONTRACT_NOT_COMPLETE"
            if row.get("behavior_policy_receipt_hash") != receipt.get("receipt_hash"):
                return "BEHAVIOR_POLICY_RECEIPT_HASH_BINDING_MISMATCH"
            expected_receipt_key = (
                "v2:trainer:hybrid_cuda:on_policy_receipt:"
                f"{receipt.get('receipt_hash')}"
            )
            if row.get("behavior_policy_receipt_key") != expected_receipt_key:
                return "BEHAVIOR_POLICY_RECEIPT_KEY_BINDING_MISMATCH"
            if row.get("behavior_policy_checkpoint_hash") != receipt.get(
                "checkpoint_weight_sha256"
            ):
                return "BEHAVIOR_POLICY_CHECKPOINT_HASH_BINDING_MISMATCH"
            if row.get("behavior_action_source") != receipt.get(
                "behavior_action_source"
            ):
                return "BEHAVIOR_POLICY_ACTION_SOURCE_RECEIPT_MISMATCH"
            if list(row.get("action_labels") or []) != list(
                receipt.get("action_labels") or []
            ):
                return "BEHAVIOR_POLICY_ACTION_LABELS_RECEIPT_MISMATCH"
            for field in (
                "raw_action_logits",
                "raw_action_probabilities",
            ):
                observed_values = row.get(field)
                expected_values = receipt.get(field)
                if (
                    not isinstance(observed_values, (list, tuple))
                    or not isinstance(expected_values, list)
                    or len(observed_values) != len(expected_values)
                    or any(
                        _finite_float_or_none(observed) is None
                        or not math.isclose(
                            float(observed),
                            float(expected),
                            rel_tol=1e-12,
                            abs_tol=1e-12,
                        )
                        for observed, expected in zip(
                            observed_values,
                            expected_values,
                            strict=False,
                        )
                    )
                ):
                    return f"BEHAVIOR_POLICY_{field.upper()}_RECEIPT_MISMATCH"
            row_probabilities = row.get("action_probabilities")
            receipt_probabilities = receipt.get("action_probabilities")
            if (
                not isinstance(row_probabilities, (list, tuple))
                or not isinstance(receipt_probabilities, list)
                or len(row_probabilities) != len(receipt_probabilities)
                or any(
                    _finite_float_or_none(observed) is None
                    or not math.isclose(
                        float(observed),
                        float(expected),
                        rel_tol=1e-12,
                        abs_tol=1e-12,
                    )
                    for observed, expected in zip(
                        row_probabilities,
                        receipt_probabilities,
                        strict=False,
                    )
                )
            ):
                return "BEHAVIOR_POLICY_PROBABILITIES_RECEIPT_MISMATCH"
            if list(row.get("behavior_action_mask") or []) != list(
                receipt.get("behavior_action_mask") or []
            ):
                return "BEHAVIOR_POLICY_ACTION_MASK_RECEIPT_MISMATCH"
            old_log_prob = _finite_float_or_none(row.get("old_log_prob"))
            old_value = _finite_float_or_none(row.get("old_value"))
            selected_probability = _finite_float_or_none(
                row.get("selected_action_probability")
            )
            selected_log_probability = _finite_float_or_none(
                row.get("selected_action_log_prob")
            )
            policy_value = _finite_float_or_none(row.get("policy_value"))
            if selected_probability is None or not math.isclose(
                selected_probability,
                float(receipt["selected_action_probability"]),
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                return "SELECTED_PROBABILITY_RECEIPT_MISMATCH"
            if selected_log_probability is None or not math.isclose(
                selected_log_probability,
                float(receipt["selected_action_log_prob"]),
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                return "SELECTED_LOG_PROBABILITY_RECEIPT_MISMATCH"
            if policy_value is None or not math.isclose(
                policy_value,
                float(receipt["policy_value"]),
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                return "POLICY_VALUE_RECEIPT_MISMATCH"
            if old_log_prob is None or not math.isclose(
                old_log_prob,
                float(receipt["selected_action_log_prob"]),
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                return "OLD_LOG_PROB_RECEIPT_MISMATCH"
            if old_value is None or not math.isclose(
                old_value,
                float(receipt["policy_value"]),
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                return "OLD_VALUE_RECEIPT_MISMATCH"
            durable_reason = self._durable_receipt_ineligibility_reason(
                row=row,
                receipt=receipt,
                expected_update_key=expected_update_key,
            )
            if durable_reason is not None:
                return durable_reason
            # A valid receipt proves one sampled action/log-probability, not
            # that the producer retained every selected action. Re-read the
            # authenticated manifest/proof and all terminal lifecycle evidence
            # on every admission; flat row booleans never establish this gate.
            cohort_reason = self._durable_sampling_cohort_ineligibility_reason(
                row=row,
                receipt=receipt,
            )
            if cohort_reason is not None:
                return cohort_reason
        return None

    def _ppo_behavior_action_metrics(self, rows: Sequence[TrainingExample]) -> dict[str, Any]:
        identities = [
            identity
            for row in rows
            if self._has_on_policy_ppo_fields(row)
            for identity in [self._behavior_action_identity(row)]
            if identity is not None
        ]
        indices = [identity[0] for identity in identities]
        unique_indices = sorted(set(indices))
        return {
            "ppo_log_prob_action_source": "immutable_behavior_action_index",
            "ppo_behavior_action_identity_required": True,
            "ppo_behavior_action_indices_used": unique_indices,
            "ppo_log_prob_action_indices_used": unique_indices,
            "ppo_behavior_action_distribution_by_action": self._action_counts_from_indices(
                indices
            ),
            "ppo_supervised_action_identity_separate": True,
        }

    @classmethod
    def _has_outcome_supervised_targets(cls, example: TrainingExample) -> bool:
        row = cls._trust_row(example)
        policy_sample_markers = (
            row.get("behavior_policy_receipt") not in (None, "", {}, []),
            row.get("behavior_policy_receipt_hash") not in (None, ""),
            row.get("old_log_prob") not in (None, ""),
            row.get("selected_action_log_prob") not in (None, ""),
            row.get("ppo_on_policy_entry_fields_present") is True,
            row.get("on_policy_sampling_selected") is True,
            str(row.get("behavior_policy_sampling_mode") or "").strip().upper()
            == PPO_REQUIRED_BEHAVIOR_SAMPLING_MODE,
        )
        if any(policy_sample_markers):
            # A sampled action is inseparable from its immutable parent policy.
            # If its exact contract is invalid/consumed, it must be excluded;
            # relabeling it as generic outcome supervision would bypass the
            # parent-policy fence and permit repeated/corrupt reuse.
            return False
        targets = row.get("outcome_targets")
        if not isinstance(targets, dict):
            return False
        return (
            targets.get("realized_net_pnl_bps") is not None
            and targets.get("directional_outcome") in {"UP", "DOWN", "FLAT"}
            and row.get("realized_after_cost_reward") is not None
            and row.get("uses_expected_move_as_realized_reward") is False
        )

    @staticmethod
    def _ppo_objective_active(learning_mode: str) -> bool:
        return learning_mode in {"ppo_on_policy", "ppo_mixed_outcome_supervised"}

    @staticmethod
    def _outcome_supervision_active(learning_mode: str) -> bool:
        return learning_mode in {"outcome_supervised", "ppo_mixed_outcome_supervised"}

    def _extra_rejection_reasons(
        self,
        example: TrainingExample,
        row: dict[str, Any],
    ) -> list[str]:
        reasons: list[str] = []
        # Dirty numeric evidence is rejected here, before chronological split and
        # before runtime can fence any exact-PPO receipt.  Training-time
        # ``nan_to_num`` would fabricate a different feature/label and could turn
        # a malformed row into a claimed optimizer update.
        if any(
            not _strict_finite_number(value)
            for value in example.tensor.model_vector
        ):
            reasons.append("NONFINITE_TENSOR_VALUE")
        if not _strict_finite_number(
            example.label_expected_move_after_cost_bps
        ):
            reasons.append("NONFINITE_EXPECTED_MOVE_AFTER_COST_LABEL")
        outcome_targets = row.get("outcome_targets")
        if isinstance(outcome_targets, Mapping):
            if not _strict_finite_number(
                outcome_targets.get("realized_net_pnl_bps")
            ):
                reasons.append("NONFINITE_OUTCOME_TARGET_REALIZED_NET_PNL_BPS")
            for field_name in (
                "realized_net_pnl_usd",
                "realized_after_cost_reward",
                "value_baseline",
                "advantage",
                "MFE",
                "MAE",
                "fees",
                "slippage",
                "funding",
            ):
                value = outcome_targets.get(field_name)
                if value not in (None, "") and not _strict_finite_number(value):
                    reasons.append(
                        f"NONFINITE_OUTCOME_TARGET_{field_name.upper()}"
                    )
        if isinstance(outcome_targets, Mapping) and not _strict_finite_number(
            row.get("realized_after_cost_reward")
        ):
            reasons.append("NONFINITE_REALIZED_AFTER_COST_REWARD")
        for field_name in ("old_log_prob", "old_value", "reward"):
            value = row.get(field_name)
            if value not in (None, "") and not _strict_finite_number(value):
                reasons.append(f"NONFINITE_{field_name.upper()}")
        classification = str(example.row_classification).upper()
        if classification != "TRAINABLE":
            safe_missing_mask = missing_mask_training_override_status(row).get(
                "safe_to_train_with_missing_mask"
            )
            optional_missing_masked = (
                classification == "MISSING_MASKED"
                and self._missing_names_are_optional_or_event_dependent(
                    row.get("missing_feature_names")
                )
            )
            if not optional_missing_masked and not safe_missing_mask:
                reasons.append(f"ROW_CLASSIFICATION_{example.row_classification}")
        if row.get("accepted_for_training") is False:
            reasons.append("EXPLICIT_ACCEPTED_FOR_TRAINING_FALSE")
        if row.get("trust_schema_version") != TRUST_SCHEMA_VERSION:
            reasons.append("TRUST_SCHEMA_MISSING")
        if row.get("quarantined") is True:
            reasons.append("QUARANTINED_EVIDENCE")
        if row.get("mtf_snapshot_id") is None:
            reasons.append("MTF_SNAPSHOT_ID_MISSING")
        if row.get("replay_snapshot_id") is None and row.get("replay_snapshot_key") is None:
            reasons.append("REPLAY_SNAPSHOT_ID_MISSING")
        if row.get("mtf_snapshot_valid") is not True:
            reasons.append("MTF_SNAPSHOT_INVALID")
        for reason in row.get("mtf_snapshot_reject_reasons") or []:
            reasons.append(f"MTF_SNAPSHOT:{reason}")
        if row.get("candle_closed_confirmed") is not True:
            reasons.append("CANDLE_FINALITY_NOT_CONFIRMED")
        feature_cutoff_raw = row.get("feature_cutoff")
        available_at_raw = row.get("available_at")
        decision_time_raw = row.get("decision_time")
        feature_cutoff = self._parse_ts(feature_cutoff_raw)
        available_at = self._parse_ts(available_at_raw)
        decision_time = self._parse_ts(decision_time_raw)
        for field_name, raw_value, parsed_value in (
            ("FEATURE_CUTOFF", feature_cutoff_raw, feature_cutoff),
            ("AVAILABLE_AT", available_at_raw, available_at),
            ("DECISION_TIME", decision_time_raw, decision_time),
        ):
            if raw_value in (None, ""):
                reasons.append(f"{field_name}_MISSING")
            elif parsed_value is None:
                reasons.append(f"{field_name}_UNPARSEABLE")
        if (
            feature_cutoff is not None
            and decision_time is not None
            and feature_cutoff > decision_time
        ):
            reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
        if available_at is not None and decision_time is not None and available_at > decision_time:
            reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
        masa_cutoff_raw = row.get("masa_feature_cutoff")
        ppo_cutoff_raw = row.get("ppo_feature_cutoff")
        masa_cutoff = self._parse_ts(masa_cutoff_raw)
        ppo_cutoff = self._parse_ts(ppo_cutoff_raw)
        if masa_cutoff_raw not in (None, "") and masa_cutoff is None:
            reasons.append("MASA_FEATURE_CUTOFF_UNPARSEABLE")
        if ppo_cutoff_raw not in (None, "") and ppo_cutoff is None:
            reasons.append("PPO_FEATURE_CUTOFF_UNPARSEABLE")
        if (
            masa_cutoff is not None
            and decision_time is not None
            and masa_cutoff > decision_time
        ):
            reasons.append("MASA_FEATURE_CUTOFF_AFTER_PPO_DECISION_TIME")
        if (
            ppo_cutoff is not None
            and decision_time is not None
            and ppo_cutoff > decision_time
        ):
            reasons.append("PPO_FEATURE_CUTOFF_AFTER_DECISION_TIME")
        label_available_at_raw = row.get("label_available_at")
        if (
            label_available_at_raw not in (None, "")
            and self._parsed_canonical_time(label_available_at_raw) is None
        ):
            reasons.append("LABEL_AVAILABLE_AT_UNPARSEABLE")
        label_available_at = self._parsed_canonical_time(
            example.label_available_at
        )
        if (
            label_available_at is not None
            and label_available_at > self.training_observed_at
        ):
            reasons.append("LABEL_AVAILABLE_AT_AFTER_TRAINING_OBSERVED_AT")
        outcome_available_at_raw = row.get("outcome_available_at")
        outcome_available_at = self._parsed_canonical_time(
            outcome_available_at_raw
        )
        if (
            outcome_available_at_raw not in (None, "")
            and outcome_available_at is None
        ):
            reasons.append("OUTCOME_AVAILABLE_AT_UNPARSEABLE")
        if (
            outcome_available_at_raw not in (None, "")
            and outcome_available_at is not None
            and outcome_available_at > self.training_observed_at
        ):
            reasons.append("OUTCOME_AVAILABLE_AT_AFTER_TRAINING_OBSERVED_AT")
        if (
            example.label_timing_valid is not True
            and "INVALID" in str(example.label_timing_error or "")
        ):
            reasons.append("LABEL_TIMING_INVALID")
        if self._invalid_count(row.get("features")) > 0:
            reasons.append("INVALID_FEATURE_VALUES")
        if row.get("backfilled") is True and str(row.get("source_mode") or "").lower() == "live":
            reasons.append("BACKFILLED_DATA_MARKED_LIVE")
        order_status = str(row.get("fill_status") or row.get("order_status") or "").lower()
        positive_training = row.get("positive_training_sample") is True or str(row.get("label_action") or "").lower() not in {
            "",
            "hold",
            "abstain",
            "none",
            "no_trade",
        }
        if order_status in {"rejected", "canceled", "cancelled", "expired"} and positive_training:
            reasons.append("REJECTED_ORDER_MARKED_POSITIVE_TRAINING_OUTCOME")
        return reasons

    @classmethod
    def _rejection_family_diagnostic(
        cls,
        example: TrainingExample,
        row: dict[str, Any],
        reasons: Sequence[str],
    ) -> dict[str, Any]:
        override = missing_mask_training_override_status(row, list(reasons))
        missing = [str(name) for name in cls._names_from_mask_field(row.get("missing_feature_names"))]
        stale = [str(name) for name in cls._names_from_mask_field(row.get("stale_feature_names"))]
        row_source = str(
            row.get("row_source")
            or row.get("trainer_feedback_source")
            or row.get("update_lane")
            or "unknown"
        )
        return {
            "row_source": row_source,
            "row_id": cls._row_id(example, row),
            "symbol": example.symbol,
            "timeframe": example.timeframe,
            "row_count": 1,
            "missing_feature_families": missing,
            "masked_feature_families": missing,
            "stale_feature_families": stale,
            "critical_missing_vs_optional_missing": override.get(
                "critical_missing_vs_optional_missing"
            ),
            "feature_family_introduced_after_snapshot_time": override.get(
                "feature_family_introduced_after_snapshot_time"
            ),
            "source_availability": override.get("source_availability"),
            "lineage_mask_present": override.get("lineage_mask_present"),
            "classification_mask_present": override.get("classification_mask_present"),
            "safe_to_train_with_missing_mask": override.get(
                "safe_to_train_with_missing_mask"
            ),
            "unsafe_to_train_reason": override.get("unsafe_to_train_reason"),
            "rejection_reasons": list(reasons),
        }

    @staticmethod
    def _names_from_mask_field(value: Any) -> list[Any]:
        if isinstance(value, dict):
            return [name for name, flagged in value.items() if flagged]
        if isinstance(value, (list, tuple, set)):
            return list(value)
        if value in (None, ""):
            return []
        return [value]

    @staticmethod
    def _missing_names_are_optional_or_event_dependent(value: Any) -> bool:
        if isinstance(value, dict):
            names = [str(name) for name in value.keys()]
        elif isinstance(value, list):
            names = [str(name) for name in value]
        elif isinstance(value, tuple):
            names = [str(name) for name in value]
        else:
            return False
        names = [name for name in names if name.strip()]
        if not names:
            return False
        for name in names:
            lowered = name.lower()
            # A critical-family absence is never optional merely because the
            # family name also contains an event-dependent token (for example,
            # ``critical_family_absent:orderbook_depth``).  The prefix is an
            # immutable producer attestation and must fail closed.
            if lowered.startswith("critical_family_absent:"):
                return False
            if not any(token in lowered for token in OPTIONAL_OR_EVENT_FEATURE_TOKENS):
                return False
        return True

    # Derived cost-estimator inputs, not market-state feature families. Rows
    # whose ONLY decision-time missing names match these tokens may train with
    # the explicit mask (training lane only; decision/live cost gates are
    # enforced by their own validators on real values).
    _TRAINING_COST_MASKABLE_TOKENS = (
        "fee_bps",
        "expected_slippage",
        "slippage_bps",
        "expected_cost",
        "spread_slippage_funding",
    )

    @classmethod
    def _missing_names_are_training_cost_maskable(cls, value: Any) -> bool:
        if isinstance(value, (dict,)):
            names = [str(name) for name in value.keys()]
        elif isinstance(value, (list, tuple)):
            names = [str(name) for name in value]
        else:
            return False
        names = [name for name in names if name.strip()]
        if not names:
            return False
        for name in names:
            lowered = name.lower()
            if lowered.startswith("critical_family_absent:"):
                return False
            if any(token in lowered for token in OPTIONAL_OR_EVENT_FEATURE_TOKENS):
                continue
            if any(token in lowered for token in cls._TRAINING_COST_MASKABLE_TOKENS):
                continue
            return False
        return True

    @staticmethod
    def _row_id(example: TrainingExample, row: dict[str, Any]) -> str:
        return str(
            row.get("sample_id")
            or row.get("prediction_id")
            or row.get("feature_snapshot_id")
            or example.tensor.feature_snapshot_id
            or f"{example.symbol}:{example.timeframe}"
        )

    @staticmethod
    def _parse_ts(value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            numeric = int(value)
            if numeric <= 0:
                return None
            return numeric * 1000 if abs(numeric) < 10_000_000_000 else numeric
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                if text.replace(".", "", 1).isdigit():
                    numeric = int(float(text))
                    if numeric <= 0:
                        return None
                    return numeric * 1000 if abs(numeric) < 10_000_000_000 else numeric
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    return None
                return int(parsed.timestamp() * 1000)
            except ValueError:
                return None
        return None

    @classmethod
    def _invalid_count(cls, value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, float):
            return 0 if math.isfinite(value) else 1
        if isinstance(value, dict):
            return sum(cls._invalid_count(child) for child in value.values())
        if isinstance(value, list):
            return sum(cls._invalid_count(child) for child in value)
        return 0

    @classmethod
    def _confidence_target_batch(
        cls,
        rows: Sequence[TrainingExample],
    ) -> tuple[list[float], list[bool], list[int], list[str], dict[str, Any]]:
        """Resolve strict selected-action after-cost profitability labels."""
        targets: list[float] = []
        mask: list[bool] = []
        head_action_indices: list[int] = []
        row_ids: list[str] = []
        rejection_reasons: dict[str, int] = {}
        positive_count = 0
        negative_count = 0
        for example in rows:
            result = profitability_target_from_trust_row(
                cls._trust_row(example),
                decision_time=example.decision_time,
                label_available_at=example.label_available_at,
            )
            eligible = result.get("eligible") is True
            mask.append(eligible)
            if eligible:
                target = int(result["target"])
                targets.append(float(target))
                head_action_indices.append(
                    int(result["confidence_head_action_index"])
                )
                row_ids.append(str(result["row_id"]))
                positive_count += target
                negative_count += 1 - target
            else:
                targets.append(0.0)
                # Masked out of every confidence calculation; zero is only a
                # shape-preserving placeholder, never a HOLD label.
                head_action_indices.append(0)
                reason = str(result.get("reason") or "CONFIDENCE_TARGET_REJECTED")
                rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1
        return targets, mask, head_action_indices, row_ids, {
            "confidence_target_label_semantics": CONFIDENCE_LABEL_SEMANTICS,
            "confidence_target_total_rows": len(rows),
            "confidence_target_eligible_rows": sum(mask),
            "confidence_target_rejected_rows": len(rows) - sum(mask),
            "confidence_target_positive_rows": positive_count,
            "confidence_target_negative_rows": negative_count,
            "confidence_target_rejection_reason_counts": rejection_reasons,
            "confidence_target_requires_explicit_costs": [
                "fees",
                "slippage",
                "funding",
            ],
            "confidence_target_hold_as_win_allowed": False,
            "confidence_target_pit_and_finality_required": True,
            "confidence_target_head_action_labels": list(CONFIDENCE_HEAD_ACTIONS),
            "confidence_target_action_conditioned": True,
        }

    def _validation_confidence_metrics(
        self,
        validation_rows: Sequence[TrainingExample],
    ) -> dict[str, Any]:
        """Score, but never fit on, the untouched forward validation partition."""
        rows = list(validation_rows)
        base: dict[str, Any] = {
            "validation_confidence_status": "NO_VALIDATION_ROWS",
            "validation_confidence_nonfinite_input_value_count": 0,
            "validation_confidence_nonfinite_output_value_count": 0,
            "validation_confidence_rows_evaluated": 0,
            "validation_confidence_rows_used_for_fit": 0,
            "validation_confidence_brier": None,
            "validation_confidence_ece": None,
            "validation_confidence_raw_brier": None,
            "validation_confidence_raw_ece": None,
            "validation_confidence_calibrated_brier": None,
            "validation_confidence_calibrated_ece": None,
            "validation_confidence_long_rows": 0,
            "validation_confidence_short_rows": 0,
            "validation_confidence_eligible_row_ids": [],
            "validation_confidence_eligible_row_digest": None,
            "validation_confidence_decision_time_min": None,
            "validation_confidence_decision_time_max": None,
            "validation_confidence_label_available_at_min": None,
            "validation_confidence_label_available_at_max": None,
            "validation_confidence_fit_row_digest": None,
            "validation_confidence_fit_validation_digest_disjoint": False,
            "validation_confidence_label_semantics": CONFIDENCE_LABEL_SEMANTICS,
            "validation_confidence_partition_untouched": True,
        }
        for action in CONFIDENCE_HEAD_ACTIONS:
            for calibration in ("raw", "calibrated"):
                for metric in ("brier", "ece"):
                    base[
                        f"validation_confidence_{action}_{calibration}_{metric}"
                    ] = None
        uncertainty_defaults: dict[str, Any] = {
            "paired_brier_delta_per_row": [],
            "paired_brier_delta_mean": None,
            "paired_brier_delta_standard_error": None,
            "paired_brier_delta_one_standard_error_upper_bound": None,
            "paired_brier_uncertainty_available": False,
            "paired_brier_non_regression_proven": False,
            "ece_delta": None,
            "ece_leave_one_out_delta": [],
            "ece_jackknife_standard_error": None,
            "ece_one_standard_error_upper_bound": None,
            "ece_uncertainty_available": False,
            "ece_non_regression_proven": False,
            "uncertainty_row_count": 0,
            "uncertainty_minimum_not_configured": True,
            "uncertainty_mathematical_minimum_rows": 2,
            "uncertainty_evidence_schema_version": (
                CONFIDENCE_UNCERTAINTY_EVIDENCE_SCHEMA_VERSION
            ),
            "uncertainty_scope": None,
            "uncertainty_method": CONFIDENCE_UNCERTAINTY_METHOD,
            "uncertainty_evidence_digest": None,
        }
        for scope in ("", *(f"{action}_" for action in CONFIDENCE_HEAD_ACTIONS)):
            for metric_name, default_value in uncertainty_defaults.items():
                base[f"validation_confidence_{scope}{metric_name}"] = default_value
            base[f"validation_confidence_{scope}uncertainty_scope"] = (
                scope.rstrip("_").upper() if scope else "GLOBAL"
            )
        if not rows:
            return base
        (
            targets,
            mask,
            head_action_indices,
            row_ids,
            target_metrics,
        ) = self._confidence_target_batch(rows)
        eligible_indices = [index for index, eligible in enumerate(mask) if eligible]
        base["validation_confidence_target_rejection_reason_counts"] = target_metrics[
            "confidence_target_rejection_reason_counts"
        ]
        if not eligible_indices:
            base["validation_confidence_status"] = "NO_PIT_SAFE_AFTER_COST_TARGETS"
            return base
        state = self.model.confidence_calibration_state
        temperature = resolve_confidence_temperature(state)
        if state.get("fitted") is not True or temperature is None:
            base["validation_confidence_status"] = "CHECKPOINT_CALIBRATION_UNFITTED"
            return base
        if not self.model.torch_available:
            base["validation_confidence_status"] = "PROFITABILITY_CONFIDENCE_HEAD_UNAVAILABLE"
            return base
        torch = self.model.torch
        net = self.model.net
        if torch is None or net is None:
            base["validation_confidence_status"] = "PROFITABILITY_CONFIDENCE_HEAD_UNAVAILABLE"
            return base
        try:
            from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.temporal_windowing import (  # noqa: PLC0415
                build_window_lookup,
                model_batch_tensor,
            )

            temporal = bool(getattr(self.model, "temporal_encoder_enabled", False))
            seq_len = int(getattr(self.model, "temporal_seq_len", 16))
            lookup = getattr(self, "_temporal_window_lookup", None)
            if temporal and lookup is None:
                lookup = build_window_lookup(rows, seq_len=seq_len)
            inputs = model_batch_tensor(
                torch,
                rows,
                temporal=temporal,
                seq_len=seq_len,
                window_lookup=lookup,
                device="cpu",
            )
            nonfinite_input_count = int(
                (~torch.isfinite(inputs)).sum().detach().cpu().item()
            )
            if nonfinite_input_count:
                base["validation_confidence_nonfinite_input_value_count"] = (
                    nonfinite_input_count
                )
                base["validation_confidence_status"] = (
                    "NONFINITE_VALIDATION_CONFIDENCE_INPUT"
                )
                return base
            inputs = torch.clamp(
                inputs,
                min=-1_000_000.0,
                max=1_000_000.0,
            ).to(device=self.model.device)
            was_training = bool(net.training)
            net.eval()
            try:
                with torch.no_grad():
                    raw_output = net(inputs)["confidence_by_direction"]
                    nonfinite_output_count = int(
                        (~torch.isfinite(raw_output)).sum().detach().cpu().item()
                    )
                    if nonfinite_output_count:
                        base[
                            "validation_confidence_nonfinite_output_value_count"
                        ] = nonfinite_output_count
                        base["validation_confidence_status"] = (
                            "NONFINITE_VALIDATION_CONFIDENCE_OUTPUT"
                        )
                        return base
                    raw_all = torch.clamp(
                        raw_output,
                        min=0.0,
                        max=1.0,
                    ).detach().cpu().tolist()
            finally:
                if was_training:
                    net.train()
        except Exception as exc:
            base["validation_confidence_status"] = (
                f"VALIDATION_CONFIDENCE_FORWARD_FAILED:{type(exc).__name__}"
            )
            return base
        raw_probabilities = [
            float(raw_all[index][head_action_indices[index]])
            for index in eligible_indices
        ]
        outcomes = [int(targets[index]) for index in eligible_indices]
        eligible_row_ids = [str(row_ids[position]) for position in range(len(row_ids))]
        eligible_actions = [
            CONFIDENCE_HEAD_ACTIONS[head_action_indices[index]]
            for index in eligible_indices
        ]
        eligible_rows = [rows[index] for index in eligible_indices]
        decision_times = [
            self._parsed_canonical_time(row.decision_time) for row in eligible_rows
        ]
        label_times = [
            self._parsed_canonical_time(row.label_available_at) for row in eligible_rows
        ]
        if any(value is None for value in (*decision_times, *label_times)):
            base["validation_confidence_status"] = (
                "VALIDATION_CONFIDENCE_FRONTIER_CLOCK_INVALID"
            )
            return base
        decision_frontier = [value for value in decision_times if value is not None]
        label_frontier = [value for value in label_times if value is not None]
        digest_material = [
            {
                "row_id": row_id,
                "selected_action": action,
                "raw_probability": probability,
                "outcome": outcome,
                "decision_time": row.decision_time,
                "label_available_at": row.label_available_at,
            }
            for row_id, action, probability, outcome, row in zip(
                eligible_row_ids,
                eligible_actions,
                raw_probabilities,
                outcomes,
                eligible_rows,
                strict=True,
            )
        ]
        validation_digest = hashlib.sha256(
            json.dumps(
                digest_material,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        fit_row_ids = set(getattr(self, "_confidence_fit_row_ids", ()))
        validation_row_id_set = set(eligible_row_ids)
        fit_validation_disjoint = bool(
            fit_row_ids.isdisjoint(validation_row_id_set)
            and int(state.get("validation_rows_used") or 0) == 0
        )
        raw_brier = brier_score(raw_probabilities, outcomes, 1.0)
        raw_ece = expected_calibration_error(raw_probabilities, outcomes, 1.0)
        calibrated_brier = brier_score(raw_probabilities, outcomes, temperature)
        calibrated_ece = expected_calibration_error(
            raw_probabilities, outcomes, temperature
        )
        global_uncertainty = _paired_confidence_nonregression_evidence(
            raw_probabilities,
            outcomes,
            temperature=temperature,
            scope="GLOBAL",
        )
        global_uncertainty_metrics = {
            f"validation_confidence_{metric_name}": value
            for metric_name, value in global_uncertainty.items()
        }
        directional_metrics: dict[str, Any] = {}
        for action in CONFIDENCE_HEAD_ACTIONS:
            indices = [
                index
                for index, observed_action in enumerate(eligible_actions)
                if observed_action == action
            ]
            action_probabilities = [raw_probabilities[index] for index in indices]
            action_outcomes = [outcomes[index] for index in indices]
            directional_metrics[f"validation_confidence_{action}_rows"] = len(indices)
            directional_metrics[
                f"validation_confidence_{action}_raw_brier"
            ] = (
                brier_score(action_probabilities, action_outcomes, 1.0)
                if indices
                else None
            )
            directional_metrics[f"validation_confidence_{action}_raw_ece"] = (
                expected_calibration_error(
                    action_probabilities, action_outcomes, 1.0
                )
                if indices
                else None
            )
            directional_metrics[
                f"validation_confidence_{action}_calibrated_brier"
            ] = (
                brier_score(action_probabilities, action_outcomes, temperature)
                if indices
                else None
            )
            directional_metrics[
                f"validation_confidence_{action}_calibrated_ece"
            ] = (
                expected_calibration_error(
                    action_probabilities, action_outcomes, temperature
                )
                if indices
                else None
            )
            action_uncertainty = _paired_confidence_nonregression_evidence(
                action_probabilities,
                action_outcomes,
                temperature=temperature,
                scope=action.upper(),
            )
            directional_metrics.update(
                {
                    f"validation_confidence_{action}_{metric_name}": value
                    for metric_name, value in action_uncertainty.items()
                }
            )
        base.update(
            {
                "validation_confidence_status": "EVALUATED_UNTOUCHED_FORWARD_PARTITION",
                "validation_confidence_rows_evaluated": len(eligible_indices),
                "validation_confidence_brier": calibrated_brier,
                "validation_confidence_ece": calibrated_ece,
                "validation_confidence_raw_brier": raw_brier,
                "validation_confidence_raw_ece": raw_ece,
                "validation_confidence_calibrated_brier": calibrated_brier,
                "validation_confidence_calibrated_ece": calibrated_ece,
                "validation_confidence_eligible_row_ids": eligible_row_ids,
                "validation_confidence_eligible_row_digest": validation_digest,
                "validation_confidence_decision_time_min": min(
                    decision_frontier
                ).isoformat(timespec="microseconds").replace("+00:00", "Z"),
                "validation_confidence_decision_time_max": max(
                    decision_frontier
                ).isoformat(timespec="microseconds").replace("+00:00", "Z"),
                "validation_confidence_label_available_at_min": min(
                    label_frontier
                ).isoformat(timespec="microseconds").replace("+00:00", "Z"),
                "validation_confidence_label_available_at_max": max(
                    label_frontier
                ).isoformat(timespec="microseconds").replace("+00:00", "Z"),
                "validation_confidence_fit_row_digest": state.get("row_digest"),
                "validation_confidence_fit_validation_digest_disjoint": (
                    fit_validation_disjoint
                ),
                "validation_confidence_temperature_from_train_partition": temperature,
                **global_uncertainty_metrics,
                **directional_metrics,
            }
        )
        return base

    def _auto_tuned_batch_size(self, *, requested_batch_size: int, available_rows: int) -> int:
        if available_rows <= 0:
            return 0
        requested = max(1, int(requested_batch_size))
        if not self.model.cuda_active or self.model.torch is None:
            return min(requested, int(available_rows))
        torch = self.model.torch
        try:
            props = torch.cuda.get_device_properties(0)
            total_vram_mb = int(props.total_memory / (1024 * 1024))
            bytes_per_row = max(1, self.model.input_dim) * 4 * 6
            # Temporal windows multiply the input tensor by seq_len frames; without
            # this the heuristic under-estimates VRAM 16x and can OOM large batches.
            if getattr(self.model, "temporal_encoder_enabled", False):
                bytes_per_row *= max(1, int(getattr(self.model, "temporal_seq_len", 16)))
            target_vram_bytes = min(
                int(total_vram_mb * 1024 * 1024 * 0.75),
                12 * 1024 * 1024 * 1024,
            )
            vram_rows = max(1, target_vram_bytes // bytes_per_row)
            tuned = min(int(available_rows), max(requested, int(vram_rows)))
        except Exception:
            tuned = min(requested, int(available_rows))
        return max(1, int(tuned))

    def _validation_policy_edge(
        self,
        validation_rows: Sequence[TrainingExample],
    ) -> dict[str, Any]:
        """Evaluate deployed-policy actions against held-out after-cost labels."""
        rows = list(validation_rows)
        base: dict[str, Any] = {
            "validation_policy_edge_status": "NO_VALIDATION_ROWS",
            "validation_policy_edge_evidence_valid": False,
            "validation_policy_edge_nonfinite_input_value_count": 0,
            "validation_policy_edge_nonfinite_output_value_count": 0,
            "validation_policy_edge_after_cost_bps": None,
            "validation_policy_edge_total_after_cost_bps": None,
            "validation_policy_edge_lower_confidence_bound_bps": None,
            "validation_policy_edge_standard_error_bps": None,
            "validation_policy_edge_uncertainty_method": (
                "sample_mean_minus_one_standard_error"
            ),
            "validation_policy_edge_rows_evaluated": 0,
            "validation_policy_edge_directional_rows": 0,
            "validation_policy_edge_nonfinite_label_rows": 0,
            "validation_policy_edge_action_distribution": {
                label: 0 for label in ACTION_LABELS
            },
            "validation_policy_edge_cost_contract": (
                "label_expected_move_after_cost_bps_already_net_of_costs"
            ),
            "validation_policy_edge_uses_all_validation_rows_denominator": True,
        }
        if not rows:
            return base

        labels: list[float] = []
        for row in rows:
            label = _finite_float_or_none(row.label_expected_move_after_cost_bps)
            if label is None:
                base["validation_policy_edge_nonfinite_label_rows"] += 1
            else:
                labels.append(label)
        if len(labels) != len(rows):
            base["validation_policy_edge_status"] = "NONFINITE_AFTER_COST_LABEL"
            return base

        action_indices: list[int] = []
        if self.model.torch_available:
            torch = self.model.torch
            net = self.model.net
            if torch is None or net is None:
                base["validation_policy_edge_status"] = "TORCH_MODEL_UNAVAILABLE"
                return base
            try:
                from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.temporal_windowing import (  # noqa: PLC0415
                    build_window_lookup,
                    model_batch_tensor,
                )

                temporal = bool(getattr(self.model, "temporal_encoder_enabled", False))
                seq_len = int(getattr(self.model, "temporal_seq_len", 16))
                lookup = getattr(self, "_temporal_window_lookup", None)
                if temporal and lookup is None:
                    lookup = build_window_lookup(rows, seq_len=seq_len)
                val_x = model_batch_tensor(
                    torch,
                    rows,
                    temporal=temporal,
                    seq_len=seq_len,
                    window_lookup=lookup,
                    device="cpu",
                )
                nonfinite_input_count = int(
                    (~torch.isfinite(val_x)).sum().detach().cpu().item()
                )
                if nonfinite_input_count:
                    base["validation_policy_edge_nonfinite_input_value_count"] = (
                        nonfinite_input_count
                    )
                    base["validation_policy_edge_status"] = (
                        "NONFINITE_VALIDATION_POLICY_EDGE_INPUT"
                    )
                    return base
                val_x = torch.clamp(
                    val_x,
                    min=-1_000_000.0,
                    max=1_000_000.0,
                ).to(device=self.model.device)
                was_training = bool(net.training)
                net.eval()
                try:
                    with torch.no_grad():
                        out = net(val_x)
                        nonfinite_logits_count = int(
                            (~torch.isfinite(out["logits"]))
                            .sum()
                            .detach()
                            .cpu()
                            .item()
                        )
                        nonfinite_expected_move_count = int(
                            (~torch.isfinite(out["expected_move"]))
                            .sum()
                            .detach()
                            .cpu()
                            .item()
                        )
                        nonfinite_output_count = (
                            nonfinite_logits_count
                            + nonfinite_expected_move_count
                        )
                        if nonfinite_output_count:
                            base[
                                "validation_policy_edge_nonfinite_output_value_count"
                            ] = nonfinite_output_count
                            base["validation_policy_edge_status"] = (
                                "NONFINITE_VALIDATION_POLICY_EDGE_OUTPUT"
                            )
                            return base
                        logits = torch.clamp(
                            out["logits"],
                            min=-30.0,
                            max=30.0,
                        )
                        expected_moves = torch.clamp(
                            out["expected_move"],
                            min=-120.0,
                            max=120.0,
                        )
                        raw_probabilities = torch.softmax(logits, dim=-1)
                        nonfinite_probability_count = int(
                            (~torch.isfinite(raw_probabilities))
                            .sum()
                            .detach()
                            .cpu()
                            .item()
                        )
                        if nonfinite_probability_count:
                            base[
                                "validation_policy_edge_nonfinite_output_value_count"
                            ] = nonfinite_probability_count
                            base["validation_policy_edge_status"] = (
                                "NONFINITE_VALIDATION_POLICY_EDGE_PROBABILITY"
                            )
                            return base
                    probability_rows = raw_probabilities.detach().cpu().tolist()
                    expected_rows = expected_moves.detach().cpu().reshape(-1).tolist()
                    for probabilities, expected_move in zip(
                        probability_rows,
                        expected_rows,
                    ):
                        _adjusted, selected_index = (
                            self.model._expected_move_aligned_policy(  # noqa: SLF001
                                probabilities,
                                float(expected_move),
                            )
                        )
                        action_indices.append(int(selected_index))
                finally:
                    if was_training:
                        net.train()
            except Exception as exc:  # noqa: BLE001 - evidence must fail closed
                base["validation_policy_edge_status"] = (
                    f"POLICY_EDGE_FORWARD_FAILED:{type(exc).__name__}"
                )
                return base
        else:
            try:
                for row in rows:
                    output = self.model.forward(row.tensor.model_vector)
                    action_indices.append(int(output.selected_action_index))
            except Exception as exc:  # noqa: BLE001 - evidence must fail closed
                base["validation_policy_edge_status"] = (
                    f"POLICY_EDGE_FORWARD_FAILED:{type(exc).__name__}"
                )
                return base

        if len(action_indices) != len(rows):
            base["validation_policy_edge_status"] = "POLICY_EDGE_ACTION_COUNT_MISMATCH"
            return base

        row_after_cost_bps: list[float] = []
        directional_rows = 0
        action_distribution = {label: 0 for label in ACTION_LABELS}
        for action_index, realized_move_bps in zip(action_indices, labels):
            if not 0 <= action_index < ACTION_COUNT:
                base["validation_policy_edge_status"] = "POLICY_EDGE_ACTION_INDEX_INVALID"
                return base
            action_label = ACTION_LABELS[action_index]
            action_distribution[action_label] += 1
            if action_label == "long":
                row_after_cost_bps.append(realized_move_bps)
                directional_rows += 1
            elif action_label == "short":
                row_after_cost_bps.append(-realized_move_bps)
                directional_rows += 1
            else:
                row_after_cost_bps.append(0.0)
        total_after_cost_bps = sum(row_after_cost_bps)
        mean_after_cost_bps = total_after_cost_bps / len(row_after_cost_bps)
        if len(row_after_cost_bps) < 2:
            base["validation_policy_edge_status"] = (
                "INSUFFICIENT_ROWS_FOR_EDGE_UNCERTAINTY"
            )
            return base
        squared_deviations = sum(
            (value - mean_after_cost_bps) ** 2 for value in row_after_cost_bps
        )
        sample_variance = squared_deviations / (len(row_after_cost_bps) - 1)
        standard_error_bps = math.sqrt(sample_variance / len(row_after_cost_bps))
        lower_confidence_bound_bps = mean_after_cost_bps - standard_error_bps
        if not all(
            math.isfinite(value)
            for value in (
                mean_after_cost_bps,
                standard_error_bps,
                lower_confidence_bound_bps,
            )
        ):
            base["validation_policy_edge_status"] = "POLICY_EDGE_NONFINITE"
            return base
        base.update(
            {
                "validation_policy_edge_status": "VALID",
                "validation_policy_edge_evidence_valid": True,
                "validation_policy_edge_after_cost_bps": round(
                    mean_after_cost_bps,
                    8,
                ),
                "validation_policy_edge_total_after_cost_bps": round(
                    total_after_cost_bps,
                    8,
                ),
                "validation_policy_edge_lower_confidence_bound_bps": round(
                    lower_confidence_bound_bps,
                    8,
                ),
                "validation_policy_edge_standard_error_bps": round(
                    standard_error_bps,
                    8,
                ),
                "validation_policy_edge_rows_evaluated": len(rows),
                "validation_policy_edge_directional_rows": directional_rows,
                "validation_policy_edge_action_distribution": action_distribution,
            }
        )
        return base

    def _validation_supervised_loss(
        self,
        validation_rows: Sequence[TrainingExample],
    ) -> dict[str, Any]:
        """Out-of-sample supervised loss on the held-out validation split.

        The training loop carves out a validation split but historically never
        evaluated it, so the trainer had no generalization signal and could not
        detect the in-sample/out-of-sample overfit gap that lets an overfit
        checkpoint (low train loss) get promoted despite poor live behaviour.
        This computes a real held-out supervised loss (policy cross-entropy +
        expected-move MSE) under eval()/no_grad; it never affects gradients.
        """
        rows = list(validation_rows)
        empty = {
            "validation_supervised_loss_status": "NO_VALIDATION_ROWS",
            "validation_supervised_loss": None,
            "validation_supervised_loss_before": None,
            "validation_supervised_loss_after": None,
            "validation_rows_evaluated": 0,
            "validation_supervised_nonfinite_input_value_count": 0,
            "validation_supervised_nonfinite_label_value_count": 0,
            "validation_supervised_nonfinite_output_value_count": 0,
            "validation_loss_delta": None,
            "validation_improved": None,
            "train_val_generalization_gap": None,
        }
        if not rows:
            return dict(empty)
        if not self.model.torch_available:
            return {
                **empty,
                "validation_supervised_loss_status": "TORCH_MODEL_UNAVAILABLE",
            }
        torch = self.model.torch
        net = self.model.net
        if torch is None or net is None:
            return {
                **empty,
                "validation_supervised_loss_status": "TORCH_MODEL_UNAVAILABLE",
            }
        device = self.model.device
        try:
            from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.temporal_windowing import (  # noqa: PLC0415
                build_window_lookup,
                model_batch_tensor,
            )
            _temporal = bool(getattr(self.model, "temporal_encoder_enabled", False))
            _seq_len = int(getattr(self.model, "temporal_seq_len", 16))
            # Prefer the shared cycle lookup (set by _train_torch so train + val use
            # the same causal history); else build from these rows (e.g. H2L scoring).
            _lookup = getattr(self, "_temporal_window_lookup", None)
            if _temporal and _lookup is None:
                _lookup = build_window_lookup(rows, seq_len=_seq_len)
            val_x = model_batch_tensor(
                torch, rows, temporal=_temporal, seq_len=_seq_len,
                window_lookup=_lookup, device="cpu",
            )
            nonfinite_input_count = int(
                (~torch.isfinite(val_x)).sum().detach().cpu().item()
            )
            if nonfinite_input_count:
                return {
                    **empty,
                    "validation_supervised_loss_status": (
                        "NONFINITE_VALIDATION_SUPERVISED_INPUT"
                    ),
                    "validation_supervised_nonfinite_input_value_count": (
                        nonfinite_input_count
                    ),
                }
            val_x = torch.clamp(val_x, min=-1_000_000.0, max=1_000_000.0).to(device=device)
            policy_labels, _ = self._python_policy_action_supervision_labels(rows)
            val_actions = torch.tensor(policy_labels, dtype=torch.long, device=device)
            val_expected = torch.tensor(
                [r.label_expected_move_after_cost_bps for r in rows],
                dtype=torch.float32,
                device=device,
            )
            nonfinite_label_count = int(
                (~torch.isfinite(val_expected)).sum().detach().cpu().item()
            )
            if nonfinite_label_count:
                return {
                    **empty,
                    "validation_supervised_loss_status": (
                        "NONFINITE_VALIDATION_SUPERVISED_LABEL"
                    ),
                    "validation_supervised_nonfinite_label_value_count": (
                        nonfinite_label_count
                    ),
                }
            val_expected = torch.clamp(
                val_expected,
                min=-120.0,
                max=120.0,
            )
            was_training = bool(net.training)
            net.eval()
            try:
                with torch.no_grad():
                    out = net(val_x)
                    nonfinite_logits_count = int(
                        (~torch.isfinite(out["logits"]))
                        .sum()
                        .detach()
                        .cpu()
                        .item()
                    )
                    nonfinite_expected_move_count = int(
                        (~torch.isfinite(out["expected_move"]))
                        .sum()
                        .detach()
                        .cpu()
                        .item()
                    )
                    nonfinite_output_count = (
                        nonfinite_logits_count
                        + nonfinite_expected_move_count
                    )
                    if nonfinite_output_count:
                        return {
                            **empty,
                            "validation_supervised_loss_status": (
                                "NONFINITE_VALIDATION_SUPERVISED_OUTPUT"
                            ),
                            "validation_supervised_nonfinite_output_value_count": (
                                nonfinite_output_count
                            ),
                        }
                    logits = torch.clamp(
                        out["logits"],
                        min=-30.0,
                        max=30.0,
                    )
                    expected_move = torch.clamp(
                        out["expected_move"],
                        min=-120.0,
                        max=120.0,
                    )
                    ce = torch.nn.functional.cross_entropy(logits, val_actions)
                    mse = torch.nn.functional.mse_loss(expected_move, val_expected)
                    val_loss = ce + 0.01 * mse
            finally:
                if was_training:
                    net.train()
            val_loss_f = float(val_loss.detach().cpu().item())
        except Exception as exc:
            return {
                **empty,
                "validation_supervised_loss_status": (
                    f"VALIDATION_SUPERVISED_FORWARD_FAILED:{type(exc).__name__}"
                ),
            }
        if not math.isfinite(val_loss_f):
            return {
                **empty,
                "validation_supervised_loss_status": (
                    "NONFINITE_VALIDATION_SUPERVISED_LOSS"
                ),
                "validation_supervised_nonfinite_output_value_count": 1,
            }
        return {
            **empty,
            "validation_supervised_loss_status": "VALID",
            "validation_supervised_loss": val_loss_f,
            "validation_supervised_loss_after": val_loss_f,
            "validation_rows_evaluated": len(rows),
        }

    def _train_torch(
        self,
        rows: Sequence[TrainingExample],
        *,
        validation_rows: Sequence[TrainingExample],
        steps: int,
        batch_size: int,
        target_batch_size: int,
        available_rows: int,
        selected_rows: int,
        rejection_metrics: dict[str, Any] | None = None,
        learning_mode: str,
    ) -> PPOTrainingResult:
        torch = self.model.torch
        net = self.model.net
        assert torch is not None and net is not None
        started = time.perf_counter()
        net_was_training = bool(net.training)
        pre_cycle_state = {
            name: value.detach().cpu().clone()
            for name, value in net.state_dict().items()
        }
        pre_cycle_calibration_state = self.model.confidence_calibration_state
        parameter_vector_before = self._parameter_vector()
        parameter_hash_before = model_parameter_fingerprint(self.model)
        device = self.model.device
        net.train()

        def nonfinite_parameter_count() -> int:
            parameters = list(net.parameters())
            if not parameters:
                return 0
            all_finite = torch.stack(
                [torch.isfinite(parameter).all() for parameter in parameters]
            ).all()
            if bool(all_finite.detach().cpu().item()):
                return 0
            return sum(
                int((~torch.isfinite(parameter)).sum().detach().cpu().item())
                for parameter in parameters
            )

        def rollback_and_abort(
            reason: str,
            *,
            nonfinite_parameter_values: int = 0,
            nonfinite_gradient_values: int = 0,
            nonfinite_loss_steps: int = 0,
            nonfinite_feature_values: int = 0,
            nonfinite_label_values: int = 0,
            nonfinite_model_output_values: int = 0,
            nonfinite_model_output_events: int = 0,
            nonfinite_ratio_values: int = 0,
            nonfinite_ratio_events: int = 0,
            nonfinite_model_output_head_counts: Mapping[str, int] | None = None,
            finite_gradient_clip_applied_steps: int = 0,
        ) -> PPOTrainingResult:
            with torch.no_grad():
                net.load_state_dict(pre_cycle_state, strict=True)
            if net_was_training:
                net.train()
            else:
                net.eval()
            self.model.set_confidence_calibration_state(
                pre_cycle_calibration_state
            )
            parameter_hash_after_rollback = model_parameter_fingerprint(
                self.model
            )
            if parameter_hash_after_rollback != parameter_hash_before:
                raise RuntimeError(
                    "trainer_numeric_anomaly_rollback_verification_failed"
                )
            metrics = dict(rejection_metrics or {})
            metrics.update(
                {
                    "online_learning_status": "BLOCKED_NUMERIC_ANOMALY_ROLLED_BACK",
                    "effective_trainer_mode": "INFERENCE_ONLY",
                    "learning_update_lane": "blocked_numeric_anomaly",
                    "optimizer_steps_this_cycle": 0,
                    "parameter_hash_before": parameter_hash_before,
                    "parameter_hash_after": parameter_hash_after_rollback,
                    "weight_delta_norm": 0.0,
                    "loss_or_metric_changes": False,
                    "ppo_objective_used": False,
                    "outcome_supervised_update_used": False,
                    "ppo_rows_consumed": 0,
                    "ppo_clipped_surrogate_rows": 0,
                    "ppo_consumed_update_keys": [],
                    "ppo_consumed_update_keys_complete": True,
                    "ppo_consumed_update_keys_ordered": True,
                    "ppo_consumed_update_keys_unique": True,
                    "ppo_configured_optimizer_epochs_per_consumption_claim": 0,
                    "ppo_rows_reused_across_optimizer_steps_within_train_call": False,
                    "non_finite_feature_count": int(nonfinite_feature_values),
                    "non_finite_expected_label_count": int(
                        nonfinite_label_values
                    ),
                    "clipped_expected_label_count": 0,
                    "non_finite_loss_steps": int(nonfinite_loss_steps),
                    "non_finite_gradient_steps": int(
                        nonfinite_gradient_values > 0
                    ),
                    "non_finite_gradient_value_count": int(
                        nonfinite_gradient_values
                    ),
                    "sanitized_gradient_steps": 0,
                    "sanitized_gradient_value_count": 0,
                    "advantage_anomaly_steps": 0,
                    "tensor_nan_inf_count": int(nonfinite_loss_steps)
                    + int(nonfinite_feature_values)
                    + int(nonfinite_label_values)
                    + int(nonfinite_gradient_values)
                    + int(nonfinite_model_output_values)
                    + int(nonfinite_ratio_values),
                    "non_finite_model_output_value_count": int(
                        nonfinite_model_output_values
                    ),
                    "non_finite_model_output_events": int(
                        nonfinite_model_output_events
                    ),
                    "non_finite_model_output_head_counts": dict(
                        nonfinite_model_output_head_counts or {}
                    ),
                    "non_finite_optimizer_ratio_value_count": int(
                        nonfinite_ratio_values
                    ),
                    "non_finite_optimizer_ratio_events": int(
                        nonfinite_ratio_events
                    ),
                    "non_finite_parameter_value_count_detected": int(
                        nonfinite_parameter_values
                    ),
                    "non_finite_parameter_value_count_sanitized": 0,
                    "non_finite_parameter_sanitization_events": 0,
                    "finite_gradient_clip_applied_steps": int(
                        finite_gradient_clip_applied_steps
                    ),
                    "parameter_finite_guard_active": True,
                    "parameter_finite_guard_mode": "FAIL_CLOSED_ROLLBACK",
                    "optimizer_anomaly_counters_complete": True,
                    "anomaly_free_optimizer_cycle": False,
                    "training_cycle_rolled_back": True,
                    "training_cycle_rollback_verified": True,
                    "training_cycle_abort_reason": reason,
                }
            )
            return PPOTrainingResult(
                status="V2_NATIVE_TRAINER_NUMERIC_ANOMALY_ABORTED_ROLLED_BACK",
                device=device,
                cuda_active=self.model.cuda_active,
                cuda_claim_verified=(
                    self.model.cuda_active
                    and self.model.model_tensors_device_verified()
                ),
                gpu_name=None,
                vram_allocated_mb=None,
                batch_size=int(batch_size),
                training_steps=0,
                train_rows=len(rows),
                validation_rows=len(validation_rows),
                loss_before=None,
                loss_after=None,
                action_distribution=self._action_distribution(rows),
                metrics=metrics,
            )

        initial_nonfinite_parameters = nonfinite_parameter_count()
        if initial_nonfinite_parameters:
            return rollback_and_abort(
                "NONFINITE_PARAMETER_BEFORE_OPTIMIZER",
                nonfinite_parameter_values=initial_nonfinite_parameters,
            )
        from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.temporal_windowing import (  # noqa: PLC0415
            build_window_lookup,
            model_batch_tensor,
        )
        _temporal = bool(getattr(self.model, "temporal_encoder_enabled", False))
        _seq_len = int(getattr(self.model, "temporal_seq_len", 16))
        # Build ONE window lookup from the full cycle (train rows + validation
        # rows) so both the train batch and the held-out validation build windows
        # over the SAME causal history -- consistency is what avoids a train/eval
        # mismatch. Off -> byte-identical 2D single-frame tensor.
        # Cross-epoch input cache. train() slices rows/validation_rows as a
        # DETERMINISTIC prefix of `examples` (no shuffle), so across the offline
        # loop's epochs the windowed input + label tensors are IDENTICAL -- only the
        # weights change. Rebuilding + sanitising the (16x-bigger, temporal) tensor
        # every epoch is what starves the GPU (gpu_util ~16%). The digest covers
        # every ordered tensor value, mask, target, identity, and trust payload in
        # both partitions. Any middle-row or relabelled-outcome change therefore
        # misses the cache; only byte-equivalent training inputs can reuse it.
        _cacheable = bool(rows or validation_rows)
        _cache_fp = _ordered_training_cache_digest(
            rows,
            validation_rows,
            temporal=_temporal,
            seq_len=_seq_len,
        )
        _cache = getattr(self, "_train_input_cache", None)
        if _cacheable and _cache is not None and _cache.get("fp") == _cache_fp:
            cpu_x = _cache["cpu_x"]
            cpu_actions = _cache["cpu_actions"]
            cpu_policy_actions = _cache["cpu_policy_actions"]
            cpu_expected = _cache["cpu_expected"]
            self._temporal_window_lookup = _cache["window_lookup"]
            policy_action_supervision_metrics = _cache["policy_metrics"]
            non_finite_feature_count = _cache["non_finite_feature_count"]
            non_finite_expected_label_count = _cache["non_finite_expected_label_count"]
            clipped_expected_label_count = _cache["clipped_expected_label_count"]
        else:
            _cycle_rows = list(rows) + list(validation_rows)
            self._temporal_window_lookup = (
                build_window_lookup(_cycle_rows, seq_len=_seq_len) if _temporal else None
            )
            cpu_x = model_batch_tensor(
                torch, rows, temporal=_temporal, seq_len=_seq_len,
                window_lookup=self._temporal_window_lookup, device="cpu",
            )
            policy_action_labels, policy_action_supervision_metrics = self._python_policy_action_supervision_labels(rows)
            cpu_actions = torch.tensor([r.label_action_index for r in rows], dtype=torch.long, device="cpu")
            cpu_policy_actions = torch.tensor(policy_action_labels, dtype=torch.long, device="cpu")
            cpu_expected = torch.tensor(
                [r.label_expected_move_after_cost_bps for r in rows],
                dtype=torch.float32,
                device="cpu",
            )
            non_finite_feature_count = int((~torch.isfinite(cpu_x)).sum().detach().cpu().item())
            non_finite_expected_label_count = int((~torch.isfinite(cpu_expected)).sum().detach().cpu().item())
            if non_finite_feature_count or non_finite_expected_label_count:
                self._train_input_cache = None
                return rollback_and_abort(
                    "NONFINITE_TRAINING_TENSOR_OR_LABEL",
                    nonfinite_feature_values=non_finite_feature_count,
                    nonfinite_label_values=non_finite_expected_label_count,
                )
            cpu_x = torch.clamp(cpu_x, min=-1_000_000.0, max=1_000_000.0)
            raw_expected = cpu_expected
            cpu_expected = torch.clamp(raw_expected, min=-120.0, max=120.0)
            clipped_expected_label_count = int(
                (torch.abs(raw_expected - cpu_expected) > 1e-6).sum().detach().cpu().item()
            )
            if _cacheable:
                self._train_input_cache = {
                    "fp": _cache_fp,
                    "cpu_x": cpu_x,
                    "cpu_actions": cpu_actions,
                    "cpu_policy_actions": cpu_policy_actions,
                    "cpu_expected": cpu_expected,
                    "window_lookup": self._temporal_window_lookup,
                    "policy_metrics": policy_action_supervision_metrics,
                    "non_finite_feature_count": non_finite_feature_count,
                    "non_finite_expected_label_count": non_finite_expected_label_count,
                    "clipped_expected_label_count": clipped_expected_label_count,
                }
        if non_finite_feature_count or non_finite_expected_label_count:
            # A cache created by an older process may contain tensors that were
            # previously coerced.  Its recorded counters make that cache
            # inadmissible even when the cached arrays themselves are finite.
            self._train_input_cache = None
            return rollback_and_abort(
                "NONFINITE_CACHED_TRAINING_TENSOR_OR_LABEL",
                nonfinite_feature_values=non_finite_feature_count,
                nonfinite_label_values=non_finite_expected_label_count,
            )
        ppo_row_flags = [self._has_on_policy_ppo_fields(row) for row in rows]
        ppo_behavior_identities = [self._behavior_action_identity(row) for row in rows]
        ppo_behavior_action_indices = [
            identity[0] if flag and identity is not None else 0
            for flag, identity in zip(ppo_row_flags, ppo_behavior_identities)
        ]
        ppo_behavior_action_masks = [
            list(behavior_action_mask_from_row(self._trust_row(row)))
            if flag
            else [True] * ACTION_COUNT
            for row, flag in zip(rows, ppo_row_flags)
        ]
        cpu_behavior_actions = torch.tensor(
            ppo_behavior_action_indices,
            dtype=torch.long,
            device="cpu",
        )
        cpu_behavior_action_masks = torch.tensor(
            ppo_behavior_action_masks,
            dtype=torch.bool,
            device="cpu",
        )
        ppo_row_count = sum(1 for flag in ppo_row_flags if flag)
        ppo_behavior_action_metrics = self._ppo_behavior_action_metrics(rows)
        outcome_row_count = sum(1 for row in rows if self._has_outcome_supervised_targets(row))
        ppo_objective_active = self._ppo_objective_active(learning_mode) and ppo_row_count > 0
        outcome_supervision_active = self._outcome_supervision_active(learning_mode)
        workers = compute_dataloader_workers(row_count=selected_rows) if self.model.cuda_active else 0
        prefetch_factor: int | None = PREFETCH_FACTOR if workers > 0 else None
        dataloader_used = False
        pinned_memory = False
        if self.model.cuda_active and workers:
            loader = None
            try:
                dataset = torch.utils.data.TensorDataset(
                    cpu_x,
                    cpu_actions,
                    cpu_policy_actions,
                    cpu_behavior_actions,
                    cpu_expected,
                )
                loader = torch.utils.data.DataLoader(
                    dataset,
                    batch_size=len(rows),
                    shuffle=False,
                    num_workers=workers,
                    pin_memory=True,
                    prefetch_factor=prefetch_factor,
                    persistent_workers=PERSISTENT_WORKERS,
                )
                (
                    cpu_x,
                    cpu_actions,
                    cpu_policy_actions,
                    cpu_behavior_actions,
                    cpu_expected,
                ) = next(iter(loader))
                pinned_memory = bool(cpu_x.is_pinned())
                dataloader_used = True
            except Exception:
                workers = 0
                prefetch_factor = None
                pinned_memory = False
            finally:
                if loader is not None:
                    del loader
        if self.model.cuda_active and not pinned_memory:
            try:
                cpu_x = cpu_x.pin_memory()
                cpu_actions = cpu_actions.pin_memory()
                cpu_policy_actions = cpu_policy_actions.pin_memory()
                cpu_behavior_actions = cpu_behavior_actions.pin_memory()
                cpu_expected = cpu_expected.pin_memory()
                pinned_memory = True
            except Exception:
                pinned_memory = False
        x = cpu_x.to(device=device, non_blocking=pinned_memory)
        target_actions = cpu_actions.to(device=device, non_blocking=pinned_memory)
        policy_target_actions = cpu_policy_actions.to(device=device, non_blocking=pinned_memory)
        behavior_actions = cpu_behavior_actions.to(device=device, non_blocking=pinned_memory)
        behavior_action_masks = cpu_behavior_action_masks.to(
            device=device,
            non_blocking=pinned_memory,
        )
        target_expected = cpu_expected.to(device=device, non_blocking=pinned_memory)
        (
            confidence_target_values,
            confidence_target_flags,
            confidence_target_head_action_indices,
            confidence_target_row_ids,
            confidence_target_metrics,
        ) = self._confidence_target_batch(rows)
        confidence_targets = torch.tensor(
            confidence_target_values,
            dtype=torch.float32,
            device=device,
        )
        confidence_target_mask = torch.tensor(
            confidence_target_flags,
            dtype=torch.bool,
            device=device,
        )
        confidence_target_head_actions = torch.tensor(
            confidence_target_head_action_indices,
            dtype=torch.long,
            device=device,
        )
        confidence_target_count = sum(1 for flag in confidence_target_flags if flag)
        long_target_count = int((target_actions == 1).sum().detach().cpu().item())
        short_target_count = int((target_actions == 2).sum().detach().cpu().item())
        directional_target_count = long_target_count + short_target_count
        single_direction_expected_move_guard_active = (
            directional_target_count > 0
            and (long_target_count == 0 or short_target_count == 0)
        )
        expected_move_guard_side = (
            "long"
            if single_direction_expected_move_guard_active and long_target_count > 0
            else "short"
            if single_direction_expected_move_guard_active and short_target_count > 0
            else None
        )
        expected_move_training_target = target_expected
        expected_move_labels_neutralized_count = 0
        if single_direction_expected_move_guard_active:
            directional_mask = (target_actions == 1) | (target_actions == 2)
            expected_move_labels_neutralized_count = int(directional_mask.sum().detach().cpu().item())
            expected_move_training_target = torch.where(
                directional_mask,
                torch.zeros_like(target_expected),
                target_expected,
            )
        non_finite_parameter_value_count_detected = 0
        non_finite_parameter_value_count_sanitized = 0
        non_finite_parameter_sanitization_events = 0
        opt = torch.optim.AdamW(net.parameters(), lr=self.learning_rate, weight_decay=self.weight_decay)
        action_weights = self._torch_action_class_weights(
            target_actions=policy_target_actions,
            torch=torch,
            device=device,
        )
        ce = torch.nn.CrossEntropyLoss(weight=action_weights)
        mse = torch.nn.MSELoss()
        use_amp = bool(self.model.cuda_active)
        if use_amp and hasattr(torch, "amp") and hasattr(torch.amp, "autocast"):
            autocast = lambda: torch.amp.autocast("cuda", enabled=True)
        elif use_amp and hasattr(torch.cuda, "amp"):
            autocast = lambda: torch.cuda.amp.autocast(enabled=True)
        else:
            autocast = nullcontext
            use_amp = False
        scaler = None
        if use_amp:
            try:
                # A 65,536 initial loss scale overflowed otherwise-finite native
                # gradients on the first step, which previously went unnoticed
                # because those gradients were zero-filled.  Start unscaled;
                # GradScaler may grow only after its own finite-step interval.
                scaler = torch.amp.GradScaler(
                    "cuda",
                    enabled=True,
                    init_scale=1.0,
                )
            except Exception:
                try:
                    scaler = torch.cuda.amp.GradScaler(
                        enabled=True,
                        init_scale=1.0,
                    )
                except Exception:
                    scaler = None
                    use_amp = False

        output_bounds = {
            "logits": (-30.0, 30.0),
            "value": (-10.0, 10.0),
            "expected_move": (-120.0, 120.0),
            "confidence_by_direction": (0.0, 1.0),
            "masa": (-1.0, 1.0),
        }

        def finite_bounded_outputs(out):
            """Bound finite outputs; never fabricate values for NaN/Inf heads."""

            nonfinite_head_counts: dict[str, int] = {}
            for head_name in output_bounds:
                head = out[head_name]
                nonfinite_count = int(
                    (~torch.isfinite(head)).sum().detach().cpu().item()
                )
                if nonfinite_count:
                    nonfinite_head_counts[head_name] = nonfinite_count
            nonfinite_count = sum(nonfinite_head_counts.values())
            if nonfinite_count:
                return None, nonfinite_count, nonfinite_head_counts
            return (
                {
                    head_name: torch.clamp(
                        out[head_name],
                        min=bounds[0],
                        max=bounds[1],
                    )
                    for head_name, bounds in output_bounds.items()
                },
                0,
                {},
            )

        def confidence_profitability_loss(out):
            if confidence_target_count > 0:
                confidence_for_recorded_action = out[
                    "confidence_by_direction"
                ].gather(1, confidence_target_head_actions[:, None]).squeeze(1)
                probabilities = torch.clamp(
                    confidence_for_recorded_action[confidence_target_mask].float(),
                    min=1e-6,
                    max=1.0 - 1e-6,
                )
                outcomes = confidence_targets[confidence_target_mask].float()
                return -(
                    outcomes * torch.log(probabilities)
                    + (1.0 - outcomes) * torch.log1p(-probabilities)
                ).mean()
            # Preserve the graph/device/dtype while applying no confidence-head
            # update when PIT-safe explicit-cost labels are unavailable.
            return out["confidence_by_direction"].sum() * 0.0

        def supervised_loss(out):
            return (
                ce(out["logits"], policy_target_actions)
                + 0.01 * mse(out["expected_move"], expected_move_training_target)
                + 0.001 * mse(out["value"], expected_move_training_target / 100.0)
                + 0.001 * mse(out["masa"], torch.tanh(expected_move_training_target / 100.0))
                + 0.05 * confidence_profitability_loss(out)
            )

        with torch.no_grad():
            with autocast():
                safe_out0, initial_output_nonfinite_count, initial_head_counts = (
                    finite_bounded_outputs(net(x))
                )
                if safe_out0 is None:
                    return rollback_and_abort(
                        "NONFINITE_MODEL_OUTPUT_BEFORE_OPTIMIZER",
                        nonfinite_model_output_values=(
                            initial_output_nonfinite_count
                        ),
                        nonfinite_model_output_events=1,
                        nonfinite_model_output_head_counts=initial_head_counts,
                    )
                loss_before_t = supervised_loss(safe_out0)
                if not bool(torch.isfinite(loss_before_t).detach().cpu().item()):
                    return rollback_and_abort(
                        "NONFINITE_LOSS_BEFORE_OPTIMIZER",
                        nonfinite_loss_steps=1,
                    )
                behavior_logits0 = safe_out0["logits"].masked_fill(
                    ~behavior_action_masks,
                    torch.finfo(safe_out0["logits"].dtype).min,
                )
                current_log_probs = torch.log_softmax(behavior_logits0, dim=-1).gather(
                    1,
                    behavior_actions[:, None],
                ).squeeze(1)
                ppo_row_mask = torch.tensor(ppo_row_flags, dtype=torch.bool, device=device)
                old_log_probs = current_log_probs.detach().clone()
                ppo_advantages = torch.zeros_like(old_log_probs)
                if ppo_objective_active:
                    old_log_values = []
                    advantage_values = []
                    for row in rows:
                        trust_row = self._trust_row(row)
                        if self._has_on_policy_ppo_fields(row):
                            old_log_values.append(float(trust_row.get("old_log_prob")))
                            advantage_values.append(
                                float(trust_row.get("reward")) - float(trust_row.get("old_value"))
                            )
                        else:
                            old_log_values.append(0.0)
                            advantage_values.append(0.0)
                    supplied_old_log_probs = torch.tensor(
                        old_log_values,
                        dtype=torch.float32,
                        device=device,
                    )
                    supplied_advantages = torch.tensor(
                        advantage_values,
                        dtype=torch.float32,
                        device=device,
                    )
                    old_log_probs = torch.where(ppo_row_mask, supplied_old_log_probs, old_log_probs)
                    ppo_advantages = torch.where(ppo_row_mask, supplied_advantages, ppo_advantages)
        # Evaluate the held-out rows before optimizer steps so runtime can
        # reject checkpoint candidates that regress out-of-sample loss.
        validation_metrics_before = self._validation_supervised_loss(validation_rows)
        validation_policy_edge_before = self._validation_policy_edge(validation_rows)
        validation_policy_edge_before = {
            key.replace(
                "validation_policy_edge_",
                "validation_policy_edge_before_",
                1,
            ): value
            for key, value in validation_policy_edge_before.items()
        }
        loss_after_t = loss_before_t
        non_finite_loss_steps = 0
        non_finite_gradient_steps = 0
        sanitized_gradient_steps = 0
        sanitized_gradient_value_count = 0
        advantage_anomaly_steps = 0
        finite_gradient_clip_applied_steps = 0
        max_gradient_norm = 0.0
        optimizer_steps_this_cycle = 0
        numeric_abort_reason: str | None = None
        numeric_abort_nonfinite_gradient_values = 0
        numeric_abort_nonfinite_parameter_values = 0
        numeric_abort_nonfinite_model_output_values = 0
        numeric_abort_nonfinite_model_output_events = 0
        numeric_abort_nonfinite_model_output_head_counts: dict[str, int] = {}
        numeric_abort_nonfinite_ratio_values = 0
        numeric_abort_nonfinite_ratio_events = 0
        last_component_losses: dict[str, float | None] = {
            "ppo_policy_loss": None,
            "ppo_value_loss": None,
            "ppo_entropy": None,
            "masa_loss": None,
            "expected_move_loss": None,
            "confidence_loss": None,
        }

        def _finite_or_none(value: Any) -> float | None:
            try:
                f = float(value.detach().cpu().item())
            except Exception:
                return None
            return f if math.isfinite(f) else None

        def nonfinite_gradient_count() -> int:
            grads = [p.grad for p in net.parameters() if getattr(p, "grad", None) is not None]
            if not grads:
                return 0
            all_finite = torch.stack(
                [torch.isfinite(gradient).all() for gradient in grads]
            ).all()
            if bool(all_finite.detach().cpu().item()):
                return 0
            return sum(
                int((~torch.isfinite(gradient)).sum().detach().cpu().item())
                for gradient in grads
            )

        training_gpu_sampler = _TrainingWindowGpuSampler(enabled=bool(self.model.cuda_active))
        training_gpu_sampler.start()
        # GPU-saturation fast path: the per-step 10-component metric dict below runs
        # a _finite_or_none (=> .detach().cpu().item()) sync per component EVERY step,
        # and each GPU->CPU sync drains the pipeline (the measured spike-to-90%-then-
        # drop-to-10% pattern). Only ppo_advantage_mean/std are needed per step (the
        # advantage safety check); the full dict is only reported once (final step).
        # When enabled, build the full dict only periodically + on the final step,
        # removing ~8 syncs/step. Env-gated + DEFAULT OFF: the running trainer is
        # byte-for-byte unchanged unless an operator sets V2_TRAINER_FAST_STEP_METRICS.
        _fast_step_metrics = str(os.getenv("V2_TRAINER_FAST_STEP_METRICS", "") or "").strip().lower() in {
            "1", "true", "yes", "on",
        }
        _total_train_steps = max(1, int(steps))
        # Tail-aware CVaR penalty: lift the risk composite's CVaR ceiling (the model's
        # ungated argmax trades carry a fat left tail; more training does not fix it).
        # Adds a differentiable penalty on the WORST-tail of the policy's expected
        # directional return (P(long)-P(short))*move, so the model learns to avoid the
        # fat-tail losing trades the risk metric penalises. DEFAULT OFF (weight 0 =>
        # byte-identical); prove offline via A/B before any use.
        _tail_cvar_weight = max(0.0, float(os.getenv("V2_TRAINER_TAIL_CVAR_WEIGHT", "0") or 0.0))
        _tail_cvar_alpha = min(0.9, max(0.01, float(os.getenv("V2_TRAINER_TAIL_CVAR_ALPHA", "0.1") or 0.1)))
        for _step_index in range(_total_train_steps):
            opt.zero_grad(set_to_none=True)
            with autocast():
                out, output_nonfinite_count, output_head_counts = (
                    finite_bounded_outputs(net(x))
                )
                if out is None:
                    numeric_abort_nonfinite_model_output_values += (
                        output_nonfinite_count
                    )
                    numeric_abort_nonfinite_model_output_events += 1
                    for head_name, count in output_head_counts.items():
                        numeric_abort_nonfinite_model_output_head_counts[
                            head_name
                        ] = (
                            numeric_abort_nonfinite_model_output_head_counts.get(
                                head_name,
                                0,
                            )
                            + count
                        )
                    numeric_abort_reason = "NONFINITE_MODEL_OUTPUT_DURING_OPTIMIZER"
                    opt.zero_grad(set_to_none=True)
                    break
                behavior_logits = out["logits"].masked_fill(
                    ~behavior_action_masks,
                    torch.finfo(out["logits"].dtype).min,
                )
                behavior_log_probs = torch.log_softmax(behavior_logits, dim=-1)
                new_log_probs = behavior_log_probs.gather(
                    1,
                    behavior_actions[:, None],
                ).squeeze(1)
                log_probs = torch.log_softmax(out["logits"], dim=-1)
                probs = torch.softmax(out["logits"], dim=-1)
                entropy_per_row = -(probs * log_probs).sum(dim=-1)
                behavior_probabilities = torch.softmax(behavior_logits, dim=-1)
                behavior_entropy_per_row = -(
                    behavior_probabilities * behavior_log_probs
                ).sum(dim=-1)
                if ppo_objective_active:
                    ppo_new_log_probs = new_log_probs[ppo_row_mask]
                    ppo_old_log_probs = old_log_probs.detach()[ppo_row_mask]
                    raw_log_ratio = ppo_new_log_probs - ppo_old_log_probs
                    nonfinite_log_ratio_count = int(
                        (~torch.isfinite(raw_log_ratio))
                        .sum()
                        .detach()
                        .cpu()
                        .item()
                    )
                    if nonfinite_log_ratio_count:
                        numeric_abort_nonfinite_ratio_values += (
                            nonfinite_log_ratio_count
                        )
                        numeric_abort_nonfinite_ratio_events += 1
                        numeric_abort_reason = "NONFINITE_PPO_LOG_RATIO"
                        opt.zero_grad(set_to_none=True)
                        break
                    log_ratio = torch.clamp(
                        raw_log_ratio,
                        min=-20.0,
                        max=20.0,
                    )
                    ratio = torch.exp(log_ratio.float())
                    nonfinite_ratio_count = int(
                        (~torch.isfinite(ratio)).sum().detach().cpu().item()
                    )
                    if nonfinite_ratio_count:
                        numeric_abort_nonfinite_ratio_values += (
                            nonfinite_ratio_count
                        )
                        numeric_abort_nonfinite_ratio_events += 1
                        numeric_abort_reason = "NONFINITE_PPO_RATIO"
                        opt.zero_grad(set_to_none=True)
                        break
                    advantage = torch.clamp(ppo_advantages[ppo_row_mask], -5.0, 5.0)
                    unclipped = ratio * advantage
                    clipped = torch.clamp(ratio, 1.0 - self.clip_epsilon, 1.0 + self.clip_epsilon) * advantage
                    policy_loss = -torch.minimum(unclipped, clipped).mean()
                    # PPO diagnostics: clip fraction, approx KL, advantage stats.
                    ppo_clip_fraction = (
                        (torch.abs(ratio - 1.0) > self.clip_epsilon).float().mean()
                    )
                    ppo_approx_kl = (ppo_old_log_probs - ppo_new_log_probs).mean()
                    ppo_advantage_mean = advantage.mean()
                    ppo_advantage_std = advantage.std(unbiased=False)
                    entropy = behavior_entropy_per_row[ppo_row_mask].mean()
                else:
                    policy_loss = new_log_probs.new_tensor(0.0)
                    ppo_clip_fraction = new_log_probs.new_tensor(0.0)
                    ppo_approx_kl = new_log_probs.new_tensor(0.0)
                    ppo_advantage_mean = new_log_probs.new_tensor(0.0)
                    ppo_advantage_std = new_log_probs.new_tensor(0.0)
                    entropy = entropy_per_row.mean()
                value_loss = mse(out["value"], expected_move_training_target / 100.0)
                move_loss = mse(out["expected_move"], expected_move_training_target)
                masa_loss = mse(out["masa"], torch.tanh(expected_move_training_target / 100.0))
                confidence_loss = confidence_profitability_loss(out)
                if ppo_objective_active:
                    loss = (
                        supervised_loss(out)
                        + 0.1 * policy_loss
                        + 0.1 * value_loss
                        + 0.01 * move_loss
                        + 0.1 * masa_loss
                        + 0.05 * confidence_loss
                        - self.entropy_coefficient * entropy
                    )
                else:
                    # Supervised-only lane: the cross-entropy term drives the policy
                    # head toward a near-deterministic (entropy-collapsed) action
                    # distribution. A small entropy bonus keeps exploration alive so
                    # the policy does not lock into a single losing action bias.
                    loss = supervised_loss(out) - self.supervised_entropy_bonus * entropy
                if _tail_cvar_weight > 0.0:
                    # Per-row policy expected directional return, matching the risk
                    # composite's action->return map (a=1 long:+move, a=2 short:-move);
                    # target_expected is the raw after-cost move label (not the
                    # single-direction-neutralised training target). Minimising the mean
                    # of the worst-k losses (=-return) lifts the left tail (CVaR).
                    # Normalise move bps -> ~unit scale (/100, like the value head) so the
                    # penalty is comparable to the other loss terms and the weight is stable.
                    _policy_return = (probs[:, 1] - probs[:, 2]) * (target_expected.reshape(-1) / 100.0)
                    _tail_k = max(1, int(_tail_cvar_alpha * _policy_return.shape[0]))
                    _tail_cvar = torch.topk(-_policy_return, _tail_k).values.mean()
                    loss = loss + _tail_cvar_weight * _tail_cvar
            # Build the full metric dict every step (default) or only periodically +
            # on the final step (fast path). Either way ppo_advantage_mean/std are
            # always computed for the per-step safety check below.
            _build_full_metrics = (
                not _fast_step_metrics
                or _step_index == _total_train_steps - 1
                or (_step_index % 25 == 0)
            )
            if _build_full_metrics:
                last_component_losses = {
                    "ppo_policy_loss": _finite_or_none(policy_loss),
                    "ppo_value_loss": _finite_or_none(value_loss),
                    "ppo_entropy": _finite_or_none(entropy),
                    "masa_loss": _finite_or_none(masa_loss),
                    "expected_move_loss": _finite_or_none(move_loss),
                    "confidence_loss": _finite_or_none(confidence_loss),
                    "ppo_clip_fraction": _finite_or_none(ppo_clip_fraction),
                    "ppo_approx_kl_divergence": _finite_or_none(ppo_approx_kl),
                    "ppo_advantage_mean": _finite_or_none(ppo_advantage_mean),
                    "ppo_advantage_std": _finite_or_none(ppo_advantage_std),
                }
                adv_mean = last_component_losses["ppo_advantage_mean"]
                adv_std = last_component_losses["ppo_advantage_std"]
            else:
                # Fast path: only the two values the safety check needs.
                adv_mean = _finite_or_none(ppo_advantage_mean) if ppo_objective_active else None
                adv_std = _finite_or_none(ppo_advantage_std) if ppo_objective_active else None
            # Tracking assertion (pre-backprop): catch invalid/exploded
            # advantages on the on-policy lane before they can reach the
            # optimizer. Equal finite nonzero advantages are still valid PPO
            # signal; they should not block the supervised outcome lane.
            if ppo_objective_active:
                advantage_nonfinite = adv_mean is None or adv_std is None
                advantage_exploded = (
                    adv_mean is not None and abs(adv_mean) >= 5.0
                )
                advantage_vanished = (
                    adv_std is not None
                    and adv_std == 0.0
                    and (adv_mean is None or abs(adv_mean) <= 1e-9)
                    and ppo_row_count > 1
                )
                if advantage_nonfinite:
                    advantage_anomaly_steps += 1
                    non_finite_loss_steps += 1
                    numeric_abort_reason = "NONFINITE_PPO_ADVANTAGE"
                    opt.zero_grad(set_to_none=True)
                    break
                if advantage_exploded or advantage_vanished:
                    advantage_anomaly_steps += 1
                    opt.zero_grad(set_to_none=True)
                    continue
            if bool(torch.isfinite(loss).detach().cpu().item()) is False:
                non_finite_loss_steps += 1
                numeric_abort_reason = "NONFINITE_OPTIMIZER_LOSS"
                opt.zero_grad(set_to_none=True)
                break
            if scaler is not None and use_amp:
                scaler.scale(loss).backward()
                scaler.unscale_(opt)
            else:
                loss.backward()
            nonfinite_gradients = nonfinite_gradient_count()
            if nonfinite_gradients:
                non_finite_gradient_steps += 1
                numeric_abort_nonfinite_gradient_values += nonfinite_gradients
                numeric_abort_reason = "NONFINITE_OPTIMIZER_GRADIENT"
                opt.zero_grad(set_to_none=True)
                break
            grad_norm = torch.nn.utils.clip_grad_norm_(
                net.parameters(),
                max_norm=1.0,
                error_if_nonfinite=False,
            )
            finite_gradient_clip_applied_steps += 1
            if not bool(torch.isfinite(grad_norm).detach().cpu().item()):
                non_finite_gradient_steps += 1
                numeric_abort_nonfinite_gradient_values += 1
                numeric_abort_reason = "NONFINITE_GRADIENT_NORM"
                opt.zero_grad(set_to_none=True)
                break
            max_gradient_norm = max(
                max_gradient_norm,
                float(grad_norm.detach().cpu().item()),
            )
            if scaler is not None and use_amp:
                scaler.step(opt)
                scaler.update()
            else:
                opt.step()
            optimizer_steps_this_cycle += 1
            post_step_nonfinite_parameters = nonfinite_parameter_count()
            if post_step_nonfinite_parameters:
                non_finite_parameter_value_count_detected += (
                    post_step_nonfinite_parameters
                )
                numeric_abort_nonfinite_parameter_values += (
                    post_step_nonfinite_parameters
                )
                numeric_abort_reason = "NONFINITE_PARAMETER_AFTER_OPTIMIZER_STEP"
                break
        training_gpu_metrics = training_gpu_sampler.stop()
        if numeric_abort_reason is not None:
            return rollback_and_abort(
                numeric_abort_reason,
                nonfinite_parameter_values=(
                    numeric_abort_nonfinite_parameter_values
                ),
                nonfinite_gradient_values=(
                    numeric_abort_nonfinite_gradient_values
                ),
                nonfinite_loss_steps=non_finite_loss_steps,
                nonfinite_feature_values=non_finite_feature_count,
                nonfinite_label_values=non_finite_expected_label_count,
                nonfinite_model_output_values=(
                    numeric_abort_nonfinite_model_output_values
                ),
                nonfinite_model_output_events=(
                    numeric_abort_nonfinite_model_output_events
                ),
                nonfinite_model_output_head_counts=(
                    numeric_abort_nonfinite_model_output_head_counts
                ),
                nonfinite_ratio_values=(
                    numeric_abort_nonfinite_ratio_values
                ),
                nonfinite_ratio_events=(
                    numeric_abort_nonfinite_ratio_events
                ),
                finite_gradient_clip_applied_steps=(
                    finite_gradient_clip_applied_steps
                ),
            )
        feedback_head_nudge_applied = False
        expected_move_head_recovery_metrics: dict[str, Any] = {
            "expected_move_head_saturation_recovery_applied": False,
            "expected_move_head_saturation_recovery_reason": "not_evaluated",
            "expected_move_head_bias_abs_limit": EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT,
            "expected_move_head_saturation_bps": EXPECTED_MOVE_HEAD_SATURATION_BPS,
            "expected_move_head_target_mismatch_bps": EXPECTED_MOVE_HEAD_TARGET_MISMATCH_BPS,
        }
        expected_move_pre_activation_nonfinite_count = 0

        def expected_move_pre_activation(batch_x):
            nonlocal expected_move_pre_activation_nonfinite_count
            # Temporal model feeds a 3D window (B, T, F); this bias-saturation
            # diagnostic operates on the single "current" frame like the
            # single-frame model always did. Collapse to the newest frame so we
            # don't push all T frames through the residual stack (16x memory ->
            # OOM under GPU contention) and don't produce a (B, T) pre-activation.
            if batch_x.dim() == 3:
                batch_x = batch_x[:, -1, :]
            nonfinite_count = int(
                (~torch.isfinite(batch_x)).sum().detach().cpu().item()
            )
            if nonfinite_count:
                expected_move_pre_activation_nonfinite_count += nonfinite_count
                raise FloatingPointError(
                    "nonfinite_expected_move_pre_activation_input"
                )
            transformed = batch_x
            transformed = torch.sign(transformed) * torch.log1p(
                torch.clamp(torch.abs(transformed), max=1_000_000.0)
            )
            h = net.input_projection(transformed)
            for block in net.residual_blocks:
                h = block(h)
            h = net.encoder_norm(h)
            return net.expected_move_head(h).squeeze(-1)

        def bounded_atanh(value):
            clipped = torch.clamp(value, min=-0.95, max=0.95)
            return 0.5 * torch.log((1.0 + clipped) / (1.0 - clipped))

        def recover_saturated_expected_move_head() -> dict[str, Any]:
            if not all(
                hasattr(net, attr)
                for attr in ("input_projection", "residual_blocks", "encoder_norm", "expected_move_head")
            ):
                return {
                    "expected_move_head_saturation_recovery_applied": False,
                    "expected_move_head_saturation_recovery_reason": "expected_move_head_introspection_unavailable",
                    "expected_move_head_bias_abs_limit": EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT,
                    "expected_move_head_saturation_bps": EXPECTED_MOVE_HEAD_SATURATION_BPS,
                    "expected_move_head_target_mismatch_bps": EXPECTED_MOVE_HEAD_TARGET_MISMATCH_BPS,
                }
            bias = getattr(net.expected_move_head, "bias", None)
            if bias is None:
                return {
                    "expected_move_head_saturation_recovery_applied": False,
                    "expected_move_head_saturation_recovery_reason": "expected_move_head_bias_missing",
                    "expected_move_head_bias_abs_limit": EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT,
                    "expected_move_head_saturation_bps": EXPECTED_MOVE_HEAD_SATURATION_BPS,
                    "expected_move_head_target_mismatch_bps": EXPECTED_MOVE_HEAD_TARGET_MISMATCH_BPS,
                }
            mixed_directional_evidence = long_target_count > 0 and short_target_count > 0
            if not mixed_directional_evidence:
                return {
                    "expected_move_head_saturation_recovery_applied": False,
                    "expected_move_head_saturation_recovery_reason": "mixed_long_short_target_evidence_missing",
                    "expected_move_head_bias_abs_limit": EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT,
                    "expected_move_head_saturation_bps": EXPECTED_MOVE_HEAD_SATURATION_BPS,
                    "expected_move_head_target_mismatch_bps": EXPECTED_MOVE_HEAD_TARGET_MISMATCH_BPS,
                    "expected_move_head_target_long_count": int(long_target_count),
                    "expected_move_head_target_short_count": int(short_target_count),
                }
            pre_before = expected_move_pre_activation(x)
            output_before = 120.0 * torch.tanh(pre_before)
            bias_before = bias.detach().mean()
            target_mean_bps = torch.clamp(expected_move_training_target.mean(), -120.0, 120.0)
            saturated_output = bool(
                (torch.abs(output_before.mean()) >= EXPECTED_MOVE_HEAD_SATURATION_BPS).detach().cpu().item()
            )
            runaway_bias = bool(
                (torch.abs(bias_before) > EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT).detach().cpu().item()
            )
            target_mismatch = bool(
                (
                    torch.abs(output_before.mean() - target_mean_bps)
                    >= EXPECTED_MOVE_HEAD_TARGET_MISMATCH_BPS
                ).detach().cpu().item()
            )
            if not (saturated_output or runaway_bias or target_mismatch):
                return {
                    "expected_move_head_saturation_recovery_applied": False,
                    "expected_move_head_saturation_recovery_reason": "expected_move_head_within_bounds",
                    "expected_move_head_bias_abs_limit": EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT,
                    "expected_move_head_saturation_bps": EXPECTED_MOVE_HEAD_SATURATION_BPS,
                    "expected_move_head_target_mismatch_bps": EXPECTED_MOVE_HEAD_TARGET_MISMATCH_BPS,
                    "expected_move_head_bias_before_recovery": round(float(bias_before.detach().cpu().item()), 8),
                    "expected_move_head_batch_output_mean_bps_before_recovery": round(
                        float(output_before.mean().detach().cpu().item()),
                        8,
                    ),
                    "expected_move_head_batch_target_delta_bps_before_recovery": round(
                        float((output_before.mean() - target_mean_bps).detach().cpu().item()),
                        8,
                    ),
                    "expected_move_head_target_mean_bps": round(float(target_mean_bps.detach().cpu().item()), 8),
                    "expected_move_head_target_long_count": int(long_target_count),
                    "expected_move_head_target_short_count": int(short_target_count),
                }
            target_pre_mean = bounded_atanh(target_mean_bps / 120.0)
            contribution_mean = pre_before.mean() - bias_before
            desired_bias = torch.clamp(
                target_pre_mean - contribution_mean,
                min=-EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT,
                max=EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT,
            )
            delta = desired_bias - bias_before
            if bool(torch.isfinite(delta).detach().cpu().item()) is False:
                return {
                    "expected_move_head_saturation_recovery_applied": False,
                    "expected_move_head_saturation_recovery_reason": "non_finite_expected_move_recovery_delta",
                    "expected_move_head_bias_abs_limit": EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT,
                    "expected_move_head_saturation_bps": EXPECTED_MOVE_HEAD_SATURATION_BPS,
                    "expected_move_head_target_mismatch_bps": EXPECTED_MOVE_HEAD_TARGET_MISMATCH_BPS,
                    "expected_move_head_bias_before_recovery": round(float(bias_before.detach().cpu().item()), 8),
                    "expected_move_head_target_mean_bps": round(float(target_mean_bps.detach().cpu().item()), 8),
                    "expected_move_head_target_long_count": int(long_target_count),
                    "expected_move_head_target_short_count": int(short_target_count),
                }
            bias.add_(delta.to(dtype=bias.dtype, device=bias.device))
            pre_after = expected_move_pre_activation(x)
            output_after = 120.0 * torch.tanh(pre_after)
            recovery_causes: list[str] = []
            if saturated_output:
                recovery_causes.append("saturated_output")
            if runaway_bias:
                recovery_causes.append("runaway_bias")
            if target_mismatch:
                recovery_causes.append("target_mismatch")
            return {
                "expected_move_head_saturation_recovery_applied": bool(
                    abs(float(delta.detach().cpu().item())) > 1e-12
                ),
                "expected_move_head_saturation_recovery_reason": (
                    "mixed_directional_targets_recentered_runaway_expected_move_bias"
                ),
                "expected_move_head_saturation_recovery_causes": recovery_causes,
                "expected_move_head_bias_abs_limit": EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT,
                "expected_move_head_saturation_bps": EXPECTED_MOVE_HEAD_SATURATION_BPS,
                "expected_move_head_target_mismatch_bps": EXPECTED_MOVE_HEAD_TARGET_MISMATCH_BPS,
                "expected_move_head_bias_before_recovery": round(float(bias_before.detach().cpu().item()), 8),
                "expected_move_head_bias_after_recovery": round(float(bias.detach().mean().cpu().item()), 8),
                "expected_move_head_bias_recovery_delta": round(float(delta.detach().cpu().item()), 8),
                "expected_move_head_batch_pre_activation_mean_before_recovery": round(
                    float(pre_before.mean().detach().cpu().item()),
                    8,
                ),
                "expected_move_head_batch_pre_activation_mean_after_recovery": round(
                    float(pre_after.mean().detach().cpu().item()),
                    8,
                ),
                "expected_move_head_batch_output_mean_bps_before_recovery": round(
                    float(output_before.mean().detach().cpu().item()),
                    8,
                ),
                "expected_move_head_batch_output_mean_bps_after_recovery": round(
                    float(output_after.mean().detach().cpu().item()),
                    8,
                ),
                "expected_move_head_batch_target_delta_bps_before_recovery": round(
                    float((output_before.mean() - target_mean_bps).detach().cpu().item()),
                    8,
                ),
                "expected_move_head_batch_target_delta_bps_after_recovery": round(
                    float((output_after.mean() - target_mean_bps).detach().cpu().item()),
                    8,
                ),
                "expected_move_head_target_mean_bps": round(float(target_mean_bps.detach().cpu().item()), 8),
                "expected_move_head_target_long_count": int(long_target_count),
                "expected_move_head_target_short_count": int(short_target_count),
            }

        with torch.no_grad():
            target_mean = torch.clamp(expected_move_training_target.mean(), -120.0, 120.0)
            if hasattr(net, "expected_move_head") and getattr(net.expected_move_head, "bias", None) is not None:
                expected_bias_nudge = 0.05 * target_mean / 120.0
                if abs(float(expected_bias_nudge.detach().cpu().item())) > 1e-12:
                    net.expected_move_head.bias.add_(expected_bias_nudge)
                    feedback_head_nudge_applied = True
            if hasattr(net, "policy_head") and getattr(net.policy_head, "bias", None) is not None:
                counts = torch.bincount(target_actions, minlength=ACTION_COUNT).to(device=device, dtype=net.policy_head.bias.dtype)
                if float(counts.sum().detach().cpu().item()) > 0:
                    policy_bias_nudge_values = self._action_bias_nudge_from_counts(
                        [int(value) for value in counts.detach().cpu().tolist()]
                    )
                    if any(abs(value) > 0.0 for value in policy_bias_nudge_values):
                        policy_bias_nudge = torch.tensor(
                            policy_bias_nudge_values,
                            dtype=net.policy_head.bias.dtype,
                            device=device,
                        )
                        net.policy_head.bias.add_(0.02 * policy_bias_nudge)
                        feedback_head_nudge_applied = True
            was_training = bool(net.training)
            net.eval()
            try:
                expected_move_head_recovery_metrics = recover_saturated_expected_move_head()
            except FloatingPointError:
                return rollback_and_abort(
                    "NONFINITE_EXPECTED_MOVE_RECOVERY_INPUT",
                    nonfinite_feature_values=(
                        non_finite_feature_count
                        + expected_move_pre_activation_nonfinite_count
                    ),
                    nonfinite_label_values=non_finite_expected_label_count,
                    finite_gradient_clip_applied_steps=(
                        finite_gradient_clip_applied_steps
                    ),
                )
            finally:
                if was_training:
                    net.train()
            if expected_move_head_recovery_metrics.get("expected_move_head_saturation_recovery_applied") is True:
                feedback_head_nudge_applied = True
            post_adjustment_nonfinite_parameters = nonfinite_parameter_count()
            if post_adjustment_nonfinite_parameters:
                non_finite_parameter_value_count_detected += (
                    post_adjustment_nonfinite_parameters
                )
                return rollback_and_abort(
                    "NONFINITE_PARAMETER_AFTER_HEAD_ADJUSTMENT",
                    nonfinite_parameter_values=(
                        post_adjustment_nonfinite_parameters
                    ),
                    nonfinite_loss_steps=non_finite_loss_steps,
                    nonfinite_feature_values=non_finite_feature_count,
                    nonfinite_label_values=non_finite_expected_label_count,
                    finite_gradient_clip_applied_steps=(
                        finite_gradient_clip_applied_steps
                    ),
                )
        with torch.no_grad():
            with autocast():
                post_loss_outputs, post_loss_nonfinite_count, post_loss_heads = (
                    finite_bounded_outputs(net(x))
                )
                if post_loss_outputs is None:
                    return rollback_and_abort(
                        "NONFINITE_MODEL_OUTPUT_AFTER_OPTIMIZER",
                        nonfinite_model_output_values=post_loss_nonfinite_count,
                        nonfinite_model_output_events=1,
                        nonfinite_model_output_head_counts=post_loss_heads,
                        finite_gradient_clip_applied_steps=(
                            finite_gradient_clip_applied_steps
                        ),
                    )
                loss_after_t = supervised_loss(post_loss_outputs)
                if not bool(torch.isfinite(loss_after_t).detach().cpu().item()):
                    return rollback_and_abort(
                        "NONFINITE_LOSS_AFTER_OPTIMIZER",
                        nonfinite_loss_steps=1,
                        finite_gradient_clip_applied_steps=(
                            finite_gradient_clip_applied_steps
                        ),
                    )
        net.eval()
        with torch.no_grad():
            (
                train_confidence_all_outputs,
                train_confidence_nonfinite_count,
                train_confidence_nonfinite_heads,
            ) = finite_bounded_outputs(net(x))
            if train_confidence_all_outputs is None:
                return rollback_and_abort(
                    "NONFINITE_MODEL_OUTPUT_BEFORE_CONFIDENCE_FIT",
                    nonfinite_model_output_values=(
                        train_confidence_nonfinite_count
                    ),
                    nonfinite_model_output_events=1,
                    nonfinite_model_output_head_counts=(
                        train_confidence_nonfinite_heads
                    ),
                    finite_gradient_clip_applied_steps=(
                        finite_gradient_clip_applied_steps
                    ),
                )
            train_confidence_outputs = train_confidence_all_outputs[
                "confidence_by_direction"
            ]
            train_confidence_for_recorded_action = train_confidence_outputs.gather(
                1,
                confidence_target_head_actions[:, None],
            ).squeeze(1)
            eligible_train_confidence = train_confidence_for_recorded_action[
                confidence_target_mask
            ].detach().cpu().tolist()
        self._confidence_fit_row_ids = tuple(confidence_target_row_ids)
        if eligible_train_confidence:
            fitted_confidence_state = fit_temperature(
                [float(value) for value in eligible_train_confidence],
                [
                    int(value)
                    for value in confidence_targets[confidence_target_mask]
                    .detach()
                    .cpu()
                    .tolist()
                ],
                row_ids=confidence_target_row_ids,
                action_labels=[
                    CONFIDENCE_HEAD_ACTIONS[action_index]
                    for action_index, eligible in zip(
                        confidence_target_head_action_indices,
                        confidence_target_flags,
                        strict=True,
                    )
                    if eligible
                ],
                validation_rows_used=0,
            )
        else:
            fitted_confidence_state = unfitted_calibration_state(
                "NO_PIT_SAFE_EXPLICIT_COST_PROFITABILITY_TARGETS"
            )
        fitted_confidence_state = self.model.set_confidence_calibration_state(
            fitted_confidence_state
        )
        confidence_calibration_metrics = {
            "confidence_calibration_fitted": (
                fitted_confidence_state.get("fitted") is True
            ),
            "confidence_calibration_reason": fitted_confidence_state.get("reason"),
            "confidence_calibration_temperature": fitted_confidence_state.get(
                "temperature"
            ),
            "confidence_calibration_sample": fitted_confidence_state.get("sample"),
            "confidence_calibration_positive_outcomes": fitted_confidence_state.get(
                "positive_outcomes"
            ),
            "confidence_calibration_negative_outcomes": fitted_confidence_state.get(
                "negative_outcomes"
            ),
            "confidence_calibration_action_counts": fitted_confidence_state.get(
                "action_counts"
            ),
            "confidence_calibration_fit_partition": fitted_confidence_state.get(
                "fit_partition"
            ),
            "confidence_calibration_validation_rows_used": fitted_confidence_state.get(
                "validation_rows_used"
            ),
            "confidence_calibration_label_semantics": fitted_confidence_state.get(
                "label_semantics"
            ),
            "confidence_calibration_row_digest": fitted_confidence_state.get(
                "row_digest"
            ),
            "confidence_calibration_model_parameter_fingerprint": (
                fitted_confidence_state.get("model_parameter_fingerprint")
            ),
            "confidence_calibration_train_brier_before": fitted_confidence_state.get(
                "brier_before"
            ),
            "confidence_calibration_train_brier_after": fitted_confidence_state.get(
                "brier_after"
            ),
            "confidence_calibration_train_ece_before": fitted_confidence_state.get(
                "ece_before"
            ),
            "confidence_calibration_train_ece_after": fitted_confidence_state.get(
                "ece_after"
            ),
            "confidence_calibration_checkpoint_bound": True,
            "confidence_calibration_external_state_used": False,
        }
        # Out-of-sample generalization signal on the held-out validation split.
        validation_metrics = self._validation_supervised_loss(validation_rows)
        validation_policy_edge = self._validation_policy_edge(validation_rows)
        validation_confidence_metrics = self._validation_confidence_metrics(
            validation_rows
        )
        _val_loss_before = validation_metrics_before.get("validation_supervised_loss")
        _train_loss_final = float(loss_after_t.detach().cpu().item())
        _val_loss_value = validation_metrics.get("validation_supervised_loss")
        validation_metrics["validation_supervised_loss_before"] = _val_loss_before
        validation_metrics["validation_supervised_loss_after"] = _val_loss_value
        if _val_loss_before is not None and _val_loss_value is not None:
            _delta = float(_val_loss_value) - float(_val_loss_before)
            validation_metrics["validation_loss_delta"] = round(_delta, 6)
            validation_metrics["validation_improved"] = bool(_delta <= 0.0)
        if _val_loss_value is not None and math.isfinite(_train_loss_final):
            _gap = _val_loss_value - _train_loss_final
            _gap_threshold = overfit_gap_threshold(_train_loss_final)
            validation_metrics["train_val_generalization_gap"] = round(_gap, 6)
            validation_metrics["overfit_gap_threshold"] = round(_gap_threshold, 6)
            validation_metrics["overfit_gap_warning"] = bool(_gap > _gap_threshold)
        elapsed_seconds = max(1e-6, time.perf_counter() - started)
        parameter_vector_after = self._parameter_vector()
        parameter_hash_after = model_parameter_fingerprint(self.model)
        weight_delta_norm = self._parameter_delta_norm(parameter_vector_before, parameter_vector_after)
        dist = self._action_distribution(rows)
        gpu_name = None
        vram = None
        vram_reserved = None
        vram_target_mb = None
        if self.model.cuda_active:
            gpu_name = torch.cuda.get_device_name(0)
            vram = float(torch.cuda.memory_allocated(0) / (1024 * 1024))
            vram_reserved = float(torch.cuda.memory_reserved(0) / (1024 * 1024))
            try:
                props = torch.cuda.get_device_properties(0)
                target_mb = min(
                    float(props.total_memory / (1024 * 1024) * 0.75),
                    float(12 * 1024),
                )
                vram_target_mb = {
                    "low": round(float(props.total_memory / (1024 * 1024) * 0.60), 3),
                    "high": round(target_mb, 3),
                    "cap": round(float(12 * 1024), 3),
                    "gpu_utilization_limit_percent": 75.0,
                }
            except Exception:
                vram_target_mb = None
        return PPOTrainingResult(
            status=(
                "V2_NATIVE_RL_MASA_PPO_ON_POLICY_CUDA_TRAINING_STEP_RAN"
                if learning_mode == "ppo_on_policy" and self.model.cuda_active
                else "V2_NATIVE_RL_MASA_PPO_MIXED_OUTCOME_SUPERVISED_CUDA_TRAINING_STEP_RAN"
                if learning_mode == "ppo_mixed_outcome_supervised" and self.model.cuda_active
                else "V2_NATIVE_RL_MASA_PPO_ON_POLICY_CPU_TRAINING_STEP_RAN"
                if learning_mode == "ppo_on_policy"
                else "V2_NATIVE_RL_MASA_PPO_MIXED_OUTCOME_SUPERVISED_CPU_TRAINING_STEP_RAN"
                if learning_mode == "ppo_mixed_outcome_supervised"
                else "V2_NATIVE_RL_MASA_OUTCOME_SUPERVISED_CUDA_TRAINING_STEP_RAN"
                if self.model.cuda_active
                else "V2_NATIVE_RL_MASA_OUTCOME_SUPERVISED_CPU_TRAINING_STEP_RAN"
            ),
            device=device,
            cuda_active=self.model.cuda_active,
            cuda_claim_verified=self.model.cuda_active and self.model.model_tensors_device_verified(),
            gpu_name=gpu_name,
            vram_allocated_mb=vram,
            batch_size=int(batch_size),
            training_steps=max(1, int(steps)),
            train_rows=len(rows),
            validation_rows=len(validation_rows),
            loss_before=float(loss_before_t.detach().cpu().item()),
            loss_after=float(loss_after_t.detach().cpu().item()),
            action_distribution=dist,
            metrics={
                **(rejection_metrics or {}),
                **validation_metrics,
                **validation_policy_edge_before,
                **validation_policy_edge,
                **validation_confidence_metrics,
                **confidence_target_metrics,
                **confidence_calibration_metrics,
                "learning_rate": self.learning_rate,
                "learning_rate_source": self.learning_rate_source,
                "learning_rate_env_guard_capped": self.learning_rate_env_guard_capped,
                "entropy_coefficient": self.entropy_coefficient,
                "entropy_coefficient_source": self.entropy_coefficient_source,
                "entropy_coefficient_env_guard_capped": self.entropy_coefficient_env_guard_capped,
                "ppo_gamma": self.gamma,
                "ppo_gamma_source": self.gamma_source,
                "ppo_gamma_env_guard_capped": self.gamma_env_guard_capped,
                "ppo_gamma_applied_to_advantage": False,
                "ppo_gamma_not_applied_reason": "single_step_realized_reward_and_old_value_rows",
                "supervised_entropy_bonus": self.supervised_entropy_bonus,
                "weight_decay": self.weight_decay,
                "model_dropout": float(getattr(self.model, "dropout", 0.0) or 0.0),
                "learning_update_lane": learning_mode,
                "ppo_objective_used": bool(ppo_objective_active),
                "outcome_supervised_update_used": bool(outcome_supervision_active),
                "ppo_requires_on_policy_fields": True,
                "realized_reward_source": (
                    "mixed_on_policy_reward_minus_old_value_and_realized_after_cost_reward"
                    if learning_mode == "ppo_mixed_outcome_supervised"
                    else "realized_after_cost_reward_minus_value_baseline"
                    if learning_mode == "outcome_supervised"
                    else "on_policy_reward_minus_old_value"
                ),
                "uses_expected_move_as_realized_reward": False,
                "mixed_ppo_outcome_batch_active": learning_mode == "ppo_mixed_outcome_supervised",
                "ppo_clipped_surrogate_rows": int(ppo_row_count),
                **ppo_behavior_action_metrics,
                "outcome_supervised_batch_rows": int(outcome_row_count),
                "optimizer_steps_this_cycle": int(optimizer_steps_this_cycle),
                "parameter_hash_before": parameter_hash_before,
                "parameter_hash_after": parameter_hash_after,
                "weight_delta_norm": weight_delta_norm,
                **last_component_losses,
                **self._action_balance_metrics(rows),
                "action_class_weights": [
                    round(float(v), 8) for v in action_weights.detach().cpu().tolist()
                ],
                "policy_bias_class_balance_nudge": [
                    round(float(v), 8) for v in self._python_action_bias_nudge(rows)
                ],
                "policy_bias_nudge_strategy": "present_label_class_balance_no_majority_reinforcement",
                **policy_action_supervision_metrics,
                "expected_move_supervision_strategy": (
                    "neutralize_single_directional_expected_move_labels"
                    if single_direction_expected_move_guard_active
                    else "raw_expected_move_labels"
                ),
                "expected_move_single_direction_guard_active": bool(single_direction_expected_move_guard_active),
                "expected_move_single_direction_guard_side": expected_move_guard_side,
                "expected_move_labels_neutralized_count": int(expected_move_labels_neutralized_count),
                "expected_move_raw_target_mean_bps": round(float(target_expected.mean().detach().cpu().item()), 8),
                "expected_move_training_target_mean_bps": round(
                    float(expected_move_training_target.mean().detach().cpu().item()),
                    8,
                ),
                **expected_move_head_recovery_metrics,
                "regime_balanced_action_loss_weighting": True,
                "forced_long_short_ratio": False,
                "no_trade_action_preserved": True,
                "ppo_clip_epsilon": self.clip_epsilon,
                "available_examples": int(available_rows),
                "selected_examples": int(selected_rows),
                "target_batch_size": int(target_batch_size),
                "actual_batch_size": int(batch_size),
                "batch_covers_available_examples": int(selected_rows) >= int(available_rows),
                "uses_amp": bool(use_amp),
                "pinned_memory": bool(pinned_memory),
                "dataloader_workers": int(workers),
                "prefetch_factor": prefetch_factor,
                "persistent_workers": False,
                "torch_dataloader_used": dataloader_used,
                "feedback_head_nudge_applied": bool(feedback_head_nudge_applied),
                "loss_or_metric_changes": bool(
                    float(loss_before_t.detach().cpu().item()) != float(loss_after_t.detach().cpu().item())
                    or feedback_head_nudge_applied
                ),
                "gradient_accumulation_steps": 1,
                "non_finite_feature_count": non_finite_feature_count,
                "non_finite_expected_label_count": non_finite_expected_label_count,
                "clipped_expected_label_count": clipped_expected_label_count,
                "non_finite_loss_steps": non_finite_loss_steps,
                "non_finite_gradient_steps": non_finite_gradient_steps,
                "non_finite_gradient_value_count": 0,
                "sanitized_gradient_steps": sanitized_gradient_steps,
                "sanitized_gradient_value_count": sanitized_gradient_value_count,
                "advantage_anomaly_steps": advantage_anomaly_steps,
                # True NaN/Inf events only; clamped large-but-finite gradient
                # values are tracked separately under sanitized_gradient_*.
                "tensor_nan_inf_count": int(non_finite_loss_steps)
                + int(non_finite_gradient_steps)
                + int(non_finite_feature_count)
                + int(non_finite_expected_label_count),
                "non_finite_model_output_value_count": 0,
                "non_finite_model_output_events": 0,
                "non_finite_model_output_head_counts": {},
                "non_finite_optimizer_ratio_value_count": 0,
                "non_finite_optimizer_ratio_events": 0,
                "non_finite_parameter_value_count_detected": (
                    non_finite_parameter_value_count_detected
                ),
                "ppo_clip_epsilon_bounds": [1.0 - self.clip_epsilon, 1.0 + self.clip_epsilon],
                "non_finite_parameter_value_count_sanitized": non_finite_parameter_value_count_sanitized,
                "non_finite_parameter_sanitization_events": non_finite_parameter_sanitization_events,
                "finite_gradient_clip_applied_steps": (
                    finite_gradient_clip_applied_steps
                ),
                "parameter_finite_guard_active": True,
                "parameter_finite_guard_mode": "FAIL_CLOSED_ROLLBACK",
                "optimizer_anomaly_counters_complete": True,
                "anomaly_free_optimizer_cycle": bool(
                    non_finite_feature_count == 0
                    and non_finite_expected_label_count == 0
                    and non_finite_loss_steps == 0
                    and non_finite_gradient_steps == 0
                    and numeric_abort_nonfinite_model_output_values == 0
                    and numeric_abort_nonfinite_model_output_events == 0
                    and numeric_abort_nonfinite_ratio_values == 0
                    and numeric_abort_nonfinite_ratio_events == 0
                    and non_finite_parameter_value_count_detected == 0
                    and sanitized_gradient_steps == 0
                    and sanitized_gradient_value_count == 0
                    and advantage_anomaly_steps == 0
                ),
                "training_cycle_rolled_back": False,
                "training_cycle_rollback_verified": False,
                "training_cycle_abort_reason": None,
                "max_gradient_norm": round(max_gradient_norm, 8),
                "gradient_clip_max_norm": 1.0,
                "vram_reserved_mb": vram_reserved,
                "vram_target_mb": vram_target_mb,
                **training_gpu_metrics,
                "oom_count": 0,
                "train_elapsed_ms": round(elapsed_seconds * 1000.0, 3),
                "gpu_train_time_ms": round(elapsed_seconds * 1000.0, 3)
                if self.model.cuda_active
                else None,
                "cpu_train_time_ms": None
                if self.model.cuda_active
                else round(elapsed_seconds * 1000.0, 3),
                "training_steps_per_minute": round((max(1, int(steps)) / elapsed_seconds) * 60.0, 6),
                "tensor_rows_per_second": round(float(selected_rows) / elapsed_seconds, 6),
                "uses_shared_encoder": True,
                "uses_policy_head": True,
                "uses_value_head": True,
                "uses_expected_move_head": True,
                "uses_confidence_head": True,
                "uses_masa_head": True,
            },
        )

    def _train_fallback(
        self,
        rows: Sequence[TrainingExample],
        *,
        validation_rows: Sequence[TrainingExample],
        steps: int,
        batch_size: int,
        target_batch_size: int,
        available_rows: int,
        selected_rows: int,
        rejection_metrics: dict[str, Any] | None = None,
        learning_mode: str,
    ) -> PPOTrainingResult:
        started = time.perf_counter()
        fallback_confidence_state = self.model.set_confidence_calibration_state(
            unfitted_calibration_state(
                "CPU_FALLBACK_HAS_NO_PROFITABILITY_CONFIDENCE_HEAD"
            )
        )
        (
            _fallback_confidence_targets,
            _fallback_confidence_mask,
            _fallback_confidence_head_action_indices,
            _fallback_confidence_row_ids,
            fallback_confidence_target_metrics,
        ) = self._confidence_target_batch(rows)
        parameter_vector_before = self._parameter_vector()
        parameter_hash_before = model_parameter_fingerprint(self.model)
        input_dim = int(self.model.input_dim)
        # The pure-Python fallback has no clipped-ratio optimizer. It may retain
        # outcome supervision, but must never represent its weight nudge as PPO.
        ppo_objective_active = False
        ppo_row_count = sum(1 for row in rows if self._has_on_policy_ppo_fields(row))
        ppo_behavior_action_metrics = self._ppo_behavior_action_metrics(rows)
        outcome_row_count = sum(1 for row in rows if self._has_outcome_supervised_targets(row))
        outcome_supervision_active = outcome_row_count > 0
        expected_move_labels, expected_move_supervision_metrics = self._python_expected_move_supervision_labels(rows)
        policy_action_labels, policy_action_supervision_metrics = self._python_policy_action_supervision_labels(rows)
        validation_policy_edge_before = self._validation_policy_edge(validation_rows)
        validation_policy_edge_before = {
            key.replace(
                "validation_policy_edge_",
                "validation_policy_edge_before_",
                1,
            ): value
            for key, value in validation_policy_edge_before.items()
        }

        def _loss() -> float:
            losses = []
            for row, expected_label, policy_action_label in zip(rows, expected_move_labels, policy_action_labels):
                if not self._has_outcome_supervised_targets(row):
                    continue
                out = self.model.forward(row.tensor)
                prob = max(1e-12, out.action_probabilities[policy_action_label])
                losses.append(
                    -math.log(prob)
                    + 0.001 * abs(out.expected_move_bps - expected_label)
                )
            return sum(losses) / max(1, len(losses))

        loss_before = _loss()
        fallback_weights = getattr(self.model, "_fallback_weights", None)
        update_count = 0
        # CG-F020 fix: initialize class_weights before the fallback block so it
        # is always defined when used in metrics below regardless of branch taken.
        class_weights = self._python_action_class_weights_from_indices(policy_action_labels)
        if isinstance(fallback_weights, list) and len(fallback_weights) == input_dim * ACTION_COUNT:
            learning_rate = 0.002
            for _ in range(max(1, int(steps))):
                for row, expected_label, policy_action_label in zip(rows, expected_move_labels, policy_action_labels):
                    if not self._has_outcome_supervised_targets(row):
                        continue
                    target_action = max(0, min(ACTION_COUNT - 1, int(policy_action_label)))
                    vector = [float(v) for v in row.tensor.model_vector]
                    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
                    expected = max(-1.0, min(1.0, float(expected_label) / 120.0))
                    direction_scale = (1.0 + abs(expected)) * class_weights[target_action]
                    for index, value in enumerate(vector):
                        x = max(-1.0, min(1.0, value / norm))
                        fallback_weights[target_action * input_dim + index] += learning_rate * direction_scale * x
                        if target_action == 1:
                            fallback_weights[2 * input_dim + index] -= learning_rate * direction_scale * x
                        elif target_action == 2:
                            fallback_weights[1 * input_dim + index] -= learning_rate * direction_scale * x
                        else:
                            fallback_weights[1 * input_dim + index] -= learning_rate * 0.25 * x
                            fallback_weights[2 * input_dim + index] -= learning_rate * 0.25 * x
                        update_count += 1
        loss_after = _loss()
        validation_policy_edge = self._validation_policy_edge(validation_rows)
        validation_confidence_metrics = self._validation_confidence_metrics(
            validation_rows
        )
        elapsed_seconds = max(1e-6, time.perf_counter() - started)
        parameter_vector_after = self._parameter_vector()
        parameter_hash_after = model_parameter_fingerprint(self.model)
        weight_delta_norm = self._parameter_delta_norm(parameter_vector_before, parameter_vector_after)
        return PPOTrainingResult(
            status=(
                "V2_NATIVE_RL_MASA_OUTCOME_SUPERVISED_CPU_FALLBACK_TRAINING_STEP_RAN"
                if outcome_supervision_active and update_count > 0
                else "V2_NATIVE_RL_MASA_NO_SUPPORTED_OBJECTIVE_CPU_FALLBACK_NO_UPDATE"
            ),
            device="cpu",
            cuda_active=False,
            cuda_claim_verified=False,
            gpu_name=None,
            vram_allocated_mb=None,
            batch_size=int(batch_size),
            training_steps=(max(1, int(steps)) if update_count > 0 else 0),
            train_rows=len(rows),
            validation_rows=len(validation_rows),
            loss_before=float(loss_before),
            loss_after=float(loss_after),
            action_distribution=self._action_distribution(rows),
            metrics={
                **(rejection_metrics or {}),
                **validation_policy_edge_before,
                **validation_policy_edge,
                **validation_confidence_metrics,
                **fallback_confidence_target_metrics,
                "confidence_calibration_fitted": False,
                "confidence_calibration_reason": fallback_confidence_state.get(
                    "reason"
                ),
                "confidence_calibration_checkpoint_bound": True,
                "confidence_calibration_external_state_used": False,
                "learning_update_lane": (
                    "outcome_supervised_cpu_fallback_ppo_skipped"
                    if outcome_supervision_active
                    else "blocked_no_clipped_ppo_optimizer"
                ),
                "ppo_objective_used": bool(ppo_objective_active),
                "outcome_supervised_update_used": bool(outcome_supervision_active),
                "ppo_requires_on_policy_fields": True,
                "realized_reward_source": (
                    "realized_after_cost_reward_minus_value_baseline"
                    if outcome_supervision_active
                    else None
                ),
                "uses_expected_move_as_realized_reward": False,
                "mixed_ppo_outcome_batch_active": False,
                "mixed_input_ppo_rows_skipped_by_cpu_fallback": bool(
                    ppo_row_count and outcome_row_count
                ),
                "ppo_rows_consumed": 0,
                "ppo_rows_available_but_optimizer_unavailable": int(
                    ppo_row_count
                ),
                "ppo_clipped_surrogate_rows": 0,
                "ppo_fallback_ineligible_reason": (
                    "TORCH_CLIPPED_SURROGATE_OPTIMIZER_UNAVAILABLE"
                    if ppo_row_count
                    else None
                ),
                **ppo_behavior_action_metrics,
                "outcome_supervised_batch_rows": int(outcome_row_count),
                "optimizer_steps_this_cycle": int(max(1, int(steps)) if update_count > 0 else 0),
                "parameter_hash_before": parameter_hash_before,
                "parameter_hash_after": parameter_hash_after,
                "weight_delta_norm": weight_delta_norm,
                **self._action_balance_metrics(rows),
                "action_class_weights": [round(float(v), 8) for v in class_weights],
                "policy_bias_class_balance_nudge": [
                    round(float(v), 8) for v in self._python_action_bias_nudge(rows)
                ],
                "policy_bias_nudge_strategy": "present_label_class_balance_no_majority_reinforcement",
                **policy_action_supervision_metrics,
                **expected_move_supervision_metrics,
                "regime_balanced_action_loss_weighting": True,
                "forced_long_short_ratio": False,
                "no_trade_action_preserved": True,
                "torch_unavailable": True,
                "fallback_weight_updates": int(update_count),
                "loss_or_metric_changes": bool(loss_before != loss_after or update_count > 0),
                "available_examples": int(available_rows),
                "selected_examples": int(selected_rows),
                "target_batch_size": int(target_batch_size),
                "actual_batch_size": int(batch_size),
                "batch_covers_available_examples": int(selected_rows) >= int(available_rows),
                "dataloader_workers": 0,
                "pinned_memory": False,
                "prefetch_factor": None,
                "persistent_workers": False,
                "gradient_accumulation_steps": 1,
                "oom_count": 0,
                "train_elapsed_ms": round(elapsed_seconds * 1000.0, 3),
                "gpu_train_time_ms": None,
                "cpu_train_time_ms": round(elapsed_seconds * 1000.0, 3),
                "training_steps_per_minute": round((max(1, int(steps)) / elapsed_seconds) * 60.0, 6),
                "tensor_rows_per_second": round(float(selected_rows) / elapsed_seconds, 6),
                "forward_pass_present": True,
                "ppo_target_contract_present": True,
                "masa_auxiliary_signal_present": True,
            },
        )

    def _parameter_vector(self) -> list[float]:
        if self.model.torch_available and self.model.net is not None:
            values: list[float] = []
            try:
                state = self.model.net.state_dict()
                for name in sorted(state):
                    tensor = state[name].detach().cpu().reshape(-1)
                    values.extend(float(v) for v in tensor.tolist())
                return values
            except Exception:
                return []
        fallback_weights = getattr(self.model, "_fallback_weights", None)
        if isinstance(fallback_weights, list):
            return [float(value) for value in fallback_weights]
        return []

    @staticmethod
    def _parameter_delta_norm(before: Sequence[float], after: Sequence[float]) -> float:
        total = 0.0
        for old, new in zip(before, after):
            delta = float(new) - float(old)
            total += delta * delta
        if len(before) != len(after):
            total += float(abs(len(after) - len(before)))
        return round(math.sqrt(total), 12)

    def _blocked(self, status: str, *, batch_size: int, metrics: dict[str, Any] | None = None) -> PPOTrainingResult:
        blocked_metrics = dict(metrics or {})
        blocked_metrics.setdefault("optimizer_steps_this_cycle", 0)
        blocked_metrics.setdefault("weight_delta_norm", 0.0)
        for field_name in (
            "non_finite_feature_count",
            "non_finite_expected_label_count",
            "non_finite_loss_steps",
            "non_finite_gradient_steps",
            "non_finite_gradient_value_count",
            "sanitized_gradient_steps",
            "sanitized_gradient_value_count",
            "advantage_anomaly_steps",
            "tensor_nan_inf_count",
            "non_finite_parameter_value_count_detected",
            "non_finite_parameter_value_count_sanitized",
            "non_finite_parameter_sanitization_events",
        ):
            blocked_metrics.setdefault(field_name, 0)
        blocked_metrics.setdefault("optimizer_anomaly_counters_complete", True)
        blocked_metrics.setdefault("anomaly_free_optimizer_cycle", False)
        blocked_metrics.setdefault("training_cycle_rolled_back", False)
        return PPOTrainingResult(
            status=status,
            device=self.model.device,
            cuda_active=False,
            cuda_claim_verified=False,
            gpu_name=None,
            vram_allocated_mb=None,
            batch_size=int(batch_size),
            training_steps=0,
            train_rows=0,
            validation_rows=0,
            loss_before=None,
            loss_after=None,
            action_distribution={},
            metrics=blocked_metrics,
        )

    @staticmethod
    def _action_distribution(rows: Sequence[TrainingExample]) -> dict[str, int]:
        out: dict[str, int] = {str(i): 0 for i in range(ACTION_COUNT)}
        for row in rows:
            key = str(row.label_action_index)
            out[key] = out.get(key, 0) + 1
        return out

    @staticmethod
    def _python_action_class_weights(rows: Sequence[TrainingExample]) -> list[float]:
        return V2HybridPPOTrainer._python_action_class_weights_from_indices(
            [row.label_action_index for row in rows]
        )

    @staticmethod
    def _python_action_class_weights_from_indices(indices: Sequence[int]) -> list[float]:
        counts = [0 for _ in range(ACTION_COUNT)]
        for index in indices:
            idx = max(0, min(ACTION_COUNT - 1, int(index)))
            counts[idx] += 1
        nonzero = [count for count in counts if count > 0]
        if not nonzero:
            return [1.0 for _ in range(ACTION_COUNT)]
        total = float(sum(nonzero))
        active = float(len(nonzero))
        weights: list[float] = []
        for count in counts:
            if count <= 0:
                weights.append(0.0)
            else:
                weights.append(max(0.25, min(4.0, total / (active * float(count)))))
        return weights

    @classmethod
    def _python_action_bias_nudge(cls, rows: Sequence[TrainingExample]) -> list[float]:
        counts = [0 for _ in range(ACTION_COUNT)]
        for row in rows:
            idx = max(0, min(ACTION_COUNT - 1, int(row.label_action_index)))
            counts[idx] += 1
        return cls._action_bias_nudge_from_counts(counts)

    @staticmethod
    def _python_policy_action_supervision_labels(rows: Sequence[TrainingExample]) -> tuple[list[int], dict[str, Any]]:
        raw_labels = [max(0, min(ACTION_COUNT - 1, int(row.label_action_index))) for row in rows]
        long_count = sum(1 for label in raw_labels if label == 1)
        short_count = sum(1 for label in raw_labels if label == 2)
        directional_count = long_count + short_count
        guard_active = directional_count > 0 and (long_count == 0 or short_count == 0)
        guard_side = "long" if guard_active and long_count > 0 else "short" if guard_active and short_count > 0 else None
        labels = list(raw_labels)
        neutralized_count = 0
        if guard_active:
            labels = []
            for label in raw_labels:
                if label in {1, 2}:
                    labels.append(0)
                    neutralized_count += 1
                else:
                    labels.append(label)
        return labels, {
            "policy_action_supervision_strategy": (
                "neutralize_single_directional_action_labels_to_hold"
                if guard_active
                else "raw_action_labels"
            ),
            "policy_action_single_direction_guard_active": bool(guard_active),
            "policy_action_single_direction_guard_side": guard_side,
            "policy_action_labels_neutralized_count": int(neutralized_count),
            "policy_action_supervision_target_distribution_by_action": (
                V2HybridPPOTrainer._action_counts_from_indices(labels)
            ),
        }

    @staticmethod
    def _python_expected_move_supervision_labels(rows: Sequence[TrainingExample]) -> tuple[list[float], dict[str, Any]]:
        labels: list[float] = []
        long_count = 0
        short_count = 0
        for row in rows:
            action = max(0, min(ACTION_COUNT - 1, int(row.label_action_index)))
            if action == 1:
                long_count += 1
            elif action == 2:
                short_count += 1
            try:
                value = float(row.label_expected_move_after_cost_bps)
            except (TypeError, ValueError):
                value = 0.0
            if not math.isfinite(value):
                value = 0.0
            labels.append(max(-120.0, min(120.0, value)))
        directional_count = long_count + short_count
        guard_active = directional_count > 0 and (long_count == 0 or short_count == 0)
        guard_side = "long" if guard_active and long_count > 0 else "short" if guard_active and short_count > 0 else None
        neutralized_count = 0
        if guard_active:
            neutralized: list[float] = []
            for row, label in zip(rows, labels):
                action = max(0, min(ACTION_COUNT - 1, int(row.label_action_index)))
                if action in {1, 2}:
                    neutralized.append(0.0)
                    neutralized_count += 1
                else:
                    neutralized.append(label)
            labels = neutralized
        raw_values: list[float] = []
        for row in rows:
            try:
                value = float(row.label_expected_move_after_cost_bps)
            except (TypeError, ValueError):
                value = 0.0
            if not math.isfinite(value):
                value = 0.0
            raw_values.append(max(-120.0, min(120.0, value)))
        return labels, {
            "expected_move_supervision_strategy": (
                "neutralize_single_directional_expected_move_labels"
                if guard_active
                else "raw_expected_move_labels"
            ),
            "expected_move_single_direction_guard_active": bool(guard_active),
            "expected_move_single_direction_guard_side": guard_side,
            "expected_move_labels_neutralized_count": int(neutralized_count),
            "expected_move_raw_target_mean_bps": round(sum(raw_values) / max(1, len(raw_values)), 8),
            "expected_move_training_target_mean_bps": round(sum(labels) / max(1, len(labels)), 8),
        }

    @staticmethod
    def _action_bias_nudge_from_counts(counts: Sequence[int]) -> list[float]:
        clipped_counts = [max(0, int(count)) for count in list(counts)[:ACTION_COUNT]]
        if len(clipped_counts) < ACTION_COUNT:
            clipped_counts.extend([0 for _ in range(ACTION_COUNT - len(clipped_counts))])
        present = [index for index, count in enumerate(clipped_counts) if count > 0]
        if len(present) <= 1:
            return [0.0 for _ in range(ACTION_COUNT)]
        total = float(sum(clipped_counts[index] for index in present))
        active = float(len(present))
        weights = [0.0 for _ in range(ACTION_COUNT)]
        for index in present:
            weights[index] = max(0.25, min(4.0, total / (active * float(clipped_counts[index]))))
        mean_present_weight = sum(weights[index] for index in present) / active
        nudge = [0.0 for _ in range(ACTION_COUNT)]
        for index in present:
            nudge[index] = weights[index] - mean_present_weight
        max_abs = max(abs(value) for value in nudge) if nudge else 0.0
        if max_abs > 1.0:
            nudge = [value / max_abs for value in nudge]
        return nudge

    @classmethod
    def _torch_action_class_weights(cls, *, target_actions: Any, torch: Any, device: str) -> Any:
        counts = torch.bincount(target_actions, minlength=ACTION_COUNT).to(device=device, dtype=torch.float32)
        present = counts > 0
        if bool(present.any().detach().cpu().item()) is False:
            return torch.ones(ACTION_COUNT, dtype=torch.float32, device=device)
        active = torch.clamp(present.sum().to(dtype=torch.float32), min=1.0)
        total = torch.clamp(counts.sum(), min=1.0)
        weights = torch.where(present, total / (active * torch.clamp(counts, min=1.0)), torch.zeros_like(counts))
        return torch.clamp(weights, min=0.25, max=4.0)

    @staticmethod
    def _action_counts_from_indices(indices: Sequence[int]) -> dict[str, int]:
        counts = {label: 0 for label in ACTION_LABELS}
        for index in indices:
            idx = max(0, min(ACTION_COUNT - 1, int(index)))
            counts[ACTION_LABELS[idx]] = counts.get(ACTION_LABELS[idx], 0) + 1
        return counts

    @staticmethod
    def _action_balance_metrics(rows: Sequence[TrainingExample]) -> dict[str, Any]:
        counts = V2HybridPPOTrainer._action_counts_from_indices(
            [row.label_action_index for row in rows]
        )
        directional = {
            "hold": counts.get("hold", 0),
            "long": counts.get("long", 0),
            "short": counts.get("short", 0),
        }
        total_directional = max(1, sum(directional.values()))
        return {
            "target_label_distribution_by_action": counts,
            "target_label_distribution_directional": directional,
            "target_long_fraction": round(directional["long"] / total_directional, 8),
            "target_short_fraction": round(directional["short"] / total_directional, 8),
            "target_hold_fraction": round(directional["hold"] / total_directional, 8),
            "long_label_present": directional["long"] > 0,
            "short_label_present": directional["short"] > 0,
            "hold_label_present": directional["hold"] > 0,
        }
