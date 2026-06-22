from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_auth_session_hardening_smoke import build_report, main


def _write_safe_evidence(tmp_path: Path) -> tuple[Path, Path, Path]:
    session = tmp_path / "session.json"
    rbac = tmp_path / "rbac.json"
    safety = tmp_path / "safety.json"
    session.write_text(
        json.dumps(
            {
                "production_auth_secret_configured": True,
                "auth_secret_strength_verified": True,
                "issuer_configured": True,
                "audience_configured": True,
                "secure_cookie_enabled": True,
                "cookie_samesite_configured": True,
                "session_ttl_enforced": True,
                "refresh_rotation_enabled": True,
                "revocation_store_durable": True,
                "session_version_invalidation_enabled": True,
                "password_change_revokes_sessions": True,
                "admin_step_up_enabled": True,
            }
        ),
        encoding="utf-8",
    )
    rbac.write_text(
        json.dumps(
            {
                "backend_role_checks_enforced": True,
                "unauthorized_admin_blocked": True,
                "superadmin_admin_rejected": True,
            }
        ),
        encoding="utf-8",
    )
    safety.write_text(
        json.dumps(
            {
                "contains_credentials": False,
                "token_exposure_found": False,
                "plaintext_password_exposure_found": False,
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
                "live_submit_available": False,
                "live_cancel_available": False,
                "leverage_mutation_available": False,
                "margin_mutation_available": False,
            }
        ),
        encoding="utf-8",
    )
    return session, rbac, safety


def test_auth_session_hardening_smoke_passes_for_safe_evidence(tmp_path: Path) -> None:
    session, rbac, safety = _write_safe_evidence(tmp_path)

    report = build_report(
        session_evidence_paths=[session],
        rbac_evidence_paths=[rbac],
        safety_evidence_paths=[safety],
    )

    assert report["production_auth_session_hardening_status"] == "passed"
    assert report["auth_secret_strength_verified"] is True
    assert report["revocation_store_durable"] is True
    assert report["backend_role_checks_enforced"] is True
    assert report["contains_credentials"] is False
    assert report["live_trading_enabled"] is False
    assert report["exchange_mutation_enabled"] is False
    assert report["missing_fields"] == []


def test_auth_session_hardening_smoke_fails_without_required_evidence(tmp_path: Path) -> None:
    _session, rbac, safety = _write_safe_evidence(tmp_path)

    report = build_report(
        session_evidence_paths=[],
        rbac_evidence_paths=[rbac],
        safety_evidence_paths=[safety],
    )

    assert report["production_auth_session_hardening_status"] == "failed"
    assert "production_auth_secret_configured" in report["missing_fields"]
    assert any("No auth/session evidence" in warning for warning in report["warnings"])


def test_auth_session_hardening_smoke_fails_on_secret_token_or_live_mutation(tmp_path: Path) -> None:
    session, rbac, safety = _write_safe_evidence(tmp_path)
    safety.write_text(
        json.dumps(
            {
                "access_token": "unsafe-token-value",
                "plaintext_password_exposure_found": True,
                "live_trading_enabled": True,
                "exchange_mutation_enabled": True,
                "live_submit_available": True,
                "live_cancel_available": True,
                "leverage_mutation_available": True,
                "margin_mutation_available": True,
            }
        ),
        encoding="utf-8",
    )

    report = build_report(
        session_evidence_paths=[session],
        rbac_evidence_paths=[rbac],
        safety_evidence_paths=[safety],
    )

    assert report["production_auth_session_hardening_status"] == "failed"
    assert "no_credential_exposure" in report["missing_fields"]
    assert "no_plaintext_password_exposure" in report["missing_fields"]
    assert "live_trading_disabled" in report["missing_fields"]
    assert "exchange_mutation_disabled" in report["missing_fields"]
    assert "live_submit_unavailable" in report["missing_fields"]
    assert "live_cancel_unavailable" in report["missing_fields"]
    assert "leverage_mutation_unavailable" in report["missing_fields"]
    assert "margin_mutation_unavailable" in report["missing_fields"]


def test_auth_session_hardening_smoke_cli_writes_artifact(tmp_path: Path) -> None:
    session, rbac, safety = _write_safe_evidence(tmp_path)
    output = tmp_path / "artifact" / "auth-session-hardening.json"

    exit_code = main(
        [
            "--session-evidence-path",
            str(session),
            "--rbac-evidence-path",
            str(rbac),
            "--safety-evidence-path",
            str(safety),
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["production_auth_session_hardening_status"] == "passed"
    assert payload["source"] == "local_auth_session_hardening_smoke"
    assert payload["source_type"] == "local_smoke"
    assert payload["mode"] == "read_only"
    assert payload["live_trading_enabled"] is False
    assert payload["exchange_mutation_enabled"] is False
