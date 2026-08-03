from __future__ import annotations

from collections import deque

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.runtime import (
    _select_training_examples_for_cycle,
)


def test_replay_buffer_training_selection_keeps_latest_bounded_slice() -> None:
    replay_buffer = deque(["old_1", "old_2", "old_3"], maxlen=10)

    selected = _select_training_examples_for_cycle(
        fresh_examples=["new_1", "new_2"],
        replay_buffer=replay_buffer,
        max_training_rows_per_cycle=3,
    )

    assert list(replay_buffer) == ["old_1", "old_2", "old_3", "new_1", "new_2"]
    assert selected == ["old_3", "new_1", "new_2"]


def test_training_selection_without_replay_keeps_fresh_rows_only() -> None:
    selected = _select_training_examples_for_cycle(
        fresh_examples=["new_1", "new_2"],
        replay_buffer=None,
        max_training_rows_per_cycle=10,
    )

    assert selected == ["new_1", "new_2"]
