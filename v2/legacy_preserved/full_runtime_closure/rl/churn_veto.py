"""
Churn Veto (Option 3)
====================

This is a lightweight learned veto designed to reduce fee-bleed and adverse selection on 1m timing entries.

How it works:
- Offline trainer script (`rl/scripts/train_churn_veto.py`) builds a dataset from Redis history
  and trains a tiny logistic model (no external deps).
- Trainer loads weights from JSON and computes P(churn_bad | state).
- High churn probability forces WAIT_REPRICE or PASSIVE_MAKER.

This does NOT guarantee winners. It prevents the system from repeatedly entering states that historically
lead to rapid churn/hedge escalation/fee drag.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)
CHURN_VETO_LOG_VERBOSE = os.getenv("CHURN_VETO_LOG_VERBOSE", "true").lower() in ("1", "true", "yes")


@dataclass
class ChurnVetoDecision:
    p_bad: Optional[float]
    action: str  # ALLOW | MAKER_ONLY | VETO
    reason: str


def _f(x, default=0.0) -> float:
    try:
        if x is None:
            return float(default)
        return float(x)
    except Exception:
        return float(default)


def _clamp01(x: float) -> float:
    try:
        if x != x:
            return 0.0
        return max(0.0, min(1.0, float(x)))
    except Exception:
        return 0.0


class ChurnVetoModel:
    """
    Linear logistic model: p = sigmoid(w·x + b)
    Features are deliberately small and stable:
      - confidence
      - toxicity
      - spread_norm
      - fast_move_score
      - churn_score
      - snapback_score
      - entropy (optional)
    """

    def __init__(self, model_path: str):
        self.model_path = str(model_path or "")
        self.w = None  # dict feature->weight
        self.b = 0.0
        self.meta = {}
        self._load()

    def _load(self) -> None:
        if not self.model_path:
            return
        try:
            if not os.path.exists(self.model_path):
                return
            with open(self.model_path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            self.w = obj.get("weights") or None
            self.b = float(obj.get("bias") or 0.0)
            self.meta = obj.get("meta") or {}
        except Exception:
            # If loading fails, operate in heuristic-only mode.
            self.w = None
            self.b = 0.0
            self.meta = {}

    def predict_p_bad(self, x: Dict[str, float]) -> Optional[float]:
        if not isinstance(self.w, dict) or not self.w:
            return None
        z = float(self.b)
        for k, w in self.w.items():
            z += float(w) * float(x.get(k, 0.0) or 0.0)
        # sigmoid
        try:
            import math

            p = 1.0 / (1.0 + math.exp(-z))
            return _clamp01(p)
        except Exception:
            return None

    def decide(
        self,
        *,
        confidence: float,
        toxicity: float,
        micro: Optional[Dict] = None,
        spread_bps: Optional[float] = None,
        entropy: Optional[float] = None,
        maker_only_prob: float = 0.45,
        block_prob: float = 0.65,
    ) -> ChurnVetoDecision:
        micro = micro or {}

        conf = _clamp01(_f(confidence, 0.0) if _f(confidence, 0.0) <= 1.0 else _f(confidence, 0.0) / 100.0)
        tox = _clamp01(_f(toxicity, 0.0))
        spread = _f(spread_bps, _f(micro.get("spread_bps", micro.get("spread", 0.0)), 0.0))
        spread_norm = _clamp01(float(spread) / 20.0) if spread > 0 else 0.0

        feat = {
            "confidence": conf,
            "toxicity": tox,
            "spread_norm": spread_norm,
            "fast_move": _clamp01(_f(micro.get("fast_move_score"), 0.0)),
            "churn": _clamp01(_f(micro.get("churn_score"), 0.0)),
            "snapback": _clamp01(_f(micro.get("snapback_score"), 0.0)),
            "entropy": _clamp01(_f(entropy, _f(micro.get("entropy"), 0.0))),
        }

        p_bad = self.predict_p_bad(feat)
        if p_bad is None:
            # Heuristic fallback: very toxic + wide spread + low confidence => maker-only / veto
            if tox >= 0.80 and conf < 0.88:
                result = ChurnVetoDecision(p_bad=None, action="VETO", reason=f"heuristic veto tox={tox:.2f} conf={conf:.2f}")
                if CHURN_VETO_LOG_VERBOSE:
                    logger.info(f"🔄 [CHURN_VETO] VETO (heuristic) | tox={tox:.2f} conf={conf:.2f}")
                return result
            if tox >= 0.55 or spread_norm >= 0.55:
                result = ChurnVetoDecision(p_bad=None, action="MAKER_ONLY", reason=f"heuristic maker tox={tox:.2f} spread_n={spread_norm:.2f}")
                if CHURN_VETO_LOG_VERBOSE:
                    logger.info(f"🔄 [CHURN_VETO] MAKER_ONLY (heuristic) | tox={tox:.2f} spread_n={spread_norm:.2f}")
                return result
            return ChurnVetoDecision(p_bad=None, action="ALLOW", reason="no_model_allow")

        if p_bad >= float(block_prob):
            result = ChurnVetoDecision(p_bad=p_bad, action="VETO", reason=f"p_bad={p_bad:.2f}>=block")
            if CHURN_VETO_LOG_VERBOSE:
                logger.info(f"🔄 [CHURN_VETO] VETO | p_bad={p_bad:.2f} >= {block_prob:.2f}")
            return result
        if p_bad >= float(maker_only_prob):
            result = ChurnVetoDecision(p_bad=p_bad, action="MAKER_ONLY", reason=f"p_bad={p_bad:.2f}>=maker")
            if CHURN_VETO_LOG_VERBOSE:
                logger.info(f"🔄 [CHURN_VETO] MAKER_ONLY | p_bad={p_bad:.2f} >= {maker_only_prob:.2f}")
            return result
        return ChurnVetoDecision(p_bad=p_bad, action="ALLOW", reason=f"p_bad={p_bad:.2f}")

