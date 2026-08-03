from __future__ import annotations

import json

import pytest

from v2.backend.app.services.orderbook_recorder.features import build_orderbook_payloads
from v2.backend.app.services.orderbook_recorder.local_book import LocalOrderBook
from v2.backend.app.services.orderbook_recorder.providers import (
    build_binance_stream_names,
    build_kucoin_subscription_messages,
    parse_binance_message,
    parse_kucoin_message,
)


def test_build_orderbook_payloads_computes_spread_depth_and_latency() -> None:
    payloads = build_orderbook_payloads(
        exchange="binance",
        symbol="BTCUSDT",
        bids=[["100.0", "2"], ["99.5", "1"]],
        asks=[["100.5", "3"], ["101.0", "1"]],
        event_time_ms=1_780_000_000_000,
        received_at="2026-06-01T00:00:01.000Z",
        sequence_id=42,
    )

    top = payloads["top"]
    features = payloads["features"]

    assert top["best_bid"] == 100.0
    assert top["best_ask"] == 100.5
    assert features["depth_5_bid_usd"] == 299.5
    assert features["depth_5_ask_usd"] == 402.5
    assert features["orderbook_imbalance"] == pytest.approx(-1.0 / 7.0)
    assert features["sequence_gap_flag"] == 0
    assert features["source_latency_ms"] is not None
    assert features["update_age_ms"] >= 0


def test_local_orderbook_detects_binance_sequence_gap() -> None:
    book = LocalOrderBook(exchange="binance", symbol="BTCUSDT")
    book.apply_snapshot(bids=[["100", "1"]], asks=[["101", "1"]], sequence_id=10)

    gap = book.apply_absolute_delta(
        bids=[["100", "2"]],
        asks=[],
        first_sequence_id=13,
        final_sequence_id=14,
        previous_sequence_id=12,
    )

    assert gap is True
    assert book.sequence_gap_count == 1
    assert book.last_sequence_id == 14
    assert book.top_levels()[0][0] == [100.0, 2.0]


def test_local_orderbook_accepts_initial_binance_diff_bridge_after_snapshot() -> None:
    book = LocalOrderBook(exchange="binance", symbol="BTCUSDT")
    book.apply_snapshot(bids=[["100", "1"]], asks=[["101", "1"]], sequence_id=100)

    gap = book.apply_absolute_delta(
        bids=[["100", "2"]],
        asks=[],
        first_sequence_id=95,
        final_sequence_id=110,
        previous_sequence_id=94,
    )

    assert gap is False
    assert book.sequence_gap_count == 0
    assert book.last_sequence_id == 110


def test_top_of_book_update_preserves_existing_depth_levels() -> None:
    book = LocalOrderBook(exchange="binance", symbol="BTCUSDT")
    book.apply_snapshot(
        bids=[["100", "1"], ["99", "2"]],
        asks=[["101", "1"], ["102", "2"]],
        sequence_id=10,
    )

    book.apply_top_of_book(bids=[["100", "3"]], asks=[["101", "4"]])
    bids, asks = book.top_levels()

    assert bids[:2] == [[100.0, 3.0], [99.0, 2.0]]
    assert asks[:2] == [[101.0, 4.0], [102.0, 2.0]]
    assert book.sequence_gap_count == 0


def test_top_of_book_update_removes_stale_more_aggressive_levels() -> None:
    book = LocalOrderBook(exchange="binance", symbol="BTCUSDT")
    book.apply_snapshot(
        bids=[["105", "1"], ["100", "2"]],
        asks=[["106", "1"], ["110", "2"]],
        sequence_id=10,
    )

    book.apply_top_of_book(bids=[["100", "3"]], asks=[["110", "4"]])
    bids, asks = book.top_levels()

    assert bids[0] == [100.0, 3.0]
    assert asks[0] == [110.0, 4.0]
    assert bids[0][0] < asks[0][0]


def test_provider_parsers_and_subscription_builders() -> None:
    streams = build_binance_stream_names(["BTCUSDT"], speed="100ms")
    assert "btcusdt@depth5@100ms" in streams
    assert "btcusdt@depth10@100ms" in streams
    assert "btcusdt@depth20@100ms" in streams
    assert "btcusdt@depth@100ms" in streams

    parsed = parse_binance_message(
        {
            "stream": "btcusdt@depth20@100ms",
            "data": {
                "e": "depthUpdate",
                "E": 1,
                "T": 2,
                "s": "BTCUSDT",
                "U": 10,
                "u": 11,
                "pu": 9,
                "b": [["100", "1"]],
                "a": [["101", "1"]],
            },
        }
    )
    assert parsed is not None
    assert parsed["exchange"] == "binance"
    assert parsed["is_snapshot"] is True
    assert parsed["depth_level"] == 20
    assert parsed["feed_speed_ms"] == 100

    default_speed = parse_binance_message(
        {
            "stream": "btcusdt@depth",
            "data": {
                "e": "depthUpdate",
                "E": 1,
                "T": 2,
                "s": "BTCUSDT",
                "U": 10,
                "u": 11,
                "pu": 9,
                "b": [["100", "1"]],
                "a": [["101", "1"]],
            },
        }
    )
    assert default_speed is not None
    assert default_speed["type"] == "diff_depth"
    assert default_speed["feed_speed_ms"] == 250

    kucoin_messages = build_kucoin_subscription_messages(["BTCUSDT"], depth="increment@10ms")
    assert kucoin_messages[0]["topic"] == "/contractMarket/level2:XBTUSDTM"
    assert kucoin_messages[0]["type"] == "subscribe"
    kucoin_all = build_kucoin_subscription_messages(["BTCUSDT"], depth="all")
    assert [row["topic"] for row in kucoin_all] == [
        "/contractMarket/level2Depth5:XBTUSDTM",
        "/contractMarket/level2Depth50:XBTUSDTM",
        "/contractMarket/level2:XBTUSDTM",
    ]

    kucoin = parse_kucoin_message(
        json.dumps(
            {
                "T": "obu.FUTURES",
                "dp": "increment@10ms",
                "t": "delta",
                "P": 1781666796660937177,
                "d": {
                    "a": [],
                    "b": [["65739.9", "14"]],
                    "C": 1743938538056,
                    "s": "XBTUSDTM",
                    "M": 1781666796658000000,
                    "O": 1743938538050,
                },
            }
        )
    )
    assert kucoin is not None
    assert kucoin["exchange"] == "kucoin"
    assert kucoin["symbol"] == "BTCUSDT"
    assert kucoin["is_snapshot"] is False
    assert kucoin["depth_level"] == "increment_best_500"
    assert kucoin["feed_speed_ms"] == 10

    kucoin_level50 = parse_kucoin_message(
        {
            "topic": "/contractMarket/level2Depth50:XBTUSDTM",
            "type": "message",
            "subject": "level2",
            "sn": 1709294490099,
            "data": {
                "bids": [["89778.6", 1534]],
                "asks": [["89778.7", 854]],
                "sequence": 1709294490099,
                "timestamp": 1731680249700,
                "ts": 1731680249700,
            },
        }
    )
    assert kucoin_level50 is not None
    assert kucoin_level50["symbol"] == "BTCUSDT"
    assert kucoin_level50["type"] == "obu_50"
    assert kucoin_level50["bids"] == [["89778.6", 1534]]
    assert kucoin_level50["is_snapshot"] is True
    assert kucoin_level50["depth_level"] == 50
    assert kucoin_level50["feed_speed_ms"] == 100
