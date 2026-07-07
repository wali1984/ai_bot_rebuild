from __future__ import annotations

import json

from v2.backend.app.services.orderbook_recorder.providers import (
    build_kucoin_subscription_messages,
    kucoin_v2_symbol_to_futures,
    parse_kucoin_message,
)


def test_kucoin_futures_aliases_1000_contracts_to_provider_symbols() -> None:
    assert kucoin_v2_symbol_to_futures("BTCUSDT") == "XBTUSDTM"
    assert kucoin_v2_symbol_to_futures("1000BONKUSDT") == "1000BONKUSDTM"
    assert kucoin_v2_symbol_to_futures("1000FLOKIUSDT") == "FLOKIUSDTM"
    assert kucoin_v2_symbol_to_futures("1000PEPEUSDT") == "PEPEUSDTM"
    assert kucoin_v2_symbol_to_futures("1000SHIBUSDT") == "SHIBUSDTM"


def test_kucoin_subscription_topics_use_provider_aliases() -> None:
    topics = [
        message["topic"]
        for message in build_kucoin_subscription_messages(
            ["1000FLOKIUSDT", "1000PEPEUSDT", "1000SHIBUSDT"],
            trade_type="FUTURES",
            depth="all",
        )
    ]

    assert "/contractMarket/level2Depth5:FLOKIUSDTM" in topics
    assert "/contractMarket/level2Depth50:PEPEUSDTM" in topics
    assert "/contractMarket/level2:SHIBUSDTM" in topics
    assert all("1000FLOKIUSDTM" not in topic for topic in topics)
    assert all("1000PEPEUSDTM" not in topic for topic in topics)
    assert all("1000SHIBUSDTM" not in topic for topic in topics)


def test_kucoin_provider_alias_parses_back_to_v2_symbol() -> None:
    parsed = parse_kucoin_message(
        json.dumps(
            {
                "topic": "/contractMarket/level2Depth50:FLOKIUSDTM",
                "data": {
                    "bids": [["0.0001", "1000"]],
                    "asks": [["0.0002", "900"]],
                    "timestamp": 1780000000000,
                    "sequence": 123,
                },
            }
        )
    )

    assert parsed is not None
    assert parsed["symbol"] == "1000FLOKIUSDT"
    assert parsed["provider_symbol"] == "FLOKIUSDTM"
    assert parsed["depth_level"] == 50
    assert parsed["feed_speed_ms"] == 100
