from __future__ import annotations

from typing import Any, Dict


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


class ScenarioEngine:
    """
    Bounded scenario influence.

    Returns:
    - scenario_top_action
    - scenario_utility
    - scenario_liq_prob
    - logit_delta (clamped)
    """

    def __init__(self, alpha: float = 0.0, clamp: float = 0.25):
        self.alpha = float(max(0.0, min(1.0, alpha)))
        self.clamp = float(max(0.01, clamp))

    def evaluate(self, symbol: str, tf: str, features: Dict[str, Any], base_logit: float) -> Dict[str, Any]:
        depth_spread = _f(features.get("depth_spread"))
        depth_quality = _f(features.get("depth_quality_score"), 1.0)
        spoof = max(_f(features.get("depth_spoof_score")), _f(features.get("p_false_move")))
        liq_long = _f(features.get("liquidation_long_strength"))
        liq_short = _f(features.get("liquidation_short_strength"))
        liq_vol = _f(features.get("liquidation_volume"))
        basis = _f(features.get("basis_pct"))
        funding = _f(features.get("funding_rate"))

        liq_pressure = (liq_short - liq_long)
        liq_prob = max(0.0, min(1.0, 0.5 + 0.15 * abs(liq_pressure) + 0.0001 * max(0.0, liq_vol)))

        # EV-style utility proxy: penalize spoof and poor quality, reward directional liquidation/futures alignment
        scenario_utility = (
            0.45 * liq_pressure
            + 0.20 * basis
            + 0.10 * funding
            - 0.25 * spoof
            - 0.05 * max(0.0, depth_spread)
            + 0.10 * (depth_quality - 1.0)
        )

        raw_delta = self.alpha * scenario_utility
        if raw_delta > self.clamp:
            logit_delta = self.clamp
        elif raw_delta < -self.clamp:
            logit_delta = -self.clamp
        else:
            logit_delta = raw_delta

        adjusted = base_logit + logit_delta
        if adjusted > 0.15:
            top_action = "LONG"
        elif adjusted < -0.15:
            top_action = "SHORT"
        else:
            top_action = "HOLD"

        return {
            "symbol": symbol,
            "tf": tf,
            "scenario_top_action": top_action,
            "scenario_utility": float(scenario_utility),
            "scenario_liq_prob": float(liq_prob),
            "logit_delta": float(logit_delta),
        }
