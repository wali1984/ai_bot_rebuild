"""Authenticated read-only trader snapshot aggregate.

This module composes existing V2 read models into one account-scoped payload.
It does not accept a frontend-supplied trader ID, does not recalculate trading
or risk logic, and does not expose any exchange mutation path.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends

from app.auth.security import require_auth
from app.auth.users import UserRecord, safe_user
from app.api.v2 import market_contracts

router = APIRouter(tags=["v2-trader-snapshot"])


SNAPSHOT_SECTIONS = (
    "account",
    "portfolio",
    "positions",
    "orders",
    "executions",
    "history",
    "signals",
    "predictions",
    "risk",
    "market_status",
    "automation_status",
    "execution_status",
    "data_status",
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _lag_ms(timestamp: str | None) -> int | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((datetime.now(UTC) - parsed.astimezone(UTC)).total_seconds() * 1000))


def _finite_number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or abs(number) == float("inf"):
        return None
    return number


def _integer(value: Any) -> int | None:
    number = _finite_number(value)
    return int(number) if number is not None else None


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _response_data(response: dict[str, Any]) -> Any:
    return response.get("data") if isinstance(response, dict) else None


def _meta_from_response(
    response: dict[str, Any],
    *,
    section: str,
    source_id: str | None = None,
    sequence: int | None = None,
    extra_missing: list[str] | None = None,
    extra_warnings: list[str] | None = None,
) -> dict[str, Any]:
    timestamp = response.get("timestamp") if isinstance(response.get("timestamp"), str) else None
    source_type = str(response.get("source_type") or "unavailable")
    stale = bool(response.get("stale"))
    missing = [
        str(item)
        for item in response.get("missing_fields", [])
        if isinstance(item, str)
    ]
    warnings = [
        str(item)
        for item in response.get("warnings", [])
        if isinstance(item, str)
    ]
    if extra_missing:
        missing.extend(extra_missing)
    if extra_warnings:
        warnings.extend(extra_warnings)
    missing = sorted(set(missing))
    warnings = [*dict.fromkeys(warnings)]
    lag = response.get("lag_ms")
    lag = lag if isinstance(lag, int) and lag >= 0 else _lag_ms(timestamp)
    unavailable = source_type == "unavailable"
    return {
        "source": str(response.get("source") or "unavailable"),
        "source_type": source_type,
        "source_id": source_id or str(response.get("endpoint") or section),
        "timestamp": timestamp,
        "received_at": response.get("received_at") if isinstance(response.get("received_at"), str) else _utc_now(),
        "sequence": sequence,
        "lag_ms": lag,
        "freshness": "offline" if unavailable else "stale" if stale else "fresh",
        "quality": "missing" if unavailable else "partial" if missing else "valid",
        "missing_fields": missing,
        "warnings": warnings,
    }


def _section(
    response: dict[str, Any],
    data: Any,
    *,
    section: str,
    source_id: str | None = None,
    sequence: int | None = None,
    extra_missing: list[str] | None = None,
    extra_warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "meta": _meta_from_response(
            response,
            section=section,
            source_id=source_id,
            sequence=sequence,
            extra_missing=extra_missing,
            extra_warnings=extra_warnings,
        ),
        "data": data,
    }


def _empty_section(section: str, missing_fields: list[str], warnings: list[str] | None = None) -> dict[str, Any]:
    return _section(
        {
            "source": "unavailable",
            "source_type": "unavailable",
            "endpoint": f"/api/v2/trader/snapshot.{section}",
            "timestamp": None,
            "received_at": _utc_now(),
            "lag_ms": None,
            "stale": True,
            "missing_fields": missing_fields,
            "warnings": warnings or [],
        },
        [] if section in {"positions", "orders", "executions", "history", "signals", "predictions", "market_status"} else {},
        section=section,
    )


def _canonical_account(
    actor: UserRecord,
    portfolio_response: dict[str, Any],
    positions_response: dict[str, Any],
    orders_response: dict[str, Any],
    executions_response: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    user = safe_user(actor)
    portfolio = _dict(_response_data(portfolio_response))
    positions = _list(_dict(_response_data(positions_response)).get("positions"))
    orders = _list(_dict(_response_data(orders_response)).get("orders"))
    executions = _list(_dict(_response_data(executions_response)).get("executions"))

    def _first_finite(*keys: str) -> float | None:
        # The canonical portfolio:state exposes PnL under *_usd suffixed keys; the
        # older flat names are not always present, so accept either spelling.
        for key in keys:
            value = _finite_number(portfolio.get(key))
            if value is not None:
                return value
        return None

    total_pnl = _first_finite("total_pnl", "total_pnl_usd", "paper_total_pnl_usd")
    realized_pnl = _first_finite("realized_pnl", "realized_pnl_usd", "realized_net_pnl_usd", "paper_realized_pnl_usd")
    unrealized_pnl = _first_finite("unrealized_pnl", "unrealized_pnl_usd", "paper_unrealized_pnl_usd")
    account = {
        "trader_id": user.get("trader_id"),
        "account_id": user.get("paper_account_id"),
        "mode": portfolio.get("mode") or "paper",
        "connection_status": "CONNECTED" if user.get("trader_id") and user.get("paper_account_id") else "UNAVAILABLE",
        "equity": _finite_number(portfolio.get("equity")),
        "available_balance": _first_finite("available_balance", "available_balance_usd", "paper_balance"),
        "used_balance": _first_finite("used_balance", "allocated_margin_usd", "used_margin_usd"),
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl if unrealized_pnl is not None else 0.0,
        "daily_pnl": _first_finite("daily_pnl", "daily_pnl_usd", "session_pnl_usd", "day_pnl_usd"),
        "total_pnl": total_pnl if total_pnl is not None else (
            (realized_pnl or 0.0) + (unrealized_pnl or 0.0) if (realized_pnl is not None or unrealized_pnl is not None) else None
        ),
        "exposure": _first_finite("total_open_notional", "gross_open_notional_usd", "total_open_notional_usd"),
        "drawdown": _first_finite("drawdown", "drawdown_pct", "max_drawdown_pct", "current_drawdown_pct"),
        "open_position_count": _integer(portfolio.get("open_position_count")) if portfolio.get("open_position_count") is not None else len(positions),
        "open_order_count": _integer(portfolio.get("open_order_count")) if portfolio.get("open_order_count") is not None else len(orders),
        "execution_count": _integer(portfolio.get("execution_count")) if portfolio.get("execution_count") is not None else len(executions),
    }
    missing = [key for key, value in account.items() if value is None]
    return account, missing


def _canonical_positions(positions_response: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    rows = _list(_dict(_response_data(positions_response)).get("positions"))
    normalized: list[dict[str, Any]] = []
    missing: set[str] = set()
    for index, row_value in enumerate(rows):
        row = _dict(row_value)
        position = {
            "id": str(row.get("id") or row.get("position_id") or f"position-{index}"),
            "symbol": row.get("symbol"),
            "side": row.get("side"),
            "quantity": _finite_number(row.get("quantity") or row.get("net_quantity") or row.get("size")),
            "entry_price": _finite_number(row.get("entry_price") or row.get("avg_entry_price") or row.get("fill_price") or row.get("entry")),
            "entry_price_source": row.get("entry_price_source") or row.get("source"),
            "mark_price": _finite_number(row.get("mark_price") or row.get("current_price")),
            "mark_price_source": row.get("mark_price_source") or row.get("price_source"),
            "mark_age_ms": _integer(row.get("mark_age_ms") or row.get("price_age_ms")),
            "exit_price": _finite_number(row.get("exit_price")),
            "exit_price_source": row.get("exit_price_source"),
            "notional": _finite_number(row.get("notional")),
            "unrealized_pnl": _finite_number(row.get("unrealized_pnl") or row.get("unrealized_pnl_usd")),
            "realized_pnl": _finite_number(row.get("realized_pnl") or row.get("realized_pnl_usd")),
            "pnl_percent": _finite_number(row.get("pnl_percent") or row.get("unrealized_pnl_pct")),
            "stop": _finite_number(row.get("stop") or row.get("stop_loss")),
            "targets": _list(row.get("targets")),
            "liquidation_price": _finite_number(row.get("liquidation_price")),
            "strategy_id": row.get("strategy_id"),
            "signal_id": row.get("signal_id"),
            "prediction_id": row.get("prediction_id"),
            "risk_status": row.get("risk_status"),
            "decision_reasoning": row.get("decision_reasoning") or row.get("reasoning"),
            "updated_at": row.get("updated_at") or row.get("time"),
        }
        for key, value in position.items():
            if value is None and key not in {"exit_price", "exit_price_source", "stop", "targets", "liquidation_price", "strategy_id", "signal_id", "prediction_id", "decision_reasoning"}:
                missing.add(f"position.{key}")
        normalized.append(position)
    if not normalized:
        missing.add("positions")
    return normalized, sorted(missing)


def _canonical_markets(market_response: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    data = _dict(_response_data(market_response))
    tickers = _list(data.get("tickers"))
    rows = tickers[:50]
    normalized: list[dict[str, Any]] = []
    missing: set[str] = set()
    for row_value in rows:
        row = _dict(row_value)
        symbol = row.get("symbol")
        market = {
            "symbol": str(symbol) if symbol else "",
            "last_price": _finite_number(row.get("last_price") or row.get("lastPrice")),
            "mark_price": _finite_number(row.get("mark_price")),
            "index_price": _finite_number(row.get("index_price")),
            "change_1h": _finite_number(row.get("change_1h")),
            "change_4h": _finite_number(row.get("change_4h")),
            "change_24h": _finite_number(row.get("change_24h") or row.get("priceChangePercent")),
            "high_24h": _finite_number(row.get("high_24h") or row.get("highPrice")),
            "low_24h": _finite_number(row.get("low_24h") or row.get("lowPrice")),
            "volume_24h": _finite_number(row.get("volume_24h") or row.get("volume")),
            "turnover_24h": _finite_number(row.get("turnover_24h") or row.get("quoteVolume")),
            "spread": _finite_number(row.get("spread")),
            "funding_rate": _finite_number(row.get("funding_rate")),
            "predicted_funding": _finite_number(row.get("predicted_funding")),
            "open_interest": _finite_number(row.get("open_interest")),
            "oi_change_1h": _finite_number(row.get("oi_change_1h")),
            "oi_change_4h": _finite_number(row.get("oi_change_4h")),
            "oi_change_24h": _finite_number(row.get("oi_change_24h")),
            "liquidations_1h": _finite_number(row.get("liquidations_1h")),
            "liquidations_24h": _finite_number(row.get("liquidations_24h")),
            "long_short_ratio": _finite_number(row.get("long_short_ratio")),
        }
        for key in ("symbol", "last_price", "change_24h", "high_24h", "low_24h", "volume_24h", "turnover_24h"):
            if market.get(key) in {None, ""}:
                missing.add(f"market.{key}")
        normalized.append(market)
    if not normalized:
        missing.add("market_status")
    return normalized, sorted(missing)


def _canonical_signals(signals_response: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    data = _dict(_response_data(signals_response))
    active = data.get("active_signal")
    rows = [active] if isinstance(active, dict) else _list(data.get("signals"))
    normalized: list[dict[str, Any]] = []
    missing: set[str] = set()
    for index, row_value in enumerate(rows):
        row = _dict(row_value)
        signal = {
            "id": str(row.get("id") or row.get("signal_id") or f"signal-{index}"),
            "symbol": row.get("symbol"),
            "direction": row.get("direction") or row.get("side"),
            "timeframe": row.get("timeframe"),
            "entry": _finite_number(row.get("entry") or row.get("entry_price")),
            "targets": _list(row.get("targets")),
            "stop": _finite_number(row.get("stop") or row.get("stop_loss")),
            "invalidation": _finite_number(row.get("invalidation")),
            "confidence": _finite_number(row.get("confidence")),
            "expected_move": _finite_number(row.get("expected_move")),
            "risk_reward": _finite_number(row.get("risk_reward")),
            "status": row.get("status"),
            "strategy": row.get("strategy") or row.get("strategy_id"),
            "model_version": row.get("model_version"),
            "risk_decision": row.get("risk_decision"),
            "created_at": row.get("created_at") or row.get("generated_at"),
            "expires_at": row.get("expires_at"),
            "evidence": _list(row.get("evidence")),
        }
        for key, value in signal.items():
            if value is None and key not in {"targets", "stop", "invalidation", "expires_at", "evidence"}:
                missing.add(f"signal.{key}")
        normalized.append(signal)
    if not normalized:
        missing.add("signals")
    return normalized, sorted(missing)


@router.get("/trader/snapshot")
async def get_trader_snapshot(actor: UserRecord = Depends(require_auth)) -> dict[str, Any]:
    sequence = int(datetime.now(UTC).timestamp() * 1000)
    (
        portfolio, positions, orders, executions, history,
        signals, predictions, risk, market_status, automation_status,
    ) = await asyncio.gather(
        market_contracts.get_portfolio(actor),
        market_contracts.get_account_positions(actor),
        market_contracts.get_execution_orders(actor),
        market_contracts.get_execution_executions(actor),
        market_contracts.get_paper_status(actor),
        market_contracts.get_signals(symbol=None, timeframe="5m", actor=actor),
        market_contracts.get_ai_predictions(symbol=None, actor=actor),
        market_contracts.get_risk_status(),
        market_contracts.get_market_overview(),
        market_contracts.get_orchestrator_status(),
    )
    execution_status = history  # same as paper status, avoid duplicate call

    account_data, account_missing = _canonical_account(actor, portfolio, positions, orders, executions)
    position_data, position_missing = _canonical_positions(positions)
    market_data, market_missing = _canonical_markets(market_status)
    signal_data, signal_missing = _canonical_signals(signals)
    execution_data = _list(_dict(_response_data(executions)).get("executions"))
    order_data = _list(_dict(_response_data(orders)).get("orders"))
    history_data = _dict(_response_data(history))
    prediction_data = _list(_dict(_response_data(predictions)).get("predictions"))
    risk_data = _dict(_response_data(risk))
    automation_data = _dict(_response_data(automation_status))
    execution_status_data = _dict(_response_data(execution_status))

    snapshot = {
        "account": _section(portfolio, account_data, section="account", sequence=sequence, extra_missing=account_missing),
        "portfolio": _section(portfolio, _dict(_response_data(portfolio)), section="portfolio", sequence=sequence),
        "positions": _section(positions, position_data, section="positions", sequence=sequence, extra_missing=position_missing),
        "orders": _section(orders, order_data, section="orders", sequence=sequence, extra_missing=[] if order_data else ["orders"]),
        "executions": _section(executions, execution_data, section="executions", sequence=sequence, extra_missing=[] if execution_data else ["executions"]),
        "history": _section(history, history_data, section="history", sequence=sequence),
        "signals": _section(signals, signal_data, section="signals", sequence=sequence, extra_missing=signal_missing),
        "predictions": _section(predictions, prediction_data, section="predictions", sequence=sequence, extra_missing=[] if prediction_data else ["predictions"]),
        "risk": _section(risk, risk_data, section="risk", sequence=sequence),
        "market_status": _section(market_status, market_data, section="market_status", sequence=sequence, extra_missing=market_missing),
        "automation_status": _section(automation_status, automation_data, section="automation_status", sequence=sequence),
        "execution_status": _section(execution_status, execution_status_data, section="execution_status", sequence=sequence),
        "data_status": _section(
            {
                "source": "trader_snapshot_aggregate",
                "source_type": "api",
                "endpoint": "/api/v2/trader/snapshot",
                "timestamp": _utc_now(),
                "received_at": _utc_now(),
                "lag_ms": 0,
                "stale": False,
                "missing_fields": [],
                "warnings": ["Snapshot is read-only and scoped to backend-authenticated trader"],
            },
            {
                "sections": list(SNAPSHOT_SECTIONS),
                "trader_id": actor.get("trader_id"),
                "paper_account_id": actor.get("paper_account_id"),
                "live_trading_enabled": False,
                "exchange_mutation_enabled": False,
            },
            section="data_status",
            sequence=sequence,
        ),
    }
    all_missing = sorted(
        {
            field
            for section in snapshot.values()
            for field in section["meta"].get("missing_fields", [])
        }
    )
    return {
        "data": snapshot,
        "source": "trader_snapshot_aggregate",
        "source_type": "api",
        "endpoint": "/api/v2/trader/snapshot",
        "timestamp": _utc_now(),
        "received_at": _utc_now(),
        "lag_ms": 0,
        "stale": False,
        "missing_fields": all_missing,
        "warnings": [
            "Authenticated trader snapshot is read-only",
            "No frontend-supplied trader ID is accepted",
            "Live execution remains blocked",
        ],
        "mode": "read_only",
        "trader_context": {
            "scope": "authenticated_trader",
            "trader_id": actor.get("trader_id"),
            "paper_account_id": actor.get("paper_account_id"),
            "username": actor.get("username"),
            "account_specific": bool(actor.get("trader_id") and actor.get("paper_account_id")),
        },
    }


@router.get("/trader/snapshot/health")
async def get_trader_snapshot_health(actor: UserRecord = Depends(require_auth)) -> dict[str, Any]:
    snapshot = await get_trader_snapshot(actor)
    data = _dict(snapshot.get("data"))
    section_health = {
        section: {
            "freshness": _dict(value).get("meta", {}).get("freshness"),
            "quality": _dict(value).get("meta", {}).get("quality"),
            "missing_fields": _dict(value).get("meta", {}).get("missing_fields", []),
        }
        for section, value in data.items()
    }
    release_blockers = [
        section
        for section, health in section_health.items()
        if health.get("quality") in {"missing", "invalid"} or health.get("freshness") == "offline"
    ]
    return {
        "data": {
            "status": "degraded" if release_blockers else "ok",
            "sections": section_health,
            "release_blockers": release_blockers,
            "live_trading_enabled": False,
            "exchange_mutation_enabled": False,
        },
        "source": "trader_snapshot_aggregate",
        "source_type": "api",
        "endpoint": "/api/v2/trader/snapshot/health",
        "timestamp": _utc_now(),
        "received_at": _utc_now(),
        "lag_ms": 0,
        "stale": False,
        "missing_fields": release_blockers,
        "warnings": ["Snapshot health is read-only and scoped to backend-authenticated trader"],
        "mode": "read_only",
    }
