from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence


DEFAULT_OPERATOR_LIMITS = {
    "max_entries_per_hour": 8,
    "max_entries_per_day": 40,
    "max_cost_as_pct_of_gross": 0.35,
    "min_edge_to_cost_ratio": 1.5,
    "max_reentries_per_day": 5,
    "min_median_hold_time_seconds": 300,
}


def _first_present(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = row.get(name)
        if value not in (None, "", [], {}):
            return value
    return None


def _finite_float(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _first_float(row: Mapping[str, Any], *names: str) -> float | None:
    for name in names:
        parsed = _finite_float(row.get(name))
        if parsed is not None:
            return parsed
    return None


def _parse_time(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        raw = float(value)
        if raw > 10_000_000_000:
            raw /= 1000.0
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _median(values: Sequence[float]) -> float | None:
    clean = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not clean:
        return None
    mid = len(clean) // 2
    if len(clean) % 2:
        return clean[mid]
    return (clean[mid - 1] + clean[mid]) / 2.0


def _symbol(row: Mapping[str, Any]) -> str:
    return str(row.get("symbol") or "UNKNOWN").upper()


def _timeframe(row: Mapping[str, Any]) -> str:
    return str(_first_present(row, "thesis_timeframe", "prediction_timeframe", "timeframe") or "UNKNOWN")


def _strategy(row: Mapping[str, Any]) -> str:
    return str(_first_present(row, "strategy_id", "strategy_family", "strategy_selected_mode", "strategy_subtype") or "UNKNOWN")


def _side(row: Mapping[str, Any]) -> str:
    side = str(_first_present(row, "side", "selected_action", "action", "direction") or "UNKNOWN").upper()
    if "LONG" in side or side == "BUY":
        return "LONG"
    if "SHORT" in side or side == "SELL":
        return "SHORT"
    return side


def _regime(row: Mapping[str, Any]) -> str:
    return str(_first_present(row, "market_regime_at_entry", "market_regime", "regime") or "UNKNOWN")


def _entry_time(row: Mapping[str, Any]) -> datetime | None:
    return _parse_time(
        _first_present(
            row,
            "entry_time",
            "opened_at",
            "entry_price_utc",
            "entry_feature_decision_time",
            "decision_time",
            "generated_utc",
            "generated_at",
        )
    )


def _exit_time(row: Mapping[str, Any]) -> datetime | None:
    return _parse_time(
        _first_present(
            row,
            "exit_time",
            "exit_price_utc",
            "closed_utc",
            "closed_at",
            "generated_utc",
            "generated_at",
            "decision_time",
        )
    )


def _notional(row: Mapping[str, Any]) -> float:
    parsed = _first_float(
        row,
        "gross_notional_usd",
        "notional_usd",
        "notional_usdt",
        "order_notional_usd",
        "target_notional_usdt",
        "allocated_notional_usd",
    )
    if parsed is not None:
        return abs(parsed)
    margin = _first_float(row, "allocated_margin_usd", "margin_usd") or 0.0
    leverage = _first_float(row, "effective_leverage", "recommended_leverage") or 1.0
    return abs(margin * leverage)


def _net_pnl(row: Mapping[str, Any]) -> float:
    return _first_float(row, "realized_pnl_usd", "realized_pnl_usdt", "net_pnl_usd", "realized_delta_usdt") or 0.0


def _gross_pnl(row: Mapping[str, Any]) -> float:
    return _first_float(row, "gross_pnl_usd", "gross_pnl_usdt", "gross_realized_pnl_usd", "pnl_before_cost_usd") or 0.0


def _fees(row: Mapping[str, Any]) -> float:
    parsed = _first_float(row, "fees_usd", "fee_usd", "fee_usdt", "expected_fees_usd")
    if parsed is not None:
        return abs(parsed)
    entry = _first_float(row, "entry_fee_usd", "entry_fee_usdt") or 0.0
    exit_fee = _first_float(row, "exit_fee_usd", "exit_fee_usdt") or 0.0
    return abs(entry) + abs(exit_fee)


def _slippage(row: Mapping[str, Any]) -> float:
    return abs(
        _first_float(
            row,
            "realized_slippage_usd",
            "slippage_usd",
            "expected_slippage_usd",
            "implementation_shortfall_usd",
            "expected_shortfall_usd",
        )
        or 0.0
    )


def _funding(row: Mapping[str, Any]) -> float:
    return _first_float(row, "funding_pnl_usd", "funding_usd", "expected_funding_usd") or 0.0


def _hold_seconds(row: Mapping[str, Any]) -> float | None:
    parsed = _first_float(row, "hold_time_seconds", "holding_period_seconds", "duration_seconds")
    if parsed is not None and parsed >= 0:
        return parsed
    start = _entry_time(row)
    end = _exit_time(row)
    if start is None or end is None:
        return None
    seconds = (end - start).total_seconds()
    return seconds if seconds >= 0 else None


def _expected_edge_bps(row: Mapping[str, Any]) -> float | None:
    parsed = _first_float(row, "expected_net_edge_bps", "expected_move_after_cost_bps", "expected_move_bps")
    return abs(parsed) if parsed is not None else None


def _cost_bps(row: Mapping[str, Any]) -> float | None:
    parsed = _first_float(row, "round_trip_cost_bps", "expected_round_trip_cost_bps", "total_cost_bps")
    if parsed is not None:
        return abs(parsed)
    parts = [
        _first_float(row, "actual_observed_spread_entry_bps", "bid_ask_spread_bps") or 0.0,
        _first_float(row, "expected_slippage_bps", "slippage_bps", "realized_slippage_bps") or 0.0,
        _first_float(row, "depth_price_impact_bps", "depth_impact_bps") or 0.0,
        abs(_first_float(row, "funding_bps", "expected_funding_bps") or 0.0),
    ]
    fee_usd = _fees(row)
    notional = _notional(row)
    if notional > 0 and fee_usd > 0:
        parts.append(fee_usd / notional * 10_000.0)
    return sum(parts) if any(parts) else None


def _bucket_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str]:
    return (_symbol(row), _timeframe(row), _strategy(row), _side(row), _regime(row))


def _state_for_bucket(metrics: Mapping[str, Any], limits: Mapping[str, float]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if (metrics.get("net_expectancy") or 0.0) <= 0.0:
        reasons.append("recent_after_cost_expectancy_lte_0")
    if metrics.get("cost_as_pct_of_gross") is not None and metrics["cost_as_pct_of_gross"] > limits["max_cost_as_pct_of_gross"]:
        reasons.append("cost_drag_exceeds_contextual_envelope")
    if metrics.get("edge_to_cost_ratio") is None or metrics["edge_to_cost_ratio"] < limits["min_edge_to_cost_ratio"]:
        reasons.append("edge_to_cost_ratio_inadequate")
    if metrics.get("reentry_count", 0) > limits["max_reentries_per_day"]:
        reasons.append("reentry_frequency_excessive")
    if metrics.get("entries_last_hour", 0) > limits["max_entries_per_hour"]:
        reasons.append("entries_last_hour_exceeds_operator_limit")
    if metrics.get("entries_last_day", 0) > limits["max_entries_per_day"]:
        reasons.append("entries_last_day_exceeds_operator_limit")
    if (
        metrics.get("median_hold_time") is not None
        and metrics["median_hold_time"] < limits["min_median_hold_time_seconds"]
        and metrics.get("net_expectancy", 0.0) <= 0.0
    ):
        reasons.append("turnover_rising_without_net_pnl_improvement")

    if "recent_after_cost_expectancy_lte_0" in reasons or "turnover_rising_without_net_pnl_improvement" in reasons:
        return "CHURN_HALTED", reasons
    if "reentry_frequency_excessive" in reasons:
        return "COOLDOWN", reasons
    if "cost_drag_exceeds_contextual_envelope" in reasons or "edge_to_cost_ratio_inadequate" in reasons:
        return "SHADOW_ONLY", reasons
    if "entries_last_hour_exceeds_operator_limit" in reasons or "entries_last_day_exceeds_operator_limit" in reasons:
        return "REDUCED_FREQUENCY", reasons
    return "ACTIVE", reasons


def evaluate_churn_governor(
    rows: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
    operator_limits: Mapping[str, float] | None = None,
    runtime_wired_to_entry_gate: bool = False,
) -> dict[str, Any]:
    """Evaluate adaptive paper churn/turnover state from supplied paper outcomes.

    This function is intentionally pure: it does not read Redis, write Redis, or
    permit/block any trade by itself. Runtime callers must explicitly wire the
    returned state into an entry gate before it can affect paper execution.
    """

    limits = {**DEFAULT_OPERATOR_LIMITS, **dict(operator_limits or {})}
    now_utc = now.astimezone(timezone.utc) if now else datetime.now(timezone.utc)
    rows_by_bucket: dict[tuple[str, str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_bucket[_bucket_key(row)].append(row)

    bucket_payloads: dict[str, Any] = {}
    state_counts: Counter[str] = Counter()
    for key, bucket_rows in sorted(rows_by_bucket.items()):
        symbol, timeframe, strategy, side, regime = key
        entries_last_hour = 0
        entries_last_day = 0
        reentry_count = max(0, len(bucket_rows) - 1)
        net_values = [_net_pnl(row) for row in bucket_rows]
        gross = sum(_gross_pnl(row) for row in bucket_rows)
        fees = sum(_fees(row) for row in bucket_rows)
        slippage = sum(_slippage(row) for row in bucket_rows)
        funding = sum(_funding(row) for row in bucket_rows)
        edge_values = [value for row in bucket_rows if (value := _expected_edge_bps(row)) is not None]
        cost_values = [value for row in bucket_rows if (value := _cost_bps(row)) is not None and value > 0.0]
        hold_values = [value for row in bucket_rows if (value := _hold_seconds(row)) is not None]
        for row in bucket_rows:
            stamp = _entry_time(row) or _exit_time(row)
            if stamp is None:
                continue
            if stamp >= now_utc - timedelta(hours=1):
                entries_last_hour += 1
            if stamp >= now_utc - timedelta(days=1):
                entries_last_day += 1
        cost_drag = (fees + slippage + abs(funding)) / abs(gross) if abs(gross) > 1e-12 else None
        median_cost = _median(cost_values)
        median_edge = _median(edge_values)
        edge_to_cost = (median_edge / median_cost) if median_edge is not None and median_cost and median_cost > 0 else None
        metrics = {
            "symbol": symbol,
            "timeframe": timeframe,
            "strategy": strategy,
            "side": side,
            "regime": regime,
            "economic_trade_count": len(bucket_rows),
            "entries_last_hour": entries_last_hour,
            "entries_last_day": entries_last_day,
            "turnover_usd": sum(_notional(row) for row in bucket_rows),
            "fees_usd": fees,
            "slippage_usd": slippage,
            "funding_usd": funding,
            "cost_as_pct_of_gross": cost_drag,
            "net_expectancy": sum(net_values) / len(net_values) if net_values else None,
            "edge_to_cost_ratio": edge_to_cost,
            "median_hold_time": _median(hold_values),
            "reentry_count": reentry_count,
        }
        state, reasons = _state_for_bucket(metrics, limits)
        state_counts[state] += 1
        metrics["state"] = state
        metrics["block_reasons"] = reasons
        bucket_payloads["|".join(key)] = metrics

    blocking_states = {"SHADOW_ONLY", "COOLDOWN", "CHURN_HALTED"}
    blocked_bucket_count = sum(count for state, count in state_counts.items() if state in blocking_states)
    status = (
        "PASS_PAPER_CHURN_GOVERNOR_WIRED_TO_ENTRY_GATE"
        if runtime_wired_to_entry_gate
        else "BLOCKED_PAPER_CHURN_GOVERNOR_NOT_WIRED_TO_ENTRY_GATE"
    )
    return {
        "schema_version": "paper_churn_governor_status_v1",
        "generated_utc": now_utc.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": status,
        "evaluation_status": "PASS_PAPER_CHURN_GOVERNOR_EVALUATED" if rows else "BLOCKED_NO_ECONOMIC_OUTCOME_ROWS",
        "read_only_audit_no_runtime_change": True,
        "operator_limits": dict(sorted(limits.items())),
        "tracked_dimensions": ["symbol", "timeframe", "strategy", "side", "regime"],
        "state_definitions": ["ACTIVE", "REDUCED_FREQUENCY", "SHADOW_ONLY", "COOLDOWN", "CHURN_HALTED"],
        "rows_examined": len(rows),
        "bucket_count": len(bucket_payloads),
        "blocked_bucket_count": blocked_bucket_count,
        "state_counts": dict(sorted(state_counts.items())),
        "buckets": bucket_payloads,
        "must_block_new_entries_when": [
            "recent_after_cost_expectancy <= 0",
            "cost drag exceeds contextual envelope",
            "edge-to-cost safety ratio is inadequate",
            "re-entry frequency is excessive",
            "turnover is rising without net PnL improvement",
        ],
        "runtime_wired_to_entry_gate": bool(runtime_wired_to_entry_gate),
        "paper_fill_allowed": False,
        "routes_to_live": False,
        "places_real_order": False,
    }


def evaluate_churn_governor_entry_gate(
    rows: Sequence[Mapping[str, Any]],
    candidate: Mapping[str, Any],
    *,
    now: datetime | None = None,
    operator_limits: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Return the paper-entry decision for a candidate from rolling outcomes.

    This is intentionally paper-only and side-effect free. It does not create
    volume: missing history, missing matching bucket evidence, and every
    non-ACTIVE bucket state fail closed.
    """

    governor = evaluate_churn_governor(
        rows,
        now=now,
        operator_limits=operator_limits,
        runtime_wired_to_entry_gate=True,
    )
    candidate_bucket_key = "|".join(_bucket_key(candidate))
    bucket = governor.get("buckets", {}).get(candidate_bucket_key)
    reasons: list[str] = []
    if governor.get("evaluation_status") != "PASS_PAPER_CHURN_GOVERNOR_EVALUATED":
        reasons.append("no_economic_outcome_rows_for_churn_governor")
    if bucket is None:
        reasons.append("no_matching_governor_bucket_history")
    else:
        state = str(bucket.get("state") or "UNKNOWN")
        if state != "ACTIVE":
            reasons.append(f"bucket_state_not_active:{state}")
            reasons.extend(str(reason) for reason in bucket.get("block_reasons") or [])

    allowed = not reasons
    return {
        "schema_version": "paper_churn_governor_entry_gate_v1",
        "generated_utc": governor.get("generated_utc"),
        "status": "PASS_PAPER_CHURN_GOVERNOR_ENTRY_GATE" if allowed else "BLOCKED_PAPER_CHURN_GOVERNOR_ENTRY_GATE",
        "allowed": allowed,
        "candidate_bucket_key": candidate_bucket_key,
        "candidate_bucket": bucket,
        "reasons": sorted(set(reasons)),
        "governor_status": governor.get("status"),
        "evaluation_status": governor.get("evaluation_status"),
        "runtime_wired_to_entry_gate": True,
        "operator_limits": governor.get("operator_limits"),
        "paper_only": True,
        "paper_fill_allowed": allowed,
        "routes_to_live": False,
        "places_real_order": False,
    }
