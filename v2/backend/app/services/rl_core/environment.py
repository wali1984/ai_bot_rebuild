"""V2 Native Paper-Only RL Environment (P0.2A).

A small Gymnasium-style env loop that:

- runs entirely in paper simulation (no exchange calls, no live orders)
- consumes V2-native feature snapshots produced by P0.1
- exposes reset()/step()/close() with deterministic price ramp
- never imports torch / stable_baselines3 / gymnasium / redis / ccxt /
  binance
- never claims trainer parity, never claims MASA/PPO policy

Legacy behavior sources consulted (read-only mirrors under
v2/legacy_owned_runtime/):

- rl/environment.py
    sha256=39866005417554c7f9552a64eddc14ec1024db7e22b432c844cfd1a8e7800b1d
    size=66775
- rl/gymnasium_wrapper.py
    sha256=61a086cb4a0a406ca67fe2035cf776b0c991bb9d7391572ce86e77aea0a16574
    size=14062

The legacy environment.py (1,455 lines after expansion) and
gymnasium_wrapper.py are NOT fully ported. This is P0.2A: a minimal
runnable env loop wired to the native feature snapshot. Full env parity
is later P0.2 work.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any

LIVE_GATE_STATUS = "blocked_human_only"

LEGACY_SOURCES = {
    "rl/environment.py": {
        "sha256": "39866005417554c7f9552a64eddc14ec1024db7e22b432c844cfd1a8e7800b1d",
        "size_bytes": 66775,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/environment.py",
    },
    "rl/gymnasium_wrapper.py": {
        "sha256": "61a086cb4a0a406ca67fe2035cf776b0c991bb9d7391572ce86e77aea0a16574",
        "size_bytes": 14062,
        "v2_owned_path": "v2/legacy_owned_runtime/rl/gymnasium_wrapper.py",
    },
}

# Discrete action space (paper-only). 0=hold, 1=long, 2=short, 3=close.
ACTION_HOLD = 0
ACTION_LONG = 1
ACTION_SHORT = 2
ACTION_CLOSE = 3
ALLOWED_ACTIONS = (ACTION_HOLD, ACTION_LONG, ACTION_SHORT, ACTION_CLOSE)


@dataclass
class EnvState:
    step_index: int
    price: float
    position_side: int  # +1 long, -1 short, 0 flat
    position_entry_price: float | None
    realized_bps: float
    unrealized_bps: float
    done: bool


@dataclass
class StepOutcome:
    observation_ref: dict[str, Any]  # ref to last built obs (snapshot id, tensor shape)
    reward_total: float
    reward_components: dict[str, float]
    info: dict[str, Any]
    done: bool


@dataclass
class PaperOnlyEnv:
    """Tiny deterministic paper-only environment.

    Price moves on a sinusoid + linear ramp; positions accrue realized_bps
    when closed and unrealized_bps while open. The env never places real
    orders.
    """

    symbol: str = "BTCUSDT"
    timeframe: str = "1m"
    max_steps: int = 64
    initial_price: float = 100.0
    fee_bps_per_side: float = 5.0
    slippage_bps_per_side: float = 1.0

    _state: EnvState | None = field(default=None, init=False)
    _price_trace: list[float] = field(default_factory=list, init=False)
    _action_log: list[int] = field(default_factory=list, init=False)

    def reset(self) -> dict[str, Any]:
        prices: list[float] = []
        for i in range(self.max_steps):
            base = self.initial_price + i * 0.25
            wave = math.sin(i / 6.0) * 0.5
            prices.append(base + wave)
        self._price_trace = prices
        self._action_log = []
        self._state = EnvState(
            step_index=0,
            price=prices[0],
            position_side=0,
            position_entry_price=None,
            realized_bps=0.0,
            unrealized_bps=0.0,
            done=False,
        )
        return {
            "step_index": 0,
            "price": prices[0],
            "position_side": 0,
            "realized_bps": 0.0,
            "unrealized_bps": 0.0,
            "done": False,
            "live_gate": LIVE_GATE_STATUS,
            "live_symbols": [],
        }

    def step(self, action: int) -> tuple[dict[str, Any], dict[str, float]]:
        if self._state is None or self._state.done:
            raise RuntimeError("env not reset or already done; call reset() first")
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"unknown action: {action!r}; allowed: {ALLOWED_ACTIONS}")
        s = self._state
        self._action_log.append(action)
        next_index = s.step_index + 1
        next_price = self._price_trace[next_index] if next_index < len(self._price_trace) else s.price
        round_trip_cost_bps = 2 * (self.fee_bps_per_side + self.slippage_bps_per_side)

        realized_bps_delta = 0.0
        if action == ACTION_LONG and s.position_side == 0:
            s.position_side = 1
            s.position_entry_price = next_price
        elif action == ACTION_SHORT and s.position_side == 0:
            s.position_side = -1
            s.position_entry_price = next_price
        elif action == ACTION_CLOSE and s.position_side != 0 and s.position_entry_price is not None:
            move_pct = (next_price - s.position_entry_price) / s.position_entry_price
            gross_bps = move_pct * 10000.0 * s.position_side
            realized_bps_delta = gross_bps - round_trip_cost_bps
            s.realized_bps += realized_bps_delta
            s.position_side = 0
            s.position_entry_price = None
        # ACTION_HOLD does nothing structural.

        # update unrealized while open
        if s.position_side != 0 and s.position_entry_price is not None:
            move_pct = (next_price - s.position_entry_price) / s.position_entry_price
            s.unrealized_bps = move_pct * 10000.0 * s.position_side
        else:
            s.unrealized_bps = 0.0

        s.step_index = next_index
        s.price = next_price
        if next_index >= self.max_steps - 1:
            s.done = True

        obs = {
            "step_index": s.step_index,
            "price": s.price,
            "position_side": s.position_side,
            "realized_bps": s.realized_bps,
            "unrealized_bps": s.unrealized_bps,
            "done": s.done,
            "live_gate": LIVE_GATE_STATUS,
            "live_symbols": [],
        }
        step_components = {
            "realized_bps_delta": realized_bps_delta,
            "unrealized_bps": s.unrealized_bps,
            "round_trip_cost_bps_if_closed": round_trip_cost_bps,
            "action_taken": float(action),
        }
        return obs, step_components

    def close(self) -> None:
        self._state = None
        self._price_trace = []
        self._action_log = []

    def current_state(self) -> EnvState | None:
        return self._state

    def action_log(self) -> list[int]:
        return list(self._action_log)


def env_invariants_snapshot() -> dict[str, Any]:
    return {
        "live_gate": LIVE_GATE_STATUS,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "scope": "PAPER_ONLY_SIMULATION",
        "imports_torch": False,
        "imports_stable_baselines3": False,
        "imports_gymnasium": False,
        "imports_redis": False,
        "imports_exchange_sdk": False,
        "places_exchange_orders": False,
        "writes_legacy_redis": False,
        "actions_supported": ["hold", "long", "short", "close"],
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "legacy_behavior_mapping": LEGACY_SOURCES,
    }
