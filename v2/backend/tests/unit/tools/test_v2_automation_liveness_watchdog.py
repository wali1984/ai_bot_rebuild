from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from claude_worklog.tools import v2_automation_liveness_watchdog as watchdog


def test_deliberately_stopped_marker_is_parsed_and_invalid_content_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "deliberately_stopped_units.txt"
    marker.write_text(
        "# operator hold\nheld.service\nother.service\nheld.service\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(watchdog, "DELIBERATELY_STOPPED_FILE", marker)
    units, error = watchdog.deliberately_stopped_units()
    assert units == frozenset({"held.service", "other.service"})
    assert error is None

    marker.write_text("held.service unexpected-token\n", encoding="utf-8")
    units, error = watchdog.deliberately_stopped_units()
    assert units == frozenset()
    assert error == "deliberately_stopped_marker_invalid"


def test_unit_state_reads_hard_hold_before_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(watchdog, "systemd_user_available", lambda: True)
    monkeypatch.setattr(watchdog, "unit_installed", lambda _unit: True)

    def fake_run(args: list[str], timeout: int = 15) -> SimpleNamespace:
        del timeout
        if "show" in args:
            return SimpleNamespace(returncode=0, stdout="yes\n", stderr="")
        if "is-active" in args:
            return SimpleNamespace(returncode=3, stdout="inactive\n", stderr="")
        if "is-enabled" in args:
            return SimpleNamespace(returncode=0, stdout="enabled\n", stderr="")
        raise AssertionError(args)

    monkeypatch.setattr(watchdog, "run", fake_run)
    assert watchdog.unit_state("held.service") == {
        "unit": "held.service",
        "installed": True,
        "active_state": "inactive",
        "enabled_state": "enabled",
        "refuse_manual_start": "yes",
    }


@pytest.mark.parametrize(
    ("unit_payload", "deliberately_stopped", "marker_error", "expected"),
    [
        (
            {"unit": "held.service", "refuse_manual_start": "no"},
            frozenset({"held.service"}),
            None,
            "unit_deliberately_stopped",
        ),
        (
            {"unit": "held.service", "refuse_manual_start": "yes"},
            frozenset(),
            None,
            "unit_refuses_manual_start",
        ),
        (
            {"unit": "held.service", "refuse_manual_start": "unknown"},
            frozenset(),
            None,
            "unit_start_hold_state_unverified",
        ),
        (
            {"unit": "held.service", "refuse_manual_start": "no"},
            frozenset(),
            "deliberately_stopped_marker_unreadable",
            "deliberately_stopped_marker_unreadable",
        ),
        (
            {"unit": "healthy.service", "refuse_manual_start": "no"},
            frozenset(),
            None,
            None,
        ),
    ],
)
def test_restart_safety_block_reason_is_fail_closed(
    unit_payload: dict[str, object],
    deliberately_stopped: frozenset[str],
    marker_error: str | None,
    expected: str | None,
) -> None:
    assert (
        watchdog.restart_safety_block_reason(
            unit_payload,
            deliberately_stopped=deliberately_stopped,
            marker_error=marker_error,
        )
        == expected
    )


@pytest.mark.parametrize(
    ("refuse_manual_start", "deliberately_stopped", "expected_reason"),
    [
        ("yes", frozenset(), "unit_refuses_manual_start"),
        ("no", frozenset({"held.service"}), "unit_deliberately_stopped"),
    ],
)
def test_build_status_never_restarts_held_unit(
    refuse_manual_start: str,
    deliberately_stopped: frozenset[str],
    expected_reason: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(watchdog, "SERVICE_UNITS", ["held.service"])
    monkeypatch.setattr(watchdog, "TIMER_UNITS", [])
    monkeypatch.setattr(watchdog, "systemd_user_available", lambda: True)
    monkeypatch.setattr(
        watchdog,
        "unit_state",
        lambda unit: {
            "unit": unit,
            "installed": True,
            "active_state": "inactive",
            "enabled_state": "enabled",
            "refuse_manual_start": refuse_manual_start,
        },
    )
    monkeypatch.setattr(
        watchdog,
        "deliberately_stopped_units",
        lambda: (deliberately_stopped, None),
    )
    monkeypatch.setattr(watchdog, "process_snapshot", lambda: {})
    monkeypatch.setattr(watchdog, "pending_codex_reviews", lambda: [])
    monkeypatch.setattr(watchdog, "read_json", lambda _path: {})

    def forbidden_restart(_unit: str) -> dict[str, object]:
        raise AssertionError("restart must not be called for a held unit")

    monkeypatch.setattr(watchdog, "restart_unit", forbidden_restart)
    payload = watchdog.build_status(no_restart=False)
    assert payload["actions"] == [
        {
            "unit": "held.service",
            "action": "restart_skipped_safety_hold",
            "reason": expected_reason,
        }
    ]
