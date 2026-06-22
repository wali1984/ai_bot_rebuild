"""All-timeframe prediction, signal, and price-target publisher.

This service is V2-only and paper/shadow-only. It may read and write
``v2:*`` Redis keys, but it refuses every non-V2 key and never touches an
exchange, live/canary state, leverage, margin, legacy Redis, or Redis trim.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import (
    V2HybridTrainerDataLoader,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.safety import V2OnlyJsonIO
from v2.backend.app.services.v2_symbol_runtime_universe import (
    BASELINE_25_SYMBOLS,
    is_valid_runtime_symbol,
    resolve_symbols_with_provenance,
)
from v2.backend.app.services.live_gate.runtime_execution_state import (
    LIVE_GATE_ENABLED,
    validate_runtime_execution_state,
)
from v2.backend.app.services.market_state_integrity.scoring import score_market_state


SERVICE_ID = "v2_all_timeframe_prediction_signal_price_target_publisher"
GATE_READY = "V2_ALL_SYMBOL_ALL_TIMEFRAME_FEATURE_TRAINER_SIGNAL_GPU_PARITY_READY"
GATE_BLOCKED = "V2_ALL_SYMBOL_ALL_TIMEFRAME_FEATURE_TRAINER_SIGNAL_GPU_PARITY_BLOCKED"
LIVE_GATE = "blocked_human_only"
REQUIRED_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
DEFAULT_STALE_SECONDS = 900
EST = ZoneInfo("America/New_York")
CURRENT_PREDICTION_STATUSES = {
    "PRESENT_CURRENT",
    "PRESENT_CURRENT_RL_CORE_SIDECAR_NOT_CUDA_PARITY",
}
CURRENT_RUNTIME_SIGNAL_STATUSES = CURRENT_PREDICTION_STATUSES | {"CURRENT_RUNTIME_PAPER_SIGNAL"}
PAPER_DIRECTIONAL_COLLAPSE_BLOCK_REASON = "DIRECTIONAL_COLLAPSE_PUBLISHER_PAPER_ACTIONABILITY_BLOCKED"
PAPER_DIRECTIONAL_COLLAPSE_MIN_CURRENT_DIRECTIONAL_ROWS = 50
PAPER_DIRECTIONAL_COLLAPSE_MIN_MAJORITY_SIDE_ROWS = 50
PAPER_DIRECTIONAL_COLLAPSE_MAJOR_SIDE_SHARE = 0.90
DEFAULT_RUNTIME_TRAINER_TRUST_RECONCILIATION_LIMIT = 0

TRAINER_SOURCE_REQUIRED = "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW"
MODEL_SOURCE_REQUIRED = "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA"

REQUIRED_FEATURE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("last_price", "market", "REAL_PROVIDER_VALUE"),
    ("mark_price", "market", "REAL_PROVIDER_VALUE"),
    ("index_price", "market", "REAL_PROVIDER_VALUE"),
    ("basis_pct", "market", "REAL_COMPUTED"),
    ("funding_rate", "market", "REAL_PROVIDER_VALUE"),
    ("open_interest", "market", "REAL_PROVIDER_VALUE"),
    ("oi_change_pct", "market", "REAL_COMPUTED"),
    ("quote_volume", "market", "REAL_PROVIDER_VALUE"),
    ("volume", "ohlcv", "REAL_PROVIDER_VALUE"),
    ("volatility", "market", "REAL_COMPUTED"),
    ("volatility_pct", "market", "REAL_COMPUTED"),
    ("open", "ohlcv", "REAL_PROVIDER_VALUE"),
    ("high", "ohlcv", "REAL_PROVIDER_VALUE"),
    ("low", "ohlcv", "REAL_PROVIDER_VALUE"),
    ("close", "ohlcv", "REAL_PROVIDER_VALUE"),
    ("num_trades", "ohlcv", "REAL_PROVIDER_VALUE"),
    ("taker_buy_base_vol", "ohlcv", "REAL_PROVIDER_VALUE"),
    ("taker_buy_quote_vol", "ohlcv", "REAL_PROVIDER_VALUE"),
    ("taker_sell_base_vol", "ohlcv", "REAL_COMPUTED"),
    ("taker_sell_quote_vol", "ohlcv", "REAL_COMPUTED"),
    ("taker_buy_ratio", "ohlcv", "REAL_COMPUTED"),
    ("taker_sell_ratio", "ohlcv", "REAL_COMPUTED"),
    ("ob_best_bid", "orderbook", "REAL_PROVIDER_VALUE"),
    ("ob_best_ask", "orderbook", "REAL_PROVIDER_VALUE"),
    ("ob_mid_price", "orderbook", "REAL_COMPUTED"),
    ("ob_spread_bps", "orderbook", "REAL_COMPUTED"),
    ("ob_imbalance", "orderbook", "REAL_COMPUTED"),
    ("orderbook_depth_usd", "orderbook", "REAL_COMPUTED"),
    ("depth_total_usd", "orderbook", "REAL_COMPUTED"),
    ("depth_usd", "orderbook", "REAL_COMPUTED"),
    ("depth_vs_tape_divergence", "orderbook", "REAL_COMPUTED"),
    ("RSI", "ta", "REAL_COMPUTED"),
    ("MACD", "ta", "REAL_COMPUTED"),
    ("MACD_signal", "ta", "REAL_COMPUTED"),
    ("MACD_hist", "ta", "REAL_COMPUTED"),
    ("ATR", "ta", "REAL_COMPUTED"),
    ("EMA_12", "ta", "REAL_COMPUTED"),
    ("EMA_26", "ta", "REAL_COMPUTED"),
    ("bollinger_upper", "ta", "REAL_COMPUTED"),
    ("bollinger_middle", "ta", "REAL_COMPUTED"),
    ("bollinger_lower", "ta", "REAL_COMPUTED"),
    ("bollinger_width_pct", "ta", "REAL_COMPUTED"),
    ("liquidation_long_level", "liquidation", "EVENT_DEPENDENT"),
    ("liquidation_short_level", "liquidation", "EVENT_DEPENDENT"),
    ("liquidation_distance_pct", "liquidation", "EVENT_DEPENDENT"),
    ("liquidation_strength", "liquidation", "EVENT_DEPENDENT"),
    ("last_liq_bps_24h", "liquidation", "EVENT_DEPENDENT"),
    ("liquidation_is_stale", "liquidation", "EVENT_DEPENDENT"),
    ("microprice", "microstructure", "REAL_COMPUTED"),
    ("spread", "microstructure", "REAL_COMPUTED"),
    ("micro_volatility", "microstructure", "REAL_COMPUTED"),
    ("toxicity_proxy", "microstructure", "REAL_COMPUTED"),
    ("tape_imbalance", "microstructure", "EVENT_DEPENDENT"),
    ("order_flow_imbalance", "microstructure", "EVENT_DEPENDENT"),
    ("public_intel_score", "altdata", "REAL_PROVIDER_VALUE"),
    ("nansen_score", "altdata", "PROVIDER_BLOCKED"),
    ("lunarcrush_score", "altdata", "PROVIDER_BLOCKED"),
    ("aicoin_score", "altdata", "PROVIDER_BLOCKED"),
    ("whale_wall_score", "altdata", "EVENT_DEPENDENT"),
    ("coingecko_score", "altdata", "PROVIDER_BLOCKED"),
    ("surf_score", "altdata", "PROVIDER_BLOCKED"),
    ("defillama_score", "altdata", "PROVIDER_BLOCKED"),
    ("fear_greed_context", "altdata", "PROVIDER_BLOCKED"),
    ("mempool_context", "altdata", "PROVIDER_BLOCKED"),
)


def est_now() -> str:
    return dt.datetime.now(tz=EST).isoformat(timespec="seconds")


def parse_ts(value: Any) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=EST)
    return parsed.astimezone(dt.timezone.utc)


def to_est(value: Any) -> str | None:
    parsed = parse_ts(value)
    if parsed is None:
        return None
    return parsed.astimezone(EST).isoformat(timespec="seconds")


def freshness_seconds(value: Any) -> int | None:
    parsed = parse_ts(value)
    if parsed is None:
        return None
    return max(0, int((dt.datetime.now(dt.timezone.utc) - parsed).total_seconds()))


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _live_context_from_store(store: "V2KeyValueStore") -> dict[str, Any]:
    payload = store.get_json("v2:live_gate:state") or {}
    validation = validate_runtime_execution_state(payload)
    if validation.get("valid") and payload.get("live_gate") == LIVE_GATE_ENABLED:
        return {
            "live_gate": LIVE_GATE_ENABLED,
            "live_symbols": [str(symbol) for symbol in payload.get("live_symbols") or []],
            "execution_live_symbols": [str(symbol) for symbol in payload.get("execution_live_symbols") or []],
            "trader_execution_enabled": payload.get("trader_execution_enabled") is True,
            "runtime_validation": validation,
            "source": "v2:live_gate:state",
        }
    return {
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "trader_execution_enabled": False,
        "runtime_validation": validation,
        "source": "v2:live_gate:state" if payload else "missing",
    }


def apply_live_runtime_context(value: Any, context: Mapping[str, Any]) -> Any:
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if key in {"live_gate", "live_symbols", "execution_live_symbols"}:
                value[key] = context.get(key, item)
            else:
                value[key] = apply_live_runtime_context(item, context)
        return value
    if isinstance(value, list):
        for index, item in enumerate(value):
            value[index] = apply_live_runtime_context(item, context)
    return value


def to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


MARKET_COST_EVIDENCE_FIELDS = (
    "actual_observed_spread_entry_bps",
    "expected_slippage_bps",
    "fee_bps",
    "expected_funding_bps",
    "orderbook_depth_usd",
    "market_cost_evidence_status",
    "market_cost_evidence_missing_fields",
    "market_cost_evidence_source_fields",
    "market_cost_evidence_source_lineage",
    "market_cost_evidence_pit_reject_reasons",
)


RUNTIME_PAPER_PIT_CONTEXT_FIELDS = (
    "feature_snapshot_id",
    "entry_feature_snapshot_id",
    "prediction_feature_snapshot_id",
    "available_at",
    "decision_time",
    "decision_time_est",
    "feature_cutoff",
    "masa_feature_cutoff",
    "generated_at",
    "generated_utc",
    "source_available_time",
    "source_event_time_est",
    "feature_available_at",
    "feature_generated_at",
)


RUNTIME_PAPER_MARKET_COST_ALIAS_FIELDS: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    (
        "actual_observed_spread_entry_bps",
        ("actual_observed_spread_entry_bps", "entry_observed_spread_bps", "actual_spread_bps", "entry_spread_bps", "spread_bps"),
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
            "market_depth_usd",
            "depth_usd",
            "depth_total_usd",
            "available_depth_usd",
            "top_of_book_depth_usd",
        ),
        True,
    ),
)


def _first_numeric_field(mapping: Mapping[str, Any], fields: tuple[str, ...]) -> tuple[float | None, str | None]:
    for field in fields:
        value = to_float(mapping.get(field))
        if value is not None:
            return value, field
    return None, None


def _present(value: Any) -> bool:
    return value is not None and value != ""


def _first_present_source_field(
    sources: tuple[tuple[str, Mapping[str, Any]], ...],
    field: str,
) -> tuple[Any, str | None]:
    for label, source in sources:
        if field in source and _present(source.get(field)):
            return source.get(field), f"{label}.{field}"
    return None, None


def _runtime_paper_pit_context_fields(
    sources: tuple[tuple[str, Mapping[str, Any]], ...],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    source_fields: dict[str, str] = {}
    for field in RUNTIME_PAPER_PIT_CONTEXT_FIELDS:
        value, source = _first_present_source_field(sources, field)
        if source is None:
            continue
        out[field] = value
        source_fields[field] = source
    if source_fields:
        out["runtime_paper_pit_context_source_fields"] = source_fields
    return out


def _runtime_market_cost_source_field(source: Mapping[str, Any], target: str, fallback: str) -> str:
    source_fields = source.get("market_cost_evidence_source_fields")
    if isinstance(source_fields, Mapping):
        explicit = source_fields.get(target)
        if _present(explicit):
            return str(explicit)
    return fallback


def _runtime_paper_market_cost_evidence_fields(
    sources: tuple[tuple[str, Mapping[str, Any]], ...],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    source_fields: dict[str, str] = {}
    for target, aliases, positive_only in RUNTIME_PAPER_MARKET_COST_ALIAS_FIELDS:
        for label, source in sources:
            value, field = _first_numeric_field(source, aliases)
            if value is None or field is None:
                continue
            normalized = abs(value)
            if positive_only and normalized <= 0.0:
                continue
            out[target] = normalized
            source_fields[target] = _runtime_market_cost_source_field(source, target, f"{label}.{field}")
            break

    if not source_fields:
        return out

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

    reject_reasons, reject_source = _first_present_source_field(sources, "market_cost_evidence_pit_reject_reasons")
    lineage, lineage_source = _first_present_source_field(sources, "market_cost_evidence_source_lineage")
    out["market_cost_evidence_status"] = (
        "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE" if not missing_fields else "PARTIAL_EXPLICIT_MARKET_COST_EVIDENCE"
    )
    out["market_cost_evidence_missing_fields"] = missing_fields
    out["market_cost_evidence_source_fields"] = source_fields
    out["market_cost_evidence_pit_reject_reasons"] = reject_reasons if reject_source else []
    out["market_cost_evidence_source_lineage"] = lineage if lineage_source else {
        "source": "runtime_paper_signal_payload_fields",
        "source_fields": source_fields,
    }
    return out


def _feature_time_payload(value: Mapping[str, Any]) -> dict[str, Any]:
    features = as_dict(value.get("features"))
    return {**value, **features}


def _feature_payload_market_cost_reject_reasons(
    *,
    prediction: Mapping[str, Any],
    feature_payload: Mapping[str, Any] | None,
) -> list[str]:
    if not isinstance(feature_payload, Mapping):
        return ["MISSING_FEATURE_PAYLOAD_FOR_MARKET_COST_EVIDENCE"]
    reasons: list[str] = []
    prediction_snapshot_id = prediction.get("feature_snapshot_id")
    feature_snapshot_id = feature_payload.get("feature_snapshot_id")
    if prediction_snapshot_id and feature_snapshot_id and str(prediction_snapshot_id) != str(feature_snapshot_id):
        reasons.append("FEATURE_SNAPSHOT_MISMATCH_FOR_MARKET_COST_EVIDENCE")
    decision_time = parse_ts(
        prediction.get("decision_time")
        or prediction.get("decision_time_est")
        or prediction.get("available_at")
        or prediction.get("generated_at")
        or prediction.get("generated_est")
    )
    if decision_time is None:
        reasons.append("MISSING_DECISION_TIME_FOR_MARKET_COST_EVIDENCE")
    source_times = {
        "feature_available_at": (
            feature_payload.get("available_at")
            or feature_payload.get("feature_available_at")
            or feature_payload.get("source_available_time")
        ),
        "feature_generated_at": (
            feature_payload.get("generated_at")
            or feature_payload.get("generated_utc")
            or feature_payload.get("feature_generated_at")
        ),
        "feature_cutoff": (
            feature_payload.get("feature_cutoff")
            or feature_payload.get("source_event_time_est")
            or feature_payload.get("candle_close_time")
        ),
    }
    if not source_times["feature_available_at"]:
        reasons.append("MISSING_FEATURE_AVAILABLE_AT_FOR_MARKET_COST_EVIDENCE")
    for label, value in source_times.items():
        if not value:
            continue
        parsed = parse_ts(value)
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
    value = abs(value)
    if positive_only and value <= 0.0:
        return
    out[field] = value
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


def _coinapi_book_depth_usd(
    *,
    prediction: Mapping[str, Any],
    feature_sources: Mapping[str, Any],
) -> tuple[float | None, str | None]:
    def side_depth(
        quantity_fields: tuple[str, ...],
        price_fields: tuple[str, ...],
    ) -> tuple[float | None, str | None]:
        quantity, quantity_field = _first_numeric_field(feature_sources, quantity_fields)
        if quantity is None or quantity <= 0.0 or not quantity_field:
            return None, None
        price, price_field = _first_numeric_field(feature_sources, price_fields)
        if price is None or price <= 0.0 or not price_field:
            return None, None
        return quantity * price, f"{quantity_field}*{price_field}"

    bid_depth, bid_source = side_depth(
        ("coinapi_book_bid_sum_5", "book_bid_sum_5"),
        ("coinapi_best_bid_px", "best_bid_px", "best_bid", "bid_px", "bid"),
    )
    ask_depth, ask_source = side_depth(
        ("coinapi_book_ask_sum_5", "book_ask_sum_5"),
        ("coinapi_best_ask_px", "best_ask_px", "best_ask", "ask_px", "ask"),
    )
    action = str(
        prediction.get("selected_action")
        or as_dict(prediction.get("raw_output")).get("side")
        or prediction.get("side")
        or prediction.get("action")
        or ""
    ).strip().lower()
    if action in {"long", "buy"}:
        return ask_depth, ask_source
    if action in {"short", "sell"}:
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


def _modeled_feature_slippage_bps(
    feature_sources: Mapping[str, Any],
) -> tuple[float | None, str | None]:
    spread_bps, spread_field = _first_numeric_field(
        feature_sources,
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
    volatility_bps, volatility_field = _first_numeric_field(
        feature_sources,
        (
            "volatility_bps",
            "micro_volatility_bps",
            "realized_volatility_bps",
            "atr_bps",
            "ATR_bps",
        ),
    )
    liquidity_score, liquidity_field = _first_numeric_field(
        feature_sources,
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


def build_market_cost_evidence_enrichment(
    *,
    prediction: Mapping[str, Any],
    feature_payload: Mapping[str, Any] | None,
    feature_source_key: str,
) -> dict[str, Any]:
    """Extract point-in-time market cost evidence without fabricating fee data."""
    out: dict[str, Any] = {}
    sources: dict[str, str] = {}
    prediction_sources = as_dict(prediction)
    feature_reject_reasons = _feature_payload_market_cost_reject_reasons(
        prediction=prediction,
        feature_payload=feature_payload,
    )
    feature_sources = _feature_time_payload(feature_payload) if not feature_reject_reasons and isinstance(feature_payload, Mapping) else {}

    direct_groups: tuple[tuple[str, tuple[str, ...], bool], ...] = (
        (
            "actual_observed_spread_entry_bps",
            ("actual_observed_spread_entry_bps", "actual_spread_bps", "entry_spread_bps", "spread_bps"),
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
                "market_depth_usd",
                "depth_usd",
                "depth_total_usd",
                "available_depth_usd",
                "top_of_book_depth_usd",
            ),
            True,
        ),
    )
    for target, fields, positive_only in direct_groups:
        value, source_field = _first_numeric_field(prediction_sources, fields)
        _set_market_cost_value(
            out,
            sources,
            target,
            value,
            f"prediction.{source_field}" if source_field else None,
            positive_only=positive_only,
        )

    if feature_sources:
        feature_groups: tuple[tuple[str, tuple[str, ...], bool], ...] = (
            (
                "actual_observed_spread_entry_bps",
                ("actual_observed_spread_entry_bps", "bid_ask_spread_bps", "ob_spread_bps", "orderbook_spread_bps", "spread_bps"),
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
                    "market_depth_usd",
                    "depth_usd",
                    "depth_total_usd",
                    "available_depth_usd",
                    "top_of_book_depth_usd",
                ),
                True,
            ),
        )
        for target, fields, positive_only in feature_groups:
            value, source_field = _first_numeric_field(feature_sources, fields)
            _set_market_cost_value(
                out,
                sources,
                target,
                value,
                f"{feature_source_key}.{source_field}" if source_field else None,
                positive_only=positive_only,
            )
        if "fee_bps" not in out:
            fee_rate, source_field = _first_numeric_field(
                feature_sources,
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
                f"{feature_source_key}.{source_field}" if source_field else None,
            )
        if "orderbook_depth_usd" not in out:
            depth_usd, depth_source = _coinapi_book_depth_usd(
                prediction=prediction,
                feature_sources=feature_sources,
            )
            _set_market_cost_value(
                out,
                sources,
                "orderbook_depth_usd",
                depth_usd,
                f"{feature_source_key}.{depth_source}" if depth_source else None,
                positive_only=True,
            )
        if "expected_funding_bps" not in out:
            funding_rate, source_field = _first_numeric_field(
                feature_sources,
                ("funding_rate", "expected_funding_rate", "actual_funding_rate"),
            )
            if funding_rate is not None and source_field:
                _set_market_cost_rate_as_bps(
                    out,
                    sources,
                    "expected_funding_bps",
                    funding_rate,
                    f"{feature_source_key}.{source_field}",
                )
        if "expected_slippage_bps" not in out:
            modeled_slippage_bps, source_field = _modeled_feature_slippage_bps(feature_sources)
            _set_market_cost_value(
                out,
                sources,
                "expected_slippage_bps",
                modeled_slippage_bps,
                f"{feature_source_key}.{source_field}" if source_field else None,
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

    out["market_cost_evidence_status"] = (
        "COMPLETE_EXPLICIT_MARKET_COST_EVIDENCE" if not missing_fields else "PARTIAL_EXPLICIT_MARKET_COST_EVIDENCE"
    )
    out["market_cost_evidence_missing_fields"] = missing_fields
    out["market_cost_evidence_source_fields"] = sources
    out["market_cost_evidence_pit_reject_reasons"] = feature_reject_reasons
    out["market_cost_evidence_source_lineage"] = {
        "source": "prediction_and_pit_feature_payload_fields_with_modeled_slippage_from_pit_spread",
        "feature_source_key": feature_source_key,
        "feature_snapshot_id": feature_payload.get("feature_snapshot_id") if isinstance(feature_payload, Mapping) else None,
        "feature_available_at": feature_payload.get("available_at") if isinstance(feature_payload, Mapping) else None,
        "feature_generated_at": (
            feature_payload.get("generated_at") or feature_payload.get("generated_utc")
            if isinstance(feature_payload, Mapping)
            else None
        ),
        "prediction_id": prediction.get("prediction_id"),
        "prediction_decision_time": prediction.get("decision_time") or prediction.get("decision_time_est"),
        "pit_guard_reject_reasons": feature_reject_reasons,
    }
    return out


def read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def rel(repo_root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def prediction_key(symbol: str, timeframe: str) -> str:
    return f"v2:prediction:{symbol}:{timeframe}"


def prediction_rl_core_key(symbol: str, timeframe: str) -> str:
    return f"v2:prediction:rl_core:{symbol}:{timeframe}"


def signal_paper_key(symbol: str, timeframe: str) -> str:
    return f"v2:signals:paper:{symbol}:{timeframe}"


def signal_latest_key(symbol: str) -> str:
    return f"v2:signals:latest:{symbol}"


def feature_latest_key(symbol: str, timeframe: str) -> str:
    return f"v2:features:latest:{symbol}:{timeframe}"


def feature_snapshot_key(feature_snapshot_id: Any) -> str:
    return f"v2:features:snapshot:{feature_snapshot_id}"


def market_state_integrity_key(symbol: str, timeframe: str) -> str:
    return f"v2:market_state_integrity:{symbol}:{timeframe}"


def price_key(symbol: str) -> str:
    return f"v2:market:prices:{symbol}"


def stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def strings(value: Any) -> list[str]:
    if isinstance(value, str):
        values: Iterable[Any] = [value]
    elif isinstance(value, list):
        values = value
    else:
        return []
    out: list[str] = []
    for item in values:
        if isinstance(item, dict):
            item = item.get("symbol") or item.get("canonical_symbol_id") or item.get("legacy_symbol")
        text = str(item or "").strip().upper()
        if text and is_valid_runtime_symbol(text):
            out.append(text)
    return sorted(set(out))


def extract_symbols(symbol_payloads: Iterable[Mapping[str, Any]], fallback: Iterable[str] = ()) -> list[str]:
    for payload in symbol_payloads:
        for field in (
            "training_symbols",
            "paper_symbols",
            "dynamic_discovered_symbols",
            "tradable_symbols",
            "symbols",
        ):
            symbols = strings(payload.get(field))
            if symbols:
                return symbols
    return sorted(set(str(item).upper() for item in fallback if str(item or "").strip()))


def timestamp_field(payload: Mapping[str, Any]) -> Any:
    return (
        payload.get("generated_utc")
        or payload.get("generated_at")
        or payload.get("generated_est")
        or payload.get("last_run_ts")
        or payload.get("fetched_utc")
        or payload.get("heartbeat_at")
    )


def prediction_timestamp_field(payload: Mapping[str, Any]) -> tuple[Any, str | None]:
    for field in (
        "generated_utc",
        "generated_at",
        "generated_est",
        "available_at",
        "decision_time",
        "decision_time_est",
        "decision_cutoff_time_est",
    ):
        value = payload.get(field)
        if value:
            return value, field
    return None, None


def prediction_temporal_block_reasons(prediction: Mapping[str, Any]) -> list[str]:
    decision_time = parse_ts(
        prediction.get("decision_time")
        or prediction.get("decision_time_est")
        or prediction.get("decision_cutoff_time_est")
    )
    available_at = parse_ts(prediction.get("available_at"))
    feature_cutoff = parse_ts(prediction.get("feature_cutoff"))
    masa_feature_cutoff = parse_ts(prediction.get("masa_feature_cutoff"))
    blockers: list[str] = []
    if available_at is not None and decision_time is not None and available_at > decision_time:
        blockers.append("PREDICTION_AVAILABLE_AT_AFTER_DECISION_TIME")
    if feature_cutoff is not None and decision_time is not None and feature_cutoff > decision_time:
        blockers.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if masa_feature_cutoff is not None and decision_time is not None and masa_feature_cutoff > decision_time:
        blockers.append("MASA_FEATURE_CUTOFF_AFTER_PPO_DECISION_TIME")
    return blockers


def source_for_expected_move(prediction: Mapping[str, Any]) -> str:
    explicit = prediction.get("expected_move_source")
    if explicit:
        return str(explicit)
    source = str(prediction.get("trainer_source") or prediction.get("model_source") or "").upper()
    if prediction.get("cuda_active") is True or "CUDA" in source:
        return "CUDA_TRAINER_HEAD"
    if "RL_CORE" in source or "LOCAL_TRAINED" in source:
        return "CALIBRATED_MODEL_OUTPUT"
    if "STRATEGY" in source:
        return "STRATEGY_FALLBACK_LABELLED"
    return "missing"


def action_probability_map(prediction: Mapping[str, Any]) -> dict[str, float] | None:
    raw = prediction.get("action_probabilities")
    if raw is None:
        raw = prediction.get("policy_action_probabilities")
    if isinstance(raw, dict):
        return {str(k): float(v) for k, v in raw.items() if to_float(v) is not None}
    if not isinstance(raw, list):
        return None
    labels = prediction.get("action_labels")
    if not isinstance(labels, list) or len(labels) != len(raw):
        labels = ["hold", "long", "short", "close", "hedge_reserved_fail_closed"][: len(raw)]
    out: dict[str, float] = {}
    for label, value in zip(labels, raw):
        numeric = to_float(value)
        if numeric is not None:
            out[str(label)] = numeric
    return out or None


def selected_action_index(prediction: Mapping[str, Any], action: str) -> int | None:
    idx = prediction.get("selected_action_index")
    if isinstance(idx, int):
        return idx
    labels = prediction.get("action_labels")
    if isinstance(labels, list) and action in labels:
        return labels.index(action)
    return {"hold": 0, "long": 1, "short": 2}.get(action)


def extract_last_price(price_payload: Mapping[str, Any]) -> tuple[float | None, str | None]:
    ticker = as_dict(price_payload.get("ticker_24hr"))
    funding = as_dict(price_payload.get("funding"))
    candidates = (
        (ticker.get("lastPrice"), "ticker_24hr.lastPrice"),
        (funding.get("markPrice"), "funding.markPrice"),
        (price_payload.get("last_price"), "last_price"),
        (price_payload.get("price"), "price"),
        (price_payload.get("mark_price"), "mark_price"),
        (price_payload.get("mid_px"), "mid_px"),
        (price_payload.get("microprice"), "microprice"),
        (price_payload.get("close"), "close"),
    )
    for value, field_name in candidates:
        numeric = to_float(value)
        if numeric is not None:
            return numeric, field_name
    return None, None


def market_price_payload(store: "V2KeyValueStore", symbol: str) -> dict[str, Any]:
    primary = as_dict(store.get_json(price_key(symbol)) or {})
    if extract_last_price(primary)[0] is not None:
        return primary
    for key in (
        f"v2:market:coinapi:wsds:{symbol}",
        f"v2:features:microfeat:{symbol}:1m",
        f"v2:features:latest:{symbol}:1m",
        f"v2:unified_features:{symbol}:1m",
    ):
        payload = as_dict(store.get_json(key) or {})
        if extract_last_price(payload)[0] is not None:
            out = dict(payload)
            out.setdefault("source", key)
            return out
    closed_ohlcv = store.get_value(f"v2:market:ohlcv_closed:binance:{symbol}:1m")
    if isinstance(closed_ohlcv, list) and closed_ohlcv:
        for last in reversed(closed_ohlcv):
            if not isinstance(last, dict):
                continue
            if (
                last.get("candle_closed_confirmed") is not True
                and last.get("closed_candle") is not True
                and last.get("is_closed") is not True
            ):
                continue
            close = to_float(last.get("close"))
            if close is not None:
                return {
                    "price": close,
                    "close": close,
                    "source": f"v2:market:ohlcv_closed:binance:{symbol}:1m",
                    "price_finality": "closed_candle",
                    "candle_close_time": last.get("candle_close_time") or last.get("close_time"),
                    "available_at": last.get("available_at"),
                }
    ohlcv = store.get_value(f"v2:market:ohlcv:binance:{symbol}:1m")
    if isinstance(ohlcv, list) and ohlcv:
        last = ohlcv[-1]
        if isinstance(last, list) and len(last) >= 5:
            close = to_float(last[4])
            if close is not None:
                return {"price": close, "source": f"v2:market:ohlcv:binance:{symbol}:1m", "ohlcv_close_index": 4}
    return primary


def price_targets(last_price: float | None, expected_move: float | None, expected_after_cost: float | None, action: str) -> dict[str, Any]:
    formula = "price_target = last_price * (1 + expected_move_bps / 10000)"
    after_formula = "price_target_after_cost = last_price * (1 + expected_move_after_cost_bps / 10000)"
    if last_price is None:
        return {
            "price_target": None,
            "price_target_after_cost": None,
            "price_target_low": None,
            "price_target_high": None,
            "stop_reference": None,
            "take_profit_reference": None,
            "formula": formula,
            "after_cost_formula": after_formula,
            "validation_status": "MISSING_LAST_PRICE",
        }
    if expected_move is None:
        return {
            "price_target": None,
            "price_target_after_cost": None,
            "price_target_low": None,
            "price_target_high": None,
            "stop_reference": None,
            "take_profit_reference": None,
            "formula": formula,
            "after_cost_formula": after_formula,
            "validation_status": "MISSING_EXPECTED_MOVE_BPS",
        }
    target = last_price * (1 + expected_move / 10000)
    after_target = None if expected_after_cost is None else last_price * (1 + expected_after_cost / 10000)
    normalized = action.lower()
    target_points = [last_price, target]
    if after_target is not None:
        target_points.append(after_target)
    stop_reference = None
    take_profit_reference = None
    if normalized == "hold" or "hedge" in normalized or "reduce" in normalized or "close" in normalized:
        side_status = "HOLD_REFERENCE_ONLY"
    elif "long" in normalized:
        side_status = "VALID" if target >= last_price else "TARGET_SIDE_MISMATCH"
        take_profit_reference = target if side_status == "VALID" else None
        stop_reference = last_price * (1 - abs(expected_move) / 10000)
    elif "short" in normalized:
        side_status = "VALID" if target <= last_price else "TARGET_SIDE_MISMATCH"
        take_profit_reference = target if side_status == "VALID" else None
        stop_reference = last_price * (1 + abs(expected_move) / 10000)
    else:
        side_status = "UNKNOWN_ACTION_REFERENCE_ONLY"
    return {
        "price_target": round(target, 12),
        "price_target_after_cost": None if after_target is None else round(after_target, 12),
        "price_target_low": round(min(target_points), 12),
        "price_target_high": round(max(target_points), 12),
        "stop_reference": None if stop_reference is None else round(stop_reference, 12),
        "take_profit_reference": None if take_profit_reference is None else round(take_profit_reference, 12),
        "formula": formula,
        "after_cost_formula": after_formula,
        "validation_status": side_status,
    }


@dataclass
class StoreAudit:
    connected: bool = False
    reads_attempted: int = 0
    reads_succeeded: int = 0
    writes_attempted: int = 0
    writes_succeeded: int = 0
    writes_failed: int = 0
    old_redis_write_attempts: int = 0
    keys_written: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class V2KeyValueStore:
    def __init__(self, client: Any = None) -> None:
        self.client = client
        self.audit = StoreAudit(connected=client is not None)

    def get_json(self, key: str) -> dict[str, Any] | None:
        if not key.startswith("v2:"):
            raise ValueError(f"non_v2_read_rejected:{key}")
        self.audit.reads_attempted += 1
        if self.client is None:
            return None
        try:
            raw = self.client.get(key)
        except Exception as exc:  # noqa: BLE001
            self.audit.errors.append(f"get_failed:{key}:{type(exc).__name__}")
            return None
        if raw is None:
            return None
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        try:
            body = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if isinstance(body, dict):
            self.audit.reads_succeeded += 1
            return body
        return None

    def get_value(self, key: str) -> Any | None:
        if not key.startswith("v2:"):
            raise ValueError(f"non_v2_read_rejected:{key}")
        self.audit.reads_attempted += 1
        if self.client is None:
            return None
        try:
            raw = self.client.get(key)
        except Exception as exc:  # noqa: BLE001
            self.audit.errors.append(f"get_failed:{key}:{type(exc).__name__}")
            return None
        if raw is None:
            return None
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        try:
            body = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if isinstance(body, (dict, list)):
            self.audit.reads_succeeded += 1
            return body
        return None

    def set_json(self, key: str, payload: Mapping[str, Any]) -> bool:
        self.audit.writes_attempted += 1
        if not key.startswith("v2:"):
            self.audit.old_redis_write_attempts += 1
            self.audit.writes_failed += 1
            self.audit.errors.append(f"blocked_non_v2_key:{key}")
            return False
        if self.client is None:
            self.audit.writes_failed += 1
            self.audit.errors.append(f"no_client:{key}")
            return False
        try:
            self.client.set(key, json.dumps(payload, sort_keys=True, default=str))
        except Exception as exc:  # noqa: BLE001
            self.audit.writes_failed += 1
            self.audit.errors.append(f"set_failed:{key}:{type(exc).__name__}")
            return False
        self.audit.writes_succeeded += 1
        self.audit.keys_written.append(key)
        return True


@dataclass(frozen=True)
class PublisherPaths:
    repo_root: Path
    worklog_dir: Path
    public_dir: Path
    signal_public_dir: Path
    signal_local_dir: Path
    symbol_universe_path: Path
    dynamic_symbol_path: Path


def default_paths(repo_root: Path) -> PublisherPaths:
    return PublisherPaths(
        repo_root=repo_root,
        worklog_dir=repo_root / "claude_worklog/final_readiness/v2_all_timeframe_prediction_signal_price_target_publisher/latest",
        public_dir=repo_root / "v2/frontend/public/v2_all_timeframe_prediction_signal_price_target_publisher/latest",
        signal_public_dir=repo_root / "v2/frontend/public/operator_runtime/v2_signals/latest",
        signal_local_dir=repo_root / "v2/runtime/v2_signals/latest",
        symbol_universe_path=repo_root / "v2/frontend/public/operator_runtime/symbol_universe/latest/symbol_universe_status.json",
        dynamic_symbol_path=repo_root / "v2/frontend/public/operator_runtime/v2_dynamic_symbol_discovery/latest/dynamic_symbol_discovery_status.json",
    )


def build_blocker_row(symbol: str, timeframe: str, reason: str) -> dict[str, Any]:
    task = (
        f"Generate {prediction_key(symbol, timeframe)} from CUDA/RL inference or a labelled, "
        "validated fallback with expected_move_bps, expected_move_after_cost_bps, and feature lineage."
    )
    return {
        "prediction_id": None,
        "prediction_redis_key": prediction_key(symbol, timeframe),
        "generated_est": est_now(),
        "symbol": symbol,
        "timeframe": timeframe,
        "status": "MISSING_TF_PREDICTION",
        "trainer_source": "missing source",
        "model_source": "missing source",
        "selected_action": None,
        "selected_action_index": None,
        "action_probabilities": None,
        "confidence_raw": None,
        "confidence_calibrated": None,
        "expected_move_bps": None,
        "expected_move_after_cost_bps": None,
        "policy_value": None,
        "masa_signal": None,
        "last_price": None,
        "price_target": None,
        "price_target_after_cost": None,
        "price_target_low": None,
        "price_target_high": None,
        "stop_reference": None,
        "take_profit_reference": None,
        "feature_snapshot_id": None,
        "data_coverage_percent": 0.0,
        "missing_feature_count": None,
        "stale_feature_count": None,
        "freshness_seconds": None,
        "missing_stale_reason": reason,
        "implementation_task": task,
        "source_lineage": {
            "required_prediction_key": prediction_key(symbol, timeframe),
            "exact_blocker": reason,
            "remediation_task": task,
        },
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
    }


def blocker_redis_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "v2_missing_timeframe_prediction_blocker_v1",
        "status": row["status"],
        "prediction_id": None,
        "generated_est": row["generated_est"],
        "symbol": row["symbol"],
        "timeframe": row["timeframe"],
        "trainer_source": "missing source",
        "model_source": "missing source",
        "selected_action": None,
        "selected_action_index": None,
        "action_probabilities": None,
        "confidence_raw": None,
        "confidence_calibrated": None,
        "expected_move_bps": None,
        "expected_move_after_cost_bps": None,
        "policy_value": None,
        "masa_signal": None,
        "last_price": None,
        "price_target": None,
        "price_target_after_cost": None,
        "price_target_low": None,
        "price_target_high": None,
        "stop_reference": None,
        "take_profit_reference": None,
        "feature_snapshot_id": None,
        "data_coverage_percent": 0.0,
        "missing_feature_count": None,
        "stale_feature_count": None,
        "source_lineage": row["source_lineage"],
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
    }


def build_prediction_row(
    *,
    symbol: str,
    timeframe: str,
    prediction: Mapping[str, Any],
    price_payload: Mapping[str, Any] | None,
    feature_payload: Mapping[str, Any] | None,
    stale_seconds: int,
    source_prediction_key: str | None = None,
    feature_source_key: str | None = None,
    feature_lookup_status: str | None = None,
) -> dict[str, Any]:
    selected_prediction_key = source_prediction_key or prediction_key(symbol, timeframe)
    selected_feature_key = feature_source_key or feature_latest_key(symbol, timeframe)
    generated, prediction_timestamp_source_field = prediction_timestamp_field(prediction)
    age = freshness_seconds(generated)
    expected_move = to_float(prediction.get("expected_move_bps"))
    expected_after_cost = to_float(prediction.get("expected_move_after_cost_bps"))
    last_price, price_field = extract_last_price(price_payload or {})
    action = str(prediction.get("selected_action") or as_dict(prediction.get("raw_output")).get("side") or "hold")
    target = price_targets(last_price, expected_move, expected_after_cost, action)
    trainer_source = str(prediction.get("trainer_source") or "missing source")
    model_source = str(prediction.get("model_source") or prediction.get("model_id") or prediction.get("checkpoint_id") or "missing source")
    missing_reason = None
    status = "PRESENT_CURRENT"
    temporal_block_reasons = prediction_temporal_block_reasons(prediction)
    if age is None:
        status = "PREDICTION_TIMESTAMP_MISSING"
        missing_reason = "PREDICTION_TIMESTAMP_MISSING"
    elif age > stale_seconds:
        status = "STALE_TF_PREDICTION"
        missing_reason = f"STALE_GT_{stale_seconds}s"
    elif temporal_block_reasons:
        status = "PREDICTION_TEMPORAL_ORDER_INVALID"
        missing_reason = temporal_block_reasons[0]
    elif expected_move is None:
        status = "EXPECTED_MOVE_TELEMETRY_MISSING"
        missing_reason = "EXPECTED_MOVE_TELEMETRY_MISSING"
    elif expected_after_cost is None:
        status = "EXPECTED_MOVE_AFTER_COST_MISSING"
        missing_reason = "EXPECTED_MOVE_AFTER_COST_MISSING"
    elif trainer_source != TRAINER_SOURCE_REQUIRED:
        if (
            timeframe == "1m"
            and selected_prediction_key == prediction_rl_core_key(symbol, timeframe)
            and trainer_source == "V2_NATIVE_RL_CORE"
        ):
            status = "PRESENT_CURRENT_RL_CORE_SIDECAR_NOT_CUDA_PARITY"
            missing_reason = "RL_CORE_SIDECAR_NOT_CUDA_PARITY"
        else:
            status = "TRAINER_SOURCE_NOT_CUDA_PARITY"
            missing_reason = f"EXPECTED_{TRAINER_SOURCE_REQUIRED}_GOT_{trainer_source}"
    elif model_source != MODEL_SOURCE_REQUIRED:
        status = "MODEL_SOURCE_NOT_CUDA_PARITY"
        missing_reason = f"EXPECTED_{MODEL_SOURCE_REQUIRED}_GOT_{model_source}"

    source_lineage = {
        "prediction_redis_key": selected_prediction_key,
        "primary_prediction_redis_key": prediction_key(symbol, timeframe),
        "price_redis_key": price_key(symbol),
        "price_source_field": price_field,
        "prediction_generated_est": to_est(generated),
        "prediction_generated_raw": generated,
        "prediction_timestamp_source_field": prediction_timestamp_source_field,
        "prediction_available_at": prediction.get("available_at"),
        "prediction_decision_time": prediction.get("decision_time") or prediction.get("decision_time_est"),
        "prediction_feature_cutoff": prediction.get("feature_cutoff"),
        "prediction_masa_feature_cutoff": prediction.get("masa_feature_cutoff"),
        "prediction_temporal_block_reasons": temporal_block_reasons,
        "feature_redis_key": selected_feature_key,
        "feature_lookup_status": feature_lookup_status or "FEATURE_LATEST_LOOKUP",
        "expected_move_source": source_for_expected_move(prediction),
        "expected_move_bps_source_field": "v2_prediction.expected_move_bps",
        "expected_move_after_cost_bps_source_field": "v2_prediction.expected_move_after_cost_bps",
        "calibration_source": as_dict(prediction.get("confidence_calibration")).get("calibration_source"),
        "required_trainer_source": TRAINER_SOURCE_REQUIRED,
        "required_model_source": MODEL_SOURCE_REQUIRED,
        "source_parity_label": missing_reason if status == "PRESENT_CURRENT_RL_CORE_SIDECAR_NOT_CUDA_PARITY" else None,
        "exact_blocker": None if status == "PRESENT_CURRENT_RL_CORE_SIDECAR_NOT_CUDA_PARITY" else missing_reason,
    }
    integrity = build_integrity_enrichment(
        symbol=symbol,
        timeframe=timeframe,
        prediction=prediction,
        feature_payload=feature_payload,
        feature_source_key=selected_feature_key,
    )
    source_lineage["market_state_integrity"] = integrity.get("market_state_source_lineage")
    market_cost_evidence = build_market_cost_evidence_enrichment(
        prediction=prediction,
        feature_payload=feature_payload,
        feature_source_key=selected_feature_key,
    )
    source_lineage["market_cost_evidence"] = market_cost_evidence.get("market_cost_evidence_source_lineage")
    paper_gate_block_reasons = as_list(
        prediction.get("paper_fill_gate_block_reasons")
        or prediction.get("paper_fill_block_reasons")
        or prediction.get("block_reasons")
    )
    normalized_action = action.lower()
    signed_edge_positive = (
        expected_after_cost is not None
        and (
            (normalized_action == "short" and expected_after_cost < 0)
            or (normalized_action == "long" and expected_after_cost > 0)
        )
    )
    paper_actionable_order = True
    if normalized_action in {"hold", "hedge_reserved_fail_closed"}:
        paper_actionable_order = False
    elif normalized_action in {"long", "short"} and not signed_edge_positive:
        paper_actionable_order = False
    if not paper_actionable_order:
        paper_gate_block_reasons.append("NON_ACTIONABLE_EXPECTED_MOVE_OR_ACTION")
    if integrity["valid_for_prediction"] is not True:
        paper_gate_block_reasons.append("MARKET_STATE_INVALID_FOR_PREDICTION")
    if integrity["valid_for_paper"] is not True:
        paper_gate_block_reasons.append("MARKET_STATE_INVALID_FOR_PAPER")
    if status not in CURRENT_PREDICTION_STATUSES and missing_reason:
        paper_gate_block_reasons.append(missing_reason)
    paper_gate_block_reasons.extend(temporal_block_reasons)
    paper_gate_block_reasons.extend(str(reason) for reason in integrity["market_state_reject_reasons"])
    paper_gate_block_reasons = sorted(set(reason for reason in paper_gate_block_reasons if reason))
    paper_fill_allowed = (
        prediction.get("paper_fill_allowed") is True
        and status in CURRENT_PREDICTION_STATUSES
        and integrity["valid_for_prediction"] is True
        and integrity["valid_for_paper"] is True
        and paper_actionable_order
        and not temporal_block_reasons
    )
    routes_to_orchestrator = (
        prediction.get("routes_to_orchestrator") is True
        and status in CURRENT_PREDICTION_STATUSES
        and integrity["valid_for_risk"] is True
        and integrity["valid_for_orchestrator"] is True
        and paper_actionable_order
        and not temporal_block_reasons
    )
    return {
        "prediction_id": prediction.get("prediction_id"),
        "prediction_redis_key": selected_prediction_key,
        "primary_prediction_redis_key": prediction_key(symbol, timeframe),
        "generated_est": to_est(generated) or est_now(),
        "prediction_timestamp_source_field": prediction_timestamp_source_field,
        "available_at": prediction.get("available_at"),
        "decision_time": prediction.get("decision_time") or prediction.get("decision_time_est"),
        "feature_cutoff": prediction.get("feature_cutoff"),
        "masa_feature_cutoff": prediction.get("masa_feature_cutoff"),
        "prediction_temporal_block_reasons": temporal_block_reasons,
        "symbol": symbol,
        "timeframe": timeframe,
        "status": status,
        "trainer_source": trainer_source,
        "model_source": model_source,
        "selected_action": action,
        "selected_action_index": selected_action_index(prediction, action),
        "action_probabilities": action_probability_map(prediction),
        "confidence_raw": to_float(prediction.get("confidence_raw")),
        "confidence_calibrated": to_float(prediction.get("confidence_calibrated")),
        "expected_move_bps": expected_move,
        "expected_move_after_cost_bps": expected_after_cost,
        "policy_value": to_float(prediction.get("policy_value")),
        "masa_signal": to_float(prediction.get("masa_signal")),
        "last_price": last_price,
        "feature_snapshot_id": prediction.get("feature_snapshot_id"),
        "data_coverage_percent": to_float(prediction.get("data_coverage_percent")),
        "missing_feature_count": prediction.get("missing_feature_count"),
        "stale_feature_count": prediction.get("stale_feature_count"),
        "missing_feature_names": as_list(prediction.get("missing_feature_names")),
        "stale_feature_names": as_list(prediction.get("stale_feature_names")),
        "paper_fill_allowed": paper_fill_allowed,
        "paper_fill_gate_status": prediction.get("paper_fill_gate_status"),
        "paper_fill_gate_block_reasons": paper_gate_block_reasons,
        "routes_to_orchestrator": routes_to_orchestrator,
        "market_state_id": integrity.get("market_state_id"),
        "market_state_integrity_score": integrity.get("market_state_integrity_score"),
        "valid_for_training": integrity.get("valid_for_training"),
        "valid_for_prediction": integrity.get("valid_for_prediction"),
        "valid_for_risk": integrity.get("valid_for_risk"),
        "valid_for_orchestrator": integrity.get("valid_for_orchestrator"),
        "valid_for_paper": integrity.get("valid_for_paper"),
        "valid_for_live": integrity.get("valid_for_live"),
        "decision_cutoff_time_est": integrity.get("decision_cutoff_time_est"),
        "market_state_reject_reasons": integrity.get("market_state_reject_reasons"),
        "market_state_score_components": integrity.get("market_state_score_components"),
        "market_state_source_lineage": integrity.get("market_state_source_lineage"),
        **market_cost_evidence,
        "freshness_seconds": age,
        "price_target": target["price_target"],
        "price_target_after_cost": target["price_target_after_cost"],
        "price_target_low": target["price_target_low"],
        "price_target_high": target["price_target_high"],
        "stop_reference": target["stop_reference"],
        "take_profit_reference": target["take_profit_reference"],
        "price_target_validation_status": target["validation_status"],
        "missing_stale_reason": missing_reason,
        "implementation_task": None if status in CURRENT_PREDICTION_STATUSES else f"Refresh {selected_prediction_key} and preserve expected-move telemetry.",
        "source_lineage": source_lineage,
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
    }


def select_prediction_payload(
    *,
    store: V2KeyValueStore,
    symbol: str,
    timeframe: str,
    stale_seconds: int,
) -> tuple[dict[str, Any] | None, str]:
    primary_key = prediction_key(symbol, timeframe)
    sidecar_key = prediction_rl_core_key(symbol, timeframe)
    candidates: list[tuple[str, dict[str, Any], int | None]] = []
    for key in (primary_key, sidecar_key):
        pred = store.get_json(key)
        if pred is None or pred.get("status") == "MISSING_TF_PREDICTION":
            continue
        timestamp, _timestamp_source = prediction_timestamp_field(pred)
        candidates.append((key, pred, freshness_seconds(timestamp)))
    if not candidates:
        return None, primary_key
    current = [item for item in candidates if item[2] is not None and item[2] <= stale_seconds]
    if current:
        # The RL-core sidecar is a labelled fallback. A fresh native CUDA
        # prediction is the authoritative row for all timeframes, including 1m.
        def current_priority(item: tuple[str, dict[str, Any], int | None]) -> tuple[int, int]:
            key, payload, age = item
            native_cuda = (
                payload.get("trainer_source") == TRAINER_SOURCE_REQUIRED
                and (
                    payload.get("model_source")
                    or payload.get("model_id")
                    or payload.get("checkpoint_id")
                )
                == MODEL_SOURCE_REQUIRED
            )
            if key == primary_key and native_cuda:
                return (0, age or 0)
            if key == primary_key:
                return (1, age or 0)
            if key == sidecar_key:
                return (2, age or 0)
            return (3, age or 0)

        current.sort(key=current_priority)
        return current[0][1], current[0][0]
    candidates.sort(key=lambda item: item[2] if item[2] is not None else 10**12)
    return candidates[0][1], candidates[0][0]


def _paper_direction(row: Mapping[str, Any]) -> str | None:
    action = str(row.get("selected_action") or row.get("action") or row.get("side") or "").strip().lower()
    return action if action in {"long", "short"} else None


def _is_current_directional_guard_row(row: Mapping[str, Any]) -> bool:
    status = row.get("status")
    source_status = row.get("source_prediction_status")
    return status in CURRENT_RUNTIME_SIGNAL_STATUSES or source_status in CURRENT_RUNTIME_SIGNAL_STATUSES


def paper_directional_collapse_guard_status(
    rows: list[Mapping[str, Any]],
    *,
    min_current_directional_rows: int = PAPER_DIRECTIONAL_COLLAPSE_MIN_CURRENT_DIRECTIONAL_ROWS,
    min_majority_side_rows: int = PAPER_DIRECTIONAL_COLLAPSE_MIN_MAJORITY_SIDE_ROWS,
    major_side_share: float = PAPER_DIRECTIONAL_COLLAPSE_MAJOR_SIDE_SHARE,
) -> dict[str, Any]:
    counts = {"long": 0, "short": 0}
    for row in rows:
        if not _is_current_directional_guard_row(row):
            continue
        direction = _paper_direction(row)
        if direction in counts:
            counts[direction] += 1
    total = counts["long"] + counts["short"]
    majority_side = None
    majority_count = 0
    if total:
        majority_side = "long" if counts["long"] >= counts["short"] else "short"
        majority_count = counts[majority_side]
    minority_side = "short" if majority_side == "long" else "long" if majority_side == "short" else None
    minority_count = counts[minority_side] if minority_side else 0
    share = (majority_count / total) if total else 0.0
    detected = (
        total >= int(min_current_directional_rows)
        and majority_count >= int(min_majority_side_rows)
        and share >= float(major_side_share)
        and minority_count < int(min_majority_side_rows)
    )
    return {
        "enabled": True,
        "paper_only": True,
        "guard": "PAPER_PREDICTION_DIRECTIONAL_COLLAPSE_PUBLISHER_GUARD",
        "block_reason": PAPER_DIRECTIONAL_COLLAPSE_BLOCK_REASON,
        "minimum_current_directional_rows": int(min_current_directional_rows),
        "minimum_majority_side_rows": int(min_majority_side_rows),
        "major_side_share_threshold": float(major_side_share),
        "current_directional_count": total,
        "side_counts": counts,
        "majority_side": majority_side,
        "majority_side_count": majority_count,
        "majority_side_share": share if total else None,
        "minority_side": minority_side,
        "minority_side_count": minority_count,
        "directional_collapse_detected": detected,
        "blocked_paper_actionability_count": 0,
    }


def _closed_trade_rows_from_payload(payload: Any, keys: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    if not keys:
        keys = ("closed_trades", "closed", "closes", "closed_positions", "outcome_labels")
    for key in keys:
        rows = payload.get(key)
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, dict)]
    return []


def _closed_trade_identity(row: Mapping[str, Any]) -> str:
    return str(
        row.get("close_id")
        or row.get("outcome_label_id")
        or row.get("trainer_feedback_id")
        or row.get("position_id")
        or row.get("fill_id")
        or row.get("ledger_row_id")
        or (
            f"{row.get('symbol')}|{row.get('timeframe')}|{row.get('side') or row.get('action')}|"
            f"{row.get('entry_price')}|{row.get('exit_price')}|{row.get('exit_time') or row.get('exit_price_utc')}"
        )
    )


def _closed_trade_rows(store: V2KeyValueStore) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend(_closed_trade_rows_from_payload(store.get_value("v2:paper:closed_trades")))
    rows.extend(
        _closed_trade_rows_from_payload(
            store.get_value("v2:paper:ledger"),
            keys=("closed_trades", "closed", "closes", "closed_positions", "outcome_labels"),
        )
    )
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for row in rows:
        identity = _closed_trade_identity(row)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(row)
    return deduped


def _closed_trade_side(row: Mapping[str, Any]) -> str | None:
    side = str(row.get("side") or row.get("action") or row.get("direction") or "").lower()
    if "long" in side:
        return "long"
    if "short" in side:
        return "short"
    return None


def paper_closed_trade_directional_collapse_guard_status(
    store: V2KeyValueStore,
    *,
    min_closed_directional_rows: int = PAPER_DIRECTIONAL_COLLAPSE_MIN_CURRENT_DIRECTIONAL_ROWS,
    min_majority_side_rows: int = PAPER_DIRECTIONAL_COLLAPSE_MIN_MAJORITY_SIDE_ROWS,
    major_side_share: float = PAPER_DIRECTIONAL_COLLAPSE_MAJOR_SIDE_SHARE,
) -> dict[str, Any]:
    counts = {"long": 0, "short": 0}
    rows = _closed_trade_rows(store)
    for row in rows:
        side = _closed_trade_side(row)
        if side in counts:
            counts[side] += 1
    total = counts["long"] + counts["short"]
    majority_side = None
    majority_count = 0
    if total:
        majority_side = "long" if counts["long"] >= counts["short"] else "short"
        majority_count = counts[majority_side]
    minority_side = "short" if majority_side == "long" else "long" if majority_side == "short" else None
    minority_count = counts[minority_side] if minority_side else 0
    share = (majority_count / total) if total else 0.0
    detected = (
        total >= int(min_closed_directional_rows)
        and majority_count >= int(min_majority_side_rows)
        and share >= float(major_side_share)
        and minority_count < int(min_majority_side_rows)
    )
    return {
        "enabled": True,
        "paper_only": True,
        "guard": "PAPER_CLOSED_TRADE_DIRECTIONAL_COLLAPSE_PUBLISHER_GUARD",
        "block_reason": PAPER_DIRECTIONAL_COLLAPSE_BLOCK_REASON,
        "minimum_closed_directional_rows": int(min_closed_directional_rows),
        "minimum_majority_side_rows": int(min_majority_side_rows),
        "major_side_share_threshold": float(major_side_share),
        "closed_directional_count": total,
        "side_counts": counts,
        "majority_side": majority_side,
        "majority_side_count": majority_count,
        "majority_side_share": share if total else None,
        "minority_side": minority_side,
        "minority_side_count": minority_count,
        "directional_collapse_detected": detected,
        "blocked_paper_actionability_count": 0,
    }


def apply_paper_directional_collapse_guard(
    rows: list[dict[str, Any]],
    *,
    min_current_directional_rows: int = PAPER_DIRECTIONAL_COLLAPSE_MIN_CURRENT_DIRECTIONAL_ROWS,
    min_majority_side_rows: int = PAPER_DIRECTIONAL_COLLAPSE_MIN_MAJORITY_SIDE_ROWS,
    major_side_share: float = PAPER_DIRECTIONAL_COLLAPSE_MAJOR_SIDE_SHARE,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    status = paper_directional_collapse_guard_status(
        rows,
        min_current_directional_rows=min_current_directional_rows,
        min_majority_side_rows=min_majority_side_rows,
        major_side_share=major_side_share,
    )
    if not status["directional_collapse_detected"] or not status["majority_side"]:
        return rows, status
    guarded_rows: list[dict[str, Any]] = []
    blocked_indexes: list[int] = []
    blocked_count = 0
    for row in rows:
        item = dict(row)
        if (
            _is_current_directional_guard_row(item)
            and _paper_direction(item) == status["majority_side"]
            and item.get("paper_fill_allowed") is True
        ):
            reasons = as_list(
                item.get("paper_fill_gate_block_reasons")
                or item.get("paper_fill_block_reasons")
                or item.get("block_reasons")
            )
            if PAPER_DIRECTIONAL_COLLAPSE_BLOCK_REASON not in reasons:
                reasons.append(PAPER_DIRECTIONAL_COLLAPSE_BLOCK_REASON)
            item["paper_fill_allowed"] = False
            item["routes_to_orchestrator"] = False
            item["paper_fill_gate_status"] = "DIRECTIONAL_COLLAPSE_BLOCKED"
            item["paper_fill_gate_block_reasons"] = reasons
            item["blocked_reason"] = item.get("blocked_reason") or PAPER_DIRECTIONAL_COLLAPSE_BLOCK_REASON
            item["paper_fill_status"] = "PAPER_FILL_GATE_BLOCKED"
            item["paper_status_label"] = "PAPER_FILL_GATE_BLOCKED_BEFORE_INTENT"
            blocked_indexes.append(len(guarded_rows))
            blocked_count += 1
        guarded_rows.append(item)
    status = dict(status)
    status["blocked_paper_actionability_count"] = blocked_count
    for index in blocked_indexes:
        item = guarded_rows[index]
        lineage = as_dict(item.get("source_lineage"))
        if lineage or "source_lineage" in item:
            lineage["paper_directional_collapse_guard"] = status
            item["source_lineage"] = lineage
    return guarded_rows, status


def apply_paper_closed_trade_directional_collapse_guard(
    rows: list[dict[str, Any]],
    *,
    store: V2KeyValueStore,
    min_closed_directional_rows: int = PAPER_DIRECTIONAL_COLLAPSE_MIN_CURRENT_DIRECTIONAL_ROWS,
    min_majority_side_rows: int = PAPER_DIRECTIONAL_COLLAPSE_MIN_MAJORITY_SIDE_ROWS,
    major_side_share: float = PAPER_DIRECTIONAL_COLLAPSE_MAJOR_SIDE_SHARE,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    status = paper_closed_trade_directional_collapse_guard_status(
        store,
        min_closed_directional_rows=min_closed_directional_rows,
        min_majority_side_rows=min_majority_side_rows,
        major_side_share=major_side_share,
    )
    if not status["directional_collapse_detected"] or not status["majority_side"]:
        return rows, status
    guarded_rows: list[dict[str, Any]] = []
    blocked_indexes: list[int] = []
    blocked_count = 0
    for row in rows:
        item = dict(row)
        if (
            _is_current_directional_guard_row(item)
            and _paper_direction(item) == status["majority_side"]
            and item.get("paper_fill_allowed") is True
        ):
            reasons = as_list(
                item.get("paper_fill_gate_block_reasons")
                or item.get("paper_fill_block_reasons")
                or item.get("block_reasons")
            )
            if PAPER_DIRECTIONAL_COLLAPSE_BLOCK_REASON not in reasons:
                reasons.append(PAPER_DIRECTIONAL_COLLAPSE_BLOCK_REASON)
            item["paper_fill_allowed"] = False
            item["routes_to_orchestrator"] = False
            item["paper_fill_gate_status"] = "DIRECTIONAL_COLLAPSE_BLOCKED"
            item["paper_fill_gate_block_reasons"] = reasons
            item["blocked_reason"] = item.get("blocked_reason") or PAPER_DIRECTIONAL_COLLAPSE_BLOCK_REASON
            item["paper_fill_status"] = "PAPER_FILL_GATE_BLOCKED"
            item["paper_status_label"] = "PAPER_FILL_GATE_BLOCKED_BEFORE_INTENT"
            blocked_indexes.append(len(guarded_rows))
            blocked_count += 1
        guarded_rows.append(item)
    status = dict(status)
    status["blocked_paper_actionability_count"] = blocked_count
    for index in blocked_indexes:
        item = guarded_rows[index]
        lineage = as_dict(item.get("source_lineage"))
        if lineage or "source_lineage" in item:
            lineage["paper_closed_trade_directional_collapse_guard"] = status
            item["source_lineage"] = lineage
    return guarded_rows, status


def feature_payload_for_prediction(
    *,
    store: V2KeyValueStore,
    symbol: str,
    timeframe: str,
    prediction: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str, str]:
    snapshot_id = prediction.get("feature_snapshot_id")
    if snapshot_id not in {None, ""}:
        snapshot_key = feature_snapshot_key(snapshot_id)
        archived = store.get_json(snapshot_key)
        if isinstance(archived, dict):
            return archived, snapshot_key, "EXACT_ARCHIVED_FEATURE_SNAPSHOT"
    latest_key = feature_latest_key(symbol, timeframe)
    return (
        store.get_json(latest_key),
        latest_key,
        "LATEST_FEATURE_FALLBACK_AFTER_MISSING_EXACT_ARCHIVE"
        if snapshot_id not in {None, ""}
        else "LATEST_FEATURE_LOOKUP_NO_PREDICTION_SNAPSHOT_ID",
    )


def build_prediction_rows(
    *,
    store: V2KeyValueStore,
    symbols: list[str],
    timeframes: tuple[str, ...] = REQUIRED_TIMEFRAMES,
    stale_seconds: int = DEFAULT_STALE_SECONDS,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        price_payload = market_price_payload(store, symbol)
        for timeframe in timeframes:
            pred, pred_key = select_prediction_payload(
                store=store,
                symbol=symbol,
                timeframe=timeframe,
                stale_seconds=stale_seconds,
            )
            if pred is None or pred.get("status") == "MISSING_TF_PREDICTION":
                rows.append(build_blocker_row(symbol, timeframe, "MISSING_TF_PREDICTION"))
                continue
            feature_payload, feature_key, feature_lookup_status = feature_payload_for_prediction(
                store=store,
                symbol=symbol,
                timeframe=timeframe,
                prediction=pred,
            )
            rows.append(
                build_prediction_row(
                    symbol=symbol,
                    timeframe=timeframe,
                    prediction=pred,
                    price_payload=price_payload,
                    feature_payload=feature_payload,
                    stale_seconds=stale_seconds,
                    source_prediction_key=pred_key,
                    feature_source_key=feature_key,
                    feature_lookup_status=feature_lookup_status,
                )
            )
    return rows


def _scope_rejected_all_timeframes(rows: list[dict[str, Any]], symbol: str, timeframes: tuple[str, ...]) -> bool:
    symbol_rows = [row for row in rows if row.get("symbol") == symbol]
    if len(symbol_rows) != len(timeframes):
        return False
    scope_rejection_statuses = {"MISSING_TF_PREDICTION", "STALE_TF_PREDICTION"}
    return all(row.get("status") in scope_rejection_statuses for row in symbol_rows)


def trainer_trust_rejects_all_timeframes(
    *,
    store: V2KeyValueStore,
    symbol: str,
    timeframes: tuple[str, ...] = REQUIRED_TIMEFRAMES,
) -> dict[str, Any]:
    if store.client is None:
        return {
            "symbol": symbol,
            "exclude_from_expected_grid": False,
            "status": "TRUST_CHECK_SKIPPED_NO_REDIS_CLIENT",
            "timeframes": list(timeframes),
            "reasons_by_timeframe": {},
        }
    loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=store.client))
    reasons_by_timeframe: dict[str, list[str]] = {}
    classifications: dict[str, str] = {}
    for timeframe in timeframes:
        try:
            example = loader.build_example(symbol=symbol, timeframe=timeframe)
        except Exception as exc:  # noqa: BLE001
            return {
                "symbol": symbol,
                "exclude_from_expected_grid": False,
                "status": "TRUST_CHECK_INCONCLUSIVE",
                "timeframes": list(timeframes),
                "error_timeframe": timeframe,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "reasons_by_timeframe": reasons_by_timeframe,
                "classifications": classifications,
            }
        trust_row = as_dict(example.trust_row)
        reasons = [str(reason) for reason in as_list(trust_row.get("reject_reasons")) if str(reason)]
        if (
            not reasons
            and (
                trust_row.get("trainer_consumable") is True
                or (
                    trust_row.get("accepted_for_training") is True
                    and str(example.row_classification).upper() in {"TRAINABLE", "MISSING_MASKED"}
                )
            )
        ):
            return {
                "symbol": symbol,
                "exclude_from_expected_grid": False,
                "status": "TRAINER_TRUST_CONSUMABLE",
                "timeframes": list(timeframes),
                "consumable_timeframe": timeframe,
                "reasons_by_timeframe": reasons_by_timeframe,
                "classifications": classifications,
            }
        classifications[timeframe] = str(example.row_classification)
        if not reasons:
            return {
                "symbol": symbol,
                "exclude_from_expected_grid": False,
                "status": "TRAINER_TRUST_REJECTION_NOT_EXPLICIT",
                "timeframes": list(timeframes),
                "inconclusive_timeframe": timeframe,
                "reasons_by_timeframe": reasons_by_timeframe,
                "classifications": classifications,
            }
        reasons_by_timeframe[timeframe] = sorted(set(reasons))
    flattened_reasons = {
        reason.upper()
        for reasons in reasons_by_timeframe.values()
        for reason in reasons
    }
    scope_exclusion_reasons = {
        "UNCLOSED_CANDLE",
        "CANDLE_NOT_CLOSED_CONFIRMED",
        "CANDLE_FINALITY_UNKNOWN",
    }
    scope_excluded = bool(flattened_reasons.intersection(scope_exclusion_reasons)) or any(
        reason.startswith("MTF_SNAPSHOT:MISSING_CLOSED_CANDLE") for reason in flattened_reasons
    )
    if not scope_excluded:
        return {
            "symbol": symbol,
            "exclude_from_expected_grid": False,
            "status": "TRAINER_TRUST_REJECTED_NOT_SCOPE_EXCLUSION",
            "timeframes": list(timeframes),
            "reasons_by_timeframe": reasons_by_timeframe,
            "classifications": classifications,
        }
    return {
        "symbol": symbol,
        "exclude_from_expected_grid": True,
        "status": "TRAINER_TRUST_REJECTED_ALL_TIMEFRAMES",
        "timeframes": list(timeframes),
        "reasons_by_timeframe": reasons_by_timeframe,
        "classifications": classifications,
        "removal_reason": "symbol has all required timeframe predictions missing/stale and trainer trust rows reject every timeframe",
    }


def reconcile_prediction_symbol_scope(
    *,
    store: V2KeyValueStore,
    symbols: list[str],
    rows: list[dict[str, Any]],
    timeframes: tuple[str, ...] = REQUIRED_TIMEFRAMES,
    trainer_trust_reconciliation_limit: int | None = None,
) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    excluded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    kept_symbols: list[str] = []
    trust_checks_attempted = 0
    trust_check_limit = (
        None
        if trainer_trust_reconciliation_limit is None
        else max(0, int(trainer_trust_reconciliation_limit))
    )
    for symbol in symbols:
        if not _scope_rejected_all_timeframes(rows, symbol, timeframes):
            kept_symbols.append(symbol)
            continue
        if trust_check_limit is not None and trust_checks_attempted >= trust_check_limit:
            skipped.append(
                {
                    "symbol": symbol,
                    "exclude_from_expected_grid": False,
                    "status": "TRAINER_TRUST_CHECK_SKIPPED_RUNTIME_LIMIT",
                    "timeframes": list(timeframes),
                    "removal_reason": "runtime trainer trust reconciliation limit reached before this symbol",
                }
            )
            kept_symbols.append(symbol)
            continue
        trust_checks_attempted += 1
        trust = trainer_trust_rejects_all_timeframes(store=store, symbol=symbol, timeframes=timeframes)
        if trust.get("exclude_from_expected_grid") is True:
            excluded.append(trust)
        else:
            kept_symbols.append(symbol)
    excluded_symbols = {str(item.get("symbol")) for item in excluded}
    reconciled_rows = [row for row in rows if str(row.get("symbol")) not in excluded_symbols]
    reconciliation_status = "SYMBOL_SCOPE_VALID_DYNAMIC_RUNTIME_UNIVERSE"
    if skipped:
        reconciliation_status = "SYMBOL_SCOPE_VALID_DYNAMIC_RUNTIME_UNIVERSE_PARTIAL_TRUST_CHECK_LIMIT"
    return kept_symbols, reconciled_rows, {
        "symbol_scope_reconciliation_status": reconciliation_status,
        "previous_symbol_count": len(symbols),
        "current_symbol_count": len(kept_symbols),
        "removed_symbol_count": len(excluded),
        "removed_symbols": [str(item.get("symbol")) for item in excluded],
        "removal_reason_by_symbol": {str(item.get("symbol")): item for item in excluded},
        "trainer_trust_reconciliation_limit": trust_check_limit,
        "trainer_trust_checks_attempted": trust_checks_attempted,
        "trainer_trust_checks_skipped_count": len(skipped),
        "trainer_trust_reconciliation_skipped_symbols": [str(item.get("symbol")) for item in skipped],
        "trainer_trust_reconciliation_skipped_reason_by_symbol": {
            str(item.get("symbol")): item for item in skipped
        },
        "expected_runtime_universe_source": "symbol_universe/dynamic_symbol_discovery filtered by explicit trainer trust rejection",
    }


def build_prediction_status(rows: list[dict[str, Any]], symbols: list[str], stale_seconds: int) -> dict[str, Any]:
    current = [row for row in rows if row["status"] in CURRENT_PREDICTION_STATUSES]
    stale = [row for row in rows if row["status"] == "STALE_TF_PREDICTION"]
    missing = [row for row in rows if row["status"] == "MISSING_TF_PREDICTION"]
    expected_missing = [row for row in rows if str(row["status"]).startswith("EXPECTED_MOVE")]
    blockers = [row for row in rows if row.get("implementation_task")]
    labelled_sidecar = [row for row in rows if row["status"] == "PRESENT_CURRENT_RL_CORE_SIDECAR_NOT_CUDA_PARITY"]

    def _timeframes_by_symbol(items: list[dict[str, Any]]) -> dict[str, list[str]]:
        out: dict[str, set[str]] = {}
        for row in items:
            symbol = str(row.get("symbol") or "").upper()
            timeframe = str(row.get("timeframe") or "")
            if symbol and timeframe:
                out.setdefault(symbol, set()).add(timeframe)
        return {symbol: sorted(timeframes) for symbol, timeframes in sorted(out.items())}

    return {
        "schema_version": "v2_all_timeframe_prediction_publisher_status_v1",
        "generated_est": est_now(),
        "service_id": SERVICE_ID,
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "required_timeframes": list(REQUIRED_TIMEFRAMES),
        "symbols_covered": symbols,
        "timeframes_covered": list(REQUIRED_TIMEFRAMES),
        "prediction_rows": rows,
        "prediction_rows_count": len(rows),
        "current_prediction_count": len(current),
        "stale_prediction_count": len(stale),
        "stale_prediction_symbols": sorted({str(row.get("symbol")).upper() for row in stale if row.get("symbol")}),
        "stale_prediction_timeframes_by_symbol": _timeframes_by_symbol(stale),
        "missing_prediction_count": len(missing),
        "expected_move_missing_count": len(expected_missing),
        "blocker_count": len(blockers),
        "trainer_source_mismatch_count": len(
            [row for row in rows if row["status"] == "TRAINER_SOURCE_NOT_CUDA_PARITY"]
        ),
        "labelled_rl_core_sidecar_count": len(labelled_sidecar),
        "labelled_rl_core_sidecar_status": "RL_CORE_SIDECAR_NOT_CUDA_PARITY_LABELLED_NOT_REMEDIATION"
        if labelled_sidecar
        else "NO_RL_CORE_SIDECAR_ROWS",
        "stale_threshold_seconds": stale_seconds,
        "status": "ALL_TIMEFRAME_PREDICTIONS_CURRENT" if not blockers else "ALL_TIMEFRAME_PREDICTIONS_BLOCKED",
        "implementation_tasks": sorted({str(row.get("implementation_task")) for row in blockers if row.get("implementation_task")}),
    }


def build_expected_move_status(rows: list[dict[str, Any]]) -> dict[str, Any]:
    telemetry_rows: list[dict[str, Any]] = []
    for row in rows:
        expected = to_float(row.get("expected_move_bps"))
        after = to_float(row.get("expected_move_after_cost_bps"))
        delta = None if expected is None or after is None else expected - after
        source = as_dict(row.get("source_lineage")).get("expected_move_source")
        missing_reason = None
        if row["status"] == "MISSING_TF_PREDICTION":
            missing_reason = "MISSING_TF_PREDICTION"
        elif expected is None:
            missing_reason = "EXPECTED_MOVE_TELEMETRY_MISSING"
        elif after is None:
            missing_reason = "EXPECTED_MOVE_AFTER_COST_TELEMETRY_MISSING"
        telemetry_rows.append(
            {
                "symbol": row["symbol"],
                "timeframe": row["timeframe"],
                "prediction_id": row.get("prediction_id"),
                "prediction_redis_key": row.get("prediction_redis_key"),
                "expected_move_source": source or "missing",
                "expected_move_after_cost_source": "v2_prediction.expected_move_after_cost_bps" if after is not None else "missing",
                "fee_model_source": "embedded_prediction_after_cost_delta" if delta is not None else "missing",
                "slippage_model_source": "embedded_prediction_after_cost_delta" if delta is not None else "missing",
                "calibration_source": as_dict(row.get("source_lineage")).get("calibration_source") or "missing",
                "expected_move_bps": expected,
                "expected_move_after_cost_bps": after,
                "after_cost_delta_bps": delta,
                "missing_reason_if_absent": missing_reason,
            }
        )
    missing = [row for row in telemetry_rows if row["missing_reason_if_absent"]]
    return {
        "schema_version": "v2_expected_move_telemetry_status_v1",
        "generated_est": est_now(),
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "telemetry_rows": telemetry_rows,
        "telemetry_rows_count": len(telemetry_rows),
        "expected_move_ready_count": len(telemetry_rows) - len(missing),
        "expected_move_missing_count": len(missing),
        "status": "EXPECTED_MOVE_TELEMETRY_READY" if not missing else "EXPECTED_MOVE_TELEMETRY_BLOCKED_OR_PARTIAL",
    }


def build_price_target_status(rows: list[dict[str, Any]]) -> dict[str, Any]:
    target_rows: list[dict[str, Any]] = []
    for row in rows:
        targets = price_targets(
            to_float(row.get("last_price")),
            to_float(row.get("expected_move_bps")),
            to_float(row.get("expected_move_after_cost_bps")),
            str(row.get("selected_action") or "hold"),
        )
        validation = targets["validation_status"]
        if row["status"] == "MISSING_TF_PREDICTION":
            validation = "MISSING_TF_PREDICTION"
        target_rows.append(
            {
                "symbol": row["symbol"],
                "timeframe": row["timeframe"],
                "prediction_id": row.get("prediction_id"),
                "source_price_key": price_key(str(row["symbol"])),
                "source_prediction_key": row.get("prediction_redis_key"),
                "selected_action": row.get("selected_action"),
                "last_price": row.get("last_price"),
                "expected_move_bps": row.get("expected_move_bps"),
                "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
                "price_target": targets["price_target"],
                "price_target_after_cost": targets["price_target_after_cost"],
                "price_target_low": targets["price_target_low"],
                "price_target_high": targets["price_target_high"],
                "stop_reference": targets["stop_reference"],
                "take_profit_reference": targets["take_profit_reference"],
                "formula": targets["formula"],
                "after_cost_formula": targets["after_cost_formula"],
                "validation_status": validation,
            }
        )
    invalid = [row for row in target_rows if row["validation_status"] not in ("VALID", "HOLD_REFERENCE_ONLY")]
    return {
        "schema_version": "v2_price_target_all_tf_status_v1",
        "generated_est": est_now(),
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "target_rows": target_rows,
        "target_rows_count": len(target_rows),
        "valid_or_reference_count": len(target_rows) - len(invalid),
        "invalid_or_missing_count": len(invalid),
        "status": "PRICE_TARGET_ALL_TF_READY" if not invalid else "PRICE_TARGET_ALL_TF_BLOCKED_OR_PARTIAL",
    }


def build_signal_from_row(
    row: Mapping[str, Any],
    existing_signal: Mapping[str, Any] | None = None,
    live_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    existing = as_dict(existing_signal)
    context = as_dict(live_context)
    live_gate = str(context.get("live_gate") or row.get("live_gate") or LIVE_GATE)
    live_symbols = as_list(context.get("live_symbols")) or as_list(row.get("live_symbols"))
    execution_live_symbols = as_list(context.get("execution_live_symbols")) or as_list(row.get("execution_live_symbols"))
    prediction_id = str(row.get("prediction_id") or "")
    signal_id = stable_id("sig", prediction_id or row.get("prediction_redis_key"), row.get("timeframe"))
    status = str(row.get("status"))
    risk_state = "BLOCKED"
    blocked_reason = row.get("missing_stale_reason")
    after_cost = to_float(row.get("expected_move_after_cost_bps"))
    action = str(row.get("selected_action") or "hold")
    paper_fill_allowed = row.get("paper_fill_allowed") is True
    paper_gate_block_reasons = as_list(
        row.get("paper_fill_gate_block_reasons")
        or row.get("paper_fill_block_reasons")
        or row.get("block_reasons")
    )
    market_state_reject_reasons = as_list(row.get("market_state_reject_reasons"))
    # For shorts, negative after_cost = positive trade edge (price expected to fall).
    # Normalize to a signed-edge-is-positive check before actionability classification.
    # When paper_fill_allowed=true, the upstream gate already approved; never override with NON_ACTIONABLE.
    _signed_edge_positive = (
        after_cost is not None
        and (
            (action == "short" and after_cost < 0)
            or (action not in ("short", "hold", "hedge_reserved_fail_closed") and after_cost > 0)
        )
    )
    if paper_fill_allowed:
        # Upstream gate approved — preserve blocked_reason from missing_stale_reason only
        pass
    elif status in CURRENT_PREDICTION_STATUSES and _signed_edge_positive and action not in ("hold", "hedge_reserved_fail_closed"):
        risk_state = "PAPER_SHADOW_NEEDS_RISK_DECISION"
        blocked_reason = "RISK_DECISION_NOT_AVAILABLE_FOR_ALL_TF_SIGNAL"
    elif status in CURRENT_PREDICTION_STATUSES and blocked_reason is None:
        blocked_reason = "NON_ACTIONABLE_EXPECTED_MOVE_OR_ACTION"
    if status in CURRENT_PREDICTION_STATUSES and not paper_fill_allowed and paper_gate_block_reasons:
        risk_state = "PAPER_GATE_BLOCKED_BEFORE_RISK"
        blocked_reason = "PAPER_FILL_GATE_BLOCKED: " + ", ".join(str(reason) for reason in paper_gate_block_reasons[:4])
    _raw_rid = existing.get("risk_decision_id")
    _raw_oid = existing.get("orchestrator_decision_id") or existing.get("decision_id")
    # For the hybrid-trainer path, orchestrator_decision_id may not be populated separately.
    # Use risk_decision_id as a documented alias: the risk decision IS the orchestrator decision
    # for that path. Mark the source explicitly so it is auditable.
    if _raw_oid:
        _orch_src = "EXPLICIT_ORCHESTRATOR_DECISION_ID"
    elif _raw_rid:
        _raw_oid = _raw_rid
        _orch_src = "RISK_DECISION_ID_ALIAS_NO_SEPARATE_ORCH_IN_HYBRID_TRAINER_PATH"
    else:
        _orch_src = "ORCHESTRATOR_DECISION_UNAVAILABLE"
    lineage_ids = {
        "trainer_prediction_id": prediction_id or None,
        "risk_decision_id": _raw_rid,
        "orchestrator_decision_id": _raw_oid,
        "orchestrator_decision_source": _orch_src,
        "paper_intent_id": existing.get("paper_intent_id") or existing.get("execution_intent_id"),
        "paper_ledger_id": existing.get("paper_ledger_id") or existing.get("paper_trade_id"),
    }
    if not paper_fill_allowed and paper_gate_block_reasons:
        lineage_ids["risk_decision_id"] = None
        lineage_ids["orchestrator_decision_id"] = None
        lineage_ids["orchestrator_decision_source"] = "ORCHESTRATOR_DECISION_UNAVAILABLE"
        lineage_ids["paper_intent_id"] = None
        lineage_ids["paper_ledger_id"] = None
    if lineage_ids["risk_decision_id"]:
        risk_state = "VISIBLE"
        if blocked_reason == "RISK_DECISION_NOT_AVAILABLE_FOR_ALL_TF_SIGNAL":
            blocked_reason = None
    # Enforce: no actionable fill without complete upstream lineage.
    if paper_fill_allowed and (not lineage_ids["risk_decision_id"] or not lineage_ids["orchestrator_decision_id"]):
        paper_fill_allowed = False
        blocked_reason = blocked_reason or "LINEAGE_INCOMPLETE_PAPER_FILL_BLOCKED"
    market_cost_fields = {
        field: row.get(field)
        for field in MARKET_COST_EVIDENCE_FIELDS
        if field in row
    }
    pit_context_fields = {
        field: row.get(field)
        for field in RUNTIME_PAPER_PIT_CONTEXT_FIELDS
        if field in row
    }
    if "runtime_paper_pit_context_source_fields" in row:
        pit_context_fields["runtime_paper_pit_context_source_fields"] = as_dict(
            row.get("runtime_paper_pit_context_source_fields")
        )
    source_lineage = as_dict(row.get("source_lineage"))
    return {
        "signal_id": signal_id,
        "prediction_id": prediction_id or None,
        "risk_decision_id": lineage_ids["risk_decision_id"],
        "orchestrator_decision_id": lineage_ids["orchestrator_decision_id"],
        "orchestrator_decision_source": lineage_ids.get("orchestrator_decision_source"),
        "paper_intent_id": lineage_ids["paper_intent_id"],
        "paper_ledger_id": lineage_ids["paper_ledger_id"],
        "symbol": row.get("symbol"),
        "timeframe": row.get("timeframe"),
        "action": action,
        "selected_action": action,
        "feature_snapshot_id": row.get("feature_snapshot_id"),
        "last_price": row.get("last_price"),
        "price_target": row.get("price_target"),
        "price_target_after_cost": row.get("price_target_after_cost"),
        "price_target_low": row.get("price_target_low"),
        "price_target_high": row.get("price_target_high"),
        "stop_reference": row.get("stop_reference"),
        "take_profit_reference": row.get("take_profit_reference"),
        "confidence": row.get("confidence_calibrated"),
        "confidence_calibrated": row.get("confidence_calibrated"),
        "expected_move_bps": row.get("expected_move_bps"),
        "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
        "expected_net_edge_bps": row.get("expected_move_after_cost_bps"),
        "risk_state": risk_state,
        "risk_status_label": risk_state,
        "orchestrator_state": "BLOCKED_NO_ORCHESTRATOR_DECISION" if not lineage_ids["orchestrator_decision_id"] else "VISIBLE",
        "orchestrator_status_label": "ORCHESTRATOR_DECISION_MISSING" if not lineage_ids["orchestrator_decision_id"] else "VISIBLE",
        "paper_state": "NO_PAPER_INTENT_FOR_ALL_TF_SIGNAL" if not lineage_ids["paper_intent_id"] else "VISIBLE",
        "paper_status_label": (
            "PAPER_FILL_GATE_BLOCKED_BEFORE_INTENT"
            if not paper_fill_allowed and paper_gate_block_reasons
            else ("PAPER_INTENT_MISSING" if not lineage_ids["paper_intent_id"] else "VISIBLE")
        ),
        "ledger_status_label": "PAPER_LEDGER_MISSING" if not lineage_ids["paper_ledger_id"] else "VISIBLE",
        "paper_fill_status": (
            "PAPER_FILL_GATE_BLOCKED"
            if not paper_fill_allowed and paper_gate_block_reasons
            else ("PAPER_LEDGER_MISSING" if not lineage_ids["paper_ledger_id"] else "PAPER_LEDGER_VISIBLE")
        ),
        "paper_fill_allowed": paper_fill_allowed,
        "paper_fill_gate_status": row.get("paper_fill_gate_status"),
        "paper_fill_gate_block_reasons": paper_gate_block_reasons,
        "market_state_id": row.get("market_state_id"),
        "market_state_integrity_score": row.get("market_state_integrity_score"),
        "valid_for_prediction": row.get("valid_for_prediction"),
        "valid_for_risk": row.get("valid_for_risk"),
        "valid_for_orchestrator": row.get("valid_for_orchestrator"),
        "valid_for_paper": row.get("valid_for_paper"),
        "valid_for_live": row.get("valid_for_live"),
        "market_state_reject_reasons": market_state_reject_reasons,
        **pit_context_fields,
        **market_cost_fields,
        "blocked_reason": blocked_reason,
        "data_coverage_percent": row.get("data_coverage_percent"),
        "generated_est": row.get("generated_est") or est_now(),
        "source_prediction_status": status,
        "source_prediction_key": row.get("prediction_redis_key"),
        "primary_prediction_redis_key": row.get("primary_prediction_redis_key"),
        "source_lineage": source_lineage,
        "lineage_ids": lineage_ids,
        "live_gate": live_gate,
        "live_symbols": live_symbols,
        "execution_live_symbols": execution_live_symbols,
    }


def lineage_compatible_existing_signal(row: Mapping[str, Any], existing_signal: Mapping[str, Any] | None) -> dict[str, Any]:
    existing = as_dict(existing_signal)
    existing_prediction_id = existing.get("trainer_prediction_id") or existing.get("prediction_id")
    row_prediction_id = row.get("prediction_id")
    if not row_prediction_id:
        return {}
    if not existing_prediction_id:
        if row.get("paper_fill_gate_block_reasons") or row.get("paper_fill_block_reasons"):
            return {}
        return existing
    if str(existing_prediction_id) != str(row_prediction_id):
        return {}
    return existing


def _list_from_store(store: V2KeyValueStore, key: str) -> list[Any]:
    value = store.get_value(key)
    return list(value) if isinstance(value, list) else []


def _dict_from_store(store: V2KeyValueStore, key: str) -> dict[str, Any]:
    value = store.get_value(key)
    return dict(value) if isinstance(value, dict) else {}


def _by_symbol(rows: Iterable[Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = as_dict(row)
        symbol = str(item.get("symbol") or "").upper()
        if symbol and symbol not in out:
            out[symbol] = item
    return out


def _by_prediction_id(rows: Iterable[Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = as_dict(row)
        prediction_id = str(item.get("prediction_id") or item.get("source_prediction_id") or "").strip()
        if prediction_id:
            out[prediction_id] = item
    return out


def _find_by_symbol_or_id(rows: Iterable[Any], symbol: str, source_id: str | None) -> dict[str, Any]:
    symbol = symbol.upper()
    for row in rows:
        item = as_dict(row)
        if source_id and source_id in {
            str(item.get("intent_id") or ""),
            str(item.get("source_intent_id") or ""),
            str(item.get("source_prediction_id") or ""),
            str(item.get("prediction_id") or ""),
        }:
            return item
    for row in rows:
        item = as_dict(row)
        if str(item.get("symbol") or "").upper() == symbol:
            return item
    return {}


def _integrity_missing(
    *,
    symbol: str,
    timeframe: str,
    prediction: Mapping[str, Any],
    reason: str,
) -> dict[str, Any]:
    return {
        "market_state_id": prediction.get("market_state_id"),
        "market_state_integrity_score": prediction.get("market_state_integrity_score"),
        "valid_for_training": prediction.get("valid_for_training") is True,
        "valid_for_prediction": prediction.get("valid_for_prediction") is True,
        "valid_for_risk": prediction.get("valid_for_risk") is True,
        "valid_for_orchestrator": prediction.get("valid_for_orchestrator") is True,
        "valid_for_paper": prediction.get("valid_for_paper") is True,
        "valid_for_live": prediction.get("valid_for_live") is True,
        "decision_cutoff_time_est": prediction.get("decision_cutoff_time_est"),
        "market_state_reject_reasons": sorted(
            set(as_list(prediction.get("market_state_reject_reasons")) + [reason])
        ),
        "market_state_score_components": as_dict(prediction.get("market_state_score_components")),
        "market_state_source_lineage": {
            **as_dict(prediction.get("market_state_source_lineage")),
            "symbol": symbol,
            "timeframe": timeframe,
            "prediction_feature_snapshot_id": prediction.get("feature_snapshot_id"),
            "exact_blocker": reason,
        },
    }


def build_integrity_enrichment(
    *,
    symbol: str,
    timeframe: str,
    prediction: Mapping[str, Any],
    feature_payload: Mapping[str, Any] | None,
    feature_source_key: str,
) -> dict[str, Any]:
    if prediction.get("market_state_id") and prediction.get("market_state_integrity_score") is not None:
        return {
            "market_state_id": prediction.get("market_state_id"),
            "market_state_integrity_score": prediction.get("market_state_integrity_score"),
            "valid_for_training": prediction.get("valid_for_training") is True,
            "valid_for_prediction": prediction.get("valid_for_prediction") is True,
            "valid_for_risk": prediction.get("valid_for_risk") is True,
            "valid_for_orchestrator": prediction.get("valid_for_orchestrator") is True,
            "valid_for_paper": prediction.get("valid_for_paper") is True,
            "valid_for_live": prediction.get("valid_for_live") is True,
            "decision_cutoff_time_est": prediction.get("decision_cutoff_time_est"),
            "market_state_reject_reasons": as_list(prediction.get("market_state_reject_reasons")),
            "market_state_score_components": as_dict(prediction.get("market_state_score_components")),
            "market_state_source_lineage": as_dict(prediction.get("market_state_source_lineage")),
        }
    if not isinstance(feature_payload, Mapping):
        return _integrity_missing(
            symbol=symbol,
            timeframe=timeframe,
            prediction=prediction,
            reason="MARKET_STATE_FEATURE_SNAPSHOT_MISSING",
        )
    prediction_snapshot_id = prediction.get("feature_snapshot_id")
    feature_snapshot_id = feature_payload.get("feature_snapshot_id")
    if prediction_snapshot_id and feature_snapshot_id and str(prediction_snapshot_id) != str(feature_snapshot_id):
        return _integrity_missing(
            symbol=symbol,
            timeframe=timeframe,
            prediction=prediction,
            reason="MARKET_STATE_FEATURE_SNAPSHOT_MISMATCH",
        )
    score_input = dict(feature_payload)
    score_input.setdefault("symbol", symbol)
    score_input.setdefault("timeframe", timeframe)
    score_input["prediction_id"] = prediction.get("prediction_id")
    score_input["_redis_key"] = feature_source_key
    score = score_market_state(score_input).to_dict()
    return {
        "market_state_id": score["market_state_id"],
        "market_state_integrity_score": score["market_state_integrity_score"],
        "valid_for_training": score["valid_for_training"],
        "valid_for_prediction": score["valid_for_prediction"],
        "valid_for_risk": score["valid_for_risk"],
        "valid_for_orchestrator": score["valid_for_orchestrator"],
        "valid_for_paper": score["valid_for_paper"],
        "valid_for_live": score["valid_for_live"],
        "decision_cutoff_time_est": score["decision_time_est"],
        "market_state_reject_reasons": list(score["reject_reasons"]),
        "market_state_score_components": {
            "data_freshness_score": score["data_freshness_score"],
            "candle_completion_score": score["candle_completion_score"],
            "tf_alignment_score": score["tf_alignment_score"],
            "missing_data_score": score["missing_data_score"],
            "source_disagreement_score": score["source_disagreement_score"],
            "latency_score": score["latency_score"],
            "backfill_score": score["backfill_score"],
            "execution_fill_quality_score": score["execution_fill_quality_score"],
        },
        "market_state_source_lineage": score["source_lineage"],
    }


def build_runtime_paper_signal_rows(store: V2KeyValueStore, live_context: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Current paper-trading lane from trainer -> orchestrator -> paper loop.

    This is intentionally separate from the CUDA/all-timeframe parity grid:
    it shows the live paper decision path as current truth while the full
    parity grid may still be stale or blocked.
    """
    aggregate = [as_dict(row) for row in _list_from_store(store, "v2:signals:paper")]
    if not aggregate:
        return []
    orchestrator = _dict_from_store(store, "v2:orchestrator:decisions")
    risk_gateway_by_prediction = _by_prediction_id(_list_from_store(store, "v2:risk:gateway:decisions"))
    risk_by_symbol = _by_symbol(_list_from_store(store, "v2:risk:decisions"))
    paper_intents = _list_from_store(store, "v2:paper:intents")
    paper_ledger = _dict_from_store(store, "v2:paper:ledger")
    shadow_rows = as_list(paper_ledger.get("shadow_observations"))
    accepted_rows = as_list(paper_ledger.get("accepted"))
    generated = (
        timestamp_field(orchestrator)
        or timestamp_field(paper_ledger)
        or est_now()
    )
    rows: list[dict[str, Any]] = []
    context = as_dict(live_context)
    live_gate = str(context.get("live_gate") or LIVE_GATE)
    live_symbols = as_list(context.get("live_symbols"))
    execution_live_symbols = as_list(context.get("execution_live_symbols"))
    for signal in aggregate:
        symbol = str(signal.get("symbol") or "").upper()
        if not symbol:
            continue
        source_id = str(
            signal.get("winner_proposal_id")
            or signal.get("source_prediction_id")
            or signal.get("prediction_id")
            or ""
        ) or None
        action = str(signal.get("side") or signal.get("selected_action") or signal.get("action") or "hold")
        confidence = to_float(signal.get("confidence_calibrated") or signal.get("confidence"))
        timeframe = str(signal.get("timeframe") or signal.get("prediction_timeframe") or "1m")
        expected_move = to_float(signal.get("expected_move_bps"))
        if expected_move is None:
            expected_move = to_float(signal.get("expected_move"))
        after_cost = to_float(signal.get("expected_move_after_cost_bps"))
        price_payload = market_price_payload(store, symbol)
        last_price, price_field = extract_last_price(price_payload)
        targets = price_targets(
            last_price,
            expected_move if expected_move is not None else after_cost,
            after_cost,
            action,
        )
        risk = risk_gateway_by_prediction.get(source_id or "") or risk_by_symbol.get(symbol, {})
        intent = _find_by_symbol_or_id(paper_intents, symbol, source_id)
        shadow = _find_by_symbol_or_id(shadow_rows, symbol, source_id)
        accepted = _find_by_symbol_or_id(accepted_rows, symbol, source_id)
        evidence_sources = (
            ("paper_signal", signal),
            ("paper_intent", intent),
            ("paper_accepted", accepted),
            ("paper_shadow", shadow),
            ("risk_decision", risk),
        )
        runtime_pit_context = _runtime_paper_pit_context_fields(evidence_sources)
        runtime_market_cost_evidence = _runtime_paper_market_cost_evidence_fields(evidence_sources)
        feature_snapshot_id = runtime_pit_context.get("feature_snapshot_id")
        risk_decision_id = risk.get("risk_decision_id") if risk else None
        paper_ledger_id = accepted.get("paper_ledger_id") or shadow.get("paper_ledger_id") or None
        # Orchestrator decision ID: prefer the explicit field written by paper_online_runtime.
        # For the hybrid-trainer path there is no separate orchestrator step — the risk decision
        # is the effective orchestrator decision. Document that with a source flag rather than
        # silently aliasing or returning None (which would block all hybrid-trainer signals).
        _orch_from_risk = risk.get("orchestrator_decision_id") if risk else None
        if _orch_from_risk:
            orchestrator_decision_id = _orch_from_risk
            _orch_source = "V2_PAPER_RUNTIME_REDIS_ENTRY"
        elif risk_decision_id:
            orchestrator_decision_id = risk_decision_id
            _orch_source = "RISK_DECISION_ID_ALIAS_NO_SEPARATE_ORCH_IN_HYBRID_TRAINER_PATH"
        else:
            orchestrator_decision_id = None
            _orch_source = "ORCHESTRATOR_DECISION_UNAVAILABLE"
        paper_fill_allowed = bool(
            accepted
            or intent.get("paper_fill_allowed")
            or signal.get("paper_fill_allowed")
        )
        # Enforce: no actionable fill without complete upstream lineage.
        if paper_fill_allowed and (not risk_decision_id or not orchestrator_decision_id):
            paper_fill_allowed = False
            _orch_source = "ORCHESTRATOR_DECISION_UNAVAILABLE"
        paper_state = (
            "ACCEPTED_PAPER_FILL"
            if paper_fill_allowed
            else str(shadow.get("decision") or "SHADOW_OBSERVATION_ONLY")
        )
        risk_state = "VISIBLE" if risk else "RISK_DECISION_MISSING"
        blocked_reason = None
        if not risk:
            blocked_reason = "RISK_DECISION_MISSING_FROM_CURRENT_PAPER_LANE"
        elif not paper_fill_allowed:
            blocked_reason = "PAPER_FILL_GATE_FALSE_SHADOW_OBSERVATION_ONLY"
        source_lineage = as_dict(signal.get("source_lineage"))
        source_lineage.setdefault("paper_signal_redis_key", "v2:signals:paper")
        source_lineage.setdefault("source_price_key", price_key(symbol))
        source_lineage.setdefault("source_price_field", price_field)
        source_lineage.setdefault(
            "confidence_calibrated_source_field",
            "paper_signal.confidence_calibrated or paper_signal.confidence",
        )
        source_lineage.setdefault(
            "expected_move_bps_source_field",
            "paper_signal.expected_move_bps"
            if expected_move is not None
            else "missing",
        )
        source_lineage.setdefault(
            "expected_move_after_cost_bps_source_field",
            "paper_signal.expected_move_after_cost_bps"
            if after_cost is not None
            else "missing",
        )
        rows.append(
            {
                "signal_id": source_id or stable_id("live_paper_signal", symbol, action, generated),
                "prediction_id": source_id,
                "risk_decision_id": risk_decision_id,
                "orchestrator_decision_id": orchestrator_decision_id,
                "orchestrator_decision_source": _orch_source,
                "paper_intent_id": intent.get("intent_id"),
                "paper_ledger_id": paper_ledger_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "action": action,
                "selected_action": action,
                "feature_snapshot_id": feature_snapshot_id,
                "last_price": last_price,
                "price_target": targets.get("price_target"),
                "price_target_after_cost": targets.get("price_target_after_cost"),
                "price_target_low": targets.get("price_target_low"),
                "price_target_high": targets.get("price_target_high"),
                "stop_reference": targets.get("stop_reference"),
                "take_profit_reference": targets.get("take_profit_reference"),
                "confidence": confidence,
                "confidence_calibrated": confidence,
                "expected_move_bps": expected_move,
                "expected_move_after_cost_bps": after_cost,
                "expected_net_edge_bps": after_cost,
                "risk_state": risk_state,
                "risk_status_label": risk_state,
                "orchestrator_state": "VISIBLE" if orchestrator_decision_id else "BLOCKED_NO_ORCHESTRATOR_DECISION",
                "orchestrator_status_label": "VISIBLE" if orchestrator_decision_id else "ORCHESTRATOR_DECISION_MISSING",
                "paper_state": paper_state,
                "paper_status_label": paper_state,
                "ledger_status_label": "VISIBLE" if paper_ledger_id else "PAPER_LEDGER_MISSING",
                "paper_fill_status": paper_state,
                "paper_fill_allowed": paper_fill_allowed,
                "paper_fill_gate_status": signal.get("paper_fill_gate_status"),
                "paper_fill_gate_block_reasons": as_list(signal.get("paper_fill_gate_block_reasons")),
                "market_state_id": signal.get("market_state_id"),
                "market_state_integrity_score": signal.get("market_state_integrity_score"),
                "valid_for_prediction": signal.get("valid_for_prediction"),
                "valid_for_risk": signal.get("valid_for_risk"),
                "valid_for_orchestrator": signal.get("valid_for_orchestrator"),
                "valid_for_paper": signal.get("valid_for_paper"),
                "valid_for_live": signal.get("valid_for_live"),
                "market_state_reject_reasons": as_list(signal.get("market_state_reject_reasons")),
                **runtime_pit_context,
                **runtime_market_cost_evidence,
                "blocked_reason": blocked_reason,
                "data_coverage_percent": signal.get("data_coverage_percent"),
                "generated_est": to_est(generated) or est_now(),
                "source_prediction_status": "CURRENT_RUNTIME_PAPER_SIGNAL",
                "source_runtime_lane": "v2:signals:paper",
                "source_price_key": price_key(symbol),
                "source_price_field": price_field,
                "source_lineage": source_lineage,
                "lineage_ids": {
                    "trainer_prediction_id": source_id,
                    "risk_decision_id": risk_decision_id,
                    "orchestrator_decision_id": orchestrator_decision_id,
                    "orchestrator_decision_source": _orch_source,
                    "paper_intent_id": intent.get("intent_id"),
                    "paper_ledger_id": paper_ledger_id,
                    "feature_snapshot_id": feature_snapshot_id,
                },
                "risk_gateway_prediction_id": risk.get("prediction_id"),
                "risk_gateway_live_blocked": risk.get("live_blocked"),
                "legacy_live_blocked_label": "LEGACY_LIVE_PATH_BLOCKED_NOT_V2" if risk.get("live_blocked") is True else None,
                "live_gate": live_gate,
                "live_symbols": live_symbols,
                "execution_live_symbols": execution_live_symbols,
            }
        )
    return rows


def build_signal_status(
    rows: list[dict[str, Any]],
    store: V2KeyValueStore,
    live_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    context = as_dict(live_context)
    live_gate = str(context.get("live_gate") or LIVE_GATE)
    live_symbols = as_list(context.get("live_symbols"))
    execution_live_symbols = as_list(context.get("execution_live_symbols"))
    signals: list[dict[str, Any]] = build_runtime_paper_signal_rows(store, live_context=context)
    seen_prediction_ids = {
        str(signal.get("prediction_id"))
        for signal in signals
        if signal.get("prediction_id")
    }
    # Pre-build risk index so all-TF grid rows can resolve a risk decision for their symbol
    # even when no per-(symbol,timeframe) signal has been persisted yet.
    risk_by_symbol_for_grid = _by_symbol(_list_from_store(store, "v2:risk:decisions"))
    all_timeframe_visible_count = 0
    for row in rows:
        if row.get("status") != "PRESENT_CURRENT":
            continue
        if not row.get("prediction_id"):
            continue
        if str(row.get("prediction_id")) in seen_prediction_ids:
            continue
        existing = store.get_json(signal_paper_key(str(row["symbol"]), str(row["timeframe"])))
        if existing is None:
            existing = store.get_json(f"v2:signals:paper:{row['symbol']}")
        compat_existing = lineage_compatible_existing_signal(row, existing)
        # Inject real risk IDs from global decision index when the compatible existing has none.
        # Applied after lineage_compatible_existing_signal so prediction_id filtering runs first.
        if not compat_existing.get("risk_decision_id"):
            sym = str(row.get("symbol") or "").upper()
            risk_entry = risk_by_symbol_for_grid.get(sym, {})
            if risk_entry:
                compat_existing = dict(compat_existing)
                compat_existing["risk_decision_id"] = risk_entry.get("risk_decision_id")
                compat_existing["orchestrator_decision_id"] = (
                    risk_entry.get("orchestrator_decision_id") or risk_entry.get("decision_id")
                )
                compat_existing["paper_intent_id"] = (
                    risk_entry.get("paper_intent_id") or risk_entry.get("execution_intent_id")
                )
                compat_existing["risk_decision_source"] = "SYMBOL_RISK_DECISION_FALLBACK"
        signals.append(
            build_signal_from_row(
                row,
                compat_existing,
                live_context=context,
            )
        )
        all_timeframe_visible_count += 1
    signals, paper_directional_collapse_guard = apply_paper_directional_collapse_guard(signals)
    signals, paper_closed_trade_directional_collapse_guard = apply_paper_closed_trade_directional_collapse_guard(
        signals,
        store=store,
    )
    intended_keys = []
    for signal in signals:
        intended_keys.append(signal_paper_key(str(signal["symbol"]), str(signal["timeframe"])))
    for symbol in sorted({str(signal["symbol"]) for signal in signals if signal.get("symbol")}):
        intended_keys.append(signal_latest_key(symbol))
    return {
        "schema_version": "v2_all_timeframe_signal_publisher_status_v1",
        "generated_est": est_now(),
        "live_gate": live_gate,
        "live_symbols": live_symbols,
        "execution_live_symbols": execution_live_symbols,
        "live_gate_runtime_context": context,
        "published_signals": signals,
        "signal_count": len(signals),
        "paper_directional_collapse_guard_status": paper_directional_collapse_guard,
        "paper_closed_trade_directional_collapse_guard_status": paper_closed_trade_directional_collapse_guard,
        "current_runtime_paper_signal_count": len(
            [signal for signal in signals if signal.get("source_runtime_lane") == "v2:signals:paper"]
        ),
        "all_timeframe_visible_signal_rows_count": all_timeframe_visible_count,
        "status": (
            "PAPER_RUNTIME_SIGNALS_VISIBLE_ALL_TIMEFRAME_PARITY_BLOCKED"
            if signals and all_timeframe_visible_count == 0
            else ("ALL_TIMEFRAME_SIGNALS_VISIBLE" if signals else "NO_ALL_TIMEFRAME_SIGNALS_VISIBLE")
        ),
        "publish_contract": {
            "redis_writes_performed": False,
            "old_redis_writes_performed": False,
            "no_live_order_keys": True,
            "intended_v2_redis_keys": intended_keys,
            "public_payload": "operator_runtime/v2_signals/latest/signals_payload.json",
        },
    }


def build_lineage_status(signal_status: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for signal in as_list(signal_status.get("published_signals")):
        item = as_dict(signal)
        ids = as_dict(item.get("lineage_ids"))
        checks = {
            "trainer_prediction_exists": bool(ids.get("trainer_prediction_id")),
            "risk_decision_exists": bool(ids.get("risk_decision_id")),
            "orchestrator_decision_exists": bool(ids.get("orchestrator_decision_id")),
            "paper_intent_exists": bool(ids.get("paper_intent_id")),
            "paper_ledger_exists": bool(ids.get("paper_ledger_id")),
        }
        blockers = [name.replace("_exists", "_MISSING").upper() for name, ok in checks.items() if not ok]
        rows.append(
            {
                "signal_id": item.get("signal_id"),
                "symbol": item.get("symbol"),
                "timeframe": item.get("timeframe"),
                **checks,
                "lineage_ids": ids,
                "required_lineage": "prediction_id -> risk_decision_id -> orchestrator_decision_id -> paper_intent_id -> paper_ledger_id",
                "exact_blocker": blockers[0] if blockers else None,
            }
        )
    missing = [row for row in rows if row.get("exact_blocker")]
    return {
        "schema_version": "v2_all_timeframe_signal_lineage_status_v1",
        "generated_est": est_now(),
        "live_gate": signal_status.get("live_gate") or LIVE_GATE,
        "live_symbols": as_list(signal_status.get("live_symbols")),
        "execution_live_symbols": as_list(signal_status.get("execution_live_symbols")),
        "lineage_rows": rows,
        "chain_complete_count": len(rows) - len(missing),
        "missing_lineage_count": len(missing),
        "status": "ALL_TIMEFRAME_LINEAGE_READY" if rows and not missing else "ALL_TIMEFRAME_LINEAGE_BLOCKED_OR_PARTIAL",
    }


def _feature_status_when_missing(default_status: str) -> str:
    if default_status in {"EVENT_DEPENDENT", "PROVIDER_BLOCKED", "OPERATOR_REQUIRED", "NOT_APPLICABLE_WITH_PROOF"}:
        return default_status
    return "PROVIDER_BLOCKED"


def build_unified_feature_parity_status(
    *,
    store: V2KeyValueStore,
    symbols: list[str],
    timeframes: tuple[str, ...] = REQUIRED_TIMEFRAMES,
    prediction_rows: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    prediction_row_by_scope: dict[tuple[str, str], dict[str, Any]] | None = None
    if prediction_rows is not None:
        prediction_row_by_scope = {
            (str(row.get("symbol") or "").upper(), str(row.get("timeframe") or "")): row
            for row in prediction_rows
            if row.get("symbol") and row.get("timeframe")
        }
        loader = None
        evidence_source = "prediction_rows_feature_summary"
    else:
        loader = V2HybridTrainerDataLoader(io=V2OnlyJsonIO(client=store.client))
        evidence_source = "trainer_loader_build_example"
    coverage_rows: list[dict[str, Any]] = []
    tensor_rows: list[dict[str, Any]] = []
    for symbol in symbols:
        for timeframe in timeframes:
            if prediction_row_by_scope is not None:
                prediction_row = prediction_row_by_scope.get((symbol, timeframe), {})
                missing_names = {str(name) for name in as_list(prediction_row.get("missing_feature_names"))}
                stale_names = {str(name) for name in as_list(prediction_row.get("stale_feature_names"))}
                missing_count = int(to_float(prediction_row.get("missing_feature_count")) or len(missing_names))
                stale_count = int(to_float(prediction_row.get("stale_feature_count")) or len(stale_names))
                data_coverage = to_float(prediction_row.get("data_coverage_percent"))
                full_field_presence_known = data_coverage is not None and data_coverage >= 99.999 and missing_count == 0
                by_name = {
                    field: True
                    for field, _family, _default_status in REQUIRED_FEATURE_FIELDS
                    if full_field_presence_known or (missing_names and field not in missing_names)
                }
                tensor_rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "tensor_id": None,
                        "feature_snapshot_id": prediction_row.get("feature_snapshot_id"),
                        "data_coverage_percent": data_coverage or 0.0,
                        "missing_feature_count": missing_count,
                        "stale_feature_count": stale_count,
                        "row_classification": "PREDICTION_ROW_FEATURE_SUMMARY",
                    }
                )
            else:
                try:
                    assert loader is not None
                    example = loader.build_example(symbol=symbol, timeframe=timeframe)
                    tensor = example.tensor
                    by_name = dict(zip(tensor.feature_names, tensor.values))
                    missing_names = set(tensor.missing_feature_names)
                    stale_names = set(tensor.stale_feature_names)
                    tensor_rows.append(
                        {
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "tensor_id": tensor.tensor_id,
                            "feature_snapshot_id": tensor.feature_snapshot_id,
                            "data_coverage_percent": tensor.data_coverage_percent,
                            "missing_feature_count": len(tensor.missing_feature_names),
                            "stale_feature_count": len(tensor.stale_feature_names),
                            "row_classification": example.row_classification,
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    by_name = {}
                    missing_names = {field for field, _family, _default in REQUIRED_FEATURE_FIELDS}
                    stale_names = set()
                    tensor_rows.append(
                        {
                            "symbol": symbol,
                            "timeframe": timeframe,
                            "tensor_id": None,
                            "feature_snapshot_id": None,
                            "data_coverage_percent": 0.0,
                            "missing_feature_count": len(REQUIRED_FEATURE_FIELDS),
                            "stale_feature_count": 0,
                            "row_classification": f"TENSOR_BUILD_FAILED:{type(exc).__name__}",
                        }
                    )
            for field_name, family, default_status in REQUIRED_FEATURE_FIELDS:
                present = field_name in by_name and field_name not in missing_names
                stale = field_name in stale_names
                if present and default_status != "EVENT_DEPENDENT":
                    status = default_status if default_status in {"REAL_COMPUTED", "REAL_PROVIDER_VALUE"} else "REAL_PROVIDER_VALUE"
                elif present:
                    status = "EVENT_DEPENDENT"
                else:
                    status = _feature_status_when_missing(default_status)
                coverage_rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "field": field_name,
                        "family": family,
                        "status": status,
                        "value_present": present,
                        "stale": stale,
                        "missing_reason": None if present else status,
                        "source_policy": "masked_missing_value_no_silent_zero_fill",
                    }
                )
    blocked = [
        row
        for row in coverage_rows
        if row["status"] in {"PROVIDER_BLOCKED", "OPERATOR_REQUIRED"}
        or (row["status"] == "EVENT_DEPENDENT" and not row["value_present"])
    ]
    by_field: dict[str, dict[str, Any]] = {}
    for row in coverage_rows:
        field = str(row["field"])
        item = by_field.setdefault(
            field,
            {
                "field": field,
                "family": row["family"],
                "rows_checked": 0,
                "value_present_count": 0,
                "stale_count": 0,
                "statuses": {},
                "sample_blockers": [],
            },
        )
        item["rows_checked"] += 1
        if row["value_present"]:
            item["value_present_count"] += 1
        if row["stale"]:
            item["stale_count"] += 1
        item["statuses"][row["status"]] = item["statuses"].get(row["status"], 0) + 1
        if row["missing_reason"] and len(item["sample_blockers"]) < 5:
            item["sample_blockers"].append(
                {
                    "symbol": row["symbol"],
                    "timeframe": row["timeframe"],
                    "missing_reason": row["missing_reason"],
                }
            )
    matrix = {
        "schema_version": "v2_unified_feature_field_coverage_matrix_v1",
        "generated_est": est_now(),
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "feature_parity_evidence_source": evidence_source,
        "required_status_values": [
            "REAL_COMPUTED",
            "REAL_PROVIDER_VALUE",
            "EVENT_DEPENDENT",
            "PROVIDER_BLOCKED",
            "OPERATOR_REQUIRED",
            "NOT_APPLICABLE_WITH_PROOF",
        ],
        "field_rows": coverage_rows,
        "field_rows_count": len(coverage_rows),
        "field_summary": sorted(by_field.values(), key=lambda item: item["field"]),
        "blocked_field_rows_count": len(blocked),
        "status": "UNIFIED_FEATURE_FIELD_COVERAGE_READY" if not blocked else "UNIFIED_FEATURE_FIELD_COVERAGE_BLOCKED_OR_PARTIAL",
    }
    parity = {
        "schema_version": "v2_unified_feature_parity_all_symbols_status_v1",
        "generated_est": est_now(),
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "feature_parity_evidence_source": evidence_source,
        "symbols_covered": symbols,
        "required_timeframes": list(timeframes),
        "required_feature_fields": [
            {"field": field, "family": family, "expected_status_when_present": default}
            for field, family, default in REQUIRED_FEATURE_FIELDS
        ],
        "tensor_rows": tensor_rows,
        "tensor_rows_count": len(tensor_rows),
        "coverage_rows_count": len(coverage_rows),
        "blocked_field_rows_count": len(blocked),
        "data_coverage_avg": (
            sum(to_float(row.get("data_coverage_percent")) or 0.0 for row in tensor_rows) / max(1, len(tensor_rows))
        ),
        "no_silent_zero_fill": True,
        "status": "UNIFIED_FEATURE_PARITY_READY" if not blocked else "UNIFIED_FEATURE_PARITY_BLOCKED_OR_PARTIAL",
    }
    return parity, matrix


def _has_v2_key(store: V2KeyValueStore, key: str) -> bool:
    if not key.startswith("v2:"):
        raise ValueError(f"non_v2_read_rejected:{key}")
    store.audit.reads_attempted += 1
    if store.client is None:
        return False
    try:
        return store.client.get(key) is not None
    except Exception as exc:  # noqa: BLE001
        store.audit.errors.append(f"get_failed:{key}:{type(exc).__name__}")
        return False


def _has_any_tf_key(store: V2KeyValueStore, symbol: str, prefix_template: str) -> bool:
    return any(_has_v2_key(store, prefix_template.format(symbol=symbol, timeframe=tf)) for tf in REQUIRED_TIMEFRAMES)


def build_dynamic_symbol_pipeline_status(
    *,
    store: V2KeyValueStore,
    symbols: list[str],
    prediction_status: Mapping[str, Any],
    signal_status: Mapping[str, Any],
    lineage_status: Mapping[str, Any],
    feature_parity_status: Mapping[str, Any],
) -> dict[str, Any]:
    provenance = resolve_symbols_with_provenance(include_baseline=True)
    rows: list[dict[str, Any]] = []
    prediction_rows = [as_dict(row) for row in as_list(prediction_status.get("prediction_rows"))]
    signals = [as_dict(row) for row in as_list(signal_status.get("published_signals"))]
    lineage_rows = [as_dict(row) for row in as_list(lineage_status.get("lineage_rows"))]
    tensor_rows = [as_dict(row) for row in as_list(feature_parity_status.get("tensor_rows"))]
    for symbol in symbols:
        price_present = store.get_json(price_key(symbol)) is not None
        orderbook_present = store.get_json(f"v2:market:orderbook:{symbol}") is not None
        ohlcv_present = _has_any_tf_key(store, symbol, "v2:market:ohlcv:binance:{symbol}:{timeframe}")
        ta_present = _has_any_tf_key(store, symbol, "v2:features:ta:{symbol}:{timeframe}") or _has_any_tf_key(
            store, symbol, "v2:technical_analysis:{symbol}:{timeframe}"
        )
        unified_present = _has_any_tf_key(store, symbol, "v2:features:latest:{symbol}:{timeframe}") or _has_any_tf_key(
            store, symbol, "v2:unified_features:{symbol}:{timeframe}"
        )
        symbol_predictions = [row for row in prediction_rows if row.get("symbol") == symbol]
        symbol_signals = [row for row in signals if row.get("symbol") == symbol]
        symbol_lineage = [row for row in lineage_rows if row.get("symbol") == symbol]
        symbol_tensors = [row for row in tensor_rows if row.get("symbol") == symbol]
        stages = {
            "symbol_discovery": "READY",
            "ingestors": "READY" if price_present else "BLOCKED_MISSING_PRICE_INGEST",
            "OHLCV": "READY" if ohlcv_present else "BLOCKED_MISSING_OHLCV",
            "orderbook": "READY" if orderbook_present else "BLOCKED_MISSING_ORDERBOOK",
            "TA": "READY" if ta_present else "BLOCKED_MISSING_TA",
            "unified_features": "READY" if unified_present else "BLOCKED_MISSING_UNIFIED_FEATURES",
            "tensor_builder": "READY" if symbol_tensors and all((to_float(row.get("data_coverage_percent")) or 0) > 0 for row in symbol_tensors) else "BLOCKED_TENSOR_COVERAGE",
            "CUDA_trainer": "READY" if any(row.get("trainer_source") == TRAINER_SOURCE_REQUIRED for row in symbol_predictions) else "BLOCKED_MISSING_CUDA_TRAINER_OUTPUT",
            "predictions": "READY" if symbol_predictions and all(row.get("status") == "PRESENT_CURRENT" for row in symbol_predictions) else "BLOCKED_MISSING_OR_STALE_TF_PREDICTIONS",
            "signals": "READY" if len(symbol_signals) >= len(REQUIRED_TIMEFRAMES) else "BLOCKED_MISSING_ALL_TF_SIGNALS",
            "risk": "READY" if symbol_lineage and all(row.get("risk_decision_exists") for row in symbol_lineage) else "BLOCKED_MISSING_RISK_LINEAGE",
            "orchestrator": "READY" if symbol_lineage and all(row.get("orchestrator_decision_exists") for row in symbol_lineage) else "BLOCKED_MISSING_ORCHESTRATOR_LINEAGE",
            "paper_trader": "READY" if symbol_lineage and all(row.get("paper_intent_exists") for row in symbol_lineage) else "BLOCKED_MISSING_PAPER_INTENT_LINEAGE",
            "website": "READY",
        }
        blockers = [f"{stage}:{state}" for stage, state in stages.items() if state != "READY"]
        rows.append(
            {
                "symbol": symbol,
                "baseline_25_retained": symbol in BASELINE_25_SYMBOLS,
                "stages": stages,
                "blockers": blockers,
                "status": "PIPELINE_READY" if not blockers else "PIPELINE_BLOCKED_OR_PARTIAL",
            }
        )
    blocked = [row for row in rows if row["blockers"]]
    return {
        "schema_version": "v2_dynamic_symbol_full_pipeline_contract_status_v1",
        "generated_est": est_now(),
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "dynamic_symbol_count": len(symbols),
        "baseline_25_count": len(BASELINE_25_SYMBOLS),
        "baseline_25_retained": all(symbol in symbols for symbol in BASELINE_25_SYMBOLS),
        "symbol_resolution": provenance,
        "required_pipeline": [
            "symbol discovery",
            "ingestors",
            "OHLCV",
            "orderbook",
            "TA",
            "unified features",
            "tensor builder",
            "CUDA trainer",
            "predictions",
            "signals",
            "risk",
            "orchestrator",
            "paper trader",
            "website",
        ],
        "symbol_rows": rows,
        "blocked_symbol_count": len(blocked),
        "status": "DYNAMIC_SYMBOL_FULL_PIPELINE_READY" if not blocked else "DYNAMIC_SYMBOL_FULL_PIPELINE_BLOCKED_OR_PARTIAL",
        "future_symbol_policy": "all newly discovered symbols must flow through every stage or record exact blocker",
    }


def cuda_prediction_grid_truth_fields(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    current_rows = [row for row in rows if row.get("status") in CURRENT_PREDICTION_STATUSES]
    missing_rows = [row for row in rows if row.get("status") == "MISSING_TF_PREDICTION"]
    stale_rows = [row for row in rows if row.get("status") == "STALE_TF_PREDICTION"]
    actionability_blocked_rows = [row for row in current_rows if row.get("paper_fill_allowed") is False]
    actionability_allowed_rows = [row for row in current_rows if row.get("paper_fill_allowed") is True]
    actionability_unknown_rows = [row for row in current_rows if row.get("paper_fill_allowed") is None]
    block_reason_counts: dict[str, int] = {}
    for row in actionability_blocked_rows:
        reasons = as_list(
            row.get("paper_fill_gate_block_reasons")
            or row.get("paper_fill_block_reasons")
            or row.get("block_reasons")
        )
        if not reasons:
            reasons = ["paper_fill_not_allowed_without_reason"]
        for reason in reasons:
            label = str(reason)
            block_reason_counts[label] = block_reason_counts.get(label, 0) + 1

    def _tf_by_symbol(items: list[Mapping[str, Any]]) -> dict[str, list[str]]:
        out: dict[str, set[str]] = {}
        for item in items:
            symbol = str(item.get("symbol") or "").upper()
            timeframe = str(item.get("timeframe") or "")
            if symbol and timeframe:
                out.setdefault(symbol, set()).add(timeframe)
        return {symbol: [tf for tf in REQUIRED_TIMEFRAMES if tf in timeframes] + sorted(timeframes.difference(REQUIRED_TIMEFRAMES)) for symbol, timeframes in sorted(out.items())}

    coverage_status = "CUDA_PREDICTION_GRID_FULL_COVERAGE"
    if missing_rows or stale_rows:
        coverage_status = "CUDA_PREDICTION_GRID_PARTIAL_MISSING_OR_STALE_TF_ROWS"
    if not current_rows:
        actionability_status = "NO_CURRENT_CUDA_ROWS"
    elif actionability_blocked_rows:
        actionability_status = "PAPER_ACTIONABILITY_BLOCKED_BY_GATES"
    elif actionability_unknown_rows:
        actionability_status = "PAPER_ACTIONABILITY_UNKNOWN"
    else:
        actionability_status = "PAPER_ACTIONABILITY_READY"
    top_block_reason_counts = dict(
        sorted(block_reason_counts.items(), key=lambda item: (-item[1], item[0]))
    )
    return {
        "present_current_prediction_rows_count": len(current_rows),
        "missing_prediction_rows_count": len(missing_rows),
        "stale_prediction_rows_count": len(stale_rows),
        "non_current_prediction_rows_count": len(rows) - len(current_rows),
        "paper_actionability_allowed_rows_count": len(actionability_allowed_rows),
        "paper_actionability_blocked_rows_count": len(actionability_blocked_rows),
        "paper_actionability_unknown_rows_count": len(actionability_unknown_rows),
        "paper_actionability_block_reason_counts": top_block_reason_counts,
        "top_paper_block_reasons": top_block_reason_counts,
        "top_prediction_paper_gate_block_reasons": top_block_reason_counts,
        "missing_prediction_symbols": sorted({str(row.get("symbol")).upper() for row in missing_rows if row.get("symbol")}),
        "missing_prediction_timeframes_by_symbol": _tf_by_symbol(missing_rows),
        "stale_prediction_symbols": sorted({str(row.get("symbol")).upper() for row in stale_rows if row.get("symbol")}),
        "stale_prediction_timeframes_by_symbol": _tf_by_symbol(stale_rows),
        "coverage_status": coverage_status,
        "actionability_status": actionability_status,
    }


def build_cuda_prediction_status(prediction_status: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    required_fields = [
        "prediction_id",
        "generated_est",
        "symbol",
        "timeframe",
        "trainer_source",
        "model_source",
        "selected_action",
        "selected_action_index",
        "action_probabilities",
        "confidence_raw",
        "confidence_calibrated",
        "expected_move_bps",
        "expected_move_after_cost_bps",
        "policy_value",
        "masa_signal",
        "last_price",
        "price_target",
        "price_target_after_cost",
        "price_target_low",
        "price_target_high",
        "stop_reference",
        "take_profit_reference",
        "feature_snapshot_id",
        "data_coverage_percent",
        "missing_feature_count",
        "stale_feature_count",
        "source_lineage",
        "live_gate",
        "live_symbols",
    ]
    for row in as_list(prediction_status.get("prediction_rows")):
        item = as_dict(row)
        reference_only = str(item.get("price_target_validation_status") or "").upper() == "HOLD_REFERENCE_ONLY"
        optional_for_reference = {"stop_reference", "take_profit_reference"} if reference_only else set()
        missing_required = [field for field in required_fields if field not in optional_for_reference and item.get(field) is None]
        rows.append(
            {
                **item,
                "trainer_source_required": TRAINER_SOURCE_REQUIRED,
                "model_source_required": MODEL_SOURCE_REQUIRED,
                "required_field_missing": missing_required,
                "next_remediation": item.get("implementation_task")
                or "publish fresh CUDA trainer prediction with all required fields",
            }
        )
    blockers = [row for row in rows if row.get("status") != "PRESENT_CURRENT" or row.get("required_field_missing")]
    symbols_covered = sorted({str(row.get("symbol")) for row in rows if row.get("symbol")})
    timeframe_set = {str(row.get("timeframe")) for row in rows if row.get("timeframe")}
    timeframes_covered = [tf for tf in REQUIRED_TIMEFRAMES if tf in timeframe_set]
    timeframes_covered.extend(sorted(timeframe_set.difference(REQUIRED_TIMEFRAMES)))
    current_prediction_count = len([row for row in rows if row.get("status") == "PRESENT_CURRENT"])
    grid_truth = cuda_prediction_grid_truth_fields(rows)
    return {
        "schema_version": "v2_all_symbol_all_timeframe_cuda_prediction_status_v1",
        "generated_est": est_now(),
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "trainer_source_required": TRAINER_SOURCE_REQUIRED,
        "model_source_required": MODEL_SOURCE_REQUIRED,
        "required_fields": required_fields,
        "symbols_covered": symbols_covered,
        "timeframes_covered": timeframes_covered,
        "symbols_count": len(symbols_covered),
        "timeframes_count": len(timeframes_covered),
        "paper_directional_collapse_guard_status": as_dict(
            prediction_status.get("paper_directional_collapse_guard_status")
        ),
        "paper_closed_trade_directional_collapse_guard_status": as_dict(
            prediction_status.get("paper_closed_trade_directional_collapse_guard_status")
        ),
        "symbol_scope_reconciliation_status": prediction_status.get("symbol_scope_reconciliation_status"),
        "previous_symbol_count": prediction_status.get("previous_symbol_count"),
        "current_symbol_count": prediction_status.get("current_symbol_count"),
        "removed_symbol_count": prediction_status.get("removed_symbol_count"),
        "removed_symbols": as_list(prediction_status.get("removed_symbols")),
        "removal_reason_by_symbol": as_dict(prediction_status.get("removal_reason_by_symbol")),
        "trainer_trust_reconciliation_limit": prediction_status.get("trainer_trust_reconciliation_limit"),
        "trainer_trust_checks_attempted": prediction_status.get("trainer_trust_checks_attempted"),
        "trainer_trust_checks_skipped_count": prediction_status.get("trainer_trust_checks_skipped_count"),
        "trainer_trust_reconciliation_skipped_symbols": as_list(
            prediction_status.get("trainer_trust_reconciliation_skipped_symbols")
        ),
        "trainer_trust_reconciliation_skipped_reason_by_symbol": as_dict(
            prediction_status.get("trainer_trust_reconciliation_skipped_reason_by_symbol")
        ),
        "expected_runtime_universe_source": prediction_status.get("expected_runtime_universe_source"),
        "prediction_rows": rows,
        "prediction_rows_count": len(rows),
        "current_prediction_count": current_prediction_count,
        "expected_prediction_count": len(symbols_covered) * len(timeframes_covered),
        "blocked_prediction_rows_count": len(blockers),
        **grid_truth,
        "status": "ALL_SYMBOL_ALL_TIMEFRAME_CUDA_PREDICTIONS_READY" if not blockers else "ALL_SYMBOL_ALL_TIMEFRAME_CUDA_PREDICTIONS_BLOCKED_OR_PARTIAL",
    }


def normalize_cuda_prediction_status_counts(cuda_prediction_status: Mapping[str, Any]) -> dict[str, Any]:
    status = dict(cuda_prediction_status)
    symbols_covered = as_list(status.get("symbols_covered"))
    timeframes_covered = as_list(status.get("timeframes_covered"))
    rows = [as_dict(row) for row in as_list(status.get("prediction_rows"))]
    if not symbols_covered:
        symbols_covered = sorted({str(row.get("symbol")) for row in rows if row.get("symbol")})
        status["symbols_covered"] = symbols_covered
    if not timeframes_covered:
        timeframe_set = {str(row.get("timeframe")) for row in rows if row.get("timeframe")}
        timeframes_covered = [tf for tf in REQUIRED_TIMEFRAMES if tf in timeframe_set]
        timeframes_covered.extend(sorted(timeframe_set.difference(REQUIRED_TIMEFRAMES)))
        status["timeframes_covered"] = timeframes_covered
    if status.get("symbols_count") is None:
        status["symbols_count"] = len(symbols_covered)
    if status.get("timeframes_count") is None:
        status["timeframes_count"] = len(timeframes_covered)
    if status.get("expected_prediction_count") is None:
        status["expected_prediction_count"] = len(symbols_covered) * len(timeframes_covered)
    for key, value in cuda_prediction_grid_truth_fields(rows).items():
        if status.get(key) is None:
            status[key] = value
    actionability_reason_counts = as_dict(status.get("paper_actionability_block_reason_counts"))
    if status.get("top_paper_block_reasons") is None:
        status["top_paper_block_reasons"] = actionability_reason_counts
    if status.get("top_prediction_paper_gate_block_reasons") is None:
        status["top_prediction_paper_gate_block_reasons"] = actionability_reason_counts
    return status


def build_expected_move_price_target_remediation_status(
    *,
    expected_move_status: Mapping[str, Any],
    price_status: Mapping[str, Any],
) -> dict[str, Any]:
    telemetry_rows = [as_dict(row) for row in as_list(expected_move_status.get("telemetry_rows"))]
    target_rows = [as_dict(row) for row in as_list(price_status.get("target_rows"))]
    target_by_key = {(row.get("symbol"), row.get("timeframe")): row for row in target_rows}
    rows: list[dict[str, Any]] = []
    for telemetry in telemetry_rows:
        target = target_by_key.get((telemetry.get("symbol"), telemetry.get("timeframe")), {})
        rows.append(
            {
                **telemetry,
                "price_target": target.get("price_target"),
                "price_target_after_cost": target.get("price_target_after_cost"),
                "price_target_low": target.get("price_target_low"),
                "price_target_high": target.get("price_target_high"),
                "stop_reference": target.get("stop_reference"),
                "take_profit_reference": target.get("take_profit_reference"),
                "price_target_validation_status": target.get("validation_status"),
                "formula": target.get("formula"),
                "after_cost_formula": target.get("after_cost_formula"),
                "remediation_required": bool(telemetry.get("missing_reason_if_absent"))
                or target.get("validation_status") not in ("VALID", "HOLD_REFERENCE_ONLY"),
            }
        )
    blocked = [row for row in rows if row["remediation_required"]]
    return {
        "schema_version": "v2_expected_move_price_target_remediation_status_v1",
        "generated_est": est_now(),
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "rows": rows,
        "rows_count": len(rows),
        "blocked_rows_count": len(blocked),
        "status": "EXPECTED_MOVE_PRICE_TARGET_REMEDIATION_READY" if not blocked else "EXPECTED_MOVE_PRICE_TARGET_REMEDIATION_BLOCKED_OR_PARTIAL",
    }


def build_signal_lineage_completion_status(
    *,
    signal_status: Mapping[str, Any],
    lineage_status: Mapping[str, Any],
) -> dict[str, Any]:
    signals = [as_dict(row) for row in as_list(signal_status.get("published_signals"))]
    lineage = [as_dict(row) for row in as_list(lineage_status.get("lineage_rows"))]
    lineage_by_signal = {row.get("signal_id"): row for row in lineage}
    rows = []
    for signal in signals:
        lineage_row = lineage_by_signal.get(signal.get("signal_id"), {})
        rows.append(
            {
                "signal_id": signal.get("signal_id"),
                "prediction_id": signal.get("prediction_id"),
                "risk_decision_id": signal.get("risk_decision_id"),
                "orchestrator_decision_id": signal.get("orchestrator_decision_id"),
                "paper_intent_id": signal.get("paper_intent_id"),
                "paper_ledger_id": signal.get("paper_ledger_id"),
                "symbol": signal.get("symbol"),
                "timeframe": signal.get("timeframe"),
                "action": signal.get("action"),
                "confidence": signal.get("confidence"),
                "expected_move_after_cost_bps": signal.get("expected_move_after_cost_bps"),
                "price_target": signal.get("price_target"),
                "risk_state": signal.get("risk_state"),
                "orchestrator_state": signal.get("orchestrator_state"),
                "paper_state": signal.get("paper_state"),
                "blocked_reason": signal.get("blocked_reason") or lineage_row.get("exact_blocker"),
                "data_coverage_percent": signal.get("data_coverage_percent"),
                "generated_est": signal.get("generated_est"),
                "lineage_complete": lineage_row.get("exact_blocker") is None and bool(lineage_row),
            }
        )
    blocked = [row for row in rows if not row["lineage_complete"]]
    return {
        "schema_version": "v2_all_timeframe_signal_lineage_completion_status_v1",
        "generated_est": est_now(),
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "signals": rows,
        "signal_count": len(rows),
        "missing_lineage_count": len(blocked),
        "status": "ALL_TIMEFRAME_SIGNAL_LINEAGE_COMPLETION_READY" if rows and not blocked else "ALL_TIMEFRAME_SIGNAL_LINEAGE_COMPLETION_BLOCKED_OR_PARTIAL",
    }


def _nvidia_smi_probe() -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total,name",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return {}
    if result.returncode != 0 or not result.stdout.strip():
        return {}
    first = result.stdout.strip().splitlines()[0]
    parts = [part.strip() for part in first.split(",")]
    if len(parts) < 4:
        return {}
    util = to_float(parts[0])
    used = to_float(parts[1])
    total = to_float(parts[2])
    return {
        "current_gpu_utilization": util,
        "current_vram_used_mb": used,
        "current_vram_total_mb": total,
        "gpu_name": parts[3],
    }


def build_resource_utilization_status(store: V2KeyValueStore) -> dict[str, Any]:
    trainer_status = as_dict(store.get_json("v2:trainer:hybrid_cuda:status"))
    trainer_metrics = as_dict(store.get_json("v2:trainer:hybrid_cuda:metrics"))
    resource = as_dict(trainer_status.get("cuda_cpu_resource_utilization")) or as_dict(
        trainer_metrics.get("cuda_cpu_resource_utilization")
    )
    smi = _nvidia_smi_probe()
    cpu_count = os.cpu_count() or 1
    cuda_available = bool(resource.get("cuda_available") or trainer_status.get("cuda_active") or smi)
    payload = {
        "schema_version": "v2_cuda_cpu_resource_utilization_upgrade_status_v1",
        "generated_est": est_now(),
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "cuda_available": cuda_available,
        "gpu_name": resource.get("gpu_name") or smi.get("gpu_name"),
        "current_gpu_utilization": smi.get("current_gpu_utilization") if smi else resource.get("current_gpu_utilization"),
        "current_vram_used_mb": smi.get("current_vram_used_mb") if smi else resource.get("current_vram_used_mb"),
        "target_batch_size": resource.get("target_batch_size"),
        "actual_batch_size": resource.get("actual_batch_size"),
        "dataloader_workers": resource.get("dataloader_workers", 0),
        "pinned_memory": bool(resource.get("pinned_memory", False)),
        "mixed_precision_enabled": bool(resource.get("mixed_precision_enabled", False)),
        "throughput_predictions_per_second": resource.get("throughput_predictions_per_second"),
        "training_steps_per_minute": resource.get("training_steps_per_minute"),
        "tensor_rows_per_second": resource.get("tensor_rows_per_second"),
        "backtest_rows_per_second": resource.get("backtest_rows_per_second"),
        "oom_count": resource.get("oom_count", 0),
        "prefetch_factor": resource.get("prefetch_factor"),
        "persistent_workers": resource.get("persistent_workers", False),
        "gradient_accumulation_steps": resource.get("gradient_accumulation_steps"),
        "cpu_cores_available": cpu_count,
        "feature_tensor_precompute_pool_target_workers": max(1, min(32, cpu_count - 2)),
        "gpu_utilization_target": "50-85% during training bursts",
        "vram_target": "60-80% VRAM when model/batch permits; never OOM",
    }
    blockers = []
    if not cuda_available:
        blockers.append("CUDA_UNAVAILABLE_OR_UNPROVEN")
    if not resource:
        blockers.append("V2_HYBRID_CUDA_TRAINER_RESOURCE_METRICS_MISSING")
    if payload["actual_batch_size"] is None:
        blockers.append("ACTUAL_BATCH_SIZE_MISSING")
    if payload["throughput_predictions_per_second"] is None:
        blockers.append("PREDICTION_THROUGHPUT_MISSING")
    payload["blockers"] = blockers
    payload["status"] = "CUDA_CPU_RESOURCE_UTILIZATION_UPGRADE_READY" if not blockers else "CUDA_CPU_RESOURCE_UTILIZATION_UPGRADE_BLOCKED_OR_PARTIAL"
    return payload


def build_backtest_edge_status(
    prediction_status: Mapping[str, Any],
    resource_status: Mapping[str, Any],
    *,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    ready_for_backtest = prediction_status.get("blocker_count") == 0
    rows_per_second = resource_status.get("backtest_rows_per_second")
    edge_metrics_path = None
    edge_metrics: dict[str, Any] = {}
    metric_summary: dict[str, Any] = {}
    if repo_root is not None:
        edge_metrics_path = repo_root / "v2/frontend/public/v2_native_edge_proof/latest/edge_metrics_summary.json"
        edge_metrics = as_dict(read_json(edge_metrics_path))
        metric_summary = as_dict(edge_metrics.get("metric_summary"))
    label_counts = as_dict(edge_metrics.get("label_counts"))
    verdict = str(edge_metrics.get("verdict") or metric_summary.get("verdict") or "")
    verdict_reason = str(edge_metrics.get("verdict_reason") or metric_summary.get("verdict_reason") or "")
    edge_claimed = verdict.upper() in {"EDGE_PROVEN", "EDGE_CLAIMED", "EDGE_READY"}
    metrics_written = bool(metric_summary)
    blockers = []
    if not ready_for_backtest:
        blockers.append("CURRENT_ALL_TF_CUDA_PREDICTIONS_REQUIRED_BEFORE_EDGE_CLAIM")
    if not metrics_written:
        blockers.append("PARALLEL_BACKTEST_WORKER_METRICS_MISSING")
    if metrics_written and not edge_claimed:
        blockers.append(verdict or "BACKTEST_EDGE_NOT_CLAIMED")
    if metric_summary.get("minimum_sample_satisfied") is False:
        blockers.append("EDGE_SAMPLE_THRESHOLD_NOT_SATISFIED_OR_OPERATOR_REQUIRED")
    ci_lower = to_float(metric_summary.get("after_cost_ci_lower_bps"))
    if ci_lower is not None and ci_lower <= 0:
        blockers.append("EDGE_CI_LOWER_NOT_POSITIVE")
    return {
        "schema_version": "v2_all_symbol_all_timeframe_backtest_edge_status_v1",
        "generated_est": est_now(),
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "symbols_count": len(as_list(prediction_status.get("symbols_covered"))),
        "timeframes": list(REQUIRED_TIMEFRAMES),
        "edge_claimed": False,
        "expectancy_threshold_passed": edge_claimed,
        "ci_lower_threshold_passed": bool(ci_lower is not None and ci_lower > 0 and edge_claimed),
        "sample_count_enough": bool(metric_summary.get("minimum_sample_satisfied") is True),
        "risk_caps_accepted_by_operator": False,
        "worker_started": metrics_written,
        "metrics_written": metrics_written,
        "metrics_source_path": None if edge_metrics_path is None else rel(repo_root or Path.cwd(), edge_metrics_path),
        "metric_generated_at": edge_metrics.get("generated_at"),
        "sample_count": metric_summary.get("sample_count"),
        "after_cost_expectancy_bps": metric_summary.get("expected_move_after_cost_bps") or metric_summary.get("after_cost_pnl_delta"),
        "after_cost_ci_lower_bps": metric_summary.get("after_cost_ci_lower_bps"),
        "false_positive_rate": metric_summary.get("false_positive_rate"),
        "false_negative_rate": metric_summary.get("false_negative_rate"),
        "false_positives": label_counts.get("false_positive"),
        "false_negatives": label_counts.get("false_negative"),
        "correct_trades": label_counts.get("correct_trade"),
        "correct_no_trades": label_counts.get("correct_no_trade") or metric_summary.get("no_trade_correct_count"),
        "drawdown": metric_summary.get("max_drawdown_bps_observed"),
        "confidence_calibration": metric_summary.get("thresholds_satisfied"),
        "edge_verdict": verdict or None,
        "edge_verdict_reason": verdict_reason or None,
        "backtest_rows_per_second": rows_per_second,
        "blockers": blockers,
        "status": "BACKTEST_EDGE_READY_NO_LIVE_APPROVAL" if not blockers else "BACKTEST_EDGE_BLOCKED_NO_EDGE_CLAIM",
    }


def build_website_board_status(
    *,
    prediction_status: Mapping[str, Any],
    signal_lineage_completion: Mapping[str, Any],
    resource_status: Mapping[str, Any],
    website_truth: Mapping[str, Any],
    routes: Iterable[str],
) -> dict[str, Any]:
    route_rows = []
    route_hashes = {row.get("route"): row for row in as_list(website_truth.get("production_route_hashes"))}
    for route in routes:
        prod = as_dict(route_hashes.get(route))
        route_rows.append(
            {
                "route": route,
                "shows_all_symbols": True,
                "shows_all_timeframes": True,
                "shows_action_confidence_expected_move_price_target": True,
                "shows_risk_orchestrator_paper_lineage": True,
                "shows_stale_missing_reason": True,
                "shows_gpu_trainer_throughput": resource_status.get("throughput_predictions_per_second") is not None,
                "last_update_est": est_now(),
                "production_http_status": prod.get("http_status"),
                "production_error": prod.get("error"),
            }
        )
    blockers = []
    if prediction_status.get("blocker_count"):
        blockers.append("PREDICTION_GRID_HAS_BLOCKERS")
    if signal_lineage_completion.get("missing_lineage_count"):
        blockers.append("SIGNAL_LINEAGE_INCOMPLETE")
    if website_truth.get("status") == "DEPLOYMENT_STALE":
        blockers.append("PRODUCTION_DEPLOYMENT_STALE")
    return {
        "schema_version": "v2_all_timeframe_signal_board_website_status_v1",
        "generated_est": est_now(),
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "required_pages": list(routes),
        "route_rows": route_rows,
        "blockers": blockers,
        "status": "ALL_TIMEFRAME_SIGNAL_BOARD_WEBSITE_READY" if not blockers else "ALL_TIMEFRAME_SIGNAL_BOARD_WEBSITE_BLOCKED_OR_PARTIAL",
    }


def build_production_dashboard_truth_status(website_truth: Mapping[str, Any]) -> dict[str, Any]:
    status = website_truth.get("status")
    return {
        "schema_version": "v2_production_dashboard_all_tf_truth_status_v1",
        "generated_est": est_now(),
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "production_base_url": website_truth.get("production_base_url"),
        "route_hashes": website_truth.get("production_route_hashes"),
        "payload_freshness": {
            "public_payload_path": website_truth.get("public_payload_path"),
            "public_payload_hash": website_truth.get("public_payload_hash"),
        },
        "deploy_command_path": "v2/frontend: npm run build && deploy production/dashboard served bundle",
        "claim_scope": website_truth.get("claim_scope"),
        "status": status,
    }


def fetch_production_routes(base_url: str, routes: Iterable[str]) -> list[dict[str, Any]]:
    import urllib.error
    import urllib.request

    out: list[dict[str, Any]] = []
    for route in routes:
        url = f"{base_url.rstrip('/')}{route}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "v2-all-tf-publisher/1.0"})
            with urllib.request.urlopen(req, timeout=10) as response:
                body = response.read(2_000_000)
                out.append(
                    {
                        "route": route,
                        "url": url,
                        "http_status": getattr(response, "status", None),
                        "content_hash": hashlib.sha256(body).hexdigest(),
                        "content_length": len(body),
                        "error": None,
                    }
                )
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            out.append({"route": route, "url": url, "http_status": None, "content_hash": None, "content_length": None, "error": str(exc)})
    return out


def build_website_truth(
    *,
    production_base_url: str,
    routes: Iterable[str],
    signal_public_dir: Path,
    prediction_rows_count: int,
) -> dict[str, Any]:
    production_rows = fetch_production_routes(production_base_url, routes)
    payload_hash = None
    payload_path = signal_public_dir / "signals_payload.json"
    if payload_path.exists():
        payload_hash = hashlib.sha256(payload_path.read_bytes()).hexdigest()
    errors = [row for row in production_rows if row.get("error") or row.get("http_status") not in (200, 304)]
    status = "DEPLOYMENT_STALE" if errors else "PRODUCTION_ROUTE_HASH_CAPTURED_REQUIRES_DEPLOYMENT_HASH_COMPARE"
    return {
        "schema_version": "v2_website_signal_grid_production_truth_status_v1",
        "generated_est": est_now(),
        "live_gate": LIVE_GATE,
        "local_dev_route_signal_grid_status": "PAYLOAD_GRID_READY_ROUTE_CRAWL_REQUIRED",
        "local_dev_prediction_rows_count": prediction_rows_count,
        "production_base_url": production_base_url,
        "production_route_hashes": production_rows,
        "public_payload_path": str(payload_path),
        "public_payload_hash": payload_hash,
        "status": status,
        "claim_scope": "local payload updated; production fixed only after dashboard.wajidali.us serves the matching deployed bundle",
    }


def publish_v2_keys(store: V2KeyValueStore, prediction_status: Mapping[str, Any], signal_status: Mapping[str, Any]) -> dict[str, Any]:
    blocker_writes = 0
    blocker_suppressed = 0
    signal_writes = 0
    integrity_writes = 0
    for row in as_list(prediction_status.get("prediction_rows")):
        item = as_dict(row)
        symbol = str(item.get("symbol") or "")
        timeframe = str(item.get("timeframe") or "")
        if symbol and timeframe and item.get("market_state_id"):
            integrity_payload = {
                "schema_version": "v2_market_state_integrity_current_row_v1",
                "generated_est": est_now(),
                "symbol": symbol,
                "timeframe": timeframe,
                "prediction_id": item.get("prediction_id"),
                "feature_snapshot_id": item.get("feature_snapshot_id"),
                "market_state_id": item.get("market_state_id"),
                "market_state_integrity_score": item.get("market_state_integrity_score"),
                "valid_for_training": item.get("valid_for_training"),
                "valid_for_prediction": item.get("valid_for_prediction"),
                "valid_for_risk": item.get("valid_for_risk"),
                "valid_for_orchestrator": item.get("valid_for_orchestrator"),
                "valid_for_paper": item.get("valid_for_paper"),
                "valid_for_live": item.get("valid_for_live"),
                "decision_cutoff_time_est": item.get("decision_cutoff_time_est"),
                "reject_reasons": as_list(item.get("market_state_reject_reasons")),
                "score_components": as_dict(item.get("market_state_score_components")),
                "source_lineage": as_dict(item.get("market_state_source_lineage")),
                "source_prediction_key": item.get("prediction_redis_key"),
            }
            if store.set_json(market_state_integrity_key(symbol, timeframe), integrity_payload):
                integrity_writes += 1
        if item.get("status") != "MISSING_TF_PREDICTION":
            continue
        blocker_suppressed += 1
    latest_by_symbol: dict[str, dict[str, Any]] = {}
    for signal in as_list(signal_status.get("published_signals")):
        item = as_dict(signal)
        symbol = str(item.get("symbol") or "")
        timeframe = str(item.get("timeframe") or "")
        if symbol and timeframe and store.set_json(signal_paper_key(symbol, timeframe), item):
            signal_writes += 1
        if symbol and (symbol not in latest_by_symbol or timeframe == "1m"):
            latest_by_symbol[symbol] = item
    for symbol, signal in latest_by_symbol.items():
        if store.set_json(signal_latest_key(symbol), signal):
            signal_writes += 1
    return {
        "redis_writes_performed": store.audit.writes_succeeded > 0,
        "blocker_prediction_key_writes": blocker_writes,
        "blocker_prediction_key_writes_suppressed": blocker_suppressed,
        "market_state_integrity_key_writes": integrity_writes,
        "signal_key_writes": signal_writes,
        "old_redis_write_attempts": store.audit.old_redis_write_attempts,
        "keys_written": list(store.audit.keys_written),
        "errors": list(store.audit.errors),
    }


def safety() -> dict[str, Any]:
    return {
        "live_gate": LIVE_GATE,
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "writes_exchange_orders": False,
        "calls_test_order_endpoint": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "writes_legacy_redis": False,
        "writes_old_redis": False,
        "redis_trim_performed": False,
        "legacy_restart_performed": False,
        "raw_credentials_exposed": False,
    }


def build_operator_dashboard_payload(
    *,
    go_no_go: str,
    dynamic_symbol_status: Mapping[str, Any],
    feature_parity_status: Mapping[str, Any],
    cuda_prediction_status: Mapping[str, Any],
    prediction_status: Mapping[str, Any],
    expected_move_status: Mapping[str, Any],
    expected_price_remediation: Mapping[str, Any],
    price_status: Mapping[str, Any],
    signal_status: Mapping[str, Any],
    lineage_status: Mapping[str, Any],
    signal_lineage_completion: Mapping[str, Any],
    resource_status: Mapping[str, Any],
    backtest_status: Mapping[str, Any],
    website_board_status: Mapping[str, Any],
    website_truth: Mapping[str, Any],
    production_dashboard_truth: Mapping[str, Any],
    redis_publish_audit: Mapping[str, Any],
) -> dict[str, Any]:
    live_gate = str(signal_status.get("live_gate") or LIVE_GATE)
    live_symbols = as_list(signal_status.get("live_symbols"))
    execution_live_symbols = as_list(signal_status.get("execution_live_symbols"))
    return {
        "schema_version": "v2_all_timeframe_prediction_signal_price_target_operator_dashboard_payload_v1",
        "generated_est": est_now(),
        "service_id": SERVICE_ID,
        "go_no_go": go_no_go,
        "recommendation": "READY_PAPER_SHADOW_ALL_TF_VISIBLE" if go_no_go == GATE_READY else "BLOCK_ALL_TF_RUNTIME_NOT_COMPLETE",
        "safety": safety(),
        "summary": {
            "prediction_rows_count": prediction_status["prediction_rows_count"],
            "current_prediction_count": prediction_status["current_prediction_count"],
            "stale_prediction_count": prediction_status["stale_prediction_count"],
            "missing_prediction_count": prediction_status["missing_prediction_count"],
            "expected_move_missing_count": expected_move_status["expected_move_missing_count"],
            "invalid_or_missing_price_targets": price_status["invalid_or_missing_count"],
            "signal_count": signal_status["signal_count"],
            "missing_lineage_count": lineage_status["missing_lineage_count"],
            "dynamic_pipeline_blocked_symbol_count": dynamic_symbol_status.get("blocked_symbol_count"),
            "feature_parity_blocked_field_rows_count": feature_parity_status.get("blocked_field_rows_count"),
            "cuda_prediction_blocked_rows_count": cuda_prediction_status.get("blocked_prediction_rows_count"),
            "expected_price_remediation_blocked_rows_count": expected_price_remediation.get("blocked_rows_count"),
            "resource_status": resource_status.get("status"),
            "backtest_status": backtest_status.get("status"),
            "website_board_status": website_board_status.get("status"),
            "production_truth_status": website_truth["status"],
            "live_gate": live_gate,
            "live_symbols": live_symbols,
            "execution_live_symbols": execution_live_symbols,
        },
        "blockers": (
            list(prediction_status.get("implementation_tasks", []))
            + list(resource_status.get("blockers", []))
            + list(backtest_status.get("blockers", []))
        ),
        "phase_status": {
            "dynamic_symbol_full_pipeline_contract_status": dynamic_symbol_status.get("status"),
            "unified_feature_parity_all_symbols_status": feature_parity_status.get("status"),
            "all_symbol_all_timeframe_cuda_prediction_status": cuda_prediction_status.get("status"),
            "expected_move_price_target_remediation_status": expected_price_remediation.get("status"),
            "all_timeframe_signal_lineage_completion_status": signal_lineage_completion.get("status"),
            "cuda_cpu_resource_utilization_upgrade_status": resource_status.get("status"),
            "all_symbol_all_timeframe_backtest_edge_status": backtest_status.get("status"),
            "all_timeframe_signal_board_website_status": website_board_status.get("status"),
            "production_dashboard_all_tf_truth_status": production_dashboard_truth.get("status"),
        },
        "redis_publish_audit": redis_publish_audit,
    }


def build_signals_payload(
    *,
    dynamic_symbol_status: Mapping[str, Any],
    feature_parity_status: Mapping[str, Any],
    cuda_prediction_status: Mapping[str, Any],
    prediction_status: Mapping[str, Any],
    expected_price_remediation: Mapping[str, Any],
    price_status: Mapping[str, Any],
    signal_status: Mapping[str, Any],
    lineage_status: Mapping[str, Any],
    signal_lineage_completion: Mapping[str, Any],
    resource_status: Mapping[str, Any],
    backtest_status: Mapping[str, Any],
    website_board_status: Mapping[str, Any],
    website_truth: Mapping[str, Any],
    production_dashboard_truth: Mapping[str, Any],
) -> dict[str, Any]:
    live_gate = str(signal_status.get("live_gate") or LIVE_GATE)
    live_symbols = as_list(signal_status.get("live_symbols"))
    execution_live_symbols = as_list(signal_status.get("execution_live_symbols"))
    return {
        "schema_version": "v2_realtime_trainer_signal_price_target_all_tf_visibility_v2",
        "worker_id": SERVICE_ID,
        "service_id": SERVICE_ID,
        "generated_at": est_now(),
        "generated_est": est_now(),
        "live_gate": live_gate,
        "live_symbols": live_symbols,
        "execution_live_symbols": execution_live_symbols,
        "safety": safety(),
        "runtime_source_inventory": {
            "schema_version": "v2_all_timeframe_runtime_source_inventory_v1",
            "generated_est": est_now(),
            "missing_or_stale_count": prediction_status["blocker_count"],
            "surfaces": [
                {
                    "surface_id": "trainer_predictions",
                    "source_redis_key": "v2:prediction:{symbol}:{timeframe}",
                    "publisher_process_service": SERVICE_ID,
                    "payload_path": "Redis v2:prediction:* plus operator_runtime/v2_signals/latest/signals_payload.json",
                    "freshness_seconds": None,
                    "symbols_covered": prediction_status["symbols_covered"],
                    "timeframes_covered": prediction_status["timeframes_covered"],
                    "missing_stale_reason": None if prediction_status["blocker_count"] == 0 else "BLOCKERS_PRESENT",
                    "generated_est": est_now(),
                }
            ],
        },
        "dynamic_symbol_full_pipeline_contract": dynamic_symbol_status,
        "unified_feature_parity": feature_parity_status,
        "cuda_prediction_contract": cuda_prediction_status,
        "expected_move_price_target_remediation": expected_price_remediation,
        "prediction_contract": prediction_status,
        "price_target_generation": price_status,
        "signal_publisher": signal_status,
        "signal_lineage": lineage_status,
        "signal_lineage_completion": signal_lineage_completion,
        "cuda_cpu_resource_utilization": resource_status,
        "backtest_edge": backtest_status,
        "website_signal_board": website_board_status,
        "website_deployment_truth": website_truth,
        "production_dashboard_truth": production_dashboard_truth,
        "summary": {
            "symbols_count": len(prediction_status["symbols_covered"]),
            "timeframes_count": len(prediction_status["timeframes_covered"]),
            "prediction_rows_count": prediction_status["prediction_rows_count"],
            "present_prediction_count": prediction_status["current_prediction_count"],
            "current_prediction_count": prediction_status["current_prediction_count"],
            "stale_prediction_count": prediction_status["stale_prediction_count"],
            "missing_prediction_count": prediction_status["missing_prediction_count"],
            "active_signal_count": signal_status["signal_count"],
            "live_gate": live_gate,
            "live_symbols": live_symbols,
            "execution_live_symbols": execution_live_symbols,
        },
    }


@dataclass
class RunResult:
    go_no_go: str
    payloads: dict[str, Any]
    paths_written: list[Path]


def build_packet(
    *,
    paths: PublisherPaths,
    store: V2KeyValueStore,
    stale_seconds: int = DEFAULT_STALE_SECONDS,
    production_base_url: str = "https://dashboard.wajidali.us",
    routes: Iterable[str] = (
        "/ai-predictions",
        "/signals",
        "/trade",
        "/derivatives",
        "/backtests",
        "/system/trainer",
        "/system/orchestrator",
        "/system/risk-controllers",
        "/system/execution",
        "/system/readiness",
    ),
    write_redis: bool = True,
    trainer_trust_reconciliation_limit: int | None = None,
    feature_parity_from_prediction_rows: bool = False,
) -> RunResult:
    symbol_payloads = [
        as_dict(read_json(paths.symbol_universe_path)),
        as_dict(read_json(paths.dynamic_symbol_path)),
    ]
    try:
        symbol_fallback = resolve_symbols_with_provenance(include_baseline=True).get("symbols", [])
    except Exception:  # noqa: BLE001
        symbol_fallback = list(BASELINE_25_SYMBOLS)
    symbols = extract_symbols(symbol_payloads, fallback=symbol_fallback)
    live_context = _live_context_from_store(store)
    prediction_rows = build_prediction_rows(store=store, symbols=symbols, stale_seconds=stale_seconds)
    symbols, prediction_rows, symbol_scope_reconciliation = reconcile_prediction_symbol_scope(
        store=store,
        symbols=symbols,
        rows=prediction_rows,
        timeframes=REQUIRED_TIMEFRAMES,
        trainer_trust_reconciliation_limit=trainer_trust_reconciliation_limit,
    )
    prediction_rows, paper_directional_collapse_guard = apply_paper_directional_collapse_guard(prediction_rows)
    prediction_rows, paper_closed_trade_directional_collapse_guard = apply_paper_closed_trade_directional_collapse_guard(
        prediction_rows,
        store=store,
    )
    prediction_status = build_prediction_status(prediction_rows, symbols, stale_seconds)
    prediction_status.update(symbol_scope_reconciliation)
    prediction_status["paper_directional_collapse_guard_status"] = paper_directional_collapse_guard
    prediction_status["paper_closed_trade_directional_collapse_guard_status"] = paper_closed_trade_directional_collapse_guard
    expected_move_status = build_expected_move_status(prediction_rows)
    price_status = build_price_target_status(prediction_rows)
    expected_price_remediation = build_expected_move_price_target_remediation_status(
        expected_move_status=expected_move_status,
        price_status=price_status,
    )
    feature_parity_status, field_coverage_matrix = build_unified_feature_parity_status(
        store=store,
        symbols=symbols,
        timeframes=REQUIRED_TIMEFRAMES,
        prediction_rows=prediction_rows if feature_parity_from_prediction_rows else None,
    )
    cuda_prediction_status = normalize_cuda_prediction_status_counts(build_cuda_prediction_status(prediction_status))
    signal_status = build_signal_status(prediction_rows, store, live_context=live_context)
    redis_publish_audit = publish_v2_keys(store, prediction_status, signal_status) if write_redis else {
        "redis_writes_performed": False,
        "blocker_prediction_key_writes": 0,
        "signal_key_writes": 0,
        "old_redis_write_attempts": store.audit.old_redis_write_attempts,
        "keys_written": [],
        "errors": [],
    }
    signal_status = dict(signal_status)
    signal_status["publish_contract"] = {
        **as_dict(signal_status.get("publish_contract")),
        "redis_writes_performed": bool(redis_publish_audit["redis_writes_performed"]),
        "old_redis_writes_performed": redis_publish_audit["old_redis_write_attempts"] > 0,
    }
    website_truth = build_website_truth(
        production_base_url=production_base_url,
        routes=routes,
        signal_public_dir=paths.signal_public_dir,
        prediction_rows_count=prediction_status["prediction_rows_count"],
    )
    lineage_status = build_lineage_status(signal_status)
    signal_lineage_completion = build_signal_lineage_completion_status(
        signal_status=signal_status,
        lineage_status=lineage_status,
    )
    resource_status = build_resource_utilization_status(store)
    backtest_status = build_backtest_edge_status(prediction_status, resource_status, repo_root=paths.repo_root)
    website_board_status = build_website_board_status(
        prediction_status=prediction_status,
        signal_lineage_completion=signal_lineage_completion,
        resource_status=resource_status,
        website_truth=website_truth,
        routes=routes,
    )
    production_dashboard_truth = build_production_dashboard_truth_status(website_truth)
    dynamic_symbol_status = build_dynamic_symbol_pipeline_status(
        store=store,
        symbols=symbols,
        prediction_status=prediction_status,
        signal_status=signal_status,
        lineage_status=lineage_status,
        feature_parity_status=feature_parity_status,
    )
    ready = (
        prediction_status["blocker_count"] == 0
        and expected_move_status["expected_move_missing_count"] == 0
        and price_status["invalid_or_missing_count"] == 0
        and signal_status["signal_count"] > 0
        and lineage_status["missing_lineage_count"] == 0
        and website_truth["status"] != "DEPLOYMENT_STALE"
        and dynamic_symbol_status["blocked_symbol_count"] == 0
        and feature_parity_status["blocked_field_rows_count"] == 0
        and cuda_prediction_status["blocked_prediction_rows_count"] == 0
        and expected_price_remediation["blocked_rows_count"] == 0
        and signal_lineage_completion["missing_lineage_count"] == 0
        and resource_status["status"] == "CUDA_CPU_RESOURCE_UTILIZATION_UPGRADE_READY"
        and backtest_status["status"] == "BACKTEST_EDGE_READY_NO_LIVE_APPROVAL"
        and website_board_status["status"] == "ALL_TIMEFRAME_SIGNAL_BOARD_WEBSITE_READY"
        and production_dashboard_truth["status"] != "DEPLOYMENT_STALE"
    )
    go_no_go = GATE_READY if ready else GATE_BLOCKED
    dashboard = build_operator_dashboard_payload(
        go_no_go=go_no_go,
        dynamic_symbol_status=dynamic_symbol_status,
        feature_parity_status=feature_parity_status,
        cuda_prediction_status=cuda_prediction_status,
        prediction_status=prediction_status,
        expected_move_status=expected_move_status,
        expected_price_remediation=expected_price_remediation,
        price_status=price_status,
        signal_status=signal_status,
        lineage_status=lineage_status,
        signal_lineage_completion=signal_lineage_completion,
        resource_status=resource_status,
        backtest_status=backtest_status,
        website_board_status=website_board_status,
        website_truth=website_truth,
        production_dashboard_truth=production_dashboard_truth,
        redis_publish_audit=redis_publish_audit,
    )
    signals_payload = build_signals_payload(
        dynamic_symbol_status=dynamic_symbol_status,
        feature_parity_status=feature_parity_status,
        cuda_prediction_status=cuda_prediction_status,
        prediction_status=prediction_status,
        expected_price_remediation=expected_price_remediation,
        price_status=price_status,
        signal_status=signal_status,
        lineage_status=lineage_status,
        signal_lineage_completion=signal_lineage_completion,
        resource_status=resource_status,
        backtest_status=backtest_status,
        website_board_status=website_board_status,
        website_truth=website_truth,
        production_dashboard_truth=production_dashboard_truth,
    )
    payloads = {
        "dynamic_symbol_full_pipeline_contract_status.json": dynamic_symbol_status,
        "unified_feature_parity_all_symbols_status.json": feature_parity_status,
        "unified_feature_field_coverage_matrix.json": field_coverage_matrix,
        "all_symbol_all_timeframe_cuda_prediction_status.json": cuda_prediction_status,
        "all_timeframe_prediction_publisher_status.json": prediction_status,
        "expected_move_telemetry_status.json": expected_move_status,
        "expected_move_price_target_remediation_status.json": expected_price_remediation,
        "price_target_all_tf_status.json": price_status,
        "all_timeframe_signal_publisher_status.json": signal_status,
        "all_timeframe_signal_lineage_status.json": lineage_status,
        "all_timeframe_signal_lineage_completion_status.json": signal_lineage_completion,
        "cuda_cpu_resource_utilization_upgrade_status.json": resource_status,
        "all_symbol_all_timeframe_backtest_edge_status.json": backtest_status,
        "all_timeframe_signal_board_website_status.json": website_board_status,
        "website_signal_grid_production_truth_status.json": website_truth,
        "production_dashboard_all_tf_truth_status.json": production_dashboard_truth,
        "operator_dashboard_payload.json": dashboard,
        "signals_payload.json": signals_payload,
    }
    payloads = {
        filename: apply_live_runtime_context(payload, live_context)
        for filename, payload in payloads.items()
    }
    return RunResult(go_no_go=go_no_go, payloads=payloads, paths_written=[])

def render_report(payloads: Mapping[str, Any], go_no_go: str) -> str:
    dashboard = as_dict(payloads["operator_dashboard_payload.json"])
    summary = as_dict(dashboard.get("summary"))
    live_gate = str(summary.get("live_gate") or LIVE_GATE)
    live_symbols = as_list(summary.get("live_symbols"))
    execution_live_symbols = as_list(summary.get("execution_live_symbols"))
    lines = [
        "# V2 All-Symbol All-Timeframe Feature Trainer Signal GPU Parity Report\n\n",
        f"Gate: `{go_no_go}`\n",
        f"Generated EST: `{dashboard.get('generated_est')}`\n",
        f"live_gate: `{live_gate}`\n",
        f"live_symbols: `{live_symbols}`\n",
        f"execution_live_symbols: `{execution_live_symbols}`\n\n",
        "## Summary\n\n",
        f"- prediction_rows_count: `{summary.get('prediction_rows_count')}`\n",
        f"- current_prediction_count: `{summary.get('current_prediction_count')}`\n",
        f"- stale_prediction_count: `{summary.get('stale_prediction_count')}`\n",
        f"- missing_prediction_count: `{summary.get('missing_prediction_count')}`\n",
        f"- expected_move_missing_count: `{summary.get('expected_move_missing_count')}`\n",
        f"- invalid_or_missing_price_targets: `{summary.get('invalid_or_missing_price_targets')}`\n",
        f"- signal_count: `{summary.get('signal_count')}`\n",
        f"- missing_lineage_count: `{summary.get('missing_lineage_count')}`\n",
        f"- dynamic_pipeline_blocked_symbol_count: `{summary.get('dynamic_pipeline_blocked_symbol_count')}`\n",
        f"- feature_parity_blocked_field_rows_count: `{summary.get('feature_parity_blocked_field_rows_count')}`\n",
        f"- cuda_prediction_blocked_rows_count: `{summary.get('cuda_prediction_blocked_rows_count')}`\n",
        f"- resource_status: `{summary.get('resource_status')}`\n",
        f"- backtest_status: `{summary.get('backtest_status')}`\n",
        f"- website_board_status: `{summary.get('website_board_status')}`\n",
        f"- production_truth_status: `{summary.get('production_truth_status')}`\n\n",
        "## Safety\n\n",
        "No live/canary enable, no order/test-order/cancel/modify, no leverage/margin mutation, no old Redis write, no legacy restart, no Redis trim.\n",
    ]
    blockers = as_list(dashboard.get("blockers"))
    if blockers:
        lines.append("\n## Blockers\n\n")
        for blocker in blockers[:20]:
            lines.append(f"- {blocker}\n")
        if len(blockers) > 20:
            lines.append(f"- plus `{len(blockers) - 20}` more timeframe remediation tasks\n")
    return "".join(lines)


def write_outputs(paths: PublisherPaths, result: RunResult) -> RunResult:
    written: list[Path] = []
    report = render_report(result.payloads, result.go_no_go)
    for base in (paths.worklog_dir, paths.public_dir):
        for filename, payload in result.payloads.items():
            if filename == "signals_payload.json":
                continue
            path = base / filename
            atomic_write_json(path, payload)
            written.append(path)
        report_path = base / "V2_ALL_TIMEFRAME_PREDICTION_SIGNAL_PRICE_TARGET_PUBLISHER_REPORT.md"
        parity_report_path = base / "V2_ALL_SYMBOL_ALL_TIMEFRAME_FEATURE_TRAINER_SIGNAL_GPU_PARITY_REPORT.md"
        gate_path = base / "GO_NO_GO.md"
        atomic_write_text(report_path, report)
        atomic_write_text(parity_report_path, report)
        atomic_write_text(gate_path, result.go_no_go + "\n")
        written.extend([report_path, parity_report_path, gate_path])
    signal_files = {
        "signals_payload.json": result.payloads["signals_payload.json"],
        "dynamic_symbol_full_pipeline_contract_status.json": result.payloads["dynamic_symbol_full_pipeline_contract_status.json"],
        "unified_feature_parity_all_symbols_status.json": result.payloads["unified_feature_parity_all_symbols_status.json"],
        "all_symbol_all_timeframe_cuda_prediction_status.json": result.payloads["all_symbol_all_timeframe_cuda_prediction_status.json"],
        "expected_move_price_target_remediation_status.json": result.payloads["expected_move_price_target_remediation_status.json"],
        "realtime_prediction_all_tf_contract_status.json": result.payloads["all_timeframe_prediction_publisher_status.json"],
        "price_target_generation_status.json": result.payloads["price_target_all_tf_status.json"],
        "realtime_signal_publisher_status.json": result.payloads["all_timeframe_signal_publisher_status.json"],
        "realtime_signal_lineage_status.json": result.payloads["all_timeframe_signal_lineage_status.json"],
        "all_timeframe_signal_lineage_completion_status.json": result.payloads["all_timeframe_signal_lineage_completion_status.json"],
        "cuda_cpu_resource_utilization_upgrade_status.json": result.payloads["cuda_cpu_resource_utilization_upgrade_status.json"],
        "all_symbol_all_timeframe_backtest_edge_status.json": result.payloads["all_symbol_all_timeframe_backtest_edge_status.json"],
        "all_timeframe_signal_board_website_status.json": result.payloads["all_timeframe_signal_board_website_status.json"],
        "website_deployment_truth_status.json": result.payloads["website_signal_grid_production_truth_status.json"],
        "production_dashboard_all_tf_truth_status.json": result.payloads["production_dashboard_all_tf_truth_status.json"],
    }
    for base in (paths.signal_public_dir, paths.signal_local_dir):
        for filename, payload in signal_files.items():
            path = base / filename
            atomic_write_json(path, payload)
            written.append(path)
    result.paths_written.extend(written)
    return result
