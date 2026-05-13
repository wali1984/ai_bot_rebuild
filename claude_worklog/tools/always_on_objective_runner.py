#!/usr/bin/env python3
"""Always-on non-live objective runner for AI BOT V2.

This tool is intentionally conservative. It writes only AI BOT REBUILD task,
status, and report files. It does not touch legacy code, write Redis, or
perform exchange actions. In daemon mode it periodically makes sure there is
always a primary Claude task or a documented blocker, and always a Codex audit
lane when safe work exists.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TASKS = ROOT / "claude_worklog/agent_supervisor/tasks"
STATE_TASKS = ROOT / "claude_worklog/agent_supervisor/state/tasks"
STATUS = ROOT / "claude_worklog/agent_supervisor/status"
EVENTS = ROOT / "claude_worklog/agent_supervisor/events.jsonl"
FINAL = ROOT / "claude_worklog/final_readiness/always_on_claude_codex_runtime/latest"
PUBLIC = ROOT / "v2/frontend/public/always_on_claude_codex_runtime/latest"

LIVE_GATE = "blocked_human_only"
READY = "ALWAYS_ON_CLAUDE_CODEX_PRIMARY_OBJECTIVE_RUNTIME_READY"
BLOCKED = "ALWAYS_ON_CLAUDE_CODEX_PRIMARY_OBJECTIVE_RUNTIME_BLOCKED"

PRIMARY_CHAIN = [
    "TONIGHT_V2_LIVE_LIKE_PAPER_SHADOW_AND_CANARY_PREFLIGHT",
    "LEGACY_LIVE_BRIDGE_TO_V2_DATA_PLANE",
    "LEGACY_EXECUTION_CONTAINMENT_AND_TRAINER_PARITY_SAFE_MODE",
    "SAFE_LEGACY_TRAINER_BRIDGE_AND_GPU_PARITY_SANDBOX",
    "RISK_GATEWAY_RUNTIME_EXPANSION_TESTS",
    "V2_DATA_PLANE_AND_SCRIPT_MIGRATION_BACKLOG",
    "PUBLIC_HOSTING_AND_TELEMETRY_BRIDGE",
    "LIVE_READINESS_PREFLIGHT",
    "FINAL_LIVE_CAPITAL_APPROVAL_REQUIRED",
]

NEVER_EMPTY_LADDER = {
    "P0_safety_critical_runtime_containment": [
        "legacy exchange action evidence",
        "dangerous controls enabled",
        "old Redis mutation evidence",
        "live gate hidden/broken",
        "stale current-truth regression",
    ],
    "P1_go_live_readiness_primary_chain": PRIMARY_CHAIN,
    "P2_continuous_legacy_monitoring_and_audit": [
        "monitor_legacy_trainer_runtime",
        "monitor_ppo_masa_gpu_metrics",
        "audit_hedge_system_behavior",
        "audit_stop_loss_and_take_profit",
        "audit_stealth_profit_profit_taking",
        "audit_liquidation_forced_close",
        "audit_stale_signal",
        "audit_duplicate_exchange_order_id",
        "audit_missing_signal_id_confidence",
        "audit_legacy_redis_readonly_stream",
        "audit_coinank_market_intelligence",
    ],
    "P3_v2_migration_and_improvement": [
        "migrate_ingestors_into_v2_wrappers",
        "migrate_feature_pipeline",
        "migrate_trainer_parity",
        "migrate_orchestrator_adapter",
        "migrate_risk_gateway_rules",
        "migrate_paper_shadow_ledger",
        "migrate_config_admin",
        "migrate_script_registry",
        "migrate_monitor_center",
        "migrate_admin_ai",
        "v2_durable_db_bounded_redis",
    ],
    "P4_research_optimization": [
        "paper_shadow_pnl_improvement",
        "confidence_calibration",
        "strategy_scorecards",
        "symbol_universe_improvements",
        "win_rate_candidate_discovery",
        "tail_risk_detection",
        "drawdown_control",
        "no_live_strategy_experiments",
    ],
    "P5_website_support": [
        "route_crawl_failure",
        "data_truth_regression",
        "broken_page",
        "new_v2_feature_needs_gui_visibility",
    ],
    "P6_deferred_human_decisions": [
        "Redis trim approval",
        "final live/capital approval",
        "legacy trader containment action if human-only",
        "live API key activation",
    ],
}

RECURRING_MONITORS = [
    "monitor_legacy_trainer_runtime",
    "monitor_ppo_masa_gpu_metrics",
    "audit_hedge_system_behavior",
    "audit_stop_loss_and_take_profit",
    "audit_stealth_profit_profit_taking",
    "audit_signal_lineage_current",
    "audit_execution_attribution",
    "audit_risk_gateway_blocks",
    "audit_paper_shadow_vs_legacy",
    "audit_coinank_market_intelligence",
    "audit_script_migration_progress",
    "audit_public_dashboard_truth",
]

CODEX_LANES = [
    "codex_audit_no_live_side_effects",
    "codex_audit_current_runtime_truth",
    "codex_audit_risk_gateway_fail_closed",
    "codex_audit_trainer_parity_truth",
    "codex_audit_legacy_bridge_readonly",
    "codex_audit_public_dashboard_truth",
    "codex_audit_script_migration_coverage",
    "codex_audit_v2_data_plane_independence",
    "codex_audit_documentation_completeness",
    "codex_audit_coinank_bridge_contract",
    "codex_audit_config_admin_dangerous_controls",
    "codex_audit_paper_shadow_performance",
]


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def run(cmd: list[str] | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, shell=isinstance(cmd, str), text=True, capture_output=True)


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def read_text(path: Path) -> str:
    try:
        return path.read_text(errors="replace").strip()
    except Exception:
        return ""


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def append_event(event: dict[str, Any]) -> None:
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    event = dict(event)
    event.setdefault("ts", now())
    with EVENTS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")


def process_lines(pattern: str) -> list[str]:
    proc = run(f"ps -eo pid,ppid,etimes,pcpu,pmem,cmd | grep -E '{pattern}' | grep -v grep || true")
    return [line for line in proc.stdout.splitlines() if line.strip()]


def git_status_lines() -> list[str]:
    return [line for line in run(["git", "status", "--short"]).stdout.splitlines() if line.strip()]


def marker(path: str) -> str:
    return read_text(ROOT / path)


def task_state(task_id: str) -> str:
    state = read_json(STATE_TASKS / f"{task_id}.json")
    definition = read_json(TASKS / f"{task_id}.json")
    return str(state.get("status") or definition.get("status") or "missing")


def primary_go_no_go() -> dict[str, str]:
    files = {
        "coinank_plan3_runtime_remediation": "claude_worklog/final_readiness/coinank_plan3_runtime_remediation/latest/GO_NO_GO.md",
        "non_drift_governor_lock": "claude_worklog/final_readiness/non_drift_governor_lock/latest/GO_NO_GO.md",
        "active_autonomous_dispatch": "claude_worklog/final_readiness/active_autonomous_dispatch/latest/GO_NO_GO.md",
        "tonight_live_like_paper_shadow": "claude_worklog/final_readiness/tonight_live_like_paper_shadow/latest/GO_NO_GO.md",
        "legacy_live_bridge_to_v2_data_plane": "claude_worklog/final_readiness/legacy_live_bridge_to_v2_data_plane/latest/GO_NO_GO.md",
        "legacy_execution_containment": "claude_worklog/final_readiness/legacy_execution_containment/latest/GO_NO_GO.md",
        "safe_legacy_trainer_bridge": "claude_worklog/final_readiness/safe_legacy_trainer_bridge/latest/GO_NO_GO.md",
        "script_migration_backlog": "claude_worklog/final_readiness/script_migration_backlog/latest/GO_NO_GO.md",
    }
    return {name: marker(path) or "MISSING" for name, path in files.items()}


def classify_dirty_line(line: str, active_children: bool) -> dict[str, str]:
    path = line[3:] if len(line) > 3 else line
    if (
        path.startswith("claude_worklog/final_readiness/always_on_claude_codex_runtime/")
        or path.startswith("v2/frontend/public/always_on_claude_codex_runtime/")
        or path.startswith("claude_worklog/tools/always_on_objective_runner.py")
        or path.startswith("claude_worklog/tools/automation_utilization_monitor.py")
        or path.startswith("v2/frontend/scripts/sync-proof-artifacts.mjs")
    ):
        cls = "durable_artifact_to_commit"
    elif path.startswith("claude_worklog/agent_supervisor/tasks/RISK_GATEWAY_RUNTIME_EXPANSION_TESTS.json"):
        cls = "durable_artifact_to_commit"
    elif path.startswith("claude_worklog/agent_supervisor/tasks/recurring_") or path.startswith("claude_worklog/agent_supervisor/tasks/codex_audit_"):
        cls = "durable_artifact_to_commit"
    elif path.startswith("claude_worklog/final_readiness/legacy_live_bridge_to_v2_data_plane/") or path.startswith("v2/frontend/public/legacy_live_bridge_to_v2_data_plane/"):
        cls = "durable_artifact_to_commit"
    elif path.startswith("claude_worklog/agent_supervisor/tasks/LEGACY_LIVE_BRIDGE_TO_V2_DATA_PLANE_READY.json"):
        cls = "durable_artifact_to_commit"
    elif path.startswith("claude_worklog/historical_pnl_audit/") or path.startswith("claude_worklog/legacy_readonly_audit/"):
        cls = "runtime_noise_to_restore_when_idle"
    elif path.startswith("claude_worklog/tools/build_active_autonomous_dispatch_packet.py") or path.startswith("claude_worklog/tools/check_objective_drift.py"):
        cls = "runtime_noise_to_restore_when_idle"
    elif active_children and (
        path.startswith("claude_worklog/final_readiness/active_autonomous_dispatch/")
        or path.startswith("v2/frontend/public/active_autonomous_dispatch/")
    ):
        cls = "active_task_owned"
    elif path.startswith("claude_worklog/autonomous_governor/") or path.startswith("claude_worklog/agent_supervisor/"):
        cls = "runtime_noise_to_restore_when_idle"
    elif path.startswith("v2/frontend/public/operator_truth") or path.startswith("claude_worklog/final_readiness/operator_truth_recovery/"):
        cls = "runtime_noise_to_restore_when_idle"
    elif path.startswith("v2/frontend/public/") and "/latest/" in path:
        cls = "runtime_noise_to_restore_when_idle"
    elif path.startswith("claude_worklog/final_readiness/"):
        cls = "runtime_noise_to_restore_when_idle"
    else:
        cls = "unknown_requires_review"
    return {"status_line": line, "path": path, "classification": cls}


def dirty_state() -> dict[str, Any]:
    claude_children = process_lines(r"claude --print")
    codex_children = process_lines(r"codex exec")
    active_children = bool(claude_children or codex_children)
    rows = [classify_dirty_line(line, active_children) for line in git_status_lines()]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["classification"]] = counts.get(row["classification"], 0) + 1
    return {
        "generated_at": now(),
        "active_claude_children": claude_children,
        "active_codex_children": codex_children,
        "active_child_present": active_children,
        "counts": counts,
        "files": rows,
        "policy": "Do not clean active-owned or runtime-noise files while control-plane daemons are running; commit durable artifacts separately.",
    }


def selected_primary_task() -> str:
    selection = read_json(ROOT / "claude_worklog/autonomous_governor/latest/NEXT_TASK_SELECTION.json")
    queue = read_json(STATUS / "queue_status.json")
    selected = (
        selection.get("selected_task_id")
        or selection.get("selected_primary_task")
        or queue.get("next_pending_task")
        or "RISK_GATEWAY_RUNTIME_EXPANSION_TESTS"
    )
    return str(selected)


def make_task(task_id: str, agent: str, prompt: str, output_dir: str, risk: str = "L1") -> dict[str, Any]:
    report = f"{output_dir}/{task_id}_REPORT.md"
    go = f"{output_dir}/{task_id}_GO_NO_GO.md"
    return {
        "task_id": task_id,
        "agent": agent,
        "risk_level": risk,
        "status": "pending",
        "cwd": str(ROOT),
        "emit_files": True,
        "allowed_output_prefixes": [output_dir + "/"],
        "required_output_files": [report, go],
        "lane": "primary_claude_lane" if agent == "claude" else "codex_parallel_audit",
        "next_gate": task_id,
        "prompt": prompt + f"\n\nEmit exactly two BEGIN_FILE blocks:\nBEGIN_FILE: {report}\n...report...\nEND_FILE\n\nBEGIN_FILE: {go}\n{task_id}_READY\nEND_FILE\n",
    }


def ensure_recurring_monitor_tasks() -> list[str]:
    created: list[str] = []
    for name in RECURRING_MONITORS:
        task_id = f"recurring_{name}"
        path = TASKS / f"{task_id}.json"
        if path.exists():
            continue
        prompt = (
            f"Run non-live recurring monitor `{name}`. Work only in AI BOT REBUILD. "
            "Read legacy processes/logs/Redis read-only only. Do not mutate legacy, old Redis, exchange state, leverage, margin, or live trading. "
            "Write health evidence and create a remediation recommendation if blocked."
        )
        task = make_task(task_id, "claude", prompt, f"claude_worklog/final_readiness/always_on_claude_codex_runtime/recurring/{name}", "L1")
        write_json(path, task)
        created.append(task_id)
    return created


def ensure_codex_audit_tasks() -> list[str]:
    created: list[str] = []
    for name in CODEX_LANES:
        task_id = name
        path = TASKS / f"{task_id}.json"
        if path.exists():
            continue
        prompt = (
            f"Run Codex non-live audit `{name}`. Do not touch /home/wali/Desktop/AI BOT. "
            "Do not write old Redis. Do not place/cancel orders. Do not change leverage/margin. "
            "Do not enable live trading. Review current runtime truth, primary objective drift, and safety. "
            "Create remediation task recommendations on fail."
        )
        task = make_task(task_id, "codex", prompt, f"claude_worklog/final_readiness/always_on_claude_codex_runtime/codex/{name}", "L1")
        write_json(path, task)
        created.append(task_id)
    return created


def ensure_primary_task() -> dict[str, Any]:
    selected = selected_primary_task()
    if selected == "FINAL_LIVE_CAPITAL_APPROVAL_REQUIRED":
        return {"selected": selected, "action": "human_final_gate_required", "created": False}
    path = TASKS / f"{selected}.json"
    state = task_state(selected)
    if path.exists() and state in {"pending", "running", "retry_scheduled", "blocked_quota", "claude_rate_limited_resume_scheduled"}:
        return {"selected": selected, "action": f"existing_{state}", "created": False}
    if state == "completed":
        selected = "RISK_GATEWAY_RUNTIME_EXPANSION_TESTS"
        path = TASKS / f"{selected}.json"
        state = task_state(selected)
        if path.exists() and state in {"pending", "running", "retry_scheduled"}:
            return {"selected": selected, "action": f"existing_{state}", "created": False}
    if not path.exists():
        prompt = (
            f"Build or validate `{selected}` as the next primary V2 live-like paper/shadow objective. "
            "Website work is support-only. Keep live blocked_human_only. Work only in AI BOT REBUILD. "
            "Legacy is read-only observed unless a separate explicit operator patch authorizes one file. "
            "Do not write old Redis, place/cancel orders, change leverage/margin, or enable live trading."
        )
        task = make_task(selected, "claude", prompt, f"claude_worklog/final_readiness/{selected.lower()}/latest", "L2")
        write_json(path, task)
        return {"selected": selected, "action": "created_pending", "created": True}
    if state == "completed":
        return {"selected": selected, "action": "completed_select_next_required", "created": False}
    return {"selected": selected, "action": f"state_{state}", "created": False}


def check_once(write_artifacts: bool = True) -> dict[str, Any]:
    FINAL.mkdir(parents=True, exist_ok=True)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    dirty = dirty_state()
    recurring_created = ensure_recurring_monitor_tasks()
    codex_created = ensure_codex_audit_tasks()
    primary = ensure_primary_task()
    claude_children = process_lines(r"claude --print")
    codex_children = process_lines(r"codex exec")
    queue = read_json(STATUS / "queue_status.json")
    paper_runtime = read_json(ROOT / "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json")
    coinank = read_json(ROOT / "v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json")
    markers = primary_go_no_go()
    utilization = {
        "classification": "ACTIVE_OK" if claude_children else "IDLE_NO_TASK_SELECTED" if primary.get("action") in {"created_pending", "completed_select_next_required"} else "IDLE_EXPECTED_BREAK",
        "claude_child_count": len(claude_children),
        "codex_child_count": len(codex_children),
        "active_child_count": len(claude_children) + len(codex_children),
        "selected_primary_task": primary.get("selected"),
        "primary_task_action": primary.get("action"),
        "codex_safe_audits_available": CODEX_LANES,
        "recurring_monitors_available": RECURRING_MONITORS,
    }
    ready = (
        primary.get("selected") != "FINAL_LIVE_CAPITAL_APPROVAL_REQUIRED"
        and bool(CODEX_LANES)
        and LIVE_GATE == "blocked_human_only"
    )
    result = {
        "generated_at": now(),
        "go_no_go": READY if ready else BLOCKED,
        "live_gate_status": LIVE_GATE,
        "dirty_state": dirty,
        "primary_task": primary,
        "recurring_monitor_tasks_created": recurring_created,
        "codex_audit_tasks_created": codex_created,
        "utilization": utilization,
        "queue_status": {
            "current_running_task": queue.get("current_running_task"),
            "next_pending_task": queue.get("next_pending_task"),
            "counts": queue.get("counts", {}),
            "gate": queue.get("gate"),
        },
        "markers": markers,
        "paper_runtime": {
            "generated_at": paper_runtime.get("generated_at"),
            "freshness": paper_runtime.get("freshness"),
            "live_gate_status": paper_runtime.get("live_gate_status"),
        },
        "coinank_remediation": {
            "go_no_go": markers.get("coinank_plan3_runtime_remediation"),
            "lastprice": coinank.get("lastprice_classification"),
            "runtime_cycles_passed": coinank.get("runtime_cycles_passed"),
            "global_11_key_contract_status": coinank.get("global_11_key_contract_status"),
        },
        "forbidden_actions_by_this_tool": {
            "legacy_mutation": False,
            "old_redis_write": False,
            "exchange_action": False,
            "live_enablement": False,
        },
    }
    if write_artifacts:
        write_json(FINAL / "always_on_runtime_state.json", result)
        write_json(FINAL / "git_dirty_state.json", dirty)
        write_json(FINAL / "never_empty_task_ladder.json", NEVER_EMPTY_LADDER)
        write_json(FINAL / "recurring_monitor_audit_tasks.json", {"generated_at": now(), "tasks": RECURRING_MONITORS})
        write_json(FINAL / "operator_dashboard_payload.json", result)
        write_json(PUBLIC / "operator_dashboard_payload.json", result)
        append_event({"event": "always_on_objective_runner_check", "selected_primary_task": primary.get("selected"), "classification": utilization["classification"]})
    return result


def daemon(poll_seconds: int) -> None:
    while True:
        check_once(write_artifacts=True)
        time.sleep(max(60, poll_seconds))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=300)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.daemon:
        daemon(args.poll_seconds)
    else:
        result = check_once(write_artifacts=True)
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
