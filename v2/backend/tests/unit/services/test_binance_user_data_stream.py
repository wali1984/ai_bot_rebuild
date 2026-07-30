"""Tests for the read-only Binance user-data (account) stream client."""
from __future__ import annotations

import asyncio
import json

import pytest

from v2.backend.app.services.execution.binance_usdm_adapter import BinanceUSDMAdapter
from v2.backend.app.services.binance_user_data_stream import (
    READ_ONLY,
    PLACES_REAL_ORDER,
    BinanceUserDataStreamClient,
    UserDataAccountModel,
    derive_user_data_ws_base,
    normalize_account_update,
    normalize_order_trade_update,
    normalize_margin_call,
    normalize_account_config_update,
)


def _adapter(creds: bool = True, base="https://fapi.binance.com") -> BinanceUSDMAdapter:
    return BinanceUSDMAdapter(
        api_key="ro-key" if creds else None,
        api_secret="ro-secret" if creds else None,
        base_url=base,
    )


# ── module invariants ─────────────────────────────────────────────────────────

def test_module_is_read_only_never_trades():
    assert READ_ONLY is True
    assert PLACES_REAL_ORDER is False


def test_ws_base_derivation_mainnet_and_testnet():
    assert derive_user_data_ws_base("https://fapi.binance.com") == "wss://fstream.binance.com"
    assert derive_user_data_ws_base("https://testnet.binancefuture.com") == "wss://stream.binancefuture.com"


# ── pure normalizers ──────────────────────────────────────────────────────────

def test_normalize_account_update():
    ev = {"e": "ACCOUNT_UPDATE", "E": 1, "T": 2, "a": {"m": "ORDER",
          "B": [{"a": "USDT", "wb": "100.5", "cw": "100.5", "bc": "0"}],
          "P": [{"s": "BTCUSDT", "pa": "0.01", "ep": "60000", "up": "1.5", "mt": "cross", "ps": "BOTH"}]}}
    n = normalize_account_update(ev)
    assert n["reason"] == "ORDER"
    assert n["balances"][0] == {"asset": "USDT", "wallet_balance": 100.5, "cross_wallet_balance": 100.5, "balance_change": 0.0}
    assert n["positions"][0]["symbol"] == "BTCUSDT"
    assert n["positions"][0]["unrealized_pnl"] == 1.5
    assert n["positions"][0]["margin_type"] == "cross"


def test_normalize_order_trade_update():
    ev = {"e": "ORDER_TRADE_UPDATE", "E": 5, "o": {"s": "ETHUSDT", "S": "BUY", "o": "LIMIT",
          "i": 42, "X": "NEW", "q": "1", "p": "3000", "z": "0", "R": False}}
    n = normalize_order_trade_update(ev)
    assert n["symbol"] == "ETHUSDT" and n["order_id"] == 42 and n["order_status"] == "NEW"
    assert n["side"] == "BUY" and n["orig_qty"] == 1.0 and n["reduce_only"] is False


def test_normalize_margin_call_and_config():
    mc = normalize_margin_call({"e": "MARGIN_CALL", "E": 9, "cw": "50",
          "p": [{"s": "BTCUSDT", "pa": "0.5", "mp": "60000", "mm": "10", "up": "-5"}]})
    assert mc["cross_wallet_balance"] == 50.0
    assert mc["positions"][0]["maintenance_margin"] == 10.0
    cfg = normalize_account_config_update({"e": "ACCOUNT_CONFIG_UPDATE", "E": 3, "ac": {"s": "BTCUSDT", "l": 5}})
    assert cfg["symbol"] == "BTCUSDT" and cfg["leverage"] == 5


# ── live model accumulation ───────────────────────────────────────────────────

def test_model_tracks_positions_orders_and_removals():
    m = UserDataAccountModel()
    m.apply({"e": "ACCOUNT_UPDATE", "E": 1, "a": {"B": [{"a": "USDT", "wb": "1000"}],
             "P": [{"s": "BTCUSDT", "pa": "0.01", "ep": "60000", "up": "2"}]}})
    assert m.snapshot()["open_position_count"] == 1
    assert m.balances["USDT"]["wallet_balance"] == 1000.0
    # open an order, then fill it -> removed from open_orders
    m.apply({"e": "ORDER_TRADE_UPDATE", "E": 2, "o": {"s": "BTCUSDT", "i": 7, "X": "NEW", "z": "0"}})
    assert m.snapshot()["open_order_count"] == 1
    m.apply({"e": "ORDER_TRADE_UPDATE", "E": 3, "o": {"s": "BTCUSDT", "i": 7, "X": "FILLED", "z": "0.01"}})
    assert m.snapshot()["open_order_count"] == 0
    # flatten the position -> removed
    m.apply({"e": "ACCOUNT_UPDATE", "E": 4, "a": {"P": [{"s": "BTCUSDT", "pa": "0"}]}})
    assert m.snapshot()["open_position_count"] == 0
    assert m.events_applied == 4


def test_model_config_and_margin_call():
    m = UserDataAccountModel()
    m.apply({"e": "ACCOUNT_CONFIG_UPDATE", "E": 1, "ac": {"s": "ETHUSDT", "l": 3}})
    assert m.snapshot()["leverage_by_symbol"] == {"ETHUSDT": 3}
    m.apply({"e": "MARGIN_CALL", "E": 2, "cw": "10", "p": [{"s": "ETHUSDT", "mm": "1"}]})
    assert m.snapshot()["margin_call"]["cross_wallet_balance"] == 10.0


# ── client: credential-absent + safety guard ──────────────────────────────────

def test_client_awaits_credentials_when_none():
    published: dict[str, str] = {}
    c = BinanceUserDataStreamClient(adapter=_adapter(creds=False),
                                    publisher=lambda k, v: published.__setitem__(k, v))
    asyncio.run(c.run(stop=lambda: True))
    status = json.loads(published["v2:live:account_stream:status"])
    assert status["state"] == "AWAITING_READONLY_CREDENTIALS"
    assert status["has_credentials"] is False
    assert status["places_real_order"] is False


def test_client_rejects_any_non_listenkey_path():
    c = BinanceUserDataStreamClient(adapter=_adapter())
    with pytest.raises(ValueError, match="disallowed_path"):
        asyncio.run(c._http_call("POST", "/fapi/v1/order"))  # would be an order — must never be reachable


def test_client_listenkey_lifecycle_and_ws_url():
    calls: list[tuple[str, str]] = []

    async def fake_http(method, url, headers, body):
        calls.append((method, url))
        assert headers.get("X-MBX-APIKEY") == "ro-key"
        if method == "POST":
            return {"ok": True, "status_code": 200, "json": {"listenKey": "LK123"}}
        return {"ok": True, "status_code": 200, "json": {}}

    c = BinanceUserDataStreamClient(adapter=_adapter(), http_sender=fake_http)
    key = asyncio.run(c.create_listen_key())
    assert key == "LK123"
    assert c.ws_url() == "wss://fstream.binance.com/ws/LK123"
    assert asyncio.run(c.keepalive_listen_key()) is True
    assert all(url.endswith("/fapi/v1/listenKey") for _, url in calls)  # only stream mgmt


def test_client_apply_raw_publishes_and_handles_expiry():
    published: dict[str, str] = {}
    c = BinanceUserDataStreamClient(adapter=_adapter(),
                                    publisher=lambda k, v: published.__setitem__(k, v))
    c.apply_raw(json.dumps({"e": "ACCOUNT_UPDATE", "E": 1,
                            "a": {"P": [{"s": "SOLUSDT", "pa": "1", "ep": "150", "up": "3"}]}}))
    snap = json.loads(published["v2:live:account:snapshot"])
    assert snap["open_position_count"] == 1 and snap["read_only"] is True
    exp = c.apply_raw(json.dumps({"e": "listenKeyExpired", "E": 9}))
    assert exp == {"event": "listenKeyExpired"}
    assert json.loads(published["v2:live:account_stream:status"])["state"] == "LISTEN_KEY_EXPIRED"
