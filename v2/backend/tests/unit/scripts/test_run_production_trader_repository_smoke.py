from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_production_trader_repository_smoke import build_report, main


def _write_safe_evidence(tmp_path: Path) -> tuple[Path, Path, Path]:
    repository = tmp_path / "repository.json"
    writer = tmp_path / "writer.json"
    isolation = tmp_path / "isolation.json"
    repository.write_text(
        json.dumps(
            {
                "durable_user_repository": True,
                "durable_trader_account_repository": True,
                "migration_applied": True,
                "backup_restore_verified": True,
                "contains_credentials": False,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    writer.write_text(
        json.dumps(
            {
                "account_writer_persistence": True,
                "activity_writer_persistence": True,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    isolation.write_text(
        json.dumps(
            {
                "row_level_trader_isolation": True,
                "paper_account_uniqueness": True,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    return repository, writer, isolation


def test_production_trader_repository_smoke_passes_for_safe_evidence(tmp_path: Path) -> None:
    repository, writer, isolation = _write_safe_evidence(tmp_path)

    report = build_report(
        repository_evidence_paths=[repository],
        writer_evidence_paths=[writer],
        isolation_evidence_paths=[isolation],
    )

    assert report["production_trader_repository_smoke_status"] == "passed"
    assert report["durable_user_repository"] is True
    assert report["durable_trader_account_repository"] is True
    assert report["account_writer_persistence"] is True
    assert report["activity_writer_persistence"] is True
    assert report["row_level_trader_isolation"] is True
    assert report["paper_account_uniqueness"] is True
    assert report["contains_credentials"] is False
    assert report["live_trading_enabled"] is False
    assert report["exchange_mutation_enabled"] is False
    assert report["missing_fields"] == []


def test_production_trader_repository_smoke_fails_missing_writer_evidence(tmp_path: Path) -> None:
    repository, _writer, isolation = _write_safe_evidence(tmp_path)

    report = build_report(
        repository_evidence_paths=[repository],
        writer_evidence_paths=[],
        isolation_evidence_paths=[isolation],
    )

    assert report["production_trader_repository_smoke_status"] == "failed"
    assert "account_writer_persistence" in report["missing_fields"]
    assert "activity_writer_persistence" in report["missing_fields"]
    assert any("No production writer evidence" in warning for warning in report["warnings"])


def test_production_trader_repository_smoke_fails_on_secret_or_live_mutation(tmp_path: Path) -> None:
    repository, writer, isolation = _write_safe_evidence(tmp_path)
    repository.write_text(
        json.dumps(
            {
                "durable_user_repository": True,
                "durable_trader_account_repository": True,
                "migration_applied": True,
                "backup_restore_verified": True,
                "api_secret": "unsafe-secret-value",
                "live_trading_enabled": True,
                "exchange_mutation_enabled": True,
            }
        ),
        encoding="utf-8",
    )

    report = build_report(
        repository_evidence_paths=[repository],
        writer_evidence_paths=[writer],
        isolation_evidence_paths=[isolation],
    )

    assert report["production_trader_repository_smoke_status"] == "failed"
    assert report["contains_credentials"] is True
    assert report["live_trading_enabled"] is True
    assert report["exchange_mutation_enabled"] is True
    assert "credential_free_repository_evidence" in report["missing_fields"]
    assert "live_trading_disabled" in report["missing_fields"]
    assert "exchange_mutation_disabled" in report["missing_fields"]


def test_production_trader_repository_smoke_cli_writes_artifact(tmp_path: Path) -> None:
    repository, writer, isolation = _write_safe_evidence(tmp_path)
    output = tmp_path / "artifact" / "production-trader-repository.json"

    exit_code = main(
        [
            "--repository-evidence-path",
            str(repository),
            "--writer-evidence-path",
            str(writer),
            "--isolation-evidence-path",
            str(isolation),
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["production_trader_repository_smoke_status"] == "passed"
    assert payload["source"] == "local_production_trader_repository_smoke"
    assert payload["source_type"] == "local_smoke"
    assert payload["mode"] == "read_only"
    assert payload["live_trading_enabled"] is False
    assert payload["exchange_mutation_enabled"] is False
