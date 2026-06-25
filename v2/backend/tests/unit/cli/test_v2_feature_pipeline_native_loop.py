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
