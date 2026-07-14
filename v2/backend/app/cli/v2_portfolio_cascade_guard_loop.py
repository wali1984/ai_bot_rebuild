"""Portfolio cascade guard — paper-only protect-and-ride control loop.

Operator directive (2026-07-14): market-maker bots pump/dump single alts
10%-10x in minutes and reverse; in the legacy bot one such move cascaded a
cross-margin liquidation of the whole portfolio. This worker closes the wiring
gap found in the defense audit: the detection engines (cascade context) and the
portfolio shock math (cross_margin_liquidation) existed but fed dashboards only.

Every cycle it:
1. reads open paper positions (``v2:paper:positions``),
2. reads the live cascade-context states for those symbols (1m + 5m),
3. builds the portfolio liquidation snapshot (correlated BTC shock scenarios),
4. emits per-symbol PAPER directives to ``v2:paper:portfolio_cascade_guard``:
   - ``CLOSE``  — confirmed cascade on an open symbol while the position is
     LOSING (protect: never let one coin's move eat the book), or any losing
     position when the worst-case correlated shock breaches liquidation.
   - ``RIDE_TIGHTEN`` — confirmed cascade while the position is WINNING: do
     NOT close (ride the move); the paper exit engine's trailing/sweep-reversal
     stops handle the reversal.
The paper lifecycle honors CLOSE directives as a TIER_0 exit.

Paper-only by construction: no orders, no leverage/margin mutation, no live
routing. Writes only the single guard status key.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from typing import Any

from v2.backend.app.services.risk.cross_margin_liquidation import (
    build_portfolio_liquidation_snapshot,
)

GUARD_KEY = "v2:paper:portfolio_cascade_guard"
CASCADE_PREFIX = "v2:microstructure:cascade_context:"
CASCADE_TIMEFRAMES = ("1m", "5m")
CASCADE_CLOSE_STATUSES = {"EVENT_CONFIRMED"}
CASCADE_RISK_CLOSE_SCORE = 0.75
GUARD_TTL_SECONDS = 180


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _f(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _redis_client():
    from redis import Redis  # noqa: PLC0415

    return Redis(host="127.0.0.1", port=6379, decode_responses=True)


def _get_json(r: Any, key: str) -> Any:
    try:
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _open_positions(r: Any) -> list[dict[str, Any]]:
    payload = _get_json(r, "v2:paper:positions")
    rows = payload.get("positions") if isinstance(payload, dict) else payload
    return [row for row in (rows or []) if isinstance(row, dict)]


def _cascade_state(r: Any, symbol: str) -> dict[str, Any]:
    """Worst cascade state across the fast timeframes for one symbol."""
    worst: dict[str, Any] = {"status": None, "score": None, "timeframe": None}
    for timeframe in CASCADE_TIMEFRAMES:
        ctx = _get_json(r, f"{CASCADE_PREFIX}{symbol}:{timeframe}")
        if not isinstance(ctx, dict):
            continue
        score = _f(ctx.get("cascade_risk_score")) or 0.0
        status = str(ctx.get("cascade_context_status") or "")
        if worst["score"] is None or score > worst["score"]:
            worst = {"status": status, "score": score, "timeframe": timeframe}
    return worst


def decide_directives(
    positions: list[dict[str, Any]],
    cascade_by_symbol: dict[str, dict[str, Any]],
    portfolio_snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    """Pure decision core (unit-tested): positions + cascade + shock -> directives."""
    directives: list[dict[str, Any]] = []
    worst_breached = bool(portfolio_snapshot.get("worst_case_liquidation_breached"))
    for row in positions:
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        pnl_bps = _f(row.get("unrealized_pnl_bps"))
        if pnl_bps is None:
            pnl_usd = _f(row.get("unrealized_pnl_usd")) or 0.0
            notional = _f(row.get("gross_notional_usd")) or 0.0
            pnl_bps = (pnl_usd / notional * 10000.0) if notional else 0.0
        cascade = cascade_by_symbol.get(symbol) or {}
        cascade_active = (
            str(cascade.get("status") or "") in CASCADE_CLOSE_STATUSES
            or (_f(cascade.get("score")) or 0.0) >= CASCADE_RISK_CLOSE_SCORE
        )
        losing = pnl_bps <= 0.0
        if cascade_active and losing:
            action, reason = "CLOSE", "CASCADE_CONFIRMED_ON_LOSING_POSITION"
        elif cascade_active:
            # Winning through the move: ride it; trailing/sweep-reversal exits
            # own the reversal. Never be the move's counterparty by panic-closing
            # a winner, never hold a loser through a cascade.
            action, reason = "RIDE_TIGHTEN", "CASCADE_CONFIRMED_POSITION_WINNING"
        elif worst_breached and losing:
            action, reason = "CLOSE", "PORTFOLIO_WORST_CASE_LIQUIDATION_BREACH"
        else:
            continue
        directives.append(
            {
                "symbol": symbol,
                "action": action,
                "reason": reason,
                "cascade_status": cascade.get("status"),
                "cascade_score": cascade.get("score"),
                "cascade_timeframe": cascade.get("timeframe"),
                "unrealized_pnl_bps": round(pnl_bps, 4),
            }
        )
    return directives


def run_once(r: Any) -> dict[str, Any]:
    positions = _open_positions(r)
    cascade_by_symbol = {
        str(row.get("symbol") or "").upper(): _cascade_state(r, str(row.get("symbol") or "").upper())
        for row in positions
    }
    snapshot: dict[str, Any] = {}
    if positions:
        ledger = _get_json(r, "v2:paper:ledger") or {}
        account = {
            "wallet_balance": _f(ledger.get("paper_equity_usd"))
            or _f(ledger.get("starting_equity_usd"))
            or 0.0,
        }
        try:
            snapshot = build_portfolio_liquidation_snapshot(
                account=account, positions=positions, generated_utc=_utc_now()
            ) or {}
        except Exception as exc:  # snapshot is advisory; guard must not die on it
            snapshot = {"error": str(exc)[:120]}
    payload = {
        "schema_version": "portfolio_cascade_guard_v1",
        "generated_utc": _utc_now(),
        "open_position_count": len(positions),
        "directives": decide_directives(positions, cascade_by_symbol, snapshot),
        "cascade_by_symbol": cascade_by_symbol,
        "worst_case_liquidation_breached": bool(snapshot.get("worst_case_liquidation_breached")),
        "worst_case_liquidation_buffer_usd": snapshot.get("worst_case_liquidation_buffer_usd"),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }
    try:
        r.set(GUARD_KEY, json.dumps(payload, default=str), ex=GUARD_TTL_SECONDS)
    except Exception:
        pass
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=20)
    args = parser.parse_args(argv)
    r = _redis_client()
    while True:
        payload = run_once(r)
        if args.once:
            print(json.dumps(payload, indent=1, default=str)[:1500])
            return 0
        time.sleep(max(5, int(args.interval_seconds)))


if __name__ == "__main__":
    raise SystemExit(main())
