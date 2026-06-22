from __future__ import annotations

from typing import Any

from .accounting import economic_fill_notional, economic_fill_quantity, normalize_side


def classify_fill(row: dict[str, Any]) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "").upper()
    side = normalize_side(row.get("side") or row.get("action") or row.get("selected_action"))
    quantity = economic_fill_quantity(row)
    notional = economic_fill_notional(row)
    price = row.get("fill_price") or row.get("entry_price")
    blockers: list[str] = []
    if not symbol:
        blockers.append("MISSING_SYMBOL")
    if side is None:
        blockers.append("MISSING_SIDE")
    if quantity is None or quantity <= 0:
        blockers.append("MISSING_QTY")
    if notional is None or notional <= 0:
        blockers.append("MISSING_NOTIONAL")
    try:
        price_value = float(price)
    except (TypeError, ValueError):
        price_value = None
    if price_value is None or price_value <= 0:
        blockers.append("MISSING_PRICE")
    if not (row.get("prediction_id") or row.get("source_prediction_id")):
        blockers.append("MISSING_LINEAGE")
    if not row.get("risk_decision_id") or not row.get("orchestrator_decision_id"):
        blockers.append("MISSING_LINEAGE")
    return {
        "economic": not blockers,
        "blockers": blockers,
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "notional": notional,
        "price": price_value,
    }
