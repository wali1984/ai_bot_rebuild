"""Read-only adaptive-regime brain status helpers for recovery evidence."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any, Mapping

from v2.backend.app.services.strategy_router.service import (
    REQUIRED_REGIME_FEATURES,
    REQUIRED_STRATEGY_MODES,
)


SCHEMA_VERSION = "phase4_adaptive_regime_brain_v1"
DEFAULT_MIN_BUCKET_SAMPLES = 2


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


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _features(row: Mapping[str, Any]) -> dict[str, Any]:
    feature_map = dict(_as_dict(row.get("regime_features")))
    nested_features = _as_dict(_as_dict(row.get("entry_feature_snapshot")).get("features"))
    feature_map.update({key: value for key, value in nested_features.items() if key not in feature_map})
    direct_map = _as_dict(row.get("features"))
    feature_map.update({key: value for key, value in direct_map.items() if key not in feature_map})
    return feature_map


def _feature_value(features: Mapping[str, Any], name: str) -> Any:
    if name == "trend_strength":
        return _first_present(features.get("trend_strength"), features.get("htf_trend_strength"))
    if name == "range_chop_score":
        return _first_present(features.get("range_chop_score"), features.get("chop_score"), features.get("range_score"))
    if name == "open_interest_change":
        return _first_present(features.get("open_interest_change"), features.get("oi_change_pct"), features.get("open_interest_change_pct"))
    if name == "liquidation_cluster_proximity":
        return _first_present(
            features.get("liquidation_cluster_proximity"),
            features.get("liquidation_sweep_target_short_distance_bps"),
            features.get("liquidation_sweep_target_long_distance_bps"),
            features.get("liquidation_distance_pct"),
        )
    if name == "spread_depth_slippage":
        value = features.get("spread_depth_slippage")
        if isinstance(value, Mapping):
            return value if any(item not in (None, "", [], {}) for item in value.values()) else None
        return _first_present(
            features.get("bid_ask_spread_bps"),
            features.get("orderbook_depth_usd"),
            features.get("expected_slippage_bps"),
        )
    if name == "aggressive_flow":
        return _first_present(features.get("aggressive_flow"), features.get("order_flow_imbalance"), features.get("tape_imbalance"))
    if name == "market_wide_risk":
        return _first_present(features.get("market_wide_risk"), features.get("risk_on_risk_off"), features.get("market_breadth_score"))
    return features.get(name)


def _feature_coverage(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    present_counts: Counter[str] = Counter()
    missing_counts: Counter[str] = Counter()
    rows_with_all = 0
    for row in rows:
        features = _features(row)
        missing: list[str] = []
        for name in REQUIRED_REGIME_FEATURES:
            value = _feature_value(features, name)
            if value in (None, "", [], {}):
                missing_counts[name] += 1
                missing.append(name)
            else:
                present_counts[name] += 1
        if not missing:
            rows_with_all += 1
    return {
        "required_features": list(REQUIRED_REGIME_FEATURES),
        "row_count": len(rows),
        "rows_with_all_required_features": rows_with_all,
        "all_rows_have_required_features": bool(rows) and rows_with_all == len(rows),
        "present_counts": dict(sorted(present_counts.items())),
        "missing_counts": dict(sorted(missing_counts.items())),
        "missing_features": sorted(missing_counts),
    }


def _realized_bps(row: Mapping[str, Any]) -> float | None:
    for key in (
        "realized_after_cost_return_bps",
        "realized_net_pnl_bps",
        "realized_pnl_bps",
        "pnl_effect_bps",
    ):
        value = _float(row.get(key))
        if value is not None:
            return value
    outcome = _as_dict(_as_dict(row.get("outcome_windows")).get(row.get("primary_outcome_window") or "5m"))
    return _float(outcome.get("after_cost_return_bps"))


def _side(row: Mapping[str, Any]) -> str:
    side = str(row.get("counterfactual_side") or row.get("selected_action") or row.get("side") or "").lower()
    return side if side in {"long", "short"} else "unknown"


def _strategy(row: Mapping[str, Any]) -> str:
    return str(row.get("strategy_id") or row.get("strategy_mode") or row.get("strategy_family") or "UNKNOWN")


def _regime(row: Mapping[str, Any]) -> str:
    return str(row.get("market_regime") or row.get("market_regime_at_entry") or row.get("strategy_market_regime") or "UNKNOWN")


def _bucket_key(row: Mapping[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("symbol") or "UNKNOWN").upper(),
            str(row.get("timeframe") or "UNKNOWN"),
            _strategy(row),
            _regime(row),
            _side(row),
        ]
    )


def _bucket_metrics(values: list[float]) -> dict[str, Any]:
    wins = [value for value in values if value > 0.0]
    losses = [value for value in values if value < 0.0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor: float | str | None
    if not values:
        profit_factor = None
    elif gross_loss == 0.0 and gross_win > 0.0:
        profit_factor = "INF"
    elif gross_loss == 0.0:
        profit_factor = 0.0
    else:
        profit_factor = gross_win / gross_loss
    return {
        "sample_count": len(values),
        "win_count": len(wins),
        "loss_count": len(losses),
        "expectancy_bps": sum(values) / len(values) if values else None,
        "profit_factor": profit_factor,
    }


def build_strategy_selector_bucket_performance(
    rows: list[Mapping[str, Any]],
    *,
    min_bucket_samples: int = DEFAULT_MIN_BUCKET_SAMPLES,
) -> dict[str, Any]:
    normalized = [_as_dict(row) for row in rows]
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in normalized:
        value = _realized_bps(row)
        if value is None:
            continue
        grouped[_bucket_key(row)].append(value)
    bucket_rows: list[dict[str, Any]] = []
    for key, values in sorted(grouped.items()):
        metrics = _bucket_metrics(values)
        expectancy = _float(metrics.get("expectancy_bps"))
        profit_factor = _float(metrics.get("profit_factor"))
        sample_count = int(metrics.get("sample_count") or 0)
        negative = sample_count >= min_bucket_samples and (
            (profit_factor is not None and profit_factor < 1.0)
            or (expectancy is not None and expectancy <= 0.0)
        )
        bucket_rows.append(
            {
                "bucket_key": key,
                **metrics,
                "negative_bucket": negative,
                "quarantine_required": negative,
                "quarantine_reason": "NEGATIVE_STRATEGY_BUCKET" if negative else None,
            }
        )
    return {
        "schema_version": f"{SCHEMA_VERSION}_bucket_performance",
        "status": "STRATEGY_SELECTOR_BUCKET_PERFORMANCE_READY" if bucket_rows else "STRATEGY_SELECTOR_BUCKET_PERFORMANCE_BLOCKED_NO_COMPLETED_OUTCOMES",
        "source_row_count": len(normalized),
        "completed_outcome_count": sum(len(values) for values in grouped.values()),
        "min_bucket_samples": min_bucket_samples,
        "bucket_count": len(bucket_rows),
        "negative_bucket_count": sum(1 for row in bucket_rows if row["negative_bucket"] is True),
        "buckets": bucket_rows,
        "no_live_mutation": True,
        "runtime_thresholds_changed": False,
    }


def _decision_bucket_key(row: Mapping[str, Any]) -> str:
    key = _as_dict(row.get("strategy_bucket_key"))
    if key:
        return "|".join(
            [
                str(key.get("symbol") or row.get("symbol") or "UNKNOWN").upper(),
                str(key.get("timeframe") or row.get("timeframe") or "UNKNOWN"),
                str(key.get("strategy_mode") or row.get("strategy_mode") or "UNKNOWN"),
                str(key.get("market_regime") or row.get("market_regime") or "UNKNOWN"),
                _side(row),
            ]
        )
    return _bucket_key(row)


def build_strategy_quarantine_status(
    bucket_performance: Mapping[str, Any],
    *,
    decision_rows: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    negative_keys = {
        str(row.get("bucket_key"))
        for row in _as_list(bucket_performance.get("buckets"))
        if _as_dict(row).get("negative_bucket") is True
    }
    violations: list[dict[str, Any]] = []
    for row in [_as_dict(item) for item in (decision_rows or [])]:
        key = _decision_bucket_key(row)
        if key not in negative_keys:
            continue
        full_size = (_float(row.get("size_multiplier")) or 1.0) >= 0.999
        quarantined = row.get("bucket_quarantined") is True or row.get("strategy_bucket_quarantined") is True
        block_reason = row.get("block_reason") or row.get("paper_fill_block_reason")
        blocked = block_reason not in (None, "")
        if full_size and not quarantined and not blocked:
            violations.append(
                {
                    "bucket_key": key,
                    "prediction_id": row.get("prediction_id"),
                    "symbol": row.get("symbol"),
                    "timeframe": row.get("timeframe"),
                    "violation": "NEGATIVE_BUCKET_CONTINUED_FULL_SIZE",
                }
            )
    return {
        "schema_version": f"{SCHEMA_VERSION}_strategy_quarantine",
        "status": "STRATEGY_QUARANTINE_PASS" if not violations else "STRATEGY_QUARANTINE_BLOCKED",
        "negative_bucket_count": len(negative_keys),
        "negative_bucket_keys": sorted(negative_keys),
        "decision_rows_checked": len(decision_rows or []),
        "full_size_negative_bucket_violation_count": len(violations),
        "violations": violations,
        "no_negative_bucket_continues_full_size": not violations,
        "no_live_mutation": True,
        "runtime_thresholds_changed": False,
    }


def build_adaptive_regime_brain_status(
    decision_rows: list[Mapping[str, Any]],
    *,
    outcome_rows: list[Mapping[str, Any]] | None = None,
    min_bucket_samples: int = DEFAULT_MIN_BUCKET_SAMPLES,
) -> dict[str, Any]:
    decisions = [_as_dict(row) for row in decision_rows]
    outcomes = [_as_dict(row) for row in (outcome_rows or [])]
    coverage = _feature_coverage(decisions)
    bucket_performance = build_strategy_selector_bucket_performance(
        outcomes,
        min_bucket_samples=min_bucket_samples,
    )
    quarantine = build_strategy_quarantine_status(
        bucket_performance,
        decision_rows=decisions,
    )
    mode_counts = Counter(str(row.get("strategy_mode") or row.get("strategy_id") or "UNKNOWN") for row in decisions)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "ADAPTIVE_REGIME_BRAIN_READY" if coverage["all_rows_have_required_features"] else "ADAPTIVE_REGIME_BRAIN_BLOCKED_FEATURE_COVERAGE",
        "required_strategy_modes": list(REQUIRED_STRATEGY_MODES),
        "required_strategy_modes_present_in_router_contract": True,
        "decision_row_count": len(decisions),
        "strategy_mode_counts": dict(sorted(mode_counts.items())),
        "regime_feature_coverage": coverage,
        "bucket_performance": bucket_performance,
        "strategy_quarantine": quarantine,
        "pass_conditions": {
            "all_required_regime_features_present": coverage["all_rows_have_required_features"],
            "all_required_strategy_modes_supported": True,
            "no_negative_strategy_bucket_continues_full_size": quarantine["no_negative_bucket_continues_full_size"],
            "no_live_mutation": True,
        },
        "no_live_mutation": True,
        "runtime_thresholds_changed": False,
    }
