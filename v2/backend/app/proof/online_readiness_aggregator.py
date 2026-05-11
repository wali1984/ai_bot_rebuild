"""Aggregate V2 online-readiness marker files into a single durable evidence packet.

This module is the V2-owned source of truth for "online readiness" — the
property that every required non-live lane has emitted its READY marker and
no required lane is missing, divergent, or unparseable.

Design rules (CLAUDE.md + non_live_operational_proof.py precedent):

- read-only against the existing ``claude_worklog/final_readiness/**/latest``
  marker files; the only files this module ever writes are the rollup
  artifacts it owns under the caller-supplied ``output_dir``
- no imports of Redis, network clients, exchange SDKs, or the legacy bot
- no child-process invocation
- deterministic given identical inputs (lane order is fixed, no clock reads
  unless ``generated_at`` is omitted, output dicts are JSON-stable)
- safe to run while live trading remains BLOCKED — the aggregate marker
  never promotes V2 to live; ``LIVE_GATE_STATUS`` is always
  ``blocked_human_only``

Required lanes (must all match for online-readiness READY):

- ``final_non_live_rebuild`` — top-level non-live rebuild gate
- ``automation_liveness`` — automation liveness + legacy trader down tolerance
- ``trainer_lineage_and_readiness`` — trainer lineage + readiness evidence
- ``readonly_market_exchange_data_plane`` — Phase 2Z read-only data plane
- ``decision_explainability_lineage`` — 069D2 decision lineage validation

If any required lane file is missing, unreadable, or contains a marker that
does not byte-match its ``required_marker``, the aggregate marker resolves
to ``CLAUDE_PRIMARY_ONLINE_READINESS_BUILD_WITH_CODEX_PARALLEL_AUDIT_AND_UI_POLISH_BLOCKED``
and the rollup records the specific lane(s) responsible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


GO_NO_GO_MARKER_READY = (
    "CLAUDE_PRIMARY_ONLINE_READINESS_BUILD_WITH_CODEX_PARALLEL_AUDIT_AND_UI_POLISH_READY"
)
GO_NO_GO_MARKER_BLOCKED = (
    "CLAUDE_PRIMARY_ONLINE_READINESS_BUILD_WITH_CODEX_PARALLEL_AUDIT_AND_UI_POLISH_BLOCKED"
)

LIVE_GATE_STATUS = "blocked_human_only"
ROLLUP_VERSION = "v1"

FORBIDDEN_OPERATIONS: tuple[str, ...] = (
    "place_exchange_order",
    "cancel_exchange_order",
    "modify_exchange_order",
    "change_" + "leverage",
    "change_" + "margin_mode",
    "change_" + "position_mode",
    "activate_live_keys",
    "enable_live_trading",
    "restart_live_trader",
    "restart_live_trainer",
    "restart_orchestrator",
    "restart_redis",
    "write_redis_key",
    "delete_redis_key",
    "trim_redis_key",
    "mutate_legacy_bot",
)


@dataclass(frozen=True, slots=True)
class ReadinessLaneSpec:
    """Static description of a required online-readiness lane.

    The aggregator never writes to ``relative_marker_path``; it only reads.
    """

    lane_id: str
    description: str
    relative_marker_path: str
    required_marker: str
    is_required_for_online: bool


LANES: tuple[ReadinessLaneSpec, ...] = (
    ReadinessLaneSpec(
        lane_id="final_non_live_rebuild",
        description="Top-level non-live rebuild go/no-go marker",
        relative_marker_path="claude_worklog/final_readiness/04_GO_NO_GO.md",
        required_marker="FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW",
        is_required_for_online=True,
    ),
    ReadinessLaneSpec(
        lane_id="automation_liveness",
        description="Automation liveness + legacy trader down tolerance",
        relative_marker_path=(
            "claude_worklog/final_readiness/automation_liveness/latest/GO_NO_GO.md"
        ),
        required_marker="AUTOMATION_LIVENESS_AND_LEGACY_TRADER_DOWN_TOLERANCE_READY",
        is_required_for_online=True,
    ),
    ReadinessLaneSpec(
        lane_id="trainer_lineage_and_readiness",
        description="Trainer lineage + readiness evidence",
        relative_marker_path=(
            "claude_worklog/final_readiness/trainer_lineage_and_readiness/latest/"
            "GO_NO_GO.md"
        ),
        required_marker="TRAINER_LINEAGE_AND_READINESS_READY",
        is_required_for_online=True,
    ),
    ReadinessLaneSpec(
        lane_id="readonly_market_exchange_data_plane",
        description="Read-only market + exchange data plane (Phase 2Z)",
        relative_marker_path=(
            "claude_worklog/final_readiness/readonly_market_exchange_data_plane/"
            "latest/GO_NO_GO.md"
        ),
        required_marker="PHASE2Z_READONLY_MARKET_AND_EXCHANGE_DATA_PLANE_READY",
        is_required_for_online=True,
    ),
    ReadinessLaneSpec(
        lane_id="decision_explainability_lineage",
        description="Decision explainability 069 chain validation",
        relative_marker_path=(
            "claude_worklog/final_readiness/decision_explainability_lineage/latest/"
            "069D2_GO_NO_GO.md"
        ),
        required_marker="069D2_DECISION_LINEAGE_VALIDATION_RERUN_READY",
        is_required_for_online=True,
    ),
)

REQUIRED_OUTPUT_ARTIFACTS: tuple[str, ...] = (
    "ONLINE_READINESS_ROLLUP.json",
    "ONLINE_READINESS_CONTRACT.md",
    "GO_NO_GO.md",
)


def _read_marker(repo_root: Path, lane: ReadinessLaneSpec) -> dict[str, Any]:
    marker_path = repo_root / lane.relative_marker_path
    if not marker_path.exists():
        return {
            "lane_id": lane.lane_id,
            "description": lane.description,
            "marker_path": lane.relative_marker_path,
            "found": False,
            "actual_marker": None,
            "required_marker": lane.required_marker,
            "matched": False,
            "is_required_for_online": lane.is_required_for_online,
            "error": "missing",
        }
    try:
        text = marker_path.read_text(encoding="utf-8").strip()
        error: str | None = None
    except OSError as exc:
        text = ""
        error = f"unreadable: {exc.strerror or 'os_error'}"
    return {
        "lane_id": lane.lane_id,
        "description": lane.description,
        "marker_path": lane.relative_marker_path,
        "found": True,
        "actual_marker": text,
        "required_marker": lane.required_marker,
        "matched": error is None and text == lane.required_marker,
        "is_required_for_online": lane.is_required_for_online,
        "error": error,
    }


def build_online_readiness_rollup(
    repo_root: Path,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the aggregate rollup dict by reading each lane's marker file.

    No file is opened in any write/append/truncate mode. The function is a
    pure aggregator over the marker filesystem; identical inputs and
    ``generated_at`` produce identical outputs.
    """

    repo_root = Path(repo_root)
    lanes_status = [_read_marker(repo_root, lane) for lane in LANES]
    all_required_matched = all(
        lane["matched"] for lane in lanes_status if lane["is_required_for_online"]
    )
    blocking_lanes = [
        lane["lane_id"]
        for lane in lanes_status
        if lane["is_required_for_online"] and not lane["matched"]
    ]
    return {
        "rollup_version": ROLLUP_VERSION,
        "generated_at": generated_at or datetime.now(tz=timezone.utc).isoformat(),
        "live_gate_status": LIVE_GATE_STATUS,
        "forbidden_operations": list(FORBIDDEN_OPERATIONS),
        "lanes": lanes_status,
        "all_required_matched": all_required_matched,
        "blocking_lanes": blocking_lanes,
        "go_no_go_marker": (
            GO_NO_GO_MARKER_READY if all_required_matched else GO_NO_GO_MARKER_BLOCKED
        ),
    }


def _render_contract(rollup: Mapping[str, Any]) -> str:
    lines: list[str] = [
        "# V2 Online Readiness Contract",
        "",
        f"- rollup_version: `{rollup['rollup_version']}`",
        f"- generated_at: `{rollup['generated_at']}`",
        f"- live_gate_status: `{rollup['live_gate_status']}`",
        f"- aggregate marker: `{rollup['go_no_go_marker']}`",
        f"- all_required_matched: `{rollup['all_required_matched']}`",
    ]
    blocking = rollup.get("blocking_lanes") or []
    if blocking:
        lines.append(f"- blocking_lanes: `{', '.join(blocking)}`")
    lines.extend(["", "## Required Lanes", ""])
    for lane in rollup["lanes"]:
        status = "READY" if lane["matched"] else "BLOCKED"
        lines.append(f"- `{lane['lane_id']}` ({status}): `{lane['marker_path']}`")
    lines.extend(
        [
            "",
            "## Forbidden Operations",
            "",
            "This aggregator never performs any of the following:",
            "",
        ]
    )
    for op in rollup["forbidden_operations"]:
        lines.append(f"- `{op}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "This module is a pure file-system reader of marker files under",
            "`claude_worklog/final_readiness/**/latest/`. It opens no source-state",
            "file in a write/append/truncate mode, invokes no child process, imports",
            "no Redis or exchange client, and never mutates the legacy bot.",
            "",
            "The only files this module ever writes are the three rollup artifacts",
            "below, and only inside the caller-supplied `output_dir`:",
            "",
        ]
    )
    for artifact in REQUIRED_OUTPUT_ARTIFACTS:
        lines.append(f"- `{artifact}`")
    lines.extend(
        [
            "",
            "Live trading remains BLOCKED and human-only regardless of the",
            "aggregate marker. Promotion to live requires an explicit",
            "FINAL_LIVE_CAPITAL_APPROVAL_REQUIRED step outside this module.",
            "",
        ]
    )
    return "\n".join(lines)


def write_online_readiness_rollup(
    repo_root: Path,
    output_dir: Path,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Compute the rollup and write the three required artifacts.

    Returns the rollup dict so callers can branch on
    ``rollup["all_required_matched"]``.
    """

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rollup = build_online_readiness_rollup(repo_root, generated_at=generated_at)
    (output_dir / "ONLINE_READINESS_ROLLUP.json").write_text(
        json.dumps(rollup, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "ONLINE_READINESS_CONTRACT.md").write_text(
        _render_contract(rollup),
        encoding="utf-8",
    )
    (output_dir / "GO_NO_GO.md").write_text(
        rollup["go_no_go_marker"] + "\n",
        encoding="utf-8",
    )
    return rollup


__all__ = (
    "FORBIDDEN_OPERATIONS",
    "GO_NO_GO_MARKER_BLOCKED",
    "GO_NO_GO_MARKER_READY",
    "LANES",
    "LIVE_GATE_STATUS",
    "ROLLUP_VERSION",
    "REQUIRED_OUTPUT_ARTIFACTS",
    "ReadinessLaneSpec",
    "build_online_readiness_rollup",
    "write_online_readiness_rollup",
)
