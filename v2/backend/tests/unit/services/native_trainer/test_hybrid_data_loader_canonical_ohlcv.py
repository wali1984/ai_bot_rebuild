from __future__ import annotations

import json
from typing import Any

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    V2HybridTrainerDataLoader,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.safety import (
    V2OnlyJsonIO,
)


class _RecordingRedis:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values
        self.read_keys: list[str] = []

    def get(self, key: str) -> Any:
        self.read_keys.append(key)
        return self.values.get(key)

    def hgetall(self, _key: str) -> dict[str, Any]:
        return {}


def _closed_row(*, close: float) -> dict[str, Any]:
    return {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "candle_open_time": 0,
        "candle_close_time": 59_999,
        "is_closed": True,
        "closed_candle": True,
        "candle_closed_confirmed": True,
        "close": close,
    }


def test_closed_candle_reader_never_reads_or_merges_legacy_raw_surface() -> None:
    canonical_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    legacy_key = "v2:market:ohlcv:binance:BTCUSDT:1m"
    redis = _RecordingRedis(
        {
            canonical_key: json.dumps([_closed_row(close=101.0)]),
            legacy_key: json.dumps([_closed_row(close=999.0)]),
        }
    )
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=redis))

    rows, selected_key = loader._read_closed_candle_series(  # noqa: SLF001
        symbol="BTCUSDT",
        timeframe="1m",
    )

    assert selected_key == canonical_key
    assert rows == [_closed_row(close=101.0)]
    assert redis.read_keys == [canonical_key]


def test_closed_candle_reader_keeps_missing_canonical_surface_missing() -> None:
    canonical_key = "v2:market:ohlcv_closed:binance:BTCUSDT:4h"
    legacy_key = "v2:market:ohlcv:binance:BTCUSDT:4h"
    redis = _RecordingRedis({legacy_key: json.dumps([_closed_row(close=999.0)])})
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=redis))

    rows, selected_key = loader._read_closed_candle_series(  # noqa: SLF001
        symbol="BTCUSDT",
        timeframe="4h",
    )

    assert rows is None
    assert selected_key == canonical_key
    assert redis.read_keys == [canonical_key]


def test_closed_candle_reader_rejects_unfinished_canonical_row() -> None:
    canonical_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    unfinished = _closed_row(close=101.0)
    unfinished["is_closed"] = False
    unfinished["closed_candle"] = False
    unfinished["candle_closed_confirmed"] = False
    redis = _RecordingRedis({canonical_key: json.dumps([unfinished])})
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=redis))

    rows, selected_key = loader._read_closed_candle_series(  # noqa: SLF001
        symbol="BTCUSDT",
        timeframe="1m",
    )

    assert rows == []
    assert selected_key == canonical_key
    assert redis.read_keys == [canonical_key]


def test_legacy_provider_namespaces_are_never_read_by_full_payload_loader() -> None:
    legacy_payload = json.dumps(
        {
            "features": {
                "coinapi_wsds_tape_imbalance": 0.99,
                "moralis_exchange_inflow_usd": 1_000_000.0,
            },
            "available_at": "2026-07-18T11:59:59Z",
            "feature_cutoff": "2026-07-18T11:59:58Z",
            "postcommit_receipt_bound": True,
            "trainer_consumable": True,
        }
    )
    fenced_keys = {
        "v2:market:coinapi:BTCUSDT",
        "v2:market:coinapi:wsds:BTCUSDT",
        "v2:features:moralis:BTCUSDT:1m",
        "v2:smart_money:signals:BTCUSDT",
    }
    redis = _RecordingRedis({key: legacy_payload for key in fenced_keys})
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=redis))

    payloads = loader.load_payloads(symbol="BTCUSDT", timeframe="1m")

    assert fenced_keys.isdisjoint(redis.read_keys)
    assert "coinapi" not in payloads
    assert "moralis_features" not in payloads
    assert "smart_money_signals" not in payloads
    assert fenced_keys.isdisjoint(set(payloads["_keys"].values()))


def test_snapshot_batch_inventory_excludes_legacy_provider_namespaces() -> None:
    loader = V2HybridTrainerDataLoader()

    keys = loader._snapshot_request_keys(  # noqa: SLF001
        symbol="BTCUSDT",
        timeframe="1m",
        latest_key="v2:features:latest:BTCUSDT:1m",
    )

    assert not any(key.startswith("v2:market:coinapi") for key in keys)
    assert not any(key.startswith("v2:features:moralis") for key in keys)
    assert not any(key.startswith("v2:smart_money:signals") for key in keys)
