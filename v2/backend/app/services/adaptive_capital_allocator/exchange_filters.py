from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, localcontext
from typing import Any


PAPER_EXECUTION_MINIMUM_SCHEMA_VERSION = "paper_execution_minimum_v1"


def _positive_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() and parsed > 0 else None


def _decimal_to_float(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def round_down_to_step_exact(quantity: float, step_size: float | None) -> float:
    """Quantize a PAPER quantity down without binary-float boundary drift."""

    parsed_quantity = _positive_decimal(quantity)
    parsed_step = _positive_decimal(step_size)
    if parsed_quantity is None:
        return 0.0
    if parsed_step is None:
        return float(parsed_quantity)
    with localcontext() as context:
        context.prec = 50
        steps = (parsed_quantity / parsed_step).to_integral_value(rounding=ROUND_FLOOR)
        return float(steps * parsed_step)


def paper_execution_minimum(
    *,
    mark_price: float,
    min_qty: float | None,
    min_notional: float | None,
    step_size: float | None,
    max_qty: float | None,
) -> dict[str, Any]:
    """Return the exact minimum executable PAPER market-order quantity.

    Decimal arithmetic is intentional: venue filter values are decimal
    contracts, and a binary-float quotient immediately below an integer step
    must not authorize an undersized order.
    """

    price = _positive_decimal(mark_price)
    minimum_quantity = _positive_decimal(min_qty) or Decimal("0")
    minimum_notional = _positive_decimal(min_notional) or Decimal("0")
    quantity_step = _positive_decimal(step_size)
    maximum_quantity = _positive_decimal(max_qty)
    rejection_reasons: list[str] = []
    if price is None:
        rejection_reasons.append("MARK_PRICE_MISSING_OR_INVALID")

    quantity_for_min_notional: Decimal | None = None
    executable_quantity: Decimal | None = None
    executable_notional: Decimal | None = None
    if not rejection_reasons:
        assert price is not None
        assert minimum_quantity is not None
        assert minimum_notional is not None
        with localcontext() as context:
            context.prec = 50
            raw_quantity_for_min_notional = minimum_notional / price
            if quantity_step is None:
                quantity_for_min_notional = raw_quantity_for_min_notional
            else:
                minimum_notional_steps = (
                    raw_quantity_for_min_notional / quantity_step
                ).to_integral_value(rounding=ROUND_CEILING)
                quantity_for_min_notional = minimum_notional_steps * quantity_step
            governing_quantity = max(minimum_quantity, quantity_for_min_notional)
            if quantity_step is None:
                executable_quantity = governing_quantity
            else:
                governing_steps = (governing_quantity / quantity_step).to_integral_value(
                    rounding=ROUND_CEILING
                )
                executable_quantity = governing_steps * quantity_step
            executable_notional = executable_quantity * price
        if maximum_quantity is not None and executable_quantity > maximum_quantity:
            rejection_reasons.append("MINIMUM_EXECUTABLE_QUANTITY_ABOVE_MAXIMUM_QUANTITY")

    return {
        "schema_version": PAPER_EXECUTION_MINIMUM_SCHEMA_VERSION,
        "status": "PASS" if not rejection_reasons else "BLOCKED",
        "mark_price": _decimal_to_float(price),
        "min_notional": _decimal_to_float(minimum_notional),
        "min_quantity": _decimal_to_float(minimum_quantity),
        "quantity_step_size": _decimal_to_float(quantity_step),
        "maximum_quantity": _decimal_to_float(maximum_quantity),
        "quantity_for_min_notional": _decimal_to_float(quantity_for_min_notional),
        "minimum_executable_quantity": _decimal_to_float(executable_quantity),
        "minimum_executable_notional": _decimal_to_float(executable_notional),
        "rounding_mode": "DECIMAL_CEIL_TO_QUANTITY_STEP",
        "rejection_reasons": rejection_reasons,
    }


def round_down_to_step(quantity: float, step_size: float | None) -> float:
    if step_size is None or step_size <= 0:
        return max(0.0, quantity)
    steps = math.floor(quantity / step_size)
    return max(0.0, steps * step_size)


def min_order_notional(*, min_qty: float | None, min_notional: float | None, price: float) -> float:
    qty_notional = 0.0
    if min_qty is not None and min_qty > 0 and price > 0:
        qty_notional = min_qty * price
    return max(qty_notional, min_notional or 0.0)
