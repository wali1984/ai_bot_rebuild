from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth.users import UserStore
from app.main import create_app


def _authenticated_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    auth_store = tmp_path / "auth_users.json"
    monkeypatch.setenv("ALPHAFORGE_AUTH_STORE", str(auth_store))
    monkeypatch.setenv("ALPHAFORGE_AUTH_SECRET", "test-secret-for-live-gate")
    UserStore(auth_store).create_user(
        email="superadmin@example.com",
        username="superadmin",
        password="super-password",
        role="superadmin",
    )
    test_client = TestClient(create_app())
    response = test_client.post("/api/auth/login", json={"email": "superadmin@example.com", "password": "super-password"})
    assert response.status_code == 200
    return test_client


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    payload_dir = tmp_path / "v2/frontend/public/v2_cuda_trainer_gpu_trader_binance_live_gate_single_pass/latest"
    payload_dir.mkdir(parents=True)
    (payload_dir / "operator_dashboard_payload.json").write_text(
        json.dumps(
            {
                "go_no_go": "V2_CUDA_TRAINER_GPU_TRADER_BINANCE_LIVE_GATE_SINGLE_PASS_BLOCKED",
                "live_gate": "blocked_human_only",
                "live_symbols": [],
                "execution_live_symbols": [],
                "trader_execution_enabled": False,
                "places_real_order": False,
                "exact_blockers": ["BACKTEST_EDGE_BLOCKED_NO_EDGE_CLAIM"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("V2_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("V2_LIVE_GATE_RUNTIME_DISABLE_REDIS_WRITES", "1")
    return _authenticated_client(tmp_path, monkeypatch)


def test_live_gate_status_is_readonly_blocked(client: TestClient) -> None:
    response = client.get("/api/v1/live-gate/status")
    assert response.status_code == 200
    body = response.json()
    assert body["live_gate"] == "blocked_human_only"
    assert body["live_symbols"] == []
    assert body["trader_execution_enabled"] is False


def test_live_gate_enable_requires_typed_confirmation(client: TestClient) -> None:
    response = client.post("/api/v1/live-gate/enable", json={})
    assert response.status_code == 400
    assert response.json()["detail"]["reason"] == "TYPED_CONFIRMATION_REQUIRED"


def test_live_gate_enable_stays_locked_with_blockers(client: TestClient) -> None:
    response = client.post(
        "/api/v1/live-gate/enable",
        json={"typed_confirmation": "ENABLE V2 LIVE EXECUTION"},
    )
    assert response.status_code == 423
    detail = response.json()["detail"]
    assert detail["enabled"] is False
    assert detail["live_gate"] == "blocked_human_only"
    assert detail["live_symbols"] == []


def test_live_gate_enable_path_available_when_new_packet_ready(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload_dir = tmp_path / "v2/frontend/public/v2_paper_fill_gate_live_blocker_burndown_and_controlled_live_enable_ready/latest"
    payload_dir.mkdir(parents=True)
    (payload_dir / "operator_dashboard_payload.json").write_text(
        json.dumps(
            {
                "verdict": "LIVE_OPERATOR_ENABLE_AVAILABLE",
                "backend_live_enable_callable": True,
                "live_enable_blockers": [],
                "live_gate": "blocked_human_only",
                "live_symbols": [],
                "execution_live_symbols": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("V2_REPO_ROOT", str(tmp_path))
    test_client = _authenticated_client(tmp_path, monkeypatch)

    evaluate = test_client.post("/api/v1/live-gate/evaluate")
    assert evaluate.status_code == 200
    assert evaluate.json()["evaluation"]["result"] == "BLOCKED"
    assert "risk_profile_operator_accepted" in evaluate.json()["exact_blockers"]

    enable = test_client.post(
        "/api/v1/live-gate/enable",
        json={"typed_confirmation": "ENABLE V2 LIVE EXECUTION"},
    )
    assert enable.status_code == 423
    assert enable.json()["detail"]["reason"] == "LIVE_GATE_BLOCKED"


def test_audited_acceptance_flow_makes_backend_gate_callable_without_runtime_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload_dir = tmp_path / "v2/frontend/public/v2_paper_fill_gate_live_blocker_burndown_and_controlled_live_enable_ready/latest"
    payload_dir.mkdir(parents=True)
    risk_profile = {
        "cooldown_seconds": 1200,
        "kill_switch_conditions": [
            "any_mutation_before_final_gate",
            "daily_loss_cap_breach",
            "drawdown_cap_breach",
        ],
        "max_daily_loss": 15.0,
        "max_drawdown": 75.0,
        "max_leverage": 1.0,
        "max_notional_per_trade": 25.0,
        "max_open_positions": 1,
        "max_slippage_bps": 2.0,
        "max_spread_bps": 3.5,
        "max_symbol_exposure": 45.0,
        "max_total_exposure": 100.0,
        "min_confidence_calibrated": 0.66,
        "min_expected_move_after_cost_bps": 12.0,
    }
    (payload_dir / "operator_dashboard_payload.json").write_text(
        json.dumps(
            {
                "generated_est": "2026-06-05T12:00:00-04:00",
                "service_id": "paper_fill_gate",
                "verdict": "LIVE_GATE_BLOCKED_RISK_CAPS_OPERATOR_REQUIRED",
                "backend_live_enable_callable": False,
                "live_gate": "blocked_human_only",
                "live_symbols": [],
                "execution_live_symbols": [],
                "final_live_gate": {
                    "requirements": {
                        "paper_fill_gate_accepts_fills": True,
                        "paper_edge_backtest_not_critically_negative": True,
                        "binance_trader_connected": True,
                        "exchange_mutation_safety_passed": True,
                        "codex_final_live_pass_exists": True,
                        "live_symbols_remain_empty_until_operator_acceptance": True,
                        "no_unresolved_critical_data_blocker": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    (payload_dir / "live_gate_risk_cap_proposal_after_paper_fill.json").write_text(
        json.dumps({"profiles": {"conservative": risk_profile}}),
        encoding="utf-8",
    )
    (payload_dir / "live_symbol_candidate_proposal_after_paper_fill.json").write_text(
        json.dumps({"proposed_live_symbols": ["BTCUSDT", "ETHUSDT"]}),
        encoding="utf-8",
    )
    (payload_dir / "paper_fill_gate_block_reason_inventory.json").write_text(
        json.dumps(
            {
                "paper_signals": 2,
                "accepted_paper_fills": 2,
                "held_by_paper_fill_gate": 0,
                "paper_signal_rows": [
                    {
                        "symbol": "BTCUSDT",
                        "prediction_id": "pred_btc",
                        "winner_proposal_id": "pred_btc",
                        "paper_fill_allowed": True,
                        "paper_fill_gate_status": "PAPER_FILL_ALLOWED_BY_ORCHESTRATOR_GATE",
                        "feature_freshness_state": "CURRENT",
                        "live_gate": "blocked_human_only",
                        "places_real_order": False,
                    },
                    {
                        "symbol": "ETHUSDT",
                        "prediction_id": "pred_eth",
                        "winner_proposal_id": "pred_eth",
                        "paper_fill_allowed": True,
                        "paper_fill_gate_status": "PAPER_FILL_ALLOWED_BY_ORCHESTRATOR_GATE",
                        "feature_freshness_state": "CURRENT",
                        "live_gate": "blocked_human_only",
                        "places_real_order": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("V2_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("V2_LIVE_GATE_RUNTIME_REDIS_REQUIRED", "0")
    monkeypatch.setenv("V2_LIVE_GATE_RUNTIME_DISABLE_REDIS_WRITES", "1")
    test_client = _authenticated_client(tmp_path, monkeypatch)

    risk = test_client.post(
        "/api/v1/live-gate/accept-risk-profile",
        json={
            "profile_id": "conservative",
            "profile_name": "conservative",
            "risk_fields": risk_profile,
            "operator_confirmation_text": "ACCEPT V2 LIVE RISK PROFILE",
            "operator_reason": "unit test risk acceptance",
            "source_payload_id": "paper_fill_gate:2026-06-05T12:00:00-04:00",
        },
    )
    assert risk.status_code == 200
    risk_audit_id = risk.json()["audit_id"]

    symbols = test_client.post(
        "/api/v1/live-gate/accept-live-symbols",
        json={
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "operator_confirmation_text": "ACCEPT V2 LIVE SYMBOLS",
            "operator_reason": "unit test symbol acceptance",
            "source_payload_id": "paper_fill_gate:2026-06-05T12:00:00-04:00",
        },
    )
    assert symbols.status_code == 200
    symbol_audit_id = symbols.json()["audit_id"]

    final = test_client.post(
        "/api/v1/live-gate/final-approval",
        json={
            "accepted_risk_audit_id": risk_audit_id,
            "accepted_symbols_audit_id": symbol_audit_id,
            "operator_confirmation_text": "APPROVE V2 LIVE EXECUTION FINAL GATE",
            "operator_reason": "unit test final approval",
            "source_payload_id": "paper_fill_gate:2026-06-05T12:00:00-04:00",
        },
    )
    assert final.status_code == 200

    evaluate = test_client.post("/api/v1/live-gate/evaluate")
    assert evaluate.status_code == 200
    body = evaluate.json()
    assert body["evaluation"]["result"] == "LIVE_OPERATOR_ENABLE_AVAILABLE"
    assert body["backend_live_enable_callable"] is True
    assert body["live_symbols"] == []

    enable = test_client.post(
        "/api/v1/live-gate/enable",
        json={
            "typed_confirmation": "ENABLE V2 LIVE EXECUTION",
            "operator_reason": "unit test enable",
            "accepted_risk_audit_id": risk_audit_id,
            "accepted_symbols_audit_id": symbol_audit_id,
            "final_approval_audit_id": final.json()["audit_id"],
        },
    )
    assert enable.status_code == 200
    enable_body = enable.json()
    assert enable_body["backend_live_enable_path_available"] is True
    assert enable_body["enabled"] is True
    assert enable_body["runtime_mutation_executed"] is True
    assert enable_body["accepted_live_symbols_for_final_enable"] == ["BTCUSDT", "ETHUSDT"]
    assert enable_body["live_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert enable_body["execution_live_symbols"] == ["BTCUSDT", "ETHUSDT"]

    runtime_state = (
        tmp_path
        / "v2/frontend/public/operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json"
    )
    assert runtime_state.exists()


def test_failover_acceptance_flow_writes_audit_but_does_not_enable_orders(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failover_dir = (
        tmp_path
        / "v2/frontend/public/v2_audited_exchange_failover_selection_and_transport_implementation/latest"
    )
    failover_dir.mkdir(parents=True)
    (failover_dir / "audited_exchange_failover_candidate_matrix.json").write_text(
        json.dumps(
            {
                "schema_version": "audited_exchange_failover_candidate_matrix_v1",
                "candidates": [
                    {
                        "exchange": "KuCoin",
                        "operator_approval_required": True,
                        "legal_operator_approval_required": True,
                        "credentials_present_by_name": ["KUCOIN_API_KEY"],
                        "raw_credentials_exposed": False,
                    }
                ],
                "automatic_live_failover_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    (failover_dir / "audited_exchange_failover_selection_proposal.json").write_text(
        json.dumps(
            {
                "schema_version": "audited_exchange_failover_selection_proposal_v1",
                "proposed_exchange": "KuCoin",
                "proposed_symbols": ["BTCUSDT", "ETHUSDT"],
                "operator_acceptance_required": True,
                "account_probe_required": True,
            }
        ),
        encoding="utf-8",
    )
    (failover_dir / "operator_dashboard_payload.json").write_text(
        json.dumps(
            {
                "binance_private_execution_status": "COMPLIANCE_HELD_HTTP_451",
                "order_submission_allowed": False,
                "automatic_live_failover_allowed": False,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("V2_REPO_ROOT", str(tmp_path))
    test_client = _authenticated_client(tmp_path, monkeypatch)

    exchange = test_client.post(
        "/api/v1/live-gate/accept-failover-exchange",
        json={
            "exchange": "KuCoin",
            "operator_confirmation_text": "ACCEPT V2 LIVE FAILOVER EXCHANGE",
            "operator_reason": "unit test failover exchange acceptance",
            "source_payload_id": "audited_failover:test",
            "operator_legal_access_attested": True,
        },
    )
    assert exchange.status_code == 200
    exchange_body = exchange.json()
    assert exchange_body["failover_exchange_operator_accepted"] is True
    assert exchange_body["failover_live_enabled"] is False
    assert exchange_body["order_submission_allowed"] is False

    symbols = test_client.post(
        "/api/v1/live-gate/accept-failover-symbols",
        json={
            "symbols": ["BTCUSDT"],
            "operator_confirmation_text": "ACCEPT V2 LIVE FAILOVER SYMBOLS",
            "operator_reason": "unit test failover symbol acceptance",
            "source_payload_id": "audited_failover:test",
        },
    )
    assert symbols.status_code == 200
    symbols_body = symbols.json()
    assert symbols_body["failover_symbol_operator_accepted"] is True
    assert symbols_body["order_submission_allowed"] is False

    final = test_client.post(
        "/api/v1/live-gate/failover-final-approval",
        json={
            "accepted_failover_exchange_audit_id": exchange_body["audit_id"],
            "accepted_failover_symbols_audit_id": symbols_body["audit_id"],
            "operator_confirmation_text": "APPROVE V2 LIVE FAILOVER FINAL GATE",
            "operator_reason": "unit test failover final approval",
            "source_payload_id": "audited_failover:test",
        },
    )
    assert final.status_code == 200
    final_body = final.json()
    assert final_body["failover_final_operator_approval_present"] is True
    assert final_body["read_only_probe_required_before_transport_enable"] is True
    assert final_body["order_submission_allowed"] is False

    audit = json.loads((failover_dir / "failover_gate_audit_record_status.json").read_text(encoding="utf-8"))
    assert audit["record_count"] == 3
    assert audit["order_submission_allowed"] is False
    assert audit["records"][0]["confirmation_text_hash"]
    assert "ACCEPT V2 LIVE FAILOVER EXCHANGE" not in json.dumps(audit)


def test_live_gate_accepts_exchange_filter_min_executable_profile_from_proposal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload_dir = tmp_path / "v2/frontend/public/v2_paper_fill_gate_live_blocker_burndown_and_controlled_live_enable_ready/latest"
    payload_dir.mkdir(parents=True)
    exchange_dir = tmp_path / "v2/frontend/public/v2_exchange_filter_risk_profile_alignment_and_min_order_execution/latest"
    exchange_dir.mkdir(parents=True)
    conservative = {
        "cooldown_seconds": 1200,
        "kill_switch_conditions": ["daily_loss_cap_breach"],
        "max_daily_loss": 15.0,
        "max_drawdown": 75.0,
        "max_leverage": 1.0,
        "max_notional_per_trade": 25.0,
        "max_open_positions": 1,
        "max_slippage_bps": 2.0,
        "max_spread_bps": 3.5,
        "max_symbol_exposure": 45.0,
        "max_total_exposure": 100.0,
        "min_confidence_calibrated": 0.66,
        "min_expected_move_after_cost_bps": 12.0,
    }
    amended = {**conservative, "max_notional_per_trade": 65.0, "max_symbol_exposure": 65.0}
    (payload_dir / "operator_dashboard_payload.json").write_text(
        json.dumps(
            {
                "generated_est": "2026-06-07T12:00:00-04:00",
                "service_id": "paper_fill_gate",
                "live_gate": "blocked_human_only",
                "live_symbols": [],
                "execution_live_symbols": [],
            }
        ),
        encoding="utf-8",
    )
    (payload_dir / "live_gate_risk_cap_proposal_after_paper_fill.json").write_text(
        json.dumps({"profiles": {"conservative": conservative}}),
        encoding="utf-8",
    )
    (exchange_dir / "executable_minimum_conservative_risk_profile_proposal.json").write_text(
        json.dumps(
            {
                "schema_version": "executable_minimum_conservative_risk_profile_proposal_v1",
                "source_payload_id": "sha256:unit",
                "profile": {
                    "profile_id": "conservative_min_executable",
                    "profile_name": "conservative_min_executable",
                    "risk_fields": amended,
                },
                "profiles": {"conservative_min_executable": amended},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("V2_REPO_ROOT", str(tmp_path))
    test_client = _authenticated_client(tmp_path, monkeypatch)

    response = test_client.post(
        "/api/v1/live-gate/accept-risk-profile",
        json={
            "profile_id": "conservative_min_executable",
            "profile_name": "conservative_min_executable",
            "risk_fields": amended,
            "operator_confirmation_text": "ACCEPT V2 LIVE RISK PROFILE",
            "operator_reason": "unit test exchange filter risk amendment",
            "source_payload_id": "sha256:unit",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["risk_profile_operator_accepted"] is True
    assert body["accepted_profile_name"] == "conservative_min_executable"
    assert body["accepted_profile_fields"] == amended
