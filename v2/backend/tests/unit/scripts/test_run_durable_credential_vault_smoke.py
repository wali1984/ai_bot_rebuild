from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_durable_credential_vault_smoke import build_report, main


def _write_safe_evidence(tmp_path: Path) -> tuple[Path, Path]:
    vault = tmp_path / "vault.json"
    safety = tmp_path / "safety.json"
    vault.write_text(
        json.dumps(
            {
                "durable_production_vault_integrated": True,
                "backend_only_secret_access": True,
                "read_only_scope_enforced": True,
                "credential_rotation_policy_configured": True,
                "secret_redaction_verified": True,
                "access_control_enforced": True,
                "audit_logging_enabled": True,
            }
        ),
        encoding="utf-8",
    )
    safety.write_text(
        json.dumps(
            {
                "raw_credential_value_exposed": False,
                "contains_credentials": False,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
                "order_write_enabled": False,
                "withdraw_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    return vault, safety


def test_durable_credential_vault_smoke_passes_for_safe_evidence(tmp_path: Path) -> None:
    vault, safety = _write_safe_evidence(tmp_path)

    report = build_report(vault_evidence_paths=[vault], safety_evidence_paths=[safety])

    assert report["durable_credential_vault_status"] == "passed"
    assert report["durable_production_vault_integrated"] is True
    assert report["backend_only_secret_access"] is True
    assert report["read_only_scope_enforced"] is True
    assert report["credential_rotation_policy_configured"] is True
    assert report["raw_credential_value_exposed"] is False
    assert report["live_trading_enabled"] is False
    assert report["exchange_mutation_enabled"] is False
    assert report["missing_fields"] == []


def test_durable_credential_vault_smoke_fails_without_required_evidence(tmp_path: Path) -> None:
    _vault, safety = _write_safe_evidence(tmp_path)

    report = build_report(vault_evidence_paths=[], safety_evidence_paths=[safety])

    assert report["durable_credential_vault_status"] == "failed"
    assert "durable_production_vault_integrated" in report["missing_fields"]
    assert any("No durable credential-vault evidence" in warning for warning in report["warnings"])


def test_durable_credential_vault_smoke_fails_on_secret_or_live_mutation(tmp_path: Path) -> None:
    vault, safety = _write_safe_evidence(tmp_path)
    safety.write_text(
        json.dumps(
            {
                "api_secret": "unsafe-secret-value",
                "live_trading_enabled": True,
                "exchange_mutation_enabled": True,
                "order_write_enabled": True,
                "withdraw_enabled": True,
            }
        ),
        encoding="utf-8",
    )

    report = build_report(vault_evidence_paths=[vault], safety_evidence_paths=[safety])

    assert report["durable_credential_vault_status"] == "failed"
    assert "no_raw_credential_exposure" in report["missing_fields"]
    assert "no_credentials_in_artifact" in report["missing_fields"]
    assert "live_trading_disabled" in report["missing_fields"]
    assert "exchange_mutation_disabled" in report["missing_fields"]
    assert "order_write_disabled" in report["missing_fields"]
    assert "withdraw_disabled" in report["missing_fields"]


def test_durable_credential_vault_smoke_cli_writes_artifact(tmp_path: Path) -> None:
    vault, safety = _write_safe_evidence(tmp_path)
    output = tmp_path / "artifact" / "durable-vault.json"

    exit_code = main(
        [
            "--vault-evidence-path",
            str(vault),
            "--safety-evidence-path",
            str(safety),
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["durable_credential_vault_status"] == "passed"
    assert payload["source"] == "local_durable_credential_vault_smoke"
    assert payload["source_type"] == "local_smoke"
    assert payload["mode"] == "read_only"
    assert payload["live_trading_enabled"] is False
    assert payload["exchange_mutation_enabled"] is False
