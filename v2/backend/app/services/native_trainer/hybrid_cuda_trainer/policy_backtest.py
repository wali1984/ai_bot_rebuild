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

import time
from typing import Any, Sequence

from .config import ACTION_INDEX, ACTION_LABELS

BACKTEST_SCHEMA_VERSION = "v2_trainer_policy_backtest_report_v1"
BACKTEST_MAX_ROWS = 16_384
_LONG_INDEX = ACTION_INDEX["long"]
_SHORT_INDEX = ACTION_INDEX["short"]


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
    max_rows: int = BACKTEST_MAX_ROWS,
) -> dict[str, Any]:
    """Batched forward pass of the current policy against labeled outcomes."""
    started = time.perf_counter()
    rows = list(examples)[: max(1, int(max_rows))]
    base: dict[str, Any] = {
        "schema_version": BACKTEST_SCHEMA_VERSION,
        "rows_evaluated": 0,
        "backtest_rows_per_second": None,
        "counts_as_A_plus": False,
        "counts_as_live_ready": False,
        "evidence_class": "BACKTEST_ONLY_NOT_A_PLUS_EVIDENCE",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    if not rows or not getattr(model, "torch_available", False):
        base["status"] = "NO_ROWS_OR_TORCH_UNAVAILABLE"
        return base
    torch = model.torch
    net = model.net
    device = model.device
    try:
        vectors = [list(example.tensor.model_vector) for example in rows]
        labels_bps = [float(example.label_expected_move_after_cost_bps or 0.0) for example in rows]
        x = torch.tensor(vectors, dtype=torch.float32, device=device)
        x = torch.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
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
    # Leverage/margin exploration (study-only): at the backtest's observed
    # after-cost edge, score a leverage grid x margin modes so the trainer keeps
    # a per-cycle signal of which risk-adjusted leverage/margin profile is best.
    # Never routes to live; leverage here is a studied variable, not an order.
    from .leverage_margin_exploration import evaluate_leverage_margin_grid

    leverage_margin_study = evaluate_leverage_margin_grid(
        {
            "expected_move_after_cost_bps": expectancy,
            "stop_distance_bps": 25.0,
            "equity_usd": 200.0,
            "notional_usd": 60.0,
        }
    )
    base.update(
        {
            "status": "OK",
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
            "a_plus_readiness_signal": bool(
                total_trades >= 100
                and (profit_factor or 0) not in (None,)
                and isinstance(profit_factor, (int, float))
                and profit_factor > 1.2
                and (expectancy or 0) > 0
                and (win_rate or 0) > 0.5
            ),
            "a_plus_readiness_note": (
                "readiness signal is a backtest heuristic over labeled archive rows; "
                "A+ grade itself requires real paper closes through the 5-trade gate"
            ),
        }
    )
    return base
