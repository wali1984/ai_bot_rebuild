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
