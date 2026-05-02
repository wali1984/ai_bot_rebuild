"""Agent supervisor reader service — READ ONLY.

Reads the supervisor JSON artifacts produced by
`claude_worklog/tools/agent_supervisor.py` and exposes typed accessors used
by the `/api/v1/_meta/agent-health`, `/_meta/queue-status`,
`/_meta/build-status`, and `/_meta/audit-chain` endpoints.

Read-only contract (CLAUDE.md + 02_IMPLEMENTATION_REPORT.md §1.10):
- never opens any file in a write/append/truncate mode
- never creates or rotates files in `claude_worklog/agent_supervisor/**`
- never touches Redis, exchanges, the legacy bot, or any live runtime
- if a file is missing or unparseable, returns a structured `missing` /
  `unparseable` shape; never raises through the API boundary

Resolution precedence for the supervisor root:
1. explicit `root` argument (used by tests with synthetic fixtures)
2. `V2_SUPERVISOR_ROOT` env var
3. `<repo_root>/claude_worklog/agent_supervisor` derived from this file
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def default_supervisor_root() -> Path:
    here = Path(__file__).resolve()
    repo_root = here.parents[4]
    return repo_root / "claude_worklog" / "agent_supervisor"


def resolve_supervisor_root(override: Path | None = None) -> Path:
    if override is not None:
        return Path(override)
    env = os.environ.get("V2_SUPERVISOR_ROOT", "").strip()
    if env:
        return Path(env)
    return default_supervisor_root()


def _read_json_safe(path: Path) -> tuple[dict[str, Any] | list[Any] | None, str | None]:
    if not path.exists():
        return None, "missing"
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh), None
    except json.JSONDecodeError as exc:
        return None, f"unparseable: {exc.msg}"
    except OSError as exc:
        return None, f"unreadable: {exc.strerror or 'os_error'}"


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _parse_iso_ts(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        v = value.replace("Z", "+00:00") if value.endswith("Z") else value
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _age_seconds(iso_ts: str | None, *, now: datetime | None = None) -> float | None:
    parsed = _parse_iso_ts(iso_ts)
    if parsed is None:
        return None
    n = now or datetime.now(tz=timezone.utc)
    return max(0.0, (n - parsed).total_seconds())


@dataclass(frozen=True)
class SupervisorPaths:
    root: Path

    @property
    def status_dir(self) -> Path:
        return self.root / "status"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def queue_status(self) -> Path:
        return self.status_dir / "queue_status.json"

    @property
    def agent_health(self) -> Path:
        return self.status_dir / "agent_health.json"

    @property
    def heartbeat(self) -> Path:
        return self.status_dir / "supervisor_heartbeat.json"

    @property
    def events_jsonl(self) -> Path:
        return self.root / "events.jsonl"


HEARTBEAT_STALE_S: float = 600.0  # per 02_IMPLEMENTATION_REPORT.md §1.11


def read_queue_status(root: Path | None = None) -> dict[str, Any]:
    paths = SupervisorPaths(resolve_supervisor_root(root))
    value, err = _read_json_safe(paths.queue_status)
    return {
        "_meta": {
            "source": str(paths.queue_status),
            "read_at": _utc_now_iso(),
            "error": err,
        },
        "data": value if isinstance(value, dict) else None,
    }


def read_agent_health(root: Path | None = None) -> dict[str, Any]:
    paths = SupervisorPaths(resolve_supervisor_root(root))

    health_value, health_err = _read_json_safe(paths.agent_health)
    hb_value, hb_err = _read_json_safe(paths.heartbeat)

    last_loop_ts = (
        hb_value.get("last_loop_ts") if isinstance(hb_value, dict) else None
    )
    age = _age_seconds(last_loop_ts) if last_loop_ts else None
    heartbeat_stale = age is not None and age >= HEARTBEAT_STALE_S
    heartbeat_missing = hb_err is not None

    return {
        "_meta": {
            "agent_health_source": str(paths.agent_health),
            "heartbeat_source": str(paths.heartbeat),
            "read_at": _utc_now_iso(),
            "agent_health_error": health_err,
            "heartbeat_error": hb_err,
        },
        "agent_health": health_value if isinstance(health_value, dict) else None,
        "heartbeat": hb_value if isinstance(hb_value, dict) else None,
        "heartbeat_age_s": age,
        "heartbeat_stale": bool(heartbeat_stale),
        "heartbeat_missing": bool(heartbeat_missing),
    }


def _list_run_dirs(runs_dir: Path) -> list[Path]:
    if not runs_dir.exists() or not runs_dir.is_dir():
        return []
    return sorted([p for p in runs_dir.iterdir() if p.is_dir()])


def read_build_status(root: Path | None = None, limit: int = 25) -> dict[str, Any]:
    paths = SupervisorPaths(resolve_supervisor_root(root))
    summaries: list[dict[str, Any]] = []

    for run_dir in _list_run_dirs(paths.runs_dir):
        summary_path = run_dir / "summary.json"
        value, err = _read_json_safe(summary_path)
        entry: dict[str, Any]
        if isinstance(value, dict) and err is None:
            entry = {
                "task_id": value.get("task_id", run_dir.name),
                "agent": value.get("agent"),
                "risk_level": value.get("risk_level"),
                "status": value.get("status"),
                "start_time": value.get("start_time"),
                "end_time": value.get("end_time"),
                "summary": value.get("summary"),
                "materialized_files": value.get("materialized_files", []),
                "timed_out": bool(value.get("timed_out", False)),
                "attention_reason": value.get("attention_reason"),
                "last_retry_reason": value.get("last_retry_reason"),
                "error": None,
            }
        else:
            entry = {
                "task_id": run_dir.name,
                "agent": None,
                "risk_level": None,
                "status": "unknown",
                "start_time": None,
                "end_time": None,
                "summary": None,
                "materialized_files": [],
                "timed_out": False,
                "attention_reason": None,
                "last_retry_reason": None,
                "error": err or "unknown",
            }
        summaries.append(entry)

    def _key(e: dict[str, Any]) -> tuple[float, str]:
        dt = _parse_iso_ts(e.get("start_time"))
        ts = dt.timestamp() if dt else 0.0
        return (ts, str(e.get("task_id", "")))

    summaries.sort(key=_key, reverse=True)
    if limit > 0:
        summaries = summaries[:limit]

    return {
        "_meta": {
            "source": str(paths.runs_dir),
            "read_at": _utc_now_iso(),
            "total_runs": len(_list_run_dirs(paths.runs_dir)),
            "returned": len(summaries),
        },
        "runs": summaries,
    }


def _tail_jsonl(path: Path, limit: int) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    if limit > 0:
        lines = lines[-limit:]
    out: list[dict[str, Any]] = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def read_audit_chain(root: Path | None = None, limit: int = 100) -> dict[str, Any]:
    paths = SupervisorPaths(resolve_supervisor_root(root))
    events = list(_tail_jsonl(paths.events_jsonl, limit=limit))

    last_ts: datetime | None = None
    breaks: list[dict[str, Any]] = []
    for idx, ev in enumerate(events):
        ts_str = ev.get("ts") if isinstance(ev, dict) else None
        cur = _parse_iso_ts(ts_str if isinstance(ts_str, str) else None)
        if cur and last_ts and cur < last_ts:
            breaks.append(
                {
                    "index": idx,
                    "previous_ts": last_ts.isoformat(),
                    "current_ts": cur.isoformat(),
                    "event": ev.get("event"),
                    "task_id": ev.get("task_id"),
                }
            )
        if cur:
            last_ts = cur

    return {
        "_meta": {
            "source": str(paths.events_jsonl),
            "read_at": _utc_now_iso(),
            "exists": paths.events_jsonl.exists(),
            "returned": len(events),
            "limit": limit,
        },
        "events": events,
        "chain_intact": len(breaks) == 0,
        "chain_breaks": breaks,
    }


__all__ = [
    "HEARTBEAT_STALE_S",
    "SupervisorPaths",
    "default_supervisor_root",
    "read_agent_health",
    "read_audit_chain",
    "read_build_status",
    "read_queue_status",
    "resolve_supervisor_root",
]
