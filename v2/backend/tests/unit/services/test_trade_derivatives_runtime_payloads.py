from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from v2.backend.app.services.operator_truth.trade_derivatives_runtime import (
    _coinank_symbol_intel,
    _global_regime,
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


def test_coinank_operator_truth_masks_invalid_global_snapshot() -> None:
    client = FakeRedis()
    client.data["v2:coinank:global:latest"] = {
        "actual_payload_present": True,
        "is_fresh": False,
        "coverage_complete": True,
        "temporal_contract_valid": True,
        "available_at": "2026-07-20T05:00:00Z",
        "feature_cutoff": "2026-07-20T04:00:00Z",
        "market_regime_context": {
            "total_open_interest_usd": 99_000_000.0,
            "aggregate_long_short_ratio": 2.0,
        },
        "members": {
            "market_sentiment": {"value": 5.5e16, "valid": False},
        },
    }

    regime = _global_regime(client)

    assert regime["data_status"] == "INVALID_OR_STALE_GLOBAL_REGIME_SOURCE"
    assert regime["total_open_interest_usd"] is None
    assert regime["aggregate_long_short_ratio"] is None
    assert regime["market_sentiment"] is None
    assert regime["missing_reason_if_any"] == "COINANK_GLOBAL_CONTRACT_INVALID_OR_STALE"


def test_coinank_operator_truth_preserves_unknown_oi_unit_and_validates_usd_fields() -> None:
    client = FakeRedis()
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(seconds=60)).isoformat().replace("+00:00", "Z")
    available = (now - timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    generated = (now - timedelta(seconds=20)).isoformat().replace("+00:00", "Z")
    client.data["v2:coinank:symbol:BTCUSDT"] = {
        "actual_payload_present": True,
        "feature_eligible": True,
        "temporal_contract_valid": True,
        "feature_cutoff": cutoff,
        "available_at": available,
        "generated_at": generated,
        "coinank_derivatives_score": 0.75,
        "features": {
            "coinank_open_interest": 12_345.0,
            "coinank_liquidation_long_turnover": 100.0,
            "coinank_liquidation_short_turnover": 40.0,
            "coinank_liquidation_imbalance_usd": 60.0,
        },
        "feature_units": {
            "coinank_open_interest": "provider_reported_open_interest_unit_unknown",
            "coinank_liquidation_long_turnover": "usd",
            "coinank_liquidation_short_turnover": "usd",
            "coinank_liquidation_imbalance_usd": "usd",
        },
    }

    intel = _coinank_symbol_intel(client, "BTCUSDT")

    assert intel["data_status"] == "CURRENT_OR_RECENT"
    assert intel["coinank_open_interest"] == 12_345.0
    assert intel["coinank_open_interest_unit"] == "provider_reported_open_interest_unit_unknown"
    assert intel["coinank_open_interest_usd"] is None
    assert intel["coinank_long_turnover_usd"] == 100.0
    assert intel["coinank_short_turnover_usd"] == 40.0
    assert intel["coinank_liquidation_imbalance_usd"] == 60.0

    client.data["v2:coinank:symbol:BTCUSDT"]["feature_eligible"] = False
    held = _coinank_symbol_intel(client, "BTCUSDT")
    assert held["data_status"] == "INVALID_OR_STALE_COINANK_SYMBOL_SOURCE"
    assert held["coinank_open_interest"] is None
    assert held["coinank_long_turnover_usd"] is None


def test_coinank_operator_truth_rejects_stale_and_inconsistent_clocks_even_with_true_flags() -> None:
    client = FakeRedis()
    now = datetime.now(timezone.utc)
    stale = (now - timedelta(seconds=901)).isoformat().replace("+00:00", "Z")
    generated = (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    client.data["v2:coinank:global:latest"] = {
        "actual_payload_present": True,
        "is_fresh": True,
        "coverage_complete": True,
        "temporal_contract_valid": True,
        "feature_cutoff": stale,
        "available_at": stale,
        "generated_at": generated,
        "members": {"funding_rate_avg": {"value": 0.0001, "valid": True}},
    }
    assert _global_regime(client)["data_status"] == "INVALID_OR_STALE_GLOBAL_REGIME_SOURCE"

    future_cutoff = (now + timedelta(seconds=30)).isoformat().replace("+00:00", "Z")
    available = (now - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
    client.data["v2:coinank:symbol:BTCUSDT"] = {
        "actual_payload_present": True,
        "feature_eligible": True,
        "temporal_contract_valid": True,
        "feature_cutoff": future_cutoff,
        "available_at": available,
        "generated_at": generated,
        "features": {"coinank_open_interest": 12_345.0},
        "feature_units": {
            "coinank_open_interest": "provider_reported_open_interest_unit_unknown"
        },
    }
    assert _coinank_symbol_intel(client, "BTCUSDT")["data_status"] == "INVALID_OR_STALE_COINANK_SYMBOL_SOURCE"
