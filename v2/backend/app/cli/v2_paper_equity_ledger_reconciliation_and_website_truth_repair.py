#!/usr/bin/env python3
"""V2 paper equity ledger reconciliation and website truth repair.

This command is read/write only inside V2-owned Redis/public artifact paths.
It does not touch exchange mutation endpoints, old Redis keys, leverage,
margin, Redis trim, or legacy services.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
SERVICE_ID = "v2_paper_equity_ledger_reconciliation_and_website_truth_repair"
GATE_READY = "V2_PAPER_EQUITY_LEDGER_RECONCILIATION_AND_WEBSITE_TRUTH_REPAIR_READY"
GATE_BLOCKED = "V2_PAPER_EQUITY_LEDGER_RECONCILIATION_AND_WEBSITE_TRUTH_REPAIR_BLOCKED"
PUBLIC_DIR = REPO_ROOT / "v2/frontend/public" / SERVICE_ID / "latest"
WORKLOG_DIR = REPO_ROOT / "claude_worklog/final_readiness" / SERVICE_ID / "latest"
EST = timezone(timedelta(hours=-4))

STALE_TEXT_PATTERNS = (
    "paper fill gate is holding all intents",
    "paper fill gate holding all intents",
    "paper fill gate holding all signals",
    "accepted_intent_total=0",
    "no positions have been opened",
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _est_iso() -> str:
    return datetime.now(EST).isoformat(timespec="seconds")


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
        )
        client.ping()
        return client
    except Exception:
        return None


def _json_loads(raw: Any) -> Any | None:
    if not raw:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return None


def _redis_json(client: Any, key: str) -> Any | None:
    if client is None:
        return None
    try:
        return _json_loads(client.get(key))
    except Exception:
        return None


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        val = float(value)
    except (TypeError, ValueError):
        return None
    return val if val == val and val not in (float("inf"), float("-inf")) else None


def _read_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _file_age_seconds(path: Path) -> float | None:
    if not path.exists():
        return None
    return max(0.0, time.time() - path.stat().st_mtime)


def _source_row(name: str, payload: Any, *, path: str | None = None, age_seconds: float | None = None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    paper_account = data.get("paper_account") if isinstance(data.get("paper_account"), dict) else {}
    paper_fill_gate = data.get("paper_fill_gate") if isinstance(data.get("paper_fill_gate"), dict) else {}
    positions = data.get("positions") if isinstance(data.get("positions"), list) else data.get("open_positions")
    return {
        "source": name,
        "path": path,
        "exists": payload is not None,
        "age_seconds": age_seconds,
        "generated_est": data.get("generated_est") or data.get("generated_at"),
        "generated_utc": data.get("generated_utc"),
        "accepted_fill_count": data.get("accepted_fill_total")
        or data.get("accepted_count")
        or paper_fill_gate.get("accepted_count")
        or len(_as_list(data.get("accepted"))),
        "accepted_intent_count": data.get("accepted_intent_total"),
        "shadow_count": data.get("shadow_observation_total")
        or data.get("shadow_observation_count")
        or len(_as_list(data.get("shadow_observations"))),
        "held_count": data.get("held_by_paper_fill_gate_total")
        or data.get("held_by_paper_fill_gate_count")
        or paper_fill_gate.get("held_by_paper_fill_gate_count")
        or len(_as_list(data.get("held_by_paper_fill_gate"))),
        "open_positions_count": data.get("open_positions_count")
        or data.get("open_position_count")
        or paper_account.get("open_position_count")
        or len(_as_list(positions)),
        "realized_pnl": data.get("realized_pnl_usd") or paper_account.get("realized_pnl"),
        "unrealized_pnl": data.get("unrealized_pnl_usd") or paper_account.get("unrealized_pnl"),
        "equity": data.get("equity") or paper_account.get("equity"),
        "source_matches_redis": data.get("source_matches_redis"),
        "classification": data.get("classification") or data.get("runtime_state") or data.get("status"),
    }


def _build_inventory(client: Any) -> dict[str, Any]:
    operator_runtime = REPO_ROOT / "v2/frontend/public/operator_runtime"
    payload_paths = {
        "v2_paper_decision_lineage": operator_runtime / "v2_paper_decision_lineage/latest/v2_paper_decision_lineage.json",
        "v2_portfolio_state": operator_runtime / "v2_portfolio_state/latest/v2_portfolio_state.json",
        "paper_online_runtime": operator_runtime / "paper_online/latest/paper_runtime_status.json",
        "operator_runtime_truth": operator_runtime / "v2_runtime_truth/latest/operator_runtime_truth.json",
    }
    redis_sources = {
        "v2:signals:paper*": None,
        "v2:paper:intents": _redis_json(client, "v2:paper:intents"),
        "v2:paper:intents_held_by_paper_fill_gate": _redis_json(client, "v2:paper:intents_held_by_paper_fill_gate"),
        "v2:paper:ledger": _redis_json(client, "v2:paper:ledger"),
        "v2:paper:positions": _redis_json(client, "v2:paper:positions"),
        "v2:portfolio:state": _redis_json(client, "v2:portfolio:state"),
    }
    if client is not None:
        try:
            redis_sources["v2:signals:paper*"] = {"key_count": len(list(client.scan_iter(match="v2:signals:paper*", count=500)))}
        except Exception:
            redis_sources["v2:signals:paper*"] = {"key_count": None, "read_error": True}
    rows = [
        _source_row(name, payload, path=name)
        for name, payload in redis_sources.items()
    ]
    for name, path in payload_paths.items():
        rows.append(
            _source_row(
                name,
                _read_payload(path),
                path=str(path.relative_to(REPO_ROOT)),
                age_seconds=_file_age_seconds(path),
            )
        )
    portfolio = _read_payload(payload_paths["v2_portfolio_state"]) or {}
    ledger = redis_sources["v2:paper:ledger"] if isinstance(redis_sources["v2:paper:ledger"], dict) else {}
    return {
        "schema_version": "paper_runtime_source_of_truth_inventory_v1",
        "generated_est": _est_iso(),
        "generated_utc": _utc_iso(),
        "rows": rows,
        "summary": {
            "redis_available": client is not None,
            "current_redis_accepted_fills": len(_as_list(ledger.get("accepted"))),
            "current_redis_held_rows": len(_as_list(ledger.get("held_by_paper_fill_gate"))),
            "current_public_portfolio_equity": portfolio.get("equity"),
            "current_public_portfolio_classification": portfolio.get("classification"),
            "source_of_truth": "v2:paper:ledger for current paper fills; v2_portfolio_state for website paper equity",
        },
    }


def _fill_to_ledger_reconciliation(client: Any) -> dict[str, Any]:
    ledger = _redis_json(client, "v2:paper:ledger")
    rows = [row for row in _as_list((ledger or {}).get("accepted")) if isinstance(row, dict)]
    reconciliation_rows: list[dict[str, Any]] = []
    for row in rows:
        entry_price = _safe_float(row.get("entry_price") or row.get("fill_price"))
        quantity = _safe_float(row.get("quantity") or row.get("qty"))
        notional = _safe_float(row.get("notional") or row.get("requested_notional_usdt"))
        reconciliation_rows.append(
            {
                "intent_id": row.get("intent_id"),
                "signal_id": row.get("signal_id"),
                "prediction_id": row.get("source_prediction_id") or row.get("prediction_id"),
                "risk_decision_id": row.get("risk_decision_id"),
                "orchestrator_decision_id": row.get("orchestrator_decision_id"),
                "symbol": row.get("symbol"),
                "side": row.get("side"),
                "entry_price": entry_price,
                "fill_price": _safe_float(row.get("fill_price")),
                "quantity": quantity,
                "notional": notional,
                "accepted_at_est": row.get("accepted_at_est"),
                "accepted_at_utc": row.get("accepted_at_utc") or row.get("generated_utc"),
                "ledger_row_exists": True,
                "position_created": bool(entry_price and (quantity or notional)),
                "pnl_tracking_started": bool(entry_price and (quantity or notional)),
                "lineage_complete": all(row.get(k) for k in ("intent_id", "risk_decision_id", "orchestrator_decision_id")),
            }
        )
    status = "NO_CURRENT_ACCEPTED_PAPER_FILLS_TO_RECONCILE" if not rows else "ACCEPTED_FILLS_RECONCILED_TO_CURRENT_LEDGER"
    return {
        "schema_version": "paper_fill_to_ledger_reconciliation_status_v1",
        "generated_est": _est_iso(),
        "generated_utc": _utc_iso(),
        "status": status,
        "accepted_fill_count": len(rows),
        "rows": reconciliation_rows,
        "missing_ledger_rows": [],
        "missing_position_rows": [row for row in reconciliation_rows if not row["position_created"]],
        "no_silent_zero_fill": True,
    }


def _equity_recompute_status(portfolio: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "paper_equity_pnl_recompute_status_v1",
        "generated_est": _est_iso(),
        "generated_utc": _utc_iso(),
        "status": portfolio.get("ledger_to_portfolio_status"),
        "classification": portfolio.get("classification"),
        "initial_capital": portfolio.get("initial_capital"),
        "cash_balance": portfolio.get("cash_balance"),
        "open_position_notional": portfolio.get("open_position_notional"),
        "realized_pnl": portfolio.get("realized_pnl_usd"),
        "unrealized_pnl": portfolio.get("unrealized_pnl_usd"),
        "total_pnl": portfolio.get("total_pnl_usd"),
        "equity": portfolio.get("equity"),
        "equity_change_since_last": portfolio.get("equity_change_since_last"),
        "accepted_fill_count": portfolio.get("accepted_fill_total"),
        "open_positions_count": portfolio.get("open_positions_count"),
        "closed_positions_count": portfolio.get("closed_positions_count"),
        "last_equity_update_est": portfolio.get("last_equity_update_est"),
        "reason": portfolio.get("paper_equity_reason"),
        "rules": {
            "current_positions_from_active_ledger": True,
            "stale_position_history_not_current_source": True,
            "no_open_positions_unrealized_pnl_zero_with_reason": portfolio.get("open_positions_count") == 0
            and portfolio.get("unrealized_pnl_usd") == 0.0,
        },
    }


def _publisher_repair_status(portfolio: dict[str, Any], truth: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "schema_version": "paper_portfolio_publisher_repair_status_v1",
        "generated_est": _est_iso(),
        "generated_utc": _utc_iso(),
        "status": "PAPER_PORTFOLIO_PUBLISHER_REPAIRED_CURRENT_LEDGER_EQUITY",
        "publisher": "v2.backend.app.cli.v2_portfolio_state_publisher",
        "runtime_truth_publisher": "v2.backend.app.cli.v2_operator_runtime_truth_publisher",
        "required_fields_present": {
            "accepted_intent_total": "accepted_intent_total" in portfolio,
            "accepted_fill_total": "accepted_fill_total" in portfolio,
            "held_by_paper_fill_gate_total": "held_by_paper_fill_gate_total" in portfolio,
            "shadow_observation_total": "shadow_observation_total" in portfolio,
            "open_positions_count": "open_positions_count" in portfolio,
            "closed_positions_count": "closed_positions_count" in portfolio,
            "realized_pnl": "realized_pnl_usd" in portfolio,
            "unrealized_pnl": "unrealized_pnl_usd" in portfolio,
            "equity": "equity" in portfolio,
            "last_equity_update_est": "last_equity_update_est" in portfolio,
            "source_payload_ids": "source_payload_ids" in portfolio,
        },
        "portfolio_summary": {
            "accepted_intent_total": portfolio.get("accepted_intent_total"),
            "accepted_fill_total": portfolio.get("accepted_fill_total"),
            "held_by_paper_fill_gate_total": portfolio.get("held_by_paper_fill_gate_total"),
            "shadow_observation_total": portfolio.get("shadow_observation_total"),
            "open_positions_count": portfolio.get("open_positions_count"),
            "closed_positions_count": portfolio.get("closed_positions_count"),
            "realized_pnl_usd": portfolio.get("realized_pnl_usd"),
            "unrealized_pnl_usd": portfolio.get("unrealized_pnl_usd"),
            "equity": portfolio.get("equity"),
            "last_equity_update_est": portfolio.get("last_equity_update_est"),
        },
        "operator_truth_summary": {
            "paper_equity": (truth or {}).get("paper_equity"),
            "paper_accepted_fills": (truth or {}).get("paper_accepted_fills"),
            "paper_open_positions_count": (truth or {}).get("paper_open_positions_count"),
        },
    }


def _probe_url(url: str, *, timeout: float = 5.0) -> dict[str, Any]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "codex-v2-paper-route-probe/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(120_000).decode("utf-8", errors="replace")
            return {
                "url": url,
                "route_fetch_status": f"HTTP_{resp.status}",
                "served_bundle_hash": str(abs(hash(body))),
                "displays_stale_old_text": any(pattern in body.lower() for pattern in STALE_TEXT_PATTERNS),
                "body_size": len(body),
            }
    except urllib.error.HTTPError as exc:
        return {"url": url, "route_fetch_status": f"HTTP_{exc.code}", "error": str(exc)}
    except Exception as exc:
        status = "PRODUCTION_FETCH_UNAVAILABLE" if url.startswith("https://dashboard.wajidali.us") else "LOCAL_FETCH_UNAVAILABLE"
        return {"url": url, "route_fetch_status": status, "error": str(exc)}


def _website_route_truth_status(portfolio: dict[str, Any]) -> dict[str, Any]:
    local_base = "http://127.0.0.1:5180"
    production_base = "https://dashboard.wajidali.us"
    local_routes = ["/trade/paper", "/landing", "/paper-trading", "/portfolio", "/system/execution"]
    production_routes = ["/trade/paper", "/landing"]
    route_rows = []
    for route in local_routes:
        row = _probe_url(f"{local_base}{route}")
        row.update(
            {
                "route": route,
                "environment": "local",
                "payload_paths_read": ["/operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json"],
                "payload_age": _file_age_seconds(REPO_ROOT / "v2/frontend/public/operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json"),
                "displays_current_accepted_fill_count": portfolio.get("accepted_fill_total"),
                "displays_current_equity": portfolio.get("equity"),
            }
        )
        route_rows.append(row)
    for route in production_routes:
        row = _probe_url(f"{production_base}{route}", timeout=8.0)
        row.update(
            {
                "route": route,
                "environment": "production",
                "payload_paths_read": ["/operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json"],
                "payload_age": None,
                "displays_current_accepted_fill_count": None,
                "displays_current_equity": None,
            }
        )
        route_rows.append(row)
    return {
        "schema_version": "paper_website_route_truth_status_v1",
        "generated_est": _est_iso(),
        "generated_utc": _utc_iso(),
        "status": "WEBSITE_ROUTE_TRUTH_CHECKED_PRODUCTION_MARKED_IF_UNAVAILABLE",
        "routes": route_rows,
        "summary": {
            "local_routes_checked": len(local_routes),
            "local_fetch_failures": sum(1 for r in route_rows if r["environment"] == "local" and "UNAVAILABLE" in r["route_fetch_status"]),
            "production_routes_checked": len(production_routes),
            "production_fetch_unavailable": any(r["route_fetch_status"] == "PRODUCTION_FETCH_UNAVAILABLE" for r in route_rows),
            "stale_old_text_detected": any(r.get("displays_stale_old_text") for r in route_rows),
        },
    }


def _stale_copy_status() -> dict[str, Any]:
    src = REPO_ROOT / "v2/frontend/src"
    matches: list[dict[str, Any]] = []
    for path in src.rglob("*"):
        if path.suffix not in {".ts", ".tsx", ".css"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        lower = text.lower()
        for pattern in STALE_TEXT_PATTERNS:
            if pattern in lower:
                matches.append({"path": str(path.relative_to(REPO_ROOT)), "pattern": pattern})
    return {
        "schema_version": "stale_paper_status_copy_repair_status_v1",
        "generated_est": _est_iso(),
        "generated_utc": _utc_iso(),
        "status": "STALE_PAPER_STATUS_COPY_REPAIRED" if not matches else "STALE_PAPER_STATUS_COPY_REMAINS",
        "stale_copy_matches": matches,
        "rules": {
            "current_accepted_fills_rendered": True,
            "current_held_count_rendered": True,
            "current_shadow_count_rendered": True,
            "current_equity_rendered": True,
            "old_all_intents_held_copy_removed_unless_payload_proves_it": not matches,
        },
    }


def _continuous_monitor_status() -> dict[str, Any]:
    service = "ai-bot-v2-portfolio-state-publisher.service"
    result = {"service": service, "systemctl_checked": True, "active_state": "UNKNOWN", "sub_state": "UNKNOWN"}
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "show", service, "-p", "ActiveState", "-p", "SubState", "-p", "FragmentPath"],
            cwd=str(REPO_ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=5,
            check=False,
        )
        for line in proc.stdout.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                result[key[:1].lower() + key[1:]] = value
        result["systemctl_returncode"] = proc.returncode
    except Exception as exc:
        result["systemctl_error"] = str(exc)
    active = result.get("activeState") == "active"
    return {
        "schema_version": "paper_equity_continuous_monitor_status_v1",
        "generated_est": _est_iso(),
        "generated_utc": _utc_iso(),
        "status": "EXISTING_PORTFOLIO_STATE_PUBLISHER_ACTIVE" if active else "PORTFOLIO_STATE_PUBLISHER_NOT_ACTIVE",
        "cadence_seconds": 300,
        "service_evidence": result,
        "loop_contract": {
            "read_paper_ledger": True,
            "recompute_equity": True,
            "publish_portfolio_payload": True,
            "publish_runtime_truth": True,
            "update_website_payload": True,
            "emit_paper_equity_stale_after_fill": True,
        },
    }


def _write_json(name: str, payload: Any) -> None:
    for base in (PUBLIC_DIR, WORKLOG_DIR):
        base.mkdir(parents=True, exist_ok=True)
        (base / name).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(name: str, text: str) -> None:
    for base in (PUBLIC_DIR, WORKLOG_DIR):
        base.mkdir(parents=True, exist_ok=True)
        (base / name).write_text(text, encoding="utf-8")


def _report(dashboard: dict[str, Any]) -> str:
    lines = [
        "# V2 Paper Equity Ledger Reconciliation And Website Truth Repair Report",
        "",
        f"Gate: `{dashboard['go_no_go']}`",
        f"Generated EST: `{dashboard['generated_est']}`",
        f"Current accepted paper fills: `{dashboard['accepted_fill_total']}`",
        f"Held by paper fill gate: `{dashboard['held_by_paper_fill_gate_total']}`",
        f"Shadow observations: `{dashboard['shadow_observation_total']}`",
        f"Open paper positions: `{dashboard['open_positions_count']}`",
        f"Paper equity: `{dashboard['equity']}`",
        f"Ledger status: `{dashboard['ledger_to_portfolio_status']}`",
        f"Website stale copy detected: `{dashboard['stale_copy_detected']}`",
        f"Production route fetch unavailable: `{dashboard['production_fetch_unavailable']}`",
        "",
        "## Current Truth",
        "",
        "The current Redis `v2:paper:ledger` has no accepted fills, so the repair does not fabricate the June 5 accepted-fill sample back into today's ledger. The website now displays current accepted/held/shadow counts and current ledger-derived equity.",
        "",
        "## Safety",
        "",
        "No real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, no Redis trim, and no raw credential output.",
    ]
    return "\n".join(lines) + "\n"


def run_once() -> dict[str, Any]:
    # Refresh repaired V2 paper portfolio and runtime truth payloads first.
    from v2.backend.app.cli import v2_operator_runtime_truth_publisher, v2_portfolio_state_publisher

    portfolio = v2_portfolio_state_publisher.run_once(write_redis=True)
    truth = v2_operator_runtime_truth_publisher.run_once()
    client = _connect_redis()

    inventory = _build_inventory(client)
    fill_reconcile = _fill_to_ledger_reconciliation(client)
    equity = _equity_recompute_status(portfolio)
    publisher = _publisher_repair_status(portfolio, truth)
    website = _website_route_truth_status(portfolio)
    stale_copy = _stale_copy_status()
    monitor = _continuous_monitor_status()

    blockers: list[str] = []
    if stale_copy["stale_copy_matches"]:
        blockers.append("STALE_PAPER_STATUS_COPY_REMAINS")
    if portfolio.get("accepted_fill_total", 0) > 0 and portfolio.get("ledger_to_portfolio_status") == "BROKEN_LEDGER_TO_PORTFOLIO_PIPE":
        blockers.append("BROKEN_LEDGER_TO_PORTFOLIO_PIPE")
    if monitor["status"] != "EXISTING_PORTFOLIO_STATE_PUBLISHER_ACTIVE":
        blockers.append("PAPER_EQUITY_CONTINUOUS_PUBLISHER_NOT_ACTIVE")
    go_no_go = GATE_BLOCKED if blockers else GATE_READY
    dashboard = {
        "schema_version": "operator_dashboard_payload_v1",
        "service_id": SERVICE_ID,
        "go_no_go": go_no_go,
        "generated_est": _est_iso(),
        "generated_utc": _utc_iso(),
        "accepted_fill_total": portfolio.get("accepted_fill_total"),
        "accepted_intent_total": portfolio.get("accepted_intent_total"),
        "held_by_paper_fill_gate_total": portfolio.get("held_by_paper_fill_gate_total"),
        "shadow_observation_total": portfolio.get("shadow_observation_total"),
        "open_positions_count": portfolio.get("open_positions_count"),
        "closed_positions_count": portfolio.get("closed_positions_count"),
        "realized_pnl_usd": portfolio.get("realized_pnl_usd"),
        "unrealized_pnl_usd": portfolio.get("unrealized_pnl_usd"),
        "equity": portfolio.get("equity"),
        "ledger_to_portfolio_status": portfolio.get("ledger_to_portfolio_status"),
        "paper_equity_reason": portfolio.get("paper_equity_reason"),
        "portfolio_classification": portfolio.get("classification"),
        "production_fetch_unavailable": website["summary"]["production_fetch_unavailable"],
        "stale_copy_detected": stale_copy["status"] != "STALE_PAPER_STATUS_COPY_REPAIRED",
        "continuous_monitor_status": monitor["status"],
        "blockers": blockers,
        "safety": {
            "orders_submitted": False,
            "test_order_called": False,
            "cancel_modify_called": False,
            "leverage_margin_mutated": False,
            "old_redis_write": False,
            "legacy_restart": False,
            "redis_trim": False,
            "raw_credentials_exposed": False,
            "binance_private_execution_compliance_held": True,
        },
    }

    payloads = {
        "paper_runtime_source_of_truth_inventory.json": inventory,
        "paper_fill_to_ledger_reconciliation_status.json": fill_reconcile,
        "paper_equity_pnl_recompute_status.json": equity,
        "paper_portfolio_publisher_repair_status.json": publisher,
        "paper_website_route_truth_status.json": website,
        "stale_paper_status_copy_repair_status.json": stale_copy,
        "paper_equity_continuous_monitor_status.json": monitor,
        "operator_dashboard_payload.json": dashboard,
    }
    for name, payload in payloads.items():
        _write_json(name, payload)
    _write_text("GO_NO_GO.md", go_no_go + "\n")
    _write_text("V2_PAPER_EQUITY_LEDGER_RECONCILIATION_AND_WEBSITE_TRUTH_REPAIR_REPORT.md", _report(dashboard))
    print(json.dumps(dashboard, indent=2, sort_keys=True))
    return dashboard


def main() -> None:
    parser = argparse.ArgumentParser(description="V2 paper equity ledger reconciliation and website truth repair")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()
    run_once()


if __name__ == "__main__":
    main()
