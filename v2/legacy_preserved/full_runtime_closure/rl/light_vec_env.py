"""
Lightweight SubprocVecEnv — torch-free workers for SubprocVecEnv

OOM FIX (2026-04-14):
SB3's SubprocVecEnv imports torch in every worker process (~474 MB each).
125 workers × 474 MB = 58 GB → OOM on 123 GB system.

This module provides LightSubprocVecEnv which:
  • Spawns worker processes using rl.light_worker._light_worker (no torch, no SB3)
  • Workers communicate via multiprocessing Pipes (same as SB3)
  • Implements SB3's VecEnv interface so PPO can use it transparently

CRITICAL: The worker function lives in rl/light_worker.py which does NOT
import torch or SB3. When spawn unpickles the target function it only
imports that tiny module (~49 MB per worker instead of ~508 MB).

Memory: ~49 MB per worker → 125 workers ≈ 6 GB (fits easily)
"""

import multiprocessing as mp
import os
import sys
import time
import numpy as np
from typing import Any, Dict, List, Optional, Sequence, Tuple, Type, Union

import gymnasium as gym

# SB3's VecEnv base class is imported ONLY in the main process
from stable_baselines3.common.vec_env.base_vec_env import VecEnv, VecEnvObs, VecEnvStepReturn

# Worker function lives in separate torch-free module
from rl.light_worker import _light_worker


class LightSubprocVecEnv(VecEnv):
    """SubprocVecEnv replacement with torch-free workers.

    Drop-in replacement for SB3's SubprocVecEnv.  Workers import only
    ``rl.cpu_env`` (~49 MB each) instead of SB3 + torch (~508 MB each).

    For 125 environments:
        SB3 SubprocVecEnv:    125 × 508 MB = 62 GB  → OOM
        LightSubprocVecEnv:   125 × 49 MB  =  6 GB  → safe
    """

    def __init__(
        self,
        env_configs: List[Tuple[str, str]],
        tx_cost: float = 0.0004,
    ):
        """
        Args:
            env_configs: list of (symbol, timeframe) tuples, one per env.
            tx_cost: transaction cost for all envs.
        """
        n_envs = len(env_configs)
        self.env_configs = env_configs
        self._tx_cost = tx_cost

        ctx = mp.get_context("spawn")

        self.parent_pipes: List[mp.connection.Connection] = []
        self.processes: List[mp.Process] = []
        self.waiting = False

        print(f"🚀 [LightSubprocVecEnv] Spawning {n_envs} torch-free workers...", flush=True)
        t0 = time.time()

        # ── CRITICAL OOM FIX ──────────────────────────────────────────
        # When launched with `python -m rl.hybrid_trainer`, spawn's
        # `get_preparation_data()` captures `__main__.__spec__.name`
        # (= 'rl.hybrid_trainer') and every child process re-imports
        # the entire 55K-line trainer → 474 MB torch overhead per worker.
        #
        # If __spec__ is None, spawn falls back to `__main__.__file__`
        # (init_main_from_path) which ALSO reimports the trainer.
        #
        # We must temporarily clear BOTH __spec__ AND __file__ so spawn
        # sends neither init_main_from_name nor init_main_from_path.
        # Children then start with a clean __main__ and only unpickle
        # the target function from rl.light_worker → no torch.
        # ──────────────────────────────────────────────────────────────
        _main = sys.modules.get("__main__")
        _saved_spec = getattr(_main, "__spec__", None) if _main else None
        _saved_file = getattr(_main, "__file__", None) if _main else None
        if _main is not None:
            _main.__spec__ = None
            if hasattr(_main, "__file__"):
                del _main.__file__

        try:
            for i, (sym, tf) in enumerate(env_configs):
                parent_conn, child_conn = ctx.Pipe()
                proc = ctx.Process(
                    target=_light_worker,
                    args=(child_conn, parent_conn, i, sym, tf, tx_cost),
                    daemon=True,
                )
                proc.start()
                child_conn.close()
                self.parent_pipes.append(parent_conn)
                self.processes.append(proc)
        finally:
            # Restore __spec__ and __file__ so the main process is unaffected
            if _main is not None:
                _main.__spec__ = _saved_spec
                if _saved_file is not None:
                    _main.__file__ = _saved_file

        # Get observation/action spaces from first worker
        self.parent_pipes[0].send(("get_spaces", None))
        obs_space, act_space = self.parent_pipes[0].recv()

        elapsed = time.time() - t0
        print(
            f"✅ [LightSubprocVecEnv] {n_envs} workers ready in {elapsed:.1f}s | "
            f"obs={obs_space.shape} act={act_space.n} | NO TORCH in workers",
            flush=True,
        )

        super().__init__(n_envs, obs_space, act_space)

        # Store metadata for trainer's env_index_map
        self.index_map = env_configs

    # ── Core VecEnv interface ────────────────────────────────────────

    def step_async(self, actions: np.ndarray) -> None:
        for i, pipe in enumerate(self.parent_pipes):
            pipe.send(("step", int(actions[i])))
        self.waiting = True

    def step_wait(self) -> VecEnvStepReturn:
        try:
            results = [pipe.recv() for pipe in self.parent_pipes]
        except (EOFError, BrokenPipeError) as exc:
            self.waiting = False
            # A worker sub-process died (pipe was closed).  Raise RuntimeError
            # so the trainer's existing "Rollout timeout" recovery path can
            # catch it, rebuild the vec_env, and continue without crashing.
            raise RuntimeError(
                f"Rollout timeout: worker process died unexpectedly ({type(exc).__name__})"
            ) from exc
        self.waiting = False

        obs_list, rews, dones, infos = [], [], [], []
        for obs, reward, done, info in results:
            obs_list.append(obs)
            rews.append(reward)
            dones.append(done)
            infos.append(info)

        return (
            np.stack(obs_list).astype(np.float32),
            np.array(rews, dtype=np.float32),
            np.array(dones, dtype=bool),
            infos,
        )

    def reset(self) -> VecEnvObs:
        for pipe in self.parent_pipes:
            pipe.send(("reset", None))
        obs_list = [pipe.recv() for pipe in self.parent_pipes]
        return np.stack(obs_list).astype(np.float32)

    def close(self) -> None:
        if self.waiting:
            for pipe in self.parent_pipes:
                try:
                    pipe.recv()
                except Exception:
                    pass

        for pipe in self.parent_pipes:
            try:
                pipe.send(("close", None))
            except Exception:
                pass
        for pipe in self.parent_pipes:
            try:
                pipe.recv()
            except Exception:
                pass
        for proc in self.processes:
            try:
                proc.join(timeout=5)
            except Exception:
                pass
        for proc in self.processes:
            if proc.is_alive():
                try:
                    proc.kill()
                except Exception:
                    pass
        self.parent_pipes = []
        self.processes = []

    def seed(self, seed: Optional[int] = None) -> Sequence[Optional[int]]:
        seeds = []
        for i, pipe in enumerate(self.parent_pipes):
            s = seed + i if seed is not None else None
            pipe.send(("seed", s))
            seeds.append(s)
        for pipe in self.parent_pipes:
            pipe.recv()
        return seeds

    def get_attr(self, attr_name: str, indices: Optional[List[int]] = None) -> List[Any]:
        target = self._get_target_pipes(indices)
        for pipe in target:
            pipe.send(("get_attr", attr_name))
        return [pipe.recv() for pipe in target]

    def set_attr(self, attr_name: str, value: Any, indices: Optional[List[int]] = None) -> None:
        target = self._get_target_pipes(indices)
        for pipe in target:
            pipe.send(("set_attr", (attr_name, value)))
        for pipe in target:
            pipe.recv()

    def env_method(
        self,
        method_name: str,
        *method_args,
        indices: Optional[List[int]] = None,
        **method_kwargs,
    ) -> List[Any]:
        target = self._get_target_pipes(indices)
        for pipe in target:
            pipe.send(("env_method", (method_name, method_args, method_kwargs)))
        return [pipe.recv() for pipe in target]

    def env_is_wrapped(
        self,
        wrapper_class: Type[gym.Wrapper],
        indices: Optional[List[int]] = None,
    ) -> List[bool]:
        n = len(indices) if indices is not None else self.num_envs
        return [False] * n

    def get_images(self) -> Sequence[Optional[np.ndarray]]:
        return [None] * self.num_envs

    def render(self, mode: Optional[str] = None) -> Optional[np.ndarray]:
        return None

    # ── Helpers ──────────────────────────────────────────────────────

    def _get_target_pipes(self, indices: Optional[List[int]] = None):
        if indices is None:
            return self.parent_pipes
        return [self.parent_pipes[i] for i in indices]
