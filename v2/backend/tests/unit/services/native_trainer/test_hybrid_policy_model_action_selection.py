from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.confidence import (
    calibrate_confidence,
    softmax,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import V2HybridPolicyModel
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import FeatureTensorRecord


def test_cuda_memory_cap_uses_lower_of_12gb_or_75_percent() -> None:
    calls: list[tuple[float, int]] = []

    class _FakeCuda:
        @staticmethod
        def get_device_properties(_index: int) -> SimpleNamespace:
            return SimpleNamespace(total_memory=24 * 1024 * 1024 * 1024)

        @staticmethod
        def set_per_process_memory_fraction(fraction: float, index: int) -> None:
            calls.append((fraction, index))

    fake_torch = SimpleNamespace(cuda=_FakeCuda())

    V2HybridPolicyModel._apply_cuda_memory_cap(fake_torch)

    assert calls == [(0.5, 0)]


def test_expected_move_does_not_force_short_without_policy_agreement() -> None:
    probs, selected = V2HybridPolicyModel._expected_move_aligned_policy(
        (0.55, 0.30, 0.15, 0.0, 0.0, 0.0, 0.0),
        -60.0,
    )

    assert selected == 0
    assert probs[0] > probs[2]


def test_expected_move_selects_short_when_policy_head_agrees() -> None:
    probs, selected = V2HybridPolicyModel._expected_move_aligned_policy(
        (0.20, 0.10, 0.70, 0.0, 0.0, 0.0, 0.0),
        -60.0,
    )

    assert selected == 2
    assert probs[2] > probs[0]


def test_conflicting_long_policy_and_negative_expected_move_selects_hold() -> None:
    probs, selected = V2HybridPolicyModel._expected_move_aligned_policy(
        (0.10, 0.80, 0.10, 0.0, 0.0, 0.0, 0.0),
        -60.0,
    )

    assert selected == 0
    assert probs[0] > probs[2]


def test_softmax_and_calibration_neutralize_non_finite_values() -> None:
    probs = softmax((math.nan, math.inf, -math.inf))
    calibration = calibrate_confidence(
        raw_probability=math.nan,
        data_coverage_percent=math.inf,
        missing_feature_count=0,
        stale_feature_count=0,
        temperature=math.nan,
    )

    assert len(probs) == 3
    assert all(math.isfinite(value) for value in probs)
    assert math.isclose(sum(probs), 1.0)
    assert calibration["confidence_raw"] == 0.0
    assert 0.0 <= calibration["confidence_calibrated"] <= 1.0


def test_torch_forward_sanitizes_non_finite_head_outputs_to_neutral_prediction() -> None:
    tensor = FeatureTensorRecord(
        tensor_id="tensor_non_finite",
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id="feature_non_finite",
        values=(math.nan,),
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
    model = V2HybridPolicyModel(input_dim=len(tensor.model_vector))
    if not model.torch_available:
        pytest.skip("torch unavailable")

    torch = model.torch
    assert torch is not None and model.net is not None
    with torch.no_grad():
        for parameter in model.net.parameters():
            parameter.fill_(float("nan"))

    result = model.forward(tensor)

    assert result.selected_action == "hold"
    assert all(math.isfinite(value) for value in result.action_logits)
    assert all(math.isfinite(value) for value in result.action_probabilities)
    assert math.isfinite(result.expected_move_bps)
    assert result.expected_move_bps == 0.0
    assert math.isfinite(result.confidence_calibrated)
    assert math.isfinite(result.policy_value)
    assert math.isfinite(result.masa_signal)


def test_attention_encoder_is_off_by_default_and_env_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("V2_TRAINER_ATTENTION_ENCODER", raising=False)
    off = V2HybridPolicyModel(input_dim=1248)
    assert off.attention_encoder_enabled is False
    monkeypatch.setenv("V2_TRAINER_ATTENTION_ENCODER", "true")
    on = V2HybridPolicyModel(input_dim=1248)
    assert on.attention_encoder_enabled is True
    # Enabling the attention encoder changes the architecture identity so it starts
    # a fresh checkpoint lineage instead of loading incompatible weights.
    assert on.model_id != off.model_id


def test_attention_encoder_only_enables_when_input_splits_into_four_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("V2_TRAINER_ATTENTION_ENCODER", "true")
    # 1247 is not divisible by 4 -> attention must stay disabled (safe fallback).
    odd = V2HybridPolicyModel(input_dim=1247)
    assert odd.attention_encoder_enabled is False
    even = V2HybridPolicyModel(input_dim=1248)
    assert even.attention_encoder_enabled is True
