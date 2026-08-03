from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from v2.backend.app.services.feature_lineage_masks import (
    MISSING_NAME_KEYS,
    STALE_NAME_KEYS,
    canonical_feature_lineage,
    mask_names,
)

from .contracts import IntegrityThresholds, MarketStateScore
from .validators import validate_candle_completion, validate_event_time_alignment

OPTIONAL_OR_EVENT_FEATURE_TOKENS = (
    "altdata",
    "ask_wall",
    "basis",
    "best_ask",
    "best_bid",
    "bid_ask",
    "bid_wall",
    "bollinger",
    "book_trade",
    "cancel_pressure",
    "coingecko",
    "coinglass",
    "cross_venue",
    "defillama",
    "distance_to_long_liq",
    "distance_to_short_liq",
    "depth_",
    "estimated_price_impact",
    "fear_greed",
    "feed_latency",
    "funding",
    "htf_",
    "index_price",
    "last_price",
    "last_liq",
    "liquidation",
    "liquidity_zone",
    "long_account",
    "long_short",
    "mark_price",
    "mempool",
    "micro_",
    "micro_price",
    "microprice",
    "microstructure",
    # moralis is a provider alt-data family exactly like surf below:
    # per-symbol coverage is inherently partial (token maps / asset slugs),
    # so its absence is structural, never a critical-feature failure.
    "moralis",
    "news_",
    "num_trades",
    "oi_",
    "open_interest",
    "order_flow",
    "orderbook_",
    "ob_",
    "quote_volume",
    "paper_position",
    "paper_unrealized",
    "price_last",
    "post_sweep",
    "provider_",
    "public_intel",
    "realized_slippage_error",
    "risk_recent_",
    "orchestrator_recent_",
    "source_latency",
    "spread",
    "spread_instability",
    "short_account",
    "surf_",
    "sweep_risk",
    "taker_buy",
    "tape_",
    "toxicity",
    "update_age",
    "whale",
)

CORE_OHLC_FIELDS = ("open", "high", "low", "close")


def _float(value: Any, default: float | None = None) -> float | None:
    if isinstance(value, bool):
        return default
    try:
        if value is None:
            return default
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return default
    return parsed


def _age_seconds(row: dict[str, Any]) -> float | None:
    raw = row.get("generated_utc") or row.get("generated_at") or row.get("timestamp")
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())


def _state_id(row: dict[str, Any]) -> str:
    existing = row.get("market_state_id")
    if existing:
        return str(existing)
    seed = "|".join(
        str(row.get(key) or "")
        for key in ("symbol", "timeframe", "feature_snapshot_id", "prediction_id", "generated_utc", "generated_at")
    )
    return "mstate_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:20]


def _features(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("features")
    if isinstance(value, dict):
        return value
    value = row.get("feature_values")
    return value if isinstance(value, dict) else {}


def _has_core_market_snapshot(row: dict[str, Any]) -> bool:
    features = _features(row)
    return all(_float(features.get(field), None) is not None for field in CORE_OHLC_FIELDS)


def _missing_feature_names(row: dict[str, Any]) -> list[str]:
    return mask_names(row, mask_key="missing_mask", names_keys=MISSING_NAME_KEYS)


def _stale_feature_names(row: dict[str, Any]) -> list[str]:
    return mask_names(row, mask_key="stale_mask", names_keys=STALE_NAME_KEYS)


def _effective_feature_count(row: dict[str, Any], *, names: list[str], count_key: str, mask_key: str, names_keys: tuple[str, ...]) -> int:
    if mask_key in row or any(key in row for key in names_keys):
        return len(names)
    return int(_float(row.get(count_key), float(len(names))) or 0)


def _missing_features_are_optional_or_event_dependent(names: list[str]) -> bool:
    if not names:
        return False
    for name in names:
        lowered = name.lower()
        if not any(token in lowered for token in OPTIONAL_OR_EVENT_FEATURE_TOKENS):
            return False
    return True


def score_market_state(
    row: dict[str, Any],
    *,
    thresholds: IntegrityThresholds | None = None,
) -> MarketStateScore:
    thresholds = thresholds or IntegrityThresholds()
    reasons: list[str] = []
    symbol = str(row.get("symbol") or "UNKNOWN").upper()
    timeframe = str(row.get("timeframe") or row.get("tf") or "unknown")
    # Temporal clocks and candle finality are evidence, not values that can be
    # reconstructed from a feature snapshot's generation clock.  In particular,
    # generated_at cannot prove event_time, available_at, decision_time, candle
    # boundaries, or that an exchange candle was final.  Keep the original row
    # intact and fail closed in the validators when any of those proofs is absent.
    row = dict(row)
    inferred_lineage: dict[str, str] = {}
    decision_time = str(row.get("decision_time_est") or row.get("generated_est") or row.get("generated_utc") or "")
    age = _age_seconds(row)

    freshness_state = str(row.get("feature_freshness_state") or row.get("freshness_state") or "").upper()
    if freshness_state == "CURRENT" or (age is not None and age <= 120):
        data_freshness = 100.0
    elif freshness_state in {"STALE", "EXPIRED"} or (age is not None and age <= 900):
        data_freshness = 55.0
        reasons.append("STALE_FEATURE_STATE")
    else:
        data_freshness = 0.0
        reasons.append("FEATURE_FRESHNESS_MISSING_OR_EXPIRED")

    candle = validate_candle_completion(row)
    if candle["status"] == "CANDLE_CLOSED_CONFIRMED":
        candle_score = 100.0
    elif candle["status"] == "UNCLOSED_CANDLE":
        candle_score = 0.0
    else:
        candle_score = 0.0
    reasons.extend(candle["reject_reasons"])

    alignment = validate_event_time_alignment(row)
    if alignment["status"] == "TF_ALIGNED":
        tf_score = 100.0
    elif alignment["status"] in {"FUTURE_LEAKAGE", "BACKFILLED_NOT_AVAILABLE_AT_DECISION_TIME"}:
        tf_score = 0.0
    else:
        tf_score = 0.0
    reasons.extend(alignment["reject_reasons"])

    missing_names = _missing_feature_names(row)
    stale_names = _stale_feature_names(row)
    missing_count = _effective_feature_count(
        row,
        names=missing_names,
        count_key="missing_feature_count",
        mask_key="missing_mask",
        names_keys=MISSING_NAME_KEYS,
    )
    stale_count = _effective_feature_count(
        row,
        names=stale_names,
        count_key="stale_feature_count",
        mask_key="stale_mask",
        names_keys=STALE_NAME_KEYS,
    )
    canonical_lineage = canonical_feature_lineage(row)
    optional_missing_masked = (
        missing_count > 0
        and _has_core_market_snapshot(row)
        and _missing_features_are_optional_or_event_dependent(missing_names)
    )
    if missing_count > 0 and not optional_missing_masked:
        reasons.append("MISSING_CRITICAL_FEATURE_FAMILY")
    if stale_count > 0:
        reasons.append("STALE_FEATURE_FAMILY")
    if optional_missing_masked:
        missing_score = max(70.0, 100.0 - (missing_count * 1.5) - (stale_count * 5.0))
    else:
        missing_score = max(0.0, 100.0 - (missing_count * 8.0) - (stale_count * 5.0))

    disagreement_bps = abs(_float(row.get("price_disagreement_bps"), 0.0) or 0.0)
    if disagreement_bps > 25:
        reasons.append("MAJOR_SOURCE_DISAGREEMENT")
    source_disagreement = max(0.0, 100.0 - min(100.0, disagreement_bps * 2.0))

    latency = _float(row.get("latency_ms"), None)
    latency_score = 100.0
    if latency is None and age is None:
        latency_score = 60.0
        reasons.append("LATENCY_OR_PAYLOAD_AGE_MISSING")
    elif latency is not None and latency > 5_000:
        latency_score = 40.0
        reasons.append("LATENCY_ABOVE_GATE")

    backfilled = bool(row.get("backfilled") or row.get("backfilled_not_available_at_decision_time"))
    backfill_score = 0.0 if backfilled else 100.0
    if backfilled:
        reasons.append("BACKFILLED_NOT_AVAILABLE_AT_DECISION_TIME")

    fill_quality = 100.0
    if row.get("execution_fill_quality_score") is not None:
        fill_quality = max(0.0, min(100.0, _float(row.get("execution_fill_quality_score"), 0.0) or 0.0))

    scores = [
        data_freshness,
        candle_score,
        tf_score,
        missing_score,
        source_disagreement,
        latency_score,
        backfill_score,
        fill_quality,
    ]
    score = round(sum(scores) / len(scores), 4)
    reasons = sorted(set(reason for reason in reasons if reason))
    training_block_reasons = reasons
    critical_prediction_reasons = {
        "feature_timestamp_after_decision_cutoff",
        "source_available_after_decision_cutoff",
        "candle_not_closed_confirmed",
        "candle_closed_confirmed_missing",
        "CANDLE_COMPLETION_UNKNOWN",
        "UNCLOSED_CANDLE",
        "source_event_time_missing",
        "decision_cutoff_time_missing",
    }
    critical_prediction_block = bool(critical_prediction_reasons.intersection(reasons))
    return MarketStateScore(
        market_state_id=_state_id(row),
        symbol=symbol,
        timeframe=timeframe,
        decision_time_est=decision_time,
        data_freshness_score=round(data_freshness, 4),
        candle_completion_score=round(candle_score, 4),
        tf_alignment_score=round(tf_score, 4),
        missing_data_score=round(missing_score, 4),
        source_disagreement_score=round(source_disagreement, 4),
        latency_score=round(latency_score, 4),
        backfill_score=round(backfill_score, 4),
        execution_fill_quality_score=round(fill_quality, 4),
        market_state_integrity_score=score,
        valid_for_training=score >= thresholds.training_min_score and not training_block_reasons,
        valid_for_prediction=score >= thresholds.prediction_min_score and not critical_prediction_block,
        valid_for_risk=score >= thresholds.risk_min_score and not critical_prediction_block,
        valid_for_orchestrator=score >= thresholds.risk_min_score and not critical_prediction_block,
        valid_for_paper=score >= thresholds.paper_min_score and not critical_prediction_block,
        valid_for_live=score >= thresholds.live_min_score and not reasons,
        reject_reasons=reasons,
        source_lineage={
            "feature_snapshot_id": row.get("feature_snapshot_id"),
            "prediction_id": row.get("prediction_id") or row.get("source_prediction_id"),
            "redis_key": row.get("_redis_key") or row.get("source_redis_key"),
            "source_event_time_est": row.get("source_event_time_est"),
            "source_received_time_est": row.get("source_received_time_est") or row.get("received_at"),
            "inferred": inferred_lineage,
            "optional_missing_features_masked": optional_missing_masked,
            "missing_feature_names": missing_names[:50],
            "missing_feature_count": missing_count,
            "missing_mask": canonical_lineage["missing_mask"],
            "stale_feature_names": stale_names[:50],
            "stale_feature_count": stale_count,
            "stale_mask": canonical_lineage["stale_mask"],
            "source_availability": canonical_lineage["source_availability"],
        },
    )
