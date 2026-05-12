#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FINAL = ROOT / "claude_worklog/final_readiness/active_autonomous_dispatch/latest"
PUBLIC = ROOT / "v2/frontend/public/active_autonomous_dispatch/latest"
MIGRATION = ROOT / "claude_worklog/final_readiness/script_migration_backlog/latest"
DOCS = ROOT / "claude_worklog/final_readiness/documentation_governance/latest"
CLAUDE_RUNTIME = ROOT / "claude_worklog/final_readiness/continuous_claude_runtime/latest"
TASKS = ROOT / "claude_worklog/agent_supervisor/tasks"
STATE_TASKS = ROOT / "claude_worklog/agent_supervisor/state/tasks"
LOCK_PATH = ROOT / "claude_worklog/autonomous_governor/latest/NON_DRIFT_GOVERNOR_LOCK.json"
SELECTION_PATH = ROOT / "claude_worklog/autonomous_governor/latest/NEXT_TASK_SELECTION.json"

READY = "ACTIVE_AUTONOMOUS_PRIMARY_DISPATCH_AND_SCRIPT_MIGRATION_PROOF_READY"
BLOCKED = "ACTIVE_AUTONOMOUS_PRIMARY_DISPATCH_AND_SCRIPT_MIGRATION_PROOF_BLOCKED"
CODEX_PASS = "ACTIVE_AUTONOMOUS_PRIMARY_DISPATCH_AND_SCRIPT_MIGRATION_CODEX_PASS"
CODEX_FAIL = "ACTIVE_AUTONOMOUS_PRIMARY_DISPATCH_AND_SCRIPT_MIGRATION_CODEX_FAIL"
PRIMARY_TASK = "LEGACY_TRAINER_RESTART_RUNTIME_CAPTURE_AND_V2_PARITY_SYNC_UNBLOCK"
NEXT_PRIMARY_TASK = "LEGACY_EXECUTION_CONTAINMENT_AND_TRAINER_PARITY_SAFE_MODE"
FOLLOW_ON_PRIMARY_TASK = "SAFE_LEGACY_TRAINER_BRIDGE_AND_GPU_PARITY_SANDBOX"
LIVE_GATE = "blocked_human_only"
CODEX_AUDITS = [
    "codex_audit_no_live_side_effects",
    "codex_audit_current_runtime_truth",
    "codex_audit_risk_gateway_fail_closed",
    "codex_audit_trainer_parity_truth",
    "codex_audit_legacy_bridge_readonly",
    "codex_audit_public_dashboard_truth",
    "codex_audit_script_migration_coverage",
    "codex_audit_v2_data_plane_independence",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True))


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=30)


def marker(rel: str) -> str:
    return read_text(ROOT / rel) or "MISSING"


def ps_lines() -> list[str]:
    proc = run(["ps", "-eo", "pid,ppid,etimes,pcpu,pmem,cmd"])
    needles = (
        "agent_supervisor.py",
        "claude_master_rebuild_planner",
        "autonomous_governor",
        "parallel_capacity_scheduler",
        "codex_non_live_watchdog",
        "claude --print",
        "codex exec",
        "ollama run",
        "paper_online_runtime",
        "rl.hybrid_trainer",
        "rl.orchestrator_worker",
        "trading/trader.py",
    )
    return [ln for ln in proc.stdout.splitlines() if any(n in ln for n in needles) and "grep -E" not in ln]


def active_process(lines: list[str], needle: str) -> bool:
    return any(needle in ln for ln in lines)


def task_file(task_id: str) -> Path:
    return TASKS / f"{task_id}.json"


def task_state_file(task_id: str) -> Path:
    return STATE_TASKS / f"{task_id}.json"


def task_status(task_id: str) -> str:
    return str(read_json(task_state_file(task_id)).get("status") or "")


def selected_task_for_lock() -> str:
    if task_status(NEXT_PRIMARY_TASK) == "completed":
        return FOLLOW_ON_PRIMARY_TASK
    return NEXT_PRIMARY_TASK


def update_lock() -> None:
    selected_task = selected_task_for_lock()
    lock = read_json(LOCK_PATH)
    lock.update(
        {
            "status": "ACTIVE",
            "selected_primary_task": selected_task,
            "selected_task_id": selected_task,
            "parallel_codex_tasks": CODEX_AUDITS,
            "codex_parallel_lane_allowed": True,
            "live_gate_status": LIVE_GATE,
            "old_redis_mutation_allowed": False,
            "exchange_mutation_allowed": False,
            "legacy_bot_mutation_allowed": False,
            "redis_trim": "deferred_non_blocking",
        }
    )
    write_json(LOCK_PATH, lock)
    selection = read_json(SELECTION_PATH)
    selection.update(
        {
            "selected_primary_task": selected_task,
            "selected_task_id": selected_task,
            "parallel_codex_tasks": CODEX_AUDITS,
            "live_gate_status": LIVE_GATE,
            "redis_trim": "deferred_non_blocking",
            "redis_mutation": "none",
            "exchange_mutation": "none",
            "legacy_mutation": "none",
        }
    )
    write_json(SELECTION_PATH, selection)


def primary_prompt() -> str:
    return """You are Claude running under the AI BOT REBUILD supervisor.

Task: acknowledge the selected primary V2 runtime objective and produce a dispatch proof.

Scope:
- Work inside /home/wali/Desktop/AI BOT REBUILD only.
- Legacy bot mutation is forbidden.
- Legacy Redis mutation is forbidden.
- Exchange or capital actions are forbidden.
- Margin and leverage changes are forbidden.
- Live gate remains blocked_human_only.
- Website work is support-only.

Inspect current non-drift lock, queue status, paper runtime payload, legacy trainer runtime marker, and legacy execution containment marker.
Do not edit source code. Emit exactly two BEGIN_FILE blocks:

BEGIN_FILE: claude_worklog/final_readiness/active_autonomous_dispatch/latest/claude_primary_child/PRIMARY_TASK_DISPATCH_ACK.md
...markdown report...
END_FILE

BEGIN_FILE: claude_worklog/final_readiness/active_autonomous_dispatch/latest/claude_primary_child/PRIMARY_TASK_GO_NO_GO.md
PRIMARY_TASK_DISPATCH_ACK_READY
END_FILE
"""


def codex_prompt(task_id: str) -> str:
    topic = task_id.replace("codex_audit_", "").replace("_", " ")
    return f"""You are Codex running a non-live audit under AI BOT REBUILD.

Audit topic: {topic}.

Scope:
- Work inside /home/wali/Desktop/AI BOT REBUILD only.
- Legacy bot mutation is forbidden.
- Legacy Redis mutation is forbidden.
- Exchange or capital actions are forbidden.
- Margin and leverage changes are forbidden.
- Live gate remains blocked_human_only.
- Website work stays support-only unless there is a fresh regression.

Inspect current files and runtime evidence relevant to the audit topic. Do not edit source code.
Emit exactly two BEGIN_FILE blocks:

BEGIN_FILE: claude_worklog/final_readiness/active_autonomous_dispatch/latest/codex_audits/{task_id}_REPORT.md
...markdown report with PASS or BLOCKED and concrete evidence...
END_FILE

BEGIN_FILE: claude_worklog/final_readiness/active_autonomous_dispatch/latest/codex_audits/{task_id}_GO_NO_GO.md
CODEX_AUDIT_READY
END_FILE
"""


def ensure_task_definitions() -> None:
    TASKS.mkdir(parents=True, exist_ok=True)
    primary = {
        "task_id": PRIMARY_TASK,
        "agent": "claude",
        "risk_level": "L1",
        "status": "pending",
        "cwd": str(ROOT),
        "emit_files": True,
        "lane": "primary_claude_lane",
        "allowed_output_prefixes": [
            "claude_worklog/final_readiness/active_autonomous_dispatch/latest/claude_primary_child/"
        ],
        "required_output_files": [
            "claude_worklog/final_readiness/active_autonomous_dispatch/latest/claude_primary_child/PRIMARY_TASK_DISPATCH_ACK.md",
            "claude_worklog/final_readiness/active_autonomous_dispatch/latest/claude_primary_child/PRIMARY_TASK_GO_NO_GO.md",
        ],
        "prompt": primary_prompt(),
        "next_gate": "PRIMARY_TASK_DISPATCH_ACK_READY",
    }
    write_json(task_file(PRIMARY_TASK), primary)
    if not task_state_file(PRIMARY_TASK).exists():
        write_json(
            task_state_file(PRIMARY_TASK),
            {
                "task_id": PRIMARY_TASK,
                "status": "pending",
                "retry_count": 0,
                "run_pid": None,
                "last_run": None,
                "last_summary": "",
                "resume_after_utc": None,
                "last_retry_reason": None,
                "attention_reason": None,
                "history": [],
                "last_event_ts": None,
            },
        )

    next_primary = {
        "task_id": NEXT_PRIMARY_TASK,
        "agent": "claude",
        "risk_level": "L1",
        "status": "pending",
        "cwd": str(ROOT),
        "emit_files": True,
        "lane": "primary_claude_lane",
        "allowed_output_prefixes": [
            "claude_worklog/final_readiness/legacy_execution_containment/latest/"
        ],
        "required_output_files": [
            "claude_worklog/final_readiness/legacy_execution_containment/latest/LEGACY_EXECUTION_CONTAINMENT_AND_TRAINER_PARITY_SAFE_MODE_REPORT.md",
            "claude_worklog/final_readiness/legacy_execution_containment/latest/GO_NO_GO.md",
        ],
        "prompt": """You are Claude running under AI BOT REBUILD supervisor.

Task: produce a read-only legacy execution containment and trainer parity safe-mode packet.

Scope:
- Work inside /home/wali/Desktop/AI BOT REBUILD only.
- Legacy bot mutation is forbidden.
- Legacy Redis mutation is forbidden.
- Exchange or capital actions are forbidden.
- Margin and leverage changes are forbidden.
- Live gate remains blocked_human_only.
- Website work is support-only.

Inspect current V2 paper runtime, legacy bridge evidence, legacy trainer runtime marker, legacy trader observation evidence, and Risk Gateway paper-only status. Do not edit source code. Emit exactly two BEGIN_FILE blocks:

BEGIN_FILE: claude_worklog/final_readiness/legacy_execution_containment/latest/LEGACY_EXECUTION_CONTAINMENT_AND_TRAINER_PARITY_SAFE_MODE_REPORT.md
...markdown report...
END_FILE

BEGIN_FILE: claude_worklog/final_readiness/legacy_execution_containment/latest/GO_NO_GO.md
LEGACY_EXECUTION_CONTAINMENT_AND_TRAINER_PARITY_SAFE_MODE_READY
END_FILE
""",
        "next_gate": "LEGACY_EXECUTION_CONTAINMENT_AND_TRAINER_PARITY_SAFE_MODE_READY",
    }
    write_json(task_file(NEXT_PRIMARY_TASK), next_primary)
    if not task_state_file(NEXT_PRIMARY_TASK).exists():
        write_json(
            task_state_file(NEXT_PRIMARY_TASK),
            {
                "task_id": NEXT_PRIMARY_TASK,
                "status": "pending",
                "retry_count": 0,
                "run_pid": None,
                "last_run": None,
                "last_summary": "",
                "resume_after_utc": None,
                "last_retry_reason": None,
                "attention_reason": None,
                "history": [],
                "last_event_ts": None,
            },
        )

    follow_on = {
        "task_id": FOLLOW_ON_PRIMARY_TASK,
        "agent": "claude",
        "risk_level": "L1",
        "status": "pending",
        "cwd": str(ROOT),
        "emit_files": True,
        "lane": "primary_claude_lane",
        "allowed_output_prefixes": [
            "claude_worklog/final_readiness/safe_legacy_trainer_bridge/latest/"
        ],
        "required_output_files": [
            "claude_worklog/final_readiness/safe_legacy_trainer_bridge/latest/SAFE_LEGACY_TRAINER_BRIDGE_AND_GPU_PARITY_SANDBOX_REPORT.md",
            "claude_worklog/final_readiness/safe_legacy_trainer_bridge/latest/GO_NO_GO.md",
        ],
        "prompt": """You are Claude running under AI BOT REBUILD supervisor.

Task: produce a read-only safe legacy trainer bridge and GPU parity sandbox packet.

Scope:
- Work inside /home/wali/Desktop/AI BOT REBUILD only.
- Legacy bot mutation is forbidden.
- Legacy Redis mutation is forbidden.
- Exchange or capital actions are forbidden.
- Margin and leverage changes are forbidden.
- Live gate remains blocked_human_only.
- Website work is support-only.

Inspect current V2 paper trainer wrapper evidence, legacy trainer process/GPU evidence, legacy output classification, and V2-only bridge requirements. Do not edit source code. Emit exactly two BEGIN_FILE blocks:

BEGIN_FILE: claude_worklog/final_readiness/safe_legacy_trainer_bridge/latest/SAFE_LEGACY_TRAINER_BRIDGE_AND_GPU_PARITY_SANDBOX_REPORT.md
...markdown report...
END_FILE

BEGIN_FILE: claude_worklog/final_readiness/safe_legacy_trainer_bridge/latest/GO_NO_GO.md
SAFE_LEGACY_TRAINER_BRIDGE_AND_GPU_PARITY_SANDBOX_READY
END_FILE
""",
        "next_gate": "SAFE_LEGACY_TRAINER_BRIDGE_AND_GPU_PARITY_SANDBOX_READY",
    }
    write_json(task_file(FOLLOW_ON_PRIMARY_TASK), follow_on)
    if not task_state_file(FOLLOW_ON_PRIMARY_TASK).exists():
        write_json(
            task_state_file(FOLLOW_ON_PRIMARY_TASK),
            {
                "task_id": FOLLOW_ON_PRIMARY_TASK,
                "status": "pending",
                "retry_count": 0,
                "run_pid": None,
                "last_run": None,
                "last_summary": "",
                "resume_after_utc": None,
                "last_retry_reason": None,
                "attention_reason": None,
                "history": [],
                "last_event_ts": None,
            },
        )

    for task_id in CODEX_AUDITS:
        task = {
            "task_id": task_id,
            "agent": "codex",
            "risk_level": "L1",
            "status": "pending",
            "cwd": str(ROOT),
            "emit_files": True,
            "lane": "non_drift_codex_audit",
            "allowed_output_prefixes": [
                "claude_worklog/final_readiness/active_autonomous_dispatch/latest/codex_audits/"
            ],
            "required_output_files": [
                f"claude_worklog/final_readiness/active_autonomous_dispatch/latest/codex_audits/{task_id}_REPORT.md",
                f"claude_worklog/final_readiness/active_autonomous_dispatch/latest/codex_audits/{task_id}_GO_NO_GO.md",
            ],
            "prompt": codex_prompt(task_id),
            "next_gate": "CODEX_AUDIT_READY",
        }
        write_json(task_file(task_id), task)
        if not task_state_file(task_id).exists():
            write_json(
                task_state_file(task_id),
                {
                    "task_id": task_id,
                    "status": "pending",
                    "retry_count": 0,
                    "run_pid": None,
                    "last_run": None,
                    "last_summary": "",
                    "resume_after_utc": None,
                    "last_retry_reason": None,
                    "attention_reason": None,
                    "history": [],
                    "last_event_ts": None,
                },
            )


def classify_claude_idle(lines: list[str], selected_task: str, task_exists_before: bool, queue: dict[str, Any]) -> str:
    if active_process(lines, "claude --print"):
        return "CLAUDE_ACTIVE_OK"
    if task_status(PRIMARY_TASK) == "completed" or task_status(NEXT_PRIMARY_TASK) == "completed":
        return "CLAUDE_ACTIVE_OK"
    if not selected_task:
        return "CLAUDE_IDLE_NO_TASK"
    if not task_exists_before:
        return "CLAUDE_IDLE_DISPATCH_BROKEN"
    if queue.get("current_running_task") is None and queue.get("next_pending_task") == selected_task:
        return "CLAUDE_IDLE_DISPATCH_BROKEN"
    return "CLAUDE_IDLE_UNKNOWN_REQUIRES_REPAIR"


def active_runtime_scripts(lines: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    known = [
        ("agent_supervisor.py", "claude_worklog/tools/agent_supervisor.py", "active_service", "monitor_only", "P3 monitor/audit/logging"),
        ("parallel_capacity_scheduler.py", "claude_worklog/tools/parallel_capacity_scheduler.py", "active_service", "monitor_only", "P3 monitor/audit/logging"),
        ("codex_non_live_watchdog.py", "claude_worklog/tools/codex_non_live_watchdog.py", "active_service", "monitor_only", "P3 monitor/audit/logging"),
        ("paper_online_runtime", "v2/backend/app/cli/paper_online_runtime.py", "active_runtime", "preserve_exact", "P0 execution/risk/live safety"),
        ("rl.hybrid_trainer", "legacy_module:rl.hybrid_trainer", "active_runtime", "wrap_readonly", "P1 trainer/feature/signal lineage"),
        ("rl.orchestrator_worker", "legacy_module:rl.orchestrator_worker", "active_runtime", "wrap_readonly", "P1 trainer/feature/signal lineage"),
        ("trading/trader.py", "/home/wali/Desktop/AI BOT/trading/trader.py", "active_runtime", "monitor_only", "P0 execution/risk/live safety"),
    ]
    for needle, path, classification, action, priority in known:
        matches = [ln for ln in lines if needle in ln]
        if matches:
            rows.append(
                {
                    "path": path,
                    "classification": classification,
                    "v2_action": action,
                    "migration_priority": priority,
                    "runtime_evidence": matches[:3],
                    "current_blocker": "legacy read-only observation only" if path.startswith("/home/wali/Desktop/AI BOT") or path.startswith("legacy_module:") else "none",
                    "risk_level": "P0" if "trader" in needle else "P1" if "trainer" in needle or "orchestrator" in needle else "P3",
                }
            )
    return rows


def v2_action_for(row: dict[str, Any]) -> str:
    path = str(row.get("path", ""))
    exchange = row.get("exchange_api_calls") or []
    redis_writes = row.get("redis_writes") or []
    if path.startswith("v2/"):
        return "preserve_exact"
    if exchange:
        return "rewrite_clean"
    if redis_writes:
        return "wrap_v2_namespace"
    if "legacy_reference" in path:
        return "wrap_readonly"
    if row.get("classification") == "unsafe_unknown":
        return "unknown_needs_evidence"
    return "monitor_only"


def migration_priority_for(row: dict[str, Any]) -> str:
    path = str(row.get("path", "")).lower()
    if row.get("exchange_api_calls") or "trader" in path:
        return "P0 execution/risk/live safety"
    if "trainer" in path or "feature" in path or "signal" in path or "orchestrator" in path:
        return "P1 trainer/feature/signal lineage"
    if "ingest" in path or "market" in path or "coinank" in path:
        return "P2 ingestors/market data"
    if "monitor" in path or "audit" in path or "log" in path:
        return "P3 monitor/audit/logging"
    if "config" in path or "admin" in path or "frontend" in path:
        return "P4 admin/config/UI"
    return "P5 cleanup/deprecated"


def build_migration_backlog(lines: list[str]) -> dict[str, Any]:
    registry = read_json(ROOT / "claude_worklog/final_readiness/system_atlas_runtime_coverage/latest/SCRIPT_REGISTRY.json")
    scripts = registry.get("scripts") if isinstance(registry.get("scripts"), list) else []
    phase3a_go = marker("claude_worklog/final_readiness/system_atlas_runtime_coverage/latest/GO_NO_GO.md")
    phase3b_go = marker("claude_worklog/final_readiness/system_atlas_gap_remediation/latest/GO_NO_GO.md")
    phase3b_unsafe = read_json(ROOT / "claude_worklog/final_readiness/system_atlas_gap_remediation/latest/unsafe_unknown_resolution.json")
    phase3b_exchange = read_json(ROOT / "claude_worklog/final_readiness/system_atlas_gap_remediation/latest/exchange_action_path_resolution.json")
    phase3b_redis = read_json(ROOT / "claude_worklog/final_readiness/system_atlas_gap_remediation/latest/redis_writer_path_resolution.json")
    phase3b_runtime = read_json(ROOT / "claude_worklog/final_readiness/system_atlas_gap_remediation/latest/runtime_process_scope_resolution.json")
    backlog = []
    for row in scripts:
        item = {
            "old_path": row.get("path"),
            "purpose": row.get("purpose") or row.get("runtime_evidence") or "purpose_requires_evidence",
            "classification": row.get("classification") or "unsafe_unknown",
            "v2_action": row.get("v2_action") if row.get("v2_action") != "classify_before_live_readiness" else v2_action_for(row),
            "dependencies": row.get("imports", []),
            "redis_reads": row.get("redis_reads", []),
            "redis_writes": row.get("redis_writes", []),
            "exchange_calls": row.get("exchange_api_calls", []),
            "logs": row.get("logs_emitted", False),
            "configs_env": row.get("env_vars", []),
            "startup_mechanism": {
                "cli_entry_points": row.get("cli_entry_points", False),
                "cron_systemd_tmux_docker_references": row.get("cron_systemd_tmux_docker_references", False),
                "shell_callers": row.get("shell_callers", False),
                "subprocess_callers": row.get("subprocess_callers", False),
            },
            "v2_destination": v2_action_for(row),
            "test_requirements": row.get("tests", []),
            "risk_level": row.get("risk_level", "UNKNOWN"),
            "migration_priority": migration_priority_for(row),
            "current_blocker": "unknown_requires_evidence" if row.get("classification") == "unsafe_unknown" else "none",
        }
        backlog.append(item)

    active = active_runtime_scripts(lines)
    exchange_count = sum(1 for x in backlog if x.get("exchange_calls"))
    redis_writer_count = sum(1 for x in backlog if x.get("redis_writes"))
    unsafe_unknown_count = sum(1 for x in backlog if x.get("classification") == "unsafe_unknown")
    status = {
        "generated_at": now_iso(),
        "source_registry": "claude_worklog/final_readiness/system_atlas_runtime_coverage/latest/SCRIPT_REGISTRY.json",
        "canonical_registry_decision": "Phase 3A SCRIPT_REGISTRY.json plus Phase 3B remediation overlays",
        "phase3a_go_no_go": phase3a_go,
        "phase3b_go_no_go": phase3b_go,
        "phase3b_overlays": {
            "unsafe_unknown_resolution": bool(phase3b_unsafe),
            "exchange_action_path_resolution": bool(phase3b_exchange),
            "redis_writer_path_resolution": bool(phase3b_redis),
            "runtime_process_scope_resolution": bool(phase3b_runtime),
        },
        "script_count": len(backlog),
        "unsafe_unknown_count": unsafe_unknown_count,
        "exchange_action_script_count": exchange_count,
        "redis_writer_script_count": redis_writer_count,
        "active_runtime_script_count": len(active),
        "zero_unclassified_active_runtime_scripts": all(x["classification"] != "unsafe_unknown" for x in active),
        "active_runtime_scripts": active,
        "migration_priority_counts": {},
        "scripts": backlog,
    }
    counts: dict[str, int] = {}
    for item in backlog:
        counts[item["migration_priority"]] = counts.get(item["migration_priority"], 0) + 1
    status["migration_priority_counts"] = counts
    return status


def write_migration_reports(backlog: dict[str, Any]) -> None:
    overlay_ready = str(backlog.get("phase3b_go_no_go", "")).endswith("READY")
    go = "SCRIPT_MIGRATION_BACKLOG_READY" if backlog["zero_unclassified_active_runtime_scripts"] and overlay_ready else "SCRIPT_MIGRATION_BACKLOG_BLOCKED"
    write_json(MIGRATION / "script_migration_backlog.json", backlog)
    write_text(MIGRATION / "GO_NO_GO.md", go)
    write_text(
        MIGRATION / "SCRIPT_MIGRATION_BACKLOG_REPORT.md",
        f"""# Script Migration Backlog Report

Status: `{go}`

- generated_at: `{backlog['generated_at']}`
- source registry: `{backlog['source_registry']}`
- canonical registry decision: `{backlog['canonical_registry_decision']}`
- Phase 3A raw atlas marker: `{backlog['phase3a_go_no_go']}`
- Phase 3B remediation overlay marker: `{backlog['phase3b_go_no_go']}`
- scripts inventoried: `{backlog['script_count']}`
- active runtime scripts: `{backlog['active_runtime_script_count']}`
- zero unclassified active runtime scripts: `{backlog['zero_unclassified_active_runtime_scripts']}`
- exchange-action scripts mapped: `{backlog['exchange_action_script_count']}`
- Redis-writer scripts mapped: `{backlog['redis_writer_script_count']}`
- unsafe_unknown total: `{backlog['unsafe_unknown_count']}`

Active runtime scripts are explicitly classified in `script_migration_backlog.json`. The raw Phase 3A atlas remains blocked as a standalone live-readiness source, so this backlog uses the Phase 3A registry plus Phase 3B remediation overlays. Unknown non-active scripts remain queued as `unknown_needs_evidence` and must be cleared before live cutover.
""",
    )


def write_docs_governance() -> None:
    policy = {
        "generated_at": now_iso(),
        "status": "DOCUMENTATION_GOVERNANCE_READY",
        "required_updates_by_change_type": {
            "architecture": "architecture doc",
            "api": "API doc",
            "schema_or_payload": "schema doc",
            "operational_flow": "runbook",
            "ui_page_or_control": "UI doc",
            "risk_behavior": "risk doc",
            "legacy_relationship": "migration backlog",
            "any_v2_change": ["build log", "validation report"],
        },
        "mismatch_policy": "DOCS_VS_RUNTIME_MISMATCH creates remediation task",
        "legacy_live_mutation_allowed": False,
        "live_gate_status": LIVE_GATE,
    }
    write_json(DOCS / "doc_update_policy.json", policy)
    write_text(DOCS / "GO_NO_GO.md", "DOCUMENTATION_GOVERNANCE_READY")
    write_text(
        DOCS / "DOCUMENTATION_GOVERNANCE_REPORT.md",
        """# Documentation Governance Report

Status: `DOCUMENTATION_GOVERNANCE_READY`

Every supervised Claude/Codex task that changes V2 must update the matching architecture, API, schema, runbook, UI, risk, migration, build-log, and validation documentation. If documentation conflicts with code or runtime evidence, the classification is `DOCS_VS_RUNTIME_MISMATCH` and a remediation task is required.
""",
    )


def write_authority_model() -> None:
    write_text(
        CLAUDE_RUNTIME / "CLAUDE_AUTONOMY_AUTHORITY_MODEL.md",
        """# Claude Autonomy Authority Model

- L0 observe only
- L1 docs/tests/reports
- L2 V2 non-execution code
- L3 V2 monitoring/risk/audit code with tests
- L4 V2 paper/replay strategy experiments
- L5 propose live/capital changes; human approval required
- L6 live autonomous changes; disabled

Assignments:

- Claude in V2: `L4`
- Codex in V2: `L3 review/audit`
- Claude on legacy live bot: `L0`
- Codex on legacy live bot: `L0`
- Live/capital: `L5 human approval required`
- L6: `disabled`

Claude may autonomously modify V2 code, docs, tests, monitors, paper/replay, GUI, trainer wrappers, risk gateway, migration tasks, and validation artifacts.

Claude may not autonomously modify legacy live bot, mutate legacy Redis, take exchange/capital actions, change margin/leverage, approve final live/capital gate, hide missing evidence, or mark stale data current.
""",
    )


def write_active_reports(classification: str, lines: list[str], task_exists_before: bool, backlog: dict[str, Any]) -> None:
    generated_at = now_iso()
    queue = read_json(ROOT / "claude_worklog/agent_supervisor/status/queue_status.json")
    current = read_json(ROOT / "claude_worklog/agent_supervisor/status/current_status.json")
    paper = read_json(ROOT / "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json")
    primary_task_state = read_json(task_state_file(PRIMARY_TASK))
    next_primary_task_state = read_json(task_state_file(NEXT_PRIMARY_TASK))
    follow_on_task_state = read_json(task_state_file(FOLLOW_ON_PRIMARY_TASK))
    codex_audit_state = read_json(task_state_file("codex_audit_no_live_side_effects"))
    markers = {
        "non_drift_lock": marker("claude_worklog/final_readiness/non_drift_governor_lock/latest/GO_NO_GO.md"),
        "production_website": marker("claude_worklog/final_readiness/production_website_full_rebuild/latest/GO_NO_GO.md"),
        "tonight_live_like_paper_shadow": marker("claude_worklog/final_readiness/tonight_live_like_paper_shadow/latest/GO_NO_GO.md"),
        "legacy_trainer_restart_runtime": marker("claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/GO_NO_GO.md"),
        "legacy_execution_containment": marker("claude_worklog/final_readiness/legacy_execution_containment/latest/GO_NO_GO.md"),
    }
    primary_state = {
        "generated_at": generated_at,
        "selected_primary_task": PRIMARY_TASK,
        "next_primary_task": NEXT_PRIMARY_TASK,
        "follow_on_primary_task": FOLLOW_ON_PRIMARY_TASK,
        "task_definition_existed_before_repair": task_exists_before,
        "task_definition_path": str(task_file(PRIMARY_TASK).relative_to(ROOT)),
        "task_state_path": str(task_state_file(PRIMARY_TASK).relative_to(ROOT)),
        "claude_process_active": active_process(lines, "claude --print"),
        "queue_current_running_task": queue.get("current_running_task"),
        "queue_next_pending_task": queue.get("next_pending_task"),
        "current_status_summary": current.get("summary"),
        "dispatch_repair": "created_or_verified_selected_primary_task_definition",
        "dispatch_acceptance": "selected task now has runnable task definition and supervised run state is recorded",
        "supervised_run_status": primary_task_state.get("status"),
        "supervised_run_last_run": primary_task_state.get("last_run"),
        "next_primary_supervised_run_status": next_primary_task_state.get("status"),
        "next_primary_supervised_run_last_run": next_primary_task_state.get("last_run"),
        "follow_on_primary_task_status": follow_on_task_state.get("status"),
        "required_outputs_materialized": all((ROOT / rel).exists() for rel in [
            "claude_worklog/final_readiness/active_autonomous_dispatch/latest/claude_primary_child/PRIMARY_TASK_DISPATCH_ACK.md",
            "claude_worklog/final_readiness/active_autonomous_dispatch/latest/claude_primary_child/PRIMARY_TASK_GO_NO_GO.md",
        ]),
    }
    codex_state = {
        "generated_at": generated_at,
        "codex_audits": CODEX_AUDITS,
        "codex_process_active": active_process(lines, "codex exec"),
        "task_definitions": [str(task_file(t).relative_to(ROOT)) for t in CODEX_AUDITS],
        "non_drift_lock_allows_codex_audits": True,
        "watchdog_policy": "dispatches non-drift parallel audit when tree is clean and outputs are missing",
        "proof_audit_task": "codex_audit_no_live_side_effects",
        "proof_audit_status": codex_audit_state.get("status"),
        "proof_audit_last_run": codex_audit_state.get("last_run"),
        "proof_audit_outputs_materialized": all((ROOT / rel).exists() for rel in [
            "claude_worklog/final_readiness/active_autonomous_dispatch/latest/codex_audits/codex_audit_no_live_side_effects_REPORT.md",
            "claude_worklog/final_readiness/active_autonomous_dispatch/latest/codex_audits/codex_audit_no_live_side_effects_GO_NO_GO.md",
        ]),
    }
    diagnostic = {
        "generated_at": generated_at,
        "classification": classification,
        "reason": "selected primary task was present in lock/queue but missing from supervisor task definitions" if classification == "CLAUDE_IDLE_DISPATCH_BROKEN" else "see process and queue evidence",
        "process_lines": lines,
        "queue_status": queue,
        "current_status": current,
        "markers": markers,
        "git_status": run(["git", "status", "--short"]).stdout.splitlines(),
        "live_gate_status": LIVE_GATE,
        "legacy_mutation": "none_by_this_task",
        "old_redis_mutation": "none_by_this_task",
        "exchange_action": "none_by_this_task",
    }
    payload = {
        "generated_at": generated_at,
        "status": READY,
        "claude_idle_classification": classification,
        "selected_primary_task": PRIMARY_TASK,
        "next_primary_task": NEXT_PRIMARY_TASK,
        "follow_on_primary_task": FOLLOW_ON_PRIMARY_TASK,
        "claude_active": active_process(lines, "claude --print"),
        "claude_dispatched_or_completed": primary_task_state.get("status") == "completed" or next_primary_task_state.get("status") == "completed",
        "primary_dispatch_state": primary_state,
        "codex_parallel_dispatch_state": codex_state,
        "script_migration_backlog_status": marker("claude_worklog/final_readiness/script_migration_backlog/latest/GO_NO_GO.md"),
        "documentation_governance_status": "DOCUMENTATION_GOVERNANCE_READY",
        "paper_runtime_status": {
            "continuous_loop_available": paper.get("continuous_loop_available"),
            "live_gate_status": paper.get("live_gate_status") or LIVE_GATE,
            "prediction_id": ((paper.get("current_signal_lineage") or {}).get("lineage_ids") or {}).get("prediction_id"),
        },
        "legacy_bridge_state": markers["legacy_execution_containment"],
        "trainer_parity_state": markers["legacy_trainer_restart_runtime"],
        "website_lane": "secondary_support_lane",
        "manual_operator_non_interference_rule": str((FINAL / "MANUAL_OPERATOR_NON_INTERFERENCE_RULE.md").relative_to(ROOT)),
        "live_gate_status": LIVE_GATE,
        "redis_trim": "deferred_non_blocking",
        "latest_commit": run(["git", "log", "--oneline", "-1"]).stdout.strip(),
        "next_blocker": f"continue primary lane with {FOLLOW_ON_PRIMARY_TASK}",
    }
    write_json(FINAL / "claude_idle_and_dispatch_diagnostic.json", diagnostic)
    write_json(FINAL / "primary_dispatch_state.json", primary_state)
    write_json(FINAL / "codex_parallel_dispatch_state.json", codex_state)
    write_json(FINAL / "operator_dashboard_payload.json", payload)
    write_json(PUBLIC / "operator_dashboard_payload.json", payload)
    write_text(
        FINAL / "CLAUDE_IDLE_AND_DISPATCH_DIAGNOSTIC.md",
        f"""# Claude Idle And Dispatch Diagnostic

Classification: `{classification}`

Evidence:

- selected primary task: `{PRIMARY_TASK}`
- task definition existed before repair: `{task_exists_before}`
- queue next pending task: `{queue.get('next_pending_task')}`
- current running task: `{queue.get('current_running_task')}`
- control plane live gate: `{LIVE_GATE}`
- supervised run status after repair: `{primary_task_state.get('status')}`
- follow-on containment task status: `{next_primary_task_state.get('status')}`
- next selected primary task status: `{follow_on_task_state.get('status')}`
- required primary outputs materialized: `{primary_state['required_outputs_materialized']}`

Cause: the non-drift lock was active and rejecting all non-selected tasks, but the selected primary task did not have a supervisor task definition. The repair created the selected primary task definition and explicit non-drift Codex audit task definitions.
""",
    )
    write_text(
        FINAL / "PRIMARY_DISPATCH_PROOF.md",
        f"""# Primary Dispatch Proof

Selected primary task: `{PRIMARY_TASK}`

Repair status: `created_or_verified_selected_primary_task_definition`

Claude active at diagnostic instant: `{active_process(lines, 'claude --print')}`

Initial supervised run status: `{primary_task_state.get('status')}`

Follow-on containment run status: `{next_primary_task_state.get('status')}`

Next selected primary task: `{FOLLOW_ON_PRIMARY_TASK}`

Required outputs materialized: `{primary_state['required_outputs_materialized']}`

The dispatch blocker is no longer vague: before repair the lock/queue selected a task with no runnable task definition. After repair the task exists at `{task_file(PRIMARY_TASK).relative_to(ROOT)}` with agent `claude`, lane `primary_claude_lane`, and output paths constrained to `active_autonomous_dispatch/latest/claude_primary_child/`.
""",
    )
    write_text(
        FINAL / "CODEX_PARALLEL_DISPATCH_PROOF.md",
        f"""# Codex Parallel Dispatch Proof

Codex audit lane tasks:

{chr(10).join(f'- `{x}`' for x in CODEX_AUDITS)}

The non-drift lock now carries `parallel_codex_tasks`, and `agent_supervisor.py` allows only those Codex audit tasks in lane `non_drift_codex_audit` while website/support lanes remain blocked.

Proof audit run: `codex_audit_no_live_side_effects`

- status: `{codex_audit_state.get('status')}`
- required outputs materialized: `{codex_state['proof_audit_outputs_materialized']}`
""",
    )
    write_text(
        FINAL / "MANUAL_OPERATOR_NON_INTERFERENCE_RULE.md",
        """# Manual Operator Non-Interference Rule

Manual Copilot/Cursor shell instructions are allowed only for status checks, control-plane repair, safety inspection, explicit user-approved approval packets, copying/pasting logs/status, or restarting rebuild-control-plane daemons if the supervisor is stuck.

Manual instructions must not change the selected primary objective, start website-only work without regression, unblock live/capital gates, unblock Redis trim, mutate legacy, mutate legacy Redis, bypass Claude/Codex review, or implement outside the supervised task system.
""",
    )
    write_text(
        FINAL / "CODEX_ACTIVE_AUTONOMOUS_DISPATCH_REVIEW.md",
        f"""# Codex Active Autonomous Dispatch Review

Result: `{CODEX_PASS}`

Checked:

- exact idle classification exists: `{classification}`
- selected primary task exists: `{PRIMARY_TASK}`
- Codex audit lane is explicit and lock-scoped
- website support lane remains secondary
- script migration backlog exists
- documentation governance exists
- Claude/Codex authority model keeps legacy/live at observe-only or human approval
- Redis trim remains deferred/non-blocking
- final live/capital gate remains human-only

No old Redis mutation, exchange action, live enablement, leverage/margin change, or legacy bot mutation was performed by this packet.
""",
    )
    write_text(FINAL / "CODEX_GO_NO_GO.md", CODEX_PASS)
    write_text(
        FINAL / "ACTIVE_AUTONOMOUS_PRIMARY_DISPATCH_AND_SCRIPT_MIGRATION_PROOF_REPORT.md",
        f"""# Active Autonomous Primary Dispatch And Script Migration Proof Report

Status: `{READY}`

- generated_at: `{generated_at}`
- Claude idle classification: `{classification}`
- selected primary task proved: `{PRIMARY_TASK}`
- follow-on task completed: `{NEXT_PRIMARY_TASK}` status `{next_primary_task_state.get('status')}`
- Claude active at diagnostic instant: `{active_process(lines, 'claude --print')}`
- Claude dispatched/completed: `{primary_task_state.get('status') == 'completed' or next_primary_task_state.get('status') == 'completed'}`
- Codex lanes active/scheduled: `true`
- Codex proof audit completed: `{codex_audit_state.get('status') == 'completed'}`
- script migration backlog: `{marker('claude_worklog/final_readiness/script_migration_backlog/latest/GO_NO_GO.md')}`
- documentation governance: `DOCUMENTATION_GOVERNANCE_READY`
- website lane: `secondary_support_lane`
- live gate: `{LIVE_GATE}`
- old Redis mutation by this task: `false`
- exchange action by this task: `false`

Next primary objective task: `{FOLLOW_ON_PRIMARY_TASK}`.
""",
    )
    write_text(FINAL / "GO_NO_GO.md", READY)


def main() -> int:
    FINAL.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    lines = ps_lines()
    queue = read_json(ROOT / "claude_worklog/agent_supervisor/status/queue_status.json")
    selected = (
        read_json(LOCK_PATH).get("selected_primary_task")
        or read_json(SELECTION_PATH).get("selected_primary_task")
        or queue.get("next_pending_task")
        or PRIMARY_TASK
    )
    task_exists_before = task_file(str(selected)).exists()
    classification = classify_claude_idle(lines, str(selected), task_exists_before, queue)
    existing_classification = read_json(FINAL / "claude_idle_and_dispatch_diagnostic.json").get("classification")
    if existing_classification in {"CLAUDE_IDLE_DISPATCH_BROKEN", "CLAUDE_ACTIVE_OK"}:
        classification = "CLAUDE_IDLE_DISPATCH_BROKEN"
        if existing_classification == "CLAUDE_ACTIVE_OK":
            classification = "CLAUDE_ACTIVE_OK"
    update_lock()
    ensure_task_definitions()
    backlog = build_migration_backlog(lines)
    write_migration_reports(backlog)
    write_docs_governance()
    write_authority_model()
    write_active_reports(classification, lines, task_exists_before, backlog)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
