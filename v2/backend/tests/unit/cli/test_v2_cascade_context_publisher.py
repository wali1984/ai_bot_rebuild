"""Cascade-context publisher: squeeze-detector input derivation (raw book/tape/premium)."""
from __future__ import annotations

import pytest


class FakeRedis:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        import json

        self.values = {
            key: json.dumps(value) for key, value in (values or {}).items()
        }
        self.get_calls: list[str] = []

    def get(self, key: str):
        self.get_calls.append(key)
        return self.values.get(key)


def test_derive_orderbook_squeeze_inputs_from_raw_depth() -> None:
    """Regression: the raw Binance book has no derived metrics, so the squeeze
    detector ran for hours as a one-input (sweep-only) detector with direction
    permanently 'unclear' (trap == probability, block/ride never fired)."""
    from app.cli.v2_cascade_context_publisher import derive_orderbook_squeeze_inputs

    book = {
        "bids": [["100.0", "9.0"], ["99.9", "6.0"]],
        "asks": [["100.1", "3.0"], ["100.2", "2.0"]],
    }
    out = derive_orderbook_squeeze_inputs(book)
    assert out is not None
    assert out["depth_imbalance"] == pytest.approx((15.0 - 5.0) / 20.0)
    assert out["spread_bps"] == pytest.approx(0.1 / 100.05 * 10000.0)
    assert derive_orderbook_squeeze_inputs({"bids": [], "asks": []}) is None
    assert derive_orderbook_squeeze_inputs(None) is None
    # crossed/garbage books refuse rather than emit a fake signal
    assert derive_orderbook_squeeze_inputs({"bids": [["101", "1"]], "asks": [["100", "1"]]}) is None


def test_derive_tape_imbalance_notional_weighted_aggressor() -> None:
    from app.cli.v2_cascade_context_publisher import derive_tape_imbalance

    # m=False -> aggressive BUY, m=True -> aggressive SELL (Binance semantics)
    payload = {
        "trades": [
            {"p": "100", "q": "3", "m": False},
            {"p": "100", "q": "1", "m": True},
        ]
    }
    out = derive_tape_imbalance(payload)
    assert out is not None
    assert out["tape_imbalance"] == pytest.approx((300.0 - 100.0) / 400.0)
    assert derive_tape_imbalance({"trades": []}) is None
    assert derive_tape_imbalance(None) is None


def test_derive_mark_index_divergence_bps() -> None:
    from app.cli.v2_cascade_context_publisher import derive_mark_index_divergence

    out = derive_mark_index_divergence({"markPrice": "100.10", "indexPrice": "100.00"})
    assert out is not None
    assert out["mark_index_divergence_bps"] == pytest.approx(10.0, abs=1e-6)
    assert derive_mark_index_divergence({"markPrice": "x"}) is None
    assert derive_mark_index_divergence(None) is None


def test_live_source_shapes_receive_only_literal_producer_lineage() -> None:
    from app.cli.v2_cascade_context_publisher import _normalize_source_lineage

    open_interest = _normalize_source_lineage(
        "open_interest",
        {
            "open_interest": 123.0,
            "binance_time_ms": 1_800_000_000_000,
            "fetched_utc": "2027-01-15T08:00:01Z",
        },
    )
    assert open_interest is not None
    assert open_interest["event_time"] == 1_800_000_000_000
    assert open_interest["feature_cutoff"] == 1_800_000_000_000
    assert open_interest["ingested_at"] == "2027-01-15T08:00:01Z"
    assert open_interest["available_at"] == "2027-01-15T08:00:01Z"

    orderbook = _normalize_source_lineage(
        "orderbook",
        {
            "depth_imbalance": 0.2,
            "event_time": "2027-01-15T08:00:02.000Z",
            "received_at": "2027-01-15T08:00:02.050Z",
            "available_at": "2027-01-15T08:00:02.060Z",
        },
    )
    assert orderbook is not None
    assert orderbook["feature_cutoff"] == "2027-01-15T08:00:02.000Z"
    assert orderbook["ingested_at"] == "2027-01-15T08:00:02.050Z"

    tape = _normalize_source_lineage(
        "trade_tape",
        {
            "generated_utc": "2027-01-15T08:00:03.500Z",
            "trades": [
                {"T": 1_800_000_002_000},
                {"T": 1_800_000_003_000},
            ],
        },
    )
    assert tape is not None
    assert tape["event_time"] == 1_800_000_003_000
    assert tape["feature_cutoff"] == 1_800_000_003_000
    assert "ingested_at" not in tape
    assert "available_at" not in tape
    assert tape["generated_utc"] == "2027-01-15T08:00:03.500Z"

    tape_with_literal_receipt = _normalize_source_lineage(
        "trade_tape",
        {
            "received_at": "2027-01-15T08:00:03.400Z",
            "available_at": "2027-01-15T08:00:03.500Z",
            "trades": [{"T": 1_800_000_003_000}],
        },
    )
    assert tape_with_literal_receipt is not None
    assert tape_with_literal_receipt["ingested_at"] == (
        "2027-01-15T08:00:03.400Z"
    )
    assert tape_with_literal_receipt["available_at"] == (
        "2027-01-15T08:00:03.500Z"
    )


def test_unknown_liquidation_shape_is_not_stamped_with_publisher_now() -> None:
    from app.cli.v2_cascade_context_publisher import _normalize_source_lineage

    payload = {
        "notional": 100.0,
        "event_time_ms": 1_800_000_000_000,
        "generated_utc": "2027-01-15T08:00:01Z",
    }
    normalized = _normalize_source_lineage("liquidation_event", payload)

    assert normalized == payload
    assert "feature_cutoff" not in normalized
    assert "ingested_at" not in normalized
    assert "available_at" not in normalized


def test_observed_aggregate_is_preferred_but_not_statically_normalized() -> None:
    from app.cli.v2_cascade_context_publisher import _source_payloads
    from app.services.microstructure_trust.cascade_context import (
        build_cascade_context,
    )

    event_ms = 1_800_000_000_000
    observed = {
        "semantic_kind": "observed_binance_force_order_snapshots",
        "source_capture_semantics": (
            "latest_force_order_snapshot_per_symbol_per_1000ms"
        ),
        "source_capture_complete": False,
        "one_hour_retention_complete": True,
        "retention_window_complete": False,
        "retention_truncated": False,
        "window_1h_ms": 60 * 60 * 1000,
        "observed_notional_1h": 2_500_000.0,
        "observed_count_1h": 12,
        "event_time": event_ms,
        "feature_cutoff": event_ms,
        "ingested_at": event_ms + 100,
        "available_at": event_ms + 100,
        "generated_at": event_ms + 100,
    }
    redis = FakeRedis(
        {
            "v2:market:liquidations:observed_aggregate:BTCUSDT": observed,
            "v2:market:liquidations:latest:BTCUSDT": {
                "notional": 1.0,
            },
            "v2:market:liquidations:aggregate:BTCUSDT": {
                "notional_24h": 999_999_999.0,
            },
        }
    )

    sources = _source_payloads(redis, "BTCUSDT", "1m")
    liquidation = sources["liquidation_event"]
    assert liquidation is not None
    assert "notional_1h" not in liquidation
    assert "count_1h" not in liquidation
    assert "cascade_risk" not in liquidation
    assert liquidation["cascade_risk_semantics"] == (
        "OBSERVED_1H_LOWER_BOUND_REQUIRES_AUTHENTICATED_ADAPTIVE_NORMALIZATION"
    )
    assert liquidation["observed_lower_bound_only"] is True
    assert liquidation["cascade_observed_window_eligible"] is False
    assert liquidation["adaptive_normalization_available"] is False
    assert liquidation["source_redis_key"] == (
        "v2:market:liquidations:observed_aggregate:BTCUSDT"
    )
    assert "v2:market:liquidations:aggregate:BTCUSDT" not in redis.get_calls

    context = build_cascade_context(
        symbol="BTCUSDT",
        timeframe="1m",
        sources=sources,
        decision_time=event_ms + 1_000,
    )
    assert context["cascade_event_component"] is None


def test_incomplete_one_hour_retention_does_not_create_numeric_aliases() -> None:
    from app.cli.v2_cascade_context_publisher import _normalize_source_lineage

    normalized = _normalize_source_lineage(
        "liquidation_event",
        {
            "semantic_kind": "observed_binance_force_order_snapshots",
            "source_capture_complete": False,
            "one_hour_retention_complete": False,
            "retention_truncated": False,
            "window_1h_ms": 60 * 60 * 1000,
            "observed_notional_1h": 5_000_000.0,
            "observed_count_1h": 20,
        },
    )

    assert normalized is not None
    assert "cascade_risk" not in normalized
    assert normalized.get("cascade_observed_window_eligible") is not True


def test_cross_asset_fallback_uses_only_finalized_candle_clocks() -> None:
    from app.cli.v2_cascade_context_publisher import _cross_asset_source

    def candle(
        close: float,
        cutoff: int,
        *,
        closed: bool = True,
    ) -> dict:
        return {
            "close": close,
            "candle_close_time": cutoff,
            "candle_closed_confirmed": closed,
            "ingested_at": cutoff + 50,
            "available_at": cutoff + 60,
        }

    redis = FakeRedis(
        {
            "v2:market:ohlcv:binance:BTCUSDT:5m": [
                candle(100.0, 1_800_000_000_000),
                candle(101.0, 1_800_000_300_000),
                candle(999.0, 1_800_000_600_000, closed=False),
            ],
            "v2:market:ohlcv:binance:ETHUSDT:5m": [
                candle(200.0, 1_800_000_000_000),
                candle(198.0, 1_800_000_300_000),
            ],
        }
    )

    source = _cross_asset_source(redis)

    assert source["BTCUSDT_change_pct"] == pytest.approx(1.0)
    assert source["ETHUSDT_change_pct"] == pytest.approx(-1.0)
    assert source["feature_cutoff"] == 1_800_000_300_000
    assert source["event_time"] == 1_800_000_300_000
    assert source["ingested_at"] == 1_800_000_300_050
    assert source["available_at"] == 1_800_000_300_060
    assert source["covered_majors"] == ["BTCUSDT", "ETHUSDT"]
    assert source["major_coverage_complete"] is False
    assert "generated_at" not in source
    assert "generated_utc" not in source
