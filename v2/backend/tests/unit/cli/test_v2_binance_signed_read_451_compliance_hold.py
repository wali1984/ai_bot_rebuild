from __future__ import annotations

from pathlib import Path

from v2.backend.app.cli.v2_live_transport_balance_aware_hold_and_first_order_monitor import (
    COMPLIANCE_HOLD,
    RESTRICTED_451,
    build_audited_exchange_failover_candidate_matrix,
    build_audited_exchange_failover_selection_proposal,
    build_balance_hold_status,
    build_binance_451_compliance_hold_monitor_status,
    build_binance_public_vs_private_runtime_split_status,
    build_compliant_binance_access_recovery_options,
    build_compliant_exchange_failover_candidate_matrix,
    build_critical_account_read_gate_status,
    build_exchange_failover_gate_contract_status,
    build_failover_exchange_read_only_probe_status,
    build_failover_order_transport_status,
    build_failover_symbol_risk_orchestrator_mapping_status,
    build_retry_guard_status,
    build_signed_read_classification_status,
    build_trader_compliance_hold_state_status,
)


def _runtime_payload() -> dict:
    return {
        "live_gate": "enabled_operator_approved",
        "trader_execution_enabled": True,
        "accepted_live_symbols": ["BTCUSDT"],
        "risk_profile": {
            "profile_name": "conservative_min_executable",
            "fields": {
                "max_leverage": 1.0,
                "max_notional_per_trade": 64.86,
            },
        },
    }


def test_signed_read_451_forces_compliance_hold_and_unknown_margin(tmp_path: Path) -> None:
    account_margin = {
        "ok": False,
        "available_margin": None,
        "wallet_balance": None,
        "endpoint": "GET /fapi/v3/account",
        "transport_public_account_status": {
            "status_code": 451,
            "error_type": "HTTPError",
            "response_redacted": '{"msg":"Service unavailable from a restricted location"}',
        },
    }
    pre_submit = {
        "status": "LIVE_ORDER_TRANSPORT_BLOCKED",
        "blockers": ["BINANCE_ACCOUNT_MARGIN_READ_FAILED"],
        "position_mode_status": {
            "ok": False,
            "status_code": 451,
            "error_type": "HTTPError",
            "response_redacted": '{"msg":"restricted location"}',
        },
    }
    connectivity = {
        "account_read_status": "HTTP_451",
        "position_read_status": "HTTP_451",
        "position_summary": {},
        "account_summary_redacted": {"balances_redacted": True},
    }
    symbol_map = {
        "rows": [
            {
                "symbol": "BTCUSDT",
                "min_executable_notional": 64.86,
                "min_executable_qty": 0.001,
                "filter_status": {"ok": True},
            }
        ]
    }

    classification = build_signed_read_classification_status(
        account_margin=account_margin,
        pre_submit=pre_submit,
        connectivity=connectivity,
    )
    critical_gate = build_critical_account_read_gate_status(
        signed_classification=classification,
        symbol_map=symbol_map,
    )
    balance_hold = build_balance_hold_status(
        runtime_payload=_runtime_payload(),
        pre_submit=pre_submit,
        symbol_map=symbol_map,
        account_margin=account_margin,
        critical_account_gate=critical_gate,
    )
    retry_guard = build_retry_guard_status(
        repo_root=tmp_path,
        balance_hold=balance_hold,
        pre_submit=pre_submit,
        account_margin=account_margin,
    )
    trader_hold = build_trader_compliance_hold_state_status(
        runtime_payload=_runtime_payload(),
        critical_account_gate=critical_gate,
        signed_classification=classification,
    )

    assert classification["classification"] == "API_RESTRICTED_LOCATION_451"
    assert critical_gate["status"] == "BLOCKED_BINANCE_SIGNED_READ_RESTRICTED"
    assert balance_hold["trader_state"] == COMPLIANCE_HOLD
    assert balance_hold["available_margin"] is None
    assert balance_hold["retry_allowed"] is False
    assert RESTRICTED_451 in balance_hold["blockers"]
    assert retry_guard["retry_allowed"] is False
    assert retry_guard["retry_blocked_reason"] == RESTRICTED_451
    assert trader_hold["trader_state"] == COMPLIANCE_HOLD
    assert trader_hold["order_submitted"] is False


def test_recovery_or_failover_artifacts_keep_private_execution_held(tmp_path: Path) -> None:
    classification = {
        "classification": "API_RESTRICTED_LOCATION_451",
        "restricted_location_detected": True,
        "signed_endpoint_rows": [
            {
                "endpoint": "GET /fapi/v3/account",
                "classification": "API_RESTRICTED_LOCATION_451",
                "http_status": 451,
                "request_type": "account info / balance",
                "signed": True,
                "account_critical": True,
            }
        ],
    }
    critical_gate = {
        "status": "BLOCKED_BINANCE_SIGNED_READ_RESTRICTED",
        "restricted_location_detected": True,
        "account_critical_reads": {
            "account_info": "BLOCKED",
            "balance": "BLOCKED",
            "positions": "BLOCKED",
            "open_orders": "BLOCKED",
            "exchange_filters": "BLOCKED",
            "position_mode": "BLOCKED",
        },
        "blockers": ["BINANCE_SIGNED_READ_RESTRICTED_LOCATION_451"],
    }
    balance_hold = {
        "trader_state": COMPLIANCE_HOLD,
        "available_margin": None,
    }
    symbol_map = {"rows": [{"symbol": "BTCUSDT", "filter_status": {"ok": False}, "blockers": ["SYMBOL_FILTERS_UNVERIFIED"]}]}

    monitor = build_binance_451_compliance_hold_monitor_status(
        repo_root=tmp_path,
        signed_classification=classification,
        critical_account_gate=critical_gate,
        symbol_map=symbol_map,
        balance_hold=balance_hold,
    )
    split = build_binance_public_vs_private_runtime_split_status(
        repo_root=tmp_path,
        signal_publish_initial={"status": "ok"},
        signal_publish={"status": "ok"},
        orchestration={"status": "ok"},
        risk_gateway={"status": "ok"},
        paper={"status": "ok"},
        signed_classification=classification,
        critical_account_gate=critical_gate,
    )
    recovery = build_compliant_binance_access_recovery_options()
    matrix = build_compliant_exchange_failover_candidate_matrix(tmp_path)
    contract = build_exchange_failover_gate_contract_status()

    assert monitor["status"] == "BINANCE_451_COMPLIANCE_HOLD_ACTIVE"
    assert monitor["order_submission_allowed"] is False
    assert monitor["available_margin"] is None
    assert split["status"] == "BINANCE_PUBLIC_RUNTIME_CONTINUES_PRIVATE_EXECUTION_HELD"
    assert split["private_binance_execution_keep_held"]["order_submit"] is True
    assert "VPN/proxy/evasion" in recovery["disallowed_options"]
    assert matrix["automatic_live_failover_allowed"] is False
    assert any(row["exchange"] == "KuCoin" for row in matrix["candidates"])
    assert contract["audited_operator_acceptance_required"] is True
    assert contract["automatic_failover_allowed"] is False


def test_audited_failover_selection_artifacts_do_not_enable_order_submission(tmp_path: Path) -> None:
    runtime = _runtime_payload()
    signal_status = {
        "signals": [
            {
                "symbol": "BTCUSDT",
                "prediction_id": "pred_btc",
                "risk_decision_id": "risk_btc",
                "orchestrator_decision_id": "orch_btc",
                "signal_id": "sig_btc",
            }
        ]
    }
    split = {
        "status": "BINANCE_PUBLIC_RUNTIME_CONTINUES_PRIVATE_EXECUTION_HELD",
        "private_execution_status": "COMPLIANCE_HELD_HTTP_451",
    }

    matrix = build_audited_exchange_failover_candidate_matrix(
        repo_root=tmp_path,
        runtime_payload=runtime,
        public_private_split=split,
    )
    selection = build_audited_exchange_failover_selection_proposal(matrix=matrix, runtime_payload=runtime)
    probe = build_failover_exchange_read_only_probe_status(repo_root=tmp_path, selection=selection)
    transport = build_failover_order_transport_status(selection=selection, probe=probe)
    mapping = build_failover_symbol_risk_orchestrator_mapping_status(
        selection=selection,
        runtime_payload=runtime,
        signal_status=signal_status,
    )

    assert matrix["automatic_live_failover_allowed"] is False
    assert matrix["recommended_exchange"] == "KuCoin"
    assert selection["proposed_exchange"] == "KuCoin"
    assert selection["operator_acceptance_required"] is True
    assert probe["probe_performed"] is False
    assert probe["probe_passed"] is False
    assert transport["order_transport_enabled"] is False
    assert transport["order_submission_allowed"] is False
    assert transport["places_real_order"] is False
    assert mapping["order_submission_allowed"] is False
    assert mapping["rows"][0]["mapping_verified"] is False
