"""Read-only Phase 6 adaptive capital status helpers."""
from __future__ import annotations

import math
from typing import Any, Mapping


SCHEMA_VERSION = "phase6_adaptive_capital_simulation_v1"
REQUIRED_SIMULATION_FIELDS = (
    "recommended_leverage",
    "recommended_margin_mode",
    "target_notional_usd",
    "allocated_margin_usd",
    "risk_budget_usd",
    "liquidation_price_estimate",
    "liquidation_buffer_bps",
    "max_loss_if_stop_hit",
    "expected_net_pnl_usd",
    "risk_reward",
    "risk_of_ruin_contribution",
    "portfolio_exposure_after_trade",
    "correlation_exposure_after_trade",
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [_as_dict(row) for row in value]


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _positive_notional_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if (_float(_first_present(row.get("target_notional_usd"), row.get("target_notional_usdt"))) or 0.0) > 0.0
    ]


def _unique_positive_numbers(rows: list[dict[str, Any]], *fields: str) -> set[float]:
    values: set[float] = set()
    for row in rows:
        value = _float(_first_present(*(row.get(field) for field in fields)))
        if value is not None and value > 0.0:
            values.add(round(value, 8))
    return values


def _profit_factor(row: Mapping[str, Any]) -> float | None:
    return _float(
        _first_present(
            row.get("bucket_profit_factor"),
            row.get("profit_factor"),
            _as_dict(row.get("strategy_bucket_performance_state")).get("profit_factor"),
        )
    )


def _missing_required_fields(row: Mapping[str, Any]) -> list[str]:
    missing: list[str] = []
    for field in REQUIRED_SIMULATION_FIELDS:
        value = row.get(field)
        if field == "target_notional_usd":
            value = _first_present(value, row.get("target_notional_usdt"))
        if value in (None, "", [], {}):
            missing.append(field)
    return missing


def _risk_budget_linked_to_edge(rows: list[dict[str, Any]]) -> bool:
    pairs: list[tuple[float, float]] = []
    for row in rows:
        edge = abs(_float(row.get("expected_move_after_cost_bps")) or 0.0)
        risk_budget = _float(row.get("risk_budget_usd"))
        if edge > 0.0 and risk_budget is not None and risk_budget > 0.0:
            pairs.append((edge, risk_budget))
    if len(pairs) < 2:
        return False
    for left_edge, left_budget in pairs:
        for right_edge, right_budget in pairs:
            if right_edge > left_edge and right_budget > left_budget:
                return True
    return False


def build_adaptive_leverage_margin_simulation_status(
    allocation_rows: list[Mapping[str, Any]],
    *,
    runtime_counts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows = _rows(allocation_rows)
    positive_rows = _positive_notional_rows(rows)
    missing_rows = [
        {
            "allocation_id": row.get("allocation_id"),
            "symbol": row.get("symbol"),
            "missing_fields": missing,
        }
        for row in rows
        if (missing := _missing_required_fields(row))
    ]
    leverage_values = _unique_positive_numbers(positive_rows, "recommended_leverage", "effective_leverage")
    notional_values = _unique_positive_numbers(positive_rows, "target_notional_usd", "target_notional_usdt")
    margin_values = _unique_positive_numbers(positive_rows, "allocated_margin_usd")
    live_mutation_rows = [
        row
        for row in rows
        if _as_dict(row.get("model_inputs")).get("leverage_live_mutation_allowed") is True
        or _as_dict(row.get("model_inputs")).get("margin_mode_live_mutation_allowed") is True
        or row.get("live_order") is True
        or row.get("places_real_order") is True
    ]
    leverage_pf_violations = [
        {
            "allocation_id": row.get("allocation_id"),
            "symbol": row.get("symbol"),
            "recommended_leverage": _float(row.get("recommended_leverage")),
            "profit_factor": _profit_factor(row),
        }
        for row in positive_rows
        if (_profit_factor(row) is not None and (_profit_factor(row) or 0.0) < 1.0)
        and (_float(row.get("recommended_leverage")) or 1.0) > 1.0
    ]
    pass_conditions = {
        "simulation_rows_present": bool(rows),
        "positive_notional_rows_present": bool(positive_rows),
        "all_required_phase6_fields_present": not missing_rows,
        "recommended_leverage_not_static_1x": any(value > 1.0 for value in leverage_values),
        "target_notional_not_static": len(notional_values) > 1,
        "allocated_margin_not_static": len(margin_values) > 1,
        "risk_budget_linked_to_edge": _risk_budget_linked_to_edge(positive_rows),
        "leverage_does_not_rise_when_profit_factor_below_1": not leverage_pf_violations,
        "simulation_only_no_live_mutation": not live_mutation_rows,
    }
    overall_pass = all(pass_conditions.values())
    return {
        "schema_version": f"{SCHEMA_VERSION}_leverage_margin",
        "status": (
            "ADAPTIVE_LEVERAGE_MARGIN_SIMULATION_READY"
            if overall_pass
            else "ADAPTIVE_LEVERAGE_MARGIN_SIMULATION_BLOCKED"
        ),
        "overall_pass": overall_pass,
        "runtime_counts": dict(runtime_counts or {}),
        "row_count": len(rows),
        "positive_notional_row_count": len(positive_rows),
        "recommended_leverage_values": sorted(leverage_values),
        "recommended_margin_modes": sorted(
            {
                str(row.get("recommended_margin_mode"))
                for row in positive_rows
                if row.get("recommended_margin_mode") not in (None, "")
            }
        ),
        "target_notional_unique_count": len(notional_values),
        "allocated_margin_unique_count": len(margin_values),
        "pass_conditions": pass_conditions,
        "sample_missing_required_fields": missing_rows[:25],
        "sample_leverage_pf_violations": leverage_pf_violations[:25],
        "live_mutation_violation_count": len(live_mutation_rows),
        "paper_or_live_pre_submit_simulation_only": True,
        "no_live_mutation": True,
    }


def build_capital_productivity_runtime_status(
    allocation_rows: list[Mapping[str, Any]],
    *,
    runtime_counts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows = _positive_notional_rows(_rows(allocation_rows))
    expected_pnl = [_float(row.get("expected_net_pnl_usd")) or 0.0 for row in rows]
    margins = [_float(row.get("allocated_margin_usd")) or 0.0 for row in rows]
    margin_return = [
        pnl / margin
        for pnl, margin in zip(expected_pnl, margins, strict=False)
        if margin > 0.0
    ]
    pass_conditions = {
        "runtime_or_simulation_rows_present": bool(rows),
        "expected_net_pnl_present": bool(rows) and all(row.get("expected_net_pnl_usd") is not None for row in rows),
        "allocated_margin_present": bool(rows) and all((_float(row.get("allocated_margin_usd")) or 0.0) > 0.0 for row in rows),
        "positive_margin_return_exists": any(value > 0.0 for value in margin_return),
    }
    overall_pass = all(pass_conditions.values())
    return {
        "schema_version": f"{SCHEMA_VERSION}_capital_productivity",
        "status": "CAPITAL_PRODUCTIVITY_RUNTIME_READY" if overall_pass else "CAPITAL_PRODUCTIVITY_RUNTIME_BLOCKED",
        "overall_pass": overall_pass,
        "runtime_counts": dict(runtime_counts or {}),
        "row_count": len(rows),
        "expected_net_pnl_total_usd": round(sum(expected_pnl), 8),
        "allocated_margin_total_usd": round(sum(margins), 8),
        "best_expected_margin_return": round(max(margin_return), 8) if margin_return else None,
        "pass_conditions": pass_conditions,
        "paper_or_live_pre_submit_simulation_only": True,
        "no_live_mutation": True,
    }


def build_risk_of_ruin_runtime_status(
    allocation_rows: list[Mapping[str, Any]],
    *,
    runtime_counts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows = _positive_notional_rows(_rows(allocation_rows))
    contributions = [
        _float(row.get("risk_of_ruin_contribution"))
        for row in rows
        if _float(row.get("risk_of_ruin_contribution")) is not None
    ]
    high_leverage_negative_pf = [
        row
        for row in rows
        if (_profit_factor(row) is not None and (_profit_factor(row) or 0.0) < 1.0)
        and (_float(row.get("recommended_leverage")) or 1.0) > 1.0
    ]
    pass_conditions = {
        "runtime_or_simulation_rows_present": bool(rows),
        "risk_of_ruin_contribution_present": len(contributions) == len(rows) and bool(rows),
        "risk_of_ruin_contribution_bounded": all(0.0 <= value <= 1.0 for value in contributions),
        "no_leverage_increase_when_profit_factor_below_1": not high_leverage_negative_pf,
    }
    overall_pass = all(pass_conditions.values())
    return {
        "schema_version": f"{SCHEMA_VERSION}_risk_of_ruin",
        "status": "RISK_OF_RUIN_RUNTIME_READY" if overall_pass else "RISK_OF_RUIN_RUNTIME_BLOCKED",
        "overall_pass": overall_pass,
        "runtime_counts": dict(runtime_counts or {}),
        "row_count": len(rows),
        "max_risk_of_ruin_contribution": round(max(contributions), 8) if contributions else None,
        "mean_risk_of_ruin_contribution": (
            round(sum(contributions) / len(contributions), 8) if contributions else None
        ),
        "high_leverage_negative_pf_count": len(high_leverage_negative_pf),
        "pass_conditions": pass_conditions,
        "paper_or_live_pre_submit_simulation_only": True,
        "no_live_mutation": True,
    }


def build_portfolio_exposure_runtime_status(
    allocation_rows: list[Mapping[str, Any]],
    *,
    runtime_counts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    rows = _positive_notional_rows(_rows(allocation_rows))
    exposure_values = [
        _float(row.get("portfolio_exposure_after_trade"))
        for row in rows
        if _float(row.get("portfolio_exposure_after_trade")) is not None
    ]
    correlation_values = [
        _float(row.get("correlation_exposure_after_trade"))
        for row in rows
        if _float(row.get("correlation_exposure_after_trade")) is not None
    ]
    pass_conditions = {
        "runtime_or_simulation_rows_present": bool(rows),
        "portfolio_exposure_after_trade_present": len(exposure_values) == len(rows) and bool(rows),
        "correlation_exposure_after_trade_present": len(correlation_values) == len(rows) and bool(rows),
        "correlation_exposure_after_trade_bounded": all(0.0 <= value <= 1.0 for value in correlation_values),
    }
    overall_pass = all(pass_conditions.values())
    return {
        "schema_version": f"{SCHEMA_VERSION}_portfolio_exposure",
        "status": "PORTFOLIO_EXPOSURE_RUNTIME_READY" if overall_pass else "PORTFOLIO_EXPOSURE_RUNTIME_BLOCKED",
        "overall_pass": overall_pass,
        "runtime_counts": dict(runtime_counts or {}),
        "row_count": len(rows),
        "max_portfolio_exposure_after_trade": round(max(exposure_values), 8) if exposure_values else None,
        "max_correlation_exposure_after_trade": round(max(correlation_values), 8) if correlation_values else None,
        "pass_conditions": pass_conditions,
        "paper_or_live_pre_submit_simulation_only": True,
        "no_live_mutation": True,
    }
