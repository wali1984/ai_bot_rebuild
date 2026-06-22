from __future__ import annotations

import math


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
