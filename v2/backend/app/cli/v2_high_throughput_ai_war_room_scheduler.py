"""V2 high-throughput AI war-room scheduler.

One-shot control-plane scheduler for the 24h recovery war-room. It only
writes local status/dispatch artifacts. It never writes Redis, calls an
exchange, starts live/canary/shutdown flows, starts GPU training, or installs
itself as a daemon.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

LIVE_GATE_BLOCKED = "blocked_human_only"
READY = "V2_HIGH_THROUGHPUT_AI_WAR_ROOM_SCHEDULER_READY"
BLOCKED = "V2_HIGH_THROUGHPUT_AI_WAR_ROOM_SCHEDULER_BLOCKED"

REQUIRED_PLAN_MARKERS = {
    "throughput_plan_codex": (
        "claude_worklog/final_readiness/v2_ai_throughput_acceleration/latest/"
        "codex_review/CODEX_GO_NO_GO.md",
        "V2_AI_THROUGHPUT_ACCELERATION_PLAN_CODEX_PASS",
    ),
    "cli_remediation_codex": (
        "claude_worklog/final_readiness/v2_ai_throughput_acceleration_cli_command_remediation/"
        "latest/codex_review/CODEX_GO_NO_GO.md",
        "V2_AI_THROUGHPUT_ACCELERATION_CLI_COMMAND_REMEDIATION_CODEX_PASS",
    ),
}

TARGET_TASK_IDS = (
    "paper_fill_gate_record_block_reason",
    "observation_gap_inventory_for_false_negatives",
    "altdata_snapshot_attached_to_replay_bundle",
)

DISPATCH_LOCKS = {
    "paper_fill_gate_record_block_reason": [
        "v2/backend/app/cli/v2_trade_management_paper_loop.py",
        "v2/backend/app/cli/v2_orchestrator_arbitration_loop.py",
        "claude_worklog/final_readiness/v2_high_throughput_ai_war_room_scheduler/dispatch/paper_fill_gate_record_block_reason/**",
    ],
    "observation_gap_inventory_for_false_negatives": [
        "v2/backend/app/services/war_room/parallel_recovery_24h.py:false_negative_observation_gap_inventory",
        "claude_worklog/final_readiness/v2_high_throughput_ai_war_room_scheduler/dispatch/observation_gap_inventory_for_false_negatives/**",
    ],
    "altdata_snapshot_attached_to_replay_bundle": [
        "v2/backend/app/services/edge_proof/replay_miner.py:altdata_snapshot_attachment",
        "claude_worklog/final_readiness/v2_high_throughput_ai_war_room_scheduler/dispatch/altdata_snapshot_attached_to_replay_bundle/**",
    ],
}

FORBIDDEN_TASK_TOKENS = (
    "live",
    "canary",
    "shutdown",
    "legacy_shutdown",
    "redis_trim",
    "gpu_training",
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    tmp.replace(path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _marker_check(repo_root: Path) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    for name, (rel_path, expected) in REQUIRED_PLAN_MARKERS.items():
        path = repo_root / rel_path
        observed = path.read_text(encoding="utf-8").strip() if path.exists() else None
        checks[name] = {
            "path": str(path),
            "expected": expected,
            "observed": observed,
            "passed": observed == expected,
        }
    return checks


def _safety_ok(doc: dict[str, Any]) -> bool:
    return (
        doc.get("live_gate") == LIVE_GATE_BLOCKED
        and doc.get("live_symbols") == []
        and doc.get("approves_live") is False
        and doc.get("approves_canary") is False
        and doc.get("approves_legacy_shutdown") is False
        and doc.get("approves_redis_trim") is False
    )


def _task_is_allowed(task: dict[str, Any]) -> bool:
    task_id = str(task.get("task_id") or "")
    joined = " ".join(
        str(task.get(k) or "") for k in ("task_id", "title", "rationale", "owner_lane")
    ).lower()
    return (
        task.get("automatable") is True
        and task_id in TARGET_TASK_IDS
        and not any(token in joined for token in FORBIDDEN_TASK_TOKENS)
    )


def _build_dispatches(tasks: list[dict[str, Any]], generated_utc: str) -> list[dict[str, Any]]:
    by_id = {str(t.get("task_id")): t for t in tasks}
    dispatches: list[dict[str, Any]] = []
    for index, task_id in enumerate(TARGET_TASK_IDS, start=1):
        task = by_id.get(task_id)
        if not task or not _task_is_allowed(task):
            continue
        dispatches.append(
            {
                "dispatch_id": f"v2_high_throughput_dispatch_{index}_{task_id}",
                "task_id": task_id,
                "title": task.get("title"),
                "owner": "claude",
                "reviewer": "codex",
                "status": "active",
                "activated_by": "V2_HIGH_THROUGHPUT_AI_WAR_ROOM_SCHEDULER",
                "activated_utc": generated_utc,
                "automatable": True,
                "resource_class": "low_cpu_no_gpu",
                "gpu_allowed": False,
                "codex_fast_mode_enabled": False,
                "live_gate": LIVE_GATE_BLOCKED,
                "live_symbols": [],
                "file_locks": DISPATCH_LOCKS[task_id],
                "scope_prompt": (
                    f"Work only on {task_id}. Do not enable live/canary/shutdown, "
                    "do not write old Redis, do not call exchange mutation, do not run GPU jobs."
                ),
            }
        )
    return dispatches


def _file_locks_unique(dispatches: list[dict[str, Any]]) -> bool:
    seen: set[str] = set()
    for dispatch in dispatches:
        for lock in dispatch.get("file_locks") or []:
            if lock in seen:
                return False
            seen.add(lock)
    return True


def _update_war_room_artifacts(
    repo_root: Path,
    dispatches: list[dict[str, Any]],
    generated_utc: str,
) -> list[str]:
    written: list[str] = []
    worklog = repo_root / "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest"
    public = repo_root / "v2/frontend/public/v2_24h_parallel_recovery_war_room/latest"

    util_path = worklog / "lane6/war_room_utilization_status.json"
    util = _read_json(util_path)
    util.update(
        {
            "generated_utc": generated_utc,
            "active_lanes": len(dispatches),
            "active_automatable_lanes": dispatches,
            "scheduler_overlay": "V2_HIGH_THROUGHPUT_AI_WAR_ROOM_SCHEDULER",
            "scheduler_overlay_remediates": "WAR_ROOM_ACTIVE_LANES_BELOW_MINIMUM",
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
        }
    )
    _write_json(util_path, util)
    written.append(str(util_path))

    dispatch_path = worklog / "lane6/war_room_task_dispatch_status.json"
    dispatch_doc = _read_json(dispatch_path)
    dispatch_doc.update(
        {
            "generated_utc": generated_utc,
            "active_dispatches": dispatches,
            "scheduler_activated_count": len(dispatches),
            "minimum_required_active_lanes_when_work_exists": 3,
            "war_room_active_lanes_below_minimum_remediated": len(dispatches) >= 3,
            "no_idle_claude_lane_with_automatable_work": len(dispatches) >= 3,
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
        }
    )
    _write_json(dispatch_path, dispatch_doc)
    written.append(str(dispatch_path))

    active_path = worklog / "active_automatable_lanes.json"
    active_doc = {
        "schema_version": "v2_high_throughput_ai_war_room_scheduler_active_lanes_v1",
        "generated_utc": generated_utc,
        "active_lanes": len(dispatches),
        "minimum_required_active_lanes_when_work_exists": 3,
        "dispatches": dispatches,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    _write_json(active_path, active_doc)
    written.append(str(active_path))

    for path_name in ("war_room_status.json",):
        path = worklog / path_name
        doc = _read_json(path)
        if doc:
            doc["generated_utc"] = generated_utc
            summary = dict(doc.get("utilization_summary") or {})
            summary["active_lanes"] = len(dispatches)
            summary["scheduler_overlay"] = "V2_HIGH_THROUGHPUT_AI_WAR_ROOM_SCHEDULER"
            doc["utilization_summary"] = summary
            doc["active_automatable_lanes"] = dispatches
            doc["live_gate"] = LIVE_GATE_BLOCKED
            doc["live_symbols"] = []
            _write_json(path, doc)
            written.append(str(path))
            _write_json(public / path_name, doc)
            written.append(str(public / path_name))

    dashboard_path = public / "operator_dashboard_payload.json"
    dashboard = _read_json(dashboard_path)
    if dashboard:
        dashboard["generated_utc"] = generated_utc
        util_summary = dict(dashboard.get("utilization_summary") or {})
        util_summary["active_lanes"] = len(dispatches)
        util_summary["scheduler_overlay"] = "V2_HIGH_THROUGHPUT_AI_WAR_ROOM_SCHEDULER"
        dashboard["utilization_summary"] = util_summary
        dashboard["active_automatable_lanes"] = dispatches
        dashboard["live_gate"] = LIVE_GATE_BLOCKED
        dashboard["live_symbols"] = []
        controls = dashboard.get("controls_present")
        dashboard["controls_present"] = False if controls is None else controls
        _write_json(dashboard_path, dashboard)
        written.append(str(dashboard_path))

    return written


def run_once(repo_root: Path) -> dict[str, Any]:
    generated_utc = _utc_now_iso()
    marker_checks = _marker_check(repo_root)
    marker_passed = all(c["passed"] for c in marker_checks.values())

    war_room_root = repo_root / "claude_worklog/final_readiness/v2_24h_parallel_recovery_war_room/latest"
    next_tasks_doc = _read_json(war_room_root / "next_automatable_tasks.json")
    util_before = _read_json(war_room_root / "lane6/war_room_utilization_status.json")
    tasks = list(next_tasks_doc.get("tasks") or [])
    dispatches = _build_dispatches(tasks, generated_utc)
    lock_ok = _file_locks_unique(dispatches)
    safety_ok = _safety_ok(next_tasks_doc) and _safety_ok(util_before)
    ready = marker_passed and safety_ok and lock_ok and len(dispatches) >= 3

    written: list[str] = []
    if ready:
        written.extend(_update_war_room_artifacts(repo_root, dispatches, generated_utc))

    latest = repo_root / "claude_worklog/final_readiness/v2_high_throughput_ai_war_room_scheduler/latest"
    public = repo_root / "v2/frontend/public/v2_high_throughput_ai_war_room_scheduler/latest"
    go_no_go = READY if ready else BLOCKED
    status = {
        "schema_version": "v2_high_throughput_ai_war_room_scheduler_status_v1",
        "generated_utc": generated_utc,
        "go_no_go": go_no_go,
        "scheduler_name": "V2_HIGH_THROUGHPUT_AI_WAR_ROOM_SCHEDULER",
        "mode": "one_shot_control_plane_dispatch",
        "daemon_installed": False,
        "systemd_timer_installed": False,
        "plan_gate_checks": marker_checks,
        "war_room_problem_targeted": "WAR_ROOM_ACTIVE_LANES_BELOW_MINIMUM",
        "active_lanes_before": util_before.get("active_lanes"),
        "active_lanes_after": len(dispatches) if ready else util_before.get("active_lanes"),
        "minimum_required_active_lanes_when_work_exists": 3,
        "dispatches": dispatches,
        "file_locks_unique": lock_ok,
        "safety_inputs_ok": safety_ok,
        "scheduler_can_select_live_canary_shutdown": False,
        "gpu_training_dispatched": False,
        "codex_fast_mode_enabled": False,
        "heavy_jobs_launched": False,
        "old_redis_writes": False,
        "exchange_mutation": False,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "paths_written": written,
    }
    _write_json(latest / "scheduler_status.json", status)
    _write_json(latest / "active_lane_dispatches.json", {"dispatches": dispatches, **status})
    _write_text(latest / "GO_NO_GO.md", go_no_go + "\n")
    _write_text(latest / "V2_HIGH_THROUGHPUT_AI_WAR_ROOM_SCHEDULER_REPORT.md", _render_report(status))

    public_payload = {
        "schema_version": "v2_high_throughput_ai_war_room_scheduler_operator_dashboard_v1",
        "generated_utc": generated_utc,
        "go_no_go": go_no_go,
        "war_room_problem_targeted": status["war_room_problem_targeted"],
        "active_lanes_before": status["active_lanes_before"],
        "active_lanes_after": status["active_lanes_after"],
        "dispatches": dispatches,
        "controls_present": False,
        "fake_readiness": False,
        "daemon_installed": False,
        "gpu_training_dispatched": False,
        "codex_fast_mode_enabled": False,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    _write_json(public / "operator_dashboard_payload.json", public_payload)
    _write_json(public / "scheduler_status.json", status)
    return status


def _render_report(status: dict[str, Any]) -> str:
    lines = [
        "# V2 High-Throughput AI War-Room Scheduler\n\n",
        f"GO/NO-GO: {status['go_no_go']}\n\n",
        "This is a one-shot control-plane scheduler dispatch. It does not install a daemon, run GPU training, enable Codex Fast mode, approve live/canary/shutdown, write old Redis, or call the exchange.\n\n",
        "## Targeted Problem\n\n",
        f"- {status['war_room_problem_targeted']}\n",
        f"- active_lanes_before: {status['active_lanes_before']}\n",
        f"- active_lanes_after: {status['active_lanes_after']}\n\n",
        "## Activated Lanes\n\n",
    ]
    for dispatch in status["dispatches"]:
        lines.append(f"- {dispatch['task_id']} ({dispatch['status']})\n")
    lines.extend(
        [
            "\n## Safety\n\n",
            f"- live_gate: {status['live_gate']}\n",
            f"- live_symbols: {status['live_symbols']}\n",
            f"- approves_live: {status['approves_live']}\n",
            f"- approves_canary: {status['approves_canary']}\n",
            f"- approves_legacy_shutdown: {status['approves_legacy_shutdown']}\n",
            f"- approves_redis_trim: {status['approves_redis_trim']}\n",
            f"- gpu_training_dispatched: {status['gpu_training_dispatched']}\n",
            f"- codex_fast_mode_enabled: {status['codex_fast_mode_enabled']}\n",
            f"- file_locks_unique: {status['file_locks_unique']}\n",
        ]
    )
    return "".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_high_throughput_ai_war_room_scheduler")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    status = run_once(Path(args.repo_root).resolve())
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True, default=str))
    else:
        print(status["go_no_go"])
    return 0 if status["go_no_go"] == READY else 1


if __name__ == "__main__":
    raise SystemExit(main())
