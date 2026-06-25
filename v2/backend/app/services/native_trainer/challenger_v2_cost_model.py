"""Production-equivalent cost model for V2 challenger research.

This module mirrors the paper execution cost inputs without touching paper
runtime behavior. A single function is used by replay labels, validation,
lockbox rows, shadow ranking, and any future paper canary gate.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Mapping

from v2.backend.app.services.adaptive_capital_allocator import AllocationInput


SCHEMA_VERSION = "challenger_v2_production_equivalent_cost_model_v1"
PRODUCTION_STANDARD_ROUND_TRIP_COST_BPS = 12.0
DEFAULT_HOLDING_PERIOD_SECONDS = 15 * 60
FUNDING_INTERVAL_SECONDS = 8 * 60 * 60
PAPER_CONFIGURED_FEE_SOURCE = "adaptive_capital_allocator.AllocationInput.fee_bps"


def finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _first_float(*values: Any) -> float | None:
    for value in values:
        parsed = finite_float(value)
        if parsed is not None:
            return parsed
    return None


def _features(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("features")
    return value if isinstance(value, Mapping) else {}


def _field(row: Mapping[str, Any], *names: str) -> Any:
    features = _features(row)
    for name in names:
        if row.get(name) not in (None, ""):
            return row.get(name)
        if features.get(name) not in (None, ""):
            return features.get(name)
    return None


def _modeled_slippage_bps(
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


def _derived_spread_bps(row: Mapping[str, Any]) -> float | None:
    spread = _first_float(
        _field(row, "observed_bid_ask_spread_bps"),
        _field(row, "actual_observed_spread_entry_bps"),
        _field(row, "bid_ask_spread_bps"),
        _field(row, "spread_bps"),
        _field(row, "ob_ob_spread_bps"),
    )
    if spread is not None:
        return abs(spread)
    bid = _first_float(_field(row, "best_bid"), _field(row, "bid"))
    ask = _first_float(_field(row, "best_ask"), _field(row, "ask"))
    mid = _first_float(_field(row, "mid_price"), _field(row, "mid"))
    if mid is None and bid is not None and ask is not None:
        mid = (bid + ask) / 2.0
    if bid is not None and ask is not None and mid and mid > 0.0:
        return abs(ask - bid) / mid * 10_000.0
    return None


def _depth_impact_bps(
    row: Mapping[str, Any],
    *,
    side: str,
    order_notional_usd: float | None,
    spread_bps: float | None,
) -> tuple[float, str, bool]:
    direct = _first_float(
        _field(row, "depth_price_impact_bps"),
        _field(row, "depth_impact_bps"),
        _field(row, "expected_price_impact_bps"),
    )
    if direct is not None:
        return max(0.0, abs(direct)), "observed_or_runtime_depth_price_impact_bps", False
    depth = _first_float(
        _field(row, "ask_depth_usd" if side == "long" else "bid_depth_usd"),
        _field(row, "entry_orderbook_depth_usd"),
        _field(row, "orderbook_depth_usd"),
        _field(row, "market_depth_usd"),
        _field(row, "top_of_book_depth_usd"),
        _field(row, "book_depth_usd"),
    )
    if depth is None or depth <= 0.0 or order_notional_usd is None or order_notional_usd <= 0.0:
        return 0.0, "MISSING_DEPTH_OR_ORDER_NOTIONAL", True
    utilization = max(0.0, float(order_notional_usd) / float(depth))
    impact = utilization * max(abs(spread_bps or 0.0), 1.0) * 2.0
    return round(min(100.0, impact), 8), "MODELED_FROM_ORDERBOOK_DEPTH_AND_NOTIONAL", False


def _fee_bps(row: Mapping[str, Any]) -> tuple[float, str, bool]:
    maker_probability = _first_float(_field(row, "maker_probability"))
    taker_probability = _first_float(_field(row, "taker_probability"))
    maker_fee = _first_float(_field(row, "maker_fee_bps"))
    taker_fee = _first_float(_field(row, "taker_fee_bps"))
    if maker_probability is not None and taker_probability is not None and (maker_fee is not None or taker_fee is not None):
        maker_fee = maker_fee if maker_fee is not None else 0.0
        taker_fee = taker_fee if taker_fee is not None else float(AllocationInput.__dataclass_fields__["fee_bps"].default)
        total_probability = max(1e-12, maker_probability + taker_probability)
        maker_weight = max(0.0, maker_probability) / total_probability
        taker_weight = max(0.0, taker_probability) / total_probability
        return (
            round(abs(maker_fee) * maker_weight + abs(taker_fee) * taker_weight, 8),
            "MAKER_TAKER_WEIGHTED_FEE_BPS",
            False,
        )
    direct = _first_float(
        _field(row, "actual_fee_bps"),
        _field(row, "fee_bps"),
        _field(row, "expected_fee_bps"),
    )
    if direct is not None:
        return abs(direct), "OBSERVED_OR_UPSTREAM_FEE_BPS", False
    return (
        float(AllocationInput.__dataclass_fields__["fee_bps"].default),
        PAPER_CONFIGURED_FEE_SOURCE,
        False,
    )


def _funding_bps(row: Mapping[str, Any], *, holding_period_seconds: int) -> tuple[float, str, bool]:
    direct = _first_float(
        _field(row, "expected_funding_bps"),
        _field(row, "funding_bps"),
        _field(row, "funding_rate_bps"),
        _field(row, "actual_funding_bps"),
    )
    if direct is not None:
        return float(direct), "EXPECTED_FUNDING_BPS_AT_DECISION_TIME", False
    funding_rate = _first_float(_field(row, "funding_rate"), _field(row, "last_funding_rate"))
    if funding_rate is not None:
        scaled = float(funding_rate) * 10_000.0 * (max(0, int(holding_period_seconds)) / FUNDING_INTERVAL_SECONDS)
        return round(scaled, 8), "FUNDING_RATE_SCALED_TO_HOLDING_PERIOD", False
    return 0.0, "MISSING_FUNDING_AT_DECISION_TIME", True


def _latency_reserve_bps(row: Mapping[str, Any]) -> tuple[float, str, bool]:
    direct = _first_float(_field(row, "latency_reserve_bps"))
    if direct is not None:
        return abs(direct), "EXPLICIT_LATENCY_RESERVE_BPS", False
    latency_ms = _first_float(
        _field(row, "latency_ms"),
        _field(row, "paper_fill_latency_ms"),
        _field(row, "fill_latency_ms"),
        _field(row, "execution_latency_ms"),
        _field(row, "simulated_latency_ms"),
    )
    volatility = _first_float(_field(row, "atr_bps"), _field(row, "volatility_bps"))
    if latency_ms is None:
        return 0.0, "MISSING_LATENCY_EVIDENCE", True
    reserve = (max(0.0, latency_ms) / 1000.0) * max(float(volatility or 1.0), 1.0) * 0.001
    return round(min(25.0, reserve), 8), "MODELED_FROM_LATENCY_AND_VOLATILITY", False


def _partial_fill_adjustment_bps(row: Mapping[str, Any], *, spread_bps: float | None) -> tuple[float, str, bool]:
    direct = _first_float(_field(row, "partial_fill_adjustment_bps"))
    if direct is not None:
        return abs(direct), "EXPLICIT_PARTIAL_FILL_ADJUSTMENT_BPS", False
    fill_probability = _first_float(_field(row, "partial_fill_probability"), _field(row, "execution_probability"))
    if fill_probability is None:
        partial_count = _first_float(_field(row, "partial_fill_count"))
        if partial_count is not None and partial_count > 0.0:
            return 0.0, "PARTIAL_FILL_LEDGER_PRESENT", False
        return 0.0, "MISSING_PARTIAL_FILL_ESTIMATE", True
    adjustment = max(0.0, 1.0 - max(0.0, min(1.0, fill_probability))) * max(abs(spread_bps or 0.0), 1.0)
    return round(adjustment, 8), "MODELED_FROM_PARTIAL_FILL_PROBABILITY", False


def _mark_index_divergence_bps(row: Mapping[str, Any]) -> tuple[float, str, bool]:
    direct = _first_float(_field(row, "mark_index_divergence_bps"))
    if direct is not None:
        return abs(direct), "EXPLICIT_MARK_INDEX_DIVERGENCE_BPS", False
    mark = _first_float(_field(row, "mark_price"))
    index = _first_float(_field(row, "index_price"))
    if mark is None or index is None or index <= 0.0:
        return 0.0, "MISSING_MARK_INDEX_DIVERGENCE_EVIDENCE", True
    return round(abs(mark - index) / index * 10_000.0, 8), "DERIVED_FROM_MARK_AND_INDEX_PRICE", False


@dataclass(frozen=True)
class ProductionCostBreakdown:
    observed_bid_ask_spread_bps: float | None
    depth_impact_bps: float
    fee_bps: float
    slippage_bps: float
    funding_bps: float
    latency_reserve_bps: float
    partial_fill_adjustment_bps: float
    mark_index_divergence_bps: float
    production_standard_reserve_bps: float
    total_cost_bps: float
    fallback: bool
    fallback_components: tuple[str, ...]
    production_grade_evidence: bool
    component_sources: dict[str, str]
    cost_model_hash: str

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "observed_bid_ask_spread_bps": self.observed_bid_ask_spread_bps,
            "depth_impact_bps": self.depth_impact_bps,
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "funding_bps": self.funding_bps,
            "latency_reserve_bps": self.latency_reserve_bps,
            "partial_fill_adjustment_bps": self.partial_fill_adjustment_bps,
            "mark_index_divergence_bps": self.mark_index_divergence_bps,
            "production_standard_reserve_bps": self.production_standard_reserve_bps,
            "total_cost_bps": self.total_cost_bps,
            "fallback": self.fallback,
            "fallback_components": list(self.fallback_components),
            "production_grade_evidence": self.production_grade_evidence,
            "component_sources": dict(self.component_sources),
            "cost_model_hash": self.cost_model_hash,
        }


def cost_model_hash() -> str:
    return stable_hash(
        {
            "schema_version": SCHEMA_VERSION,
            "production_standard_round_trip_cost_bps": PRODUCTION_STANDARD_ROUND_TRIP_COST_BPS,
            "paper_fee_bps": float(AllocationInput.__dataclass_fields__["fee_bps"].default),
            "funding_interval_seconds": FUNDING_INTERVAL_SECONDS,
            "slippage_model": "paper_loop_model_expected_slippage_bps_equivalent",
            "depth_model": "runtime_depth_price_impact_else_orderbook_depth_notional_utilization",
        }
    )


def estimate_production_cost(
    row: Mapping[str, Any],
    *,
    side: str = "long",
    order_notional_usd: float | None = None,
    holding_period_seconds: int = DEFAULT_HOLDING_PERIOD_SECONDS,
) -> ProductionCostBreakdown:
    normalized_side = str(side or "").lower()
    if normalized_side not in {"long", "short"}:
        normalized_side = "long"
    notional = _first_float(
        order_notional_usd,
        _field(row, "order_size_usd"),
        _field(row, "order_notional_usd"),
        _field(row, "notional_usd"),
        _field(row, "target_notional_usdt"),
        _field(row, "gross_notional_usd"),
    )
    spread = _derived_spread_bps(row)
    fallback_components: set[str] = set()
    sources: dict[str, str] = {}
    if spread is None:
        spread_component = 0.0
        fallback_components.add("observed_bid_ask_spread_bps")
        sources["observed_bid_ask_spread_bps"] = "MISSING_OBSERVED_SPREAD_AT_DECISION_TIME"
    else:
        spread_component = spread
        sources["observed_bid_ask_spread_bps"] = "OBSERVED_OR_DERIVED_BID_ASK_SPREAD_BPS"

    depth_impact, depth_source, depth_fallback = _depth_impact_bps(
        row,
        side=normalized_side,
        order_notional_usd=notional,
        spread_bps=spread,
    )
    if depth_fallback:
        fallback_components.add("depth_impact_bps")
    sources["depth_impact_bps"] = depth_source

    fee, fee_source, fee_fallback = _fee_bps(row)
    if fee_fallback:
        fallback_components.add("fee_bps")
    sources["fee_bps"] = fee_source
    if _first_float(_field(row, "maker_probability")) is None or _first_float(_field(row, "taker_probability")) is None:
        fallback_components.add("maker_taker_probability")
        sources["maker_taker_probability"] = "MISSING_MAKER_TAKER_PROBABILITY_EVIDENCE"
    else:
        sources["maker_taker_probability"] = "MAKER_TAKER_PROBABILITY_AT_DECISION_TIME"

    slippage_direct = _first_float(
        _field(row, "expected_slippage_bps"),
        _field(row, "actual_observed_slippage_bps"),
        _field(row, "actual_slippage_bps"),
        _field(row, "realized_slippage_bps"),
        _field(row, "slippage_bps"),
        _field(row, "estimated_slippage_bps"),
    )
    if slippage_direct is not None:
        slippage = abs(slippage_direct)
        sources["slippage_bps"] = "OBSERVED_OR_UPSTREAM_MODELED_SLIPPAGE_BPS"
    elif spread is not None:
        volatility = _first_float(_field(row, "volatility_bps"), _field(row, "atr_bps"))
        liquidity = _first_float(_field(row, "liquidity_score"), _field(row, "allocator_liquidity_score"))
        slippage = _modeled_slippage_bps(
            spread_bps=spread,
            volatility_bps=volatility,
            liquidity_score=liquidity,
        )
        sources["slippage_bps"] = "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY"
    else:
        slippage = 0.0
        fallback_components.add("slippage_bps")
        sources["slippage_bps"] = "MISSING_OBSERVED_OR_MODELED_SLIPPAGE_AT_DECISION_TIME"

    funding, funding_source, funding_fallback = _funding_bps(row, holding_period_seconds=holding_period_seconds)
    if funding_fallback:
        fallback_components.add("funding_bps")
    sources["funding_bps"] = funding_source

    latency, latency_source, latency_fallback = _latency_reserve_bps(row)
    if latency_fallback:
        fallback_components.add("latency_reserve_bps")
    sources["latency_reserve_bps"] = latency_source

    partial, partial_source, partial_fallback = _partial_fill_adjustment_bps(row, spread_bps=spread)
    if partial_fallback:
        fallback_components.add("partial_fill_adjustment_bps")
    sources["partial_fill_adjustment_bps"] = partial_source

    mark_index, mark_source, mark_fallback = _mark_index_divergence_bps(row)
    if mark_fallback:
        fallback_components.add("mark_index_divergence_bps")
    sources["mark_index_divergence_bps"] = mark_source

    component_sum = (
        spread_component
        + depth_impact
        + abs(fee)
        + abs(slippage)
        + abs(funding)
        + abs(latency)
        + abs(partial)
        + abs(mark_index)
    )
    reserve = max(0.0, PRODUCTION_STANDARD_ROUND_TRIP_COST_BPS - component_sum)
    total = round(component_sum + reserve, 8)
    fallback = bool(fallback_components)
    return ProductionCostBreakdown(
        observed_bid_ask_spread_bps=round(spread, 8) if spread is not None else None,
        depth_impact_bps=round(depth_impact, 8),
        fee_bps=round(abs(fee), 8),
        slippage_bps=round(abs(slippage), 8),
        funding_bps=round(funding, 8),
        latency_reserve_bps=round(abs(latency), 8),
        partial_fill_adjustment_bps=round(abs(partial), 8),
        mark_index_divergence_bps=round(abs(mark_index), 8),
        production_standard_reserve_bps=round(reserve, 8),
        total_cost_bps=total,
        fallback=fallback,
        fallback_components=tuple(sorted(fallback_components)),
        production_grade_evidence=not fallback,
        component_sources=sources,
        cost_model_hash=cost_model_hash(),
    )


def estimate_replay_cost(row: Mapping[str, Any], **kwargs: Any) -> ProductionCostBreakdown:
    return estimate_production_cost(row, **kwargs)


def estimate_paper_cost(row: Mapping[str, Any], **kwargs: Any) -> ProductionCostBreakdown:
    return estimate_production_cost(row, **kwargs)


def net_return_for_side(gross_return_bps: float, side: str, cost: ProductionCostBreakdown) -> float:
    if str(side or "").lower() == "short":
        return -float(gross_return_bps) - cost.total_cost_bps
    return float(gross_return_bps) - cost.total_cost_bps
