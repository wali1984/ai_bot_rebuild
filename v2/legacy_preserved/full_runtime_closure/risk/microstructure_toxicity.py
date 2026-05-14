"""
risk/microstructure_toxicity.py — Defensive Microstructure Toxicity Scorer.

Reads live orderbook / depth features from Redis and computes a composite
"toxicity score" (0..1) for each symbol.  High toxicity signals an adverse
microstructure environment where:

  - Spoofing / quote-stuffing is likely (large orders appear/disappear)
  - Spread is wide / depth is thin (liquidity vacuum)
  - Order-book churn is elevated (fake pressure)
  - Imbalance is unstable / flipping rapidly
  - Fast-move risk is high (whipsaw environment)

The score is used by:

  1. Execution engine  — prefer maker, add delay, reduce clip size
  2. Orchestrator      — attach to signal, may delay entry
  3. Regime layer      — additional primitive for MoE router

Feature-flagged via config.MICROSTRUCTURE_TOXICITY_ENABLED (default: True).

Redis output key: ``toxicity:{symbol}`` with TTL.
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
_TOXICITY_ENABLED = True
_TOXICITY_CACHE_TTL_SEC = 300     # Must survive prediction cycle (~3min)
_TOXICITY_HIGH_THRESHOLD = 0.65   # Above → considered "toxic"
_TOXICITY_EXTREME_THRESHOLD = 0.85  # Above → hard-delay execution

# Component weights (sum to 1.0)
_W_SPOOF = 0.25
_W_CHURN = 0.15
_W_SPREAD = 0.15
_W_DEPTH = 0.15
_W_IMBALANCE = 0.10
_W_FAST_MOVE = 0.10
_W_SNAPBACK = 0.10


def _cfg(key: str, default):
    if config is not None:
        full_key = f"TOXICITY_{key}"
        val = getattr(config, full_key, None)
        if val is not None:
            return val
    return default


class ToxicityResult:
    """Per-symbol toxicity assessment."""

    __slots__ = (
        "symbol", "score", "is_toxic", "is_extreme",
        "components", "execution_hint", "updated_ts_ms",
    )

    def __init__(
        self,
        symbol: str,
        score: float,
        components: Dict[str, float],
        execution_hint: str = "NORMAL",
        updated_ts_ms: int = 0,
    ):
        self.symbol = symbol
        self.score = max(0.0, min(1.0, score))
        self.is_toxic = self.score >= float(_cfg("HIGH_THRESHOLD", _TOXICITY_HIGH_THRESHOLD))
        self.is_extreme = self.score >= float(_cfg("EXTREME_THRESHOLD", _TOXICITY_EXTREME_THRESHOLD))
        self.components = components
        self.execution_hint = execution_hint
        self.updated_ts_ms = updated_ts_ms or int(time.time() * 1000)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "score": round(self.score, 4),
            "is_toxic": self.is_toxic,
            "is_extreme": self.is_extreme,
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "execution_hint": self.execution_hint,
            "updated_ts_ms": self.updated_ts_ms,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ToxicityResult":
        return cls(
            symbol=str(d.get("symbol") or ""),
            score=float(d.get("score") or 0.0),
            components=d.get("components") or {},
            execution_hint=str(d.get("execution_hint") or "NORMAL"),
            updated_ts_ms=int(d.get("updated_ts_ms") or 0),
        )

    def __repr__(self) -> str:
        return f"Toxicity({self.symbol}: {self.score:.3f} hint={self.execution_hint})"


# ── Compute ──────────────────────────────────────────────────────────

def compute_toxicity_from_features(
    features: Dict[str, Any],
    symbol: str = "",
) -> ToxicityResult:
    """Compute toxicity score from unified_features hash fields.

    Expected fields (from depth/orderbook ingestor):
      depth_spoof_score       0..1  spoofing likelihood
      depth_churn_score       0..1  quote churn rate
      depth_spread            float spread in price units
      depth_quality_score     0..1  overall depth quality (inverted)
      depth_imbalance_5       float bid/ask imbalance at 5 levels
      depth_fast_move_score   0..1  fast move risk
      depth_snapback_score    0..1  snapback / whipsaw risk
      depth_total_usd         float total depth USD (thin = risky)
      depth_bps_10_total_usd  float depth within 10bps

    Returns ToxicityResult with score 0 (clean) to 1 (toxic).
    """
    now_ms = int(time.time() * 1000)

    # Extract raw components (safe defaults = neutral)
    spoof = _safe_float(features.get("depth_spoof_score"), 0.0)
    churn = _safe_float(features.get("depth_churn_score"), 0.0)
    quality = _safe_float(features.get("depth_quality_score"), 0.5)
    imbalance_raw = _safe_float(features.get("depth_imbalance_5"), 0.0)
    fast_move = _safe_float(features.get("depth_fast_move_score"), 0.0)
    snapback = _safe_float(features.get("depth_snapback_score"), 0.0)
    spread_raw = _safe_float(features.get("depth_spread"), 0.0)
    mid_price = _safe_float(features.get("depth_mid_price"), 0.0)
    depth_usd = _safe_float(features.get("depth_bps_10_total_usd"), 0.0)

    # Normalize spread to 0..1 (spread_bps / reference)
    spread_bps = 0.0
    if mid_price > 0 and spread_raw > 0:
        spread_bps = (spread_raw / mid_price) * 10000.0
    # 0 bps = clean, 20+ bps = very toxic
    spread_norm = min(1.0, max(0.0, spread_bps / 20.0))

    # Depth thinness: low depth USD = risky
    # 0 USD = extremely thin, $500k+ = thick
    if depth_usd > 0:
        depth_thin = max(0.0, 1.0 - (depth_usd / 500_000.0))
    else:
        depth_thin = 0.5  # Unknown → neutral

    # Imbalance instability: high abs value = one-sided pressure
    imbalance_norm = min(1.0, abs(imbalance_raw))

    # Quality inversion: high quality = low toxicity
    quality_inv = max(0.0, 1.0 - quality)

    # Weighted composite
    w_spoof = float(_cfg("W_SPOOF", _W_SPOOF))
    w_churn = float(_cfg("W_CHURN", _W_CHURN))
    w_spread = float(_cfg("W_SPREAD", _W_SPREAD))
    w_depth = float(_cfg("W_DEPTH", _W_DEPTH))
    w_imbal = float(_cfg("W_IMBALANCE", _W_IMBALANCE))
    w_fast = float(_cfg("W_FAST_MOVE", _W_FAST_MOVE))
    w_snap = float(_cfg("W_SNAPBACK", _W_SNAPBACK))

    w_total = w_spoof + w_churn + w_spread + w_depth + w_imbal + w_fast + w_snap
    if w_total <= 0:
        w_total = 1.0

    score = (
        w_spoof * spoof
        + w_churn * churn
        + w_spread * spread_norm
        + w_depth * depth_thin
        + w_imbal * imbalance_norm
        + w_fast * fast_move
        + w_snap * snapback
    ) / w_total

    score = max(0.0, min(1.0, score))

    # Determine execution hint
    extreme_thresh = float(_cfg("EXTREME_THRESHOLD", _TOXICITY_EXTREME_THRESHOLD))
    high_thresh = float(_cfg("HIGH_THRESHOLD", _TOXICITY_HIGH_THRESHOLD))

    if score >= extreme_thresh:
        hint = "WAIT_REPRICE"  # Delay execution, wait for cleaner microstructure
    elif score >= high_thresh:
        hint = "MAKER_ONLY"   # Avoid taker, use limit orders only
    elif score >= 0.40:
        hint = "REDUCE_SIZE"  # Halve clip size to reduce impact
    else:
        hint = "NORMAL"       # Clean microstructure, proceed normally

    components = {
        "spoof": round(spoof, 4),
        "churn": round(churn, 4),
        "spread_norm": round(spread_norm, 4),
        "depth_thin": round(depth_thin, 4),
        "imbalance": round(imbalance_norm, 4),
        "fast_move": round(fast_move, 4),
        "snapback": round(snapback, 4),
        "quality_inv": round(quality_inv, 4),
    }

    return ToxicityResult(
        symbol=symbol,
        score=score,
        components=components,
        execution_hint=hint,
        updated_ts_ms=now_ms,
    )


def compute_toxicity_from_redis(
    redis_client,
    symbol: str,
    timeframe: str = "5m",
) -> Optional[ToxicityResult]:
    """Read unified_features for a symbol, compute toxicity, cache result."""
    if not redis_client:
        return None
    try:
        key = f"unified_features:{symbol}:{timeframe}"
        raw = redis_client.hgetall(key)
        if not raw:
            return None
        # Decode bytes
        features: Dict[str, Any] = {}
        for k, v in raw.items():
            kk = k.decode("utf-8", errors="ignore") if isinstance(k, (bytes, bytearray)) else str(k)
            vv = v.decode("utf-8", errors="ignore") if isinstance(v, (bytes, bytearray)) else str(v)
            features[kk] = vv

        result = compute_toxicity_from_features(features, symbol=symbol)

        # Cache
        ttl = int(_cfg("CACHE_TTL_SEC", _TOXICITY_CACHE_TTL_SEC))
        try:
            redis_client.setex(
                f"toxicity:{symbol}",
                max(10, ttl),
                json.dumps(result.to_dict(), separators=(",", ":")),
            )
        except Exception:
            pass

        return result

    except Exception as e:
        logger.debug("[TOXICITY_ERROR] %s: %s", symbol, e)
        return None


def read_cached_toxicity(
    redis_client,
    symbol: str,
) -> Optional[ToxicityResult]:
    """Read cached toxicity from Redis. Returns None if missing."""
    if not redis_client:
        return None
    try:
        raw = redis_client.get(f"toxicity:{symbol}")
        if not raw:
            return None
        val = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
        data = json.loads(val)
        if not isinstance(data, dict):
            return None
        return ToxicityResult.from_dict(data)
    except Exception:
        return None


def compute_universe_toxicity(
    redis_client,
    symbols: Optional[List[str]] = None,
    timeframe: str = "5m",
) -> Dict[str, ToxicityResult]:
    """Compute toxicity for all symbols in the universe."""
    if not redis_client:
        return {}
    if symbols is None:
        symbols = list(getattr(config, "SYMBOLS", []) or [])

    results: Dict[str, ToxicityResult] = {}
    for sym in symbols:
        try:
            r = compute_toxicity_from_redis(redis_client, sym, timeframe)
            if r:
                results[sym] = r
        except Exception:
            pass
    return results


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        f = float(val)
        if f != f:  # NaN check
            return default
        return f
    except (ValueError, TypeError):
        return default
