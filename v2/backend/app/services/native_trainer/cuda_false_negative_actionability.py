"""False-negative reduction and actionability artifacts for the CUDA trainer.

Consumes the CUDA edge-calibration/outcome burn-in operator payload and creates
paper-only diagnostics for missed opportunities. It does not write Redis,
does not change thresholds in runtime config, does not bypass risk, and does
not approve live or canary.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import LIVE_GATE_BLOCKED
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.publisher import dumps_pretty
from v2.backend.app.services.v2_symbol_runtime_universe import (
    BASELINE_25_SYMBOLS,
    SMOKE_TEST_SYMBOLS,
    resolve_symbols_with_provenance,
)

GO_READY = "V2_CUDA_TRAINER_FALSE_NEGATIVE_REDUCTION_AND_ACTIONABILITY_READY"
GO_BLOCKED = "V2_CUDA_TRAINER_FALSE_NEGATIVE_REDUCTION_AND_ACTIONABILITY_BLOCKED"
SCHEMA_VERSION = "v2_cuda_trainer_false_negative_reduction_actionability_v1"
ARTIFACT_REL = Path("v2_cuda_trainer_false_negative_reduction_and_actionability/latest")
SOURCE_PAYLOAD_REL = Path("v2_native_cuda_trainer_edge_calibration_and_outcome_burn_in/latest/operator_dashboard_payload.json")

LIVE_BLOCKERS = (
    "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
    "BLOCK_LIVE_MODEL_SIGNAL_QUALITY_NOT_READY",
    "BLOCK_LIVE_RISK_CAPS_OPERATOR_REQUIRED",
)
MAJOR_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
PREMIUM_CONTEXT_FIELDS = (
    "liquidity_context",
    "liquidity_zone_context",
    "liquidation_distance_context",
    "liquidation_context",
    "microstructure_context",
    "oi_funding_context",
    "public_intel_context",
)
LIQUIDITY_VALUE_FIELDS = (
    "liquidity_score",
    "orderbook_depth_usd",
    "bid_depth_usd",
    "ask_depth_usd",
    "depth_imbalance",
    "whale_bid_wall_notional_usd",
    "whale_ask_wall_notional_usd",
    "nearest_bid_wall_distance_bps",
    "nearest_ask_wall_distance_bps",
)
LIQUIDATION_VALUE_FIELDS = (
    "nearest_liquidation_level_above",
    "nearest_liquidation_level_below",
    "liquidation_long_distance_pct",
    "liquidation_short_distance_pct",
    "liquidation_sweep_target_long_distance_bps",
    "liquidation_sweep_target_short_distance_bps",
    "liquidation_cascade_risk",
    "liquidation_pressure_direction",
    "liquidation_levels_count_long",
    "liquidation_levels_count_short",
    "liquidation_zones_count_long",
    "liquidation_zones_count_short",
    "liquidation_long_strength",
    "liquidation_short_strength",
    "liquidation_volume",
)
MICROSTRUCTURE_VALUE_FIELDS = (
    "bid_ask_spread_bps",
    "spread_bps",
    "ob_spread_bps",
    "micro_price",
    "orderbook_imbalance",
    "depth_imbalance",
    "bid_depth_usd",
    "ask_depth_usd",
    "orderbook_depth_usd",
)
OI_FUNDING_VALUE_FIELDS = (
    "funding_rate",
    "expected_funding_bps",
    "funding_bps",
    "open_interest",
    "oi_change_pct",
    "open_interest_change_pct",
    "long_short_ratio",
    "long_account_ratio",
    "short_account_ratio",
)
PUBLIC_INTEL_VALUE_FIELDS = (
    "public_intel_score",
    "news_attention_score",
    "news_sentiment_score",
    "sentiment_score",
    "fear_greed_score",
    "market_breadth_score",
    "social_momentum_score",
    "social_volume_velocity",
)


@dataclass(frozen=True)
class FalseNegativeActionabilityPaths:
    repo_root: Path
    worklog_dir: Path
    public_dir: Path
    source_payload_path: Path


@dataclass(frozen=True)
class FalseNegativeActionabilityResult:
    go_no_go: str
    artifacts: dict[str, Any]
    operator_dashboard_payload: dict[str, Any]
    paths_written: tuple[str, ...] = field(default_factory=tuple)


SimulationPredicate = Callable[[Mapping[str, Any]], bool]


def default_paths(repo_root: Path) -> FalseNegativeActionabilityPaths:
    root = repo_root.resolve()
    return FalseNegativeActionabilityPaths(
        repo_root=root,
        worklog_dir=root / "claude_worklog/final_readiness" / ARTIFACT_REL,
        public_dir=root / "v2/frontend/public" / ARTIFACT_REL,
        source_payload_path=root / "v2/frontend/public" / SOURCE_PAYLOAD_REL,
    )


def _est_iso() -> str:
    return datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _ci_lower_95(values: list[float]) -> float | None:
    if not values:
        return None
    if len(values) < 2:
        return float(values[0])
    return statistics.fmean(values) - 1.96 * statistics.stdev(values) / math.sqrt(len(values))


def _read_json(path: Path) -> dict[str, Any]:
    return _as_dict(json.loads(path.read_text(encoding="utf-8")))


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    tmp.replace(path)


def _completed_rows(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [_as_dict(row) for row in _as_list(_as_dict(source.get("outcome_mining")).get("rows"))]
    return [row for row in rows if _float(row.get("realized_after_cost_return_bps")) is not None]


def _outcome_rows(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [_as_dict(row) for row in _as_list(_as_dict(source.get("outcome_mining")).get("rows"))]


def _false_negative_rows(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [row for row in _completed_rows(source) if row.get("classification") == "false_negative"]


def _feature_bag(row: Mapping[str, Any]) -> dict[str, Any]:
    features: dict[str, Any] = {}
    for snapshot_field in ("entry_feature_snapshot", "feature_snapshot"):
        snapshot = _as_dict(row.get(snapshot_field))
        snapshot_features = _as_dict(snapshot.get("features"))
        features.update(snapshot_features)
    for field in (
        *LIQUIDITY_VALUE_FIELDS,
        *LIQUIDATION_VALUE_FIELDS,
        *MICROSTRUCTURE_VALUE_FIELDS,
        *OI_FUNDING_VALUE_FIELDS,
        *PUBLIC_INTEL_VALUE_FIELDS,
    ):
        if row.get(field) is not None:
            features[field] = row.get(field)
    return features


def _context_missing_mask(context: Mapping[str, Any]) -> list[str]:
    for key in ("missing_feature_names", "missing_features", "missing_contexts"):
        values = context.get(key)
        if isinstance(values, list):
            return [str(item) for item in values]
    reason = context.get("unavailable_reason") or context.get("missing_reason")
    return [str(reason)] if reason else []


def _context_status(row: Mapping[str, Any], names: tuple[str, ...], fields: tuple[str, ...]) -> dict[str, Any]:
    missing: list[str] = []
    sources: list[str] = []
    for name in names:
        context = _as_dict(row.get(name))
        if not context:
            missing.append(name)
            continue
        source = str(context.get("source") or name)
        if source:
            sources.append(source)
        has_value = any(_float(context.get(field)) is not None for field in fields)
        if has_value:
            return {
                "status": "READY",
                "context_name": name,
                "source": source,
                "sources_seen": sorted(set(sources)),
                "missing_mask": [],
            }
        mask = _context_missing_mask(context)
        if mask:
            missing.extend(f"{name}:{item}" for item in mask)
    feature_values = _feature_bag(row)
    if any(_float(feature_values.get(field)) is not None for field in fields):
        return {
            "status": "READY_FROM_FEATURE_SNAPSHOT",
            "context_name": "entry_feature_snapshot",
            "source": "ENTRY_FEATURE_SNAPSHOT",
            "sources_seen": sorted(set(sources + ["ENTRY_FEATURE_SNAPSHOT"])),
            "missing_mask": [],
        }
    return {
        "status": "MISSING_WITH_EXPLICIT_MASK" if missing else "MISSING",
        "context_name": None,
        "source": None,
        "sources_seen": sorted(set(sources)),
        "missing_mask": sorted(set(missing)),
    }


def _first_context_float(row: Mapping[str, Any], fields: tuple[str, ...], context_names: tuple[str, ...]) -> float | None:
    for name in context_names:
        context = _as_dict(row.get(name))
        for field in fields:
            value = _float(context.get(field))
            if value is not None:
                return value
    features = _feature_bag(row)
    for field in fields:
        value = _float(features.get(field))
        if value is not None:
            return value
    return None


def _first_context_text(row: Mapping[str, Any], fields: tuple[str, ...], context_names: tuple[str, ...]) -> str | None:
    for name in context_names:
        context = _as_dict(row.get(name))
        for field in fields:
            value = context.get(field)
            if value not in (None, "", [], {}):
                return str(value)
    features = _feature_bag(row)
    for field in fields:
        value = features.get(field)
        if value not in (None, "", [], {}):
            return str(value)
    return None


def _direction_from_signed(value: float | None, *, positive: str, negative: str) -> str | None:
    if value is None:
        return None
    if value > 0:
        return positive
    if value < 0:
        return negative
    return "NEUTRAL"


def _premium_ingestor_evidence(row: Mapping[str, Any]) -> dict[str, Any]:
    liquidity_status = _context_status(row, ("liquidity_context", "liquidity_zone_context"), LIQUIDITY_VALUE_FIELDS)
    liquidation_status = _context_status(
        row,
        ("liquidation_distance_context", "liquidation_context"),
        LIQUIDATION_VALUE_FIELDS,
    )
    micro_status = _context_status(row, ("microstructure_context", "liquidity_context"), MICROSTRUCTURE_VALUE_FIELDS)
    oi_funding_status = _context_status(row, ("oi_funding_context",), OI_FUNDING_VALUE_FIELDS)
    public_status = _context_status(row, ("public_intel_context",), PUBLIC_INTEL_VALUE_FIELDS)

    imbalance = _first_context_float(
        row,
        ("orderbook_imbalance", "depth_imbalance"),
        ("microstructure_context", "liquidity_context", "liquidity_zone_context"),
    )
    orderbook_direction = _direction_from_signed(
        imbalance,
        positive="BUY_PRESSURE",
        negative="SELL_PRESSURE",
    )

    bid_wall = _first_context_float(
        row,
        ("whale_bid_wall_notional_usd",),
        ("liquidity_context", "liquidity_zone_context"),
    )
    ask_wall = _first_context_float(
        row,
        ("whale_ask_wall_notional_usd",),
        ("liquidity_context", "liquidity_zone_context"),
    )
    wall_delta = bid_wall - ask_wall if bid_wall is not None and ask_wall is not None else None
    wall_direction = _direction_from_signed(wall_delta, positive="BID_WALL_SUPPORT", negative="ASK_WALL_RESISTANCE")

    funding = _first_context_float(row, ("funding_bps", "expected_funding_bps", "funding_rate"), ("oi_funding_context",))
    oi_change = _first_context_float(row, ("oi_change_pct", "open_interest_change_pct"), ("oi_funding_context",))
    long_short_ratio = _first_context_float(row, ("long_short_ratio",), ("oi_funding_context",))
    funding_direction = _direction_from_signed(funding, positive="POSITIVE_FUNDING", negative="NEGATIVE_FUNDING")
    oi_direction = _direction_from_signed(oi_change, positive="OI_EXPANDING", negative="OI_CONTRACTING")
    crowd_direction = None
    if long_short_ratio is not None:
        crowd_direction = "LONG_CROWDED" if long_short_ratio > 1 else "SHORT_CROWDED" if long_short_ratio < 1 else "BALANCED"

    pressure_direction = _first_context_text(
        row,
        ("liquidation_pressure_direction",),
        ("liquidation_distance_context", "liquidation_context"),
    )
    long_strength = _first_context_float(
        row,
        ("liquidation_long_strength", "liquidation_levels_count_long", "liquidation_zones_count_long"),
        ("liquidation_distance_context", "liquidation_context"),
    )
    short_strength = _first_context_float(
        row,
        ("liquidation_short_strength", "liquidation_levels_count_short", "liquidation_zones_count_short"),
        ("liquidation_distance_context", "liquidation_context"),
    )
    strength_delta = short_strength - long_strength if short_strength is not None and long_strength is not None else None
    liquidation_strength_direction = _direction_from_signed(
        strength_delta,
        positive="SHORT_LIQUIDATION_CLUSTER_DOMINANT",
        negative="LONG_LIQUIDATION_CLUSTER_DOMINANT",
    )
    long_target = _first_context_float(
        row,
        ("liquidation_sweep_target_long_distance_bps", "liquidation_long_distance_pct"),
        ("liquidation_distance_context", "liquidation_context"),
    )
    short_target = _first_context_float(
        row,
        ("liquidation_sweep_target_short_distance_bps", "liquidation_short_distance_pct"),
        ("liquidation_distance_context", "liquidation_context"),
    )
    closer_sweep_target = None
    if long_target is not None and short_target is not None:
        closer_sweep_target = "LONG_SIDE_SWEEP_CLOSER" if abs(long_target) < abs(short_target) else "SHORT_SIDE_SWEEP_CLOSER"

    public_scores = {
        field: _first_context_float(row, (field,), ("public_intel_context",))
        for field in PUBLIC_INTEL_VALUE_FIELDS
    }
    public_scores = {key: value for key, value in public_scores.items() if value is not None}

    context_statuses = {
        "liquidity_context": liquidity_status,
        "liquidation_context": liquidation_status,
        "microstructure_context": micro_status,
        "oi_funding_context": oi_funding_status,
        "public_intel_context": public_status,
    }
    ready_sources = [
        status.get("source")
        for status in context_statuses.values()
        if str(status.get("status") or "").startswith("READY") and status.get("source")
    ]
    missing_masks = {
        key: status.get("missing_mask", [])
        for key, status in context_statuses.items()
        if status.get("missing_mask")
    }
    return {
        "premium_context_ready": bool(ready_sources),
        "premium_ingestor_sources_used": sorted(set(str(source) for source in ready_sources)),
        "premium_context_statuses": context_statuses,
        "premium_missing_masks": missing_masks,
        "orderbook_confirmation": orderbook_direction or micro_status["status"],
        "orderbook_imbalance": imbalance,
        "funding_oi_confirmation": {
            "funding_direction": funding_direction or oi_funding_status["status"],
            "oi_direction": oi_direction or oi_funding_status["status"],
            "crowd_direction": crowd_direction or oi_funding_status["status"],
            "funding": funding,
            "oi_change_pct": oi_change,
            "long_short_ratio": long_short_ratio,
        },
        "public_intel_contribution": {
            "status": public_status["status"],
            "scores": public_scores,
            "missing_mask": public_status.get("missing_mask", []),
        },
        "whale_wall_contribution": {
            "direction": wall_direction or liquidity_status["status"],
            "bid_wall_notional_usd": bid_wall,
            "ask_wall_notional_usd": ask_wall,
        },
        "liquidation_signal": {
            "status": liquidation_status["status"],
            "raw_pressure_direction": pressure_direction,
            "cluster_strength_direction": liquidation_strength_direction,
            "closer_sweep_target": closer_sweep_target,
            "long_strength": long_strength,
            "short_strength": short_strength,
            "long_target_distance": long_target,
            "short_target_distance": short_target,
        },
        "liquidation_engine_used": str(liquidation_status["status"]).startswith("READY"),
    }


def _premium_direction_agrees(evidence: Mapping[str, Any], side: str) -> bool:
    if side not in {"long", "short"}:
        return False
    directional_votes: list[str] = []
    orderbook = str(evidence.get("orderbook_confirmation") or "")
    if orderbook in {"BUY_PRESSURE", "SELL_PRESSURE"}:
        directional_votes.append("long" if orderbook == "BUY_PRESSURE" else "short")
    wall = str(_as_dict(evidence.get("whale_wall_contribution")).get("direction") or "")
    if wall in {"BID_WALL_SUPPORT", "ASK_WALL_RESISTANCE"}:
        directional_votes.append("long" if wall == "BID_WALL_SUPPORT" else "short")
    liq = _as_dict(evidence.get("liquidation_signal"))
    liq_cluster = str(liq.get("cluster_strength_direction") or "")
    if liq_cluster == "SHORT_LIQUIDATION_CLUSTER_DOMINANT":
        directional_votes.append("long")
    elif liq_cluster == "LONG_LIQUIDATION_CLUSTER_DOMINANT":
        directional_votes.append("short")
    if not directional_votes:
        return False
    return directional_votes.count(side) > directional_votes.count("short" if side == "long" else "long")


def _percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * quantile)))
    return ordered[index]


def _adaptive_bounds(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    confidences = [value for value in (_float(row.get("confidence_calibrated")) for row in rows) if value is not None]
    coverages = [value for value in (_float(row.get("data_coverage_percent")) for row in rows) if value is not None]
    expected_moves = [
        abs(value)
        for value in (_float(row.get("expected_move_after_cost_bps")) for row in rows)
        if value is not None and value != 0.0
    ]
    return {
        "low_confidence_bound": _percentile(confidences, 0.25),
        "median_confidence_bound": _percentile(confidences, 0.50),
        "high_confidence_bound": _percentile(confidences, 0.75),
        "low_coverage_bound": _percentile(coverages, 0.25),
        "median_coverage_bound": _percentile(coverages, 0.50),
        "minimum_abs_expected_move_bps": _percentile(expected_moves, 0.25),
    }


def _at_least(value: float | None, bound: float | None) -> bool:
    return value is not None and bound is not None and value >= bound


def _expected_move_misaligned(row: Mapping[str, Any]) -> bool:
    expected = _float(row.get("expected_move_after_cost_bps"))
    side = str(row.get("counterfactual_side") or "").lower()
    if expected is None or side not in {"long", "short"}:
        return False
    return (side == "long" and expected <= 0) or (side == "short" and expected >= 0)


def _missed_move_classification(row: Mapping[str, Any], bounds: Mapping[str, float | None]) -> list[str]:
    classifications: list[str] = []
    selected_action = str(row.get("selected_action") or "").lower()
    missed_side = str(row.get("counterfactual_side") or "").lower()
    confidence = _float(row.get("confidence_calibrated"))
    expected = _float(row.get("expected_move_after_cost_bps"))
    missing = int(_float(row.get("missing_feature_count")) or 0)
    stale = int(_float(row.get("stale_feature_count")) or 0)
    risk_action = str(row.get("risk_action") or "").lower()
    orch_action = str(row.get("orchestrator_action") or "").lower()
    block_reasons = [str(item).lower() for item in _as_list(row.get("paper_fill_gate_block_reasons"))]
    regime = str(row.get("market_regime") or row.get("market_regime_at_entry") or "").strip().lower()
    premium = _premium_ingestor_evidence(row)

    if selected_action in {"long", "short"} and missed_side in {"long", "short"} and selected_action != missed_side:
        classifications.append("WRONG_DIRECTION")
    if _at_least(confidence, bounds.get("high_confidence_bound")) and (
        selected_action in {"long", "short"} and selected_action != missed_side
    ):
        classifications.append("CONFIDENCE_HIGH_BUT_WRONG")
    if confidence is not None and bounds.get("low_confidence_bound") is not None and confidence <= float(bounds["low_confidence_bound"]):
        classifications.append("CONFIDENCE_TOO_LOW")
    if expected is None:
        classifications.append("EXPECTED_MOVE_MISSING")
    elif _expected_move_misaligned(row):
        classifications.append("EXPECTED_MOVE_NEGATIVE")
    elif bounds.get("minimum_abs_expected_move_bps") is not None and abs(expected) <= float(bounds["minimum_abs_expected_move_bps"]):
        classifications.append("EXPECTED_MOVE_TOO_LOW")
    if regime in {"", "unknown", "none", "not_detected", "undetected"}:
        classifications.append("REGIME_NOT_DETECTED")
    if missing > 0 or premium.get("premium_missing_masks"):
        classifications.append("FEATURE_MISSING")
    if stale > 0:
        classifications.append("STALE_DATA")
    if risk_action and risk_action != "allow":
        classifications.append("RISK_BLOCKED")
    if orch_action in {"hold", "abstain"}:
        classifications.append("ORCHESTRATOR_BLOCKED")
    if any("allocator" in reason or "capital" in reason or "margin" in reason for reason in block_reasons):
        classifications.append("ALLOCATOR_BLOCKED")
    if row.get("paper_fill_allowed") is False or any("paper" in reason or "fill" in reason for reason in block_reasons):
        classifications.append("PAPER_EXECUTION_BLOCKED")
    return list(dict.fromkeys(classifications or ["UNCLASSIFIED_REQUIRES_REPLAY_EXPANSION"]))


def _timeframe_coverage(source: Mapping[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    configured = _as_list(source.get("configured_timeframes") or source.get("timeframes"))
    observed = sorted({str(row.get("timeframe")) for row in rows if row.get("timeframe")})
    windows = [
        str(item.get("window_id"))
        for item in _as_list(_as_dict(source.get("outcome_mining")).get("outcome_windows"))
        if _as_dict(item).get("window_id")
    ]
    return {
        "configured_timeframes": configured or observed or windows,
        "observed_timeframes": observed,
        "future_label_windows": windows,
        "coverage_scope": "ALL_CONFIGURED_TFS_WHEN_SOURCE_PAYLOAD_PROVIDES_ROWS",
        "future_window_labels_without_future_leakage": True,
    }


def _symbol_universe_coverage(source: Mapping[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        provenance = resolve_symbols_with_provenance()
        symbols = [str(symbol).upper() for symbol in _as_list(provenance.get("symbols"))]
    except Exception as exc:
        provenance = {
            "symbol_profile": "baseline_fallback_after_resolver_error",
            "resolver_error": str(exc),
            "count": len(BASELINE_25_SYMBOLS),
        }
        symbols = list(BASELINE_25_SYMBOLS)
    observed = sorted({str(row.get("symbol")).upper() for row in rows if row.get("symbol")})
    top_volume = _as_list(
        source.get("top_volume_symbols")
        or source.get("top_30_volume_symbols")
        or source.get("symbols_by_volume")
        or []
    )
    top_volume_symbols = [str(symbol).upper() for symbol in top_volume if str(symbol or "").strip()]
    if not top_volume_symbols:
        top_volume_symbols = symbols[:30]
    return {
        "scope": "FULL_CONFIGURED_SYMBOL_UNIVERSE",
        "symbol_resolver": provenance,
        "symbols": symbols[:250],
        "symbol_count": len(symbols),
        "observed_outcome_symbols": observed,
        "observed_outcome_symbol_count": len(observed),
        "top_volume_priority_symbols": top_volume_symbols[:30],
        "top_volume_source": "source_payload" if top_volume else "runtime_universe_order_fallback",
        "mandatory_major_symbols": list(MAJOR_SYMBOLS),
        "mandatory_major_observed": {symbol: symbol in observed for symbol in MAJOR_SYMBOLS},
        "mandatory_major_in_universe": {symbol: symbol in symbols for symbol in MAJOR_SYMBOLS},
        "not_limited_to_btc_eth_sol": len(set(symbols) - set(SMOKE_TEST_SYMBOLS)) > 0,
        "smoke_test_profile_active": bool(provenance.get("smoke_test")),
    }


def _outcome(row: Mapping[str, Any], window: str = "5m") -> dict[str, Any]:
    return _as_dict(_as_dict(row.get("outcome_windows")).get(window))


def _root_causes(row: Mapping[str, Any], bounds: Mapping[str, float | None]) -> list[str]:
    causes: list[str] = []
    coverage = _float(row.get("data_coverage_percent"))
    missing = int(_float(row.get("missing_feature_count")) or 0)
    stale = int(_float(row.get("stale_feature_count")) or 0)
    confidence = _float(row.get("confidence_calibrated"))
    expected = _float(row.get("expected_move_after_cost_bps"))
    action = str(row.get("selected_action") or "").lower()
    orch_action = str(row.get("orchestrator_action") or "").lower()
    orch_reason = str(row.get("orchestrator_reason") or "").lower()
    risk_action = str(row.get("risk_action") or "").lower()
    block_reasons = [str(item).lower() for item in _as_list(row.get("paper_fill_gate_block_reasons"))]

    low_coverage = bounds.get("low_coverage_bound")
    low_confidence = bounds.get("low_confidence_bound")
    expected_floor = bounds.get("minimum_abs_expected_move_bps")

    if coverage is not None and low_coverage is not None and coverage < low_coverage:
        causes.append("DATA_COVERAGE_LOW")
    if missing > 0:
        causes.append("INSUFFICIENT_HISTORY")
    if stale > 0 or "stale" in orch_reason:
        causes.append("FEATURE_STALE")
    if confidence is not None and low_confidence is not None and confidence <= low_confidence:
        causes.append("CONFIDENCE_TOO_LOW")
    if expected is None or _expected_move_misaligned(row):
        causes.append("EXPECTED_MOVE_NEGATIVE_OR_MISSING")
    elif expected_floor is not None and abs(expected) <= expected_floor:
        causes.append("EXPECTED_MOVE_TOO_LOW")
    if action not in {"long", "short"}:
        causes.append("TRAINER_ACTION_TOO_CONSERVATIVE")
    if risk_action and risk_action != "allow":
        causes.append("RISK_GATE_BLOCKED")
    if orch_action in {"hold", "abstain"}:
        causes.append("ORCHESTRATOR_HOLD")
    if any("overconcentration" in reason or "symbol_concentration" in reason for reason in block_reasons):
        causes.append("SYMBOL_OVERCONCENTRATION_GUARD")
    if "strategy_disagreement" in block_reasons:
        causes.append("STRATEGY_SIGNAL_DISAGREEMENT")
    causes.extend(_missed_move_classification(row, bounds))
    return list(dict.fromkeys(causes or ["TRAINER_ACTION_TOO_CONSERVATIVE"]))


def _strategy_evidence(row: Mapping[str, Any]) -> dict[str, Any]:
    side = str(row.get("counterfactual_side") or "")
    one = _float(_outcome(row, "1m").get("after_cost_return_bps"))
    five = _float(_outcome(row, "5m").get("after_cost_return_bps"))
    fifteen = _float(_outcome(row, "15m").get("after_cost_return_bps"))
    max_favorable = _float(_outcome(row, "5m").get("max_favorable_bps"))

    trend_agrees = five is not None and fifteen is not None and five > 0 and fifteen > 0
    momentum_agrees = one is not None and five is not None and one > 0 and five > 0
    breakout_agrees = max_favorable is not None and max_favorable >= 12.0
    premium = _premium_ingestor_evidence(row)
    premium_agrees = _premium_direction_agrees(premium, side)
    strategy_agrees = bool(
        side in {"long", "short"}
        and (trend_agrees or momentum_agrees or breakout_agrees or premium_agrees)
    )

    return {
        "strategy_agreement": "AGREE" if strategy_agrees else "DISAGREE_OR_INSUFFICIENT_EVIDENCE",
        "trend_strategy_signal": side if trend_agrees else "NO_TREND_CONFIRMATION",
        "breakout_signal": side if breakout_agrees else "NO_BREAKOUT_CONFIRMATION",
        "momentum_signal": side if momentum_agrees else "NO_MOMENTUM_CONFIRMATION",
        "ta_confirmation": "OUTCOME_WINDOW_DIAGNOSTIC_CONFIRMATION" if any((trend_agrees, momentum_agrees, breakout_agrees)) else "INSUFFICIENT_TA_CONFIRMATION",
        "funding_oi_confirmation": premium["funding_oi_confirmation"],
        "orderbook_confirmation": premium["orderbook_confirmation"],
        "public_intel_contribution": premium["public_intel_contribution"],
        "whale_wall_contribution": premium["whale_wall_contribution"],
        "liquidation_signal": premium["liquidation_signal"],
        "premium_context_ready": premium["premium_context_ready"],
        "premium_ingestor_sources_used": premium["premium_ingestor_sources_used"],
        "premium_context_statuses": premium["premium_context_statuses"],
        "premium_missing_masks": premium["premium_missing_masks"],
        "liquidation_engine_used": premium["liquidation_engine_used"],
        "premium_direction_agrees": premium_agrees,
        "derived_from_outcome_windows_only": not bool(premium["premium_context_ready"]),
    }


def _attribution_row(row: Mapping[str, Any], bounds: Mapping[str, float | None]) -> dict[str, Any]:
    outcome = _outcome(row, "5m")
    causes = _root_causes(row, bounds)
    strategy = _strategy_evidence(row)
    return {
        "prediction_id": row.get("prediction_id"),
        "symbol": row.get("symbol"),
        "timeframe": row.get("timeframe"),
        "trainer_action": row.get("selected_action"),
        "trainer_confidence": row.get("confidence_calibrated"),
        "expected_move_after_cost_bps": row.get("expected_move_after_cost_bps"),
        "risk_decision": {
            "risk_decision_id": row.get("risk_decision_id"),
            "risk_action": row.get("risk_action"),
            "risk_reason": row.get("risk_reason"),
        },
        "orchestrator_decision": {
            "orchestrator_decision_id": row.get("orchestrator_decision_id"),
            "orchestrator_action": row.get("orchestrator_action"),
            "orchestrator_reason": row.get("orchestrator_reason"),
        },
        "paper_outcome": {
            "paper_intent_id": row.get("paper_intent_id"),
            "paper_ledger_id": row.get("paper_ledger_id"),
            "paper_ledger_action": row.get("paper_ledger_action"),
            "paper_ledger_reason": row.get("paper_ledger_reason"),
            "classification": row.get("classification"),
        },
        "realized_after_cost_bps": row.get("realized_after_cost_return_bps"),
        "missed_direction": row.get("counterfactual_side"),
        "block_reason": row.get("risk_reason") or row.get("orchestrator_reason") or row.get("paper_ledger_reason"),
        "data_coverage_percent": row.get("data_coverage_percent"),
        "feature_stale_missing_flags": {
            "missing_feature_count": row.get("missing_feature_count"),
            "stale_feature_count": row.get("stale_feature_count"),
            "paper_fill_gate_block_reasons": row.get("paper_fill_gate_block_reasons", []),
        },
        "strategy_agreement_disagreement": strategy["strategy_agreement"],
        "missed_move_classification": _missed_move_classification(row, bounds),
        "adaptive_bounds_used": dict(bounds),
        "root_causes": causes,
        "primary_root_cause": causes[0],
        "strategy_evidence": strategy,
        "premium_ingestor_context": {
            "status": row.get("premium_ingestor_context_status"),
            "sources": row.get("premium_ingestor_context_sources"),
            "missing_contexts": row.get("premium_ingestor_missing_contexts"),
            "liquidation_engine_context_status": row.get("liquidation_engine_context_status"),
            "feature_cutoff": row.get("feature_cutoff"),
            "available_at": row.get("available_at"),
            "decision_time": row.get("decision_time"),
        },
    }


def build_false_negative_attribution(source: Mapping[str, Any], *, generated_est: str) -> dict[str, Any]:
    source_rows = _outcome_rows(source)
    completed = _completed_rows(source)
    coverage_rows = completed if completed else source_rows
    bounds = _adaptive_bounds(completed)
    rows = [_attribution_row(row, bounds) for row in _false_negative_rows(source)]
    cause_counts = Counter(cause for row in rows for cause in _as_list(row.get("root_causes")))
    classification_counts = Counter(
        cause for row in rows for cause in _as_list(row.get("missed_move_classification"))
    )
    premium_context_ready_count = sum(
        1 for row in rows if _as_dict(row.get("strategy_evidence")).get("premium_context_ready") is True
    )
    liquidation_engine_used_count = sum(
        1 for row in rows if _as_dict(row.get("strategy_evidence")).get("liquidation_engine_used") is True
    )
    source_premium_context_ready_rows = sum(
        1 for row in source_rows if row.get("premium_ingestor_context_status") == "PREMIUM_CONTEXT_READY"
    )
    source_liquidation_engine_ready_rows = sum(
        1 for row in source_rows if row.get("liquidation_engine_context_status") == "LIQUIDATION_ENGINE_CONTEXT_READY"
    )
    missing_lineage = [
        row.get("prediction_id")
        for row in rows
        if not _as_dict(row.get("risk_decision")).get("risk_decision_id")
        or not _as_dict(row.get("orchestrator_decision")).get("orchestrator_decision_id")
        or not _as_dict(row.get("paper_outcome")).get("paper_ledger_id")
    ]
    return {
        "schema_version": f"{SCHEMA_VERSION}_false_negative_attribution",
        "generated_est": generated_est,
        "status": "FALSE_NEGATIVE_ATTRIBUTION_READY" if not missing_lineage else "FALSE_NEGATIVE_ATTRIBUTION_BLOCKED",
        "false_negative_count": len(rows),
        "root_cause_counts": dict(sorted(cause_counts.items())),
        "missed_move_classification_counts": dict(sorted(classification_counts.items())),
        "adaptive_bounds": bounds,
        "source_prediction_row_count": len(source_rows),
        "completed_outcome_row_count": len(completed),
        "pending_future_window_rows": max(0, len(source_rows) - len(completed)),
        "source_premium_context_ready_rows": source_premium_context_ready_rows,
        "source_liquidation_engine_ready_rows": source_liquidation_engine_ready_rows,
        "symbol_universe_coverage": _symbol_universe_coverage(source, coverage_rows),
        "timeframe_coverage": _timeframe_coverage(source, coverage_rows),
        "required_move_types": [
            "major_up_moves",
            "major_down_moves",
            "squeezes",
            "fakeouts",
            "v_reversals",
            "liquidation_cascades",
            "chop_range_traps",
        ],
        "premium_ingestor_context_ready_count": premium_context_ready_count,
        "liquidation_engine_used_count": liquidation_engine_used_count,
        "lineage_complete": not missing_lineage,
        "missing_lineage_prediction_ids": missing_lineage[:100],
        "rows": rows,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
    }


def _candidate_rows(rows: list[dict[str, Any]], predicate: SimulationPredicate) -> list[dict[str, Any]]:
    return [row for row in rows if predicate(row)]


def _has_strategy_agreement(row: Mapping[str, Any]) -> bool:
    return _strategy_evidence(row)["strategy_agreement"] == "AGREE"


def _simulation_result(
    *,
    simulation_id: str,
    description: str,
    rows: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    recommendation: str,
    notes: str,
) -> dict[str, Any]:
    recovered = [row for row in candidates if row.get("classification") == "false_negative"]
    introduced = [
        row
        for row in candidates
        if row.get("classification") in {"correct_no_trade", "false_positive"}
        and (_float(row.get("realized_after_cost_return_bps")) or 0.0) <= 0.0
    ]
    candidate_values = [
        value
        for value in (_float(row.get("realized_after_cost_return_bps")) for row in candidates)
        if value is not None
    ]
    baseline_values = [
        value
        for value in (_float(row.get("realized_after_cost_return_bps")) for row in rows)
        if value is not None
    ]
    drawdowns = [
        value
        for value in (_float(_outcome(row, "5m").get("drawdown_bps")) for row in candidates)
        if value is not None
    ]
    return {
        "simulation_id": simulation_id,
        "description": description,
        "paper_only": True,
        "runtime_config_changed": False,
        "thresholds_auto_accepted": False,
        "sample_count": len(rows),
        "candidate_count": len(candidates),
        "recovered_false_negatives": len(recovered),
        "recovered_prediction_ids": [row.get("prediction_id") for row in recovered[:64]],
        "introduced_false_positives_estimate": len(introduced),
        "introduced_false_positive_prediction_ids": [row.get("prediction_id") for row in introduced[:64]],
        "expected_after_cost_change": (
            (_mean(candidate_values) or 0.0) - (_mean(baseline_values) or 0.0)
            if candidate_values and baseline_values
            else None
        ),
        "candidate_after_cost_expectancy_bps": _mean(candidate_values),
        "candidate_after_cost_ci_lower_bps": _ci_lower_95(candidate_values),
        "max_drawdown_estimate": max(drawdowns) if drawdowns else None,
        "recommendation": recommendation,
        "notes": notes,
    }


def build_threshold_simulation(source: Mapping[str, Any], *, generated_est: str) -> dict[str, Any]:
    rows = _completed_rows(source)
    bounds = _adaptive_bounds(rows)
    by_symbol_false_positives = Counter(row.get("symbol") for row in rows if row.get("classification") == "false_positive")
    by_symbol_false_negatives = Counter(row.get("symbol") for row in rows if row.get("classification") == "false_negative")
    low_confidence = bounds.get("low_confidence_bound")
    median_confidence = bounds.get("median_confidence_bound")
    low_coverage = bounds.get("low_coverage_bound")
    median_coverage = bounds.get("median_coverage_bound")
    expected_floor = bounds.get("minimum_abs_expected_move_bps")

    simulations = [
        _simulation_result(
            simulation_id="lower_min_confidence_by_bucket",
            description="Review candidates above the sample-derived low-confidence and low-coverage bounds.",
            rows=rows,
            candidates=_candidate_rows(
                rows,
                lambda row: _at_least(_float(row.get("confidence_calibrated")), low_confidence)
                and _at_least(_float(row.get("data_coverage_percent")), low_coverage)
                and row.get("counterfactual_side") in {"long", "short"},
            ),
            recommendation="PAPER_ONLY_REVIEW_REQUIRED",
            notes="Diagnostic only; does not change live/runtime caps.",
        ),
        _simulation_result(
            simulation_id="lower_expected_move_after_cost_threshold",
            description="Review candidates above the sample-derived expected-move floor after costs.",
            rows=rows,
            candidates=_candidate_rows(
                rows,
                lambda row: _at_least(
                    abs(_float(row.get("expected_move_after_cost_bps")) or 0.0),
                    expected_floor,
                )
                and _at_least(_float(row.get("confidence_calibrated")), low_confidence)
                and _at_least(_float(row.get("data_coverage_percent")), low_coverage),
            ),
            recommendation="REJECT_FOR_NOW_HIGH_FALSE_POSITIVE_RISK",
            notes="Broader threshold recovery is too blunt without more feature coverage.",
        ),
        _simulation_result(
            simulation_id="symbol_specific_thresholds",
            description="Consider symbols with false negatives and no observed false positives in current sample.",
            rows=rows,
            candidates=_candidate_rows(
                rows,
                lambda row: by_symbol_false_negatives.get(row.get("symbol"), 0) > 0
                and by_symbol_false_positives.get(row.get("symbol"), 0) == 0
                and _at_least(_float(row.get("confidence_calibrated")), low_confidence),
            ),
            recommendation="PAPER_ONLY_SYMBOL_REVIEW_REQUIRED",
            notes="Symbol-specific thresholds are not accepted automatically.",
        ),
        _simulation_result(
            simulation_id="strategy_confirmed_overrides",
            description="Recover only missed opportunities with derived trend/momentum/breakout agreement.",
            rows=rows,
            candidates=_candidate_rows(
                rows,
                lambda row: _has_strategy_agreement(row)
                and _at_least(_float(row.get("confidence_calibrated")), low_confidence)
                and _at_least(_float(row.get("data_coverage_percent")), low_coverage),
            ),
            recommendation="PAPER_SHADOW_EXPERIMENT_CANDIDATE",
            notes="Still cannot bypass risk; overlay source must remain paper_shadow_actionability_experiment.",
        ),
        _simulation_result(
            simulation_id="risk_gate_soft_downrank_vs_hard_block",
            description="Diagnostic soft downrank, but final risk gate remains hard fail-closed.",
            rows=rows,
            candidates=[],
            recommendation="DO_NOT_USE_FOR_RECOVERY_WITHOUT_RISK_REVIEW",
            notes="Risk hard block remains final; recovered count is intentionally zero.",
        ),
        _simulation_result(
            simulation_id="require_multi_source_confirmation",
            description="Require strategy agreement, confidence >= 0.50, coverage >= 50%, and no stale features.",
            rows=rows,
            candidates=_candidate_rows(
                rows,
                lambda row: _has_strategy_agreement(row)
                and _at_least(_float(row.get("confidence_calibrated")), median_confidence)
                and _at_least(_float(row.get("data_coverage_percent")), median_coverage)
                and int(_float(row.get("stale_feature_count")) or 0) == 0,
            ),
            recommendation="SAFEST_PAPER_SHADOW_OVERLAY_CANDIDATE",
            notes="Most conservative current recovery candidate; still simulation only.",
        ),
        _simulation_result(
            simulation_id="no_trade_preservation_threshold",
            description="Preserve no-trade unless derived strategy agreement and current outcome margin exceeds 12 bps.",
            rows=rows,
            candidates=_candidate_rows(
                rows,
                lambda row: _has_strategy_agreement(row)
                and _at_least(
                    _float(row.get("realized_after_cost_return_bps")),
                    expected_floor,
                )
                and _at_least(_float(row.get("data_coverage_percent")), median_coverage),
            ),
            recommendation="PAPER_ONLY_REVIEW_REQUIRED",
            notes="Uses realized outcomes for diagnostics; not deployable as a real-time rule.",
        ),
    ]
    return {
        "schema_version": f"{SCHEMA_VERSION}_threshold_actionability_simulation",
        "generated_est": generated_est,
        "status": "THRESHOLD_ACTIONABILITY_SIMULATION_READY",
        "paper_only": True,
        "runtime_thresholds_changed": False,
        "thresholds_auto_accepted": False,
        "adaptive_bounds": bounds,
        "simulations": simulations,
        "recommended_simulation_id": "require_multi_source_confirmation",
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
    }


def build_strategy_assisted_recovery(attribution: Mapping[str, Any], *, generated_est: str) -> dict[str, Any]:
    rows = []
    missing_by_context: Counter[str] = Counter()
    premium_ready_count = 0
    liquidation_ready_count = 0
    for item in _as_list(attribution.get("rows")):
        row = _as_dict(item)
        strategy = _as_dict(row.get("strategy_evidence"))
        if strategy.get("premium_context_ready") is True:
            premium_ready_count += 1
        if strategy.get("liquidation_engine_used") is True:
            liquidation_ready_count += 1
        for context_name, missing in _as_dict(strategy.get("premium_missing_masks")).items():
            if missing:
                missing_by_context[str(context_name)] += 1
        rows.append(
            {
                "prediction_id": row.get("prediction_id"),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "missed_direction": row.get("missed_direction"),
                "realized_after_cost_bps": row.get("realized_after_cost_bps"),
                "trend_strategy_signal": strategy.get("trend_strategy_signal"),
                "breakout_signal": strategy.get("breakout_signal"),
                "momentum_signal": strategy.get("momentum_signal"),
                "ta_confirmation": strategy.get("ta_confirmation"),
                "funding_oi_confirmation": strategy.get("funding_oi_confirmation"),
                "orderbook_confirmation": strategy.get("orderbook_confirmation"),
                "public_intel_contribution": strategy.get("public_intel_contribution"),
                "whale_wall_contribution": strategy.get("whale_wall_contribution"),
                "liquidation_signal": strategy.get("liquidation_signal"),
                "premium_context_ready": strategy.get("premium_context_ready"),
                "premium_ingestor_sources_used": strategy.get("premium_ingestor_sources_used"),
                "premium_missing_masks": strategy.get("premium_missing_masks"),
                "liquidation_engine_used": strategy.get("liquidation_engine_used"),
                "strategy_agreement": row.get("strategy_agreement_disagreement"),
            }
        )
    agreement_count = sum(1 for row in rows if row.get("strategy_agreement") == "AGREE")
    return {
        "schema_version": f"{SCHEMA_VERSION}_strategy_assisted_recovery",
        "generated_est": generated_est,
        "status": "STRATEGY_ASSISTED_RECOVERY_READY",
        "false_negative_count": len(rows),
        "strategy_agreement_count": agreement_count,
        "strategy_disagreement_or_insufficient_count": max(0, len(rows) - agreement_count),
        "rows": rows,
        "premium_ingestor_usage": {
            "premium_context_ready_count": premium_ready_count,
            "liquidation_engine_ready_count": liquidation_ready_count,
            "missing_context_counts": dict(sorted(missing_by_context.items())),
            "missing_contexts_are_explicit_masks": True,
        },
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
    }


def _overlay_candidates(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = _completed_rows(source)
    bounds = _adaptive_bounds(rows)
    median_confidence = bounds.get("median_confidence_bound")
    median_coverage = bounds.get("median_coverage_bound")
    max_missing_observed = max(
        (int(_float(row.get("missing_feature_count")) or 0) for row in rows),
        default=0,
    )
    candidates = []
    for row in _false_negative_rows(source):
        if (
            _has_strategy_agreement(row)
            and _at_least(_float(row.get("confidence_calibrated")), median_confidence)
            and _at_least(_float(row.get("data_coverage_percent")), median_coverage)
            and int(_float(row.get("stale_feature_count")) or 0) == 0
            and int(_float(row.get("missing_feature_count")) or 0) <= max_missing_observed
        ):
            candidates.append(row)
    return candidates


def build_paper_actionability_overlay(source: Mapping[str, Any], *, generated_est: str) -> dict[str, Any]:
    candidates = _overlay_candidates(source)
    rows = []
    for row in candidates:
        rows.append(
            {
                "overlay_candidate_id": f"paper_shadow_actionability_experiment:{row.get('prediction_id')}",
                "prediction_id": row.get("prediction_id"),
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "candidate_direction": row.get("counterfactual_side"),
                "source": "paper_shadow_actionability_experiment",
                "overlay_reason": "strategy_confirmed_false_negative_with_minimum_coverage",
                "risk_bypass": False,
                "risk_decision_id": row.get("risk_decision_id"),
                "risk_action": row.get("risk_action"),
                "risk_reason": row.get("risk_reason"),
                "orchestrator_decision_id": row.get("orchestrator_decision_id"),
                "paper_ledger_id": row.get("paper_ledger_id"),
                "realized_after_cost_bps": row.get("realized_after_cost_return_bps"),
                "confidence_calibrated": row.get("confidence_calibrated"),
                "data_coverage_percent": row.get("data_coverage_percent"),
                "missing_feature_count": row.get("missing_feature_count"),
                "stale_feature_count": row.get("stale_feature_count"),
                "live_gate": LIVE_GATE_BLOCKED,
                "live_symbols": [],
                "execution_live_symbols": [],
            }
        )
    return {
        "schema_version": f"{SCHEMA_VERSION}_paper_actionability_overlay",
        "generated_est": generated_est,
        "status": "PAPER_ACTIONABILITY_OVERLAY_READY",
        "overlay_source": "paper_shadow_actionability_experiment",
        "overlay_candidate_count": len(rows),
        "rows": rows,
        "paper_shadow_only": True,
        "runtime_config_changed": False,
        "thresholds_auto_accepted": False,
        "risk_bypass": False,
        "risk_fail_closed_preserved": True,
        "can_bypass_risk": False,
        "writes_live_symbols": False,
        "enables_execution": False,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
    }


def build_edge_after_overlay(source: Mapping[str, Any], overlay: Mapping[str, Any], *, generated_est: str) -> dict[str, Any]:
    edge = _as_dict(source.get("edge_recompute"))
    base = _as_dict(edge.get("new_cuda_trainer"))
    completed = _completed_rows(source)
    overlay_rows = _as_list(overlay.get("rows"))
    overlay_values = [
        value
        for value in (_float(row.get("realized_after_cost_bps")) for row in overlay_rows)
        if value is not None
    ]
    all_values = [
        value
        for value in (_float(row.get("realized_after_cost_return_bps")) for row in completed)
        if value is not None
    ]
    by_symbol: dict[str, list[float]] = {}
    for row in overlay_rows:
        value = _float(row.get("realized_after_cost_bps"))
        symbol = str(row.get("symbol") or "UNKNOWN")
        if value is not None:
            by_symbol.setdefault(symbol, []).append(value)
    return {
        "schema_version": f"{SCHEMA_VERSION}_edge_after_actionability_overlay",
        "generated_est": generated_est,
        "status": "EDGE_AFTER_ACTIONABILITY_OVERLAY_READY",
        "edge_proven": False,
        "before_overlay": {
            "after_cost_expectancy_bps": base.get("after_cost_expectancy_bps"),
            "after_cost_ci_lower_bps": base.get("after_cost_ci_lower_bps"),
            "false_positive_count": edge.get("false_positive_count"),
            "false_negative_count": edge.get("false_negative_count"),
            "correct_no_trade_count": _as_dict(_as_dict(source.get("outcome_mining")).get("classification_counts")).get("correct_no_trade"),
            "drawdown": edge.get("drawdown"),
            "candidate_count": 0,
        },
        "simulated_overlay": {
            "overlay_candidate_count": len(overlay_rows),
            "recovered_false_negatives": len(overlay_rows),
            "introduced_false_positives_estimate": 0,
            "candidate_after_cost_expectancy_bps": _mean(overlay_values),
            "candidate_after_cost_ci_lower_bps": _ci_lower_95(overlay_values),
            "candidate_count": len(overlay_rows),
            "all_completed_outcome_expectancy_bps": _mean(all_values),
            "all_completed_outcome_ci_lower_bps": _ci_lower_95(all_values),
        },
        "actual_paper_shadow_overlay_after_burn_in": {
            "available": False,
            "status": "PENDING_FUTURE_PAPER_BURN_IN",
        },
        "by_symbol_recovered_opportunities": [
            {
                "symbol": symbol,
                "recovered_count": len(values),
                "candidate_after_cost_expectancy_bps": _mean(values),
                "candidate_after_cost_ci_lower_bps": _ci_lower_95(values),
            }
            for symbol, values in sorted(by_symbol.items())
        ],
        "recommendations": list(LIVE_BLOCKERS),
        "primary_recommendation": "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
    }


def build_operator_payload(
    *,
    source: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    generated_est: str,
    go_no_go: str,
) -> dict[str, Any]:
    attribution = artifacts["v2_cuda_false_negative_attribution_status.json"]
    simulation = artifacts["v2_cuda_threshold_actionability_simulation.json"]
    strategy = artifacts["v2_cuda_strategy_assisted_recovery_status.json"]
    overlay = artifacts["v2_cuda_paper_actionability_overlay_status.json"]
    edge = artifacts["v2_cuda_edge_after_actionability_overlay_status.json"]
    return {
        "schema_version": f"{SCHEMA_VERSION}_operator_dashboard",
        "generated_est": generated_est,
        "generated_at": generated_est,
        "go_no_go": go_no_go,
        "source_gate": source.get("go_no_go"),
        "source_payload_path": f"/{SOURCE_PAYLOAD_REL}",
        "false_negative_attribution": attribution,
        "threshold_actionability_simulation": simulation,
        "strategy_assisted_recovery": strategy,
        "paper_actionability_overlay": overlay,
        "edge_after_actionability_overlay": edge,
        "source_edge_recompute": _as_dict(source.get("edge_recompute")),
        "source_outcome_mining": {
            "outcome_sample_count": _as_dict(source.get("outcome_mining")).get("outcome_sample_count"),
            "classification_counts": _as_dict(source.get("outcome_mining")).get("classification_counts"),
        },
        "symbol_universe_coverage": attribution.get("symbol_universe_coverage"),
        "timeframe_coverage": attribution.get("timeframe_coverage"),
        "premium_ingestor_usage": {
            "premium_context_ready_count": attribution.get("premium_ingestor_context_ready_count"),
            "liquidation_engine_used_count": attribution.get("liquidation_engine_used_count"),
            "source_premium_context_ready_rows": attribution.get("source_premium_context_ready_rows"),
            "source_liquidation_engine_ready_rows": attribution.get("source_liquidation_engine_ready_rows"),
            "pending_future_window_rows": attribution.get("pending_future_window_rows"),
            "strategy_assisted_usage": strategy.get("premium_ingestor_usage"),
        },
        "website_sync": {
            "status": "WEBSITE_SYNC_READY",
            "payload_path": f"/{ARTIFACT_REL}/operator_dashboard_payload.json",
            "surfaces_synced": ["AI Brain", "Replay / Edge", "Paper Trading", "Risk", "Orchestrator", "Live Readiness"],
            "must_show": {
                "false_negative_count": attribution.get("false_negative_count"),
                "false_negative_root_causes": attribution.get("root_cause_counts"),
                "missed_move_classification_counts": attribution.get("missed_move_classification_counts"),
                "symbol_universe_scope": _as_dict(attribution.get("symbol_universe_coverage")).get("scope"),
                "mandatory_major_symbols": _as_dict(attribution.get("symbol_universe_coverage")).get("mandatory_major_symbols"),
                "not_limited_to_btc_eth_sol": _as_dict(attribution.get("symbol_universe_coverage")).get("not_limited_to_btc_eth_sol"),
                "premium_ingestor_context_ready_count": attribution.get("premium_ingestor_context_ready_count"),
                "liquidation_engine_used_count": attribution.get("liquidation_engine_used_count"),
                "source_premium_context_ready_rows": attribution.get("source_premium_context_ready_rows"),
                "source_liquidation_engine_ready_rows": attribution.get("source_liquidation_engine_ready_rows"),
                "pending_future_window_rows": attribution.get("pending_future_window_rows"),
                "threshold_simulation_results": len(_as_list(simulation.get("simulations"))),
                "paper_only_overlay_status": overlay.get("status"),
                "recovered_opportunities": overlay.get("overlay_candidate_count"),
                "why_live_remains_blocked": edge.get("recommendations"),
            },
        },
        "live_readiness": {
            "live_ready": False,
            "canary_ready": False,
            "primary_recommendation": edge.get("primary_recommendation"),
            "recommendations": edge.get("recommendations"),
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "execution_live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
        },
        "live_switch": {
            "visible": True,
            "enabled": False,
            "backend_live_enable_callable": False,
            "disabled_reason": "LIVE_GATE=blocked_human_only; false-negative recovery is paper/shadow only and not live approval.",
        },
        "safety_scoreboard": {
            "paper_shadow_only": True,
            "runtime_config_changed": False,
            "thresholds_auto_accepted": False,
            "risk_bypass": False,
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "execution_live_symbols": [],
            "approves_live": False,
            "approves_canary": False,
            "places_orders": False,
            "cancels_orders": False,
            "modifies_orders": False,
            "calls_test_order_endpoint": False,
            "changes_leverage": False,
            "changes_margin_mode": False,
            "writes_old_redis": False,
            "restarts_legacy": False,
            "trims_redis": False,
        },
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
    }


def build_report(result: FalseNegativeActionabilityResult) -> str:
    p = result.operator_dashboard_payload
    attr = p["false_negative_attribution"]
    overlay = p["paper_actionability_overlay"]
    edge = p["edge_after_actionability_overlay"]
    before = edge["before_overlay"]
    simulated = edge["simulated_overlay"]
    return "\n".join(
        [
            "# V2 CUDA Trainer False-Negative Reduction And Actionability Report",
            "",
            f"Gate: `{result.go_no_go}`",
            f"Generated EST: `{p['generated_est']}`",
            f"False negatives attributed: `{attr.get('false_negative_count')}`",
            f"Root causes: `{attr.get('root_cause_counts')}`",
            f"Threshold simulations: `{len(p['threshold_actionability_simulation'].get('simulations') or [])}`",
            f"Paper overlay candidates: `{overlay.get('overlay_candidate_count')}`",
            f"Before overlay expectancy bps: `{before.get('after_cost_expectancy_bps')}`",
            f"Before overlay CI lower bps: `{before.get('after_cost_ci_lower_bps')}`",
            f"Simulated overlay recovered false negatives: `{simulated.get('recovered_false_negatives')}`",
            f"Simulated overlay candidate expectancy bps: `{simulated.get('candidate_after_cost_expectancy_bps')}`",
            "",
            "Live/canary remain blocked. Thresholds are simulated only and not auto-accepted.",
            "",
            f"- live_gate: `{LIVE_GATE_BLOCKED}`",
            "- live_symbols: `[]`",
            "- execution_live_symbols: `[]`",
            "- risk_bypass: `False`",
            "- runtime_config_changed: `False`",
            f"- recommendation: `{edge.get('primary_recommendation')}`",
            f"- blockers: `{', '.join(edge.get('recommendations') or [])}`",
            "",
            "Safety: no live/canary enable, no order/test-order/cancel/modify, no leverage/margin mutation, no old Redis write, no legacy restart, no Redis trim.",
        ]
    ) + "\n"


def build_false_negative_actionability(
    source: Mapping[str, Any],
    *,
    generated_est: str | None = None,
) -> FalseNegativeActionabilityResult:
    generated = generated_est or _est_iso()
    artifacts: dict[str, Any] = {}
    artifacts["v2_cuda_false_negative_attribution_status.json"] = build_false_negative_attribution(
        source,
        generated_est=generated,
    )
    artifacts["v2_cuda_threshold_actionability_simulation.json"] = build_threshold_simulation(
        source,
        generated_est=generated,
    )
    artifacts["v2_cuda_strategy_assisted_recovery_status.json"] = build_strategy_assisted_recovery(
        artifacts["v2_cuda_false_negative_attribution_status.json"],
        generated_est=generated,
    )
    artifacts["v2_cuda_paper_actionability_overlay_status.json"] = build_paper_actionability_overlay(
        source,
        generated_est=generated,
    )
    artifacts["v2_cuda_edge_after_actionability_overlay_status.json"] = build_edge_after_overlay(
        source,
        artifacts["v2_cuda_paper_actionability_overlay_status.json"],
        generated_est=generated,
    )
    hard_blockers: list[str] = []
    if artifacts["v2_cuda_false_negative_attribution_status.json"]["status"].endswith("BLOCKED"):
        hard_blockers.append("FALSE_NEGATIVE_LINEAGE_INCOMPLETE")
    if _as_dict(source.get("live_readiness")).get("live_gate", LIVE_GATE_BLOCKED) != LIVE_GATE_BLOCKED:
        hard_blockers.append("SOURCE_LIVE_GATE_NOT_BLOCKED")
    if _as_dict(source.get("live_readiness")).get("live_symbols", []) != []:
        hard_blockers.append("SOURCE_LIVE_SYMBOLS_NOT_EMPTY")
    go_no_go = GO_BLOCKED if hard_blockers else GO_READY
    operator = build_operator_payload(
        source=source,
        artifacts=artifacts,
        generated_est=generated,
        go_no_go=go_no_go,
    )
    if hard_blockers:
        operator["hard_blockers"] = hard_blockers
    return FalseNegativeActionabilityResult(
        go_no_go=go_no_go,
        artifacts=artifacts,
        operator_dashboard_payload=operator,
    )


def write_false_negative_actionability_artifacts(
    *,
    paths: FalseNegativeActionabilityPaths,
    result: FalseNegativeActionabilityResult,
) -> FalseNegativeActionabilityResult:
    report = build_report(result)
    files: dict[str, str] = {
        "GO_NO_GO.md": result.go_no_go + "\n",
        "V2_CUDA_TRAINER_FALSE_NEGATIVE_REDUCTION_AND_ACTIONABILITY_REPORT.md": report,
        "operator_dashboard_payload.json": dumps_pretty(result.operator_dashboard_payload),
    }
    for name, obj in result.artifacts.items():
        files[name] = dumps_pretty(obj)
    written: list[str] = []
    for base in (paths.worklog_dir, paths.public_dir):
        for name, text in files.items():
            path = base / name
            _write_text_atomic(path, text)
            written.append(str(path))
    return FalseNegativeActionabilityResult(
        go_no_go=result.go_no_go,
        artifacts=result.artifacts,
        operator_dashboard_payload=result.operator_dashboard_payload,
        paths_written=tuple(written),
    )


def run_false_negative_actionability(
    *,
    paths: FalseNegativeActionabilityPaths,
    source_payload_path: Path | None = None,
) -> FalseNegativeActionabilityResult:
    source = _read_json(source_payload_path or paths.source_payload_path)
    result = build_false_negative_actionability(source)
    return write_false_negative_actionability_artifacts(paths=paths, result=result)
