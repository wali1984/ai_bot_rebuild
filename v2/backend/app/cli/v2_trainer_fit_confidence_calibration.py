"""Deprecated external confidence fitter (fail-closed compatibility command).

Confidence calibration is now fitted only from the trainer's purged training
partition and persisted inside the same checkpoint blob as the calibrated
weights.  A global state file fitted from a held-out slice would leak forward
validation into inference and could calibrate unrelated weights, so this command
never scores, writes, or adopts calibration state.
"""
from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from v2.backend.app.cli.v2_trainer_offline_batch_train import (
    LIVE_CHECKPOINT_DIR,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (
    CONFIDENCE_TEMPERATURE_STATE_PATH,
)


def _directional_confidence_outcomes(
    checkpoint_dir: str, rows: Sequence[Any]
) -> tuple[list[float], list[int]]:
    """Run the checkpoint on rows -> (raw_confidence, realised_win) for trades.

    Only rows where the model selects a directional action (long/short) count --
    those are the decisions the confidence gate governs. win=1 when the realised
    post-cost move went the model's way.
    """
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (  # noqa: PLC0415
        V2HybridCheckpointManager,
    )
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (  # noqa: PLC0415
        V2HybridPolicyModel,
    )

    input_dim = len(rows[0].tensor.model_vector) if rows else 1248
    model = V2HybridPolicyModel(input_dim=input_dim)
    load = V2HybridCheckpointManager(Path(checkpoint_dir)).load_latest_weights(model)
    if not (load.get("latest_checkpoint_loadable") and load.get("model_state_restored")):
        return [], []
    raw_probs: list[float] = []
    wins: list[int] = []
    for r in rows:
        out = model.forward(r.tensor)
        action = int(out.selected_action_index)
        if action not in (1, 2):  # only directional trades
            continue
        move = float(getattr(r, "label_expected_move_after_cost_bps", 0.0) or 0.0)
        ret = move if action == 1 else -move
        raw_probs.append(float(out.confidence_raw))
        wins.append(1 if ret > 0 else 0)
    return raw_probs, wins


def run_fit(
    *,
    checkpoint_dir: str,
    rows: Sequence[Any],
    confirm: bool,
    state_path: Path,
) -> dict[str, Any]:
    return {
        "schema_version": "trainer_confidence_calibration_external_fitter_deprecated_v2",
        "generated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "checkpoint_dir": checkpoint_dir,
        "rows_received_but_not_scored": len(rows),
        "confirm_requested_but_refused": bool(confirm),
        "state_path": str(state_path),
        "state_write_attempted": False,
        "state_mutated": False,
        "external_state_adopted_by_inference": False,
        "decision": "BLOCKED_EXTERNAL_CALIBRATION_BYPASS_DEPRECATED",
        "reason": (
            "CALIBRATION_MUST_BE_PURGED_TRAIN_ONLY_AND_BOUND_TO_THE_SAME_CHECKPOINT_BLOB"
        ),
        "paper_only": True,
        "places_real_order": False,
        "routes_to_live": False,
        "live_gate": "blocked_human_only",
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checkpoint-dir", default=LIVE_CHECKPOINT_DIR)
    p.add_argument("--symbols", default=None,
                   help="comma-separated symbols; default = dynamic universe resolver (adaptive)")
    p.add_argument("--smoke-test", action="store_true",
                   help="use the BTC/ETH/SOL smoke-test set (test only)")
    p.add_argument("--timeframes", default="1m,5m,15m,1h")
    p.add_argument("--limit", type=int, default=8000, help="held-out rows to score")
    p.add_argument("--cache-path", default="claude_worklog/trainer_atlas/calibration_fit_cache.pkl")
    p.add_argument("--confirm", action="store_true",
                   help="write the fitted temperature (default dry-run)")
    p.add_argument("--output", default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run_fit(
        checkpoint_dir=args.checkpoint_dir,
        rows=(),
        confirm=args.confirm,
        state_path=CONFIDENCE_TEMPERATURE_STATE_PATH,
    )
    import json  # noqa: PLC0415

    text = json.dumps(report, indent=2, default=str)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text)
    print(text)
    print(
        "CALIBRATION_FIT:",
        f"decision={report.get('decision')}",
        "external_state_write=False",
        "checkpoint_bound_required=True",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
