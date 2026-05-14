"""
risk/trainer_intent.py — Trainer Intent Publisher & Reader.

PURPOSE:
  The trainer publishes its directional intent (what direction it believes
  the market is going) into Redis every prediction cycle.  Autonomous closers
  in the trader (PER_LEG_ROI_KILL, proactive soft reduce, auto-deleverager)
  read this intent BEFORE closing positions.

  If a position is ALIGNED with the trainer's high-confidence intent,
  the autonomous closer must use elevated thresholds and/or streak persistence
  before firing — preventing premature closes that liquidated the portfolio.

Redis Keys:
  trainer:intent:{symbol}  — Hash with fields:
    direction   : "LONG" | "SHORT" | "NEUTRAL"
    confidence  : 0.0-1.0  (model's raw confidence)
    action      : raw action string (e.g. "OPEN_SHORT", "HOLD")
    timeframe   : primary timeframe that generated the signal
    ts_ms       : timestamp milliseconds when intent was published
    producer    : "trainer"

  TTL: 300 seconds (5 minutes). If trainer hasn't published in 5 min,
  intent is stale → autonomous closers revert to normal thresholds.

Kill-switch:  config.TRAINER_INTENT_ENABLED  (default: True)

Usage (Trainer side):
    from risk.trainer_intent import publish_intent
    publish_intent(redis, symbol="BTCUSDT", direction="SHORT",
                   confidence=0.92, action="OPEN_SHORT", timeframe="1h")

Usage (Trader/Risk side):
    from risk.trainer_intent import get_intent, position_aligns_with_intent
    intent = get_intent(redis, "BTCUSDT")
    if intent and position_aligns_with_intent(intent, position_side="SHORT"):
        # Position aligns with trainer — use elevated thresholds
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

_INTENT_KEY_PREFIX = "trainer:intent"
_INTENT_TTL_SEC = 300  # 5 minutes
_MIN_CONFIDENCE_FOR_DEFERENCE = 0.70  # Below this, autonomous closers ignore intent


# ── Config Helpers ──────────────────────────────────────────────────────────

def _cfg(name: str, default):
    """Safe config lookup — never crashes."""
    try:
        import config
        return getattr(config, name, default)
    except Exception:
        return default


# ── Data Classes ────────────────────────────────────────────────────────────

@dataclass
class TrainerIntent:
    """Snapshot of the trainer's current directional intent for a symbol."""
    symbol: str
    direction: str          # "LONG", "SHORT", "NEUTRAL"
    confidence: float       # 0.0-1.0
    action: str             # Raw action string
    timeframe: str          # Timeframe that generated the intent
    ts_ms: int              # When intent was published
    producer: str = "trainer"

    @property
    def age_seconds(self) -> float:
        """How old this intent is (seconds)."""
        return max(0.0, (time.time() * 1000 - self.ts_ms) / 1000.0)

    @property
    def is_stale(self) -> bool:
        """True if intent is older than TTL."""
        return self.age_seconds > float(_cfg("TRAINER_INTENT_TTL_SEC", _INTENT_TTL_SEC))

    @property
    def is_high_confidence(self) -> bool:
        """True if confidence exceeds deference threshold."""
        min_conf = float(_cfg("TRAINER_INTENT_MIN_CONFIDENCE", _MIN_CONFIDENCE_FOR_DEFERENCE))
        return self.confidence >= min_conf

    @property
    def is_directional(self) -> bool:
        """True if intent is LONG or SHORT (not NEUTRAL/HOLD)."""
        return self.direction in ("LONG", "SHORT")

    def aligns_with_position(self, position_side: str) -> bool:
        """
        True if this intent supports keeping the given position open.

        SHORT intent → SHORT position is aligned
        LONG intent  → LONG position is aligned
        NEUTRAL      → no alignment
        """
        if not self.is_directional:
            return False
        return self.direction == position_side.upper()


# ── Publisher (Trainer-side) ────────────────────────────────────────────────

def publish_intent(
    redis_client,
    symbol: str,
    direction: str,
    confidence: float,
    action: str = "",
    timeframe: str = "",
    producer: str = "trainer",
) -> bool:
    """
    Publish trainer's directional intent for a symbol to Redis.

    Called by the trainer every prediction cycle, BEFORE signal publication.

    Args:
        redis_client: Redis connection
        symbol:       Trading symbol (e.g., "BTCUSDT")
        direction:    "LONG", "SHORT", or "NEUTRAL"
        confidence:   Model confidence 0.0-1.0
        action:       Raw action string for debugging
        timeframe:    Source timeframe
        producer:     Always "trainer"

    Returns:
        True if published successfully, False otherwise.
    """
    try:
        enabled = bool(_cfg("TRAINER_INTENT_ENABLED", True))
        if not enabled or not redis_client:
            return False

        ttl = int(_cfg("TRAINER_INTENT_TTL_SEC", _INTENT_TTL_SEC))
        key = f"{_INTENT_KEY_PREFIX}:{symbol}"
        ts_ms = int(time.time() * 1000)

        direction = direction.upper().strip()
        if direction not in ("LONG", "SHORT", "NEUTRAL"):
            direction = "NEUTRAL"

        mapping = {
            "direction": direction,
            "confidence": str(round(confidence, 4)),
            "action": str(action),
            "timeframe": str(timeframe),
            "ts_ms": str(ts_ms),
            "producer": producer,
        }

        redis_client.hset(key, mapping=mapping)
        redis_client.expire(key, ttl)

        logger.debug(
            "TRAINER_INTENT_PUB | symbol=%s | direction=%s | conf=%.3f | "
            "action=%s | tf=%s | ttl=%ds",
            symbol, direction, confidence, action, timeframe, ttl,
        )
        return True

    except Exception as e:
        logger.debug("TRAINER_INTENT_PUB_ERR | symbol=%s | %s", symbol, e)
        return False


def infer_direction_from_action(action: str) -> str:
    """
    Infer directional intent from an action string.

    LONG signals:  OPEN_LONG, CLOSE_AND_LONG, INCREASE_LONG, ADD_LONG
    SHORT signals: OPEN_SHORT, CLOSE_AND_SHORT, INCREASE_SHORT, ADD_SHORT
    NEUTRAL:       HOLD, CLOSE_*, DECREASE_*, PARTIAL_CLOSE_*

    Note: Pure closes (CLOSE_LONG, CLOSE_SHORT) are NEUTRAL — they don't
    indicate a directional view, just an exit.
    """
    a = str(action or "").upper().strip()

    # Flips and opens carry strong directional intent
    if "CLOSE_AND_LONG" in a or "FLIP_TO_LONG" in a or "CLOSE_SHORT_OPEN_LONG" in a or "CLOSE_SHORT_AND_OPEN_LONG" in a:
        return "LONG"
    if "CLOSE_AND_SHORT" in a or "FLIP_TO_SHORT" in a or "CLOSE_LONG_OPEN_SHORT" in a or "CLOSE_LONG_AND_OPEN_SHORT" in a:
        return "SHORT"

    # Explicit opens
    if "OPEN_LONG" in a or "ENTER_LONG" in a:
        return "LONG"
    if "OPEN_SHORT" in a or "ENTER_SHORT" in a:
        return "SHORT"

    # Increases/adds maintain direction
    if "INCREASE_LONG" in a or "ADD_LONG" in a or "ADD_TO_LONG" in a:
        return "LONG"
    if "INCREASE_SHORT" in a or "ADD_SHORT" in a or "ADD_TO_SHORT" in a:
        return "SHORT"

    # Hedges: ADD_HEDGE_LONG means "hedge with a long" but doesn't indicate
    # market direction — it's protective. Mark as NEUTRAL to avoid confusion.
    if "HEDGE" in a:
        return "NEUTRAL"

    # Pure closes/reductions are NEUTRAL
    if any(tok in a for tok in ["CLOSE", "REDUCE", "DECREASE", "PARTIAL", "EXIT"]):
        return "NEUTRAL"

    # HOLD is NEUTRAL
    if a in ("HOLD", "NONE", "WAIT", ""):
        return "NEUTRAL"

    # Fallback: try to extract side from action name
    if "LONG" in a:
        return "LONG"
    if "SHORT" in a:
        return "SHORT"

    return "NEUTRAL"


# ── Reader (Trader/Risk-side) ──────────────────────────────────────────────

def get_intent(redis_client, symbol: str) -> Optional[TrainerIntent]:
    """
    Read the trainer's current intent for a symbol.

    Returns:
        TrainerIntent if available and not expired, None otherwise.
    """
    try:
        enabled = bool(_cfg("TRAINER_INTENT_ENABLED", True))
        if not enabled or not redis_client:
            return None

        key = f"{_INTENT_KEY_PREFIX}:{symbol}"
        data = redis_client.hgetall(key)
        if not data:
            return None

        # Decode bytes if needed
        def _d(v):
            return v.decode("utf-8", errors="replace") if isinstance(v, bytes) else str(v)

        intent = TrainerIntent(
            symbol=symbol,
            direction=_d(data.get(b"direction", data.get("direction", "NEUTRAL"))),
            confidence=float(_d(data.get(b"confidence", data.get("confidence", "0")))),
            action=_d(data.get(b"action", data.get("action", ""))),
            timeframe=_d(data.get(b"timeframe", data.get("timeframe", ""))),
            ts_ms=int(_d(data.get(b"ts_ms", data.get("ts_ms", "0")))),
            producer=_d(data.get(b"producer", data.get("producer", "trainer"))),
        )

        # Don't return stale intents
        if intent.is_stale:
            logger.debug(
                "TRAINER_INTENT_STALE | symbol=%s | age=%.0fs | ttl=%ds",
                symbol, intent.age_seconds, int(_cfg("TRAINER_INTENT_TTL_SEC", _INTENT_TTL_SEC)),
            )
            return None

        return intent

    except Exception as e:
        logger.debug("TRAINER_INTENT_READ_ERR | symbol=%s | %s", symbol, e)
        return None  # Fail-open: no deference


def position_aligns_with_intent(
    redis_client,
    symbol: str,
    position_side: str,
) -> tuple:
    """
    Check if a position aligns with the trainer's current intent.

    Returns:
        (aligns: bool, intent: Optional[TrainerIntent])

    Alignment rules:
    - Intent must be fresh (not stale)
    - Intent must be directional (not NEUTRAL)
    - Intent must be high-confidence
    - Intent direction must match position side
    """
    intent = get_intent(redis_client, symbol)
    if intent is None:
        return (False, None)

    if not intent.is_directional:
        return (False, intent)

    if not intent.is_high_confidence:
        return (False, intent)

    aligns = intent.aligns_with_position(position_side)
    return (aligns, intent)


def get_deference_multiplier(
    redis_client,
    symbol: str,
    position_side: str,
) -> float:
    """
    Get the ROI kill threshold multiplier based on trainer intent alignment.

    Returns:
        1.0  = no deference (normal thresholds)
        2.0  = double threshold (position aligns with high-confidence intent)

    Example:
        Normal PER_LEG_ROI_KILL_PCT = -30%
        With deference: -30% * 2.0 = -60% (requires deeper loss before kill)
    """
    try:
        enabled = bool(_cfg("TRAINER_INTENT_ENABLED", True))
        if not enabled:
            return 1.0

        aligns, intent = position_aligns_with_intent(redis_client, symbol, position_side)
        if not aligns or intent is None:
            return 1.0

        # Scale multiplier by confidence: 0.70 conf → 1.5x, 0.90 conf → 2.0x
        # Linear interpolation between 1.0 and max multiplier
        max_mult = float(_cfg("TRAINER_DEFERENCE_ROI_MULTIPLIER", 2.0))
        min_conf = float(_cfg("TRAINER_INTENT_MIN_CONFIDENCE", _MIN_CONFIDENCE_FOR_DEFERENCE))

        if intent.confidence >= 0.99:
            return max_mult

        # Linear scale: at min_conf → 1.5x, at 1.0 → max_mult
        scale = (intent.confidence - min_conf) / (1.0 - min_conf)
        scale = max(0.0, min(1.0, scale))
        mult = 1.0 + scale * (max_mult - 1.0)

        logger.info(
            "TRAINER_DEFERENCE | symbol=%s | side=%s | direction=%s | "
            "conf=%.3f | mult=%.2f | intent_age=%.0fs",
            symbol, position_side, intent.direction,
            intent.confidence, mult, intent.age_seconds,
        )
        return mult

    except Exception as e:
        logger.debug("TRAINER_DEFERENCE_ERR | symbol=%s | %s", symbol, e)
        return 1.0  # Fail-open: normal thresholds
