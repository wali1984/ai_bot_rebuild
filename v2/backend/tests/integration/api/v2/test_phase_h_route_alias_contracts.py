from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from app.api.v1 import derivatives as v1_derivatives
from app.api.v1 import paper as v1_paper
from app.api.v2 import live_readiness, market_contracts, mobile, system_metrics
from app.main import create_app
from app.services.operator_truth import trade_derivatives_runtime


class FakeRedis:
    def __init__(self, store: dict[str, Any]) -> None:
        self.store = store

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        value = self.store.get(key)
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return json.dumps(value)
        return str(value)

    def exists(self, key: str) -> bool:
        return key in self.store


def _ts() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _derivatives_payload() -> dict[str, Any]:
    ts = _ts()
    rows = [{"symbol": "BTCUSDT", "source_key": "test", "data_status": "CURRENT_OR_RECENT"}]
    return {
        "schema_version": "v2_derivatives_payload_v1",
        "generated_utc": ts,
        "generated_est": ts,
        "payload_age_seconds": 0,
        "symbols": ["BTCUSDT"],
        "source_keys": {
            "funding": "test",
            "open_interest": "test",
            "long_short": "test",
            "basis": "test",
            "liquidations": "test",
        },
        "live_submit_allowed": False,
        "live_submit_blocker": "TEST_BLOCKED",
        "modules": {
            "funding": {"data_status": "CURRENT_OR_RECENT", "rows": rows, "missing_reason_if_any": None},
            "open_interest": {"data_status": "CURRENT_OR_RECENT", "rows": rows, "missing_reason_if_any": None},
            "long_short": {"data_status": "CURRENT_OR_RECENT", "rows": rows, "missing_reason_if_any": None},
            "basis": {"data_status": "CURRENT_OR_RECENT", "rows": rows, "missing_reason_if_any": None},
            "liquidations": {"data_status": "EVENT_WINDOW_EMPTY_BUT_WSS_ACTIVE", "rows": rows, "missing_reason_if_any": None},
        },
        "exchanges": {
            "generated_est": ts,
            "payload_age_seconds": 0,
            "source_keys": "test",
            "data_status": "CURRENT_RUNTIME_SOURCES_PRESENT",
            "rows": [{"exchange": "Binance", "public_data_available": True}],
            "missing_reason_if_any": None,
        },
    }


def _fake_redis() -> FakeRedis:
    ts = _ts()
    return FakeRedis(
        {
            "v2:paper:ledger": {
                "generated_utc": ts,
                "paper_session_id": "phase-h-session",
                "paper_session_state_source": "test",
                "new_entries_allowed": False,
                "paper_new_entries_halted": True,
                "paper_effective_entry_gate_status": "HALTED",
                "open_positions": [{"paper_trade_id": "open-1", "symbol": "BTCUSDT"}],
                "closed_trades": [{"paper_trade_id": "closed-1", "symbol": "ETHUSDT"}],
                "accepted": [],
                "current_cycle_accepted": [],
                "closes": [],
            },
            "v2:portfolio:state": {
                "generated_utc": ts,
                "paper_session_id": "phase-h-session",
                "equity": 2999.0,
            },
            "v2:paper:trade_management:status": {"generated_utc": ts},
            "v2:orchestrator:heartbeat": {
                "started_at": ts,
                "finished_at": ts,
                "classification": "TEST_ORCHESTRATOR",
                "live_gate": "blocked_human_only",
                "approves_live": False,
            },
            "v2:orchestrator:decisions": [{"generated_utc": ts, "decision_id": "orch-1"}],
            "v2:orchestrator:proposals": [{"generated_utc": ts, "proposal_id": "prop-1"}],
            "v2:risk:gateway:heartbeat": {
                "started_at": ts,
                "finished_at": ts,
                "classification": "V2_RISK_GATEWAY_LIVE_OK",
                "live_gate": "blocked_human_only",
                "approves_live": False,
                "fail_closed": True,
            },
            "v2:risk:active_profile": {"profile_id": "test", "profile_name": "test", "fields": {}},
            "v2:risk:gateway:latest": {"classification": "TEST_RISK", "approves_live": False},
            "v2:risk:paper_online_decisions": [{"generated_utc": ts, "risk_decision_id": "risk-1"}],
            "v2:paper:preemptive_edge_control_status": {
                "schema_version": "preemptive_edge_control_status_v1",
                "generated_utc": ts,
                "candidate_count": 7,
                "accepted_count": 0,
                "decision_counts": {"NO_TRADE": 7},
                "accepted_without_preemptive_decision": 0,
                "accepted_high_loss_probability_count": 0,
                "reduced_size_without_guardian_approval_count": 0,
                "hard_fail": False,
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
            },
            "v2:paper:preemptive_candidate_decision_matrix": {
                "schema_version": "preemptive_candidate_decision_matrix_v1",
                "generated_utc": ts,
                "candidate_count": 7,
                "sample_decisions": [
                    {
                        "preemptive_decision_id": "pec_contract_test",
                        "preemptive_decision": "NO_TRADE",
                        "pre_trade_loss_probability": 0.91,
                        "confidence_overstatement_risk": 0.82,
                        "regime_compatibility_score": 0.22,
                        "exit_feasibility_score": 0.31,
                        "bucket_profit_factor": 0.42,
                        "preemptive_decision_reasons": [
                            "BUCKET_PF_OR_EXPECTANCY_NEGATIVE"
                        ],
                    }
                ],
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
            },
            "v2:paper:preemptive_admission_status": {
                "schema_version": "paper_preemptive_admission_status_v1",
                "generated_utc": ts,
                "candidate_count": 7,
                "accepted_count": 0,
                "prevention_reasons": ["BUCKET_PF_OR_EXPECTANCY_NEGATIVE"],
                "hard_fail": False,
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
            },
            "v2:paper:no_bad_entry_runtime_status": {
                "schema_version": "paper_no_bad_entry_runtime_status_v1",
                "generated_utc": ts,
                "status": "PASS_NO_BAD_ENTRY_ACCEPTED",
                "accepted_count": 0,
                "hard_fail": False,
                "paper_only": True,
                "routes_to_live": False,
                "places_real_order": False,
            },
        }
    )


def test_phase_h_required_routes_return_json_not_spa_html(monkeypatch) -> None:
    fake = _fake_redis()
    monkeypatch.setattr(market_contracts, "BINANCE_FAPI_BASE", "http://127.0.0.1:9")
    monkeypatch.setattr(market_contracts, "BINANCE_HTTP_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(market_contracts, "get_redis", lambda: fake)
    monkeypatch.setattr(live_readiness, "get_redis", lambda: fake)
    monkeypatch.setattr(mobile, "get_redis", lambda: fake)
    monkeypatch.setattr(system_metrics, "get_redis", lambda: fake)
    monkeypatch.setattr(v1_paper, "get_redis", lambda: fake)
    monkeypatch.setattr(trade_derivatives_runtime, "json_load", lambda path, default=None: None)
    monkeypatch.setattr(trade_derivatives_runtime, "build_derivatives_payload", _derivatives_payload)
    monkeypatch.setattr(v1_derivatives, "json_load", lambda path, default=None: _derivatives_payload())
    monkeypatch.setattr(v1_derivatives, "build_derivatives_payload", _derivatives_payload)

    client = TestClient(create_app())
    required_paths = [
        "/api/v2/portfolio",
        "/api/v2/paper/runtime-status",
        "/api/v2/trainer/status",
        "/api/v2/signals",
        "/api/v2/markets",
        "/api/v2/derivatives",
        "/api/v2/risk/status",
        "/api/v2/risk",
        "/api/v2/orchestrator",
        "/api/v2/live-readiness",
        "/api/v2/system/health",
        "/api/v2/mobile/risk-status",
        "/api/v1/derivatives/exchanges",
        "/api/v1/derivatives/funding",
        "/api/v1/derivatives/open-interest",
        "/api/v1/derivatives/long-short",
        "/api/v1/derivatives/basis",
        "/api/v1/derivatives/liquidations",
        "/api/v1/paper-trades",
    ]

    for path in required_paths:
        response = client.get(path)
        assert response.status_code == 200, path
        assert "application/json" in response.headers["content-type"], path
        assert not response.text.lstrip().lower().startswith("<!doctype"), path
        response.json()

    assert client.get("/api/v2/risk").json()["endpoint"] == "/api/v2/risk"
    risk_status = client.get("/api/v2/risk/status").json()
    assert risk_status["preemptive_prevention"]["candidate_count"] == 7
    assert risk_status["preemptive_prevention"]["decision_counts"] == {"NO_TRADE": 7}
    assert risk_status["preemptive_prevention"]["hard_fail"] is False
    assert risk_status["preemptive_prevention"]["why_trade_was_prevented"] == [
        "BUCKET_PF_OR_EXPECTANCY_NEGATIVE"
    ]

    paper_runtime = client.get("/api/v2/paper/runtime-status").json()
    assert paper_runtime["preemptive_edge_control"]["candidate_count"] == 7
    assert paper_runtime["preemptive_edge_control"]["accepted_count"] == 0
    assert paper_runtime["preemptive_edge_control"]["decision_counts"] == {"NO_TRADE": 7}
    assert paper_runtime["paper_no_bad_entry_runtime_status"]["status"] == (
        "PASS_NO_BAD_ENTRY_ACCEPTED"
    )

    mobile_risk = client.get("/api/v2/mobile/risk-status").json()
    assert mobile_risk["preemptive_edge_control"]["candidate_count"] == 7
    assert mobile_risk["preemptive_edge_control"]["pre_trade_loss_probability"] == 0.91
    assert mobile_risk["preemptive_edge_control"]["confidence_overstatement_risk"] == 0.82
    assert mobile_risk["preemptive_edge_control"]["why_trade_was_prevented"] == [
        "BUCKET_PF_OR_EXPECTANCY_NEGATIVE"
    ]

    assert client.get("/api/v2/orchestrator").json()["endpoint"] == "/api/v2/orchestrator"
    live_readiness_payload = client.get("/api/v2/live-readiness").json()
    assert live_readiness_payload["data"]["live_submit_allowed"] is False
    live_preemptive = live_readiness_payload["data"]["preemptive_edge_control"]
    assert live_preemptive["status"] == "PREEMPTIVE_EDGE_CONTROL_ACTIVE"
    assert live_preemptive["candidate_count"] == 7
    assert live_preemptive["decision_counts"] == {"NO_TRADE": 7}
    assert live_preemptive["live_dry_run_requires_preemptive_decision"] is True
    assert live_preemptive["live_dry_run_allows_only"] == "ALLOW_A_PLUS_CANDIDATE"
    assert live_preemptive["live_dry_run_currently_blocked_by_preemptive"] is True
    assert live_readiness_payload["data"]["live_dry_run_preemptive_policy"] == {
        "requires_preemptive_decision": True,
        "allow_decision": "ALLOW_A_PLUS_CANDIDATE",
        "fail_closed_if_missing": True,
        "fail_closed_if_not_allow": True,
        "places_real_order": False,
    }
    assert client.get("/api/v2/system/health").json()["data"]["places_real_order"] is False
    assert client.get("/api/v1/paper-trades").json()["data"]["paper_session_id"] == "phase-h-session"
