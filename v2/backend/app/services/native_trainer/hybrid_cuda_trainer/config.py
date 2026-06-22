"""Configuration and constants for the V2 hybrid CUDA trainer."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

LIVE_GATE_BLOCKED = "blocked_human_only"
TRAINER_SOURCE = "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW"
MODEL_SOURCE = "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"
CHECKPOINT_SOURCE = "V2_LOCAL_TRAINED"
TRAINER_CORE_PAPER_SHADOW_GO_NO_GO = (
    "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_FULL_FUNCTION_PARITY_READY"
)

ACTION_LABELS = (
    "hold",
    "long",
    "short",
    "close_long",
    "close_short",
    "reduce",
    "hedge_reserved_fail_closed",
)
ACTION_INDEX = {label: i for i, label in enumerate(ACTION_LABELS)}
ACTION_COUNT = len(ACTION_LABELS)

DEFAULT_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
DEFAULT_MIN_DATA_COVERAGE_PERCENT = 70.0
DEFAULT_MIN_CONFIDENCE_CALIBRATED = 0.55
DEFAULT_MIN_EDGE_AFTER_COST_BPS = 4.0
DEFAULT_MAX_TRAINING_ROWS_PER_CYCLE = 32768
DEFAULT_BATCH_SIZE = 32768
DEFAULT_ROLLOUT_N_STEPS = 512
DEFAULT_ROLLOUT_MAX_ENVS = 256
DEFAULT_PARALLEL_ENV_WORKERS = 32

REDIS_HEARTBEAT_KEY = "v2:trainer:hybrid_cuda:heartbeat"
REDIS_STATUS_KEY = "v2:trainer:hybrid_cuda:status"
REDIS_METRICS_KEY = "v2:trainer:hybrid_cuda:metrics"
PREDICTION_KEY_TEMPLATE = "v2:prediction:{symbol}:{timeframe}"
RISK_DECISIONS_KEY = "v2:trainer:hybrid_cuda:risk_decision_preview"
ORCHESTRATOR_DECISIONS_KEY = "v2:trainer:hybrid_cuda:orchestrator_decision_preview"
PAPER_INTENTS_KEY = "v2:trainer:hybrid_cuda:paper_intent_preview"
PAPER_LEDGER_KEY = "v2:trainer:hybrid_cuda:paper_ledger_preview"
PAPER_POSITIONS_KEY = "v2:trainer:hybrid_cuda:paper_positions_preview"
PAPER_BLOCK_REASONS_KEY = "v2:trainer:hybrid_cuda:paper_block_reasons"
PAPER_SIGNAL_LINEAGE_KEY = "v2:trainer:hybrid_cuda:paper_signal_lineage_preview"
PAPER_SIGNAL_KEY_TEMPLATE = "v2:trainer:hybrid_cuda:signals:paper:{symbol}"
PAPER_SIGNAL_TIMEFRAME_KEY_TEMPLATE = "v2:trainer:hybrid_cuda:signals:paper:{symbol}:{timeframe}"

LEGACY_BEHAVIOR_REFERENCES = {
    "environment": "v2/legacy_owned_runtime/rl/environment.py",
    "gymnasium_wrapper": "v2/legacy_owned_runtime/rl/gymnasium_wrapper.py",
    "obs_schema": "v2/legacy_owned_runtime/rl/obs_schema.py",
    "unified_feature_builder": "v2/legacy_owned_runtime/rl/unified_feature_builder.py",
    "masa_agent": "v2/legacy_owned_runtime/rl/agents/masa_agent.py",
    "enhanced_architectures": "v2/legacy_owned_runtime/rl/enhanced_architectures.py",
    "gpu_cnn_policy": "v2/legacy_owned_runtime/rl/gpu_cnn_policy.py",
    "reward_functions": "v2/legacy_owned_runtime/rl/reward_functions.py",
    "constrained_reward": "v2/legacy_owned_runtime/rl/constrained_reward.py",
    "fee_ratio_reward_shaping": "v2/legacy_owned_runtime/rl/fee_ratio_reward_shaping.py",
    "hedge_reward_functions": "v2/legacy_owned_runtime/rl/hedge_reward_functions.py",
    "checkpoint_manager": "v2/legacy_owned_runtime/rl/checkpoint_manager.py",
    "confidence_gates": "v2/legacy_owned_runtime/rl/confidence_gates.py",
    "calibrated_confidence": "v2/legacy_owned_runtime/rl/calibrated_confidence.py",
    "hybrid_trainer": "v2/legacy_owned_runtime/rl/hybrid_trainer.py",
}

LEGACY_HYBRID_PARITY_BASELINE = {
    "legacy_trainer": "v2/legacy_owned_runtime/rl/hybrid_trainer.py",
    "legacy_masa_agent": "v2/legacy_owned_runtime/rl/agents/masa_agent.py",
    "legacy_core_capabilities": [
        "stable_baselines3_ppo_with_gpu_forced_training",
        "masa_agent_network_and_hybrid_ppo_blending",
        "subproc_vec_env_symbol_timeframe_rollouts",
        "continuous_hybrid_train_and_predict_loop",
        "realtime_prediction_publisher_with_multi_timeframe_alignment",
        "checkpoint_resume_and_cleanup",
        "adaptive_confidence_thresholds",
        "return_head_training",
        "risk_signal_profit_liquidation_context_gates",
    ],
    "v2_safe_scope": [
        "v2_only_redis_writes",
        "paper_shadow_only_predictions",
        "dynamic_symbol_resolution_without_trader_execution",
        "trainer_to_orchestrator_to_risk_to_paper_lineage",
    ],
}


@dataclass(frozen=True)
class HybridTrainerConfig:
    """Runtime config for one paper/shadow training cycle."""

    symbols: tuple[str, ...] = field(default_factory=lambda: tuple(resolve_symbols()))
    timeframes: tuple[str, ...] = DEFAULT_TIMEFRAMES
    model_dir: Path = Path(".local_models/v2_native_rl_masa_ppo")
    min_data_coverage_percent: float = DEFAULT_MIN_DATA_COVERAGE_PERCENT
    min_confidence_calibrated: float = DEFAULT_MIN_CONFIDENCE_CALIBRATED
    min_edge_after_cost_bps: float = DEFAULT_MIN_EDGE_AFTER_COST_BPS
    fee_bps_per_side: float = 5.0
    slippage_bps_per_side: float = 1.0
    max_training_rows_per_cycle: int = DEFAULT_MAX_TRAINING_ROWS_PER_CYCLE
    validation_fraction: float = 0.2
    ppo_clip_epsilon: float = 0.2
    train_steps: int = 256
    batch_size: int = DEFAULT_BATCH_SIZE
    rollout_n_steps: int = DEFAULT_ROLLOUT_N_STEPS
    rollout_max_envs: int = DEFAULT_ROLLOUT_MAX_ENVS
    parallel_env_workers: int = DEFAULT_PARALLEL_ENV_WORKERS
    allow_weight_artifact_write: bool = True
    risk_caps_configured: bool = False
    live_gate: str = LIVE_GATE_BLOCKED
    live_symbols: tuple[str, ...] = field(default_factory=tuple)

    def validate_safety(self) -> None:
        if self.live_gate != LIVE_GATE_BLOCKED:
            raise ValueError("live_gate must stay blocked_human_only")
        if self.live_symbols:
            raise ValueError("live_symbols must remain empty")
        model_dir_text = str(self.model_dir)
        if self.allow_weight_artifact_write and not (
            model_dir_text.startswith(".local_models") or "/.local_models/" in model_dir_text
        ):
            raise ValueError("model artifacts may only be written under .local_models")
