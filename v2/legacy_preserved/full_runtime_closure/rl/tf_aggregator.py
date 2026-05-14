from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


def _to_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _vote_dir(action: Any, logit: Any = None) -> int:
    # Numeric direction support (-1/0/1) from lightweight caches.
    try:
        if isinstance(action, (int, float)) and int(action) in (-1, 0, 1):
            return int(action)
        if isinstance(action, str):
            s = action.strip()
            if s in ("-1", "0", "1"):
                return int(float(s))
    except Exception:
        pass

    a = str(action or "").upper().strip()
    if a in {"FLAT", "HOLD", "NONE", "WAIT", "NO_ACTION", "UNKNOWN"}:
        return 0
    # Pure closes are non-directional; composite flips (close+open) resolve to OPEN_*.
    if a.startswith("CLOSE") and not (("OPEN_" in a) or ("AND_OPEN_" in a) or ("FLIP_" in a) or ("CLOSE_AND" in a)):
        return 0
    # Explicit open/flip tokens first (avoid "SHORT" substring dominating composite flips).
    if ("OPEN_LONG" in a) or ("AND_OPEN_LONG" in a) or ("FLIP_LONG" in a) or ("CLOSE_AND_LONG" in a) or ("CLOSE_AND_FLIP_LONG" in a):
        return 1
    if ("OPEN_SHORT" in a) or ("AND_OPEN_SHORT" in a) or ("FLIP_SHORT" in a) or ("CLOSE_AND_SHORT" in a) or ("CLOSE_AND_FLIP_SHORT" in a):
        return -1
    # Fallback to simple contains checks (avoid composite ambiguity).
    if "SHORT" in a and "LONG" not in a:
        return -1
    if "LONG" in a and "SHORT" not in a:
        return 1
    l = _to_float(logit, 0.0)
    if l < -0.15:
        return -1
    if l > 0.15:
        return 1
    return 0


def aggregate_tf_votes_from_ta_oracle(
    redis_client,
    symbol: str,
    *,
    current_conf: float = 0.0,
    timeframes: Optional[list] = None,
) -> Dict[str, Any]:
    """
    Replacement for aggregate_tf_votes that uses REAL TA indicators
    instead of PPO's own predictions (which are circular noise).
    
    Reads from unified_features:{symbol}:{tf} Redis hashes and computes
    direction from EMA stack, RSI, MACD, momentum, slope, etc.
    
    Returns same schema as aggregate_tf_votes for backward compatibility.
    """
    try:
        from rl.ta_direction_oracle import get_ta_direction_cached
    except ImportError:
        # Fallback to neutral if oracle not available
        return {
            "bias_dir": 0,
            "timing_dir": 0,
            "conflict_score": 0.5,
            "tf_votes": {},
            "ta_oracle_active": False,
        }
    
    ta = get_ta_direction_cached(redis_client, symbol, timeframes)
    
    # Build tf_votes from per-TF TA analysis
    tf_votes = {}
    for tf, tf_data in (ta.get("per_tf") or {}).items():
        tf_votes[tf] = int(tf_data.get("direction", 0))
    
    # Map TA oracle output to legacy schema
    htf_bias = ta.get("htf_bias", 0)
    ltf_timing = ta.get("ltf_timing", 0)
    conflict = ta.get("conflict", False)
    
    # Conflict score: 0 = aligned, 1 = full disagreement
    if htf_bias != 0 and ltf_timing != 0:
        conflict_score = 1.0 if htf_bias != ltf_timing else 0.0
    elif htf_bias == 0:
        conflict_score = 0.5  # No bias = moderate uncertainty
    else:
        conflict_score = 0.3  # Bias exists but no LTF timing
    
    return {
        "bias_dir": int(htf_bias),
        "timing_dir": int(ltf_timing),
        "conflict_score": float(conflict_score),
        "tf_votes": tf_votes,
        "ta_oracle_active": True,
        "ta_strength": ta.get("strength", 0.0),
        "ta_direction": ta.get("direction", 0),
    }


def aggregate_tf_votes(
    tf_preds: Mapping[str, Mapping[str, Any]],
    *,
    current_conf: float = 0.0,
    htf_timeframes: tuple[str, ...] = ("1h", "4h"),
    ltf_timeframes: tuple[str, ...] = ("1m", "5m", "15m"),
) -> Dict[str, Any]:
    """
    Aggregate multi-TF model outputs into audit-friendly bias/timing/conflict values.

    Returns:
    - bias_dir: long-term direction from HTF votes (-1/0/1)
    - timing_dir: short-term direction from LTF votes (-1/0/1)
    - conflict_score: disagreement ratio between HTF and LTF (0..1)
    - tf_votes: per-timeframe vote map
    """
    votes: Dict[str, int] = {}
    weighted_abs = 0.0
    disagree_abs = 0.0

    for tf, pred in (tf_preds or {}).items():
        pred = pred or {}
        # NOTE: get_tf_predictions_for_symbol() stores direction under "dir" key,
        # while raw prediction dicts use "action"/"final_action"/"predicted_action".
        # Support both to avoid silent all-zero votes.
        vote = _vote_dir(
            pred.get("action") or pred.get("final_action") or pred.get("predicted_action") or pred.get("dir"),
            pred.get("logit"),
        )
        votes[str(tf)] = int(vote)

    def _majority(frames: tuple[str, ...]) -> int:
        score = 0.0
        for tf in frames:
            v = int(votes.get(tf, 0))
            _pred_d = tf_preds.get(tf) or {}
            _raw_c = _pred_d.get("confidence")
            if _raw_c is None:
                _raw_c = _pred_d.get("conf")  # get_tf_predictions_for_symbol uses "conf"
            c = max(0.0, min(1.0, _to_float(_raw_c, current_conf)))
            w = 0.5 + c
            score += v * w
        if score > 0.15:
            return 1
        if score < -0.15:
            return -1
        return 0

    bias_dir = _majority(htf_timeframes)
    timing_dir = _majority(ltf_timeframes)

    for tf in ltf_timeframes:
        v = int(votes.get(tf, 0))
        _pred_c = tf_preds.get(tf) or {}
        _raw_conf = _pred_c.get("confidence")
        if _raw_conf is None:
            _raw_conf = _pred_c.get("conf")  # get_tf_predictions_for_symbol uses "conf"
        c = max(0.0, min(1.0, _to_float(_raw_conf, current_conf)))
        w = 0.5 + c
        if v == 0:
            continue
        weighted_abs += w
        if bias_dir != 0 and v != bias_dir:
            disagree_abs += w

    if bias_dir == 0:
        # No strong long-term bias -> treat as moderate conflict until bias forms.
        conflict_score = 0.5 if weighted_abs > 0 else 0.0
    else:
        conflict_score = (disagree_abs / weighted_abs) if weighted_abs > 0 else 0.0

    conflict_score = max(0.0, min(1.0, float(conflict_score)))

    return {
        "bias_dir": int(bias_dir),
        "timing_dir": int(timing_dir),
        "conflict_score": float(conflict_score),
        "tf_votes": votes,
    }
