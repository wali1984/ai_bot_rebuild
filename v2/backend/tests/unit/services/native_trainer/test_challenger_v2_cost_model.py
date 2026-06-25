from __future__ import annotations

import pytest

from v2.backend.app.services.native_trainer.challenger_v2_cost_model import (
    PRODUCTION_STANDARD_ROUND_TRIP_COST_BPS,
    estimate_paper_cost,
    estimate_replay_cost,
)


def _cost_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "observed_bid_ask_spread_bps": 2.5,
        "order_notional_usd": 1_000.0,
        "orderbook_depth_usd": 100_000.0,
        "maker_probability": 0.25,
        "taker_probability": 0.75,
        "maker_fee_bps": 1.0,
        "taker_fee_bps": 5.0,
        "funding_rate": 0.0008,
        "latency_ms": 250.0,
        "volatility_bps": 80.0,
        "partial_fill_probability": 0.9,
        "mark_price": 100.2,
        "index_price": 100.0,
        "liquidity_score": 0.8,
    }
    row.update(overrides)
    return row


def test_replay_cost_equals_paper_cost_for_same_snapshot_and_order() -> None:
    row = _cost_row()

    replay = estimate_replay_cost(row, side="long", order_notional_usd=1_000.0, holding_period_seconds=3600)
    paper = estimate_paper_cost(row, side="long", order_notional_usd=1_000.0, holding_period_seconds=3600)

    assert replay.to_jsonable() == paper.to_jsonable()
    assert replay.total_cost_bps >= PRODUCTION_STANDARD_ROUND_TRIP_COST_BPS


def test_observed_spread_not_replaced_by_constant() -> None:
    cost = estimate_replay_cost(_cost_row(observed_bid_ask_spread_bps=3.25), order_notional_usd=1_000.0)

    assert cost.observed_bid_ask_spread_bps == pytest.approx(3.25)
    assert cost.component_sources["observed_bid_ask_spread_bps"] == "OBSERVED_OR_DERIVED_BID_ASK_SPREAD_BPS"
    assert cost.total_cost_bps >= PRODUCTION_STANDARD_ROUND_TRIP_COST_BPS


def test_depth_impact_scales_with_notional() -> None:
    low = estimate_replay_cost(_cost_row(), order_notional_usd=1_000.0)
    high = estimate_replay_cost(_cost_row(), order_notional_usd=10_000.0)

    assert high.depth_impact_bps > low.depth_impact_bps
    assert high.component_sources["depth_impact_bps"] == "MODELED_FROM_ORDERBOOK_DEPTH_AND_NOTIONAL"


def test_funding_applied_for_holding_period() -> None:
    one_hour = estimate_replay_cost(_cost_row(), holding_period_seconds=3600)
    four_hours = estimate_replay_cost(_cost_row(), holding_period_seconds=14_400)

    assert four_hours.funding_bps > one_hour.funding_bps
    assert one_hour.component_sources["funding_bps"] == "FUNDING_RATE_SCALED_TO_HOLDING_PERIOD"


def test_fallback_cost_not_counted_as_production_evidence() -> None:
    cost = estimate_replay_cost({"symbol": "BTCUSDT"}, order_notional_usd=None)

    assert cost.fallback is True
    assert cost.production_grade_evidence is False
    assert "observed_bid_ask_spread_bps" in cost.fallback_components
    assert "funding_bps" in cost.fallback_components
