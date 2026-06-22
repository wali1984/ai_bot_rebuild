from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_alembic_auth_migration_approval_smoke import build_report, main


def _write_safe_evidence(tmp_path: Path) -> tuple[Path, Path]:
    approval = tmp_path / "approval.json"
    safety = tmp_path / "safety.json"
    approval.write_text(
        json.dumps(
            {
                "auth_user_migration_present": True,
                "revocation_migration_present": True,
                "admin_audit_migration_present": True,
                "migration_reviewed": True,
                "rollback_plan_reviewed": True,
                "retention_policy_reviewed": True,
                "uniqueness_constraints_reviewed": True,
                "no_plaintext_password_columns": True,
                "migration_not_applied_by_runner": True,
            }
        ),
        encoding="utf-8",
    )
    safety.write_text(
        json.dumps(
            {
                "secret_exposure_found": False,
                "database_mutation_performed": False,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    return approval, safety


def test_alembic_auth_migration_approval_smoke_passes_for_safe_evidence(tmp_path: Path) -> None:
    approval, safety = _write_safe_evidence(tmp_path)

    report = build_report(approval_artifact_paths=[approval], safety_artifact_paths=[safety])

    assert report["alembic_auth_migration_approval_status"] == "passed"
    assert report["auth_user_migration_present"] is True
    assert report["revocation_migration_present"] is True
    assert report["admin_audit_migration_present"] is True
    assert report["rollback_plan_reviewed"] is True
    assert report["secret_exposure_found"] is False
    assert report["database_mutation_performed"] is False
    assert report["live_trading_enabled"] is False
    assert report["exchange_mutation_enabled"] is False
    assert report["missing_fields"] == []


def test_alembic_auth_migration_approval_smoke_fails_without_required_evidence(tmp_path: Path) -> None:
    _approval, safety = _write_safe_evidence(tmp_path)

    report = build_report(approval_artifact_paths=[], safety_artifact_paths=[safety])

    assert report["alembic_auth_migration_approval_status"] == "failed"
    assert "auth_user_migration_present" in report["missing_fields"]
    assert any("No Alembic migration approval artifacts" in warning for warning in report["warnings"])


def test_alembic_auth_migration_approval_smoke_fails_on_secret_db_or_live_mutation(tmp_path: Path) -> None:
    approval, safety = _write_safe_evidence(tmp_path)
    safety.write_text(
        json.dumps(
            {
                "api_secret": "unsafe-secret-value",
                "database_mutation_performed": True,
                "live_trading_enabled": True,
                "exchange_mutation_enabled": True,
            }
        ),
        encoding="utf-8",
    )

    report = build_report(approval_artifact_paths=[approval], safety_artifact_paths=[safety])

    assert report["alembic_auth_migration_approval_status"] == "failed"
    assert "no_secret_exposure" in report["missing_fields"]
    assert "no_database_mutation_by_smoke_runner" in report["missing_fields"]
    assert "live_trading_disabled" in report["missing_fields"]
    assert "exchange_mutation_disabled" in report["missing_fields"]


def test_alembic_auth_migration_approval_smoke_cli_writes_artifact(tmp_path: Path) -> None:
    approval, safety = _write_safe_evidence(tmp_path)
    output = tmp_path / "artifact" / "alembic-approval.json"

    exit_code = main(
        [
            "--approval-artifact-path",
            str(approval),
            "--safety-artifact-path",
            str(safety),
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["alembic_auth_migration_approval_status"] == "passed"
    assert payload["source"] == "local_alembic_auth_migration_approval_smoke"
    assert payload["source_type"] == "local_smoke"
    assert payload["mode"] == "read_only"
    assert payload["live_trading_enabled"] is False
    assert payload["exchange_mutation_enabled"] is False
