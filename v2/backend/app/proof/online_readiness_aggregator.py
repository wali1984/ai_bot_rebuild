"""Aggregate V2 online-readiness marker files into a single durable evidence packet.

This module is the V2-owned source of truth for "online readiness" - the
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
- safe to run while live trading remains BLOCKED - the aggregate marker
  never promotes V2 to live; ``LIVE_GATE_STATUS`` is always
  ``blocked_human_only``

Required lanes (must all match for online-readiness READY):

- ``final_non_live_rebuild`` - top-level non-live rebuild gate
- ``automation_liveness`` - automation liveness + legacy trader down tolerance
- ``trainer_lineage_and_readiness`` - trainer lineage + readiness evidence
- ``readonly_market_exchange_data_plane`` - Phase 2Z read-only data plane
- ``decision_explainability_lineage`` - 069D2 decision lineage validation

If any required lane file is missing, unreadable, or contains a marker that
does not byte-match its ``required_marker``, the aggregate marker resolves
to ``CLAUDE_PRIMARY_ONLINE_READINESS_BUILD_WITH_CODEX_PARALLEL_AUDIT_AND_UI_POLISH_BLOCKED``
and the rollup records the specific lane(s) responsible.

Freshness / audit-history extension (additive, never gating):

Each lane entry additionally carries ``marker_mtime_iso``, ``marker_size_bytes``,
``marker_sha256``, ``marker_age_seconds`` (relative to ``now`` when provided),
and ``stale``. The top level adds ``evidence_freshness_window_seconds``,
``most_recent_lane_mtime_iso``, ``oldest_lane_mtime_iso``, ``stale_lanes``, and
``evidence_evaluated_at``. These fields are informational for the GUI banner
and operator audit trails - they never demote the aggregate go/no-go marker
from READY to BLOCKED. Text-match against ``required_marker`` remains the sole
gating predicate so the freshness signal cannot cause an unintended live-gate
state transition.
"""

from __future__ import annotations

import hashlib
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
ROLLUP_VERSION = "v2"

DEFAULT_EVIDENCE_FRESHNESS_WINDOW_SECONDS = 30 * 24 * 60 * 60

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


def _parse_now(now: str | datetime | None) -> datetime | None:
    """Normalize an optional ``now`` argument to a UTC-aware ``datetime``.

    ``None`` is returned unchanged (callers treat it as "freshness disabled").
    Naive datetimes are interpreted as UTC. ISO 8601 strings without a tz
    suffix are also treated as UTC. Unparseable strings yield ``None`` rather
    than raising, so the aggregator stays robust against unusual inputs.
    """

    if now is None:
        return None
    if isinstance(now, datetime):
        return now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(now)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


_EMPTY_FRESHNESS: dict[str, Any] = {
    "marker_mtime_iso": None,
    "marker_size_bytes": None,
    "marker_sha256": None,
    "marker_age_seconds": None,
    "stale": False,
}


def _read_marker(
    repo_root: Path,
    lane: ReadinessLaneSpec,
    *,
    now: datetime | None,
    window_seconds: int,
) -> dict[str, Any]:
    """Read a single lane marker and compute its freshness metadata.

    Only the byte-level text comparison against ``required_marker`` decides
    ``matched``; freshness fields are informational and never affect
    ``matched`` or downstream gating.
    """

    marker_path = repo_root / lane.relative_marker_path
    base = {
        "lane_id": lane.lane_id,
        "description": lane.description,
        "marker_path": lane.relative_marker_path,
        "required_marker": lane.required_marker,
        "is_required_for_online": lane.is_required_for_online,
    }
    if not marker_path.exists():
        return {
            **base,
            "found": False,
            "actual_marker": None,
            "matched": False,
            "error": "missing",
            **_EMPTY_FRESHNESS,
        }
    try:
        raw_bytes = marker_path.read_bytes()
        stat_result = marker_path.stat()
    except OSError as exc:
        return {
            **base,
            "found": True,
            "actual_marker": "",
            "matched": False,
            "error": f"unreadable: {exc.strerror or 'os_error'}",
            **_EMPTY_FRESHNESS,
        }
    try:
        text = raw_bytes.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        return {
            **base,
            "found": True,
            "actual_marker": "",
            "matched": False,
            "error": f"unreadable: {exc.reason}",
            **_EMPTY_FRESHNESS,
        }
    mtime_dt = datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc)
    sha256_hex = hashlib.sha256(raw_bytes).hexdigest()
    if now is None:
        age_seconds: int | None = None
        stale = False
    else:
        delta = (now - mtime_dt).total_seconds()
        age_seconds = int(delta) if delta >= 0 else 0
        stale = age_seconds > window_seconds
    return {
        **base,
        "found": True,
        "actual_marker": text,
        "matched": text == lane.required_marker,
        "error": None,
        "marker_mtime_iso": mtime_dt.isoformat(),
        "marker_size_bytes": int(stat_result.st_size),
        "marker_sha256": sha256_hex,
        "marker_age_seconds": age_seconds,
        "stale": bool(stale),
    }


def build_online_readiness_rollup(
    repo_root: Path,
    *,
    generated_at: str | None = None,
    now: str | datetime | None = None,
    freshness_window_seconds: int = DEFAULT_EVIDENCE_FRESHNESS_WINDOW_SECONDS,
) -> dict[str, Any]:
    """Build the aggregate rollup dict by reading each lane's marker file.

    No file is opened in any write/append/truncate mode. The function is a
    pure aggregator over the marker filesystem; identical inputs and
    ``generated_at`` produce identical outputs.

    ``now`` and ``freshness_window_seconds`` enable the additive
    freshness/audit-history layer documented at the top of this module. When
    ``now`` is omitted, ``stale_lanes`` is empty and every lane has
    ``marker_age_seconds=None`` - freshness checks are simply disabled.
    """

    repo_root = Path(repo_root)
    now_dt = _parse_now(now)
    window_seconds = int(freshness_window_seconds)
    lanes_status = [
        _read_marker(repo_root, lane, now=now_dt, window_seconds=window_seconds)
        for lane in LANES
    ]
    all_required_matched = all(
        lane["matched"] for lane in lanes_status if lane["is_required_for_online"]
    )
    blocking_lanes = [
        lane["lane_id"]
        for lane in lanes_status
        if lane["is_required_for_online"] and not lane["matched"]
    ]
    mtime_values = [
        lane["marker_mtime_iso"]
        for lane in lanes_status
        if lane.get("marker_mtime_iso")
    ]
    most_recent_lane_mtime_iso = max(mtime_values) if mtime_values else None
    oldest_lane_mtime_iso = min(mtime_values) if mtime_values else None
    stale_lanes = [
        lane["lane_id"]
        for lane in lanes_status
        if lane["is_required_for_online"] and lane.get("stale")
    ]
    return {
        "rollup_version": ROLLUP_VERSION,
        "generated_at": generated_at or datetime.now(tz=timezone.utc).isoformat(),
        "evidence_evaluated_at": now_dt.isoformat() if now_dt is not None else None,
        "evidence_freshness_window_seconds": window_seconds,
        "live_gate_status": LIVE_GATE_STATUS,
        "forbidden_operations": list(FORBIDDEN_OPERATIONS),
        "lanes": lanes_status,
        "all_required_matched": all_required_matched,
        "blocking_lanes": blocking_lanes,
        "most_recent_lane_mtime_iso": most_recent_lane_mtime_iso,
        "oldest_lane_mtime_iso": oldest_lane_mtime_iso,
        "stale_lanes": stale_lanes,
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
    most_recent = rollup.get("most_recent_lane_mtime_iso")
    if most_recent:
        lines.append(f"- most_recent_lane_mtime_iso: `{most_recent}`")
    oldest = rollup.get("oldest_lane_mtime_iso")
    if oldest:
        lines.append(f"- oldest_lane_mtime_iso: `{oldest}`")
    window = rollup.get("evidence_freshness_window_seconds")
    if window is not None:
        lines.append(f"- evidence_freshness_window_seconds: `{window}`")
    evaluated = rollup.get("evidence_evaluated_at")
    if evaluated:
        lines.append(f"- evidence_evaluated_at: `{evaluated}`")
    stale = rollup.get("stale_lanes") or []
    if stale:
        lines.append(f"- stale_lanes: `{', '.join(stale)}`")
    lines.extend(["", "## Required Lanes", ""])
    for lane in rollup["lanes"]:
        status = "READY" if lane["matched"] else "BLOCKED"
        sha = lane.get("marker_sha256")
        mtime = lane.get("marker_mtime_iso") or "-"
        suffix = ""
        if sha:
            suffix = f" (sha256=`{sha[:16]}...`, mtime=`{mtime}`)"
        lines.append(f"- `{lane['lane_id']}` ({status}): `{lane['marker_path']}`{suffix}")
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
            "## Freshness (informational only)",
            "",
            "Each lane row carries `marker_mtime_iso`, `marker_size_bytes`,",
            "`marker_sha256`, `marker_age_seconds`, and `stale`. These fields",
            "let the GUI banner show 'last evidence refresh' and flag stale",
            "lanes without re-reading every marker from the browser. Staleness",
            "is never used to flip the aggregate go/no-go marker - text-match",
            "against `required_marker` remains the sole gating predicate so",
            "the freshness signal cannot cause an unintended live-gate state",
            "transition.",
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
    now: str | datetime | None = None,
    freshness_window_seconds: int = DEFAULT_EVIDENCE_FRESHNESS_WINDOW_SECONDS,
) -> dict[str, Any]:
    """Compute the rollup and write the three required artifacts.

    Returns the rollup dict so callers can branch on
    ``rollup["all_required_matched"]``.
    """

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rollup = build_online_readiness_rollup(
        repo_root,
        generated_at=generated_at,
        now=now,
        freshness_window_seconds=freshness_window_seconds,
    )
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
    "DEFAULT_EVIDENCE_FRESHNESS_WINDOW_SECONDS",
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
