#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


WORKSPACE = Path(__file__).resolve().parents[2]
STATE_DIR = WORKSPACE / "claude_worklog/agent_supervisor/state/tasks"
STATUS_DIR = WORKSPACE / "claude_worklog/agent_supervisor/status"
EVENTS = WORKSPACE / "claude_worklog/agent_supervisor/events.jsonl"

Evidence = Tuple[str, str, List[str]]

EVIDENCE_MARKERS: List[Evidence] = [
    (
        "PHASE2F_A_ORCHESTRATOR_DECISION_DOMAIN_IMPL_AND_VALIDATION_PASSED",
        "claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/07_2F_A_ORCHESTRATOR_DECISION_DOMAIN_GO_NO_GO.md",
        [
            "117_orchestrator_decision_2fa_domain_implementation",
            "codex_recover_117_orchestrator_decision_2fa_domain_implementation",
        ],
    ),
    (
        "PHASE2E3C_TRAINER_PREDICTION_OUTPUT_COMPOSITION_ROOT_CODEX_PASS",
        "claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/205_2E3C_PREDICTION_OUTPUT_COMPOSITION_ROOT_CODEX_GO_NO_GO.md",
        [
            "116_trainer_parity_2e3c_prediction_output_composition_root_codex_review",
        ],
    ),
    (
        "PHASE2E3C_TRAINER_PREDICTION_OUTPUT_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED",
        "claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/203_2E3C_PREDICTION_OUTPUT_COMPOSITION_ROOT_GO_NO_GO.md",
        [
            "115_trainer_parity_2e3c_prediction_output_composition_root_implementation",
            "codex_recover_115_trainer_parity_2e3c_prediction_output_composition_root_implementation",
        ],
    ),
    (
        "PHASE2E3B_TRAINER_PREDICTION_RECORD_ASSEMBLER_CODEX_PASS",
        "claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/197_2E3B_PREDICTION_RECORD_ASSEMBLER_CODEX_GO_NO_GO.md",
        [
            "113_trainer_parity_2e3b_prediction_record_assembler_implementation",
            "114_trainer_parity_2e3b_prediction_record_assembler_codex_review",
            "codex_recover_114_trainer_parity_2e3b_prediction_record_assembler_codex_review",
        ],
    ),
    (
        "PHASE2E3B_TRAINER_PREDICTION_RECORD_ASSEMBLER_IMPL_AND_VALIDATION_PASSED",
        "claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/195_2E3B_PREDICTION_RECORD_ASSEMBLER_GO_NO_GO.md",
        [
            "113_trainer_parity_2e3b_prediction_record_assembler_implementation",
        ],
    ),
    (
        "PHASE2E3A_TRAINER_PREDICTION_OUTPUT_DOMAIN_CODEX_REREVIEW_AFTER_DIRTY_TREE_CLEAN_PASS",
        "claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/189_2E3A_CODEX_REREVIEW_AFTER_DIRTY_TREE_CLEAN_GO_NO_GO.md",
        [
            "110_trainer_parity_2e3a_prediction_output_domain_implementation",
            "111_trainer_parity_2e3a_prediction_output_domain_codex_review",
            "112_trainer_parity_2e3a_codex_rereview_after_dirty_tree_clean",
        ],
    ),
    (
        "PHASE2E1C_GAMMA_TRAINER_PARITY_IMPL_CODEX_PASS",
        "claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/95_2E1C_GAMMA_CODEX_GO_NO_GO.md",
        [
            "083_trainer_parity_2e1c_gamma_codex_review",
        ],
    ),
    (
        "PHASE2E1C_GAMMA_TRAINER_PARITY_IMPL_AND_VALIDATION_PASSED",
        "claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/92_2E1C_GAMMA_GO_NO_GO.md",
        [
            "082_trainer_parity_2e1c_gamma_implementation",
            "084_codex_recover_planner_gamma_materialization_blocker",
            "086",
            "086A_trainer_parity_2e1c_gamma_reader_protocol",
            "086B_trainer_parity_2e1c_gamma_observation_collector",
            "086C_trainer_parity_2e1c_gamma_observation_history",
        ],
    ),
    (
        "PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS",
        "claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/69_2E1C_BETA_FINAL_CODEX_GO_NO_GO.md",
        [
            "066_trainer_parity_2e1c_beta_codex_review",
            "077_trainer_parity_2e1c_beta_codex_rereview_after_remediation",
            "078_trainer_parity_2e1c_beta_final_codex_rereview",
        ],
    ),
    (
        "CODEX_064_HUMAN_ATTENTION_RECOVERY_READY",
        "claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/076_CODEX_RECOVERY_064_GO_NO_GO.md",
        [
            "064_trainer_parity_2e1c_beta_implementation",
            "076_codex_recover_064_human_attention",
        ],
    ),
    (
        "CODEX_PARALLEL_TRAINER_LIVENESS_AUTOFIX_PASS",
        "claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/74_CODEX_PARALLEL_REREVIEW_TRAINER_LIVENESS_AUTOFIX_GO_NO_GO.md",
        [
            "060_trainer_parity_2e1c_alpha_implementation",
            "060c_trainer_liveness_validation_docs",
            "069_codex_parallel_review_trainer_liveness_stack",
            "072_codex_parallel_autofix_trainer_liveness_worker_dead",
            "073_codex_parallel_rereview_trainer_liveness_autofix",
        ],
    ),
    (
        "PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS",
        "claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/34_2E1B_CODEX_GO_NO_GO.md",
        [
            "056_trainer_parity_2e1b_implementation",
            "057_trainer_parity_2e1b_codex_review",
        ],
    ),
    (
        "015F_CODEX_REVIEW_PASS",
        "claude_worklog/v2_scaffold_reviews/025_CODEX_GO_NO_GO_015F.md",
        [
            "025_codex_review_015f_agent_dashboard_integration",
        ],
    ),
    (
        "FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW",
        "claude_worklog/final_readiness/04_GO_NO_GO.md",
        [
            "010_actual_codex_architecture_rerun_after_remediation",
        ],
    ),
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_text(path: Path, limit: int = 20000) -> str:
    try:
        return path.read_text(errors="replace")[:limit]
    except FileNotFoundError:
        return ""


def append_event(event: dict) -> None:
    EVENTS.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(event)
    payload.setdefault("ts", now())
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def load_state(task_id: str) -> dict:
    p = STATE_DIR / f"{task_id}.json"
    if not p.exists():
        return {"task_id": task_id, "history": []}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"task_id": task_id, "history": []}


def save_state(task_id: str, state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / f"{task_id}.json").write_text(json.dumps(state, indent=2) + "\n")


def process_alive(pid: object) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def active_process_mentions(task_id: str) -> bool:
    result = subprocess.run(
        ["bash", "-lc", f"pgrep -af {task_id!r} || true"],
        cwd=WORKSPACE,
        text=True,
        capture_output=True,
        check=False,
    )
    lines = []
    for line in result.stdout.splitlines():
        if "pgrep -af" in line:
            continue
        if "reconcile_evidence_status.py" in line:
            continue
        lines.append(line)
    return bool(lines)


def marker_present(marker: str, relpath: str) -> bool:
    return marker in read_text(WORKSPACE / relpath)


def reconcile() -> dict:
    generated_at = now()
    found: Dict[str, dict] = {}
    superseded: Dict[str, str] = {}

    for marker, relpath, task_ids in EVIDENCE_MARKERS:
        if marker_present(marker, relpath):
            found[marker] = {
                "path": relpath,
                "supersedes": task_ids,
            }
            for task_id in task_ids:
                superseded[task_id] = marker

    for task_id, marker in sorted(superseded.items()):
        state = load_state(task_id)
        if state.get("status") == "running" and (
            process_alive(state.get("run_pid")) or active_process_mentions(task_id)
        ):
            continue

        hist = list(state.get("history") or [])
        hist.append(
            {
                "ts": generated_at,
                "status": "superseded_by_evidence",
                "reason": marker,
            }
        )
        state.update(
            {
                "task_id": task_id,
                "status": "superseded_by_evidence",
                "superseded_by_evidence": marker,
                "last_summary": f"Superseded by committed evidence marker: {marker}",
                "last_status_change_ts": generated_at,
                "last_event_ts": generated_at,
                "history": hist[-50:],
            }
        )
        save_state(task_id, state)
        append_event(
            {
                "event": "task_state_superseded_by_evidence",
                "task_id": task_id,
                "marker": marker,
            }
        )

    report = {
        "generated_at": generated_at,
        "found_markers": found,
        "superseded_tasks": superseded,
        "policy": "evidence_first_status_reconciliation",
    }

    STATUS_DIR.mkdir(parents=True, exist_ok=True)
    (STATUS_DIR / "evidence_reconciliation_status.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    print(json.dumps(reconcile(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
