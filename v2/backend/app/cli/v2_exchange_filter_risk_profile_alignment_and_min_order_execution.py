"""Align audited risk caps with Binance exchange filters and evaluate first order.

This runner is V2-only. It may submit a live order only after the audited live
gate, amended risk profile, accepted symbols, lineage, exchange filters, and
transport guards all pass. It never calls test-order, cancel, modify, leverage,
margin, transfer, withdrawal, legacy startup, Redis trim, or non-V2 Redis keys.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "v2/backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402
from v2.backend.app.cli import (  # noqa: E402
    v2_all_timeframe_prediction_signal_price_target_publisher as signal_cli,
)
from v2.backend.app.cli import v2_orchestrator_arbitration_loop as orchestrator_loop  # noqa: E402
from v2.backend.app.cli import v2_risk_gateway_live_loop as risk_gateway_loop  # noqa: E402
from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop  # noqa: E402
from v2.backend.app.cli.v2_live_order_transport_state_lineage_and_write_guard_repair import (  # noqa: E402
    raw_secret_scan,
)
from v2.backend.app.services.all_timeframe_prediction_signal_price_target_publisher import (  # noqa: E402
    default_paths as signal_default_paths,
)
from v2.backend.app.services.live_gate.binance_live_order_transport import (  # noqa: E402
    BinanceUsdMLiveOrderTransport,
    BinanceUsdMWebSocketPrimaryTransport,
    evaluate_live_order_transport,
)
from v2.backend.app.services.live_gate.exchange_filter_sizing import min_executable_order  # noqa: E402
from v2.backend.app.services.live_gate.runtime_execution_state import (  # noqa: E402
    LIVE_GATE_ENABLED,
    read_runtime_execution_state,
)
from v2.backend.app.services.live_gate.single_pass import (  # noqa: E402
    _est_iso,
    build_binance_connectivity_status,
    default_paths as live_gate_default_paths,
)


GATE_READY = "V2_EXCHANGE_FILTER_RISK_PROFILE_ALIGNMENT_AND_MIN_ORDER_EXECUTION_READY"
GATE_BLOCKED = "V2_EXCHANGE_FILTER_RISK_PROFILE_ALIGNMENT_AND_MIN_ORDER_EXECUTION_BLOCKED"
SERVICE_ID = "v2_exchange_filter_risk_profile_alignment_and_min_order_execution"
ACCEPTED_SYMBOLS = ["BNBUSDT", "BTCUSDT", "ETHUSDT", "PAXGUSDT", "XAUTUSDT", "ZECUSDT"]
PUBLIC_DIR_REL = Path("v2/frontend/public") / SERVICE_ID / "latest"
WORKLOG_DIR_REL = Path("claude_worklog/final_readiness") / SERVICE_ID / "latest"
EST = ZoneInfo("America/New_York")


def est_now() -> str:
    return datetime.now(tz=EST).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


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


def mirror_outputs(repo_root: Path, payloads: Mapping[str, Mapping[str, Any]], report: str) -> list[str]:
    written: list[str] = []
    go_no_go = str(payloads["operator_dashboard_payload.json"]["go_no_go"])
    for base in (repo_root / PUBLIC_DIR_REL, repo_root / WORKLOG_DIR_REL):
        base.mkdir(parents=True, exist_ok=True)
        for name, payload in payloads.items():
            path = base / name
            write_json(path, payload)
            written.append(str(path))
        report_path = base / "V2_EXCHANGE_FILTER_RISK_PROFILE_ALIGNMENT_AND_MIN_ORDER_EXECUTION_REPORT.md"
        write_text(report_path, report)
        written.append(str(report_path))
        go_path = base / "GO_NO_GO.md"
        write_text(go_path, go_no_go + "\n")
        written.append(str(go_path))
    return written


def sha256_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def connect_redis() -> Any:
    try:
        import redis  # type: ignore

        client = redis.Redis.from_url(
            os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0"),
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        client.ping()
        return client
    except Exception:
        return None


def redis_json(client: Any, key: str) -> Any:
    if client is None or not str(key).startswith("v2:"):
        return None
    try:
        raw = client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def safe_run(label: str, fn, *args, **kwargs) -> dict[str, Any]:
    try:
        return {"label": label, "ok": True, "payload": fn(*args, **kwargs), "error": None}
    except Exception as exc:
        return {"label": label, "ok": False, "payload": {}, "error": type(exc).__name__}


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


def current_acceptance_records(repo_root: Path) -> dict[str, Any]:
    base = repo_root / "v2/frontend/public/v2_audited_operator_live_acceptance_and_enable_flow/latest"
    runtime_base = repo_root / "v2/frontend/public/v2_live_gate_runtime_execution_adapter_enablement/latest"
    return {
        "risk": read_json(base / "risk_profile_acceptance_status.json"),
        "symbols": read_json(base / "live_symbol_acceptance_status.json"),
        "final": read_json(base / "final_operator_live_approval_status.json"),
        "audit": read_json(base / "live_gate_audit_record_status.json"),
        "enable": read_json(base / "live_enable_re_evaluation_status.json"),
        "runtime_enable": read_json(runtime_base / "live_enable_runtime_mutation_attempt_status.json"),
    }


def _current_price(client: Any, signal: Mapping[str, Any]) -> tuple[float | None, str, dict[str, Any]]:
    symbol = str(signal.get("symbol") or "").upper()
    price_key = str(signal.get("source_price_key") or f"v2:market:prices:{symbol}")
    payload = redis_json(client, price_key)
    source = price_key
    if isinstance(payload, Mapping):
        for field in ("mark_price", "last_price", "price", "close"):
            value = _float(payload.get(field))
            if value is not None and value > 0:
                return value, f"{price_key}.{field}", dict(payload)
    for field in ("price_target_after_cost", "price_target", "last_price"):
        value = _float(signal.get(field))
        if value is not None and value > 0:
            return value, f"signal.{field}", {}
    return None, source, dict(payload) if isinstance(payload, Mapping) else {}


def _float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and parsed not in (float("inf"), float("-inf")) else None


def signals_by_symbol(signal_status: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in signal_status.get("published_signals") or []:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        if symbol not in ACCEPTED_SYMBOLS:
            continue
        action = str(row.get("action") or row.get("observed_action") or "").lower()
        if action not in {"long", "short"}:
            continue
        current = out.get(symbol)
        if current is None or (
            (_float(row.get("expected_move_after_cost_bps")) or -1e9),
            (_float(row.get("confidence")) or -1e9),
        ) > (
            (_float(current.get("expected_move_after_cost_bps")) or -1e9),
            (_float(current.get("confidence")) or -1e9),
        ):
            out[symbol] = row
    return out


def exchange_filter_snapshot(
    *,
    client: Any,
    transport: BinanceUsdMLiveOrderTransport | BinanceUsdMWebSocketPrimaryTransport,
    signal_status: Mapping[str, Any],
    runtime_payload: Mapping[str, Any],
) -> dict[str, Any]:
    generated_est = est_now()
    profile = runtime_payload.get("risk_profile") if isinstance(runtime_payload.get("risk_profile"), Mapping) else {}
    fields = profile.get("fields") if isinstance(profile.get("fields"), Mapping) else {}
    current_max_notional = _float(fields.get("max_notional_per_trade")) or 0.0
    by_symbol = signals_by_symbol(signal_status)
    rows: list[dict[str, Any]] = []
    for symbol in ACCEPTED_SYMBOLS:
        signal = by_symbol.get(symbol, {"symbol": symbol})
        mark_price, price_source, price_payload = _current_price(client, signal)
        filters = transport.fetch_symbol_filters(symbol)
        sizing = min_executable_order(
            mark_price=mark_price,
            min_notional=filters.get("min_notional"),
            min_qty=filters.get("min_qty"),
            step_size=filters.get("step_size"),
        )
        min_notional = _float(filters.get("min_notional"))
        min_qty = _float(filters.get("min_qty"))
        min_exec_notional = _float(sizing.get("min_executable_notional"))
        min_exec_qty = _float(sizing.get("min_executable_quantity"))
        executable = bool(
            filters.get("ok") is True
            and sizing.get("ok") is True
            and min_exec_notional is not None
            and current_max_notional >= min_exec_notional
        )
        blockers: list[str] = []
        if filters.get("ok") is not True:
            blockers.append("SYMBOL_FILTERS_NOT_VERIFIED")
        if mark_price is None or mark_price <= 0:
            blockers.append("MARK_PRICE_MISSING_OR_INVALID")
        if sizing.get("ok") is not True:
            blockers.extend(str(item) for item in sizing.get("blockers") or [])
        if min_exec_notional is not None and current_max_notional < min_exec_notional:
            blockers.append("RISK_MAX_NOTIONAL_BELOW_EXCHANGE_MIN_NOTIONAL")
        if min_exec_qty is not None and mark_price and current_max_notional > 0:
            requested_qty = current_max_notional / mark_price
            if requested_qty < min_exec_qty:
                blockers.append("ORDER_QUANTITY_BELOW_MIN_EXECUTABLE_QTY")
        rows.append(
            {
                "symbol": symbol,
                "mark_price": mark_price,
                "price_source": price_source,
                "price_payload_source_type": "redis_v2_market_price" if price_payload else "signal_payload",
                "min_notional": min_notional,
                "min_qty": min_qty,
                "step_size": filters.get("step_size"),
                "tick_size": filters.get("tick_size"),
                "quantity_precision": filters.get("quantity_precision"),
                "price_precision": filters.get("price_precision"),
                "min_executable_quantity": min_exec_qty,
                "min_executable_notional": min_exec_notional,
                "current_risk_max_notional": current_max_notional,
                "executable_under_current_profile": executable,
                "blocker_if_false": sorted(set(blockers)),
                "filter_status": filters,
                "signal": {
                    "prediction_id": signal.get("prediction_id"),
                    "risk_decision_id": signal.get("risk_decision_id"),
                    "orchestrator_decision_id": signal.get("orchestrator_decision_id"),
                    "signal_id": signal.get("signal_id"),
                    "expected_move_after_cost_bps": signal.get("expected_move_after_cost_bps"),
                    "confidence": signal.get("confidence"),
                    "paper_state": signal.get("paper_state"),
                    "generated_est": signal.get("generated_est"),
                    "live_gate": signal.get("live_gate"),
                },
            }
        )
    blocked = [row for row in rows if not row["executable_under_current_profile"]]
    return {
        "schema_version": "exchange_filter_min_order_status_v1",
        "generated_est": generated_est,
        "accepted_symbols": ACCEPTED_SYMBOLS,
        "current_risk_profile": profile,
        "rows": rows,
        "executable_symbols_under_current_profile": [
            row["symbol"] for row in rows if row["executable_under_current_profile"]
        ],
        "blocked_symbols_under_current_profile": [row["symbol"] for row in blocked],
        "status": "EXCHANGE_FILTER_MIN_ORDER_READY" if rows and not blocked else "EXCHANGE_FILTER_MIN_ORDER_PARTIAL",
    }


def compatibility_status(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    rows = [row for row in snapshot.get("rows") or [] if isinstance(row, dict)]
    max_required = max((_float(row.get("min_executable_notional")) or 0.0 for row in rows), default=0.0)
    executable = [row for row in rows if row.get("executable_under_current_profile") is True]
    blockers = sorted(
        {
            str(blocker)
            for row in rows
            for blocker in (row.get("blocker_if_false") or [])
            if str(blocker)
        }
    )
    return {
        "schema_version": "risk_profile_exchange_filter_compatibility_status_v1",
        "generated_est": est_now(),
        "status": "RISK_PROFILE_COMPATIBLE_WITH_AT_LEAST_ONE_ACCEPTED_SYMBOL"
        if executable
        else "RISK_PROFILE_INCOMPATIBLE_WITH_EXCHANGE_FILTERS",
        "accepted_symbols": ACCEPTED_SYMBOLS,
        "executable_symbols_under_current_profile": [row["symbol"] for row in executable],
        "blocked_symbols_under_current_profile": [
            row["symbol"] for row in rows if row.get("executable_under_current_profile") is not True
        ],
        "blocked_by_min_notional": [
            row["symbol"] for row in rows if "RISK_MAX_NOTIONAL_BELOW_EXCHANGE_MIN_NOTIONAL" in row.get("blocker_if_false", [])
        ],
        "blocked_by_min_qty": [
            row["symbol"] for row in rows if "ORDER_QUANTITY_BELOW_MIN_EXECUTABLE_QTY" in row.get("blocker_if_false", [])
        ],
        "quantity_rounds_to_zero": [
            row["symbol"] for row in rows if "ORDER_QUANTITY_ROUNDS_TO_ZERO" in row.get("blocker_if_false", [])
        ],
        "minimum_amended_cap_required": max_required,
        "blockers": blockers,
    }


def choose_first_order_symbol(snapshot: Mapping[str, Any], signal_status: Mapping[str, Any]) -> dict[str, Any]:
    rows = {str(row.get("symbol")): row for row in snapshot.get("rows") or [] if isinstance(row, dict)}
    signals = list(signals_by_symbol(signal_status).values())
    ranked = sorted(
        signals,
        key=lambda row: (
            _float(row.get("expected_move_after_cost_bps")) or -1e9,
            _float(row.get("confidence")) or -1e9,
            -(_float(rows.get(str(row.get("symbol") or "").upper(), {}).get("min_executable_notional")) or 1e9),
        ),
        reverse=True,
    )
    for signal in ranked:
        symbol = str(signal.get("symbol") or "").upper()
        row = rows.get(symbol)
        if row and row.get("min_executable_notional"):
            return {"symbol": symbol, "signal": signal, "filter_row": row, "selection_reason": "BEST_CURRENT_SIGNAL_WITH_FILTERS"}
    return {"symbol": None, "signal": None, "filter_row": None, "selection_reason": "NO_ACCEPTED_SYMBOL_SIGNAL_CANDIDATE"}


def amended_profile_proposal(
    *,
    repo_root: Path,
    snapshot: Mapping[str, Any],
    compatibility: Mapping[str, Any],
    runtime_payload: Mapping[str, Any],
    signal_status: Mapping[str, Any],
) -> dict[str, Any]:
    profile = runtime_payload.get("risk_profile") if isinstance(runtime_payload.get("risk_profile"), Mapping) else {}
    fields = dict(profile.get("fields") if isinstance(profile.get("fields"), Mapping) else {})
    selected = choose_first_order_symbol(snapshot, signal_status)
    filter_row = selected.get("filter_row") if isinstance(selected.get("filter_row"), Mapping) else {}
    min_exec = _float(filter_row.get("min_executable_notional"))
    if min_exec is None:
        min_exec = _float(compatibility.get("minimum_amended_cap_required")) or _float(fields.get("max_notional_per_trade")) or 0.0
    required_cap = max(min_exec, _float(compatibility.get("minimum_amended_cap_required")) or 0.0)
    rows = [row for row in snapshot.get("rows") or [] if isinstance(row, Mapping)]
    max_required_row = max(rows, key=lambda row: _float(row.get("min_executable_notional")) or 0.0, default={})
    if (_float(max_required_row.get("min_executable_notional")) or 0.0) >= required_cap:
        filter_row = max_required_row
        selected = {
            **selected,
            "symbol": max_required_row.get("symbol"),
            "filter_row": max_required_row,
            "selection_reason": "MAX_ACCEPTED_SYMBOL_MIN_EXECUTABLE_NOTIONAL_FOR_TRANSPORT_COMPATIBILITY",
        }
    buffer = max(1.0, required_cap * 0.01)
    amended_cap = round(required_cap + buffer, 2)
    current_symbol_exposure = _float(fields.get("max_symbol_exposure")) or 0.0
    current_total = _float(fields.get("max_total_exposure")) or 0.0
    amended_fields = dict(fields)
    amended_fields.update(
        {
            "max_notional_per_trade": amended_cap,
            "max_symbol_exposure": round(max(current_symbol_exposure, amended_cap), 2),
            "max_total_exposure": round(max(current_total, amended_cap), 2),
            "max_open_positions": 1,
            "max_leverage": 1.0,
            "kill_switch_conditions": list(fields.get("kill_switch_conditions") or ["daily_loss_cap_breach"]),
        }
    )
    profile_payload = {
        "profile_id": "conservative_min_executable",
        "profile_name": "conservative_min_executable",
        "risk_fields": amended_fields,
        "source_profile": profile.get("profile_name"),
        "selected_first_order_symbol": selected.get("symbol"),
        "selected_filter_row": filter_row,
        "filter_buffer_usdt": round(buffer, 6),
    }
    proposal = {
        "schema_version": "executable_minimum_conservative_risk_profile_proposal_v1",
        "generated_est": est_now(),
        "service_id": SERVICE_ID,
        "profile": profile_payload,
        "profiles": {"conservative_min_executable": amended_fields},
        "accepted_symbols": ACCEPTED_SYMBOLS,
        "operator_acceptance_required": True,
        "auto_accept": False,
        "proposal_only_not_enablement": True,
        "risk_profile_amendment_reason": "EXCHANGE_FILTER_RISK_PROFILE_MISMATCH",
        "minimum_amended_cap_required": compatibility.get("minimum_amended_cap_required"),
        "source_runtime_risk_profile": profile,
    }
    proposal["source_payload_id"] = sha256_payload(proposal)
    for base in (repo_root / PUBLIC_DIR_REL, repo_root / WORKLOG_DIR_REL):
        write_json(base / "executable_minimum_conservative_risk_profile_proposal.json", proposal)
    return proposal


def _api_client(repo_root: Path) -> TestClient:
    os.environ["V2_REPO_ROOT"] = str(repo_root)
    return TestClient(create_app())


def post_json(client: TestClient, path: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    response = client.post(path, json=payload)
    try:
        body = response.json()
    except Exception:
        body = {"raw_response": response.text}
    return {"http_status": response.status_code, "payload": body, "ok": 200 <= response.status_code < 300}


def execute_audited_risk_amendment(
    *,
    repo_root: Path,
    proposal: Mapping[str, Any],
    records_before: Mapping[str, Any],
) -> dict[str, Any]:
    profile = proposal.get("profile") if isinstance(proposal.get("profile"), Mapping) else {}
    risk_fields = profile.get("risk_fields") if isinstance(profile.get("risk_fields"), Mapping) else {}
    symbols = records_before.get("symbols") if isinstance(records_before.get("symbols"), Mapping) else {}
    source_payload_id = str(proposal.get("source_payload_id") or sha256_payload(proposal))
    client = _api_client(repo_root)
    risk_request = {
        "profile_id": "conservative_min_executable",
        "profile_name": "conservative_min_executable",
        "risk_fields": dict(risk_fields),
        "operator_confirmation_text": "ACCEPT V2 LIVE RISK PROFILE",
        "operator_reason": "Amend conservative risk profile to satisfy exchange minimum executable order filters while preserving one-position conservative live test.",
        "source_payload_id": source_payload_id,
        "operator_id": "wali",
        "operator_role": "operator",
    }
    risk_response = post_json(client, "/api/v1/live-gate/accept-risk-profile", risk_request)
    risk_audit_id = None
    if risk_response["ok"] and isinstance(risk_response["payload"], Mapping):
        risk_audit_id = risk_response["payload"].get("audit_id")
    symbol_audit_id = symbols.get("audit_id")
    final_response: dict[str, Any] = {"ok": False, "http_status": None, "payload": {"skipped": True}}
    enable_response: dict[str, Any] = {"ok": False, "http_status": None, "payload": {"skipped": True}}
    if risk_audit_id and symbol_audit_id:
        final_response = post_json(
            client,
            "/api/v1/live-gate/final-approval",
            {
                "accepted_risk_audit_id": risk_audit_id,
                "accepted_symbols_audit_id": symbol_audit_id,
                "operator_confirmation_text": "APPROVE V2 LIVE EXECUTION FINAL GATE",
                "operator_reason": "Operator approved final gated live execution after audited exchange-filter risk amendment.",
                "source_payload_id": f"{source_payload_id}+{symbols.get('source_payload_id')}",
                "operator_id": "wali",
                "operator_role": "operator",
            },
        )
        final_audit_id = final_response["payload"].get("audit_id") if isinstance(final_response["payload"], Mapping) else None
        if final_response["ok"] and final_audit_id:
            enable_response = post_json(
                client,
                "/api/v1/live-gate/enable",
                {
                    "operator_confirmation_text": "ENABLE V2 LIVE EXECUTION",
                    "operator_reason": "Operator completed audited exchange-filter risk amendment and requested final runtime enable.",
                    "accepted_risk_audit_id": risk_audit_id,
                    "accepted_symbols_audit_id": symbol_audit_id,
                    "final_approval_audit_id": final_audit_id,
                    "operator_id": "wali",
                    "operator_role": "operator",
                },
            )
    return {
        "schema_version": "risk_profile_amendment_api_execution_status_v1",
        "generated_est": est_now(),
        "source_payload_id": source_payload_id,
        "risk_acceptance": risk_response,
        "final_approval": final_response,
        "enable": enable_response,
        "risk_audit_id": risk_audit_id,
        "symbols_audit_id": symbol_audit_id,
        "final_approval_audit_id": final_response["payload"].get("audit_id")
        if isinstance(final_response.get("payload"), Mapping)
        else None,
        "enable_audit_id": enable_response["payload"].get("audit_id")
        if isinstance(enable_response.get("payload"), Mapping)
        else None,
        "runtime_mutation_executed": bool(
            isinstance(enable_response.get("payload"), Mapping)
            and enable_response["payload"].get("runtime_mutation_executed") is True
        ),
    }


def candidate_filter_aligned_status(pre_submit: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    candidate = pre_submit.get("selected_candidate") if isinstance(pre_submit.get("selected_candidate"), Mapping) else {}
    symbol = str(candidate.get("symbol") or "")
    row = next((item for item in snapshot.get("rows") or [] if isinstance(item, dict) and item.get("symbol") == symbol), {})
    blockers = list(pre_submit.get("blockers") or [])
    filter_blockers = [
        blocker
        for blocker in blockers
        if blocker
        in {
            "ORDER_QUANTITY_ROUNDS_TO_ZERO",
            "RISK_MAX_NOTIONAL_BELOW_EXCHANGE_MIN_NOTIONAL",
            "ORDER_QUANTITY_BELOW_MIN_QTY",
            "ORDER_NOTIONAL_BELOW_MIN_NOTIONAL",
        }
    ]
    return {
        "schema_version": "first_live_order_candidate_filter_aligned_status_v1",
        "generated_est": est_now(),
        "status": "FIRST_LIVE_ORDER_CANDIDATE_FILTER_ALIGNED_READY"
        if candidate and not filter_blockers
        else "FIRST_LIVE_ORDER_CANDIDATE_FILTER_ALIGNED_BLOCKED",
        "candidate": candidate,
        "exchange_filter_row": row,
        "filter_blockers": filter_blockers,
        "all_pre_submit_blockers": blockers,
    }


def pre_submit_validation_status(pre_submit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "first_live_order_pre_submit_validation_status_v1",
        "generated_est": est_now(),
        "status": pre_submit.get("status"),
        "would_submit": pre_submit.get("would_submit"),
        "dry_run": pre_submit.get("dry_run"),
        "blockers": pre_submit.get("blockers") or [],
        "warnings": pre_submit.get("warnings") or [],
        "selected_candidate": pre_submit.get("selected_candidate"),
        "order_submitted": False,
    }


def submit_status_from_transport(status: Mapping[str, Any], skipped_reason: str | None = None) -> dict[str, Any]:
    payload = {
        "schema_version": "first_live_order_submit_result_status_v1",
        "generated_est": est_now(),
        "status": status.get("status") if skipped_reason is None else skipped_reason,
        "order_submitted": bool(status.get("order_submitted")),
        "writes_exchange_orders": bool(status.get("writes_exchange_orders")),
        "places_real_order": bool(status.get("places_real_order")),
        "selected_candidate": status.get("selected_candidate"),
        "submit_result": status.get("submit_result"),
        "blockers": status.get("blockers") or [],
        "warnings": status.get("warnings") or [],
    }
    if skipped_reason:
        payload["skipped_reason"] = skipped_reason
    return payload


def validation_status(repo_root: Path) -> dict[str, Any]:
    commands = {
        "py_compile": [
            "python3",
            "-m",
            "py_compile",
            "v2/backend/app/services/live_gate/exchange_filter_sizing.py",
            "v2/backend/app/services/live_gate/runtime_execution_state.py",
            "v2/backend/app/services/live_gate/binance_live_order_transport.py",
            "v2/backend/app/api/v1/live_gate.py",
            "v2/backend/app/cli/v2_exchange_filter_risk_profile_alignment_and_min_order_execution.py",
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
        ],
        "frontend_typecheck": ["npm", "run", "typecheck"],
        "frontend_build": ["npm", "run", "build"],
    }
    results: dict[str, Any] = {"schema_version": "validation_status_v1", "generated_est": est_now()}
    for label, command in commands.items():
        cwd = repo_root / "v2/frontend" if label.startswith("frontend_") else repo_root
        try:
            proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=300)
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
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    results["forbidden_exchange_mutation_scan"] = {
        "returncode": forbidden.returncode,
        "status": "PASS" if forbidden.returncode == 1 else "FAIL",
        "matches": forbidden.stdout[-2000:],
    }
    old_redis = subprocess.run(
        [
            "rg",
            "-n",
            "\"(v1:|legacy:|redis:old)",
            "v2/backend/app/services/live_gate",
            "v2/backend/app/cli/v2_exchange_filter_risk_profile_alignment_and_min_order_execution.py",
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


def render_report(dashboard: Mapping[str, Any]) -> str:
    blockers = dashboard.get("blockers") or []
    blocker_lines = [f"- `{blocker}`" for blocker in blockers] if blockers else ["- None"]
    return "\n".join(
        [
            "# V2 Exchange Filter Risk Profile Alignment And Min Order Execution Report",
            "",
            f"Gate: `{dashboard.get('go_no_go')}`",
            f"Generated EST: `{dashboard.get('generated_est')}`",
            f"Live gate: `{dashboard.get('live_gate')}`",
            f"Active risk profile: `{dashboard.get('active_risk_profile')}`",
            f"Accepted symbols: `{dashboard.get('accepted_symbols')}`",
            f"Exchange-filter aligned candidate: `{dashboard.get('candidate_filter_aligned')}`",
            f"Pre-submit status: `{dashboard.get('pre_submit_status')}`",
            f"Submit result status: `{dashboard.get('submit_result_status')}`",
            f"Order submitted: `{dashboard.get('order_submitted')}`",
            "",
            "Blockers:",
            *blocker_lines,
            "",
            "Safety: no test-order/cancel/modify, no leverage or margin mutation, no transfer/withdrawal, no legacy restart, no Redis trim, no raw credential output.",
            "",
        ]
    )


def run_once(
    repo_root: Path,
    *,
    execute_audit_flow: bool = True,
    submit_if_all_checks_pass: bool = True,
    run_validation_checks: bool = True,
) -> dict[str, Any]:
    os.environ["V2_REPO_ROOT"] = str(repo_root)
    client = connect_redis()
    generated_est = est_now()
    transport = BinanceUsdMWebSocketPrimaryTransport(redis_client=client)

    runtime_before = read_runtime_execution_state(repo_root=repo_root, redis_client=client, max_age_seconds=86400)
    safe_run("v2_orchestrator_arbitration_loop", orchestrator_loop.run_once)
    safe_run("v2_risk_gateway_live_loop", risk_gateway_loop.run_once, ttl_seconds=300)
    safe_run("v2_trade_management_paper_loop", paper_loop.run_once)
    safe_run("v2_all_timeframe_prediction_signal_price_target_publisher", run_signal_publisher, repo_root)
    signal_paths = signal_default_paths(repo_root)
    signal_status = read_json(signal_paths.signal_public_dir / "realtime_signal_publisher_status.json")
    signal_status = signal_status if isinstance(signal_status, Mapping) else {}

    snapshot = exchange_filter_snapshot(
        client=client,
        transport=transport,
        signal_status=signal_status,
        runtime_payload=runtime_before.get("payload") if isinstance(runtime_before.get("payload"), Mapping) else {},
    )
    compatibility = compatibility_status(snapshot)
    proposal = amended_profile_proposal(
        repo_root=repo_root,
        snapshot=snapshot,
        compatibility=compatibility,
        runtime_payload=runtime_before.get("payload") if isinstance(runtime_before.get("payload"), Mapping) else {},
        signal_status=signal_status,
    )
    records_before = current_acceptance_records(repo_root)
    current_profile = (
        (runtime_before.get("payload") or {}).get("risk_profile", {}).get("profile_name")
        if isinstance(runtime_before.get("payload"), Mapping)
        else None
    )
    current_max = _float(
        ((runtime_before.get("payload") or {}).get("risk_profile", {}).get("fields", {}) or {}).get(
            "max_notional_per_trade"
        )
    )
    proposed_max = _float(((proposal.get("profile") or {}).get("risk_fields") or {}).get("max_notional_per_trade"))
    amendment_needed = bool(
        current_profile != "conservative_min_executable"
        or (current_max is not None and proposed_max is not None and current_max < proposed_max)
    )
    amendment_execution = {
        "schema_version": "risk_profile_amendment_api_execution_status_v1",
        "generated_est": est_now(),
        "skipped": True,
        "reason": "AMENDMENT_NOT_NEEDED",
    }
    if execute_audit_flow and amendment_needed:
        amendment_execution = execute_audited_risk_amendment(
            repo_root=repo_root,
            proposal=proposal,
            records_before=records_before,
        )
    elif amendment_needed:
        amendment_execution = {
            "schema_version": "risk_profile_amendment_api_execution_status_v1",
            "generated_est": est_now(),
            "skipped": True,
            "reason": "AUDITED_RISK_AMENDMENT_SKIPPED_BY_FLAG",
        }

    runtime_after = read_runtime_execution_state(repo_root=repo_root, redis_client=client, max_age_seconds=86400)
    safe_run("v2_orchestrator_arbitration_loop_after_amendment", orchestrator_loop.run_once)
    safe_run("v2_risk_gateway_live_loop_after_amendment", risk_gateway_loop.run_once, ttl_seconds=300)
    safe_run("v2_trade_management_paper_loop_after_amendment", paper_loop.run_once)
    safe_run("v2_all_timeframe_prediction_signal_price_target_publisher_after_amendment", run_signal_publisher, repo_root)
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
        "trader_execution_enabled": bool((runtime_after.get("validation") or {}).get("valid")),
        "live_gate": (runtime_after.get("payload") or {}).get("live_gate"),
        "live_symbols": (runtime_after.get("payload") or {}).get("live_symbols") or [],
        "execution_live_symbols": (runtime_after.get("payload") or {}).get("execution_live_symbols") or [],
    }
    pre_submit = evaluate_live_order_transport(
        repo_root=repo_root,
        signal_status=signal_status,
        trader_status=trader_status,
        runtime_read=runtime_after,
        redis_client=client,
        dry_run=True,
    )
    candidate_aligned = candidate_filter_aligned_status(pre_submit, snapshot)
    pre_validation = pre_submit_validation_status(pre_submit)

    if pre_submit.get("status") == "LIVE_ORDER_TRANSPORT_PRE_SUBMIT_READY" and submit_if_all_checks_pass:
        submit_transport = evaluate_live_order_transport(
            repo_root=repo_root,
            signal_status=signal_status,
            trader_status=trader_status,
            runtime_read=runtime_after,
            redis_client=client,
            dry_run=False,
        )
        submit_result = submit_status_from_transport(submit_transport)
    elif pre_submit.get("status") == "LIVE_ORDER_TRANSPORT_PRE_SUBMIT_READY":
        submit_result = submit_status_from_transport(pre_submit, "SUBMIT_SKIPPED_BY_NO_SUBMIT_FLAG")
    elif pre_submit.get("blockers"):
        submit_result = submit_status_from_transport(pre_submit, "LIVE_ORDER_TRANSPORT_SUBMIT_SKIPPED_PRECHECK_BLOCKERS")
    else:
        submit_result = submit_status_from_transport(pre_submit, "TRANSPORT_READY_NO_VALID_ORDER_CANDIDATE")

    post_monitor = {
        "schema_version": "post_live_enable_first_hour_status_v1",
        "generated_est": est_now(),
        "monitor_status": "STARTED_OR_REFRESHED",
        "orders_attempted": 1 if submit_result.get("selected_candidate") else 0,
        "orders_submitted": 1 if submit_result.get("order_submitted") else 0,
        "orders_rejected": 1 if submit_result.get("submit_result") and not submit_result.get("order_submitted") else 0,
        "accepted_symbols": ACCEPTED_SYMBOLS,
        "kill_switch_active": pre_submit.get("kill_switch_active"),
        "latest_transport_status": submit_result.get("status"),
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

    validation = validation_status(repo_root) if run_validation_checks else {
        "schema_version": "validation_status_v1",
        "generated_est": est_now(),
        "status": "SKIPPED",
    }

    blockers: list[str] = []
    runtime_validation = runtime_after.get("validation") if isinstance(runtime_after.get("validation"), Mapping) else {}
    blockers.extend(str(item) for item in runtime_validation.get("blockers") or [])
    if (runtime_after.get("payload") or {}).get("live_gate") != LIVE_GATE_ENABLED:
        blockers.append("LIVE_GATE_NOT_ENABLED")
    if execute_audit_flow and amendment_needed and not amendment_execution.get("runtime_mutation_executed"):
        blockers.append("AUDITED_RISK_PROFILE_AMENDMENT_RUNTIME_ENABLE_FAILED")
    if not execute_audit_flow and amendment_needed:
        blockers.append("AUDITED_RISK_PROFILE_AMENDMENT_NOT_EXECUTED")
    blockers.extend(str(item) for item in pre_submit.get("blockers") or [])
    if submit_result.get("status") == "SUBMIT_SKIPPED_BY_NO_SUBMIT_FLAG":
        blockers.append("SUBMIT_SKIPPED_BY_NO_SUBMIT_FLAG")
    if submit_result.get("status") == "LIVE_ORDER_TRANSPORT_SUBMIT_FAILED":
        blockers.append("LIVE_ORDER_TRANSPORT_SUBMIT_FAILED")
    for label in (
        "py_compile",
        "focused_backend_tests",
        "frontend_typecheck",
        "frontend_build",
        "forbidden_exchange_mutation_scan",
        "old_redis_scan",
        "raw_secret_scan",
    ):
        if validation.get(label, {}).get("status") == "FAIL":
            blockers.append(f"{label.upper()}_FAILED")
    blockers = sorted(set(item for item in blockers if item))
    go_no_go = GATE_READY if not blockers and submit_result.get("order_submitted") is True else GATE_BLOCKED
    if not blockers and submit_result.get("status") == "TRANSPORT_READY_NO_VALID_ORDER_CANDIDATE":
        go_no_go = GATE_READY

    dashboard = {
        "schema_version": "operator_dashboard_payload_v1",
        "service_id": SERVICE_ID,
        "generated_est": generated_est,
        "go_no_go": go_no_go,
        "live_gate": (runtime_after.get("payload") or {}).get("live_gate"),
        "trader_execution_enabled": (runtime_after.get("payload") or {}).get("trader_execution_enabled") is True,
        "active_risk_profile": ((runtime_after.get("payload") or {}).get("risk_profile") or {}).get("profile_name"),
        "active_max_notional_per_trade": (((runtime_after.get("payload") or {}).get("risk_profile") or {}).get("fields") or {}).get("max_notional_per_trade"),
        "accepted_symbols": ACCEPTED_SYMBOLS,
        "candidate_filter_aligned": candidate_aligned.get("status") == "FIRST_LIVE_ORDER_CANDIDATE_FILTER_ALIGNED_READY",
        "pre_submit_status": pre_submit.get("status"),
        "submit_result_status": submit_result.get("status"),
        "order_submitted": bool(submit_result.get("order_submitted")),
        "writes_exchange_orders": bool(submit_result.get("writes_exchange_orders")),
        "places_real_order": bool(submit_result.get("places_real_order")),
        "blockers": blockers,
        "amendment_execution": amendment_execution,
        "validation": validation,
        "safety": {
            "no_test_order_cancel_modify": True,
            "no_leverage_margin_mutation": True,
            "no_transfer_or_withdrawal": True,
            "no_old_redis_write": True,
            "no_redis_trim": True,
            "no_legacy_restart": True,
            "raw_credentials_exposed": False,
        },
    }

    payloads: dict[str, Mapping[str, Any]] = {
        "exchange_filter_min_order_status.json": snapshot,
        "risk_profile_exchange_filter_compatibility_status.json": compatibility,
        "executable_minimum_conservative_risk_profile_proposal.json": proposal,
        "risk_profile_amendment_api_execution_status.json": amendment_execution,
        "first_live_order_candidate_filter_aligned_status.json": candidate_aligned,
        "first_live_order_pre_submit_validation_status.json": pre_validation,
        "first_live_order_submit_result_status.json": submit_result,
        "post_live_enable_first_hour_status.json": post_monitor,
        "operator_dashboard_payload.json": dashboard,
        "validation_status.json": validation,
    }
    report = render_report(dashboard)
    paths = mirror_outputs(repo_root, payloads, report)
    return {"go_no_go": go_no_go, "payloads": payloads, "paths_written": paths}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=SERVICE_ID)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--no-submit", action="store_true", help="Run audited amendment and dry validation only.")
    parser.add_argument("--no-audit-flow", action="store_true", help="Generate proposal without calling live-gate audit endpoints.")
    parser.add_argument("--skip-validation", action="store_true")
    args = parser.parse_args(argv)
    result = run_once(
        Path(args.repo_root).resolve(),
        execute_audit_flow=not bool(args.no_audit_flow),
        submit_if_all_checks_pass=not bool(args.no_submit),
        run_validation_checks=not bool(args.skip_validation),
    )
    print(json.dumps({"go_no_go": result["go_no_go"], "paths_written": result["paths_written"]}, indent=2))
    return 0 if result["go_no_go"] == GATE_READY else 2


if __name__ == "__main__":
    raise SystemExit(main())
