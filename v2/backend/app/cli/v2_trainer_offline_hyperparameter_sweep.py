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
import json
import os
from datetime import datetime, timezone
from typing import Any, Sequence

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import V2HybridPolicyModel
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (
    V2HybridPPOTrainer,
    PPOTrainingResult,
)

# One config is a dict of the tunable knobs.
DEFAULT_GRID: tuple[dict[str, float], ...] = tuple(
    {"learning_rate": lr, "entropy_coefficient": ec, "supervised_entropy_bonus": 0.0, "weight_decay": 0.02, "dropout": 0.10}
    for lr in (3e-5, 1e-4, 3e-4)
    for ec in (0.005, 0.01, 0.02)
)


def _parse_utc(value: Any) -> datetime | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            epoch = float(value)
        except (TypeError, ValueError):
            return None
        if epoch <= 0 or epoch != epoch:
            return None
        if epoch > 10_000_000_000:
            epoch /= 1000.0
        try:
            return datetime.fromtimestamp(epoch, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _first_time(row: dict[str, Any], *keys: str) -> datetime | None:
    for key in keys:
        parsed = _parse_utc(row.get(key))
        if parsed is not None:
            return parsed
    return None


def point_in_time_safety_report(examples: Sequence[Any]) -> dict[str, Any]:
    """Fail-closed replay timing audit for offline tuning inputs.

    The sweep trains on trusted replay/feedback rows, but it is still a
    recovery tool: before spending GPU cycles, verify that row-level timing
    fields do not imply future leakage into the decision window.
    """
    violations: list[dict[str, Any]] = []
    missing_trust_row_count = 0
    missing_decision_time_count = 0
    checked_rows = 0
    for index, example in enumerate(examples):
        row = getattr(example, "trust_row", None)
        if not isinstance(row, dict):
            missing_trust_row_count += 1
            continue
        decision_time = _first_time(
            row,
            "decision_time",
            "decision_time_est",
            "decision_cutoff",
            "decision_cutoff_time_est",
        )
        if decision_time is None:
            missing_decision_time_count += 1
            continue
        checked_rows += 1
        for field in (
            "available_at",
            "feature_cutoff",
            "source_available_time",
            "masa_feature_cutoff",
            "ppo_feature_cutoff",
        ):
            observed = _parse_utc(row.get(field))
            if observed is not None and observed > decision_time:
                violations.append(
                    {
                        "row_index": index,
                        "symbol": getattr(example, "symbol", None),
                        "timeframe": getattr(example, "timeframe", None),
                        "field": field,
                        "observed": observed.isoformat(),
                        "decision_time": decision_time.isoformat(),
                        "reason": f"{field}_AFTER_DECISION_TIME",
                    }
                )
        if row.get("candle_closed_confirmed") is False or row.get("closed_candle") is False:
            violations.append(
                {
                    "row_index": index,
                    "symbol": getattr(example, "symbol", None),
                    "timeframe": getattr(example, "timeframe", None),
                    "field": "candle_closed_confirmed",
                    "observed": False,
                    "decision_time": decision_time.isoformat(),
                    "reason": "UNFINISHED_CANDLE_USED_AS_FINAL",
                }
            )
    return {
        "schema_version": "trainer_offline_point_in_time_safety_v1",
        "checked_rows": checked_rows,
        "missing_trust_row_count": missing_trust_row_count,
        "missing_decision_time_count": missing_decision_time_count,
        "violation_count": len(violations),
        "violations_sample": violations[:10],
        "passed": (
            missing_trust_row_count == 0
            and missing_decision_time_count == 0
            and not violations
        ),
    }


def _diverged(result: PPOTrainingResult) -> bool:
    lb, la = result.loss_before, result.loss_after
    if lb is None or la is None:
        return True
    # Divergence: post-training loss materially exceeds pre-training loss.
    return la > lb * 1.25 + 1e-6


def _train_one_config(
    examples: Sequence[Any],
    *,
    config: dict[str, float],
    steps: int,
    batch_size: int,
    validation_fraction: float,
    load_checkpoint: bool,
) -> dict[str, Any]:
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
    return {
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
        # Prefer: not diverged, then lowest validation loss.
        if r["diverged"] or vl is None:
            return (1, float("inf"))
        return (0, float(vl))

    results_sorted = sorted(results, key=_score)
    stable = [r for r in results_sorted if not r["diverged"] and r["validation_supervised_loss"] is not None]
    return {
        "schema_version": "trainer_offline_hyperparameter_sweep_v1",
        "config_count": len(results),
        "stable_config_count": len(stable),
        "best": stable[0] if stable else None,
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
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT")
    p.add_argument("--timeframes", default="1m,5m,15m,1h")
    p.add_argument("--limit", type=int, default=4096, help="max training rows to load")
    p.add_argument("--steps", type=int, default=200)
    p.add_argument("--batch-size", type=int, default=4096)
    p.add_argument("--validation-fraction", type=float, default=0.2)
    p.add_argument("--from-checkpoint", action="store_true", help="start each config from the current checkpoint")
    p.add_argument("--output", default=None, help="write the sweep JSON here")
    p.add_argument("--promote", action="store_true", help="(NOT IMPLEMENTED HERE) reserved; sweep is report-only")
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

    loader = V2HybridTrainerDataLoader()
    examples = loader.load_training_examples(
        symbols=[s.strip().upper() for s in args.symbols.split(",") if s.strip()],
        timeframes=[t.strip().lower() for t in args.timeframes.split(",") if t.strip()],
        limit=args.limit,
        trusted_only=True,
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
