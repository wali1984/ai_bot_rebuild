from __future__ import annotations

import pytest

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    V2HybridTrainerDataLoader,
)


@pytest.mark.parametrize(
    ("after_cost_bps", "expected_action_index"),
    [
        (0.000001, 1),
        (-0.000001, 2),
        (0.0, 0),
    ],
)
def test_after_cost_label_uses_break_even_invariant_without_static_bps_band(
    after_cost_bps: float,
    expected_action_index: int,
) -> None:
    assert (
        V2HybridTrainerDataLoader._label_action(after_cost_bps)  # noqa: SLF001
        == expected_action_index
    )
