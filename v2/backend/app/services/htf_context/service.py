"""Higher-timeframe and cross-asset decision context from closed candles.

Phase 4 of goal V2_A_PLUS_LIVE_READY_TRAINER_EDGE_REPAIR_AND_ZERO_TOLERANCE_TRADE_GATE.

Reads only closed Binance klines already ingested into V2 Redis
(``v2:market:ohlcv:binance:{symbol}:{tf}``). 1D context is derived from 4h
closed candles aligned to UTC midnight, so no new exchange endpoints or API
keys are required. Public market data only; never mutates exchange state.

Contract:
    build_htf_context(symbol, klines_4h)      -> >= 20 HTF fields
    build_cross_asset_context(btc_1h, btc_4h, eth_4h) -> BTC/ETH market regime context
    multi_timeframe_alignment_score(...)      -> [-1, +1] alignment for a side
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

HTF_CONTEXT_REDIS_KEY_TEMPLATE = "v2:context:htf:{symbol}"
CROSS_ASSET_CONTEXT_REDIS_KEY = "v2:context:cross_asset"
SCHEMA_VERSION = "v2_htf_context_v1"

FOUR_HOURS_MS = 4 * 3600 * 1000
ONE_DAY_MS = 24 * 3600 * 1000


def _finite(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _parse_klines(rows: Sequence[Any]) -> list[dict[str, float]]:
    """Accept Binance kline arrays or dict rows; return closed candles ascending."""
    parsed: list[dict[str, float]] = []
    for row in rows or ():
        if isinstance(row, (list, tuple)) and len(row) >= 11:
            open_time = _finite(row[0])
            values = [_finite(v) for v in (row[1], row[2], row[3], row[4], row[5], row[7], row[9])]
            close_time = _finite(row[6])
            if open_time is None or close_time is None or any(v is None for v in values):
                continue
            o, h, l, c, vol, quote_vol, taker_buy = values  # noqa: E741
            parsed.append(
                {
                    "open_time": open_time,
                    "close_time": close_time,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": vol,
                    "quote_volume": quote_vol,
                    "taker_buy_volume": taker_buy,
                }
            )
        elif isinstance(row, Mapping):
            o = _finite(row.get("open"))
            h = _finite(row.get("high"))
            l = _finite(row.get("low"))  # noqa: E741
            c = _finite(row.get("close"))
            open_time = _finite(row.get("open_time") or row.get("openTime"))
            close_time = _finite(row.get("close_time") or row.get("closeTime"))
            if None in (o, h, l, c, open_time, close_time):
                continue
            parsed.append(
                {
                    "open_time": open_time,
                    "close_time": close_time,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": _finite(row.get("volume")) or 0.0,
                    "quote_volume": _finite(row.get("quote_volume") or row.get("quoteVolume")) or 0.0,
                    "taker_buy_volume": _finite(row.get("taker_buy_volume")) or 0.0,
                }
            )
    parsed.sort(key=lambda item: item["open_time"])
    return parsed


def derive_daily_candles(klines_4h: Sequence[Any]) -> list[dict[str, float]]:
    """Aggregate 4h closed candles into UTC-midnight-aligned 1D candles."""
    rows = _parse_klines(klines_4h)
    days: dict[int, dict[str, float]] = {}
    for row in rows:
        day_start = int(row["open_time"] // ONE_DAY_MS) * ONE_DAY_MS
        bucket = days.get(day_start)
        if bucket is None:
            days[day_start] = {
                "open_time": float(day_start),
                "close_time": float(day_start + ONE_DAY_MS - 1),
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "quote_volume": row["quote_volume"],
                "taker_buy_volume": row["taker_buy_volume"],
                "_segments": 1.0,
                "_last_open_time": row["open_time"],
            }
        else:
            bucket["high"] = max(bucket["high"], row["high"])
            bucket["low"] = min(bucket["low"], row["low"])
            if row["open_time"] > bucket["_last_open_time"]:
                bucket["close"] = row["close"]
                bucket["_last_open_time"] = row["open_time"]
            bucket["volume"] += row["volume"]
            bucket["quote_volume"] += row["quote_volume"]
            bucket["taker_buy_volume"] += row["taker_buy_volume"]
            bucket["_segments"] += 1.0
    complete = [
        {key: value for key, value in bucket.items() if not key.startswith("_")}
        for bucket in days.values()
        if bucket["_segments"] >= 6.0  # only fully-covered days
    ]
    complete.sort(key=lambda item: item["open_time"])
    return complete


def _ema(values: Sequence[float], period: int) -> float | None:
    if len(values) < period:
        return None
    multiplier = 2.0 / (period + 1.0)
    ema = sum(values[:period]) / period
    for value in values[period:]:
        ema = (value - ema) * multiplier + ema
    return ema


def _ema_series(values: Sequence[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    multiplier = 2.0 / (period + 1.0)
    ema = sum(values[:period]) / period
    series = [ema]
    for value in values[period:]:
        ema = (value - ema) * multiplier + ema
        series.append(ema)
    return series


def _rsi(values: Sequence[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values[:-1], values[1:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for gain, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def _rsi_zone(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value >= 70.0:
        return "OVERBOUGHT"
    if value >= 55.0:
        return "BULLISH"
    if value > 45.0:
        return "NEUTRAL"
    if value > 30.0:
        return "BEARISH"
    return "OVERSOLD"


def _macd_state(values: Sequence[float]) -> tuple[str, float | None, float | None]:
    if len(values) < 35:
        return "UNKNOWN", None, None
    fast = _ema_series(values, 12)
    slow = _ema_series(values, 26)
    if not fast or not slow:
        return "UNKNOWN", None, None
    offset = len(fast) - len(slow)
    macd_line = [fast[index + offset] - slow[index] for index in range(len(slow))]
    signal_series = _ema_series(macd_line, 9)
    if not signal_series:
        return "UNKNOWN", None, None
    macd_value = macd_line[-1]
    signal_value = signal_series[-1]
    histogram = macd_value - signal_value
    prev_histogram = (
        macd_line[-2] - signal_series[-2] if len(macd_line) >= 2 and len(signal_series) >= 2 else histogram
    )
    if histogram > 0:
        state = "BULLISH_EXPANDING" if histogram >= prev_histogram else "BULLISH_FADING"
    elif histogram < 0:
        state = "BEARISH_EXPANDING" if histogram <= prev_histogram else "BEARISH_FADING"
    else:
        state = "FLAT"
    return state, macd_value, histogram


def _support_resistance_distance_bps(rows: Sequence[Mapping[str, float]], lookback: int) -> tuple[float | None, float | None]:
    """Distance (bps) from last close to nearest swing support below / resistance above."""
    window = list(rows)[-lookback:]
    if len(window) < 5:
        return None, None
    close = window[-1]["close"]
    if close <= 0:
        return None, None
    pivots_high: list[float] = []
    pivots_low: list[float] = []
    for index in range(2, len(window) - 2):
        high = window[index]["high"]
        low = window[index]["low"]
        if high >= max(window[index - 2]["high"], window[index - 1]["high"], window[index + 1]["high"], window[index + 2]["high"]):
            pivots_high.append(high)
        if low <= min(window[index - 2]["low"], window[index - 1]["low"], window[index + 1]["low"], window[index + 2]["low"]):
            pivots_low.append(low)
    resistance_candidates = [p for p in pivots_high if p > close]
    support_candidates = [p for p in pivots_low if p < close]
    resistance = min(resistance_candidates) if resistance_candidates else None
    support = max(support_candidates) if support_candidates else None
    resistance_bps = ((resistance - close) / close * 10_000.0) if resistance else None
    support_bps = ((close - support) / close * 10_000.0) if support else None
    return support_bps, resistance_bps


def _volume_profile_poc_distance_bps(rows: Sequence[Mapping[str, float]], buckets: int = 24) -> float | None:
    """Distance (bps) from last close to the highest-volume price bucket (POC)."""
    window = list(rows)
    if len(window) < 10:
        return None
    lows = [row["low"] for row in window]
    highs = [row["high"] for row in window]
    low, high = min(lows), max(highs)
    close = window[-1]["close"]
    if high <= low or close <= 0:
        return None
    bucket_size = (high - low) / buckets
    volume_by_bucket = [0.0] * buckets
    for row in window:
        mid = (row["high"] + row["low"]) / 2.0
        index = min(buckets - 1, max(0, int((mid - low) / bucket_size)))
        volume_by_bucket[index] += row.get("quote_volume") or row.get("volume") or 0.0
    poc_index = max(range(buckets), key=lambda i: volume_by_bucket[i])
    poc_price = low + (poc_index + 0.5) * bucket_size
    return (poc_price - close) / close * 10_000.0


def _direction(values: Sequence[float], period: int = 20) -> str:
    ema_series = _ema_series(list(values), period)
    if len(ema_series) < 3:
        return "UNKNOWN"
    if ema_series[-1] > ema_series[-2] > ema_series[-3]:
        return "UP"
    if ema_series[-1] < ema_series[-2] < ema_series[-3]:
        return "DOWN"
    return "FLAT"


def build_htf_context(symbol: str, klines_4h: Sequence[Any]) -> dict[str, Any]:
    """Compute the Phase 4 HTF feature set from 4h closed candles (>= 20 fields)."""
    rows_4h = _parse_klines(klines_4h)
    rows_1d = derive_daily_candles(klines_4h)
    closes_4h = [row["close"] for row in rows_4h]
    closes_1d = [row["close"] for row in rows_1d]

    ema50_4h = _ema(closes_4h, 50)
    close_4h = closes_4h[-1] if closes_4h else None
    ema50_delta_pct_4h = (
        (close_4h - ema50_4h) / ema50_4h * 100.0 if close_4h is not None and ema50_4h not in (None, 0.0) else None
    )
    rsi_4h = _rsi(closes_4h)
    macd_state_4h, macd_value_4h, macd_hist_4h = _macd_state(closes_4h)
    rsi_1d = _rsi(closes_1d)
    ema_direction_1d = _direction(closes_1d, 20)
    support_4h_bps, resistance_4h_bps = _support_resistance_distance_bps(rows_4h, lookback=60)
    support_1d_bps, resistance_1d_bps = _support_resistance_distance_bps(rows_1d, lookback=30)
    poc_distance_bps = _volume_profile_poc_distance_bps(rows_4h[-60:] if len(rows_4h) > 60 else rows_4h)

    ema20_4h = _ema(closes_4h, 20)
    trend_4h = (
        "UP"
        if close_4h is not None and ema20_4h is not None and ema50_4h is not None and close_4h > ema20_4h > ema50_4h
        else "DOWN"
        if close_4h is not None and ema20_4h is not None and ema50_4h is not None and close_4h < ema20_4h < ema50_4h
        else "MIXED"
        if None not in (close_4h, ema20_4h, ema50_4h)
        else "UNKNOWN"
    )
    ret_1d_pct = (
        (closes_1d[-1] - closes_1d[-2]) / closes_1d[-2] * 100.0 if len(closes_1d) >= 2 and closes_1d[-2] != 0 else None
    )
    ret_4h_pct = (
        (closes_4h[-1] - closes_4h[-2]) / closes_4h[-2] * 100.0 if len(closes_4h) >= 2 and closes_4h[-2] != 0 else None
    )
    realized_vol_1d_pct = None
    if len(closes_1d) >= 15:
        returns = [
            math.log(current / previous)
            for previous, current in zip(closes_1d[-15:-1], closes_1d[-14:])
            if previous > 0 and current > 0
        ]
        if len(returns) >= 5:
            mean = sum(returns) / len(returns)
            variance = sum((value - mean) ** 2 for value in returns) / len(returns)
            realized_vol_1d_pct = math.sqrt(variance) * 100.0

    context = {
        "schema_version": SCHEMA_VERSION,
        "symbol": symbol.upper(),
        "candles_4h_used": len(rows_4h),
        "candles_1d_derived": len(rows_1d),
        "htf_4h_close": close_4h,
        "htf_4h_ema50": ema50_4h,
        "htf_4h_ema50_delta_pct": ema50_delta_pct_4h,
        "htf_4h_ema20": ema20_4h,
        "htf_4h_trend": trend_4h,
        "htf_4h_ret_pct": ret_4h_pct,
        "htf_4h_rsi_14": rsi_4h,
        "htf_4h_rsi_zone": _rsi_zone(rsi_4h),
        "htf_4h_macd_state": macd_state_4h,
        "htf_4h_macd_value": macd_value_4h,
        "htf_4h_macd_hist": macd_hist_4h,
        "htf_4h_support_distance_bps": support_4h_bps,
        "htf_4h_resistance_distance_bps": resistance_4h_bps,
        "htf_1d_close": closes_1d[-1] if closes_1d else None,
        "htf_1d_ema_direction": ema_direction_1d,
        "htf_1d_ret_pct": ret_1d_pct,
        "htf_1d_rsi_14": rsi_1d,
        "htf_1d_rsi_zone": _rsi_zone(rsi_1d),
        "htf_1d_support_distance_bps": support_1d_bps,
        "htf_1d_resistance_distance_bps": resistance_1d_bps,
        "htf_1d_realized_vol_pct": realized_vol_1d_pct,
        "htf_volume_poc_distance_bps": poc_distance_bps,
        "places_real_order": False,
        "writes_legacy_redis": False,
    }
    feature_fields = [key for key in context if key.startswith("htf_")]
    context["htf_feature_count"] = len(feature_fields)
    return context


def build_cross_asset_context(
    *,
    btc_klines_1h: Sequence[Any],
    btc_klines_4h: Sequence[Any],
    eth_klines_4h: Sequence[Any],
) -> dict[str, Any]:
    """BTC/ETH market-regime context shared by every symbol decision."""
    btc_1h = _parse_klines(btc_klines_1h)
    btc_4h = _parse_klines(btc_klines_4h)
    eth_4h = _parse_klines(eth_klines_4h)
    btc_1h_closes = [row["close"] for row in btc_1h]
    btc_4h_closes = [row["close"] for row in btc_4h]
    eth_4h_closes = [row["close"] for row in eth_4h]

    btc_direction_1h = _direction(btc_1h_closes, 20)
    btc_direction_4h = _direction(btc_4h_closes, 20)
    btc_rsi_4h = _rsi(btc_4h_closes)

    eth_btc_ratio: list[float] = []
    for btc_row, eth_row in zip(btc_4h[-40:], eth_4h[-40:]):
        if btc_row["close"] > 0:
            eth_btc_ratio.append(eth_row["close"] / btc_row["close"])
    eth_btc_direction = _direction(eth_btc_ratio, 10) if len(eth_btc_ratio) >= 13 else "UNKNOWN"

    # Risk-off proxy: BTC falling on both windows while ETH/BTC also falls
    # (alts bleeding into BTC weakness) marks a market-wide risk-off state.
    risk_off = btc_direction_4h == "DOWN" and btc_direction_1h == "DOWN"
    if risk_off and eth_btc_direction == "DOWN":
        market_risk_state = "RISK_OFF_BROAD"
    elif risk_off:
        market_risk_state = "RISK_OFF_BTC_LED"
    elif btc_direction_4h == "UP" and eth_btc_direction == "UP":
        market_risk_state = "RISK_ON_ALT_EXPANSION"
    elif btc_direction_4h == "UP":
        market_risk_state = "RISK_ON_BTC_LED"
    else:
        market_risk_state = "MIXED"

    btc_ret_4h_pct = (
        (btc_4h_closes[-1] - btc_4h_closes[-2]) / btc_4h_closes[-2] * 100.0
        if len(btc_4h_closes) >= 2 and btc_4h_closes[-2] != 0
        else None
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "context_type": "CROSS_ASSET",
        "btc_direction_1h": btc_direction_1h,
        "btc_direction_4h": btc_direction_4h,
        "btc_rsi_4h": btc_rsi_4h,
        "btc_rsi_zone_4h": _rsi_zone(btc_rsi_4h),
        "btc_ret_4h_pct": btc_ret_4h_pct,
        "eth_btc_direction_4h": eth_btc_direction,
        "market_risk_state": market_risk_state,
        "risk_off_proxy": bool(risk_off),
        "places_real_order": False,
        "writes_legacy_redis": False,
    }


def multi_timeframe_alignment_score(
    *,
    side: str,
    entry_timeframe_trend: str | None,
    htf_context: Mapping[str, Any],
    cross_asset: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Alignment in [-1, +1] between the proposed side and HTF/cross-asset context."""
    normalized = side.strip().lower()
    if normalized not in {"long", "short"}:
        return {"alignment_score": None, "aligned": False, "components": {}, "reason": f"UNKNOWN_SIDE:{side}"}
    want_up = normalized == "long"

    def _vote(direction: Any) -> float:
        text = str(direction or "").upper()
        if text in {"UP", "BULLISH", "BULLISH_EXPANDING", "RISING"}:
            return 1.0 if want_up else -1.0
        if text in {"DOWN", "BEARISH", "BEARISH_EXPANDING", "FALLING"}:
            return -1.0 if want_up else 1.0
        if text in {"BULLISH_FADING"}:
            return 0.3 if want_up else -0.3
        if text in {"BEARISH_FADING"}:
            return -0.3 if want_up else 0.3
        return 0.0

    components: dict[str, float] = {
        "entry_tf_trend": _vote(entry_timeframe_trend),
        "htf_4h_trend": _vote(htf_context.get("htf_4h_trend")),
        "htf_4h_macd": _vote(htf_context.get("htf_4h_macd_state")),
        "htf_1d_ema": _vote(htf_context.get("htf_1d_ema_direction")),
    }
    rsi_zone_4h = str(htf_context.get("htf_4h_rsi_zone") or "")
    if rsi_zone_4h == "OVERBOUGHT":
        components["htf_4h_rsi"] = -0.5 if want_up else 0.5
    elif rsi_zone_4h == "OVERSOLD":
        components["htf_4h_rsi"] = 0.5 if want_up else -0.5
    else:
        components["htf_4h_rsi"] = _vote(rsi_zone_4h)
    if cross_asset:
        components["btc_4h"] = 0.5 * _vote(cross_asset.get("btc_direction_4h"))
        if cross_asset.get("risk_off_proxy") is True and want_up:
            components["risk_off_penalty"] = -0.75
    weight_total = sum(abs(value) if value != 0 else 1.0 for value in components.values())
    score = sum(components.values()) / weight_total if weight_total > 0 else 0.0
    score = max(-1.0, min(1.0, score))
    return {
        "alignment_score": score,
        "aligned": score >= 0.25,
        "strongly_aligned": score >= 0.5,
        "misaligned": score <= -0.25,
        "components": components,
        "side": normalized,
    }
