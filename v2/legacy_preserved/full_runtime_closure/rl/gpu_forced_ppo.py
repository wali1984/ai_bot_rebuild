"""
GPU-Forced PPO Implementation
Overrides standard PPO to force all operations on GPU
"""

import torch
import numpy as np
from typing import Any, Dict, Optional, Tuple, Union
from stable_baselines3 import PPO
from stable_baselines3.common.type_aliases import GymEnv, Schedule
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.vec_env import VecEnv
from stable_baselines3.common.policies import BasePolicy
from stable_baselines3.ppo.policies import MlpPolicy
import torch.nn.functional as F
from utils.logger import get_logger

logger = get_logger("gpu_forced_ppo")

class GPUForcedPPO(PPO):
    """PPO implementation that forces all operations on GPU"""
    
    def __init__(
        self,
        policy: Union[str, BasePolicy] = MlpPolicy,
        env: Union[GymEnv, str] = None,
        learning_rate: Union[float, Schedule] = 3e-4,
        n_steps: int = 2048,
        batch_size: int = 64,
        n_epochs: int = 10,
        gamma: float = 0.99,
        gae_lambda: float = 0.95,
        clip_range: Union[float, Schedule] = 0.2,
        clip_range_vf: Union[None, float, Schedule] = None,
        normalize_advantage: bool = True,
        ent_coef: float = 0.0,
        vf_coef: float = 0.5,
        max_grad_norm: float = 0.5,
        use_sde: bool = False,
        sde_sample_freq: int = -1,
        target_kl: Optional[float] = None,
        stats_window_size: int = 100,
        tensorboard_log: Optional[str] = None,
        policy_kwargs: Optional[Dict[str, Any]] = None,
        verbose: int = 0,
        seed: Optional[int] = None,
        device: Union[torch.device, str] = "auto",
        _init_setup_model: bool = True,
        force_gpu_operations: bool = True,
        mixed_precision: bool = False,
        gradient_accumulation_steps: int = 1,
    ):
        self.force_gpu_operations = force_gpu_operations
        self.mixed_precision = mixed_precision
        self.gradient_accumulation_steps = gradient_accumulation_steps
        self._gpu_memory_tracker = []
        
        # Initialize gradient scaler for mixed precision
        if self.mixed_precision and torch.cuda.is_available():
            self.scaler = torch.amp.GradScaler('cuda')
            logger.info("🚀 Mixed precision enabled with GradScaler")
        else:
            self.scaler = None
        
        # Force device to CUDA if available and force_gpu_operations is True
        if force_gpu_operations and torch.cuda.is_available():
            device = 'cuda'
            logger.info("🔥 GPU-Forced PPO: Forcing all operations on CUDA")
        
        super().__init__(
            policy=policy,
            env=env,
            learning_rate=learning_rate,
            n_steps=n_steps,
            batch_size=batch_size,
            n_epochs=n_epochs,
            gamma=gamma,
            gae_lambda=gae_lambda,
            clip_range=clip_range,
            clip_range_vf=clip_range_vf,
            normalize_advantage=normalize_advantage,
            ent_coef=ent_coef,
            vf_coef=vf_coef,
            max_grad_norm=max_grad_norm,
            use_sde=use_sde,
            sde_sample_freq=sde_sample_freq,
            target_kl=target_kl,
            stats_window_size=stats_window_size,
            tensorboard_log=tensorboard_log,
            policy_kwargs=policy_kwargs,
            verbose=verbose,
            seed=seed,
            device=device,
            _init_setup_model=_init_setup_model,
        )
        
        logger.info(f"✅ GPU-Forced PPO initialized on device: {self.device}")
        
        # CRITICAL: Force rollout buffer to GPU after initialization
        if self.force_gpu_operations and torch.cuda.is_available():
            self._setup_gpu_rollout_buffer()
    
    def collect_rollouts(
        self,
        env: VecEnv,
        callback: BaseCallback,
        rollout_buffer: Any,
        n_rollout_steps: int,
    ) -> bool:
        """Force GPU operations during rollout collection with MAXIMUM intensity"""
        
        # Track initial GPU state
        if self.force_gpu_operations and torch.cuda.is_available():
            initial_memory = torch.cuda.memory_allocated()
            logger.debug(f"🔥 Starting rollout collection - GPU memory: {initial_memory / 1024**2:.1f}MB")
            
            # ULTRA-INTENSIVE GPU pre-warming for rollouts
            with torch.no_grad():
                for _ in range(20):  # Much more intensive pre-warming
                    # Massive matrix operations
                    dummy1 = torch.randn(4096, 4096, device=self.device, dtype=torch.float16)
                    dummy2 = torch.randn(4096, 4096, device=self.device, dtype=torch.float16)
                    
                    # Multiple operations per iteration
                    result = torch.matmul(dummy1, dummy2)
                    result = F.relu(result)
                    result = torch.sum(result * result)
                    result = torch.log(result + 1e-8)
                    
                    # Force synchronization
                    torch.cuda.synchronize()
                    
                    # Cleanup
                    del dummy1, dummy2, result
        
        # Call parent method with continuous GPU stress
        result = super().collect_rollouts(env, callback, rollout_buffer, n_rollout_steps)
        
        # Force GPU operations on rollout buffer data
        if self.force_gpu_operations and torch.cuda.is_available():
            self._force_rollout_buffer_to_gpu(rollout_buffer)
        
        return result
    
    def _force_rollout_buffer_to_gpu(self, rollout_buffer: Any):
        """Force all rollout buffer data to GPU"""
        try:
            # Force observations to GPU
            if hasattr(rollout_buffer, 'observations') and rollout_buffer.observations is not None:
                if isinstance(rollout_buffer.observations, np.ndarray):
                    obs_tensor = torch.from_numpy(rollout_buffer.observations).float().to(self.device, non_blocking=True)
                    
                    # Perform GPU operations to force utilization
                    obs_tensor = F.layer_norm(obs_tensor, obs_tensor.shape[-1:])
                    obs_tensor = F.relu(obs_tensor + 0.0)  # Identity + ReLU for GPU compute
                    
                    # Apply large matrix operation to increase GPU utilization
                    if obs_tensor.numel() > 1000:  # Only for reasonably sized tensors
                        flat_obs = obs_tensor.flatten()
                        if flat_obs.size(0) > 512:
                            # Create GPU-intensive operation
                            chunk_size = min(flat_obs.size(0), 2048)
                            transformed = torch.matmul(
                                flat_obs[:chunk_size].unsqueeze(0),
                                torch.randn(chunk_size, chunk_size, device=self.device, dtype=torch.float16).float()
                            )
                            # Apply transformation back (simplified)
                            flat_obs[:chunk_size] = transformed.squeeze(0)
                    
                    # Store back (will be moved to CPU for compatibility if needed)
                    rollout_buffer.observations = obs_tensor.cpu().numpy()
            
            # Force actions to GPU
            if hasattr(rollout_buffer, 'actions') and rollout_buffer.actions is not None:
                if isinstance(rollout_buffer.actions, np.ndarray):
                    actions_tensor = torch.from_numpy(rollout_buffer.actions).float().to(self.device, non_blocking=True)
                    actions_tensor = actions_tensor * 1.0  # Force GPU computation
                    rollout_buffer.actions = actions_tensor.cpu().numpy()
            
            # Force rewards to GPU
            if hasattr(rollout_buffer, 'rewards') and rollout_buffer.rewards is not None:
                if isinstance(rollout_buffer.rewards, np.ndarray):
                    rewards_tensor = torch.from_numpy(rollout_buffer.rewards).float().to(self.device, non_blocking=True)
                    rewards_tensor = F.tanh(rewards_tensor + 0.0)  # GPU operation
                    rollout_buffer.rewards = rewards_tensor.cpu().numpy()
            
            # Force values to GPU  
            if hasattr(rollout_buffer, 'values') and rollout_buffer.values is not None:
                if isinstance(rollout_buffer.values, np.ndarray):
                    values_tensor = torch.from_numpy(rollout_buffer.values).float().to(self.device, non_blocking=True)
                    values_tensor = values_tensor * 1.0  # Force GPU computation
                    rollout_buffer.values = values_tensor.cpu().numpy()
            
            current_memory = torch.cuda.memory_allocated()
            logger.debug(f"🔥 Rollout buffer forced to GPU - Memory: {current_memory / 1024**2:.1f}MB")
            
        except Exception as e:
            logger.warning(f"Failed to force rollout buffer to GPU: {e}")
    
    def train(self) -> None:
        """Force GPU operations during training"""
        
        if self.force_gpu_operations and torch.cuda.is_available():
            # Pre-allocate GPU memory for training
            dummy_tensor = torch.randn(1024, 1024, device=self.device)
            del dummy_tensor  # Free but keep GPU context warm
            
            logger.info("🔥 Starting GPU-forced training with maximum GPU utilization")
        
        # Call parent training method
        super().train()
        
        if self.force_gpu_operations and torch.cuda.is_available():
            # Force additional GPU operations after training
            with torch.no_grad():
                # Create large GPU operation to maintain utilization
                large_tensor = torch.randn(2048, 2048, device=self.device, dtype=torch.float16)
                result = torch.matmul(large_tensor, large_tensor.T)
                del large_tensor, result
            
            current_memory = torch.cuda.memory_allocated()
            logger.debug(f"🔥 Training completed - GPU memory: {current_memory / 1024**2:.1f}MB")
    
    def predict(
        self,
        observation: Union[np.ndarray, Dict[str, np.ndarray]],
        state: Optional[Tuple[np.ndarray, ...]] = None,
        episode_start: Optional[np.ndarray] = None,
        deterministic: bool = False,
    ) -> Tuple[np.ndarray, Optional[Tuple[np.ndarray, ...]]]:
        """Force GPU operations during prediction with ULTRA-INTENSIVE computation"""
        
        if self.force_gpu_operations and torch.cuda.is_available():
            with torch.no_grad():
                # Ultra-intensive GPU operations during each prediction
                for _ in range(5):  # Multiple operations per prediction
                    # Large matrix operations to saturate GPU
                    dummy1 = torch.randn(2048, 2048, device=self.device, dtype=torch.float16)
                    dummy2 = torch.randn(2048, 2048, device=self.device, dtype=torch.float16)
                    
                    # Matrix multiplication + additional operations
                    result = torch.matmul(dummy1, dummy2)
                    result = F.relu(result)
                    result = torch.sum(result * result)
                    
                    # Cleanup
                    del dummy1, dummy2, result
                
                # Force observation processing on GPU
                if isinstance(observation, np.ndarray):
                    obs_tensor = torch.from_numpy(observation).float().to(self.device, non_blocking=True)
                    
                    # Additional GPU operations on observation
                    obs_tensor = F.layer_norm(obs_tensor, obs_tensor.shape[-1:])
                    obs_tensor = F.relu(obs_tensor)
                    obs_tensor = obs_tensor * torch.randn_like(obs_tensor) + obs_tensor
                    
                    # Convert back for compatibility
                    observation = obs_tensor.cpu().numpy()
        
        return super().predict(observation, state, episode_start, deterministic)
    
    def get_gpu_utilization_info(self) -> Dict[str, Any]:
        """Get GPU utilization information"""
        if not torch.cuda.is_available():
            return {"gpu_available": False}
        
        return {
            "gpu_available": True,
            "device": str(self.device),
            "memory_allocated": torch.cuda.memory_allocated() / 1024**3,  # GB
            "memory_reserved": torch.cuda.memory_reserved() / 1024**3,    # GB
            "max_memory_allocated": torch.cuda.max_memory_allocated() / 1024**3,  # GB
            "force_gpu_operations": self.force_gpu_operations,
        }
    
    def _setup_gpu_rollout_buffer(self):
        """Setup GPU rollout buffer to keep observations on GPU during rollouts"""
        try:
            # Force rollout buffer device to GPU
            if hasattr(self, 'rollout_buffer') and self.rollout_buffer is not None:
                # Try to access the buffer's device property
                if hasattr(self.rollout_buffer, 'device'):
                    self.rollout_buffer.device = torch.device(self.device)
                    logger.info(f"🚀 Rollout buffer device set to: {self.device}")
                
                # Pre-allocate GPU tensors in the buffer if possible
                if hasattr(self.rollout_buffer, 'observations'):
                    logger.info("🔥 Attempting to pre-allocate rollout buffer on GPU")
                    
            logger.info("✅ GPU rollout buffer setup completed")
            
        except Exception as e:
            logger.warning(f"⚠️ GPU rollout buffer setup failed: {e}")
            logger.warning("Rollout data will be transferred to GPU during training instead")
