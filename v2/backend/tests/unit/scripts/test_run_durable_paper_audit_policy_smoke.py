from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_durable_paper_audit_policy_smoke import build_report, main


def _write_safe_policy(tmp_path: Path) -> Path:
    path = tmp_path / "durable-paper-audit-policy.json"
    path.write_text(
        json.dumps(
            {
                "production_durable_store": True,
                "retention_enforced": True,
                "production_writer_hardened": True,
                "audit_verification_passed": True,
                "backup_restore_verified": True,
                "access_control_enforced": True,
                "contains_credentials": False,
                "live_transport_enabled": False,
                "exchange_mutation_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_durable_paper_audit_policy_smoke_passes_for_safe_evidence(tmp_path: Path) -> None:
    evidence = _write_safe_policy(tmp_path)

    report = build_report(evidence_paths=[evidence])

    assert report["durable_paper_audit_policy_smoke_status"] == "passed"
    assert report["durable_paper_audit_policy_status"] == "passed"
    assert report["production_durable_store"] is True
    assert report["retention_enforced"] is True
    assert report["production_writer_hardened"] is True
    assert report["audit_verification_passed"] is True
    assert report["backup_restore_verified"] is True
    assert report["access_control_enforced"] is True
    assert report["contains_credentials"] is False
    assert report["live_transport_enabled"] is False
    assert report["exchange_mutation_enabled"] is False
    assert report["missing_fields"] == []


def test_durable_paper_audit_policy_smoke_fails_missing_policy_fields(tmp_path: Path) -> None:
    evidence = tmp_path / "partial-policy.json"
    evidence.write_text(
        json.dumps(
            {
                "production_durable_store": True,
                "retention_enforced": True,
                "live_transport_enabled": False,
                "exchange_mutation_enabled": False,
            }
        ),
        encoding="utf-8",
    )

    report = build_report(evidence_paths=[evidence])

    assert report["durable_paper_audit_policy_smoke_status"] == "failed"
    assert "production_writer_hardened" in report["missing_fields"]
    assert "audit_verification_passed" in report["missing_fields"]
    assert "backup_restore_verified" in report["missing_fields"]
    assert "access_control_enforced" in report["missing_fields"]


def test_durable_paper_audit_policy_smoke_fails_secret_or_live_mutation(tmp_path: Path) -> None:
    evidence = _write_safe_policy(tmp_path)
    evidence.write_text(
        json.dumps(
            {
                "production_durable_store": True,
                "retention_enforced": True,
                "production_writer_hardened": True,
                "audit_verification_passed": True,
                "backup_restore_verified": True,
                "access_control_enforced": True,
                "api_secret": "unsafe-secret-value",
                "live_transport_enabled": True,
                "exchange_mutation_enabled": True,
            }
        ),
        encoding="utf-8",
    )

    report = build_report(evidence_paths=[evidence])

    assert report["durable_paper_audit_policy_smoke_status"] == "failed"
    assert report["contains_credentials"] is True
    assert report["live_transport_enabled"] is True
    assert report["exchange_mutation_enabled"] is True
    assert "credential_free_audit_policy_evidence" in report["missing_fields"]
    assert "live_transport_disabled" in report["missing_fields"]
    assert "exchange_mutation_disabled" in report["missing_fields"]


def test_durable_paper_audit_policy_smoke_cli_writes_artifact(tmp_path: Path) -> None:
    evidence = _write_safe_policy(tmp_path)
    output = tmp_path / "artifact" / "durable-paper-audit-policy.json"

    exit_code = main([
        "--evidence-path",
        str(evidence),
        "--output",
        str(output),
    ])

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["durable_paper_audit_policy_smoke_status"] == "passed"
    assert payload["source"] == "local_durable_paper_audit_policy_smoke"
    assert payload["source_type"] == "local_smoke"
    assert payload["mode"] == "paper"
    assert payload["live_transport_enabled"] is False
    assert payload["exchange_mutation_enabled"] is False
