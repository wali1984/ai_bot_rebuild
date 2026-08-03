from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_current_validation_evidence_smoke import build_report, main


COMMANDS = [
    "python scripts/check_product_readiness_status.py",
    "npm run build",
    "npx playwright test --project=chromium",
]


def _write_status(tmp_path: Path, commands: list[str] | None = None) -> Path:
    status_path = tmp_path / "product-readiness-status.json"
    status_path.write_text(
        json.dumps({"pending_validation_queue": commands if commands is not None else COMMANDS}),
        encoding="utf-8",
    )
    return status_path


def _write_results(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    results_path = tmp_path / "validation-results.json"
    results_path.write_text(json.dumps({"results": rows}), encoding="utf-8")
    return results_path


def _passing_rows() -> list[dict[str, object]]:
    return [
        {
            "command": command,
            "status": "passed",
            "after_latest_changes": True,
            "live_trading_enabled": False,
            "exchange_mutation_enabled": False,
        }
        for command in COMMANDS
    ]


def test_current_validation_evidence_smoke_passes_when_all_required_commands_are_current_and_safe(tmp_path: Path) -> None:
    status_path = _write_status(tmp_path)
    results_path = _write_results(tmp_path, _passing_rows())

    report = build_report(readiness_status_path=status_path, validation_result_paths=[results_path])

    assert report["current_validation_evidence_status"] == "passed"
    assert report["required_command_count"] == len(COMMANDS)
    assert report["passed_command_count"] == len(COMMANDS)
    assert report["missing_commands"] == []
    assert report["non_current_commands"] == []
    assert report["skipped_commands"] == []
    assert report["failed_commands"] == []
    assert report["missing_fields"] == []
    assert report["live_trading_enabled"] is False
    assert report["exchange_mutation_enabled"] is False


def test_current_validation_evidence_smoke_fails_when_required_command_is_missing(tmp_path: Path) -> None:
    status_path = _write_status(tmp_path)
    results_path = _write_results(tmp_path, _passing_rows()[:-1])

    report = build_report(readiness_status_path=status_path, validation_result_paths=[results_path])

    assert report["current_validation_evidence_status"] == "failed"
    assert report["missing_commands"] == ["npx playwright test --project=chromium"]
    assert "all_pending_validation_commands_passed" in report["missing_fields"]


def test_current_validation_evidence_smoke_fails_on_stale_skipped_failed_or_live_rows(tmp_path: Path) -> None:
    status_path = _write_status(tmp_path)
    results_path = _write_results(
        tmp_path,
        [
            {
                "command": COMMANDS[0],
                "status": "passed",
                "after_latest_changes": False,
            },
            {
                "command": COMMANDS[1],
                "status": "skipped",
                "after_latest_changes": True,
            },
            {
                "command": COMMANDS[2],
                "status": "failed",
                "after_latest_changes": True,
                "live_trading_enabled": True,
                "exchange_mutation_enabled": True,
            },
        ],
    )

    report = build_report(readiness_status_path=status_path, validation_result_paths=[results_path])

    assert report["current_validation_evidence_status"] == "failed"
    assert COMMANDS[0] in report["non_current_commands"]
    assert COMMANDS[1] in report["skipped_commands"]
    assert COMMANDS[2] in report["failed_commands"]
    assert "validation_results_after_latest_changes" in report["missing_fields"]
    assert "no_skipped_validation_commands" in report["missing_fields"]
    assert "no_failed_validation_commands" in report["missing_fields"]
    assert "live_trading_disabled" in report["missing_fields"]
    assert "exchange_mutation_disabled" in report["missing_fields"]
    assert report["live_trading_enabled"] is True
    assert report["exchange_mutation_enabled"] is True


def test_current_validation_evidence_smoke_cli_writes_artifact(tmp_path: Path) -> None:
    status_path = _write_status(tmp_path)
    results_path = _write_results(tmp_path, _passing_rows())
    output_path = tmp_path / "artifact" / "current-validation-evidence.json"

    exit_code = main(
        [
            "--readiness-status-path",
            str(status_path),
            "--validation-result-path",
            str(results_path),
            "--output",
            str(output_path),
        ]
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["current_validation_evidence_status"] == "passed"
    assert payload["source"] == "local_current_validation_evidence_smoke"
    assert payload["source_type"] == "local_smoke"
    assert payload["mode"] == "read_only"
    assert payload["missing_fields"] == []
