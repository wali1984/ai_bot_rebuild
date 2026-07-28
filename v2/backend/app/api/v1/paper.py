"""`/paper-trades/` endpoints — paper-mode acks, full chain (§7, 12B §9.7).

Scaffold-only: `prefix=` is set and an OPTIONS shim returns route metadata.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.v2._common import get_redis
from app.services.paper_session import epoch as paper_epoch

router = APIRouter(prefix="/paper-trades", tags=["paper-trades"])

ROUTE_METADATA: dict[str, Any] = {
    "group": "paper_trades",
    "prefix": "/paper-trades",
    "endpoints": ("/", "/{paper_trade_id}", "/{paper_trade_id}/explain"),
    "rbac": "mixed",
    "lineage_bearing": True,
    "stage_required_ids": (
        "feature_snapshot_id",
        "prediction_id",
        "signal_id",
        "decision_id",
        "risk_decision_id",
        "execution_intent_id",
    ),
    "milestone_d_status": "skeleton",
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _lag_ms(timestamp: str | None) -> int | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return max(0, int((datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds() * 1000))


def _redis_json(key: str) -> dict[str, Any] | None:
    if not key.startswith("v2:"):
        return None
    r = get_redis()
    if r is None:
        return None
    try:
        raw = r.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        return [row for row in value.values() if isinstance(row, dict)]
    return []


def _paper_trade_id(row: dict[str, Any]) -> str | None:
    for key in (
        "paper_trade_id",
        "trade_id",
        "position_id",
        "fill_id",
        "close_id",
        "execution_intent_id",
        "intent_id",
        "risk_decision_id",
        "orchestrator_decision_id",
        "candidate_id",
        "symbol",
    ):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _paper_payload(endpoint: str, scope: str = paper_epoch.DEFAULT_SCOPE) -> dict[str, Any]:
    client = get_redis()
    normalized_scope = paper_epoch.normalize_scope(scope)
    session = paper_epoch.current_session(client)
    ledger = _redis_json("v2:paper:ledger") or {}
    portfolio = _redis_json("v2:portfolio:state") or {}
    runtime = _redis_json("v2:paper:trade_management:status") or {}
    timestamp = (
        ledger.get("generated_utc")
        or ledger.get("generated_at")
        or portfolio.get("generated_utc")
        or runtime.get("generated_utc")
    )
    lag = _lag_ms(timestamp)
    open_positions = _rows(ledger.get("open_positions") or ledger.get("positions_by_symbol"))
    closed_trades = _rows(ledger.get("closed_trades"))
    accepted = _rows(ledger.get("accepted") or ledger.get("accepted_fills"))
    current_cycle_accepted = _rows(ledger.get("current_cycle_accepted"))
    closes = _rows(ledger.get("closes") or ledger.get("close_records"))
    total_rows = sum(map(len, (open_positions, closed_trades, accepted, current_cycle_accepted, closes)))
    if session.get("paper_account_epoch") is not None or normalized_scope != paper_epoch.DEFAULT_SCOPE:
        open_positions = paper_epoch.scope_rows(open_positions, session.get("paper_session_id"), normalized_scope)
        closed_trades = paper_epoch.scope_rows(closed_trades, session.get("paper_session_id"), normalized_scope)
        accepted = paper_epoch.scope_rows(accepted, session.get("paper_session_id"), normalized_scope)
        current_cycle_accepted = paper_epoch.scope_rows(
            current_cycle_accepted,
            session.get("paper_session_id"),
            normalized_scope,
        )
        closes = paper_epoch.scope_rows(closes, session.get("paper_session_id"), normalized_scope)
    shown_rows = sum(map(len, (open_positions, closed_trades, accepted, current_cycle_accepted, closes)))
    missing = []
    if not ledger:
        missing.append("v2:paper:ledger")
    if not portfolio:
        missing.append("v2:portfolio:state")

    realized_net_pnl = (
        portfolio.get("realized_net_pnl_usd")
        or portfolio.get("clean_session_valid_realized_pnl_usd")
        or portfolio.get("realized_pnl_usd")
    )
    unrealized_pnl = (
        portfolio.get("unrealized_pnl_usd")
        or portfolio.get("clean_session_valid_unrealized_pnl_usd")
    )
    total_pnl = portfolio.get("total_pnl_usd")
    data = {
        "paper_session_id": session.get("paper_session_id"),
        "paper_account_epoch": session.get("paper_account_epoch"),
        "scope": normalized_scope,
        "paper_session_state_source": ledger.get("paper_session_state_source"),
        "new_entries_allowed": ledger.get("new_entries_allowed"),
        "paper_new_entries_halted": ledger.get("paper_new_entries_halted"),
        "paper_effective_entry_gate_status": ledger.get("paper_effective_entry_gate_status"),
        "governor_state": (
            ledger.get("paper_performance_governor_status")
            or ledger.get("paper_churn_equity_bleed_governor_status")
        ),
        "equity": portfolio.get("equity") or portfolio.get("current_session_equity"),
        "starting_equity_usd": portfolio.get("initial_capital") or portfolio.get("starting_equity_usd") or ledger.get("starting_equity_usd"),
        "realized_pnl_usd": realized_net_pnl,
        "realized_net_pnl_usd": realized_net_pnl,
        "realized_gross_pnl_usd": portfolio.get("realized_gross_pnl_usd"),
        "unrealized_pnl_usd": unrealized_pnl,
        "total_pnl_usd": total_pnl,
        "pnl_source_key": portfolio.get("pnl_source_key", "v2:portfolio:state"),
        "pnl_source_route": portfolio.get("pnl_source_route", "/api/v2/portfolio"),
        "pnl_source_type": portfolio.get("pnl_source_type", "CANONICAL_CURRENT_SESSION_RUNTIME") if portfolio else None,
        "pnl_conflict_detected": bool(portfolio.get("pnl_conflict_detected", False)),
        "pnl_conflict_reason": portfolio.get("pnl_conflict_reason"),
        "closed_ledger_net_pnl_usd": portfolio.get("closed_ledger_net_pnl_usd"),
        "portfolio_realized_matches_closed_ledger": portfolio.get("portfolio_realized_matches_closed_ledger"),
        "equity_reconciles_within_1_cent": portfolio.get("equity_reconciles_within_1_cent"),
        "counts": {
            "open_positions": len(open_positions),
            "closed_trades": len(closed_trades),
            "accepted": len(accepted),
            "current_cycle_accepted": len(current_cycle_accepted),
            "closes": len(closes),
            "ledger_open_position_count": ledger.get("open_position_count"),
            "ledger_closed_trade_count": ledger.get("closed_trade_count"),
        },
        "accepted": accepted[:200],
        "current_cycle_accepted": current_cycle_accepted[:200],
        "open_positions": open_positions[:200],
        "closed_trades": closed_trades[:200],
        "closes": closes[:200],
        "lineage_bearing": True,
        "live_submit_allowed": False,
        "places_real_order": False,
    }
    data.update(paper_epoch.scope_response_fields(session, normalized_scope, total_rows, shown_rows))
    return {
        "data": data,
        "source": "redis:v2:portfolio:state + redis:v2:paper:ledger + redis:v2:paper:trade_management:status",
        "source_type": "redis_live" if ledger else "unavailable",
        "endpoint": endpoint,
        "timestamp": timestamp,
        "received_at": _utc_now(),
        "lag_ms": lag,
        "stale": not ledger or lag is None or lag > 300_000,
        "missing_fields": missing,
        "warnings": ["Paper trade endpoints are read-only and cannot place exchange orders"],
        "mode": "paper",
    }


def _all_trade_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    rows: list[dict[str, Any]] = []
    for key in ("accepted", "current_cycle_accepted", "open_positions", "closed_trades", "closes"):
        rows.extend(_rows(data.get(key)))
    return rows


@router.options("/", include_in_schema=False)
async def _route_metadata() -> dict[str, Any]:
    return ROUTE_METADATA


@router.get("")
@router.get("/")
async def list_paper_trades(
    scope: str = Query(default=paper_epoch.DEFAULT_SCOPE),
) -> dict[str, Any]:
    return _paper_payload("/api/v1/paper-trades", scope)


@router.get("/{paper_trade_id}")
async def get_paper_trade(
    paper_trade_id: str,
    scope: str = Query(default=paper_epoch.DEFAULT_SCOPE),
) -> dict[str, Any]:
    payload = _paper_payload(f"/api/v1/paper-trades/{paper_trade_id}", scope)
    for row in _all_trade_rows(payload):
        identifiers = {str(value) for value in row.values() if value not in (None, "")}
        row_id = _paper_trade_id(row)
        if paper_trade_id == row_id or paper_trade_id in identifiers:
            payload["data"] = {
                "paper_session_id": payload["data"].get("paper_session_id"),
                "trade": row,
                "trade_identifier": row_id,
                "lineage_bearing": True,
                "live_submit_allowed": False,
                "places_real_order": False,
            }
            return payload
    raise HTTPException(status_code=404, detail="paper_trade_not_found")


@router.get("/{paper_trade_id}/explain")
async def explain_paper_trade(
    paper_trade_id: str,
    scope: str = Query(default=paper_epoch.DEFAULT_SCOPE),
) -> dict[str, Any]:
    payload = await get_paper_trade(paper_trade_id, scope)
    trade = payload["data"]["trade"]
    payload["endpoint"] = f"/api/v1/paper-trades/{paper_trade_id}/explain"
    payload["data"] = {
        "paper_session_id": payload["data"].get("paper_session_id"),
        "trade_identifier": payload["data"].get("trade_identifier"),
        "lineage": {
            "feature_snapshot_id": trade.get("feature_snapshot_id"),
            "prediction_id": trade.get("prediction_id"),
            "signal_id": trade.get("signal_id"),
            "decision_id": trade.get("decision_id"),
            "risk_decision_id": trade.get("risk_decision_id"),
            "orchestrator_decision_id": trade.get("orchestrator_decision_id"),
            "execution_intent_id": trade.get("execution_intent_id"),
            "paper_session_id": trade.get("paper_session_id") or payload["data"].get("paper_session_id"),
        },
        "economics": {
            "symbol": trade.get("symbol"),
            "side": trade.get("side"),
            "quantity": trade.get("quantity") or trade.get("qty"),
            "entry_price": trade.get("entry_price") or trade.get("fill_price"),
            "exit_price": trade.get("exit_price"),
            "realized_pnl_usd": trade.get("realized_pnl_usd") or trade.get("realized_pnl_usdt"),
            "fees_usd": trade.get("fees_usd") or trade.get("fee_usd"),
            "slippage_usd": trade.get("slippage_usd"),
            "funding_usd": trade.get("funding_usd"),
        },
        "raw_trade": trade,
        "live_submit_allowed": False,
        "places_real_order": False,
    }
    return payload
