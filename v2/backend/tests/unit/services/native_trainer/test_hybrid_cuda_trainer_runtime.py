from __future__ import annotations

from collections import deque

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.runtime import (
    _trusted_replay_load_limit_for_cycle,
)


def test_resident_replay_load_limit_uses_replay_buffer_capacity() -> None:
    replay_buffer = deque(maxlen=4096)

    limit = _trusted_replay_load_limit_for_cycle(
        max_training_rows_per_cycle=32768,
        replay_buffer=replay_buffer,
    )

    assert limit == 4096


def test_nonresident_replay_load_limit_uses_requested_rows() -> None:
    limit = _trusted_replay_load_limit_for_cycle(
        max_training_rows_per_cycle=32768,
        replay_buffer=None,
    )

    assert limit == 32768
