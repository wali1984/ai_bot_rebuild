from __future__ import annotations

import json
from types import SimpleNamespace

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    V2HybridTrainerDataLoader,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.publisher import (
    build_prediction_payload,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.safety import (
    V2OnlyJsonIO,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FeatureTensorRecord,
)


class _MemoryClient:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str):
        self.store[key] = value
        return True


class _StubTensorBuilder:
    def build(self, *, symbol: str, timeframe: str, payloads):  # noqa: ANN001
        del payloads
        values = (100.0, 101.0, 99.5, 101.0, 0.001, 56.0, 0.08, 0.04)
        feature_names = ("open", "high", "low", "close", "ret_pct", "rsi_14", "macd", "macd_signal")
        source_labels = ("synthetic",) * len(values)
        masks = (0,) * len(values)
        return FeatureTensorRecord(
            tensor_id="stub_tensor_clean_vs_corrupt",
            symbol=symbol,
            timeframe=timeframe,
            feature_snapshot_id="stub_feature_snapshot_clean_vs_corrupt",
            values=values,
            missing_mask=masks,
            stale_mask=masks,
            source_availability=masks,
            feature_names=feature_names,
            source_labels=source_labels,
            missing_feature_names=(),
            stale_feature_names=(),
            data_coverage_percent=100.0,
            source_availability_vector=masks,
        )


def _seed(
    client: _MemoryClient,
    *,
    feature_overrides: dict[str, object] | None = None,
    prediction_overrides: dict[str, object] | None = None,
) -> None:
    latest = {
        "feature_snapshot_id": "v2_fsnap_BTCUSDT_1m_rl_core_clean_corrupt",
        "feature_freshness_state": "CURRENT",
        "freshness_state": "FRESH",
        "generated_at": "2026-06-11T00:01:00Z",
        "feature_cutoff": "2026-06-11T00:01:00Z",
        "available_at": "2026-06-11T00:01:00Z",
        "source_event_time": "2026-06-11T00:01:00Z",
        "source_available_time": "2026-06-11T00:01:00Z",
        "decision_time": "2026-06-11T00:01:05Z",
        "candle_closed_confirmed": True,
        "candle_open_time": "2026-06-11T00:00:00Z",
        "candle_close_time": "2026-06-11T00:01:00Z",
        "all_tf_candle_timestamps": ["2026-06-11T00:01:00Z"],
        "all_source_event_times": ["2026-06-11T00:01:00Z"],
        "features": {
            "ret_pct": 0.001,
            "log_return": 0.001,
            "range_pct": 0.004,
            "body_pct": 0.001,
            "true_range_pct": 0.005,
            "ema_12": 101.0,
            "ema_26": 100.0,
            "rsi_14": 56.0,
            "macd": 0.08,
            "macd_signal": 0.04,
            "macd_hist": 0.04,
            "bb_width_pct": 0.012,
            "htf_ret_pct": 0.002,
            "htf_rsi_14": 58.0,
            "bid_ask_spread_bps": 3.0,
            "depth_imbalance": 0.15,
            "micro_price": 101.0,
            "toxicity_proxy": 0.1,
            "paper_position_present": 0,
        },
        "missing_feature_flags": [],
        "stale_feature_flags": [],
    }
    if feature_overrides:
        latest.update(feature_overrides)
    prediction = {
        "prediction_id": "pred_btc_1m",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "masa_feature_cutoff": "2026-06-11T00:01:00Z",
        "ppo_feature_cutoff": "2026-06-11T00:01:00Z",
        "source_mode": "paper",
    }
    if prediction_overrides:
        prediction.update(prediction_overrides)

    client.set("v2:features:latest:BTCUSDT:1m", json.dumps(latest))
    client.set(
        "v2:features:ta:BTCUSDT:1m",
        json.dumps({"indicators": {"ema_12": 101.0, "ema_26": 100.0, "rsi_14": 56.0}}),
    )
    client.set("v2:prediction:BTCUSDT:1m", json.dumps(prediction))
    client.set("v2:market:prices:BTCUSDT", json.dumps({"price": 101.0}))
    client.set(
        "v2:market:ohlcv:binance:BTCUSDT:1m",
        json.dumps({"open": 100.0, "high": 101.0, "low": 99.5, "close": 101.0, "volume": 1000.0}),
    )
    client.set(
        "v2:market:ohlcv_closed:binance:BTCUSDT:1m",
        json.dumps(
            [
                {
                    "candle_open_time": "2026-06-11T00:00:00Z",
                    "candle_close_time": "2026-06-11T00:01:00Z",
                    "available_at": "2026-06-11T00:01:00Z",
                    "event_time": "2026-06-11T00:01:00Z",
                    "closed_candle": True,
                    "is_closed": True,
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.5,
                    "close": 101.0,
                }
            ]
        ),
    )
    client.set(
        "v2:market:ohlcv_closed:binance:BTCUSDT:5m",
        json.dumps(
            [
                {
                    "candle_open_time": "2026-06-10T23:55:00Z",
                    "candle_close_time": "2026-06-11T00:00:00Z",
                    "available_at": "2026-06-11T00:00:00Z",
                    "event_time": "2026-06-11T00:00:00Z",
                    "closed_candle": True,
                    "is_closed": True,
                }
            ]
        ),
    )
    client.set(
        "v2:market:ohlcv_closed:binance:BTCUSDT:15m",
        json.dumps(
            [
                {
                    "candle_open_time": "2026-06-10T23:45:00Z",
                    "candle_close_time": "2026-06-11T00:00:00Z",
                    "available_at": "2026-06-11T00:00:00Z",
                    "event_time": "2026-06-11T00:00:00Z",
                    "closed_candle": True,
                    "is_closed": True,
                }
            ]
        ),
    )
    client.set(
        "v2:market:ohlcv_closed:binance:BTCUSDT:1h",
        json.dumps(
            [
                {
                    "candle_open_time": "2026-06-10T23:00:00Z",
                    "candle_close_time": "2026-06-11T00:00:00Z",
                    "available_at": "2026-06-11T00:00:00Z",
                    "event_time": "2026-06-11T00:00:00Z",
                    "closed_candle": True,
                    "is_closed": True,
                }
            ]
        ),
    )
    client.set(
        "v2:market:ohlcv_closed:binance:BTCUSDT:4h",
        json.dumps(
            [
                {
                    "candle_open_time": "2026-06-10T20:00:00Z",
                    "candle_close_time": "2026-06-11T00:00:00Z",
                    "available_at": "2026-06-11T00:00:00Z",
                    "event_time": "2026-06-11T00:00:00Z",
                    "closed_candle": True,
                    "is_closed": True,
                }
            ]
        ),
    )
    client.set("v2:market:orderbook:BTCUSDT", json.dumps({"spread_bps": 3.0, "depth_imbalance": 0.15}))
    client.set("v2:market:funding:BTCUSDT", json.dumps({"funding_rate": 0.0001}))
    client.set("v2:market:open_interest:BTCUSDT", json.dumps({"open_interest": 1000000.0}))
    client.set("v2:market:open_interest_hist:BTCUSDT:5m", json.dumps({"change_pct": 0.01}))
    client.set("v2:market:long_short:BTCUSDT", json.dumps({"long_short_ratio": 1.5, "long_account_ratio": 0.6, "short_account_ratio": 0.4}))
    client.set("v2:market:microstructure:BTCUSDT", json.dumps({"micro_price": 101.0, "toxicity_proxy": 0.1}))
    client.set("v2:market:liquidation_levels:BTCUSDT", json.dumps({"nearest_distance_bps": 150.0}))
    client.set("v2:altdata:public_intel:symbol:BTCUSDT", json.dumps({"public_intel_score": 0.5}))
    client.set("v2:altdata:aicoin:symbol:BTCUSDT", json.dumps({"aicoin_order_flow_score": 0.2}))
    client.set("v2:altdata:whale_walls:symbol:BTCUSDT", json.dumps({"whale_wall_score": 0.8, "whale_bid_pressure_score": 0.85}))
    client.set("v2:altdata:lunarcrush:symbol:BTCUSDT", json.dumps({"score": 0.5}))
    client.set("v2:altdata:nansen:symbol:BTCUSDT", json.dumps({"presence": 1.0}))
    client.set(
        "v2:altdata:symbol_score:BTCUSDT",
        json.dumps(
            {
                "altdata_symbol_score": 0.5,
                "provider_availability_score": 1.0,
                "altdata_freshness_score": 1.0,
                "public_intel_score": 0.5,
                "coingecko_discovery_score": 0.6,
                "defillama_liquidity_score": 0.4,
                "aicoin_order_flow_score": 0.2,
                "whale_wall_score": 0.8,
                "whale_bid_pressure_score": 0.85,
            }
        ),
    )
    client.set("v2:liquidations:events", json.dumps({"count_5m": 1}))
    client.set("v2:risk:decisions", json.dumps({"recent_allow_rate": 0.0}))
    client.set("v2:orchestrator:decisions", json.dumps({"recent_allow_rate": 0.0}))
    client.set("v2:paper:positions", json.dumps({"position_present": 0, "unrealized_bps": 0.0}))
    client.set("v2:paper:ledger", json.dumps({"entries": []}))
    client.set("v2:paper:position_history", json.dumps({"entries": []}))


def _model_output(**overrides) -> SimpleNamespace:
    values = {
        "selected_action": "long",
        "selected_action_index": 1,
        "action_probabilities": [0.1, 0.8, 0.1, 0.0, 0.0, 0.0, 0.0],
        "expected_move_bps": 15.0,
        "confidence_raw": 0.9,
        "confidence_calibrated": 0.9,
        "calibration": "test",
        "policy_value": 0.0,
        "masa_signal": 0.55,
        "model_id": "model-test",
        "device": "cpu",
        "cuda_active": False,
        "model_tensors_device_verified": False,
    }
    values.update(overrides)
    return SimpleNamespace(
        **values,
    )


def test_clean_path_produces_publishable_prediction_payload() -> None:
    client = _MemoryClient()
    _seed(client)
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=client), tensor_builder=_StubTensorBuilder())

    example = loader.build_example(symbol="BTCUSDT", timeframe="1m")
    trusted = loader.load_training_examples(symbols=("BTCUSDT",), timeframes=("1m",), trusted_only=True)
    payload = build_prediction_payload(
        example=example,
        model_output=_model_output(),
        checkpoint=None,
        round_trip_cost_bps=0.0,
        min_data_coverage_percent=1.0,
        min_confidence_calibrated=0.0,
        min_edge_after_cost_bps=0.0,
    )

    assert example.row_classification != "MARKET_STATE_REJECTED"
    assert len(trusted) == 1
    assert payload["paper_fill_allowed"] is True
    assert payload["replay_snapshot_ready"] is True
    assert payload["replay_snapshot_id"] == payload["decision_id"]
    assert str(payload["mtf_snapshot_id"]).startswith("mtf_")
    assert payload["input_feature_hash"]
    assert payload["all_tf_candle_timestamps"]
    assert payload["counterfactual_directional_action_from_expected_move"] == "long"
    assert payload["counterfactual_directional_expected_move_after_cost_bps"] == 15.0
    assert payload["selected_hold_with_directional_edge_after_cost"] is False
    assert "market_state_invalid_for_prediction" not in payload["paper_fill_gate_block_reasons"]
    assert payload["market_state_integrity_score"] >= 80.0


def test_hold_with_directional_edge_is_diagnostic_only_and_blocked() -> None:
    client = _MemoryClient()
    _seed(client)
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=client), tensor_builder=_StubTensorBuilder())

    example = loader.build_example(symbol="BTCUSDT", timeframe="1m")
    payload = build_prediction_payload(
        example=example,
        model_output=_model_output(
            selected_action="hold",
            selected_action_index=0,
            action_probabilities=[0.250001, 0.05, 0.25, 0.0, 0.0, 0.0, 0.0],
            expected_move_bps=-20.0,
            confidence_raw=0.250001,
            confidence_calibrated=0.9,
        ),
        checkpoint=None,
        round_trip_cost_bps=12.0,
        min_data_coverage_percent=1.0,
        min_confidence_calibrated=0.0,
        min_edge_after_cost_bps=4.0,
    )

    assert payload["paper_fill_allowed"] is False
    assert payload["routes_to_orchestrator"] is False
    assert "action_not_directional" in payload["paper_fill_gate_block_reasons"]
    assert "expected_move_after_cost_below_threshold" in payload["paper_fill_gate_block_reasons"]
    assert payload["expected_move_after_cost_bps"] == 0.0
    assert payload["counterfactual_directional_action_from_expected_move"] == "short"
    assert payload["counterfactual_directional_expected_move_after_cost_bps"] == -8.0
    assert payload["counterfactual_directional_action_probability"] == 0.25
    assert payload["selected_action_probability"] == 0.250001
    assert payload["selected_hold_with_directional_edge_after_cost"] is True
    assert (
        payload["selected_hold_directional_edge_diagnostic_reason"]
        == "EXPECTED_MOVE_DIRECTIONAL_EDGE_BLOCKED_BY_SELECTED_HOLD"
    )


def test_corrupt_path_is_blocked_before_training_and_prediction() -> None:
    client = _MemoryClient()
    _seed(
        client,
        feature_overrides={"available_at": "2026-06-11T00:01:06Z"},
        prediction_overrides={"masa_feature_cutoff": "2026-06-11T00:01:06Z"},
    )
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=client), tensor_builder=_StubTensorBuilder())

    example = loader.build_example(symbol="BTCUSDT", timeframe="1m")
    trusted = loader.load_training_examples(symbols=("BTCUSDT",), timeframes=("1m",), trusted_only=True)
    payload = build_prediction_payload(
        example=example,
        model_output=_model_output(),
        checkpoint=None,
        round_trip_cost_bps=0.0,
        min_data_coverage_percent=1.0,
        min_confidence_calibrated=0.0,
        min_edge_after_cost_bps=0.0,
    )

    assert example.row_classification == "MARKET_STATE_REJECTED"
    assert trusted == []
    assert payload["paper_fill_allowed"] is False
    assert any(reason.startswith("training_trust:") for reason in payload["paper_fill_gate_block_reasons"])
