"""Historical-to-serving checkpoint comparison (legacy mutation quarantined).

The online loop overfits its warm-checkpoint fine-tune (train down, validation
flat/up), so it stays BLOCKED_NO_DURABLE_WEIGHT_UPDATE / INFERENCE_ONLY. The
legacy fix is the H2L transition: build a generalizing checkpoint offline
(historical mode), then promote it as the live warm start so the online loop
refines from a model that already generalizes.

Safety (this tool):
- Paper-only diagnostics may compare two integrity-verified, content-addressed,
  causally ordered checkpoint artifacts on the same disjoint forward slice.
- The legacy copy/write promotion path is quarantined. ``--confirm`` fails closed
  before reading or writing either checkpoint directory. It cannot back up,
  replace, or create serving artifacts.
- Canonical candidate-vs-serving promotion belongs to the persistent trainer's
  checkpoint lifecycle and must prove exact optimizer-ledger, ancestry,
  calibration, and untouched-forward PIT/label-maturity evidence. This legacy
  CLI does not possess that complete contract.
- It never places an order, routes to live trading, restarts a service, or
  mutates leverage/margin. LIVE_GATE stays ``blocked_human_only``.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any, Sequence

from v2.backend.app.cli.v2_trainer_offline_batch_train import (
    DEFAULT_OFFLINE_DIR,
    LIVE_CHECKPOINT_DIR,
    load_or_build_examples,
)

DEFAULT_HELDOUT_CACHE = "claude_worklog/trainer_atlas/h2l_heldout_cache.pkl"
DEFAULT_HELDOUT_OFFSET = int(os.getenv("V2_H2L_HELDOUT_OFFSET", "20000") or 20000)
LEGACY_H2L_MUTATION_BLOCKER = "LEGACY_H2L_MUTATION_LANE_QUARANTINED"
PROMOTION_CONTRACT_BLOCKERS = (
    LEGACY_H2L_MUTATION_BLOCKER,
    "CANONICAL_CANDIDATE_VS_SERVING_LIFECYCLE_UNPROVEN",
    "UNTOUCHED_FORWARD_PIT_AND_LABEL_MATURITY_UNPROVEN",
    "EXACT_OPTIMIZER_LEDGER_ANCESTRY_CALIBRATION_UNPROVEN",
)


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
    if len(examples) <= offset and examples:
        # Supply shorter than the requested training prefix (fresh tail windows
        # legitimately yield fewer labelable rows than train_rows). The fixed
        # offset would leave an EMPTY heldout, scoring both sides at None and
        # aborting every run with NO_VALIDATION_SIGNAL. Fall back to a
        # proportional split: newest ~24% (time-ordered suffix) becomes the
        # out-of-sample heldout; the prefix stays the training set. Disjointness
        # is preserved — only the boundary moves.
        offset = max(1, int(len(examples) * 0.76))
        meta["h2l_proportional_split_fallback"] = {
            "supply": len(examples),
            "requested_offset": max(0, int(heldout_offset)),
            "effective_offset": offset,
        }
    heldout_rows = examples[offset : offset + max(0, int(limit))]
    excluded_rows = examples[:offset]
    meta.update(
        {
            "h2l_heldout_offset": offset,
            "h2l_requested_rows": requested,
            "h2l_heldout_rows": len(heldout_rows),
            "h2l_excluded_prefix_rows": len(excluded_rows),
            "diagnostic_only": True,
            "promotion_contract_verified": False,
            "promotion_contract_blockers": list(PROMOTION_CONTRACT_BLOCKERS),
        }
    )
    return heldout_rows, excluded_rows, meta


def _verified_checkpoint_metadata(checkpoint_dir: str) -> dict[str, Any]:
    """Resolve one checkpoint only through the canonical causal verifier.

    Filesystem order, modification time, arbitrary JSON, and architecture
    fallbacks are deliberately not identity signals. The highest causal
    generation returned by ``manifests`` must itself verify; corruption or
    ambiguity is never skipped in favour of an older artifact.
    """
    from pathlib import Path as _P  # noqa: PLC0415

    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (  # noqa: PLC0415
        V2HybridCheckpointManager,
    )

    manager = V2HybridCheckpointManager(_P(checkpoint_dir))
    try:
        manifests = manager.manifests(require_weight_blob=True)
    except Exception as exc:  # noqa: BLE001 - convert to stable fail-closed contract
        raise RuntimeError("checkpoint_manifest_or_causal_ledger_invalid") from exc
    if not manifests:
        raise RuntimeError("checkpoint_verified_manifest_missing")
    manifest = manifests[0]
    try:
        verification = manager.verify_manifest_artifact(manifest)
    except Exception as exc:  # noqa: BLE001 - stable fail-closed diagnostic
        raise RuntimeError("checkpoint_artifact_verification_failed") from exc
    required = (
        verification.get("checkpoint_artifact_verified") is True
        and verification.get("checkpoint_identity_verified") is True
        and verification.get("checkpoint_evidence_verified") is True
        and verification.get("weight_file_sha256_verified") is True
        and verification.get("model_parameter_fingerprint_verified") is True
        and verification.get("checkpoint_id") == manifest.checkpoint_id
        and isinstance(manifest.input_dim, int)
        and manifest.input_dim > 0
        and isinstance(manifest.checkpoint_generation, int)
        and manifest.checkpoint_generation > 0
        and isinstance(manifest.checkpoint_semantic_digest, str)
        and len(manifest.checkpoint_semantic_digest) == 64
        and isinstance(manifest.checkpoint_causal_record_digest, str)
        and len(manifest.checkpoint_causal_record_digest) == 64
        and bool(manifest.lineage_kind)
    )
    if not required:
        raise RuntimeError(
            "checkpoint_content_identity_or_lineage_unverified:"
            + json.dumps(verification, sort_keys=True, default=str)
        )
    return {
        "checkpoint_id": manifest.checkpoint_id,
        "input_dim": manifest.input_dim,
        "model_id": manifest.model_id,
        "lineage_kind": manifest.lineage_kind,
        "checkpoint_generation": manifest.checkpoint_generation,
        "checkpoint_semantic_digest": manifest.checkpoint_semantic_digest,
        "checkpoint_causal_record_digest": manifest.checkpoint_causal_record_digest,
        "weight_file_sha256": verification.get("weight_file_sha256"),
        "checkpoint_evidence_digest": verification.get("checkpoint_evidence_digest"),
        "artifact_verified": True,
    }


def _score_checkpoint(checkpoint_dir: str, input_dim: int, rows: Sequence[Any]) -> dict[str, Any]:
    """Load the exact verified causal checkpoint and score diagnostic loss."""
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

    try:
        identity = _verified_checkpoint_metadata(checkpoint_dir)
    except RuntimeError as exc:
        return {
            "checkpoint_dir": checkpoint_dir,
            "loaded": False,
            "load_status": str(exc),
            "validation_supervised_loss": None,
        }
    if identity["input_dim"] != input_dim:
        return {
            "checkpoint_dir": checkpoint_dir,
            "loaded": False,
            "load_status": "CHECKPOINT_INPUT_DIM_MISMATCH",
            "checkpoint_identity": identity,
            "validation_supervised_loss": None,
        }
    model = V2HybridPolicyModel(input_dim=input_dim)
    load = V2HybridCheckpointManager(_P(checkpoint_dir)).load_latest_weights(
        model,
        allowed_lineage_kinds=frozenset({str(identity["lineage_kind"])}),
    )
    load_verified = (
        load.get("latest_checkpoint_loadable") is True
        and load.get("model_state_restored") is True
        and load.get("checkpoint_identity_verified") is True
        and load.get("checkpoint_evidence_verified") is True
        and load.get("weight_file_sha256_verified") is True
        and load.get("checkpoint_id") == identity["checkpoint_id"]
    )
    if not load_verified:
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
        "checkpoint_id": load.get("checkpoint_id"),
        "checkpoint_identity": identity,
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
    if len(rows) != len(actions):
        raise ValueError("H2L_ACTION_LABEL_CARDINALITY_MISMATCH")
    for r, a in zip(rows, actions, strict=True):
        raw_move = getattr(r, "label_expected_move_after_cost_bps", None)
        try:
            move = float(raw_move)
        except (TypeError, ValueError) as exc:
            raise ValueError("H2L_MATURE_POST_COST_LABEL_MISSING") from exc
        if not math.isfinite(move):
            raise ValueError("H2L_MATURE_POST_COST_LABEL_NONFINITE")
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

    try:
        identity = _verified_checkpoint_metadata(checkpoint_dir)
    except RuntimeError as exc:
        return {"loaded": False, "error": str(exc)}
    if identity["input_dim"] != input_dim:
        return {"loaded": False, "error": "CHECKPOINT_INPUT_DIM_MISMATCH"}
    model = V2HybridPolicyModel(input_dim=input_dim)
    load = V2HybridCheckpointManager(_P(checkpoint_dir)).load_latest_weights(
        model,
        allowed_lineage_kinds=frozenset({str(identity["lineage_kind"])}),
    )
    loadable = (
        load.get("latest_checkpoint_loadable") is True
        and load.get("model_state_restored") is True
        and load.get("checkpoint_identity_verified") is True
        and load.get("checkpoint_evidence_verified") is True
        and load.get("weight_file_sha256_verified") is True
        and load.get("checkpoint_id") == identity["checkpoint_id"]
    )
    if not loadable or model.net is None:
        return {"loaded": False, "load_status": load}
    net = model.net
    device = model.device
    returns: list[float] = []
    from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.temporal_windowing import (  # noqa: PLC0415
        build_window_lookup,
        model_batch_tensor,
    )
    _temporal = bool(getattr(model, "temporal_encoder_enabled", False))
    _seq_len = int(getattr(model, "temporal_seq_len", 16))
    _lookup = build_window_lookup(list(rows), seq_len=_seq_len) if _temporal else None
    try:
        net.eval()
        with torch.no_grad():
            x = model_batch_tensor(
                torch, list(rows), temporal=_temporal, seq_len=_seq_len,
                window_lookup=_lookup, device="cpu",
            )
            if not bool(torch.isfinite(x).all().item()):
                raise ValueError("H2L_HELDOUT_MODEL_VECTOR_NONFINITE")
            x = x.to(device=device)
            actions = torch.argmax(net(x)["logits"], dim=-1).detach().cpu().tolist()
        returns = _returns_from_actions(rows, actions)
    except Exception as exc:  # noqa: BLE001 - diagnostic fails closed
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
    return parsed if math.isfinite(parsed) else None


def _risk_gate_report(
    *,
    live_risk: dict[str, Any],
    offline_risk: dict[str, Any],
    min_sortino: float,
    max_cvar_loss_bps: float | None,
) -> dict[str, Any]:
    """Relative paired diagnostic; legacy absolute thresholds are ignored.

    Only immutable evidence availability and candidate-vs-incumbent
    non-regression are evaluated. This report never authorizes mutation.
    """
    failures: list[str] = []
    live_sortino = _float_or_none(live_risk.get("sortino_ratio"))
    offline_sortino = _float_or_none(offline_risk.get("sortino_ratio"))
    live_cvar = _float_or_none(live_risk.get("cvar"))
    offline_cvar = _float_or_none(offline_risk.get("cvar"))
    offline_trades = int(offline_risk.get("trades") or 0)

    if not live_risk.get("loaded"):
        failures.append("LIVE_RISK_SUMMARY_UNAVAILABLE")
    if not offline_risk.get("loaded"):
        failures.append("OFFLINE_RISK_SUMMARY_UNAVAILABLE")
    if live_risk.get("error"):
        failures.append("LIVE_RISK_SUMMARY_ERROR")
    if offline_risk.get("error"):
        failures.append("OFFLINE_RISK_SUMMARY_ERROR")
    if offline_trades <= 0:
        failures.append("OFFLINE_POLICY_PRODUCED_NO_OUT_OF_SAMPLE_TRADES")
    if int(live_risk.get("trades") or 0) <= 0:
        failures.append("LIVE_POLICY_PRODUCED_NO_OUT_OF_SAMPLE_TRADES")
    if offline_sortino is None:
        failures.append("OFFLINE_SORTINO_UNAVAILABLE")
    if live_sortino is None:
        failures.append("LIVE_SORTINO_UNAVAILABLE")
    if live_sortino is not None and offline_sortino is not None and offline_sortino < live_sortino:
        failures.append("OFFLINE_SORTINO_WORSE_THAN_LIVE")

    if offline_cvar is None:
        failures.append("OFFLINE_CVAR_UNAVAILABLE")
    if live_cvar is None:
        failures.append("LIVE_CVAR_UNAVAILABLE")
    if live_cvar is not None and offline_cvar is not None and offline_cvar < live_cvar:
        failures.append("OFFLINE_CVAR_WORSE_THAN_LIVE")

    return {
        "required": True,
        "passed": not failures,
        "failures": failures,
        "legacy_static_min_sortino_ignored": float(min_sortino),
        "legacy_static_max_cvar_loss_bps_ignored": max_cvar_loss_bps,
        "offline_sortino": offline_sortino,
        "live_sortino": live_sortino,
        "offline_cvar": offline_cvar,
        "live_cvar": live_cvar,
        "offline_trades": offline_trades,
        "live_trades": int(live_risk.get("trades") or 0),
        "mutation_authorized": False,
        "rule": "paired forward diagnostic must not regress live Sortino or CVaR",
    }


def _backup_live_dir(live_dir: str) -> str:
    del live_dir
    raise RuntimeError(LEGACY_H2L_MUTATION_BLOCKER)


def _promote(offline_dir: str, live_dir: str) -> dict[str, Any]:
    del offline_dir, live_dir
    raise RuntimeError(LEGACY_H2L_MUTATION_BLOCKER)


def _infer_input_dim(checkpoint_dir: str) -> int:
    """Return only a causal, content-addressed, artifact-verified width."""
    return int(_verified_checkpoint_metadata(checkpoint_dir)["input_dim"])


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
    safety_posture: dict[str, Any] = {
        "paper_only": True,
        "places_real_order": False,
        "routes_to_live": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "serving_checkpoint_mutated": False,
        "service_restart_attempted": False,
        "live_gate": "blocked_human_only",
        "promotion_mutation_authorized": False,
        "promotion_contract_verified": False,
        "promotion_contract_blockers": list(PROMOTION_CONTRACT_BLOCKERS),
        "legacy_static_min_improvement_ignored": float(min_improvement),
        "legacy_static_min_sortino_ignored": float(min_sortino),
        "legacy_static_max_cvar_loss_bps_ignored": max_cvar_loss_bps,
    }
    # ``--confirm`` used to cross the serving mutation boundary. It is now a
    # stable fail-closed request and is rejected before any checkpoint read,
    # backup, write, or model construction occurs.
    if confirm:
        return {
            "schema_version": "trainer_h2l_diagnostic_v2",
            "held_out_rows": len(rows),
            "confirmation_requested": True,
            "decision": LEGACY_H2L_MUTATION_BLOCKER,
            "promoted": False,
            **safety_posture,
        }
    try:
        input_dim = _infer_input_dim(offline_dir)
    except RuntimeError as exc:
        return {
            "schema_version": "trainer_h2l_diagnostic_v2",
            "held_out_rows": len(rows),
            "confirmation_requested": False,
            "decision": "ABORT_CHECKPOINT_CONTENT_IDENTITY_UNVERIFIED",
            "checkpoint_identity_error": str(exc),
            "promoted": False,
            **safety_posture,
        }
    overlap = _overlap_report(rows, excluded_rows or [])
    if overlap["overlap_count"] > 0:
        return {
            "schema_version": "trainer_h2l_diagnostic_v2",
            "input_dim": input_dim,
            "held_out_rows": len(rows),
            "heldout_overlap": overlap,
            "decision": "ABORT_HELDOUT_OVERLAPS_TRAINING_ROWS",
            "promoted": False,
            **safety_posture,
        }
    live_score = _score_checkpoint(live_dir, input_dim, rows)
    offline_score = _score_checkpoint(offline_dir, input_dim, rows)
    lv = live_score.get("validation_supervised_loss")
    ov = offline_score.get("validation_supervised_loss")
    report: dict[str, Any] = {
        "schema_version": "trainer_h2l_diagnostic_v2",
        "input_dim": input_dim,
        "held_out_rows": len(rows),
        "live": live_score,
        "offline": offline_score,
        "offline_loaded": offline_score.get("loaded"),
        "live_loaded": live_score.get("loaded"),
        "heldout_overlap": overlap,
        "confirmation_requested": False,
        **safety_posture,
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
    if not math.isfinite(float(offline_better_by)):
        report["decision"] = "ABORT_NONFINITE_PAIRED_VALIDATION_SIGNAL"
        report["promoted"] = False
        return report
    if offline_better_by <= 0.0:
        report["decision"] = "DIAGNOSTIC_OFFLINE_RELATIVE_REGRESSION"
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
    report["decision"] = "DIAGNOSTIC_OFFLINE_RELATIVE_NON_REGRESSION"
    report["promoted"] = False
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--offline-dir", default=DEFAULT_OFFLINE_DIR)
    p.add_argument("--live-dir", default=LIVE_CHECKPOINT_DIR)
    p.add_argument("--symbols", default=None,
                   help="comma-separated symbols; default = dynamic universe resolver (adaptive)")
    p.add_argument("--smoke-test", action="store_true",
                   help="use the BTC/ETH/SOL smoke-test set (test only)")
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
    p.add_argument(
        "--min-improvement",
        type=float,
        default=0.0,
        help="legacy compatibility value; ignored and never authorizes mutation",
    )
    p.add_argument(
        "--require-risk-gate",
        action=argparse.BooleanOptionalAction,
        default=os.getenv("V2_H2L_REQUIRE_RISK_GATE", "1").strip().lower()
        in {"1", "true", "yes", "on"},
        help="include paired forward Sortino/CVaR non-regression diagnostics",
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
        help="legacy compatibility value; ignored by the paired diagnostic",
    )
    p.add_argument("--cache-path", default=DEFAULT_HELDOUT_CACHE)
    p.add_argument("--rebuild-cache", action="store_true")
    p.add_argument(
        "--confirm",
        action="store_true",
        help=f"fail closed with {LEGACY_H2L_MUTATION_BLOCKER}",
    )
    p.add_argument("--output", default=None)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols  # noqa: PLC0415

    args = parse_args(argv)
    if args.confirm:
        report = run_h2l(
            offline_dir=args.offline_dir,
            live_dir=args.live_dir,
            rows=[],
            excluded_rows=[],
            min_improvement=args.min_improvement,
            confirm=True,
            require_risk_gate=bool(args.require_risk_gate),
            min_sortino=float(args.min_sortino),
            max_cvar_loss_bps=args.max_cvar_loss_bps,
        )
        print(json.dumps(report, indent=2, default=str))
        return 0
    rows, excluded_rows, load_meta = load_h2l_heldout_examples(
        symbols=resolve_symbols(explicit=args.symbols, smoke_test=args.smoke_test),
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
