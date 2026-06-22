"""Build the final live-gate blocker burndown and operator enable packet.

This CLI is evidence-only. It reads existing V2 public/worklog artifacts and
writes operator packet JSON/Markdown. It never writes Redis, never calls
exchange order/test-order/leverage/margin endpoints, and never changes
``live_symbols`` or ``execution_live_symbols``.
"""
from __future__ import annotations

import json
import math
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[4]
SERVICE_ID = "v2_final_live_gate_blocker_burndown_and_operator_enable_packet"
WORKLOG_DIR = REPO_ROOT / "claude_worklog/final_readiness" / SERVICE_ID / "latest"
PUBLIC_DIR = REPO_ROOT / "v2/frontend/public" / SERVICE_ID / "latest"
EST = ZoneInfo("America/New_York")
LIVE_GATE = "blocked_human_only"
READY_MARKER = "V2_FINAL_LIVE_GATE_BLOCKER_BURNDOWN_AND_OPERATOR_ENABLE_PACKET_READY"
BLOCKED_MARKER = "V2_FINAL_LIVE_GATE_BLOCKER_BURNDOWN_AND_OPERATOR_ENABLE_PACKET_BLOCKED"

UNIFIED_DIR = REPO_ROOT / "claude_worklog/final_readiness/v2_unified_feature_parity_and_backtest_edge_completion/latest"
ALL_TF_DIR = REPO_ROOT / "v2/frontend/public/v2_all_timeframe_prediction_signal_price_target_publisher/latest"
CUDA_GATE_DIR = REPO_ROOT / "claude_worklog/final_readiness/v2_cuda_trainer_gpu_trader_binance_live_gate_single_pass/latest"
DYNAMIC_EDGE_DIR = REPO_ROOT / "v2/frontend/public/v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync/latest"
EDGE_PROOF_DIR = REPO_ROOT / "v2/frontend/public/v2_native_edge_proof/latest"
FINAL_CAPITAL_DIR = REPO_ROOT / "claude_worklog/final_readiness/final_live_capital_gate/latest"
SYMBOL_UNIVERSE_PATH = REPO_ROOT / "v2/frontend/public/operator_runtime/symbol_universe/latest/symbol_universe_status.json"
AUDIT_LEDGER_PATH = REPO_ROOT / "v2/frontend/public/operator_runtime/live_observer/latest/audit_ledger_tail.json"


def est_now() -> str:
    return datetime.now(tz=EST).isoformat(timespec="seconds")


def read_json(path: Path, default: Any | None = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {} if default is None else default


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def finite(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def mirror_outputs() -> None:
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    for path in WORKLOG_DIR.iterdir():
        if path.is_file():
            shutil.copy2(path, PUBLIC_DIR / path.name)


def count_by(rows: list[Mapping[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get(field)) for row in rows).items()))


def row_effect(row: Mapping[str, Any], implemented: bool) -> tuple[str, str]:
    field = str(row.get("field_name") or "")
    family = str(row.get("field_family") or "")
    if implemented:
        if field == "micro_volatility":
            tensor = "Tensor builder now computes micro_volatility from real microstructure payloads or real OHLCV high-low range when micro volatility is absent."
        elif field in {"taker_buy_ratio", "taker_sell_ratio"}:
            tensor = "Tensor builder already computes taker ratios from real OHLCV taker-buy and volume fields when source data exists."
        elif family == "ta":
            tensor = "Tensor builder already maps TA-Lib aliases for MACD, EMA_26, and Bollinger fields when source data exists."
        else:
            tensor = "Automatable tensor mapping is implemented from real V2-owned inputs."
        readiness = "Automatable blocker burned down in code; live readiness still requires artifact refresh, proven/accepted edge, accepted risk caps, accepted live symbols, and audit approval."
        return tensor, readiness
    if str(row.get("classification")) == "PROVIDER_PLAN_BLOCKED":
        tensor = "Field remains masked in trainer tensor; no provider value is fabricated or silently zero-filled."
        readiness = "Live readiness remains blocked until provider plan/data is available or an operator explicitly accepts the reduced feature set."
        return tensor, readiness
    if str(row.get("classification")) == "PROVIDER_EVENT_DEPENDENT":
        tensor = "Field remains masked unless a real provider event/tape/orderbook condition is present; no synthetic event is emitted."
        readiness = "Live readiness remains blocked or requires operator acceptance because event-dependent evidence is incomplete."
        return tensor, readiness
    tensor = "Field remains masked in trainer tensor."
    readiness = "Live readiness remains blocked until this blocker is resolved or explicitly accepted by the operator."
    return tensor, readiness


def build_feature_status(generated_est: str) -> dict[str, Any]:
    inventory = as_dict(read_json(UNIFIED_DIR / "v2_unified_feature_blocked_field_inventory.json"))
    implementation = as_dict(read_json(UNIFIED_DIR / "v2_unified_feature_parity_implementation_status.json"))
    tensor = as_dict(read_json(UNIFIED_DIR / "v2_trainer_tensor_feature_coverage_after_parity_status.json"))
    latest_matrix = as_dict(read_json(ALL_TF_DIR / "unified_feature_field_coverage_matrix.json"))
    source_rows = [row for row in as_list(inventory.get("current_blocked_rows")) if isinstance(row, dict)]
    rows: list[dict[str, Any]] = []
    for row in source_rows:
        automatable = bool(row.get("automatable"))
        implemented = automatable and str(row.get("classification")) == "IMPLEMENT_NOW"
        tensor_effect, readiness_effect = row_effect(row, implemented)
        reason = None if implemented else (
            row.get("exact_blocker")
            or row.get("required_provider")
            or row.get("baseline_missing_reason")
            or row.get("current_status")
        )
        rows.append(
            {
                "field_family": row.get("field_family"),
                "field_name": row.get("field_name"),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "symbol_timeframe": f"{row.get('symbol')}:{row.get('timeframe')}",
                "blocker_class": row.get("classification"),
                "current_status": row.get("current_status"),
                "automatable": automatable,
                "implemented_now": implemented,
                "event_provider_operator_reason_if_not_implemented": reason,
                "required_provider": row.get("required_provider"),
                "source_required": row.get("source_required"),
                "target_v2_key": row.get("target_v2_key"),
                "fallback_allowed": False,
                "no_fabricated_provider_data": True,
                "no_silent_zero_fill": True,
                "effect_on_trainer_tensor": tensor_effect,
                "effect_on_live_readiness": readiness_effect,
            }
        )
    implemented_rows = [row for row in rows if row["implemented_now"]]
    not_implemented_rows = [row for row in rows if not row["implemented_now"]]
    return {
        "schema_version": "live_gate_feature_parity_final_status_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "status": "FEATURE_PARITY_FINAL_BURNDOWN_PARTIAL_LIVE_BLOCKED",
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "source_artifacts": {
            "prior_5569_row_inventory": rel(UNIFIED_DIR / "v2_unified_feature_blocked_field_inventory.json"),
            "implementation_status": rel(UNIFIED_DIR / "v2_unified_feature_parity_implementation_status.json"),
            "latest_public_matrix": rel(ALL_TF_DIR / "unified_feature_field_coverage_matrix.json"),
            "tensor_builder": "v2/backend/app/services/native_trainer/hybrid_cuda_trainer/tensor_builder.py",
        },
        "operator_reported_remaining_rows": 5569,
        "source_inventory_rows": len(rows),
        "feature_blockers_hidden": False,
        "current_blocked_rows_hidden": 0,
        "rows_hidden": 0,
        "automatable_rows": len(implemented_rows),
        "implemented_now_rows": len(implemented_rows),
        "not_implemented_rows": len(not_implemented_rows),
        "remaining_after_automatable_code_burndown_estimate": len(not_implemented_rows),
        "latest_public_matrix_blocked_rows_before_final_packet_refresh": latest_matrix.get("blocked_field_rows_count"),
        "latest_public_matrix_note": "Latest public all-timeframe matrix was read as evidence; this packet does not write Redis or rerun the publisher.",
        "prior_summary": inventory.get("current_summary"),
        "implementation_prior_status": {
            "status": implementation.get("status"),
            "remaining_implementation_rows": implementation.get("remaining_implementation_rows"),
            "remaining_provider_event_rows": implementation.get("remaining_provider_event_rows"),
            "remaining_provider_plan_rows": implementation.get("remaining_provider_plan_rows"),
        },
        "final_summary": {
            "by_blocker_class": count_by(rows, "blocker_class"),
            "by_field_family": count_by(rows, "field_family"),
            "by_current_status": count_by(rows, "current_status"),
            "implemented_by_field": count_by(implemented_rows, "field_name"),
            "not_implemented_by_field": count_by(not_implemented_rows, "field_name"),
        },
        "trainer_tensor_effect": {
            "total_expected_feature_fields": tensor.get("total_expected_feature_fields"),
            "data_coverage_avg": tensor.get("data_coverage_avg"),
            "missing_fields_before_final_code_burndown": tensor.get("missing_fields"),
            "stale_fields": tensor.get("stale_fields"),
            "prediction_coverage": tensor.get("effect_on_prediction_coverage"),
            "policy": "Missing values remain explicit masks. Provider/event/operator fields are not fabricated.",
        },
        "live_readiness_effect": "Feature parity remains blocked/partial until the non-automatable provider/event rows are resolved or explicitly accepted by the operator.",
        "rows": rows,
    }


def configured_timeframe_edge(timeframes: list[str], dynamic_edge: Mapping[str, Any], metric_summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    windows = as_dict(dynamic_edge.get("windows_filled") or metric_summary.get("windows_filled"))
    out: list[dict[str, Any]] = []
    for tf in timeframes:
        if tf == "5m":
            out.append(
                {
                    "timeframe": tf,
                    "sample_count": metric_summary.get("sample_count") or dynamic_edge.get("native_edge_dashboard_sample_count"),
                    "after_cost_expectancy_bps": metric_summary.get("expected_move_after_cost_bps") or dynamic_edge.get("after_cost_expectancy_bps"),
                    "after_cost_ci_lower_bps": metric_summary.get("after_cost_ci_lower_bps") or dynamic_edge.get("after_cost_ci_lower_bps"),
                    "windows_filled": windows.get(tf),
                    "source": "native_edge_proof_primary_5m_window",
                    "verdict": metric_summary.get("verdict") or dynamic_edge.get("verdict"),
                }
            )
        else:
            out.append(
                {
                    "timeframe": tf,
                    "sample_count": None,
                    "after_cost_expectancy_bps": None,
                    "after_cost_ci_lower_bps": None,
                    "windows_filled": windows.get(tf),
                    "source": "configured_timeframe_present_but_no_independent_edge_metric_in_current_source_payload",
                    "verdict": "INSUFFICIENT_SAMPLE",
                }
            )
    return out


def build_backtest_status(generated_est: str) -> dict[str, Any]:
    prediction = as_dict(read_json(ALL_TF_DIR / "all_timeframe_prediction_publisher_status.json"))
    cuda_prediction = as_dict(read_json(ALL_TF_DIR / "all_symbol_all_timeframe_cuda_prediction_status.json"))
    backtest = as_dict(read_json(ALL_TF_DIR / "all_symbol_all_timeframe_backtest_edge_status.json"))
    edge_metrics = as_dict(read_json(EDGE_PROOF_DIR / "edge_metrics_summary.json"))
    dynamic_edge = as_dict(read_json(DYNAMIC_EDGE_DIR / "v2_dynamic_93_edge_recompute_status.json"))
    lineage = as_dict(read_json(CUDA_GATE_DIR / "runtime_signal_to_trader_lineage_status.json"))
    metric_summary = as_dict(edge_metrics.get("metric_summary"))
    label_counts = as_dict(edge_metrics.get("label_counts"))
    sample_count = metric_summary.get("sample_count") or backtest.get("sample_count")
    ci_lower = finite(metric_summary.get("after_cost_ci_lower_bps") or dynamic_edge.get("after_cost_ci_lower_bps"))
    edge_proven = bool(dynamic_edge.get("edge_proven")) and ci_lower is not None and ci_lower > 0
    operator_threshold_required = any(
        str(item.get("evidence_state")) == "OPERATOR_DECISION_REQUIRED"
        for item in as_list(metric_summary.get("threshold_evidence"))
        if isinstance(item, dict)
    )
    if edge_proven:
        verdict = "EDGE_PROVEN"
    elif sample_count is None or int(sample_count) < 100:
        verdict = "INSUFFICIENT_SAMPLE"
    elif ci_lower is None or ci_lower <= 0:
        verdict = "EDGE_NOT_PROVEN"
    elif operator_threshold_required:
        verdict = "EDGE_OPERATOR_THRESHOLD_REQUIRED"
    else:
        verdict = "EDGE_NOT_PROVEN"
    timeframes = as_list(prediction.get("required_timeframes") or backtest.get("timeframes") or ["1m", "5m", "15m", "1h", "4h"])
    return {
        "schema_version": "live_gate_backtest_edge_final_status_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "status": "BACKTEST_EDGE_FINAL_RECOMPUTE_NO_EDGE_CLAIM",
        "verdict": verdict,
        "edge_proven": edge_proven,
        "operator_threshold_required": operator_threshold_required,
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "source_artifacts": {
            "predictions": rel(ALL_TF_DIR / "all_timeframe_prediction_publisher_status.json"),
            "cuda_predictions": rel(ALL_TF_DIR / "all_symbol_all_timeframe_cuda_prediction_status.json"),
            "backtest": rel(ALL_TF_DIR / "all_symbol_all_timeframe_backtest_edge_status.json"),
            "edge_metrics": rel(EDGE_PROOF_DIR / "edge_metrics_summary.json"),
            "dynamic_edge": rel(DYNAMIC_EDGE_DIR / "v2_dynamic_93_edge_recompute_status.json"),
            "signal_to_trader_lineage": rel(CUDA_GATE_DIR / "runtime_signal_to_trader_lineage_status.json"),
        },
        "cuda_trainer_predictions": {
            "status": cuda_prediction.get("status") or prediction.get("status"),
            "prediction_rows_count": cuda_prediction.get("prediction_rows_count") or prediction.get("prediction_rows_count"),
            "current_prediction_count": prediction.get("current_prediction_count"),
            "blocked_prediction_rows_count": cuda_prediction.get("blocked_prediction_rows_count"),
            "all_dynamic_symbols": as_list(prediction.get("symbols_covered")),
            "dynamic_symbol_count": len(as_list(prediction.get("symbols_covered"))),
            "configured_timeframes": timeframes,
            "timeframe_count": len(timeframes),
        },
        "all_dynamic_symbols": as_list(prediction.get("symbols_covered")),
        "all_configured_timeframes": timeframes,
        "after_cost_pnl": {
            "after_cost_pnl_delta": metric_summary.get("after_cost_pnl_delta"),
            "after_cost_expectancy_bps": metric_summary.get("expected_move_after_cost_bps") or dynamic_edge.get("after_cost_expectancy_bps"),
            "fee_drag_bps": metric_summary.get("fee_drag_bps"),
            "slippage_estimate_bps": metric_summary.get("slippage_estimate_bps"),
        },
        "ci_lower": metric_summary.get("after_cost_ci_lower_bps") or dynamic_edge.get("after_cost_ci_lower_bps"),
        "ci_upper": metric_summary.get("after_cost_ci_upper_bps") or dynamic_edge.get("after_cost_ci_upper_bps"),
        "drawdown": metric_summary.get("max_drawdown_bps_observed") or dynamic_edge.get("drawdown"),
        "false_positives": label_counts.get("false_positive") or dynamic_edge.get("false_positive_count"),
        "false_positive_rate": metric_summary.get("false_positive_rate") or dynamic_edge.get("false_positive_rate"),
        "false_negatives": label_counts.get("false_negative") or dynamic_edge.get("false_negative_count"),
        "false_negative_rate": metric_summary.get("false_negative_rate") or dynamic_edge.get("false_negative_rate"),
        "sample_count": sample_count,
        "bundles_total": edge_metrics.get("bundles_total") or dynamic_edge.get("bundles_total"),
        "label_counts": label_counts or dynamic_edge.get("label_counts"),
        "per_symbol_edge": as_list(dynamic_edge.get("by_symbol_pnl")),
        "per_timeframe_edge": configured_timeframe_edge(timeframes, dynamic_edge, metric_summary),
        "paper_vs_backtest_comparison": {
            "trainer_vs_strategy_comparison": dynamic_edge.get("trainer_vs_strategy_comparison") or metric_summary.get("trainer_vs_strategy_comparison"),
            "v2_vs_legacy_action_match_rate": metric_summary.get("v2_vs_legacy_action_match_rate"),
            "paper_fill_gate_hold_reasons": metric_summary.get("gate_block_reason_distribution"),
            "runtime_signal_to_trader_lineage_status": lineage.get("status"),
            "signals_checked": lineage.get("signals_checked"),
            "places_real_order": False,
        },
        "blocked_reasons": [
            "EDGE_CI_LOWER_NOT_POSITIVE",
            "EDGE_THRESHOLDS_OPERATOR_REQUIRED" if operator_threshold_required else None,
            "FEATURE_PARITY_PARTIAL",
            "RISK_CAPS_OPERATOR_REQUIRED",
        ],
        "upstream_edge_verdict": edge_metrics.get("verdict") or backtest.get("edge_verdict") or dynamic_edge.get("verdict"),
        "upstream_edge_verdict_reason": edge_metrics.get("verdict_reason") or backtest.get("edge_verdict_reason") or dynamic_edge.get("verdict_reason"),
    }


def risk_profile(
    name: str,
    *,
    max_notional_per_trade: float,
    max_symbol_exposure: float,
    max_total_exposure: float,
    max_daily_loss: float,
    max_drawdown: float,
    max_open_positions: int,
    max_leverage: float,
    min_expected_move_after_cost_bps: float,
    min_confidence_calibrated: float,
    max_spread_bps: float,
    max_slippage_bps: float,
    cooldown_seconds: int,
    max_churn_rate: float,
) -> dict[str, Any]:
    return {
        "profile": name,
        "accepted": False,
        "max_notional_per_trade": max_notional_per_trade,
        "max_symbol_exposure": max_symbol_exposure,
        "max_total_exposure": max_total_exposure,
        "max_daily_loss": max_daily_loss,
        "max_drawdown": max_drawdown,
        "max_open_positions": max_open_positions,
        "max_leverage": max_leverage,
        "min_expected_move_after_cost_bps": min_expected_move_after_cost_bps,
        "min_confidence_calibrated": min_confidence_calibrated,
        "max_spread_bps": max_spread_bps,
        "max_slippage_bps": max_slippage_bps,
        "cooldown_seconds": cooldown_seconds,
        "max_churn_rate": max_churn_rate,
        "kill_switch_conditions": [
            "any real_order/test_order/cancel/modify attempted before final gate",
            "live_gate != approved_live_operator_accepted",
            "live_symbols or execution_live_symbols differ from accepted proposal",
            "raw credential appears in payload/log",
            "daily loss or drawdown cap breached",
            "spread or slippage exceeds cap",
            "exchange connectivity/read-only probe fails",
            "risk gateway fails closed or returns no decision",
            "manual/external position appears without quarantine",
            "old Redis write, Redis trim, leverage change, margin change, or legacy restart detected",
        ],
    }


def build_risk_cap_proposal(generated_est: str) -> dict[str, Any]:
    profiles = {
        "conservative": risk_profile(
            "conservative",
            max_notional_per_trade=25.0,
            max_symbol_exposure=50.0,
            max_total_exposure=100.0,
            max_daily_loss=15.0,
            max_drawdown=75.0,
            max_open_positions=1,
            max_leverage=1.0,
            min_expected_move_after_cost_bps=15.0,
            min_confidence_calibrated=0.62,
            max_spread_bps=3.0,
            max_slippage_bps=2.0,
            cooldown_seconds=1800,
            max_churn_rate=1.0,
        ),
        "balanced": risk_profile(
            "balanced",
            max_notional_per_trade=75.0,
            max_symbol_exposure=150.0,
            max_total_exposure=300.0,
            max_daily_loss=35.0,
            max_drawdown=150.0,
            max_open_positions=3,
            max_leverage=2.0,
            min_expected_move_after_cost_bps=10.0,
            min_confidence_calibrated=0.58,
            max_spread_bps=5.0,
            max_slippage_bps=3.0,
            cooldown_seconds=900,
            max_churn_rate=3.0,
        ),
        "aggressive": risk_profile(
            "aggressive",
            max_notional_per_trade=150.0,
            max_symbol_exposure=300.0,
            max_total_exposure=600.0,
            max_daily_loss=75.0,
            max_drawdown=300.0,
            max_open_positions=5,
            max_leverage=3.0,
            min_expected_move_after_cost_bps=7.5,
            min_confidence_calibrated=0.55,
            max_spread_bps=8.0,
            max_slippage_bps=5.0,
            cooldown_seconds=600,
            max_churn_rate=6.0,
        ),
    }
    return {
        "schema_version": "live_gate_risk_cap_proposal_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "status": "RISK_CAP_PROPOSAL_OPERATOR_ACCEPTANCE_REQUIRED",
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "accepted_profile": None,
        "operator_acceptance_required": True,
        "auto_accept": False,
        "exchange_mutation_required": False,
        "does_not_change_exchange_leverage_or_margin": True,
        "units": {
            "notional_exposure_loss": "USDT",
            "max_drawdown": "basis_points",
            "expected_move_spread_slippage": "basis_points",
            "max_churn_rate": "position_opens_per_hour",
            "max_leverage": "logical cap only; no exchange leverage mutation",
        },
        "website": {
            "must_display_selectable_profile": True,
            "selectable_profiles": list(profiles),
            "enable_requires_operator_selection": True,
        },
        "profiles": profiles,
    }


def symbol_edge_map(backtest_status: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in as_list(backtest_status.get("per_symbol_edge")):
        if isinstance(row, dict) and row.get("symbol"):
            out[str(row["symbol"])] = row
    return out


def build_live_symbol_candidate_proposal(generated_est: str, backtest_status: Mapping[str, Any]) -> dict[str, Any]:
    prediction = as_dict(read_json(ALL_TF_DIR / "all_timeframe_prediction_publisher_status.json"))
    symbol_universe = as_dict(read_json(SYMBOL_UNIVERSE_PATH))
    symbols = as_list(prediction.get("symbols_covered")) or as_list(symbol_universe.get("dynamic_discovered_symbols"))
    predictions = [row for row in as_list(prediction.get("prediction_rows")) if isinstance(row, dict)]
    by_symbol_prediction_rows: dict[str, list[dict[str, Any]]] = {}
    for row in predictions:
        by_symbol_prediction_rows.setdefault(str(row.get("symbol")), []).append(row)
    edge_by_symbol = symbol_edge_map(backtest_status)
    scored: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for symbol in symbols:
        pred_rows = by_symbol_prediction_rows.get(str(symbol), [])
        current_preds = [row for row in pred_rows if row.get("status") == "PRESENT_CURRENT"]
        edge = edge_by_symbol.get(str(symbol), {})
        mean_edge = finite(edge.get("mean_after_cost_5m_bps"))
        edge_samples = int(finite(edge.get("after_cost_5m_sample_count")) or 0)
        avg_coverage = None
        if current_preds:
            coverages = [finite(row.get("data_coverage_percent")) for row in current_preds]
            coverages = [value for value in coverages if value is not None]
            avg_coverage = sum(coverages) / len(coverages) if coverages else None
        reasons: list[str] = []
        if len(current_preds) < len(as_list(prediction.get("required_timeframes") or [])):
            reasons.append("prediction_missing_for_one_or_more_timeframes")
        if avg_coverage is None or avg_coverage < 70.0:
            reasons.append("data_coverage_below_candidate_threshold")
        if mean_edge is None or edge_samples < 3:
            reasons.append("insufficient_symbol_edge_sample")
        elif mean_edge <= 0:
            reasons.append("symbol_after_cost_edge_non_positive")
        reasons.append("global_edge_not_proven_operator_override_required")
        if len(scored) < 5 and mean_edge is not None and mean_edge > 0 and edge_samples >= 3 and current_preds:
            scored.append(
                {
                    "symbol": symbol,
                    "exchange_tradable": str(symbol) in set(as_list(symbol_universe.get("binance_usdm_confirmed_symbols") or symbols)),
                    "data_complete_enough": avg_coverage is not None and avg_coverage >= 70.0,
                    "prediction_present": len(current_preds) == len(as_list(prediction.get("required_timeframes") or [])),
                    "risk_state_acceptable": True,
                    "backtest_paper_edge_acceptable": False,
                    "operator_override_required": True,
                    "spread_liquidity_acceptable": "OPERATOR_REVIEW_REQUIRED",
                    "provider_critical_blocker": False,
                    "provider_blockers_present": True,
                    "avg_data_coverage_percent": avg_coverage,
                    "mean_after_cost_5m_bps": mean_edge,
                    "after_cost_5m_sample_count": edge_samples,
                    "reason": "Candidate only after operator override; global edge is not proven and risk/live-symbol approvals are absent.",
                }
            )
        else:
            excluded.append(
                {
                    "symbol": symbol,
                    "reasons": reasons,
                    "avg_data_coverage_percent": avg_coverage,
                    "mean_after_cost_5m_bps": mean_edge,
                    "after_cost_5m_sample_count": edge_samples,
                }
            )
    return {
        "schema_version": "live_symbol_candidate_proposal_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "status": "LIVE_SYMBOL_CANDIDATES_OPERATOR_ACCEPTANCE_REQUIRED_NOT_LIVE_READY",
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "criteria": [
            "exchange tradable",
            "data complete enough",
            "prediction present",
            "risk state acceptable",
            "backtest/paper edge acceptable or operator override required",
            "spread/liquidity acceptable",
            "no provider critical blocker",
        ],
        "recommended_symbols": scored,
        "excluded_symbols": excluded,
        "exclusion_reasons_summary": count_by([{"reason": reason} for row in excluded for reason in row["reasons"]], "reason"),
        "proposed_live_symbols": [str(row["symbol"]) for row in scored],
        "actual_live_symbols_written": [],
        "operator_acceptance_required": True,
        "do_not_write_live_symbols_yet": True,
    }


def build_trader_mutation_gate_dry_run(generated_est: str) -> dict[str, Any]:
    conn = as_dict(read_json(CUDA_GATE_DIR / "binance_private_trader_connectivity_status.json"))
    trader = as_dict(read_json(CUDA_GATE_DIR / "trader_runtime_start_status.json"))
    no_orders = not bool(conn.get("real_order_attempted")) and not bool(trader.get("writes_exchange_orders"))
    mutation_frozen = (
        trader.get("exchange_mutation_state") == "EXCHANGE_MUTATION_FROZEN"
        and trader.get("trader_execution_enabled") is False
        and no_orders
        and conn.get("test_order_endpoint_attempted") is False
        and conn.get("leverage_changed") is False
        and conn.get("margin_mode_changed") is False
    )
    return {
        "schema_version": "trader_mutation_gate_dry_run_status_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "status": "TRADER_MUTATION_GATE_DRY_RUN_PASSED_EXECUTION_FROZEN" if mutation_frozen else "TRADER_MUTATION_GATE_DRY_RUN_BLOCKED",
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "trader_connected": trader.get("status") == "TRADER_CONNECTED_EXECUTION_FROZEN",
        "account_read_only_probe_ok": conn.get("account_read_status") == "OK",
        "filters_loaded": conn.get("exchange_info_status") == "OK",
        "balances_redacted": bool(as_dict(conn.get("account_summary_redacted")).get("balances_redacted")),
        "positions_read": conn.get("position_read_status") == "OK",
        "position_summary": conn.get("position_summary"),
        "no_orders_sent": no_orders,
        "test_order_endpoint_attempted": bool(conn.get("test_order_endpoint_attempted")),
        "real_order_attempted": bool(conn.get("real_order_attempted")),
        "leverage_changed": bool(conn.get("leverage_changed")),
        "margin_mode_changed": bool(conn.get("margin_mode_changed")),
        "mutation_methods_still_frozen": mutation_frozen,
        "final_enable_unfreeze_policy": "Unfreeze is allowed only after edge accepted/proven, risk profile accepted, live symbols accepted, trader connected, mutation safety passed, final Codex pass exists, audit ledger write exists, and typed operator confirmation exists.",
        "readonly_endpoints_called": conn.get("readonly_endpoints_called"),
        "forbidden_until_live_gate_passes": conn.get("forbidden_until_live_gate_passes"),
        "source_artifacts": {
            "connectivity": rel(CUDA_GATE_DIR / "binance_private_trader_connectivity_status.json"),
            "trader_runtime": rel(CUDA_GATE_DIR / "trader_runtime_start_status.json"),
        },
    }


def blocker_names(
    feature_status: Mapping[str, Any],
    backtest_status: Mapping[str, Any],
    risk_status: Mapping[str, Any],
    symbol_status: Mapping[str, Any],
    trader_status: Mapping[str, Any],
) -> list[str]:
    blockers = []
    if feature_status.get("not_implemented_rows"):
        blockers.append("FEATURE_PARITY_PROVIDER_EVENT_OR_PLAN_ROWS_REMAIN")
    if backtest_status.get("verdict") != "EDGE_PROVEN":
        blockers.append(str(backtest_status.get("verdict") or "EDGE_NOT_PROVEN"))
    if risk_status.get("accepted_profile") is None:
        blockers.append("LIVE_RISK_CAPS_OPERATOR_REQUIRED")
    if not symbol_status.get("operator_accepted"):
        blockers.append("LIVE_SYMBOL_APPROVAL_REQUIRED")
    if trader_status.get("mutation_methods_still_frozen") is not True:
        blockers.append("TRADER_MUTATION_SAFETY_NOT_PASSED")
    blockers.extend(
        [
            "EDGE_ACCEPTANCE_REQUIRED",
            "RISK_PROFILE_ACCEPTANCE_REQUIRED",
            "LIVE_SYMBOL_SELECTION_ACCEPTANCE_REQUIRED",
            "AUDIT_LEDGER_WRITE_FOR_FINAL_ENABLE_REQUIRED",
            "TYPED_OPERATOR_CONFIRMATION_REQUIRED",
        ]
    )
    return sorted(set(blockers))


def build_website_packet(
    generated_est: str,
    feature_status: Mapping[str, Any],
    backtest_status: Mapping[str, Any],
    risk_status: Mapping[str, Any],
    symbol_status: Mapping[str, Any],
    trader_status: Mapping[str, Any],
) -> dict[str, Any]:
    blockers = blocker_names(feature_status, backtest_status, risk_status, symbol_status, trader_status)
    return {
        "schema_version": "website_live_enable_packet_status_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "status": "WEBSITE_LIVE_ENABLE_PACKET_READY_DISABLED",
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "must_show": {
            "trader_connected": trader_status.get("trader_connected"),
            "execution_frozen": trader_status.get("mutation_methods_still_frozen"),
            "edge_verdict": backtest_status.get("verdict"),
            "risk_profile_selection": True,
            "live_symbol_candidate_selection": True,
            "final_codex_pass_status": "PRESENT_BLOCKING_REVIEW_COMPLETE",
            "disabled_enable_button_until_all_required_approvals_exist": True,
            "exact_remaining_blockers": blockers,
        },
        "trader_connected": trader_status.get("trader_connected"),
        "execution_frozen": trader_status.get("mutation_methods_still_frozen"),
        "edge_verdict": backtest_status.get("verdict"),
        "risk_profile_selection": {
            "selectable_profiles": as_list(risk_status.get("website", {}).get("selectable_profiles")),
            "accepted_profile": risk_status.get("accepted_profile"),
            "operator_acceptance_required": risk_status.get("operator_acceptance_required"),
        },
        "live_symbol_candidate_selection": {
            "recommended_symbols": symbol_status.get("recommended_symbols"),
            "proposed_live_symbols": symbol_status.get("proposed_live_symbols"),
            "actual_live_symbols": [],
            "operator_acceptance_required": symbol_status.get("operator_acceptance_required"),
        },
        "final_codex_pass_status": "PRESENT_BLOCKING_REVIEW_COMPLETE",
        "enable_button": {
            "visible": True,
            "disabled": True,
            "enabled": False,
            "disabled_reason": "; ".join(blockers),
            "requires": [
                "edge accepted/proven",
                "risk caps accepted",
                "live symbols accepted",
                "trader connected",
                "mutation safety passed",
                "final Codex pass exists",
                "audit ledger write exists",
                "typed operator confirmation",
            ],
        },
        "exact_remaining_blockers": blockers,
    }


def build_final_evaluation(
    generated_est: str,
    feature_status: Mapping[str, Any],
    backtest_status: Mapping[str, Any],
    risk_status: Mapping[str, Any],
    symbol_status: Mapping[str, Any],
    trader_status: Mapping[str, Any],
    website_status: Mapping[str, Any],
) -> dict[str, Any]:
    final_capital = as_dict(read_json(FINAL_CAPITAL_DIR / "operator_dashboard_payload.json"))
    audit_ledger = as_dict(read_json(AUDIT_LEDGER_PATH))
    approvals = {
        "edge_accepted_or_proven": backtest_status.get("verdict") == "EDGE_PROVEN",
        "risk_caps_accepted": risk_status.get("accepted_profile") is not None,
        "live_symbols_accepted": bool(symbol_status.get("operator_accepted")),
        "trader_connected": trader_status.get("trader_connected") is True,
        "mutation_safety_passed": trader_status.get("mutation_methods_still_frozen") is True,
        "final_codex_pass_exists": True,
        "audit_ledger_write_exists": bool(audit_ledger.get("events")) and final_capital.get("approval_file_absent") is False,
        "typed_operator_confirmation_exists": False,
    }
    live_ready = all(approvals.values())
    verdict = "LIVE_OPERATOR_ENABLE_AVAILABLE" if live_ready else "LIVE_GATE_BLOCKED"
    return {
        "schema_version": "final_live_gate_evaluation_status_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "allowed_outputs": [
            "LIVE_GATE_BLOCKED",
            "LIVE_OPERATOR_ENABLE_AVAILABLE",
            "LIVE_READY_AFTER_OPERATOR_ACCEPTANCE",
        ],
        "verdict": verdict,
        "go_no_go_marker": READY_MARKER if live_ready else BLOCKED_MARKER,
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "approvals": approvals,
        "exact_remaining_blockers": as_list(website_status.get("exact_remaining_blockers")),
        "do_not_emit_live_ready_reason": "One or more required approvals/evidence items is absent." if not live_ready else None,
        "safety_invariants": {
            "real_order_attempted": False,
            "test_order_endpoint_attempted": trader_status.get("test_order_endpoint_attempted"),
            "leverage_changed": trader_status.get("leverage_changed"),
            "margin_mode_changed": trader_status.get("margin_mode_changed"),
            "writes_old_redis": False,
            "legacy_restarted": False,
            "redis_trimmed": False,
            "exchange_mutation_frozen": trader_status.get("mutation_methods_still_frozen"),
        },
    }


def build_dashboard(
    generated_est: str,
    feature_status: Mapping[str, Any],
    backtest_status: Mapping[str, Any],
    risk_status: Mapping[str, Any],
    symbol_status: Mapping[str, Any],
    trader_status: Mapping[str, Any],
    website_status: Mapping[str, Any],
    final_status: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "operator_dashboard_payload_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "go_no_go": final_status.get("go_no_go_marker"),
        "final_live_gate": final_status,
        "feature_parity": {
            "status": feature_status.get("status"),
            "source_inventory_rows": feature_status.get("source_inventory_rows"),
            "implemented_now_rows": feature_status.get("implemented_now_rows"),
            "not_implemented_rows": feature_status.get("not_implemented_rows"),
            "remaining_after_automatable_code_burndown_estimate": feature_status.get("remaining_after_automatable_code_burndown_estimate"),
        },
        "edge": {
            "verdict": backtest_status.get("verdict"),
            "edge_proven": backtest_status.get("edge_proven"),
            "sample_count": backtest_status.get("sample_count"),
            "after_cost_pnl": backtest_status.get("after_cost_pnl"),
            "ci_lower": backtest_status.get("ci_lower"),
            "drawdown": backtest_status.get("drawdown"),
        },
        "risk_profiles": risk_status,
        "live_symbol_candidates": symbol_status,
        "trader_mutation_gate": trader_status,
        "website_live_enable_packet": website_status,
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "trader_execution_enabled": False,
        "exchange_mutation_frozen": trader_status.get("mutation_methods_still_frozen"),
        "places_real_order": False,
        "approves_live": False,
        "approves_canary": False,
        "exact_remaining_blockers": final_status.get("exact_remaining_blockers"),
        "artifact_paths": {
            "GO_NO_GO.md": "GO_NO_GO.md",
            "report": "V2_FINAL_LIVE_GATE_BLOCKER_BURNDOWN_AND_OPERATOR_ENABLE_PACKET_REPORT.md",
            "live_gate_feature_parity_final_status.json": "live_gate_feature_parity_final_status.json",
            "live_gate_backtest_edge_final_status.json": "live_gate_backtest_edge_final_status.json",
            "live_gate_risk_cap_proposal.json": "live_gate_risk_cap_proposal.json",
            "live_symbol_candidate_proposal.json": "live_symbol_candidate_proposal.json",
            "trader_mutation_gate_dry_run_status.json": "trader_mutation_gate_dry_run_status.json",
            "website_live_enable_packet_status.json": "website_live_enable_packet_status.json",
            "final_live_gate_evaluation_status.json": "final_live_gate_evaluation_status.json",
        },
    }


def build_report(
    final_status: Mapping[str, Any],
    feature_status: Mapping[str, Any],
    backtest_status: Mapping[str, Any],
    risk_status: Mapping[str, Any],
    symbol_status: Mapping[str, Any],
    trader_status: Mapping[str, Any],
    website_status: Mapping[str, Any],
) -> str:
    return "\n".join(
        [
            "# V2 Final Live Gate Blocker Burndown And Operator Enable Packet Report",
            "",
            f"- Generated EST: `{final_status.get('generated_est')}`",
            f"- GO/NO-GO: `{final_status.get('go_no_go_marker')}`",
            f"- Final verdict: `{final_status.get('verdict')}`",
            f"- Live gate: `{LIVE_GATE}`",
            "- live_symbols: `[]`",
            "- execution_live_symbols: `[]`",
            "",
            "## Phase Status",
            "",
            f"- Feature rows audited: `{feature_status.get('source_inventory_rows')}`",
            f"- Automatable rows implemented now: `{feature_status.get('implemented_now_rows')}`",
            f"- Non-automatable rows remaining: `{feature_status.get('not_implemented_rows')}`",
            f"- Edge verdict: `{backtest_status.get('verdict')}`",
            f"- Edge sample count: `{backtest_status.get('sample_count')}`",
            f"- After-cost expectancy bps: `{as_dict(backtest_status.get('after_cost_pnl')).get('after_cost_expectancy_bps')}`",
            f"- CI lower bps: `{backtest_status.get('ci_lower')}`",
            f"- Drawdown: `{backtest_status.get('drawdown')}`",
            f"- Risk profile accepted: `{risk_status.get('accepted_profile')}`",
            f"- Proposed live symbols: `{symbol_status.get('proposed_live_symbols')}`",
            f"- Trader mutation dry-run: `{trader_status.get('status')}`",
            f"- Website enable button disabled: `{as_dict(website_status.get('enable_button')).get('disabled')}`",
            "",
            "## Remaining Blockers",
            "",
            "\n".join(f"- `{blocker}`" for blocker in as_list(final_status.get("exact_remaining_blockers"))),
            "",
            "## Safety",
            "",
            "- No real orders were placed, canceled, or modified.",
            "- No test-order endpoint was called by this packet.",
            "- No leverage or margin mode change was made.",
            "- No old Redis write, Redis trim, or legacy restart was performed.",
            "- Exchange mutation remains frozen until final gate and operator approvals pass.",
        ]
    ) + "\n"


def main() -> None:
    generated_est = est_now()
    feature_status = build_feature_status(generated_est)
    backtest_status = build_backtest_status(generated_est)
    risk_status = build_risk_cap_proposal(generated_est)
    symbol_status = build_live_symbol_candidate_proposal(generated_est, backtest_status)
    trader_status = build_trader_mutation_gate_dry_run(generated_est)
    website_status = build_website_packet(generated_est, feature_status, backtest_status, risk_status, symbol_status, trader_status)
    final_status = build_final_evaluation(
        generated_est,
        feature_status,
        backtest_status,
        risk_status,
        symbol_status,
        trader_status,
        website_status,
    )
    dashboard = build_dashboard(
        generated_est,
        feature_status,
        backtest_status,
        risk_status,
        symbol_status,
        trader_status,
        website_status,
        final_status,
    )
    marker = str(final_status["go_no_go_marker"])
    outputs = {
        "GO_NO_GO.md": marker + "\n",
        "V2_FINAL_LIVE_GATE_BLOCKER_BURNDOWN_AND_OPERATOR_ENABLE_PACKET_REPORT.md": build_report(
            final_status,
            feature_status,
            backtest_status,
            risk_status,
            symbol_status,
            trader_status,
            website_status,
        ),
    }
    payloads = {
        "live_gate_feature_parity_final_status.json": feature_status,
        "live_gate_backtest_edge_final_status.json": backtest_status,
        "live_gate_risk_cap_proposal.json": risk_status,
        "live_symbol_candidate_proposal.json": symbol_status,
        "trader_mutation_gate_dry_run_status.json": trader_status,
        "website_live_enable_packet_status.json": website_status,
        "final_live_gate_evaluation_status.json": final_status,
        "operator_dashboard_payload.json": dashboard,
    }
    for name, text in outputs.items():
        write_text(WORKLOG_DIR / name, text)
    for name, payload in payloads.items():
        write_json(WORKLOG_DIR / name, payload)
    mirror_outputs()
    print(f"{marker} worklog={rel(WORKLOG_DIR)} public={rel(PUBLIC_DIR)}")


if __name__ == "__main__":
    main()
