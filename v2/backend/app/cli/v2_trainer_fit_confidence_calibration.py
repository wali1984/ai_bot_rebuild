"""WI-3: fit the confidence temperature from realised outcomes (calibration).

The policy is overconfident -- its high-confidence directional calls lose too
often (the governor's HIGH_CONFIDENCE_LOSS_CLUSTER, and the worse-than-live CVaR
that blocks H2L promotion). A fixed temperature (1.4) cannot fix that. This job
runs the current checkpoint on a held-out slice, pairs each directional call's
RAW confidence with whether it was actually profitable, and fits the temperature
(Guo et al. temperature scaling) that minimises NLL. A well-fit T>1 pushes the
overconfident losers below the confidence floor, so the edge gate blocks them --
this only makes selection STRICTER, never looser. Read-only; writes a small
state file the model reads live. Paper/shadow only; live gate stays blocked.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from v2.backend.app.cli.v2_trainer_offline_batch_train import (
    LIVE_CHECKPOINT_DIR,
    load_or_build_examples,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (
    CONFIDENCE_TEMPERATURE_STATE_PATH,
    fit_temperature,
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
    raw_probs, wins = _directional_confidence_outcomes(checkpoint_dir, rows)
    fit = fit_temperature(raw_probs, wins)
    report: dict[str, Any] = {
        "schema_version": "trainer_confidence_calibration_fit_v1",
        "generated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "checkpoint_dir": checkpoint_dir,
        "directional_decisions": len(raw_probs),
        "fit": fit,
        "state_path": str(state_path),
        "paper_only": True,
        "places_real_order": False,
        "routes_to_live": False,
        "live_gate": "blocked_human_only",
    }
    if not fit.get("fitted"):
        report["decision"] = "REFUSE_WRITE_INSUFFICIENT_OR_UNFIT"
        return report
    # Only adopt a fit that actually improves calibration (ECE) out-of-sample.
    if fit["ece_after"] > fit["ece_before"] + 1e-9:
        report["decision"] = "REFUSE_WRITE_ECE_NOT_IMPROVED"
        return report
    if not confirm:
        report["decision"] = "DRY_RUN_PASS_CONFIRM_TO_WRITE"
        return report
    state = {
        "temperature": fit["temperature"],
        "fitted_utc": report["generated_utc"],
        "sample": fit["sample"],
        "ece_before": fit["ece_before"],
        "ece_after": fit["ece_after"],
        "source": "v2_trainer_fit_confidence_calibration",
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2))
    report["decision"] = "WROTE_FITTED_TEMPERATURE"
    return report


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
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols  # noqa: PLC0415

    args = parse_args(argv)
    rows, _ = load_or_build_examples(
        symbols=resolve_symbols(explicit=args.symbols, smoke_test=args.smoke_test),
        timeframes=[t.strip().lower() for t in args.timeframes.split(",") if t.strip()],
        limit=args.limit,
        cache_path=args.cache_path,
        rebuild_cache=False,
    )
    report = run_fit(
        checkpoint_dir=args.checkpoint_dir,
        rows=rows,
        confirm=args.confirm,
        state_path=CONFIDENCE_TEMPERATURE_STATE_PATH,
    )
    text = json.dumps(report, indent=2, default=str)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text)
    print(text)
    fit = report.get("fit", {})
    print(
        "CALIBRATION_FIT:",
        f"decision={report.get('decision')}",
        f"T={fit.get('temperature')}",
        f"ece {fit.get('ece_before')}->{fit.get('ece_after')}",
        f"n={report.get('directional_decisions')}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
