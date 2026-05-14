"""
risk/global_breadth.py — Cross-symbol global breadth signal.

Aggregates per-symbol regime data (tf_alignment, tf_entropy, fast_move_score,
liq_imbalance, volatility_score) into portfolio-wide breadth metrics:

  breadth_dir         int  {-1, 0, +1}   consensus direction
  breadth_strength    float 0..1          fraction of symbols aligned
  breadth_entropy     float 0..1          cross-symbol dispersion
  breadth_corr        float 0..1          avg cross-symbol alignment correlation
  breadth_vol         float 0..1          global vol score (weighted avg)
  breadth_fast_move   float 0..1          max fast_move_score across universe
  breadth_liq_imbal   float               avg log liq imbalance (signed)
  updated_ts_ms       int                 computation timestamp

All computation uses existing unified_features + regime:{symbol} Redis data.
No new data sources required.

Feature-flagged via config.GLOBAL_BREADTH_ENABLED (default: False).

Redis output key: ``regime:global:{timeframe}`` with configurable TTL.
"""

from __future__ import annotations

import json
import logging
import math
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import config
except ImportError:
    config = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ── Defaults (overridden by config if available) ─────────────────────
_BREADTH_ENABLED = False
_BREADTH_MIN_SYMBOLS = 4
_BREADTH_ALIGNED_THRESHOLD = 0.30   # abs(tf_alignment) > this → "aligned"
_BREADTH_CACHE_TTL_SEC = 45
_BREADTH_STALE_SEC = 600
_BREADTH_TIMEFRAMES = ["5m", "15m"]  # TFs for which global breadth is computed


def _cfg(key: str, default):
    """Read from config with safe fallback."""
    if config is not None:
        return getattr(config, key, default)
    return default


def compute_global_breadth(
    regimes_by_symbol: Dict[str, Dict[str, Any]],
    *,
    symbols: Optional[List[str]] = None,
    now_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Compute cross-symbol breadth from per-symbol regime dicts.

    Parameters
    ----------
    regimes_by_symbol : dict
        ``{symbol: regime_dict}`` where regime_dict is the output of
        ``risk.market_regime.compute_regime()``.
    symbols : list, optional
        Restrict computation to these symbols (else all keys).
    now_ms : int, optional
        Current timestamp (default: now).

    Returns
    -------
    dict  with keys documented in module docstring.
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)

    stale_sec = float(_cfg("GLOBAL_BREADTH_STALE_SEC", _BREADTH_STALE_SEC))
    stale_cutoff_ms = now_ms - int(stale_sec * 1000)
    min_symbols = int(_cfg("GLOBAL_BREADTH_MIN_SYMBOLS", _BREADTH_MIN_SYMBOLS))
    align_thresh = float(_cfg("GLOBAL_BREADTH_ALIGNED_THRESHOLD", _BREADTH_ALIGNED_THRESHOLD))

    # Filter valid + fresh regimes
    target_syms = set(s.upper() for s in symbols) if symbols else set(regimes_by_symbol.keys())
    fresh: Dict[str, Dict[str, Any]] = {}
    for sym in target_syms:
        r = regimes_by_symbol.get(sym)
        if not r or not isinstance(r, dict):
            continue
        updated = int(r.get("updated_ts_ms") or 0)
        if updated > 0 and updated < stale_cutoff_ms:
            continue  # stale
        fresh[sym] = r

    n = len(fresh)
    empty = _empty_breadth(now_ms, n)

    if n < min_symbols:
        logger.debug(
            "[BREADTH_INSUFFICIENT] fresh=%d min=%d stale_cutoff_ms=%d",
            n, min_symbols, stale_cutoff_ms,
        )
        return empty

    # ── Collect per-symbol primitives ─────────────────────────────────
    alignments: List[float] = []    # signed tf_alignment (-1..+1)
    entropies: List[float] = []     # per-symbol tf_entropy (0..1)
    vol_scores: List[float] = []    # volatility_score (0..1)
    fast_moves: List[float] = []    # fast_move_score (0..1)
    liq_imbals: List[float] = []    # signed liq_imbalance
    move_scores: List[float] = []   # move_score (0..1)

    for sym, r in fresh.items():
        alignments.append(float(r.get("tf_alignment") or 0.0))
        entropies.append(float(r.get("tf_entropy") or 0.0))
        vol_scores.append(float(r.get("volatility_score") or 0.0))
        fast_moves.append(float(r.get("fast_move_score") or 0.0))
        liq_imbals.append(float(r.get("liq_imbalance") or 0.0))
        move_scores.append(float(r.get("move_score") or 0.0))

    # ── 1. Breadth direction + strength ───────────────────────────────
    # Count how many symbols are aligned LONG (+) vs SHORT (-) above threshold
    n_long = sum(1 for a in alignments if a > align_thresh)
    n_short = sum(1 for a in alignments if a < -align_thresh)
    n_neutral = n - n_long - n_short

    if n_long > n_short:
        breadth_dir = 1
        aligned_count = n_long
    elif n_short > n_long:
        breadth_dir = -1
        aligned_count = n_short
    else:
        breadth_dir = 0
        aligned_count = max(n_long, n_short)

    breadth_strength = float(aligned_count) / float(n) if n > 0 else 0.0

    # ── 2. Breadth entropy (cross-symbol vote dispersion) ─────────────
    # Shannon entropy over [long, neutral, short] buckets, normalised to 0..1
    p_long = float(n_long) / float(n) if n > 0 else 0.0
    p_neutral = float(n_neutral) / float(n) if n > 0 else 0.0
    p_short = float(n_short) / float(n) if n > 0 else 0.0
    ent = 0.0
    for p in [p_long, p_neutral, p_short]:
        if p > 0:
            ent -= p * math.log2(p)
    # Max entropy for 3 states = log2(3) ≈ 1.585
    breadth_entropy = min(1.0, ent / 1.585) if ent > 0 else 0.0

    # ── 3. Breadth correlation (avg pairwise alignment similarity) ────
    # Proxy: how similarly aligned are symbols? Use mean absolute alignment.
    # Then measure variance — low variance = high corr.
    mean_align = sum(alignments) / n if n > 0 else 0.0
    var_align = sum((a - mean_align) ** 2 for a in alignments) / n if n > 1 else 0.0
    # Normalise: max variance for uniform in [-1,1] ≈ 0.33
    # breadth_corr = 1 - normalised_variance (high corr = low variance)
    breadth_corr = max(0.0, min(1.0, 1.0 - (var_align / 0.33))) if var_align >= 0 else 0.5

    # ── 4. Breadth vol (weighted average vol score) ───────────────────
    # Weight by move_score (volatile + fast-moving symbols count more)
    weight_sum = 0.0
    weighted_vol = 0.0
    for i in range(n):
        w = 1.0 + float(move_scores[i])  # base weight 1.0, up to 2.0
        weighted_vol += float(vol_scores[i]) * w
        weight_sum += w
    breadth_vol = float(weighted_vol / weight_sum) if weight_sum > 0 else 0.0

    # ── 5. Global fast move (max across universe) ─────────────────────
    breadth_fast_move = max(fast_moves) if fast_moves else 0.0

    # ── 6. Average liq imbalance (signed) ─────────────────────────────
    breadth_liq_imbal = sum(liq_imbals) / n if n > 0 else 0.0

    return {
        "breadth_dir": int(breadth_dir),
        "breadth_strength": round(breadth_strength, 4),
        "breadth_entropy": round(breadth_entropy, 4),
        "breadth_corr": round(breadth_corr, 4),
        "breadth_vol": round(breadth_vol, 4),
        "breadth_fast_move": round(breadth_fast_move, 4),
        "breadth_liq_imbal": round(breadth_liq_imbal, 4),
        "n_symbols_fresh": int(n),
        "n_long": int(n_long),
        "n_short": int(n_short),
        "n_neutral": int(n_neutral),
        "updated_ts_ms": int(now_ms),
    }


def _empty_breadth(now_ms: int, n_fresh: int = 0) -> Dict[str, Any]:
    return {
        "breadth_dir": 0,
        "breadth_strength": 0.0,
        "breadth_entropy": 1.0,  # max dispersion = uncertain
        "breadth_corr": 0.0,
        "breadth_vol": 0.0,
        "breadth_fast_move": 0.0,
        "breadth_liq_imbal": 0.0,
        "n_symbols_fresh": int(n_fresh),
        "n_long": 0,
        "n_short": 0,
        "n_neutral": 0,
        "updated_ts_ms": int(now_ms),
    }


# ── Redis convenience helpers ────────────────────────────────────────

def compute_and_cache_global_breadth(
    redis_client,
    *,
    symbols: Optional[List[str]] = None,
    timeframe: str = "5m",
) -> Dict[str, Any]:
    """Read per-symbol regimes from Redis, compute breadth, cache result.

    Reads ``regime:{symbol}`` for each symbol, computes global breadth,
    writes to ``regime:global:{timeframe}`` with TTL.

    Returns the breadth dict (or empty dict on error).
    """
    if not redis_client:
        return {}

    try:
        if symbols is None:
            symbols = list(_cfg("SYMBOLS", []) or [])
        if not symbols:
            return {}

        now_ms = int(time.time() * 1000)
        regimes: Dict[str, Dict[str, Any]] = {}

        # Pipeline read for efficiency
        try:
            pipe = redis_client.pipeline(transaction=False)
            for sym in symbols:
                pipe.get(f"regime:{sym}")
            results = pipe.execute()
        except Exception:
            # Fallback: individual reads
            results = []
            for sym in symbols:
                try:
                    results.append(redis_client.get(f"regime:{sym}"))
                except Exception:
                    results.append(None)

        for i, sym in enumerate(symbols):
            raw = results[i] if i < len(results) else None
            if not raw:
                continue
            try:
                val = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
                regime = json.loads(val)
                if isinstance(regime, dict):
                    regimes[sym.upper()] = regime
            except Exception:
                continue

        breadth = compute_global_breadth(regimes, symbols=symbols, now_ms=now_ms)

        # Cache to Redis
        ttl = int(_cfg("GLOBAL_BREADTH_CACHE_TTL_SEC", _BREADTH_CACHE_TTL_SEC))
        try:
            redis_client.setex(
                f"regime:global:{timeframe}",
                max(10, ttl),
                json.dumps(breadth, separators=(",", ":")),
            )
        except Exception:
            pass

        return breadth

    except Exception as e:
        logger.debug("[GLOBAL_BREADTH_ERROR] %s", e)
        return {}


def read_cached_breadth(
    redis_client,
    timeframe: str = "5m",
) -> Optional[Dict[str, Any]]:
    """Read cached breadth from Redis.  Returns None if missing/stale."""
    if not redis_client:
        return None
    try:
        raw = redis_client.get(f"regime:global:{timeframe}")
        if not raw:
            return None
        val = raw.decode("utf-8", errors="ignore") if isinstance(raw, (bytes, bytearray)) else str(raw)
        data = json.loads(val)
        if not isinstance(data, dict):
            return None
        # Staleness check
        stale_sec = float(_cfg("GLOBAL_BREADTH_STALE_SEC", _BREADTH_STALE_SEC))
        updated = int(data.get("updated_ts_ms") or 0)
        now_ms = int(time.time() * 1000)
        if updated > 0 and (now_ms - updated) > int(stale_sec * 1000):
            return None
        return data
    except Exception:
        return None
