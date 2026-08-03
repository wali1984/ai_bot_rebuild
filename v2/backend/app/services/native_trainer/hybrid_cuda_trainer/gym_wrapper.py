"""Gymnasium compatibility shim for the V2 paper/shadow environment."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import ACTION_COUNT
from .environment import V2PaperShadowHybridEnv


@dataclass(frozen=True)
class DiscreteSpace:
    n: int

    def contains(self, value: Any) -> bool:
        return isinstance(value, int) and 0 <= value < self.n


@dataclass(frozen=True)
class BoxSpace:
    shape: tuple[int, ...]
    dtype: str = "float32"


class V2HybridGymWrapper(V2PaperShadowHybridEnv):
    """Expose action_space/observation_space without importing gymnasium."""

    def __init__(self, *args, observation_dim: int | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.action_space = DiscreteSpace(ACTION_COUNT)
        if observation_dim is None and self.examples:
            tensor = self.examples[0].tensor if hasattr(self.examples[0], "tensor") else self.examples[0]
            observation_dim = len(tensor.model_vector)
        self.observation_space = BoxSpace(shape=(int(observation_dim or 0),))
