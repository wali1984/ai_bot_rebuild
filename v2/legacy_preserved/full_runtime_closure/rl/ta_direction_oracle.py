"""
TA Direction Oracle — Computes reliable directional bias from REAL indicators.

Replaces the circular PPO-votes-on-PPO system with actual market data.
Reads from unified_features:{symbol}:{tf} Redis hashes which contain 2000+ features
from CoinAPI, CoinAnk, Binance forced liquidations, order book, OHLCV, etc.

Returns a directional bias per symbol: -1 (bearish), 0 (neutral), +1 (bullish)
along with a strength score (0.0 to 1.0).

Kill switch: TA_ORACLE_ENABLED (config.py, default True)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Weights for multi-TF aggregation (higher TF = more weight for bias) ──
_TF_WEIGHTS = {
    "4h": 3.0,
    "1h": 2.5,
    "15m": 1.5,
    "5m": 1.0,
    "1m": 0.5,
}

# ── Feature keys for directional signals ──
# Each tuple: (redis_hash_field, bullish_threshold, bearish_threshold, weight)
# Positive value above bullish_threshold => +1, below bearish => -1
_DIRECTION_SIGNALS = [
    # EMA stack alignment (price vs EMA20/50/200)
    ("ema_alignment_score", 0.3, -0.3, 2.0),
    # RSI directional (>55 bullish, <45 bearish)
    ("rsi_14", 55.0, 45.0, 1.5),
    # MACD histogram sign
    ("macd_histogram", 0.0, 0.0, 1.5),
    # Momentum
    ("momentum_10", 0.0, 0.0, 1.0),
    # Williams %R (<-20 overbought/bullish momentum, >-80 oversold/bearish)
    ("willr_14", -50.0, -50.0, 0.8),  # Special handling below
    # Linear regression slope
    ("linreg_slope_14", 0.0, 0.0, 1.2),
    # ADX trend strength (only amplifies, doesn't set direction)
    ("adx_14", 25.0, 0.0, 0.0),  # Used as amplifier only
    # Stochastic RSI
    ("stochrsi_k", 60.0, 40.0, 0.8),
    # CCI
    ("cci_20", 50.0, -50.0, 0.7),
    # Funding rate (negative = shorts paying = bullish pressure)
    ("funding_rate", 0.0, 0.0, 0.6),
    # Long/Short ratio from CoinAnk
    ("long_short_ratio", 1.1, 0.9, 0.8),
    # Net taker volume (buy pressure vs sell pressure)
    ("taker_buy_ratio", 0.52, 0.48, 0.7),
    # Liquidation imbalance (more short liqs = bullish squeeze)
    ("liq_imbalance", 0.0, 0.0, 1.0),
]


def _safe_float(v: Any, default: float = 0.0) -> float:
    """Safely convert Redis value to float."""
    if v is None:
        return default
    try:
        f = float(v)
        if f != f:  # NaN check
            return default
        return f
    except (ValueError, TypeError):
        return default


def _find_feature(features: Dict[str, Any], *candidates: str) -> Any:
    """
    Find a feature value by trying multiple key patterns.
    Redis unified_features keys can be:
      - Simple: "rsi_14", "ema_20", "close"
      - Namespaced: "ind_ind_BTCUSDT_ta_RSI_14_1h", "ind_ta_RSI_14_1h"
      - Mixed: "funding_rate", "kline_taker_buy_ratio"
    
    This function tries exact match first, then substring match.
    """
    # Try exact matches first
    for key in candidates:
        if key in features:
            return features[key]
    
    # Try case-insensitive partial match on the feature dict keys
    for key in candidates:
        key_upper = key.upper().replace("_", "")
        for fk, fv in features.items():
            fk_upper = fk.upper().replace("_", "")
            if key_upper in fk_upper:
                return fv
    
    return None


def _find_feature_float(features: Dict[str, Any], *candidates: str, default=0.0):
    """Find feature and convert to float. Returns default if not found."""
    val = _find_feature(features, *candidates)
    if val is None:
        return default
    result = _safe_float(val, 0.0 if default is None else default)
    return result if result != 0.0 or default is not None else default


def compute_ta_direction(
    features: Dict[str, Any],
    *,
    symbol: str = "",
    timeframe: str = "",
) -> Dict[str, Any]:
    """
    Compute directional bias from real TA indicators in a feature dict.
    
    Args:
        features: Dict from unified_features:{symbol}:{tf} Redis hash
        symbol: For logging
        timeframe: For logging
    
    Returns:
        {
            "direction": -1 | 0 | 1,
            "strength": 0.0..1.0,
            "signal_count": int,  # How many indicators contributed
            "details": {...}  # Per-indicator votes for debugging
        }
    """
    weighted_sum = 0.0
    total_weight = 0.0
    signal_count = 0
    details = {}
    
    # ADX as trend strength amplifier
    adx = _find_feature_float(features, "adx_14", "ADX_14", "adx")
    adx_multiplier = 1.0
    if adx > 40:
        adx_multiplier = 1.5  # Strong trend — amplify signals
    elif adx > 25:
        adx_multiplier = 1.2  # Moderate trend
    elif adx < 15 and adx > 0:
        adx_multiplier = 0.7  # No trend — reduce conviction
    
    # ── EMA Stack Analysis (most reliable trend indicator) ──
    price = _find_feature_float(features, "close", "current_price", "price", "ccxt_close")
    ema20 = _find_feature_float(features, "EMA_20", "ema_20", "ema20")
    ema50 = _find_feature_float(features, "EMA_50", "ema_50", "ema50")
    ema200 = _find_feature_float(features, "EMA_200", "ema_200", "ema200")
    
    if price > 0 and ema20 > 0:
        ema_score = 0.0
        ema_signals = 0
        
        # Price vs EMAs
        if price > ema20:
            ema_score += 1.0
        elif price < ema20:
            ema_score -= 1.0
        ema_signals += 1
        
        if ema50 > 0:
            if price > ema50:
                ema_score += 1.0
            elif price < ema50:
                ema_score -= 1.0
            ema_signals += 1
            
            # EMA20 vs EMA50 (golden/death cross proxy)
            if ema20 > ema50:
                ema_score += 1.5
            elif ema20 < ema50:
                ema_score -= 1.5
            ema_signals += 1
        
        if ema200 > 0:
            if price > ema200:
                ema_score += 1.0
            elif price < ema200:
                ema_score -= 1.0
            ema_signals += 1
            
            if ema50 > 0:
                if ema50 > ema200:
                    ema_score += 1.0
                elif ema50 < ema200:
                    ema_score -= 1.0
                ema_signals += 1
        
        # Normalize to -1..+1
        if ema_signals > 0:
            ema_dir = max(-1.0, min(1.0, ema_score / max(ema_signals, 1)))
            weight = 3.0 * adx_multiplier  # EMA stack is highest weight
            weighted_sum += ema_dir * weight
            total_weight += weight
            signal_count += 1
            details["ema_stack"] = round(ema_dir, 3)
    
    # ── RSI ──
    rsi = _find_feature_float(features, "RSI_14", "rsi_14", "rsi")
    if 0 < rsi <= 100:
        if rsi > 55:
            rsi_dir = min(1.0, (rsi - 50) / 30)  # Scale 55-80 to ~0.17-1.0
        elif rsi < 45:
            rsi_dir = max(-1.0, (rsi - 50) / 30)
        else:
            rsi_dir = 0.0
        weight = 1.5
        weighted_sum += rsi_dir * weight
        total_weight += weight
        signal_count += 1
        details["rsi"] = round(rsi_dir, 3)
    
    # ── MACD Histogram ──
    macd_hist = _find_feature_float(features, "MACD_hist", "macd_histogram", "macd_hist", "macdhist", default=None)
    if macd_hist is not None:
        # Normalize by price to make comparable across symbols
        if price > 0:
            macd_norm = macd_hist / price * 1000  # Scale to reasonable range
        else:
            macd_norm = macd_hist
        if abs(macd_norm) > 0.01:
            macd_dir = max(-1.0, min(1.0, macd_norm / 2.0))
            weight = 1.5 * adx_multiplier
            weighted_sum += macd_dir * weight
            total_weight += weight
            signal_count += 1
            details["macd"] = round(macd_dir, 3)
    
    # ── Momentum ──
    mom = _find_feature_float(features, "MOM_10", "momentum_10", "mom_10", "momentum", default=None)
    if mom is not None and price > 0:
        mom_norm = mom / price * 100  # As percentage
        if abs(mom_norm) > 0.1:
            mom_dir = max(-1.0, min(1.0, mom_norm / 5.0))
            weight = 1.0
            weighted_sum += mom_dir * weight
            total_weight += weight
            signal_count += 1
            details["momentum"] = round(mom_dir, 3)
    
    # ── Linear Regression Slope ──
    slope = _find_feature_float(features, "LINEARREG_SLOPE_14", "linreg_slope_14", "linreg_slope", "linear_regression_slope", default=None)
    if slope is not None and price > 0:
        slope_norm = slope / price * 1000
        if abs(slope_norm) > 0.05:
            slope_dir = max(-1.0, min(1.0, slope_norm / 3.0))
            weight = 1.2 * adx_multiplier
            weighted_sum += slope_dir * weight
            total_weight += weight
            signal_count += 1
            details["slope"] = round(slope_dir, 3)
    
    # ── StochRSI ──
    stoch_k = _find_feature_float(features, "STOCHRSI_k", "stochrsi_k", "stoch_k", "stochastic_k", default=None)
    if stoch_k is not None and 0 <= stoch_k <= 100:
        if stoch_k > 60:
            stoch_dir = min(1.0, (stoch_k - 50) / 40)
        elif stoch_k < 40:
            stoch_dir = max(-1.0, (stoch_k - 50) / 40)
        else:
            stoch_dir = 0.0
        weight = 0.8
        weighted_sum += stoch_dir * weight
        total_weight += weight
        signal_count += 1
        details["stochrsi"] = round(stoch_dir, 3)
    
    # ── CCI ──
    cci = _find_feature_float(features, "CCI_20", "cci_20", "cci", default=None)
    if cci is not None:
        if abs(cci) > 30:
            cci_dir = max(-1.0, min(1.0, cci / 200.0))
            weight = 0.7
            weighted_sum += cci_dir * weight
            total_weight += weight
            signal_count += 1
            details["cci"] = round(cci_dir, 3)
    
    # ── Funding Rate (negative = shorts paying = bullish) ──
    funding = _find_feature_float(features, "funding_rate", "fundingRate", default=None)
    if funding is not None and abs(funding) > 0.0001:
        # Negative funding = shorts paying longs = bullish pressure
        fund_dir = max(-1.0, min(1.0, -funding * 5000))  # Amplify small values
        weight = 0.6
        weighted_sum += fund_dir * weight
        total_weight += weight
        signal_count += 1
        details["funding"] = round(fund_dir, 3)
    
    # ── Long/Short Ratio (from CoinAnk) ──
    ls_ratio = _find_feature_float(features, "long_short_ratio", "ls_ratio", "coinank_ls", default=None)
    if ls_ratio is not None and ls_ratio > 0:
        if ls_ratio > 1.1:
            ls_dir = min(1.0, (ls_ratio - 1.0) / 0.5)
        elif ls_ratio < 0.9:
            ls_dir = max(-1.0, (ls_ratio - 1.0) / 0.5)
        else:
            ls_dir = 0.0
        weight = 0.8
        weighted_sum += ls_dir * weight
        total_weight += weight
        signal_count += 1
        details["ls_ratio"] = round(ls_dir, 3)
    
    # ── Taker Buy Ratio (order flow) ──
    taker = _find_feature_float(features, "kline_taker_buy_ratio", "taker_buy_ratio", "taker_buy_volume_ratio", default=None)
    if taker is not None and 0 < taker < 1:
        if taker > 0.52:
            tk_dir = min(1.0, (taker - 0.5) / 0.1)
        elif taker < 0.48:
            tk_dir = max(-1.0, (taker - 0.5) / 0.1)
        else:
            tk_dir = 0.0
        weight = 0.7
        weighted_sum += tk_dir * weight
        total_weight += weight
        signal_count += 1
        details["taker"] = round(tk_dir, 3)
    
    # ── Liquidation Imbalance (from CoinAnk/Binance forced liqs) ──
    liq_long = _find_feature_float(features, "liquidation_long_strength", "liq_long_usd", "liq_long")
    liq_short = _find_feature_float(features, "liquidation_short_strength", "liq_short_usd", "liq_short")
    if liq_long + liq_short > 0:
        # More short liquidations = bullish squeeze
        liq_total = liq_long + liq_short
        if liq_total > 0:
            liq_imbalance = (liq_short - liq_long) / liq_total  # +1 = all short liqs (bullish)
            if abs(liq_imbalance) > 0.1:
                liq_dir = max(-1.0, min(1.0, liq_imbalance * 2.0))
                weight = 1.0
                weighted_sum += liq_dir * weight
                total_weight += weight
                signal_count += 1
                details["liq_imbalance"] = round(liq_dir, 3)
    
    # ── Williams %R (inverted scale: -100 to 0) ──
    willr = _find_feature_float(features, "WILLR_14", "willr_14", "williams_r", default=None)
    if willr is not None and -100 <= willr <= 0:
        # Near 0 = overbought (bullish momentum), near -100 = oversold (bearish)
        willr_mid = -50
        if willr > -30:
            willr_dir = min(1.0, (willr - willr_mid) / 30)
        elif willr < -70:
            willr_dir = max(-1.0, (willr - willr_mid) / 30)
        else:
            willr_dir = 0.0
        weight = 0.8
        weighted_sum += willr_dir * weight
        total_weight += weight
        signal_count += 1
        details["willr"] = round(willr_dir, 3)
    
    # ── Compute final direction ──
    if total_weight > 0 and signal_count >= 2:
        raw_score = weighted_sum / total_weight  # -1..+1
        strength = min(1.0, abs(raw_score))
        
        # Require minimum conviction to declare direction
        if raw_score > 0.15:
            direction = 1
        elif raw_score < -0.15:
            direction = -1
        else:
            direction = 0
            strength = 0.0
    else:
        direction = 0
        strength = 0.0
        raw_score = 0.0
    
    return {
        "direction": direction,
        "strength": round(strength, 4),
        "raw_score": round(raw_score if total_weight > 0 else 0.0, 4),
        "signal_count": signal_count,
        "adx_multiplier": round(adx_multiplier, 2),
        "details": details,
    }


def compute_multi_tf_ta_direction(
    redis_client,
    symbol: str,
    timeframes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Compute TA-based directional bias across multiple timeframes for a symbol.
    
    Reads from unified_features:{symbol}:{tf} Redis hashes.
    
    Returns:
        {
            "direction": -1 | 0 | 1,
            "strength": 0.0..1.0,
            "per_tf": { "1h": {...}, "4h": {...}, ... },
            "htf_bias": -1 | 0 | 1,  # Higher timeframe bias (4h, 1h)
            "ltf_timing": -1 | 0 | 1,  # Lower timeframe timing (5m, 15m)
            "conflict": bool,  # HTF vs LTF disagreement
        }
    """
    if timeframes is None:
        timeframes = ["4h", "1h", "15m", "5m"]
    
    per_tf = {}
    weighted_sum = 0.0
    total_weight = 0.0
    
    htf_sum = 0.0
    htf_weight = 0.0
    ltf_sum = 0.0
    ltf_weight = 0.0
    
    htf_set = {"4h", "1h"}
    ltf_set = {"15m", "5m", "1m"}
    
    for tf in timeframes:
        try:
            key = f"unified_features:{symbol}:{tf}"
            if redis_client is None:
                continue
            raw = redis_client.hgetall(key)
            if not raw:
                continue
            
            # Decode bytes if needed
            features = {}
            for k, v in raw.items():
                k_str = k.decode() if isinstance(k, bytes) else str(k)
                v_str = v.decode() if isinstance(v, bytes) else str(v)
                features[k_str] = v_str
            
            # Check staleness (skip if data older than 10 minutes)
            ts_ms = _safe_float(features.get("ts_ms") or features.get("timestamp_ms"), 0.0)
            if ts_ms > 0:
                age_s = (time.time() * 1000 - ts_ms) / 1000
                # Relaxed staleness: TA indicators (EMA/RSI/MACD) are computed per-candle
                # and stay valid for 2x the candle period. Tight thresholds caused
                # non-major symbols to have empty per_tf (only 5m survived).
                max_age = {"4h": 28800, "1h": 7200, "15m": 1800, "5m": 600, "1m": 240}.get(tf, 7200)
                if age_s > max_age:
                    logger.debug(f"[TA_ORACLE] {symbol}:{tf} stale ({age_s:.0f}s > {max_age}s), skipping")
                    continue
            
            result = compute_ta_direction(features, symbol=symbol, timeframe=tf)
            per_tf[tf] = result
            
            tf_w = _TF_WEIGHTS.get(tf, 1.0)
            contrib = result["direction"] * result["strength"] * tf_w
            weighted_sum += contrib
            total_weight += tf_w
            
            if tf in htf_set:
                htf_sum += contrib
                htf_weight += tf_w
            elif tf in ltf_set:
                ltf_sum += contrib
                ltf_weight += tf_w
                
        except Exception as e:
            logger.debug(f"[TA_ORACLE] Error reading {symbol}:{tf}: {e}")
            continue
    
    # Compute overall direction
    if total_weight > 0:
        raw_score = weighted_sum / total_weight
        if raw_score > 0.12:
            direction = 1
        elif raw_score < -0.12:
            direction = -1
        else:
            direction = 0
        strength = min(1.0, abs(raw_score))
    else:
        direction = 0
        strength = 0.0
        raw_score = 0.0
    
    # HTF bias
    if htf_weight > 0:
        htf_score = htf_sum / htf_weight
        htf_bias = 1 if htf_score > 0.12 else (-1 if htf_score < -0.12 else 0)
    else:
        htf_bias = 0
    
    # LTF timing
    if ltf_weight > 0:
        ltf_score = ltf_sum / ltf_weight
        ltf_timing = 1 if ltf_score > 0.1 else (-1 if ltf_score < -0.1 else 0)
    else:
        ltf_timing = 0
    
    conflict = (htf_bias != 0 and ltf_timing != 0 and htf_bias != ltf_timing)

    # #region agent log
    try:
        import json as _dj
        import time as _dt
        open("/home/wali/Desktop/AI BOT/.cursor/debug-1acbe2.log", "a").write(
            _dj.dumps(
                {
                    "sessionId": "1acbe2",
                    "hypothesisId": "H5",
                    "location": "ta_direction_oracle:compute_multi_tf",
                    "message": "per_tf_coverage",
                    "data": {
                        "symbol": str(symbol),
                        "n_per_tf": len(per_tf),
                        "tfs": list(per_tf.keys()),
                        "htf_bias": int(htf_bias),
                        "ltf_timing": int(ltf_timing),
                    },
                    "timestamp": int(_dt.time() * 1000),
                }
            )
            + "\n"
        )
    except Exception:
        pass
    # #endregion

    return {
        "direction": direction,
        "strength": round(strength, 4),
        "raw_score": round(raw_score, 4),
        "per_tf": per_tf,
        "htf_bias": htf_bias,
        "ltf_timing": ltf_timing,
        "conflict": conflict,
    }


def gate_action_against_ta(
    action_name: str,
    ta_result: Dict[str, Any],
    confidence: float = 0.5,
    *,
    min_strength_to_gate: float = 0.25,
) -> Dict[str, Any]:
    """
    Check if a proposed action agrees with or conflicts with the TA direction oracle.
    
    Returns:
        {
            "allowed": bool,
            "reason": str,
            "adjusted_confidence": float,
            "ta_direction": int,
            "ta_strength": float,
        }
    
    Rules:
    - PROTECTIVE actions (CLOSE, REDUCE) are ALWAYS allowed
    - HOLD is always allowed
    - OPEN_LONG blocked if TA says bearish with strength >= min_strength_to_gate
    - OPEN_SHORT blocked if TA says bullish with strength >= min_strength_to_gate
    - Flip actions: treated as OPEN for the new direction
    - Actions WITH the trend get confidence boost
    - Actions against weak TA signal get confidence reduction but are allowed
    """
    a = str(action_name or "").upper().strip()
    ta_dir = ta_result.get("direction", 0)
    ta_str = ta_result.get("strength", 0.0)
    htf_bias = ta_result.get("htf_bias", 0)
    
    # Always allow protective actions
    if a in ("HOLD", "NONE", "WAIT", "NO_ACTION"):
        return {"allowed": True, "reason": "HOLD_PASS", "adjusted_confidence": confidence,
                "ta_direction": ta_dir, "ta_strength": ta_str}
    
    # Pure closes always allowed
    is_pure_close = ("CLOSE" in a or "REDUCE" in a) and "OPEN" not in a and "FLIP" not in a and "AND_" not in a
    if is_pure_close:
        return {"allowed": True, "reason": "PROTECTIVE_PASS", "adjusted_confidence": confidence,
                "ta_direction": ta_dir, "ta_strength": ta_str}
    
    # Determine the effective direction of the action
    is_long = ("OPEN_LONG" in a or "FLIP_LONG" in a or "FLIP_TO_LONG" in a or 
               ("CLOSE_AND" in a and "LONG" in a) or "INCREASE_LONG" in a or 
               ("CLOSE_SHORT" in a and "OPEN_LONG" in a))
    is_short = ("OPEN_SHORT" in a or "FLIP_SHORT" in a or "FLIP_TO_SHORT" in a or
                ("CLOSE_AND" in a and "SHORT" in a) or "INCREASE_SHORT" in a or
                ("CLOSE_LONG" in a and "OPEN_SHORT" in a))
    
    if not is_long and not is_short:
        # Can't determine direction — allow with warning
        return {"allowed": True, "reason": "DIRECTION_UNKNOWN_PASS", "adjusted_confidence": confidence,
                "ta_direction": ta_dir, "ta_strength": ta_str}
    
    action_dir = 1 if is_long else -1
    
    # TA signal too weak to gate
    if ta_str < min_strength_to_gate:
        return {"allowed": True, "reason": "TA_WEAK_PASS", "adjusted_confidence": confidence,
                "ta_direction": ta_dir, "ta_strength": ta_str}
    
    # Check alignment
    if action_dir == ta_dir:
        # WITH the trend — boost confidence
        boost = min(0.15, ta_str * 0.2)
        adj_conf = min(0.99, confidence + boost)
        return {"allowed": True, "reason": "TA_ALIGNED", "adjusted_confidence": adj_conf,
                "ta_direction": ta_dir, "ta_strength": ta_str}
    
    if ta_dir == 0:
        # TA neutral — allow
        return {"allowed": True, "reason": "TA_NEUTRAL_PASS", "adjusted_confidence": confidence,
                "ta_direction": ta_dir, "ta_strength": ta_str}
    
    # COUNTER-TREND: action opposes TA direction
    # Strong TA signal (>0.5 strength) AND HTF agrees → BLOCK
    if ta_str >= 0.5 and htf_bias == ta_dir:
        return {"allowed": False, "reason": "TA_COUNTER_TREND_BLOCK",
                "adjusted_confidence": max(0.01, confidence * 0.3),
                "ta_direction": ta_dir, "ta_strength": ta_str}
    
    # Moderate TA signal — reduce confidence significantly but allow
    # This lets the model take contrarian trades if very confident, but penalizes them
    penalty = ta_str * 0.4  # Up to 40% confidence reduction
    adj_conf = max(0.01, confidence - penalty)
    return {"allowed": True, "reason": "TA_COUNTER_TREND_REDUCED",
            "adjusted_confidence": adj_conf,
            "ta_direction": ta_dir, "ta_strength": ta_str}


# ── Cache to avoid hitting Redis every cycle for every symbol ──
_ta_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_TA_CACHE_TTL_S = 15.0  # Refresh every 15 seconds


def get_ta_direction_cached(
    redis_client,
    symbol: str,
    timeframes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Cached version of compute_multi_tf_ta_direction.
    Returns cached result if < _TA_CACHE_TTL_S old.
    """
    cache_key = symbol
    now = time.time()
    
    if cache_key in _ta_cache:
        ts, result = _ta_cache[cache_key]
        if now - ts < _TA_CACHE_TTL_S:
            return result
    
    result = compute_multi_tf_ta_direction(redis_client, symbol, timeframes)
    _ta_cache[cache_key] = (now, result)
    return result
