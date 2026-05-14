"""
Gymnasium Wrapper for TradingEnvironment
Makes the trading environment compatible with stable-baselines3
"""

import gymnasium as gym
import numpy as np
from typing import Dict, Any, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import os
import sys
import threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rl.environment import TradingEnvironment
from rl.hedge_reward_functions import HedgeRewardCalculator, ActionContext, HedgeAction
from utils.logger import get_logger

logger = get_logger("gymnasium_wrapper")

class TradingEnvironmentWrapper(gym.Env):
    """
    Gymnasium wrapper for TradingEnvironment to make it compatible with stable-baselines3
    Supports both CPU and GPU environments
    """
    
    def __init__(self, 
                 base_env=None,
                 initial_balance: float = 10000.0,
                 transaction_cost: float = 0.001,
                 max_position: float = 1.0,
                 lookback_window: int = 10):
        """
        Initialize the Gymnasium wrapper
        """
        super().__init__()
        
        # Use provided environment or create default CPU environment
        if base_env is not None:
            self.env = base_env
            self.is_gpu_env = hasattr(base_env, 'get_state_gpu')
            logger.info(f"Using {'GPU' if self.is_gpu_env else 'CPU'} environment wrapper")
        else:
            # Create the underlying CPU trading environment
            self.env = TradingEnvironment(
                initial_balance=initial_balance,
                transaction_cost=transaction_cost,
                max_position=max_position,
                lookback_window=lookback_window
            )
            self.is_gpu_env = False
        
        # Define action space (canonical):
        # Discrete(7) mapping is defined in rl/action_ontology.py:
        # 0=HOLD, 1=OPEN_LONG, 2=OPEN_SHORT, 3=CLOSE_LONG, 4=CLOSE_SHORT,
        # 5=CLOSE_SHORT_OPEN_LONG, 6=CLOSE_LONG_OPEN_SHORT
        self.action_space = gym.spaces.Discrete(7)  # Single categorical action (no MultiDiscrete)
        
        # Define observation space
        # Get initial state to determine observation size
        if self.is_gpu_env:
            try:
                initial_state = self.env.get_state_gpu().cpu().numpy()
                obs_size = len(initial_state)
            except Exception as e:
                logger.warning(f"⚠️ GPU state not ready during init: {e}, using fallback size")
                obs_size = 14620  # Use known size from CPU env
        else:
            initial_state = self.env.get_state()
            obs_size = len(initial_state)
        logger.info(f"Observation space size: {obs_size} ({'GPU' if self.is_gpu_env else 'CPU'} environment)")
        
        # Observation space: continuous values normalized to [-10, 10] range
        self.observation_space = gym.spaces.Box(
            low=-10.0, 
            high=10.0, 
            shape=(obs_size,), 
            dtype=np.float32
        )
        
        # Episode tracking
        self.episode_steps = 0
        self.max_episode_steps = 1000
        
        # Initialize hedge reward calculator for 7-action system
        self.hedge_reward_calc = HedgeRewardCalculator(min_hold_minutes=20)
        
        logger.info("TradingEnvironmentWrapper initialized with 7-action hedge rewards")
        
        # ------------------------------------------------------------------
        # Performance vs safety tradeoff (IMPORTANT)
        #
        # Previous implementation wrapped *every env call* in a brand new
        # ThreadPoolExecutor to enforce timeouts. That is extremely expensive
        # (thousands of threadpool creations per rollout) and will tank rollout FPS.
        #
        # We now default to **no per-call thread timeout** and rely on the outer
        # rollout watchdog in `GPUForcedPPO.collect_rollouts()` to detect stuck
        # SubprocVecEnv workers and recreate the VecEnv.
        #
        # If you still want per-env call timeouts (debug/ops), set:
        #   ENV_IO_TIMEOUT_SECONDS=10
        # ------------------------------------------------------------------
        try:
            self._io_timeout_seconds = float(os.getenv("ENV_IO_TIMEOUT_SECONDS", "0"))
        except Exception:
            self._io_timeout_seconds = 0.0
        self._executor: Optional[ThreadPoolExecutor] = None
        self._timeout_fail_count = 0
        self._shutting_down = False
        
    def _is_shutting_down(self):
        """Check if interpreter is shutting down"""
        return self._shutting_down or threading.current_thread() != threading.main_thread()

    def _safe_call(self, fn, *args, **kwargs):
        """Run a function with a hard timeout and return (ok, result).
        On timeout or error, returns (False, None)."""
        # Fast path: no thread-based timeout (default for performance)
        if not self._io_timeout_seconds or self._io_timeout_seconds <= 0:
            try:
                return True, fn(*args, **kwargs)
            except Exception as e:
                if not self._is_shutting_down():
                    logger.error(f"❌ Env call failed: {e}")
                return False, None

        # Slow/safety path: optional thread timeout (opt-in via ENV_IO_TIMEOUT_SECONDS)
        if self._is_shutting_down():
            return False, None

        try:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="env_io")

            future = self._executor.submit(fn, *args, **kwargs)
            return True, future.result(timeout=self._io_timeout_seconds)

        except FuturesTimeoutError:
            self._timeout_fail_count += 1
            if not self._is_shutting_down():
                logger.warning(
                    f"⚠️ Env call timed out after {self._io_timeout_seconds}s "
                    f"(fail_count={self._timeout_fail_count})"
                )
            # Best-effort cancel; the underlying work may keep running in the thread.
            try:
                future.cancel()
            except Exception:
                pass
            # Recreate executor to avoid a stuck worker thread blocking subsequent calls.
            try:
                if self._executor is not None:
                    self._executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                # Python < 3.9: cancel_futures not supported
                try:
                    self._executor.shutdown(wait=False)
                except Exception:
                    pass
            except Exception:
                pass
            self._executor = None
            return False, None

        except (RuntimeError, SystemExit) as e:
            # Handle shutdown-related errors gracefully
            if "cannot schedule new futures after interpreter shutdown" in str(e):
                self._shutting_down = True
                return False, None
            logger.error(f"❌ Env call failed: {e}")
            return False, None

        except Exception as e:
            if not self._is_shutting_down():
                logger.error(f"❌ Env call failed: {e}")
            return False, None
    
    def reset(self, seed: Optional[int] = None, options: Optional[dict] = None) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Reset the environment
        
        Returns:
            observation: Initial observation
            info: Additional information
        """
        super().reset(seed=seed)
        
        # Reset the underlying environment with timeout protection
        if self.is_gpu_env:
            ok, gpu_observation = self._safe_call(self.env.reset_gpu)
            if ok and gpu_observation is not None:
                observation = gpu_observation.cpu().numpy().astype(np.float32)
                balance = self.env.current_balance.item()
                positions = self.env.positions.cpu().numpy()
            else:
                # Fallback on timeout/error
                observation = np.zeros(self.observation_space.shape, dtype=np.float32)
                balance = self.env.initial_balance if hasattr(self.env, 'initial_balance') else 10000.0
                positions = np.zeros(len(getattr(self.env, 'positions', [])) or 0)
        else:
            _ = self.env.reset()
            ok, state = self._safe_call(self.env.get_state)
            if ok and state is not None:
                observation = state.astype(np.float32)
            else:
                observation = np.zeros(self.observation_space.shape, dtype=np.float32)
            balance = getattr(self.env, 'current_balance', self.env.initial_balance)
            positions = dict(getattr(self.env, 'positions', {}))
        
        self.episode_steps = 0
        
        # Ensure observation is within bounds
        observation = np.clip(observation, -10.0, 10.0)
        
        info = {
            'balance': balance,
            'positions': positions,
            'step': self.episode_steps
        }
        
        return observation, info
    
    def step(self, action: np.ndarray) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        """
        Execute one step in the environment - HARDENED for VecEnv compatibility
        
        Args:
            action: Single action array for this env (not batched)
            
        Returns:
            observation: Next observation  
            reward: Reward for this step
            terminated: Whether episode is terminated
            truncated: Whether episode is truncated
            info: Additional information
        """
        self.episode_steps += 1
        
        # HEDGE RECOVERY: Handle single categorical action (0-6)
        action = np.asarray(action)
        if action.ndim > 1:
            action = action.squeeze()  # Remove batch dimensions
        
        # Validate action is single integer in [0,6] 
        if action.ndim > 0:  # Still an array
            action = action.item()  # Convert to scalar
        
        if not (0 <= action <= 6):
            raise ValueError(f"Action out of range: got {action}, expected [0,6] for 7-action Categorical")
        
        # Pass action directly (no conversion needed for single categorical)
        action_int = int(action)
        
        # Execute step in underlying environment with timeout protection
        if self.is_gpu_env:
            ok, result = self._safe_call(self.env.step_gpu, action_int)
            if ok and result is not None:
                gpu_observation, reward, done, info = result
                observation = gpu_observation.cpu().numpy().astype(np.float32)
                balance = info.get('balance', self.env.initial_balance)
                positions = info.get('positions', [])
                if self.episode_steps == 1:
                    logger.info(f"🚀 GPU environment step completed - obs shape: {observation.shape}")
            else:
                # Timeout/error fallback
                observation = np.zeros(self.observation_space.shape, dtype=np.float32)
                reward = -0.5  # Mild penalty for stalled data
                done = True
                info = {'timeout': True, 'gpu_accelerated': True}
                balance = self.env.initial_balance
                positions = []
        else:
            ok, result = self._safe_call(self.env.step, action_int)
            if ok and result is not None:
                observation, reward, done, info = result
                observation = observation.astype(np.float32)
                balance = getattr(self.env, 'current_balance', self.env.initial_balance)
                positions = dict(getattr(self.env, 'positions', {}))
            else:
                observation = np.zeros(self.observation_space.shape, dtype=np.float32)
                reward = -0.5
                done = True
                info = {'timeout': True, 'gpu_accelerated': False}
                balance = getattr(self.env, 'current_balance', self.env.initial_balance)
                positions = dict(getattr(self.env, 'positions', {}))

        # Ensure observation is within bounds
        observation = np.clip(observation, -10.0, 10.0)

        # Handle termination vs truncation
        initial_balance = self.env.initial_balance
        terminated = done and (balance <= 0.1 * initial_balance)
        truncated = self.episode_steps >= self.max_episode_steps or (done and not terminated)

        # Update info
        info.update({
            'balance': balance,
            'positions': positions,
            'step': self.episode_steps,
            'total_return': (balance / initial_balance) - 1.0,
            'gpu_accelerated': self.is_gpu_env
        })

        return observation, float(reward), terminated, truncated, info
    
    def render(self):
        """Render the environment (optional)"""
        return self.env.render() if hasattr(self.env, 'render') else None
    
    def close(self):
        """Close the environment"""
        # Best-effort shutdown of optional thread executor
        try:
            if self._executor is not None:
                try:
                    self._executor.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    self._executor.shutdown(wait=False)
                self._executor = None
        except Exception:
            pass
        if hasattr(self.env, 'close'):
            self.env.close()


def make_env(rank: int = 0, **kwargs):
    """
    Utility function to create environment for multiprocessing
    
    Args:
        rank: Environment rank for seeding
        **kwargs: Arguments for TradingEnvironmentWrapper
        
    Returns:
        Environment creation function
    """
    def _init():
        env = TradingEnvironmentWrapper(**kwargs)
        env.reset(seed=rank)
        return env
    return _init
