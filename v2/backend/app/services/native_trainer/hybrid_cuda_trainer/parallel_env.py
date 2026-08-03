"""V2-safe parallel environment rollout proof for the hybrid trainer."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from .config import ACTION_LABELS, LIVE_GATE_BLOCKED
from .environment import V2PaperShadowHybridEnv


@dataclass(frozen=True)
class ParallelEnvRolloutResult:
    status: str
    backend: str
    configured_n_envs: int
    envs_requested: int
    envs_instantiated: int
    worker_count: int
    rollout_n_steps: int
    unique_symbols: int
    unique_timeframes: int
    covers_all_loaded_examples: bool
    action_contract: tuple[str, ...]
    reward_min_bps: float | None
    reward_max_bps: float | None
    reward_avg_bps: float | None
    samples: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    live_gate: str = LIVE_GATE_BLOCKED
    live_symbols: tuple[str, ...] = field(default_factory=tuple)
    exchange_mutation: bool = False

    def to_jsonable(self) -> dict[str, Any]:
        out = asdict(self)
        out["action_contract"] = list(self.action_contract)
        out["live_symbols"] = list(self.live_symbols)
        return out


def run_parallel_env_rollout_proof(
    examples: Sequence[Any],
    *,
    configured_n_envs: int,
    rollout_n_steps: int,
    max_workers: int,
) -> ParallelEnvRolloutResult:
    """Instantiate one paper/shadow env per loaded example up to the configured cap.

    This intentionally does not import the raw legacy SubprocVecEnv trainer. It gives
    V2 a deterministic, no-exchange-mutation rollout proof across the dynamic
    symbol/timeframe batch while preserving V2-only safety.
    """

    loaded = list(examples)
    if not loaded:
        return ParallelEnvRolloutResult(
            status="NO_EXAMPLES",
            backend="ThreadPoolExecutor",
            configured_n_envs=max(0, int(configured_n_envs)),
            envs_requested=0,
            envs_instantiated=0,
            worker_count=0,
            rollout_n_steps=max(1, int(rollout_n_steps)),
            unique_symbols=0,
            unique_timeframes=0,
            covers_all_loaded_examples=False,
            action_contract=ACTION_LABELS,
            reward_min_bps=None,
            reward_max_bps=None,
            reward_avg_bps=None,
        )

    requested = min(len(loaded), max(1, int(configured_n_envs)))
    worker_count = max(1, min(int(max_workers), requested))
    selected = loaded[:requested]

    def run_one(index: int, example: Any) -> dict[str, Any]:
        env = V2PaperShadowHybridEnv(examples=[example], max_steps=1)
        obs, reset_info = env.reset()
        del obs
        action = int(getattr(example, "label_action_index", 0) or 0)
        _, reward, terminated, truncated, info = env.step(action)
        action_label = ACTION_LABELS[action] if 0 <= action < len(ACTION_LABELS) else "unknown"
        return {
            "index": index,
            "symbol": getattr(example, "symbol", ""),
            "timeframe": getattr(example, "timeframe", ""),
            "action_index": action,
            "action_label": action_label,
            "reward_bps": float(reward),
            "terminated": bool(terminated),
            "truncated": bool(truncated),
            "reset_live_gate": reset_info.get("live_gate"),
            "step_live_gate": info.get("live_gate"),
            "exchange_mutation": bool(info.get("exchange_mutation", False)),
            "paper_fill_only": bool(info.get("paper_fill_only", False)),
        }

    samples: list[dict[str, Any]] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {pool.submit(run_one, idx, example): idx for idx, example in enumerate(selected)}
        for future in as_completed(futures):
            try:
                samples.append(future.result())
            except Exception as exc:  # noqa: BLE001
                errors.append(f"env_{futures[future]}:{type(exc).__name__}:{exc}")

    samples.sort(key=lambda row: int(row.get("index", 0)))
    rewards = [float(row["reward_bps"]) for row in samples if "reward_bps" in row]
    unique_symbols = len({str(getattr(example, "symbol", "")) for example in selected})
    unique_timeframes = len({str(getattr(example, "timeframe", "")) for example in selected})
    covers_all = len(samples) == len(loaded) and not errors
    status = "READY_FULL_DYNAMIC_BATCH" if covers_all else "READY_TRUNCATED_OR_ERRORS"
    if errors:
        status = "ROLLUP_ERRORS"
    return ParallelEnvRolloutResult(
        status=status,
        backend="ThreadPoolExecutor",
        configured_n_envs=max(0, int(configured_n_envs)),
        envs_requested=requested,
        envs_instantiated=len(samples),
        worker_count=worker_count,
        rollout_n_steps=max(1, int(rollout_n_steps)),
        unique_symbols=unique_symbols,
        unique_timeframes=unique_timeframes,
        covers_all_loaded_examples=covers_all,
        action_contract=ACTION_LABELS,
        reward_min_bps=min(rewards) if rewards else None,
        reward_max_bps=max(rewards) if rewards else None,
        reward_avg_bps=sum(rewards) / len(rewards) if rewards else None,
        samples=samples[:32],
        errors=errors[:32],
    )
