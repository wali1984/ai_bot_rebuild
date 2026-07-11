"""Dry-run Binance USD-M order builder.

Builds Binance-shaped order parameters and fee/filter telemetry without
submitting anything. Entries are maker-first LIMIT+GTX by default. Taker
fallbacks are only represented for emergency/squeeze/liquidation/explicit
alpha urgency contexts; the builder never calls Binance.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from v2.backend.app.services.execution.order_intent_contract import build_order_intent

SCHEMA_VERSION = "binance_order_builder_v1"

EMERGENCY_TAKER_REASONS = frozenset({
    "EMERGENCY_EXIT",
    "SQUEEZE_DEFENSE",
    "LIQUIDATION_BUFFER_COLLAPSE",
    "EXPLICIT_ALPHA_URGENCY",
})


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _binance_side(side: str) -> str:
    text = str(side or "").strip().lower()
    if text in {"buy", "long", "open_long"}:
        return "BUY"
    if text in {"sell", "short", "open_short"}:
        return "SELL"
    return str(side or "").upper()


def _position_side(side: str, hedge_mode: bool, close_position: bool) -> str:
    if not hedge_mode:
        return "BOTH"
    text = str(side or "").strip().lower()
    if close_position:
        return "LONG" if text in {"sell", "short", "close_long"} else "SHORT"
    return "LONG" if text in {"buy", "long", "open_long"} else "SHORT"


def _client_order_id(symbol: str, side: str, order_type: str, generated_utc: str) -> str:
    digest = hashlib.sha256(f"{symbol}|{side}|{order_type}|{generated_utc}".encode()).hexdigest()[:20]
    return f"v2_{digest}"


def _maker_price(side: str, best_bid: float | None, best_ask: float | None, reference_price: float) -> float:
    if side == "BUY" and best_bid and best_bid > 0:
        return best_bid
    if side == "SELL" and best_ask and best_ask > 0:
        return best_ask
    return reference_price


def build_binance_order_plan(
    *,
    symbol: str,
    side: str,
    symbol_filters: Mapping[str, Any],
    hedge_mode: bool,
    generated_utc: str,
    current_price: float | None = None,
    best_bid: float | None = None,
    best_ask: float | None = None,
    quantity: float | None = None,
    notional_usd: float | None = None,
    order_type: str = "LIMIT",
    time_in_force: str | None = "GTX",
    close_position: bool = False,
    reduce_only: bool = False,
    taker_fallback_reason: str | None = None,
    maker_fee_bps: float = 2.0,
    taker_fee_bps: float = 4.0,
    self_trade_prevention_mode: str = "EXPIRE_TAKER",
    stop_price: float | None = None,
    activation_price: float | None = None,
    callback_rate: float | None = None,
    working_type: str = "MARK_PRICE",
    price_protect: bool = True,
) -> dict[str, Any]:
    symbol = str(symbol or "").upper()
    binance_side = _binance_side(side)
    order_type = str(order_type or "LIMIT").upper()
    price_ref = _float(current_price) or _float(best_bid) or _float(best_ask) or 0.0
    bid = _float(best_bid)
    ask = _float(best_ask)

    builder_reject_reasons: list[str] = []
    taker_reason = str(taker_fallback_reason or "").upper() or None
    taker_fallback_allowed = bool(taker_reason in EMERGENCY_TAKER_REASONS)
    if order_type in {"MARKET", "STOP_MARKET"} and not (close_position or taker_fallback_allowed):
        builder_reject_reasons.append("TAKER_ENTRY_BLOCKED_WITHOUT_EMERGENCY_OR_ALPHA_URGENCY")
    if time_in_force == "IOC" and not (close_position or taker_fallback_allowed):
        builder_reject_reasons.append("IOC_ENTRY_BLOCKED_WITHOUT_EMERGENCY_OR_ALPHA_URGENCY")
    if price_ref <= 0 and not close_position:
        builder_reject_reasons.append("REFERENCE_PRICE_MISSING")

    maker_first = order_type == "LIMIT" and time_in_force == "GTX" and not close_position
    order_price = None if order_type in {"MARKET", "STOP_MARKET", "TAKE_PROFIT_MARKET", "TRAILING_STOP_MARKET"} else _maker_price(binance_side, bid, ask, price_ref)
    qty = _float(quantity)
    if qty is None and notional_usd is not None and (order_price or price_ref) > 0:
        qty = float(notional_usd) / float(order_price or price_ref)
    if qty is None and not close_position:
        builder_reject_reasons.append("QUANTITY_MISSING")
        qty = 0.0

    client_order_id = _client_order_id(symbol, binance_side, order_type, generated_utc)
    expected_fill_probability = 0.82 if maker_first and bid and ask else (0.25 if maker_first else 1.0 if close_position else 0.0)
    cancel_replace_plan = "cancel+replace GTX maker clip if it crosses spread or remains unfilled past TTL" if maker_first else None
    intent = build_order_intent(
        symbol=symbol,
        side=binance_side,
        order_type=order_type,
        quantity=qty,
        price=order_price,
        hedge_mode=hedge_mode,
        reduce_only=reduce_only,
        close_position=close_position,
        symbol_filters=symbol_filters,
        maker_fee_bps=maker_fee_bps,
        taker_fee_bps=taker_fee_bps,
        time_in_force=time_in_force,
        best_bid=bid,
        best_ask=ask,
        client_order_id=client_order_id,
        self_trade_prevention_mode=self_trade_prevention_mode,
        taker_fallback_reason=taker_reason,
        expected_fill_probability=round(expected_fill_probability, 4),
        cancel_replace_plan=cancel_replace_plan,
        generated_utc=generated_utc,
    )
    if intent["post_only_cross_spread_risk"]:
        builder_reject_reasons.append("POST_ONLY_WOULD_CROSS_OR_BOOK_MISSING")
    if not intent["symbol_filter_pass"]:
        builder_reject_reasons.extend(intent["symbol_filter_reasons"])
    if intent["hedge_mode_violations"]:
        builder_reject_reasons.extend(intent["hedge_mode_violations"])

    position_side = _position_side(side, hedge_mode, close_position)
    params: dict[str, Any] = {
        "symbol": symbol,
        "side": binance_side,
        "type": order_type,
        "newClientOrderId": client_order_id,
        "selfTradePreventionMode": self_trade_prevention_mode,
    }
    if time_in_force:
        params["timeInForce"] = time_in_force
    if hedge_mode:
        params["positionSide"] = position_side
    if order_price is not None:
        params["price"] = intent["price_rounded"]
    if not close_position:
        params["quantity"] = intent["quantity_rounded"]
    if close_position:
        params["closePosition"] = "true"
    rounded_stop = _float(stop_price)
    if order_type in {"STOP_MARKET", "TAKE_PROFIT_MARKET"}:
        if rounded_stop is None or rounded_stop <= 0:
            builder_reject_reasons.append("STOP_PRICE_REQUIRED_FOR_TRIGGER_ORDER")
        else:
            params["stopPrice"] = rounded_stop
        params["workingType"] = working_type
        params["priceProtect"] = "TRUE" if price_protect else "FALSE"
    if order_type == "TRAILING_STOP_MARKET":
        cb = _float(callback_rate)
        if cb is None or cb <= 0:
            builder_reject_reasons.append("CALLBACK_RATE_REQUIRED_FOR_TRAILING_STOP")
        else:
            params["callbackRate"] = cb
        act = _float(activation_price)
        if act is not None and act > 0:
            params["activationPrice"] = act
        params["workingType"] = working_type

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc,
        "symbol": symbol,
        "side": binance_side,
        "order_type": order_type,
        "timeInForce": time_in_force,
        "post_only_requested": time_in_force == "GTX",
        "post_only_supported": order_type == "LIMIT" and time_in_force == "GTX",
        "maker_first": maker_first,
        "taker_fallback_allowed": taker_fallback_allowed,
        "taker_fallback_reason": taker_reason if taker_fallback_allowed else None,
        "positionSide": position_side,
        "closePosition": bool(close_position),
        "reduce_only_semantics": "HEDGE_MODE_CLOSE_POSITION" if hedge_mode and close_position else ("ONE_WAY_REDUCE_ONLY" if reduce_only else "ENTRY_OR_ADD"),
        "clientOrderId": client_order_id,
        "symbol_filter_pass": intent["symbol_filter_pass"] and not builder_reject_reasons,
        "symbol_filter_reasons": intent["symbol_filter_reasons"],
        "builder_reject_reasons": sorted(set(builder_reject_reasons)),
        "estimated_maker_fee_usd": intent["estimated_maker_fee_usd"],
        "estimated_taker_fee_usd": intent["estimated_taker_fee_usd"],
        "expected_fill_probability": round(expected_fill_probability, 4),
        "cancel_replace_plan": cancel_replace_plan,
        "post_only_cross_spread_risk": intent["post_only_cross_spread_risk"],
        "post_only_cross_spread_reasons": intent["post_only_cross_spread_reasons"],
        "order_params": params,
        "intent": intent,
        "would_submit_order": False,
        "would_submit_test_order": False,
        "places_real_order": False,
        "leverage_mutated": False,
        "margin_mutated": False,
        "raw_key_exposed": False,
    }
