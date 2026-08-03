"""B6: replay status route.

Reads `replay:last_run:*` Redis keys to surface the most recent bounded
replay's marker. Never invokes the replay runner, never mutates any key.

Shape:
{ last_run: str|None, idempotent_hash: str|None, bounded_events_count: int|None }
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from app.api.v2._common import get_redis

router = APIRouter(prefix="/replay", tags=["v2-landing"])


def _empty() -> dict[str, Any]:
    return {
        "last_run": None,
        "idempotent_hash": None,
        "bounded_events_count": None,
    }


def _coerce_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _merge_from_json(out: dict[str, Any], raw: Any) -> bool:
    """Update `out` in-place from a JSON-encoded value. Returns True if any
    field was populated.
    """
    if not isinstance(raw, str):
        return False
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    found = False
    if data.get("last_run") not in (None, ""):
        out["last_run"] = data["last_run"]
        found = True
    if data.get("idempotent_hash") not in (None, ""):
        out["idempotent_hash"] = data["idempotent_hash"]
        found = True
    if data.get("bounded_events_count") is not None:
        coerced = _coerce_int(data["bounded_events_count"])
        if coerced is not None:
            out["bounded_events_count"] = coerced
            found = True
    return found


def _read_json(r: Any, key: str) -> dict[str, Any]:
    try:
        raw = r.get(key)
    except Exception:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        data = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


@router.get("/backtest")
async def get_backtest_results() -> dict[str, Any]:
    """Realtime backtest + replay-feedback results for the web/iOS display.

    Read-only. Surfaces the trainer's in-cycle policy backtest, the out-of-sample
    generalization signal (validation loss + overfit gap), and the continuous
    replay -> trainer feedback so the operator can see whether backtest edge is
    holding up out-of-sample. Backtest is explicitly NOT A+/live evidence.
    """
    out: dict[str, Any] = {
        "available": False,
        "generated_utc": None,
        "policy_backtest": None,
        "generalization": None,
        "replay_feedback": None,
        "continuous_replay_active": None,
        "effective_trainer_mode": None,
        "replay_examples_built": None,
        "backtest_is_a_plus_evidence": False,
    }
    r = get_redis()
    if r is None:
        return out

    trainer = _read_json(r, "v2:trainer:hybrid_cuda:status")
    if trainer:
        out["generated_utc"] = trainer.get("generated_utc")
        out["effective_trainer_mode"] = trainer.get("effective_trainer_mode")
        out["replay_examples_built"] = trainer.get("trusted_replay_examples_built")
        util = trainer.get("cuda_cpu_resource_utilization")
        pb = util.get("policy_backtest") if isinstance(util, dict) else None
        if isinstance(pb, dict):
            out["available"] = True
            out["policy_backtest"] = {
                "win_rate": pb.get("win_rate"),
                "profit_factor_proxy": pb.get("profit_factor_proxy"),
                "expectancy_after_cost_bps": pb.get("expectancy_after_cost_bps"),
                "rows_evaluated": pb.get("rows_evaluated"),
                "status": pb.get("status"),
                "evidence_class": pb.get("evidence_class"),
            }
        lm = trainer.get("learning_metrics")
        if isinstance(lm, dict):
            out["generalization"] = {
                "validation_supervised_loss": lm.get("validation_supervised_loss"),
                "validation_rows_evaluated": lm.get("validation_rows_evaluated"),
                "train_val_generalization_gap": lm.get("train_val_generalization_gap"),
                "overfit_gap_warning": lm.get("overfit_gap_warning"),
                "loss_before": lm.get("loss_before"),
                "loss_after": lm.get("loss_after"),
            }

    cf = _read_json(r, "v2:trainer:feedback:counterfactual_status")
    if cf:
        out["replay_feedback"] = {
            "existing_counterfactual_rows": cf.get("existing_counterfactual_rows"),
            "new_matured_rows": cf.get("new_matured_rows"),
            "pending_rows": cf.get("pending_rows"),
            "trainer_loader_consumes": cf.get("trainer_loader_consumes_counterfactual_key"),
        }

    ef = _read_json(r, "v2:edge_factory:replay_status")
    if ef:
        out["continuous_replay_active"] = True
        out["edge_factory_replay_status"] = {
            "status": ef.get("status"),
            "generated_utc": ef.get("generated_utc"),
            "replay_windows_processed": ef.get("replay_windows_processed") or ef.get("windows_processed"),
            "snapshots_scanned": ef.get("snapshots_scanned"),
        }

    return out


@router.get("/status")
async def get_replay_status() -> dict[str, Any]:
    r = get_redis()
    out = _empty()
    if r is None:
        return out

    # Aggregate JSON keys first.
    json_candidates = (
        "replay:last_run",
        "replay:last_run:latest",
        "replay:last_run:summary",
        "v2:replay:last_run",
    )
    for key in json_candidates:
        try:
            raw = r.get(key)
        except Exception:
            raw = None
        if raw is not None:
            _merge_from_json(out, raw)

    # Discrete keys override (or fill) individual fields.
    discrete = (
        ("replay:last_run:id", "last_run"),
        ("replay:last_run:ts", "last_run"),
        ("replay:last_run:hash", "idempotent_hash"),
        ("replay:last_run:idempotent_hash", "idempotent_hash"),
        ("replay:last_run:events_count", "bounded_events_count"),
        ("replay:last_run:bounded_events_count", "bounded_events_count"),
    )
    for key, field in discrete:
        try:
            raw = r.get(key)
        except Exception:
            raw = None
        if raw is None:
            continue
        if field == "bounded_events_count":
            coerced = _coerce_int(raw)
            if coerced is not None:
                out[field] = coerced
        else:
            out[field] = raw

    return out
