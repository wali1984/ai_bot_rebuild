from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from v2.backend.app.cli import v2_self_healing_supervisor as supervisor
from v2.backend.app.services.self_healing.component_registry import ComponentSpec


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
