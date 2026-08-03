"""Read-only Phase 5 paper exit and churn status helpers."""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Mapping


SCHEMA_VERSION = "phase5_paper_exit_quality_v1"
STATIC_EXIT_TOGGLES = (
    "static_stop_loss_enabled",
    "static_take_profit_enabled",
    "static_profit_lock_enabled",
    "static_profit_bank_enabled",
    "static_max_hold_enabled",
)
PATH_FIELDS = (
    "mfe_bps",
    "mae_bps",
    "intra_trade_high_price",
    "intra_trade_low_price",
)
STATIC_CLOSE_REASONS = {
    "TIER_1_STOP_LOSS",
    "TIER_2_TAKE_PROFIT",
    "TIER_2_PROFIT_LOCK",
    "TIER_2_PROFIT_BANK",
    "TIER_4_MAX_HOLD_TIME",
}
ADAPTIVE_CLOSE_REASONS = {
    "TIER_0_EMERGENCY_LIQUIDATION_DISTANCE",
    "TIER_0_DRAWDOWN_EMERGENCY_EXIT",
    "TIER_1_ATR_VOLATILITY_STOP",
    "TIER_1_MICROSTRUCTURE_REVERSAL_EXIT",
    "TIER_1_MODEL_REVERSAL_EXIT",
    "TIER_1_CONFIDENCE_DECAY_EXIT",
    "TIER_2_DYNAMIC_TAKE_PROFIT",
    "TIER_2_TRAILING_STOP",
    "TIER_3_MODEL_REVERSAL_NETTING",
}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, dict)]


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


def _close_reason(row: Mapping[str, Any]) -> str:
    return str(row.get("close_reason") or row.get("exit_reason") or "UNKNOWN_CLOSE_REASON")


def _realized_pnl_usd(row: Mapping[str, Any]) -> float | None:
    return _float(
        _first_present(
            row.get("realized_net_pnl_usd"),
            row.get("realized_pnl_usd"),
            row.get("realized_pnl_usdt"),
        )
    )


def _realized_pnl_bps(row: Mapping[str, Any]) -> float | None:
    return _float(
        _first_present(
            row.get("realized_after_cost_return_bps"),
            row.get("realized_net_pnl_bps"),
            row.get("realized_pnl_bps"),
            row.get("pnl_effect_bps"),
        )
    )


def build_adaptive_exit_policy_status(
    stop_takeprofit_status: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Summarize whether active paper runtime is using adaptive exits only."""
    status = _as_dict(stop_takeprofit_status)
    static_toggle_state = {field: status.get(field) for field in STATIC_EXIT_TOGGLES}
    static_disabled = all(status.get(field) is False for field in STATIC_EXIT_TOGGLES)
    adaptive_fields = {
        "paper_exit_policy_version": status.get("paper_exit_policy_version"),
        "trailing_stop_enabled": status.get("trailing_stop_enabled"),
        "min_profit_before_trailing_bps": status.get("min_profit_before_trailing_bps"),
        "trailing_stop_min_after_cost_buffer_bps": status.get(
            "trailing_stop_min_after_cost_buffer_bps"
        ),
        "atr_trailing_stop_multiplier": status.get("atr_trailing_stop_multiplier"),
    }
    adaptive_fields_present = all(value not in (None, "") for value in adaptive_fields.values())
    pass_conditions = {
        "static_stop_loss_disabled": status.get("static_stop_loss_enabled") is False,
        "static_take_profit_disabled": status.get("static_take_profit_enabled") is False,
        "static_profit_lock_disabled": status.get("static_profit_lock_enabled") is False,
        "static_profit_bank_disabled": status.get("static_profit_bank_enabled") is False,
        "static_max_hold_disabled": status.get("static_max_hold_enabled") is False,
        "adaptive_exit_fields_present": adaptive_fields_present,
    }
    overall_pass = all(pass_conditions.values())
    blockers = [name for name, passed in pass_conditions.items() if not passed]
    return {
        "schema_version": f"{SCHEMA_VERSION}_adaptive_exit_policy",
        "status": (
            "ADAPTIVE_EXIT_POLICY_READY"
            if overall_pass
            else "ADAPTIVE_EXIT_POLICY_BLOCKED_STATIC_OR_MISSING_ADAPTIVE_FIELDS"
        ),
        "overall_pass": overall_pass,
        "pass_conditions": pass_conditions,
        "blockers": blockers,
        "static_exit_toggle_state": static_toggle_state,
        "adaptive_exit_fields": adaptive_fields,
        "new_close_event_count": int(status.get("new_close_event_count") or 0),
        "active_policy_closed_trade_count": int(status.get("active_policy_closed_trade_count") or 0),
        "active_policy_close_reasons": _as_dict(status.get("active_policy_close_reasons")),
        "paper_only": True,
        "no_live_mutation": True,
        "runtime_thresholds_changed": False,
    }


def build_mfe_mae_exit_quality_status(
    closed_trades: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarize MFE/MAE path quality and exit reason health for closed paper rows."""
    rows = [_as_dict(row) for row in closed_trades]
    dirty_rows: list[dict[str, Any]] = []
    static_reason_count = 0
    adaptive_reason_count = 0
    model_reversal_rows: list[dict[str, Any]] = []
    wasted_mfe_rows: list[dict[str, Any]] = []
    reason_counts: Counter[str] = Counter()
    for row in rows:
        reason = _close_reason(row)
        reason_counts[reason] += 1
        missing = [field for field in PATH_FIELDS if _float(row.get(field)) is None]
        if missing:
            dirty_rows.append({
                "close_id": row.get("close_id"),
                "trainer_feedback_id": row.get("trainer_feedback_id"),
                "symbol": row.get("symbol"),
                "missing_path_fields": missing,
            })
        if reason in STATIC_CLOSE_REASONS:
            static_reason_count += 1
        if reason in ADAPTIVE_CLOSE_REASONS:
            adaptive_reason_count += 1
        if "MODEL_REVERSAL" in reason:
            model_reversal_rows.append(row)
        mfe_bps = _float(row.get("mfe_bps"))
        realized_bps = _realized_pnl_bps(row)
        realized_usd = _realized_pnl_usd(row)
        if (
            mfe_bps is not None
            and mfe_bps > 0.0
            and (
                (realized_bps is not None and realized_bps < 0.0)
                or (realized_bps is None and realized_usd is not None and realized_usd < 0.0)
            )
        ):
            wasted_mfe_rows.append({
                "close_id": row.get("close_id"),
                "trainer_feedback_id": row.get("trainer_feedback_id"),
                "symbol": row.get("symbol"),
                "close_reason": reason,
                "mfe_bps": mfe_bps,
                "realized_pnl_bps": realized_bps,
                "realized_pnl_usd": realized_usd,
            })
    model_reversal_pnl = sum(_realized_pnl_usd(row) or 0.0 for row in model_reversal_rows)
    model_reversal_profitable_or_absent = not model_reversal_rows or model_reversal_pnl > 0.0
    closed_count = len(rows)
    pass_conditions = {
        "runtime_has_closed_trades": closed_count > 0,
        "closed_trades_have_mfe_mae_path": closed_count > 0 and not dirty_rows,
        "static_exit_reason_count_zero": static_reason_count == 0,
        "adaptive_exit_reason_present_when_closed": closed_count == 0 or adaptive_reason_count > 0,
        "model_reversal_exits_profitable_or_absent": model_reversal_profitable_or_absent,
        "mfe_not_wasted_into_negative_realized_rows": not wasted_mfe_rows,
    }
    overall_pass = all(pass_conditions.values())
    return {
        "schema_version": f"{SCHEMA_VERSION}_mfe_mae_exit_quality",
        "status": (
            "MFE_MAE_EXIT_QUALITY_READY"
            if overall_pass
            else "MFE_MAE_EXIT_QUALITY_BLOCKED_RUNTIME_OR_DIRTY_PATH"
        ),
        "overall_pass": overall_pass,
        "pass_conditions": pass_conditions,
        "closed_trade_count": closed_count,
        "dirty_path_row_count": len(dirty_rows),
        "static_exit_reason_count": static_reason_count,
        "adaptive_exit_reason_count": adaptive_reason_count,
        "model_reversal_exit_count": len(model_reversal_rows),
        "model_reversal_realized_pnl_usd": round(model_reversal_pnl, 8),
        "wasted_mfe_negative_realized_count": len(wasted_mfe_rows),
        "close_reason_counts": dict(sorted(reason_counts.items())),
        "sample_dirty_path_rows": dirty_rows[:25],
        "sample_wasted_mfe_rows": wasted_mfe_rows[:25],
        "paper_only": True,
        "no_live_mutation": True,
        "runtime_thresholds_changed": False,
    }


def build_churn_equity_bleed_block_status(
    churn_status: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Normalize the paper churn governor into the Phase 5 artifact shape."""
    status = _as_dict(churn_status)
    pass_conditions = _as_dict(status.get("pass_conditions"))
    if not pass_conditions:
        pass_conditions = {
            "duplicate_new_entries_eq_zero": status.get("duplicate_new_entries") in (0, None),
            "same_candle_reentry_unexplained_eq_zero": status.get(
                "same_candle_reentry_unexplained"
            ) in (0, None),
            "cost_drag_within_envelope": status.get("cost_drag_within_envelope") is not False,
            "economic_trade_count_reconciles": status.get("economic_trade_count_reconciles") is not False,
        }
    overall_pass = bool(pass_conditions) and all(value is True for value in pass_conditions.values())
    return {
        "schema_version": f"{SCHEMA_VERSION}_churn_equity_bleed",
        "status": "CHURN_EQUITY_BLEED_BLOCK_READY" if overall_pass else "CHURN_EQUITY_BLEED_BLOCK_ACTIVE_OR_INCOMPLETE",
        "overall_pass": overall_pass,
        "governor_state": status.get("state") or status.get("status"),
        "new_entries_allowed_by_churn_governor": status.get("new_entries_allowed"),
        "pass_conditions": pass_conditions,
        "duplicate_new_entries": int(status.get("duplicate_new_entries") or 0),
        "blocked_duplicate_or_churn_attempt_rows": int(
            status.get("blocked_duplicate_or_churn_attempt_rows") or 0
        ),
        "same_candle_reentry_count": int(status.get("same_candle_reentry_count") or 0),
        "same_prediction_duplicate_count": int(status.get("same_prediction_duplicate_count") or 0),
        "same_signal_duplicate_count": int(status.get("same_signal_duplicate_count") or 0),
        "cost_drag_bps": status.get("cost_drag_bps"),
        "edge_to_cost_ratio": status.get("edge_to_cost_ratio"),
        "paper_only": status.get("paper_only") is not False,
        "no_live_mutation": status.get("places_real_order") is not True and status.get("routes_to_live") is not True,
        "runtime_thresholds_changed": False,
    }


def build_execution_cost_parity_status(
    rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Check paper rows carry production-equivalent cost evidence."""
    source_rows = [_as_dict(row) for row in rows]
    row_checks: list[dict[str, Any]] = []
    for row in source_rows:
        has_fee = _first_present(row.get("fee_bps"), row.get("fees_usd"), row.get("expected_fees_usd")) is not None
        has_slippage = _first_present(
            row.get("expected_slippage_bps"),
            row.get("realized_slippage_bps"),
            row.get("expected_slippage_usd"),
            row.get("realized_slippage_usd"),
        ) is not None
        has_funding = _first_present(
            row.get("expected_funding_bps"),
            row.get("funding_rate"),
            row.get("funding_pnl_usd"),
            row.get("expected_funding_usd"),
        ) is not None
        has_spread = _first_present(
            row.get("actual_observed_spread_entry_bps"),
            row.get("actual_observed_spread_exit_bps"),
            row.get("observed_bid_ask_spread_bps"),
            row.get("bid_ask_spread_bps"),
        ) is not None
        fallback_as_real = any(
            row.get(field) is True
            for field in (
                "bid_ask_spread_bps_fallback",
                "expected_slippage_bps_fallback",
                "fee_bps_fallback",
                "expected_funding_bps_fallback",
            )
        )
        missing = [
            name
            for name, present in (
                ("fee", has_fee),
                ("slippage", has_slippage),
                ("funding", has_funding),
                ("spread", has_spread),
            )
            if not present
        ]
        row_checks.append({
            "row_id": _first_present(
                row.get("close_id"),
                row.get("fill_id"),
                row.get("ledger_row_id"),
                row.get("prediction_id"),
            ),
            "symbol": row.get("symbol"),
            "missing_cost_components": missing,
            "fallback_treated_as_real": fallback_as_real,
        })
    incomplete_rows = [
        row
        for row in row_checks
        if row["missing_cost_components"] or row["fallback_treated_as_real"]
    ]
    pass_conditions = {
        "runtime_has_cost_rows": bool(source_rows),
        "all_rows_have_fee_slippage_funding_spread": bool(source_rows) and not incomplete_rows,
        "no_fallback_value_treated_as_real": not any(row["fallback_treated_as_real"] for row in row_checks),
    }
    overall_pass = all(pass_conditions.values())
    return {
        "schema_version": f"{SCHEMA_VERSION}_execution_cost_parity",
        "status": (
            "EXECUTION_COST_PARITY_READY"
            if overall_pass
            else "EXECUTION_COST_PARITY_BLOCKED_RUNTIME_OR_INCOMPLETE_COST_EVIDENCE"
        ),
        "overall_pass": overall_pass,
        "pass_conditions": pass_conditions,
        "source_row_count": len(source_rows),
        "incomplete_cost_row_count": len(incomplete_rows),
        "sample_incomplete_cost_rows": incomplete_rows[:25],
        "paper_only": True,
        "no_live_mutation": True,
        "runtime_thresholds_changed": False,
    }
