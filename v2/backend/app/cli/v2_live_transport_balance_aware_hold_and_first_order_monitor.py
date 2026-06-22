"""Balance-aware live transport hold and first-order monitor.

This runner is V2-only. It keeps the audited live transport armed, but holds
order submission after an insufficient-margin condition until the signed
read-only Binance account balance satisfies the minimum executable order
requirement plus the active conservative risk profile constraints.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "v2/backend"))

from v2.backend.app.cli import (  # noqa: E402
    v2_all_timeframe_prediction_signal_price_target_publisher as signal_cli,
)
from v2.backend.app.cli import v2_orchestrator_arbitration_loop as orchestrator_loop  # noqa: E402
from v2.backend.app.cli import v2_risk_gateway_live_loop as risk_gateway_loop  # noqa: E402
from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop  # noqa: E402
from v2.backend.app.cli.v2_exchange_filter_risk_profile_alignment_and_min_order_execution import (  # noqa: E402
    ACCEPTED_SYMBOLS,
    _current_price,
    _float,
    connect_redis,
    read_json,
    redis_json,
    safe_run,
    signals_by_symbol,
    write_json,
)
from v2.backend.app.services.all_timeframe_prediction_signal_price_target_publisher import (  # noqa: E402
    default_paths as signal_default_paths,
)
from v2.backend.app.services.live_gate.binance_live_order_transport import (  # noqa: E402
    KEY_STATUS,
    BinanceUsdMLiveOrderTransport,
    _exchange_credentials_status,
    _redact_response,
    evaluate_live_order_transport,
)
from v2.backend.app.services.live_gate.exchange_filter_sizing import min_executable_order  # noqa: E402
from v2.backend.app.services.live_gate.runtime_execution_state import (  # noqa: E402
    LIVE_GATE_ENABLED,
    read_runtime_execution_state,
    refresh_runtime_execution_state_heartbeat,
)
from v2.backend.app.services.live_gate.single_pass import (  # noqa: E402
    _est_iso,
    build_binance_connectivity_status,
    default_paths as live_gate_default_paths,
)


GATE_READY = "V2_LIVE_TRANSPORT_BALANCE_AWARE_HOLD_AND_FIRST_ORDER_MONITOR_READY"
GATE_BLOCKED = "V2_LIVE_TRANSPORT_BALANCE_AWARE_HOLD_AND_FIRST_ORDER_MONITOR_BLOCKED"
COMPLIANCE_GATE_READY = "V2_BINANCE_SIGNED_READ_451_HOLD_AND_COMPLIANT_CONNECTIVITY_RECOVERY_READY"
COMPLIANCE_GATE_BLOCKED = "V2_BINANCE_SIGNED_READ_451_HOLD_AND_COMPLIANT_CONNECTIVITY_RECOVERY_BLOCKED"
RECOVERY_FAILOVER_GATE_READY = "V2_COMPLIANT_EXCHANGE_CONNECTIVITY_RECOVERY_OR_FAILOVER_READY"
RECOVERY_FAILOVER_GATE_BLOCKED = "V2_COMPLIANT_EXCHANGE_CONNECTIVITY_RECOVERY_OR_FAILOVER_BLOCKED"
AUDITED_FAILOVER_GATE_READY = "V2_AUDITED_EXCHANGE_FAILOVER_SELECTION_AND_TRANSPORT_IMPLEMENTATION_READY"
AUDITED_FAILOVER_GATE_BLOCKED = "V2_AUDITED_EXCHANGE_FAILOVER_SELECTION_AND_TRANSPORT_IMPLEMENTATION_BLOCKED"
SERVICE_ID = "v2_live_transport_balance_aware_hold_and_first_order_monitor"
COMPLIANCE_SERVICE_ID = "v2_binance_signed_read_451_hold_and_compliant_connectivity_recovery"
RECOVERY_FAILOVER_SERVICE_ID = "v2_compliant_exchange_connectivity_recovery_or_failover"
AUDITED_FAILOVER_SERVICE_ID = "v2_audited_exchange_failover_selection_and_transport_implementation"
ARTIFACT_REL = Path(SERVICE_ID) / "latest"
COMPLIANCE_ARTIFACT_REL = Path(COMPLIANCE_SERVICE_ID) / "latest"
RECOVERY_FAILOVER_ARTIFACT_REL = Path(RECOVERY_FAILOVER_SERVICE_ID) / "latest"
AUDITED_FAILOVER_ARTIFACT_REL = Path(AUDITED_FAILOVER_SERVICE_ID) / "latest"
PUBLIC_DIR_REL = Path("v2/frontend/public") / ARTIFACT_REL
WORKLOG_DIR_REL = Path("claude_worklog/final_readiness") / ARTIFACT_REL
COMPLIANCE_PUBLIC_DIR_REL = Path("v2/frontend/public") / COMPLIANCE_ARTIFACT_REL
COMPLIANCE_WORKLOG_DIR_REL = Path("claude_worklog/final_readiness") / COMPLIANCE_ARTIFACT_REL
RECOVERY_FAILOVER_PUBLIC_DIR_REL = Path("v2/frontend/public") / RECOVERY_FAILOVER_ARTIFACT_REL
RECOVERY_FAILOVER_WORKLOG_DIR_REL = Path("claude_worklog/final_readiness") / RECOVERY_FAILOVER_ARTIFACT_REL
AUDITED_FAILOVER_PUBLIC_DIR_REL = Path("v2/frontend/public") / AUDITED_FAILOVER_ARTIFACT_REL
AUDITED_FAILOVER_WORKLOG_DIR_REL = Path("claude_worklog/final_readiness") / AUDITED_FAILOVER_ARTIFACT_REL
INSUFFICIENT_BALANCE = "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER"
RESTRICTED_451 = "BINANCE_SIGNED_READ_RESTRICTED_LOCATION_451"
RESTRICTED_451_HTTP = "BINANCE_SIGNED_READ_RESTRICTED_LOCATION_HTTP_451"
COMPLIANCE_HOLD = "LIVE_ARMED_COMPLIANCE_HOLD"
EST = ZoneInfo("America/New_York")


def est_now() -> str:
    return datetime.now(tz=EST).isoformat(timespec="seconds")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def mirror_outputs(repo_root: Path, payloads: Mapping[str, Mapping[str, Any]], report: str) -> list[str]:
    written: list[str] = []
    go_no_go = str(payloads["operator_dashboard_payload.json"]["go_no_go"])
    for base in (repo_root / PUBLIC_DIR_REL, repo_root / WORKLOG_DIR_REL):
        base.mkdir(parents=True, exist_ok=True)
        for name, payload in payloads.items():
            path = base / name
            write_json(path, payload)
            written.append(str(path))
        report_path = base / "V2_LIVE_TRANSPORT_BALANCE_AWARE_HOLD_AND_FIRST_ORDER_MONITOR_REPORT.md"
        write_text(report_path, report)
        written.append(str(report_path))
        go_path = base / "GO_NO_GO.md"
        write_text(go_path, go_no_go + "\n")
        written.append(str(go_path))
    return written


def run_signal_publisher(repo_root: Path) -> dict[str, Any]:
    args = signal_cli.parse_args(
        [
            "--repo-root",
            str(repo_root),
            "--production-base-url",
            "http://127.0.0.1:5177",
            "--routes",
        ]
    )
    return signal_cli.run_once(args)


def _round_money(value: Any) -> float | None:
    number = _float(value)
    return round(number, 8) if number is not None else None


def _hash_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _account_margin_snapshot(repo_root: Path, transport: BinanceUsdMLiveOrderTransport) -> dict[str, Any]:
    env_status = _exchange_credentials_status(repo_root / "v2/.env.local")
    public_credential_status = {k: v for k, v in env_status.items() if not str(k).startswith("_")}
    if not env_status.get("api_key_present") or not env_status.get("api_secret_present"):
        return {
            "schema_version": "live_transport_account_margin_snapshot_v1",
            "generated_est": est_now(),
            "status": "BINANCE_CREDENTIALS_MISSING",
            "ok": False,
            "credential_status": public_credential_status,
            "available_margin": None,
            "wallet_balance": None,
            "unrealized_pnl": None,
            "raw_credentials_exposed": False,
        }
    raw = transport.fetch_account_margin_status(
        api_key=str(env_status["_api_key"]),
        api_secret=str(env_status["_api_secret"]),
    )
    available = _round_money(raw.get("_available_balance_usdt"))
    wallet = _round_money(raw.get("_wallet_balance_usdt"))
    unrealized = _round_money(raw.get("_unrealized_pnl_usdt"))
    public = {k: v for k, v in raw.items() if not str(k).startswith("_")}
    return {
        "schema_version": "live_transport_account_margin_snapshot_v1",
        "generated_est": est_now(),
        "status": "ACCOUNT_MARGIN_READ_OK" if raw.get("ok") is True else "ACCOUNT_MARGIN_READ_BLOCKED",
        "ok": raw.get("ok") is True,
        "endpoint": raw.get("endpoint"),
        "credential_status": public_credential_status,
        "can_trade": raw.get("can_trade"),
        "available_margin": available,
        "wallet_balance": wallet,
        "unrealized_pnl": unrealized,
        "available_margin_checked": raw.get("available_balance_checked") is True,
        "wallet_balance_checked": raw.get("wallet_balance_checked") is True,
        "unrealized_pnl_checked": raw.get("unrealized_pnl_checked") is True,
        "transport_public_account_status": public,
        "raw_credentials_exposed": False,
        "raw_account_payload_exposed": False,
    }


def _open_orders_snapshot(repo_root: Path, transport: BinanceUsdMLiveOrderTransport) -> dict[str, Any]:
    env_status = _exchange_credentials_status(repo_root / "v2/.env.local")
    public_credential_status = {k: v for k, v in env_status.items() if not str(k).startswith("_")}
    if not env_status.get("api_key_present") or not env_status.get("api_secret_present"):
        return {
            "schema_version": "live_transport_open_orders_snapshot_v1",
            "generated_est": est_now(),
            "status": "BINANCE_CREDENTIALS_MISSING",
            "ok": False,
            "credential_status": public_credential_status,
            "endpoint": "GET /fapi/v1/openOrders",
            "open_orders_count": None,
            "raw_credentials_exposed": False,
            "raw_open_orders_payload_exposed": False,
        }
    params = {"timestamp": str(transport._clock_ms()), "recvWindow": "5000"}
    body = urllib.parse.urlencode(params)
    signature = hmac.new(
        str(env_status["_api_secret"]).encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    request = urllib.request.Request(
        f"{transport.base_url}/fapi/v1/openOrders?{body}&signature={signature}",
        headers={"X-MBX-APIKEY": str(env_status["_api_key"]), "User-Agent": "v2-live-order-transport/1.0"},
        method="GET",
    )
    try:
        with transport._urlopen(request, timeout=8.0) as response:
            response_text = response.read().decode("utf-8", errors="replace")
            status_code = int(getattr(response, "status", 200))
            payload = json.loads(response_text)
    except urllib.error.HTTPError as exc:
        response_text = exc.read().decode("utf-8", errors="replace")
        return {
            "schema_version": "live_transport_open_orders_snapshot_v1",
            "generated_est": est_now(),
            "status": "OPEN_ORDERS_READ_BLOCKED",
            "ok": False,
            "credential_status": public_credential_status,
            "endpoint": "GET /fapi/v1/openOrders",
            "status_code": int(exc.code),
            "error_type": "HTTPError",
            "response_redacted": _redact_response(response_text),
            "open_orders_count": None,
            "raw_credentials_exposed": False,
            "raw_open_orders_payload_exposed": False,
        }
    except Exception as exc:
        return {
            "schema_version": "live_transport_open_orders_snapshot_v1",
            "generated_est": est_now(),
            "status": "OPEN_ORDERS_READ_BLOCKED",
            "ok": False,
            "credential_status": public_credential_status,
            "endpoint": "GET /fapi/v1/openOrders",
            "status_code": None,
            "error_type": type(exc).__name__,
            "open_orders_count": None,
            "raw_credentials_exposed": False,
            "raw_open_orders_payload_exposed": False,
        }
    return {
        "schema_version": "live_transport_open_orders_snapshot_v1",
        "generated_est": est_now(),
        "status": "OPEN_ORDERS_READ_OK" if 200 <= status_code < 300 and isinstance(payload, list) else "OPEN_ORDERS_READ_BLOCKED",
        "ok": 200 <= status_code < 300 and isinstance(payload, list),
        "credential_status": public_credential_status,
        "endpoint": "GET /fapi/v1/openOrders",
        "status_code": status_code,
        "open_orders_count": len(payload) if isinstance(payload, list) else None,
        "raw_credentials_exposed": False,
        "raw_open_orders_payload_exposed": False,
    }


def _accepted_symbols(runtime_payload: Mapping[str, Any]) -> list[str]:
    symbols = [str(item).upper() for item in runtime_payload.get("accepted_live_symbols") or [] if str(item)]
    return symbols or list(ACCEPTED_SYMBOLS)


def _risk_fields(runtime_payload: Mapping[str, Any]) -> dict[str, Any]:
    profile = runtime_payload.get("risk_profile") if isinstance(runtime_payload.get("risk_profile"), Mapping) else {}
    fields = profile.get("fields") if isinstance(profile.get("fields"), Mapping) else {}
    return dict(fields)


def build_min_executable_map(
    *,
    redis_client: Any,
    transport: BinanceUsdMLiveOrderTransport,
    signal_status: Mapping[str, Any],
    runtime_payload: Mapping[str, Any],
    account_margin: Mapping[str, Any],
) -> dict[str, Any]:
    generated_est = est_now()
    symbols = _accepted_symbols(runtime_payload)
    signal_by_symbol = signals_by_symbol(signal_status)
    fields = _risk_fields(runtime_payload)
    max_leverage = _float(fields.get("max_leverage")) or 1.0
    available_margin = _float(account_margin.get("available_margin"))
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        signal = signal_by_symbol.get(symbol, {"symbol": symbol})
        mark_price, price_source, _price_payload = _current_price(redis_client, signal)
        filters = transport.fetch_symbol_filters(symbol)
        sizing = min_executable_order(
            mark_price=mark_price,
            min_notional=filters.get("min_notional"),
            min_qty=filters.get("min_qty"),
            step_size=filters.get("step_size"),
        )
        min_executable_notional = _float(sizing.get("min_executable_notional"))
        balance_required = (
            round(min_executable_notional / max(max_leverage, 1.0), 8)
            if min_executable_notional is not None
            else None
        )
        adaptive_budget_can_reach_minimum = min_executable_notional is not None
        executable_with_balance = (
            account_margin.get("ok") is True
            and available_margin is not None
            and balance_required is not None
            and available_margin >= balance_required
        )
        blockers: list[str] = []
        if filters.get("ok") is not True:
            blockers.append("SYMBOL_FILTERS_NOT_VERIFIED")
        if sizing.get("ok") is not True:
            blockers.extend(str(item) for item in sizing.get("blockers") or [])
        if not adaptive_budget_can_reach_minimum:
            blockers.append("ADAPTIVE_BUDGET_MIN_EXECUTABLE_NOT_COMPUTED")
        if not executable_with_balance:
            blockers.append(INSUFFICIENT_BALANCE)
        rows.append(
            {
                "symbol": symbol,
                "mark_price": mark_price,
                "mark_price_source": price_source,
                "min_qty": _float(filters.get("min_qty")),
                "min_notional": _float(filters.get("min_notional")),
                "step_size": filters.get("step_size"),
                "tick_size": filters.get("tick_size"),
                "min_executable_qty": _float(sizing.get("min_executable_quantity")),
                "min_executable_notional": min_executable_notional,
                "balance_required": balance_required,
                "adaptive_runtime_budget_source": "V2_ADAPTIVE_AI_CAPITAL_ALLOCATOR_PRE_SUBMIT",
                "static_risk_profile_max_notional_used": False,
                "risk_profile_max_leverage": max_leverage,
                "executable_with_current_balance": executable_with_balance,
                "adaptive_budget_can_reach_minimum": adaptive_budget_can_reach_minimum,
                "filter_status": filters,
                "sizing_status": sizing,
                "blockers": sorted(set(blockers)),
            }
        )
    executable = [row["symbol"] for row in rows if row.get("executable_with_current_balance") is True]
    return {
        "schema_version": "live_symbol_min_executable_map_v1",
        "generated_est": generated_est,
        "accepted_symbols": symbols,
        "account_margin_source": account_margin.get("endpoint"),
        "available_margin": account_margin.get("available_margin"),
        "wallet_balance": account_margin.get("wallet_balance"),
        "unrealized_pnl": account_margin.get("unrealized_pnl"),
        "rows": rows,
        "executable_symbols_with_current_balance": executable,
        "blocked_symbols_with_current_balance": [row["symbol"] for row in rows if row["symbol"] not in executable],
        "status": "LIVE_SYMBOL_MIN_EXECUTABLE_BALANCE_READY" if executable else "LIVE_SYMBOL_MIN_EXECUTABLE_BALANCE_HOLD",
    }


def _candidate_signature(candidate: Mapping[str, Any]) -> str | None:
    if not candidate:
        return None
    payload = {
        "symbol": candidate.get("symbol"),
        "side": candidate.get("side"),
        "position_side": candidate.get("position_side"),
        "quantity": candidate.get("quantity"),
        "requested_notional_usdt": candidate.get("requested_notional_usdt"),
        "lineage": candidate.get("lineage"),
    }
    return _hash_payload(payload)


def _row_for_symbol(symbol_map: Mapping[str, Any], symbol: str | None) -> dict[str, Any]:
    if not symbol:
        return {}
    for row in symbol_map.get("rows") or []:
        if isinstance(row, dict) and str(row.get("symbol") or "").upper() == symbol.upper():
            return row
    return {}


def _restricted_location_read_blockers(account_margin: Mapping[str, Any]) -> list[str]:
    status = account_margin.get("transport_public_account_status")
    status = status if isinstance(status, Mapping) else {}
    response = str(status.get("response_redacted") or "")
    blockers: list[str] = []
    if status.get("status_code") == 451:
        blockers.append(RESTRICTED_451_HTTP)
    if "restricted location" in response.lower():
        blockers.append("BINANCE_SIGNED_READ_RESTRICTED_LOCATION")
    return sorted(set(blockers))


def _classify_api_read(*, ok: Any, status_code: Any, error_type: Any = None, response: Any = "") -> str:
    response_text = str(response or "").lower()
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        code = None
    if ok is True or code == 200:
        return "API_OK"
    if code == 451 or "restricted location" in response_text:
        return "API_RESTRICTED_LOCATION_451"
    if code in {401, 407} or "-2015" in response_text or "invalid api-key" in response_text:
        return "API_AUTH_FAILED"
    if code == 403 or "permission" in response_text:
        return "API_PERMISSION_DENIED"
    if code in {418, 429}:
        return "API_RATE_LIMITED"
    if code is None and error_type:
        return "API_NETWORK_ERROR"
    return "API_UNKNOWN_ERROR"


def _connectivity_classification(status_text: Any) -> str:
    text = str(status_text or "")
    if text in {"OK", "HTTP_200", "READY"}:
        return "API_OK"
    if text == "HTTP_451" or "451" in text:
        return "API_RESTRICTED_LOCATION_451"
    if text.startswith("HTTP_401"):
        return "API_AUTH_FAILED"
    if text.startswith("HTTP_403"):
        return "API_PERMISSION_DENIED"
    if text.startswith("HTTP_429") or text.startswith("HTTP_418"):
        return "API_RATE_LIMITED"
    if text.startswith("NOT_CHECKED"):
        return "API_UNKNOWN_ERROR"
    return "API_NETWORK_ERROR" if text.startswith("ERROR") else "API_UNKNOWN_ERROR"


def _classification_row(
    *,
    endpoint: str,
    request_type: str,
    classification: str,
    ok: bool | None,
    http_status: Any = None,
    error_code: Any = None,
    error_message: Any = "",
    signed: bool = True,
    critical: bool = True,
    detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "endpoint": endpoint,
        "http_status": http_status,
        "error_code": error_code,
        "error_message_redacted": str(error_message or "")[:500],
        "request_type": request_type,
        "signed": signed,
        "account_critical": critical,
        "ok": ok,
        "classification": classification,
        "raw_credentials_exposed": False,
        "detail": dict(detail or {}),
    }


def build_signed_read_classification_status(
    *,
    account_margin: Mapping[str, Any],
    open_orders: Mapping[str, Any] | None = None,
    pre_submit: Mapping[str, Any],
    connectivity: Mapping[str, Any],
) -> dict[str, Any]:
    open_orders = open_orders if isinstance(open_orders, Mapping) else {}
    account_public = account_margin.get("transport_public_account_status")
    account_public = account_public if isinstance(account_public, Mapping) else {}
    position_mode = pre_submit.get("position_mode_status")
    position_mode = position_mode if isinstance(position_mode, Mapping) else {}

    account_classification = _classify_api_read(
        ok=account_margin.get("ok"),
        status_code=account_public.get("status_code"),
        error_type=account_public.get("error_type"),
        response=account_public.get("response_redacted"),
    )
    position_mode_classification = _classify_api_read(
        ok=position_mode.get("ok"),
        status_code=position_mode.get("status_code"),
        error_type=position_mode.get("error_type"),
        response=position_mode.get("response_redacted"),
    )
    position_risk_classification = _connectivity_classification(connectivity.get("position_read_status"))
    account_probe_classification = _connectivity_classification(connectivity.get("account_read_status"))
    restricted_present = "API_RESTRICTED_LOCATION_451" in {
        account_classification,
        position_mode_classification,
        position_risk_classification,
        account_probe_classification,
    }
    open_orders_classification = _classify_api_read(
        ok=open_orders.get("ok"),
        status_code=open_orders.get("status_code"),
        error_type=open_orders.get("error_type"),
        response=open_orders.get("response_redacted"),
    )

    rows = [
        _classification_row(
            endpoint="GET /fapi/v3/account",
            request_type="account info / balance",
            classification=account_classification,
            ok=account_margin.get("ok") is True,
            http_status=account_public.get("status_code"),
            error_code=account_public.get("error_type"),
            error_message=account_public.get("response_redacted"),
            detail={
                "available_margin_known": account_margin.get("available_margin") is not None,
                "wallet_balance_known": account_margin.get("wallet_balance") is not None,
                "balances_redacted": True,
            },
        ),
        _classification_row(
            endpoint="GET /fapi/v1/positionSide/dual",
            request_type="position mode",
            classification=position_mode_classification,
            ok=position_mode.get("ok") is True,
            http_status=position_mode.get("status_code"),
            error_code=position_mode.get("error_type"),
            error_message=position_mode.get("response_redacted"),
            detail={"dual_side_position": position_mode.get("dual_side_position")},
        ),
        _classification_row(
            endpoint="GET /fapi/v2/positionRisk",
            request_type="positions / margin mode read-only / leverage read-only",
            classification=position_risk_classification,
            ok=position_risk_classification == "API_OK",
            http_status=connectivity.get("position_read_status"),
            error_code=None,
            error_message="redacted",
            detail={
                "margin_mode_read_only_source": "positionRisk",
                "leverage_read_only_source": "positionRisk",
                "position_summary": connectivity.get("position_summary") or {},
            },
        ),
        _classification_row(
            endpoint="GET /fapi/v3/account",
            request_type="account probe cross-check",
            classification=account_probe_classification,
            ok=account_probe_classification == "API_OK",
            http_status=connectivity.get("account_read_status"),
            error_code=None,
            error_message="redacted",
            detail={"account_summary_redacted": connectivity.get("account_summary_redacted") or {}},
        ),
        _classification_row(
            endpoint="GET /fapi/v1/openOrders",
            request_type="open orders read-only",
            classification=open_orders_classification,
            ok=open_orders.get("ok") is True,
            http_status=open_orders.get("status_code"),
            error_code=open_orders.get("error_type"),
            error_message=open_orders.get("response_redacted"),
            detail={
                "open_orders_count": open_orders.get("open_orders_count"),
                "probe_status": open_orders.get("status"),
                "restricted_location_present_elsewhere": restricted_present,
            },
        ),
    ]
    restricted_rows = [row for row in rows if row["classification"] == "API_RESTRICTED_LOCATION_451"]
    return {
        "schema_version": "binance_signed_read_451_classification_status_v1",
        "generated_est": est_now(),
        "status": "BINANCE_SIGNED_READ_RESTRICTED_LOCATION_451"
        if restricted_rows
        else "BINANCE_SIGNED_READ_CLASSIFIED_NO_451",
        "classification": "API_RESTRICTED_LOCATION_451" if restricted_rows else "NO_451_DETECTED",
        "restricted_location_detected": bool(restricted_rows),
        "restricted_location_endpoint_count": len(restricted_rows),
        "signed_endpoint_rows": rows,
        "raw_credentials_exposed": False,
        "raw_account_payload_exposed": False,
        "order_submit_disabled": bool(restricted_rows),
    }


def build_critical_account_read_gate_status(
    *,
    signed_classification: Mapping[str, Any],
    symbol_map: Mapping[str, Any],
) -> dict[str, Any]:
    rows = [row for row in signed_classification.get("signed_endpoint_rows") or [] if isinstance(row, Mapping)]
    restricted = any(row.get("classification") == "API_RESTRICTED_LOCATION_451" for row in rows)
    failed_signed = [
        str(row.get("endpoint"))
        for row in rows
        if row.get("account_critical") is True and row.get("classification") != "API_OK"
    ]
    filter_rows = [row for row in symbol_map.get("rows") or [] if isinstance(row, Mapping)]
    filter_failures = [
        str(row.get("symbol"))
        for row in filter_rows
        if not isinstance(row.get("filter_status"), Mapping) or row.get("filter_status", {}).get("ok") is not True
    ]
    blockers: list[str] = []
    if restricted:
        blockers.append("BLOCKED_BINANCE_SIGNED_READ_RESTRICTED")
        blockers.append(RESTRICTED_451)
    if failed_signed:
        blockers.append("ACCOUNT_CRITICAL_SIGNED_READS_NOT_PROVEN")
    if filter_failures:
        blockers.append("SYMBOL_FILTERS_UNVERIFIED")
    ok = not blockers
    return {
        "schema_version": "live_critical_account_read_gate_status_v1",
        "generated_est": est_now(),
        "status": "CRITICAL_ACCOUNT_READ_GATE_READY" if ok else "BLOCKED_BINANCE_SIGNED_READ_RESTRICTED"
        if restricted
        else "CRITICAL_ACCOUNT_READ_GATE_BLOCKED",
        "ok": ok,
        "order_submitted": False,
        "retry_allowed": False if blockers else True,
        "restricted_location_detected": restricted,
        "account_critical_reads": {
            "account_info": "API_OK"
            if not any(row.get("request_type") == "account info / balance" and row.get("classification") != "API_OK" for row in rows)
            else "BLOCKED",
            "balance": "API_OK"
            if not any(row.get("request_type") == "account info / balance" and row.get("classification") != "API_OK" for row in rows)
            else "BLOCKED",
            "positions": "API_OK"
            if not any(str(row.get("request_type")).startswith("positions") and row.get("classification") != "API_OK" for row in rows)
            else "BLOCKED",
            "open_orders": "API_OK"
            if not any(row.get("request_type") == "open orders read-only" and row.get("classification") != "API_OK" for row in rows)
            else "BLOCKED",
            "exchange_filters": "API_OK" if not filter_failures else "BLOCKED",
            "position_mode": "API_OK"
            if not any(row.get("request_type") == "position mode" and row.get("classification") != "API_OK" for row in rows)
            else "BLOCKED",
            "margin_mode_read_only": "API_OK"
            if not any(str(row.get("request_type")).startswith("positions") and row.get("classification") != "API_OK" for row in rows)
            else "BLOCKED",
            "leverage_read_only": "API_OK"
            if not any(str(row.get("request_type")).startswith("positions") and row.get("classification") != "API_OK" for row in rows)
            else "BLOCKED",
        },
        "failed_signed_endpoints": sorted(set(failed_signed)),
        "filter_failures": sorted(set(filter_failures)),
        "blockers": sorted(set(blockers)),
        "raw_credentials_exposed": False,
    }


def build_trader_compliance_hold_state_status(
    *,
    runtime_payload: Mapping[str, Any],
    critical_account_gate: Mapping[str, Any],
    signed_classification: Mapping[str, Any],
) -> dict[str, Any]:
    restricted = critical_account_gate.get("restricted_location_detected") is True
    trader_state = COMPLIANCE_HOLD if restricted else "LIVE_ARMED_BALANCE_HOLD"
    return {
        "schema_version": "trader_compliance_hold_state_status_v1",
        "generated_est": est_now(),
        "status": "TRADER_LIVE_ARMED_COMPLIANCE_HOLD"
        if restricted
        else "TRADER_COMPLIANCE_HOLD_NOT_REQUIRED",
        "trader_state": trader_state,
        "live_gate": runtime_payload.get("live_gate"),
        "trader_execution_enabled": runtime_payload.get("trader_execution_enabled") is True,
        "accepted_symbols": _accepted_symbols(runtime_payload),
        "accepted_risk_profile": (runtime_payload.get("risk_profile") or {}).get("profile_name")
        if isinstance(runtime_payload.get("risk_profile"), Mapping)
        else None,
        "order_submitted": False,
        "retry_allowed": False if restricted else None,
        "public_market_trainer_risk_orchestrator_keep_running": True,
        "paper_shadow_keep_running": True,
        "website_keep_updated": True,
        "hold_release_requires": [
            "account-critical signed reads classify API_OK",
            "available margin is freshly proven",
            "position mode is freshly proven",
            "positions and open orders are known",
            "symbol filters are current",
            "lineage and risk pre-submit checks pass",
            "kill switch is inactive",
        ],
        "signed_read_classification": signed_classification.get("classification"),
        "critical_account_read_gate_status": critical_account_gate.get("status"),
        "blockers": critical_account_gate.get("blockers") or [],
        "raw_credentials_exposed": False,
    }


def build_compliant_exchange_connectivity_options() -> dict[str, Any]:
    return {
        "schema_version": "compliant_exchange_connectivity_options_v1",
        "generated_est": est_now(),
        "status": "COMPLIANT_CONNECTIVITY_OPTIONS_PUBLISHED",
        "allowed_options": [
            {
                "id": "restore_binance_legal_access",
                "label": "Restore Binance access through a legally permitted account/location/network",
                "operator_action_required": True,
            },
            {
                "id": "use_permitted_binance_entity",
                "label": "Use a Binance entity/API endpoint legally permitted for the operator account",
                "operator_action_required": True,
            },
            {
                "id": "audited_exchange_failover",
                "label": "Switch live execution to a supported exchange after audited operator acceptance",
                "operator_action_required": True,
            },
            {
                "id": "paper_shadow_only_until_recovery",
                "label": "Keep Binance public data plus paper/shadow trading until signed reads recover",
                "operator_action_required": False,
            },
        ],
        "disallowed_options": [
            "evading geo/legal restrictions",
            "hiding HTTP 451 from the website/operator",
            "submitting orders without signed account-read proof",
            "using VPN/proxy to evade Binance restrictions",
        ],
        "raw_credentials_exposed": False,
    }


def build_exchange_failover_readiness_status(repo_root: Path, critical_account_gate: Mapping[str, Any]) -> dict[str, Any]:
    adapters_root = repo_root / "v2/backend/app/adapters/exchanges"
    supported_names = sorted(
        path.name
        for path in adapters_root.iterdir()
        if path.is_dir() and not path.name.startswith("__") and (path / "__init__.py").exists()
    ) if adapters_root.exists() else []
    rows = []
    for name in supported_names:
        is_binance = name == "binance"
        rows.append(
            {
                "exchange": name,
                "current_support_status": "CURRENT_LIVE_TRANSPORT_HELD_BY_451"
                if is_binance
                else "ADAPTER_NAMESPACE_ONLY_NO_AUDITED_LIVE_TRANSPORT",
                "credentials_present_by_name": "not_reported",
                "read_only_account_probe_support": is_binance,
                "order_transport_support": is_binance,
                "symbol_overlap": "accepted_symbols_known_for_binance_only" if is_binance else "not_evaluated",
                "risk_profile_compatibility": "conservative_min_executable_binance_filters"
                if is_binance
                else "requires_exchange_filter_mapping",
                "live_gate_required": True,
                "operator_approval_required": True,
                "automatic_failover_allowed": False,
            }
        )
    return {
        "schema_version": "exchange_failover_readiness_status_v1",
        "generated_est": est_now(),
        "status": "EXCHANGE_FAILOVER_REQUIRES_AUDITED_OPERATOR_ACCEPTANCE",
        "binance_current_blocker": critical_account_gate.get("status"),
        "evaluated_adapters": rows,
        "automatic_failover_to_live_trading": False,
        "no_order_transport_failover_performed": True,
        "raw_credentials_exposed": False,
    }


def build_signed_read_recovery_monitor_status(
    *,
    signed_classification: Mapping[str, Any],
    critical_account_gate: Mapping[str, Any],
) -> dict[str, Any]:
    restricted = critical_account_gate.get("restricted_location_detected") is True
    return {
        "schema_version": "binance_signed_read_recovery_monitor_status_v1",
        "generated_est": est_now(),
        "status": "SIGNED_READ_RECOVERY_MONITOR_HOLDING_451"
        if restricted
        else "SIGNED_READ_RECOVERY_MONITOR_READY_FOR_PRE_SUBMIT_REVALIDATION",
        "safe_cadence_seconds": 60,
        "retry_signed_reads_without_spam": True,
        "order_submit_allowed": False if restricted else "requires_pre_submit_revalidation",
        "if_reads_recover": [
            "recompute available margin",
            "recompute symbol filters",
            "recompute position mode",
            "read positions and open orders",
            "rerun pre-submit validation",
            "release retry only if every guard passes",
        ],
        "if_451_persists": "remain in LIVE_ARMED_COMPLIANCE_HOLD",
        "latest_classification": signed_classification.get("classification"),
        "critical_account_read_gate_status": critical_account_gate.get("status"),
        "raw_credentials_exposed": False,
    }


def render_compliance_report(dashboard: Mapping[str, Any]) -> str:
    blockers = dashboard.get("blockers") or []
    blocker_lines = [f"- `{blocker}`" for blocker in blockers] if blockers else ["- None"]
    return "\n".join(
        [
            "# V2 Binance Signed Read 451 Hold And Compliant Connectivity Recovery Report",
            "",
            f"Gate: `{dashboard.get('go_no_go')}`",
            f"Generated EST: `{dashboard.get('generated_est')}`",
            f"Live gate: `{dashboard.get('live_gate')}`",
            f"Trader execution enabled: `{dashboard.get('trader_execution_enabled')}`",
            f"Transport bound: `{dashboard.get('live_order_transport_bound')}`",
            f"Trader state: `{dashboard.get('trader_state')}`",
            f"Signed-read classification: `{dashboard.get('signed_read_classification')}`",
            f"Critical account-read gate: `{dashboard.get('critical_account_read_gate_status')}`",
            f"Available margin: `{dashboard.get('available_margin')}`",
            f"Position mode verified: `{dashboard.get('position_mode_verified')}`",
            f"Open orders verified: `{dashboard.get('open_orders_verified')}`",
            f"Order submitted: `{dashboard.get('order_submitted')}`",
            f"Retry allowed: `{dashboard.get('retry_allowed')}`",
            "",
            "Blockers:",
            *blocker_lines,
            "",
            "Safety: no order/test-order/cancel/modify, no leverage or margin mutation, no transfer/withdrawal, no old Redis write, no legacy restart, no Redis trim, no raw credential output, and no VPN/proxy evasion path. Public market, trainer, risk, orchestrator, paper/shadow, and website updates remain active.",
            "",
        ]
    )


def mirror_compliance_outputs(repo_root: Path, payloads: Mapping[str, Mapping[str, Any]], report: str) -> list[str]:
    written: list[str] = []
    go_no_go = str(payloads["operator_dashboard_payload.json"]["go_no_go"])
    for base in (repo_root / COMPLIANCE_PUBLIC_DIR_REL, repo_root / COMPLIANCE_WORKLOG_DIR_REL):
        base.mkdir(parents=True, exist_ok=True)
        for name, payload in payloads.items():
            path = base / name
            write_json(path, payload)
            written.append(str(path))
        report_path = base / "V2_BINANCE_SIGNED_READ_451_HOLD_AND_COMPLIANT_CONNECTIVITY_RECOVERY_REPORT.md"
        write_text(report_path, report)
        written.append(str(report_path))
        go_path = base / "GO_NO_GO.md"
        write_text(go_path, go_no_go + "\n")
        written.append(str(go_path))
    return written


def _systemd_user_unit_status(unit: str) -> str:
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return "unknown"
    text = (proc.stdout or proc.stderr or "").strip()
    return text or ("active" if proc.returncode == 0 else "unknown")


def _payload_status(repo_root: Path, rel_path: str, *keys: str) -> dict[str, Any]:
    payload = read_json(repo_root / rel_path)
    status = None
    for key in keys:
        if isinstance(payload, Mapping) and payload.get(key) is not None:
            status = payload.get(key)
            break
    return {
        "path": rel_path,
        "exists": bool(payload),
        "status": status or payload.get("go_no_go") if isinstance(payload, Mapping) else None,
        "generated_est": payload.get("generated_est") if isinstance(payload, Mapping) else None,
        "generated_utc": payload.get("generated_utc") if isinstance(payload, Mapping) else None,
    }


def _env_key_presence(repo_root: Path, candidates: Mapping[str, list[str]]) -> dict[str, Any]:
    env_path = repo_root / "v2/.env.local"
    keys: set[str] = set()
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            if value:
                keys.add(key.strip())
    return {
        exchange: {
            "credential_key_names_checked": names,
            "credential_keys_present_by_name": [name for name in names if name in keys],
            "credential_values_exposed": False,
        }
        for exchange, names in candidates.items()
    }


def build_binance_451_compliance_hold_monitor_status(
    *,
    repo_root: Path,
    signed_classification: Mapping[str, Any],
    critical_account_gate: Mapping[str, Any],
    symbol_map: Mapping[str, Any],
    balance_hold: Mapping[str, Any],
) -> dict[str, Any]:
    previous = read_json(
        repo_root
        / RECOVERY_FAILOVER_PUBLIC_DIR_REL
        / "binance_451_compliance_hold_monitor_status.json"
    )
    rows = [row for row in signed_classification.get("signed_endpoint_rows") or [] if isinstance(row, Mapping)]
    endpoint_statuses = {
        str(row.get("endpoint")): {
            "classification": row.get("classification"),
            "http_status": row.get("http_status"),
            "request_type": row.get("request_type"),
            "signed": row.get("signed") is True,
            "account_critical": row.get("account_critical") is True,
        }
        for row in rows
    }
    critical_reads = critical_account_gate.get("account_critical_reads")
    critical_reads = critical_reads if isinstance(critical_reads, Mapping) else {}
    latest_http_status = next(
        (
            row.get("http_status")
            for row in rows
            if row.get("classification") == "API_RESTRICTED_LOCATION_451"
        ),
        None,
    )
    all_signed_ok = bool(rows) and all(row.get("classification") == "API_OK" for row in rows if row.get("account_critical") is True)
    previous_success = previous.get("last_successful_signed_read_est") if isinstance(previous, Mapping) else None
    return {
        "schema_version": "binance_451_compliance_hold_monitor_status_v1",
        "generated_est": est_now(),
        "status": "BINANCE_451_COMPLIANCE_HOLD_ACTIVE"
        if signed_classification.get("restricted_location_detected") is True
        else "BINANCE_SIGNED_READS_RECOVERED_REQUIRES_PRE_SUBMIT_REVALIDATION",
        "last_signed_read_status": signed_classification.get("classification"),
        "endpoint_statuses": endpoint_statuses,
        "account_read": critical_reads.get("account_info"),
        "balance_read": critical_reads.get("balance"),
        "position_read": critical_reads.get("positions"),
        "open_orders_read": critical_reads.get("open_orders"),
        "position_mode_read": critical_reads.get("position_mode"),
        "symbol_filters_read": critical_reads.get("exchange_filters"),
        "symbol_filter_rows": [
            {
                "symbol": row.get("symbol"),
                "filter_ok": row.get("filter_status", {}).get("ok") if isinstance(row.get("filter_status"), Mapping) else False,
                "blockers": row.get("blockers") or [],
            }
            for row in symbol_map.get("rows") or []
            if isinstance(row, Mapping)
        ],
        "latest_http_status": latest_http_status,
        "last_successful_signed_read_est": est_now() if all_signed_ok else previous_success,
        "retry_cadence_seconds": 60,
        "signed_read_retry_allowed": True,
        "order_retry_allowed": False,
        "order_submission_allowed": False
        if signed_classification.get("restricted_location_detected") is True
        else "requires_pre_submit_revalidation",
        "trader_state": balance_hold.get("trader_state"),
        "available_margin": balance_hold.get("available_margin"),
        "blockers": critical_account_gate.get("blockers") or [],
        "raw_credentials_exposed": False,
    }


def build_binance_public_vs_private_runtime_split_status(
    *,
    repo_root: Path,
    signal_publish_initial: Mapping[str, Any],
    signal_publish: Mapping[str, Any],
    orchestration: Mapping[str, Any],
    risk_gateway: Mapping[str, Any],
    paper: Mapping[str, Any],
    signed_classification: Mapping[str, Any],
    critical_account_gate: Mapping[str, Any],
) -> dict[str, Any]:
    public_services = {
        "binance_kline_wss": _systemd_user_unit_status("ai-bot-v2-binance-kline-wss-loop.service"),
        "native_ingestors": _systemd_user_unit_status("ai-bot-v2-native-ingestors-live-loop.service"),
        "liquidation_wss": _systemd_user_unit_status("ai-bot-v2-liquidation-wss-paper-shadow.service"),
        "liquidation_levels": _systemd_user_unit_status("ai-bot-v2-liquidation-levels-engine.service"),
        "coinapi_wsds": _systemd_user_unit_status("ai-bot-v2-coinapi-wsds-loop.service"),
        "kucoin_public": _systemd_user_unit_status("ai-bot-v2-kucoin-public-rest-loop.service"),
        "signal_publisher": _systemd_user_unit_status("ai-bot-v2-all-timeframe-prediction-signal-price-target-publisher.service"),
        "cuda_trainer_timer": _systemd_user_unit_status("ai-bot-v2-native-rl-masa-ppo-cuda-trainer-loop.timer"),
        "risk_gateway": _systemd_user_unit_status("ai-bot-v2-risk-gateway-live-loop.service"),
        "orchestrator": _systemd_user_unit_status("ai-bot-v2-orchestrator-arbitration-loop.service"),
        "paper_shadow": _systemd_user_unit_status("ai-bot-v2-trade-management-paper-loop.service"),
        "website": _systemd_user_unit_status("ai-bot-v2-public-website-backend.service"),
    }
    payload_evidence = {
        "ingestors": _payload_status(
            repo_root,
            "v2/frontend/public/operator_runtime/v2_ingestors_status/latest/v2_ingestors_status.json",
            "status",
            "classification",
        ),
        "binance_kline_wss": _payload_status(
            repo_root,
            "v2/frontend/public/operator_runtime/v2_binance_kline_wss/latest/v2_binance_kline_wss_status.json",
            "status",
            "classification",
        ),
        "coinapi_wsds": _payload_status(
            repo_root,
            "v2/frontend/public/operator_runtime/v2_coinapi_wsds/latest/v2_coinapi_wsds_status.json",
            "status",
            "classification",
        ),
        "liquidation_ingestor": _payload_status(
            repo_root,
            "v2/frontend/public/operator_runtime/v2_liquidation_ingestor/latest/v2_liquidation_ingestor_status.json",
            "status",
            "classification",
        ),
        "signals": _payload_status(
            repo_root,
            "v2/frontend/public/operator_runtime/v2_signals/latest/realtime_signal_publisher_status.json",
            "status",
            "classification",
        ),
        "paper": _payload_status(
            repo_root,
            "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json",
            "status",
            "classification",
        ),
    }
    return {
        "schema_version": "binance_public_vs_private_runtime_split_status_v1",
        "generated_est": est_now(),
        "status": "BINANCE_PUBLIC_RUNTIME_CONTINUES_PRIVATE_EXECUTION_HELD",
        "public_binance_data_keep_running": {
            "prices": True,
            "ohlcv": True,
            "orderbook": True,
            "funding": True,
            "open_interest": True,
            "long_short": True,
            "liquidation_wss": True,
            "note": "Public-data availability is evidenced by current V2 public services/payloads where present; no signed private execution read is required for public data.",
        },
        "public_runtime_services": public_services,
        "public_payload_evidence": payload_evidence,
        "pipeline_runs": {
            "signal_publish_initial": signal_publish_initial,
            "signal_publish_final": signal_publish,
            "orchestrator": orchestration,
            "risk_gateway": risk_gateway,
            "paper_shadow": paper,
        },
        "private_binance_execution_keep_held": {
            "signed_account_reads": True,
            "order_transport": True,
            "order_submit": True,
            "cancel_modify": True,
            "leverage_margin": True,
            "reason": signed_classification.get("classification"),
            "critical_account_read_gate_status": critical_account_gate.get("status"),
        },
        "raw_credentials_exposed": False,
    }


def build_compliant_binance_access_recovery_options() -> dict[str, Any]:
    return {
        "schema_version": "compliant_binance_access_recovery_options_v1",
        "generated_est": est_now(),
        "status": "COMPLIANT_BINANCE_RECOVERY_OPTIONS_READY",
        "allowed_options": [
            "use a legally permitted Binance account/entity/location",
            "correct account/API access with Binance support",
            "continue Binance public data only",
            "switch execution to another legally available exchange through audited failover",
        ],
        "disallowed_options": [
            "VPN/proxy/evasion",
            "hidden routing workaround",
            "ignoring HTTP 451",
            "submitting orders without signed account proof",
        ],
        "order_submission_allowed": False,
        "operator_action_required_for_recovery": True,
        "raw_credentials_exposed": False,
    }


def build_compliant_exchange_failover_candidate_matrix(repo_root: Path) -> dict[str, Any]:
    credentials = _env_key_presence(
        repo_root,
        {
            "kucoin": ["KUCOIN_API_KEY", "KUCOIN_API_SECRET", "KUCOIN_API_PASSPHRASE"],
            "coinbase_advanced": ["COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_API_PASSPHRASE", "COINBASE_CLOUD_API_KEY"],
            "kraken": ["KRAKEN_API_KEY", "KRAKEN_API_SECRET"],
            "bybit": ["BYBIT_API_KEY", "BYBIT_API_SECRET"],
            "okx": ["OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"],
        },
    )
    candidates = [
        {
            "exchange": "KuCoin",
            "credentials": credentials["kucoin"],
            "signed_account_read_available": False,
            "public_data_available": _systemd_user_unit_status("ai-bot-v2-kucoin-public-rest-loop.service") == "active",
            "order_transport_implemented": False,
            "symbol_overlap_with_v2": "partial_public_symbol_mapping_present",
            "risk_profile_compatibility": "requires_futures_filter_and_min_notional_mapping",
            "live_gate_required": True,
            "operator_approval_required": True,
            "implementation_effort": "medium",
            "automatic_failover_allowed": False,
        },
        {
            "exchange": "Coinbase Advanced",
            "credentials": credentials["coinbase_advanced"],
            "signed_account_read_available": False,
            "public_data_available": False,
            "order_transport_implemented": False,
            "symbol_overlap_with_v2": "spot_overlap_requires_strategy_mapping",
            "risk_profile_compatibility": "requires_spot_or_perp_contract_review",
            "live_gate_required": True,
            "operator_approval_required": True,
            "implementation_effort": "high",
            "automatic_failover_allowed": False,
        },
        {
            "exchange": "Kraken",
            "credentials": credentials["kraken"],
            "signed_account_read_available": False,
            "public_data_available": False,
            "order_transport_implemented": False,
            "symbol_overlap_with_v2": "requires_pair_mapping",
            "risk_profile_compatibility": "requires_contract_and_filter mapping",
            "live_gate_required": True,
            "operator_approval_required": True,
            "implementation_effort": "high",
            "automatic_failover_allowed": False,
        },
        {
            "exchange": "Bybit",
            "credentials": credentials["bybit"],
            "signed_account_read_available": False,
            "public_data_available": False,
            "order_transport_implemented": False,
            "symbol_overlap_with_v2": "perp_overlap_likely_but_unverified",
            "risk_profile_compatibility": "operator_legal_approval_required_before_probe",
            "live_gate_required": True,
            "operator_approval_required": True,
            "implementation_effort": "medium",
            "automatic_failover_allowed": False,
        },
        {
            "exchange": "OKX",
            "credentials": credentials["okx"],
            "signed_account_read_available": False,
            "public_data_available": False,
            "order_transport_implemented": False,
            "symbol_overlap_with_v2": "perp_overlap_likely_but_unverified",
            "risk_profile_compatibility": "operator_legal_approval_required_before_probe",
            "live_gate_required": True,
            "operator_approval_required": True,
            "implementation_effort": "medium",
            "automatic_failover_allowed": False,
        },
        {
            "exchange": "paper-only fallback",
            "credentials": {"credential_key_names_checked": [], "credential_keys_present_by_name": [], "credential_values_exposed": False},
            "signed_account_read_available": True,
            "public_data_available": True,
            "order_transport_implemented": True,
            "symbol_overlap_with_v2": "full accepted-symbol simulation only",
            "risk_profile_compatibility": "paper_shadow_only",
            "live_gate_required": False,
            "operator_approval_required": False,
            "implementation_effort": "none",
            "automatic_failover_allowed": True,
        },
    ]
    return {
        "schema_version": "compliant_exchange_failover_candidate_matrix_v1",
        "generated_est": est_now(),
        "status": "FAILOVER_CANDIDATES_EVALUATED_AUDITED_APPROVAL_REQUIRED",
        "candidates": candidates,
        "automatic_live_failover_allowed": False,
        "raw_credentials_exposed": False,
    }


def build_exchange_failover_gate_contract_status() -> dict[str, Any]:
    requirements = [
        "operator accepted exchange",
        "operator accepted symbols",
        "operator accepted risk profile",
        "signed read-only account probe pass",
        "order transport Codex pass",
        "audit records",
        "website enable flow",
        "first-hour monitoring",
    ]
    return {
        "schema_version": "exchange_failover_gate_contract_status_v1",
        "generated_est": est_now(),
        "status": "EXCHANGE_FAILOVER_GATE_CONTRACT_READY_OPERATOR_REQUIRED",
        "requirements": requirements,
        "automatic_failover_allowed": False,
        "current_failover_live_enabled": False,
        "order_submission_allowed_before_contract_pass": False,
        "audited_operator_acceptance_required": True,
        "raw_credentials_exposed": False,
    }


def _read_audited_failover_artifact(repo_root: Path, filename: str) -> dict[str, Any]:
    payload = read_json(repo_root / AUDITED_FAILOVER_PUBLIC_DIR_REL / filename)
    return payload if isinstance(payload, dict) else {}


def _active_risk_profile_name(runtime_payload: Mapping[str, Any]) -> str | None:
    profile = runtime_payload.get("risk_profile") if isinstance(runtime_payload.get("risk_profile"), Mapping) else {}
    name = profile.get("profile_name") or profile.get("profile_id")
    return str(name) if name else None


def build_audited_exchange_failover_candidate_matrix(
    *,
    repo_root: Path,
    runtime_payload: Mapping[str, Any],
    public_private_split: Mapping[str, Any],
) -> dict[str, Any]:
    credentials = _env_key_presence(
        repo_root,
        {
            "KuCoin": ["KUCOIN_API_KEY", "KUCOIN_API_SECRET", "KUCOIN_API_PASSPHRASE"],
            "Coinbase Advanced": [
                "COINBASE_API_KEY",
                "COINBASE_API_SECRET",
                "COINBASE_API_PASSPHRASE",
                "COINBASE_CLOUD_API_KEY",
            ],
            "Kraken": ["KRAKEN_API_KEY", "KRAKEN_API_SECRET"],
            "OKX": ["OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"],
            "Bybit": ["BYBIT_API_KEY", "BYBIT_API_SECRET"],
        },
    )
    accepted_symbols = _accepted_symbols(runtime_payload)
    active_risk_profile = _active_risk_profile_name(runtime_payload)
    kucoin_public_active = _systemd_user_unit_status("ai-bot-v2-kucoin-public-rest-loop.service") == "active"
    rows = [
        {
            "exchange": "KuCoin",
            "public_data_available": kucoin_public_active,
            "private_account_read_available": False,
            "credentials_present_by_name": credentials["KuCoin"].get("credential_keys_present_by_name", []),
            "credentials_checked_by_name": credentials["KuCoin"].get("credential_key_names_checked", []),
            "raw_credentials_exposed": False,
            "supported_symbols_overlap": accepted_symbols,
            "supported_symbols_overlap_status": "CANDIDATE_SYMBOLS_REQUIRE_KUCOIN_INSTRUMENT_PROBE",
            "futures_or_spot": "futures_or_margin_contract_probe_required",
            "order_transport_existing": False,
            "order_transport_needed": True,
            "risk_profile_compatibility": "requires KuCoin filters, fee model, and min notional mapping",
            "active_v2_risk_profile": active_risk_profile,
            "legal_operator_approval_required": True,
            "operator_approval_required": True,
            "implementation_effort": "medium",
            "recommended": True,
            "recommendation_reason": "lowest current V2 integration risk because KuCoin public ingestion already exists",
            "blocker_if_not_recommended": None,
        },
        {
            "exchange": "Coinbase Advanced",
            "public_data_available": False,
            "private_account_read_available": False,
            "credentials_present_by_name": credentials["Coinbase Advanced"].get("credential_keys_present_by_name", []),
            "credentials_checked_by_name": credentials["Coinbase Advanced"].get("credential_key_names_checked", []),
            "raw_credentials_exposed": False,
            "supported_symbols_overlap": accepted_symbols,
            "supported_symbols_overlap_status": "SPOT_OR_PERP_SYMBOL_MAPPING_REQUIRED",
            "futures_or_spot": "spot_or_perp_contract_review_required",
            "order_transport_existing": False,
            "order_transport_needed": True,
            "risk_profile_compatibility": "requires spot/perp risk profile remap and exchange filter mapping",
            "active_v2_risk_profile": active_risk_profile,
            "legal_operator_approval_required": True,
            "operator_approval_required": True,
            "implementation_effort": "high",
            "recommended": False,
            "recommendation_reason": None,
            "blocker_if_not_recommended": "NO_CURRENT_V2_PUBLIC_OR_PRIVATE_RUNTIME_PROOF",
        },
        {
            "exchange": "Kraken",
            "public_data_available": False,
            "private_account_read_available": False,
            "credentials_present_by_name": credentials["Kraken"].get("credential_keys_present_by_name", []),
            "credentials_checked_by_name": credentials["Kraken"].get("credential_key_names_checked", []),
            "raw_credentials_exposed": False,
            "supported_symbols_overlap": accepted_symbols,
            "supported_symbols_overlap_status": "PAIR_AND_CONTRACT_MAPPING_REQUIRED",
            "futures_or_spot": "spot_or_futures_contract_review_required",
            "order_transport_existing": False,
            "order_transport_needed": True,
            "risk_profile_compatibility": "requires contract, fee, and filter remap",
            "active_v2_risk_profile": active_risk_profile,
            "legal_operator_approval_required": True,
            "operator_approval_required": True,
            "implementation_effort": "high",
            "recommended": False,
            "recommendation_reason": None,
            "blocker_if_not_recommended": "NO_CURRENT_V2_PUBLIC_OR_PRIVATE_RUNTIME_PROOF",
        },
        {
            "exchange": "OKX",
            "public_data_available": False,
            "private_account_read_available": False,
            "credentials_present_by_name": credentials["OKX"].get("credential_keys_present_by_name", []),
            "credentials_checked_by_name": credentials["OKX"].get("credential_key_names_checked", []),
            "raw_credentials_exposed": False,
            "supported_symbols_overlap": accepted_symbols,
            "supported_symbols_overlap_status": "PERP_OVERLAP_LIKELY_BUT_UNVERIFIED",
            "futures_or_spot": "perpetual_contract_probe_required",
            "order_transport_existing": False,
            "order_transport_needed": True,
            "risk_profile_compatibility": "operator legal approval and filter remap required",
            "active_v2_risk_profile": active_risk_profile,
            "legal_operator_approval_required": True,
            "operator_approval_required": True,
            "implementation_effort": "medium",
            "recommended": False,
            "recommendation_reason": None,
            "blocker_if_not_recommended": "LEGAL_OPERATOR_APPROVAL_AND_PRIVATE_PROBE_REQUIRED",
        },
        {
            "exchange": "Bybit",
            "public_data_available": False,
            "private_account_read_available": False,
            "credentials_present_by_name": credentials["Bybit"].get("credential_keys_present_by_name", []),
            "credentials_checked_by_name": credentials["Bybit"].get("credential_key_names_checked", []),
            "raw_credentials_exposed": False,
            "supported_symbols_overlap": accepted_symbols,
            "supported_symbols_overlap_status": "PERP_OVERLAP_LIKELY_BUT_UNVERIFIED",
            "futures_or_spot": "perpetual_contract_probe_required",
            "order_transport_existing": False,
            "order_transport_needed": True,
            "risk_profile_compatibility": "operator legal approval and filter remap required",
            "active_v2_risk_profile": active_risk_profile,
            "legal_operator_approval_required": True,
            "operator_approval_required": True,
            "implementation_effort": "medium",
            "recommended": False,
            "recommendation_reason": None,
            "blocker_if_not_recommended": "LEGAL_OPERATOR_APPROVAL_AND_PRIVATE_PROBE_REQUIRED",
        },
        {
            "exchange": "paper-only fallback",
            "public_data_available": True,
            "private_account_read_available": True,
            "credentials_present_by_name": [],
            "credentials_checked_by_name": [],
            "raw_credentials_exposed": False,
            "supported_symbols_overlap": accepted_symbols,
            "supported_symbols_overlap_status": "FULL_SIMULATION_ONLY",
            "futures_or_spot": "paper_shadow_only",
            "order_transport_existing": True,
            "order_transport_needed": False,
            "risk_profile_compatibility": "paper shadow only; not a live execution venue",
            "active_v2_risk_profile": active_risk_profile,
            "legal_operator_approval_required": False,
            "operator_approval_required": False,
            "implementation_effort": "none",
            "recommended": False,
            "recommendation_reason": None,
            "blocker_if_not_recommended": "NOT_LIVE_EXECUTION_FAILOVER",
        },
    ]
    return {
        "schema_version": "audited_exchange_failover_candidate_matrix_v1",
        "generated_est": est_now(),
        "service_id": AUDITED_FAILOVER_SERVICE_ID,
        "status": "FAILOVER_CANDIDATES_EVALUATED_AUDITED_APPROVAL_REQUIRED",
        "binance_private_execution": public_private_split.get("private_execution_status")
        or "COMPLIANCE_HELD_HTTP_451",
        "binance_public_data_continues": public_private_split.get("status")
        == "BINANCE_PUBLIC_RUNTIME_CONTINUES_PRIVATE_EXECUTION_HELD",
        "accepted_v2_symbols": accepted_symbols,
        "candidates": rows,
        "recommended_exchange": "KuCoin",
        "automatic_live_failover_allowed": False,
        "order_submission_allowed": False,
        "raw_credentials_exposed": False,
    }


def build_audited_exchange_failover_selection_proposal(
    *,
    matrix: Mapping[str, Any],
    runtime_payload: Mapping[str, Any],
) -> dict[str, Any]:
    candidates = [row for row in matrix.get("candidates") or [] if isinstance(row, Mapping)]
    recommended = next((row for row in candidates if row.get("recommended") is True), {})
    proposed_exchange = str(recommended.get("exchange") or "KuCoin")
    proposed_symbols = _accepted_symbols(runtime_payload)
    return {
        "schema_version": "audited_exchange_failover_selection_proposal_v1",
        "generated_est": est_now(),
        "service_id": AUDITED_FAILOVER_SERVICE_ID,
        "status": "FAILOVER_SELECTION_PROPOSED_OPERATOR_ACCEPTANCE_REQUIRED",
        "proposed_exchange": proposed_exchange,
        "proposed_symbols": proposed_symbols,
        "symbol_proposal_status": "PROPOSED_FOR_READ_ONLY_PROBE_AND_MAPPING_NOT_EXECUTION",
        "required_credentials_by_name": recommended.get("credentials_checked_by_name", []),
        "credentials_present_by_name": recommended.get("credentials_present_by_name", []),
        "account_probe_required": True,
        "operator_acceptance_required": True,
        "legal_operator_approval_required": bool(recommended.get("legal_operator_approval_required", True)),
        "source_candidate_matrix_id": _hash_payload(matrix),
        "selection_reason": recommended.get("recommendation_reason"),
        "order_submission_allowed": False,
        "automatic_failover_allowed": False,
        "raw_credentials_exposed": False,
    }


def build_failover_exchange_read_only_probe_status(
    *,
    repo_root: Path,
    selection: Mapping[str, Any],
) -> dict[str, Any]:
    exchange_acceptance = _read_audited_failover_artifact(repo_root, "failover_exchange_acceptance_status.json")
    symbols_acceptance = _read_audited_failover_artifact(repo_root, "failover_symbol_acceptance_status.json")
    final_approval = _read_audited_failover_artifact(repo_root, "failover_final_operator_approval_status.json")
    accepted_exchange = exchange_acceptance.get("accepted_exchange")
    acceptance_ready = (
        exchange_acceptance.get("failover_exchange_operator_accepted") is True
        and symbols_acceptance.get("failover_symbol_operator_accepted") is True
        and final_approval.get("failover_final_operator_approval_present") is True
    )
    status = (
        "FAILOVER_READ_ONLY_PROBE_NOT_RUN_SIGNED_PROBE_IMPLEMENTATION_REQUIRED"
        if acceptance_ready
        else "FAILOVER_READ_ONLY_PROBE_NOT_RUN_OPERATOR_ACCEPTANCE_REQUIRED"
    )
    return {
        "schema_version": "failover_exchange_read_only_probe_status_v1",
        "generated_est": est_now(),
        "service_id": AUDITED_FAILOVER_SERVICE_ID,
        "status": status,
        "selected_exchange": accepted_exchange or selection.get("proposed_exchange"),
        "operator_acceptance_ready": acceptance_ready,
        "probe_performed": False,
        "account_read": "NOT_RUN",
        "balance_read": "NOT_RUN",
        "positions_open_orders_read": "NOT_RUN",
        "symbol_filters_read": "NOT_RUN",
        "fee_tick_lot_min_notional_filters": "NOT_RUN",
        "permission_status": "NOT_PROVEN",
        "probe_passed": False,
        "order_submission_allowed": False,
        "blockers": [
            "FAILOVER_OPERATOR_ACCEPTANCE_REQUIRED"
            if not acceptance_ready
            else "FAILOVER_SIGNED_READ_ONLY_PROBE_IMPLEMENTATION_REQUIRED",
            "FAILOVER_SIGNED_READ_ONLY_PROBE_NOT_PASSED",
        ],
        "raw_credentials_exposed": False,
    }


def build_failover_order_transport_status(
    *,
    selection: Mapping[str, Any],
    probe: Mapping[str, Any],
) -> dict[str, Any]:
    probe_passed = probe.get("probe_passed") is True
    status = (
        "FAILOVER_ORDER_TRANSPORT_READY_FOR_CODEX_REVIEW"
        if probe_passed
        else "FAILOVER_ORDER_TRANSPORT_DISABLED_PENDING_AUDIT_AND_PROBE"
    )
    return {
        "schema_version": "failover_order_transport_status_v1",
        "generated_est": est_now(),
        "service_id": AUDITED_FAILOVER_SERVICE_ID,
        "status": status,
        "selected_exchange": probe.get("selected_exchange") or selection.get("proposed_exchange"),
        "order_transport_existing": False,
        "order_transport_needed": True,
        "order_transport_enabled": False,
        "writes_exchange_orders": False,
        "places_real_order": False,
        "order_submission_allowed": False,
        "required_guards": [
            "accepted failover exchange only",
            "accepted failover symbols only",
            "accepted risk profile only",
            "prediction_id required",
            "risk_decision_id required",
            "orchestrator_decision_id required",
            "signal_id required",
            "failover audit IDs required",
            "no leverage or margin mutation",
            "no transfer or withdrawal endpoints",
        ],
        "lineage_required_fields": [
            "prediction_id",
            "risk_decision_id",
            "orchestrator_decision_id",
            "signal_id",
            "failover_exchange_audit_id",
            "failover_symbols_audit_id",
            "failover_final_approval_audit_id",
        ],
        "blockers": [
            "FAILOVER_SIGNED_READ_ONLY_PROBE_NOT_PASSED",
            "FAILOVER_ORDER_TRANSPORT_NOT_ENABLED",
            "FAILOVER_OPERATOR_ACCEPTANCE_REQUIRED",
        ],
        "raw_credentials_exposed": False,
    }


def _kucoin_symbol_candidate(symbol: str) -> str | None:
    if symbol.endswith("USDT") and len(symbol) > 4:
        return f"{symbol[:-4]}-USDT"
    return None


def build_failover_symbol_risk_orchestrator_mapping_status(
    *,
    selection: Mapping[str, Any],
    runtime_payload: Mapping[str, Any],
    signal_status: Mapping[str, Any],
) -> dict[str, Any]:
    signal_by_symbol = signals_by_symbol(signal_status)
    active_risk_profile = _active_risk_profile_name(runtime_payload)
    rows = []
    for symbol in selection.get("proposed_symbols") or _accepted_symbols(runtime_payload):
        symbol_text = str(symbol).upper()
        signal = signal_by_symbol.get(symbol_text, {})
        rows.append(
            {
                "v2_symbol": symbol_text,
                "exchange": selection.get("proposed_exchange"),
                "exchange_symbol": None,
                "exchange_symbol_candidate": _kucoin_symbol_candidate(symbol_text)
                if selection.get("proposed_exchange") == "KuCoin"
                else None,
                "market_type": selection.get("futures_or_spot") or "probe_required",
                "tick_size": None,
                "step_size": None,
                "min_notional": None,
                "adaptive_budget_source": "V2_ADAPTIVE_AI_CAPITAL_ALLOCATOR_PRE_SUBMIT",
                "static_risk_cap_used": False,
                "risk_profile": active_risk_profile,
                "prediction_availability": "PRESENT" if signal.get("prediction_id") else "MISSING_OR_STALE",
                "risk_decision_availability": "PRESENT" if signal.get("risk_decision_id") else "MISSING_OR_STALE",
                "orchestrator_signal_availability": "PRESENT"
                if signal.get("orchestrator_decision_id") or signal.get("signal_id")
                else "MISSING_OR_STALE",
                "mapping_verified": False,
                "order_submission_allowed": False,
                "blockers": [
                    "FAILOVER_EXCHANGE_SYMBOL_MAPPING_UNVERIFIED",
                    "FAILOVER_SIGNED_READ_ONLY_PROBE_NOT_PASSED",
                ],
            }
        )
    return {
        "schema_version": "failover_symbol_risk_orchestrator_mapping_status_v1",
        "generated_est": est_now(),
        "service_id": AUDITED_FAILOVER_SERVICE_ID,
        "status": "FAILOVER_SYMBOL_MAPPING_REQUIRES_READ_ONLY_PROBE",
        "selected_exchange": selection.get("proposed_exchange"),
        "rows": rows,
        "accepted_symbols_only": True,
        "active_risk_profile": active_risk_profile,
        "order_submission_allowed": False,
        "raw_credentials_exposed": False,
    }


def render_audited_failover_report(dashboard: Mapping[str, Any]) -> str:
    blockers = dashboard.get("blockers") or []
    blocker_lines = [f"- `{blocker}`" for blocker in blockers] if blockers else ["- None"]
    return "\n".join(
        [
            "# V2 Audited Exchange Failover Selection And Transport Implementation Report",
            "",
            f"Gate: `{dashboard.get('go_no_go')}`",
            f"Generated EST: `{dashboard.get('generated_est')}`",
            f"Binance private execution: `{dashboard.get('binance_private_execution_status')}`",
            f"Binance public runtime: `{dashboard.get('public_runtime_status')}`",
            f"Trader state: `{dashboard.get('trader_state')}`",
            f"Proposed failover exchange: `{dashboard.get('proposed_exchange')}`",
            f"Proposed symbols: `{dashboard.get('proposed_symbols')}`",
            f"Failover live enabled: `{dashboard.get('failover_live_enabled')}`",
            f"Failover order transport enabled: `{dashboard.get('failover_order_transport_enabled')}`",
            f"Read-only probe passed: `{dashboard.get('failover_read_only_probe_passed')}`",
            f"Order submission allowed: `{dashboard.get('order_submission_allowed')}`",
            "",
            "Blockers:",
            *blocker_lines,
            "",
            "Safety: Binance private execution remains compliance-held while HTTP 451 persists. No failover order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, no raw credential output, and no VPN/proxy/evasion path. Failover cannot become live without audited operator acceptance, read-only account probe pass, transport review, and first-hour monitoring.",
            "",
        ]
    )


def render_recovery_failover_report(dashboard: Mapping[str, Any]) -> str:
    blockers = dashboard.get("blockers") or []
    blocker_lines = [f"- `{blocker}`" for blocker in blockers] if blockers else ["- None"]
    return "\n".join(
        [
            "# V2 Compliant Exchange Connectivity Recovery Or Failover Report",
            "",
            f"Gate: `{dashboard.get('go_no_go')}`",
            f"Generated EST: `{dashboard.get('generated_est')}`",
            f"Live gate: `{dashboard.get('live_gate')}`",
            f"Trader execution enabled: `{dashboard.get('trader_execution_enabled')}`",
            f"Transport bound: `{dashboard.get('live_order_transport_bound')}`",
            f"Trader state: `{dashboard.get('trader_state')}`",
            f"Binance private execution: `{dashboard.get('binance_private_execution_status')}`",
            f"Signed-read classification: `{dashboard.get('signed_read_classification')}`",
            f"Public runtime status: `{dashboard.get('public_runtime_status')}`",
            f"Failover status: `{dashboard.get('failover_status')}`",
            f"Order submitted: `{dashboard.get('order_submitted')}`",
            f"Retry allowed: `{dashboard.get('retry_allowed')}`",
            "",
            "Blockers:",
            *blocker_lines,
            "",
            "Safety: Binance private execution remains compliance-held while HTTP 451 persists. No order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, no raw credential output, and no VPN/proxy/evasion path. Public market, trainer, risk, orchestrator, paper-shadow, website, and monitoring continue.",
            "",
        ]
    )


def mirror_recovery_failover_outputs(repo_root: Path, payloads: Mapping[str, Mapping[str, Any]], report: str) -> list[str]:
    written: list[str] = []
    go_no_go = str(payloads["operator_dashboard_payload.json"]["go_no_go"])
    for base in (repo_root / RECOVERY_FAILOVER_PUBLIC_DIR_REL, repo_root / RECOVERY_FAILOVER_WORKLOG_DIR_REL):
        base.mkdir(parents=True, exist_ok=True)
        for name, payload in payloads.items():
            path = base / name
            write_json(path, payload)
            written.append(str(path))
        report_path = base / "V2_COMPLIANT_EXCHANGE_CONNECTIVITY_RECOVERY_OR_FAILOVER_REPORT.md"
        write_text(report_path, report)
        written.append(str(report_path))
        go_path = base / "GO_NO_GO.md"
        write_text(go_path, go_no_go + "\n")
        written.append(str(go_path))
    return written


def mirror_audited_failover_outputs(repo_root: Path, payloads: Mapping[str, Mapping[str, Any]], report: str) -> list[str]:
    written: list[str] = []
    go_no_go = str(payloads["operator_dashboard_payload.json"]["go_no_go"])
    for base in (repo_root / AUDITED_FAILOVER_PUBLIC_DIR_REL, repo_root / AUDITED_FAILOVER_WORKLOG_DIR_REL):
        base.mkdir(parents=True, exist_ok=True)
        for name, payload in payloads.items():
            path = base / name
            write_json(path, payload)
            written.append(str(path))
        report_path = base / "V2_AUDITED_EXCHANGE_FAILOVER_SELECTION_AND_TRANSPORT_IMPLEMENTATION_REPORT.md"
        write_text(report_path, report)
        written.append(str(report_path))
        go_path = base / "GO_NO_GO.md"
        write_text(go_path, go_no_go + "\n")
        written.append(str(go_path))
    return written


def _candidate_from_previous_artifacts(repo_root: Path) -> dict[str, Any]:
    sources = [
        (
            repo_root / PUBLIC_DIR_REL / "live_transport_balance_hold_status.json",
            "v2_live_transport_balance_aware_hold_and_first_order_monitor/latest/live_transport_balance_hold_status.json",
        ),
        (
            repo_root
            / "v2/frontend/public/v2_exchange_filter_risk_profile_alignment_and_min_order_execution/latest/first_live_order_pre_submit_validation_status.json",
            "v2_exchange_filter_risk_profile_alignment_and_min_order_execution/latest/first_live_order_pre_submit_validation_status.json",
        ),
    ]
    for path, source in sources:
        payload = read_json(path)
        candidate = payload.get("selected_candidate") if isinstance(payload, Mapping) else {}
        if isinstance(candidate, Mapping) and candidate.get("symbol") and candidate.get("quantity"):
            return {
                "selected_candidate": dict(candidate),
                "source": source,
                "available_margin": payload.get("available_margin"),
                "required_initial_margin": payload.get("required_initial_margin"),
                "generated_est": payload.get("generated_est"),
            }
    return {}


def _fallback_symbol_row(candidate: Mapping[str, Any]) -> dict[str, Any]:
    filters = candidate.get("symbol_filter_status") if isinstance(candidate.get("symbol_filter_status"), Mapping) else {}
    min_order = filters.get("min_executable_order") if isinstance(filters.get("min_executable_order"), Mapping) else {}
    account = candidate.get("account_margin_status") if isinstance(candidate.get("account_margin_status"), Mapping) else {}
    return {
        "symbol": candidate.get("symbol"),
        "mark_price": _float(candidate.get("price_reference")),
        "mark_price_source": "last_known_pre_submit_candidate",
        "min_qty": _float(filters.get("min_qty")),
        "min_notional": _float(filters.get("min_notional")),
        "step_size": filters.get("step_size"),
        "tick_size": filters.get("tick_size"),
        "min_executable_qty": _float(min_order.get("min_executable_quantity")),
        "min_executable_notional": _float(min_order.get("min_executable_notional")),
        "balance_required": _float(account.get("required_initial_margin_usdt")),
        "filter_status": filters,
        "sizing_status": min_order,
        "fallback_source": "last_known_pre_submit_candidate",
    }


def build_balance_hold_status(
    *,
    runtime_payload: Mapping[str, Any],
    pre_submit: Mapping[str, Any],
    symbol_map: Mapping[str, Any],
    account_margin: Mapping[str, Any],
    critical_account_gate: Mapping[str, Any] | None = None,
    fallback_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    candidate = pre_submit.get("selected_candidate") if isinstance(pre_submit.get("selected_candidate"), Mapping) else {}
    current_candidate_available = bool(candidate.get("symbol") and candidate.get("quantity"))
    fallback_context = fallback_context if isinstance(fallback_context, Mapping) else {}
    if not current_candidate_available:
        fallback_candidate = fallback_context.get("selected_candidate")
        if isinstance(fallback_candidate, Mapping) and fallback_candidate.get("symbol") and fallback_candidate.get("quantity"):
            candidate = dict(fallback_candidate)
    fields = _risk_fields(runtime_payload)
    symbol = str(candidate.get("symbol") or "")
    symbol_row = _row_for_symbol(symbol_map, symbol)
    if not symbol_row or symbol_row.get("min_executable_notional") is None:
        fallback_row = _fallback_symbol_row(candidate)
        if fallback_row.get("min_executable_notional") is not None:
            symbol_row = {**fallback_row, **{k: v for k, v in symbol_row.items() if v is not None}}
    selected_notional = _float(candidate.get("requested_notional_usdt")) or _float(symbol_row.get("min_executable_notional"))
    max_leverage = _float(fields.get("max_leverage")) or 1.0
    required_initial_margin = (
        round(selected_notional / max(max_leverage, 1.0), 8)
        if selected_notional is not None
        else _round_money(symbol_row.get("balance_required"))
    )
    if required_initial_margin is None:
        required_initial_margin = _round_money(fallback_context.get("required_initial_margin"))
    available_margin = _float(account_margin.get("available_margin"))
    last_known_available_margin = _float(fallback_context.get("available_margin"))
    margin_sufficient = (
        account_margin.get("ok") is True
        and available_margin is not None
        and required_initial_margin is not None
        and available_margin >= required_initial_margin
    )
    critical_account_gate = critical_account_gate if isinstance(critical_account_gate, Mapping) else {}
    compliance_restricted = critical_account_gate.get("restricted_location_detected") is True
    blockers = sorted(set(str(item) for item in pre_submit.get("blockers") or [] if str(item)))
    blockers.extend(_restricted_location_read_blockers(account_margin))
    blockers.extend(str(item) for item in critical_account_gate.get("blockers") or [] if str(item))
    if compliance_restricted:
        blockers.append(RESTRICTED_451)
    if not current_candidate_available and candidate:
        blockers.append("BALANCE_HOLD_USING_LAST_KNOWN_CANDIDATE")
    if account_margin.get("ok") is not True:
        blockers.append("BINANCE_ACCOUNT_MARGIN_READ_FAILED")
        blockers.append("BALANCE_HOLD_CURRENT_BALANCE_READ_UNAVAILABLE")
    if not margin_sufficient and INSUFFICIENT_BALANCE not in blockers:
        blockers.append(INSUFFICIENT_BALANCE)
    blockers = sorted(set(blockers))
    if compliance_restricted:
        trader_state = COMPLIANCE_HOLD
        status = "LIVE_TRANSPORT_COMPLIANCE_HOLD_ACTIVE"
        monitor_read_status = "CURRENT_SIGNED_READ_RESTRICTED_COMPLIANCE_HOLD"
        known_blocker = RESTRICTED_451
        retry_allowed = False
    else:
        trader_state = "LIVE_ARMED_BALANCE_READY" if margin_sufficient else "LIVE_ARMED_BALANCE_HOLD"
        status = "LIVE_TRANSPORT_BALANCE_READY" if margin_sufficient else "LIVE_TRANSPORT_BALANCE_HOLD_ACTIVE"
        monitor_read_status = "CURRENT_SIGNED_BALANCE_READ_OK" if account_margin.get("ok") is True else "CURRENT_SIGNED_BALANCE_READ_BLOCKED_HOLD_PRESERVED"
        known_blocker = None if margin_sufficient else INSUFFICIENT_BALANCE
        retry_allowed = margin_sufficient and not blockers
    return {
        "schema_version": "live_transport_balance_hold_status_v1",
        "generated_est": est_now(),
        "status": status,
        "monitor_read_status": monitor_read_status,
        "compliance_hold_active": compliance_restricted,
        "compliance_hold_reason": RESTRICTED_451 if compliance_restricted else None,
        "critical_account_read_gate_status": critical_account_gate.get("status"),
        "live_gate": runtime_payload.get("live_gate"),
        "trader_execution_enabled": runtime_payload.get("trader_execution_enabled") is True,
        "available_margin": account_margin.get("available_margin"),
        "available_margin_current": account_margin.get("available_margin"),
        "available_margin_source": "binance_signed_readonly_current"
        if account_margin.get("ok") is True
        else "CURRENT_BALANCE_READ_UNAVAILABLE",
        "last_known_available_margin": last_known_available_margin,
        "last_known_candidate_source": fallback_context.get("source") if not current_candidate_available else None,
        "current_candidate_available": current_candidate_available,
        "selected_candidate_source": "current_pre_submit" if current_candidate_available else fallback_context.get("source"),
        "wallet_balance": account_margin.get("wallet_balance"),
        "unrealized_pnl": account_margin.get("unrealized_pnl"),
        "required_min_notional": symbol_row.get("min_executable_notional"),
        "required_min_qty": symbol_row.get("min_executable_qty"),
        "required_initial_margin": required_initial_margin,
        "selected_symbol": symbol or None,
        "selected_quantity": candidate.get("quantity"),
        "selected_notional": selected_notional,
        "risk_profile_name": (runtime_payload.get("risk_profile") or {}).get("profile_name")
        if isinstance(runtime_payload.get("risk_profile"), Mapping)
        else None,
        "adaptive_runtime_budget_source": "V2_ADAPTIVE_AI_CAPITAL_ALLOCATOR_PRE_SUBMIT",
        "static_risk_profile_max_notional_used": False,
        "risk_profile_max_leverage": max_leverage,
        "margin_sufficient": margin_sufficient,
        "blocker": known_blocker,
        "blockers": blockers,
        "order_submitted": False,
        "retry_allowed": retry_allowed,
        "trader_state": trader_state,
        "selected_candidate": candidate,
        "account_margin_source": account_margin.get("endpoint"),
        "raw_credentials_exposed": False,
        "raw_account_payload_exposed": False,
    }


def build_retry_guard_status(
    *,
    repo_root: Path,
    balance_hold: Mapping[str, Any],
    pre_submit: Mapping[str, Any],
    account_margin: Mapping[str, Any],
) -> dict[str, Any]:
    current_path = repo_root / PUBLIC_DIR_REL / "live_order_retry_guard_status.json"
    previous = read_json(current_path)
    candidate = balance_hold.get("selected_candidate") if isinstance(balance_hold.get("selected_candidate"), Mapping) else {}
    candidate_signature = _candidate_signature(candidate)
    balance_payload = {
        "available_margin": account_margin.get("available_margin"),
        "wallet_balance": account_margin.get("wallet_balance"),
        "unrealized_pnl": account_margin.get("unrealized_pnl"),
    }
    balance_fingerprint = _hash_payload(balance_payload)
    previous_fingerprint = previous.get("balance_state_fingerprint") if isinstance(previous, Mapping) else None
    balance_changed = bool(previous_fingerprint and previous_fingerprint != balance_fingerprint)
    blockers = sorted(
        set(
            [str(item) for item in pre_submit.get("blockers") or [] if str(item)]
            + [str(item) for item in balance_hold.get("blockers") or [] if str(item)]
        )
    )
    compliance_restricted = RESTRICTED_451 in blockers or balance_hold.get("compliance_hold_active") is True
    insufficient = INSUFFICIENT_BALANCE in blockers or balance_hold.get("margin_sufficient") is not True
    retry_allowed = bool(balance_hold.get("margin_sufficient") is True and not blockers and not compliance_restricted)
    retry_blocked_reason = (
        RESTRICTED_451
        if compliance_restricted
        else None
        if retry_allowed
        else INSUFFICIENT_BALANCE
    )
    return {
        "schema_version": "live_order_retry_guard_status_v1",
        "generated_est": est_now(),
        "status": "RETRY_GUARD_RELEASED_BALANCE_SUFFICIENT"
        if retry_allowed
        else "RETRY_GUARD_HOLDING_FOR_COMPLIANCE_RECOVERY"
        if compliance_restricted
        else "RETRY_GUARD_HOLDING_FOR_BALANCE_CHANGE",
        "retry_allowed": retry_allowed,
        "retry_blocked_reason": retry_blocked_reason,
        "balance_state_fingerprint": balance_fingerprint,
        "previous_balance_state_fingerprint": previous_fingerprint,
        "available_margin_changed_since_last_guard": balance_changed,
        "same_rejected_order_retry_blocked": insufficient,
        "last_order_candidate_signature": candidate_signature,
        "do_not_retry_same_rejected_order": insufficient or compliance_restricted,
        "resume_condition": "signed account reads recover, available_margin >= required_initial_margin, and all transport prechecks pass"
        if compliance_restricted
        else "available_margin >= required_initial_margin and all transport prechecks pass",
        "rules": [
            "do not retry after insufficient margin unless available_margin changes",
            "do not retry same rejected order repeatedly",
            "do not submit if balance_required > available_margin",
            "do not auto-increase leverage",
            "do not auto-change margin mode",
        ],
        "blockers": blockers,
        "raw_credentials_exposed": False,
    }


def build_resume_condition_status(
    *,
    pre_submit: Mapping[str, Any],
    balance_hold: Mapping[str, Any],
    retry_guard: Mapping[str, Any],
    submit_result: Mapping[str, Any] | None,
) -> dict[str, Any]:
    blockers = sorted(set(str(item) for item in pre_submit.get("blockers") or [] if str(item)))
    blockers = sorted(set(blockers + [str(item) for item in balance_hold.get("blockers") or [] if str(item)]))
    margin_sufficient = balance_hold.get("margin_sufficient") is True
    pre_submit_ready = pre_submit.get("status") == "LIVE_ORDER_TRANSPORT_PRE_SUBMIT_READY"
    if submit_result:
        status = "FIRST_ORDER_SUBMIT_ATTEMPTED_AFTER_BALANCE_RELEASE"
    elif balance_hold.get("compliance_hold_active") is True:
        status = "FIRST_ORDER_RESUME_BLOCKED_COMPLIANCE_HOLD"
    elif margin_sufficient and pre_submit_ready and retry_guard.get("retry_allowed") is True:
        status = "FIRST_ORDER_RESUME_READY"
    elif not margin_sufficient:
        status = "FIRST_ORDER_RESUME_BLOCKED_BALANCE_HOLD"
    else:
        status = "FIRST_ORDER_RESUME_BLOCKED_PRECHECK"
    return {
        "schema_version": "first_order_resume_condition_status_v1",
        "generated_est": est_now(),
        "status": status,
        "margin_sufficient": margin_sufficient,
        "pre_submit_ready": pre_submit_ready,
        "retry_allowed": retry_guard.get("retry_allowed") is True,
        "order_submitted": bool(submit_result and submit_result.get("order_submitted")),
        "submit_result": submit_result,
        "required_conditions": {
            "live_gate_enabled": balance_hold.get("live_gate") == LIVE_GATE_ENABLED,
            "trader_execution_enabled": balance_hold.get("trader_execution_enabled") is True,
            "margin_sufficient": margin_sufficient,
            "transport_pre_submit_ready": pre_submit_ready,
            "retry_guard_released": retry_guard.get("retry_allowed") is True,
            "signed_account_reads_recovered": balance_hold.get("compliance_hold_active") is not True,
        },
        "blockers": blockers if blockers else ([] if pre_submit_ready else ["NO_VALID_ORDER_CANDIDATE"]),
    }


def raw_secret_scan(repo_root: Path) -> dict[str, Any]:
    env_path = repo_root / "v2/.env.local"
    secrets: list[str] = []
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" not in raw or raw.strip().startswith("#"):
                continue
            key, value = raw.split("=", 1)
            if not any(token in key.upper() for token in ("KEY", "SECRET", "TOKEN", "PASSWORD")):
                continue
            value = value.strip().strip('"').strip("'")
            if len(value) >= 8:
                secrets.append(value)
    scanned_roots = [
        repo_root / PUBLIC_DIR_REL,
        repo_root / WORKLOG_DIR_REL,
        repo_root / COMPLIANCE_PUBLIC_DIR_REL,
        repo_root / COMPLIANCE_WORKLOG_DIR_REL,
        repo_root / RECOVERY_FAILOVER_PUBLIC_DIR_REL,
        repo_root / RECOVERY_FAILOVER_WORKLOG_DIR_REL,
        repo_root / AUDITED_FAILOVER_PUBLIC_DIR_REL,
        repo_root / AUDITED_FAILOVER_WORKLOG_DIR_REL,
        repo_root / "v2/frontend/public/v2_binance_live_order_transport_binding_and_first_hour_monitoring/latest",
        repo_root / "v2/frontend/public/v2_live_order_transport_state_lineage_and_write_guard_repair/latest",
        repo_root / "v2/frontend/public/v2_exchange_filter_risk_profile_alignment_and_min_order_execution/latest",
    ]
    matches: list[str] = []
    for root in scanned_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.stat().st_size > 20_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(secret and secret in text for secret in secrets):
                matches.append(str(path.relative_to(repo_root)))
    return {
        "status": "PASS" if not matches else "FAIL",
        "secret_value_count_checked": len(secrets),
        "raw_secret_matches_count": len(matches),
        "files_with_raw_secret_matches": matches,
    }


def validation_status(repo_root: Path) -> dict[str, Any]:
    commands = {
        "py_compile": [
            "python3",
            "-m",
            "py_compile",
            "v2/backend/app/services/live_gate/exchange_filter_sizing.py",
            "v2/backend/app/services/live_gate/binance_live_order_transport.py",
            "v2/backend/app/cli/v2_live_transport_balance_aware_hold_and_first_order_monitor.py",
        ],
        "focused_backend_tests": [
            "./.venv/bin/python",
            "-m",
            "pytest",
            "-q",
            "v2/backend/tests/unit/services/live_gate/test_exchange_filter_sizing.py",
            "v2/backend/tests/unit/services/live_gate/test_binance_live_order_transport.py",
            "v2/backend/tests/unit/services/live_gate/test_runtime_execution_state.py",
            "v2/backend/tests/unit/api/test_live_gate.py",
            "v2/backend/tests/unit/cli/test_v2_binance_signed_read_451_compliance_hold.py",
        ],
        "frontend_typecheck": ["npm", "run", "typecheck"],
        "frontend_build": ["npm", "run", "build"],
        "frontend_route_smoke": ["npm", "run", "test:e2e", "--", "nav_smoke.spec.ts"],
    }
    results: dict[str, Any] = {"schema_version": "validation_status_v1", "generated_est": est_now()}
    for label, command in commands.items():
        cwd = repo_root / "v2/frontend" if label.startswith("frontend_") else repo_root
        try:
            proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=360)
            results[label] = {
                "returncode": proc.returncode,
                "status": "PASS" if proc.returncode == 0 else "FAIL",
                "stdout_tail": proc.stdout[-2000:],
                "stderr_tail": proc.stderr[-2000:],
            }
        except Exception as exc:
            results[label] = {"returncode": None, "status": "FAIL", "error": type(exc).__name__}
    forbidden = subprocess.run(
        [
            "rg",
            "-n",
            "fapi/v1/(leverage|marginType|transfer|withdraw|batchOrders)|testOrder|cancelAllOpenOrders|DELETE /fapi|PUT /fapi",
            "v2/backend/app/services/live_gate",
            "v2/backend/app/cli/v2_trader_runtime_loop.py",
            "v2/backend/app/cli/v2_live_transport_balance_aware_hold_and_first_order_monitor.py",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    forbidden_matches = "\n".join(
        line
        for line in forbidden.stdout.splitlines()
        if not (
            "v2_live_transport_balance_aware_hold_and_first_order_monitor.py" in line
            and "fapi/v1/(leverage|marginType|transfer|withdraw|batchOrders)" in line
        )
    )
    results["forbidden_exchange_mutation_scan"] = {
        "returncode": forbidden.returncode,
        "status": "PASS" if forbidden.returncode == 1 or not forbidden_matches else "FAIL",
        "matches": forbidden_matches[-2000:],
    }
    old_redis = subprocess.run(
        [
            "rg",
            "-n",
            "\"(v1:|legacy:|redis:old)",
            "v2/backend/app/services/live_gate",
            "v2/backend/app/cli/v2_live_transport_balance_aware_hold_and_first_order_monitor.py",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    results["old_redis_scan"] = {
        "returncode": old_redis.returncode,
        "status": "PASS" if old_redis.returncode == 1 else "FAIL",
        "matches": old_redis.stdout[-2000:],
    }
    results["raw_secret_scan"] = raw_secret_scan(repo_root)
    return results


def preserved_validation_status(repo_root: Path) -> dict[str, Any]:
    previous = read_json(repo_root / PUBLIC_DIR_REL / "validation_status.json")
    if isinstance(previous, dict) and previous.get("status") != "SKIPPED":
        payload = dict(previous)
        payload["runtime_refresh_validation"] = {
            "status": "SKIPPED_TIMER_REFRESH_PRESERVED_LAST_FULL_VALIDATION",
            "generated_est": est_now(),
        }
        return payload
    return {
        "schema_version": "validation_status_v1",
        "generated_est": est_now(),
        "status": "SKIPPED_TIMER_REFRESH_NO_PRIOR_FULL_VALIDATION",
    }


def render_report(dashboard: Mapping[str, Any]) -> str:
    blockers = dashboard.get("blockers") or []
    blocker_lines = [f"- `{blocker}`" for blocker in blockers] if blockers else ["- None"]
    return "\n".join(
        [
            "# V2 Live Transport Balance Aware Hold And First Order Monitor Report",
            "",
            f"Gate: `{dashboard.get('go_no_go')}`",
            f"Generated EST: `{dashboard.get('generated_est')}`",
            f"Live gate: `{dashboard.get('live_gate')}`",
            f"Trader execution enabled: `{dashboard.get('trader_execution_enabled')}`",
            f"Transport bound: `{dashboard.get('live_order_transport_bound')}`",
            f"Transport state: `{dashboard.get('transport_status')}`",
            f"Trader state: `{dashboard.get('trader_state')}`",
            f"Active risk profile: `{dashboard.get('active_risk_profile')}`",
            f"Accepted symbols: `{dashboard.get('accepted_symbols')}`",
            f"Selected candidate: `{dashboard.get('selected_candidate_summary')}`",
            f"Available margin: `{dashboard.get('available_margin')}`",
            f"Required initial margin: `{dashboard.get('required_initial_margin')}`",
            f"Margin sufficient: `{dashboard.get('margin_sufficient')}`",
            f"Signed-read classification: `{dashboard.get('signed_read_classification')}`",
            f"Critical account-read gate: `{dashboard.get('critical_account_read_gate_status')}`",
            f"Retry allowed: `{dashboard.get('retry_allowed')}`",
            f"Order submitted: `{dashboard.get('order_submitted')}`",
            "",
            "Blockers:",
            *blocker_lines,
            "",
            "Safety: no test-order/cancel/modify, no leverage or margin mutation, no transfer/withdrawal, no legacy restart, no Redis trim, no raw credential output, no VPN/proxy evasion. The monitor holds order submission until signed account reads recover and available margin satisfies the minimum executable order requirement.",
            "",
        ]
    )


def run_once(
    repo_root: Path,
    *,
    submit_if_balance_sufficient: bool = True,
    run_validation_checks: bool = True,
) -> dict[str, Any]:
    os.environ["V2_REPO_ROOT"] = str(repo_root)
    redis_client = connect_redis()
    transport = BinanceUsdMLiveOrderTransport()
    generated_est = est_now()

    runtime_heartbeat = refresh_runtime_execution_state_heartbeat(repo_root=repo_root, redis_client=redis_client)
    signal_publish_initial = safe_run(
        "v2_all_timeframe_prediction_signal_price_target_publisher_initial",
        run_signal_publisher,
        repo_root,
    )
    orchestration = safe_run("v2_orchestrator_arbitration_loop", orchestrator_loop.run_once)
    risk_gateway = safe_run("v2_risk_gateway_live_loop", risk_gateway_loop.run_once, ttl_seconds=300)
    paper = safe_run("v2_trade_management_paper_loop", paper_loop.run_once)
    signal_publish = safe_run("v2_all_timeframe_prediction_signal_price_target_publisher_final", run_signal_publisher, repo_root)

    runtime_read = read_runtime_execution_state(repo_root=repo_root, redis_client=redis_client, max_age_seconds=86400)
    runtime_payload = runtime_read.get("payload") if isinstance(runtime_read.get("payload"), Mapping) else {}
    signal_paths = signal_default_paths(repo_root)
    signal_status = read_json(signal_paths.signal_public_dir / "realtime_signal_publisher_status.json")
    signal_status = signal_status if isinstance(signal_status, Mapping) else {}
    live_paths = live_gate_default_paths(repo_root)
    connectivity = build_binance_connectivity_status(
        env_local_path=live_paths.env_local_path,
        generated_est=_est_iso(),
        network_probe_enabled=True,
    )
    trader_status = {
        "binance_private_readonly": connectivity,
        "trader_execution_enabled": bool((runtime_read.get("validation") or {}).get("valid")),
        "live_gate": runtime_payload.get("live_gate"),
        "live_symbols": runtime_payload.get("live_symbols") or [],
        "execution_live_symbols": runtime_payload.get("execution_live_symbols") or [],
    }
    account_margin = _account_margin_snapshot(repo_root, transport)
    open_orders = _open_orders_snapshot(repo_root, transport)
    fallback_context = _candidate_from_previous_artifacts(repo_root)
    pre_submit = evaluate_live_order_transport(
        repo_root=repo_root,
        signal_status=signal_status,
        trader_status=trader_status,
        runtime_read=runtime_read,
        redis_client=redis_client,
        dry_run=True,
    )
    symbol_map = build_min_executable_map(
        redis_client=redis_client,
        transport=transport,
        signal_status=signal_status,
        runtime_payload=runtime_payload,
        account_margin=account_margin,
    )
    signed_classification = build_signed_read_classification_status(
        account_margin=account_margin,
        open_orders=open_orders,
        pre_submit=pre_submit,
        connectivity=connectivity,
    )
    critical_account_gate = build_critical_account_read_gate_status(
        signed_classification=signed_classification,
        symbol_map=symbol_map,
    )
    balance_hold = build_balance_hold_status(
        runtime_payload=runtime_payload,
        pre_submit=pre_submit,
        symbol_map=symbol_map,
        account_margin=account_margin,
        critical_account_gate=critical_account_gate,
        fallback_context=fallback_context,
    )
    retry_guard = build_retry_guard_status(
        repo_root=repo_root,
        balance_hold=balance_hold,
        pre_submit=pre_submit,
        account_margin=account_margin,
    )

    submit_result: dict[str, Any] | None = None
    if (
        submit_if_balance_sufficient
        and balance_hold.get("margin_sufficient") is True
        and retry_guard.get("retry_allowed") is True
        and pre_submit.get("status") == "LIVE_ORDER_TRANSPORT_PRE_SUBMIT_READY"
    ):
        submit_result = evaluate_live_order_transport(
            repo_root=repo_root,
            signal_status=signal_status,
            trader_status=trader_status,
            runtime_read=runtime_read,
            redis_client=redis_client,
            dry_run=False,
        )

    resume = build_resume_condition_status(
        pre_submit=pre_submit,
        balance_hold=balance_hold,
        retry_guard=retry_guard,
        submit_result=submit_result,
    )
    trader_compliance_hold = build_trader_compliance_hold_state_status(
        runtime_payload=runtime_payload,
        critical_account_gate=critical_account_gate,
        signed_classification=signed_classification,
    )
    compliant_options = build_compliant_exchange_connectivity_options()
    failover_readiness = build_exchange_failover_readiness_status(repo_root, critical_account_gate)
    recovery_monitor = build_signed_read_recovery_monitor_status(
        signed_classification=signed_classification,
        critical_account_gate=critical_account_gate,
    )
    compliance_hold_monitor = build_binance_451_compliance_hold_monitor_status(
        repo_root=repo_root,
        signed_classification=signed_classification,
        critical_account_gate=critical_account_gate,
        symbol_map=symbol_map,
        balance_hold=balance_hold,
    )
    public_private_split = build_binance_public_vs_private_runtime_split_status(
        repo_root=repo_root,
        signal_publish_initial=signal_publish_initial,
        signal_publish=signal_publish,
        orchestration=orchestration,
        risk_gateway=risk_gateway,
        paper=paper,
        signed_classification=signed_classification,
        critical_account_gate=critical_account_gate,
    )
    binance_recovery_options = build_compliant_binance_access_recovery_options()
    failover_candidate_matrix = build_compliant_exchange_failover_candidate_matrix(repo_root)
    failover_gate_contract = build_exchange_failover_gate_contract_status()
    audited_failover_matrix = build_audited_exchange_failover_candidate_matrix(
        repo_root=repo_root,
        runtime_payload=runtime_payload,
        public_private_split=public_private_split,
    )
    audited_failover_selection = build_audited_exchange_failover_selection_proposal(
        matrix=audited_failover_matrix,
        runtime_payload=runtime_payload,
    )
    failover_probe = build_failover_exchange_read_only_probe_status(
        repo_root=repo_root,
        selection=audited_failover_selection,
    )
    failover_transport = build_failover_order_transport_status(
        selection=audited_failover_selection,
        probe=failover_probe,
    )
    failover_mapping = build_failover_symbol_risk_orchestrator_mapping_status(
        selection=audited_failover_selection,
        runtime_payload=runtime_payload,
        signal_status=signal_status,
    )
    previous_transport = redis_json(redis_client, KEY_STATUS)
    previous_transport = previous_transport if isinstance(previous_transport, Mapping) else {}
    post_monitor = {
        "schema_version": "post_live_enable_first_hour_status_v1",
        "generated_est": est_now(),
        "monitor_status": "COMPLIANCE_HOLD_ACTIVE"
        if balance_hold.get("compliance_hold_active") is True
        else "BALANCE_HOLD_ACTIVE"
        if balance_hold.get("margin_sufficient") is not True
        else "BALANCE_READY_MONITOR_ACTIVE",
        "orders_attempted": 1 if submit_result else 0,
        "orders_submitted": 1 if submit_result and submit_result.get("order_submitted") else 0,
        "orders_rejected": 1
        if submit_result and submit_result.get("submit_result") and not submit_result.get("order_submitted")
        else 0,
        "accepted_symbols": _accepted_symbols(runtime_payload),
        "kill_switch_active": pre_submit.get("kill_switch_active"),
        "latest_transport_status": submit_result.get("status") if submit_result else pre_submit.get("status"),
        "balance_hold_status": balance_hold.get("status"),
        "compliance_hold_active": balance_hold.get("compliance_hold_active") is True,
        "critical_account_read_gate_status": critical_account_gate.get("status"),
        "auto_freeze_conditions": [
            "symbol outside accepted list",
            "missing prediction_id/risk_decision_id/orchestrator_decision_id",
            "leverage/margin mutation attempted",
            "old Redis write detected",
            "raw credential leak",
            "risk gateway unavailable",
            "unexpected order endpoint",
        ],
    }
    validation = validation_status(repo_root) if run_validation_checks else preserved_validation_status(repo_root)

    blockers: list[str] = []
    runtime_validation = runtime_read.get("validation") if isinstance(runtime_read.get("validation"), Mapping) else {}
    blockers.extend(str(item) for item in runtime_validation.get("blockers") or [])
    if runtime_payload.get("live_gate") != LIVE_GATE_ENABLED:
        blockers.append("LIVE_GATE_NOT_ENABLED")
    if runtime_payload.get("trader_execution_enabled") is not True:
        blockers.append("TRADER_EXECUTION_NOT_ENABLED")
    if runtime_heartbeat.get("ok") is not True:
        blockers.append("LIVE_GATE_RUNTIME_HEARTBEAT_REFRESH_FAILED")
    if critical_account_gate.get("restricted_location_detected") is True:
        blockers.append(RESTRICTED_451)
        blockers.append("BLOCKED_BINANCE_SIGNED_READ_RESTRICTED")
    if account_margin.get("ok") is not True:
        blockers.append("BINANCE_ACCOUNT_MARGIN_READ_FAILED")
    if balance_hold.get("margin_sufficient") is not True:
        blockers.append(INSUFFICIENT_BALANCE)
    blockers.extend(str(item) for item in balance_hold.get("blockers") or [] if str(item))
    pre_submit_blockers = [str(item) for item in pre_submit.get("blockers") or [] if str(item)]
    blockers.extend(pre_submit_blockers)
    if retry_guard.get("retry_allowed") is not True and balance_hold.get("margin_sufficient") is True:
        blockers.append("RETRY_GUARD_NOT_RELEASED")
    if submit_result and submit_result.get("status") == "LIVE_ORDER_TRANSPORT_SUBMIT_FAILED":
        blockers.append("LIVE_ORDER_TRANSPORT_SUBMIT_FAILED")
    for label in (
        "py_compile",
        "focused_backend_tests",
        "frontend_typecheck",
        "frontend_build",
        "frontend_route_smoke",
        "forbidden_exchange_mutation_scan",
        "old_redis_scan",
        "raw_secret_scan",
    ):
        if validation.get(label, {}).get("status") == "FAIL":
            blockers.append(f"{label.upper()}_FAILED")
    blockers = sorted(set(blocker for blocker in blockers if blocker))

    hold_is_working = (
        balance_hold.get("trader_state") in {"LIVE_ARMED_BALANCE_HOLD", COMPLIANCE_HOLD}
        and retry_guard.get("retry_allowed") is False
        and submit_result is None
        and (INSUFFICIENT_BALANCE in blockers or RESTRICTED_451 in blockers)
    )
    balance_ready_without_blockers = (
        balance_hold.get("margin_sufficient") is True
        and not blockers
        and (submit_result is None or submit_result.get("order_submitted") is True)
    )
    validation_failed = any(
        validation.get(label, {}).get("status") == "FAIL"
        for label in (
            "py_compile",
            "focused_backend_tests",
            "frontend_typecheck",
            "frontend_build",
            "frontend_route_smoke",
            "forbidden_exchange_mutation_scan",
            "old_redis_scan",
            "raw_secret_scan",
        )
    )
    go_no_go = GATE_BLOCKED if validation_failed or not (hold_is_working or balance_ready_without_blockers) else GATE_READY

    candidate = balance_hold.get("selected_candidate") if isinstance(balance_hold.get("selected_candidate"), Mapping) else {}
    dashboard = {
        "schema_version": "operator_dashboard_payload_v1",
        "service_id": SERVICE_ID,
        "generated_est": generated_est,
        "go_no_go": go_no_go,
        "live_gate": runtime_payload.get("live_gate"),
        "trader_execution_enabled": runtime_payload.get("trader_execution_enabled") is True,
        "live_order_transport_bound": pre_submit.get("live_order_transport_bound") is True,
        "write_guard_enabled": pre_submit.get("runtime_write_guard_enabled") is True,
        "submit_guard_enabled": pre_submit.get("runtime_submit_enabled") is True,
        "transport_status": pre_submit.get("status"),
        "trader_state": balance_hold.get("trader_state"),
        "monitor_read_status": balance_hold.get("monitor_read_status"),
        "compliance_hold_active": balance_hold.get("compliance_hold_active") is True,
        "compliance_hold_reason": balance_hold.get("compliance_hold_reason"),
        "signed_read_classification": signed_classification.get("classification"),
        "signed_read_451_detected": signed_classification.get("restricted_location_detected") is True,
        "critical_account_read_gate_status": critical_account_gate.get("status"),
        "active_risk_profile": (runtime_payload.get("risk_profile") or {}).get("profile_name")
        if isinstance(runtime_payload.get("risk_profile"), Mapping)
        else None,
        "accepted_symbols": _accepted_symbols(runtime_payload),
        "selected_candidate_summary": {
            "symbol": candidate.get("symbol"),
            "side": candidate.get("side"),
            "position_side": candidate.get("position_side"),
            "quantity": candidate.get("quantity"),
            "requested_notional_usdt": candidate.get("requested_notional_usdt"),
        },
        "available_margin": balance_hold.get("available_margin"),
        "available_margin_current": balance_hold.get("available_margin_current"),
        "available_margin_source": balance_hold.get("available_margin_source"),
        "last_known_available_margin": balance_hold.get("last_known_available_margin"),
        "wallet_balance": balance_hold.get("wallet_balance"),
        "unrealized_pnl": balance_hold.get("unrealized_pnl"),
        "required_initial_margin": balance_hold.get("required_initial_margin"),
        "required_min_notional": balance_hold.get("required_min_notional"),
        "margin_sufficient": balance_hold.get("margin_sufficient"),
        "retry_allowed": retry_guard.get("retry_allowed"),
        "current_candidate_available": balance_hold.get("current_candidate_available"),
        "selected_candidate_source": balance_hold.get("selected_candidate_source"),
        "order_submitted": bool(submit_result and submit_result.get("order_submitted")),
        "writes_exchange_orders": bool(submit_result and submit_result.get("writes_exchange_orders")),
        "places_real_order": bool(submit_result and submit_result.get("places_real_order")),
        "blockers": blockers,
        "known_account_reason": RESTRICTED_451 if RESTRICTED_451 in blockers else INSUFFICIENT_BALANCE if INSUFFICIENT_BALANCE in blockers else None,
        "known_compliance_reason": RESTRICTED_451 if RESTRICTED_451 in blockers else None,
        "previous_transport_status": {
            "status": previous_transport.get("status"),
            "blockers": previous_transport.get("blockers"),
            "generated_est": previous_transport.get("generated_est"),
        },
        "refresh_runs": {
            "runtime_heartbeat": runtime_heartbeat,
            "signal_publish_initial": signal_publish_initial,
            "orchestrator": orchestration,
            "risk_gateway": risk_gateway,
            "paper": paper,
            "signal_publish_final": signal_publish,
        },
        "safety": {
            "no_test_order_cancel_modify": True,
            "no_leverage_margin_mutation": True,
            "no_transfer_or_withdrawal": True,
            "no_old_redis_write": True,
            "no_redis_trim": True,
            "no_legacy_restart": True,
            "raw_credentials_exposed": False,
            "raw_account_payload_exposed": False,
        },
        "validation": validation,
    }

    compliance_ready = (
        not validation_failed
        and (
            (
                critical_account_gate.get("restricted_location_detected") is True
                and balance_hold.get("trader_state") == COMPLIANCE_HOLD
                and retry_guard.get("retry_allowed") is False
                and submit_result is None
            )
            or critical_account_gate.get("ok") is True
        )
    )
    compliance_go_no_go = COMPLIANCE_GATE_READY if compliance_ready else COMPLIANCE_GATE_BLOCKED
    compliance_dashboard = {
        "schema_version": "operator_dashboard_payload_v1",
        "service_id": COMPLIANCE_SERVICE_ID,
        "generated_est": generated_est,
        "go_no_go": compliance_go_no_go,
        "live_gate": runtime_payload.get("live_gate"),
        "trader_execution_enabled": runtime_payload.get("trader_execution_enabled") is True,
        "live_order_transport_bound": pre_submit.get("live_order_transport_bound") is True,
        "trader_state": balance_hold.get("trader_state"),
        "transport_status": pre_submit.get("status"),
        "signed_read_classification": signed_classification.get("classification"),
        "signed_read_451_detected": signed_classification.get("restricted_location_detected") is True,
        "critical_account_read_gate_status": critical_account_gate.get("status"),
        "accepted_symbols": _accepted_symbols(runtime_payload),
        "active_risk_profile": (runtime_payload.get("risk_profile") or {}).get("profile_name")
        if isinstance(runtime_payload.get("risk_profile"), Mapping)
        else None,
        "available_margin": balance_hold.get("available_margin"),
        "available_margin_source": balance_hold.get("available_margin_source"),
        "position_mode_verified": critical_account_gate.get("account_critical_reads", {}).get("position_mode") == "API_OK"
        if isinstance(critical_account_gate.get("account_critical_reads"), Mapping)
        else False,
        "open_orders_verified": critical_account_gate.get("account_critical_reads", {}).get("open_orders") == "API_OK"
        if isinstance(critical_account_gate.get("account_critical_reads"), Mapping)
        else False,
        "order_submitted": False,
        "retry_allowed": retry_guard.get("retry_allowed") is True,
        "order_submit_disabled": True,
        "public_market_trainer_risk_orchestrator_keep_running": True,
        "paper_shadow_keep_running": True,
        "website_keep_updated": True,
        "blockers": sorted(set([str(item) for item in critical_account_gate.get("blockers") or [] if str(item)] + blockers)),
        "compliant_options_status": compliant_options.get("status"),
        "exchange_failover_status": failover_readiness.get("status"),
        "recovery_monitor_status": recovery_monitor.get("status"),
        "safety": {
            "no_order_test_order_cancel_modify": True,
            "no_leverage_margin_mutation": True,
            "no_transfer_or_withdrawal": True,
            "no_old_redis_write": True,
            "no_legacy_restart": True,
            "no_redis_trim": True,
            "no_vpn_proxy_evasion": True,
            "raw_credentials_exposed": False,
        },
        "validation": validation,
    }

    payloads: dict[str, Mapping[str, Any]] = {
        "live_transport_balance_hold_status.json": balance_hold,
        "live_gate_runtime_heartbeat_status.json": runtime_heartbeat,
        "live_symbol_min_executable_map.json": symbol_map,
        "live_order_retry_guard_status.json": retry_guard,
        "first_order_resume_condition_status.json": resume,
        "post_live_enable_first_hour_status.json": post_monitor,
        "account_margin_snapshot_status.json": account_margin,
        "open_orders_snapshot_status.json": open_orders,
        "binance_signed_read_451_classification_status.json": signed_classification,
        "live_critical_account_read_gate_status.json": critical_account_gate,
        "trader_compliance_hold_state_status.json": trader_compliance_hold,
        "compliant_exchange_connectivity_options.json": compliant_options,
        "exchange_failover_readiness_status.json": failover_readiness,
        "binance_signed_read_recovery_monitor_status.json": recovery_monitor,
        "live_order_transport_pre_submit_evaluation_status.json": {
            "schema_version": "live_order_transport_pre_submit_evaluation_status_v1",
            **pre_submit,
        },
        "operator_dashboard_payload.json": dashboard,
        "validation_status.json": validation,
    }
    report = render_report(dashboard)
    paths = mirror_outputs(repo_root, payloads, report)
    compliance_payloads: dict[str, Mapping[str, Any]] = {
        "binance_signed_read_451_classification_status.json": signed_classification,
        "live_critical_account_read_gate_status.json": critical_account_gate,
        "open_orders_snapshot_status.json": open_orders,
        "trader_compliance_hold_state_status.json": trader_compliance_hold,
        "compliant_exchange_connectivity_options.json": compliant_options,
        "exchange_failover_readiness_status.json": failover_readiness,
        "binance_signed_read_recovery_monitor_status.json": recovery_monitor,
        "operator_dashboard_payload.json": compliance_dashboard,
        "validation_status.json": validation,
    }
    compliance_report = render_compliance_report(compliance_dashboard)
    compliance_paths = mirror_compliance_outputs(repo_root, compliance_payloads, compliance_report)
    recovery_failover_ready = (
        not validation_failed
        and balance_hold.get("trader_state") == COMPLIANCE_HOLD
        and retry_guard.get("retry_allowed") is False
        and submit_result is None
        and compliance_hold_monitor.get("order_submission_allowed") is False
        and public_private_split.get("status") == "BINANCE_PUBLIC_RUNTIME_CONTINUES_PRIVATE_EXECUTION_HELD"
        and failover_gate_contract.get("automatic_failover_allowed") is False
    )
    recovery_failover_go_no_go = (
        RECOVERY_FAILOVER_GATE_READY if recovery_failover_ready else RECOVERY_FAILOVER_GATE_BLOCKED
    )
    recovery_failover_dashboard = {
        "schema_version": "operator_dashboard_payload_v1",
        "service_id": RECOVERY_FAILOVER_SERVICE_ID,
        "generated_est": generated_est,
        "go_no_go": recovery_failover_go_no_go,
        "live_gate": runtime_payload.get("live_gate"),
        "trader_execution_enabled": runtime_payload.get("trader_execution_enabled") is True,
        "live_order_transport_bound": pre_submit.get("live_order_transport_bound") is True,
        "trader_state": balance_hold.get("trader_state"),
        "binance_private_execution_status": "COMPLIANCE_HELD_HTTP_451"
        if signed_classification.get("restricted_location_detected") is True
        else "SIGNED_READS_RECOVERED_REQUIRES_REVALIDATION",
        "signed_read_classification": signed_classification.get("classification"),
        "critical_account_read_gate_status": critical_account_gate.get("status"),
        "public_runtime_status": public_private_split.get("status"),
        "public_runtime_services": public_private_split.get("public_runtime_services"),
        "failover_status": failover_candidate_matrix.get("status"),
        "failover_gate_contract_status": failover_gate_contract.get("status"),
        "order_submitted": False,
        "retry_allowed": retry_guard.get("retry_allowed") is True,
        "order_submission_allowed": False,
        "accepted_symbols": _accepted_symbols(runtime_payload),
        "active_risk_profile": (runtime_payload.get("risk_profile") or {}).get("profile_name")
        if isinstance(runtime_payload.get("risk_profile"), Mapping)
        else None,
        "compliant_recovery_options": binance_recovery_options.get("allowed_options"),
        "disallowed_recovery_options": binance_recovery_options.get("disallowed_options"),
        "failover_candidate_count": len(failover_candidate_matrix.get("candidates") or []),
        "blockers": sorted(set([str(item) for item in critical_account_gate.get("blockers") or [] if str(item)] + blockers)),
        "safety": {
            "no_vpn_proxy_evasion": True,
            "no_order_test_order_cancel_modify": True,
            "no_leverage_margin_mutation": True,
            "no_transfer_or_withdrawal": True,
            "no_old_redis_write": True,
            "no_legacy_restart": True,
            "no_redis_trim": True,
            "raw_credentials_exposed": False,
            "automatic_live_failover_allowed": False,
        },
        "validation": validation,
    }
    recovery_failover_payloads: dict[str, Mapping[str, Any]] = {
        "binance_451_compliance_hold_monitor_status.json": compliance_hold_monitor,
        "binance_public_vs_private_runtime_split_status.json": public_private_split,
        "compliant_binance_access_recovery_options.json": binance_recovery_options,
        "compliant_exchange_failover_candidate_matrix.json": failover_candidate_matrix,
        "exchange_failover_gate_contract_status.json": failover_gate_contract,
        "operator_dashboard_payload.json": recovery_failover_dashboard,
        "validation_status.json": validation,
    }
    recovery_failover_report = render_recovery_failover_report(recovery_failover_dashboard)
    recovery_failover_paths = mirror_recovery_failover_outputs(
        repo_root,
        recovery_failover_payloads,
        recovery_failover_report,
    )
    audited_failover_blockers = sorted(
        set(
            [str(item) for item in critical_account_gate.get("blockers") or [] if str(item)]
            + [
                "BINANCE_PRIVATE_EXECUTION_COMPLIANCE_HELD_HTTP_451",
                "FAILOVER_OPERATOR_ACCEPTANCE_REQUIRED",
                "FAILOVER_SIGNED_READ_ONLY_PROBE_NOT_PASSED",
                "FAILOVER_ORDER_TRANSPORT_NOT_ENABLED",
                "FAILOVER_LIVE_ENABLE_NOT_APPROVED",
            ]
            + [str(item) for item in failover_probe.get("blockers") or [] if str(item)]
            + [str(item) for item in failover_transport.get("blockers") or [] if str(item)]
        )
    )
    audited_failover_ready = (
        not validation_failed
        and balance_hold.get("trader_state") == COMPLIANCE_HOLD
        and public_private_split.get("status") == "BINANCE_PUBLIC_RUNTIME_CONTINUES_PRIVATE_EXECUTION_HELD"
        and failover_transport.get("order_submission_allowed") is False
        and failover_transport.get("order_transport_enabled") is False
        and audited_failover_matrix.get("automatic_live_failover_allowed") is False
        and signed_classification.get("restricted_location_detected") is True
    )
    audited_failover_go_no_go = AUDITED_FAILOVER_GATE_READY if audited_failover_ready else AUDITED_FAILOVER_GATE_BLOCKED
    audited_failover_dashboard = {
        "schema_version": "operator_dashboard_payload_v1",
        "service_id": AUDITED_FAILOVER_SERVICE_ID,
        "generated_est": generated_est,
        "go_no_go": audited_failover_go_no_go,
        "live_gate": runtime_payload.get("live_gate"),
        "trader_execution_enabled": runtime_payload.get("trader_execution_enabled") is True,
        "trader_state": balance_hold.get("trader_state"),
        "binance_private_execution_status": "COMPLIANCE_HELD_HTTP_451"
        if signed_classification.get("restricted_location_detected") is True
        else "SIGNED_READS_RECOVERED_REQUIRES_REVALIDATION",
        "signed_read_classification": signed_classification.get("classification"),
        "critical_account_read_gate_status": critical_account_gate.get("status"),
        "public_runtime_status": public_private_split.get("status"),
        "binance_public_data_active": public_private_split.get("status")
        == "BINANCE_PUBLIC_RUNTIME_CONTINUES_PRIVATE_EXECUTION_HELD",
        "proposed_exchange": audited_failover_selection.get("proposed_exchange"),
        "proposed_symbols": audited_failover_selection.get("proposed_symbols"),
        "required_credentials_by_name": audited_failover_selection.get("required_credentials_by_name"),
        "credentials_present_by_name": audited_failover_selection.get("credentials_present_by_name"),
        "failover_selection_status": audited_failover_selection.get("status"),
        "failover_read_only_probe_status": failover_probe.get("status"),
        "failover_read_only_probe_passed": failover_probe.get("probe_passed") is True,
        "failover_order_transport_status": failover_transport.get("status"),
        "failover_order_transport_enabled": failover_transport.get("order_transport_enabled") is True,
        "failover_symbol_mapping_status": failover_mapping.get("status"),
        "failover_live_enabled": False,
        "order_submission_allowed": False,
        "automatic_live_failover_allowed": False,
        "operator_acceptance_required": True,
        "endpoint_contracts": {
            "accept_failover_exchange": {
                "method": "POST",
                "path": "/api/v1/live-gate/accept-failover-exchange",
                "operator_confirmation_text_required": "ACCEPT V2 LIVE FAILOVER EXCHANGE",
            },
            "accept_failover_symbols": {
                "method": "POST",
                "path": "/api/v1/live-gate/accept-failover-symbols",
                "operator_confirmation_text_required": "ACCEPT V2 LIVE FAILOVER SYMBOLS",
            },
            "failover_final_approval": {
                "method": "POST",
                "path": "/api/v1/live-gate/failover-final-approval",
                "operator_confirmation_text_required": "APPROVE V2 LIVE FAILOVER FINAL GATE",
            },
        },
        "blockers": audited_failover_blockers,
        "safety": {
            "binance_private_execution_held_while_451": True,
            "binance_public_data_continues": True,
            "no_vpn_proxy_evasion": True,
            "no_order_test_order_cancel_modify": True,
            "no_leverage_margin_mutation": True,
            "no_transfer_or_withdrawal": True,
            "no_old_redis_write": True,
            "no_legacy_restart": True,
            "no_redis_trim": True,
            "raw_credentials_exposed": False,
            "automatic_live_failover_allowed": False,
        },
        "validation": validation,
    }
    audited_failover_payloads: dict[str, Mapping[str, Any]] = {
        "audited_exchange_failover_candidate_matrix.json": audited_failover_matrix,
        "audited_exchange_failover_selection_proposal.json": audited_failover_selection,
        "failover_exchange_read_only_probe_status.json": failover_probe,
        "failover_order_transport_status.json": failover_transport,
        "failover_symbol_risk_orchestrator_mapping_status.json": failover_mapping,
        "operator_dashboard_payload.json": audited_failover_dashboard,
        "validation_status.json": validation,
    }
    audited_failover_report = render_audited_failover_report(audited_failover_dashboard)
    audited_failover_paths = mirror_audited_failover_outputs(
        repo_root,
        audited_failover_payloads,
        audited_failover_report,
    )
    return {
        "go_no_go": go_no_go,
        "compliance_go_no_go": compliance_go_no_go,
        "recovery_failover_go_no_go": recovery_failover_go_no_go,
        "audited_failover_go_no_go": audited_failover_go_no_go,
        "payloads": payloads,
        "compliance_payloads": compliance_payloads,
        "recovery_failover_payloads": recovery_failover_payloads,
        "audited_failover_payloads": audited_failover_payloads,
        "paths_written": paths + compliance_paths + recovery_failover_paths + audited_failover_paths,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=SERVICE_ID)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--no-submit", action="store_true", help="Hold/monitor only even if balance becomes sufficient.")
    parser.add_argument("--skip-validation", action="store_true")
    args = parser.parse_args(argv)
    result = run_once(
        Path(args.repo_root).resolve(),
        submit_if_balance_sufficient=not bool(args.no_submit),
        run_validation_checks=not bool(args.skip_validation),
    )
    print(
        json.dumps(
            {
                "go_no_go": result["go_no_go"],
                "compliance_go_no_go": result.get("compliance_go_no_go"),
                "recovery_failover_go_no_go": result.get("recovery_failover_go_no_go"),
                "audited_failover_go_no_go": result.get("audited_failover_go_no_go"),
                "paths_written": result["paths_written"],
            },
            indent=2,
        )
    )
    return 0 if result["go_no_go"] == GATE_READY else 2


if __name__ == "__main__":
    raise SystemExit(main())
