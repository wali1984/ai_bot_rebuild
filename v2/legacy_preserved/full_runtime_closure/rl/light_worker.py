"""
Torch-free worker function for LightSubprocVecEnv.

This module is imported ONLY by spawned child processes.
It must NOT import torch, stable_baselines3, or any module that does.

Memory per worker: ~49 MB (vs 508 MB with SB3 + torch)
"""

import os
import sys
import time
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))


def _light_worker(
    pipe,           # multiprocessing.connection.Connection
    parent_pipe,    # multiprocessing.connection.Connection
    env_id: int,
    symbol: str,
    timeframe: str,
    tx_cost: float,
):
    """Worker loop for LightSubprocVecEnv.

    This function runs in a spawned child process.  It imports ONLY:
      - rl.cpu_env  (numpy-only, ~33 MB)
      - config      (no torch since CUDA_VISIBLE_DEVICES="")
      - gymnasium   (~5 MB)

    Total per-worker: ~49 MB  (vs 508 MB with SB3 + torch)
    """
    parent_pipe.close()

    # Hard-disable CUDA before any imports
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"
    os.environ["NUMEXPR_MAX_THREADS"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["SUBPROC_DEBUG_MODE"] = "1"

    # Stagger startup to avoid Redis thundering-herd
    if env_id > 0:
        stagger = min(0.1 * env_id, 8.0)
        time.sleep(stagger)

    from rl.cpu_env import CPUTradingEnvironment

    env = CPUTradingEnvironment(
        symbol=symbol,
        timeframe=timeframe,
        initial_balance=10000.0,
        transaction_cost=tx_cost,
        max_position=1.0,
        lookback_window=10,
    )

    # Episode tracking (mimics SB3 Monitor)
    episode_rewards: list = []
    episode_length: int = 0
    t_start = time.time()

    try:
        while True:
            cmd, data = pipe.recv()

            if cmd == "step":
                obs, reward, terminated, truncated, info = env.step(data)
                episode_rewards.append(reward)
                episode_length += 1
                done = terminated or truncated

                if done:
                    # Record episode stats like SB3 Monitor does
                    info["episode"] = {
                        "r": sum(episode_rewards),
                        "l": episode_length,
                        "t": round(time.time() - t_start, 6),
                    }
                    info["terminal_observation"] = obs.copy()
                    obs, _reset_info = env.reset()
                    episode_rewards = []
                    episode_length = 0

                # SB3 VecEnv expects (obs, reward, done, info) — 4 values
                pipe.send((obs, reward, done, info))

            elif cmd == "reset":
                obs, info = env.reset()
                episode_rewards = []
                episode_length = 0
                pipe.send(obs)

            elif cmd == "get_spaces":
                pipe.send((env.observation_space, env.action_space))

            elif cmd == "get_attr":
                pipe.send(getattr(env, data, None))

            elif cmd == "set_attr":
                attr_name, value = data
                setattr(env, attr_name, value)
                pipe.send(True)

            elif cmd == "env_method":
                method_name, args, kwargs = data
                result = getattr(env, method_name)(*args, **kwargs)
                pipe.send(result)

            elif cmd == "close":
                pipe.send(True)
                break

            elif cmd == "seed":
                env.reset(seed=data)
                pipe.send(True)

            else:
                raise ValueError(f"Unknown command: {cmd}")

    except (EOFError, BrokenPipeError):
        pass
    except KeyboardInterrupt:
        pass
    finally:
        try:
            env.close()
        except Exception:
            pass
        pipe.close()
