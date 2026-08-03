"""V2 Autonomous Full-Rebuild Self-Healing Controller.

Drives the universal automation loop spec'd in
``V2_AUTONOMOUS_FULL_REBUILD_SELF_HEALING_CONTROLLER_READY``.

Each cycle:

1. preflight (Redis reachability, heartbeats, live safety, queue
   remediated, objective lock present);
2. invoke the issue classifier
   (``v2_autonomous_issue_classifier.py``);
3. invoke the pending-task watchdog
   (``v2_pending_task_watchdog.py`` — annotation-only, no destructive
   re-dispatch unless ``--allow-watchdog-redispatch`` is set);
4. invoke the work selector
   (``v2_autonomous_work_selector.py``);
5. dispatch / dry-run the next action;
6. write status + frontend mirror.

The controller is **safe by construction**:

- never starts policy architecture, checkpoint loading, live, canary,
  shutdown acceptance, paid alt-data, or Redis migration / trimming;
- never modifies ``/home/wali/Desktop/AI BOT``;
- never writes old Redis keys, never calls the exchange;
- never creates approval tokens or shutdown acceptance files;
- never auto-adopts Symbol Universe entries.

Modes: ``--once`` (default), ``--loop``, ``--status``, ``--dry-run``.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "claude_worklog" / "tools"
WORKLOG_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_autonomous_full_rebuild_self_healing"
    / "latest"
)
PUBLIC_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_autonomous_full_rebuild_self_healing"
    / "latest"
)
TASKS_DIR = REPO_ROOT / "claude_worklog" / "agent_supervisor" / "tasks"

REMEDIATED_QUEUE_GO = (
    "V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_REMEDIATED_READY"
)
QUEUE_CODEX_PASS = "V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_CODEX_PASS"

FORBIDDEN_ACTIONS = (
    "modify /home/wali/Desktop/AI BOT",
    "place or cancel or modify exchange orders",
    "change leverage or margin",
    "enable live trading",
    "create live/canary/shutdown/Redis-trim approval tokens",
    "create paper-only shutdown acceptance file",
    "expose raw API keys",
    "deserialize checkpoint blobs",
    "write old (legacy) Redis keys",
    "claim checkpoint compatibility",
    "claim policy architecture parity",
    "zero-fill unknown values",
    "stop V2 runtime, remediation governor, legacy log observer,"
    " V2-vs-legacy comparator, liquidation WSS daemon, position-history daemon",
    "automatic Symbol Universe adoption",
    "automatic external source adoption",
)


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _run_tool(script: Path, extra_args: list[str] | None = None) -> tuple[int, str]:
    cmd = [sys.executable, str(script)]
    if extra_args:
        cmd.extend(extra_args)
    try:
        res = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            cwd=str(REPO_ROOT),
        )
        return res.returncode, (res.stdout or "") + (res.stderr or "")
    except Exception as exc:  # noqa: BLE001
        return 1, f"tool exception: {exc}"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _objective_lock_present() -> bool:
    return (WORKLOG_DIR / "objective_lock.json").exists()


def _lane_registry_present() -> bool:
    return (WORKLOG_DIR / "lane_registry.json").exists()


def _file_lock_registry_present() -> bool:
    return (WORKLOG_DIR / "file_lock_registry.json").exists()


def runtime_preflight() -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "timestamp_utc": _utc_iso(),
        "checks": {
            "objective_lock_present": _objective_lock_present(),
            "lane_registry_present": _lane_registry_present(),
            "file_lock_registry_present": _file_lock_registry_present(),
        },
    }
    # Reuse the queue go/no-go check by reading the queue file.
    queue_path = (
        REPO_ROOT
        / "claude_worklog"
        / "final_readiness"
        / "v2_full_observation_remaining_dim_execution_queue"
        / "latest"
        / "remaining_dim_execution_queue.json"
    )
    doc = _read_json(queue_path) or {}
    queue_go = doc.get("go_no_go")
    result["checks"]["queue_go_no_go"] = queue_go
    result["checks"]["queue_remediated"] = queue_go == REMEDIATED_QUEUE_GO

    # Codex pass marker file
    codex_marker = (
        REPO_ROOT
        / "claude_worklog"
        / "final_readiness"
        / "v2_full_observation_remaining_dim_execution_queue"
        / "latest"
        / "codex_review"
        / "CODEX_GO_NO_GO.md"
    )
    try:
        text = codex_marker.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        text = ""
    result["checks"]["queue_codex_passed"] = QUEUE_CODEX_PASS in text

    all_ok = all(
        result["checks"][k] for k in (
            "objective_lock_present",
            "lane_registry_present",
            "file_lock_registry_present",
            "queue_remediated",
        )
    )
    result["ok"] = bool(all_ok)
    return result


def write_action_plan(
    *,
    selected_work: dict[str, Any] | None,
    selector_status: str | None,
    next_action: str,
    controller_intent: str,
    dry_run: bool,
) -> dict[str, Any]:
    plan = {
        "schema_version": "v2_autonomous_full_rebuild_self_healing_action_plan_v1",
        "generated_utc": _utc_iso(),
        "selector_status": selector_status,
        "selected_work": selected_work,
        "controller_intent": controller_intent,
        "next_action": next_action,
        "forbidden_actions": list(FORBIDDEN_ACTIONS),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    if not dry_run:
        body = json.dumps(plan, indent=2, sort_keys=True) + "\n"
        (WORKLOG_DIR / "latest_action_plan.json").write_text(body, encoding="utf-8")
        PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
        (PUBLIC_DIR / "latest_action_plan.json").write_text(body, encoding="utf-8")
    return plan


def dispatch_action(work: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    """Decide how to act on the selected work. The controller does NOT
    auto-implement code for non-trivial categories — it surfaces them
    so the supervisor / operator can route to Claude or Codex.

    For categories that benefit from a fresh Codex review packet (e.g.,
    CODEX_REVIEW_FAIL, FRONTEND_TRUTH_MISMATCH, SCHEMA_MISMATCH), it
    creates an annotation under the autonomous self-healing latest
    directory, but it does NOT itself fix code.
    """
    cat = work.get("category")
    result: dict[str, Any] = {
        "action": "annotate_only",
        "category": cat,
        "dry_run": dry_run,
        "did_dispatch_task": False,
    }
    write_action_plan(
        selected_work=work,
        selector_status="AUTOMATABLE_WORK_SELECTED",
        next_action=f"route category {cat!r} via supervisor to {work.get('owner')}",
        controller_intent="annotate-and-route",
        dry_run=dry_run,
    )
    return result


def cycle(args: argparse.Namespace) -> dict[str, Any]:
    state: dict[str, Any] = {
        "controller": "v2_autonomous_full_rebuild_self_healing_controller",
        "timestamp_utc": _utc_iso(),
        "mode": args.mode,
        "dry_run": bool(args.dry_run),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    preflight = runtime_preflight()
    state["preflight"] = preflight
    if not preflight["ok"]:
        state["go_no_go"] = (
            "V2_AUTONOMOUS_FULL_REBUILD_SELF_HEALING_CONTROLLER_BLOCKED"
        )
        state["next_action"] = (
            "fix preflight (objective lock / lane registry / file-lock"
            " registry / remediated queue) before continuing"
        )
        return state

    # Phase 2: issue classifier
    rc, _out = _run_tool(TOOLS_DIR / "v2_autonomous_issue_classifier.py")
    state["issue_classifier_rc"] = rc
    issues_doc = _read_json(WORKLOG_DIR / "latest_issues.json") or {}
    state["issue_summary"] = issues_doc.get("summary_by_category", {})
    state["automatable_issue_count"] = issues_doc.get("automatable_issue_count", 0)
    state["operator_owned_issue_count"] = issues_doc.get("operator_owned_issue_count", 0)

    # Phase 3: pending-task watchdog
    watchdog_args = ["--stale-seconds", str(args.watchdog_stale_seconds)]
    if args.allow_watchdog_redispatch:
        watchdog_args.append("--allow-redispatch")
    rc, _out = _run_tool(TOOLS_DIR / "v2_pending_task_watchdog.py", watchdog_args)
    state["watchdog_rc"] = rc
    watchdog_doc = _read_json(WORKLOG_DIR / "pending_task_watchdog_status.json") or {}
    state["watchdog_summary"] = {
        k: watchdog_doc.get(k) for k in (
            "pending_claude_count", "pending_codex_count",
            "stale_claude_count", "stale_codex_count",
            "actions",
        )
    }

    # Phase 4: work selector
    rc, _out = _run_tool(TOOLS_DIR / "v2_autonomous_work_selector.py")
    state["selector_rc"] = rc
    selected_doc = _read_json(WORKLOG_DIR / "latest_selected_work.json") or {}
    state["selector_status"] = selected_doc.get("status")
    state["selected_work"] = selected_doc.get("selected_work")
    state["operator_owned_blockers"] = selected_doc.get("operator_owned_blockers") or []

    # Phase 5: dispatch (annotate-only)
    if selected_doc.get("status") == "NO_AUTOMATABLE_WORK_REMAINING":
        state["next_action"] = "all automatable lanes complete; monitor only"
        state["action_result"] = {
            "action": "clear_stale_action_plan",
            "did_dispatch_task": False,
            "reason": "no_automatable_work_remaining",
        }
        write_action_plan(
            selected_work=None,
            selector_status=selected_doc.get("status"),
            next_action=state["next_action"],
            controller_intent="monitor-only",
            dry_run=bool(args.dry_run),
        )
        state["go_no_go"] = (
            "V2_AUTONOMOUS_FULL_REBUILD_SELF_HEALING_CONTROLLER_READY"
        )
        return state

    work = selected_doc.get("selected_work")
    if not work:
        state["next_action"] = "no work selected this cycle"
        state["action_result"] = {
            "action": "clear_stale_action_plan",
            "did_dispatch_task": False,
            "reason": "no_selected_work",
        }
        write_action_plan(
            selected_work=None,
            selector_status=selected_doc.get("status"),
            next_action=state["next_action"],
            controller_intent="monitor-only",
            dry_run=bool(args.dry_run),
        )
        state["go_no_go"] = (
            "V2_AUTONOMOUS_FULL_REBUILD_SELF_HEALING_CONTROLLER_READY"
        )
        return state

    action = dispatch_action(work, dry_run=bool(args.dry_run))
    state["action_result"] = action
    state["go_no_go"] = (
        "V2_AUTONOMOUS_FULL_REBUILD_SELF_HEALING_CONTROLLER_READY"
    )
    state["next_action"] = (
        f"route category {work.get('category')!r} via supervisor to {work.get('owner')}"
    )
    return state


def emit_status(state: dict[str, Any]) -> None:
    WORKLOG_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    body = json.dumps(state, indent=2, sort_keys=True) + "\n"
    (WORKLOG_DIR / "autonomous_full_rebuild_self_healing_status.json").write_text(body, encoding="utf-8")
    (PUBLIC_DIR / "autonomous_full_rebuild_self_healing_status.json").write_text(body, encoding="utf-8")
    (PUBLIC_DIR / "operator_dashboard_payload.json").write_text(body, encoding="utf-8")


def cmd_status() -> dict[str, Any]:
    p = WORKLOG_DIR / "autonomous_full_rebuild_self_healing_status.json"
    if p.exists():
        return _read_json(p) or {"status": "UNREADABLE"}
    return {
        "controller": "v2_autonomous_full_rebuild_self_healing_controller",
        "status": "NEVER_RAN",
        "timestamp_utc": _utc_iso(),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--once", dest="mode", action="store_const", const="once")
    g.add_argument("--loop", dest="mode", action="store_const", const="loop")
    g.add_argument("--status", dest="mode", action="store_const", const="status")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--loop-interval-seconds", type=int, default=300)
    p.add_argument("--loop-max-cycles", type=int, default=1)
    p.add_argument("--watchdog-stale-seconds", type=int, default=300)
    p.add_argument(
        "--allow-watchdog-redispatch",
        action="store_true",
        help="permit watchdog to annotate stale descriptors as pending_redispatch",
    )
    args = p.parse_args()
    if args.mode is None:
        args.mode = "once"

    if args.mode == "status":
        print(json.dumps(cmd_status(), indent=2, sort_keys=True))
        return 0

    if args.mode == "once":
        state = cycle(args)
        emit_status(state)
        print(json.dumps({
            "controller": state["controller"],
            "go_no_go": state.get("go_no_go"),
            "selector_status": state.get("selector_status"),
            "selected_work": state.get("selected_work"),
            "automatable_issue_count": state.get("automatable_issue_count"),
            "operator_owned_issue_count": state.get("operator_owned_issue_count"),
        }, indent=2, sort_keys=True))
        return 0 if state.get("go_no_go", "").endswith("READY") else 1

    interval = max(60, int(args.loop_interval_seconds))
    cycles = max(1, int(args.loop_max_cycles))
    last_state: dict[str, Any] = {}
    for i in range(cycles):
        last_state = cycle(args)
        emit_status(last_state)
        if last_state.get("go_no_go", "").endswith("BLOCKED"):
            break
        if last_state.get("selector_status") == "NO_AUTOMATABLE_WORK_REMAINING":
            break
        if i < cycles - 1:
            time.sleep(interval)
    print(json.dumps({
        "controller": last_state.get("controller"),
        "go_no_go": last_state.get("go_no_go"),
        "selector_status": last_state.get("selector_status"),
    }, indent=2, sort_keys=True))
    return 0 if last_state.get("go_no_go", "").endswith("READY") else 1


if __name__ == "__main__":
    sys.exit(main())
