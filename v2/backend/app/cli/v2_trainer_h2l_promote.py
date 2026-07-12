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
import os
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
DEFAULT_HELDOUT_OFFSET = int(os.getenv("V2_H2L_HELDOUT_OFFSET", "20000") or 20000)


def _example_identity(example: Any) -> str:
    tensor = getattr(example, "tensor", None)
    return json.dumps(
        {
            "symbol": getattr(example, "symbol", None),
            "timeframe": getattr(example, "timeframe", None),
            "tensor_id": getattr(tensor, "tensor_id", None),
            "feature_snapshot_id": getattr(tensor, "feature_snapshot_id", None),
            "label_action_index": getattr(example, "label_action_index", None),
            "payload_keys": list(getattr(example, "payload_keys", ()) or ()),
        },
        sort_keys=True,
        default=str,
    )


def _overlap_report(rows: Sequence[Any], excluded_rows: Sequence[Any]) -> dict[str, Any]:
    excluded = {_example_identity(row) for row in excluded_rows}
    overlap = sorted(
        identity for row in rows if (identity := _example_identity(row)) in excluded
    )
    return {
        "heldout_row_count": len(rows),
        "excluded_row_count": len(excluded_rows),
        "overlap_count": len(overlap),
        "overlap_samples": overlap[:10],
    }


def load_h2l_heldout_examples(
    *,
    symbols: Sequence[str],
    timeframes: Sequence[str],
    limit: int,
    heldout_offset: int,
    cache_path: str | None,
    rebuild_cache: bool,
) -> tuple[list[Any], list[Any], dict[str, Any]]:
    """Load a disjoint validation slice after a training-prefix offset.

    H2L promotion must not score against the same archive prefix used for the
    offline pretrain. This helper loads ``heldout_offset + limit`` examples and
    returns ``(heldout_rows, excluded_prefix_rows, metadata)``.
    """
    offset = max(0, int(heldout_offset))
    requested = max(0, int(limit)) + offset
    examples, meta = load_or_build_examples(
        symbols=symbols,
        timeframes=timeframes,
        limit=requested,
        cache_path=cache_path,
        rebuild_cache=rebuild_cache,
    )
    if cache_path and not rebuild_cache and len(examples) < requested and meta.get("cache_hit"):
        examples, meta = load_or_build_examples(
            symbols=symbols,
            timeframes=timeframes,
            limit=requested,
            cache_path=cache_path,
            rebuild_cache=True,
        )
        meta["rebuilt_cache_reason"] = "cached_rows_shorter_than_h2l_heldout_offset"
    heldout_rows = examples[offset : offset + max(0, int(limit))]
    excluded_rows = examples[:offset]
    meta.update(
        {
            "h2l_heldout_offset": offset,
            "h2l_requested_rows": requested,
            "h2l_heldout_rows": len(heldout_rows),
            "h2l_excluded_prefix_rows": len(excluded_rows),
        }
    )
    return heldout_rows, excluded_rows, meta


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


def _returns_from_actions(rows: Sequence[Any], actions: Sequence[int]) -> list[float]:
    """Per-trade realised returns from argmax actions (long=+move, short=-move).

    Action semantics mirror the trainer: index 1 = long, index 2 = short; every
    other index is treated as no position and contributes no trade return. The
    realised move is each row's label_expected_move_after_cost_bps (post-cost, so
    a losing directional call already nets negative). Pure/testable -- no torch.
    """
    returns: list[float] = []
    for r, a in zip(rows, actions, strict=False):
        move = float(getattr(r, "label_expected_move_after_cost_bps", 0.0) or 0.0)
        if a == 1:      # long
            returns.append(move)
        elif a == 2:    # short
            returns.append(-move)
        # other actions = no position -> no trade return
    return returns


def _candidate_risk_summary(
    checkpoint_dir: str, input_dim: int, rows: Sequence[Any]
) -> dict[str, Any]:
    """Out-of-sample risk-adjusted summary (WI-2) for a checkpoint's decisions.

    Runs the model on held-out rows, takes the argmax action, and builds a
    per-trade realised-return series (long=+move, short=-move, using each row's
    label_expected_move_after_cost_bps). Sortino/CVaR of that series measure the
    candidate's downside/tail risk out-of-sample. Read-only; never trades.
    """
    from pathlib import Path as _P  # noqa: PLC0415

    import torch  # noqa: PLC0415

    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (  # noqa: PLC0415
        V2HybridCheckpointManager,
    )
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (  # noqa: PLC0415
        V2HybridPolicyModel,
    )
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.risk_metrics import (  # noqa: PLC0415
        risk_adjusted_summary,
    )

    model = V2HybridPolicyModel(input_dim=input_dim)
    load = V2HybridCheckpointManager(_P(checkpoint_dir)).load_latest_weights(model)
    loadable = load.get("latest_checkpoint_loadable") and load.get("model_state_restored")
    if not loadable or model.net is None:
        return {"loaded": False}
    net = model.net
    device = model.device
    returns: list[float] = []
    try:
        net.eval()
        with torch.no_grad():
            vectors = [list(r.tensor.model_vector) for r in rows]
            x = torch.tensor(vectors, dtype=torch.float32, device="cpu")
            x = torch.nan_to_num(x, nan=0.0, posinf=1e6, neginf=-1e6).to(device=device)
            actions = torch.argmax(net(x)["logits"], dim=-1).detach().cpu().tolist()
        returns = _returns_from_actions(rows, actions)
    except Exception as exc:  # pragma: no cover
        return {"loaded": True, "error": str(exc)}
    summary = risk_adjusted_summary(returns)
    summary["loaded"] = True
    summary["trades"] = len(returns)
    return summary


def _float_or_none(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _risk_gate_report(
    *,
    live_risk: dict[str, Any],
    offline_risk: dict[str, Any],
    min_sortino: float,
    max_cvar_loss_bps: float | None,
) -> dict[str, Any]:
    """Promotion guard for WI-2 risk-adjusted H2L validation.

    A checkpoint must not be promoted on lower supervised loss alone when its
    out-of-sample actions have worse downside/tail behavior than the incumbent.
    """
    failures: list[str] = []
    live_sortino = _float_or_none(live_risk.get("sortino_ratio"))
    offline_sortino = _float_or_none(offline_risk.get("sortino_ratio"))
    live_cvar = _float_or_none(live_risk.get("cvar"))
    offline_cvar = _float_or_none(offline_risk.get("cvar"))
    offline_trades = int(offline_risk.get("trades") or 0)

    if not offline_risk.get("loaded"):
        failures.append("OFFLINE_RISK_SUMMARY_UNAVAILABLE")
    if offline_risk.get("error"):
        failures.append("OFFLINE_RISK_SUMMARY_ERROR")
    if offline_trades <= 0:
        failures.append("OFFLINE_POLICY_PRODUCED_NO_OUT_OF_SAMPLE_TRADES")
    if offline_sortino is None:
        failures.append("OFFLINE_SORTINO_UNAVAILABLE")
    elif offline_sortino < float(min_sortino):
        failures.append("OFFLINE_SORTINO_BELOW_MINIMUM")
    if live_sortino is not None and offline_sortino is not None and offline_sortino < live_sortino:
        failures.append("OFFLINE_SORTINO_WORSE_THAN_LIVE")

    if max_cvar_loss_bps is not None:
        max_loss = abs(float(max_cvar_loss_bps))
        if offline_cvar is None:
            failures.append("OFFLINE_CVAR_UNAVAILABLE")
        elif offline_cvar < -max_loss:
            failures.append("OFFLINE_CVAR_TAIL_LOSS_EXCEEDS_LIMIT")
    if live_cvar is not None and offline_cvar is not None and offline_cvar < live_cvar:
        failures.append("OFFLINE_CVAR_WORSE_THAN_LIVE")

    return {
        "required": True,
        "passed": not failures,
        "failures": failures,
        "min_sortino": float(min_sortino),
        "max_cvar_loss_bps": max_cvar_loss_bps,
        "offline_sortino": offline_sortino,
        "live_sortino": live_sortino,
        "offline_cvar": offline_cvar,
        "live_cvar": live_cvar,
        "offline_trades": offline_trades,
        "live_trades": int(live_risk.get("trades") or 0),
        "rule": (
            "offline must meet min Sortino, produce OOS trades, stay within CVaR "
            "limit when configured, and not be worse than live on Sortino/CVaR"
        ),
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
    excluded_rows: Sequence[Any] | None = None,
    min_improvement: float,
    confirm: bool,
    require_risk_gate: bool = False,
    min_sortino: float = 0.0,
    max_cvar_loss_bps: float | None = None,
) -> dict[str, Any]:
    input_dim = _infer_input_dim(offline_dir)
    overlap = _overlap_report(rows, excluded_rows or [])
    if overlap["overlap_count"] > 0:
        return {
            "schema_version": "trainer_h2l_promotion_v1",
            "input_dim": input_dim,
            "held_out_rows": len(rows),
            "heldout_overlap": overlap,
            "decision": "ABORT_HELDOUT_OVERLAPS_TRAINING_ROWS",
            "promoted": False,
            "paper_only": True,
            "places_real_order": False,
            "routes_to_live": False,
            "leverage_mutated": False,
            "margin_mutated": False,
            "live_gate": "blocked_human_only",
        }
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
        "heldout_overlap": overlap,
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
    if require_risk_gate:
        live_risk = _candidate_risk_summary(live_dir, input_dim, rows)
        offline_risk = _candidate_risk_summary(offline_dir, input_dim, rows)
        risk_gate = _risk_gate_report(
            live_risk=live_risk,
            offline_risk=offline_risk,
            min_sortino=min_sortino,
            max_cvar_loss_bps=max_cvar_loss_bps,
        )
        report["risk_adjusted_validation"] = {
            "live": live_risk,
            "offline": offline_risk,
            "gate": risk_gate,
        }
        if not risk_gate["passed"]:
            report["decision"] = "REFUSE_RISK_ADJUSTED_PROMOTION_GATE"
            report["promoted"] = False
            return report
    else:
        report["risk_adjusted_validation"] = {
            "gate": {
                "required": False,
                "passed": None,
                "reason": "require_risk_gate_false",
            }
        }
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
    p.add_argument(
        "--heldout-offset",
        type=int,
        default=DEFAULT_HELDOUT_OFFSET,
        help=(
            "skip this many trusted examples before selecting validation rows, "
            "so the H2L gate does not score against the offline-training prefix"
        ),
    )
    p.add_argument("--min-improvement", type=float, default=0.0,
                   help="offline held-out loss must be lower than live by at least this margin")
    p.add_argument(
        "--require-risk-gate",
        action=argparse.BooleanOptionalAction,
        default=os.getenv("V2_H2L_REQUIRE_RISK_GATE", "1").strip().lower()
        in {"1", "true", "yes", "on"},
        help="require out-of-sample Sortino/CVaR gate before promotion",
    )
    p.add_argument(
        "--min-sortino",
        type=float,
        default=float(os.getenv("V2_H2L_MIN_SORTINO", "0.0") or 0.0),
    )
    p.add_argument(
        "--max-cvar-loss-bps",
        type=float,
        default=(
            float(os.environ["V2_H2L_MAX_CVAR_LOSS_BPS"])
            if os.getenv("V2_H2L_MAX_CVAR_LOSS_BPS")
            else None
        ),
        help="optional maximum allowed signed CVaR tail loss in bps, e.g. 25 blocks CVaR below -25",
    )
    p.add_argument("--cache-path", default=DEFAULT_HELDOUT_CACHE)
    p.add_argument("--rebuild-cache", action="store_true")
    p.add_argument("--confirm", action="store_true", help="actually promote (default is dry-run)")
    p.add_argument("--output", default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows, excluded_rows, load_meta = load_h2l_heldout_examples(
        symbols=args.symbols.split(","),
        timeframes=args.timeframes.split(","),
        limit=args.limit,
        heldout_offset=args.heldout_offset,
        cache_path=args.cache_path,
        rebuild_cache=args.rebuild_cache,
    )
    if not rows:
        print(json.dumps({
            "error": "no held-out rows loaded",
            "heldout_load": load_meta,
            "promoted": False,
        }))
        return 2
    report = run_h2l(
        offline_dir=args.offline_dir,
        live_dir=args.live_dir,
        rows=rows,
        excluded_rows=excluded_rows,
        min_improvement=args.min_improvement,
        confirm=args.confirm,
        require_risk_gate=bool(args.require_risk_gate),
        min_sortino=float(args.min_sortino),
        max_cvar_loss_bps=args.max_cvar_loss_bps,
    )
    report["heldout_load"] = load_meta
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
        "| risk_gate=", report.get("risk_adjusted_validation", {}).get("gate", {}).get("passed"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
