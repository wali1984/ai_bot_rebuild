from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_production_https_smoke import build_report, main


def _write_safe_evidence(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    route = tmp_path / "routes.json"
    status = tmp_path / "status.json"
    auth = tmp_path / "auth.json"
    console = tmp_path / "console.json"
    safety = tmp_path / "safety.json"
    route.write_text(
        json.dumps(
            {
                "base_url": "https://alpha.example.com",
                "https_enabled": True,
                "routes": [
                    "/",
                    "/login",
                    "/status",
                    "/dashboard",
                    "/markets",
                    "/market/BTCUSDT",
                    "/trade",
                    "/account-settings",
                    "/chart/BTCUSDT",
                    "/admin",
                ],
            }
        ),
        encoding="utf-8",
    )
    status.write_text('{"public_status_checked":true,"public_status_safe":true}', encoding="utf-8")
    auth.write_text(
        '{"auth_gate_checked":true,"admin_unauthenticated_blocked":true,"superadmin_admin_rejected":true}',
        encoding="utf-8",
    )
    console.write_text('{"console_error_count":0}', encoding="utf-8")
    safety.write_text(
        """{
          "secret_exposure_found": false,
          "live_trading_enabled": false,
          "exchange_mutation_enabled": false,
          "live_submit_available": false,
          "live_cancel_available": false,
          "leverage_mutation_available": false,
          "margin_mutation_available": false
        }""",
        encoding="utf-8",
    )
    return route, status, auth, console, safety


def test_production_https_smoke_passes_for_safe_https_evidence(tmp_path: Path) -> None:
    route, status, auth, console, safety = _write_safe_evidence(tmp_path)

    report = build_report(
        route_evidence_paths=[route],
        status_evidence_paths=[status],
        auth_evidence_paths=[auth],
        console_evidence_paths=[console],
        safety_evidence_paths=[safety],
    )

    assert report["production_https_smoke_status"] == "passed"
    assert report["https_enabled"] is True
    assert report["routes_checked"] is True
    assert report["public_status_safe"] is True
    assert report["auth_gate_checked"] is True
    assert report["console_errors_absent"] is True
    assert report["secret_exposure_found"] is False
    assert report["live_trading_enabled"] is False
    assert report["exchange_mutation_enabled"] is False
    assert report["missing_fields"] == []


def test_production_https_smoke_fails_without_required_evidence(tmp_path: Path) -> None:
    route, _status, auth, console, safety = _write_safe_evidence(tmp_path)

    report = build_report(
        route_evidence_paths=[route],
        status_evidence_paths=[],
        auth_evidence_paths=[auth],
        console_evidence_paths=[console],
        safety_evidence_paths=[safety],
    )

    assert report["production_https_smoke_status"] == "failed"
    assert "public_status_checked" in report["missing_fields"]
    assert any("No public status smoke evidence" in warning for warning in report["warnings"])


def test_production_https_smoke_requires_exact_route_evidence(tmp_path: Path) -> None:
    route, status, auth, console, safety = _write_safe_evidence(tmp_path)
    route.write_text('{"base_url":"https://alpha.example.com","https_enabled":true}', encoding="utf-8")

    report = build_report(
        route_evidence_paths=[route],
        status_evidence_paths=[status],
        auth_evidence_paths=[auth],
        console_evidence_paths=[console],
        safety_evidence_paths=[safety],
    )

    assert report["production_https_smoke_status"] == "failed"
    assert report["routes_checked"] is False
    assert "route_checked:/trade" in report["missing_fields"]
    assert "route_checked:/status" in report["missing_fields"]


def test_production_https_smoke_fails_on_http_secret_or_live_mutation(tmp_path: Path) -> None:
    route, status, auth, console, safety = _write_safe_evidence(tmp_path)
    route.write_text(
        json.dumps(
            {
                "base_url": "http://alpha.example.com",
                "routes": [
                    "/",
                    "/login",
                    "/status",
                    "/dashboard",
                    "/markets",
                    "/market/BTCUSDT",
                    "/trade",
                    "/account-settings",
                    "/chart/BTCUSDT",
                    "/admin",
                ],
            }
        ),
        encoding="utf-8",
    )
    safety.write_text(
        json.dumps(
            {
                "api_secret": "unsafe-secret-value",
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
        route_evidence_paths=[route],
        status_evidence_paths=[status],
        auth_evidence_paths=[auth],
        console_evidence_paths=[console],
        safety_evidence_paths=[safety],
    )

    assert report["production_https_smoke_status"] == "failed"
    assert "https_enabled" in report["missing_fields"]
    assert "no_insecure_http_origin" in report["missing_fields"]
    assert "no_secret_exposure" in report["missing_fields"]
    assert "live_trading_disabled" in report["missing_fields"]
    assert "exchange_mutation_disabled" in report["missing_fields"]
    assert "live_submit_unavailable" in report["missing_fields"]
    assert "live_cancel_unavailable" in report["missing_fields"]
    assert "leverage_mutation_unavailable" in report["missing_fields"]
    assert "margin_mutation_unavailable" in report["missing_fields"]


def test_production_https_smoke_cli_writes_artifact(tmp_path: Path) -> None:
    route, status, auth, console, safety = _write_safe_evidence(tmp_path)
    output = tmp_path / "artifact" / "production-https-smoke.json"

    exit_code = main(
        [
            "--route-evidence-path",
            str(route),
            "--status-evidence-path",
            str(status),
            "--auth-evidence-path",
            str(auth),
            "--console-evidence-path",
            str(console),
            "--safety-evidence-path",
            str(safety),
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["production_https_smoke_status"] == "passed"
    assert payload["source"] == "local_production_https_smoke"
    assert payload["source_type"] == "local_smoke"
    assert payload["mode"] == "read_only"
    assert payload["live_trading_enabled"] is False
    assert payload["exchange_mutation_enabled"] is False
