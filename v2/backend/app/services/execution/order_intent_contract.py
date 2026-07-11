"""Order intent contract — canonical dry-run order description.

Describes exactly what WOULD be submitted, with symbol-filter validation and
Hedge-Mode / reduceOnly correctness, without ever submitting. Enforces the
safety rules that block accidental live/test orders unless an operator flag
is explicitly set in the environment.
"""

from __future__ import annotations

import math
import os
from typing import Any, Mapping

SCHEMA_VERSION = "order_intent_contract_v1"

# Binance forbids reduceOnly in Hedge Mode; closes use positionSide + closePosition.
MAKER_ORDER_TYPES = frozenset({"LIMIT"})
EMERGENCY_ORDER_TYPES = frozenset({"MARKET", "STOP_MARKET", "TAKE_PROFIT_MARKET", "TRAILING_STOP_MARKET"})


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return math.floor(value / step) * step


def operator_test_order_allowed() -> bool:
    return os.environ.get("BINANCE_TEST_ORDER_PROBE_ALLOWED", "").lower() == "true"


def operator_leverage_mutation_allowed() -> bool:
    return os.environ.get("BINANCE_LEVERAGE_MUTATION_PROBE_ALLOWED", "").lower() == "true"


def operator_margin_mutation_allowed() -> bool:
    return os.environ.get("BINANCE_MARGIN_MUTATION_PROBE_ALLOWED", "").lower() == "true"


def build_order_intent(
    *,
    symbol: str,
    side: str,
    order_type: str,
    quantity: float,
    price: float | None,
    hedge_mode: bool,
    reduce_only: bool,
    close_position: bool,
    symbol_filters: Mapping[str, Any],
    maker_fee_bps: float = 2.0,
    taker_fee_bps: float = 4.0,
    time_in_force: str | None = None,
    best_bid: float | None = None,
    best_ask: float | None = None,
    client_order_id: str | None = None,
    self_trade_prevention_mode: str | None = None,
    taker_fallback_reason: str | None = None,
    expected_fill_probability: float | None = None,
    cancel_replace_plan: str | None = None,
    generated_utc: str,
) -> dict[str, Any]:
    symbol = str(symbol).upper()
    side = str(side).upper()
    order_type = str(order_type).upper()
    tick = _float(symbol_filters.get("tick_size") or symbol_filters.get("tickSize")) or 0.0
    step = _float(symbol_filters.get("step_size") or symbol_filters.get("stepSize")) or 0.0
    min_qty = _float(symbol_filters.get("min_qty") or symbol_filters.get("minQty")) or 0.0
    min_notional = _float(symbol_filters.get("min_notional") or symbol_filters.get("minNotional")) or 0.0

    filter_reasons: list[str] = []
    input_quantity = 0.0 if quantity is None and close_position else quantity
    q = _round_step(input_quantity, step) if step else input_quantity
    if not close_position and q < min_qty:
        filter_reasons.append("QUANTITY_BELOW_MIN_QTY")
    p = _round_step(price, tick) if (price and tick) else price
    notional = (p or 0.0) * q if p else None
    if not close_position and notional is not None and min_notional and notional < min_notional:
        filter_reasons.append("NOTIONAL_BELOW_MIN_NOTIONAL")

    # Hedge-mode correctness: reduceOnly forbidden in hedge mode; use positionSide.
    position_side = ("LONG" if side == "BUY" else "SHORT") if hedge_mode else "BOTH"
    hedge_violations: list[str] = []
    effective_reduce_only = reduce_only
    if hedge_mode and reduce_only:
        hedge_violations.append("REDUCE_ONLY_FORBIDDEN_IN_HEDGE_MODE_USE_POSITIONSIDE")
        effective_reduce_only = False

    is_maker = order_type in MAKER_ORDER_TYPES and (time_in_force == "GTX")
    maker_first = order_type == "LIMIT"

    # GTX (post-only) must never cross the spread — flag if it would.
    bid = _float(best_bid)
    ask = _float(best_ask)
    post_only_reasons: list[str] = []
    post_only_cross_risk = False
    if time_in_force == "GTX" and p:
        if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
            post_only_cross_risk = True
            post_only_reasons.append("BOOK_MISSING_FOR_POST_ONLY_GTX")
        elif side == "BUY" and p >= ask:
            post_only_cross_risk = True
            post_only_reasons.append("BUY_GTX_PRICE_WOULD_CROSS_ASK")
        elif side == "SELL" and p <= bid:
            post_only_cross_risk = True
            post_only_reasons.append("SELL_GTX_PRICE_WOULD_CROSS_BID")
    stp = str(self_trade_prevention_mode or "EXPIRE_TAKER").upper()

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "symbol": symbol,
        "side": side,
        "order_type": order_type,
        "time_in_force": time_in_force,
        "position_side": position_side,
        "positionSide": position_side,
        "close_position": bool(close_position),
        "closePosition": bool(close_position),
        "reduce_only_requested": bool(reduce_only),
        "reduce_only_effective": bool(effective_reduce_only),
        "hedge_mode": bool(hedge_mode),
        "quantity_rounded": q,
        "price_rounded": p,
        "notional_usd": round(notional, 4) if notional is not None else None,
        "symbol_filter_pass": not filter_reasons,
        "symbol_filter_reasons": filter_reasons,
        "hedge_mode_violations": hedge_violations,
        "post_only_supported": is_maker,
        "post_only_requested": time_in_force == "GTX",
        "post_only_cross_spread_risk": post_only_cross_risk,
        "post_only_cross_spread_reasons": post_only_reasons,
        "maker_first": maker_first,
        "clientOrderId": client_order_id,
        "selfTradePreventionMode": stp,
        "estimated_maker_fee_usd": round((notional or 0) * maker_fee_bps / 10_000.0, 6),
        "estimated_taker_fee_usd": round((notional or 0) * taker_fee_bps / 10_000.0, 6),
        "expected_fill_probability": expected_fill_probability,
        "taker_fallback_reason": taker_fallback_reason,
        "cancel_replace_plan": cancel_replace_plan,
        "is_emergency_type": order_type in EMERGENCY_ORDER_TYPES,
        # SAFETY: dry-run always. Live/test require explicit operator env flags.
        "would_submit_order": False,
        "would_submit_test_order": False,
        "operator_test_order_allowed": operator_test_order_allowed(),
        "operator_leverage_mutation_allowed": operator_leverage_mutation_allowed(),
        "operator_margin_mutation_allowed": operator_margin_mutation_allowed(),
        "places_real_order": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "raw_key_exposed": False,
    }
