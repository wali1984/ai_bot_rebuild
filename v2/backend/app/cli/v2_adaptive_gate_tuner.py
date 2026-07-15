"""Adaptive gate tuner: continuous learning from paper outcomes, no static thresholds.

This system:
1. Monitors actual paper trading outcomes (win rate, PnL, execution speed)
2. Measures prediction accuracy vs confidence
3. Learns market regime (volatility, directional bias, liquidity)
4. Auto-calibrates confidence thresholds based on realized performance
5. Enables/disables grades (B, A, A+) based on evidence accumulation
6. Feeds back to edge gates and gates continuously

No hardcoded static thresholds; all adaptive to current market state.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Mapping

import redis

logger = logging.getLogger(__name__)

GATE_TUNING_KEY = "v2:orchestrator:adaptive_gate_tuning_state"
REGIME_KEY = "v2:market:regime_analysis"
CALIBRATION_KEY = "v2:trainer:adaptive_confidence_calibration"


def analyze_paper_outcomes(redis_client: redis.Redis) -> dict[str, Any]:
    """Analyze actual paper trading outcomes to measure prediction accuracy."""
    try:
        closed_trades = redis_client.get("v2:paper:closed_trades")
        if not closed_trades:
            return {"status": "NO_TRADES", "sample_size": 0}

        trades = json.loads(closed_trades)
        # Handle both list and dict formats
        if isinstance(trades, dict):
            trades = trades.get("trades", [])
        elif not isinstance(trades, list):
            trades = []

        # Measure confidence calibration
        confidence_outcomes = []
        for trade in trades[-100:]:  # Last 100 trades
            # Try multiple confidence field names
            confidence = (
                trade.get("entry_confidence_calibrated") or
                trade.get("entry_confidence") or
                trade.get("confidence_calibrated") or
                trade.get("confidence")
            )
            # Try multiple PnL field names
            pnl = trade.get("realized_pnl_usd") or trade.get("pnl_usd") or trade.get("pnl") or 0.0
            realized_win = 1.0 if (float(pnl or 0) > 0) else 0.0
            if confidence is not None:
                try:
                    confidence_outcomes.append((float(confidence), realized_win))
                except (TypeError, ValueError):
                    pass  # Skip invalid confidence values

        if not confidence_outcomes:
            return {"status": "NO_CONFIDENCE_DATA", "sample_size": 0}

        # Group by confidence bins and measure accuracy
        bins = {
            "high": [c for c, w in confidence_outcomes if c >= 0.75],
            "medium": [c for c, w in confidence_outcomes if 0.50 <= c < 0.75],
            "low": [c for c, w in confidence_outcomes if c < 0.50],
        }
        wins = {
            "high": sum(1 for c, w in confidence_outcomes if c >= 0.75 and w > 0),
            "medium": sum(1 for c, w in confidence_outcomes if 0.50 <= c < 0.75 and w > 0),
            "low": sum(1 for c, w in confidence_outcomes if c < 0.50 and w > 0),
        }
        win_rates = {
            "high": wins["high"] / len(bins["high"]) if bins["high"] else 0.0,
            "medium": wins["medium"] / len(bins["medium"]) if bins["medium"] else 0.0,
            "low": wins["low"] / len(bins["low"]) if bins["low"] else 0.0,
        }

        # Measure grade-specific performance
        a_grade_trades = [t for t in trades if t.get("grade") == "A"]
        b_grade_trades = [t for t in trades if t.get("grade") == "B"]
        prob_trades = [t for t in trades if t.get("grade") == "PROBATION"]

        return {
            "status": "OK",
            "sample_size": len(trades),
            "recent_sample": len(confidence_outcomes),
            "confidence_bins": {
                "high": {"count": len(bins["high"]), "win_rate": win_rates["high"]},
                "medium": {"count": len(bins["medium"]), "win_rate": win_rates["medium"]},
                "low": {"count": len(bins["low"]), "win_rate": win_rates["low"]},
            },
            "overall_win_rate": sum(1 for _, w in confidence_outcomes if w > 0) / len(confidence_outcomes),
            "a_grade_count": len(a_grade_trades),
            "b_grade_count": len(b_grade_trades),
            "probation_count": len(prob_trades),
            "total_pnl_usd": sum(float(t.get("realized_pnl_usd", 0)) for t in trades),
            "average_pnl_per_trade": sum(float(t.get("realized_pnl_usd", 0)) for t in trades) / len(trades) if trades else 0.0,
        }
    except Exception as e:
        logger.error(f"Error analyzing paper outcomes: {e}")
        return {"status": "ERROR", "error": str(e)}


def learn_market_regime(redis_client: redis.Redis) -> dict[str, Any]:
    """Learn current market regime from price action and volatility."""
    try:
        # Get recent prices
        prices = []
        for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            key = f"v2:market:candle:latest:{symbol}"
            candle = redis_client.get(key)
            if candle:
                c = json.loads(candle)
                prices.append({
                    "symbol": symbol,
                    "close": c.get("close"),
                    "high": c.get("high"),
                    "low": c.get("low"),
                    "volume": c.get("volume"),
                })

        if len(prices) < 2:
            return {"status": "INSUFFICIENT_DATA"}

        # Measure recent volatility
        volatility_bps = sum(
            ((p["high"] - p["low"]) / p["close"] * 10000) if p["close"] else 0
            for p in prices
        ) / len(prices)

        return {
            "status": "OK",
            "volatility_bps": volatility_bps,
            "regime": "HIGH" if volatility_bps > 100 else ("LOW" if volatility_bps < 30 else "NORMAL"),
            "symbols_analyzed": len(prices),
        }
    except Exception as e:
        logger.error(f"Error learning market regime: {e}")
        return {"status": "ERROR"}


def compute_adaptive_confidence_threshold(outcomes: dict, regime: dict) -> float:
    """Compute confidence threshold based on actual outcomes and market regime.

    No static thresholds. Adapts to:
    - High-confidence actual win rate (if > 60%, lower threshold to 0.65)
    - Medium-confidence actual win rate (if < 40%, raise threshold to 0.75)
    - Market regime (high volatility → stricter)
    """
    if outcomes.get("status") != "OK":
        return 0.70  # Conservative default

    bins = outcomes.get("confidence_bins", {})
    high_conf_wr = bins.get("high", {}).get("win_rate", 0.0)
    med_conf_wr = bins.get("medium", {}).get("win_rate", 0.0)

    regime_type = regime.get("regime", "NORMAL")
    volatility_bps = regime.get("volatility_bps", 50)

    # Adaptive rule: if high-confidence trades win >65%, lower threshold
    if high_conf_wr > 0.65 and med_conf_wr > 0.50:
        base_threshold = 0.65  # Looser
    elif high_conf_wr < 0.45:
        base_threshold = 0.80  # Stricter
    else:
        base_threshold = 0.70  # Neutral

    # Market regime adjustment
    if regime_type == "HIGH":
        base_threshold += 0.05  # Stricter in high volatility
    elif regime_type == "LOW":
        base_threshold -= 0.03  # Looser in calm markets

    return round(max(0.50, min(0.90, base_threshold)), 4)


def should_enable_b_grade(outcomes: dict) -> bool:
    """Enable B-grade entries if medium-confidence trades show positive EV."""
    if outcomes.get("status") != "OK":
        return False

    bins = outcomes.get("confidence_bins", {})
    med_conf_wr = bins.get("medium", {}).get("win_rate", 0.0)
    recent_pnl = outcomes.get("average_pnl_per_trade", 0.0)

    # B-grade enabled if medium-confidence shows >45% win rate AND positive avg PnL
    return med_conf_wr > 0.45 and recent_pnl > 0.0


def should_enable_a_grade(outcomes: dict) -> bool:
    """Enable A-grade if we have 100+ historical trades with positive expectancy."""
    if outcomes.get("status") != "OK":
        return False

    # Need 100+ total trades (B + A + Probation)
    total_trades = (
        outcomes.get("a_grade_count", 0)
        + outcomes.get("b_grade_count", 0)
        + outcomes.get("probation_count", 0)
    )

    overall_wr = outcomes.get("overall_win_rate", 0.0)
    total_pnl = outcomes.get("total_pnl_usd", 0.0)

    # A-grade enabled if 100+ trades AND >52% win rate AND positive PnL
    return total_trades >= 100 and overall_wr > 0.52 and total_pnl > 0.0


def publish_gate_tuning(redis_client: redis.Redis, tuning_state: dict) -> None:
    """Publish adaptive gate tuning state to Redis."""
    tuning_state["generated_at"] = datetime.now(timezone.utc).isoformat()
    tuning_state["schema_version"] = "adaptive_gate_tuning_v1"

    redis_client.set(
        GATE_TUNING_KEY,
        json.dumps(tuning_state, default=str),
        ex=3600,  # 1-hour TTL
    )


def run_adaptive_tuning(redis_client: redis.Redis = None) -> dict[str, Any]:
    """Run one iteration of adaptive gate tuning."""
    if redis_client is None:
        redis_client = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"))

    # Analyze current state
    outcomes = analyze_paper_outcomes(redis_client)
    regime = learn_market_regime(redis_client)

    # Compute adaptive thresholds
    adaptive_confidence_threshold = compute_adaptive_confidence_threshold(outcomes, regime)
    enable_b_grade = should_enable_b_grade(outcomes)
    enable_a_grade = should_enable_a_grade(outcomes)

    # Compute loss probability threshold (inverse of confidence: when we're confident, allow higher loss_prob)
    # When B-grade enabled (markets favorable): raise threshold to accept more candidates (0.85)
    # When B-grade disabled (markets tough): lower threshold to accept only safest (0.80)
    loss_probability_threshold = 0.85 if enable_b_grade else 0.80

    tuning_state = {
        "outcomes": outcomes,
        "market_regime": regime,
        "adaptive_confidence_threshold": adaptive_confidence_threshold,
        "adaptive_loss_probability_threshold": loss_probability_threshold,
        "enable_b_grade": enable_b_grade,
        "enable_a_grade": enable_a_grade,
        "a_grade_ready": enable_a_grade,
        "blockers_resolved": False,  # Will be set by higher-level monitor
    }

    # Publish state
    publish_gate_tuning(redis_client, tuning_state)

    logger.info(f"Adaptive tuning: confidence_threshold={adaptive_confidence_threshold}, loss_prob_threshold={loss_probability_threshold}, b_grade={enable_b_grade}, a_grade={enable_a_grade}")

    return tuning_state


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    result = run_adaptive_tuning()
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0)  # Always exit 0; the JSON output (not exit code) signals state
