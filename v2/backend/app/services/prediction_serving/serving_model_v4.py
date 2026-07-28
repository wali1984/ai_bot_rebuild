"""ServingFeatureABIV2 model with a dedicated profitability-confidence head."""

from __future__ import annotations

from typing import Any

MODEL_ARCHITECTURE = "mlp_29x32_action3_edge2_profit2_v4"
DIRECTIONAL_ACTIONS = ("long", "short")


def build_serving_model_v4(*, input_dim: int, action_count: int) -> Any:
    """Build the shared train/serve graph for future paper challengers.

    Action probabilities answer which action the policy selects.  Profitability
    logits separately answer whether LONG or SHORT will finish positive after
    complete costs.  Keeping those heads separate prevents action certainty
    from being mislabeled as economic confidence.
    """

    import torch

    class ServingActionEdgeProfitabilityModelV4(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.trunk = torch.nn.Sequential(
                torch.nn.Linear(input_dim, 32),
                torch.nn.ReLU(),
            )
            self.action_head = torch.nn.Linear(32, action_count)
            self.directional_net_edge_head = torch.nn.Linear(
                32, len(DIRECTIONAL_ACTIONS)
            )
            self.directional_profitability_head = torch.nn.Linear(
                32, len(DIRECTIONAL_ACTIONS)
            )

        def forward(self, values: Any) -> tuple[Any, Any, Any]:
            hidden = self.trunk(values)
            return (
                self.action_head(hidden),
                self.directional_net_edge_head(hidden),
                self.directional_profitability_head(hidden),
            )

    return ServingActionEdgeProfitabilityModelV4()


__all__ = [
    "DIRECTIONAL_ACTIONS",
    "MODEL_ARCHITECTURE",
    "build_serving_model_v4",
]
