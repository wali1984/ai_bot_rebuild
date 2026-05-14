"""
risk/risk_state_machine.py — 3-State Risk State Machine with Breach Persistence.

Prevents the survival layer (governor + deleverager) from dominating normal operation.
Enforcement is **stateful and edge-aware**, not snapshot-reactive.

Three states:
  NORMAL      — governor blocks insane adds; deleverager OFF; swings allowed
  STRESSED    — block new risk-adds; do NOT force-close; allow existing swings
  EMERGENCY   — deleverager ON after breach_streak >= N; closes even at loss

Transitions require *persistence*, not single-snapshot breaches:
  - NORMAL → STRESSED  when MU > stress_high or acct_im > stress_im_high
  - STRESSED → EMERGENCY  when breach_streak >= N  (N consecutive checks above emergency_high)
  - EMERGENCY → STRESSED  when MU < emergency_low AND breach_streak resets
  - STRESSED → NORMAL  when MU < stress_low (hysteresis band)

Breach streak is stored in Redis so restarts don't reset it (preventing
the pattern where "restart → immediate fire → cut at loss → repeat").

Edge feed:
  Reads ``regime:{symbol}`` from Redis (computed by risk/market_regime.py).
  When edge is known (tf_alignment direction), deleverager preserves main leg
  and reduces hedge leg first. When no edge → PAIR_REDUCE proportionally.

Kill-switch: config.RISK_STATE_MACHINE_ENABLED (default: True)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    import config
except ImportError:
    config = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# ─── helpers ────────────────────────────────────────────────────────────────

def _cfg(key: str, default):
    if config is not None:
        val = getattr(config, key, None)
        if val is not None:
            return val
    return default


def _sf(v, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        out = float(v)
        return default if out != out else out
    except Exception:
        return default


# ─── enums & data classes ───────────────────────────────────────────────────

class RiskState(str, Enum):
    NORMAL = "NORMAL"
    STRESSED = "STRESSED"
    EMERGENCY = "EMERGENCY"


@dataclass
class RiskStateSnapshot:
    """Full snapshot of current risk state with diagnostics."""
    state: RiskState
    previous_state: RiskState
    mu_pct: float
    acct_im_pct: float
    equity: float
    total_im: float
    breach_streak: int
    breach_streak_required: int
    transition: Optional[str]       # e.g. "NORMAL→STRESSED" or None
    deleverage_allowed: bool
    add_risk_allowed: bool
    timestamp: float
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EdgeSignal:
    """Market edge for a symbol — determines data-driven unwind decisions."""
    symbol: str
    direction: str                  # "LONG", "SHORT", or "NEUTRAL"
    confidence: float               # 0..1 — strength of edge
    tf_alignment: float             # -1..1 from regime (signed strength)
    move_regime: str                # CALM/NORMAL/FAST/IMPULSE
    regime_source: str              # "redis" or "default"
    timestamp: float


# ─── breach streak tracker (Redis-persisted) ───────────────────────────────

class BreachStreakTracker:
    """
    Tracks consecutive breach checks in Redis.
    Restarts don't reset the streak — this is the key difference from
    the in-memory cadence gate that resets on every process restart.
    """

    REDIS_PREFIX = "risk:breach_streak"

    def __init__(self, redis_client=None):
        self.redis = redis_client

    def get_streak(self, account_id: str) -> int:
        """Get current breach streak count from Redis."""
        if not self.redis:
            return 0
        try:
            key = f"{self.REDIS_PREFIX}:{account_id}"
            raw = self.redis.get(key)
            if raw is None:
                return 0
            val = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
            data = json.loads(val)
            return int(data.get("streak", 0))
        except Exception:
            return 0

    def get_full_state(self, account_id: str) -> Dict[str, Any]:
        """Get full breach state from Redis."""
        if not self.redis:
            return {"streak": 0, "last_breach_ts": 0.0, "last_clear_ts": 0.0,
                    "last_mu_pct": 0.0, "last_im_pct": 0.0}
        try:
            key = f"{self.REDIS_PREFIX}:{account_id}"
            raw = self.redis.get(key)
            if raw is None:
                return {"streak": 0, "last_breach_ts": 0.0, "last_clear_ts": 0.0,
                        "last_mu_pct": 0.0, "last_im_pct": 0.0}
            val = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
            return json.loads(val)
        except Exception:
            return {"streak": 0, "last_breach_ts": 0.0, "last_clear_ts": 0.0,
                    "last_mu_pct": 0.0, "last_im_pct": 0.0}

    def increment(self, account_id: str, mu_pct: float, im_pct: float) -> int:
        """Increment breach streak. Returns new count."""
        if not self.redis:
            return 1
        try:
            key = f"{self.REDIS_PREFIX}:{account_id}"
            now = time.time()
            state = self.get_full_state(account_id)
            new_streak = state.get("streak", 0) + 1
            state.update({
                "streak": new_streak,
                "last_breach_ts": now,
                "last_mu_pct": round(mu_pct, 2),
                "last_im_pct": round(im_pct, 2),
            })
            # TTL 10 minutes — stale breach data auto-expires
            self.redis.setex(key, 600, json.dumps(state))
            return new_streak
        except Exception as e:
            logger.debug("BREACH_STREAK_INCREMENT_ERR | %s", e)
            return 1

    def reset(self, account_id: str, reason: str = "") -> None:
        """Reset streak to 0 (metrics fell below low-water mark)."""
        if not self.redis:
            return
        try:
            key = f"{self.REDIS_PREFIX}:{account_id}"
            state = {
                "streak": 0,
                "last_clear_ts": time.time(),
                "last_clear_reason": reason,
                "last_mu_pct": 0.0,
                "last_im_pct": 0.0,
            }
            self.redis.setex(key, 600, json.dumps(state))
        except Exception:
            pass


# ─── edge feed reader ──────────────────────────────────────────────────────

class EdgeFeed:
    """
    Reads market regime from Redis to provide directional edge per symbol.
    This makes unwind decisions data-driven instead of metric-driven.
    """

    # Minimum tf_alignment magnitude to consider as "having edge"
    EDGE_MIN_ALIGNMENT = 0.25

    def __init__(self, redis_client=None):
        self.redis = redis_client

    def get_edge(self, symbol: str) -> EdgeSignal:
        """
        Read regime:{symbol} from Redis and extract directional edge.

        Returns EdgeSignal with direction LONG/SHORT/NEUTRAL.
        Falls back to NEUTRAL if no regime data available.
        """
        default = EdgeSignal(
            symbol=symbol,
            direction="NEUTRAL",
            confidence=0.0,
            tf_alignment=0.0,
            move_regime="UNKNOWN",
            regime_source="default",
            timestamp=time.time(),
        )

        if not self.redis:
            return default

        try:
            raw = self.redis.get(f"regime:{symbol}")
            if not raw:
                return default

            val = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
            regime = json.loads(val)

            tf_alignment = _sf(regime.get("tf_alignment"), 0.0)
            confidence = abs(tf_alignment)
            move_regime = str(regime.get("move_regime", "UNKNOWN")).upper()

            min_align = float(_cfg("RISK_EDGE_MIN_ALIGNMENT", self.EDGE_MIN_ALIGNMENT))

            if confidence >= min_align:
                direction = "LONG" if tf_alignment > 0 else "SHORT"
            else:
                direction = "NEUTRAL"

            return EdgeSignal(
                symbol=symbol,
                direction=direction,
                confidence=round(confidence, 4),
                tf_alignment=round(tf_alignment, 4),
                move_regime=move_regime,
                regime_source="redis",
                timestamp=time.time(),
            )
        except Exception as e:
            logger.debug("EDGE_FEED_ERR | symbol=%s | %s", symbol, e)
            return default


# ─── risk state machine ────────────────────────────────────────────────────

class RiskStateMachine:
    """
    3-state risk state machine with breach persistence and hysteresis.

    Key behavior:
      - Does NOT fire deleverage on single-snapshot breach
      - Requires N consecutive breach checks (breach_streak) before EMERGENCY
      - Uses hysteresis (separate high/low thresholds) to prevent oscillation
      - State persisted in Redis for restart resilience
      - Edge feed makes unwind decisions data-driven

    Usage:
        rsm = RiskStateMachine(redis_client)
        snap = rsm.evaluate(account_id, mu_pct=52.0, acct_im_pct=0.48, equity=750.0)
        if snap.deleverage_allowed:
            # proceed with deleverage
        if not snap.add_risk_allowed:
            # block new risk-adds
    """

    REDIS_KEY_PREFIX = "risk:state"

    def __init__(self, redis_client=None):
        self.redis = redis_client
        self._breach_tracker = BreachStreakTracker(redis_client)
        self._edge_feed = EdgeFeed(redis_client)
        self._last_state: RiskState = RiskState.NORMAL
        self._last_transition_ts: float = 0.0
        self._last_log_ts: float = 0.0

        # Hydrate last state from Redis
        self._hydrate_state()

    def _hydrate_state(self):
        """Load last state from Redis on startup."""
        if not self.redis:
            return
        try:
            raw = self.redis.get(f"{self.REDIS_KEY_PREFIX}:current")
            if raw:
                val = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
                data = json.loads(val)
                state_str = data.get("state", "NORMAL").upper()
                if state_str in ("NORMAL", "STRESSED", "EMERGENCY"):
                    self._last_state = RiskState(state_str)
                    self._last_transition_ts = _sf(data.get("transition_ts"), 0.0)
                    logger.info(
                        "RISK_STATE_HYDRATE | state=%s | age=%.0fs",
                        self._last_state.value,
                        time.time() - self._last_transition_ts if self._last_transition_ts > 0 else 0,
                    )
        except Exception as e:
            logger.debug("RISK_STATE_HYDRATE_ERR | %s", e)

    def _persist_state(self, state: RiskState, snap: RiskStateSnapshot):
        """Persist current state to Redis."""
        if not self.redis:
            return
        try:
            data = {
                "state": state.value,
                "transition_ts": time.time(),
                "mu_pct": round(snap.mu_pct, 2),
                "acct_im_pct": round(snap.acct_im_pct, 4),
                "breach_streak": snap.breach_streak,
                "equity": round(snap.equity, 2),
            }
            # TTL 10 minutes — if process dies, state expires and recomputes
            self.redis.setex(f"{self.REDIS_KEY_PREFIX}:current", 600, json.dumps(data))
        except Exception:
            pass

    def evaluate(
        self,
        account_id: str,
        mu_pct: float,
        acct_im_pct: float,
        equity: float = 0.0,
        total_im: float = 0.0,
    ) -> RiskStateSnapshot:
        """
        Evaluate current account metrics and return risk state.

        This is the ONLY function that determines whether deleverage is allowed.
        Called every cycle by the deleverage loop.
        """
        enabled = bool(_cfg("RISK_STATE_MACHINE_ENABLED", True))
        if not enabled:
            # Disabled: do not arm deleverage via RSM (legacy "always EMERGENCY" caused
            # GOV_DELEVERAGE_MODE=state_machine to bypass hard thresholds → fee bleed).
            # AutoDeleverager skips RSM entirely when disabled; this path is for direct callers.
            return RiskStateSnapshot(
                state=RiskState.NORMAL,
                previous_state=self._last_state,
                mu_pct=mu_pct,
                acct_im_pct=acct_im_pct,
                equity=equity,
                total_im=total_im,
                breach_streak=0,
                breach_streak_required=999,
                transition=None,
                deleverage_allowed=False,
                add_risk_allowed=True,
                timestamp=time.time(),
                meta={"reason": "state_machine_disabled_no_rsm_deleverage"},
            )

        # ── Thresholds with hysteresis ────────────────────────────────────
        # STRESSED triggers (high-water marks)
        stress_mu_high = float(_cfg("RISK_STRESS_MU_HIGH", 48.0))
        stress_im_high = float(_cfg("RISK_STRESS_IM_HIGH", 0.43))

        # NORMAL recovery (low-water marks — hysteresis band)
        stress_mu_low = float(_cfg("RISK_STRESS_MU_LOW", 40.0))
        stress_im_low = float(_cfg("RISK_STRESS_IM_LOW", 0.35))

        # EMERGENCY triggers (high-water marks)
        emergency_mu_high = float(_cfg("RISK_EMERGENCY_MU_HIGH", 52.0))
        emergency_im_high = float(_cfg("RISK_EMERGENCY_IM_HIGH", 0.48))

        # EMERGENCY recovery (low-water marks)
        emergency_mu_low = float(_cfg("RISK_EMERGENCY_MU_LOW", 44.0))
        emergency_im_low = float(_cfg("RISK_EMERGENCY_IM_LOW", 0.40))

        # Breach streak N required for EMERGENCY activation
        streak_required = int(_cfg("RISK_BREACH_STREAK_REQUIRED", 3))

        previous_state = self._last_state

        # ── Classify current metrics ────────────────────────────────────
        in_emergency_zone = (mu_pct > emergency_mu_high) or (acct_im_pct > emergency_im_high)
        in_stress_zone = (mu_pct > stress_mu_high) or (acct_im_pct > stress_im_high)
        below_stress_low = (mu_pct < stress_mu_low) and (acct_im_pct < stress_im_low)
        below_emergency_low = (mu_pct < emergency_mu_low) and (acct_im_pct < emergency_im_low)

        # ── Update breach streak ────────────────────────────────────────
        if in_emergency_zone:
            streak = self._breach_tracker.increment(account_id, mu_pct, acct_im_pct)
        elif below_emergency_low:
            self._breach_tracker.reset(account_id, reason="below_emergency_low")
            streak = 0
        else:
            streak = self._breach_tracker.get_streak(account_id)

        # ── State transitions ───────────────────────────────────────────
        new_state = previous_state
        transition = None

        if previous_state == RiskState.NORMAL:
            if in_stress_zone:
                new_state = RiskState.STRESSED
                transition = "NORMAL→STRESSED"

        elif previous_state == RiskState.STRESSED:
            if in_emergency_zone and streak >= streak_required:
                new_state = RiskState.EMERGENCY
                transition = "STRESSED→EMERGENCY"
            elif below_stress_low:
                new_state = RiskState.NORMAL
                transition = "STRESSED→NORMAL"

        elif previous_state == RiskState.EMERGENCY:
            if below_emergency_low:
                new_state = RiskState.STRESSED
                transition = "EMERGENCY→STRESSED"
            # Stay in EMERGENCY if still in zone (even if streak would reset,
            # we don't drop straight to NORMAL from EMERGENCY)

        # ── Compute allowed actions ─────────────────────────────────────
        deleverage_allowed = (new_state == RiskState.EMERGENCY)
        add_risk_allowed = (new_state == RiskState.NORMAL)

        snap = RiskStateSnapshot(
            state=new_state,
            previous_state=previous_state,
            mu_pct=round(mu_pct, 2),
            acct_im_pct=round(acct_im_pct, 4),
            equity=round(equity, 2),
            total_im=round(total_im, 2),
            breach_streak=streak,
            breach_streak_required=streak_required,
            transition=transition,
            deleverage_allowed=deleverage_allowed,
            add_risk_allowed=add_risk_allowed,
            timestamp=time.time(),
            meta={
                "in_emergency_zone": in_emergency_zone,
                "in_stress_zone": in_stress_zone,
                "below_stress_low": below_stress_low,
                "below_emergency_low": below_emergency_low,
                "streak_required": streak_required,
            },
        )

        # ── Persist + log transitions ───────────────────────────────────
        if transition:
            self._last_state = new_state
            self._last_transition_ts = time.time()
            self._persist_state(new_state, snap)
            logger.warning(
                "RISK_STATE_TRANSITION | %s | mu=%.1f%% | im=%.1f%% | "
                "streak=%d/%d | equity=$%.2f",
                transition, mu_pct, acct_im_pct * 100,
                streak, streak_required, equity,
            )
        else:
            # Periodic heartbeat log (every 5 minutes, not every cycle)
            now = time.time()
            if now - self._last_log_ts > 300:
                self._last_log_ts = now
                logger.info(
                    "RISK_STATE_HEARTBEAT | state=%s | mu=%.1f%% | im=%.1f%% | "
                    "streak=%d/%d | deleverage=%s | add_risk=%s",
                    new_state.value, mu_pct, acct_im_pct * 100,
                    streak, streak_required,
                    deleverage_allowed, add_risk_allowed,
                )
            # Still update Redis state periodically for monitoring
            self._persist_state(new_state, snap)

        return snap

    def get_edge(self, symbol: str) -> EdgeSignal:
        """Get directional edge for a symbol from regime data."""
        return self._edge_feed.get_edge(symbol)

    def get_current_state(self) -> RiskState:
        """Return last evaluated state."""
        return self._last_state

    @property
    def breach_tracker(self) -> BreachStreakTracker:
        return self._breach_tracker

    @property
    def edge_feed(self) -> EdgeFeed:
        return self._edge_feed
