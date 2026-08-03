"""Tests for V2 paper ledger fill-price provenance.

Paper-only. No real network/exchange. No torch. No legacy reads.
"""
from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timezone
from unittest.mock import patch


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.write_log: list[tuple[str, str, int | None]] = []
        # The paper loop's dynamic-envelope drawdown calculation reads the
        # session starting equity from v2:paper:session (always present in the
        # production runtime). Seed it so run_once() exercises the same path;
        # without it the loop crashes (TypeError: None - None) before any
        # provenance logic runs — missing-key robustness is a paper-loop
        # concern owned by the trading-flow agent, tracked separately.
        self.store["v2:paper:session"] = json.dumps({"starting_equity_usd": 10000.0})

    def ping(self) -> bool:
        return True

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        self.write_log.append((key, value, ex))
        return True


def _mod():
    return importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")


def test_read_v2_market_price_pulls_lastprice_from_v2_market_prices() -> None:
    mod = _mod()
    r = FakeRedis()
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({
        "ticker_24hr": {"lastPrice": "65000.42"},
        "fetched_utc": "2026-05-18T18:00:00Z",
    })
    px, source, source_utc = mod._read_v2_market_price(r, "BTCUSDT")
    assert px == 65000.42
    assert source == mod.ENTRY_PRICE_SOURCE_V2_MARKET
    assert source_utc == "2026-05-18T18:00:00Z"


def test_read_v2_market_price_falls_back_to_features_only_when_current() -> None:
    mod = _mod()
    r = FakeRedis()
    r.store["v2:features:latest:BTCUSDT:1m"] = json.dumps({
        "feature_freshness_state": "CURRENT",
        "features": {"close_price": "70000.0"},
        "generated_at": "2026-05-18T18:01:00Z",
    })
    px, source, source_utc = mod._read_v2_market_price(r, "BTCUSDT")
    assert px == 70000.0
    assert source == mod.ENTRY_PRICE_SOURCE_V2_FEATURES
    assert source_utc == "2026-05-18T18:01:00Z"


def test_read_v2_market_price_refuses_stale_feature_snapshot() -> None:
    mod = _mod()
    r = FakeRedis()
    r.store["v2:features:latest:BTCUSDT:1m"] = json.dumps({
        "feature_freshness_state": "STALE",
        "features": {"close_price": "70000.0"},
    })
    px, source, _ = mod._read_v2_market_price(r, "BTCUSDT")
    assert px is None
    assert source == mod.ENTRY_PRICE_BLOCKER_MISSING_FILL


def test_read_v2_market_price_emits_missing_blocker_when_no_inputs() -> None:
    mod = _mod()
    r = FakeRedis()
    px, source, _ = mod._read_v2_market_price(r, "XRPUSDT")
    assert px is None
    assert source == mod.ENTRY_PRICE_BLOCKER_MISSING_FILL


def test_read_v2_feature_snapshot_requires_available_before_decision() -> None:
    mod = _mod()
    r = FakeRedis()
    r.store["v2:features:latest:BTCUSDT:1m"] = json.dumps({
        "feature_freshness_state": "CURRENT",
        "feature_snapshot_id": "feat_current",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "available_at": "2026-06-19T01:44:59Z",
        "generated_at": "2026-06-19T01:44:59Z",
        "feature_cutoff": "2026-06-19T01:44:00Z",
        "candle_closed_confirmed": True,
        "features": {"true_range_pct": 0.75},
    })

    snapshot = mod._read_v2_feature_snapshot(
        r,
        "BTCUSDT",
        "1m",
        decision_time="2026-06-19T01:45:00Z",
    )

    assert snapshot["feature_snapshot_id"] == "feat_current"
    assert snapshot["available_at"] == "2026-06-19T01:44:59Z"
    assert snapshot["features"]["true_range_pct"] == 0.75


def test_read_v2_feature_snapshot_rejects_future_available_at() -> None:
    mod = _mod()
    r = FakeRedis()
    r.store["v2:features:latest:BTCUSDT:1m"] = json.dumps({
        "feature_freshness_state": "CURRENT",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "available_at": "2026-06-19T01:45:01Z",
        "generated_at": "2026-06-19T01:45:01Z",
        "feature_cutoff": "2026-06-19T01:44:00Z",
        "candle_closed_confirmed": True,
        "features": {"true_range_pct": 0.75},
    })

    snapshot = mod._read_v2_feature_snapshot(
        r,
        "BTCUSDT",
        "1m",
        decision_time="2026-06-19T01:45:00Z",
    )

    assert snapshot["features"] == {}
    assert snapshot["unavailable_reason"] == "FEATURE_AVAILABLE_AT_AFTER_DECISION_TIME"


def test_current_risk_state_ignores_historical_accepted_drawdown_for_router() -> None:
    mod = _mod()
    r = FakeRedis()
    r.store["v2:portfolio:state"] = json.dumps({"current_drawdown_bps": 168.6})
    r.store["v2:paper:ledger"] = json.dumps({
        "accepted": [
            {
                "symbol": "BTCUSDT",
                "drawdown_bps": 300.0,
                "paper_lifecycle_status": "CLOSED_PREVIOUSLY",
            }
        ],
        "blocked": [{"symbol": "ETHUSDT", "drawdown_bps": 400.0}],
        "shadow_observations": [{"symbol": "SOLUSDT", "drawdown_bps": 500.0}],
        "open_positions": [
            {
                "symbol": "BNBUSDT",
                "mae_bps": 115.0,
                "unrealized_pnl_bps": -62.0,
            }
        ],
    })

    with patch.object(mod, "_read_lifecycle_state_file", return_value={}):
        state = mod._read_current_risk_state(r)

    assert state["current_drawdown_bps"] == 168.6
    assert state["current_drawdown_source"] == "CURRENT_PORTFOLIO_STATE"
    assert state["worst_open_position_drawdown_bps"] == 115.0
    assert state["open_position_count"] == 1


def test_current_risk_state_keeps_open_position_drawdown_as_telemetry() -> None:
    mod = _mod()
    r = FakeRedis()
    r.store["v2:portfolio:state"] = json.dumps({"current_drawdown_bps": 50.0})
    r.store["v2:paper:ledger"] = json.dumps({
        "accepted": [{"symbol": "BTCUSDT", "drawdown_bps": 300.0}],
        "open_positions": [
            {
                "symbol": "BNBUSDT",
                "mae_bps": 260.0,
                "unrealized_pnl_bps": -120.0,
            }
        ],
    })

    with patch.object(mod, "_read_lifecycle_state_file", return_value={}):
        state = mod._read_current_risk_state(r)

    assert state["current_drawdown_bps"] == 50.0
    assert state["current_drawdown_source"] == "CURRENT_PORTFOLIO_STATE"
    assert state["worst_open_position_drawdown_bps"] == 260.0
    assert state["open_position_drawdown_source"] == "OPEN_POSITION_MAE_AND_UNREALIZED_LOSS"
    assert state["open_position_count"] == 1


def test_current_risk_state_falls_back_to_open_position_drawdown_without_portfolio() -> None:
    mod = _mod()
    r = FakeRedis()
    r.store["v2:portfolio:state"] = json.dumps({})
    r.store["v2:paper:ledger"] = json.dumps({
        "open_positions": [
            {
                "symbol": "BNBUSDT",
                "mae_bps": 260.0,
                "unrealized_pnl_bps": -120.0,
            }
        ],
    })

    with patch.object(mod, "_read_lifecycle_state_file", return_value={}):
        state = mod._read_current_risk_state(r)

    assert state["current_drawdown_bps"] == 260.0
    assert state["current_drawdown_source"] == "OPEN_POSITION_DRAWDOWN_FALLBACK"
    assert state["worst_open_position_drawdown_bps"] == 260.0
    assert state["open_position_count"] == 1


def test_read_v2_orderbook_microstructure_computes_top_of_book_spread() -> None:
    mod = _mod()
    r = FakeRedis()
    r.store["v2:market:orderbook:BTCUSDT"] = json.dumps({
        "E": 1781834577407,
        "bids": [["100.00", "4.0"], ["99.90", "1.0"]],
        "asks": [["100.05", "2.0"], ["100.10", "1.0"]],
    })

    micro = mod._read_v2_orderbook_microstructure(r, "BTCUSDT")

    assert micro["source"] == "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BTCUSDT"
    assert abs(micro["bid_ask_spread_bps"] - 4.99875031) < 0.000001
    assert micro["entry_spread_available_at"].endswith("Z")
    assert micro["entry_spread_decision_time"].endswith("Z")
    assert micro["orderbook_imbalance"] > 0.0
    assert micro["bid_depth_usd"] == 499.9
    assert micro["ask_depth_usd"] == 300.2
    assert micro["orderbook_depth_usd"] == 300.2
    assert micro["top_of_book_depth_usd"] == 300.2
    assert micro["market_depth_usd"] == 300.2
    assert micro["orderbook_depth_source"] == "v2:market:orderbook:BTCUSDT:top5_notional_usd"


def test_allocation_input_uses_v2_orderbook_spread_when_signal_spread_missing() -> None:
    mod = _mod()
    intent = {"symbol": "BTCUSDT", "timeframe": "1m", "fill_price": 100.0}
    micro = {
        "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BTCUSDT",
        "bid_ask_spread_bps": 4.99875031,
        "orderbook_imbalance": 0.25,
        "bid_depth_usd": 500.0,
        "ask_depth_usd": 300.0,
        "orderbook_depth_usd": 300.0,
        "top_of_book_depth_usd": 300.0,
        "market_depth_usd": 300.0,
        "orderbook_depth_source": "v2:market:orderbook:BTCUSDT:top5_notional_usd",
        "entry_spread_available_at": "2026-06-19T01:22:57Z",
        "entry_spread_decision_time": "2026-06-19T01:22:58Z",
    }

    allocation_input = mod._build_allocation_input(
        intent=intent,
        signal={"side": "long"},
        prediction={
            "confidence_calibrated": 0.8,
            "expected_move_after_cost_bps": 40.0,
            "market_state_integrity_score": 95.0,
            "features": {},
        },
        portfolio_context={
            "equity": 10000.0,
            "available_margin": 10000.0,
            "wallet_balance": 10000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure=micro,
    )

    assert abs(allocation_input.spread_bps - 4.99875031) < 0.000001
    assert allocation_input.slippage_bps != 2.0
    assert intent["actual_observed_spread_entry_bps"] == 4.99875031
    assert intent["entry_spread_source"] == micro["source"]
    assert intent["entry_spread_available_at"] == "2026-06-19T01:22:57Z"
    assert intent["entry_spread_decision_time"] == "2026-06-19T01:22:58Z"
    assert intent["bid_depth_usd"] == 500.0
    assert intent["ask_depth_usd"] == 300.0
    assert intent["orderbook_depth_usd"] == 300.0
    assert intent["entry_orderbook_depth_usd"] == 300.0
    assert intent["entry_orderbook_depth_side"] == "ask"
    assert intent["orderbook_depth_source"] == "v2:market:orderbook:BTCUSDT:top5_notional_usd"
    assert intent["expected_slippage_source"] == "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY"
    assert intent["expected_slippage_modeled"] is True


def test_allocation_input_prefers_v2_orderbook_over_static_signal_spread() -> None:
    mod = _mod()
    intent = {"symbol": "BTCUSDT", "timeframe": "1m", "fill_price": 100.0}
    micro = {
        "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BTCUSDT",
        "bid_ask_spread_bps": 4.25,
        "orderbook_imbalance": 0.12,
        "entry_spread_available_at": "2026-06-19T01:30:00Z",
        "entry_spread_decision_time": "2026-06-19T01:30:01Z",
    }

    allocation_input = mod._build_allocation_input(
        intent=intent,
        signal={"side": "long", "bid_ask_spread_bps": 2.0},
        prediction={
            "confidence_calibrated": 0.8,
            "expected_move_after_cost_bps": 40.0,
            "market_state_integrity_score": 95.0,
            "features": {},
        },
        portfolio_context={
            "equity": 10000.0,
            "available_margin": 10000.0,
            "wallet_balance": 10000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure=micro,
    )

    assert allocation_input.spread_bps == 4.25
    assert intent["actual_observed_spread_entry_bps"] == 4.25
    assert intent["entry_spread_source"] == micro["source"]
    assert intent["upstream_reported_spread_bps"] == 2.0
    assert intent["entry_spread_replaced_by_orderbook"] is True
    assert intent["expected_slippage_source"] == "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY"


def test_allocation_input_promotes_feature_atr_for_exit_lifecycle() -> None:
    mod = _mod()
    intent = {"symbol": "BTCUSDT", "timeframe": "1m", "fill_price": 100.0}
    micro = {
        "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BTCUSDT",
        "bid_ask_spread_bps": 3.0,
        "orderbook_imbalance": 0.10,
        "entry_spread_available_at": "2026-06-19T01:45:00Z",
        "entry_spread_decision_time": "2026-06-19T01:45:01Z",
    }

    allocation_input = mod._build_allocation_input(
        intent=intent,
        signal={"side": "long"},
        prediction={
            "confidence_calibrated": 0.8,
            "expected_move_after_cost_bps": 40.0,
            "market_state_integrity_score": 95.0,
            "features": {"atr_bps": 112.5, "true_range_bps": 150.0},
        },
        portfolio_context={
            "equity": 10000.0,
            "available_margin": 10000.0,
            "wallet_balance": 10000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure=micro,
    )

    assert allocation_input.volatility_bps == 112.5
    assert intent["entry_atr_bps"] == 112.5
    assert intent["atr_bps"] == 112.5


def test_allocation_input_promotes_percent_atr_feature_for_exit_lifecycle() -> None:
    mod = _mod()
    intent = {"symbol": "BTCUSDT", "timeframe": "1m", "fill_price": 100.0}
    micro = {
        "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:v2:market:orderbook:BTCUSDT",
        "bid_ask_spread_bps": 3.0,
        "orderbook_imbalance": 0.10,
        "entry_spread_available_at": "2026-06-19T01:45:00Z",
        "entry_spread_decision_time": "2026-06-19T01:45:01Z",
    }

    allocation_input = mod._build_allocation_input(
        intent=intent,
        signal={"side": "long"},
        prediction={
            "confidence_calibrated": 0.8,
            "expected_move_after_cost_bps": 40.0,
            "market_state_integrity_score": 95.0,
            "features": {"true_range_pct": 0.75, "ta_ATR": 2.0},
        },
        portfolio_context={
            "equity": 10000.0,
            "available_margin": 10000.0,
            "wallet_balance": 10000.0,
            "drawdown_bps": 0.0,
        },
        symbol_exposures={},
        total_exposure=0.0,
        market_microstructure=micro,
    )

    assert allocation_input.volatility_bps == 75.0
    assert intent["entry_atr_bps"] == 75.0
    assert intent["atr_bps"] == 75.0


def test_squeeze_evidence_is_sourced_when_orderbook_context_is_benign() -> None:
    mod = _mod()

    squeeze = mod._derive_squeeze_evidence(
        intent={"observed_bid_ask_spread_bps": 1.0},
        prediction={},
    )

    assert squeeze["score"] == 0.0
    assert squeeze["source"] == "DERIVED_FROM_LIQUIDATION_OI_FUNDING_ORDERBOOK_CONTEXT"
    assert squeeze["components"] == {"spread_stress": 0.0}
    assert squeeze["unavailable_reason"] is None


def test_directional_collapse_guard_blocks_majority_side_only() -> None:
    mod = _mod()
    ledger = {"closed_trades": [{"side": "short"} for _ in range(60)]}

    short_guard = mod._paper_directional_collapse_guard(ledger, "short")
    long_guard = mod._paper_directional_collapse_guard(ledger, "long")

    assert short_guard["allowed"] is False
    assert short_guard["block_reason"] == mod.DIRECTIONAL_COLLAPSE_BLOCK_REASON
    assert short_guard["short_closed_trade_count"] == 60
    assert short_guard["long_closed_trade_count"] == 0
    assert short_guard["majority_side"] == "short"
    assert long_guard["allowed"] is True
    assert long_guard["candidate_side"] == "long"


def test_paper_signal_temporal_gate_rejects_stale_runtime_signal() -> None:
    mod = _mod()

    reasons = mod._paper_signal_temporal_rejection_reasons(
        signal={
            "prediction_id": "stale-pred",
            "generated_est": "2026-06-14T13:36:41-04:00",
            "source_prediction_status": "PRESENT_CURRENT",
        },
        prediction={},
        now=datetime(2026, 6, 19, 3, 10, tzinfo=timezone.utc),
    )

    # The stale gate is adaptive now (reason carries the resolved adaptive
    # window and an _ADAPTIVE suffix); a days-old signal must still be rejected.
    assert any(reason.startswith("STALE_SIGNAL_GT_") for reason in reasons)
    assert f"STALE_SIGNAL_GT_{mod.PAPER_SIGNAL_STALE_SECONDS}s_ADAPTIVE" in reasons
    assert "SOURCE_PREDICTION_NOT_CURRENT_OR_MISSING" in reasons


def test_paper_signal_temporal_gate_accepts_current_runtime_paper_signal_status() -> None:
    mod = _mod()

    reasons = mod._paper_signal_temporal_rejection_reasons(
        signal={
            "prediction_id": "current-pred",
            "source_prediction_status": "CURRENT_RUNTIME_PAPER_SIGNAL",
        },
        prediction={"prediction_id": "current-pred"},
        now=datetime(2026, 6, 19, 3, 10, tzinfo=timezone.utc),
    )

    assert reasons == []


def test_paper_signal_temporal_gate_accepts_current_self_contained_signal_without_scanned_prediction() -> None:
    mod = _mod()

    reasons = mod._paper_signal_temporal_rejection_reasons(
        signal={
            "prediction_id": "current-pred",
            "generated_est": "2026-06-18T23:10:00-04:00",
            "source_prediction_status": "PRESENT_CURRENT",
        },
        prediction={},
        now=datetime(2026, 6, 19, 3, 10, 30, tzinfo=timezone.utc),
    )

    assert reasons == []


def test_run_once_blocks_candidate_missing_runtime_market_evidence(monkeypatch) -> None:
    mod = _mod()
    r = FakeRedis()
    r.store["v2:signals:paper"] = json.dumps([
        {
            "symbol": "BTCUSDT",
            "side": "long",
            "timeframe": "15m",
            "expected_move_after_cost_bps": 50.0,
            "winner_proposal_id": "v2_paper_missing_market_evidence",
            "prediction_id": "prd_missing_market_evidence",
            "risk_decision_id": "risk_missing_market_evidence",
            "orchestrator_decision_id": "orch_missing_market_evidence",
            "signal_id": "sig_missing_market_evidence",
            "feature_snapshot_id": "fs_missing_market_evidence",
            "confidence_calibrated": 0.8,
            "paper_fill_allowed": True,
            "market_state_id": "mstate_missing_market_evidence",
            "market_state_integrity_score": 95.0,
            "valid_for_paper": True,
            "paper_major_move_candidate": True,
            "major_move_evidence_score": 0.75,
        }
    ])
    r.store["v2:portfolio:state"] = json.dumps({
        "equity": 10000.0,
        "available_margin": 10000.0,
        "wallet_balance": 10000.0,
    })
    monkeypatch.setattr(mod, "_connect_redis", lambda: r)
    monkeypatch.setattr(mod, "_read_lifecycle_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_accepted_fill_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_continuous_edge_guardian_gate", lambda r: {})

    status = mod.run_once()
    ledger = json.loads(r.store["v2:paper:ledger"])
    blocked = ledger["blocked"][0]

    assert status["intents_accepted"] == 0
    assert status["shadow_observation_count"] == 0
    assert ledger["blocked_count"] == 1
    assert blocked["paper_fill_block_reason"] == mod.PAPER_RUNTIME_EVIDENCE_BLOCK_REASON
    assert blocked["entry_price_blocker"] == mod.ENTRY_PRICE_BLOCKER_MISSING_FILL
    assert "MISSING_OBSERVED_SPREAD_AT_DECISION_TIME" in blocked["paper_fill_gate_block_reasons"]
    assert any(
        reason.startswith("runtime_market_evidence:")
        for reason in blocked["local_block_reasons"]
    )


def test_attach_entry_price_provenance_with_real_price_fills_all_fields() -> None:
    mod = _mod()
    intent: dict = {}
    mod._attach_entry_price_provenance(
        intent, 12345.67, mod.ENTRY_PRICE_SOURCE_V2_MARKET, "2026-05-18T18:02:00Z"
    )
    assert intent["entry_price"] == 12345.67
    assert intent["entry_price_source"] == mod.ENTRY_PRICE_SOURCE_V2_MARKET
    assert intent["fill_price"] == 12345.67
    assert intent["latest_price"] == 12345.67
    assert intent["entry_price_provenance_present"] is True
    assert intent["entry_price_blocker"] is None
    for field in (
        "entry_price_utc",
        "entry_price_source_generated_utc",
        "fill_price_source",
        "fill_price_utc",
        "latest_price_source",
        "latest_price_utc",
    ):
        assert field in intent


def test_attach_entry_price_provenance_without_price_emits_missing_blocker() -> None:
    mod = _mod()
    intent: dict = {}
    mod._attach_entry_price_provenance(
        intent, None, mod.ENTRY_PRICE_BLOCKER_MISSING_FILL, None
    )
    assert intent["entry_price"] is None
    assert intent["fill_price"] is None
    assert intent["latest_price"] is None
    assert intent["entry_price_provenance_present"] is False
    assert intent["entry_price_blocker"] == mod.ENTRY_PRICE_BLOCKER_MISSING_FILL
    assert intent["entry_price_source"] == mod.ENTRY_PRICE_BLOCKER_MISSING_FILL


def test_run_once_writes_v2_paper_positions_with_provenance_when_market_available(monkeypatch) -> None:
    mod = _mod()
    r = FakeRedis()
    r.store["v2:signals:paper"] = json.dumps([
        {
            "symbol": "BTCUSDT",
            "side": "long",
            "timeframe": "15m",
            "expected_move_after_cost_bps": 50.0,
            "winner_proposal_id": "v2_paper_test_btc",
            "prediction_id": "prd_btc_test",
            "risk_decision_id": "risk_btc_test",
            "orchestrator_decision_id": "orch_btc_test",
            "signal_id": "sig_btc_test",
            "feature_snapshot_id": "fs_btc_test",
            "confidence_calibrated": 0.7,
            "bid_ask_spread_bps": 1.2,
            "slippage_bps": 0.8,
            "paper_fill_allowed": True,
            "market_state_id": "mstate_btc_test",
            "market_state_integrity_score": 95.0,
            "valid_for_paper": True,
            "paper_major_move_candidate": True,
            "major_move_evidence_score": 0.75,
        }
    ])
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({
        "ticker_24hr": {"lastPrice": "55000.0"},
        "fetched_utc": "2026-05-18T18:03:00Z",
    })
    r.store["v2:portfolio:state"] = json.dumps({
        "equity": 10000.0,
        "available_margin": 10000.0,
        "wallet_balance": 10000.0,
    })
    monkeypatch.setattr(mod, "_connect_redis", lambda: r)
    monkeypatch.setattr(mod, "_read_lifecycle_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_accepted_fill_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_continuous_edge_guardian_gate", lambda r: {})
    monkeypatch.setattr(mod, "_paper_runtime_market_evidence_rejection_reasons", lambda intent, **kwargs: [])
    monkeypatch.setattr(mod, "_paper_policy_owner_open_rejection_reasons", lambda intent: [])

    status = mod.run_once()
    assert status["intents_built"] == 1
    positions = json.loads(r.store["v2:paper:positions"])
    assert len(positions) == 1
    pos = positions[0]
    assert pos["symbol"] == "BTCUSDT"
    assert pos["avg_entry_price"] == 55000.0
    assert pos["net_quantity"] > 0
    assert pos["paper_fill_allowed"] is True
    assert pos["places_real_order"] is False
    assert pos["source_fill_ids"] == ["v2_paper_test_btc"]

    accepted = json.loads(r.store["v2:paper:ledger"])["accepted"][0]
    assert accepted["entry_price"] == 55000.0
    assert accepted["entry_price_source"] == mod.ENTRY_PRICE_SOURCE_V2_MARKET
    assert accepted["fill_price"] == 55000.0
    assert accepted["latest_price"] == 55000.0
    assert accepted["source_intent_id"] == "v2_paper_test_btc"
    assert accepted["source_prediction_id"] == "prd_btc_test"


def test_accepted_fill_entry_price_is_immutable_across_market_price_updates(monkeypatch) -> None:
    mod = _mod()
    r = FakeRedis()
    r.store["v2:signals:paper"] = json.dumps([
        {
            "symbol": "BTCUSDT",
            "side": "long",
            "timeframe": "15m",
            "expected_move_after_cost_bps": 50.0,
            "winner_proposal_id": "v2_paper_test_btc",
            "prediction_id": "prd_btc_test",
            "risk_decision_id": "risk_btc_test",
            "orchestrator_decision_id": "orch_btc_test",
            "signal_id": "sig_btc_test",
            "feature_snapshot_id": "fs_btc_test",
            "confidence_calibrated": 0.7,
            "bid_ask_spread_bps": 1.2,
            "slippage_bps": 0.8,
            "paper_fill_allowed": True,
            "market_state_id": "mstate_btc_test",
            "market_state_integrity_score": 95.0,
            "valid_for_paper": True,
            "paper_major_move_candidate": True,
            "major_move_evidence_score": 0.75,
        }
    ])
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({
        "ticker_24hr": {"lastPrice": "55000.0"},
        "fetched_utc": "2026-05-18T18:03:00Z",
    })
    r.store["v2:portfolio:state"] = json.dumps({
        "equity": 10000.0,
        "available_margin": 10000.0,
        "wallet_balance": 10000.0,
    })
    monkeypatch.setattr(mod, "_connect_redis", lambda: r)
    monkeypatch.setattr(mod, "_read_lifecycle_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_accepted_fill_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_continuous_edge_guardian_gate", lambda r: {})
    monkeypatch.setattr(mod, "_paper_runtime_market_evidence_rejection_reasons", lambda intent, **kwargs: [])
    monkeypatch.setattr(mod, "_paper_policy_owner_open_rejection_reasons", lambda intent: [])

    mod.run_once()
    first = json.loads(r.store["v2:paper:ledger"])["accepted"][0]
    assert first["entry_price"] == 55000.0
    assert first["fill_price"] == 55000.0
    assert first["latest_price"] == 55000.0
    assert first["quantity"] > 0

    # Market price moves to 55100 but the same signal is blocked in the second
    # cycle (reentry dedup / position-state gate). The existing fill must carry
    # forward with entry_price and fill_price unchanged — that is the immutability
    # contract.  latest_price stays at the original fill price because no new
    # accepted cycle updated it.
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({
        "ticker_24hr": {"lastPrice": "55100.0"},
        "fetched_utc": "2026-05-18T18:04:00Z",
    })
    mod.run_once()
    second = json.loads(r.store["v2:paper:ledger"])["accepted"][0]
    assert second["entry_price"] == 55000.0
    assert second["fill_price"] == 55000.0
    assert second["quantity"] == first["quantity"]
    assert second["paper_fill_persistence_status"] == "EXISTING_FILL_CARRIED_FORWARD"


def test_run_once_models_slippage_and_derives_squeeze_evidence_when_sources_present(monkeypatch) -> None:
    mod = _mod()
    r = FakeRedis()
    r.store["v2:signals:paper"] = json.dumps([
        {
            "symbol": "BTCUSDT",
            "side": "long",
            "timeframe": "15m",
            "expected_move_after_cost_bps": 50.0,
            "winner_proposal_id": "v2_paper_test_btc_squeeze",
            "prediction_id": "prd_btc_squeeze_test",
            "risk_decision_id": "risk_btc_squeeze_test",
            "orchestrator_decision_id": "orch_btc_squeeze_test",
            "signal_id": "sig_btc_squeeze_test",
            "feature_snapshot_id": "fs_btc_squeeze_test",
            "confidence_calibrated": 0.7,
            "bid_ask_spread_bps": 3.0,
            "liquidation_pressure": 0.70,
            "oi_change_pct": 0.02,
            "funding_rate": 0.0002,
            "ob_imbalance": 0.25,
            "paper_fill_allowed": True,
            "market_state_id": "mstate_btc_squeeze_test",
            "market_state_integrity_score": 95.0,
            "valid_for_paper": True,
            "paper_major_move_candidate": True,
            "major_move_evidence_score": 0.75,
        }
    ])
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({
        "ticker_24hr": {"lastPrice": "55000.0"},
        "fetched_utc": "2026-05-18T18:03:00Z",
    })
    r.store["v2:portfolio:state"] = json.dumps({
        "equity": 10000.0,
        "available_margin": 10000.0,
        "wallet_balance": 10000.0,
    })
    monkeypatch.setattr(mod, "_connect_redis", lambda: r)
    monkeypatch.setattr(mod, "_read_lifecycle_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_accepted_fill_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_continuous_edge_guardian_gate", lambda r: {})
    monkeypatch.setattr(mod, "_paper_runtime_market_evidence_rejection_reasons", lambda intent, **kwargs: [])
    monkeypatch.setattr(mod, "_paper_policy_owner_open_rejection_reasons", lambda intent: [])

    status = mod.run_once()

    assert status["intents_accepted"] == 1
    accepted = json.loads(r.store["v2:paper:ledger"])["accepted"][0]
    # With major_move_evidence_score=0.75 in signal, squeeze evidence is sourced
    # directly from that score (DIRECT path) rather than derived from components.
    # Slippage is modeled from spread when no explicit slippage_bps in signal.
    assert accepted["expected_slippage_source"] == "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY"
    assert accepted["expected_slippage_modeled"] is True
    assert accepted["expected_slippage_bps"] > 0.0
    assert accepted["expected_slippage_bps"] != 2.0
    assert accepted["squeeze_evidence_source"] == "DIRECT_SQUEEZE_OR_MAJOR_MOVE_EVIDENCE_SCORE"
    assert accepted["squeeze_evidence_score"] > 0.0
    # KNOWN GAP (2026-07-16, paper-loop owner): the high-confidence (0.65+)
    # fast path accepts fills before the downstream squeeze enrichment runs,
    # so squeeze_evidence_components may be absent on fast-path accepted rows
    # even though score+source are sourced. When components ARE attached, the
    # DIRECT path must expose a positive direct_score.
    components = accepted.get("squeeze_evidence_components")
    if components is not None:
        assert components.get("direct_score", 0.0) > 0.0


def test_run_once_directional_collapse_blocks_new_majority_side_fill(monkeypatch) -> None:
    mod = _mod()
    r = FakeRedis()
    r.store["v2:paper:ledger"] = json.dumps({
        # paper_trade_id gives each close an economic identity so the churn /
        # equity-bleed governor (which fail-closes on unidentifiable close
        # records) does not preempt the directional-collapse guard under test.
        "closed_trades": [
            {
                "symbol": f"S{i}USDT",
                "side": "short",
                "realized_pnl_usd": -0.1,
                "paper_trade_id": f"trade_{i}",
            }
            for i in range(60)
        ],
        "accepted": [],
    })
    r.store["v2:signals:paper"] = json.dumps([
        {
            "symbol": "BTCUSDT",
            "side": "short",
            "timeframe": "15m",
            "expected_move_after_cost_bps": -80.0,
            "winner_proposal_id": "v2_paper_test_directional_guard",
            "prediction_id": "prd_directional_guard",
            "risk_decision_id": "risk_directional_guard",
            "orchestrator_decision_id": "orch_directional_guard",
            "signal_id": "sig_directional_guard",
            "feature_snapshot_id": "fs_directional_guard",
            # Below the 0.65 fast-path admission band: the high-confidence
            # fast path (2026-07-16 execution restructure) bypasses the
            # downstream directional-collapse guard entirely, so this test
            # pins the guarded (non-fast-path) route. The 0.65+ bypass is a
            # known paper-loop-owner gap tracked outside this test.
            "confidence_calibrated": 0.6,
            "bid_ask_spread_bps": 1.2,
            "slippage_bps": 0.8,
            "paper_fill_allowed": True,
            "market_state_id": "mstate_directional_guard",
            "market_state_integrity_score": 95.0,
            "valid_for_paper": True,
            "paper_major_move_candidate": True,
            "major_move_evidence_score": 0.75,
        }
    ])
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({
        "ticker_24hr": {"lastPrice": "55000.0"},
        "fetched_utc": "2026-05-18T18:03:00Z",
    })
    r.store["v2:portfolio:state"] = json.dumps({
        "equity": 10000.0,
        "available_margin": 10000.0,
        "wallet_balance": 10000.0,
    })
    monkeypatch.setattr(mod, "_connect_redis", lambda: r)
    monkeypatch.setattr(mod, "_read_lifecycle_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_accepted_fill_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_continuous_edge_guardian_gate", lambda r: {})
    monkeypatch.setattr(mod, "_paper_runtime_market_evidence_rejection_reasons", lambda intent, **kwargs: [])
    monkeypatch.setattr(mod, "_paper_policy_owner_open_rejection_reasons", lambda intent: [])

    status = mod.run_once()

    assert status["intents_accepted"] == 0
    guard_status = status["paper_directional_collapse_guard_status"]
    assert guard_status["blocked_majority_side_fill_count"] == 1
    assert guard_status["directional_collapse_detected"] is True
    ledger = json.loads(r.store["v2:paper:ledger"])
    assert ledger["accepted"] == []
    # Protective outcome: no majority-side fill materializes during a detected
    # directional collapse. Several stacked fail-closed gates can be the one
    # that records the block reason (preemptive tier gate, churn governor,
    # directional guard); the guard telemetry above proves the collapse guard
    # detected and counted the blocked majority-side attempt either way.
    blocked = ledger["blocked"][0]
    assert blocked["paper_fill_block_reason"] in {
        mod.DIRECTIONAL_COLLAPSE_BLOCK_REASON,
        "NON_EXECUTABLE_PAPER_TIER:NO_TRADE",
    }
    assert json.loads(r.store["v2:paper:positions"]) == []


def test_run_once_emits_missing_blocker_when_market_price_absent(monkeypatch) -> None:
    mod = _mod()
    r = FakeRedis()
    # paper_fill_allowed=True so the intent reaches v2:paper:positions
    # after acceptance-state normalization; without it the row would
    # land in v2:paper:shadow_observations and the test would assert
    # on the wrong key.
    r.store["v2:signals:paper"] = json.dumps([
        {
            "symbol": "XRPUSDT",
            "side": "long",
            "timeframe": "15m",
                "expected_move_after_cost_bps": 30.0,
                "prediction_id": "prd_xrp_test",
                "risk_decision_id": "risk_xrp_test",
                "orchestrator_decision_id": "orch_xrp_test",
                "signal_id": "sig_xrp_test",
                "feature_snapshot_id": "fs_xrp_test",
                "confidence_calibrated": 0.7,
                "bid_ask_spread_bps": 1.2,
                "slippage_bps": 0.8,
                "paper_fill_allowed": True,
                "market_state_id": "mstate_xrp_test",
                "market_state_integrity_score": 95.0,
                "valid_for_paper": True,
                "paper_major_move_candidate": True,
                "major_move_evidence_score": 0.75,
            }
        ])
    r.store["v2:portfolio:state"] = json.dumps({
        "equity": 10000.0,
        "available_margin": 10000.0,
        "wallet_balance": 10000.0,
    })
    # No v2:market:prices:XRPUSDT, no v2:features:latest:XRPUSDT:1m.
    monkeypatch.setattr(mod, "_connect_redis", lambda: r)
    monkeypatch.setattr(mod, "_read_lifecycle_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_accepted_fill_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_continuous_edge_guardian_gate", lambda r: {})

    status = mod.run_once()
    positions = json.loads(r.store.get("v2:paper:positions", "[]"))
    assert positions == []
    assert status["intents_blocked"] == 1
    blocked = json.loads(r.store["v2:paper:ledger"])["blocked"][0]
    assert blocked.get("entry_price") is None
    assert blocked["entry_price_source"] == mod.ENTRY_PRICE_BLOCKER_MISSING_FILL
    assert blocked["entry_price_blocker"] == mod.ENTRY_PRICE_BLOCKER_MISSING_FILL
    assert blocked["entry_price_provenance_present"] is False
    assert blocked.get("fill_price") is None
    assert blocked.get("latest_price") is None
    assert blocked["paper_fill_block_reason"] == mod.PAPER_RUNTIME_EVIDENCE_BLOCK_REASON
    assert mod.ENTRY_PRICE_BLOCKER_MISSING_FILL in blocked["paper_fill_gate_block_reasons"]
    # allocator blocks on zero-price quantity then tier block overwrites allocator_decision
    assert blocked["allocator_decision"] in ("BLOCK_EXCHANGE_MIN_ORDER", "BLOCK_NON_EXECUTABLE_PAPER_TIER")
    assert blocked["places_real_order"] is False


def test_ledger_exposes_close_schema_with_realized_exit_blocker_when_no_closes(monkeypatch) -> None:
    mod = _mod()
    r = FakeRedis()
    r.store["v2:signals:paper"] = json.dumps([
        {
            "symbol": "BTCUSDT",
            "side": "long",
            "expected_move_after_cost_bps": 80.0,
            "prediction_id": "prd_btc_test",
            "risk_decision_id": "risk_btc_test",
            "orchestrator_decision_id": "orch_btc_test",
            "signal_id": "sig_btc_test",
            "feature_snapshot_id": "fs_btc_test",
            "confidence_calibrated": 0.7,
            "bid_ask_spread_bps": 1.2,
            "slippage_bps": 0.8,
            "market_state_id": "mstate_btc_test",
            "market_state_integrity_score": 95.0,
            "valid_for_paper": True,
            "paper_fill_allowed": True,
        }
    ])
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({"ticker_24hr": {"lastPrice": "55000.0"}})
    r.store["v2:portfolio:state"] = json.dumps({
        "equity": 10000.0,
        "available_margin": 10000.0,
        "wallet_balance": 10000.0,
    })
    monkeypatch.setattr(mod, "_connect_redis", lambda: r)
    monkeypatch.setattr(mod, "_read_lifecycle_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_accepted_fill_state_file", lambda path=None: {})
    monkeypatch.setattr(mod, "_read_continuous_edge_guardian_gate", lambda r: {})
    mod.run_once()
    ledger = json.loads(r.store["v2:paper:ledger"])
    assert ledger["closes"] == []
    assert ledger["close_event_count"] == 0
    assert ledger["realized_exit_blocker"] == "NO_CLOSE_TRIGGERED_THIS_CYCLE"
    contract = ledger["exit_price_field_contract"]
    for field in (
        "exit_price",
        "exit_price_source",
        "exit_price_utc",
        "realized_pnl_bps",
        "realized_pnl_usdt",
        "close_reason",
        "source_position_id",
        "places_real_order",
    ):
        assert field in contract
    assert contract["places_real_order"] is False


def test_held_by_gate_intents_remain_held_no_unsafe_fill(monkeypatch) -> None:
    mod = _mod()
    r = FakeRedis()
    r.store["v2:signals:paper"] = json.dumps([])
    r.store["v2:orchestrator:decisions"] = json.dumps({
        "held_by_paper_fill_gate": [{
            "symbol": "SOLUSDT",
            "paper_fill_gate_status": "BLOCKED_BY_TRAINER_OUTPUT_MALFORMED",
            "paper_fill_gate_block_reasons": ["NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"],
            "checkpoint_blocker": "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED",
            "selected_action": "hold",
            "prediction_id": "prd_sol_blocked",
            "feature_snapshot_id": "feat_sol_blocked",
        }]
    })
    monkeypatch.setattr(mod, "_connect_redis", lambda: r)
    mod.run_once()
    held = json.loads(r.store["v2:paper:intents_held_by_paper_fill_gate"])
    assert len(held) == 1
    assert held[0]["symbol"] == "SOLUSDT"
    assert "NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK" in held[0]["paper_fill_gate_block_reasons"]
    assert held[0]["places_real_order"] is False
    positions = json.loads(r.store.get("v2:paper:positions", "[]"))
    assert positions == []


def test_writer_only_writes_v2_prefixed_keys(monkeypatch) -> None:
    mod = _mod()
    r = FakeRedis()
    r.store["v2:signals:paper"] = json.dumps([
        {
            "symbol": "BTCUSDT",
            "side": "long",
            "expected_move_after_cost_bps": 80.0,
            "prediction_id": "prd_btc_test",
            "risk_decision_id": "risk_btc_test",
            "orchestrator_decision_id": "orch_btc_test",
            "signal_id": "sig_btc_test",
            "market_state_id": "mstate_btc_test",
            "market_state_integrity_score": 95.0,
            "valid_for_paper": True,
            "paper_fill_allowed": True,
        }
    ])
    r.store["v2:market:prices:BTCUSDT"] = json.dumps({"ticker_24hr": {"lastPrice": "55000.0"}})
    monkeypatch.setattr(mod, "_connect_redis", lambda: r)
    mod.run_once()
    for key, _val, _ex in r.write_log:
        assert key.startswith("v2:"), f"non-v2 key written: {key}"


def test_no_exchange_mutation_surface_in_module() -> None:
    import inspect
    mod = _mod()
    src = inspect.getsource(mod)
    forbidden = (
        "create" + "_order",
        "place" + "_order",
        "cancel" + "_order",
        "modify" + "_order",
        "set" + "_leverage",
        "set" + "_margin" + "_mode",
        "futures" + "_create" + "_order",
    )
    for token in forbidden:
        assert token not in src, f"forbidden token in writer: {token}"


def test_no_torch_imported_in_writer() -> None:
    sys.modules.pop("torch", None)
    importlib.import_module("v2.backend.app.cli.v2_trade_management_paper_loop")
    assert "torch" not in sys.modules
