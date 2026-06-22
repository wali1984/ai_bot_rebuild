"""Publish natural-language explanations for current V2 predictions/signals.

This is a read-only runtime explainer. It reads current V2 Redis/public payloads
and writes V2-owned website artifacts only. It never submits orders, calls a
test-order endpoint, changes leverage/margin, writes Redis, restarts services,
or touches legacy namespaces.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from v2.backend.app.services.v2_symbol_runtime_universe import is_valid_runtime_symbol
except ImportError:  # Backend PYTHONPATH style.
    from app.services.v2_symbol_runtime_universe import is_valid_runtime_symbol


REPO = Path("/home/wali/Desktop/AI BOT REBUILD")
PUBLIC_DIR = REPO / "v2/frontend/public/operator_runtime/v2_prediction_signal_explanations/latest"
READY_DIR = (
    REPO
    / "v2/frontend/public/v2_prediction_signal_natural_language_explainer/latest"
)
EST = ZoneInfo("America/New_York")

TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
LIVE_SYMBOLS = {"BNBUSDT", "BTCUSDT", "ETHUSDT", "PAXGUSDT", "XAUTUSDT", "ZECUSDT"}
DEFAULT_EXPLANATION_LIMIT = 1000
DEFAULT_FEATURE_SAMPLE_LIMIT = 32


def _est_now() -> str:
    return datetime.now(EST).isoformat(timespec="seconds")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis() -> Any:
    try:
        import redis  # type: ignore

        client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=5,
        )
        client.ping()
        return client
    except Exception:
        return None


def _json(raw: Any, default: Any = None) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default


def _read_key(r: Any, key: str, default: Any = None) -> Any:
    if r is None:
        return default
    try:
        kind = r.type(key)
        if kind == "string":
            return _json(r.get(key), default)
        if kind == "hash":
            return r.hgetall(key)
        if kind == "stream":
            return r.xrevrange(key, count=20)
    except Exception:
        return default
    return default


def _scan_json(r: Any, pattern: str, limit: int = 5000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if r is None:
        return rows
    try:
        for key in r.scan_iter(match=pattern, count=500):
            payload = _read_key(r, str(key))
            if isinstance(payload, dict):
                row = dict(payload)
                row["_redis_key"] = str(key)
                rows.append(row)
            elif isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        row = dict(item)
                        row["_redis_key"] = str(key)
                        rows.append(row)
            if len(rows) >= limit:
                break
    except Exception:
        return rows
    return rows


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        out = float(value)
    elif isinstance(value, str):
        try:
            out = float(value)
        except ValueError:
            return None
    else:
        return None
    return out if math.isfinite(out) else None


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _format_bps(value: Any) -> str:
    number = _float(value)
    return "missing" if number is None else f"{number:.2f} bps"


def _format_pct(value: Any) -> str:
    number = _float(value)
    return "missing" if number is None else f"{number * 100:.1f}%"


def _format_price(value: Any) -> str:
    number = _float(value)
    if number is None:
        return "missing"
    if abs(number) >= 100:
        return f"${number:,.2f}"
    return f"${number:.8g}"


def _probability_map(row: dict[str, Any]) -> dict[str, float]:
    raw = row.get("action_probabilities")
    labels = row.get("action_labels")
    if isinstance(raw, dict):
        return {str(k): float(v) for k, v in raw.items() if _float(v) is not None}
    if isinstance(raw, list) and isinstance(labels, list):
        out: dict[str, float] = {}
        for label, value in zip(labels, raw):
            number = _float(value)
            if number is not None:
                out[str(label)] = number
        return out
    return {}


def _string_list(value: Any, *, limit: int = 20) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item not in (None, "")][:limit]


def _source_keys(*values: Any) -> list[str]:
    keys: list[str] = []
    for value in values:
        if isinstance(value, str) and value:
            keys.extend(part.strip() for part in value.split(",") if part.strip())
    return list(dict.fromkeys(keys))


def _top_action_probabilities(row: dict[str, Any], *, limit: int = 7) -> list[dict[str, Any]]:
    return [
        {"action": action, "probability": probability}
        for action, probability in sorted(
            _probability_map(row).items(),
            key=lambda item: item[1],
            reverse=True,
        )[:limit]
    ]


def _feature_samples(features: dict[str, Any], *, limit: int = DEFAULT_FEATURE_SAMPLE_LIMIT) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    priority = (
        "close",
        "last_price",
        "ret_pct",
        "log_return",
        "rsi_14",
        "macd",
        "ema_12",
        "ema_26",
        "bb_width_pct",
        "bid_ask_spread_bps",
        "depth_imbalance",
        "micro_price",
        "funding_rate",
        "oi_change_pct",
        "long_short_ratio",
        "liquidation_long_level",
        "liquidation_short_level",
        "paper_position_present",
    )
    ordered_names = [name for name in priority if name in features]
    ordered_names.extend(name for name in sorted(features) if name not in set(ordered_names))
    for name in ordered_names[:limit]:
        value = features.get(name)
        samples.append({"feature": str(name), "value": value})
    return samples


def _market_state_summary(row: dict[str, Any]) -> dict[str, Any]:
    lineage = row.get("market_state_source_lineage")
    return {
        "market_state_id": row.get("market_state_id"),
        "market_state_integrity_score": _float(row.get("market_state_integrity_score")),
        "market_state_score_components": row.get("market_state_score_components") if isinstance(row.get("market_state_score_components"), dict) else {},
        "market_state_reject_reasons": _string_list(row.get("market_state_reject_reasons"), limit=20),
        "source_lineage": lineage if isinstance(lineage, dict) else {},
        "source_event_time_est": row.get("source_event_time_est") or (lineage or {}).get("source_event_time_est") if isinstance(lineage, dict) else row.get("source_event_time_est"),
        "source_received_time_est": row.get("source_received_time_est") or (lineage or {}).get("source_received_time_est") if isinstance(lineage, dict) else row.get("source_received_time_est"),
        "decision_cutoff_time_est": row.get("decision_cutoff_time_est"),
        "feature_cutoff": row.get("feature_cutoff") or row.get("decision_cutoff_time_est"),
        "freshness_seconds": row.get("freshness_seconds"),
    }


def _selected_action_probability(row: dict[str, Any]) -> tuple[float | None, float | None]:
    action = str(row.get("selected_action") or "").lower()
    probabilities = _probability_map(row)
    selected: float | None = None
    for label, probability in probabilities.items():
        if str(label).lower() == action:
            selected = probability
            break
    ordered = sorted(probabilities.values(), reverse=True)
    second = ordered[1] if len(ordered) > 1 else None
    margin = selected - second if selected is not None and second is not None else None
    return selected, margin


def _driver(
    *,
    name: str,
    direction: str,
    evidence_value: Any,
    source_key: str | None,
    plain_english: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "direction": direction,
        "evidence_value": evidence_value,
        "source_key": source_key,
        "plain_english": plain_english,
    }


def _directional_action(row: dict[str, Any]) -> str:
    action = str(row.get("selected_action") or "").lower()
    if "long" in action or "buy" in action:
        return "long"
    if "short" in action or "sell" in action:
        return "short"
    return "neutral"


def _confidence_explanation(
    row: dict[str, Any],
    features: dict[str, Any],
    feature_source_keys: list[str],
    market_state: dict[str, Any],
) -> dict[str, Any]:
    prediction_source = row.get("_redis_key") or row.get("prediction_redis_key") or row.get("redis_key")
    feature_source = feature_source_keys[0] if feature_source_keys else None
    raw = _float(row.get("confidence_raw"))
    calibrated = _float(row.get("confidence_calibrated"))
    delta = calibrated - raw if raw is not None and calibrated is not None else None
    if delta is None:
        calibration_direction = "CALIBRATION_UNKNOWN"
    elif delta > 0.005:
        calibration_direction = "CALIBRATION_RAISED_CONFIDENCE"
    elif delta < -0.005:
        calibration_direction = "CALIBRATION_LOWERED_CONFIDENCE"
    else:
        calibration_direction = "CALIBRATION_FLAT_OR_UNKNOWN"

    selected_probability, probability_margin = _selected_action_probability(row)
    action_kind = _directional_action(row)
    drivers: list[dict[str, Any]] = []

    if delta is None:
        drivers.append(
            _driver(
                name="raw_to_calibrated_confidence",
                direction="NEUTRAL",
                evidence_value=None,
                source_key=str(prediction_source) if prediction_source else None,
                plain_english="The prediction row did not expose both raw and calibrated confidence, so the UI cannot show whether calibration raised or lowered confidence.",
            )
        )
    else:
        drivers.append(
            _driver(
                name="raw_to_calibrated_confidence",
                direction="UP" if delta > 0.005 else "DOWN" if delta < -0.005 else "NEUTRAL",
                evidence_value={"raw": raw, "calibrated": calibrated, "delta": delta},
                source_key=str(prediction_source) if prediction_source else None,
                plain_english=(
                    f"The trainer published raw confidence {_format_pct(raw)} and calibrated confidence {_format_pct(calibrated)}. "
                    f"Calibration {'raised' if delta > 0 else 'lowered' if delta < 0 else 'left'} confidence by {_format_pct(abs(delta))}."
                ),
            )
        )

    if selected_probability is None:
        action_direction = "NEUTRAL"
        action_text = "The prediction row did not expose a selected-action probability, so action certainty cannot be separated from total confidence."
    elif probability_margin is not None and selected_probability >= 0.65 and probability_margin >= 0.10:
        action_direction = "UP"
        action_text = (
            f"The selected action probability is {_format_pct(selected_probability)} with a {_format_pct(probability_margin)} gap to the next action, "
            "so the action head is clearly separated."
        )
    elif selected_probability < 0.45 or (probability_margin is not None and probability_margin < 0.03):
        action_direction = "DOWN"
        action_text = (
            f"The selected action probability is {_format_pct(selected_probability)} and the margin is {_format_pct(probability_margin)}, "
            "so the action head is weak or crowded by alternate actions."
        )
    else:
        action_direction = "NEUTRAL"
        action_text = (
            f"The selected action probability is {_format_pct(selected_probability)} with margin {_format_pct(probability_margin)}, "
            "which is usable context but not a strong standalone confidence boost."
        )
    drivers.append(
        _driver(
            name="selected_action_probability_margin",
            direction=action_direction,
            evidence_value={"selected_probability": selected_probability, "margin_to_next_action": probability_margin},
            source_key=str(prediction_source) if prediction_source else None,
            plain_english=action_text,
        )
    )

    after_cost = _float(row.get("expected_move_after_cost_bps"))
    if after_cost is None:
        edge_direction = "NEUTRAL"
        edge_text = "The row did not expose expected_move_after_cost_bps, so the UI cannot show after-cost edge support."
    elif after_cost >= 5:
        edge_direction = "UP"
        edge_text = f"Expected move after estimated fees/slippage is {_format_bps(after_cost)}, which supports confidence because edge remains after costs."
    elif after_cost > 0:
        edge_direction = "NEUTRAL"
        edge_text = f"Expected move after costs is positive but small at {_format_bps(after_cost)}; this is context, not strong confirmation."
    else:
        edge_direction = "DOWN"
        edge_text = f"Expected move after costs is {_format_bps(after_cost)}, so estimated costs erase or exceed the model edge."
    drivers.append(
        _driver(
            name="expected_move_after_cost",
            direction=edge_direction,
            evidence_value=after_cost,
            source_key=str(prediction_source) if prediction_source else None,
            plain_english=edge_text,
        )
    )

    coverage = _float(row.get("data_coverage_percent"))
    if coverage is None:
        coverage_direction = "NEUTRAL"
        coverage_text = "Feature coverage was not published on the prediction row."
    elif coverage >= 90:
        coverage_direction = "UP"
        coverage_text = f"Feature coverage is {coverage:.1f}%, so the model had broad runtime evidence for this row."
    elif coverage >= 70:
        coverage_direction = "NEUTRAL"
        coverage_text = f"Feature coverage is {coverage:.1f}%, enough for context but not a strong confidence booster."
    else:
        coverage_direction = "DOWN"
        coverage_text = f"Feature coverage is only {coverage:.1f}%, which should lower confidence or keep the row paper-only."
    drivers.append(
        _driver(
            name="feature_coverage",
            direction=coverage_direction,
            evidence_value=coverage,
            source_key=feature_source,
            plain_english=coverage_text,
        )
    )

    missing_count = int(_float(row.get("missing_feature_count")) or 0)
    stale_count = int(_float(row.get("stale_feature_count")) or 0)
    if missing_count == 0 and stale_count == 0:
        missing_direction = "UP"
        missing_text = "No missing or stale feature count was reported, so freshness/completeness does not penalize confidence."
    else:
        missing_direction = "DOWN"
        missing_text = f"The prediction row reports {missing_count} missing and {stale_count} stale features, which should reduce confidence or block actionability."
    drivers.append(
        _driver(
            name="missing_or_stale_features",
            direction=missing_direction,
            evidence_value={"missing_feature_count": missing_count, "stale_feature_count": stale_count},
            source_key=feature_source,
            plain_english=missing_text,
        )
    )

    integrity = _float(market_state.get("market_state_integrity_score"))
    reject_reasons = market_state.get("market_state_reject_reasons") or []
    if integrity is None:
        integrity_direction = "NEUTRAL"
        integrity_text = "Market-state integrity score was not available on this row."
    elif reject_reasons:
        integrity_direction = "DOWN"
        integrity_text = f"Market-state integrity has reject reasons: {', '.join(map(str, reject_reasons[:4]))}."
    elif integrity >= 95:
        integrity_direction = "UP"
        integrity_text = f"Market-state integrity score is {integrity:.2f}, so lineage/freshness evidence supports the confidence."
    elif integrity >= 80:
        integrity_direction = "NEUTRAL"
        integrity_text = f"Market-state integrity score is {integrity:.2f}; acceptable context, but not strong confirmation."
    else:
        integrity_direction = "DOWN"
        integrity_text = f"Market-state integrity score is {integrity:.2f}, which should lower trust in the prediction."
    drivers.append(
        _driver(
            name="market_state_integrity",
            direction=integrity_direction,
            evidence_value={"score": integrity, "reject_reasons": reject_reasons[:8]},
            source_key=str(prediction_source) if prediction_source else None,
            plain_english=integrity_text,
        )
    )

    spread = _float(features.get("bid_ask_spread_bps") or features.get("ob_spread_bps"))
    if spread is not None:
        if spread <= 2:
            spread_direction = "UP"
            spread_text = f"Bid/ask spread is tight at {_format_bps(spread)}, which supports executable confidence after costs."
        elif spread <= 8:
            spread_direction = "NEUTRAL"
            spread_text = f"Bid/ask spread is {_format_bps(spread)}; usable, but still a cost drag."
        else:
            spread_direction = "DOWN"
            spread_text = f"Bid/ask spread is wide at {_format_bps(spread)}, so execution cost should lower confidence."
        drivers.append(
            _driver(
                name="bid_ask_spread_bps",
                direction=spread_direction,
                evidence_value=spread,
                source_key=feature_source,
                plain_english=spread_text,
            )
        )

    imbalance = _float(features.get("depth_imbalance") or features.get("ob_imbalance"))
    if imbalance is not None:
        if action_kind == "long" and imbalance > 0.05 or action_kind == "short" and imbalance < -0.05:
            imbalance_direction = "UP"
            imbalance_text = f"Orderbook depth imbalance is {imbalance:.4f}, aligned with the selected {action_kind} action."
        elif action_kind == "long" and imbalance < -0.05 or action_kind == "short" and imbalance > 0.05:
            imbalance_direction = "DOWN"
            imbalance_text = f"Orderbook depth imbalance is {imbalance:.4f}, against the selected {action_kind} action."
        else:
            imbalance_direction = "NEUTRAL"
            imbalance_text = f"Orderbook depth imbalance is {imbalance:.4f}; it is not a strong directional confirmation."
        drivers.append(
            _driver(
                name="orderbook_depth_imbalance",
                direction=imbalance_direction,
                evidence_value=imbalance,
                source_key=feature_source,
                plain_english=imbalance_text,
            )
        )

    rsi = _float(features.get("rsi_14") or features.get("RSI"))
    if rsi is not None:
        if action_kind == "long" and 45 <= rsi <= 70:
            rsi_direction = "UP"
            rsi_text = f"RSI is {rsi:.2f}, a supportive momentum range for a long-biased signal without being extremely overbought."
        elif action_kind == "short" and 30 <= rsi <= 55:
            rsi_direction = "UP"
            rsi_text = f"RSI is {rsi:.2f}, a supportive momentum range for a short-biased signal without being extremely oversold."
        elif rsi >= 75 or rsi <= 25:
            rsi_direction = "DOWN"
            rsi_text = f"RSI is extreme at {rsi:.2f}, which can reduce confidence because reversal/chop risk is higher."
        else:
            rsi_direction = "NEUTRAL"
            rsi_text = f"RSI is {rsi:.2f}; useful context but not a strong confidence driver by itself."
        drivers.append(
            _driver(
                name="rsi_14",
                direction=rsi_direction,
                evidence_value=rsi,
                source_key=feature_source,
                plain_english=rsi_text,
            )
        )

    macd = _float(features.get("macd") or features.get("MACD"))
    if macd is not None:
        if action_kind == "long" and macd > 0 or action_kind == "short" and macd < 0:
            macd_direction = "UP"
            macd_text = f"MACD is {macd:.6g}, aligned with the selected {action_kind} action."
        elif action_kind == "long" and macd < 0 or action_kind == "short" and macd > 0:
            macd_direction = "DOWN"
            macd_text = f"MACD is {macd:.6g}, against the selected {action_kind} action."
        else:
            macd_direction = "NEUTRAL"
            macd_text = f"MACD is {macd:.6g}; it is not directional for a hold/reduce style action."
        drivers.append(
            _driver(
                name="macd",
                direction=macd_direction,
                evidence_value=macd,
                source_key=feature_source,
                plain_english=macd_text,
            )
        )

    funding = _float(features.get("funding_rate"))
    oi_change = _float(features.get("oi_change_pct") or features.get("open_interest_change_pct"))
    long_short = _float(features.get("long_short_ratio"))
    if funding is not None or oi_change is not None or long_short is not None:
        drivers.append(
            _driver(
                name="derivatives_positioning_context",
                direction="NEUTRAL",
                evidence_value={"funding_rate": funding, "oi_change_pct": oi_change, "long_short_ratio": long_short},
                source_key=feature_source,
                plain_english=(
                    "Funding, open interest, and long/short ratio are present as crowding context. "
                    "They explain market pressure, but this explainer does not treat them as standalone causal attribution."
                ),
            )
        )

    counts = Counter(str(driver["direction"]) for driver in drivers)
    plain = (
        "Confidence is published by the trainer, not recalculated by the website. "
        f"This row published raw confidence {_format_pct(raw)} and calibrated confidence {_format_pct(calibrated)}. "
        "The driver list shows visible runtime evidence that likely supported, penalized, or contextualized that confidence: "
        "action-probability separation, after-cost edge, feature coverage, missing/stale data, market-state integrity, and current feature values. "
        "Where explicit neural attribution is absent, these are evidence drivers rather than hidden-weight causal proof."
    )
    return {
        "raw_confidence": raw,
        "calibrated_confidence": calibrated,
        "confidence_delta": delta,
        "calibration_direction": calibration_direction,
        "selected_action_probability": selected_probability,
        "action_probability_margin": probability_margin,
        "driver_counts": dict(counts),
        "drivers": drivers,
        "confidence_calculation_plain_english": plain,
    }


def _features_for(r: Any, symbol: str, timeframe: str) -> tuple[dict[str, Any], str | None]:
    candidates = [
        f"v2:features:latest:{symbol}:{timeframe}",
        f"v2:unified_features:{symbol}:{timeframe}:latest",
        f"v2:unified_features:{symbol}:{timeframe}",
    ]
    merged: dict[str, Any] = {}
    used: list[str] = []
    for key in candidates:
        payload = _read_key(r, key, {})
        if isinstance(payload, dict):
            values = payload.get("features") if isinstance(payload.get("features"), dict) else payload
            for name, value in values.items():
                merged.setdefault(str(name), value)
            used.append(key)
    return merged, ", ".join(used) if used else None


def _family_status(
    features: dict[str, Any],
    prediction: dict[str, Any],
) -> list[dict[str, Any]]:
    family_defs = [
        (
            "price_action",
            ("close", "open", "high", "low", "ret_pct", "log_return", "last_price", "price_last"),
            "Price and candle data tell the model what actually moved, the recent direction, and the local range it is trading inside.",
        ),
        (
            "technical_indicators",
            ("rsi_14", "RSI", "macd", "MACD", "ema_12", "ema_26", "bb_width_pct", "ATR", "atr_14"),
            "Momentum, trend, volatility, and band-width indicators help separate trend continuation from chop or mean reversion.",
        ),
        (
            "orderbook_liquidity",
            ("bid_ask_spread_bps", "ob_spread_bps", "depth_imbalance", "ob_imbalance", "micro_price", "microprice"),
            "Orderbook and spread fields estimate trading cost, short-term pressure, and whether the book is skewed toward bids or asks.",
        ),
        (
            "derivatives_positioning",
            ("funding_rate", "open_interest", "oi_change_pct", "open_interest_change_pct", "long_short_ratio"),
            "Funding, open interest, and long/short positioning show crowding and leverage pressure that can help explain continuation or squeeze risk.",
        ),
        (
            "liquidation_map",
            ("liquidation_long_level", "liquidation_short_level", "liquidation_distance_pct", "liquidation_strength", "liquidation_count_5m"),
            "Liquidation levels mark nearby forced-flow zones; the strategy can avoid chasing into bad liquidity or look for pressure toward those zones.",
        ),
        (
            "alternative_data",
            ("public_intel_score", "aicoin_score", "whale_wall_score", "coingecko_score", "lunarcrush_score", "news_sentiment_score"),
            "Alternative data is treated as context, not a standalone trigger; it can raise or lower confidence when attention or whale/order-flow evidence agrees with market data.",
        ),
    ]
    missing_features = set(str(x) for x in (prediction.get("missing_feature_names") or []) if x)
    stale_features = set(str(x) for x in (prediction.get("stale_feature_names") or []) if x)
    rows: list[dict[str, Any]] = []
    for family, keys, explanation in family_defs:
        present = [key for key in keys if key in features or key in prediction.get("feature_names", [])]
        live_values = {
            key: _float(features.get(key))
            for key in keys
            if _float(features.get(key)) is not None
        }
        missing = [key for key in keys if key in missing_features]
        stale = [key for key in keys if key in stale_features]
        if live_values:
            sample = ", ".join(f"{key}={value:.6g}" for key, value in list(live_values.items())[:4])
        elif present:
            sample = "feature names present; current values unavailable in this payload"
        else:
            sample = "not present in current feature snapshot"
        status = "PRESENT_CURRENT" if present and not stale else "PARTIAL_OR_STALE" if present else "MISSING_OR_MASKED"
        rows.append(
            {
                "family": family,
                "status": status,
                "sample_values": sample,
                "present_field_count": len(present),
                "missing_fields": missing[:8],
                "stale_fields": stale[:8],
                "why_useful_plain_english": explanation,
            }
        )
    return rows


def _prediction_plain(row: dict[str, Any]) -> str:
    action = str(row.get("selected_action") or "hold")
    confidence = _format_pct(row.get("confidence_calibrated"))
    raw_confidence = _format_pct(row.get("confidence_raw"))
    after_cost = _format_bps(row.get("expected_move_after_cost_bps"))
    before_cost = _format_bps(row.get("expected_move_bps"))
    coverage = _float(row.get("data_coverage_percent"))
    coverage_text = "missing coverage" if coverage is None else f"{coverage:.1f}% data coverage"
    probs = _probability_map(row)
    action_prob = probs.get(action)
    action_prob_text = "" if action_prob is None else f" The PPO action head assigned {action} probability {_format_pct(action_prob)}."
    return (
        f"The native PPO/MASA trainer selected {action.upper()} for {row.get('symbol')} {row.get('timeframe')} "
        f"with calibrated confidence {confidence} from raw confidence {raw_confidence}. "
        f"The MASA expected move is {before_cost}; after estimated costs it is {after_cost}. "
        f"The confidence was adjusted using {coverage_text}.{action_prob_text}"
    )


def _strategy_plain(row: dict[str, Any]) -> str:
    return (
        "The strategy is hybrid PPO plus MASA: PPO chooses the action policy "
        "(hold, long, short, close, reduce, or fail-closed hedge reserve), while MASA contributes "
        "direction, expected move, and confidence. Risk and orchestrator layers then decide whether "
        "the model output is actionable for paper or live. The trainer does not place exchange orders."
    )


def _risk_plain(risk: dict[str, Any] | None) -> str:
    if not risk:
        return "No current risk decision matched this prediction, so the signal cannot be treated as fully actionable."
    allowed = risk.get("pre_trade_allowed") is True and risk.get("fee_gate_allowed") is True and risk.get("churn_blocked") is not True
    if allowed:
        return "Risk currently allows this paper-side candidate: pre-trade checks passed, fee gate passed, and churn guard did not block it."
    reasons = [
        str(risk.get("fee_gate_reason") or ""),
        str(risk.get("churn_reason") or ""),
        str(risk.get("risk_reason_code") or ""),
    ]
    joined = "; ".join(reason for reason in reasons if reason and reason != "None")
    return f"Risk blocks or downranks this candidate. Current reason: {joined or 'risk decision did not publish a detailed reason'}."


def _paper_plain(row: dict[str, Any] | None, prediction: dict[str, Any] | None = None) -> str:
    if not row:
        prediction = prediction or {}
        gate_reasons = (
            prediction.get("paper_fill_gate_block_reasons")
            or prediction.get("paper_fill_block_reasons")
            or prediction.get("block_reasons")
            or []
        )
        if gate_reasons:
            return (
                "No paper ledger row was created because the prediction was blocked before paper execution. "
                f"Current paper gate reasons: {', '.join(map(str, gate_reasons[:5]))}."
            )
        return "No paper ledger row matched this prediction yet."
    status = row.get("paper_fill_block_reason") or row.get("paper_fill_status") or row.get("paper_result")
    if row.get("economic_fill") is True or row.get("paper_fill_status") == "ACCEPTED":
        return "Paper accepted this as an economic fill and it should flow into ledger, position reconstruction, mark-to-market PnL, and portfolio equity."
    blockers = row.get("paper_fill_gate_block_reasons") or row.get("market_state_reject_reasons") or []
    if blockers:
        return f"Paper did not accept this candidate because: {', '.join(map(str, blockers[:5]))}."
    return f"Paper did not accept this candidate. Current paper status: {status or 'unpublished'}."


def _improvements(row: dict[str, Any], families: list[dict[str, Any]], paper: dict[str, Any] | None) -> list[str]:
    fixes: list[str] = []
    if row.get("market_state_id") is None:
        fixes.append("Attach market_state_id, market_state_integrity_score, and valid_for_paper to prediction/intention rows so the paper gate can verify data quality.")
    if _float(row.get("expected_move_after_cost_bps")) is not None and _float(row.get("expected_move_after_cost_bps")) < 0:
        fixes.append("Keep this action downranked unless future samples show the after-cost edge turns positive.")
    if _float(row.get("confidence_calibrated")) is not None and _float(row.get("confidence_calibrated")) < 0.6:
        fixes.append("Use paper outcomes and feature attribution to calibrate low-confidence actions before allowing larger notional or live use.")
    if paper and paper.get("paper_fill_gate_block_reasons"):
        fixes.append("Repair the current paper gate blocker before treating accepted risk decisions as paper-executable.")
    gate_reasons = row.get("paper_fill_gate_block_reasons") or row.get("paper_fill_block_reasons") or []
    if "confidence_below_threshold" in gate_reasons:
        fixes.append("Confidence is the active paper gate blocker; use paper-only exploration analysis and calibration before lowering this threshold.")
    if "data_coverage_below_threshold" in gate_reasons:
        fixes.append("Improve feature coverage for this symbol/timeframe before expecting the prediction to become paper-actionable.")
    if "expected_move_after_cost_below_threshold" in gate_reasons:
        fixes.append("After-cost edge is too small for the current gate; keep observing unless costs, spread, or model edge improves.")
    for family in families:
        if family["status"] == "MISSING_OR_MASKED":
            fixes.append(f"Improve or mask {family['family']} cleanly; do not let optional missing fields pretend to be clean data.")
            break
    if not fixes:
        fixes.append("Continue collecting paper outcomes for this setup and compare realized mark-to-market behavior against the expected move after costs.")
    return fixes


def _latest_price_target(symbol: str, timeframe: str) -> dict[str, Any] | None:
    path = (
        REPO
        / "v2/frontend/public/v2_all_timeframe_prediction_signal_price_target_publisher/latest/price_target_all_tf_status.json"
    )
    payload = _json(path.read_text() if path.exists() else None, {})
    for row in payload.get("target_rows") or []:
        if row.get("symbol") == symbol and row.get("timeframe") == timeframe:
            return row
    return None


def build_payload(*, limit: int = 30) -> dict[str, Any]:
    r = _connect_redis()
    signals_payload_path = REPO / "v2/frontend/public/operator_runtime/v2_signals/latest/signals_payload.json"
    signals_payload = _json(signals_payload_path.read_text() if signals_payload_path.exists() else None, {})
    canonical_predictions = (
        ((signals_payload.get("prediction_contract") or {}).get("prediction_rows"))
        if isinstance(signals_payload, dict)
        else None
    )
    canonical_signals = (
        ((signals_payload.get("signal_publisher") or {}).get("published_signals"))
        if isinstance(signals_payload, dict)
        else None
    )
    if isinstance(canonical_predictions, list) and canonical_predictions:
        primary = [
            dict(row)
            for row in canonical_predictions
            if isinstance(row, dict) and is_valid_runtime_symbol(str(row.get("symbol") or ""))
        ]
        source_description = "current canonical V2 all-timeframe signal payload plus current feature snapshots"
    else:
        predictions = _scan_json(r, "v2:prediction:*", limit=6000)
        primary = [
            row
            for row in predictions
            if isinstance(row, dict)
            and ":rl_core:" not in str(row.get("_redis_key", ""))
            and is_valid_runtime_symbol(str(row.get("symbol") or ""))
        ]
        source_description = "current V2 Redis prediction/risk/paper keys plus current feature snapshots"
    risk_rows_raw = _read_key(r, "v2:risk:decisions", []) or []
    risk_rows = risk_rows_raw if isinstance(risk_rows_raw, list) else [risk_rows_raw] if isinstance(risk_rows_raw, dict) else []
    risk_by_prediction = {
        str(row.get("prediction_id")): row
        for row in risk_rows
        if isinstance(row, dict) and row.get("prediction_id")
    }
    ledger = _read_key(r, "v2:paper:ledger", {}) or {}
    paper_rows: list[dict[str, Any]] = []
    if isinstance(canonical_signals, list):
        for item in canonical_signals:
            if isinstance(item, dict):
                paper_rows.append(dict(item))
    if isinstance(ledger, dict):
        for bucket in ("accepted", "current_cycle_accepted", "blocked", "held_by_paper_fill_gate", "accepted_intents"):
            for item in ledger.get(bucket) or []:
                if isinstance(item, dict):
                    paper_rows.append(item)
    paper_by_prediction = {
        str(row.get("prediction_id") or row.get("source_prediction_id")): row
        for row in paper_rows
        if row.get("prediction_id") or row.get("source_prediction_id")
    }
    all_paper_block_reasons = Counter()
    paper_reason_rows = (
        [dict(item) for item in canonical_signals if isinstance(item, dict)]
        if isinstance(canonical_signals, list) and canonical_signals
        else paper_rows
    )
    for paper_row in paper_reason_rows:
        for reason in paper_row.get("paper_fill_gate_block_reasons") or paper_row.get("market_state_reject_reasons") or []:
            all_paper_block_reasons[str(reason)] += 1

    def score(row: dict[str, Any]) -> tuple[int, float, float]:
        live_bonus = 0 if row.get("symbol") in LIVE_SYMBOLS else 1
        after_cost = abs(_float(row.get("expected_move_after_cost_bps")) or 0.0)
        confidence = _float(row.get("confidence_calibrated")) or 0.0
        return (live_bonus, -after_cost, -confidence)

    selected = sorted(primary, key=score)[: max(1, limit)]
    explanations: list[dict[str, Any]] = []
    action_counts = Counter(str(row.get("selected_action") or "unknown") for row in primary)
    prediction_gate_reasons = Counter()
    paper_fill_allowed_count = 0
    routes_to_orchestrator_count = 0
    for row in primary:
        if row.get("paper_fill_allowed") is True:
            paper_fill_allowed_count += 1
        if row.get("routes_to_orchestrator") is True:
            routes_to_orchestrator_count += 1
        for reason in row.get("paper_fill_gate_block_reasons") or row.get("paper_fill_block_reasons") or []:
            prediction_gate_reasons[str(reason)] += 1
    family_counts = Counter()
    for row in selected:
        symbol = str(row.get("symbol"))
        timeframe = str(row.get("timeframe") or "")
        features, feature_source = _features_for(r, symbol, timeframe)
        target = _latest_price_target(symbol, timeframe) or {}
        families = _family_status(features, row)
        for family in families:
            if family["status"] == "PRESENT_CURRENT":
                family_counts[str(family["family"])] += 1
        risk = risk_by_prediction.get(str(row.get("prediction_id")))
        paper = paper_by_prediction.get(str(row.get("prediction_id")))
        feature_source_keys = _source_keys(feature_source)
        market_state = _market_state_summary(row)
        confidence_explanation = _confidence_explanation(row, features, feature_source_keys, market_state)
        target_source_keys = _source_keys(target.get("source_prediction_key"), target.get("source_price_key"))
        strategy_text = _strategy_plain(row)
        prediction_text = _prediction_plain(row)
        risk_text = _risk_plain(risk)
        paper_text = _paper_plain(paper, row)
        explanations.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "prediction_id": row.get("prediction_id"),
                "signal_id": (risk or {}).get("signal_id") or (paper or {}).get("signal_id"),
                "risk_decision_id": (risk or {}).get("risk_decision_id") or (paper or {}).get("risk_decision_id"),
                "orchestrator_decision_id": (risk or {}).get("orchestrator_decision_id") or (paper or {}).get("orchestrator_decision_id"),
                "selected_action": row.get("selected_action"),
                "confidence_calibrated": _float(row.get("confidence_calibrated")),
                "confidence_raw": _float(row.get("confidence_raw")),
                "expected_move_bps": _float(row.get("expected_move_bps")),
                "expected_move_after_cost_bps": _float(row.get("expected_move_after_cost_bps")),
                "price_target": _float(target.get("price_target_after_cost") or target.get("price_target")),
                "price_target_raw": _float(target.get("price_target")),
                "price_target_after_cost": _float(target.get("price_target_after_cost")),
                "price_target_validation_status": target.get("validation_status") or row.get("price_target_validation_status"),
                "last_price": _float(target.get("last_price") or features.get("close") or features.get("last_price")),
                "trainer_source": row.get("trainer_source"),
                "model_source": row.get("model_source"),
                "checkpoint_id": row.get("checkpoint_id"),
                "feature_snapshot_id": row.get("feature_snapshot_id"),
                "feature_source": feature_source,
                "feature_source_keys": feature_source_keys,
                "prediction_source_key": row.get("_redis_key") or row.get("prediction_redis_key") or row.get("redis_key"),
                "target_source_keys": target_source_keys,
                "runtime_source_paths": {
                    "prediction_payload": "operator_runtime/v2_signals/latest/signals_payload.json"
                    if isinstance(canonical_predictions, list) and canonical_predictions
                    else "redis:v2:prediction:*",
                    "feature_sources": feature_source_keys,
                    "risk_decisions": "redis:v2:risk:decisions",
                    "paper_ledger": "redis:v2:paper:ledger",
                    "price_targets": "v2_all_timeframe_prediction_signal_price_target_publisher/latest/price_target_all_tf_status.json",
                },
                "data_coverage_percent": _float(row.get("data_coverage_percent")),
                "missing_feature_count": row.get("missing_feature_count"),
                "stale_feature_count": row.get("stale_feature_count"),
                "missing_feature_names": _string_list(row.get("missing_feature_names"), limit=80),
                "stale_feature_names": _string_list(row.get("stale_feature_names"), limit=80),
                "optional_missing_features_masked": bool(
                    row.get("optional_missing_features_masked")
                    or (isinstance(row.get("market_state_source_lineage"), dict) and row["market_state_source_lineage"].get("optional_missing_features_masked"))
                ),
                "feature_value_count": len(features),
                "feature_value_samples": _feature_samples(features),
                "action_probabilities": _probability_map(row),
                "top_action_probabilities": _top_action_probabilities(row),
                "confidence_explanation": confidence_explanation,
                "market_state": market_state,
                "risk_gate": {
                    "pre_trade_allowed": (risk or paper or {}).get("pre_trade_allowed"),
                    "fee_gate_allowed": (risk or paper or {}).get("fee_gate_allowed"),
                    "churn_blocked": (risk or paper or {}).get("churn_blocked"),
                    "risk_action": (risk or {}).get("risk_action"),
                    "risk_result": (risk or {}).get("risk_result"),
                    "risk_reason_code": (risk or {}).get("risk_reason_code"),
                    "risk_blockers": _string_list((risk or {}).get("blockers"), limit=20),
                },
                "orchestrator_gate": {
                    "orchestrator_decision_id": (risk or {}).get("orchestrator_decision_id") or (paper or {}).get("orchestrator_decision_id"),
                    "orchestrator_action": (risk or {}).get("orchestrator_action") or (paper or {}).get("orchestrator_action"),
                    "orchestrator_reason": (risk or {}).get("orchestrator_reason") or (paper or {}).get("orchestrator_reason"),
                    "routes_to_orchestrator": row.get("routes_to_orchestrator"),
                },
                "paper_gate": {
                    "paper_fill_allowed": row.get("paper_fill_allowed") is True or (paper or {}).get("paper_fill_allowed") is True,
                    "paper_fill_gate_status": row.get("paper_fill_gate_status") or (paper or {}).get("paper_fill_gate_status"),
                    "paper_fill_gate_block_reasons": _string_list(
                        row.get("paper_fill_gate_block_reasons")
                        or row.get("paper_fill_block_reasons")
                        or (paper or {}).get("paper_fill_gate_block_reasons")
                        or (paper or {}).get("market_state_reject_reasons"),
                        limit=30,
                    ),
                },
                "data_families": families,
                "natural_language_summary": f"{symbol} {timeframe}: {prediction_text} {risk_text} {paper_text}",
                "strategy_plain_english": strategy_text,
                "prediction_plain_english": prediction_text,
                "risk_plain_english": risk_text,
                "paper_plain_english": paper_text,
                "truth_policy_plain_english": (
                    "This row shows runtime evidence available to the trainer and downstream gates. "
                    "It does not invent hidden neural-network feature importance; if explicit attribution is absent, "
                    "the UI labels values as evidence, not causal proof."
                ),
                "why_this_data_is_useful_plain_english": [
                    family["why_useful_plain_english"] for family in families if family["status"] != "MISSING_OR_MASKED"
                ],
                "improvement_suggestions": _improvements(row, families, paper),
                "safety": {
                    "exchange_order_submitted": False,
                    "test_order_called": False,
                    "leverage_or_margin_mutation": False,
                    "old_redis_write": False,
                },
            }
        )

    runtime_truth_path = REPO / "v2/frontend/public/operator_runtime/v2_runtime_truth/latest/operator_runtime_truth.json"
    runtime_truth = _json(runtime_truth_path.read_text() if runtime_truth_path.exists() else None, {})
    if isinstance(ledger, dict):
        accepted = int(ledger.get("accepted_count") or len(ledger.get("accepted") or []) or 0)
    else:
        accepted = 0
    if isinstance(canonical_signals, list) and canonical_signals:
        blocked = sum(1 for row in canonical_signals if isinstance(row, dict) and row.get("paper_fill_allowed") is not True)
    else:
        blocked = int(ledger.get("blocked_count") or 0) if isinstance(ledger, dict) else 0
    unique_symbols = sorted({str(row.get("symbol")) for row in explanations if row.get("symbol")})
    unique_timeframes = [tf for tf in TIMEFRAMES if tf in {str(row.get("timeframe")) for row in explanations if row.get("timeframe")}]
    top_paper_block_reasons = dict(all_paper_block_reasons.most_common(10))
    top_prediction_gate_reasons = dict(prediction_gate_reasons.most_common(10))
    safety = {
        "real_order_mutation": False,
        "test_order_called": False,
        "leverage_or_margin_mutation": False,
        "old_redis_write": False,
        "legacy_restart": False,
        "raw_credentials_emitted": False,
    }
    return {
        "schema_version": "v2_prediction_signal_natural_language_explanations_v1",
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "source": source_description,
        "explanation_count": len(explanations),
        "unique_symbols": len(unique_symbols),
        "unique_timeframes": unique_timeframes,
        "symbols_explained": unique_symbols,
        "timeframes_explained": unique_timeframes,
        "top_paper_block_reasons": top_paper_block_reasons,
        "top_prediction_paper_gate_block_reasons": top_prediction_gate_reasons,
        "legacy_restart_attempted": safety["legacy_restart"],
        "leverage_or_margin_mutation_attempted": safety["leverage_or_margin_mutation"],
        "old_redis_write_attempted": safety["old_redis_write"],
        "raw_credentials_emitted": safety["raw_credentials_emitted"],
        "real_order_mutation_attempted": safety["real_order_mutation"],
        "test_order_called": safety["test_order_called"],
        "summary": {
            "prediction_rows": len(primary),
            "explanation_rows": len(explanations),
            "explanation_count": len(explanations),
            "unique_symbols": len(unique_symbols),
            "unique_timeframes": unique_timeframes,
            "symbols_explained": unique_symbols,
            "timeframes_explained": unique_timeframes,
            "action_counts": dict(action_counts.most_common()),
            "data_family_present_counts": dict(family_counts.most_common()),
            "paper_accepted_count": accepted,
            "paper_blocked_count": blocked,
            "top_paper_block_reasons": top_paper_block_reasons,
            "prediction_paper_fill_allowed_count": paper_fill_allowed_count,
            "prediction_routes_to_orchestrator_count": routes_to_orchestrator_count,
            "top_prediction_paper_gate_block_reasons": top_prediction_gate_reasons,
            "live_gate": runtime_truth.get("live_gate"),
            "trader_state": runtime_truth.get("trader_state"),
            "live_submit_blocker": runtime_truth.get("live_order_submit_blocker"),
        },
        "plain_english_overview": [
            "Predictions are generated by the native CUDA PPO/MASA trainer from current market feature snapshots across price action, technical indicators, orderbook liquidity, derivatives positioning, liquidation levels, and selected alternative-data scores.",
            "PPO is the action-policy side: it chooses hold, long, short, close, reduce, or fail-closed reserve actions from the feature tensor and learned reward feedback.",
            "MASA is the forecast side: it estimates direction, expected move, confidence, and regime-like context. The system then subtracts costs to decide whether an edge remains after fees and slippage.",
            "Risk and orchestrator stages do not blindly trust the model. They require lineage, data quality, fee/churn gates, and paper/live eligibility before a decision can become a paper fill or live candidate.",
            "Live order submission remains disabled until live balance/margin is sufficient; this explainer is read-only and paper/training focused.",
        ],
        "task_descriptions": {
            "trainer_cycle": "Refreshes native CUDA PPO/MASA training and prediction rows from clean V2 feature snapshots. It should improve model learning and publish predictions; it does not touch exchange orders.",
            "replay": "Reconstructs prior decision states to check whether the model, risk, and orchestrator behaved consistently with the data available at that time.",
            "backtest": "Scores strategy rules and model decisions against historical or replay windows to estimate expectancy, false positives, false negatives, and drawdown before trusting new behavior.",
            "full_pipeline": "Runs the safe V2 paper/training data path together: ingest freshness, feature snapshots, predictions, risk, orchestrator, paper ledger, and website payloads. It still cannot place real orders.",
            "risk_manager": "Applies fee, churn, lineage, symbol, profile, and safety gates after the trainer predicts. It explains why an otherwise interesting signal is allowed, downranked, or blocked.",
            "orchestrator": "Chooses between model proposals, resolves conflicts, and emits a traceable signal candidate only when evidence is comparable and fresh.",
            "paper_trader": "Turns eligible signal candidates into paper fills and positions, then mark-to-markets equity from current prices. It is the proving ground before live use.",
            "live_trader": "Can submit only after live gate, accepted symbols, risk profile, lineage, exchange filters, kill switch, signed reads, and available margin all pass.",
        },
        "explanations": explanations,
        "issues_and_next_fixes": [
            "If paper rows are blocked for missing market_state_id or valid_for_paper, propagate market-state integrity fields from prediction to orchestrator and paper intent rows.",
            "If confidence remains near 50-55%, keep collecting paper outcomes and use false-positive/false-negative feedback to calibrate action thresholds per symbol/timeframe.",
            "If optional data families are missing, mask them cleanly for training; do not let missing optional data appear as clean zero values.",
            "If expected_move_after_cost is negative, treat the signal as non-actionable unless a strategy-specific exit/reduce rule applies.",
            "Use liquidation levels and orderbook imbalance as context features, not sole entry triggers; they are most useful when they agree with trend, expected move, and risk gates.",
        ],
        "safety": safety,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_outputs(payload: dict[str, Any]) -> None:
    for base in (PUBLIC_DIR, READY_DIR):
        _write_json(base / "prediction_signal_explanations.json", payload)
        _write_json(base / "operator_dashboard_payload.json", payload)
        _write_json(
            base / "GO_NO_GO.md",
            "V2_PREDICTION_SIGNAL_NATURAL_LANGUAGE_EXPLAINER_READY\n",
        )
        report = [
            "# V2 Prediction Signal Natural Language Explainer Report",
            "",
            "Gate: `V2_PREDICTION_SIGNAL_NATURAL_LANGUAGE_EXPLAINER_READY`",
            f"Generated EST: `{payload['generated_est']}`",
            f"Prediction rows explained: `{payload['summary']['explanation_rows']}`",
            f"Live gate: `{payload['summary'].get('live_gate')}`",
            f"Trader state: `{payload['summary'].get('trader_state')}`",
            f"Live submit blocker: `{payload['summary'].get('live_submit_blocker')}`",
            "",
            "Safety: read-only explainer; no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, and no raw credential output.",
            "",
        ]
        _write_json(base / "prediction_signal_explanation_summary.json", payload.get("summary", {}))
        (base / "V2_PREDICTION_SIGNAL_NATURAL_LANGUAGE_EXPLAINER_REPORT.md").write_text(
            "\n".join(report),
            encoding="utf-8",
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="v2_prediction_signal_natural_language_explainer")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_EXPLANATION_LIMIT,
        help="maximum symbol/timeframe explanation rows to publish; default covers the full current trainer grid",
    )
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    while True:
        payload = build_payload(limit=max(1, int(args.limit)))
        write_outputs(payload)
        print(
            json.dumps(
                {
                    "generated_est": payload["generated_est"],
                    "explanation_rows": payload["summary"]["explanation_rows"],
                    "live_submit_blocker": payload["summary"].get("live_submit_blocker"),
                },
                sort_keys=True,
            ),
            flush=True,
        )
        if not args.loop:
            break
        time.sleep(max(10, int(args.interval_seconds)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
