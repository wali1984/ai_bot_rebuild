"""
WMA AI Bot Hybrid Trainer - RTX 5080 Optimized
Maximum GPU utilization with PPO+MASA ensemble architecture
Restored from proven implementation with GPU optimizations
"""
# Suppress warnings early
import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="torch.cuda")
warnings.filterwarnings("ignore", message=".*pynvml.*deprecated.*")

# Set NumExpr to use all available cores (32 cores available)
import os
os.environ['NUMEXPR_MAX_THREADS'] = '32'

import torch
os.environ.setdefault("TORCH_CUDA_ARCH_LIST", "12.0+PTX")

import multiprocessing
import sys
import time
import asyncio
import torch.nn as nn
import torch.nn.functional as F
from torch.amp import autocast  # Mixed-precision training support
import numpy as np
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List

# CRITICAL: Set multiprocessing start method BEFORE any CUDA operations
import atexit
import signal

def cleanup_resources():
    """Clean up multiprocessing resources"""
    try:
        import gc
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except:
        pass

# Register cleanup function
atexit.register(cleanup_resources)

# Handle signals properly
def signal_handler(signum, frame):
    cleanup_resources()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

try:
    # Use 'fork' for better CPU efficiency (Linux only)
    multiprocessing.set_start_method('fork', force=True)
except RuntimeError:
    try:
        multiprocessing.set_start_method('forkserver', force=True)
    except RuntimeError:
        pass  # Keep existing method

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import configuration and Binance client for real portfolio integration
from config import get_live_config
try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException
    BINANCE_AVAILABLE = True
except ImportError:
    BINANCE_AVAILABLE = False
    Client = None
    BinanceAPIException = Exception

# Import Telegram alerts for signal notifications
try:
    from telegram_alerts import TelegramNotifier
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    TelegramNotifier = None

# Import MASA agents and hybrid PPO classes
from rl.agents.masa_agent import MASAAgent, MASAConfig, HybridPPO, DualHeadActorCriticPolicy

# Phase 4: Import enhancement modules for 1000× profitability
try:
    from rl.enhanced_architectures import RecurrentFeatureExtractor, RecurrentActorCriticPolicy
    from rl.hybrid_action_space import HybridActionDecoder, TradingAction
    from rl.advanced_risk_management import TrailingStopLoss, DynamicTakeProfit, RiskLimits
    ENHANCEMENTS_AVAILABLE = True
    # Note: Logger will log this later after it's initialized
except ImportError as e:
    ENHANCEMENTS_AVAILABLE = False
    RecurrentFeatureExtractor = None
    HybridActionDecoder = None
    RecurrentActorCriticPolicy = None
    TrailingStopLoss = None
    DynamicTakeProfit = None

# Phase 3: Import new services for enhanced learning
try:
    from services.onchain_analyzer import OnChainAnalyzer
    ONCHAIN_AVAILABLE = True
except ImportError:
    ONCHAIN_AVAILABLE = False
    OnChainAnalyzer = None

try:
    from rl.continuous_learner import ContinuousLearner, WalkForwardOptimizer, FeedbackCollector
    CONTINUOUS_LEARNING_AVAILABLE = True
except ImportError:
    CONTINUOUS_LEARNING_AVAILABLE = False
    ContinuousLearner = WalkForwardOptimizer = FeedbackCollector = None

try:
    from rl.reward_functions import AdvancedRewardCalculator, RealisticTradingSimulator, OnlineRewardShaper
    ADVANCED_REWARDS_AVAILABLE = True
except ImportError:
    ADVANCED_REWARDS_AVAILABLE = False
    AdvancedRewardCalculator = RealisticTradingSimulator = OnlineRewardShaper = None

# GPU and ML imports
import warnings
from stable_baselines3 import PPO
from stable_baselines3.common.type_aliases import GymEnv, Schedule
from stable_baselines3.common.callbacks import BaseCallback
from stable_baselines3.common.policies import BasePolicy
from stable_baselines3.ppo.policies import MlpPolicy
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor
from stable_baselines3.common.policies import ActorCriticPolicy
from gymnasium import spaces

class RTX5080FeatureExtractor(BaseFeaturesExtractor):
    """
    CNN Feature extractor optimized for RTX 5080 (70-90% GPU utilization target)

    Transforms 1430 features into CNN-friendly format for GPU processing
    """
    def __init__(self, observation_space: spaces.Box, features_dim: int = 2048):
        super().__init__(observation_space, features_dim)
        input_size = observation_space.shape[0]  # e.g., 1430 expected
        # Create 2D representation: aim for a compact shape
        # Example: 1056 -> 33x32 (closer to rectangle)
        # For 1430, try 55x26 (1430), with some padding if needed
        self.height = 55
        self.width = 26   # 55*26 = 1430
        self.channels = 1
        self.padding_size = (self.height * self.width) - input_size  # If input not exact
        # GPU-optimized CNN layers
        self.cnn = nn.Sequential(
            # Conv blocks tuned for GPU utilization
            nn.Conv2d(1, 32, kernel_size=3, stride=1, padding=1),  # initial conv
            nn.BatchNorm2d(32),
            nn.ReLU(inplace=True),
            nn.Conv2d(32, 64, kernel_size=3, stride=2, padding=1),  # downsample
            nn.BatchNorm2d(64),
            nn.ReLU(inplace=True),
            nn.Conv2d(64, 128, kernel_size=3, stride=1, padding=1),  # conv
            nn.BatchNorm2d(128),
            nn.ReLU(inplace=True),
            nn.Conv2d(128, 256, kernel_size=3, stride=2, padding=1),  # downsample further
            nn.BatchNorm2d(256),
            nn.ReLU(inplace=True),
            nn.Flatten(),
            nn.Linear(256 * (self.height//4) * (self.width//4), features_dim),  # final projection
            nn.ReLU(inplace=True),
        )

    def forward(self, observations: torch.Tensor) -> torch.Tensor:
        # If input smaller than expected, pad with zeros
        if self.padding_size > 0:
            pad = torch.zeros(observations.shape[0], self.padding_size, device=observations.device)
            observations = torch.cat([observations, pad], dim=1)
        # Reshape to [batch, 1, height, width]
        obs_image = observations.view(observations.shape[0], self.channels, self.height, self.width)
        features = self.cnn(obs_image)
        return features

class GPUForcedPPO(PPO):
    """PPO implementation optimized for maximum GPU utilization on RTX 5080"""
    def __init__(self, *args, force_gpu_operations: bool = True, **kwargs):
        # Force specific torch behaviors for GPU
        if 'device' not in kwargs:
            kwargs['device'] = 'cuda' if torch.cuda.is_available() else 'cpu'
        super().__init__(*args, **kwargs)
        self.device_str = kwargs.get('device', 'cuda')
        self._cuda_preallocated = False
        # If using GPU, attempt to pre-allocate memory and warm up kernels
        if self.device_str == 'cuda' and force_gpu_operations:
            try:
                dummy_input = torch.randn((1, ) + self.policy.observation_space.shape, device=self.device_str, dtype=torch.float32)
                with torch.no_grad():
                    _ = self.policy(dummy_input)
                logger.info("✅ GPU memory pre-allocated and kernels warmed up")
            except Exception as e:
                logger.warning(f"⚠️ Could not pre-allocate GPU memory: {e}")

    def _setup_masa_blending(self):
        """Setup MASA+PPO logit blending as specified in architecture design"""
        if not hasattr(self, 'masa_agent') or self.masa_agent is None:
            return
        # Store original policy forward method
        original_forward = self.policy.forward
        masa_agent = self.masa_agent
        base_masa_weight = getattr(self, 'masa_weight', 0.3)  # Base weight from config

        def get_adaptive_masa_weight(confidence):
            """
            Compute adaptive MASA weight based on confidence and market regime.
            High confidence (>0.80): Up to 85% MASA
            Medium-high (0.70-0.80): Up to 70% MASA
            Medium (0.50-0.70): ~60% (base)
            Low (<0.50): As low as 30% MASA
            """
            if confidence > 0.80:
                return min(0.85, base_masa_weight * 2.0)
            elif confidence > 0.70:
                return min(0.70, base_masa_weight * 1.5)
            elif confidence > 0.50:
                return base_masa_weight
            else:
                return max(0.30, base_masa_weight * 0.5)

        def blended_forward(obs, deterministic=False):
            """Blend PPO+MASA logits at action time"""
            # Get PPO policy output first
            with torch.no_grad():
                with autocast('cuda', enabled=(self.device_str == 'cuda')):
                    distribution = self.policy.get_distribution(obs)
                    ppo_logits = distribution.distribution.logits
                    try:
                        masa_logits = masa_agent.forward(obs)  # MASA agent output logits
                        ppo_probs = torch.softmax(ppo_logits, dim=-1)
                        ppo_max_prob = torch.max(ppo_probs, dim=-1)[0]
                        avg_confidence = torch.mean(ppo_max_prob).item()
                        masa_weight = get_adaptive_masa_weight(avg_confidence)
                        tau = 1.0  # temperature scaling (could be adjusted)
                        alpha = 1.0 - masa_weight  # PPO weight
                        blended = alpha * ppo_logits + (1.0 - alpha) * masa_logits
                        blended = blended / tau
                        # Select action from blended logits
                        if deterministic:
                            action = torch.argmax(blended, dim=-1)
                        else:
                            action = torch.distributions.Categorical(logits=blended).sample()
                        # Publish decisions every N steps with reasoning
                        self._forward_call_count += 1
                        from config import get_live_config
                        config = get_live_config()
                        should_publish = (
                            getattr(config, "PUBLISH_SIGNALS", True) and
                            (self._forward_call_count % max(1, int(getattr(config, "SIGNAL_PUBLISH_EVERY_N_STEPS", 2))) == 0)
                        )
                        if should_publish:
                            act_np = action.detach().cpu().numpy() if hasattr(action, "detach") else np.asarray(action)
                            confidences = None
                            try:
                                probs = torch.softmax(blended, dim=-1)
                                chosen_probs = probs.gather(-1, action.unsqueeze(-1)).squeeze(-1)
                                confidences = chosen_probs.detach().cpu().numpy()
                            except Exception:
                                confidences = None
                            prices = None
                            try:
                                if hasattr(self.env, "get_last_prices_vector"):
                                    prices = self.env.get_last_prices_vector()
                            except Exception:
                                prices = None
                            self._publish_decisions_with_reasoning(act_np.reshape(-1), confidences=confidences, prices=prices)
                        # Get value estimates and log probabilities from PPO policy
                        values = self.policy.predict_values(obs)
                        log_prob = distribution.log_prob(action)
                        return action, values, log_prob
                    except Exception as e:
                        logger.warning(f"⚠️ MASA blending failed, using PPO-only: {e}")
                        # Fallback to original PPO forward
                        pass
            return original_forward(obs, deterministic)
        # Replace the policy forward method with our blended version
        self.policy.forward = blended_forward
        logger.info("✅ MASA+PPO blending enabled at action time")

    def collect_rollouts(self, env, callback, rollout_buffer, n_rollout_steps: int):
        """Override rollout collection for maximum GPU utilization"""
        # Pre-allocate GPU tensors for performance
        if self.device_str == 'cuda':
            stream1 = torch.cuda.Stream()
            stream2 = torch.cuda.Stream()
            with torch.cuda.stream(stream1):
                result = super().collect_rollouts(env, callback, rollout_buffer, n_rollout_steps)
            torch.cuda.synchronize()
            return result
        else:
            return super().collect_rollouts(env, callback, rollout_buffer, n_rollout_steps)

class GPUBatchedVecEnv:
    """GPU-optimized vectorized environment for maximum GPU utilization"""
    def __init__(self, n_envs: int = 128, **env_kwargs):
        self.n_envs = n_envs
        self.envs = [None] * n_envs
        self.index_map: List[Tuple[str, str]] = []
        # Create environments
        for i in range(n_envs):
            env = TradingEnvironmentWrapper(**env_kwargs)
            self.envs[i] = env
            # If environment has index (symbol, timeframe), record it
            if hasattr(env, 'index') and isinstance(env.index, tuple):
                self.index_map.append(env.index)
        # Dummy attributes for stable_baselines compatibility
        self.num_envs = n_envs
        self.observation_space = self.envs[0].observation_space
        self.action_space = self.envs[0].action_space

    def reset(self):
        obs = [env.reset() for env in self.envs]
        return np.stack(obs)

    def step_async(self, actions):
        # Step all envs asynchronously (here just synchronous as placeholder)
        self._actions = actions

    def step_wait(self):
        results = [env.step(a) for env, a in zip(self.envs, self._actions)]
        obs, rewards, dones, infos = zip(*results)
        return np.stack(obs), np.array(rewards), np.array(dones), list(infos)

    def close(self):
        for env in self.envs:
            env.close()

    def render(self):
        return

# Utils and wrappers
from utils.redis_client import get_redis
from utils.logger import get_logger
from rl.gymnasium_wrapper import TradingEnvironmentWrapper, make_env
from rl.environment import TradingEnvironment

logger = get_logger("hybrid_trainer")

class GPUEnvironment(TradingEnvironment):
    """Custom TradingEnvironment that operates fully on GPU (for speed)"""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Additional GPU setup if needed
        self._device = None
        self._cuda_initialized = False
        # GPU state (positions, prices, balance) as torch tensors
        self.positions = None
        self.entry_prices = None
        self.current_balance = None
        self.feature_processor = None
        self.feature_buffer = None
        self.observation_buffer = None
        # Action space size (e.g., 3^N for multi-asset discrete actions)
        self.action_space_size = 3 ** len(SYMBOLS)
        self.n_symbols = len(SYMBOLS)
        # Connect to Redis for features
        self.redis = get_redis()
        # Pre-compute symbol index mapping for quick reference
        self.symbol_to_idx = {symbol: idx for idx, symbol in enumerate(SYMBOLS)}
        logger.info(f"🎯 GPU Environment ready with {self.n_symbols} symbols (CUDA deferred)")

    @property
    def device(self):
        """Get device, initializing CUDA if needed"""
        if self._device is None:
            self._initialize_cuda()
        return self._device

    def _initialize_cuda(self):
        """Initialize CUDA after process fork to avoid multiprocessing issues"""
        if self._cuda_initialized:
            return
        self._device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        if self._device.type == 'cuda':
            logger.info(f"🚀 GPU Environment initialized on {torch.cuda.get_device_name()}")
        else:
            if self._device != 'cpu':
                logger.warning(f"⚠️ CUDA not available, falling back to CPU")
            else:
                logger.debug("CPU environment initialized")
        # Initialize GPU tensors
        self.positions = torch.zeros(len(SYMBOLS), device=self._device, dtype=torch.float32)
        self.entry_prices = torch.zeros(len(SYMBOLS), device=self._device, dtype=torch.float32)
        self.current_balance = torch.tensor(self.initial_balance, device=self._device, dtype=torch.float32)
        # GPU feature processing network
        self.feature_processor = self._create_gpu_feature_processor()
        # Pre-allocate buffers
        self.feature_buffer = torch.zeros(2000, device=self._device, dtype=torch.float32)
        self.observation_buffer = torch.zeros(1000, device=self._device, dtype=torch.float32)
        self._cuda_initialized = True
        logger.info(f"✅ CUDA initialization complete on {self._device}")

    def warm_up_gpu(self):
        """Warm up GPU by ensuring CUDA is initialized"""
        _ = self.device
        if self.feature_processor is not None:
            dummy_input = torch.randn(1, 2000, device=self.device)
            with torch.no_grad():
                _ = self.feature_processor(dummy_input)
        logger.info("🔥 GPU warmed up successfully")

    def _create_gpu_feature_processor(self) -> nn.Module:
        """Create GPU-accelerated feature processing network"""
        input_size = 1430  # based on unified features (10 symbols × 143 features)
        logger.info(f"🎯 Creating feature processor with input size: {input_size}")
        processor = nn.Sequential(
            nn.Linear(input_size, 1024),
            nn.LayerNorm(1024),
            nn.ReLU(inplace=True),
            nn.Dropout(0.1),
            nn.Linear(1024, 512),
            nn.LayerNorm(512),
            nn.ReLU(inplace=True),
            nn.Dropout(0.1),
            nn.Linear(512, 1000),
            nn.LayerNorm(1000),
            nn.Tanh()
        ).to(self._device)
        for module in processor.modules():
            if isinstance(module, nn.Linear):
                nn.init.xavier_uniform_(module.weight)
                nn.init.zeros_(module.bias)
        return processor

    def get_current_features_gpu(self) -> torch.Tensor:
        """Get current market features and process on GPU - comprehensive unified features"""
        self._initialize_cuda()
        # Use shared cached features if set (for batched env optimization)
        if hasattr(self, '_override_shared_features') and self._override_shared_features is not None:
            features = self._override_shared_features
            self._override_shared_features = None
            if hasattr(self, '_redis_log_counter'):
                self._redis_log_counter += 1
                if self._redis_log_counter % 1000 == 0:
                    logger.info(f"✅ Redis batching active: {features.shape[0]} features (call #{self._redis_log_counter})")
            else:
                self._redis_log_counter = 1
                logger.info(f"✅ Using SHARED BATCHED features: {features.shape[0]} features (Redis overhead eliminated!)")
            return features
        # Simple cache to avoid excessive Redis calls (cache 1 second)
        current_time = time.time()
        if hasattr(self, '_feature_cache_time') and (current_time - self._feature_cache_time) < 1.0:
            if hasattr(self, '_cached_features'):
                return self._cached_features
        try:
            # Retrieve unified features from Redis for all symbols and multiple timeframes
            symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'ADAUSDT', 'DOTUSDT',
                       'LINKUSDT', 'MATICUSDT', 'AVAXUSDT', 'LTCUSDT', 'ATOMUSDT']
            primary_tf = '1m'
            # Build unified feature keys for comprehensive data (multi-TF context)
            unified_keys = []
            for symbol in symbols:
                unified_keys.append(f"unified_features:{symbol}:{primary_tf}")
                for tf in ['5m', '15m', '1h']:
                    unified_keys.append(f"unified_features:{symbol}:{tf}")
            # Check existence of each unified feature key
            logger.debug(f"Checking {len(unified_keys)} unified feature sets")
            feature_exists = []
            for key in unified_keys:
                exists = self.redis.exists(key)
                feature_exists.append(exists)
            if not any(feature_exists):
                logger.warning("No unified features available, using default features")
                return self._get_default_features_gpu()
            feature_values = []
            # Process unified features for each symbol with fallback logic
            for symbol_idx, symbol in enumerate(symbols):
                symbol_features = []
                # Determine which timeframe's features to use (fallback 1m -> 5m -> 15m -> 1h)
                timeframe_to_use = None
                if feature_exists[symbol_idx * 4]:
                    timeframe_to_use = primary_tf  # 1m features exist
                elif feature_exists[symbol_idx * 4 + 1]:
                    timeframe_to_use = '5m'
                elif feature_exists[symbol_idx * 4 + 2]:
                    timeframe_to_use = '15m'
                elif feature_exists[symbol_idx * 4 + 3]:
                    timeframe_to_use = '1h'
                if timeframe_to_use:
                    unified_key = f"unified_features:{symbol}:{timeframe_to_use}"
                    try:
                        unified_features = self.redis.hgetall(unified_key)
                        if unified_features:
                            # Extract features in consistent order
                            # CCXT features (OHLCV)
                            for key in ['ccxt_open', 'ccxt_high', 'ccxt_low', 'ccxt_close', 'ccxt_volume']:
                                value = unified_features.get(key.encode('utf-8'), b'0.0')
                                if isinstance(value, bytes):
                                    value = value.decode('utf-8')
                                symbol_features.append(float(value) if value != '0.0' else 50000.0)
                            # CoinAnk comprehensive features (93 features per symbol)
                            coinank_features = []
                            for k, v in unified_features.items():
                                if isinstance(k, bytes):
                                    k = k.decode('utf-8')
                                if isinstance(v, bytes):
                                    v = v.decode('utf-8')
                                if k.startswith('coinank_'):
                                    try:
                                        if v.replace('.', '').replace('-', '').isdigit():
                                            coinank_features.append(float(v))
                                        else:
                                            # Handle categorical values
                                            if v.lower() in ['bullish', 'buy', 'long']:
                                                coinank_features.append(1.0)
                                            elif v.lower() in ['bearish', 'sell', 'short']:
                                                coinank_features.append(-1.0)
                                            else:
                                                coinank_features.append(0.0)
                                    except:
                                        coinank_features.append(0.0)
                            # Ensure 93 CoinAnk features
                            while len(coinank_features) < 93:
                                coinank_features.append(0.0)
                            symbol_features.extend(coinank_features[:93])
                            # TokenMetrics features
                            tm_features = []
                            for k, v in unified_features.items():
                                if isinstance(k, bytes):
                                    k = k.decode('utf-8')
                                if isinstance(v, bytes):
                                    v = v.decode('utf-8')
                                if k.startswith('tm_'):
                                    try:
                                        if k == 'tm_grade':
                                            grade_map = {'A': 90, 'B': 75, 'C': 50, 'D': 25, 'F': 0}
                                            tm_features.append(grade_map.get(v, 50))
                                        else:
                                            tm_features.append(float(v))
                                    except:
                                        tm_features.append(0.0)
                            # Ensure minimum TokenMetrics features
                            while len(tm_features) < 3:
                                tm_features.append(50.0)
                            symbol_features.extend(tm_features[:3])
                            # Order book features
                            for key in ['ob_bid_depth', 'ob_ask_depth', 'ob_spread', 'ob_imbalance']:
                                value = unified_features.get(key.encode('utf-8'), b'0.0')
                                if isinstance(value, bytes):
                                    value = value.decode('utf-8')
                                symbol_features.append(float(value))
                            # Technical indicators
                            ind_features = []
                            for k, v in unified_features.items():
                                if isinstance(k, bytes):
                                    k = k.decode('utf-8')
                                if isinstance(v, bytes):
                                    v = v.decode('utf-8')
                                if k.startswith('ind_'):
                                    try:
                                        ind_features.append(float(v))
                                    except:
                                        ind_features.append(0.0)
                            # Ensure minimum indicator features
                            while len(ind_features) < 10:
                                ind_features.append(0.0)
                            symbol_features.extend(ind_features[:10])
                        else:
                            # Default comprehensive features for symbol (no data in hash)
                            symbol_features.extend([50000.0] * 5)  # CCXT
                            symbol_features.extend([0.0] * 93)     # CoinAnk
                            symbol_features.extend([50.0, 50.0, 0.0])  # TokenMetrics
                            symbol_features.extend([0.0] * 4)     # Order book
                            symbol_features.extend([0.0] * 10)    # Indicators
                    except Exception as e:
                        logger.debug(f"Error processing unified features for {symbol}: {e}")
                        # Default comprehensive features for symbol on exception
                        symbol_features.extend([50000.0] * 5)  # CCXT
                        symbol_features.extend([0.0] * 93)     # CoinAnk
                        symbol_features.extend([50.0, 50.0, 0.0])  # TokenMetrics
                        symbol_features.extend([0.0] * 4)     # Order book
                        symbol_features.extend([0.0] * 10)    # Indicators
                else:
                    # No unified features found for this symbol in any timeframe
                    symbol_features.extend([50000.0] * 5)  # CCXT
                    symbol_features.extend([0.0] * 93)     # CoinAnk
                    symbol_features.extend([50.0, 50.0, 0.0])  # TokenMetrics
                    symbol_features.extend([0.0] * 4)     # Order book
                    symbol_features.extend([0.0] * 10)    # Indicators
                feature_values.extend(symbol_features)
            # Optionally include global market-wide features (TokenMetrics + CoinAnk global metrics)
            global_features = self._load_global_features()
            feature_values.extend(global_features)
            # If in historical training mode, load historical context features too
            if getattr(self, 'training_mode', 'live') == 'historical':
                historical_features = self._load_historical_features(symbols, primary_tf)
                feature_values.extend(historical_features)
            # Convert to GPU tensor
            feature_array = np.array(feature_values, dtype=np.float32)
            feature_tensor = torch.tensor(feature_array, device=self._device)
            # Cache the result for a short time
            self._cached_features = feature_tensor
            self._feature_cache_time = time.time()
            # Process features with GPU feature processor
            processed = self.feature_processor(feature_tensor.unsqueeze(0))
            return processed.squeeze(0)
        except Exception as e:
            logger.error(f"Failed to get GPU features: {e}")
            return self._get_default_features_gpu()

    def _get_default_features_gpu(self) -> torch.Tensor:
        """Generate a default feature tensor when no data is available"""
        # 10 symbols × 115 default features + 23 global = 1173 (padded to 1430 perhaps)
        default_features = []
        for _ in range(10):
            default_features.extend([50000.0] * 5)   # CCXT (OHLCV)
            default_features.extend([0.0] * 93)      # CoinAnk
            default_features.extend([50.0, 50.0, 0.0])  # TokenMetrics (grade, score, prediction)
            default_features.extend([0.0] * 4)       # Order book
            default_features.extend([0.0] * 10)      # Indicators
        default_features.extend([0.0] * 23)  # global features default
        return torch.tensor(default_features, device=self._device, dtype=torch.float32)

    def _load_global_features(self) -> List[float]:
        """
        Load global market-wide features from Redis (TokenMetrics + CoinAnk global metrics)
        Returns:
            List of 23 global features (12 TokenMetrics global + 11 CoinAnk global)
        """
        global_features = []
        try:
            # TokenMetrics global features (12 keys)
            tm_global_keys = [
                "tm_global_btc_dominance", "tm_global_altcoin_marketcap", "tm_global_marketcap_change",
                "tm_global_volume_24h", "tm_global_defi_marketcap", "tm_global_defi_volume_24h",
                "tm_global_derivatives_volume_24h", "tm_global_stablecoin_marketcap", "tm_global_stablecoin_volume_24h",
                "tm_global_marketcap_ath", "tm_global_mcap_to_ath_pct", "tm_global_volume_to_mcap_ratio"
            ]
            for key in tm_global_keys:
                data_str = self.redis.get(key)
                if data_str:
                    data = json.loads(data_str)
                    # Each global TM key might be a simple value or dict; take a representative float
                    if isinstance(data, dict):
                        value = float(next(iter(data.values()), 0.0))
                    else:
                        try:
                            value = float(data)
                        except:
                            value = 0.0
                    global_features.append(value)
                else:
                    global_features.append(0.0)
            # CoinAnk global features (11 keys)
            coinank_global_keys = [
                "coinank_global_open_interest", "coinank_global_funding_rate", "coinank_global_liquidations_long",
                "coinank_global_liquidations_short", "coinank_global_volume_24h", "coinank_global_volatility_index",
                "coinank_global_greed_fear", "coinank_global_up_down_ratio", "coinank_global_whale_index",
                "coinank_global_defi_tvls", "coinank_global_derivs_open_interest"
            ]
            for key in coinank_global_keys:
                data_str = self.redis.get(key)
                if data_str:
                    data = json.loads(data_str)
                    if isinstance(data, dict):
                        # If dict, get first value
                        value = float(next(iter(data.values()), 0.0))
                    else:
                        try:
                            value = float(data)
                        except:
                            value = 0.0
                    global_features.append(value)
                else:
                    global_features.append(0.0)
            # Ensure exactly 23 features
            while len(global_features) < 23:
                global_features.append(0.0)
            logger.debug(f"✅ Loaded {len(global_features[:23])} global features")
            return global_features[:23]
        except Exception as e:
            logger.error(f"Error loading global features: {e}")
            return [0.0] * 23

    def _load_historical_features(self, symbols: List[str], primary_tf: str) -> List[float]:
        """
        Load historical features (e.g., recent price moves or technical trends)
        for each symbol. In a real implementation, this might fetch from Redis or a database.
        """
        historical_features = []
        try:
            # Placeholder example: simple recent price change features
            for symbol in symbols:
                # This would extract recent price changes from Redis or elsewhere
                # For now, use dummy features to represent historical context
                historical_features.extend([0.0] * 5)  # e.g., price changes for 5 recent intervals
        except Exception as e:
            logger.error(f"Error loading historical features: {e}")
        # Ensure a consistent length (5 features per symbol as placeholder)
        return historical_features

    def _calculate_portfolio_value_gpu(self) -> torch.Tensor:
        """Calculate total portfolio value on GPU"""
        current_prices = self._get_current_prices_gpu()
        position_values = self.positions * current_prices
        return self.current_balance + position_values.sum()

    def _get_current_prices_gpu(self) -> torch.Tensor:
        """
        Get current prices for all symbols from Redis (or cached) as a GPU tensor.
        """
        try:
            # This would extract prices from Redis and convert to GPU tensor
            # For now, placeholder implementation
            return torch.ones(self.n_symbols, device=self.device) * 50000.0
        except Exception as e:
            logger.error(f"Error getting current prices: {e}")
            return torch.ones(self.n_symbols, device=self.device) * 0.0

    def reset_gpu(self) -> torch.Tensor:
        """Reset environment on GPU"""
        if not self._cuda_initialized:
            self._initialize_cuda()
        self.positions.zero_()
        self.entry_prices.zero_()
        self.current_balance.fill_(self.initial_balance)
        return self.get_state_gpu()

    def get_state_gpu(self) -> torch.Tensor:
        """Get full state (features + portfolio) as GPU tensor"""
        features = self.get_current_features_gpu()
        return features  # Already processed by feature_processor

    def step_gpu(self, action: int) -> Tuple[torch.Tensor, torch.Tensor, bool, Dict[str, Any]]:
        """
        Take a step using action (int) on GPU environment.
        Returns: (next_state, reward, done, info)
        """
        # For simplicity, mimic the environment step
        reward = torch.zeros(1, device=self._device)
        done = False
        info = {}
        # Simulate trade execution (update positions etc.) - simplified for demonstration
        return self.get_state_gpu(), reward, done, info

    def close(self):
        """Cleanup resources"""
        pass

# Configuration for hybrid training
class HybridConfig:
    """Configuration for hybrid PPO+MASA training"""
    def __init__(self):
        # Device configuration
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.use_compile = False
        self.amp = True  # Automatic Mixed Precision
        self.force_gpu_rollouts = True
        self.mixed_precision = True
        # Environment parallelism and network sizes
        self.n_envs = 64
        self.vec_env_type = 'dummy'
        self.heavy_policy_network = False
        self.policy_layers = [2048, 1024, 512, 256]
        self.value_layers = [2048, 1024, 512, 256]
        # Training hyperparameters for continuous high utilization
        self.total_timesteps = 10_000_000  # default total training steps
        self.learning_rate = 5e-4
        self.n_steps = 1024   # per environment
        self.batch_size = 2048
        self.n_epochs = 16
        self.gamma = 0.99
        self.gae_lambda = 0.95
        self.clip_range = 0.2
        self.ent_coef = 0.0
        self.vf_coef = 0.5
        self.max_grad_norm = 0.5
        # MASA settings
        self.masa_enabled = True
        self.masa_weight = 0.3
        self.masa_update_freq = 1000
        self.masa_hidden_size = 2048
        # Confidence threshold for trading signals
        self.min_trading_confidence = 0.75
        self.adaptive_threshold_window = 500

class HybridTrainer:
    """Hybrid PPO+MASA trainer with GPU optimization"""
    def __init__(self, config: Optional[HybridConfig] = None, training_mode: str = "live"):
        self.config = config or HybridConfig()
        self.training_mode = training_mode
        # Redis connection
        self.redis = get_redis()
        self._signal_redis = None
        self._signal_min_conf = 0.75
        self._forward_call_count = 0
        # Initialize environment
        env_kwargs = {
            "initial_balance": 100000.0,
            "trading_fee": 0.0005,
            "reward_scaling": 1.0,
            "observation_type": "unified"  # using unified feature vectors
        }
        # Create vectorized environments
        if self.config.force_gpu_rollouts:
            # Use GPU-accelerated environment
            vec_env = GPUBatchedVecEnv(n_envs=self.config.n_envs, **env_kwargs)
        else:
            # Use CPU vectorized environments via DummyVecEnv or SubprocVecEnv
            env_fns = [make_env(**env_kwargs) for _ in range(self.config.n_envs)]
            vec_env = DummyVecEnv(env_fns)
        self.vec_env = vec_env
        # Determine observation and action dimensions
        obs_space = vec_env.observation_space
        act_space = vec_env.action_space
        if isinstance(obs_space, spaces.Box):
            obs_dim = int(np.prod(obs_space.shape))
        else:
            obs_dim = obs_space.n
        if isinstance(act_space, spaces.Discrete):
            act_dim = act_space.n
        elif isinstance(act_space, spaces.MultiDiscrete):
            act_dim = int(np.prod(act_space.nvec))
        else:
            act_dim = act_space.shape[0] if act_space.shape else 1
        logger.info(f"📊 Environment dimensions - Obs: {obs_dim}, Actions: {act_dim}")
        # Check for any checkpoint to resume
        checkpoint_metadata = None
        # (Loading logic for checkpoints would go here, omitted for brevity)
        if checkpoint_metadata:
            logger.info("🔄 Resuming training from checkpoint")
            # (Resume logic omitted)
        else:
            logger.info("📊 Will train from scratch using historical data")
        # Create new models (PPO and optionally MASA)
        logger.info("🆕 Creating fresh models with updated architecture")
        if ENHANCEMENTS_AVAILABLE:
            logger.info("🚀 Using LSTM+Attention Policy with Recurrent Feature Extractor")
            policy_kwargs = {
                "features_extractor_class": RecurrentFeatureExtractor,
                "features_extractor_kwargs": {
                    "features_dim": 2048,
                    "lstm_hidden_size": 512,
                    "lstm_num_layers": 2,
                    "attention_heads": 8,
                    "sequence_length": 10,
                    "dropout": 0.1
                },
                "net_arch": dict(pi=[1024, 512, 256], vf=[1024, 512, 256]),
                "activation_fn": nn.ReLU,
            }
            self.sequence_length = 10
            self.observation_sequences = {}
            self.ppo_model = GPUForcedPPO(
                "MlpPolicy",
                vec_env,
                learning_rate=self.config.learning_rate,
                n_steps=self.config.n_steps,
                batch_size=self.config.batch_size,
                n_epochs=self.config.n_epochs,
                gamma=self.config.gamma,
                gae_lambda=self.config.gae_lambda,
                clip_range=self.config.clip_range,
                ent_coef=self.config.ent_coef,
                vf_coef=self.config.vf_coef,
                max_grad_norm=self.config.max_grad_norm,
                policy_kwargs=policy_kwargs,
                device='cuda',
                verbose=1,
                force_gpu_operations=True,
                mixed_precision=True,
                pin_memory=True,
                num_threads=16
            )
            logger.info("✅ LSTM+Attention Policy created with sequence length 10")
        else:
            logger.info("🚀 Using RTX5080-optimized CNN Policy for maximum GPU utilization")
            self.ppo_model = GPUForcedPPO(
                RTX5080Policy,
                vec_env,
                learning_rate=self.config.learning_rate,
                n_steps=self.config.n_steps,
                batch_size=self.config.batch_size,
                n_epochs=self.config.n_epochs,
                gamma=self.config.gamma,
                gae_lambda=self.config.gae_lambda,
                clip_range=self.config.clip_range,
                ent_coef=self.config.ent_coef,
                vf_coef=self.config.vf_coef,
                max_grad_norm=self.config.max_grad_norm,
                device='cuda',
                verbose=1,
                force_gpu_operations=True,
                mixed_precision=True,
                pin_memory=True,
                num_threads=16
            )
        logger.info("✅ Fresh PPO model created")
        # Attach signal publisher for real-time signals
        live_config = get_live_config()
        self.attach_signal_publisher(self.redis, min_conf=live_config.MIN_TRADING_CONFIDENCE)
        # Initialize MASA agent if enabled
        if getattr(live_config, "MASA_ENABLED", self.config.masa_enabled):
            masa_config = MASAConfig(
                obs_dim=obs_dim,
                act_dim=act_dim,
                hidden_size=self.config.masa_hidden_size,
                num_layers=8,
                dropout=0.1
            )
            self.masa_agent = MASAAgent(masa_config, device=torch.device(self.config.device))
            self.masa_weight = float(getattr(live_config, "MASA_WEIGHT", self.config.masa_weight))
            self.masa_update_freq = int(getattr(live_config, "MASA_UPDATE_FREQ", self.config.masa_update_freq))
            logger.info(f"✅ MASA enabled (weight={self.masa_weight}); device={self.config.device}")
        else:
            self.masa_agent = None
            logger.info("ℹ️ MASA disabled; PPO-only mode")
        # Pass MASA agent and blending parameters to PPO model
        if hasattr(self.ppo_model, 'masa_agent'):
            self.ppo_model.masa_agent = self.masa_agent
            self.ppo_model.masa_weight = self.config.masa_weight
        # Apply aggressive GPU optimizations to models
        if self.config.device == 'cuda':
            self.ppo_model = apply_aggressive_gpu_optimizations(self.ppo_model, device=torch.device(self.config.device))
            if self.masa_agent:
                self.masa_agent = apply_aggressive_gpu_optimizations(self.masa_agent, device=torch.device(self.config.device))
        # Prepare training callback and others if needed
        self.training_callback = self._create_training_callback()
        # If continuous learning enabled, instantiate feedback collector
        self.feedback_collector = FeedbackCollector() if CONTINUOUS_LEARNING_AVAILABLE else None
        # Telegram notifier setup
        self.telegram_notifier = None
        try:
            from telegram_alerts import TelegramNotifier
            live_cfg = get_live_config()
            self.telegram_notifier = TelegramNotifier(
                bot_token=live_cfg.TELEGRAM_BOT_TOKEN,
                bot_chat_id=live_cfg.TELEGRAM_CHAT_ID,
                channel_id=live_cfg.PRIVATE_CHANNEL_ID,
            )
            logger.info("✅ Telegram notifier initialized")
        except Exception as e:
            logger.warning(f"⚠️ Telegram notifier setup failed: {e}")
        # On-chain analytics setup
        if ONCHAIN_AVAILABLE:
            try:
                self.onchain = OnChainAnalyzer(redis_client=self.redis)
                logger.info("🔗 On-chain analytics initialized (Glassnode + Whale Alert)")
            except Exception as e:
                logger.error(f"Failed to initialize on-chain analyzer: {e}")
                self.onchain = None
        else:
            self.onchain = None

    def attach_signal_publisher(self, redis_client, min_conf: float):
        """Attach a Redis-based signal publisher for model decisions (streams + last-hash storage)"""
        self._signal_redis = redis_client
        self._signal_min_conf = min_conf
        logger.info(f"✅ Signal publisher attached (Redis stream + last-hash, min_conf={min_conf})")

    def _publish_decision(self, payload: dict):
        """Publish a single decision payload to Redis stream"""
        from config import get_live_config
        config = get_live_config()
        if not getattr(config, "PUBLISH_SIGNALS", True):
            return
        try:
            self._signal_redis.xadd(
                config.SIGNAL_OUTPUT_STREAM,
                {"data": json.dumps(payload, separators=(",", ":"))},
                maxlen=config.SIGNAL_STREAM_MAXLEN,
                approximate=True,
            )
            self._signal_redis.hset(
                f"{config.SIGNAL_OUTPUT_STREAM}:last:{payload.get('symbol')}:{payload.get('timeframe')}",
                mapping={k: (json.dumps(v) if not isinstance(v,(int,float,str)) else v) for k, v in payload.items()}
            )
        except Exception as e:
            logger.exception(f"Failed to publish single decision: {e}")

    def _publish_decisions_batch(self, actions, confidences=None, prices=None, ts: float = None):
        """Publish batch of decisions for all environments using Redis pipeline"""
        from config import get_live_config
        config = get_live_config()
        if not getattr(config, "PUBLISH_SIGNALS", True):
            return
        if not getattr(self, "env_index_map", None):
            self._init_env_index_map(getattr(self, 'env', None))
        now = ts or time.time()
        n = min(len(self.env_index_map), len(actions))
        pipe = self._signal_redis.pipeline()
        for i in range(n):
            sym, tf = self.env_index_map[i]
            a = int(actions[i])
            c = float(confidences[i]) if confidences is not None else 1.0
            min_confidence_threshold = max(0.85, getattr(config, "SIGNAL_CONFIDENCE_MIN", 0.85))
            if c < min_confidence_threshold:
                continue
            if c >= 0.85 and self.telegram_notifier and a != 0:
                action_name = "LONG" if a > 0 else "SHORT"
                asyncio.create_task(self.telegram_notifier.send_to_ai_signals(
                    f"🎯 HIGH CONFIDENCE SIGNAL\n\n"
                    f"Symbol: {sym}\n"
                    f"Timeframe: {tf}\n"
                    f"Action: {action_name}\n"
                    f"Confidence: {c*100:.1f}%\n"
                    f"Model: PPO+MASA+LSTM\n"
                    f"Timestamp: {datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S')}"
                ))
            payload = {
                "timestamp": now,
                "symbol": sym,
                "timeframe": tf,
                "action": a,
                "confidence": c,
                "model": "ppo_masa_lstm",
                "source": getattr(config, "PUBLISH_SOURCE_TAG", "trainer"),
            }
            if prices is not None and i < len(prices):
                payload["price"] = float(prices[i])
            pipe.xadd(
                config.SIGNAL_OUTPUT_STREAM,
                {"data": json.dumps(payload, separators=(",", ":"))},
                maxlen=config.SIGNAL_STREAM_MAXLEN,
                approximate=True,
            )
            pipe.hset(
                f"{config.SIGNAL_OUTPUT_STREAM}:last:{sym}:{tf}",
                mapping=payload
            )
        try:
            pipe.execute(False)
        except Exception as e:
            logger.exception(f"Failed to publish batch decisions: {e}")

    def _get_current_position(self, symbol: str, include_paper: bool = True) -> Dict[str, Any]:
        """Query Redis for current position state from traders (live and paper)"""
        try:
            position_key = f"positions:{symbol}"
            position_data = self._signal_redis.hgetall(position_key)
            is_paper = False
            if not position_data and include_paper:
                position_key = f"positions:paper:{symbol}"
                position_data = self._signal_redis.hgetall(position_key)
                is_paper = True
            if not position_data:
                return {
                    'has_position': False,
                    'side': 'NONE',
                    'size': 0.0,
                    'entry_price': 0.0,
                    'current_price': 0.0,
                    'unrealized_pnl': 0.0,
                    'pnl_pct': 0.0,
                    'leverage': 1,
                    'margin_used': 0.0,
                    'age_seconds': 0,
                    'is_paper': False
                }
            has_long = position_data.get('has_long', 'False') == 'True'
            has_short = position_data.get('has_short', 'False') == 'True'
            if has_long:
                long_data = json.loads(position_data.get('long', '{}'))
                return {
                    'has_position': True,
                    'side': 'LONG',
                    'size': float(long_data.get('size', 0)),
                    'entry_price': float(long_data.get('entry_price', 0)),
                    'current_price': float(long_data.get('current_price', 0)),
                    'unrealized_pnl': float(long_data.get('unrealized_pnl', 0)),
                    'pnl_pct': float(long_data.get('pnl_pct', 0)),
                    'leverage': int(long_data.get('leverage', 1)),
                    'margin_used': float(long_data.get('margin_used', 0)),
                    'age_seconds': int(long_data.get('age_seconds', 0)),
                    'is_paper': is_paper
                }
            if has_short:
                short_data = json.loads(position_data.get('short', '{}'))
                return {
                    'has_position': True,
                    'side': 'SHORT',
                    'size': float(short_data.get('size', 0)),
                    'entry_price': float(short_data.get('entry_price', 0)),
                    'current_price': float(short_data.get('current_price', 0)),
                    'unrealized_pnl': float(short_data.get('unrealized_pnl', 0)),
                    'pnl_pct': float(short_data.get('pnl_pct', 0)),
                    'leverage': int(short_data.get('leverage', 1)),
                    'margin_used': float(short_data.get('margin_used', 0)),
                    'age_seconds': int(short_data.get('age_seconds', 0)),
                    'is_paper': is_paper
                }
            return {
                'has_position': False,
                'side': 'NONE',
                'size': 0.0,
                'entry_price': 0.0,
                'current_price': 0.0,
                'unrealized_pnl': 0.0,
                'pnl_pct': 0.0,
                'leverage': 1,
                'margin_used': 0.0,
                'age_seconds': 0,
                'is_paper': is_paper
            }
        except Exception as e:
            logger.error(f"Error querying position for {symbol}: {e}")
            return {
                'has_position': False,
                'side': 'NONE',
                'size': 0.0,
                'entry_price': 0.0,
                'current_price': 0.0,
                'unrealized_pnl': 0.0,
                'pnl_pct': 0.0,
                'leverage': 1,
                'margin_used': 0.0,
                'age_seconds': 0,
                'is_paper': False
            }

    def _get_portfolio_state(self, include_paper: bool = True) -> Dict[str, Any]:
        """Aggregate portfolio state (balance, margin utilization, etc.)"""
        try:
            if hasattr(self.config, 'redis_client') and self.config.redis_client:
                redis_client = self.config.redis_client
            elif hasattr(self, 'redis') and self.redis:
                redis_client = self.redis
            else:
                import redis
                redis_client = redis.Redis(host='localhost', port=6379, decode_responses=True)
            data = redis_client.get('portfolio:state')
            if data:
                state = json.loads(data)
                return state
        except Exception as e:
            logger.error(f"Error getting portfolio state: {e}")
        return {'total_balance': 0.0, 'available_balance': 0.0, 'total_margin_used': 0.0,
                'margin_utilization_pct': 0.0, 'unrealized_pnl': 0.0, 'is_paper': False}

    def _calculate_training_level(self) -> float:
        """Calculate training progression level (0.0 to 1.0) based on timesteps completed"""
        # This could track learning progress to adjust strategies
        return 0.5  # placeholder value

    def _estimate_market_volatility(self, symbol: str, timeframe: str) -> float:
        """Estimate market volatility (e.g., recent ATR or stddev) for a symbol/timeframe"""
        try:
            vol_key = f"volatility:{symbol}:{timeframe}"
            vol_data = self.redis.get(vol_key)
            if vol_data:
                vol = float(vol_data)
                return min(1.0, vol)  # normalize if needed
        except Exception as e:
            logger.debug(f"Volatility estimate failed: {e}")
        return 0.0

    def _calculate_optimal_leverage(self, symbol: str, confidence: float, training_level: float, volatility: float) -> int:
        """Calculate recommended leverage based on confidence, training progress, volatility"""
        try:
            # Example: base leverage range by symbol (could be fetched from config)
            leverage_ranges = {
                "BTCUSDT": (20, 125),
                "ETHUSDT": (20, 100),
                "DEFAULT": (5, 50)
            }
            min_lev, max_lev = leverage_ranges.get(symbol, leverage_ranges["DEFAULT"])
            # Confidence and training level to scaling factor (0-1)
            conf_factor = confidence
            training_factor = training_level
            vol_factor = (1.0 - volatility)  # lower leverage if volatility high
            # Combined factor (weight confidence more)
            final_factor = (0.7 * conf_factor) + (0.2 * training_factor) + (0.1 * vol_factor)
            leverage_range = max_lev - min_lev
            leverage = int(min_lev + (leverage_range * final_factor))
            leverage = max(min_lev, min(max_lev, leverage))
            return leverage
        except Exception as e:
            logger.warning(f"⚠️ Leverage calculation failed: {e}")
            if symbol in ["BTCUSDT", "ETHUSDT", "BTCUSD", "ETHUSD"]:
                return 75
            elif symbol in ["SOLUSDT", "SOLUSD"]:
                return 53
            elif symbol in ["LTCUSDT", "LTCUSD"]:
                return 40
            else:
                return 17

    def _calculate_optimal_position_size(self, confidence: float, training_level: float, volatility: float, timeframe: str) -> float:
        """Calculate recommended position size (as % of balance)"""
        try:
            base_size = 0.05  # base 5% of balance
            # Adjust size by confidence and volatility
            size = base_size * (0.5 + confidence * 0.5) * (0.5 + (1.0 - volatility) * 0.5)
            # Further adjust by training progress if needed
            size *= (0.8 + training_level * 0.2)
            return min(1.0, size)
        except Exception as e:
            logger.warning(f"⚠️ Position sizing calculation failed: {e}")
            return 0.05

    def _calculate_risk_score(self, confidence: float, training_level: float, volatility: float) -> float:
        """Calculate a composite risk score (0-1, higher = riskier)"""
        # Example: risk is high if volatility high or confidence low
        risk = volatility * (1.0 - confidence)
        risk *= (0.5 + training_level * 0.5)
        return max(0.0, min(1.0, risk))

    def _calculate_trade_urgency(self, action: int, confidence: float) -> float:
        """Calculate urgency for executing the trade (e.g., based on confidence and action type)"""
        if action == 0:
            return 1.0  # HOLD: lowest urgency
        urgency = 1.0 + confidence * 4.0  # scale from 1 to 5
        return min(5.0, urgency)

    def _estimate_hold_time(self, timeframe: str, confidence: float) -> float:
        """Estimate expected hold time (in hours) based on timeframe and confidence"""
        base_hours = {"1m": 0.5, "5m": 2, "15m": 6, "1h": 24}
        hours = base_hours.get(timeframe, 1)
        # If low confidence, shorter hold, if high, longer hold possibly
        hold = hours * (0.5 + confidence * 0.5)
        return hold

    def _generate_contextual_action(self, raw_action: int, symbol: str, confidence: float,
                                    position: Dict[str, Any], portfolio: Dict[str, Any],
                                    current_price: float) -> Dict[str, Any]:
        """Convert raw PPO action to position-aware contextual action with reasoning"""
        try:
            has_position = position['has_position']
            position_side = position['side']
            pnl_pct = position['pnl_pct']
            unrealized_pnl = position['unrealized_pnl']
            position_age = position['age_seconds']
            margin_utilization = portfolio['margin_utilization_pct']
            PROFIT_THRESHOLD = 2.0   # 2% profit threshold
            LOSS_THRESHOLD = -1.5    # -1.5% loss threshold
            HIGH_CONFIDENCE = 0.75
            VERY_HIGH_CONFIDENCE = 0.85
            action_name = None
            reasoning = ""
            should_execute = True
            urgency = 3
            # Action 0: HOLD
            if raw_action == 0:
                if not has_position:
                    action_name = "HOLD_FLAT"
                    reasoning = f"Model suggests HOLD with {confidence:.1%} confidence. No position to manage."
                    should_execute = False
                    urgency = 1
                elif position_side == 'LONG':
                    action_name = "HOLD_LONG"
                    if pnl_pct > PROFIT_THRESHOLD:
                        reasoning = f"Holding profitable LONG position (+{pnl_pct:.2f}%, ${unrealized_pnl:.2f} profit). Model confident to hold."
                        urgency = 2
                    elif pnl_pct < LOSS_THRESHOLD:
                        reasoning = f"Holding losing LONG position ({pnl_pct:.2f}%, ${unrealized_pnl:.2f} loss). Waiting for recovery."
                        urgency = 2
                    else:
                        reasoning = f"Holding LONG position near break-even ({pnl_pct:.2f}%). Monitoring for direction."
                        urgency = 1
                    should_execute = True
                elif position_side == 'SHORT':
                    action_name = "HOLD_SHORT"
                    if pnl_pct > PROFIT_THRESHOLD:
                        reasoning = f"Holding profitable SHORT position (+{pnl_pct:.2f}%, ${unrealized_pnl:.2f} profit). Model confident to hold."
                        urgency = 2
                    elif pnl_pct < LOSS_THRESHOLD:
                        reasoning = f"Holding losing SHORT position ({pnl_pct:.2f}%, ${unrealized_pnl:.2f} loss). Waiting for reversal."
                        urgency = 2
                    else:
                        reasoning = f"Holding SHORT position near break-even ({pnl_pct:.2f}%). Monitoring for direction."
                        urgency = 1
                    should_execute = True
            # Action 1: LONG
            elif raw_action == 1:
                if not has_position:
                    action_name = "OPEN_LONG"
                    reasoning = f"Opening new LONG position with {confidence:.1%} confidence at ${current_price:.4f}."
                    urgency = 4 if confidence >= VERY_HIGH_CONFIDENCE else 3
                    should_execute = True
                elif position_side == 'LONG':
                    if pnl_pct > PROFIT_THRESHOLD and confidence >= HIGH_CONFIDENCE:
                        action_name = "ADD_TO_LONG"
                        reasoning = f"Adding to profitable LONG (+{pnl_pct:.2f}%, ${unrealized_pnl:.2f}). Strong bullish signal with {confidence:.1%} confidence."
                        urgency = 4
                        should_execute = True
                    else:
                        action_name = "HOLD_LONG"
                        reasoning = f"Already LONG. Model suggests more upside but holding current position (PnL: {pnl_pct:.2f}%)."
                        urgency = 2
                        should_execute = True
                elif position_side == 'SHORT':
                    if confidence >= VERY_HIGH_CONFIDENCE:
                        action_name = "REVERSE_SHORT_TO_LONG"
                        reasoning = f"REVERSING: Closing SHORT (PnL: {pnl_pct:.2f}%) and opening LONG. Very high confidence {confidence:.1%} reversal signal."
                        urgency = 5
                        should_execute = True
                    else:
                        action_name = "HOLD_SHORT"
                        reasoning = f"Conflicting signal: SHORT position exists but model suggests LONG. Confidence {confidence:.1%} too low for reversal. Holding SHORT."
                        urgency = 2
                        should_execute = True
            # Action 2: SHORT
            elif raw_action == 2:
                if not has_position:
                    action_name = "OPEN_SHORT"
                    reasoning = f"Opening new SHORT position with {confidence:.1%} confidence at ${current_price:.4f}."
                    urgency = 4 if confidence >= VERY_HIGH_CONFIDENCE else 3
                    should_execute = True
                elif position_side == 'SHORT':
                    if pnl_pct > PROFIT_THRESHOLD and confidence >= HIGH_CONFIDENCE:
                        action_name = "ADD_TO_SHORT"
                        reasoning = f"Adding to profitable SHORT (+{pnl_pct:.2f}%, ${unrealized_pnl:.2f}). Strong bearish signal with {confidence:.1%} confidence."
                        urgency = 4
                        should_execute = True
                    else:
                        action_name = "HOLD_SHORT"
                        reasoning = f"Already SHORT. Model suggests more downside but holding current position (PnL: {pnl_pct:.2f}%)."
                        urgency = 2
                        should_execute = True
                elif position_side == 'LONG':
                    if confidence >= VERY_HIGH_CONFIDENCE:
                        action_name = "REVERSE_LONG_TO_SHORT"
                        reasoning = f"REVERSING: Closing LONG (PnL: {pnl_pct:.2f}%) and opening SHORT. Very high confidence {confidence:.1%} reversal signal."
                        urgency = 5
                        should_execute = True
                    else:
                        action_name = "HOLD_LONG"
                        reasoning = f"Conflicting signal: LONG position exists but model suggests SHORT. Confidence {confidence:.1%} too low for reversal. Holding LONG."
                        urgency = 2
                        should_execute = True
            # Action 3: CLOSE
            elif raw_action == 3:
                if not has_position:
                    action_name = "HOLD_FLAT"
                    reasoning = f"Close signal received but no position exists. Remaining flat."
                    should_execute = False
                    urgency = 1
                elif position_side == 'LONG':
                    if pnl_pct > PROFIT_THRESHOLD:
                        action_name = "TAKE_PROFIT_LONG"
                        reasoning = f"Taking profit on LONG: +{pnl_pct:.2f}% (${unrealized_pnl:.2f}). Model suggests exit with {confidence:.1%} confidence."
                        urgency = 4
                    elif pnl_pct < LOSS_THRESHOLD:
                        action_name = "STOP_LOSS_LONG"
                        reasoning = f"Stopping loss on LONG: {pnl_pct:.2f}% (${unrealized_pnl:.2f}). Model suggests cut losses with {confidence:.1%} confidence."
                        urgency = 5
                    else:
                        action_name = "CLOSE_LONG"
                        reasoning = f"Closing LONG position near break-even ({pnl_pct:.2f}%). Model suggests exit with {confidence:.1%} confidence."
                        urgency = 3
                    should_execute = True
                elif position_side == 'SHORT':
                    if pnl_pct > PROFIT_THRESHOLD:
                        action_name = "TAKE_PROFIT_SHORT"
                        reasoning = f"Taking profit on SHORT: +{pnl_pct:.2f}% (${unrealized_pnl:.2f}). Model suggests exit with {confidence:.1%} confidence."
                        urgency = 4
                    elif pnl_pct < LOSS_THRESHOLD:
                        action_name = "STOP_LOSS_SHORT"
                        reasoning = f"Stopping loss on SHORT: {pnl_pct:.2f}% (${unrealized_pnl:.2f}). Model suggests cut losses with {confidence:.1%} confidence."
                        urgency = 5
                    else:
                        action_name = "CLOSE_SHORT"
                        reasoning = f"Closing SHORT position near break-even ({pnl_pct:.2f}%). Model suggests exit with {confidence:.1%} confidence."
                        urgency = 3
                    should_execute = True
            # Default fallback
            if action_name is None:
                action_name = "HOLD_FLAT"
                reasoning = f"Unknown action state. Defaulting to HOLD_FLAT."
                should_execute = False
                urgency = 1
            # Add margin utilization warning if high
            if margin_utilization > 70:
                reasoning += f" ⚠️ Portfolio margin utilization: {margin_utilization:.1f}%"
            # Add position age context
            if has_position and position_age > 0:
                age_hours = position_age / 3600
                if age_hours < 1:
                    age_str = f"{position_age // 60}m"
                else:
                    age_str = f"{age_hours:.1f}h"
                reasoning += f" (Position age: {age_str})"
            return {
                'action': action_name,
                'raw_action': raw_action,
                'reasoning': reasoning,
                'should_execute': should_execute,
                'urgency': urgency
            }
        except Exception as e:
            logger.error(f"Failed to generate contextual action for {symbol}: {e}")
            return {
                'action': 'HOLD_FLAT',
                'raw_action': raw_action,
                'reasoning': f"Error generating contextual action: {e}",
                'should_execute': False,
                'urgency': 1
            }

    def _publish_decisions_with_reasoning(self, actions, confidences=None, prices=None, ts: float = None):
        """Publish detailed decisions with position sizing and natural language reasoning"""
        from config import get_live_config
        config = get_live_config()
        if not getattr(config, "PUBLISH_SIGNALS", True):
            return
        if not getattr(self, "env_index_map", None):
            self._init_env_index_map(getattr(self, 'env', None))
        now = ts or time.time()
        n = min(len(self.env_index_map), len(actions))
        for i in range(n):
            sym, tf = self.env_index_map[i]
            a = int(actions[i])
            c = float(confidences[i]) if confidences is not None else 1.0
            if c < getattr(config, "SIGNAL_CONFIDENCE_MIN", 0.0):
                continue
            current_position = self._get_current_position(sym, include_paper=True)
            portfolio_state = self._get_portfolio_state(include_paper=True)
            current_price = self._get_realtime_price(sym)
            if current_price == 0.0 and prices is not None and i < len(prices):
                current_price = float(prices[i])
            contextual_action = self._generate_contextual_action(
                raw_action=a,
                symbol=sym,
                confidence=c,
                position=current_position,
                portfolio=portfolio_state,
                current_price=current_price
            )
            if not contextual_action['should_execute']:
                logger.debug(f"Skipping signal for {sym}:{tf} - {contextual_action['action']}: {contextual_action['reasoning']}")
                continue
            training_level = self._calculate_training_level()
            market_volatility = self._estimate_market_volatility(sym, tf)
            recommended_leverage = self._calculate_optimal_leverage(sym, c, training_level, market_volatility)
            recommended_position_pct = self._calculate_optimal_position_size(c, training_level, market_volatility, tf)
            risk_score = self._calculate_risk_score(c, training_level, market_volatility)
            trade_urgency = self._calculate_trade_urgency(a, c)
            base_reasoning = self._generate_trade_reasoning(sym, tf, a, c, training_level, market_volatility,
                                                            recommended_position_pct, risk_score)
            enhanced_reasoning = f"{contextual_action['reasoning']}\n\nModel Analysis: {base_reasoning}"
            why_features, why_families = self._analyze_feature_importance(sym, tf)
            payload = {
                "timestamp": now,
                "symbol": sym,
                "timeframe": tf,
                "action": contextual_action['action'],
                "raw_action": a,
                "urgency": contextual_action['urgency'],
                "confidence": c,
                "model": "ppo_masa",
                "source": getattr(config, "PUBLISH_SOURCE_TAG", "trainer"),
                "current_position": {
                    "has_position": current_position['has_position'],
                    "side": current_position['side'],
                    "size": current_position['size'],
                    "entry_price": current_position['entry_price'],
                    "current_price": current_price,
                    "unrealized_pnl": current_position['unrealized_pnl'],
                    "pnl_pct": current_position['pnl_pct'],
                    "leverage": current_position['leverage'],
                    "margin_used": current_position['margin_used'],
                    "age_seconds": current_position['age_seconds'],
                    "is_paper": current_position['is_paper']
                },
                "portfolio": {
                    "total_balance": portfolio_state['total_balance'],
                    "available_balance": portfolio_state['available_balance'],
                    "total_margin_used": portfolio_state['total_margin_used'],
                    "margin_utilization_pct": portfolio_state['margin_utilization_pct'],
                    "unrealized_pnl": portfolio_state['unrealized_pnl'],
                    "is_paper": portfolio_state['is_paper']
                },
                "training_level": float(training_level),
                "market_volatility": float(market_volatility),
                "recommended_leverage": int(recommended_leverage),
                "recommended_position_pct": float(recommended_position_pct),
                "risk_score": float(risk_score),
                "trade_urgency": float(trade_urgency),
                "expected_hold_time": self._estimate_hold_time(tf, c),
                "reasoning": enhanced_reasoning,
                "why_features": [{"name": n, "score": float(s)} for n, s in (why_features or [])[:10]],
                "why_families": {k: float(v) for k, v in (why_families or {}).items()}
            }
            try:
                self._signal_redis.xadd(
                    config.SIGNAL_OUTPUT_STREAM,
                    {"data": json.dumps(payload, separators=(",", ":"))},
                    maxlen=config.SIGNAL_STREAM_MAXLEN,
                    approximate=True,
                )
                # Also store the last decision in a Redis hash for quick access
                self._signal_redis.hset(
                    f"{config.SIGNAL_OUTPUT_STREAM}:last:{sym}:{tf}",
                    mapping={k: (json.dumps(v) if not isinstance(v, (int, float, str)) else v) for k, v in payload.items()}
                )
                logger.info(f"📊 {sym}:{tf} → {contextual_action['action']} (confidence={c:.1%}, urgency={contextual_action['urgency']}/5)")
                if current_position['has_position']:
                    logger.debug(f"   Position: {current_position['side']} {current_position['size']:.6f} @ ${current_position['entry_price']:.4f} (PnL: {current_position['pnl_pct']:.2f}%)")
            except Exception as e:
                logger.exception(f"Failed to publish decision for {sym}: {e}")

    def _publish_decision_legacy(self, symbol, tf, action, model_conf, correlator_conf, why_feats, why_fams, ppo_logits, masa_logits, blended_logits):
        """Helper to publish a decision payload"""
        import json, time
        if not hasattr(self, "_signal_redis") or self._signal_redis is None:
            return
        ts_ms = int(time.time() * 1000)
        training_level = self._calculate_training_level()
        market_volatility = self._estimate_market_volatility(symbol, tf)
        recommended_leverage = self._calculate_optimal_leverage(symbol, model_conf, training_level, market_volatility)
        recommended_position_pct = self._calculate_optimal_position_size(model_conf, training_level, market_volatility, tf)
        enhanced_reasoning = self._generate_trade_reasoning(
            symbol, tf, action, model_conf, training_level, market_volatility,
            recommended_position_pct, self._calculate_risk_score(model_conf, training_level, market_volatility)
        )
        payload = {
            "ts_ms": ts_ms, "symbol": symbol, "timeframe": tf, "action": int(action),
            "model_confidence": float(model_conf), "correlator_confidence": float(correlator_conf),
            "ppo_logit": ppo_logits, "masa_logit": masa_logits, "blended_logit": blended_logits,
            "why_features": [{"name": n, "score": float(s)} for n, s in (why_feats or [])[:10]],
            "why_families": {k: float(v) for k, v in (why_fams or {}).items()},
            "training_level": float(training_level),
            "market_volatility": float(market_volatility),
            "recommended_leverage": int(recommended_leverage),
            "recommended_position_pct": float(recommended_position_pct),
            "risk_score": float(self._calculate_risk_score(model_conf, training_level, market_volatility)),
            "trade_urgency": float(self._calculate_trade_urgency(action, model_conf)),
            "expected_hold_time": self._estimate_hold_time(tf, model_conf),
            "reasoning": enhanced_reasoning,
            "action_name": {-1: "SELL", 0: "HOLD", 1: "BUY", 2: "SHORT", 3: "CLOSE"}.get(action, "UNKNOWN")
        }
        try:
            self._signal_redis.xadd("wma:trainer:predictions", {"data": json.dumps(payload)})
            self._signal_redis.hset(f"wma:trainer:predictions:last:{symbol}:{tf}",
                                    mapping={k: (json.dumps(v) if not isinstance(v,(int,float,str)) else v) for k, v in payload.items()})
            if self.telegram_notifier and model_conf >= 0.75 and action != 0:
                try:
                    import asyncio
                    signal_data = payload.copy()
                    signal_data['confidence'] = model_conf
                    signal_data['source'] = 'trainer'
                    signal_data['alert_type'] = 'prediction'
                    action_name = {1: "LONG", 2: "SHORT"}.get(action, "HOLD")
                    confidence_emoji = "🔥" if model_conf >= 0.9 else "✅" if model_conf >= 0.8 else "⚠️"
                    def send_telegram_alert():
                        try:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            alert_message = f"""
🤖 <b>TRADING SIGNAL GENERATED</b>

<b>Symbol:</b> {symbol}
<b>Timeframe:</b> {tf}
<b>Action:</b> {action_name}
<b>Confidence:</b> {model_conf:.1%} {confidence_emoji}

<b>Trading Parameters:</b>
• Recommended Leverage: {int(recommended_leverage)}x
• Position Size: {recommended_position_pct:.1f}%
• Risk Score: {payload.get('risk_score', 0):.2f}
• Expected Hold: {payload.get('expected_hold_time', 'Unknown')}

<b>Model Details:</b>
• PPO Logit: {ppo_logits:.3f}
• MASA Logit: {masa_logits:.3f}
• Training Level: {training_level:.1%}

<b>Reasoning:</b> {payload.get('reasoning', 'AI analysis complete')}
""".strip()
                            loop.run_until_complete(self.telegram_notifier.send_message(
                                alert_message, parse_mode="HTML", forward_to_private=True
                            ))
                            loop.close()
                        except Exception as e:
                            logger.warning(f"⚠️ Telegram alert failed: {e}")
                    threading.Thread(target=send_telegram_alert, daemon=True).start()
                except Exception as e:
                    logger.warning(f"⚠️ Failed to send telegram alert: {e}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to publish decision: {e}")

    def _pre_warm_gpu(self, vec_env):
        """Pre-warm GPU with intensive operations"""
        if not torch.cuda.is_available():
            return
        try:
            dummy_obs = torch.randn(self.config.n_envs * 1000, 1430, device=self.config.device)
            dummy_actions = torch.randint(0, 10, (self.config.n_envs * 1000,), device=self.config.device)
            for _ in range(10):
                with torch.no_grad():
                    try:
                        prediction_result = self.ppo_model.policy.predict(dummy_obs, deterministic=False)
                        if isinstance(prediction_result, (tuple, list)):
                            for item in prediction_result:
                                if hasattr(item, 'cpu'):
                                    _ = item.cpu()
                        elif hasattr(prediction_result, 'cpu'):
                            _ = prediction_result.cpu()
                        _ = torch.matmul(dummy_obs, dummy_obs.T)
                        _ = torch.nn.functional.relu(dummy_obs @ dummy_obs.T)
                    except Exception as predict_error:
                        logger.warning(f"⚠️ PPO prediction failed during pre-warming: {predict_error}")
                        _ = torch.matmul(dummy_obs, dummy_obs.T)
                        _ = torch.nn.functional.relu(dummy_obs @ dummy_obs.T)
            del dummy_obs, dummy_actions
            torch.cuda.synchronize()
            logger.info("✅ GPU pre-warming completed")
        except Exception as e:
            logger.warning(f"⚠️ GPU pre-warming failed: {e}")

    def _get_gpu_utilization(self) -> float:
        """Get current GPU utilization percentage"""
        try:
            import subprocess
            result = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader,nounits'],
                                    capture_output=True, text=True, timeout=5)
            return float(result.stdout.strip())
        except:
            return 0.0

    def _create_training_callback(self):
        """Create training callback for monitoring and periodic updates"""
        class GPUTrainingCallback(BaseCallback):
            def __init__(self, trainer, verbose=0):
                super().__init__(verbose)
                self.trainer = trainer
                self.step_count = 0

            def _on_step(self) -> bool:
                self.step_count += 1
                # Update MASA agent every N steps if enabled
                if (self.trainer.masa_agent is not None and
                        self.step_count % self.trainer.config.masa_update_freq == 0):
                    try:
                        self._update_masa_agent()
                    except Exception as e:
                        logger.warning(f"⚠️ MASA update failed at step {self.step_count}: {e}")
                # Log MASA status occasionally
                if self.step_count % 1000 == 0:
                    masa_status = 'ON' if self.trainer.masa_agent else 'OFF'
                    logger.info(f"🧠 MASA {masa_status}; PPO+MASA blending logged at step {self.step_count}")
                return True

            def _update_masa_agent(self):
                """Update MASA agent with recent experience"""
                try:
                    # Get rollout buffer data
                    obs = self.trainer.ppo_model.rollout_buffer.observations
                    actions = self.trainer.ppo_model.rollout_buffer.actions
                    advantages = self.trainer.ppo_model.rollout_buffer.advantages
                    # Update MASA agent with this batch of experiences
                    self.trainer.masa_agent.update(obs, actions, advantages)
                    logger.debug(f"✅ MASA agent updated at step {self.step_count}")
                except Exception as e:
                    logger.warning(f"⚠️ MASA agent update error: {e}")

        return GPUTrainingCallback(trainer=self)
