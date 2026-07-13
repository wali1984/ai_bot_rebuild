"""Cross-epoch input cache in _train_torch (WI-1 prod speedup).

The offline loop calls train() with the SAME examples every epoch; train() slices
a deterministic prefix, so the windowed input + label tensors are identical across
epochs and only the weights change. Caching them avoids rebuilding + sanitising the
(16x-bigger, temporal) tensor every epoch, which was starving the GPU.

The SAFETY-CRITICAL property tested here: the cache is keyed by a per-example
content fingerprint (tensor_id), NOT by row COUNT alone -- so the online loop, which
feeds DIFFERENT examples of the SAME length each cycle, always MISSES and rebuilds
(never trains on stale data). A hit reuses the cache dict object; a miss reassigns it.
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


def _rows(start: int, n: int):
    return [_example(start + i, (1, 2, 0)[i % 3]) for i in range(n)]


def _trainer(monkeypatch):
    monkeypatch.setenv("V2_TRAINER_HIDDEN_SIZE", "64")
    monkeypatch.setenv("V2_TRAINER_RESIDUAL_BLOCKS", "1")
    monkeypatch.delenv("V2_TRAINER_TEMPORAL_ENCODER", raising=False)  # arch-independent
    # model_vector = values + missing_mask + stale_mask + source_availability = 4*(1 feature).
    model = V2HybridPolicyModel(input_dim=4)
    if not model.torch_available:
        pytest.skip("torch unavailable")
    return V2HybridPPOTrainer(model=model)


def test_same_rows_hit_and_different_rows_of_equal_length_miss(monkeypatch) -> None:
    trainer = _trainer(monkeypatch)
    rows_a = _rows(0, 16)
    rows_b = _rows(1000, 16)  # SAME length, DIFFERENT examples (different tensor_ids)

    trainer.train(rows_a, steps=1, batch_size=12)
    cache1 = getattr(trainer, "_train_input_cache", None)
    assert cache1 is not None, "cache should be populated after a cacheable train() call"
    fp_a = cache1["fp"]

    # SAME rows -> HIT: else-branch skipped, so the cache dict object is unchanged.
    trainer.train(rows_a, steps=1, batch_size=12)
    assert trainer._train_input_cache is cache1, "same rows must reuse the cached tensors (hit)"
    assert trainer._train_input_cache["fp"] == fp_a

    # DIFFERENT rows, SAME length -> MISS: must rebuild (no stale-data false hit).
    trainer.train(rows_b, steps=1, batch_size=12)
    assert trainer._train_input_cache is not cache1, "different examples must rebuild (miss)"
    assert trainer._train_input_cache["fp"] != fp_a, (
        "equal-length-but-different rows must NOT share a fingerprint (online-safety)"
    )


def test_cache_fingerprint_uses_tensor_id_not_just_count(monkeypatch) -> None:
    # Directly assert the fingerprint carries a per-example token, so it cannot
    # collapse to a count-only key (which would false-hit the online loop).
    trainer = _trainer(monkeypatch)
    trainer.train(_rows(0, 16), steps=1, batch_size=12)
    fp = trainer._train_input_cache["fp"]
    # fp = (len_train, len_val, temporal, seq_len, tokens); tokens carry tensor ids.
    tokens = fp[-1]
    token_ids = [t[0] for t in tokens if t is not None]
    assert token_ids, "fingerprint must include at least one tensor-id token"
    assert any(tid is not None for tid in token_ids), "tensor-id tokens must be populated"
