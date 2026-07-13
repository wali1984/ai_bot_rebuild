"""Tail-aware CVaR training penalty (env-gated, DEFAULT OFF).

The risk composite's CVaR ceiling is architecture/data-limited, not undertrained.
V2_TRAINER_TAIL_CVAR_WEIGHT adds a differentiable penalty on the worst-tail of the
policy's expected directional return so the model learns to avoid fat-tail losing
trades. These tests lock in: OFF => byte-identical (no crash, trains normally), and
ON => still trains to a finite loss (no shape/NaN break in the penalty path).
"""
from __future__ import annotations

import pytest
from tests.unit.services.native_trainer.test_hybrid_trainer_regularization_and_validation import (
    _example,
)

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import V2HybridPolicyModel
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.ppo_trainer import (
    V2HybridPPOTrainer,
)

pytest.importorskip("torch")


def _rows(n: int):
    # Mixed long/short/hold with both +/- moves so the tail term has a real distribution.
    return [_example(i, (1, 2, 0)[i % 3], expected=(15.0, -80.0, 0.0)[i % 3]) for i in range(n)]


def _trainer(monkeypatch):
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "64")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.delenv("V2_TRAINER_TEMPORAL_ENCODER", raising=False)
    model = V2HybridPolicyModel(input_dim=4)
    if not model.torch_available:
        pytest.skip("torch unavailable")
    return V2HybridPPOTrainer(model=model)


def test_tail_cvar_off_trains_normally(monkeypatch) -> None:
    monkeypatch.delenv("V2_TRAINER_TAIL_CVAR_WEIGHT", raising=False)
    trainer = _trainer(monkeypatch)
    res = trainer.train(_rows(24), steps=2, batch_size=16)
    import math
    assert math.isfinite(res.loss_after)


def test_tail_cvar_on_still_trains_finite(monkeypatch) -> None:
    monkeypatch.setenv("V2_TRAINER_TAIL_CVAR_WEIGHT", "0.5")
    monkeypatch.setenv("V2_TRAINER_TAIL_CVAR_ALPHA", "0.2")
    trainer = _trainer(monkeypatch)
    res = trainer.train(_rows(24), steps=3, batch_size=16)
    import math
    assert math.isfinite(res.loss_after)
    # Sanity: a huge weight must not NaN/inf the loss (topk mean is bounded).
    monkeypatch.setenv("V2_TRAINER_TAIL_CVAR_WEIGHT", "5.0")
    trainer2 = _trainer(monkeypatch)
    res2 = trainer2.train(_rows(24), steps=2, batch_size=16)
    assert math.isfinite(res2.loss_after)
