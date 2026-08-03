"""Continuous hourly paper trading monitor.

Reads paper_events.jsonl and computes windowed statistics for 7 hourly artifacts.
Uses only closed, in-memory, point-in-time safe data — no future labels.

Phase 3-10 wiring sprint companion: provides the evidence layer that loss_recovery.py
uses to tighten gates when a window is losing.

No exchange mutation. No legacy Redis writes. No live orders.
Live gate: blocked_human_only.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "v2_hourly_monitor_v1"
LIVE_GATE = "blocked_human_only"


def _parse_ts(value: Any) -> float | None:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.timestamp()
    except Exception:  # noqa: BLE001
        return None


def _coerce(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _load_events(jsonl_path: Path, since_ts: float | None = None, until_ts: float | None = None) -> list[dict]:
    events = []
    try:
        with jsonl_path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    ev = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                ts = _parse_ts(ev.get("generated_at"))
                if since_ts is not None and ts is not None and ts < since_ts:
                    continue
                if until_ts is not None and ts is not None and ts > until_ts:
                    continue
                events.append(ev)
    except OSError:
        pass
    return events


def compute_paper_pnl_window(events: list[dict]) -> dict[str, Any]:
    """Compute PnL and trade stats for a window of paper events."""
    fills = [e for e in events if e.get("paper_result") == "FILLED_PAPER_ONLY"]
    closed = [e for e in events if e.get("paper_result") == "POSITION_CLOSED_PAPER_ONLY"]
    held = [e for e in events if e.get("paper_result") == "POSITION_HELD_PAPER_ONLY"]
    blocked = [e for e in events if e.get("paper_result") == "NO_FILL_RISK_BLOCKED"]

    # P&L from closed trades
    realized_pnl = sum(_coerce(e.get("realized_delta_usdt")) for e in closed if e.get("realized_delta_usdt") is not None)
    unrealized_pnl = sum(_coerce(e.get("unrealized_pnl_usdt")) for e in held if e.get("unrealized_pnl_usdt") is not None)

    # Win/loss
    wins = [e for e in closed if _coerce(e.get("realized_delta_usdt")) > 0]
    losses = [e for e in closed if _coerce(e.get("realized_delta_usdt")) < 0]
    win_rate = len(wins) / len(closed) if closed else None

    win_bps_list = [_coerce(e.get("current_return_bps")) for e in wins if e.get("current_return_bps") is not None]
    loss_bps_list = [abs(_coerce(e.get("current_return_bps"))) for e in losses if e.get("current_return_bps") is not None]
    avg_win_bps = sum(win_bps_list) / len(win_bps_list) if win_bps_list else None
    avg_loss_bps = sum(loss_bps_list) / len(loss_bps_list) if loss_bps_list else None

    total_gain = sum(_coerce(e.get("realized_delta_usdt")) for e in wins)
    total_loss = abs(sum(_coerce(e.get("realized_delta_usdt")) for e in losses))
    profit_factor = total_gain / total_loss if total_loss > 0 else None

    pnl_series = [_coerce(e.get("realized_delta_usdt")) for e in closed if e.get("realized_delta_usdt") is not None]
    cumulative = 0.0
    peak = 0.0
    max_dd_usdt = 0.0
    for p in pnl_series:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd_usdt:
            max_dd_usdt = dd

    symbol_counts: dict[str, int] = {}
    tf_counts: dict[str, int] = {}
    strategy_counts: dict[str, int] = {}
    long_count = 0
    short_count = 0
    for e in fills + closed:
        sym = str(e.get("symbol") or "unknown")
        symbol_counts[sym] = symbol_counts.get(sym, 0) + 1
        tf = str(e.get("timeframe") or "unknown")
        tf_counts[tf] = tf_counts.get(tf, 0) + 1
        strategy = str(e.get("strategy_family") or e.get("trainer_source") or "unknown")
        strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
        side = str(e.get("paper_action") or e.get("ledger_action") or "").lower()
        if "long" in side or e.get("side") == "long":
            long_count += 1
        elif "short" in side or e.get("side") == "short":
            short_count += 1

    block_reasons = Counter(e.get("risk_reason_code") or "unknown" for e in blocked)
    top_block_reasons = [{"reason": r, "count": c} for r, c in block_reasons.most_common(10)]

    exit_reasons = Counter(e.get("exit_reason") or "none" for e in closed)

    return {
        "fill_count": len(fills),
        "closed_trade_count": len(closed),
        "open_position_count": 1 if held else 0,
        "blocked_count": len(blocked),
        "paper_realized_pnl": round(realized_pnl, 6),
        "paper_unrealized_pnl": round(unrealized_pnl, 6),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "average_win_bps": round(avg_win_bps, 2) if avg_win_bps is not None else None,
        "average_loss_bps": round(avg_loss_bps, 2) if avg_loss_bps is not None else None,
        "max_drawdown_usdt": round(max_dd_usdt, 6),
        "trade_count_by_symbol": symbol_counts,
        "trade_count_by_timeframe": tf_counts,
        "trade_count_by_strategy": strategy_counts,
        "long_count": long_count,
        "short_count": short_count,
        "long_short_ratio": round(long_count / max(short_count, 1), 3),
        "top_block_reasons": top_block_reasons,
        "exit_reason_counts": dict(exit_reasons),
        "live_mutation_count_must_be_zero": 0,
    }


def compute_prediction_accuracy_window(events: list[dict]) -> dict[str, Any]:
    """Compute prediction accuracy stats for a window."""
    filled = [e for e in events if e.get("paper_result") == "FILLED_PAPER_ONLY"]
    closed = [e for e in events if e.get("paper_result") == "POSITION_CLOSED_PAPER_ONLY"]

    stale_count = sum(1 for e in filled if str(e.get("feature_freshness_state") or "").lower() not in ("current", "warn"))
    missing_critical = sum(1 for e in filled if e.get("missing_feature_flags") and len(e.get("missing_feature_flags") or []) > 5)

    # Accuracy by direction
    correct_long = correct_short = total_long = total_short = 0
    for e in closed:
        action = str(e.get("paper_action") or "").lower()
        pnl = _coerce(e.get("realized_delta_usdt"))
        if "long" in action:
            total_long += 1
            if pnl > 0:
                correct_long += 1
        elif "short" in action:
            total_short += 1
            if pnl > 0:
                correct_short += 1

    acc_by_direction = {
        "long": {"total": total_long, "correct": correct_long, "accuracy": round(correct_long / total_long, 4) if total_long else None},
        "short": {"total": total_short, "correct": correct_short, "accuracy": round(correct_short / total_short, 4) if total_short else None},
    }

    # Accuracy by symbol+TF
    sym_tf_results: dict[str, dict] = {}
    for e in closed:
        sym = str(e.get("symbol") or "unknown")
        tf = str(e.get("timeframe") or "unknown")
        key = f"{sym}:{tf}"
        if key not in sym_tf_results:
            sym_tf_results[key] = {"total": 0, "correct": 0}
        sym_tf_results[key]["total"] += 1
        if _coerce(e.get("realized_delta_usdt")) > 0:
            sym_tf_results[key]["correct"] += 1

    acc_by_sym_tf = {
        k: {
            **v,
            "accuracy": round(v["correct"] / v["total"], 4) if v["total"] else None,
        }
        for k, v in sym_tf_results.items()
    }

    return {
        "total_predictions_in_window": len(filled) + len(events) - len(filled),
        "filled_count": len(filled),
        "closed_count": len(closed),
        "stale_prediction_rows": stale_count,
        "missing_critical_feature_rows": missing_critical,
        "prediction_accuracy_by_direction": acc_by_direction,
        "prediction_accuracy_by_symbol_tf": acc_by_sym_tf,
    }


def compute_orchestrator_window(events: list[dict]) -> dict[str, Any]:
    """Compute orchestrator decision quality for a window."""
    total = len(events)
    filled = sum(1 for e in events if e.get("paper_result") == "FILLED_PAPER_ONLY")
    blocked = sum(1 for e in events if e.get("paper_result") == "NO_FILL_RISK_BLOCKED")
    accept_rate = filled / total if total else None
    return {
        "total_decisions": total,
        "accepted_count": filled,
        "blocked_count": blocked,
        "orchestrator_accept_rate": round(accept_rate, 4) if accept_rate is not None else None,
    }


def compute_risk_window(events: list[dict]) -> dict[str, Any]:
    """Compute risk controller stats for a window."""
    blocked_events = [e for e in events if e.get("paper_result") == "NO_FILL_RISK_BLOCKED"]
    filled_events = [e for e in events if e.get("paper_result") == "FILLED_PAPER_ONLY"]
    total = len(events)
    risk_accept_rate = len(filled_events) / total if total else None
    block_reasons = Counter(e.get("risk_reason_code") or "unknown" for e in blocked_events)
    return {
        "total_evaluated": total,
        "risk_accepted": len(filled_events),
        "risk_blocked": len(blocked_events),
        "risk_accept_rate": round(risk_accept_rate, 4) if risk_accept_rate is not None else None,
        "block_reasons": {r: c for r, c in block_reasons.most_common(10)},
    }


def compute_hedge_exit_window(events: list[dict]) -> dict[str, Any]:
    """Compute hedge and exit stats for a window."""
    closed = [e for e in events if e.get("paper_result") == "POSITION_CLOSED_PAPER_ONLY"]
    exit_counts = Counter(str(e.get("exit_reason") or "none") for e in closed)
    return {
        "closed_count": len(closed),
        "exit_reason_counts": dict(exit_counts),
        "hedge_recommendations": 0,
        "hedge_accepts": 0,
        "hedge_blocks": 0,
        "hedge_note": "hedge_engine fail-closed until operator_paper_hedge_engine_approved=True",
    }


def compute_leverage_margin_window(events: list[dict]) -> dict[str, Any]:
    """Compute adaptive leverage/margin recommendation stats for a window."""
    filled = [e for e in events if e.get("paper_result") == "FILLED_PAPER_ONLY"]
    # leverage_recommendation is a dict emitted by recommend_leverage_for_signal
    lev_recs = sum(
        1 for e in filled
        if isinstance(e.get("leverage_recommendation"), dict) and e["leverage_recommendation"]
    )
    return {
        "fill_count": len(filled),
        "adaptive_leverage_recommendation_count": lev_recs,
        "adaptive_margin_recommendation_count": lev_recs,
        "live_mutation_count_must_be_zero": 0,
        "mutates_exchange": False,
    }


def build_hourly_artifacts(
    *,
    jsonl_path: Path,
    window_start: dt.datetime,
    window_end: dt.datetime,
) -> dict[str, dict]:
    """Build all 7 hourly artifacts for the given time window.

    Returns a dict of {artifact_name: payload}.
    """
    start_ts = window_start.timestamp()
    end_ts = window_end.timestamp()
    events = _load_events(jsonl_path, since_ts=start_ts, until_ts=end_ts)

    now_iso = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    window_start_iso = window_start.isoformat(timespec="seconds")
    window_end_iso = window_end.isoformat(timespec="seconds")

    pnl_stats = compute_paper_pnl_window(events)
    pred_stats = compute_prediction_accuracy_window(events)
    orch_stats = compute_orchestrator_window(events)
    risk_stats = compute_risk_window(events)
    hedge_stats = compute_hedge_exit_window(events)
    lev_stats = compute_leverage_margin_window(events)

    common = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso,
        "window_start_est": window_start_iso,
        "window_end_est": window_end_iso,
        "event_count_in_window": len(events),
        "live_gate": LIVE_GATE,
        "live_mutation_count_must_be_zero": 0,
        "mutates_exchange": False,
    }

    # trainer_feedback_consumed = closed trades in window (each triggers backfill_realized_outcome)
    # feedback_sent events are closed trades tagged by append_paper_event with feedback_sent=True
    _feedback_sent = sum(1 for e in events if e.get("feedback_sent") is True)
    _closed_count = pnl_stats["closed_trade_count"]
    trainer_feedback_consumed = _feedback_sent if _feedback_sent > 0 else _closed_count

    return {
        "trainer_hourly_status": {
            **common,
            "trainer_feedback_consumed": trainer_feedback_consumed,
            "trainer_feedback_quarantined": 0,
            "checkpoint_updates": 0,
            "stale_prediction_rows": pred_stats["stale_prediction_rows"],
            "missing_critical_feature_rows": pred_stats["missing_critical_feature_rows"],
            "prediction_count": pred_stats["filled_count"],
            "trainer_note": (
                "trainer_feedback_consumed = closed trades that triggered backfill_realized_outcome. "
                "Trainer is a protected ML runtime; consumes feedback on its own evaluation cycle."
            ),
        },
        "signal_prediction_hourly_accuracy": {
            **common,
            **pred_stats,
            "accepted_count": pnl_stats["fill_count"],
            "blocked_count": pnl_stats["blocked_count"],
            "top_block_reasons": pnl_stats["top_block_reasons"],
        },
        "orchestrator_hourly_decision_quality": {
            **common,
            **orch_stats,
        },
        "risk_controller_hourly_status": {
            **common,
            **risk_stats,
        },
        "paper_trader_hourly_pnl": {
            **common,
            **pnl_stats,
        },
        "hedge_exit_hourly_status": {
            **common,
            **hedge_stats,
        },
        "adaptive_action_leverage_margin_hourly_status": {
            **common,
            **lev_stats,
        },
    }


def build_cumulative_artifacts(*, jsonl_path: Path) -> dict[str, dict]:
    """Build artifacts for all available data (no time window filter)."""
    now = dt.datetime.now(dt.timezone.utc)
    far_past = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
    return build_hourly_artifacts(jsonl_path=jsonl_path, window_start=far_past, window_end=now)


def build_3h_window_artifacts(*, jsonl_path: Path, hours: int = 3) -> list[dict]:
    """Build artifacts for the last N consecutive 1-hour windows.

    Returns a list of hourly artifact dicts in chronological order.
    """
    now = dt.datetime.now(dt.timezone.utc)
    windows = []
    for i in range(hours, 0, -1):
        w_start = now - dt.timedelta(hours=i)
        w_end = now - dt.timedelta(hours=i - 1)
        artifacts = build_hourly_artifacts(jsonl_path=jsonl_path, window_start=w_start, window_end=w_end)
        windows.append({
            "window_index": hours - i,
            "window_start": w_start.isoformat(timespec="seconds"),
            "window_end": w_end.isoformat(timespec="seconds"),
            "artifacts": artifacts,
        })
    return windows


def is_window_losing(pnl_artifacts: dict) -> bool:
    """Return True if the paper_trader_hourly_pnl shows a losing window."""
    pnl = pnl_artifacts.get("paper_trader_hourly_pnl", {})
    realized = pnl.get("paper_realized_pnl", 0.0)
    win_rate = pnl.get("win_rate")
    closed = pnl.get("closed_trade_count", 0)
    if closed == 0:
        return False
    if realized < 0:
        return True
    if win_rate is not None and win_rate < 0.4:
        return True
    return False
