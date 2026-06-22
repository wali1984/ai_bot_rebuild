from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        out = float(value)
        return out if out == out and out not in (float("inf"), float("-inf")) else None
    if isinstance(value, str):
        try:
            out = float(value)
        except (TypeError, ValueError):
            return None
        return out if out == out and out not in (float("inf"), float("-inf")) else None
    return None


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _row_pnl(row: Mapping[str, Any]) -> float | None:
    return _coerce_float(
        row.get("realized_pnl_usdt")
        if row.get("realized_pnl_usdt") is not None
        else row.get("realized_pnl_bps")
    )


def _aggregate(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [row for row in rows if isinstance(row, Mapping)]
    pnls = [_row_pnl(row) for row in rows]
    realized = [pnl for pnl in pnls if pnl is not None]
    wins = [pnl for pnl in realized if pnl > 0]
    losses = [pnl for pnl in realized if pnl < 0]
    fees = [_coerce_float(row.get("fees_usdt") if row.get("fees_usdt") is not None else row.get("fee_bps")) for row in rows]
    slippage = [_coerce_float(row.get("slippage_bps")) for row in rows]
    drawdowns = [_coerce_float(row.get("drawdown_bps")) for row in rows]
    blocked = [
        row
        for row in rows
        if row.get("strategy_router_block_reason")
        or row.get("strategy_selected_mode") == "no_trade_mode"
        or row.get("decision") in {"HELD_BY_PAPER_FILL_GATE", "SHADOW_OBSERVATION_ONLY"}
    ]
    disagreement = [
        row
        for row in rows
        if "MODEL_DISAGREEMENT" in _as_list(row.get("strategy_regime_labels"))
    ]
    data_quality_block = [
        row
        for row in rows
        if "DATA_UNRELIABLE" in _as_list(row.get("strategy_regime_labels"))
        or str(row.get("strategy_router_block_reason") or "").startswith("DATA_QUALITY")
    ]
    total_realized_loss = abs(sum(losses))
    profit_factor = None
    if wins and losses:
        profit_factor = sum(wins) / total_realized_loss if total_realized_loss > 0 else None
    elif wins and not losses:
        profit_factor = None
    return {
        "trade_count": len(rows),
        "win_rate": (len(wins) / len(realized)) if realized else None,
        "profit_factor": profit_factor,
        "expectancy": (sum(realized) / len(realized)) if realized else None,
        "average_win": (sum(wins) / len(wins)) if wins else None,
        "average_loss": (sum(losses) / len(losses)) if losses else None,
        "max_drawdown": max((value for value in drawdowns if value is not None), default=None),
        "fees": sum(value for value in fees if value is not None),
        "slippage": sum(value for value in slippage if value is not None),
        "blocked_trades": len(blocked),
        "masa_ppo_disagreement_rate": (len(disagreement) / len(rows)) if rows else 0.0,
        "data_quality_block_rate": (len(data_quality_block) / len(rows)) if rows else 0.0,
    }


def summarize_strategy_router_performance(
    *,
    accepted_rows: Iterable[Mapping[str, Any]],
    blocked_rows: Iterable[Mapping[str, Any]],
    shadow_rows: Iterable[Mapping[str, Any]],
    held_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    all_rows = [
        *(row for row in accepted_rows if isinstance(row, Mapping)),
        *(row for row in blocked_rows if isinstance(row, Mapping)),
        *(row for row in shadow_rows if isinstance(row, Mapping)),
        *(row for row in held_rows if isinstance(row, Mapping)),
    ]
    by_mode: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    by_regime: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in all_rows:
        mode = str(row.get("strategy_selected_mode") or "unclassified")
        by_mode[mode].append(row)
        labels = _as_list(row.get("strategy_regime_labels")) or ["UNLABELED"]
        for label in labels:
            by_regime[str(label)].append(row)
    return {
        "schema_version": "v2_strategy_router_report_v1",
        "total_rows": len(all_rows),
        "mode_counts": {mode: len(rows) for mode, rows in sorted(by_mode.items())},
        "regime_counts": {label: len(rows) for label, rows in sorted(by_regime.items())},
        "by_mode": {mode: _aggregate(rows) for mode, rows in sorted(by_mode.items())},
        "by_regime": {label: _aggregate(rows) for label, rows in sorted(by_regime.items())},
        "blocked_trade_count": sum(
            1 for row in all_rows if row.get("strategy_router_block_reason")
        ),
        "data_quality_block_count": sum(
            1
            for row in all_rows
            if "DATA_UNRELIABLE" in _as_list(row.get("strategy_regime_labels"))
            or str(row.get("strategy_router_block_reason") or "").startswith("DATA_QUALITY")
        ),
        "masa_ppo_disagreement_count": sum(
            1 for row in all_rows if "MODEL_DISAGREEMENT" in _as_list(row.get("strategy_regime_labels"))
        ),
    }
