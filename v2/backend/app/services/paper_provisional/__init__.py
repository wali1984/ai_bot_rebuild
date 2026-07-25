"""Normal autonomous 100-row paper checkpoint policy (paper-only, never live)."""

from v2.backend.app.services.paper_provisional.policy_v1 import (
    DEFAULT_PROVISIONAL_MAX_NOTIONAL_USD,
    PAPER_PROVISIONAL_CHECKPOINT_CLASSIFICATION,
    PAPER_PROVISIONAL_MIN_TRAIN_ROWS,
    STRICT_CHAMPION_MIN_TRAIN_ROWS,
    PaperProvisionalCheckpointPolicyV1,
    PaperProvisionalLimitsV1,
    cohort_identity,
    load_paper_provisional_policy_v1,
    minimum_valid_notional,
    provisional_notional_plan,
)

__all__ = [
    "PAPER_PROVISIONAL_CHECKPOINT_CLASSIFICATION",
    "PAPER_PROVISIONAL_MIN_TRAIN_ROWS",
    "STRICT_CHAMPION_MIN_TRAIN_ROWS",
    "PaperProvisionalCheckpointPolicyV1",
    "PaperProvisionalLimitsV1",
    "DEFAULT_PROVISIONAL_MAX_NOTIONAL_USD",
    "cohort_identity",
    "minimum_valid_notional",
    "provisional_notional_plan",
    "load_paper_provisional_policy_v1",
]
