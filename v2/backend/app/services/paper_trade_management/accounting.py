from __future__ import annotations

from typing import Any


def coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        return value if value == value and value not in (float("inf"), float("-inf")) else None
    if isinstance(value, str):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed == parsed and parsed not in (float("inf"), float("-inf")) else None
    return None


def normalize_side(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text in {"long", "buy", "open_long", "proceed_long"} or text.endswith("_long"):
        return "long"
    if text in {"short", "sell", "open_short", "proceed_short"} or text.endswith("_short"):
        return "short"
    return None


def side_sign(side: str) -> int:
    return 1 if side == "long" else -1


def pnl_usd(*, side: str, entry_price: float, exit_price: float, quantity: float) -> float:
    if side == "long":
        return (exit_price - entry_price) * quantity
    return (entry_price - exit_price) * quantity


def pnl_bps(*, side: str, entry_price: float, exit_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    if side == "long":
        return ((exit_price - entry_price) / entry_price) * 10000.0
    return ((entry_price - exit_price) / entry_price) * 10000.0


def fee_and_slippage_usd(*, notional_usdt: float, fee_bps: float, slippage_bps: float) -> tuple[float, float]:
    fee = abs(notional_usdt) * max(0.0, fee_bps) / 10000.0
    slippage = abs(notional_usdt) * max(0.0, slippage_bps) / 10000.0
    return fee, slippage


def economic_fill_notional(row: dict[str, Any]) -> float | None:
    for key in ("notional", "notional_usdt", "notional_usd", "requested_notional_usdt"):
        value = coerce_float(row.get(key))
        if value is not None and value > 0:
            return abs(value)
    qty = coerce_float(row.get("quantity"))
    price = coerce_float(row.get("fill_price") or row.get("entry_price"))
    if qty is not None and qty > 0 and price is not None and price > 0:
        return abs(qty * price)
    return None


def economic_fill_quantity(row: dict[str, Any]) -> float | None:
    qty = coerce_float(row.get("quantity") or row.get("qty") or row.get("size"))
    if qty is not None and qty > 0:
        return abs(qty)
    notional = economic_fill_notional(row)
    price = coerce_float(row.get("fill_price") or row.get("entry_price"))
    if notional is not None and price is not None and price > 0:
        return abs(notional / price)
    return None
