"""Deterministic execution overlay scaffolding.

This module provides a minimal, opt-in overlay for profit locking and
loss-realization guarding. Defaults keep the overlay inert so existing
behavior is unchanged until explicitly enabled.
"""
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class ExecutionOverlay:
    """Overlay helper that can emit protective intents when enabled."""

    def __init__(self, config=None, redis_client=None, mode: str = "off", enable_protective_hedge: bool = False):
        self.config = config
        self.redis = redis_client
        self.mode = (mode or "off").lower()
        self.enable_protective_hedge = bool(enable_protective_hedge)

        # Static ladder thresholds (can be overridden by config/env later)
        self._ladder_thresholds = [1.0, 1.8, 2.8]  # percent
        self._runner_tighten_trigger = 3.5  # percent

    @property
    def active(self) -> bool:
        return self.mode in ("observe", "live")

    def _build_intent(self, intent_type: str, **kwargs) -> Dict[str, Any]:
        payload = {"type": intent_type}
        payload.update(kwargs)
        return payload

    def should_allow_loss_realization(self, position: Optional[Dict[str, Any]], reason_codes: Optional[List[str]] = None) -> bool:
        """Guard to block loss-taking unless explicit risk reasons apply."""
        if not self.active:
            return True
        pos = position or {}
        pnl = float(pos.get("unrealized_pnl_pct", 0.0) or 0.0)
        reasons = set((reason_codes or []))
        if pnl >= 0:
            return True
        if reasons & {"risk_exit", "stop_loss", "max_time", "fast_lane"}:
            return True
        return False

    def compute_overlay_actions(
        self,
        symbol: str,
        position: Optional[Dict[str, Any]],
        market_features: Optional[Dict[str, Any]] = None,
        intrabar_event: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Return overlay intents. In observe/off modes this is empty."""
        if not self.active:
            return []
        if not position or not position.get("size"):
            return []

        intents: List[Dict[str, Any]] = []
        pnl = float(position.get("unrealized_pnl_pct", 0.0) or 0.0)

        # Profit ladder (observe-only until mode set to live)
        for idx, threshold in enumerate(self._ladder_thresholds):
            if pnl >= threshold:
                intents.append(self._build_intent("PARTIAL_CLOSE", close_pct=0.25, rung=idx + 1))

        if pnl >= self._runner_tighten_trigger:
            intents.append(self._build_intent("TIGHTEN_TRAIL", trail_to=None, reason="runner_mode"))

        if self.enable_protective_hedge and pnl >= self._ladder_thresholds[0]:
            intents.append(self._build_intent("OPEN_PROTECTIVE_HEDGE", hedge_fraction=0.15))

        return intents if self.mode == "live" else []
