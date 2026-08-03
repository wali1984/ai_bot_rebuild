"""V2-native RL/MASA/PPO CUDA trainer package.

This package is the V2-owned trainer implementation surface. It uses the
copied legacy RL files only as behavior references and never imports or launches
the raw legacy trainer at runtime.
"""
from .config import (
    ACTION_LABELS,
    LIVE_GATE_BLOCKED,
    MODEL_SOURCE,
    TRAINER_SOURCE,
    TRAINER_CORE_PAPER_SHADOW_GO_NO_GO,
    HybridTrainerConfig,
)
from .data_loader import TrainingExample, V2HybridTrainerDataLoader
from .environment import V2PaperShadowHybridEnv
from .model import V2HybridPolicyModel
from .parallel_env import ParallelEnvRolloutResult, run_parallel_env_rollout_proof
from .publisher import V2HybridPredictionPublisher
from .runtime import run_hybrid_trainer_cycle
from .tensor_builder import FeatureTensorRecord, V2UnifiedFeatureTensorBuilder

__all__ = (
    "ACTION_LABELS",
    "FeatureTensorRecord",
    "HybridTrainerConfig",
    "LIVE_GATE_BLOCKED",
    "MODEL_SOURCE",
    "ParallelEnvRolloutResult",
    "TRAINER_SOURCE",
    "TRAINER_CORE_PAPER_SHADOW_GO_NO_GO",
    "TrainingExample",
    "V2HybridPolicyModel",
    "V2HybridPredictionPublisher",
    "V2HybridTrainerDataLoader",
    "V2PaperShadowHybridEnv",
    "V2UnifiedFeatureTensorBuilder",
    "run_parallel_env_rollout_proof",
    "run_hybrid_trainer_cycle",
)
