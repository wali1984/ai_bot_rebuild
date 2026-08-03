"""Stealth router + order intent contract safety invariants."""

from __future__ import annotations

from v2.backend.app.services.execution.binance_order_builder import build_binance_order_plan
from v2.backend.app.services.execution.binance_usdm_adapter import (
    BinanceUSDMAdapter,
    endpoint_contract_matrix,
)
from v2.backend.app.services.execution.order_intent_contract import build_order_intent
from v2.backend.app.services.execution.stealth_order_router import plan_stealth_execution

NOW = "2026-07-09T06:00:00Z"
FILTERS = {"tick_size": 0.1, "step_size": 0.001, "min_qty": 0.001, "min_notional": 5.0}


def test_maker_first_plan_never_submits_and_splits_clips():
    plan = plan_stealth_execution(
        symbol="BTCUSDT", side="long", total_notional_usd=5000.0, current_price=60000.0,
        book_liquidity_usd=8000.0, generated_utc=NOW,
    )
    assert plan["would_submit_order"] is False
    assert plan["places_real_order"] is False
    assert plan["maker_first"] is True
    assert plan["time_in_force"] == "GTX"
    assert plan["single_large_visible_order"] is False
    assert plan["clip_count"] >= 2
    assert plan["max_clip_notional_usd"] <= 5000.0
    assert plan["emergency_stop_present"] is True
    assert plan["synthetic_stop_present"] is True


def test_emergency_uses_market_and_marks_taker():
    plan = plan_stealth_execution(
        symbol="ETHUSDT", side="short", total_notional_usd=1000.0, current_price=3000.0,
        is_emergency=True, taker_fallback_reason="LIQUIDATION_BUFFER_COLLAPSE", generated_utc=NOW,
    )
    assert plan["order_type"] == "MARKET"
    assert plan["taker_fallback_allowed"] is True
    assert plan["would_submit_order"] is False


def test_taker_fallback_rejected_for_non_emergency_entry():
    plan = plan_stealth_execution(
        symbol="BTCUSDT", side="long", total_notional_usd=500.0, current_price=60000.0,
        taker_fallback_reason="I_WANT_IT_NOW", generated_utc=NOW,
    )
    assert plan["taker_fallback_allowed"] is False
    assert plan["taker_fallback_reason"] is None


def test_reduce_only_forbidden_in_hedge_mode():
    intent = build_order_intent(
        symbol="BTCUSDT", side="sell", order_type="LIMIT", quantity=0.01, price=60000.0,
        hedge_mode=True, reduce_only=True, close_position=False,
        symbol_filters=FILTERS, time_in_force="GTX", generated_utc=NOW,
    )
    assert "REDUCE_ONLY_FORBIDDEN_IN_HEDGE_MODE_USE_POSITIONSIDE" in intent["hedge_mode_violations"]
    assert intent["reduce_only_effective"] is False
    assert intent["position_side"] == "SHORT"
    assert intent["would_submit_order"] is False


def test_post_only_cross_spread_flagged():
    # Missing book for GTX must fail closed instead of pretending post-only is safe.
    intent = build_order_intent(
        symbol="BTCUSDT", side="buy", order_type="LIMIT", quantity=0.01, price=60000.0,
        hedge_mode=False, reduce_only=False, close_position=False,
        symbol_filters={"tick_size": 0.1, "step_size": 0.001, "min_qty": 0.001, "min_notional": 5.0},
        time_in_force="GTX", generated_utc=NOW,
    )
    assert intent["post_only_cross_spread_risk"] is True
    assert "BOOK_MISSING_FOR_POST_ONLY_GTX" in intent["post_only_cross_spread_reasons"]


def test_symbol_filter_min_notional_enforced():
    intent = build_order_intent(
        symbol="BTCUSDT", side="buy", order_type="LIMIT", quantity=0.001, price=1.0,
        hedge_mode=False, reduce_only=False, close_position=False,
        symbol_filters=FILTERS, time_in_force="GTX", generated_utc=NOW,
    )
    assert intent["symbol_filter_pass"] is False
    assert "NOTIONAL_BELOW_MIN_NOTIONAL" in intent["symbol_filter_reasons"]


def test_binance_order_builder_maker_first_dry_run_contract():
    plan = build_binance_order_plan(
        symbol="BTCUSDT", side="long", symbol_filters=FILTERS, hedge_mode=True,
        current_price=60000.0, best_bid=59999.0, best_ask=60001.0, notional_usd=120.0,
        generated_utc=NOW,
    )
    assert plan["would_submit_order"] is False
    assert plan["would_submit_test_order"] is False
    assert plan["places_real_order"] is False
    assert plan["order_type"] == "LIMIT"
    assert plan["timeInForce"] == "GTX"
    assert plan["maker_first"] is True
    assert plan["positionSide"] == "LONG"
    assert plan["clientOrderId"].startswith("v2_")
    assert plan["post_only_cross_spread_risk"] is False
    assert plan["symbol_filter_pass"] is True


def test_binance_order_builder_blocks_default_taker_entry():
    plan = build_binance_order_plan(
        symbol="ETHUSDT", side="long", symbol_filters=FILTERS, hedge_mode=False,
        current_price=3000.0, quantity=0.01, order_type="MARKET",
        generated_utc=NOW,
    )
    assert "TAKER_ENTRY_BLOCKED_WITHOUT_EMERGENCY_OR_ALPHA_URGENCY" in plan["builder_reject_reasons"]
    assert plan["would_submit_order"] is False


def test_binance_order_builder_supports_hedge_mode_close_position_stop_dry_run():
    plan = build_binance_order_plan(
        symbol="BTCUSDT", side="close_long", symbol_filters=FILTERS, hedge_mode=True,
        current_price=60000.0, order_type="STOP_MARKET", time_in_force=None,
        close_position=True, taker_fallback_reason="EMERGENCY_EXIT", stop_price=59234.5,
        generated_utc=NOW,
    )
    assert plan["positionSide"] == "LONG"
    assert plan["closePosition"] is True
    assert plan["order_params"]["closePosition"] == "true"
    assert plan["order_params"]["stopPrice"] == 59234.5
    assert "quantity" not in plan["order_params"]
    assert plan["would_submit_order"] is False


def test_binance_usdm_adapter_redacts_signed_read_contract_and_blocks_mutation():
    adapter = BinanceUSDMAdapter(api_key="key", api_secret="secret", base_url="https://example.test")
    ws_contract = adapter.signed_ws_contract("account.status", {"recvWindow": 5000})
    assert ws_contract["would_call"] is True
    assert ws_contract["payload_redacted"]["params"]["apiKey"] == "[redacted]"
    assert ws_contract["payload_redacted"]["params"]["signature"] == "[redacted]"
    contract = adapter.signed_get_contract("/fapi/v3/account", {"recvWindow": 5000})
    assert contract["transport"] == "rest_fallback_only"
    assert contract["would_call"] is False
    assert contract["rest_fallback_blocked_reason"] == "REST_FALLBACK_REASON_REQUIRED_WEBSOCKET_PRIMARY"
    assert contract["rest_used_as_primary"] is False
    blocked_rest = adapter.signed_get("/fapi/v3/account", {"recvWindow": 5000}, execute=True)
    assert blocked_rest["status"] == "REST_FALLBACK_BLOCKED_WEBSOCKET_PRIMARY"
    assert blocked_rest["rest_used_as_primary"] is False
    fallback = adapter.signed_get_contract(
        "/fapi/v3/account", {"recvWindow": 5000}, fallback_reason="WSS_CACHE_STALE"
    )
    assert fallback["rest_fallback_reason"] == "WSS_CACHE_STALE"
    assert fallback["would_call"] is False
    assert str(fallback["rest_fallback_blocked_reason"]).startswith("REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY")
    assert contract["headers"]["X-MBX-APIKEY"] == "<redacted>"
    assert contract["params_redacted"]["signature"] == "<redacted>"
    assert contract["api_key_exposed"] is False
    assert contract["api_secret_exposed"] is False
    blocked = adapter.blocked_mutation("/fapi/v1/order", {"symbol": "BTCUSDT"})
    assert blocked["would_submit_order"] is False
    assert blocked["places_real_order"] is False
    matrix = endpoint_contract_matrix()
    assert matrix["account_and_trader_primary_transport"] == "binance_usdm_websocket_api"
    assert matrix["rest_used_as_primary"] is False
    assert matrix["signed_rest_fallback_supported_for_trader_readiness"] is False
    assert matrix["trader_account_reads_require_websocket_api"] is True
    assert matrix["trader_order_submit_requires_websocket_api"] is True
    assert matrix["rest_role"].startswith("fallback_only")
    assert "/fapi/v3/account" in matrix["signed_rest_fallback_endpoints"]
