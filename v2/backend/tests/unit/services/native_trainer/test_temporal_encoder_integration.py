"""WI-1 Step 4: temporal GRU encoder integration into V2HybridPolicyModel.

Guardrails: OFF by default (no GRU, byte-identical single-frame path), arch
identity forks when ON so temporal checkpoints never mix with single-frame ones,
and the net accepts either a 2D single frame or a 3D no-lookahead window.
"""
from __future__ import annotations

import pytest

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)

torch = pytest.importorskip("torch")


def _small_env(monkeypatch):
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "128")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "2")


def test_temporal_off_by_default_no_gru(monkeypatch) -> None:
    _small_env(monkeypatch)
    monkeypatch.delenv("V2_TRAINER_TEMPORAL_ENCODER", raising=False)
    m = V2HybridPolicyModel(input_dim=1248)
    assert m.temporal_encoder_enabled is False
    if m.torch_available:
        assert not hasattr(m.net, "temporal_gru")
        out = m.net(torch.randn(3, 1248, device=m.device))
        assert tuple(out["logits"].shape) == (3, 7)


def test_temporal_on_builds_gru_and_forks_arch(monkeypatch) -> None:
    _small_env(monkeypatch)
    monkeypatch.delenv("V2_TRAINER_TEMPORAL_ENCODER", raising=False)
    off = V2HybridPolicyModel(input_dim=1248)
    monkeypatch.setenv("V2_TRAINER_TEMPORAL_ENCODER", "gru")
    monkeypatch.setenv("V2_TRAINER_TEMPORAL_HIDDEN", "64")
    on = V2HybridPolicyModel(input_dim=1248)
    assert on.temporal_encoder_enabled is True
    # Arch identity must fork so temporal weights never load into a single-frame model.
    assert on.model_id != off.model_id
    if on.torch_available:
        assert hasattr(on.net, "temporal_gru")
        # 3D no-lookahead window (B, T, F) forward.
        out3d = on.net(torch.randn(2, 16, 1248, device=on.device))
        assert tuple(out3d["logits"].shape) == (2, 7)
        # 2D single frame still accepted (graceful).
        out2d = on.net(torch.randn(2, 1248, device=on.device))
        assert tuple(out2d["logits"].shape) == (2, 7)


def test_temporal_off_single_frame_path_is_deterministic(monkeypatch) -> None:
    # Same seed + off => identical 2D output (byte-path unchanged by the temporal
    # addition, which only activates on 3D input with the flag on).
    _small_env(monkeypatch)
    monkeypatch.delenv("V2_TRAINER_TEMPORAL_ENCODER", raising=False)
    m1 = V2HybridPolicyModel(input_dim=1248)
    m2 = V2HybridPolicyModel(input_dim=1248)
    if not (m1.torch_available and m2.torch_available):
        pytest.skip("torch unavailable")
    m1.net.eval()  # eval() disables dropout so same-seed init -> identical output
    m2.net.eval()
    x = torch.randn(4, 1248)
    with torch.no_grad():
        o1 = m1.net(x.to(m1.device))["logits"].detach().cpu()
        o2 = m2.net(x.to(m2.device))["logits"].detach().cpu()
    assert torch.allclose(o1, o2, atol=1e-6)
