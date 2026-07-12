"""Scheduled offline historical pretrain + out-of-sample-gated H2L promotion.

Purpose (the GPU-utilisation answer): the online loop is data-build-bound and
does NOT need to saturate the GPU. The heavy GPU work belongs in periodic OFFLINE
historical pretrains (98% GPU, ~46k rows/s on the archive) whose result is only
promoted to the online warm start when it beats the current checkpoint OUT OF
SAMPLE. Run this on a timer to keep the brain improving with the GPU fully used,
without touching the online resident loop.

Flow (all paper/shadow, live gate stays blocked_human_only):
1. Load a disjoint split from the archive: a training PREFIX + a held-out SUFFIX.
2. Pretrain the real V2HybridPPOTrainer on the PREFIX (early-stop on best val),
   at the live architecture (hidden/residual from env), save to the offline dir.
3. Head-to-head: score offline vs current live checkpoint on the DISJOINT held-out
   suffix (out-of-sample). Refuse promotion unless offline generalises better.
4. --auto-promote (default OFF): back up the live dir + promote if it won.
   --auto-restart (default OFF): restart the trainer so it loads the promotion.
   Default is evaluate-and-publish only (operator decides).
5. Publish status to Redis + a worklog file.

Guardrails honoured: no venv mutation (core torch only), env-gated, out-of-sample
promotion only, never loosens a gate, no order/leverage/margin, stays inside
native_trainer + cli/v2_trainer_offline_* surfaces.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.cli.v2_trainer_offline_batch_train import (
    DEFAULT_OFFLINE_DIR,
    LIVE_CHECKPOINT_DIR,
    run_batch_training,
    save_offline_weights,
)
from v2.backend.app.cli.v2_trainer_h2l_promote import load_h2l_heldout_examples, run_h2l

STATUS_REDIS_KEY = "v2:trainer:scheduled_pretrain:status"
TRAINER_SERVICE = "ai-bot-v2-native-cuda-trainer-persistent.service"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _publish(status: dict[str, Any]) -> None:
    try:
        from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.safety import V2OnlyJsonIO  # noqa: PLC0415
        from v2.backend.app.services.native_trainer.persistent_cuda_trainer_runtime import (  # noqa: PLC0415
            connect_redis,
        )

        V2OnlyJsonIO(client=connect_redis()).set_json(STATUS_REDIS_KEY, status)
    except Exception:  # pragma: no cover - publish is best-effort telemetry
        pass


def run_scheduled_pretrain(
    *,
    symbols: list[str],
    timeframes: list[str],
    train_rows: int,
    heldout_rows: int,
    epochs: int,
    steps_per_epoch: int,
    batch_size: int,
    early_stop_patience: int,
    min_epochs: int,
    min_improvement: float,
    offline_dir: str,
    live_dir: str,
    cache_path: str,
    auto_promote: bool,
    auto_restart: bool,
) -> dict[str, Any]:
    started = time.time()
    # Disjoint split: PREFIX (train_rows) trains the model; SUFFIX (heldout_rows)
    # scores it out-of-sample. The offline pretrain must never see the held-out.
    heldout, training_prefix, split_meta = load_h2l_heldout_examples(
        symbols=symbols,
        timeframes=timeframes,
        limit=heldout_rows,
        heldout_offset=train_rows,
        cache_path=cache_path,
        rebuild_cache=False,
    )
    status: dict[str, Any] = {
        "schema_version": "trainer_scheduled_pretrain_status_v1",
        "generated_utc": _utc_now(),
        "training_prefix_rows": len(training_prefix),
        "heldout_rows": len(heldout),
        "split_meta": split_meta,
        "paper_only": True,
        "places_real_order": False,
        "routes_to_live": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "live_gate": "blocked_human_only",
        "auto_promote": bool(auto_promote),
        "auto_restart": bool(auto_restart),
    }
    if len(training_prefix) < max(64, batch_size // 4):
        status["phase"] = "ABORT_INSUFFICIENT_TRAINING_ROWS"
        _publish(status)
        return status

    # Phase 1: offline historical pretrain on the PREFIX (98% GPU on the archive).
    rep = run_batch_training(
        training_prefix,
        epochs=epochs,
        steps_per_epoch=steps_per_epoch,
        batch_size=batch_size,
        learning_rate=1e-4,
        entropy_coefficient=0.01,
        weight_decay=0.02,
        dropout=0.10,
        validation_fraction=0.2,
        from_checkpoint=False,
        gpu_sample_interval_s=3.0,
        early_stop_patience=early_stop_patience,
        min_epochs=min_epochs,
    )
    model = rep.pop("trained_model", None)
    status["pretrain"] = {
        "epochs_run": rep.get("epochs_run"),
        "best_epoch": rep.get("best_epoch"),
        "best_validation_loss": rep.get("best_validation_loss"),
        "stopped_early": rep.get("stopped_early"),
        "gpu_utilization_max_pct": rep.get("gpu", {}).get("gpu_utilization_max_pct"),
        "gpu_utilization_mean_pct": rep.get("gpu", {}).get("gpu_utilization_mean_pct"),
        "rows_per_second": rep.get("rows_per_second"),
    }
    if model is not None:
        status["pretrain"]["saved"] = save_offline_weights(model, offline_dir)

    # Phase 2: out-of-sample head-to-head + (gated) promotion.
    h2l = run_h2l(
        offline_dir=offline_dir,
        live_dir=live_dir,
        rows=heldout,
        excluded_rows=training_prefix,
        min_improvement=min_improvement,
        confirm=bool(auto_promote),
    )
    status["head_to_head"] = h2l
    status["promoted"] = bool(h2l.get("promoted"))

    # Phase 3: gated restart so the resident trainer loads a promotion.
    if status["promoted"] and auto_restart:
        try:
            r = subprocess.run(
                ["systemctl", "--user", "restart", TRAINER_SERVICE],
                capture_output=True, text=True, timeout=60, check=False,
            )
            status["trainer_restarted"] = r.returncode == 0
        except Exception as exc:  # pragma: no cover
            status["trainer_restarted"] = False
            status["trainer_restart_error"] = str(exc)

    status["duration_seconds"] = round(time.time() - started, 1)
    status["phase"] = "COMPLETE"
    _publish(status)
    return status


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT,AVAXUSDT,LINKUSDT,DOGEUSDT,LTCUSDT")
    p.add_argument("--timeframes", default="1m,5m,15m,1h")
    p.add_argument("--train-rows", type=int, default=20000)
    p.add_argument("--heldout-rows", type=int, default=5000)
    p.add_argument("--epochs", type=int, default=25)
    p.add_argument("--steps-per-epoch", type=int, default=25)
    p.add_argument("--batch-size", type=int, default=4096)
    p.add_argument("--early-stop-patience", type=int, default=4)
    p.add_argument("--min-epochs", type=int, default=8)
    p.add_argument("--min-improvement", type=float, default=1.0)
    p.add_argument("--offline-dir", default=DEFAULT_OFFLINE_DIR)
    p.add_argument("--live-dir", default=LIVE_CHECKPOINT_DIR)
    p.add_argument("--cache-path", default="claude_worklog/trainer_atlas/scheduled_pretrain_cache.pkl")
    p.add_argument("--auto-promote", action="store_true", help="promote (with backup) if offline wins out-of-sample")
    p.add_argument("--auto-restart", action="store_true", help="restart the trainer after a promotion")
    p.add_argument("--output", default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status = run_scheduled_pretrain(
        symbols=[s.strip().upper() for s in args.symbols.split(",") if s.strip()],
        timeframes=[t.strip().lower() for t in args.timeframes.split(",") if t.strip()],
        train_rows=args.train_rows,
        heldout_rows=args.heldout_rows,
        epochs=args.epochs,
        steps_per_epoch=args.steps_per_epoch,
        batch_size=args.batch_size,
        early_stop_patience=args.early_stop_patience,
        min_epochs=args.min_epochs,
        min_improvement=args.min_improvement,
        offline_dir=args.offline_dir,
        live_dir=args.live_dir,
        cache_path=args.cache_path,
        auto_promote=args.auto_promote,
        auto_restart=args.auto_restart,
    )
    text = json.dumps(status, indent=2, default=str)
    out = args.output or f"claude_worklog/trainer_atlas/scheduled_pretrain_{int(time.time())}.json"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(text)
    print(text)
    hh = status.get("head_to_head", {})
    print("SCHEDULED_PRETRAIN:", status.get("phase"),
          "| decision=", hh.get("decision"),
          "| offline_val=", hh.get("offline", {}).get("validation_supervised_loss"),
          "| live_val=", hh.get("live", {}).get("validation_supervised_loss"),
          "| promoted=", status.get("promoted"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
