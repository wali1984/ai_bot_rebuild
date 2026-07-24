from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _watchdog_module():
    root = Path(__file__).resolve().parents[5]
    path = root / "tools" / "trainer_fail_closed_watchdog.py"
    spec = importlib.util.spec_from_file_location("trainer_fail_closed_watchdog", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dead_service_in_deliberate_stop_registry_is_not_restarted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchdog = _watchdog_module()
    registry = tmp_path / "deliberately_stopped_units.txt"
    registry.write_text(
        "# maintenance hold\nai-bot-v2-native-cuda-trainer-persistent.service\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(watchdog, "DELIBERATELY_STOPPED_FILE", registry)
    monkeypatch.setattr(watchdog, "STOP_MARKER", tmp_path / "no-stop-marker")
    monkeypatch.setattr(watchdog, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watchdog, "_service_active", lambda: False)

    def forbidden_restart(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("a deliberately stopped service must not be restarted")

    monkeypatch.setattr(watchdog, "_restart", forbidden_restart)

    assert watchdog.main() == 0


def test_dead_service_with_unreadable_registry_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchdog = _watchdog_module()
    monkeypatch.setattr(
        watchdog,
        "DELIBERATELY_STOPPED_FILE",
        tmp_path / "missing-deliberately-stopped-units.txt",
    )
    monkeypatch.setattr(watchdog, "STOP_MARKER", tmp_path / "no-stop-marker")
    monkeypatch.setattr(watchdog, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(watchdog, "_service_active", lambda: False)
    monkeypatch.setattr(
        watchdog,
        "_restart",
        lambda *_args, **_kwargs: pytest.fail("unverified stop registry must hold"),
    )

    assert watchdog.main() == 0
