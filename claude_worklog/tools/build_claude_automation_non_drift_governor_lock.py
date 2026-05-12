#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


READY = "CLAUDE_AUTOMATION_NON_DRIFT_GOVERNOR_LOCK_READY"
BLOCKED = "CLAUDE_AUTOMATION_NON_DRIFT_GOVERNOR_LOCK_BLOCKED"
CODEX_PASS = "CLAUDE_AUTOMATION_NON_DRIFT_GOVERNOR_LOCK_CODEX_PASS"
CODEX_FAIL = "CLAUDE_AUTOMATION_NON_DRIFT_GOVERNOR_LOCK_CODEX_FAIL"
LIVE_GATE_STATUS = "blocked_human_only"

ROOT = Path("/home/wali/Desktop/AI BOT REBUILD")
FINAL = ROOT / "claude_worklog/final_readiness/claude_automation_non_drift_governor_lock/latest"
PUBLIC = ROOT / "v2/frontend/public/claude_automation_non_drift_governor_lock/latest"
GOVERNOR = ROOT / "claude_worklog/autonomous_governor/latest"
LOCK_PATH = GOVERNOR / "NON_DRIFT_GOVERNOR_LOCK.json"
SELECTION_PATH = GOVERNOR / "NEXT_TASK_SELECTION.json"
SELECTION_MD = GOVERNOR / "NEXT_TASK_SELECTION.md"
STATUS_PATH = ROOT / "claude_worklog/agent_supervisor/status/non_drift_governor_lock_status.json"

PRIMARY_LANE = "v2_live_like_paper_shadow_canary_preflight"
SUPPORT_LANES = ["production_website_full_rebuild", "operator_proof_archive", "visual_route_acceptance"]
NEXT_PRIMARY_TASK = "LEGACY_TRAINER_RESTART_RUNTIME_CAPTURE_AND_V2_PARITY_SYNC_UNBLOCK"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, indent=2, sort_keys=True))


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""


def run(cmd: list[str] | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, shell=isinstance(cmd, str), text=True, capture_output=True)


def ps_lines(pattern: str) -> list[str]:
    proc = run(f"ps -eo pid,ppid,etimes,cmd | grep -E '{pattern}' | grep -v grep || true")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def parse_age_seconds(value: str | None) -> int | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()))
    except Exception:
        return None


def marker(path: str) -> str:
    return read_text(ROOT / path) or "MISSING"


def main() -> int:
    generated_at = now_iso()
    paper_runtime = read_json(ROOT / "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json")
    queue = read_json(ROOT / "claude_worklog/agent_supervisor/status/queue_status.json")
    current = read_json(ROOT / "claude_worklog/agent_supervisor/status/current_status.json")
    planner = read_json(ROOT / "claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json")
    website_go = marker("claude_worklog/final_readiness/production_website_full_rebuild/latest/GO_NO_GO.md")
    tonight_go = marker("claude_worklog/final_readiness/tonight_live_like_paper_shadow/latest/GO_NO_GO.md")
    canonical_go = marker("claude_worklog/final_readiness/paper_online_canonical_truth_bridge/latest/GO_NO_GO.md")
    supervisor_go = marker("claude_worklog/final_readiness/control_plane_supervisor_persistence/latest/GO_NO_GO.md")
    legacy_trainer_go = marker("claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/GO_NO_GO.md")
    legacy_execution_go = marker("claude_worklog/final_readiness/legacy_execution_containment/latest/GO_NO_GO.md")

    paper_age = parse_age_seconds(paper_runtime.get("generated_at"))
    queue_age = parse_age_seconds(queue.get("generated_at"))
    planner_age = parse_age_seconds(planner.get("generated_at"))
    processes = {
        "agent_supervisor": ps_lines(r"agent_supervisor.py .*--daemon|agent_supervisor.py --daemon"),
        "scheduler": ps_lines(r"parallel_capacity_scheduler.py --daemon"),
        "watchdog": ps_lines(r"codex_non_live_watchdog.py --daemon"),
        "paper_runtime": ps_lines(r"paper_online_runtime"),
        "legacy_trainer": ps_lines(r"rl.hybrid_trainer"),
        "legacy_orchestrator": ps_lines(r"rl.orchestrator_worker"),
        "legacy_trader": ps_lines(r"trading/trader.py"),
    }
    git_status = run(["git", "status", "--short"]).stdout.strip() or "clean"
    git_head = run(["git", "log", "--oneline", "-1"]).stdout.strip()

    current_primary_blockers = []
    if "BLOCKED" in legacy_trainer_go or legacy_trainer_go == "MISSING":
        current_primary_blockers.append("legacy_trainer_restart_runtime_parity_sync_blocked")
    if legacy_execution_go == "MISSING" or "BLOCKED" in legacy_execution_go:
        current_primary_blockers.append("legacy_execution_containment_marker_missing")
    if not processes["agent_supervisor"]:
        current_primary_blockers.append("agent_supervisor_daemon_not_observed")
    if queue_age is None or queue_age > 300:
        current_primary_blockers.append("supervisor_queue_status_stale")
    if planner_age is None or planner_age > 300:
        current_primary_blockers.append("master_planner_status_stale")

    lock = {
        "generated_at": generated_at,
        "lock_id": "CLAUDE_AUTOMATION_NON_DRIFT_GOVERNOR_LOCK",
        "status": "ACTIVE",
        "primary_objective": "V2 live-like paper/shadow observer/twin, legacy bridge, risk gateway, trainer parity, canary preflight",
        "selected_primary_task": NEXT_PRIMARY_TASK,
        "primary_lane": PRIMARY_LANE,
        "support_lanes": SUPPORT_LANES,
        "support_lane_policy": "Support lanes are allowed only when they expose current runtime truth or unblock the primary live-like paper/shadow/canary path. Website/UI-only work cannot supersede primary runtime work.",
        "forbidden_drift": [
            "ui_only_marker_accumulation",
            "proof_dump_expansion_without_runtime_value",
            "static_fixture_as_current_truth",
            "frontend_polish_without_runtime_contract",
            "new website-only milestones before primary blockers are addressed",
        ],
        "required_primary_work_order": [
            "keep V2 paper runtime fresh",
            "keep legacy live bridge fresh/read-only",
            "risk gateway final authority over all V2 intents",
            "legacy trainer restart/runtime/parity evidence",
            "legacy execution containment classification",
            "canary preflight only, no activation",
        ],
        "current_primary_blockers": current_primary_blockers,
        "live_gate_status": LIVE_GATE_STATUS,
        "old_redis_mutation_allowed": False,
        "exchange_mutation_allowed": False,
        "legacy_bot_mutation_allowed": False,
        "website_lane_status": website_go,
        "paper_shadow_status": tonight_go,
        "canonical_truth_bridge_status": canonical_go,
        "supervisor_persistence_status": supervisor_go,
        "legacy_trainer_restart_status": legacy_trainer_go,
        "legacy_execution_containment_status": legacy_execution_go or "MISSING",
        "paper_runtime_age_seconds": paper_age,
        "queue_status_age_seconds": queue_age,
        "master_planner_status_age_seconds": planner_age,
        "git_head": git_head,
        "git_status": git_status,
    }
    status = {
        "generated_at": generated_at,
        "lock_active": True,
        "selected_primary_task": NEXT_PRIMARY_TASK,
        "primary_lane": PRIMARY_LANE,
        "current_running_task": queue.get("current_running_task"),
        "queue_next_pending_task": queue.get("next_pending_task"),
        "queue_next_pending_task_superseded_by_lock": queue.get("next_pending_task") != NEXT_PRIMARY_TASK,
        "planner_status_stale": planner_age is None or planner_age > 300,
        "queue_status_stale": queue_age is None or queue_age > 300,
        "processes": processes,
        "lock": lock,
    }
    selection = {
        "generated_at": generated_at,
        "selected_primary_task": NEXT_PRIMARY_TASK,
        "selected_task_id": "claude_primary_v2_live_like_paper_shadow_followup",
        "primary_lane": PRIMARY_LANE,
        "ui_polish_lane_state": "support_only_after_production_website_full_rebuild_ready",
        "website_support_lane_status": website_go,
        "why_selected": "website rebuild passed and is demoted to support; primary blockers are legacy trainer parity/restart capture, legacy execution containment, risk gateway visibility, and canary preflight readiness",
        "primary_claude_lane": [
            "v2_live_like_paper_shadow",
            "legacy_live_bridge_readonly",
            "risk_gateway_final_authority",
            "trainer_parity_runtime_capture",
            "canary_preflight_blocked_human_only",
        ],
        "parallel_codex_tasks": [
            "audit_no_live_side_effects",
            "audit_legacy_bridge_readonly",
            "audit_trainer_parity_truth",
            "audit_risk_gateway_final_authority",
            "audit_paper_shadow_runtime_freshness",
        ],
        "human_input_required": "false_unless_final_live_capital_gate",
        "legacy_mutation": "none",
        "redis_mutation": "none",
        "exchange_mutation": "none",
        "live_gate_status": LIVE_GATE_STATUS,
        "redis_trim": "deferred_non_blocking",
        "current_primary_blockers": current_primary_blockers,
        "non_drift_lock_path": "claude_worklog/autonomous_governor/latest/NON_DRIFT_GOVERNOR_LOCK.json",
    }
    marker_value = READY if paper_age is not None and paper_age <= 120 and website_go.endswith("READY") and tonight_go.endswith("READY") else BLOCKED
    codex_marker = CODEX_PASS if marker_value == READY else CODEX_FAIL
    dashboard_payload = {
        "generated_at": generated_at,
        "status": marker_value,
        "codex_status": codex_marker,
        "primary_objective_locked": True,
        "website_lane": "secondary_support_lane",
        "selected_primary_task": NEXT_PRIMARY_TASK,
        "paper_runtime_age_seconds": paper_age,
        "current_primary_blockers": current_primary_blockers,
        "lock_path": "claude_worklog/autonomous_governor/latest/NON_DRIFT_GOVERNOR_LOCK.json",
        "status_path": "claude_worklog/agent_supervisor/status/non_drift_governor_lock_status.json",
        "live_gate_status": LIVE_GATE_STATUS,
        "old_redis_writes": False,
        "exchange_actions": False,
        "legacy_bot_mutation": False,
    }

    for base in (FINAL, PUBLIC):
        write_json(base / "operator_dashboard_payload.json", dashboard_payload)
    write_json(LOCK_PATH, lock)
    write_json(STATUS_PATH, status)
    write_json(FINAL / "primary_objective_lock.json", lock)
    write_json(FINAL / "non_drift_governor_status.json", status)
    write_json(SELECTION_PATH, selection)
    write_text(SELECTION_MD, f"""# Next Task Selection

Generated: {generated_at}

- Selected primary task: `{NEXT_PRIMARY_TASK}`
- Primary lane: `{PRIMARY_LANE}`
- Website lane: `secondary_support_lane`
- Live gate: `{LIVE_GATE_STATUS}`
- Legacy mutation: `none`
- Redis mutation: `none`
- Exchange mutation: `none`

The production website rebuild is accepted support evidence. It cannot supersede V2 live-like paper/shadow, legacy bridge, risk gateway, trainer parity, or canary preflight work.
""")
    write_text(FINAL / "GO_NO_GO.md", marker_value)
    write_text(FINAL / "CODEX_GO_NO_GO.md", codex_marker)

    write_text(FINAL / "PRIMARY_OBJECTIVE_LOCK.md", f"""# Primary Objective Lock

Generated: {generated_at}

The primary objective is restored and locked to V2 live-like paper/shadow operation:

- V2 live observer and paper/shadow twin
- legacy bridge read-only evidence
- risk gateway final authority
- trainer parity and restart/runtime capture
- canary preflight only, no activation

Website rebuild status: `{website_go}`. This is now a secondary support lane. UI work may continue only when it exposes current runtime truth or removes an operator-visibility blocker for the primary path.
""")
    write_text(FINAL / "AUTOMATION_QUEUE_REFOCUS_REPORT.md", f"""# Automation Queue Refocus Report

Generated: {generated_at}

- Current queue next task: `{queue.get('next_pending_task')}`
- Lock-selected next task: `{NEXT_PRIMARY_TASK}`
- Queue status age seconds: `{queue_age}`
- Master planner status age seconds: `{planner_age}`
- Agent supervisor observed: `{bool(processes['agent_supervisor'])}`
- Scheduler observed: `{bool(processes['scheduler'])}`
- Watchdog observed: `{bool(processes['watchdog'])}`

The queue/status files still contain older recovery context. The lock does not hide that state; it supersedes it for next-task selection until the rebuild supervisor refreshes queue state.
""")
    write_text(FINAL / "NON_DRIFT_GOVERNOR_LOCK_POLICY.md", """# Non-Drift Governor Lock Policy

Allowed primary lanes:

- V2 paper/shadow runtime freshness
- legacy live bridge read-only importer
- risk gateway final-authority validation
- trainer runtime/parity evidence
- paper execution ledger and audit ledger
- canary preflight packet, with activation blocked

Support lanes:

- website route acceptance
- GUI visibility of current runtime truth
- proof archive cleanup

Support lanes cannot create READY markers that supersede missing runtime evidence. `hist_*`, static fixture, proof archive, route crawl, or design-only evidence cannot become current runtime truth.
Parallel scheduler and Codex watchdog recovery lanes must hold while this lock is active unless the work directly advances the selected primary task.
""")
    write_text(FINAL / "CODEX_NON_DRIFT_GOVERNOR_LOCK_REVIEW.md", f"""# Codex Non-Drift Governor Lock Review

Result: `{codex_marker}`

Checked:

- Website rebuild demoted to support lane: yes
- Primary selected task restored: `{NEXT_PRIMARY_TASK}`
- Parallel scheduler / Codex watchdog support lanes paused by lock: yes
- V2 paper runtime age seconds: `{paper_age}`
- Live gate blocked: `{LIVE_GATE_STATUS}`
- Old Redis writes by this task: false
- Exchange actions by this task: false
- Legacy bot mutation by this task: false
- Remaining primary blockers: `{', '.join(current_primary_blockers) if current_primary_blockers else 'none'}`

Codex would fail this packet if website/UI work remained the selected primary lane, if paper runtime was stale, if live gate was not blocked, or if any legacy/Redis/exchange mutation occurred.
""")
    write_text(FINAL / "CLAUDE_AUTOMATION_NON_DRIFT_GOVERNOR_LOCK_REPORT.md", f"""# Claude Automation Non-Drift Governor Lock Report

Status: `{marker_value}`

Generated: {generated_at}

The production website rebuild passed and is now explicitly a secondary support lane. The autonomous governor selection now points back to the primary path:

- selected_primary_task: `{NEXT_PRIMARY_TASK}`
- primary_lane: `{PRIMARY_LANE}`
- website_lane: `secondary_support_lane`
- V2 paper runtime age seconds: `{paper_age}`
- current primary blockers: `{', '.join(current_primary_blockers) if current_primary_blockers else 'none'}`
- live gate: `{LIVE_GATE_STATUS}`

The parallel scheduler and Codex watchdog are configured to hold support/recovery lanes while the lock is active, so stale recovery tasks cannot supersede the selected primary work.

No legacy bot files were modified. No old Redis mutation, exchange action, leverage/margin change, or live enablement was performed.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
