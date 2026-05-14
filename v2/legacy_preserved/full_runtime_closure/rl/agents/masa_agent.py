"""
MASA (Multi-Agent System Architecture) Agent for AI Trading Bot
Optimized for RTX 5080 maximum GPU utilization

This implementation provides:
- MASAAgent: GPU-optimized neural architecture
- MASAConfig: Configuration for MASA parameters
- HybridPPO: Custom PPO implementation for hybrid training
- DualHeadActorCriticPolicy: Policy with separate actor/critic heads
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import os
from typing import Dict, Any, Optional, Tuple, Union
from stable_baselines3 import PPO
from stable_baselines3.common.policies import ActorCriticPolicy
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor
from stable_baselines3.common.type_aliases import Schedule
from gymnasium import spaces
import logging

logger = logging.getLogger(__name__)


class MASAConfig:
    """Configuration for MASA Agent"""
    
    def __init__(
        self,
        obs_dim: int,
        act_dim: int,
        hidden_size: int = 1024,
        num_layers: int = 3,
        dropout: float = 0.1,
        activation: str = 'relu',
        use_layer_norm: bool = True,
        use_residual: bool = True
    ):
        self.obs_dim = obs_dim
        self.act_dim = act_dim
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout
        self.activation = activation
        self.use_layer_norm = use_layer_norm
        self.use_residual = use_residual


class _ResidualBlock(nn.Module):
    """Pre-norm residual block: LayerNorm -> Linear -> Activation -> Dropout + skip."""
    def __init__(self, dim: int, dropout: float = 0.1):
        super().__init__()
        self.norm = nn.LayerNorm(dim)
        self.fc = nn.Linear(dim, dim)
        self.act = nn.ReLU(inplace=True)
        self.drop = nn.Dropout(dropout) if dropout > 0 else nn.Identity()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.drop(self.act(self.fc(self.norm(x))))


class GPUOptimizedMASANetwork(nn.Module):
    """GPU-optimized neural network for MASA agent with residual connections."""

    def __init__(self, config: MASAConfig):
        super().__init__()
        self.config = config

        self._input_projection = None
        self._adapted_obs_dim = config.obs_dim

        self.input_proj = nn.Sequential(
            nn.Linear(config.obs_dim, config.hidden_size),
            nn.LayerNorm(config.hidden_size),
            nn.ReLU(inplace=True),
        )

        self.res_blocks = nn.Sequential(
            *[_ResidualBlock(config.hidden_size, config.dropout)
              for _ in range(config.num_layers)]
        )

        self.action_head = nn.Linear(config.hidden_size, config.act_dim)
        self.value_head = nn.Linear(config.hidden_size, 1)

        self._initialize_weights()
    
    def adapt_input_dim(self, new_obs_dim: int) -> bool:
        """
        Dynamically adapt the network to handle a different observation dimension.
        Creates a projection layer to map new_obs_dim -> config.obs_dim.
        
        Returns True if adaptation was performed, False if no adaptation needed.
        """
        if new_obs_dim == self.config.obs_dim:
            return False
        
        # Create projection layer to map new dimension to expected dimension
        device = next(self.parameters()).device
        self._input_projection = nn.Linear(new_obs_dim, self.config.obs_dim, bias=True).to(device)
        
        # Initialize with identity-like mapping for stability
        with torch.no_grad():
            nn.init.eye_(self._input_projection.weight[:, :min(new_obs_dim, self.config.obs_dim)])
            nn.init.zeros_(self._input_projection.bias)
        
        self._adapted_obs_dim = new_obs_dim
        logger.info(f"🔧 [MASA] Adapted input dimension: {new_obs_dim} -> {self.config.obs_dim} via projection layer")
        return True
    
    def _initialize_weights(self):
        """Initialize weights for optimal GPU performance"""
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)
    
    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """Forward pass optimized for GPU with dynamic dimension adaptation"""
        device = next(self.parameters()).device
        if x.device != device:
            x = x.to(device, non_blocking=True)
        x = x.float()
        
        actual_dim = x.shape[-1]
        expected_dim = self.config.obs_dim
        
        if actual_dim != expected_dim:
            if not hasattr(self, '_input_projection'):
                self._input_projection = None
            if not hasattr(self, '_adapted_obs_dim'):
                self._adapted_obs_dim = self.config.obs_dim
            
            if self._input_projection is None or self._adapted_obs_dim != actual_dim:
                self.adapt_input_dim(actual_dim)
            
            if self._input_projection is not None:
                x = self._input_projection(x)
        
        features = self.input_proj(x)
        features = self.res_blocks(features)

        raw_logits = self.action_head(features)
        action_logits = torch.clamp(raw_logits, -6.0, 6.0)
        value = self.value_head(features)

        return action_logits, value, raw_logits


class MASAAgent:
    """MASA Agent with GPU optimization for RTX 5080"""
    
    def __init__(self, config: MASAConfig, device: torch.device, amp: bool = True):
        self.config = config
        self.device = device
        self.amp = amp  # Automatic Mixed Precision
        
        # Create the neural network
        self.model = GPUOptimizedMASANetwork(config).to(device)
        self._device = next(self.model.parameters()).device
        
        # Enable mixed precision for RTX 5080 optimization
        if amp:
            self.scaler = torch.amp.GradScaler('cuda')
        else:
            self.scaler = None
        
        # Optimizer — lower LR (3e-4) prevents rapid logit explosion that caused
        # repeated entropy collapse at 1e-3. Weight decay acts as global L2.
        self.optimizer = torch.optim.AdamW(
            self.model.parameters(),
            lr=3e-4,
            weight_decay=1e-3,
            eps=1e-7
        )
        
        # Scheduler — slow decay so MASA has time to learn
        self.scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(
            self.optimizer, T_max=50000, eta_min=1e-5
        )
        
        logger.info(f"✅ MASA Agent initialized on {device} with AMP={amp}")
        logger.info(f"   Network parameters: {sum(p.numel() for p in self.model.parameters()):,}")
    
    def get_action_and_value(self, obs: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, bool]:
        """Get action logits, value, and validity flag with FP32-only, NaN-safe forward."""
        self.model.eval()
        device = getattr(self, "_device", self.device)

        def _sanitize(x: torch.Tensor, clamp: float = 10.0) -> torch.Tensor:
            x = torch.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
            if clamp is not None:
                x = torch.clamp(x, -clamp, clamp)
            return x

        def _forward(xx: torch.Tensor, amp_enabled: bool):
            # torch.inference_mode is faster than no_grad and reduces overhead in live prediction loops
            with torch.inference_mode():
                if amp_enabled and xx.is_cuda:
                    with torch.amp.autocast('cuda', enabled=True):
                        return self.model(xx)
                # FP32 fallback (always safe)
                with torch.amp.autocast('cuda', enabled=False):
                    return self.model(xx.float())

        obs = obs.to(device, non_blocking=True)
        obs = _sanitize(obs, clamp=10.0)

        # Dimension adaptation: dynamically handle obs_dim mismatches via projection layer
        expected_dim = getattr(self.model.config, "obs_dim", None)
        actual_dim = obs.shape[-1]
        if expected_dim is not None and actual_dim != expected_dim:
            # The model.forward() will handle adaptation via projection layer
            # Log only once per unique dimension change
            if not hasattr(self, '_last_adapted_dim') or self._last_adapted_dim != actual_dim:
                logger.info(
                    f"[MASA_ADAPT] obs_dim adapted: {actual_dim} -> {expected_dim} via projection layer"
                )
                self._last_adapted_dim = actual_dim

        # AMP inference is optional (default ON) with FP32 fallback if outputs go invalid.
        amp_infer = (
            bool(getattr(self, "amp", False))
            and obs.is_cuda
            and os.getenv("MASA_INFER_AMP", "1") == "1"
        )
        action_logits, value, _raw = _forward(obs, amp_enabled=amp_infer)

        def _is_finite(*tensors) -> bool:
            return all(torch.isfinite(t).all().item() for t in tensors)

        if not _is_finite(action_logits, value):
            # Retry once more in strict FP32
            action_logits, value, _raw = _forward(obs, amp_enabled=False)

        if not _is_finite(action_logits, value):
            # If still invalid, return safe zeros but keep MASA path active
            action_logits = torch.zeros((obs.shape[0], self.model.config.act_dim), device=device)
            value = torch.zeros((obs.shape[0], 1), device=device)
            is_valid = False
        else:
            is_valid = True

        # Final sanitize to guarantee finite outputs and reject collapsed logits
        action_logits = torch.nan_to_num(action_logits, nan=0.0, posinf=0.0, neginf=0.0)
        value = torch.nan_to_num(value, nan=0.0, posinf=0.0, neginf=0.0)

        # Clamp to reasonable range
        action_logits = torch.clamp(action_logits, -20.0, 20.0)

        try:
            if action_logits.shape[0] > 1:
                batch_var = float(action_logits.std(dim=0).mean().item())
            else:
                batch_var = float(action_logits.std().item())
            if batch_var < 1e-7:
                logger.warning(f"[MASA] Truly degenerate logits (batch_var={batch_var:.2e})")
                action_logits = torch.zeros_like(action_logits)
                is_valid = False
        except Exception:
            is_valid = False

        return action_logits, value, is_valid
    
    def update(self, obs: torch.Tensor, actions: torch.Tensor, 
               returns: torch.Tensor, advantages: torch.Tensor) -> Dict[str, float]:
        """Update the MASA model with GPU optimization"""
        self.model.train()
        
        obs = obs.to(self.device, non_blocking=True)
        actions = actions.to(self.device, non_blocking=True)
        returns = returns.to(self.device, non_blocking=True)
        advantages = advantages.to(self.device, non_blocking=True)
        
        # --- Anti-collapse coefficients ---
        # Entropy bonus: encourages exploration like PPO's ent_coef.
        # Without this, the policy gradient has no counter-pressure and logits
        # diverge to one action → entropy→0 within ~6 updates.
        _entropy_coeff = 0.10
        # L2 on raw logits: prevents logit magnitude explosion.
        _logit_l2_coeff = 0.10
        # Value loss coefficient (same as PPO default).
        _vf_coeff = 0.5

        def _compute_loss(action_logits, values, raw_logits):
            action_log_probs = F.log_softmax(action_logits, dim=-1)
            selected_log_probs = action_log_probs.gather(1, actions.unsqueeze(1)).squeeze(1)
            
            policy_loss = -(selected_log_probs * advantages).mean()
            value_loss = F.mse_loss(values.squeeze(1), returns)
            logit_l2 = raw_logits.pow(2).mean()
            
            probs = F.softmax(action_logits, dim=-1)
            entropy = -(probs * action_log_probs).sum(dim=-1).mean()
            
            total_loss = (policy_loss
                          + _vf_coeff * value_loss
                          + _logit_l2_coeff * logit_l2
                          - _entropy_coeff * entropy)  # subtract because we MAXIMIZE entropy
            return policy_loss, value_loss, logit_l2, entropy, total_loss

        if self.amp:
            with torch.amp.autocast('cuda'):
                action_logits, values, raw_logits = self.model(obs)
                policy_loss, value_loss, logit_l2, entropy, total_loss = _compute_loss(
                    action_logits, values, raw_logits)
            
            self.optimizer.zero_grad()
            self.scaler.scale(total_loss).backward()
            self.scaler.unscale_(self.optimizer)
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=0.5)
            self.scaler.step(self.optimizer)
            self.scaler.update()
        else:
            action_logits, values, raw_logits = self.model(obs)
            policy_loss, value_loss, logit_l2, entropy, total_loss = _compute_loss(
                action_logits, values, raw_logits)
            
            self.optimizer.zero_grad()
            total_loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=0.5)
            self.optimizer.step()
        
        _l2_val = logit_l2.item()
        _ent_val = entropy.item()
        _std_val = raw_logits.std(dim=-1).mean().item()
        if _l2_val > 150 or _ent_val < 0.15 or (_ent_val < 0.30 and _l2_val > 30) or _std_val > 5.0:
            logger.warning(
                "[MASA_AUTO_RESET] logit_l2=%.1f entropy=%.4f logit_std=%.1f — reinitializing to prevent permanent collapse",
                _l2_val, _ent_val, _std_val,
            )
            self.model._initialize_weights()
            for group in self.optimizer.param_groups:
                group['lr'] = 3e-4
            self.optimizer.state.clear()
        
        self.scheduler.step()
        
        with torch.no_grad():
            logit_std = raw_logits.std(dim=-1).mean()
        
        metrics = {
            'policy_loss': policy_loss.item(),
            'value_loss': value_loss.item(),
            'logit_l2': _l2_val,
            'total_loss': total_loss.item(),
            'entropy': _ent_val,
            'logit_std': logit_std.item(),
            'learning_rate': self.scheduler.get_last_lr()[0]
        }
        
        logger.info(
            "[MASA_TRAIN] policy=%.4f value=%.4f logit_l2=%.4f total=%.4f entropy=%.3f logit_std=%.4f lr=%.2e",
            metrics['policy_loss'], metrics['value_loss'], metrics['logit_l2'],
            metrics['total_loss'], metrics['entropy'], metrics['logit_std'],
            metrics['learning_rate']
        )
        
        return metrics


class GPUOptimizedFeatureExtractor(BaseFeaturesExtractor):
    """GPU-optimized feature extractor for DualHeadActorCriticPolicy"""
    
    def __init__(self, observation_space: spaces.Space, features_dim: int = 512):
        super().__init__(observation_space, features_dim)
        
        # Calculate input dimension
        if isinstance(observation_space, spaces.Box):
            input_dim = int(np.prod(observation_space.shape))
        else:
            input_dim = observation_space.n
        
        # GPU-optimized feature extraction network
        self.features_extractor = nn.Sequential(
            nn.Linear(input_dim, features_dim * 2),
            nn.LayerNorm(features_dim * 2),
            nn.ReLU(inplace=True),
            nn.Dropout(0.1),
            
            nn.Linear(features_dim * 2, features_dim),
            nn.LayerNorm(features_dim),
            nn.ReLU(inplace=True),
            nn.Dropout(0.1),
            
            nn.Linear(features_dim, features_dim),
            nn.LayerNorm(features_dim),
            nn.ReLU(inplace=True)
        )
        
        # Initialize weights
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)
    
    def forward(self, observations: torch.Tensor) -> torch.Tensor:
        """Extract features with GPU optimization"""
        # Ensure tensor is on the correct device and dtype (CPU-safe)
        device = next(self.parameters()).device
        if observations.device != device:
            observations = observations.to(device, non_blocking=True)
        observations = observations.float()
        
        # Flatten if needed
        if len(observations.shape) > 2:
            observations = observations.flatten(start_dim=1)
        
        # Clone tensor to prevent CUDAGraph overwriting issues
        observations_safe = observations.clone().detach()
        return self.features_extractor(observations_safe)


class DualHeadActorCriticPolicy(ActorCriticPolicy):
    """Dual-head Actor-Critic policy optimized for RTX 5080"""
    
    def __init__(self, observation_space: spaces.Space, action_space: spaces.Space, 
                 lr_schedule: Schedule, *args, **kwargs):
        
        # Set GPU-optimized policy kwargs
        kwargs['features_extractor_class'] = GPUOptimizedFeatureExtractor
        kwargs['features_extractor_kwargs'] = {'features_dim': 512}
        
        # Network architecture
        kwargs['net_arch'] = {
            'pi': [512, 256, 128],  # Policy network
            'vf': [512, 256, 128]   # Value function network
        }
        
        # Activation function
        kwargs['activation_fn'] = nn.ReLU
        
        super().__init__(observation_space, action_space, lr_schedule, *args, **kwargs)
        
        # Enable mixed precision
        self.use_amp = True
        if self.use_amp:
            self.scaler = torch.amp.GradScaler('cuda')
    
    def forward(self, obs: torch.Tensor, deterministic: bool = False) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Forward pass with mixed precision support"""
        if self.use_amp and obs.is_cuda:
            with torch.amp.autocast('cuda', enabled=True):
                return super().forward(obs, deterministic)
        return super().forward(obs, deterministic)


class HybridPPO(PPO):
    """Hybrid PPO implementation optimized for GPU training"""
    
    def __init__(self, *args, **kwargs):
        # Force CUDA device if available
        if torch.cuda.is_available():
            kwargs['device'] = 'cuda'
        
        # GPU optimization settings
        kwargs['policy_kwargs'] = kwargs.get('policy_kwargs', {})
        kwargs['policy_kwargs']['optimizer_class'] = torch.optim.AdamW
        kwargs['policy_kwargs']['optimizer_kwargs'] = {
            'eps': 1e-7,
            'weight_decay': 1e-4
        }
        
        super().__init__(*args, **kwargs)
        
        # Enable mixed precision training
        self.use_amp = True
        if self.use_amp:
            self.scaler = torch.amp.GradScaler('cuda')
        
        # Set TF32 for RTX 5080 optimization
        if torch.cuda.is_available():
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            torch.backends.cudnn.benchmark = True
            torch.set_float32_matmul_precision('high')
        
        logger.info("✅ HybridPPO initialized with GPU optimizations")
        logger.info(f"   Device: {self.device}")
        logger.info(f"   Mixed precision: {self.use_amp}")
        logger.info(f"   TF32 enabled: {torch.backends.cuda.matmul.allow_tf32}")
    
    def train(self) -> None:
        """Override train method to use mixed precision"""
        if self.use_amp:
            # Store original train method
            original_train = super().train
            
            # Wrap in autocast
            def amp_train():
                with torch.amp.autocast('cuda', enabled=torch.cuda.is_available()):
                    return original_train()
            
            return amp_train()
        else:
            return super().train()
    
    def predict(self, observation: Union[np.ndarray, torch.Tensor], 
                state: Optional[Tuple[np.ndarray, ...]] = None, 
                episode_start: Optional[np.ndarray] = None, 
                deterministic: bool = False) -> Tuple[np.ndarray, Optional[Tuple[np.ndarray, ...]]]:
        """Predict with GPU optimization"""
        # Ensure observation is on CUDA
        if isinstance(observation, np.ndarray):
            observation = torch.from_numpy(observation).cuda()
        elif isinstance(observation, torch.Tensor) and not observation.is_cuda:
            observation = observation.cuda()
        
        if self.use_amp:
            with torch.amp.autocast('cuda'):
                with torch.no_grad():
                    return super().predict(observation.cpu().numpy(), state, episode_start, deterministic)
        else:
            with torch.no_grad():
                return super().predict(observation.cpu().numpy(), state, episode_start, deterministic)
