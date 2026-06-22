from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_production_alert_delivery_audit_smoke import build_report, main


def _write_safe_evidence(tmp_path: Path) -> tuple[Path, Path, Path]:
    repository = tmp_path / "alert-repository.json"
    delivery = tmp_path / "alert-delivery.json"
    audit = tmp_path / "alert-audit.json"
    repository.write_text(
        json.dumps(
            {
                "alert_repository_configured": True,
                "alert_crud_validated": True,
                "trader_scope_enforced": True,
                "paper_account_scope_enforced": True,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
                "real_order_submitted": False,
                "live_gate_mutation_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    delivery.write_text(
        json.dumps(
            {
                "delivery_service_configured": True,
                "notification_delivery_tested": True,
                "delivery_secret_redacted": True,
                "contains_credentials": False,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
                "real_order_submitted": False,
                "live_gate_mutation_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    audit.write_text(
        json.dumps(
            {
                "audit_repository_durable": True,
                "audit_events_linked": True,
                "audit_retention_enforced": True,
                "access_control_enforced": True,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
                "real_order_submitted": False,
                "live_gate_mutation_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    return repository, delivery, audit


def test_production_alert_delivery_audit_smoke_passes_for_safe_evidence(tmp_path: Path) -> None:
    repository, delivery, audit = _write_safe_evidence(tmp_path)

    report = build_report(repository_paths=[repository], delivery_paths=[delivery], audit_paths=[audit])

    assert report["production_alert_delivery_audit_smoke_status"] == "passed"
    assert report["alerts_crud_delivery_audit_repositories_status"] == "passed"
    assert report["alert_repository_configured"] is True
    assert report["alert_crud_validated"] is True
    assert report["trader_scope_enforced"] is True
    assert report["paper_account_scope_enforced"] is True
    assert report["delivery_service_configured"] is True
    assert report["notification_delivery_tested"] is True
    assert report["delivery_secret_redacted"] is True
    assert report["audit_repository_durable"] is True
    assert report["audit_events_linked"] is True
    assert report["audit_retention_enforced"] is True
    assert report["access_control_enforced"] is True
    assert report["contains_credentials"] is False
    assert report["missing_fields"] == []


def test_production_alert_delivery_audit_smoke_fails_missing_delivery_or_audit(tmp_path: Path) -> None:
    repository = tmp_path / "alert-repository.json"
    repository.write_text(
        json.dumps(
            {
                "alert_repository_configured": True,
                "alert_crud_validated": True,
                "trader_scope_enforced": True,
                "paper_account_scope_enforced": True,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
                "real_order_submitted": False,
                "live_gate_mutation_enabled": False,
            }
        ),
        encoding="utf-8",
    )

    report = build_report(repository_paths=[repository], delivery_paths=[], audit_paths=[])

    assert report["production_alert_delivery_audit_smoke_status"] == "failed"
    assert "delivery_service_configured" in report["missing_fields"]
    assert "notification_delivery_tested" in report["missing_fields"]
    assert "audit_repository_durable" in report["missing_fields"]
    assert "audit_events_linked" in report["missing_fields"]
    assert any("No production alert delivery" in warning for warning in report["warnings"])
    assert any("No production alert audit" in warning for warning in report["warnings"])


def test_production_alert_delivery_audit_smoke_fails_secret_or_live_mutation(tmp_path: Path) -> None:
    repository, delivery, audit = _write_safe_evidence(tmp_path)
    delivery.write_text(
        json.dumps(
            {
                "delivery_service_configured": True,
                "notification_delivery_tested": True,
                "delivery_secret_redacted": True,
                "webhook_url": "https://alerts.example.local/hook?token=unsafe-token",
                "live_trading_enabled": True,
                "exchange_mutation_enabled": True,
                "real_order_submitted": True,
                "live_gate_mutation_enabled": True,
            }
        ),
        encoding="utf-8",
    )

    report = build_report(repository_paths=[repository], delivery_paths=[delivery], audit_paths=[audit])

    assert report["production_alert_delivery_audit_smoke_status"] == "failed"
    assert report["contains_credentials"] is True
    assert report["live_trading_enabled"] is True
    assert report["exchange_mutation_enabled"] is True
    assert report["real_order_submitted"] is True
    assert report["live_gate_mutation_enabled"] is True
    assert "credential_free_alert_delivery_audit_evidence" in report["missing_fields"]
    assert "live_trading_disabled" in report["missing_fields"]
    assert "exchange_mutation_disabled" in report["missing_fields"]
    assert "real_order_submission_absent" in report["missing_fields"]
    assert "live_gate_mutation_absent" in report["missing_fields"]


def test_production_alert_delivery_audit_smoke_cli_writes_artifact(tmp_path: Path) -> None:
    repository, delivery, audit = _write_safe_evidence(tmp_path)
    output = tmp_path / "artifact" / "production-alert-delivery-audit.json"

    exit_code = main(
        [
            "--repository-evidence-path",
            str(repository),
            "--delivery-evidence-path",
            str(delivery),
            "--audit-evidence-path",
            str(audit),
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["production_alert_delivery_audit_smoke_status"] == "passed"
    assert payload["source"] == "local_production_alert_delivery_audit_smoke"
    assert payload["source_type"] == "local_smoke"
    assert payload["mode"] == "paper"
    assert payload["live_trading_enabled"] is False
    assert payload["exchange_mutation_enabled"] is False
    assert payload["real_order_submitted"] is False
    assert payload["live_gate_mutation_enabled"] is False
