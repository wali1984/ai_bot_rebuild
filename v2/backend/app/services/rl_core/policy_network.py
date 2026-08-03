"""
Policy Network - Lightweight inference-only PPO policy

Extracted from legacy hybrid_trainer.py (57k lines) and simplified for V2.
- Loads legacy PyTorch checkpoints
- Inference-only (no training loops)
- Compatible with 562-dim observations
- Outputs action logits + value estimate
"""

import torch
import torch.nn as nn
from typing import Tuple, Optional, Dict, Any
import logging
import math

logger = logging.getLogger(__name__)


class SimpleFeatureExtractor(nn.Module):
    """
    Simplified feature extractor (legacy: RTX5080FeatureExtractor).

    Converts 562-dim features → 512-dim learned representation.
    Uses shallow MLP instead of CNN for inference speed.
    """

    def __init__(self, input_dim: int = 562, hidden_dim: int = 2048, output_dim: int = 512):
        """
        Initialize feature extractor.

        Args:
            input_dim: Input feature dimension (default 562)
            hidden_dim: Hidden layer dimension
            output_dim: Output feature dimension
        """
        super().__init__()

        self.input_dim = input_dim
        self.output_dim = output_dim

        # Simple MLP (faster than CNN for 562 dims)
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(inplace=True),
            nn.BatchNorm1d(hidden_dim),
            nn.Dropout(0.2),

            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(inplace=True),
            nn.BatchNorm1d(hidden_dim),
            nn.Dropout(0.2),

            nn.Linear(hidden_dim, output_dim),
            nn.ReLU(inplace=True),
        )

        self._init_weights()

    def _init_weights(self):
        """Initialize weights with Kaiming initialization."""
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
                if m.bias is not None:
                    nn.init.constant_(m.bias, 0)
            elif isinstance(m, nn.BatchNorm1d):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)

    def forward(self, observations: torch.Tensor) -> torch.Tensor:
        """
        Extract features from observations.

        Args:
            observations: Tensor of shape (batch_size, input_dim)

        Returns:
            Tensor of shape (batch_size, output_dim)
        """
        return self.net(observations)


class PolicyNetwork(nn.Module):
    """
    Actor-Critic policy network with separate actor and critic heads.

    Architecture:
    - Input: 562-dim observation vector
    - Shared feature extraction: 512-dim learned representation
    - Actor head: outputs action logits (5 actions)
    - Critic head: outputs value estimate (scalar)
    """

    def __init__(self,
                 input_dim: int = 562,
                 hidden_dim: int = 2048,
                 feature_dim: int = 512,
                 num_actions: int = 5,
                 device: str = "cpu"):
        """
        Initialize policy network.

        Args:
            input_dim: Input feature dimension (default 562)
            hidden_dim: Hidden layer dimension
            feature_dim: Learned feature dimension
            num_actions: Number of discrete actions (default 5)
            device: PyTorch device (cpu or cuda)
        """
        super().__init__()

        self.input_dim = input_dim
        self.num_actions = num_actions
        self.device = torch.device(device)

        # Shared feature extractor
        self.feature_extractor = SimpleFeatureExtractor(
            input_dim=input_dim,
            hidden_dim=hidden_dim,
            output_dim=feature_dim
        )

        # Actor head (outputs action logits)
        self.actor = nn.Sequential(
            nn.Linear(feature_dim, 256),
            nn.ReLU(inplace=True),
            nn.Linear(256, num_actions),  # Logits for each action
        )

        # Critic head (outputs value scalar)
        self.critic = nn.Sequential(
            nn.Linear(feature_dim, 256),
            nn.ReLU(inplace=True),
            nn.Linear(256, 1),  # Single value estimate
        )

        self.to(self.device)
        self._init_weights()

    def _init_weights(self):
        """Initialize actor and critic heads."""
        for module in [self.actor, self.critic]:
            for m in module.modules():
                if isinstance(m, nn.Linear):
                    nn.init.orthogonal_(m.weight, gain=math.sqrt(2))
                    nn.init.constant_(m.bias, 0)

    def forward(self, observations: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Forward pass through policy.

        Args:
            observations: Tensor of shape (batch_size, input_dim) or (input_dim,)

        Returns:
            Tuple of (action_logits, value_estimate)
            - action_logits: shape (batch_size, num_actions) or (num_actions,)
            - value_estimate: shape (batch_size, 1) or (1,)
        """
        # Handle single sample (add batch dimension)
        squeeze_output = False
        if observations.ndim == 1:
            observations = observations.unsqueeze(0)
            squeeze_output = True

        # Ensure on correct device
        observations = observations.to(self.device)

        # Extract features
        features = self.feature_extractor(observations)

        # Actor and critic outputs
        action_logits = self.actor(features)
        value_estimate = self.critic(features)

        # Remove batch dimension if input was single sample
        if squeeze_output:
            action_logits = action_logits.squeeze(0)
            value_estimate = value_estimate.squeeze(0)

        return action_logits, value_estimate

    def get_action_and_value(self, observations: torch.Tensor) \
            -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Get action, log probability, and value for given observation.

        Args:
            observations: Tensor of shape (batch_size, input_dim) or (input_dim,)

        Returns:
            Tuple of (action, log_prob, value)
            - action: sampled action ID
            - log_prob: log probability of sampled action
            - value: value estimate
        """
        action_logits, value = self.forward(observations)

        # Sample action from distribution
        dist = torch.distributions.Categorical(logits=action_logits)
        action = dist.sample()
        log_prob = dist.log_prob(action)

        return action, log_prob, value

    def load_checkpoint(self, checkpoint_path: str, strict: bool = False) -> bool:
        """
        Load weights from a PyTorch checkpoint.

        Args:
            checkpoint_path: Path to .pt checkpoint file
            strict: If False, allow partial weight loading for compatibility

        Returns:
            True if load successful, False otherwise
        """
        try:
            checkpoint = torch.load(checkpoint_path, map_location=self.device)

            # Handle various checkpoint formats
            if isinstance(checkpoint, dict):
                # Standard format: checkpoint['model_state_dict']
                if 'model_state_dict' in checkpoint:
                    state_dict = checkpoint['model_state_dict']
                # Alternative: direct state dict
                elif 'state_dict' in checkpoint:
                    state_dict = checkpoint['state_dict']
                # Otherwise assume entire dict is state_dict
                else:
                    state_dict = checkpoint
            else:
                # Assume checkpoint is the model itself
                state_dict = checkpoint.state_dict()

            # Load state dict
            incompatible = self.load_state_dict(state_dict, strict=strict)

            if incompatible.missing_keys:
                logger.warning(f"Missing keys when loading checkpoint: {incompatible.missing_keys[:5]}")
            if incompatible.unexpected_keys:
                logger.warning(f"Unexpected keys when loading checkpoint: {incompatible.unexpected_keys[:5]}")

            logger.info(f"✅ Loaded checkpoint from {checkpoint_path}")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to load checkpoint {checkpoint_path}: {e}")
            return False

    def eval_mode(self):
        """Set network to evaluation mode (disable dropout, batch norm)."""
        self.eval()
        with torch.no_grad():
            # Prevent gradient computation during inference
            for param in self.parameters():
                param.requires_grad = False

    def inference(self, observations: torch.Tensor) -> Dict[str, Any]:
        """
        Run inference and return structured output.

        Args:
            observations: Tensor of shape (batch_size, input_dim) or (input_dim,)

        Returns:
            Dict with keys:
            - action: sampled action ID(s)
            - action_name: human-readable action name(s)
            - confidence: probability of selected action
            - value: value estimate
        """
        self.eval()

        with torch.no_grad():
            action_logits, value = self.forward(observations)

            # Sample action
            dist = torch.distributions.Categorical(logits=action_logits)
            action = dist.sample()

            # Get confidence (probability of selected action)
            probs = torch.softmax(action_logits, dim=-1)
            confidence = probs.gather(-1, action.unsqueeze(-1))

            # Map action to name
            action_names = {
                0: "LONG",
                1: "SHORT",
                2: "HOLD",
                3: "EXIT",
                4: "REDUCE"
            }

            # Handle batch vs single sample
            if action.ndim > 0:
                # Batch
                action_names_out = [action_names.get(a.item(), "UNKNOWN") for a in action]
            else:
                # Single
                action_names_out = action_names.get(action.item(), "UNKNOWN")

            return {
                "action": action,
                "action_name": action_names_out,
                "confidence": confidence.squeeze(-1),
                "value": value.squeeze(-1),
                "action_logits": action_logits,
                "distribution": {
                    "probabilities": probs.cpu().numpy(),
                    "entropy": dist.entropy().cpu().numpy(),
                },
            }


if __name__ == "__main__":
    # Test policy network
    import numpy as np

    device = "cpu"  # Use cpu for testing
    policy = PolicyNetwork(input_dim=562, num_actions=5, device=device)
    policy.eval_mode()

    print("✅ Policy Network Test")
    print(f"   Input dim: 562")
    print(f"   Num actions: 5")
    print(f"   Device: {device}")

    # Test single sample
    obs_single = torch.randn(562, device=device)
    output = policy.inference(obs_single)

    print(f"\n   Single sample inference:")
    print(f"      Action: {output['action_name']}")
    print(f"      Confidence: {output['confidence'].item():.4f}")
    print(f"      Value: {output['value'].item():.4f}")

    # Test batch
    obs_batch = torch.randn(8, 562, device=device)
    action_logits, value = policy.forward(obs_batch)

    print(f"\n   Batch inference (8 samples):")
    print(f"      Action logits shape: {action_logits.shape}")
    print(f"      Value shape: {value.shape}")

    # Test checkpoint loading (will fail gracefully if no checkpoint)
    print(f"\n   Checkpoint loading:")
    result = policy.load_checkpoint("/tmp/nonexistent.pt", strict=False)
    print(f"      Result: {result}")

    print("\n✅ Policy Network tests complete")
