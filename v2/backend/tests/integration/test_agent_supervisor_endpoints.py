"""Integration tests for the agent-supervisor reader endpoints.

These tests synthesize a temporary supervisor artifact tree under tmp_path,
point `V2_SUPERVISOR_ROOT` at it, and exercise the four endpoints through
the FastAPI app via TestClient. No legacy bot, Redis, exchange, or live
runtime is touched.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _materialize_supervisor_tree(
    root: Path,
    *,
    heartbeat_age_s: int = 30,
    queue: dict[str, Any] | None = None,
    runs: list[dict[str, Any]] | None = None,
    events: list[dict[str, Any]] | None = None,
) -> None:
    status_dir = root / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(tz=timezone.utc)
    last_loop = now - timedelta(seconds=heartbeat_age_s)

    (status_dir / "supervisor_heartbeat.json").write_text(
        json.dumps(
            {
                "pid": 12345,
                "tmux_session": "%99",
                "loop_count": 7,
                "last_loop_ts": _utc_iso(last_loop),
                "current_task": "synthetic_task",
                "last_event_ts": _utc_iso(last_loop),
                "started_at": _utc_iso(last_loop - timedelta(minutes=5)),
                "version": "2.0-reliability-hardened",
            }
        ),
        encoding="utf-8",
    )

    (status_dir / "agent_health.json").write_text(
        json.dumps(
            {
                "generated_at": _utc_iso(now),
                "terminal_operator": "test",
                "active_agents": ["Claude", "Codex", "Ollama"],
                "claude": {"ready_marker": True},
                "codex": {"ready_marker": True},
                "ollama": {"model_count": 1, "models": ["qwen2.5-coder:7b"]},
                "last_auto_commit_hash": None,
                "supervisor_version": "2.0-reliability-hardened",
            }
        ),
        encoding="utf-8",
    )

    queue_payload = queue if queue is not None else {
        "generated_at": _utc_iso(now),
        "next_pending_task": None,
        "current_running_task": "synthetic_task",
        "blocked_quota": None,
        "stale_running_count": 0,
        "stale_running_tasks": [],
        "no_event_count": 0,
        "no_event_tasks": [],
        "no_output_growth_count": 0,
        "no_output_growth_tasks": [],
        "human_attention_required_count": 0,
        "human_attention_required_tasks": [],
        "counts": {
            "pending": 0, "running": 1, "completed": 0, "failed": 0,
            "blocked": 0, "retry_scheduled": 0, "skipped": 0, "cancelled": 0,
            "human_attention_required": 0,
        },
        "gate": "READY_FOR_SCAFFOLD_PLANNING",
    }
    (status_dir / "queue_status.json").write_text(json.dumps(queue_payload), encoding="utf-8")

    runs_payload = runs if runs is not None else [
        {
            "task_id": "001_demo",
            "agent": "claude",
            "risk_level": "L2",
            "status": "completed",
            "start_time": _utc_iso(now - timedelta(minutes=10)),
            "end_time": _utc_iso(now - timedelta(minutes=5)),
            "summary": "demo run",
            "materialized_files": ["v2/example.txt"],
            "timed_out": False,
            "attention_reason": None,
            "last_retry_reason": None,
        }
    ]
    for r in runs_payload:
        rd = runs_dir / r["task_id"]
        rd.mkdir(parents=True, exist_ok=True)
        (rd / "summary.json").write_text(json.dumps(r), encoding="utf-8")

    events_payload = events if events is not None else [
        {"event": "task_running", "task_id": "001_demo", "ts": _utc_iso(now - timedelta(minutes=10))},
        {"event": "task_completed", "task_id": "001_demo", "ts": _utc_iso(now - timedelta(minutes=5))},
    ]
    (root / "events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events_payload) + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def supervisor_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "agent_supervisor"
    _materialize_supervisor_tree(root)
    monkeypatch.setenv("V2_SUPERVISOR_ROOT", str(root))
    return root


@pytest.fixture
def client(supervisor_root: Path) -> TestClient:
    return TestClient(create_app())


# --------------------------------------------------------------------- #
# /_meta/agent-health
# --------------------------------------------------------------------- #

def test_agent_health_returns_heartbeat_and_health(client: TestClient) -> None:
    res = client.get("/api/v1/_meta/agent-health")
    assert res.status_code == 200
    body = res.json()
    assert body["heartbeat"] is not None
    assert body["agent_health"] is not None
    assert body["heartbeat"]["pid"] == 12345
    assert body["heartbeat_missing"] is False
    assert body["heartbeat_stale"] is False
    assert body["heartbeat_age_s"] is not None and body["heartbeat_age_s"] < 600


def test_agent_health_flags_stale_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "supervisor"
    _materialize_supervisor_tree(root, heartbeat_age_s=900)
    monkeypatch.setenv("V2_SUPERVISOR_ROOT", str(root))
    client = TestClient(create_app())

    res = client.get("/api/v1/_meta/agent-health")
    body = res.json()
    assert body["heartbeat_stale"] is True
    assert body["heartbeat_age_s"] >= 600


def test_agent_health_handles_missing_heartbeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "supervisor"
    (root / "status").mkdir(parents=True)
    monkeypatch.setenv("V2_SUPERVISOR_ROOT", str(root))
    client = TestClient(create_app())

    res = client.get("/api/v1/_meta/agent-health")
    assert res.status_code == 200
    body = res.json()
    assert body["heartbeat"] is None
    assert body["heartbeat_missing"] is True
    assert body["heartbeat_stale"] is False


# --------------------------------------------------------------------- #
# /_meta/queue-status
# --------------------------------------------------------------------- #

def test_queue_status_passes_through_payload(client: TestClient) -> None:
    res = client.get("/api/v1/_meta/queue-status")
    assert res.status_code == 200
    body = res.json()
    assert body["data"] is not None
    assert body["data"]["current_running_task"] == "synthetic_task"
    assert body["data"]["counts"]["running"] == 1
    assert body["_meta"]["error"] is None


def test_queue_status_surfaces_alert_arrays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "supervisor"
    queue = {
        "generated_at": _utc_iso(datetime.now(tz=timezone.utc)),
        "next_pending_task": None,
        "current_running_task": "stuck_task",
        "blocked_quota": {
            "task_id": "quota_task",
            "agent": "claude",
            "resume_after_utc": _utc_iso(datetime.now(tz=timezone.utc)),
        },
        "stale_running_count": 1,
        "stale_running_tasks": ["stuck_task"],
        "no_event_count": 1,
        "no_event_tasks": ["silent_task"],
        "no_output_growth_count": 1,
        "no_output_growth_tasks": ["frozen_task"],
        "human_attention_required_count": 1,
        "human_attention_required_tasks": [
            {
                "task_id": "broken_task",
                "agent": "claude",
                "attention_reason": "max_attempts_exhausted_stale_running",
                "last_summary": "retries exhausted",
            }
        ],
        "counts": {
            "pending": 0, "running": 1, "completed": 0, "failed": 0,
            "blocked": 1, "retry_scheduled": 0, "skipped": 0, "cancelled": 0,
            "human_attention_required": 1,
        },
        "gate": "BLOCKED_HUMAN_ATTENTION_REQUIRED",
    }
    _materialize_supervisor_tree(root, queue=queue)
    monkeypatch.setenv("V2_SUPERVISOR_ROOT", str(root))
    client = TestClient(create_app())

    res = client.get("/api/v1/_meta/queue-status")
    body = res.json()["data"]
    assert body["stale_running_tasks"] == ["stuck_task"]
    assert body["no_event_tasks"] == ["silent_task"]
    assert body["no_output_growth_tasks"] == ["frozen_task"]
    assert body["blocked_quota"]["task_id"] == "quota_task"
    assert body["human_attention_required_tasks"][0]["task_id"] == "broken_task"


def test_queue_status_handles_missing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "empty"
    (root / "status").mkdir(parents=True)
    monkeypatch.setenv("V2_SUPERVISOR_ROOT", str(root))
    client = TestClient(create_app())

    res = client.get("/api/v1/_meta/queue-status")
    assert res.status_code == 200
    body = res.json()
    assert body["data"] is None
    assert body["_meta"]["error"] == "missing"


# --------------------------------------------------------------------- #
# /_meta/build-status
# --------------------------------------------------------------------- #

def test_build_status_returns_summaries_sorted_desc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "supervisor"
    now = datetime.now(tz=timezone.utc)
    runs = [
        {
            "task_id": "older_task",
            "agent": "claude",
            "risk_level": "L1",
            "status": "completed",
            "start_time": _utc_iso(now - timedelta(hours=2)),
            "end_time": _utc_iso(now - timedelta(hours=1, minutes=55)),
            "summary": "older",
            "materialized_files": [],
            "timed_out": False,
            "attention_reason": None,
            "last_retry_reason": None,
        },
        {
            "task_id": "newer_task",
            "agent": "codex",
            "risk_level": "L2",
            "status": "completed",
            "start_time": _utc_iso(now - timedelta(minutes=5)),
            "end_time": _utc_iso(now - timedelta(minutes=2)),
            "summary": "newer",
            "materialized_files": ["v2/foo.py"],
            "timed_out": False,
            "attention_reason": None,
            "last_retry_reason": None,
        },
    ]
    _materialize_supervisor_tree(root, runs=runs)
    monkeypatch.setenv("V2_SUPERVISOR_ROOT", str(root))
    client = TestClient(create_app())

    res = client.get("/api/v1/_meta/build-status")
    assert res.status_code == 200
    body = res.json()
    assert body["_meta"]["returned"] == 2
    assert [r["task_id"] for r in body["runs"]] == ["newer_task", "older_task"]
    assert body["runs"][0]["agent"] == "codex"


def test_build_status_respects_limit_query(client: TestClient) -> None:
    res = client.get("/api/v1/_meta/build-status?limit=1")
    assert res.status_code == 200
    body = res.json()
    assert body["_meta"]["returned"] <= 1


def test_build_status_includes_unparseable_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "supervisor"
    _materialize_supervisor_tree(root)
    bad = root / "runs" / "broken_task"
    bad.mkdir()
    (bad / "summary.json").write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv("V2_SUPERVISOR_ROOT", str(root))
    client = TestClient(create_app())

    res = client.get("/api/v1/_meta/build-status")
    body = res.json()
    ids = {r["task_id"]: r for r in body["runs"]}
    assert "broken_task" in ids
    assert ids["broken_task"]["error"] is not None


# --------------------------------------------------------------------- #
# /_meta/audit-chain
# --------------------------------------------------------------------- #

def test_audit_chain_returns_intact_chain(client: TestClient) -> None:
    res = client.get("/api/v1/_meta/audit-chain")
    assert res.status_code == 200
    body = res.json()
    assert body["chain_intact"] is True
    assert body["chain_breaks"] == []
    assert body["_meta"]["returned"] == 2


def test_audit_chain_detects_break(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "supervisor"
    now = datetime.now(tz=timezone.utc)
    events = [
        {"event": "a", "task_id": "t1", "ts": _utc_iso(now - timedelta(minutes=5))},
        {"event": "b", "task_id": "t1", "ts": _utc_iso(now - timedelta(minutes=10))},
    ]
    _materialize_supervisor_tree(root, events=events)
    monkeypatch.setenv("V2_SUPERVISOR_ROOT", str(root))
    client = TestClient(create_app())

    res = client.get("/api/v1/_meta/audit-chain")
    body = res.json()
    assert body["chain_intact"] is False
    assert body["chain_breaks"][0]["index"] == 1
    assert body["chain_breaks"][0]["task_id"] == "t1"


def test_audit_chain_missing_events_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "supervisor"
    (root / "status").mkdir(parents=True)
    monkeypatch.setenv("V2_SUPERVISOR_ROOT", str(root))
    client = TestClient(create_app())

    res = client.get("/api/v1/_meta/audit-chain")
    assert res.status_code == 200
    body = res.json()
    assert body["events"] == []
    assert body["chain_intact"] is True
    assert body["_meta"]["exists"] is False


# --------------------------------------------------------------------- #
# Read-only contract
# --------------------------------------------------------------------- #

def test_endpoints_do_not_mutate_supervisor_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "supervisor"
    _materialize_supervisor_tree(root)
    monkeypatch.setenv("V2_SUPERVISOR_ROOT", str(root))
    client = TestClient(create_app())

    def snapshot() -> dict[str, tuple[int, float]]:
        out: dict[str, tuple[int, float]] = {}
        for p in root.rglob("*"):
            if p.is_file():
                st = p.stat()
                out[str(p.relative_to(root))] = (st.st_size, st.st_mtime)
        return out

    before = snapshot()
    for path in (
        "/api/v1/_meta/agent-health",
        "/api/v1/_meta/queue-status",
        "/api/v1/_meta/build-status",
        "/api/v1/_meta/audit-chain",
    ):
        assert client.get(path).status_code == 200
    after = snapshot()

    assert before == after, (
        "agent-supervisor reader mutated the supervisor tree; "
        f"diff={set(after.items()) ^ set(before.items())}"
    )
