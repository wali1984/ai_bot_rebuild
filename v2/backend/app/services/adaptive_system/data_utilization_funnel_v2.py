"""Data-utilization funnel — FINAL PASS Phase 7 / task FP-080 telemetry.

Makes the training-corpus pipeline observable end to end so a green status can
never conceal a dead downstream stage. Every drop between two adjacent stages
MUST have an exact, enumerated exclusion reason whose counts reconcile with the
drop — otherwise the funnel is INCONSISTENT and fails closed.

Stages (raw -> trained), each a monotonically non-increasing count:

    raw_events
    canonical_events
    feature_snapshots
    finality_proven_snapshots
    cost_complete_snapshots
    microstructure_complete_snapshots
    labeled_snapshots
    candidate_outcome_rows
    training_eligible_rows
    rows_used_by_active_checkpoint

This module computes and validates the funnel from supplied counts; a thin
collector (elsewhere) gathers those counts from the real stores. Pure + testable.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

SCHEMA_VERSION = "data_utilization_funnel_v2"
REDIS_KEY = "v2:training:data_utilization_funnel"

# Ordered funnel stages (each count <= the previous stage's count).
STAGES: Sequence[str] = (
    "raw_events",
    "canonical_events",
    "feature_snapshots",
    "finality_proven_snapshots",
    "cost_complete_snapshots",
    "microstructure_complete_snapshots",
    "labeled_snapshots",
    "candidate_outcome_rows",
    "training_eligible_rows",
    "rows_used_by_active_checkpoint",
)


@dataclass(frozen=True)
class DataUtilizationFunnel:
    stage_counts: Mapping[str, int]
    # {from_stage: {reason: count}} — reasons for the drop into the NEXT stage.
    exclusions_by_stage: Mapping[str, Mapping[str, int]]
    consistent: bool
    inconsistencies: Sequence[str]
    overall_utilization_rate: float | None
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "redis_key": REDIS_KEY,
            "stage_counts": {s: int(self.stage_counts.get(s, 0)) for s in STAGES},
            "exclusions_by_stage": {
                s: {str(k): int(v) for k, v in (self.exclusions_by_stage.get(s) or {}).items()}
                for s in STAGES
            },
            "consistent": self.consistent,
            "inconsistencies": list(self.inconsistencies),
            "overall_utilization_rate": self.overall_utilization_rate,
        }


def build_funnel(
    stage_counts: Mapping[str, int],
    exclusions_by_stage: Mapping[str, Mapping[str, int]] | None = None,
) -> DataUtilizationFunnel:
    """Validate monotonicity + reconcile every drop with enumerated reasons."""
    exclusions_by_stage = exclusions_by_stage or {}
    inconsistencies: list[str] = []

    # every stage must be a non-negative int
    counts: dict[str, int] = {}
    for s in STAGES:
        v = stage_counts.get(s)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            inconsistencies.append(f"STAGE_COUNT_INVALID:{s}")
            counts[s] = 0
        else:
            counts[s] = v

    # monotonic non-increasing + drop reconciliation
    for i in range(len(STAGES) - 1):
        cur, nxt = STAGES[i], STAGES[i + 1]
        drop = counts[cur] - counts[nxt]
        if drop < 0:
            inconsistencies.append(f"STAGE_NOT_MONOTONIC:{cur}->{nxt}:{counts[cur]}<{counts[nxt]}")
            continue
        if drop > 0:
            reasons = exclusions_by_stage.get(cur) or {}
            reason_total = sum(int(v) for v in reasons.values() if isinstance(v, int))
            if not reasons:
                inconsistencies.append(f"UNEXPLAINED_DROP:{cur}->{nxt}:count={drop}")
            elif reason_total != drop:
                inconsistencies.append(
                    f"DROP_REASONS_DO_NOT_RECONCILE:{cur}->{nxt}:drop={drop}:reasons_sum={reason_total}"
                )

    raw = counts[STAGES[0]]
    used = counts[STAGES[-1]]
    rate = (used / raw) if raw > 0 else None

    return DataUtilizationFunnel(
        stage_counts=counts,
        exclusions_by_stage=exclusions_by_stage,
        consistent=not inconsistencies,
        inconsistencies=inconsistencies,
        overall_utilization_rate=rate,
    )


__all__ = [
    "SCHEMA_VERSION",
    "REDIS_KEY",
    "STAGES",
    "DataUtilizationFunnel",
    "build_funnel",
]
