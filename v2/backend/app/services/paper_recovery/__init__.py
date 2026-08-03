"""Isolated paper-recovery lane.

This package holds the single, self-contained recovery policy that permits a
bounded, explicitly-tagged paper-only inference/execution lane while every
strict promotion, PIT and live-readiness gate stays unchanged and stricter.

Nothing in this package may authorise a live route, an exchange action, or a
strict-promotable / trainer-eligible artifact.  See ``PaperRecoveryPolicyV1``.
"""

from .paper_recovery_policy_v1 import (
    RECOVERY_LIVE_DENY_REASON,
    SNAPSHOT_PIT_WAIVER_FIELDS,
    PaperRecoveryPolicyV1,
    PaperRecoveryWaiverError,
    load_paper_recovery_policy_v1,
    snapshot_recovery_waiver_receipt,
)

__all__ = [
    "PaperRecoveryPolicyV1",
    "PaperRecoveryWaiverError",
    "RECOVERY_LIVE_DENY_REASON",
    "SNAPSHOT_PIT_WAIVER_FIELDS",
    "load_paper_recovery_policy_v1",
    "snapshot_recovery_waiver_receipt",
]
