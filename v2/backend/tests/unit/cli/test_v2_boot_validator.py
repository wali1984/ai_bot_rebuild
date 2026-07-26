from __future__ import annotations

import json
from types import SimpleNamespace

from v2.backend.app.cli import v2_boot_validator as validator


def _hold(unit: str = "ai-bot-v2-held.service") -> dict:
    return {
        "schema_version": "RepairHoldV1",
        "unit": unit,
        "owner": "unit-test",
        "reason": "bounded repair",
        "opened_at": "2026-07-26T00:00:00Z",
        "expires_at": "2099-08-09T00:00:00Z",
        "replacement_unit": "ai-bot-v2-replacement.service",
        "required_exit_evidence": "receipt",
        "live_authority": False,
    }


def test_repair_holds_are_republished_from_durable_inventory(tmp_path, monkeypatch) -> None:
    payload = {"schema_version": "v2_repair_holds_v1", "holds": [_hold()]}
    path = tmp_path / "repair_holds.json"
    path.write_text(json.dumps(payload))
    writes: list[tuple[str, ...]] = []
    monkeypatch.setattr(validator, "REPAIR_HOLDS_PATH", path)
    monkeypatch.setattr(
        validator,
        "redis_cli",
        lambda *args: writes.append(args) or "OK",
    )

    observed, failures = validator.publish_repair_holds()

    assert observed == payload
    assert failures == []
    assert writes[0][:2] == ("SET", "v2:operations:repair_holds")


def test_active_repair_held_unit_fails_closed(monkeypatch) -> None:
    unit = "ai-bot-v2-held.service"
    monkeypatch.setattr(validator, "expected_active_units", lambda: {})
    monkeypatch.setattr(
        validator,
        "sh",
        lambda _cmd: f"{unit} enabled",
    )
    monkeypatch.setattr(validator, "unit_state", lambda _unit: ("active", "running", "yes"))

    rows, failures = validator.classify_units({"holds": [_hold(unit)]})

    assert rows[0]["classification"] == "FAILED_UNEXPECTED"
    assert failures[0]["reason"] == "repair-held service became authoritative"


def test_serving_is_not_healthy_without_directional_supply(monkeypatch) -> None:
    monkeypatch.setattr(
        validator,
        "get_json_key",
        lambda _key: {
            "generated_utc": validator.utc_now(),
            "records_published": 100,
            "directional_records": 0,
        },
    )

    result = validator.check_serving()

    assert result["ok"] is False
    assert result["detail"]["records_published"] == 100
    assert result["detail"]["directional_records"] == 0


def test_systemd_warning_is_an_invalid_unit(monkeypatch) -> None:
    monkeypatch.setattr(
        validator.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="",
            stderr="broken.service:8: Invalid environment assignment, ignoring: BOT",
        ),
    )

    result = validator.check_systemd_units()

    assert result["ok"] is False
    assert result["detail"]["invalid_units"] == 1
