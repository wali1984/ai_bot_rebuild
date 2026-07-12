"""Historical->Live (H2L) checkpoint promotion with a head-to-head validation gate.

The online loop overfits its warm-checkpoint fine-tune (train down, validation
flat/up), so it stays BLOCKED_NO_DURABLE_WEIGHT_UPDATE / INFERENCE_ONLY. The
legacy fix is the H2L transition: build a generalizing checkpoint offline
(historical mode), then promote it as the live warm start so the online loop
refines from a model that already generalizes.

Safety (this tool):
- Head-to-head: scores the OFFLINE checkpoint and the current LIVE checkpoint on
  the SAME held-out validation set, and REFUSES to promote unless the offline one
  generalizes better by a margin. No promoting a worse model.
- Architecture guard: both must load into the same model shape (input_dim +
  hidden/residual from env). A mismatch aborts (never silently fresh-inits live).
- Backs up the entire live checkpoint dir before promoting, so rollback is a copy.
- Dry-run by default; only --confirm mutates the live checkpoint dir.
- Paper/shadow only: never places an order, never routes to live trading, never
  mutates leverage/margin. LIVE_GATE stays blocked_human_only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path
from typing import Any, Sequence

from v2.backend.app.cli.v2_trainer_offline_batch_train import (
    DEFAULT_OFFLINE_DIR,
    LIVE_CHECKPOINT_DIR,
    load_or_build_examples,
)

DEFAULT_HELDOUT_CACHE = "claude_worklog/trainer_atlas/h2l_heldout_cache.pkl"


def _score_checkpoint(checkpoint_dir: str, input_dim: int, rows: Sequence[Any]) -> dict[str, Any]:
    """Load the latest checkpoint in ``checkpoint_dir`` and score held-out loss."""
    from pathlib import Path as _P  # noqa: PLC0415

    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (  # noqa: PLC0415
        V2HybridCheckpointManager,
    )
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (  # noqa: PLC0415
        V2HybridPolicyModel,
    )
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (  # noqa: PLC0415
        V2HybridPPOTrainer,
    )

    model = V2HybridPolicyModel(input_dim=input_dim)
    load = V2HybridCheckpointManager(_P(checkpoint_dir)).load_latest_weights(model)
    if not (load.get("latest_checkpoint_loadable") and load.get("model_state_restored")):
        return {
            "checkpoint_dir": checkpoint_dir,
            "loaded": False,
            "load_status": load,
            "validation_supervised_loss": None,
        }
    trainer = V2HybridPPOTrainer(model=model)
    val = trainer._validation_supervised_loss(list(rows))
    return {
        "checkpoint_dir": checkpoint_dir,
        "loaded": True,
        "checkpoint_id": load.get("latest_metadata_checkpoint_id") or load.get("checkpoint_id"),
        "validation_supervised_loss": val.get("validation_supervised_loss"),
        "validation_rows_evaluated": val.get("validation_rows_evaluated"),
    }


def _backup_live_dir(live_dir: str) -> str:
    src = Path(live_dir)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dst = src.parent / f"{src.name}_backup_{stamp}"
    shutil.copytree(src, dst)
    return str(dst)


def _promote(offline_dir: str, live_dir: str) -> dict[str, Any]:
    """Copy the offline checkpoint's latest weights + manifest into the live dir.

    Copies the offline weight blob(s) and re-points the live manifest at it. The
    live dir is backed up by the caller first.
    """
    from pathlib import Path as _P  # noqa: PLC0415

    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (  # noqa: PLC0415
        V2HybridCheckpointManager,
    )
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (  # noqa: PLC0415
        V2HybridPolicyModel,
    )

    off = _P(offline_dir)
    live = _P(live_dir)
    # Load the offline model, then write it as a fresh live checkpoint (blob +
    # manifest) via the live checkpoint manager so the manifest/lineage are valid.
    import torch  # noqa: PLC0415

    model = V2HybridPolicyModel(input_dim=_infer_input_dim(offline_dir))
    V2HybridCheckpointManager(off).load_latest_weights(model)
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    manifest = V2HybridCheckpointManager(live).write_checkpoint(
        model=model,
        input_dim=int(model.input_dim),
        device=device,
        cuda_active=torch.cuda.is_available(),
        write_weight_blob=True,
    )
    return {
        "promoted_checkpoint_id": getattr(manifest, "checkpoint_id", None)
        or (manifest.get("checkpoint_id") if isinstance(manifest, dict) else None),
        "live_dir": str(live),
    }


def _infer_input_dim(checkpoint_dir: str) -> int:
    """Read input_dim from the offline checkpoint manifest json."""
    for j in sorted(Path(checkpoint_dir).glob("*.json")):
        try:
            data = json.loads(j.read_text())
        except Exception:
            continue
        dim = data.get("input_dim") or data.get("__input_dim")
        if dim:
            return int(dim[0] if isinstance(dim, list) else dim)
    return 1248


def run_h2l(
    *,
    offline_dir: str,
    live_dir: str,
    rows: Sequence[Any],
    min_improvement: float,
    confirm: bool,
) -> dict[str, Any]:
    input_dim = _infer_input_dim(offline_dir)
    live_score = _score_checkpoint(live_dir, input_dim, rows)
    offline_score = _score_checkpoint(offline_dir, input_dim, rows)
    lv = live_score.get("validation_supervised_loss")
    ov = offline_score.get("validation_supervised_loss")
    report: dict[str, Any] = {
        "schema_version": "trainer_h2l_promotion_v1",
        "input_dim": input_dim,
        "held_out_rows": len(rows),
        "live": live_score,
        "offline": offline_score,
        "min_improvement": float(min_improvement),
        "offline_loaded": offline_score.get("loaded"),
        "live_loaded": live_score.get("loaded"),
        # safety posture
        "paper_only": True,
        "places_real_order": False,
        "routes_to_live": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "live_gate": "blocked_human_only",
    }
    if not (offline_score.get("loaded") and live_score.get("loaded")):
        report["decision"] = "ABORT_CHECKPOINT_LOAD_FAILED_OR_SHAPE_MISMATCH"
        report["promoted"] = False
        return report
    if ov is None or lv is None:
        report["decision"] = "ABORT_NO_VALIDATION_SIGNAL"
        report["promoted"] = False
        return report
    offline_better_by = lv - ov  # positive => offline has lower (better) held-out loss
    report["offline_better_by"] = round(offline_better_by, 6)
    if offline_better_by < min_improvement:
        report["decision"] = "REFUSE_OFFLINE_NOT_BETTER"
        report["promoted"] = False
        return report
    if not confirm:
        report["decision"] = "DRY_RUN_OFFLINE_WINS_PASS_CONFIRM_TO_PROMOTE"
        report["promoted"] = False
        return report
    report["backup_dir"] = _backup_live_dir(live_dir)
    report["promotion"] = _promote(offline_dir, live_dir)
    report["decision"] = "PROMOTED"
    report["promoted"] = True
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--offline-dir", default=DEFAULT_OFFLINE_DIR)
    p.add_argument("--live-dir", default=LIVE_CHECKPOINT_DIR)
    p.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT,ADAUSDT,AVAXUSDT,LINKUSDT")
    p.add_argument("--timeframes", default="1m,5m,15m,1h")
    p.add_argument("--limit", type=int, default=6000, help="held-out validation rows")
    p.add_argument("--min-improvement", type=float, default=0.0,
                   help="offline held-out loss must be lower than live by at least this margin")
    p.add_argument("--cache-path", default=DEFAULT_HELDOUT_CACHE)
    p.add_argument("--confirm", action="store_true", help="actually promote (default is dry-run)")
    p.add_argument("--output", default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows, _ = load_or_build_examples(
        symbols=args.symbols.split(","),
        timeframes=args.timeframes.split(","),
        limit=args.limit,
        cache_path=args.cache_path,
        rebuild_cache=False,
    )
    if not rows:
        print(json.dumps({"error": "no held-out rows loaded", "promoted": False}))
        return 2
    report = run_h2l(
        offline_dir=args.offline_dir,
        live_dir=args.live_dir,
        rows=rows,
        min_improvement=args.min_improvement,
        confirm=args.confirm,
    )
    text = json.dumps(report, indent=2, default=str)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text)
    print(text)
    print(
        "H2L:",
        report.get("decision"),
        "| live_val=", report.get("live", {}).get("validation_supervised_loss"),
        "| offline_val=", report.get("offline", {}).get("validation_supervised_loss"),
        "| offline_better_by=", report.get("offline_better_by"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
