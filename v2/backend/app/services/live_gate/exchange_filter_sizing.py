"""Exchange-filter aware order sizing helpers for V2 live transport.

All calculations use ``Decimal`` so minimum executable quantities are rounded
up to the exchange step size without float drift.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_CEILING
from typing import Any


def decimal_or_none(value: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(value))
    except Exception:
        return None
    return parsed if parsed.is_finite() else None


def ceil_to_step_size(quantity: Any, step_size: Any) -> Decimal | None:
    qty = decimal_or_none(quantity)
    step = decimal_or_none(step_size)
    if qty is None or step is None or step <= 0:
        return None
    units = (qty / step).to_integral_value(rounding=ROUND_CEILING)
    return units * step


def min_executable_order(
    *,
    mark_price: Any,
    min_notional: Any,
    min_qty: Any,
    step_size: Any,
) -> dict[str, Any]:
    price = decimal_or_none(mark_price)
    notional = decimal_or_none(min_notional) or Decimal("0")
    qty_min = decimal_or_none(min_qty) or Decimal("0")
    step = decimal_or_none(step_size)
    blockers: list[str] = []

    if price is None or price <= 0:
        blockers.append("MARK_PRICE_MISSING_OR_INVALID")
    if step is None or step <= 0:
        blockers.append("STEP_SIZE_MISSING_OR_INVALID")
    if blockers:
        return {
            "ok": False,
            "blockers": blockers,
            "raw_qty_for_min_notional": None,
            "min_executable_quantity": None,
            "min_executable_notional": None,
        }

    raw_qty_for_min_notional = Decimal("0") if notional <= 0 else notional / price
    raw_min_qty = max(qty_min, raw_qty_for_min_notional)
    rounded_qty = ceil_to_step_size(raw_min_qty, step)
    if rounded_qty is None or rounded_qty <= 0:
        return {
            "ok": False,
            "blockers": ["MIN_EXECUTABLE_QUANTITY_ROUNDS_TO_ZERO"],
            "raw_qty_for_min_notional": float(raw_qty_for_min_notional),
            "min_executable_quantity": None,
            "min_executable_notional": None,
        }
    executable_notional = rounded_qty * price
    return {
        "ok": True,
        "blockers": [],
        "raw_qty_for_min_notional": float(raw_qty_for_min_notional),
        "min_executable_quantity": float(rounded_qty),
        "min_executable_notional": float(executable_notional),
        "min_executable_quantity_text": _plain_decimal(rounded_qty),
        "min_executable_notional_text": _plain_decimal(executable_notional),
    }


def _plain_decimal(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text
