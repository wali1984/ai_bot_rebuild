from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

# Import canonical action classification to stay aligned with ontology
try:
    from rl.action_ontology import get_action_category
except ImportError:
    get_action_category = None

EXIT_TOKENS = ("CLOSE", "PARTIAL_CLOSE", "REDUCE", "DECREASE", "STOP_LOSS", "TAKE_PROFIT", "EXIT")
ENTRY_TOKENS = ("OPEN", "LONG", "SHORT", "INCREASE")


@dataclass
class LifecycleDecision:
    final_action: str
    size_multiplier: float
    reason_codes: List[str]


class TradeLifecycleController:
    """
    Deterministic lifecycle controller.

    Non-breaking design:
    - Always computes lifecycle decision + reasons.
    - Enforcement can be toggled by caller (`enforce=False` keeps action unchanged).
    """

    def decide(
        self,
        *,
        macro_bias: float,
        entry_score: float,
        exit_score: float,
        current_position_state: Dict[str, Any] | None,
        margin_state: Dict[str, Any] | None,
        ppo_logit: float,
        masa_logit: float,
        requested_action: str,
        enforce: bool = False,
        trainer_confidence: float = 0.0,
    ) -> LifecycleDecision:
        action = str(requested_action or "HOLD").upper()
        reasons: List[str] = []

        has_position = bool(current_position_state)
        pos_side = str((current_position_state or {}).get("side") or "").upper()
        margin_util = float((margin_state or {}).get("margin_util") or 0.0)

        is_exit = any(tok in action for tok in EXIT_TOKENS)
        is_entry = any(tok in action for tok in ENTRY_TOKENS) and not is_exit

        reasons.append(f"MACRO_BIAS_{'UP' if macro_bias > 0 else 'DOWN' if macro_bias < 0 else 'NEUTRAL'}")
        reasons.append(f"ENTRY_SCORE_{entry_score:.3f}")
        reasons.append(f"EXIT_SCORE_{exit_score:.3f}")
        reasons.append(f"MARGIN_UTIL_{margin_util:.3f}")
        reasons.append(f"MODEL_BLEND_PPO_{ppo_logit:.3f}_MASA_{masa_logit:.3f}")
        reasons.append(f"TRAINER_CONF_{trainer_confidence:.3f}")

        size_multiplier = 1.0
        final_action = action

        # HIGH-CONFIDENCE TRAINER PROTECTION:
        # If the trainer has high confidence (>=0.90) in this action, do NOT override it.
        # The lifecycle controller should only intervene on LOW-confidence signals.
        trainer_high_conf = trainer_confidence >= 0.90

        # Exit logic precedence (if enabled): prefer reducing risk when exit dominates and a position exists
        if has_position and exit_score >= (entry_score + 0.15):
            reasons.append("EXIT_PRIORITY")
            if enforce and is_entry and not trainer_high_conf:
                if pos_side == "LONG":
                    final_action = "PARTIAL_CLOSE_LONG"
                elif pos_side == "SHORT":
                    final_action = "PARTIAL_CLOSE_SHORT"
                else:
                    final_action = "HOLD"
                size_multiplier = 0.5
                reasons.append("ENTRY_OVERRIDDEN_BY_EXIT")
            elif enforce and is_entry and trainer_high_conf:
                reasons.append("EXIT_PRIORITY_DEFERRED_TRAINER_HIGH_CONF")

        # Macro contradiction handling (only if enforcement is enabled AND trainer not high-conf)
        if enforce and is_entry and not trainer_high_conf:
            if macro_bias < -0.20 and "LONG" in action:
                final_action = "HOLD"
                reasons.append("MACRO_CONTRA_LONG_BLOCK")
            elif macro_bias > 0.20 and "SHORT" in action:
                final_action = "HOLD"
                reasons.append("MACRO_CONTRA_SHORT_BLOCK")
        elif enforce and is_entry and trainer_high_conf:
            if macro_bias < -0.20 and "LONG" in action:
                reasons.append("MACRO_CONTRA_LONG_DEFERRED_TRAINER_HIGH_CONF")
            elif macro_bias > 0.20 and "SHORT" in action:
                reasons.append("MACRO_CONTRA_SHORT_DEFERRED_TRAINER_HIGH_CONF")

        return LifecycleDecision(
            final_action=final_action,
            size_multiplier=float(max(0.1, min(1.0, size_multiplier))),
            reason_codes=reasons,
        )
