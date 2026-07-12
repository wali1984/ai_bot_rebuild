"""Offline, GPU-saturating batch trainer for the native CUDA MASA/PPO model.

Purpose
-------
The online streaming loop spends ~60s/cycle *building* 16k examples on the CPU
and only ~17s training, so the RTX 5080 sits at <10% utilisation. This tool
decouples the two: it builds a large trusted-example set from the replay archive
**once**, caches it to disk, then runs many GPU gradient steps at a large batch
size so the GPU actually saturates. It measures GPU utilisation and throughput so
the speed-up is *verified*, not assumed.

Safety / boundaries
--------------------
- Offline and report-only by design. It does NOT run the live prediction loop,
  does NOT place any order, does NOT change leverage/margin, and does NOT touch
  the LIVE checkpoint directory. The exchange gate stays ``blocked_human_only``.
- ``--save-offline DIR`` writes trained weights to a NON-LIVE directory only
  (default ``.local_models/v2_native_rl_masa_ppo_offline``). It never writes the
  live path (``.local_models/v2_native_rl_masa_ppo``), so the running trainer is
  never mutated. Promotion to live remains an explicit, separate operator step.
- Reuses the REAL ``V2HybridTrainerDataLoader`` + ``V2HybridPPOTrainer`` so the
  learning transfers directly to the online loop.

See also: v2/docs/TRAINER_OFFLINE_RETRAIN_RUNBOOK.md
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import threading
import time
from pathlib import Path
from typing import Any, Sequence

# Reuse the point-in-time leakage audit + safety helpers from the sweep tool so
# the two offline trainers share one fail-closed timing contract.
from v2.backend.app.cli.v2_trainer_offline_hyperparameter_sweep import (
    point_in_time_safety_report,
)

LIVE_CHECKPOINT_DIR = ".local_models/v2_native_rl_masa_ppo"
DEFAULT_OFFLINE_DIR = ".local_models/v2_native_rl_masa_ppo_offline"
DEFAULT_CACHE_PATH = "claude_worklog/trainer_atlas/offline_batch_example_cache.pkl"


# ─────────────────────────────── GPU sampler ────────────────────────────────


class GpuUtilizationSampler:
    """Background sampler for GPU utilisation/VRAM via nvidia-smi.

    Read-only; if nvidia-smi is unavailable the samples are simply empty and the
    report notes that GPU telemetry was unavailable (training still runs).
    """

    def __init__(self, interval_s: float = 0.5) -> None:
        self.interval_s = max(0.1, float(interval_s))
        self._util: list[float] = []
        self._vram_mb: list[float] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._available = True

    def _sample_once(self) -> tuple[float, float] | None:
        import subprocess  # noqa: PLC0415 - local, read-only telemetry

        try:
            out = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            self._available = False
            return None
        line = (out.stdout or "").strip().splitlines()
        if not line:
            return None
        try:
            util_s, vram_s = line[0].split(",")
            return float(util_s.strip()), float(vram_s.strip())
        except (ValueError, IndexError):
            return None

    def _run(self) -> None:
        while not self._stop.is_set():
            sample = self._sample_once()
            if sample is not None:
                self._util.append(sample[0])
                self._vram_mb.append(sample[1])
            if not self._available:
                return
            self._stop.wait(self.interval_s)

    def __enter__(self) -> "GpuUtilizationSampler":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    def report(self) -> dict[str, Any]:
        if not self._util:
            return {
                "gpu_telemetry_available": bool(self._available),
                "samples": 0,
                "gpu_utilization_mean_pct": None,
                "gpu_utilization_max_pct": None,
                "vram_used_max_mb": None,
            }
        return {
            "gpu_telemetry_available": True,
            "samples": len(self._util),
            "gpu_utilization_mean_pct": round(sum(self._util) / len(self._util), 2),
            "gpu_utilization_max_pct": round(max(self._util), 2),
            "vram_used_max_mb": round(max(self._vram_mb), 1) if self._vram_mb else None,
        }


# ─────────────────────────────── cache layer ────────────────────────────────


def build_independent_archive_view(real_root: Path, view_root: Path) -> Path:
    """Create a temp archive view that symlinks DATA but keeps its OWN cursors.

    ``load_trusted_replay_examples`` persists a replay cursor that the LIVE
    trainer also consumes; reading through the real root would advance that
    cursor and starve the running loop. This view symlinks the read-only data
    (blobs/index/manifest) into a fresh directory and deliberately omits the
    ``*_cursor.json`` files, so the offline loader starts at offset 0 and writes
    its cursor into the throwaway view — the live cursor is never touched.
    """
    view_root.mkdir(parents=True, exist_ok=True)
    for entry in real_root.iterdir():
        if entry.name.endswith("_cursor.json"):
            continue  # keep offline cursor state isolated from the live loop
        link = view_root / entry.name
        if link.exists() or link.is_symlink():
            continue
        link.symlink_to(entry.resolve())
    return view_root


def load_or_build_examples(
    *,
    symbols: Sequence[str],
    timeframes: Sequence[str],
    limit: int,
    cache_path: str | None,
    rebuild_cache: bool,
) -> tuple[list[Any], dict[str, Any]]:
    """Load trusted examples, using a pickle cache to skip the slow archive build.

    Returns ``(examples, load_meta)``. The cache stores the actual
    ``TrainingExample`` objects so subsequent runs pay ~0s instead of the ~60s
    per-16k-rows archive/feature build the online loop pays every cycle.

    Reads go through an independent archive view (see
    ``build_independent_archive_view``) so the live trainer's replay cursor is
    never advanced.
    """
    meta: dict[str, Any] = {"cache_path": cache_path, "cache_hit": False}
    if cache_path and not rebuild_cache and Path(cache_path).exists():
        started = time.perf_counter()
        with open(cache_path, "rb") as fh:
            examples = pickle.load(fh)
        meta["cache_hit"] = True
        meta["load_seconds"] = round(time.perf_counter() - started, 3)
        meta["examples"] = len(examples)
        return examples, meta

    import tempfile  # noqa: PLC0415
    from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (  # noqa: PLC0415
        default_archive_root,
    )
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (  # noqa: PLC0415
        V2HybridTrainerDataLoader,
    )

    real_root = default_archive_root()
    view_root = Path(tempfile.mkdtemp(prefix="v2_offline_archive_view_"))
    build_independent_archive_view(real_root, view_root)
    meta["archive_view_root"] = str(view_root)
    meta["live_cursor_untouched"] = True
    loader = V2HybridTrainerDataLoader(trusted_replay_archive_root=view_root)

    started = time.perf_counter()
    examples: list[Any] = []
    # Highest-quality supervised rows first: real closed-trade outcomes.
    try:
        examples.extend(loader.load_training_examples(
            symbols=[s.strip().upper() for s in symbols if s.strip()],
            timeframes=[t.strip().lower() for t in timeframes if t.strip()],
            limit=limit,
            trusted_only=True,
            closed_trade_only=True,
        ))
    except Exception as exc:  # pragma: no cover - closed-trade lane is best-effort
        meta["closed_trade_lane_error"] = str(exc)
    # Bulk historical archive rows via the isolated cursor (repeated chunks).
    stagnation = 0
    while len(examples) < limit and stagnation < 3:
        before = len(examples)
        chunk = loader.load_trusted_replay_examples(limit=limit - len(examples))
        examples.extend(chunk)
        if len(examples) <= before or not chunk:
            stagnation += 1
        else:
            stagnation = 0
    meta["load_seconds"] = round(time.perf_counter() - started, 3)
    meta["examples"] = len(examples)
    if cache_path and examples:
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "wb") as fh:
            pickle.dump(examples, fh, protocol=pickle.HIGHEST_PROTOCOL)
        meta["cache_written"] = True
    return examples, meta


# ─────────────────────────────── training ───────────────────────────────────


def run_batch_training(
    examples: Sequence[Any],
    *,
    epochs: int,
    steps_per_epoch: int,
    batch_size: int,
    learning_rate: float,
    entropy_coefficient: float,
    weight_decay: float,
    dropout: float,
    validation_fraction: float,
    from_checkpoint: bool,
    gpu_sample_interval_s: float = 0.5,
) -> dict[str, Any]:
    """Run many GPU gradient steps on the real trainer; verify GPU saturation.

    Fail-closed on point-in-time leakage before spending GPU cycles.
    """
    if not examples:
        raise ValueError("offline batch training requires at least one example")
    pit = point_in_time_safety_report(examples)
    if not pit["passed"]:
        raise ValueError(
            "offline batch training blocked by point-in-time safety violations: "
            + json.dumps(pit, default=str)
        )

    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (  # noqa: PLC0415
        V2HybridPolicyModel,
    )
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (  # noqa: PLC0415
        V2HybridPPOTrainer,
    )

    input_dim = len(examples[0].tensor.model_vector)
    prev_dropout = os.environ.get("V2_TRAINER_DROPOUT")
    os.environ["V2_TRAINER_DROPOUT"] = str(dropout)
    try:
        model = V2HybridPolicyModel(input_dim=input_dim)
    finally:
        if prev_dropout is None:
            os.environ.pop("V2_TRAINER_DROPOUT", None)
        else:
            os.environ["V2_TRAINER_DROPOUT"] = prev_dropout

    if from_checkpoint:
        try:
            from pathlib import Path as _P  # noqa: PLC0415
            from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (  # noqa: PLC0415
                V2HybridCheckpointManager,
            )

            V2HybridCheckpointManager(_P(LIVE_CHECKPOINT_DIR)).load_latest_weights(model)
        except Exception:  # pragma: no cover - warm start is best-effort
            pass

    trainer = V2HybridPPOTrainer(
        model=model,
        learning_rate=learning_rate,
        entropy_coefficient=entropy_coefficient,
        supervised_entropy_bonus=0.0,
        weight_decay=weight_decay,
    )

    epoch_reports: list[dict[str, Any]] = []
    total_steps = 0
    loss_first: float | None = None
    loss_last: float | None = None
    wall_started = time.perf_counter()
    with GpuUtilizationSampler(interval_s=gpu_sample_interval_s) as sampler:
        for epoch in range(max(1, int(epochs))):
            result = trainer.train(
                examples,
                steps=steps_per_epoch,
                batch_size=batch_size,
                validation_fraction=validation_fraction,
            )
            total_steps += int(steps_per_epoch)
            if loss_first is None:
                loss_first = result.loss_before
            loss_last = result.loss_after
            epoch_reports.append(
                {
                    "epoch": epoch,
                    "loss_before": result.loss_before,
                    "loss_after": result.loss_after,
                    "validation_supervised_loss": result.metrics.get("validation_supervised_loss"),
                    "train_val_generalization_gap": result.metrics.get("train_val_generalization_gap"),
                    "ppo_entropy": result.metrics.get("ppo_entropy"),
                    "learning_mode": result.metrics.get("learning_mode"),
                }
            )
        gpu = sampler.report()
    wall_seconds = max(1e-6, time.perf_counter() - wall_started)

    rows_processed = int(len(examples)) * total_steps
    return {
        "schema_version": "trainer_offline_batch_train_v1",
        "examples": len(examples),
        "epochs": int(max(1, epochs)),
        "steps_per_epoch": int(steps_per_epoch),
        "batch_size": int(batch_size),
        "total_gradient_steps": total_steps,
        "wall_seconds": round(wall_seconds, 3),
        "gradient_steps_per_second": round(total_steps / wall_seconds, 3),
        "rows_processed": rows_processed,
        "rows_per_second": round(rows_processed / wall_seconds, 1),
        "loss_first": loss_first,
        "loss_last": loss_last,
        "loss_improved": (loss_first is not None and loss_last is not None and loss_last < loss_first),
        "gpu": gpu,
        "epoch_reports": epoch_reports,
        "point_in_time_safety": pit,
        "trained_model": model,
        # explicit safety posture
        "offline_only": True,
        "writes_live_checkpoint": False,
        "places_real_order": False,
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "routes_to_live": False,
        "live_gate": "blocked_human_only",
    }


def save_offline_weights(model: Any, offline_dir: str) -> dict[str, Any]:
    """Persist trained weights to a NON-LIVE directory only.

    Refuses to write anywhere under the live checkpoint directory so the running
    trainer can never be mutated by this tool.
    """
    resolved = Path(offline_dir).resolve()
    live = Path(LIVE_CHECKPOINT_DIR).resolve()
    if resolved == live or live in resolved.parents or resolved in live.parents:
        raise ValueError(
            f"refusing to save into or around the live checkpoint dir ({LIVE_CHECKPOINT_DIR}); "
            "offline batch trainer must never mutate the running trainer"
        )
    resolved.mkdir(parents=True, exist_ok=True)
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (  # noqa: PLC0415
        V2HybridCheckpointManager,
    )

    try:
        import torch  # noqa: PLC0415

        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        cuda_active = torch.cuda.is_available()
    except Exception:  # pragma: no cover
        device, cuda_active = "cpu", False

    manager = V2HybridCheckpointManager(resolved)
    manifest = manager.write_checkpoint(
        model=model,
        input_dim=int(model.input_dim),
        device=device,
        cuda_active=cuda_active,
        write_weight_blob=True,
    )
    return {
        "offline_dir": str(resolved),
        "is_live_dir": False,
        "saved": True,
        "checkpoint_id": getattr(manifest, "checkpoint_id", None) or (manifest.get("checkpoint_id") if isinstance(manifest, dict) else None),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT")
    p.add_argument("--timeframes", default="1m,5m,15m,1h")
    p.add_argument("--limit", type=int, default=65536, help="max trusted rows to load into the cache")
    p.add_argument("--epochs", type=int, default=20)
    p.add_argument("--steps-per-epoch", type=int, default=50)
    p.add_argument("--batch-size", type=int, default=8192)
    p.add_argument("--learning-rate", type=float, default=1e-4)
    p.add_argument("--entropy-coefficient", type=float, default=0.01)
    p.add_argument("--weight-decay", type=float, default=0.02)
    p.add_argument("--dropout", type=float, default=0.10)
    p.add_argument("--validation-fraction", type=float, default=0.2)
    p.add_argument("--from-checkpoint", action="store_true", help="warm-start from the current LIVE checkpoint (read-only)")
    p.add_argument("--cache-path", default=DEFAULT_CACHE_PATH)
    p.add_argument("--no-cache", action="store_true", help="do not read/write the example cache")
    p.add_argument("--rebuild-cache", action="store_true", help="ignore any existing cache and rebuild it")
    p.add_argument("--save-offline", nargs="?", const=DEFAULT_OFFLINE_DIR, default=None,
                   help="save trained weights to a NON-LIVE dir (never the live checkpoint dir)")
    p.add_argument("--output", default=None, help="write the report JSON here")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cache_path = None if args.no_cache else args.cache_path
    examples, load_meta = load_or_build_examples(
        symbols=args.symbols.split(","),
        timeframes=args.timeframes.split(","),
        limit=args.limit,
        cache_path=cache_path,
        rebuild_cache=args.rebuild_cache,
    )
    if not examples:
        print(json.dumps({"error": "no trusted training examples loaded", "offline_only": True}))
        return 2

    report = run_batch_training(
        examples,
        epochs=args.epochs,
        steps_per_epoch=args.steps_per_epoch,
        batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        entropy_coefficient=args.entropy_coefficient,
        weight_decay=args.weight_decay,
        dropout=args.dropout,
        validation_fraction=args.validation_fraction,
        from_checkpoint=args.from_checkpoint,
    )
    model = report.pop("trained_model", None)
    report["load"] = load_meta
    if args.save_offline and model is not None:
        report["save"] = save_offline_weights(model, args.save_offline)

    text = json.dumps(report, indent=2, default=str)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as fh:
            fh.write(text)
    print(text)
    gpu = report.get("gpu", {})
    print(
        "OFFLINE_BATCH_TRAIN:",
        f"examples={report['examples']}",
        f"steps={report['total_gradient_steps']}",
        f"rows/s={report['rows_per_second']}",
        f"gpu_util_mean={gpu.get('gpu_utilization_mean_pct')}%",
        f"gpu_util_max={gpu.get('gpu_utilization_max_pct')}%",
        f"loss {report['loss_first']} -> {report['loss_last']}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
