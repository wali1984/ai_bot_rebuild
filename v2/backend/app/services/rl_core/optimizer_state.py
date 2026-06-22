"""AdamW-compatible optimizer state (P0.2G, pure stdlib)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

OPTIMIZER_STATE_SCHEMA_VERSION = "v2_native_adamw_optimizer_state_v1"
DEFAULT_LR = 1e-3
DEFAULT_BETA1 = 0.9
DEFAULT_BETA2 = 0.999
DEFAULT_EPS = 1e-8
DEFAULT_WEIGHT_DECAY = 1e-2


@dataclass
class AdamWState:
    name: str
    length: int
    m: list[float] = field(default_factory=list)
    v: list[float] = field(default_factory=list)
    step: int = 0
    lr: float = DEFAULT_LR
    beta1: float = DEFAULT_BETA1
    beta2: float = DEFAULT_BETA2
    eps: float = DEFAULT_EPS
    weight_decay: float = DEFAULT_WEIGHT_DECAY

    def initialize(self) -> None:
        if not self.m:
            self.m = [0.0] * self.length
        if not self.v:
            self.v = [0.0] * self.length

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "length": self.length,
            "step": self.step,
            "m_norm": math.sqrt(sum(x * x for x in self.m)) if self.m else 0.0,
            "v_norm": math.sqrt(sum(x * x for x in self.v)) if self.v else 0.0,
            "lr": self.lr,
            "beta1": self.beta1,
            "beta2": self.beta2,
            "eps": self.eps,
            "weight_decay": self.weight_decay,
        }


def adamw_step(
    state: AdamWState,
    *,
    parameter: list[float],
    gradient: Sequence[float],
) -> None:
    if len(parameter) != state.length:
        raise ValueError(
            f"parameter length {len(parameter)} != state.length {state.length}"
        )
    if len(gradient) != state.length:
        raise ValueError(
            f"gradient length {len(gradient)} != state.length {state.length}"
        )
    state.initialize()
    state.step += 1
    b1 = state.beta1
    b2 = state.beta2
    one_minus_b1 = 1.0 - b1
    one_minus_b2 = 1.0 - b2
    b1_t = 1.0 - (b1 ** state.step)
    b2_t = 1.0 - (b2 ** state.step)
    for i in range(state.length):
        g = float(gradient[i])
        state.m[i] = b1 * state.m[i] + one_minus_b1 * g
        state.v[i] = b2 * state.v[i] + one_minus_b2 * (g * g)
        m_hat = state.m[i] / b1_t
        v_hat = state.v[i] / b2_t
        update = m_hat / (math.sqrt(v_hat) + state.eps) + state.weight_decay * parameter[i]
        parameter[i] = parameter[i] - state.lr * update


def optimizer_state_invariants_snapshot() -> dict:
    return {
        "schema_version": OPTIMIZER_STATE_SCHEMA_VERSION,
        "optimizer_class": "AdamW",
        "default_lr": DEFAULT_LR,
        "default_beta1": DEFAULT_BETA1,
        "default_beta2": DEFAULT_BETA2,
        "default_eps": DEFAULT_EPS,
        "default_weight_decay": DEFAULT_WEIGHT_DECAY,
        "imports_torch": False,
        "imports_numpy": False,
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
    }
