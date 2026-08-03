from __future__ import annotations

import pytest

from v2.backend.app.cli.v2_paper_provisional_prediction_publisher import (
    _gross_expected_move_from_directional_net_edge,
)
from v2.backend.app.services.prediction_serving.serving_model_v3 import (
    EDGE_HEAD_ACTIONS,
    build_serving_model_v3,
)


def test_shared_model_emits_action_logits_and_both_directional_edges() -> None:
    torch = pytest.importorskip("torch")
    model = build_serving_model_v3(input_dim=29, action_count=3)

    logits, edges = model(torch.zeros((4, 29), dtype=torch.float32))

    assert tuple(logits.shape) == (4, 3)
    assert tuple(edges.shape) == (4, len(EDGE_HEAD_ACTIONS))


@pytest.mark.parametrize(
    ("action", "net_edge", "cost", "expected_gross"),
    [
        ("long", 42.0, 8.0, 50.0),
        ("short", 42.0, 8.0, -50.0),
        ("hold", None, 8.0, 0.0),
    ],
)
def test_directional_net_edge_converts_to_signed_gross_move_once(
    action: str, net_edge: float | None, cost: float, expected_gross: float
) -> None:
    assert _gross_expected_move_from_directional_net_edge(
        action=action,
        directional_net_edge_bps=net_edge,
        round_trip_cost_bps=cost,
    ) == expected_gross
