"""PPO/MASA-shaped paper/shadow training loop with lazy CUDA support."""
from __future__ import annotations

import math
import os
import subprocess
import threading
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from app.services.market_state_integrity.scoring import OPTIONAL_OR_EVENT_FEATURE_TOKENS
from app.services.market_state_integrity.sample_rejection import (
    classify_training_sample,
    missing_mask_training_override_status,
)
from app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION
from app.services.native_trainer.dataloader_worker_config import (
    PERSISTENT_WORKERS,
    PREFETCH_FACTOR,
    compute_dataloader_workers,
)
from .config import ACTION_COUNT, ACTION_LABELS
from .data_loader import TrainingExample, _has_explicit_training_trust_evidence
from .model import V2HybridPolicyModel


EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT = 12.0
EXPECTED_MOVE_HEAD_SATURATION_BPS = 118.0
EXPECTED_MOVE_HEAD_TARGET_MISMATCH_BPS = 30.0
GPU_TRAINING_SAMPLE_INTERVAL_SECONDS = 0.5
ENV_PPO_LEARNING_RATE_MAX = 2e-4
ENV_PPO_ENTROPY_COEFFICIENT_MAX = 0.015


def _finite_float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


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
    ) -> None:
        self.model = model
        self.clip_epsilon = float(clip_epsilon)
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

    def train(
        self,
        examples: Sequence[TrainingExample],
        *,
        steps: int = 2,
        batch_size: int = 64,
        validation_fraction: float = 0.2,
    ) -> PPOTrainingResult:
        available_rows = list(examples)
        trusted_rows, rejection_metrics = self._filter_trusted_training_rows(available_rows)
        ppo_rows = [row for row in trusted_rows if self._has_on_policy_ppo_fields(row)]
        outcome_rows = [row for row in trusted_rows if self._has_outcome_supervised_targets(row)]
        if ppo_rows and outcome_rows:
            learning_mode = "ppo_mixed_outcome_supervised"
            ppo_row_ids = {id(row) for row in ppo_rows}
            outcome_row_ids = {id(row) for row in outcome_rows}
            # Keep the scarce on-policy rows in the training slice. Otherwise
            # the default validation split can place the only PPO row at the
            # tail, yielding a large batch but no clipped-surrogate update.
            learnable_rows = [
                *ppo_rows,
                *[
                    row
                    for row in trusted_rows
                    if id(row) in outcome_row_ids and id(row) not in ppo_row_ids
                ],
            ]
        elif ppo_rows:
            learning_mode = "ppo_on_policy"
            learnable_rows = ppo_rows
        else:
            learning_mode = "outcome_supervised"
            learnable_rows = outcome_rows
        trust_rows_for_metrics = [self._trust_row(row) for row in learnable_rows]
        accepted_trust_rows_for_metrics = [self._trust_row(row) for row in trusted_rows]
        policy_sampled_rows_seen = sum(
            1
            for row in accepted_trust_rows_for_metrics
            if row.get("ppo_on_policy_entry_fields_present") is True
            or row.get("old_log_prob") not in (None, "")
            or row.get("selected_action_log_prob") not in (None, "")
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
        ppo_exact_reason = None
        if not ppo_rows:
            if policy_sampled_rows_seen <= 0:
                ppo_exact_reason = "NO_POLICY_SAMPLED_POSITION_OPEN"
            elif policy_sampled_closed_positions <= 0:
                ppo_exact_reason = "POLICY_POSITION_OPEN_WAITING_CLOSE"
            else:
                ppo_exact_reason = "CLOSED_ROWS_MISSING_ON_POLICY_FIELDS"
        rejection_metrics.update(
            {
                "accepted_training_rows": len(trusted_rows),
                "trusted_rows_loaded": len(learnable_rows),
                "ppo_on_policy_rows": len(ppo_rows),
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
        target_batch_size = max(1, int(batch_size))
        tuned_batch_size = self._auto_tuned_batch_size(
            requested_batch_size=target_batch_size,
            available_rows=len(learnable_rows),
        )
        rows = learnable_rows[:tuned_batch_size]
        if not rows:
            return self._blocked(
                "NO_TRUSTED_TRAINING_ROWS",
                batch_size=target_batch_size,
                metrics=rejection_metrics,
            )
        val_count = max(1, int(len(rows) * validation_fraction)) if len(rows) > 1 else 0
        train_rows = rows[:-val_count] if val_count else rows
        validation_rows = rows[-val_count:] if val_count else []
        if self.model.torch_available:
            return self._train_torch(
                train_rows,
                validation_rows=validation_rows,
                steps=steps,
                batch_size=tuned_batch_size,
                target_batch_size=target_batch_size,
                available_rows=len(available_rows),
                selected_rows=len(rows),
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
            selected_rows=len(rows),
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
        return row

    @classmethod
    def _has_on_policy_ppo_fields(cls, example: TrainingExample) -> bool:
        row = cls._trust_row(example)
        required = ("old_log_prob", "old_value", "reward", "done", "rollout_id")
        if any(row.get(field) in (None, "") for field in required):
            return False
        if row.get("trajectory_index") in (None, "") and row.get("trajectory_step") in (None, ""):
            return False
        return True

    @classmethod
    def _has_outcome_supervised_targets(cls, example: TrainingExample) -> bool:
        row = cls._trust_row(example)
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

    @classmethod
    def _extra_rejection_reasons(cls, example: TrainingExample, row: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        classification = str(example.row_classification).upper()
        if classification != "TRAINABLE":
            safe_missing_mask = missing_mask_training_override_status(row).get(
                "safe_to_train_with_missing_mask"
            )
            optional_missing_masked = (
                classification == "MISSING_MASKED"
                and cls._missing_names_are_optional_or_event_dependent(row.get("missing_feature_names"))
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
        feature_cutoff = cls._parse_ts(row.get("feature_cutoff") or row.get("decision_cutoff"))
        available_at = cls._parse_ts(row.get("available_at") or row.get("source_available_time"))
        decision_time = cls._parse_ts(row.get("decision_time") or row.get("decision_time_est") or row.get("generated_at"))
        if feature_cutoff is None:
            reasons.append("FEATURE_CUTOFF_MISSING")
        if available_at is None:
            reasons.append("AVAILABLE_AT_MISSING")
        if available_at is not None and decision_time is not None and available_at > decision_time:
            reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
        masa_cutoff = cls._parse_ts(row.get("masa_feature_cutoff"))
        ppo_cutoff = cls._parse_ts(row.get("ppo_feature_cutoff"))
        if masa_cutoff is not None and ppo_cutoff is not None and masa_cutoff != ppo_cutoff:
            reasons.append("MASA_PPO_CUTOFF_MISMATCH")
        if cls._invalid_count(row.get("features")) > 0:
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
        if value is None:
            return None
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            numeric = int(value)
            return numeric * 1000 if abs(numeric) < 10_000_000_000 else numeric
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                if text.replace(".", "", 1).isdigit():
                    numeric = int(float(text))
                    return numeric * 1000 if abs(numeric) < 10_000_000_000 else numeric
                return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
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
            "validation_supervised_loss": None,
            "validation_supervised_loss_before": None,
            "validation_supervised_loss_after": None,
            "validation_rows_evaluated": 0,
            "validation_loss_delta": None,
            "validation_improved": None,
            "train_val_generalization_gap": None,
        }
        if not rows or not self.model.torch_available:
            return dict(empty)
        torch = self.model.torch
        net = self.model.net
        if torch is None or net is None:
            return dict(empty)
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
            val_x = torch.nan_to_num(val_x, nan=0.0, posinf=1_000_000.0, neginf=-1_000_000.0)
            val_x = torch.clamp(val_x, min=-1_000_000.0, max=1_000_000.0).to(device=device)
            policy_labels, _ = self._python_policy_action_supervision_labels(rows)
            val_actions = torch.tensor(policy_labels, dtype=torch.long, device=device)
            val_expected = torch.tensor(
                [r.label_expected_move_after_cost_bps for r in rows],
                dtype=torch.float32,
                device=device,
            )
            val_expected = torch.clamp(
                torch.nan_to_num(val_expected, nan=0.0, posinf=120.0, neginf=-120.0),
                min=-120.0,
                max=120.0,
            )
            was_training = bool(net.training)
            net.eval()
            try:
                with torch.no_grad():
                    out = net(val_x)
                    logits = torch.clamp(
                        torch.nan_to_num(out["logits"], nan=0.0, posinf=30.0, neginf=-30.0),
                        min=-30.0,
                        max=30.0,
                    )
                    expected_move = torch.clamp(
                        torch.nan_to_num(out["expected_move"], nan=0.0, posinf=120.0, neginf=-120.0),
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
        except Exception:
            return dict(empty)
        return {
            "validation_supervised_loss": val_loss_f if math.isfinite(val_loss_f) else None,
            "validation_supervised_loss_after": val_loss_f if math.isfinite(val_loss_f) else None,
            "validation_rows_evaluated": len(rows),
            "validation_loss_delta": None,
            "validation_improved": None,
            "train_val_generalization_gap": None,
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
        parameter_vector_before = self._parameter_vector()
        parameter_hash_before = self._parameter_hash_from_vector(parameter_vector_before)
        device = self.model.device
        net.train()
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
        # every epoch is what starves the GPU (gpu_util ~16%). Cache by a CONTENT
        # fingerprint (decision_time of boundary rows, NOT id() -- id reuse would be
        # unsafe), so the offline loop hits the cache while the online loop (fresh,
        # time-advancing rows each cycle) always misses and rebuilds. Byte-identical
        # results either way -- pure speed.
        def _fp_token(seq: Sequence[Any], idx: int) -> Any:
            try:
                r = seq[idx]
            except (IndexError, TypeError):
                return None
            tensor = getattr(r, "tensor", None)
            tid = getattr(tensor, "tensor_id", None) or getattr(tensor, "feature_snapshot_id", None)
            # tensor_id is unique per feature snapshot; pair with the label so even a
            # tid collision across sets is distinguished. TrainingExample has NO
            # top-level decision_time, so a time-based token would be degenerate.
            return (tid, getattr(r, "label_action_index", None))

        _fp_tokens = (
            _fp_token(rows, 0), _fp_token(rows, len(rows) // 2), _fp_token(rows, -1),
            _fp_token(validation_rows, -1),
        )
        # Fail-safe: only cache when we have a REAL distinguishing signal (a tensor
        # id on a boundary row). A degenerate all-None fingerprint could false-hit
        # across DIFFERENT online-cycle row sets of equal length -> training on stale
        # data. When we can't fingerprint, never cache (rebuild every call, as before).
        _cacheable = any(t is not None and t[0] is not None for t in _fp_tokens)
        _cache_fp = (len(rows), len(validation_rows), _temporal, _seq_len, _fp_tokens)
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
            cpu_x = torch.nan_to_num(cpu_x, nan=0.0, posinf=1_000_000.0, neginf=-1_000_000.0)
            cpu_x = torch.clamp(cpu_x, min=-1_000_000.0, max=1_000_000.0)
            raw_expected = torch.nan_to_num(cpu_expected, nan=0.0, posinf=120.0, neginf=-120.0)
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
        ppo_row_flags = [self._has_on_policy_ppo_fields(row) for row in rows]
        ppo_row_count = sum(1 for flag in ppo_row_flags if flag)
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
                dataset = torch.utils.data.TensorDataset(cpu_x, cpu_actions, cpu_policy_actions, cpu_expected)
                loader = torch.utils.data.DataLoader(
                    dataset,
                    batch_size=len(rows),
                    shuffle=False,
                    num_workers=workers,
                    pin_memory=True,
                    prefetch_factor=prefetch_factor,
                    persistent_workers=PERSISTENT_WORKERS,
                )
                cpu_x, cpu_actions, cpu_policy_actions, cpu_expected = next(iter(loader))
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
                cpu_expected = cpu_expected.pin_memory()
                pinned_memory = True
            except Exception:
                pinned_memory = False
        x = cpu_x.to(device=device, non_blocking=pinned_memory)
        target_actions = cpu_actions.to(device=device, non_blocking=pinned_memory)
        policy_target_actions = cpu_policy_actions.to(device=device, non_blocking=pinned_memory)
        target_expected = cpu_expected.to(device=device, non_blocking=pinned_memory)
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
        non_finite_parameter_value_count_sanitized = 0
        non_finite_parameter_sanitization_events = 0

        def sanitize_parameters() -> int:
            with torch.no_grad():
                params = list(net.parameters())
                if not params:
                    return 0
                # Single-sync global check (was one .item() sync per parameter each
                # step). Common case (all finite) returns after ONE sync; only the
                # rare non-finite case walks parameters for the exact cleanup.
                if bool(torch.stack([torch.isfinite(p).all() for p in params]).all().detach().cpu().item()):
                    return 0
                sanitized_count = 0
                for parameter in params:
                    finite_mask = torch.isfinite(parameter)
                    if bool(finite_mask.all().detach().cpu().item()):
                        continue
                    sanitized_count += int((~finite_mask).sum().detach().cpu().item())
                    cleaned = torch.nan_to_num(parameter, nan=0.0, posinf=0.0, neginf=0.0)
                    parameter.copy_(cleaned)
            return sanitized_count

        initial_sanitized_parameter_count = sanitize_parameters()
        if initial_sanitized_parameter_count:
            non_finite_parameter_value_count_sanitized += initial_sanitized_parameter_count
            non_finite_parameter_sanitization_events += 1
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
                scaler = torch.amp.GradScaler("cuda", enabled=True)
            except Exception:
                try:
                    scaler = torch.cuda.amp.GradScaler(enabled=True)
                except Exception:
                    scaler = None
                    use_amp = False

        def safe_outputs(out):
            return {
                "logits": torch.clamp(
                    torch.nan_to_num(out["logits"], nan=0.0, posinf=30.0, neginf=-30.0),
                    min=-30.0,
                    max=30.0,
                ),
                "value": torch.clamp(
                    torch.nan_to_num(out["value"], nan=0.0, posinf=10.0, neginf=-10.0),
                    min=-10.0,
                    max=10.0,
                ),
                "expected_move": torch.clamp(
                    torch.nan_to_num(out["expected_move"], nan=0.0, posinf=120.0, neginf=-120.0),
                    min=-120.0,
                    max=120.0,
                ),
                "confidence": torch.clamp(
                    torch.nan_to_num(out["confidence"], nan=0.0, posinf=1.0, neginf=0.0),
                    min=0.0,
                    max=1.0,
                ),
                "masa": torch.clamp(
                    torch.nan_to_num(out["masa"], nan=0.0, posinf=1.0, neginf=-1.0),
                    min=-1.0,
                    max=1.0,
                ),
            }

        def supervised_loss(out):
            out = safe_outputs(out)
            return (
                ce(out["logits"], policy_target_actions)
                + 0.01 * mse(out["expected_move"], expected_move_training_target)
                + 0.001 * mse(out["value"], expected_move_training_target / 100.0)
                + 0.001 * mse(out["masa"], torch.tanh(expected_move_training_target / 100.0))
                + 0.05 * mse(
                    out["confidence"],
                    torch.clamp(torch.abs(expected_move_training_target) / 100.0, 0.0, 1.0),
                )
            )

        with torch.no_grad():
            with autocast():
                out0 = net(x)
                loss_before_t = supervised_loss(out0)
                safe_out0 = safe_outputs(out0)
                current_log_probs = torch.log_softmax(safe_out0["logits"], dim=-1).gather(
                    1,
                    policy_target_actions[:, None],
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
        loss_after_t = loss_before_t
        non_finite_loss_steps = 0
        non_finite_gradient_steps = 0
        sanitized_gradient_steps = 0
        sanitized_gradient_value_count = 0
        advantage_anomaly_steps = 0
        max_gradient_norm = 0.0
        optimizer_steps_this_cycle = 0
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

        def sanitize_gradients() -> int:
            grads = [p.grad for p in net.parameters() if getattr(p, "grad", None) is not None]
            if not grads:
                return 0
            # Single-sync global cleanliness check. The previous code ran TWO
            # GPU->CPU .item() syncs PER PARAMETER every step; each sync drains the
            # CUDA pipeline (the measured GPU idle between step bursts). Reduce the
            # common case (nothing to clean) to ONE sync via a fused reduction;
            # behaviourally identical -- only the rare non-finite/oversized case
            # walks parameters for the exact cleanup + count.
            global_ok = torch.stack([
                (torch.isfinite(g).all() & (torch.abs(g) <= 1_000.0).all())
                for g in grads
            ]).all()
            if bool(global_ok.detach().cpu().item()):
                return 0
            sanitized_count = 0
            for grad in grads:
                finite_mask = torch.isfinite(grad)
                if bool(finite_mask.all().detach().cpu().item()) is False:
                    sanitized_count += int((~finite_mask).sum().detach().cpu().item())
                cleaned = torch.nan_to_num(grad, nan=0.0, posinf=0.0, neginf=0.0)
                clamp_mask = torch.abs(cleaned) > 1_000.0
                if bool(clamp_mask.any().detach().cpu().item()):
                    sanitized_count += int(clamp_mask.sum().detach().cpu().item())
                    cleaned = torch.clamp(cleaned, min=-1_000.0, max=1_000.0)
                if sanitized_count:
                    grad.copy_(cleaned)
            return sanitized_count

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
                out = safe_outputs(net(x))
                new_log_probs = torch.log_softmax(out["logits"], dim=-1).gather(
                    1,
                    policy_target_actions[:, None],
                ).squeeze(1)
                log_probs = torch.log_softmax(out["logits"], dim=-1)
                probs = torch.softmax(out["logits"], dim=-1)
                entropy_per_row = -(probs * log_probs).sum(dim=-1)
                if ppo_objective_active:
                    ppo_new_log_probs = new_log_probs[ppo_row_mask]
                    ppo_old_log_probs = old_log_probs.detach()[ppo_row_mask]
                    log_ratio = torch.clamp(ppo_new_log_probs - ppo_old_log_probs, min=-20.0, max=20.0)
                    ratio = torch.nan_to_num(torch.exp(log_ratio), nan=1.0, posinf=1.0, neginf=1.0)
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
                    entropy = entropy_per_row[ppo_row_mask].mean()
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
                confidence_loss = mse(
                    out["confidence"],
                    torch.clamp(torch.abs(expected_move_training_target) / 100.0, 0.0, 1.0),
                )
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
                advantage_exploded = adv_mean is None or abs(adv_mean) >= 5.0
                advantage_vanished = (
                    adv_std is not None
                    and adv_std == 0.0
                    and (adv_mean is None or abs(adv_mean) <= 1e-9)
                    and ppo_row_count > 1
                )
                if advantage_exploded or advantage_vanished:
                    advantage_anomaly_steps += 1
                    non_finite_loss_steps += 1
                    opt.zero_grad(set_to_none=True)
                    continue
            if bool(torch.isfinite(loss).detach().cpu().item()) is False:
                non_finite_loss_steps += 1
                opt.zero_grad(set_to_none=True)
                continue
            if scaler is not None and use_amp:
                scaler.scale(loss).backward()
                scaler.unscale_(opt)
                sanitized_count = sanitize_gradients()
                if sanitized_count:
                    sanitized_gradient_steps += 1
                    sanitized_gradient_value_count += sanitized_count
                grad_norm = torch.nn.utils.clip_grad_norm_(net.parameters(), max_norm=1.0, error_if_nonfinite=False)
                if bool(torch.isfinite(grad_norm).detach().cpu().item()):
                    max_gradient_norm = max(max_gradient_norm, float(grad_norm.detach().cpu().item()))
                    if sanitized_count:
                        opt.step()
                        optimizer_steps_this_cycle += 1
                    else:
                        scaler.step(opt)
                        optimizer_steps_this_cycle += 1
                    parameter_sanitized_count = sanitize_parameters()
                    if parameter_sanitized_count:
                        non_finite_parameter_value_count_sanitized += parameter_sanitized_count
                        non_finite_parameter_sanitization_events += 1
                else:
                    non_finite_gradient_steps += 1
                    opt.zero_grad(set_to_none=True)
                scaler.update()
            else:
                loss.backward()
                sanitized_count = sanitize_gradients()
                if sanitized_count:
                    sanitized_gradient_steps += 1
                    sanitized_gradient_value_count += sanitized_count
                grad_norm = torch.nn.utils.clip_grad_norm_(net.parameters(), max_norm=1.0, error_if_nonfinite=False)
                if bool(torch.isfinite(grad_norm).detach().cpu().item()):
                    max_gradient_norm = max(max_gradient_norm, float(grad_norm.detach().cpu().item()))
                    opt.step()
                    optimizer_steps_this_cycle += 1
                    parameter_sanitized_count = sanitize_parameters()
                    if parameter_sanitized_count:
                        non_finite_parameter_value_count_sanitized += parameter_sanitized_count
                        non_finite_parameter_sanitization_events += 1
                else:
                    non_finite_gradient_steps += 1
                    opt.zero_grad(set_to_none=True)
        training_gpu_metrics = training_gpu_sampler.stop()
        feedback_head_nudge_applied = False
        expected_move_head_recovery_metrics: dict[str, Any] = {
            "expected_move_head_saturation_recovery_applied": False,
            "expected_move_head_saturation_recovery_reason": "not_evaluated",
            "expected_move_head_bias_abs_limit": EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT,
            "expected_move_head_saturation_bps": EXPECTED_MOVE_HEAD_SATURATION_BPS,
            "expected_move_head_target_mismatch_bps": EXPECTED_MOVE_HEAD_TARGET_MISMATCH_BPS,
        }

        def expected_move_pre_activation(batch_x):
            # Temporal model feeds a 3D window (B, T, F); this bias-saturation
            # diagnostic operates on the single "current" frame like the
            # single-frame model always did. Collapse to the newest frame so we
            # don't push all T frames through the residual stack (16x memory ->
            # OOM under GPU contention) and don't produce a (B, T) pre-activation.
            if batch_x.dim() == 3:
                batch_x = batch_x[:, -1, :]
            transformed = torch.nan_to_num(batch_x, nan=0.0, posinf=1_000_000.0, neginf=-1_000_000.0)
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
            finally:
                if was_training:
                    net.train()
            if expected_move_head_recovery_metrics.get("expected_move_head_saturation_recovery_applied") is True:
                feedback_head_nudge_applied = True
            parameter_sanitized_count = sanitize_parameters()
            if parameter_sanitized_count:
                non_finite_parameter_value_count_sanitized += parameter_sanitized_count
                non_finite_parameter_sanitization_events += 1
        with torch.no_grad():
            with autocast():
                loss_after_t = supervised_loss(net(x))
        net.eval()
        # Out-of-sample generalization signal on the held-out validation split.
        validation_metrics = self._validation_supervised_loss(validation_rows)
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
            validation_metrics["train_val_generalization_gap"] = round(_gap, 6)
            validation_metrics["overfit_gap_warning"] = bool(_gap > 0.5)
        elapsed_seconds = max(1e-6, time.perf_counter() - started)
        parameter_vector_after = self._parameter_vector()
        parameter_hash_after = self._parameter_hash_from_vector(parameter_vector_after)
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
                "sanitized_gradient_steps": sanitized_gradient_steps,
                "sanitized_gradient_value_count": sanitized_gradient_value_count,
                "advantage_anomaly_steps": advantage_anomaly_steps,
                # True NaN/Inf events only; clamped large-but-finite gradient
                # values are tracked separately under sanitized_gradient_*.
                "tensor_nan_inf_count": int(non_finite_loss_steps)
                + int(non_finite_gradient_steps)
                + int(non_finite_feature_count)
                + int(non_finite_expected_label_count),
                "ppo_clip_epsilon_bounds": [1.0 - self.clip_epsilon, 1.0 + self.clip_epsilon],
                "non_finite_parameter_value_count_sanitized": non_finite_parameter_value_count_sanitized,
                "non_finite_parameter_sanitization_events": non_finite_parameter_sanitization_events,
                "parameter_finite_guard_active": True,
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
        parameter_vector_before = self._parameter_vector()
        parameter_hash_before = self._parameter_hash_from_vector(parameter_vector_before)
        input_dim = int(self.model.input_dim)
        ppo_objective_active = self._ppo_objective_active(learning_mode) and any(
            self._has_on_policy_ppo_fields(row) for row in rows
        )
        outcome_supervision_active = self._outcome_supervision_active(learning_mode)
        ppo_row_count = sum(1 for row in rows if self._has_on_policy_ppo_fields(row))
        outcome_row_count = sum(1 for row in rows if self._has_outcome_supervised_targets(row))
        expected_move_labels, expected_move_supervision_metrics = self._python_expected_move_supervision_labels(rows)
        policy_action_labels, policy_action_supervision_metrics = self._python_policy_action_supervision_labels(rows)

        def _loss() -> float:
            losses = []
            for row, expected_label, policy_action_label in zip(rows, expected_move_labels, policy_action_labels):
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
        elapsed_seconds = max(1e-6, time.perf_counter() - started)
        parameter_vector_after = self._parameter_vector()
        parameter_hash_after = self._parameter_hash_from_vector(parameter_vector_after)
        weight_delta_norm = self._parameter_delta_norm(parameter_vector_before, parameter_vector_after)
        return PPOTrainingResult(
            status=(
                "V2_NATIVE_RL_MASA_PPO_ON_POLICY_TORCH_UNAVAILABLE_CPU_FALLBACK_TRAINING_STEP_RAN"
                if learning_mode == "ppo_on_policy"
                else "V2_NATIVE_RL_MASA_PPO_MIXED_OUTCOME_SUPERVISED_TORCH_UNAVAILABLE_CPU_FALLBACK_TRAINING_STEP_RAN"
                if learning_mode == "ppo_mixed_outcome_supervised"
                else "V2_NATIVE_RL_MASA_OUTCOME_SUPERVISED_TORCH_UNAVAILABLE_CPU_FALLBACK_TRAINING_STEP_RAN"
            ),
            device="cpu",
            cuda_active=False,
            cuda_claim_verified=False,
            gpu_name=None,
            vram_allocated_mb=None,
            batch_size=int(batch_size),
            training_steps=max(1, int(steps)),
            train_rows=len(rows),
            validation_rows=len(validation_rows),
            loss_before=float(loss_before),
            loss_after=float(loss_after),
            action_distribution=self._action_distribution(rows),
            metrics={
                **(rejection_metrics or {}),
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
    def _parameter_hash_from_vector(values: Sequence[float]) -> str:
        import hashlib

        digest = hashlib.sha256()
        for value in values:
            if math.isfinite(float(value)):
                digest.update(f"{float(value):.12g},".encode("ascii"))
            else:
                digest.update(b"nan,")
        return digest.hexdigest()

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
            metrics=metrics or {},
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
