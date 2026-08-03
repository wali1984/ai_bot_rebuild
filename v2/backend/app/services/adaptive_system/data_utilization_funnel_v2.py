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
    stages: Sequence[str] = STAGES

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "redis_key": REDIS_KEY,
            "stage_counts": {s: int(self.stage_counts.get(s, 0)) for s in self.stages},
            "exclusions_by_stage": {
                s: {str(k): int(v) for k, v in (self.exclusions_by_stage.get(s) or {}).items()}
                for s in self.stages
            },
            "consistent": self.consistent,
            "inconsistencies": list(self.inconsistencies),
            "overall_utilization_rate": self.overall_utilization_rate,
        }


def _validated_exclusions(
    stages: Sequence[str],
    exclusions_by_stage: Mapping[str, Mapping[str, int]],
    inconsistencies: list[str],
) -> dict[str, dict[str, int]]:
    """Normalize exclusions without accepting bools, negatives, or ghost stages."""

    known = set(stages)
    normalized: dict[str, dict[str, int]] = {stage: {} for stage in stages}
    for stage, reasons in exclusions_by_stage.items():
        if stage not in known:
            inconsistencies.append(f"EXCLUSION_STAGE_UNKNOWN:{stage}")
            continue
        if not isinstance(reasons, Mapping):
            inconsistencies.append(f"EXCLUSION_REASONS_INVALID:{stage}")
            continue
        for reason, count in reasons.items():
            if not isinstance(reason, str) or not reason.strip() or reason.strip() != reason:
                inconsistencies.append(f"EXCLUSION_REASON_INVALID:{stage}")
                continue
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                inconsistencies.append(f"EXCLUSION_COUNT_INVALID:{stage}:{reason}")
                continue
            if count == 0:
                inconsistencies.append(f"EXCLUSION_COUNT_ZERO:{stage}:{reason}")
                continue
            normalized[stage][reason] = count
    return normalized


def build_path_funnel(
    stages: Sequence[str],
    stage_counts: Mapping[str, int],
    exclusions_by_stage: Mapping[str, Mapping[str, int]] | None = None,
) -> DataUtilizationFunnel:
    """Build one identity-coherent path with exact adjacent-stage exclusions.

    The original FINAL PASS counter list spans different identity domains
    (market events, feature snapshots, candidate decisions, and checkpoint
    rows).  Those domains must not be subtracted from one another.  This helper
    therefore accepts an explicit path; callers build separate paths and keep
    cross-domain inventories as counters rather than manufacturing a flat
    monotonic funnel.
    """

    ordered = tuple(stages)
    inconsistencies: list[str] = []
    if not ordered or any(not isinstance(stage, str) or not stage for stage in ordered):
        inconsistencies.append("PATH_STAGES_INVALID")
    if len(set(ordered)) != len(ordered):
        inconsistencies.append("PATH_STAGES_DUPLICATED")

    counts: dict[str, int] = {}
    for stage in ordered:
        value = stage_counts.get(stage)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            inconsistencies.append(f"STAGE_COUNT_INVALID:{stage}")
            counts[stage] = 0
        else:
            counts[stage] = value
    for unknown in sorted(set(stage_counts) - set(ordered)):
        inconsistencies.append(f"STAGE_COUNT_UNKNOWN:{unknown}")

    normalized = _validated_exclusions(
        ordered,
        exclusions_by_stage or {},
        inconsistencies,
    )
    for index in range(len(ordered) - 1):
        current, following = ordered[index], ordered[index + 1]
        drop = counts[current] - counts[following]
        if drop < 0:
            inconsistencies.append(
                f"STAGE_NOT_MONOTONIC:{current}->{following}:"
                f"{counts[current]}<{counts[following]}"
            )
            continue
        reasons = normalized[current]
        reason_total = sum(reasons.values())
        if drop == 0 and reason_total:
            inconsistencies.append(
                f"EXCLUSIONS_WITHOUT_DROP:{current}->{following}:reasons_sum={reason_total}"
            )
        elif drop > 0 and not reasons:
            inconsistencies.append(f"UNEXPLAINED_DROP:{current}->{following}:count={drop}")
        elif drop > 0 and reason_total != drop:
            inconsistencies.append(
                f"DROP_REASONS_DO_NOT_RECONCILE:{current}->{following}:"
                f"drop={drop}:reasons_sum={reason_total}"
            )

    first = counts.get(ordered[0], 0) if ordered else 0
    last = counts.get(ordered[-1], 0) if ordered else 0
    return DataUtilizationFunnel(
        stage_counts=counts,
        exclusions_by_stage=normalized,
        consistent=not inconsistencies,
        inconsistencies=inconsistencies,
        overall_utilization_rate=(last / first) if first > 0 else None,
        stages=ordered,
    )


def build_funnel(
    stage_counts: Mapping[str, int],
    exclusions_by_stage: Mapping[str, Mapping[str, int]] | None = None,
) -> DataUtilizationFunnel:
    """Validate monotonicity + reconcile every drop with enumerated reasons."""
    return build_path_funnel(STAGES, stage_counts, exclusions_by_stage)


__all__ = [
    "SCHEMA_VERSION",
    "REDIS_KEY",
    "STAGES",
    "DataUtilizationFunnel",
    "build_path_funnel",
    "build_funnel",
]
