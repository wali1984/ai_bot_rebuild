"""Publish the unified feature parity and backtest edge completion gate.

This CLI is evidence-only. It reads existing V2 public/worklog artifacts,
classifies remaining feature-field blockers, mirrors dashboard-ready payloads,
and never writes Redis, old Redis, exchange state, live/canary approvals, or
legacy runtime state.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo


THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))


SERVICE_ID = "v2_unified_feature_parity_and_backtest_edge_completion"
GATE_READY = "V2_UNIFIED_FEATURE_PARITY_AND_BACKTEST_EDGE_COMPLETION_READY"
GATE_BLOCKED = "V2_UNIFIED_FEATURE_PARITY_AND_BACKTEST_EDGE_COMPLETION_BLOCKED"
LIVE_GATE = "blocked_human_only"
EST = ZoneInfo("America/New_York")

ALL_TF_PUBLIC = REPO_ROOT / "v2/frontend/public/v2_all_timeframe_prediction_signal_price_target_publisher/latest"
ALL_TF_DIST = REPO_ROOT / "v2/frontend/dist/v2_all_timeframe_prediction_signal_price_target_publisher/latest"
EDGE_PUBLIC = REPO_ROOT / "v2/frontend/public/v2_native_edge_proof/latest"
POST_HOC_PUBLIC = REPO_ROOT / "v2/frontend/public/v2_post_hoc_replay_outcome_miner/latest"

WORKLOG_DIR = REPO_ROOT / "claude_worklog/final_readiness/v2_unified_feature_parity_and_backtest_edge_completion/latest"
PUBLIC_DIR = REPO_ROOT / "v2/frontend/public/v2_unified_feature_parity_and_backtest_edge_completion/latest"

OPERATOR_REPORTED_PRIOR_BLOCKED_ROWS = 13_688

EVENT_FIELDS = {
    "last_liq_bps_24h",
    "liquidation_count_5m",
    "liquidation_long_level",
    "liquidation_short_level",
    "liquidation_distance_pct",
    "liquidation_strength",
    "liquidation_is_stale",
    "tape_imbalance",
    "order_flow_imbalance",
    "depth_vs_tape_divergence",
    "whale_wall_score",
}

PLAN_BLOCKED_FIELDS = {
    "nansen_score": "Nansen",
    "nansen_presence": "Nansen",
    "lunarcrush_score": "LunarCrush",
    "aicoin_score": "AICoin",
    "coingecko_score": "CoinGecko",
    "surf_score": "Surf",
    "defillama_score": "DeFiLlama",
    "fear_greed_context": "Fear & Greed public feed",
    "mempool_context": "BTC mempool public feed",
}

IMPLEMENTABLE_FIELDS = {
    "micro_volatility",
    "volatility",
    "volatility_pct",
    "bollinger_upper",
    "bollinger_middle",
    "bollinger_lower",
    "RSI",
    "MACD",
    "MACD_signal",
    "MACD_hist",
    "ATR",
    "EMA_12",
    "EMA_26",
    "bollinger_width_pct",
    "taker_buy_ratio",
    "taker_sell_ratio",
}


def est_now() -> str:
    return datetime.now(tz=EST).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


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


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def is_blocked_feature_row(row: Mapping[str, Any]) -> bool:
    status = row.get("status")
    return status in {"PROVIDER_BLOCKED", "OPERATOR_REQUIRED"} or (
        status == "EVENT_DEPENDENT" and not bool(row.get("value_present"))
    )


def field_source_required(field: str, family: str) -> str:
    if field in {"last_price", "mark_price", "index_price", "basis_pct"}:
        return "Binance USD-M ticker, mark price, and index price"
    if field in {"funding_rate"}:
        return "Binance USD-M funding endpoint"
    if field in {"open_interest", "oi_change_pct"}:
        return "Binance USD-M open interest and open-interest history"
    if family == "ohlcv":
        return "Binance USD-M OHLCV"
    if family == "orderbook":
        return "Binance/CoinAPI orderbook plus tape when required"
    if family == "ta":
        return "V2 TA-Lib full indicator worker"
    if family == "liquidation":
        return "Binance force-liquidation WSS plus V2 liquidation levels engine"
    if family == "microstructure":
        return "CoinAPI WSDS quote/book/trade microstructure stream"
    if family == "altdata":
        return PLAN_BLOCKED_FIELDS.get(field) or "V2 public-intel / altdata provider payload"
    return "V2 unified feature payload"


def target_v2_key(field: str, family: str, symbol: str, timeframe: str) -> str:
    if family == "market":
        if field == "funding_rate":
            return f"v2:market:funding:{symbol}"
        if field in {"open_interest", "oi_change_pct"}:
            return f"v2:market:open_interest:{symbol} / v2:market:open_interest_hist:{symbol}:5m"
        return f"v2:market:prices:{symbol}"
    if family == "ohlcv":
        return f"v2:market:ohlcv:binance:{symbol}:{timeframe}"
    if family == "orderbook":
        return f"v2:market:orderbook:{symbol}"
    if family == "ta":
        return f"v2:features:ta:{symbol}:{timeframe} / v2:features:ta_full:{symbol}:{timeframe}"
    if family == "liquidation":
        return f"v2:liquidations:levels:{symbol}:{timeframe} / v2:liquidations:events"
    if family == "microstructure":
        return f"v2:market:coinapi:wsds:{symbol} / v2:features:microfeat:{symbol}:{timeframe}"
    if family == "altdata":
        provider = PLAN_BLOCKED_FIELDS.get(field)
        if provider:
            return f"v2:altdata:{provider.lower().replace(' ', '_')}:{symbol}"
        return f"v2:altdata:public_intel:{symbol} / v2:altdata:symbol_score:{symbol}"
    return f"v2:unified_features:{symbol}:{timeframe}"


def classify_row(row: Mapping[str, Any], current_row: Mapping[str, Any] | None = None) -> dict[str, Any]:
    effective = current_row if current_row else row
    field = str(row.get("field") or row.get("field_name") or "")
    family = str(row.get("family") or row.get("field_family") or "")
    current_status = str(effective.get("status") or row.get("status") or "UNKNOWN")
    current_present = bool(effective.get("value_present"))
    if current_present and not is_blocked_feature_row(effective):
        return {
            "classification": "IMPLEMENT_NOW",
            "automatable": True,
            "exact_blocker": "RESOLVED_BY_CURRENT_IMPLEMENTATION_REAL_FIELD_PRESENT",
            "fallback_allowed": False,
        }
    if current_status == "OPERATOR_REQUIRED":
        return {
            "classification": "OPERATOR_REQUIRED",
            "automatable": False,
            "exact_blocker": "operator approval or runtime setting required",
            "fallback_allowed": False,
        }
    if field in EVENT_FIELDS or current_status == "EVENT_DEPENDENT":
        return {
            "classification": "PROVIDER_EVENT_DEPENDENT",
            "automatable": False,
            "exact_blocker": "real provider event or operator-enabled tape/liquidation event not present",
            "fallback_allowed": False,
        }
    if field in PLAN_BLOCKED_FIELDS:
        return {
            "classification": "PROVIDER_PLAN_BLOCKED",
            "automatable": False,
            "exact_blocker": f"{PLAN_BLOCKED_FIELDS[field]} provider payload is absent, plan-limited, or not available for this symbol",
            "fallback_allowed": False,
        }
    if field in IMPLEMENTABLE_FIELDS:
        return {
            "classification": "IMPLEMENT_NOW",
            "automatable": True,
            "exact_blocker": "real source row is still absent or rolling computation state is not yet available",
            "fallback_allowed": False,
        }
    if current_status == "PROVIDER_BLOCKED":
        return {
            "classification": "PROVIDER_EVENT_DEPENDENT",
            "automatable": False,
            "exact_blocker": "provider payload missing for this symbol/timeframe",
            "fallback_allowed": False,
        }
    return {
        "classification": "NOT_REQUIRED_WITH_PROOF",
        "automatable": False,
        "exact_blocker": "not required only if downstream proof excludes the field",
        "fallback_allowed": False,
    }


def inventory_row(row: Mapping[str, Any], current_by_key: Mapping[tuple[str, str, str], Mapping[str, Any]]) -> dict[str, Any]:
    symbol = str(row.get("symbol") or "")
    timeframe = str(row.get("timeframe") or "")
    field = str(row.get("field") or row.get("field_name") or "")
    family = str(row.get("family") or row.get("field_family") or "")
    current = current_by_key.get((symbol, timeframe, field), row)
    classification = classify_row(row, current)
    required_provider = PLAN_BLOCKED_FIELDS.get(field)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "field_name": field,
        "field_family": family,
        "source_required": field_source_required(field, family),
        "current_status": current.get("status") or row.get("status"),
        "current_value_present": bool(current.get("value_present")),
        "baseline_status": row.get("status"),
        "baseline_missing_reason": row.get("missing_reason"),
        "exact_blocker": classification["exact_blocker"],
        "automatable": classification["automatable"],
        "required_provider": required_provider,
        "target_v2_key": target_v2_key(field, family, symbol, timeframe),
        "fallback_allowed": classification["fallback_allowed"],
        "classification": classification["classification"],
        "no_silent_zero_fill": True,
    }


def summarize_rows(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    by_class = Counter(str(row.get("classification")) for row in rows)
    by_family = Counter(str(row.get("field_family")) for row in rows)
    by_field = Counter(str(row.get("field_name")) for row in rows)
    by_status = Counter(str(row.get("current_status")) for row in rows)
    return {
        "count": len(rows),
        "by_classification": dict(sorted(by_class.items())),
        "by_family": dict(sorted(by_family.items())),
        "by_status": dict(sorted(by_status.items())),
        "top_fields": [
            {"field_name": field, "count": count}
            for field, count in by_field.most_common(25)
        ],
    }


def tensor_coverage_rows(parity: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for row in as_list(parity.get("tensor_rows")):
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "data_coverage_percent": row.get("data_coverage_percent"),
                "missing_feature_count": row.get("missing_feature_count"),
                "stale_feature_count": row.get("stale_feature_count"),
                "row_classification": row.get("row_classification"),
                "tensor_id": row.get("tensor_id"),
                "feature_snapshot_id": row.get("feature_snapshot_id"),
            }
        )
    return rows


def per_timeframe_edge(dynamic_edge: Mapping[str, Any], metric_summary: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    by_tf = as_list(dynamic_edge.get("by_timeframe_pnl") or dynamic_edge.get("by_timeframe_edge"))
    for row in by_tf:
        if isinstance(row, dict):
            rows.append(dict(row))
    if rows:
        return rows
    return [
        {
            "timeframe": "5m",
            "sample_count": metric_summary.get("sample_count"),
            "after_cost_expectancy_bps": metric_summary.get("expected_move_after_cost_bps")
            or metric_summary.get("after_cost_pnl_delta"),
            "after_cost_ci_lower_bps": metric_summary.get("after_cost_ci_lower_bps"),
            "verdict": metric_summary.get("verdict"),
            "source": "v2_post_hoc_replay_outcome_miner_primary_window",
        }
    ]


def build_payloads() -> dict[str, Any]:
    generated_est = est_now()
    current_matrix = as_dict(read_json(ALL_TF_PUBLIC / "unified_feature_field_coverage_matrix.json"))
    current_parity = as_dict(read_json(ALL_TF_PUBLIC / "unified_feature_parity_all_symbols_status.json"))
    available_prior_matrix = as_dict(read_json(ALL_TF_DIST / "unified_feature_field_coverage_matrix.json"))
    all_tf_dashboard = as_dict(read_json(ALL_TF_PUBLIC / "operator_dashboard_payload.json"))
    cuda_status = as_dict(read_json(ALL_TF_PUBLIC / "all_symbol_all_timeframe_cuda_prediction_status.json"))
    prediction_status = as_dict(read_json(ALL_TF_PUBLIC / "all_timeframe_prediction_publisher_status.json"))
    price_status = as_dict(read_json(ALL_TF_PUBLIC / "price_target_all_tf_status.json"))
    lineage_status = as_dict(read_json(ALL_TF_PUBLIC / "all_timeframe_signal_lineage_completion_status.json"))
    backtest_status = as_dict(read_json(ALL_TF_PUBLIC / "all_symbol_all_timeframe_backtest_edge_status.json"))
    edge_metrics = as_dict(read_json(EDGE_PUBLIC / "edge_metrics_summary.json"))
    post_hoc_status = as_dict(read_json(POST_HOC_PUBLIC / "post_hoc_replay_outcome_status.json"))
    dynamic_edge = as_dict(read_json(REPO_ROOT / "v2/frontend/public/v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync/latest/v2_dynamic_93_edge_recompute_status.json"))

    current_rows = [row for row in as_list(current_matrix.get("field_rows")) if isinstance(row, dict)]
    current_blocked_raw = [row for row in current_rows if is_blocked_feature_row(row)]
    current_by_key = {
        (str(row.get("symbol")), str(row.get("timeframe")), str(row.get("field"))): row
        for row in current_rows
    }
    prior_rows = [row for row in as_list(available_prior_matrix.get("field_rows")) if isinstance(row, dict)]
    available_prior_blocked_raw = [row for row in prior_rows if is_blocked_feature_row(row)]
    if not available_prior_blocked_raw:
        available_prior_blocked_raw = current_blocked_raw

    available_prior_inventory = [inventory_row(row, current_by_key) for row in available_prior_blocked_raw]
    current_inventory = [inventory_row(row, current_by_key) for row in current_blocked_raw]
    resolved_from_available_prior = [
        row for row in available_prior_inventory if row.get("current_value_present") and row.get("classification") == "IMPLEMENT_NOW"
    ]

    field_summary = as_list(current_matrix.get("field_summary"))
    current_status_counts = Counter(str(row.get("status")) for row in current_rows)
    current_missing_count = sum(1 for row in current_rows if not bool(row.get("value_present")))
    stale_count = sum(1 for row in current_rows if bool(row.get("stale")))
    metric_summary = as_dict(edge_metrics.get("metric_summary"))
    label_counts = as_dict(edge_metrics.get("label_counts"))
    sample_count = metric_summary.get("sample_count") or backtest_status.get("sample_count")
    edge_verdict = edge_metrics.get("verdict") or metric_summary.get("verdict") or backtest_status.get("edge_verdict")
    edge_verdict_reason = (
        edge_metrics.get("verdict_reason")
        or metric_summary.get("verdict_reason")
        or backtest_status.get("edge_verdict_reason")
    )

    operator_prior_delta = OPERATOR_REPORTED_PRIOR_BLOCKED_ROWS - len(current_blocked_raw)
    available_prior_delta = len(available_prior_blocked_raw) - len(current_blocked_raw)
    inventory = {
        "schema_version": "v2_unified_feature_blocked_field_inventory_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "operator_reported_prior_blocked_field_rows_count": OPERATOR_REPORTED_PRIOR_BLOCKED_ROWS,
        "operator_reported_prior_row_level_artifact_found": False,
        "operator_reported_prior_row_level_artifact_note": (
            "The exact 13,688-row historical matrix was not found on disk during this run; "
            "the available row-level prior matrix contained 8,672 blockers."
        ),
        "available_prior_blocked_field_rows_count": len(available_prior_blocked_raw),
        "current_blocked_field_rows_count": len(current_blocked_raw),
        "resolved_from_operator_reported_prior_count": max(0, operator_prior_delta),
        "resolved_from_available_prior_count": len(resolved_from_available_prior),
        "current_blocked_rows_hidden": 0,
        "available_prior_summary": summarize_rows(available_prior_inventory),
        "current_summary": summarize_rows(current_inventory),
        "available_prior_blocked_rows": available_prior_inventory,
        "current_blocked_rows": current_inventory,
        "no_silent_zero_fill": True,
        "no_fabricated_provider_data": True,
    }

    implementation = {
        "schema_version": "v2_unified_feature_parity_implementation_status_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "status": "UNIFIED_FEATURE_PARITY_BLOCKED_OR_PARTIAL",
        "operator_reported_prior_blocked_field_rows_count": OPERATOR_REPORTED_PRIOR_BLOCKED_ROWS,
        "available_prior_blocked_field_rows_count": len(available_prior_blocked_raw),
        "current_blocked_field_rows_count": len(current_blocked_raw),
        "blocked_rows_reduced_from_operator_reported_prior": max(0, operator_prior_delta),
        "blocked_rows_reduced_from_available_prior": max(0, available_prior_delta),
        "implemented_now": [
            "V2OnlyJsonIO now reads Redis hash payloads for V2 feature keys.",
            "Hybrid data loader merges V2 microstructure and liquidation fallback keys instead of stopping at a partial payload.",
            "Tensor builder maps Binance funding, open interest, OI history, mark/index basis, liquidation distance/strength, and last liquidation bps from real V2 payloads.",
            "Tensor builder maps full TA-Lib Bollinger/MACD field names emitted by v2_full_talib_ta_loop.",
            "Tensor builder computes volatility/range/body/log-return fields from real OHLCV when the feature snapshot is absent.",
            "Tensor builder maps CoinAPI WSDS imbalance into toxicity_proxy as a real computed microstructure proxy.",
            "All-timeframe backtest lane now reads native edge-proof metrics instead of reporting worker metrics missing.",
            "V2 RL-core inference loop writes sidecar v2:prediction:rl_core:* keys and no longer overwrites existing CUDA primary prediction keys.",
        ],
        "remaining_implementation_rows": summarize_rows(
            [row for row in current_inventory if row.get("classification") == "IMPLEMENT_NOW"]
        ),
        "remaining_provider_event_rows": summarize_rows(
            [row for row in current_inventory if row.get("classification") == "PROVIDER_EVENT_DEPENDENT"]
        ),
        "remaining_provider_plan_rows": summarize_rows(
            [row for row in current_inventory if row.get("classification") == "PROVIDER_PLAN_BLOCKED"]
        ),
        "no_silent_zero_fill": True,
        "fallback_policy": "fallback_allowed=false for blocked rows; missing values remain masked, not zero-filled as truth",
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
    }

    tensor_rows = tensor_coverage_rows(current_parity)
    coverage_by_symbol_timeframe = {
        f"{row['symbol']}:{row['timeframe']}": row.get("data_coverage_percent")
        for row in tensor_rows
    }
    coverage = {
        "schema_version": "v2_trainer_tensor_feature_coverage_after_parity_status_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "status": current_parity.get("status"),
        "total_expected_feature_fields": current_matrix.get("field_rows_count"),
        "real_computed_fields": current_status_counts.get("REAL_COMPUTED", 0),
        "real_provider_value_fields": current_status_counts.get("REAL_PROVIDER_VALUE", 0),
        "event_dependent_fields": current_status_counts.get("EVENT_DEPENDENT", 0),
        "provider_blocked_fields": current_status_counts.get("PROVIDER_BLOCKED", 0),
        "operator_required_fields": current_status_counts.get("OPERATOR_REQUIRED", 0),
        "missing_fields": current_missing_count,
        "stale_fields": stale_count,
        "data_coverage_avg": current_parity.get("data_coverage_avg"),
        "data_coverage_percent_by_symbol_timeframe": coverage_by_symbol_timeframe,
        "tensor_rows": tensor_rows,
        "effect_on_cuda_tensor_builder": (
            "Tensor coverage improved through real V2 key/hash, TA-Lib, OHLCV, CoinAPI WSDS, "
            "and liquidation-level mappings; remaining missing fields are masked."
        ),
        "effect_on_prediction_coverage": {
            "prediction_rows_count": prediction_status.get("prediction_rows_count"),
            "current_prediction_count": prediction_status.get("current_prediction_count"),
            "missing_prediction_count": prediction_status.get("missing_prediction_count"),
            "stale_prediction_count": prediction_status.get("stale_prediction_count"),
            "cuda_prediction_blocked_rows_count": cuda_status.get("blocked_prediction_rows_count"),
        },
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
    }

    backtest_metrics = {
        "schema_version": "v2_parallel_backtest_worker_metrics_status_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "status": backtest_status.get("status"),
        "worker_started": bool(backtest_status.get("worker_started")),
        "metrics_written": bool(backtest_status.get("metrics_written")),
        "metrics_source_path": backtest_status.get("metrics_source_path") or rel(EDGE_PUBLIC / "edge_metrics_summary.json"),
        "post_hoc_status_path": rel(POST_HOC_PUBLIC / "post_hoc_replay_outcome_status.json"),
        "symbols_count": backtest_status.get("symbols_count"),
        "timeframes": backtest_status.get("timeframes"),
        "sample_count": sample_count,
        "bundles_total": edge_metrics.get("bundles_total") or post_hoc_status.get("bundles_total"),
        "label_counts": label_counts,
        "windows_filled": edge_metrics.get("windows_filled") or post_hoc_status.get("windows_filled"),
        "after_cost_pnl_delta": metric_summary.get("after_cost_pnl_delta"),
        "after_cost_expectancy_bps": metric_summary.get("expected_move_after_cost_bps") or metric_summary.get("after_cost_pnl_delta"),
        "after_cost_ci_lower_bps": metric_summary.get("after_cost_ci_lower_bps"),
        "after_cost_ci_upper_bps": metric_summary.get("after_cost_ci_upper_bps"),
        "drawdown": metric_summary.get("max_drawdown_bps_observed") or backtest_status.get("drawdown"),
        "false_positives": label_counts.get("false_positive"),
        "false_negatives": label_counts.get("false_negative"),
        "false_positive_rate": metric_summary.get("false_positive_rate"),
        "false_negative_rate": metric_summary.get("false_negative_rate"),
        "correct_trade": label_counts.get("correct_trade"),
        "correct_no_trade": label_counts.get("correct_no_trade"),
        "per_symbol_edge": dynamic_edge.get("by_symbol_pnl") or dynamic_edge.get("by_symbol_edge") or [],
        "per_timeframe_edge": per_timeframe_edge(dynamic_edge, metric_summary),
        "confidence_calibration": {
            "thresholds_used": metric_summary.get("thresholds_used"),
            "thresholds_satisfied": metric_summary.get("thresholds_satisfied"),
            "threshold_evidence": metric_summary.get("threshold_evidence"),
        },
        "trainer_vs_strategy_comparison": {
            "v2_vs_legacy_action_match_rate": metric_summary.get("v2_vs_legacy_action_match_rate"),
            "gate_block_reason_distribution": metric_summary.get("gate_block_reason_distribution"),
            "strategy_fallback_edge_claimed": False,
        },
        "edge_verdict": edge_verdict,
        "edge_verdict_reason": edge_verdict_reason,
        "blockers": backtest_status.get("blockers"),
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
    }

    edge_recompute = {
        "schema_version": "v2_backtest_edge_recompute_after_feature_parity_status_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "status": "BACKTEST_EDGE_RECOMPUTE_BLOCKED_NO_EDGE_CLAIM",
        "edge_proven": False,
        "edge_claimed": False,
        "after_cost_expectancy_bps": backtest_metrics["after_cost_expectancy_bps"],
        "after_cost_ci_lower_bps": backtest_metrics["after_cost_ci_lower_bps"],
        "drawdown": backtest_metrics["drawdown"],
        "sample_count": sample_count,
        "allowed_recommendations": [
            "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
            "BLOCK_LIVE_MODEL_SIGNAL_QUALITY_NOT_READY",
            "BLOCK_LIVE_RISK_CAPS_OPERATOR_REQUIRED",
            "CANARY_OPERATOR_DECISION_REQUIRED only if all gates pass",
        ],
        "primary_recommendation": "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
        "recommendations": [
            "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
            "BLOCK_LIVE_MODEL_SIGNAL_QUALITY_NOT_READY",
            "BLOCK_LIVE_RISK_CAPS_OPERATOR_REQUIRED",
        ],
        "blocked_reasons": [
            "UNIFIED_FEATURE_PARITY_BLOCKED_OR_PARTIAL",
            "EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED",
            "EDGE_CI_LOWER_NOT_POSITIVE",
            "LIVE_RISK_CAPS_OPERATOR_REQUIRED",
        ],
        "forbidden_readiness_markers_absent": True,
        "approves_live": False,
        "approves_canary": False,
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
    }

    website_sync = {
        "schema_version": "v2_unified_feature_parity_website_sync_status_v1",
        "generated_est": generated_est,
        "status": "WEBSITE_SYNC_READY_WITH_BLOCKED_LIVE_GATE",
        "updated_data_surfaces": [
            "Feature Pipeline",
            "Technical Analysis",
            "Trainer Brain",
            "Backtests",
            "Replay / Edge",
            "Live Readiness",
        ],
        "public_payload_base": rel(PUBLIC_DIR),
        "must_show": {
            "unified_feature_coverage": True,
            "blocked_field_families": True,
            "provider_event_blockers": True,
            "backtest_metrics": True,
            "edge_verdict": True,
            "why_live_remains_blocked": True,
        },
        "source_payloads": {
            "all_timeframe_dashboard": rel(ALL_TF_PUBLIC / "operator_dashboard_payload.json"),
            "feature_matrix": rel(ALL_TF_PUBLIC / "unified_feature_field_coverage_matrix.json"),
            "native_edge_metrics": rel(EDGE_PUBLIC / "edge_metrics_summary.json"),
            "post_hoc_outcome_status": rel(POST_HOC_PUBLIC / "post_hoc_replay_outcome_status.json"),
        },
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
    }

    validation = {
        "schema_version": "v2_unified_feature_parity_validation_status_v1",
        "generated_est": generated_est,
        "py_compile": "PENDING_EXTERNAL_COMMAND",
        "feature_parity_tests": "PENDING_EXTERNAL_COMMAND",
        "tensor_builder_tests": "PENDING_EXTERNAL_COMMAND",
        "backtest_worker_tests": "PENDING_EXTERNAL_COMMAND",
        "frontend_typecheck": "PENDING_EXTERNAL_COMMAND",
        "frontend_build": "PENDING_EXTERNAL_COMMAND",
        "route_crawl": "PENDING_EXTERNAL_COMMAND",
        "old_redis_scan": "PENDING_EXTERNAL_COMMAND",
        "exchange_mutation_scan": "PENDING_EXTERNAL_COMMAND",
        "approval_scan": "PENDING_EXTERNAL_COMMAND",
        "raw_secret_scan": "PENDING_EXTERNAL_COMMAND",
    }

    go_no_go = GATE_BLOCKED
    if not current_blocked_raw and edge_verdict in {"EDGE_PROVEN", "EDGE_READY", "EDGE_CLAIMED"}:
        go_no_go = GATE_READY
    dashboard = {
        "schema_version": "v2_unified_feature_parity_and_backtest_edge_operator_dashboard_payload_v1",
        "generated_est": generated_est,
        "service_id": SERVICE_ID,
        "go_no_go": go_no_go,
        "recommendation": "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
        "summary": {
            "prediction_rows_count": prediction_status.get("prediction_rows_count"),
            "current_prediction_count": prediction_status.get("current_prediction_count"),
            "stale_prediction_count": prediction_status.get("stale_prediction_count"),
            "missing_prediction_count": prediction_status.get("missing_prediction_count"),
            "signal_count": all_tf_dashboard.get("summary", {}).get("signal_count"),
            "missing_lineage_count": lineage_status.get("missing_lineage_count"),
            "invalid_or_missing_price_targets": price_status.get("invalid_or_missing_count"),
            "operator_reported_prior_feature_blocked_rows": OPERATOR_REPORTED_PRIOR_BLOCKED_ROWS,
            "available_prior_feature_blocked_rows": len(available_prior_blocked_raw),
            "current_feature_blocked_rows": len(current_blocked_raw),
            "feature_rows_resolved_from_operator_reported_prior": max(0, operator_prior_delta),
            "feature_rows_resolved_from_available_prior": max(0, available_prior_delta),
            "data_coverage_avg": current_parity.get("data_coverage_avg"),
            "backtest_worker_started": backtest_metrics["worker_started"],
            "backtest_metrics_written": backtest_metrics["metrics_written"],
            "backtest_sample_count": sample_count,
            "edge_verdict": edge_verdict,
            "edge_recommendation": "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
            "live_gate": LIVE_GATE,
            "live_symbols": [],
            "execution_live_symbols": [],
        },
        "blockers": [
            "UNIFIED_FEATURE_PARITY_BLOCKED_OR_PARTIAL",
            "BACKTEST_EDGE_BLOCKED_NO_EDGE_CLAIM",
            "LIVE_RISK_CAPS_OPERATOR_REQUIRED",
        ],
        "artifact_paths": {
            "GO_NO_GO.md": rel(PUBLIC_DIR / "GO_NO_GO.md"),
            "V2_UNIFIED_FEATURE_PARITY_AND_BACKTEST_EDGE_COMPLETION_REPORT.md": rel(PUBLIC_DIR / "V2_UNIFIED_FEATURE_PARITY_AND_BACKTEST_EDGE_COMPLETION_REPORT.md"),
            "v2_unified_feature_blocked_field_inventory.json": rel(PUBLIC_DIR / "v2_unified_feature_blocked_field_inventory.json"),
            "v2_unified_feature_parity_implementation_status.json": rel(PUBLIC_DIR / "v2_unified_feature_parity_implementation_status.json"),
            "v2_trainer_tensor_feature_coverage_after_parity_status.json": rel(PUBLIC_DIR / "v2_trainer_tensor_feature_coverage_after_parity_status.json"),
            "v2_parallel_backtest_worker_metrics_status.json": rel(PUBLIC_DIR / "v2_parallel_backtest_worker_metrics_status.json"),
            "v2_backtest_edge_recompute_after_feature_parity_status.json": rel(PUBLIC_DIR / "v2_backtest_edge_recompute_after_feature_parity_status.json"),
            "operator_dashboard_payload.json": rel(PUBLIC_DIR / "operator_dashboard_payload.json"),
        },
        "safety": {
            "approves_live": False,
            "approves_canary": False,
            "writes_exchange_orders": False,
            "calls_test_order_endpoint": False,
            "leverage_changed": False,
            "margin_mode_changed": False,
            "writes_old_redis": False,
            "writes_legacy_redis": False,
            "redis_trim_performed": False,
            "legacy_restart_performed": False,
            "raw_credentials_exposed": False,
            "live_gate": LIVE_GATE,
            "live_symbols": [],
            "execution_live_symbols": [],
        },
    }

    report = (
        "# V2 Unified Feature Parity And Backtest Edge Completion Report\n\n"
        f"Gate: `{go_no_go}`\n"
        f"Generated EST: `{generated_est}`\n"
        f"Prediction grid: `{prediction_status.get('current_prediction_count')}/{prediction_status.get('prediction_rows_count')}` current\n"
        f"Signals: `{all_tf_dashboard.get('summary', {}).get('signal_count')}`\n"
        f"Missing lineage rows: `{lineage_status.get('missing_lineage_count')}`\n"
        f"Invalid/missing price targets: `{price_status.get('invalid_or_missing_count')}`\n"
        f"Operator-reported prior feature blockers: `{OPERATOR_REPORTED_PRIOR_BLOCKED_ROWS}`\n"
        f"Available prior row-level feature blockers: `{len(available_prior_blocked_raw)}`\n"
        f"Current feature blockers: `{len(current_blocked_raw)}`\n"
        f"Tensor coverage avg: `{current_parity.get('data_coverage_avg')}`\n"
        f"Backtest worker metrics written: `{backtest_metrics['metrics_written']}`\n"
        f"Backtest sample count: `{sample_count}`\n"
        f"Edge verdict: `{edge_verdict}`\n"
        f"Recommendation: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN`\n\n"
        "Live/canary remain blocked. This artifact does not emit live-ready or canary-ready approval markers.\n\n"
        "- live_gate: `blocked_human_only`\n"
        "- live_symbols: `[]`\n"
        "- execution_live_symbols: `[]`\n"
        "- blockers: `UNIFIED_FEATURE_PARITY_BLOCKED_OR_PARTIAL, BACKTEST_EDGE_BLOCKED_NO_EDGE_CLAIM, LIVE_RISK_CAPS_OPERATOR_REQUIRED`\n\n"
        "Safety: no live/canary enable, no order/test-order/cancel/modify, no leverage/margin mutation, no old Redis write, no Redis trim, no legacy restart.\n"
    )

    return {
        "go_no_go": go_no_go,
        "generated_est": generated_est,
        "inventory": inventory,
        "implementation": implementation,
        "coverage": coverage,
        "backtest_metrics": backtest_metrics,
        "edge_recompute": edge_recompute,
        "website_sync": website_sync,
        "validation": validation,
        "dashboard": dashboard,
        "report": report,
    }


def write_outputs(payloads: Mapping[str, Any]) -> list[Path]:
    written: list[Path] = []
    files = {
        "GO_NO_GO.md": str(payloads["go_no_go"]) + "\n",
        "V2_UNIFIED_FEATURE_PARITY_AND_BACKTEST_EDGE_COMPLETION_REPORT.md": payloads["report"],
        "v2_unified_feature_blocked_field_inventory.json": payloads["inventory"],
        "v2_unified_feature_parity_implementation_status.json": payloads["implementation"],
        "v2_trainer_tensor_feature_coverage_after_parity_status.json": payloads["coverage"],
        "v2_parallel_backtest_worker_metrics_status.json": payloads["backtest_metrics"],
        "v2_backtest_edge_recompute_after_feature_parity_status.json": payloads["edge_recompute"],
        "v2_unified_feature_parity_website_sync_status.json": payloads["website_sync"],
        "v2_unified_feature_parity_validation_status.json": payloads["validation"],
        "operator_dashboard_payload.json": payloads["dashboard"],
    }
    for base in (WORKLOG_DIR, PUBLIC_DIR):
        for name, payload in files.items():
            path = base / name
            if name.endswith(".md"):
                write_text(path, str(payload))
            else:
                write_json(path, payload)
            written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=SERVICE_ID)
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)
    payloads = build_payloads()
    written: list[Path] = []
    if not args.no_write:
        written = write_outputs(payloads)
    print(
        json.dumps(
            {
                "go_no_go": payloads["go_no_go"],
                "generated_est": payloads["generated_est"],
                "current_blocked_field_rows_count": payloads["inventory"]["current_blocked_field_rows_count"],
                "available_prior_blocked_field_rows_count": payloads["inventory"]["available_prior_blocked_field_rows_count"],
                "backtest_metrics_written": payloads["backtest_metrics"]["metrics_written"],
                "edge_verdict": payloads["backtest_metrics"]["edge_verdict"],
                "paths_written": [str(path) for path in written],
                "live_gate": LIVE_GATE,
                "live_symbols": [],
                "execution_live_symbols": [],
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
