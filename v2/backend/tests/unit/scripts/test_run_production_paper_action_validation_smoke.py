from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_production_paper_action_validation_smoke import build_report, main


def _write_safe_actions(tmp_path: Path) -> Path:
    path = tmp_path / "production-paper-actions.json"
    path.write_text(
        json.dumps(
            {
                "paper_submit_validated": True,
                "paper_cancel_validated": True,
                "paper_fill_validated": True,
                "production_paper_actions_fail_closed": True,
                "service_verified_paper_only": True,
                "trader_scope_enforced": True,
                "paper_account_scope_enforced": True,
                "backend_owned_order_ids": True,
                "durable_repository_verified": True,
                "audit_event_linked": True,
                "contains_credentials": False,
                "live_transport_enabled": False,
                "exchange_mutation_enabled": False,
                "real_order_submitted": False,
                "real_order_cancelled": False,
                "leverage_mutation_enabled": False,
                "margin_mutation_enabled": False,
                "live_gate_mutation_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_production_paper_action_validation_smoke_passes_for_safe_evidence(tmp_path: Path) -> None:
    evidence = _write_safe_actions(tmp_path)

    report = build_report(evidence_paths=[evidence])

    assert report["production_paper_action_validation_smoke_status"] == "passed"
    assert report["production_paper_submit_cancel_validation_status"] == "passed"
    assert report["paper_submit_validated"] is True
    assert report["paper_cancel_validated"] is True
    assert report["paper_fill_validated"] is True
    assert report["production_paper_actions_fail_closed"] is True
    assert report["service_verified_paper_only"] is True
    assert report["trader_scope_enforced"] is True
    assert report["paper_account_scope_enforced"] is True
    assert report["durable_repository_verified"] is True
    assert report["audit_event_linked"] is True
    assert report["missing_fields"] == []


def test_production_paper_action_validation_smoke_accepts_disabled_fill_policy(tmp_path: Path) -> None:
    evidence = _write_safe_actions(tmp_path)
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload["paper_fill_validated"] = False
    payload["paper_fill_disabled_by_policy"] = True
    evidence.write_text(json.dumps(payload), encoding="utf-8")

    report = build_report(evidence_paths=[evidence])

    assert report["production_paper_action_validation_smoke_status"] == "passed"
    assert report["paper_fill_validated"] is False
    assert report["paper_fill_disabled_by_policy"] is True
    assert "paper_fill_validated_or_policy_disabled" not in report["missing_fields"]


def test_production_paper_action_validation_smoke_fails_missing_action_scope_and_audit(tmp_path: Path) -> None:
    evidence = tmp_path / "partial-actions.json"
    evidence.write_text(
        json.dumps(
            {
                "paper_submit_validated": True,
                "live_transport_enabled": False,
                "exchange_mutation_enabled": False,
                "real_order_submitted": False,
                "real_order_cancelled": False,
                "leverage_mutation_enabled": False,
                "margin_mutation_enabled": False,
                "live_gate_mutation_enabled": False,
            }
        ),
        encoding="utf-8",
    )

    report = build_report(evidence_paths=[evidence])

    assert report["production_paper_action_validation_smoke_status"] == "failed"
    assert "paper_cancel_validated" in report["missing_fields"]
    assert "paper_fill_validated_or_policy_disabled" in report["missing_fields"]
    assert "trader_scope_enforced" in report["missing_fields"]
    assert "paper_account_scope_enforced" in report["missing_fields"]
    assert "audit_event_linked" in report["missing_fields"]


def test_production_paper_action_validation_smoke_fails_secret_or_live_mutation(tmp_path: Path) -> None:
    evidence = _write_safe_actions(tmp_path)
    payload = json.loads(evidence.read_text(encoding="utf-8"))
    payload.update(
        {
            "api_secret": "unsafe-secret-value",
            "live_transport_enabled": True,
            "exchange_mutation_enabled": True,
            "real_order_submitted": True,
            "real_order_cancelled": True,
            "leverage_mutation_enabled": True,
            "margin_mutation_enabled": True,
            "live_gate_mutation_enabled": True,
        }
    )
    evidence.write_text(json.dumps(payload), encoding="utf-8")

    report = build_report(evidence_paths=[evidence])

    assert report["production_paper_action_validation_smoke_status"] == "failed"
    assert report["contains_credentials"] is True
    assert report["live_transport_enabled"] is True
    assert report["exchange_mutation_enabled"] is True
    assert report["real_order_submitted"] is True
    assert report["real_order_cancelled"] is True
    assert "credential_free_paper_action_evidence" in report["missing_fields"]
    assert "live_transport_disabled" in report["missing_fields"]
    assert "exchange_mutation_disabled" in report["missing_fields"]
    assert "real_order_submission_absent" in report["missing_fields"]
    assert "real_order_cancellation_absent" in report["missing_fields"]
    assert "leverage_mutation_absent" in report["missing_fields"]
    assert "margin_mutation_absent" in report["missing_fields"]
    assert "live_gate_mutation_absent" in report["missing_fields"]


def test_production_paper_action_validation_smoke_cli_writes_artifact(tmp_path: Path) -> None:
    evidence = _write_safe_actions(tmp_path)
    output = tmp_path / "artifact" / "production-paper-actions.json"

    exit_code = main([
        "--evidence-path",
        str(evidence),
        "--output",
        str(output),
    ])

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["production_paper_action_validation_smoke_status"] == "passed"
    assert payload["source"] == "local_production_paper_action_validation_smoke"
    assert payload["source_type"] == "local_smoke"
    assert payload["mode"] == "paper"
    assert payload["real_order_submitted"] is False
    assert payload["real_order_cancelled"] is False
    assert payload["live_gate_mutation_enabled"] is False
