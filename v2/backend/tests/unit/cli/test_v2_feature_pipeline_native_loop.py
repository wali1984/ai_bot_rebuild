from __future__ import annotations

import importlib
import json
import re


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.expiries: dict[str, int | None] = {}

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        self.expiries[key] = ex
        return True

    def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    def hgetall(self, key: str) -> dict:
        return {}

    def xrange(self, key: str, min: str = "-", max: str = "+") -> list:  # noqa: A002
        return []

    def scan_iter(self, match: str | None = None, count: int = 500):  # noqa: ARG002
        if match is None:
            yield from list(self.store)
            return
        prefix = match.rstrip("*")
        for key in list(self.store):
            if match.endswith("*") and key.startswith(prefix):
                yield key
            elif key == match:
                yield key


def _market_payload() -> dict:
    return {
        "price": 100.0,
        "ticker_24hr": {
            "lastPrice": "100.0",
            "openPrice": "99.0",
            "highPrice": "101.0",
            "lowPrice": "98.0",
            "prevClosePrice": "99.0",
            "quoteVolume": "1000000",
        },
        "funding": {"lastFundingRate": "0.0001", "markPrice": "100.0", "indexPrice": "100.0"},
        "open_interest": {},
    }


def test_utc_iso_preserves_millisecond_precision() -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")

    value = mod._utc_iso()

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value)


def test_feature_snapshot_without_closed_ohlcv_is_not_trainer_consumable(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert payload["trainer_consumable"] is False
    assert payload["valid_for_prediction"] is False
    assert payload["valid_for_paper"] is False
    assert payload["feature_freshness_state"] == "MISSING_CLOSED_OHLCV"
    assert payload["candle_closed_confirmed"] is False
    assert payload["feature_cutoff"] is None
    assert "ohlcv_closed_window" in payload["missing_feature_flags"]
    assert "candle_closed_confirmed" in payload["missing_feature_flags"]
    assert "feature_cutoff" in payload["missing_feature_flags"]


def test_feature_snapshot_with_closed_ohlcv_carries_cutoff(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    close_ms = int(mod.time.time() * 1000) - 10_000
    open_ms = close_ms - 60_000
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps([
        {
            "open_time": open_ms,
            "close_time": close_ms,
            "open": "99.0",
            "high": "101.0",
            "low": "98.0",
            "close": "100.0",
            "volume": "1000",
            "is_closed": True,
        }
    ])
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert payload["trainer_consumable"] is True
    assert payload["valid_for_prediction"] is True
    assert payload["valid_for_paper"] is True
    assert payload["feature_freshness_state"] == "CURRENT"
    assert payload["candle_closed_confirmed"] is True
    assert payload["feature_cutoff"] == mod._ms_to_utc_iso(close_ms)  # noqa: SLF001


def test_feature_snapshot_emits_closed_window_atr_percentile(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    latest_close_ms = int(mod.time.time() * 1000) - 10_000
    rows = []
    for index in range(45):
        close_ms = latest_close_ms - (44 - index) * 60_000
        open_ms = close_ms - 60_000
        close = 100.0 + index * 0.2
        width = 0.8 + (index % 9) * 0.08
        rows.append(
            {
                "open_time": open_ms,
                "close_time": close_ms,
                "available_at": close_ms + 1_000,
                "open": f"{close - 0.1}",
                "high": f"{close + width}",
                "low": f"{close - width * 0.7}",
                "close": f"{close}",
                "volume": f"{1000 + index}",
                "is_closed": True,
            }
        )
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps(rows)
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    features = payload["features"]
    assert payload["trainer_consumable"] is True
    assert payload["latest_unclosed_kline_excluded"] is False
    assert features["atr_percentile"] is not None
    assert 0.0 <= features["atr_percentile"] <= 1.0
    assert "atr_percentile" not in payload["missing_feature_flags"]


def test_feature_snapshot_skips_closed_candle_available_after_decision(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    now_ms = int(mod.time.time() * 1000)
    older_close_ms = now_ms - 70_000
    newer_close_ms = now_ms - 10_000
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps([
        {
            "open_time": older_close_ms - 60_000,
            "close_time": older_close_ms,
            "available_at": older_close_ms + 1_000,
            "open": "99.0",
            "high": "101.0",
            "low": "98.0",
            "close": "100.0",
            "volume": "1000",
            "is_closed": True,
        },
        {
            "open_time": newer_close_ms - 60_000,
            "close_time": newer_close_ms,
            "available_at": now_ms + 60_000,
            "open": "100.0",
            "high": "102.0",
            "low": "99.0",
            "close": "101.0",
            "volume": "1200",
            "is_closed": True,
        },
    ])
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert payload["trainer_consumable"] is True
    assert payload["feature_freshness_state"] == "CURRENT"
    assert payload["feature_cutoff"] == mod._ms_to_utc_iso(older_close_ms)  # noqa: SLF001


def test_feature_snapshot_falls_back_to_finalized_raw_ohlcv(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    close_ms = int(mod.time.time() * 1000) - 10_000
    open_ms = close_ms - 60_000
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv:binance:BTCUSDT:1m"] = json.dumps(
        [[open_ms, "99.0", "101.0", "98.0", "100.0", "1000", close_ms, "100000", 20, "500", "50000", "0"]]
    )
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert payload["trainer_consumable"] is True
    assert payload["valid_for_prediction"] is True
    assert payload["feature_freshness_state"] == "CURRENT"
    assert payload["feature_cutoff"] == mod._ms_to_utc_iso(close_ms)  # noqa: SLF001


def test_feature_snapshot_carries_point_in_time_cost_evidence_from_orderbook(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    close_ms = int(mod.time.time() * 1000) - 10_000
    open_ms = close_ms - 60_000
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:orderbook:BTCUSDT"] = json.dumps(
        {
            "bids": [["99.95", "10"]],
            "asks": [["100.05", "10"]],
        }
    )
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps([
        {
            "open_time": open_ms,
            "close_time": close_ms,
            "open": "99.0",
            "high": "101.0",
            "low": "98.0",
            "close": "100.0",
            "volume": "1000",
            "is_closed": True,
        }
    ])
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    features = payload["features"]
    assert payload["trainer_consumable"] is True
    assert features["fee_bps"] == mod._configured_fee_bps()  # noqa: SLF001
    assert abs(features["expected_slippage_bps"] - 5.0) < 1e-9
    assert "fee_bps" not in payload["missing_feature_flags"]
    assert "expected_slippage_bps" not in payload["missing_feature_flags"]
    assert payload["market_cost_evidence_source_fields"] == {
        "fee_bps": mod.CONFIGURED_FEE_BPS_SOURCE,
        "expected_slippage_bps": "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY(bid_ask_spread_bps)",
    }


def test_feature_snapshot_merges_realtime_ingestors_for_trainer(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    close_ms = int(mod.time.time() * 1000) - 10_000
    open_ms = close_ms - 60_000
    market = _market_payload()
    market["open_interest"] = {"openInterest": "123.45"}
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(market)
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps([
        {
            "open_time": open_ms,
            "close_time": close_ms,
            "open": "99.0",
            "high": "101.0",
            "low": "98.0",
            "close": "100.0",
            "volume": "100.0",
            "quote_volume": "10000.0",
            "num_trades": "40",
            "taker_buy_base_vol": "60.0",
            "taker_buy_quote_vol": "6000.0",
            "is_closed": True,
        }
    ])
    fake.store["v2:orderbook:features:binance:BTCUSDT"] = json.dumps(
        {
            "best_bid": "99.9",
            "best_ask": "100.1",
            "mid": "100.0",
            "best_bid_size": "5",
            "best_ask_size": "6",
            "spread_bps": "1.2",
            "depth_total_usd": "100000",
            "depth_5_bid_usd": "52000",
            "depth_5_ask_usd": "48000",
            "depth_slope": "0.12",
            "estimated_price_impact_bps": "0.9",
            "sequence_gap_flag": "0",
            "source_latency_ms": "11",
        }
    )
    fake.store["v2:microstructure:trust_score:BTCUSDT:1m"] = json.dumps(
        {
            "microstructure_trust_score": "0.73",
            "feed_latency_ms": "12",
            "spread_instability": "0.1",
            "depth_persistence": "0.82",
            "cancel_pressure": "0.2",
            "book_trade_divergence": "0.03",
            "cross_venue_confirmation": "0.91",
            "sweep_risk": "0.14",
            "post_sweep_reversal_probability": "0.23",
            "realized_slippage_error": "-0.4",
        }
    )
    fake.store["v2:microstructure:trade_tape_confirmation:BTCUSDT"] = json.dumps(
        {
            "book_trade_divergence_score": "0.04",
            "trade_imbalance": "0.12",
        }
    )
    fake.store["v2:altdata:public_intel:symbol:BTCUSDT"] = json.dumps(
        {
            "public_intel_score": "0.61",
            "defillama_liquidity_score": "0.71",
            "fear_greed_score": "0.52",
            "btc_mempool_pressure_score": "0.33",
        }
    )
    fake.store["v2:altdata:aicoin:symbol:BTCUSDT"] = json.dumps(
        {
            "aicoin_market_activity_score": "0.4",
            "aicoin_order_flow_score": "0.8",
        }
    )
    fake.store["v2:altdata:whale_walls:symbol:BTCUSDT"] = json.dumps(
        {
            "whale_wall_score": "0.7",
            "whale_bid_pressure_score": "0.65",
            "whale_ask_pressure_score": "0.35",
        }
    )
    fake.store["v2:altdata:santiment:symbol:BTCUSDT"] = json.dumps(
        {
            "santiment_social_volume_score": "0.74",
            "santiment_whale_activity_score": "0.62",
            "santiment_sentiment_score": "0.4",
            "santiment_onchain_activity_score": "0.81",
            "santiment_exchange_inflow_risk_score": "0.64",
            "santiment_supply_on_exchanges_score": "0.87",
            "santiment_social_volume_total": "1200",
            "santiment_exchange_inflow": "2500000",
            "santiment_percent_of_total_supply_on_exchanges": "13",
        }
    )
    fake.store["v2:altdata:symbol_score:BTCUSDT"] = json.dumps(
        {
            "surf_market_price_signal_score": "0.55",
            "coinglass_derivatives_score": "0.66",
            "coingecko_discovery_score": "0.44",
            "provider_availability_score": "0.9",
            "santiment_social_volume_score": "0.74",
        }
    )
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    features = payload["features"]
    assert payload["trainer_consumable"] is True
    assert features["open_interest"] == 123.45
    assert features["taker_sell_base_vol"] == 40.0
    assert features["taker_sell_quote_vol"] == 4000.0
    assert features["taker_buy_ratio"] == 0.6
    assert features["ob_best_bid"] == 99.9
    assert features["ob_best_ask"] == 100.1
    assert features["best_bid_size"] == 5.0
    assert features["spread_bps"] == 1.2
    assert features["microprice"] == 100.0
    assert abs(features["expected_slippage_bps"] - 0.6) < 1e-9
    assert features["microstructure_trust_score"] == 0.73
    assert features["feed_latency_ms"] == 12.0
    assert features["realized_slippage_error"] == -0.4
    assert features["depth_vs_tape_divergence"] == 0.04
    assert features["tape_imbalance"] == 0.12
    assert features["order_flow_imbalance"] == 0.12
    assert features["public_intel_score"] == 0.61
    assert features["whale_wall_score"] == 0.7
    assert features["santiment_social_volume_score"] == 0.74
    assert features["santiment_sentiment_score"] == 0.4
    assert features["santiment_exchange_inflow_risk_score"] == 0.64
    assert features["santiment_supply_on_exchanges_score"] == 0.87
    assert abs(features["aicoin_score"] - 0.6) < 1e-9
    assert features["surf_score"] == 0.55
    assert features["coinglass_derivatives_score"] == 0.66
    assert {
        "v2:orderbook:features",
        "v2:microstructure:trust_score",
        "v2:microstructure:trade_tape_confirmation",
        "v2:altdata:public_intel",
        "v2:altdata:aicoin",
        "v2:altdata:whale_walls",
        "v2:altdata:santiment",
        "v2:altdata:symbol_score",
    }.issubset(set(payload["external_v2_sources_present"]))
    assert "open_interest" not in payload["missing_feature_flags"]
    assert "public_intel_score" not in payload["missing_feature_flags"]
    assert "microstructure_trust_score" not in payload["missing_feature_flags"]
    assert "aicoin_score" not in payload["missing_feature_flags"]
    assert "santiment_social_volume_score" not in payload["missing_feature_flags"]


def test_feature_snapshot_skips_stale_santiment_for_decision_features(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    close_ms = int(mod.time.time() * 1000) - 10_000
    open_ms = close_ms - 60_000
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps([
        {
            "open_time": open_ms,
            "close_time": close_ms,
            "open": "99.0",
            "high": "101.0",
            "low": "98.0",
            "close": "100.0",
            "volume": "1000",
            "is_closed": True,
        }
    ])
    fake.store["v2:altdata:santiment:symbol:BTCUSDT"] = json.dumps(
        {
            "santiment_social_volume_score": "0.74",
            "provider_freshness_seconds": 31 * 24 * 60 * 60,
            "stale_feature_flags": ["sanbase_pro_delayed_data_window"],
        }
    )
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert "v2:altdata:santiment_stale_skipped" in payload["external_v2_sources_present"]
    assert "santiment_social_volume_score" not in payload["features"]


def test_feature_snapshot_does_not_use_future_raw_ohlcv(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    now_ms = int(mod.time.time() * 1000)
    close_ms = now_ms + 60_000
    open_ms = close_ms - 60_000
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv:binance:BTCUSDT:1m"] = json.dumps(
        [[open_ms, "99.0", "101.0", "98.0", "100.0", "1000", close_ms, "100000", 20, "500", "50000", "0"]]
    )
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert payload["trainer_consumable"] is False
    assert payload["valid_for_prediction"] is False
    assert payload["feature_freshness_state"] == "MISSING_CLOSED_OHLCV"


def test_feature_snapshot_with_stale_closed_ohlcv_is_not_consumable(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps([
        {
            "open_time": 1_781_000_000_000,
            "close_time": 1_781_000_059_999,
            "open": "99.0",
            "high": "101.0",
            "low": "98.0",
            "close": "100.0",
            "volume": "1000",
            "is_closed": True,
        }
    ])
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert payload["trainer_consumable"] is False
    assert payload["valid_for_prediction"] is False
    assert payload["valid_for_paper"] is False
    assert payload["feature_freshness_state"] == "STALE_CLOSED_OHLCV"
    assert payload["candle_closed_confirmed"] is True
    assert payload["feature_cutoff"] == mod._ms_to_utc_iso(1_781_000_059_999)  # noqa: SLF001
    assert payload["stale_feature_flags"] == ["ohlcv_closed_window"]
    assert "ohlcv_closed_window_stale" in payload["missing_feature_flags"]


def test_finalized_raw_ohlcv_bridge_writes_closed_rows_and_skips_future() -> None:
    bridge = importlib.import_module("v2.backend.app.cli.v2_closed_candle_resampler")
    fake = FakeRedis()
    now_ms = 1_781_000_000_000
    closed_open = now_ms - 4 * 60 * 60 * 1000
    closed_close = now_ms - 1_000
    future_open = now_ms
    future_close = now_ms + 4 * 60 * 60 * 1000 - 1
    fake.store["v2:market:ohlcv:binance:BTCUSDT:4h"] = json.dumps(
        [
            [closed_open, "100", "102", "99", "101", "12", closed_close, "1200", 10, "6", "600", "0"],
            [future_open, "101", "103", "100", "102", "8", future_close, "816", 8, "4", "408", "0"],
        ]
    )

    result = bridge.copy_finalized_raw_ohlcv(
        fake,
        symbol="BTCUSDT",
        timeframe="4h",
        now_ms_value=now_ms,
    )

    rows = json.loads(fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:4h"])
    assert result["rows_after"] == 1
    assert result["skipped_future_or_open_rows"] == 1
    assert rows[0]["candle_closed_confirmed"] is True
    assert rows[0]["candle_close_time"] == closed_close
    assert rows[0]["close"] == 101.0


def test_feature_snapshot_uses_finalized_raw_ohlcv_bridge(monkeypatch) -> None:
    bridge = importlib.import_module("v2.backend.app.cli.v2_closed_candle_resampler")
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    now_ms = int(mod.time.time() * 1000)
    close_ms = now_ms - 10_000
    open_ms = close_ms - 4 * 60 * 60 * 1000
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv:binance:BTCUSDT:4h"] = json.dumps(
        [[open_ms, "99", "101", "98", "100", "1000", close_ms, "100000", 20, "500", "50000", "0"]]
    )
    bridge.copy_finalized_raw_ohlcv(
        fake,
        symbol="BTCUSDT",
        timeframe="4h",
        now_ms_value=now_ms,
    )
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "4h", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:4h"])
    assert payload["trainer_consumable"] is True
    assert payload["valid_for_paper"] is True
    assert payload["feature_freshness_state"] == "CURRENT"
    assert payload["feature_cutoff"] == mod._ms_to_utc_iso(close_ms)  # noqa: SLF001


class TestReadKlinesTieBreak:
    """F-0009: ohlcv_closed key history is TTL-truncated for intervals longer
    than the key TTL; on freshness ties _read_klines must prefer the deeper
    raw buffer so history-window features (atr_percentile) can compute."""

    class _FakeRedis:
        def __init__(self, store):
            self._store = store

        def get(self, key):
            return self._store.get(key)

    @staticmethod
    def _kline(close_ms: int) -> list:
        # 12-field Binance kline row; index 6 is close_time
        return [close_ms - 60_000, "1", "2", "0.5", "1.5", "10", close_ms, "10", 5, "5", "5", "0"]

    def test_tie_prefers_deeper_raw_buffer(self):
        import json as _json
        import time as _time
        import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

        now_ms = int(_time.time() * 1000)
        latest = now_ms - 10_000
        raw = [self._kline(latest - i * 900_000) for i in range(50)][::-1]
        closed = [self._kline(latest)]  # TTL-truncated: only the newest row
        store = {
            f"{fp.V2_REDIS_PREFIX}market:ohlcv:binance:XUSDT:15m": _json.dumps(raw),
            f"{fp.V2_REDIS_PREFIX}market:ohlcv_closed:binance:XUSDT:15m": _json.dumps(closed),
        }
        rows = fp._read_klines(self._FakeRedis(store), "XUSDT", "15m", decision_ms=now_ms)
        assert len(rows) == 50, "tie must resolve to the deeper raw buffer"

    def test_newer_closed_key_still_wins(self):
        import json as _json
        import time as _time
        import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

        now_ms = int(_time.time() * 1000)
        raw = [self._kline(now_ms - 900_000)]
        closed = [self._kline(now_ms - 10_000), self._kline(now_ms - 910_000)]
        store = {
            f"{fp.V2_REDIS_PREFIX}market:ohlcv:binance:XUSDT:15m": _json.dumps(raw),
            f"{fp.V2_REDIS_PREFIX}market:ohlcv_closed:binance:XUSDT:15m": _json.dumps(closed),
        }
        rows = fp._read_klines(self._FakeRedis(store), "XUSDT", "15m", decision_ms=now_ms)
        assert len(rows) == 2, "closed key with strictly newer candle must win"
