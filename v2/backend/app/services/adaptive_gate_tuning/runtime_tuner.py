"""Adaptive gate tuning based on market conditions, ingestor health, and trainer performance."""

import json
import logging
import os
from typing import Any, Mapping

import redis

logger = logging.getLogger(__name__)

V2_REDIS_PREFIX = os.environ.get("V2_REDIS_PREFIX", "v2:")
GATE_TUNING_KEY = f"{V2_REDIS_PREFIX}orchestrator:adaptive_gate_tuning_state"


def _get_market_volatility_factor(r: redis.Redis) -> float:
    """Read market volatility from regime publishers. Returns 0.5-2.0 multiplier."""
    try:
        regime = r.get(f"{V2_REDIS_PREFIX}context:market_regime_current")
        if regime:
            regime = json.loads(regime)
            volatility = float(regime.get("volatility_percentile", 0.5))
            # High volatility = relax gates (more candidates), low volatility = tighten (fewer false signals)
            return 0.5 + volatility  # 0.5 + [0-1] = [0.5-1.5]
    except Exception as e:
        logger.debug(f"Failed to read market volatility: {e}")
    return 1.0


def _get_ingestor_health_factor(r: redis.Redis) -> float:
    """Read data freshness from all ingestors. Returns 0.5-1.5 multiplier."""
    try:
        ingestors_status = r.get(f"{V2_REDIS_PREFIX}ingestors:status")
        if ingestors_status:
            status = json.loads(ingestors_status)
            healthy_count = status.get("healthy_count", 0)
            total_count = status.get("total_count", 1)
            health_ratio = max(0, healthy_count / total_count)
            # More healthy ingestors = tighter gates (trust the data)
            # Fewer healthy ingestors = relax gates (data quality uncertain)
            return 0.5 + (health_ratio * 1.0)  # [0.5-1.5]
    except Exception as e:
        logger.debug(f"Failed to read ingestor health: {e}")
    return 1.0


def _get_trainer_performance_factor(r: redis.Redis) -> float:
    """Read trainer metrics (win_rate, profit_factor, confidence). Returns 0.5-2.0 multiplier."""
    try:
        trainer_metrics = r.get(f"{V2_REDIS_PREFIX}trainer:hybrid_cuda:metrics")
        if trainer_metrics:
            metrics = json.loads(trainer_metrics)
            win_rate = float(metrics.get("win_rate_percent", 50)) / 100.0  # 0-1
            profit_factor = float(metrics.get("profit_factor", 1.0))
            confidence = float(metrics.get("avg_prediction_confidence", 0.5))  # 0-1

            # Combine: high performance = relax gates (trust model)
            # Low performance = tighten gates (be cautious)
            combined = (win_rate * 0.4) + (min(profit_factor / 2.0, 1.0) * 0.3) + (confidence * 0.3)
            # [0-1] range, scale to [0.5-1.5]
            return 0.5 + (combined * 1.0)
    except Exception as e:
        logger.debug(f"Failed to read trainer performance: {e}")
    return 1.0


def _get_closed_trades_factor(r: redis.Redis) -> float:
    """Read portfolio performance from closed trades. Returns 0.5-2.0 multiplier."""
    try:
        paper_session = r.get(f"{V2_REDIS_PREFIX}paper:session")
        if paper_session:
            session = json.loads(paper_session)
            pnl = float(session.get("net_pnl_usd", 0))
            starting_equity = float(session.get("starting_equity_usd", 1000))
            profit_pct = (pnl / starting_equity) if starting_equity > 0 else 0

            # Positive profit = relax (system is working), negative = tighten (be careful)
            # Scale: -50% loss to +50% gain
            factor = 1.0 + (profit_pct / 0.5)  # maps [-1 to 1] to [0-2]
            return max(0.5, min(2.0, factor))
    except Exception as e:
        logger.debug(f"Failed to read portfolio performance: {e}")
    return 1.0


def compute_adaptive_gate_tuning(r: redis.Redis) -> dict[str, Any]:
    """Compute adaptive gate thresholds based on all market conditions and performance."""
    volatility_factor = _get_market_volatility_factor(r)
    ingestor_factor = _get_ingestor_health_factor(r)
    trainer_factor = _get_trainer_performance_factor(r)
    portfolio_factor = _get_closed_trades_factor(r)

    # Composite adaptive multiplier
    composite = (volatility_factor * 0.25) + (ingestor_factor * 0.25) + (trainer_factor * 0.3) + (portfolio_factor * 0.2)
    composite = max(0.5, min(2.0, composite))

    # Base thresholds (from original hardcoded values)
    base_exit_feasibility = 0.20  # paper mode
    base_confidence_risk = 0.90  # paper mode
    base_loss_probability = 0.72  # PAPER_RISK_CONTROLLER_EXPLORATION
    base_min_confidence = 0.30  # allocator paper mode
    base_min_market_state = 30  # allocator paper mode
    base_max_spread_ratio = 2.0  # allocator paper mode

    # Adaptive thresholds: multiply by composite factor
    # Higher factor = relax thresholds (accept more)
    # Lower factor = tighten thresholds (accept fewer)
    tuning_state = {
        "schema_version": "adaptive_gate_tuning_v2",
        "adaptive_exit_feasibility_threshold": base_exit_feasibility / composite,
        "adaptive_confidence_risk_threshold": base_confidence_risk / composite,
        "adaptive_loss_probability_threshold": min(1.0, base_loss_probability / composite),
        "adaptive_min_confidence": max(0.1, base_min_confidence / composite),
        "adaptive_min_market_state": max(10, int(base_min_market_state / composite)),
        "adaptive_max_spread_slippage_ratio": base_max_spread_ratio * composite,
        "adaptive_leverage_multiplier": composite,

        # Diagnostic: show what's driving the adaptation
        "volatility_factor": volatility_factor,
        "ingestor_health_factor": ingestor_factor,
        "trainer_performance_factor": trainer_factor,
        "portfolio_performance_factor": portfolio_factor,
        "composite_adaptive_multiplier": composite,

        # Flags for each condition
        "market_volatile": volatility_factor > 1.2,
        "ingestors_degraded": ingestor_factor < 0.8,
        "trainer_underperforming": trainer_factor < 0.7,
        "portfolio_negative": portfolio_factor < 0.8,

        "generated_utc": os.popen("date -u +%Y-%m-%dT%H:%M:%SZ").read().strip(),
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }

    return tuning_state


def publish_adaptive_gate_tuning(r: redis.Redis) -> None:
    """Compute and publish adaptive gate tuning state to Redis."""
    try:
        tuning_state = compute_adaptive_gate_tuning(r)
        r.set(GATE_TUNING_KEY, json.dumps(tuning_state, default=str), ex=60)
        logger.info(f"Published adaptive gate tuning: composite={tuning_state.get('composite_adaptive_multiplier', 1.0):.2f}")
    except Exception as e:
        logger.error(f"Failed to publish adaptive gate tuning: {e}")


def get_adaptive_threshold(r: redis.Redis, threshold_name: str, default: float) -> float:
    """Get adaptive threshold from tuning state, fall back to default."""
    try:
        tuning_json = r.get(GATE_TUNING_KEY)
        if tuning_json:
            tuning = json.loads(tuning_json)
            threshold = tuning.get(threshold_name)
            if threshold is not None:
                return float(threshold)
    except Exception as e:
        logger.debug(f"Failed to read {threshold_name}: {e}")
    return default
