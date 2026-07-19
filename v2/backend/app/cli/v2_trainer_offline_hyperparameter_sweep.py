"""Offline hyperparameter sweep for the native CUDA MASA/PPO trainer.

Read-only / offline by design: this does NOT run the live prediction loop, does
NOT place any order, and (unless --promote is passed) does NOT write a checkpoint.
It loads one fixed batch of trusted training rows from the replay archive and
trains the *real* V2HybridPPOTrainer under several (learning_rate, entropy,
weight_decay, dropout) configs, then reports which config trains stably to the
lowest out-of-sample validation loss without diverging.

Use it to find a stable hyperparameter set for the trainer (the online model was
observed to diverge under an over-strong entropy bonus). See the runbook:
v2/docs/TRAINER_OFFLINE_RETRAIN_RUNBOOK.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import V2HybridPolicyModel
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (
    PPOTrainingResult,
    V2HybridPPOTrainer,
)

# One config is a dict of the tunable knobs.
DEFAULT_GRID: tuple[dict[str, float], ...] = tuple(
    {
        "learning_rate": lr,
        "entropy_coefficient": ec,
        "supervised_entropy_bonus": 0.0,
        "weight_decay": 0.02,
        "dropout": 0.10,
    }
    for lr in (3e-5, 1e-4, 3e-4)
    for ec in (0.005, 0.01, 0.02)
)
RUNTIME_MODEL_DIR = Path(".local_models/v2_native_rl_masa_ppo")
DEFAULT_STAGE_MODEL_DIR = Path(".local_models/v2_native_rl_masa_ppo_offline_recovery_candidate")


def _parse_utc(value: Any) -> datetime | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        try:
            epoch = float(value)
        except (TypeError, ValueError):
            return None
        if epoch <= 0 or epoch != epoch:
            return None
        if epoch > 10_000_000_000:
            epoch /= 1000.0
        try:
            return datetime.fromtimestamp(epoch, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


_REQUIRED_PIT_CLOCK_FIELDS: tuple[str, ...] = (
    "event_time",
    "ingested_at",
    "generated_at",
    "available_at",
    "feature_cutoff",
    "decision_time",
    "masa_feature_cutoff",
    "ppo_feature_cutoff",
    "ppo_decision_time",
    "execution_time",
    "outcome_available_at",
    "label_available_at",
    "training_observed_at",
    "candle_open_time",
    "candle_close_time",
)

_REQUIRED_PIT_FINALITY_FIELDS: tuple[str, ...] = (
    "candle_closed_confirmed",
    "outcome_finalized",
    "label_finalized",
)

_PIT_CLOCK_ORDER_RULES: tuple[tuple[str, str, str, bool], ...] = (
    ("candle_open_time", "candle_close_time", "CANDLE_WINDOW_NOT_FINAL", True),
    (
        "candle_close_time",
        "feature_cutoff",
        "CANDLE_CLOSE_TIME_AFTER_FEATURE_CUTOFF",
        False,
    ),
    ("event_time", "ingested_at", "EVENT_TIME_AFTER_INGESTED_AT", False),
    ("event_time", "feature_cutoff", "EVENT_TIME_AFTER_FEATURE_CUTOFF", False),
    ("ingested_at", "generated_at", "INGESTED_AT_AFTER_GENERATED_AT", False),
    (
        "feature_cutoff",
        "generated_at",
        "FEATURE_CUTOFF_AFTER_GENERATED_AT",
        False,
    ),
    ("generated_at", "available_at", "GENERATED_AT_AFTER_AVAILABLE_AT", False),
    (
        "feature_cutoff",
        "available_at",
        "FEATURE_CUTOFF_AFTER_AVAILABLE_AT",
        False,
    ),
    (
        "available_at",
        "decision_time",
        "FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME",
        False,
    ),
    (
        "decision_time",
        "ppo_decision_time",
        "DECISION_TIME_AFTER_PPO_DECISION_TIME",
        False,
    ),
    (
        "masa_feature_cutoff",
        "ppo_decision_time",
        "MASA_FEATURE_CUTOFF_AFTER_PPO_DECISION_TIME",
        False,
    ),
    (
        "ppo_feature_cutoff",
        "ppo_decision_time",
        "PPO_FEATURE_CUTOFF_AFTER_PPO_DECISION_TIME",
        False,
    ),
    (
        "ppo_decision_time",
        "execution_time",
        "PPO_DECISION_TIME_AFTER_EXECUTION_TIME",
        False,
    ),
    (
        "execution_time",
        "outcome_available_at",
        "OUTCOME_AVAILABLE_BEFORE_EXECUTION",
        False,
    ),
    (
        "outcome_available_at",
        "label_available_at",
        "LABEL_AVAILABLE_BEFORE_OUTCOME",
        False,
    ),
    (
        "outcome_available_at",
        "training_observed_at",
        "OUTCOME_AVAILABLE_AT_AFTER_TRAINING_OBSERVED_AT",
        False,
    ),
    (
        "label_available_at",
        "training_observed_at",
        "LABEL_AVAILABLE_AT_AFTER_TRAINING_OBSERVED_AT",
        False,
    ),
)


def point_in_time_safety_report(examples: Sequence[Any]) -> dict[str, Any]:
    """Fail-closed replay timing audit for offline tuning inputs.

    The sweep trains on trusted replay/feedback rows, but it is still a
    recovery tool: before spending GPU cycles, verify that row-level timing
    fields do not imply future leakage into the decision window.
    """
    audit_observed_at = datetime.now(UTC)
    violations: list[dict[str, Any]] = []
    missing_trust_row_count = 0
    missing_decision_time_count = 0
    missing_clock_counts = {field: 0 for field in _REQUIRED_PIT_CLOCK_FIELDS}
    invalid_clock_counts = {field: 0 for field in _REQUIRED_PIT_CLOCK_FIELDS}
    missing_finality_counts = {
        field: 0 for field in _REQUIRED_PIT_FINALITY_FIELDS
    }
    checked_rows = 0

    def add_violation(
        *,
        index: int,
        example: Any,
        field: str,
        observed: Any,
        reason: str,
    ) -> None:
        violations.append(
            {
                "row_index": index,
                "symbol": getattr(example, "symbol", None),
                "timeframe": getattr(example, "timeframe", None),
                "field": field,
                "observed": observed,
                "reason": reason,
            }
        )

    for index, example in enumerate(examples):
        row = getattr(example, "trust_row", None)
        if not isinstance(row, dict):
            missing_trust_row_count += 1
            continue
        checked_rows += 1
        clocks: dict[str, datetime] = {}
        for field in _REQUIRED_PIT_CLOCK_FIELDS:
            raw_value = row.get(field)
            if raw_value in (None, ""):
                missing_clock_counts[field] += 1
                if field == "decision_time":
                    missing_decision_time_count += 1
                add_violation(
                    index=index,
                    example=example,
                    field=field,
                    observed=raw_value,
                    reason=f"{field.upper()}_MISSING",
                )
                continue
            parsed = _parse_utc(raw_value)
            if parsed is None:
                invalid_clock_counts[field] += 1
                if field == "decision_time":
                    missing_decision_time_count += 1
                add_violation(
                    index=index,
                    example=example,
                    field=field,
                    observed=str(raw_value),
                    reason=f"{field.upper()}_NOT_TIMEZONE_AWARE_OR_INVALID",
                )
                continue
            clocks[field] = parsed

        row_evaluation_observed_at = row.get("evaluation_observed_at")
        if row_evaluation_observed_at not in (None, ""):
            parsed_evaluation_observed_at = _parse_utc(row_evaluation_observed_at)
            if parsed_evaluation_observed_at is None:
                add_violation(
                    index=index,
                    example=example,
                    field="evaluation_observed_at",
                    observed=str(row_evaluation_observed_at),
                    reason="EVALUATION_OBSERVED_AT_NOT_TIMEZONE_AWARE_OR_INVALID",
                )
            else:
                clocks["evaluation_observed_at"] = parsed_evaluation_observed_at

        for field in _REQUIRED_PIT_FINALITY_FIELDS:
            if row.get(field) is not True:
                missing_finality_counts[field] += 1
                add_violation(
                    index=index,
                    example=example,
                    field=field,
                    observed=row.get(field),
                    reason=f"{field.upper()}_NOT_EXPLICITLY_FINAL",
                )
        if "closed_candle" in row and row.get("closed_candle") is not True:
            add_violation(
                index=index,
                example=example,
                field="closed_candle",
                observed=row.get("closed_candle"),
                reason="CLOSED_CANDLE_EVIDENCE_CONFLICT",
            )

        for left, right, reason, strict in _PIT_CLOCK_ORDER_RULES:
            if left not in clocks or right not in clocks:
                continue
            ordered = (
                clocks[left] < clocks[right]
                if strict
                else clocks[left] <= clocks[right]
            )
            if not ordered:
                add_violation(
                    index=index,
                    example=example,
                    field=left,
                    observed=clocks[left].isoformat(),
                    reason=reason,
                )
        if (
            "training_observed_at" in clocks
            and clocks["training_observed_at"] > audit_observed_at
        ):
            add_violation(
                index=index,
                example=example,
                field="training_observed_at",
                observed=clocks["training_observed_at"].isoformat(),
                reason="TRAINING_OBSERVED_AT_AFTER_EVALUATION_OBSERVED_AT",
            )
        if "evaluation_observed_at" in clocks:
            if clocks["evaluation_observed_at"] > audit_observed_at:
                add_violation(
                    index=index,
                    example=example,
                    field="evaluation_observed_at",
                    observed=clocks["evaluation_observed_at"].isoformat(),
                    reason="ROW_EVALUATION_OBSERVED_AT_AFTER_AUDIT_OBSERVED_AT",
                )
            if (
                "training_observed_at" in clocks
                and clocks["training_observed_at"]
                > clocks["evaluation_observed_at"]
            ):
                add_violation(
                    index=index,
                    example=example,
                    field="training_observed_at",
                    observed=clocks["training_observed_at"].isoformat(),
                    reason="TRAINING_OBSERVED_AT_AFTER_ROW_EVALUATION_OBSERVED_AT",
                )
            for availability_field in (
                "outcome_available_at",
                "label_available_at",
            ):
                if (
                    availability_field in clocks
                    and clocks[availability_field]
                    > clocks["evaluation_observed_at"]
                ):
                    add_violation(
                        index=index,
                        example=example,
                        field=availability_field,
                        observed=clocks[availability_field].isoformat(),
                        reason=(
                            f"{availability_field.upper()}_AFTER_EVALUATION_OBSERVED_AT"
                        ),
                    )
    return {
        "schema_version": "trainer_offline_point_in_time_safety_v2",
        "checked_rows": checked_rows,
        "missing_trust_row_count": missing_trust_row_count,
        "missing_decision_time_count": missing_decision_time_count,
        "required_clock_fields": list(_REQUIRED_PIT_CLOCK_FIELDS),
        "required_finality_fields": list(_REQUIRED_PIT_FINALITY_FIELDS),
        "training_evaluation_observation_cutoff_field": "training_observed_at",
        "evaluation_observed_at": audit_observed_at.isoformat(),
        "missing_clock_counts": missing_clock_counts,
        "invalid_clock_counts": invalid_clock_counts,
        "missing_finality_counts": missing_finality_counts,
        "violation_count": len(violations),
        "violation_reasons": sorted({row["reason"] for row in violations}),
        "violations_sample": violations[:50],
        "passed": (
            missing_trust_row_count == 0
            and not violations
        ),
    }


def _diverged(result: PPOTrainingResult) -> bool:
    lb, la = result.loss_before, result.loss_after
    if lb is None or la is None:
        return True
    # Divergence: post-training loss materially exceeds pre-training loss.
    return la > lb * 1.25 + 1e-6


def _eligible_for_recovery(result: dict[str, Any]) -> bool:
    """A config is usable only if the online validation guard would accept it."""
    return (
        result.get("diverged") is False
        and result.get("validation_supervised_loss") is not None
        and result.get("overfit_gap_warning") is not True
    )


def _sha256_file(path: str | None) -> str | None:
    if not path:
        return None
    source = Path(path)
    if not source.exists() or not source.is_file():
        return None
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _looks_like_runtime_model_dir(path: Path) -> bool:
    try:
        target_resolved = Path(path).expanduser().resolve(strict=False)
        runtime_resolved = RUNTIME_MODEL_DIR.expanduser().resolve(strict=False)
        if target_resolved == runtime_resolved:
            return True
    except Exception:
        pass
    text = Path(path).as_posix().rstrip("/")
    runtime = RUNTIME_MODEL_DIR.as_posix().rstrip("/")
    return text == runtime or text.endswith(f"/{runtime}")


def _train_model_for_config(
    examples: Sequence[Any],
    *,
    config: dict[str, float],
    steps: int,
    batch_size: int,
    validation_fraction: float,
    load_checkpoint: bool,
) -> tuple[V2HybridPolicyModel, dict[str, Any]]:
    input_dim = len(examples[0].tensor.model_vector)
    # Dropout is read from env at model construction; set it for this config.
    prev_dropout = os.environ.get("V2_TRAINER_DROPOUT")
    os.environ["V2_TRAINER_DROPOUT"] = str(config.get("dropout", 0.10))
    try:
        model = V2HybridPolicyModel(input_dim=input_dim)
    finally:
        if prev_dropout is None:
            os.environ.pop("V2_TRAINER_DROPOUT", None)
        else:
            os.environ["V2_TRAINER_DROPOUT"] = prev_dropout
    if load_checkpoint:
        try:
            from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
                V2HybridCheckpointManager,
            )
            from pathlib import Path

            V2HybridCheckpointManager(Path(".local_models/v2_native_rl_masa_ppo")).load_latest_weights(model)
        except Exception:
            pass
    trainer = V2HybridPPOTrainer(
        model=model,
        learning_rate=config["learning_rate"],
        entropy_coefficient=config["entropy_coefficient"],
        supervised_entropy_bonus=config.get("supervised_entropy_bonus", 0.0),
        weight_decay=config.get("weight_decay", 0.02),
    )
    result = trainer.train(
        examples, steps=steps, batch_size=batch_size, validation_fraction=validation_fraction
    )
    m = result.metrics
    return model, {
        "config": config,
        "loss_before": result.loss_before,
        "loss_after": result.loss_after,
        "validation_supervised_loss": m.get("validation_supervised_loss"),
        "train_val_generalization_gap": m.get("train_val_generalization_gap"),
        "overfit_gap_warning": bool(m.get("overfit_gap_warning") is True),
        "ppo_entropy": m.get("ppo_entropy"),
        "diverged": _diverged(result),
        "train_rows": result.train_rows,
        "validation_rows": result.validation_rows,
    }


def _train_one_config(
    examples: Sequence[Any],
    *,
    config: dict[str, float],
    steps: int,
    batch_size: int,
    validation_fraction: float,
    load_checkpoint: bool,
) -> dict[str, Any]:
    _, result = _train_model_for_config(
        examples,
        config=config,
        steps=steps,
        batch_size=batch_size,
        validation_fraction=validation_fraction,
        load_checkpoint=load_checkpoint,
    )
    return result


def stage_recovery_checkpoint(
    examples: Sequence[Any],
    *,
    config: dict[str, float],
    stage_model_dir: Path = DEFAULT_STAGE_MODEL_DIR,
    steps: int = 200,
    batch_size: int = 4096,
    validation_fraction: float = 0.2,
    load_checkpoint: bool = False,
) -> dict[str, Any]:
    """Train one promotable config and write it to an isolated candidate dir.

    This is intentionally not an install/promote path: it writes a local NPZ
    checkpoint under a staging directory only after the retrained candidate still
    satisfies the same recovery eligibility used by the sweep ranking.
    """
    if not examples:
        raise ValueError("offline recovery staging requires at least one training example")
    point_in_time_safety = point_in_time_safety_report(examples)
    if not point_in_time_safety["passed"]:
        raise ValueError(
            "offline recovery staging blocked by point-in-time safety violations: "
            + json.dumps(point_in_time_safety, default=str)
        )
    stage_dir = Path(stage_model_dir)
    if _looks_like_runtime_model_dir(stage_dir):
        raise ValueError("refusing to stage offline recovery into the active runtime model directory")

    model, candidate = _train_model_for_config(
        examples,
        config=dict(config),
        steps=steps,
        batch_size=batch_size,
        validation_fraction=validation_fraction,
        load_checkpoint=load_checkpoint,
    )
    if not _eligible_for_recovery(candidate):
        return {
            "schema_version": "trainer_offline_recovery_checkpoint_stage_v1",
            "status": "REJECTED_NOT_PROMOTABLE",
            "stage_model_dir": str(stage_dir),
            "staged_checkpoint_written": False,
            "runtime_checkpoint_written": False,
            "writes_current_checkpoint": False,
            "candidate": candidate,
            "point_in_time_safety": point_in_time_safety,
            "places_real_order": False,
            "test_order_submitted": False,
            "order_submitted": False,
            "leverage_mutated": False,
            "margin_mutated": False,
            "routes_to_live": False,
        }

    manager = V2HybridCheckpointManager(stage_dir)
    input_dim = len(examples[0].tensor.model_vector)
    manifest = manager.write_checkpoint(
        model=model,
        input_dim=input_dim,
        device=model.device,
        cuda_active=model.cuda_active,
        write_weight_blob=True,
    )
    reload_status = manager.load_latest_weights(V2HybridPolicyModel(input_dim=input_dim))
    checkpoint_hash = _sha256_file(manifest.weight_file_path)
    reload_verified = bool(
        reload_status.get("latest_checkpoint_loadable")
        and reload_status.get("model_state_restored")
        and reload_status.get("safe_weight_format")
    )
    return {
        "schema_version": "trainer_offline_recovery_checkpoint_stage_v1",
        "status": "STAGED_PROMOTABLE_CANDIDATE" if reload_verified else "STAGED_RELOAD_FAILED",
        "stage_model_dir": str(stage_dir),
        "staged_checkpoint_written": bool(manifest.weight_blob_written),
        "runtime_checkpoint_written": False,
        "writes_current_checkpoint": False,
        "operator_install_required": True,
        "candidate": candidate,
        "checkpoint_id": manifest.checkpoint_id,
        "checkpoint_manifest_path": manifest.path,
        "checkpoint_weight_file_path": manifest.weight_file_path,
        "checkpoint_weight_file_format": manifest.weight_file_format,
        "checkpoint_weight_file_size_bytes": manifest.weight_file_size_bytes,
        "checkpoint_hash": checkpoint_hash,
        "checkpoint_reload_verified": reload_verified,
        "checkpoint_reload_status": reload_status,
        "point_in_time_safety": point_in_time_safety,
        "places_real_order": False,
        "test_order_submitted": False,
        "order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "routes_to_live": False,
    }


def run_hyperparameter_sweep(
    examples: Sequence[Any],
    *,
    grid: Sequence[dict[str, float]] = DEFAULT_GRID,
    steps: int = 200,
    batch_size: int = 4096,
    validation_fraction: float = 0.2,
    load_checkpoint: bool = False,
) -> dict[str, Any]:
    """Train the real trainer under each config; rank by stability + val loss."""
    if not examples:
        raise ValueError("offline sweep requires at least one training example")
    point_in_time_safety = point_in_time_safety_report(examples)
    if not point_in_time_safety["passed"]:
        raise ValueError(
            "offline sweep blocked by point-in-time safety violations: "
            + json.dumps(point_in_time_safety, default=str)
        )
    results: list[dict[str, Any]] = []
    for config in grid:
        results.append(
            _train_one_config(
                examples,
                config=config,
                steps=steps,
                batch_size=batch_size,
                validation_fraction=validation_fraction,
                load_checkpoint=load_checkpoint,
            )
        )

    def _score(r: dict[str, Any]) -> tuple[int, float]:
        vl = r["validation_supervised_loss"]
        # Prefer configs the online validation guard could actually promote:
        # non-diverged, validation-present, and no train/validation overfit gap.
        if not _eligible_for_recovery(r):
            return (1, float("inf"))
        return (0, float(vl))

    results_sorted = sorted(results, key=_score)
    eligible = [r for r in results_sorted if _eligible_for_recovery(r)]
    non_diverged = [
        r
        for r in results_sorted
        if not r["diverged"] and r["validation_supervised_loss"] is not None
    ]
    overfit_rejected = [
        r
        for r in non_diverged
        if r.get("overfit_gap_warning") is True
    ]
    return {
        "schema_version": "trainer_offline_hyperparameter_sweep_v1",
        "config_count": len(results),
        "stable_config_count": len(eligible),
        "promotable_config_count": len(eligible),
        "non_diverged_config_count": len(non_diverged),
        "overfit_rejected_config_count": len(overfit_rejected),
        "best": eligible[0] if eligible else None,
        "results": results_sorted,
        "point_in_time_safety": point_in_time_safety,
        "places_real_order": False,
        "test_order_submitted": False,
        "order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "routes_to_live": False,
        "writes_checkpoint": False,
        "offline_only": True,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbols", default=None,
                   help="comma-separated symbols; default = dynamic universe resolver (adaptive)")
    p.add_argument("--smoke-test", action="store_true",
                   help="use the BTC/ETH/SOL smoke-test set (test only)")
    p.add_argument("--timeframes", default="1m,5m,15m,1h")
    p.add_argument("--limit", type=int, default=4096, help="max training rows to load")
    p.add_argument("--steps", type=int, default=200)
    p.add_argument("--batch-size", type=int, default=4096)
    p.add_argument("--validation-fraction", type=float, default=0.2)
    p.add_argument("--from-checkpoint", action="store_true", help="start each config from the current checkpoint")
    p.add_argument("--output", default=None, help="write the sweep JSON here")
    p.add_argument("--promote", action="store_true", help="(NOT IMPLEMENTED HERE) reserved; sweep is report-only")
    p.add_argument(
        "--stage-checkpoint",
        action="store_true",
        help="write the best promotable config to an isolated offline recovery candidate directory",
    )
    p.add_argument(
        "--stage-model-dir",
        default=str(DEFAULT_STAGE_MODEL_DIR),
        help="candidate checkpoint directory; active runtime model dir is refused",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.promote:
        print(
            json.dumps(
                {
                    "error": "promote is intentionally not implemented by the offline sweep",
                    "offline_only": True,
                    "writes_checkpoint": False,
                    "places_real_order": False,
                    "routes_to_live": False,
                }
            )
        )
        return 3
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
        V2HybridTrainerDataLoader,
    )
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols  # noqa: PLC0415

    loader = V2HybridTrainerDataLoader()
    examples = loader.load_training_examples(
        symbols=resolve_symbols(explicit=args.symbols, smoke_test=args.smoke_test),
        timeframes=[t.strip().lower() for t in args.timeframes.split(",") if t.strip()],
        limit=args.limit,
        trusted_only=True,
        closed_trade_only=True,
    )
    if not examples:
        print(json.dumps({"error": "no training examples loaded from replay", "offline_only": True}))
        return 2
    report = run_hyperparameter_sweep(
        examples,
        steps=args.steps,
        batch_size=args.batch_size,
        validation_fraction=args.validation_fraction,
        load_checkpoint=args.from_checkpoint,
    )
    report["examples_loaded"] = len(examples)
    exit_code = 0
    if args.stage_checkpoint:
        best = report.get("best")
        if not isinstance(best, dict) or not isinstance(best.get("config"), dict):
            report["staged_checkpoint"] = {
                "schema_version": "trainer_offline_recovery_checkpoint_stage_v1",
                "status": "NO_PROMOTABLE_CONFIG",
                "staged_checkpoint_written": False,
                "runtime_checkpoint_written": False,
                "writes_current_checkpoint": False,
                "operator_install_required": True,
                "places_real_order": False,
                "test_order_submitted": False,
                "order_submitted": False,
                "leverage_mutated": False,
                "margin_mutated": False,
                "routes_to_live": False,
            }
            exit_code = 4
        else:
            try:
                report["staged_checkpoint"] = stage_recovery_checkpoint(
                    examples,
                    config=best["config"],
                    stage_model_dir=Path(args.stage_model_dir),
                    steps=args.steps,
                    batch_size=args.batch_size,
                    validation_fraction=args.validation_fraction,
                    load_checkpoint=args.from_checkpoint,
                )
                if report["staged_checkpoint"].get("status") != "STAGED_PROMOTABLE_CANDIDATE":
                    exit_code = 4
            except Exception as exc:  # noqa: BLE001
                report["staged_checkpoint"] = {
                    "schema_version": "trainer_offline_recovery_checkpoint_stage_v1",
                    "status": "STAGE_FAILED",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "staged_checkpoint_written": False,
                    "runtime_checkpoint_written": False,
                    "writes_current_checkpoint": False,
                    "operator_install_required": True,
                    "places_real_order": False,
                    "test_order_submitted": False,
                    "order_submitted": False,
                    "leverage_mutated": False,
                    "margin_mutated": False,
                    "routes_to_live": False,
                }
                exit_code = 4
    text = json.dumps(report, indent=2, default=str)
    if args.output:
        with open(args.output, "w") as fh:
            fh.write(text)
    print(text)
    best = report.get("best")
    if best:
        print(
            "BEST_STABLE_CONFIG:",
            json.dumps(best["config"]),
            "| val_loss:", best["validation_supervised_loss"],
            "| gap:", best["train_val_generalization_gap"],
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
