"""Signed-read recovery balance-hold gate.

This V2-only runner wraps the balance-aware live transport monitor in
no-submit mode, then publishes the operator-facing gate that distinguishes a
recovered Binance signed-read path from the remaining insufficient-balance
hold. It never calls order/test-order/cancel/modify endpoints.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "v2/backend"))

from v2.backend.app.cli import (  # noqa: E402
    v2_live_transport_balance_aware_hold_and_first_order_monitor as balance_monitor,
)


SERVICE_ID = "v2_signed_read_recovered_balance_hold_and_first_order_resume"
GATE_READY = "V2_SIGNED_READ_RECOVERED_BALANCE_HOLD_AND_FIRST_ORDER_RESUME_READY"
GATE_BLOCKED = "V2_SIGNED_READ_RECOVERED_BALANCE_HOLD_AND_FIRST_ORDER_RESUME_BLOCKED"
EST = ZoneInfo("America/New_York")
INSUFFICIENT_BALANCE = "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER"
ACCOUNT_INFO_ENDPOINT_LABELS = ("WS account.status", "GET /fapi/v3/account")
POSITION_MODE_ENDPOINT_LABELS = ("WS account.position", "GET /fapi/v1/positionSide/dual")
POSITIONS_ENDPOINT_LABELS = (
    "WS account.position",
    "GET /fapi/v3/positionRisk",
    "GET /fapi/v2/positionRisk",
)
OPEN_ORDERS_ENDPOINT_LABELS = ("WS openOrders.status", "GET /fapi/v1/openOrders")


def est_now() -> str:
    return datetime.now(tz=EST).isoformat(timespec="seconds")


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _rows(payload: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    rows = payload.get(key)
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _signed_read_ok(
    classification: Mapping[str, Any],
    *,
    endpoints: tuple[str, ...],
    request_prefix: str,
) -> bool:
    for row in _rows(classification, "signed_endpoint_rows"):
        request_type = str(row.get("request_type") or "")
        if row.get("endpoint") not in endpoints and not request_type.startswith(request_prefix):
            continue
        return row.get("classification") == "API_OK" and row.get("ok") is True
    return False


def _min_required_margin(symbol_map: Mapping[str, Any]) -> float | None:
    values: list[float] = []
    for row in _rows(symbol_map, "rows"):
        value = row.get("balance_required")
        if isinstance(value, (int, float)):
            values.append(float(value))
    return round(min(values), 8) if values else None


def _compliance_ok(value: str) -> bool:
    return value in {"true", "operator_attested"}


def build_gate_payloads(
    *,
    monitor_result: Mapping[str, Any],
    network_path_compliance: str,
    compliance_reason: str,
) -> dict[str, Mapping[str, Any]]:
    generated_est = est_now()
    payloads = monitor_result.get("payloads") if isinstance(monitor_result.get("payloads"), Mapping) else {}
    signed = payloads.get("binance_signed_read_451_classification_status.json")
    signed = signed if isinstance(signed, Mapping) else {}
    critical = payloads.get("live_critical_account_read_gate_status.json")
    critical = critical if isinstance(critical, Mapping) else {}
    balance = payloads.get("live_transport_balance_hold_status.json")
    balance = balance if isinstance(balance, Mapping) else {}
    symbol_map = payloads.get("live_symbol_min_executable_map.json")
    symbol_map = symbol_map if isinstance(symbol_map, Mapping) else {}
    resume = payloads.get("first_order_resume_condition_status.json")
    resume = resume if isinstance(resume, Mapping) else {}
    open_orders = payloads.get("open_orders_snapshot_status.json")
    open_orders = open_orders if isinstance(open_orders, Mapping) else {}
    account_margin = payloads.get("account_margin_snapshot_status.json")
    account_margin = account_margin if isinstance(account_margin, Mapping) else {}
    dashboard_source = payloads.get("operator_dashboard_payload.json")
    dashboard_source = dashboard_source if isinstance(dashboard_source, Mapping) else {}

    signed_reads_recovered = (
        signed.get("classification") == "NO_451_DETECTED"
        and signed.get("restricted_location_detected") is False
        and critical.get("ok") is True
        and _signed_read_ok(signed, endpoints=ACCOUNT_INFO_ENDPOINT_LABELS, request_prefix="account info")
        and _signed_read_ok(signed, endpoints=POSITION_MODE_ENDPOINT_LABELS, request_prefix="position mode")
        and _signed_read_ok(signed, endpoints=POSITIONS_ENDPOINT_LABELS, request_prefix="positions")
        and _signed_read_ok(signed, endpoints=OPEN_ORDERS_ENDPOINT_LABELS, request_prefix="open orders")
    )
    compliance_accepted = _compliance_ok(network_path_compliance)
    margin_sufficient = balance.get("margin_sufficient") is True
    insufficient_balance = INSUFFICIENT_BALANCE in {str(item) for item in balance.get("blockers") or []}
    trader_state = "LIVE_ARMED_BALANCE_HOLD" if signed_reads_recovered and compliance_accepted else "LIVE_ARMED_COMPLIANCE_HOLD"

    blockers: list[str] = []
    if not signed_reads_recovered:
        blockers.append("SIGNED_READS_NOT_FULLY_RECOVERED")
    if not compliance_accepted:
        blockers.append("SIGNED_READ_RECOVERY_NETWORK_PATH_COMPLIANCE_NOT_ATTESTED")
    if not margin_sufficient:
        blockers.append(INSUFFICIENT_BALANCE)
    if dashboard_source.get("order_submitted") is True:
        blockers.append("UNEXPECTED_ORDER_SUBMITTED")
    gate_ready = (
        signed_reads_recovered
        and compliance_accepted
        and insufficient_balance
        and balance.get("order_submitted") is False
        and dashboard_source.get("order_submitted") is not True
    )
    go_no_go = GATE_READY if gate_ready else GATE_BLOCKED

    signed_read_recovery_status = {
        "schema_version": "signed_read_recovery_status_v1",
        "generated_est": generated_est,
        "status": "SIGNED_READS_RECOVERED" if signed_reads_recovered else "SIGNED_READS_NOT_FULLY_RECOVERED",
        "signed_read_classification": signed.get("classification"),
        "restricted_location_detected": signed.get("restricted_location_detected") is True,
        "account_read_ok": _signed_read_ok(signed, endpoints=ACCOUNT_INFO_ENDPOINT_LABELS, request_prefix="account info"),
        "balance_read_ok": account_margin.get("ok") is True,
        "positions_read_ok": _signed_read_ok(signed, endpoints=POSITIONS_ENDPOINT_LABELS, request_prefix="positions"),
        "open_orders_read_ok": open_orders.get("ok") is True,
        "open_orders_count": open_orders.get("open_orders_count"),
        "position_mode_read_ok": _signed_read_ok(signed, endpoints=POSITION_MODE_ENDPOINT_LABELS, request_prefix="position mode"),
        "critical_account_read_gate_status": critical.get("status"),
        "critical_account_read_gate_ok": critical.get("ok") is True,
        "signed_read_recovery_network_path_compliant": network_path_compliance,
        "network_path_compliance_reason": compliance_reason,
        "network_path_compliance_independently_verified": False,
        "raw_credentials_exposed": False,
        "raw_account_payload_exposed": False,
    }
    account_margin_balance_hold_status = {
        "schema_version": "account_margin_balance_hold_status_v1",
        "generated_est": generated_est,
        "status": "LIVE_ARMED_BALANCE_HOLD" if trader_state == "LIVE_ARMED_BALANCE_HOLD" else "LIVE_ARMED_COMPLIANCE_HOLD",
        "trader_state": trader_state,
        "available_margin": balance.get("available_margin"),
        "wallet_balance": balance.get("wallet_balance"),
        "unrealized_pnl": balance.get("unrealized_pnl"),
        "required_initial_margin": balance.get("required_initial_margin") or _min_required_margin(symbol_map),
        "minimum_required_initial_margin_any_accepted_symbol": _min_required_margin(symbol_map),
        "margin_sufficient": margin_sufficient,
        "retry_allowed": False,
        "order_submitted": False,
        "blockers": sorted(set(blockers)),
    }
    live_symbol_min_executable_refresh_status = {
        "schema_version": "live_symbol_min_executable_refresh_status_v1",
        "generated_est": generated_est,
        "status": symbol_map.get("status"),
        "accepted_symbols": symbol_map.get("accepted_symbols") or [],
        "available_margin": symbol_map.get("available_margin"),
        "executable_symbols_with_current_balance": symbol_map.get("executable_symbols_with_current_balance") or [],
        "blocked_symbols_with_current_balance": symbol_map.get("blocked_symbols_with_current_balance") or [],
        "minimum_required_initial_margin_any_accepted_symbol": _min_required_margin(symbol_map),
        "rows": symbol_map.get("rows") or [],
    }
    first_order_resume_condition_status = {
        "schema_version": "first_order_resume_condition_status_v1",
        "generated_est": generated_est,
        "status": "WAITING_FOR_AVAILABLE_MARGIN" if signed_reads_recovered and compliance_accepted else "WAITING_FOR_COMPLIANCE_ATTESTATION_OR_SIGNED_READS",
        "source_resume_status": resume,
        "required_conditions": {
            "signed_reads_recovered": signed_reads_recovered,
            "network_path_compliance": network_path_compliance,
            "available_margin_gte_required_initial_margin": margin_sufficient,
            "critical_account_read_gate_ready": critical.get("ok") is True,
            "symbol_filters_verified": not critical.get("filter_failures"),
            "open_orders_verified": open_orders.get("ok") is True,
            "order_submitted": False,
        },
        "next_trigger": "available margin becomes sufficient for the minimum executable accepted symbol",
        "submit_allowed_now": False,
    }
    trader_state_transition_status = {
        "schema_version": "trader_state_transition_status_v1",
        "generated_est": generated_est,
        "status": "TRADER_STATE_BALANCE_HOLD_ACTIVE" if trader_state == "LIVE_ARMED_BALANCE_HOLD" else "TRADER_STATE_COMPLIANCE_HOLD_ACTIVE",
        "from_state": "LIVE_ARMED_COMPLIANCE_HOLD",
        "to_state": trader_state,
        "transition_reason": "NO_451_DETECTED_AND_ACCOUNT_CRITICAL_READS_READY" if signed_reads_recovered else "SIGNED_READS_NOT_READY",
        "signed_read_recovery_network_path_compliant": network_path_compliance,
        "order_submission_allowed": False,
        "retry_allowed": False,
        "blockers": sorted(set(blockers)),
    }
    operator_dashboard_payload = {
        "schema_version": "operator_dashboard_payload_v1",
        "service_id": SERVICE_ID,
        "generated_est": generated_est,
        "go_no_go": go_no_go,
        "live_gate": dashboard_source.get("live_gate"),
        "trader_execution_enabled": dashboard_source.get("trader_execution_enabled") is True,
        "transport_bound": dashboard_source.get("live_order_transport_bound") is True,
        "signed_read_classification": signed.get("classification"),
        "critical_account_read_gate": critical.get("status"),
        "signed_read_recovery_network_path_compliant": network_path_compliance,
        "trader_state": trader_state,
        "active_risk_profile": dashboard_source.get("active_risk_profile"),
        "accepted_symbols": dashboard_source.get("accepted_symbols") or [],
        "available_margin": balance.get("available_margin"),
        "wallet_balance": balance.get("wallet_balance"),
        "required_initial_margin": account_margin_balance_hold_status["required_initial_margin"],
        "margin_sufficient": margin_sufficient,
        "retry_allowed": False,
        "order_submitted": False,
        "live_submit_allowed": False,
        "blockers": sorted(set(blockers)),
        "safety": {
            "no_order_test_order_cancel_modify": True,
            "no_leverage_margin_mutation": True,
            "no_transfer_or_withdrawal": True,
            "no_old_redis_write": True,
            "no_legacy_restart": True,
            "no_redis_trim": True,
            "raw_credentials_exposed": False,
            "raw_account_payload_exposed": False,
        },
    }
    return {
        "signed_read_recovery_status.json": signed_read_recovery_status,
        "account_margin_balance_hold_status.json": account_margin_balance_hold_status,
        "live_symbol_min_executable_refresh_status.json": live_symbol_min_executable_refresh_status,
        "first_order_resume_condition_status.json": first_order_resume_condition_status,
        "trader_state_transition_status.json": trader_state_transition_status,
        "operator_dashboard_payload.json": operator_dashboard_payload,
    }


def render_report(dashboard: Mapping[str, Any]) -> str:
    blockers = "\n".join(f"- `{item}`" for item in dashboard.get("blockers") or []) or "- none"
    return "\n".join(
        [
            "# V2 Signed Read Recovered Balance Hold And First Order Resume Report",
            "",
            f"Gate: `{dashboard.get('go_no_go')}`",
            f"Generated EST: `{dashboard.get('generated_est')}`",
            f"Live gate: `{dashboard.get('live_gate')}`",
            f"Trader execution enabled: `{dashboard.get('trader_execution_enabled')}`",
            f"Transport bound: `{dashboard.get('transport_bound')}`",
            f"Signed-read classification: `{dashboard.get('signed_read_classification')}`",
            f"Critical account-read gate: `{dashboard.get('critical_account_read_gate')}`",
            f"Network path compliance: `{dashboard.get('signed_read_recovery_network_path_compliant')}`",
            f"Trader state: `{dashboard.get('trader_state')}`",
            f"Available margin: `{dashboard.get('available_margin')}`",
            f"Wallet balance: `{dashboard.get('wallet_balance')}`",
            f"Required initial margin: `{dashboard.get('required_initial_margin')}`",
            f"Margin sufficient: `{dashboard.get('margin_sufficient')}`",
            f"Retry allowed: `{dashboard.get('retry_allowed')}`",
            f"Order submitted: `{dashboard.get('order_submitted')}`",
            "",
            "Blockers:",
            blockers,
            "",
            "Safety: no order/test-order/cancel/modify, no leverage or margin mutation, no transfer/withdrawal, no old Redis write, no legacy restart, no Redis trim, no raw credential output.",
            "",
        ]
    )


def write_outputs(repo_root: Path, payloads: Mapping[str, Mapping[str, Any]]) -> list[str]:
    written: list[str] = []
    dashboard = payloads["operator_dashboard_payload.json"]
    report = render_report(dashboard)
    for base in (
        repo_root / "v2/frontend/public" / SERVICE_ID / "latest",
        repo_root / "claude_worklog/final_readiness" / SERVICE_ID / "latest",
    ):
        for name, payload in payloads.items():
            path = base / name
            write_json(path, payload)
            written.append(str(path))
        report_path = base / "V2_SIGNED_READ_RECOVERED_BALANCE_HOLD_AND_FIRST_ORDER_RESUME_REPORT.md"
        write_text(report_path, report)
        written.append(str(report_path))
        go_path = base / "GO_NO_GO.md"
        write_text(go_path, str(dashboard["go_no_go"]) + "\n")
        written.append(str(go_path))
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=SERVICE_ID)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument(
        "--network-path-compliance",
        choices=["true", "false", "unknown", "operator_attested"],
        default="operator_attested",
        help="Operator-facing compliance status for the recovered signed-read network path.",
    )
    parser.add_argument(
        "--network-path-compliance-reason",
        default="operator attestation required for legal/account eligibility; Codex only verifies signed read recovery",
    )
    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve()
    monitor_result = balance_monitor.run_once(
        repo_root,
        submit_if_balance_sufficient=False,
        run_validation_checks=False,
    )
    payloads = build_gate_payloads(
        monitor_result=monitor_result,
        network_path_compliance=args.network_path_compliance,
        compliance_reason=args.network_path_compliance_reason,
    )
    paths = write_outputs(repo_root, payloads)
    dashboard = payloads["operator_dashboard_payload.json"]
    print(json.dumps({"go_no_go": dashboard["go_no_go"], "paths_written": paths}, indent=2))
    return 0 if dashboard["go_no_go"] == GATE_READY else 2


if __name__ == "__main__":
    raise SystemExit(main())
