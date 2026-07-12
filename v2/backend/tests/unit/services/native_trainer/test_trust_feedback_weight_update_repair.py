from __future__ import annotations

import inspect
import json
from datetime import datetime
from pathlib import Path

import pytest

from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop
from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION
from v2.backend.app.services.native_trainer.feedback_enrichment import (
    build_strategy_hedge_exit_feedback,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import checkpoint as checkpoint_module
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import model as model_module
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer import ppo_trainer as ppo_trainer_module
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.checkpoint import (
    V2HybridCheckpointManager,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    TrainingExample,
    V2HybridTrainerDataLoader,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (
    V2HybridPPOTrainer,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import (
    FEATURE_SPEC,
    FeatureTensorRecord,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.safety import V2OnlyJsonIO
from v2.backend.app.services.paper_trade_management.outcomes import build_close_event
from v2.backend.app.services.paper_trade_management.position_state import position_from_fill


DECISION_TIME = "2026-06-21T10:01:00Z"
AVAILABLE_AT = "2026-06-21T10:00:30Z"
FEATURE_CUTOFF = "2026-06-21T10:00:00Z"


def test_training_window_gpu_sample_parser_and_summary() -> None:
    sample = ppo_trainer_module._parse_nvidia_smi_training_sample("72, 9820, 16303")

    assert sample == {
        "gpu_utilization_percent": 72.0,
        "vram_used_mb": 9820.0,
        "vram_total_mb": 16303.0,
    }

    summary = ppo_trainer_module._summarize_training_gpu_samples(
        [
            sample,
            {
                "gpu_utilization_percent": 58.0,
                "vram_used_mb": 9400.0,
                "vram_total_mb": 16303.0,
            },
        ]
    )

    assert summary["training_window_gpu_sampler_active"] is True
    assert summary["training_window_gpu_utilization_sample_count"] == 2
    assert summary["training_window_gpu_utilization_avg_percent"] == 65.0
    assert summary["training_window_gpu_utilization_max_percent"] == 72.0
    assert summary["training_window_vram_used_max_fraction"] == round(9820.0 / 16303.0, 6)


def _epoch_ms(iso_value: str) -> int:
    parsed = datetime.fromisoformat(iso_value.replace("Z", "+00:00"))
    return int(parsed.timestamp() * 1000)


def _source_hashes(feature_snapshot_id: str = "feat_1") -> dict[str, str]:
    return {
        "feature_vector_hash": f"hash_{feature_snapshot_id}",
        "input_feature_hash": f"input_{feature_snapshot_id}",
        "prediction_hash": f"prediction_{feature_snapshot_id}",
    }


def _premium_feature_values() -> dict[str, float]:
    return {
        "orderbook_depth_usd": 250000.0,
        "bid_depth_usd": 130000.0,
        "ask_depth_usd": 120000.0,
        "depth_imbalance": 0.04,
        "bid_ask_spread_bps": 1.2,
        "micro_price": 100.2,
        "funding_rate": 0.0001,
        "expected_funding_bps": 1.0,
        "long_short_ratio": 1.2,
        "oi_change_pct": 0.01,
        "nearest_liquidation_level_above": 103.0,
        "nearest_liquidation_level_below": 97.0,
        "liquidation_sweep_target_short_distance_bps": 76.0,
        "liquidation_sweep_target_long_distance_bps": 115.0,
        "liquidation_pressure_direction": -0.22,
        "liquidation_levels_count_long": 4.0,
        "liquidation_levels_count_short": 3.0,
        "public_intel_score": 0.1,
        "news_sentiment_score": 0.05,
    }


def _premium_contexts() -> dict[str, dict[str, object]]:
    return {
        "liquidity_context": {
            "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS",
            "orderbook_depth_usd": 250000.0,
            "bid_depth_usd": 130000.0,
            "ask_depth_usd": 120000.0,
            "depth_imbalance": 0.04,
        },
        "liquidity_zone_context": {
            "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS",
            "orderbook_depth_usd": 250000.0,
            "nearest_bid_wall_distance_bps": 42.0,
            "nearest_ask_wall_distance_bps": 58.0,
        },
        "liquidation_distance_context": {
            "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS",
            "nearest_liquidation_level_above": 103.0,
            "nearest_liquidation_level_below": 97.0,
            "liquidation_sweep_target_short_distance_bps": 76.0,
            "liquidation_sweep_target_long_distance_bps": 115.0,
            "liquidation_pressure_direction": -0.22,
        },
        "liquidation_context": {
            "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS",
            "nearest_liquidation_level_above": 103.0,
            "nearest_liquidation_level_below": 97.0,
            "liquidation_sweep_target_short_distance_bps": 76.0,
            "liquidation_sweep_target_long_distance_bps": 115.0,
            "liquidation_pressure_direction": -0.22,
        },
        "microstructure_context": {
            "source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:unit",
            "bid_ask_spread_bps": 1.2,
            "orderbook_depth_usd": 250000.0,
            "depth_imbalance": 0.04,
            "micro_price": 100.2,
        },
        "oi_funding_context": {
            "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS",
            "funding_rate": 0.0001,
            "expected_funding_bps": 1.0,
            "long_short_ratio": 1.2,
            "oi_change_pct": 0.01,
        },
        "public_intel_context": {
            "source": "V2_ENTRY_FEATURE_SNAPSHOT_PREMIUM_INGESTORS",
            "public_intel_score": 0.1,
            "news_sentiment_score": 0.05,
        },
    }


def _feature_snapshot(
    feature_snapshot_id: str = "feat_1",
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "1m",
) -> dict[str, object]:
    features = {name: 1.0 for name, _source in FEATURE_SPEC}
    features.update(_premium_feature_values())
    return {
        "feature_snapshot_id": feature_snapshot_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "available_at": AVAILABLE_AT,
        "generated_at": AVAILABLE_AT,
        "feature_cutoff": FEATURE_CUTOFF,
        "source_available_time": AVAILABLE_AT,
        "candle_open_time": "2026-06-21T09:59:00Z",
        "candle_close_time": FEATURE_CUTOFF,
        "candle_closed_confirmed": True,
        "latest_unclosed_kline_excluded": True,
        "source_hashes": _source_hashes(feature_snapshot_id),
        "categories_present": ["microstructure", "funding_oi_liquidation", "premium_ingestors"],
        "external_v2_sources_present": ["v2:unified_features", "v2:liquidation_levels_engine"],
        "missing_feature_flags": [],
        "stale_feature_flags": [],
        "features": features,
    }


def _trust_prediction(
    *,
    prediction_id: str = "pred_1",
    symbol: str = "BTCUSDT",
    timeframe: str = "1m",
    selected_action: str = "long",
    feature_snapshot_id: str = "feat_1",
    available_at: str = AVAILABLE_AT,
) -> dict[str, object]:
    return {
        "prediction_id": prediction_id,
        "signal_id": "sig_1",
        "decision_id": "decision_1",
        "orchestrator_decision_id": "decision_1",
        "feature_snapshot_id": feature_snapshot_id,
        "mtf_snapshot_id": "mtf_1",
        "feature_cutoff": FEATURE_CUTOFF,
        "decision_time": DECISION_TIME,
        "available_at": available_at,
        "symbol": symbol,
        "timeframe": timeframe,
        "selected_action": selected_action,
        "model_version": "unit_model_v1",
        "model_source": "unit_model_v1",
        "checkpoint_id": "ckpt_1",
        "source_hashes": _source_hashes(feature_snapshot_id),
        "feature_vector_hash": f"hash_{feature_snapshot_id}",
        "input_feature_hash": f"input_{feature_snapshot_id}",
    }


def _audit_fields() -> dict[str, object]:
    return {
        "actual_observed_spread_entry_bps": 1.2,
        "actual_observed_spread_exit_bps": 1.4,
        "entry_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:unit",
        "exit_spread_source": "V2_MARKET_ORDERBOOK_TOP_OF_BOOK:unit",
        "expected_slippage_bps": 0.7,
        "expected_slippage_usd": 0.01,
        "expected_slippage_source": "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY",
        "expected_slippage_modeled": True,
        "realized_slippage_bps": 0.8,
        "realized_slippage_usd": 0.01,
        "implementation_shortfall_usd": 0.0,
        "squeeze_evidence_score": 0.0,
        "squeeze_evidence_source": "DERIVED_FROM_LIQUIDATION_OI_FUNDING_ORDERBOOK_CONTEXT",
        "squeeze_evidence_components": {"spread_stress": 0.0},
        "mfe_bps": 20.0,
        "mfe_usd": 2.0,
        "mae_bps": 5.0,
        "mae_usd": 0.5,
        "intra_trade_high_price": 102.0,
        "intra_trade_low_price": 99.5,
        "trailing_stop_history": [],
        **_premium_contexts(),
    }


def _close_and_outcome(*, action: str = "long", symbol: str = "BTCUSDT") -> tuple[dict[str, object], dict[str, object]]:
    close_event = {
        "trainer_feedback_id": "fb_1",
        "outcome_label_id": "out_1",
        "position_id": "pos_1",
        "symbol": symbol,
        "prediction_id": "pred_1",
        "entry_prediction_id": "pred_1",
        "signal_id": "sig_1",
        "entry_signal_id": "sig_1",
        "feature_snapshot_id": "feat_1",
        "entry_feature_snapshot_id": "feat_1",
        "market_state_id": "ms_1",
        "entry_market_state_id": "ms_1",
        "timeframe": "1m",
        "action": action,
        "selected_action": action,
        "entry_price": 100.0,
        "exit_price": 101.0 if action == "long" else 99.0,
        "realized_pnl": 1.0,
        "realized_pnl_usd": 1.0,
        "realized_pnl_bps": 100.0,
        "strategy_id": "trend_following_v1",
        "strategy_family": "trend_following",
        "strategy_subtype": "trend_following_v1",
        "hedge_state": "NO_HEDGE",
        "hedge_reason": "NO_HEDGE_CONTEXT",
        "exit_reason": "TIER_2_TAKE_PROFIT",
        "hold_time_seconds": 300,
        "exit_time": "2026-06-21T10:06:00Z",
        "market_regime": "TREND",
        "market_regime_at_entry": "TREND",
        "market_regime_at_exit": "TREND",
        **_premium_contexts(),
        "future_window_label_source": "closed_trade_outcome",
        "drawdown_at_entry": 0.0,
        **_audit_fields(),
    }
    outcome_label = {
        **close_event,
        "outcome_label_id": "out_1",
        "directional_outcome": "UP" if action == "long" else "DOWN",
        "trade_outcome": "WIN",
    }
    return close_event, outcome_label


def _tensor(index: int = 1) -> FeatureTensorRecord:
    return FeatureTensorRecord(
        tensor_id=f"tensor_{index}",
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id=f"feat_{index}",
        values=(float(index),),
        missing_mask=(0,),
        stale_mask=(0,),
        source_availability=(1,),
        feature_names=("ret_pct",),
        source_labels=("unit",),
        missing_feature_names=(),
        stale_feature_names=(),
        data_coverage_percent=100.0,
        source_availability_vector=(1,),
    )


def _outcome_targets() -> dict[str, object]:
    return {
        "realized_net_pnl_bps": 42.0,
        "realized_net_pnl_usd": 4.2,
        "directional_outcome": "UP",
        "trade_outcome": "WIN",
        "selected_action": "long",
        "action_was_profitable": True,
        "holding_period": 300,
        "fees": 0.1,
        "slippage": 0.05,
        "funding": 0.0,
        "MFE": 55.0,
        "MAE": 8.0,
        "exit_reason": "TIER_2_TAKE_PROFIT",
    }


def _training_example(index: int = 1, *, trust_overrides: dict[str, object] | None = None) -> TrainingExample:
    tensor = _tensor(index)
    trust_row: dict[str, object] = {
        "prediction_id": f"pred_{index}",
        "signal_id": f"sig_{index}",
        "decision_id": f"decision_{index}",
        "feature_snapshot_id": tensor.feature_snapshot_id,
        "mtf_snapshot_id": f"mtf_{index}",
        "feature_cutoff": FEATURE_CUTOFF,
        "decision_cutoff": FEATURE_CUTOFF,
        "decision_time": DECISION_TIME,
        "decision_time_est": DECISION_TIME,
        "available_at": AVAILABLE_AT,
        "source_available_time": AVAILABLE_AT,
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "selected_action": "long",
        "model_version": "unit_model_v1",
        "checkpoint_id": "ckpt_1",
        "source_hashes": _source_hashes(tensor.feature_snapshot_id),
        "feature_vector_hash": tensor.tensor_id,
        "input_feature_hash": tensor.tensor_id,
        "accepted_for_training": True,
        "reject_reasons": [],
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "mtf_snapshot_valid": True,
        "replay_snapshot_id": f"replay_{index}",
        "candle_closed_confirmed": True,
        "closed_candle": True,
        "feature_freshness_state": "CURRENT",
        "freshness_state": "CURRENT",
        "latency_ms": 10,
        "candle_open_time": "2026-06-21T09:59:00Z",
        "candle_close_time": FEATURE_CUTOFF,
        "source_event_time": FEATURE_CUTOFF,
        "source_event_time_est": FEATURE_CUTOFF,
        "source_received_time_est": FEATURE_CUTOFF,
        "features": {"ret_pct": 0.0},
        "outcome_targets": _outcome_targets(),
        "realized_after_cost_reward": 0.42,
        "value_baseline": 0.10,
        "advantage": 0.32,
        "advantage_source": "realized_after_cost_reward_minus_value_baseline",
        "realized_reward_source": "realized_net_pnl_bps_after_cost",
        "uses_expected_move_as_realized_reward": False,
        "expected_move_after_cost_bps": 9999.0,
    }
    trust_row.update(trust_overrides or {})
    return TrainingExample(
        symbol="BTCUSDT",
        timeframe="1m",
        tensor=tensor,
        label_action_index=1,
        label_expected_move_after_cost_bps=42.0,
        payload_keys=("unit",),
        row_classification="TRAINABLE",
        trust_row=trust_row,
    )


class _FakeRedis:
    def __init__(self, store: dict[str, object]) -> None:
        self.store = store

    def get(self, key: str) -> str | None:
        value = self.store.get(key)
        if value is None:
            return None
        import json

        return json.dumps(value)


def _train_one() -> tuple[V2HybridPolicyModel, object]:
    example = _training_example()
    model = V2HybridPolicyModel(input_dim=len(example.tensor.model_vector), seed=7)
    trainer = V2HybridPPOTrainer(model=model)
    result = trainer.train([example], steps=1, batch_size=1, validation_fraction=0.0)
    return model, result


def test_trust_envelope_survives_full_paper_lifecycle() -> None:
    fill = {
        "fill_id": "fill_1",
        "ledger_row_id": "fill_1",
        "intent_id": "intent_1",
        "symbol": "BTCUSDT",
        "side": "long",
        "quantity": 1.0,
        "notional": 100.0,
        "entry_price": 100.0,
        "fill_price": 100.0,
        "fill_price_utc": DECISION_TIME,
        "generated_utc": DECISION_TIME,
        "prediction_id": "pred_1",
        "signal_id": "sig_1",
        "risk_decision_id": "risk_1",
        "orchestrator_decision_id": "decision_1",
        "market_state_id": "ms_1",
        "decision_id": "decision_1",
        "feature_snapshot_id": "feat_1",
        "mtf_snapshot_id": "mtf_1",
        "feature_cutoff": FEATURE_CUTOFF,
        "decision_time": DECISION_TIME,
        "available_at": AVAILABLE_AT,
        "selected_action": "long",
        "model_version": "unit_model_v1",
        "checkpoint_id": "ckpt_1",
        "source_hashes": _source_hashes(),
        "entry_feature_snapshot": _feature_snapshot(),
        "timeframe": "1m",
        "strategy_id": "trend_following_v1",
        "strategy_family": "trend_following",
        "strategy_subtype": "trend_following_v1",
        "strategy_selected_mode": "trend_following_v1",
        "hedge_state": "NO_HEDGE",
        "hedge_reason": "NO_HEDGE_CONTEXT",
        "market_regime_at_entry": "TREND",
        **_audit_fields(),
    }
    position = position_from_fill(fill, fill_id="fill_1", side="long", quantity=1.0, price=100.0)
    assert position.entry_feature_snapshot == _feature_snapshot()
    assert position.to_payload(generated_utc=DECISION_TIME)["entry_feature_snapshot"] == _feature_snapshot()
    close_event, outcome = build_close_event(
        position=position,
        close_quantity=1.0,
        exit_price=102.0,
        exit_time="2026-06-21T10:06:00Z",
        close_reason="TIER_2_TAKE_PROFIT",
        exit_spread_bps=1.4,
        exit_spread_source="V2_MARKET_ORDERBOOK_TOP_OF_BOOK:unit",
    )
    feedback = build_strategy_hedge_exit_feedback(close_event=close_event, outcome_label=outcome)

    assert close_event["entry_feature_snapshot"] == _feature_snapshot()
    assert outcome["entry_feature_snapshot"] == _feature_snapshot()
    assert feedback["entry_feature_snapshot"] == _feature_snapshot()
    for field in (
        "prediction_id",
        "signal_id",
        "decision_id",
        "feature_snapshot_id",
        "mtf_snapshot_id",
        "feature_cutoff",
        "decision_time",
        "available_at",
        "symbol",
        "timeframe",
        "selected_action",
        "model_version",
        "checkpoint_id",
        "source_hashes",
    ):
        assert feedback[field]
    assert feedback["trainer_consumable"] is True


def test_prediction_id_alone_is_not_sufficient_trust() -> None:
    close_event, outcome = _close_and_outcome()
    rows = paper_loop._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[close_event],
        outcome_labels=[outcome],
        predictions_by_id={},
    )
    assert rows[0]["trainer_consumable"] is False
    assert "TRUST_RECONSTRUCTION:ENTRY_PREDICTION_NOT_FOUND" in rows[0]["trust_envelope_rejection_reasons"]


def test_verified_lineage_reconstructs_existing_feedback() -> None:
    close_event, outcome = _close_and_outcome()
    prediction = _trust_prediction()
    prediction.update(
        {
            "confidence_raw": 0.58,
            "confidence_calibrated": 0.62,
            "expected_move_bps": 34.0,
            "expected_move_after_cost_bps": 27.5,
            "selected_action_probability": 0.64,
        }
    )
    rows = paper_loop._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[close_event],
        outcome_labels=[outcome],
        predictions_by_id={"pred_1": prediction},
    )
    row = rows[0]
    assert row["trainer_consumable"] is True
    assert row["trust_reconstructed"] is True
    assert row["trust_source_ids"]["entry_prediction_id"] == "pred_1"
    assert row["decision_id"] == "decision_1"
    assert row["source_hashes"]["feature_vector_hash"] == "hash_feat_1"
    assert row["confidence_calibrated"] == pytest.approx(0.62)
    assert row["expected_move_after_cost_bps"] == pytest.approx(27.5)
    assert row["prediction_score_source"] == "VERIFIED_ENTRY_PREDICTION"


def test_epoch_ms_feature_cutoff_reconstructs_existing_feedback() -> None:
    close_event, outcome = _close_and_outcome()
    prediction = _trust_prediction()
    prediction["feature_cutoff"] = _epoch_ms(FEATURE_CUTOFF)

    rows = paper_loop._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[close_event],
        outcome_labels=[outcome],
        predictions_by_id={"pred_1": prediction},
    )

    row = rows[0]
    assert row["trainer_consumable"] is True
    assert row["trust_reconstructed"] is True
    assert row["feature_cutoff"] == _epoch_ms(FEATURE_CUTOFF)


def test_mismatched_lineage_remains_quarantined() -> None:
    close_event, outcome = _close_and_outcome()
    rows = paper_loop._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[close_event],
        outcome_labels=[outcome],
        predictions_by_id={"pred_1": _trust_prediction(symbol="ETHUSDT")},
    )
    assert rows[0]["trainer_consumable"] is False
    assert "TRUST_RECONSTRUCTION:SYMBOL_MISMATCH" in rows[0]["trust_envelope_rejection_reasons"]


def test_future_available_at_is_rejected() -> None:
    close_event, outcome = _close_and_outcome()
    rows = paper_loop._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[close_event],
        outcome_labels=[outcome],
        predictions_by_id={"pred_1": _trust_prediction(available_at="2026-06-21T10:02:00Z")},
    )
    assert rows[0]["trainer_consumable"] is False
    assert "TRUST_RECONSTRUCTION:AVAILABLE_AT_AFTER_DECISION_TIME" in rows[0]["trust_envelope_rejection_reasons"]


def test_future_epoch_ms_feature_cutoff_is_rejected() -> None:
    close_event, outcome = _close_and_outcome()
    prediction = _trust_prediction()
    prediction["feature_cutoff"] = _epoch_ms("2026-06-21T10:02:00Z")

    rows = paper_loop._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[close_event],
        outcome_labels=[outcome],
        predictions_by_id={"pred_1": prediction},
    )

    assert rows[0]["trainer_consumable"] is False
    assert "TRUST_RECONSTRUCTION:FEATURE_CUTOFF_AFTER_DECISION_TIME" in rows[0]["trust_envelope_rejection_reasons"]


def test_realized_pnl_generates_outcome_targets() -> None:
    fill = {
        "fill_id": "fill_1",
        "symbol": "BTCUSDT",
        "side": "long",
        "quantity": 1.0,
        "entry_price": 100.0,
        "fill_price": 100.0,
        "fill_price_utc": DECISION_TIME,
        "generated_utc": DECISION_TIME,
        "prediction_id": "pred_1",
        "signal_id": "sig_1",
        "decision_id": "decision_1",
        "feature_snapshot_id": "feat_1",
        "mtf_snapshot_id": "mtf_1",
        "feature_cutoff": FEATURE_CUTOFF,
        "decision_time": DECISION_TIME,
        "available_at": AVAILABLE_AT,
        "selected_action": "long",
        "model_version": "unit_model_v1",
        "checkpoint_id": "ckpt_1",
        "source_hashes": _source_hashes(),
        "timeframe": "1m",
        **_audit_fields(),
    }
    position = position_from_fill(fill, fill_id="fill_1", side="long", quantity=1.0, price=100.0)
    close_event, outcome = build_close_event(
        position=position,
        close_quantity=1.0,
        exit_price=103.0,
        exit_time="2026-06-21T10:06:00Z",
        close_reason="TIER_2_TAKE_PROFIT",
        exit_spread_bps=1.4,
    )
    targets = outcome["outcome_targets"]
    assert targets["realized_net_pnl_bps"] == pytest.approx(outcome["realized_net_pnl_bps"])
    assert targets["realized_net_pnl_usd"] == pytest.approx(outcome["realized_net_pnl_usd"])
    assert targets["directional_outcome"] == "UP"
    assert targets["trade_outcome"] == "WIN"
    assert targets["selected_action"] == "long"
    assert targets["action_was_profitable"] is True
    assert targets["exit_reason"] == "TIER_2_TAKE_PROFIT"


def test_entry_prediction_scores_survive_close_and_feedback() -> None:
    fill = {
        "fill_id": "fill_1",
        "symbol": "BTCUSDT",
        "side": "long",
        "quantity": 1.0,
        "entry_price": 100.0,
        "fill_price": 100.0,
        "fill_price_utc": DECISION_TIME,
        "generated_utc": DECISION_TIME,
        "prediction_id": "pred_1",
        "signal_id": "sig_1",
        "decision_id": "decision_1",
        "feature_snapshot_id": "feat_1",
        "mtf_snapshot_id": "mtf_1",
        "feature_cutoff": FEATURE_CUTOFF,
        "decision_time": DECISION_TIME,
        "available_at": AVAILABLE_AT,
        "selected_action": "long",
        "model_version": "unit_model_v1",
        "checkpoint_id": "ckpt_1",
        "source_hashes": _source_hashes(),
        "timeframe": "1m",
        "confidence_raw": 0.57,
        "confidence_calibrated": 0.63,
        "expected_move_bps": 31.0,
        "expected_move_after_cost_bps": 24.0,
        "selected_action_probability": 0.66,
        "policy_value": 0.12,
        "value_baseline": 0.08,
        **_audit_fields(),
    }
    position = position_from_fill(fill, fill_id="fill_1", side="long", quantity=1.0, price=100.0)
    close_event, outcome = build_close_event(
        position=position,
        close_quantity=1.0,
        exit_price=103.0,
        exit_time="2026-06-21T10:06:00Z",
        close_reason="TIER_2_TAKE_PROFIT",
        exit_spread_bps=1.4,
    )
    feedback = build_strategy_hedge_exit_feedback(close_event=close_event, outcome_label=outcome)

    for row in (position.to_payload(generated_utc=DECISION_TIME), close_event, outcome, feedback):
        assert row["confidence_raw"] == pytest.approx(0.57)
        assert row["confidence_calibrated"] == pytest.approx(0.63)
        assert row["expected_move_bps"] == pytest.approx(31.0)
        assert row["expected_move_after_cost_bps"] == pytest.approx(24.0)
        assert row["selected_action_probability"] == pytest.approx(0.66)
        assert row["prediction_score_missing_reason"] is None


def test_missing_entry_prediction_scores_are_not_fabricated() -> None:
    fill = {
        "fill_id": "fill_1",
        "symbol": "BTCUSDT",
        "side": "long",
        "quantity": 1.0,
        "entry_price": 100.0,
        "fill_price": 100.0,
        "fill_price_utc": DECISION_TIME,
        "generated_utc": DECISION_TIME,
        "prediction_id": "pred_1",
        "signal_id": "sig_1",
        "decision_id": "decision_1",
        "feature_snapshot_id": "feat_1",
        "mtf_snapshot_id": "mtf_1",
        "feature_cutoff": FEATURE_CUTOFF,
        "decision_time": DECISION_TIME,
        "available_at": AVAILABLE_AT,
        "selected_action": "long",
        "model_version": "unit_model_v1",
        "checkpoint_id": "ckpt_1",
        "source_hashes": _source_hashes(),
        "timeframe": "1m",
        **_audit_fields(),
    }
    position = position_from_fill(fill, fill_id="fill_1", side="long", quantity=1.0, price=100.0)
    close_event, outcome = build_close_event(
        position=position,
        close_quantity=1.0,
        exit_price=103.0,
        exit_time="2026-06-21T10:06:00Z",
        close_reason="TIER_2_TAKE_PROFIT",
        exit_spread_bps=1.4,
    )
    feedback = build_strategy_hedge_exit_feedback(close_event=close_event, outcome_label=outcome)

    assert feedback["confidence_calibrated"] is None
    assert feedback["expected_move_after_cost_bps"] is None
    assert feedback["prediction_score_missing_reason"] == (
        "MISSING_ENTRY_PREDICTION_SCORE_FIELDS:"
        "confidence_calibrated,expected_move_after_cost_bps"
    )


def test_feedback_batch_uses_realized_after_cost_reward() -> None:
    _, result = _train_one()
    assert result.metrics["realized_reward_source"] == "realized_after_cost_reward_minus_value_baseline"
    assert result.metrics["outcome_supervised_update_used"] is True


def test_snapshot_backed_feedback_uses_entry_feature_snapshot() -> None:
    close_event, outcome_label = _close_and_outcome(action="short")
    prediction = _trust_prediction(selected_action="short")
    row = paper_loop._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[close_event],
        outcome_labels=[outcome_label],
        predictions_by_id={"pred_1": prediction},
    )[0]
    assert row["trainer_consumable"] is True
    snapshot = _feature_snapshot()
    features = dict(snapshot["features"])
    features.pop("best_bid_size")
    features.pop("estimated_price_impact_bps")
    snapshot["features"] = features
    loader = V2HybridTrainerDataLoader(
        io=V2OnlyJsonIO(
            client=_FakeRedis(
                {
                    "v2:trainer:feedback:outcomes": [row],
                    "v2:features:snapshot:feat_1": snapshot,
                }
            )
        )
    )

    examples = loader.load_training_examples(symbols=[], timeframes=[], limit=4, trusted_only=True)

    assert len(examples) == 1
    trust_row = examples[0].trust_row or {}
    assert trust_row["learning_mode"] == "outcome_supervised"
    assert trust_row["snapshot_backed_closed_trade_feedback"] is True
    assert trust_row["realized_reward_source"] == "realized_net_pnl_bps_after_cost"
    assert trust_row["uses_expected_move_as_realized_reward"] is False
    assert trust_row["candle_closed_confirmed"] is True
    assert trust_row["candle_close_time"] == FEATURE_CUTOFF
    # Decision-time lineage is canonical: the snapshot's explicit
    # missing_feature_flags say nothing was missing, so the two dropped
    # features are tensor-reconstruction gaps, preserved separately.
    assert trust_row["missing_feature_names"] == []
    assert trust_row["missing_feature_lineage_source"] == "feature_snapshot_decision_time_flags"
    assert {"best_bid_size", "estimated_price_impact_bps"}.issubset(
        set(trust_row["tensor_unreconstructed_feature_names"])
    )
    assert trust_row["tensor_missing_mask_preserved"] is True
    assert examples[0].tensor.feature_snapshot_id == "feat_1"
    model = V2HybridPolicyModel(input_dim=len(examples[0].tensor.model_vector))
    accepted, summary = V2HybridPPOTrainer(model=model)._filter_trusted_training_rows(examples)  # noqa: SLF001
    assert accepted == examples
    assert summary["training_trusted_rows"] == 1


def test_snapshot_with_explicit_missing_critical_source_still_blocks_training() -> None:
    close_event, outcome_label = _close_and_outcome(action="short")
    prediction = _trust_prediction(selected_action="short")
    row = paper_loop._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[close_event],
        outcome_labels=[outcome_label],
        predictions_by_id={"pred_1": prediction},
    )[0]
    snapshot = _feature_snapshot()
    snapshot["missing_feature_flags"] = ["ohlcv_window", "orderbook"]
    snapshot["missing_feature_count"] = 2
    loader = V2HybridTrainerDataLoader(
        io=V2OnlyJsonIO(
            client=_FakeRedis(
                {
                    "v2:trainer:feedback:outcomes": [row],
                    "v2:features:snapshot:feat_1": snapshot,
                }
            )
        )
    )

    trusted_examples = loader.load_training_examples(symbols=[], timeframes=[], limit=4, trusted_only=True)
    assert trusted_examples == [] or all(
        (example.trust_row or {}).get("trainer_consumable") is not True for example in trusted_examples
    )
    if trusted_examples:
        model = V2HybridPolicyModel(input_dim=len(trusted_examples[0].tensor.model_vector))
        accepted, summary = V2HybridPPOTrainer(model=model)._filter_trusted_training_rows(trusted_examples)  # noqa: SLF001
        assert accepted == []
        assert summary["training_trusted_rows"] == 0


def test_embedded_entry_feature_snapshot_trains_when_archive_snapshot_missing() -> None:
    close_event, outcome_label = _close_and_outcome(action="long")
    prediction = _trust_prediction(selected_action="long")
    row = paper_loop._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[close_event],
        outcome_labels=[outcome_label],
        predictions_by_id={"pred_1": prediction},
    )[0]
    row["entry_feature_snapshot"] = _feature_snapshot()
    loader = V2HybridTrainerDataLoader(
        io=V2OnlyJsonIO(
            client=_FakeRedis(
                {
                    "v2:trainer:feedback:outcomes": [row],
                }
            )
        )
    )

    examples = loader.load_training_examples(symbols=[], timeframes=[], limit=4, trusted_only=True)

    assert len(examples) == 1
    trust_row = examples[0].trust_row or {}
    assert trust_row["source_lineage"]["feature_snapshot_key"] == "trainer_feedback.entry_feature_snapshot"
    assert examples[0].tensor.feature_snapshot_id == "feat_1"


def test_embedded_entry_prediction_snapshot_reconstructs_without_archive_prediction() -> None:
    close_event, outcome_label = _close_and_outcome(action="long")
    entry_prediction_snapshot = _trust_prediction(selected_action="long")
    entry_prediction_snapshot.update(
        {
            "confidence_calibrated": 0.71,
            "expected_move_after_cost_bps": 18.0,
            "entry_prediction_snapshot_source": "ENTRY_DECISION_TIME_PAYLOAD",
        }
    )
    close_event["entry_prediction_snapshot"] = entry_prediction_snapshot
    close_event["entry_feature_snapshot"] = _feature_snapshot()
    outcome_label["entry_prediction_snapshot"] = dict(entry_prediction_snapshot)
    outcome_label["entry_feature_snapshot"] = _feature_snapshot()

    row = paper_loop._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[close_event],
        outcome_labels=[outcome_label],
        predictions_by_id={},
        feature_snapshots_by_id={},
    )[0]

    assert row["trust_reconstructed"] is True
    assert row["trust_source_ids"]["entry_prediction_id"] == "pred_1"
    assert row["trust_source_ids"]["checkpoint_id"] == "ckpt_1"
    assert row["entry_prediction_snapshot"]["prediction_id"] == "pred_1"
    assert row["entry_feature_snapshot"]["feature_snapshot_id"] == "feat_1"
    assert row["checkpoint_id"] == "ckpt_1"
    assert row["confidence_calibrated"] == pytest.approx(0.71)
    assert row["expected_move_after_cost_bps"] == pytest.approx(18.0)
    assert row["trust_reconstruction_rejection_reasons"] == []


def test_mismatched_embedded_entry_feature_snapshot_is_not_trainable() -> None:
    close_event, outcome_label = _close_and_outcome(action="long")
    prediction = _trust_prediction(selected_action="long")
    row = paper_loop._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[close_event],
        outcome_labels=[outcome_label],
        predictions_by_id={"pred_1": prediction},
    )[0]
    row["entry_feature_snapshot"] = _feature_snapshot("other_feat")
    loader = V2HybridTrainerDataLoader(
        io=V2OnlyJsonIO(
            client=_FakeRedis(
                {
                    "v2:trainer:feedback:outcomes": [row],
                }
            )
        )
    )

    examples = loader.load_training_examples(symbols=[], timeframes=[], limit=4, trusted_only=True)

    assert examples == []


def test_verified_prediction_without_feature_snapshot_deref_is_rejected() -> None:
    close_event, outcome_label = _close_and_outcome(action="long")
    prediction = _trust_prediction(selected_action="long")

    row = paper_loop._build_trainer_feedback_rows(  # noqa: SLF001
        close_events=[close_event],
        outcome_labels=[outcome_label],
        predictions_by_id={"pred_1": prediction},
        feature_snapshots_by_id={},
    )[0]

    assert row["trainer_consumable"] is False
    assert "TRUST_RECONSTRUCTION:ENTRY_FEATURE_SNAPSHOT_NOT_FOUND" in row["trust_envelope_rejection_reasons"]


def test_expected_move_is_not_used_as_realized_reward() -> None:
    _, result = _train_one()
    assert result.metrics["uses_expected_move_as_realized_reward"] is False


def test_ppo_rejects_rows_without_on_policy_fields() -> None:
    _, result = _train_one()
    assert result.metrics["ppo_rows_rejected_missing_on_policy_fields"] == 1
    assert result.metrics["ppo_objective_used"] is False
    assert result.metrics["learning_update_lane"] == "outcome_supervised"


def test_ppo_mixed_lane_keeps_outcome_rows_in_training_batch() -> None:
    ppo_row = _training_example(
        1,
        trust_overrides={
            "old_log_prob": -0.7,
            "old_value": 0.05,
            "reward": 0.42,
            "done": True,
            "rollout_id": "rollout_1",
            "trajectory_index": 0,
        },
    )
    replay_row = _training_example(2)
    second_replay_row = _training_example(3)
    model = V2HybridPolicyModel(input_dim=len(ppo_row.tensor.model_vector), seed=7)
    trainer = V2HybridPPOTrainer(model=model)

    result = trainer.train(
        [replay_row, second_replay_row, ppo_row],
        steps=1,
        batch_size=8,
        validation_fraction=0.34,
    )

    assert result.metrics["learning_update_lane"] == "ppo_mixed_outcome_supervised"
    assert result.metrics["ppo_objective_used"] is True
    assert result.metrics["outcome_supervised_update_used"] is True
    assert result.metrics["mixed_ppo_outcome_batch_active"] is True
    assert result.metrics["ppo_rows_consumed"] == 1
    assert result.metrics["ppo_rows_rejected_missing_on_policy_fields"] == 0
    assert result.metrics["ppo_rows_missing_on_policy_fields"] == 2
    assert result.metrics["selected_examples"] == 3
    assert result.metrics["actual_batch_size"] == 3
    assert result.train_rows == 2


def test_ppo_equal_nonzero_advantages_do_not_skip_mixed_training() -> None:
    ppo_rows = [
        _training_example(
            1,
            trust_overrides={
                "old_log_prob": -0.7,
                "old_value": 0.05,
                "reward": 2.3058026,
                "done": True,
                "rollout_id": "rollout_equal",
                "trajectory_index": 0,
            },
        ),
        _training_example(
            2,
            trust_overrides={
                "old_log_prob": -0.6,
                "old_value": 0.15,
                "reward": 2.4058026,
                "done": True,
                "rollout_id": "rollout_equal",
                "trajectory_index": 1,
            },
        ),
    ]
    replay_row = _training_example(3)
    model = V2HybridPolicyModel(input_dim=len(ppo_rows[0].tensor.model_vector), seed=7)
    trainer = V2HybridPPOTrainer(model=model)

    result = trainer.train(
        [*ppo_rows, replay_row],
        steps=1,
        batch_size=8,
        validation_fraction=0.0,
    )

    assert result.metrics["learning_update_lane"] == "ppo_mixed_outcome_supervised"
    assert result.metrics["ppo_objective_used"] is True
    assert result.metrics["ppo_rows_consumed"] == 2
    assert result.metrics["ppo_advantage_std"] == pytest.approx(0.0)
    assert result.metrics["ppo_advantage_mean"] == pytest.approx(2.2558026)
    assert result.metrics["advantage_anomaly_steps"] == 0
    assert result.metrics["non_finite_loss_steps"] == 0
    assert result.metrics["optimizer_steps_this_cycle"] == 1


def test_outcome_supervised_lane_updates_weights() -> None:
    _, result = _train_one()
    assert result.metrics["learning_update_lane"] == "outcome_supervised"
    assert result.metrics["optimizer_steps_this_cycle"] > 0
    assert result.metrics["parameter_hash_before"] != result.metrics["parameter_hash_after"]


def test_parameter_hash_changes_after_training() -> None:
    _, result = _train_one()
    assert result.metrics["parameter_hash_before"] != result.metrics["parameter_hash_after"]
    assert result.metrics["weight_delta_norm"] > 0.0


def test_checkpoint_contains_updated_weight_blob(tmp_path: Path) -> None:
    model, result = _train_one()
    manager = V2HybridCheckpointManager(tmp_path / ".local_models/v2_native_rl_masa_ppo")
    manifest = manager.write_checkpoint(
        model=model,
        input_dim=model.input_dim,
        device=result.device,
        cuda_active=result.cuda_active,
        write_weight_blob=True,
    )
    assert manifest.weight_blob_written is True
    assert manifest.weight_file_path is not None
    assert Path(manifest.weight_file_path).exists()


def test_checkpoint_loads_when_manifest_weight_path_is_stale(tmp_path: Path) -> None:
    # A manifest may store a repo-root-relative weight_file_path; a tool invoked
    # from a different CWD would then fail to resolve it. The blob always lives in
    # model_dir/{checkpoint_id}.weights.npz, so load must fall back to that and
    # not wrongly report NO_COMPATIBLE_WEIGHT_BLOB_MANIFEST.
    model, result = _train_one()
    model_dir = tmp_path / ".local_models/v2_native_rl_masa_ppo"
    manager = V2HybridCheckpointManager(model_dir)
    manifest = manager.write_checkpoint(
        model=model,
        input_dim=model.input_dim,
        device=result.device,
        cuda_active=result.cuda_active,
        write_weight_blob=True,
    )
    # Corrupt the stored weight_file_path to a bogus relative path (blob stays put).
    manifest_json = model_dir / f"{manifest.checkpoint_id}.json"
    data = json.loads(manifest_json.read_text())
    data["weight_file_path"] = "does/not/exist/from/this/cwd.weights.npz"
    manifest_json.write_text(json.dumps(data))

    fresh = model_module.V2HybridPolicyModel(input_dim=model.input_dim)
    loaded = V2HybridCheckpointManager(model_dir).load_latest_weights(fresh)
    assert loaded["latest_checkpoint_loadable"] is True
    assert loaded["model_state_restored"] is True


def test_checkpoint_writers_do_not_share_deterministic_tmp_paths(tmp_path: Path) -> None:
    model, result = _train_one()
    manager = V2HybridCheckpointManager(tmp_path / ".local_models/v2_native_rl_masa_ppo")
    manifest = manager.write_checkpoint(
        model=model,
        input_dim=model.input_dim,
        device=result.device,
        cuda_active=result.cuda_active,
        write_weight_blob=True,
    )
    weight_path = Path(manifest.weight_file_path or "")

    assert "NamedTemporaryFile" in inspect.getsource(checkpoint_module._atomic_write_text)
    assert "NamedTemporaryFile" in inspect.getsource(model_module.V2HybridPolicyModel.save_weight_blob)
    assert not weight_path.with_suffix(weight_path.suffix + ".tmp").exists()
    assert not list(weight_path.parent.glob(f".{weight_path.name}.*.tmp"))


def test_checkpoint_reload_reproduces_predictions(tmp_path: Path) -> None:
    model, result = _train_one()
    vector = list(_training_example().tensor.model_vector)
    expected = model.forward(vector)
    manager = V2HybridCheckpointManager(tmp_path / ".local_models/v2_native_rl_masa_ppo")
    manager.write_checkpoint(
        model=model,
        input_dim=model.input_dim,
        device=result.device,
        cuda_active=result.cuda_active,
        write_weight_blob=True,
    )
    restored = V2HybridPolicyModel(input_dim=model.input_dim, seed=7)
    load_status = manager.load_latest_weights(restored)
    actual = restored.forward(vector)
    assert load_status["model_state_restored"] is True
    assert actual.action_probabilities == pytest.approx(expected.action_probabilities)
    assert actual.expected_move_bps == pytest.approx(expected.expected_move_bps)


def test_metadata_only_checkpoint_does_not_block_latest_weight_blob(tmp_path: Path) -> None:
    model, result = _train_one()
    vector = list(_training_example().tensor.model_vector)
    expected = model.forward(vector)
    manager = V2HybridCheckpointManager(tmp_path / ".local_models/v2_native_rl_masa_ppo")
    valid_manifest = manager.write_checkpoint(
        model=model,
        input_dim=model.input_dim,
        device=result.device,
        cuda_active=result.cuda_active,
        write_weight_blob=True,
    )
    metadata_only = manager.write_manifest(
        model_id="metadata_only_newer_v2_model_123456789012345678901234",
        input_dim=model.input_dim,
        device=result.device,
        cuda_active=result.cuda_active,
        weight_blob_written=False,
    )

    restored = V2HybridPolicyModel(input_dim=model.input_dim, seed=7)
    load_status = manager.load_latest_weights(restored)
    actual = restored.forward(vector)

    assert metadata_only.checkpoint_id != valid_manifest.checkpoint_id
    assert load_status["checkpoint_id"] == valid_manifest.checkpoint_id
    assert load_status["latest_metadata_checkpoint_id"] == metadata_only.checkpoint_id
    assert load_status["metadata_only_manifest_ignored_for_weight_load"] is True
    assert load_status["model_state_restored"] is True
    assert actual.action_probabilities == pytest.approx(expected.action_probabilities)
