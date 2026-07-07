from __future__ import annotations

from datetime import datetime, timezone
from statistics import fmean
from typing import Any, Mapping, Sequence

from v2.backend.app.services.market_state_integrity.masa_ppo_disagreement import (
    classify_masa_ppo_disagreement,
)

MODE_TREND = "trend_mode"
MODE_MEAN_REVERSION = "mean_reversion_mode"
MODE_BREAKOUT = "breakout_mode"
MODE_SCALP = "scalp_mode"
MODE_REDUCE_SIZE = "reduce_size_mode"
MODE_NO_TRADE = "no_trade_mode"

STRATEGY_TREND_CONTINUATION = "trend_continuation"
STRATEGY_BREAKOUT_SQUEEZE = "breakout_squeeze"
STRATEGY_MEAN_REVERSION = "mean_reversion"
STRATEGY_RANGE_SCALP = "range_scalp"
STRATEGY_LIQUIDITY_SWEEP_REVERSAL = "liquidity_sweep_reversal"
STRATEGY_RISK_OFF_NO_TRADE = "risk_off_no_trade"
STRATEGY_REDUCE_ONLY_RECOVERY = "reduce_only_recovery"
REQUIRED_STRATEGY_MODES = (
    STRATEGY_TREND_CONTINUATION,
    STRATEGY_BREAKOUT_SQUEEZE,
    STRATEGY_MEAN_REVERSION,
    STRATEGY_RANGE_SCALP,
    STRATEGY_LIQUIDITY_SWEEP_REVERSAL,
    STRATEGY_RISK_OFF_NO_TRADE,
    STRATEGY_REDUCE_ONLY_RECOVERY,
)

LABEL_TREND = "TREND"
LABEL_RANGE = "RANGE"
LABEL_BREAKOUT = "BREAKOUT"
LABEL_HIGH_VOLATILITY = "HIGH_VOLATILITY"
LABEL_LOW_LIQUIDITY = "LOW_LIQUIDITY"
LABEL_DATA_UNRELIABLE = "DATA_UNRELIABLE"
LABEL_MODEL_DISAGREEMENT = "MODEL_DISAGREEMENT"
LABEL_NO_TRADE = "NO_TRADE"
LABEL_LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"
LABEL_RISK_OFF = "RISK_OFF"

REQUIRED_REGIME_FEATURES = (
    "trend_strength",
    "range_chop_score",
    "volatility_expansion",
    "atr_percentile",
    "funding_skew",
    "open_interest_change",
    "long_short_ratio",
    "liquidation_cluster_proximity",
    "orderbook_imbalance",
    "spread_depth_slippage",
    "aggressive_flow",
    "cross_asset_btc_eth_sol_regime",
    "market_wide_risk",
    "fakeout_reversal_probability",
)

_KNOWN_ACTIONS = ("hold", "long", "short", "close")
_KNOWN_POSITION_STATES = {"FLAT", "LONG", "SHORT", "INVALID"}

DEFAULT_ROUTER_CONFIG: dict[str, float | bool] = {
    "data_quality_min_score": 80.0,
    "masa_confidence_min": 0.55,
    "ppo_confidence_min": 0.52,
    "execution_success_min_probability": 0.45,
    "drawdown_block_bps": 250.0,
    "drawdown_reduce_bps": 125.0,
    "breakout_expected_move_bps": 18.0,
    "scalp_expected_move_bps": 10.0,
    "high_volatility_threshold": 0.02,
    "high_spread_bps_threshold": 12.0,
    "low_liquidity_threshold": 0.35,
    "disagreement_reduce_size_multiplier": 0.5,
    "low_confidence_reduce_size_multiplier": 0.6,
    "high_volatility_reduce_size_multiplier": 0.7,
    "low_liquidity_reduce_size_multiplier": 0.5,
    "drawdown_reduce_size_multiplier": 0.5,
    "microstructure_min_trust_score": 0.65,
    "microstructure_shadow_block_threshold": 0.45,
    "microstructure_reduce_size_multiplier": 0.5,
    "microstructure_sweep_block_threshold": 0.75,
    "microstructure_sweep_reduce_threshold": 0.55,
    "paper_insufficient_execution_sample_reduce_size_multiplier": 0.65,
    "paper_major_move_min_evidence_score": 0.60,
    "paper_major_move_min_expected_move_bps": 10.0,
    "block_on_htf_conflict": True,
    "block_on_mid_conflict": True,
}


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        out = float(value)
        return out if out == out and out not in (float("inf"), float("-inf")) else None
    if isinstance(value, str):
        try:
            out = float(value)
        except (TypeError, ValueError):
            return None
        return out if out == out and out not in (float("inf"), float("-inf")) else None
    return None


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _timeframe_seconds(value: Any) -> int:
    text = str(value or "").strip().lower()
    if not text:
        return 0
    unit = text[-1]
    try:
        amount = int(text[:-1])
    except ValueError:
        return 0
    if unit == "m":
        return amount * 60
    if unit == "h":
        return amount * 3600
    if unit == "d":
        return amount * 86400
    return 0


def _normalize_action(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"buy", "open_long"}:
        return "long"
    if text in {"sell", "open_short"}:
        return "short"
    if text in {"flat", "abstain"}:
        return "hold"
    return text if text in _KNOWN_ACTIONS else "hold"


def _normalize_position_state(value: Any) -> str:
    if value is None or str(value).strip() == "":
        return "FLAT"
    text = str(value).strip().upper()
    if text in {"OPEN_LONG", "LONG_OPEN"}:
        return "LONG"
    if text in {"OPEN_SHORT", "SHORT_OPEN"}:
        return "SHORT"
    if text in {"NO_OPEN_POSITION", "NONE", "UNKNOWN"}:
        return "FLAT"
    if text in {"CONFLICT", "INVALID"} or text.startswith("INVALID_"):
        return "INVALID"
    return text if text in _KNOWN_POSITION_STATES else "FLAT"


def _direction_from_row(row: Mapping[str, Any]) -> str | None:
    action = _normalize_action(
        row.get("masa_direction")
        or row.get("masa_selected_direction")
        or row.get("selected_action")
        or row.get("side")
    )
    if action in {"long", "short"}:
        return action
    move = _coerce_float(
        row.get("expected_move_after_cost_bps")
        if row.get("expected_move_after_cost_bps") is not None
        else row.get("expected_move_bps")
    )
    if move is None:
        return None
    if move > 0:
        return "long"
    if move < 0:
        return "short"
    return None


def _confidence_from_row(row: Mapping[str, Any]) -> float | None:
    value = _coerce_float(
        row.get("masa_confidence")
        if row.get("masa_confidence") is not None
        else row.get("confidence_calibrated")
    )
    if value is not None:
        return max(0.0, min(1.0, value))
    probs = row.get("action_probabilities") or row.get("policy_action_probabilities")
    if isinstance(probs, Sequence) and not isinstance(probs, (str, bytes)):
        numeric = [_coerce_float(v) for v in probs]
        numeric = [v for v in numeric if v is not None]
        if numeric:
            return max(0.0, min(1.0, max(numeric)))
    return None


def _expected_move_from_row(row: Mapping[str, Any]) -> float | None:
    value = _coerce_float(
        row.get("expected_move_after_cost_bps")
        if row.get("expected_move_after_cost_bps") is not None
        else row.get("expected_move_bps")
    )
    return value


def _select_timeframe_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any] | None]:
    ordered = sorted(
        [row for row in rows if isinstance(row, Mapping)],
        key=lambda row: (_timeframe_seconds(row.get("timeframe")), str(row.get("generated_utc") or row.get("generated_at") or "")),
    )
    if not ordered:
        return {"higher": None, "mid": None, "lower": None}
    if len(ordered) == 1:
        only = ordered[0]
        return {"higher": only, "mid": only, "lower": only}
    if len(ordered) == 2:
        return {"higher": ordered[-1], "mid": ordered[-1], "lower": ordered[0]}
    return {"higher": ordered[-1], "mid": ordered[len(ordered) // 2], "lower": ordered[0]}


def _future_cutoff_detected(
    *,
    market_state_envelope: Mapping[str, Any],
    timeframe_rows: Sequence[Mapping[str, Any]],
) -> bool:
    decision_time = _parse_time(
        market_state_envelope.get("decision_time")
        or market_state_envelope.get("generated_utc")
        or market_state_envelope.get("observation_time")
    )
    if decision_time is None:
        return False
    for row in timeframe_rows:
        feature_cutoff = _parse_time(row.get("feature_cutoff") or row.get("generated_at"))
        if feature_cutoff is not None and feature_cutoff > decision_time:
            return True
    return False


def _position_transition_allowed(position_state: str, action: str) -> bool:
    if action not in {"long", "short"}:
        return True
    if position_state == "FLAT":
        return True
    if position_state == "LONG":
        return action == "long"
    if position_state == "SHORT":
        return action == "short"
    return False


def _combine_confidence(values: Sequence[float | None]) -> float:
    usable = [value for value in values if value is not None]
    if not usable:
        return 0.0
    return max(0.0, min(1.0, fmean(usable)))


def _paper_only_envelope(envelope: Mapping[str, Any]) -> bool:
    mode = str(envelope.get("mode") or envelope.get("runtime_mode") or "").lower()
    return envelope.get("paper_only") is True or mode in {"paper", "paper_shadow", "paper_only"}


def _confidence_bucket(confidence: float | None) -> str:
    if confidence is None:
        return "missing"
    for low, high in (
        (0.0, 0.5),
        (0.5, 0.6),
        (0.6, 0.7),
        (0.7, 0.8),
        (0.8, 0.9),
        (0.9, 1.01),
    ):
        if low <= confidence < high:
            return f"{low:.1f}-{high:.1f}"
    return "1.0-plus"


def _known_bucket_value(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and text.upper() != "UNKNOWN"


def _paper_loss_quarantine_blocked_keys(envelope: Mapping[str, Any]) -> set[str]:
    direct = envelope.get("paper_loss_quarantine_blocked_bucket_keys")
    if isinstance(direct, Sequence) and not isinstance(direct, (str, bytes)):
        return {str(item) for item in direct if str(item)}
    status = _as_mapping(envelope.get("paper_loss_quarantine_status"))
    keys = status.get("blocked_bucket_keys")
    if isinstance(keys, Sequence) and not isinstance(keys, (str, bytes)):
        return {str(item) for item in keys if str(item)}
    return set()


def _paper_loss_quarantine_candidate_keys(
    *,
    envelope: Mapping[str, Any],
    action: str,
    confidence: float | None,
    strategy_mode: Any | None = None,
    regime_labels: Sequence[Any] | None = None,
) -> set[str]:
    symbol = str(envelope.get("symbol") or "UNKNOWN").upper()
    timeframe = str(envelope.get("timeframe") or "UNKNOWN")
    strategy = str(
        _first_present(
            strategy_mode,
            envelope.get("strategy_mode"),
            envelope.get("strategy_canonical_mode"),
            envelope.get("strategy_id"),
            envelope.get("strategy_family"),
            envelope.get("strategy_selected_mode"),
            envelope.get("strategy_router_selected_mode"),
        )
        or "UNKNOWN"
    )
    regime = str(
        _first_present(
            envelope.get("market_regime"),
            envelope.get("market_regime_at_entry"),
            envelope.get("strategy_market_regime"),
        )
        or "UNKNOWN"
    )
    confidence_bucket = _confidence_bucket(confidence)
    keys = {f"{symbol}|{timeframe}|{strategy}|{regime}"}
    if _known_bucket_value(action):
        keys.add(f"side:{action}")
    if _known_bucket_value(regime):
        keys.add(f"regime:{regime}")
    if _known_bucket_value(timeframe):
        keys.add(f"timeframe:{timeframe}")
    if _known_bucket_value(strategy) and _known_bucket_value(regime):
        keys.add(f"strategy_regime:{strategy}|{regime}")
    if _known_bucket_value(confidence_bucket) and _known_bucket_value(regime):
        keys.add(f"confidence_regime:{confidence_bucket}|{regime}")
    for label in regime_labels or ():
        label_text = str(label or "").strip()
        if not _known_bucket_value(label_text):
            continue
        keys.add(f"regime:{label_text}")
        if _known_bucket_value(strategy):
            keys.add(f"strategy_regime:{strategy}|{label_text}")
            if _known_bucket_value(symbol) and _known_bucket_value(timeframe):
                keys.add(f"{symbol}|{timeframe}|{strategy}|{label_text}")
        if _known_bucket_value(confidence_bucket):
            keys.add(f"confidence_regime:{confidence_bucket}|{label_text}")
    return keys


def _execution_sample_is_insufficient(metrics: Mapping[str, Any]) -> bool:
    source = str(metrics.get("execution_success_metric_source") or "")
    sample_status = str(metrics.get("execution_success_sample_status") or "")
    return (
        source == "V2_PAPER_ACCEPTED_BLOCKED_FALLBACK"
        or sample_status in {"NO_CLOSED_OUTCOMES_FALLBACK", "NO_CLOSED_OUTCOMES"}
    )


def _paper_major_move_evidence(
    *,
    envelope: Mapping[str, Any],
    action: str,
    expected_move_bps: float,
    cfg: Mapping[str, Any],
) -> dict[str, Any]:
    evidence_score = _coerce_float(
        envelope.get("major_move_evidence_score")
        if envelope.get("major_move_evidence_score") is not None
        else envelope.get("squeeze_evidence_score")
    )
    direction = _normalize_action(envelope.get("major_move_direction") or envelope.get("selected_action") or action)
    signal_id = envelope.get("major_move_signal_id")
    paper_candidate = envelope.get("paper_major_move_candidate") is True or bool(signal_id)
    expected_edge = abs(expected_move_bps)
    allowed = (
        _paper_only_envelope(envelope)
        and paper_candidate
        and action in {"long", "short"}
        and direction == action
        and evidence_score is not None
        and evidence_score >= float(cfg["paper_major_move_min_evidence_score"])
        and expected_edge >= float(cfg["paper_major_move_min_expected_move_bps"])
    )
    return {
        "allowed": allowed,
        "paper_candidate": paper_candidate,
        "direction": direction,
        "evidence_score": evidence_score,
        "expected_edge_bps": expected_edge,
        "major_move_signal_id": signal_id,
    }


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _nested_float(*sources_and_keys: tuple[Mapping[str, Any], str]) -> float | None:
    for source, key in sources_and_keys:
        value = _coerce_float(_as_mapping(source).get(key))
        if value is not None:
            return value
    return None


def _context(envelope: Mapping[str, Any], predictions: Sequence[Mapping[str, Any]], name: str) -> Mapping[str, Any]:
    direct = _as_mapping(envelope.get(name))
    if direct:
        return direct
    for row in predictions:
        value = _as_mapping(row.get(name))
        if value:
            return value
    return {}


def _premium_regime_features(
    *,
    envelope: Mapping[str, Any],
    predictions: Sequence[Mapping[str, Any]],
    volatility_liquidity_state: Mapping[str, Any],
) -> dict[str, Any]:
    liquidity = _context(envelope, predictions, "liquidity_context")
    liquidation = _context(envelope, predictions, "liquidation_context") or _context(
        envelope,
        predictions,
        "liquidation_distance_context",
    )
    cascade_context = _context(envelope, predictions, "cascade_context")
    micro = _context(envelope, predictions, "microstructure_context")
    oi_funding = _context(envelope, predictions, "oi_funding_context")
    public_intel = _context(envelope, predictions, "public_intel_context")
    trend_strength = _nested_float(
        (envelope, "trend_strength"),
        (envelope, "htf_trend_strength"),
        (public_intel, "market_breadth_score"),
    )
    chop = _nested_float((envelope, "range_chop_score"), (envelope, "chop_score"), (envelope, "range_score"))
    volatility_expansion = _nested_float(
        (envelope, "volatility_expansion"),
        (volatility_liquidity_state, "volatility_expansion"),
        (volatility_liquidity_state, "volatility"),
        (volatility_liquidity_state, "volatility_pct"),
    )
    spread = _nested_float((micro, "bid_ask_spread_bps"), (micro, "spread_bps"), (volatility_liquidity_state, "bid_ask_spread_bps"))
    depth = _nested_float((liquidity, "orderbook_depth_usd"), (micro, "orderbook_depth_usd"), (volatility_liquidity_state, "orderbook_depth_usd"))
    slippage = _nested_float((envelope, "expected_slippage_bps"), (volatility_liquidity_state, "expected_slippage_bps"))
    spread_depth_slippage = {
        "bid_ask_spread_bps": spread,
        "orderbook_depth_usd": depth,
        "expected_slippage_bps": slippage,
    }
    return {
        "trend_strength": trend_strength,
        "range_chop_score": chop,
        "volatility_expansion": volatility_expansion,
        "atr_percentile": _nested_float((envelope, "atr_percentile"), (volatility_liquidity_state, "atr_percentile")),
        "funding_skew": _nested_float((oi_funding, "funding_skew"), (oi_funding, "funding_bps"), (oi_funding, "funding_rate")),
        "open_interest_change": _nested_float((oi_funding, "oi_change_pct"), (oi_funding, "open_interest_change_pct")),
        "long_short_ratio": _nested_float((oi_funding, "long_short_ratio")),
        "liquidation_cluster_proximity": _nested_float(
            (cascade_context, "liquidation_level_proximity_component"),
            (liquidation, "liquidation_sweep_target_short_distance_bps"),
            (liquidation, "liquidation_sweep_target_long_distance_bps"),
            (liquidation, "liquidation_distance_pct"),
            (liquidation, "nearest_distance_bps"),
        ),
        "cascade_context_status": _first_present(
            envelope.get("cascade_context_status"),
            cascade_context.get("cascade_context_status"),
        ),
        "cascade_risk_score": _nested_float(
            (envelope, "cascade_risk_score"),
            (cascade_context, "cascade_risk_score"),
            (liquidation, "liquidation_cascade_risk"),
            (liquidation, "cascade_risk"),
        ),
        "cascade_missing_mask": _first_present(
            envelope.get("cascade_missing_mask"),
            cascade_context.get("missing_mask"),
        ),
        "cascade_stale_mask": _first_present(
            envelope.get("cascade_stale_mask"),
            cascade_context.get("stale_mask"),
        ),
        "cascade_source_availability": _first_present(
            envelope.get("cascade_source_availability"),
            cascade_context.get("source_availability"),
        ),
        "orderbook_imbalance": _nested_float((micro, "orderbook_imbalance"), (micro, "depth_imbalance"), (liquidity, "depth_imbalance")),
        "spread_depth_slippage": spread_depth_slippage,
        "aggressive_flow": _nested_float(
            (micro, "order_flow_imbalance"),
            (micro, "tape_imbalance"),
            (envelope, "aggressive_flow"),
        ),
        "cross_asset_btc_eth_sol_regime": _first_present(
            envelope.get("cross_asset_btc_eth_sol_regime"),
            envelope.get("cross_asset_regime"),
            public_intel.get("cross_asset_btc_eth_sol_regime"),
        ),
        "market_wide_risk": _first_present(
            envelope.get("market_wide_risk"),
            envelope.get("risk_on_risk_off"),
            public_intel.get("market_breadth_score"),
        ),
        "fakeout_reversal_probability": _nested_float(
            (envelope, "fakeout_reversal_probability"),
            (micro, "post_sweep_reversal_probability"),
            (liquidation, "fakeout_reversal_probability"),
            (public_intel, "fakeout_reversal_probability"),
        ),
        "microstructure_trust_score": _nested_float(
            (envelope, "microstructure_trust_score"),
            (micro, "microstructure_trust_score"),
            (micro, "orderbook_trust_score"),
        ),
        "microstructure_action": _first_present(
            envelope.get("microstructure_action"),
            micro.get("microstructure_action"),
        ),
        "sweep_risk": _nested_float(
            (envelope, "sweep_risk"),
            (envelope, "sweep_risk_score"),
            (micro, "sweep_risk"),
            (micro, "sweep_risk_score"),
        ),
        "cross_venue_confirmation_score": _nested_float(
            (envelope, "cross_venue_confirmation_score"),
            (micro, "cross_venue_confirmation_score"),
            (micro, "cross_venue_confirmation"),
        ),
        "trade_tape_confirmation_score": _nested_float(
            (envelope, "trade_tape_confirmation_score"),
            (micro, "trade_tape_confirmation_score"),
        ),
    }


def _regime_feature_status(features: Mapping[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    present: list[str] = []
    for name in REQUIRED_REGIME_FEATURES:
        value = features.get(name)
        if isinstance(value, Mapping):
            if any(item not in (None, "", [], {}) for item in value.values()):
                present.append(name)
            else:
                missing.append(name)
        elif value in (None, "", [], {}):
            missing.append(name)
        else:
            present.append(name)
    return {
        "required_features": list(REQUIRED_REGIME_FEATURES),
        "present_features": present,
        "missing_features": missing,
        "all_required_features_present": not missing,
        "missing_features_are_explicit": True,
    }


def _bucket_performance_state(
    envelope: Mapping[str, Any],
    recent_execution_success_metrics: Mapping[str, Any],
) -> dict[str, Any]:
    perf = _as_mapping(envelope.get("bucket_performance") or recent_execution_success_metrics.get("bucket_performance"))
    profit_factor = _coerce_float(
        _first_present(
            perf.get("profit_factor"),
            perf.get("PF"),
            envelope.get("bucket_profit_factor"),
            recent_execution_success_metrics.get("bucket_profit_factor"),
        )
    )
    expectancy = _coerce_float(
        _first_present(
            perf.get("expectancy"),
            perf.get("expectancy_bps"),
            envelope.get("bucket_expectancy_bps"),
            recent_execution_success_metrics.get("bucket_expectancy_bps"),
        )
    )
    sample_count = _coerce_float(
        _first_present(
            perf.get("sample_count"),
            perf.get("closed_trades"),
            envelope.get("bucket_closed_trades"),
            recent_execution_success_metrics.get("bucket_closed_trades"),
        )
    )
    negative = (profit_factor is not None and profit_factor < 1.0) or (
        expectancy is not None and expectancy <= 0.0
    )
    return {
        "profit_factor": profit_factor,
        "expectancy_bps": expectancy,
        "sample_count": int(sample_count) if sample_count is not None else None,
        "negative_bucket": negative,
        "quarantine_reason": "NEGATIVE_BUCKET_PERFORMANCE" if negative else None,
    }


def _canonical_strategy_mode(
    *,
    selected_mode: str,
    block_reason: str | None,
    position_state: str,
    labels: Sequence[str],
    features: Mapping[str, Any],
) -> str:
    if block_reason is not None or LABEL_NO_TRADE in labels or LABEL_RISK_OFF in labels:
        return STRATEGY_RISK_OFF_NO_TRADE
    if position_state in {"LONG", "SHORT"}:
        return STRATEGY_REDUCE_ONLY_RECOVERY
    if (
        selected_mode != MODE_TREND
        and features.get("fakeout_reversal_probability") is not None
        and features.get("liquidation_cluster_proximity") is not None
    ):
        return STRATEGY_LIQUIDITY_SWEEP_REVERSAL
    if selected_mode == MODE_REDUCE_SIZE:
        return STRATEGY_REDUCE_ONLY_RECOVERY
    if selected_mode == MODE_BREAKOUT:
        return STRATEGY_BREAKOUT_SQUEEZE
    if selected_mode == MODE_TREND:
        return STRATEGY_TREND_CONTINUATION
    if selected_mode == MODE_SCALP:
        return STRATEGY_RANGE_SCALP
    if selected_mode == MODE_MEAN_REVERSION:
        return STRATEGY_MEAN_REVERSION
    return STRATEGY_RISK_OFF_NO_TRADE


def route_strategy(
    *,
    market_state_envelope: Mapping[str, Any],
    masa_predictions: Sequence[Mapping[str, Any]] | None,
    ppo_proposed_action: str,
    current_position_state: str,
    recent_execution_success_metrics: Mapping[str, Any] | None = None,
    volatility_liquidity_state: Mapping[str, Any] | None = None,
    data_quality_score: float | None = None,
    current_drawdown_risk_state: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = {**DEFAULT_ROUTER_CONFIG, **(dict(config or {}))}
    predictions = [dict(row) for row in (masa_predictions or []) if isinstance(row, Mapping)]
    envelope = dict(market_state_envelope or {})
    recent_execution_success_metrics = dict(recent_execution_success_metrics or {})
    volatility_liquidity_state = dict(volatility_liquidity_state or {})
    current_drawdown_risk_state = dict(current_drawdown_risk_state or {})

    action = _normalize_action(ppo_proposed_action)
    position_state = _normalize_position_state(current_position_state)
    timeframe_rows = _select_timeframe_rows(predictions)
    higher = timeframe_rows["higher"] or {}
    mid = timeframe_rows["mid"] or {}
    lower = timeframe_rows["lower"] or {}
    higher_direction = _direction_from_row(higher)
    mid_direction = _direction_from_row(mid)
    lower_direction = _direction_from_row(lower)
    data_quality = (
        data_quality_score
        if data_quality_score is not None
        else _coerce_float(
            envelope.get("data_quality_score")
            if envelope.get("data_quality_score") is not None
            else envelope.get("market_state_integrity_score")
        )
    )
    masa_confidence = _confidence_from_row(higher) or _confidence_from_row(mid) or _confidence_from_row(lower)
    ppo_confidence = _coerce_float(envelope.get("ppo_confidence")) or _coerce_float(envelope.get("confidence_calibrated"))
    if ppo_confidence is None:
        ppo_confidence = _confidence_from_row(envelope)
    execution_success_probability = _coerce_float(
        recent_execution_success_metrics.get("execution_success_probability")
    )
    current_drawdown_bps = _coerce_float(
        current_drawdown_risk_state.get("current_drawdown_bps")
        if current_drawdown_risk_state.get("current_drawdown_bps") is not None
        else current_drawdown_risk_state.get("drawdown_bps")
    )
    volatility = _coerce_float(
        volatility_liquidity_state.get("volatility")
        if volatility_liquidity_state.get("volatility") is not None
        else volatility_liquidity_state.get("volatility_pct")
    )
    spread_bps = _coerce_float(volatility_liquidity_state.get("bid_ask_spread_bps"))
    liquidity_score = _coerce_float(
        volatility_liquidity_state.get("liquidity_score")
        if volatility_liquidity_state.get("liquidity_score") is not None
        else volatility_liquidity_state.get("coingecko_liquidity_score")
    )
    expected_move_bps = (
        _expected_move_from_row(higher)
        or _expected_move_from_row(mid)
        or _expected_move_from_row(lower)
        or _coerce_float(envelope.get("expected_move_after_cost_bps"))
        or 0.0
    )
    paper_only = _paper_only_envelope(envelope)
    paper_loss_quarantine_blocked_keys = _paper_loss_quarantine_blocked_keys(envelope)
    paper_loss_quarantine_candidate_keys: set[str] = set()
    paper_loss_quarantine_matched_keys: list[str] = []
    execution_sample_insufficient = _execution_sample_is_insufficient(recent_execution_success_metrics)
    paper_major_move = _paper_major_move_evidence(
        envelope=envelope,
        action=action,
        expected_move_bps=float(expected_move_bps),
        cfg=cfg,
    )
    regime_features = _premium_regime_features(
        envelope=envelope,
        predictions=predictions,
        volatility_liquidity_state=volatility_liquidity_state,
    )
    regime_feature_status = _regime_feature_status(regime_features)
    bucket_performance_state = _bucket_performance_state(envelope, recent_execution_success_metrics)

    disagreement = classify_masa_ppo_disagreement(
        {
            "prediction_id": envelope.get("prediction_id"),
            "symbol": envelope.get("symbol"),
            "timeframe": envelope.get("timeframe"),
            "masa_direction": higher_direction,
            "masa_expected_move_bps": _expected_move_from_row(higher),
            "masa_confidence": masa_confidence,
            "selected_action": action,
            "confidence_calibrated": ppo_confidence,
            "ppo_action_probabilities": envelope.get("action_probabilities")
            or envelope.get("policy_action_probabilities"),
        }
    )
    has_masa_signal = any(
        bool(row)
        and (
            _direction_from_row(row) is not None
            or _confidence_from_row(row) is not None
            or _expected_move_from_row(row) is not None
            or bool(row.get("prediction_id"))
        )
        for row in (higher, mid, lower)
    )

    labels: list[str] = []
    reasons: list[str] = []
    size_multiplier = 1.0
    block_reason: str | None = None

    if bucket_performance_state["negative_bucket"] is True:
        labels.extend([LABEL_RISK_OFF, LABEL_NO_TRADE])
        reasons.append(str(bucket_performance_state["quarantine_reason"]))
        block_reason = "NEGATIVE_BUCKET_PERFORMANCE_QUARANTINE"

    if _future_cutoff_detected(market_state_envelope=envelope, timeframe_rows=predictions):
        labels.extend([LABEL_DATA_UNRELIABLE, LABEL_NO_TRADE])
        reasons.append("MASA_FUTURE_CUTOFF_BLOCK")
        block_reason = "MASA_FUTURE_CUTOFF_BLOCK"

    if data_quality is not None and data_quality < float(cfg["data_quality_min_score"]):
        labels.append(LABEL_DATA_UNRELIABLE)
        reasons.append("DATA_QUALITY_BELOW_THRESHOLD")
        block_reason = block_reason or "DATA_QUALITY_BELOW_THRESHOLD"

    if execution_success_probability is not None and execution_success_probability < float(
        cfg["execution_success_min_probability"]
    ):
        if paper_only and execution_sample_insufficient:
            reasons.append("EXECUTION_SUCCESS_SAMPLE_INSUFFICIENT_PAPER_SOFT_REDUCE")
            size_multiplier = min(
                size_multiplier,
                float(cfg["paper_insufficient_execution_sample_reduce_size_multiplier"]),
            )
        else:
            reasons.append("EXECUTION_SUCCESS_PROBABILITY_BELOW_THRESHOLD")
            block_reason = block_reason or "EXECUTION_SUCCESS_PROBABILITY_BELOW_THRESHOLD"

    if current_drawdown_bps is not None and current_drawdown_bps >= float(cfg["drawdown_block_bps"]):
        reasons.append("DRAWDOWN_LIMIT_BLOCK")
        block_reason = block_reason or "DRAWDOWN_LIMIT_BLOCK"
    elif current_drawdown_bps is not None and current_drawdown_bps >= float(cfg["drawdown_reduce_bps"]):
        reasons.append("DRAWDOWN_REDUCE_SIZE")
        size_multiplier = min(size_multiplier, float(cfg["drawdown_reduce_size_multiplier"]))

    if not _position_transition_allowed(position_state, action):
        reasons.append("POSITION_STATE_CONFLICT_BLOCK")
        block_reason = block_reason or "POSITION_STATE_CONFLICT_BLOCK"

    if action not in {"long", "short"}:
        reasons.append("PPO_ACTION_NOT_TRADABLE")
        block_reason = block_reason or "PPO_ACTION_NOT_TRADABLE"

    if higher_direction and action in {"long", "short"} and higher_direction != action:
        labels.append(LABEL_MODEL_DISAGREEMENT)
        reasons.append("HTF_DIRECTION_CONFLICT")
        if bool(cfg["block_on_htf_conflict"]):
            block_reason = block_reason or "HTF_DIRECTION_CONFLICT"
        else:
            size_multiplier = min(size_multiplier, float(cfg["disagreement_reduce_size_multiplier"]))

    if mid_direction and higher_direction and mid_direction != higher_direction:
        labels.append(LABEL_MODEL_DISAGREEMENT)
        reasons.append("MID_TIMEFRAME_CONFLICT")
        if bool(cfg["block_on_mid_conflict"]):
            block_reason = block_reason or "MID_TIMEFRAME_CONFLICT"
        else:
            size_multiplier = min(size_multiplier, float(cfg["disagreement_reduce_size_multiplier"]))

    if lower_direction and higher_direction and lower_direction != higher_direction:
        reasons.append("LOWER_TIMEFRAME_TIMING_CONFLICT")
        size_multiplier = min(size_multiplier, float(cfg["disagreement_reduce_size_multiplier"]))

    if has_masa_signal and disagreement["disagreement_classes"] != ["AGREEMENT_OR_INSUFFICIENT_MASA_FIELDS"]:
        labels.append(LABEL_MODEL_DISAGREEMENT)
        reasons.extend(str(item) for item in disagreement["disagreement_classes"])
        size_multiplier = min(size_multiplier, float(cfg["disagreement_reduce_size_multiplier"]))

    if masa_confidence is not None and masa_confidence < float(cfg["masa_confidence_min"]):
        reasons.append("MASA_CONFIDENCE_LOW")
        size_multiplier = min(size_multiplier, float(cfg["low_confidence_reduce_size_multiplier"]))
        if masa_confidence < float(cfg["masa_confidence_min"]) * 0.75:
            block_reason = block_reason or "MASA_CONFIDENCE_TOO_LOW"

    if ppo_confidence is not None and ppo_confidence < float(cfg["ppo_confidence_min"]):
        reasons.append("PPO_CONFIDENCE_LOW")
        size_multiplier = min(size_multiplier, float(cfg["low_confidence_reduce_size_multiplier"]))
        if ppo_confidence < float(cfg["ppo_confidence_min"]) * 0.75:
            block_reason = block_reason or "PPO_CONFIDENCE_TOO_LOW"

    if volatility is not None and volatility >= float(cfg["high_volatility_threshold"]):
        labels.append(LABEL_HIGH_VOLATILITY)
        reasons.append("HIGH_VOLATILITY_REDUCE_SIZE")
        size_multiplier = min(size_multiplier, float(cfg["high_volatility_reduce_size_multiplier"]))

    low_liquidity = False
    if spread_bps is not None and spread_bps >= float(cfg["high_spread_bps_threshold"]):
        low_liquidity = True
    if liquidity_score is not None and liquidity_score < float(cfg["low_liquidity_threshold"]):
        low_liquidity = True
    if low_liquidity:
        labels.append(LABEL_LOW_LIQUIDITY)
        reasons.append("LOW_LIQUIDITY_REDUCE_SIZE")
        size_multiplier = min(size_multiplier, float(cfg["low_liquidity_reduce_size_multiplier"]))

    microstructure_trust_score = _coerce_float(regime_features.get("microstructure_trust_score"))
    microstructure_action = str(regime_features.get("microstructure_action") or "").upper()
    sweep_risk = _coerce_float(regime_features.get("sweep_risk"))
    if microstructure_action in {"NO_TRADE", "SHADOW_ONLY", "CLOSE_OR_REDUCE_ONLY"}:
        labels.extend([LABEL_DATA_UNRELIABLE, LABEL_NO_TRADE])
        reasons.append(f"MICROSTRUCTURE_ACTION_{microstructure_action}")
        block_reason = block_reason or f"MICROSTRUCTURE_ACTION_{microstructure_action}"
    elif microstructure_trust_score is not None and microstructure_trust_score < float(cfg["microstructure_shadow_block_threshold"]):
        labels.extend([LABEL_DATA_UNRELIABLE, LABEL_NO_TRADE])
        reasons.append("MICROSTRUCTURE_TRUST_SCORE_UNTRUSTED")
        block_reason = block_reason or "MICROSTRUCTURE_TRUST_SCORE_UNTRUSTED"
    elif (
        microstructure_action == "REDUCE_SIZE"
        or (microstructure_trust_score is not None and microstructure_trust_score < float(cfg["microstructure_min_trust_score"]))
    ):
        reasons.append("MICROSTRUCTURE_TRUST_REDUCE_SIZE")
        size_multiplier = min(size_multiplier, float(cfg["microstructure_reduce_size_multiplier"]))
    if sweep_risk is not None and sweep_risk >= float(cfg["microstructure_sweep_block_threshold"]):
        labels.extend([LABEL_LIQUIDITY_SWEEP, LABEL_NO_TRADE])
        reasons.append("MICROSTRUCTURE_SWEEP_RISK_BLOCK")
        block_reason = block_reason or "MICROSTRUCTURE_SWEEP_RISK_BLOCK"
    elif sweep_risk is not None and sweep_risk >= float(cfg["microstructure_sweep_reduce_threshold"]):
        labels.append(LABEL_LIQUIDITY_SWEEP)
        reasons.append("MICROSTRUCTURE_SWEEP_RISK_REDUCE_SIZE")
        size_multiplier = min(size_multiplier, float(cfg["microstructure_reduce_size_multiplier"]))

    selected_mode = MODE_NO_TRADE
    if block_reason is None:
        if paper_major_move["allowed"]:
            labels.extend([LABEL_TREND, LABEL_BREAKOUT])
            reasons.append("PAPER_MAJOR_MOVE_EVIDENCE_BREAKOUT")
            selected_mode = MODE_BREAKOUT
        elif abs(expected_move_bps) >= float(cfg["breakout_expected_move_bps"]) and LABEL_HIGH_VOLATILITY in labels:
            labels.extend([LABEL_TREND, LABEL_BREAKOUT])
            selected_mode = MODE_BREAKOUT
        elif higher_direction and higher_direction == action and mid_direction in {None, action}:
            labels.append(LABEL_TREND)
            selected_mode = MODE_TREND
        elif LABEL_HIGH_VOLATILITY in labels:
            selected_mode = MODE_SCALP
        else:
            labels.append(LABEL_RANGE)
            selected_mode = MODE_MEAN_REVERSION
        if size_multiplier < 0.999:
            selected_mode = MODE_REDUCE_SIZE
    else:
        labels.append(LABEL_NO_TRADE)

    confidence = _combine_confidence(
        (
            masa_confidence,
            ppo_confidence,
            (data_quality / 100.0) if data_quality is not None else None,
            execution_success_probability,
        )
    )
    paper_loss_quarantine_confidence = (
        ppo_confidence if ppo_confidence is not None else masa_confidence
    )

    canonical_strategy_mode = _canonical_strategy_mode(
        selected_mode=selected_mode,
        block_reason=block_reason,
        position_state=position_state,
        labels=labels,
        features=regime_features,
    )
    if paper_only and paper_loss_quarantine_blocked_keys:
        paper_loss_quarantine_candidate_keys = _paper_loss_quarantine_candidate_keys(
            envelope=envelope,
            action=action,
            confidence=paper_loss_quarantine_confidence,
            strategy_mode=canonical_strategy_mode,
            regime_labels=labels,
        )
        paper_loss_quarantine_matched_keys = sorted(
            paper_loss_quarantine_blocked_keys & paper_loss_quarantine_candidate_keys
        )
        if paper_loss_quarantine_matched_keys:
            labels.extend([LABEL_RISK_OFF, LABEL_NO_TRADE])
            reasons.append("PAPER_LOSS_BUCKET_QUARANTINE")
            reasons.extend(
                f"PAPER_LOSS_BUCKET_QUARANTINE_MATCH:{key}"
                for key in paper_loss_quarantine_matched_keys
            )
            block_reason = "PAPER_LOSS_BUCKET_QUARANTINE"
            selected_mode = MODE_NO_TRADE
            canonical_strategy_mode = _canonical_strategy_mode(
                selected_mode=selected_mode,
                block_reason=block_reason,
                position_state=position_state,
                labels=labels,
                features=regime_features,
            )

    action_mask = {name: False for name in _KNOWN_ACTIONS}
    action_mask["hold"] = True
    if position_state in {"LONG", "SHORT"}:
        action_mask["close"] = True
    if selected_mode != MODE_NO_TRADE and block_reason is None:
        if higher_direction == "long" or (higher_direction is None and action == "long"):
            action_mask["long"] = True
        if higher_direction == "short" or (higher_direction is None and action == "short"):
            action_mask["short"] = True
    if position_state == "LONG":
        action_mask["short"] = False
    if position_state == "SHORT":
        action_mask["long"] = False

    allowed_actions = [name for name, allowed in action_mask.items() if allowed]
    if action not in allowed_actions and action in {"long", "short"}:
        block_reason = block_reason or "ACTION_NOT_ALLOWED_BY_ROUTER"
        if LABEL_NO_TRADE not in labels:
            labels.append(LABEL_NO_TRADE)
        selected_mode = MODE_NO_TRADE

    canonical_strategy_mode = _canonical_strategy_mode(
        selected_mode=selected_mode,
        block_reason=block_reason,
        position_state=position_state,
        labels=labels,
        features=regime_features,
    )
    market_regime = ",".join(sorted(set(labels))) if labels else LABEL_RANGE

    return {
        "selected_mode": selected_mode,
        "strategy_mode": canonical_strategy_mode,
        "strategy_modes_supported": list(REQUIRED_STRATEGY_MODES),
        "allowed_actions": allowed_actions,
        "action_mask": action_mask,
        "size_multiplier": round(max(0.0, min(1.0, size_multiplier)), 6),
        "confidence": round(confidence, 6),
        "block_reason": block_reason,
        "reason_codes": sorted(set(reasons)),
        "regime_labels": sorted(set(labels)),
        "market_regime": market_regime,
        "regime_features": regime_features,
        "regime_feature_status": regime_feature_status,
        "bucket_performance_state": bucket_performance_state,
        "strategy_bucket_key": {
            "symbol": envelope.get("symbol"),
            "timeframe": envelope.get("timeframe"),
            "strategy_mode": canonical_strategy_mode,
            "market_regime": market_regime,
            "position_state": position_state,
        },
        "bucket_quarantined": bucket_performance_state["negative_bucket"] is True,
        "bucket_quarantine_reason": bucket_performance_state["quarantine_reason"],
        "strategy_feature_snapshot_status": envelope.get("strategy_feature_snapshot_status"),
        "strategy_feature_snapshot_id": envelope.get("strategy_feature_snapshot_id"),
        "strategy_feature_snapshot_available_at": envelope.get("strategy_feature_snapshot_available_at"),
        "strategy_feature_snapshot_feature_cutoff": envelope.get("strategy_feature_snapshot_feature_cutoff"),
        "strategy_feature_snapshot_candle_closed_confirmed": envelope.get(
            "strategy_feature_snapshot_candle_closed_confirmed"
        ),
        "strategy_feature_snapshot_latest_unclosed_kline_excluded": envelope.get(
            "strategy_feature_snapshot_latest_unclosed_kline_excluded"
        ),
        "strategy_regime_feature_source_map": dict(
            _as_mapping(envelope.get("strategy_regime_feature_source_map"))
        ),
        "strategy_cross_asset_context_status": envelope.get("strategy_cross_asset_context_status"),
        "strategy_cross_asset_context_source": envelope.get("strategy_cross_asset_context_source"),
        "strategy_cross_asset_available_symbol_count": envelope.get(
            "strategy_cross_asset_available_symbol_count"
        ),
        "paper_loss_quarantine_status": envelope.get("paper_loss_quarantine_status"),
        "paper_loss_quarantine_blocked_bucket_keys": sorted(
            paper_loss_quarantine_blocked_keys
        ),
        "paper_loss_quarantine_candidate_bucket_keys": sorted(
            paper_loss_quarantine_candidate_keys
        ),
        "paper_loss_quarantine_matched_bucket_keys": paper_loss_quarantine_matched_keys,
        "explanation": {
            "higher_timeframe": {
                "timeframe": higher.get("timeframe"),
                "direction": higher_direction,
                "confidence": _confidence_from_row(higher),
                "feature_cutoff": higher.get("feature_cutoff"),
            },
            "mid_timeframe": {
                "timeframe": mid.get("timeframe"),
                "direction": mid_direction,
                "confidence": _confidence_from_row(mid),
                "feature_cutoff": mid.get("feature_cutoff"),
            },
            "lower_timeframe": {
                "timeframe": lower.get("timeframe"),
                "direction": lower_direction,
                "confidence": _confidence_from_row(lower),
                "feature_cutoff": lower.get("feature_cutoff"),
            },
            "ppo_action": action,
            "ppo_confidence": ppo_confidence,
            "masa_confidence": masa_confidence,
            "execution_success_probability": execution_success_probability,
            "data_quality_score": data_quality,
            "current_position_state": position_state,
            "volatility": volatility,
            "bid_ask_spread_bps": spread_bps,
            "liquidity_score": liquidity_score,
            "current_drawdown_bps": current_drawdown_bps,
            "expected_move_bps": expected_move_bps,
            "masa_ppo_disagreement": disagreement,
            "paper_only": paper_only,
            "execution_sample_insufficient": execution_sample_insufficient,
            "paper_major_move": paper_major_move,
        },
    }
