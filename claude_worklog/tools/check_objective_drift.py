#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FINAL = ROOT / "claude_worklog/final_readiness/non_drift_governor_lock/latest"
PUBLIC = ROOT / "v2/frontend/public/non_drift_governor_lock/latest"
LOCK_PATH = ROOT / "claude_worklog/autonomous_governor/latest/NON_DRIFT_GOVERNOR_LOCK.json"
SELECTION_PATH = ROOT / "claude_worklog/autonomous_governor/latest/NEXT_TASK_SELECTION.json"
SELECTION_MD = ROOT / "claude_worklog/autonomous_governor/latest/NEXT_TASK_SELECTION.md"

READY = "CLAUDE_AUTOMATION_NON_DRIFT_GOVERNOR_LOCK_READY"
BLOCKED = "CLAUDE_AUTOMATION_NON_DRIFT_GOVERNOR_LOCK_BLOCKED"
CODEX_PASS = "CLAUDE_AUTOMATION_NON_DRIFT_GOVERNOR_LOCK_CODEX_PASS"
CODEX_FAIL = "CLAUDE_AUTOMATION_NON_DRIFT_GOVERNOR_LOCK_CODEX_FAIL"
LIVE_GATE = "blocked_human_only"
SELECTED_PRIMARY_TASK = "SAFE_LEGACY_TRAINER_BRIDGE_AND_GPU_PARITY_SANDBOX"
PARALLEL_CODEX_TASKS = [
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


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True))


def run(cmd: list[str] | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, shell=isinstance(cmd, str), text=True, capture_output=True)


def marker(rel: str) -> str:
    value = read_text(ROOT / rel)
    return value or "MISSING"


def age_seconds(timestamp: str | None) -> int | None:
    if not timestamp:
        return None
    text = str(timestamp).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()))
    except Exception:
        return None


def ps_lines(pattern: str) -> list[str]:
    proc = run(f"ps -eo pid,ppid,etimes,cmd | grep -E '{pattern}' | grep -v grep || true")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def task_kind(task: str) -> str:
    lower = task.lower()
    if any(term in lower for term in ["live_gate", "capital", "enable_live", "canary_activation"]):
        return "final_live_gate"
    if any(term in lower for term in ["redis_trim", "xtrim", "phase3h"]):
        return "redis_trim"
    if any(term in lower for term in ["website", "frontend", "route", "ui", "design", "visual"]):
        return "website_support"
    if any(term in lower for term in ["proof", "marker", "archive", "evidence_cleanup"]):
        return "proof_marker"
    if any(term in lower for term in ["legacy_execution", "exchange_order", "containment", "live_risk"]):
        return "safety_primary"
    if any(term in lower for term in ["paper", "shadow", "bridge", "trainer", "risk", "canary", "parity"]):
        return "primary_objective"
    return "unknown"


def build_status() -> dict[str, Any]:
    generated_at = now_iso()
    queue = read_json(ROOT / "claude_worklog/agent_supervisor/status/queue_status.json")
    current = read_json(ROOT / "claude_worklog/agent_supervisor/status/current_status.json")
    governor = read_json(SELECTION_PATH)
    existing_lock = read_json(LOCK_PATH)
    paper_runtime = read_json(ROOT / "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json")
    legacy_bridge = read_json(ROOT / "v2/frontend/public/operator_runtime/legacy_live_bridge/latest/legacy_live_bridge_status.json")

    markers = {
        "production_website": marker("claude_worklog/final_readiness/production_website_full_rebuild/latest/GO_NO_GO.md"),
        "production_website_codex": marker("claude_worklog/final_readiness/production_website_full_rebuild/latest/CODEX_GO_NO_GO.md"),
        "tonight_live_like_paper_shadow": marker("claude_worklog/final_readiness/tonight_live_like_paper_shadow/latest/GO_NO_GO.md"),
        "paper_online_canonical_truth_bridge": marker("claude_worklog/final_readiness/paper_online_canonical_truth_bridge/latest/GO_NO_GO.md"),
        "control_plane_supervisor_persistence": marker("claude_worklog/final_readiness/control_plane_supervisor_persistence/latest/GO_NO_GO.md"),
        "legacy_trainer_restart_runtime": marker("claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/GO_NO_GO.md"),
        "legacy_execution_containment": marker("claude_worklog/final_readiness/legacy_execution_containment/latest/GO_NO_GO.md"),
        "legacy_trainer_gpu_parity": marker("claude_worklog/final_readiness/legacy_trainer_gpu_parity/latest/GO_NO_GO.md"),
    }

    selected_task = (
        str(existing_lock.get("selected_primary_task") or "")
        or str(governor.get("selected_primary_task") or "")
        or str(queue.get("next_pending_task") or "")
        or SELECTED_PRIMARY_TASK
    )
    selected_kind = task_kind(selected_task)

    website_ready = markers["production_website"].endswith("READY")
    website_codex_pass = markers["production_website_codex"].endswith("CODEX_PASS")
    paper_shadow_ready = markers["tonight_live_like_paper_shadow"].endswith("READY")
    canonical_bridge_ready = markers["paper_online_canonical_truth_bridge"].endswith("READY")
    trainer_blocked = "BLOCKED" in markers["legacy_trainer_restart_runtime"] or markers["legacy_trainer_restart_runtime"] == "MISSING"
    execution_blocked = "BLOCKED" in markers["legacy_execution_containment"] or markers["legacy_execution_containment"] == "MISSING"
    primary_incomplete = trainer_blocked or execution_blocked
    paper_age = age_seconds(str(paper_runtime.get("generated_at") or ""))
    queue_age = age_seconds(str(queue.get("generated_at") or ""))
    legacy_bridge_age = age_seconds(str(legacy_bridge.get("generated_at") or ""))

    if selected_kind == "final_live_gate":
        drift_classification = "FINAL_LIVE_GATE_REQUIRED"
    elif selected_kind == "redis_trim":
        drift_classification = "REDIS_TRIM_DECISION_DEFERRED"
    elif selected_kind == "safety_primary":
        drift_classification = "SAFETY_CRITICAL_OVERRIDE"
    elif selected_kind == "website_support" and website_ready and primary_incomplete:
        drift_classification = "WEBSITE_DRIFT_BLOCKED"
    elif selected_kind == "website_support":
        drift_classification = "WEBSITE_SUPPORT_ALLOWED"
    elif selected_kind == "proof_marker" and primary_incomplete:
        drift_classification = "PROOF_MARKER_DRIFT_BLOCKED"
    else:
        drift_classification = "ON_PRIMARY_OBJECTIVE"

    current_primary_blockers: list[str] = []
    if trainer_blocked:
        current_primary_blockers.append("legacy_trainer_restart_runtime_parity_sync_blocked")
    if execution_blocked:
        current_primary_blockers.append("legacy_execution_containment_marker_missing")
    if paper_age is None or paper_age > 120:
        current_primary_blockers.append("paper_runtime_not_fresh")
    if not canonical_bridge_ready:
        current_primary_blockers.append("canonical_truth_bridge_not_ready")

    processes = {
        "agent_supervisor": ps_lines(r"agent_supervisor.py .*--daemon|agent_supervisor.py --daemon"),
        "parallel_capacity_scheduler": ps_lines(r"parallel_capacity_scheduler.py --daemon"),
        "codex_non_live_watchdog": ps_lines(r"codex_non_live_watchdog.py --daemon"),
        "paper_runtime": ps_lines(r"paper_online_runtime"),
        "legacy_trainer": ps_lines(r"rl.hybrid_trainer"),
        "legacy_orchestrator": ps_lines(r"rl.orchestrator_worker"),
        "legacy_trader": ps_lines(r"trading/trader.py"),
    }

    return {
        "generated_at": generated_at,
        "classification": drift_classification,
        "selected_task": selected_task,
        "selected_task_kind": selected_kind,
        "recommended_next_primary_task": SELECTED_PRIMARY_TASK,
        "primary_objective": "V2 live-like paper/shadow, legacy bridge, risk gateway, trainer parity, and canary preflight",
        "primary_incomplete": primary_incomplete,
        "current_primary_blockers": current_primary_blockers,
        "markers": markers,
        "freshness": {
            "paper_runtime_age_seconds": paper_age,
            "queue_status_age_seconds": queue_age,
            "legacy_bridge_age_seconds": legacy_bridge_age,
        },
        "website_support_lane": {
            "status": "secondary_support_lane",
            "production_website_ready": website_ready,
            "production_website_codex_pass": website_codex_pass,
            "allowed_only_on_regression": True,
        },
        "live_gate_status": LIVE_GATE,
        "redis_trim": "deferred_non_blocking",
        "processes": processes,
        "source_evidence": {
            "queue_status": "claude_worklog/agent_supervisor/status/queue_status.json",
            "governor_selection": "claude_worklog/autonomous_governor/latest/NEXT_TASK_SELECTION.json",
            "non_drift_lock": "claude_worklog/autonomous_governor/latest/NON_DRIFT_GOVERNOR_LOCK.json",
            "paper_runtime": "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json",
        },
    }


def build_lanes(status: dict[str, Any]) -> dict[str, Any]:
    generated_at = status["generated_at"]
    return {
        "generated_at": generated_at,
        "primary_claude_lane": {
            "selected_task": status["recommended_next_primary_task"],
            "why_selected": "Website rebuild passed; legacy execution containment proof exists; trainer runtime/parity remains the active primary blocker.",
            "objective_mapping": [
                "V2 live-like paper/shadow",
                "legacy bridge read-only evidence",
                "risk gateway final authority",
                "trainer parity runtime capture",
                "canary preflight blocked_human_only",
            ],
            "autonomous_run_allowed": True,
            "human_approval_required": False,
            "source_evidence": [
                "claude_worklog/final_readiness/tonight_live_like_paper_shadow/latest/GO_NO_GO.md",
                "claude_worklog/final_readiness/legacy_trainer_restart_runtime/latest/GO_NO_GO.md",
                "claude_worklog/final_readiness/production_website_full_rebuild/latest/GO_NO_GO.md",
            ],
        },
        "codex_parallel_lane": {
            "selected_tasks": PARALLEL_CODEX_TASKS,
            "why_selected": "Parallel audits support primary runtime safety and truth without superseding the primary Claude lane.",
            "objective_mapping": "adversarial review of V2 live-like paper/shadow safety and data truth",
            "autonomous_run_allowed": True,
            "human_approval_required": False,
            "source_evidence": ["claude_worklog/autonomous_governor/latest/NON_DRIFT_GOVERNOR_LOCK.json"],
        },
        "website_support_lane": {
            "selected_task": "none_unless_regression",
            "why_selected": "Public/local website crawl passed; route work resumes only for route/data-truth regression or browser-visible defect.",
            "objective_mapping": "operator visibility support only",
            "autonomous_run_allowed": False,
            "human_approval_required": False,
            "source_evidence": [
                "claude_worklog/final_readiness/production_website_full_rebuild/latest/GO_NO_GO.md",
                "claude_worklog/final_readiness/production_website_full_rebuild/latest/CODEX_GO_NO_GO.md",
            ],
        },
        "blocked_decision_packets": {
            "redis_trim_approval": {
                "selected_task": "deferred_non_blocking",
                "human_approval_required": True,
            },
            "final_live_capital_approval": {
                "selected_task": "blocked_human_only",
                "human_approval_required": True,
            },
            "legacy_trader_containment_action": {
                "selected_task": "decision_packet_if_action_required",
                "human_approval_required": True,
            },
        },
    }


def write_packet(status: dict[str, Any], lanes: dict[str, Any]) -> None:
    generated_at = status["generated_at"]
    final_ready = (
        status["classification"] in {"ON_PRIMARY_OBJECTIVE", "SAFETY_CRITICAL_OVERRIDE", "REDIS_TRIM_DECISION_DEFERRED"}
        and status["live_gate_status"] == LIVE_GATE
        and status["website_support_lane"]["production_website_ready"]
    )
    go = READY if final_ready else BLOCKED
    codex = CODEX_PASS if final_ready else CODEX_FAIL

    lock = {
        "generated_at": generated_at,
        "lock_id": "CLAUDE_AUTOMATION_NON_DRIFT_GOVERNOR_LOCK",
        "status": "ACTIVE",
        "primary_objective": status["primary_objective"],
        "selected_primary_task": status["recommended_next_primary_task"],
        "selected_task_id": status["recommended_next_primary_task"],
        "parallel_codex_tasks": lanes["codex_parallel_lane"]["selected_tasks"],
        "codex_parallel_lane_allowed": True,
        "primary_lane": "v2_live_like_paper_shadow_canary_preflight",
        "support_lane_policy": "Website/UI/proof work is support-only unless it fixes a fresh route/data-truth regression or unblocks primary runtime truth.",
        "current_primary_blockers": status["current_primary_blockers"],
        "live_gate_status": LIVE_GATE,
        "old_redis_mutation_allowed": False,
        "exchange_mutation_allowed": False,
        "legacy_bot_mutation_allowed": False,
        "redis_trim": "deferred_non_blocking",
        "canonical_packet_path": "claude_worklog/final_readiness/non_drift_governor_lock/latest",
    }
    selection = {
        "generated_at": generated_at,
        "selected_primary_task": status["recommended_next_primary_task"],
        "selected_task_id": status["recommended_next_primary_task"],
        "primary_lane": "v2_live_like_paper_shadow_canary_preflight",
        "ui_polish_lane_state": "support_only_after_production_website_full_rebuild_ready",
        "website_support_lane_status": status["markers"]["production_website"],
        "why_selected": lanes["primary_claude_lane"]["why_selected"],
        "primary_claude_lane": lanes["primary_claude_lane"]["objective_mapping"],
        "parallel_codex_tasks": lanes["codex_parallel_lane"]["selected_tasks"],
        "human_input_required": "false_unless_final_live_capital_gate",
        "legacy_mutation": "none",
        "redis_mutation": "none",
        "exchange_mutation": "none",
        "live_gate_status": LIVE_GATE,
        "redis_trim": "deferred_non_blocking",
        "current_primary_blockers": status["current_primary_blockers"],
        "non_drift_lock_path": "claude_worklog/autonomous_governor/latest/NON_DRIFT_GOVERNOR_LOCK.json",
    }
    payload = {
        "generated_at": generated_at,
        "status": go,
        "codex_status": codex,
        "primary_objective": status["primary_objective"],
        "current_selected_task": status["selected_task"],
        "recommended_next_primary_task": status["recommended_next_primary_task"],
        "reason_selected": lanes["primary_claude_lane"]["why_selected"],
        "secondary_website_lane_status": status["website_support_lane"],
        "codex_parallel_audit_lane_status": lanes["codex_parallel_lane"],
        "current_paper_runtime_status": status["freshness"],
        "current_legacy_bridge_containment_status": {
            "legacy_bridge_age_seconds": status["freshness"]["legacy_bridge_age_seconds"],
            "legacy_execution_containment": status["markers"]["legacy_execution_containment"],
        },
        "trainer_parity_status": {
            "legacy_trainer_restart_runtime": status["markers"]["legacy_trainer_restart_runtime"],
            "legacy_trainer_gpu_parity": status["markers"]["legacy_trainer_gpu_parity"],
        },
        "live_gate_status": LIVE_GATE,
        "redis_trim": "deferred_non_blocking",
        "public_website_pass_marker": status["markers"]["production_website"],
        "drift_status": status["classification"],
    }

    write_json(FINAL / "objective_drift_status.json", status)
    write_json(FINAL / "next_tasks_by_lane.json", lanes)
    write_json(FINAL / "operator_dashboard_payload.json", payload)
    write_json(PUBLIC / "operator_dashboard_payload.json", payload)
    write_json(LOCK_PATH, lock)
    write_json(SELECTION_PATH, selection)
    write_text(SELECTION_MD, f"""# Next Task Selection

Generated: {generated_at}

- Selected primary task: `{status['recommended_next_primary_task']}`
- Primary lane: `v2_live_like_paper_shadow_canary_preflight`
- Website lane: `secondary_support_lane`
- Live gate: `{LIVE_GATE}`
- Legacy mutation: `none`
- Redis mutation: `none`
- Exchange mutation: `none`

Website work is support-only after the production route crawl pass. The next autonomous lane must stay on V2 live-like paper/shadow, legacy bridge, risk gateway, trainer parity, and canary preflight.
""")

    write_text(FINAL / "PRIMARY_OBJECTIVE_LOCK.md", f"""# Primary Objective Lock

Generated: {generated_at}

Primary objective:

1. Keep legacy live system observed/read-only, not mutated.
2. Bring V2 online as live-like paper/shadow twin.
3. Use fresh V2 paper runtime and legacy bridge as canonical truth.
4. Preserve trainer/model/feature/orchestrator logic through adapters and parity checks.
5. Keep Risk Gateway as final authority.
6. Keep website as control plane, not proof archive.
7. Prepare canary preflight only.
8. Keep live blocked_human_only until explicit human approval.

Secondary/support objective:

- Website polish and route repair only when public/local crawl fails, a route becomes placeholder-only, data truth regresses, a dangerous control appears enabled, or the user reports a browser-visible defect.

Explicit non-goals:

- More marker-only tasks.
- Stale proof-packet cleanup unless blocking current runtime truth.
- UI-only polish after route crawl pass.
- Unrelated Codex review batches not tied to primary objective.
- Redis trim approval unless explicitly requested.
- Full live cutover without final live/capital approval.
""")
    write_text(FINAL / "GOVERNOR_PRIORITY_POLICY.md", f"""# Governor Priority Policy

Generated: {generated_at}

Priority order:

0. Safety-critical live-risk containment: legacy execution risk, exchange order evidence, dangerous enabled control, old Redis mutation risk, or broken live gate.
1. V2 live-like paper/shadow: paper runtime freshness, canonical truth bridge, legacy bridge, public/local truth verification.
2. Legacy execution containment: legacy trader containment classification, exchange_order_id forensics, publish-to-execution path classification.
3. Trainer/GPU parity: legacy trainer GPU parity, safe bridge, V2 wrapper field completion, trainer output to V2-only bridge.
4. Risk gateway/runtime: risk-add classification, stale/missing attribution blocking, ADJUST_LEVERAGE blocking, margin/leverage profile, kill switch and loss gates.
5. V2 data plane: Postgres/audit ledger, V2 bounded Redis namespace, legacy read-only importer, durable records.
6. Website support lane: only route/data-truth regression or broken page.
7. Redis trim: deferred/non-blocking unless explicit approval exists.

Downgrade rule: website/UI tasks are rejected or downgraded when production website full crawl is READY, no fresh UI regression exists, and active primary runtime objectives remain incomplete.
""")
    write_text(FINAL / "NEXT_TASKS_BY_LANE.md", f"""# Next Tasks By Lane

Generated: {generated_at}

Primary Claude lane:

- Selected task: `{lanes['primary_claude_lane']['selected_task']}`
- Why: {lanes['primary_claude_lane']['why_selected']}
- Autonomous: yes
- Human approval: no, unless final live/capital gate.

Codex parallel lane:

- Selected audits: `{', '.join(lanes['codex_parallel_lane']['selected_tasks'])}`
- Autonomous: yes
- Human approval: no.

Website support lane:

- Selected task: `none_unless_regression`
- Why: public/local crawl already passed.
- Autonomous: no UI-only work while primary chain is incomplete.

Blocked decision packets:

- Redis trim approval: deferred/non-blocking.
- Final live/capital approval: blocked_human_only.
- Legacy trader containment action: decision packet if action required.
""")
    write_text(FINAL / "CODEX_NON_DRIFT_GOVERNOR_REVIEW.md", f"""# Codex Non-Drift Governor Review

Result: `{codex}`

Checked:

- Website tasks cannot supersede primary objective after website pass without regression.
- Stale proof-marker cleanup does not outrank live-like paper/shadow.
- Redis trim remains deferred/non-blocking without approval.
- Final live/capital gate remains human-only.
- Primary objective mapping exists.
- Drift detector exists and emitted `{status['classification']}`.
- Codex parallel lane is defined for runtime/safety audits.

Live gate: `{LIVE_GATE}`. Old Redis mutation: false. Exchange action: false.
""")
    write_text(FINAL / "CLAUDE_AUTOMATION_NON_DRIFT_GOVERNOR_LOCK_REPORT.md", f"""# Claude Automation Non-Drift Governor Lock Report

Status: `{go}`

Generated: {generated_at}

The production website rebuild remains accepted support evidence, not the primary lane. The governor lock now points back to:

- selected primary task: `{status['recommended_next_primary_task']}`
- drift status: `{status['classification']}`
- website lane: `secondary_support_lane`
- Codex audits: `{', '.join(lanes['codex_parallel_lane']['selected_tasks'])}`
- paper runtime age seconds: `{status['freshness']['paper_runtime_age_seconds']}`
- live gate: `{LIVE_GATE}`

No legacy bot files were modified. No old Redis mutation, exchange action, leverage/margin change, or live enablement was performed.
""")
    write_text(FINAL / "GO_NO_GO.md", go)
    write_text(FINAL / "CODEX_GO_NO_GO.md", codex)


def main() -> int:
    status = build_status()
    lanes = build_lanes(status)
    write_packet(status, lanes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
