from __future__ import annotations

from pathlib import Path

from v2.backend.app.cli.v2_worker_inventory import build_inventory


def _touch(path: Path, body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def test_inventory_backlog_never_counts_as_migrated(tmp_path, monkeypatch) -> None:
    _touch(
        tmp_path / "claude_worklog/final_readiness/script_migration_backlog/latest/script_migration_backlog.json",
        '{"items":[{"category":"feature_snapshot_builder"}]}',
    )
    monkeypatch.setattr("v2.backend.app.cli.v2_worker_inventory._process_lines", lambda: [])

    payload = build_inventory(tmp_path)
    worker = next(item for item in payload["workers"] if item["category"] == "feature_snapshot_builder")

    assert worker["status"] == "BACKLOG_ONLY"
    assert worker["is_migration"] is False


def test_worker_with_path_command_payload_and_test_can_be_migrated_not_running(tmp_path, monkeypatch) -> None:
    _touch(tmp_path / "v2/backend/app/cli/paper_online_runtime.py")
    _touch(tmp_path / "v2/backend/tests/unit/cli/test_paper_online_runtime.py")
    _touch(tmp_path / "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json", "{}")
    monkeypatch.setattr("v2.backend.app.cli.v2_worker_inventory._process_lines", lambda: [])

    payload = build_inventory(tmp_path)
    worker = next(item for item in payload["workers"] if item["category"] == "paper_execution_worker")

    assert worker["status"] == "PAPER_ONLY"
    assert worker["old_redis_write_risk"] is False
    assert worker["live_action_risk"] is False


def test_legacy_only_worker_is_not_v2_migration(tmp_path, monkeypatch) -> None:
    _touch(tmp_path / "legacy_reference/trading/signal_router.py")
    monkeypatch.setattr("v2.backend.app.cli.v2_worker_inventory._process_lines", lambda: [])

    payload = build_inventory(tmp_path)
    worker = next(item for item in payload["workers"] if item["category"] == "signal_publisher")

    assert worker["status"] == "LEGACY_ONLY"
    assert worker["is_migration"] is False
