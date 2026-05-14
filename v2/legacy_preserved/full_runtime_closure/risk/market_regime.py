"""
risk/market_regime.py — Single-source market regime computation.

Reads unified_features from Redis, computes a normalised regime object
that every module consumes (trainer proposals, orchestrator policy,
hedge_manager sizing).  Written to Redis as ``regime:{symbol}`` and
attached inline to every proposal/signal metadata.

Regime fields:
  move_score        float 0..1   ATR-normalised absolute return across TFs
  move_regime       str          CALM / NORMAL / FAST / IMPULSE
  volatility_score  float 0..1   Realised vol rank (NATR cross-TF)
  fast_move_score   float 0..1   Orderbook fast-move detection score
  liq_risk          float 0..1   Distance + imbalance combined risk
  liquidity_score   float 0..1   Depth/spread quality proxy
  tf_alignment      float -1..1  Aggregate TF bias direction (signed strength)
  tf_conflict       float 0..1   TF conflict score (existing)
  tf_entropy        float 0..1   TF disagreement entropy (vote dispersion)
  liq_imbalance     float        log imbalance: ln(long_strength/short_strength)
  regime_version    str          Schema version (e.g. v1)
  updated_ts_ms     int          Computation timestamp
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

try:
    import config
except ImportError:
    config = None

logger = logging.getLogger(__name__)

# ── Move regime thresholds (normalised move_score 0..1) ──────────────
# Read from config if available, else use safe defaults
if config and hasattr(config, "REGIME_MOVE_CALM_MAX"):
    MOVE_CALM_MAX = config.REGIME_MOVE_CALM_MAX
    MOVE_NORMAL_MAX = config.REGIME_MOVE_NORMAL_MAX
    MOVE_FAST_MAX = config.REGIME_MOVE_FAST_MAX
else:
    MOVE_CALM_MAX = 0.20
    MOVE_NORMAL_MAX = 0.45
    MOVE_FAST_MAX = 0.70
# Above MOVE_FAST_MAX → IMPULSE

# ── Feature key lookup helpers ───────────────────────────────────────
_NATR_KEYS = [
    "ind_ta_NATR_14_{tf}",
    "ind_ind_{sym}_ta_NATR_14_{tf}",
    "ccxt_volatility_{tf}",
]
_ATR_KEYS = [
    "ind_ta_ATR_14_{tf}",
    "ind_ind_{sym}_ta_ATR_14_{tf}",
]
_CLOSE_KEYS = [
    "ccxt_close",
    "close",
]
_FAST_MOVE_KEYS = [
    "depth_fast_move_score",
    "depth_fast_move_{tf}",
]
_SPREAD_KEYS = [
    "spread_bps",
    "ccxt_spread_bps",
    "ind_spread_bps",
]
_DEPTH_KEYS = [
    "depth_total_usd",
    "orderbook_depth_usd",
    "depth_bps_25_total_usd",
]


def _safe_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    try:
        v = float(val)
        return v if v == v else default  # NaN guard
    except (ValueError, TypeError):
        return default


def _feat_get(feat: Dict, patterns: list, *, tf: str = "", sym: str = "") -> float:
    """Try multiple key patterns and return first non-zero float."""
    for pat in patterns:
        key = pat.replace("{tf}", tf).replace("{sym}", sym)
        v = _safe_float(feat.get(key))
        if v != 0.0:
            return v
        # Try bytes variant (Redis hgetall without decode_responses)
        v = _safe_float(feat.get(key.encode()))
        if v != 0.0:
            return v
    return 0.0


def compute_regime(
    symbol: str,
    features_by_tf: Dict[str, Dict[str, Any]],
    *,
    tf_agg: Optional[Dict[str, Any]] = None,
    liq_long_strength: float = 0.0,
    liq_short_strength: float = 0.0,
    liq_distance_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """Compute a normalised market regime object from multi-TF features.

    Parameters
    ----------
    symbol : str
        Trading pair (e.g. BTCUSDT).
    features_by_tf : dict
        ``{tf_str: feature_dict}`` — raw Redis hashes per timeframe.
    tf_agg : dict, optional
        Pre-computed TF aggregation (bias_dir, timing_dir, conflict_score, tf_votes).
    liq_long_strength, liq_short_strength : float
        Liquidation strengths from unified_features or liqmap.
    liq_distance_pct : float, optional
        Current liquidation distance %, or None.

    Returns
    -------
    dict  with keys documented in module docstring.
    """
    sym = str(symbol or "").upper().replace("USDT", "")
    now_ms = int(time.time() * 1000)

    # ── 1. Volatility score: cross-TF NATR normalised to 0..1 ───────
    natr_vals = []
    for tf, feat in features_by_tf.items():
        natr = _feat_get(feat, _NATR_KEYS, tf=tf, sym=sym)
        if natr > 0:
            natr_vals.append(natr)

    # NATR is typically in percent (0.05 = 5 bps); normalise so 0.5% → 1.0
    avg_natr = sum(natr_vals) / len(natr_vals) if natr_vals else 0.0
    # Different TFs have different scale; 1m NATR ~0.05%, 1h ~0.7%
    # Use max across TFs for "how volatile is the market right now"
    max_natr = max(natr_vals) if natr_vals else 0.0
    # Reference: 0.5% NATR on 1h is quite volatile; scale accordingly
    volatility_score = min(1.0, max_natr / 2.0) if max_natr > 0 else 0.0

    # ── 2. Move score: ATR-normalised price move across TFs ──────────
    move_components = []
    for tf, feat in features_by_tf.items():
        atr = _feat_get(feat, _ATR_KEYS, tf=tf, sym=sym)
        close = _feat_get(feat, _CLOSE_KEYS, tf=tf, sym=sym)
        # We need the return; approximate from NATR + close (NATR = ATR/close * 100)
        # A better approach: if we have ATR and close, and NATR, then move ~ NATR
        # Use NATR directly as a proxy for "recent move magnitude normalised by ATR"
        natr = _feat_get(feat, _NATR_KEYS, tf=tf, sym=sym)
        if natr > 0:
            # NATR is ATR/close * 100, so it's already normalised
            # Scale: 0.05 (5 bps) is calm, 0.3 (30 bps) is fast, >0.5 impulse
            move_components.append(natr)

    # Weight shorter TFs more heavily (1m, 5m capture real-time moves)
    tf_weights = {"1m": 3.0, "5m": 2.5, "15m": 1.5, "1h": 1.0, "4h": 0.5}
    weighted_sum = 0.0
    weight_total = 0.0
    for tf, feat in features_by_tf.items():
        natr = _feat_get(feat, _NATR_KEYS, tf=tf, sym=sym)
        w = tf_weights.get(tf, 1.0)
        weighted_sum += natr * w
        weight_total += w
    weighted_move = weighted_sum / weight_total if weight_total > 0 else 0.0
    # Normalise to 0..1: 0.05% → ~0.1, 0.25% → ~0.5, 0.50% → ~1.0
    move_score = min(1.0, weighted_move / 0.5) if weighted_move > 0 else 0.0

    # ── 3. Move regime classification ────────────────────────────────
    if move_score <= MOVE_CALM_MAX:
        move_regime = "CALM"
    elif move_score <= MOVE_NORMAL_MAX:
        move_regime = "NORMAL"
    elif move_score <= MOVE_FAST_MAX:
        move_regime = "FAST"
    else:
        move_regime = "IMPULSE"

    # ── 4. Fast move score (orderbook-derived) ───────────────────────
    fms_vals = []
    for tf, feat in features_by_tf.items():
        fms = _feat_get(feat, _FAST_MOVE_KEYS, tf=tf, sym=sym)
        if fms > 0:
            fms_vals.append(fms)
    fast_move_score = max(fms_vals) if fms_vals else 0.0

    # ── 5. Liquidity score (spread + depth proxy) ────────────────────
    spread_vals = []
    depth_vals = []
    for tf, feat in features_by_tf.items():
        sp = _feat_get(feat, _SPREAD_KEYS, tf=tf, sym=sym)
        if sp > 0:
            spread_vals.append(sp)
        dp = _feat_get(feat, _DEPTH_KEYS, tf=tf, sym=sym)
        if dp > 0:
            depth_vals.append(dp)
    # Spread: lower is better.  Reference: 1 bps excellent, 5 bps bad
    avg_spread = sum(spread_vals) / len(spread_vals) if spread_vals else 0.0
    spread_quality = max(0.0, 1.0 - avg_spread / 5.0) if avg_spread > 0 else 0.5  # default neutral
    # Depth: higher is better.  Reference: $100k+ is good for alts, $1M+ for majors
    avg_depth = sum(depth_vals) / len(depth_vals) if depth_vals else 0.0
    depth_quality = min(1.0, avg_depth / 500_000.0) if avg_depth > 0 else 0.5  # default neutral
    liquidity_score = (spread_quality + depth_quality) / 2.0

    # ── 6. Liq risk (distance + imbalance) ───────────────────────────
    liq_risk = 0.0
    if liq_distance_pct is not None and liq_distance_pct > 0:
        # Closer to liq = higher risk.  Reference: 5% safe, 1% dangerous
        liq_risk = max(0.0, 1.0 - (liq_distance_pct / 5.0))
    liq_total = liq_long_strength + liq_short_strength
    if liq_total > 0:
        imbalance = abs(liq_long_strength - liq_short_strength) / liq_total
        # Imbalance adds risk (0..0.5 range, capped)
        liq_risk = min(1.0, liq_risk + imbalance * 0.3)

    # ── 7. TF alignment + entropy (from pre-computed aggregation) ────
    tf_alignment = 0.0
    tf_conflict = 0.0
    tf_entropy = 0.0
    if tf_agg and isinstance(tf_agg, dict):
        # tf_alignment: direction * strength (-1..+1)
        bias_dir = float(tf_agg.get("bias_dir", 0) or 0)
        timing_dir = float(tf_agg.get("timing_dir", 0) or 0)
        # Average direction as signed alignment
        tf_alignment = (bias_dir + timing_dir) / 2.0
        tf_alignment = max(-1.0, min(1.0, tf_alignment))
        
        # tf_conflict: existing conflict score
        tf_conflict = float(tf_agg.get("conflict_score", 0) or 0)
        tf_conflict = max(0.0, min(1.0, tf_conflict))
        
        # tf_entropy: vote dispersion (Shannon entropy approximation)
        # From tf_votes dict: count +1, 0, -1 votes and compute entropy
        tf_votes = tf_agg.get("tf_votes", {})
        if tf_votes and isinstance(tf_votes, dict):
            votes = [float(v) for v in tf_votes.values() if v is not None]
            if votes:
                # Count direction buckets
                n_long = sum(1 for v in votes if v > 0)
                n_flat = sum(1 for v in votes if v == 0)
                n_short = sum(1 for v in votes if v < 0)
                total = len(votes)
                if total > 0:
                    # Normalize to probabilities
                    p_long = n_long / total
                    p_flat = n_flat / total
                    p_short = n_short / total
                    # Shannon entropy (normalized to 0..1)
                    import math
                    ent = 0.0
                    for p in [p_long, p_flat, p_short]:
                        if p > 0:
                            ent -= p * math.log2(p)
                    # Max entropy for 3 states = log2(3) ≈ 1.585
                    tf_entropy = min(1.0, ent / 1.585) if ent > 0 else 0.0
    else:
        # Per-TF mode: comprehensive direction from 2000+ unified features
        _dir_signals = []
        for tf, feat in features_by_tf.items():
            _fg = lambda keys: _feat_get(feat, keys, tf=tf, sym=sym)
            _votes = []  # (weight, signal) pairs

            # ─── TA-Lib trend indicators (weight: high) ───────────────────
            _rsi = _fg(["ind_ta_RSI_14_{tf}", "ind_ta_RSI_14", "rsi_14"])
            if _rsi > 0:
                _votes.append((0.12, max(-1.0, min(1.0, (_rsi - 50) / 30))))

            _macd_hist = _fg(["ind_ta_MACDhist_12_26_9_{tf}", "ind_ta_MACD_macd_fastperiod12_slowperiod26_signalperiod9_{tf}"])
            if _macd_hist != 0:
                _votes.append((0.10, 1.0 if _macd_hist > 0 else -1.0))

            _adx = _fg(["ind_ta_ADX_14_{tf}", "ind_ta_ADX_14"])
            _plus_di = _fg(["ind_ta_PLUS_DI_14_{tf}", "ind_ta_PLUS_DI_14"])
            _minus_di = _fg(["ind_ta_MINUS_DI_14_{tf}", "ind_ta_MINUS_DI_14"])
            if _adx > 15 and (_plus_di > 0 or _minus_di > 0):
                _adx_strength = min(1.0, _adx / 40)
                _di_dir = 1.0 if _plus_di > _minus_di else -1.0
                _votes.append((0.12, _di_dir * _adx_strength))

            _cci = _fg(["ind_ta_CCI_14_{tf}", "ind_ta_CCI_14"])
            if _cci != 0:
                _votes.append((0.05, max(-1.0, min(1.0, _cci / 150))))

            _willr = _fg(["ind_ta_WILLR_14_{tf}", "ind_ta_WILLR_14"])
            if _willr != 0:
                _votes.append((0.04, max(-1.0, min(1.0, -(_willr + 50) / 30))))

            _mom = _fg(["ind_ta_MOM_14_{tf}", "ind_ta_MOM_14"])
            if _mom != 0:
                _votes.append((0.04, 1.0 if _mom > 0 else -1.0))

            _bop = _fg(["ind_ta_BOP_{tf}", "ind_ta_BOP"])
            if _bop != 0:
                _votes.append((0.04, max(-1.0, min(1.0, _bop))))

            _aroon_up = _fg(["ind_ta_AROON_up_14_{tf}", "ind_ta_AROON_up_14"])
            _aroon_dn = _fg(["ind_ta_AROON_down_14_{tf}", "ind_ta_AROON_down_14"])
            if _aroon_up > 0 or _aroon_dn > 0:
                _aroon_dir = (_aroon_up - _aroon_dn) / 100.0
                _votes.append((0.04, max(-1.0, min(1.0, _aroon_dir))))

            _trix = _fg(["ind_ta_TRIX_14_{tf}", "ind_ta_TRIX_14"])
            if _trix != 0:
                _votes.append((0.03, 1.0 if _trix > 0 else -1.0))

            _ht = _fg(["ind_ta_HT_TRENDMODE_{tf}", "ind_ta_HT_TRENDMODE"])
            if _ht != 0:
                _votes.append((0.02, 1.0 if _ht > 0 else -1.0))

            # EMA alignment (EMA10 > EMA50 > EMA200 = bullish)
            _ema10 = _fg(["ind_ta_EMA_10_{tf}", "ind_ta_EMA_10"])
            _ema50 = _fg(["ind_ta_EMA_50_{tf}", "ind_ta_EMA_50", "ema_50"])
            _ema200 = _fg(["ind_ta_EMA_200_{tf}", "ind_ta_EMA_200", "ema_200"])
            _close = _fg(_CLOSE_KEYS)
            if _ema50 > 0 and _ema200 > 0:
                _ema_align = 1.0 if _ema50 > _ema200 else -1.0
                _votes.append((0.08, _ema_align))
            if _close > 0 and _ema10 > 0:
                _price_vs_ema = 1.0 if _close > _ema10 else -1.0
                _votes.append((0.04, _price_vs_ema))

            _pressure = _fg(["ind_ta_pressure", f"ind_ind_{tf}_pressure", "ind_ind_1m_pressure"])
            if _pressure != 0:
                _votes.append((0.03, max(-1.0, min(1.0, _pressure))))

            # ─── Orderbook / Microstructure (weight: medium) ──────────────
            _ob_imb = _fg(["ob_ob_imbalance", "depth_imbalance_5"])
            if _ob_imb != 0:
                _votes.append((0.06, max(-1.0, min(1.0, _ob_imb * 2))))

            _trade_imb_1s = _fg(["depth_trade_imbalance_1s"])
            if _trade_imb_1s != 0:
                _votes.append((0.04, max(-1.0, min(1.0, _trade_imb_1s))))

            _trade_imb_5s = _fg(["depth_trade_imbalance_5s"])
            if _trade_imb_5s != 0:
                _votes.append((0.03, max(-1.0, min(1.0, _trade_imb_5s))))

            # ─── CoinAnk (weight: medium) ─────────────────────────────────
            _fr = _fg(["coinank_fundingRate_indicator_data_0_fundingRate", "coinank_fundingRate_indicator_data_0_fr", "funding_rate"])
            if _fr != 0:
                _votes.append((0.04, max(-1.0, min(1.0, _fr * 100))))

            _ls_global = _fg(["coinank_ls_global_account_ratio_longShortRatio_mean", "coinank_ls_global_account_ratio_data_0_longShortRatio"])
            if _ls_global > 0:
                _ls_dir = max(-1.0, min(1.0, (_ls_global - 1.0) * 2))
                _votes.append((0.03, _ls_dir))

            _ls_top = _fg(["coinank_ls_toptrader_accounts_longShortRatio_first", "coinank_ls_toptrader_accounts_longShortRatio_mean"])
            if _ls_top > 0:
                _ls_top_dir = max(-1.0, min(1.0, (_ls_top - 1.0) * 2))
                _votes.append((0.03, _ls_top_dir))

            _buy_val = _fg(["coinank_marketOrder_getBuySellValue_data_col1_last"])
            _sell_val = _fg(["coinank_marketOrder_getBuySellValue_data_col2_last"])
            if _buy_val > 0 and _sell_val > 0:
                _total_val = _buy_val + _sell_val
                _mkt_imb = (_buy_val - _sell_val) / _total_val if _total_val > 0 else 0.0
                _votes.append((0.04, max(-1.0, min(1.0, _mkt_imb * 3))))

            # ─── Liquidation zone pressure ────────────────────────────────
            _liq_l_str = _fg(["liquidation_long_strength"])
            _liq_s_str = _fg(["liquidation_short_strength"])
            if _liq_l_str > 0 or _liq_s_str > 0:
                _liq_total = _liq_l_str + _liq_s_str
                if _liq_total > 0:
                    _liq_dir = (_liq_s_str - _liq_l_str) / _liq_total
                    _votes.append((0.04, max(-1.0, min(1.0, _liq_dir))))

            _liq_l_dist = _fg(["liquidation_long_distance_pct"])
            _liq_s_dist = _fg(["liquidation_short_distance_pct"])
            if _liq_l_dist > 0 and _liq_s_dist > 0:
                _closer_short = 1.0 if _liq_s_dist < _liq_l_dist else -1.0
                _votes.append((0.02, _closer_short))

            # ─── Cross-TF context features ────────────────────────────────
            for _ctx_tf in ("1h", "4h", "15m"):
                _xtf_imb = _fg([f"xtf_{_ctx_tf}_ob_ob_imbalance"])
                if _xtf_imb != 0:
                    _votes.append((0.01, max(-1.0, min(1.0, _xtf_imb * 2))))

            # ─── Compute weighted alignment ───────────────────────────────
            _w_sum = 0.0
            _w_total = 0.0
            for _w, _s in _votes:
                _w_sum += _w * _s
                _w_total += _w
            _tf_align = _w_sum / _w_total if _w_total > 0 else 0.0
            _dir_signals.append(max(-1.0, min(1.0, _tf_align)))
        if _dir_signals:
            tf_alignment = sum(_dir_signals) / len(_dir_signals)
            tf_alignment = max(-1.0, min(1.0, tf_alignment))

    # ── 8. Liq imbalance (log ratio) ─────────────────────────────────
    liq_imbalance = 0.0
    if liq_long_strength > 0 and liq_short_strength > 0:
        import math
        liq_imbalance = math.log(liq_long_strength / liq_short_strength)
    
    # ── 9. Version tracking ──────────────────────────────────────────
    regime_version = "v1"
    if config and hasattr(config, "REGIME_VERSION"):
        regime_version = config.REGIME_VERSION

    if tf_alignment > 0.15:
        trend_direction = "LONG"
    elif tf_alignment < -0.15:
        trend_direction = "SHORT"
    else:
        trend_direction = "NEUTRAL"

    return {
        "move_score": round(move_score, 4),
        "move_regime": move_regime,
        "market_regime": move_regime,
        "trend_direction": trend_direction,
        "volatility_score": round(volatility_score, 4),
        "fast_move_score": round(fast_move_score, 4),
        "liq_risk": round(liq_risk, 4),
        "liquidity_score": round(liquidity_score, 4),
        "tf_alignment": round(tf_alignment, 4),
        "tf_conflict": round(tf_conflict, 4),
        "tf_entropy": round(tf_entropy, 4),
        "liq_imbalance": round(liq_imbalance, 4),
        "regime_version": regime_version,
        "updated_ts_ms": now_ms,
    }


def compute_regime_from_redis(
    redis_client,
    symbol: str,
    timeframes: Optional[list] = None,
    *,
    tf_agg: Optional[Dict[str, Any]] = None,
    liq_long_strength: float = 0.0,
    liq_short_strength: float = 0.0,
    liq_distance_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """Convenience: read features from Redis then compute regime.

    Also writes result to ``regime:{symbol}`` with TTL for caching.
    
    **Fail-open behavior**: If any exception occurs, returns empty dict.
    Caller must check for missing fields and use old logic as fallback.
    """
    if timeframes is None:
        timeframes = ["1m", "5m", "15m", "1h"]

    # Fail-open: if anything goes wrong, return empty dict
    try:
        features_by_tf: Dict[str, Dict[str, Any]] = {}
        if redis_client:
            for tf in timeframes:
                key = f"unified_features:{symbol}:{tf}"
                try:
                    raw = redis_client.hgetall(key)
                    if raw:
                        # Decode bytes keys/values if needed
                        feat: Dict[str, Any] = {}
                        for k, v in raw.items():
                            ks = k.decode("utf-8", errors="ignore") if isinstance(k, (bytes, bytearray)) else str(k)
                            vs = v.decode("utf-8", errors="ignore") if isinstance(v, (bytes, bytearray)) else str(v)
                            feat[ks] = vs
                        features_by_tf[tf] = feat
                except Exception:
                    pass

        regime = compute_regime(
            symbol,
            features_by_tf,
            tf_agg=tf_agg,
            liq_long_strength=liq_long_strength,
            liq_short_strength=liq_short_strength,
            liq_distance_pct=liq_distance_pct,
        )

        # Cache to Redis
        if redis_client:
            ttl = 60
            if config and hasattr(config, "REGIME_CACHE_TTL_SEC"):
                ttl = config.REGIME_CACHE_TTL_SEC
            try:
                redis_client.setex(
                    f"regime:{symbol}",
                    ttl,
                    json.dumps(regime, separators=(",", ":")),
                )
                # region agent log
                try:
                    _ts = int(time.time() * 1000)
                    _symu = str(symbol or "").upper()
                    # Throttle aggressively to avoid log spam (regime computes per symbol per cycle).
                    if _symu not in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
                        raise RuntimeError("skip_symbol")
                    _last_map = globals().get("_AGENT_REGIME_LOG_LAST", {}) or {}
                    try:
                        _last_ts = int(_last_map.get(_symu, 0) or 0)
                    except Exception:
                        _last_ts = 0
                    if (_ts - _last_ts) < 60_000:
                        raise RuntimeError("throttled")
                    _last_map[_symu] = _ts
                    globals()["_AGENT_REGIME_LOG_LAST"] = _last_map
                    _payload = {
                        "sessionId": "53deb7",
                        "id": f"log_{_ts}_regime_cache_{symbol}",
                        "timestamp": _ts,
                        "location": "risk/market_regime.py:compute_regime_from_redis",
                        "message": "regime_cached",
                        "runId": "post-fix",
                        "hypothesisId": "H2",
                        "data": {
                            "symbol": str(symbol),
                            "ttl_sec": int(ttl),
                            "move_regime": regime.get("move_regime"),
                            "trend_direction": regime.get("trend_direction"),
                            "tf_alignment": regime.get("tf_alignment"),
                            "volatility_score": regime.get("volatility_score"),
                            "updated_ts_ms": regime.get("updated_ts_ms"),
                            "redis_host": None,
                            "redis_port": None,
                            "redis_db": None,
                            "redis_server_run_id": None,
                            "redis_server_tcp_port": None,
                            "post_setex_exists": None,
                            "post_setex_len": None,
                            "post_setex_ttl_sec": None,
                        },
                    }
                    try:
                        _ck = getattr(redis_client, "connection_pool", None)
                        _kw = getattr(_ck, "connection_kwargs", {}) or {}
                        _payload["data"]["redis_host"] = _kw.get("host")
                        _payload["data"]["redis_port"] = _kw.get("port")
                        _payload["data"]["redis_db"] = _kw.get("db")
                    except Exception:
                        pass
                    try:
                        _info = redis_client.info() if redis_client else {}
                        if isinstance(_info, dict):
                            _payload["data"]["redis_server_run_id"] = _info.get("run_id")
                            _payload["data"]["redis_server_tcp_port"] = _info.get("tcp_port")
                    except Exception:
                        pass
                    try:
                        _rk = f"regime:{symbol}"
                        _v = redis_client.get(_rk)
                        _payload["data"]["post_setex_exists"] = bool(_v)
                        _payload["data"]["post_setex_len"] = int(len(_v)) if isinstance(_v, str) else None
                        _payload["data"]["post_setex_ttl_sec"] = int(redis_client.ttl(_rk))
                    except Exception:
                        pass
                    with open(
                        "/home/wali/Desktop/AI BOT/.cursor/debug-53deb7.log",
                        "a",
                        encoding="utf-8",
                    ) as _f:
                        _f.write(json.dumps(_payload, separators=(",", ":")) + "\n")
                except Exception:
                    pass
                # endregion
            except Exception:
                pass

        # Also compute and cache per-TF regime for MTF Position Builder
        _h6_tf_regimes = {}
        try:
            if redis_client and features_by_tf:
                for tf, feat in features_by_tf.items():
                    if not feat:
                        continue
                    tf_regime = compute_regime(
                        symbol, {tf: feat},
                        tf_agg=None,
                        liq_long_strength=liq_long_strength,
                        liq_short_strength=liq_short_strength,
                        liq_distance_pct=liq_distance_pct,
                    )
                    if tf_regime:
                        tf_regime["timeframe"] = tf
                        redis_client.setex(
                            f"regime:{symbol}:{tf}",
                            ttl,
                            json.dumps(tf_regime, separators=(",", ":")),
                        )
                        _h6_tf_regimes[tf] = {"move_regime": tf_regime.get("move_regime"), "trend_direction": tf_regime.get("trend_direction"), "tf_alignment": tf_regime.get("tf_alignment"), "market_regime": tf_regime.get("market_regime")}
        except Exception:
            pass

        return regime
    except Exception as e:
        # Fail-open: log once and return empty dict
        logger.debug(f"[REGIME_COMPUTE_ERROR] {symbol}: {e}")
        return {}
