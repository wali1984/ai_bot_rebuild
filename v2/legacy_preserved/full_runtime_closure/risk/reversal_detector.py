"""
risk/reversal_detector.py — Global Reversal Detection Layer.

Fires a "global reversal warning" when multiple indicators flip within a short
window, enabling the system to de-risk, tighten stops, and require stricter
alignment for new entries.

Reversal trigger fires when **any 2+** of these occur within the detection window:

  1. breadth_strength drops sharply (e.g. 0.75 → 0.45)
  2. breadth_entropy spikes (dispersion increases)
  3. breadth_dir flips sign
  4. liq_imbalance flips and strengthens
  5. liquidation flow flips (long liqs dominate after long trend)
  6. fast_move_score spikes during an existing directional regime

On reversal detection:
  - Open positions: tighten risk_mult, add hedges, upgrade to DEFENSIVE
  - New signals: require stricter tf_alignment, enforce hedge-first on alts
  - Widen cadence (slow new opens)
  - State persists until breadth restabilizes (entropy drops, breadth firms up)

Feature-flagged via config.REVERSAL_DETECTOR_ENABLED (default: False).

Redis output key: ``reversal:global`` with TTL.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

try:
    import config
except ImportError:
    config = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ── Defaults ─────────────────────────────────────────────────────────
_REVERSAL_WINDOW_SEC = 120         # Time window to count trigger hits
_REVERSAL_MIN_TRIGGERS = 2        # Min trigger hits to fire reversal
_REVERSAL_BREADTH_DROP = 0.25     # breadth_strength drop threshold
_REVERSAL_ENTROPY_SPIKE = 0.25    # breadth_entropy increase threshold
_REVERSAL_LIQ_IMBAL_FLIP = 0.50   # liq_imbalance swing threshold
_REVERSAL_FAST_MOVE_SPIKE = 0.60  # fast_move_score threshold
_REVERSAL_COOLDOWN_SEC = 180      # Min time between reversal fires
_REVERSAL_RECOVERY_ENTROPY_MAX = 0.55  # Entropy must drop below this to clear
_REVERSAL_RECOVERY_STRENGTH_MIN = 0.30  # Breadth must firm above this to clear
_REVERSAL_CACHE_TTL_SEC = 300
_REVERSAL_MAX_DURATION_SEC = 600       # Absolute timeout: clear after 10 min regardless


def _cfg(key: str, default):
    if config is not None:
        full_key = f"REVERSAL_{key}"
        val = getattr(config, full_key, None)
        if val is not None:
            return val
    return default


class ReversalState:
    """Tracks reversal trigger conditions over a rolling window."""

    def __init__(self):
        self.active: bool = False
        self.fire_ts: float = 0.0             # When reversal was fired
        self.trigger_count: int = 0            # How many triggers hit
        self.triggers: List[str] = []          # Which triggers fired
        self.prev_breadth_dir: int = 0
        self.prev_breadth_strength: float = 0.0
        self.prev_breadth_entropy: float = 1.0
        self.prev_liq_imbal: float = 0.0
        self.prev_fast_move: float = 0.0
        self.prev_update_ts: float = 0.0
        self.consecutive_clear_ticks: int = 0  # How many cycles clear conditions met

    def to_dict(self) -> Dict[str, Any]:
        return {
            "active": self.active,
            "fire_ts": self.fire_ts,
            "trigger_count": self.trigger_count,
            "triggers": self.triggers,
            "prev_breadth_dir": self.prev_breadth_dir,
            "prev_breadth_strength": self.prev_breadth_strength,
            "prev_breadth_entropy": self.prev_breadth_entropy,
            "prev_liq_imbal": self.prev_liq_imbal,
            "consecutive_clear_ticks": self.consecutive_clear_ticks,
            "updated_ts_ms": int(time.time() * 1000),
        }


def evaluate_reversal(
    state: ReversalState,
    breadth: Dict[str, Any],
    *,
    liq_flow_flipped: bool = False,
    now: Optional[float] = None,
) -> ReversalState:
    """Evaluate whether a global reversal warning should fire or clear.

    Parameters
    ----------
    state : ReversalState
        Previous state (mutated in-place and returned).
    breadth : dict
        Output of ``risk.global_breadth.compute_global_breadth()``.
    liq_flow_flipped : bool
        True if liquidation flow has flipped direction (external signal).
    now : float, optional
        Current time (default: time.time()).

    Returns
    -------
    ReversalState (same object, mutated).
    """
    if now is None:
        now = time.time()

    b_dir = int(breadth.get("breadth_dir") or 0)
    b_strength = float(breadth.get("breadth_strength") or 0.0)
    b_entropy = float(breadth.get("breadth_entropy") or 1.0)
    b_fast = float(breadth.get("breadth_fast_move") or 0.0)
    b_liq_imbal = float(breadth.get("breadth_liq_imbal") or 0.0)

    window_sec = float(_cfg("WINDOW_SEC", _REVERSAL_WINDOW_SEC))
    min_triggers = int(_cfg("MIN_TRIGGERS", _REVERSAL_MIN_TRIGGERS))
    cooldown_sec = float(_cfg("COOLDOWN_SEC", _REVERSAL_COOLDOWN_SEC))

    # ── If already active, check for recovery ─────────────────────────
    if state.active:
        max_duration = float(_cfg("MAX_DURATION_SEC", _REVERSAL_MAX_DURATION_SEC))
        if (now - state.fire_ts) >= max_duration:
            logger.info(
                "[REVERSAL_EXPIRE] Auto-cleared after %.0fs (max_duration=%.0f)",
                now - state.fire_ts, max_duration,
            )
            state.active = False
            state.trigger_count = 0
            state.triggers = []
            state.consecutive_clear_ticks = 0
            _update_prev(state, b_dir, b_strength, b_entropy, b_liq_imbal, b_fast, now)
            return state

        recovery_entropy_max = float(_cfg("RECOVERY_ENTROPY_MAX", _REVERSAL_RECOVERY_ENTROPY_MAX))
        recovery_strength_min = float(_cfg("RECOVERY_STRENGTH_MIN", _REVERSAL_RECOVERY_STRENGTH_MIN))

        clear = (
            b_entropy <= recovery_entropy_max
            and b_strength >= recovery_strength_min
        )
        if clear:
            state.consecutive_clear_ticks += 1
            if state.consecutive_clear_ticks >= 3:
                logger.info(
                    "[REVERSAL_CLEAR] breadth_strength=%.3f entropy=%.3f clear_ticks=%d",
                    b_strength, b_entropy, state.consecutive_clear_ticks,
                )
                state.active = False
                state.trigger_count = 0
                state.triggers = []
                state.consecutive_clear_ticks = 0
        else:
            state.consecutive_clear_ticks = 0

        # Update prev values
        state.prev_breadth_dir = b_dir
        state.prev_breadth_strength = b_strength
        state.prev_breadth_entropy = b_entropy
        state.prev_liq_imbal = b_liq_imbal
        state.prev_fast_move = b_fast
        state.prev_update_ts = now
        return state

    # ── Not active: check for new reversal triggers ───────────────────

    # Cooldown check
    if (now - state.fire_ts) < cooldown_sec:
        _update_prev(state, b_dir, b_strength, b_entropy, b_liq_imbal, b_fast, now)
        return state

    # Only evaluate if we have previous data
    if state.prev_update_ts <= 0:
        _update_prev(state, b_dir, b_strength, b_entropy, b_liq_imbal, b_fast, now)
        return state

    # Check time window
    dt = now - state.prev_update_ts
    if dt > window_sec:
        # Too old — just update prev
        _update_prev(state, b_dir, b_strength, b_entropy, b_liq_imbal, b_fast, now)
        return state

    triggers: List[str] = []

    # Trigger 1: breadth_strength drops sharply
    drop_thresh = float(_cfg("BREADTH_DROP", _REVERSAL_BREADTH_DROP))
    if state.prev_breadth_strength - b_strength >= drop_thresh:
        triggers.append(f"BREADTH_DROP:{state.prev_breadth_strength:.2f}→{b_strength:.2f}")

    # Trigger 2: breadth_entropy spikes
    spike_thresh = float(_cfg("ENTROPY_SPIKE", _REVERSAL_ENTROPY_SPIKE))
    if b_entropy - state.prev_breadth_entropy >= spike_thresh:
        triggers.append(f"ENTROPY_SPIKE:{state.prev_breadth_entropy:.2f}→{b_entropy:.2f}")

    # Trigger 3: breadth_dir flips sign
    if (
        state.prev_breadth_dir != 0
        and b_dir != 0
        and state.prev_breadth_dir != b_dir
    ):
        triggers.append(f"DIR_FLIP:{state.prev_breadth_dir}→{b_dir}")

    # Trigger 4: liq_imbalance flips and strengthens
    liq_flip_thresh = float(_cfg("LIQ_IMBAL_FLIP", _REVERSAL_LIQ_IMBAL_FLIP))
    if state.prev_liq_imbal != 0 and b_liq_imbal != 0:
        # Signs differ AND new value is strong
        if (
            (state.prev_liq_imbal > 0) != (b_liq_imbal > 0)
            and abs(b_liq_imbal) >= liq_flip_thresh
        ):
            triggers.append(f"LIQ_IMBAL_FLIP:{state.prev_liq_imbal:.2f}→{b_liq_imbal:.2f}")

    # Trigger 5: liquidation flow flip (external)
    if liq_flow_flipped:
        triggers.append("LIQ_FLOW_FLIP")

    # Trigger 6: fast_move_score spikes during directional regime
    fms_thresh = float(_cfg("FAST_MOVE_SPIKE", _REVERSAL_FAST_MOVE_SPIKE))
    if b_fast >= fms_thresh and state.prev_breadth_dir != 0:
        triggers.append(f"FAST_MOVE_SPIKE:{b_fast:.2f}")

    # ── Fire reversal if enough triggers ──────────────────────────────
    if len(triggers) >= min_triggers:
        state.active = True
        state.fire_ts = now
        state.trigger_count = len(triggers)
        state.triggers = triggers
        state.consecutive_clear_ticks = 0
        logger.warning(
            "[REVERSAL_FIRE] triggers=%d details=%s breadth_str=%.3f entropy=%.3f dir=%d",
            len(triggers), triggers, b_strength, b_entropy, b_dir,
        )

    _update_prev(state, b_dir, b_strength, b_entropy, b_liq_imbal, b_fast, now)
    return state


def _update_prev(
    state: ReversalState,
    b_dir: int,
    b_strength: float,
    b_entropy: float,
    b_liq_imbal: float,
    b_fast: float,
    now: float,
) -> None:
    state.prev_breadth_dir = b_dir
    state.prev_breadth_strength = b_strength
    state.prev_breadth_entropy = b_entropy
    state.prev_liq_imbal = b_liq_imbal
    state.prev_fast_move = b_fast
    state.prev_update_ts = now


# ── Redis cache ──────────────────────────────────────────────────────

def cache_reversal_state(
    redis_client,
    state: ReversalState,
    ttl_sec: int = 0,
) -> bool:
    """Write reversal state to Redis."""
    if not redis_client:
        return False
    if ttl_sec <= 0:
        ttl_sec = int(_cfg("CACHE_TTL_SEC", _REVERSAL_CACHE_TTL_SEC))
    try:
        redis_client.setex(
            "reversal:global",
            max(10, ttl_sec),
            json.dumps(state.to_dict(), separators=(",", ":")),
        )
        return True
    except Exception:
        return False


def read_cached_reversal(redis_client) -> Optional[Dict[str, Any]]:
    """Read cached reversal state from Redis. Returns None if missing."""
    if not redis_client:
        return None
    try:
        raw = redis_client.get("reversal:global")
        if not raw:
            return None
        val = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
        data = json.loads(val)
        return data if isinstance(data, dict) else None
    except Exception:
        return None
