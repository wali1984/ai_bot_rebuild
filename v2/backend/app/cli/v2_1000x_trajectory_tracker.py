"""1000x-in-90-days trajectory tracker (TASK 3, 2026-07-17).

Publishes an honest, always-fresh view of where paper equity stands
against the operator's aspirational 1000x/90d research objective, and —
critically — WHICH constraint is currently binding, derived from live
runtime state (never guessed).

Research objective, not a promise (CLAUDE.md Performance Objective):
survival and auditability outrank growth. This tracker changes no
behavior; it makes the gap and its binding constraint visible.

Writes: v2:goal:trajectory_1000x
Paper-only. Never places orders. Never touches live trading.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import time
from typing import Any

import redis

from v2.backend.app.services.paper_session.epoch import (
    EPOCH_POINTER_KEY,
    LEGACY_SESSION_KEY,
    PORTFOLIO_STATE_KEY,
    scope_rows,
)

REDIS_URL = "redis://127.0.0.1:6379/0"
OUT_KEY = "v2:goal:trajectory_1000x"
TARGET_MULTIPLE = 1000.0
TARGET_DAYS = 90.0
# 1000^(1/90) - 1
REQUIRED_DAILY_RATE = TARGET_MULTIPLE ** (1.0 / TARGET_DAYS) - 1.0

A_PLUS_TRUST_BAR = 0.60


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(ts: dt.datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _get_json(r: Any, key: str) -> Any:
    try:
        raw = r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _session_start(session_id: str) -> dt.datetime | None:
    # Legacy fallback only, e.g. paper_3000_final_pre_live_20260713T190904Z.
    # Post-rotation ids are hash-suffixed (paper_session_<digest>) and carry
    # no timestamp; those sessions anchor on the epoch pointer instead.
    token = session_id.rsplit("_", 1)[-1]
    try:
        return dt.datetime.strptime(token, "%Y%m%dT%H%M%SZ").replace(
            tzinfo=dt.timezone.utc
        )
    except Exception:
        return None


def _parse_iso_utc(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _session_anchor(r: Any, ledger: dict[str, Any]) -> dict[str, Any]:
    """Authoritative session identity + day-0 anchor for the 90-day horizon.

    Precedence: PaperAccountEpochV1 pointer (started_at written atomically at
    rotation) -> legacy v2:paper:session (started_at field) -> ledger session
    id with the legacy timestamp-suffix parse. Never guesses: a missing
    anchor yields started_at=None and the payload reports days_elapsed=null
    with the source recorded.
    """
    pointer = _get_json(r, EPOCH_POINTER_KEY)
    if isinstance(pointer, dict) and pointer.get("paper_session_id"):
        return {
            "paper_session_id": str(pointer.get("paper_session_id")),
            "paper_account_epoch": pointer.get("paper_account_epoch"),
            "starting_equity_usd": _coerce_float(
                pointer.get("starting_equity_usd")
            ),
            "started_at": _parse_iso_utc(pointer.get("started_at")),
            "anchor_source": f"redis:{EPOCH_POINTER_KEY}",
        }
    legacy = _get_json(r, LEGACY_SESSION_KEY)
    if isinstance(legacy, dict) and legacy.get("paper_session_id"):
        session_id = str(legacy.get("paper_session_id"))
        return {
            "paper_session_id": session_id,
            "paper_account_epoch": legacy.get("paper_account_epoch"),
            "starting_equity_usd": _coerce_float(
                legacy.get("starting_equity_usd")
                if legacy.get("starting_equity_usd") is not None
                else legacy.get("initial_capital")
            ),
            "started_at": (
                _parse_iso_utc(legacy.get("started_at"))
                or _session_start(session_id)
            ),
            "anchor_source": f"redis:{LEGACY_SESSION_KEY}",
        }
    session_id = str(ledger.get("paper_session_id") or "")
    return {
        "paper_session_id": session_id or None,
        "paper_account_epoch": ledger.get("paper_account_epoch"),
        "starting_equity_usd": _coerce_float(ledger.get("starting_equity_usd")),
        "started_at": _session_start(session_id) if session_id else None,
        "anchor_source": "redis:v2:paper:ledger",
    }


def _latest_terminal_outcome_projection(
    closed: list[Any],
) -> dict[str, Any] | None:
    """Newest current-session close carrying the per-outcome terminal
    projection stamped by the outcome pipeline (requirement: publish the
    terminal-equity distribution after every completed outcome). Mirrored
    verbatim — this tracker computes no probabilities of its own."""
    newest: dict[str, Any] | None = None
    newest_stamp = ""
    for row in closed:
        if not isinstance(row, dict):
            continue
        projection = row.get("terminal_equity_after_completed_outcome")
        if not isinstance(projection, dict):
            continue
        stamp = str(
            row.get("exit_price_utc")
            or row.get("closed_utc")
            or row.get("exit_time_utc")
            or ""
        )
        if newest is None or stamp >= newest_stamp:
            newest = {
                "close_trade_id": row.get("trade_id")
                or row.get("close_id")
                or row.get("id"),
                "close_stamp_utc": stamp or None,
                "terminal_equity_after_completed_outcome": projection,
                "terminal_target_probability": row.get(
                    "terminal_target_probability"
                ),
                "terminal_equity_distribution_usd": row.get(
                    "terminal_equity_distribution_usd"
                ),
            }
            newest_stamp = stamp
    return newest


def _binding_constraint(r: Any) -> dict[str, Any]:
    """Derive the single most upstream live blocker, with raw evidence."""
    circuit = _get_json(r, "v2:paper:performance_circuit_breaker_status") or {}
    if circuit.get("new_entries_allowed") is not True:
        return {
            "constraint": "PERFORMANCE_CIRCUIT_HALTED",
            "detail": (
                "entry circuit halted on negative rolling evidence; probe "
                "lane is generating the closes that can clear it"
            ),
            "evidence": {
                "block_reasons": circuit.get("block_reasons"),
                "key": "v2:paper:performance_circuit_breaker_status",
            },
        }
    trust = _get_json(r, "v2:microstructure:trust_score:BTCUSDT:1m") or {}
    composite = _coerce_float(trust.get("composite_microstructure_trust_score"))
    if composite is not None and composite < A_PLUS_TRUST_BAR:
        return {
            "constraint": "MICROSTRUCTURE_TRUST_BELOW_A_PLUS_BAR",
            "detail": (
                f"composite {composite:.2f} < {A_PLUS_TRUST_BAR:.2f} — A+ lane "
                "cannot confirm candidates yet"
            ),
            "evidence": {
                "composite": composite,
                "key": "v2:microstructure:trust_score:BTCUSDT:1m",
            },
        }
    cc = _get_json(r, "v2:trainer:champion_challenger_status") or {}
    if cc.get("promotion_allowed") is not True:
        return {
            "constraint": "CHALLENGER_AWAITING_RUNTIME_EVIDENCE",
            "detail": str(cc.get("promotion_reason") or "")[:160],
            "evidence": {
                "best_challenger_id": cc.get("best_challenger_id"),
                "paper_opportunity_tier": cc.get("paper_opportunity_tier"),
                "key": "v2:trainer:champion_challenger_status",
            },
        }
    a_plus = _get_json(r, "v2:paper:a_plus_gate:status") or {}
    matrix = a_plus.get("rejected_reason_matrix") or {}
    if matrix:
        top = max(matrix.items(), key=lambda kv: kv[1])
        return {
            "constraint": "A_PLUS_CHECKS_REJECTING",
            "detail": f"top rejector: {top[0]} ({top[1]} candidates)",
            "evidence": {
                "rejected_reason_matrix": matrix,
                "key": "v2:paper:a_plus_gate:status",
            },
        }
    return {
        "constraint": "COMPOUNDING_WITHIN_ENVELOPE",
        "detail": "no upstream blocker detected; growth bound by risk envelope",
        "evidence": {},
    }


def _growth_stage(r: Any, closed: list[Any]) -> dict[str, Any]:
    """Which stage of the staged 1000x path the system currently occupies.

    The daily rate decomposes as
        daily% ~= trades/day x net_bps/trade x (avg_notional/equity) / 100
    so the stages are strictly ordered — scaling size or leverage before
    edge is positive only scales losses (proven 2026-07-17: the largest
    fills were the largest losers).

    1. EDGE_REPAIR      exit: rolling-25 PF >= 1.2 AND notional-weighted
                        expectancy > 0 (challenger promotion + calibration
                        recovery drive this; nothing else matters first).
    2. THROUGHPUT       exit: >= 15 closed outcomes/day sustained with
                        stage-1 criteria still holding.
    3. SCALE            exit: dynamic envelope combined factor > 2 (WR/PF
                        exponential scaling engaged) with hedge-aware
                        sizing amplification active on >= half of fills.
    4. COMPOUND         steady state: the formula above at ~8%/day; the
                        envelope, ladder, and hedge amplification carry
                        sizing to multiples of equity as evidence allows.
    """
    recent = [row for row in closed[-25:] if isinstance(row, dict)]
    gains = sum(
        _coerce_float(row.get("realized_net_pnl_usd")) or 0.0
        for row in recent
        if (_coerce_float(row.get("realized_net_pnl_usd")) or 0.0) > 0
    )
    losses = abs(
        sum(
            _coerce_float(row.get("realized_net_pnl_usd")) or 0.0
            for row in recent
            if (_coerce_float(row.get("realized_net_pnl_usd")) or 0.0) < 0
        )
    )
    pf25 = (gains / losses) if losses > 0 else (99.0 if gains > 0 else 0.0)
    weighted_num = 0.0
    weighted_den = 0.0
    for row in recent:
        notional = _coerce_float(row.get("gross_notional_usd")) or 0.0
        bps = _coerce_float(row.get("realized_net_pnl_bps")) or 0.0
        weighted_num += notional * bps
        weighted_den += notional
    weighted_bps = (weighted_num / weighted_den) if weighted_den > 0 else 0.0
    now = _utc_now()
    closes_24h = sum(
        1
        for row in closed
        if isinstance(row, dict)
        and str(row.get("exit_price_utc") or "")
        > (now - dt.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    stage = "EDGE_REPAIR"
    if pf25 >= 1.2 and weighted_bps > 0:
        stage = "THROUGHPUT"
        if closes_24h >= 15:
            stage = "SCALE"
    return {
        "stage": stage,
        "stage_order": ["EDGE_REPAIR", "THROUGHPUT", "SCALE", "COMPOUND"],
        "rolling_25_pf": round(pf25, 3),
        "rolling_25_weighted_bps": round(weighted_bps, 3),
        "closes_24h": closes_24h,
        "edge_repair_exit": "PF25 >= 1.2 AND weighted expectancy > 0",
        "throughput_exit": ">= 15 closes/day with edge criteria holding",
        "scale_exit": "envelope factor > 2 with hedge-aware sizing active",
        "rate_formula": (
            "daily% ~= trades/day x net_bps x (avg_notional/equity) / 100; "
            "8%/day ~= 20 trades x 20bps x 2.0x deployed"
        ),
    }


def run_once() -> dict[str, Any]:
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    now = _utc_now()
    ledger = _get_json(r, "v2:paper:ledger") or {}
    positions = _get_json(r, "v2:paper:positions") or []
    closed_all = _get_json(r, "v2:paper:closed_trades") or []

    anchor = _session_anchor(r, ledger)
    session_id = anchor["paper_session_id"] or ""
    # Current-session accounting only: post-rotation the global closed-trades
    # history preserves archived sessions, and summing them re-mixed archived
    # PnL into the live $3000 face (observed live as days_elapsed=null with
    # blended equity). Rows without a session stamp are pre-rotation legacy
    # and only count when no rotation pointer exists.
    if session_id:
        closed = scope_rows(closed_all, session_id, "current_session")
        session_scope = "current_session"
    else:
        closed = [row for row in closed_all if isinstance(row, dict)]
        session_scope = "all_unscoped_no_session_anchor"

    starting = (
        anchor["starting_equity_usd"]
        or _coerce_float(ledger.get("starting_equity_usd"))
        or 3000.0
    )
    realized = sum(
        _coerce_float(row.get("realized_net_pnl_usd")) or 0.0
        for row in closed
        if isinstance(row, dict)
    )
    unrealized = sum(
        _coerce_float(row.get("unrealized_pnl")) or 0.0
        for row in positions
        if isinstance(row, dict)
    )
    equity = starting + realized + unrealized
    equity_source = "session_scoped_recompute"
    # Prefer the authoritative portfolio publisher when it describes the SAME
    # session (it recomputes equity from scratch with reconciliation flags).
    portfolio = _get_json(r, PORTFOLIO_STATE_KEY) or {}
    portfolio_equity = _coerce_float(portfolio.get("equity_usd"))
    if (
        portfolio_equity is not None
        and session_id
        and str(portfolio.get("paper_session_id") or "") == session_id
    ):
        equity = portfolio_equity
        equity_source = f"redis:{PORTFOLIO_STATE_KEY}"

    started = anchor["started_at"]
    days_elapsed = (
        max(0.0001, (now - started).total_seconds() / 86400.0) if started else None
    )
    multiple_now = equity / starting if starting > 0 else None
    actual_daily_rate = (
        (multiple_now ** (1.0 / days_elapsed) - 1.0)
        if multiple_now is not None and multiple_now > 0 and days_elapsed
        else None
    )
    required_equity_today = (
        starting * ((1.0 + REQUIRED_DAILY_RATE) ** days_elapsed)
        if days_elapsed is not None
        else None
    )
    # Days needed at the required rate to reach 1000x from CURRENT equity
    days_remaining_at_required = (
        math.log(TARGET_MULTIPLE / multiple_now)
        / math.log(1.0 + REQUIRED_DAILY_RATE)
        if multiple_now is not None and 0 < multiple_now < TARGET_MULTIPLE
        else None
    )

    remaining_days = (
        max(0.0, TARGET_DAYS - days_elapsed) if days_elapsed is not None else None
    )
    latest_terminal = _latest_terminal_outcome_projection(closed)

    payload: dict[str, Any] = {
        "schema_version": "v2_goal_trajectory_1000x_v1",
        "generated_utc": _iso(now),
        "objective": "1000x_in_90_days_research_objective_not_a_promise",
        "paper_session_id": session_id or None,
        "paper_account_epoch": anchor["paper_account_epoch"],
        "session_scope": session_scope,
        "session_anchor_source": anchor["anchor_source"],
        "equity_source": equity_source,
        "session_started_utc": _iso(started) if started else None,
        "days_elapsed": round(days_elapsed, 3) if days_elapsed else None,
        "remaining_days_to_target": (
            round(remaining_days, 3) if remaining_days is not None else None
        ),
        "target_equity_usd": round(starting * TARGET_MULTIPLE, 2),
        "latest_outcome_terminal_projection": latest_terminal,
        "terminal_projection_note": (
            None
            if latest_terminal is not None
            else (
                "NO_CURRENT_SESSION_CLOSE_CARRIES_TERMINAL_PROJECTION_YET"
            )
        ),
        "target_guaranteed": False,
        "starting_equity_usd": round(starting, 2),
        "equity_usd": round(equity, 4),
        "realized_pnl_usd": round(realized, 4),
        "unrealized_pnl_usd": round(unrealized, 4),
        "multiple_now": round(multiple_now, 6) if multiple_now else None,
        "target_multiple": TARGET_MULTIPLE,
        "target_days": TARGET_DAYS,
        "required_daily_rate_pct": round(REQUIRED_DAILY_RATE * 100.0, 3),
        "actual_daily_rate_pct": (
            round(actual_daily_rate * 100.0, 4)
            if actual_daily_rate is not None
            else None
        ),
        "on_track": (
            actual_daily_rate is not None
            and actual_daily_rate >= REQUIRED_DAILY_RATE
        ),
        "required_equity_today_usd": (
            round(required_equity_today, 2)
            if required_equity_today is not None
            else None
        ),
        "equity_gap_vs_required_usd": (
            round(equity - required_equity_today, 2)
            if required_equity_today is not None
            else None
        ),
        "days_to_target_at_required_rate_from_here": (
            round(days_remaining_at_required, 1)
            if days_remaining_at_required is not None
            else None
        ),
        "binding_constraint": _binding_constraint(r),
        "growth_stage": _growth_stage(r, closed),
        "open_position_count": len(positions),
        "closed_trade_count": len(closed),
        "historical_closed_trade_count": len(closed_all),
        "historical_rows_excluded_from_current_view": max(
            0, len(closed_all) - len(closed)
        ),
        "paper_only": True,
        "places_real_order": False,
        "routes_to_live": False,
        "live_gate": "blocked_human_only",
    }
    r.set(OUT_KEY, json.dumps(payload, sort_keys=True), ex=1800)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(prog="v2_1000x_trajectory_tracker")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    args = parser.parse_args()
    if args.loop:
        while True:
            try:
                payload = run_once()
                print(
                    json.dumps(
                        {
                            "generated_utc": payload["generated_utc"],
                            "equity_usd": payload["equity_usd"],
                            "multiple_now": payload["multiple_now"],
                            "on_track": payload["on_track"],
                            "binding_constraint": payload["binding_constraint"][
                                "constraint"
                            ],
                        }
                    ),
                    flush=True,
                )
            except Exception as exc:  # keep the loop alive on transient errors
                print(json.dumps({"error": str(exc)[:200]}), flush=True)
            time.sleep(max(30, args.interval_seconds))
    print(json.dumps(run_once(), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
