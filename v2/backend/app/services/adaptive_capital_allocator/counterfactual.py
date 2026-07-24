from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class CounterfactualRiskEnvelope:
    starting_equity_usd: float = 10_000.0
    max_drawdown_pct: float = 0.20
    max_expected_shortfall_pct: float = 0.03
    max_liquidation_probability: float = 0.001
    max_portfolio_exposure_pct: float = 0.60
    min_liquidation_buffer_bps: float = 500.0
    max_effective_leverage: float = 3.0


DEFAULT_NOTIONAL_MULTIPLIERS = (0.25, 0.5, 1.0, 2.0, 3.0, 5.0)  # up to 5x notional for counterfactual
DEFAULT_LEVERAGE_VALUES = (1.0, 2.0, 5.0, 10.0, 20.0)  # explore up to 20x leverage
DEFAULT_STOP_MULTIPLIERS = (0.5, 0.75, 1.0, 1.5, 2.0)  # wider stops for volatility
DEFAULT_TAKE_PROFIT_PLANS = ("none", "one_r", "two_r", "three_r")  # more profit targets
DEFAULT_MARGIN_MODES = ("isolated", "cross")
DEFAULT_HEDGE_FLAGS = (False, True)
COUNTERFACTUAL_HEDGE_COST_BPS = 3.0
COUNTERFACTUAL_HEDGE_TAIL_LOSS_REDUCTION_FACTOR = 0.75
REQUIRED_COUNTERFACTUAL_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
A_GRADE_CONFIDENCE_THRESHOLD = 0.75
A_GRADE_MIN_AFTER_COST_EDGE_BPS = 0.0
REQUIRED_SCENARIOS = (
    "flash_crash",
    "exchange_outage",
    "spread_explosion",
    "slippage_spike",
    "funding_inversion",
    "squeeze",
    "liquidation_cascade",
)


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


def _side(row: dict[str, Any]) -> str:
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


def _directional_after_cost_edge_bps(row: dict[str, Any]) -> float | None:
    raw_edge = _coerce_float(
        _first_present(row.get("expected_move_after_cost_bps"), row.get("expected_net_edge_bps"))
    )
    if raw_edge is None:
        return None
    if _side(row) == "short" and raw_edge < 0.0:
        return abs(raw_edge)
    return raw_edge


def _nested_mapping(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = row.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _allocation_mapping(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("adaptive_allocation")
    return value if isinstance(value, dict) else {}


def _row_value(row: dict[str, Any], field: str) -> Any:
    allocation = _allocation_mapping(row)
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
        entry_price = _coerce_float(_first_present(row.get("entry_price"), row.get("fill_price"), row.get("price")))
        quantity = _coerce_float(_first_present(row.get("quantity"), row.get("target_quantity"), allocation.get("target_quantity")))
        if entry_price is not None and quantity is not None:
            return entry_price * quantity
        return None
    return _first_present(row.get(field), allocation.get(field))


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _declared_time(
    row: dict[str, Any],
    *,
    label: str,
    keys: tuple[str, ...],
) -> tuple[datetime | None, str | None]:
    for key in keys:
        if key not in row:
            continue
        parsed = _parse_time(row.get(key))
        if parsed is None:
            return None, f"INVALID_{label}"
        return parsed, None
    return None, f"MISSING_{label}"


def _declared_decision_time(
    row: dict[str, Any],
) -> tuple[datetime | None, str | None]:
    declared: list[datetime] = []
    for key in ("decision_time", "entry_feature_decision_time"):
        if key not in row:
            continue
        parsed = _parse_time(row.get(key))
        if parsed is None:
            return None, "INVALID_DECISION_TIME"
        declared.append(parsed)
    if not declared:
        return None, "MISSING_DECISION_TIME"
    if any(candidate != declared[0] for candidate in declared[1:]):
        return None, "DECISION_TIME_ALIAS_CONFLICT"
    return declared[0], None


def _temporal_status(row: dict[str, Any]) -> tuple[bool, list[str]]:
    decision, decision_error = _declared_decision_time(row)
    reasons: list[str] = []
    if decision_error is not None:
        reasons.append(decision_error)

    available, available_error = _declared_time(
        row,
        label="AVAILABLE_AT",
        keys=("entry_feature_available_at", "available_at"),
    )
    generated, generated_error = _declared_time(
        row,
        label="GENERATED_AT",
        keys=("entry_feature_generated_at", "generated_at"),
    )
    cutoff, cutoff_error = _declared_time(
        row,
        label="FEATURE_CUTOFF",
        keys=("entry_feature_cutoff", "feature_cutoff"),
    )
    for error in (available_error, generated_error, cutoff_error):
        if error is not None:
            reasons.append(error)

    if decision is not None:
        for label, parsed in (
            ("AVAILABLE_AT", available),
            ("GENERATED_AT", generated),
            ("FEATURE_CUTOFF", cutoff),
        ):
            if parsed is not None and parsed > decision:
                reasons.append(f"{label}_AFTER_DECISION_TIME")
    if cutoff is not None and available is not None and cutoff > available:
        reasons.append("FEATURE_CUTOFF_AFTER_AVAILABLE_AT")
    if cutoff is not None and generated is not None and cutoff > generated:
        reasons.append("FEATURE_CUTOFF_AFTER_GENERATED_AT")
    if generated is not None and available is not None and generated > available:
        reasons.append("GENERATED_AT_AFTER_AVAILABLE_AT")

    if "entry_feature_candle_closed_confirmed" not in row:
        reasons.append("MISSING_CANDLE_FINALITY")
    elif row.get("entry_feature_candle_closed_confirmed") is False:
        reasons.append("UNFINISHED_CANDLE")
    elif row.get("entry_feature_candle_closed_confirmed") is not True:
        reasons.append("INVALID_CANDLE_FINALITY")
    return not reasons, reasons


def _is_a_grade(
    row: dict[str, Any],
    *,
    confidence_threshold: float = A_GRADE_CONFIDENCE_THRESHOLD,
    after_cost_edge_bps_min_exclusive: float = A_GRADE_MIN_AFTER_COST_EDGE_BPS,
) -> bool:
    confidence = _coerce_float(_first_present(row.get("confidence_calibrated"), row.get("confidence"))) or 0.0
    edge = _directional_after_cost_edge_bps(row) or 0.0
    decision = str(row.get("allocator_decision") or row.get("decision") or "")
    side = _side(row)
    return (
        side in {"long", "short"}
        and confidence >= confidence_threshold
        and edge > after_cost_edge_bps_min_exclusive
        and not decision.startswith("BLOCK_")
    )


def _not_a_grade_reasons(
    row: dict[str, Any],
    *,
    confidence_threshold: float = A_GRADE_CONFIDENCE_THRESHOLD,
    after_cost_edge_bps_min_exclusive: float = A_GRADE_MIN_AFTER_COST_EDGE_BPS,
) -> list[str]:
    confidence_value = _first_present(row.get("confidence_calibrated"), row.get("confidence"))
    confidence = _coerce_float(confidence_value)
    edge = _directional_after_cost_edge_bps(row)
    decision = str(row.get("allocator_decision") or row.get("decision") or "")
    side = _side(row)
    reasons: list[str] = []
    if side not in {"long", "short"}:
        reasons.append("NON_DIRECTIONAL_ACTION")
    if confidence is None:
        reasons.append("MISSING_CONFIDENCE")
    elif confidence < confidence_threshold:
        reasons.append("LOW_CONFIDENCE")
    if edge is None:
        reasons.append("MISSING_AFTER_COST_EDGE")
    elif edge <= after_cost_edge_bps_min_exclusive:
        reasons.append("NON_POSITIVE_AFTER_COST_EDGE")
    if decision.startswith("BLOCK_"):
        reasons.append(f"ALLOCATOR_{decision}")
    return reasons


def _near_a_grade_diagnostic(
    row: dict[str, Any],
    reasons: list[str],
    *,
    confidence_threshold: float = A_GRADE_CONFIDENCE_THRESHOLD,
    after_cost_edge_bps_min_exclusive: float = A_GRADE_MIN_AFTER_COST_EDGE_BPS,
) -> dict[str, Any]:
    confidence = _coerce_float(_first_present(row.get("confidence_calibrated"), row.get("confidence")))
    edge = _directional_after_cost_edge_bps(row)
    decision = str(row.get("allocator_decision") or row.get("decision") or "")
    side = _side(row)
    confidence_gap = (
        round(max(0.0, confidence_threshold - confidence), 8)
        if confidence is not None else None
    )
    edge_gap = (
        round(max(0.0, after_cost_edge_bps_min_exclusive - edge), 8)
        if edge is not None else None
    )
    gap_score = (
        (confidence_gap if confidence_gap is not None else 1.0)
        + ((edge_gap / 100.0) if edge_gap is not None else 1.0)
        + (1.0 if side not in {"long", "short"} else 0.0)
        + (1.0 if decision.startswith("BLOCK_") else 0.0)
    )
    return {
        "symbol": row.get("symbol"),
        "timeframe": row.get("timeframe"),
        "side": _first_present(row.get("side"), row.get("action")),
        "source_kind": _source_kind(row),
        "signal_id": _first_present(row.get("signal_id"), row.get("id")),
        "prediction_id": _first_present(
            row.get("prediction_id"),
            row.get("source_prediction_id"),
            row.get("prediction_signal_id"),
        ),
        "feature_snapshot_id": row.get("feature_snapshot_id"),
        "decision_time": row.get("decision_time"),
        "available_at": _first_present(row.get("available_at"), row.get("entry_feature_available_at")),
        "generated_at": _first_present(row.get("generated_at"), row.get("entry_feature_generated_at")),
        "feature_cutoff": _first_present(row.get("feature_cutoff"), row.get("entry_feature_cutoff")),
        "source_redis_key": row.get("source_redis_key"),
        "confidence": round(confidence, 8) if confidence is not None else None,
        "confidence_threshold": confidence_threshold,
        "confidence_gap_to_a_grade": confidence_gap,
        "after_cost_edge_bps": round(edge, 8) if edge is not None else None,
        "minimum_after_cost_edge_bps": after_cost_edge_bps_min_exclusive,
        "edge_gap_to_positive_bps": edge_gap,
        "allocator_decision": decision or None,
        "allocator_blocked": decision.startswith("BLOCK_"),
        "reasons": sorted(set(reasons)),
        "eligibility_gap_score": round(gap_score, 8),
        "market_cost_evidence_status": row.get("market_cost_evidence_status"),
        "market_cost_evidence_missing_fields": row.get("market_cost_evidence_missing_fields", []),
        "market_cost_evidence_pit_reject_reasons": row.get(
            "market_cost_evidence_pit_reject_reasons",
            [],
        ),
    }


def _empty_a_grade_source_readiness() -> dict[str, Any]:
    return {
        "row_count": 0,
        "directional_row_count": 0,
        "confidence_present_count": 0,
        "confidence_at_or_above_threshold_count": 0,
        "edge_present_count": 0,
        "positive_after_cost_edge_count": 0,
        "positive_edge_below_confidence_count": 0,
        "a_grade_before_temporal_count": 0,
        "event_time_valid_candidate_count": 0,
        "best_configuration_count": 0,
        "no_feasible_configuration_count": 0,
        "temporal_invalid_count": 0,
        "not_a_grade_reason_counts": {},
        "max_confidence": None,
        "max_after_cost_edge_bps": None,
        "closest_near_a_grade": None,
    }


def _update_closest_near_a_grade(bucket: dict[str, Any], diagnostic: dict[str, Any]) -> None:
    current = bucket.get("closest_near_a_grade")
    if not isinstance(current, dict):
        bucket["closest_near_a_grade"] = diagnostic
        return
    if float(diagnostic.get("eligibility_gap_score") or 999.0) < float(current.get("eligibility_gap_score") or 999.0):
        bucket["closest_near_a_grade"] = diagnostic


def _normalized_symbol(row: dict[str, Any]) -> str:
    symbol = str(row.get("symbol") or "").strip().upper()
    return symbol if symbol else "UNKNOWN"


def _timeframe_from_source_key(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parts = [part for part in value.split(":") if part]
    for part in reversed(parts):
        if part in REQUIRED_COUNTERFACTUAL_TIMEFRAMES:
            return part
    return None


def _normalized_timeframe(row: dict[str, Any]) -> str:
    timeframe = str(
        _first_present(
            row.get("timeframe"),
            row.get("tf"),
            row.get("interval"),
            _timeframe_from_source_key(row.get("source_redis_key")),
        ) or ""
    ).strip()
    return timeframe if timeframe else "UNKNOWN"


def _source_kind(row: dict[str, Any]) -> str:
    explicit_kind = str(row.get("counterfactual_source_kind") or row.get("source_kind") or "").strip()
    if explicit_kind:
        return explicit_kind
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


def _counterfactual_source_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    symbols = sorted({
        _normalized_symbol(row)
        for row in rows
        if _normalized_symbol(row) != "UNKNOWN"
    })
    required_cells = {
        (symbol, timeframe)
        for symbol in symbols
        for timeframe in REQUIRED_COUNTERFACTUAL_TIMEFRAMES
    }
    observed_required_cells: set[tuple[str, str]] = set()
    observed_cells: set[tuple[str, str]] = set()
    timeframe_counts: dict[str, int] = {}
    source_kind_counts: dict[str, int] = {}
    for row in rows:
        symbol = _normalized_symbol(row)
        timeframe = _normalized_timeframe(row)
        timeframe_counts[timeframe] = timeframe_counts.get(timeframe, 0) + 1
        source_kind = _source_kind(row)
        source_kind_counts[source_kind] = source_kind_counts.get(source_kind, 0) + 1
        if symbol == "UNKNOWN" or timeframe == "UNKNOWN":
            continue
        observed_cells.add((symbol, timeframe))
        if timeframe in REQUIRED_COUNTERFACTUAL_TIMEFRAMES:
            observed_required_cells.add((symbol, timeframe))
    missing_cells = sorted(required_cells - observed_required_cells)
    required_count = len(required_cells)
    observed_required_count = len(observed_required_cells)
    coverage = observed_required_count / required_count if required_count else 0.0
    return {
        "required_all_observed_symbols_all_timeframes": True,
        "required_timeframes": list(REQUIRED_COUNTERFACTUAL_TIMEFRAMES),
        "source_row_count": len(rows),
        "source_symbol_count": len(symbols),
        "source_symbol_sample": symbols[:50],
        "source_timeframe_counts": {
            key: timeframe_counts[key] for key in sorted(timeframe_counts)
        },
        "source_kind_counts": {
            key: source_kind_counts[key] for key in sorted(source_kind_counts)
        },
        "required_symbol_timeframe_cell_count": required_count,
        "observed_required_symbol_timeframe_cell_count": observed_required_count,
        "observed_symbol_timeframe_cell_count": len(observed_cells),
        "missing_required_symbol_timeframe_cell_count": len(missing_cells),
        "missing_required_symbol_timeframe_cells_sample": [
            {"symbol": symbol, "timeframe": timeframe}
            for symbol, timeframe in missing_cells[:50]
        ],
        "source_coverage": round(coverage, 8),
        "source_coverage_status": (
            "PASSED"
            if required_count > 0 and observed_required_count == required_count
            else "NO_GO_COUNTERFACTUAL_SOURCE_COVERAGE_INCOMPLETE"
            if required_count > 0
            else "NO_COUNTERFACTUAL_SOURCE_ROWS"
        ),
    }


def _notional(row: dict[str, Any]) -> float:
    return abs(_coerce_float(_row_value(row, "gross_notional_usd")) or 0.0)


def _base_counterfactual_notional(
    row: dict[str, Any],
    *,
    equity: float,
    envelope: CounterfactualRiskEnvelope,
) -> tuple[float, str]:
    explicit = _notional(row)
    if explicit > 0.0:
        return explicit, "explicit_row_notional"
    if equity <= 0.0:
        return 0.0, "missing_notional_and_non_positive_equity"
    max_multiplier = max(DEFAULT_NOTIONAL_MULTIPLIERS)
    if max_multiplier <= 0.0:
        return 0.0, "invalid_counterfactual_notional_axis"
    max_notional = equity * envelope.max_portfolio_exposure_pct
    seed = max_notional / max_multiplier
    if seed <= 0.0:
        return 0.0, "risk_envelope_seed_non_positive"
    return seed, "risk_envelope_seed_max_portfolio_exposure"


def _orderbook_side_depth_usd(levels: Any) -> float | None:
    if not isinstance(levels, list):
        return None
    total = 0.0
    for level in levels:
        if isinstance(level, dict):
            price = _coerce_float(_first_present(level.get("price"), level.get("px")))
            quantity = _coerce_float(_first_present(level.get("quantity"), level.get("qty"), level.get("size")))
        elif isinstance(level, (list, tuple)) and len(level) >= 2:
            price = _coerce_float(level[0])
            quantity = _coerce_float(level[1])
        else:
            continue
        if price is None or quantity is None or price <= 0.0 or quantity <= 0.0:
            continue
        total += price * quantity
    return total if total > 0.0 else None


def _market_cost_contexts(row: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    contexts: list[tuple[str, dict[str, Any]]] = []
    allocation = _allocation_mapping(row)
    for prefix, mapping in (
        ("adaptive_allocation.model_inputs", allocation.get("model_inputs")),
        ("model_inputs", row.get("model_inputs")),
        ("market_cost_evidence", row.get("market_cost_evidence")),
        ("adaptive_allocation.market_cost_evidence", allocation.get("market_cost_evidence")),
    ):
        if isinstance(mapping, dict):
            contexts.append((prefix, mapping))
    return contexts


def _depth_capacity_usd(row: dict[str, Any]) -> tuple[float | None, str | None]:
    side = str(_first_present(row.get("side"), row.get("action"), "")).lower()
    microstructure = _nested_mapping(
        row,
        "market_microstructure",
        "microstructure_context",
        "orderbook_context",
        "liquidity_context",
        "depth_context",
    )
    direct_side_fields = (
        ("ask_depth_usd", "ask_depth_usdt", "entry_ask_depth_usd")
        if side == "long"
        else ("bid_depth_usd", "bid_depth_usdt", "entry_bid_depth_usd")
    )
    generic_fields = (
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
    )
    for field in (*direct_side_fields, *generic_fields):
        value = _coerce_float(_first_present(_row_value(row, field), microstructure.get(field)))
        if value is not None and value > 0.0:
            return value, field
    for prefix, context in _market_cost_contexts(row):
        for field in (*direct_side_fields, *generic_fields):
            value = _coerce_float(context.get(field))
            if value is not None and value > 0.0:
                return value, f"{prefix}.{field}"
    if side == "long":
        levels = _first_present(row.get("asks"), microstructure.get("asks"), row.get("ask_levels"), microstructure.get("ask_levels"))
    else:
        levels = _first_present(row.get("bids"), microstructure.get("bids"), row.get("bid_levels"), microstructure.get("bid_levels"))
    depth_from_levels = _orderbook_side_depth_usd(levels)
    if depth_from_levels is not None:
        return depth_from_levels, "orderbook_levels"
    level_fields = ("asks", "ask_levels") if side == "long" else ("bids", "bid_levels")
    for prefix, context in _market_cost_contexts(row):
        levels = _first_present(*(context.get(field) for field in level_fields))
        depth_from_levels = _orderbook_side_depth_usd(levels)
        if depth_from_levels is not None:
            return depth_from_levels, f"{prefix}.orderbook_levels"
    return None, None


def _bps_from_fields(
    row: dict[str, Any],
    *,
    bps_fields: tuple[str, ...],
    rate_fields: tuple[str, ...] = (),
    usd_fields: tuple[str, ...] = (),
    base_notional: float,
) -> tuple[float | None, str | None]:
    for field in bps_fields:
        value = _coerce_float(_row_value(row, field))
        if value is not None:
            return abs(value), field
    for field in bps_fields:
        for prefix, context in _market_cost_contexts(row):
            value = _coerce_float(context.get(field))
            if value is not None:
                return abs(value), f"{prefix}.{field}"
    for field in rate_fields:
        value = _coerce_float(_row_value(row, field))
        if value is not None:
            return abs(value) * 10000.0, field
    for field in rate_fields:
        for prefix, context in _market_cost_contexts(row):
            value = _coerce_float(context.get(field))
            if value is not None:
                return abs(value) * 10000.0, f"{prefix}.{field}"
    if base_notional > 0.0:
        for field in usd_fields:
            value = _coerce_float(_row_value(row, field))
            if value is not None:
                return abs(value) / base_notional * 10000.0, field
        for field in usd_fields:
            for prefix, context in _market_cost_contexts(row):
                value = _coerce_float(context.get(field))
                if value is not None:
                    return abs(value) / base_notional * 10000.0, f"{prefix}.{field}"
    return None, None


def _market_cost_evidence(
    row: dict[str, Any],
    *,
    base_notional: float,
) -> tuple[dict[str, float], dict[str, str], list[str]]:
    spread_bps, spread_source = _bps_from_fields(
        row,
        bps_fields=(
            "actual_observed_spread_entry_bps",
            "actual_spread_bps",
            "entry_spread_bps",
            "spread_bps",
        ),
        base_notional=base_notional,
    )
    slippage_bps, slippage_source = _bps_from_fields(
        row,
        bps_fields=(
            "actual_observed_slippage_bps",
            "actual_slippage_bps",
            "realized_slippage_bps",
            "expected_slippage_bps",
            "slippage_bps",
            "estimated_slippage_bps",
            "slippage_estimate_bps",
        ),
        usd_fields=("actual_slippage_usd", "expected_slippage_usd"),
        base_notional=base_notional,
    )
    fee_bps, fee_source = _bps_from_fields(
        row,
        bps_fields=(
            "actual_fee_bps",
            "fee_bps",
            "taker_fee_bps",
            "expected_fee_bps",
            "estimated_fee_bps",
            "fee_estimate_bps",
            "commission_bps",
        ),
        rate_fields=(
            "fee_rate",
            "taker_fee_rate",
            "expected_fee_rate",
            "estimated_fee_rate",
            "commission_rate",
        ),
        usd_fields=("actual_fees_usd", "expected_fees_usd"),
        base_notional=base_notional,
    )
    funding_bps, funding_source = _bps_from_fields(
        row,
        bps_fields=(
            "actual_funding_bps",
            "funding_bps",
            "funding_rate_bps",
            "expected_funding_bps",
            "estimated_funding_bps",
            "funding_estimate_bps",
        ),
        rate_fields=("funding_rate", "expected_funding_rate", "actual_funding_rate"),
        usd_fields=("actual_funding_usd", "expected_funding_usd"),
        base_notional=base_notional,
    )
    values: dict[str, float] = {}
    sources: dict[str, str] = {}
    missing: list[str] = []
    for label, value, source, reason in (
        ("spread_bps", spread_bps, spread_source, "MISSING_ACTUAL_SPREAD"),
        ("slippage_bps", slippage_bps, slippage_source, "MISSING_SLIPPAGE"),
        ("fee_bps", fee_bps, fee_source, "MISSING_FEES"),
        ("funding_bps", funding_bps, funding_source, "MISSING_FUNDING"),
    ):
        if value is None or source is None:
            missing.append(reason)
        else:
            values[label] = max(0.0, value)
            sources[label] = source
    return values, sources, missing


def _realized_move_bps(row: dict[str, Any], notional: float) -> float:
    direct = _coerce_float(_first_present(row.get("realized_pnl_bps"), row.get("paper_exit_pnl_bps")))
    if direct is not None:
        return direct
    pnl = _coerce_float(_first_present(row.get("realized_pnl_usd"), row.get("realized_pnl_usdt"))) or 0.0
    if notional <= 0:
        return 0.0
    return pnl / notional * 10000.0


def _base_stop_bps(row: dict[str, Any]) -> float:
    explicit = _coerce_float(_row_value(row, "stop_distance_bps"))
    if explicit is not None and explicit > 0:
        return explicit
    atr = _coerce_float(_first_present(_row_value(row, "entry_atr_bps"), _row_value(row, "atr_bps")))
    if atr is not None and atr > 0:
        return max(10.0, atr * 1.5)
    mae = _coerce_float(_row_value(row, "mae_bps"))
    if mae is not None and mae > 0:
        return max(10.0, mae)
    return 80.0


def _liq_distance_bps(leverage: float, maintenance_rate: float) -> float:
    if leverage <= 0:
        return 0.0
    return max(0.0, (1.0 / leverage - max(0.0, maintenance_rate)) * 10000.0)


def _liquidation_probability(*, liquidation_buffer_bps: float, stress_bps: float) -> float:
    if liquidation_buffer_bps <= 0:
        return 1.0
    return max(0.0, min(1.0, stress_bps / (liquidation_buffer_bps + stress_bps) * 0.01))


def _scenario_losses(result: dict[str, Any]) -> dict[str, float]:
    gross = float(result["gross_notional_usd"])
    stop = float(result["stop_distance_bps"])
    leverage = float(result["leverage"])
    buffer_bps = float(result["liquidation_buffer_bps"])
    return {
        "flash_crash": gross * min((stop * 4.0) / 10000.0, 1.0),
        "exchange_outage": gross * min((stop * 2.5) / 10000.0, 1.0),
        "spread_explosion": gross * 0.01,
        "slippage_spike": gross * 0.015,
        "funding_inversion": gross * 0.005,
        "squeeze": gross * min((stop * 3.0) / 10000.0, 1.0),
        "liquidation_cascade": gross * (1.0 if buffer_bps <= 0 else min(1.0, leverage * 0.10)),
    }


def _configuration_grid_count() -> int:
    return (
        len(DEFAULT_NOTIONAL_MULTIPLIERS)
        * len(DEFAULT_LEVERAGE_VALUES)
        * len(DEFAULT_MARGIN_MODES)
        * len(DEFAULT_STOP_MULTIPLIERS)
        * len(DEFAULT_TAKE_PROFIT_PLANS)
        * len(DEFAULT_HEDGE_FLAGS)
    )


def _theoretical_axis_values() -> dict[str, list[Any]]:
    return {
        "notional_multipliers": list(DEFAULT_NOTIONAL_MULTIPLIERS),
        "leverage_values": list(DEFAULT_LEVERAGE_VALUES),
        "margin_modes": list(DEFAULT_MARGIN_MODES),
        "stop_multipliers": list(DEFAULT_STOP_MULTIPLIERS),
        "take_profit_plans": list(DEFAULT_TAKE_PROFIT_PLANS),
        "hedge_flags": list(DEFAULT_HEDGE_FLAGS),
    }


def _empty_feasible_axis_values() -> dict[str, set[Any]]:
    return {
        "notional_multipliers": set(),
        "leverage_values": set(),
        "margin_modes": set(),
        "stop_distance_bps_values": set(),
        "take_profit_plans": set(),
        "hedge_flags": set(),
    }


def _accumulate_feasible_axis_values(
    feasible: dict[str, set[Any]],
    results: list[dict[str, Any]],
) -> None:
    for row in results:
        for output_field, source_field in (
            ("notional_multipliers", "notional_multiplier"),
            ("leverage_values", "leverage"),
            ("stop_distance_bps_values", "stop_distance_bps"),
        ):
            parsed = _coerce_float(row.get(source_field))
            if parsed is not None:
                feasible[output_field].add(parsed)
        for output_field, source_field in (
            ("margin_modes", "margin_mode"),
            ("take_profit_plans", "take_profit_plan"),
        ):
            value = row.get(source_field)
            if value not in (None, ""):
                feasible[output_field].add(str(value))
        hedge_enabled = row.get("hedge_enabled")
        if isinstance(hedge_enabled, bool):
            feasible["hedge_flags"].add(hedge_enabled)


def _feasible_axis_value_coverage_from_sets(
    feasible_sets: dict[str, set[Any]],
) -> dict[str, Any]:
    theoretical = _theoretical_axis_values()
    feasible = {
        key: sorted(values)
        for key, values in feasible_sets.items()
    }
    observed_stop_multiplier_count = len(feasible["stop_distance_bps_values"])
    return {
        "theoretical_axis_values": theoretical,
        "feasible_axis_values": feasible,
        "observed_axis_value_counts": {
            key: len(value)
            for key, value in feasible.items()
        },
        "required_axis_value_counts": {
            "notional_multipliers": len(DEFAULT_NOTIONAL_MULTIPLIERS),
            "leverage_values": len(DEFAULT_LEVERAGE_VALUES),
            "margin_modes": len(DEFAULT_MARGIN_MODES),
            "stop_distance_bps_values": len(DEFAULT_STOP_MULTIPLIERS),
            "take_profit_plans": len(DEFAULT_TAKE_PROFIT_PLANS),
            "hedge_flags": len(DEFAULT_HEDGE_FLAGS),
        },
        "full_feasible_axis_value_coverage": (
            set(feasible["notional_multipliers"]) == set(theoretical["notional_multipliers"])
            and set(feasible["leverage_values"]) == set(theoretical["leverage_values"])
            and set(feasible["margin_modes"]) == set(theoretical["margin_modes"])
            and observed_stop_multiplier_count == len(DEFAULT_STOP_MULTIPLIERS)
            and set(feasible["take_profit_plans"]) == set(theoretical["take_profit_plans"])
            and set(feasible["hedge_flags"]) == set(theoretical["hedge_flags"])
        ),
    }


def _feasible_axis_value_coverage(results: list[dict[str, Any]]) -> dict[str, Any]:
    feasible = _empty_feasible_axis_values()
    _accumulate_feasible_axis_values(feasible, results)
    return _feasible_axis_value_coverage_from_sets(feasible)


def _finalize_candidate_config_audit(audit: dict[str, Any]) -> dict[str, Any]:
    theoretical = int(audit.get("theoretical_configuration_count") or 0)
    considered = int(audit.get("configurations_considered_count") or 0)
    feasible = int(audit.get("feasible_configuration_count") or 0)
    pruned = int(audit.get("pruned_configuration_count") or 0)
    audit["axis_count"] = 6
    audit["considered_count"] = considered
    audit["feasible_count"] = feasible
    audit["pruned_count"] = pruned
    audit["configuration_count_reconciled"] = considered == theoretical
    audit["feasible_plus_pruned_reconciled"] = feasible + pruned == theoretical
    audit.setdefault("axis_value_coverage", _feasible_axis_value_coverage([]))
    return audit


def _empty_hedge_accounting_accumulator() -> dict[str, Any]:
    return {
        "configuration_count": 0,
        "hedge_enabled_configuration_count": 0,
        "hedge_disabled_configuration_count": 0,
        "hedge_budget_positive_count": 0,
        "hedge_cost_positive_count": 0,
        "expected_shortfall_reduced_count": 0,
        "max_hedge_budget_usd": 0.0,
        "max_hedge_cost_usd": 0.0,
        "hedge_tail_loss_reduction_factors": set(),
        "missing_field_counts": {},
    }


def _accumulate_hedge_accounting(
    accumulator: dict[str, Any],
    results: list[dict[str, Any]],
) -> None:
    required_fields = (
        "hedge_enabled",
        "hedge_budget_usd",
        "hedge_cost_bps",
        "hedge_cost_usd",
        "hedge_tail_loss_reduction_factor",
        "unhedged_expected_shortfall_usd",
        "expected_shortfall_usd",
    )
    missing_fields = accumulator["missing_field_counts"]
    reduction_factors = accumulator["hedge_tail_loss_reduction_factors"]
    for result in results:
        accumulator["configuration_count"] += 1
        for field in required_fields:
            if field not in result:
                missing_fields[field] = missing_fields.get(field, 0) + 1
        hedge_enabled = result.get("hedge_enabled") is True
        if hedge_enabled:
            accumulator["hedge_enabled_configuration_count"] += 1
        else:
            accumulator["hedge_disabled_configuration_count"] += 1
        hedge_budget = _coerce_float(result.get("hedge_budget_usd")) or 0.0
        hedge_cost = _coerce_float(result.get("hedge_cost_usd")) or 0.0
        hedge_factor = _coerce_float(result.get("hedge_tail_loss_reduction_factor"))
        unhedged_shortfall = _coerce_float(result.get("unhedged_expected_shortfall_usd")) or 0.0
        expected_shortfall = _coerce_float(result.get("expected_shortfall_usd")) or 0.0
        if hedge_budget > 0.0:
            accumulator["hedge_budget_positive_count"] += 1
        if hedge_cost > 0.0:
            accumulator["hedge_cost_positive_count"] += 1
        if unhedged_shortfall > expected_shortfall:
            accumulator["expected_shortfall_reduced_count"] += 1
        if hedge_factor is not None:
            reduction_factors.add(round(hedge_factor, 8))
        accumulator["max_hedge_budget_usd"] = max(
            accumulator["max_hedge_budget_usd"],
            hedge_budget,
        )
        accumulator["max_hedge_cost_usd"] = max(
            accumulator["max_hedge_cost_usd"],
            hedge_cost,
        )


def _finalize_hedge_accounting_accumulator(
    accumulator: dict[str, Any],
) -> dict[str, Any]:
    configuration_count = int(accumulator["configuration_count"])
    hedge_enabled_count = int(
        accumulator["hedge_enabled_configuration_count"]
    )
    hedge_disabled_count = int(
        accumulator["hedge_disabled_configuration_count"]
    )
    hedge_budget_positive_count = int(
        accumulator["hedge_budget_positive_count"]
    )
    hedge_cost_positive_count = int(accumulator["hedge_cost_positive_count"])
    expected_shortfall_reduced_count = int(
        accumulator["expected_shortfall_reduced_count"]
    )
    missing_fields = accumulator["missing_field_counts"]
    complete = (
        configuration_count > 0
        and not missing_fields
        and hedge_enabled_count > 0
        and hedge_disabled_count > 0
        and hedge_budget_positive_count == hedge_enabled_count
        and hedge_cost_positive_count == hedge_enabled_count
        and expected_shortfall_reduced_count == hedge_enabled_count
    )
    return {
        "status": "PASSED" if complete else "NO_GO_HEDGE_ACCOUNTING_INCOMPLETE",
        "configuration_count": configuration_count,
        "hedge_enabled_configuration_count": hedge_enabled_count,
        "hedge_disabled_configuration_count": hedge_disabled_count,
        "hedge_budget_positive_count": hedge_budget_positive_count,
        "hedge_cost_positive_count": hedge_cost_positive_count,
        "expected_shortfall_reduced_count": expected_shortfall_reduced_count,
        "max_hedge_budget_usd": round(accumulator["max_hedge_budget_usd"], 8),
        "max_hedge_cost_usd": round(accumulator["max_hedge_cost_usd"], 8),
        "hedge_tail_loss_reduction_factors": sorted(
            accumulator["hedge_tail_loss_reduction_factors"]
        ),
        "missing_field_counts": dict(sorted(missing_fields.items())),
        "hedge_cost_bps_when_enabled": COUNTERFACTUAL_HEDGE_COST_BPS,
        "tail_loss_reduction_factor_when_enabled": COUNTERFACTUAL_HEDGE_TAIL_LOSS_REDUCTION_FACTOR,
        "hedge_budget_usd_formula": "unhedged_expected_shortfall_usd - expected_shortfall_usd",
    }


def _hedge_accounting_audit(results: list[dict[str, Any]]) -> dict[str, Any]:
    accumulator = _empty_hedge_accounting_accumulator()
    _accumulate_hedge_accounting(accumulator, results)
    return _finalize_hedge_accounting_accumulator(accumulator)


def _simulate_candidate(
    row: dict[str, Any],
    *,
    equity: float,
    envelope: CounterfactualRiskEnvelope,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    audit = {
        "symbol": row.get("symbol"),
        "timeframe": row.get("timeframe"),
        "theoretical_configuration_count": _configuration_grid_count(),
        "configurations_considered_count": 0,
        "feasible_configuration_count": 0,
        "pruned_configuration_count": 0,
        "pruned_reason_counts": {},
    }

    def prune(reason: str, count: int = 1) -> None:
        audit["pruned_configuration_count"] += count
        reason_counts = audit["pruned_reason_counts"]
        reason_counts[reason] = reason_counts.get(reason, 0) + count

    base_notional, base_notional_source = _base_counterfactual_notional(
        row,
        equity=equity,
        envelope=envelope,
    )
    audit["base_notional_usd"] = round(base_notional, 8)
    audit["base_notional_source"] = base_notional_source
    if base_notional <= 0 or equity <= 0:
        prune("NON_POSITIVE_BASE_NOTIONAL_OR_EQUITY", _configuration_grid_count())
        audit["configurations_considered_count"] = audit["pruned_configuration_count"]
        return [], _finalize_candidate_config_audit(audit)
    depth_capacity, depth_source = _depth_capacity_usd(row)
    if depth_capacity is None or depth_capacity <= 0.0:
        prune("MISSING_MARKET_DEPTH", _configuration_grid_count())
        audit["configurations_considered_count"] = audit["pruned_configuration_count"]
        return [], _finalize_candidate_config_audit(audit)
    cost_values, cost_sources, cost_missing = _market_cost_evidence(row, base_notional=base_notional)
    if cost_missing:
        audit["pruned_configuration_count"] = _configuration_grid_count()
        reason_counts = audit["pruned_reason_counts"]
        for reason in cost_missing:
            reason_counts[reason] = _configuration_grid_count()
        audit["pruned_reason_counts"] = dict(sorted(reason_counts.items()))
        audit["configurations_considered_count"] = audit["pruned_configuration_count"]
        return [], _finalize_candidate_config_audit(audit)
    base_stop = _base_stop_bps(row)
    realized_bps = _realized_move_bps(row, base_notional)
    spread_bps = cost_values["spread_bps"]
    slippage_bps = cost_values["slippage_bps"]
    fee_bps = cost_values["fee_bps"]
    funding_bps = cost_values["funding_bps"]
    maintenance = _coerce_float(_row_value(row, "maintenance_margin_rate"))
    if maintenance is None or not 0.0 < maintenance < 1.0:
        prune("MISSING_OR_INVALID_MAINTENANCE_MARGIN_RATE", _configuration_grid_count())
        audit["configurations_considered_count"] = audit["pruned_configuration_count"]
        return [], _finalize_candidate_config_audit(audit)
    mfe_bps = max(0.0, _coerce_float(_row_value(row, "mfe_bps")) or abs(realized_bps))
    results: list[dict[str, Any]] = []
    for multiplier in DEFAULT_NOTIONAL_MULTIPLIERS:
        gross = base_notional * multiplier
        if gross > depth_capacity:
            prune(
                "DEPTH_CAPACITY_EXCEEDED",
                len(DEFAULT_LEVERAGE_VALUES)
                * len(DEFAULT_MARGIN_MODES)
                * len(DEFAULT_STOP_MULTIPLIERS)
                * len(DEFAULT_TAKE_PROFIT_PLANS)
                * len(DEFAULT_HEDGE_FLAGS),
            )
            continue
        if gross / equity > envelope.max_portfolio_exposure_pct:
            prune(
                "PORTFOLIO_EXPOSURE_LIMIT_BREACH",
                len(DEFAULT_LEVERAGE_VALUES)
                * len(DEFAULT_MARGIN_MODES)
                * len(DEFAULT_STOP_MULTIPLIERS)
                * len(DEFAULT_TAKE_PROFIT_PLANS)
                * len(DEFAULT_HEDGE_FLAGS),
            )
            continue
        for leverage in DEFAULT_LEVERAGE_VALUES:
            if leverage > envelope.max_effective_leverage:
                prune(
                    "EFFECTIVE_LEVERAGE_LIMIT_BREACH",
                    len(DEFAULT_MARGIN_MODES)
                    * len(DEFAULT_STOP_MULTIPLIERS)
                    * len(DEFAULT_TAKE_PROFIT_PLANS)
                    * len(DEFAULT_HEDGE_FLAGS),
                )
                continue
            allocated_margin = gross / leverage
            for margin_mode in DEFAULT_MARGIN_MODES:
                margin_penalty_bps = 0.0 if margin_mode == "isolated" else 2.0
                for stop_multiplier in DEFAULT_STOP_MULTIPLIERS:
                    stop_bps = base_stop * stop_multiplier
                    liquidation_distance = _liq_distance_bps(leverage, maintenance)
                    liquidation_buffer = liquidation_distance - stop_bps - spread_bps - slippage_bps - fee_bps - funding_bps
                    if liquidation_buffer < envelope.min_liquidation_buffer_bps:
                        prune(
                            "LIQUIDATION_BUFFER_LIMIT_BREACH",
                            len(DEFAULT_TAKE_PROFIT_PLANS) * len(DEFAULT_HEDGE_FLAGS),
                        )
                        continue
                    for take_profit_plan in DEFAULT_TAKE_PROFIT_PLANS:
                        if take_profit_plan == "one_r" and mfe_bps >= stop_bps:
                            outcome_bps = min(realized_bps, stop_bps)
                        elif take_profit_plan == "two_r" and mfe_bps >= stop_bps * 2.0:
                            outcome_bps = min(realized_bps, stop_bps * 2.0)
                        else:
                            outcome_bps = realized_bps
                        outcome_bps = max(outcome_bps, -stop_bps)
                        for hedge_enabled in DEFAULT_HEDGE_FLAGS:
                            hedge_cost_bps = COUNTERFACTUAL_HEDGE_COST_BPS if hedge_enabled else 0.0
                            hedge_tail_reduction = (
                                COUNTERFACTUAL_HEDGE_TAIL_LOSS_REDUCTION_FACTOR
                                if hedge_enabled else 1.0
                            )
                            cost_bps = spread_bps + slippage_bps + fee_bps + funding_bps + margin_penalty_bps + hedge_cost_bps
                            net_pnl_usd = gross * (outcome_bps - cost_bps) / 10000.0
                            unhedged_expected_shortfall_usd = gross * stop_bps / 10000.0
                            expected_shortfall_usd = unhedged_expected_shortfall_usd * hedge_tail_reduction
                            hedge_budget_usd = (
                                max(0.0, unhedged_expected_shortfall_usd - expected_shortfall_usd)
                                if hedge_enabled else 0.0
                            )
                            hedge_cost_usd = gross * hedge_cost_bps / 10000.0
                            drawdown_pct = max(0.0, expected_shortfall_usd / equity)
                            liq_probability = _liquidation_probability(
                                liquidation_buffer_bps=liquidation_buffer,
                                stress_bps=stop_bps * 3.0,
                            )
                            if drawdown_pct > envelope.max_drawdown_pct:
                                prune("DRAWDOWN_LIMIT_BREACH")
                                continue
                            if expected_shortfall_usd / equity > envelope.max_expected_shortfall_pct:
                                prune("EXPECTED_SHORTFALL_LIMIT_BREACH")
                                continue
                            if liq_probability > envelope.max_liquidation_probability:
                                prune("LIQUIDATION_PROBABILITY_LIMIT_BREACH")
                                continue
                            final_equity = equity + net_pnl_usd
                            if final_equity <= 0:
                                prune("NON_POSITIVE_FINAL_EQUITY")
                                continue
                            log_growth = math.log(final_equity / equity)
                            result = {
                                "symbol": row.get("symbol"),
                                "timeframe": row.get("timeframe"),
                                "side": _first_present(row.get("side"), row.get("action")),
                                "base_notional_usd": round(base_notional, 8),
                                "base_notional_source": base_notional_source,
                                "notional_multiplier": multiplier,
                                "gross_notional_usd": round(gross, 8),
                                "allocated_margin_usd": round(allocated_margin, 8),
                                "leverage": leverage,
                                "margin_mode": margin_mode,
                                "stop_distance_bps": round(stop_bps, 8),
                                "take_profit_plan": take_profit_plan,
                                "hedge_enabled": hedge_enabled,
                                "hedge_budget_usd": round(hedge_budget_usd, 8),
                                "hedge_cost_bps": round(hedge_cost_bps, 8),
                                "hedge_cost_usd": round(hedge_cost_usd, 8),
                                "hedge_tail_loss_reduction_factor": round(hedge_tail_reduction, 8),
                                "unhedged_expected_shortfall_usd": round(unhedged_expected_shortfall_usd, 8),
                                "net_pnl_usd": round(net_pnl_usd, 8),
                                "expected_shortfall_usd": round(expected_shortfall_usd, 8),
                                "liquidation_buffer_bps": round(liquidation_buffer, 8),
                                "liquidation_probability": round(liq_probability, 10),
                                "drawdown_pct": round(drawdown_pct, 10),
                                "expected_log_growth": round(log_growth, 12),
                                "actual_spread_bps": spread_bps,
                                "market_depth_capacity_usd": round(depth_capacity, 8),
                                "market_depth_source": depth_source,
                                "market_depth_utilization_pct": round(gross / depth_capacity, 10) if depth_capacity > 0 else None,
                                "slippage_bps": slippage_bps,
                                "fee_bps": fee_bps,
                                "funding_bps": funding_bps,
                                "market_cost_evidence_sources": dict(sorted(cost_sources.items())),
                            }
                            result["scenario_losses_usd"] = {
                                key: round(value * hedge_tail_reduction, 8)
                                for key, value in _scenario_losses(result).items()
                            }
                            results.append(result)
    audit["feasible_configuration_count"] = len(results)
    audit["configurations_considered_count"] = (
        audit["feasible_configuration_count"] + audit["pruned_configuration_count"]
    )
    audit["pruned_reason_counts"] = dict(sorted(audit["pruned_reason_counts"].items()))
    audit["axis_value_coverage"] = _feasible_axis_value_coverage(results)
    return results, _finalize_candidate_config_audit(audit)


def _no_feasible_configuration_reasons(
    row: dict[str, Any],
    *,
    equity: float,
    envelope: CounterfactualRiskEnvelope,
) -> list[str]:
    reasons: list[str] = []
    base_notional, _base_notional_source = _base_counterfactual_notional(
        row,
        equity=equity,
        envelope=envelope,
    )
    if equity <= 0.0:
        reasons.append("NON_POSITIVE_EQUITY")
    if base_notional <= 0.0:
        reasons.append("NON_POSITIVE_BASE_NOTIONAL")
    depth_capacity, _depth_source = _depth_capacity_usd(row)
    if depth_capacity is None or depth_capacity <= 0.0:
        reasons.append("MISSING_MARKET_DEPTH")
    elif base_notional * min(DEFAULT_NOTIONAL_MULTIPLIERS) > depth_capacity:
        reasons.append("DEPTH_BELOW_MIN_NOTIONAL")
    _cost_values, _cost_sources, cost_missing = _market_cost_evidence(row, base_notional=base_notional)
    reasons.extend(cost_missing)
    if not reasons:
        reasons.append("NO_CONFIGURATION_WITHIN_RISK_ENVELOPE")
    return reasons


def run_counterfactual_sweep(
    rows: list[dict[str, Any]],
    *,
    envelope: CounterfactualRiskEnvelope | None = None,
    require_full_source_coverage: bool = False,
    confidence_threshold: float = A_GRADE_CONFIDENCE_THRESHOLD,
    after_cost_edge_bps_min_exclusive: float = A_GRADE_MIN_AFTER_COST_EDGE_BPS,
) -> dict[str, Any]:
    envelope = envelope or CounterfactualRiskEnvelope()
    confidence_threshold = (
        _coerce_float(confidence_threshold)
        if confidence_threshold is not None else None
    )
    if confidence_threshold is None:
        confidence_threshold = A_GRADE_CONFIDENCE_THRESHOLD
    after_cost_edge_bps_min_exclusive = (
        _coerce_float(after_cost_edge_bps_min_exclusive)
        if after_cost_edge_bps_min_exclusive is not None else None
    )
    if after_cost_edge_bps_min_exclusive is None:
        after_cost_edge_bps_min_exclusive = A_GRADE_MIN_AFTER_COST_EDGE_BPS
    source_coverage = _counterfactual_source_coverage(rows)
    candidates: list[dict[str, Any]] = []
    skipped_temporal: list[dict[str, Any]] = []
    skipped_not_a_grade = 0
    skipped_not_a_grade_reason_counts: dict[str, int] = {}
    skipped_not_a_grade_sample: list[dict[str, Any]] = []
    near_a_grade_rows: list[dict[str, Any]] = []
    skipped_no_feasible_configuration = 0
    skipped_no_feasible_configuration_reason_counts: dict[str, int] = {}
    skipped_no_feasible_configuration_sample: list[dict[str, Any]] = []
    a_grade_before_temporal_count = 0
    source_kind_readiness: dict[str, dict[str, Any]] = {}
    for row in rows:
        source_kind = _source_kind(row)
        source_bucket = source_kind_readiness.setdefault(source_kind, _empty_a_grade_source_readiness())
        source_bucket["row_count"] += 1
        side = _side(row)
        confidence = _coerce_float(_first_present(row.get("confidence_calibrated"), row.get("confidence")))
        edge = _directional_after_cost_edge_bps(row)
        if side in {"long", "short"}:
            source_bucket["directional_row_count"] += 1
        if confidence is not None:
            source_bucket["confidence_present_count"] += 1
            source_bucket["max_confidence"] = round(
                max(float(source_bucket["max_confidence"] or confidence), confidence),
                8,
            )
            if confidence >= confidence_threshold:
                source_bucket["confidence_at_or_above_threshold_count"] += 1
        if edge is not None:
            source_bucket["edge_present_count"] += 1
            source_bucket["max_after_cost_edge_bps"] = round(
                max(float(source_bucket["max_after_cost_edge_bps"] or edge), edge),
                8,
            )
            if edge > after_cost_edge_bps_min_exclusive:
                source_bucket["positive_after_cost_edge_count"] += 1
                if confidence is not None and confidence < confidence_threshold:
                    source_bucket["positive_edge_below_confidence_count"] += 1
        not_a_grade_reasons = _not_a_grade_reasons(
            row,
            confidence_threshold=confidence_threshold,
            after_cost_edge_bps_min_exclusive=after_cost_edge_bps_min_exclusive,
        )
        if not_a_grade_reasons:
            skipped_not_a_grade += 1
            for reason in not_a_grade_reasons:
                skipped_not_a_grade_reason_counts[reason] = skipped_not_a_grade_reason_counts.get(reason, 0) + 1
                reason_counts = source_bucket["not_a_grade_reason_counts"]
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
            near_diagnostic = _near_a_grade_diagnostic(
                row,
                not_a_grade_reasons,
                confidence_threshold=confidence_threshold,
                after_cost_edge_bps_min_exclusive=after_cost_edge_bps_min_exclusive,
            )
            near_a_grade_rows.append(near_diagnostic)
            _update_closest_near_a_grade(source_bucket, near_diagnostic)
            if len(skipped_not_a_grade_sample) < 20:
                skipped_not_a_grade_sample.append({
                    "symbol": row.get("symbol"),
                    "timeframe": row.get("timeframe"),
                    "source_kind": source_kind,
                    "reasons": sorted(set(not_a_grade_reasons)),
                })
            continue
        a_grade_before_temporal_count += 1
        source_bucket["a_grade_before_temporal_count"] += 1
        temporal_ok, temporal_reasons = _temporal_status(row)
        if not temporal_ok:
            source_bucket["temporal_invalid_count"] += 1
            skipped_temporal.append({
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "source_kind": source_kind,
                "reasons": temporal_reasons,
            })
            continue
        source_bucket["event_time_valid_candidate_count"] += 1
        candidates.append(row)
    feasible_result_count = 0
    feasible_axis_values = _empty_feasible_axis_values()
    hedge_accounting_accumulator = _empty_hedge_accounting_accumulator()
    best_by_signal: list[dict[str, Any]] = []
    configuration_audit_sample: list[dict[str, Any]] = []
    theoretical_configuration_count = 0
    configurations_considered_count = 0
    pruned_configuration_count = 0
    pruned_reason_counts: dict[str, int] = {}
    equity = envelope.starting_equity_usd
    for index, row in enumerate(candidates):
        simulated, configuration_audit = _simulate_candidate(row, equity=equity, envelope=envelope)
        if len(configuration_audit_sample) < 20:
            configuration_audit_sample.append(configuration_audit)
        theoretical_configuration_count += int(
            configuration_audit.get("theoretical_configuration_count") or 0
        )
        configurations_considered_count += int(
            configuration_audit.get("configurations_considered_count") or 0
        )
        pruned_configuration_count += int(
            configuration_audit.get("pruned_configuration_count") or 0
        )
        for reason, count in (
            configuration_audit.get("pruned_reason_counts") or {}
        ).items():
            pruned_reason_counts[reason] = (
                pruned_reason_counts.get(reason, 0) + int(count or 0)
            )
        feasible_result_count += len(simulated)
        _accumulate_feasible_axis_values(feasible_axis_values, simulated)
        _accumulate_hedge_accounting(
            hedge_accounting_accumulator,
            simulated,
        )
        if not simulated:
            source_bucket = source_kind_readiness.setdefault(_source_kind(row), _empty_a_grade_source_readiness())
            source_bucket["no_feasible_configuration_count"] += 1
            skipped_no_feasible_configuration += 1
            no_config_reasons = _no_feasible_configuration_reasons(row, equity=equity, envelope=envelope)
            for reason in no_config_reasons:
                skipped_no_feasible_configuration_reason_counts[reason] = (
                    skipped_no_feasible_configuration_reason_counts.get(reason, 0) + 1
                )
            if len(skipped_no_feasible_configuration_sample) < 20:
                skipped_no_feasible_configuration_sample.append({
                    "symbol": row.get("symbol"),
                    "timeframe": row.get("timeframe"),
                    "source_kind": _source_kind(row),
                    "reasons": sorted(set(no_config_reasons)),
                })
            continue
        best = max(simulated, key=lambda item: item["expected_log_growth"])
        best_by_signal.append({
            "signal_index": index,
            "symbol": row.get("symbol"),
            "timeframe": row.get("timeframe"),
            "source_kind": _source_kind(row),
            "selected": best,
        })
        source_bucket = source_kind_readiness.setdefault(_source_kind(row), _empty_a_grade_source_readiness())
        source_bucket["best_configuration_count"] += 1
        equity = max(0.01, equity + float(best["net_pnl_usd"]))
    source_coverage_passed = source_coverage["source_coverage_status"] == "PASSED"
    completed = (
        bool(candidates)
        and len(best_by_signal) == len(candidates)
        and (source_coverage_passed or not require_full_source_coverage)
    )
    total_log_growth = sum(float(item["selected"]["expected_log_growth"]) for item in best_by_signal)
    worst_shortfall = max((float(item["selected"]["expected_shortfall_usd"]) for item in best_by_signal), default=0.0)
    max_liq_probability = max((float(item["selected"]["liquidation_probability"]) for item in best_by_signal), default=0.0)
    config_space_audit = {
        "axis_count": 6,
        "per_candidate_theoretical_configuration_count": _configuration_grid_count(),
        "candidate_count": len(candidates),
        "event_time_valid_candidate_count": len(candidates),
        "theoretical_configuration_count": theoretical_configuration_count,
        "considered_count": configurations_considered_count,
        "configurations_considered_count": configurations_considered_count,
        "feasible_count": feasible_result_count,
        "feasible_configuration_count": feasible_result_count,
        "pruned_count": pruned_configuration_count,
        "pruned_configuration_count": pruned_configuration_count,
        "configuration_count_reconciled": configurations_considered_count == theoretical_configuration_count,
        "feasible_plus_pruned_reconciled": (
            feasible_result_count + pruned_configuration_count
            == theoretical_configuration_count
        ),
        "pruned_reason_counts": dict(sorted(pruned_reason_counts.items())),
        "axis_value_coverage": _feasible_axis_value_coverage_from_sets(
            feasible_axis_values
        ),
        "candidate_configuration_audit_sample": configuration_audit_sample,
        "feasible_rows_materialized_across_candidates": False,
        "feasible_rows_aggregated_streaming": True,
    }
    hedge_accounting_audit = _finalize_hedge_accounting_accumulator(
        hedge_accounting_accumulator
    )
    near_a_grade_sample = sorted(
        near_a_grade_rows,
        key=lambda item: (
            float(item["eligibility_gap_score"]),
            -float(item["confidence"] or 0.0),
            -float(item["after_cost_edge_bps"] or 0.0),
            str(item.get("symbol") or ""),
            str(item.get("timeframe") or ""),
        ),
    )[:20]
    blocker_reasons: list[str] = []
    if not rows:
        blocker_reasons.append("NO_COUNTERFACTUAL_SOURCE_ROWS")
    if (
        require_full_source_coverage
        and source_coverage["source_coverage_status"] == "NO_GO_COUNTERFACTUAL_SOURCE_COVERAGE_INCOMPLETE"
    ):
        blocker_reasons.append("COUNTERFACTUAL_SOURCE_COVERAGE_INCOMPLETE")
    if rows and a_grade_before_temporal_count == 0:
        blocker_reasons.append("NO_A_GRADE_SIGNALS")
    if a_grade_before_temporal_count > 0 and not candidates:
        blocker_reasons.append("NO_EVENT_TIME_VALID_CANDIDATES")
    if skipped_no_feasible_configuration:
        blocker_reasons.append("NO_FEASIBLE_CONFIGURATION_FOR_SOME_CANDIDATES")
    if candidates and not best_by_signal:
        blocker_reasons.append("NO_BEST_CONFIGURATIONS")
    elif candidates and len(best_by_signal) < len(candidates):
        blocker_reasons.append("PARTIAL_BEST_CONFIGURATION_COVERAGE")
    source_kind_readiness = {
        source_kind: {
            **bucket,
            "not_a_grade_reason_counts": dict(sorted((bucket.get("not_a_grade_reason_counts") or {}).items())),
            "confidence_threshold": confidence_threshold,
            "after_cost_edge_bps_min_exclusive": after_cost_edge_bps_min_exclusive,
            "confidence_gap_to_threshold": (
                round(max(0.0, confidence_threshold - float(bucket["max_confidence"])), 8)
                if bucket.get("max_confidence") is not None else None
            ),
            "positive_edge_but_below_confidence_count": (
                int(bucket.get("positive_edge_below_confidence_count") or 0)
            ),
        }
        for source_kind, bucket in sorted(source_kind_readiness.items())
    }
    closest_by_source = {
        source_kind: bucket.get("closest_near_a_grade")
        for source_kind, bucket in source_kind_readiness.items()
        if isinstance(bucket.get("closest_near_a_grade"), dict)
    }
    a_grade_readiness = {
        "confidence_threshold": confidence_threshold,
        "after_cost_edge_bps_min_exclusive": after_cost_edge_bps_min_exclusive,
        "source_row_count": len(rows),
        "source_kind_counts": {
            source_kind: bucket["row_count"]
            for source_kind, bucket in source_kind_readiness.items()
        },
        "source_kind_readiness": source_kind_readiness,
        "closest_near_a_grade_by_source_kind": closest_by_source,
        "a_grade_before_temporal_count": a_grade_before_temporal_count,
        "event_time_valid_candidate_count": len(candidates),
        "best_configuration_count": len(best_by_signal),
        "readiness_blocker_reasons": blocker_reasons,
    }
    return {
        "status": "PASSED" if completed else "NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE",
        "counterfactual_blocker_reasons": blocker_reasons,
        "event_time_valid_required": True,
        "source_coverage_required_for_pass": require_full_source_coverage,
        "source_coverage": source_coverage,
        "a_grade_thresholds": {
            "confidence_min": confidence_threshold,
            "after_cost_edge_bps_min_exclusive": after_cost_edge_bps_min_exclusive,
            "allocator_blocked_decisions_excluded": True,
        },
        "a_grade_before_temporal_count": a_grade_before_temporal_count,
        "event_time_valid_candidate_count": len(candidates),
        "skipped_not_a_grade_count": skipped_not_a_grade,
        "skipped_not_a_grade_reason_counts": dict(sorted(skipped_not_a_grade_reason_counts.items())),
        "skipped_not_a_grade_sample": skipped_not_a_grade_sample,
        "near_a_grade_sample": near_a_grade_sample,
        "a_grade_readiness": a_grade_readiness,
        "skipped_temporal_invalid_count": len(skipped_temporal),
        "skipped_temporal_invalid_sample": skipped_temporal[:20],
        "skipped_no_feasible_configuration_count": skipped_no_feasible_configuration,
        "skipped_no_feasible_configuration_reason_counts": dict(sorted(skipped_no_feasible_configuration_reason_counts.items())),
        "skipped_no_feasible_configuration_sample": skipped_no_feasible_configuration_sample,
        "sweep_result_count": feasible_result_count,
        "config_space_audit": config_space_audit,
        "hedge_accounting_audit": hedge_accounting_audit,
        "best_configuration_count": len(best_by_signal),
        "efficient_frontier_ready": completed,
        "objective": "maximize_expected_log_final_equity",
        "total_expected_log_growth": round(total_log_growth, 12),
        "worst_expected_shortfall_usd": round(worst_shortfall, 8),
        "max_liquidation_probability": round(max_liq_probability, 10),
        "best_configurations": best_by_signal,
        "best_configurations_sample": best_by_signal[:25],
        "config_axes": {
            **_theoretical_axis_values(),
            "hedge_budget_model": {
                "hedge_cost_bps_when_enabled": COUNTERFACTUAL_HEDGE_COST_BPS,
                "tail_loss_reduction_factor_when_enabled": (
                    COUNTERFACTUAL_HEDGE_TAIL_LOSS_REDUCTION_FACTOR
                ),
                "hedge_budget_usd_formula": (
                    "unhedged_expected_shortfall_usd - expected_shortfall_usd"
                ),
            },
            "market_depth_capacity": "required_actual_depth_usd_or_orderbook_levels",
            "market_cost_evidence": "required_explicit_spread_slippage_fee_funding_bps_or_usd",
        },
    }


def run_rare_event_capital_stress(sweep: dict[str, Any]) -> dict[str, Any]:
    best = sweep.get("best_configurations") or sweep.get("best_configurations_sample") or []
    if not best:
        return {
            "status": "NO_GO_RARE_EVENT_CAPITAL_STRESS_NOT_RUN",
            "stress_source": "counterfactual_best_configurations",
            "required_scenarios": list(REQUIRED_SCENARIOS),
            "completed_scenarios": [],
            "scenario_failures": ["NO_COUNTERFACTUAL_BEST_CONFIGURATIONS"],
        }
    scenario_max: dict[str, float] = {scenario: 0.0 for scenario in REQUIRED_SCENARIOS}
    for item in best:
        selected = item.get("selected") if isinstance(item, dict) else None
        if not isinstance(selected, dict):
            continue
        losses = selected.get("scenario_losses_usd") or {}
        for scenario in REQUIRED_SCENARIOS:
            scenario_max[scenario] = max(scenario_max[scenario], float(losses.get(scenario) or 0.0))
    failures = [
        scenario
        for scenario, loss in scenario_max.items()
        if loss > CounterfactualRiskEnvelope().starting_equity_usd * CounterfactualRiskEnvelope().max_drawdown_pct
    ]
    return {
        "status": "PASSED" if not failures else "NO_GO_RARE_EVENT_CAPITAL_STRESS_FAILED",
        "stress_source": "counterfactual_best_configurations",
        "required_scenarios": list(REQUIRED_SCENARIOS),
        "completed_scenarios": list(REQUIRED_SCENARIOS),
        "scenario_max_loss_usd": {key: round(value, 8) for key, value in scenario_max.items()},
        "scenario_failures": failures,
    }


def _runtime_allocation_stress_row(row: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    gross = _notional(row)
    stop = _coerce_float(row.get("stop_distance_bps"))
    leverage = _coerce_float(_first_present(row.get("effective_leverage"), row.get("recommended_leverage"), row.get("leverage")))
    liquidation_buffer = _coerce_float(row.get("liquidation_buffer_bps"))
    reasons: list[str] = []
    if gross <= 0.0:
        reasons.append("MISSING_OR_NON_POSITIVE_GROSS_NOTIONAL")
    if stop is None or stop <= 0.0:
        reasons.append("MISSING_OR_NON_POSITIVE_STOP_DISTANCE")
    if leverage is None or leverage <= 0.0:
        reasons.append("MISSING_OR_NON_POSITIVE_EFFECTIVE_LEVERAGE")
    if liquidation_buffer is None:
        reasons.append("MISSING_LIQUIDATION_BUFFER")
    if reasons:
        return None, reasons
    selected = {
        "symbol": row.get("symbol"),
        "timeframe": row.get("timeframe"),
        "side": _first_present(row.get("side"), row.get("action")),
        "gross_notional_usd": gross,
        "stop_distance_bps": stop,
        "leverage": leverage,
        "liquidation_buffer_bps": liquidation_buffer,
        "allocated_margin_usd": _coerce_float(row.get("allocated_margin_usd")),
        "expected_shortfall_usd": _coerce_float(row.get("expected_shortfall_usd")),
        "hedge_budget_usd": _coerce_float(row.get("hedge_budget_usd")) or 0.0,
    }
    selected["scenario_losses_usd"] = {
        key: round(value, 8)
        for key, value in _scenario_losses(selected).items()
    }
    return selected, []


def run_runtime_allocation_rare_event_stress(
    rows: list[dict[str, Any]],
    *,
    envelope: CounterfactualRiskEnvelope | None = None,
) -> dict[str, Any]:
    envelope = envelope or CounterfactualRiskEnvelope()
    equity = max(0.0, float(envelope.starting_equity_usd))
    limit_usd = equity * envelope.max_drawdown_pct
    if not rows:
        zero_losses = {scenario: 0.0 for scenario in REQUIRED_SCENARIOS}
        return {
            "status": "PASSED",
            "stress_source": "runtime_no_current_exposure",
            "required_scenarios": list(REQUIRED_SCENARIOS),
            "completed_scenarios": list(REQUIRED_SCENARIOS),
            "runtime_allocation_row_count": 0,
            "runtime_stressed_row_count": 0,
            "stressed_allocation_sample_count": 0,
            "runtime_stress_missing_evidence_count": 0,
            "runtime_stress_missing_evidence_sample": [],
            "scenario_loss_limit_usd": round(limit_usd, 8),
            "scenario_loss_limit_pct": round(envelope.max_drawdown_pct, 8),
            "scenario_max_loss_usd": zero_losses,
            "scenario_total_loss_usd": zero_losses,
            "scenario_failures": [],
            "stressed_allocation_sample": [],
            "no_current_runtime_exposure": True,
            "notes": (
                "No open adaptive-capital positions or active sized pre-submit candidates "
                "were present, so runtime rare-event loss is zero. Counterfactual A-grade "
                "configuration stress remains separately gated by the counterfactual replay status."
            ),
        }
    scenario_max: dict[str, float] = {scenario: 0.0 for scenario in REQUIRED_SCENARIOS}
    scenario_total: dict[str, float] = {scenario: 0.0 for scenario in REQUIRED_SCENARIOS}
    stressed_rows: list[dict[str, Any]] = []
    stressed_count = 0
    missing_sample: list[dict[str, Any]] = []
    missing_count = 0
    for row in rows:
        selected, reasons = _runtime_allocation_stress_row(row)
        if selected is None:
            missing_count += 1
            if len(missing_sample) < 20:
                missing_sample.append({
                    "symbol": row.get("symbol"),
                    "timeframe": row.get("timeframe"),
                    "reasons": sorted(set(reasons)),
                })
            continue
        losses = selected.get("scenario_losses_usd") or {}
        for scenario in REQUIRED_SCENARIOS:
            loss = float(losses.get(scenario) or 0.0)
            scenario_max[scenario] = max(scenario_max[scenario], loss)
            scenario_total[scenario] += loss
        stressed_count += 1
        if len(stressed_rows) < 20:
            stressed_rows.append({
                "symbol": selected.get("symbol"),
                "timeframe": selected.get("timeframe"),
                "side": selected.get("side"),
                "gross_notional_usd": round(float(selected["gross_notional_usd"]), 8),
                "allocated_margin_usd": (
                    round(float(selected["allocated_margin_usd"]), 8)
                    if selected.get("allocated_margin_usd") is not None
                    else None
                ),
                "effective_leverage": round(float(selected["leverage"]), 8),
                "stop_distance_bps": round(float(selected["stop_distance_bps"]), 8),
                "liquidation_buffer_bps": round(float(selected["liquidation_buffer_bps"]), 8),
                "expected_shortfall_usd": (
                    round(float(selected["expected_shortfall_usd"]), 8)
                    if selected.get("expected_shortfall_usd") is not None
                    else None
                ),
                "hedge_budget_usd": round(float(selected["hedge_budget_usd"]), 8),
                "scenario_losses_usd": selected["scenario_losses_usd"],
            })
    completed = list(REQUIRED_SCENARIOS) if stressed_count else []
    scenario_failures = [
        scenario
        for scenario, loss in scenario_total.items()
        if loss > limit_usd
    ]
    if missing_count:
        scenario_failures.append("MISSING_RUNTIME_ALLOCATION_STRESS_FIELDS")
    if not stressed_count:
        scenario_failures.append("NO_STRESSABLE_RUNTIME_ALLOCATIONS")
    status = (
        "PASSED"
        if not scenario_failures
        else "NO_GO_RARE_EVENT_CAPITAL_STRESS_INCOMPLETE"
        if missing_count or not stressed_rows
        else "NO_GO_RARE_EVENT_CAPITAL_STRESS_FAILED"
    )
    return {
        "status": status,
        "stress_source": "runtime_adaptive_allocations",
        "required_scenarios": list(REQUIRED_SCENARIOS),
        "completed_scenarios": completed,
        "runtime_allocation_row_count": len(rows),
        "runtime_stressed_row_count": stressed_count,
        "stressed_allocation_sample_count": len(stressed_rows),
        "runtime_stress_missing_evidence_count": missing_count,
        "runtime_stress_missing_evidence_sample": missing_sample,
        "scenario_loss_limit_usd": round(limit_usd, 8),
        "scenario_loss_limit_pct": round(envelope.max_drawdown_pct, 8),
        "scenario_max_loss_usd": {key: round(value, 8) for key, value in scenario_max.items()},
        "scenario_total_loss_usd": {key: round(value, 8) for key, value in scenario_total.items()},
        "scenario_failures": scenario_failures,
        "stressed_allocation_sample": stressed_rows,
    }
