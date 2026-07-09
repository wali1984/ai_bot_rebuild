"""Canonical paper PnL projection for web, iOS, and UI snapshots.

The service is intentionally read-only. It reads current V2 Redis materialized
state and returns one compact USD-first contract. It does not call exchanges,
place orders, mutate account state, or write Redis.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Mapping
from zoneinfo import ZoneInfo

DISPLAY_TZ = ZoneInfo("America/New_York")
CANONICAL_KEYS = (
    "v2:portfolio:state",
    "v2:paper:session",
    "v2:paper:ledger",
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _display_time_et() -> str:
    return datetime.now(DISPLAY_TZ).isoformat(timespec="seconds")


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _source_lag_seconds(payloads: list[Mapping[str, Any]]) -> float | None:
    timestamps: list[datetime] = []
    for payload in payloads:
        for key in ("generated_utc", "generated_at", "updated_at", "timestamp"):
            parsed = _parse_ts(payload.get(key))
            if parsed is not None:
                timestamps.append(parsed)
                break
    if not timestamps:
        return None
    newest = max(timestamps)
    return round(max(0.0, (datetime.now(UTC) - newest).total_seconds()), 3)


def _json_object(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_key(client: Any, key: str) -> dict[str, Any]:
    if client is None:
        return {}
    try:
        return _json_object(client.get(key))
    except Exception:
        return {}


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or abs(parsed) == float("inf"):
        return None
    return parsed


def _integer(value: Any) -> int | None:
    parsed = _num(value)
    if parsed is None:
        return None
    return int(parsed)


def _first(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _money(value: Any) -> float | None:
    parsed = _num(value)
    if parsed is None:
        return None
    return round(parsed, 4)


def _fee_total(*values: Any) -> float:
    return round(sum(_num(value) or 0.0 for value in values), 4)


def build_canonical_pnl(client: Any) -> dict[str, Any]:
    """Build the canonical USD-first PnL payload from current V2 Redis state."""

    portfolio = _read_key(client, "v2:portfolio:state")
    session = _read_key(client, "v2:paper:session")
    ledger = _read_key(client, "v2:paper:ledger")
    present_sources = [
        key for key, payload in (
            ("v2:portfolio:state", portfolio),
            ("v2:paper:session", session),
            ("v2:paper:ledger", ledger),
        )
        if payload
    ]

    starting_equity = _money(_first(
        session.get("starting_equity_usd"),
        portfolio.get("starting_equity_usd"),
        portfolio.get("initial_capital"),
        ledger.get("starting_equity_usd"),
        ledger.get("initial_capital"),
    ))
    realized_net = _money(_first(
        portfolio.get("realized_net_pnl_usd"),
        portfolio.get("clean_session_valid_realized_pnl_usd"),
        portfolio.get("realized_pnl_usd"),
        portfolio.get("realized_pnl"),
        ledger.get("realized_net_pnl_usd"),
        ledger.get("realized_pnl_usd"),
    ))
    unrealized = _money(_first(
        portfolio.get("unrealized_pnl_usd"),
        portfolio.get("net_unrealized_pnl"),
        portfolio.get("unrealized_pnl"),
        ledger.get("unrealized_pnl_usd"),
    ))
    fees = _fee_total(
        portfolio.get("fees_usd"),
        ledger.get("fees_usd"),
        ledger.get("commission_usd"),
    )
    slippage = _fee_total(portfolio.get("slippage_usd"), ledger.get("slippage_usd"))
    funding = _fee_total(portfolio.get("funding_usd"), ledger.get("funding_usd"))
    gross_pnl = _money(_first(
        portfolio.get("gross_pnl_usd"),
        portfolio.get("realized_gross_pnl_usd"),
        ledger.get("gross_pnl_usd"),
    ))
    net_pnl = _money(_first(
        portfolio.get("total_pnl_usd"),
        portfolio.get("net_pnl_usd"),
        (realized_net + (unrealized or 0.0)) if realized_net is not None else None,
    ))
    equity = _money(_first(
        portfolio.get("equity"),
        portfolio.get("paper_equity"),
        (starting_equity + (net_pnl or 0.0)) if starting_equity is not None else None,
    ))
    closed_trade_count = _integer(_first(
        portfolio.get("closed_trade_count"),
        portfolio.get("closed_positions_count"),
        ledger.get("closed_trade_count"),
    ))
    session_id = _first(
        session.get("paper_session_id"),
        portfolio.get("paper_session_id"),
        ledger.get("paper_session_id"),
        session.get("session_id"),
        portfolio.get("session_id"),
        ledger.get("session_id"),
    )

    missing_fields = [
        field for field, value in (
            ("equity_usd", equity),
            ("starting_equity_usd", starting_equity),
            ("realized_net_pnl_usd", realized_net),
            ("unrealized_pnl_usd", unrealized),
        )
        if value is None
    ]
    reconciliation_status = "PASS"
    reconciliation_delta_usd: float | None = None
    if equity is None or starting_equity is None or net_pnl is None:
        reconciliation_status = "PARTIAL"
    else:
        reconciliation_delta_usd = round(equity - (starting_equity + net_pnl), 4)
        if abs(reconciliation_delta_usd) > 0.01:
            reconciliation_status = "FAIL"

    return {
        "schema_version": "canonical_pnl_v1",
        "generated_utc": _utc_now(),
        "display_time_et": _display_time_et(),
        "source_timezone": "UTC",
        "display_timezone": "America/New_York",
        "paper_session_id": session_id,
        "account_scope": "paper",
        "equity_usd": equity,
        "starting_equity_usd": starting_equity,
        "realized_net_pnl_usd": realized_net,
        "unrealized_pnl_usd": unrealized,
        "fees_usd": fees,
        "slippage_usd": slippage,
        "funding_usd": funding,
        "gross_pnl_usd": gross_pnl,
        "net_pnl_usd": net_pnl,
        "closed_trade_count": closed_trade_count or 0,
        "source": "+".join(present_sources) if present_sources else "unavailable",
        "source_keys": present_sources,
        "source_lag_seconds": _source_lag_seconds([p for p in (portfolio, session, ledger) if p]),
        "reconciliation_status": reconciliation_status,
        "reconciliation_delta_usd": reconciliation_delta_usd,
        "missing_fields": missing_fields,
        "warnings": (
            ["Canonical PnL source missing required current-session fields"]
            if missing_fields else []
        ),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
