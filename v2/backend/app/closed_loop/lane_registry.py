"""Mission-classified lane registry for Spark runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LaneConfig:
    lane_group: str
    worker_kind: str
    mission_categories: tuple[str, ...]
    max_parallel: int
    review_of: str | None = None


LANE_REGISTRY: tuple[LaneConfig, ...] = (
    LaneConfig(
        lane_group="runtime-claude",
        worker_kind="claude",
        mission_categories=(
            "runtime_stability",
            "production_equivalence",
            "ingestor",
        ),
        max_parallel=2,
    ),
    LaneConfig(
        lane_group="model-claude",
        worker_kind="claude",
        mission_categories=(
            "trainer_model",
            "checkpoint_contract",
            "model_policy_readiness",
        ),
        max_parallel=1,
    ),
    LaneConfig(
        lane_group="proof-claude",
        worker_kind="claude",
        mission_categories=(
            "paper_edge",
            "observation_completeness",
            "decision_match",
            "risk_control",
        ),
        max_parallel=1,
    ),
    LaneConfig(
        lane_group="runtime-codex",
        worker_kind="codex",
        mission_categories=(),
        max_parallel=2,
        review_of="runtime-claude",
    ),
    LaneConfig(
        lane_group="model-codex",
        worker_kind="codex",
        mission_categories=(),
        max_parallel=1,
        review_of="model-claude",
    ),
    LaneConfig(
        lane_group="proof-codex",
        worker_kind="codex",
        mission_categories=(),
        max_parallel=1,
        review_of="proof-claude",
    ),
)


def lane_group_ids() -> tuple[str, ...]:
    return tuple(item.lane_group for item in LANE_REGISTRY)


def get_lane(lane_group: str) -> LaneConfig | None:
    for cfg in LANE_REGISTRY:
        if cfg.lane_group == lane_group:
            return cfg
    return None


def get_group_for_mission_category(mission_category: str | None) -> str | None:
    category = _normalize_key(mission_category or "")
    for cfg in LANE_REGISTRY:
        if cfg.worker_kind != "claude":
            continue
        for mission in cfg.mission_categories:
            if _normalize_key(mission) == category:
                return cfg.lane_group
    # Backward compatible aliases
    legacy_map: dict[str, str] = {
        _normalize_key("paper edge"): "proof-claude",
        _normalize_key("observation completeness"): "proof-claude",
        _normalize_key("decision match"): "proof-claude",
        _normalize_key("risk control"): "proof-claude",
        _normalize_key("runtime stability"): "runtime-claude",
        _normalize_key("production equivalence"): "runtime-claude",
        _normalize_key("ingestor"): "runtime-claude",
        _normalize_key("trainer model"): "model-claude",
        _normalize_key("checkpoint contract"): "model-claude",
        _normalize_key("model/policy readiness"): "model-claude",
        _normalize_key("model_policy_readiness"): "model-claude",
        _normalize_key("symbol selection"): "runtime-claude",
        _normalize_key("symbol-selection"): "runtime-claude",
        _normalize_key("symbol"): "runtime-claude",
    }
    return legacy_map.get(category)


def claude_lane_priority() -> tuple[str, ...]:
    return ("runtime-claude", "model-claude", "proof-claude")


def all_lane_configs() -> list[LaneConfig]:
    return list(LANE_REGISTRY)


def all_claude_lanes() -> tuple[LaneConfig, ...]:
    return tuple(cfg for cfg in LANE_REGISTRY if cfg.worker_kind == "claude")


def all_codex_lanes() -> tuple[LaneConfig, ...]:
    return tuple(cfg for cfg in LANE_REGISTRY if cfg.worker_kind == "codex")


def lane_review_dependency(lane_group: str) -> str | None:
    cfg = get_lane(lane_group)
    return cfg.review_of if cfg else None


def codex_review_lane_for_claude(lane_group: str) -> str | None:
    if lane_group == "runtime-claude":
        return "runtime-codex"
    if lane_group == "model-claude":
        return "model-codex"
    if lane_group == "proof-claude":
        return "proof-codex"
    return None


def normalize_task_status(value: str) -> str:
    return _normalize_key(value)


def as_dict() -> dict[str, Any]:
    return {
        "lane_registry": [
            {
                "lane_group": item.lane_group,
                "worker_kind": item.worker_kind,
                "mission_categories": list(item.mission_categories),
                "max_parallel": item.max_parallel,
                "review_of": item.review_of,
            }
            for item in LANE_REGISTRY
        ],
        "lane_priority": claude_lane_priority(),
    }


def _normalize_key(value: str) -> str:
    return value.replace("-", "_").replace(" ", "_").replace("/", "_").lower().strip()
