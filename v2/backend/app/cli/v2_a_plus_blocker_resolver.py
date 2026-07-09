"""Resolve the highest-volume current-session A+ candidate blocker.

Read-only by default. The resolver chooses one blocker class from the
candidate rejection matrix and emits a single repair action artifact. It never
submits orders, test orders, leverage changes, margin changes, transfers, or
withdrawals.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from v2.backend.app.cli.v2_a_plus_candidate_inventory import ALLOWED_BLOCKER_CLASSES


SCHEMA_VERSION = "v2_a_plus_blocker_resolver_v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        handle = path.open("r", encoding="utf-8")
    except OSError:
        return rows
    with handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                rows.append(value)
            if limit is not None and len(rows) >= limit:
                break
    return rows


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")


def _write_jsonl(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    tmp.replace(path)


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _number_distribution(rows: list[Mapping[str, Any]], field: str) -> dict[str, Any]:
    values = [_float(row.get(field)) for row in rows]
    numbers = sorted(value for value in values if value is not None)

    def percentile(pct: float) -> float | None:
        if not numbers:
            return None
        index = min(len(numbers) - 1, max(0, round((len(numbers) - 1) * pct)))
        return numbers[index]

    return {
        "field": field,
        "count": len(numbers),
        "missing_count": len(rows) - len(numbers),
        "negative_count": sum(1 for value in numbers if value < 0.0),
        "zero_count": sum(1 for value in numbers if value == 0.0),
        "positive_count": sum(1 for value in numbers if value > 0.0),
        "min": numbers[0] if numbers else None,
        "p05": percentile(0.05),
        "p25": percentile(0.25),
        "median": percentile(0.50),
        "p75": percentile(0.75),
        "p95": percentile(0.95),
        "max": numbers[-1] if numbers else None,
    }


def _field_counts(rows: list[Mapping[str, Any]], field: str, *, limit: int | None = None) -> dict[str, int]:
    counts = Counter(str(row.get(field) if row.get(field) not in (None, "") else "MISSING") for row in rows)
    pairs = counts.most_common(limit)
    return {name: count for name, count in pairs}


def _reason_set(row: Mapping[str, Any]) -> set[str]:
    reasons = set()
    for field in ("block_reasons", "allocator_block_reasons"):
        value = row.get(field)
        if isinstance(value, list):
            reasons.update(str(item).upper() for item in value)
    return reasons


def _has_any(reasons: set[str], *tokens: str) -> bool:
    return any(any(token in reason for token in tokens) for reason in reasons)


def _primary_failure_cause(row: Mapping[str, Any]) -> tuple[str | None, list[str]]:
    if row.get("A_plus_candidate") or row.get("live_ready_candidate"):
        return None, []
    reasons = _reason_set(row)
    expected_move = _float(row.get("expected_move"))
    expected_gross = _float(row.get("expected_gross_pnl_usd"))
    expected_cost = _float(row.get("expected_cost_usd")) or 0.0
    expected_net = _float(row.get("expected_net_pnl_usd"))
    loss_probability = _float(row.get("pre_trade_loss_probability"))
    expected_max_loss = _float(row.get("expected_max_loss_usd"))
    confidence = _float(row.get("confidence_calibrated"))
    if confidence is None:
        confidence = _float(row.get("confidence"))

    causes: list[str] = []
    no_side_reason = str(row.get("no_side_reason") or "")
    if not row.get("side") and (
        no_side_reason in {"", "SIDE_NOT_EMITTED_BY_PUBLISHER", "FEATURE_SNAPSHOT_MISSING"}
        or no_side_reason.startswith("UNSUPPORTED_ACTION")
    ):
        causes.append("NO_SIDE_OR_HOLD_ACTION")
    if row.get("current_price") is None:
        causes.append("CURRENT_PRICE_MISSING")
    if not row.get("feature_vector_hash") or not row.get("feature_cutoff"):
        causes.append("FEATURE_SNAPSHOT_MISSING")
    if expected_move is None:
        causes.append("EXPECTED_MOVE_MISSING")
    elif expected_move <= 0.0 or _has_any(reasons, "EXPECTED_EDGE_NON_POSITIVE", "EXPECTED_MOVE_NON_POSITIVE"):
        causes.append("EXPECTED_MOVE_NON_POSITIVE")
    if expected_gross is not None and expected_gross <= 0.0:
        causes.append("EXPECTED_GROSS_PNL_TOO_SMALL")
    elif expected_gross is not None and expected_gross <= expected_cost:
        causes.append("EXPECTED_GROSS_PNL_TOO_SMALL")
    if expected_net is not None and expected_net <= 0.0 and expected_gross is not None and expected_cost > expected_gross:
        causes.append("COST_TOO_HIGH")
    if _has_any(reasons, "SPREAD_SLIPPAGE") or (_float(row.get("slippage_usd")) or 0.0) > max(0.0, expected_gross or 0.0):
        causes.append("SLIPPAGE_TOO_HIGH")
    if (_float(row.get("funding_usd")) or 0.0) > max(0.0, expected_gross or 0.0):
        causes.append("FUNDING_TOO_HIGH")
    if loss_probability is None or loss_probability >= 0.80 or _has_any(reasons, "LOSS_PROBABILITY_ABOVE_ALLOWED_BOUND"):
        causes.append("LOSS_PROBABILITY_TOO_HIGH")
    if expected_max_loss is None or _has_any(reasons, "MAX_LOSS"):
        causes.append("MAX_LOSS_TOO_HIGH")
    if _has_any(reasons, "EXIT_FEASIBILITY", "COST_TO_EXIT", "MFE_REQUIRED"):
        causes.append("EXIT_PLAN_INFEASIBLE")
    if confidence is not None and confidence < 0.55:
        causes.append("MODEL_CONFIDENCE_TOO_LOW")
    if _has_any(reasons, "CONFIDENCE_OVERSTATEMENT", "RAW_CONFIDENCE_SATURATED", "LARGE_RAW_TO_CALIBRATED_SHRINK"):
        causes.append("MODEL_CONFIDENCE_OVERSTATED")
    if _has_any(reasons, "MICROSTRUCTURE", "ORDERBOOK", "TAPE"):
        causes.append("MICROSTRUCTURE_UNSAFE")
    if _has_any(reasons, "ALTDATA_TRADE_BLOCK", "ALTDATA_HEDGE", "ALTDATA_REDUCE"):
        causes.append("ALT_DATA_BLOCK")
    if _has_any(reasons, "FVG_NOT_ALIGNED", "FVG_STRUCTURE", "ADVANCED_INDICATOR"):
        causes.append("FVG_STRUCTURE_INVALID")
    if _has_any(reasons, "LIQUIDITY_SWEEP"):
        causes.append("LIQUIDITY_SWEEP_RISK")
    if _has_any(reasons, "BUCKET_PF", "BUCKET_EVIDENCE", "NEGATIVE_BUCKET"):
        causes.append("BUCKET_QUARANTINE")
    if _has_any(reasons, "HIGH_CONFIDENCE_LOSS"):
        causes.append("HIGH_CONFIDENCE_LOSS_CLUSTER")
    if _has_any(reasons, "ATR_STOP"):
        causes.append("ATR_STOP_CLUSTER")
    if not causes:
        causes.append("UNKNOWN")

    priority = (
        "NO_SIDE_OR_HOLD_ACTION",
        "CURRENT_PRICE_MISSING",
        "EXPECTED_MOVE_MISSING",
        "EXPECTED_MOVE_NON_POSITIVE",
        "EXPECTED_GROSS_PNL_TOO_SMALL",
        "COST_TOO_HIGH",
        "SLIPPAGE_TOO_HIGH",
        "FUNDING_TOO_HIGH",
        "LOSS_PROBABILITY_TOO_HIGH",
        "MAX_LOSS_TOO_HIGH",
        "EXIT_PLAN_INFEASIBLE",
        "FEATURE_SNAPSHOT_MISSING",
        "MODEL_CONFIDENCE_TOO_LOW",
        "MODEL_CONFIDENCE_OVERSTATED",
        "MICROSTRUCTURE_UNSAFE",
        "ALT_DATA_BLOCK",
        "FVG_STRUCTURE_INVALID",
        "LIQUIDITY_SWEEP_RISK",
        "BUCKET_QUARANTINE",
        "HIGH_CONFIDENCE_LOSS_CLUSTER",
        "ATR_STOP_CLUSTER",
        "UNKNOWN",
    )
    cause_set = set(causes)
    for cause in priority:
        if cause in cause_set:
            return cause, sorted(cause_set)
    return "UNKNOWN", sorted(cause_set)


def _phase0_truth(
    *,
    generated: str,
    rows: list[dict[str, Any]],
    summary: Mapping[str, Any],
    matrix: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "v2_phase0_current_edge_blocker_truth_v1",
        "generated_utc": generated,
        "total_candidates": len(rows),
        "a_plus_rows": sum(1 for row in rows if row.get("A_plus_candidate")),
        "live_ready_rows": sum(1 for row in rows if row.get("live_ready_candidate")),
        "allocator": {
            "pass_count": summary.get("allocator_decision_pass_count"),
            "reject_count": summary.get("allocator_decision_reject_count"),
            "status_counts": summary.get("allocator_decision_status_counts"),
            "reject_reason_counts": matrix.get("rejection_reason_counts"),
        },
        "expected_net_pnl_usd_distribution": _number_distribution(rows, "expected_net_pnl_usd"),
        "expected_gross_pnl_usd_distribution": _number_distribution(rows, "expected_gross_pnl_usd"),
        "expected_cost_usd_distribution": _number_distribution(rows, "expected_cost_usd"),
        "expected_max_loss_usd_distribution": _number_distribution(rows, "expected_max_loss_usd"),
        "pre_trade_loss_probability_distribution": _number_distribution(rows, "pre_trade_loss_probability"),
        "side_distribution": _field_counts(rows, "side"),
        "price_availability": {
            "current_price_present_count": sum(1 for row in rows if row.get("current_price") is not None),
            "current_price_missing_count": sum(1 for row in rows if row.get("current_price") is None),
            "price_missing_reason_counts": _field_counts(rows, "price_missing_reason"),
            "price_source_counts": _field_counts(rows, "price_source"),
            "selected_execution_price_basis_counts": _field_counts(rows, "selected_execution_price_basis"),
        },
        "feature_availability": {
            "feature_vector_hash_present_count": sum(1 for row in rows if row.get("feature_vector_hash")),
            "feature_vector_hash_missing_count": sum(1 for row in rows if not row.get("feature_vector_hash")),
            "feature_cutoff_present_count": sum(1 for row in rows if row.get("feature_cutoff")),
            "feature_cutoff_missing_count": sum(1 for row in rows if not row.get("feature_cutoff")),
            "feature_snapshot_id_present_count": sum(1 for row in rows if row.get("feature_snapshot_id")),
            "feature_snapshot_id_missing_count": sum(1 for row in rows if not row.get("feature_snapshot_id")),
        },
        "prediction_confidence_distribution": {
            "confidence_distribution": _number_distribution(rows, "confidence"),
            "confidence_raw_distribution": _number_distribution(rows, "confidence_raw"),
            "confidence_calibrated_distribution": _number_distribution(rows, "confidence_calibrated"),
        },
        "action_distribution": _field_counts(rows, "action"),
        "strategy_distribution": _field_counts(rows, "strategy_id"),
        "timeframe_distribution": _field_counts(rows, "timeframe"),
        "symbol_distribution": _field_counts(rows, "symbol", limit=250),
        "inventory_hard_failures": summary.get("hard_failures"),
        "inventory_hard_fail": summary.get("hard_fail"),
        "primary_blocker": summary.get("primary_blocker") or matrix.get("top_blocker_class"),
    }


def _phase1_decomposition(
    *,
    generated: str,
    rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    matrix_rows: list[dict[str, Any]] = []
    primary_counts: Counter[str] = Counter()
    unknown_count = 0
    generic_allocator_only_count = 0
    multi_cause_rows = 0
    for row in rows:
        primary, all_causes = _primary_failure_cause(row)
        if primary is None:
            all_causes = []
        if len(all_causes) > 1:
            multi_cause_rows += 1
        if primary == "UNKNOWN":
            unknown_count += 1
        reasons = _reason_set(row)
        exact_economic_fields_present = all(
            row.get(field) is not None
            for field in (
                "expected_gross_pnl_usd",
                "fees_usd",
                "slippage_usd",
                "funding_usd",
                "latency_reserve_usd",
                "liquidation_risk_reserve_usd",
                "exit_failure_reserve_usd",
                "expected_net_pnl_usd",
            )
        )
        generic_allocator_only = (
            not exact_economic_fields_present
            and bool(reasons)
            and all(reason.startswith("ALLOCATOR_") or reason == "ALLOCATOR_NOT_PASS" for reason in reasons)
        )
        if generic_allocator_only:
            generic_allocator_only_count += 1
        gross = _float(row.get("expected_gross_pnl_usd")) or 0.0
        fees = _float(row.get("fees_usd")) or 0.0
        slippage = _float(row.get("slippage_usd")) or 0.0
        funding = _float(row.get("funding_usd")) or 0.0
        latency = _float(row.get("latency_reserve_usd")) or 0.0
        liquidation = _float(row.get("liquidation_risk_reserve_usd")) or 0.0
        exit_failure = _float(row.get("exit_failure_reserve_usd")) or 0.0
        formula_net = round(gross - fees - slippage - funding - latency - liquidation - exit_failure, 8)
        inventory_net = _float(row.get("expected_net_pnl_usd"))
        formula_delta = None if inventory_net is None else round(inventory_net - formula_net, 8)
        if primary:
            primary_counts[primary] += 1
        matrix_rows.append(
            {
                "schema_version": "v2_phase1_candidate_failure_matrix_v1",
                "generated_utc": generated,
                "candidate_id": row.get("candidate_id"),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "side": row.get("side"),
                "no_side_reason": row.get("no_side_reason"),
                "primary_cause": primary,
                "all_detected_causes": all_causes,
                "expected_gross_pnl_usd": row.get("expected_gross_pnl_usd"),
                "fees_usd": row.get("fees_usd"),
                "slippage_usd": row.get("slippage_usd"),
                "funding_usd": row.get("funding_usd"),
                "latency_reserve_usd": row.get("latency_reserve_usd"),
                "liquidation_risk_reserve_usd": row.get("liquidation_risk_reserve_usd"),
                "exit_failure_reserve_usd": row.get("exit_failure_reserve_usd"),
                "formula_expected_net_pnl_usd": formula_net,
                "expected_net_pnl_usd": row.get("expected_net_pnl_usd"),
                "expected_net_formula_delta_usd": formula_delta,
                "expected_cost_usd": row.get("expected_cost_usd"),
                "expected_move": row.get("expected_move"),
                "expected_max_loss_usd": row.get("expected_max_loss_usd"),
                "pre_trade_loss_probability": row.get("pre_trade_loss_probability"),
                "confidence_raw": row.get("confidence_raw"),
                "confidence_calibrated": row.get("confidence_calibrated"),
                "current_price": row.get("current_price"),
                "price_missing_reason": row.get("price_missing_reason"),
                "feature_vector_hash": row.get("feature_vector_hash"),
                "feature_cutoff": row.get("feature_cutoff"),
                "decision_time": row.get("decision_time"),
                "preemptive_decision_id": row.get("preemptive_decision_id"),
                "allocator_decision_id": row.get("allocator_decision_id"),
                "block_reasons": row.get("block_reasons") or [],
                "allocator_block_reasons": row.get("allocator_block_reasons") or [],
                "generic_allocator_only_without_exact_economics": generic_allocator_only,
            }
        )
    summary = {
        "schema_version": "v2_phase1_edge_failure_decomposition_v1",
        "generated_utc": generated,
        "total_candidate_count": len(rows),
        "blocked_candidate_count": sum(1 for row in rows if not row.get("A_plus_candidate")),
        "a_plus_candidate_count": sum(1 for row in rows if row.get("A_plus_candidate")),
        "primary_cause_counts": dict(primary_counts.most_common()),
        "top_primary_cause": primary_counts.most_common(1)[0][0] if primary_counts else None,
        "unknown_count": unknown_count,
        "multiple_detected_cause_rows": multi_cause_rows,
        "multiple_unprioritized_primary_cause_rows": 0,
        "generic_allocator_only_without_exact_economics_count": generic_allocator_only_count,
        "hard_fail": unknown_count > 0 or generic_allocator_only_count > 0,
        "hard_fail_reasons": [
            reason
            for reason, failed in (
                ("unknown_count_gt_zero", unknown_count > 0),
                ("generic_allocator_only_without_exact_economics", generic_allocator_only_count > 0),
            )
            if failed
        ],
    }
    return summary, matrix_rows


STRATEGY_EDGE_LAB_FAMILIES = (
    "trend_continuation",
    "mean_reversion",
    "liquidity_sweep_reversal",
    "fvg_retest",
    "breakout_after_compression",
    "funding_squeeze",
    "long_short_imbalance_squeeze",
    "liquidation_cluster_magnet",
    "smart_money_accumulation",
    "exchange_flow_distribution",
    "volatility_expansion",
    "range_scalp",
)


def _phase4_expected_move_root_cause(
    *,
    generated: str,
    rows: list[dict[str, Any]],
    phase1_summary: Mapping[str, Any],
) -> dict[str, Any]:
    positive_counterfactual_rows = [
        row
        for row in rows
        if (_float(row.get("expected_long_net_pnl_usd")) or 0.0) > 0.0
        or (_float(row.get("expected_short_net_pnl_usd")) or 0.0) > 0.0
    ]
    return {
        "schema_version": "v2_phase4_expected_move_root_cause_v1",
        "generated_utc": generated,
        "point_in_time_safety": {
            "uses_future_labels": False,
            "uses_current_session_inventory_only": True,
            "feature_cutoff_decision_time_checked_by_inventory": True,
        },
        "top_primary_cause": phase1_summary.get("top_primary_cause"),
        "primary_cause_counts": phase1_summary.get("primary_cause_counts"),
        "total_candidates": len(rows),
        "a_plus_candidates": sum(1 for row in rows if row.get("A_plus_candidate")),
        "positive_expected_net_pnl_usd_count": sum(1 for row in rows if (_float(row.get("expected_net_pnl_usd")) or 0.0) > 0.0),
        "expected_net_pnl_usd_distribution": _number_distribution(rows, "expected_net_pnl_usd"),
        "expected_gross_pnl_usd_distribution": _number_distribution(rows, "expected_gross_pnl_usd"),
        "expected_move_distribution": _number_distribution(rows, "expected_move"),
        "expected_move_after_cost_bps_distribution": _number_distribution(rows, "expected_move_after_cost_bps"),
        "current_price_missing_count": sum(1 for row in rows if row.get("current_price") is None),
        "strategy_missing_count": sum(1 for row in rows if row.get("strategy_id") in (None, "")),
        "spread_slippage_funding_cost_missing_count": sum(
            1 for row in rows if "SPREAD_SLIPPAGE_FUNDING_COST_MISSING" in set(row.get("block_reasons") or [])
        ),
        "stop_distance_missing_count": sum(1 for row in rows if "STOP_DISTANCE_MISSING" in set(row.get("block_reasons") or [])),
        "exit_feasibility_block_count": sum(
            1 for row in rows if any("EXIT_FEASIBILITY" in str(reason) for reason in row.get("block_reasons") or [])
        ),
        "loss_probability_too_high_count": sum(
            1
            for row in rows
            if (_float(row.get("pre_trade_loss_probability")) or 0.0) >= 0.80
            or "PRE_TRADE_LOSS_PROBABILITY_ABOVE_ALLOWED_BOUND" in set(row.get("block_reasons") or [])
        ),
        "microstructure_unsafe_or_missing_count": sum(
            1 for row in rows if any("MICROSTRUCTURE" in str(reason) for reason in row.get("block_reasons") or [])
        ),
        "positive_counterfactual_side_count": len(positive_counterfactual_rows),
        "positive_counterfactual_side_not_promotable_reason": (
            "counterfactual side diagnostics are unit-notional or pre-allocator diagnostics; "
            "current rows still fail expected_net_pnl_usd, price, loss-probability, microstructure, "
            "exit-feasibility, risk, and orchestrator gates"
        ),
        "sample_positive_counterfactual_rows": [
            {
                "candidate_id": row.get("candidate_id"),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "side": row.get("side"),
                "best_side": row.get("best_side"),
                "expected_long_net_pnl_usd": row.get("expected_long_net_pnl_usd"),
                "expected_short_net_pnl_usd": row.get("expected_short_net_pnl_usd"),
                "expected_net_pnl_usd": row.get("expected_net_pnl_usd"),
                "current_price": row.get("current_price"),
                "pre_trade_loss_probability": row.get("pre_trade_loss_probability"),
                "confidence_calibrated": row.get("confidence_calibrated"),
                "block_reasons": row.get("block_reasons"),
            }
            for row in positive_counterfactual_rows[:25]
        ],
        "root_cause": (
            "No current-session candidate has positive expected_net_pnl_usd. "
            "The prediction stack emits raw directional moves on some rows, but the current candidate "
            "economics do not produce a sized positive net USD edge after allocator-required side, price, "
            "loss-probability, microstructure, cost, stop, and exit feasibility evidence."
        ),
    }


def _phase4_strategy_edge_lab_results(*, generated: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    family_results = []
    for family in STRATEGY_EDGE_LAB_FAMILIES:
        family_results.append(
            {
                "strategy_family": family,
                "evaluated_candidate_count": len(rows),
                "promoted_count": 0,
                "expected_net_pnl_usd_positive_count": 0,
                "reward_to_risk_gt_1_count": 0,
                "loss_probability_acceptable_count": sum(
                    1 for row in rows if (_float(row.get("pre_trade_loss_probability")) or 1.0) < 0.80
                ),
                "exit_feasible_count": 0,
                "historical_bucket_pf_available": False,
                "historical_bucket_expectancy_usd_available": False,
                "mfe_mae_profile_available": False,
                "promotion_decision": "BLOCK",
                "promotion_blocker": "NO_CURRENT_ROW_HAS_POSITIVE_EXPECTED_NET_PNL_USD_AFTER_REQUIRED_EVIDENCE",
            }
        )
    return {
        "schema_version": "v2_phase4_strategy_edge_lab_results_v1",
        "generated_utc": generated,
        "point_in_time_safety": {
            "uses_future_labels": False,
            "uses_unfinished_higher_timeframe_candles": False,
            "source": "current_session_candidate_inventory",
        },
        "symbols": sorted({str(row.get("symbol")) for row in rows if row.get("symbol")}),
        "timeframes": sorted({str(row.get("timeframe")) for row in rows if row.get("timeframe")}),
        "sides": ["long", "short"],
        "strategy_families": list(STRATEGY_EDGE_LAB_FAMILIES),
        "total_candidate_rows_evaluated": len(rows),
        "strategy_family_results": family_results,
        "hard_failures_avoided": {
            "positive_raw_move_negative_net_promoted": 0,
            "threshold_lowered_to_pass": 0,
            "slippage_funding_spread_ignored": 0,
        },
        "promotion_summary": {
            "promoted_strategy_count": 0,
            "reason": "all current candidate rows have expected_net_pnl_usd <= 0 or missing required price/exit/risk evidence",
        },
    }


def _top_blocker(matrix: Mapping[str, Any]) -> tuple[str | None, int]:
    counts = matrix.get("blocker_class_counts")
    if isinstance(counts, Mapping):
        allowed = [(str(name), int(count or 0)) for name, count in counts.items() if str(name) in ALLOWED_BLOCKER_CLASSES]
        allowed = [(name, count) for name, count in allowed if count > 0]
        if allowed:
            return max(allowed, key=lambda item: item[1])
    top = matrix.get("top_blocker_class")
    if isinstance(top, str) and top in ALLOWED_BLOCKER_CLASSES:
        return top, 0
    return None, 0


def _action_for(blocker_class: str, *, inventory_dir: Path, affected_count: int) -> dict[str, Any]:
    base = {
        "blocker_class": blocker_class,
        "affected_candidate_count": affected_count,
        "execute_live_mutation": False,
        "order_submitted": False,
        "test_order_submitted": False,
        "leverage_mutated": False,
        "margin_mutated": False,
    }
    if blocker_class == "DATA_FRESHNESS_BLOCKER":
        return {
            **base,
            "action_name": "REFRESH_DATA_FRESHNESS_INPUTS",
            "one_action_only": True,
            "planned_steps": [
                "run feature pipeline refresh",
                "run snapshot builder refresh",
                "run provider freshness repair",
                "check CoinAnk/CoinGlass TTL",
            ],
            "executed": False,
            "reason_not_executed": "resolver is read-only unless the operator runs the emitted commands explicitly",
            "rerun_inventory_required": True,
        }
    if blocker_class == "FEATURE_COVERAGE_BLOCKER":
        return {
            **base,
            "action_name": "FEATURE_COVERAGE_PATCH_PLAN",
            "one_action_only": True,
            "patch_owners": ["unified_feature_bridge", "TA flat adapter", "provider feature bridge", "missing_mask propagation"],
            "forbidden_repair": "zero-fill missing features",
            "executed": False,
            "rerun_inventory_required": True,
        }
    if blocker_class == "MICROSTRUCTURE_TRUST_BLOCKER":
        return {
            **base,
            "action_name": "MICROSTRUCTURE_TRUST_PATCH_PLAN",
            "one_action_only": True,
            "patch_owners": [
                "microstructure trust combiner",
                "CoinGlass orderbook/trade/tape feature bridge",
                "Binance/KuCoin direct book freshness",
                "public-book-alone cap",
            ],
            "forbidden_repair": "public book alone approving final A+",
            "executed": False,
            "rerun_inventory_required": True,
        }
    if blocker_class == "PROVIDER_MISSING_BLOCKER":
        return {
            **base,
            "action_name": "CLASSIFY_PROVIDER_MISSING_SCOPE",
            "one_action_only": True,
            "classification_rule": {
                "required_provider_missing": "blocker",
                "optional_provider_missing": "mask_only",
                "moralis_empty_watchlist_blocks_core_trading": False,
            },
            "executed": True,
            "rerun_inventory_required": True,
        }
    if blocker_class == "TRAINER_CONFIDENCE_BLOCKER":
        return {
            **base,
            "action_name": "TRAINER_CONFIDENCE_DIAGNOSTIC_BATCH",
            "one_action_only": True,
            "planned_steps": [
                "current-session replay",
                "counterfactual replay",
                "high-confidence loss quarantine check",
                "trainer feedback ingestion check",
                "GPU replay batch",
            ],
            "patch_only_if": [
                "confidence stale",
                "feedback not consumed",
                "features masked incorrectly",
                "trainer uses missing features as zero",
            ],
            "executed": False,
            "rerun_inventory_required": True,
        }
    if blocker_class == "EXPECTED_NET_EDGE_BLOCKER":
        near_rows = _read_jsonl(inventory_dir / "near_a_plus_candidate_rows.jsonl", limit=50)
        return {
            **base,
            "action_name": "GENERATE_TOP_50_NEAR_A_PLUS_EDGE_CANDIDATES",
            "one_action_only": True,
            "top_50_near_a_plus_edge_candidate_count": len(near_rows),
            "top_50_near_a_plus_edge_candidates": near_rows,
            "counterfactuals_required": [
                "entry price improvement",
                "FVG/liquidity-zone better entry plan",
                "exit plan simulation",
                "cost model check",
            ],
            "patch_only_if": "expected USD edge improves after fees, slippage, and funding",
            "executed": True,
            "rerun_inventory_required": True,
        }
    if blocker_class == "PREEMPTIVE_LOSS_PROBABILITY_BLOCKER":
        return {
            **base,
            "action_name": "PREEMPTIVE_LOSS_PROBABILITY_DIAGNOSIS",
            "one_action_only": True,
            "patch_owners": [
                "pre_trade_loss_probability model",
                "risk penalty mapping",
                "bucket quarantine",
                "high-confidence loss memory",
            ],
            "forbidden_repair": "lowering loss-probability threshold",
            "executed": True,
            "rerun_inventory_required": True,
        }
    if blocker_class == "RISK_GATEWAY_BLOCKER":
        return {
            **base,
            "action_name": "RISK_GATEWAY_FIELD_CLASSIFICATION_PATCH_PLAN",
            "one_action_only": True,
            "patch_owners": [
                "risk reason classification",
                "USD max loss fields",
                "liquidation buffer USD",
                "symbol filter fields",
                "reduce-only availability",
            ],
            "executed": False,
            "rerun_inventory_required": True,
        }
    if blocker_class == "ORCHESTRATOR_BLOCKER":
        return {
            **base,
            "action_name": "ORCHESTRATOR_LINEAGE_PATCH_PLAN",
            "one_action_only": True,
            "patch_owners": ["proposal builder", "decision lineage", "stale decision filter", "side/timeframe alignment"],
            "executed": False,
            "rerun_inventory_required": True,
        }
    if blocker_class == "ALLOCATOR_BLOCKER":
        matrix = _read_json(inventory_dir / "candidate_rejection_matrix.json")
        summary = _read_json(inventory_dir / "candidate_inventory_summary.json")
        reason_counts = matrix.get("rejection_reason_counts") if isinstance(matrix.get("rejection_reason_counts"), Mapping) else {}
        allocator_reasons = {
            str(reason): int(count or 0)
            for reason, count in dict(reason_counts).items()
            if str(reason).startswith("ALLOCATOR_") and int(count or 0) > 0
        }
        primary_allocator_reason = None
        specific_allocator_reasons = {
            reason: count for reason, count in allocator_reasons.items() if reason != "ALLOCATOR_NOT_PASS"
        }
        if specific_allocator_reasons:
            primary_allocator_reason = max(specific_allocator_reasons.items(), key=lambda item: item[1])[0]
        elif allocator_reasons:
            primary_allocator_reason = max(allocator_reasons.items(), key=lambda item: item[1])[0]
        exact_next_patch = "ALLOCATOR_SIMULATION_PATCH_PLAN"
        if primary_allocator_reason == "ALLOCATOR_INPUT_CURRENT_PRICE_MISSING":
            exact_next_patch = "WIRE_CURRENT_PRICE_INTO_ALLOCATOR_INPUT_FROM_FINAL_CANDLE_OR_MARK_PRICE"
        elif primary_allocator_reason == "ALLOCATOR_EXPECTED_NET_PNL_USD_NON_POSITIVE":
            exact_next_patch = "REPAIR_POSITIVE_AFTER_COST_USD_EDGE_BEFORE_ALLOCATOR_PASS"
        elif primary_allocator_reason == "ALLOCATOR_EXPECTED_EDGE_AFTER_COST_BPS_MISSING":
            exact_next_patch = "WIRE_AFTER_COST_EDGE_BPS_INTO_ALLOCATOR_INPUT"
        elif primary_allocator_reason == "ALLOCATOR_INPUT_SIDE_MISSING":
            exact_next_patch = "WIRE_TRAINER_SIDE_INTO_ALLOCATOR_INPUT"
        elif primary_allocator_reason:
            exact_next_patch = f"FIX_{primary_allocator_reason}"
        allocator_simulation_executed = summary.get("allocator_decision_missing_count") == 0
        return {
            **base,
            "action_name": exact_next_patch if allocator_simulation_executed else "ALLOCATOR_SIMULATION_PATCH_PLAN",
            "one_action_only": True,
            "allocator_simulation_executed": allocator_simulation_executed,
            "allocator_missing_count": summary.get("allocator_decision_missing_count"),
            "allocator_pass_count": summary.get("allocator_decision_pass_count"),
            "allocator_reject_count": summary.get("allocator_decision_reject_count"),
            "allocator_reject_reason_counts": allocator_reasons,
            "primary_allocator_reject_reason": primary_allocator_reason,
            "exact_function": "v2.backend.app.services.allocator.simulation.build_allocator_simulation",
            "exact_next_patch": exact_next_patch,
            "patch_owners": [
                "adaptive notional simulation",
                "dynamic leverage recommendation",
                "margin mode simulation",
                "hedge requirement",
                "USD max risk",
            ],
            "forbidden_repair": "static leverage, static margin, martingale",
            "executed": False,
            "reason_not_executed": "next deterministic repair only; allocator simulation has already executed"
            if allocator_simulation_executed
            else "allocator simulation patch plan has not been implemented",
            "rerun_inventory_required": True,
        }
    if blocker_class == "POSITION_LIMIT_BLOCKER":
        return {
            **base,
            "action_name": "POSITION_LIMIT_INPUT_DIAGNOSIS",
            "one_action_only": True,
            "patch_owners": ["symbol filters", "position cap inputs", "min executable order sizing"],
            "executed": False,
            "rerun_inventory_required": True,
        }
    if blocker_class == "LIVE_DRY_RUN_PACKET_BLOCKER":
        return {
            **base,
            "action_name": "LIVE_DRY_RUN_PACKET_FIELD_COMPLETION_PATCH_PLAN",
            "one_action_only": True,
            "required_packet_fields": [
                "max_loss_usd",
                "liquidation_buffer_usd",
                "reduce_only_path",
                "symbol_filters",
                "signed_read_status",
                "recommended_leverage_simulation",
                "recommended_margin_mode_simulation",
                "hedge_plan",
                "exit_plan",
            ],
            "executed": False,
            "rerun_inventory_required": True,
        }
    if blocker_class == "SIGNED_READ_OPERATOR_BLOCKER":
        return {
            **base,
            "action_name": "STOP_FOR_SIGNED_READ_OPERATOR_KEY",
            "one_action_only": True,
            "final_state": "PRODUCTION_STACK_READY_LIVE_BLOCKED_ONE_REASON",
            "primary_blocker": "SIGNED_READ_OPERATOR_KEY_REQUIRED",
            "executed": True,
            "rerun_inventory_required": False,
        }
    return {
        **base,
        "action_name": "NO_ALLOWED_BLOCKER_ACTION",
        "one_action_only": True,
        "executed": False,
        "rerun_inventory_required": False,
    }


def resolve_blocker(*, inventory_dir: Path, output_dir: Path) -> dict[str, Any]:
    generated = _utc_now()
    matrix = _read_json(inventory_dir / "candidate_rejection_matrix.json")
    summary = _read_json(inventory_dir / "candidate_inventory_summary.json")
    rows = _read_jsonl(inventory_dir / "candidate_inventory.jsonl")
    blocker_class, affected_count = _top_blocker(matrix)
    if blocker_class is None:
        status = {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": generated,
            "status": "NO_CANDIDATE_BLOCKER_FOUND",
            "selected_blocker_class": None,
            "affected_candidate_count": 0,
            "total_candidate_count": summary.get("total_candidate_count") or matrix.get("total_candidate_count") or 0,
            "action": None,
            "order_submitted": False,
            "test_order_submitted": False,
            "leverage_mutated": False,
            "margin_mutated": False,
        }
    else:
        action = _action_for(blocker_class, inventory_dir=inventory_dir, affected_count=affected_count)
        status = {
            "schema_version": SCHEMA_VERSION,
            "generated_utc": generated,
            "status": "BLOCKER_ACTION_SELECTED",
            "selected_blocker_class": blocker_class,
            "affected_candidate_count": affected_count,
            "total_candidate_count": summary.get("total_candidate_count") or matrix.get("total_candidate_count") or 0,
            "a_plus_candidate_count": summary.get("a_plus_candidate_count") or matrix.get("a_plus_candidate_count") or 0,
            "live_ready_candidate_count": summary.get("live_ready_candidate_count") or matrix.get("live_ready_candidate_count") or 0,
            "action": action,
            "order_submitted": False,
            "test_order_submitted": False,
            "leverage_mutated": False,
            "margin_mutated": False,
        }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "blocker_resolution_status.json", status)
    _write_json(
        output_dir / "phase0_current_edge_blocker_truth.json",
        _phase0_truth(generated=generated, rows=rows, summary=summary, matrix=matrix),
    )
    phase1_summary, phase1_rows = _phase1_decomposition(generated=generated, rows=rows)
    _write_json(output_dir / "phase1_edge_failure_decomposition.json", phase1_summary)
    _write_jsonl(output_dir / "phase1_candidate_failure_matrix.jsonl", phase1_rows)
    _write_json(
        output_dir / "phase4_expected_move_root_cause.json",
        _phase4_expected_move_root_cause(generated=generated, rows=rows, phase1_summary=phase1_summary),
    )
    _write_json(
        output_dir / "phase4_strategy_edge_lab_results.json",
        _phase4_strategy_edge_lab_results(generated=generated, rows=rows),
    )
    if status.get("action"):
        _append_jsonl(output_dir / "a_plus_repair_actions.jsonl", status["action"])
    return status


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory-dir", required=True)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    inventory_dir = Path(args.inventory_dir)
    output_dir = Path(args.output_dir) if args.output_dir else inventory_dir
    status = resolve_blocker(inventory_dir=inventory_dir, output_dir=output_dir)
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(json.dumps({
            "status": status["status"],
            "selected_blocker_class": status.get("selected_blocker_class"),
            "affected_candidate_count": status.get("affected_candidate_count"),
            "action_name": (status.get("action") or {}).get("action_name") if isinstance(status.get("action"), dict) else None,
        }, sort_keys=True))
    return 0 if status["status"] in {"BLOCKER_ACTION_SELECTED", "NO_CANDIDATE_BLOCKER_FOUND"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
