from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import sqrt
from typing import Any, Dict, List, Tuple


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


@dataclass
class _RollingWindow:
    window: int

    def __post_init__(self):
        self.q: deque = deque(maxlen=self.window)
        self.sum: float = 0.0
        self.sumsq: float = 0.0

    def update(self, x: float) -> None:
        if len(self.q) == self.q.maxlen:
            old = self.q[0]
            self.sum -= old
            self.sumsq -= old * old
        self.q.append(x)
        self.sum += x
        self.sumsq += x * x

    def mean_std(self) -> Tuple[float, float]:
        n = len(self.q)
        if n < 2:
            return (0.0, 1.0)
        mean = self.sum / n
        var = max((self.sumsq / n) - (mean * mean), 1e-8)
        return (mean, sqrt(var))


class MoveShockEngine:
    """
    Diagnostic-only move shock engine.
    Computes intensity, direction, type, and top contributors from unified features.
    """

    FEATURE_FAMILIES = {
        "microstructure": lambda k: k.startswith("depth_") or k.startswith("ob_"),
        "spoof_churn": lambda k: ("spoof" in k) or ("churn" in k) or (k == "p_false_move"),
        "fast_move": lambda k: "fast_move" in k,
        "liquidations": lambda k: k.startswith("liquidation_"),
        "futures": lambda k: k in {"funding_rate", "basis_pct", "mark_price", "index_price"},
    }

    FAMILY_ALPHA = {
        "microstructure": 0.28,
        "spoof_churn": 0.18,
        "fast_move": 0.24,
        "liquidations": 0.20,
        "futures": 0.10,
    }

    DIRECTION_KEYS = {
        "depth_imbalance_5": 1.0,
        "ob_ob_imbalance": 1.0,
        "depth_microprice_minus_mid": 1.2,
        "liquidation_asymmetry": 1.4,
        "basis_pct": 0.5,
    }

    def __init__(self, window: int = 120, z_cap: float = 6.0):
        self.window = int(max(20, window))
        self.z_cap = float(max(1.0, z_cap))
        self._stats: Dict[Tuple[str, str, str], _RollingWindow] = {}

    def _family_for_key(self, key: str) -> str | None:
        for name, matcher in self.FEATURE_FAMILIES.items():
            if matcher(key):
                return name
        return None

    def _get_derived_features(self, features: Dict[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        micro = _safe_float(features.get("depth_microprice"))
        mid = _safe_float(features.get("depth_mid_price"))
        if mid != 0.0:
            out["depth_microprice_minus_mid"] = (micro - mid) / abs(mid)

        ls = _safe_float(features.get("liquidation_short_strength"))
        ll = _safe_float(features.get("liquidation_long_strength"))
        denom = abs(ls) + abs(ll) + 1e-9
        out["liquidation_asymmetry"] = (ls - ll) / denom
        return out

    def _rolling_z(self, symbol: str, tf: str, key: str, value: float) -> float:
        stat_key = (symbol, tf, key)
        bucket = self._stats.get(stat_key)
        if bucket is None:
            bucket = _RollingWindow(window=self.window)
            self._stats[stat_key] = bucket

        mean, std = bucket.mean_std()
        z = (value - mean) / (std + 1e-8)
        z = _clamp(z, -self.z_cap, self.z_cap)
        bucket.update(value)
        return z

    def _get_spoof_probability(self, features: Dict[str, Any]) -> float:
        vals = [
            _safe_float(features.get("depth_spoof_score"), 0.0),
            _safe_float(features.get("spoof_score"), 0.0),
            _safe_float(features.get("p_false_move"), 0.0),
        ]
        vals = [_clamp(v, 0.0, 1.0) for v in vals if v is not None]
        if not vals:
            return 0.0
        return float(max(vals))

    def _classify_type(
        self,
        family_scores: Dict[str, float],
        spoof_prob: float,
        top_key: str,
    ) -> str:
        micro = family_scores.get("microstructure", 0.0)
        spoof = family_scores.get("spoof_churn", 0.0)
        liq = family_scores.get("liquidations", 0.0)
        fast = family_scores.get("fast_move", 0.0)
        if spoof_prob >= 0.65 and (spoof >= 0.25 or "imbalance" in top_key or "depth_" in top_key):
            return "SPOOF_FALSE_MOVE"
        if liq >= 1.2 and ("liquidation" in top_key or liq >= micro):
            return "LIQUIDATION_CASCADE"
        if micro >= 1.2 and fast < 1.0:
            return "LIQUIDITY_VACUUM"
        if fast >= 1.0:
            return "MOMENTUM_BREAK"
        return "NORMAL"

    def evaluate(self, symbol: str, tf: str, unified_features: Dict[str, Any]) -> Dict[str, Any]:
        features = dict(unified_features or {})
        features.update(self._get_derived_features(features))

        spoof_prob = self._get_spoof_probability(features)
        downweight = 1.0 - 0.7 * _clamp(spoof_prob, 0.0, 1.0)

        contributions: List[Dict[str, Any]] = []
        family_accum: Dict[str, float] = {
            "microstructure": 0.0,
            "spoof_churn": 0.0,
            "fast_move": 0.0,
            "liquidations": 0.0,
            "futures": 0.0,
        }
        direction_signal = 0.0

        for key, raw_val in features.items():
            val = _safe_float(raw_val, default=float("nan"))
            if val != val:  # NaN guard
                continue

            family = self._family_for_key(key)
            if family is None and key not in self.DIRECTION_KEYS:
                continue

            z = self._rolling_z(symbol, tf, key, val)
            abs_z = abs(z)

            weight = 1.0
            if family == "microstructure" and ("imbalance" in key or "depth_" in key):
                weight *= downweight

            if family is not None:
                family_accum[family] += weight * abs_z

            if key in self.DIRECTION_KEYS:
                direction_signal += self.DIRECTION_KEYS[key] * z * weight

            contributions.append({
                "feature": key,
                "z": float(z),
                "abs_z": float(abs_z),
                "value": float(val),
                "family": family or "derived",
            })

        family_scores = {
            fam: self.FAMILY_ALPHA[fam] * score for fam, score in family_accum.items()
        }
        move_intensity = float(sum(family_scores.values()))
        move_intensity = _clamp(move_intensity, 0.0, 10.0)

        if direction_signal > 0.35:
            move_direction = "UP"
        elif direction_signal < -0.35:
            move_direction = "DOWN"
        else:
            move_direction = "NEUTRAL"

        top_sorted = sorted(contributions, key=lambda x: x["abs_z"], reverse=True)
        top5 = top_sorted[:5]
        top_key = top5[0]["feature"] if top5 else ""
        move_type = self._classify_type(family_scores, spoof_prob, top_key)

        return {
            "move_intensity": float(move_intensity),
            "move_direction": move_direction,
            "move_type": move_type,
            "top_contributors": top5,
            "spoof_probability": float(_clamp(spoof_prob, 0.0, 1.0)),
            "direction_signal": float(_clamp(direction_signal, -10.0, 10.0)),
            "family_scores": {k: float(v) for k, v in family_scores.items()},
        }
