"""Adaptive allocation and paper lifecycle 24h soak monitor.

This CLI is paper-only and observer-only. It reads V2 paper/adaptive runtime
payloads and optional V2 Redis paper keys, then emits soak evidence artifacts.
It never places orders, never calls test-order, never changes leverage/margin,
and never writes Redis.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[4]
SLUG = "v2_adaptive_allocation_and_trade_lifecycle_24h_paper_soak"
RUNTIME_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "operator_runtime" / SLUG / "latest"
PUBLIC_DIR = REPO_ROOT / "v2" / "frontend" / "public" / SLUG / "latest"
PAPER_RUNTIME_DIR = (
    REPO_ROOT / "v2" / "frontend" / "public" / "operator_runtime" / "v2_paper_trade_management" / "latest"
)
PORTFOLIO_STATE_DIR = (
    REPO_ROOT / "v2" / "frontend" / "public" / "operator_runtime" / "v2_portfolio_state" / "latest"
)
RUNTIME_TRUTH_DIR = (
    REPO_ROOT / "v2" / "frontend" / "public" / "operator_runtime" / "v2_runtime_truth" / "latest"
)
ADAPTIVE_GATE_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_adaptive_ai_capital_allocation_and_dynamic_risk_budget"
    / "latest"
)
PAPER_GATE_DIR = (
    REPO_ROOT
    / "v2"
    / "frontend"
    / "public"
    / "v2_paper_trade_management_exit_netting_risk_and_trainer_feedback"
    / "latest"
)
OBSERVATION_JSONL = "soak_observations.jsonl"
DEFAULT_SOAK_REQUIRED_SECONDS = 12 * 3600
DEFAULT_SOAK_WINDOW_HOURS = DEFAULT_SOAK_REQUIRED_SECONDS / 3600.0
SOAK_WINDOW_LABEL = "12h"
READY_GATE = "V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_12H_PAPER_SOAK_READY"
BLOCKED_GATE = "V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_12H_PAPER_SOAK_BLOCKED"
COMPLETE_READY_GATE = "V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_12H_PAPER_SOAK_COMPLETE_READY"
COMPLETE_BLOCKED_GATE = "V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_12H_PAPER_SOAK_COMPLETE_BLOCKED"
LOCAL_TZ = ZoneInfo("America/New_York")


def soak_window_label(required_seconds: int) -> str:
    hours = max(1, int(required_seconds)) / 3600.0
    if hours.is_integer():
        return f"{int(hours)}h"
    return f"{hours:g}h"


def _soak_gate_suffix(required_seconds: int) -> str:
    return soak_window_label(required_seconds).upper()


def ready_gate(required_seconds: int) -> str:
    return f"V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_{_soak_gate_suffix(required_seconds)}_PAPER_SOAK_READY"


def blocked_gate(required_seconds: int) -> str:
    return f"V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_{_soak_gate_suffix(required_seconds)}_PAPER_SOAK_BLOCKED"


def complete_ready_gate(required_seconds: int) -> str:
    return (
        f"V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_{_soak_gate_suffix(required_seconds)}_"
        "PAPER_SOAK_COMPLETE_READY"
    )


def complete_blocked_gate(required_seconds: int) -> str:
    return (
        f"V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_{_soak_gate_suffix(required_seconds)}_"
        "PAPER_SOAK_COMPLETE_BLOCKED"
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None = None) -> str:
    return (dt or _utc_now()).astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _est_iso(value: Any) -> str | None:
    parsed = _parse_iso(value)
    if parsed is None:
        return None
    return parsed.astimezone(LOCAL_TZ).isoformat(timespec="seconds")


def _read_json(path: Path, fallback: Any | None = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {} if fallback is None else fallback


def _write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _write_text(path, json.dumps(payload, indent=2, sort_keys=True))


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, dict)]
    if isinstance(value, dict):
        for key in ("rows", "positions", "open_positions", "closed_trades", "outcome_labels", "new_outcome_labels"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [dict(row) for row in nested if isinstance(row, dict)]
    return []


def _is_canonical_open_position_row(row: dict[str, Any]) -> bool:
    """Return true for net/open position rows, not raw accepted fill rows."""
    state = str(row.get("position_state") or row.get("status") or "").upper()
    if state and ("OPEN" in state or "POSITION" in state):
        return True
    if row.get("open_position") is True:
        return True
    if row.get("position_id"):
        return True
    if row.get("opened_est") or row.get("opened_utc") or row.get("opened_at"):
        return True
    if isinstance(row.get("source_fill_ids"), list):
        return True
    if row.get("net_quantity") is not None:
        return True
    return False


def _canonical_open_position_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if _is_canonical_open_position_row(row)]


def _portfolio_open_position_rows(portfolio_state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _as_list(portfolio_state.get("open_positions"))
    if rows:
        return rows
    positions = _as_list(portfolio_state.get("positions"))
    return [
        row
        for row in positions
        if row.get("open_position") is True
        or "OPEN" in str(row.get("position_state") or row.get("status") or "").upper()
    ]


def _first_num(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _num(row.get(key))
        if value is not None:
            return value
    return None


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def _read_v2_redis_json(redis_client: Any, key: str) -> Any:
    if redis_client is None or not key.startswith("v2:"):
        return None
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _allocation_distribution(samples: list[dict[str, Any]]) -> dict[str, Any]:
    values = [
        value
        for row in samples
        if (value := _num(row.get("target_notional_usdt"))) is not None and value > 0
    ]
    if not values:
        return {"count": 0, "min": None, "median": None, "max": None}
    return {
        "count": len(values),
        "min": round(min(values), 8),
        "median": round(statistics.median(values), 8),
        "max": round(max(values), 8),
    }


def _exposure_by_symbol(positions: list[dict[str, Any]]) -> dict[str, float]:
    totals: defaultdict[str, float] = defaultdict(float)
    for row in positions:
        symbol = str(row.get("symbol") or "UNKNOWN").upper()
        notional = _first_num(row, "notional", "gross_notional", "notional_usdt")
        if notional is None:
            qty = _first_num(row, "net_quantity", "quantity")
            price = _first_num(row, "last_mark_price", "avg_entry_price", "entry_price")
            notional = abs(qty * price) if qty is not None and price is not None else 0.0
        totals[symbol] += abs(notional)
    return {symbol: round(value, 8) for symbol, value in sorted(totals.items())}


def _position_counts_by_symbol(positions: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(str(row.get("symbol") or "UNKNOWN").upper() for row in positions)
    return dict(sorted(counts.items()))


def _accidental_hedge_symbols(positions: list[dict[str, Any]]) -> list[str]:
    sides_by_symbol: defaultdict[str, set[str]] = defaultdict(set)
    for row in positions:
        symbol = str(row.get("symbol") or "UNKNOWN").upper()
        side = str(row.get("side") or "").lower()
        if side:
            sides_by_symbol[symbol].add(side)
    return sorted(symbol for symbol, sides in sides_by_symbol.items() if len(sides) > 1)


def _position_opened_time(row: dict[str, Any]) -> datetime | None:
    for key in ("opened_utc", "opened_at", "opened_est", "opened_time", "entry_time", "created_at"):
        parsed = _parse_iso(row.get(key))
        if parsed is not None:
            return parsed
    return None


def _position_age_seconds(row: dict[str, Any], now: datetime) -> int | None:
    opened_at = _position_opened_time(row)
    if opened_at is None:
        return None
    return max(0, int((now.astimezone(timezone.utc) - opened_at).total_seconds()))


def _position_summaries(positions: list[dict[str, Any]], now: datetime, *, limit: int = 100) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for row in positions[:limit]:
        qty = _first_num(row, "net_quantity", "quantity")
        entry_price = _first_num(row, "avg_entry_price", "entry_price")
        mark_price = _first_num(row, "last_mark_price", "mark_price", "latest_price")
        notional = _first_num(row, "notional", "gross_notional", "notional_usdt")
        if notional is None and qty is not None:
            price = mark_price if mark_price is not None else entry_price
            notional = abs(qty * price) if price is not None else None
        summaries.append(
            {
                "position_id": row.get("position_id"),
                "symbol": str(row.get("symbol") or "UNKNOWN").upper(),
                "side": str(row.get("side") or "").lower() or None,
                "net_quantity": qty,
                "avg_entry_price": entry_price,
                "last_mark_price": mark_price,
                "notional_usdt": round(abs(notional), 8) if notional is not None else None,
                "opened_est": row.get("opened_est"),
                "last_mark_est": row.get("last_mark_est"),
                "unrealized_pnl_usd": _first_num(row, "unrealized_pnl", "unrealized_pnl_usd"),
                "position_age_seconds": _position_age_seconds(row, now),
            }
        )
    return summaries


def _closed_trade_summaries(rows: list[dict[str, Any]], *, limit: int = 100) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for row in rows[:limit]:
        summaries.append(
            {
                "position_id": row.get("position_id"),
                "symbol": str(row.get("symbol") or "UNKNOWN").upper(),
                "side": str(row.get("side") or "").lower() or None,
                "realized_pnl_usd": _first_num(row, "realized_pnl_usd", "realized_pnl", "pnl_usd"),
                "realized_pnl_bps": _first_num(row, "realized_pnl_bps", "pnl_bps"),
                "close_reason": row.get("close_reason"),
                "winner": row.get("winner"),
                "closed_est": row.get("closed_est") or row.get("exit_est"),
            }
        )
    return summaries


def _realized_pnl(rows: list[dict[str, Any]]) -> float:
    total = 0.0
    for row in rows:
        value = _first_num(row, "realized_pnl_usd", "realized_pnl", "pnl_usd")
        if value is not None:
            total += value
    return round(total, 8)


def _unrealized_pnl(positions: list[dict[str, Any]]) -> float:
    total = 0.0
    for row in positions:
        value = _first_num(row, "unrealized_pnl", "unrealized_pnl_usd")
        if value is not None:
            total += value
    return round(total, 8)


def _close_reason_counts(rows: list[dict[str, Any]], exit_status: dict[str, Any]) -> dict[str, int]:
    counts = Counter(str(row.get("close_reason") or "UNKNOWN") for row in rows if row.get("close_reason"))
    if not counts and isinstance(exit_status.get("close_reasons"), dict):
        return {str(key): int(value) for key, value in exit_status["close_reasons"].items()}
    return dict(sorted(counts.items()))


def _max_position_age_seconds(positions: list[dict[str, Any]], now: datetime) -> int | None:
    ages = [age for row in positions if (age := _position_age_seconds(row, now)) is not None]
    return max(ages) if ages else None


def _drawdown_status(drawdown_bps: float | None) -> str:
    if drawdown_bps is None:
        return "MISSING_DRAWDOWN_EVIDENCE"
    if drawdown_bps <= 0:
        return "CLEAR"
    return "DRAWDOWN_OBSERVED"


def _same_symbol_stack_status(max_positions_per_symbol: int) -> str:
    if max_positions_per_symbol <= 1:
        return "CLEAR"
    return "BREACH_UNCONTROLLED_SAME_SYMBOL_STACKING"


def _same_symbol_hedge_status(accidental_symbols: list[str], hedge_allowed: bool) -> str:
    if not accidental_symbols:
        return "CLEAR"
    if hedge_allowed:
        return "EXPLICIT_HEDGE_ALLOWED"
    return "BREACH_ACCIDENTAL_SAME_SYMBOL_HEDGE"


def _static_sizing_regression_status(static_regression: dict[str, Any]) -> str:
    if bool(static_regression.get("static_sizing_regression")):
        return "BREACH_STATIC_RUNTIME_SIZING_REGRESSION"
    return "CLEAR"


def _live_balance_hold_status(live_pre_submit_active: bool, live_blocker: Any, live_submit_changed: bool, submit_allowed_without_margin: bool) -> str:
    if live_submit_changed or submit_allowed_without_margin:
        return "BREACH_LIVE_NOT_BALANCE_HELD"
    if live_pre_submit_active and str(live_blocker or "") == "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER":
        return "CLEAR"
    if live_pre_submit_active:
        return "PENDING_BALANCE_HOLD_EVIDENCE"
    return "PENDING_NO_LIVE_PRE_SUBMIT_EVIDENCE"


def _allocator_bypass_status(allocation_status: dict[str, Any]) -> str:
    candidates = int(_num(allocation_status.get("paper_candidates_with_allocation")) or 0)
    accepted = int(_num(allocation_status.get("accepted_allocation_count")) or 0)
    blocked = int(_num(allocation_status.get("blocked_allocation_count")) or 0)
    if candidates <= 0:
        return "PENDING_NO_PAPER_CANDIDATES"
    if accepted + blocked <= 0:
        return "BREACH_ADAPTIVE_ALLOCATOR_BYPASSED_BY_PAPER_EXECUTION"
    return "CLEAR"


def _position_stale_status(open_positions_count: int, max_age_seconds: int | None, max_hold_seconds: float | None) -> str:
    if open_positions_count <= 0:
        return "CLEAR"
    if max_age_seconds is None or max_hold_seconds is None or max_hold_seconds <= 0:
        return "PENDING_MAX_HOLD_EVIDENCE"
    if max_age_seconds > max_hold_seconds:
        return "BREACH_POSITION_OPEN_BEYOND_MAX_HOLD"
    return "CLEAR"


def _observation_high_severity_alerts(row: dict[str, Any]) -> list[str]:
    alerts: list[str] = []
    if str(row.get("allocator_bypass_status") or "").startswith("BREACH_"):
        alerts.append("ADAPTIVE_ALLOCATOR_BYPASSED_BY_PAPER_EXECUTION")
    if bool(row.get("static_sizing_regression")) or str(row.get("static_sizing_regression_status") or "").startswith("BREACH_"):
        alerts.append("STATIC_RUNTIME_SIZING_REGRESSION")
    if row.get("exposure_caps_valid") is False:
        alerts.append("PAPER_EXPOSURE_CAP_BREACH")
    if int(_num(row.get("max_positions_per_symbol")) or 0) > 1:
        alerts.append("UNCONTROLLED_SAME_SYMBOL_STACKING")
    if str(row.get("same_symbol_hedge_status") or "").startswith("BREACH_"):
        alerts.append("ACCIDENTAL_SAME_SYMBOL_HEDGE")
    if str(row.get("position_stale_status") or "").startswith("BREACH_"):
        alerts.append("PAPER_POSITION_STALE_BEYOND_EXIT_RULES")
    closed_count = int(_num(row.get("closed_trades_count")) or 0)
    outcome_count = int(_num(row.get("outcome_labels_count")) or _num(row.get("outcome_label_count")) or 0)
    feedback_count = int(_num(row.get("trainer_feedback_rows_count")) or _num(row.get("trainer_feedback_row_count")) or 0)
    if closed_count > 0 and outcome_count <= 0:
        alerts.append("CLOSED_TRADES_WITHOUT_OUTCOME_LABELS")
    if outcome_count > 0 and feedback_count <= 0:
        alerts.append("OUTCOME_LABELS_WITHOUT_TRAINER_FEEDBACK")
    pnl_present = abs(float(_num(row.get("realized_pnl_usd")) or 0.0)) > 0 or abs(float(_num(row.get("unrealized_pnl_usd")) or 0.0)) > 0
    if pnl_present and _num(row.get("paper_equity")) is None:
        alerts.append("PAPER_EQUITY_MISSING_WHILE_PNL_PRESENT")
    if bool(row.get("live_submit_changed")) or bool(row.get("live_submit_allowed_without_margin")):
        alerts.append("LIVE_BALANCE_HOLD_BYPASSED")
    if bool(row.get("test_order_attempted")):
        alerts.append("TEST_ORDER_ATTEMPTED")
    if bool(row.get("leverage_changed")):
        alerts.append("LEVERAGE_CHANGED")
    if bool(row.get("margin_mode_changed")):
        alerts.append("MARGIN_MODE_CHANGED")
    return sorted(set(alerts))


def _exposure_caps_valid(cap_status: dict[str, Any]) -> bool:
    for row in _as_list(cap_status.get("evaluations")):
        symbol_notional = _num(row.get("current_symbol_notional")) or 0.0
        candidate = _num(row.get("candidate_notional")) or 0.0
        max_symbol = _num(row.get("computed_max_symbol_notional_usdt"))
        total_open = _num(row.get("total_open_notional")) or 0.0
        max_total = _num(row.get("computed_max_total_notional_usdt"))
        if max_symbol is not None and symbol_notional > max_symbol + 1e-9:
            return False
        if max_total is not None and total_open > max_total + candidate + 1e-9:
            return False
    return True


def _static_sizing_regression(
    allocation_status: dict[str, Any],
    risk_envelope_status: dict[str, Any],
    static_scan_status: dict[str, Any],
) -> dict[str, Any]:
    samples = _as_list(allocation_status.get("sample_allocations"))
    nonzero = [
        value
        for row in samples
        if (value := _num(row.get("target_notional_usdt"))) is not None and value > 0
    ]
    fixed_200_sample_count = sum(1 for value in nonzero if abs(value - 200.0) < 1e-9)
    all_samples_equal_200 = bool(nonzero) and len(nonzero) > 1 and fixed_200_sample_count == len(nonzero)
    scan_remove_count = int(_num(static_scan_status.get("current_runtime_static_sizing_remove_count")) or 0)
    static_trade_size_used = bool(
        allocation_status.get("static_trade_size_used")
        or risk_envelope_status.get("static_trade_size_used")
        or risk_envelope_status.get("fixed_200_usdt_runtime_sizing")
    )
    return {
        "static_sizing_regression": bool(static_trade_size_used or scan_remove_count > 0 or all_samples_equal_200),
        "static_trade_size_used": static_trade_size_used,
        "fixed_200_sample_count": fixed_200_sample_count,
        "all_nonzero_sample_allocations_equal_200": all_samples_equal_200,
        "current_runtime_static_sizing_remove_count": scan_remove_count,
    }


def _paper_equity_context(
    risk_envelope_status: dict[str, Any],
    portfolio_state: dict[str, Any],
    paper_session_equity_status: dict[str, Any],
) -> dict[str, Any]:
    """Resolve paper equity from the freshest operator-facing source available."""
    candidates = [
        (
            _num(portfolio_state.get("equity")),
            "operator_runtime:v2_portfolio_state.equity",
        ),
        (
            _num(portfolio_state.get("current_session_equity")),
            "operator_runtime:v2_portfolio_state.current_session_equity",
        ),
        (
            _num(paper_session_equity_status.get("current_session_equity")),
            "operator_runtime:v2_runtime_truth.paper_session_equity_status.current_session_equity",
        ),
        (
            _num(paper_session_equity_status.get("paper_equity")),
            "operator_runtime:v2_runtime_truth.paper_session_equity_status.paper_equity",
        ),
        (
            _num(risk_envelope_status.get("equity")),
            str(risk_envelope_status.get("equity_source") or "risk_envelope_dynamic_budget_status.equity"),
        ),
    ]
    for value, source in candidates:
        if value is not None and value > 0:
            return {"paper_equity": value, "paper_equity_source": source}
    for value, source in candidates:
        if value is not None:
            return {"paper_equity": value, "paper_equity_source": source}
    return {"paper_equity": None, "paper_equity_source": None}


def collect_observation(
    *,
    root: Path = REPO_ROOT,
    redis_client: Any | None = None,
    now: datetime | None = None,
    observation_run_id: str | None = None,
) -> dict[str, Any]:
    observed_dt = (now or _utc_now()).astimezone(timezone.utc)
    paper_runtime = root / PAPER_RUNTIME_DIR.relative_to(REPO_ROOT)
    portfolio_state_dir = root / PORTFOLIO_STATE_DIR.relative_to(REPO_ROOT)
    runtime_truth_dir = root / RUNTIME_TRUTH_DIR.relative_to(REPO_ROOT)
    adaptive_gate = root / ADAPTIVE_GATE_DIR.relative_to(REPO_ROOT)
    paper_gate = root / PAPER_GATE_DIR.relative_to(REPO_ROOT)
    redis_client = redis_client if redis_client is not None else _connect_redis()

    allocation_status = _read_json(paper_runtime / "paper_adaptive_sizing_runtime_status.json", {})
    lifecycle_status = _read_json(paper_runtime / "paper_position_lifecycle_status.json", {})
    cap_status = _read_json(paper_runtime / "paper_position_exposure_cap_status.json", {})
    hedge_status = _read_json(paper_runtime / "paper_hedge_netting_status.json", {})
    exit_status = _read_json(paper_runtime / "paper_exit_coordinator_status.json", {})
    stop_status = _read_json(paper_runtime / "paper_stop_takeprofit_trailing_status.json", {})
    closed_status = _read_json(paper_runtime / "paper_closed_trade_outcome_label_status.json", {})
    risk_envelope_status = _read_json(paper_runtime / "risk_envelope_dynamic_budget_status.json", {})
    guard_status = _read_json(paper_runtime / "trade_lifecycle_guard_status.json", {})
    paper_outcomes = _read_json(paper_runtime / "paper_outcome_labels.json", {})
    portfolio_state = _read_json(portfolio_state_dir / "v2_portfolio_state.json", {})
    paper_session_equity_status = _read_json(runtime_truth_dir / "paper_session_equity_status.json", {})
    static_scan_status = _read_json(adaptive_gate / "adaptive_sizing_static_constant_scan_status.json", {})
    live_pre_submit_status = _read_json(adaptive_gate / "live_adaptive_sizing_pre_submit_status.json", {})
    paper_gate_payload = _read_json(paper_gate / "operator_dashboard_payload.json", {})

    redis_position_rows = _as_list(_read_v2_redis_json(redis_client, "v2:paper:positions"))
    redis_positions = _canonical_open_position_rows(redis_position_rows)
    portfolio_position_rows = _portfolio_open_position_rows(portfolio_state)
    portfolio_positions = _canonical_open_position_rows(portfolio_position_rows)
    redis_closed = _as_list(_read_v2_redis_json(redis_client, "v2:paper:closed_trades"))
    redis_outcomes = _as_list(_read_v2_redis_json(redis_client, "v2:paper:outcome_labels"))
    redis_feedback = _as_list(_read_v2_redis_json(redis_client, "v2:trainer:feedback:outcomes"))

    outcome_labels = redis_outcomes or _as_list(paper_outcomes.get("outcome_labels"))
    closed_trades = redis_closed
    feedback_rows = redis_feedback
    if redis_positions:
        positions = redis_positions
        position_source = "redis:v2:paper:positions.canonical_open_rows"
    elif portfolio_positions:
        positions = portfolio_positions
        position_source = "operator_runtime:v2_portfolio_state.open_positions"
    else:
        positions = []
        position_source = (
            "redis:v2:paper:positions.raw_rows_ignored"
            if redis_position_rows
            else "paper_lifecycle_status.open_positions_count"
        )

    exposure_by_symbol = _exposure_by_symbol(positions)
    total_exposure = round(sum(exposure_by_symbol.values()), 8)
    position_counts = _position_counts_by_symbol(positions)
    max_positions_per_symbol = max(position_counts.values(), default=0)
    accidental_hedge_symbols = _accidental_hedge_symbols(positions)
    accidental_hedge_pairs_allowed = bool(hedge_status.get("accidental_hedge_pairs_allowed"))
    static_regression = _static_sizing_regression(allocation_status, risk_envelope_status, static_scan_status)
    sample_allocations = _as_list(allocation_status.get("sample_allocations"))
    allocation_distribution = _allocation_distribution(sample_allocations)
    open_positions_count = len(positions) if positions else int(_num(lifecycle_status.get("open_positions_count")) or 0)
    closed_trades_count = len(closed_trades) if closed_trades else int(_num(closed_status.get("closed_trade_count")) or 0)
    outcome_labels_count = len(outcome_labels) if outcome_labels else int(_num(closed_status.get("outcome_label_count")) or 0)
    trainer_feedback_rows_count = len(feedback_rows) if feedback_rows else int(_num(closed_status.get("trainer_feedback_rows_ready")) or 0)
    realized_pnl_usd = _realized_pnl(closed_trades or outcome_labels)
    unrealized_pnl_usd = _unrealized_pnl(positions)
    drawdown_bps = _num(risk_envelope_status.get("drawdown_bps"))
    live_pre_submit_allocator_active = bool(
        live_pre_submit_status.get("uses_adaptive_allocator") or allocation_status.get("live_pre_submit_allocator_active")
    )
    live_submit_changed = bool(live_pre_submit_status.get("live_submit_changed"))
    live_submit_allowed_without_margin = bool(live_pre_submit_status.get("submit_allowed_without_margin"))
    live_blocker = live_pre_submit_status.get("insufficient_margin_blocker_preserved")
    max_hold_seconds = _num(stop_status.get("max_hold_seconds"))
    if max_hold_seconds is None:
        max_hold_seconds = _num(exit_status.get("max_hold_seconds"))
    max_position_age_seconds = _max_position_age_seconds(positions, observed_dt)
    paper_equity_context = _paper_equity_context(
        risk_envelope_status,
        portfolio_state,
        paper_session_equity_status,
    )

    observation = {
        "schema_version": "v2_adaptive_allocation_trade_lifecycle_soak_observation_v1",
        "observed_utc": _iso(observed_dt),
        "observed_est": _est_iso(_iso(observed_dt)),
        "observation_run_id": observation_run_id,
        "paper_only": True,
        "places_real_order": False,
        "paper_allocation_distribution": allocation_distribution,
        "paper_allocation_size_distribution": allocation_distribution,
        "position_source": position_source,
        "raw_redis_position_row_count": len(redis_position_rows),
        "canonical_redis_position_row_count": len(redis_positions),
        "portfolio_position_row_count": len(portfolio_position_rows),
        "canonical_portfolio_position_row_count": len(portfolio_positions),
        "paper_candidates_with_allocation": int(_num(allocation_status.get("paper_candidates_with_allocation")) or 0),
        "accepted_allocation_count": int(_num(allocation_status.get("accepted_allocation_count")) or 0),
        "blocked_allocation_count": int(_num(allocation_status.get("blocked_allocation_count")) or 0),
        "allocator_decision_counts": allocation_status.get("allocator_decision_counts") if isinstance(allocation_status.get("allocator_decision_counts"), dict) else {},
        "exposure_by_symbol": exposure_by_symbol,
        "total_paper_exposure_usdt": total_exposure,
        "open_positions": _position_summaries(positions, observed_dt),
        "open_positions_count": open_positions_count,
        "position_counts_by_symbol": position_counts,
        "max_positions_per_symbol": max_positions_per_symbol,
        "same_symbol_stack_status": _same_symbol_stack_status(max_positions_per_symbol),
        "closed_positions": _closed_trade_summaries(closed_trades or outcome_labels),
        "closed_positions_count": closed_trades_count,
        "closed_trades_count": closed_trades_count,
        "outcome_label_count": outcome_labels_count,
        "outcome_labels_count": outcome_labels_count,
        "trainer_feedback_row_count": trainer_feedback_rows_count,
        "trainer_feedback_rows_count": trainer_feedback_rows_count,
        "realized_pnl": realized_pnl_usd,
        "realized_pnl_usd": realized_pnl_usd,
        "unrealized_pnl": unrealized_pnl_usd,
        "unrealized_pnl_usd": unrealized_pnl_usd,
        "exit_reason_counts": _close_reason_counts(closed_trades or outcome_labels, exit_status),
        "stop_takeprofit_trailing": {
            "stop_loss_bps": stop_status.get("stop_loss_bps"),
            "take_profit_bps": stop_status.get("take_profit_bps"),
            "trailing_stop_bps": stop_status.get("trailing_stop_bps"),
            "max_hold_seconds": max_hold_seconds,
            "triggered_count": stop_status.get("triggered_count"),
        },
        "max_position_age_seconds": max_position_age_seconds,
        "position_stale_status": _position_stale_status(open_positions_count, max_position_age_seconds, max_hold_seconds),
        "model_reversal_exit_enabled": "TIER_3" in {str(item) for item in exit_status.get("tiers_enabled", [])}
        or "TIER_3_MODEL_SIGNAL_EXIT" in {str(item) for item in paper_gate_payload.get("risk_lifecycle", [])},
        "accidental_hedge_symbols": accidental_hedge_symbols,
        "accidental_hedge_pairs_allowed": accidental_hedge_pairs_allowed,
        "same_symbol_hedge_status": _same_symbol_hedge_status(accidental_hedge_symbols, accidental_hedge_pairs_allowed),
        "same_side_netting_count": int(_num(hedge_status.get("same_side_netting_count")) or 0),
        "opposite_side_netting_count": int(_num(hedge_status.get("opposite_side_netting_count")) or 0),
        "allocator_bypass_status": _allocator_bypass_status(allocation_status),
        "exposure_caps_valid": _exposure_caps_valid(cap_status),
        "drawdown_bps": drawdown_bps,
        "drawdown_status": _drawdown_status(drawdown_bps),
        "paper_equity": paper_equity_context["paper_equity"],
        "paper_equity_source": paper_equity_context["paper_equity_source"],
        "drawdown_guard_evidence_present": drawdown_bps is not None,
        "risk_envelope_operator_type": risk_envelope_status.get("operator_envelope_type"),
        "trade_lifecycle_guard_active": bool(guard_status.get("shared_guard_available") and guard_status.get("paper_path_using_lifecycle_controls")),
        "live_pre_submit_allocator_active": live_pre_submit_allocator_active,
        "live_submit_changed": live_submit_changed,
        "live_submit_allowed_without_margin": live_submit_allowed_without_margin,
        "live_blocker": live_blocker,
        "live_balance_hold_status": _live_balance_hold_status(
            live_pre_submit_allocator_active,
            live_blocker,
            live_submit_changed,
            live_submit_allowed_without_margin,
        ),
        "test_order_attempted": bool(live_pre_submit_status.get("test_order_endpoint_attempted")),
        "leverage_changed": bool(live_pre_submit_status.get("leverage_changed")),
        "margin_mode_changed": bool(live_pre_submit_status.get("margin_mode_changed")),
        "static_sizing_regression_status": _static_sizing_regression_status(static_regression),
        **static_regression,
    }
    return observation


def _aggregate_bool(rows: list[dict[str, Any]], key: str, *, default: bool = False, all_rows: bool = True) -> bool:
    if not rows:
        return default
    values = [bool(row.get(key)) for row in rows]
    return all(values) if all_rows else any(values)


def _is_density_eligible_observation(row: dict[str, Any]) -> bool:
    return all(
        key in row
        for key in (
            "observed_est",
            "paper_allocation_distribution",
            "same_symbol_stack_status",
            "same_symbol_hedge_status",
            "static_sizing_regression_status",
            "live_balance_hold_status",
        )
    )


def _is_current_position_schema_observation(row: dict[str, Any]) -> bool:
    return isinstance(row.get("position_source"), str) and bool(row.get("position_source"))


def _observation_density(
    observations: list[dict[str, Any]],
    *,
    interval_seconds: int,
    generated_dt: datetime,
) -> dict[str, Any]:
    eligible_rows = [row for row in observations if _is_density_eligible_observation(row)]
    eligible_timestamps = [ts for row in eligible_rows if (ts := _parse_iso(row.get("observed_utc"))) is not None]
    if len(eligible_timestamps) >= 2:
        elapsed_seconds = max(0, int((max(eligible_timestamps) - min(eligible_timestamps)).total_seconds()))
    else:
        elapsed_seconds = 0
    expected_observations = math.floor(elapsed_seconds / max(1, interval_seconds))
    minimum_required = max(12, int(expected_observations * 0.80))
    observed_count = len(eligible_timestamps)
    latest_ts = max(eligible_timestamps) if eligible_timestamps else None
    last_age = max(0, int((generated_dt - latest_ts).total_seconds())) if latest_ts is not None else None
    freshness_limit = max(1, interval_seconds) * 2
    density_ok = observed_count >= minimum_required
    freshness_ok = last_age is not None and last_age <= freshness_limit
    return {
        "density_window_first_observation_utc": _iso(min(eligible_timestamps)) if eligible_timestamps else None,
        "density_window_first_observation_est": _est_iso(_iso(min(eligible_timestamps))) if eligible_timestamps else None,
        "density_window_latest_observation_utc": _iso(latest_ts) if latest_ts else None,
        "density_window_latest_observation_est": _est_iso(_iso(latest_ts)) if latest_ts else None,
        "density_window_elapsed_seconds": elapsed_seconds,
        "interval_seconds": max(1, interval_seconds),
        "expected_observations": expected_observations,
        "minimum_required_observations": minimum_required,
        "density_eligible_observation_count": observed_count,
        "observation_density_ok": density_ok,
        "observation_density_status": "CLEAR" if density_ok else "INSUFFICIENT_OBSERVATION_DENSITY",
        "last_observation_age_seconds": last_age,
        "last_observation_freshness_limit_seconds": freshness_limit,
        "last_observation_fresh": freshness_ok,
        "last_observation_freshness_status": "CLEAR" if freshness_ok else "STALE_LAST_OBSERVATION",
    }


def build_soak_status(
    observations: list[dict[str, Any]],
    *,
    generated_utc: str | None = None,
    required_seconds: int = DEFAULT_SOAK_REQUIRED_SECONDS,
    interval_seconds: int = 300,
) -> dict[str, Any]:
    all_observations = list(observations)
    latest = all_observations[-1] if all_observations else {}
    generated_dt = _parse_iso(generated_utc) or _utc_now()
    generated_utc_value = _iso(generated_dt)
    breach_rows: list[tuple[int, dict[str, Any], list[str]]] = []
    for index, row in enumerate(all_observations):
        row_alerts = _observation_high_severity_alerts(row)
        if row_alerts:
            breach_rows.append((index, row, row_alerts))
    historical_high_severity_alerts = sorted({alert for _, _, alerts in breach_rows for alert in alerts})
    proof_window_reset_reason = None
    last_safety_breach_utc = None
    last_safety_breach_alerts: list[str] = []
    observations = all_observations
    if breach_rows:
        last_breach_index, last_breach_row, last_safety_breach_alerts = breach_rows[-1]
        last_safety_breach_utc = last_breach_row.get("observed_utc")
        if last_breach_index < len(all_observations) - 1:
            observations = all_observations[last_breach_index + 1 :]
            proof_window_reset_reason = "SAFETY_BREACH_RESOLVED_RESTARTED_PROOF_WINDOW"
    if not observations and latest:
        observations = [latest]
    timestamps = [ts for row in observations if (ts := _parse_iso(row.get("observed_utc"))) is not None]
    first_observation_utc = _iso(min(timestamps)) if timestamps else None
    latest_observation_utc = _iso(max(timestamps)) if timestamps else None
    density = _observation_density(observations, interval_seconds=interval_seconds, generated_dt=generated_dt)
    elapsed_seconds = 0
    if len(timestamps) >= 2:
        elapsed_seconds = max(0, int((max(timestamps) - min(timestamps)).total_seconds()))
    max_closed = max((int(_num(row.get("closed_trades_count")) or 0) for row in observations), default=0)
    max_outcomes = max((int(_num(row.get("outcome_labels_count")) or 0) for row in observations), default=0)
    max_feedback = max((int(_num(row.get("trainer_feedback_rows_count")) or 0) for row in observations), default=0)
    max_positions_per_symbol = max((int(_num(row.get("max_positions_per_symbol")) or 0) for row in observations), default=0)
    accidental_hedges = sorted(
        {
            str(symbol)
            for row in observations
            for symbol in row.get("accidental_hedge_symbols", [])
            if symbol
        }
    )
    no_static_regression = not _aggregate_bool(observations, "static_sizing_regression", all_rows=False)
    safety_ok = all(
        [
            no_static_regression,
            not _aggregate_bool(observations, "live_submit_changed", all_rows=False),
            not _aggregate_bool(observations, "live_submit_allowed_without_margin", all_rows=False),
            not _aggregate_bool(observations, "test_order_attempted", all_rows=False),
            not _aggregate_bool(observations, "leverage_changed", all_rows=False),
            not _aggregate_bool(observations, "margin_mode_changed", all_rows=False),
        ]
    )
    high_severity_alerts = sorted(
        {
            alert
            for row in observations
            for alert in _observation_high_severity_alerts(row)
        }
    )
    if max_closed > 0 and max_outcomes <= 0:
        high_severity_alerts.append("CLOSED_TRADES_WITHOUT_OUTCOME_LABELS")
    if max_outcomes > 0 and max_feedback <= 0:
        high_severity_alerts.append("OUTCOME_LABELS_WITHOUT_TRAINER_FEEDBACK")
    pnl_present = abs(float(_num(latest.get("realized_pnl_usd")) or 0.0)) > 0 or abs(float(_num(latest.get("unrealized_pnl_usd")) or 0.0)) > 0
    if pnl_present and _num(latest.get("paper_equity")) is None:
        high_severity_alerts.append("PAPER_EQUITY_MISSING_WHILE_PNL_PRESENT")
    if bool(latest.get("live_submit_changed")) or bool(latest.get("live_submit_allowed_without_margin")):
        high_severity_alerts.append("LIVE_BALANCE_HOLD_BYPASSED")
    if bool(latest.get("test_order_attempted")):
        high_severity_alerts.append("TEST_ORDER_ATTEMPTED")
    if bool(latest.get("leverage_changed")):
        high_severity_alerts.append("LEVERAGE_CHANGED")
    if bool(latest.get("margin_mode_changed")):
        high_severity_alerts.append("MARGIN_MODE_CHANGED")
    high_severity_alerts = sorted(set(high_severity_alerts))

    hedge_allowed_seen = _aggregate_bool(observations, "accidental_hedge_pairs_allowed", all_rows=False)
    criteria = {
        "no_fixed_runtime_sizing_appears": no_static_regression,
        "no_runaway_symbol_exposure": _aggregate_bool(observations, "exposure_caps_valid", default=False),
        "no_unbounded_position_stacking": max_positions_per_symbol <= 1,
        "no_same_symbol_accidental_hedge_unless_explicit": not accidental_hedges or hedge_allowed_seen,
        "closed_trades_gt_0": max_closed > 0,
        "outcome_labels_gt_0": max_outcomes > 0,
        "trainer_feedback_rows_gt_0": max_feedback > 0,
        "paper_equity_updates_from_pnl": _num(latest.get("paper_equity")) is not None,
        "drawdown_guard_evidence_present": _aggregate_bool(observations, "drawdown_guard_evidence_present", default=False),
        "live_remains_balance_held": bool(latest.get("live_pre_submit_allocator_active"))
        and not bool(latest.get("live_submit_changed"))
        and str(latest.get("live_blocker") or "") == "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER",
        "completion_window_elapsed_seconds_gte_required": int(density["density_window_elapsed_seconds"]) >= required_seconds,
        "observation_density_ok": bool(density["observation_density_ok"]),
        "last_observation_fresh": bool(density["last_observation_fresh"]),
    }
    soak_complete = all(criteria.values()) and safety_ok and not high_severity_alerts
    soak_24h_complete = soak_complete and int(density["density_window_elapsed_seconds"]) >= 24 * 3600
    dangerous_blockers = high_severity_alerts
    window_label = soak_window_label(required_seconds)
    window_suffix = _soak_gate_suffix(required_seconds)
    gate = blocked_gate(required_seconds) if dangerous_blockers else ready_gate(required_seconds)
    completion_marker = (
        complete_blocked_gate(required_seconds)
        if dangerous_blockers
        else complete_ready_gate(required_seconds)
        if soak_complete
        else None
    )
    proof_status = (
        f"SOAK_{window_suffix}_COMPLETE"
        if soak_complete
        else f"PENDING_{window_suffix}_OBSERVATION"
        if not dangerous_blockers
        else "BLOCKED_BY_SAFETY_INVARIANT"
    )
    return {
        "schema_version": "v2_adaptive_allocation_trade_lifecycle_soak_status_v1",
        "gate": gate,
        "proof_status": proof_status,
        "completion_marker": completion_marker,
        "generated_utc": generated_utc_value,
        "generated_est": _est_iso(generated_utc_value),
        "soak_window_label": window_label,
        "soak_window_hours": round(required_seconds / 3600.0, 4),
        "soak_required_seconds": required_seconds,
        "completion_window_required_seconds": required_seconds,
        "first_observation_utc": first_observation_utc,
        "first_observation_est": _est_iso(first_observation_utc),
        "latest_observation_utc": latest_observation_utc,
        "latest_observation_est": _est_iso(latest_observation_utc),
        "observation_count": len(observations),
        "total_observation_count": len(all_observations),
        "proof_window_reset_reason": proof_window_reset_reason,
        "last_safety_breach_utc": last_safety_breach_utc,
        "last_safety_breach_est": _est_iso(last_safety_breach_utc),
        "last_safety_breach_alerts": last_safety_breach_alerts,
        "historical_high_severity_alerts": historical_high_severity_alerts,
        "required_seconds": required_seconds,
        "elapsed_seconds": elapsed_seconds,
        "elapsed_window_seconds": elapsed_seconds,
        "completion_window_elapsed_seconds": density["density_window_elapsed_seconds"],
        "density_window_elapsed_seconds": density["density_window_elapsed_seconds"],
        "elapsed_seconds_observed": elapsed_seconds,
        "elapsed_hours_observed": round(elapsed_seconds / 3600.0, 4),
        **density,
        "soak_complete": soak_complete,
        "soak_1h_complete": soak_complete if required_seconds == 3600 else False,
        "soak_12h_complete": soak_complete if required_seconds == DEFAULT_SOAK_REQUIRED_SECONDS else False,
        "soak_24h_complete": soak_24h_complete,
        "success_criteria": criteria,
        "dangerous_blockers": dangerous_blockers,
        "high_severity_alerts": high_severity_alerts,
        "latest_metrics": {
            "paper_allocation_distribution": latest.get("paper_allocation_distribution")
            or latest.get("paper_allocation_size_distribution"),
            "paper_allocation_size_distribution": latest.get("paper_allocation_size_distribution")
            or latest.get("paper_allocation_distribution"),
            "accepted_allocation_count": latest.get("accepted_allocation_count"),
            "blocked_allocation_count": latest.get("blocked_allocation_count"),
            "allocator_decision_counts": latest.get("allocator_decision_counts") or {},
            "position_source": latest.get("position_source"),
            "raw_redis_position_row_count": latest.get("raw_redis_position_row_count"),
            "canonical_redis_position_row_count": latest.get("canonical_redis_position_row_count"),
            "portfolio_position_row_count": latest.get("portfolio_position_row_count"),
            "canonical_portfolio_position_row_count": latest.get("canonical_portfolio_position_row_count"),
            "open_positions": latest.get("open_positions") or [],
            "exposure_by_symbol": latest.get("exposure_by_symbol"),
            "total_paper_exposure_usdt": latest.get("total_paper_exposure_usdt"),
            "open_positions_count": latest.get("open_positions_count"),
            "closed_positions": latest.get("closed_positions") or [],
            "closed_positions_count": latest.get("closed_positions_count") or latest.get("closed_trades_count"),
            "closed_trades_count": latest.get("closed_trades_count"),
            "same_symbol_stack_status": latest.get("same_symbol_stack_status"),
            "same_symbol_hedge_status": latest.get("same_symbol_hedge_status"),
            "realized_pnl_usd": latest.get("realized_pnl_usd"),
            "unrealized_pnl_usd": latest.get("unrealized_pnl_usd"),
            "exit_reason_counts": latest.get("exit_reason_counts"),
            "stop_takeprofit_trailing": latest.get("stop_takeprofit_trailing") or {},
            "max_position_age_seconds": latest.get("max_position_age_seconds"),
            "outcome_label_count": latest.get("outcome_label_count") or latest.get("outcome_labels_count"),
            "outcome_labels_count": latest.get("outcome_labels_count") or latest.get("outcome_label_count"),
            "trainer_feedback_row_count": latest.get("trainer_feedback_row_count")
            or latest.get("trainer_feedback_rows_count"),
            "trainer_feedback_rows_count": latest.get("trainer_feedback_rows_count")
            or latest.get("trainer_feedback_row_count"),
            "paper_equity": latest.get("paper_equity"),
            "paper_equity_source": latest.get("paper_equity_source"),
            "drawdown_bps": latest.get("drawdown_bps"),
            "drawdown_status": latest.get("drawdown_status"),
            "static_sizing_regression_status": latest.get("static_sizing_regression_status"),
            "live_blocker": latest.get("live_blocker"),
            "live_balance_hold_status": latest.get("live_balance_hold_status"),
            "allocator_bypass_status": latest.get("allocator_bypass_status"),
            "position_stale_status": latest.get("position_stale_status"),
        },
        "safety": {
            "paper_only": True,
            "live_submit_changed": bool(latest.get("live_submit_changed")),
            "test_order_attempted": bool(latest.get("test_order_attempted")),
            "leverage_changed": bool(latest.get("leverage_changed")),
            "margin_mode_changed": bool(latest.get("margin_mode_changed")),
            "writes_redis": False,
            "writes_old_redis": False,
            "raw_credentials_exposed": False,
        },
    }


def build_report(status: dict[str, Any]) -> str:
    criteria = status.get("success_criteria", {})
    latest = status.get("latest_metrics", {})
    alerts = status.get("high_severity_alerts") or []
    window_label = str(status.get("soak_window_label") or SOAK_WINDOW_LABEL)
    lines = [
        f"# V2 Adaptive Allocation And Trade Lifecycle {window_label} Paper Soak Report",
        "",
        f"Generated: `{status.get('generated_utc')}`",
        f"First observation EST: `{status.get('first_observation_est')}`",
        f"Latest observation EST: `{status.get('latest_observation_est')}`",
        "",
        "Gate:",
        "",
        "```text",
        str(status.get("gate")),
        "```",
        "",
        f"Proof status: `{status.get('proof_status')}`",
        f"Completion marker: `{status.get('completion_marker')}`",
        f"Soak window: `{status.get('soak_window_label')}`",
        f"Required seconds: `{status.get('soak_required_seconds')}`",
        f"Observed hours: `{status.get('elapsed_hours_observed')}`",
        f"Completion-window elapsed seconds: `{status.get('completion_window_elapsed_seconds')}`",
        f"Density-eligible observations: `{status.get('density_eligible_observation_count')}`",
        f"Expected observations: `{status.get('expected_observations')}`",
        f"Minimum required observations: `{status.get('minimum_required_observations')}`",
        f"Observation density status: `{status.get('observation_density_status')}`",
        f"Last observation age seconds: `{status.get('last_observation_age_seconds')}`",
        f"Last observation freshness status: `{status.get('last_observation_freshness_status')}`",
        f"{window_label} complete: `{status.get('soak_complete')}`",
        f"1h complete: `{status.get('soak_1h_complete')}`",
        f"12h legacy alias complete: `{status.get('soak_12h_complete')}`",
        f"24h legacy alias complete: `{status.get('soak_24h_complete')}`",
        "",
        "Current monitored metrics:",
        "",
        f"- Accepted allocations: `{latest.get('accepted_allocation_count')}`",
        f"- Blocked allocations: `{latest.get('blocked_allocation_count')}`",
        f"- Position source: `{latest.get('position_source')}`",
        f"- Raw Redis position rows: `{latest.get('raw_redis_position_row_count')}`",
        f"- Canonical Redis open position rows: `{latest.get('canonical_redis_position_row_count')}`",
        f"- Total paper exposure USDT: `{latest.get('total_paper_exposure_usdt')}`",
        f"- Open positions: `{latest.get('open_positions_count')}`",
        f"- Closed trades: `{latest.get('closed_trades_count')}`",
        f"- Realized PnL USD: `{latest.get('realized_pnl_usd')}`",
        f"- Unrealized PnL USD: `{latest.get('unrealized_pnl_usd')}`",
        f"- Outcome labels: `{latest.get('outcome_labels_count')}`",
        f"- Trainer feedback rows: `{latest.get('trainer_feedback_rows_count')}`",
        f"- Same-symbol stack status: `{latest.get('same_symbol_stack_status')}`",
        f"- Same-symbol hedge status: `{latest.get('same_symbol_hedge_status')}`",
        f"- Static sizing regression status: `{latest.get('static_sizing_regression_status')}`",
        f"- Live blocker: `{latest.get('live_blocker')}`",
        f"- Live balance-hold status: `{latest.get('live_balance_hold_status')}`",
        "",
        "High-severity alerts:",
        "",
    ]
    lines.extend(f"- `{alert}`" for alert in alerts)
    if not alerts:
        lines.append("- `none`")
    lines.extend(
        [
            "",
            "Success criteria:",
            "",
        ]
    )
    lines.extend(f"- `{key}` = `{value}`" for key, value in criteria.items())
    lines.extend(
        [
            "",
            "Safety boundary:",
            "",
            "- This monitor does not write Redis.",
            "- This monitor does not place real orders or call test-order.",
            "- This monitor does not change leverage or margin mode.",
            "- Live remains held by available-margin gating.",
            "",
            "Interpretation:",
            "",
            f"READY means the paper-only soak observer is wired and safe to run. It does not claim {window_label} proof until `soak_complete` is true.",
        ]
    )
    return "\n".join(lines) + "\n"


def _completion_artifacts(status: dict[str, Any]) -> dict[str, dict[str, Any]]:
    latest = status.get("latest_metrics", {})
    base = {
        "generated_utc": status.get("generated_utc"),
        "completion_marker": status.get("completion_marker"),
        "proof_status": status.get("proof_status"),
        "soak_window_label": status.get("soak_window_label"),
        "soak_window_hours": status.get("soak_window_hours"),
        "soak_required_seconds": status.get("soak_required_seconds"),
        "first_observation_est": status.get("first_observation_est"),
        "latest_observation_est": status.get("latest_observation_est"),
        "elapsed_window_seconds": status.get("elapsed_window_seconds"),
        "completion_window_elapsed_seconds": status.get("completion_window_elapsed_seconds"),
        "density_window_elapsed_seconds": status.get("density_window_elapsed_seconds"),
        "interval_seconds": status.get("interval_seconds"),
        "expected_observations": status.get("expected_observations"),
        "minimum_required_observations": status.get("minimum_required_observations"),
        "density_eligible_observation_count": status.get("density_eligible_observation_count"),
        "observation_density_status": status.get("observation_density_status"),
        "last_observation_age_seconds": status.get("last_observation_age_seconds"),
        "last_observation_freshness_limit_seconds": status.get("last_observation_freshness_limit_seconds"),
        "last_observation_freshness_status": status.get("last_observation_freshness_status"),
        "soak_complete": status.get("soak_complete"),
        "soak_1h_complete": status.get("soak_1h_complete"),
        "soak_12h_complete": status.get("soak_12h_complete"),
        "soak_24h_complete": status.get("soak_24h_complete"),
        "high_severity_alerts": status.get("high_severity_alerts"),
    }
    return {
        "adaptive_allocation_24h_distribution.json": {
            **base,
            "paper_allocation_distribution": latest.get("paper_allocation_distribution"),
            "accepted_allocation_count": latest.get("accepted_allocation_count"),
            "blocked_allocation_count": latest.get("blocked_allocation_count"),
            "allocator_decision_counts": latest.get("allocator_decision_counts"),
        },
        "paper_lifecycle_24h_exposure_status.json": {
            **base,
            "open_positions": latest.get("open_positions"),
            "open_positions_count": latest.get("open_positions_count"),
            "exposure_by_symbol": latest.get("exposure_by_symbol"),
            "total_paper_exposure_usdt": latest.get("total_paper_exposure_usdt"),
            "same_symbol_stack_status": latest.get("same_symbol_stack_status"),
            "same_symbol_hedge_status": latest.get("same_symbol_hedge_status"),
        },
        "paper_lifecycle_24h_exit_status.json": {
            **base,
            "exit_reason_counts": latest.get("exit_reason_counts"),
            "stop_takeprofit_trailing": latest.get("stop_takeprofit_trailing"),
            "position_stale_status": latest.get("position_stale_status"),
            "max_position_age_seconds": latest.get("max_position_age_seconds"),
        },
        "paper_lifecycle_24h_outcome_labels_status.json": {
            **base,
            "closed_positions": latest.get("closed_positions"),
            "closed_positions_count": latest.get("closed_positions_count"),
            "outcome_label_count": latest.get("outcome_label_count"),
        },
        "trainer_feedback_24h_status.json": {
            **base,
            "trainer_feedback_row_count": latest.get("trainer_feedback_row_count"),
            "trainer_feedback_rows_count": latest.get("trainer_feedback_rows_count"),
        },
        "paper_pnl_24h_status.json": {
            **base,
            "paper_equity": latest.get("paper_equity"),
            "realized_pnl_usd": latest.get("realized_pnl_usd"),
            "unrealized_pnl_usd": latest.get("unrealized_pnl_usd"),
            "drawdown_bps": latest.get("drawdown_bps"),
            "drawdown_status": latest.get("drawdown_status"),
        },
        "soak_24h_final_operator_dashboard_payload.json": status,
    }


def _write_completion_artifacts(public_dir: Path, runtime_dir: Path, status: dict[str, Any]) -> None:
    if not status.get("completion_marker"):
        return
    for filename, payload in _completion_artifacts(status).items():
        for base in (public_dir, runtime_dir):
            _write_json(base / filename, payload)
    _write_text(
        public_dir / "V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_24H_PAPER_SOAK_COMPLETION_REPORT.md",
        build_report(status),
    )
    _write_text(
        public_dir / "V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_12H_PAPER_SOAK_COMPLETION_REPORT.md",
        build_report(status),
    )
    suffix = _soak_gate_suffix(int(status.get("soak_required_seconds") or DEFAULT_SOAK_REQUIRED_SECONDS))
    _write_text(
        public_dir / f"V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_{suffix}_PAPER_SOAK_COMPLETION_REPORT.md",
        build_report(status),
    )
    _write_text(public_dir / "GO_NO_GO.md", str(status["completion_marker"]) + "\n")


def _mirror_artifacts(status: dict[str, Any], observation: dict[str, Any]) -> None:
    for base in (RUNTIME_DIR, PUBLIC_DIR):
        _write_json(base / "soak_status.json", status)
        _write_json(base / "soak_observation_latest.json", observation)
        _write_json(base / "operator_dashboard_payload.json", status)
    _write_text(PUBLIC_DIR / "GO_NO_GO.md", str(status.get("completion_marker") or status["gate"]) + "\n")
    _write_text(
        PUBLIC_DIR / "V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_24H_PAPER_SOAK_REPORT.md",
        build_report(status),
    )
    _write_text(
        PUBLIC_DIR / "V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_12H_PAPER_SOAK_REPORT.md",
        build_report(status),
    )
    _write_text(
        PUBLIC_DIR
        / f"V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_{_soak_gate_suffix(int(status.get('soak_required_seconds') or DEFAULT_SOAK_REQUIRED_SECONDS))}_PAPER_SOAK_REPORT.md",
        build_report(status),
    )
    _write_completion_artifacts(PUBLIC_DIR, RUNTIME_DIR, status)


def run_once(
    *,
    root: Path = REPO_ROOT,
    redis_client: Any | None = None,
    append_observation: bool = True,
    now: datetime | None = None,
    interval_seconds: int = 300,
    required_seconds: int = DEFAULT_SOAK_REQUIRED_SECONDS,
    observation_run_id: str | None = None,
) -> dict[str, Any]:
    observation = collect_observation(
        root=root,
        redis_client=redis_client,
        now=now,
        observation_run_id=observation_run_id,
    )
    runtime_dir = root / RUNTIME_DIR.relative_to(REPO_ROOT)
    public_dir = root / PUBLIC_DIR.relative_to(REPO_ROOT)
    runtime_jsonl = runtime_dir / OBSERVATION_JSONL
    public_jsonl = public_dir / OBSERVATION_JSONL
    if append_observation:
        _append_jsonl(runtime_jsonl, observation)
        _append_jsonl(public_jsonl, observation)
    observations = [
        row for row in _read_jsonl(runtime_jsonl) if _is_current_position_schema_observation(row)
    ]
    if observation_run_id:
        observations = [
            row for row in observations if row.get("observation_run_id") == observation_run_id
        ]
    if not observations:
        observations = [observation]
    status = build_soak_status(
        observations,
        generated_utc=observation["observed_utc"],
        interval_seconds=interval_seconds,
        required_seconds=required_seconds,
    )
    for base in (runtime_dir, public_dir):
        _write_json(base / "soak_status.json", status)
        _write_json(base / "soak_observation_latest.json", observation)
        _write_json(base / "operator_dashboard_payload.json", status)
    _write_text(public_dir / "GO_NO_GO.md", str(status.get("completion_marker") or status["gate"]) + "\n")
    _write_text(
        public_dir / "V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_24H_PAPER_SOAK_REPORT.md",
        build_report(status),
    )
    _write_text(
        public_dir / "V2_ADAPTIVE_ALLOCATION_AND_TRADE_LIFECYCLE_12H_PAPER_SOAK_REPORT.md",
        build_report(status),
    )
    _write_completion_artifacts(public_dir, runtime_dir, status)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_adaptive_allocation_trade_lifecycle_24h_paper_soak")
    parser.add_argument("--once", action="store_true", help="collect one observation and emit latest status")
    parser.add_argument("--loop", action="store_true", help="run until duration-hours elapses")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--duration-hours", type=float, default=12.0)
    parser.add_argument("--required-hours", type=float, default=DEFAULT_SOAK_WINDOW_HOURS)
    parser.add_argument(
        "--observation-run-id",
        help="Scope density/freshness calculations to observations from this remediation run.",
    )
    args = parser.parse_args(argv)
    required_seconds = max(1, int(float(args.required_hours) * 3600.0))

    if args.loop:
        started = time.monotonic()
        duration_seconds = max(0.0, float(args.duration_hours) * 3600.0)
        while True:
            status = run_once(
                interval_seconds=args.interval_seconds,
                required_seconds=required_seconds,
                observation_run_id=args.observation_run_id,
            )
            print(
                json.dumps(
                    {
                        "gate": status["gate"],
                        "proof_status": status["proof_status"],
                        "completion_marker": status.get("completion_marker"),
                        "elapsed_hours_observed": status["elapsed_hours_observed"],
                        "density_window_elapsed_seconds": status.get("density_window_elapsed_seconds"),
                        "density_eligible_observation_count": status.get("density_eligible_observation_count"),
                        "observation_density_status": status.get("observation_density_status"),
                        "last_observation_freshness_status": status.get("last_observation_freshness_status"),
                        "soak_window_label": status.get("soak_window_label"),
                        "soak_1h_complete": status.get("soak_1h_complete"),
                        "soak_12h_complete": status["soak_12h_complete"],
                        "soak_24h_complete": status["soak_24h_complete"],
                        "high_severity_alerts": status.get("high_severity_alerts", []),
                    },
                    sort_keys=True,
                )
            )
            if time.monotonic() - started >= duration_seconds:
                return 0
            time.sleep(max(30, int(args.interval_seconds)))

    status = run_once(
        interval_seconds=args.interval_seconds,
        required_seconds=required_seconds,
        observation_run_id=args.observation_run_id,
    )
    print(
        json.dumps(
            {
                "gate": status["gate"],
                "proof_status": status["proof_status"],
                "completion_marker": status.get("completion_marker"),
                "density_window_elapsed_seconds": status.get("density_window_elapsed_seconds"),
                "density_eligible_observation_count": status.get("density_eligible_observation_count"),
                "observation_density_status": status.get("observation_density_status"),
                "last_observation_freshness_status": status.get("last_observation_freshness_status"),
                "soak_window_label": status.get("soak_window_label"),
                "soak_1h_complete": status.get("soak_1h_complete"),
                "soak_12h_complete": status.get("soak_12h_complete"),
                "high_severity_alerts": status.get("high_severity_alerts", []),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
