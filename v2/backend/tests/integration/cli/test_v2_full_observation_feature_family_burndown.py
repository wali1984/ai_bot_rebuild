"""Tests for the V2 full-observation feature-family burndown.

Paper-only. No torch import. No legacy mutation. No silent zero-fill.
"""
from __future__ import annotations

import importlib


def _sample_feature_snapshot() -> dict:
    return {
        "schema_version": "v2_native_feature_snapshot_v1",
        "feature_snapshot_id": "v2_fsnap_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
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


def test_subfamily_layout_sums_to_137_plus_padding() -> None:
    mod = _builder()
    total = sum(sz for _, sz in mod.SUBFAMILY_LAYOUT)
    assert total == 137, f"sub-family chunks must sum to 137, got {total}"


def test_burndown_increases_unified_features_dim_meaningfully() -> None:
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
                           "predictions_with_open_gate": ["BTCUSDT", "ETHUSDT"]},
        prediction={"paper_fill_allowed": True,
                    "selected_action": "long",
                    "expected_move_bps": 15.0,
                    "confidence_calibrated": 0.61,
                    "paper_fill_gate_block_reasons": []},
        market_price=_sample_market_price(),
        market_funding=_sample_funding(),
        market_open_interest=_sample_open_interest(),
    )
    # The new builder produces materially more present dims than the
    # 23-feature-only baseline (44).
    assert result.generated_full_observation_dim >= 100
    # No silent zero-fill.
    assert result.zero_filled_field_count == 0
    # Sub-family present counts must be populated for buildable families.
    for family in (
        "binance_klines",
        "binance_orderbook",
        "liquidations",
        "technical_analysis",
        "coinank",
        "portfolio_state_unified",
    ):
        assert result.subfamily_present_counts.get(family, 0) > 0, family
    # External-source / operator-decision families must NOT count as
    # present.
    for family in ("ccxt_ohlcv", "token_metrics"):
        assert result.subfamily_present_counts.get(family, 0) == 0, family


def test_subfamily_count_totals_aggregate_in_status_payload() -> None:
    mod = _builder()
    payload = mod.build_full_observation_status()
    assert "subfamily_present_counts_total" in payload
    assert "subfamily_target_counts_total" in payload
    # Targets are stable.
    assert payload["subfamily_target_counts_total"]["binance_klines"] == 20
    assert payload["subfamily_target_counts_total"]["technical_analysis"] == 25
    # Token metrics + onchain remain at zero present total because they
    # are external-source-required.
    assert payload["subfamily_present_counts_total"]["token_metrics"] == 0
    assert payload["subfamily_present_counts_total"]["ccxt_ohlcv"] == 0
    # Buildable families have at least one present dim across all symbols.
    for family in (
        "binance_klines",
        "binance_orderbook",
        "liquidations",
        "technical_analysis",
        "coinank",
        "portfolio_state_unified",
    ):
        assert payload["subfamily_present_counts_total"][family] > 0, family


def test_state_partial_until_full_1911_filled() -> None:
    mod = _builder()
    payload = mod.build_full_observation_status()
    assert payload["state"] == "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS"
    assert payload["checkpoint_compatibility_claimed"] is False
    assert payload["policy_architecture_parity_claimed"] is False
    assert payload["no_zero_fill_for_unknown_fields"] is True
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["approves_legacy_shutdown"] is False


def test_external_and_operator_lists_remain_explicit() -> None:
    mod = _builder()
    payload = mod.build_full_observation_status()
    assert "unified_feature_family.token_metrics" in payload[
        "external_source_required_families"
    ]
    assert "onchain_btc" in payload["external_source_required_families"]
    assert "onchain_eth" in payload["external_source_required_families"]
    assert "unified_feature_family.ccxt_ohlcv" in payload[
        "operator_decision_required_families"
    ]
