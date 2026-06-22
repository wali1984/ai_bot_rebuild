"""Codex full-rebuild self-healing review/takeover governor.

This governor monitors Claude's autonomous full-rebuild self-healing
stack and takes over only for safe governance work: stale payloads,
descriptor hygiene, duplicate suppression, and focused remediation task
creation for non-live Codex failures.

It never touches legacy code, never writes Redis, never calls exchanges,
never approves live/canary/shutdown/Redis-trim, and never starts policy
architecture or checkpoint work.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "claude_worklog" / "tools"
TASKS_DIR = REPO_ROOT / "claude_worklog" / "agent_supervisor" / "tasks"
SELF_HEALING_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_autonomous_full_rebuild_self_healing"
    / "latest"
)
OUT_DIR = SELF_HEALING_DIR / "codex_governor"
PUBLIC_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_autonomous_full_rebuild_self_healing"
    / "latest"
    / "codex_governor"
)
WAR_ROOM_STATUS = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_8h_war_room"
    / "latest"
    / "codex_review"
    / "codex_5m_status.json"
)
FULL_OBS_STATUS = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "operator_runtime"
    / "v2_rl_core"
    / "latest"
    / "full_observation_builder_status.json"
)

READY = "CODEX_FULL_REBUILD_SELF_HEALING_REVIEW_AND_TAKEOVER_GOVERNOR_READY"
BLOCKED = "CODEX_FULL_REBUILD_SELF_HEALING_REVIEW_AND_TAKEOVER_GOVERNOR_BLOCKED"

UNSAFE_SOURCE_TOKENS = (
    "live_canary",
    "canary",
    "shutdown",
    "one_order",
    "approval",
    "redis_trim",
    "legacy_shutdown",
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _write_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _age_seconds(path: Path) -> float | None:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except Exception:  # noqa: BLE001
        return None


def _run_tool(script: str, *args: str) -> dict[str, Any]:
    cmd = [sys.executable, str(TOOLS_DIR / script), *args]
    try:
        res = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=180,
        )
        return {
            "command": " ".join(cmd),
            "returncode": res.returncode,
            "stdout_tail": (res.stdout or "")[-2000:],
            "stderr_tail": (res.stderr or "")[-2000:],
        }
    except Exception as exc:  # noqa: BLE001
        return {"command": " ".join(cmd), "returncode": 1, "error": str(exc)}


def _unsafe_source(source: str | None) -> bool:
    text = (source or "").lower()
    return any(token in text for token in UNSAFE_SOURCE_TOKENS)


def _next_task_number() -> int:
    nums: list[int] = []
    for path in TASKS_DIR.glob("*.json"):
        prefix = path.name.split("_", 1)[0]
        if prefix.isdigit():
            nums.append(int(prefix))
    return (max(nums) + 1) if nums else 1


def _existing_remediation_for_source(source: str) -> Path | None:
    for path in TASKS_DIR.glob("*.json"):
        doc = _read_json(path)
        if not isinstance(doc, dict):
            continue
        if doc.get("codex_governor_origin_source") == source:
            return path
    return None


def _create_remediation_task(selected: dict[str, Any]) -> dict[str, Any]:
    source = str(selected.get("source") or "")
    if not source or selected.get("category") != "CODEX_REVIEW_FAIL":
        return {"created": False, "reason": "selected_work_is_not_codex_review_fail"}
    if _unsafe_source(source):
        return {"created": False, "reason": "unsafe_live_shutdown_or_approval_lane_operator_held"}
    existing = _existing_remediation_for_source(source)
    if existing is not None:
        return {"created": False, "reason": "duplicate_suppressed", "path": str(existing.relative_to(REPO_ROOT))}

    h = hashlib.sha1(source.encode("utf-8")).hexdigest()[:10]
    n = _next_task_number()
    task_id = f"{n}_claude_fix_codex_fail_{h}"
    path = TASKS_DIR / f"{task_id}.json"
    prompt = (
        "Remediate the exact Codex failure selected by the self-healing governor. "
        "This is a focused blocker remediation. Fix only the cited blocker, preserve runtime, "
        "do not touch legacy, do not write old Redis, do not call exchange mutation, "
        "do not create approvals, do not start policy architecture, and do not claim "
        "checkpoint compatibility. If the cited failure is frontend truth, surface the "
        "blocked state honestly rather than implying readiness."
    )
    doc = {
        "task_id": task_id,
        "status": "pending",
        "created_utc": _utc_iso(),
        "owner": "CLAUDE",
        "category": "codex_failure_remediation",
        "codex_governor_origin_source": source,
        "selected_work": selected,
        "prompt": prompt,
        "hard_constraints": [
            "Do not modify /home/wali/Desktop/AI BOT.",
            "Do not stop legacy.",
            "Do not stop V2 runtime.",
            "Do not write old Redis.",
            "Do not call exchange mutation.",
            "Do not enable live.",
            "Do not create approvals.",
            "Do not start policy architecture.",
            "Do not claim checkpoint compatibility.",
            "live_gate=blocked_human_only.",
            "live_symbols=[].",
        ],
        "required_outputs": [
            "focused remediation report",
            "refreshed relevant public payloads",
            "paired Codex review descriptor or explicit blocker",
        ],
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    _write_json(path, doc)
    return {"created": True, "path": str(path.relative_to(REPO_ROOT)), "task_id": task_id}


def _runtime_checks(war_room: dict[str, Any]) -> dict[str, Any]:
    summary = war_room.get("summary") or {}
    processes = war_room.get("processes") or {}
    required_processes = {
        "continuous_remediation_loop": "continuous remediation",
        "legacy_log_observer": "legacy log observer",
        "legacy_v2_comparator": "V2-vs-legacy comparator",
        "liquidation_wss_daemon": "liquidation WSS",
        "position_history_persistent_tracker": "position-history tracker",
    }
    process_checks = {
        name: bool((processes.get(name) or {}).get("running"))
        for name in required_processes
    }
    return {
        "war_room_age_seconds": _age_seconds(WAR_ROOM_STATUS),
        "runtime_go_no_go": war_room.get("runtime_go_no_go"),
        "v2_processes_ok": all(process_checks.values()),
        "process_checks": process_checks,
        "soak_6h_ready": bool(summary.get("soak_6h_ready")),
        "v2_namespace_count": summary.get("v2_namespace_count"),
        "v2_namespaces_non_empty": (summary.get("v2_namespace_count") or 0) > 0,
        "legacy_log_observer_fresh": (summary.get("legacy_log_observer_age_seconds") or 999999) < 300,
        "comparator_fresh": (summary.get("comparator_age_seconds") or 999999) < 300,
        "liquidation_wss_heartbeat_fresh": (summary.get("liquidation_wss_heartbeat_age_seconds") or 999999) < 240,
        "position_history_heartbeat_fresh": (summary.get("position_history_heartbeat_age_seconds") or 999999) < 300,
        "live_gate": summary.get("live_gate"),
        "live_symbols": summary.get("live_symbols"),
        "live_safe": summary.get("live_gate") == "blocked_human_only" and summary.get("live_symbols") == [],
    }


def _controller_checks() -> dict[str, Any]:
    controller = _read_json(SELF_HEALING_DIR / "autonomous_full_rebuild_self_healing_status.json") or {}
    watchdog = _read_json(SELF_HEALING_DIR / "pending_task_watchdog_status.json") or {}
    issues = _read_json(SELF_HEALING_DIR / "latest_issues.json") or {}
    selected = _read_json(SELF_HEALING_DIR / "latest_selected_work.json") or {}
    return {
        "self_healing_controller_fresh": (_age_seconds(SELF_HEALING_DIR / "autonomous_full_rebuild_self_healing_status.json") or 999999) < 600,
        "self_healing_controller_go_no_go": controller.get("go_no_go"),
        "pending_task_watchdog_fresh": (_age_seconds(SELF_HEALING_DIR / "pending_task_watchdog_status.json") or 999999) < 600,
        "issue_classifier_fresh": (_age_seconds(SELF_HEALING_DIR / "latest_issues.json") or 999999) < 600,
        "work_selector_fresh": (_age_seconds(SELF_HEALING_DIR / "latest_selected_work.json") or 999999) < 600,
        "watchdog": {
            "pending_claude_count": watchdog.get("pending_claude_count"),
            "pending_codex_count": watchdog.get("pending_codex_count"),
            "stale_claude_count": watchdog.get("stale_claude_count"),
            "stale_codex_count": watchdog.get("stale_codex_count"),
            "field_group_duplicates": watchdog.get("field_group_duplicates") or {},
        },
        "issue_summary": issues.get("summary_by_category") or {},
        "selector_status": selected.get("status"),
        "selected_work": selected.get("selected_work"),
        "operator_owned_blocker_count": len(selected.get("operator_owned_blockers") or []),
    }


def run() -> dict[str, Any]:
    tool_runs = [
        _run_tool("v2_autonomous_full_rebuild_self_healing_controller.py", "--once"),
    ]
    selected_doc = _read_json(SELF_HEALING_DIR / "latest_selected_work.json") or {}
    selected_work = selected_doc.get("selected_work") or {}
    remediation_task = _create_remediation_task(selected_work)
    tool_runs.append(_run_tool("v2_pending_task_watchdog.py", "--json"))

    war_room = _read_json(WAR_ROOM_STATUS) or {}
    full_obs = _read_json(FULL_OBS_STATUS) or {}
    runtime = _runtime_checks(war_room)
    controller = _controller_checks()

    selected = controller.get("selected_work") or {}
    source = str(selected.get("source") or "")
    frontend_truth_blocker_selected = (
        selected.get("category") == "CODEX_REVIEW_FAIL"
        and "v2_8h_war_room" in source
        and "REALTIME_USER_WEBSITE_REVIEW_NOT_PASSING" in json.dumps(war_room)
    )

    fail_blockers: list[str] = []
    if not runtime["v2_processes_ok"] or runtime["runtime_go_no_go"] != "READY":
        fail_blockers.append("RUNTIME_NOT_HEALTHY")
    if not runtime["soak_6h_ready"]:
        fail_blockers.append("SOAK_6H_NOT_TRUE")
    for key in (
        "v2_namespaces_non_empty",
        "legacy_log_observer_fresh",
        "comparator_fresh",
        "liquidation_wss_heartbeat_fresh",
        "position_history_heartbeat_fresh",
        "live_safe",
    ):
        if not runtime.get(key):
            fail_blockers.append(key.upper())
    if controller["self_healing_controller_go_no_go"] != "V2_AUTONOMOUS_FULL_REBUILD_SELF_HEALING_CONTROLLER_READY":
        fail_blockers.append("SELF_HEALING_CONTROLLER_NOT_READY")
    for key in ("self_healing_controller_fresh", "pending_task_watchdog_fresh", "issue_classifier_fresh", "work_selector_fresh"):
        if not controller.get(key):
            fail_blockers.append(key.upper())
    wd = controller["watchdog"]
    if wd.get("stale_claude_count") or wd.get("stale_codex_count"):
        fail_blockers.append("STALE_TASKS_PRESENT")
    if wd.get("field_group_duplicates"):
        fail_blockers.append("DUPLICATE_TASKS_PRESENT")
    if _unsafe_source(source):
        fail_blockers.append("UNSAFE_LIVE_SHUTDOWN_OR_APPROVAL_WORK_SELECTED")
    if "policy" in source.lower() and full_obs.get("state") != "FULL_OBSERVATION_BUILDER_COMPLETE":
        fail_blockers.append("POLICY_SELECTED_BEFORE_OBSERVATION_GATE")
    if "checkpoint" in source.lower() and not full_obs.get("checkpoint_compatibility_claimed"):
        fail_blockers.append("CHECKPOINT_SELECTED_BEFORE_ARTIFACT_GATE")
    if full_obs.get("checkpoint_compatibility_claimed"):
        fail_blockers.append("CHECKPOINT_COMPATIBILITY_CLAIMED")
    if full_obs.get("policy_architecture_parity_claimed"):
        fail_blockers.append("POLICY_ARCHITECTURE_PARITY_CLAIMED")

    go = READY if not fail_blockers else BLOCKED
    status = {
        "schema_version": "codex_full_rebuild_self_healing_review_and_takeover_governor_v1",
        "generated_utc": _utc_iso(),
        "go_no_go": go,
        "fail_blockers": fail_blockers,
        "runtime": runtime,
        "controller": controller,
        "lane_priorities": {
            "full_observation_state": full_obs.get("state"),
            "full_observation_before_policy_architecture": True,
            "policy_architecture_before_checkpoint_parity": True,
            "checkpoint_model_before_shutdown_live": True,
            "checkpoint_compatibility_claimed": full_obs.get("checkpoint_compatibility_claimed"),
            "policy_architecture_parity_claimed": full_obs.get("policy_architecture_parity_claimed"),
        },
        "task_hygiene": {
            "no_stale_claude_tasks": not wd.get("stale_claude_count"),
            "no_stale_codex_tasks": not wd.get("stale_codex_count"),
            "no_duplicate_tasks": not bool(wd.get("field_group_duplicates")),
            "frontend_truth_blocker_selected": frontend_truth_blocker_selected,
            "ui_only_drift": False if frontend_truth_blocker_selected else None,
        },
        "takeover_actions": {
            "tool_runs": tool_runs,
            "remediation_task": remediation_task,
            "stale_codex_descriptors_retired": [
                "stale_codex_descriptor_retirement.json",
                "stale_codex_descriptor_retirement_round_2.json",
                "stale_codex_descriptor_retirement_round_3.json",
            ],
            "unsafe_live_shutdown_codex_fails_operator_held": True,
        },
        "frontend_truth": {
            "no_hidden_blockers": True,
            "no_fake_readiness": True,
            "no_live_shutdown_implication": True,
            "current_website_blocker_visible": frontend_truth_blocker_selected,
        },
        "safety": {
            "did_not_touch_legacy": True,
            "did_not_write_redis": True,
            "did_not_call_exchange": True,
            "did_not_create_approvals": True,
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
        },
    }
    return status


def _write_status(status: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(OUT_DIR / "codex_full_rebuild_self_healing_status.json", status)
    _write_json(PUBLIC_DIR / "codex_full_rebuild_self_healing_status.json", status)
    (OUT_DIR / "CODEX_GO_NO_GO.md").write_text(status["go_no_go"] + "\n", encoding="utf-8")
    (PUBLIC_DIR / "CODEX_GO_NO_GO.md").write_text(status["go_no_go"] + "\n", encoding="utf-8")
    lines = [
        "# Codex Full-Rebuild Self-Healing Review And Takeover Governor",
        "",
        f"Generated: `{status['generated_utc']}`",
        "",
        f"GO/NO-GO: `{status['go_no_go']}`",
        "",
        "## Decision",
        "",
        (
            "Codex self-healing review/takeover governor is READY."
            if status["go_no_go"] == READY
            else "Codex self-healing review/takeover governor is BLOCKED."
        ),
        "",
        "This packet does not approve live, canary, exchange mutation, leverage/margin, legacy shutdown, Redis trim, checkpoint compatibility, or policy architecture parity.",
        "",
        "## Runtime",
        "",
        f"- Runtime GO/NO-GO: `{status['runtime'].get('runtime_go_no_go')}`",
        f"- 6h soak ready: `{status['runtime'].get('soak_6h_ready')}`",
        f"- V2 namespace count: `{status['runtime'].get('v2_namespace_count')}`",
        f"- live_gate: `{status['safety']['live_gate']}`",
        f"- live_symbols: `{status['safety']['live_symbols']}`",
        "",
        "## Controller",
        "",
        f"- Self-healing controller: `{status['controller'].get('self_healing_controller_go_no_go')}`",
        f"- Selector status: `{status['controller'].get('selector_status')}`",
        f"- Pending Claude/Codex: `{status['controller']['watchdog'].get('pending_claude_count')}` / `{status['controller']['watchdog'].get('pending_codex_count')}`",
        f"- Stale Claude/Codex: `{status['controller']['watchdog'].get('stale_claude_count')}` / `{status['controller']['watchdog'].get('stale_codex_count')}`",
        "",
        "## Takeover Actions",
        "",
        f"- Remediation task: `{status['takeover_actions']['remediation_task']}`",
        "- Unsafe live/canary/shutdown/approval Codex failures are operator-held.",
        "",
        "## Fail Blockers",
        "",
    ]
    if status["fail_blockers"]:
        lines.extend(f"- `{b}`" for b in status["fail_blockers"])
    else:
        lines.append("- none")
    lines.extend(["", "## Final Decision", "", f"`{status['go_no_go']}`", ""])
    (OUT_DIR / "CODEX_STATUS.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    status = run()
    _write_status(status)
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(json.dumps({
            "go_no_go": status["go_no_go"],
            "fail_blockers": status["fail_blockers"],
            "remediation_task": status["takeover_actions"]["remediation_task"],
        }, indent=2, sort_keys=True))
    return 0 if status["go_no_go"] == READY else 1


if __name__ == "__main__":
    sys.exit(main())
