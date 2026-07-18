"""GPU-fast per-cycle policy backtest over labeled replay examples.

Every trainer cycle already holds thousands of trusted archive rows whose
future outcome (``label_expected_move_after_cost_bps``) is known. A single
batched forward pass of the CURRENT policy over those rows yields an instant
backtest: directional accuracy, simulated after-cost expectancy, a profit-
factor proxy, per-bucket breakdowns, and a confidence-calibration curve.

Hard truth contract: backtest results are TRAINING/READINESS evidence only.
They never count as A+ evidence, never mark rows live-ready, and never touch
any gate. The A+ path still requires real paper closes through the 5-trade
evidence gate.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Any, Sequence

from .config import ACTION_INDEX, ACTION_LABELS

BACKTEST_SCHEMA_VERSION = "v2_trainer_policy_backtest_report_v1"
BACKTEST_MAX_ROWS = 16_384
_LONG_INDEX = ACTION_INDEX["long"]
_SHORT_INDEX = ACTION_INDEX["short"]


def _example_identity(example: Any) -> str:
    tensor = getattr(example, "tensor", None)
    material = {
        "symbol": getattr(example, "symbol", None),
        "timeframe": getattr(example, "timeframe", None),
        "tensor_id": getattr(tensor, "tensor_id", None),
        "feature_snapshot_id": getattr(tensor, "feature_snapshot_id", None),
        "decision_time": getattr(example, "decision_time", None),
        "label_available_at": getattr(example, "label_available_at", None),
        "label_expected_move_after_cost_bps": getattr(
            example,
            "label_expected_move_after_cost_bps",
            None,
        ),
    }
    return hashlib.sha256(
        json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _strict_finite_row(example: Any) -> bool:
    label = getattr(example, "label_expected_move_after_cost_bps", None)
    if label is None or isinstance(label, bool):
        return False
    try:
        label_value = float(label)
    except (TypeError, ValueError, OverflowError):
        return False
    tensor = getattr(example, "tensor", None)
    vector = getattr(tensor, "model_vector", None)
    if not math.isfinite(label_value) or not isinstance(vector, (list, tuple)) or not vector:
        return False
    for value in vector:
        if isinstance(value, bool):
            return False
        try:
            numeric = float(value)
        except (TypeError, ValueError, OverflowError):
            return False
        if not math.isfinite(numeric):
            return False
    return True


def _bucket_stats(bucket: dict[str, Any]) -> dict[str, Any]:
    trades = bucket["trades"]
    wins = bucket["wins"]
    gross_win = bucket["gross_win_bps"]
    gross_loss = bucket["gross_loss_bps"]
    return {
        "rows": bucket["rows"],
        "trades": trades,
        "win_rate": round(wins / trades, 6) if trades else None,
        "expectancy_bps": round(bucket["net_bps"] / trades, 6) if trades else None,
        "profit_factor_proxy": (
            round(gross_win / gross_loss, 6) if gross_loss > 0 else (None if gross_win == 0 else float("inf"))
        ),
    }


def run_policy_archive_backtest(
    *,
    model: Any,
    examples: Sequence[Any],
    excluded_training_examples: Sequence[Any] = (),
    untouched_forward_partition_proven: bool = False,
    max_rows: int = BACKTEST_MAX_ROWS,
) -> dict[str, Any]:
    """Evaluate only an untouched, PIT-proven forward partition.

    This remains diagnostic evidence. It cannot grant runtime, A+, paper, or
    live readiness and refuses in-sample, missing-label, or nonfinite rows.
    """
    started = time.perf_counter()
    rows = list(examples)[: max(1, int(max_rows))]
    base: dict[str, Any] = {
        "schema_version": BACKTEST_SCHEMA_VERSION,
        "rows_evaluated": 0,
        "backtest_rows_per_second": None,
        "counts_as_A_plus": False,
        "counts_as_live_ready": False,
        "evidence_class": "NO_EVIDENCE_UNTOUCHED_FORWARD_PARTITION_UNPROVEN",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    if untouched_forward_partition_proven is not True:
        base["status"] = "BLOCKED_UNTOUCHED_FORWARD_PARTITION_NOT_PROVEN"
        return base
    training_identities = {
        _example_identity(example) for example in excluded_training_examples
    }
    row_identities = [_example_identity(example) for example in rows]
    overlap = sorted(set(row_identities).intersection(training_identities))
    if overlap or len(row_identities) != len(set(row_identities)):
        base.update(
            {
                "status": "BLOCKED_FORWARD_PARTITION_IDENTITY_OVERLAP",
                "partition_overlap_count": len(overlap),
                "duplicate_forward_row_count": len(row_identities)
                - len(set(row_identities)),
            }
        )
        return base
    invalid_rows = sum(1 for example in rows if not _strict_finite_row(example))
    if invalid_rows:
        base.update(
            {
                "status": "BLOCKED_INVALID_FORWARD_ROW",
                "invalid_forward_row_count": invalid_rows,
            }
        )
        return base
    if not rows or not getattr(model, "torch_available", False):
        base["status"] = "NO_ROWS_OR_TORCH_UNAVAILABLE"
        return base
    torch = model.torch
    net = model.net
    device = model.device
    try:
        vectors = [list(example.tensor.model_vector) for example in rows]
        labels_bps = [float(example.label_expected_move_after_cost_bps) for example in rows]
        x = torch.tensor(vectors, dtype=torch.float32, device=device)
        was_training = net.training
        net.eval()
        with torch.no_grad():
            out = net(x)
            logits = out["logits"] if isinstance(out, dict) else out[0]
            probs = torch.softmax(logits, dim=-1)
            confidence, actions = probs.max(dim=-1)
        if was_training:
            net.train()
        actions_list = actions.detach().cpu().tolist()
        confidence_list = confidence.detach().cpu().tolist()
    except Exception as exc:
        base["status"] = f"BACKTEST_FORWARD_FAILED:{type(exc).__name__}"
        return base

    total_trades = 0
    wins = 0
    net_bps = 0.0
    gross_win = 0.0
    gross_loss = 0.0
    action_counts: dict[str, int] = {label: 0 for label in ACTION_LABELS}
    buckets: dict[str, dict[str, Any]] = {}
    calibration_bins: list[dict[str, Any]] = [
        {"bin": f"{lo / 10:.1f}-{(lo + 1) / 10:.1f}", "trades": 0, "wins": 0}
        for lo in range(10)
    ]
    for example, action_index, conf, realized_bps in zip(rows, actions_list, confidence_list, labels_bps):
        action_label = ACTION_LABELS[int(action_index)] if 0 <= int(action_index) < len(ACTION_LABELS) else "hold"
        action_counts[action_label] = action_counts.get(action_label, 0) + 1
        for key in (f"timeframe:{example.timeframe}", f"action:{action_label}"):
            bucket = buckets.setdefault(
                key, {"rows": 0, "trades": 0, "wins": 0, "net_bps": 0.0, "gross_win_bps": 0.0, "gross_loss_bps": 0.0}
            )
            bucket["rows"] += 1
        if int(action_index) == _LONG_INDEX:
            trade_bps = realized_bps
        elif int(action_index) == _SHORT_INDEX:
            trade_bps = -realized_bps
        else:
            continue
        total_trades += 1
        net_bps += trade_bps
        if trade_bps > 0:
            wins += 1
            gross_win += trade_bps
        else:
            gross_loss += -trade_bps
        bin_index = min(9, max(0, int(float(conf) * 10)))
        calibration_bins[bin_index]["trades"] += 1
        if trade_bps > 0:
            calibration_bins[bin_index]["wins"] += 1
        for key in (f"timeframe:{example.timeframe}", f"action:{action_label}"):
            bucket = buckets[key]
            bucket["trades"] += 1
            bucket["net_bps"] += trade_bps
            if trade_bps > 0:
                bucket["wins"] += 1
                bucket["gross_win_bps"] += trade_bps
            else:
                bucket["gross_loss_bps"] += -trade_bps

    elapsed = max(1e-9, time.perf_counter() - started)
    for entry in calibration_bins:
        entry["win_rate"] = round(entry["wins"] / entry["trades"], 6) if entry["trades"] else None
    profit_factor = round(gross_win / gross_loss, 6) if gross_loss > 0 else (None if gross_win == 0 else float("inf"))
    expectancy = round(net_bps / total_trades, 6) if total_trades else None
    win_rate = round(wins / total_trades, 6) if total_trades else None
    leverage_margin_study = {
        "status": "NOT_EVALUATED_MISSING_EVIDENCE_BOUND_PAPER_RISK_INPUTS",
        "fictional_stop_equity_notional_inputs_used": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    base.update(
        {
            "status": "OK_UNTOUCHED_FORWARD_DIAGNOSTIC_ONLY",
            "evidence_class": "UNTOUCHED_FORWARD_DIAGNOSTIC_NOT_READINESS",
            "untouched_forward_partition_proven": True,
            "forward_partition_digest": hashlib.sha256(
                "".join(row_identities).encode("ascii")
            ).hexdigest(),
            "excluded_training_identity_count": len(training_identities),
            "partition_overlap_count": 0,
            "leverage_margin_exploration": leverage_margin_study,
            "rows_evaluated": len(rows),
            "backtest_rows_per_second": round(len(rows) / elapsed, 3),
            "backtest_elapsed_ms": round(elapsed * 1000.0, 3),
            "directional_trades": total_trades,
            "hold_or_non_directional_rows": len(rows) - total_trades,
            "win_rate": win_rate,
            "expectancy_after_cost_bps": expectancy,
            "profit_factor_proxy": profit_factor,
            "action_distribution": action_counts,
            "confidence_calibration_bins": calibration_bins,
            "bucket_breakdown": {key: _bucket_stats(bucket) for key, bucket in sorted(buckets.items())},
            "a_plus_readiness_signal": False,
            "a_plus_readiness_note": (
                "untouched forward diagnostics never count as A+ or runtime readiness; "
                "real paper outcomes and canonical runtime evidence remain mandatory"
            ),
        }
    )
    return base
