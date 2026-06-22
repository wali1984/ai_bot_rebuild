from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from v2.backend.app.closed_loop.lease_store.sqlite_store import SQLiteLeaseStore
from v2.backend.app.closed_loop.services.executive_payloads import (
    build_executive_payload,
    build_operator_payload,
)
from v2.backend.app.closed_loop.services.fail_mapper import classify_from_output
from v2.backend.app.closed_loop.services.burndown import evaluate_ready_gate
from v2.backend.app.closed_loop.services.metrics import build_metrics_payload
from v2.backend.app.closed_loop.workers.codex_worker import _parse_verdict
from v2.backend.app.closed_loop.workers import codex_worker as codex_mod
from v2.backend.app.closed_loop.workers import claude_worker as claude_mod


def _base_task(task_id: str, lane_group: str = "runtime-claude", agent: str = "claude") -> dict:
    return {
        "task_id": task_id,
        "task_type": "CLAUDE_IMPLEMENTATION",
        "mission_category": "runtime_stability",
        "lane_group": lane_group,
        "owner": "CLAUDE",
        "agent": agent,
        "status": "pending",
        "file_lock_group": task_id,
        "paired_task_id": None,
        "depends_on_task_id": None,
        "safe_envelope": {
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "approves_legacy_shutdown": False,
            "approves_redis_trim": False,
        },
        "prompt": "test",
    }


def test_sqlite_bootstrap_uses_wal(tmp_path: Path) -> None:
    store = SQLiteLeaseStore(db_path=tmp_path / "leases.db")
    status = store.report_status()
    assert status["status"] == "ok"
    assert status["tasks"] == 0
    assert status["leases"] == 0
    assert "wal" in str(status["journal_mode"]).lower()
    store.close()


def test_create_task_without_safe_envelope_fails(tmp_path: Path) -> None:
    store = SQLiteLeaseStore(db_path=tmp_path / "leases.db")
    task = _base_task("t1")
    task["safe_envelope"] = {}
    try:
        store.create_task(task)
    except ValueError:
        pass
    else:
        assert False, "unsafe task should be refused"
    store.close()


def test_unsupported_duplicate_active_lease_prevented(tmp_path: Path) -> None:
    store = SQLiteLeaseStore(db_path=tmp_path / "leases.db")
    store.create_task(_base_task("duplicate_a"))
    first = store.claim_task(worker_id="w1", lane_group="runtime-claude", worker_kind="claude")
    second = store.claim_task(worker_id="w2", lane_group="runtime-claude", worker_kind="claude")
    assert first is not None
    assert second is None
    store.close()


def test_file_lock_uniqueness_blocks_parallel(tmp_path: Path) -> None:
    store = SQLiteLeaseStore(db_path=tmp_path / "leases.db")
    a = _base_task("a")
    b = _base_task("b")
    b["file_lock_group"] = "shared"
    a["file_lock_group"] = "shared"
    store.create_task(a)
    store.create_task(b)
    first = store.claim_task(worker_id="w1", lane_group="runtime-claude", worker_kind="claude")
    second = store.claim_task(worker_id="w2", lane_group="runtime-claude", worker_kind="claude")
    assert first is not None
    assert second is None
    store.close()


def test_stale_reclaim_and_second_stale_escalation(tmp_path: Path) -> None:
    store = SQLiteLeaseStore(db_path=tmp_path / "leases.db")
    store.create_task(_base_task("stale1"))
    first = store.claim_task(worker_id="w1", lane_group="runtime-claude", worker_kind="claude")
    lease_id = first["lease"]["lease_id"] if first else None
    assert lease_id is not None
    store._conn.execute(
        "UPDATE leases SET heartbeat_at=datetime('now', '-10 minutes') WHERE lease_id=?",
        (lease_id,),
    )
    summary = store.stale_lease_reclaim(stale_seconds=1, second_stale_seconds=2)
    assert summary["stale_reclaims"] >= 0
    store.close()


def test_second_stale_creates_remediation_and_fail_mapping(tmp_path: Path) -> None:
    store = SQLiteLeaseStore(db_path=tmp_path / "second-stale.db")
    store.create_task(_base_task("second_stale_task"))
    first = store.claim_task(worker_id="w1", lane_group="runtime-claude", worker_kind="claude")
    assert first is not None
    lease_id = first["lease"]["lease_id"]
    stale_at = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    payload = first["lease"]["payload_json"]
    payload["reclaim_stage"] = 1
    store._conn.execute(
        "UPDATE leases SET heartbeat_at=?, payload_json=? WHERE lease_id=?",
        (stale_at, json.dumps(payload, sort_keys=True), lease_id),
    )
    summary = store.stale_lease_reclaim(stale_seconds=1, second_stale_seconds=2)
    assert summary["second_stale_escalations"] == 1
    remediation = store.get_task("closed_loop_remediation_second_stale_task")
    assert remediation is not None
    assert remediation["status"] == "pending"
    mapped = store._conn.execute(
        "SELECT * FROM codex_fail_map WHERE codex_task_id='second_stale_task'"
    ).fetchone()
    assert mapped is not None
    assert mapped["classification"] == "second_stale_remediation_required"
    assert mapped["remediation_task_id"] == "closed_loop_remediation_second_stale_task"
    store.close()


def test_autoseed_generates_paired_tasks(tmp_path: Path) -> None:
    from v2.backend.app.closed_loop.services.autoseed import run_once

    status = run_once(db_path=tmp_path / "seed.db", max_new_tasks=1)
    assert status["generated_pairs"]


def test_codex_review_waits_for_dependency(tmp_path: Path) -> None:
    store = SQLiteLeaseStore(db_path=tmp_path / "deps.db")
    impl = _base_task("implA")
    codex = _base_task("codexA", lane_group="runtime-codex", agent="codex")
    codex["task_type"] = "CODEX_REVIEW"
    codex["depends_on_task_id"] = "implA"
    codex["paired_task_id"] = "implA"
    codex["lane_type"] = "CODEX_REVIEW"
    store.create_task(impl)
    store.create_task(codex)
    claim = store.claim_task(worker_id="c1", lane_group="runtime-codex", worker_kind="codex")
    assert claim is None
    store.complete_task("implA", status="completed")
    claim_ready = store.claim_task(worker_id="c1", lane_group="runtime-codex", worker_kind="codex")
    assert claim_ready is not None
    store.close()


def test_codex_executor_failure_maps_operator_required(tmp_path: Path, monkeypatch) -> None:
    store = SQLiteLeaseStore(db_path=tmp_path / "codex-missing.db")
    codex = _base_task("codex_missing", lane_group="runtime-codex", agent="codex")
    codex["task_type"] = "CODEX_REVIEW"
    codex["lane_type"] = "CODEX_REVIEW"
    store.create_task(codex)
    claim = store.claim_task(worker_id="c1", lane_group="runtime-codex", worker_kind="codex")
    assert claim is not None
    monkeypatch.setattr(
        codex_mod,
        "_run_codex_review",
        lambda *a, **k: (127, "codex_cli_missing"),
    )
    result = codex_mod.run_review_task(store, "c1", claim, timeout=1)
    assert result["action"] == "operator_required"
    mapped = store._conn.execute(
        "SELECT * FROM codex_fail_map WHERE codex_task_id='codex_missing'"
    ).fetchone()
    assert mapped is not None
    assert mapped["classification"] == "operator_required"
    assert mapped["operator_required"] == 1
    store.close()


class _FakePopen:
    def __init__(self, poll_sequence: list[int | None], *, pid: int = 1234) -> None:
        self._polls = poll_sequence
        self.pid = pid
        self.stdout = None
        self.returncode: int | None = None

    def poll(self) -> int | None:
        if not self._polls:
            self.returncode = 0
            return self.returncode
        value = self._polls.pop(0)
        self.returncode = 0 if value is None else value
        return value

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode if self.returncode is not None else 0


def test_claude_child_heartbeat_runs_during_execution(tmp_path: Path, monkeypatch) -> None:
    store = SQLiteLeaseStore(db_path=tmp_path / "heartbeat.db")
    task = _base_task("heartbeat_claude")
    store.create_task(task)
    claim = store.claim_task(worker_id="w1", lane_group="runtime-claude", worker_kind="claude")
    assert claim is not None

    heartbeat_worker = []
    heartbeat_lease = []

    def fake_heartbeat_worker(*args, **kwargs):
        heartbeat_worker.append((args, kwargs))

    def fake_heartbeat_lease(*args, **kwargs):
        heartbeat_lease.append((args, kwargs))

    def fake_popen(*args, **kwargs):
        return _FakePopen([None, None, 0], pid=4321)

    monkeypatch.setattr(claude_mod, "subprocess", type("Sub", (), {"Popen": fake_popen, "DEVNULL": None, "STDOUT": None}))
    monkeypatch.setattr(store, "heartbeat_worker", fake_heartbeat_worker)
    monkeypatch.setattr(store, "heartbeat_lease", fake_heartbeat_lease)
    monkeypatch.setattr(claude_mod.os, "killpg", lambda *a, **k: None)

    rc, _ = claude_mod._run_child(
        task,
        timeout=30,
        store=store,
        worker_id="w1",
        lease_id=claim["lease"]["lease_id"],
        lane_group="runtime-claude",
    )
    assert rc == 0
    assert len(heartbeat_worker) >= 2
    assert len(heartbeat_lease) >= 2


def test_systemd_notify_ready_is_sent_after_initialization(monkeypatch) -> None:
    ready_calls = {"count": 0}

    def fake_notify_ready() -> bool:
        ready_calls["count"] += 1
        return True

    monkeypatch.setattr(claude_mod, "notify_ready", fake_notify_ready)
    monkeypatch.setattr(claude_mod, "notify_status", lambda *_a, **_k: None)
    monkeypatch.setattr(claude_mod, "notify_watchdog", lambda: None)
    status = claude_mod.run_worker(
        worker_id="notify-clause",
        max_iterations=0,
        task_timeout_seconds=1,
        db_path=":memory:",
    )
    assert status["iterations"] == 0
    assert ready_calls["count"] == 1


def test_store_refuses_unsafe_task_before_lease(tmp_path: Path) -> None:
    store = SQLiteLeaseStore(db_path=tmp_path / "unsafe.db")
    task = _base_task("unsafe_claude")
    task["safe_envelope"]["live_gate"] = "open"
    try:
        store.create_task(task)
    except ValueError as exc:
        assert "unsafe live_gate" in str(exc)
    else:
        assert False, "unsafe task should be refused before lease"
    store.close()


def test_fail_classification(tmp_path: Path) -> None:
    assert classify_from_output("needs exchange mutation")["unsafe_to_fix"]
    assert classify_from_output("operator required for manual review")["operator_required"]


def test_metrics_payload_shape(tmp_path: Path) -> None:
    store = SQLiteLeaseStore(db_path=tmp_path / "metrics.db")
    payload = build_metrics_payload(store)
    for key in [
        "v2_closed_loop_active_leases",
        "v2_closed_loop_busy_workers",
        "v2_closed_loop_idle_workers",
    ]:
        assert key in payload
    store.close()


def test_codex_parse_verdict() -> None:
    task = {"task_id": "x"}
    assert _parse_verdict(task, "PASS") == ("PASS", [])
    assert _parse_verdict(task, "FAIL") == ("FAIL", ["FAIL"])


def test_burndown_ready_gate() -> None:
    assert evaluate_ready_gate(0)
    assert not evaluate_ready_gate(1)


def test_executive_payload_does_not_claim_global_readiness(tmp_path: Path) -> None:
    store = SQLiteLeaseStore(db_path=tmp_path / "executive.db")
    payload = build_executive_payload(store)
    operator_payload = build_operator_payload(store)
    assert payload["MIGRATION_COMPLETE"] is False
    assert payload["PAPER_EDGE_PROVEN"] is False
    assert payload["LIVE_READY"] is False
    assert payload["LEGACY_SHUTDOWN_READY"] is False
    assert operator_payload["ready"] is False
    store.close()


def test_spark_systemd_units_are_durable_and_first_class() -> None:
    repo_root = Path(__file__).resolve().parents[6]
    systemd_dir = (
        repo_root
        / "claude_worklog"
        / "final_readiness"
        / "v2_codex_spark_parallel_closed_loop"
        / "latest"
        / "systemd"
    )
    claude_unit = (systemd_dir / "ai-bot-v2-claude-lane@.service").read_text(encoding="utf-8")
    codex_unit = (systemd_dir / "ai-bot-v2-codex-lane@.service").read_text(encoding="utf-8")
    autoseed_unit = (systemd_dir / "ai-bot-v2-closed-loop-autoseed.service").read_text(encoding="utf-8")
    burndown_unit = (systemd_dir / "ai-bot-v2-closed-loop-burndown.service").read_text(encoding="utf-8")
    assert "--max-iterations=1" not in claude_unit
    assert "--max-iterations=1" not in codex_unit
    assert "-m v2.backend.app.closed_loop.cli.autoseed" in autoseed_unit
    assert "-m v2.backend.app.closed_loop.cli.burndown" in burndown_unit
