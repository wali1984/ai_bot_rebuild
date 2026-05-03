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
