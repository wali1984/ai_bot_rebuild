from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.cli import v2_full_talib_ta_loop as worker
from v2.backend.app.services.full_talib_ta.service import (
    build_full_talib_ta_payload,
    normalize_ohlcv_rows,
)


def _klines(count: int = 120) -> list[list[Any]]:
    out: list[list[Any]] = []
    base_ts = 1_780_000_000_000
    for i in range(count):
        price = 100.0 + (i * 0.25) + ((-1) ** i) * 0.1
        out.append(
            [
                base_ts + i * 60_000,
                str(price - 0.2),
                str(price + 0.5),
                str(price - 0.7),
                str(price),
                str(1000.0 + i),
            ]
        )
    return out


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = int(ex)
        return True

    def scan_iter(self, match: str, count: int = 500):  # noqa: ARG002
        prefix = match[:-1] if match.endswith("*") else match
        for key in sorted(self.store):
            if key.startswith(prefix):
                yield key


def test_normalize_accepts_binance_kline_rows() -> None:
    candles = normalize_ohlcv_rows(_klines(3))
    assert len(candles) == 3
    assert candles[0].open > 0
    assert candles[-1].ts_ms is not None


def test_full_talib_payload_reaches_legacy_field_depth() -> None:
    result = build_full_talib_ta_payload(
        symbol="BTCUSDT",
        timeframe="1m",
        candles=_klines(140),
        source_ohlcv_key="v2:market:ohlcv:binance:BTCUSDT:1m",
    )
    payload = result.to_payload(source_ohlcv_key="v2:market:ohlcv:binance:BTCUSDT:1m")
    assert payload["classification"] in {
        "V2_FULL_TALIB_TA_OK",
        "V2_FULL_TALIB_TA_PARTIAL_OK",
        "BLOCKED_TALIB_IMPORT_FAILED",
    }
    if payload["classification"] != "BLOCKED_TALIB_IMPORT_FAILED":
        assert payload["field_count"] >= 100
        assert payload["talib_function_count"] >= 150
        assert payload["computed_function_count"] >= 100
        assert payload["indicators"]["ta_RSI_14"] > 0
        assert "ta_MACD_12_26_9_macd" in payload["indicators"]
    else:
        assert "talib_import" in payload["skipped_functions"]
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["writes_legacy_redis"] is False
    assert payload["places_real_order"] is False


def test_run_once_writes_v2_ta_keys_and_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRedis()
    fake.store["v2:market:ohlcv:binance:BTCUSDT:1m"] = json.dumps(_klines(120))
    monkeypatch.setattr(worker, "PUBLIC_STATUS_PATH", tmp_path / "public.json")
    monkeypatch.setattr(worker, "LOCAL_STATUS_PATH", tmp_path / "local.json")
    status = worker.run_once(
        symbols_arg="BTCUSDT",
        timeframes_arg="1m",
        redis_client=fake,
    )
    assert status["classification"] in {
        "V2_FULL_TALIB_TA_LIVE_OK",
        "V2_FULL_TALIB_TA_LIVE_PARTIAL",
    }
    # 4 keys: ta, ta_full, technical_analysis, plus the repaint-free
    # ta_closed variant (closed-candle-confirmed rows).
    assert status["keys_written_count"] == 4
    assert "v2:features:ta:BTCUSDT:1m" in fake.store
    assert "v2:features:ta_closed:BTCUSDT:1m" in fake.store
    assert "v2:features:ta_full:BTCUSDT:1m" in fake.store
    assert "v2:technical_analysis:BTCUSDT:1m" in fake.store
    assert "v2:features:ta:heartbeat" in fake.store
    for key in fake.store:
        assert key.startswith("v2:")
    payload = json.loads(fake.store["v2:features:ta:BTCUSDT:1m"])
    assert payload["classification"] in {
        "V2_FULL_TALIB_TA_OK",
        "V2_FULL_TALIB_TA_PARTIAL_OK",
        "BLOCKED_TALIB_IMPORT_FAILED",
    }
    if payload["classification"] != "BLOCKED_TALIB_IMPORT_FAILED":
        assert payload["field_count"] >= 100
        assert payload["trainer_consumable"] is True
    assert json.loads((tmp_path / "public.json").read_text())["worker_id"] == worker.WORKER_ID


def test_run_once_merges_closed_history_when_live_window_is_below_ta_minimum(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRedis()
    history = _klines(100)
    fake.store["v2:market:ohlcv:binance:BTCUSDT:1h"] = json.dumps(history[-50:])
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1h"] = json.dumps(history)
    monkeypatch.setattr(worker, "PUBLIC_STATUS_PATH", tmp_path / "public.json")
    monkeypatch.setattr(worker, "LOCAL_STATUS_PATH", tmp_path / "local.json")

    worker.run_once(
        symbols_arg="BTCUSDT",
        timeframes_arg="1h",
        redis_client=fake,
    )

    payload = json.loads(fake.store["v2:features:ta_full:BTCUSDT:1h"])
    assert payload["candle_count"] == 100
    assert payload["classification"] != "BLOCKED_INSUFFICIENT_OHLCV_HISTORY"
