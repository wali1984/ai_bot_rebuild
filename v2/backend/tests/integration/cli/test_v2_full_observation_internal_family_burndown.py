"""Tests for the V2 internal feature-family burndown (round 2).

Verifies that subfamily expansions (orderbook, TA, coinank, liquidations)
add real V2-native derived dims without fabrication.
"""
from __future__ import annotations

import importlib


def _sample_feature_snapshot() -> dict:
    return {
        "schema_version": "v2_native_feature_snapshot_v1",
        "feature_snapshot_id": "v2_fsnap_cccccccccccccccccccccccccccccccc",
        "feature_freshness_state": "CURRENT",
        "features": {
            "ret_pct": 0.001,
            "log_return": 0.001,
            "body_pct": 0.4,
            "range_pct": 0.55,
            "gap_pct": 0.0,
            "true_range_pct": 0.5,
            "ema_12": 3500.0,
            "ema_26": 3490.0,
            "macd": 1.0,
            "macd_signal": 0.9,
            "macd_hist": 0.1,
            "rsi_14": 55.0,
            "bb_width_pct": 0.6,
            "htf_ret_pct": 0.01,
            "htf_rsi_14": 60.0,
            "bid_ask_spread_bps": 1.0,
            "depth_imbalance": 0.05,
            "micro_price": 3499.5,
            "toxicity_proxy": 0.05,
            "funding_rate": 0.0001,
            "oi_change_pct": 0.005,
            "last_liq_bps_24h": 10.0,
            "paper_position_present": False,
        },
    }


def _sample_market_price() -> dict:
    return {
        "ticker_24hr": {
            "lastPrice": "3500.5",
            "openPrice": "3490.0",
            "highPrice": "3510.0",
            "lowPrice": "3480.0",
            "prevClosePrice": "3490.5",
            "weightedAvgPrice": "3499.7",
            "volume": "12345.6",
            "quoteVolume": "43210987.6",
            "count": 152340,
            "priceChange": "10.0",
            "priceChangePercent": "0.286",
            "bidPrice": "3500.3",
            "askPrice": "3500.7",
            "bidQty": "12.4",
            "askQty": "8.1",
        }
    }


def _sample_funding() -> dict:
    return {
        "lastFundingRate": "0.0001",
        "markPrice": "3500.55",
        "indexPrice": "3500.40",
        "interestRate": "0.0001",
        "estimatedSettlePrice": "3500.50",
    }


def _sample_open_interest() -> dict:
    return {"openInterest": "123456.78"}


def _builder():
    return importlib.import_module(
        "v2.backend.app.services.rl_core.full_observation_builder"
    )


def test_subfamily_present_counts_increased_after_burndown_round_2() -> None:
    mod = _builder()
    result = mod.build_full_observation_for_symbol(
        symbol="ETHUSDT",
        timeframe="1m",
        feature_snapshot=_sample_feature_snapshot(),
        paper_positions=[
            {"symbol": "ETHUSDT", "side": "long",
             "expected_move_after_cost_bps": 12.0,
             "confidence_calibrated": 0.6}
        ],
        paper_ledger={"accepted_count": 1, "blocked_count": 0,
                      "held_by_paper_fill_gate_count": 0},
        risk_decisions=[{"symbol": "ETHUSDT", "pre_trade_allowed": True,
                         "fee_gate_allowed": True, "churn_blocked": False}],
        orchestrator_decisions={"considered_count": 1,
                                "bucket_winners": [{}],
                                "stale_proposal_ids": []},
        trainer_heartbeat={"predictions_count": 3,
                           "predictions_with_open_gate": ["BTCUSDT", "ETHUSDT"],
                           "predictions_blocked": []},
        prediction={"paper_fill_allowed": True,
                    "selected_action": "long",
                    "expected_move_bps": 15.0,
                    "expected_move_after_cost_bps": 12.0,
                    "confidence_raw": 0.55,
                    "confidence_calibrated": 0.61,
                    "paper_fill_gate_block_reasons": []},
        market_price=_sample_market_price(),
        market_funding=_sample_funding(),
        market_open_interest=_sample_open_interest(),
    )
    # Each touched sub-family must have grown its present count past the
    # round-1 lower bound established earlier.
    assert result.subfamily_present_counts.get("binance_orderbook", 0) >= 13
    assert result.subfamily_present_counts.get("technical_analysis", 0) >= 22
    assert result.subfamily_present_counts.get("coinank", 0) >= 14
    assert result.subfamily_present_counts.get("liquidations", 0) >= 4
    # Aggregate generated dim must clear the round-1 burndown bound.
    assert result.generated_full_observation_dim >= 140


def test_orderbook_source_available_flag_is_zero_when_no_depth_ladder() -> None:
    mod = _builder()
    result = mod.build_full_observation_for_symbol(
        symbol="ETHUSDT",
        timeframe="1m",
        feature_snapshot=_sample_feature_snapshot(),
        paper_positions=[],
        paper_ledger={},
        risk_decisions=[],
        orchestrator_decisions={},
        trainer_heartbeat={},
        prediction={},
        market_price=_sample_market_price(),
        market_funding=_sample_funding(),
        market_open_interest=_sample_open_interest(),
    )
    # Find the orderbook depth source-flag slot; its value must be 0.0
    # (probe flag, not fabricated).
    sources_by_name = {
        result.field_names[i]: (result.field_values[i], result.field_sources[i])
        for i in range(len(result.field_names))
    }
    flag = sources_by_name.get("binance_orderbook.v2_depth_source_available")
    assert flag is not None
    val, src = flag
    assert val == 0.0
    assert src == "V2_PROBE_FLAG_NO_DEPTH_LADDER_PRESENT"


def test_coinank_aggregator_source_available_flag_is_zero() -> None:
    mod = _builder()
    result = mod.build_full_observation_for_symbol(
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot=_sample_feature_snapshot(),
        paper_positions=[],
        paper_ledger={},
        risk_decisions=[],
        orchestrator_decisions={},
        trainer_heartbeat={},
        prediction={},
        market_price=_sample_market_price(),
        market_funding=_sample_funding(),
        market_open_interest=_sample_open_interest(),
    )
    sources_by_name = {
        result.field_names[i]: (result.field_values[i], result.field_sources[i])
        for i in range(len(result.field_names))
    }
    flag = sources_by_name.get("coinank.v2_coinank_aggregator_source_available")
    assert flag is not None
    val, src = flag
    assert val == 0.0
    assert src == "V2_PROBE_FLAG_NO_COINANK_AGGREGATOR_PRESENT"


def test_liquidation_source_available_flag_is_zero() -> None:
    mod = _builder()
    result = mod.build_full_observation_for_symbol(
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot=_sample_feature_snapshot(),
        paper_positions=[],
        paper_ledger={},
        risk_decisions=[],
        orchestrator_decisions={},
        trainer_heartbeat={},
        prediction={},
        market_price=_sample_market_price(),
        market_funding=_sample_funding(),
        market_open_interest=_sample_open_interest(),
    )
    sources_by_name = {
        result.field_names[i]: (result.field_values[i], result.field_sources[i])
        for i in range(len(result.field_names))
    }
    flag = sources_by_name.get("liquidations.v2_liquidation_source_available")
    assert flag is not None
    val, src = flag
    assert val == 0.0
    # Aggregator service now reports a per-symbol-scoped flag.
    assert src in {
        "V2_PROBE_FLAG_NO_LIQUIDATION_AGGREGATOR_PRESENT",
        "V2_PROBE_FLAG_NO_PER_SYMBOL_LIQUIDATION_AGGREGATOR_PRESENT",
    }


def test_no_zero_fill_after_burndown_round_2() -> None:
    mod = _builder()
    result = mod.build_full_observation_for_symbol(
        symbol="ETHUSDT",
        timeframe="1m",
        feature_snapshot=_sample_feature_snapshot(),
        paper_positions=[],
        paper_ledger={},
        risk_decisions=[],
        orchestrator_decisions={},
        trainer_heartbeat={},
        prediction={},
        market_price=_sample_market_price(),
        market_funding=_sample_funding(),
        market_open_interest=_sample_open_interest(),
    )
    assert result.zero_filled_field_count == 0
    none_count = sum(1 for v in result.field_values if v is None)
    assert none_count == result.missing_dim_count
    assert result.state == "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS"
