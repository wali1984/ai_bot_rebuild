"""
Dynamic Position Sizing with Multi-TF Confirmation
===================================================

Rules:
1. 1m timeframe = LEARNING ONLY (never used for trading decisions)
2. Multi-TF confirmation requires 3+ action TFs agreeing (5m, 15m, 1h, 4h, 1d)
3. Trend lock = main_tf ≥ 95% confidence + 3+ TFs ≥ 80%
4. Dynamic sizing based on confidence, volatility, drawdown, and performance

Author: Enhanced RL BOT
Date: December 9, 2025
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# Timeframe classification
LEARNING_TF = "1m"  # Learning only, never for trading
ACTION_TFS = ["5m", "15m", "1h", "4h", "1d"]  # Can drive trades
DEFAULT_MAIN_TF = "15m"  # Primary decision timeframe


def compute_position_sizing(
    equity: float,
    price: float,
    atr_price: float,  # ATR in price units on main_tf
    atr_pct: float,  # ATR / price on main_tf (e.g., 0.02 = 2%)
    atr_pct_med: float,  # 30d median ATR% on main_tf
    conf_by_tf: Dict[str, float],  # {"1m": 0.73, "5m": 0.81, "15m": 0.96, ...}
    main_tf: str = DEFAULT_MAIN_TF,
    learning_tf: str = LEARNING_TF,
    drawdown: float = 0.0,  # 0.0–0.5
    perf_score: float = 0.0,  # recent performance ~ [-1, +1]
    portfolio_exposure_cap: float = 0.6,  # total portfolio cap (60% of equity)
) -> Dict[str, Any]:
    """
    Returns recommended sizing and flags for RL BOT.
    
    NOTE: 1m is learning-only: not used for gating or bucket caps.
    
    Returns:
        {
            "trend_lock": bool,
            "core_pct": float,
            "hedge_pct": float,
            "target_exposure_pct": float,
            "bucket_cap": float,
            "strong_tfs": List[str],
            "conf_main": float,
        }
    """
    # 1) Multi-TF gating (exclude 1m from confirmation)
    if main_tf not in conf_by_tf:
        logger.warning(f"main_tf {main_tf} missing in conf_by_tf, using 0.5 default")
        c_main = 0.5
    else:
        c_main = conf_by_tf[main_tf]

    # Count strong timeframes (≥ 80%) excluding learning_tf
    strong_tfs = [
        tf for tf, c in conf_by_tf.items()
        if tf != learning_tf and tf in ACTION_TFS and c >= 0.80
    ]
    
    # Trend lock = main TF ≥ 95% + at least 3 strong TFs
    trend_lock = (c_main >= 0.95 and len(strong_tfs) >= 3)

    logger.debug(
        f"Multi-TF gate: main_tf={main_tf} conf={c_main:.3f}, "
        f"strong_tfs={strong_tfs} ({len(strong_tfs)}/5), trend_lock={trend_lock}"
    )

    # 2) Volatility multiplier (bigger size in calmer regimes)
    v = max(atr_pct / max(atr_pct_med, 1e-8), 1e-8)  # vol regime ratio
    vol_mult = (1.0 / v) ** 0.5  # sqrt(1 / v)
    vol_mult = max(0.7, min(vol_mult, 1.4))  # clamp [0.7, 1.4]

    # 3) Drawdown multiplier (de-risk when in DD)
    f_dd = 1.0 - 1.5 * drawdown
    f_dd = max(0.3, min(f_dd, 1.0))

    # 4) Confidence curve (aggressive near 95%+)
    c_eff = max(0.0, c_main - 0.60) / 0.40  # map [0.60, 1.0] -> [0,1]
    c_eff = max(0.0, min(c_eff, 1.0))
    f_conf = c_eff ** 1.5

    exposure_min = 0.01  # 1% of equity at low edge
    exposure_max = 0.20  # 20% at highest edge (before caps)

    exposure_conf = exposure_min + (exposure_max - exposure_min) * f_conf

    # 5) Timeframe & trainer performance multipliers (small nudges)
    tf_mult_map = {
        "5m": 0.8,
        "15m": 1.0,
        "1h": 1.1,
        "4h": 1.15,
        "1d": 1.2,
    }
    tf_mult = tf_mult_map.get(main_tf, 1.0)

    training_mult = 1.0 + 0.2 * perf_score
    training_mult = max(0.8, min(training_mult, 1.2))  # [0.8, 1.2]

    # 6) Combine multipliers
    target_exposure_pct = exposure_conf * vol_mult * f_dd * tf_mult * training_mult

    # 7) Confidence bucket caps (loosened to let dynamic sizing matter)
    if c_main >= 0.95 and trend_lock:
        bucket_cap = 0.20  # allow up to 20% only in true trend_lock
    elif c_main >= 0.85:
        bucket_cap = 0.12
    else:
        bucket_cap = 0.07

    target_exposure_pct = min(target_exposure_pct, bucket_cap)

    # 8) Core vs hedge split
    if trend_lock:
        core_pct = target_exposure_pct * 0.7  # 70% core position
        hedge_pct = target_exposure_pct * 0.3  # 30% reserved for hedge/TP
    else:
        # no strong multi-TF agreement -> balanced split
        core_pct = target_exposure_pct * 0.5
        hedge_pct = target_exposure_pct * 0.5

    # 9) Portfolio exposure cap is enforced at portfolio-level
    target_exposure_pct = min(target_exposure_pct, portfolio_exposure_cap)
    core_pct = min(core_pct, portfolio_exposure_cap)
    hedge_pct = min(hedge_pct, portfolio_exposure_cap)

    result = {
        "trend_lock": trend_lock,
        "core_pct": core_pct,
        "hedge_pct": hedge_pct,
        "target_exposure_pct": target_exposure_pct,
        "bucket_cap": bucket_cap,
        "strong_tfs": strong_tfs,
        "conf_main": c_main,
        "vol_mult": vol_mult,
        "dd_mult": f_dd,
        "conf_mult": f_conf,
    }

    logger.debug(
        f"Position sizing: target={target_exposure_pct:.1%}, "
        f"core={core_pct:.1%}, hedge={hedge_pct:.1%}, "
        f"bucket_cap={bucket_cap:.1%}, trend_lock={trend_lock}"
    )

    return result


def should_trade_on_timeframe(timeframe: str) -> bool:
    """
    Check if timeframe is allowed for trading decisions.
    
    Returns:
        True if timeframe can be used for trading
        False if timeframe is learning-only (1m)
    """
    return timeframe != LEARNING_TF and timeframe in ACTION_TFS


def get_multi_tf_consensus(
    conf_by_tf: Dict[str, float],
    required_agreement: int = 3,
    min_confidence: float = 0.80,
) -> Dict[str, Any]:
    """
    Check multi-TF consensus for trading decisions.
    
    Args:
        conf_by_tf: Confidence by timeframe
        required_agreement: Minimum number of TFs that must agree (default 3)
        min_confidence: Minimum confidence for a TF to "agree" (default 80%)
    
    Returns:
        {
            "has_consensus": bool,
            "strong_tfs": List[str],
            "confidence_avg": float,
            "direction": str (LONG/SHORT/NEUTRAL)
        }
    """
    # Filter to action TFs only (exclude 1m)
    action_tf_confs = {
        tf: conf for tf, conf in conf_by_tf.items()
        if tf in ACTION_TFS
    }
    
    if not action_tf_confs:
        return {
            "has_consensus": False,
            "strong_tfs": [],
            "confidence_avg": 0.0,
            "direction": "NEUTRAL"
        }
    
    # Count strong TFs (≥ min_confidence)
    strong_tfs = [
        tf for tf, conf in action_tf_confs.items()
        if conf >= min_confidence
    ]
    
    has_consensus = len(strong_tfs) >= required_agreement
    confidence_avg = sum(action_tf_confs.values()) / len(action_tf_confs)
    
    # Determine direction (assuming positive conf = LONG, negative = SHORT)
    # This would need to be adapted based on your actual encoding
    direction = "LONG" if confidence_avg > 0.5 else "SHORT" if confidence_avg < 0.5 else "NEUTRAL"
    
    return {
        "has_consensus": has_consensus,
        "strong_tfs": strong_tfs,
        "confidence_avg": confidence_avg,
        "direction": direction
    }


if __name__ == "__main__":
    # Test the position sizing function
    logging.basicConfig(level=logging.DEBUG)
    
    # Example: Strong bullish trend across multiple TFs
    conf_by_tf_trend = {
        "1m": 0.73,  # Learning only - ignored
        "5m": 0.92,
        "15m": 0.96,
        "1h": 0.94,
        "4h": 0.88,
    }
    
    result = compute_position_sizing(
        equity=10000,
        price=100,
        atr_price=2.0,
        atr_pct=0.02,
        atr_pct_med=0.018,
        conf_by_tf=conf_by_tf_trend,
        main_tf="15m",
        drawdown=0.0,
        perf_score=0.5,
    )
    
    print("\n=== TREND LOCK SCENARIO ===")
    print(f"Trend Lock: {result['trend_lock']}")
    print(f"Target Exposure: {result['target_exposure_pct']:.1%}")
    print(f"Core Position: {result['core_pct']:.1%}")
    print(f"Hedge Reserve: {result['hedge_pct']:.1%}")
    print(f"Strong TFs: {result['strong_tfs']}")
    
    # Example: Weak/mixed signals
    conf_by_tf_mixed = {
        "1m": 0.89,  # Learning only - ignored
        "5m": 0.72,
        "15m": 0.75,
        "1h": 0.68,
        "4h": 0.71,
    }
    
    result2 = compute_position_sizing(
        equity=10000,
        price=100,
        atr_price=2.0,
        atr_pct=0.02,
        atr_pct_med=0.018,
        conf_by_tf=conf_by_tf_mixed,
        main_tf="15m",
        drawdown=0.05,
        perf_score=0.0,
    )
    
    print("\n=== NO TREND LOCK SCENARIO ===")
    print(f"Trend Lock: {result2['trend_lock']}")
    print(f"Target Exposure: {result2['target_exposure_pct']:.1%}")
    print(f"Core Position: {result2['core_pct']:.1%}")
    print(f"Hedge Reserve: {result2['hedge_pct']:.1%}")
    print(f"Strong TFs: {result2['strong_tfs']}")
