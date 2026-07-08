from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "v2" / "backend"))

from v2.backend.app.cli import v2_runtime_drift_monitor as monitor


def _by_name(alerts: list[dict], name: str) -> dict:
    for alert in alerts:
        if alert["name"] == name:
            return alert
    raise AssertionError(f"missing alert: {name}")


def test_required_alerts_fire_for_bad_paper_performance_without_false_entry_alert() -> None:
    alerts = monitor.evaluate_required_alerts(
        {
            "repo_head_commit": "repo",
            "repo_head_backend_commit": "backend",
            "stale_services": [],
            "profit_factor": 0.8,
            "expectancy_bps": -2.5,
            "closed_trades": 6,
            "new_entries_allowed": False,
            "halt_reasons": ["PF_BELOW_ONE", "EXPECTANCY_NON_POSITIVE"],
            "trainer_feedback_rows": 6,
            "trainer_weights_status": "WEIGHTS_UPDATING",
            "prediction_key_count": 10,
            "prediction_grid_age_seconds": 30,
            "market_data_age_seconds": 45,
            "orderbook_trust_age_seconds": 60,
            "outcome_memory_age_seconds": 70,
            "paper_online_runtime_active": False,
            "live_gate": "blocked_human_only",
            "exchange_mutation_detected": False,
            "website_truth_pass": True,
            "ios_truth_pass": True,
            "santiment_symbol_count": 15,
        }
    )

    assert _by_name(alerts, "PF < 1 after 5 trades")["fires"] is True
    assert _by_name(alerts, "expectancy <= 0 after 5 trades")["fires"] is True
    assert _by_name(alerts, "new entries allowed while halted")["fires"] is False
    assert _by_name(alerts, "paid ingestor unused")["fires"] is False
    assert _by_name(alerts, "website stale-current mismatch")["fires"] is False
    assert _by_name(alerts, "iOS stale-current mismatch")["fires"] is False


def test_runtime_drift_alert_exposes_f0008_restart_evidence() -> None:
    alerts = monitor.evaluate_required_alerts(
        {
            "repo_head_commit": "repo_head",
            "repo_head_backend_commit": "backend_head",
            "stale_services": [
                {
                    "unit": "ai-bot-v2-public-website-backend.service",
                    "service_running_commit": "old123",
                    "service_restart_required": True,
                    "schema_version_mismatch": True,
                }
            ],
            "closed_trades": 0,
            "trainer_weights_status": "WEIGHTS_UPDATING",
            "prediction_key_count": 1,
            "prediction_grid_age_seconds": 1,
            "market_data_age_seconds": 1,
            "orderbook_trust_age_seconds": 1,
            "outcome_memory_age_seconds": 1,
            "paper_online_runtime_active": False,
            "live_gate": "blocked_human_only",
            "exchange_mutation_detected": False,
            "website_truth_pass": True,
            "ios_truth_pass": True,
            "santiment_symbol_count": 1,
        }
    )

    drift = _by_name(alerts, "runtime code commit differs from repo/service commit")
    schema = _by_name(alerts, "feature schema changed but service not restarted")

    assert drift["fires"] is True
    assert drift["evidence"]["service_running_commit"] == "old123"
    assert drift["evidence"]["repo_head_commit"] == "repo_head"
    assert drift["evidence"]["service_restart_required"] is True
    assert drift["evidence"]["schema_version_mismatch"] is True
    assert schema["fires"] is True


def test_runtime_collection_counts_singular_prediction_namespace(monkeypatch) -> None:
    scanned: list[str] = []

    def fake_scan_count(_client, pattern: str, *, limit: int = 10000) -> int:
        scanned.append(pattern)
        return 7 if pattern == "v2:prediction:*" else 0

    monkeypatch.setattr(monitor, "_redis_client", lambda: object())
    monkeypatch.setattr(monitor, "_redis_json", lambda _client, _key: {})
    monkeypatch.setattr(monitor, "_read_status_file", lambda _relative: {})
    monkeypatch.setattr(monitor, "_redis_scan_count", fake_scan_count)
    monkeypatch.setattr(monitor, "_run", lambda _cmd: "inactive")

    runtime = monitor.collect_runtime_inputs(stale_services=[], repo_head="repo", backend_commit="backend")

    assert runtime["prediction_key_count"] == 7
    assert "v2:prediction:*" in scanned
    assert "v2:predictions:*" in scanned
