"""V2 RL core service package.

This package houses the partially-migrated RL core for V2. It is paper-only and
strictly non-live:

- the observation schema is a declarative descriptor, not a runtime tensor builder
- the reward functions are pure CPU implementations for paper outcomes only
- the checkpoint metadata adapter parses legacy filenames; it does NOT load
  PyTorch state
- the confidence calibration adapter is a pure temperature-scaling math helper

The PPO+MASA policy network, Gymnasium env step/reset loop, and GPU training loop
remain MISSING_IN_V2 and are honestly reported as such by
:class:`RLCoreService.current_paper_only_status`.
"""

from .observation_schema import (
    LEGACY_OBS_SHA256,
    V2_OBSERVATION_SCHEMA,
    V2ObservationField,
    observation_field_names,
    observation_schema_completeness,
)
from .reward import (
    REWARD_CLAMP_DEFAULT,
    LEGACY_CONSTRAINED_REWARD_SHA256,
    LEGACY_FEE_RATIO_REWARD_SHAPING_SHA256,
    LEGACY_REWARD_FUNCTIONS_SHA256,
    RewardComponents,
    compute_constrained_reward,
)
from .checkpoint_metadata import (
    CheckpointMetadata,
    parse_legacy_checkpoint_filename,
)
from .service import (
    LIVE_GATE_STATUS,
    RL_CORE_SUBPROJECT_BLOCKED,
    RL_CORE_SUBPROJECT_PARTIALLY_MIGRATED,
    RLCoreService,
    calibrate_confidence,
)

__all__ = [
    "LEGACY_OBS_SHA256",
    "V2_OBSERVATION_SCHEMA",
    "V2ObservationField",
    "observation_field_names",
    "observation_schema_completeness",
    "REWARD_CLAMP_DEFAULT",
    "LEGACY_CONSTRAINED_REWARD_SHA256",
    "LEGACY_FEE_RATIO_REWARD_SHAPING_SHA256",
    "LEGACY_REWARD_FUNCTIONS_SHA256",
    "RewardComponents",
    "compute_constrained_reward",
    "CheckpointMetadata",
    "parse_legacy_checkpoint_filename",
    "LIVE_GATE_STATUS",
    "RL_CORE_SUBPROJECT_BLOCKED",
    "RL_CORE_SUBPROJECT_PARTIALLY_MIGRATED",
    "RLCoreService",
    "calibrate_confidence",
]
