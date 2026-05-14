#!/usr/bin/env python3
"""V2 worker-porting orchestrator.

Reads the strict worker-porting sequence, detects per-worker completion by
checking required artifacts on disk, identifies the next action, and writes
state files + dashboard payloads. Does NOT itself execute subprocesses; the
existing ``agent_supervisor.py`` daemon picks up pending task descriptors and
runs them. This orchestrator is the state machine + selector + reporter that
makes the worker porting flow autonomous.

Hard safety rules (audit-enforced):
  - Never creates a final live approval token.
  - Never mutates legacy paths.
  - Never writes old Redis.
  - Never invokes an exchange order / leverage / margin codepath.
  - Refuses to mark any worker complete unless paired Codex GO/NO-GO contains
    the worker's PASS marker.
  - Reports BLOCKED_GIT (and stops dispatch) if `.git` shows the empty-loose-
    object corruption pattern.

CLI:
    python3 claude_worklog/tools/v2_worker_porting_orchestrator.py --once
    python3 claude_worklog/tools/v2_worker_porting_orchestrator.py --daemon --poll-seconds 120
    python3 claude_worklog/tools/v2_worker_porting_orchestrator.py --dry-run
    python3 claude_worklog/tools/v2_worker_porting_orchestrator.py --status
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
V2_FRONTEND_PUBLIC = REPO_ROOT / "v2" / "frontend" / "public"
TASKS_DIR = REPO_ROOT / "claude_worklog" / "agent_supervisor" / "tasks"
WORKERS_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "emergency_v2_runtime_migration"
    / "latest"
    / "workers"
)
STATE_DIR = (
    REPO_ROOT
    / "claude_worklog"
    / "final_readiness"
    / "v2_worker_porting_orchestrator"
    / "latest"
)
PUBLIC_STATE_DIR = V2_FRONTEND_PUBLIC / "v2_worker_porting_orchestrator" / "latest"
APPROVALS_DIR = REPO_ROOT / "claude_worklog" / "approvals"
EVENTS_FILE = REPO_ROOT / "claude_worklog" / "agent_supervisor" / "events.jsonl"

LIVE_GATE_STATUS = "blocked_human_only"

# Strict worker sequence, encoded once. Do NOT reorder without operator approval.
# Updated after legacy_startup_baseline_v2_migration: the legacy startup script
# proves the system begins with ingestors -> feature pipeline / TA -> trainer ->
# orchestrator -> trader. The three new "*_from_legacy_baseline" workers are
# inserted at the FRONT of P0 so the baseline data plane lands before risk
# gateway / paper execution / signal lineage / account monitor.
WORKER_SEQUENCE: List[Dict[str, str]] = [
    # P0 — baseline-anchored data plane (ingestor-first, per legacy startup script)
    {"id": "v2_feature_snapshot_builder", "priority": "P0"},
    {"id": "v2_market_ingestor_from_legacy_baseline", "priority": "P0"},
    {"id": "v2_coinank_and_liquidation_bridge_from_legacy_baseline", "priority": "P0"},
    {"id": "v2_feature_pipeline_and_ta_worker_from_legacy_baseline", "priority": "P0"},
    # P0 — V2-native gates that consume the baseline data plane
    {"id": "v2_risk_gateway_runtime_worker", "priority": "P0"},
    {"id": "v2_paper_execution_worker", "priority": "P0"},
    {"id": "v2_execution_ledger_worker", "priority": "P0"},
    {"id": "v2_signal_lineage_worker", "priority": "P0"},
    {"id": "v2_account_position_monitor", "priority": "P0"},
    # P1
    {"id": "v2_trainer_bridge", "priority": "P1"},
    {"id": "v2_orchestrator_adapter", "priority": "P1"},
    {"id": "v2_signal_publisher", "priority": "P1"},
    {"id": "v2_replay_worker", "priority": "P1"},
    {"id": "v2_script_monitor", "priority": "P1"},
    {"id": "v2_config_admin_manager", "priority": "P1"},
    # P2 fail-closed stubs
    {"id": "v2_p2_default_blocked_execution_adapter_stub", "priority": "P2"},
    {"id": "v2_p2_binance_usdm_adapter_stub", "priority": "P2"},
    {"id": "v2_p2_deployment_helpers", "priority": "P2"},
]

# Worker completion classifications.
QUEUED = "QUEUED"
LEGACY_BASELINE_REQUIRED = "LEGACY_BASELINE_REQUIRED"
CLAUDE_RUNNING = "CLAUDE_RUNNING"
CLAUDE_COMPLETED_AWAITING_CODEX = "CLAUDE_COMPLETED_AWAITING_CODEX"
CODEX_RUNNING = "CODEX_RUNNING"
CODEX_PASS = "CODEX_PASS"
CODEX_PASS_BUT_LEGACY_BACKFILL_REQUIRED = "CODEX_PASS_BUT_LEGACY_BACKFILL_REQUIRED"
CODEX_FAIL_REMEDIATION_REQUIRED = "CODEX_FAIL_REMEDIATION_REQUIRED"
BLOCKED_GIT = "BLOCKED_GIT"
BLOCKED_AUTH_OR_RATE_LIMIT = "BLOCKED_AUTH_OR_RATE_LIMIT"
BLOCKED_SAFETY = "BLOCKED_SAFETY"
BLOCKED_UNKNOWN = "BLOCKED_UNKNOWN"


def iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- artifact-presence helpers --------------------------------------


def cli_path_for(worker_id: str) -> Path:
    return REPO_ROOT / "v2" / "backend" / "app" / "cli" / f"{worker_id}.py"


def test_path_for(worker_id: str) -> Path:
    return (
        REPO_ROOT
        / "v2"
        / "backend"
        / "tests"
        / "integration"
        / "cli"
        / f"test_{worker_id}.py"
    )


def worker_report_path(worker_id: str) -> Path:
    return WORKERS_DIR / f"{worker_id}_report.md"


def worker_status_json_path(worker_id: str) -> Path:
    return WORKERS_DIR / f"{worker_id}_status.json"


def codex_go_no_go_path(worker_id: str) -> Path:
    return WORKERS_DIR / f"codex_{worker_id}_go_no_go.md"


def legacy_baseline_analysis_path(worker_id: str) -> Path:
    return WORKERS_DIR / f"{worker_id}_LEGACY_BASELINE_ANALYSIS.md"


def legacy_behavior_mapping_path(worker_id: str) -> Path:
    return WORKERS_DIR / f"{worker_id}_legacy_behavior_mapping.json"


def public_payload_path(worker_id: str) -> Path:
    return (
        V2_FRONTEND_PUBLIC
        / "operator_runtime"
        / worker_id
        / "latest"
        / f"{worker_id}_status.json"
    )


def task_descriptor_path(worker_id: str) -> Path:
    return TASKS_DIR / f"claude_port_{worker_id}.json"


def codex_review_descriptor_path(worker_id: str) -> Path:
    return TASKS_DIR / f"codex_review_{worker_id}.json"


def remediation_descriptor_path(worker_id: str) -> Path:
    return TASKS_DIR / f"claude_remediate_{worker_id}_codex_fail.json"


def task_state_path(task_id: str) -> Path:
    return REPO_ROOT / "claude_worklog" / "agent_supervisor" / "state" / "tasks" / f"{task_id}.json"


def read_json_file(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def parse_utc_ts(value: Any) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except Exception:
        return None


def task_state_end_ts(task_id: str) -> Optional[dt.datetime]:
    last_run = read_json_file(task_state_path(task_id)).get("last_run")
    if isinstance(last_run, dict):
        return parse_utc_ts(last_run.get("end"))
    return None


def descriptor_required_paths(worker_id: str) -> List[Path]:
    descriptor = read_json_file(task_descriptor_path(worker_id))
    paths: List[Path] = []
    for item in descriptor.get("required_output_files", []):
        raw = str(item).strip()
        if not raw:
            continue
        candidate = Path(raw)
        if candidate.is_absolute() or ".." in candidate.parts:
            continue
        paths.append(REPO_ROOT / candidate)
    return paths


def first_required_path(worker_id: str, predicate: Any, fallback: Path) -> Path:
    for path in descriptor_required_paths(worker_id):
        try:
            rel = str(path.relative_to(REPO_ROOT))
        except Exception:
            rel = str(path)
        if predicate(rel):
            return path
    return fallback


# ---------- completion logic ----------------------------------------------


def expected_codex_pass_token(worker_id: str) -> str:
    """The exact PASS marker string the per-worker Codex go/no-go file must contain."""
    return f"{worker_id.upper()}_CODEX_PASS"


def expected_codex_fail_token(worker_id: str) -> str:
    return f"{worker_id.upper()}_CODEX_FAIL"


def check_worker_completion(worker: Dict[str, str]) -> Dict[str, Any]:
    """Inspect on-disk artifacts and classify the worker's state."""
    worker_id = worker["id"]
    cli = first_required_path(
        worker_id,
        lambda rel: rel.startswith("v2/backend/app/cli/") and rel.endswith(".py"),
        cli_path_for(worker_id),
    )
    tests = first_required_path(
        worker_id,
        lambda rel: rel.startswith("v2/backend/tests/") and Path(rel).name.startswith("test_") and rel.endswith(".py"),
        test_path_for(worker_id),
    )
    report = first_required_path(
        worker_id,
        lambda rel: rel.startswith(str(WORKERS_DIR.relative_to(REPO_ROOT))) and rel.endswith("_report.md"),
        worker_report_path(worker_id),
    )
    status_json = first_required_path(
        worker_id,
        lambda rel: rel.startswith(str(WORKERS_DIR.relative_to(REPO_ROOT))) and rel.endswith("_status.json"),
        worker_status_json_path(worker_id),
    )
    codex_go = codex_go_no_go_path(worker_id)
    payload = first_required_path(
        worker_id,
        lambda rel: rel.startswith("v2/frontend/public/operator_runtime/") and rel.endswith("_status.json"),
        public_payload_path(worker_id),
    )
    task = task_descriptor_path(worker_id)
    codex_task = codex_review_descriptor_path(worker_id)
    legacy_baseline = legacy_baseline_analysis_path(worker_id)
    legacy_mapping = legacy_behavior_mapping_path(worker_id)
    required_outputs = descriptor_required_paths(worker_id)
    missing_required_outputs = [
        str(path.relative_to(REPO_ROOT))
        for path in required_outputs
        if not path.exists()
    ]

    missing: List[str] = []
    if missing_required_outputs:
        missing.extend(missing_required_outputs)
    elif not cli.exists():
        missing.append(str(cli.relative_to(REPO_ROOT)))
    if not tests.exists():
        missing.append(str(tests.relative_to(REPO_ROOT)))
    if not report.exists():
        missing.append(str(report.relative_to(REPO_ROOT)))
    if not status_json.exists():
        missing.append(str(status_json.relative_to(REPO_ROOT)))
    if not legacy_baseline.exists():
        missing.append(str(legacy_baseline.relative_to(REPO_ROOT)))
    if not legacy_mapping.exists():
        missing.append(str(legacy_mapping.relative_to(REPO_ROOT)))

    state: str
    codex_text: Optional[str] = None
    if codex_go.exists():
        try:
            codex_text = codex_go.read_text()
        except Exception as exc:
            codex_text = f"<unreadable: {exc}>"

    safety_violation: Optional[str] = None
    if status_json.exists():
        try:
            sj = json.loads(status_json.read_text())
            gate = sj.get("live_gate") or sj.get("current_gate_state")
            if gate and gate != LIVE_GATE_STATUS:
                safety_violation = f"worker status reports live_gate={gate!r} (must be {LIVE_GATE_STATUS!r})"
        except Exception:
            pass

    # Legacy-baseline enforcement: a worker is not allowed to leave QUEUED
    # until its LEGACY_BASELINE_ANALYSIS.md and legacy_behavior_mapping.json
    # exist. The grandfather rule: if Codex already PASSed and the legacy
    # files are missing, the worker is classified
    # CODEX_PASS_BUT_LEGACY_BACKFILL_REQUIRED — it remains in the completed
    # list but a backfill task is required.
    legacy_baseline_present = legacy_baseline.exists() and legacy_mapping.exists()

    codex_state = read_json_file(task_state_path(f"codex_review_{worker_id}")).get("status")
    claude_state = read_json_file(task_state_path(f"claude_port_{worker_id}")).get("status")
    remediation_task_id = f"claude_remediate_{worker_id}_codex_fail"
    remediation_state = read_json_file(task_state_path(remediation_task_id)).get("status")
    remediation_finished_at = task_state_end_ts(remediation_task_id)
    codex_finished_at = task_state_end_ts(f"codex_review_{worker_id}")
    remediation_newer_than_codex = (
        remediation_state == "completed"
        and remediation_finished_at is not None
        and (codex_finished_at is None or remediation_finished_at > codex_finished_at)
    )

    pass_token = expected_codex_pass_token(worker_id)
    fail_token = expected_codex_fail_token(worker_id)

    if safety_violation:
        state = BLOCKED_SAFETY
    elif codex_text and pass_token in codex_text:
        if legacy_baseline_present:
            state = CODEX_PASS
        else:
            state = CODEX_PASS_BUT_LEGACY_BACKFILL_REQUIRED
    elif codex_text and fail_token in codex_text and remediation_newer_than_codex:
        state = CLAUDE_COMPLETED_AWAITING_CODEX
    elif codex_text and fail_token in codex_text:
        state = CODEX_FAIL_REMEDIATION_REQUIRED
    elif not cli.exists() and not legacy_baseline_present:
        state = LEGACY_BASELINE_REQUIRED
    elif missing_required_outputs and claude_state in {"running"}:
        state = CLAUDE_RUNNING
    elif missing_required_outputs and claude_state in {"pending", "retry_scheduled", "blocked_dependency", None, ""}:
        state = QUEUED
    elif not legacy_baseline_present and not codex_go.exists():
        state = LEGACY_BASELINE_REQUIRED
    elif not tests.exists() or not report.exists() or not status_json.exists():
        state = CLAUDE_RUNNING
    elif not codex_go.exists() and codex_state == "running":
        state = CODEX_RUNNING
    elif not codex_go.exists():
        state = CLAUDE_COMPLETED_AWAITING_CODEX
    else:
        state = BLOCKED_UNKNOWN

    return {
        "worker_id": worker_id,
        "priority": worker["priority"],
        "state": state,
        "cli_present": cli.exists(),
        "tests_present": tests.exists(),
        "report_present": report.exists(),
        "status_json_present": status_json.exists(),
        "codex_go_no_go_present": codex_go.exists(),
        "codex_review_descriptor_present": codex_task.exists(),
        "task_descriptor_present": task.exists(),
        "public_payload_present": payload.exists(),
        "legacy_baseline_analysis_present": legacy_baseline.exists(),
        "legacy_behavior_mapping_present": legacy_mapping.exists(),
        "missing_artifacts": missing,
        "safety_violation": safety_violation,
    }


# ---------- selector + state writer ----------------------------------------


def is_final_approval_token_present() -> bool:
    candidates = [
        APPROVALS_DIR / "APPROVED_FINAL_LIVE_TINY_CANARY_ONLY.md",
        APPROVALS_DIR / "APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md",
    ]
    return any(p.exists() for p in candidates)


def detect_git_corruption() -> Tuple[bool, str]:
    """Return (corrupted, evidence). Empty loose object files are the signature."""
    git_objects = REPO_ROOT / ".git" / "objects"
    if not git_objects.is_dir():
        return False, "no .git/objects dir"
    try:
        # Quick scan: any empty (zero-byte) loose object means corruption.
        # Only check top two hex levels; avoid full traversal.
        for entry in git_objects.iterdir():
            if not entry.is_dir() or len(entry.name) != 2:
                continue
            for f in entry.iterdir():
                if f.is_file() and f.stat().st_size == 0:
                    return True, f"empty loose object: {f.relative_to(REPO_ROOT)}"
    except Exception as exc:
        return False, f"scan failed: {exc}"
    return False, "no empty loose objects"


def classify_dirty_git(limit: int = 40) -> Dict[str, Any]:
    """Return classification of `git status --short` entries."""
    try:
        out = subprocess.run(
            ["git", "status", "--short"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except Exception as exc:
        return {"available": False, "error": str(exc)}
    lines = [line for line in out.stdout.splitlines() if line.strip()]
    classified = {
        "active_daemon_owned": [],
        "active_task_owned": [],
        "durable_artifact_to_commit": [],
        "runtime_churn_to_ignore": [],
        "unsafe_unknown": [],
    }
    for line in lines:
        # Format: ` M path` or `?? path`
        path = line[3:].strip() if len(line) >= 3 else line
        if "operator_runtime/paper_online" in path or "operator_runtime/paper_shadow_observation" in path:
            classified["active_daemon_owned"].append(path)
        elif path.startswith("claude_worklog/agent_supervisor/state") or path.startswith("claude_worklog/agent_supervisor/runs"):
            classified["active_daemon_owned"].append(path)
        elif path.startswith("v2/runtime/"):
            classified["runtime_churn_to_ignore"].append(path)
        elif path.startswith("v2/frontend/public/operator_runtime/"):
            classified["runtime_churn_to_ignore"].append(path)
        elif "/latest/" in path and "operator_dashboard_payload.json" in path:
            classified["active_daemon_owned"].append(path)
        elif path.startswith("claude_worklog/final_readiness/"):
            classified["active_task_owned"].append(path)
        elif path.startswith("v2/backend/app/cli/"):
            classified["durable_artifact_to_commit"].append(path)
        elif path.startswith("v2/backend/tests/"):
            classified["durable_artifact_to_commit"].append(path)
        elif path.startswith("v2/backend/app/services/"):
            classified["durable_artifact_to_commit"].append(path)
        else:
            classified["unsafe_unknown"].append(path)
    return {
        "available": True,
        "total_dirty": len(lines),
        "buckets": {k: len(v) for k, v in classified.items()},
        "preview_unsafe_unknown": classified["unsafe_unknown"][:limit],
    }


def evaluate_all_workers() -> List[Dict[str, Any]]:
    return [check_worker_completion(w) for w in WORKER_SEQUENCE]


def select_next_action(reports: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Walk the sequence; first worker not yet CODEX_PASS dictates the action."""
    if is_final_approval_token_present():
        return {
            "kind": "blocked_safety",
            "reason": "final_live_approval_token_present",
            "next_worker": None,
            "follow_up": "operator_review_required_before_orchestrator_acts",
        }
    corrupted, evidence = detect_git_corruption()
    if corrupted:
        return {
            "kind": "blocked_git",
            "reason": evidence,
            "next_worker": None,
            "follow_up": "do_not_repair_destructively_without_operator_approval",
        }
    backfill_required: List[str] = []
    for rpt in reports:
        state = rpt["state"]
        if state == CODEX_PASS:
            continue
        if state == CODEX_PASS_BUT_LEGACY_BACKFILL_REQUIRED:
            # Workers in this state are NOT blocking; they pass Codex. But a
            # backfill task must exist for them. Record and continue past.
            backfill_required.append(rpt["worker_id"])
            continue
        if state == LEGACY_BASELINE_REQUIRED:
            return {
                "kind": "dispatch_legacy_baseline_analysis",
                "next_worker": rpt["worker_id"],
                "required_files": [
                    str(legacy_baseline_analysis_path(rpt["worker_id"]).relative_to(REPO_ROOT)),
                    str(legacy_behavior_mapping_path(rpt["worker_id"]).relative_to(REPO_ROOT)),
                ],
                "task_descriptor": str(task_descriptor_path(rpt["worker_id"]).relative_to(REPO_ROOT)),
                "follow_up": "claude_must_read_legacy_reference_and_emit_baseline_analysis_before_implementation",
                "backfill_required_workers": backfill_required,
            }
        if state == QUEUED:
            return {
                "kind": "dispatch_claude",
                "next_worker": rpt["worker_id"],
                "task_descriptor": str(task_descriptor_path(rpt["worker_id"]).relative_to(REPO_ROOT)),
                "follow_up": f"after_claude_artifacts_appear_dispatch_codex_review_{rpt['worker_id']}",
                "backfill_required_workers": backfill_required,
            }
        if state == CLAUDE_RUNNING:
            return {
                "kind": "wait_for_claude",
                "next_worker": rpt["worker_id"],
                "missing_artifacts": rpt["missing_artifacts"],
                "follow_up": "no_dispatch_until_claude_emits_all_required_files",
            }
        if state == CLAUDE_COMPLETED_AWAITING_CODEX:
            return {
                "kind": "dispatch_codex_review",
                "next_worker": rpt["worker_id"],
                "codex_descriptor": str(codex_review_descriptor_path(rpt["worker_id"]).relative_to(REPO_ROOT)),
                "follow_up": "wait_for_codex_go_no_go_file",
            }
        if state == CODEX_RUNNING:
            return {
                "kind": "wait_for_codex",
                "next_worker": rpt["worker_id"],
                "follow_up": "no_advancement_until_codex_pass_token_written",
            }
        if state == CODEX_FAIL_REMEDIATION_REQUIRED:
            return {
                "kind": "dispatch_remediation",
                "next_worker": rpt["worker_id"],
                "remediation_task_id": f"claude_remediate_{rpt['worker_id']}_codex_fail",
                "follow_up": "rerun_codex_review_after_remediation",
            }
        if state in (BLOCKED_SAFETY, BLOCKED_AUTH_OR_RATE_LIMIT, BLOCKED_UNKNOWN):
            return {
                "kind": state.lower(),
                "next_worker": rpt["worker_id"],
                "reason": rpt.get("safety_violation") or "see worker status payload",
                "follow_up": "operator_review_required",
            }
    return {
        "kind": "all_workers_complete",
        "next_worker": None,
        "follow_up": "proceed_to_v2_local_online_bootstrap_paper_shadow_only",
    }


def aggregate_state(reports: List[Dict[str, Any]], next_action: Dict[str, Any]) -> Dict[str, Any]:
    # Both CODEX_PASS and CODEX_PASS_BUT_LEGACY_BACKFILL_REQUIRED count as
    # "passed Codex" for advancement. The backfill list is surfaced separately.
    passing = {CODEX_PASS, CODEX_PASS_BUT_LEGACY_BACKFILL_REQUIRED}
    completed = [r["worker_id"] for r in reports if r["state"] in passing]
    legacy_backfill_required = [
        r["worker_id"] for r in reports if r["state"] == CODEX_PASS_BUT_LEGACY_BACKFILL_REQUIRED
    ]
    queued = [r["worker_id"] for r in reports if r["state"] == QUEUED]
    legacy_baseline_required = [
        r["worker_id"] for r in reports if r["state"] == LEGACY_BASELINE_REQUIRED
    ]
    in_flight = [
        r["worker_id"]
        for r in reports
        if r["state"] in (CLAUDE_RUNNING, CLAUDE_COMPLETED_AWAITING_CODEX, CODEX_RUNNING)
    ]
    failing = [r["worker_id"] for r in reports if r["state"] == CODEX_FAIL_REMEDIATION_REQUIRED]
    blocked = [
        r["worker_id"]
        for r in reports
        if r["state"] in (BLOCKED_GIT, BLOCKED_SAFETY, BLOCKED_AUTH_OR_RATE_LIMIT, BLOCKED_UNKNOWN)
    ]
    last_completed = completed[-1] if completed else None
    p0_total = sum(1 for w in WORKER_SEQUENCE if w["priority"] == "P0")
    p0_complete = sum(1 for r in reports if r["state"] in passing and r["priority"] == "P0")
    p1_total = sum(1 for w in WORKER_SEQUENCE if w["priority"] == "P1")
    p1_complete = sum(1 for r in reports if r["state"] in passing and r["priority"] == "P1")
    p2_total = sum(1 for w in WORKER_SEQUENCE if w["priority"] == "P2")
    p2_complete = sum(1 for r in reports if r["state"] in passing and r["priority"] == "P2")
    if p0_complete == p0_total:
        v2_local_online = "V2_LOCAL_ONLINE_P0_READY_PAPER_SHADOW_ONLY"
    else:
        v2_local_online = "V2_LOCAL_ONLINE_DEGRADED_P0_INCOMPLETE"
    return {
        "as_of_utc": iso_now(),
        "live_gate": LIVE_GATE_STATUS,
        "final_approval_token": "present" if is_final_approval_token_present() else "absent",
        "redis_trim_approval": "present"
        if (APPROVALS_DIR / "APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md").exists()
        else "absent",
        "worker_sequence": [w["id"] for w in WORKER_SEQUENCE],
        "workers": reports,
        "completed_workers": completed,
        "queued_workers": queued,
        "legacy_baseline_required_workers": legacy_baseline_required,
        "legacy_backfill_required_workers": legacy_backfill_required,
        "in_flight_workers": in_flight,
        "remediation_required_workers": failing,
        "blocked_workers": blocked,
        "last_completed_worker": last_completed,
        "next_worker": next_action.get("next_worker"),
        "next_action": next_action,
        "v2_local_online_state": v2_local_online,
        "progress_p0": {"complete": p0_complete, "total": p0_total},
        "progress_p1": {"complete": p1_complete, "total": p1_total},
        "progress_p2": {"complete": p2_complete, "total": p2_total},
        "git_classification": classify_dirty_git(),
        "git_corruption_detected": detect_git_corruption()[0],
        "primary_objective_lock": [
            "v2_independent_paper_shadow_runtime",
            "live_blocked_human_only",
            "no_legacy_mutation",
            "no_old_redis_writes",
            "no_exchange_actions",
        ],
        "supersedes": "manual_worker_by_worker_prompting",
    }


def render_status_markdown(state: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# V2 worker porting status")
    lines.append("")
    lines.append(f"As of: {state['as_of_utc']}")
    lines.append("")
    lines.append(f"Live gate: `{state['live_gate']}`")
    lines.append(f"Final approval token: `{state['final_approval_token']}`")
    lines.append(f"V2 local online state: `{state['v2_local_online_state']}`")
    lines.append("")
    p0 = state["progress_p0"]
    p1 = state["progress_p1"]
    p2 = state["progress_p2"]
    lines.append(f"P0 progress: {p0['complete']} / {p0['total']}")
    lines.append(f"P1 progress: {p1['complete']} / {p1['total']}")
    lines.append(f"P2 progress: {p2['complete']} / {p2['total']}")
    lines.append("")
    lines.append("## Next action")
    lines.append("")
    na = state["next_action"]
    lines.append(f"- kind: `{na.get('kind')}`")
    if na.get("next_worker"):
        lines.append(f"- next_worker: `{na['next_worker']}`")
    if na.get("reason"):
        lines.append(f"- reason: {na['reason']}")
    if na.get("follow_up"):
        lines.append(f"- follow_up: {na['follow_up']}")
    lines.append("")
    lines.append("## Worker states")
    lines.append("")
    lines.append("| priority | worker | state | cli | tests | report | status | codex |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for w in state["workers"]:
        lines.append(
            f"| {w['priority']} | `{w['worker_id']}` | **{w['state']}** | "
            f"{'✓' if w['cli_present'] else '·'} | "
            f"{'✓' if w['tests_present'] else '·'} | "
            f"{'✓' if w['report_present'] else '·'} | "
            f"{'✓' if w['status_json_present'] else '·'} | "
            f"{'✓' if w['codex_go_no_go_present'] else '·'} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def render_dashboard_payload(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "task_id": "v2_worker_porting_orchestrator",
        "as_of_utc": state["as_of_utc"],
        "source_paths": [
            "claude_worklog/final_readiness/v2_worker_porting_orchestrator/latest/worker_porting_state.json",
            "claude_worklog/tools/v2_worker_porting_orchestrator.py",
        ],
        "go_no_go": "V2_AUTONOMOUS_WORKER_PORTING_ORCHESTRATOR_READY",
        "live_gate": state["live_gate"],
        "final_approval_token": state["final_approval_token"],
        "redis_trim_approval": state["redis_trim_approval"],
        "current_worker": state["next_worker"],
        "current_claude_task": (
            f"claude_port_{state['next_worker']}"
            if state["next_worker"] and state["next_action"]["kind"] == "dispatch_claude"
            else None
        ),
        "current_codex_task": (
            f"codex_review_{state['next_worker']}"
            if state["next_worker"] and state["next_action"]["kind"] in {"dispatch_codex_review", "wait_for_codex"}
            else None
        ),
        "last_completed_worker": state["last_completed_worker"],
        "completed_workers": state["completed_workers"],
        "queued_workers": state["queued_workers"],
        "legacy_baseline_required_workers": state["legacy_baseline_required_workers"],
        "legacy_backfill_required_workers": state["legacy_backfill_required_workers"],
        "in_flight_workers": state["in_flight_workers"],
        "remediation_required_workers": state["remediation_required_workers"],
        "blocked_workers": state["blocked_workers"],
        "progress_p0": state["progress_p0"],
        "progress_p1": state["progress_p1"],
        "progress_p2": state["progress_p2"],
        "v2_local_online_state": state["v2_local_online_state"],
        "git_classification": state["git_classification"],
        "git_corruption_detected": state["git_corruption_detected"],
        "next_action": state["next_action"],
        "primary_objective_lock": state["primary_objective_lock"],
        "supersedes": state["supersedes"],
    }


def write_state(state: Dict[str, Any], dashboard: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PUBLIC_STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "worker_porting_state.json").write_text(
        json.dumps(state, indent=2, sort_keys=True, default=str)
    )
    (STATE_DIR / "WORKER_PORTING_STATUS.md").write_text(render_status_markdown(state))
    (STATE_DIR / "operator_dashboard_payload.json").write_text(
        json.dumps(dashboard, indent=2, sort_keys=True, default=str)
    )
    (PUBLIC_STATE_DIR / "operator_dashboard_payload.json").write_text(
        json.dumps(dashboard, indent=2, sort_keys=True, default=str)
    )


def emit_event(event: Dict[str, Any]) -> None:
    try:
        EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"ts": iso_now(), **event}, default=str)
        with EVENTS_FILE.open("a") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


# ---------- orchestrator-managed task selection ----------------------------


def select_task_descriptor(action: Dict[str, Any], dry_run: bool) -> Optional[str]:
    """Mark the next Claude task descriptor as pending-and-selected.

    The existing agent_supervisor.py picks up tasks whose status is 'pending'.
    We do NOT mutate completed task descriptors. We only ensure the next
    in-sequence task's status is 'pending' (it already is by default in this
    repo's queued descriptors). We also write a thin selector pointer file so
    operators and external watchers can see which task is next.
    """
    kind = action.get("kind")
    if kind not in {
        "dispatch_legacy_baseline_analysis",
        "dispatch_claude",
        "dispatch_codex_review",
        "dispatch_remediation",
    }:
        return None
    worker_id = action.get("next_worker")
    if not worker_id:
        return None
    if kind in {"dispatch_legacy_baseline_analysis", "dispatch_claude"}:
        target = task_descriptor_path(worker_id)
    elif kind == "dispatch_codex_review":
        target = codex_review_descriptor_path(worker_id)
    else:
        target = remediation_descriptor_path(worker_id)
    if dry_run:
        return f"dry_run_would_select:{target.relative_to(REPO_ROOT)}"
    if not target.exists():
        return f"missing_descriptor:{target.relative_to(REPO_ROOT)}"
    try:
        descriptor = json.loads(target.read_text())
        if descriptor.get("status") not in {"pending", None}:
            return f"descriptor_status_unchanged:{descriptor.get('status')}"
    except Exception as exc:
        return f"descriptor_read_failed:{exc}"
    # Write a thin selector pointer (non-destructive) so external watchers see
    # the choice without mutating the descriptor itself.
    selector = STATE_DIR / "next_selected_task.json"
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    selector.write_text(
        json.dumps(
            {
                "selected_at_utc": iso_now(),
                "selected_by": "v2_worker_porting_orchestrator",
                "task_descriptor": str(target.relative_to(REPO_ROOT)),
                "worker_id": worker_id,
                "action_kind": kind,
            },
            indent=2,
            sort_keys=True,
        )
    )
    if kind == "dispatch_codex_review":
        task_id = f"codex_review_{worker_id}"
        state_path = task_state_path(task_id)
        existing = read_json_file(state_path)
        existing.update(
            {
                "task_id": task_id,
                "status": "pending",
                "run_pid": None,
                "resume_after_utc": None,
                "last_retry_reason": "rerun_after_remediation",
            }
        )
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n")
    return f"selected:{target.relative_to(REPO_ROOT)}"


# ---------- main loop ------------------------------------------------------


def run_once(dry_run: bool = False, verbose: bool = False) -> Dict[str, Any]:
    reports = evaluate_all_workers()
    action = select_next_action(reports)
    state = aggregate_state(reports, action)
    dashboard = render_dashboard_payload(state)
    selection_outcome: Optional[str] = None
    if not dry_run:
        write_state(state, dashboard)
        selection_outcome = select_task_descriptor(action, dry_run=False)
        emit_event(
            {
                "event": "v2_worker_porting_orchestrator_tick",
                "next_action_kind": action.get("kind"),
                "next_worker": action.get("next_worker"),
                "selection_outcome": selection_outcome,
                "p0_progress": state["progress_p0"],
            }
        )
    else:
        selection_outcome = select_task_descriptor(action, dry_run=True)
    state["selection_outcome"] = selection_outcome
    if verbose:
        print(json.dumps({k: v for k, v in state.items() if k != "workers"}, indent=2, default=str))
    return state


def run_daemon(poll_seconds: int) -> None:
    try:
        while True:
            try:
                run_once()
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                emit_event(
                    {
                        "event": "v2_worker_porting_orchestrator_iteration_failed",
                        "error": str(exc),
                    }
                )
            time.sleep(max(5, poll_seconds))
    except KeyboardInterrupt:
        return


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="v2_worker_porting_orchestrator")
    parser.add_argument("--once", action="store_true", help="run one iteration and exit")
    parser.add_argument("--daemon", action="store_true", help="run continuously")
    parser.add_argument("--poll-seconds", type=int, default=120, help="daemon poll interval")
    parser.add_argument("--dry-run", action="store_true", help="compute state but do not write any files")
    parser.add_argument("--status", action="store_true", help="print verbose status JSON and exit")
    args = parser.parse_args(argv)
    if not (args.once or args.daemon or args.dry_run or args.status):
        args.once = True
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    if args.daemon:
        run_daemon(args.poll_seconds)
        return 0
    state = run_once(dry_run=args.dry_run, verbose=args.status)
    if state["final_approval_token"] == "present":
        return 3  # safety blocker
    if state["git_corruption_detected"]:
        return 4  # git blocker
    if state["next_action"]["kind"] == "all_workers_complete":
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
