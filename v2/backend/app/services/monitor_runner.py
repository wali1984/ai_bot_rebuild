"""V2 script monitor service.

Static monitor for V2 worker scripts. The service inspects V2-owned files and
payloads only; it never executes legacy scripts and never calls Redis or an
exchange.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


ACTIVE = "active"
BROKEN = "broken"
UNUSED = "unused"
DUPLICATE = "duplicate"
UNKNOWN = "unknown"
STATUSES = (ACTIVE, BROKEN, UNUSED, DUPLICATE, UNKNOWN)


@dataclass(frozen=True)
class ScriptStatus:
    worker_id: str
    script_path: str
    status: str
    last_run: Optional[str]
    last_success: Optional[str]
    last_failure: Optional[str]
    metrics_emitted: bool
    alerts: List[str]
    has_main_guard: bool
    has_argparse: bool
    public_payload_path: str
    task_descriptor_path: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _worker_id_from_cli(path: Path) -> str:
    return path.stem


def _payload_last_run(payload: Mapping[str, Any]) -> Optional[str]:
    for key in ("last_run_ts", "generated_at", "codex_review_emitted_at"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _is_failure_payload(payload: Mapping[str, Any]) -> bool:
    if payload.get("fail_closed") is True:
        return True
    status = str(payload.get("runtime_evidence_status") or "").upper()
    return status.startswith("INVALID") or status.startswith("MISSING")


def _classify_script(
    *,
    worker_id: str,
    script_path: Path,
    repo_root: Path,
    duplicate_worker_ids: Sequence[str],
    public_payload: Optional[Mapping[str, Any]],
    task_descriptor_exists: bool,
) -> ScriptStatus:
    text = script_path.read_text(errors="replace")
    has_main_guard = 'if __name__ == "__main__"' in text or "if __name__ == '__main__'" in text
    has_argparse = "argparse" in text
    alerts: List[str] = []
    status = UNKNOWN
    last_run: Optional[str] = None
    last_success: Optional[str] = None
    last_failure: Optional[str] = None
    metrics_emitted = False

    if duplicate_worker_ids.count(worker_id) > 1:
        status = DUPLICATE
        alerts.append("duplicate_worker_id")
    elif "placeholder" in text.lower() and len(text.strip()) < 400:
        status = BROKEN
        alerts.append("placeholder_or_stub")
    elif not has_main_guard:
        status = BROKEN
        alerts.append("missing_main_guard")
    elif not has_argparse:
        status = BROKEN
        alerts.append("missing_argparse_cli")
    elif public_payload:
        last_run = _payload_last_run(public_payload)
        metrics_emitted = True
        if _is_failure_payload(public_payload):
            status = BROKEN
            last_failure = last_run
            alerts.append("public_payload_fail_closed_or_missing_evidence")
        else:
            status = ACTIVE
            last_success = last_run
    elif task_descriptor_exists:
        status = UNKNOWN
        alerts.append("task_descriptor_present_payload_missing")
    else:
        status = UNUSED
        alerts.append("no_task_descriptor_or_public_payload")

    public_payload_path = (
        repo_root
        / "v2"
        / "frontend"
        / "public"
        / "operator_runtime"
        / worker_id
        / "latest"
        / f"{worker_id}_status.json"
    )
    task_descriptor_path = (
        repo_root / "claude_worklog" / "agent_supervisor" / "tasks" / f"claude_port_{worker_id}.json"
    )
    return ScriptStatus(
        worker_id=worker_id,
        script_path=_rel(script_path, repo_root),
        status=status,
        last_run=last_run,
        last_success=last_success,
        last_failure=last_failure,
        metrics_emitted=metrics_emitted,
        alerts=alerts,
        has_main_guard=has_main_guard,
        has_argparse=has_argparse,
        public_payload_path=_rel(public_payload_path, repo_root),
        task_descriptor_path=_rel(task_descriptor_path, repo_root),
    )


def enumerate_v2_worker_scripts(cli_dir: Path) -> List[Path]:
    if not cli_dir.exists():
        return []
    return sorted(
        path
        for path in cli_dir.glob("v2_*.py")
        if path.is_file() and path.name != "__init__.py"
    )


def collect_script_statuses(
    *,
    repo_root: Path,
    cli_dir: Optional[Path] = None,
    public_runtime_root: Optional[Path] = None,
    task_dir: Optional[Path] = None,
) -> List[ScriptStatus]:
    cli_dir = cli_dir or repo_root / "v2" / "backend" / "app" / "cli"
    public_runtime_root = public_runtime_root or repo_root / "v2" / "frontend" / "public" / "operator_runtime"
    task_dir = task_dir or repo_root / "claude_worklog" / "agent_supervisor" / "tasks"
    scripts = enumerate_v2_worker_scripts(cli_dir)
    worker_ids = [_worker_id_from_cli(path) for path in scripts]
    statuses: List[ScriptStatus] = []
    for script in scripts:
        worker_id = _worker_id_from_cli(script)
        payload_path = public_runtime_root / worker_id / "latest" / f"{worker_id}_status.json"
        payload = _read_json(payload_path)
        payload_map = payload if isinstance(payload, dict) else None
        task_descriptor_exists = (task_dir / f"claude_port_{worker_id}.json").exists()
        statuses.append(
            _classify_script(
                worker_id=worker_id,
                script_path=script,
                repo_root=repo_root,
                duplicate_worker_ids=worker_ids,
                public_payload=payload_map,
                task_descriptor_exists=task_descriptor_exists,
            )
        )
    return statuses


def summarize_statuses(statuses: Iterable[ScriptStatus]) -> Dict[str, Any]:
    records = [status.to_dict() for status in statuses]
    by_status = {status: 0 for status in STATUSES}
    for record in records:
        by_status[str(record["status"])] = by_status.get(str(record["status"]), 0) + 1
    return {
        "scripts": records,
        "scripts_enumerated_total": len(records),
        "scripts_by_status": by_status,
        "scripts_broken": [r for r in records if r["status"] == BROKEN],
        "scripts_unused": [r for r in records if r["status"] == UNUSED],
        "alerts_generated": [
            {"worker_id": r["worker_id"], "alerts": r["alerts"]}
            for r in records
            if r["alerts"]
        ],
    }


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
