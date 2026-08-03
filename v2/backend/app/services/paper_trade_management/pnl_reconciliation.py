from __future__ import annotations

from typing import Any

from .accounting import coerce_float


def reconcile_paper_pnl(
    *,
    fills: list[dict[str, Any]],
    open_positions: list[dict[str, Any]],
    closed_trades: list[dict[str, Any]],
    mark_prices: dict[str, Any],
    starting_equity: float = 0.0,
) -> dict[str, Any]:
    unreconciled: list[dict[str, Any]] = []
    fees = 0.0
    slippage = 0.0
    realized = 0.0
    for row in closed_trades:
        realized += coerce_float(row.get("realized_pnl_usd") or row.get("realized_pnl_usdt")) or 0.0
        fees += coerce_float(row.get("fees")) or 0.0
        slippage += coerce_float(row.get("slippage")) or 0.0
        if not row.get("source_fill_ids"):
            unreconciled.append({"row": row.get("close_id"), "reason": "CLOSED_TRADE_MISSING_SOURCE_FILL_IDS"})
        if coerce_float(row.get("entry_price")) is None or coerce_float(row.get("exit_price")) is None:
            unreconciled.append({"row": row.get("close_id"), "reason": "CLOSED_TRADE_MISSING_ENTRY_OR_EXIT_PRICE"})

    unrealized = 0.0
    for row in open_positions:
        symbol = str(row.get("symbol") or "").upper()
        mark = mark_prices.get(symbol)
        if isinstance(mark, dict):
            mark = mark.get("price") or mark.get("mark_price")
        mark_value = coerce_float(mark or row.get("last_mark_price"))
        qty = coerce_float(row.get("net_quantity") or row.get("quantity"))
        entry = coerce_float(row.get("avg_entry_price") or row.get("entry_price"))
        side = str(row.get("side") or "").lower()
        if mark_value is None or qty is None or entry is None or side not in {"long", "short"}:
            unreconciled.append({"row": row.get("position_id") or symbol, "reason": "OPEN_POSITION_MISSING_MARK_QTY_ENTRY_OR_SIDE"})
            continue
        if side == "long":
            unrealized += (mark_value - entry) * qty
        else:
            unrealized += (entry - mark_value) * qty

    fill_ids = set()
    for row in fills:
        fill_id = row.get("fill_id") or row.get("ledger_row_id") or row.get("intent_id")
        if fill_id:
            fill_ids.add(str(fill_id))
    for row in closed_trades:
        for fill_id in row.get("source_fill_ids") or []:
            if str(fill_id) not in fill_ids:
                unreconciled.append({"row": row.get("close_id"), "reason": f"SOURCE_FILL_NOT_FOUND:{fill_id}"})

    equity = starting_equity + realized + unrealized
    return {
        "paper_equity": equity,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "fees": fees,
        "slippage": slippage,
        "open_positions_count": len(open_positions),
        "closed_positions_count": len(closed_trades),
        "mark_price_sources": sorted(str(k) for k in mark_prices.keys()),
        "reconciliation_status": "RECONCILED" if not unreconciled else "UNRECONCILED_ROWS_PRESENT",
        "unreconciled_rows": unreconciled,
        "paper_only": True,
        "places_real_order": False,
    }


__all__ = ["reconcile_paper_pnl"]
