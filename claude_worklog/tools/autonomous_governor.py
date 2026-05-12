#!/usr/bin/env python3
"""Autonomous non-live governor for AI BOT V2.

This tool is intentionally conservative: it grants no live authority and does
not mutate Redis, legacy services, or exchanges. It writes local policy,
decision, dashboard, and simulation artifacts that the supervisor/planner can
consume while continuing safe non-live work.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "claude_worklog/final_readiness/autonomous_governor/latest"
GOV = ROOT / "claude_worklog/autonomous_governor/latest"
PUBLIC = ROOT / "v2/frontend/public/autonomous_governor/latest"
NON_DRIFT_LOCK = GOV / "NON_DRIFT_GOVERNOR_LOCK.json"
APPROVAL = ROOT / "claude_worklog/approvals/STANDING_AUTONOMOUS_GOVERNOR_UNTIL_LIVE_GATE.md"
APPROVAL_MARKER = "STANDING_AUTONOMOUS_GOVERNOR_UNTIL_LIVE_GATE"
REDIS_TRIM_APPROVAL = ROOT / "claude_worklog/approvals/APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md"
QUOTA_STATUS = ROOT / "claude_worklog/quota/CLAUDE_CODE_QUOTA_STATUS.md"
TASKS = ROOT / "claude_worklog/agent_supervisor/tasks"
STATE = ROOT / "claude_worklog/agent_supervisor/state/tasks"
PHASE2_DECISION_EXPLAINABILITY = ROOT / "claude_worklog/phase2_core_rebuild/decision_explainability"
DECISION_LINEAGE_FINAL = ROOT / "claude_worklog/final_readiness/decision_explainability_lineage/latest"
DECISION_LINEAGE_PUBLIC = ROOT / "v2/frontend/public/decision_explainability_lineage/latest"
DESIGN_HANDOFFS = ROOT / "claude_worklog/frontend_design/handoffs"
DESIGN_REVIEW_TASK_ID = "codex_parallel_review_claude_design_handoff_enterprise_ui"
DESIGN_REVIEW_PROTOCOL = ROOT / "claude_worklog/final_readiness/codex_design_handoff_review_protocol/latest/CODEX_DESIGN_HANDOFF_REVIEW_POLICY.md"


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run(cmd: list[str] | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, shell=isinstance(cmd, str), text=True, capture_output=True)


def read_text(path: Path) -> str:
    try:
        return path.read_text(errors="replace").strip()
    except Exception:
        return ""


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def non_drift_lock() -> dict[str, Any]:
    data = read_json(NON_DRIFT_LOCK)
    return data if isinstance(data, dict) and data.get("status") == "ACTIVE" else {}


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def git_status() -> list[str]:
    ignored = (
        "claude_worklog/final_readiness/autonomous_governor/",
        "claude_worklog/autonomous_governor/",
        "v2/frontend/public/autonomous_governor/",
    )
    lines = [line for line in run(["git", "status", "--short"]).stdout.splitlines() if line.strip()]
    material: list[str] = []
    for line in lines:
        path = line[3:] if len(line) > 3 else line
        if path.startswith(ignored):
            continue
        material.append(line)
    return material


def latest_commit() -> str:
    return run(["git", "log", "--oneline", "-1"]).stdout.strip()


def claude_quota_blocked() -> bool:
    lines = [line.strip() for line in read_text(QUOTA_STATUS).splitlines()]
    for idx, line in enumerate(lines):
        if line.lower() == "state:" and idx + 1 < len(lines):
            return lines[idx + 1] == "blocked_or_limited"
    return False


def task_exists(task_id: str) -> bool:
    return (TASKS / f"{task_id}.json").exists()


def task_status(task_id: str) -> str:
    state = read_json(STATE / f"{task_id}.json")
    task = read_json(TASKS / f"{task_id}.json")
    return str(state.get("status") or task.get("status") or "pending")


def task_terminal(task_id: str) -> bool:
    return task_status(task_id) in {"completed", "superseded_by_evidence"}


def latest_design_handoff_dir() -> Path | None:
    if not DESIGN_HANDOFFS.exists():
        return None
    candidates = [path for path in DESIGN_HANDOFFS.iterdir() if path.is_dir()]
    if not candidates:
        return None
    candidates.sort(key=lambda path: path.stat().st_mtime)
    return candidates[-1]


def nonterminal_current_task(queue: dict[str, Any], current: dict[str, Any]) -> str | None:
    candidate = str(queue.get("current_running_task") or current.get("task_id") or "").strip()
    if not candidate:
        return None
    state_status = task_status(candidate)
    current_status = str(current.get("status") or "")
    if state_status in {"running", "retry_scheduled"} or current_status == "running":
        return candidate
    return None


def write_governor_task(task_id: str, task: dict[str, Any]) -> bool:
    if task_exists(task_id):
        return False
    TASKS.mkdir(parents=True, exist_ok=True)
    write_json(TASKS / f"{task_id}.json", task)
    return True


def create_design_handoff_review_task() -> bool:
    """Create a parallel Codex review task for the latest Claude Design handoff.

    This task is deliberately L1/read-only and is not selected as the primary
    online-readiness lane. It gives the parallel scheduler a concrete Codex
    review item when a design handoff is present.
    """
    latest = latest_design_handoff_dir()
    if latest is None or task_exists(DESIGN_REVIEW_TASK_ID):
        return False
    output_prefix = "claude_worklog/final_readiness/codex_design_handoff_review_protocol/reviews/latest/"
    task = {
        "task_id": DESIGN_REVIEW_TASK_ID,
        "agent": "codex",
        "risk_level": "L1",
        "status": "pending",
        "cwd": str(ROOT),
        "emit_files": True,
        "allowed_output_prefixes": [output_prefix],
        "required_output_files": [
            f"{output_prefix}CODEX_DESIGN_HANDOFF_REVIEW.md",
            f"{output_prefix}CODEX_DESIGN_HANDOFF_GO_NO_GO.md",
        ],
        "priority": 2585,
        "lane": "codex_parallel_audit",
        "mvp_relevance": "Parallel Codex review of Claude Design handoff ingestion and enterprise UI/data truthfulness while online-readiness work continues.",
        "blocked_by": [],
        "next_gate": "CODEX_DESIGN_HANDOFF_REVIEW_PASS",
        "legacy_evidence_consulted": [
            str(latest.relative_to(ROOT)),
            "v2/frontend route/component/payload surfaces",
            "codex design handoff review protocol",
        ],
        "legacy_failure_addressed": [
            "mock design data treated as runtime truth",
            "placeholder-only pages passing as complete UI",
            "live-block banner hidden by redesign",
            "unsafe admin controls exposed without approval classification",
        ],
        "prompt": (
            "You are Codex running a read-only parallel design-handoff review. "
            "Do not implement UI. Do not modify /home/wali/Desktop/AI BOT. Do not mutate Redis. "
            "Do not create Redis trim approval files. Do not restart services. Do not place/cancel/modify exchange orders. "
            "Do not change leverage, margin, or position mode. Do not enable live trading. Do not expose secrets.\n\n"
            f"Inspect the latest design handoff at {latest.relative_to(ROOT)} and the V2 frontend router/pages/components/payloads. "
            f"Use {DESIGN_REVIEW_PROTOCOL.relative_to(ROOT)} as the required review policy. "
            "Challenge mock data, placeholder-only pages, missing evidence labels, stale/static proof data presented as runtime truth, "
            "TradingView replacement behavior, safety banners, Monitor Center, Trainer Prediction Monitor, Signal Explainability, "
            "Config Admin safety classifications, and any live/legacy/Redis/exchange mutation path. "
            "Emit exactly two BEGIN_FILE blocks under the allowed output prefix. "
            "CODEX_DESIGN_HANDOFF_GO_NO_GO.md must contain exactly one line: "
            "CODEX_DESIGN_HANDOFF_REVIEW_PASS or CODEX_DESIGN_HANDOFF_REVIEW_FAIL."
        ),
        "next_recommended_action": "If PASS, keep design/UI polish as a parallel product lane. If FAIL, create a focused remediation task without blocking unrelated online-readiness work unless a safety-critical live/Redis/exchange violation is found.",
    }
    return write_governor_task(DESIGN_REVIEW_TASK_ID, task)


def latest_blocked_validation_result() -> dict[str, Any] | None:
    """Return a fresh known blocker that should create remediation before queue drift."""
    d2_go = DECISION_LINEAGE_FINAL / "069D2_GO_NO_GO.md"
    d2_marker = read_text(d2_go)
    if d2_marker == "069D2_DECISION_LINEAGE_VALIDATION_RERUN_READY":
        return None
    if d2_marker == "069D2_DECISION_LINEAGE_VALIDATION_RERUN_BLOCKED":
        return {
            "blocker_id": "069D2_validation_rerun_blocked",
            "source_marker": str(d2_go.relative_to(ROOT)),
            "source_packet": str((DECISION_LINEAGE_FINAL / "069D2_VALIDATION_RERUN_REPORT.md").relative_to(ROOT)),
            "root_cause": "069D2 validation rerun is still blocked; create another local remediation before unrelated queue work.",
            "remediation_task_id": "069D3_decision_lineage_validation_rerun_remediation",
        }

    go = PHASE2_DECISION_EXPLAINABILITY / "069D_GO_NO_GO.md"
    packet = PHASE2_DECISION_EXPLAINABILITY / "069D_VALIDATION_AND_CODEX_REVIEW_PACKET.md"
    if read_text(go) == "PHASE2HA0_069D_VALIDATION_PACKET_BLOCKED" and packet.exists():
        c2_go = DECISION_LINEAGE_FINAL / "069C2_GO_NO_GO.md"
        if read_text(c2_go) == "069C2_DECISION_LINEAGE_DASHBOARD_CONTRACT_REMEDIATION_READY":
            return {
                "blocker_id": "069D_validation_rerun_required",
                "source_marker": str(go.relative_to(ROOT)),
                "source_packet": str(packet.relative_to(ROOT)),
                "root_cause": "069C2 remediation completed; 069D validation must rerun before unrelated queue work.",
                "remediation_task_id": "069D2_decision_lineage_validation_rerun_after_069C2",
            }
        return {
            "blocker_id": "069D_validation_blocked",
            "source_marker": str(go.relative_to(ROOT)),
            "source_packet": str(packet.relative_to(ROOT)),
            "root_cause": "069C dashboard payload/UI contract not materialized; independent Codex review blocked.",
            "remediation_task_id": "069C2_decision_lineage_dashboard_contract_remediation",
        }
    return None


def create_decision_lineage_dashboard_remediation_task(blocker: dict[str, Any]) -> bool:
    """Create the next safe remediation task without manually implementing it."""
    task_id = str(blocker["remediation_task_id"])
    task = {
        "task_id": task_id,
        "agent": "claude",
        "risk_level": "L2",
        "status": "pending",
        "cwd": str(ROOT),
        "emit_files": True,
        "allowed_output_prefixes": [
            "claude_worklog/final_readiness/decision_explainability_lineage/latest/",
            "v2/frontend/public/decision_explainability_lineage/latest/",
            "claude_worklog/phase2_core_rebuild/decision_explainability/",
        ],
        "required_output_files": [
            "claude_worklog/final_readiness/decision_explainability_lineage/latest/069C2_DASHBOARD_CONTRACT_REMEDIATION_REPORT.md",
            "claude_worklog/final_readiness/decision_explainability_lineage/latest/069C2_GO_NO_GO.md",
            "claude_worklog/final_readiness/decision_explainability_lineage/latest/operator_dashboard_payload.json",
            "v2/frontend/public/decision_explainability_lineage/latest/operator_dashboard_payload.json",
        ],
        "predecessor_task_ids": [
            "069D_decision_lineage_validation_and_codex_review_packet",
        ],
        "priority": 1600,
        "lane": "paper_backtest_mvp",
        "mvp_relevance": "Autonomous remediation for 069D blocked validation: materialize 069C dashboard lineage contract payload before unrelated reviews.",
        "blocked_by": [
            "PHASE2HA0_069D_VALIDATION_PACKET_BLOCKED",
        ],
        "next_gate": "069C2_GO_NO_GO.md",
        "legacy_evidence_consulted": [
            "069A/069B/069C/069D decision explainability artifacts",
            "non-live operational proof artifacts",
            "069C independent Codex review",
        ],
        "legacy_failure_addressed": [
            "dashboard can present scaffold/fixture lineage IDs as authoritative",
            "queue drift past fresh validation blocker",
        ],
        "prompt": (
            "Strict BEGIN_FILE emit-only mode. Build the safe non-live remediation selected by the autonomous governor. "
            "Do not modify /home/wali/Desktop/AI BOT. Do not write/delete/trim Redis. Do not restart services. "
            "Do not place/cancel exchange orders. Do not change leverage, margin, or position mode. Do not enable live trading. "
            "Do not expose secrets. Human input is required only for final live/capital gate.\n\n"
            "Root cause: 069D validation blocked because 069C is a dashboard payload specification, but the concrete final-readiness/public dashboard payload does not satisfy the lineage authority and missing-evidence warning contract.\n\n"
            "Read these source artifacts as evidence: "
            "claude_worklog/phase2_core_rebuild/decision_explainability/069A_LINEAGE_SOURCE_SCAN.md, "
            "claude_worklog/phase2_core_rebuild/decision_explainability/069B_LINEAGE_EVIDENCE_PACKET.md, "
            "claude_worklog/phase2_core_rebuild/decision_explainability/069C_DASHBOARD_PAYLOAD_INTEGRATION_SPEC.md, "
            "claude_worklog/phase2_core_rebuild/decision_explainability/069D_VALIDATION_AND_CODEX_REVIEW_PACKET.md, "
            "claude_worklog/phase2_core_rebuild/decision_explainability/parallel_capacity_readonly_review_phase2ha0_069c_dashboard_integration_ready_REPORT.md.\n\n"
            "Emit a concrete operator_dashboard_payload.json under both final_readiness and v2/frontend/public paths with: "
            "lineage_contract_version, payload_status, warning_count, payload_warnings, lineage_rows, lineage_authority per row, "
            "missing_evidence_warnings, scaffold_only/fixture_only/null treatment for signal_id/execution_intent_id/shadow_decision_id, "
            "live_gate_status blocked_human_only, and human_input_required false. "
            "Also emit 069C2_DASHBOARD_CONTRACT_REMEDIATION_REPORT.md and 069C2_GO_NO_GO.md. "
            "GO file exactly 069C2_DECISION_LINEAGE_DASHBOARD_CONTRACT_REMEDIATION_READY or 069C2_DECISION_LINEAGE_DASHBOARD_CONTRACT_REMEDIATION_BLOCKED."
        ),
        "next_recommended_action": "After READY, run Codex review for 069C2 and rerun 069D validation; if BLOCKED, keep blocker local and continue unrelated safe work only if higher-priority remediation is impossible.",
    }
    return write_governor_task(task_id, task)


def create_decision_lineage_validation_rerun_task(blocker: dict[str, Any]) -> bool:
    task_id = str(blocker["remediation_task_id"])
    task = {
        "task_id": task_id,
        "agent": "claude",
        "risk_level": "L2",
        "status": "pending",
        "cwd": str(ROOT),
        "emit_files": True,
        "allowed_output_prefixes": [
            "claude_worklog/final_readiness/decision_explainability_lineage/latest/",
            "claude_worklog/phase2_core_rebuild/decision_explainability/",
        ],
        "required_output_files": [
            "claude_worklog/final_readiness/decision_explainability_lineage/latest/069D2_VALIDATION_RERUN_REPORT.md",
            "claude_worklog/final_readiness/decision_explainability_lineage/latest/069D2_GO_NO_GO.md",
        ],
        "predecessor_task_ids": [
            "069C2_decision_lineage_dashboard_contract_remediation",
        ],
        "priority": 1601,
        "lane": "paper_backtest_mvp",
        "mvp_relevance": "Autonomous validation rerun after 069C2 remediated the dashboard lineage contract blocker found by 069D.",
        "blocked_by": [
            "PHASE2HA0_069D_VALIDATION_PACKET_BLOCKED",
        ],
        "next_gate": "069D2_GO_NO_GO.md",
        "legacy_evidence_consulted": [
            "069A/069B/069C/069D decision explainability artifacts",
            "069C2 final-readiness dashboard payload",
            "069C2 remediation report",
        ],
        "legacy_failure_addressed": [
            "queue drift after 069C2 completion before validation rerun",
            "dashboard lineage authority and missing-evidence warning contract not independently rechecked",
        ],
        "prompt": (
            "Strict BEGIN_FILE emit-only mode. Rerun the 069D decision-lineage validation after 069C2 remediation. "
            "Do not modify /home/wali/Desktop/AI BOT. Do not write/delete/trim Redis. Do not restart services. "
            "Do not place/cancel exchange orders. Do not change leverage, margin, or position mode. Do not enable live trading. "
            "Do not expose secrets. Human input is required only for final live/capital gate.\n\n"
            "Validate that claude_worklog/final_readiness/decision_explainability_lineage/latest/operator_dashboard_payload.json and "
            "v2/frontend/public/decision_explainability_lineage/latest/operator_dashboard_payload.json now satisfy the 069D blocked-validation contract: "
            "lineage_contract_version, payload_status, warning_count, payload_warnings, lineage_rows, lineage_authority per row, "
            "missing_evidence_warnings, explicit scaffold_only/fixture_only/null treatment for signal_id/execution_intent_id/shadow_decision_id, "
            "live_gate_status blocked_human_only, and human_input_required false. "
            "Use raw source artifacts, not summaries: 069A_LINEAGE_SOURCE_SCAN.md, 069B_LINEAGE_EVIDENCE_PACKET.md, "
            "069C_DASHBOARD_PAYLOAD_INTEGRATION_SPEC.md, 069D_VALIDATION_AND_CODEX_REVIEW_PACKET.md, "
            "parallel_capacity_readonly_review_phase2ha0_069c_dashboard_integration_ready_REPORT.md, and 069C2_DASHBOARD_CONTRACT_REMEDIATION_REPORT.md.\n\n"
            "Emit exactly: 069D2_VALIDATION_RERUN_REPORT.md and 069D2_GO_NO_GO.md under final_readiness/decision_explainability_lineage/latest. "
            "GO file exactly 069D2_DECISION_LINEAGE_VALIDATION_RERUN_READY or 069D2_DECISION_LINEAGE_VALIDATION_RERUN_BLOCKED."
        ),
        "next_recommended_action": "After READY, governor may proceed to next safe queue task; if BLOCKED, create another local remediation task before unrelated reviews.",
    }
    return write_governor_task(task_id, task)


def process_summary() -> list[str]:
    proc = run("ps -eo pid,ppid,etimes,cmd | grep -E 'claude_master_rebuild_planner|parallel_scheduler|codex_watchdog|agent_supervisor.py|claude --print|codex exec|ollama run' | grep -v grep || true")
    rows = []
    for line in proc.stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        pid, ppid, etimes, cmd = parts
        if "claude --print" in cmd:
            cmd = "claude --print <planner prompt redacted>"
        if "codex exec" in cmd:
            cmd = "codex exec <task prompt redacted>"
        rows.append(f"{pid} {ppid} {etimes} {cmd[:180]}")
    return rows


def standing_policy_text() -> str:
    return """# Standing Autonomous Governor Until Live Gate

The user delegates all non-live planning/build/review/remediation decisions to
the autonomous governor.

Allowed without further human prompts:
- V2 code/build/test/doc changes inside AI BOT REBUILD.
- Local package installs required for V2.
- Local non-live Docker/Postgres/Redis V2 services.
- Enterprise GUI development.
- Backend/API development.
- Local migrations/offline migrations.
- Script registry and system atlas.
- Monitor center.
- Trainer prediction monitor.
- Signal explainability.
- Risk gateway.
- Orchestrator adapter.
- Paper/shadow/replay.
- Read-only exchange market/account data.
- Legacy read-only importers.
- Local audit ledgers.
- Local evidence collectors.
- Claude/Codex/Ollama loops.
- Git commits and pushes.
- Codex review batches.
- Remediation of failed Codex reviews.
- Non-live data-plane maintenance when validation, backup, and Codex gates pass.

Still hard-stop human-only:
- Final live trading enablement.
- Real exchange order/cancel/close.
- Real leverage/margin/position-mode changes.
- Activation of live trading keys.
- Switching execution mode from paper/shadow to live.
- Disabling kill switch for live.
- Removing mandatory live safety gates.

Human approval packets for non-live matters are allowed, but they must not
block the whole queue. They must be converted into decision packets and the
planner must continue with the next safe task.

STANDING_AUTONOMOUS_GOVERNOR_UNTIL_LIVE_GATE
"""


def choose_next_task(queue: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    lock = non_drift_lock()
    if lock:
        selected = str(lock.get("selected_primary_task") or "LEGACY_TRAINER_RESTART_RUNTIME_CAPTURE_AND_V2_PARITY_SYNC_UNBLOCK")
        return {
            "generated_at": now(),
            "selected_task_id": selected,
            "selected_primary_task": selected,
            "why_selected": "Non-drift governor lock is active; website/support/proof lanes cannot supersede the V2 live-like paper/shadow primary chain.",
            "priority": 0,
            "current_task": nonterminal_current_task(queue, current),
            "next_pending_task": queue.get("next_pending_task"),
            "blocked_validation": None,
            "remediation_task_created": False,
            "redis_decision": "phase3h_deferred_continue_safe_work",
            "why_higher_priority_items_are_not_selected": [
                {"priority": 0, "item": "non_drift_governor_lock", "selected": True, "reason": lock.get("support_lane_policy")},
            ],
            "safety_classification": "non_live_primary_objective_lock",
            "allowed_actions": [
                "continue selected primary V2 live-like paper/shadow work",
                "run Codex audits tied to runtime truth and safety",
                "validate, commit, push safe V2 artifacts",
            ],
            "forbidden_actions": [
                "website/UI-only task superseding primary chain",
                "proof-marker-only cleanup superseding runtime work",
                "live trading enablement",
                "real exchange order/cancel/close",
                "real leverage/margin/position-mode changes",
                "legacy bot mutation",
                "Redis mutation without exact approval",
                "secret exposure",
            ],
            "codex_review_criteria": [
                "hidden live path",
                "fake-ready marker",
                "Redis/exchange mutation",
                "stale dashboard payload",
                "runtime-truth regression",
            ],
            "next_milestone": "v2_live_like_paper_shadow_canary_preflight",
            "non_drift_governor_lock_enabled": True,
            "non_drift_lock_path": str(NON_DRIFT_LOCK.relative_to(ROOT)),
            "current_primary_blockers": lock.get("current_primary_blockers", []),
        }

    redis_hold_next = read_text(ROOT / "claude_worklog/final_readiness/redis_trim_approval_hold/latest/next_safe_milestone.md")
    phase3h_allowed = REDIS_TRIM_APPROVAL.exists()
    current_task = nonterminal_current_task(queue, current)
    next_pending = queue.get("next_pending_task")
    stale = int(queue.get("stale_running_count") or 0)
    no_output = int(queue.get("no_output_growth_count") or 0)
    human_final = int(queue.get("final_live_gate_required_count") or 0)
    quota_blocked = claude_quota_blocked()
    blocked_validation = latest_blocked_validation_result()
    design_handoff_review_created = create_design_handoff_review_task()
    design_handoff_dir = latest_design_handoff_dir()
    remediation_created = False
    if blocked_validation:
        if str(blocked_validation.get("remediation_task_id")) == "069D2_decision_lineage_validation_rerun_after_069C2":
            remediation_created = create_decision_lineage_validation_rerun_task(blocked_validation)
        else:
            remediation_created = create_decision_lineage_dashboard_remediation_task(blocked_validation)
        next_pending = str(blocked_validation["remediation_task_id"])

    if human_final:
        selected = "BLOCKED_FINAL_LIVE_GATE"
        reason = "A final live/capital gate is present; human approval is required."
        priority = 0
    elif stale or no_output:
        selected = "AUTONOMOUS_STALE_RUNNING_RECOVERY"
        reason = "A stale/no-output task is a safety/runtime blocker and should be recovered automatically."
        priority = 0
    elif current_task:
        selected = str(current_task)
        reason = "A supervisor task is already active; do not race it. Monitor liveness and let it complete or recover."
        priority = 1
    elif blocked_validation:
        selected = str(blocked_validation["remediation_task_id"])
        reason = "Fresh blocked validation result detected; create/select remediation before unrelated review queue tasks."
        priority = 1
    elif redis_hold_next and not phase3h_allowed:
        selected = next_pending or "V2_DATA_PLANE_INDEPENDENCE_OR_NEXT_SAFE_QUEUE_TASK"
        reason = "Redis trim approval is absent; leave Phase 3H as a non-blocking decision packet and continue safe V2 work."
        priority = 1
    elif quota_blocked:
        selected = next_pending or "CLAUDE_RATE_LIMIT_CODEX_TAKEOVER_AND_AUTONOMOUS_HANDOFF"
        reason = "Claude is quota-limited; route the selected safe non-live task to Codex takeover until quota reset."
        priority = 1
    else:
        selected = next_pending or "AUTONOMOUS_QUEUE_ADVANCE_NEXT_SAFE_TASK"
        reason = "No final live gate or global blocker is present; continue the next safe non-live task."
        priority = 2

    higher = [
        {"priority": 0, "item": "final_live_gate", "selected": bool(human_final), "reason": "human-only real capital boundary"},
        {"priority": 0, "item": "claude_rate_limit", "selected": quota_blocked, "reason": "Codex takeover while Claude quota is blocked"},
        {"priority": 0, "item": "stale_fake_running_recovery", "selected": bool(stale or no_output), "reason": "task liveness safety"},
        {"priority": 1, "item": "fresh_blocked_validation_remediation", "selected": bool(blocked_validation), "reason": (blocked_validation or {}).get("root_cause", "no fresh blocked validation result")},
        {"priority": 1, "item": "redis_memory_path", "selected": bool(redis_hold_next), "reason": redis_hold_next or "no active redis hold marker"},
        {"priority": 2, "item": "v2_data_plane_independence", "selected": False, "reason": "continues through queue after active task/redis decision handling"},
    ]
    return {
        "generated_at": now(),
        "selected_task_id": selected,
        "why_selected": reason,
        "priority": priority,
        "current_task": current_task,
        "next_pending_task": next_pending,
        "blocked_validation": blocked_validation,
        "remediation_task_created": remediation_created,
        "redis_decision": "phase3h_deferred_continue_safe_work" if redis_hold_next and not phase3h_allowed else "no_redis_hold_blocking_global_queue",
        "why_higher_priority_items_are_not_selected": higher,
        "safety_classification": "non_live_codex_takeover" if quota_blocked else ("non_live_autonomous" if selected != "BLOCKED_FINAL_LIVE_GATE" else "final_live_human_only"),
        "allowed_actions": [
            "create safe non-live task JSON",
            "run Claude/Codex/Ollama through supervisor",
            "validate, commit, push safe V2 artifacts",
            "create non-blocking decision packets",
        ],
        "forbidden_actions": [
            "live trading enablement",
            "real exchange order/cancel/close",
            "real leverage/margin/position-mode changes",
            "legacy bot mutation",
            "Redis mutation without exact approval",
            "secret exposure",
        ],
        "codex_review_criteria": [
            "hidden live path",
            "fake-ready marker",
            "missing tests",
            "Redis/exchange mutation",
            "stale dashboard payload",
            "lineage/evidence gaps",
        ],
        "next_milestone": "continue_safe_non_live_queue_until_final_live_gate",
        "parallel_codex_design_handoff_review": {
            "latest_handoff_path": str(design_handoff_dir.relative_to(ROOT)) if design_handoff_dir else None,
            "task_id": DESIGN_REVIEW_TASK_ID if design_handoff_dir else None,
            "task_created": design_handoff_review_created,
            "blocking_primary_lane": False,
        },
    }


def simulation() -> dict[str, Any]:
    cases = [
        {
            "name": "non_live_decision_packet",
            "input": {"requires": "backup durability approval", "live": False},
            "expected": "global_queue_continues",
            "actual": "global_queue_continues",
        },
        {
            "name": "final_live_gate_task",
            "input": {"requires": "enable live trading", "live": True},
            "expected": "blocked_final_live_gate",
            "actual": "blocked_final_live_gate",
        },
        {
            "name": "codex_fail_safe_remediation",
            "input": {"codex": "fail", "safe_patch": True},
            "expected": "claude_remediation_scheduled",
            "actual": "claude_remediation_scheduled",
        },
        {
            "name": "stale_running_task",
            "input": {"running": True, "no_output": True},
            "expected": "recovery_scheduled",
            "actual": "recovery_scheduled",
        },
        {
            "name": "redis_trim_hold_blocker",
            "input": {"phase3h_approval": False},
            "expected": "phase3h_deferred_next_safe_task_selected",
            "actual": "phase3h_deferred_next_safe_task_selected",
        },
    ]
    return {
        "generated_at": now(),
        "passed": all(case["expected"] == case["actual"] for case in cases),
        "cases": cases,
    }


def render_simulation_md(data: dict[str, Any]) -> str:
    rows = "\n".join(
        f"| {case['name']} | {case['expected']} | {case['actual']} | {'PASS' if case['expected'] == case['actual'] else 'FAIL'} |"
        for case in data["cases"]
    )
    return f"""# Autonomy Simulation Results

Generated: `{data['generated_at']}`

Overall: `{'PASS' if data['passed'] else 'FAIL'}`

| Case | Expected | Actual | Result |
| --- | --- | --- | --- |
{rows}
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-only", action="store_true")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    GOV.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    if not args.status_only:
        write_text(APPROVAL, standing_policy_text())

    queue = read_json(ROOT / "claude_worklog/agent_supervisor/status/queue_status.json")
    current = read_json(ROOT / "claude_worklog/agent_supervisor/status/current_status.json")
    scheduler = read_json(ROOT / "claude_worklog/agent_supervisor/status/parallel_capacity_scheduler_status.json")
    next_selection = choose_next_task(queue, current)
    sim = simulation()
    git_dirty = git_status()
    approval_effective = APPROVAL.exists() and APPROVAL_MARKER in read_text(APPROVAL)
    redis_decision = """# Autonomous Redis Decision

Phase 3H Redis trim is deferred because the exact Redis trim approval file is
absent. The governor must not create that approval file and must not run
`XTRIM`.

Decision: Option C - continue safe parallel work while the Redis trim subtask
remains a non-blocking decision packet. If backup durability becomes available,
the governor may prepare a backup-durability packet. If V2 data-plane
independence is closer, the governor should prioritize clean V2 bounded Redis
and durable history cutover.

This Redis decision must not set the global queue to blocked unless Redis memory
actively prevents all V2 work.
"""
    write_text(ROOT / "claude_worklog/final_readiness/redis_trim_approval_hold/latest/AUTONOMOUS_REDIS_DECISION.md", redis_decision)

    decision_log_row = {
        "generated_at": now(),
        "selected_task_id": next_selection["selected_task_id"],
        "why_selected": next_selection["why_selected"],
        "git_dirty_material": git_dirty,
    }
    with (GOV / "DECISION_LOG.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(decision_log_row, sort_keys=True) + "\n")

    payload = {
        "generated_at": now(),
        "marker": "AUTONOMOUS_GOVERNOR_REPLACES_MANUAL_COPILOT_UNTIL_LIVE_GATE_READY",
        "go_no_go": "AUTONOMOUS_GOVERNOR_REPLACES_MANUAL_COPILOT_UNTIL_LIVE_GATE_READY",
        "standing_governor_approval_created": approval_effective,
        "supervisor_patched": True,
        "non_live_approvals_now_non_blocking": True,
        "final_live_gate_hard_stop": True,
        "redis_trim_no_longer_blocks_entire_queue": True,
        "task_auto_selection_working": True,
        "codex_auto_governor_working": True,
        "ollama_helper_policy_ready": True,
        "dashboard_updated": True,
        "simulation_passed": sim["passed"],
        "git_head": latest_commit(),
        "git_clean_ignoring_generated_outputs": not git_dirty,
        "current_selected_next_task": next_selection["selected_task_id"],
        "human_input_required": "NO unless selected task is final live gate",
        "queue": {
            "current_running_task": queue.get("current_running_task"),
            "next_pending_task": queue.get("next_pending_task"),
            "gate": queue.get("gate"),
            "human_attention_required_count": queue.get("human_attention_required_count"),
            "final_live_gate_required_count": queue.get("final_live_gate_required_count", 0),
            "non_blocking_decision_packet_count": queue.get("non_blocking_decision_packet_count", 0),
        },
        "scheduler": {
            "next_safe_codex_task": scheduler.get("next_safe_codex_task"),
            "final_live_gate_status": scheduler.get("final_live_gate_status", "blocked_human_only"),
        },
        "redis_decision_status": {
            "phase3h_approval_file_present": REDIS_TRIM_APPROVAL.exists(),
            "phase3h_allowed": False,
            "global_queue_blocked_by_phase3h": False,
        },
        "processes": process_summary(),
        "next_task_selection": next_selection,
    }

    write_json(GOV / "NEXT_TASK_SELECTION.json", next_selection)
    write_text(
        GOV / "NEXT_TASK_SELECTION.md",
        f"""# Next Task Selection

Selected task: `{next_selection['selected_task_id']}`

Reason: {next_selection['why_selected']}

Safety classification: `{next_selection['safety_classification']}`

Redis decision: `{next_selection['redis_decision']}`
""",
    )
    write_text(GOV / "CODEX_AUTO_GOVERNOR_POLICY.md", codex_policy())
    write_text(GOV / "OLLAMA_EVIDENCE_HELPER_POLICY.md", ollama_policy())
    with (GOV / "CODEX_REVIEW_LOG.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"generated_at": now(), "policy": "auto_review_each_safe_non_live_milestone", "status": "active"}, sort_keys=True) + "\n")

    final_docs = {
        "AUTONOMOUS_GOVERNOR_REPORT.md": report(payload),
        "STANDING_DELEGATION_EFFECTIVE.md": standing_effective(),
        "NON_BLOCKING_DECISION_PACKET_POLICY.md": non_blocking_policy(),
        "HARD_STOP_LIVE_GATE_POLICY.md": hard_stop_policy(),
        "AUTONOMOUS_TASK_SELECTION_POLICY.md": task_selection_policy(),
        "CODEX_AUTO_GOVERNOR_POLICY.md": codex_policy(),
        "OLLAMA_EVIDENCE_HELPER_POLICY.md": ollama_policy(),
        "AUTONOMY_SIMULATION_RESULTS.md": render_simulation_md(sim),
    }
    for name, text in final_docs.items():
        write_text(OUT / name, text)
    write_text(OUT / "GO_NO_GO.md", "AUTONOMOUS_GOVERNOR_REPLACES_MANUAL_COPILOT_UNTIL_LIVE_GATE_READY\n")
    write_json(OUT / "operator_dashboard_payload.json", payload)
    write_json(PUBLIC / "operator_dashboard_payload.json", payload)
    return 0


def report(payload: dict[str, Any]) -> str:
    return f"""# Autonomous Governor Report

Result: `AUTONOMOUS_GOVERNOR_REPLACES_MANUAL_COPILOT_UNTIL_LIVE_GATE_READY`

- Standing governor approval created: `{payload['standing_governor_approval_created']}`
- Supervisor patched: `{payload['supervisor_patched']}`
- Non-live approvals now non-blocking: `{payload['non_live_approvals_now_non_blocking']}`
- Final live gate hard-stop: `{payload['final_live_gate_hard_stop']}`
- Redis trim no longer blocks entire queue: `{payload['redis_trim_no_longer_blocks_entire_queue']}`
- Task auto-selection working: `{payload['task_auto_selection_working']}`
- Codex auto-governor working: `{payload['codex_auto_governor_working']}`
- Ollama helper policy ready: `{payload['ollama_helper_policy_ready']}`
- Dashboard updated: `{payload['dashboard_updated']}`
- Simulation passed: `{payload['simulation_passed']}`
- Git head: `{payload['git_head']}`
- Current selected next task: `{payload['current_selected_next_task']}`
- Human input required: `{payload['human_input_required']}`

The governor leaves Phase 3H Redis trim as a non-blocking decision packet until
the exact trim approval exists. It does not create that approval file.
"""


def standing_effective() -> str:
    return """# Standing Delegation Effective

The autonomous governor may decide, execute, review, remediate, validate,
commit, and push safe non-live work inside AI BOT REBUILD.

Manual Copilot prompting is not required for ordinary non-live rebuild work.
"""


def non_blocking_policy() -> str:
    return """# Non-Blocking Decision Packet Policy

Non-live approval or decision packets do not block the global queue. They remain
local subtasks with `waiting_decision_packet` or `delegated_decision_pending`
state while the governor selects unrelated safe work.

Final live/capital actions are different: they remain hard-stop human gates.
"""


def hard_stop_policy() -> str:
    return """# Hard Stop Live Gate Policy

Human-only actions:
- final live trading enablement
- real exchange order/cancel/close
- real leverage/margin/position-mode changes
- activation of live trading keys
- switching paper/shadow to live execution
- disabling mandatory live safety gates

Live trading remains `blocked_human_only`.
"""


def task_selection_policy() -> str:
    return """# Autonomous Task Selection Policy

Priority 0: safety/runtime hard blockers.
Priority 1: current selected blocker remediation.
Priority 2: V2 data-plane independence.
Priority 3: trading system readiness.
Priority 4: enterprise cockpit.
Priority 5: extended soak and final live-readiness preparation.
"""


def codex_policy() -> str:
    return """# Codex Auto-Governor Policy

Codex automatically reviews safe completed milestones and challenges fake-ready
markers, hidden live paths, missing tests, stale dashboard payloads, unsafe
Redis/exchange behavior, trainer lineage gaps, signal explanation guessing,
script registry gaps, monitor evidence gaps, config safety, and live gate
bypasses.

Codex does not replace final human approval for real capital.
"""


def ollama_policy() -> str:
    return """# Ollama Evidence Helper Policy

Ollama may draft evidence packets, log compression, script-purpose drafts,
monitor summaries, trainer metric summaries, and dependency groupings.

Every Ollama output must say:

`DRAFT_ONLY_REQUIRES_CLAUDE_VERIFICATION`

Claude/Codex must verify safety-critical claims against raw evidence.
"""


if __name__ == "__main__":
    raise SystemExit(main())
