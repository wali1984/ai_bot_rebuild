from __future__ import annotations

import json

from v2.backend.app.services.operator_truth.trade_derivatives_runtime import (
    build_derivatives_payload,
    build_trade_terminal_payload,
)


class FakeRedis:
    def __init__(self) -> None:
        self.data = {
            "v2:market:coinapi:wsds:BTCUSDT": {
                "mid_px": 100.0,
                "best_bid_px": 99.9,
                "best_ask_px": 100.1,
                "book_bid_sum_5": 10.0,
                "book_ask_sum_5": 7.0,
                "imbalance_5": 0.17647,
            },
            "v2:market:funding:BTCUSDT": {
                "lastFundingRate": "0.0001",
                "markPrice": "100.0",
                "indexPrice": "99.5",
                "time": 1781042158000,
            },
            "v2:market:open_interest:BTCUSDT": {
                "openInterest": "12345.0",
                "time": 1781042158000,
            },
            "v2:market:prices:BTCUSDT": {
                "ticker_24hr": {"lastPrice": "100.0", "quoteVolume": "500000.0"},
            },
            "v2:market:ohlcv:binance:BTCUSDT:1m": [
                [1781042100000, "99", "101", "98", "100", "42.5", 1781042159999, "4250.0"]
            ],
            "v2:liquidations:levels:BTCUSDT:1m": {
                "liquidation_long_level": 95.0,
                "liquidation_short_level": 105.0,
                "liquidation_long_distance_pct": 0.05,
            },
        }

    def get(self, key: str) -> str | None:
        value = self.data.get(key)
        return json.dumps(value) if value is not None else None

    def scan_iter(self, match: str, count: int = 500):  # noqa: ARG002
        prefix = match.replace("*", "")
        for key in sorted(self.data):
            if key.startswith(prefix):
                yield key

    def xlen(self, key: str) -> int:  # noqa: ARG002
        return 2

    def xrevrange(self, key: str, count: int = 50):  # noqa: ARG002
        return [("1-0", {"symbol": "BTCUSDT"}), ("0-0", {"symbol": "ETHUSDT"})]


class CoinankOnlyRedis(FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        for key in (
            "v2:market:funding:BTCUSDT",
            "v2:market:open_interest:BTCUSDT",
        ):
            self.data.pop(key, None)
        self.data.update(
            {
                "latest:coinank:funding:BTCUSDT:15m": {
                    "data": {"success": True, "code": "1", "data": [{"fundingRate": 0.00023, "fr": 0.00023}]}
                },
                "latest:coinank:open_interest:BTCUSDT:15m": {
                    "data": {
                        "success": True,
                        "code": "1",
                        "data": [
                            {"coinValue": 1000.0, "close": 1000.0},
                            {"coinValue": 1100.0, "close": 1100.0},
                        ],
                    }
                },
                "latest:coinank:long_short:BTCUSDT:15m": {
                    "data": {
                        "success": True,
                        "code": "1",
                        "data": [
                            {"open": 1.1, "high": 1.3, "low": 1.0, "close": 1.25},
                        ],
                    }
                },
                "latest:coinank:liquidations:BTCUSDT:15m": {
                    "data": {
                        "success": True,
                        "code": "1",
                        "data": [{"longTurnover": 10.0, "shortTurnover": 5.0}],
                    }
                },
            }
        )


def test_trade_terminal_payload_merges_current_sources() -> None:
    payload = build_trade_terminal_payload("BTCUSDT", client=FakeRedis())

    assert payload["last_price"] == 100.0
    assert payload["bid"] == 99.9
    assert payload["ask"] == 100.1
    assert payload["funding_rate"] == 0.0001
    assert payload["open_interest"] == 12345.0
    assert payload["volume_1m"] == 42.5
    assert payload["quote_volume_24h"] == 500000.0
    assert payload["liquidation_level_count"] == 1
    assert payload["liquidation_event_count"] == 1
    assert payload["safety"]["real_orders"] is False
    assert payload["safety"]["test_order"] is False
    assert payload["safety"]["leverage_margin_mutation"] is False


def test_derivatives_payload_exposes_typed_modules() -> None:
    payload = build_derivatives_payload(client=FakeRedis(), symbols=["BTCUSDT"])

    assert payload["modules"]["funding"]["data_status"] == "CURRENT_OR_RECENT"
    assert payload["modules"]["open_interest"]["data_status"] == "CURRENT_OR_RECENT"
    assert payload["modules"]["basis"]["data_status"] == "CURRENT_OR_RECENT"
    assert payload["modules"]["liquidations"]["data_status"] == "CURRENT_OR_RECENT"
    assert payload["exchanges"]["rows"]
    assert payload["safety"]["old_redis_write"] is False


def test_trade_and_derivatives_payloads_use_direct_coinank_fallbacks() -> None:
    client = CoinankOnlyRedis()

    trade = build_trade_terminal_payload("BTCUSDT", client=client)
    derivatives = build_derivatives_payload(client=client, symbols=["BTCUSDT"])

    assert trade["funding_rate"] == 0.00023
    assert trade["funding_source"] == "latest:coinank:funding:BTCUSDT:15m"
    assert trade["open_interest"] == 1100.0
    assert trade["oi_source"] == "latest:coinank:open_interest:BTCUSDT:15m"
    assert trade["open_interest_change_pct"] == 10.0
    assert trade["long_short_ratio"] == 1.25
    assert trade["coinank_liquidation_turnover_latest"] == 15.0
    assert derivatives["modules"]["funding"]["data_status"] == "CURRENT_OR_RECENT"
    assert derivatives["modules"]["open_interest"]["rows"][0]["source_key"] == "latest:coinank:open_interest:BTCUSDT:15m"
    assert derivatives["modules"]["long_short"]["rows"][0]["long_short_ratio"] == 1.25
