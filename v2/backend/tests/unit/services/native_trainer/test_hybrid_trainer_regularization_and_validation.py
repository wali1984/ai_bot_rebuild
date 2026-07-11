"""Regression fixtures for the trainer generalization/regularization repair.

These lock in the three edge-recovery changes:
  1. the held-out validation split is actually EVALUATED out-of-sample (it was
     previously carved out and discarded), giving a real generalization signal;
  2. regularization/exploration knobs (entropy coefficient, supervised entropy
     bonus, weight decay, dropout) are env-controlled so the operator can tune or
     instantly revert without a redeploy;
  3. those knob values are surfaced in the training metrics.
"""
from __future__ import annotations

import pytest

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import V2HybridPolicyModel
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import V2HybridPPOTrainer
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import FeatureTensorRecord
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import TrainingExample
from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION


def _tensor(index: int, value: float | None = None) -> FeatureTensorRecord:
    return FeatureTensorRecord(
        tensor_id=f"tensor_{index}",
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id=f"feat_{index}",
        values=(float(index) if value is None else float(value),),
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


def _example(index: int, action_index: int, *, expected: float | None = None) -> TrainingExample:
    expected_bps = (
        float(expected)
        if expected is not None
        else 12.0 if action_index == 1 else (-12.0 if action_index == 2 else 0.0)
    )
    selected_action = ("hold", "long", "short")[action_index]
    directional_outcome = "UP" if expected_bps > 0 else "DOWN" if expected_bps < 0 else "FLAT"
    trade_outcome = "WIN" if action_index in (1, 2) and abs(expected_bps) > 0 else "BREAKEVEN"
    return TrainingExample(
        symbol="BTCUSDT",
        timeframe="1m",
        tensor=_tensor(index),
        label_action_index=action_index,
        label_expected_move_after_cost_bps=expected_bps,
        payload_keys=("unit",),
        row_classification="TRAINABLE",
        trust_row={
            "accepted_for_training": True,
            "reject_reasons": [],
            "trust_schema_version": TRUST_SCHEMA_VERSION,
            "mtf_snapshot_id": f"mtf_{index}",
            "mtf_snapshot_valid": True,
            "replay_snapshot_id": f"replay_{index}",
            "candle_closed_confirmed": True,
            "closed_candle": True,
            "feature_freshness_state": "CURRENT",
            "freshness_state": "CURRENT",
            "latency_ms": 100,
            "candle_open_time": "2026-06-18T23:59:00Z",
            "candle_close_time": "2026-06-19T00:00:00Z",
            "source_event_time": "2026-06-19T00:00:00Z",
            "source_event_time_est": "2026-06-19T00:00:00Z",
            "source_received_time_est": "2026-06-19T00:00:00Z",
            "feature_cutoff": "2026-06-19T00:00:00Z",
            "decision_cutoff": "2026-06-19T00:00:00Z",
            "available_at": "2026-06-19T00:00:00Z",
            "source_available_time": "2026-06-19T00:00:00Z",
            "decision_time": "2026-06-19T00:01:00Z",
            "decision_time_est": "2026-06-19T00:01:00Z",
            "features": {"ret_pct": 0.0},
            "selected_action": selected_action,
            "model_version": "unit_model_v1",
            "checkpoint_id": "ckpt_unit",
            "source_hashes": {"feature_vector_hash": f"tensor_{index}"},
            "outcome_targets": {
                "realized_net_pnl_bps": expected_bps,
                "realized_net_pnl_usd": expected_bps / 10.0,
                "directional_outcome": directional_outcome,
                "trade_outcome": trade_outcome,
                "selected_action": selected_action,
                "action_was_profitable": trade_outcome == "WIN",
                "holding_period": 300,
                "fees": 0.01,
                "slippage": 0.01,
                "funding": 0.0,
                "MFE": max(0.0, abs(expected_bps)),
                "MAE": 0.0,
                "exit_reason": "unit",
            },
            "realized_after_cost_reward": expected_bps / 100.0,
            "value_baseline": 0.0,
            "advantage": expected_bps / 100.0,
            "advantage_source": "realized_after_cost_reward_minus_value_baseline",
            "uses_expected_move_as_realized_reward": False,
        },
    )


def _mixed_rows(n: int) -> list[TrainingExample]:
    rows: list[TrainingExample] = []
    for i in range(n):
        action = (1, 2, 0)[i % 3]
        rows.append(_example(i, action))
    return rows


# --------------------------------------------------------------------------- #
# regularization / exploration knobs are env-controlled and reversible
# --------------------------------------------------------------------------- #
def test_regularization_knobs_default_values(monkeypatch) -> None:
    for env in ("V2_TRAINER_ENTROPY_COEF", "V2_TRAINER_SUPERVISED_ENTROPY_BONUS", "V2_TRAINER_WEIGHT_DECAY"):
        monkeypatch.delenv(env, raising=False)
    model = V2HybridPolicyModel(input_dim=1)
    trainer = V2HybridPPOTrainer(model=model)
    assert trainer.entropy_coefficient == pytest.approx(0.01)
    assert trainer.supervised_entropy_bonus == pytest.approx(0.0)
    assert trainer.weight_decay == pytest.approx(0.02)


def test_regularization_knobs_env_controlled(monkeypatch) -> None:
    monkeypatch.setenv("V2_TRAINER_ENTROPY_COEF", "0.01")
    monkeypatch.setenv("V2_TRAINER_SUPERVISED_ENTROPY_BONUS", "0.0")
    monkeypatch.setenv("V2_TRAINER_WEIGHT_DECAY", "0.01")
    model = V2HybridPolicyModel(input_dim=1)
    trainer = V2HybridPPOTrainer(model=model)
    # env values restore the prior behaviour exactly (proves reversibility)
    assert trainer.entropy_coefficient == pytest.approx(0.01)
    assert trainer.supervised_entropy_bonus == pytest.approx(0.0)
    assert trainer.weight_decay == pytest.approx(0.01)


def test_regularization_knobs_explicit_param_overrides_env(monkeypatch) -> None:
    monkeypatch.setenv("V2_TRAINER_ENTROPY_COEF", "0.01")
    model = V2HybridPolicyModel(input_dim=1)
    trainer = V2HybridPPOTrainer(model=model, entropy_coefficient=0.07)
    assert trainer.entropy_coefficient == pytest.approx(0.07)


def test_dropout_default_and_env_controlled(monkeypatch) -> None:
    monkeypatch.delenv("V2_TRAINER_DROPOUT", raising=False)
    assert V2HybridPolicyModel(input_dim=1).dropout == pytest.approx(0.10)
    monkeypatch.setenv("V2_TRAINER_DROPOUT", "0.05")
    assert V2HybridPolicyModel(input_dim=1).dropout == pytest.approx(0.05)


# --------------------------------------------------------------------------- #
# the held-out validation split is actually evaluated out-of-sample
# --------------------------------------------------------------------------- #
def test_validation_split_is_evaluated_out_of_sample() -> None:
    rows = _mixed_rows(6)
    model = V2HybridPolicyModel(input_dim=len(rows[0].tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")
    result = V2HybridPPOTrainer(model=model).train(rows, steps=1, batch_size=6, validation_fraction=0.34)
    assert result.validation_rows >= 1
    assert result.metrics["validation_rows_evaluated"] >= 1
    val_loss = result.metrics["validation_supervised_loss"]
    assert isinstance(val_loss, float)
    assert val_loss == val_loss  # finite (not NaN)
    assert result.metrics["validation_supervised_loss_after"] == pytest.approx(val_loss)
    assert isinstance(result.metrics["validation_supervised_loss_before"], float)
    assert isinstance(result.metrics["validation_loss_delta"], float)
    assert isinstance(result.metrics["validation_improved"], bool)


def test_generalization_gap_and_knobs_reported_in_metrics() -> None:
    rows = _mixed_rows(6)
    model = V2HybridPolicyModel(input_dim=len(rows[0].tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")
    result = V2HybridPPOTrainer(model=model).train(rows, steps=1, batch_size=6, validation_fraction=0.34)
    m = result.metrics
    assert "train_val_generalization_gap" in m
    assert isinstance(m["train_val_generalization_gap"], float)
    assert m["entropy_coefficient"] == pytest.approx(0.01)
    assert m["weight_decay"] == pytest.approx(0.02)
    assert m["model_dropout"] == pytest.approx(0.10)


def test_no_validation_evaluation_when_single_row_batch() -> None:
    # With a single-row batch the loop carves out no validation split
    # (val_count == 0), so no out-of-sample loss is computed.
    rows = _mixed_rows(1)
    model = V2HybridPolicyModel(input_dim=len(rows[0].tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")
    result = V2HybridPPOTrainer(model=model).train(rows, steps=1, batch_size=1, validation_fraction=0.2)
    assert result.validation_rows == 0
    assert result.metrics["validation_rows_evaluated"] == 0
    assert result.metrics["validation_supervised_loss"] is None
