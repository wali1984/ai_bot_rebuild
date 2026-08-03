from __future__ import annotations

from v2.backend.app.services.orderbook_recorder.store import LocalReplayStore


def test_local_replay_store_partitions_and_reports_status(tmp_path) -> None:
    store = LocalReplayStore(tmp_path / "orderbook_replay")
    store.append(
        exchange="binance",
        symbol="BTCUSDT",
        record_type="features",
        event_time="2026-06-01T12:34:56.000Z",
        payload={
            "event_time": "2026-06-01T12:34:56.000Z",
            "bid": 100.0,
            "ask": 101.0,
            "spread_bps": 1.0,
            "update_type": "partial_depth",
            "depth_level": 20,
            "feed_speed_ms": 100,
        },
    )
    store.append(
        exchange="binance",
        symbol="BTCUSDT",
        record_type="raw_delta",
        event_time="2026-06-01T12:34:57.000Z",
        payload={
            "event_time": "2026-06-01T12:34:57.000Z",
            "bids": [["100", "1"]],
            "asks": [["101", "1"]],
            "sequence_gap": True,
        },
    )

    status = store.status()

    assert status["files"] == 2
    assert status["symbols_recorded"] == 1
    assert status["active_exchanges"] == ["binance"]
    assert status["symbols_by_exchange"] == {"binance": ["BTCUSDT"]}
    assert status["raw_delta_symbol_count"] == 1
    assert status["sequence_gap_symbols"] == ["binance:BTCUSDT"]
    assert status["feed_coverage"]["binance:BTCUSDT"]["depth_levels"] == [20]
    assert status["feed_coverage"]["binance:BTCUSDT"]["feed_speeds_ms"] == [100]
    assert status["update_type_counts"]["binance:partial_depth"] == 1
    assert status["disk_usage"] > 0
    assert status["oldest_replay_timestamp"] == "2026-06-01T12:34:56.000Z"
    assert status["newest_replay_timestamp"] == "2026-06-01T12:34:57.000Z"


def test_local_replay_store_ignores_empty_orderbook_rows_for_coverage(tmp_path) -> None:
    store = LocalReplayStore(tmp_path / "orderbook_replay")
    store.append(
        exchange="kucoin",
        symbol="BICOUSDT",
        record_type="features",
        event_time="2026-06-01T12:34:56.000Z",
        payload={
            "event_time": "2026-06-01T12:34:56.000Z",
            "bid": None,
            "ask": None,
            "update_type": "rest_snapshot",
        },
    )

    status = store.status()

    assert status["files"] == 1
    assert status["files_with_usable_orderbook_rows"] == 0
    assert status["symbols_recorded"] == 0
    assert status["feed_coverage"] == {}
