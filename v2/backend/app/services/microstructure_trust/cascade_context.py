"""Continuous cascade-risk context from existing V2 market data.

This module builds a persistent cascade context without inventing liquidation
events and without lowering the R29-D2 entry-gate threshold.  Missing and stale
inputs are explicit masks so consumers can distinguish true no-cascade from
missing-feed no-trade.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .feed_quality import iso_now, parse_time_ms, utc_now_ms

CASCADE_EVENT_CONFIRMED = "EVENT_CONFIRMED"
CASCADE_LEVEL_PROXIMITY_CONFIRMED = "LEVEL_PROXIMITY_CONFIRMED"
CASCADE_PROXY_CONFIRMED = "PROXY_CONFIRMED"
CASCADE_INSUFFICIENT_SHADOW_ONLY = "INSUFFICIENT_BUT_SHADOW_ONLY"
CASCADE_ABSENT_NO_TRADE = "ABSENT_NO_TRADE"
CASCADE_STALE_NO_TRADE = "STALE_NO_TRADE"

CASCADE_CONTEXT_STATUSES = (
    CASCADE_EVENT_CONFIRMED,
    CASCADE_LEVEL_PROXIMITY_CONFIRMED,
    CASCADE_PROXY_CONFIRMED,
    CASCADE_INSUFFICIENT_SHADOW_ONLY,
    CASCADE_ABSENT_NO_TRADE,
    CASCADE_STALE_NO_TRADE,
)

REQUIRED_SOURCES = (
    "coinank_level",
    "liquidation_event",
    "open_interest",
    "funding",
    "long_short",
    "orderbook",
    "spread",
    "trade_tape",
    "mark_index",
    "cross_asset",
)

FRESHNESS_BOUNDS_SECONDS = {
    "coinank_level": 6 * 3600,
    "liquidation_event": 30 * 60,
    "open_interest": 20 * 60,
    "funding": 90 * 60,
    "long_short": 30 * 60,
    "orderbook": 90,
    "spread": 90,
    "trade_tape": 180,
    "mark_index": 120,
    "cross_asset": 10 * 60,
}


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _iso_from_ms(value: int | None) -> str | None:
    if value is None:
        return None
    return (
        datetime.fromtimestamp(value / 1000.0, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _source_time_ms(
    payload: Mapping[str, Any],
    *,
    source_name: str | None = None,
) -> int | None:
    event_clock_keys = (
        "liquidation_last_event_ts",
        "feature_cutoff",
        "event_time",
        "event_time_ms",
        "event_at",
        "timestamp",
        "ts_ms",
        "ts",
        "time",
        "as_of_ms",
    )
    availability_clock_keys = (
        "available_at",
        "generated_at",
        "generated_utc",
        "fetched_utc",
        "source_utc",
        "ingest_ts",
        "updated_at",
        "updated_ts",
        "liquidation_updated_ts",
        "received_at",
    )
    # Liquidation freshness is the age of the observed event/feature cutoff,
    # never the age of a heartbeat republish. Use the same conservative order
    # for raw liquidation events. Other sources retain their prior fallback
    # compatibility after checking any explicit feature cutoff first.
    keys: tuple[str, ...]
    if source_name in {"coinank_level", "liquidation_event"}:
        keys = event_clock_keys + availability_clock_keys
    else:
        keys = (
            ("feature_cutoff", "event_time", "event_time_ms")
            + availability_clock_keys
            + ("timestamp", "ts_ms", "ts", "time", "as_of_ms")
        )
    for key in keys:
        parsed = parse_time_ms(payload.get(key))
        if parsed is not None:
            return parsed
    return None


def _flag_is_true(value: Any) -> bool:
    if value is True or value == 1:
        return True
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _explicit_invalid_reason(
    source_name: str,
    payload: Mapping[str, Any],
) -> str | None:
    if source_name != "coinank_level":
        return None
    if _flag_is_true(payload.get("liquidation_is_stale")):
        return "source_declared_stale"
    if _flag_is_true(payload.get("liquidation_no_events")):
        return "source_has_no_events"
    if _flag_is_true(payload.get("liquidation_no_fresh_market_reference")):
        return "no_fresh_market_reference"
    coverage_key = "liquidation_observation_coverage_complete"
    if not _flag_is_true(payload.get(coverage_key)):
        return "observation_window_incomplete"
    semantic_kind = str(payload.get("liquidation_semantic_kind") or "").strip()
    if semantic_kind != "observed_forced_liquidation_clusters":
        return "unsupported_liquidation_semantics"
    if not _flag_is_true(payload.get("liquidation_current_price_execution_grade")):
        return "current_price_not_execution_grade"
    price_source = str(payload.get("liquidation_current_price_source") or "").lower()
    if price_source in {"unavailable", "liquidation_event_price_ewma_fallback"}:
        return "non_market_reference_price"
    feature_cutoff = parse_time_ms(payload.get("feature_cutoff"))
    available_at = parse_time_ms(payload.get("available_at"))
    if feature_cutoff is not None and available_at is not None and feature_cutoff > available_at:
        return "feature_cutoff_after_available_at"
    return None


def _source_ingested_time_ms(payload: Mapping[str, Any]) -> int | None:
    for key in (
        "ingested_at",
        "ingest_ts",
        "received_at",
    ):
        parsed = parse_time_ms(payload.get(key))
        if parsed is not None:
            return parsed
    return None


def _source_available_time_ms(payload: Mapping[str, Any]) -> int | None:
    # Availability is a distinct PIT clock. A heartbeat/generated timestamp
    # cannot be promoted to availability on behalf of the source feature.
    return parse_time_ms(payload.get("available_at"))


def _general_lineage_invalid_reason(
    payload: Mapping[str, Any],
    *,
    decision_ms: int,
) -> str | None:
    event_ms = parse_time_ms(
        _first_present(
            payload.get("liquidation_last_event_ts"),
            payload.get("event_time"),
            payload.get("event_time_ms"),
        )
    )
    cutoff_ms = parse_time_ms(payload.get("feature_cutoff"))
    ingested_ms = _source_ingested_time_ms(payload)
    available_ms = _source_available_time_ms(payload)
    if payload and cutoff_ms is None:
        return "missing_feature_cutoff"
    if payload and ingested_ms is None:
        return "missing_ingested_at"
    if payload and available_ms is None:
        return "missing_available_at"
    if event_ms is not None and cutoff_ms is not None and event_ms > cutoff_ms:
        return "event_time_after_feature_cutoff"
    if cutoff_ms is not None and ingested_ms is not None and cutoff_ms > ingested_ms:
        return "feature_cutoff_after_ingested_at"
    if cutoff_ms is not None and available_ms is not None and cutoff_ms > available_ms:
        return "feature_cutoff_after_available_at"
    if ingested_ms is not None and available_ms is not None and ingested_ms > available_ms:
        return "ingested_at_after_available_at"
    if any(
        value is not None and value > decision_ms
        for value in (cutoff_ms, ingested_ms, available_ms)
    ):
        return "source_available_after_decision"
    return None


def _source_availability(
    *,
    sources: Mapping[str, Mapping[str, Any] | None],
    decision_time: Any = None,
) -> tuple[
    dict[str, dict[str, Any]],
    list[str],
    list[str],
    int | None,
    int | None,
]:
    decision_ms = parse_time_ms(decision_time) or utc_now_ms()
    availability: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    stale: list[str] = []
    latest_ms: int | None = None
    latest_ingested_ms: int | None = None
    for name in REQUIRED_SOURCES:
        payload = _as_mapping(sources.get(name))
        source_ms = _source_time_ms(payload, source_name=name)
        invalid_reason = _general_lineage_invalid_reason(payload, decision_ms=decision_ms)
        if invalid_reason is None:
            invalid_reason = _explicit_invalid_reason(name, payload)
        source_ingested_ms = _source_ingested_time_ms(payload)
        source_available_ms = _source_available_time_ms(payload)
        age_seconds = None if source_ms is None else max(0.0, (decision_ms - source_ms) / 1000.0)
        is_present = bool(payload)
        is_future = source_ms is not None and source_ms > decision_ms
        lineage_is_future = any(
            value is not None and value > decision_ms
            for value in (source_ingested_ms, source_available_ms)
        )
        if invalid_reason is None and lineage_is_future:
            invalid_reason = "source_available_after_decision"
        is_stale = is_present and (
            source_ms is None
            or is_future
            or invalid_reason is not None
            or (age_seconds is not None and age_seconds > FRESHNESS_BOUNDS_SECONDS[name])
        )
        if not is_present:
            missing.append(name)
        elif is_stale:
            stale.append(name)
        elif source_ms is not None:
            # Keep lineage clocks from the same source row. Combining the
            # newest event from one source with an unrelated ingestion clock
            # from another can invert event_time/ingested_at.
            if latest_ms is None or source_ms > latest_ms:
                latest_ms = source_ms
                latest_ingested_ms = source_ingested_ms
        availability[name] = {
            "available": is_present and not is_stale,
            "present": is_present,
            "stale": is_stale,
            "invalid": invalid_reason is not None,
            "invalid_reason": invalid_reason,
            "age_seconds": age_seconds,
            "source_timestamp": _iso_from_ms(source_ms),
            "source_ingested_at": _iso_from_ms(source_ingested_ms),
            "source_available_at": _iso_from_ms(source_available_ms),
            "freshness_bound_seconds": FRESHNESS_BOUNDS_SECONDS[name],
        }
    return availability, missing, stale, latest_ms, latest_ingested_ms


def _level_component(levels: Mapping[str, Any]) -> float | None:
    if str(levels.get("liquidation_semantic_kind") or "") == "observed_forced_liquidation_clusters":
        # Realized execution clusters are retrospective evidence, not an
        # estimated open-position liquidation surface. Their distance from
        # current price must never confirm future level proximity.
        return None
    explicit = _float(
        _first_present(levels.get("liquidation_cascade_risk"), levels.get("cascade_risk"))
    )
    distances = [
        _float(
            _first_present(
                levels.get("distance_to_long_liq_bps"),
                levels.get("long_distance_bps"),
                levels.get("liquidation_sweep_target_long_distance_bps"),
                levels.get("nearest_liquidation_level_bps"),
                levels.get("nearest_distance_bps"),
            )
        ),
        _float(
            _first_present(
                levels.get("liquidation_long_distance_bps"),
                levels.get("liquidation_short_distance_bps"),
                levels.get("distance_to_short_liq_bps"),
                levels.get("short_distance_bps"),
            )
        ),
    ]
    proximities = [_clamp((300.0 - value) / 300.0) for value in distances if value is not None]
    if explicit is None and not proximities:
        return None
    values = [explicit] if explicit is not None else []
    values.extend(proximities)
    return _clamp(max(values))


def _event_component(event: Mapping[str, Any]) -> float | None:
    explicit = _float(
        _first_present(event.get("cascade_risk"), event.get("liquidation_cascade_risk"))
    )
    if explicit is not None:
        return _clamp(explicit)
    notional = _float(
        _first_present(
            event.get("notional_usd"),
            event.get("liquidation_notional_usd"),
            event.get("usd_value"),
            event.get("notional"),
            event.get("notional_1h"),
            event.get("notional_24h"),
        )
    )
    count = _float(
        _first_present(
            event.get("event_count"),
            event.get("liquidation_count"),
            event.get("count"),
            event.get("count_1h"),
            event.get("count_24h"),
            event.get("event_count_in_ring"),
        )
    )
    components = []
    if notional is not None:
        components.append(_clamp(notional / 5_000_000.0))
    if count is not None:
        components.append(_clamp(count / 25.0))
    return max(components) if components else None


def _oi_component(oi: Mapping[str, Any]) -> float | None:
    change = _float(
        _first_present(
            oi.get("oi_change_pct"), oi.get("open_interest_change_pct"), oi.get("change_pct")
        )
    )
    return None if change is None else _clamp(abs(change) / 0.05)


def _funding_component(funding: Mapping[str, Any]) -> float | None:
    value = _float(
        _first_present(
            funding.get("funding_skew"),
            funding.get("funding_rate"),
            funding.get("last_funding_rate"),
            funding.get("funding_bps"),
        )
    )
    if value is None:
        return None
    if abs(value) > 1.0:
        return _clamp(abs(value) / 25.0)
    return _clamp(abs(value) / 0.001)


def _long_short_component(long_short: Mapping[str, Any]) -> float | None:
    ratio = _float(
        _first_present(
            long_short.get("long_short_ratio"),
            long_short.get("longShortRatio"),
            long_short.get("ratio"),
        )
    )
    if ratio is None:
        long_pct = _float(
            _first_present(long_short.get("long_account_pct"), long_short.get("long_pct"))
        )
        short_pct = _float(
            _first_present(long_short.get("short_account_pct"), long_short.get("short_pct"))
        )
        if long_pct is not None and short_pct is not None and short_pct != 0.0:
            ratio = long_pct / short_pct
    if ratio is None:
        return None
    return _clamp(abs(ratio - 1.0) / 2.0)


def _orderbook_component(orderbook: Mapping[str, Any]) -> float | None:
    depth_collapse = _float(
        _first_present(orderbook.get("depth_collapse_bps"), orderbook.get("depth_collapse_score"))
    )
    imbalance = _float(
        _first_present(
            orderbook.get("orderbook_imbalance"),
            orderbook.get("depth_imbalance"),
            orderbook.get("imbalance"),
        )
    )
    depth_usd = _float(
        _first_present(
            orderbook.get("market_depth_usd"),
            orderbook.get("orderbook_depth_usd"),
            orderbook.get("depth_usd"),
        )
    )
    components = []
    if depth_collapse is not None:
        components.append(
            _clamp(depth_collapse if depth_collapse <= 1 else depth_collapse / 3500.0)
        )
    if imbalance is not None:
        components.append(_clamp(abs(imbalance)))
    if depth_usd is not None:
        components.append(_clamp((250_000.0 - depth_usd) / 250_000.0))
    return max(components) if components else None


def _spread_component(spread: Mapping[str, Any]) -> float | None:
    spread_bps = _float(
        _first_present(
            spread.get("spread_bps"),
            spread.get("bid_ask_spread_bps"),
            spread.get("real_spread_bps"),
        )
    )
    return None if spread_bps is None else _clamp(spread_bps / 20.0)


def _trade_tape_component(tape: Mapping[str, Any]) -> float | None:
    accel = _float(
        _first_present(
            tape.get("trade_tape_acceleration"),
            tape.get("aggressive_flow_acceleration"),
            tape.get("trade_update_rate"),
        )
    )
    imbalance = _float(
        _first_present(
            tape.get("trade_imbalance"),
            tape.get("order_flow_imbalance"),
            tape.get("aggressive_flow"),
        )
    )
    components = []
    if accel is not None:
        components.append(_clamp(accel / 30.0))
    if imbalance is not None:
        components.append(_clamp(abs(imbalance)))
    return max(components) if components else None


def _mark_index_component(mark_index: Mapping[str, Any]) -> float | None:
    divergence = _float(
        _first_present(
            mark_index.get("mark_index_divergence_bps"),
            mark_index.get("basis_bps"),
            mark_index.get("basis_pct"),
        )
    )
    if divergence is None:
        return None
    if abs(divergence) <= 1.0:
        divergence *= 10_000.0
    return _clamp(abs(divergence) / 50.0)


def _cross_asset_component(cross_asset: Mapping[str, Any]) -> float | None:
    move = _float(
        _first_present(
            cross_asset.get("correlated_move_score"),
            cross_asset.get("btc_eth_sol_move_score"),
            cross_asset.get("market_wide_risk"),
        )
    )
    if move is None:
        btc = _float(cross_asset.get("BTCUSDT_change_pct") or cross_asset.get("btc_change_pct"))
        eth = _float(cross_asset.get("ETHUSDT_change_pct") or cross_asset.get("eth_change_pct"))
        sol = _float(cross_asset.get("SOLUSDT_change_pct") or cross_asset.get("sol_change_pct"))
        values = [abs(v) for v in (btc, eth, sol) if v is not None]
        if values:
            move = max(values) / 0.05
    return None if move is None else _clamp(move)


def build_cascade_context(
    *,
    symbol: str,
    timeframe: str,
    sources: Mapping[str, Mapping[str, Any] | None],
    decision_time: Any = None,
) -> dict[str, Any]:
    """Build a structured cascade context from available V2 data sources."""
    generated_iso = iso_now()
    explicit_decision_ms = parse_time_ms(decision_time)
    decision_iso = _iso_from_ms(explicit_decision_ms) or generated_iso
    generated_ms = parse_time_ms(generated_iso)
    decision_ms = parse_time_ms(decision_iso)
    decision_time_safe = bool(
        generated_ms is not None and decision_ms is not None and generated_ms <= decision_ms
    )
    (
        availability,
        missing,
        stale,
        latest_ms,
        latest_ingested_ms,
    ) = _source_availability(sources=sources, decision_time=decision_iso)
    usable = {
        name: _as_mapping(sources.get(name))
        for name in REQUIRED_SOURCES
        if availability[name]["available"] is True
    }
    components = {
        "cascade_event_component": _event_component(usable.get("liquidation_event", {})),
        "liquidation_level_proximity_component": _level_component(usable.get("coinank_level", {})),
        "oi_change_component": _oi_component(usable.get("open_interest", {})),
        "funding_skew_component": _funding_component(usable.get("funding", {})),
        "long_short_component": _long_short_component(usable.get("long_short", {})),
        "orderbook_depth_component": _orderbook_component(usable.get("orderbook", {})),
        "spread_instability_component": _spread_component(usable.get("spread", {})),
        "trade_tape_component": _trade_tape_component(usable.get("trade_tape", {})),
        "mark_index_component": _mark_index_component(usable.get("mark_index", {})),
        "cross_asset_component": _cross_asset_component(usable.get("cross_asset", {})),
    }
    non_null = [value for value in components.values() if value is not None]
    proxy_names = (
        "oi_change_component",
        "funding_skew_component",
        "long_short_component",
        "orderbook_depth_component",
        "spread_instability_component",
        "trade_tape_component",
        "mark_index_component",
        "cross_asset_component",
    )
    proxy_values = [value for name in proxy_names if (value := components[name]) is not None]
    event = components["cascade_event_component"]
    level = components["liquidation_level_proximity_component"]
    proxy_avg = sum(proxy_values) / len(proxy_values) if proxy_values else None
    weighted_values = []
    if event is not None:
        weighted_values.append(event * 0.35)
    if level is not None:
        weighted_values.append(level * 0.25)
    if proxy_avg is not None:
        weighted_values.append(proxy_avg * 0.40)
    score = _clamp(sum(weighted_values) if weighted_values else 0.0)
    if event is not None and event >= 0.30:
        status = CASCADE_EVENT_CONFIRMED
    elif level is not None and level >= 0.30 and len(proxy_values) >= 1 and score >= 0.30:
        status = CASCADE_LEVEL_PROXIMITY_CONFIRMED
    elif proxy_avg is not None and len(proxy_values) >= 3 and score >= 0.30:
        status = CASCADE_PROXY_CONFIRMED
    elif non_null and not stale:
        status = CASCADE_INSUFFICIENT_SHADOW_ONLY
    elif not non_null and stale:
        status = CASCADE_STALE_NO_TRADE
    elif stale and len(stale) >= max(1, len(usable)):
        status = CASCADE_STALE_NO_TRADE
    else:
        status = CASCADE_ABSENT_NO_TRADE
    source_available = [name for name, row in availability.items() if row["available"]]
    return {
        "schema_version": "cascade_context_v1",
        "symbol": str(symbol or "").upper(),
        "timeframe": str(timeframe or "").lower(),
        "cascade_context_status": status,
        "cascade_risk_score": round(score, 8),
        **{
            key: (round(value, 8) if value is not None else None)
            for key, value in components.items()
        },
        "missing_mask": missing,
        "stale_mask": stale,
        "source_availability": availability,
        "source_available_count": len(source_available),
        "source_available": source_available,
        "event_time": _iso_from_ms(latest_ms),
        "feature_cutoff": _iso_from_ms(latest_ms),
        "ingested_at": _iso_from_ms(latest_ingested_ms),
        "available_at": generated_iso,
        "decision_time": decision_iso,
        "decision_time_safe": decision_time_safe,
        "decision_time_safety_reason": (
            None if decision_time_safe else "context_generated_after_decision_time"
        ),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "fabricated_liquidation_event": False,
        "threshold_lowered": False,
        "generated_at": generated_iso,
    }


def context_allows_short_trend_paper_entry(
    context: Mapping[str, Any], *, threshold: float = 0.30
) -> tuple[bool, str | None]:
    """Return whether structured context satisfies the short-trend cascade gate."""
    status = str(context.get("cascade_context_status") or "")
    score = _float(context.get("cascade_risk_score")) or 0.0
    if status in {
        CASCADE_EVENT_CONFIRMED,
        CASCADE_LEVEL_PROXIMITY_CONFIRMED,
        CASCADE_PROXY_CONFIRMED,
    }:
        if context.get("decision_time_safe") is not True:
            return False, "REGIME_GATE_CASCADE_CONTEXT_AVAILABLE_AFTER_DECISION"
        cutoff_ms = parse_time_ms(context.get("feature_cutoff"))
        ingested_ms = parse_time_ms(context.get("ingested_at"))
        available_ms = parse_time_ms(context.get("available_at"))
        generated_ms = parse_time_ms(context.get("generated_at"))
        decision_ms = parse_time_ms(context.get("decision_time"))
        if (
            cutoff_ms is None
            or ingested_ms is None
            or available_ms is None
            or generated_ms is None
            or decision_ms is None
        ):
            return False, "REGIME_GATE_CASCADE_CONTEXT_INVALID_LINEAGE"
        if not (
            cutoff_ms <= ingested_ms <= available_ms and generated_ms <= available_ms <= decision_ms
        ):
            return False, "REGIME_GATE_CASCADE_CONTEXT_INVALID_LINEAGE"
        if score >= threshold:
            return True, None
        return (
            False,
            f"REGIME_GATE_INSUFFICIENT_CASCADE_RISK:{score:.4f}<{threshold:.2f}:cascade_context:{status}",
        )
    if status == CASCADE_INSUFFICIENT_SHADOW_ONLY:
        return False, "REGIME_GATE_CASCADE_CONTEXT_SHADOW_ONLY"
    if status == CASCADE_STALE_NO_TRADE:
        return False, "REGIME_GATE_STALE_CASCADE_CONTEXT"
    return False, "REGIME_GATE_CASCADE_CONTEXT_ABSENT_NO_TRADE"
