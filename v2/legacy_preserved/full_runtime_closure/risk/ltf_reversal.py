"""
Lower-TF Mean-Reversion & Exhaustion Scoring (LTFMR)

Provides two data-driven composite scores derived from 1m/5m/15m real-time data:

1. compute_ltf_reversal_score(symbol, direction, redis_client)
   → float [0, 1] indicating likelihood of a mean-reversion against `direction`.
   Used by hedge_manager_v3 to relax trainer veto and allow protective hedges.

2. compute_ltf_exhaustion_score(symbol, direction, redis_client)
   → float [0, 1] indicating the current move in `direction` is exhausted.
   Used by orchestrator_worker to pause/reduce INCREASE scaling.

All data is read from Redis live feeds. Graceful zero-contribution on missing data.
No trainer predictions are modified.
"""

import json
import logging

logger = logging.getLogger("ltf_reversal")

def _safe_float(val, default=0.0):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _get_msnap(redis_client, symbol: str) -> dict:
    try:
        return redis_client.hgetall(f"msnap:coinapi_wsds:{symbol}") or {}
    except Exception:
        return {}


def _get_uf(redis_client, symbol: str, tf: str) -> dict:
    try:
        return redis_client.hgetall(f"unified_features:{symbol}:{tf}") or {}
    except Exception:
        return {}


def _get_regime(redis_client, symbol: str) -> dict:
    try:
        raw = redis_client.get(f"regime:{symbol}")
        if raw:
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8", errors="ignore")
            return json.loads(raw)
    except Exception:
        pass
    return {}


def _rsi_reversal_signal(uf_1m: dict, uf_5m: dict, uf_15m: dict, direction: str) -> float:
    """RSI divergence across LTFs. Returns 0-1 reversal signal."""
    rsi_1m = _safe_float(uf_1m.get("ind_ta_RSI_14_1m"))
    rsi_5m = _safe_float(uf_5m.get("ind_ta_RSI_14_5m"))
    rsi_15m = _safe_float(uf_15m.get("ind_ta_RSI_14_15m"))
    xtf_1h_rsi = _safe_float(uf_5m.get("xtf_1h_rsi_14"))
    if rsi_1m == 0 and rsi_5m == 0:
        return 0.0

    score = 0.0
    if direction == "SHORT":
        # Move was SHORT → reversal = price bouncing UP → RSI climbing from oversold
        if rsi_1m > 0:
            if rsi_1m < 25:
                score += 0.4
            elif rsi_1m < 35:
                score += 0.2
        if rsi_5m > 0:
            if rsi_5m < 30:
                score += 0.3
            elif rsi_5m < 40:
                score += 0.15
        if rsi_15m > 0 and rsi_15m < 35:
            score += 0.2
        # 1m recovering faster than 1h = LTF divergence
        if rsi_1m > 0 and xtf_1h_rsi > 0 and rsi_1m > xtf_1h_rsi + 8:
            score += 0.1
    else:
        if rsi_1m > 0:
            if rsi_1m > 75:
                score += 0.4
            elif rsi_1m > 65:
                score += 0.2
        if rsi_5m > 0:
            if rsi_5m > 70:
                score += 0.3
            elif rsi_5m > 60:
                score += 0.15
        if rsi_15m > 0 and rsi_15m > 65:
            score += 0.2
        if rsi_1m > 0 and xtf_1h_rsi > 0 and rsi_1m < xtf_1h_rsi - 8:
            score += 0.1

    return min(1.0, score)


def _stochrsi_extreme_signal(uf_5m: dict, uf_15m: dict, direction: str) -> float:
    """StochRSI extreme reading → reversal signal."""
    k5 = "ind_ta_STOCHRSI_k_timeperiod14_fastk_period5_fastd_period3_fastd_matype0_5m"
    k15 = "ind_ta_STOCHRSI_k_timeperiod14_fastk_period5_fastd_period3_fastd_matype0_15m"
    srsi_5 = _safe_float(uf_5m.get(k5), -1)
    srsi_15 = _safe_float(uf_15m.get(k15), -1)

    score = 0.0
    if direction == "SHORT":
        if srsi_5 >= 0 and srsi_5 < 10:
            score += 0.5
        elif srsi_5 >= 0 and srsi_5 < 20:
            score += 0.25
        if srsi_15 >= 0 and srsi_15 < 15:
            score += 0.5
    else:
        if srsi_5 >= 0 and srsi_5 > 90:
            score += 0.5
        elif srsi_5 >= 0 and srsi_5 > 80:
            score += 0.25
        if srsi_15 >= 0 and srsi_15 > 85:
            score += 0.5

    return min(1.0, score)


def _cci_willr_signal(uf_1m: dict, uf_5m: dict, direction: str) -> float:
    """CCI and Williams %R extreme → reversal signal."""
    cci_1m = _safe_float(uf_1m.get("ind_ta_CCI_14_1m"))
    cci_5m = _safe_float(uf_5m.get("ind_ta_CCI_14_5m"))
    willr_5m = _safe_float(uf_5m.get("ind_ta_WILLR_14_5m"))

    score = 0.0
    if direction == "SHORT":
        if cci_1m < -150:
            score += 0.3
        elif cci_1m < -100:
            score += 0.15
        if cci_5m < -100:
            score += 0.2
        if willr_5m < -85:
            score += 0.3
        elif willr_5m < -75:
            score += 0.15
    else:
        if cci_1m > 150:
            score += 0.3
        elif cci_1m > 100:
            score += 0.15
        if cci_5m > 100:
            score += 0.2
        if willr_5m > -15:
            score += 0.3
        elif willr_5m > -25:
            score += 0.15

    return min(1.0, score)


def _orderbook_imbalance_signal(msnap: dict, direction: str) -> float:
    """CoinAPI orderbook imbalance opposing the move → reversal signal."""
    imb = _safe_float(msnap.get("imbalance_5"))
    bid_sum = _safe_float(msnap.get("book_bid_sum_5"))
    ask_sum = _safe_float(msnap.get("book_ask_sum_5"))

    score = 0.0
    if direction == "SHORT":
        # Buyers stepping in against downtrend
        if imb > 0.3:
            score += 0.5
        elif imb > 0.15:
            score += 0.25
        # Bids thickening relative to asks
        if bid_sum > 0 and ask_sum > 0:
            ratio = bid_sum / ask_sum
            if ratio > 1.5:
                score += 0.3
            elif ratio > 1.0:
                score += 0.1
    else:
        if imb < -0.3:
            score += 0.5
        elif imb < -0.15:
            score += 0.25
        if bid_sum > 0 and ask_sum > 0:
            ratio = ask_sum / bid_sum
            if ratio > 1.5:
                score += 0.3
            elif ratio > 1.0:
                score += 0.1

    return min(1.0, score)


def _price_ema_distance_signal(uf_5m: dict, msnap: dict, direction: str) -> float:
    """Price extended from EMA → snapback likely. Replaces BBANDS."""
    mid_px = _safe_float(msnap.get("mid_px"))
    ema20 = _safe_float(uf_5m.get("ind_ta_EMA_20_5m"))
    ema50 = _safe_float(uf_5m.get("ind_ta_EMA_50_5m"))
    if mid_px <= 0 or ema20 <= 0:
        return 0.0

    dist_20_pct = (mid_px - ema20) / ema20 * 100.0
    dist_50_pct = (mid_px - ema50) / ema50 * 100.0 if ema50 > 0 else 0.0

    score = 0.0
    if direction == "SHORT":
        # Price below EMA = extended short
        if dist_20_pct < -0.5:
            score += min(0.5, abs(dist_20_pct) / 2.0)
        if dist_50_pct < -0.3:
            score += min(0.3, abs(dist_50_pct) / 3.0)
    else:
        if dist_20_pct > 0.5:
            score += min(0.5, dist_20_pct / 2.0)
        if dist_50_pct > 0.3:
            score += min(0.3, dist_50_pct / 3.0)

    return min(1.0, score)


def _coinank_flow_signal(uf_5m: dict, direction: str) -> float:
    """CoinAnk order flow, L/S ratio, net positions → reversal signal.
    Graceful zero when data is missing (common for alt-coins)."""
    score = 0.0
    available = 0

    # Order flow bid/ask ratio
    of_bids = _safe_float(uf_5m.get("coinank_orderFlow_lists_data_0_bids_mean"))
    of_asks = _safe_float(uf_5m.get("coinank_orderFlow_lists_data_0_asks_mean"))
    if of_bids > 0 and of_asks > 0:
        available += 1
        ratio = of_bids / of_asks
        if direction == "SHORT" and ratio > 1.3:
            score += 0.5
        elif direction == "LONG" and ratio < 0.7:
            score += 0.5

    # L/S global ratio
    ls_ratio = _safe_float(uf_5m.get("coinank_ls_global_account_ratio_longShortRatio_first"))
    if ls_ratio > 0:
        available += 1
        if direction == "SHORT" and ls_ratio > 2.5:
            # Crowded longs during SHORT move → contrarian reversal
            score += 0.3
        elif direction == "LONG" and ls_ratio < 0.8:
            score += 0.3

    # Net positions
    nl = _safe_float(uf_5m.get("coinank_netPositions_getNetPositions_data_0_netLongsClose"))
    ns = _safe_float(uf_5m.get("coinank_netPositions_getNetPositions_data_0_netShortsClose"))
    if abs(nl) > 0 or abs(ns) > 0:
        available += 1
        if direction == "SHORT" and nl > 0 and abs(nl) > abs(ns) * 1.5:
            score += 0.2
        elif direction == "LONG" and ns < 0 and abs(ns) > abs(nl) * 1.5:
            score += 0.2

    if available == 0:
        return 0.0
    return min(1.0, score / max(1, available) * 2.0)


def _liquidation_proximity_signal(uf_5m: dict, direction: str) -> float:
    """Liquidation cluster proximity → potential cascade reversal."""
    if direction == "SHORT":
        dist = _safe_float(uf_5m.get("liquidation_long_distance_pct"), 999)
        strength = _safe_float(uf_5m.get("liquidation_long_strength"))
    else:
        dist = _safe_float(uf_5m.get("liquidation_short_distance_pct"), 999)
        strength = _safe_float(uf_5m.get("liquidation_short_strength"))

    if dist >= 999:
        return 0.0

    score = 0.0
    if dist < 0.15:
        score = 0.8
    elif dist < 0.3:
        score = 0.5
    elif dist < 0.5:
        score = 0.2

    if strength > 1_000_000:
        score = min(1.0, score * 1.3)

    return min(1.0, score)


def _funding_extreme_signal(uf_5m: dict, direction: str) -> float:
    """Extreme funding rate → contrarian reversal pressure."""
    fr = _safe_float(uf_5m.get("funding_rate"))
    coinank_fr = _safe_float(uf_5m.get("coinank_fundingRate_indicator_data_0_fundingRate"))
    effective_fr = coinank_fr if abs(coinank_fr) > abs(fr) else fr

    if abs(effective_fr) < 1e-8:
        return 0.0

    score = 0.0
    if direction == "SHORT" and effective_fr < -0.0004:
        score = min(1.0, abs(effective_fr) / 0.001)
    elif direction == "LONG" and effective_fr > 0.0004:
        score = min(1.0, effective_fr / 0.001)

    return min(1.0, score)


def _aroon_reversal_signal(uf_1m: dict, uf_5m: dict, direction: str) -> float:
    """AROON crossover on LTFs → reversal signal."""
    up_1m = _safe_float(uf_1m.get("ind_ta_AROON_up_14_1m"))
    dn_1m = _safe_float(uf_1m.get("ind_ta_AROON_down_14_1m"))
    up_5m = _safe_float(uf_5m.get("ind_ta_AROON_up_14_5m"))
    dn_5m = _safe_float(uf_5m.get("ind_ta_AROON_down_14_5m"))

    score = 0.0
    if direction == "SHORT":
        if up_1m > dn_1m + 20:
            score += 0.4
        if up_5m > dn_5m + 15:
            score += 0.3
    else:
        if dn_1m > up_1m + 20:
            score += 0.4
        if dn_5m > up_5m + 15:
            score += 0.3

    return min(1.0, score)


def compute_ltf_reversal_score_fast(
    symbol: str,
    direction: str,
    redis_client,
) -> tuple:
    """
    Orderbook-only reversal score for fast (sub-minute) reaction.
    Uses only msnap — no candle-based data. For use when protective hedge
    needs to open during a fast reversal before RSI/CCI etc. have updated.

    Returns:
        (score: float [0,1], components: dict)
    """
    direction = str(direction).upper()
    if direction not in ("LONG", "SHORT"):
        return 0.0, {}

    msnap = _get_msnap(redis_client, symbol)
    c_ob = _orderbook_imbalance_signal(msnap, direction)

    # Microprice skew: microprice > mid_px = buying pressure
    mid_px = _safe_float(msnap.get("mid_px"))
    microprice = _safe_float(msnap.get("microprice"))
    skew = 0.0
    if mid_px > 0 and microprice > 0:
        skew_pct = (microprice - mid_px) / mid_px * 100.0
        if direction == "SHORT" and skew_pct > 0.02:
            skew = min(0.5, skew_pct * 5.0)
        elif direction == "LONG" and skew_pct < -0.02:
            skew = min(0.5, abs(skew_pct) * 5.0)

    # p_false_move high = prior move may be fake, reversal likely
    p_false = _safe_float(msnap.get("p_false_move"))
    c_false = min(0.3, p_false * 2.0) if p_false > 0.1 else 0.0

    # snapback_score: snapback in progress → reversal signal
    snapback = _safe_float(msnap.get("snapback_score"))
    c_snap = min(0.25, snapback * 0.5) if snapback > 0.1 else 0.0

    # Trade flow (when COINAPI_ALLOW_TRADE=true): leading signal, often flips before orderbook
    buy_n = _safe_float(msnap.get("trade_buy_notional_5s", msnap.get("trade_buy_notional_1s", 0)))
    sell_n = _safe_float(msnap.get("trade_sell_notional_5s", msnap.get("trade_sell_notional_1s", 0)))
    c_trade = 0.0
    if buy_n > 0 or sell_n > 0:
        total = buy_n + sell_n
        if total > 0:
            imb = (buy_n - sell_n) / total
            if direction == "SHORT" and imb > 0.2:
                c_trade = min(0.25, imb * 0.8)
            elif direction == "LONG" and imb < -0.2:
                c_trade = min(0.25, abs(imb) * 0.8)

    components = {k: round(v, 4) for k, v in [("orderbook", c_ob), ("microprice_skew", skew), ("p_false_move", c_false), ("snapback", c_snap), ("trade_flow", c_trade)]}
    composite = c_ob * 0.55 + skew * 0.22 + c_false * 0.10 + c_snap * 0.05 + c_trade * 0.08
    composite = max(0.0, min(1.0, composite))


    return composite, components


def compute_ltf_reversal_score(
    symbol: str,
    direction: str,
    redis_client,
) -> tuple:
    """
    Compute composite lower-TF mean-reversion score.

    Args:
        symbol: Trading pair (e.g. "ETHUSDT")
        direction: Current move direction ("LONG" or "SHORT") that we're checking reversal against
        redis_client: Redis connection

    Returns:
        (score: float [0,1], components: dict) — score >= 0.55 suggests a mean-reversion is likely.
    """
    direction = str(direction).upper()
    if direction not in ("LONG", "SHORT"):
        return 0.0, {}

    msnap = _get_msnap(redis_client, symbol)
    uf_1m = _get_uf(redis_client, symbol, "1m")
    uf_5m = _get_uf(redis_client, symbol, "5m")
    uf_15m = _get_uf(redis_client, symbol, "15m")

    c_rsi = _rsi_reversal_signal(uf_1m, uf_5m, uf_15m, direction)
    c_srsi = _stochrsi_extreme_signal(uf_5m, uf_15m, direction)
    c_cci_willr = _cci_willr_signal(uf_1m, uf_5m, direction)
    c_ob = _orderbook_imbalance_signal(msnap, direction)
    c_ema = _price_ema_distance_signal(uf_5m, msnap, direction)
    c_flow = _coinank_flow_signal(uf_5m, direction)
    c_liq = _liquidation_proximity_signal(uf_5m, direction)
    c_fund = _funding_extreme_signal(uf_5m, direction)
    c_aroon = _aroon_reversal_signal(uf_1m, uf_5m, direction)

    # Bonus: snapback_score and p_false_move (non-zero is rare but significant)
    snapback = _safe_float(msnap.get("snapback_score"))
    p_false = _safe_float(msnap.get("p_false_move"))
    c_bonus = 0.0
    if snapback > 0.1:
        c_bonus += min(0.3, snapback * 0.5)
    if p_false > 0.1:
        c_bonus += min(0.2, p_false * 0.5)

    weights = {
        "rsi": 0.18,
        "stochrsi": 0.10,
        "cci_willr": 0.12,
        "orderbook": 0.18,
        "ema_dist": 0.10,
        "flow": 0.10,
        "liquidation": 0.08,
        "funding": 0.05,
        "aroon": 0.05,
        "bonus": 0.04,
    }

    components = {
        "rsi": round(c_rsi, 4),
        "stochrsi": round(c_srsi, 4),
        "cci_willr": round(c_cci_willr, 4),
        "orderbook": round(c_ob, 4),
        "ema_dist": round(c_ema, 4),
        "flow": round(c_flow, 4),
        "liquidation": round(c_liq, 4),
        "funding": round(c_fund, 4),
        "aroon": round(c_aroon, 4),
        "bonus": round(c_bonus, 4),
    }

    composite = sum(weights[k] * components[k] for k in weights)
    composite = max(0.0, min(1.0, composite))


    return composite, components


# ─────────────────────────────────────────────────────────────────────────────
# Fix 2: Exhaustion Score
# ─────────────────────────────────────────────────────────────────────────────

def _adx_declining_signal(uf_5m: dict, uf_15m: dict) -> float:
    """Declining ADX → trend losing steam."""
    adx_5m = _safe_float(uf_5m.get("ind_ta_ADX_14_5m"))
    adx_15m = _safe_float(uf_15m.get("ind_ta_ADX_14_15m"))
    adx_21_5m = _safe_float(uf_5m.get("ind_ta_ADX_21_5m"))

    score = 0.0
    # ADX below 20 = no trend
    if 0 < adx_5m < 20:
        score += 0.4
    elif 0 < adx_5m < 25:
        score += 0.2
    # ADX_14 < ADX_21 = declining momentum
    if adx_5m > 0 and adx_21_5m > 0 and adx_5m < adx_21_5m:
        score += 0.3

    if 0 < adx_15m < 22:
        score += 0.2

    return min(1.0, score)


def _fast_move_declining_signal(msnap: dict) -> float:
    """fast_move_score declining from peak → move exhaustion."""
    fms = _safe_float(msnap.get("fast_move_score"))
    fms_1m = _safe_float(msnap.get("fast_move_max_1m"))

    if fms_1m <= 0:
        return 0.0

    # Ratio of current to recent peak
    if fms_1m > 0:
        ratio = fms / fms_1m if fms_1m > 0 else 1.0
        if ratio < 0.3:
            return 0.8
        elif ratio < 0.5:
            return 0.5
        elif ratio < 0.7:
            return 0.2
    return 0.0


def _depth_thinning_signal(msnap: dict, direction: str) -> float:
    """Orderbook thinning in move direction → liquidity drying up."""
    bid_usd = _safe_float(msnap.get("depth_bps_10_bid_usd"))
    ask_usd = _safe_float(msnap.get("depth_bps_10_ask_usd"))

    if bid_usd <= 0 and ask_usd <= 0:
        return 0.0

    score = 0.0
    if direction == "SHORT" and bid_usd > 0 and ask_usd > 0:
        # Move is SHORT → bids thinning means sellers running out of buyers to hit
        if bid_usd < ask_usd * 0.3:
            score = 0.6
        elif bid_usd < ask_usd * 0.5:
            score = 0.3
    elif direction == "LONG" and bid_usd > 0 and ask_usd > 0:
        if ask_usd < bid_usd * 0.3:
            score = 0.6
        elif ask_usd < bid_usd * 0.5:
            score = 0.3

    return min(1.0, score)


def _churn_rising_signal(msnap: dict) -> float:
    """Rising churn_score → lots of activity but no price progress."""
    churn = _safe_float(msnap.get("churn_score"))
    if churn > 0.15:
        return min(1.0, (churn - 0.08) / 0.15)
    elif churn > 0.08:
        return 0.3
    return 0.0


def _cci_willr_extreme_signal(uf_1m: dict, uf_5m: dict, direction: str) -> float:
    """CCI/WILLR at extremes in move direction → exhaustion."""
    cci_5m = _safe_float(uf_5m.get("ind_ta_CCI_14_5m"))
    willr_5m = _safe_float(uf_5m.get("ind_ta_WILLR_14_5m"))

    score = 0.0
    if direction == "SHORT":
        if cci_5m < -150:
            score += 0.4
        elif cci_5m < -100:
            score += 0.2
        if willr_5m < -85:
            score += 0.4
    else:
        if cci_5m > 150:
            score += 0.4
        elif cci_5m > 100:
            score += 0.2
        if willr_5m > -15:
            score += 0.4

    return min(1.0, score)


def _ema_overextension_signal(uf_5m: dict, uf_15m: dict, msnap: dict, direction: str) -> float:
    """Price way beyond EMA → overextended, likely snapback."""
    mid_px = _safe_float(msnap.get("mid_px"))
    ema20_5m = _safe_float(uf_5m.get("ind_ta_EMA_20_5m"))
    ema20_15m = _safe_float(uf_15m.get("ind_ta_EMA_20_15m"))

    if mid_px <= 0:
        return 0.0

    score = 0.0
    if ema20_5m > 0:
        d = (mid_px - ema20_5m) / ema20_5m * 100.0
        if direction == "LONG" and d > 0.8:
            score += min(0.5, d / 2.0)
        elif direction == "SHORT" and d < -0.8:
            score += min(0.5, abs(d) / 2.0)

    if ema20_15m > 0:
        d15 = (mid_px - ema20_15m) / ema20_15m * 100.0
        if direction == "LONG" and d15 > 0.5:
            score += min(0.3, d15 / 3.0)
        elif direction == "SHORT" and d15 < -0.5:
            score += min(0.3, abs(d15) / 3.0)

    return min(1.0, score)


def _oi_volume_declining_signal(uf_5m: dict) -> float:
    """Declining OI or volume → move losing participation."""
    oi_close = _safe_float(uf_5m.get("coinank_openInterest_kline_data_0_close"))
    oi_open = _safe_float(uf_5m.get("coinank_openInterest_kline_data_0_open"))

    score = 0.0
    if oi_close > 0 and oi_open > 0:
        if oi_close < oi_open * 0.98:
            score += 0.5
        elif oi_close < oi_open * 0.995:
            score += 0.2

    return min(1.0, score)


def compute_ltf_exhaustion_score(
    symbol: str,
    direction: str,
    redis_client,
) -> tuple:
    """
    Compute composite exhaustion score for a move in `direction`.

    Args:
        symbol: Trading pair
        direction: Direction of the current move ("LONG" or "SHORT")
        redis_client: Redis connection

    Returns:
        (score: float [0,1], components: dict) — score >= 0.50 → scaling should be paused/reduced.
    """
    direction = str(direction).upper()
    if direction not in ("LONG", "SHORT"):
        return 0.0, {}

    msnap = _get_msnap(redis_client, symbol)
    uf_1m = _get_uf(redis_client, symbol, "1m")
    uf_5m = _get_uf(redis_client, symbol, "5m")
    uf_15m = _get_uf(redis_client, symbol, "15m")

    c_adx = _adx_declining_signal(uf_5m, uf_15m)
    c_fms = _fast_move_declining_signal(msnap)
    c_depth = _depth_thinning_signal(msnap, direction)
    c_churn = _churn_rising_signal(msnap)
    c_cci_willr = _cci_willr_extreme_signal(uf_1m, uf_5m, direction)
    c_ema = _ema_overextension_signal(uf_5m, uf_15m, msnap, direction)
    c_oi = _oi_volume_declining_signal(uf_5m)

    weights = {
        "adx": 0.20,
        "fast_move": 0.15,
        "depth": 0.15,
        "churn": 0.10,
        "cci_willr": 0.15,
        "ema_ext": 0.15,
        "oi_vol": 0.10,
    }

    components = {
        "adx": round(c_adx, 4),
        "fast_move": round(c_fms, 4),
        "depth": round(c_depth, 4),
        "churn": round(c_churn, 4),
        "cci_willr": round(c_cci_willr, 4),
        "ema_ext": round(c_ema, 4),
        "oi_vol": round(c_oi, 4),
    }

    composite = sum(weights[k] * components[k] for k in weights)
    composite = max(0.0, min(1.0, composite))


    return composite, components
