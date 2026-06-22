from __future__ import annotations

from app.cli.v2_kucoin_ingestor_worker import _parse_kline


def test_parse_kucoin_futures_kline_uses_futures_field_order() -> None:
    parsed = _parse_kline(
        [[1_780_495_200, "0.0349", "0.0349", "0.03459", "0.03478", "1670", "581.4826"]],
        symbol="BANKUSDT",
        kucoin_symbol="BANKUSDTM",
        timeframe="1m",
        source="kucoin_futures_public_rest",
    )

    assert parsed is not None
    assert parsed["open"] == 0.0349
    assert parsed["high"] == 0.0349
    assert parsed["low"] == 0.03459
    assert parsed["close"] == 0.03478
    assert parsed["low"] <= parsed["open"] <= parsed["high"]
    assert parsed["low"] <= parsed["close"] <= parsed["high"]


def test_parse_kucoin_spot_kline_preserves_spot_field_order() -> None:
    parsed = _parse_kline(
        [[1_780_495_200, "100", "101", "102", "99", "10", "1000"]],
        symbol="BTCUSDT",
        kucoin_symbol="BTC-USDT",
        timeframe="1m",
        source="kucoin_spot_public_rest",
    )

    assert parsed is not None
    assert parsed["open"] == 100.0
    assert parsed["close"] == 101.0
    assert parsed["high"] == 102.0
    assert parsed["low"] == 99.0


def test_parse_kucoin_kline_rejects_malformed_ohlc() -> None:
    parsed = _parse_kline(
        [[1_780_495_200, "100", "101", "99", "102", "10", "1000"]],
        symbol="BTCUSDT",
        kucoin_symbol="BTC-USDT",
        timeframe="1m",
        source="kucoin_spot_public_rest",
    )

    assert parsed is None
