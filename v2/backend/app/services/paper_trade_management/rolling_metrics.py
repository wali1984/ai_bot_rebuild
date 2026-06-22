"""Rolling paper trade metrics with strict closed-label vs open-MTM separation.

Core invariant:
    Closed-label win rate and open mark-to-market accuracy are DIFFERENT metrics
    and must NEVER be combined. A position that is profitable on an open MTM basis
    is NOT a winner until it closes with realized_pnl_usd > 0 (net of fees).

    closed_label_win_rate  = count(outcome_labels.winner=True) / count(outcome_labels)
    open_mtm_hit_rate      = count(open_positions.unrealized_pnl > 0) / count(open_positions)

    These are logged separately and must not be summed or averaged.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def _confidence_interval_95(wins: int, n: int) -> tuple[float, float]:
    """Wilson score 95% confidence interval for a proportion."""
    if n == 0:
        return (0.0, 1.0)
    z = 1.96
    p = wins / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (max(0.0, round(centre - margin, 4)), min(1.0, round(centre + margin, 4)))


def compute_rolling_closed_label_metrics(
    outcome_labels: list[dict[str, Any]],
    now_utc: datetime | None = None,
    window_hours: float = 3.0,
) -> dict[str, Any]:
    """Compute closed-label win rate, realized PnL, and confidence interval.

    Parameters
    ----------
    outcome_labels:
        List of outcome_label dicts from the paper ledger. Each must have
        ``winner`` (bool) and ``realized_pnl_usd`` (float) and optionally
        ``exit_time`` for window filtering.
    now_utc:
        Reference time for the rolling window. Defaults to UTC now.
    window_hours:
        Rolling window in hours (default 3).

    Returns
    -------
    dict with:
        window_hours, sample_count, win_count, loss_count, win_rate,
        realized_pnl_usd_sum, ci_95_low, ci_95_high, sufficient_sample,
        metric_source.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    cutoff_seconds = window_hours * 3600.0
    rows_in_window: list[dict[str, Any]] = []
    for row in outcome_labels:
        if not isinstance(row, dict):
            continue
        if row.get("winner") is None or _coerce_float(row.get("realized_pnl_usd")) is None:
            continue
        exit_time = _parse_utc(row.get("exit_time") or row.get("generated_utc") or "")
        if exit_time is not None:
            age_seconds = (now_utc - exit_time).total_seconds()
            if age_seconds > cutoff_seconds:
                continue
        rows_in_window.append(row)

    n = len(rows_in_window)
    wins = sum(1 for row in rows_in_window if row.get("winner") is True)
    losses = n - wins
    pnl_sum = sum(_coerce_float(row.get("realized_pnl_usd")) or 0.0 for row in rows_in_window)
    win_rate = wins / n if n > 0 else None
    ci_low, ci_high = _confidence_interval_95(wins, n)
    sufficient_sample = n >= 20

    return {
        "metric_type": "CLOSED_LABEL_WIN_RATE",
        "window_hours": window_hours,
        "sample_count": n,
        "win_count": wins,
        "loss_count": losses,
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
        "realized_pnl_usd_sum": round(pnl_sum, 6),
        "ci_95_low": ci_low,
        "ci_95_high": ci_high,
        "sufficient_sample": sufficient_sample,
        "sufficient_sample_threshold": 20,
        "metric_source": "V2_PAPER_CLOSED_TRADE_OUTCOME_LABELS",
        "note": "Win rate is based on net realized PnL after fees and slippage. Open MTM not included.",
    }


def compute_open_mtm_hit_rate(
    open_positions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute directional accuracy on currently open positions (mark-to-market).

    This is NOT win rate. It measures whether open positions are currently
    moving in the predicted direction. A position can switch between positive
    and negative MTM before closing — this metric does NOT predict final outcome.
    """
    positions = [row for row in open_positions if isinstance(row, dict)]
    n = len(positions)
    in_favor = 0
    for row in positions:
        pnl = _coerce_float(row.get("unrealized_pnl") or row.get("unrealized_pnl_bps"))
        if pnl is not None and pnl > 0:
            in_favor += 1
    hit_rate = in_favor / n if n > 0 else None

    return {
        "metric_type": "OPEN_MTM_DIRECTIONAL_HIT_RATE",
        "open_position_count": n,
        "in_favor_count": in_favor,
        "hit_rate": round(hit_rate, 4) if hit_rate is not None else None,
        "metric_source": "V2_PAPER_OPEN_POSITIONS_CURRENT_MTM",
        "warning": "This is NOT a closed-label win rate. Open positions can reverse before close.",
        "must_not_mix_with_closed_label_win_rate": True,
    }


def compute_pnl_reconciliation(
    closed_trades: list[dict[str, Any]],
    outcome_labels: list[dict[str, Any]],
    open_positions: list[dict[str, Any]],
) -> dict[str, Any]:
    """Reconcile PnL sources across the paper ledger.

    Rule: sum(closed_trades.realized_pnl_usd) must equal sum(outcome_labels.realized_pnl_usd).
    Open position unrealized PnL is accounted separately and never added to realized.
    """
    closed_sum = sum(
        _coerce_float(row.get("realized_pnl_usd") or row.get("realized_pnl_usdt")) or 0.0
        for row in closed_trades
        if isinstance(row, dict)
    )
    outcome_sum = sum(
        _coerce_float(row.get("realized_pnl_usd") or row.get("realized_pnl")) or 0.0
        for row in outcome_labels
        if isinstance(row, dict)
    )
    unrealized_sum = sum(
        _coerce_float(row.get("unrealized_pnl")) or 0.0
        for row in open_positions
        if isinstance(row, dict)
    )
    delta = abs(closed_sum - outcome_sum)
    reconciled = delta < 0.01  # within $0.01 floating-point tolerance

    return {
        "portfolio_closed_pnl_usd": round(closed_sum, 6),
        "outcome_label_pnl_usd": round(outcome_sum, 6),
        "open_mtm_unrealized_pnl_usd": round(unrealized_sum, 6),
        "delta_closed_vs_outcome": round(delta, 6),
        "reconciled": reconciled,
        "total_equity_change_realized_only": round(closed_sum, 6),
        "note": "Unrealized PnL is separate and must not be added to realized for performance reporting.",
    }


def build_rolling_metrics_report(
    outcome_labels: list[dict[str, Any]],
    open_positions: list[dict[str, Any]],
    closed_trades: list[dict[str, Any]],
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Build the full rolling metrics report for the operator dashboard."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    metrics_1h = compute_rolling_closed_label_metrics(outcome_labels, now_utc=now_utc, window_hours=1.0)
    metrics_3h = compute_rolling_closed_label_metrics(outcome_labels, now_utc=now_utc, window_hours=3.0)
    metrics_12h = compute_rolling_closed_label_metrics(outcome_labels, now_utc=now_utc, window_hours=12.0)
    open_mtm = compute_open_mtm_hit_rate(open_positions)
    reconciliation = compute_pnl_reconciliation(closed_trades, outcome_labels, open_positions)

    return {
        "generated_utc": now_utc.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "closed_label_metrics_1h": metrics_1h,
        "closed_label_metrics_3h": metrics_3h,
        "closed_label_metrics_12h": metrics_12h,
        "open_mtm_metrics": open_mtm,
        "pnl_reconciliation": reconciliation,
        "separation_enforced": True,
        "paper_only": True,
        "places_real_order": False,
        "live_gate": "blocked_human_only",
    }
