from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from v2.backend.app.cli import v2_self_healing_supervisor as supervisor
from v2.backend.app.services.self_healing.component_registry import (
    ACTION_RESTART_DEAD,
    ComponentSpec,
)


def test_heartbeat_age_uses_freshest_valid_resident_mode_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 21, 10, 0, tzinfo=UTC)
    legacy_path = tmp_path / "legacy.json"
    waiting_path = tmp_path / "waiting.json"
    legacy_path.write_text(
        json.dumps({"generated_utc": (now - timedelta(days=2)).isoformat()}),
        encoding="utf-8",
    )
    waiting_path.write_text(
        json.dumps({"generated_at": (now - timedelta(seconds=7)).isoformat()}),
        encoding="utf-8",
    )
    monkeypatch.setattr(supervisor, "REPO_ROOT", tmp_path)
    spec = ComponentSpec(
        name="trainer",
        unit="ai-bot-v2-native-cuda-trainer-persistent.service",
        category="trainer",
        heartbeat_file="legacy.json",
        heartbeat_files=("waiting.json", "malformed.json"),
        heartbeat_field="generated_utc",
        max_staleness_seconds=1800,
    )
    (tmp_path / "malformed.json").write_text("not-json", encoding="utf-8")

    assert supervisor._heartbeat_age_seconds(None, spec, now) == 7.0


def test_heartbeat_age_returns_none_when_no_configured_clock_is_valid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(supervisor, "REPO_ROOT", tmp_path)
    (tmp_path / "invalid.json").write_text("{}", encoding="utf-8")
    spec = ComponentSpec(
        name="trainer",
        unit="ai-bot-v2-native-cuda-trainer-persistent.service",
        category="trainer",
        heartbeat_file="missing.json",
        heartbeat_files=("invalid.json",),
        max_staleness_seconds=1800,
    )

    assert supervisor._heartbeat_age_seconds(None, spec, datetime.now(UTC)) is None


def test_restart_resets_failed_latch_before_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A StartLimitBurst 'failed' unit must be reset-failed before restart.

    Without the reset, systemd rejects the restart ("start request repeated
    too quickly") and the unit stays dead forever despite the supervisor.
    """
    now = datetime(2026, 7, 24, 18, 0, tzinfo=UTC)
    unit = "ai-bot-v2-profiled-base-feature-publisher.service"
    spec = ComponentSpec(
        name="base-feature-publisher",
        unit=unit,
        category="trainer",
        heartbeat_file="hb.json",
        heartbeat_files=(),
        heartbeat_field="generated_utc",
        max_staleness_seconds=1800,
    )
    calls: list[list[str]] = []

    def fake_run(args: list[str], timeout: int = 30) -> SimpleNamespace:
        calls.append(list(args))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(supervisor, "NON_INGESTOR_COMPONENTS", [spec])
    monkeypatch.setattr(supervisor, "_utc_now", lambda: now)
    monkeypatch.setattr(supervisor, "_deliberately_stopped", lambda client: set())
    monkeypatch.setattr(supervisor, "_read_stale_streaks", lambda client: {})
    monkeypatch.setattr(supervisor, "_recent_restarts", lambda client, u, n: 0)
    monkeypatch.setattr(supervisor, "_record_restart", lambda client, u, n: None)
    monkeypatch.setattr(
        supervisor,
        "_unit_state",
        lambda u, n: {
            "installed": True,
            "enabled_bool": True,
            "enabled": "enabled",
            "active": "failed",
            "active_since_seconds": None,
        },
    )
    monkeypatch.setattr(
        supervisor,
        "decide_heal_action",
        lambda *a, **k: SimpleNamespace(action=ACTION_RESTART_DEAD, reason="dead"),
    )
    monkeypatch.setattr(supervisor, "_run", fake_run)

    payload = supervisor.run_once(None, dry_run=False, write_redis=False)

    verbs = [c[2] for c in calls if len(c) >= 3 and c[0] == "systemctl"]
    assert "reset-failed" in verbs, verbs
    assert "restart" in verbs, verbs
    # reset-failed must come immediately before restart for the failed unit
    assert verbs.index("reset-failed") < verbs.index("restart")
    assert ["systemctl", "--user", "reset-failed", unit] in calls
    assert ["systemctl", "--user", "restart", unit] in calls
    assert unit in payload["restarted_units"]
    remediation = payload["decisions"][0]["remediation"]
    assert remediation["reset_failed_returncode"] == 0
    assert remediation["returncode"] == 0
