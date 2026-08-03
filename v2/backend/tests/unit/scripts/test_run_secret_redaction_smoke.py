from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_secret_redaction_smoke import build_report


def test_secret_redaction_smoke_passes_for_redacted_artifacts(tmp_path: Path) -> None:
    payload_dir = tmp_path / "payloads"
    log_dir = tmp_path / "logs"
    screenshot_dir = tmp_path / "screenshots"
    payload_dir.mkdir()
    log_dir.mkdir()
    screenshot_dir.mkdir()
    (payload_dir / "credential-status.json").write_text(
        '{"api_key":"[redacted]","api_secret":"[redacted]","status":"configured"}',
        encoding="utf-8",
    )
    (log_dir / "app.log").write_text("credential status emitted with redacted values\n", encoding="utf-8")
    (screenshot_dir / "status-390x844.png").write_bytes(b"fake png placeholder")

    report = build_report(
        safe_api_payload_paths=[payload_dir],
        log_paths=[log_dir],
        screenshot_paths=[screenshot_dir],
        screenshots_reviewed=True,
    )

    assert report["secret_redaction_smoke_status"] == "passed"
    assert report["raw_credential_value_exposed"] is False
    assert report["api_key_exposed"] is False
    assert report["api_secret_exposed"] is False
    assert report["access_token_exposed"] is False
    assert report["safe_api_payloads_checked"] is True
    assert report["logs_checked"] is True
    assert report["screenshots_checked"] is True
    assert report["live_trading_enabled"] is False
    assert report["exchange_mutation_enabled"] is False


def test_secret_redaction_smoke_fails_without_screenshot_attestation(tmp_path: Path) -> None:
    payload = tmp_path / "payload.json"
    log = tmp_path / "service.log"
    screenshot = tmp_path / "status.png"
    payload.write_text('{"api_key":"[redacted]"}', encoding="utf-8")
    log.write_text("safe log\n", encoding="utf-8")
    screenshot.write_bytes(b"fake png placeholder")

    report = build_report(
        safe_api_payload_paths=[payload],
        log_paths=[log],
        screenshot_paths=[screenshot],
        screenshots_reviewed=False,
    )

    assert report["secret_redaction_smoke_status"] == "failed"
    assert report["screenshots_checked"] is False
    assert any("Screenshot artifacts require explicit review" in warning for warning in report["warnings"])


def test_secret_redaction_smoke_flags_unredacted_values_without_returning_secret(tmp_path: Path) -> None:
    payload_dir = tmp_path / "payloads"
    log_dir = tmp_path / "logs"
    screenshot_dir = tmp_path / "screenshots"
    payload_dir.mkdir()
    log_dir.mkdir()
    screenshot_dir.mkdir()
    secret_value = "abcd1234abcd1234abcd1234abcd1234"
    (payload_dir / "unsafe.json").write_text(f'{{"api_secret":"{secret_value}"}}', encoding="utf-8")
    (log_dir / "app.log").write_text("safe log\n", encoding="utf-8")
    (screenshot_dir / "status.png").write_bytes(b"fake png placeholder")

    report = build_report(
        safe_api_payload_paths=[payload_dir],
        log_paths=[log_dir],
        screenshot_paths=[screenshot_dir],
        screenshots_reviewed=True,
    )

    assert report["secret_redaction_smoke_status"] == "failed"
    assert report["raw_credential_value_exposed"] is True
    assert report["api_secret_exposed"] is True
    assert report["findings_count"] == 1
    assert secret_value not in str(report["findings"])
    assert report["findings"][0]["field"] == "api_secret"
