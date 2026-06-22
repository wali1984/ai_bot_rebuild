from __future__ import annotations

import pytest

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    V2UnifiedFeatureTensorBuilder,
)


def _feature(record, name: str) -> tuple[float, int, str]:
    index = record.feature_names.index(name)
    return record.values[index], record.missing_mask[index], record.source_labels[index]


def test_native_trainer_tensor_consumes_direct_coinank_current_features() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BTCUSDT",
        timeframe="15m",
        payloads={
            "coinank_funding": {
                "data": {"success": True, "code": "1", "data": [{"fundingRate": 0.00031}]}
            },
            "coinank_open_interest": {
                "data": {
                    "success": True,
                    "code": "1",
                    "data": [
                        {"coinValue": 1000.0, "close": 1000.0},
                        {"coinValue": 1110.0, "close": 1110.0},
                    ],
                }
            },
            "coinank_long_short": {
                "data": {
                    "success": True,
                    "code": "1",
                    "data": [
                        {"open": 1.05, "high": 1.2, "low": 1.0, "close": 1.17},
                    ],
                }
            },
            "coinank_liquidations": {
                "data": {"success": True, "code": "1", "data": [{"longTurnover": 20.0, "shortTurnover": 7.5}]}
            },
            "coinank_market_order_flow": {
                "data": {"success": True, "code": "1", "data": [[1, 80.0, 20.0]]}
            },
        },
    )

    value, missing, source = _feature(record, "funding_rate")
    assert value == pytest.approx(0.00031)
    assert missing == 0
    assert source == "latest:coinank:funding"

    value, missing, source = _feature(record, "open_interest")
    assert value == pytest.approx(1110.0)
    assert missing == 0
    assert source == "latest:coinank:open_interest"

    value, missing, source = _feature(record, "oi_change_pct")
    assert value == pytest.approx(0.11)
    assert missing == 0
    assert source == "latest:coinank:open_interest"

    value, missing, source = _feature(record, "long_short_ratio")
    assert value == pytest.approx(1.17)
    assert missing == 0
    assert source == "latest:coinank:long_short"

    value, missing, source = _feature(record, "last_liq_bps_24h")
    assert value == pytest.approx(27.5)
    assert missing == 0
    assert source == "latest:coinank:liquidations"

    value, missing, source = _feature(record, "order_flow_imbalance")
    assert value == pytest.approx(0.6)
    assert missing == 0
    assert source == "latest:coinank:market_order_flow"


def test_zero_volume_closed_candle_emits_zero_taker_ratios() -> None:
    record = V2UnifiedFeatureTensorBuilder().build(
        symbol="BANKUSDT",
        timeframe="1m",
        payloads={
            "ohlcv": {
                "open": 0.04,
                "high": 0.04,
                "low": 0.04,
                "close": 0.04,
                "volume": 0.0,
                "quote_volume": 0.0,
                "num_trades": 0,
                "taker_buy_base_vol": 0.0,
                "taker_buy_quote_vol": 0.0,
                "is_closed": True,
                "closed_candle": True,
                "candle_closed_confirmed": True,
                "candle_close_time": 1_781_380_679_999,
                "available_at": 1_781_380_679_999,
            }
        },
    )

    value, missing, source = _feature(record, "taker_buy_ratio")
    assert value == pytest.approx(0.0)
    assert missing == 0
    assert source == "v2:market:ohlcv"

    value, missing, source = _feature(record, "taker_sell_ratio")
    assert value == pytest.approx(0.0)
    assert missing == 0
    assert source == "v2:market:ohlcv"
