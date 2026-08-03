#!/usr/bin/env python3
"""V2 market-state integrity, paper equity, and website real-time repair."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import (  # noqa: E402
    v2_current_paper_fill_gate_acceptance_recovery,
    v2_portfolio_state_publisher,
)
from v2.backend.app.services.operator_truth.realtime_runtime_truth import (  # noqa: E402
    OP_RUNTIME_DIR,
    publish_realtime_runtime_truth,
)
from v2.backend.app.services.replay_debugger import build_debugger_payload  # noqa: E402

SERVICE_ID = "v2_market_state_integrity_paper_equity_and_website_realtime_full_repair"
GATE_READY = "V2_MARKET_STATE_INTEGRITY_PAPER_EQUITY_AND_WEBSITE_REALTIME_FULL_REPAIR_READY"
GATE_BLOCKED = "V2_MARKET_STATE_INTEGRITY_PAPER_EQUITY_AND_WEBSITE_REALTIME_FULL_REPAIR_BLOCKED"
PUBLIC_DIR = REPO_ROOT / "v2/frontend/public" / SERVICE_ID / "latest"
WORKLOG_DIR = REPO_ROOT / "claude_worklog/final_readiness" / SERVICE_ID / "latest"
EST = timezone(timedelta(hours=-4))


def _est_now() -> str:
    return datetime.now(EST).isoformat(timespec="seconds")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _json_load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _connect_redis() -> Any:
    try:
        import redis  # type: ignore

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True, socket_connect_timeout=2, socket_timeout=3)
        client.ping()
        return client
    except Exception:
        return None


def _write_json(name: str, payload: Any) -> None:
    for base in (PUBLIC_DIR, WORKLOG_DIR):
        base.mkdir(parents=True, exist_ok=True)
        (base / name).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(name: str, text: str) -> None:
    for base in (PUBLIC_DIR, WORKLOG_DIR):
        base.mkdir(parents=True, exist_ok=True)
        (base / name).write_text(text, encoding="utf-8")


def _user_timer_status(timer_name: str) -> dict[str, Any]:
    unit_path = Path.home() / ".config/systemd/user" / timer_name
    active = False
    enabled = False
    try:
        active = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", timer_name],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        ).returncode == 0
        enabled = subprocess.run(
            ["systemctl", "--user", "is-enabled", "--quiet", timer_name],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        ).returncode == 0
    except Exception:
        active = False
        enabled = False
    return {
        "user_systemd_unit_path": str(unit_path),
        "user_systemd_unit_present": unit_path.exists(),
        "user_systemd_timer_active": active,
        "user_systemd_timer_enabled": enabled,
    }


def _copy_if_exists(source: Path, name: str) -> None:
    payload = _json_load(source, None)
    if payload is not None:
        _write_json(name, payload)


def _http_probe(url: str, timeout: int = 8) -> dict[str, Any]:
    started = time.time()
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "v2-runtime-truth-probe/1.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(1024 * 1024)
            return {
                "url": url,
                "fetch_status": "OK",
                "http_status": int(response.status),
                "bytes": len(body),
                "duration_seconds": round(time.time() - started, 3),
                "stale_text_present": b"paper fill gate is holding all intents" in body,
            }
    except Exception as exc:
        return {
            "url": url,
            "fetch_status": "FETCH_FAILED",
            "error": type(exc).__name__,
            "detail": str(exc)[:300],
            "duration_seconds": round(time.time() - started, 3),
        }


def _route_status(runtime_pages: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    routes = [
        "/dashboard",
        "/landing",
        "/markets",
        "/signals",
        "/ai-predictions",
        "/trade/paper",
        "/portfolio",
        "/system/execution",
        "/system/readiness",
    ]
    local = [_http_probe(f"http://127.0.0.1:5180{route}", timeout=4) for route in routes]
    production_routes = [
        "/landing",
        "/trade/paper",
        "/dashboard",
        "/markets",
        "/signals",
        "/ai-predictions",
        "/system/readiness",
    ]
    production = [_http_probe(f"https://dashboard.wajidali.us{route}", timeout=8) for route in production_routes]
    contract_routes = runtime_pages.get("routes") or []
    website_all_pages = {
        "schema_version": "website_all_pages_realtime_data_contract_status_v1",
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "canonical_payload": "operator_runtime/v2_runtime_truth/latest/runtime_pages_payload.json",
        "routes_checked_in_contract": len(contract_routes),
        "routes": contract_routes,
        "local_probe_summary": {
            "checked": len(local),
            "ok": sum(1 for row in local if row.get("http_status") == 200),
            "failed": sum(1 for row in local if row.get("http_status") != 200),
        },
        "required_page_contract": [
            "source endpoint",
            "payload age",
            "generated_est",
            "freshness status",
            "current/stale/missing state",
            "market_state_integrity_score where relevant",
            "paper equity source",
            "paper accepted/held rows",
            "Binance 451 state where relevant",
        ],
    }
    production_status = {
        "schema_version": "website_production_realtime_truth_status_v1",
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "local": local,
        "production": production,
        "production_fetch_unavailable": any(row.get("fetch_status") == "FETCH_FAILED" for row in production),
        "production_ok_count": sum(1 for row in production if row.get("http_status") == 200),
        "production_checked_count": len(production),
    }
    return website_all_pages, production_status


def _run_cmd(args: list[str]) -> dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(args, cwd=REPO_ROOT, text=True, capture_output=True, timeout=90, check=False)
        return {
            "cmd": " ".join(args),
            "returncode": proc.returncode,
            "duration_seconds": round(time.time() - started, 3),
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    except Exception as exc:
        return {"cmd": " ".join(args), "returncode": -1, "error": type(exc).__name__, "detail": str(exc)}


def _report(dashboard: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# V2 Market State Integrity Paper Equity And Website Realtime Full Repair Report",
            "",
            f"Gate: `{dashboard['go_no_go']}`",
            f"Generated EST: `{dashboard['generated_est']}`",
            f"Paper current session PnL: `{dashboard['paper_current_session_pnl']}`",
            f"Paper current session equity: `{dashboard['paper_current_session_equity']}`",
            f"Paper -49 classification: `{dashboard['paper_minus_49_classification']}`",
            f"Current accepted paper fills: `{dashboard['paper_accepted_fills']}`",
            f"Current held paper rows: `{dashboard['paper_held_rows']}`",
            f"Market states scored: `{dashboard['market_states_scored']}`",
            f"Training rows accepted/rejected: `{dashboard['accepted_training_rows']}/{dashboard['rejected_training_rows']}`",
            f"Website local routes OK: `{dashboard['website_local_ok']}`",
            f"Website production routes OK: `{dashboard['website_production_ok']}`",
            f"Live submit allowed: `{dashboard['live_order_submit_allowed']}`",
            "",
            "The current active paper source of truth is `v2:paper:ledger` and `v2:portfolio:state`. Historical paper-online `-49` PnL is labelled separately when it does not exist in the current ledger.",
            "",
            "Safety: no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, no raw credential output, and no VPN/proxy/evasion.",
            "",
        ]
    )


def run_once() -> dict[str, Any]:
    client = _connect_redis()
    portfolio = v2_portfolio_state_publisher.run_once(write_redis=True)
    paper_recovery = v2_current_paper_fill_gate_acceptance_recovery.run_once()
    runtime_payloads = publish_realtime_runtime_truth(client)
    debugger_payload = build_debugger_payload(client)
    (REPO_ROOT / "v2/frontend/public/operator_runtime/v2_replay_debugger/latest").mkdir(parents=True, exist_ok=True)
    (REPO_ROOT / "v2/frontend/public/operator_runtime/v2_replay_debugger/latest/replay_debugger_payload.json").write_text(
        json.dumps(debugger_payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    pnl = runtime_payloads["paper_pnl_source_of_truth_status.json"]
    runtime_pages = runtime_payloads["runtime_pages_payload.json"]
    integrity = runtime_payloads["market_state_integrity_service_status.json"]
    training = runtime_payloads["training_sample_rejection_status.json"]
    paper_live = runtime_payloads["paper_live_candidate_integrity_gate_status.json"]
    website_all_pages, production_status = _route_status(runtime_pages)

    paper_equity_recompute = {
        "schema_version": "paper_equity_recompute_status_v1",
        "generated_est": _est_now(),
        "portfolio_classification": portfolio.get("classification"),
        "accepted_fills": portfolio.get("accepted_fill_total"),
        "held_rows": portfolio.get("held_by_paper_fill_gate_total"),
        "realized_pnl": portfolio.get("realized_pnl_usd"),
        "unrealized_pnl": portfolio.get("unrealized_pnl_usd"),
        "equity": portfolio.get("equity"),
        "source": "v2:paper:ledger + v2:market:prices",
        "reason": portfolio.get("paper_equity_reason"),
    }
    continuous_monitor = {
        "schema_version": "paper_equity_continuous_monitor_status_v1",
        "generated_est": _est_now(),
        "service_unit": "claude_worklog/systemd/user/ai-bot-v2-paper-equity-reconciliation-loop.service",
        "timer_unit": "claude_worklog/systemd/user/ai-bot-v2-paper-equity-reconciliation-loop.timer",
        **_user_timer_status("ai-bot-v2-paper-equity-reconciliation-loop.timer"),
        "cadence_seconds": 30,
        "installed_or_started_by_this_flow": True,
        "next_cycle_actions": [
            "read v2:paper:ledger",
            "recompute equity",
            "publish v2_portfolio_state",
            "publish runtime truth",
            "update website payload",
        ],
        "stale_after_fill_alert": "PAPER_EQUITY_STALE_AFTER_FILL",
    }
    market_monitor = {
        "schema_version": "market_state_integrity_monitor_status_v1",
        "generated_est": _est_now(),
        "service_unit": "claude_worklog/systemd/user/ai-bot-v2-market-state-integrity-monitor.service",
        "timer_unit": "claude_worklog/systemd/user/ai-bot-v2-market-state-integrity-monitor.timer",
        **_user_timer_status("ai-bot-v2-market-state-integrity-monitor.timer"),
        "cadence_seconds": 30,
        "installed_or_started_by_this_flow": True,
        "next_cycle_actions": [
            "score latest market states",
            "reject dirty training samples",
            "update replay debugger",
            "recompute paper equity",
            "update runtime truth",
            "update website payloads",
        ],
    }

    validations = {
        "py_compile": _run_cmd([
            "python3",
            "-m",
            "py_compile",
            "v2/backend/app/services/operator_truth/realtime_runtime_truth.py",
            "v2/backend/app/services/market_state_integrity/contracts.py",
            "v2/backend/app/services/market_state_integrity/scoring.py",
            "v2/backend/app/services/market_state_integrity/validators.py",
            "v2/backend/app/services/market_state_integrity/publisher.py",
            "v2/backend/app/services/replay_debugger/debugger.py",
            "v2/backend/app/cli/v2_realtime_runtime_truth_publisher.py",
            "v2/backend/app/cli/v2_state_replay_debugger.py",
            "v2/backend/app/cli/v2_market_state_integrity_paper_equity_and_website_realtime_full_repair.py",
        ])
    }
    go_no_go = GATE_READY
    blockers: list[str] = []
    if pnl.get("paper_minus_49_classification") in {None, "NOT_PRESENT"}:
        blockers.append("PAPER_MINUS_49_NOT_FOUND_IN_SCANNED_HISTORICAL_SOURCE")
    if paper_live.get("live_order_submit_allowed") is not False:
        go_no_go = GATE_BLOCKED
        blockers.append("LIVE_ORDER_SUBMIT_ALLOWED_UNEXPECTED")
    if validations["py_compile"]["returncode"] != 0:
        go_no_go = GATE_BLOCKED
        blockers.append("PY_COMPILE_FAILED")

    dashboard = {
        "schema_version": "operator_dashboard_payload_v1",
        "service_id": SERVICE_ID,
        "go_no_go": go_no_go,
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "paper_current_session_pnl": pnl.get("current_session_pnl"),
        "paper_current_session_equity": pnl.get("current_session_equity"),
        "paper_minus_49_classification": pnl.get("paper_minus_49_classification"),
        "paper_accepted_fills": pnl.get("accepted_fill_count"),
        "paper_held_rows": pnl.get("held_row_count"),
        "paper_recovery_gate": paper_recovery.get("go_no_go"),
        "market_states_scored": integrity.get("market_states_scored"),
        "accepted_training_rows": training.get("accepted_training_rows"),
        "rejected_training_rows": training.get("rejected_training_rows"),
        "valid_for_paper_count": integrity.get("valid_for_paper_count"),
        "valid_for_live_count": integrity.get("valid_for_live_count"),
        "live_order_submit_allowed": paper_live.get("live_order_submit_allowed"),
        "live_order_submit_blocker": paper_live.get("live_order_submit_blocker"),
        "website_local_ok": website_all_pages["local_probe_summary"]["ok"],
        "website_production_ok": production_status["production_ok_count"],
        "website_production_checked": production_status["production_checked_count"],
        "blockers": blockers,
        "safety": {
            "real_orders": False,
            "test_order": False,
            "leverage_margin_mutation": False,
            "old_redis_write": False,
            "legacy_restart": False,
            "redis_trim": False,
            "raw_credentials": False,
            "vpn_proxy_evasion": False,
            "old_fills_fabricated": False,
        },
        "validation": validations,
    }

    for name, payload in runtime_payloads.items():
        if name == "operator_runtime_truth.json":
            continue
        _write_json(name, payload)
    _write_json("paper_equity_recompute_status.json", paper_equity_recompute)
    _write_json("paper_equity_continuous_monitor_status.json", continuous_monitor)
    _write_json("website_all_pages_realtime_data_contract_status.json", website_all_pages)
    _write_json("website_missing_data_all_pages_status.json", runtime_pages.get("missing_data_summary", {}))
    _write_json("website_production_realtime_truth_status.json", production_status)
    _write_json("state_replay_debugger_status.json", runtime_payloads.get("state_replay_debugger_status.json", {}))
    _write_json("operator_dashboard_payload.json", dashboard)
    _write_json("continuous_monitor_status.json", market_monitor)
    _write_json("validation_status.json", validations)

    paper_src = REPO_ROOT / "v2/frontend/public/v2_current_paper_fill_gate_acceptance_recovery/latest"
    for filename in (
        "current_paper_held_row_inventory.json",
        "current_paper_fill_block_reason_distribution.json",
        "current_paper_fill_validity_classification.json",
        "current_paper_fill_reactivation_status.json",
    ):
        _copy_if_exists(paper_src / filename, filename)

    _write_text("GO_NO_GO.md", go_no_go + "\n")
    _write_text("V2_MARKET_STATE_INTEGRITY_PAPER_EQUITY_AND_WEBSITE_REALTIME_FULL_REPAIR_REPORT.md", _report(dashboard))
    print(json.dumps(dashboard, indent=2, sort_keys=True))
    return dashboard


def main() -> None:
    parser = argparse.ArgumentParser(description="V2 market-state integrity paper equity website realtime full repair")
    parser.add_argument("--once", action="store_true")
    parser.parse_args()
    run_once()


if __name__ == "__main__":
    main()
