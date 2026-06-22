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

LABEL_TREND = "TREND"
LABEL_RANGE = "RANGE"
LABEL_BREAKOUT = "BREAKOUT"
LABEL_HIGH_VOLATILITY = "HIGH_VOLATILITY"
LABEL_LOW_LIQUIDITY = "LOW_LIQUIDITY"
LABEL_DATA_UNRELIABLE = "DATA_UNRELIABLE"
LABEL_MODEL_DISAGREEMENT = "MODEL_DISAGREEMENT"
LABEL_NO_TRADE = "NO_TRADE"

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
    execution_sample_insufficient = _execution_sample_is_insufficient(recent_execution_success_metrics)
    paper_major_move = _paper_major_move_evidence(
        envelope=envelope,
        action=action,
        expected_move_bps=float(expected_move_bps),
        cfg=cfg,
    )

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

    return {
        "selected_mode": selected_mode,
        "allowed_actions": allowed_actions,
        "action_mask": action_mask,
        "size_multiplier": round(max(0.0, min(1.0, size_multiplier)), 6),
        "confidence": round(confidence, 6),
        "block_reason": block_reason,
        "reason_codes": sorted(set(reasons)),
        "regime_labels": sorted(set(labels)),
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
