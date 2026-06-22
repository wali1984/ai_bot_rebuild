from __future__ import annotations

import math

import pytest

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import TrainingExample
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import V2HybridPolicyModel
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (
    EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT,
    V2HybridPPOTrainer,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import FeatureTensorRecord
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


def _example(index: int, action_index: int, *, value: float | None = None, expected: float | None = None) -> TrainingExample:
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
        tensor=_tensor(index, value=value),
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


def test_action_class_weights_upweight_scarce_long_without_forcing_ratio() -> None:
    rows = [_example(i, 2) for i in range(8)]
    rows.append(_example(100, 1))
    rows.append(_example(101, 0))

    weights = V2HybridPPOTrainer._python_action_class_weights(rows)  # noqa: SLF001
    metrics = V2HybridPPOTrainer._action_balance_metrics(rows)  # noqa: SLF001

    assert weights[1] > weights[2]
    assert weights[0] > 0.0
    assert metrics["target_label_distribution_directional"] == {
        "hold": 1,
        "long": 1,
        "short": 8,
    }
    assert metrics["long_label_present"] is True
    assert metrics["short_label_present"] is True
    assert metrics["hold_label_present"] is True


def test_policy_bias_nudge_upweights_scarce_present_labels_without_reinforcing_majority() -> None:
    rows = [_example(i, 2) for i in range(8)]
    rows.append(_example(100, 1))
    rows.append(_example(101, 0))

    nudge = V2HybridPPOTrainer._python_action_bias_nudge(rows)  # noqa: SLF001

    assert nudge[1] > 0.0
    assert nudge[0] > 0.0
    assert nudge[2] < 0.0
    assert nudge[3:] == [0.0, 0.0, 0.0, 0.0]


def test_policy_bias_nudge_is_neutral_for_single_class_short_batch() -> None:
    rows = [_example(i, 2) for i in range(8)]

    nudge = V2HybridPPOTrainer._python_action_bias_nudge(rows)  # noqa: SLF001

    assert nudge == [0.0 for _ in nudge]


def test_policy_action_supervision_neutralizes_single_direction_short_batch_to_hold() -> None:
    rows = [_example(i, 2, expected=-12.0) for i in range(8)]

    labels, metrics = V2HybridPPOTrainer._python_policy_action_supervision_labels(rows)  # noqa: SLF001

    assert labels == [0 for _ in rows]
    assert metrics["policy_action_supervision_strategy"] == "neutralize_single_directional_action_labels_to_hold"
    assert metrics["policy_action_single_direction_guard_active"] is True
    assert metrics["policy_action_single_direction_guard_side"] == "short"
    assert metrics["policy_action_labels_neutralized_count"] == len(rows)
    assert metrics["policy_action_supervision_target_distribution_by_action"]["hold"] == len(rows)
    assert metrics["policy_action_supervision_target_distribution_by_action"]["short"] == 0


def test_policy_action_supervision_preserves_balanced_directional_batch() -> None:
    rows = [_example(1, 2, expected=-12.0), _example(2, 1, expected=12.0)]

    labels, metrics = V2HybridPPOTrainer._python_policy_action_supervision_labels(rows)  # noqa: SLF001

    assert labels == [2, 1]
    assert metrics["policy_action_supervision_strategy"] == "raw_action_labels"
    assert metrics["policy_action_single_direction_guard_active"] is False
    assert metrics["policy_action_labels_neutralized_count"] == 0


def test_expected_move_supervision_neutralizes_single_direction_short_batch() -> None:
    rows = [_example(i, 2, expected=-12.0) for i in range(8)]

    labels, metrics = V2HybridPPOTrainer._python_expected_move_supervision_labels(rows)  # noqa: SLF001

    assert labels == [0.0 for _ in rows]
    assert metrics["expected_move_supervision_strategy"] == "neutralize_single_directional_expected_move_labels"
    assert metrics["expected_move_single_direction_guard_active"] is True
    assert metrics["expected_move_single_direction_guard_side"] == "short"
    assert metrics["expected_move_labels_neutralized_count"] == len(rows)
    assert metrics["expected_move_raw_target_mean_bps"] == -12.0
    assert metrics["expected_move_training_target_mean_bps"] == 0.0


def test_expected_move_supervision_preserves_balanced_directional_batch() -> None:
    rows = [_example(1, 2, expected=-12.0), _example(2, 1, expected=12.0)]

    labels, metrics = V2HybridPPOTrainer._python_expected_move_supervision_labels(rows)  # noqa: SLF001

    assert labels == [-12.0, 12.0]
    assert metrics["expected_move_supervision_strategy"] == "raw_expected_move_labels"
    assert metrics["expected_move_single_direction_guard_active"] is False
    assert metrics["expected_move_labels_neutralized_count"] == 0


def test_torch_training_sanitizes_non_finite_runtime_tensors_and_labels() -> None:
    rows = [
        _example(1, 2, value=math.nan, expected=math.inf),
        _example(2, 2, value=math.inf, expected=999.0),
        _example(3, 0, value=-math.inf, expected=0.0),
    ]
    model = V2HybridPolicyModel(input_dim=len(rows[0].tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")

    result = V2HybridPPOTrainer(model=model).train(rows, steps=1, batch_size=3, validation_fraction=0.0)

    assert result.training_steps == 1
    assert result.metrics["non_finite_feature_count"] >= 1
    assert result.metrics["non_finite_expected_label_count"] >= 1
    assert result.metrics["clipped_expected_label_count"] >= 1
    assert result.metrics["non_finite_loss_steps"] == 0


def test_torch_training_sanitizes_non_finite_model_parameters() -> None:
    rows = [
        _example(1, 1, expected=8.0),
        _example(2, 2, expected=-8.0),
        _example(3, 0, expected=0.0),
    ]
    model = V2HybridPolicyModel(input_dim=len(rows[0].tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")

    torch = model.torch
    assert torch is not None and model.net is not None
    with torch.no_grad():
        first_parameter = next(model.net.parameters())
        flat = first_parameter.reshape(-1)
        flat[0] = float("nan")
        if flat.numel() > 1:
            flat[1] = float("inf")

    result = V2HybridPPOTrainer(model=model).train(rows, steps=1, batch_size=3, validation_fraction=0.0)

    assert math.isfinite(result.loss_before)
    assert math.isfinite(result.loss_after)
    assert result.metrics["parameter_finite_guard_active"] is True
    assert result.metrics["non_finite_parameter_value_count_sanitized"] >= 1
    assert result.metrics["non_finite_parameter_sanitization_events"] >= 1
    for parameter in model.net.parameters():
        assert bool(torch.isfinite(parameter).all().detach().cpu().item())


def test_torch_training_neutralizes_single_direction_expected_move_targets() -> None:
    rows = [_example(i, 2, expected=-12.0) for i in range(4)]
    model = V2HybridPolicyModel(input_dim=len(rows[0].tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")

    result = V2HybridPPOTrainer(model=model).train(rows, steps=1, batch_size=4, validation_fraction=0.0)

    assert result.metrics["policy_action_supervision_strategy"] == "neutralize_single_directional_action_labels_to_hold"
    assert result.metrics["policy_action_single_direction_guard_active"] is True
    assert result.metrics["policy_action_single_direction_guard_side"] == "short"
    assert result.metrics["policy_action_labels_neutralized_count"] == result.train_rows
    assert result.metrics["policy_action_supervision_target_distribution_by_action"]["hold"] == result.train_rows
    assert result.metrics["policy_action_supervision_target_distribution_by_action"]["short"] == 0
    assert result.metrics["expected_move_supervision_strategy"] == "neutralize_single_directional_expected_move_labels"
    assert result.metrics["expected_move_single_direction_guard_active"] is True
    assert result.metrics["expected_move_single_direction_guard_side"] == "short"
    assert result.metrics["expected_move_labels_neutralized_count"] == result.train_rows
    assert result.metrics["expected_move_raw_target_mean_bps"] == -12.0
    assert result.metrics["expected_move_training_target_mean_bps"] == 0.0
    assert result.metrics["expected_move_head_saturation_recovery_applied"] is False
    assert result.metrics["expected_move_head_saturation_recovery_reason"] == "mixed_long_short_target_evidence_missing"


def test_torch_training_recovers_runaway_expected_move_bias_with_mixed_directional_targets() -> None:
    rows = [
        _example(1, 1, expected=12.0),
        _example(2, 2, expected=-12.0),
        _example(3, 0, expected=0.0),
    ]
    model = V2HybridPolicyModel(input_dim=len(rows[0].tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")

    torch = model.torch
    assert torch is not None and model.net is not None
    with torch.no_grad():
        model.net.expected_move_head.weight.zero_()
        model.net.expected_move_head.bias.fill_(-57.0)

    result = V2HybridPPOTrainer(model=model).train(rows, steps=1, batch_size=3, validation_fraction=0.0)

    metrics = result.metrics
    assert metrics["expected_move_head_saturation_recovery_applied"] is True
    assert metrics["expected_move_head_saturation_recovery_reason"] == (
        "mixed_directional_targets_recentered_runaway_expected_move_bias"
    )
    assert metrics["expected_move_head_target_long_count"] == 1
    assert metrics["expected_move_head_target_short_count"] == 1
    assert metrics["expected_move_head_bias_before_recovery"] < -EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT
    assert abs(metrics["expected_move_head_bias_after_recovery"]) <= EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT
    assert metrics["expected_move_head_batch_output_mean_bps_before_recovery"] <= -118.0
    assert abs(metrics["expected_move_head_batch_output_mean_bps_after_recovery"]) < 1.0
    assert abs(float(model.net.expected_move_head.bias.detach().cpu().item())) <= EXPECTED_MOVE_HEAD_BIAS_ABS_LIMIT


def test_torch_training_recenters_expected_move_head_when_output_mismatches_mixed_targets() -> None:
    rows = [
        _example(1, 1, expected=12.0),
        _example(2, 2, expected=-12.0),
        _example(3, 0, expected=0.0),
    ]
    model = V2HybridPolicyModel(input_dim=len(rows[0].tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")

    torch = model.torch
    assert torch is not None and model.net is not None
    with torch.no_grad():
        model.net.expected_move_head.weight.zero_()
        model.net.expected_move_head.bias.fill_(1.5)

    result = V2HybridPPOTrainer(model=model).train(rows, steps=1, batch_size=3, validation_fraction=0.0)

    metrics = result.metrics
    assert metrics["expected_move_head_saturation_recovery_applied"] is True
    assert "target_mismatch" in metrics["expected_move_head_saturation_recovery_causes"]
    assert abs(metrics["expected_move_head_batch_output_mean_bps_after_recovery"]) < 1.0
    assert abs(metrics["expected_move_head_batch_target_delta_bps_after_recovery"]) < 1.0


def test_checkpoint_load_rejects_non_finite_torch_tensors(tmp_path) -> None:
    np = pytest.importorskip("numpy")
    model = V2HybridPolicyModel(input_dim=1)
    if not model.torch_available:
        pytest.skip("torch unavailable")
    payload = {
        "__format_version": np.array(["v2_hybrid_policy_npz_v1"]),
        "__input_dim": np.array([model.input_dim], dtype=np.int64),
        "__seed": np.array([model.seed], dtype=np.int64),
        "__torch_available": np.array([1], dtype=np.int64),
    }
    first_tensor = True
    for name, tensor in model.net.state_dict().items():
        array = tensor.detach().cpu().numpy()
        if first_tensor:
            array = array.copy()
            array.reshape(-1)[0] = np.nan
            first_tensor = False
        payload[f"torch::{name}"] = array
    path = tmp_path / "bad.weights.npz"
    np.savez_compressed(path, **payload)

    with pytest.raises(ValueError, match="non_finite_tensor_in_checkpoint"):
        model.load_weight_blob(path)
