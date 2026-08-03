from __future__ import annotations

import pytest

from v2.backend.app.services.trade_tape import service


def _trade(ts_ms: int = 1_780_000_000_000) -> dict:
    return {"T": ts_ms, "p": "100", "q": "1", "m": False}


def test_fetch_binance_agg_trades_uses_websocket_primary(monkeypatch) -> None:
    rest_called = False

    def fake_wss(symbol: str, *, limit: int, timeout: float):
        assert symbol == "BTCUSDT"
        assert limit == 25
        return [_trade()], "wss://fstream.binance.com/ws/btcusdt@aggTrade"

    def fake_rest(*args, **kwargs):
        nonlocal rest_called
        rest_called = True
        return [_trade()]

    monkeypatch.delenv("BINANCE_REST_FALLBACK_ALLOWED", raising=False)
    monkeypatch.setattr(service, "_fetch_binance_agg_trades_websocket", fake_wss)
    monkeypatch.setattr(service, "_fetch_binance_agg_trades_rest_fallback", fake_rest)

    result = service.fetch_binance_agg_trades_with_source("btcusdt", limit=25)

    assert result.source == service.WEBSOCKET_PRIMARY_SOURCE
    assert result.transport == "websocket"
    assert result.fallback_used is False
    assert result.rest_fallback_allowed is False
    assert rest_called is False
    assert result.trades == [_trade()]


def test_fetch_binance_agg_trades_blocks_rest_when_fallback_flag_absent(monkeypatch) -> None:
    rest_called = False

    def fake_wss(*args, **kwargs):
        raise TimeoutError("no stream messages")

    def fake_rest(*args, **kwargs):
        nonlocal rest_called
        rest_called = True
        return [_trade()]

    monkeypatch.delenv("BINANCE_REST_FALLBACK_ALLOWED", raising=False)
    monkeypatch.setattr(service, "_fetch_binance_agg_trades_websocket", fake_wss)
    monkeypatch.setattr(service, "_fetch_binance_agg_trades_rest_fallback", fake_rest)

    with pytest.raises(RuntimeError, match="BINANCE_REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY"):
        service.fetch_binance_agg_trades_with_source("BTCUSDT", limit=25)

    assert rest_called is False


def test_fetch_binance_agg_trades_rest_fallback_requires_operator_flag(monkeypatch) -> None:
    def fake_wss(*args, **kwargs):
        raise TimeoutError("no stream messages")

    def fake_rest(symbol: str, *, limit: int, timeout: float):
        assert symbol == "BTCUSDT"
        assert limit == 25
        return [_trade()]

    monkeypatch.setenv("BINANCE_REST_FALLBACK_ALLOWED", "true")
    monkeypatch.setattr(service, "_fetch_binance_agg_trades_websocket", fake_wss)
    monkeypatch.setattr(service, "_fetch_binance_agg_trades_rest_fallback", fake_rest)

    result = service.fetch_binance_agg_trades_with_source("BTCUSDT", limit=25)

    assert result.source == service.REST_FALLBACK_SOURCE
    assert result.transport == "rest_fallback"
    assert result.fallback_used is True
    assert result.rest_fallback_allowed is True
    assert result.fallback_reason and "TimeoutError" in result.fallback_reason


def test_fetch_binance_agg_trades_batch_collects_combined_stream(monkeypatch) -> None:
    messages = [
        {
            "stream": "btcusdt@aggTrade",
            "data": {
                "e": "aggTrade",
                "E": 1_780_000_000_001,
                "a": 1,
                "s": "BTCUSDT",
                "p": "100",
                "q": "1",
                "f": 1,
                "l": 1,
                "T": 1_780_000_000_000,
                "m": False,
            },
        },
        {
            "stream": "ethusdt@aggTrade",
            "data": {
                "e": "aggTrade",
                "E": 1_780_000_000_002,
                "a": 2,
                "s": "ETHUSDT",
                "p": "200",
                "q": "2",
                "f": 2,
                "l": 2,
                "T": 1_780_000_000_001,
                "m": True,
            },
        },
    ]

    class FakeWebSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def recv(self, timeout: float):
            del timeout
            if not messages:
                raise TimeoutError("done")
            return service.json.dumps(messages.pop(0))

    def fake_connect(url: str, **kwargs):
        del kwargs
        assert "btcusdt@aggTrade/ethusdt@aggTrade/xrpusdt@aggTrade" in url
        return FakeWebSocket()

    monkeypatch.setattr("websockets.sync.client.connect", fake_connect)
    monkeypatch.delenv("BINANCE_REST_FALLBACK_ALLOWED", raising=False)

    result = service.fetch_binance_agg_trades_batch_with_source(
        ["BTCUSDT", "ETHUSDT", "XRPUSDT"],
        limit_per_symbol=2,
        timeout=1.0,
    )

    assert result.transport == "websocket_batch"
    assert result.fallback_used is False
    assert len(result.trades_by_symbol["BTCUSDT"]) == 1
    assert len(result.trades_by_symbol["ETHUSDT"]) == 1
    assert result.trades_by_symbol["XRPUSDT"] == []
    assert result.symbol_errors == {"XRPUSDT": "NO_WEBSOCKET_AGG_TRADE_WITHIN_TIMEOUT"}
