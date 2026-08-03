import json

from v2.backend.app.services.paper_trade_management.path_telemetry_backfill import (
    build_path_telemetry_backfill_report,
    enrich_closed_trade_row,
)


class FakeRedis:
    def __init__(self, store: dict[str, object]):
        self.store = {key: json.dumps(value) for key, value in store.items()}
        self.set_calls: list[tuple[str, object, int | None]] = []

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None):
        self.store[key] = value
        self.set_calls.append((key, json.loads(value), ex))
        return True


def _trade(**overrides):
    row = {
        "close_id": "close-1",
        "outcome_label_id": "outcome-1",
        "trainer_feedback_id": "feedback-1",
        "position_id": "position-1",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "side": "long",
        "entry_price": 100.0,
        "exit_price": 103.0,
        "exit_time": "2026-06-19T00:20:00Z",
        "hold_time_seconds": 1200,
        "closed_quantity": 2.0,
        "paper_only": True,
        "places_real_order": False,
    }
    row.update(overrides)
    return row


def _closed_candle(open_ms: int, close_ms: int, *, high: float, low: float, **overrides):
    row = {
        "candle_open_time": open_ms,
        "candle_close_time": close_ms,
        "available_at": close_ms + 1,
        "high": high,
        "low": low,
        "is_closed": True,
        "closed_candle": True,
        "candle_closed_confirmed": True,
        "feature_eligible": True,
    }
    row.update(overrides)
    return row


def test_enriches_missing_path_from_strictly_contained_final_candles():
    redis = FakeRedis(
        {
            "v2:market:ohlcv_closed:binance:BTCUSDT:5m": [
                _closed_candle(1781827500000, 1781827799999, high=105.0, low=99.0),
                _closed_candle(1781827800000, 1781828099999, high=104.0, low=101.0),
            ],
            "v2:market:ohlcv:binance:BTCUSDT:5m": [],
        }
    )

    enriched, status, used_public = enrich_closed_trade_row(redis, _trade(), generated_at="2026-06-19T00:30:00Z")

    assert status == "repaired"
    assert used_public is False
    assert enriched["intra_trade_high_price"] == 105.0
    assert enriched["intra_trade_low_price"] == 99.0
    assert enriched["mfe_bps"] == 500.0
    assert enriched["mae_bps"] == 100.0
    assert enriched["path_telemetry_uses_unfinished_candle"] is False
    assert enriched["path_telemetry_uses_overlapping_candle"] is False
    assert enriched["path_telemetry_quality"] == "STRICT_CONTAINED_FINAL_CANDLES_PLUS_ENTRY_EXIT_BOUNDARIES"


def test_rejects_overlapping_or_unfinished_candles_without_synthesizing_path():
    redis = FakeRedis(
        {
            "v2:market:ohlcv_closed:binance:BTCUSDT:5m": [
                _closed_candle(1781826900000, 1781827199999, high=110.0, low=90.0),
                _closed_candle(1781827500000, 1781827799999, high=105.0, low=99.0, is_closed=False),
            ],
            "v2:market:ohlcv:binance:BTCUSDT:5m": [],
        }
    )

    enriched, status, used_public = enrich_closed_trade_row(redis, _trade(), generated_at="2026-06-19T00:30:00Z")

    assert status == "not_coverable"
    assert used_public is False
    assert "mfe_bps" not in enriched
    assert enriched["path_telemetry_backfill_status"] == "NO_STRICT_CONTAINED_FINAL_CANDLE_COVERAGE"


def test_opt_in_public_klines_repair_missing_local_coverage():
    redis = FakeRedis(
        {
            "v2:market:ohlcv_closed:binance:BTCUSDT:5m": [],
            "v2:market:ohlcv:binance:BTCUSDT:5m": [],
        }
    )
    calls = []

    def fake_http_get_json(url: str, timeout: float):
        calls.append((url, timeout))
        return [
            [
                1781827500000,
                "100.0",
                "105.0",
                "99.0",
                "104.0",
                "1000",
                1781827559999,
                "100000",
                10,
                "500",
                "50000",
                "0",
            ]
        ]

    enriched, status, used_public = enrich_closed_trade_row(
        redis,
        _trade(),
        generated_at="2026-06-19T00:30:00Z",
        fetch_binance_public_klines=True,
        http_get_json=fake_http_get_json,
        fetched_at_ms=1781829000000,
    )

    assert status == "repaired"
    assert used_public is True
    assert calls and "fapi.binance.com/fapi/v1/klines" in calls[0][0]
    assert enriched["path_telemetry_source"] == "BINANCE_USDM_PUBLIC_KLINES_CONTAINED_PATH_BACKFILL"
    assert enriched["path_telemetry_public_market_data_readonly"] is True
    assert enriched["intra_trade_high_price"] == 105.0
    assert enriched["intra_trade_low_price"] == 99.0


def test_report_batches_public_klines_by_symbol_window():
    second_trade = _trade(
        close_id="close-2",
        outcome_label_id="outcome-2",
        trainer_feedback_id="feedback-2",
        position_id="position-2",
        exit_time="2026-06-19T00:22:00Z",
        hold_time_seconds=60,
        entry_price=200.0,
        exit_price=201.0,
    )
    redis = FakeRedis(
        {
            "v2:paper:closed_trades": [_trade(), second_trade],
            "v2:paper:outcome_labels": [],
            "v2:paper:ledger": {},
            "v2:market:ohlcv_closed:binance:BTCUSDT:1m": [],
            "v2:market:ohlcv:binance:BTCUSDT:1m": [],
        }
    )
    calls = []

    def fake_http_get_json(url: str, timeout: float):
        calls.append((url, timeout))
        return [
            [
                1781827500000,
                "100.0",
                "105.0",
                "99.0",
                "104.0",
                "1000",
                1781827559999,
                "100000",
                10,
                "500",
                "50000",
                "0",
            ],
            [
                1781828460000,
                "200.0",
                "204.0",
                "198.0",
                "201.0",
                "1000",
                1781828519999,
                "100000",
                10,
                "500",
                "50000",
                "0",
            ],
        ]

    report = build_path_telemetry_backfill_report(
        redis,
        write=False,
        generated_at="2026-06-19T00:30:00Z",
        fetch_binance_public_klines=True,
        http_get_json=fake_http_get_json,
    )

    assert report["repaired_path_rows"] == 2
    assert report["binance_public_klines_symbol_windows"] == 1
    assert report["binance_public_klines_cache_entries"] == 1
    assert report["binance_public_klines_used_for_rows"] == 2
    assert len(calls) == 1
    assert "startTime=1781827200000" in calls[0][0]
    assert "endTime=1781828520000" in calls[0][0]


def test_opt_in_public_agg_trades_repair_short_interval_without_contained_kline():
    redis = FakeRedis(
        {
            "v2:market:ohlcv_closed:binance:BTCUSDT:1m": [],
            "v2:market:ohlcv:binance:BTCUSDT:1m": [],
        }
    )
    calls = []
    short_trade = _trade(
        exit_time="2026-06-19T00:20:30Z",
        hold_time_seconds=20,
        side="short",
        entry_price=100.0,
        exit_price=99.5,
    )

    def fake_http_get_json(url: str, timeout: float):
        calls.append((url, timeout))
        if "aggTrades" in url:
            return [
                {"a": 1, "p": "99.0", "T": 1781828411000},
                {"a": 2, "p": "101.0", "T": 1781828420000},
            ]
        return []

    enriched, status, used_public = enrich_closed_trade_row(
        redis,
        short_trade,
        generated_at="2026-06-19T00:30:00Z",
        fetch_binance_public_klines=True,
        fetch_binance_public_agg_trades=True,
        http_get_json=fake_http_get_json,
        fetched_at_ms=1781829000000,
    )

    assert status == "repaired"
    assert used_public is True
    assert any("fapi.binance.com/fapi/v1/aggTrades" in call[0] for call in calls)
    assert enriched["path_telemetry_source"] == "BINANCE_USDM_PUBLIC_AGG_TRADES_CONTAINED_PATH_BACKFILL"
    assert enriched["path_telemetry_quality"] == "STRICT_CONTAINED_FINAL_AGG_TRADES_PLUS_ENTRY_EXIT_BOUNDARIES"
    assert enriched["path_telemetry_public_agg_trades_readonly"] is True
    assert enriched["intra_trade_high_price"] == 101.0
    assert enriched["intra_trade_low_price"] == 99.0
    assert enriched["mfe_bps"] == 100.0
    assert enriched["mae_bps"] == 100.0


def test_report_write_updates_only_v2_paper_keys_with_ttls():
    trade = _trade()
    redis = FakeRedis(
        {
            "v2:paper:closed_trades": [trade],
            "v2:paper:outcome_labels": [
                {
                    "outcome_label_id": "outcome-1",
                    "trainer_feedback_id": "feedback-1",
                    "position_id": "position-1",
                    "symbol": "BTCUSDT",
                    "side": "long",
                }
            ],
            "v2:paper:ledger": {
                "closed_trades": [trade],
                "outcome_labels": [{"outcome_label_id": "outcome-1", "trainer_feedback_id": "feedback-1"}],
            },
            "v2:market:ohlcv_closed:binance:BTCUSDT:5m": [
                _closed_candle(1781827500000, 1781827799999, high=105.0, low=99.0),
            ],
            "v2:market:ohlcv:binance:BTCUSDT:5m": [],
        }
    )

    report = build_path_telemetry_backfill_report(redis, write=True, generated_at="2026-06-19T00:30:00Z")

    assert report["writes_redis"] is True
    assert report["writes_exchange_orders"] is False
    assert report["places_real_order"] is False
    assert report["repaired_path_rows"] == 1
    assert report["outcome_label_rows_updated"] == 1
    assert report["ledger_rows_updated"]["closed_trades"] == 1
    assert [call[0] for call in redis.set_calls] == [
        "v2:paper:closed_trades",
        "v2:paper:outcome_labels",
        "v2:paper:ledger",
    ]
    assert [call[2] for call in redis.set_calls] == [1800, 1800, 600]
