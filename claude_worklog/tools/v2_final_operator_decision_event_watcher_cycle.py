"""Run one safe final operator-decision/event-watcher automation cycle."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PYTHON = ROOT / ".venv/bin/python"
OUT = (
    ROOT
    / "claude_worklog/final_readiness/"
    "v2_final_operator_decision_and_event_watcher_execution/latest"
)
PUBLIC = (
    ROOT
    / "v2/frontend/public/"
    "v2_final_operator_decision_and_event_watcher_execution/latest"
)

SAFETY = {
    "live_gate": "blocked_human_only",
    "live_symbols": [],
    "approves_live": False,
    "approves_canary": False,
    "approves_legacy_shutdown": False,
    "approves_redis_trim": False,
    "writes_old_redis": False,
    "calls_exchange_mutation": False,
    "creates_approval_tokens": False,
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def command_plan() -> list[tuple[str, list[str]]]:
    return [
        (
            "production_payload_freshness_refresher",
            [str(PYTHON), "-m", "v2.backend.app.cli.v2_production_payload_freshness_refresher", "--once"],
        ),
        (
            "production_equivalence_comparator",
            [str(PYTHON), "-m", "v2.backend.app.cli.v2_production_equivalence_comparator", "--once"],
        ),
        (
            "runtime_soak_governor",
            [str(PYTHON), "claude_worklog/tools/codex_runtime_soak_and_production_equivalence_governor.py", "--once"],
        ),
        (
            "final_blocker_classifier",
            [str(PYTHON), "claude_worklog/tools/v2_production_equivalence_final_blocker_classification.py", "--json"],
        ),
        (
            "final_blocker_resolution_sprint",
            [str(PYTHON), "claude_worklog/tools/v2_final_production_equivalence_blocker_resolution_sprint.py", "--json"],
        ),
        (
            "final_operator_decision_event_watcher_execution",
            [str(PYTHON), "claude_worklog/tools/v2_final_operator_decision_and_event_watcher_execution.py", "--json"],
        ),
        (
            "report_center_indexer",
            [str(PYTHON), "-m", "v2.backend.app.cli.v2_report_center_indexer", "--once", "--json"],
        ),
    ]


def run_command(label: str, argv: list[str], timeout_seconds: int) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ROOT / 'claude_worklog/tools'}:{ROOT}"
    env["LIVE_GATE"] = "blocked_human_only"
    try:
        proc = subprocess.run(
            argv,
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "label": label,
            "exit_code": 124,
            "ok": False,
            "timeout_seconds": timeout_seconds,
            "timeout": True,
            "stdout_bytes": len(exc.stdout or ""),
            "stderr_bytes": len(exc.stderr or ""),
            "stdout_stored": False,
            "stderr_stored": False,
        }
    return {
        "label": label,
        "exit_code": proc.returncode,
        "ok": proc.returncode == 0,
        "stdout_bytes": len(proc.stdout or ""),
        "stderr_bytes": len(proc.stderr or ""),
        "stdout_stored": False,
        "stderr_stored": False,
    }


def run_once(timeout_seconds: int = 180) -> dict[str, Any]:
    started = utc_iso()
    commands = [run_command(label, argv, timeout_seconds) for label, argv in command_plan()]
    decision_center = read_json(OUT / "final_operator_decision_center.json") or {}
    external_status = read_json(OUT / "external_source_decision_execution_status.json") or {}
    watcher_status = read_json(OUT / "event_dependent_watcher_runtime_status.json") or {}
    recommendation = read_json(OUT / "final_shutdown_recommendation.json") or {}
    report_center = read_json(ROOT / "v2/frontend/public/v2_report_center/latest/report_index.json") or {}
    status = {
        "schema_version": "v2_final_operator_decision_event_watcher_cycle_status_v1",
        "started_utc": started,
        "completed_utc": utc_iso(),
        "go_no_go": (
            "V2_FINAL_OPERATOR_DECISION_EVENT_WATCHER_CYCLE_READY"
            if all(item["ok"] for item in commands)
            else "V2_FINAL_OPERATOR_DECISION_EVENT_WATCHER_CYCLE_BLOCKED"
        ),
        "commands": commands,
        "all_commands_succeeded": all(item["ok"] for item in commands),
        "refreshed_artifacts": [
            "final_operator_decision_center.json",
            "external_source_decision_execution_status.json",
            "event_dependent_watcher_runtime_status.json",
            "final_shutdown_recommendation.json",
            "v2_report_center/latest/report_index.json",
        ],
        "operator_decision_count": decision_center.get("operator_decision_count"),
        "operator_accepted_count": decision_center.get("operator_accepted_count"),
        "external_source_states": [
            item.get("classification")
            for item in external_status.get("items", [])
            if isinstance(item, dict)
        ],
        "event_watcher_count": watcher_status.get("event_watcher_count"),
        "event_watchers_completed": watcher_status.get("completed_watcher_count"),
        "final_recommendation": recommendation.get("final_recommendation"),
        "shutdown_safe": recommendation.get("shutdown_safe"),
        "live_ready": recommendation.get("live_ready"),
        "report_center_generated_at": report_center.get("generated_at"),
        "safety": SAFETY,
    }
    write_json(OUT / "automation_cycle_status.json", status)
    PUBLIC.mkdir(parents=True, exist_ok=True)
    shutil.copy2(OUT / "automation_cycle_status.json", PUBLIC / "automation_cycle_status.json")
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args(argv)
    status = run_once(timeout_seconds=args.timeout_seconds)
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["all_commands_succeeded"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
