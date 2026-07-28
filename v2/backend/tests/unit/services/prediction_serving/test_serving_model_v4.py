from __future__ import annotations

import pytest

from v2.backend.app.services.prediction_serving.serving_model_v4 import (
    DIRECTIONAL_ACTIONS,
    MODEL_ARCHITECTURE,
    build_serving_model_v4,
)


def test_shared_v4_model_keeps_action_and_profitability_heads_distinct() -> None:
    torch = pytest.importorskip("torch")
    model = build_serving_model_v4(input_dim=29, action_count=3)

    action_logits, edges, profitability_logits = model(
        torch.zeros((4, 29), dtype=torch.float32)
    )

    assert MODEL_ARCHITECTURE == "mlp_29x32_action3_edge2_profit2_v4"
    assert tuple(action_logits.shape) == (4, 3)
    assert tuple(edges.shape) == (4, len(DIRECTIONAL_ACTIONS))
    assert tuple(profitability_logits.shape) == (4, len(DIRECTIONAL_ACTIONS))
    assert model.action_head is not model.directional_profitability_head
