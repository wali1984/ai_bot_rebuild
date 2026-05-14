"""
Intent Engine (Option 2 core)
============================

Purpose:
- Compute a per-symbol INTENT from higher timeframes (e.g. 5m/15m/1h) driven by PPO/MASA.
- Intent defines direction and strength. It does NOT execute trades directly by default.
- 1m can only act as a timing layer aligned with intent (handled elsewhere).

Design notes:
- No static cooldowns/holds. Intent decays naturally when agreement/entropy worsens.
- Deterministic regime prior is optional and used as a *confidence prior + veto*, not as a direction dictator.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)
INTENT_LOG_VERBOSE = os.getenv("INTENT_LOG_VERBOSE", "true").lower() in ("1", "true", "yes")


@dataclass
class Intent:
    symbol: str
    direction: str  # LONG|SHORT|NONE
    strength: float  # 0..1
    effective_conf: float  # 0..1
    agreement: float  # 0..1 (PPO/MASA + TF consensus)
    reason: str


def _clamp01(x: float) -> float:
    try:
        if x != x:  # NaN
            return 0.0
        return max(0.0, min(1.0, float(x)))
    except Exception:
        return 0.0


class IntentEngine:
    def __init__(
        self,
        *,
        intent_timeframes: List[str],
        min_agreement: float,
        min_effective_conf: float,
        enable_regime_prior: bool = True,
    ):
        self.intent_timeframes = [str(x) for x in (intent_timeframes or [])]
        self.min_agreement = float(min_agreement or 0.0)
        self.min_effective_conf = float(min_effective_conf or 0.0)
        self.enable_regime_prior = bool(enable_regime_prior)

    def compute_intent(
        self,
        *,
        symbol: str,
        tf_predictions: Dict[str, Dict],
        regime: Optional[Dict] = None,
    ) -> Intent:
        """
        tf_predictions: timeframe -> prediction dict with (best-effort):
          - direction: 'LONG'|'SHORT' (or action_name)
          - confidence: 0..1
          - entropy: 0..1 (optional)
          - ppo_confidence / masa_confidence (optional)
        regime: optional deterministic prior:
          - trend_dir: 'LONG'|'SHORT'|'NEUTRAL'
          - trend_strength: 0..1
          - veto_dir: optional dir to veto (e.g., 'LONG' when strong downtrend)
        """
        # Aggregate votes across intent_timeframes
        votes_long = 0.0
        votes_short = 0.0
        confs: List[float] = []
        entropies: List[float] = []
        details: List[str] = []

        for tf in self.intent_timeframes:
            p = (tf_predictions or {}).get(tf) or {}
            a = str(p.get("action_name") or p.get("action") or p.get("direction") or "").upper()
            conf = p.get("confidence", p.get("model_confidence", 0.0))
            try:
                conf_f = float(conf or 0.0)
            except Exception:
                conf_f = 0.0
            if conf_f > 1.0:
                conf_f = conf_f / 100.0
            conf_f = _clamp01(conf_f)

            # Direction extraction
            if "LONG" in a or a == "OPEN_LONG":
                votes_long += conf_f
                details.append(f"{tf}:LONG@{conf_f:.2f}")
            elif "SHORT" in a or a == "OPEN_SHORT":
                votes_short += conf_f
                details.append(f"{tf}:SHORT@{conf_f:.2f}")
            else:
                details.append(f"{tf}:HOLD@{conf_f:.2f}")

            confs.append(conf_f)
            try:
                ent = float(p.get("entropy", 0.0) or 0.0)
            except Exception:
                ent = 0.0
            entropies.append(_clamp01(ent))

        total = votes_long + votes_short
        if total <= 1e-9:
            return Intent(symbol=symbol, direction="NONE", strength=0.0, effective_conf=0.0, agreement=0.0, reason="no_votes")

        agreement = abs(votes_long - votes_short) / max(total, 1e-9)  # 0..1
        base_dir = "LONG" if votes_long > votes_short else "SHORT"
        base_strength = _clamp01(agreement)
        base_conf = _clamp01(sum(confs) / max(1, len(confs)))
        ent_avg = _clamp01(sum(entropies) / max(1, len(entropies)))

        # Regime prior (optional): continuous confidence shaping + veto
        vetoed = False
        conf_effective = base_conf * (1.0 - 0.25 * ent_avg)  # penalize high entropy
        regime_note = ""
        if self.enable_regime_prior and isinstance(regime, dict):
            trend_dir = str(regime.get("trend_dir") or "NEUTRAL").upper()
            try:
                trend_strength = _clamp01(float(regime.get("trend_strength") or 0.0))
            except Exception:
                trend_strength = 0.0

            # Confidence prior: boost if aligned with trend, damp if against.
            if trend_dir in ("LONG", "SHORT") and trend_strength > 0:
                aligned = (trend_dir == base_dir)
                factor = (0.85 + 0.30 * trend_strength) if aligned else (0.85 - 0.35 * trend_strength)
                conf_effective = _clamp01(conf_effective * factor)
                regime_note = f"regime:{trend_dir}@{trend_strength:.2f}:{'aligned' if aligned else 'against'}"

            veto_dir = str(regime.get("veto_dir") or "").upper()
            if veto_dir in ("LONG", "SHORT") and veto_dir == base_dir and trend_strength >= 0.75:
                vetoed = True
                regime_note = (regime_note + "|veto").strip("|")

        # Soft gating: below thresholds -> intent NONE (but logged via reason)
        if vetoed:
            return Intent(symbol=symbol, direction="NONE", strength=0.0, effective_conf=conf_effective, agreement=agreement, reason=f"veto:{regime_note}")

        if agreement < float(self.min_agreement) or conf_effective < float(self.min_effective_conf):
            why = f"weak_intent agreement={agreement:.2f} conf_eff={conf_effective:.2f} ({'|'.join(details)})"
            if regime_note:
                why += f" | {regime_note}"
            return Intent(symbol=symbol, direction="NONE", strength=base_strength, effective_conf=conf_effective, agreement=agreement, reason=why)

        why = f"intent={base_dir} agreement={agreement:.2f} conf_eff={conf_effective:.2f} ({'|'.join(details)})"
        if regime_note:
            why += f" | {regime_note}"

        result = Intent(symbol=symbol, direction=base_dir, strength=base_strength, effective_conf=conf_effective, agreement=agreement, reason=why)
        if INTENT_LOG_VERBOSE and base_dir != "NONE":
            logger.info(f"🧭 [INTENT] {symbol} | dir={base_dir} | strength={base_strength:.2f} | conf_eff={conf_effective:.2f} | agree={agreement:.2f}")
        return result

