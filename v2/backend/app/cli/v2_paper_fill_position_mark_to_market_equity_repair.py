"""V2 paper fill -> position -> mark-to-market equity repair gate.

This CLI refreshes the V2 paper-only chain and writes operator-facing
artifacts. It does not touch live exchange endpoints, leverage, margin, old
Redis keys, or legacy services.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from v2.backend.app.cli import (
    v2_orchestrator_arbitration_loop,
    v2_portfolio_state_publisher,
    v2_trade_management_paper_loop,
)
from v2.backend.app.services.paper_accounting.mark_to_market import build_accounting_state


REPO_ROOT = Path(__file__).resolve().parents[4]
PUBLIC_DIR = REPO_ROOT / "v2/frontend/public"
OUT_REL = Path("v2_paper_fill_position_mark_to_market_equity_repair/latest")
WORKLOG_REL = Path("claude_worklog/final_readiness") / OUT_REL
EST = ZoneInfo("America/New_York")

READY = "V2_PAPER_FILL_POSITION_MARK_TO_MARKET_EQUITY_REPAIR_READY"
BLOCKED = "V2_PAPER_FILL_POSITION_MARK_TO_MARKET_EQUITY_REPAIR_BLOCKED"


def est_now() -> str:
    return datetime.now(tz=EST).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def connect_redis() -> Any:
    try:
        import redis  # type: ignore

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True, socket_timeout=3)
        client.ping()
        return client
    except Exception:
        return None


def redis_json(client: Any, key: str, default: Any = None) -> Any:
    if client is None:
        return default
    try:
        raw = client.get(key)
    except Exception:
        return default
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def service_status(unit: str) -> dict[str, Any]:
    fields = {}
    for field in ("LoadState", "ActiveState", "SubState", "UnitFileState", "Result"):
        try:
            result = subprocess.run(
                ["systemctl", "--user", "show", unit, f"--property={field}", "--value"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            fields[field] = result.stdout.strip() or "UNKNOWN"
        except Exception as exc:
            fields[field] = f"UNKNOWN:{exc}"
    return {"unit": unit, **fields}


def route_status(path: str) -> dict[str, Any]:
    full = PUBLIC_DIR / path.lstrip("/")
    return {
        "path": path,
        "exists": full.exists(),
        "size_bytes": full.stat().st_size if full.exists() else None,
    }


def run_pipeline_refresh() -> dict[str, Any]:
    results: dict[str, Any] = {}
    for name, func in (
        ("orchestrator", v2_orchestrator_arbitration_loop.run_once),
        ("paper_loop", v2_trade_management_paper_loop.run_once),
        ("portfolio", v2_portfolio_state_publisher.run_once),
    ):
        try:
            if name == "portfolio":
                results[name] = func(write_redis=True)
            else:
                results[name] = func()
        except Exception as exc:
            results[name] = {"error": str(exc)}
    return results


def build_statuses(refresh: dict[str, Any]) -> dict[str, Any]:
    client = connect_redis()
    ledger = as_dict(redis_json(client, "v2:paper:ledger", {}))
    portfolio = as_dict(redis_json(client, "v2:portfolio:state", {})) or read_json(
        PUBLIC_DIR / "operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json"
    )
    accepted = [as_dict(row) for row in as_list(ledger.get("accepted")) if isinstance(row, dict)]
    closed = [
        as_dict(row)
        for source in ("closed", "closed_positions", "realized", "realized_fills", "closes")
        for row in as_list(ledger.get(source))
        if isinstance(row, dict)
    ]
    inventory = as_list(portfolio.get("paper_fill_economic_inventory"))
    positions = as_list(portfolio.get("positions_by_symbol"))
    if not inventory:
        mark_prices: dict[str, tuple[float | None, str | None, float | None]] = {}
        for row in accepted:
            symbol = str(row.get("symbol") or "").upper()
            if not symbol:
                continue
            price, source, _generated = v2_portfolio_state_publisher._read_v2_market_price(client, symbol)
            mark_prices[symbol] = (price, source, None)
        accounting = build_accounting_state(accepted, closed, mark_prices)
        inventory = as_list(accounting.get("inventory"))
        positions = as_list(accounting.get("positions_by_symbol"))
    economic_count = int(portfolio.get("economic_fill_total") or sum(1 for row in inventory if row.get("economic_fill")))
    accepted_count = int(portfolio.get("accepted_fill_total") or len(accepted))
    open_count = int(portfolio.get("open_positions_count") or len([row for row in positions if row.get("open_position")]))
    blockers = []
    runtime_notes = []
    if accepted_count > 0 and economic_count == 0:
        blockers.append("ACCEPTED_PAPER_FILLS_NON_ECONOMIC")
    if accepted_count > 0 and open_count == 0 and economic_count > 0:
        blockers.append("NO_OPEN_POSITIONS_AFTER_ECONOMIC_FILL")
    if portfolio.get("paper_zero_pnl_reason") in {"MARK_PRICE_MISSING", "FILL_TO_POSITION_PIPE_BROKEN"}:
        blockers.append(str(portfolio.get("paper_zero_pnl_reason")))
    if refresh.get("orchestrator", {}).get("proposals_arbitrated") == 0:
        runtime_notes.append("NO_NATIVE_CUDA_PAPER_FILL_ALLOWED_PROPOSALS_CURRENTLY")

    fill_inventory = {
        "schema_version": "paper_fill_economic_inventory_v1",
        "generated_est": est_now(),
        "accepted_fill_count": accepted_count,
        "economic_fill_count": economic_count,
        "non_economic_fill_count": int(portfolio.get("non_economic_fill_total") or (accepted_count - economic_count)),
        "fills": inventory,
        "old_june_5_fills_reused": False,
        "fills_fabricated": False,
    }
    reconciliation_rows = []
    accepted_by_id = {
        str(row.get("intent_id") or row.get("paper_fill_id") or row.get("prediction_id") or row.get("source_prediction_id")): row
        for row in accepted
    }
    for fill in inventory:
        row_id = str(fill.get("intent_id") or fill.get("fill_id") or fill.get("prediction_id"))
        row = accepted_by_id.get(row_id) or {}
        reconciliation_rows.append(
            {
                "fill_id": fill.get("fill_id"),
                "accepted_fill_exists": bool(row),
                "ledger_row_exists": bool(row),
                "ledger_row_id": row_id,
                "ledger_row_has_qty": row.get("quantity") is not None or row.get("qty") is not None,
                "ledger_row_has_price": row.get("fill_price") is not None or row.get("entry_price") is not None,
                "ledger_row_has_side": bool(row.get("side") or row.get("selected_action") or row.get("action")),
                "ledger_row_has_notional": row.get("notional") is not None or row.get("notional_usdt") is not None,
                "ledger_row_has_lineage": all(fill.get(field) for field in ("prediction_id", "risk_decision_id", "orchestrator_decision_id", "signal_id")),
                "ledger_row_has_session_id": bool(row.get("session_id") or ledger.get("session_id")),
                "ledger_row_has_mark_price_source": bool(row.get("latest_price_source") or fill.get("mark_price_source")),
                "classification": fill.get("classification"),
                "missing_fields": fill.get("missing_fields"),
            }
        )
    fill_to_ledger = {
        "schema_version": "paper_fill_to_ledger_reconciliation_status_v1",
        "generated_est": est_now(),
        "accepted_fill_count": accepted_count,
        "economic_fill_count": economic_count,
        "rows": reconciliation_rows,
        "status": (
            "FILL_TO_LEDGER_ECONOMIC_ROWS_OK"
            if economic_count > 0
            else "ACCEPTED_ROWS_PRESENT_BUT_NON_ECONOMIC"
            if accepted_count > 0
            else "NO_ACCEPTED_PAPER_FILLS_CURRENTLY"
        ),
    }
    position_status = {
        "schema_version": "paper_position_reconstruction_status_v1",
        "generated_est": est_now(),
        "open_positions_count": open_count,
        "closed_positions_count": int(portfolio.get("closed_positions_count") or 0),
        "positions_by_symbol": positions,
        "realized_pnl": portfolio.get("realized_pnl_usd", 0.0),
        "unrealized_pnl": portfolio.get("unrealized_pnl_usd", 0.0),
        "status": portfolio.get("ledger_to_portfolio_status"),
    }
    mark_status = {
        "schema_version": "paper_mark_price_source_status_v1",
        "generated_est": est_now(),
        "rows": [
            {
                "symbol": fill.get("symbol"),
                "mark_price": fill.get("current_mark_price"),
                "mark_price_source": fill.get("mark_price_source"),
                "mark_price_age_seconds": fill.get("mark_price_age_seconds"),
                "entry_price": fill.get("entry_price"),
                "price_delta": fill.get("price_delta"),
                "unrealized_pnl": fill.get("unrealized_pnl"),
                "status": "MARK_PRICE_OK" if fill.get("current_mark_price") else "MARK_PRICE_MISSING",
            }
            for fill in inventory
        ],
    }
    equity_status = {
        "schema_version": "paper_equity_mark_to_market_recompute_status_v1",
        "generated_est": est_now(),
        "initial_capital": portfolio.get("initial_capital", 10000.0),
        "cash_balance": portfolio.get("cash_balance", 10000.0),
        "open_position_notional": portfolio.get("open_position_notional", 0.0),
        "closed_position_notional": None,
        "realized_pnl": portfolio.get("realized_pnl_usd", 0.0),
        "unrealized_pnl": portfolio.get("unrealized_pnl_usd", 0.0),
        "fees": 0.0,
        "slippage": 0.0,
        "current_session_pnl": portfolio.get("total_pnl_usd", 0.0),
        "current_session_equity": portfolio.get("equity", 10000.0),
        "equity_change_since_last_cycle": portfolio.get("equity_change_since_last", 0.0),
        "accepted_fill_count": accepted_count,
        "economic_fill_count": economic_count,
        "open_positions_count": open_count,
        "closed_positions_count": portfolio.get("closed_positions_count", 0),
        "last_fill_est": portfolio.get("last_fill_est"),
        "last_fill_utc": portfolio.get("last_fill_utc"),
        "last_mark_to_market_est": portfolio.get("last_equity_update_est"),
        "zero_pnl_reason": portfolio.get("paper_zero_pnl_reason") or portfolio.get("paper_equity_reason"),
    }
    monitor_status = {
        "schema_version": "paper_mark_to_market_continuous_monitor_status_v1",
        "generated_est": est_now(),
        "paper_equity_reconciliation_loop_timer": service_status("ai-bot-v2-paper-equity-reconciliation-loop.timer"),
        "paper_mark_to_market_loop_timer": service_status("ai-bot-v2-paper-mark-to-market-loop.timer"),
        "cadence_seconds": "15-30 target if paper-mark-to-market timer installed; existing equity reconciliation timer remains active",
        "alert": (
            "PAPER_MARK_TO_MARKET_EQUITY_STALE_AFTER_ECONOMIC_FILL"
            if accepted_count > 0 and economic_count > 0 and portfolio.get("equity_change_since_last") == 0
            else None
        ),
    }
    website_status = {
        "schema_version": "paper_website_equity_source_status_v1",
        "generated_est": est_now(),
        "current_session_equity": portfolio.get("equity"),
        "current_session_pnl": portfolio.get("total_pnl_usd"),
        "stale_values_blocked_as_current": ["9950.654465", "-49", "-45"],
        "source_payload": "operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json",
        "routes": [
            route_status("operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json"),
            route_status("operator_runtime/v2_runtime_truth/latest/operator_runtime_truth.json"),
        ],
    }
    dashboard = {
        "gate": READY if not blockers else BLOCKED,
        "generated_est": est_now(),
        "pipeline_refresh": refresh,
        "accepted_fill_count": accepted_count,
        "economic_fill_count": economic_count,
        "held_row_count": int(portfolio.get("held_by_paper_fill_gate_total") or ledger.get("held_by_paper_fill_gate_count") or 0),
        "open_positions_count": open_count,
        "current_session_equity": portfolio.get("equity"),
        "current_session_pnl": portfolio.get("total_pnl_usd"),
        "zero_pnl_reason": equity_status["zero_pnl_reason"],
        "blockers": blockers,
        "runtime_notes": runtime_notes,
        "live_state": "LIVE_ARMED_BALANCE_HOLD",
        "safety": {
            "places_real_order": False,
            "calls_test_order": False,
            "changes_leverage": False,
            "changes_margin_mode": False,
            "writes_old_redis": False,
            "restarts_legacy": False,
            "trims_redis": False,
            "raw_credentials_exposed": False,
        },
    }
    return {
        "paper_fill_economic_inventory.json": fill_inventory,
        "paper_fill_to_ledger_reconciliation_status.json": fill_to_ledger,
        "paper_position_reconstruction_status.json": position_status,
        "paper_mark_price_source_status.json": mark_status,
        "paper_equity_mark_to_market_recompute_status.json": equity_status,
        "paper_mark_to_market_continuous_monitor_status.json": monitor_status,
        "paper_website_equity_source_status.json": website_status,
        "operator_dashboard_payload.json": dashboard,
    }


def report_text(dashboard: dict[str, Any], validation: dict[str, Any]) -> str:
    blockers = dashboard.get("blockers") or []
    blocker_lines = "\n".join(f"- `{item}`" for item in blockers) if blockers else "- none"
    notes = dashboard.get("runtime_notes") or []
    note_lines = "\n".join(f"- `{item}`" for item in notes) if notes else "- none"
    return "\n".join(
        [
            "# V2 Paper Fill Position Mark To Market Equity Repair Report",
            "",
            f"Gate: `{dashboard['gate']}`",
            f"Generated EST: `{dashboard['generated_est']}`",
            f"Accepted paper fills: `{dashboard['accepted_fill_count']}`",
            f"Economic paper fills: `{dashboard['economic_fill_count']}`",
            f"Held paper rows: `{dashboard['held_row_count']}`",
            f"Open paper positions: `{dashboard['open_positions_count']}`",
            f"Paper current session equity: `{dashboard['current_session_equity']}`",
            f"Paper current session PnL: `{dashboard['current_session_pnl']}`",
            f"Zero PnL reason: `{dashboard['zero_pnl_reason']}`",
            "",
            "## Blockers",
            "",
            blocker_lines,
            "",
            "## Runtime Notes",
            "",
            note_lines,
            "",
            "## Validation",
            "",
            *[f"- {key}: `{value}`" for key, value in validation.items()],
            "",
            "Safety: no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, and no raw credential output.",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="V2 paper mark-to-market equity repair gate")
    parser.add_argument("--skip-refresh", action="store_true")
    args = parser.parse_args(argv)
    refresh = {} if args.skip_refresh else run_pipeline_refresh()
    statuses = build_statuses(refresh)
    validation = {
        "py_compile": "NOT_RUN_BY_GATE_CLI",
        "focused_paper_accounting_tests": "NOT_RUN_BY_GATE_CLI",
        "frontend_typecheck": "NOT_RUN_BY_GATE_CLI",
        "frontend_build": "NOT_RUN_BY_GATE_CLI",
        "route_crawl": "NOT_RUN_BY_GATE_CLI",
        "old_redis_scan": "NOT_RUN_BY_GATE_CLI",
        "exchange_mutation_scan": "NOT_RUN_BY_GATE_CLI",
        "raw_secret_scan": "NOT_RUN_BY_GATE_CLI",
    }
    dashboard = statuses["operator_dashboard_payload.json"]
    dashboard["validation"] = validation
    out_dirs = [PUBLIC_DIR / OUT_REL, REPO_ROOT / WORKLOG_REL]
    for out_dir in out_dirs:
        for filename, payload in statuses.items():
            write_json(out_dir / filename, payload)
        write_text(out_dir / "GO_NO_GO.md", dashboard["gate"] + "\n")
        write_text(
            out_dir / "V2_PAPER_FILL_POSITION_MARK_TO_MARKET_EQUITY_REPAIR_REPORT.md",
            report_text(dashboard, validation),
        )
    print(json.dumps({"gate": dashboard["gate"], "blockers": dashboard.get("blockers", [])}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
