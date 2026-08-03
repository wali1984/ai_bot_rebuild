from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from scripts.run_production_stream_alerting_smoke import build_report, main


def test_production_stream_alerting_smoke_passes_for_public_safe_evidence(tmp_path: Path) -> None:
    alerting = tmp_path / "alerting.json"
    dashboard = tmp_path / "dashboard.json"
    stream_status = tmp_path / "stream-status.json"
    alerting.write_text(
        """{
          "production_alerting_integrated": true,
          "stale_alerts_enabled": true,
          "reconnect_alerts_enabled": true,
          "lag_monitoring_enabled": true,
          "missing_source_alerts_enabled": true,
          "public_market_data_only": true,
          "contains_credentials": false,
          "live_trading_enabled": false,
          "exchange_mutation_enabled": false
        }""",
        encoding="utf-8",
    )
    dashboard.write_text('{"dashboard_integrated": true, "public_market_data_only": true}', encoding="utf-8")
    stream_status.write_text('{"source":"market_stream_status","live_trading_enabled":false}', encoding="utf-8")

    report = build_report(
        alerting_config_paths=[alerting],
        dashboard_evidence_paths=[dashboard],
        stream_status_paths=[stream_status],
    )

    assert report["production_alerting_status"] == "passed"
    assert report["status"] == "passed"
    assert report["production_alerting_integrated"] is True
    assert report["dashboard_integrated"] is True
    assert report["stale_alerts_enabled"] is True
    assert report["reconnect_alerts_enabled"] is True
    assert report["lag_monitoring_enabled"] is True
    assert report["missing_source_alerts_enabled"] is True
    assert report["contains_credentials"] is False
    assert report["live_trading_enabled"] is False
    assert report["exchange_mutation_enabled"] is False
    assert report["missing_fields"] == []


def test_production_stream_alerting_smoke_fails_without_dashboard_evidence(tmp_path: Path) -> None:
    alerting = tmp_path / "alerting.json"
    stream_status = tmp_path / "stream-status.json"
    alerting.write_text(
        """{
          "production_alerting_integrated": true,
          "stale_alerts_enabled": true,
          "reconnect_alerts_enabled": true,
          "lag_monitoring_enabled": true,
          "missing_source_alerts_enabled": true,
          "public_market_data_only": true,
          "live_trading_enabled": false,
          "exchange_mutation_enabled": false
        }""",
        encoding="utf-8",
    )
    stream_status.write_text('{"live_trading_enabled":false,"exchange_mutation_enabled":false}', encoding="utf-8")

    report = build_report(
        alerting_config_paths=[alerting],
        dashboard_evidence_paths=[],
        stream_status_paths=[stream_status],
    )

    assert report["production_alerting_status"] == "failed"
    assert "dashboard_integrated" in report["missing_fields"]
    assert any("No dashboard evidence" in warning for warning in report["warnings"])


def test_production_stream_alerting_smoke_fails_on_credentials_or_live_flags(tmp_path: Path) -> None:
    alerting = tmp_path / "alerting.json"
    dashboard = tmp_path / "dashboard.json"
    stream_status = tmp_path / "stream-status.json"
    alerting.write_text(
        """{
          "production_alerting_integrated": true,
          "stale_alerts_enabled": true,
          "reconnect_alerts_enabled": true,
          "lag_monitoring_enabled": true,
          "missing_source_alerts_enabled": true,
          "public_market_data_only": true,
          "api_key": "unsafe-live-key",
          "live_trading_enabled": true,
          "exchange_mutation_enabled": true
        }""",
        encoding="utf-8",
    )
    dashboard.write_text('{"dashboard_integrated": true}', encoding="utf-8")
    stream_status.write_text('{"source":"market_stream_status"}', encoding="utf-8")

    report = build_report(
        alerting_config_paths=[alerting],
        dashboard_evidence_paths=[dashboard],
        stream_status_paths=[stream_status],
    )

    assert report["production_alerting_status"] == "failed"
    assert report["contains_credentials"] is True
    assert report["live_trading_enabled"] is True
    assert report["exchange_mutation_enabled"] is True
    assert "credential_free_public_payloads" in report["missing_fields"]
    assert "live_trading_disabled" in report["missing_fields"]
    assert "exchange_mutation_disabled" in report["missing_fields"]


def test_production_stream_alerting_smoke_cli_writes_artifact(tmp_path: Path) -> None:
    alerting = tmp_path / "alerting.json"
    dashboard = tmp_path / "dashboard.json"
    stream_status = tmp_path / "stream-status.json"
    output = tmp_path / "artifact" / "production-stream-alerting.json"
    alerting.write_text(
        """{
          "production_alerting_integrated": true,
          "stale_alerts_enabled": true,
          "reconnect_alerts_enabled": true,
          "lag_monitoring_enabled": true,
          "missing_source_alerts_enabled": true,
          "public_market_data_only": true,
          "contains_credentials": false,
          "live_trading_enabled": false,
          "exchange_mutation_enabled": false
        }""",
        encoding="utf-8",
    )
    dashboard.write_text('{"dashboard_integrated": true}', encoding="utf-8")
    stream_status.write_text('{"live_trading_enabled": false, "exchange_mutation_enabled": false}', encoding="utf-8")

    exit_code = main(
        [
            "--alerting-config-path",
            str(alerting),
            "--dashboard-evidence-path",
            str(dashboard),
            "--stream-status-path",
            str(stream_status),
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["production_alerting_status"] == "passed"
    assert payload["source"] == "local_production_stream_alerting_smoke"
    assert payload["source_type"] == "local_smoke"
    assert payload["mode"] == "read_only"
    assert payload["live_trading_enabled"] is False
    assert payload["exchange_mutation_enabled"] is False
