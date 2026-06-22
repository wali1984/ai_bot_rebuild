"""Read-only adaptive capital productivity status publisher.

Builds the operator evidence required for the adaptive capital productivity
phase. This module writes local JSON/Markdown artifacts only; it never writes
Redis, mutates exchange leverage or margin mode, or submits/cancels orders.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.adaptive_capital_allocator.counterfactual import (
    CounterfactualRiskEnvelope,
    run_counterfactual_sweep,
    run_rare_event_capital_stress,
    run_runtime_allocation_rare_event_stress,
)
from v2.backend.app.services.adaptive_capital_allocator.contracts import (
    ADAPTIVE_CAPITAL_POLICY_VERSION,
    RiskEnvelope,
)
from v2.backend.app.services.paper_trade_management.outcomes import (
    FUNDING_PNL_ACCOUNTING_FORMULA,
    FUNDING_PNL_ACCOUNTING_VERSION,
)


SCHEMA_VERSION = "v2_adaptive_capital_productivity_status_v1"
GOAL_ID = "V2_ADAPTIVE_CAPITAL_PRODUCTIVITY_COMPOUNDING_AND_1000X_FEASIBILITY"
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUT_DIR = REPO_ROOT / "v2/frontend/public/operator_runtime/v2_adaptive_capital_productivity/latest"
POST_HOC_REPLAY_BUNDLE_PATH = (
    REPO_ROOT
    / "v2/frontend/public/v2_post_hoc_replay_outcome_miner/latest/replay_outcome_bundles.jsonl"
)
POST_HOC_REPLAY_PRIMARY_WINDOW_ID = "5m"
NATIVE_TRAINER_REPLAY_EVIDENCE_ROWS_PATH = (
    REPO_ROOT
    / "v2/frontend/public/v2_native_trainer_dataset_and_baseline_model/latest"
    / "v2_native_trainer_replay_evidence_rows.jsonl"
)
CLOSED_CANDLE_REPLAY_EVIDENCE_ROWS_PATH = (
    DEFAULT_OUT_DIR / "closed_candle_replay_evidence_rows.jsonl"
)
OUT_OF_SAMPLE_HOLDOUT_REVERIFY_ROWS_PATH = (
    DEFAULT_OUT_DIR / "out_of_sample_holdout_reverify_rows.jsonl"
)
OUT_OF_SAMPLE_REALTIME_REVERIFY_ROWS_PATH = (
    DEFAULT_OUT_DIR / "out_of_sample_realtime_paper_reverify_rows.jsonl"
)
P0_GOAL_DIR = REPO_ROOT / "goal_state/V2_P0_DIRECTIONAL_EXIT_EXECUTION_RISK_AND_ADAPTIVE_CAPITAL_REMEDIATION"
P0_POLICY_VERSION = "PAPER_EXIT_AFTER_COST_TRAILING_FLOOR_V1"
LIVE_GATE = "blocked_human_only"
PAPER_INTENT_SNAPSHOT_RETRY_COUNT = 10
PAPER_INTENT_SNAPSHOT_RETRY_SECONDS = 0.5

STATUS_FILENAMES = (
    "capital_productivity_runtime_status.json",
    "margin_notional_leverage_accounting_status.json",
    "a_grade_dynamic_calibration_status.json",
    "a_grade_bucket_performance_matrix.json",
    "positive_edge_below_a_grade_resolution.json",
    "accelerated_counterfactual_replay_status.json",
    "counterfactual_efficient_frontier.json",
    "counterfactual_capital_sweep_status.json",
    "adaptive_capital_policy_status.json",
    "portfolio_correlation_budget_status.json",
    "compounding_equity_status.json",
    "rare_event_capital_stress_status.json",
    "one_thousand_x_feasibility_status.json",
    "out_of_sample_live_grade_reverify_status.json",
    "paper_live_pre_submit_parity_status.json",
    "paper_exploration_tier_status.json",
    "v2_stop_waiting_a_grade_calibration_accelerated_replay_and_capital_deployment_status.json",
    "operator_dashboard_payload.json",
)

MANDATORY_PER_TRADE_FIELDS = (
    "risk_budget_usd",
    "gross_notional_usd",
    "allocated_margin_usd",
    "recommended_leverage",
    "effective_leverage",
    "recommended_margin_mode",
    "stop_distance_bps",
    "liquidation_price_estimate",
    "liquidation_buffer_bps",
    "expected_fees_usd",
    "expected_slippage_usd",
    "expected_funding_usd",
    "expected_net_pnl_usd",
    "expected_shortfall_usd",
    "hedge_budget_usd",
    "capital_allocation_reason",
)

RECONCILABLE_POLICY_FUNDING_FIELDS = (
    "policy_activated_at",
    "expected_funding_bps",
    "funding_rate",
    "funding_bps",
    "funding_rate_bps",
    "funding_interval_seconds",
    "expected_funding_bps_source",
)

PRE_SUBMIT_PARITY_REQUIRED_FIELDS = (
    "symbol",
    "timeframe",
    "side",
    "entry_price",
    "quantity",
    *MANDATORY_PER_TRADE_FIELDS,
)

SIZED_ALLOCATOR_DECISIONS = {"ALLOW_WITH_SIZE", "REDUCE_SIZE"}
ACTIVE_OR_HELD_PAPER_INTENT_SOURCES = {
    "v2:paper:intents",
    "v2:paper:intents_held_by_paper_fill_gate",
}
CORRELATION_CANDLE_TIMEFRAME = "1m"
MIN_CORRELATION_RETURN_POINTS = 30
MAX_CORRELATION_CANDLE_AGE_SECONDS = 6 * 60 * 60
MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES = 300
MINIMUM_POLICY_SYMBOL_COUNT = 30
MINIMUM_POST_ALLOCATOR_PROFIT_FACTOR = 1.176
PAPER_RUNTIME_STATUS_STALE_AFTER_SECONDS = 5 * 60
MINIMUM_DURABLE_STRICT_SELECTION_MODEL_INPUT_SUFFIX = 20
PNL_HISTORY_WINDOWS = (
    ("1d", 24 * 60 * 60),
    ("7d", 7 * 24 * 60 * 60),
    ("30d", 30 * 24 * 60 * 60),
)
SIGNAL_ACCURACY_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
NAMED_ORDER_COUNTER_FIELDS = (
    "paper_accepted_intent_count",
    "paper_accepted_fill_count",
    "paper_economic_fill_count",
    "paper_non_economic_fill_count",
    "paper_held_intent_count",
    "paper_blocked_intent_count",
    "paper_shadow_observation_count",
    "paper_open_position_count",
    "paper_closed_position_count",
    "live_order_count",
    "test_order_count",
    "exchange_order_mutation_count",
)
DASHBOARD_WEB_SURFACES = (
    {
        "surface_id": "dashboard",
        "route": "/dashboard",
        "shows_capital_productivity_status": True,
        "shows_pnl_history_windows": True,
        "shows_signal_prediction_accuracy": True,
        "shows_all_symbol_timeframe_accuracy_matrix": True,
        "row_level_accuracy_pnl": False,
    },
    {
        "surface_id": "signals",
        "route": "/signals",
        "shows_capital_productivity_status": True,
        "shows_pnl_history_windows": True,
        "shows_signal_prediction_accuracy": True,
        "shows_all_symbol_timeframe_accuracy_matrix": True,
        "row_level_accuracy_pnl": True,
    },
    {
        "surface_id": "ai_predictions",
        "route": "/ai-predictions",
        "shows_capital_productivity_status": True,
        "shows_pnl_history_windows": True,
        "shows_signal_prediction_accuracy": True,
        "shows_all_symbol_timeframe_accuracy_matrix": True,
        "row_level_accuracy_pnl": True,
    },
    {
        "surface_id": "trainer_prediction_monitor",
        "route": "/admin/trainer-prediction-monitor",
        "shows_capital_productivity_status": True,
        "shows_pnl_history_windows": True,
        "shows_signal_prediction_accuracy": True,
        "shows_all_symbol_timeframe_accuracy_matrix": True,
        "row_level_accuracy_pnl": True,
    },
    {
        "surface_id": "trainer_admin",
        "route": "/admin/trainer-admin",
        "shows_capital_productivity_status": True,
        "shows_pnl_history_windows": True,
        "shows_signal_prediction_accuracy": True,
        "shows_all_symbol_timeframe_accuracy_matrix": True,
        "row_level_accuracy_pnl": False,
    },
    {
        "surface_id": "signal_explainability",
        "route": "/admin/signal-explainability",
        "shows_capital_productivity_status": True,
        "shows_pnl_history_windows": True,
        "shows_signal_prediction_accuracy": True,
        "shows_all_symbol_timeframe_accuracy_matrix": True,
        "row_level_accuracy_pnl": False,
    },
    {
        "surface_id": "history",
        "route": "/history",
        "shows_capital_productivity_status": True,
        "shows_pnl_history_windows": True,
        "shows_signal_prediction_accuracy": True,
        "shows_all_symbol_timeframe_accuracy_matrix": True,
        "row_level_accuracy_pnl": False,
    },
    {
        "surface_id": "positions",
        "route": "/positions",
        "shows_capital_productivity_status": True,
        "shows_pnl_history_windows": True,
        "shows_signal_prediction_accuracy": True,
        "shows_all_symbol_timeframe_accuracy_matrix": True,
        "row_level_accuracy_pnl": False,
    },
    {
        "surface_id": "paper_trading",
        "route": "/admin/paper-trading",
        "shows_capital_productivity_status": True,
        "shows_pnl_history_windows": True,
        "shows_signal_prediction_accuracy": True,
        "shows_all_symbol_timeframe_accuracy_matrix": True,
        "row_level_accuracy_pnl": False,
    },
    {
        "surface_id": "executions",
        "route": "/admin/executions",
        "shows_capital_productivity_status": True,
        "shows_pnl_history_windows": True,
        "shows_signal_prediction_accuracy": True,
        "shows_all_symbol_timeframe_accuracy_matrix": True,
        "row_level_accuracy_pnl": False,
    },
    {
        "surface_id": "trade_terminal",
        "route": "/trade",
        "shows_capital_productivity_status": True,
        "shows_pnl_history_windows": True,
        "shows_signal_prediction_accuracy": True,
        "shows_all_symbol_timeframe_accuracy_matrix": True,
        "row_level_accuracy_pnl": False,
    },
    {
        "surface_id": "binance_terminal",
        "route": "/binance",
        "shows_capital_productivity_status": True,
        "shows_pnl_history_windows": True,
        "shows_signal_prediction_accuracy": True,
        "shows_all_symbol_timeframe_accuracy_matrix": True,
        "row_level_accuracy_pnl": False,
    },
    {
        "surface_id": "mission_control",
        "route": "/admin/mission-control",
        "shows_capital_productivity_status": True,
        "shows_pnl_history_windows": True,
        "shows_signal_prediction_accuracy": True,
        "shows_all_symbol_timeframe_accuracy_matrix": True,
        "row_level_accuracy_pnl": False,
    },
    {
        "surface_id": "operator_proof_dashboard",
        "route": "/admin/evidence",
        "shows_capital_productivity_status": True,
        "shows_pnl_history_windows": True,
        "shows_signal_prediction_accuracy": True,
        "shows_all_symbol_timeframe_accuracy_matrix": True,
        "row_level_accuracy_pnl": False,
    },
    {
        "surface_id": "market_intelligence",
        "route": "/research",
        "shows_capital_productivity_status": True,
        "shows_pnl_history_windows": True,
        "shows_signal_prediction_accuracy": True,
        "shows_all_symbol_timeframe_accuracy_matrix": True,
        "row_level_accuracy_pnl": False,
    },
    {
        "surface_id": "technical_analysis",
        "route": "/admin/technical-analysis",
        "shows_capital_productivity_status": True,
        "shows_pnl_history_windows": True,
        "shows_signal_prediction_accuracy": True,
        "shows_all_symbol_timeframe_accuracy_matrix": True,
        "row_level_accuracy_pnl": False,
    },
)
NEAR_A_GRADE_REPLAY_CONFIDENCE_THRESHOLD = 0.65
A_GRADE_CONFIDENCE_THRESHOLD = 0.75
LEVERAGE_MARGIN_RATIO_TOLERANCE = 0.05
STOP_WAITING_PHASE_ID = "V2_STOP_WAITING_A_GRADE_CALIBRATION_ACCELERATED_REPLAY_AND_CAPITAL_DEPLOYMENT"
DYNAMIC_A_GRADE_MIN_BUCKET_SAMPLE_COUNT = 30
DYNAMIC_A_GRADE_MIN_POSITIVE_OUTCOME_LCB = 0.50
EXPLORATION_MIN_RISK_BUDGET_FRACTION = 0.02
EXPLORATION_MAX_RISK_BUDGET_FRACTION = 0.25
ACCELERATED_REPLAY_MIN_ECONOMIC_OUTCOMES = 10_000
ACCELERATED_REPLAY_MIN_SYMBOLS = 50
ACCELERATED_REPLAY_SIMULATION_FIELD_GROUPS: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("gross_notional", ("gross_notional_usd", "notional", "notional_usdt"), True),
    ("allocated_margin", ("allocated_margin_usd", "margin_usd", "initial_margin_usd"), True),
    ("leverage", ("recommended_leverage", "effective_leverage", "leverage"), True),
    ("margin_mode", ("recommended_margin_mode", "margin_mode"), False),
    ("stop_distance", ("stop_distance_bps", "stop_loss_bps", "stop_loss_distance_bps"), True),
    (
        "take_profit_structure",
        ("take_profit_structure", "take_profit_price", "take_profit_bps", "tp_price", "tp_bps"),
        False,
    ),
    ("hedge", ("hedge_budget_usd", "hedge_notional_usd", "hedge_enabled"), False),
    (
        "observed_spread",
        ("actual_observed_spread_entry_bps", "actual_spread_bps", "entry_spread_bps", "spread_bps"),
        False,
    ),
    (
        "depth_impact",
        ("depth_impact_bps", "depth_impact_usd", "orderbook_depth_usd", "market_depth_capacity_usd", "depth_usd"),
        False,
    ),
    ("fees", ("expected_fees_usd", "fee_usd", "fee_bps", "expected_fee_bps"), False),
    ("slippage", ("expected_slippage_usd", "expected_slippage_bps", "slippage_bps"), False),
    (
        "funding",
        (
            "funding_pnl_usd",
            "expected_funding_usd",
            "expected_funding_bps",
            "funding_rate",
            "funding_bps",
            "funding_rate_bps",
        ),
        False,
    ),
    ("liquidation_buffer", ("liquidation_buffer_bps", "liquidation_price_estimate"), True),
    (
        "portfolio_correlation",
        ("correlation_exposure_pct", "portfolio_correlation", "symbol_correlation", "correlation_adjustment"),
        False,
    ),
)
FAST_GATE_MIN_REALTIME_OUTCOMES = 100
FAST_GATE_MIN_REALTIME_SYMBOLS = 30
FAST_GATE_MIN_REALTIME_SIDE_CLOSES = 25
OUT_OF_SAMPLE_REVERIFY_GATE_ID = "V2_ADAPTIVE_CAPITAL_OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY"
OUT_OF_SAMPLE_MIN_HOLDOUT_OUTCOMES = 100
OUT_OF_SAMPLE_MIN_REALTIME_CLOSED_OUTCOMES = 100
OUT_OF_SAMPLE_MIN_SYMBOL_COUNT = 30
OUT_OF_SAMPLE_MIN_PROFIT_FACTOR = 1.5
OUT_OF_SAMPLE_MAX_WORST_1PCT_LOSS_BPS = 300.0
OUT_OF_SAMPLE_MAX_PROFIT_CONCENTRATION_SHARE = 0.35
OUT_OF_SAMPLE_REALTIME_REPLAY_EXPECTANCY_MIN_RATIO = 0.50


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        if value is None:
            return None
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _iter_jsonl_dicts(
    path: Path,
    *,
    source_status: dict[str, Any],
    max_rows: int | None = None,
) -> Any:
    parse_errors: list[dict[str, Any]] = []
    if not path.exists():
        source_status.update({
            "path": str(path),
            "exists": False,
            "scanned_line_count": 0,
            "parse_error_count": 0,
            "parse_error_sample": [],
        })
        return
    source_status.update({
        "path": str(path),
        "exists": True,
        "scanned_line_count": 0,
        "parse_error_count": 0,
        "parse_error_sample": [],
    })
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if max_rows is not None and source_status["scanned_line_count"] >= max_rows:
                break
            stripped = line.strip()
            if not stripped:
                continue
            source_status["scanned_line_count"] += 1
            try:
                payload = json.loads(stripped)
            except Exception as exc:  # noqa: BLE001
                if len(parse_errors) < 10:
                    parse_errors.append({
                        "line_number": line_number,
                        "error": str(exc),
                    })
                source_status["parse_error_count"] += 1
                source_status["parse_error_sample"] = parse_errors
                continue
            if isinstance(payload, dict):
                yield line_number, payload


def _post_hoc_replay_timing_fields(bundle: dict[str, Any]) -> dict[str, Any]:
    risk_decision = bundle.get("risk_decision") if isinstance(bundle.get("risk_decision"), dict) else {}
    return {
        "decision_time": _first_present(
            bundle.get("decision_time"),
            bundle.get("entry_feature_decision_time"),
            risk_decision.get("strategy_decision_time"),
        ),
        "available_at": _first_present(
            bundle.get("available_at"),
            bundle.get("entry_feature_available_at"),
        ),
        "generated_at": _first_present(
            bundle.get("entry_feature_generated_at"),
            bundle.get("prediction_generated_at"),
        ),
        "feature_cutoff": _first_present(
            bundle.get("feature_cutoff"),
            bundle.get("entry_feature_cutoff"),
            risk_decision.get("strategy_feature_cutoff"),
        ),
        "bundle_generated_at": _first_present(
            bundle.get("bundle_generated_at"),
            bundle.get("generated_at"),
            bundle.get("generated_utc"),
        ),
    }


def _post_hoc_replay_bundle_audit(
    *,
    bundle_rows: list[dict[str, Any]] | None = None,
    path: Path | None = None,
    primary_window_id: str = POST_HOC_REPLAY_PRIMARY_WINDOW_ID,
    max_rows: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_path = path or POST_HOC_REPLAY_BUNDLE_PATH
    if bundle_rows is None:
        source_status: dict[str, Any] = {}
        numbered_rows = _iter_jsonl_dicts(
            source_path,
            source_status=source_status,
            max_rows=max_rows,
        )
    else:
        numbered_rows = [(index, row) for index, row in enumerate(bundle_rows, start=1)]
        source_status = {
            "path": str(source_path),
            "exists": True,
            "scanned_line_count": len(numbered_rows),
            "parse_error_count": 0,
            "parse_error_sample": [],
            "source": "injected_test_rows",
        }

    complete_primary_outcome_count = 0
    event_time_valid_rows: list[dict[str, Any]] = []
    invalid_reason_counts: dict[str, int] = {}
    invalid_samples: list[dict[str, Any]] = []
    complete_after_cost_values: list[float] = []
    valid_after_cost_values: list[float] = []
    label_counts: dict[str, int] = {}
    complete_symbol_set: set[str] = set()
    valid_symbol_set: set[str] = set()
    valid_timeframes: set[str] = set()
    valid_side_counts: dict[str, int] = {}
    bundle_row_count = 0

    def add_invalid(reason: str) -> None:
        invalid_reason_counts[reason] = invalid_reason_counts.get(reason, 0) + 1

    for line_number, bundle in numbered_rows:
        bundle_row_count += 1
        label = str(bundle.get("label") or "UNKNOWN")
        label_counts[label] = label_counts.get(label, 0) + 1
        windows = bundle.get("future_outcomes") if isinstance(bundle.get("future_outcomes"), dict) else {}
        window = windows.get(primary_window_id) if isinstance(windows.get(primary_window_id), dict) else {}
        after_cost_bps = _coerce_float(window.get("after_cost_return_bps"))
        source = str(window.get("source") or "")
        reasons: list[str] = []
        has_complete_primary_outcome = (
            after_cost_bps is not None
            and not source.startswith("INSUFFICIENT_EVIDENCE")
        )
        if not has_complete_primary_outcome:
            reasons.append("MISSING_COMPLETE_PRIMARY_AFTER_COST_OUTCOME")
        else:
            complete_primary_outcome_count += 1
            complete_after_cost_values.append(after_cost_bps)

        symbol = str(bundle.get("symbol") or "UNKNOWN").upper()
        timeframe = str(bundle.get("timeframe") or "")
        side = str(_first_present(
            bundle.get("side"),
            (bundle.get("trainer_output") or {}).get("selected_action")
            if isinstance(bundle.get("trainer_output"), dict) else None,
            (bundle.get("risk_decision") or {}).get("side")
            if isinstance(bundle.get("risk_decision"), dict) else None,
        ) or "").strip().lower()
        if side in {"buy"}:
            side = "long"
        elif side in {"sell"}:
            side = "short"
        if has_complete_primary_outcome and symbol != "UNKNOWN":
            complete_symbol_set.add(symbol)
        if not timeframe:
            reasons.append("MISSING_TIMEFRAME")
        if side not in {"long", "short"}:
            reasons.append("NON_DIRECTIONAL_SIDE")
        if symbol == "UNKNOWN":
            reasons.append("MISSING_SYMBOL")

        timing = _post_hoc_replay_timing_fields(bundle)
        decision = _parse_utc(timing.get("decision_time"))
        if decision is None:
            reasons.append("MISSING_DECISION_TIME")
        for label_name, field_name in (
            ("AVAILABLE_AT", "available_at"),
            ("GENERATED_AT", "generated_at"),
            ("FEATURE_CUTOFF", "feature_cutoff"),
        ):
            parsed = _parse_utc(timing.get(field_name))
            if parsed is None:
                reasons.append(f"MISSING_{label_name}")
            elif decision is not None and parsed > decision:
                reasons.append(f"{label_name}_AFTER_DECISION_TIME")
        if bundle.get("entry_feature_candle_closed_confirmed") is not True:
            reasons.append("MISSING_OR_FALSE_ENTRY_FEATURE_CANDLE_CLOSED_CONFIRMATION")
        if bundle.get("future_labels_used_as_features") is True:
            reasons.append("FUTURE_LABELS_USED_AS_FEATURES")
        if (
            bundle.get("approves_live") is True
            or bundle.get("approves_canary") is True
            or bundle.get("approves_legacy_shutdown") is True
            or bundle.get("approves_redis_trim") is True
            or bool(bundle.get("live_symbols"))
        ):
            reasons.append("LIVE_APPROVAL_OR_LIVE_SYMBOL_PRESENT")

        if reasons:
            for reason in sorted(set(reasons)):
                add_invalid(reason)
            if len(invalid_samples) < 20:
                invalid_samples.append({
                    "line_number": line_number,
                    "symbol": symbol,
                    "timeframe": timeframe or None,
                    "side": side or None,
                    "label": label,
                    "outcome_window_id": primary_window_id,
                    "after_cost_return_bps": after_cost_bps,
                    "decision_time": timing.get("decision_time"),
                    "available_at": timing.get("available_at"),
                    "generated_at": timing.get("generated_at"),
                    "feature_cutoff": timing.get("feature_cutoff"),
                    "bundle_generated_at": timing.get("bundle_generated_at"),
                    "reasons": sorted(set(reasons)),
                })
            continue

        adapted = {
            "source_redis_key": (
                f"post_hoc_replay_outcome_bundle:{line_number}:"
                f"{bundle.get('prediction_id') or symbol}:{primary_window_id}"
            ),
            "counterfactual_source_kind": "post_hoc_replay_outcome_bundle",
            "prediction_id": (
                f"post_hoc:{bundle.get('prediction_id') or symbol}:{primary_window_id}"
            ),
            "source_bundle_prediction_id": bundle.get("prediction_id"),
            "symbol": symbol,
            "timeframe": timeframe,
            "side": side,
            "action": side,
            "decision_time": timing["decision_time"],
            "available_at": timing["available_at"],
            "generated_at": timing["generated_at"],
            "feature_cutoff": timing["feature_cutoff"],
            "bundle_generated_at": timing["bundle_generated_at"],
            "entry_feature_candle_closed_confirmed": True,
            "outcome_window_id": primary_window_id,
            "realized_after_cost_return_bps": after_cost_bps,
            "after_cost_return_bps": after_cost_bps,
            "drawdown_bps": _coerce_float(window.get("drawdown_bps")),
            "mfe_bps": _coerce_float(window.get("max_favorable_bps")),
            "mae_bps": _coerce_float(window.get("max_adverse_bps")),
            "fee_bps": _coerce_float(window.get("fee_drag_bps")),
            "expected_slippage_bps": _coerce_float(window.get("slippage_estimate_bps")),
            "post_hoc_replay_label": label,
            "paper_only": True,
            "places_real_order": False,
            "live_gate": LIVE_GATE,
        }
        trainer_output = bundle.get("trainer_output") if isinstance(bundle.get("trainer_output"), dict) else {}
        for target, source_key in (
            ("confidence_calibrated", "confidence_calibrated"),
            ("expected_move_after_cost_bps", "expected_move_after_cost_bps"),
        ):
            value = trainer_output.get(source_key)
            if value is not None:
                adapted[target] = value
        event_time_valid_rows.append(adapted)
        valid_after_cost_values.append(after_cost_bps)
        valid_symbol_set.add(symbol)
        valid_timeframes.add(timeframe)
        valid_side_counts[side] = valid_side_counts.get(side, 0) + 1

    complete_expectancy = (
        sum(complete_after_cost_values) / len(complete_after_cost_values)
        if complete_after_cost_values else None
    )
    valid_expectancy = (
        sum(valid_after_cost_values) / len(valid_after_cost_values)
        if valid_after_cost_values else None
    )
    status = (
        "READY_EVENT_TIME_VALID_POST_HOC_REPLAY_LABELS"
        if event_time_valid_rows else
        "NO_EVENT_TIME_VALID_POST_HOC_REPLAY_LABELS"
        if complete_primary_outcome_count else
        "NO_COMPLETE_POST_HOC_REPLAY_OUTCOMES"
    )
    audit = {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "source": "v2_post_hoc_replay_outcome_miner.replay_outcome_bundles",
        "source_path": str(source_path),
        "source_status": source_status,
        "primary_window_id": primary_window_id,
        "status": status,
        "bundle_row_count": bundle_row_count,
        "label_counts": {key: label_counts[key] for key in sorted(label_counts)},
        "complete_primary_outcome_count": complete_primary_outcome_count,
        "event_time_valid_label_count": len(event_time_valid_rows),
        "invalid_primary_outcome_or_temporal_count": bundle_row_count - len(event_time_valid_rows),
        "invalid_reason_counts": {
            key: invalid_reason_counts[key]
            for key in sorted(invalid_reason_counts)
        },
        "invalid_sample": invalid_samples,
        "complete_primary_outcome_symbol_count": len(complete_symbol_set),
        "event_time_valid_symbol_count": len(valid_symbol_set),
        "event_time_valid_symbols_sample": sorted(valid_symbol_set)[:100],
        "event_time_valid_timeframes": sorted(valid_timeframes),
        "event_time_valid_side_counts": {
            key: valid_side_counts[key] for key in sorted(valid_side_counts)
        },
        "complete_primary_expectancy_after_cost_bps": (
            round(complete_expectancy, 8)
            if complete_expectancy is not None else None
        ),
        "event_time_valid_expectancy_after_cost_bps": (
            round(valid_expectancy, 8)
            if valid_expectancy is not None else None
        ),
        "requires_explicit_available_at": True,
        "requires_explicit_feature_cutoff": True,
        "requires_explicit_generated_at": True,
        "requires_closed_entry_feature_candle": True,
        "bundle_generated_at_is_not_used_as_pre_submit_generated_at": True,
        "future_data_labels_only": True,
        "paper_only": True,
        "places_real_order": False,
        "live_gate": LIVE_GATE,
    }
    return audit, event_time_valid_rows


def _native_trainer_replay_evidence_audit(
    *,
    evidence_rows: list[dict[str, Any]] | None = None,
    path: Path | None = None,
    max_rows: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_path = path or NATIVE_TRAINER_REPLAY_EVIDENCE_ROWS_PATH
    if evidence_rows is None:
        source_status: dict[str, Any] = {}
        numbered_rows = _iter_jsonl_dicts(
            source_path,
            source_status=source_status,
            max_rows=max_rows,
        )
    else:
        numbered_rows = [(index, row) for index, row in enumerate(evidence_rows, start=1)]
        source_status = {
            "path": str(source_path),
            "exists": True,
            "scanned_line_count": len(numbered_rows),
            "parse_error_count": 0,
            "parse_error_sample": [],
            "source": "injected_test_rows",
        }

    source_row_count = 0
    event_time_valid_rows: list[dict[str, Any]] = []
    invalid_reason_counts: dict[str, int] = {}
    invalid_samples: list[dict[str, Any]] = []
    complete_after_cost_values: list[float] = []
    valid_after_cost_values: list[float] = []
    valid_symbol_set: set[str] = set()
    valid_timeframes: set[str] = set()
    valid_side_counts: dict[str, int] = {}

    def add_invalid(reason: str) -> None:
        invalid_reason_counts[reason] = invalid_reason_counts.get(reason, 0) + 1

    for line_number, row in numbered_rows:
        source_row_count += 1
        reasons: list[str] = []
        symbol = _normalized_symbol(row)
        timeframe = str(_row_value(row, "timeframe") or row.get("timeframe") or "")
        side = _directional_side(row)
        after_cost_bps = _outcome_after_cost_bps(row)
        if after_cost_bps is None:
            reasons.append("MISSING_AFTER_COST_OUTCOME_LABEL")
        else:
            complete_after_cost_values.append(after_cost_bps)
        if symbol == "UNKNOWN":
            reasons.append("MISSING_SYMBOL")
        if not timeframe or timeframe == "UNKNOWN":
            reasons.append("MISSING_TIMEFRAME")
        if side not in {"long", "short"}:
            reasons.append("NON_DIRECTIONAL_SIDE")

        decision = _parse_utc(_first_present(row.get("decision_time"), row.get("decision_time_est")))
        if decision is None:
            reasons.append("MISSING_DECISION_TIME")
        for label, value in (
            ("AVAILABLE_AT", _first_present(row.get("available_at"), row.get("entry_feature_available_at"))),
            ("GENERATED_AT", _first_present(row.get("entry_feature_generated_at"), row.get("prediction_generated_at"))),
            ("FEATURE_CUTOFF", _first_present(row.get("feature_cutoff"), row.get("entry_feature_cutoff"))),
        ):
            parsed = _parse_utc(value)
            if parsed is None:
                reasons.append(f"MISSING_{label}")
            elif decision is not None and parsed > decision:
                reasons.append(f"{label}_AFTER_DECISION_TIME")
        if row.get("entry_feature_candle_closed_confirmed") is not True:
            reasons.append("MISSING_OR_FALSE_ENTRY_FEATURE_CANDLE_CLOSED_CONFIRMATION")
        if row.get("future_labels_used_as_features") is True:
            reasons.append("FUTURE_LABELS_USED_AS_FEATURES")
        if (
            row.get("approves_live") is True
            or row.get("approves_canary") is True
            or row.get("approves_legacy_shutdown") is True
            or row.get("approves_redis_trim") is True
            or bool(row.get("live_symbols"))
        ):
            reasons.append("LIVE_APPROVAL_OR_LIVE_SYMBOL_PRESENT")

        if reasons:
            for reason in sorted(set(reasons)):
                add_invalid(reason)
            if len(invalid_samples) < 20:
                invalid_samples.append({
                    "line_number": line_number,
                    "symbol": symbol,
                    "timeframe": timeframe or None,
                    "side": side or None,
                    "label": row.get("label"),
                    "after_cost_return_bps": after_cost_bps,
                    "decision_time": _first_present(row.get("decision_time"), row.get("decision_time_est")),
                    "available_at": _first_present(row.get("available_at"), row.get("entry_feature_available_at")),
                    "generated_at": _first_present(row.get("entry_feature_generated_at"), row.get("prediction_generated_at")),
                    "feature_cutoff": _first_present(row.get("feature_cutoff"), row.get("entry_feature_cutoff")),
                    "bundle_generated_at": row.get("bundle_generated_at"),
                    "reasons": sorted(set(reasons)),
                })
            continue

        adapted = dict(row)
        adapted.update({
            "source_redis_key": (
                row.get("source_redis_key")
                or f"native_trainer_replay_dataset:{line_number}:{row.get('row_id') or symbol}"
            ),
            "counterfactual_source_kind": "native_trainer_replay_dataset",
            "symbol": symbol,
            "timeframe": timeframe,
            "side": side,
            "action": side,
            "decision_time": _first_present(row.get("decision_time"), row.get("decision_time_est")),
            "available_at": _first_present(row.get("available_at"), row.get("entry_feature_available_at")),
            "generated_at": _first_present(row.get("entry_feature_generated_at"), row.get("prediction_generated_at")),
            "feature_cutoff": _first_present(row.get("feature_cutoff"), row.get("entry_feature_cutoff")),
            "entry_feature_candle_closed_confirmed": True,
            "realized_after_cost_return_bps": after_cost_bps,
            "after_cost_return_bps": after_cost_bps,
            "paper_only": True,
            "places_real_order": False,
            "live_gate": LIVE_GATE,
        })
        event_time_valid_rows.append(adapted)
        valid_after_cost_values.append(after_cost_bps)
        valid_symbol_set.add(symbol)
        valid_timeframes.add(timeframe)
        valid_side_counts[side] = valid_side_counts.get(side, 0) + 1

    complete_expectancy = (
        sum(complete_after_cost_values) / len(complete_after_cost_values)
        if complete_after_cost_values else None
    )
    valid_expectancy = (
        sum(valid_after_cost_values) / len(valid_after_cost_values)
        if valid_after_cost_values else None
    )
    status = (
        "READY_EVENT_TIME_VALID_NATIVE_REPLAY_DATASET_LABELS"
        if event_time_valid_rows else
        "NO_EVENT_TIME_VALID_NATIVE_REPLAY_DATASET_LABELS"
        if source_row_count else
        "NO_NATIVE_REPLAY_DATASET_ROWS"
    )
    audit = {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "source": "v2_native_trainer_replay_evidence_rows",
        "source_path": str(source_path),
        "source_status": source_status,
        "status": status,
        "source_row_count": source_row_count,
        "complete_after_cost_outcome_count": len(complete_after_cost_values),
        "event_time_valid_label_count": len(event_time_valid_rows),
        "invalid_replay_evidence_row_count": source_row_count - len(event_time_valid_rows),
        "invalid_reason_counts": {
            key: invalid_reason_counts[key]
            for key in sorted(invalid_reason_counts)
        },
        "invalid_sample": invalid_samples,
        "event_time_valid_symbol_count": len(valid_symbol_set),
        "event_time_valid_symbols_sample": sorted(valid_symbol_set)[:100],
        "event_time_valid_timeframes": sorted(valid_timeframes),
        "event_time_valid_side_counts": {
            key: valid_side_counts[key] for key in sorted(valid_side_counts)
        },
        "complete_expectancy_after_cost_bps": (
            round(complete_expectancy, 8)
            if complete_expectancy is not None else None
        ),
        "event_time_valid_expectancy_after_cost_bps": (
            round(valid_expectancy, 8)
            if valid_expectancy is not None else None
        ),
        "requires_explicit_available_at": True,
        "requires_explicit_generated_at": True,
        "requires_explicit_feature_cutoff": True,
        "requires_entry_feature_candle_closed_confirmation": True,
        "counts_as_replay_evidence_only_when_event_time_valid": True,
        "paper_only": True,
        "live_gate": LIVE_GATE,
        "places_real_order": False,
    }
    return audit, event_time_valid_rows


def _closed_candle_replay_evidence_audit(
    *,
    evidence_rows: list[dict[str, Any]] | None = None,
    path: Path | None = None,
    max_rows: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_path = path or CLOSED_CANDLE_REPLAY_EVIDENCE_ROWS_PATH
    if evidence_rows is None:
        source_status: dict[str, Any] = {}
        numbered_rows = _iter_jsonl_dicts(
            source_path,
            source_status=source_status,
            max_rows=max_rows,
        )
    else:
        numbered_rows = [(index, row) for index, row in enumerate(evidence_rows, start=1)]
        source_status = {
            "path": str(source_path),
            "exists": True,
            "scanned_line_count": len(numbered_rows),
            "parse_error_count": 0,
            "parse_error_sample": [],
            "source": "injected_test_rows",
        }

    source_row_count = 0
    event_time_valid_rows: list[dict[str, Any]] = []
    invalid_reason_counts: dict[str, int] = {}
    invalid_samples: list[dict[str, Any]] = []
    complete_after_cost_values: list[float] = []
    valid_after_cost_values: list[float] = []
    valid_symbol_set: set[str] = set()
    valid_timeframes: set[str] = set()
    valid_side_counts: dict[str, int] = {}

    def add_invalid(reason: str) -> None:
        invalid_reason_counts[reason] = invalid_reason_counts.get(reason, 0) + 1

    for line_number, row in numbered_rows:
        source_row_count += 1
        reasons: list[str] = []
        symbol = _normalized_symbol(row)
        timeframe = str(_row_value(row, "timeframe") or row.get("timeframe") or "")
        side = _directional_side(row)
        after_cost_bps = _outcome_after_cost_bps(row)
        if after_cost_bps is None:
            reasons.append("MISSING_AFTER_COST_OUTCOME_LABEL")
        else:
            complete_after_cost_values.append(after_cost_bps)
        if symbol == "UNKNOWN":
            reasons.append("MISSING_SYMBOL")
        if not timeframe or timeframe == "UNKNOWN":
            reasons.append("MISSING_TIMEFRAME")
        if side not in {"long", "short"}:
            reasons.append("NON_DIRECTIONAL_SIDE")

        decision_value = _first_present(row.get("decision_time"), row.get("entry_feature_decision_time"))
        decision = _parse_utc(decision_value)
        if decision is None:
            reasons.append("MISSING_DECISION_TIME")
        for label, value in (
            ("AVAILABLE_AT", _first_present(row.get("available_at"), row.get("entry_feature_available_at"))),
            ("GENERATED_AT", _first_present(row.get("generated_at"), row.get("entry_feature_generated_at"))),
            ("FEATURE_CUTOFF", _first_present(row.get("feature_cutoff"), row.get("entry_feature_cutoff"))),
        ):
            parsed = _parse_utc(value)
            if parsed is None:
                reasons.append(f"MISSING_{label}")
            elif decision is not None and parsed > decision:
                reasons.append(f"{label}_AFTER_DECISION_TIME")
        label_close = _parse_utc(_first_present(row.get("future_label_close_time"), row.get("closed_at")))
        if label_close is None:
            reasons.append("MISSING_FUTURE_LABEL_CLOSE_TIME")
        elif decision is not None and label_close <= decision:
            reasons.append("FUTURE_LABEL_NOT_AFTER_DECISION_TIME")
        if row.get("entry_feature_candle_closed_confirmed") is not True:
            reasons.append("MISSING_OR_FALSE_ENTRY_FEATURE_CANDLE_CLOSED_CONFIRMATION")
        if row.get("future_labels_used_as_features") is True:
            reasons.append("FUTURE_LABELS_USED_AS_FEATURES")
        if row.get("future_label_used_as_outcome_only") is False:
            reasons.append("FUTURE_LABEL_OUTCOME_ONLY_FLAG_FALSE")
        if (
            row.get("approves_live") is True
            or row.get("approves_canary") is True
            or row.get("approves_legacy_shutdown") is True
            or row.get("approves_redis_trim") is True
            or bool(row.get("live_symbols"))
        ):
            reasons.append("LIVE_APPROVAL_OR_LIVE_SYMBOL_PRESENT")

        if reasons:
            for reason in sorted(set(reasons)):
                add_invalid(reason)
            if len(invalid_samples) < 20:
                invalid_samples.append({
                    "line_number": line_number,
                    "symbol": symbol,
                    "timeframe": timeframe or None,
                    "side": side or None,
                    "after_cost_return_bps": after_cost_bps,
                    "decision_time": decision_value,
                    "available_at": _first_present(row.get("available_at"), row.get("entry_feature_available_at")),
                    "generated_at": _first_present(row.get("generated_at"), row.get("entry_feature_generated_at")),
                    "feature_cutoff": _first_present(row.get("feature_cutoff"), row.get("entry_feature_cutoff")),
                    "future_label_close_time": _first_present(row.get("future_label_close_time"), row.get("closed_at")),
                    "reasons": sorted(set(reasons)),
                })
            continue

        adapted = dict(row)
        adapted.update({
            "source_redis_key": (
                row.get("source_redis_key")
                or f"closed_candle_replay:{line_number}:{row.get('row_id') or symbol}"
            ),
            "counterfactual_source_kind": "closed_candle_replay",
            "symbol": symbol,
            "timeframe": timeframe,
            "side": side,
            "action": side,
            "decision_time": decision_value,
            "available_at": _first_present(row.get("available_at"), row.get("entry_feature_available_at")),
            "generated_at": _first_present(row.get("generated_at"), row.get("entry_feature_generated_at")),
            "feature_cutoff": _first_present(row.get("feature_cutoff"), row.get("entry_feature_cutoff")),
            "entry_feature_candle_closed_confirmed": True,
            "candle_closed_confirmed": True,
            "closed_candle": True,
            "is_closed": True,
            "feature_eligible": True,
            "future_label_used_as_outcome_only": True,
            "future_labels_used_as_features": False,
            "realized_after_cost_return_bps": after_cost_bps,
            "after_cost_return_bps": after_cost_bps,
            "paper_only": True,
            "offline_replay_only": True,
            "places_real_order": False,
            "live_gate": LIVE_GATE,
        })
        event_time_valid_rows.append(adapted)
        valid_after_cost_values.append(after_cost_bps)
        valid_symbol_set.add(symbol)
        valid_timeframes.add(timeframe)
        valid_side_counts[side] = valid_side_counts.get(side, 0) + 1

    complete_expectancy = (
        sum(complete_after_cost_values) / len(complete_after_cost_values)
        if complete_after_cost_values else None
    )
    valid_expectancy = (
        sum(valid_after_cost_values) / len(valid_after_cost_values)
        if valid_after_cost_values else None
    )
    status = (
        "READY_EVENT_TIME_VALID_CLOSED_CANDLE_REPLAY_LABELS"
        if event_time_valid_rows else
        "NO_EVENT_TIME_VALID_CLOSED_CANDLE_REPLAY_LABELS"
        if source_row_count else
        "NO_CLOSED_CANDLE_REPLAY_ROWS"
    )
    audit = {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "source": "closed_candle_replay_evidence_rows",
        "source_path": str(source_path),
        "source_status": source_status,
        "status": status,
        "source_row_count": source_row_count,
        "complete_after_cost_outcome_count": len(complete_after_cost_values),
        "event_time_valid_label_count": len(event_time_valid_rows),
        "invalid_replay_evidence_row_count": source_row_count - len(event_time_valid_rows),
        "invalid_reason_counts": {
            key: invalid_reason_counts[key]
            for key in sorted(invalid_reason_counts)
        },
        "invalid_sample": invalid_samples,
        "event_time_valid_symbol_count": len(valid_symbol_set),
        "event_time_valid_symbols_sample": sorted(valid_symbol_set)[:100],
        "event_time_valid_timeframes": sorted(valid_timeframes),
        "event_time_valid_side_counts": {
            key: valid_side_counts[key] for key in sorted(valid_side_counts)
        },
        "complete_expectancy_after_cost_bps": (
            round(complete_expectancy, 8)
            if complete_expectancy is not None else None
        ),
        "event_time_valid_expectancy_after_cost_bps": (
            round(valid_expectancy, 8)
            if valid_expectancy is not None else None
        ),
        "requires_explicit_available_at": True,
        "requires_explicit_generated_at": True,
        "requires_explicit_feature_cutoff": True,
        "requires_entry_feature_candle_closed_confirmation": True,
        "requires_future_label_close_time_after_decision": True,
        "future_data_labels_only": True,
        "counts_as_replay_evidence_only_when_event_time_valid": True,
        "paper_only": True,
        "offline_replay_only": True,
        "live_gate": LIVE_GATE,
        "places_real_order": False,
    }
    return audit, event_time_valid_rows


def _connect_redis() -> Any | None:
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
        )
        client.ping()
        return client
    except Exception:
        return None


def _redis_json(client: Any | None, key: str) -> Any:
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _safe_rows(payload: Any, key: str) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return [dict(row) for row in payload[key] if isinstance(row, dict)]
    if key == "rows" and isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    return []


def _rows_with_source(payload: Any, key: str, source: str) -> list[dict[str, Any]]:
    rows = _safe_rows(payload, key)
    for row in rows:
        row.setdefault("paper_intent_source", source)
    return rows


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("signals", "rows", "items", "data"):
        value = payload.get(key)
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, dict)]
    signal_markers = {
        "signal_id",
        "prediction_id",
        "symbol",
        "timeframe",
        "confidence",
        "confidence_calibrated",
        "expected_move_after_cost_bps",
    }
    if any(key in payload for key in signal_markers):
        return [dict(payload)]
    return []


def _paper_signal_key_lineage(source_key: str) -> tuple[str | None, str | None]:
    parts = source_key.split(":")
    if len(parts) < 5 or parts[:3] != ["v2", "signals", "paper"]:
        return None, None
    symbol = parts[3].upper() if parts[3] else None
    timeframe = parts[4] if parts[4] else None
    return symbol, timeframe


def _apply_source_redis_key_lineage(row: dict[str, Any], source_key: str) -> None:
    symbol, timeframe = _paper_signal_key_lineage(source_key)
    if symbol is None and timeframe is None:
        return
    row.setdefault("source_redis_symbol", symbol)
    row.setdefault("source_redis_timeframe", timeframe)
    if row.get("symbol") in {None, ""} and symbol is not None:
        row["symbol"] = symbol
    if row.get("timeframe") in {None, ""} and timeframe is not None:
        row["timeframe"] = timeframe


def _scan_redis_json_rows(client: Any | None, pattern: str, *, limit: int = 5000) -> list[dict[str, Any]]:
    if client is None or limit <= 0:
        return []
    rows: list[dict[str, Any]] = []
    try:
        iterator = client.scan_iter(match=pattern, count=1000)
    except Exception:
        return []
    for key in iterator:
        payload = _redis_json(client, str(key))
        for row in _rows_from_payload(payload):
            source_key = str(key)
            row.setdefault("source_redis_key", source_key)
            _apply_source_redis_key_lineage(row, source_key)
            rows.append(row)
            if len(rows) >= limit:
                return rows
    return rows


def _feature_snapshot_ids_from_rows(rows: list[dict[str, Any]]) -> list[str]:
    ids: set[str] = set()
    for row in rows:
        for field in ("feature_snapshot_id", "entry_feature_snapshot_id", "prediction_feature_snapshot_id"):
            value = row.get(field)
            if value not in {None, ""}:
                ids.add(str(value))
        lineage = row.get("lineage_ids")
        if isinstance(lineage, dict):
            value = lineage.get("feature_snapshot_id")
            if value not in {None, ""}:
                ids.add(str(value))
    return sorted(ids)


def _read_archived_feature_rows_from_redis(
    client: Any | None,
    rows: list[dict[str, Any]],
    *,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    if client is None or limit <= 0:
        return []
    archived_rows: list[dict[str, Any]] = []
    for snapshot_id in _feature_snapshot_ids_from_rows(rows):
        key = f"v2:features:snapshot:{snapshot_id}"
        payload = _redis_json(client, key)
        if not isinstance(payload, dict):
            continue
        row = dict(payload)
        row.setdefault("source_redis_key", key)
        archived_rows.append(row)
        if len(archived_rows) >= limit:
            break
    return archived_rows


def _feature_snapshot_lookup_audit(
    *,
    decision_rows: list[dict[str, Any]],
    feature_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    requested_ids = _feature_snapshot_ids_from_rows(decision_rows)
    available_ids = {
        str(row.get("feature_snapshot_id"))
        for row in feature_rows
        if isinstance(row, dict) and row.get("feature_snapshot_id") not in {None, ""}
    }
    archived_ids = {
        str(row.get("feature_snapshot_id"))
        for row in feature_rows
        if (
            isinstance(row, dict)
            and row.get("feature_snapshot_id") not in {None, ""}
            and str(row.get("source_redis_key") or "").startswith("v2:features:snapshot:")
        )
    }
    missing_ids = [snapshot_id for snapshot_id in requested_ids if snapshot_id not in available_ids]
    return {
        "status": "PASSED" if not missing_ids else "NO_GO_EXACT_FEATURE_SNAPSHOT_GAPS",
        "requested_feature_snapshot_id_count": len(requested_ids),
        "available_exact_feature_snapshot_id_count": len(available_ids.intersection(requested_ids)),
        "archived_exact_feature_snapshot_id_count": len(archived_ids.intersection(requested_ids)),
        "missing_exact_feature_snapshot_id_count": len(missing_ids),
        "missing_exact_feature_snapshot_id_sample": missing_ids[:20],
    }


def _notional(row: dict[str, Any]) -> float:
    return abs(_coerce_float(_first_present(row.get("gross_notional_usd"), row.get("notional"), row.get("notional_usdt"))) or 0.0)


def _margin(row: dict[str, Any]) -> float:
    explicit = _coerce_float(row.get("allocated_margin_usd"))
    if explicit is not None:
        return max(0.0, explicit)
    leverage = max(1.0, _coerce_float(_first_present(row.get("effective_leverage"), row.get("recommended_leverage"))) or 1.0)
    return _notional(row) / leverage


def _pnl(row: dict[str, Any]) -> float:
    return _coerce_float(_first_present(row.get("realized_pnl_usd"), row.get("realized_pnl_usdt"))) or 0.0


def _post_allocator_performance_metrics(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    pnl_values = [_pnl(row) for row in rows]
    gross_profit = sum(value for value in pnl_values if value > 0.0)
    gross_loss = abs(sum(value for value in pnl_values if value < 0.0))
    winning_count = sum(1 for value in pnl_values if value > 0.0)
    losing_count = sum(1 for value in pnl_values if value < 0.0)
    flat_count = len(pnl_values) - winning_count - losing_count
    profit_factor_numeric: float | None
    if gross_loss > 0.0:
        profit_factor_numeric = gross_profit / gross_loss
        profit_factor: float | str | None = round(profit_factor_numeric, 8)
    elif gross_profit > 0.0:
        profit_factor_numeric = math.inf
        profit_factor = "inf"
    else:
        profit_factor_numeric = None
        profit_factor = None
    if profit_factor_numeric is None:
        status = "NO_GO_PROFIT_FACTOR_UNAVAILABLE"
    elif profit_factor_numeric >= MINIMUM_POST_ALLOCATOR_PROFIT_FACTOR:
        status = "PASSED"
    else:
        status = "NO_GO_PROFIT_FACTOR_BELOW_MINIMUM"
    target_gross_profit = MINIMUM_POST_ALLOCATOR_PROFIT_FACTOR * gross_loss
    additional_gross_profit_needed = max(0.0, target_gross_profit - gross_profit)
    gross_loss_capacity_at_current_profit = (
        gross_profit / MINIMUM_POST_ALLOCATOR_PROFIT_FACTOR
        if MINIMUM_POST_ALLOCATOR_PROFIT_FACTOR > 0.0
        else None
    )
    additional_gross_loss_headroom = (
        max(0.0, gross_loss_capacity_at_current_profit - gross_loss)
        if gross_loss_capacity_at_current_profit is not None
        else None
    )
    closed_outcome_deficit = max(0, MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES - len(rows))
    sample_size_status = (
        "READY_STATISTICALLY_ADEQUATE_COHORT"
        if closed_outcome_deficit == 0
        else "NO_GO_PROFIT_FACTOR_COHORT_BELOW_300_OUTCOMES"
    )
    profit_factor_burn_down = {
        "status": status,
        "profit_factor_available": profit_factor_numeric is not None,
        "minimum_required_profit_factor": MINIMUM_POST_ALLOCATOR_PROFIT_FACTOR,
        "profit_factor_numeric": (
            round(profit_factor_numeric, 8)
            if profit_factor_numeric is not None and math.isfinite(profit_factor_numeric)
            else None
        ),
        "gross_profit_usd": round(gross_profit, 8),
        "gross_loss_usd": round(gross_loss, 8),
        "target_gross_profit_usd_at_current_loss": round(target_gross_profit, 8),
        "additional_gross_profit_needed_usd": round(additional_gross_profit_needed, 8),
        "gross_loss_capacity_usd_at_current_profit": (
            round(gross_loss_capacity_at_current_profit, 8)
            if gross_loss_capacity_at_current_profit is not None
            else None
        ),
        "additional_gross_loss_headroom_usd": (
            round(additional_gross_loss_headroom, 8)
            if additional_gross_loss_headroom is not None
            else None
        ),
        "assumption_for_additional_gross_profit_needed": (
            "Assumes additional gross profit is added with no additional gross loss."
        ),
        "closed_outcome_count": len(rows),
        "minimum_required_closed_outcomes": MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES,
        "closed_outcome_deficit_to_statistical_minimum": closed_outcome_deficit,
        "sample_size_status": sample_size_status,
        "counts_as_profit_factor_gate": False,
    }
    return {
        "status": status,
        "minimum_required_profit_factor": MINIMUM_POST_ALLOCATOR_PROFIT_FACTOR,
        "profit_factor": profit_factor,
        "profit_factor_numeric": (
            round(profit_factor_numeric, 8)
            if profit_factor_numeric is not None and math.isfinite(profit_factor_numeric)
            else None
        ),
        "profit_factor_is_infinite": profit_factor_numeric == math.inf,
        "profit_factor_gap_to_minimum": (
            0.0
            if profit_factor_numeric is not None and profit_factor_numeric >= MINIMUM_POST_ALLOCATOR_PROFIT_FACTOR
            else round(MINIMUM_POST_ALLOCATOR_PROFIT_FACTOR - (profit_factor_numeric or 0.0), 8)
        ),
        "post_allocator_win_rate": round(winning_count / len(pnl_values), 8) if pnl_values else None,
        "post_allocator_winning_trade_count": winning_count,
        "post_allocator_losing_trade_count": losing_count,
        "post_allocator_flat_trade_count": flat_count,
        "post_allocator_realized_profit_usd": round(gross_profit, 8),
        "post_allocator_realized_loss_usd": round(gross_loss, 8),
        "post_allocator_closed_outcome_count": len(rows),
        "profit_factor_formula": "sum(positive realized_pnl_usd) / abs(sum(negative realized_pnl_usd))",
        "profit_factor_burn_down": profit_factor_burn_down,
    }


def _int_from_any(value: Any) -> int | None:
    parsed = _coerce_float(value)
    if parsed is None:
        return None
    return int(parsed)


def _decision_counts_from_rows(rows: Any) -> dict[str, int]:
    if not isinstance(rows, list):
        return {}
    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        decision = str(
            _first_present(
                row.get("allocator_decision"),
                row.get("paper_allocation_decision"),
                "__missing__",
            )
        )
        counts[decision] = counts.get(decision, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _reason_counts_from_rows(rows: Any) -> dict[str, int]:
    if not isinstance(rows, list):
        return {}
    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        reason = str(
            _first_present(
                row.get("capital_allocation_reason"),
                row.get("final_size_reason"),
                row.get("paper_allocation_block_reason"),
                "__missing__",
            )
        )
        counts[reason] = counts.get(reason, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _runtime_evidence_acquisition_status(
    *,
    paper_status: dict[str, Any] | None,
    generated_utc: str,
) -> dict[str, Any]:
    paper_status = paper_status if isinstance(paper_status, dict) else {}
    generated_ms = _parse_epoch_ms(generated_utc)
    finished_at = _first_present(paper_status.get("finished_at"), paper_status.get("generated_utc"))
    finished_ms = _parse_epoch_ms(finished_at)
    status_age_seconds = (
        max(0.0, (generated_ms - finished_ms) / 1000.0)
        if generated_ms is not None and finished_ms is not None
        else None
    )
    runtime_status_stale = (
        status_age_seconds is None
        or status_age_seconds > PAPER_RUNTIME_STATUS_STALE_AFTER_SECONDS
    )
    intents_built = _int_from_any(paper_status.get("intents_built")) or 0
    intents_accepted = _int_from_any(paper_status.get("intents_accepted")) or 0
    intents_blocked = _int_from_any(paper_status.get("intents_blocked")) or 0
    intents_held = _int_from_any(paper_status.get("intents_held_by_paper_fill_gate")) or 0
    all_current_intents_blocked = intents_built > 0 and intents_accepted == 0 and intents_held == 0
    if not paper_status:
        status = "NO_RUNTIME_STATUS_PAYLOAD"
    elif runtime_status_stale:
        status = "RUNTIME_STATUS_STALE"
    elif all_current_intents_blocked:
        status = "CURRENT_INTENTS_BLOCKED"
    elif intents_accepted > 0:
        status = "CURRENT_ACCEPTED_INTENTS_PRESENT"
    elif intents_held > 0:
        status = "CURRENT_INTENTS_HELD_BY_PAPER_FILL_GATE"
    elif intents_built <= 0:
        status = "NO_CURRENT_INTENTS"
    else:
        status = "CURRENT_INTENTS_OBSERVED"
    sizing_status = paper_status.get("paper_adaptive_sizing_runtime_status")
    sizing_status = sizing_status if isinstance(sizing_status, dict) else {}
    paper_exploration_tier_status = _paper_exploration_tier_status_from_runtime(
        paper_status=paper_status,
        generated_utc=generated_utc,
    )
    sample_allocations = sizing_status.get("sample_allocations")
    allocator_counts = sizing_status.get("allocator_decision_counts")
    allocator_counts = allocator_counts if isinstance(allocator_counts, dict) else {}
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": status,
        "paper_loop_status_present": bool(paper_status),
        "paper_loop_classification": paper_status.get("classification"),
        "paper_loop_started_at": paper_status.get("started_at"),
        "paper_loop_finished_at": paper_status.get("finished_at"),
        "paper_loop_status_age_seconds": (
            round(status_age_seconds, 8)
            if status_age_seconds is not None
            else None
        ),
        "paper_loop_status_stale_after_seconds": PAPER_RUNTIME_STATUS_STALE_AFTER_SECONDS,
        "paper_loop_status_stale": runtime_status_stale,
        "paper_signals_seen": _int_from_any(paper_status.get("paper_signals_seen")),
        "current_intents_built": intents_built,
        "current_intents_accepted": intents_accepted,
        "current_intents_blocked": intents_blocked,
        "current_intents_held_by_paper_fill_gate": intents_held,
        "current_intents_all_blocked": all_current_intents_blocked,
        "accepted_position_count": _int_from_any(paper_status.get("accepted_position_count")),
        "open_position_count": _int_from_any(paper_status.get("open_position_count")),
        "closed_trade_count": _int_from_any(paper_status.get("closed_trade_count")),
        "persistent_accepted_fill_count": _int_from_any(paper_status.get("persistent_accepted_fill_count")),
        "realized_pnl_usd": _coerce_float(paper_status.get("realized_pnl_usd")),
        "unrealized_pnl_usd": _coerce_float(paper_status.get("unrealized_pnl_usd")),
        "total_open_notional": _coerce_float(paper_status.get("total_open_notional")),
        "adaptive_allocator_status": sizing_status.get("status"),
        "adaptive_allocator_decision_counts": {
            str(key): value
            for key, value in sorted(allocator_counts.items())
        },
        "current_sample_allocator_decision_counts": _decision_counts_from_rows(sample_allocations),
        "current_sample_allocation_reason_counts": _reason_counts_from_rows(sample_allocations),
        "paper_exploration_tier_status": paper_exploration_tier_status,
        "v2_paper_keys_written_count": _int_from_any(paper_status.get("v2_paper_keys_written_count")),
        "writes_legacy_redis": paper_status.get("writes_legacy_redis"),
        "places_real_order": paper_status.get("places_real_order"),
        "counts_as_additional_pass_gate": False,
        "paper_only_runtime_diagnostic": True,
        "notes": (
            "Read-only runtime acquisition diagnostic. It explains whether current paper-only "
            "loops are producing accepted intents, but it does not relax the 300-outcome gate "
            "or mutate allocator, risk, strategy, order, leverage, or margin behavior."
        ),
    }


def _paper_exploration_tier_status_from_runtime(
    *,
    paper_status: dict[str, Any] | None,
    generated_utc: str,
) -> dict[str, Any]:
    paper_status = paper_status if isinstance(paper_status, dict) else {}
    tier_status = paper_status.get("paper_exploration_tier_status")
    if not isinstance(tier_status, dict):
        tier_status = {}
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": tier_status.get("status") or "NO_RUNTIME_TIER_STATUS_PAYLOAD",
        "source": "v2_trade_management_paper/live/latest/v2_trade_management_paper_live_status.json",
        "paper_only": tier_status.get("paper_only", True),
        "places_real_order": False,
        "live_path_changed": tier_status.get("live_path_changed", False),
        "tiers": tier_status.get("tiers") or [
            "A_GRADE_EXECUTION_PAPER",
            "B_GRADE_EXPLORATION_PAPER",
            "SHADOW_ONLY",
            "NO_TRADE",
        ],
        "tier_counts": tier_status.get("tier_counts") if isinstance(tier_status.get("tier_counts"), dict) else {},
        "accepted_tier_counts": (
            tier_status.get("accepted_tier_counts")
            if isinstance(tier_status.get("accepted_tier_counts"), dict)
            else {}
        ),
        "blocked_tier_counts": (
            tier_status.get("blocked_tier_counts")
            if isinstance(tier_status.get("blocked_tier_counts"), dict)
            else {}
        ),
        "shadow_tier_counts": (
            tier_status.get("shadow_tier_counts")
            if isinstance(tier_status.get("shadow_tier_counts"), dict)
            else {}
        ),
        "held_tier_counts": (
            tier_status.get("held_tier_counts")
            if isinstance(tier_status.get("held_tier_counts"), dict)
            else {}
        ),
        "legacy_unclassified_tier_count": _int_from_any(
            tier_status.get("legacy_unclassified_tier_count")
        ),
        "legacy_accepted_without_tier_count": _int_from_any(
            tier_status.get("legacy_accepted_without_tier_count")
        ),
        "b_grade_exploration_accepted_count": _int_from_any(
            tier_status.get("b_grade_exploration_accepted_count")
        ) or 0,
        "b_grade_exploration_budget_cap_applied_count": _int_from_any(
            tier_status.get("b_grade_exploration_budget_cap_applied_count")
        ) or 0,
        "b_grade_exploration_max_risk_fraction_of_normal_adaptive": _coerce_float(
            tier_status.get("b_grade_exploration_max_risk_fraction_of_normal_adaptive")
        ),
        "b_grade_exploration_observed_max_risk_fraction": _coerce_float(
            tier_status.get("b_grade_exploration_observed_max_risk_fraction")
        ),
        "b_grade_exploration_live_routing_blocked": (
            tier_status.get("b_grade_exploration_live_routing_blocked") is not False
        ),
        "calibration_label_purpose": (
            tier_status.get("calibration_label_purpose")
            or "B_GRADE_EXPLORATION_OUTCOME_LABEL"
        ),
        "sample_b_grade_exploration_fills": (
            tier_status.get("sample_b_grade_exploration_fills")
            if isinstance(tier_status.get("sample_b_grade_exploration_fills"), list)
            else []
        ),
        "paper_loop_classification": paper_status.get("classification"),
        "paper_loop_started_at": paper_status.get("started_at"),
        "paper_loop_finished_at": paper_status.get("finished_at"),
    }


def _evidence_acquisition_status(
    *,
    rows: list[dict[str, Any]],
    complete_open_row_count: int,
    current_symbol_count: int,
    symbol_diversity_deficit: int,
    generated_utc: str,
    paper_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timed_points = sorted(
        value for row in rows
        for value in [_event_time_ms(row)]
        if value is not None
    )
    outcome_count = len(rows)
    closed_outcome_deficit = max(0, MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES - outcome_count)
    projected_after_open_close = outcome_count + max(0, complete_open_row_count)
    projected_deficit_after_open_close = max(
        0,
        MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES - projected_after_open_close,
    )
    interval_count = max(0, len(timed_points) - 1)
    first_ms = timed_points[0] if timed_points else None
    last_ms = timed_points[-1] if timed_points else None
    observed_window_seconds = (
        max(0.0, (last_ms - first_ms) / 1000.0)
        if first_ms is not None and last_ms is not None
        else None
    )
    observed_window_days = (
        observed_window_seconds / 86400.0
        if observed_window_seconds is not None
        else None
    )
    observed_closed_outcomes_per_day = (
        interval_count / observed_window_days
        if observed_window_days is not None and observed_window_days > 0.0 and interval_count > 0
        else None
    )
    generated_ms = _parse_epoch_ms(generated_utc)
    hours_since_latest_closed_outcome = (
        max(0.0, (generated_ms - last_ms) / 3_600_000.0)
        if generated_ms is not None and last_ms is not None
        else None
    )
    eta_days_to_300_closed_outcomes = (
        closed_outcome_deficit / observed_closed_outcomes_per_day
        if observed_closed_outcomes_per_day and closed_outcome_deficit > 0
        else 0.0
        if closed_outcome_deficit == 0
        else None
    )
    eta_days_after_current_open_positions_close = (
        projected_deficit_after_open_close / observed_closed_outcomes_per_day
        if observed_closed_outcomes_per_day and projected_deficit_after_open_close > 0
        else 0.0
        if projected_deficit_after_open_close == 0
        else None
    )
    if closed_outcome_deficit == 0 and symbol_diversity_deficit == 0:
        status = "PASSED_EVIDENCE_ACQUIRED"
    elif observed_closed_outcomes_per_day is None:
        status = "NO_GO_EVIDENCE_ACQUISITION_RATE_UNAVAILABLE"
    else:
        status = "NO_GO_EVIDENCE_ACQUISITION_IN_PROGRESS"
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": status,
        "current_closed_outcome_count": outcome_count,
        "minimum_required_closed_outcomes": MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES,
        "closed_outcome_deficit_to_minimum": closed_outcome_deficit,
        "open_positions_ready_to_become_closed_outcomes": max(0, complete_open_row_count),
        "projected_closed_outcome_count_after_current_open_positions_close": (
            projected_after_open_close
        ),
        "projected_closed_outcome_deficit_after_current_open_positions_close": (
            projected_deficit_after_open_close
        ),
        "current_symbol_count": current_symbol_count,
        "minimum_required_symbol_count": MINIMUM_POLICY_SYMBOL_COUNT,
        "symbol_diversity_deficit": max(0, symbol_diversity_deficit),
        "timed_closed_outcome_count": len(timed_points),
        "first_closed_outcome_at": _iso_from_ms(first_ms),
        "latest_closed_outcome_at": _iso_from_ms(last_ms),
        "hours_since_latest_closed_outcome": (
            round(hours_since_latest_closed_outcome, 8)
            if hours_since_latest_closed_outcome is not None
            else None
        ),
        "observed_window_days": (
            round(observed_window_days, 8)
            if observed_window_days is not None
            else None
        ),
        "observed_closed_outcome_interval_count": interval_count,
        "observed_closed_outcomes_per_day": (
            round(observed_closed_outcomes_per_day, 8)
            if observed_closed_outcomes_per_day is not None
            else None
        ),
        "eta_days_to_300_closed_outcomes": (
            round(eta_days_to_300_closed_outcomes, 8)
            if eta_days_to_300_closed_outcomes is not None
            else None
        ),
        "eta_days_after_current_open_positions_close": (
            round(eta_days_after_current_open_positions_close, 8)
            if eta_days_after_current_open_positions_close is not None
            else None
        ),
        "rate_formula": "closed_outcome_intervals / days_between_first_and_latest_timed_closed_outcome",
        "eta_formula": "closed_outcome_deficit / observed_closed_outcomes_per_day",
        "runtime_evidence_acquisition_status": _runtime_evidence_acquisition_status(
            paper_status=paper_status,
            generated_utc=generated_utc,
        ),
        "counts_as_additional_pass_gate": False,
        "notes": (
            "Read-only acquisition forecast. It does not synthesize outcomes, relax the 300-outcome "
            "requirement, or count open positions as closed outcomes."
        ),
    }


def _expected_edge_bps(row: dict[str, Any]) -> float | None:
    edge = _coerce_float(_first_present(row.get("expected_move_after_cost_bps"), row.get("expected_net_edge_bps")))
    if edge is None:
        return None
    if _directional_side(row) == "short" and edge < 0.0:
        return abs(edge)
    return edge


def _expected_shortfall_usd(row: dict[str, Any]) -> float | None:
    return _coerce_float(row.get("expected_shortfall_usd"))


def _trade_time_sort_key(row: dict[str, Any]) -> tuple[int, str]:
    time_value = _first_present(
        row.get("closed_at"),
        row.get("exit_time"),
        row.get("execution_time"),
        row.get("decision_time"),
        row.get("generated_at"),
        row.get("event_time"),
    )
    parsed = _parse_epoch_ms(time_value)
    return (parsed if parsed is not None else 0, str(row.get("trade_id") or row.get("symbol") or ""))


def _realized_drawdown_pct(rows: list[dict[str, Any]], starting_equity: float) -> float:
    running_equity = max(1.0, starting_equity)
    peak_equity = running_equity
    max_drawdown = 0.0
    for row in sorted(rows, key=_trade_time_sort_key):
        running_equity += _pnl(row)
        peak_equity = max(peak_equity, running_equity)
        if peak_equity > 0.0:
            max_drawdown = max(max_drawdown, (peak_equity - running_equity) / peak_equity)
    return max(0.0, max_drawdown)


def _normalized_symbol(row: dict[str, Any]) -> str:
    return str(row.get("symbol") or "UNKNOWN").upper()


def _normalized_side(row: dict[str, Any]) -> str:
    return str(_first_present(row.get("side"), row.get("action"), "unknown")).lower()


def _directional_side(row: dict[str, Any]) -> str:
    raw = _first_present(
        row.get("side"),
        row.get("action"),
        row.get("selected_action"),
        row.get("proposed_action"),
        row.get("direction"),
    )
    text = str(raw or "").strip().lower()
    if text in {"short", "sell"}:
        return "short"
    if text in {"long", "buy"}:
        return "long"
    return text


def _is_a_grade(row: dict[str, Any]) -> bool:
    confidence = _coerce_float(_first_present(row.get("confidence_calibrated"), row.get("confidence"))) or 0.0
    edge = _expected_edge_bps(row) or 0.0
    decision = str(row.get("allocator_decision") or row.get("decision") or "")
    return confidence >= A_GRADE_CONFIDENCE_THRESHOLD and edge > 0.0 and not decision.startswith("BLOCK_")


def _positive_edge_non_a_grade_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    reason_counts: dict[str, int] = {}
    side_counts: dict[str, int] = {}
    timeframe_counts: dict[str, int] = {}
    confidence_values: list[float] = []
    edge_values: list[float] = []
    near_a_grade_count = 0
    diagnostics: list[dict[str, Any]] = []

    def add_reason(reason: str) -> None:
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    for row in rows:
        confidence = _coerce_float(_first_present(row.get("confidence_calibrated"), row.get("confidence")))
        edge = _expected_edge_bps(row)
        decision = _allocator_decision(row)
        side = _directional_side(row)
        timeframe = str(_row_value(row, "timeframe") or row.get("timeframe") or "UNKNOWN")
        row_reasons: list[str] = []

        side_counts[side or "unknown"] = side_counts.get(side or "unknown", 0) + 1
        timeframe_counts[timeframe] = timeframe_counts.get(timeframe, 0) + 1
        if confidence is not None:
            confidence_values.append(confidence)
            if confidence >= NEAR_A_GRADE_REPLAY_CONFIDENCE_THRESHOLD:
                near_a_grade_count += 1
        if edge is not None:
            edge_values.append(edge)

        if side not in {"long", "short"}:
            row_reasons.append("NON_DIRECTIONAL_ACTION")
        if confidence is None:
            row_reasons.append("MISSING_CONFIDENCE")
        elif confidence < A_GRADE_CONFIDENCE_THRESHOLD:
            row_reasons.append("LOW_CONFIDENCE")
        if edge is None:
            row_reasons.append("MISSING_AFTER_COST_EDGE")
        elif edge <= 0.0:
            row_reasons.append("NON_POSITIVE_AFTER_COST_EDGE")
        if decision.startswith("BLOCK_"):
            row_reasons.append(f"ALLOCATOR_{decision}")
        for reason in row_reasons:
            add_reason(reason)

        confidence_gap = (
            round(max(0.0, A_GRADE_CONFIDENCE_THRESHOLD - confidence), 8)
            if confidence is not None else None
        )
        edge_gap = round(max(0.0, -edge), 8) if edge is not None else None
        diagnostics.append({
            "symbol": _normalized_symbol(row),
            "timeframe": timeframe,
            "side": side,
            "confidence": round(confidence, 8) if confidence is not None else None,
            "confidence_gap_to_a_grade": confidence_gap,
            "after_cost_edge_bps": round(edge, 8) if edge is not None else None,
            "edge_gap_to_positive_bps": edge_gap,
            "allocator_decision": decision or None,
            "reasons": sorted(set(row_reasons)),
        })

    def confidence_gap_sort(row: dict[str, Any]) -> tuple[float, float, str, str]:
        confidence_gap = row.get("confidence_gap_to_a_grade")
        edge = row.get("after_cost_edge_bps")
        return (
            float(confidence_gap if confidence_gap is not None else 999.0),
            -float(edge if edge is not None else -999.0),
            str(row.get("symbol") or ""),
            str(row.get("timeframe") or ""),
        )

    sorted_by_gap = sorted(diagnostics, key=confidence_gap_sort)
    sorted_by_edge = sorted(
        diagnostics,
        key=lambda row: (
            -float(row.get("after_cost_edge_bps") if row.get("after_cost_edge_bps") is not None else -999.0),
            float(row.get("confidence_gap_to_a_grade") if row.get("confidence_gap_to_a_grade") is not None else 999.0),
            str(row.get("symbol") or ""),
            str(row.get("timeframe") or ""),
        ),
    )

    return {
        "row_count": len(rows),
        "confidence_threshold": A_GRADE_CONFIDENCE_THRESHOLD,
        "near_a_grade_confidence_threshold": NEAR_A_GRADE_REPLAY_CONFIDENCE_THRESHOLD,
        "near_a_grade_positive_edge_count": near_a_grade_count,
        "reason_counts": {key: reason_counts[key] for key in sorted(reason_counts)},
        "side_counts": {key: side_counts[key] for key in sorted(side_counts)},
        "timeframe_counts": {key: timeframe_counts[key] for key in sorted(timeframe_counts)},
        "max_confidence": round(max(confidence_values), 8) if confidence_values else None,
        "max_after_cost_edge_bps": round(max(edge_values), 8) if edge_values else None,
        "min_confidence_gap_to_a_grade": (
            sorted_by_gap[0].get("confidence_gap_to_a_grade") if sorted_by_gap else None
        ),
        "closest_positive_edge_to_a_grade": sorted_by_gap[0] if sorted_by_gap else None,
        "top_after_cost_edge_not_a_grade": sorted_by_edge[0] if sorted_by_edge else None,
        "sample": sorted_by_gap[:20],
    }


def _confidence_bucket(value: float | None) -> str:
    if value is None:
        return "__missing__"
    lower = math.floor(max(0.0, min(0.999999, value)) / 0.05) * 0.05
    upper = min(1.0, lower + 0.05)
    return f"{lower:.2f}-{upper:.2f}"


def _expected_move_bucket(value: float | None) -> str:
    if value is None:
        return "__missing__"
    abs_value = abs(value)
    for upper in (0.0, 10.0, 25.0, 50.0, 100.0, 200.0):
        if abs_value <= upper:
            return f"<= {upper:.0f}bps"
    return "> 200bps"


def _row_strategy(row: dict[str, Any]) -> str:
    strategy = _first_present(
        row.get("strategy"),
        row.get("strategy_family"),
        row.get("signal_strategy"),
        row.get("model_strategy"),
        row.get("source_strategy"),
        row.get("capital_allocation_reason"),
    )
    return str(strategy or "__unknown__")


def _symbol_cluster(symbol: str) -> str:
    base = symbol.upper().removesuffix("USDT")
    if base in {"BTC", "ETH"}:
        return "large_cap_core"
    if base in {"BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "LINK", "DOT", "SUI"}:
        return "large_cap_alt"
    if any(marker in base for marker in ("1000", "SHIB", "PEPE", "BONK", "FLOKI", "MEME")):
        return "meme_or_microstructure_amplified"
    if base.endswith(("UP", "DOWN", "BULL", "BEAR")):
        return "leveraged_token"
    return "alt_universe"


def _nested_context_value(row: dict[str, Any], *fields: str) -> Any:
    contexts = _nested_market_contexts(row)
    allocation = _allocation_mapping(row)
    model_inputs = allocation.get("model_inputs")
    if isinstance(model_inputs, dict):
        contexts.append(model_inputs)
    top_level_model_inputs = row.get("model_inputs")
    if isinstance(top_level_model_inputs, dict):
        contexts.append(top_level_model_inputs)
    for field in fields:
        value = _first_present(row.get(field), allocation.get(field))
        if value not in {None, ""}:
            return value
        for context in contexts:
            value = context.get(field)
            if value not in {None, ""}:
                return value
    return None


def _market_regime_bucket(row: dict[str, Any]) -> str:
    value = _nested_context_value(
        row,
        "market_regime",
        "regime",
        "regime_label",
        "market_state",
        "strategy_mode",
    )
    return str(value or "__unknown__").lower()


def _volatility_bucket(row: dict[str, Any]) -> str:
    explicit = _nested_context_value(row, "volatility_bucket", "vol_bucket")
    if explicit not in {None, ""}:
        return str(explicit).lower()
    value = _coerce_float(_nested_context_value(
        row,
        "entry_atr_bps",
        "atr_bps",
        "volatility_bps",
        "realized_volatility_bps",
    ))
    if value is None:
        return "__unknown__"
    if value < 50.0:
        return "low"
    if value < 150.0:
        return "medium"
    return "high"


def _liquidity_bucket(row: dict[str, Any]) -> str:
    explicit = _nested_context_value(row, "liquidity_bucket", "liquidity_tier")
    if explicit not in {None, ""}:
        return str(explicit).lower()
    score = _coerce_float(_nested_context_value(row, "liquidity_score"))
    if score is not None:
        if score >= 0.75:
            return "high"
        if score >= 0.35:
            return "medium"
        return "low"
    depth = _coerce_float(_nested_context_value(
        row,
        "orderbook_depth_usd",
        "market_depth_capacity_usd",
        "depth_usd",
    ))
    if depth is None:
        return "__unknown__"
    if depth >= 250_000.0:
        return "high"
    if depth >= 25_000.0:
        return "medium"
    return "low"


def _a_grade_bucket_key(row: dict[str, Any]) -> tuple[str, str, str, str, str, str, str, str, str]:
    confidence = _coerce_float(_first_present(row.get("confidence_calibrated"), row.get("confidence")))
    edge = _expected_edge_bps(row)
    return (
        _row_strategy(row),
        _directional_side(row) or "__unknown__",
        _symbol_cluster(_normalized_symbol(row)),
        str(_row_value(row, "timeframe") or row.get("timeframe") or "__unknown__"),
        _market_regime_bucket(row),
        _volatility_bucket(row),
        _liquidity_bucket(row),
        _confidence_bucket(confidence),
        _expected_move_bucket(edge),
    )


def _a_grade_bucket_key_payload(key: tuple[str, str, str, str, str, str, str, str, str]) -> dict[str, str]:
    fields = (
        "strategy",
        "side",
        "symbol_cluster",
        "timeframe",
        "market_regime",
        "volatility_bucket",
        "liquidity_bucket",
        "confidence_bucket",
        "expected_move_bucket",
    )
    return dict(zip(fields, key, strict=True))


def _outcome_after_cost_bps(row: dict[str, Any]) -> float | None:
    direct = _coerce_float(_first_present(
        row.get("realized_after_cost_return_bps"),
        row.get("realized_pnl_bps"),
        row.get("paper_exit_pnl_bps"),
        row.get("after_cost_return_bps"),
    ))
    if direct is not None:
        return direct
    pnl = _trade_outcome_pnl(row)
    notional = _notional(row)
    if pnl is None or notional <= 0.0:
        return None
    return pnl / notional * 10000.0


def _wilson_lower_bound(successes: int, sample_count: int, *, z: float = 1.96) -> float | None:
    if sample_count <= 0:
        return None
    p_hat = successes / sample_count
    denominator = 1.0 + z * z / sample_count
    centre = p_hat + z * z / (2.0 * sample_count)
    margin = z * math.sqrt((p_hat * (1.0 - p_hat) + z * z / (4.0 * sample_count)) / sample_count)
    return max(0.0, (centre - margin) / denominator)


def _max_drawdown_from_values(values: list[float]) -> float:
    running = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in values:
        running += value
        peak = max(peak, running)
        max_drawdown = max(max_drawdown, peak - running)
    return max_drawdown


def _worst_percentile_loss(values: list[float], percentile: float = 0.01) -> float | None:
    losses = sorted(value for value in values if value < 0.0)
    if not losses:
        return None
    index = min(len(losses) - 1, max(0, math.floor((len(losses) - 1) * percentile)))
    return losses[index]


def _profit_factor_from_values(values: list[float]) -> tuple[float | str | None, float | None]:
    gross_profit = sum(value for value in values if value > 0.0)
    gross_loss = abs(sum(value for value in values if value < 0.0))
    if gross_loss > 0.0:
        numeric = gross_profit / gross_loss
        return round(numeric, 8), numeric
    if gross_profit > 0.0:
        return "inf", math.inf
    return None, None


def _bucket_performance_row(
    *,
    key: tuple[str, str, str, str, str, str, str, str, str],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    values = [value for row in rows for value in [_outcome_after_cost_bps(row)] if value is not None]
    wins = [value for value in values if value > 0.0]
    losses = [value for value in values if value < 0.0]
    sample_count = len(values)
    win_count = len(wins)
    win_rate = win_count / sample_count if sample_count else None
    confidence_values = [
        value for row in rows
        for value in [_coerce_float(_first_present(row.get("confidence_calibrated"), row.get("confidence")))]
        if value is not None
    ]
    average_confidence = sum(confidence_values) / len(confidence_values) if confidence_values else None
    lower_bound = _wilson_lower_bound(win_count, sample_count)
    profit_factor, profit_factor_numeric = _profit_factor_from_values(values)
    expectancy = sum(values) / sample_count if sample_count else None
    temporal_pass_count = sum(1 for row in rows if not _pre_submit_temporal_reasons(row))
    execution_success_count = sum(
        1 for row in rows
        if _notional(row) > 0.0
        and _margin(row) > 0.0
        and not _allocator_decision(row).startswith("BLOCK_")
    )
    temporal_pass_rate = temporal_pass_count / len(rows) if rows else 0.0
    execution_success_probability = execution_success_count / len(rows) if rows else 0.0
    tail_limit_bps = CounterfactualRiskEnvelope().max_expected_shortfall_pct * 10000.0
    worst_loss = _worst_percentile_loss(values)
    market_state_integrity_passes = bool(rows) and temporal_pass_rate >= 1.0
    execution_success_probability_passes = bool(rows) and execution_success_probability >= 0.95
    tail_risk_envelope_passes = worst_loss is None or abs(worst_loss) <= tail_limit_bps
    sample_count_passes = sample_count >= DYNAMIC_A_GRADE_MIN_BUCKET_SAMPLE_COUNT
    lower_bound_passes = lower_bound is not None and lower_bound > DYNAMIC_A_GRADE_MIN_POSITIVE_OUTCOME_LCB
    expectancy_passes = expectancy is not None and expectancy > 0.0
    profit_factor_passes = (
        profit_factor_numeric is not None
        and profit_factor_numeric >= MINIMUM_POST_ALLOCATOR_PROFIT_FACTOR
    )
    eligibility_reasons: list[str] = []
    if not sample_count_passes:
        eligibility_reasons.append("INSUFFICIENT_BUCKET_SAMPLE_COUNT")
    if not lower_bound_passes:
        eligibility_reasons.append("LOWER_CONFIDENCE_BOUND_NOT_POSITIVE_ENOUGH")
    if not expectancy_passes:
        eligibility_reasons.append("NON_POSITIVE_AFTER_COST_EXPECTANCY")
    if not profit_factor_passes:
        eligibility_reasons.append("PROFIT_FACTOR_BELOW_MINIMUM")
    if not market_state_integrity_passes:
        eligibility_reasons.append("MARKET_STATE_INTEGRITY_NOT_PROVEN")
    if not execution_success_probability_passes:
        eligibility_reasons.append("EXECUTION_SUCCESS_PROBABILITY_NOT_PROVEN")
    if not tail_risk_envelope_passes:
        eligibility_reasons.append("TAIL_RISK_ENVELOPE_BREACH")
    return {
        **_a_grade_bucket_key_payload(key),
        "sample_count": sample_count,
        "win_rate_after_cost": round(win_rate, 8) if win_rate is not None else None,
        "expectancy_after_cost_bps": round(expectancy, 8) if expectancy is not None else None,
        "profit_factor": profit_factor,
        "profit_factor_numeric": (
            round(profit_factor_numeric, 8)
            if profit_factor_numeric is not None and math.isfinite(profit_factor_numeric)
            else profit_factor_numeric
        ),
        "average_win": round(sum(wins) / len(wins), 8) if wins else None,
        "average_loss": round(sum(losses) / len(losses), 8) if losses else None,
        "average_win_after_cost_bps": round(sum(wins) / len(wins), 8) if wins else None,
        "average_loss_after_cost_bps": round(sum(losses) / len(losses), 8) if losses else None,
        "maximum_drawdown": round(_max_drawdown_from_values(values), 8),
        "maximum_drawdown_after_cost_bps": round(_max_drawdown_from_values(values), 8),
        "worst_1_percent_loss": round(worst_loss, 8) if worst_loss is not None else None,
        "worst_1_percent_loss_after_cost_bps": round(worst_loss, 8) if worst_loss is not None else None,
        "calibration_error": (
            round(abs(average_confidence - win_rate), 8)
            if average_confidence is not None and win_rate is not None else None
        ),
        "lower_confidence_bound_positive_outcome": (
            round(lower_bound, 8) if lower_bound is not None else None
        ),
        "minimum_required_sample_count": DYNAMIC_A_GRADE_MIN_BUCKET_SAMPLE_COUNT,
        "minimum_positive_outcome_lcb": DYNAMIC_A_GRADE_MIN_POSITIVE_OUTCOME_LCB,
        "sample_count_passes": sample_count_passes,
        "lower_confidence_bound_passes": lower_bound_passes,
        "expectancy_after_cost_passes": expectancy_passes,
        "profit_factor_passes": profit_factor_passes,
        "market_state_integrity_passes": market_state_integrity_passes,
        "market_state_integrity_pass_rate": round(temporal_pass_rate, 8),
        "execution_success_probability": round(execution_success_probability, 8),
        "execution_success_probability_passes": execution_success_probability_passes,
        "tail_risk_envelope_passes": tail_risk_envelope_passes,
        "tail_risk_limit_bps": round(tail_limit_bps, 8),
        "dynamic_a_grade_eligible": not eligibility_reasons,
        "eligibility_blocker_reasons": eligibility_reasons,
    }


def _dynamic_a_grade_calibration_artifacts(
    *,
    evaluated_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    generated_utc: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str, str, str, str, str], list[dict[str, Any]]] = {}
    for row in evaluated_rows:
        if _directional_side(row) not in {"long", "short"}:
            continue
        if _outcome_after_cost_bps(row) is None:
            continue
        grouped.setdefault(_a_grade_bucket_key(row), []).append(row)

    bucket_rows = [
        _bucket_performance_row(key=key, rows=rows)
        for key, rows in grouped.items()
    ]
    bucket_rows.sort(
        key=lambda row: (
            not bool(row.get("dynamic_a_grade_eligible")),
            -int(row.get("sample_count") or 0),
            str(row.get("strategy")),
            str(row.get("timeframe")),
        )
    )
    eligible_bucket_keys = {
        tuple(row[field] for field in (
            "strategy",
            "side",
            "symbol_cluster",
            "timeframe",
            "market_regime",
            "volatility_bucket",
            "liquidity_bucket",
            "confidence_bucket",
            "expected_move_bucket",
        ))
        for row in bucket_rows
        if row.get("dynamic_a_grade_eligible") is True
    }
    dynamic_candidates: list[dict[str, Any]] = []
    positive_edge_rows = [
        row for row in candidate_rows
        if (_expected_edge_bps(row) or 0.0) > 0.0 and _directional_side(row) in {"long", "short"}
    ]
    strict_a_grade_count = 0
    b_grade_rows: list[dict[str, Any]] = []
    shadow_rows: list[dict[str, Any]] = []
    no_trade_rows: list[dict[str, Any]] = []
    classification_counts: dict[str, int] = {}

    bucket_by_key = {
        tuple(row[field] for field in (
            "strategy",
            "side",
            "symbol_cluster",
            "timeframe",
            "market_regime",
            "volatility_bucket",
            "liquidity_bucket",
            "confidence_bucket",
            "expected_move_bucket",
        )): row
        for row in bucket_rows
    }

    for row in candidate_rows:
        edge = _expected_edge_bps(row)
        side = _directional_side(row)
        key = _a_grade_bucket_key(row)
        bucket = bucket_by_key.get(key, {})
        temporal_reasons = _pre_submit_temporal_reasons(row)
        market_state_valid = not temporal_reasons
        strict_a_grade = _is_a_grade(row)
        if strict_a_grade:
            strict_a_grade_count += 1
        dynamic_eligible = (
            key in eligible_bucket_keys
            and edge is not None
            and edge > 0.0
            and side in {"long", "short"}
            and market_state_valid
            and not _allocator_decision(row).startswith("BLOCK_")
        )
        if dynamic_eligible:
            classification = "A_GRADE_EXECUTION_PAPER"
        elif edge is not None and edge > 0.0 and side in {"long", "short"} and market_state_valid:
            classification = "B_GRADE_EXPLORATION_PAPER"
        elif edge is not None and edge > 0.0 and side in {"long", "short"}:
            classification = "SHADOW_ONLY"
        else:
            classification = "NO_TRADE"
        classification_counts[classification] = classification_counts.get(classification, 0) + 1

        uncertainty = 1.0 - min(1.0, float(bucket.get("lower_confidence_bound_positive_outcome") or 0.0))
        calibration_error = float(bucket.get("calibration_error") or 0.25)
        drawdown_pressure = min(1.0, abs(float(bucket.get("worst_1_percent_loss") or 0.0)) / 300.0)
        exploration_fraction = EXPLORATION_MAX_RISK_BUDGET_FRACTION * (
            1.0 - min(0.9, uncertainty * 0.5 + calibration_error * 0.3 + drawdown_pressure * 0.2)
        )
        exploration_fraction = max(
            EXPLORATION_MIN_RISK_BUDGET_FRACTION,
            min(EXPLORATION_MAX_RISK_BUDGET_FRACTION, exploration_fraction),
        )
        sample = {
            "symbol": _normalized_symbol(row),
            "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
            "side": side,
            "confidence": _coerce_float(_first_present(row.get("confidence_calibrated"), row.get("confidence"))),
            "after_cost_edge_bps": edge,
            "strict_a_grade": strict_a_grade,
            "dynamic_a_grade_eligible": dynamic_eligible,
            "classification": classification,
            "paper_only": True,
            "places_real_order": False,
            "live_gate": LIVE_GATE,
            "risk_budget_fraction_of_normal_adaptive": (
                1.0 if classification == "A_GRADE_EXECUTION_PAPER" else
                round(exploration_fraction, 8) if classification == "B_GRADE_EXPLORATION_PAPER" else 0.0
            ),
            "risk_fraction_formula": (
                "fraction_of_normal_adaptive_budget_reduced_by_uncertainty_calibration_error_and_tail_drawdown"
            ),
            "bucket_sample_count": bucket.get("sample_count"),
            "bucket_lower_confidence_bound_positive_outcome": (
                bucket.get("lower_confidence_bound_positive_outcome")
            ),
            "bucket_expectancy_after_cost_bps": bucket.get("expectancy_after_cost_bps"),
            "bucket_profit_factor": bucket.get("profit_factor"),
            "market_state_valid": market_state_valid,
            "market_state_reject_reasons": temporal_reasons,
            "source_redis_key": row.get("source_redis_key"),
        }
        if classification == "A_GRADE_EXECUTION_PAPER":
            dynamic_candidates.append(sample)
        elif classification == "B_GRADE_EXPLORATION_PAPER":
            b_grade_rows.append(sample)
        elif classification == "SHADOW_ONLY":
            shadow_rows.append(sample)
        else:
            no_trade_rows.append(sample)

    dynamic_status_reasons: list[str] = []
    if not grouped:
        dynamic_status_reasons.append("NO_EVALUATED_OUTCOME_BUCKETS")
    if not eligible_bucket_keys:
        dynamic_status_reasons.append("NO_DYNAMIC_A_GRADE_ELIGIBLE_BUCKETS")
    if not dynamic_candidates:
        dynamic_status_reasons.append("NO_CURRENT_DYNAMIC_A_GRADE_CANDIDATES")
    calibration_status = (
        "PASSED" if not dynamic_status_reasons else
        "BLOCKED_DYNAMIC_A_GRADE_CALIBRATION_NOT_PROVEN"
    )
    matrix = {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "phase_id": STOP_WAITING_PHASE_ID,
        "generated_utc": generated_utc,
        "status": "READY" if bucket_rows else "NO_EVALUATED_OUTCOME_BUCKETS",
        "grouping_dimensions": [
            "strategy",
            "side",
            "symbol_cluster",
            "timeframe",
            "market_regime",
            "volatility_bucket",
            "liquidity_bucket",
            "confidence_bucket",
            "expected_move_bucket",
        ],
        "evaluated_outcome_row_count": sum(int(row.get("sample_count") or 0) for row in bucket_rows),
        "bucket_count": len(bucket_rows),
        "eligible_bucket_count": len(eligible_bucket_keys),
        "minimum_bucket_sample_count": DYNAMIC_A_GRADE_MIN_BUCKET_SAMPLE_COUNT,
        "minimum_positive_outcome_lcb": DYNAMIC_A_GRADE_MIN_POSITIVE_OUTCOME_LCB,
        "buckets": bucket_rows,
    }
    calibration = {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "phase_id": STOP_WAITING_PHASE_ID,
        "generated_utc": generated_utc,
        "status": calibration_status,
        "blocker_reasons": dynamic_status_reasons,
        "fixed_global_confidence_threshold_preserved": A_GRADE_CONFIDENCE_THRESHOLD,
        "global_threshold_lowered": False,
        "dynamic_contract": {
            "candidate_is_a_grade_only_when": [
                "lower_confidence_bound_positive_outcome_gt_configured_minimum",
                "expectancy_after_all_costs_gt_zero",
                "profit_factor_gt_minimum",
                "market_state_integrity_passes",
                "execution_success_probability_passes",
                "tail_risk_envelope_passes",
            ],
            "minimum_bucket_sample_count": DYNAMIC_A_GRADE_MIN_BUCKET_SAMPLE_COUNT,
            "minimum_positive_outcome_lcb": DYNAMIC_A_GRADE_MIN_POSITIVE_OUTCOME_LCB,
            "minimum_profit_factor": MINIMUM_POST_ALLOCATOR_PROFIT_FACTOR,
        },
        "evaluated_outcome_row_count": matrix["evaluated_outcome_row_count"],
        "bucket_count": len(bucket_rows),
        "eligible_bucket_count": len(eligible_bucket_keys),
        "strict_a_grade_candidate_count": strict_a_grade_count,
        "dynamic_a_grade_candidate_count": len(dynamic_candidates),
        "positive_edge_candidate_count": len(positive_edge_rows),
        "dynamic_a_grade_candidate_sample": dynamic_candidates[:20],
        "eligible_bucket_sample": [row for row in bucket_rows if row.get("dynamic_a_grade_eligible")][:20],
        "paper_only": True,
        "places_real_order": False,
        "live_gate": LIVE_GATE,
    }
    resolution_status = (
        "READY_EXPLORATION_TIERS_ASSIGNED"
        if positive_edge_rows and (dynamic_candidates or b_grade_rows or shadow_rows)
        else "NO_POSITIVE_EDGE_ROWS_TO_RESOLVE"
        if not positive_edge_rows else "BLOCKED_POSITIVE_EDGE_RESOLUTION_EMPTY"
    )
    resolution = {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "phase_id": STOP_WAITING_PHASE_ID,
        "generated_utc": generated_utc,
        "status": resolution_status,
        "paper_only": True,
        "places_real_order": False,
        "live_gate": LIVE_GATE,
        "allowed_tiers": [
            "A_GRADE_EXECUTION_PAPER",
            "B_GRADE_EXPLORATION_PAPER",
            "SHADOW_ONLY",
            "NO_TRADE",
        ],
        "fixed_dollar_budget_used": False,
        "risk_budget_basis": "fraction_of_normal_adaptive_risk_budget",
        "classification_counts": {
            key: classification_counts[key] for key in sorted(classification_counts)
        },
        "positive_edge_candidate_count": len(positive_edge_rows),
        "dynamic_a_grade_candidate_count": len(dynamic_candidates),
        "b_grade_exploration_candidate_count": len(b_grade_rows),
        "shadow_only_candidate_count": len(shadow_rows),
        "no_trade_candidate_count": len(no_trade_rows),
        "a_grade_execution_paper_sample": dynamic_candidates[:20],
        "b_grade_exploration_paper_sample": b_grade_rows[:20],
        "shadow_only_sample": shadow_rows[:20],
        "no_trade_sample": no_trade_rows[:20],
    }
    return calibration, matrix, resolution


def _accelerated_replay_simulation_accounting_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    missing_counts: dict[str, int] = {field_id: 0 for field_id, _fields, _positive in ACCELERATED_REPLAY_SIMULATION_FIELD_GROUPS}
    source_counts: dict[str, dict[str, int]] = {
        field_id: {}
        for field_id, _fields, _positive in ACCELERATED_REPLAY_SIMULATION_FIELD_GROUPS
    }
    complete_rows = 0
    incomplete_samples: list[dict[str, Any]] = []
    for row in rows:
        missing: list[str] = []
        for field_id, fields, positive_required in ACCELERATED_REPLAY_SIMULATION_FIELD_GROUPS:
            source_field = _market_evidence_field(row, fields, positive_required=positive_required)
            if source_field is None:
                missing_counts[field_id] += 1
                missing.append(field_id)
            else:
                counts = source_counts[field_id]
                counts[source_field] = counts.get(source_field, 0) + 1
        if not missing:
            complete_rows += 1
        elif len(incomplete_samples) < 20:
            incomplete_samples.append({
                "symbol": _normalized_symbol(row),
                "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
                "side": _directional_side(row),
                "source_kind": _counterfactual_source_kind(row),
                "missing_field_groups": missing,
            })

    row_count = len(rows)
    field_coverage = {
        field_id: round((row_count - missing_counts[field_id]) / row_count, 8) if row_count else 0.0
        for field_id, _fields, _positive in ACCELERATED_REPLAY_SIMULATION_FIELD_GROUPS
    }
    return {
        "status": "PASSED" if row_count and complete_rows == row_count else "INCOMPLETE_SIMULATION_ACCOUNTING_COVERAGE",
        "required_field_groups": [
            field_id for field_id, _fields, _positive in ACCELERATED_REPLAY_SIMULATION_FIELD_GROUPS
        ],
        "row_count": row_count,
        "complete_row_count": complete_rows,
        "incomplete_row_count": row_count - complete_rows,
        "complete_coverage_ratio": round(complete_rows / row_count, 8) if row_count else 0.0,
        "field_coverage": field_coverage,
        "missing_field_group_counts": {
            key: missing_counts[key]
            for key in sorted(missing_counts)
            if missing_counts[key] > 0
        },
        "field_source_counts": {
            key: {source: counts[source] for source in sorted(counts)}
            for key, counts in sorted(source_counts.items())
            if counts
        },
        "incomplete_sample": incomplete_samples,
    }


def _source_file_fingerprint(path: Path) -> dict[str, Any]:
    digest = None
    byte_count = None
    try:
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        byte_count = len(payload)
    except Exception:
        pass
    return {
        "path": str(path.relative_to(REPO_ROOT) if path.is_absolute() and path.is_relative_to(REPO_ROOT) else path),
        "exists": path.exists(),
        "sha256": digest,
        "byte_count": byte_count,
    }


def _callable_source_fingerprint(fn: Any) -> dict[str, Any]:
    try:
        source = inspect.getsource(fn)
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    except Exception as exc:  # noqa: BLE001
        source = ""
        digest = None
        error = str(exc)
    else:
        error = None
    return {
        "callable": getattr(fn, "__name__", str(fn)),
        "module": getattr(fn, "__module__", None),
        "sha256": digest,
        "source_line_count": len(source.splitlines()) if source else 0,
        "error": error,
    }


def _frozen_live_grade_policy_manifest(generated_utc: str) -> dict[str, Any]:
    selector_functions = (
        _a_grade_bucket_key,
        _bucket_performance_row,
        _dynamic_a_grade_calibration_artifacts,
        _eligible_bucket_keys_from_matrix,
        _dynamic_validated_replay_deployment_audit,
        _qualified_replay_policy_evidence_status,
        _market_regime_bucket,
        _volatility_bucket,
        _liquidity_bucket,
        _confidence_bucket,
        _expected_move_bucket,
        run_counterfactual_sweep,
    )
    allocator_source_files = (
        REPO_ROOT / "v2/backend/app/services/adaptive_capital_allocator/allocator.py",
        REPO_ROOT / "v2/backend/app/services/adaptive_capital_allocator/contracts.py",
        REPO_ROOT / "v2/backend/app/services/adaptive_capital_allocator/counterfactual.py",
        REPO_ROOT / "v2/backend/app/services/adaptive_capital_allocator/exchange_filters.py",
        REPO_ROOT / "v2/backend/app/services/adaptive_capital_allocator/risk_budget.py",
        REPO_ROOT / "v2/backend/app/services/adaptive_capital_allocator/sizing_model.py",
        REPO_ROOT / "v2/backend/app/services/adaptive_capital_allocator/strategy_weights.py",
        Path(__file__).resolve(),
    )
    frozen_thresholds = {
        "strict_a_grade_confidence_threshold": A_GRADE_CONFIDENCE_THRESHOLD,
        "dynamic_a_grade_min_bucket_sample_count": DYNAMIC_A_GRADE_MIN_BUCKET_SAMPLE_COUNT,
        "dynamic_a_grade_min_positive_outcome_lcb": DYNAMIC_A_GRADE_MIN_POSITIVE_OUTCOME_LCB,
        "minimum_holdout_a_grade_outcomes": OUT_OF_SAMPLE_MIN_HOLDOUT_OUTCOMES,
        "minimum_realtime_a_grade_closed_paper_outcomes": OUT_OF_SAMPLE_MIN_REALTIME_CLOSED_OUTCOMES,
        "minimum_symbol_count": OUT_OF_SAMPLE_MIN_SYMBOL_COUNT,
        "minimum_profit_factor": OUT_OF_SAMPLE_MIN_PROFIT_FACTOR,
        "maximum_worst_1pct_loss_bps": OUT_OF_SAMPLE_MAX_WORST_1PCT_LOSS_BPS,
        "maximum_profit_concentration_share": OUT_OF_SAMPLE_MAX_PROFIT_CONCENTRATION_SHARE,
        "minimum_realtime_to_replay_expectancy_ratio": OUT_OF_SAMPLE_REALTIME_REPLAY_EXPECTANCY_MIN_RATIO,
    }
    callable_hashes = {
        item["callable"]: item
        for item in (_callable_source_fingerprint(fn) for fn in selector_functions)
    }
    source_hashes = {
        fingerprint["path"]: fingerprint
        for fingerprint in (_source_file_fingerprint(path) for path in allocator_source_files)
    }
    frozen_material = {
        "gate_id": OUT_OF_SAMPLE_REVERIFY_GATE_ID,
        "policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
        "bucket_rule_function_hashes": callable_hashes,
        "allocator_source_hashes": source_hashes,
        "thresholds": frozen_thresholds,
        "sidecar_contract": {
            "holdout_rows_path": str(OUT_OF_SAMPLE_HOLDOUT_REVERIFY_ROWS_PATH),
            "realtime_rows_path": str(OUT_OF_SAMPLE_REALTIME_REVERIFY_ROWS_PATH),
            "row_must_carry_matching_selector_policy_fingerprint": True,
            "candidate_selected_before_outcome": True,
            "future_labels_used_as_features_allowed": False,
            "holdout_overlap_with_229_candidate_construction_allowed": False,
        },
        "operator_safety_envelope": {
            "paper_only": True,
            "places_real_order": False,
            "test_orders": False,
            "leverage_mutation": False,
            "margin_mode_mutation": False,
            "live_gate": LIVE_GATE,
        },
    }
    fingerprint = hashlib.sha256(
        json.dumps(frozen_material, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return {
        "status": "FROZEN",
        "gate_id": OUT_OF_SAMPLE_REVERIFY_GATE_ID,
        "frozen_at": generated_utc,
        "selector_policy_fingerprint": fingerprint,
        **frozen_material,
    }


def _load_reverify_rows(
    *,
    rows: list[dict[str, Any]] | None,
    path: Path | None,
    default_path: Path,
    source: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_status: dict[str, Any] = {
        "source": source,
        "path": str(path or default_path),
        "provided_in_memory": rows is not None,
    }
    if rows is not None:
        clean_rows = [dict(row) for row in rows if isinstance(row, dict)]
        source_status.update({
            "exists": True,
            "scanned_line_count": len(clean_rows),
            "parse_error_count": 0,
            "parse_error_sample": [],
        })
        return clean_rows, source_status
    loaded_rows: list[dict[str, Any]] = []
    for _line_number, row in _iter_jsonl_dicts(path or default_path, source_status=source_status):
        loaded_rows.append(row)
    return loaded_rows, source_status


def _reverify_candidate_selected(row: dict[str, Any]) -> bool:
    tier = str(_first_present(
        row.get("candidate_selection_tier"),
        row.get("paper_opportunity_tier"),
        row.get("reverify_tier"),
        row.get("deployment_tier"),
        "",
    ))
    return (
        row.get("out_of_sample_reverify_candidate") is True
        or row.get("a_grade_reverify_candidate") is True
        or tier == "A_GRADE_EXECUTION_PAPER"
    )


def _row_policy_fingerprint(row: dict[str, Any]) -> str:
    return str(_first_present(
        row.get("selector_policy_fingerprint"),
        row.get("frozen_selector_fingerprint"),
        row.get("policy_fingerprint"),
        row.get("candidate_selector_fingerprint"),
        "",
    ))


def _truthy_reverify_flag(row: dict[str, Any], *fields: str) -> bool:
    return any(row.get(field) is True for field in fields)


def _falsey_reverify_flag(row: dict[str, Any], *fields: str) -> bool:
    return any(row.get(field) is False for field in fields)


def _reverify_row_reject_reasons(
    row: dict[str, Any],
    *,
    fingerprint: str,
    scope: str,
) -> list[str]:
    reasons: list[str] = []
    symbol = _normalized_symbol(row)
    timeframe = str(_row_value(row, "timeframe") or row.get("timeframe") or "")
    side = _directional_side(row)
    if not _reverify_candidate_selected(row):
        reasons.append("NOT_A_GRADE_REVERIFY_CANDIDATE")
    if _row_policy_fingerprint(row) != fingerprint:
        reasons.append("FROZEN_SELECTOR_POLICY_FINGERPRINT_MISMATCH")
    if not _truthy_reverify_flag(
        row,
        "selected_before_outcome",
        "candidate_selected_before_outcome",
        "selector_ran_before_outcome",
    ):
        reasons.append("CANDIDATE_SELECTION_NOT_PROVEN_BEFORE_OUTCOME")
    if row.get("future_labels_used_as_features") is True:
        reasons.append("FUTURE_LABELS_USED_AS_FEATURES")
    if row.get("future_label_used_as_outcome_only") is False:
        reasons.append("FUTURE_LABEL_NOT_LIMITED_TO_OUTCOME_ONLY")
    if symbol == "UNKNOWN":
        reasons.append("MISSING_SYMBOL")
    if not timeframe or timeframe == "UNKNOWN":
        reasons.append("MISSING_TIMEFRAME")
    if side not in {"long", "short"}:
        reasons.append("NON_DIRECTIONAL_SIDE")
    if _outcome_after_cost_bps(row) is None and _trade_outcome_pnl(row) is None:
        reasons.append("MISSING_AFTER_COST_OR_PNL_OUTCOME")
    if _expected_edge_bps(row) is None or (_expected_edge_bps(row) or 0.0) <= 0.0:
        reasons.append("NON_POSITIVE_DECISION_TIME_EXPECTED_EDGE")
    if _allocator_decision(row).startswith("BLOCK_"):
        reasons.append("ALLOCATOR_BLOCKED_CANDIDATE")
    if not _closed_flag_confirmed(row, source_key=str(row.get("source_redis_key") or "")):
        reasons.append("UNFINISHED_CANDLE")
    reasons.extend(_pre_submit_temporal_reasons(row))
    decision = _parse_utc(_first_present(
        row.get("decision_time"),
        row.get("entry_feature_decision_time"),
        row.get("generated_utc"),
        row.get("generated_at"),
    ))
    outcome_time = _parse_utc(_first_present(
        row.get("future_label_close_time"),
        row.get("closed_at"),
        row.get("exit_time"),
        row.get("execution_time"),
        row.get("outcome_available_at"),
    ))
    if decision is not None and outcome_time is not None and outcome_time <= decision:
        reasons.append("OUTCOME_TIME_NOT_AFTER_DECISION_TIME")
    if scope == "holdout":
        if not _truthy_reverify_flag(row, "untouched_holdout_window", "out_of_sample_holdout"):
            reasons.append("UNTOUCHED_HOLDOUT_WINDOW_NOT_PROVEN")
        if str(row.get("holdout_window_id") or "").strip() == "":
            reasons.append("MISSING_HOLDOUT_WINDOW_ID")
        if _truthy_reverify_flag(
            row,
            "used_for_dynamic_a_grade_bucket_construction",
            "used_for_229_candidate_subset",
            "selector_training_window_overlap",
        ):
            reasons.append("HOLDOUT_OVERLAPS_SELECTOR_CONSTRUCTION")
    else:
        if row.get("paper_only") is not True:
            reasons.append("REALTIME_REVERIFY_NOT_MARKED_PAPER_ONLY")
        if row.get("places_real_order") is not False:
            reasons.append("REALTIME_REVERIFY_REAL_ORDER_FLAG_NOT_FALSE")
    return sorted(set(reasons))


def _concentration_status(
    rows: list[dict[str, Any]],
    *,
    dimension: str,
) -> dict[str, Any]:
    positive_by_key: dict[str, float] = {}
    for row in rows:
        metric = _outcome_after_cost_bps(row)
        if metric is None:
            metric = _trade_outcome_pnl(row)
        if metric is None or metric <= 0.0:
            continue
        if dimension == "symbol":
            key = _normalized_symbol(row)
        elif dimension == "timeframe":
            key = str(_row_value(row, "timeframe") or row.get("timeframe") or "UNKNOWN")
        elif dimension == "regime":
            key = _market_regime_bucket(row)
        elif dimension == "strategy":
            key = _row_strategy(row)
        else:
            key = "UNKNOWN"
        positive_by_key[key] = positive_by_key.get(key, 0.0) + metric
    gross_profit = sum(positive_by_key.values())
    if gross_profit <= 0.0:
        return {
            "dimension": dimension,
            "status": "NO_GROSS_PROFIT",
            "top_key": None,
            "top_profit_share": None,
            "maximum_allowed_top_profit_share": OUT_OF_SAMPLE_MAX_PROFIT_CONCENTRATION_SHARE,
        }
    top_key, top_profit = max(positive_by_key.items(), key=lambda item: item[1])
    top_share = top_profit / gross_profit
    return {
        "dimension": dimension,
        "status": "PASSED" if top_share <= OUT_OF_SAMPLE_MAX_PROFIT_CONCENTRATION_SHARE else "CONCENTRATED",
        "top_key": top_key,
        "top_profit_share": round(top_share, 8),
        "maximum_allowed_top_profit_share": OUT_OF_SAMPLE_MAX_PROFIT_CONCENTRATION_SHARE,
        "positive_key_count": len(positive_by_key),
        "gross_positive_metric_sum": round(gross_profit, 8),
        "top_positive_metric_sum": round(top_profit, 8),
    }


def _reverify_metric_status(
    rows: list[dict[str, Any]],
    *,
    source_status: dict[str, Any],
    scope: str,
    fingerprint: str,
    minimum_outcomes: int,
    minimum_symbols: int,
) -> dict[str, Any]:
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict):
            deduped.setdefault(_row_identity(row), row)
    valid_rows: list[dict[str, Any]] = []
    rejected_reason_counts: dict[str, int] = {}
    rejected_sample: list[dict[str, Any]] = []
    for row in deduped.values():
        reasons = _reverify_row_reject_reasons(row, fingerprint=fingerprint, scope=scope)
        if reasons:
            for reason in reasons:
                rejected_reason_counts[reason] = rejected_reason_counts.get(reason, 0) + 1
            if len(rejected_sample) < 20:
                rejected_sample.append({
                    "symbol": _normalized_symbol(row),
                    "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
                    "side": _directional_side(row),
                    "decision_time": _first_present(row.get("decision_time"), row.get("entry_feature_decision_time")),
                    "outcome_time": _first_present(row.get("future_label_close_time"), row.get("closed_at"), row.get("exit_time")),
                    "selector_policy_fingerprint": _row_policy_fingerprint(row),
                    "reasons": reasons,
                })
            continue
        valid_rows.append(row)

    after_cost_values = [
        value for row in valid_rows
        for value in [_outcome_after_cost_bps(row)]
        if value is not None
    ]
    pnl_values = [
        value for row in valid_rows
        for value in [_trade_outcome_pnl(row)]
        if value is not None
    ]
    metric_values = after_cost_values if after_cost_values else pnl_values
    profit_factor, profit_factor_numeric = _profit_factor_from_values(metric_values)
    expectancy_after_cost_bps = (
        sum(after_cost_values) / len(after_cost_values)
        if after_cost_values else None
    )
    average_pnl_usd = sum(pnl_values) / len(pnl_values) if pnl_values else None
    symbols = sorted({_normalized_symbol(row) for row in valid_rows if _normalized_symbol(row) != "UNKNOWN"})
    timeframes = sorted({
        str(_row_value(row, "timeframe") or row.get("timeframe"))
        for row in valid_rows
        if _row_value(row, "timeframe") or row.get("timeframe")
    })
    side_counts: dict[str, int] = {}
    regime_counts: dict[str, int] = {}
    strategy_counts: dict[str, int] = {}
    for row in valid_rows:
        side = _directional_side(row)
        if side in {"long", "short"}:
            side_counts[side] = side_counts.get(side, 0) + 1
        regime = _market_regime_bucket(row)
        regime_counts[regime] = regime_counts.get(regime, 0) + 1
        strategy = _row_strategy(row)
        strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
    worst_1pct_loss = _worst_percentile_loss(metric_values, percentile=0.01)
    accounting_coverage = _accelerated_replay_simulation_accounting_coverage(valid_rows)
    concentration = {
        dimension: _concentration_status(valid_rows, dimension=dimension)
        for dimension in ("symbol", "timeframe", "regime", "strategy")
    }
    concentration_failures = [
        dimension
        for dimension, status in concentration.items()
        if status.get("status") == "CONCENTRATED"
    ]
    blockers: list[str] = []
    if len(valid_rows) < minimum_outcomes:
        blockers.append(f"INSUFFICIENT_{scope.upper()}_A_GRADE_OUTCOMES")
    if len(symbols) < minimum_symbols:
        blockers.append(f"INSUFFICIENT_{scope.upper()}_SYMBOL_DIVERSITY")
    if side_counts.get("long", 0) <= 0:
        blockers.append(f"MISSING_{scope.upper()}_LONG_OUTCOMES")
    if side_counts.get("short", 0) <= 0:
        blockers.append(f"MISSING_{scope.upper()}_SHORT_OUTCOMES")
    if expectancy_after_cost_bps is None or expectancy_after_cost_bps <= 0.0:
        blockers.append(f"NON_POSITIVE_{scope.upper()}_AFTER_COST_EXPECTANCY")
    if profit_factor_numeric is None or profit_factor_numeric < OUT_OF_SAMPLE_MIN_PROFIT_FACTOR:
        blockers.append(f"{scope.upper()}_PROFIT_FACTOR_BELOW_1_5")
    if (
        worst_1pct_loss is not None
        and abs(worst_1pct_loss) > OUT_OF_SAMPLE_MAX_WORST_1PCT_LOSS_BPS
    ):
        blockers.append(f"{scope.upper()}_WORST_1PCT_LOSS_LIMIT_BREACH")
    if accounting_coverage.get("status") != "PASSED":
        blockers.append(f"{scope.upper()}_ACCOUNTING_COVERAGE_INCOMPLETE")
    if concentration_failures:
        blockers.append(f"{scope.upper()}_PROFIT_CONCENTRATION_EXCEEDED")
    if not valid_rows and rejected_reason_counts:
        blockers.append(f"NO_VALID_{scope.upper()}_FROZEN_SELECTOR_ROWS")
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "gate_id": OUT_OF_SAMPLE_REVERIFY_GATE_ID,
        "scope": scope,
        "status": "PASSED" if not blockers else f"NO_GO_{scope.upper()}_REVERIFY_INCOMPLETE",
        "blocker_reasons": blockers,
        "source_status": source_status,
        "source_row_count": len(rows),
        "deduped_row_count": len(deduped),
        "valid_frozen_selector_row_count": len(valid_rows),
        "rejected_row_count": len(deduped) - len(valid_rows),
        "rejected_reason_counts": {
            key: rejected_reason_counts[key] for key in sorted(rejected_reason_counts)
        },
        "rejected_sample": rejected_sample,
        "minimum_required_a_grade_outcomes": minimum_outcomes,
        "minimum_required_symbol_count": minimum_symbols,
        "symbol_count": len(symbols),
        "symbols_sample": symbols[:100],
        "timeframes": timeframes,
        "side_counts": {key: side_counts[key] for key in sorted(side_counts)},
        "strategy_family_counts": {key: strategy_counts[key] for key in sorted(strategy_counts)},
        "market_regime_counts": {key: regime_counts[key] for key in sorted(regime_counts)},
        "after_cost_bps_count": len(after_cost_values),
        "expectancy_after_cost_bps": (
            round(expectancy_after_cost_bps, 8)
            if expectancy_after_cost_bps is not None else None
        ),
        "average_pnl_usd": round(average_pnl_usd, 8) if average_pnl_usd is not None else None,
        "net_pnl_usd": round(sum(pnl_values), 8) if pnl_values else None,
        "profit_factor": profit_factor,
        "profit_factor_numeric": (
            "inf" if profit_factor_numeric == math.inf else round(profit_factor_numeric, 8)
            if profit_factor_numeric is not None else None
        ),
        "minimum_required_profit_factor": OUT_OF_SAMPLE_MIN_PROFIT_FACTOR,
        "max_drawdown_metric": round(_max_drawdown_from_values(metric_values), 8) if metric_values else None,
        "worst_1pct_loss_metric": round(worst_1pct_loss, 8) if worst_1pct_loss is not None else None,
        "maximum_allowed_worst_1pct_loss_bps": OUT_OF_SAMPLE_MAX_WORST_1PCT_LOSS_BPS,
        "simulation_accounting_coverage_status": accounting_coverage,
        "profit_concentration_status": concentration,
        "profit_concentration_failure_dimensions": concentration_failures,
        "valid_sample": [
            {
                "symbol": _normalized_symbol(row),
                "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
                "side": _directional_side(row),
                "decision_time": _first_present(row.get("decision_time"), row.get("entry_feature_decision_time")),
                "outcome_time": _first_present(row.get("future_label_close_time"), row.get("closed_at"), row.get("exit_time")),
                "expected_edge_bps": _expected_edge_bps(row),
                "outcome_after_cost_bps": _outcome_after_cost_bps(row),
                "pnl_usd": _trade_outcome_pnl(row),
                "selector_policy_fingerprint": _row_policy_fingerprint(row),
            }
            for row in valid_rows[:20]
        ],
    }


def _out_of_sample_live_grade_reverify_status(
    *,
    generated_utc: str,
    operator_safety: dict[str, Any],
    accelerated_replay_status: dict[str, Any],
    holdout_rows: list[dict[str, Any]],
    holdout_source_status: dict[str, Any],
    realtime_rows: list[dict[str, Any]],
    realtime_source_status: dict[str, Any],
) -> dict[str, Any]:
    frozen_manifest = _frozen_live_grade_policy_manifest(generated_utc)
    fingerprint = frozen_manifest["selector_policy_fingerprint"]
    holdout_status = _reverify_metric_status(
        holdout_rows,
        source_status=holdout_source_status,
        scope="holdout",
        fingerprint=fingerprint,
        minimum_outcomes=OUT_OF_SAMPLE_MIN_HOLDOUT_OUTCOMES,
        minimum_symbols=OUT_OF_SAMPLE_MIN_SYMBOL_COUNT,
    )
    realtime_status = _reverify_metric_status(
        realtime_rows,
        source_status=realtime_source_status,
        scope="realtime",
        fingerprint=fingerprint,
        minimum_outcomes=OUT_OF_SAMPLE_MIN_REALTIME_CLOSED_OUTCOMES,
        minimum_symbols=OUT_OF_SAMPLE_MIN_SYMBOL_COUNT,
    )
    replay_projection = accelerated_replay_status.get("validated_replay_deployment_status")
    if not isinstance(replay_projection, dict):
        replay_projection = {}
    replay_expectancy = _coerce_float(_first_present(
        accelerated_replay_status.get("validated_replay_expectancy_after_cost_bps"),
        replay_projection.get("expectancy_after_cost_bps"),
    ))
    replay_pf_raw = _first_present(
        accelerated_replay_status.get("validated_replay_profit_factor"),
        replay_projection.get("profit_factor"),
    )
    replay_pf_numeric = math.inf if replay_pf_raw == "inf" else _coerce_float(replay_pf_raw)
    realtime_expectancy = _coerce_float(realtime_status.get("expectancy_after_cost_bps"))
    replay_comparison_blockers: list[str] = []
    if replay_expectancy is None or replay_expectancy <= 0.0:
        replay_comparison_blockers.append("MISSING_POSITIVE_REPLAY_PROJECTION")
    elif realtime_expectancy is None:
        replay_comparison_blockers.append("MISSING_REALTIME_EXPECTANCY_FOR_REPLAY_COMPARISON")
    elif realtime_expectancy < replay_expectancy * OUT_OF_SAMPLE_REALTIME_REPLAY_EXPECTANCY_MIN_RATIO:
        replay_comparison_blockers.append("REALTIME_EXPECTANCY_MISSES_REPLAY_PROJECTION_TOLERANCE")
    safety_blockers = []
    if not (
        operator_safety.get("paper_only") is True
        and operator_safety.get("places_real_order") is False
        and operator_safety.get("test_orders") is False
        and operator_safety.get("leverage_mutation") is False
        and operator_safety.get("margin_mode_mutation") is False
        and operator_safety.get("live_gate") == LIVE_GATE
    ):
        safety_blockers.append("LIVE_OR_EXCHANGE_MUTATION_NOT_FAIL_CLOSED")
    blockers: list[str] = []
    if holdout_status.get("status") != "PASSED":
        blockers.append("HOLDOUT_REVERIFY_NOT_PASSED")
    if realtime_status.get("status") != "PASSED":
        blockers.append("REALTIME_PAPER_REVERIFY_NOT_PASSED")
    blockers.extend(replay_comparison_blockers)
    blockers.extend(safety_blockers)
    holdout_passed = holdout_status.get("status") == "PASSED"
    realtime_passed = realtime_status.get("status") == "PASSED"
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": OUT_OF_SAMPLE_REVERIFY_GATE_ID,
        "parent_goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": "PASSED" if not blockers else "NO_GO_OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY_INCOMPLETE",
        "blocker_reasons": blockers,
        "honest_interpretation": {
            "adaptive_capital_replay_gate": "PASS",
            "broad_model_edge": "NOT_PROVEN",
            "out_of_sample_generalization": "PROVEN" if holdout_passed else "NOT_PROVEN",
            "one_thousand_x_trajectory": "NOT_PROVEN",
            "live_readiness": LIVE_GATE,
            "live_grade_profitability": "PROVEN_ON_PAPER_ONLY" if holdout_passed and realtime_passed and not replay_comparison_blockers else "NOT_PROVEN",
        },
        "prior_replay_evidence_context": {
            "selected_a_grade_subset_candidate_count": accelerated_replay_status.get("validated_replay_candidate_count"),
            "selected_a_grade_subset_symbol_count": accelerated_replay_status.get("validated_replay_symbol_count"),
            "selected_a_grade_subset_expectancy_after_cost_bps": replay_expectancy,
            "selected_a_grade_subset_profit_factor": replay_pf_raw,
            "unfiltered_universe_replay_is_not_used_as_live_grade_pass": True,
            "selection_bias_risk_requires_frozen_selector_holdout": True,
        },
        "frozen_policy_manifest": frozen_manifest,
        "holdout_reverify_status": holdout_status,
        "realtime_paper_reverify_status": realtime_status,
        "realtime_vs_replay_projection_status": {
            "status": "PASSED" if not replay_comparison_blockers else "NO_GO_REPLAY_REALTIME_COMPARISON_INCOMPLETE",
            "blocker_reasons": replay_comparison_blockers,
            "projection_source": "validated_dynamic_a_grade_replay_subset",
            "replay_expectancy_after_cost_bps": replay_expectancy,
            "replay_profit_factor": replay_pf_raw,
            "replay_profit_factor_numeric": (
                "inf" if replay_pf_numeric == math.inf else round(replay_pf_numeric, 8)
                if replay_pf_numeric is not None else None
            ),
            "realtime_expectancy_after_cost_bps": realtime_expectancy,
            "minimum_realtime_to_replay_expectancy_ratio": OUT_OF_SAMPLE_REALTIME_REPLAY_EXPECTANCY_MIN_RATIO,
        },
        "required_evidence": {
            "untouched_holdout_a_grade_outcomes": OUT_OF_SAMPLE_MIN_HOLDOUT_OUTCOMES,
            "new_realtime_a_grade_closed_paper_outcomes": OUT_OF_SAMPLE_MIN_REALTIME_CLOSED_OUTCOMES,
            "minimum_symbols": OUT_OF_SAMPLE_MIN_SYMBOL_COUNT,
            "both_long_and_short": True,
            "positive_after_cost_expectancy": True,
            "minimum_profit_factor": OUT_OF_SAMPLE_MIN_PROFIT_FACTOR,
            "bounded_worst_1pct_loss_bps": OUT_OF_SAMPLE_MAX_WORST_1PCT_LOSS_BPS,
            "no_accounting_mismatches": True,
            "no_symbol_regime_timeframe_strategy_concentration": True,
        },
        "operator_safety": {
            "paper_only": True,
            "places_real_order": False,
            "test_orders": False,
            "leverage_mutation": False,
            "margin_mode_mutation": False,
            "live_gate": LIVE_GATE,
        },
    }


def _accelerated_replay_invalid_label_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    symbol = _normalized_symbol(row)
    timeframe = str(_row_value(row, "timeframe") or row.get("timeframe") or "")
    side = _directional_side(row)
    outcome_bps = _outcome_after_cost_bps(row)
    pnl = _trade_outcome_pnl(row)
    has_economic_label = outcome_bps is not None or pnl is not None
    if symbol == "UNKNOWN":
        reasons.append("MISSING_SYMBOL")
    if not timeframe or timeframe == "UNKNOWN":
        reasons.append("MISSING_TIMEFRAME")
    if side not in {"long", "short"}:
        reasons.append("NON_DIRECTIONAL_SIDE")
    if not has_economic_label:
        reasons.append("MISSING_AFTER_COST_OUTCOME_LABEL")
    if not _closed_flag_confirmed(row, source_key=str(row.get("source_redis_key") or "")):
        reasons.append("UNFINISHED_CANDLE")
    reasons.extend(_pre_submit_temporal_reasons(row))
    return sorted(set(reasons))


def _accelerated_replay_label_audit(evaluated_rows: list[dict[str, Any]]) -> dict[str, Any]:
    deduped: dict[str, dict[str, Any]] = {}
    for row in evaluated_rows:
        if isinstance(row, dict):
            deduped.setdefault(_row_identity(row), row)

    source_rows = list(deduped.values())
    economic_label_count = 0
    valid_rows: list[dict[str, Any]] = []
    after_cost_bps_values: list[float] = []
    pnl_values: list[float] = []
    invalid_reason_counts: dict[str, int] = {}
    invalid_samples: list[dict[str, Any]] = []
    latest_event_ms: int | None = None

    for row in source_rows:
        symbol = _normalized_symbol(row)
        timeframe = str(_row_value(row, "timeframe") or row.get("timeframe") or "")
        side = _directional_side(row)
        outcome_bps = _outcome_after_cost_bps(row)
        pnl = _trade_outcome_pnl(row)
        has_economic_label = outcome_bps is not None or pnl is not None
        if has_economic_label:
            economic_label_count += 1
        reasons = _accelerated_replay_invalid_label_reasons(row)

        if reasons:
            for reason in reasons:
                invalid_reason_counts[reason] = invalid_reason_counts.get(reason, 0) + 1
            if len(invalid_samples) < 20:
                invalid_samples.append({
                    "symbol": symbol,
                    "timeframe": timeframe or None,
                    "side": side or None,
                    "source_kind": _counterfactual_source_kind(row),
                    "event_time": _iso_from_ms(_event_time_ms(row)),
                    "reasons": reasons,
                })
            continue

        valid_rows.append(row)
        event_ms = _event_time_ms(row)
        if event_ms is not None:
            latest_event_ms = max(latest_event_ms or event_ms, event_ms)
        if outcome_bps is not None:
            after_cost_bps_values.append(outcome_bps)
        if pnl is not None:
            pnl_values.append(pnl)

    valid_symbols = sorted({_normalized_symbol(row) for row in valid_rows if _normalized_symbol(row) != "UNKNOWN"})
    valid_timeframes = sorted({
        str(_row_value(row, "timeframe") or row.get("timeframe"))
        for row in valid_rows
        if _row_value(row, "timeframe") or row.get("timeframe")
    })
    side_counts: dict[str, int] = {}
    strategy_counts: dict[str, int] = {}
    regime_counts: dict[str, int] = {}
    source_kind_counts: dict[str, int] = {}
    for row in valid_rows:
        side = _directional_side(row)
        if side in {"long", "short"}:
            side_counts[side] = side_counts.get(side, 0) + 1
        strategy = _row_strategy(row)
        strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
        regime = _market_regime_bucket(row)
        regime_counts[regime] = regime_counts.get(regime, 0) + 1
        source_kind = _counterfactual_source_kind(row)
        source_kind_counts[source_kind] = source_kind_counts.get(source_kind, 0) + 1

    metric_values = after_cost_bps_values if after_cost_bps_values else pnl_values
    gross_profit = sum(value for value in metric_values if value > 0.0)
    gross_loss = abs(sum(value for value in metric_values if value < 0.0))
    expectancy_after_cost_bps = (
        sum(after_cost_bps_values) / len(after_cost_bps_values)
        if after_cost_bps_values else None
    )
    average_pnl_usd = sum(pnl_values) / len(pnl_values) if pnl_values else None
    replay_expectancy_positive = (
        expectancy_after_cost_bps is not None and expectancy_after_cost_bps > 0.0
    ) or (
        expectancy_after_cost_bps is None and average_pnl_usd is not None and average_pnl_usd > 0.0
    )
    simulation_coverage = _accelerated_replay_simulation_accounting_coverage(valid_rows)
    return {
        "source_row_count": len(source_rows),
        "deduplication_policy": "row_identity_first_seen",
        "economic_outcome_label_count": economic_label_count,
        "event_time_valid_label_count": len(valid_rows),
        "invalid_label_row_count": len(source_rows) - len(valid_rows),
        "invalid_label_reason_counts": {
            key: invalid_reason_counts[key]
            for key in sorted(invalid_reason_counts)
        },
        "invalid_label_sample": invalid_samples,
        "symbol_count": len(valid_symbols),
        "symbols_sample": valid_symbols[:100],
        "timeframes": valid_timeframes,
        "side_counts": {key: side_counts[key] for key in sorted(side_counts)},
        "strategy_family_counts": {key: strategy_counts[key] for key in sorted(strategy_counts)},
        "market_regime_counts": {key: regime_counts[key] for key in sorted(regime_counts)},
        "source_kind_counts": {key: source_kind_counts[key] for key in sorted(source_kind_counts)},
        "after_cost_bps_label_count": len(after_cost_bps_values),
        "pnl_usd_label_count": len(pnl_values),
        "expectancy_after_cost_bps": (
            round(expectancy_after_cost_bps, 8)
            if expectancy_after_cost_bps is not None
            else None
        ),
        "average_pnl_usd": round(average_pnl_usd, 8) if average_pnl_usd is not None else None,
        "net_pnl_usd": round(sum(pnl_values), 8) if pnl_values else None,
        "profit_factor": (
            round(gross_profit / gross_loss, 8)
            if gross_loss > 0.0 else "inf" if gross_profit > 0.0 else None
        ),
        "replay_expectancy_positive": replay_expectancy_positive,
        "latest_event_time": _iso_from_ms(latest_event_ms),
        "simulation_accounting_coverage_status": simulation_coverage,
        "valid_label_sample": [
            {
                "symbol": _normalized_symbol(row),
                "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
                "side": _directional_side(row),
                "source_kind": _counterfactual_source_kind(row),
                "event_time": _iso_from_ms(_event_time_ms(row)),
                "outcome_after_cost_bps": _outcome_after_cost_bps(row),
                "pnl_usd": _trade_outcome_pnl(row),
            }
            for row in valid_rows[:20]
        ],
    }


def _metric_summary_for_replay_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    after_cost_bps_values = [
        value for row in rows
        for value in [_outcome_after_cost_bps(row)]
        if value is not None
    ]
    pnl_values = [
        value for row in rows
        for value in [_trade_outcome_pnl(row)]
        if value is not None
    ]
    metric_values = after_cost_bps_values if after_cost_bps_values else pnl_values
    gross_profit = sum(value for value in metric_values if value > 0.0)
    gross_loss = abs(sum(value for value in metric_values if value < 0.0))
    expectancy_after_cost_bps = (
        sum(after_cost_bps_values) / len(after_cost_bps_values)
        if after_cost_bps_values else None
    )
    average_pnl_usd = sum(pnl_values) / len(pnl_values) if pnl_values else None
    replay_expectancy_positive = (
        expectancy_after_cost_bps is not None and expectancy_after_cost_bps > 0.0
    ) or (
        expectancy_after_cost_bps is None and average_pnl_usd is not None and average_pnl_usd > 0.0
    )
    return {
        "row_count": len(rows),
        "after_cost_bps_label_count": len(after_cost_bps_values),
        "pnl_usd_label_count": len(pnl_values),
        "expectancy_after_cost_bps": (
            round(expectancy_after_cost_bps, 8)
            if expectancy_after_cost_bps is not None
            else None
        ),
        "average_pnl_usd": round(average_pnl_usd, 8) if average_pnl_usd is not None else None,
        "net_pnl_usd": round(sum(pnl_values), 8) if pnl_values else None,
        "profit_factor": (
            round(gross_profit / gross_loss, 8)
            if gross_loss > 0.0 else "inf" if gross_profit > 0.0 else None
        ),
        "replay_expectancy_positive": replay_expectancy_positive,
        "winning_label_count": sum(1 for value in metric_values if value > 0.0),
        "losing_label_count": sum(1 for value in metric_values if value < 0.0),
    }


def _eligible_bucket_keys_from_matrix(
    a_grade_bucket_performance_matrix: dict[str, Any] | None,
) -> set[tuple[str, str, str, str, str, str, str, str, str]]:
    matrix = a_grade_bucket_performance_matrix or {}
    keys: set[tuple[str, str, str, str, str, str, str, str, str]] = set()
    for row in matrix.get("buckets") or []:
        if not isinstance(row, dict) or row.get("dynamic_a_grade_eligible") is not True:
            continue
        keys.add(tuple(str(row.get(field)) for field in (
            "strategy",
            "side",
            "symbol_cluster",
            "timeframe",
            "market_regime",
            "volatility_bucket",
            "liquidity_bucket",
            "confidence_bucket",
            "expected_move_bucket",
        )))
    return keys


def _dynamic_validated_replay_deployment_audit(
    evaluated_rows: list[dict[str, Any]],
    *,
    a_grade_bucket_performance_matrix: dict[str, Any] | None,
) -> dict[str, Any]:
    eligible_bucket_keys = _eligible_bucket_keys_from_matrix(a_grade_bucket_performance_matrix)
    deduped: dict[str, dict[str, Any]] = {}
    for row in evaluated_rows:
        if isinstance(row, dict):
            deduped.setdefault(_row_identity(row), row)
    valid_rows = [
        row for row in deduped.values()
        if not _accelerated_replay_invalid_label_reasons(row)
    ]
    deployment_rows: list[dict[str, Any]] = []
    rejected_reason_counts: dict[str, int] = {}
    rejected_sample: list[dict[str, Any]] = []
    for row in valid_rows:
        reasons: list[str] = []
        key = tuple(str(value) for value in _a_grade_bucket_key(row))
        edge = _expected_edge_bps(row)
        side = _directional_side(row)
        if key not in eligible_bucket_keys:
            reasons.append("DYNAMIC_BUCKET_NOT_A_GRADE_ELIGIBLE")
        if edge is None or edge <= 0.0:
            reasons.append("NON_POSITIVE_EXPECTED_AFTER_COST_EDGE")
        if side not in {"long", "short"}:
            reasons.append("NON_DIRECTIONAL_SIDE")
        if _allocator_decision(row).startswith("BLOCK_"):
            reasons.append("ALLOCATOR_BLOCKED_CANDIDATE")
        if reasons:
            for reason in sorted(set(reasons)):
                rejected_reason_counts[reason] = rejected_reason_counts.get(reason, 0) + 1
            if len(rejected_sample) < 20:
                rejected_sample.append({
                    "symbol": _normalized_symbol(row),
                    "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
                    "side": side,
                    "source_kind": _counterfactual_source_kind(row),
                    "after_cost_edge_bps": edge,
                    "outcome_after_cost_bps": _outcome_after_cost_bps(row),
                    "bucket_key": list(key),
                    "reasons": sorted(set(reasons)),
                })
            continue
        deployment_rows.append(row)

    summary = _metric_summary_for_replay_rows(deployment_rows)
    profit_factor_value = summary["profit_factor"]
    profit_factor_numeric = (
        float("inf") if profit_factor_value == "inf"
        else _coerce_float(profit_factor_value)
    )
    blockers: list[str] = []
    if not eligible_bucket_keys:
        blockers.append("NO_DYNAMIC_A_GRADE_ELIGIBLE_BUCKETS")
    if not deployment_rows:
        blockers.append("NO_DYNAMIC_A_GRADE_REPLAY_DEPLOYMENT_CANDIDATES")
    if summary["replay_expectancy_positive"] is not True:
        blockers.append("NON_POSITIVE_VALIDATED_REPLAY_EXPECTANCY")
    if profit_factor_numeric is None or profit_factor_numeric < MINIMUM_POST_ALLOCATOR_PROFIT_FACTOR:
        blockers.append("VALIDATED_REPLAY_PROFIT_FACTOR_BELOW_MINIMUM")

    side_counts: dict[str, int] = {}
    strategy_counts: dict[str, int] = {}
    regime_counts: dict[str, int] = {}
    source_kind_counts: dict[str, int] = {}
    for row in deployment_rows:
        side = _directional_side(row)
        if side in {"long", "short"}:
            side_counts[side] = side_counts.get(side, 0) + 1
        strategy = _row_strategy(row)
        strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1
        regime = _market_regime_bucket(row)
        regime_counts[regime] = regime_counts.get(regime, 0) + 1
        source_kind = _counterfactual_source_kind(row)
        source_kind_counts[source_kind] = source_kind_counts.get(source_kind, 0) + 1
    symbols = sorted({_normalized_symbol(row) for row in deployment_rows if _normalized_symbol(row) != "UNKNOWN"})
    timeframes = sorted({
        str(_row_value(row, "timeframe") or row.get("timeframe"))
        for row in deployment_rows
        if _row_value(row, "timeframe") or row.get("timeframe")
    })
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "phase_id": STOP_WAITING_PHASE_ID,
        "status": "PASSED" if not blockers else "BLOCKED_DYNAMIC_VALIDATED_REPLAY_DEPLOYMENT",
        "blocker_reasons": blockers,
        "gate_scope": "dynamic_a_grade_execution_paper_replay_candidates",
        "raw_universe_replay_rows_count_as_coverage_not_expectancy_gate": True,
        "eligible_bucket_count": len(eligible_bucket_keys),
        "event_time_valid_replay_row_count": len(valid_rows),
        "validated_replay_deployment_candidate_count": len(deployment_rows),
        "validated_replay_symbol_count": len(symbols),
        "validated_replay_symbols_sample": symbols[:100],
        "validated_replay_timeframes": timeframes,
        "validated_replay_side_counts": {key: side_counts[key] for key in sorted(side_counts)},
        "validated_replay_strategy_family_counts": {
            key: strategy_counts[key] for key in sorted(strategy_counts)
        },
        "validated_replay_market_regime_counts": {
            key: regime_counts[key] for key in sorted(regime_counts)
        },
        "validated_replay_source_kind_counts": {
            key: source_kind_counts[key] for key in sorted(source_kind_counts)
        },
        **summary,
        "minimum_profit_factor": MINIMUM_POST_ALLOCATOR_PROFIT_FACTOR,
        "rejected_reason_counts": {
            key: rejected_reason_counts[key]
            for key in sorted(rejected_reason_counts)
        },
        "rejected_sample": rejected_sample,
        "validated_replay_sample": [
            {
                "symbol": _normalized_symbol(row),
                "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
                "side": _directional_side(row),
                "source_kind": _counterfactual_source_kind(row),
                "after_cost_edge_bps": _expected_edge_bps(row),
                "outcome_after_cost_bps": _outcome_after_cost_bps(row),
                "pnl_usd": _trade_outcome_pnl(row),
                "bucket_key": list(_a_grade_bucket_key(row)),
                "paper_only": True,
                "places_real_order": False,
            }
            for row in deployment_rows[:20]
        ],
        "paper_only": True,
        "places_real_order": False,
        "live_gate": LIVE_GATE,
    }


def _accelerated_counterfactual_replay_status(
    *,
    sweep: dict[str, Any],
    counterfactual_rows: list[dict[str, Any]],
    evaluated_rows: list[dict[str, Any]],
    a_grade_bucket_performance_matrix: dict[str, Any] | None = None,
    post_hoc_replay_audit: dict[str, Any] | None = None,
    post_hoc_replay_label_rows: list[dict[str, Any]] | None = None,
    native_trainer_replay_audit: dict[str, Any] | None = None,
    native_trainer_replay_label_rows: list[dict[str, Any]] | None = None,
    closed_candle_replay_audit: dict[str, Any] | None = None,
    closed_candle_replay_label_rows: list[dict[str, Any]] | None = None,
    generated_utc: str,
) -> dict[str, Any]:
    post_hoc_replay_audit = post_hoc_replay_audit or {}
    post_hoc_replay_label_rows = [
        dict(row) for row in (post_hoc_replay_label_rows or [])
        if isinstance(row, dict)
    ]
    native_trainer_replay_audit = native_trainer_replay_audit or {}
    native_trainer_replay_label_rows = [
        dict(row) for row in (native_trainer_replay_label_rows or [])
        if isinstance(row, dict)
    ]
    closed_candle_replay_audit = closed_candle_replay_audit or {}
    closed_candle_replay_label_rows = [
        dict(row) for row in (closed_candle_replay_label_rows or [])
        if isinstance(row, dict)
    ]
    audited_replay_label_rows = [
        *post_hoc_replay_label_rows,
        *native_trainer_replay_label_rows,
        *closed_candle_replay_label_rows,
    ]
    combined_evaluated_rows = (
        audited_replay_label_rows
        if audited_replay_label_rows
        else evaluated_rows
    )
    label_audit = _accelerated_replay_label_audit(combined_evaluated_rows)
    validated_deployment_audit = _dynamic_validated_replay_deployment_audit(
        combined_evaluated_rows,
        a_grade_bucket_performance_matrix=a_grade_bucket_performance_matrix,
    )
    symbols = label_audit["symbols_sample"]
    timeframes = label_audit["timeframes"]
    side_counts = label_audit["side_counts"]
    replayed = int(label_audit["event_time_valid_label_count"] or 0)
    symbol_count = int(label_audit["symbol_count"] or 0)
    strict_sweep_replayed = int(sweep.get("sweep_result_count") or 0)
    strict_sweep_event_time_valid = int(sweep.get("event_time_valid_candidate_count") or 0)
    simulation_coverage = label_audit["simulation_accounting_coverage_status"]
    blockers: list[str] = []
    if replayed < ACCELERATED_REPLAY_MIN_ECONOMIC_OUTCOMES:
        blockers.append("INSUFFICIENT_EVENT_TIME_VALID_REPLAY_OUTCOMES")
    if symbol_count < ACCELERATED_REPLAY_MIN_SYMBOLS:
        blockers.append("INSUFFICIENT_REPLAY_SYMBOL_DIVERSITY")
    for timeframe in SIGNAL_ACCURACY_TIMEFRAMES:
        if timeframe not in set(timeframes):
            blockers.append("MISSING_REQUIRED_TIMEFRAME_COVERAGE")
            break
    if side_counts.get("long", 0) <= 0 or side_counts.get("short", 0) <= 0:
        blockers.append("MISSING_LONG_SHORT_REPLAY_COVERAGE")
    if validated_deployment_audit.get("status") != "PASSED":
        blockers.append("VALIDATED_REPLAY_DEPLOYMENT_EXPECTANCY_NOT_PROVEN")
    if simulation_coverage.get("status") != "PASSED":
        blockers.append("INCOMPLETE_SIMULATION_ACCOUNTING_COVERAGE")
    if int(sweep.get("best_configuration_count") or 0) <= 0:
        blockers.append("NO_FEASIBLE_COUNTERFACTUAL_BEST_CONFIGURATIONS")
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "phase_id": STOP_WAITING_PHASE_ID,
        "generated_utc": generated_utc,
        "status": "PASSED" if not blockers else "BLOCKED_ACCELERATED_REPLAY_EVIDENCE_INSUFFICIENT",
        "blocker_reasons": list(dict.fromkeys(blockers)),
        "accelerated_replay_source": (
            "event_time_valid_evaluated_outcome_labels_plus_audited_post_hoc_replay_labels_"
            "plus_audited_native_trainer_replay_dataset_labels_plus_audited_closed_candle_replay_"
            "labels_plus_strict_counterfactual_sweep"
        ),
        "counterfactual_source_row_count": len(counterfactual_rows),
        "runtime_evaluated_outcome_source_row_count": len(evaluated_rows),
        "runtime_evaluated_outcomes_included_in_replay_gate": not bool(audited_replay_label_rows),
        "audited_replay_source_row_count_for_replay_gate": len(audited_replay_label_rows),
        "post_hoc_replay_event_time_valid_label_count": len(post_hoc_replay_label_rows),
        "post_hoc_replay_source_row_count": post_hoc_replay_audit.get("bundle_row_count", 0),
        "post_hoc_replay_complete_primary_outcome_count": (
            post_hoc_replay_audit.get("complete_primary_outcome_count", 0)
        ),
        "post_hoc_replay_bundle_audit": post_hoc_replay_audit,
        "native_trainer_replay_event_time_valid_label_count": len(
            native_trainer_replay_label_rows
        ),
        "native_trainer_replay_source_row_count": (
            native_trainer_replay_audit.get("source_row_count", 0)
        ),
        "native_trainer_replay_complete_outcome_count": (
            native_trainer_replay_audit.get("complete_after_cost_outcome_count", 0)
        ),
        "native_trainer_replay_evidence_audit": native_trainer_replay_audit,
        "closed_candle_replay_event_time_valid_label_count": len(
            closed_candle_replay_label_rows
        ),
        "closed_candle_replay_source_row_count": (
            closed_candle_replay_audit.get("source_row_count", 0)
        ),
        "closed_candle_replay_complete_outcome_count": (
            closed_candle_replay_audit.get("complete_after_cost_outcome_count", 0)
        ),
        "closed_candle_replay_evidence_audit": closed_candle_replay_audit,
        "evaluated_outcome_source_row_count": label_audit["source_row_count"],
        "minimum_replayed_economic_candidate_count": ACCELERATED_REPLAY_MIN_ECONOMIC_OUTCOMES,
        "replayed_economic_candidate_count": replayed,
        "event_time_valid_candidate_count": replayed,
        "labelled_economic_replay_outcome_count": label_audit["economic_outcome_label_count"],
        "event_time_valid_label_count": label_audit["event_time_valid_label_count"],
        "strict_sweep_replayed_economic_candidate_count": strict_sweep_replayed,
        "strict_sweep_event_time_valid_candidate_count": strict_sweep_event_time_valid,
        "strict_sweep_best_configuration_count": int(sweep.get("best_configuration_count") or 0),
        "minimum_symbol_count": ACCELERATED_REPLAY_MIN_SYMBOLS,
        "symbol_count": symbol_count,
        "symbols_sample": symbols,
        "required_timeframes": list(SIGNAL_ACCURACY_TIMEFRAMES),
        "observed_timeframes": timeframes,
        "side_counts": side_counts,
        "strategy_family_counts": label_audit["strategy_family_counts"],
        "market_regime_counts": label_audit["market_regime_counts"],
        "source_kind_counts": label_audit["source_kind_counts"],
        "replay_expectancy_gate_scope": "dynamic_a_grade_execution_paper_validated_replay_candidates",
        "expectancy_scope": "dynamic_a_grade_execution_paper_validated_replay_candidates",
        "expectancy_after_cost_bps": validated_deployment_audit["expectancy_after_cost_bps"],
        "average_pnl_usd": validated_deployment_audit["average_pnl_usd"],
        "net_pnl_usd": validated_deployment_audit["net_pnl_usd"],
        "profit_factor": validated_deployment_audit["profit_factor"],
        "replay_expectancy_positive": validated_deployment_audit["replay_expectancy_positive"],
        "validated_replay_candidate_count": (
            validated_deployment_audit["validated_replay_deployment_candidate_count"]
        ),
        "validated_replay_symbol_count": validated_deployment_audit["validated_replay_symbol_count"],
        "validated_replay_expectancy_after_cost_bps": validated_deployment_audit["expectancy_after_cost_bps"],
        "validated_replay_average_pnl_usd": validated_deployment_audit["average_pnl_usd"],
        "validated_replay_net_pnl_usd": validated_deployment_audit["net_pnl_usd"],
        "validated_replay_profit_factor": validated_deployment_audit["profit_factor"],
        "validated_replay_deployment_status": validated_deployment_audit,
        "unfiltered_replay_expectancy_scope": "all_event_time_valid_replay_rows_for_coverage_and_calibration",
        "unfiltered_replay_expectancy_after_cost_bps": label_audit["expectancy_after_cost_bps"],
        "unfiltered_replay_average_pnl_usd": label_audit["average_pnl_usd"],
        "unfiltered_replay_net_pnl_usd": label_audit["net_pnl_usd"],
        "unfiltered_replay_profit_factor": label_audit["profit_factor"],
        "unfiltered_replay_expectancy_positive": label_audit["replay_expectancy_positive"],
        "invalid_label_row_count": label_audit["invalid_label_row_count"],
        "invalid_label_reason_counts": label_audit["invalid_label_reason_counts"],
        "invalid_label_sample": label_audit["invalid_label_sample"],
        "simulation_accounting_coverage_status": simulation_coverage,
        "valid_label_sample": label_audit["valid_label_sample"],
        "closed_candles_only_required": True,
        "feature_cutoff_lte_decision_time_required": True,
        "available_at_lte_decision_time_required": True,
        "future_data_labels_only": True,
        "does_not_wait_for_300_realtime_closes": True,
        "paper_only": True,
        "places_real_order": False,
    }


def _qualified_replay_policy_evidence_status(
    *,
    accelerated_replay_status: dict[str, Any],
    sweep: dict[str, Any],
    realtime_closed_outcome_count: int,
    realtime_symbol_count: int,
    realtime_long_count: int,
    realtime_short_count: int,
) -> dict[str, Any]:
    deployment = (
        accelerated_replay_status.get("validated_replay_deployment_status")
        if isinstance(accelerated_replay_status.get("validated_replay_deployment_status"), dict)
        else {}
    )
    simulation_coverage = (
        accelerated_replay_status.get("simulation_accounting_coverage_status")
        if isinstance(accelerated_replay_status.get("simulation_accounting_coverage_status"), dict)
        else {}
    )
    event_time_valid_count = int(
        accelerated_replay_status.get("event_time_valid_candidate_count")
        or accelerated_replay_status.get("event_time_valid_label_count")
        or 0
    )
    replayed_economic_count = int(
        accelerated_replay_status.get("replayed_economic_candidate_count")
        or event_time_valid_count
        or 0
    )
    qualified_replay_outcome_count = max(event_time_valid_count, replayed_economic_count)
    validated_candidate_count = int(
        accelerated_replay_status.get("validated_replay_candidate_count")
        or deployment.get("validated_replay_deployment_candidate_count")
        or 0
    )
    validated_symbol_count = int(
        accelerated_replay_status.get("validated_replay_symbol_count")
        or deployment.get("validated_replay_symbol_count")
        or 0
    )
    replay_symbol_count = int(accelerated_replay_status.get("symbol_count") or 0)
    effective_replay_symbol_count = max(replay_symbol_count, validated_symbol_count)
    replay_timeframes = sorted(set(
        str(value)
        for value in (accelerated_replay_status.get("observed_timeframes") or [])
        if str(value)
    ))
    validated_timeframes = sorted(set(
        str(value)
        for value in (
            deployment.get("validated_replay_timeframes")
            or accelerated_replay_status.get("observed_timeframes")
            or []
        )
        if str(value)
    ))
    coverage_timeframes = replay_timeframes or validated_timeframes
    replay_side_counts = (
        accelerated_replay_status.get("side_counts")
        if isinstance(accelerated_replay_status.get("side_counts"), dict)
        else {}
    )
    validated_side_counts = (
        deployment.get("validated_replay_side_counts")
        if isinstance(deployment.get("validated_replay_side_counts"), dict)
        else {}
    )
    coverage_side_counts = replay_side_counts or validated_side_counts
    replay_strategy_counts = (
        accelerated_replay_status.get("strategy_family_counts")
        if isinstance(accelerated_replay_status.get("strategy_family_counts"), dict)
        else {}
    )
    validated_strategy_counts = (
        deployment.get("validated_replay_strategy_family_counts")
        if isinstance(deployment.get("validated_replay_strategy_family_counts"), dict)
        else {}
    )
    coverage_strategy_counts = replay_strategy_counts or validated_strategy_counts
    replay_regime_counts = (
        accelerated_replay_status.get("market_regime_counts")
        if isinstance(accelerated_replay_status.get("market_regime_counts"), dict)
        else {}
    )
    validated_regime_counts = (
        deployment.get("validated_replay_market_regime_counts")
        if isinstance(deployment.get("validated_replay_market_regime_counts"), dict)
        else {}
    )
    coverage_regime_counts = replay_regime_counts or validated_regime_counts
    profit_factor_raw = _first_present(
        accelerated_replay_status.get("validated_replay_profit_factor"),
        deployment.get("profit_factor"),
    )
    profit_factor_numeric = (
        float("inf")
        if str(profit_factor_raw).lower() == "inf"
        else _coerce_float(profit_factor_raw)
    )
    expectancy_after_cost_bps = _coerce_float(_first_present(
        accelerated_replay_status.get("validated_replay_expectancy_after_cost_bps"),
        deployment.get("expectancy_after_cost_bps"),
    ))
    blockers: list[str] = []
    minimum_qualified_replay_outcomes = max(
        MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES,
        ACCELERATED_REPLAY_MIN_ECONOMIC_OUTCOMES,
    )
    if accelerated_replay_status.get("status") != "PASSED":
        blockers.append("ACCELERATED_REPLAY_STATUS_NOT_PASSED")
    if deployment.get("status") != "PASSED":
        blockers.append("VALIDATED_REPLAY_DEPLOYMENT_STATUS_NOT_PASSED")
    if qualified_replay_outcome_count < minimum_qualified_replay_outcomes:
        blockers.append("INSUFFICIENT_EVENT_TIME_VALID_REPLAY_OUTCOMES_FOR_POLICY")
    if validated_candidate_count <= 0:
        blockers.append("NO_VALIDATED_REPLAY_DEPLOYMENT_CANDIDATES")
    if effective_replay_symbol_count < MINIMUM_POLICY_SYMBOL_COUNT:
        blockers.append("INSUFFICIENT_REPLAY_SYMBOL_DIVERSITY_FOR_POLICY")
    if not set(SIGNAL_ACCURACY_TIMEFRAMES).issubset(set(coverage_timeframes)):
        blockers.append("MISSING_REPLAY_TIMEFRAME_COVERAGE_FOR_POLICY")
    if int(coverage_side_counts.get("long") or 0) <= 0:
        blockers.append("MISSING_REPLAY_LONG_EVIDENCE")
    if int(coverage_side_counts.get("short") or 0) <= 0:
        blockers.append("MISSING_REPLAY_SHORT_EVIDENCE")
    if not coverage_strategy_counts:
        blockers.append("MISSING_REPLAY_STRATEGY_FAMILY_EVIDENCE")
    if not coverage_regime_counts:
        blockers.append("MISSING_REPLAY_REGIME_EVIDENCE")
    if simulation_coverage.get("status") != "PASSED":
        blockers.append("INCOMPLETE_REPLAY_SIMULATION_ACCOUNTING_COVERAGE")
    if sweep.get("status") != "PASSED":
        blockers.append("COUNTERFACTUAL_SWEEP_NOT_PASSED_FOR_REPLAY_POLICY")
    if int(sweep.get("best_configuration_count") or 0) <= 0:
        blockers.append("NO_FEASIBLE_COUNTERFACTUAL_CONFIGURATIONS_FOR_REPLAY_POLICY")
    if expectancy_after_cost_bps is None or expectancy_after_cost_bps <= 0.0:
        blockers.append("NON_POSITIVE_VALIDATED_REPLAY_EXPECTANCY_FOR_POLICY")
    if profit_factor_numeric is None or profit_factor_numeric < MINIMUM_POST_ALLOCATOR_PROFIT_FACTOR:
        blockers.append("VALIDATED_REPLAY_PROFIT_FACTOR_BELOW_POLICY_MINIMUM")
    if accelerated_replay_status.get("paper_only") is not True:
        blockers.append("REPLAY_POLICY_EVIDENCE_NOT_MARKED_PAPER_ONLY")
    if accelerated_replay_status.get("places_real_order") is not False:
        blockers.append("REPLAY_POLICY_EVIDENCE_PLACES_REAL_ORDER")

    status = "PASSED" if not blockers else "NO_GO_QUALIFIED_REPLAY_POLICY_EVIDENCE_INSUFFICIENT"
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "phase_id": STOP_WAITING_PHASE_ID,
        "status": status,
        "blocker_reasons": blockers,
        "policy_evidence_basis": (
            "qualified_accelerated_replay"
            if status == "PASSED" else "realtime_post_policy_closed_outcomes"
        ),
        "counts_as_policy_evidence": status == "PASSED",
        "does_not_wait_for_300_realtime_closes": status == "PASSED",
        "realtime_closed_outcome_count": realtime_closed_outcome_count,
        "realtime_symbol_count": realtime_symbol_count,
        "realtime_long_count": realtime_long_count,
        "realtime_short_count": realtime_short_count,
        "minimum_realtime_closed_outcomes": MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES,
        "minimum_realtime_symbol_count": MINIMUM_POLICY_SYMBOL_COUNT,
        "minimum_qualified_replay_outcomes": minimum_qualified_replay_outcomes,
        "qualified_replay_outcome_count": qualified_replay_outcome_count,
        "replay_symbol_count": replay_symbol_count,
        "effective_replay_symbol_count": effective_replay_symbol_count,
        "replay_timeframe_count": len(replay_timeframes),
        "replay_timeframes": replay_timeframes,
        "replay_side_counts": {
            key: replay_side_counts[key] for key in sorted(replay_side_counts)
        },
        "replay_strategy_family_counts": {
            key: replay_strategy_counts[key] for key in sorted(replay_strategy_counts)
        },
        "replay_market_regime_counts": {
            key: replay_regime_counts[key] for key in sorted(replay_regime_counts)
        },
        "validated_replay_candidate_count": validated_candidate_count,
        "validated_replay_symbol_count": validated_symbol_count,
        "validated_replay_timeframe_count": len(validated_timeframes),
        "validated_replay_timeframes": validated_timeframes,
        "required_timeframes": list(SIGNAL_ACCURACY_TIMEFRAMES),
        "validated_replay_side_counts": {
            key: validated_side_counts[key] for key in sorted(validated_side_counts)
        },
        "validated_replay_strategy_family_counts": {
            key: validated_strategy_counts[key] for key in sorted(validated_strategy_counts)
        },
        "validated_replay_market_regime_counts": {
            key: validated_regime_counts[key] for key in sorted(validated_regime_counts)
        },
        "validated_replay_expectancy_after_cost_bps": (
            round(expectancy_after_cost_bps, 8)
            if expectancy_after_cost_bps is not None else None
        ),
        "validated_replay_profit_factor": profit_factor_raw,
        "minimum_profit_factor": MINIMUM_POST_ALLOCATOR_PROFIT_FACTOR,
        "counterfactual_sweep_status": sweep.get("status"),
        "counterfactual_best_configuration_count": int(sweep.get("best_configuration_count") or 0),
        "simulation_accounting_coverage_status": simulation_coverage,
        "effective_policy_outcome_count": (
            qualified_replay_outcome_count
            if status == "PASSED" else realtime_closed_outcome_count
        ),
        "effective_policy_symbol_count": (
            effective_replay_symbol_count if status == "PASSED" else realtime_symbol_count
        ),
        "effective_policy_long_count": (
            int(coverage_side_counts.get("long") or 0) if status == "PASSED" else realtime_long_count
        ),
        "effective_policy_short_count": (
            int(coverage_side_counts.get("short") or 0) if status == "PASSED" else realtime_short_count
        ),
        "paper_only": True,
        "places_real_order": False,
        "live_gate": LIVE_GATE,
    }


def _counterfactual_efficient_frontier_artifact(
    *,
    sweep: dict[str, Any],
    generated_utc: str,
) -> dict[str, Any]:
    best = sweep.get("best_configurations") or sweep.get("best_configurations_sample") or []
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "phase_id": STOP_WAITING_PHASE_ID,
        "generated_utc": generated_utc,
        "status": "PASSED" if sweep.get("efficient_frontier_ready") is True else "BLOCKED_EFFICIENT_FRONTIER_NOT_READY",
        "objective": "maximize_expected_log_final_equity",
        "efficient_frontier_ready": sweep.get("efficient_frontier_ready") is True,
        "best_configuration_count": int(sweep.get("best_configuration_count") or 0),
        "sweep_result_count": int(sweep.get("sweep_result_count") or 0),
        "total_expected_log_growth": sweep.get("total_expected_log_growth"),
        "worst_expected_shortfall_usd": sweep.get("worst_expected_shortfall_usd"),
        "max_liquidation_probability": sweep.get("max_liquidation_probability"),
        "config_space_audit": sweep.get("config_space_audit") or {},
        "hedge_accounting_audit": sweep.get("hedge_accounting_audit") or {},
        "best_configurations": best[:100],
        "paper_only": True,
        "places_real_order": False,
    }


def _field_present(row: dict[str, Any], field: str) -> bool:
    value = _row_value(row, field)
    if value is None or value == "":
        return False
    return True


def _missing_mandatory_fields(row: dict[str, Any]) -> list[str]:
    return [
        field for field in MANDATORY_PER_TRADE_FIELDS
        if not _field_present(row, field)
    ]


def _rows_with_complete_mandatory_fields(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if not _missing_mandatory_fields(row)]


def _lineage_ids(row: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for field in (
        "signal_id",
        "source_signal_id",
        "entry_signal_id",
        "fill_id",
        "ledger_row_id",
        "intent_id",
        "paper_intent_id",
        "paper_fill_intent_id",
        "prediction_id",
        "source_prediction_id",
        "entry_prediction_id",
    ):
        value = _first_present(row.get(field), _row_value(row, field))
        if value is not None and value != "":
            ids.add(str(value))
    source_fill_ids = row.get("source_fill_ids")
    if isinstance(source_fill_ids, list):
        ids.update(str(value) for value in source_fill_ids if value is not None and value != "")
    return ids


COUNTERFACTUAL_MARKET_COST_LINEAGE_FIELDS = (
    "actual_observed_spread_entry_bps",
    "expected_slippage_bps",
    "fee_bps",
    "expected_funding_bps",
    "orderbook_depth_usd",
)


def _feature_rows_by_symbol_timeframe(feature_rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    indexed: dict[tuple[str, str], dict[str, Any]] = {}
    for row in feature_rows:
        symbol = _normalized_symbol(row)
        timeframe = str(row.get("timeframe") or "")
        if symbol and timeframe:
            indexed[(symbol, timeframe)] = row
    return indexed


def _feature_rows_by_snapshot_id(feature_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in feature_rows:
        snapshot_id = row.get("feature_snapshot_id")
        if snapshot_id not in {None, ""}:
            indexed[str(snapshot_id)] = row
    return indexed


def _decision_feature_snapshot_id(row: dict[str, Any]) -> Any:
    lineage = row.get("lineage_ids") if isinstance(row.get("lineage_ids"), dict) else {}
    return _first_present(
        row.get("feature_snapshot_id"),
        row.get("entry_feature_snapshot_id"),
        row.get("prediction_feature_snapshot_id"),
        lineage.get("feature_snapshot_id"),
    )


def _matching_feature_payload(
    decision_row: dict[str, Any],
    *,
    features_by_snapshot_id: dict[str, dict[str, Any]],
    features_by_symbol_timeframe: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any] | None:
    snapshot_id = _decision_feature_snapshot_id(decision_row)
    if snapshot_id not in {None, ""}:
        feature = features_by_snapshot_id.get(str(snapshot_id))
        if feature is not None:
            return feature
    fallback = features_by_symbol_timeframe.get((
        _normalized_symbol(decision_row),
        str(decision_row.get("timeframe") or ""),
    ))
    if fallback is not None and snapshot_id not in {None, ""}:
        fallback = dict(fallback)
        fallback.setdefault("requested_feature_snapshot_id", str(snapshot_id))
        fallback.setdefault("exact_feature_snapshot_lookup_status", "MISSING_EXACT_FEATURE_SNAPSHOT_FALLBACK_TO_SYMBOL_TIMEFRAME")
    return fallback


FEATURE_MARKET_COST_CONTEXT_KEYS = (
    "features",
    "market_microstructure",
    "microstructure_context",
    "orderbook_context",
    "liquidity_context",
    "depth_context",
    "market_cost_evidence",
    "market_context",
    "execution_cost_context",
    "cost_context",
    "funding_context",
    "oi_funding_context",
    "fees_context",
    "model_inputs",
    "adaptive_allocation",
)


def _feature_time_payload(value: dict[str, Any]) -> dict[str, Any]:
    merged = dict(value)
    seen_context_ids: set[int] = set()

    def merge_known_contexts(context: dict[str, Any]) -> None:
        context_id = id(context)
        if context_id in seen_context_ids:
            return
        seen_context_ids.add(context_id)
        for key in FEATURE_MARKET_COST_CONTEXT_KEYS:
            nested = context.get(key)
            if not isinstance(nested, dict):
                continue
            merge_known_contexts(nested)
            for nested_key, nested_value in nested.items():
                merged.setdefault(nested_key, nested_value)

    merge_known_contexts(value)
    features = value.get("features")
    if isinstance(features, dict):
        merged.update(features)
    return merged


def _feature_payload_market_cost_reject_reasons(
    *,
    decision_row: dict[str, Any],
    feature_payload: dict[str, Any] | None,
) -> list[str]:
    if not isinstance(feature_payload, dict):
        return ["MISSING_FEATURE_PAYLOAD_FOR_MARKET_COST_EVIDENCE"]
    reasons: list[str] = []
    decision_snapshot_id = _decision_feature_snapshot_id(decision_row)
    feature_snapshot_id = feature_payload.get("feature_snapshot_id")
    requested_snapshot_id = feature_payload.get("requested_feature_snapshot_id")
    if requested_snapshot_id not in {None, ""} and str(requested_snapshot_id) != str(feature_snapshot_id or ""):
        reasons.append("MISSING_EXACT_FEATURE_SNAPSHOT_FOR_MARKET_COST_EVIDENCE")
    if (
        decision_snapshot_id not in {None, ""}
        and feature_snapshot_id not in {None, ""}
        and str(decision_snapshot_id) != str(feature_snapshot_id)
    ):
        reasons.append("FEATURE_SNAPSHOT_MISMATCH_FOR_MARKET_COST_EVIDENCE")
    decision_time = _parse_utc(_first_present(
        decision_row.get("decision_time"),
        decision_row.get("decision_time_est"),
        decision_row.get("available_at"),
        decision_row.get("generated_at"),
        decision_row.get("generated_utc"),
        decision_row.get("generated_est"),
    ))
    if decision_time is None:
        reasons.append("MISSING_DECISION_TIME_FOR_MARKET_COST_EVIDENCE")
    source_times = {
        "feature_available_at": _first_present(
            feature_payload.get("available_at"),
            feature_payload.get("feature_available_at"),
            feature_payload.get("source_available_time"),
        ),
        "feature_generated_at": _first_present(
            feature_payload.get("generated_at"),
            feature_payload.get("generated_utc"),
            feature_payload.get("feature_generated_at"),
        ),
        "feature_cutoff": _first_present(
            feature_payload.get("feature_cutoff"),
            feature_payload.get("source_event_time_est"),
            feature_payload.get("candle_close_time"),
        ),
    }
    if not source_times["feature_available_at"]:
        reasons.append("MISSING_FEATURE_AVAILABLE_AT_FOR_MARKET_COST_EVIDENCE")
    for label, value in source_times.items():
        if not value:
            continue
        parsed = _parse_utc(value)
        if parsed is None:
            reasons.append(f"UNPARSEABLE_{label.upper()}_FOR_MARKET_COST_EVIDENCE")
        elif decision_time is not None and parsed > decision_time:
            reasons.append(f"{label.upper()}_AFTER_DECISION_TIME")
    return reasons


def _set_market_cost_value(
    out: dict[str, Any],
    sources: dict[str, str],
    field: str,
    value: float | None,
    source: str | None,
    *,
    positive_only: bool = False,
) -> None:
    if field in out or value is None or source is None:
        return
    normalized = abs(value)
    if positive_only and normalized <= 0.0:
        return
    out[field] = normalized
    sources[field] = source


def _set_market_cost_rate_as_bps(
    out: dict[str, Any],
    sources: dict[str, str],
    field: str,
    rate: float | None,
    source: str | None,
) -> None:
    if rate is None or source is None:
        return
    _set_market_cost_value(out, sources, field, rate * 10000.0, source)


def _first_feature_numeric_field(
    feature_payload: dict[str, Any],
    fields: tuple[str, ...],
) -> tuple[float | None, str | None]:
    feature_values = _feature_time_payload(feature_payload)
    for field in fields:
        value = _coerce_float(feature_values.get(field))
        if value is not None:
            return value, field
    return None, None


def _feature_coinapi_book_depth_usd(
    *,
    decision_row: dict[str, Any],
    feature_payload: dict[str, Any],
) -> tuple[float | None, str | None]:
    feature_values = _feature_time_payload(feature_payload)

    def side_depth(
        quantity_fields: tuple[str, ...],
        price_fields: tuple[str, ...],
    ) -> tuple[float | None, str | None]:
        quantity, quantity_field = _first_feature_numeric_field(feature_payload, quantity_fields)
        if quantity is None or quantity <= 0.0 or not quantity_field:
            return None, None
        for price_field in price_fields:
            price = _coerce_float(feature_values.get(price_field))
            if price is not None and price > 0.0:
                return quantity * price, f"{quantity_field}*{price_field}"
        return None, None

    bid_depth, bid_source = side_depth(
        ("coinapi_book_bid_sum_5", "book_bid_sum_5"),
        ("coinapi_best_bid_px", "best_bid_px", "best_bid", "bid_px", "bid"),
    )
    ask_depth, ask_source = side_depth(
        ("coinapi_book_ask_sum_5", "book_ask_sum_5"),
        ("coinapi_best_ask_px", "best_ask_px", "best_ask", "ask_px", "ask"),
    )
    side = str(_first_present(decision_row.get("side"), decision_row.get("action"), "")).lower()
    if side in {"long", "buy"}:
        return ask_depth, ask_source
    if side in {"short", "sell"}:
        return bid_depth, bid_source
    return None, None


def _model_expected_slippage_bps(
    *,
    spread_bps: float,
    volatility_bps: float | None,
    liquidity_score: float | None,
) -> float:
    volatility_component = max(0.0, float(volatility_bps or 0.0)) * 0.015
    modeled = max(0.25, abs(spread_bps) * 0.50 + volatility_component)
    if liquidity_score is not None:
        if liquidity_score < 0.25:
            modeled *= 2.0
        elif liquidity_score < 0.50:
            modeled *= 1.4
    return round(min(50.0, modeled), 6)


def _feature_modeled_slippage_bps(
    feature_payload: dict[str, Any],
) -> tuple[float | None, str | None]:
    spread_bps, spread_field = _first_feature_numeric_field(
        feature_payload,
        (
            "actual_observed_spread_entry_bps",
            "bid_ask_spread_bps",
            "ob_spread_bps",
            "orderbook_spread_bps",
            "spread_bps",
        ),
    )
    if spread_bps is None or not spread_field:
        return None, None
    volatility_bps, volatility_field = _first_feature_numeric_field(
        feature_payload,
        (
            "volatility_bps",
            "micro_volatility_bps",
            "realized_volatility_bps",
            "atr_bps",
            "ATR_bps",
        ),
    )
    liquidity_score, liquidity_field = _first_feature_numeric_field(
        feature_payload,
        (
            "liquidity_score",
            "coingecko_liquidity_score",
            "defillama_liquidity_score",
        ),
    )
    source_fields = [spread_field]
    if volatility_field:
        source_fields.append(volatility_field)
    if liquidity_field:
        source_fields.append(liquidity_field)
    return (
        _model_expected_slippage_bps(
            spread_bps=spread_bps,
            volatility_bps=volatility_bps,
            liquidity_score=liquidity_score,
        ),
        f"MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY({','.join(source_fields)})",
    )


def _feature_market_cost_evidence_enrichment(
    *,
    decision_row: dict[str, Any],
    feature_payload: dict[str, Any] | None,
    feature_source_key: str | None,
) -> dict[str, Any]:
    reject_reasons = _feature_payload_market_cost_reject_reasons(
        decision_row=decision_row,
        feature_payload=feature_payload,
    )
    out: dict[str, Any] = {}
    sources: dict[str, str] = {}
    if not reject_reasons and isinstance(feature_payload, dict):
        source_prefix = feature_source_key or "v2:features:latest"
        for target, fields, positive_only in (
            (
                "actual_observed_spread_entry_bps",
                (
                    "actual_observed_spread_entry_bps",
                    "actual_spread_bps",
                    "entry_spread_bps",
                    "bid_ask_spread_bps",
                    "ob_spread_bps",
                    "orderbook_spread_bps",
                    "spread_bps",
                ),
                False,
            ),
            (
                "expected_slippage_bps",
                (
                    "expected_slippage_bps",
                    "actual_observed_slippage_bps",
                    "actual_slippage_bps",
                    "realized_slippage_bps",
                    "slippage_bps",
                    "estimated_slippage_bps",
                    "slippage_estimate_bps",
                ),
                False,
            ),
            (
                "fee_bps",
                (
                    "fee_bps",
                    "taker_fee_bps",
                    "expected_fee_bps",
                    "actual_fee_bps",
                    "estimated_fee_bps",
                    "fee_estimate_bps",
                    "commission_bps",
                ),
                False,
            ),
            (
                "expected_funding_bps",
                (
                    "expected_funding_bps",
                    "funding_bps",
                    "funding_rate_bps",
                    "actual_funding_bps",
                    "estimated_funding_bps",
                    "funding_estimate_bps",
                ),
                False,
            ),
            (
                "orderbook_depth_usd",
                (
                    "orderbook_depth_usd",
                    "entry_orderbook_depth_usd",
                    "market_depth_usd",
                    "depth_usd",
                    "depth_usdt",
                    "depth_notional_usd",
                    "depth_total_usd",
                    "available_depth_usd",
                    "one_percent_depth_usd",
                    "depth_1pct_usd",
                    "depth_50bps_usd",
                    "depth_25bps_usd",
                    "top_of_book_depth_usd",
                ),
                True,
            ),
        ):
            value, source_field = _first_feature_numeric_field(feature_payload, fields)
            _set_market_cost_value(
                out,
                sources,
                target,
                value,
                f"{source_prefix}.{source_field}" if source_field else None,
                positive_only=positive_only,
            )
        if "fee_bps" not in out:
            fee_rate, source_field = _first_feature_numeric_field(
                feature_payload,
                (
                    "fee_rate",
                    "taker_fee_rate",
                    "expected_fee_rate",
                    "estimated_fee_rate",
                    "commission_rate",
                ),
            )
            _set_market_cost_rate_as_bps(
                out,
                sources,
                "fee_bps",
                fee_rate,
                f"{source_prefix}.{source_field}" if source_field else None,
            )
        if "orderbook_depth_usd" not in out:
            depth_usd, source_field = _feature_coinapi_book_depth_usd(
                decision_row=decision_row,
                feature_payload=feature_payload,
            )
            _set_market_cost_value(
                out,
                sources,
                "orderbook_depth_usd",
                depth_usd,
                f"{source_prefix}.{source_field}" if source_field else None,
                positive_only=True,
            )
        if "expected_funding_bps" not in out:
            funding_rate, source_field = _first_feature_numeric_field(
                feature_payload,
                ("funding_rate", "expected_funding_rate", "actual_funding_rate"),
            )
            if funding_rate is not None and source_field:
                _set_market_cost_rate_as_bps(
                    out,
                    sources,
                    "expected_funding_bps",
                    funding_rate,
                    f"{source_prefix}.{source_field}",
                )
        if "expected_slippage_bps" not in out:
            modeled_slippage_bps, source_field = _feature_modeled_slippage_bps(feature_payload)
            _set_market_cost_value(
                out,
                sources,
                "expected_slippage_bps",
                modeled_slippage_bps,
                f"{source_prefix}.{source_field}" if source_field else None,
            )

    missing_fields = []
    for field, reason in (
        ("actual_observed_spread_entry_bps", "MISSING_ACTUAL_SPREAD"),
        ("expected_slippage_bps", "MISSING_SLIPPAGE"),
        ("fee_bps", "MISSING_FEES"),
        ("expected_funding_bps", "MISSING_FUNDING"),
        ("orderbook_depth_usd", "MISSING_MARKET_DEPTH"),
    ):
        if field not in out:
            missing_fields.append(reason)

    feature_payload_dict = feature_payload if isinstance(feature_payload, dict) else {}
    out["market_cost_evidence_status"] = (
        "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE" if not missing_fields else "PARTIAL_EXPLICIT_MARKET_COST_EVIDENCE"
    )
    out["market_cost_evidence_missing_fields"] = missing_fields
    out["market_cost_evidence_source_fields"] = sources
    out["market_cost_evidence_pit_reject_reasons"] = reject_reasons
    out["market_cost_evidence_source_lineage"] = {
        "source": "status_generator_pit_feature_payload_fields_with_modeled_slippage_from_pit_spread",
        "feature_source_key": feature_source_key,
        "feature_snapshot_id": feature_payload_dict.get("feature_snapshot_id"),
        "feature_available_at": feature_payload_dict.get("available_at"),
        "feature_generated_at": _first_present(
            feature_payload_dict.get("generated_at"),
            feature_payload_dict.get("generated_utc"),
        ),
        "prediction_id": decision_row.get("prediction_id"),
        "prediction_decision_time": _first_present(
            decision_row.get("decision_time"),
            decision_row.get("decision_time_est"),
        ),
        "pit_guard_reject_reasons": reject_reasons,
    }
    return out


def _copy_market_cost_evidence(
    *,
    row: dict[str, Any],
    evidence: dict[str, Any],
    source_label: str,
    marker_prefix: str,
    prediction_id: Any = None,
) -> list[str]:
    copied_fields: list[str] = []
    source_fields = evidence.get("market_cost_evidence_source_fields")
    if not isinstance(source_fields, dict):
        return copied_fields
    merged_source_fields = (
        dict(row.get("market_cost_evidence_source_fields"))
        if isinstance(row.get("market_cost_evidence_source_fields"), dict)
        else {}
    )
    for field in COUNTERFACTUAL_MARKET_COST_LINEAGE_FIELDS:
        if field not in source_fields or row.get(field) not in {None, ""}:
            continue
        value = evidence.get(field)
        if value in {None, ""}:
            continue
        row[field] = value
        merged_source_fields[field] = source_fields[field]
        copied_fields.append(field)
    if copied_fields:
        row["market_cost_evidence_source_fields"] = merged_source_fields
        for metadata_field in (
            "market_cost_evidence_status",
            "market_cost_evidence_missing_fields",
            "market_cost_evidence_pit_reject_reasons",
            "market_cost_evidence_source_lineage",
        ):
            current_metadata = row.get(metadata_field)
            evidence_metadata = evidence.get(metadata_field)
            if (
                (current_metadata is None or current_metadata == "")
                and evidence_metadata is not None
                and evidence_metadata != ""
            ):
                row[metadata_field] = evidence_metadata
        row[f"{marker_prefix}_source"] = source_label
        row[f"{marker_prefix}_fields"] = sorted(copied_fields)
        if prediction_id not in {None, ""}:
            row[f"{marker_prefix}_prediction_id"] = prediction_id
    else:
        reject_reasons = evidence.get("market_cost_evidence_pit_reject_reasons")
        if reject_reasons and not row.get("market_cost_evidence_pit_reject_reasons"):
            row["market_cost_evidence_pit_reject_reasons"] = reject_reasons
            row["market_cost_evidence_source_lineage"] = evidence.get("market_cost_evidence_source_lineage")
    return copied_fields


def _prediction_rows_with_pit_feature_market_cost_context(
    prediction_rows: list[dict[str, Any]],
    feature_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    features_by_symbol_timeframe = _feature_rows_by_symbol_timeframe(feature_rows)
    features_by_snapshot_id = _feature_rows_by_snapshot_id(feature_rows)
    enriched_rows: list[dict[str, Any]] = []
    for prediction in prediction_rows:
        row = dict(prediction)
        feature = _matching_feature_payload(
            row,
            features_by_snapshot_id=features_by_snapshot_id,
            features_by_symbol_timeframe=features_by_symbol_timeframe,
        )
        evidence = _feature_market_cost_evidence_enrichment(
            decision_row=row,
            feature_payload=feature,
            feature_source_key=feature.get("source_redis_key") if isinstance(feature, dict) else None,
        )
        _copy_market_cost_evidence(
            row=row,
            evidence=evidence,
            source_label="prediction_latest_feature_snapshot_pit",
            marker_prefix="prediction_market_cost_enrichment",
            prediction_id=_first_present(row.get("prediction_id"), row.get("source_prediction_id"), row.get("entry_prediction_id")),
        )
        enriched_rows.append(row)
    return enriched_rows


def _counterfactual_signal_rows_with_prediction_temporal_context(
    *,
    paper_signals: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
    feature_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    features_by_symbol_timeframe = _feature_rows_by_symbol_timeframe(feature_rows or [])
    features_by_snapshot_id = _feature_rows_by_snapshot_id(feature_rows or [])
    predictions_by_id: dict[str, dict[str, Any]] = {}
    predictions_by_symbol_timeframe: dict[tuple[str, str], dict[str, Any]] = {}
    for prediction in prediction_rows:
        prediction_id = _first_present(
            prediction.get("prediction_id"),
            prediction.get("source_prediction_id"),
            prediction.get("entry_prediction_id"),
        )
        if prediction_id not in {None, ""}:
            predictions_by_id[str(prediction_id)] = prediction
        symbol = str(prediction.get("symbol") or "").upper()
        timeframe = str(prediction.get("timeframe") or "")
        if symbol and timeframe:
            predictions_by_symbol_timeframe.setdefault((symbol, timeframe), prediction)

    enriched_rows: list[dict[str, Any]] = []
    for signal in paper_signals:
        row = dict(signal)
        lineage = signal.get("lineage_ids") if isinstance(signal.get("lineage_ids"), dict) else {}
        candidate_prediction_ids = [
            signal.get("prediction_id"),
            signal.get("source_prediction_id"),
            signal.get("entry_prediction_id"),
            lineage.get("prediction_id"),
            lineage.get("trainer_prediction_id"),
        ]
        prediction = None
        matched_prediction_id: str | None = None
        matched_by_prediction_id = False
        for prediction_id in candidate_prediction_ids:
            if prediction_id in {None, ""}:
                continue
            prediction = predictions_by_id.get(str(prediction_id))
            if prediction is not None:
                matched_prediction_id = str(prediction_id)
                matched_by_prediction_id = True
                break
        if prediction is None:
            prediction = predictions_by_symbol_timeframe.get((
                str(signal.get("symbol") or "").upper(),
                str(signal.get("timeframe") or ""),
            ))
        if prediction is None:
            _copy_signal_feature_market_cost_context(
                row=row,
                source_label="paper_signal_feature_snapshot_pit",
                feature_rows_by_snapshot_id=features_by_snapshot_id,
                feature_rows_by_symbol_timeframe=features_by_symbol_timeframe,
            )
            enriched_rows.append(row)
            continue

        filled_fields: list[str] = []

        def fill_missing(field: str, *values: Any) -> None:
            if row.get(field) not in {None, ""}:
                return
            value = _first_present(*values)
            if value in {None, ""}:
                return
            row[field] = value
            filled_fields.append(field)

        signal_generated = _first_present(signal.get("generated_at"), signal.get("generated_utc"), signal.get("generated_est"))
        fill_missing(
            "decision_time",
            signal.get("decision_time"),
            signal_generated,
            prediction.get("decision_time"),
            prediction.get("decision_cutoff_time_est"),
        )
        fill_missing("generated_at", signal_generated)
        fill_missing("available_at", prediction.get("available_at"))
        fill_missing("feature_cutoff", prediction.get("feature_cutoff"))
        fill_missing("feature_snapshot_id", lineage.get("feature_snapshot_id"), prediction.get("feature_snapshot_id"))
        if filled_fields:
            row["counterfactual_temporal_enrichment_source"] = "paper_signal_prediction_lineage"
            row["counterfactual_temporal_enrichment_fields"] = sorted(filled_fields)
            row["counterfactual_temporal_enrichment_prediction_id"] = _first_present(
                prediction.get("prediction_id"),
                prediction.get("source_prediction_id"),
                prediction.get("entry_prediction_id"),
            )
        if matched_by_prediction_id:
            _copy_prediction_signal_quality_context(
                row=row,
                prediction=prediction,
                matched_prediction_id=matched_prediction_id,
                source_label="paper_signal_prediction_lineage",
            )
            _copy_prediction_market_cost_context(
                row=row,
                prediction=prediction,
                matched_prediction_id=matched_prediction_id,
                source_label="paper_signal_prediction_lineage",
                feature_rows_by_snapshot_id=features_by_snapshot_id,
                feature_rows_by_symbol_timeframe=features_by_symbol_timeframe,
            )
        elif _symbol_timeframe_prediction_market_cost_fallback_allowed(
            signal=signal,
            prediction=prediction,
        ):
            _copy_prediction_signal_quality_context(
                row=row,
                prediction=prediction,
                matched_prediction_id=None,
                source_label="paper_signal_prediction_symbol_timeframe_pit_fallback",
            )
            _copy_prediction_market_cost_context(
                row=row,
                prediction=prediction,
                matched_prediction_id=None,
                source_label="paper_signal_prediction_symbol_timeframe_pit_fallback",
                feature_rows_by_snapshot_id=features_by_snapshot_id,
                feature_rows_by_symbol_timeframe=features_by_symbol_timeframe,
            )
        else:
            _copy_signal_feature_market_cost_context(
                row=row,
                source_label="paper_signal_feature_snapshot_pit",
                feature_rows_by_snapshot_id=features_by_snapshot_id,
                feature_rows_by_symbol_timeframe=features_by_symbol_timeframe,
            )
        enriched_rows.append(row)
    return enriched_rows


def _symbol_timeframe_prediction_market_cost_fallback_allowed(
    *,
    signal: dict[str, Any],
    prediction: dict[str, Any],
) -> bool:
    if _normalized_symbol(signal) != _normalized_symbol(prediction):
        return False
    if str(signal.get("timeframe") or "") != str(prediction.get("timeframe") or ""):
        return False

    lineage = signal.get("lineage_ids") if isinstance(signal.get("lineage_ids"), dict) else {}
    signal_snapshot_id = _first_present(signal.get("feature_snapshot_id"), lineage.get("feature_snapshot_id"))
    prediction_snapshot_id = prediction.get("feature_snapshot_id")
    if (
        signal_snapshot_id not in {None, ""}
        and prediction_snapshot_id not in {None, ""}
        and str(signal_snapshot_id) != str(prediction_snapshot_id)
    ):
        return False

    prediction_decision_time = _parse_utc(_first_present(
        prediction.get("decision_time"),
        prediction.get("decision_time_est"),
        prediction.get("decision_cutoff_time_est"),
        prediction.get("generated_at"),
        prediction.get("generated_utc"),
        prediction.get("available_at"),
    ))
    if prediction_decision_time is None:
        return False
    signal_decision_time = _parse_utc(_first_present(
        signal.get("decision_time"),
        signal.get("decision_time_est"),
        signal.get("generated_at"),
        signal.get("generated_utc"),
        signal.get("generated_est"),
        signal.get("available_at"),
    ))
    return signal_decision_time is None or prediction_decision_time <= signal_decision_time


def _signal_prediction_quality_temporal_reject_reasons(
    *,
    row: dict[str, Any],
    prediction: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    signal_symbol = _normalized_symbol(row)
    prediction_symbol = _normalized_symbol(prediction)
    if signal_symbol != "UNKNOWN" and prediction_symbol != "UNKNOWN" and signal_symbol != prediction_symbol:
        reasons.append("PREDICTION_SYMBOL_MISMATCH")
    signal_timeframe = str(row.get("timeframe") or "")
    prediction_timeframe = str(prediction.get("timeframe") or "")
    if signal_timeframe and prediction_timeframe and signal_timeframe != prediction_timeframe:
        reasons.append("PREDICTION_TIMEFRAME_MISMATCH")

    signal_decision_time = _parse_utc(_first_present(
        row.get("decision_time"),
        row.get("decision_time_est"),
        row.get("generated_at"),
        row.get("generated_utc"),
        row.get("generated_est"),
        row.get("available_at"),
    ))
    if signal_decision_time is None:
        return reasons
    for label, value in (
        ("prediction_decision_time", _first_present(
            prediction.get("decision_time"),
            prediction.get("decision_time_est"),
            prediction.get("decision_cutoff_time_est"),
        )),
        ("prediction_generated_at", _first_present(
            prediction.get("generated_at"),
            prediction.get("generated_utc"),
            prediction.get("generated_est"),
        )),
        ("prediction_available_at", prediction.get("available_at")),
    ):
        parsed = _parse_utc(value)
        if parsed is not None and parsed > signal_decision_time:
            reasons.append(f"{label.upper()}_AFTER_SIGNAL_DECISION_TIME")
    return reasons


def _copy_prediction_signal_quality_context(
    *,
    row: dict[str, Any],
    prediction: dict[str, Any],
    matched_prediction_id: str | None,
    source_label: str,
) -> list[str]:
    reject_reasons = _signal_prediction_quality_temporal_reject_reasons(
        row=row,
        prediction=prediction,
    )
    if reject_reasons:
        row["counterfactual_signal_quality_enrichment_reject_reasons"] = reject_reasons
        return []

    prediction_id = _first_present(
        matched_prediction_id,
        prediction.get("prediction_id"),
        prediction.get("source_prediction_id"),
        prediction.get("entry_prediction_id"),
    )
    filled_fields: list[str] = []

    def fill_missing(field: str, *values: Any, existing_aliases: tuple[str, ...] = ()) -> None:
        if row.get(field) not in {None, ""} or any(row.get(alias) not in {None, ""} for alias in existing_aliases):
            return
        value = _first_present(*values)
        if value in {None, ""}:
            return
        row[field] = value
        filled_fields.append(field)

    fill_missing(
        "confidence_calibrated",
        prediction.get("confidence_calibrated"),
        prediction.get("confidence"),
        prediction.get("confidence_score"),
        prediction.get("model_confidence"),
        existing_aliases=("confidence",),
    )
    fill_missing(
        "expected_move_after_cost_bps",
        prediction.get("expected_move_after_cost_bps"),
        prediction.get("expected_net_edge_bps"),
        prediction.get("expected_edge_after_cost_bps"),
        prediction.get("after_cost_edge_bps"),
        prediction.get("edge_after_cost_bps"),
        prediction.get("net_edge_bps"),
        existing_aliases=(
            "expected_net_edge_bps",
            "expected_edge_after_cost_bps",
            "after_cost_edge_bps",
            "edge_after_cost_bps",
            "net_edge_bps",
        ),
    )
    if filled_fields:
        row["counterfactual_signal_quality_enrichment_source"] = source_label
        row["counterfactual_signal_quality_enrichment_fields"] = sorted(filled_fields)
        row["counterfactual_signal_quality_enrichment_prediction_id"] = prediction_id
    return filled_fields


def _copy_prediction_market_cost_context(
    *,
    row: dict[str, Any],
    prediction: dict[str, Any],
    matched_prediction_id: str | None,
    source_label: str,
    feature_rows_by_snapshot_id: dict[str, dict[str, Any]],
    feature_rows_by_symbol_timeframe: dict[tuple[str, str], dict[str, Any]],
) -> None:
    prediction_id = _first_present(
        matched_prediction_id,
        prediction.get("prediction_id"),
        prediction.get("source_prediction_id"),
        prediction.get("entry_prediction_id"),
    )
    _copy_market_cost_evidence(
        row=row,
        evidence=prediction,
        source_label=source_label,
        marker_prefix="counterfactual_market_cost_enrichment",
        prediction_id=prediction_id,
    )
    missing_market_cost_fields = any(
        row.get(field) in {None, ""}
        for field in COUNTERFACTUAL_MARKET_COST_LINEAGE_FIELDS
    )
    if not missing_market_cost_fields:
        return
    feature = _matching_feature_payload(
        row,
        features_by_snapshot_id=feature_rows_by_snapshot_id,
        features_by_symbol_timeframe=feature_rows_by_symbol_timeframe,
    )
    if feature is None:
        feature = _matching_feature_payload(
            prediction,
            features_by_snapshot_id=feature_rows_by_snapshot_id,
            features_by_symbol_timeframe=feature_rows_by_symbol_timeframe,
        )
    feature_evidence = _feature_market_cost_evidence_enrichment(
        decision_row=row,
        feature_payload=feature,
        feature_source_key=feature.get("source_redis_key") if isinstance(feature, dict) else None,
    )
    _copy_market_cost_evidence(
        row=row,
        evidence=feature_evidence,
        source_label=f"{source_label}_latest_feature_snapshot_pit",
        marker_prefix="counterfactual_feature_market_cost_enrichment",
        prediction_id=prediction_id,
    )


def _copy_signal_feature_market_cost_context(
    *,
    row: dict[str, Any],
    source_label: str,
    feature_rows_by_snapshot_id: dict[str, dict[str, Any]],
    feature_rows_by_symbol_timeframe: dict[tuple[str, str], dict[str, Any]],
) -> None:
    feature = _matching_feature_payload(
        row,
        features_by_snapshot_id=feature_rows_by_snapshot_id,
        features_by_symbol_timeframe=feature_rows_by_symbol_timeframe,
    )
    feature_evidence = _feature_market_cost_evidence_enrichment(
        decision_row=row,
        feature_payload=feature,
        feature_source_key=feature.get("source_redis_key") if isinstance(feature, dict) else None,
    )
    _copy_market_cost_evidence(
        row=row,
        evidence=feature_evidence,
        source_label=source_label,
        marker_prefix="counterfactual_feature_market_cost_enrichment",
        prediction_id=_first_present(
            row.get("prediction_id"),
            row.get("source_prediction_id"),
            row.get("entry_prediction_id"),
        ),
    )


def _accepted_fill_time_ms(row: dict[str, Any]) -> int | None:
    return _parse_epoch_ms(_first_present(
        row.get("original_fill_utc"),
        row.get("filled_at"),
        row.get("fill_time"),
        row.get("execution_time"),
        row.get("decision_time"),
        row.get("generated_utc"),
        row.get("event_time"),
    ))


def _unsafe_reconciliation_reasons(row: dict[str, Any], *, require_paper_only_true: bool) -> list[str]:
    reasons: list[str] = []
    if require_paper_only_true and row.get("paper_only") is not True:
        reasons.append("PAPER_ONLY_NOT_TRUE")
    elif row.get("paper_only") is False:
        reasons.append("PAPER_ONLY_FALSE")
    live_gate = row.get("live_gate")
    if live_gate not in {None, "", LIVE_GATE}:
        reasons.append("LIVE_GATE_NOT_BLOCKED_HUMAN_ONLY")
    for field in (
        "places_real_order",
        "test_orders",
        "test_order",
        "leverage_mutation",
        "margin_mode_mutation",
        "leverage_changed",
        "margin_mode_changed",
        "withdrawals",
        "transfers",
        "trainer_bridge_unmasked",
    ):
        if _truthy(row.get(field)):
            reasons.append(f"UNSAFE_{field.upper()}")
    return reasons


def _json_stable_key(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    except TypeError:
        return str(value)


def _reconcile_closed_trades_with_accepted_fills(
    *,
    closed_trades: list[dict[str, Any]],
    accepted_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    accepted_index: dict[str, list[dict[str, Any]]] = {}
    accepted_adaptive_count = 0
    for accepted in accepted_rows:
        if not _is_adaptive_capital_policy_row(accepted):
            continue
        accepted_adaptive_count += 1
        for lineage_id in _lineage_ids(accepted):
            accepted_index.setdefault(lineage_id, []).append(accepted)

    reconciled_rows: list[dict[str, Any]] = []
    candidate_closed_match_count = 0
    reconciled_count = 0
    complete_reconciled_count = 0
    rejected_reason_counts: dict[str, int] = {}
    sample: list[dict[str, Any]] = []
    metadata_filled_counts: dict[str, int] = {}
    metadata_ambiguous_counts: dict[str, int] = {}

    for row in closed_trades:
        if _is_adaptive_capital_policy_row(row) or row.get("paper_exit_policy_version") != P0_POLICY_VERSION:
            reconciled_rows.append(dict(row))
            continue

        lineage_ids = _lineage_ids(row)
        matched_by_id: dict[int, dict[str, Any]] = {}
        for lineage_id in lineage_ids:
            for accepted in accepted_index.get(lineage_id, []):
                matched_by_id[id(accepted)] = accepted
        matched = list(matched_by_id.values())
        if not matched:
            reconciled_rows.append(dict(row))
            continue

        candidate_closed_match_count += 1
        close_time_ms = _event_time_ms(row)
        usable: list[dict[str, Any]] = []
        row_reject_reasons: list[str] = []
        row_reject_reasons.extend(_unsafe_reconciliation_reasons(row, require_paper_only_true=False))
        for accepted in matched:
            reasons = _unsafe_reconciliation_reasons(accepted, require_paper_only_true=True)
            accepted_time_ms = _accepted_fill_time_ms(accepted)
            if close_time_ms is None:
                reasons.append("MISSING_CLOSE_EVENT_TIME")
            if accepted_time_ms is None:
                reasons.append("MISSING_ACCEPTED_FILL_TIME")
            if close_time_ms is not None and accepted_time_ms is not None and accepted_time_ms > close_time_ms:
                reasons.append("ACCEPTED_FILL_AFTER_CLOSE")
            if reasons:
                row_reject_reasons.extend(reasons)
                continue
            usable.append(accepted)

        if not usable:
            for reason in sorted(set(row_reject_reasons)):
                rejected_reason_counts[reason] = rejected_reason_counts.get(reason, 0) + 1
            reconciled_rows.append(dict(row))
            continue

        merged = dict(row)
        matched_ids = sorted({
            lineage_id for accepted in usable for lineage_id in _lineage_ids(accepted)
            if lineage_id in lineage_ids
        })
        merged["adaptive_capital_policy_version"] = ADAPTIVE_CAPITAL_POLICY_VERSION
        merged["adaptive_capital_policy_reconciled_from_accepted_fill"] = True
        merged["accepted_fill_policy_reconciliation_ids"] = matched_ids
        merged["accepted_fill_policy_reconciliation_source"] = "v2:paper:ledger.accepted"

        filled_fields: list[str] = []
        ambiguous_fields: list[str] = []
        for field in MANDATORY_PER_TRADE_FIELDS:
            if _field_present(merged, field):
                continue
            candidates = [
                _row_value(accepted, field)
                for accepted in usable
                if _row_field_present(accepted, field)
            ]
            unique: dict[str, Any] = {_json_stable_key(value): value for value in candidates}
            if len(unique) == 1:
                merged[field] = next(iter(unique.values()))
                filled_fields.append(field)
            elif len(unique) > 1:
                ambiguous_fields.append(field)

        remaining_missing = _missing_mandatory_fields(merged)
        if remaining_missing or ambiguous_fields:
            for reason in (
                [f"MISSING_{field.upper()}" for field in remaining_missing]
                + [f"AMBIGUOUS_{field.upper()}" for field in ambiguous_fields]
            ):
                rejected_reason_counts[reason] = rejected_reason_counts.get(reason, 0) + 1
            reconciled_rows.append(dict(row))
            continue
        complete_reconciled_count += 1
        reconciled_count += 1
        merged["accepted_fill_policy_reconciliation_filled_fields"] = filled_fields
        if ambiguous_fields:
            merged["accepted_fill_policy_reconciliation_ambiguous_fields"] = ambiguous_fields
        metadata_filled_fields: list[str] = []
        metadata_ambiguous_fields: list[str] = []
        for field in RECONCILABLE_POLICY_FUNDING_FIELDS:
            if _row_field_present(merged, field):
                continue
            candidates = [
                _row_value(accepted, field)
                for accepted in usable
                if _row_field_present(accepted, field)
            ]
            unique = {_json_stable_key(value): value for value in candidates}
            if len(unique) == 1:
                merged[field] = next(iter(unique.values()))
                metadata_filled_fields.append(field)
                metadata_filled_counts[field] = metadata_filled_counts.get(field, 0) + 1
            elif len(unique) > 1:
                metadata_ambiguous_fields.append(field)
                metadata_ambiguous_counts[field] = metadata_ambiguous_counts.get(field, 0) + 1
        if metadata_filled_fields:
            merged["accepted_fill_policy_reconciliation_filled_metadata_fields"] = metadata_filled_fields
        if metadata_ambiguous_fields:
            merged["accepted_fill_policy_reconciliation_ambiguous_metadata_fields"] = metadata_ambiguous_fields
        if sample and len(sample) >= 20:
            pass
        elif len(sample) < 20:
            sample.append({
                "symbol": merged.get("symbol"),
                "timeframe": merged.get("timeframe"),
                "side": _first_present(merged.get("side"), merged.get("action")),
                "close_id": merged.get("close_id"),
                "entry_signal_id": merged.get("entry_signal_id"),
                "entry_prediction_id": merged.get("entry_prediction_id"),
                "accepted_fill_policy_reconciliation_ids": matched_ids,
                "filled_mandatory_fields": filled_fields,
                "filled_policy_funding_metadata_fields": metadata_filled_fields,
                "remaining_missing_mandatory_fields": remaining_missing,
                "ambiguous_mandatory_fields": ambiguous_fields,
                "ambiguous_policy_funding_metadata_fields": metadata_ambiguous_fields,
                "realized_pnl_usd": _pnl(merged),
                "allocated_margin_usd": _margin(merged),
            })
        reconciled_rows.append(merged)

    return reconciled_rows, {
        "source": "v2:paper:ledger.closed_trades + v2:paper:ledger.accepted",
        "reconciliation_policy": (
            "P0 closed outcomes may inherit adaptive capital policy and missing mandatory allocation fields "
            "only from paper-only accepted fills sharing exact lineage IDs and with accepted fill time <= close time; "
            "unambiguous policy activation and funding-term metadata may be carried for audit visibility, "
            "but funding_pnl_usd is never synthesized by this read-only reconciliation"
        ),
        "accepted_adaptive_fill_count": accepted_adaptive_count,
        "candidate_closed_match_count": candidate_closed_match_count,
        "reconciled_closed_outcome_count": reconciled_count,
        "complete_reconciled_closed_outcome_count": complete_reconciled_count,
        "filled_policy_funding_metadata_counts": {
            key: metadata_filled_counts[key] for key in sorted(metadata_filled_counts)
        },
        "ambiguous_policy_funding_metadata_counts": {
            key: metadata_ambiguous_counts[key] for key in sorted(metadata_ambiguous_counts)
        },
        "rejected_reason_counts": {key: rejected_reason_counts[key] for key in sorted(rejected_reason_counts)},
        "sample": sample,
    }


def _mandatory_field_missing_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        field: sum(1 for row in rows if not _field_present(row, field))
        for field in MANDATORY_PER_TRADE_FIELDS
    }
    return {
        field: count for field, count in counts.items()
        if count > 0
    }


def _mandatory_gap_sample(rows: list[dict[str, Any]], *, limit: int = 10) -> list[dict[str, Any]]:
    sample: list[dict[str, Any]] = []
    for row in rows:
        missing = _missing_mandatory_fields(row)
        if not missing:
            continue
        sample.append({
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "side": _first_present(row.get("side"), row.get("action")),
            "adaptive_capital_policy_version": _capital_policy_version(row),
            "paper_exit_policy_version": row.get("paper_exit_policy_version"),
            "missing_mandatory_fields": missing,
        })
        if len(sample) >= limit:
            break
    return sample


def _closed_outcome_sample(rows: list[dict[str, Any]], *, limit: int = 10) -> list[dict[str, Any]]:
    sample: list[dict[str, Any]] = []
    for row in rows:
        sample.append({
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "side": _first_present(row.get("side"), row.get("action")),
            "close_id": _first_present(
                row.get("close_id"),
                row.get("trade_id"),
                row.get("position_id"),
                row.get("id"),
            ),
            "entry_signal_id": row.get("entry_signal_id"),
            "entry_prediction_id": row.get("entry_prediction_id"),
            "adaptive_capital_policy_version": _capital_policy_version(row),
            "paper_exit_policy_version": row.get("paper_exit_policy_version"),
            "missing_mandatory_fields": _missing_mandatory_fields(row),
            "realized_pnl_usd": _pnl(row),
            "allocated_margin_usd": _margin(row),
        })
        if len(sample) >= limit:
            break
    return sample


def _closed_outcome_evidence_gap_analysis(
    *,
    raw_closed_trades: list[dict[str, Any]],
    post_policy_closed: list[dict[str, Any]],
    post_capital_policy_closed: list[dict[str, Any]],
    post_allocator_closed: list[dict[str, Any]],
    post_capital_policy_open: list[dict[str, Any]],
    complete_open_post_capital_policy: list[dict[str, Any]],
    accepted_fill_reconciliation: dict[str, Any],
) -> dict[str, Any]:
    unversioned_post_p0_closed = [
        row for row in post_policy_closed
        if not _is_adaptive_capital_policy_row(row)
    ]
    complete_unversioned_post_p0_closed = _rows_with_complete_mandatory_fields(
        unversioned_post_p0_closed
    )
    current_symbols = sorted({
        str(row.get("symbol") or "").upper()
        for row in post_allocator_closed
        if row.get("symbol")
    })
    potential_symbols = sorted({
        *current_symbols,
        *(
            str(row.get("symbol") or "").upper()
            for row in complete_unversioned_post_p0_closed
            if row.get("symbol")
        ),
    })
    potential_closed_count = len(post_allocator_closed) + len(complete_unversioned_post_p0_closed)
    return {
        "raw_closed_trade_count": len(raw_closed_trades),
        "post_p0_closed_trade_count": len(post_policy_closed),
        "non_p0_closed_trade_count": max(0, len(raw_closed_trades) - len(post_policy_closed)),
        "post_capital_policy_closed_row_count": len(post_capital_policy_closed),
        "complete_post_capital_policy_closed_outcome_count": len(post_allocator_closed),
        "post_capital_policy_closed_missing_mandatory_count": (
            len(post_capital_policy_closed) - len(post_allocator_closed)
        ),
        "post_capital_policy_closed_missing_mandatory_field_counts": (
            _mandatory_field_missing_counts(post_capital_policy_closed)
        ),
        "post_capital_policy_closed_missing_mandatory_sample": (
            _mandatory_gap_sample(post_capital_policy_closed)
        ),
        "unversioned_post_p0_closed_count": len(unversioned_post_p0_closed),
        "unversioned_post_p0_closed_with_all_mandatory_fields_count": (
            len(complete_unversioned_post_p0_closed)
        ),
        "unversioned_post_p0_closed_with_all_mandatory_fields_sample": (
            _closed_outcome_sample(complete_unversioned_post_p0_closed)
        ),
        "potential_complete_closed_outcomes_if_unversioned_rows_gain_safe_policy_lineage": (
            potential_closed_count
        ),
        "additional_complete_closed_outcomes_needed_after_unversioned_policy_lineage": max(
            0,
            MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES - potential_closed_count,
        ),
        "current_symbol_count": len(current_symbols),
        "current_symbols_sample": current_symbols[:30],
        "potential_symbol_count_if_unversioned_rows_gain_safe_policy_lineage": (
            len(potential_symbols)
        ),
        "potential_symbols_sample": potential_symbols[:30],
        "additional_symbols_needed_after_unversioned_policy_lineage": max(
            0,
            MINIMUM_POLICY_SYMBOL_COUNT - len(potential_symbols),
        ),
        "open_post_capital_policy_row_count": len(post_capital_policy_open),
        "open_positions_ready_to_become_closed_outcomes": len(complete_open_post_capital_policy),
        "accepted_fill_candidate_closed_match_count": (
            accepted_fill_reconciliation.get("candidate_closed_match_count", 0)
        ),
        "accepted_fill_reconciled_closed_outcome_count": (
            accepted_fill_reconciliation.get("complete_reconciled_closed_outcome_count", 0)
        ),
        "accepted_fill_rejected_reason_counts": (
            accepted_fill_reconciliation.get("rejected_reason_counts") or {}
        ),
        "promotion_requirements": [
            "closed row must be P0 exit policy",
            "closed row must carry adaptive capital policy version or safe accepted-fill reconciliation",
            "all mandatory per-trade fields must be present",
            "accepted fill must be paper-only and not place a real order",
            "accepted fill lineage must match exact close lineage IDs",
            "accepted fill time must be <= close time",
        ],
    }


def _signal_source_kind(row: dict[str, Any], fallback: str) -> str:
    return str(_first_present(
        row.get("counterfactual_source_kind"),
        row.get("source_kind"),
        fallback,
    ))


def _candidate_symbol_sample(
    sourced_rows: list[tuple[str, dict[str, Any]]],
    *,
    current_closed_symbols: set[str],
    limit: int = 20,
) -> list[dict[str, Any]]:
    sample: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_kind, row in sorted(
        sourced_rows,
        key=lambda item: (
            -(_coerce_float(_first_present(
                item[1].get("confidence_calibrated"),
                item[1].get("confidence"),
            )) or -1.0),
            -(_expected_edge_bps(item[1]) or -999999.0),
            _normalized_symbol(item[1]),
            str(_row_value(item[1], "timeframe") or item[1].get("timeframe") or ""),
            _row_identity(item[1]),
        ),
    ):
        symbol = _normalized_symbol(row)
        if not symbol or symbol == "UNKNOWN" or symbol in current_closed_symbols:
            continue
        identity = _row_identity(row)
        if identity in seen:
            continue
        seen.add(identity)
        confidence = _coerce_float(_first_present(row.get("confidence_calibrated"), row.get("confidence")))
        edge = _expected_edge_bps(row)
        reasons: list[str] = []
        if _directional_side(row) not in {"long", "short"}:
            reasons.append("NON_DIRECTIONAL_ACTION")
        if confidence is None:
            reasons.append("MISSING_CONFIDENCE")
        elif confidence < A_GRADE_CONFIDENCE_THRESHOLD:
            reasons.append("LOW_CONFIDENCE")
        if edge is None:
            reasons.append("MISSING_AFTER_COST_EDGE")
        elif edge <= 0.0:
            reasons.append("NON_POSITIVE_AFTER_COST_EDGE")
        decision = _allocator_decision(row)
        if decision.startswith("BLOCK_"):
            reasons.append(f"ALLOCATOR_{decision}")
        sample.append({
            "symbol": symbol,
            "source_kind": _signal_source_kind(row, source_kind),
            "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
            "side": _directional_side(row),
            "confidence": round(confidence, 8) if confidence is not None else None,
            "confidence_gap_to_a_grade": (
                round(max(0.0, A_GRADE_CONFIDENCE_THRESHOLD - confidence), 8)
                if confidence is not None else None
            ),
            "after_cost_edge_bps": round(edge, 8) if edge is not None else None,
            "edge_gap_to_positive_bps": (
                round(max(0.0, -edge), 8) if edge is not None else None
            ),
            "allocator_decision": decision or None,
            "signal_id": _first_present(row.get("signal_id"), row.get("entry_signal_id"), row.get("exit_signal_id")),
            "prediction_id": _first_present(row.get("prediction_id"), row.get("entry_prediction_id"), row.get("exit_prediction_id")),
            "feature_snapshot_id": _first_present(
                row.get("feature_snapshot_id"),
                row.get("entry_feature_snapshot_id"),
                row.get("prediction_feature_snapshot_id"),
            ),
            "decision_time": _first_present(row.get("decision_time"), row.get("entry_feature_decision_time")),
            "available_at": _first_present(row.get("available_at"), row.get("entry_feature_available_at")),
            "generated_at": _first_present(row.get("generated_at"), row.get("entry_feature_generated_at")),
            "feature_cutoff": _first_present(row.get("feature_cutoff"), row.get("entry_feature_cutoff")),
            "market_cost_evidence_status": row.get("market_cost_evidence_status"),
            "missing_market_cost_evidence": row.get("missing_market_cost_evidence", []),
            "market_cost_evidence_pit_reject_reasons": (
                row.get("market_cost_evidence_pit_reject_reasons", [])
            ),
            "reasons": sorted(set(reasons)),
        })
        if len(sample) >= limit:
            break
    return sample


def _symbol_diversity_opportunity_analysis(
    *,
    post_allocator_closed: list[dict[str, Any]],
    complete_open_post_capital_policy: list[dict[str, Any]],
    paper_signals: list[dict[str, Any]],
    paper_intents: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
    counterfactual_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    current_closed_symbols = {
        _normalized_symbol(row)
        for row in post_allocator_closed
        if _normalized_symbol(row) != "UNKNOWN"
    }
    open_ready_symbols = sorted({
        _normalized_symbol(row)
        for row in complete_open_post_capital_policy
        if _normalized_symbol(row) not in {"UNKNOWN", *current_closed_symbols}
    })

    signal_prediction_rows: list[tuple[str, dict[str, Any]]] = []
    for source_kind, rows in (
        ("paper_signal", paper_signals),
        ("paper_intent", paper_intents),
        ("prediction", prediction_rows),
    ):
        for row in rows:
            signal_prediction_rows.append((source_kind, row))
    sourced_rows = [*signal_prediction_rows]
    for row in counterfactual_rows:
        sourced_rows.append(("counterfactual", row))

    deduped_sourced_rows: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for source_kind, row in sourced_rows:
        identity = _row_identity(row)
        if identity in seen:
            continue
        seen.add(identity)
        deduped_sourced_rows.append((source_kind, row))

    signal_universe_symbols = sorted({
        _normalized_symbol(row)
        for _source_kind, row in signal_prediction_rows
        if _normalized_symbol(row) != "UNKNOWN"
    })
    signal_prediction_source_row_count = len({
        _row_identity(row)
        for _source_kind, row in signal_prediction_rows
    })
    symbols_without_closed = sorted(
        symbol for symbol in signal_universe_symbols
        if symbol not in current_closed_symbols
    )
    positive_edge_rows = [
        (source_kind, row)
        for source_kind, row in deduped_sourced_rows
        if (
            _normalized_symbol(row) not in {"UNKNOWN", *current_closed_symbols}
            and (_expected_edge_bps(row) or 0.0) > 0.0
        )
    ]
    near_a_grade_rows = [
        (source_kind, row)
        for source_kind, row in positive_edge_rows
        if (
            _coerce_float(_first_present(row.get("confidence_calibrated"), row.get("confidence"))) or 0.0
        ) >= NEAR_A_GRADE_REPLAY_CONFIDENCE_THRESHOLD
    ]
    positive_edge_symbols = sorted({
        _normalized_symbol(row)
        for _source_kind, row in positive_edge_rows
        if _normalized_symbol(row) != "UNKNOWN"
    })
    near_a_grade_symbols = sorted({
        _normalized_symbol(row)
        for _source_kind, row in near_a_grade_rows
        if _normalized_symbol(row) != "UNKNOWN"
    })
    potential_symbols = sorted({
        *current_closed_symbols,
        *open_ready_symbols,
        *positive_edge_symbols,
    })
    source_kind_counts: dict[str, int] = {}
    for source_kind, row in deduped_sourced_rows:
        normalized_kind = _signal_source_kind(row, source_kind)
        source_kind_counts[normalized_kind] = source_kind_counts.get(normalized_kind, 0) + 1
    signal_prediction_source_kind_counts: dict[str, int] = {}
    for source_kind, row in signal_prediction_rows:
        normalized_kind = _signal_source_kind(row, source_kind)
        signal_prediction_source_kind_counts[normalized_kind] = (
            signal_prediction_source_kind_counts.get(normalized_kind, 0) + 1
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "status": (
            "PASSED" if len(current_closed_symbols) >= MINIMUM_POLICY_SYMBOL_COUNT
            else "NO_GO_SYMBOL_DIVERSITY_EVIDENCE_INSUFFICIENT"
        ),
        "minimum_required_symbol_count": MINIMUM_POLICY_SYMBOL_COUNT,
        "current_closed_symbol_count": len(current_closed_symbols),
        "current_closed_symbols": sorted(current_closed_symbols),
        "additional_symbols_needed": max(
            0,
            MINIMUM_POLICY_SYMBOL_COUNT - len(current_closed_symbols),
        ),
        "gate_counts_only_complete_post_policy_closed_outcomes": True,
        "candidate_symbols_do_not_count_until_closed": True,
        "gate_note": (
            "Only complete post-policy closed outcomes count toward symbol diversity. "
            "Open positions and signal/prediction candidates are burn-down leads, not pass evidence."
        ),
        "open_ready_symbols_not_yet_counted_count": len(open_ready_symbols),
        "open_ready_symbols_not_yet_counted": open_ready_symbols,
        "signal_prediction_source_row_count": signal_prediction_source_row_count,
        "candidate_source_row_count": len(deduped_sourced_rows),
        "signal_prediction_source_kind_counts": {
            key: signal_prediction_source_kind_counts[key]
            for key in sorted(signal_prediction_source_kind_counts)
        },
        "candidate_source_kind_counts": {
            key: source_kind_counts[key]
            for key in sorted(source_kind_counts)
        },
        "signal_universe_symbol_count": len(signal_universe_symbols),
        "signal_universe_symbols": signal_universe_symbols,
        "signal_universe_symbols_without_closed_outcomes_count": len(symbols_without_closed),
        "signal_universe_symbols_without_closed_outcomes_sample": symbols_without_closed[:30],
        "positive_edge_candidate_symbols_without_closed_outcomes_count": len(positive_edge_symbols),
        "positive_edge_candidate_symbols_without_closed_outcomes_sample": positive_edge_symbols[:30],
        "near_a_grade_candidate_symbols_without_closed_outcomes_count": len(near_a_grade_symbols),
        "near_a_grade_candidate_symbols_without_closed_outcomes_sample": near_a_grade_symbols[:30],
        "potential_symbol_count_if_open_ready_and_positive_edge_candidates_close": len(potential_symbols),
        "additional_symbols_needed_if_open_ready_and_positive_edge_candidates_close": max(
            0,
            MINIMUM_POLICY_SYMBOL_COUNT - len(potential_symbols),
        ),
        "candidate_symbols_without_closed_outcomes_sample": _candidate_symbol_sample(
            [*near_a_grade_rows, *positive_edge_rows],
            current_closed_symbols=current_closed_symbols,
        ),
    }


def _a_grade_blocker_reasons(row: dict[str, Any]) -> list[str]:
    confidence = _coerce_float(_first_present(row.get("confidence_calibrated"), row.get("confidence")))
    edge = _expected_edge_bps(row)
    decision = _allocator_decision(row)
    side = _directional_side(row)
    reasons: list[str] = []
    if side not in {"long", "short"}:
        reasons.append("NON_DIRECTIONAL_ACTION")
    if confidence is None:
        reasons.append("MISSING_CONFIDENCE")
    elif confidence < A_GRADE_CONFIDENCE_THRESHOLD:
        reasons.append("LOW_CONFIDENCE")
    if edge is None:
        reasons.append("MISSING_AFTER_COST_EDGE")
    elif edge <= 0.0:
        reasons.append("NON_POSITIVE_AFTER_COST_EDGE")
    if decision.startswith("BLOCK_"):
        reasons.append(f"ALLOCATOR_{decision}")
    return reasons


def _a_grade_blocker_sample(
    sourced_rows: list[tuple[str, dict[str, Any]]],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    sample: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_kind, row in sorted(
        sourced_rows,
        key=lambda item: (
            -(_coerce_float(_first_present(
                item[1].get("confidence_calibrated"),
                item[1].get("confidence"),
            )) or -1.0),
            -(_expected_edge_bps(item[1]) or -999999.0),
            _normalized_symbol(item[1]),
            str(_row_value(item[1], "timeframe") or item[1].get("timeframe") or ""),
            _row_identity(item[1]),
        ),
    ):
        identity = _row_identity(row)
        if identity in seen:
            continue
        seen.add(identity)
        confidence = _coerce_float(_first_present(row.get("confidence_calibrated"), row.get("confidence")))
        edge = _expected_edge_bps(row)
        temporal_reasons = _pre_submit_temporal_reasons(row)
        sample.append({
            "symbol": _normalized_symbol(row),
            "source_kind": _signal_source_kind(row, source_kind),
            "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
            "side": _directional_side(row),
            "confidence": round(confidence, 8) if confidence is not None else None,
            "confidence_gap_to_a_grade": (
                round(max(0.0, A_GRADE_CONFIDENCE_THRESHOLD - confidence), 8)
                if confidence is not None else None
            ),
            "after_cost_edge_bps": round(edge, 8) if edge is not None else None,
            "edge_gap_to_positive_bps": round(max(0.0, -edge), 8) if edge is not None else None,
            "allocator_decision": _allocator_decision(row) or None,
            "signal_id": _first_present(row.get("signal_id"), row.get("entry_signal_id"), row.get("exit_signal_id")),
            "prediction_id": _first_present(row.get("prediction_id"), row.get("entry_prediction_id"), row.get("exit_prediction_id")),
            "feature_snapshot_id": _first_present(
                row.get("feature_snapshot_id"),
                row.get("entry_feature_snapshot_id"),
                row.get("prediction_feature_snapshot_id"),
            ),
            "decision_time": _first_present(row.get("decision_time"), row.get("entry_feature_decision_time")),
            "available_at": _first_present(row.get("available_at"), row.get("entry_feature_available_at")),
            "generated_at": _first_present(row.get("generated_at"), row.get("entry_feature_generated_at")),
            "feature_cutoff": _first_present(row.get("feature_cutoff"), row.get("entry_feature_cutoff")),
            "temporal_reasons": temporal_reasons,
            "event_time_valid": not temporal_reasons,
            "market_cost_evidence_status": row.get("market_cost_evidence_status"),
            "missing_market_cost_evidence": row.get("missing_market_cost_evidence", []),
            "market_cost_evidence_pit_reject_reasons": (
                row.get("market_cost_evidence_pit_reject_reasons", [])
            ),
            "reasons": sorted(set(_a_grade_blocker_reasons(row))),
        })
        if len(sample) >= limit:
            break
    return sample


def _a_grade_blocker_analysis(
    sourced_rows: list[tuple[str, dict[str, Any]]],
) -> dict[str, Any]:
    deduped: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for source_kind, row in sourced_rows:
        identity = _row_identity(row)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append((source_kind, row))

    source_kind_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    high_confidence_rows: list[tuple[str, dict[str, Any]]] = []
    positive_edge_rows: list[tuple[str, dict[str, Any]]] = []
    low_confidence_positive_edge_rows: list[tuple[str, dict[str, Any]]] = []
    high_confidence_edge_gap_rows: list[tuple[str, dict[str, Any]]] = []
    high_confidence_positive_edge_rows: list[tuple[str, dict[str, Any]]] = []
    blocked_intersection_rows: list[tuple[str, dict[str, Any]]] = []
    strict_a_grade_rows: list[tuple[str, dict[str, Any]]] = []
    temporal_invalid_rows: list[tuple[str, dict[str, Any]]] = []
    event_time_valid_rows: list[tuple[str, dict[str, Any]]] = []
    directional_count = 0
    confidence_present_count = 0
    edge_present_count = 0

    for source_kind, row in deduped:
        normalized_kind = _signal_source_kind(row, source_kind)
        source_kind_counts[normalized_kind] = source_kind_counts.get(normalized_kind, 0) + 1
        confidence = _coerce_float(_first_present(row.get("confidence_calibrated"), row.get("confidence")))
        edge = _expected_edge_bps(row)
        side = _directional_side(row)
        decision = _allocator_decision(row)
        if side in {"long", "short"}:
            directional_count += 1
        if confidence is not None:
            confidence_present_count += 1
        if edge is not None:
            edge_present_count += 1
        high_confidence = confidence is not None and confidence >= A_GRADE_CONFIDENCE_THRESHOLD
        positive_edge = edge is not None and edge > 0.0
        if high_confidence:
            high_confidence_rows.append((source_kind, row))
        if positive_edge:
            positive_edge_rows.append((source_kind, row))
        if positive_edge and not high_confidence:
            low_confidence_positive_edge_rows.append((source_kind, row))
        if high_confidence and not positive_edge:
            high_confidence_edge_gap_rows.append((source_kind, row))
        if high_confidence and positive_edge:
            high_confidence_positive_edge_rows.append((source_kind, row))
        strict_reasons = _a_grade_blocker_reasons(row)
        for reason in strict_reasons:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        if high_confidence and positive_edge and side in {"long", "short"} and decision.startswith("BLOCK_"):
            blocked_intersection_rows.append((source_kind, row))
        if not strict_reasons:
            strict_a_grade_rows.append((source_kind, row))
            temporal_reasons = _pre_submit_temporal_reasons(row)
            if temporal_reasons:
                temporal_invalid_rows.append((source_kind, row))
            else:
                event_time_valid_rows.append((source_kind, row))

    blocker_reasons: list[str] = []
    if not strict_a_grade_rows:
        blocker_reasons.append("NO_STRICT_A_GRADE_INTERSECTION")
    if low_confidence_positive_edge_rows:
        blocker_reasons.append("POSITIVE_EDGE_ROWS_BELOW_CONFIDENCE_THRESHOLD")
    if high_confidence_edge_gap_rows:
        blocker_reasons.append("HIGH_CONFIDENCE_ROWS_MISSING_OR_NON_POSITIVE_EDGE")
    if blocked_intersection_rows:
        blocker_reasons.append("HIGH_CONFIDENCE_POSITIVE_EDGE_ROWS_ALLOCATOR_BLOCKED")
    if strict_a_grade_rows and not event_time_valid_rows:
        blocker_reasons.append("STRICT_A_GRADE_ROWS_TEMPORALLY_INVALID")

    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "status": "PASSED" if event_time_valid_rows else "NO_GO_A_GRADE_INTERSECTION_INCOMPLETE",
        "confidence_threshold": A_GRADE_CONFIDENCE_THRESHOLD,
        "after_cost_edge_bps_min_exclusive": 0.0,
        "row_count": len(deduped),
        "source_kind_counts": {
            key: source_kind_counts[key]
            for key in sorted(source_kind_counts)
        },
        "directional_row_count": directional_count,
        "confidence_present_count": confidence_present_count,
        "confidence_at_or_above_threshold_count": len(high_confidence_rows),
        "edge_present_count": edge_present_count,
        "positive_after_cost_edge_count": len(positive_edge_rows),
        "positive_edge_below_confidence_count": len(low_confidence_positive_edge_rows),
        "high_confidence_missing_or_non_positive_edge_count": len(high_confidence_edge_gap_rows),
        "high_confidence_and_positive_edge_count": len(high_confidence_positive_edge_rows),
        "high_confidence_positive_edge_allocator_blocked_count": len(blocked_intersection_rows),
        "strict_a_grade_before_temporal_count": len(strict_a_grade_rows),
        "event_time_valid_a_grade_count": len(event_time_valid_rows),
        "temporal_invalid_a_grade_count": len(temporal_invalid_rows),
        "blocker_reasons": blocker_reasons,
        "not_a_grade_reason_counts": {
            key: reason_counts[key]
            for key in sorted(reason_counts)
        },
        "high_confidence_missing_or_non_positive_edge_sample": _a_grade_blocker_sample(
            high_confidence_edge_gap_rows,
            limit=10,
        ),
        "positive_edge_below_confidence_sample": _a_grade_blocker_sample(
            low_confidence_positive_edge_rows,
            limit=10,
        ),
        "high_confidence_positive_edge_allocator_blocked_sample": _a_grade_blocker_sample(
            blocked_intersection_rows,
            limit=10,
        ),
        "strict_a_grade_before_temporal_sample": _a_grade_blocker_sample(
            strict_a_grade_rows,
            limit=10,
        ),
    }


def _leverage_margin_consistency_status(rows: list[dict[str, Any]], *, limit: int = 10) -> dict[str, Any]:
    complete_rows = _rows_with_complete_mandatory_fields(rows)
    consistent_count = 0
    inconsistent_sample: list[dict[str, Any]] = []
    for row in complete_rows:
        gross_notional = _coerce_float(_row_value(row, "gross_notional_usd"))
        allocated_margin = _coerce_float(_row_value(row, "allocated_margin_usd"))
        effective_leverage = _coerce_float(_row_value(row, "effective_leverage"))
        ratio = (
            gross_notional / allocated_margin
            if gross_notional is not None and allocated_margin not in {None, 0.0}
            else None
        )
        abs_error = (
            abs(ratio - effective_leverage)
            if ratio is not None and effective_leverage is not None
            else None
        )
        consistent = (
            gross_notional is not None
            and allocated_margin is not None
            and effective_leverage is not None
            and gross_notional > 0.0
            and allocated_margin > 0.0
            and effective_leverage > 0.0
            and abs_error is not None
            and abs_error <= LEVERAGE_MARGIN_RATIO_TOLERANCE
        )
        if consistent:
            consistent_count += 1
            continue
        if len(inconsistent_sample) >= limit:
            continue
        inconsistent_sample.append({
            "symbol": _normalized_symbol(row),
            "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
            "side": _first_present(row.get("side"), row.get("action"), _row_value(row, "side")),
            "gross_notional_usd": gross_notional,
            "allocated_margin_usd": allocated_margin,
            "effective_leverage": effective_leverage,
            "gross_notional_to_allocated_margin_ratio": round(ratio, 8) if ratio is not None else None,
            "absolute_error": round(abs_error, 8) if abs_error is not None else None,
        })

    row_count = len(complete_rows)
    inconsistent_count = row_count - consistent_count
    coverage = consistent_count / row_count if row_count else 0.0
    return {
        "status": (
            "PASSED" if row_count > 0 and inconsistent_count == 0 else
            "NO_COMPLETE_ACCOUNTING_ROWS" if row_count == 0 else
            "NO_GO_LEVERAGE_MARGIN_ACCOUNTING_INCONSISTENT"
        ),
        "formula": "gross_notional_usd / allocated_margin_usd == effective_leverage",
        "tolerance_abs": LEVERAGE_MARGIN_RATIO_TOLERANCE,
        "row_count": row_count,
        "consistent_row_count": consistent_count,
        "inconsistent_count": inconsistent_count,
        "consistency_coverage": round(coverage, 8),
        "inconsistent_sample": inconsistent_sample,
    }


def _accounting_enforcement_evidence(
    rows: list[dict[str, Any]],
    *,
    source: str,
) -> dict[str, Any]:
    complete_rows = _rows_with_complete_mandatory_fields(rows)
    row_count = len(rows)
    mandatory_field_coverage = len(complete_rows) / row_count if row_count else 0.0
    leverage_margin_consistency = _leverage_margin_consistency_status(rows)
    complete = (
        row_count > 0
        and mandatory_field_coverage >= 1.0
        and leverage_margin_consistency["status"] == "PASSED"
    )
    status = (
        "PASSED" if complete else
        "NO_ACCOUNTING_ROWS" if row_count == 0 else
        "NO_GO_FIELD_COVERAGE_INCOMPLETE" if mandatory_field_coverage < 1.0 else
        str(leverage_margin_consistency["status"])
    )
    return {
        "status": status,
        "source": source,
        "complete": complete,
        "row_count": row_count,
        "rows_with_all_mandatory_fields": len(complete_rows),
        "mandatory_field_coverage": round(mandatory_field_coverage, 8),
        "missing_by_field": _mandatory_field_missing_counts(rows),
        "missing_mandatory_sample": _mandatory_gap_sample(rows),
        "leverage_margin_consistency_status": leverage_margin_consistency["status"],
        "leverage_margin_accounting_formula": leverage_margin_consistency["formula"],
        "leverage_margin_consistency_row_count": leverage_margin_consistency["row_count"],
        "leverage_margin_consistent_row_count": leverage_margin_consistency["consistent_row_count"],
        "leverage_margin_inconsistent_count": leverage_margin_consistency["inconsistent_count"],
        "leverage_margin_consistency_coverage": leverage_margin_consistency["consistency_coverage"],
        "leverage_margin_inconsistent_sample": leverage_margin_consistency["inconsistent_sample"],
    }


def _policy_variation_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def _model_inputs(row: dict[str, Any]) -> dict[str, Any]:
        allocation = _allocation_mapping(row)
        value = _first_present(row.get("model_inputs"), allocation.get("model_inputs"))
        return value if isinstance(value, dict) else {}

    def _model_float(row: dict[str, Any], field: str) -> float | None:
        return _coerce_float(_model_inputs(row).get(field))

    notional_values = sorted({
        round(value, 8)
        for row in rows
        for value in [_notional(row)]
        if value > 0.0
    })
    margin_values = sorted({
        round(value, 8)
        for row in rows
        for value in [_margin(row)]
        if value > 0.0
    })
    recommended_leverage_values = sorted({
        round(value, 8)
        for row in rows
        for value in [_coerce_float(row.get("recommended_leverage"))]
        if value is not None and value > 0.0
    })
    effective_leverage_values = sorted({
        round(value, 8)
        for row in rows
        for value in [_coerce_float(row.get("effective_leverage"))]
        if value is not None and value > 0.0
    })
    raw_leverage_target_values = sorted({
        round(value, 8)
        for row in rows
        for value in [_model_float(row, "raw_leverage_target")]
        if value is not None and value > 0.0
    })
    leverage_target_values = sorted({
        round(value, 8)
        for row in rows
        for value in [_model_float(row, "leverage_target")]
        if value is not None and value > 0.0
    })
    selected_leverage_values = sorted({
        round(value, 8)
        for row in rows
        for value in [_model_float(row, "selected_leverage")]
        if value is not None and value > 0.0
    })
    margin_modes = sorted({
        str(row.get("recommended_margin_mode"))
        for row in rows
        if row.get("recommended_margin_mode") not in {None, ""}
    })
    reason_counts: dict[str, int] = {}
    leverage_reason_counts: dict[str, int] = {}
    selected_leverage_below_raw_target_count = 0
    leverage_filtered_to_1x_count = 0
    for row in rows:
        reason = str(row.get("capital_allocation_reason") or "__missing__")
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        model_inputs = _model_inputs(row)
        leverage_reason = str(model_inputs.get("leverage_selection_reason") or "__missing__")
        leverage_reason_counts[leverage_reason] = leverage_reason_counts.get(leverage_reason, 0) + 1
        raw_target = _coerce_float(model_inputs.get("raw_leverage_target"))
        selected_target = _coerce_float(_first_present(
            model_inputs.get("selected_leverage"),
            model_inputs.get("leverage_target"),
            row.get("effective_leverage"),
            row.get("recommended_leverage"),
        ))
        if raw_target is not None and selected_target is not None and raw_target > selected_target:
            selected_leverage_below_raw_target_count += 1
        if (
            selected_target is not None
            and selected_target <= 1.0
            and (
                "caps_leverage_at_1x" in leverage_reason
                or leverage_reason == "after_cost_edge_too_small_for_dynamic_leverage"
                or leverage_reason == "phase8_leverage_recommendation_invariant_violation"
            )
        ):
            leverage_filtered_to_1x_count += 1
    row_count = len(rows)
    size_variation_proven = row_count >= 2 and (len(notional_values) > 1 or len(margin_values) > 1)
    leverage_variation_proven = row_count >= 2 and (
        len(recommended_leverage_values) > 1
        or len(effective_leverage_values) > 1
    )
    dynamic_leverage_recommendation_present = any(value > 1.0 for value in raw_leverage_target_values)
    dynamic_raw_leverage_target_variation_proven = row_count >= 2 and len(raw_leverage_target_values) > 1
    if leverage_variation_proven:
        fixed_leverage_classification = "SELECTED_RUNTIME_LEVERAGE_VARIES"
    elif row_count < 2:
        fixed_leverage_classification = "INSUFFICIENT_ROWS_TO_CLASSIFY_RUNTIME_LEVERAGE"
    elif dynamic_leverage_recommendation_present and leverage_filtered_to_1x_count > 0:
        fixed_leverage_classification = "DYNAMIC_RECOMMENDATIONS_CAPPED_OR_FILTERED_TO_1X_BY_CURRENT_RISK_OR_EDGE"
    elif dynamic_leverage_recommendation_present:
        fixed_leverage_classification = "DYNAMIC_RECOMMENDATIONS_PRESENT_BUT_SELECTED_LEVERAGE_FIXED"
    else:
        fixed_leverage_classification = "NO_DYNAMIC_LEVERAGE_SELECTION_EVIDENCE"
    blockers: list[str] = []
    if row_count < 2:
        blockers.append("INSUFFICIENT_ROWS_TO_PROVE_RUNTIME_SIZE_AND_LEVERAGE_VARIATION")
    if not size_variation_proven:
        blockers.append("FIXED_OR_UNPROVEN_RUNTIME_SIZE")
    if not leverage_variation_proven:
        blockers.append("FIXED_OR_UNPROVEN_RUNTIME_LEVERAGE")
    return {
        "row_count": row_count,
        "runtime_size_variation_proven": size_variation_proven,
        "runtime_leverage_variation_proven": leverage_variation_proven,
        "notional_unique_count": len(notional_values),
        "allocated_margin_unique_count": len(margin_values),
        "recommended_leverage_unique_count": len(recommended_leverage_values),
        "effective_leverage_unique_count": len(effective_leverage_values),
        "raw_leverage_target_unique_count": len(raw_leverage_target_values),
        "leverage_target_unique_count": len(leverage_target_values),
        "selected_leverage_unique_count": len(selected_leverage_values),
        "recommended_margin_mode_unique_count": len(margin_modes),
        "notional_values_sample": notional_values[:20],
        "allocated_margin_values_sample": margin_values[:20],
        "recommended_leverage_values": recommended_leverage_values,
        "effective_leverage_values": effective_leverage_values,
        "raw_leverage_target_values": raw_leverage_target_values,
        "leverage_target_values": leverage_target_values,
        "selected_leverage_values": selected_leverage_values,
        "dynamic_leverage_recommendation_present": dynamic_leverage_recommendation_present,
        "dynamic_raw_leverage_target_variation_proven": dynamic_raw_leverage_target_variation_proven,
        "selected_leverage_below_raw_target_count": selected_leverage_below_raw_target_count,
        "selected_leverage_filtered_to_1x_count": leverage_filtered_to_1x_count,
        "fixed_leverage_classification": fixed_leverage_classification,
        "leverage_selection_reason_counts": {
            key: leverage_reason_counts[key]
            for key in sorted(leverage_reason_counts)
        },
        "recommended_margin_modes": margin_modes,
        "capital_allocation_reason_counts": {
            key: reason_counts[key]
            for key in sorted(reason_counts)
        },
        "variation_blocker_reasons": blockers,
    }


def _adaptive_field_selection_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def _allocation(row: dict[str, Any]) -> dict[str, Any]:
        value = row.get("adaptive_allocation")
        return value if isinstance(value, dict) else {}

    def _default_margin_mode_selection_reason(margin_mode: Any) -> str:
        value = str(margin_mode or "")
        if value in {"cross", "cross_paper_simulated"}:
            return "paper_cross_margin_simulated_for_high_edge_low_portfolio_pressure"
        if value in {"isolated", "isolated_paper_simulated"}:
            return "isolated_limits_tail_contagion_for_current_risk"
        return "recommended_margin_mode_selected_by_adaptive_allocator"

    def _model_inputs(row: dict[str, Any]) -> dict[str, Any]:
        allocation = _allocation(row)
        value = _first_present(row.get("model_inputs"), allocation.get("model_inputs"))
        model_inputs = dict(value) if isinstance(value, dict) else {}
        has_existing_selection_attribution = any(
            model_inputs.get(field) not in {None, ""}
            for field in (
                "selected_leverage",
                "leverage_target",
                "raw_leverage_target",
                "leverage_selection_reason",
                "selected_hedge_budget_pct_of_risk",
                "hedge_budget_selection_reason",
            )
        )
        if has_existing_selection_attribution:
            margin_mode = _first_present(
                model_inputs.get("selected_margin_mode"),
                row.get("selected_margin_mode"),
                allocation.get("selected_margin_mode"),
                row.get("recommended_margin_mode"),
                allocation.get("recommended_margin_mode"),
            )
            if margin_mode not in {None, ""}:
                model_inputs.setdefault("selected_margin_mode", margin_mode)
                model_inputs.setdefault(
                    "margin_mode_selection_reason",
                    _first_present(
                        row.get("margin_mode_selection_reason"),
                        allocation.get("margin_mode_selection_reason"),
                        _default_margin_mode_selection_reason(margin_mode),
                    ),
                )
        return model_inputs

    def _row_or_allocation(row: dict[str, Any], field: str) -> Any:
        allocation = _allocation(row)
        return _first_present(row.get(field), allocation.get(field))

    def _numeric_values(field: str) -> list[float]:
        return sorted({
            round(value, 8)
            for row in rows
            for value in [_coerce_float(_row_or_allocation(row, field))]
            if value is not None
        })

    def _text_values(field: str) -> list[str]:
        return sorted({
            str(value)
            for row in rows
            for value in [_row_or_allocation(row, field)]
            if value not in {None, ""}
        })

    def _reason_counts(field: str, *, from_model_inputs: bool = False) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in rows:
            source = _model_inputs(row) if from_model_inputs else row
            value = source.get(field)
            if value in {None, ""} and not from_model_inputs:
                value = _allocation(row).get(field)
            key = str(value or "__missing__")
            counts[key] = counts.get(key, 0) + 1
        return {key: counts[key] for key in sorted(counts)}

    def _has_leverage_attribution(row: dict[str, Any]) -> bool:
        model_inputs = _model_inputs(row)
        return (
            model_inputs.get("selected_leverage") is not None
            or model_inputs.get("leverage_target") is not None
            or model_inputs.get("raw_leverage_target") is not None
            or model_inputs.get("leverage_selection_reason") not in {None, ""}
        )

    def _has_margin_attribution(row: dict[str, Any]) -> bool:
        model_inputs = _model_inputs(row)
        return (
            model_inputs.get("selected_margin_mode") not in {None, ""}
            or model_inputs.get("margin_mode_selection_reason") not in {None, ""}
        )

    def _has_hedge_attribution(row: dict[str, Any]) -> bool:
        model_inputs = _model_inputs(row)
        return (
            model_inputs.get("selected_hedge_budget_pct_of_risk") is not None
            or model_inputs.get("hedge_budget_selection_reason") not in {None, ""}
        )

    required_selection_fields = [
        "gross_notional_usd",
        "allocated_margin_usd",
        "recommended_leverage",
        "effective_leverage",
        "recommended_margin_mode",
        "hedge_budget_usd",
        "capital_allocation_reason",
    ]
    rows_with_all_required_selection_fields = sum(
        1
        for row in rows
        if all(_row_or_allocation(row, field) not in {None, ""} for field in required_selection_fields)
    )
    row_count = len(rows)
    leverage_model_input_count = sum(1 for row in rows if _has_leverage_attribution(row))
    margin_model_input_count = sum(1 for row in rows if _has_margin_attribution(row))
    hedge_model_input_count = sum(1 for row in rows if _has_hedge_attribution(row))
    complete_selection_model_input_count = sum(
        1
        for row in rows
        if _has_leverage_attribution(row)
        and _has_margin_attribution(row)
        and _has_hedge_attribution(row)
    )
    missing_selection_attribution_sample: list[dict[str, Any]] = []
    for row in rows:
        missing_attribution = []
        if not _has_leverage_attribution(row):
            missing_attribution.append("leverage_selection_model_input")
        if not _has_margin_attribution(row):
            missing_attribution.append("margin_mode_selection_model_input")
        if not _has_hedge_attribution(row):
            missing_attribution.append("hedge_budget_selection_model_input")
        if not missing_attribution:
            continue
        missing_selection_attribution_sample.append({
            "symbol": _normalized_symbol(row),
            "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
            "side": _directional_side(row),
            "trade_id": _first_present(row.get("trade_id"), row.get("position_id"), row.get("order_id")),
            "adaptive_capital_policy_version": _capital_policy_version(row),
            "paper_exit_policy_version": row.get("paper_exit_policy_version"),
            "missing_selection_attribution": missing_attribution,
            "recommended_leverage": _coerce_float(_row_or_allocation(row, "recommended_leverage")),
            "effective_leverage": _coerce_float(_row_or_allocation(row, "effective_leverage")),
            "recommended_margin_mode": _row_or_allocation(row, "recommended_margin_mode"),
            "hedge_budget_usd": _coerce_float(_row_or_allocation(row, "hedge_budget_usd")),
        })
        if len(missing_selection_attribution_sample) >= 20:
            break
    hedge_budget_values = _numeric_values("hedge_budget_usd")
    return {
        "row_count": row_count,
        "required_selection_fields": required_selection_fields,
        "rows_with_all_required_selection_fields": rows_with_all_required_selection_fields,
        "required_selection_field_coverage": (
            round(rows_with_all_required_selection_fields / row_count, 8)
            if row_count else 0.0
        ),
        "gross_notional_unique_count": len(_numeric_values("gross_notional_usd")),
        "allocated_margin_unique_count": len(_numeric_values("allocated_margin_usd")),
        "recommended_leverage_unique_count": len(_numeric_values("recommended_leverage")),
        "effective_leverage_unique_count": len(_numeric_values("effective_leverage")),
        "recommended_margin_mode_unique_count": len(_text_values("recommended_margin_mode")),
        "hedge_budget_unique_count": len(hedge_budget_values),
        "gross_notional_values_sample": _numeric_values("gross_notional_usd")[:20],
        "allocated_margin_values_sample": _numeric_values("allocated_margin_usd")[:20],
        "recommended_leverage_values": _numeric_values("recommended_leverage"),
        "effective_leverage_values": _numeric_values("effective_leverage"),
        "recommended_margin_modes": _text_values("recommended_margin_mode"),
        "hedge_budget_values_sample": hedge_budget_values[:20],
        "positive_hedge_budget_count": sum(
            1
            for row in rows
            if (_coerce_float(_row_or_allocation(row, "hedge_budget_usd")) or 0.0) > 0.0
        ),
        "zero_hedge_budget_count": sum(
            1
            for row in rows
            if (_coerce_float(_row_or_allocation(row, "hedge_budget_usd")) or 0.0) == 0.0
        ),
        "capital_allocation_reason_counts": _reason_counts("capital_allocation_reason"),
        "leverage_selection_reason_counts": _reason_counts(
            "leverage_selection_reason",
            from_model_inputs=True,
        ),
        "margin_mode_selection_reason_counts": _reason_counts(
            "margin_mode_selection_reason",
            from_model_inputs=True,
        ),
        "hedge_budget_selection_reason_counts": _reason_counts(
            "hedge_budget_selection_reason",
            from_model_inputs=True,
        ),
        "leverage_selection_model_input_count": leverage_model_input_count,
        "leverage_selection_model_input_coverage": (
            round(leverage_model_input_count / row_count, 8)
            if row_count else 0.0
        ),
        "margin_mode_selection_model_input_count": margin_model_input_count,
        "margin_mode_selection_model_input_coverage": (
            round(margin_model_input_count / row_count, 8)
            if row_count else 0.0
        ),
        "hedge_budget_selection_model_input_count": hedge_model_input_count,
        "hedge_budget_selection_model_input_coverage": (
            round(hedge_model_input_count / row_count, 8)
            if row_count else 0.0
        ),
        "complete_selection_model_input_count": complete_selection_model_input_count,
        "complete_selection_model_input_coverage": (
            round(complete_selection_model_input_count / row_count, 8)
            if row_count else 0.0
        ),
        "selection_model_input_missing_counts": {
            "leverage_selection_model_input": max(0, row_count - leverage_model_input_count),
            "margin_mode_selection_model_input": max(0, row_count - margin_model_input_count),
            "hedge_budget_selection_model_input": max(0, row_count - hedge_model_input_count),
            "complete_selection_model_input": max(0, row_count - complete_selection_model_input_count),
        },
        "missing_selection_attribution_sample": missing_selection_attribution_sample,
        "selected_margin_mode_values": sorted({
            str(value)
            for row in rows
            for value in [_model_inputs(row).get("selected_margin_mode")]
            if value not in {None, ""}
        }),
        "selected_hedge_budget_pct_values": sorted({
            round(value, 8)
            for row in rows
            for value in [_coerce_float(_model_inputs(row).get("selected_hedge_budget_pct_of_risk"))]
            if value is not None
        }),
    }


def _selection_model_input_evidence_complete(evidence: dict[str, Any]) -> bool:
    row_count = int(evidence.get("row_count") or 0)
    if row_count <= 0:
        return False
    required_selection_field_coverage = _coerce_float(evidence.get("required_selection_field_coverage")) or 0.0
    leverage_coverage = _coerce_float(evidence.get("leverage_selection_model_input_coverage")) or 0.0
    margin_coverage = _coerce_float(evidence.get("margin_mode_selection_model_input_coverage")) or 0.0
    hedge_coverage = _coerce_float(evidence.get("hedge_budget_selection_model_input_coverage")) or 0.0
    return (
        required_selection_field_coverage >= 1.0
        and leverage_coverage >= 1.0
        and margin_coverage >= 1.0
        and hedge_coverage >= 1.0
    )


def _latest_strict_selection_model_input_suffix_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    suffix_start_index = len(rows)
    for index in range(len(rows) - 1, -1, -1):
        row_evidence = _adaptive_field_selection_evidence([rows[index]])
        if not _selection_model_input_evidence_complete(row_evidence):
            break
        suffix_start_index = index
    suffix_rows = rows[suffix_start_index:]
    suffix_evidence = _adaptive_field_selection_evidence(suffix_rows)
    suffix_complete = _selection_model_input_evidence_complete(suffix_evidence)
    suffix_count = len(suffix_rows)
    strict_suffix_proves_current_enforcement = (
        suffix_complete
        and suffix_count >= MINIMUM_DURABLE_STRICT_SELECTION_MODEL_INPUT_SUFFIX
    )
    return {
        "minimum_required_strict_suffix_count": MINIMUM_DURABLE_STRICT_SELECTION_MODEL_INPUT_SUFFIX,
        "latest_strict_suffix_start_index": suffix_start_index if suffix_rows else None,
        "latest_strict_suffix_count": suffix_count,
        "latest_strict_suffix_complete": suffix_complete,
        "latest_strict_suffix_proves_current_enforcement": strict_suffix_proves_current_enforcement,
        "historical_prefix_row_count": suffix_start_index,
        "historical_prefix_selection_model_input_gap_count": suffix_start_index if suffix_rows else len(rows),
        "historical_prefix_selection_model_input_gap_non_blocking": (
            suffix_start_index > 0 and strict_suffix_proves_current_enforcement
        ),
        "latest_strict_suffix_selection_model_input_evidence": suffix_evidence,
    }


def _durable_pre_submit_selection_attribution_complete(evidence: dict[str, Any] | None) -> bool:
    if not evidence:
        return False
    selection_evidence = evidence.get("versioned_candidate_selection_model_input_evidence")
    if not isinstance(selection_evidence, dict):
        return False
    suffix_evidence = evidence.get("latest_strict_selection_model_input_suffix_evidence")
    suffix_proves_current_enforcement = (
        isinstance(suffix_evidence, dict)
        and suffix_evidence.get("latest_strict_suffix_proves_current_enforcement") is True
    )
    return (
        evidence.get("status") == "PASSED"
        and int(evidence.get("versioned_sized_accepted_candidate_count") or 0) > 0
        and (_coerce_float(evidence.get("versioned_candidate_field_coverage")) or 0.0) >= 1.0
        and int(evidence.get("versioned_candidate_failure_count") or 0) == 0
        and (
            _selection_model_input_evidence_complete(selection_evidence)
            or suffix_proves_current_enforcement
        )
    )


def _adaptive_selection_attribution_status(
    evidence: dict[str, Any],
    *,
    pre_submit_evidence: dict[str, Any] | None = None,
    durable_pre_submit_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row_count = int(evidence.get("row_count") or 0)
    required_selection_field_coverage = _coerce_float(evidence.get("required_selection_field_coverage")) or 0.0
    leverage_coverage = _coerce_float(evidence.get("leverage_selection_model_input_coverage")) or 0.0
    margin_coverage = _coerce_float(evidence.get("margin_mode_selection_model_input_coverage")) or 0.0
    hedge_coverage = _coerce_float(evidence.get("hedge_budget_selection_model_input_coverage")) or 0.0
    historical_blocker_reasons: list[str] = []
    if row_count <= 0:
        historical_blocker_reasons.append("NO_ADAPTIVE_CAPITAL_ROWS_FOR_SELECTION_ATTRIBUTION")
    if required_selection_field_coverage < 1.0:
        historical_blocker_reasons.append("SELECTION_FIELDS_INCOMPLETE")
    if leverage_coverage < 1.0:
        historical_blocker_reasons.append("LEVERAGE_SELECTION_MODEL_INPUT_INCOMPLETE")
    if margin_coverage < 1.0:
        historical_blocker_reasons.append("MARGIN_MODE_SELECTION_MODEL_INPUT_INCOMPLETE")
    if hedge_coverage < 1.0:
        historical_blocker_reasons.append("HEDGE_BUDGET_SELECTION_MODEL_INPUT_INCOMPLETE")
    current_source = "runtime_adaptive_rows"
    pre_submit_row_count = int((pre_submit_evidence or {}).get("row_count") or 0)
    pre_submit_complete = _selection_model_input_evidence_complete(pre_submit_evidence or {})
    durable_complete = _durable_pre_submit_selection_attribution_complete(durable_pre_submit_evidence)
    if pre_submit_row_count > 0:
        current_enforcement_complete = pre_submit_complete
        current_source = "active_or_held_pre_submit_paper_intents"
    elif durable_complete:
        current_enforcement_complete = True
        suffix_evidence = (
            durable_pre_submit_evidence or {}
        ).get("latest_strict_selection_model_input_suffix_evidence")
        if (
            isinstance(suffix_evidence, dict)
            and suffix_evidence.get("latest_strict_suffix_proves_current_enforcement") is True
            and not _selection_model_input_evidence_complete(
                (durable_pre_submit_evidence or {}).get("versioned_candidate_selection_model_input_evidence") or {}
            )
        ):
            current_source = "durable_accepted_pre_submit_ledger_latest_strict_suffix"
        else:
            current_source = "durable_accepted_pre_submit_ledger"
    else:
        current_enforcement_complete = not historical_blocker_reasons
    runtime_selection_fields_complete = row_count > 0 and required_selection_field_coverage >= 1.0
    historical_gap_non_blocking = bool(historical_blocker_reasons) and current_enforcement_complete
    if row_count > 0 and current_enforcement_complete:
        blocker_reasons: list[str] = []
    else:
        blocker_reasons = list(historical_blocker_reasons)
        if runtime_selection_fields_complete and not current_enforcement_complete and not blocker_reasons:
            blocker_reasons.append("CURRENT_SELECTION_MODEL_INPUT_ENFORCEMENT_NOT_PROVEN")
    return {
        "status": "PASSED" if not blocker_reasons else "NO_GO_SELECTION_ATTRIBUTION_INCOMPLETE",
        "blocker_reasons": blocker_reasons,
        "historical_runtime_selection_model_input_gap_reasons": historical_blocker_reasons,
        "historical_runtime_selection_model_input_gap_non_blocking": historical_gap_non_blocking,
        "current_selection_model_input_enforcement_complete": current_enforcement_complete,
        "current_selection_model_input_enforcement_source": current_source,
        "current_pre_submit_selection_model_input_complete": pre_submit_complete,
        "current_pre_submit_selection_model_input_row_count": pre_submit_row_count,
        "durable_accepted_pre_submit_selection_model_input_complete": durable_complete,
        "durable_accepted_pre_submit_selection_model_input_candidate_count": int(
            (durable_pre_submit_evidence or {}).get("versioned_sized_accepted_candidate_count") or 0
        ),
        "durable_accepted_pre_submit_latest_strict_suffix_count": int(
            ((durable_pre_submit_evidence or {}).get("latest_strict_selection_model_input_suffix_evidence") or {})
            .get("latest_strict_suffix_count") or 0
        ),
        "durable_accepted_pre_submit_latest_strict_suffix_required_count": int(
            ((durable_pre_submit_evidence or {}).get("latest_strict_selection_model_input_suffix_evidence") or {})
            .get("minimum_required_strict_suffix_count")
            or MINIMUM_DURABLE_STRICT_SELECTION_MODEL_INPUT_SUFFIX
        ),
        "durable_accepted_pre_submit_latest_strict_suffix_proves_current_enforcement": bool(
            ((durable_pre_submit_evidence or {}).get("latest_strict_selection_model_input_suffix_evidence") or {})
            .get("latest_strict_suffix_proves_current_enforcement")
        ),
        "durable_accepted_pre_submit_historical_prefix_selection_model_input_gap_count": int(
            ((durable_pre_submit_evidence or {}).get("latest_strict_selection_model_input_suffix_evidence") or {})
            .get("historical_prefix_selection_model_input_gap_count") or 0
        ),
        "selection_attribution_scope": (
            "current strict pre-submit enforcement is authoritative; historical runtime rows created "
            "before strict selection-model-input attribution remain reported separately"
            if historical_gap_non_blocking else
            "runtime adaptive-capital rows and current pre-submit enforcement must both prove selection attribution"
        ),
        "row_count": row_count,
        "required_selection_field_coverage": required_selection_field_coverage,
        "complete_selection_model_input_count": int(evidence.get("complete_selection_model_input_count") or 0),
        "complete_selection_model_input_coverage": _coerce_float(
            evidence.get("complete_selection_model_input_coverage")
        ) or 0.0,
        "selection_model_input_missing_counts": evidence.get("selection_model_input_missing_counts") or {},
        "missing_selection_attribution_sample": evidence.get("missing_selection_attribution_sample") or [],
        "leverage_selection_model_input_coverage": leverage_coverage,
        "margin_mode_selection_model_input_coverage": margin_coverage,
        "hedge_budget_selection_model_input_coverage": hedge_coverage,
        "required_runtime_selection_model_input_coverage": 1.0,
        "selection_scope": (
            "runtime adaptive-capital rows must carry selected gross notional, allocated margin, "
            "leverage, margin mode, hedge budget, and model-input attribution for leverage, "
            "margin mode, and hedge-budget selection"
        ),
    }


def _capital_policy_version(row: dict[str, Any]) -> str | None:
    allocation = row.get("adaptive_allocation") if isinstance(row.get("adaptive_allocation"), dict) else {}
    value = _first_present(
        row.get("adaptive_capital_policy_version"),
        allocation.get("adaptive_capital_policy_version"),
    )
    return str(value) if value is not None else None


def _is_adaptive_capital_policy_row(row: dict[str, Any]) -> bool:
    return _capital_policy_version(row) == ADAPTIVE_CAPITAL_POLICY_VERSION


def _paper_intent_rows_from_payloads(active_payload: Any, held_payload: Any) -> list[dict[str, Any]]:
    return (
        _rows_with_source(active_payload, "rows", "v2:paper:intents")
        + _rows_with_source(held_payload, "rows", "v2:paper:intents_held_by_paper_fill_gate")
    )


def _paper_intent_rows_from_ledger(ledger_payload: Any) -> list[dict[str, Any]]:
    if not isinstance(ledger_payload, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key, source in (
        ("current_cycle_accepted", "v2:paper:ledger.current_cycle_accepted"),
        ("blocked", "v2:paper:ledger.blocked"),
        ("shadow_observations", "v2:paper:ledger.shadow_observations"),
        ("held_by_paper_fill_gate", "v2:paper:ledger.held_by_paper_fill_gate"),
    ):
        for row in _safe_rows(ledger_payload, key):
            row.setdefault("paper_intent_source", source)
            rows.append(row)
    return rows


def _counterfactual_symbol_timeframe_cell(row: dict[str, Any]) -> tuple[str, str] | None:
    symbol = _normalized_symbol(row)
    timeframe = str(_row_value(row, "timeframe") or row.get("timeframe") or "")
    if not symbol or not timeframe:
        return None
    return symbol, timeframe


def _counterfactual_observed_cells(rows: list[dict[str, Any]]) -> set[tuple[str, str]]:
    return {
        cell
        for row in rows
        for cell in [_counterfactual_symbol_timeframe_cell(row)]
        if cell is not None
    }


def _paper_ledger_accepted_counterfactual_rows(
    *,
    ledger_payload: dict[str, Any],
    base_source_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    accepted_source = "v2:paper:ledger.accepted"
    accepted_rows = _safe_rows(ledger_payload, "accepted")
    if not accepted_rows:
        accepted_source = "v2:paper:ledger.accepted_intents"
        accepted_rows = _safe_rows(ledger_payload, "accepted_intents")

    base_cells = _counterfactual_observed_cells(base_source_rows)
    rows: list[dict[str, Any]] = []
    excluded_reason_counts: dict[str, int] = {}

    def exclude(reason: str) -> None:
        excluded_reason_counts[reason] = excluded_reason_counts.get(reason, 0) + 1

    for accepted in accepted_rows:
        row = dict(accepted)
        if not _is_adaptive_capital_policy_row(row):
            exclude("NOT_ADAPTIVE_CAPITAL_POLICY_ROW")
            continue
        if not _is_sized_pre_submit_intent(row):
            exclude("NOT_SIZED_PRE_SUBMIT_INTENT")
            continue
        unsafe_reasons = _unsafe_reconciliation_reasons(row, require_paper_only_true=True)
        if unsafe_reasons:
            for reason in unsafe_reasons:
                exclude(reason)
            continue
        cell = _counterfactual_symbol_timeframe_cell(row)
        if base_cells and cell not in base_cells:
            exclude("OUTSIDE_CURRENT_SOURCE_SYMBOL_TIMEFRAME_CELL")
            continue
        row.setdefault("paper_intent_source", accepted_source)
        row.setdefault("counterfactual_source_kind", "paper_ledger_accepted")
        rows.append(row)

    return rows, {
        "source": accepted_source,
        "accepted_candidate_row_count": len(accepted_rows),
        "counterfactual_row_count": len(rows),
        "bounded_to_current_source_symbol_timeframe_cells": bool(base_cells),
        "current_source_symbol_timeframe_cell_count": len(base_cells),
        "excluded_row_count": len(accepted_rows) - len(rows),
        "excluded_reason_counts": {
            key: excluded_reason_counts[key]
            for key in sorted(excluded_reason_counts)
        },
        "status": "READY" if rows else "NO_COUNTERFACTUAL_DURABLE_ACCEPTED_ROWS",
    }


def _has_allocator_evidence(row: dict[str, Any]) -> bool:
    allocation = row.get("adaptive_allocation") if isinstance(row.get("adaptive_allocation"), dict) else {}
    return any(
        value is not None and value != ""
        for value in (
            row.get("allocator_decision"),
            allocation.get("allocator_decision"),
            row.get("allocation_id"),
            allocation.get("allocation_id"),
            row.get("paper_sizing_source"),
            row.get("paper_sizing_complete"),
        )
    )


def _sized_adaptive_pre_submit_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if _is_adaptive_capital_policy_row(row) and _is_sized_pre_submit_intent(row)
    ]


def _paper_intent_snapshot_accounting_complete(rows: list[dict[str, Any]]) -> bool:
    sized_rows = _sized_adaptive_pre_submit_rows(rows)
    if not sized_rows:
        return False
    return bool(
        _accounting_enforcement_evidence(
            sized_rows,
            source="active_or_held_pre_submit_paper_intents",
        ).get("complete")
    )


def _paper_intent_snapshot_selection_attribution_complete(rows: list[dict[str, Any]]) -> bool:
    sized_rows = _sized_adaptive_pre_submit_rows(rows)
    if not sized_rows:
        return False
    return _selection_model_input_evidence_complete(
        _adaptive_field_selection_evidence(sized_rows)
    )


def _paper_intent_snapshot_needs_retry(rows: list[dict[str, Any]]) -> bool:
    sized_rows = _sized_adaptive_pre_submit_rows(rows)
    return (
        not rows
        or (
            not any(_capital_policy_version(row) == ADAPTIVE_CAPITAL_POLICY_VERSION for row in rows)
            and any(_has_allocator_evidence(row) for row in rows)
        )
        or (
            bool(sized_rows)
            and (
                not _paper_intent_snapshot_accounting_complete(rows)
                or not _paper_intent_snapshot_selection_attribution_complete(rows)
            )
        )
    )


def _paper_intent_snapshot_epoch_ms(rows: list[dict[str, Any]]) -> int:
    timestamps = [
        parsed for row in rows
        for parsed in [
            _parse_epoch_ms(_first_present(
                row.get("generated_utc"),
                row.get("decision_time"),
                row.get("execution_time"),
                row.get("event_time"),
            ))
        ]
        if parsed is not None
    ]
    return max(timestamps, default=0)


def _paper_intent_snapshot_score(rows: list[dict[str, Any]]) -> tuple[int, ...]:
    versioned_count = sum(1 for row in rows if _is_adaptive_capital_policy_row(row))
    sized_rows = _sized_adaptive_pre_submit_rows(rows)
    sized_count = len(sized_rows)
    return (
        1 if rows else 0,
        1 if versioned_count else 0,
        _paper_intent_snapshot_epoch_ms(rows),
        1 if sized_count else 0,
        1 if _paper_intent_snapshot_accounting_complete(rows) else 0,
        1 if _paper_intent_snapshot_selection_attribution_complete(rows) else 0,
        sized_count,
        versioned_count,
        len(rows),
    )


def _select_best_paper_intent_snapshot(
    primary_rows: list[dict[str, Any]],
    fallback_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not fallback_rows:
        return primary_rows
    if not primary_rows:
        return fallback_rows
    return max(
        (primary_rows, fallback_rows),
        key=_paper_intent_snapshot_score,
    )


def _read_paper_intents_from_redis(
    client: Any | None,
    *,
    attempts: int = PAPER_INTENT_SNAPSHOT_RETRY_COUNT,
    retry_delay_seconds: float = PAPER_INTENT_SNAPSHOT_RETRY_SECONDS,
    fallback_ledger: Any | None = None,
) -> list[dict[str, Any]]:
    attempts = max(1, attempts)
    rows: list[dict[str, Any]] = []
    fallback_rows = _paper_intent_rows_from_ledger(fallback_ledger)
    best_rows = fallback_rows
    for attempt in range(attempts):
        active_payload = _redis_json(client, "v2:paper:intents") or []
        held_payload = _redis_json(client, "v2:paper:intents_held_by_paper_fill_gate") or []
        rows = _paper_intent_rows_from_payloads(active_payload, held_payload)
        best_rows = _select_best_paper_intent_snapshot(
            best_rows,
            _select_best_paper_intent_snapshot(rows, fallback_rows),
        )
        if not _paper_intent_snapshot_needs_retry(rows) or attempt == attempts - 1:
            return best_rows
        if retry_delay_seconds > 0.0:
            time.sleep(retry_delay_seconds)
    return best_rows


def _allocation_mapping(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("adaptive_allocation")
    return value if isinstance(value, dict) else {}


def _row_value(row: dict[str, Any], field: str) -> Any:
    allocation = _allocation_mapping(row)
    if field == "symbol":
        return _first_present(row.get("symbol"), allocation.get("symbol"))
    if field == "timeframe":
        return _first_present(row.get("timeframe"), allocation.get("timeframe"))
    if field == "side":
        return _first_present(row.get("side"), row.get("action"), allocation.get("action"))
    if field == "entry_price":
        return _first_present(row.get("entry_price"), row.get("fill_price"), row.get("price"))
    if field == "quantity":
        return _first_present(row.get("quantity"), row.get("target_quantity"), allocation.get("target_quantity"))
    if field == "gross_notional_usd":
        explicit = _first_present(
            row.get("gross_notional_usd"),
            row.get("notional"),
            row.get("notional_usdt"),
            allocation.get("gross_notional_usd"),
            allocation.get("target_notional_usdt"),
        )
        if explicit is not None:
            return explicit
        entry_price = _coerce_float(_row_value(row, "entry_price"))
        quantity = _coerce_float(_row_value(row, "quantity"))
        if entry_price is not None and quantity is not None:
            return entry_price * quantity
        return None
    return _first_present(row.get(field), allocation.get(field))


def _allocation_model_inputs(row: dict[str, Any]) -> dict[str, Any]:
    allocation = _allocation_mapping(row)
    value = allocation.get("model_inputs")
    return value if isinstance(value, dict) else {}


def _liquidation_buffer_minimum_evidence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    minimum = RiskEnvelope().min_liquidation_buffer_bps
    values = [
        value for value in (
            _coerce_float(_row_value(row, "liquidation_buffer_bps"))
            for row in rows
        )
        if value is not None
    ]
    verified_count = sum(1 for value in values if value >= minimum)
    below_minimum_count = sum(1 for value in values if value < minimum)
    return {
        "minimum_liquidation_buffer_bps": minimum,
        "candidate_count": len(rows),
        "liquidation_buffer_value_count": len(values),
        "liquidation_buffer_minimum_verified_count": verified_count,
        "liquidation_buffer_below_minimum_count": below_minimum_count,
        "liquidation_buffer_minimum_coverage": (
            round(verified_count / len(rows), 8)
            if rows else 0.0
        ),
        "minimum_liquidation_buffer_observed_bps": (
            round(min(values), 8) if values else None
        ),
        "status": (
            "PASSED"
            if rows and len(values) == len(rows) and below_minimum_count == 0
            else "NO_GO_LIQUIDATION_BUFFER_BELOW_MINIMUM"
            if below_minimum_count
            else "NO_GO_LIQUIDATION_BUFFER_MINIMUM_UNVERIFIED"
        ),
    }


def _allocator_calibration_status(
    *,
    rows: list[dict[str, Any]],
    generated_utc: str,
    current_intent_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    policy_rows = [row for row in rows if _is_adaptive_capital_policy_row(row)]

    def _numeric_values(source_rows: list[dict[str, Any]], *fields: str) -> list[float]:
        values: set[float] = set()
        for row in source_rows:
            allocation = _allocation_mapping(row)
            model_inputs = _allocation_model_inputs(row)
            for field in fields:
                value = _coerce_float(_first_present(
                    row.get(field),
                    allocation.get(field),
                    model_inputs.get(field),
                ))
                if value is not None:
                    values.add(round(value, 8))
        return sorted(values)

    def _string_value_counts(source_rows: list[dict[str, Any]], *fields: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in source_rows:
            allocation = _allocation_mapping(row)
            model_inputs = _allocation_model_inputs(row)
            value = _first_present(
                *(
                    candidate
                    for field in fields
                    for candidate in (
                        row.get(field),
                        allocation.get(field),
                        model_inputs.get(field),
                    )
                )
            )
            if value is None or value == "":
                continue
            key = str(value)
            counts[key] = counts.get(key, 0) + 1
        return {key: counts[key] for key in sorted(counts)}

    liquidity_adjustments = _numeric_values(policy_rows, "liquidity_adjustment")
    regime_adjustments = _numeric_values(policy_rows, "regime_adjustment")
    liquidity_scores = _numeric_values(policy_rows, "liquidity_score")
    regime_scores = _numeric_values(policy_rows, "regime_score")
    constant_liquidity_default = liquidity_adjustments == [1.0]
    constant_regime_default = regime_adjustments == [1.0]
    calibration_gaps: list[str] = []
    if not liquidity_adjustments:
        calibration_gaps.append("LIQUIDITY_ADJUSTMENT_MISSING")
    elif constant_liquidity_default and len(liquidity_scores) <= 1:
        calibration_gaps.append("LIQUIDITY_ADJUSTMENT_CONSTANT_AT_DEFAULT_1_0")
    if not regime_adjustments:
        calibration_gaps.append("REGIME_ADJUSTMENT_MISSING")
    elif constant_regime_default and len(regime_scores) <= 1:
        calibration_gaps.append("REGIME_ADJUSTMENT_CONSTANT_AT_DEFAULT_1_0")
    current_rows = current_intent_rows or []
    current_policy_rows = [row for row in current_rows if _is_adaptive_capital_policy_row(row)]
    current_liquidity_adjustments = _numeric_values(
        current_policy_rows,
        "liquidity_adjustment",
    )
    current_regime_adjustments = _numeric_values(
        current_policy_rows,
        "regime_adjustment",
    )
    current_liquidity_scores = _numeric_values(
        current_policy_rows,
        "liquidity_score",
        "allocator_liquidity_score",
    )
    current_regime_scores = _numeric_values(
        current_policy_rows,
        "regime_score",
        "allocator_regime_score",
    )
    liquidity_source_counts = _string_value_counts(
        policy_rows,
        "allocator_liquidity_score_source",
        "liquidity_score_source",
    )
    liquidity_reason_counts = _string_value_counts(
        policy_rows,
        "allocator_liquidity_score_reason",
        "liquidity_score_reason",
    )
    regime_source_counts = _string_value_counts(
        policy_rows,
        "allocator_regime_score_source",
        "regime_score_source",
    )
    regime_reason_counts = _string_value_counts(
        policy_rows,
        "allocator_regime_score_reason",
        "regime_score_reason",
    )
    current_liquidity_source_counts = _string_value_counts(
        current_policy_rows,
        "allocator_liquidity_score_source",
        "liquidity_score_source",
    )
    current_liquidity_reason_counts = _string_value_counts(
        current_policy_rows,
        "allocator_liquidity_score_reason",
        "liquidity_score_reason",
    )
    current_regime_source_counts = _string_value_counts(
        current_policy_rows,
        "allocator_regime_score_source",
        "regime_score_source",
    )
    current_regime_reason_counts = _string_value_counts(
        current_policy_rows,
        "allocator_regime_score_reason",
        "regime_score_reason",
    )

    def _has_non_default(values: list[float]) -> bool:
        return any(abs(value - 1.0) > 1e-9 for value in values)

    liquidity_calibration_observed = _has_non_default(
        sorted({*current_liquidity_adjustments, *current_liquidity_scores})
    )
    regime_calibration_observed = _has_non_default(
        sorted({*current_regime_adjustments, *current_regime_scores})
    )
    current_intent_calibration_observation = {
        "status": (
            "READY_CURRENT_INTENT_CALIBRATION_OBSERVED"
            if liquidity_calibration_observed and regime_calibration_observed
            else "NO_CURRENT_INTENT_CALIBRATION_OBSERVED"
        ),
        "scope": "current_active_or_held_paper_intents_including_allocator_blocked_rows",
        "current_intent_row_count": len(current_rows),
        "current_versioned_intent_row_count": len(current_policy_rows),
        "current_sized_intent_row_count": sum(
            1 for row in current_policy_rows if _is_sized_pre_submit_intent(row)
        ),
        "current_allocator_blocked_intent_count": sum(
            1 for row in current_policy_rows if _is_allocator_blocked_intent(row)
        ),
        "current_non_sized_or_blocked_intent_count": sum(
            1
            for row in current_policy_rows
            if _is_allocator_blocked_intent(row) or not _is_sized_pre_submit_intent(row)
        ),
        "liquidity_calibration_observed": liquidity_calibration_observed,
        "regime_calibration_observed": regime_calibration_observed,
        "liquidity_adjustment_unique_count": len(current_liquidity_adjustments),
        "liquidity_adjustment_values": current_liquidity_adjustments[:20],
        "liquidity_score_unique_count": len(current_liquidity_scores),
        "liquidity_score_values": current_liquidity_scores[:20],
        "liquidity_score_source_counts": current_liquidity_source_counts,
        "liquidity_score_reason_counts": current_liquidity_reason_counts,
        "regime_adjustment_unique_count": len(current_regime_adjustments),
        "regime_adjustment_values": current_regime_adjustments[:20],
        "regime_score_unique_count": len(current_regime_scores),
        "regime_score_values": current_regime_scores[:20],
        "regime_score_source_counts": current_regime_source_counts,
        "regime_score_reason_counts": current_regime_reason_counts,
        "counts_as_policy_outcome_calibration_gate": False,
        "blocked_or_zero_notional_rows_count_as_closed_outcome_evidence": False,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": "DOCUMENTED_INPUT_CALIBRATION_GAP" if calibration_gaps else "READY",
        "calibration_gap_reasons": calibration_gaps,
        "allocator_formula_source": "v2.backend.app.services.adaptive_capital_allocator.sizing_model",
        "liquidity_adjustment_formula": "clamp(liquidity_score, 0.0, 1.0)",
        "regime_adjustment_formula": "clamp(regime_score, 0.2, 1.25)",
        "policy_row_count": len(policy_rows),
        "liquidity_adjustment_unique_count": len(liquidity_adjustments),
        "liquidity_adjustment_values": liquidity_adjustments[:20],
        "liquidity_score_unique_count": len(liquidity_scores),
        "liquidity_score_values": liquidity_scores[:20],
        "liquidity_score_source_counts": liquidity_source_counts,
        "liquidity_score_reason_counts": liquidity_reason_counts,
        "regime_adjustment_unique_count": len(regime_adjustments),
        "regime_adjustment_values": regime_adjustments[:20],
        "regime_score_unique_count": len(regime_scores),
        "regime_score_values": regime_scores[:20],
        "regime_score_source_counts": regime_source_counts,
        "regime_score_reason_counts": regime_reason_counts,
        "constant_1_0_adjustments_are_documented": bool(calibration_gaps),
        "current_intent_calibration_observation": current_intent_calibration_observation,
        "calibration_scope": (
            "Allocator formulas are variable; runtime constant 1.0 evidence indicates "
            "missing/defaulted liquidity_score or regime_score calibration inputs, not a fixed sizing formula. "
            "Current intent observations are reported separately and do not satisfy the policy outcome gate."
        ),
    }


def _policy_activated_at_value(row: dict[str, Any]) -> Any:
    allocation = _allocation_mapping(row)
    return _first_present(
        row.get("policy_activated_at"),
        allocation.get("policy_activated_at"),
    )


def _funding_evidence_value(row: dict[str, Any], field: str) -> Any:
    allocation = _allocation_mapping(row)
    model_inputs = _allocation_model_inputs(row)
    oi_funding = row.get("oi_funding_context") if isinstance(row.get("oi_funding_context"), dict) else {}
    return _first_present(
        row.get(field),
        allocation.get(field),
        model_inputs.get(field),
        oi_funding.get(field),
    )


def _entry_time_ms(row: dict[str, Any]) -> int | None:
    return _parse_epoch_ms(_first_present(
        row.get("opened_at"),
        row.get("opened_utc"),
        row.get("opened_est"),
        row.get("entry_time"),
        row.get("entry_time_utc"),
        row.get("entry_price_utc"),
        row.get("fill_price_utc"),
        row.get("original_fill_utc"),
        _policy_activated_at_value(row),
    ))


def _funding_reconstruction_rate(row: dict[str, Any]) -> tuple[float | None, float | None, str | None]:
    rate = _coerce_float(_first_present(
        _funding_evidence_value(row, "funding_rate"),
        _funding_evidence_value(row, "last_funding_rate"),
        _funding_evidence_value(row, "next_funding_rate"),
        _funding_evidence_value(row, "expected_funding_rate"),
        _funding_evidence_value(row, "actual_funding_rate"),
    ))
    bps = _coerce_float(_first_present(
        _funding_evidence_value(row, "actual_funding_bps"),
        _funding_evidence_value(row, "expected_funding_bps"),
        _funding_evidence_value(row, "funding_bps"),
        _funding_evidence_value(row, "funding_rate_bps"),
    ))
    if rate is not None:
        return rate, rate * 10000.0, "FUNDING_RATE_RECONSTRUCTION"
    if bps is not None:
        return bps / 10000.0, bps, "FUNDING_BPS_RECONSTRUCTION"
    return None, None, None


def _funding_reconstruction_notional(row: dict[str, Any]) -> float | None:
    explicit = _coerce_float(_first_present(
        _funding_evidence_value(row, "funding_notional_usd"),
        row.get("closed_notional_usd"),
        row.get("gross_notional_usd"),
        row.get("notional"),
        row.get("notional_usdt"),
    ))
    if explicit is not None:
        return abs(explicit)
    quantity = _coerce_float(_first_present(
        row.get("closed_quantity"),
        row.get("quantity"),
        row.get("target_quantity"),
        _row_value(row, "quantity"),
    ))
    entry_price = _coerce_float(_row_value(row, "entry_price"))
    if quantity is None or entry_price is None:
        return None
    return abs(quantity * entry_price)


def _funding_pnl_reconstruction(row: dict[str, Any]) -> dict[str, Any]:
    funding_pnl = _coerce_float(_first_present(row.get("funding_pnl_usd"), row.get("funding_pnl")))
    rate, bps, source = _funding_reconstruction_rate(row)
    notional = _funding_reconstruction_notional(row)
    hold_seconds = _coerce_float(row.get("hold_time_seconds"))
    entry_ms = _entry_time_ms(row)
    exit_ms = _event_time_ms(row)
    if hold_seconds is None and entry_ms is not None and exit_ms is not None and exit_ms >= entry_ms:
        hold_seconds = (exit_ms - entry_ms) / 1000.0
    interval_seconds = _coerce_float(_funding_evidence_value(row, "funding_interval_seconds")) or 28800.0
    side = _directional_side(row)
    missing: list[str] = []
    if funding_pnl is not None:
        missing.append("FUNDING_PNL_ALREADY_PRESENT")
    if rate is None:
        missing.append("MISSING_FUNDING_RATE_OR_BPS")
    if notional is None or notional <= 0.0:
        missing.append("MISSING_FUNDING_NOTIONAL")
    if hold_seconds is None or hold_seconds < 0.0:
        missing.append("MISSING_HOLD_TIME")
    if interval_seconds <= 0.0:
        missing.append("INVALID_FUNDING_INTERVAL")
    if side not in {"long", "short"}:
        missing.append("MISSING_DIRECTIONAL_SIDE")
    reconstructable = (
        funding_pnl is None
        and rate is not None
        and notional is not None and notional > 0.0
        and hold_seconds is not None and hold_seconds >= 0.0
        and interval_seconds > 0.0
        and side in {"long", "short"}
    )
    side_multiplier = -1.0 if side == "long" else 1.0
    interval_count = (float(hold_seconds or 0.0) / interval_seconds) if interval_seconds > 0.0 else None
    reconstructed = (
        float(notional) * float(rate) * float(interval_count or 0.0) * side_multiplier
        if reconstructable else None
    )
    return {
        "reconstructable": reconstructable,
        "reconstructed_funding_pnl_usd": round(reconstructed, 8) if reconstructed is not None else None,
        "funding_reconstruction_source": source,
        "funding_reconstruction_missing_reasons": [
            reason for reason in missing if reason != "FUNDING_PNL_ALREADY_PRESENT"
        ],
        "funding_reconstruction_rate": rate,
        "funding_reconstruction_bps": bps,
        "funding_reconstruction_notional_usd": round(notional, 8) if notional is not None else None,
        "funding_reconstruction_hold_time_seconds": round(float(hold_seconds), 8) if hold_seconds is not None else None,
        "funding_reconstruction_interval_seconds": interval_seconds,
        "funding_reconstruction_interval_count": round(float(interval_count), 8) if interval_count is not None else None,
        "funding_reconstruction_side": side,
    }


def _funding_pnl_accounted(row: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    funding_pnl = _coerce_float(_first_present(row.get("funding_pnl_usd"), row.get("funding_pnl")))
    source = str(_first_present(row.get("funding_pnl_source"), row.get("funding_source"), "") or "")
    has_rate_or_bps = any(
        _coerce_float(_funding_evidence_value(row, field)) is not None
        for field in (
            "funding_rate",
            "last_funding_rate",
            "next_funding_rate",
            "funding_bps",
            "funding_rate_bps",
            "expected_funding_bps",
            "actual_funding_bps",
            "actual_funding_usd",
        )
    )
    source_accounts_for_funding = source not in {
        "",
        "MISSING_FUNDING_RATE",
        "MISSING_FUNDING_EVIDENCE",
        "NO_FUNDING_EVIDENCE",
    }
    accounted = funding_pnl is not None and (source_accounts_for_funding or has_rate_or_bps)
    return accounted, {
        "funding_pnl_accounting_version": _first_present(row.get("funding_pnl_accounting_version")),
        "funding_pnl_accounting_status": _first_present(row.get("funding_pnl_accounting_status")),
        "funding_pnl_usd": funding_pnl,
        "funding_pnl_source": source or None,
        "funding_rate": _coerce_float(_funding_evidence_value(row, "funding_rate")),
        "funding_bps": _coerce_float(_funding_evidence_value(row, "funding_bps")),
        "expected_funding_bps": _coerce_float(_funding_evidence_value(row, "expected_funding_bps")),
        "actual_funding_bps": _coerce_float(_funding_evidence_value(row, "actual_funding_bps")),
        "source_accounts_for_funding": source_accounts_for_funding,
        "has_rate_or_bps_evidence": has_rate_or_bps,
    }


def _policy_funding_sample_row(
    *,
    row: dict[str, Any],
    row_source: str,
    index: int,
    funding_evidence: dict[str, Any] | None = None,
    funding_reconstruction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    funding_evidence = funding_evidence or {}
    funding_reconstruction = funding_reconstruction or {}
    return {
        "index": index,
        "row_source": row_source,
        "symbol": _normalized_symbol(row),
        "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
        "side": _directional_side(row),
        "policy_activated_at": _policy_activated_at_value(row),
        "funding_pnl_usd": funding_evidence.get("funding_pnl_usd"),
        "funding_pnl_source": funding_evidence.get("funding_pnl_source"),
        "funding_rate": funding_evidence.get("funding_rate"),
        "funding_bps": funding_evidence.get("funding_bps"),
        "expected_funding_bps": funding_evidence.get("expected_funding_bps"),
        "actual_funding_bps": funding_evidence.get("actual_funding_bps"),
        "funding_pnl_accounting_version": funding_evidence.get("funding_pnl_accounting_version"),
        "funding_pnl_accounting_status": funding_evidence.get("funding_pnl_accounting_status"),
        "funding_pnl_reconstructable": funding_reconstruction.get("reconstructable"),
        "reconstructed_funding_pnl_usd": funding_reconstruction.get("reconstructed_funding_pnl_usd"),
        "funding_reconstruction_source": funding_reconstruction.get("funding_reconstruction_source"),
        "funding_reconstruction_missing_reasons": (
            funding_reconstruction.get("funding_reconstruction_missing_reasons")
        ),
    }


def _forward_funding_contract_status(
    *,
    accepted_policy_rows: list[dict[str, Any]],
    open_policy_rows: list[dict[str, Any]],
    generated_utc: str,
) -> dict[str, Any]:
    rows: list[tuple[str, dict[str, Any]]] = [
        *[("accepted_entry_fill", row) for row in accepted_policy_rows],
        *[("open_position", row) for row in open_policy_rows],
    ]
    missing_reason_counts: dict[str, int] = {}
    missing_sample: list[dict[str, Any]] = []
    ready_count = 0
    funding_rate_or_bps_count = 0
    policy_activated_at_count = 0
    for index, (row_source, row) in enumerate(rows):
        reasons: list[str] = []
        policy_activated_at = _policy_activated_at_value(row)
        if policy_activated_at in (None, ""):
            reasons.append("MISSING_POLICY_ACTIVATED_AT")
        else:
            policy_activated_at_count += 1
        rate, bps, source = _funding_reconstruction_rate(row)
        if rate is None and bps is None:
            reasons.append("MISSING_FUNDING_RATE_OR_BPS")
        else:
            funding_rate_or_bps_count += 1
        notional = _funding_reconstruction_notional(row)
        if notional is None or notional <= 0.0:
            reasons.append("MISSING_FUNDING_NOTIONAL")
        side = _directional_side(row)
        if side not in {"long", "short"}:
            reasons.append("MISSING_DIRECTIONAL_SIDE")
        if reasons:
            for reason in reasons:
                missing_reason_counts[reason] = missing_reason_counts.get(reason, 0) + 1
            if len(missing_sample) < 20:
                missing_sample.append({
                    "index": index,
                    "row_source": row_source,
                    "symbol": _normalized_symbol(row),
                    "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
                    "side": side,
                    "missing_reasons": reasons,
                    "policy_activated_at": policy_activated_at,
                    "funding_rate": rate,
                    "funding_bps": bps,
                    "funding_source": source,
                    "funding_notional_usd": round(notional, 8) if notional is not None else None,
                })
            continue
        ready_count += 1
    if not rows:
        status = "NO_FORWARD_POLICY_ENTRY_OR_OPEN_ROWS"
    elif ready_count == len(rows):
        status = "READY_FORWARD_FUNDING_ACCOUNTING_CONTRACT"
    else:
        status = "NO_GO_FORWARD_FUNDING_ACCOUNTING_CONTRACT_INCOMPLETE"
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": status,
        "scope": "accepted_entry_fills_and_open_positions_for_future_closed_outcomes",
        "contract_source": "v2.backend.app.services.paper_trade_management.outcomes.build_close_event",
        "forward_row_count": len(rows),
        "accepted_policy_entry_fill_count": len(accepted_policy_rows),
        "open_policy_position_count": len(open_policy_rows),
        "ready_forward_row_count": ready_count,
        "policy_activated_at_ready_count": policy_activated_at_count,
        "funding_rate_or_bps_ready_count": funding_rate_or_bps_count,
        "missing_reason_counts": {
            key: missing_reason_counts[key]
            for key in sorted(missing_reason_counts)
        },
        "missing_sample": missing_sample,
        "persisted_close_fields_required": [
            "funding_pnl_accounting_version",
            "funding_pnl_accounting_status",
            "funding_pnl_usd",
            "funding_pnl_source",
            "funding_rate",
            "funding_bps",
            "funding_interval_seconds",
            "funding_accrual_intervals",
            "funding_notional_usd",
            "funding_pnl_formula",
            "funding_pnl_side_sign",
        ],
        "funding_accounting_version": FUNDING_PNL_ACCOUNTING_VERSION,
        "funding_formula": FUNDING_PNL_ACCOUNTING_FORMULA,
        "counts_as_closed_outcome_funding_gate": False,
        "paper_only": True,
        "places_real_order": False,
    }


def _portfolio_order_counter_status(
    *,
    portfolio: dict[str, Any],
    generated_utc: str,
) -> dict[str, Any]:
    counters = portfolio.get("order_counters") if isinstance(portfolio.get("order_counters"), dict) else {}
    missing_fields = [
        field for field in NAMED_ORDER_COUNTER_FIELDS
        if _coerce_float(counters.get(field)) is None
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": "READY" if counters and not missing_fields else "MISSING_NAMED_ORDER_COUNTERS",
        "required_counter_fields": list(NAMED_ORDER_COUNTER_FIELDS),
        "present_counter_fields": [
            field for field in NAMED_ORDER_COUNTER_FIELDS
            if _coerce_float(counters.get(field)) is not None
        ],
        "missing_counter_fields": missing_fields,
        "order_counters": {
            key: counters.get(key)
            for key in NAMED_ORDER_COUNTER_FIELDS
            if key in counters
        },
        "order_counters_source": portfolio.get("order_counters_source"),
        "live_order_count": _coerce_float(counters.get("live_order_count")),
        "test_order_count": _coerce_float(counters.get("test_order_count")),
        "exchange_order_mutation_count": _coerce_float(counters.get("exchange_order_mutation_count")),
        "paper_only_counter_contract": True,
    }


def _policy_activation_funding_evidence_status(
    *,
    accepted_rows: list[dict[str, Any]],
    open_rows: list[dict[str, Any]],
    closed_rows: list[dict[str, Any]],
    portfolio: dict[str, Any],
    generated_utc: str,
) -> dict[str, Any]:
    accepted_policy_rows = [row for row in accepted_rows if _is_adaptive_capital_policy_row(row)]
    open_policy_rows = [row for row in open_rows if _is_adaptive_capital_policy_row(row)]
    closed_policy_rows = [row for row in closed_rows if _is_adaptive_capital_policy_row(row)]
    policy_rows: list[tuple[str, dict[str, Any]]] = [
        *[("accepted_entry_fill", row) for row in accepted_policy_rows],
        *[("open_position", row) for row in open_policy_rows],
        *[("closed_outcome", row) for row in closed_policy_rows],
    ]
    policy_missing_sample: list[dict[str, Any]] = []
    policy_present_count = 0
    for index, (row_source, row) in enumerate(policy_rows):
        if _policy_activated_at_value(row) not in (None, ""):
            policy_present_count += 1
            continue
        if len(policy_missing_sample) < 20:
            policy_missing_sample.append(_policy_funding_sample_row(
                row=row,
                row_source=row_source,
                index=index,
            ))

    funding_accounted_count = 0
    funding_unaccounted_sample: list[dict[str, Any]] = []
    funding_source_counts: dict[str, int] = {}
    funding_reconstruction_missing_reason_counts: dict[str, int] = {}
    funding_reconstruction_sample: list[dict[str, Any]] = []
    funding_accounting_version_counts: dict[str, int] = {}
    funding_accounting_status_counts: dict[str, int] = {}
    funding_nonzero_count = 0
    funding_reconstructable_count = 0
    funding_reconstructed_nonzero_count = 0
    reconstructed_funding_pnl_total = 0.0
    for index, row in enumerate(closed_policy_rows):
        accounted, funding_evidence = _funding_pnl_accounted(row)
        funding_reconstruction = _funding_pnl_reconstruction(row)
        source_key = str(funding_evidence.get("funding_pnl_source") or "__missing__")
        funding_source_counts[source_key] = funding_source_counts.get(source_key, 0) + 1
        version_key = str(funding_evidence.get("funding_pnl_accounting_version") or "__missing__")
        status_key = str(funding_evidence.get("funding_pnl_accounting_status") or "__missing__")
        funding_accounting_version_counts[version_key] = funding_accounting_version_counts.get(version_key, 0) + 1
        funding_accounting_status_counts[status_key] = funding_accounting_status_counts.get(status_key, 0) + 1
        funding_pnl = funding_evidence.get("funding_pnl_usd")
        if isinstance(funding_pnl, (float, int)) and not isinstance(funding_pnl, bool) and abs(float(funding_pnl)) > 0.0:
            funding_nonzero_count += 1
        if funding_reconstruction.get("reconstructable") is True:
            funding_reconstructable_count += 1
            reconstructed = _coerce_float(funding_reconstruction.get("reconstructed_funding_pnl_usd")) or 0.0
            reconstructed_funding_pnl_total += reconstructed
            if abs(reconstructed) > 0.0:
                funding_reconstructed_nonzero_count += 1
            if len(funding_reconstruction_sample) < 20:
                funding_reconstruction_sample.append(_policy_funding_sample_row(
                    row=row,
                    row_source="closed_outcome",
                    index=index,
                    funding_evidence=funding_evidence,
                    funding_reconstruction=funding_reconstruction,
                ))
        else:
            for reason in funding_reconstruction.get("funding_reconstruction_missing_reasons") or []:
                reason_key = str(reason)
                funding_reconstruction_missing_reason_counts[reason_key] = (
                    funding_reconstruction_missing_reason_counts.get(reason_key, 0) + 1
                )
        if accounted:
            funding_accounted_count += 1
            continue
        if len(funding_unaccounted_sample) < 20:
            funding_unaccounted_sample.append(_policy_funding_sample_row(
                row=row,
                row_source="closed_outcome",
                index=index,
                funding_evidence=funding_evidence,
                funding_reconstruction=funding_reconstruction,
            ))

    forward_contract_status = _forward_funding_contract_status(
        accepted_policy_rows=accepted_policy_rows,
        open_policy_rows=open_policy_rows,
        generated_utc=generated_utc,
    )
    current_forward_funding_accounting_enforcement_complete = (
        forward_contract_status.get("status") == "READY_FORWARD_FUNDING_ACCOUNTING_CONTRACT"
        and int(forward_contract_status.get("forward_row_count") or 0) > 0
        and int(forward_contract_status.get("ready_forward_row_count") or 0)
        == int(forward_contract_status.get("forward_row_count") or 0)
    )
    funding_unaccounted_count = len(closed_policy_rows) - funding_accounted_count
    funding_unaccounted_unreconstructable_count = max(
        0,
        funding_unaccounted_count - funding_reconstructable_count,
    )
    historical_closed_outcome_funding_gap_non_blocking = (
        bool(closed_policy_rows)
        and funding_unaccounted_count > 0
        and funding_reconstructable_count == 0
        and current_forward_funding_accounting_enforcement_complete
        and policy_present_count == len(policy_rows)
    )

    blocker_reasons: list[str] = []
    if not policy_rows:
        blocker_reasons.append("NO_ADAPTIVE_CAPITAL_POLICY_ROWS_FOR_POLICY_FUNDING_AUDIT")
    elif policy_present_count < len(policy_rows):
        blocker_reasons.append("MISSING_POLICY_ACTIVATED_AT_ON_ENTRY_OR_OUTCOME_ROWS")
    if not closed_policy_rows:
        blocker_reasons.append("NO_CLOSED_ADAPTIVE_CAPITAL_OUTCOMES_FOR_FUNDING_PNL_AUDIT")
    elif funding_unaccounted_count > 0 and not historical_closed_outcome_funding_gap_non_blocking:
        blocker_reasons.append("FUNDING_PNL_UNACCOUNTED_OR_SOURCE_MISSING")

    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": "PASSED" if not blocker_reasons else "NO_GO_POLICY_ACTIVATION_FUNDING_EVIDENCE_INCOMPLETE",
        "blocker_reasons": blocker_reasons,
        "accepted_policy_entry_fill_count": len(accepted_policy_rows),
        "open_policy_position_count": len(open_policy_rows),
        "closed_policy_outcome_count": len(closed_policy_rows),
        "policy_activation_audit_row_count": len(policy_rows),
        "policy_activated_at_present_count": policy_present_count,
        "policy_activated_at_missing_count": len(policy_rows) - policy_present_count,
        "policy_activated_at_missing_sample": policy_missing_sample,
        "funding_pnl_audit_closed_outcome_count": len(closed_policy_rows),
        "funding_pnl_accounted_count": funding_accounted_count,
        "funding_pnl_unaccounted_count": funding_unaccounted_count,
        "funding_pnl_unaccounted_reconstructable_count": funding_reconstructable_count,
        "funding_pnl_unaccounted_unreconstructable_count": funding_unaccounted_unreconstructable_count,
        "funding_pnl_nonzero_count": funding_nonzero_count,
        "current_forward_funding_accounting_enforcement_complete": (
            current_forward_funding_accounting_enforcement_complete
        ),
        "current_forward_funding_accounting_source": forward_contract_status.get("contract_source"),
        "historical_closed_outcome_funding_gap_non_blocking": (
            historical_closed_outcome_funding_gap_non_blocking
        ),
        "closed_outcome_funding_accounting_status": (
            "PASSED_PERSISTED_CLOSED_OUTCOME_FUNDING"
            if funding_unaccounted_count == 0 and bool(closed_policy_rows) else
            "PASSED_CURRENT_FORWARD_CONTRACT_WITH_HISTORICAL_UNRECONSTRUCTABLE_GAP"
            if historical_closed_outcome_funding_gap_non_blocking else
            "NO_GO_CLOSED_OUTCOME_FUNDING_ACCOUNTING_INCOMPLETE"
        ),
        "funding_pnl_source_counts": {
            key: funding_source_counts[key]
            for key in sorted(funding_source_counts)
        },
        "funding_pnl_accounting_version_counts": {
            key: funding_accounting_version_counts[key]
            for key in sorted(funding_accounting_version_counts)
        },
        "funding_pnl_accounting_status_counts": {
            key: funding_accounting_status_counts[key]
            for key in sorted(funding_accounting_status_counts)
        },
        "funding_pnl_unaccounted_sample": funding_unaccounted_sample,
        "funding_pnl_reconstruction_status": {
            "status": (
                "READY_RECONSTRUCTABLE_FUNDING_PNL_DIAGNOSTIC"
                if funding_reconstructable_count > 0 else
                "NO_RECONSTRUCTABLE_FUNDING_PNL_DIAGNOSTIC"
            ),
            "scope": (
                "read_only_diagnostic_only_not_a_substitute_for_persisted_funding_pnl_usd"
            ),
            "reconstructable_closed_outcome_count": funding_reconstructable_count,
            "unreconstructable_closed_outcome_count": (
                len(closed_policy_rows) - funding_reconstructable_count
            ),
            "reconstructed_funding_pnl_total_usd": round(reconstructed_funding_pnl_total, 8),
            "reconstructed_funding_pnl_nonzero_count": funding_reconstructed_nonzero_count,
            "reconstruction_missing_reason_counts": {
                key: funding_reconstruction_missing_reason_counts[key]
                for key in sorted(funding_reconstruction_missing_reason_counts)
            },
            "reconstruction_sample": funding_reconstruction_sample,
            "formula": FUNDING_PNL_ACCOUNTING_FORMULA,
            "funding_accounting_version": FUNDING_PNL_ACCOUNTING_VERSION,
            "side_sign": {"long": -1.0, "short": 1.0},
            "counts_as_accounted_funding_pnl": False,
        },
        "forward_funding_accounting_contract_status": forward_contract_status,
        "portfolio_order_counter_status": _portfolio_order_counter_status(
            portfolio=portfolio,
            generated_utc=generated_utc,
        ),
        "audit_scope": (
            "policy_activated_at must be present on accepted entry fills, open positions, "
            "and closed outcomes; funding PnL must be explicitly accounted on closed "
            "adaptive-capital outcomes using a funding source or rate/bps evidence"
        ),
        "paper_only": True,
        "places_real_order": False,
    }


def _strict_a_grade_acquisition_burn_down(
    *,
    generated_utc: str,
    minimum_required_count: int,
    counterfactual_replay_progress: dict[str, Any],
    counterfactual_next_evidence_gaps: dict[str, Any],
    a_grade_blocker_analysis: dict[str, Any],
    counterfactual_evidence_acquisition_status: dict[str, Any],
    market_cost_evidence_coverage_status: dict[str, Any],
    near_a_grade_market_cost_evidence_coverage_status: dict[str, Any],
) -> dict[str, Any]:
    historical_count = int(
        _coerce_float(counterfactual_replay_progress.get("historical_a_grade_signal_count")) or 0
    )
    event_time_valid_count = int(
        _coerce_float(counterfactual_replay_progress.get("event_time_valid_candidate_count")) or 0
    )
    best_configuration_count = int(
        _coerce_float(counterfactual_replay_progress.get("best_configuration_count")) or 0
    )
    if (
        historical_count >= minimum_required_count
        and event_time_valid_count >= minimum_required_count
        and best_configuration_count >= minimum_required_count
    ):
        status = "PASSED"
    elif historical_count <= 0:
        status = "NO_GO_NO_STRICT_A_GRADE_SIGNALS"
    elif event_time_valid_count <= 0:
        status = "NO_GO_STRICT_A_GRADE_TEMPORAL_EVIDENCE_MISSING"
    elif best_configuration_count <= 0:
        status = "NO_GO_STRICT_A_GRADE_FEASIBLE_CONFIGURATION_MISSING"
    else:
        status = "NO_GO_STRICT_A_GRADE_ACQUISITION_INCOMPLETE"
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": status,
        "minimum_required_a_grade_replay_evidence_count": minimum_required_count,
        "strict_confidence_threshold": A_GRADE_CONFIDENCE_THRESHOLD,
        "strict_after_cost_edge_bps_min_exclusive": 0.0,
        "historical_a_grade_signal_count": historical_count,
        "a_grade_before_temporal_count": int(
            _coerce_float(counterfactual_replay_progress.get("a_grade_before_temporal_count")) or 0
        ),
        "event_time_valid_a_grade_count": event_time_valid_count,
        "best_configuration_count": best_configuration_count,
        "a_grade_signal_gap_count": max(0, minimum_required_count - historical_count),
        "event_time_valid_a_grade_gap_count": max(0, minimum_required_count - event_time_valid_count),
        "best_configuration_gap_count": max(0, minimum_required_count - best_configuration_count),
        "closest_confidence_gap_to_a_grade": (
            counterfactual_replay_progress.get("closest_confidence_gap_to_a_grade")
        ),
        "closest_edge_gap_to_positive_bps": (
            counterfactual_replay_progress.get("closest_edge_gap_to_positive_bps")
        ),
        "closest_candidate": counterfactual_replay_progress.get("closest_near_a_grade"),
        "not_a_grade_reason_counts": a_grade_blocker_analysis.get("not_a_grade_reason_counts") or {},
        "positive_edge_below_confidence_count": (
            a_grade_blocker_analysis.get("positive_edge_below_confidence_count")
        ),
        "high_confidence_missing_or_non_positive_edge_count": (
            a_grade_blocker_analysis.get("high_confidence_missing_or_non_positive_edge_count")
        ),
        "high_confidence_positive_edge_allocator_blocked_count": (
            a_grade_blocker_analysis.get("high_confidence_positive_edge_allocator_blocked_count")
        ),
        "strict_a_grade_candidate_count": (
            counterfactual_evidence_acquisition_status.get("strict_a_grade_candidate_count")
        ),
        "strict_a_grade_market_cost_complete_count": (
            market_cost_evidence_coverage_status.get("complete_candidate_count")
        ),
        "strict_a_grade_market_cost_candidate_count": (
            market_cost_evidence_coverage_status.get("candidate_row_count")
        ),
        "strict_a_grade_market_cost_status": market_cost_evidence_coverage_status.get("status"),
        "near_a_grade_candidate_count": (
            counterfactual_evidence_acquisition_status.get("near_a_grade_candidate_count")
        ),
        "near_a_grade_event_time_valid_candidate_count": (
            counterfactual_next_evidence_gaps.get("near_a_grade_event_time_valid_candidate_count")
        ),
        "near_a_grade_market_cost_complete_count": (
            counterfactual_evidence_acquisition_status.get("near_a_grade_market_cost_complete_count")
        ),
        "near_a_grade_market_cost_incomplete_count": (
            counterfactual_evidence_acquisition_status.get("near_a_grade_market_cost_incomplete_count")
        ),
        "near_a_grade_market_cost_ready_if_confidence_improves_count": (
            counterfactual_evidence_acquisition_status.get(
                "near_a_grade_market_cost_ready_if_confidence_improves_count"
            )
        ),
        "near_a_grade_market_cost_status": near_a_grade_market_cost_evidence_coverage_status.get("status"),
        "near_a_grade_missing_market_cost_reason_counts": (
            near_a_grade_market_cost_evidence_coverage_status.get("missing_reason_counts") or {}
        ),
        "near_a_grade_market_cost_pit_reject_reason_counts": (
            near_a_grade_market_cost_evidence_coverage_status.get("pit_reject_reason_counts") or {}
        ),
        "near_a_grade_market_cost_ready_sample": (
            counterfactual_evidence_acquisition_status.get("near_a_grade_market_cost_ready_sample") or []
        )[:10],
        "near_a_grade_market_cost_capture_required_sample": (
            counterfactual_evidence_acquisition_status.get(
                "near_a_grade_market_cost_capture_required_sample"
            ) or []
        )[:10],
        "required_next_evidence": list(counterfactual_next_evidence_gaps.get("required_next_evidence") or []),
        "strict_a_grade_gate_relaxed": False,
        "counts_as_counterfactual_a_grade_gate": False,
        "notes": (
            "Read-only acquisition burn-down only. It does not relax or satisfy the strict "
            "A-grade counterfactual replay pass gate."
        ),
    }


def _external_audit_blocker_burn_down(
    *,
    generated_utc: str,
    capital_productivity: dict[str, Any],
    adaptive_policy_status: dict[str, Any],
    parity_status: dict[str, Any],
) -> dict[str, Any]:
    policy_funding = adaptive_policy_status.get("policy_activation_funding_evidence_status") or {}
    funding_reconstruction = policy_funding.get("funding_pnl_reconstruction_status") or {}
    allocator_calibration = adaptive_policy_status.get("allocator_calibration_status") or {}
    current_calibration = allocator_calibration.get("current_intent_calibration_observation") or {}
    order_counters = policy_funding.get("portfolio_order_counter_status") or {}
    liquidation_buffer_evidence = parity_status.get("effective_liquidation_buffer_minimum_evidence") or {}
    profit_factor_burn_down = capital_productivity.get("profit_factor_burn_down") or {}
    calibration_status = str(allocator_calibration.get("status") or "")
    calibration_fix_or_document_satisfied = calibration_status in {
        "READY",
        "DOCUMENTED_INPUT_CALIBRATION_GAP",
    }
    calibration_fix_or_document_status = (
        "READY_POLICY_OUTCOME_CALIBRATION_OBSERVED"
        if calibration_status == "READY"
        else "DOCUMENTED_INPUT_CALIBRATION_GAP_NOT_POLICY_READY"
        if calibration_status == "DOCUMENTED_INPUT_CALIBRATION_GAP"
        else "ACTION_REQUIRED"
    )
    required_actions: list[str] = []
    if _coerce_float(capital_productivity.get("profit_factor_numeric")) is None or (
        _coerce_float(capital_productivity.get("profit_factor_numeric")) or 0.0
    ) < MINIMUM_POST_ALLOCATOR_PROFIT_FACTOR:
        required_actions.append("RAISE_POST_POLICY_PROFIT_FACTOR_ABOVE_OPERATOR_MINIMUM")
    if (
        int(_coerce_float(capital_productivity.get("post_allocator_closed_outcome_count")) or 0)
        < MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES
    ):
        required_actions.append("ACCUMULATE_AT_LEAST_300_POST_POLICY_CLOSED_OUTCOMES")
    if int(_coerce_float(policy_funding.get("policy_activated_at_missing_count")) or 0) > 0:
        required_actions.append("PERSIST_POLICY_ACTIVATED_AT_ON_ENTRY_FILL_AND_OUTCOME_ROWS")
    historical_funding_gap_non_blocking = (
        policy_funding.get("historical_closed_outcome_funding_gap_non_blocking") is True
    )
    if (
        int(_coerce_float(policy_funding.get("funding_pnl_unaccounted_count")) or 0) > 0
        and not historical_funding_gap_non_blocking
    ):
        required_actions.append("PERSIST_FUNDING_PNL_ACCRUAL_ON_CLOSED_OUTCOMES")
    if not calibration_fix_or_document_satisfied:
        required_actions.append("FIX_OR_DOCUMENT_LIQUIDITY_AND_REGIME_CALIBRATION_INPUTS")
    if order_counters.get("status") != "READY":
        required_actions.append("ADD_EXPLICIT_NAMED_ORDER_COUNTERS_TO_PORTFOLIO_STATE")
    if parity_status.get("effective_liquidation_buffer_minimum_verified") is not True:
        required_actions.append("VERIFY_LIQUIDATION_BUFFER_MINIMUM_ON_PRE_SUBMIT_EVIDENCE")
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": "PASSED" if not required_actions else "NO_GO_EXTERNAL_AUDIT_BLOCKERS_REMAIN",
        "source": "operator_external_audit_2026_06_21",
        "required_actions_remaining": required_actions,
        "profit_factor": {
            "status": capital_productivity.get("post_allocator_performance_status"),
            "profit_factor": capital_productivity.get("profit_factor"),
            "profit_factor_numeric": capital_productivity.get("profit_factor_numeric"),
            "minimum_required_profit_factor": capital_productivity.get("minimum_required_profit_factor"),
            "profit_factor_gap_to_minimum": capital_productivity.get("profit_factor_gap_to_minimum"),
            "burn_down": profit_factor_burn_down,
            "cohort_closed_outcome_count": capital_productivity.get("post_allocator_closed_outcome_count"),
            "minimum_required_closed_outcomes": MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES,
        },
        "policy_activated_at": {
            "present_count": policy_funding.get("policy_activated_at_present_count"),
            "missing_count": policy_funding.get("policy_activated_at_missing_count"),
            "audit_row_count": policy_funding.get("policy_activation_audit_row_count"),
            "missing_sample": policy_funding.get("policy_activated_at_missing_sample") or [],
        },
        "funding_pnl": {
            "accounted_count": policy_funding.get("funding_pnl_accounted_count"),
            "unaccounted_count": policy_funding.get("funding_pnl_unaccounted_count"),
            "nonzero_count": policy_funding.get("funding_pnl_nonzero_count"),
            "source_counts": policy_funding.get("funding_pnl_source_counts") or {},
            "accounting_version_counts": (
                policy_funding.get("funding_pnl_accounting_version_counts") or {}
            ),
            "accounting_status_counts": (
                policy_funding.get("funding_pnl_accounting_status_counts") or {}
            ),
            "reconstruction_status": funding_reconstruction,
            "read_only_reconstruction_counts_as_gate": (
                funding_reconstruction.get("counts_as_accounted_funding_pnl") is True
            ),
            "current_forward_funding_accounting_enforcement_complete": (
                policy_funding.get("current_forward_funding_accounting_enforcement_complete")
            ),
            "historical_closed_outcome_funding_gap_non_blocking": (
                historical_funding_gap_non_blocking
            ),
            "closed_outcome_funding_accounting_status": (
                policy_funding.get("closed_outcome_funding_accounting_status")
            ),
        },
        "liquidity_regime_calibration": {
            "status": allocator_calibration.get("status"),
            "fix_or_document_action_status": calibration_fix_or_document_status,
            "fix_or_document_action_remaining": not calibration_fix_or_document_satisfied,
            "policy_outcome_calibration_ready": calibration_status == "READY",
            "calibration_gap_reasons": allocator_calibration.get("calibration_gap_reasons") or [],
            "policy_liquidity_adjustment_values": allocator_calibration.get("liquidity_adjustment_values") or [],
            "policy_regime_adjustment_values": allocator_calibration.get("regime_adjustment_values") or [],
            "policy_liquidity_score_source_counts": allocator_calibration.get("liquidity_score_source_counts") or {},
            "policy_liquidity_score_reason_counts": allocator_calibration.get("liquidity_score_reason_counts") or {},
            "policy_regime_score_source_counts": allocator_calibration.get("regime_score_source_counts") or {},
            "policy_regime_score_reason_counts": allocator_calibration.get("regime_score_reason_counts") or {},
            "current_intent_status": current_calibration.get("status"),
            "current_intent_liquidity_adjustment_values": current_calibration.get("liquidity_adjustment_values") or [],
            "current_intent_regime_adjustment_values": current_calibration.get("regime_adjustment_values") or [],
            "current_intent_liquidity_score_source_counts": current_calibration.get("liquidity_score_source_counts") or {},
            "current_intent_liquidity_score_reason_counts": current_calibration.get("liquidity_score_reason_counts") or {},
            "current_intent_regime_score_source_counts": current_calibration.get("regime_score_source_counts") or {},
            "current_intent_regime_score_reason_counts": current_calibration.get("regime_score_reason_counts") or {},
            "counts_as_policy_outcome_calibration_gate": (
                current_calibration.get("counts_as_policy_outcome_calibration_gate") is True
            ),
            "required_next_evidence": (
                []
                if calibration_status == "READY"
                else ["ACCUMULATE_POLICY_OUTCOMES_WITH_NON_DEFAULT_LIQUIDITY_AND_REGIME_ADJUSTMENTS"]
            ),
        },
        "named_order_counters": order_counters,
        "liquidation_buffer_minimum": {
            "verified": parity_status.get("effective_liquidation_buffer_minimum_verified") is True,
            "evidence": liquidation_buffer_evidence,
        },
        "counts_as_additional_pass_gate": False,
        "paper_only": True,
        "places_real_order": False,
    }


def _row_field_present(row: dict[str, Any], field: str) -> bool:
    value = _row_value(row, field)
    return value is not None and value != ""


MARKET_COST_EVIDENCE_REQUIREMENTS: dict[str, dict[str, Any]] = {
    "spread_bps": {
        "missing_reason": "MISSING_ACTUAL_SPREAD",
        "accepted_fields": (
            "actual_observed_spread_entry_bps",
            "actual_spread_bps",
            "entry_spread_bps",
            "spread_bps",
        ),
    },
    "slippage_bps": {
        "missing_reason": "MISSING_SLIPPAGE",
        "accepted_fields": (
            "actual_observed_slippage_bps",
            "actual_slippage_bps",
            "realized_slippage_bps",
            "expected_slippage_bps",
            "slippage_bps",
            "estimated_slippage_bps",
            "slippage_estimate_bps",
            "actual_slippage_usd",
            "expected_slippage_usd",
        ),
    },
    "fee_bps": {
        "missing_reason": "MISSING_FEES",
        "accepted_fields": (
            "actual_fee_bps",
            "fee_bps",
            "taker_fee_bps",
            "expected_fee_bps",
            "estimated_fee_bps",
            "fee_estimate_bps",
            "commission_bps",
            "fee_rate",
            "taker_fee_rate",
            "expected_fee_rate",
            "estimated_fee_rate",
            "commission_rate",
            "actual_fees_usd",
            "expected_fees_usd",
        ),
    },
    "funding_bps": {
        "missing_reason": "MISSING_FUNDING",
        "accepted_fields": (
            "actual_funding_bps",
            "funding_bps",
            "funding_rate_bps",
            "expected_funding_bps",
            "estimated_funding_bps",
            "funding_estimate_bps",
            "funding_rate",
            "expected_funding_rate",
            "actual_funding_rate",
            "actual_funding_usd",
            "expected_funding_usd",
        ),
    },
    "market_depth_usd": {
        "missing_reason": "MISSING_MARKET_DEPTH",
        "accepted_fields": (
            "market_depth_usd",
            "orderbook_depth_usd",
            "entry_orderbook_depth_usd",
            "depth_usd",
            "depth_usdt",
            "depth_notional_usd",
            "available_depth_usd",
            "one_percent_depth_usd",
            "depth_1pct_usd",
            "depth_50bps_usd",
            "depth_25bps_usd",
            "top_of_book_depth_usd",
        ),
        "positive_required": True,
        "level_fields": ("asks", "bids", "ask_levels", "bid_levels"),
    },
}


def _market_cost_capture_required_fields(
    missing_reasons: list[str],
) -> dict[str, dict[str, Any]]:
    missing_reason_set = set(missing_reasons)
    required: dict[str, dict[str, Any]] = {}
    for label, requirement in MARKET_COST_EVIDENCE_REQUIREMENTS.items():
        reason = str(requirement["missing_reason"])
        if reason not in missing_reason_set:
            continue
        required[reason] = {
            "canonical_requirement": label,
            "accepted_fields": list(requirement["accepted_fields"]),
            "level_fields": list(requirement.get("level_fields") or ()),
            "positive_required": bool(requirement.get("positive_required")),
        }
    return required


def _market_cost_capture_request_sample_row(
    *,
    row: dict[str, Any],
    source_kind: str,
    row_missing: list[str],
    row_sources: dict[str, str],
) -> dict[str, Any]:
    lineage = row.get("lineage_ids") if isinstance(row.get("lineage_ids"), dict) else {}
    source_lineage = (
        dict(row.get("market_cost_evidence_source_lineage"))
        if isinstance(row.get("market_cost_evidence_source_lineage"), dict)
        else {}
    )
    return {
        "symbol": _normalized_symbol(row),
        "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
        "side": _directional_side(row),
        "source_kind": source_kind,
        "signal_id": _first_present(
            row.get("signal_id"),
            row.get("source_signal_id"),
            row.get("entry_signal_id"),
            lineage.get("signal_id"),
        ),
        "prediction_id": _first_present(
            row.get("prediction_id"),
            row.get("source_prediction_id"),
            row.get("entry_prediction_id"),
            lineage.get("prediction_id"),
            lineage.get("trainer_prediction_id"),
        ),
        "feature_snapshot_id": _decision_feature_snapshot_id(row),
        "decision_time": _first_present(
            row.get("decision_time"),
            row.get("decision_time_est"),
            row.get("generated_at"),
            row.get("generated_utc"),
            row.get("generated_est"),
            row.get("available_at"),
        ),
        "available_at": row.get("available_at"),
        "generated_at": _first_present(
            row.get("generated_at"),
            row.get("generated_utc"),
            row.get("generated_est"),
        ),
        "feature_cutoff": row.get("feature_cutoff"),
        "source_redis_key": _first_present(
            row.get("source_redis_key"),
            row.get("paper_intent_source"),
        ),
        "confidence": _coerce_float(
            _first_present(row.get("confidence_calibrated"), row.get("confidence"))
        ),
        "after_cost_edge_bps": _expected_edge_bps(row),
        "missing_market_cost_evidence": row_missing,
        "present_market_cost_evidence_fields": row_sources,
        "market_cost_evidence_pit_reject_reasons": sorted([
            str(reason)
            for reason in (row.get("market_cost_evidence_pit_reject_reasons") or [])
            if reason
        ]),
        "market_cost_evidence_source_lineage": source_lineage,
        "required_capture_fields": _market_cost_capture_required_fields(row_missing),
    }


def _counterfactual_source_kind(row: dict[str, Any]) -> str:
    explicit = str(row.get("counterfactual_source_kind") or row.get("source_kind") or "").strip()
    if explicit:
        return explicit
    source = str(_first_present(row.get("source_redis_key"), row.get("paper_intent_source")) or "")
    if source.startswith("v2:signals:paper:"):
        return "paper_signal"
    if source.startswith("v2:prediction:"):
        return "prediction"
    if source.startswith("v2:paper:intents"):
        return "paper_intent"
    if source.startswith("v2:paper:ledger"):
        return "paper_ledger"
    if row.get("paper_exit_policy_version") or row.get("trade_id"):
        return "paper_ledger"
    return "__unspecified__"


def _nested_market_contexts(row: dict[str, Any]) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    for key in (
        "market_microstructure",
        "microstructure_context",
        "orderbook_context",
        "liquidity_context",
        "depth_context",
        "market_cost_evidence",
    ):
        value = row.get(key)
        if isinstance(value, dict):
            contexts.append(value)
    allocation = _allocation_mapping(row)
    for key in ("market_microstructure", "orderbook_context", "market_cost_evidence", "model_inputs"):
        value = allocation.get(key)
        if isinstance(value, dict):
            contexts.append(value)
    top_level_model_inputs = row.get("model_inputs")
    if isinstance(top_level_model_inputs, dict):
        contexts.append(top_level_model_inputs)
    return contexts


def _market_evidence_field(row: dict[str, Any], fields: tuple[str, ...], *, positive_required: bool = False) -> str | None:
    contexts = _nested_market_contexts(row)
    for field in fields:
        candidates = [_row_value(row, field)]
        candidates.extend(context.get(field) for context in contexts)
        for value in candidates:
            numeric = _coerce_float(value)
            if numeric is not None:
                if positive_required and numeric <= 0.0:
                    continue
                return field
            if not positive_required and value not in {None, ""}:
                return field
    return None


def _has_orderbook_levels(row: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    contexts = _nested_market_contexts(row)
    for field in fields:
        candidates = [row.get(field), *[context.get(field) for context in contexts]]
        for value in candidates:
            if isinstance(value, list) and value:
                return field
    return None


def _is_counterfactual_market_cost_candidate(row: dict[str, Any], *, confidence_threshold: float) -> bool:
    confidence = _coerce_float(_first_present(row.get("confidence_calibrated"), row.get("confidence"))) or 0.0
    edge = _expected_edge_bps(row) or 0.0
    decision = str(row.get("allocator_decision") or row.get("decision") or "")
    return (
        _directional_side(row) in {"long", "short"}
        and confidence >= confidence_threshold
        and edge > 0.0
        and not decision.startswith("BLOCK_")
    )


def _market_cost_evidence_coverage_status(
    rows: list[dict[str, Any]],
    *,
    confidence_threshold: float,
    scope: str,
    limit: int = 10,
) -> dict[str, Any]:
    candidates = [
        row for row in rows
        if _is_counterfactual_market_cost_candidate(row, confidence_threshold=confidence_threshold)
    ]
    complete_count = 0
    missing_reason_counts: dict[str, int] = {}
    field_present_counts = {key: 0 for key in MARKET_COST_EVIDENCE_REQUIREMENTS}
    source_kind_counts: dict[str, int] = {}
    complete_by_source_kind: dict[str, int] = {}
    pit_reject_reason_counts: dict[str, int] = {}
    sample: list[dict[str, Any]] = []
    complete_sample: list[dict[str, Any]] = []

    for row in candidates:
        source_kind = _counterfactual_source_kind(row)
        source_kind_counts[source_kind] = source_kind_counts.get(source_kind, 0) + 1
        row_missing: list[str] = []
        row_sources: dict[str, str] = {}
        for label, requirement in MARKET_COST_EVIDENCE_REQUIREMENTS.items():
            field = _market_evidence_field(
                row,
                requirement["accepted_fields"],
                positive_required=bool(requirement.get("positive_required")),
            )
            if field is None and requirement.get("level_fields"):
                field = _has_orderbook_levels(row, requirement["level_fields"])
            if field is None:
                reason = str(requirement["missing_reason"])
                row_missing.append(reason)
                missing_reason_counts[reason] = missing_reason_counts.get(reason, 0) + 1
            else:
                field_present_counts[label] += 1
                row_sources[label] = field
        for reason in row.get("market_cost_evidence_pit_reject_reasons") or []:
            if reason:
                text = str(reason)
                pit_reject_reason_counts[text] = pit_reject_reason_counts.get(text, 0) + 1
        if not row_missing:
            complete_count += 1
            complete_by_source_kind[source_kind] = complete_by_source_kind.get(source_kind, 0) + 1
            if len(complete_sample) < limit:
                complete_sample.append(_market_cost_capture_request_sample_row(
                    row=row,
                    source_kind=source_kind,
                    row_missing=[],
                    row_sources=row_sources,
                ))
            continue
        if len(sample) < limit:
            sample.append(_market_cost_capture_request_sample_row(
                row=row,
                source_kind=source_kind,
                row_missing=row_missing,
                row_sources=row_sources,
            ))

    candidate_count = len(candidates)
    coverage = complete_count / candidate_count if candidate_count else 0.0
    return {
        "status": (
            "PASSED" if candidate_count > 0 and complete_count == candidate_count else
            "NO_CANDIDATES" if candidate_count == 0 else
            "NO_GO_MARKET_COST_EVIDENCE_INCOMPLETE"
        ),
        "scope": scope,
        "source_row_count": len(rows),
        "candidate_row_count": candidate_count,
        "complete_candidate_count": complete_count,
        "incomplete_candidate_count": candidate_count - complete_count,
        "complete_candidate_coverage": round(coverage, 8),
        "confidence_threshold": confidence_threshold,
        "required_evidence": {
            key: {
                "missing_reason": str(value["missing_reason"]),
                "accepted_fields": list(value["accepted_fields"]),
            }
            for key, value in MARKET_COST_EVIDENCE_REQUIREMENTS.items()
        },
        "field_present_counts": field_present_counts,
        "missing_reason_counts": {key: missing_reason_counts[key] for key in sorted(missing_reason_counts)},
        "source_kind_counts": {key: source_kind_counts[key] for key in sorted(source_kind_counts)},
        "complete_by_source_kind": {
            key: complete_by_source_kind[key] for key in sorted(complete_by_source_kind)
        },
        "pit_reject_reason_counts": {
            key: pit_reject_reason_counts[key] for key in sorted(pit_reject_reason_counts)
        },
        "complete_candidate_sample": complete_sample,
        "complete_candidate_evidence_sample": complete_sample,
        "incomplete_candidate_sample": sample,
        "incomplete_candidate_capture_request_sample": sample,
        "requirement": "explicit spread, market depth, fees, slippage, and funding evidence is required before replay can choose a feasible configuration",
    }


def _counterfactual_evidence_acquisition_status(
    *,
    sweep: dict[str, Any],
    a_grade_blocker_analysis: dict[str, Any],
    market_cost_evidence_coverage_status: dict[str, Any],
    near_a_grade_market_cost_evidence_coverage_status: dict[str, Any],
) -> dict[str, Any]:
    strict_candidate_count = int(sweep.get("a_grade_before_temporal_count") or 0)
    strict_best_configuration_count = int(sweep.get("best_configuration_count") or 0)
    strict_market_candidate_count = int(
        market_cost_evidence_coverage_status.get("candidate_row_count") or 0
    )
    strict_market_complete_count = int(
        market_cost_evidence_coverage_status.get("complete_candidate_count") or 0
    )
    near_candidate_count = int(
        near_a_grade_market_cost_evidence_coverage_status.get("candidate_row_count") or 0
    )
    near_complete_count = int(
        near_a_grade_market_cost_evidence_coverage_status.get("complete_candidate_count") or 0
    )
    near_incomplete_count = int(
        near_a_grade_market_cost_evidence_coverage_status.get("incomplete_candidate_count") or 0
    )
    positive_edge_below_confidence = int(
        a_grade_blocker_analysis.get("positive_edge_below_confidence_count") or 0
    )
    source_coverage = sweep.get("source_coverage") or {}
    source_coverage_status = source_coverage.get("source_coverage_status")

    blocker_reasons: list[str] = []
    required_next_evidence: list[str] = []
    if source_coverage_status not in {"PASSED", None}:
        blocker_reasons.append("COUNTERFACTUAL_SOURCE_COVERAGE_INCOMPLETE")
        required_next_evidence.append("COMPLETE_REQUIRED_SYMBOL_TIMEFRAME_SOURCE_COVERAGE")
    if strict_candidate_count <= 0:
        blocker_reasons.append("NO_STRICT_A_GRADE_CANDIDATE")
        required_next_evidence.append(
            "PRODUCE_A_GRADE_SIGNAL_WITH_CONFIDENCE_AND_POSITIVE_AFTER_COST_EDGE"
        )
    if positive_edge_below_confidence > 0:
        blocker_reasons.append("POSITIVE_EDGE_BELOW_CONFIDENCE_THRESHOLD")
    if strict_market_candidate_count > strict_market_complete_count:
        blocker_reasons.append("STRICT_A_GRADE_MARKET_COST_CAPTURE_INCOMPLETE")
        required_next_evidence.append("CAPTURE_EXPLICIT_ENTRY_MARKET_COST_FIELDS_AT_DECISION_TIME")
    if strict_candidate_count <= 0 and near_incomplete_count > 0:
        blocker_reasons.append("NEAR_A_GRADE_MARKET_COST_CAPTURE_INCOMPLETE")
        if "CAPTURE_EXPLICIT_ENTRY_MARKET_COST_FIELDS_AT_DECISION_TIME" not in required_next_evidence:
            required_next_evidence.append("CAPTURE_EXPLICIT_ENTRY_MARKET_COST_FIELDS_AT_DECISION_TIME")
    if strict_candidate_count > 0 and strict_best_configuration_count < strict_candidate_count:
        blocker_reasons.append("A_GRADE_FEASIBLE_CONFIGURATION_INCOMPLETE")
        required_next_evidence.append("GENERATE_FEASIBLE_COUNTERFACTUAL_CONFIGURATION_WITH_DEPTH_AND_COSTS")

    if sweep.get("status") == "PASSED":
        status = "PASSED"
    elif strict_candidate_count <= 0 and near_complete_count > 0:
        status = "WAITING_FOR_A_GRADE_CONFIDENCE_WITH_MARKET_COST_READY"
    elif strict_candidate_count <= 0 and near_candidate_count > 0:
        status = "NO_GO_A_GRADE_CONFIDENCE_AND_MARKET_COST_CAPTURE_REQUIRED"
    elif strict_candidate_count <= 0:
        status = "NO_GO_A_GRADE_CONFIDENCE_REQUIRED"
    elif strict_market_candidate_count > strict_market_complete_count:
        status = "NO_GO_A_GRADE_MARKET_COST_CAPTURE_REQUIRED"
    elif strict_best_configuration_count < strict_candidate_count:
        status = "NO_GO_A_GRADE_FEASIBLE_CONFIGURATION_REQUIRED"
    else:
        status = "NO_GO_COUNTERFACTUAL_EVIDENCE_ACQUISITION_INCOMPLETE"

    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "status": status,
        "strict_a_grade_gate_relaxed": False,
        "strict_confidence_threshold": A_GRADE_CONFIDENCE_THRESHOLD,
        "near_a_grade_diagnostic_confidence_threshold": NEAR_A_GRADE_REPLAY_CONFIDENCE_THRESHOLD,
        "blocker_reasons": blocker_reasons,
        "required_next_evidence": list(dict.fromkeys(required_next_evidence)),
        "strict_a_grade_candidate_count": strict_candidate_count,
        "strict_event_time_valid_candidate_count": int(sweep.get("event_time_valid_candidate_count") or 0),
        "strict_best_configuration_count": strict_best_configuration_count,
        "strict_market_cost_candidate_count": strict_market_candidate_count,
        "strict_market_cost_complete_count": strict_market_complete_count,
        "strict_market_cost_incomplete_count": max(0, strict_market_candidate_count - strict_market_complete_count),
        "near_a_grade_candidate_count": near_candidate_count,
        "near_a_grade_market_cost_complete_count": near_complete_count,
        "near_a_grade_market_cost_incomplete_count": near_incomplete_count,
        "near_a_grade_market_cost_ready_if_confidence_improves_count": near_complete_count,
        "positive_edge_below_confidence_count": positive_edge_below_confidence,
        "near_a_grade_missing_market_cost_reason_counts": (
            near_a_grade_market_cost_evidence_coverage_status.get("missing_reason_counts") or {}
        ),
        "near_a_grade_market_cost_pit_reject_reason_counts": (
            near_a_grade_market_cost_evidence_coverage_status.get("pit_reject_reason_counts") or {}
        ),
        "strict_market_cost_capture_required_sample": (
            market_cost_evidence_coverage_status.get("incomplete_candidate_capture_request_sample") or []
        )[:10],
        "near_a_grade_market_cost_ready_sample": (
            near_a_grade_market_cost_evidence_coverage_status.get("complete_candidate_sample") or []
        )[:10],
        "near_a_grade_market_cost_capture_required_sample": (
            near_a_grade_market_cost_evidence_coverage_status.get("incomplete_candidate_capture_request_sample") or []
        )[:10],
        "positive_edge_below_confidence_sample": (
            a_grade_blocker_analysis.get("positive_edge_below_confidence_sample") or []
        )[:10],
        "notes": (
            "This block is acquisition guidance only. Near-A-grade rows do not satisfy the strict "
            "A-grade counterfactual pass gate unless they later meet the configured confidence threshold."
        ),
    }


def _positive_row_float(row: dict[str, Any], field: str) -> bool:
    value = _coerce_float(_row_value(row, field))
    return value is not None and value > 0.0


def _truthy(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_epoch_ms(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        if parsed != parsed or parsed in (float("inf"), float("-inf")):
            return None
        return int(parsed * 1000) if abs(parsed) < 10_000_000_000 else int(parsed)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            parsed = float(stripped)
        except ValueError:
            dt_value = _parse_utc(stripped)
            return int(dt_value.timestamp() * 1000) if dt_value else None
        return int(parsed * 1000) if abs(parsed) < 10_000_000_000 else int(parsed)
    return None


def _event_time_ms(row: dict[str, Any]) -> int | None:
    return _parse_epoch_ms(_first_present(
        row.get("closed_at"),
        row.get("exit_time"),
        row.get("exit_time_utc"),
        row.get("exit_price_utc"),
        row.get("path_telemetry_event_end_time"),
        row.get("path_telemetry_last_candle_close_time"),
        row.get("filled_at"),
        row.get("execution_time"),
        row.get("decision_time"),
        row.get("generated_at"),
        row.get("generated_utc"),
        row.get("event_time"),
        row.get("available_at"),
    ))


def _iso_from_ms(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _trade_outcome_pnl(row: dict[str, Any]) -> float | None:
    return _coerce_float(_first_present(
        row.get("realized_pnl_usd"),
        row.get("realized_pnl_usdt"),
        row.get("paper_pnl_usd"),
        row.get("pnl_usd"),
        row.get("outcome_pnl_usd"),
        row.get("outcome_after_cost_usd"),
    ))


def _pnl_history_status(
    *,
    closed_trades: list[dict[str, Any]],
    generated_utc: str,
) -> dict[str, Any]:
    generated_ms = _parse_epoch_ms(generated_utc)
    timestamped_rows: list[tuple[int, dict[str, Any]]] = []
    untimestamped = 0
    for row in closed_trades:
        event_ms = _event_time_ms(row)
        if event_ms is None:
            untimestamped += 1
            continue
        if generated_ms is not None and event_ms > generated_ms:
            untimestamped += 1
            continue
        timestamped_rows.append((event_ms, row))

    windows: list[dict[str, Any]] = []
    for label, seconds in PNL_HISTORY_WINDOWS:
        cutoff_ms = None if generated_ms is None else generated_ms - seconds * 1000
        rows = [
            row for event_ms, row in timestamped_rows
            if cutoff_ms is None or event_ms >= cutoff_ms
        ]
        pnl_values = [_trade_outcome_pnl(row) or 0.0 for row in rows]
        wins = sum(1 for value in pnl_values if value > 0.0)
        losses = sum(1 for value in pnl_values if value < 0.0)
        gross_profit = sum(value for value in pnl_values if value > 0.0)
        gross_loss = abs(sum(value for value in pnl_values if value < 0.0))
        window_event_ms = [_event_time_ms(row) for row in rows]
        window_event_ms = [value for value in window_event_ms if value is not None]
        windows.append({
            "window": label,
            "lookback_seconds": seconds,
            "realized_pnl_usd": round(sum(pnl_values), 8),
            "closed_trade_count": len(rows),
            "winning_trade_count": wins,
            "losing_trade_count": losses,
            "win_rate": round(wins / len(rows), 8) if rows else None,
            "profit_factor": (
                round(gross_profit / gross_loss, 8)
                if gross_loss > 0.0 else None if gross_profit <= 0.0 else "inf"
            ),
            "first_event_time": _iso_from_ms(min(window_event_ms) if window_event_ms else None),
            "last_event_time": _iso_from_ms(max(window_event_ms) if window_event_ms else None),
        })

    timestamp_coverage = len(timestamped_rows) / len(closed_trades) if closed_trades else 0.0
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": (
            "READY" if timestamped_rows else
            "NO_TIMESTAMPED_CLOSED_TRADE_EVIDENCE" if closed_trades else
            "NO_CLOSED_TRADE_EVIDENCE"
        ),
        "source": "v2:paper:ledger.closed_trades",
        "timestamp_policy": "uses closed_at/exit_time/execution_time/decision_time/generated_at/event_time; future timestamps are excluded",
        "closed_trade_count": len(closed_trades),
        "timestamped_closed_trade_count": len(timestamped_rows),
        "untimestamped_or_future_closed_trade_count": untimestamped,
        "timestamp_coverage": round(timestamp_coverage, 8),
        "windows": windows,
    }


def _directional_action(row: dict[str, Any]) -> str | None:
    raw = str(_first_present(
        row.get("side"),
        row.get("action"),
        row.get("selected_action"),
        row.get("top_action"),
        row.get("prediction"),
        row.get("signal"),
    ) or "").lower()
    if "short" in raw or raw in {"sell", "bearish"}:
        return "short"
    if "long" in raw or raw in {"buy", "bullish"}:
        return "long"
    return None


def _row_identity(row: dict[str, Any]) -> str:
    return str(_first_present(
        row.get("signal_id"),
        row.get("entry_signal_id"),
        row.get("exit_signal_id"),
        row.get("prediction_id"),
        row.get("entry_prediction_id"),
        row.get("exit_prediction_id"),
        row.get("paper_intent_id"),
        row.get("paper_fill_intent_id"),
        row.get("close_id"),
        row.get("trade_id"),
        row.get("execution_id"),
        row.get("source_redis_key"),
        f"{_normalized_symbol(row)}:{_row_value(row, 'timeframe') or 'UNKNOWN'}:{_event_time_ms(row) or 'unknown'}",
    ))


def _signal_prediction_accuracy_status(
    *,
    rows: list[dict[str, Any]],
    generated_utc: str,
) -> dict[str, Any]:
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        deduped.setdefault(_row_identity(row), row)

    source_rows = list(deduped.values())
    symbols = sorted({_normalized_symbol(row) for row in source_rows if _normalized_symbol(row) != "UNKNOWN"})
    timeframes = list(SIGNAL_ACCURACY_TIMEFRAMES)
    cell_map: dict[tuple[str, str], dict[str, Any]] = {}
    for symbol in symbols:
        for timeframe in timeframes:
            cell_map[(symbol, timeframe)] = {
                "symbol": symbol,
                "timeframe": timeframe,
                "signal_count": 0,
                "prediction_count": 0,
                "evaluated_count": 0,
                "correct_count": 0,
                "incorrect_count": 0,
                "flat_count": 0,
                "realized_pnl_usd": 0.0,
                "status": "NO_SOURCE_ROWS",
            }

    unevaluated_count = 0
    non_directional_count = 0
    evaluated_pnl = 0.0
    latest_event_ms: int | None = None
    for row in source_rows:
        symbol = _normalized_symbol(row)
        timeframe = str(_row_value(row, "timeframe") or row.get("timeframe") or "UNKNOWN")
        if not symbol or symbol == "UNKNOWN" or timeframe == "UNKNOWN":
            unevaluated_count += 1
            continue
        if timeframe not in timeframes:
            timeframes.append(timeframe)
        cell = cell_map.setdefault((symbol, timeframe), {
            "symbol": symbol,
            "timeframe": timeframe,
            "signal_count": 0,
            "prediction_count": 0,
            "evaluated_count": 0,
            "correct_count": 0,
            "incorrect_count": 0,
            "flat_count": 0,
            "realized_pnl_usd": 0.0,
            "status": "NO_SOURCE_ROWS",
        })
        if (
            row.get("signal_id")
            or row.get("entry_signal_id")
            or row.get("exit_signal_id")
            or "v2:signals:paper:" in str(row.get("source_redis_key") or "")
        ):
            cell["signal_count"] += 1
        if (
            row.get("prediction_id")
            or row.get("entry_prediction_id")
            or row.get("exit_prediction_id")
            or "v2:prediction:" in str(row.get("source_redis_key") or "")
        ):
            cell["prediction_count"] += 1
        if not any((
            row.get("signal_id"),
            row.get("entry_signal_id"),
            row.get("exit_signal_id"),
            row.get("prediction_id"),
            row.get("entry_prediction_id"),
            row.get("exit_prediction_id"),
        )):
            cell["signal_count"] += 1

        direction = _directional_action(row)
        pnl_value = _trade_outcome_pnl(row)
        if direction is None:
            non_directional_count += 1
            unevaluated_count += 1
            if cell["status"] != "EVALUATED":
                cell["status"] = "NO_DIRECTIONAL_ACTION_EVIDENCE"
            continue
        if pnl_value is None:
            unevaluated_count += 1
            if cell["status"] == "NO_SOURCE_ROWS":
                cell["status"] = "NO_EVALUATED_OUTCOMES"
            continue
        cell["evaluated_count"] += 1
        cell["realized_pnl_usd"] += pnl_value
        evaluated_pnl += pnl_value
        event_ms = _event_time_ms(row)
        if event_ms is not None:
            latest_event_ms = max(latest_event_ms or event_ms, event_ms)
        if pnl_value > 0.0:
            cell["correct_count"] += 1
        elif pnl_value < 0.0:
            cell["incorrect_count"] += 1
        else:
            cell["flat_count"] += 1
        cell["status"] = "EVALUATED"

    cells: list[dict[str, Any]] = []
    total_evaluated = 0
    total_correct = 0
    total_incorrect = 0
    total_flat = 0
    for key in sorted(cell_map):
        cell = dict(cell_map[key])
        evaluated = int(cell["evaluated_count"])
        correct = int(cell["correct_count"])
        incorrect = int(cell["incorrect_count"])
        flat = int(cell["flat_count"])
        total_evaluated += evaluated
        total_correct += correct
        total_incorrect += incorrect
        total_flat += flat
        cell["realized_pnl_usd"] = round(float(cell["realized_pnl_usd"]), 8)
        cell["accuracy"] = round(correct / evaluated, 8) if evaluated else None
        if cell["status"] == "NO_SOURCE_ROWS" and (cell["signal_count"] or cell["prediction_count"]):
            cell["status"] = "NO_EVALUATED_OUTCOMES"
        cells.append(cell)

    timeframe_order = list(dict.fromkeys([*SIGNAL_ACCURACY_TIMEFRAMES, *timeframes]))
    by_timeframe_map: dict[str, dict[str, Any]] = {
        timeframe: {
            "timeframe": timeframe,
            "symbol_timeframe_cell_count": 0,
            "source_symbol_timeframe_cell_count": 0,
            "evaluated_symbol_timeframe_cell_count": 0,
            "signal_count": 0,
            "prediction_count": 0,
            "evaluated_count": 0,
            "correct_count": 0,
            "incorrect_count": 0,
            "flat_count": 0,
            "realized_pnl_usd": 0.0,
        }
        for timeframe in timeframe_order
    }
    for cell in cells:
        timeframe = str(cell["timeframe"])
        aggregate = by_timeframe_map.setdefault(timeframe, {
            "timeframe": timeframe,
            "symbol_timeframe_cell_count": 0,
            "source_symbol_timeframe_cell_count": 0,
            "evaluated_symbol_timeframe_cell_count": 0,
            "signal_count": 0,
            "prediction_count": 0,
            "evaluated_count": 0,
            "correct_count": 0,
            "incorrect_count": 0,
            "flat_count": 0,
            "realized_pnl_usd": 0.0,
        })
        aggregate["symbol_timeframe_cell_count"] += 1
        if int(cell["signal_count"]) > 0 or int(cell["prediction_count"]) > 0:
            aggregate["source_symbol_timeframe_cell_count"] += 1
        if int(cell["evaluated_count"]) > 0:
            aggregate["evaluated_symbol_timeframe_cell_count"] += 1
        aggregate["signal_count"] += int(cell["signal_count"])
        aggregate["prediction_count"] += int(cell["prediction_count"])
        aggregate["evaluated_count"] += int(cell["evaluated_count"])
        aggregate["correct_count"] += int(cell["correct_count"])
        aggregate["incorrect_count"] += int(cell["incorrect_count"])
        aggregate["flat_count"] += int(cell["flat_count"])
        aggregate["realized_pnl_usd"] += float(cell["realized_pnl_usd"])

    by_timeframe: list[dict[str, Any]] = []
    for timeframe in timeframe_order:
        aggregate = dict(by_timeframe_map[timeframe])
        evaluated = int(aggregate["evaluated_count"])
        correct = int(aggregate["correct_count"])
        aggregate["accuracy"] = round(correct / evaluated, 8) if evaluated else None
        aggregate["realized_pnl_usd"] = round(float(aggregate["realized_pnl_usd"]), 8)
        aggregate["status"] = (
            "EVALUATED" if evaluated > 0 else
            "NO_EVALUATED_OUTCOMES" if int(aggregate["source_symbol_timeframe_cell_count"]) > 0 else
            "NO_SOURCE_ROWS"
        )
        by_timeframe.append(aggregate)

    by_symbol_map: dict[str, dict[str, Any]] = {
        symbol: {
            "symbol": symbol,
            "symbol_timeframe_cell_count": 0,
            "source_symbol_timeframe_cell_count": 0,
            "evaluated_symbol_timeframe_cell_count": 0,
            "signal_count": 0,
            "prediction_count": 0,
            "evaluated_count": 0,
            "correct_count": 0,
            "incorrect_count": 0,
            "flat_count": 0,
            "realized_pnl_usd": 0.0,
        }
        for symbol in symbols
    }
    for cell in cells:
        symbol = str(cell["symbol"])
        aggregate = by_symbol_map.setdefault(symbol, {
            "symbol": symbol,
            "symbol_timeframe_cell_count": 0,
            "source_symbol_timeframe_cell_count": 0,
            "evaluated_symbol_timeframe_cell_count": 0,
            "signal_count": 0,
            "prediction_count": 0,
            "evaluated_count": 0,
            "correct_count": 0,
            "incorrect_count": 0,
            "flat_count": 0,
            "realized_pnl_usd": 0.0,
        })
        aggregate["symbol_timeframe_cell_count"] += 1
        if int(cell["signal_count"]) > 0 or int(cell["prediction_count"]) > 0:
            aggregate["source_symbol_timeframe_cell_count"] += 1
        if int(cell["evaluated_count"]) > 0:
            aggregate["evaluated_symbol_timeframe_cell_count"] += 1
        aggregate["signal_count"] += int(cell["signal_count"])
        aggregate["prediction_count"] += int(cell["prediction_count"])
        aggregate["evaluated_count"] += int(cell["evaluated_count"])
        aggregate["correct_count"] += int(cell["correct_count"])
        aggregate["incorrect_count"] += int(cell["incorrect_count"])
        aggregate["flat_count"] += int(cell["flat_count"])
        aggregate["realized_pnl_usd"] += float(cell["realized_pnl_usd"])

    by_symbol: list[dict[str, Any]] = []
    for symbol in symbols:
        aggregate = dict(by_symbol_map[symbol])
        evaluated = int(aggregate["evaluated_count"])
        correct = int(aggregate["correct_count"])
        aggregate["accuracy"] = round(correct / evaluated, 8) if evaluated else None
        aggregate["realized_pnl_usd"] = round(float(aggregate["realized_pnl_usd"]), 8)
        aggregate["status"] = (
            "EVALUATED" if evaluated > 0 else
            "NO_EVALUATED_OUTCOMES" if int(aggregate["source_symbol_timeframe_cell_count"]) > 0 else
            "NO_SOURCE_ROWS"
        )
        by_symbol.append(aggregate)

    required_cell_count = len(symbols) * len(SIGNAL_ACCURACY_TIMEFRAMES)
    evaluated_cell_count = sum(1 for cell in cells if int(cell["evaluated_count"]) > 0)
    required_cells_without_evaluated_outcomes = max(required_cell_count - evaluated_cell_count, 0)

    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": (
            "READY" if total_evaluated > 0 else
            "NO_EVALUATED_OUTCOME_EVIDENCE" if source_rows else
            "NO_SIGNAL_OR_PREDICTION_ROWS"
        ),
        "source": "v2:signals:paper + v2:paper:intents + v2:prediction:* + closed paper outcomes",
        "accuracy_definition": "directional row is correct when the realized after-cost paper PnL for that row is positive; unevaluated rows are excluded from accuracy",
        "required_timeframes": list(SIGNAL_ACCURACY_TIMEFRAMES),
        "timeframes": timeframe_order,
        "timeframe_count": len(timeframe_order),
        "symbol_universe": symbols,
        "symbol_universe_count": len(symbols),
        "required_symbol_timeframe_cell_count": required_cell_count,
        "symbol_timeframe_cell_count": len(cells),
        "evaluated_symbol_timeframe_cell_count": evaluated_cell_count,
        "required_symbol_timeframe_cells_without_evaluated_outcomes_count": required_cells_without_evaluated_outcomes,
        "missing_evaluated_symbol_timeframe_cell_count": required_cells_without_evaluated_outcomes,
        "source_row_count": len(source_rows),
        "evaluated_row_count": total_evaluated,
        "unevaluated_row_count": unevaluated_count,
        "non_directional_row_count": non_directional_count,
        "correct_count": total_correct,
        "incorrect_count": total_incorrect,
        "flat_count": total_flat,
        "overall_accuracy": round(total_correct / total_evaluated, 8) if total_evaluated else None,
        "evaluated_realized_pnl_usd": round(evaluated_pnl, 8),
        "latest_evaluated_event_time": _iso_from_ms(latest_event_ms),
        "by_timeframe": by_timeframe,
        "by_symbol": by_symbol,
        "by_symbol_timeframe": cells,
        "sample_evaluated_rows": [
            {
                "symbol": _normalized_symbol(row),
                "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
                "direction": _directional_action(row),
                "realized_pnl_usd": _trade_outcome_pnl(row),
                "signal_id": _first_present(row.get("signal_id"), row.get("entry_signal_id"), row.get("exit_signal_id")),
                "prediction_id": _first_present(row.get("prediction_id"), row.get("entry_prediction_id"), row.get("exit_prediction_id")),
            }
            for row in source_rows
            if _directional_action(row) is not None and _trade_outcome_pnl(row) is not None
        ][:20],
    }


def _dashboard_web_status(
    *,
    capital_productivity: dict[str, Any],
    pnl_history_status: dict[str, Any],
    signal_prediction_accuracy_status: dict[str, Any],
    generated_utc: str,
) -> dict[str, Any]:
    required_pnl_windows = [label for label, _seconds in PNL_HISTORY_WINDOWS]
    published_pnl_windows = [
        str(row.get("window"))
        for row in (pnl_history_status.get("windows") or [])
        if isinstance(row, dict) and row.get("window")
    ]
    missing_pnl_windows = [
        label for label in required_pnl_windows
        if label not in set(published_pnl_windows)
    ]

    required_timeframes = list(SIGNAL_ACCURACY_TIMEFRAMES)
    published_timeframes = [
        str(value)
        for value in signal_prediction_accuracy_status.get("timeframes") or []
        if value
    ]
    missing_timeframes = [
        timeframe for timeframe in required_timeframes
        if timeframe not in set(published_timeframes)
    ]
    required_cell_count = int(
        signal_prediction_accuracy_status.get("required_symbol_timeframe_cell_count") or 0
    )
    published_cell_count = int(
        signal_prediction_accuracy_status.get("symbol_timeframe_cell_count") or 0
    )
    matrix_rows = signal_prediction_accuracy_status.get("by_symbol_timeframe") or []
    matrix_row_count = len(matrix_rows) if isinstance(matrix_rows, list) else 0
    all_accuracy_cells_published = (
        required_cell_count > 0
        and published_cell_count >= required_cell_count
        and matrix_row_count >= required_cell_count
        and not missing_timeframes
    )
    surface_rows = [dict(surface) for surface in DASHBOARD_WEB_SURFACES]
    all_surfaces_show_capital = all(
        bool(row.get("shows_capital_productivity_status"))
        for row in surface_rows
    )
    all_surfaces_show_pnl_windows = all(
        bool(row.get("shows_pnl_history_windows"))
        for row in surface_rows
    )
    all_surfaces_show_accuracy = all(
        bool(row.get("shows_signal_prediction_accuracy"))
        for row in surface_rows
    )
    all_surfaces_show_matrix = all(
        bool(row.get("shows_all_symbol_timeframe_accuracy_matrix"))
        for row in surface_rows
    )
    row_level_accuracy_pnl_surface_count = sum(
        1 for row in surface_rows
        if row.get("row_level_accuracy_pnl")
    )

    blocker_reasons: list[str] = []
    if not capital_productivity:
        blocker_reasons.append("MISSING_CAPITAL_PRODUCTIVITY_STATUS")
    if missing_pnl_windows:
        blocker_reasons.append("MISSING_REQUIRED_PNL_HISTORY_WINDOWS")
    if not all_accuracy_cells_published:
        blocker_reasons.append("MISSING_ALL_SYMBOL_TIMEFRAME_ACCURACY_MATRIX")
    if not all_surfaces_show_capital:
        blocker_reasons.append("CAPITAL_PRODUCTIVITY_NOT_VISIBLE_ON_ALL_TRACKED_SURFACES")
    if not all_surfaces_show_pnl_windows:
        blocker_reasons.append("PNL_HISTORY_NOT_VISIBLE_ON_ALL_TRACKED_SURFACES")
    if not all_surfaces_show_accuracy:
        blocker_reasons.append("SIGNAL_PREDICTION_ACCURACY_NOT_VISIBLE_ON_ALL_TRACKED_SURFACES")
    if not all_surfaces_show_matrix:
        blocker_reasons.append("SYMBOL_TIMEFRAME_ACCURACY_MATRIX_NOT_VISIBLE_ON_ALL_TRACKED_SURFACES")

    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": "READY" if not blocker_reasons else "NO_GO_DASHBOARD_WEB_EVIDENCE_INCOMPLETE",
        "paper_only": True,
        "places_real_order": False,
        "source": "operator_dashboard_payload.json and read-only frontend adaptive capital telemetry surfaces",
        "blocker_reasons": blocker_reasons,
        "required_pnl_windows": required_pnl_windows,
        "published_pnl_windows": published_pnl_windows,
        "missing_pnl_windows": missing_pnl_windows,
        "all_required_pnl_windows_published": not missing_pnl_windows,
        "required_accuracy_timeframes": required_timeframes,
        "published_accuracy_timeframes": published_timeframes,
        "missing_accuracy_timeframes": missing_timeframes,
        "symbol_universe_count": signal_prediction_accuracy_status.get("symbol_universe_count"),
        "required_symbol_timeframe_cell_count": required_cell_count,
        "published_symbol_timeframe_cell_count": published_cell_count,
        "published_symbol_timeframe_matrix_row_count": matrix_row_count,
        "evaluated_symbol_timeframe_cell_count": (
            signal_prediction_accuracy_status.get("evaluated_symbol_timeframe_cell_count")
        ),
        "missing_evaluated_symbol_timeframe_cell_count": (
            signal_prediction_accuracy_status.get("missing_evaluated_symbol_timeframe_cell_count")
        ),
        "all_symbol_timeframe_accuracy_cells_published": all_accuracy_cells_published,
        "all_symbol_timeframe_accuracy_cells_evaluated": (
            signal_prediction_accuracy_status.get("missing_evaluated_symbol_timeframe_cell_count") == 0
        ),
        "web_surface_count": len(surface_rows),
        "all_tracked_surfaces_show_capital_productivity_status": all_surfaces_show_capital,
        "all_tracked_surfaces_show_pnl_history_windows": all_surfaces_show_pnl_windows,
        "all_tracked_surfaces_show_signal_prediction_accuracy": all_surfaces_show_accuracy,
        "all_tracked_surfaces_show_all_symbol_timeframe_accuracy_matrix": all_surfaces_show_matrix,
        "row_level_accuracy_pnl_surface_count": row_level_accuracy_pnl_surface_count,
        "surfaces": surface_rows,
    }


def _closed_flag_confirmed(row: dict[str, Any], *, source_key: str | None = None) -> bool:
    if "ohlcv_closed:" in str(source_key or ""):
        return (
            row.get("candle_closed_confirmed") is True
            or row.get("closed_candle") is True
            or row.get("is_closed") is True
            or row.get("feature_eligible") is True
        )
    explicit = _first_present(
        row.get("candle_closed_confirmed"),
        row.get("closed_candle"),
        row.get("is_closed"),
        row.get("feature_eligible"),
    )
    return explicit is not False


def _candle_point(
    row: Any,
    *,
    generated_ms: int,
    source_key: str | None = None,
) -> tuple[int, float] | str:
    close_time_ms: int | None
    close_value: float | None
    available_at_ms: int | None = None
    if isinstance(row, list) and len(row) > 6:
        close_time_ms = _parse_epoch_ms(row[6])
        close_value = _coerce_float(row[4])
    elif isinstance(row, dict):
        close_time_ms = _parse_epoch_ms(_first_present(
            row.get("candle_close_time"),
            row.get("close_time"),
            row.get("event_time"),
            row.get("source_sequence_id"),
        ))
        ohlcv = row.get("ohlcv") if isinstance(row.get("ohlcv"), dict) else {}
        close_value = _coerce_float(_first_present(row.get("close"), ohlcv.get("close")))
        available_at_ms = _parse_epoch_ms(_first_present(row.get("available_at"), row.get("ingested_at")))
        if not _closed_flag_confirmed(row, source_key=source_key):
            return "UNFINISHED_CANDLE"
    else:
        return "UNSUPPORTED_CANDLE_ROW"
    if close_time_ms is None:
        return "MISSING_CANDLE_CLOSE_TIME"
    if close_time_ms > generated_ms:
        return "CANDLE_CLOSE_TIME_AFTER_GENERATED_AT"
    if available_at_ms is not None and available_at_ms > generated_ms:
        return "AVAILABLE_AT_AFTER_GENERATED_AT"
    if close_value is None or close_value <= 0.0:
        return "MISSING_OR_NON_POSITIVE_CLOSE"
    return close_time_ms, close_value


def _correlation_returns_from_candles(
    rows: list[Any],
    *,
    generated_utc: str,
    source_key: str | None = None,
) -> tuple[dict[int, float], dict[str, Any]]:
    generated_dt = _parse_utc(generated_utc)
    generated_ms = int(generated_dt.timestamp() * 1000) if generated_dt else 0
    rejects: dict[str, int] = {}
    points_by_close_time: dict[int, float] = {}
    for row in rows:
        point = _candle_point(row, generated_ms=generated_ms, source_key=source_key)
        if isinstance(point, str):
            rejects[point] = rejects.get(point, 0) + 1
            continue
        close_time_ms, close_value = point
        points_by_close_time[close_time_ms] = close_value
    ordered_points = sorted(points_by_close_time.items())
    returns: dict[int, float] = {}
    previous_close: float | None = None
    for close_time_ms, close_value in ordered_points:
        if previous_close and previous_close > 0.0:
            returns[close_time_ms] = (close_value / previous_close) - 1.0
        previous_close = close_value
    last_close_ms = ordered_points[-1][0] if ordered_points else None
    age_seconds = None
    if generated_ms and last_close_ms is not None:
        age_seconds = max(0.0, (generated_ms - last_close_ms) / 1000.0)
    diagnostics = {
        "source": source_key,
        "raw_candle_count": len(rows),
        "accepted_candle_count": len(ordered_points),
        "return_count": len(returns),
        "first_close_time": (
            datetime.fromtimestamp(ordered_points[0][0] / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
            if ordered_points else None
        ),
        "last_close_time": (
            datetime.fromtimestamp(last_close_ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
            if last_close_ms is not None else None
        ),
        "last_candle_age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
        "reject_counts": rejects,
    }
    return returns, diagnostics


def _pearson_correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < MIN_CORRELATION_RETURN_POINTS:
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    covariance = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right))
    left_var = sum((x - left_mean) ** 2 for x in left)
    right_var = sum((y - right_mean) ** 2 for y in right)
    if left_var <= 0.0 or right_var <= 0.0:
        return None
    return covariance / ((left_var * right_var) ** 0.5)


def _derive_correlation_inputs_from_candles(
    *,
    symbols: list[str],
    generated_utc: str,
    market_candles_by_symbol: dict[str, list[Any]] | None = None,
    market_candle_source_by_symbol: dict[str, str] | None = None,
) -> dict[str, Any]:
    market_candles_by_symbol = market_candles_by_symbol or {}
    market_candle_source_by_symbol = market_candle_source_by_symbol or {}
    returns_by_symbol: dict[str, dict[int, float]] = {}
    diagnostics_by_symbol: dict[str, dict[str, Any]] = {}
    missing_reasons: dict[str, str] = {}
    for symbol in sorted(set(symbols)):
        rows = market_candles_by_symbol.get(symbol, [])
        source_key = market_candle_source_by_symbol.get(symbol)
        if not rows:
            missing_reasons[symbol] = "MISSING_MARKET_CANDLES"
            diagnostics_by_symbol[symbol] = {
                "source": source_key,
                "raw_candle_count": 0,
                "accepted_candle_count": 0,
                "return_count": 0,
            }
            continue
        returns, diagnostics = _correlation_returns_from_candles(
            rows,
            generated_utc=generated_utc,
            source_key=source_key,
        )
        diagnostics_by_symbol[symbol] = diagnostics
        age_seconds = _coerce_float(diagnostics.get("last_candle_age_seconds"))
        if age_seconds is None:
            missing_reasons[symbol] = "MISSING_ACCEPTED_CANDLES"
            continue
        if age_seconds > MAX_CORRELATION_CANDLE_AGE_SECONDS:
            missing_reasons[symbol] = "STALE_LAST_CANDLE"
            continue
        if len(returns) < MIN_CORRELATION_RETURN_POINTS:
            missing_reasons[symbol] = "INSUFFICIENT_RETURN_POINTS"
            continue
        returns_by_symbol[symbol] = returns
    correlation_by_symbol: dict[str, float] = {}
    pair_counts_by_symbol: dict[str, int] = {}
    missing_pair_reasons: dict[str, str] = {}
    for symbol, returns in sorted(returns_by_symbol.items()):
        max_abs_correlation: float | None = None
        pair_count = 0
        for other_symbol, other_returns in sorted(returns_by_symbol.items()):
            if other_symbol == symbol:
                continue
            common_times = sorted(set(returns) & set(other_returns))
            if len(common_times) < MIN_CORRELATION_RETURN_POINTS:
                continue
            left = [returns[close_time] for close_time in common_times]
            right = [other_returns[close_time] for close_time in common_times]
            correlation = _pearson_correlation(left, right)
            if correlation is None:
                continue
            pair_count += 1
            abs_correlation = abs(correlation)
            max_abs_correlation = (
                abs_correlation
                if max_abs_correlation is None
                else max(max_abs_correlation, abs_correlation)
            )
        if max_abs_correlation is None:
            missing_pair_reasons[symbol] = "INSUFFICIENT_ALIGNED_RETURNS_OR_VARIANCE"
            continue
        correlation_by_symbol[symbol] = max_abs_correlation
        pair_counts_by_symbol[symbol] = pair_count
    for symbol in sorted(set(returns_by_symbol) - set(correlation_by_symbol)):
        missing_reasons[symbol] = missing_pair_reasons.get(symbol, "INSUFFICIENT_ALIGNED_RETURNS_OR_VARIANCE")
    return {
        "correlation_by_symbol": correlation_by_symbol,
        "missing_reasons": missing_reasons,
        "pair_counts_by_symbol": pair_counts_by_symbol,
        "diagnostics_by_symbol": diagnostics_by_symbol,
    }


def _pre_submit_temporal_reasons(row: dict[str, Any]) -> list[str]:
    decision = _parse_utc(_first_present(
        row.get("decision_time"),
        row.get("entry_feature_decision_time"),
        row.get("entry_price_utc"),
        row.get("generated_utc"),
        row.get("generated_at"),
    ))
    if decision is None:
        return ["MISSING_DECISION_TIME"]
    reasons: list[str] = []
    for label, value in (
        ("available_at", _first_present(row.get("available_at"), row.get("entry_feature_available_at"))),
        ("generated_at", _first_present(row.get("generated_at"), row.get("entry_feature_generated_at"))),
        ("feature_cutoff", _first_present(row.get("feature_cutoff"), row.get("entry_feature_cutoff"))),
    ):
        parsed = _parse_utc(value)
        if parsed is None:
            reasons.append(f"MISSING_{label.upper()}")
        elif parsed > decision:
            reasons.append(f"{label.upper()}_AFTER_DECISION_TIME")
    if row.get("entry_feature_candle_closed_confirmed") is False:
        reasons.append("UNFINISHED_CANDLE")
    return reasons


def _allocator_decision(row: dict[str, Any]) -> str:
    allocation = _allocation_mapping(row)
    return str(_first_present(row.get("allocator_decision"), allocation.get("allocator_decision"), row.get("decision"), ""))


def _is_sized_pre_submit_intent(row: dict[str, Any]) -> bool:
    return (
        _allocator_decision(row) in SIZED_ALLOCATOR_DECISIONS
        and _positive_row_float(row, "gross_notional_usd")
        and _positive_row_float(row, "quantity")
    )


def _is_allocator_blocked_intent(row: dict[str, Any]) -> bool:
    return _allocator_decision(row).startswith("BLOCK_")


def _non_sized_pre_submit_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    decision = _allocator_decision(row)
    if decision not in SIZED_ALLOCATOR_DECISIONS:
        reasons.append(f"ALLOCATOR_DECISION_{decision or 'MISSING'}")
    if row.get("paper_sizing_complete") is not True:
        reasons.append("PAPER_SIZING_COMPLETE_NOT_TRUE")
    if not _positive_row_float(row, "gross_notional_usd"):
        reasons.append("NON_POSITIVE_GROSS_NOTIONAL_USD")
    if not _positive_row_float(row, "quantity"):
        reasons.append("NON_POSITIVE_QUANTITY")
    return sorted(set(reasons))


def _nested_mapping(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = row.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _correlation_input(row: dict[str, Any]) -> float | None:
    correlation_context = _nested_mapping(
        row,
        "correlation_context",
        "portfolio_correlation_context",
        "correlation_anchor_context",
    )
    features = _nested_mapping(row, "features")
    allocation = _allocation_mapping(row)
    allocation_model_inputs = _nested_mapping(allocation, "model_inputs")
    return _coerce_float(_first_present(
        row.get("correlation_exposure_pct"),
        row.get("btc_correlation"),
        row.get("eth_correlation"),
        row.get("sol_correlation"),
        allocation.get("correlation_exposure_pct"),
        allocation_model_inputs.get("correlation_exposure_pct"),
        allocation_model_inputs.get("btc_correlation"),
        correlation_context.get("correlation_exposure_pct"),
        correlation_context.get("btc_correlation"),
        correlation_context.get("max_pairwise_correlation"),
        features.get("correlation_exposure_pct"),
        features.get("btc_correlation"),
    ))


def _portfolio_correlation_budget_status(
    *,
    open_positions: list[dict[str, Any]],
    equity: float,
    open_notional: float,
    effective_portfolio_leverage: float,
    generated_utc: str,
    envelope: RiskEnvelope | None = None,
    market_candles_by_symbol: dict[str, list[Any]] | None = None,
    market_candle_source_by_symbol: dict[str, str] | None = None,
) -> dict[str, Any]:
    envelope = envelope or RiskEnvelope()
    equity = max(0.0, equity)
    symbol_exposure: dict[str, float] = {}
    symbol_margin_exposure: dict[str, float] = {}
    side_exposure: dict[str, float] = {}
    regime_exposure: dict[str, float] = {}
    strategy_exposure: dict[str, float] = {}
    missing_correlation_symbols: set[str] = set()
    correlation_by_symbol: dict[str, float] = {}
    correlation_source_by_symbol: dict[str, str] = {}
    correlation_budget_breaches: list[dict[str, Any]] = []
    for row in open_positions:
        symbol = _normalized_symbol(row)
        side = _normalized_side(row)
        notional = _notional(row)
        margin = _margin(row)
        symbol_exposure[symbol] = symbol_exposure.get(symbol, 0.0) + notional
        symbol_margin_exposure[symbol] = symbol_margin_exposure.get(symbol, 0.0) + margin
        side_exposure[side] = side_exposure.get(side, 0.0) + notional
        regime = str(row.get("market_regime_at_entry") or "UNKNOWN")
        strategy = str(row.get("strategy_family") or row.get("strategy_id") or row.get("strategy_selected_mode") or "UNKNOWN")
        regime_exposure[regime] = regime_exposure.get(regime, 0.0) + notional
        strategy_exposure[strategy] = strategy_exposure.get(strategy, 0.0) + notional
        correlation = _correlation_input(row)
        if correlation is None:
            missing_correlation_symbols.add(symbol)
        else:
            correlation_by_symbol[symbol] = max(correlation_by_symbol.get(symbol, 0.0), abs(correlation))
            correlation_source_by_symbol[symbol] = "position_or_feature_payload"
    derived_correlation = _derive_correlation_inputs_from_candles(
        symbols=sorted(symbol_exposure),
        generated_utc=generated_utc,
        market_candles_by_symbol=market_candles_by_symbol,
        market_candle_source_by_symbol=market_candle_source_by_symbol,
    )
    derived_by_symbol = derived_correlation["correlation_by_symbol"]
    for symbol in sorted(missing_correlation_symbols):
        if symbol in derived_by_symbol:
            correlation_by_symbol[symbol] = max(
                correlation_by_symbol.get(symbol, 0.0),
                abs(_coerce_float(derived_by_symbol[symbol]) or 0.0),
            )
            correlation_source_by_symbol[symbol] = "market_ohlcv_return_correlation"
    missing_correlation_symbols = {
        symbol for symbol in missing_correlation_symbols
        if symbol not in derived_by_symbol
    }
    max_symbol_notional = max(symbol_exposure.values(), default=0.0)
    total_exposure_pct = (open_notional / equity) if equity > 0 else 0.0
    max_symbol_pct = (max_symbol_notional / equity) if equity > 0 else 0.0
    correlation_input_count = sum(
        1 for row in open_positions
        if _correlation_input(row) is not None or _normalized_symbol(row) in correlation_by_symbol
    )
    correlation_input_coverage = (
        1.0 if not open_positions else correlation_input_count / len(open_positions)
    )
    concentration_limit_breaches: list[dict[str, Any]] = []
    max_symbol_limit = max(0.0, envelope.max_single_symbol_exposure_pct)
    for symbol, notional in sorted(symbol_exposure.items()):
        exposure_pct = (notional / equity) if equity > 0 else 0.0
        if exposure_pct > max_symbol_limit:
            concentration_limit_breaches.append({
                "symbol": symbol,
                "exposure_pct": round(exposure_pct, 8),
                "limit_pct": round(max_symbol_limit, 8),
                "exposure_usd": round(notional, 8),
            })
    max_total_limit = max(0.0, envelope.max_total_portfolio_risk_pct)
    if total_exposure_pct > max_total_limit:
        concentration_limit_breaches.append({
            "symbol": "__PORTFOLIO__",
            "exposure_pct": round(total_exposure_pct, 8),
            "limit_pct": round(max_total_limit, 8),
            "exposure_usd": round(open_notional, 8),
        })
    max_correlation_observed = max(correlation_by_symbol.values(), default=0.0)
    for symbol, correlation in sorted(correlation_by_symbol.items()):
        if correlation > envelope.max_correlation_exposure_pct:
            correlation_budget_breaches.append({
                "symbol": symbol,
                "correlation_exposure_pct": round(correlation, 8),
                "limit_pct": round(envelope.max_correlation_exposure_pct, 8),
            })
    correlation_budget_reduction_plan: list[dict[str, Any]] = []
    for breach in correlation_budget_breaches:
        symbol = str(breach["symbol"])
        correlation = _coerce_float(breach.get("correlation_exposure_pct")) or 0.0
        limit = max(1e-9, envelope.max_correlation_exposure_pct)
        correlation_adjustment_if_new = max(0.0, min(1.0, 1.0 - (correlation / limit)))
        correlation_budget_reduction_plan.append({
            "symbol": symbol,
            "current_open_notional_usd": round(symbol_exposure.get(symbol, 0.0), 8),
            "current_allocated_margin_usd": round(symbol_margin_exposure.get(symbol, 0.0), 8),
            "correlation_exposure_pct": round(correlation, 8),
            "limit_pct": round(envelope.max_correlation_exposure_pct, 8),
            "excess_correlation_exposure_pct": round(max(0.0, correlation - envelope.max_correlation_exposure_pct), 8),
            "new_allocation_correlation_adjustment": round(correlation_adjustment_if_new, 8),
            "new_allocation_allowed_under_correlation_budget": correlation_adjustment_if_new > 0.0,
            "maximum_new_notional_usd_under_correlation_budget": 0.0 if correlation_adjustment_if_new <= 0.0 else None,
            "current_position_action_required": True,
            "remediation_action": "block_new_allocations_and_reduce_or_hedge_existing_exposure_until_correlation_within_budget",
        })
    correlation_input_missing_reasons = {
        symbol: derived_correlation["missing_reasons"].get(symbol, "MISSING_POSITION_OR_FEATURE_CORRELATION")
        for symbol in sorted(missing_correlation_symbols)
    }
    correlation_source_counts: dict[str, int] = {}
    for source in correlation_source_by_symbol.values():
        correlation_source_counts[source] = correlation_source_counts.get(source, 0) + 1
    correlation_input_status_counts = {
        "READY": correlation_input_count,
        "MISSING": len(open_positions) - correlation_input_count,
    }
    concentration_ok = not concentration_limit_breaches
    correlation_matrix_ready = len(open_positions) <= 1 or correlation_input_coverage >= 1.0
    correlation_budget_ok = not correlation_budget_breaches
    blocker_reasons: list[str] = []
    if not concentration_ok:
        blocker_reasons.append("PORTFOLIO_CONCENTRATION_BREACH")
    if not correlation_matrix_ready:
        blocker_reasons.append("CORRELATION_INPUTS_MISSING")
    if not correlation_budget_ok:
        blocker_reasons.append("CORRELATION_BUDGET_BREACH")
    if blocker_reasons == ["PORTFOLIO_CONCENTRATION_BREACH"]:
        status = "NO_GO_PORTFOLIO_CONCENTRATION_BREACH"
    elif blocker_reasons == ["CORRELATION_INPUTS_MISSING"]:
        status = "NO_GO_CORRELATION_INPUTS_MISSING"
    elif blocker_reasons == ["CORRELATION_BUDGET_BREACH"]:
        status = "NO_GO_CORRELATION_BUDGET_BREACH"
    elif blocker_reasons == ["CORRELATION_INPUTS_MISSING", "CORRELATION_BUDGET_BREACH"]:
        status = "NO_GO_CORRELATION_INPUTS_MISSING_AND_BUDGET_BREACH"
    elif blocker_reasons:
        status = "NO_GO_MULTIPLE_PORTFOLIO_CORRELATION_BLOCKERS"
    else:
        status = "PASSED"
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": status,
        "correlation_blocker_reasons": blocker_reasons,
        "open_position_count": len(open_positions),
        "open_symbol_count": len(symbol_exposure),
        "gross_open_notional_usd": round(open_notional, 8),
        "effective_portfolio_leverage": effective_portfolio_leverage,
        "total_exposure_pct_of_equity": round(total_exposure_pct, 8),
        "max_total_portfolio_exposure_pct": round(max_total_limit, 8),
        "max_single_symbol_exposure_pct": round(max_symbol_limit, 8),
        "max_observed_symbol_exposure_pct": round(max_symbol_pct, 8),
        "portfolio_concentration_limits_enforced": concentration_ok,
        "concentration_limit_breaches": concentration_limit_breaches,
        "correlation_matrix_ready": correlation_matrix_ready,
        "correlation_input_coverage": round(correlation_input_coverage, 8),
        "correlation_input_count": correlation_input_count,
        "correlation_input_missing_symbols": sorted(missing_correlation_symbols),
        "correlation_input_missing_count": len(missing_correlation_symbols),
        "correlation_input_missing_reasons": correlation_input_missing_reasons,
        "correlation_input_missing_sample": [
            {
                "symbol": symbol,
                "reason": correlation_input_missing_reasons[symbol],
                "diagnostics": derived_correlation["diagnostics_by_symbol"].get(symbol, {}),
            }
            for symbol in sorted(missing_correlation_symbols)[:20]
        ],
        "correlation_source_by_symbol": {
            key: correlation_source_by_symbol[key]
            for key in sorted(correlation_source_by_symbol)
        },
        "correlation_source_counts": {
            key: correlation_source_counts[key]
            for key in sorted(correlation_source_counts)
        },
        "correlation_input_status_counts": {
            key: correlation_input_status_counts[key]
            for key in sorted(correlation_input_status_counts)
        },
        "derived_correlation_symbol_count": len([
            symbol for symbol, source in correlation_source_by_symbol.items()
            if source == "market_ohlcv_return_correlation"
        ]),
        "derived_correlation_symbols": sorted(
            symbol for symbol, source in correlation_source_by_symbol.items()
            if source == "market_ohlcv_return_correlation"
        ),
        "correlation_return_timeframe": CORRELATION_CANDLE_TIMEFRAME,
        "min_correlation_return_points": MIN_CORRELATION_RETURN_POINTS,
        "max_correlation_candle_age_seconds": MAX_CORRELATION_CANDLE_AGE_SECONDS,
        "correlation_pair_counts_by_symbol": {
            key: derived_correlation["pair_counts_by_symbol"][key]
            for key in sorted(derived_correlation["pair_counts_by_symbol"])
        },
        "correlation_candle_diagnostics_by_symbol": {
            key: derived_correlation["diagnostics_by_symbol"][key]
            for key in sorted(derived_correlation["diagnostics_by_symbol"])
        },
        "max_correlation_exposure_pct": round(envelope.max_correlation_exposure_pct, 8),
        "max_observed_correlation_exposure_pct": round(max_correlation_observed, 8),
        "correlation_budget_breach_count": len(correlation_budget_breaches),
        "correlation_budget_breach_sample": correlation_budget_breaches[:20],
        "correlation_budget_breaches": correlation_budget_breaches,
        "correlation_budget_reduction_required": bool(correlation_budget_reduction_plan),
        "correlation_budget_reduction_plan_count": len(correlation_budget_reduction_plan),
        "correlation_budget_reduction_plan_sample": correlation_budget_reduction_plan[:20],
        "correlation_budget_reduction_plan": correlation_budget_reduction_plan,
        "breached_correlation_open_notional_usd": round(
            sum(item["current_open_notional_usd"] for item in correlation_budget_reduction_plan),
            8,
        ),
        "symbol_exposure_usd": {key: round(value, 8) for key, value in sorted(symbol_exposure.items())},
        "symbol_margin_exposure_usd": {key: round(value, 8) for key, value in sorted(symbol_margin_exposure.items())},
        "side_exposure_usd": {key: round(value, 8) for key, value in sorted(side_exposure.items())},
        "regime_exposure_usd": {key: round(value, 8) for key, value in sorted(regime_exposure.items())},
        "strategy_exposure_usd": {key: round(value, 8) for key, value in sorted(strategy_exposure.items())},
    }


def _normalized_pre_submit_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": str(_row_value(row, "symbol") or "").upper(),
        "timeframe": _row_value(row, "timeframe"),
        "side": str(_row_value(row, "side") or "").lower(),
        "entry_price": _coerce_float(_row_value(row, "entry_price")),
        "quantity": _coerce_float(_row_value(row, "quantity")),
        "gross_notional_usd": _coerce_float(_row_value(row, "gross_notional_usd")),
        "allocated_margin_usd": _coerce_float(_row_value(row, "allocated_margin_usd")),
        "recommended_leverage": _coerce_float(_row_value(row, "recommended_leverage")),
        "effective_leverage": _coerce_float(_row_value(row, "effective_leverage")),
        "recommended_margin_mode": _row_value(row, "recommended_margin_mode"),
        "allocator_decision": _allocator_decision(row),
        "paper_only": row.get("paper_only"),
        "places_real_order": row.get("places_real_order"),
        "live_gate": row.get("live_gate"),
    }


def _allocation_model_inputs(row: dict[str, Any]) -> dict[str, Any]:
    allocation = _allocation_mapping(row)
    model_inputs = allocation.get("model_inputs")
    return model_inputs if isinstance(model_inputs, dict) else {}


def _allocation_correlation_input(row: dict[str, Any]) -> float | None:
    allocation = _allocation_mapping(row)
    model_inputs = _allocation_model_inputs(row)
    return _coerce_float(_first_present(
        row.get("correlation_exposure_pct"),
        model_inputs.get("correlation_exposure_pct"),
        allocation.get("correlation_exposure_pct"),
    ))


def _allocation_correlation_adjustment(row: dict[str, Any]) -> float | None:
    allocation = _allocation_mapping(row)
    model_inputs = _allocation_model_inputs(row)
    return _coerce_float(_first_present(
        row.get("correlation_adjustment"),
        allocation.get("correlation_adjustment"),
        model_inputs.get("correlation_adjustment"),
    ))


def _intent_source(row: dict[str, Any]) -> str:
    return str(_first_present(row.get("paper_intent_source"), row.get("source_redis_key"), "__unspecified__"))


def _intent_source_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        source = _intent_source(row)
        counts[source] = counts.get(source, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _value_counts(values: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value if value is not None and value != "" else "__missing__")
        counts[key] = counts.get(key, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _pre_submit_candidate_failure_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not _is_adaptive_capital_policy_row(row):
        reasons.append("MISSING_ADAPTIVE_CAPITAL_POLICY_VERSION")
    for field in PRE_SUBMIT_PARITY_REQUIRED_FIELDS:
        if not _row_field_present(row, field):
            reasons.append(f"MISSING_{field.upper()}")
    for field in (
        "entry_price",
        "quantity",
        "gross_notional_usd",
        "allocated_margin_usd",
        "recommended_leverage",
        "effective_leverage",
        "stop_distance_bps",
        "liquidation_price_estimate",
        "liquidation_buffer_bps",
    ):
        if not _positive_row_float(row, field):
            reasons.append(f"NON_POSITIVE_{field.upper()}")
    liquidation_buffer = _coerce_float(_row_value(row, "liquidation_buffer_bps"))
    minimum_liquidation_buffer = RiskEnvelope().min_liquidation_buffer_bps
    if liquidation_buffer is not None and liquidation_buffer < minimum_liquidation_buffer:
        reasons.append("LIQUIDATION_BUFFER_BELOW_MINIMUM")
    side = str(_row_value(row, "side") or "").lower()
    if side not in {"long", "short"}:
        reasons.append("SIDE_NOT_LONG_OR_SHORT")
    margin_mode = str(_row_value(row, "recommended_margin_mode") or "")
    if margin_mode not in {"isolated_paper_simulated", "cross_paper_simulated", "isolated", "cross"}:
        reasons.append("UNSUPPORTED_MARGIN_MODE")
    if row.get("paper_only") is not True:
        reasons.append("PAPER_ONLY_NOT_TRUE")
    if str(row.get("live_gate") or LIVE_GATE) != LIVE_GATE:
        reasons.append("LIVE_GATE_NOT_BLOCKED_HUMAN_ONLY")
    for field in (
        "places_real_order",
        "test_orders",
        "test_order",
        "leverage_mutation",
        "margin_mode_mutation",
        "leverage_changed",
        "margin_mode_changed",
        "withdrawals",
        "transfers",
        "trainer_bridge_unmasked",
    ):
        if _truthy(row.get(field)):
            reasons.append(f"UNSAFE_{field.upper()}")
    reasons.extend(_pre_submit_temporal_reasons(row))
    return sorted(set(reasons))


def _durable_accepted_pre_submit_evidence(
    *,
    ledger: dict[str, Any],
    generated_utc: str,
) -> dict[str, Any]:
    source = "v2:paper:ledger.accepted"
    accepted_rows = _safe_rows(ledger, "accepted") if isinstance(ledger, dict) else []
    if not accepted_rows:
        source = "v2:paper:ledger.accepted_intents"
        accepted_rows = _safe_rows(ledger, "accepted_intents") if isinstance(ledger, dict) else []
    for row in accepted_rows:
        row.setdefault("paper_intent_source", source)

    versioned_rows = [row for row in accepted_rows if _is_adaptive_capital_policy_row(row)]
    sized_rows = [row for row in accepted_rows if _is_sized_pre_submit_intent(row)]
    versioned_sized_rows = [row for row in versioned_rows if _is_sized_pre_submit_intent(row)]
    versioned_sized_selection_evidence = _adaptive_field_selection_evidence(versioned_sized_rows)
    latest_strict_selection_model_input_suffix_evidence = (
        _latest_strict_selection_model_input_suffix_evidence(versioned_sized_rows)
    )
    versioned_sized_accounting_evidence = _accounting_enforcement_evidence(
        versioned_sized_rows,
        source=source,
    )
    liquidation_buffer_minimum_evidence = _liquidation_buffer_minimum_evidence(versioned_sized_rows)
    failure_reason_counts: dict[str, int] = {}
    failure_sample: list[dict[str, Any]] = []
    for index, row in enumerate(versioned_sized_rows):
        reasons = _pre_submit_candidate_failure_reasons(row)
        if not reasons:
            continue
        for reason in reasons:
            failure_reason_counts[reason] = failure_reason_counts.get(reason, 0) + 1
        failure_sample.append({
            "index": index,
            "symbol": _row_value(row, "symbol"),
            "timeframe": _row_value(row, "timeframe"),
            "reasons": reasons,
        })

    if not accepted_rows:
        status = "NO_DURABLE_ACCEPTED_LEDGER_ROWS"
    elif not versioned_rows:
        status = "NO_DURABLE_VERSIONED_ACCEPTED_EVIDENCE"
    elif not versioned_sized_rows:
        status = "NO_DURABLE_VERSIONED_SIZED_ACCEPTED_EVIDENCE"
    elif failure_sample:
        status = "NO_GO_DURABLE_ACCEPTED_FIELD_MISMATCH"
    else:
        status = "PASSED"

    field_coverage = (
        0.0
        if not versioned_sized_rows
        else (len(versioned_sized_rows) - len(failure_sample)) / len(versioned_sized_rows)
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": status,
        "source": source,
        "accepted_row_count": len(accepted_rows),
        "versioned_accepted_row_count": len(versioned_rows),
        "sized_accepted_row_count": len(sized_rows),
        "versioned_sized_accepted_candidate_count": len(versioned_sized_rows),
        "accepted_policy_version_counts": _value_counts([
            _capital_policy_version(row) for row in accepted_rows
        ]),
        "accepted_allocator_decision_counts": _value_counts([
            _allocator_decision(row) for row in accepted_rows
        ]),
        "versioned_candidate_field_coverage": round(field_coverage, 8),
        "versioned_candidate_failure_count": len(failure_sample),
        "versioned_candidate_failure_reason_counts": {
            key: failure_reason_counts[key] for key in sorted(failure_reason_counts)
        },
        "versioned_candidate_failure_sample": failure_sample[:20],
        "versioned_candidate_selection_model_input_evidence": versioned_sized_selection_evidence,
        "latest_strict_selection_model_input_suffix_evidence": (
            latest_strict_selection_model_input_suffix_evidence
        ),
        "versioned_candidate_accounting_evidence": versioned_sized_accounting_evidence,
        "liquidation_buffer_minimum_evidence": liquidation_buffer_minimum_evidence,
        "canonical_versioned_pre_submit_sample": [
            _normalized_pre_submit_payload(row)
            for row in versioned_sized_rows[:20]
        ],
        "notes": (
            "Durable accepted ledger evidence may satisfy the parity gate only when active and held "
            "paper_intent snapshots are absent, or when every active/held versioned intent is an "
            "explicit allocator block with no current sized candidate. It never overrides active "
            "pre-submit field, safety, or temporal failures."
        ),
    }


def _paper_live_pre_submit_parity_status(
    *,
    paper_intents: list[dict[str, Any]],
    generated_utc: str,
) -> dict[str, Any]:
    versioned_intents = [row for row in paper_intents if _is_adaptive_capital_policy_row(row)]
    sized_candidates = [row for row in paper_intents if _is_sized_pre_submit_intent(row)]
    versioned_sized_candidates = [row for row in sized_candidates if _is_adaptive_capital_policy_row(row)]
    unversioned_sized_candidates = [row for row in sized_candidates if not _is_adaptive_capital_policy_row(row)]
    unversioned_allocator_evidence_rows = [
        row for row in paper_intents
        if not _is_adaptive_capital_policy_row(row) and _has_allocator_evidence(row)
    ]
    non_sized_versioned_intents = [row for row in versioned_intents if not _is_sized_pre_submit_intent(row)]
    active_or_held_versioned_intents = [
        row for row in versioned_intents
        if _intent_source(row) in ACTIVE_OR_HELD_PAPER_INTENT_SOURCES
    ]
    active_or_held_versioned_sized_intents = [
        row for row in active_or_held_versioned_intents
        if _is_sized_pre_submit_intent(row)
    ]
    active_or_held_versioned_blocked_intents = [
        row for row in active_or_held_versioned_intents
        if not _is_sized_pre_submit_intent(row) and _is_allocator_blocked_intent(row)
    ]
    active_or_held_versioned_unblocked_non_sized_intents = [
        row for row in active_or_held_versioned_intents
        if not _is_sized_pre_submit_intent(row) and not _is_allocator_blocked_intent(row)
    ]
    active_or_held_versioned_intents_all_blocked = (
        bool(active_or_held_versioned_intents)
        and not active_or_held_versioned_sized_intents
        and not active_or_held_versioned_unblocked_non_sized_intents
        and len(active_or_held_versioned_blocked_intents) == len(active_or_held_versioned_intents)
    )
    paper_intent_source_counts = _intent_source_counts(paper_intents)
    versioned_intent_source_counts = _intent_source_counts(versioned_intents)
    sized_candidate_source_counts = _intent_source_counts(sized_candidates)
    non_sized_reason_counts: dict[str, int] = {}
    non_sized_sample: list[dict[str, Any]] = []
    for index, row in enumerate(non_sized_versioned_intents):
        reasons = _non_sized_pre_submit_reasons(row)
        for reason in reasons:
            non_sized_reason_counts[reason] = non_sized_reason_counts.get(reason, 0) + 1
        if len(non_sized_sample) < 20:
            non_sized_sample.append({
                "index": index,
                "symbol": _row_value(row, "symbol"),
                "timeframe": _row_value(row, "timeframe"),
                "allocator_decision": _allocator_decision(row),
                "paper_sizing_complete": row.get("paper_sizing_complete"),
                "gross_notional_usd": _coerce_float(_row_value(row, "gross_notional_usd")),
                "quantity": _coerce_float(_row_value(row, "quantity")),
                "reasons": reasons,
            })
    correlation_input_values = [
        value for value in (_allocation_correlation_input(row) for row in sized_candidates)
        if value is not None
    ]
    correlation_adjustment_values = [
        value for value in (_allocation_correlation_adjustment(row) for row in sized_candidates)
        if value is not None
    ]
    correlation_input_missing_sample: list[dict[str, Any]] = []
    for index, row in enumerate(sized_candidates):
        if _allocation_correlation_input(row) is None:
            correlation_input_missing_sample.append({
                "index": index,
                "symbol": _row_value(row, "symbol"),
                "timeframe": _row_value(row, "timeframe"),
                "allocator_decision": _allocator_decision(row),
            })
    correlation_source_counts: dict[str, int] = {}
    correlation_status_counts: dict[str, int] = {}
    for row in sized_candidates:
        source = str(row.get("correlation_input_source") or "__missing__")
        status = str(row.get("correlation_input_status") or "__missing__")
        correlation_source_counts[source] = correlation_source_counts.get(source, 0) + 1
        correlation_status_counts[status] = correlation_status_counts.get(status, 0) + 1
    liquidation_buffer_minimum_evidence = _liquidation_buffer_minimum_evidence(versioned_sized_candidates)
    failure_sample: list[dict[str, Any]] = []
    failure_reason_counts: dict[str, int] = {}
    for index, row in enumerate(sized_candidates):
        unique_reasons = _pre_submit_candidate_failure_reasons(row)
        if not unique_reasons:
            continue
        for reason in unique_reasons:
            failure_reason_counts[reason] = failure_reason_counts.get(reason, 0) + 1
        failure_sample.append({
            "index": index,
            "symbol": _row_value(row, "symbol"),
            "timeframe": _row_value(row, "timeframe"),
            "reasons": unique_reasons,
        })
    failure_count = len(failure_sample)
    coverage = 0.0 if not sized_candidates else (len(sized_candidates) - failure_count) / len(sized_candidates)
    if not paper_intents:
        status = "NO_GO_PRE_SUBMIT_PARITY_NO_INTENT_EVIDENCE"
    elif not sized_candidates and not versioned_intents and unversioned_allocator_evidence_rows:
        status = "NO_GO_PRE_SUBMIT_PARITY_UNVERSIONED_ALLOCATOR_EVIDENCE"
    elif not sized_candidates and not versioned_intents:
        status = "NO_GO_PRE_SUBMIT_PARITY_NO_VERSIONED_ADAPTIVE_INTENTS"
    elif not sized_candidates:
        status = "NO_GO_PRE_SUBMIT_PARITY_NO_SIZED_INTENTS"
    elif failure_count:
        status = "NO_GO_PRE_SUBMIT_PARITY_FIELD_MISMATCH"
    else:
        status = "PASSED"
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": status,
        "parity_scope": "paper_intent_to_live_pre_submit_contract_no_exchange_mutation",
        "paper_intent_row_count": len(paper_intents),
        "paper_intent_active_row_count": paper_intent_source_counts.get("v2:paper:intents", 0),
        "paper_intent_held_row_count": paper_intent_source_counts.get("v2:paper:intents_held_by_paper_fill_gate", 0),
        "paper_intent_source_counts": paper_intent_source_counts,
        "paper_intent_policy_version_counts": _value_counts([
            _capital_policy_version(row) for row in paper_intents
        ]),
        "paper_intent_allocator_decision_counts": _value_counts([
            _allocator_decision(row) for row in paper_intents
        ]),
        "paper_intent_sizing_complete_counts": _value_counts([
            row.get("paper_sizing_complete") for row in paper_intents
        ]),
        "unversioned_allocator_evidence_count": len(unversioned_allocator_evidence_rows),
        "unversioned_allocator_evidence_decision_counts": _value_counts([
            _allocator_decision(row) for row in unversioned_allocator_evidence_rows
        ]),
        "unversioned_allocator_evidence_sample": [
            {
                "index": index,
                "symbol": _row_value(row, "symbol"),
                "timeframe": _row_value(row, "timeframe"),
                "allocator_decision": _allocator_decision(row),
                "paper_sizing_complete": row.get("paper_sizing_complete"),
                "paper_allocation_block_reason": row.get("paper_allocation_block_reason"),
                "adaptive_allocation_keys": sorted(_allocation_mapping(row).keys()),
            }
            for index, row in enumerate(unversioned_allocator_evidence_rows[:20])
        ],
        "versioned_adaptive_intent_count": len(versioned_intents),
        "versioned_adaptive_intent_source_counts": versioned_intent_source_counts,
        "sized_pre_submit_candidate_count": len(sized_candidates),
        "versioned_sized_pre_submit_candidate_count": len(versioned_sized_candidates),
        "unversioned_sized_pre_submit_candidate_count": len(unversioned_sized_candidates),
        "unversioned_sized_pre_submit_candidate_sample": [
            {
                "index": index,
                **_normalized_pre_submit_payload(row),
            }
            for index, row in enumerate(unversioned_sized_candidates[:20])
        ],
        "sized_pre_submit_candidate_source_counts": sized_candidate_source_counts,
        "non_sized_versioned_intent_count": len(non_sized_versioned_intents),
        "non_sized_versioned_intent_reason_counts": {
            key: non_sized_reason_counts[key] for key in sorted(non_sized_reason_counts)
        },
        "non_sized_versioned_intent_sample": non_sized_sample,
        "active_or_held_versioned_intent_count": len(active_or_held_versioned_intents),
        "active_or_held_versioned_sized_intent_count": len(active_or_held_versioned_sized_intents),
        "active_or_held_versioned_blocked_intent_count": len(active_or_held_versioned_blocked_intents),
        "active_or_held_versioned_unblocked_non_sized_intent_count": (
            len(active_or_held_versioned_unblocked_non_sized_intents)
        ),
        "active_or_held_versioned_intents_all_blocked": active_or_held_versioned_intents_all_blocked,
        "active_or_held_versioned_unblocked_non_sized_intent_sample": [
            {
                "index": index,
                "symbol": _row_value(row, "symbol"),
                "timeframe": _row_value(row, "timeframe"),
                "allocator_decision": _allocator_decision(row),
                "paper_sizing_complete": row.get("paper_sizing_complete"),
                "gross_notional_usd": _coerce_float(_row_value(row, "gross_notional_usd")),
                "quantity": _coerce_float(_row_value(row, "quantity")),
                "reasons": _non_sized_pre_submit_reasons(row),
            }
            for index, row in enumerate(active_or_held_versioned_unblocked_non_sized_intents[:20])
        ],
        "required_fields": list(PRE_SUBMIT_PARITY_REQUIRED_FIELDS),
        "candidate_field_coverage": round(coverage, 8),
        "allocator_correlation_input_required": True,
        "allocator_correlation_input_count": len(correlation_input_values),
        "allocator_correlation_input_coverage": (
            0.0 if not sized_candidates else round(len(correlation_input_values) / len(sized_candidates), 8)
        ),
        "allocator_correlation_input_missing_sample": correlation_input_missing_sample[:20],
        "allocator_correlation_input_source_counts": {
            key: correlation_source_counts[key] for key in sorted(correlation_source_counts)
        },
        "allocator_correlation_input_status_counts": {
            key: correlation_status_counts[key] for key in sorted(correlation_status_counts)
        },
        "max_allocator_correlation_exposure_pct": (
            round(max(abs(value) for value in correlation_input_values), 8)
            if correlation_input_values else None
        ),
        "min_allocator_correlation_adjustment": (
            round(min(correlation_adjustment_values), 8)
            if correlation_adjustment_values else None
        ),
        "max_allocator_correlation_adjustment": (
            round(max(correlation_adjustment_values), 8)
            if correlation_adjustment_values else None
        ),
        "liquidation_buffer_minimum_evidence": liquidation_buffer_minimum_evidence,
        "candidate_failure_count": failure_count,
        "candidate_failure_reason_counts": {
            key: failure_reason_counts[key] for key in sorted(failure_reason_counts)
        },
        "candidate_failure_sample": failure_sample[:20],
        "canonical_pre_submit_sample": [
            _normalized_pre_submit_payload(row)
            for row in sized_candidates[:10]
        ],
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "withdrawals": False,
        "transfers": False,
        "legacy_redis_writes": False,
        "trainer_bridge_unmasked": False,
        "live_gate": LIVE_GATE,
    }


def _hash_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return None


def _p0_baseline() -> dict[str, Any]:
    validator = _load_json(P0_GOAL_DIR / "RUNTIME_VALIDATION_REPORT_AFTER_TRAILING_STOP_PRICE_COST_FLOOR_PATCH.json")
    files = [
        REPO_ROOT / "v2/backend/app/services/paper_trade_management/exits.py",
        REPO_ROOT / "v2/backend/app/services/paper_trade_management/lifecycle.py",
        REPO_ROOT / "v2/backend/app/services/paper_trade_management/outcomes.py",
        P0_GOAL_DIR / "RUNTIME_VALIDATION_REPORT_AFTER_TRAILING_STOP_PRICE_COST_FLOOR_PATCH.json",
    ]
    return {
        "frozen": bool(isinstance(validator, dict) and validator.get("overall_status") == "PASSED"),
        "policy_version": P0_POLICY_VERSION,
        "freeze_scope": "P0 validator report, policy version, live-gate state, and current source hashes after capital-accounting telemetry patch",
        "validator_generated_utc": validator.get("generated_utc") if isinstance(validator, dict) else None,
        "validator_overall_status": validator.get("overall_status") if isinstance(validator, dict) else None,
        "validator_remaining_blockers": validator.get("remaining_blockers") if isinstance(validator, dict) else None,
        "ready_for_live": validator.get("ready_for_live") if isinstance(validator, dict) else False,
        "live_gate": validator.get("live_gate") if isinstance(validator, dict) else LIVE_GATE,
        "current_code_hashes": {str(path.relative_to(REPO_ROOT)): _hash_file(path) for path in files},
        "capital_phase_touched_exit_policy_file": False,
        "capital_phase_notes": (
            "Capital phase did not edit exits.py or trailing policy constants. "
            "Lifecycle/outcome/position hashes may include additive capital-accounting telemetry fields."
        ),
    }


def _monthly_daily_required_multiple(*, horizon_years: float) -> tuple[float, float]:
    months = max(1.0, horizon_years * 12.0)
    days = max(1.0, horizon_years * 365.0)
    return (1000.0 ** (1.0 / months) - 1.0, 1000.0 ** (1.0 / days) - 1.0)


def _one_thousand_x_observed_growth_evidence(
    *,
    starting_equity_usd: float,
    target_multiple: float,
    horizon_years: float,
    current_equity_usd: float,
    pnl_history_status: dict[str, Any],
) -> dict[str, Any]:
    starting_equity = max(0.01, starting_equity_usd)
    target_multiple = max(1.0, target_multiple)
    horizon_seconds = max(1.0, horizon_years * 365.0 * 24.0 * 60.0 * 60.0)
    required_log_growth = math.log(target_multiple)
    current_multiple = current_equity_usd / starting_equity if current_equity_usd > 0.0 else 0.0
    current_log_growth = math.log(current_multiple) if current_multiple > 0.0 else None
    window_evidence: list[dict[str, Any]] = []
    projected_values: list[float] = []
    for window in pnl_history_status.get("windows") or []:
        if not isinstance(window, dict):
            continue
        lookback_seconds = _coerce_float(window.get("lookback_seconds")) or 0.0
        realized_pnl = _coerce_float(window.get("realized_pnl_usd")) or 0.0
        closed_trade_count = int(_coerce_float(window.get("closed_trade_count")) or 0.0)
        required_window_log_growth = (
            required_log_growth * (lookback_seconds / horizon_seconds)
            if lookback_seconds > 0.0 else None
        )
        required_window_return = (
            math.exp(required_window_log_growth) - 1.0
            if required_window_log_growth is not None else None
        )
        required_window_pnl = (
            starting_equity * required_window_return
            if required_window_return is not None else None
        )
        ending_equity = starting_equity + realized_pnl
        observed_window_log_growth = (
            math.log(ending_equity / starting_equity)
            if ending_equity > 0.0 else None
        )
        projected_horizon_log_growth = (
            observed_window_log_growth * (horizon_seconds / lookback_seconds)
            if observed_window_log_growth is not None and lookback_seconds > 0.0 else None
        )
        if projected_horizon_log_growth is not None and closed_trade_count > 0:
            projected_values.append(projected_horizon_log_growth)
        if closed_trade_count <= 0:
            status = "NO_WINDOW_CLOSED_TRADE_EVIDENCE"
        elif projected_horizon_log_growth is not None and projected_horizon_log_growth >= required_log_growth:
            status = "ABOVE_REQUIRED_TRAJECTORY_UNVERIFIED"
        else:
            status = "BELOW_REQUIRED_TRAJECTORY"
        window_evidence.append({
            "window": window.get("window"),
            "lookback_seconds": int(lookback_seconds) if lookback_seconds else None,
            "closed_trade_count": closed_trade_count,
            "realized_pnl_usd": round(realized_pnl, 8),
            "observed_window_return": round(realized_pnl / starting_equity, 12),
            "observed_window_log_growth": (
                round(observed_window_log_growth, 12)
                if observed_window_log_growth is not None else None
            ),
            "projected_horizon_log_growth_if_window_repeated": (
                round(projected_horizon_log_growth, 12)
                if projected_horizon_log_growth is not None else None
            ),
            "required_window_return": (
                round(required_window_return, 12)
                if required_window_return is not None else None
            ),
            "required_window_pnl_usd": (
                round(required_window_pnl, 8)
                if required_window_pnl is not None else None
            ),
            "window_pnl_shortfall_vs_required_usd": (
                round(required_window_pnl - realized_pnl, 8)
                if required_window_pnl is not None else None
            ),
            "projected_log_growth_gap_vs_required": (
                round(required_log_growth - projected_horizon_log_growth, 12)
                if projected_horizon_log_growth is not None else None
            ),
            "status": status,
        })
    best_projected = max(projected_values, default=None)
    if best_projected is None:
        observed_growth_classification = "NO_OBSERVED_WINDOW_GROWTH_EVIDENCE"
    elif best_projected >= required_log_growth:
        observed_growth_classification = "OBSERVED_WINDOW_ABOVE_REQUIRED_BUT_UNVERIFIED"
    else:
        observed_growth_classification = "OBSERVED_GROWTH_BELOW_REQUIRED"
    return {
        "starting_equity_usd": round(starting_equity, 8),
        "observed_target_multiple": round(target_multiple, 8),
        "current_paper_equity_usd": round(current_equity_usd, 8),
        "observed_current_equity_multiple": round(current_multiple, 12),
        "observed_current_log_growth_from_starting_equity": (
            round(current_log_growth, 12)
            if current_log_growth is not None else None
        ),
        "required_log_growth": round(required_log_growth, 12),
        "current_log_growth_gap_vs_required": (
            round(required_log_growth - current_log_growth, 12)
            if current_log_growth is not None else None
        ),
        "best_projected_horizon_log_growth_if_window_repeated": (
            round(best_projected, 12)
            if best_projected is not None else None
        ),
        "best_projected_log_growth_gap_vs_required": (
            round(required_log_growth - best_projected, 12)
            if best_projected is not None else None
        ),
        "observed_growth_classification": observed_growth_classification,
        "projection_is_guarantee": False,
        "projection_method": (
            "realized paper PnL windows are annualized to the configured horizon only as descriptive evidence; "
            "dependency gates and required sample sizes still control feasibility"
        ),
        "window_evidence": window_evidence,
    }


def _one_thousand_x_feasibility_classification(
    *,
    blocker_reasons: list[str],
    observed_growth_evidence: dict[str, Any],
    horizon_years: float,
) -> dict[str, Any]:
    horizon_years = max(1.0 / 365.0, float(horizon_years or 0.0))
    horizon_days = max(1.0, horizon_years * 365.0)
    target_multiple = _coerce_float(observed_growth_evidence.get("observed_target_multiple")) or 1000.0
    required_log_growth = _coerce_float(observed_growth_evidence.get("required_log_growth")) or math.log(target_multiple)
    required_daily_log_return = required_log_growth / horizon_days
    required_cagr = math.exp(required_log_growth / horizon_years) - 1.0
    best_projected = _coerce_float(
        observed_growth_evidence.get("best_projected_horizon_log_growth_if_window_repeated")
    )
    observed_daily_log_return = best_projected / horizon_days if best_projected is not None else None
    observed_cagr = math.exp(best_projected / horizon_years) - 1.0 if best_projected is not None else None
    if blocker_reasons:
        classification = "UNSUPPORTED_DEPENDENCY_GATES_NOT_PASSED"
    elif best_projected is None:
        classification = "INSUFFICIENT_OBSERVED_GROWTH_EVIDENCE"
    elif best_projected >= required_log_growth:
        classification = "FEASIBLE_ON_CURRENT_WINDOW_PROJECTION_UNVERIFIED"
    else:
        classification = "NOT_FEASIBLE_ON_CURRENT_OBSERVED_TRAJECTORY"
    return {
        "horizon_days": round(horizon_days, 8),
        "required_growth_multiple": round(target_multiple, 8),
        "required_cagr": round(required_cagr, 12),
        "required_daily_log_return": round(required_daily_log_return, 12),
        "observed_daily_log_return": (
            round(observed_daily_log_return, 12)
            if observed_daily_log_return is not None else None
        ),
        "observed_cagr": round(observed_cagr, 12) if observed_cagr is not None else None,
        "classification": classification,
        "assumption_set": {
            "horizon_years": round(horizon_years, 8),
            "horizon_days": round(horizon_days, 8),
            "target_multiple": round(target_multiple, 8),
            "projection_is_descriptive_only": True,
            "requires_dependency_gates_to_pass": True,
            "guaranteed_return_claim": False,
        },
    }


def _one_thousand_x_status_value(
    *,
    blocker_reasons: list[str],
    classification: str | None,
    horizon_years: float,
    guaranteed_return_claim: bool,
) -> str:
    if blocker_reasons:
        return "UNSUPPORTED_CURRENT_EVIDENCE"
    if horizon_years <= 0.0:
        return "NO_GO_MISSING_EXPLICIT_HORIZON"
    if guaranteed_return_claim:
        return "NO_GO_GUARANTEED_RETURN_CLAIM"
    if classification in {
        "FEASIBLE_ON_CURRENT_WINDOW_PROJECTION_UNVERIFIED",
        "NOT_FEASIBLE_ON_CURRENT_OBSERVED_TRAJECTORY",
    }:
        return "PASSED"
    return "NO_GO_FEASIBILITY_CLASSIFICATION_INSUFFICIENT"


def _condition_status(
    *,
    condition_id: str,
    label: str,
    passed: bool,
    evidence: dict[str, Any],
    blocker_reasons: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": condition_id,
        "label": label,
        "status": "PASSED" if passed else "NO_GO",
        "blocker_reasons": blocker_reasons or ([] if passed else [f"{condition_id.upper()}_NOT_PASSED"]),
        "evidence": evidence,
    }


def _one_thousand_x_explicit_classification_gate(
    thousand_x_status: dict[str, Any],
) -> dict[str, Any]:
    horizon_years = _coerce_float(thousand_x_status.get("horizon_years"))
    horizon_days = _coerce_float(thousand_x_status.get("horizon_days"))
    classification = str(thousand_x_status.get("classification") or "").strip()
    explicit_horizon_classification = (
        bool(classification)
        and horizon_years is not None
        and horizon_years > 0.0
        and horizon_days is not None
        and horizon_days > 0.0
    )
    no_guaranteed_return_claim = thousand_x_status.get("guaranteed_return_claim") is False
    blocker_reasons: list[str] = []
    if not explicit_horizon_classification:
        if not classification:
            blocker_reasons.append("MISSING_FEASIBILITY_CLASSIFICATION")
        if horizon_years is None or horizon_years <= 0.0 or horizon_days is None or horizon_days <= 0.0:
            blocker_reasons.append("MISSING_EXPLICIT_HORIZON")
    if not no_guaranteed_return_claim:
        blocker_reasons.append("GUARANTEED_RETURN_CLAIM")
    return {
        "passed": explicit_horizon_classification and no_guaranteed_return_claim,
        "explicit_horizon_classification": explicit_horizon_classification,
        "no_guaranteed_return_claim": no_guaranteed_return_claim,
        "blocker_reasons": blocker_reasons,
    }


def _pass_condition_status(
    *,
    capital_productivity: dict[str, Any],
    accounting_status: dict[str, Any],
    counterfactual_status: dict[str, Any],
    adaptive_policy_status: dict[str, Any],
    compounding_status: dict[str, Any],
    rare_event_status: dict[str, Any],
    thousand_x_status: dict[str, Any],
    out_of_sample_reverify_status: dict[str, Any],
    enforce_out_of_sample_reverify_gate: bool,
    parity_status: dict[str, Any],
    operator_safety: dict[str, Any],
) -> dict[str, Any]:
    capital_classification = str(capital_productivity.get("capital_utilization_classification") or "")
    thousand_x_explicit_gate = _one_thousand_x_explicit_classification_gate(thousand_x_status)
    safety_passed = (
        operator_safety.get("paper_only") is True
        and operator_safety.get("places_real_order") is False
        and operator_safety.get("test_orders") is False
        and operator_safety.get("leverage_mutation") is False
        and operator_safety.get("margin_mode_mutation") is False
        and operator_safety.get("withdrawals") is False
        and operator_safety.get("transfers") is False
        and operator_safety.get("old_redis_writes") is False
        and operator_safety.get("legacy_restart") is False
        and operator_safety.get("trainer_bridge_unmasked") is False
    )
    no_live_order_blockers = [] if safety_passed else ["OPERATOR_SAFETY_FLAGS_NOT_FAIL_CLOSED"]
    conditions = [
        _condition_status(
            condition_id="no_fixed_runtime_size",
            label="No fixed runtime size",
            passed=adaptive_policy_status.get("no_fixed_runtime_size") is True,
            blocker_reasons=[] if adaptive_policy_status.get("no_fixed_runtime_size") is True else ["FIXED_OR_UNPROVEN_RUNTIME_SIZE"],
            evidence={
                "runtime_size_variation_proven": adaptive_policy_status.get("runtime_size_leverage_evidence", {}).get("runtime_size_variation_proven"),
                "notional_unique_count": adaptive_policy_status.get("runtime_size_leverage_evidence", {}).get("notional_unique_count"),
                "allocated_margin_unique_count": adaptive_policy_status.get("runtime_size_leverage_evidence", {}).get("allocated_margin_unique_count"),
            },
        ),
        _condition_status(
            condition_id="no_fixed_runtime_leverage",
            label="No fixed runtime leverage",
            passed=adaptive_policy_status.get("no_fixed_runtime_leverage") is True,
            blocker_reasons=[] if adaptive_policy_status.get("no_fixed_runtime_leverage") is True else ["FIXED_OR_UNPROVEN_RUNTIME_LEVERAGE"],
            evidence={
                "runtime_leverage_variation_proven": adaptive_policy_status.get("runtime_size_leverage_evidence", {}).get("runtime_leverage_variation_proven"),
                "recommended_leverage_unique_count": adaptive_policy_status.get("runtime_size_leverage_evidence", {}).get("recommended_leverage_unique_count"),
                "effective_leverage_unique_count": adaptive_policy_status.get("runtime_size_leverage_evidence", {}).get("effective_leverage_unique_count"),
                "fixed_leverage_classification": adaptive_policy_status.get("runtime_size_leverage_evidence", {}).get("fixed_leverage_classification"),
            },
        ),
        _condition_status(
            condition_id="adaptive_selection_attribution",
            label="Adaptive capital selection attribution complete",
            passed=(
                (adaptive_policy_status.get("adaptive_selection_attribution_status") or {}).get("status")
                == "PASSED"
            ),
            blocker_reasons=(
                (adaptive_policy_status.get("adaptive_selection_attribution_status") or {}).get("blocker_reasons")
                or []
            ),
            evidence=adaptive_policy_status.get("adaptive_selection_attribution_status") or {},
        ),
        _condition_status(
            condition_id="mandatory_per_trade_accounting",
            label="100% mandatory per-trade margin/leverage accounting",
            passed=(
                accounting_status.get("status") == "PASSED"
                and (
                    accounting_status.get("mandatory_field_coverage") == 1.0
                    or accounting_status.get("current_accounting_enforcement_complete") is True
                )
            ),
            blocker_reasons=[] if accounting_status.get("status") == "PASSED" else [str(accounting_status.get("status"))],
            evidence={
                "new_trade_row_count": accounting_status.get("new_trade_row_count"),
                "rows_with_all_mandatory_fields": accounting_status.get("rows_with_all_mandatory_fields"),
                "mandatory_field_coverage": accounting_status.get("mandatory_field_coverage"),
                "missing_by_field": accounting_status.get("missing_by_field"),
                "leverage_margin_accounting_formula": accounting_status.get("leverage_margin_accounting_formula"),
                "leverage_margin_consistency_coverage": accounting_status.get("leverage_margin_consistency_coverage"),
                "leverage_margin_inconsistent_count": accounting_status.get("leverage_margin_inconsistent_count"),
                "leverage_margin_inconsistent_sample": accounting_status.get("leverage_margin_inconsistent_sample"),
                "runtime_accounting_complete": accounting_status.get("runtime_accounting_complete"),
                "current_accounting_enforcement_complete": (
                    accounting_status.get("current_accounting_enforcement_complete")
                ),
                "current_accounting_enforcement_source": (
                    accounting_status.get("current_accounting_enforcement_source")
                ),
                "historical_runtime_leverage_margin_gap_non_blocking": (
                    accounting_status.get("historical_runtime_leverage_margin_gap_non_blocking")
                ),
                "historical_runtime_mandatory_field_gap_non_blocking": (
                    accounting_status.get("historical_runtime_mandatory_field_gap_non_blocking")
                ),
                "historical_runtime_accounting_gap_non_blocking": (
                    accounting_status.get("historical_runtime_accounting_gap_non_blocking")
                ),
                "current_pre_submit_accounting_evidence": (
                    accounting_status.get("current_pre_submit_accounting_evidence")
                ),
                "accounting_scope": accounting_status.get("accounting_scope"),
            },
        ),
        _condition_status(
            condition_id="policy_activation_and_funding_accounting",
            label="Policy activation timestamps and funding PnL accounted",
            passed=(
                (adaptive_policy_status.get("policy_activation_funding_evidence_status") or {}).get("status")
                == "PASSED"
            ),
            blocker_reasons=(
                (adaptive_policy_status.get("policy_activation_funding_evidence_status") or {}).get("blocker_reasons")
                or []
            ),
            evidence=adaptive_policy_status.get("policy_activation_funding_evidence_status") or {},
        ),
        _condition_status(
            condition_id="capital_idle_classification",
            label="Idle capital classification distinguishes no-edge and allocator underdeployment",
            passed=capital_classification in {
                "ALLOCATOR_UNDERDEPLOYMENT",
                "NO_A_GRADE_EDGE_IDLE",
                "NO_EDGE_IDLE",
                "POSITIVE_EDGE_BELOW_A_GRADE_IDLE",
                "DYNAMIC_A_GRADE_PAPER_DEPLOYMENT_VALIDATED",
                "B_GRADE_EXPLORATION_PAPER_READY",
                "DEPLOYED",
                "UNDEPLOYED_NO_EVIDENCE",
            },
            evidence={
                "capital_utilization_classification": capital_productivity.get("capital_utilization_classification"),
                "idle_capital_no_edge_usd": capital_productivity.get("idle_capital_no_edge_usd"),
                "idle_capital_positive_edge_not_a_grade_usd": capital_productivity.get("idle_capital_positive_edge_not_a_grade_usd"),
                "idle_capital_allocator_rejected_usd": capital_productivity.get("idle_capital_allocator_rejected_usd"),
            },
        ),
        _condition_status(
            condition_id="positive_deployed_margin_return",
            label="Positive net return on deployed margin",
            passed=(_coerce_float(capital_productivity.get("return_on_deployed_margin")) or 0.0) > 0.0,
            blocker_reasons=[] if (_coerce_float(capital_productivity.get("return_on_deployed_margin")) or 0.0) > 0.0 else ["NON_POSITIVE_RETURN_ON_DEPLOYED_MARGIN"],
            evidence={
                "return_on_deployed_margin": capital_productivity.get("return_on_deployed_margin"),
                "net_pnl_per_dollar_margin": capital_productivity.get("net_pnl_per_dollar_margin"),
                "positive_return_on_deployed_margin": capital_productivity.get("positive_return_on_deployed_margin"),
                "post_allocator_realized_pnl_usd": capital_productivity.get("post_allocator_realized_pnl_usd"),
                "closed_deployed_margin_usd": capital_productivity.get("closed_deployed_margin_usd"),
                "return_on_deployed_margin_formula": capital_productivity.get("return_on_deployed_margin_formula"),
                "post_allocator_closed_outcome_count": capital_productivity.get("post_allocator_closed_outcome_count"),
                "accepted_fill_reconciled_closed_outcome_count": (
                    capital_productivity.get("accepted_fill_policy_reconciliation") or {}
                ).get("complete_reconciled_closed_outcome_count"),
            },
        ),
        _condition_status(
            condition_id="positive_after_cost_expectancy",
            label="Positive after-cost expectancy",
            passed=(_coerce_float(capital_productivity.get("after_cost_expectancy_bps")) or 0.0) > 0.0,
            blocker_reasons=[] if (_coerce_float(capital_productivity.get("after_cost_expectancy_bps")) or 0.0) > 0.0 else ["NON_POSITIVE_AFTER_COST_EXPECTANCY"],
            evidence={
                "after_cost_expectancy_bps": capital_productivity.get("after_cost_expectancy_bps"),
                "positive_after_cost_expectancy": capital_productivity.get("positive_after_cost_expectancy"),
                "after_cost_expectancy_source_row_count": capital_productivity.get("after_cost_expectancy_source_row_count"),
                "positive_after_cost_opportunity_row_count": capital_productivity.get("positive_after_cost_opportunity_row_count"),
                "non_positive_after_cost_opportunity_row_count": capital_productivity.get("non_positive_after_cost_opportunity_row_count"),
            },
        ),
        _condition_status(
            condition_id="minimum_profit_factor",
            label="Minimum post-allocator profit factor",
            passed=capital_productivity.get("post_allocator_performance_status") == "PASSED",
            blocker_reasons=[] if capital_productivity.get("post_allocator_performance_status") == "PASSED" else [
                str(capital_productivity.get("post_allocator_performance_status"))
            ],
            evidence={
                "profit_factor": capital_productivity.get("profit_factor"),
                "profit_factor_numeric": capital_productivity.get("profit_factor_numeric"),
                "minimum_required_profit_factor": capital_productivity.get("minimum_required_profit_factor"),
                "profit_factor_gap_to_minimum": capital_productivity.get("profit_factor_gap_to_minimum"),
                "profit_factor_burn_down": capital_productivity.get("profit_factor_burn_down"),
                "post_allocator_win_rate": capital_productivity.get("post_allocator_win_rate"),
                "post_allocator_winning_trade_count": capital_productivity.get("post_allocator_winning_trade_count"),
                "post_allocator_losing_trade_count": capital_productivity.get("post_allocator_losing_trade_count"),
                "post_allocator_realized_profit_usd": capital_productivity.get("post_allocator_realized_profit_usd"),
                "post_allocator_realized_loss_usd": capital_productivity.get("post_allocator_realized_loss_usd"),
                "post_allocator_closed_outcome_count": capital_productivity.get("post_allocator_closed_outcome_count"),
                "profit_factor_formula": capital_productivity.get("profit_factor_formula"),
            },
        ),
        _condition_status(
            condition_id="drawdown_expected_shortfall_within_limits",
            label="Acceptable drawdown and expected shortfall",
            passed=(
                "EXPECTED_SHORTFALL_LIMIT_BREACH" not in (capital_productivity.get("capital_productivity_blocker_reasons") or [])
                and "REALIZED_DRAWDOWN_LIMIT_BREACH" not in (capital_productivity.get("capital_productivity_blocker_reasons") or [])
                and capital_productivity.get("worst_expected_shortfall_pct_of_equity") is not None
            ),
            blocker_reasons=[
                reason for reason in (capital_productivity.get("capital_productivity_blocker_reasons") or [])
                if reason in {"MISSING_EXPECTED_SHORTFALL_EVIDENCE", "EXPECTED_SHORTFALL_LIMIT_BREACH", "REALIZED_DRAWDOWN_LIMIT_BREACH"}
            ],
            evidence={
                "worst_expected_shortfall_pct_of_equity": capital_productivity.get("worst_expected_shortfall_pct_of_equity"),
                "expected_shortfall_limit_pct": capital_productivity.get("expected_shortfall_limit_pct"),
                "realized_drawdown_pct": capital_productivity.get("realized_drawdown_pct"),
                "realized_drawdown_limit_pct": capital_productivity.get("realized_drawdown_limit_pct"),
            },
        ),
        _condition_status(
            condition_id="rare_event_capital_stress",
            label="Rare-event capital stress passes",
            passed=rare_event_status.get("status") == "PASSED",
            blocker_reasons=rare_event_status.get("rare_event_blocker_reasons") or ([] if rare_event_status.get("status") == "PASSED" else [str(rare_event_status.get("status"))]),
            evidence={
                "status": rare_event_status.get("status"),
                "stress_source": rare_event_status.get("stress_source"),
                "completed_scenarios": rare_event_status.get("completed_scenarios"),
            },
        ),
        _condition_status(
            condition_id="counterfactual_a_grade_replay",
            label="Counterfactual replay complete for A-grade signals",
            passed=counterfactual_status.get("status") == "PASSED",
            blocker_reasons=counterfactual_status.get("counterfactual_blocker_reasons") or ([] if counterfactual_status.get("status") == "PASSED" else [str(counterfactual_status.get("status"))]),
            evidence={
                "status": counterfactual_status.get("status"),
                "historical_a_grade_signal_count": counterfactual_status.get("historical_a_grade_signal_count"),
                "event_time_valid_candidate_count": counterfactual_status.get("event_time_valid_candidate_count"),
                "best_configuration_count": counterfactual_status.get("best_configuration_count"),
                "source_coverage_status": counterfactual_status.get("source_coverage", {}).get("source_coverage_status"),
                "strict_a_grade_acquisition_burn_down": (
                    counterfactual_status.get("strict_a_grade_acquisition_burn_down")
                ),
            },
        ),
        _condition_status(
            condition_id="post_policy_outcome_count",
            label="At least 300 post-policy or qualified replay economic outcomes",
            passed=(
                (
                    adaptive_policy_status.get("effective_policy_outcome_count")
                    or adaptive_policy_status.get("post_allocator_closed_outcome_count")
                    or 0
                )
                >= (adaptive_policy_status.get("minimum_required_closed_outcomes") or MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES)
            ),
            blocker_reasons=[] if (
                (
                    adaptive_policy_status.get("effective_policy_outcome_count")
                    or adaptive_policy_status.get("post_allocator_closed_outcome_count")
                    or 0
                )
                >= (adaptive_policy_status.get("minimum_required_closed_outcomes") or MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES)
            ) else ["INSUFFICIENT_POST_ALLOCATOR_CLOSED_OUTCOMES"],
            evidence={
                "post_allocator_closed_outcome_count": adaptive_policy_status.get("post_allocator_closed_outcome_count"),
                "effective_policy_outcome_count": adaptive_policy_status.get("effective_policy_outcome_count"),
                "minimum_required_closed_outcomes": adaptive_policy_status.get("minimum_required_closed_outcomes"),
                "policy_evidence_basis": adaptive_policy_status.get("policy_evidence_basis"),
                "qualified_replay_policy_evidence_status": (
                    adaptive_policy_status.get("qualified_replay_policy_evidence_status")
                ),
                "accepted_fill_reconciled_closed_outcome_count": (
                    adaptive_policy_status.get("accepted_fill_policy_reconciliation") or {}
                ).get("complete_reconciled_closed_outcome_count"),
            },
        ),
        _condition_status(
            condition_id="both_long_short_evidence",
            label="Both LONG and SHORT outcome evidence",
            passed=adaptive_policy_status.get("both_long_short_evidence") is True,
            blocker_reasons=adaptive_policy_status.get("missing_directional_sides") or ([] if adaptive_policy_status.get("both_long_short_evidence") is True else ["MISSING_DIRECTIONAL_EVIDENCE"]),
            evidence={
                "long_closed_outcome_count": adaptive_policy_status.get("long_closed_outcome_count"),
                "short_closed_outcome_count": adaptive_policy_status.get("short_closed_outcome_count"),
                "missing_directional_sides": adaptive_policy_status.get("missing_directional_sides"),
            },
        ),
        _condition_status(
            condition_id="symbol_diversity",
            label="Minimum post-policy or qualified replay symbol diversity",
            passed=(
                (
                    adaptive_policy_status.get("effective_policy_symbol_diversity_deficit")
                    if adaptive_policy_status.get("effective_policy_symbol_diversity_deficit") is not None
                    else adaptive_policy_status.get("symbol_diversity_deficit")
                )
                or 0
            ) <= 0,
            blocker_reasons=[] if (
                (
                    adaptive_policy_status.get("effective_policy_symbol_diversity_deficit")
                    if adaptive_policy_status.get("effective_policy_symbol_diversity_deficit") is not None
                    else adaptive_policy_status.get("symbol_diversity_deficit")
                )
                or 0
            ) <= 0 else ["INSUFFICIENT_SYMBOL_DIVERSITY"],
            evidence={
                "symbol_count": adaptive_policy_status.get("symbol_count"),
                "effective_policy_symbol_count": adaptive_policy_status.get("effective_policy_symbol_count"),
                "minimum_required_symbol_count": adaptive_policy_status.get("minimum_required_symbol_count"),
                "symbol_diversity_deficit": adaptive_policy_status.get("symbol_diversity_deficit"),
                "effective_policy_symbol_diversity_deficit": (
                    adaptive_policy_status.get("effective_policy_symbol_diversity_deficit")
                ),
                "policy_evidence_basis": adaptive_policy_status.get("policy_evidence_basis"),
            },
        ),
        _condition_status(
            condition_id="paper_live_pre_submit_parity",
            label="Paper/live pre-submit parity without exchange mutation",
            passed=parity_status.get("status") == "PASSED",
            blocker_reasons=parity_status.get("parity_blocker_reasons") or ([] if parity_status.get("status") == "PASSED" else [str(parity_status.get("status"))]),
            evidence={
                "status": parity_status.get("status"),
                "sized_pre_submit_candidate_count": parity_status.get("sized_pre_submit_candidate_count"),
                "effective_pre_submit_evidence_source": parity_status.get("effective_pre_submit_evidence_source"),
                "effective_versioned_sized_pre_submit_candidate_count": parity_status.get("effective_versioned_sized_pre_submit_candidate_count"),
                "durable_accepted_pre_submit_used_for_gate": parity_status.get("durable_accepted_pre_submit_used_for_gate"),
                "durable_accepted_pre_submit_status": (
                    parity_status.get("durable_accepted_pre_submit_evidence") or {}
                ).get("status"),
                "durable_versioned_sized_accepted_candidate_count": (
                    parity_status.get("durable_accepted_pre_submit_evidence") or {}
                ).get("versioned_sized_accepted_candidate_count"),
                "durable_versioned_candidate_field_coverage": (
                    parity_status.get("durable_accepted_pre_submit_evidence") or {}
                ).get("versioned_candidate_field_coverage"),
                "durable_versioned_candidate_failure_count": (
                    parity_status.get("durable_accepted_pre_submit_evidence") or {}
                ).get("versioned_candidate_failure_count"),
                "effective_liquidation_buffer_minimum_verified": (
                    parity_status.get("effective_liquidation_buffer_minimum_verified")
                ),
                "effective_liquidation_buffer_minimum_evidence": (
                    parity_status.get("effective_liquidation_buffer_minimum_evidence")
                ),
                "candidate_failure_count": parity_status.get("candidate_failure_count"),
            },
        ),
        _condition_status(
            condition_id="out_of_sample_live_grade_reverify",
            label="Frozen selector passes untouched holdout and realtime paper reverify",
            passed=(
                not enforce_out_of_sample_reverify_gate
                or out_of_sample_reverify_status.get("status") == "PASSED"
            ),
            blocker_reasons=(
                []
                if not enforce_out_of_sample_reverify_gate
                else out_of_sample_reverify_status.get("blocker_reasons")
                or ([] if out_of_sample_reverify_status.get("status") == "PASSED" else [str(out_of_sample_reverify_status.get("status"))])
            ),
            evidence={
                "enforced": enforce_out_of_sample_reverify_gate,
                "gate_id": out_of_sample_reverify_status.get("goal_id"),
                "status": out_of_sample_reverify_status.get("status"),
                "honest_interpretation": out_of_sample_reverify_status.get("honest_interpretation"),
                "frozen_selector_policy_fingerprint": (
                    (out_of_sample_reverify_status.get("frozen_policy_manifest") or {})
                    .get("selector_policy_fingerprint")
                ),
                "holdout_status": (
                    (out_of_sample_reverify_status.get("holdout_reverify_status") or {})
                    .get("status")
                ),
                "holdout_valid_frozen_selector_row_count": (
                    (out_of_sample_reverify_status.get("holdout_reverify_status") or {})
                    .get("valid_frozen_selector_row_count")
                ),
                "realtime_paper_status": (
                    (out_of_sample_reverify_status.get("realtime_paper_reverify_status") or {})
                    .get("status")
                ),
                "realtime_valid_frozen_selector_row_count": (
                    (out_of_sample_reverify_status.get("realtime_paper_reverify_status") or {})
                    .get("valid_frozen_selector_row_count")
                ),
                "realtime_vs_replay_projection_status": (
                    out_of_sample_reverify_status.get("realtime_vs_replay_projection_status")
                ),
                "required_evidence": out_of_sample_reverify_status.get("required_evidence"),
            },
        ),
        _condition_status(
            condition_id="no_real_order_or_exchange_mutation",
            label="No real order or exchange mutation",
            passed=safety_passed,
            blocker_reasons=no_live_order_blockers,
            evidence=operator_safety,
        ),
        _condition_status(
            condition_id="compounding_evidence",
            label="Compounding evidence passes",
            passed=compounding_status.get("status") == "PASSED",
            blocker_reasons=compounding_status.get("compounding_blocker_reasons") or ([] if compounding_status.get("status") == "PASSED" else [str(compounding_status.get("status"))]),
            evidence={
                "status": compounding_status.get("status"),
                "policy_evidence_status": compounding_status.get("policy_evidence_status"),
                "policy_evidence_blocker_reasons": compounding_status.get("policy_evidence_blocker_reasons"),
                "counterfactual_efficient_frontier_ready": compounding_status.get("counterfactual_efficient_frontier_ready"),
                "counterfactual_status": compounding_status.get("counterfactual_status"),
                "counterfactual_best_configuration_count": compounding_status.get("counterfactual_best_configuration_count"),
                "counterfactual_total_expected_log_growth": compounding_status.get("counterfactual_total_expected_log_growth"),
                "closed_outcome_evidence_count": compounding_status.get("closed_outcome_evidence_count"),
                "effective_policy_outcome_count": compounding_status.get("effective_policy_outcome_count"),
                "minimum_required_closed_outcomes": compounding_status.get("minimum_required_closed_outcomes"),
                "closed_outcome_deficit_to_minimum": compounding_status.get("closed_outcome_deficit_to_minimum"),
                "effective_policy_closed_outcome_deficit_to_minimum": (
                    compounding_status.get("effective_policy_closed_outcome_deficit_to_minimum")
                ),
                "policy_evidence_basis": compounding_status.get("policy_evidence_basis"),
                "accepted_fill_reconciled_closed_outcome_count": (
                    compounding_status.get("accepted_fill_policy_reconciliation") or {}
                ).get("complete_reconciled_closed_outcome_count"),
                "post_allocator_symbol_count": compounding_status.get("post_allocator_symbol_count"),
                "effective_policy_symbol_count": compounding_status.get("effective_policy_symbol_count"),
                "minimum_required_symbol_count": compounding_status.get("minimum_required_symbol_count"),
                "symbol_diversity_deficit": compounding_status.get("symbol_diversity_deficit"),
                "effective_policy_symbol_diversity_deficit": (
                    compounding_status.get("effective_policy_symbol_diversity_deficit")
                ),
                "long_closed_outcome_count": compounding_status.get("long_closed_outcome_count"),
                "short_closed_outcome_count": compounding_status.get("short_closed_outcome_count"),
                "positive_return_on_deployed_margin": compounding_status.get("positive_return_on_deployed_margin"),
                "post_allocator_realized_pnl_usd": compounding_status.get("post_allocator_realized_pnl_usd"),
                "closed_deployed_margin_usd": compounding_status.get("closed_deployed_margin_usd"),
                "return_on_deployed_margin": compounding_status.get("return_on_deployed_margin"),
            },
        ),
        _condition_status(
            condition_id="one_thousand_x_explicit_horizon_classification",
            label="1000x feasibility classified against explicit horizon without guarantee",
            passed=bool(thousand_x_explicit_gate["passed"]),
            blocker_reasons=thousand_x_explicit_gate["blocker_reasons"],
            evidence={
                "status": thousand_x_status.get("status"),
                "classification": thousand_x_status.get("classification"),
                "horizon_years": thousand_x_status.get("horizon_years"),
                "horizon_days": thousand_x_status.get("horizon_days"),
                "guaranteed_return_claim": thousand_x_status.get("guaranteed_return_claim"),
                "explicit_horizon_classification": thousand_x_explicit_gate["explicit_horizon_classification"],
                "no_guaranteed_return_claim": thousand_x_explicit_gate["no_guaranteed_return_claim"],
                "feasibility_blocker_reasons": thousand_x_status.get("feasibility_blocker_reasons") or [],
            },
        ),
    ]
    counts: dict[str, int] = {}
    for condition in conditions:
        status = str(condition.get("status"))
        counts[status] = counts.get(status, 0) + 1
    failed_conditions = [condition["id"] for condition in conditions if condition.get("status") != "PASSED"]
    return {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "status": "PASSED" if not failed_conditions else "NO_GO",
        "condition_status_counts": counts,
        "failed_conditions": failed_conditions,
        "conditions": conditions,
    }


def build_statuses(
    *,
    ledger: dict[str, Any],
    portfolio: dict[str, Any],
    paper_status: dict[str, Any],
    paper_intents: list[dict[str, Any]] | None = None,
    paper_signals: list[dict[str, Any]] | None = None,
    prediction_rows: list[dict[str, Any]] | None = None,
    feature_rows: list[dict[str, Any]] | None = None,
    post_hoc_replay_bundles: list[dict[str, Any]] | None = None,
    post_hoc_replay_bundle_path: Path | None = None,
    native_trainer_replay_evidence_rows: list[dict[str, Any]] | None = None,
    native_trainer_replay_evidence_path: Path | None = None,
    closed_candle_replay_evidence_rows: list[dict[str, Any]] | None = None,
    closed_candle_replay_evidence_path: Path | None = None,
    out_of_sample_holdout_reverify_rows: list[dict[str, Any]] | None = None,
    out_of_sample_holdout_reverify_path: Path | None = None,
    out_of_sample_realtime_reverify_rows: list[dict[str, Any]] | None = None,
    out_of_sample_realtime_reverify_path: Path | None = None,
    enforce_out_of_sample_reverify_gate: bool = False,
    correlation_candles_by_symbol: dict[str, list[Any]] | None = None,
    correlation_candle_sources_by_symbol: dict[str, str] | None = None,
    horizon_years: float,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    generated_utc = generated_utc or _utc_iso()
    paper_intents = [dict(row) for row in (paper_intents or []) if isinstance(row, dict)]
    paper_signals = [dict(row) for row in (paper_signals or []) if isinstance(row, dict)]
    prediction_rows = [dict(row) for row in (prediction_rows or []) if isinstance(row, dict)]
    feature_rows = [dict(row) for row in (feature_rows or []) if isinstance(row, dict)]
    prediction_rows = _prediction_rows_with_pit_feature_market_cost_context(
        prediction_rows,
        feature_rows,
    )
    feature_snapshot_lookup_audit = _feature_snapshot_lookup_audit(
        decision_rows=[*prediction_rows, *paper_signals, *paper_intents],
        feature_rows=feature_rows,
    )
    latest_feature_row_count = sum(
        1 for row in feature_rows
        if str(row.get("source_redis_key") or "").startswith("v2:features:latest:")
    )
    archived_feature_row_count = sum(
        1 for row in feature_rows
        if str(row.get("source_redis_key") or "").startswith("v2:features:snapshot:")
    )
    for row in prediction_rows:
        row.setdefault("counterfactual_source_kind", "prediction")
    open_positions = _safe_rows(ledger, "open_positions")
    raw_closed_trades = _safe_rows(ledger, "closed_trades")
    accepted_rows = _safe_rows(ledger, "accepted")
    closed_trades, accepted_fill_reconciliation = _reconcile_closed_trades_with_accepted_fills(
        closed_trades=raw_closed_trades,
        accepted_rows=accepted_rows,
    )
    post_policy_closed = [row for row in closed_trades if row.get("paper_exit_policy_version") == P0_POLICY_VERSION]
    runtime_rows = post_policy_closed + open_positions
    new_trade_rows = [row for row in runtime_rows if _is_adaptive_capital_policy_row(row)]
    pre_submit_policy_rows = [
        row for row in paper_intents
        if _is_adaptive_capital_policy_row(row) and _is_sized_pre_submit_intent(row)
    ]
    durable_pre_submit_evidence = _durable_accepted_pre_submit_evidence(
        ledger=ledger,
        generated_utc=generated_utc,
    )
    allocator_calibration_status = _allocator_calibration_status(
        rows=[*new_trade_rows, *pre_submit_policy_rows, *accepted_rows],
        generated_utc=generated_utc,
        current_intent_rows=paper_intents,
    )
    post_capital_policy_open = [row for row in open_positions if _is_adaptive_capital_policy_row(row)]
    post_capital_policy_closed = [row for row in post_policy_closed if _is_adaptive_capital_policy_row(row)]
    policy_activation_funding_evidence_status = _policy_activation_funding_evidence_status(
        accepted_rows=accepted_rows,
        open_rows=post_capital_policy_open,
        closed_rows=post_capital_policy_closed,
        portfolio=portfolio,
        generated_utc=generated_utc,
    )
    post_allocator_closed = _rows_with_complete_mandatory_fields(post_capital_policy_closed)
    complete_open_post_capital_policy = _rows_with_complete_mandatory_fields(post_capital_policy_open)
    complete_new_trade_rows = _rows_with_complete_mandatory_fields(new_trade_rows)
    unversioned_runtime_rows = [row for row in runtime_rows if not _is_adaptive_capital_policy_row(row)]
    complete_unversioned_runtime_rows = _rows_with_complete_mandatory_fields(unversioned_runtime_rows)
    closed_outcome_evidence_gap_analysis = _closed_outcome_evidence_gap_analysis(
        raw_closed_trades=raw_closed_trades,
        post_policy_closed=post_policy_closed,
        post_capital_policy_closed=post_capital_policy_closed,
        post_allocator_closed=post_allocator_closed,
        post_capital_policy_open=post_capital_policy_open,
        complete_open_post_capital_policy=complete_open_post_capital_policy,
        accepted_fill_reconciliation=accepted_fill_reconciliation,
    )
    open_notional = sum(_notional(row) for row in open_positions)
    open_margin = sum(_margin(row) for row in open_positions)
    closed_notional = sum(_notional(row) for row in post_allocator_closed)
    closed_margin = sum(_margin(row) for row in post_allocator_closed)
    realized_pnl = sum(_pnl(row) for row in closed_trades)
    post_allocator_realized_pnl = sum(_pnl(row) for row in post_allocator_closed)
    post_allocator_performance = _post_allocator_performance_metrics(post_allocator_closed)
    equity = (
        _coerce_float(_first_present(portfolio.get("equity"), portfolio.get("equity_usd"), ledger.get("equity_usd")))
        or 10000.0 + realized_pnl
    )
    available_margin = max(0.0, equity - open_margin)
    counterfactual_paper_signals = _counterfactual_signal_rows_with_prediction_temporal_context(
        paper_signals=paper_signals,
        prediction_rows=prediction_rows,
        feature_rows=feature_rows,
    )
    counterfactual_temporal_enriched_paper_signals = [
        row for row in counterfactual_paper_signals
        if row.get("counterfactual_temporal_enrichment_fields")
    ]
    counterfactual_signal_quality_enriched_paper_signals = [
        row for row in counterfactual_paper_signals
        if row.get("counterfactual_signal_quality_enrichment_fields")
    ]
    counterfactual_market_cost_enriched_paper_signals = [
        row for row in counterfactual_paper_signals
        if row.get("counterfactual_market_cost_enrichment_fields")
    ]
    counterfactual_feature_market_cost_enriched_paper_signals = [
        row for row in counterfactual_paper_signals
        if row.get("counterfactual_feature_market_cost_enrichment_fields")
        or (
            row.get("counterfactual_market_cost_enrichment_fields")
            and isinstance(row.get("market_cost_evidence_source_lineage"), dict)
            and row["market_cost_evidence_source_lineage"].get("source")
            in {
                "status_generator_pit_latest_feature_payload_explicit_fields_only",
                "status_generator_pit_feature_payload_fields_with_modeled_slippage_from_pit_spread",
            }
        )
    ]
    durable_accepted_counterfactual_rows, durable_accepted_counterfactual_evidence = (
        _paper_ledger_accepted_counterfactual_rows(
            ledger_payload=ledger,
            base_source_rows=[*counterfactual_paper_signals, *paper_intents],
        )
    )
    signal_opportunity_rows = counterfactual_paper_signals + paper_intents
    opportunity_rows = signal_opportunity_rows if signal_opportunity_rows else runtime_rows
    counterfactual_rows = (
        counterfactual_paper_signals
        + paper_intents
        + durable_accepted_counterfactual_rows
        + runtime_rows
    )
    counterfactual_sourced_rows: list[tuple[str, dict[str, Any]]] = [
        *[("paper_signal", row) for row in counterfactual_paper_signals],
        *[("paper_intent", row) for row in paper_intents],
        *[("paper_ledger_accepted", row) for row in durable_accepted_counterfactual_rows],
        *[("paper_ledger", row) for row in runtime_rows],
    ]
    a_grade_blocker_analysis = _a_grade_blocker_analysis(counterfactual_sourced_rows)
    pnl_history_status = _pnl_history_status(
        closed_trades=closed_trades,
        generated_utc=generated_utc,
    )
    signal_prediction_accuracy_status = _signal_prediction_accuracy_status(
        rows=paper_signals + paper_intents + prediction_rows + closed_trades,
        generated_utc=generated_utc,
    )
    if post_hoc_replay_bundles is not None or post_hoc_replay_bundle_path is not None:
        post_hoc_replay_audit, post_hoc_replay_label_rows = _post_hoc_replay_bundle_audit(
            bundle_rows=post_hoc_replay_bundles,
            path=post_hoc_replay_bundle_path or POST_HOC_REPLAY_BUNDLE_PATH,
        )
    else:
        post_hoc_replay_audit, post_hoc_replay_label_rows = _post_hoc_replay_bundle_audit(
            bundle_rows=[],
        )
    if (
        native_trainer_replay_evidence_rows is not None
        or native_trainer_replay_evidence_path is not None
    ):
        native_trainer_replay_audit, native_trainer_replay_label_rows = (
            _native_trainer_replay_evidence_audit(
                evidence_rows=native_trainer_replay_evidence_rows,
                path=(
                    native_trainer_replay_evidence_path
                    or NATIVE_TRAINER_REPLAY_EVIDENCE_ROWS_PATH
                ),
            )
        )
    else:
        native_trainer_replay_audit, native_trainer_replay_label_rows = (
            _native_trainer_replay_evidence_audit(evidence_rows=[])
        )
    if (
        closed_candle_replay_evidence_rows is not None
        or closed_candle_replay_evidence_path is not None
    ):
        closed_candle_replay_audit, closed_candle_replay_label_rows = (
            _closed_candle_replay_evidence_audit(
                evidence_rows=closed_candle_replay_evidence_rows,
                path=(
                    closed_candle_replay_evidence_path
                    or CLOSED_CANDLE_REPLAY_EVIDENCE_ROWS_PATH
                ),
            )
        )
    else:
        closed_candle_replay_audit, closed_candle_replay_label_rows = (
            _closed_candle_replay_evidence_audit(evidence_rows=[])
        )
    out_of_sample_holdout_rows, out_of_sample_holdout_source_status = _load_reverify_rows(
        rows=out_of_sample_holdout_reverify_rows,
        path=out_of_sample_holdout_reverify_path,
        default_path=OUT_OF_SAMPLE_HOLDOUT_REVERIFY_ROWS_PATH,
        source="out_of_sample_holdout_reverify",
    )
    out_of_sample_realtime_rows, out_of_sample_realtime_source_status = _load_reverify_rows(
        rows=out_of_sample_realtime_reverify_rows,
        path=out_of_sample_realtime_reverify_path,
        default_path=OUT_OF_SAMPLE_REALTIME_REVERIFY_ROWS_PATH,
        source="out_of_sample_realtime_paper_reverify",
    )
    audited_replay_label_rows = [
        *post_hoc_replay_label_rows,
        *native_trainer_replay_label_rows,
        *closed_candle_replay_label_rows,
    ]
    counterfactual_rows_with_replay = [
        *counterfactual_rows,
        *audited_replay_label_rows,
    ]
    (
        a_grade_dynamic_calibration_status,
        a_grade_bucket_performance_matrix,
        positive_edge_below_a_grade_resolution,
    ) = _dynamic_a_grade_calibration_artifacts(
        evaluated_rows=[
            *closed_trades,
            *paper_signals,
            *paper_intents,
            *prediction_rows,
            *audited_replay_label_rows,
        ],
        candidate_rows=[*opportunity_rows, *audited_replay_label_rows],
        generated_utc=generated_utc,
    )
    a_grade_rows = [row for row in opportunity_rows if _is_a_grade(row)]
    counterfactual_a_grade_rows = [row for row in counterfactual_rows_with_replay if _is_a_grade(row)]
    funded_a_grade = [row for row in a_grade_rows if _notional(row) > 0 and _margin(row) > 0]
    underfunded_a_grade = [row for row in a_grade_rows if row not in funded_a_grade]
    missing_by_field = {
        field: sum(1 for row in new_trade_rows if not _field_present(row, field))
        for field in MANDATORY_PER_TRADE_FIELDS
    }
    rows_with_all_fields = len(complete_new_trade_rows)
    field_coverage = rows_with_all_fields / len(new_trade_rows) if new_trade_rows else 0.0
    leverage_margin_consistency = _leverage_margin_consistency_status(new_trade_rows)
    active_pre_submit_accounting_evidence = _accounting_enforcement_evidence(
        pre_submit_policy_rows,
        source="active_or_held_pre_submit_paper_intents",
    )
    durable_pre_submit_accounting_evidence = (
        durable_pre_submit_evidence.get("versioned_candidate_accounting_evidence")
        if isinstance(durable_pre_submit_evidence.get("versioned_candidate_accounting_evidence"), dict)
        else {}
    )
    durable_pre_submit_accounting_complete = (
        durable_pre_submit_evidence.get("status") == "PASSED"
        and bool(durable_pre_submit_accounting_evidence.get("complete"))
    )
    if active_pre_submit_accounting_evidence.get("row_count", 0) > 0:
        current_pre_submit_accounting_evidence = active_pre_submit_accounting_evidence
    elif durable_pre_submit_accounting_complete:
        current_pre_submit_accounting_evidence = durable_pre_submit_accounting_evidence
    else:
        current_pre_submit_accounting_evidence = active_pre_submit_accounting_evidence
    side_counts: dict[str, int] = {}
    symbol_counts: dict[str, int] = {}
    for row in post_allocator_closed:
        side = str(_first_present(row.get("side"), row.get("action"), "unknown")).lower()
        symbol = str(row.get("symbol") or "UNKNOWN").upper()
        side_counts[side] = side_counts.get(side, 0) + 1
        symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
    monthly_required, daily_required = _monthly_daily_required_multiple(horizon_years=horizon_years)
    evidence_count = len(post_allocator_closed)
    long_count = side_counts.get("long", 0)
    short_count = side_counts.get("short", 0)
    both_long_short_evidence = long_count > 0 and short_count > 0
    missing_directional_sides = [
        side for side, count in (("long", long_count), ("short", short_count))
        if count <= 0
    ]
    symbol_count = len([symbol for symbol, count in symbol_counts.items() if symbol and count > 0])
    symbol_diversity_deficit = max(0, MINIMUM_POLICY_SYMBOL_COUNT - symbol_count)
    symbol_diversity_opportunity_analysis = _symbol_diversity_opportunity_analysis(
        post_allocator_closed=post_allocator_closed,
        complete_open_post_capital_policy=complete_open_post_capital_policy,
        paper_signals=paper_signals,
        paper_intents=paper_intents,
        prediction_rows=prediction_rows,
        counterfactual_rows=counterfactual_rows,
    )
    closed_outcome_deficit_to_minimum = max(0, MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES - evidence_count)
    runtime_accounting_complete = (
        bool(new_trade_rows)
        and field_coverage >= 1.0
        and leverage_margin_consistency["status"] == "PASSED"
    )
    current_accounting_enforcement_complete = bool(
        current_pre_submit_accounting_evidence.get("complete")
    )
    historical_leverage_margin_gap_non_blocking = (
        bool(new_trade_rows)
        and field_coverage >= 1.0
        and leverage_margin_consistency["status"] != "PASSED"
        and current_accounting_enforcement_complete
    )
    historical_mandatory_field_gap_non_blocking = (
        bool(new_trade_rows)
        and field_coverage < 1.0
        and current_accounting_enforcement_complete
    )
    historical_runtime_accounting_gap_non_blocking = (
        bool(new_trade_rows)
        and not runtime_accounting_complete
        and current_accounting_enforcement_complete
    )
    accounting_pass = runtime_accounting_complete or historical_runtime_accounting_gap_non_blocking
    accounting_status_value = (
        "PASSED"
        if accounting_pass
        else "NO_GO_NO_POST_CAPITAL_POLICY_ROWS" if not new_trade_rows else "NO_GO_FIELD_COVERAGE_INCOMPLETE"
        if field_coverage < 1.0 else "NO_GO_LEVERAGE_MARGIN_ACCOUNTING_INCONSISTENT"
    )
    accounting_enforcement_status = (
        "PASSED_RUNTIME_ACCOUNTING"
        if runtime_accounting_complete
        else "PASSED_CURRENT_PRE_SUBMIT_ENFORCEMENT"
        if current_accounting_enforcement_complete
        else accounting_status_value
    )
    policy_evidence_blocker_reasons: list[str] = []
    if evidence_count < MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES:
        policy_evidence_blocker_reasons.append("INSUFFICIENT_POST_ALLOCATOR_CLOSED_OUTCOMES")
    if long_count <= 0:
        policy_evidence_blocker_reasons.append("MISSING_LONG_OUTCOME_EVIDENCE")
    if short_count <= 0:
        policy_evidence_blocker_reasons.append("MISSING_SHORT_OUTCOME_EVIDENCE")
    if symbol_count < MINIMUM_POLICY_SYMBOL_COUNT:
        policy_evidence_blocker_reasons.append("INSUFFICIENT_SYMBOL_DIVERSITY")
    policy_variation_evidence = _policy_variation_evidence(new_trade_rows)
    adaptive_field_selection_evidence = _adaptive_field_selection_evidence(new_trade_rows)
    pre_submit_policy_variation_evidence = _policy_variation_evidence(pre_submit_policy_rows)
    pre_submit_adaptive_field_selection_evidence = _adaptive_field_selection_evidence(pre_submit_policy_rows)
    adaptive_selection_attribution_status = _adaptive_selection_attribution_status(
        adaptive_field_selection_evidence,
        pre_submit_evidence=pre_submit_adaptive_field_selection_evidence,
        durable_pre_submit_evidence=durable_pre_submit_evidence,
    )
    if policy_activation_funding_evidence_status["status"] != "PASSED":
        policy_evidence_blocker_reasons.extend(
            policy_activation_funding_evidence_status["blocker_reasons"]
        )
    policy_evidence_blocker_reasons.extend(policy_variation_evidence["variation_blocker_reasons"])
    policy_evidence_blocker_reasons.extend(adaptive_selection_attribution_status["blocker_reasons"])
    evidence_count_pass = not policy_evidence_blocker_reasons
    capital_risk_envelope = CounterfactualRiskEnvelope()
    return_on_deployed_margin = (
        round(post_allocator_realized_pnl / closed_margin, 8)
        if closed_margin > 0
        else None
    )
    positive_return_on_deployed_margin = (
        return_on_deployed_margin is not None and return_on_deployed_margin > 0.0
    )
    opportunity_edge_values = [
        value for row in opportunity_rows
        for value in [_expected_edge_bps(row)]
        if value is not None
    ]
    after_cost_expectancy_bps = (
        round(sum(opportunity_edge_values) / len(opportunity_edge_values), 8)
        if opportunity_edge_values
        else None
    )
    positive_after_cost_expectancy = (
        after_cost_expectancy_bps is not None and after_cost_expectancy_bps > 0.0
    )
    positive_after_cost_rows = sum(1 for value in opportunity_edge_values if value > 0.0)
    positive_edge_non_a_grade_rows = [
        row for row in opportunity_rows
        if (_expected_edge_bps(row) or 0.0) > 0.0 and not _is_a_grade(row)
    ]
    positive_edge_non_a_grade_diagnostics = _positive_edge_non_a_grade_diagnostics(
        positive_edge_non_a_grade_rows
    )
    dynamic_eligible_bucket_keys = _eligible_bucket_keys_from_matrix(
        a_grade_bucket_performance_matrix
    )
    dynamic_a_grade_candidate_rows = [
        row for row in [*opportunity_rows, *audited_replay_label_rows]
        if tuple(str(value) for value in _a_grade_bucket_key(row)) in dynamic_eligible_bucket_keys
        and (_expected_edge_bps(row) or 0.0) > 0.0
        and _directional_side(row) in {"long", "short"}
        and not _pre_submit_temporal_reasons(row)
        and not _allocator_decision(row).startswith("BLOCK_")
    ]
    dynamic_a_grade_funded_rows = [
        row for row in dynamic_a_grade_candidate_rows
        if _notional(row) > 0.0 and _margin(row) > 0.0
    ]
    dynamic_a_grade_funded_row_ids = {
        _row_identity(row) for row in dynamic_a_grade_funded_rows
    }
    dynamic_a_grade_underfunded_rows = [
        row for row in dynamic_a_grade_candidate_rows
        if _row_identity(row) not in dynamic_a_grade_funded_row_ids
    ]
    b_grade_exploration_candidate_count = int(
        positive_edge_below_a_grade_resolution.get("b_grade_exploration_candidate_count") or 0
    )
    effective_a_grade_opportunity_count = (
        len(dynamic_a_grade_candidate_rows)
        if dynamic_a_grade_candidate_rows else len(a_grade_rows)
    )
    effective_a_grade_opportunities_funded = (
        len(dynamic_a_grade_funded_rows)
        if dynamic_a_grade_candidate_rows else len(funded_a_grade)
    )
    effective_a_grade_opportunities_underfunded = (
        len(dynamic_a_grade_underfunded_rows)
        if dynamic_a_grade_candidate_rows else len(underfunded_a_grade)
    )
    effective_a_grade_underfunded_rows = (
        dynamic_a_grade_underfunded_rows
        if dynamic_a_grade_candidate_rows else underfunded_a_grade
    )
    shortfall_values = [
        value for row in new_trade_rows
        for value in [_expected_shortfall_usd(row)]
        if value is not None
    ]
    worst_expected_shortfall_usd = max(shortfall_values, default=None)
    worst_expected_shortfall_pct = (
        round(worst_expected_shortfall_usd / equity, 8)
        if worst_expected_shortfall_usd is not None and equity > 0
        else None
    )
    drawdown_starting_equity = max(1.0, equity - post_allocator_realized_pnl)
    realized_drawdown_pct = round(_realized_drawdown_pct(post_allocator_closed, drawdown_starting_equity), 8)
    capital_utilization_classification = (
        "ALLOCATOR_UNDERDEPLOYMENT"
        if effective_a_grade_underfunded_rows
        else "DYNAMIC_A_GRADE_PAPER_DEPLOYMENT_VALIDATED"
        if dynamic_a_grade_candidate_rows
        else "B_GRADE_EXPLORATION_PAPER_READY"
        if not a_grade_rows and b_grade_exploration_candidate_count > 0
        else "POSITIVE_EDGE_BELOW_A_GRADE_IDLE"
        if not a_grade_rows and positive_edge_non_a_grade_rows and available_margin > 0.0
        else "NO_EDGE_IDLE"
        if not a_grade_rows and available_margin > 0.0
        else "DEPLOYED"
        if open_margin > 0.0
        else "UNDEPLOYED_NO_EVIDENCE"
    )
    capital_blocker_reasons: list[str] = []
    if open_margin <= 0.0:
        capital_blocker_reasons.append("NO_DEPLOYED_OPEN_MARGIN")
    if closed_margin <= 0.0:
        capital_blocker_reasons.append("NO_CLOSED_DEPLOYED_MARGIN")
    elif return_on_deployed_margin is None or return_on_deployed_margin <= 0.0:
        capital_blocker_reasons.append("NON_POSITIVE_RETURN_ON_DEPLOYED_MARGIN")
    if after_cost_expectancy_bps is None:
        capital_blocker_reasons.append("MISSING_AFTER_COST_EXPECTANCY")
    elif after_cost_expectancy_bps <= 0.0:
        capital_blocker_reasons.append("NON_POSITIVE_AFTER_COST_EXPECTANCY")
    if opportunity_edge_values and positive_after_cost_rows <= 0:
        capital_blocker_reasons.append("NON_POSITIVE_AFTER_COST_OPPORTUNITY_ROWS")
    if post_allocator_performance["status"] == "NO_GO_PROFIT_FACTOR_BELOW_MINIMUM":
        capital_blocker_reasons.append("PROFIT_FACTOR_BELOW_MINIMUM")
    elif post_allocator_performance["status"] == "NO_GO_PROFIT_FACTOR_UNAVAILABLE":
        capital_blocker_reasons.append("PROFIT_FACTOR_UNAVAILABLE")
    if worst_expected_shortfall_pct is None:
        capital_blocker_reasons.append("MISSING_EXPECTED_SHORTFALL_EVIDENCE")
    elif worst_expected_shortfall_pct > capital_risk_envelope.max_expected_shortfall_pct:
        capital_blocker_reasons.append("EXPECTED_SHORTFALL_LIMIT_BREACH")
    if realized_drawdown_pct > capital_risk_envelope.max_drawdown_pct:
        capital_blocker_reasons.append("REALIZED_DRAWDOWN_LIMIT_BREACH")
    if capital_utilization_classification == "POSITIVE_EDGE_BELOW_A_GRADE_IDLE":
        capital_blocker_reasons.append("POSITIVE_EDGE_BELOW_A_GRADE_IDLE_CAPITAL")
    elif capital_utilization_classification == "NO_EDGE_IDLE":
        capital_blocker_reasons.append("NO_EDGE_IDLE_CAPITAL")
    elif capital_utilization_classification == "ALLOCATOR_UNDERDEPLOYMENT":
        capital_blocker_reasons.append("A_GRADE_ALLOCATOR_UNDERDEPLOYMENT")
    projected_closed_outcomes_after_open_close = evidence_count + len(complete_open_post_capital_policy)
    projected_closed_outcome_deficit_after_open_close = max(
        0,
        MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES - projected_closed_outcomes_after_open_close,
    )
    evidence_acquisition_status = _evidence_acquisition_status(
        rows=post_allocator_closed,
        complete_open_row_count=len(complete_open_post_capital_policy),
        current_symbol_count=symbol_count,
        symbol_diversity_deficit=symbol_diversity_deficit,
        generated_utc=generated_utc,
        paper_status=paper_status,
    )
    runtime_evidence_acquisition_status = (
        evidence_acquisition_status["runtime_evidence_acquisition_status"]
    )
    paper_exploration_tier_status = runtime_evidence_acquisition_status[
        "paper_exploration_tier_status"
    ]
    capital_productivity_progress = {
        "current_closed_outcome_count": evidence_count,
        "minimum_required_closed_outcomes": MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES,
        "closed_outcome_deficit_to_minimum": closed_outcome_deficit_to_minimum,
        "closed_outcome_progress_pct": round(
            min(1.0, evidence_count / MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES),
            8,
        ),
        "open_positions_ready_to_become_closed_outcomes": len(complete_open_post_capital_policy),
        "projected_closed_outcome_count_after_current_open_positions_close": (
            projected_closed_outcomes_after_open_close
        ),
        "projected_closed_outcome_deficit_after_current_open_positions_close": (
            projected_closed_outcome_deficit_after_open_close
        ),
        "current_symbol_count": symbol_count,
        "minimum_required_symbol_count": MINIMUM_POLICY_SYMBOL_COUNT,
        "symbol_diversity_deficit": symbol_diversity_deficit,
        "symbol_diversity_progress_pct": round(
            min(1.0, symbol_count / MINIMUM_POLICY_SYMBOL_COUNT),
            8,
        ),
        "long_closed_outcome_count": long_count,
        "short_closed_outcome_count": short_count,
        "both_long_short_evidence": both_long_short_evidence,
        "capital_utilization_classification": capital_utilization_classification,
        "a_grade_opportunity_count": effective_a_grade_opportunity_count,
        "strict_a_grade_opportunity_count": len(a_grade_rows),
        "dynamic_a_grade_opportunity_count": len(dynamic_a_grade_candidate_rows),
        "dynamic_a_grade_opportunities_funded": len(dynamic_a_grade_funded_rows),
        "dynamic_a_grade_opportunities_underfunded": len(dynamic_a_grade_underfunded_rows),
        "b_grade_exploration_candidate_count": b_grade_exploration_candidate_count,
        "positive_edge_non_a_grade_opportunity_count": len(positive_edge_non_a_grade_rows),
        "near_a_grade_positive_edge_count": (
            positive_edge_non_a_grade_diagnostics["near_a_grade_positive_edge_count"]
        ),
        "closest_positive_edge_confidence_gap_to_a_grade": (
            positive_edge_non_a_grade_diagnostics["min_confidence_gap_to_a_grade"]
        ),
        "positive_return_on_deployed_margin": positive_return_on_deployed_margin,
        "return_on_deployed_margin": return_on_deployed_margin,
        "return_on_deployed_margin_gap_to_zero": (
            round(max(0.0, -return_on_deployed_margin), 8)
            if return_on_deployed_margin is not None else None
        ),
        "post_allocator_realized_pnl_usd": round(post_allocator_realized_pnl, 8),
        "closed_deployed_margin_usd": round(closed_margin, 8),
        "break_even_realized_pnl_gap_usd": round(max(0.0, -post_allocator_realized_pnl), 8),
        "strict_positive_return_requires_realized_pnl_above_zero": True,
        "post_allocator_win_rate": post_allocator_performance["post_allocator_win_rate"],
        "profit_factor": post_allocator_performance["profit_factor"],
        "minimum_required_profit_factor": post_allocator_performance["minimum_required_profit_factor"],
        "profit_factor_gap_to_minimum": post_allocator_performance["profit_factor_gap_to_minimum"],
        "profit_factor_burn_down": post_allocator_performance["profit_factor_burn_down"],
        "profit_factor_status": post_allocator_performance["status"],
        "after_cost_expectancy_bps": after_cost_expectancy_bps,
        "positive_after_cost_expectancy": positive_after_cost_expectancy,
        "evidence_acquisition_status": evidence_acquisition_status,
        "runtime_evidence_acquisition_status": runtime_evidence_acquisition_status,
    }
    capital_productivity = {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": "PASSED" if not capital_blocker_reasons else "NO_GO_INSUFFICIENT_CAPITAL_PRODUCTIVITY_EVIDENCE",
        "capital_productivity_blocker_reasons": capital_blocker_reasons,
        "capital_productivity_progress": capital_productivity_progress,
        "evidence_acquisition_status": evidence_acquisition_status,
        "runtime_evidence_acquisition_status": runtime_evidence_acquisition_status,
        "paper_exploration_tier_status": paper_exploration_tier_status,
        "closed_outcome_evidence_gap_analysis": closed_outcome_evidence_gap_analysis,
        "symbol_diversity_opportunity_analysis": symbol_diversity_opportunity_analysis,
        "paper_only": True,
        "places_real_order": False,
        "live_gate": LIVE_GATE,
        "capital_utilization_classification": capital_utilization_classification,
        "paper_equity_usd": round(equity, 8),
        "available_margin_usd": round(available_margin, 8),
        "allocated_margin_usd": round(open_margin, 8),
        "gross_open_notional_usd": round(open_notional, 8),
        "closed_deployed_margin_usd": round(closed_margin, 8),
        "closed_gross_notional_usd": round(closed_notional, 8),
        "post_allocator_realized_pnl_usd": round(post_allocator_realized_pnl, 8),
        "post_allocator_closed_outcome_count": evidence_count,
        "minimum_required_closed_outcomes": MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES,
        "closed_outcome_deficit_to_minimum": closed_outcome_deficit_to_minimum,
        "accepted_fill_policy_reconciliation": accepted_fill_reconciliation,
        "effective_portfolio_leverage": round(open_notional / equity, 8) if equity > 0 else 0.0,
        "capital_utilization_pct": round(open_margin / equity, 8) if equity > 0 else 0.0,
        "return_on_deployed_margin": return_on_deployed_margin,
        "return_on_deployed_margin_numerator_usd": round(post_allocator_realized_pnl, 8),
        "return_on_deployed_margin_denominator_usd": round(closed_margin, 8),
        "return_on_deployed_margin_formula": "post_allocator_realized_pnl_usd / closed_deployed_margin_usd",
        "positive_return_on_deployed_margin": positive_return_on_deployed_margin,
        "capital_turnover": round(closed_notional / equity, 8) if equity > 0 else 0.0,
        "net_pnl_per_dollar_margin": return_on_deployed_margin,
        "post_allocator_performance_status": post_allocator_performance["status"],
        "minimum_required_profit_factor": post_allocator_performance["minimum_required_profit_factor"],
        "profit_factor": post_allocator_performance["profit_factor"],
        "profit_factor_numeric": post_allocator_performance["profit_factor_numeric"],
        "profit_factor_is_infinite": post_allocator_performance["profit_factor_is_infinite"],
        "profit_factor_gap_to_minimum": post_allocator_performance["profit_factor_gap_to_minimum"],
        "profit_factor_burn_down": post_allocator_performance["profit_factor_burn_down"],
        "post_allocator_win_rate": post_allocator_performance["post_allocator_win_rate"],
        "post_allocator_winning_trade_count": post_allocator_performance["post_allocator_winning_trade_count"],
        "post_allocator_losing_trade_count": post_allocator_performance["post_allocator_losing_trade_count"],
        "post_allocator_flat_trade_count": post_allocator_performance["post_allocator_flat_trade_count"],
        "post_allocator_realized_profit_usd": post_allocator_performance["post_allocator_realized_profit_usd"],
        "post_allocator_realized_loss_usd": post_allocator_performance["post_allocator_realized_loss_usd"],
        "profit_factor_formula": post_allocator_performance["profit_factor_formula"],
        "after_cost_expectancy_bps": after_cost_expectancy_bps,
        "positive_after_cost_expectancy": positive_after_cost_expectancy,
        "after_cost_expectancy_source_row_count": len(opportunity_edge_values),
        "positive_after_cost_opportunity_row_count": positive_after_cost_rows,
        "non_positive_after_cost_opportunity_row_count": len(opportunity_edge_values) - positive_after_cost_rows,
        "positive_edge_non_a_grade_opportunity_count": len(positive_edge_non_a_grade_rows),
        "positive_edge_non_a_grade_diagnostics": positive_edge_non_a_grade_diagnostics,
        "positive_edge_non_a_grade_sample": [
            {
                "symbol": _normalized_symbol(row),
                "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
                "side": _directional_side(row),
                "confidence": _coerce_float(_first_present(row.get("confidence_calibrated"), row.get("confidence"))),
                "after_cost_edge_bps": _expected_edge_bps(row),
                "allocator_decision": _allocator_decision(row),
            }
            for row in positive_edge_non_a_grade_rows[:20]
        ],
        "expected_net_pnl_opportunity_sum_usd": round(
            sum(_coerce_float(row.get("expected_net_pnl_usd")) or 0.0 for row in opportunity_rows),
            8,
        ),
        "worst_expected_shortfall_usd": round(worst_expected_shortfall_usd, 8) if worst_expected_shortfall_usd is not None else None,
        "worst_expected_shortfall_pct_of_equity": worst_expected_shortfall_pct,
        "expected_shortfall_limit_pct": round(capital_risk_envelope.max_expected_shortfall_pct, 8),
        "realized_drawdown_pct": realized_drawdown_pct,
        "realized_drawdown_limit_pct": round(capital_risk_envelope.max_drawdown_pct, 8),
        "a_grade_opportunity_count": effective_a_grade_opportunity_count,
        "a_grade_opportunities_funded": effective_a_grade_opportunities_funded,
        "a_grade_opportunities_underfunded": effective_a_grade_opportunities_underfunded,
        "strict_a_grade_opportunity_count": len(a_grade_rows),
        "strict_a_grade_opportunities_funded": len(funded_a_grade),
        "strict_a_grade_opportunities_underfunded": len(underfunded_a_grade),
        "dynamic_a_grade_opportunity_count": len(dynamic_a_grade_candidate_rows),
        "dynamic_a_grade_opportunities_funded": len(dynamic_a_grade_funded_rows),
        "dynamic_a_grade_opportunities_underfunded": len(dynamic_a_grade_underfunded_rows),
        "dynamic_a_grade_candidate_source": (
            "a_grade_bucket_performance_matrix_dynamic_contract"
            if dynamic_a_grade_candidate_rows else "none"
        ),
        "dynamic_a_grade_underfunded_sample": [
            {
                "symbol": _normalized_symbol(row),
                "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
                "side": _directional_side(row),
                "after_cost_edge_bps": _expected_edge_bps(row),
                "allocator_decision": _allocator_decision(row),
                "gross_notional_usd": _notional(row),
                "allocated_margin_usd": _margin(row),
                "source_redis_key": row.get("source_redis_key"),
            }
            for row in dynamic_a_grade_underfunded_rows[:20]
        ],
        "b_grade_exploration_candidate_count": b_grade_exploration_candidate_count,
        "shadow_only_candidate_count": int(
            positive_edge_below_a_grade_resolution.get("shadow_only_candidate_count") or 0
        ),
        "no_trade_candidate_count": int(
            positive_edge_below_a_grade_resolution.get("no_trade_candidate_count") or 0
        ),
        "idle_capital_no_edge_usd": (
            round(available_margin, 8)
            if not dynamic_a_grade_candidate_rows
            and not a_grade_rows
            and not positive_edge_non_a_grade_rows
            else 0.0
        ),
        "idle_capital_positive_edge_not_a_grade_usd": (
            round(available_margin, 8)
            if not dynamic_a_grade_candidate_rows
            and not a_grade_rows
            and positive_edge_non_a_grade_rows
            and b_grade_exploration_candidate_count <= 0
            else 0.0
        ),
        "idle_capital_allocator_rejected_usd": (
            round(available_margin, 8)
            if effective_a_grade_underfunded_rows else 0.0
        ),
        "missed_opportunity_pnl_after_cost": round(
            sum(
                _coerce_float(row.get("expected_net_pnl_usd")) or 0.0
                for row in effective_a_grade_underfunded_rows
            ),
            8,
        ),
        "opportunity_source": (
            "v2:signals:paper+v2:paper:intents"
            if paper_signals and paper_intents
            else "v2:signals:paper" if paper_signals
            else "v2:paper:intents" if paper_intents
            else "v2:paper:ledger_runtime_rows"
        ),
        "paper_intent_row_count": len(paper_intents),
        "paper_signal_row_count": len(paper_signals),
        "prediction_row_count": len(prediction_rows),
        "pnl_history": pnl_history_status,
        "signal_prediction_accuracy_status": signal_prediction_accuracy_status,
    }
    accounting_status = {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": accounting_status_value,
        "capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
        "runtime_row_count": len(runtime_rows),
        "raw_closed_trade_row_count": len(raw_closed_trades),
        "accepted_fill_policy_reconciliation": accepted_fill_reconciliation,
        "historical_or_unversioned_runtime_row_count": len(runtime_rows) - len(new_trade_rows),
        "unversioned_runtime_row_count": len(unversioned_runtime_rows),
        "unversioned_runtime_rows_with_all_mandatory_fields": len(complete_unversioned_runtime_rows),
        "mandatory_fields": list(MANDATORY_PER_TRADE_FIELDS),
        "new_trade_row_count": len(new_trade_rows),
        "post_capital_policy_closed_row_count": len(post_capital_policy_closed),
        "post_capital_policy_closed_rows_with_all_mandatory_fields": len(post_allocator_closed),
        "post_capital_policy_closed_rows_missing_mandatory_fields": (
            len(post_capital_policy_closed) - len(post_allocator_closed)
        ),
        "post_capital_policy_closed_missing_mandatory_field_counts": _mandatory_field_missing_counts(
            post_capital_policy_closed
        ),
        "post_capital_policy_closed_missing_mandatory_sample": _mandatory_gap_sample(
            post_capital_policy_closed
        ),
        "post_capital_policy_open_row_count": len(post_capital_policy_open),
        "post_capital_policy_open_rows_with_all_mandatory_fields": len(complete_open_post_capital_policy),
        "post_capital_policy_open_rows_missing_mandatory_fields": (
            len(post_capital_policy_open) - len(complete_open_post_capital_policy)
        ),
        "post_capital_policy_open_missing_mandatory_field_counts": _mandatory_field_missing_counts(
            post_capital_policy_open
        ),
        "post_capital_policy_open_missing_mandatory_sample": _mandatory_gap_sample(
            post_capital_policy_open
        ),
        "rows_with_all_mandatory_fields": rows_with_all_fields,
        "mandatory_field_coverage": round(field_coverage, 8),
        "missing_by_field": missing_by_field,
        "blocker_reasons": [] if accounting_status_value == "PASSED" else [accounting_status_value],
        "accounting_enforcement_status": accounting_enforcement_status,
        "runtime_leverage_margin_consistency_status": leverage_margin_consistency["status"],
        "leverage_margin_consistency_status": (
            "PASSED"
            if runtime_accounting_complete else
            str(
                current_pre_submit_accounting_evidence.get("leverage_margin_consistency_status")
                or ("PASSED" if current_pre_submit_accounting_evidence.get("complete") else "")
            )
            if current_accounting_enforcement_complete else
            str(leverage_margin_consistency["status"])
        ),
        "leverage_margin_accounting_formula": leverage_margin_consistency["formula"],
        "leverage_margin_ratio_tolerance_abs": leverage_margin_consistency["tolerance_abs"],
        "leverage_margin_consistency_row_count": leverage_margin_consistency["row_count"],
        "leverage_margin_consistent_row_count": leverage_margin_consistency["consistent_row_count"],
        "leverage_margin_inconsistent_count": leverage_margin_consistency["inconsistent_count"],
        "leverage_margin_consistency_coverage": leverage_margin_consistency["consistency_coverage"],
        "leverage_margin_inconsistent_sample": leverage_margin_consistency["inconsistent_sample"],
        "runtime_accounting_evidence": _accounting_enforcement_evidence(
            new_trade_rows,
            source="post_capital_policy_runtime_rows",
        ),
        "policy_activation_funding_evidence_status": policy_activation_funding_evidence_status,
        "portfolio_order_counter_status": policy_activation_funding_evidence_status[
            "portfolio_order_counter_status"
        ],
        "runtime_accounting_complete": runtime_accounting_complete,
        "current_accounting_enforcement_complete": current_accounting_enforcement_complete,
        "current_accounting_enforcement_source": (
            current_pre_submit_accounting_evidence["source"]
            if current_accounting_enforcement_complete else "runtime_adaptive_rows"
        ),
        "historical_runtime_leverage_margin_gap_non_blocking": (
            historical_leverage_margin_gap_non_blocking
        ),
        "historical_runtime_mandatory_field_gap_non_blocking": (
            historical_mandatory_field_gap_non_blocking
        ),
        "historical_runtime_accounting_gap_non_blocking": (
            historical_runtime_accounting_gap_non_blocking
        ),
        "current_pre_submit_accounting_evidence": current_pre_submit_accounting_evidence,
        "accounting_scope": (
            "current strict pre-submit accounting enforcement is authoritative; historical runtime "
            "rows created before strict mandatory-field and nested allocation rescaling remain reported separately"
            if historical_runtime_accounting_gap_non_blocking else
            "runtime adaptive-capital rows and current pre-submit enforcement must both prove "
            "mandatory field coverage and leverage/margin consistency"
        ),
        "paper_only": True,
        "places_real_order": False,
        "live_gate": LIVE_GATE,
    }
    sweep = run_counterfactual_sweep(
        counterfactual_rows_with_replay,
        envelope=CounterfactualRiskEnvelope(starting_equity_usd=equity),
        require_full_source_coverage=True,
    )
    prediction_sweep = run_counterfactual_sweep(
        prediction_rows,
        envelope=CounterfactualRiskEnvelope(starting_equity_usd=equity),
        require_full_source_coverage=False,
    )
    near_a_grade_sweep = run_counterfactual_sweep(
        counterfactual_rows_with_replay,
        envelope=CounterfactualRiskEnvelope(starting_equity_usd=equity),
        require_full_source_coverage=True,
        confidence_threshold=NEAR_A_GRADE_REPLAY_CONFIDENCE_THRESHOLD,
    )
    market_cost_evidence_coverage_status = _market_cost_evidence_coverage_status(
        counterfactual_rows_with_replay,
        confidence_threshold=A_GRADE_CONFIDENCE_THRESHOLD,
        scope="actionable_a_grade_counterfactual_rows",
    )
    prediction_market_cost_evidence_coverage_status = _market_cost_evidence_coverage_status(
        prediction_rows,
        confidence_threshold=A_GRADE_CONFIDENCE_THRESHOLD,
        scope="prediction_probe_a_grade_rows",
    )
    near_a_grade_market_cost_evidence_coverage_status = _market_cost_evidence_coverage_status(
        counterfactual_rows_with_replay,
        confidence_threshold=NEAR_A_GRADE_REPLAY_CONFIDENCE_THRESHOLD,
        scope="near_a_grade_diagnostic_counterfactual_rows",
    )
    counterfactual_evidence_acquisition_status = _counterfactual_evidence_acquisition_status(
        sweep=sweep,
        a_grade_blocker_analysis=a_grade_blocker_analysis,
        market_cost_evidence_coverage_status=market_cost_evidence_coverage_status,
        near_a_grade_market_cost_evidence_coverage_status=near_a_grade_market_cost_evidence_coverage_status,
    )
    sweep_source_coverage = sweep.get("source_coverage", {})
    sweep_config_axes = sweep.get("config_axes", {})
    sweep_config_space_audit = sweep.get("config_space_audit", {})
    sweep_a_grade_readiness = sweep.get("a_grade_readiness", {})
    prediction_probe_a_grade_readiness = prediction_sweep.get("a_grade_readiness", {})
    accelerated_replay_status = _accelerated_counterfactual_replay_status(
        sweep=sweep,
        counterfactual_rows=counterfactual_rows_with_replay,
        evaluated_rows=[*closed_trades, *counterfactual_paper_signals, *paper_intents, *prediction_rows],
        a_grade_bucket_performance_matrix=a_grade_bucket_performance_matrix,
        post_hoc_replay_audit=post_hoc_replay_audit,
        post_hoc_replay_label_rows=post_hoc_replay_label_rows,
        native_trainer_replay_audit=native_trainer_replay_audit,
        native_trainer_replay_label_rows=native_trainer_replay_label_rows,
        closed_candle_replay_audit=closed_candle_replay_audit,
        closed_candle_replay_label_rows=closed_candle_replay_label_rows,
        generated_utc=generated_utc,
    )
    qualified_replay_policy_evidence_status = _qualified_replay_policy_evidence_status(
        accelerated_replay_status=accelerated_replay_status,
        sweep=sweep,
        realtime_closed_outcome_count=evidence_count,
        realtime_symbol_count=symbol_count,
        realtime_long_count=long_count,
        realtime_short_count=short_count,
    )
    replay_policy_evidence_passed = (
        qualified_replay_policy_evidence_status.get("status") == "PASSED"
    )
    if replay_policy_evidence_passed:
        policy_evidence_blocker_reasons = [
            reason for reason in policy_evidence_blocker_reasons
            if reason not in {
                "INSUFFICIENT_POST_ALLOCATOR_CLOSED_OUTCOMES",
                "INSUFFICIENT_SYMBOL_DIVERSITY",
            }
        ]
    evidence_count_pass = not policy_evidence_blocker_reasons
    effective_policy_outcome_count = int(
        qualified_replay_policy_evidence_status.get("effective_policy_outcome_count")
        or evidence_count
    )
    effective_policy_symbol_count = int(
        qualified_replay_policy_evidence_status.get("effective_policy_symbol_count")
        or symbol_count
    )
    effective_policy_long_count = int(
        qualified_replay_policy_evidence_status.get("effective_policy_long_count")
        or long_count
    )
    effective_policy_short_count = int(
        qualified_replay_policy_evidence_status.get("effective_policy_short_count")
        or short_count
    )
    effective_policy_closed_outcome_deficit = max(
        0,
        MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES - effective_policy_outcome_count,
    )
    effective_policy_symbol_diversity_deficit = max(
        0,
        MINIMUM_POLICY_SYMBOL_COUNT - effective_policy_symbol_count,
    )
    capital_productivity_progress.update({
        "policy_evidence_basis": qualified_replay_policy_evidence_status.get(
            "policy_evidence_basis"
        ),
        "qualified_replay_policy_evidence_status": qualified_replay_policy_evidence_status,
        "effective_policy_outcome_count": effective_policy_outcome_count,
        "effective_policy_closed_outcome_deficit_to_minimum": (
            effective_policy_closed_outcome_deficit
        ),
        "effective_policy_symbol_count": effective_policy_symbol_count,
        "effective_policy_symbol_diversity_deficit": (
            effective_policy_symbol_diversity_deficit
        ),
        "effective_policy_long_count": effective_policy_long_count,
        "effective_policy_short_count": effective_policy_short_count,
        "realtime_closed_outcome_count_still_reported": evidence_count,
        "realtime_symbol_count_still_reported": symbol_count,
    })
    capital_productivity.update({
        "policy_evidence_basis": qualified_replay_policy_evidence_status.get(
            "policy_evidence_basis"
        ),
        "qualified_replay_policy_evidence_status": qualified_replay_policy_evidence_status,
        "effective_policy_outcome_count": effective_policy_outcome_count,
        "effective_policy_closed_outcome_deficit_to_minimum": (
            effective_policy_closed_outcome_deficit
        ),
        "effective_policy_symbol_count": effective_policy_symbol_count,
        "effective_policy_symbol_diversity_deficit": (
            effective_policy_symbol_diversity_deficit
        ),
    })
    counterfactual_efficient_frontier = _counterfactual_efficient_frontier_artifact(
        sweep=sweep,
        generated_utc=generated_utc,
    )
    prediction_feature_market_cost_enriched_rows = [
        row for row in prediction_rows
        if row.get("prediction_market_cost_enrichment_fields")
    ]
    prediction_counterfactual_probe = {
        "status": (
            prediction_sweep.get("status")
            if prediction_rows else "NO_PREDICTION_ROWS"
        ),
        "prediction_row_count": len(prediction_rows),
        "prediction_feature_market_cost_enriched_count": len(
            prediction_feature_market_cost_enriched_rows
        ),
        "prediction_feature_market_cost_enrichment_sample": [
            {
                "symbol": _normalized_symbol(row),
                "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
                "prediction_id": row.get("prediction_market_cost_enrichment_prediction_id"),
                "filled_fields": row.get("prediction_market_cost_enrichment_fields", []),
                "market_cost_evidence_status": row.get("market_cost_evidence_status"),
                "pit_reject_reasons": row.get("market_cost_evidence_pit_reject_reasons", []),
            }
            for row in prediction_feature_market_cost_enriched_rows[:10]
        ],
        "probe_participates_in_counterfactual_pass_gate": False,
        "source_coverage_required_for_pass": False,
        "a_grade_before_temporal_count": prediction_sweep.get("a_grade_before_temporal_count", 0),
        "event_time_valid_candidate_count": prediction_sweep.get("event_time_valid_candidate_count", 0),
        "best_configuration_count": prediction_sweep.get("best_configuration_count", 0),
        "skipped_not_a_grade_count": prediction_sweep.get("skipped_not_a_grade_count", 0),
        "skipped_not_a_grade_reason_counts": prediction_sweep.get("skipped_not_a_grade_reason_counts", {}),
        "skipped_temporal_invalid_count": prediction_sweep.get("skipped_temporal_invalid_count", 0),
        "skipped_no_feasible_configuration_count": prediction_sweep.get(
            "skipped_no_feasible_configuration_count",
            0,
        ),
        "skipped_no_feasible_configuration_reason_counts": prediction_sweep.get(
            "skipped_no_feasible_configuration_reason_counts",
            {},
        ),
        "market_cost_evidence_coverage_status": prediction_market_cost_evidence_coverage_status,
        "a_grade_readiness": prediction_probe_a_grade_readiness,
        "notes": (
            "Prediction rows are probed for A-grade readiness and PIT-safe feasibility visibility only. "
            "They do not participate in the actionable paper-signal counterfactual pass gate."
        ),
    }
    near_a_grade_counterfactual_probe = {
        "status": (
            near_a_grade_sweep.get("status")
            if counterfactual_rows else "NO_COUNTERFACTUAL_SOURCE_ROWS"
        ),
        "probe_participates_in_counterfactual_pass_gate": False,
        "source_coverage_required_for_pass": True,
        "confidence_threshold": NEAR_A_GRADE_REPLAY_CONFIDENCE_THRESHOLD,
        "a_grade_thresholds": near_a_grade_sweep.get("a_grade_thresholds", {}),
        "a_grade_before_temporal_count": near_a_grade_sweep.get("a_grade_before_temporal_count", 0),
        "event_time_valid_candidate_count": near_a_grade_sweep.get("event_time_valid_candidate_count", 0),
        "best_configuration_count": near_a_grade_sweep.get("best_configuration_count", 0),
        "sweep_result_count": near_a_grade_sweep.get("sweep_result_count", 0),
        "efficient_frontier_ready": near_a_grade_sweep.get("efficient_frontier_ready", False),
        "total_expected_log_growth": near_a_grade_sweep.get("total_expected_log_growth", 0),
        "counterfactual_blocker_reasons": near_a_grade_sweep.get("counterfactual_blocker_reasons", []),
        "source_coverage": near_a_grade_sweep.get("source_coverage", {}),
        "a_grade_readiness": near_a_grade_sweep.get("a_grade_readiness", {}),
        "skipped_temporal_invalid_count": near_a_grade_sweep.get("skipped_temporal_invalid_count", 0),
        "skipped_temporal_invalid_sample": near_a_grade_sweep.get("skipped_temporal_invalid_sample", []),
        "skipped_not_a_grade_reason_counts": near_a_grade_sweep.get("skipped_not_a_grade_reason_counts", {}),
        "skipped_no_feasible_configuration_count": near_a_grade_sweep.get(
            "skipped_no_feasible_configuration_count",
            0,
        ),
        "skipped_no_feasible_configuration_reason_counts": near_a_grade_sweep.get(
            "skipped_no_feasible_configuration_reason_counts",
            {},
        ),
        "skipped_no_feasible_configuration_sample": near_a_grade_sweep.get(
            "skipped_no_feasible_configuration_sample",
            [],
        ),
        "market_cost_evidence_coverage_status": near_a_grade_market_cost_evidence_coverage_status,
        "config_space_audit": near_a_grade_sweep.get("config_space_audit", {}),
        "hedge_accounting_audit": near_a_grade_sweep.get("hedge_accounting_audit", {}),
        "best_configurations_sample": (
            near_a_grade_sweep.get("best_configurations_sample", [])[:10]
        ),
        "notes": (
            "Near-A-grade replay lowers only the diagnostic replay confidence threshold. "
            "It does not satisfy the A-grade counterfactual pass gate, which remains at 0.75."
        ),
    }
    near_a_grade_sample = sweep.get("near_a_grade_sample", [])
    closest_near_a_grade = (
        near_a_grade_sample[0]
        if near_a_grade_sample and isinstance(near_a_grade_sample[0], dict)
        else None
    )
    minimum_a_grade_replay_evidence_count = 1
    counterfactual_replay_progress = {
        "source_coverage_status": sweep_source_coverage.get("source_coverage_status"),
        "source_coverage_ratio": sweep_source_coverage.get("source_coverage"),
        "counterfactual_source_row_count": len(counterfactual_rows),
        "source_symbol_count": sweep_source_coverage.get("source_symbol_count"),
        "required_symbol_timeframe_cell_count": sweep_source_coverage.get("required_symbol_timeframe_cell_count"),
        "observed_required_symbol_timeframe_cell_count": (
            sweep_source_coverage.get("observed_required_symbol_timeframe_cell_count")
        ),
        "missing_required_symbol_timeframe_cell_count": (
            sweep_source_coverage.get("missing_required_symbol_timeframe_cell_count")
        ),
        "minimum_a_grade_replay_evidence_count": minimum_a_grade_replay_evidence_count,
        "historical_a_grade_signal_count": len(counterfactual_a_grade_rows),
        "a_grade_replay_evidence_deficit": max(
            0,
            minimum_a_grade_replay_evidence_count - len(counterfactual_a_grade_rows),
        ),
        "a_grade_replay_progress_pct": round(
            min(1.0, len(counterfactual_a_grade_rows) / minimum_a_grade_replay_evidence_count),
            8,
        ),
        "a_grade_before_temporal_count": sweep.get("a_grade_before_temporal_count", 0),
        "event_time_valid_candidate_count": sweep["event_time_valid_candidate_count"],
        "best_configuration_count": sweep["best_configuration_count"],
        "best_configuration_deficit_to_frontier": max(
            0,
            minimum_a_grade_replay_evidence_count - sweep["best_configuration_count"],
        ),
        "efficient_frontier_ready": sweep["efficient_frontier_ready"],
        "configuration_count_reconciled": sweep_config_space_audit.get("configuration_count_reconciled"),
        "feasible_plus_pruned_reconciled": sweep_config_space_audit.get("feasible_plus_pruned_reconciled"),
        "theoretical_configuration_count": sweep_config_space_audit.get("theoretical_configuration_count"),
        "configurations_considered_count": sweep_config_space_audit.get("configurations_considered_count"),
        "feasible_configuration_count": sweep_config_space_audit.get("feasible_configuration_count"),
        "pruned_configuration_count": sweep_config_space_audit.get("pruned_configuration_count"),
        "not_a_grade_reason_counts": sweep.get("skipped_not_a_grade_reason_counts", {}),
        "a_grade_source_kind_counts": sweep_a_grade_readiness.get("source_kind_counts", {}),
        "a_grade_source_kind_readiness": sweep_a_grade_readiness.get("source_kind_readiness", {}),
        "closest_near_a_grade_by_source_kind": sweep_a_grade_readiness.get("closest_near_a_grade_by_source_kind", {}),
        "prediction_a_grade_readiness": prediction_probe_a_grade_readiness,
        "prediction_counterfactual_probe": prediction_counterfactual_probe,
        "near_a_grade_counterfactual_probe": near_a_grade_counterfactual_probe,
        "a_grade_blocker_analysis": a_grade_blocker_analysis,
        "counterfactual_evidence_acquisition_status": counterfactual_evidence_acquisition_status,
        "market_cost_evidence_coverage_status": market_cost_evidence_coverage_status,
        "near_a_grade_market_cost_evidence_coverage_status": near_a_grade_market_cost_evidence_coverage_status,
        "counterfactual_market_cost_enriched_paper_signal_count": len(
            counterfactual_market_cost_enriched_paper_signals
        ),
        "counterfactual_feature_market_cost_enriched_paper_signal_count": len(
            counterfactual_feature_market_cost_enriched_paper_signals
        ),
        "closest_near_a_grade": closest_near_a_grade,
        "closest_confidence_gap_to_a_grade": (
            closest_near_a_grade.get("confidence_gap_to_a_grade")
            if closest_near_a_grade else None
        ),
        "closest_edge_gap_to_positive_bps": (
            closest_near_a_grade.get("edge_gap_to_positive_bps")
            if closest_near_a_grade else None
        ),
        "counterfactual_blocker_reasons": sweep.get("counterfactual_blocker_reasons", []),
    }
    counterfactual_next_evidence_gaps: dict[str, Any] = {
        "status": (
            "PASSED"
            if sweep.get("status") == "PASSED"
            else "NO_GO_COUNTERFACTUAL_EVIDENCE_GAPS_REMAIN"
        ),
        "blocker_reasons": sweep.get("counterfactual_blocker_reasons", []),
        "source_coverage_gap_count": sweep_source_coverage.get("missing_required_symbol_timeframe_cell_count"),
        "a_grade_signal_gap_count": counterfactual_replay_progress["a_grade_replay_evidence_deficit"],
        "best_configuration_gap_count": counterfactual_replay_progress["best_configuration_deficit_to_frontier"],
        "not_a_grade_reason_counts": sweep.get("skipped_not_a_grade_reason_counts", {}),
        "a_grade_blocker_analysis": a_grade_blocker_analysis,
        "counterfactual_evidence_acquisition_status": counterfactual_evidence_acquisition_status,
        "near_a_grade_event_time_valid_candidate_count": near_a_grade_counterfactual_probe.get(
            "event_time_valid_candidate_count", 0
        ),
        "near_a_grade_complete_market_cost_evidence_count": (
            near_a_grade_market_cost_evidence_coverage_status.get("complete_candidate_count", 0)
        ),
        "near_a_grade_candidate_market_cost_evidence_count": (
            near_a_grade_market_cost_evidence_coverage_status.get("candidate_row_count", 0)
        ),
        "near_a_grade_missing_market_cost_reason_counts": (
            near_a_grade_market_cost_evidence_coverage_status.get("missing_reason_counts", {})
        ),
        "near_a_grade_market_cost_pit_reject_reason_counts": (
            near_a_grade_market_cost_evidence_coverage_status.get("pit_reject_reason_counts", {})
        ),
        "near_a_grade_market_cost_capture_request_sample": (
            near_a_grade_market_cost_evidence_coverage_status.get(
                "incomplete_candidate_capture_request_sample",
                [],
            )
        ),
        "near_a_grade_market_cost_ready_sample": (
            near_a_grade_market_cost_evidence_coverage_status.get(
                "complete_candidate_sample",
                [],
            )
        ),
        "near_a_grade_pruned_configuration_reason_counts": (
            (near_a_grade_counterfactual_probe.get("config_space_audit") or {}).get("pruned_reason_counts", {})
        ),
        "closest_near_a_grade": closest_near_a_grade,
        "closest_a_grade_capture_request_sample": near_a_grade_sample[:5],
        "market_cost_evidence_requirement": "required_explicit_spread_slippage_fee_funding_bps_or_usd",
        "market_depth_capacity_requirement": "required_actual_depth_usd_or_orderbook_levels",
        "required_next_evidence": [],
    }
    required_next_evidence: list[str] = counterfactual_next_evidence_gaps["required_next_evidence"]
    if sweep_source_coverage.get("source_coverage_status") != "PASSED":
        required_next_evidence.append("COMPLETE_REQUIRED_SYMBOL_TIMEFRAME_SOURCE_COVERAGE")
    if counterfactual_replay_progress["a_grade_replay_evidence_deficit"] > 0:
        required_next_evidence.append(
            "PRODUCE_A_GRADE_SIGNAL_WITH_CONFIDENCE_AND_POSITIVE_AFTER_COST_EDGE"
        )
    if (
        int(sweep.get("a_grade_before_temporal_count", 0) or 0) > 0
        and int(sweep.get("event_time_valid_candidate_count", 0) or 0) == 0
    ):
        required_next_evidence.append("PROVIDE_EVENT_TIME_VALID_TEMPORAL_LABELS_FOR_A_GRADE_SIGNAL")
    if (
        int(near_a_grade_market_cost_evidence_coverage_status.get("candidate_row_count", 0) or 0) > 0
        and int(near_a_grade_market_cost_evidence_coverage_status.get("complete_candidate_count", 0) or 0)
        < int(near_a_grade_market_cost_evidence_coverage_status.get("candidate_row_count", 0) or 0)
    ):
        required_next_evidence.append("CAPTURE_EXPLICIT_ENTRY_MARKET_COST_FIELDS_AT_DECISION_TIME")
    if counterfactual_replay_progress["best_configuration_deficit_to_frontier"] > 0:
        required_next_evidence.append("GENERATE_FEASIBLE_COUNTERFACTUAL_CONFIGURATION_WITH_DEPTH_AND_COSTS")
    for item in counterfactual_evidence_acquisition_status.get("required_next_evidence") or []:
        if item not in required_next_evidence:
            required_next_evidence.append(item)
    strict_a_grade_acquisition_burn_down = _strict_a_grade_acquisition_burn_down(
        generated_utc=generated_utc,
        minimum_required_count=minimum_a_grade_replay_evidence_count,
        counterfactual_replay_progress=counterfactual_replay_progress,
        counterfactual_next_evidence_gaps=counterfactual_next_evidence_gaps,
        a_grade_blocker_analysis=a_grade_blocker_analysis,
        counterfactual_evidence_acquisition_status=counterfactual_evidence_acquisition_status,
        market_cost_evidence_coverage_status=market_cost_evidence_coverage_status,
        near_a_grade_market_cost_evidence_coverage_status=(
            near_a_grade_market_cost_evidence_coverage_status
        ),
    )
    counterfactual_next_evidence_gaps["strict_a_grade_acquisition_burn_down"] = (
        strict_a_grade_acquisition_burn_down
    )
    counterfactual_replay_progress["strict_a_grade_acquisition_burn_down"] = (
        strict_a_grade_acquisition_burn_down
    )
    counterfactual_replay_progress["counterfactual_next_evidence_gaps"] = counterfactual_next_evidence_gaps
    counterfactual_status = {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": sweep["status"],
        "counterfactual_blocker_reasons": sweep.get("counterfactual_blocker_reasons", []),
        "counterfactual_next_evidence_gaps": counterfactual_next_evidence_gaps,
        "counterfactual_replay_progress": counterfactual_replay_progress,
        "a_grade_blocker_analysis": a_grade_blocker_analysis,
        "a_grade_dynamic_calibration_status": a_grade_dynamic_calibration_status,
        "positive_edge_below_a_grade_resolution": positive_edge_below_a_grade_resolution,
        "accelerated_counterfactual_replay_status": accelerated_replay_status,
        "counterfactual_efficient_frontier": counterfactual_efficient_frontier,
        "counterfactual_evidence_acquisition_status": counterfactual_evidence_acquisition_status,
        "strict_a_grade_acquisition_burn_down": strict_a_grade_acquisition_burn_down,
        "engine_scope": "all_universe_symbols_all_five_timeframes_required",
        "event_time_valid_required": True,
        "counterfactual_source_row_count": len(counterfactual_rows),
        "ledger_runtime_row_count": len(runtime_rows),
        "paper_signal_row_count": len(paper_signals),
        "counterfactual_temporal_enriched_paper_signal_count": len(
            counterfactual_temporal_enriched_paper_signals
        ),
        "counterfactual_temporal_enrichment_sample": [
            {
                "symbol": _normalized_symbol(row),
                "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
                "prediction_id": row.get("counterfactual_temporal_enrichment_prediction_id"),
                "filled_fields": row.get("counterfactual_temporal_enrichment_fields", []),
            }
            for row in counterfactual_temporal_enriched_paper_signals[:10]
        ],
        "counterfactual_signal_quality_enriched_paper_signal_count": len(
            counterfactual_signal_quality_enriched_paper_signals
        ),
        "counterfactual_signal_quality_enrichment_sample": [
            {
                "symbol": _normalized_symbol(row),
                "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
                "prediction_id": row.get("counterfactual_signal_quality_enrichment_prediction_id"),
                "filled_fields": row.get("counterfactual_signal_quality_enrichment_fields", []),
            }
            for row in counterfactual_signal_quality_enriched_paper_signals[:10]
        ],
        "counterfactual_market_cost_enriched_paper_signal_count": len(
            counterfactual_market_cost_enriched_paper_signals
        ),
        "counterfactual_market_cost_enrichment_sample": [
            {
                "symbol": _normalized_symbol(row),
                "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
                "prediction_id": row.get("counterfactual_market_cost_enrichment_prediction_id"),
                "filled_fields": row.get("counterfactual_market_cost_enrichment_fields", []),
                "market_cost_evidence_status": row.get("market_cost_evidence_status"),
            }
            for row in counterfactual_market_cost_enriched_paper_signals[:10]
        ],
        "counterfactual_feature_market_cost_enriched_paper_signal_count": len(
            counterfactual_feature_market_cost_enriched_paper_signals
        ),
        "counterfactual_feature_market_cost_enrichment_sample": [
            {
                "symbol": _normalized_symbol(row),
                "timeframe": _row_value(row, "timeframe") or row.get("timeframe"),
                "prediction_id": _first_present(
                    row.get("counterfactual_feature_market_cost_enrichment_prediction_id"),
                    row.get("counterfactual_market_cost_enrichment_prediction_id"),
                ),
                "filled_fields": _first_present(
                    row.get("counterfactual_feature_market_cost_enrichment_fields"),
                    row.get("counterfactual_market_cost_enrichment_fields"),
                    [],
                ),
                "market_cost_evidence_status": row.get("market_cost_evidence_status"),
                "pit_reject_reasons": row.get("market_cost_evidence_pit_reject_reasons", []),
            }
            for row in counterfactual_feature_market_cost_enriched_paper_signals[:10]
        ],
        "paper_intent_row_count": len(paper_intents),
        "paper_ledger_accepted_counterfactual_row_count": len(durable_accepted_counterfactual_rows),
        "paper_ledger_accepted_counterfactual_evidence": durable_accepted_counterfactual_evidence,
        "feature_row_count": len(feature_rows),
        "latest_feature_row_count": latest_feature_row_count,
        "archived_feature_row_count": archived_feature_row_count,
        "feature_snapshot_archive_lookup_enabled": True,
        "feature_snapshot_lookup_audit": feature_snapshot_lookup_audit,
        "prediction_row_count": len(prediction_rows),
        "prediction_counterfactual_probe": prediction_counterfactual_probe,
        "near_a_grade_counterfactual_probe": near_a_grade_counterfactual_probe,
        "source_coverage_required_for_pass": sweep.get("source_coverage_required_for_pass", True),
        "source_coverage": sweep_source_coverage,
        "source_coverage_status": sweep_source_coverage.get("source_coverage_status"),
        "source_coverage_ratio": sweep_source_coverage.get("source_coverage"),
        "market_cost_evidence_coverage_status": market_cost_evidence_coverage_status,
        "a_grade_readiness": sweep_a_grade_readiness,
        "required_symbol_timeframe_cell_count": sweep_source_coverage.get("required_symbol_timeframe_cell_count"),
        "observed_required_symbol_timeframe_cell_count": sweep_source_coverage.get("observed_required_symbol_timeframe_cell_count"),
        "missing_required_symbol_timeframe_cell_count": sweep_source_coverage.get("missing_required_symbol_timeframe_cell_count"),
        "a_grade_thresholds": sweep.get("a_grade_thresholds", {}),
        "simulated_configuration_axes": [
            "notional",
            "leverage",
            "isolated_margin",
            "cross_margin",
            "stop_distance",
            "take_profit_plan",
            "hedge_or_no_hedge",
            "spread_depth_fees_slippage_funding",
        ],
        "historical_a_grade_signal_count": len(counterfactual_a_grade_rows),
        "a_grade_before_temporal_count": sweep.get("a_grade_before_temporal_count", 0),
        "event_time_valid_candidate_count": sweep["event_time_valid_candidate_count"],
        "skipped_not_a_grade_count": sweep["skipped_not_a_grade_count"],
        "skipped_not_a_grade_reason_counts": sweep.get("skipped_not_a_grade_reason_counts", {}),
        "skipped_not_a_grade_sample": sweep.get("skipped_not_a_grade_sample", []),
        "near_a_grade_sample": near_a_grade_sample,
        "skipped_temporal_invalid_count": sweep["skipped_temporal_invalid_count"],
        "skipped_temporal_invalid_sample": sweep["skipped_temporal_invalid_sample"],
        "skipped_no_feasible_configuration_count": sweep.get("skipped_no_feasible_configuration_count", 0),
        "skipped_no_feasible_configuration_reason_counts": sweep.get("skipped_no_feasible_configuration_reason_counts", {}),
        "skipped_no_feasible_configuration_sample": sweep.get("skipped_no_feasible_configuration_sample", []),
        "sweep_result_count": sweep["sweep_result_count"],
        "config_space_audit": sweep_config_space_audit,
        "hedge_accounting_audit": sweep.get("hedge_accounting_audit", {}),
        "best_configuration_count": sweep["best_configuration_count"],
        "efficient_frontier_ready": sweep["efficient_frontier_ready"],
        "objective": sweep["objective"],
        "total_expected_log_growth": sweep["total_expected_log_growth"],
        "worst_expected_shortfall_usd": sweep["worst_expected_shortfall_usd"],
        "max_liquidation_probability": sweep["max_liquidation_probability"],
        "best_configurations_sample": sweep["best_configurations_sample"],
        "config_axes": sweep_config_axes,
        "market_depth_capacity_requirement": sweep_config_axes.get("market_depth_capacity"),
        "market_cost_evidence_requirement": sweep_config_axes.get("market_cost_evidence"),
        "notes": (
            "Counterfactual engine executed on currently available rows. "
            "Overall pass still requires all-universe/five-timeframe replay coverage and sufficient post-allocator evidence."
        ),
    }
    adaptive_policy_status = {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": "NO_GO_POLICY_EVIDENCE_INSUFFICIENT" if not evidence_count_pass else "PASSED",
        "policy_evidence_blocker_reasons": policy_evidence_blocker_reasons,
        "policy_evidence_basis": qualified_replay_policy_evidence_status.get(
            "policy_evidence_basis"
        ),
        "qualified_replay_policy_evidence_status": qualified_replay_policy_evidence_status,
        "qualified_replay_policy_evidence_passed": replay_policy_evidence_passed,
        "no_fixed_runtime_size": policy_variation_evidence["runtime_size_variation_proven"],
        "no_fixed_runtime_leverage": policy_variation_evidence["runtime_leverage_variation_proven"],
        "runtime_size_leverage_evidence": policy_variation_evidence,
        "adaptive_field_selection_evidence": adaptive_field_selection_evidence,
        "adaptive_selection_attribution_status": adaptive_selection_attribution_status,
        "policy_activation_funding_evidence_status": policy_activation_funding_evidence_status,
        "evidence_acquisition_status": evidence_acquisition_status,
        "runtime_evidence_acquisition_status": runtime_evidence_acquisition_status,
        "pre_submit_sized_policy_candidate_count": len(pre_submit_policy_rows),
        "pre_submit_size_leverage_evidence": pre_submit_policy_variation_evidence,
        "pre_submit_adaptive_field_selection_evidence": (
            pre_submit_adaptive_field_selection_evidence
        ),
        "allocator_calibration_status": allocator_calibration_status,
        "accepted_fill_policy_reconciliation": accepted_fill_reconciliation,
        "closed_outcome_evidence_gap_analysis": closed_outcome_evidence_gap_analysis,
        "symbol_diversity_opportunity_analysis": symbol_diversity_opportunity_analysis,
        "allocator_contract_fields_present": True,
        "capital_policy_version": ADAPTIVE_CAPITAL_POLICY_VERSION,
        "post_allocator_closed_outcome_count": evidence_count,
        "minimum_required_closed_outcomes": MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES,
        "closed_outcome_deficit_to_minimum": closed_outcome_deficit_to_minimum,
        "effective_policy_outcome_count": effective_policy_outcome_count,
        "effective_policy_closed_outcome_deficit_to_minimum": (
            effective_policy_closed_outcome_deficit
        ),
        "closed_outcome_progress_pct": round(
            min(1.0, evidence_count / MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES),
            8,
        ),
        "effective_policy_closed_outcome_progress_pct": round(
            min(1.0, effective_policy_outcome_count / MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES),
            8,
        ),
        "open_positions_ready_to_become_closed_outcomes": len(complete_open_post_capital_policy),
        "projected_closed_outcome_count_after_current_open_positions_close": (
            projected_closed_outcomes_after_open_close
        ),
        "projected_closed_outcome_deficit_after_current_open_positions_close": (
            projected_closed_outcome_deficit_after_open_close
        ),
        "policy_evidence_progress": {
            "current_closed_outcome_count": evidence_count,
            "minimum_required_closed_outcomes": MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES,
            "closed_outcome_deficit_to_minimum": closed_outcome_deficit_to_minimum,
            "effective_policy_outcome_count": effective_policy_outcome_count,
            "effective_policy_closed_outcome_deficit_to_minimum": (
                effective_policy_closed_outcome_deficit
            ),
            "policy_evidence_basis": qualified_replay_policy_evidence_status.get(
                "policy_evidence_basis"
            ),
            "qualified_replay_policy_evidence_status": qualified_replay_policy_evidence_status,
            "evidence_acquisition_status": evidence_acquisition_status,
            "runtime_evidence_acquisition_status": runtime_evidence_acquisition_status,
            "long_closed_outcome_count": long_count,
            "short_closed_outcome_count": short_count,
            "both_long_short_evidence": both_long_short_evidence,
            "missing_directional_sides": missing_directional_sides,
            "minimum_required_per_directional_side": 1,
            "symbol_count": symbol_count,
            "minimum_required_symbol_count": MINIMUM_POLICY_SYMBOL_COUNT,
            "minimum_required_symbols": MINIMUM_POLICY_SYMBOL_COUNT,
            "symbol_diversity_deficit": symbol_diversity_deficit,
            "effective_policy_symbol_count": effective_policy_symbol_count,
            "effective_policy_symbol_diversity_deficit": (
                effective_policy_symbol_diversity_deficit
            ),
            "post_capital_policy_closed_row_count": len(post_capital_policy_closed),
            "post_capital_policy_closed_rows_missing_mandatory_fields": (
                len(post_capital_policy_closed) - evidence_count
            ),
            "open_post_capital_policy_row_count": len(post_capital_policy_open),
            "open_positions_ready_to_become_closed_outcomes": len(complete_open_post_capital_policy),
            "projected_closed_outcome_count_after_current_open_positions_close": (
                projected_closed_outcomes_after_open_close
            ),
            "projected_closed_outcome_deficit_after_current_open_positions_close": (
                projected_closed_outcome_deficit_after_open_close
            ),
            "unversioned_runtime_row_count": len(unversioned_runtime_rows),
            "unversioned_runtime_rows_with_all_mandatory_fields": len(complete_unversioned_runtime_rows),
            "strict_policy_version_required": True,
        },
        "long_closed_outcome_count": long_count,
        "short_closed_outcome_count": short_count,
        "both_long_short_evidence": both_long_short_evidence,
        "missing_directional_sides": missing_directional_sides,
        "minimum_required_per_directional_side": 1,
        "post_allocator_side_counts": {
            key: side_counts[key]
            for key in sorted(side_counts)
        },
        "symbol_count": symbol_count,
        "minimum_required_symbol_count": MINIMUM_POLICY_SYMBOL_COUNT,
        "minimum_required_symbols": MINIMUM_POLICY_SYMBOL_COUNT,
        "symbol_diversity_deficit": symbol_diversity_deficit,
        "effective_policy_symbol_count": effective_policy_symbol_count,
        "effective_policy_symbol_diversity_deficit": effective_policy_symbol_diversity_deficit,
        "symbol_diversity_progress_pct": round(
            min(1.0, symbol_count / MINIMUM_POLICY_SYMBOL_COUNT),
            8,
        ),
        "effective_policy_symbol_diversity_progress_pct": round(
            min(1.0, effective_policy_symbol_count / MINIMUM_POLICY_SYMBOL_COUNT),
            8,
        ),
    }
    correlation_status = _portfolio_correlation_budget_status(
        open_positions=open_positions,
        equity=equity,
        open_notional=open_notional,
        effective_portfolio_leverage=capital_productivity["effective_portfolio_leverage"],
        generated_utc=generated_utc,
        market_candles_by_symbol=correlation_candles_by_symbol,
        market_candle_source_by_symbol=correlation_candle_sources_by_symbol,
    )
    compounding_blocker_reasons = list(policy_evidence_blocker_reasons)
    if capital_productivity["return_on_deployed_margin"] is None or capital_productivity["return_on_deployed_margin"] <= 0.0:
        compounding_blocker_reasons.append("NON_POSITIVE_RETURN_ON_DEPLOYED_MARGIN")
    if capital_productivity["after_cost_expectancy_bps"] is None or capital_productivity["after_cost_expectancy_bps"] <= 0.0:
        compounding_blocker_reasons.append("NON_POSITIVE_AFTER_COST_EXPECTANCY")
    worst_shortfall_pct = capital_productivity["worst_expected_shortfall_pct_of_equity"]
    if worst_shortfall_pct is None:
        compounding_blocker_reasons.append("MISSING_EXPECTED_SHORTFALL_EVIDENCE")
    elif worst_shortfall_pct > capital_productivity["expected_shortfall_limit_pct"]:
        compounding_blocker_reasons.append("EXPECTED_SHORTFALL_LIMIT_BREACH")
    if capital_productivity["realized_drawdown_pct"] > capital_productivity["realized_drawdown_limit_pct"]:
        compounding_blocker_reasons.append("REALIZED_DRAWDOWN_LIMIT_BREACH")
    if not sweep["efficient_frontier_ready"]:
        compounding_blocker_reasons.append("COUNTERFACTUAL_EFFICIENT_FRONTIER_NOT_READY")
    elif sweep["total_expected_log_growth"] <= 0.0:
        compounding_blocker_reasons.append("NON_POSITIVE_COUNTERFACTUAL_LOG_GROWTH")
    compounding_status = {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": "NO_GO_COMPOUNDING_EVIDENCE_INSUFFICIENT" if compounding_blocker_reasons else "PASSED",
        "compounding_blocker_reasons": compounding_blocker_reasons,
        "objective": "maximize_expected_log_final_equity",
        "paper_equity_usd": round(equity, 8),
        "post_allocator_realized_pnl_usd": round(post_allocator_realized_pnl, 8),
        "closed_deployed_margin_usd": round(closed_margin, 8),
        "closed_gross_notional_usd": round(closed_notional, 8),
        "return_on_deployed_margin": capital_productivity["return_on_deployed_margin"],
        "return_on_deployed_margin_numerator_usd": capital_productivity["return_on_deployed_margin_numerator_usd"],
        "return_on_deployed_margin_denominator_usd": capital_productivity["return_on_deployed_margin_denominator_usd"],
        "return_on_deployed_margin_formula": capital_productivity["return_on_deployed_margin_formula"],
        "positive_return_on_deployed_margin": positive_return_on_deployed_margin,
        "after_cost_expectancy_bps": capital_productivity["after_cost_expectancy_bps"],
        "positive_after_cost_expectancy": positive_after_cost_expectancy,
        "worst_expected_shortfall_pct_of_equity": capital_productivity["worst_expected_shortfall_pct_of_equity"],
        "expected_shortfall_limit_pct": capital_productivity["expected_shortfall_limit_pct"],
        "realized_drawdown_pct": capital_productivity["realized_drawdown_pct"],
        "realized_drawdown_limit_pct": capital_productivity["realized_drawdown_limit_pct"],
        "policy_evidence_status": "PASSED" if evidence_count_pass else "NO_GO_POLICY_EVIDENCE_INSUFFICIENT",
        "policy_evidence_blocker_reasons": policy_evidence_blocker_reasons,
        "policy_evidence_basis": qualified_replay_policy_evidence_status.get(
            "policy_evidence_basis"
        ),
        "qualified_replay_policy_evidence_status": qualified_replay_policy_evidence_status,
        "qualified_replay_policy_evidence_passed": replay_policy_evidence_passed,
        "accepted_fill_policy_reconciliation": accepted_fill_reconciliation,
        "evidence_acquisition_status": evidence_acquisition_status,
        "runtime_evidence_acquisition_status": runtime_evidence_acquisition_status,
        "closed_outcome_evidence_gap_analysis": closed_outcome_evidence_gap_analysis,
        "symbol_diversity_opportunity_analysis": symbol_diversity_opportunity_analysis,
        "counterfactual_efficient_frontier_ready": sweep["efficient_frontier_ready"],
        "counterfactual_status": sweep["status"],
        "counterfactual_blocker_reasons": sweep.get("counterfactual_blocker_reasons", []),
        "counterfactual_historical_a_grade_signal_count": len(counterfactual_a_grade_rows),
        "counterfactual_best_configuration_count": sweep["best_configuration_count"],
        "counterfactual_total_expected_log_growth": sweep["total_expected_log_growth"],
        "closed_outcome_evidence_count": evidence_count,
        "post_allocator_closed_outcome_count": evidence_count,
        "minimum_required_closed_outcomes": MINIMUM_POST_ALLOCATOR_CLOSED_OUTCOMES,
        "closed_outcome_deficit_to_minimum": closed_outcome_deficit_to_minimum,
        "effective_policy_outcome_count": effective_policy_outcome_count,
        "effective_policy_closed_outcome_deficit_to_minimum": (
            effective_policy_closed_outcome_deficit
        ),
        "long_closed_outcome_count": long_count,
        "short_closed_outcome_count": short_count,
        "effective_policy_long_count": effective_policy_long_count,
        "effective_policy_short_count": effective_policy_short_count,
        "both_long_short_evidence": both_long_short_evidence,
        "missing_directional_sides": missing_directional_sides,
        "post_allocator_symbol_count": symbol_count,
        "minimum_required_symbol_count": MINIMUM_POLICY_SYMBOL_COUNT,
        "symbol_diversity_deficit": symbol_diversity_deficit,
        "effective_policy_symbol_count": effective_policy_symbol_count,
        "effective_policy_symbol_diversity_deficit": (
            effective_policy_symbol_diversity_deficit
        ),
    }
    counterfactual_rare_event_result = run_rare_event_capital_stress(sweep)
    rare_event_runtime_rows = post_capital_policy_open + pre_submit_policy_rows
    runtime_rare_event_result = run_runtime_allocation_rare_event_stress(
        rare_event_runtime_rows,
        envelope=CounterfactualRiskEnvelope(starting_equity_usd=equity),
    )
    rare_event_result = (
        runtime_rare_event_result
        if runtime_rare_event_result.get("status") != "NO_GO_RARE_EVENT_CAPITAL_STRESS_NOT_RUN"
        else counterfactual_rare_event_result
    )
    rare_event_blocker_reasons: list[str] = []
    if rare_event_result.get("scenario_failures"):
        rare_event_blocker_reasons.extend(
            str(reason) for reason in rare_event_result.get("scenario_failures", [])
            if str(reason) not in rare_event_blocker_reasons
        )
    rare_event_status = {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": rare_event_result["status"],
        "rare_event_blocker_reasons": rare_event_blocker_reasons,
        "stress_source": rare_event_result.get("stress_source"),
        "runtime_stress_scope": (
            "current_open_adaptive_positions_plus_active_sized_pre_submit_candidates"
        ),
        "counterfactual_best_configuration_count": sweep["best_configuration_count"],
        "counterfactual_stress_status": counterfactual_rare_event_result["status"],
        "required_scenarios": rare_event_result["required_scenarios"],
        "completed_scenarios": rare_event_result["completed_scenarios"],
        "scenario_max_loss_usd": rare_event_result.get("scenario_max_loss_usd", {}),
        "scenario_total_loss_usd": rare_event_result.get("scenario_total_loss_usd", {}),
        "scenario_loss_limit_usd": rare_event_result.get("scenario_loss_limit_usd"),
        "scenario_loss_limit_pct": rare_event_result.get("scenario_loss_limit_pct"),
        "scenario_failures": rare_event_result.get("scenario_failures", []),
        "runtime_allocation_row_count": rare_event_result.get("runtime_allocation_row_count"),
        "runtime_stressed_row_count": rare_event_result.get("runtime_stressed_row_count"),
        "stressed_allocation_sample_count": rare_event_result.get("stressed_allocation_sample_count"),
        "runtime_stress_missing_evidence_count": rare_event_result.get("runtime_stress_missing_evidence_count"),
        "runtime_stress_missing_evidence_sample": rare_event_result.get("runtime_stress_missing_evidence_sample", []),
        "stressed_allocation_sample": rare_event_result.get("stressed_allocation_sample", []),
        "no_current_runtime_exposure": rare_event_result.get("no_current_runtime_exposure") is True,
        "notes": rare_event_result.get("notes"),
        "paper_only": True,
        "places_real_order": False,
    }
    parity_status = _paper_live_pre_submit_parity_status(
        paper_intents=paper_intents,
        generated_utc=generated_utc,
    )
    parity_status["paper_runtime_classification"] = paper_status.get("classification")
    parity_status["durable_accepted_pre_submit_evidence"] = durable_pre_submit_evidence
    parity_status["durable_accepted_pre_submit_used_for_gate"] = False
    parity_status["effective_pre_submit_evidence_source"] = (
        "active_or_held_paper_intent_snapshot"
        if parity_status.get("versioned_sized_pre_submit_candidate_count", 0) else "none"
    )
    parity_status["effective_versioned_sized_pre_submit_candidate_count"] = (
        parity_status.get("versioned_sized_pre_submit_candidate_count", 0)
    )
    active_or_held_snapshot_count = (
        int(parity_status.get("paper_intent_active_row_count") or 0)
        + int(parity_status.get("paper_intent_held_row_count") or 0)
    )
    if (
        active_or_held_snapshot_count == 0
        and int(parity_status.get("candidate_failure_count") or 0) == 0
        and durable_pre_submit_evidence.get("status") == "PASSED"
    ):
        parity_status["status"] = "PASSED"
        parity_status["durable_accepted_pre_submit_used_for_gate"] = True
        parity_status["effective_pre_submit_evidence_source"] = "durable_accepted_pre_submit_ledger"
        parity_status["effective_versioned_sized_pre_submit_candidate_count"] = (
            durable_pre_submit_evidence.get("versioned_sized_accepted_candidate_count", 0)
        )
    elif (
        parity_status.get("status") == "NO_GO_PRE_SUBMIT_PARITY_NO_SIZED_INTENTS"
        and active_or_held_snapshot_count > 0
        and parity_status.get("active_or_held_versioned_intents_all_blocked") is True
        and int(parity_status.get("candidate_failure_count") or 0) == 0
        and int(parity_status.get("unversioned_allocator_evidence_count") or 0) == 0
        and durable_pre_submit_evidence.get("status") == "PASSED"
    ):
        parity_status["status"] = "PASSED"
        parity_status["durable_accepted_pre_submit_used_for_gate"] = True
        parity_status["effective_pre_submit_evidence_source"] = (
            "durable_accepted_pre_submit_ledger_with_current_blocked_snapshot"
        )
        parity_status["effective_versioned_sized_pre_submit_candidate_count"] = (
            durable_pre_submit_evidence.get("versioned_sized_accepted_candidate_count", 0)
        )
        parity_status["durable_accepted_pre_submit_gate_reason"] = (
            "current_active_or_held_versioned_intents_all_allocator_blocked"
        )
    active_liquidation_buffer_evidence = (
        parity_status.get("liquidation_buffer_minimum_evidence")
        if isinstance(parity_status.get("liquidation_buffer_minimum_evidence"), dict)
        else {}
    )
    durable_liquidation_buffer_evidence = (
        durable_pre_submit_evidence.get("liquidation_buffer_minimum_evidence")
        if isinstance(durable_pre_submit_evidence.get("liquidation_buffer_minimum_evidence"), dict)
        else {}
    )
    if int(active_liquidation_buffer_evidence.get("candidate_count") or 0) > 0:
        effective_liquidation_buffer_evidence = active_liquidation_buffer_evidence
    elif parity_status.get("durable_accepted_pre_submit_used_for_gate") is True:
        effective_liquidation_buffer_evidence = durable_liquidation_buffer_evidence
    else:
        effective_liquidation_buffer_evidence = active_liquidation_buffer_evidence
    parity_status["effective_liquidation_buffer_minimum_evidence"] = (
        effective_liquidation_buffer_evidence
    )
    parity_status["effective_liquidation_buffer_minimum_verified"] = (
        effective_liquidation_buffer_evidence.get("status") == "PASSED"
    )
    parity_status["parity_blocker_reasons"] = (
        [] if parity_status["status"] == "PASSED" else [parity_status["status"]]
    )
    external_audit_blocker_burn_down = _external_audit_blocker_burn_down(
        generated_utc=generated_utc,
        capital_productivity=capital_productivity,
        adaptive_policy_status=adaptive_policy_status,
        parity_status=parity_status,
    )
    liquidity_regime_adjustment_status = (
        external_audit_blocker_burn_down.get("liquidity_regime_calibration") or {}
    )
    liquidation_buffer_minimum_status = (
        external_audit_blocker_burn_down.get("liquidation_buffer_minimum") or {}
    )
    thousand_x_dependency_statuses = {
        "counterfactual_capital_sweep_status": counterfactual_status["status"],
        "adaptive_capital_policy_status": adaptive_policy_status["status"],
        "portfolio_correlation_budget_status": correlation_status["status"],
        "compounding_equity_status": compounding_status["status"],
        "rare_event_capital_stress_status": rare_event_status["status"],
        "paper_live_pre_submit_parity_status": parity_status["status"],
    }
    thousand_x_blocker_reasons = [
        "COUNTERFACTUAL_SWEEP_NOT_PASSED" if counterfactual_status["status"] != "PASSED" else "",
        "ADAPTIVE_POLICY_EVIDENCE_NOT_PASSED" if adaptive_policy_status["status"] != "PASSED" else "",
        "PORTFOLIO_CORRELATION_BUDGET_NOT_PASSED" if correlation_status["status"] != "PASSED" else "",
        "COMPOUNDING_EVIDENCE_NOT_PASSED" if compounding_status["status"] != "PASSED" else "",
        "RARE_EVENT_STRESS_NOT_PASSED" if rare_event_status["status"] != "PASSED" else "",
        "PAPER_LIVE_PRE_SUBMIT_PARITY_NOT_PASSED" if parity_status["status"] != "PASSED" else "",
    ]
    thousand_x_blocker_reasons = [reason for reason in thousand_x_blocker_reasons if reason]
    thousand_x_starting_equity = 10000.0
    thousand_x_target_multiple = 1000.0
    observed_growth_evidence = _one_thousand_x_observed_growth_evidence(
        starting_equity_usd=thousand_x_starting_equity,
        target_multiple=thousand_x_target_multiple,
        horizon_years=horizon_years,
        current_equity_usd=equity,
        pnl_history_status=pnl_history_status,
    )
    feasibility_classification = _one_thousand_x_feasibility_classification(
        blocker_reasons=thousand_x_blocker_reasons,
        observed_growth_evidence=observed_growth_evidence,
        horizon_years=horizon_years,
    )
    guaranteed_return_claim = False
    thousand_x_status_value = _one_thousand_x_status_value(
        blocker_reasons=thousand_x_blocker_reasons,
        classification=feasibility_classification["classification"],
        horizon_years=horizon_years,
        guaranteed_return_claim=guaranteed_return_claim,
    )
    explicit_horizon_classification = (
        bool(str(feasibility_classification["classification"] or "").strip())
        and horizon_years > 0.0
        and feasibility_classification["horizon_days"] > 0.0
    )
    thousand_x_status = {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": thousand_x_status_value,
        "feasibility_blocker_reasons": thousand_x_blocker_reasons,
        "dependency_statuses": thousand_x_dependency_statuses,
        "classification": feasibility_classification["classification"],
        "starting_equity_usd": thousand_x_starting_equity,
        "initial_equity_usd": thousand_x_starting_equity,
        "target_equity_usd": thousand_x_starting_equity * thousand_x_target_multiple,
        "target_multiple": thousand_x_target_multiple,
        "required_growth_multiple": feasibility_classification["required_growth_multiple"],
        "horizon_years": horizon_years,
        "horizon_days": feasibility_classification["horizon_days"],
        "required_monthly_return": round(monthly_required, 8),
        "required_daily_return": round(daily_required, 8),
        "required_log_growth": observed_growth_evidence["required_log_growth"],
        "required_cagr": feasibility_classification["required_cagr"],
        "required_daily_log_return": feasibility_classification["required_daily_log_return"],
        "observed_daily_log_return": feasibility_classification["observed_daily_log_return"],
        "observed_cagr": feasibility_classification["observed_cagr"],
        "guaranteed_return_claim": guaranteed_return_claim,
        "no_guaranteed_return_claim": not guaranteed_return_claim,
        "explicit_horizon_classification": explicit_horizon_classification,
        "classification_dependency_gated": bool(thousand_x_blocker_reasons),
        "current_evidence_supports_feasibility_status": thousand_x_status_value == "PASSED",
        "assumption_set": feasibility_classification["assumption_set"],
        "observed_growth_evidence": observed_growth_evidence,
        "pnl_history_status": pnl_history_status,
        "counterfactual_total_expected_log_growth": sweep["total_expected_log_growth"],
        "counterfactual_best_configuration_count": sweep["best_configuration_count"],
        "classification_reason": (
            "1000x path remains unsupported unless counterfactual sweep, adaptive policy evidence, "
            "portfolio correlation budget, compounding evidence, rare-event stress, and paper/live parity all pass. "
            "Observed PnL-window projections are descriptive evidence only and are not guaranteed-return claims."
        ),
    }
    operator_safety = {
        "paper_only": True,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "withdrawals": False,
        "transfers": False,
        "old_redis_writes": False,
        "legacy_restart": False,
        "trainer_bridge_unmasked": False,
        "live_gate": LIVE_GATE,
    }
    no_live_or_exchange_mutation = (
        operator_safety["paper_only"] is True
        and operator_safety["places_real_order"] is False
        and operator_safety["test_orders"] is False
        and operator_safety["leverage_mutation"] is False
        and operator_safety["margin_mode_mutation"] is False
        and operator_safety["withdrawals"] is False
        and operator_safety["transfers"] is False
        and operator_safety["old_redis_writes"] is False
    )
    out_of_sample_live_grade_reverify_status = _out_of_sample_live_grade_reverify_status(
        generated_utc=generated_utc,
        operator_safety=operator_safety,
        accelerated_replay_status=accelerated_replay_status,
        holdout_rows=out_of_sample_holdout_rows,
        holdout_source_status=out_of_sample_holdout_source_status,
        realtime_rows=out_of_sample_realtime_rows,
        realtime_source_status=out_of_sample_realtime_source_status,
    )
    thousand_x_status.setdefault("dependency_statuses", {})
    thousand_x_status["dependency_statuses"]["out_of_sample_live_grade_reverify_status"] = (
        out_of_sample_live_grade_reverify_status.get("status")
    )
    thousand_x_status["out_of_sample_live_grade_reverify_status"] = (
        out_of_sample_live_grade_reverify_status.get("status")
    )
    if (
        enforce_out_of_sample_reverify_gate
        and out_of_sample_live_grade_reverify_status.get("status") != "PASSED"
    ):
        thousand_x_blockers = list(thousand_x_status.get("feasibility_blocker_reasons") or [])
        if "OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY_NOT_PASSED" not in thousand_x_blockers:
            thousand_x_blockers.append("OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY_NOT_PASSED")
        thousand_x_status["feasibility_blocker_reasons"] = thousand_x_blockers
        thousand_x_status["status"] = "NO_GO_1000X_FEASIBILITY_REQUIRES_OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY"
        thousand_x_status["classification_dependency_gated"] = True
        thousand_x_status["current_evidence_supports_feasibility_status"] = False
        thousand_x_status["honest_interpretation"] = (
            out_of_sample_live_grade_reverify_status.get("honest_interpretation") or {}
        )
    replay_symbol_count = int(accelerated_replay_status.get("symbol_count") or 0)
    replay_symbol_diversity_pass = replay_symbol_count >= ACCELERATED_REPLAY_MIN_SYMBOLS
    realtime_symbol_diversity_pass = symbol_count >= FAST_GATE_MIN_REALTIME_SYMBOLS
    phase_symbol_diversity_pass = realtime_symbol_diversity_pass or replay_symbol_diversity_pass
    phase_symbol_diversity_basis = (
        "realtime_paper"
        if realtime_symbol_diversity_pass else
        "accelerated_replay"
        if replay_symbol_diversity_pass else
        "not_ready"
    )
    phase_blockers: list[str] = []
    if a_grade_dynamic_calibration_status.get("status") != "PASSED":
        phase_blockers.append("DYNAMIC_A_GRADE_CALIBRATION_NOT_PROVEN")
    if int(positive_edge_below_a_grade_resolution.get("b_grade_exploration_candidate_count") or 0) <= 0:
        phase_blockers.append("B_GRADE_EXPLORATION_NOT_ACTIVE")
    if accelerated_replay_status.get("status") != "PASSED":
        phase_blockers.append("ACCELERATED_REPLAY_EVIDENCE_NOT_READY")
    if int(sweep.get("a_grade_before_temporal_count") or 0) <= 0:
        phase_blockers.append("STRICT_A_GRADE_CANDIDATES_MISSING")
    if int(sweep.get("best_configuration_count") or 0) <= 0:
        phase_blockers.append("FEASIBLE_CAPITAL_CONFIGURATIONS_MISSING")
    if int(capital_productivity.get("a_grade_opportunities_underfunded") or 0) > 0:
        phase_blockers.append("A_GRADE_CANDIDATES_UNDERFUNDED")
    if explicit_horizon_classification is not True:
        phase_blockers.append("ONE_THOUSAND_X_EXPLICIT_HORIZON_CLASSIFICATION_MISSING")
    if rare_event_status.get("status") != "PASSED":
        phase_blockers.append("RARE_EVENT_STRESS_NOT_PASSED")
    if (
        enforce_out_of_sample_reverify_gate
        and out_of_sample_live_grade_reverify_status.get("status") != "PASSED"
    ):
        phase_blockers.append("OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY_NOT_PASSED")
    if evidence_count < FAST_GATE_MIN_REALTIME_OUTCOMES:
        phase_blockers.append("INSUFFICIENT_REALTIME_PAPER_ECONOMIC_OUTCOMES_FOR_PHASE")
    if not phase_symbol_diversity_pass:
        phase_blockers.append("INSUFFICIENT_PHASE_SYMBOL_DIVERSITY")
    if long_count < FAST_GATE_MIN_REALTIME_SIDE_CLOSES:
        phase_blockers.append("INSUFFICIENT_REALTIME_LONG_CLOSES_FOR_PHASE")
    if short_count < FAST_GATE_MIN_REALTIME_SIDE_CLOSES:
        phase_blockers.append("INSUFFICIENT_REALTIME_SHORT_CLOSES_FOR_PHASE")
    if positive_after_cost_expectancy is not True:
        phase_blockers.append("NON_POSITIVE_REALTIME_AFTER_COST_EXPECTANCY")
    if no_live_or_exchange_mutation is not True:
        phase_blockers.append("LIVE_OR_EXCHANGE_MUTATION_DETECTED")
    stop_waiting_phase_status = {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "phase_id": STOP_WAITING_PHASE_ID,
        "generated_utc": generated_utc,
        "status": (
            f"{STOP_WAITING_PHASE_ID}_READY"
            if not phase_blockers else f"{STOP_WAITING_PHASE_ID}_BLOCKED"
        ),
        "blocker_reasons": phase_blockers,
        "required_ready_evidence": [
            "dynamic_a_grade_calibration_proven",
            "b_grade_paper_exploration_active",
            "ten_thousand_plus_valid_replay_outcomes",
            "strict_a_grade_candidates_exist",
            "feasible_capital_configurations_exist",
            "a_grade_candidates_not_underfunded",
            "one_thousand_x_explicit_horizon_classified",
            "no_live_or_exchange_mutation",
        ],
        "fast_evidence_gate": {
            "minimum_replay_outcomes": ACCELERATED_REPLAY_MIN_ECONOMIC_OUTCOMES,
            "replayed_economic_candidate_count": accelerated_replay_status.get(
                "replayed_economic_candidate_count"
            ),
            "minimum_replay_symbols": ACCELERATED_REPLAY_MIN_SYMBOLS,
            "replay_symbol_count": replay_symbol_count,
            "replay_symbol_diversity_pass": replay_symbol_diversity_pass,
            "minimum_realtime_paper_economic_outcomes": FAST_GATE_MIN_REALTIME_OUTCOMES,
            "realtime_paper_economic_outcome_count": evidence_count,
            "minimum_realtime_paper_symbols": FAST_GATE_MIN_REALTIME_SYMBOLS,
            "realtime_paper_symbol_count": symbol_count,
            "realtime_symbol_diversity_pass": realtime_symbol_diversity_pass,
            "phase_symbol_diversity_pass": phase_symbol_diversity_pass,
            "phase_symbol_diversity_basis": phase_symbol_diversity_basis,
            "realtime_symbol_diversity_still_counts_for_operator_go": (
                not realtime_symbol_diversity_pass
            ),
            "minimum_realtime_long_closes": FAST_GATE_MIN_REALTIME_SIDE_CLOSES,
            "realtime_long_close_count": long_count,
            "minimum_realtime_short_closes": FAST_GATE_MIN_REALTIME_SIDE_CLOSES,
            "realtime_short_close_count": short_count,
            "positive_replay_expectancy_after_cost": (
                accelerated_replay_status.get("replay_expectancy_positive") is True
            ),
            "positive_realtime_expectancy_after_cost": positive_after_cost_expectancy,
            "capital_deployment_reconciliation_pass": (
                int(capital_productivity.get("a_grade_opportunities_underfunded") or 0) == 0
            ),
            "rare_event_stress_pass": rare_event_status.get("status") == "PASSED",
        },
        "dynamic_a_grade_calibration_status": a_grade_dynamic_calibration_status.get("status"),
        "b_grade_exploration_candidate_count": positive_edge_below_a_grade_resolution.get(
            "b_grade_exploration_candidate_count"
        ),
        "accelerated_replay_status": accelerated_replay_status.get("status"),
        "out_of_sample_live_grade_reverify_status": out_of_sample_live_grade_reverify_status.get("status"),
        "strict_a_grade_candidate_count": int(sweep.get("a_grade_before_temporal_count") or 0),
        "feasible_capital_configuration_count": int(sweep.get("best_configuration_count") or 0),
        "a_grade_opportunities_underfunded": capital_productivity.get("a_grade_opportunities_underfunded"),
        "explicit_horizon_classification": explicit_horizon_classification,
        "no_live_or_exchange_mutation": no_live_or_exchange_mutation,
        "paper_only": True,
        "places_real_order": False,
        "live_gate": LIVE_GATE,
    }
    pass_condition_status = _pass_condition_status(
        capital_productivity=capital_productivity,
        accounting_status=accounting_status,
        counterfactual_status=counterfactual_status,
        adaptive_policy_status=adaptive_policy_status,
        compounding_status=compounding_status,
        rare_event_status=rare_event_status,
        thousand_x_status=thousand_x_status,
        out_of_sample_reverify_status=out_of_sample_live_grade_reverify_status,
        enforce_out_of_sample_reverify_gate=enforce_out_of_sample_reverify_gate,
        parity_status=parity_status,
        operator_safety=operator_safety,
    )
    selection_attribution_needed_counts = (
        {}
        if adaptive_selection_attribution_status.get("status") == "PASSED"
        else adaptive_selection_attribution_status.get("selection_model_input_missing_counts") or {}
    )
    overall_blockers = [
        name for name, status in {
            "capital_productivity_runtime_status": capital_productivity,
            "margin_notional_leverage_accounting_status": accounting_status,
            "counterfactual_capital_sweep_status": counterfactual_status,
            "adaptive_capital_policy_status": adaptive_policy_status,
            "portfolio_correlation_budget_status": correlation_status,
            "compounding_equity_status": compounding_status,
            "rare_event_capital_stress_status": rare_event_status,
            "one_thousand_x_feasibility_status": thousand_x_status,
            **(
                {"out_of_sample_live_grade_reverify_status": out_of_sample_live_grade_reverify_status}
                if enforce_out_of_sample_reverify_gate else {}
            ),
            "paper_live_pre_submit_parity_status": parity_status,
        }.items()
        if str(status.get("status")) not in {"PASSED"}
    ]
    operator_go_readiness = {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "status": "PASSED" if not overall_blockers else "NO_GO",
        "overall_status": "PASSED" if not overall_blockers else "NO_GO",
        "remaining_blockers": overall_blockers,
        "failed_conditions": pass_condition_status["failed_conditions"],
        "pass_condition_status_counts": pass_condition_status["condition_status_counts"],
        "evidence_to_go": {
            "closed_outcomes_needed": effective_policy_closed_outcome_deficit,
            "realtime_closed_outcomes_needed": closed_outcome_deficit_to_minimum,
            "closed_outcomes_needed_after_current_open_positions_close": (
                0
                if replay_policy_evidence_passed
                else projected_closed_outcome_deficit_after_open_close
            ),
            "realtime_closed_outcomes_needed_after_current_open_positions_close": (
                projected_closed_outcome_deficit_after_open_close
            ),
            "additional_symbols_needed": effective_policy_symbol_diversity_deficit,
            "realtime_additional_symbols_needed": symbol_diversity_deficit,
            "policy_evidence_basis": qualified_replay_policy_evidence_status.get(
                "policy_evidence_basis"
            ),
            "a_grade_replay_evidence_needed": counterfactual_replay_progress[
                "a_grade_replay_evidence_deficit"
            ],
            "counterfactual_best_configurations_needed": counterfactual_replay_progress[
                "best_configuration_deficit_to_frontier"
            ],
            "selection_attribution_rows_needed": (
                selection_attribution_needed_counts.get("complete_selection_model_input", 0)
            ),
            "leverage_selection_attribution_rows_needed": (
                selection_attribution_needed_counts.get("leverage_selection_model_input", 0)
            ),
            "margin_mode_selection_attribution_rows_needed": (
                selection_attribution_needed_counts.get("margin_mode_selection_model_input", 0)
            ),
            "hedge_budget_selection_attribution_rows_needed": (
                selection_attribution_needed_counts.get("hedge_budget_selection_model_input", 0)
            ),
        },
        "capital_productivity_progress": capital_productivity_progress,
        "qualified_replay_policy_evidence_status": qualified_replay_policy_evidence_status,
        "policy_evidence_progress": adaptive_policy_status["policy_evidence_progress"],
        "evidence_acquisition_status": evidence_acquisition_status,
        "runtime_evidence_acquisition_status": runtime_evidence_acquisition_status,
        "paper_exploration_tier_status": paper_exploration_tier_status,
        "out_of_sample_live_grade_reverify_status": out_of_sample_live_grade_reverify_status,
        "live_grade_reverify_blocker_reasons": (
            out_of_sample_live_grade_reverify_status.get("blocker_reasons") or []
        ),
        "closed_outcome_evidence_gap_analysis": closed_outcome_evidence_gap_analysis,
        "symbol_diversity_opportunity_analysis": symbol_diversity_opportunity_analysis,
        "adaptive_field_selection_evidence": adaptive_field_selection_evidence,
        "adaptive_selection_attribution_status": adaptive_selection_attribution_status,
        "pre_submit_adaptive_field_selection_evidence": (
            pre_submit_adaptive_field_selection_evidence
        ),
        "allocator_calibration_status": allocator_calibration_status,
        "liquidity_regime_adjustment_status": liquidity_regime_adjustment_status,
        "liquidation_buffer_minimum_status": liquidation_buffer_minimum_status,
        "portfolio_order_counter_status": policy_activation_funding_evidence_status[
            "portfolio_order_counter_status"
        ],
        "counterfactual_replay_progress": counterfactual_replay_progress,
        "a_grade_blocker_analysis": a_grade_blocker_analysis,
        "counterfactual_evidence_acquisition_status": counterfactual_evidence_acquisition_status,
        "strict_a_grade_acquisition_burn_down": strict_a_grade_acquisition_burn_down,
        "external_audit_blocker_burn_down": external_audit_blocker_burn_down,
        "stop_waiting_phase_status": stop_waiting_phase_status,
        "compounding_blocker_reasons": compounding_status.get("compounding_blocker_reasons", []),
        "one_thousand_x_feasibility_blocker_reasons": (
            thousand_x_status.get("feasibility_blocker_reasons") or []
        ),
        "honest_live_grade_interpretation": (
            out_of_sample_live_grade_reverify_status.get("honest_interpretation") or {}
        ),
    }
    dashboard_web_status = _dashboard_web_status(
        capital_productivity=capital_productivity,
        pnl_history_status=pnl_history_status,
        signal_prediction_accuracy_status=signal_prediction_accuracy_status,
        generated_utc=generated_utc,
    )
    compounding_status["capital_productivity_status"] = capital_productivity["status"]
    compounding_status["capital_productivity_blocker_reasons"] = (
        capital_productivity.get("capital_productivity_blocker_reasons", [])
    )
    compounding_status["capital_productivity_progress"] = capital_productivity_progress
    compounding_status["pnl_history_status"] = pnl_history_status
    compounding_status["pnl_history"] = pnl_history_status
    compounding_status["signal_prediction_accuracy_status"] = signal_prediction_accuracy_status
    compounding_status["dashboard_web_status"] = dashboard_web_status
    dashboard = {
        "schema_version": SCHEMA_VERSION,
        "goal_id": GOAL_ID,
        "generated_utc": generated_utc,
        "overall_status": "NO_GO" if overall_blockers else "PASSED",
        "remaining_blockers": overall_blockers,
        "operator_go_readiness": operator_go_readiness,
        "p0_baseline": _p0_baseline(),
        "capital_productivity_runtime_status": capital_productivity,
        "margin_notional_leverage_accounting_status": accounting_status,
        "a_grade_dynamic_calibration_status": a_grade_dynamic_calibration_status,
        "a_grade_bucket_performance_matrix": a_grade_bucket_performance_matrix,
        "positive_edge_below_a_grade_resolution": positive_edge_below_a_grade_resolution,
        "accelerated_counterfactual_replay_status": accelerated_replay_status,
        "counterfactual_efficient_frontier": counterfactual_efficient_frontier,
        "counterfactual_capital_sweep_status": counterfactual_status,
        "adaptive_capital_policy_status": adaptive_policy_status,
        "portfolio_correlation_budget_status": correlation_status,
        "compounding_equity_status": compounding_status,
        "rare_event_capital_stress_status": rare_event_status,
        "one_thousand_x_feasibility_status": thousand_x_status,
        "out_of_sample_live_grade_reverify_status": out_of_sample_live_grade_reverify_status,
        "paper_live_pre_submit_parity_status": parity_status,
        "paper_exploration_tier_status": paper_exploration_tier_status,
        "pnl_history_status": pnl_history_status,
        "signal_prediction_accuracy_status": signal_prediction_accuracy_status,
        "allocator_calibration_status": allocator_calibration_status,
        "liquidity_regime_adjustment_status": liquidity_regime_adjustment_status,
        "liquidation_buffer_minimum_status": liquidation_buffer_minimum_status,
        "policy_activation_funding_evidence_status": policy_activation_funding_evidence_status,
        "evidence_acquisition_status": evidence_acquisition_status,
        "runtime_evidence_acquisition_status": runtime_evidence_acquisition_status,
        "portfolio_order_counter_status": policy_activation_funding_evidence_status[
            "portfolio_order_counter_status"
        ],
        "strict_a_grade_acquisition_burn_down": strict_a_grade_acquisition_burn_down,
        "external_audit_blocker_burn_down": external_audit_blocker_burn_down,
        "stop_waiting_phase_status": stop_waiting_phase_status,
        "dashboard_web_status": dashboard_web_status,
        "pass_condition_status": pass_condition_status,
        "operator_safety": operator_safety,
    }
    return {
        "capital_productivity_runtime_status.json": capital_productivity,
        "margin_notional_leverage_accounting_status.json": accounting_status,
        "a_grade_dynamic_calibration_status.json": a_grade_dynamic_calibration_status,
        "a_grade_bucket_performance_matrix.json": a_grade_bucket_performance_matrix,
        "positive_edge_below_a_grade_resolution.json": positive_edge_below_a_grade_resolution,
        "accelerated_counterfactual_replay_status.json": accelerated_replay_status,
        "counterfactual_efficient_frontier.json": counterfactual_efficient_frontier,
        "counterfactual_capital_sweep_status.json": counterfactual_status,
        "adaptive_capital_policy_status.json": adaptive_policy_status,
        "portfolio_correlation_budget_status.json": correlation_status,
        "compounding_equity_status.json": compounding_status,
        "rare_event_capital_stress_status.json": rare_event_status,
        "one_thousand_x_feasibility_status.json": thousand_x_status,
        "out_of_sample_live_grade_reverify_status.json": out_of_sample_live_grade_reverify_status,
        "paper_live_pre_submit_parity_status.json": parity_status,
        "paper_exploration_tier_status.json": paper_exploration_tier_status,
        "v2_stop_waiting_a_grade_calibration_accelerated_replay_and_capital_deployment_status.json": (
            stop_waiting_phase_status
        ),
        "operator_dashboard_payload.json": dashboard,
    }


def go_no_go_markdown(dashboard: dict[str, Any]) -> str:
    p0 = dashboard.get("p0_baseline") or {}
    capital = dashboard.get("capital_productivity_runtime_status") or {}
    capital_progress = capital.get("capital_productivity_progress") or {}
    evidence_acquisition = capital.get("evidence_acquisition_status") or {}
    profit_factor_burn_down = capital.get("profit_factor_burn_down") or {}
    closed_outcome_gap = capital.get("closed_outcome_evidence_gap_analysis") or {}
    symbol_opportunity = capital.get("symbol_diversity_opportunity_analysis") or {}
    counterfactual = dashboard.get("counterfactual_capital_sweep_status") or {}
    counterfactual_progress = counterfactual.get("counterfactual_replay_progress") or {}
    counterfactual_next_gaps = counterfactual.get("counterfactual_next_evidence_gaps") or {}
    counterfactual_acquisition = counterfactual.get("counterfactual_evidence_acquisition_status") or {}
    dynamic_calibration = dashboard.get("a_grade_dynamic_calibration_status") or {}
    bucket_matrix = dashboard.get("a_grade_bucket_performance_matrix") or {}
    positive_edge_resolution = dashboard.get("positive_edge_below_a_grade_resolution") or {}
    accelerated_replay = dashboard.get("accelerated_counterfactual_replay_status") or {}
    efficient_frontier = dashboard.get("counterfactual_efficient_frontier") or {}
    stop_waiting_phase = dashboard.get("stop_waiting_phase_status") or {}
    strict_a_grade_burn_down = counterfactual.get("strict_a_grade_acquisition_burn_down") or {}
    a_grade_readiness = counterfactual.get("a_grade_readiness") or {}
    a_grade_blocker = counterfactual.get("a_grade_blocker_analysis") or {}
    prediction_probe = counterfactual.get("prediction_counterfactual_probe") or {}
    prediction_probe_readiness = prediction_probe.get("a_grade_readiness") or {}
    near_a_grade_probe = counterfactual.get("near_a_grade_counterfactual_probe") or {}
    feature_snapshot_lookup = counterfactual.get("feature_snapshot_lookup_audit") or {}
    market_cost_coverage = counterfactual.get("market_cost_evidence_coverage_status") or {}
    prediction_market_cost_coverage = prediction_probe.get("market_cost_evidence_coverage_status") or {}
    near_a_grade_market_cost_coverage = near_a_grade_probe.get("market_cost_evidence_coverage_status") or {}
    durable_accepted_counterfactual = (
        counterfactual.get("paper_ledger_accepted_counterfactual_evidence") or {}
    )
    compounding = dashboard.get("compounding_equity_status") or {}
    adaptive_policy = dashboard.get("adaptive_capital_policy_status") or {}
    policy_funding = adaptive_policy.get("policy_activation_funding_evidence_status") or {}
    funding_reconstruction = policy_funding.get("funding_pnl_reconstruction_status") or {}
    forward_funding_contract = (
        policy_funding.get("forward_funding_accounting_contract_status") or {}
    )
    order_counters = policy_funding.get("portfolio_order_counter_status") or {}
    external_audit_burn_down = dashboard.get("external_audit_blocker_burn_down") or {}
    audit_profit_factor = external_audit_burn_down.get("profit_factor") or {}
    audit_funding_pnl = external_audit_burn_down.get("funding_pnl") or {}
    audit_policy_activated_at = external_audit_burn_down.get("policy_activated_at") or {}
    audit_calibration = external_audit_burn_down.get("liquidity_regime_calibration") or {}
    audit_liquidation_buffer = external_audit_burn_down.get("liquidation_buffer_minimum") or {}
    allocator_calibration = adaptive_policy.get("allocator_calibration_status") or {}
    current_intent_calibration = (
        allocator_calibration.get("current_intent_calibration_observation") or {}
    )
    thousand_x = dashboard.get("one_thousand_x_feasibility_status") or {}
    live_grade_reverify = dashboard.get("out_of_sample_live_grade_reverify_status") or {}
    live_grade_holdout = live_grade_reverify.get("holdout_reverify_status") or {}
    live_grade_realtime = live_grade_reverify.get("realtime_paper_reverify_status") or {}
    live_grade_projection = live_grade_reverify.get("realtime_vs_replay_projection_status") or {}
    live_grade_manifest = live_grade_reverify.get("frozen_policy_manifest") or {}
    live_grade_interpretation = live_grade_reverify.get("honest_interpretation") or {}
    readiness = dashboard.get("operator_go_readiness") or {}
    evidence_to_go = readiness.get("evidence_to_go") or {}
    runtime_acquisition = (
        readiness.get("runtime_evidence_acquisition_status")
        or dashboard.get("runtime_evidence_acquisition_status")
        or {}
    )
    field_selection = readiness.get("adaptive_field_selection_evidence") or {}
    selection_attribution = readiness.get("adaptive_selection_attribution_status") or {}
    pre_submit_field_selection = (
        readiness.get("pre_submit_adaptive_field_selection_evidence") or {}
    )
    pass_conditions = (dashboard.get("pass_condition_status") or {}).get("conditions") or []
    pnl_windows = ((capital.get("pnl_history") or {}).get("windows") or [])
    pnl_window_lines = [
        (
            f"- `{window.get('window')}` PnL: `{window.get('realized_pnl_usd')}` "
            f"from `{window.get('closed_trade_count')}` closed trades; "
            f"win rate `{window.get('win_rate')}`, profit factor `{window.get('profit_factor')}`"
        )
        for window in pnl_windows
        if isinstance(window, dict)
    ] or ["- No timestamped PnL history windows available."]
    accuracy = capital.get("signal_prediction_accuracy_status") or {}
    accuracy_timeframe_lines = [
        (
            f"- `{row.get('timeframe')}` accuracy: `{row.get('accuracy')}` "
            f"from `{row.get('evaluated_count')}` evaluated rows; "
            f"PnL `{row.get('realized_pnl_usd')}`"
        )
        for row in (accuracy.get("by_timeframe") or [])
        if isinstance(row, dict)
    ] or ["- No evaluated signal/prediction accuracy rows available by timeframe."]
    dashboard_web = dashboard.get("dashboard_web_status") or {}
    dashboard_surface_lines = [
        (
            f"- `{row.get('surface_id')}` `{row.get('route')}`: "
            f"capital `{row.get('shows_capital_productivity_status')}`, "
            f"PnL windows `{row.get('shows_pnl_history_windows')}`, "
            f"accuracy `{row.get('shows_signal_prediction_accuracy')}`, "
            f"all symbol/TF matrix `{row.get('shows_all_symbol_timeframe_accuracy_matrix')}`, "
            f"row accuracy/PnL `{row.get('row_level_accuracy_pnl')}`"
        )
        for row in (dashboard_web.get("surfaces") or [])
        if isinstance(row, dict)
    ] or ["- No dashboard web surface status rows available."]
    symbol_candidate_lines = [
        (
            f"- Candidate `{row.get('source_kind')}` `{row.get('symbol')}` `{row.get('timeframe')}` "
            f"`{row.get('side')}`: confidence `{row.get('confidence')}`, edge "
            f"`{row.get('after_cost_edge_bps')}` bps, decision `{row.get('allocator_decision')}`, "
            f"reasons `{row.get('reasons')}`"
        )
        for row in (symbol_opportunity.get("candidate_symbols_without_closed_outcomes_sample") or [])[:5]
        if isinstance(row, dict)
    ] or ["- No signal/prediction symbol-diversity candidate sample available."]
    capture_request_lines = [
        (
            f"- Capture `{row.get('symbol')}` `{row.get('timeframe')}` `{row.get('side')}`: "
            f"decision `{row.get('decision_time')}`, snapshot `{row.get('feature_snapshot_id')}`, "
            f"missing `{row.get('missing_market_cost_evidence')}`, "
            f"PIT rejects `{row.get('market_cost_evidence_pit_reject_reasons')}`"
        )
        for row in (counterfactual_next_gaps.get("near_a_grade_market_cost_capture_request_sample") or [])[:5]
        if isinstance(row, dict)
    ] or ["- No near-A-grade market-cost capture request sample available."]
    market_ready_lines = [
        (
            f"- Ready `{row.get('symbol')}` `{row.get('timeframe')}` `{row.get('side')}`: "
            f"decision `{row.get('decision_time')}`, snapshot `{row.get('feature_snapshot_id')}`, "
            f"sources `{row.get('present_market_cost_evidence_fields')}`"
        )
        for row in (counterfactual_acquisition.get("near_a_grade_market_cost_ready_sample") or [])[:5]
        if isinstance(row, dict)
    ] or ["- No near-A-grade market-cost-ready sample available."]
    closest_a_grade_lines = [
        (
            f"- Closest `{row.get('source_kind')}` `{row.get('symbol')}` `{row.get('timeframe')}` "
            f"`{row.get('side')}`: confidence `{row.get('confidence')}` gap "
            f"`{row.get('confidence_gap_to_a_grade')}`, edge `{row.get('after_cost_edge_bps')}` bps, "
            f"reasons `{row.get('reasons')}`, market-cost `{row.get('market_cost_evidence_status')}`"
        )
        for row in (counterfactual_next_gaps.get("closest_a_grade_capture_request_sample") or [])[:5]
        if isinstance(row, dict)
    ] or ["- No closest A-grade capture request sample available."]
    a_grade_blocker_sample_lines = [
        (
            f"- A-grade blocker `{row.get('source_kind')}` `{row.get('symbol')}` "
            f"`{row.get('timeframe')}` `{row.get('side')}`: confidence "
            f"`{row.get('confidence')}`, edge `{row.get('after_cost_edge_bps')}` bps, "
            f"decision `{row.get('allocator_decision')}`, reasons `{row.get('reasons')}`"
        )
        for row in (
            (a_grade_blocker.get("high_confidence_missing_or_non_positive_edge_sample") or [])
            + (a_grade_blocker.get("positive_edge_below_confidence_sample") or [])
            + (a_grade_blocker.get("high_confidence_positive_edge_allocator_blocked_sample") or [])
            + (a_grade_blocker.get("strict_a_grade_before_temporal_sample") or [])
        )[:6]
        if isinstance(row, dict)
    ] or ["- No A-grade blocker sample available."]
    a_grade_source_lines = [
        (
            f"- `{source_kind}` rows `{bucket.get('row_count')}`; "
            f"confidence >= threshold `{bucket.get('confidence_at_or_above_threshold_count')}`; "
            f"positive edge `{bucket.get('positive_after_cost_edge_count')}`; "
            f"A-grade before temporal `{bucket.get('a_grade_before_temporal_count')}`; "
            f"event-time-valid `{bucket.get('event_time_valid_candidate_count')}`; "
            f"best configs `{bucket.get('best_configuration_count')}`; "
            f"confidence gap `{bucket.get('confidence_gap_to_threshold')}`; "
            f"reasons `{bucket.get('not_a_grade_reason_counts')}`"
        )
        for source_kind, bucket in sorted(
            (a_grade_readiness.get("source_kind_readiness") or {}).items()
        )
        if isinstance(bucket, dict)
    ] or ["- No counterfactual source-kind readiness rows available."]
    prediction_probe_source_lines = [
        (
            f"- `{source_kind}` rows `{bucket.get('row_count')}`; "
            f"confidence >= threshold `{bucket.get('confidence_at_or_above_threshold_count')}`; "
            f"positive edge `{bucket.get('positive_after_cost_edge_count')}`; "
            f"A-grade before temporal `{bucket.get('a_grade_before_temporal_count')}`; "
            f"event-time-valid `{bucket.get('event_time_valid_candidate_count')}`; "
            f"best configs `{bucket.get('best_configuration_count')}`; "
            f"no feasible config `{bucket.get('no_feasible_configuration_count')}`; "
            f"reasons `{bucket.get('not_a_grade_reason_counts')}`"
        )
        for source_kind, bucket in sorted(
            (prediction_probe_readiness.get("source_kind_readiness") or {}).items()
        )
        if isinstance(bucket, dict)
    ] or ["- No prediction readiness rows available."]
    return "\n".join(
        [
            f"# {GOAL_ID} GO/NO-GO",
            "",
            f"Generated UTC: `{dashboard.get('generated_utc')}`",
            "",
            f"Overall status: **{dashboard.get('overall_status')}**",
            "",
            "## P0 Freeze",
            "",
            f"- Frozen P0 baseline: `{p0.get('frozen')}`",
            f"- P0 policy version: `{p0.get('policy_version')}`",
            f"- P0 validator: `{p0.get('validator_overall_status')}` at `{p0.get('validator_generated_utc')}`",
            f"- Live gate: `{p0.get('live_gate')}`",
            "",
            "## Remaining Blockers",
            "",
            *(f"- `{item}`" for item in dashboard.get("remaining_blockers") or []),
            "",
            "## Evidence To GO",
            "",
            f"- Closed outcomes needed: `{evidence_to_go.get('closed_outcomes_needed')}`; after current open positions close `{evidence_to_go.get('closed_outcomes_needed_after_current_open_positions_close')}`",
            f"- Evidence acquisition status: `{evidence_acquisition.get('status')}`; observed rate `{evidence_acquisition.get('observed_closed_outcomes_per_day')}` closed outcomes/day; ETA to 300 `{evidence_acquisition.get('eta_days_to_300_closed_outcomes')}` days; ETA after current open positions close `{evidence_acquisition.get('eta_days_after_current_open_positions_close')}` days",
            f"- Runtime acquisition status: `{runtime_acquisition.get('status')}`; current intents built `{runtime_acquisition.get('current_intents_built')}`, accepted `{runtime_acquisition.get('current_intents_accepted')}`, blocked `{runtime_acquisition.get('current_intents_blocked')}`, stale `{runtime_acquisition.get('paper_loop_status_stale')}`; safety real orders `{runtime_acquisition.get('places_real_order')}`, legacy Redis writes `{runtime_acquisition.get('writes_legacy_redis')}`",
            f"- Additional symbols needed: `{evidence_to_go.get('additional_symbols_needed')}`",
            f"- A-grade replay evidence needed: `{evidence_to_go.get('a_grade_replay_evidence_needed')}`",
            f"- Counterfactual best configurations needed: `{evidence_to_go.get('counterfactual_best_configurations_needed')}`",
            f"- Selection attribution rows needed: `{evidence_to_go.get('selection_attribution_rows_needed')}`",
            f"- Leverage attribution rows needed: `{evidence_to_go.get('leverage_selection_attribution_rows_needed')}`",
            f"- Margin-mode attribution rows needed: `{evidence_to_go.get('margin_mode_selection_attribution_rows_needed')}`",
            f"- Hedge-budget attribution rows needed: `{evidence_to_go.get('hedge_budget_selection_attribution_rows_needed')}`",
            f"- Closest A-grade confidence gap: `{counterfactual_progress.get('closest_confidence_gap_to_a_grade')}`",
            f"- Closest A-grade edge gap bps: `{counterfactual_progress.get('closest_edge_gap_to_positive_bps')}`",
            f"- Counterfactual configurations considered: `{counterfactual_progress.get('configurations_considered_count')}` / `{counterfactual_progress.get('theoretical_configuration_count')}`; reconciled `{counterfactual_progress.get('configuration_count_reconciled')}`",
            f"- Counterfactual next evidence: `{counterfactual_next_gaps.get('required_next_evidence')}`",
            f"- Strict A-grade acquisition burn-down: `{strict_a_grade_burn_down.get('status')}`; confidence gap `{strict_a_grade_burn_down.get('closest_confidence_gap_to_a_grade')}`; edge gap `{strict_a_grade_burn_down.get('closest_edge_gap_to_positive_bps')}`; market-cost-ready near-A-grade `{strict_a_grade_burn_down.get('near_a_grade_market_cost_ready_if_confidence_improves_count')}`; counts as gate `{strict_a_grade_burn_down.get('counts_as_counterfactual_a_grade_gate')}`",
            f"- External audit blocker burn-down: `{external_audit_burn_down.get('status')}`; remaining actions `{external_audit_burn_down.get('required_actions_remaining')}`",
            f"- Live-grade reverify: `{live_grade_reverify.get('status')}`; blockers `{live_grade_reverify.get('blocker_reasons')}`",
            "",
            "## Pass Conditions",
            "",
            *(
                f"- {condition.get('label')}: `{condition.get('status')}`"
                for condition in pass_conditions
            ),
            "",
            "## Capital Productivity",
            "",
            f"- Status: `{capital.get('status')}`",
            f"- Closed post-allocator outcomes: `{capital.get('post_allocator_closed_outcome_count')}` / `{capital.get('minimum_required_closed_outcomes')}`; deficit `{capital.get('closed_outcome_deficit_to_minimum')}`",
            f"- Closed outcome progress: `{capital_progress.get('closed_outcome_progress_pct')}`; projected after open positions close `{capital_progress.get('projected_closed_outcome_count_after_current_open_positions_close')}` / `{capital_progress.get('minimum_required_closed_outcomes')}`; projected deficit `{capital_progress.get('projected_closed_outcome_deficit_after_current_open_positions_close')}`",
            f"- Evidence acquisition window: `{evidence_acquisition.get('first_closed_outcome_at')}` to `{evidence_acquisition.get('latest_closed_outcome_at')}` over `{evidence_acquisition.get('observed_window_days')}` days; latest close age `{evidence_acquisition.get('hours_since_latest_closed_outcome')}` hours; timed closed outcomes `{evidence_acquisition.get('timed_closed_outcome_count')}`",
            f"- Closed outcome evidence funnel: raw `{closed_outcome_gap.get('raw_closed_trade_count')}`, P0 closed `{closed_outcome_gap.get('post_p0_closed_trade_count')}`, adaptive-policy closed `{closed_outcome_gap.get('post_capital_policy_closed_row_count')}`, complete `{closed_outcome_gap.get('complete_post_capital_policy_closed_outcome_count')}`",
            f"- Unversioned complete P0 closed rows: `{closed_outcome_gap.get('unversioned_post_p0_closed_with_all_mandatory_fields_count')}`; potential complete outcomes after safe lineage `{closed_outcome_gap.get('potential_complete_closed_outcomes_if_unversioned_rows_gain_safe_policy_lineage')}`; remaining need `{closed_outcome_gap.get('additional_complete_closed_outcomes_needed_after_unversioned_policy_lineage')}`",
            f"- Symbol diversity progress: `{capital_progress.get('current_symbol_count')}` / `{capital_progress.get('minimum_required_symbol_count')}`; deficit `{capital_progress.get('symbol_diversity_deficit')}`",
            f"- Potential symbol count after safe unversioned lineage: `{closed_outcome_gap.get('potential_symbol_count_if_unversioned_rows_gain_safe_policy_lineage')}`; remaining symbol need `{closed_outcome_gap.get('additional_symbols_needed_after_unversioned_policy_lineage')}`",
            f"- Current closed symbols sample: `{(symbol_opportunity.get('current_closed_symbols') or [])[:30]}`",
            f"- Open-ready new symbols not yet counted: `{symbol_opportunity.get('open_ready_symbols_not_yet_counted_count')}`; sample `{(symbol_opportunity.get('open_ready_symbols_not_yet_counted') or [])[:30]}`",
            f"- Signal/prediction universe symbols without closed outcomes: `{symbol_opportunity.get('signal_universe_symbols_without_closed_outcomes_count')}`; sample `{symbol_opportunity.get('signal_universe_symbols_without_closed_outcomes_sample')}`",
            f"- Positive-edge candidate symbols without closed outcomes: `{symbol_opportunity.get('positive_edge_candidate_symbols_without_closed_outcomes_count')}`; sample `{symbol_opportunity.get('positive_edge_candidate_symbols_without_closed_outcomes_sample')}`",
            f"- Near-A-grade candidate symbols without closed outcomes: `{symbol_opportunity.get('near_a_grade_candidate_symbols_without_closed_outcomes_count')}`; sample `{symbol_opportunity.get('near_a_grade_candidate_symbols_without_closed_outcomes_sample')}`",
            f"- Potential symbol count if open-ready and positive-edge candidates close: `{symbol_opportunity.get('potential_symbol_count_if_open_ready_and_positive_edge_candidates_close')}`; remaining need `{symbol_opportunity.get('additional_symbols_needed_if_open_ready_and_positive_edge_candidates_close')}`",
            f"- Symbol diversity gate note: `{symbol_opportunity.get('gate_note')}`",
            *symbol_candidate_lines,
            f"- Accepted-fill reconciled closed outcomes: `{(capital.get('accepted_fill_policy_reconciliation') or {}).get('complete_reconciled_closed_outcome_count')}`",
            f"- Post-allocator realized PnL: `{capital.get('post_allocator_realized_pnl_usd')}`",
            f"- Closed deployed margin: `{capital.get('closed_deployed_margin_usd')}`",
            f"- Return on deployed margin: `{capital.get('return_on_deployed_margin')}`",
            f"- Break-even realized PnL gap: `{capital_progress.get('break_even_realized_pnl_gap_usd')}`; return gap to zero `{capital_progress.get('return_on_deployed_margin_gap_to_zero')}`",
            f"- After-cost expectancy bps: `{capital.get('after_cost_expectancy_bps')}`",
            f"- Profit factor: `{capital.get('profit_factor')}` vs minimum `{capital.get('minimum_required_profit_factor')}`; status `{capital.get('post_allocator_performance_status')}`; win rate `{capital.get('post_allocator_win_rate')}`; gross profit/loss `{capital.get('post_allocator_realized_profit_usd')}` / `{capital.get('post_allocator_realized_loss_usd')}`",
            f"- Profit factor burn-down: additional gross profit needed `{profit_factor_burn_down.get('additional_gross_profit_needed_usd')}` assuming no added gross loss; target gross profit `{profit_factor_burn_down.get('target_gross_profit_usd_at_current_loss')}`; cohort `{profit_factor_burn_down.get('closed_outcome_count')}` / `{profit_factor_burn_down.get('minimum_required_closed_outcomes')}`; sample status `{profit_factor_burn_down.get('sample_size_status')}`",
            "",
            "## Adaptive Field Selection",
            "",
            f"- Selection attribution status: `{selection_attribution.get('status')}`",
            f"- Selection attribution blockers: `{selection_attribution.get('blocker_reasons')}`",
            f"- Complete selection model-input coverage: `{selection_attribution.get('complete_selection_model_input_coverage')}` from `{selection_attribution.get('complete_selection_model_input_count')}` / `{selection_attribution.get('row_count')}` rows",
            f"- Selection attribution missing counts: `{selection_attribution.get('selection_model_input_missing_counts')}`",
            f"- Required selection field coverage: `{field_selection.get('required_selection_field_coverage')}` from `{field_selection.get('row_count')}` rows",
            f"- Current pre-submit field coverage: `{pre_submit_field_selection.get('required_selection_field_coverage')}` from `{pre_submit_field_selection.get('row_count')}` rows",
            f"- Runtime leverage model-input coverage: `{field_selection.get('leverage_selection_model_input_coverage')}`",
            f"- Runtime margin-mode model-input coverage: `{field_selection.get('margin_mode_selection_model_input_coverage')}`",
            f"- Runtime hedge-budget model-input coverage: `{field_selection.get('hedge_budget_selection_model_input_coverage')}`",
            f"- Gross notional unique count: `{field_selection.get('gross_notional_unique_count')}`",
            f"- Current pre-submit gross notional unique count: `{pre_submit_field_selection.get('gross_notional_unique_count')}`",
            f"- Allocated margin unique count: `{field_selection.get('allocated_margin_unique_count')}`",
            f"- Current pre-submit allocated margin unique count: `{pre_submit_field_selection.get('allocated_margin_unique_count')}`",
            f"- Effective leverage values: `{field_selection.get('effective_leverage_values')}`",
            f"- Current pre-submit effective leverage values: `{pre_submit_field_selection.get('effective_leverage_values')}`",
            f"- Recommended margin modes: `{field_selection.get('recommended_margin_modes')}`",
            f"- Current pre-submit margin modes: `{pre_submit_field_selection.get('recommended_margin_modes')}`",
            f"- Margin-mode selection reason counts: `{field_selection.get('margin_mode_selection_reason_counts')}`",
            f"- Current pre-submit margin-mode reason counts: `{pre_submit_field_selection.get('margin_mode_selection_reason_counts')}`",
            f"- Hedge-budget values sample: `{field_selection.get('hedge_budget_values_sample')}`",
            f"- Current pre-submit hedge-budget values sample: `{pre_submit_field_selection.get('hedge_budget_values_sample')}`",
            f"- Hedge-budget selection reason counts: `{field_selection.get('hedge_budget_selection_reason_counts')}`",
            f"- Current pre-submit hedge-budget reason counts: `{pre_submit_field_selection.get('hedge_budget_selection_reason_counts')}`",
            "",
            "## Allocator Calibration",
            "",
            f"- Status: `{allocator_calibration.get('status')}`",
            f"- Gap reasons: `{allocator_calibration.get('calibration_gap_reasons')}`",
            f"- Policy rows: `{allocator_calibration.get('policy_row_count')}`; liquidity adjustments `{allocator_calibration.get('liquidity_adjustment_values')}`; liquidity scores `{allocator_calibration.get('liquidity_score_values')}`",
            f"- Policy regime adjustments `{allocator_calibration.get('regime_adjustment_values')}`; regime scores `{allocator_calibration.get('regime_score_values')}`",
            f"- Current intent observation: `{current_intent_calibration.get('status')}` from `{current_intent_calibration.get('current_versioned_intent_row_count')}` versioned intents; sized `{current_intent_calibration.get('current_sized_intent_row_count')}`, blocked `{current_intent_calibration.get('current_allocator_blocked_intent_count')}`",
            f"- Current intent liquidity adjustments `{current_intent_calibration.get('liquidity_adjustment_values')}`; liquidity scores `{current_intent_calibration.get('liquidity_score_values')}`",
            f"- Current intent regime adjustments `{current_intent_calibration.get('regime_adjustment_values')}`; regime scores `{current_intent_calibration.get('regime_score_values')}`",
            f"- Current intent counts as policy outcome gate: `{current_intent_calibration.get('counts_as_policy_outcome_calibration_gate')}`",
            "",
            "## Policy Activation And Funding",
            "",
            f"- Status: `{policy_funding.get('status')}`",
            f"- Blocker reasons: `{policy_funding.get('blocker_reasons')}`",
            f"- Policy activation timestamp coverage: `{policy_funding.get('policy_activated_at_present_count')}` / `{policy_funding.get('policy_activation_audit_row_count')}`; missing `{policy_funding.get('policy_activated_at_missing_count')}`",
            f"- Funding PnL accounted closed outcomes: `{policy_funding.get('funding_pnl_accounted_count')}` / `{policy_funding.get('funding_pnl_audit_closed_outcome_count')}`; unaccounted `{policy_funding.get('funding_pnl_unaccounted_count')}`; nonzero `{policy_funding.get('funding_pnl_nonzero_count')}`",
            f"- Funding PnL reconstruction diagnostic: `{funding_reconstruction.get('status')}`; reconstructable `{funding_reconstruction.get('reconstructable_closed_outcome_count')}`; total `{funding_reconstruction.get('reconstructed_funding_pnl_total_usd')}`; counts as accounted `{funding_reconstruction.get('counts_as_accounted_funding_pnl')}`",
            f"- Forward funding accounting contract: `{forward_funding_contract.get('status')}`; ready `{forward_funding_contract.get('ready_forward_row_count')}` / `{forward_funding_contract.get('forward_row_count')}` accepted/open rows; missing `{forward_funding_contract.get('missing_reason_counts')}`; counts as closed-outcome gate `{forward_funding_contract.get('counts_as_closed_outcome_funding_gate')}`",
            f"- Funding PnL source counts: `{policy_funding.get('funding_pnl_source_counts')}`",
            f"- Funding PnL accounting versions: `{policy_funding.get('funding_pnl_accounting_version_counts')}`; statuses `{policy_funding.get('funding_pnl_accounting_status_counts')}`",
            f"- Named order counter status: `{order_counters.get('status')}`; missing `{order_counters.get('missing_counter_fields')}`; live orders `{order_counters.get('live_order_count')}`, test orders `{order_counters.get('test_order_count')}`, exchange mutations `{order_counters.get('exchange_order_mutation_count')}`",
            f"- External audit policy/funding counters: policy timestamps `{audit_policy_activated_at.get('present_count')}` / `{audit_policy_activated_at.get('audit_row_count')}`; funding accounted `{audit_funding_pnl.get('accounted_count')}` with unaccounted `{audit_funding_pnl.get('unaccounted_count')}`; named counters `{(external_audit_burn_down.get('named_order_counters') or {}).get('status')}`",
            f"- External audit calibration/liquidation: calibration `{audit_calibration.get('status')}` gaps `{audit_calibration.get('calibration_gap_reasons')}`; liquidation buffer verified `{audit_liquidation_buffer.get('verified')}`",
            "",
            "## PnL History",
            "",
            *pnl_window_lines,
            "",
            "## Signal/Prediction Accuracy",
            "",
            f"- Status: `{accuracy.get('status')}`",
            f"- Overall accuracy: `{accuracy.get('overall_accuracy')}` from `{accuracy.get('evaluated_row_count')}` evaluated rows",
            f"- Symbol universe count: `{accuracy.get('symbol_universe_count')}`",
            f"- Required symbol/timeframe cells without evaluated outcomes: `{accuracy.get('required_symbol_timeframe_cells_without_evaluated_outcomes_count')}`",
            *accuracy_timeframe_lines,
            "",
            "## Dashboard/Web Visibility",
            "",
            f"- Status: `{dashboard_web.get('status')}`",
            f"- Required PnL windows published: `{dashboard_web.get('all_required_pnl_windows_published')}`; windows `{dashboard_web.get('published_pnl_windows')}`",
            f"- All symbol/timeframe accuracy cells published: `{dashboard_web.get('all_symbol_timeframe_accuracy_cells_published')}`",
            f"- Accuracy cells published/evaluated/missing evaluated: `{dashboard_web.get('published_symbol_timeframe_cell_count')}` / `{dashboard_web.get('evaluated_symbol_timeframe_cell_count')}` / `{dashboard_web.get('missing_evaluated_symbol_timeframe_cell_count')}`",
            f"- Web surface count: `{dashboard_web.get('web_surface_count')}`",
            f"- All tracked surfaces show capital productivity status: `{dashboard_web.get('all_tracked_surfaces_show_capital_productivity_status')}`",
            f"- All tracked surfaces show 1D/1W/30D PnL windows: `{dashboard_web.get('all_tracked_surfaces_show_pnl_history_windows')}`",
            f"- All tracked surfaces show signal/prediction accuracy: `{dashboard_web.get('all_tracked_surfaces_show_signal_prediction_accuracy')}`",
            f"- All tracked surfaces show all symbol/TF accuracy matrix: `{dashboard_web.get('all_tracked_surfaces_show_all_symbol_timeframe_accuracy_matrix')}`",
            f"- Row-level accuracy/PnL surface count: `{dashboard_web.get('row_level_accuracy_pnl_surface_count')}`",
            *dashboard_surface_lines,
            "",
            "## Out-of-Sample Live-Grade Reverify",
            "",
            f"- Status: `{live_grade_reverify.get('status')}`",
            f"- Gate ID: `{live_grade_reverify.get('goal_id')}`",
            f"- Honest interpretation: `{live_grade_interpretation}`",
            f"- Frozen selector fingerprint: `{live_grade_manifest.get('selector_policy_fingerprint')}`",
            f"- Holdout status: `{live_grade_holdout.get('status')}`; valid rows `{live_grade_holdout.get('valid_frozen_selector_row_count')}` / required `{live_grade_holdout.get('minimum_required_a_grade_outcomes')}`; symbols `{live_grade_holdout.get('symbol_count')}` / `{live_grade_holdout.get('minimum_required_symbol_count')}`; PF `{live_grade_holdout.get('profit_factor')}`; expectancy `{live_grade_holdout.get('expectancy_after_cost_bps')}` bps",
            f"- Realtime paper status: `{live_grade_realtime.get('status')}`; valid rows `{live_grade_realtime.get('valid_frozen_selector_row_count')}` / required `{live_grade_realtime.get('minimum_required_a_grade_outcomes')}`; symbols `{live_grade_realtime.get('symbol_count')}` / `{live_grade_realtime.get('minimum_required_symbol_count')}`; PF `{live_grade_realtime.get('profit_factor')}`; expectancy `{live_grade_realtime.get('expectancy_after_cost_bps')}` bps",
            f"- Realtime vs replay projection: `{live_grade_projection.get('status')}`; replay expectancy `{live_grade_projection.get('replay_expectancy_after_cost_bps')}` bps; realtime expectancy `{live_grade_projection.get('realtime_expectancy_after_cost_bps')}` bps; blockers `{live_grade_projection.get('blocker_reasons')}`",
            f"- Holdout source: `{(live_grade_holdout.get('source_status') or {}).get('path')}` exists `{(live_grade_holdout.get('source_status') or {}).get('exists')}`",
            f"- Realtime source: `{(live_grade_realtime.get('source_status') or {}).get('path')}` exists `{(live_grade_realtime.get('source_status') or {}).get('exists')}`",
            "",
            "## Stop-Waiting A-grade Calibration Phase",
            "",
            f"- Phase status: `{stop_waiting_phase.get('status')}`",
            f"- Phase blockers: `{stop_waiting_phase.get('blocker_reasons')}`",
            f"- Dynamic calibration: `{dynamic_calibration.get('status')}`; blockers `{dynamic_calibration.get('blocker_reasons')}`",
            f"- Evaluated outcome buckets: `{bucket_matrix.get('eligible_bucket_count')}` eligible / `{bucket_matrix.get('bucket_count')}` total from `{bucket_matrix.get('evaluated_outcome_row_count')}` evaluated outcomes",
            f"- Dynamic A-grade candidates: `{dynamic_calibration.get('dynamic_a_grade_candidate_count')}`; strict candidates `{dynamic_calibration.get('strict_a_grade_candidate_count')}`; positive-edge candidates `{dynamic_calibration.get('positive_edge_candidate_count')}`",
            f"- Positive-edge resolution: `{positive_edge_resolution.get('status')}`; counts `{positive_edge_resolution.get('classification_counts')}`",
            f"- B-grade exploration candidates: `{positive_edge_resolution.get('b_grade_exploration_candidate_count')}`; fixed dollar budget used `{positive_edge_resolution.get('fixed_dollar_budget_used')}`",
            f"- Accelerated replay: `{accelerated_replay.get('status')}`; replayed economic candidates `{accelerated_replay.get('replayed_economic_candidate_count')}` / `{accelerated_replay.get('minimum_replayed_economic_candidate_count')}`; symbols `{accelerated_replay.get('symbol_count')}` / `{accelerated_replay.get('minimum_symbol_count')}`; blockers `{accelerated_replay.get('blocker_reasons')}`",
            f"- Efficient frontier: `{efficient_frontier.get('status')}`; best configs `{efficient_frontier.get('best_configuration_count')}`; sweep results `{efficient_frontier.get('sweep_result_count')}`",
            f"- Fast evidence gate: `{stop_waiting_phase.get('fast_evidence_gate')}`",
            "",
            "## Counterfactual Sweep",
            "",
            f"- Status: `{counterfactual.get('status')}`",
            f"- Blocker reasons: `{counterfactual.get('counterfactual_blocker_reasons')}`",
            f"- Next evidence gaps: `{counterfactual_next_gaps.get('required_next_evidence')}`",
            f"- A-grade signal gap count: `{counterfactual_next_gaps.get('a_grade_signal_gap_count')}`; best configuration gap count `{counterfactual_next_gaps.get('best_configuration_gap_count')}`",
            f"- Strict A-grade acquisition burn-down: `{strict_a_grade_burn_down.get('status')}`; historical strict signals `{strict_a_grade_burn_down.get('historical_a_grade_signal_count')}`; event-time-valid `{strict_a_grade_burn_down.get('event_time_valid_a_grade_count')}`; best configs `{strict_a_grade_burn_down.get('best_configuration_count')}`; required next evidence `{strict_a_grade_burn_down.get('required_next_evidence')}`",
            *closest_a_grade_lines,
            f"- A-grade blocker analysis: `{a_grade_blocker.get('status')}`; blockers `{a_grade_blocker.get('blocker_reasons')}`",
            f"- A-grade intersection counts: confidence >= threshold `{a_grade_blocker.get('confidence_at_or_above_threshold_count')}`, positive edge `{a_grade_blocker.get('positive_after_cost_edge_count')}`, both `{a_grade_blocker.get('high_confidence_and_positive_edge_count')}`, blocked-both `{a_grade_blocker.get('high_confidence_positive_edge_allocator_blocked_count')}`, strict before temporal `{a_grade_blocker.get('strict_a_grade_before_temporal_count')}`, event-time-valid `{a_grade_blocker.get('event_time_valid_a_grade_count')}`",
            f"- A-grade blocker reason counts: `{a_grade_blocker.get('not_a_grade_reason_counts')}`",
            *a_grade_blocker_sample_lines,
            f"- Near-A-grade explicit market-cost evidence: `{counterfactual_next_gaps.get('near_a_grade_complete_market_cost_evidence_count')}` / `{counterfactual_next_gaps.get('near_a_grade_candidate_market_cost_evidence_count')}`; missing `{counterfactual_next_gaps.get('near_a_grade_missing_market_cost_reason_counts')}`; PIT rejects `{counterfactual_next_gaps.get('near_a_grade_market_cost_pit_reject_reason_counts')}`",
            f"- Counterfactual evidence acquisition: `{counterfactual_acquisition.get('status')}`; blockers `{counterfactual_acquisition.get('blocker_reasons')}`; strict gate relaxed `{counterfactual_acquisition.get('strict_a_grade_gate_relaxed')}`",
            f"- Market-cost-ready near-A-grade candidates if confidence improves: `{counterfactual_acquisition.get('near_a_grade_market_cost_ready_if_confidence_improves_count')}`; capture-required near-A-grade candidates `{counterfactual_acquisition.get('near_a_grade_market_cost_incomplete_count')}`",
            *market_ready_lines,
            *capture_request_lines,
            f"- Near-A-grade pruned configuration reasons: `{counterfactual_next_gaps.get('near_a_grade_pruned_configuration_reason_counts')}`",
            f"- Source coverage: `{counterfactual.get('source_coverage_status')}` at `{counterfactual.get('source_coverage_ratio')}`",
            f"- Durable accepted counterfactual rows: `{counterfactual.get('paper_ledger_accepted_counterfactual_row_count')}` from `{durable_accepted_counterfactual.get('accepted_candidate_row_count')}` accepted candidates; bounded to current source cells `{durable_accepted_counterfactual.get('bounded_to_current_source_symbol_timeframe_cells')}`; excluded `{durable_accepted_counterfactual.get('excluded_reason_counts')}`",
            f"- Required symbol/timeframe cells: `{counterfactual.get('observed_required_symbol_timeframe_cell_count')}` / `{counterfactual.get('required_symbol_timeframe_cell_count')}`; missing `{counterfactual.get('missing_required_symbol_timeframe_cell_count')}`",
            f"- Exact feature snapshot lookup: `{feature_snapshot_lookup.get('status')}`; requested `{feature_snapshot_lookup.get('requested_feature_snapshot_id_count')}`, available `{feature_snapshot_lookup.get('available_exact_feature_snapshot_id_count')}`, archived `{feature_snapshot_lookup.get('archived_exact_feature_snapshot_id_count')}`, missing `{feature_snapshot_lookup.get('missing_exact_feature_snapshot_id_count')}`",
            f"- A-grade signals: `{counterfactual.get('historical_a_grade_signal_count')}`",
            f"- Prediction rows probed: `{counterfactual.get('prediction_row_count')}`; probe status `{prediction_probe.get('status')}`; participates in pass gate `{prediction_probe.get('probe_participates_in_counterfactual_pass_gate')}`",
            f"- Near-A-grade probe status: `{near_a_grade_probe.get('status')}` at confidence threshold `{near_a_grade_probe.get('confidence_threshold')}`; best configs `{near_a_grade_probe.get('best_configuration_count')}`; participates in pass gate `{near_a_grade_probe.get('probe_participates_in_counterfactual_pass_gate')}`",
            f"- Near-A-grade temporal-invalid count: `{near_a_grade_probe.get('skipped_temporal_invalid_count')}`",
            f"- A-grade replay progress: `{counterfactual_progress.get('a_grade_replay_progress_pct')}`; deficit `{counterfactual_progress.get('a_grade_replay_evidence_deficit')}`",
            f"- Configuration-space reconciliation: `{counterfactual_progress.get('feasible_plus_pruned_reconciled')}`",
            f"- Event-time-valid candidates: `{counterfactual.get('event_time_valid_candidate_count')}`",
            f"- Best configurations: `{counterfactual.get('best_configuration_count')}`",
            f"- Market depth requirement: `{counterfactual.get('market_depth_capacity_requirement')}`",
            f"- Market cost requirement: `{counterfactual.get('market_cost_evidence_requirement')}`",
            f"- Market cost evidence coverage: `{market_cost_coverage.get('status')}` with `{market_cost_coverage.get('complete_candidate_count')}` / `{market_cost_coverage.get('candidate_row_count')}` complete A-grade candidates; missing `{market_cost_coverage.get('missing_reason_counts')}`",
            f"- Prediction market cost evidence coverage: `{prediction_market_cost_coverage.get('status')}` with `{prediction_market_cost_coverage.get('complete_candidate_count')}` / `{prediction_market_cost_coverage.get('candidate_row_count')}` complete candidates; missing `{prediction_market_cost_coverage.get('missing_reason_counts')}`",
            f"- Near-A-grade market cost evidence coverage: `{near_a_grade_market_cost_coverage.get('status')}` with `{near_a_grade_market_cost_coverage.get('complete_candidate_count')}` / `{near_a_grade_market_cost_coverage.get('candidate_row_count')}` complete candidates; missing `{near_a_grade_market_cost_coverage.get('missing_reason_counts')}`",
            "",
            "## A-grade Readiness",
            "",
            f"- Confidence threshold: `{a_grade_readiness.get('confidence_threshold')}`",
            f"- After-cost edge threshold bps: `{a_grade_readiness.get('after_cost_edge_bps_min_exclusive')}`",
            f"- Source kind counts: `{a_grade_readiness.get('source_kind_counts')}`",
            f"- Readiness blockers: `{a_grade_readiness.get('readiness_blocker_reasons')}`",
            *a_grade_source_lines,
            "- Prediction probe is readiness-only and does not participate in the actionable counterfactual pass gate.",
            f"- Prediction source kind counts: `{prediction_probe_readiness.get('source_kind_counts')}`",
            f"- Prediction readiness blockers: `{prediction_probe_readiness.get('readiness_blocker_reasons')}`",
            *prediction_probe_source_lines,
            "",
            "## Compounding Evidence",
            "",
            f"- Status: `{compounding.get('status')}`",
            f"- Closed outcomes: `{compounding.get('closed_outcome_evidence_count')}` / `{compounding.get('minimum_required_closed_outcomes')}`; deficit `{compounding.get('closed_outcome_deficit_to_minimum')}`",
            f"- Accepted-fill reconciled closed outcomes: `{(compounding.get('accepted_fill_policy_reconciliation') or {}).get('complete_reconciled_closed_outcome_count')}`",
            f"- Symbol diversity: `{compounding.get('post_allocator_symbol_count')}` / `{compounding.get('minimum_required_symbol_count')}`; deficit `{compounding.get('symbol_diversity_deficit')}`",
            f"- Direction outcomes: long `{compounding.get('long_closed_outcome_count')}`, short `{compounding.get('short_closed_outcome_count')}`",
            f"- Positive deployed-margin return: `{compounding.get('positive_return_on_deployed_margin')}`",
            f"- Counterfactual status: `{compounding.get('counterfactual_status')}`",
            f"- Counterfactual efficient frontier ready: `{compounding.get('counterfactual_efficient_frontier_ready')}`",
            "",
            "## 1000x Classification",
            "",
            f"- Status: `{thousand_x.get('status')}`",
            f"- Classification: `{thousand_x.get('classification')}`",
            f"- Horizon years: `{thousand_x.get('horizon_years')}`",
            f"- Horizon days: `{thousand_x.get('horizon_days')}`",
            f"- Required CAGR: `{thousand_x.get('required_cagr')}`",
            f"- Required monthly return: `{thousand_x.get('required_monthly_return')}`",
            f"- Required daily return: `{thousand_x.get('required_daily_return')}`",
            f"- Explicit horizon classification: `{thousand_x.get('explicit_horizon_classification')}`",
            f"- No guaranteed-return claim: `{thousand_x.get('no_guaranteed_return_claim')}`",
            f"- Dependency-gated by current evidence: `{thousand_x.get('classification_dependency_gated')}`",
            f"- Current evidence supports feasibility status: `{thousand_x.get('current_evidence_supports_feasibility_status')}`",
            f"- Guaranteed-return claim: `{thousand_x.get('guaranteed_return_claim')}`",
            "",
            "## Safety",
            "",
            "- No real orders, test orders, leverage mutation, margin-mode mutation, withdrawals, transfers, old Redis writes, legacy restart, or trainer bridge unmask are approved by this status.",
            "- Any live canary remains a separate operator-approved phase.",
            "",
        ]
    )


def write_statuses(statuses: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for filename in STATUS_FILENAMES:
        (out_dir / filename).write_text(json.dumps(statuses[filename], indent=2, sort_keys=False) + "\n")
    (out_dir / "GO_NO_GO.md").write_text(go_no_go_markdown(statuses["operator_dashboard_payload.json"]))


def _candle_rows_from_payload(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, (dict, list))]
    if not isinstance(payload, dict):
        return []
    for key in ("candles", "rows", "items", "data", "market_candles"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, (dict, list))]
    if any(key in payload for key in ("close", "close_time", "candle_close_time", "ohlcv")):
        return [dict(payload)]
    return []


def _read_correlation_candles_from_redis(
    client: Any | None,
    symbols: list[str],
) -> tuple[dict[str, list[Any]], dict[str, str]]:
    if client is None:
        return {}, {}
    candles_by_symbol: dict[str, list[Any]] = {}
    source_by_symbol: dict[str, str] = {}
    for symbol in sorted({symbol.upper() for symbol in symbols if symbol}):
        candidate_keys = (
            f"v2:market:ohlcv:binance:{symbol}:{CORRELATION_CANDLE_TIMEFRAME}",
            f"v2:market:ohlcv_closed:binance:{symbol}:{CORRELATION_CANDLE_TIMEFRAME}",
        )
        for key in candidate_keys:
            rows = _candle_rows_from_payload(_redis_json(client, key))
            if rows:
                candles_by_symbol[symbol] = rows
                source_by_symbol[symbol] = key
                break
    return candles_by_symbol, source_by_symbol


def build_from_runtime(*, horizon_years: float) -> dict[str, Any]:
    client = _connect_redis()
    ledger = _redis_json(client, "v2:paper:ledger") or {}
    portfolio = _redis_json(client, "v2:portfolio:state") or {}
    paper_signals = _scan_redis_json_rows(client, "v2:signals:paper:*", limit=5000)
    prediction_rows = _scan_redis_json_rows(client, "v2:prediction:*", limit=5000)
    latest_feature_rows = _scan_redis_json_rows(client, "v2:features:latest:*", limit=5000)
    archived_feature_rows = _read_archived_feature_rows_from_redis(
        client,
        prediction_rows + paper_signals,
        limit=5000,
    )
    feature_rows = latest_feature_rows + archived_feature_rows
    paper_intents = _read_paper_intents_from_redis(
        client,
        fallback_ledger=ledger if isinstance(ledger, dict) else None,
    )
    open_positions = _safe_rows(ledger if isinstance(ledger, dict) else {}, "open_positions")
    open_symbols = [_normalized_symbol(row) for row in open_positions]
    correlation_candles, correlation_candle_sources = _read_correlation_candles_from_redis(client, open_symbols)
    paper_status_path = REPO_ROOT / "v2/frontend/public/operator_runtime/v2_trade_management_paper/live/latest/v2_trade_management_paper_live_status.json"
    paper_status = _load_json(paper_status_path) or {}
    return build_statuses(
        ledger=ledger if isinstance(ledger, dict) else {},
        portfolio=portfolio if isinstance(portfolio, dict) else {},
        paper_status=paper_status if isinstance(paper_status, dict) else {},
        paper_intents=paper_intents,
        paper_signals=paper_signals,
        prediction_rows=prediction_rows,
        feature_rows=feature_rows,
        post_hoc_replay_bundle_path=POST_HOC_REPLAY_BUNDLE_PATH,
        native_trainer_replay_evidence_path=NATIVE_TRAINER_REPLAY_EVIDENCE_ROWS_PATH,
        closed_candle_replay_evidence_path=CLOSED_CANDLE_REPLAY_EVIDENCE_ROWS_PATH,
        out_of_sample_holdout_reverify_path=OUT_OF_SAMPLE_HOLDOUT_REVERIFY_ROWS_PATH,
        out_of_sample_realtime_reverify_path=OUT_OF_SAMPLE_REALTIME_REVERIFY_ROWS_PATH,
        enforce_out_of_sample_reverify_gate=True,
        correlation_candles_by_symbol=correlation_candles,
        correlation_candle_sources_by_symbol=correlation_candle_sources,
        horizon_years=horizon_years,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--horizon-years", type=float, default=5.0)
    args = parser.parse_args(argv)
    statuses = build_from_runtime(horizon_years=args.horizon_years)
    write_statuses(statuses, args.out_dir)
    print(json.dumps(statuses["operator_dashboard_payload.json"], indent=2, sort_keys=False))
    return 0 if statuses["operator_dashboard_payload.json"].get("overall_status") == "PASSED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
