"""First-class closed-loop runtime package for Spark migration.

The implementation in this package promotes the existing worklog-oriented
runtime behavior into a SQLite-backed control plane with explicit task, lease,
and worker truth tables.
"""

from __future__ import annotations

from .lane_registry import (
    LaneConfig,
    LANE_REGISTRY,
    get_group_for_mission_category,
    lane_group_ids,
)

__all__ = [
    "LaneConfig",
    "LANE_REGISTRY",
    "get_group_for_mission_category",
    "lane_group_ids",
]
