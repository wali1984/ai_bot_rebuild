"""
GPU-Optimized CNN Policy for RTX 5080
Custom policy designed to maximize GPU utilization with convolutional layers
"""

import numpy as np
import torch
import torch.nn as nn
from stable_baselines3.common.policies import ActorCriticPolicy
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor
from gymnasium import spaces
import torch.nn.functional as F


class RTX5080FeatureExtractor(BaseFeaturesExtractor):
    """
    Custom CNN-based feature extractor optimized for RTX 5080
    Transforms flat features into 2D representation for CNN processing
    
    UPDATED: Reduced complexity for 70-90% GPU utilization target:
    - Channel progression: 32→64→128→256→512→1024 (reduced from 64→128→256→512→1024→2048)
    - Enhanced feature processor with dropout for stability
    """
    
    def __init__(self, observation_space: spaces.Box, features_dim: int = 2048):
        super().__init__(observation_space, features_dim)
        
        # Input features: 1430 -> reshape to something CNN can process
        input_size = observation_space.shape[0]  # 1430
        
        # Create 2D representation: 1430 -> 38x38 (closest to square)
        self.height = 38
        self.width = 38
        self.channels = 1
        
        # Pad input to fit 38x38 = 1444
        self.padding_size = (self.height * self.width) - input_size  # 1444 - 1430 = 14
        
        print(f"🎯 RTX5080 CNN Policy: {input_size} features -> {self.height}x{self.width} with {self.padding_size} padding")
        
        # GPU-optimized CNN layers (reduced for 70-90% utilization, 80% VRAM)
        self.cnn = nn.Sequential(
            # First Conv Block - Moderate GPU workload
            nn.Conv2d(1, 32, kernel_size=3, stride=1, padding=1),  # 33x32 -> 33x32
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.Conv2d(32, 64, kernel_size=3, stride=2, padding=1),  # 33x32 -> 17x16
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            
            # Second Conv Block - Controlled GPU computation
            nn.Conv2d(64, 128, kernel_size=3, stride=1, padding=1),  # 17x16 -> 17x16
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.Conv2d(128, 256, kernel_size=3, stride=2, padding=1),  # 17x16 -> 9x8
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),
            
            # Third Conv Block - Balanced GPU utilization
            nn.Conv2d(256, 512, kernel_size=3, stride=1, padding=1),  # 9x8 -> 9x8
            nn.BatchNorm2d(512),
            nn.ReLU(inplace=True),
            nn.Conv2d(512, 1024, kernel_size=3, stride=2, padding=1),  # 9x8 -> 5x4
            nn.BatchNorm2d(1024),
            nn.ReLU(inplace=True),
            
            # Global Average Pooling
            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Flatten(),
        )
        
        # Additional dense layers for feature processing (reduced size)
        self.feature_processor = nn.Sequential(
            nn.Linear(1024, features_dim),
            nn.ReLU(inplace=True),
            nn.Dropout(0.3),
            nn.Linear(features_dim, features_dim // 2),
            nn.ReLU(inplace=True),
            nn.Linear(features_dim // 2, features_dim),
            nn.ReLU(inplace=True),
        )
        
        # Initialize weights for better GPU performance
        self._initialize_weights()
    
    def _initialize_weights(self):
        """Initialize weights for optimal GPU performance"""
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
                if m.bias is not None:
                    nn.init.constant_(m.bias, 0)
            elif isinstance(m, nn.BatchNorm2d):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)
            elif isinstance(m, nn.Linear):
                nn.init.normal_(m.weight, 0, 0.01)
                nn.init.constant_(m.bias, 0)
    
    def forward(self, observations: torch.Tensor) -> torch.Tensor:
        """
        Forward pass optimized for GPU batch processing
        """
        batch_size = observations.shape[0]
        
        # Pad input to fit CNN dimensions
        if self.padding_size > 0:
            padding = torch.zeros(batch_size, self.padding_size, device=observations.device)
            observations = torch.cat([observations, padding], dim=1)
        
        # Reshape to 2D for CNN: (batch, 1, height, width)
        x = observations.view(batch_size, self.channels, self.height, self.width)
        
        # CNN feature extraction (heavy GPU computation)
        features = self.cnn(x)
        
        # Additional processing
        features = self.feature_processor(features)
        
        return features


class RTX5080Policy(ActorCriticPolicy):
    """
    Custom policy optimized for RTX 5080 GPU utilization
    Uses CNN-based feature extraction for maximum GPU throughput
    """
    
    def __init__(self, *args, **kwargs):
        print("🚀 Initializing RTX5080-optimized CNN Policy")
        super().__init__(*args, **kwargs)
    
    def _build_mlp_extractor(self) -> None:
        """
        Build the MLP that process the features after CNN extraction
        """
        from stable_baselines3.common.torch_layers import MlpExtractor
        
        # Create proper MLP extractor with correct interface
        self.mlp_extractor = MlpExtractor(
            feature_dim=self.features_extractor.features_dim,
            net_arch=self.net_arch,
            activation_fn=self.activation_fn,
            device=self.device,
        )
        
        print(f"🎯 MLP Extractor built with feature_dim={self.features_extractor.features_dim}")


def create_rtx5080_policy_kwargs():
    """
    Create policy kwargs optimized for RTX 5080
    """
    return {
        'features_extractor_class': RTX5080FeatureExtractor,
        'features_extractor_kwargs': {'features_dim': 2048},
        'net_arch': {
            'shared': [1024, 512],
            'pi': [256, 128],
            'vf': [256, 128]
        },
        'activation_fn': nn.ReLU,
    }


# Test function to verify GPU utilization
def test_rtx5080_policy():
    """Test the RTX5080 policy with sample data"""
    print("🧪 Testing RTX5080 CNN Policy...")
    
    # Create dummy observation space
    obs_space = spaces.Box(low=-np.inf, high=np.inf, shape=(1430,), dtype=np.float32)
    
    # Create feature extractor
    extractor = RTX5080FeatureExtractor(obs_space, features_dim=2048)
    
    if torch.cuda.is_available():
        extractor = extractor.cuda()
        print("✅ Policy moved to GPU")
    
    # Test with batch of observations
    batch_size = 32  # Same as environment batch
    dummy_obs = torch.randn(batch_size, 1430)
    if torch.cuda.is_available():
        dummy_obs = dummy_obs.cuda()
    
    # Forward pass
    with torch.no_grad():
        start_time = torch.cuda.Event(enable_timing=True)
        end_time = torch.cuda.Event(enable_timing=True)
        
        start_time.record()
        features = extractor(dummy_obs)
        end_time.record()
        
        torch.cuda.synchronize()
        elapsed_time = start_time.elapsed_time(end_time)
        
        print(f"✅ Forward pass: {elapsed_time:.2f}ms for batch of {batch_size}")
        print(f"✅ Output features shape: {features.shape}")
        print(f"✅ GPU memory usage: {torch.cuda.memory_allocated() / 1024**3:.2f} GB")
    
    return True


if __name__ == "__main__":
    test_rtx5080_policy()
