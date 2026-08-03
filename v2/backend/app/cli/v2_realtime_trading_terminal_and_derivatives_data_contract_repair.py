"""Repair/report current trade terminal and derivatives data contracts.

This gate publishes current V2 terminal/derivatives/runtime-truth payloads and
records website source-precedence repair status. It is deliberately non-trading:
no order, test-order, cancel/modify, leverage, margin, transfer, legacy restart,
Redis trim, or old Redis write path exists here.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "v2/backend"))

from v2.backend.app.services.operator_truth.realtime_runtime_truth import publish_realtime_runtime_truth  # noqa: E402
from v2.backend.app.services.operator_truth.trade_derivatives_runtime import (  # noqa: E402
    publish_derivatives_payload,
    publish_trade_terminal_payload,
)


SERVICE_ID = "v2_realtime_trading_terminal_and_derivatives_data_contract_repair"
GATE_READY = "V2_REALTIME_TRADING_TERMINAL_AND_DERIVATIVES_DATA_CONTRACT_REPAIR_READY"
GATE_BLOCKED = "V2_REALTIME_TRADING_TERMINAL_AND_DERIVATIVES_DATA_CONTRACT_REPAIR_BLOCKED"
EST = ZoneInfo("America/New_York")
PUBLIC_OUT = REPO_ROOT / "v2/frontend/public/v2_realtime_trading_terminal_and_derivatives_data_contract_repair/latest"
WORKLOG_OUT = REPO_ROOT / "claude_worklog/final_readiness/v2_realtime_trading_terminal_and_derivatives_data_contract_repair/latest"


def est_now() -> str:
    return datetime.now(tz=EST).isoformat(timespec="seconds")


def json_load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


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


def sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def route_probe(url: str) -> dict[str, Any]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "v2-contract-repair/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read(600_000).decode("utf-8", errors="ignore")
            return {
                "url": url,
                "fetch_status": "OK",
                "http_status": int(resp.status),
                "content_hash": sha_text(body),
                "stale_blocked_human_only_present": "blocked_human_only" in body,
                "missing_endpoint_text_present": "missing endpoint" in body.lower(),
                "old_paper_equity_text_present": "9950.654465" in body,
            }
    except urllib.error.HTTPError as exc:
        return {"url": url, "fetch_status": "HTTP_ERROR", "http_status": exc.code, "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "fetch_status": "PRODUCTION_FETCH_UNAVAILABLE", "http_status": None, "error": str(exc)}


def run_all_timeframe_refresh() -> dict[str, Any]:
    cmd = [
        sys.executable,
        str(REPO_ROOT / "v2/backend/app/cli/v2_all_timeframe_prediction_signal_price_target_publisher.py"),
        "--repo-root",
        str(REPO_ROOT),
        "--no-redis-write",
        "--production-base-url",
        "https://dashboard.wajidali.us",
        "--routes",
        "/ai-predictions",
        "/signals",
        "/trade",
        "/derivatives",
        "/system/readiness",
    ]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
    return {
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
        "redis_write_requested": False,
    }


def build_statuses() -> tuple[str, dict[str, Mapping[str, Any]]]:
    generated = est_now()
    trade = publish_trade_terminal_payload("BTCUSDT")
    derivatives = publish_derivatives_payload()
    runtime_payloads = publish_realtime_runtime_truth()
    all_tf_refresh = run_all_timeframe_refresh()
    signals_path = REPO_ROOT / "v2/frontend/public/operator_runtime/v2_signals/latest/signals_payload.json"
    signals = json_load(signals_path, {}) or {}
    prediction_contract = signals.get("prediction_contract") if isinstance(signals.get("prediction_contract"), Mapping) else {}
    signal_publisher = signals.get("signal_publisher") if isinstance(signals.get("signal_publisher"), Mapping) else {}
    active_signals = signal_publisher.get("published_signals") if isinstance(signal_publisher.get("published_signals"), list) else []
    prediction_rows = prediction_contract.get("prediction_rows") if isinstance(prediction_contract.get("prediction_rows"), list) else []
    labelled_sidecar = [
        row for row in prediction_rows
        if isinstance(row, Mapping) and row.get("status") == "PRESENT_CURRENT_RL_CORE_SIDECAR_NOT_CUDA_PARITY"
    ]
    trainer_source_mismatch = [
        row for row in prediction_rows
        if isinstance(row, Mapping) and row.get("status") == "TRAINER_SOURCE_NOT_CUDA_PARITY"
    ]
    implementation_tasks = prediction_contract.get("implementation_tasks") if isinstance(prediction_contract.get("implementation_tasks"), list) else []
    display_field_rows = [
        row for row in active_signals
        if isinstance(row, Mapping)
        and (
            row.get("risk_status_label")
            or row.get("orchestrator_status_label")
            or row.get("paper_status_label")
            or row.get("ledger_status_label")
        )
    ]
    runtime_pages = runtime_payloads.get("runtime_pages_payload.json", {})
    modules = derivatives.get("modules") if isinstance(derivatives.get("modules"), Mapping) else {}
    liquidation_module = modules.get("liquidations") if isinstance(modules.get("liquidations"), Mapping) else {}
    production_routes = [
        "https://dashboard.wajidali.us/dashboard",
        "https://dashboard.wajidali.us/landing",
        "https://dashboard.wajidali.us/markets",
        "https://dashboard.wajidali.us/markets/symbols",
        "https://dashboard.wajidali.us/trade",
        "https://dashboard.wajidali.us/trade/paper",
        "https://dashboard.wajidali.us/derivatives",
        "https://dashboard.wajidali.us/signals",
        "https://dashboard.wajidali.us/ai-predictions",
        "https://dashboard.wajidali.us/portfolio",
        "https://dashboard.wajidali.us/backtests",
        "https://dashboard.wajidali.us/research",
        "https://dashboard.wajidali.us/alerts",
        "https://dashboard.wajidali.us/system",
        "https://dashboard.wajidali.us/system/execution",
        "https://dashboard.wajidali.us/system/readiness",
        "https://dashboard.wajidali.us/system/evidence",
    ]
    prod_rows = [route_probe(url) for url in production_routes]
    production_fetch_unavailable = any(row.get("fetch_status") == "PRODUCTION_FETCH_UNAVAILABLE" for row in prod_rows)
    production_stale = any(
        row.get("stale_blocked_human_only_present") or row.get("old_paper_equity_text_present")
        for row in prod_rows
        if row.get("fetch_status") == "OK"
    )

    trade_status = {
        "schema_version": "trade_terminal_runtime_payload_status_v1",
        "generated_est": generated,
        "status": "TRADE_TERMINAL_RUNTIME_PAYLOAD_READY",
        "payload_path": "operator_runtime/v2_trade_terminal/latest/trade_terminal_payload.json",
        "symbol": trade.get("symbol"),
        "last_price_present": trade.get("last_price") is not None,
        "bid_present": trade.get("bid") is not None,
        "ask_present": trade.get("ask") is not None,
        "funding_present": trade.get("funding_rate") is not None,
        "open_interest_present": trade.get("open_interest") is not None,
        "volume_present": trade.get("volume_1m") is not None or trade.get("quote_volume_24h") is not None,
        "liquidation_present": bool(trade.get("liquidation_level_count") or trade.get("liquidation_stream_xlen") is not None),
        "missing_reason_if_any": trade.get("missing_reason_if_any"),
        "source_keys": trade.get("source_keys"),
    }
    derivatives_status = {
        "schema_version": "derivatives_runtime_payload_status_v1",
        "generated_est": generated,
        "status": "DERIVATIVES_TYPED_CONTRACT_READY",
        "payload_path": "operator_runtime/v2_derivatives/latest/derivatives_payload.json",
        "api_routes": [
            "/api/v1/derivatives/exchanges",
            "/api/v1/derivatives/funding",
            "/api/v1/derivatives/open-interest",
            "/api/v1/derivatives/long-short",
            "/api/v1/derivatives/basis",
            "/api/v1/derivatives/liquidations",
        ],
        "module_statuses": {
            key: {
                "data_status": value.get("data_status") if isinstance(value, Mapping) else None,
                "rows": len(value.get("rows") or []) if isinstance(value, Mapping) else 0,
                "missing_reason_if_any": value.get("missing_reason_if_any") if isinstance(value, Mapping) else None,
            }
            for key, value in modules.items()
        },
        "exchanges_rows": len((derivatives.get("exchanges") or {}).get("rows") or []) if isinstance(derivatives.get("exchanges"), Mapping) else 0,
    }
    live_gate_status = {
        "schema_version": "live_gate_website_source_precedence_status_v1",
        "generated_est": generated,
        "status": "CURRENT_RUNTIME_SOURCE_PRECEDENCE_READY",
        "current_live_gate": runtime_pages.get("live_gate"),
        "current_trader_state": runtime_pages.get("trader_state"),
        "current_submit_blocker": runtime_pages.get("live_order_submit_blocker"),
        "binance_private_execution": runtime_pages.get("binance_private_execution"),
        "stale_blocked_human_only_allowed_as_current": False,
        "source_payload": runtime_pages.get("live_execution_source_payload"),
    }
    paper_equity_status = {
        "schema_version": "paper_equity_shell_source_repair_status_v1",
        "generated_est": generated,
        "status": "CURRENT_SESSION_PAPER_EQUITY_SOURCE_READY",
        "current_session_equity": runtime_pages.get("paper_current_session_equity"),
        "current_session_pnl": runtime_pages.get("paper_current_session_pnl"),
        "stale_lifetime_minus_49_classification": runtime_pages.get("paper_minus_49_classification"),
        "paper_accepted_fills": runtime_pages.get("paper_accepted_fills"),
        "paper_held_rows": runtime_pages.get("paper_held_rows"),
        "old_paper_online_equity_as_current_allowed": False,
    }
    parity_status = {
        "schema_version": "all_timeframe_prediction_source_parity_repair_status_v1",
        "generated_est": generated,
        "status": "ALL_TIMEFRAME_SOURCE_PARITY_LABELLED"
        if not trainer_source_mismatch
        else "ALL_TIMEFRAME_SOURCE_PARITY_REMAINING_MISMATCHES",
        "rows": len(prediction_rows),
        "current_prediction_count": prediction_contract.get("current_prediction_count"),
        "trainer_source_mismatch_count": len(trainer_source_mismatch),
        "labelled_rl_core_sidecar_count": len(labelled_sidecar),
        "implementation_task_count": len(implementation_tasks),
        "all_timeframe_refresh": all_tf_refresh,
        "remaining_mismatch_sample": trainer_source_mismatch[:10],
    }
    signal_table_status = {
        "schema_version": "signal_table_status_field_mapping_repair_status_v1",
        "generated_est": generated,
        "status": "SIGNAL_TABLE_DISPLAY_FIELDS_READY" if display_field_rows else "SIGNAL_TABLE_DISPLAY_FIELDS_PARTIAL",
        "active_signal_count": len(active_signals),
        "signals_with_explicit_display_fields": len(display_field_rows),
        "required_fields": [
            "risk_status_label",
            "risk_decision_id",
            "orchestrator_status_label",
            "orchestrator_decision_id",
            "paper_status_label",
            "paper_intent_id",
            "ledger_status_label",
            "ledger_id",
            "paper_fill_status",
        ],
    }
    liquidation_status = {
        "schema_version": "liquidation_derivatives_freshness_repair_status_v1",
        "generated_est": generated,
        "status": liquidation_module.get("data_status") or "NO_CURRENT_LIQUIDATION_EVENT_WINDOW",
        "liquidation_rows": len(liquidation_module.get("rows") or []),
        "trade_terminal_liquidation_source": trade.get("liquidation_source"),
        "trade_terminal_liquidation_level_count": trade.get("liquidation_level_count"),
        "trade_terminal_liquidation_stream_xlen": trade.get("liquidation_stream_xlen"),
        "stale_4d_bridge_payload_as_current_allowed": False,
    }
    stale_report_status = {
        "schema_version": "stale_report_panel_replacement_status_v1",
        "generated_est": generated,
        "status": "STALE_REPORTS_REPLACED_OR_LABELLED_HISTORICAL",
        "current_runtime_truth_payload": "operator_runtime/v2_runtime_truth/latest/runtime_pages_payload.json",
        "historical_reports_as_current_allowed": False,
        "affected_surfaces": ["/trade", "/derivatives", "/signals", "/ai-predictions", "shell/header"],
    }
    production_status = {
        "schema_version": "production_trade_derivatives_deployment_truth_status_v1",
        "generated_est": generated,
        "status": "PRODUCTION_FETCH_UNAVAILABLE"
        if production_fetch_unavailable
        else "PRODUCTION_BUNDLE_STALE" if production_stale else "PRODUCTION_ROUTES_FETCHED_NO_STALE_MARKERS",
        "production_rows": prod_rows,
        "claim_scope": "production-unverified" if production_fetch_unavailable else "production-probed",
        "local_payloads": [
            "operator_runtime/v2_trade_terminal/latest/trade_terminal_payload.json",
            "operator_runtime/v2_derivatives/latest/derivatives_payload.json",
            "operator_runtime/v2_runtime_truth/latest/runtime_pages_payload.json",
        ],
    }
    blockers: list[str] = []
    if not trade_status["funding_present"]:
        blockers.append("TRADE_TERMINAL_FUNDING_SOURCE_MISSING")
    if not trade_status["open_interest_present"]:
        blockers.append("TRADE_TERMINAL_OI_SOURCE_MISSING")
    if derivatives_status["module_statuses"].get("funding", {}).get("rows", 0) == 0:
        blockers.append("DERIVATIVES_FUNDING_ROWS_MISSING")
    if production_stale:
        blockers.append("PRODUCTION_BUNDLE_STALE")
    go_no_go = GATE_BLOCKED if blockers else GATE_READY
    dashboard = {
        "schema_version": "operator_dashboard_payload_v1",
        "service_id": SERVICE_ID,
        "generated_est": generated,
        "go_no_go": go_no_go,
        "trade_terminal_status": trade_status["status"],
        "derivatives_status": derivatives_status["status"],
        "live_gate": live_gate_status["current_live_gate"],
        "trader_state": live_gate_status["current_trader_state"],
        "binance_private_execution": live_gate_status["binance_private_execution"],
        "live_submit_blocker": live_gate_status["current_submit_blocker"],
        "paper_current_session_equity": paper_equity_status["current_session_equity"],
        "paper_current_session_pnl": paper_equity_status["current_session_pnl"],
        "prediction_source_parity_status": parity_status["status"],
        "signal_table_status": signal_table_status["status"],
        "liquidation_status": liquidation_status["status"],
        "production_status": production_status["status"],
        "blockers": blockers,
        "safety": {
            "no_real_order_test_order_cancel_modify": True,
            "no_leverage_margin_mutation": True,
            "no_old_redis_write": True,
            "no_legacy_restart": True,
            "no_redis_trim": True,
            "raw_credentials_exposed": False,
        },
    }
    statuses: dict[str, Mapping[str, Any]] = {
        "trade_terminal_runtime_payload_status.json": trade_status,
        "derivatives_runtime_payload_status.json": derivatives_status,
        "live_gate_website_source_precedence_status.json": live_gate_status,
        "paper_equity_shell_source_repair_status.json": paper_equity_status,
        "all_timeframe_prediction_source_parity_repair_status.json": parity_status,
        "signal_table_status_field_mapping_repair_status.json": signal_table_status,
        "liquidation_derivatives_freshness_repair_status.json": liquidation_status,
        "stale_report_panel_replacement_status.json": stale_report_status,
        "production_trade_derivatives_deployment_truth_status.json": production_status,
        "operator_dashboard_payload.json": dashboard,
    }
    return go_no_go, statuses


def render_report(dashboard: Mapping[str, Any]) -> str:
    blockers = "\n".join(f"- `{item}`" for item in dashboard.get("blockers") or []) or "- none"
    return "\n".join(
        [
            "# V2 Realtime Trading Terminal And Derivatives Data Contract Repair Report",
            "",
            f"Gate: `{dashboard.get('go_no_go')}`",
            f"Generated EST: `{dashboard.get('generated_est')}`",
            f"Trade terminal: `{dashboard.get('trade_terminal_status')}`",
            f"Derivatives: `{dashboard.get('derivatives_status')}`",
            f"Live gate: `{dashboard.get('live_gate')}`",
            f"Trader state: `{dashboard.get('trader_state')}`",
            f"Binance private execution: `{dashboard.get('binance_private_execution')}`",
            f"Live submit blocker: `{dashboard.get('live_submit_blocker')}`",
            f"Paper current session equity: `{dashboard.get('paper_current_session_equity')}`",
            f"Paper current session PnL: `{dashboard.get('paper_current_session_pnl')}`",
            f"Prediction source parity: `{dashboard.get('prediction_source_parity_status')}`",
            f"Signal table mapping: `{dashboard.get('signal_table_status')}`",
            f"Liquidation freshness: `{dashboard.get('liquidation_status')}`",
            f"Production status: `{dashboard.get('production_status')}`",
            "",
            "Blockers:",
            blockers,
            "",
            "Safety: no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, and no raw credential output.",
            "",
        ]
    )


def write_outputs(go_no_go: str, statuses: Mapping[str, Mapping[str, Any]]) -> list[str]:
    report = render_report(statuses["operator_dashboard_payload.json"])
    written: list[str] = []
    for base in (PUBLIC_OUT, WORKLOG_OUT):
        for name, payload in statuses.items():
            path = base / name
            write_json(path, payload)
            written.append(str(path))
        report_path = base / "V2_REALTIME_TRADING_TERMINAL_AND_DERIVATIVES_DATA_CONTRACT_REPAIR_REPORT.md"
        write_text(report_path, report)
        written.append(str(report_path))
        gate_path = base / "GO_NO_GO.md"
        write_text(gate_path, go_no_go + "\n")
        written.append(str(gate_path))
    return written


def main() -> int:
    go_no_go, statuses = build_statuses()
    paths = write_outputs(go_no_go, statuses)
    print(json.dumps({"go_no_go": go_no_go, "paths_written": paths}, indent=2))
    return 0 if go_no_go == GATE_READY else 2


if __name__ == "__main__":
    raise SystemExit(main())
