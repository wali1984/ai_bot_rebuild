"""Shared action and directional-edge model for ServingFeatureABIV2."""

from __future__ import annotations

from typing import Any

MODEL_ARCHITECTURE = "mlp_29x32_action3_edge2_v3"
EDGE_HEAD_ACTIONS = ("long", "short")


def build_serving_model_v3(*, input_dim: int, action_count: int) -> Any:
    """Build the identical module graph used by training and serving."""
    import torch

    class ServingActionEdgeModelV3(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.trunk = torch.nn.Sequential(
                torch.nn.Linear(input_dim, 32),
                torch.nn.ReLU(),
            )
            self.action_head = torch.nn.Linear(32, action_count)
            self.directional_net_edge_head = torch.nn.Linear(
                32, len(EDGE_HEAD_ACTIONS)
            )

        def forward(self, values: Any) -> tuple[Any, Any]:
            hidden = self.trunk(values)
            return self.action_head(hidden), self.directional_net_edge_head(hidden)

    return ServingActionEdgeModelV3()


__all__ = ["EDGE_HEAD_ACTIONS", "MODEL_ARCHITECTURE", "build_serving_model_v3"]
