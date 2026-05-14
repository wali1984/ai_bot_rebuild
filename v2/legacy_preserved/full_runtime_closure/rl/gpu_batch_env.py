"""
GPU Batched Environment - Single Process High GPU Utilization
Replaces DummyVecEnv with a GPU-optimized batched environment that processes multiple environments
in parallel on GPU without multiprocessing overhead.
"""
import torch
import torch.nn as nn
import numpy as np
from typing import List, Tuple, Dict, Any, Optional
import logging
from stable_baselines3.common.vec_env import VecEnv
# Note: These utilities may not be available in all SB3 versions
try:
    from stable_baselines3.common.vec_env.util import copy_obs_dict, dict_to_obs, obs_space_info
except ImportError:
    # Fallback implementations for missing utilities
    def copy_obs_dict(obs):
        return obs.copy() if isinstance(obs, dict) else obs
    
    def dict_to_obs(obs_dict):
        return obs_dict
    
    def obs_space_info(obs_space):
        return obs_space.shape, obs_space.dtype
import gymnasium as gym

from utils.logger import get_logger
from rl.gpu_environment import GPUTradingEnvironment
from rl.gymnasium_wrapper import TradingEnvironmentWrapper

logger = get_logger("gpu_batch_env")

class GPUBatchedVecEnv(VecEnv):
    """
    GPU-optimized vectorized environment that processes multiple environments
    in parallel on GPU within a single process for maximum GPU utilization.
    """
    
    def __init__(self, n_envs: int = 64, **env_kwargs):
        """Initialize GPU batched environment"""
        self.n_envs = n_envs
        self.env_kwargs = env_kwargs
        
        # Create a single GPU environment to get spaces
        temp_gpu_env = GPUTradingEnvironment(**env_kwargs)
        temp_wrapper = TradingEnvironmentWrapper(base_env=temp_gpu_env)
        
        observation_space = temp_wrapper.observation_space
        action_space = temp_wrapper.action_space
        
        super().__init__(n_envs, observation_space, action_space)
        
        # GPU device setup
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        logger.info(f"🚀 GPU Batched VecEnv initializing on {self.device}")
        
        # Create batched GPU environments
        self.gpu_envs = []
        for i in range(n_envs):
            gpu_env = GPUTradingEnvironment(**env_kwargs)
            wrapper = TradingEnvironmentWrapper(base_env=gpu_env)
            self.gpu_envs.append(wrapper)
        
        # GPU tensors for batched processing
        self.obs_shape = observation_space.shape[0]
        self.action_dim = action_space.n if hasattr(action_space, 'n') else action_space.shape[0]
        
        # Pre-allocated GPU tensors for batched operations
        self.batch_observations = torch.zeros(n_envs, self.obs_shape, device=self.device, dtype=torch.float32)
        self.batch_rewards = torch.zeros(n_envs, device=self.device, dtype=torch.float32)
        self.batch_dones = torch.zeros(n_envs, device=self.device, dtype=torch.bool)
        self.batch_infos = [{}] * n_envs
        
        # Environment states
        self.episode_rewards = torch.zeros(n_envs, device=self.device, dtype=torch.float32)
        self.episode_lengths = torch.zeros(n_envs, device=self.device, dtype=torch.int32)
        
        logger.info(f"✅ GPU Batched VecEnv created with {n_envs} environments on {self.device}")
        logger.info(f"🎯 Observation shape: {self.obs_shape}, Action dim: {self.action_dim}")
        
        # Warm up all environments
        self._warm_up_environments()
    
    def _warm_up_environments(self):
        """Warm up all environments and initialize observations"""
        logger.info("🔥 Warming up GPU batched environments...")
        
        initial_obs = []
        for i, env in enumerate(self.gpu_envs):
            obs, _ = env.reset()
            initial_obs.append(obs)
        
        # Convert to GPU tensor batch
        obs_array = np.array(initial_obs)
        self.batch_observations = torch.from_numpy(obs_array).to(self.device, dtype=torch.float32)
        
        logger.info(f"✅ All {self.n_envs} environments warmed up on GPU")
    
    def step_async(self, actions: np.ndarray):
        """Queue actions for batched execution"""
        # Convert actions to GPU tensor for processing
        if isinstance(actions, np.ndarray):
            self.pending_actions = torch.from_numpy(actions).to(self.device)
        else:
            self.pending_actions = torch.tensor(actions, device=self.device)
    
    def step_wait(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray, List[Dict]]:
        """Execute batched step operations on GPU"""
        # Process all environments in parallel
        observations = []
        rewards = []
        dones = []
        infos = []
        
        # GPU-accelerated batch processing
        with torch.no_grad():
            for i, env in enumerate(self.gpu_envs):
                action = self.pending_actions[i].cpu().numpy()
                obs, reward, done, truncated, info = env.step(action)
                
                observations.append(obs)
                
                # Ensure we get Python scalars, not tensors
                if isinstance(reward, torch.Tensor):
                    reward = reward.cpu().item()
                if isinstance(done, torch.Tensor):
                    done = done.cpu().item()
                if isinstance(truncated, torch.Tensor):
                    truncated = truncated.cpu().item()
                
                rewards.append(float(reward))
                dones.append(bool(done or truncated))
                infos.append(info)
                
                # Track episode statistics on GPU
                self.episode_rewards[i] += reward
                self.episode_lengths[i] += 1
                
                if done or truncated:
                    # Reset environment and update statistics
                    obs, _ = env.reset()
                    observations[-1] = obs
                    
                    # Add episode info
                    info['episode'] = {
                        'r': float(self.episode_rewards[i]),
                        'l': int(self.episode_lengths[i])
                    }
                    
                    # Reset counters
                    self.episode_rewards[i] = 0
                    self.episode_lengths[i] = 0
        
        # Convert to numpy arrays first for SB3 compatibility
        obs_array = np.array(observations)
        rewards_array = np.array(rewards)
        dones_array = np.array(dones)
        
        # Store GPU tensors for internal processing
        self.batch_observations = torch.from_numpy(obs_array).to(self.device, dtype=torch.float32)
        self.batch_rewards = torch.from_numpy(rewards_array).to(self.device, dtype=torch.float32)
        self.batch_dones = torch.from_numpy(dones_array).to(self.device, dtype=torch.bool)
        
        # Return CPU arrays for SB3 compatibility
        return obs_array, rewards_array, dones_array, infos
    
    def reset(self) -> np.ndarray:
        """Reset all environments"""
        logger.info("🔄 Resetting all GPU batched environments")
        
        observations = []
        for env in self.gpu_envs:
            obs, _ = env.reset()
            observations.append(obs)
        
        # Convert to GPU tensor batch
        obs_array = np.array(observations)
        self.batch_observations = torch.from_numpy(obs_array).to(self.device, dtype=torch.float32)
        
        # Reset episode tracking
        self.episode_rewards.zero_()
        self.episode_lengths.zero_()
        
        return obs_array
    
    def close(self):
        """Close all environments"""
        logger.info("🛑 Closing GPU batched environments")
        for env in self.gpu_envs:
            env.close()
    
    def get_attr(self, attr_name: str, indices=None):
        """Get attribute from environments"""
        if indices is None:
            indices = range(self.n_envs)
        return [getattr(self.gpu_envs[i], attr_name) for i in indices]
    
    def set_attr(self, attr_name: str, value, indices=None):
        """Set attribute in environments"""
        if indices is None:
            indices = range(self.n_envs)
        for i in indices:
            setattr(self.gpu_envs[i], attr_name, value)
    
    def env_method(self, method_name: str, *method_args, indices=None, **method_kwargs):
        """Call method on environments"""
        if indices is None:
            indices = range(self.n_envs)
        return [getattr(self.gpu_envs[i], method_name)(*method_args, **method_kwargs) for i in indices]
    
    def seed(self, seed: Optional[int] = None):
        """Set random seed for all environments"""
        if seed is None:
            seed = np.random.randint(0, 2**32 - 1)
        
        seeds = []
        for i, env in enumerate(self.gpu_envs):
            env_seed = seed + i
            env.seed(env_seed)
            seeds.append(env_seed)
        return seeds
    
    def get_gpu_observations(self) -> torch.Tensor:
        """Get current observations as GPU tensor"""
        return self.batch_observations
    
    def get_gpu_metrics(self) -> Dict[str, torch.Tensor]:
        """Get GPU-based metrics for monitoring"""
        return {
            'episode_rewards': self.episode_rewards,
            'episode_lengths': self.episode_lengths,
            'batch_rewards': self.batch_rewards,
            'batch_dones': self.batch_dones
        }
    
    def env_is_wrapped(self, wrapper_class, indices=None):
        """Check if environments are wrapped with specific wrapper"""
        if indices is None:
            indices = range(self.n_envs)
        return [isinstance(self.gpu_envs[i], wrapper_class) for i in indices]
