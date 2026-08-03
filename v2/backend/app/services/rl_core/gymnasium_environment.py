"""
Gymnasium-compatible trading environment for V2 RL inference

Observation space: Box(542) — 562 unified feature fields (409 live + 153 zero-padded)
Action space: Discrete(5) — LONG (0), SHORT (1), HOLD (2), EXIT (3), REDUCE (4)

Compatible with legacy PPO checkpoints trained on same space.
Inference-only (no training loop in this module).
"""

import gymnasium as gym
from gymnasium import spaces
import numpy as np
from typing import Dict, Any, Tuple, Optional
import logging

logger = logging.getLogger(__name__)

# Action space definition
class TradingAction:
    LONG = 0
    SHORT = 1
    HOLD = 2
    EXIT = 3
    REDUCE = 4

    NAMES = {
        0: "LONG",
        1: "SHORT",
        2: "HOLD",
        3: "EXIT",
        4: "REDUCE"
    }


class V2TradingEnvironment(gym.Env):
    """
    Gymnasium environment wrapping V2 unified features for RL inference.

    This environment provides:
    - Observation space: 562-dimensional feature vector (Box)
    - Action space: 5 discrete actions
    - Compatible with legacy PPO/MASA policies trained on same space

    Note: Inference-only. No reward signal, no episode termination.
    Used solely for policy evaluation.
    """

    metadata = {"render_modes": []}

    def __init__(self, feature_dim: int = 562, action_space_size: int = 5):
        """
        Initialize trading environment.

        Args:
            feature_dim: Number of input features (default 562)
            action_space_size: Number of discrete actions (default 5)
        """
        super().__init__()

        self.feature_dim = feature_dim
        self.action_space_size = action_space_size

        # Observation space: continuous features
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(feature_dim,),
            dtype=np.float32
        )

        # Action space: discrete actions
        self.action_space = spaces.Discrete(action_space_size)

        # Current state (set by reset or step)
        self._current_obs = None
        self._step_count = 0

        logger.info(f"V2TradingEnvironment initialized")
        logger.info(f"  Observation space: {self.observation_space}")
        logger.info(f"  Action space: {self.action_space}")

    def reset(self, seed: Optional[int] = None, options: Optional[Dict] = None) \
            -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        Reset environment to initial state.

        For inference-only mode, this is a no-op that returns zero observation.
        """
        super().reset(seed=seed)

        # Zero initial observation
        self._current_obs = np.zeros(self.feature_dim, dtype=np.float32)
        self._step_count = 0

        info = {
            "reset_type": "inference_init",
            "step": self._step_count
        }

        return self._current_obs, info

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        """
        Step environment with given action.

        For inference-only mode:
        - Returns current observation (unchanged)
        - Reward is always 0
        - Never done
        - Info contains action metadata
        """
        if not self.action_space.contains(action):
            raise ValueError(f"Invalid action {action}. Must be in {self.action_space}")

        if self._current_obs is None:
            self.reset()

        self._step_count += 1

        # Inference-only: no reward, no termination
        reward = 0.0
        terminated = False
        truncated = False

        info = {
            "action": action,
            "action_name": TradingAction.NAMES.get(action, "UNKNOWN"),
            "step": self._step_count,
            "mode": "inference_only"
        }

        return self._current_obs, reward, terminated, truncated, info

    def set_observation(self, obs: np.ndarray) -> None:
        """
        Set the current observation directly.

        Used by inference loop to feed unified features into environment.

        Args:
            obs: Observation array of shape (feature_dim,)
        """
        if obs.shape != (self.feature_dim,):
            raise ValueError(f"Expected obs shape {(self.feature_dim,)}, got {obs.shape}")

        self._current_obs = obs.astype(np.float32)

    def get_observation(self) -> np.ndarray:
        """Get current observation."""
        if self._current_obs is None:
            self.reset()
        return self._current_obs.copy()

    def render(self) -> None:
        """Render is not supported in inference-only mode."""
        pass

    def close(self) -> None:
        """Clean up environment resources."""
        pass


class FeatureNormalizer:
    """
    Normalize features to [-1, 1] range for neural network input.

    Maintains running statistics for robust normalization.
    """

    def __init__(self, feature_dim: int = 562, epsilon: float = 1e-8):
        """
        Initialize normalizer.

        Args:
            feature_dim: Number of features
            epsilon: Small constant for numerical stability
        """
        self.feature_dim = feature_dim
        self.epsilon = epsilon

        # Running statistics
        self.mean = np.zeros(feature_dim, dtype=np.float32)
        self.std = np.ones(feature_dim, dtype=np.float32)
        self.count = 0

    def update(self, batch: np.ndarray) -> None:
        """
        Update normalization statistics with a batch of features.

        Args:
            batch: Array of shape (batch_size, feature_dim) or (feature_dim,)
        """
        if batch.ndim == 1:
            batch = batch.reshape(1, -1)

        batch = batch.astype(np.float32)

        # Update running mean/std
        for feature in batch:
            self.count += 1
            delta = feature - self.mean
            self.mean += delta / self.count

            # Welford's online algorithm for std
            delta2 = feature - self.mean
            self.std = np.sqrt(
                ((self.count - 1) * self.std**2 + delta * delta2) / self.count + self.epsilon
            )

    def normalize(self, features: np.ndarray) -> np.ndarray:
        """
        Normalize features to approximately [-1, 1].

        Args:
            features: Array of shape (feature_dim,) or (batch_size, feature_dim)

        Returns:
            Normalized array
        """
        return (features - self.mean) / (self.std + self.epsilon)

    def denormalize(self, normalized: np.ndarray) -> np.ndarray:
        """Reverse normalization."""
        return normalized * (self.std + self.epsilon) + self.mean


if __name__ == "__main__":
    # Test environment
    env = V2TradingEnvironment()

    obs, info = env.reset()
    print(f"Initial obs shape: {obs.shape}")
    print(f"Observation space: {env.observation_space}")
    print(f"Action space: {env.action_space}")

    # Simulate some steps
    for i in range(5):
        action = env.action_space.sample()
        obs, reward, terminated, truncated, info = env.step(action)
        print(f"Step {i+1}: action={info['action_name']}, reward={reward}, obs_shape={obs.shape}")

    print("\n✅ Gymnasium environment working correctly")
