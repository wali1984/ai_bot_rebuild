"""Read-only major-move false-negative mining for Phase 3 recovery."""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Mapping


SCHEMA_VERSION = "phase3_major_move_false_negative_miner_v1"
MAJOR_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
DEFAULT_MAJOR_MOVE_BPS = 15.0


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _realized_bps(row: Mapping[str, Any]) -> float | None:
    for key in (
        "realized_after_cost_return_bps",
        "realized_net_pnl_bps",
        "realized_pnl_bps",
        "pnl_effect_bps",
    ):
        value = _float(row.get(key))
        if value is not None:
            return value
    outcome = _as_dict(_as_dict(row.get("outcome_windows")).get(row.get("primary_outcome_window") or "5m"))
    return _float(outcome.get("after_cost_return_bps"))


def _missed_side(row: Mapping[str, Any]) -> str:
    return str(row.get("counterfactual_side") or row.get("missed_side") or "").lower()


def _selected_action(row: Mapping[str, Any]) -> str:
    return str(row.get("selected_action") or row.get("action") or "unknown").lower()


def _is_false_negative(row: Mapping[str, Any]) -> bool:
    if row.get("false_negative") is True:
        return True
    return str(row.get("classification") or "").lower() == "false_negative"


def _is_major_move_false_negative(
    row: Mapping[str, Any],
    *,
    symbols: tuple[str, ...],
    min_after_cost_bps: float,
) -> bool:
    symbol = str(row.get("symbol") or "").upper()
    realized = _realized_bps(row)
    return (
        symbol in symbols
        and _is_false_negative(row)
        and realized is not None
        and realized >= min_after_cost_bps
    )


def _trim_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "prediction_id": row.get("prediction_id") or row.get("entry_prediction_id"),
        "symbol": str(row.get("symbol") or "").upper(),
        "timeframe": row.get("timeframe"),
        "selected_action": _selected_action(row),
        "counterfactual_side": _missed_side(row),
        "confidence_calibrated": row.get("confidence_calibrated"),
        "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
        "realized_after_cost_return_bps": _realized_bps(row),
        "classification": row.get("classification"),
        "paper_fill_gate_block_reasons": row.get("paper_fill_gate_block_reasons", []),
        "risk_reason": row.get("risk_reason"),
        "orchestrator_reason": row.get("orchestrator_reason"),
    }


def mine_major_move_false_negatives(
    rows: list[Mapping[str, Any]],
    *,
    major_symbols: tuple[str, ...] = MAJOR_SYMBOLS,
    min_after_cost_bps: float = DEFAULT_MAJOR_MOVE_BPS,
) -> dict[str, Any]:
    normalized = [_as_dict(row) for row in rows]
    major_symbols = tuple(symbol.upper() for symbol in major_symbols)
    completed = [row for row in normalized if _realized_bps(row) is not None]
    false_negatives = [row for row in completed if _is_false_negative(row)]
    major_missed = [
        row
        for row in false_negatives
        if _is_major_move_false_negative(
            row,
            symbols=major_symbols,
            min_after_cost_bps=min_after_cost_bps,
        )
    ]
    by_symbol = Counter(str(row.get("symbol") or "").upper() for row in major_missed)
    by_side = Counter(_missed_side(row) or "unknown" for row in major_missed)
    viable_side_counts: Counter[str] = Counter()
    for row in completed:
        side = _missed_side(row) or _selected_action(row)
        realized = _realized_bps(row)
        if side in {"long", "short"} and realized is not None and realized > 0.0:
            viable_side_counts[side] += 1
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "MAJOR_MOVE_FALSE_NEGATIVE_MINING_READY",
        "row_count": len(normalized),
        "completed_outcome_count": len(completed),
        "major_symbols": list(major_symbols),
        "min_after_cost_bps": min_after_cost_bps,
        "false_negative_count": len(false_negatives),
        "major_move_false_negative_count": len(major_missed),
        "by_symbol": dict(sorted(by_symbol.items())),
        "by_counterfactual_side": dict(sorted(by_side.items())),
        "mandatory_major_classified": {
            symbol: by_symbol.get(symbol, 0) > 0 for symbol in major_symbols
        },
        "long_path_positive_count": viable_side_counts.get("long", 0),
        "short_path_positive_count": viable_side_counts.get("short", 0),
        "long_and_short_have_viable_path": (
            viable_side_counts.get("long", 0) > 0 and viable_side_counts.get("short", 0) > 0
        ),
        "sample_rows": [_trim_row(row) for row in major_missed[:50]],
        "no_live_mutation": True,
        "runtime_thresholds_changed": False,
    }
