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
from collections.abc import Mapping
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
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _redis_client():
    from redis import Redis  # noqa: PLC0415

    return Redis(host="127.0.0.1", port=6379, decode_responses=True)


def _get_json(r: Any, key: str) -> Any:
    try:
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _open_position_inputs(r: Any) -> tuple[list[Any], list[str]]:
    try:
        raw = r.get("v2:paper:positions")
    except Exception:
        return [], ["POSITION_COLLECTION_READ_FAILED"]
    if raw in (None, ""):
        return [], []
    try:
        payload = json.loads(raw) if isinstance(raw, str | bytes | bytearray) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        return [], ["POSITION_COLLECTION_JSON_INVALID"]
    if isinstance(payload, dict):
        if "positions" not in payload:
            return [], ["POSITION_COLLECTION_MISSING"]
        rows = payload.get("positions")
    else:
        rows = payload
    if not isinstance(rows, list):
        return [], ["POSITION_COLLECTION_NOT_LIST"]
    return list(rows), []


def _paper_margin_inputs(
    positions: list[dict[str, Any]],
    ledger: Mapping[str, Any],
    *,
    expected_position_count: int | None = None,
    input_rejection_reasons: tuple[str, ...] = (),
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    """Join canonical paper position rows to audited margin-accounting rows."""

    margin_status = ledger.get("paper_account_margin_status")
    margin_status = margin_status if isinstance(margin_status, Mapping) else {}
    margin_rows = margin_status.get("position_margin_rows")
    margin_rows = margin_rows if isinstance(margin_rows, list) else []
    by_symbol: dict[str, dict[str, Any]] = {}
    duplicate_symbols: set[str] = set()
    for row in margin_rows:
        if not isinstance(row, Mapping):
            continue
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        if symbol in by_symbol:
            duplicate_symbols.add(symbol)
            continue
        by_symbol[symbol] = dict(row)

    enriched: list[dict[str, Any]] = []
    rejection_reasons: list[str] = list(input_rejection_reasons)
    maintenance_margin_usd = 0.0
    for position in positions:
        symbol = str(position.get("symbol") or "").upper()
        margin_row = by_symbol.get(symbol)
        if margin_row is None:
            rejection_reasons.append(f"MARGIN_ROW_MISSING:{symbol or 'UNKNOWN'}")
            continue
        rate = _f(margin_row.get("maintenance_margin_rate"))
        notional = _f(margin_row.get("canonical_notional_usd"))
        leverage = _f(margin_row.get("effective_leverage"))
        if margin_row.get("valid") is not True:
            rejection_reasons.append(f"MARGIN_ROW_INVALID:{symbol}")
            continue
        if margin_row.get("maintenance_margin_evidence_valid") is not True:
            rejection_reasons.append(f"MAINTENANCE_MARGIN_EVIDENCE_INVALID:{symbol}")
            continue
        if rate is None or rate <= 0.0 or notional is None or notional <= 0.0:
            rejection_reasons.append(f"MARGIN_ROW_NUMERIC_EVIDENCE_INVALID:{symbol}")
            continue
        if leverage is None or leverage < 1.0:
            rejection_reasons.append(f"LEVERAGE_EVIDENCE_INVALID:{symbol}")
            continue
        joined = dict(position)
        joined["maintenance_margin_rate"] = rate
        joined["effective_leverage"] = leverage
        joined["cascade_margin_row_id"] = margin_row.get("row_id")
        joined["cascade_margin_rate_source"] = margin_row.get("maintenance_margin_rate_source")
        enriched.append(joined)
        maintenance_margin_usd += notional * rate

    if duplicate_symbols:
        rejection_reasons.extend(
            f"DUPLICATE_MARGIN_ROWS:{symbol}" for symbol in sorted(duplicate_symbols)
        )
    margin_base = _f(margin_status.get("margin_base_usd"))
    used_margin = _f(margin_status.get("used_margin_usd"))
    free_margin = _f(margin_status.get("free_margin_usd"))
    if margin_status.get("status") != "PASS":
        rejection_reasons.append("PAPER_MARGIN_STATUS_NOT_PASS")
    if margin_status.get("accounting_complete") is not True:
        rejection_reasons.append("PAPER_MARGIN_ACCOUNTING_INCOMPLETE")
    if margin_base is None or margin_base <= 0.0:
        rejection_reasons.append("PAPER_MARGIN_BASE_INVALID")
    if used_margin is None or used_margin < 0.0:
        rejection_reasons.append("PAPER_USED_MARGIN_INVALID")
    if free_margin is None or free_margin < 0.0:
        rejection_reasons.append("PAPER_FREE_MARGIN_INVALID")
    expected_count = (
        len(positions) if expected_position_count is None else expected_position_count
    )
    if len(positions) != expected_count:
        rejection_reasons.append("POSITION_INPUT_MAPPING_COUNT_MISMATCH")
    if len(enriched) != expected_count:
        rejection_reasons.append("POSITION_MARGIN_JOIN_INCOMPLETE")

    evidence_complete = not rejection_reasons
    account = {
        "totalWalletBalance": margin_base,
        "totalCrossWalletBalance": margin_base,
        "totalMarginBalance": margin_base,
        "totalInitialMargin": used_margin,
        "totalMaintMargin": maintenance_margin_usd,
        "availableBalance": free_margin,
    }
    evidence = {
        "schema_version": "paper_cascade_margin_join_v1",
        "status": "PASS" if evidence_complete else "BLOCKED",
        "position_count": expected_count,
        "mappable_position_count": len(positions),
        "joined_position_count": len(enriched),
        "margin_row_count": len(margin_rows),
        "maintenance_margin_usd": (
            round(maintenance_margin_usd, 8) if evidence_complete else None
        ),
        "calculated_maintenance_margin_usd": round(maintenance_margin_usd, 8),
        "rejection_reasons": sorted(set(rejection_reasons)),
    }
    return enriched, account, evidence


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
    worst_breached = (
        portfolio_snapshot.get("portfolio_level_computed") is True
        and portfolio_snapshot.get("worst_case_liquidation_breached") is True
    )
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
    position_inputs, position_input_rejections = _open_position_inputs(r)
    expected_position_count = len(position_inputs)
    positions: list[dict[str, Any]] = []
    for index, row in enumerate(position_inputs):
        if isinstance(row, Mapping):
            positions.append(dict(row))
        else:
            position_input_rejections.append(f"POSITION_ROW_NOT_MAPPING:{index}")
    cascade_by_symbol = {
        str(row.get("symbol") or "").upper(): _cascade_state(
            r, str(row.get("symbol") or "").upper()
        )
        for row in positions
    }
    snapshot: dict[str, Any] = {}
    margin_evidence: dict[str, Any] = {
        "schema_version": "paper_cascade_margin_join_v1",
        "status": "NOT_APPLICABLE_NO_OPEN_POSITIONS",
        "position_count": 0,
        "mappable_position_count": 0,
        "joined_position_count": 0,
        "margin_row_count": 0,
        "maintenance_margin_usd": None,
        "calculated_maintenance_margin_usd": 0.0,
        "rejection_reasons": [],
    }
    risk_applicable = expected_position_count > 0 or bool(position_input_rejections)
    if risk_applicable:
        ledger = _get_json(r, "v2:paper:ledger") or {}
        enriched_positions, account, margin_evidence = _paper_margin_inputs(
            positions,
            ledger if isinstance(ledger, Mapping) else {},
            expected_position_count=expected_position_count,
            input_rejection_reasons=tuple(position_input_rejections),
        )
        if margin_evidence["status"] == "PASS":
            try:
                snapshot = (
                    build_portfolio_liquidation_snapshot(
                        account=account,
                        positions=enriched_positions,
                        generated_utc=_utc_now(),
                    )
                    or {}
                )
            except Exception as exc:  # pure snapshot failure must be explicit
                snapshot = {
                    "portfolio_level_computed": False,
                    "error": str(exc)[:120],
                }
        else:
            snapshot = {
                "portfolio_level_computed": False,
                "risk_state": "UNTRUSTED_MARGIN_EVIDENCE",
            }
    computed_position_count = snapshot.get("computed_position_count")
    position_count_matches = (
        computed_position_count == expected_position_count
        if type(computed_position_count) is int
        else None
    )
    snapshot_breach = snapshot.get("worst_case_liquidation_breached")
    snapshot_authoritative = snapshot.get("portfolio_risk_result_authoritative") is True
    breach_conclusion_available = type(snapshot_breach) is bool
    portfolio_risk_authoritative = (
        risk_applicable
        and margin_evidence.get("status") == "PASS"
        and snapshot_authoritative
        and position_count_matches is True
        and breach_conclusion_available
    )
    portfolio_risk_block_reasons = list(margin_evidence.get("rejection_reasons") or [])
    portfolio_risk_block_reasons.extend(snapshot.get("portfolio_risk_block_reasons") or [])
    if risk_applicable and position_count_matches is False:
        portfolio_risk_block_reasons.append("POSITION_COUNT_MISMATCH")
    if (
        risk_applicable
        and margin_evidence.get("status") == "PASS"
        and snapshot_authoritative
        and not breach_conclusion_available
    ):
        portfolio_risk_block_reasons.append("PORTFOLIO_BREACH_CONCLUSION_UNKNOWN")
    if risk_applicable and not portfolio_risk_authoritative and not portfolio_risk_block_reasons:
        portfolio_risk_block_reasons.append("PORTFOLIO_RISK_SNAPSHOT_NOT_AUTHORITATIVE")
    portfolio_risk_block_reasons = list(dict.fromkeys(portfolio_risk_block_reasons))
    directive_snapshot = snapshot
    if not portfolio_risk_authoritative:
        directive_snapshot = {
            **snapshot,
            "portfolio_level_computed": False,
            "worst_case_liquidation_breached": None,
        }
    payload = {
        "schema_version": "portfolio_cascade_guard_v1",
        "generated_utc": _utc_now(),
        "open_position_count": expected_position_count,
        "portfolio_position_count_expected": expected_position_count,
        "portfolio_position_count_mappable": len(positions),
        "portfolio_position_count_computed": computed_position_count,
        "portfolio_position_count_matches": position_count_matches,
        "portfolio_level_computed": portfolio_risk_authoritative,
        "portfolio_risk_result_authoritative": portfolio_risk_authoritative,
        "portfolio_risk_computation_blocked": (
            risk_applicable and not portfolio_risk_authoritative
        ),
        "portfolio_risk_status": (
            "NOT_APPLICABLE_NO_OPEN_POSITIONS"
            if not risk_applicable
            else "PASS"
            if portfolio_risk_authoritative
            else "BLOCKED"
        ),
        "portfolio_risk_block_reasons": portfolio_risk_block_reasons,
        "portfolio_margin_evidence": margin_evidence,
        "maintenance_margin_evidence_complete": snapshot.get(
            "maintenance_margin_evidence_complete"
        ),
        "leverage_evidence_complete": snapshot.get("leverage_evidence_complete"),
        "position_count_evidence_complete": snapshot.get(
            "position_count_evidence_complete"
        ),
        "dropped_position_count": snapshot.get("dropped_position_count"),
        "dropped_positions": snapshot.get("dropped_positions"),
        "position_direction_evidence_complete": snapshot.get(
            "position_direction_evidence_complete"
        ),
        "position_direction_conflicts": snapshot.get("position_direction_conflicts"),
        "unrecognized_position_directions": snapshot.get(
            "unrecognized_position_directions"
        ),
        "account_dependency_evidence_complete": snapshot.get(
            "account_dependency_evidence_complete"
        ),
        "account_dependency_issues": snapshot.get("account_dependency_issues"),
        "maintenance_margin_fallback_symbols": snapshot.get(
            "maintenance_margin_fallback_symbols"
        ),
        "directives": decide_directives(positions, cascade_by_symbol, directive_snapshot),
        "cascade_by_symbol": cascade_by_symbol,
        "worst_case_liquidation_breached": (
            snapshot_breach if portfolio_risk_authoritative else None
        ),
        "worst_case_liquidation_buffer_usd": (
            snapshot.get("worst_case_liquidation_buffer_usd")
            if portfolio_risk_authoritative
            else None
        ),
        "calculated_worst_case_liquidation_breached": snapshot.get(
            "calculated_worst_case_liquidation_breached"
        ),
        "calculated_worst_case_liquidation_buffer_usd": snapshot.get(
            "calculated_worst_case_liquidation_buffer_usd"
        ),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }
    try:
        r.set(GUARD_KEY, json.dumps(payload, default=str), ex=GUARD_TTL_SECONDS)
    except Exception:  # noqa: S110 - paper-only telemetry remains best-effort
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
