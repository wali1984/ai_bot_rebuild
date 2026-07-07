"""Trade tape / order flow features from free Binance USD-M aggTrades.

Public market data only. This module never places, cancels, or modifies
exchange orders, never changes leverage or margin mode, and never writes
legacy Redis keys.

Feature contract (goal V2_A_PLUS_LIVE_READY_TRAINER_EDGE_REPAIR_AND_ZERO_TOLERANCE_TRADE_GATE,
Phase 5):
    taker_buy_pct_1m
    delta_1m
    cumulative_delta_trend_5m
    large_trade_flag
    aggressive_buy_volume
    aggressive_sell_volume
    volume_acceleration
    trade_tape_confirmation_score
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any, Mapping, Sequence

BINANCE_FAPI_AGG_TRADES_URL = "https://fapi.binance.com/fapi/v1/aggTrades"
AGG_TRADES_REDIS_KEY_TEMPLATE = "v2:market:agg_trades:{symbol}"
TRADE_TAPE_FEATURES_REDIS_KEY_TEMPLATE = "v2:market:trade_tape_features:{symbol}"
SCHEMA_VERSION = "v2_trade_tape_features_v1"

# A single aggTrades request carries request weight 20 on Binance USD-M.
# Callers must budget symbol count per cycle against the 2400/min IP cap.
AGG_TRADES_REQUEST_WEIGHT = 20

LARGE_TRADE_NOTIONAL_MULTIPLIER = 4.0
MIN_TRADES_FOR_CONFIRMATION = 20
ONE_MINUTE_MS = 60_000
FIVE_MINUTES_MS = 5 * ONE_MINUTE_MS


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


def fetch_binance_agg_trades(
    symbol: str,
    *,
    limit: int = 1000,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """Fetch recent aggregated trades from the free public fapi endpoint.

    Returns rows shaped like Binance's payload:
    {"a": aggId, "p": price, "q": qty, "f": first, "l": last, "T": ms, "m": buyer_is_maker}
    """
    params = urllib.parse.urlencode({"symbol": symbol.upper(), "limit": max(1, min(int(limit), 1000))})
    request = urllib.request.Request(
        f"{BINANCE_FAPI_AGG_TRADES_URL}?{params}",
        method="GET",
        headers={"User-Agent": "ai-bot-v2-trade-tape-ingestor"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"unexpected_agg_trades_payload_type:{type(payload).__name__}")
    return [row for row in payload if isinstance(row, dict)]


def _trade_fields(trade: Mapping[str, Any]) -> tuple[float, float, int, bool] | None:
    price = _finite(trade.get("p") or trade.get("price"))
    qty = _finite(trade.get("q") or trade.get("qty") or trade.get("quantity"))
    ts = trade.get("T") or trade.get("timestamp") or trade.get("time")
    try:
        ts_ms = int(ts)
    except (TypeError, ValueError):
        return None
    maker = trade.get("m")
    if maker is None:
        maker = trade.get("is_buyer_maker")
    if price is None or qty is None or price <= 0 or qty <= 0 or maker is None:
        return None
    # Binance semantics: m=True means the BUYER was the maker, i.e. the
    # aggressor was a SELLER. Aggressive buy = m False.
    return price, qty, ts_ms, bool(maker)


def compute_trade_tape_features(
    trades: Sequence[Mapping[str, Any]],
    *,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Pure computation of the Phase 5 tape features from aggTrades rows."""
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    parsed: list[tuple[float, float, int, bool]] = []
    for trade in trades:
        if not isinstance(trade, Mapping):
            continue
        fields = _trade_fields(trade)
        if fields is not None:
            parsed.append(fields)
    parsed.sort(key=lambda row: row[2])

    aggressive_buy_volume = 0.0
    aggressive_sell_volume = 0.0
    notionals: list[float] = []
    minute_delta: dict[int, float] = {}
    minute_volume: dict[int, float] = {}
    buy_1m = sell_1m = 0.0
    window_start_5m = now - FIVE_MINUTES_MS
    window_start_1m = now - ONE_MINUTE_MS
    oldest_ts: int | None = None
    newest_ts: int | None = None
    for price, qty, ts_ms, buyer_is_maker in parsed:
        if ts_ms < window_start_5m:
            continue
        notional = price * qty
        oldest_ts = ts_ms if oldest_ts is None else min(oldest_ts, ts_ms)
        newest_ts = ts_ms if newest_ts is None else max(newest_ts, ts_ms)
        notionals.append(notional)
        signed = -notional if buyer_is_maker else notional
        if buyer_is_maker:
            aggressive_sell_volume += notional
        else:
            aggressive_buy_volume += notional
        minute_index = (now - ts_ms) // ONE_MINUTE_MS  # 0 = most recent minute
        minute_delta[minute_index] = minute_delta.get(minute_index, 0.0) + signed
        minute_volume[minute_index] = minute_volume.get(minute_index, 0.0) + notional
        if ts_ms >= window_start_1m:
            if buyer_is_maker:
                sell_1m += notional
            else:
                buy_1m += notional

    total_1m = buy_1m + sell_1m
    taker_buy_pct_1m = (buy_1m / total_1m) if total_1m > 0 else None
    delta_1m = buy_1m - sell_1m if total_1m > 0 else None

    # Cumulative delta trend over the 5m window: sign-consistent slope of
    # per-minute deltas, newest minute weighted first.
    deltas_by_minute = [minute_delta.get(index, 0.0) for index in range(4, -1, -1)]  # oldest → newest
    cumulative = 0.0
    cumulative_series: list[float] = []
    for value in deltas_by_minute:
        cumulative += value
        cumulative_series.append(cumulative)
    if len(cumulative_series) >= 2 and any(value != 0.0 for value in deltas_by_minute):
        first_half = cumulative_series[1]
        second_half = cumulative_series[-1]
        if second_half > first_half and second_half > 0:
            cumulative_delta_trend_5m = "RISING"
        elif second_half < first_half and second_half < 0:
            cumulative_delta_trend_5m = "FALLING"
        else:
            cumulative_delta_trend_5m = "FLAT"
    else:
        cumulative_delta_trend_5m = "UNKNOWN"

    mean_notional = (sum(notionals) / len(notionals)) if notionals else 0.0
    large_threshold = mean_notional * LARGE_TRADE_NOTIONAL_MULTIPLIER
    large_trades = [value for value in notionals if large_threshold > 0 and value >= large_threshold]
    large_trade_flag = bool(large_trades)

    recent_volume = minute_volume.get(0, 0.0)
    prior_minutes = [minute_volume.get(index, 0.0) for index in range(1, 5)]
    prior_mean = sum(prior_minutes) / len(prior_minutes) if prior_minutes else 0.0
    volume_acceleration = (recent_volume / prior_mean) if prior_mean > 0 else None

    total_volume = aggressive_buy_volume + aggressive_sell_volume
    imbalance = ((aggressive_buy_volume - aggressive_sell_volume) / total_volume) if total_volume > 0 else 0.0

    trade_count = len(notionals)
    if trade_count < MIN_TRADES_FOR_CONFIRMATION:
        confirmation_score = None
        confirmation_state = "INSUFFICIENT_TAPE_DATA"
    else:
        score = 0.5 + 0.5 * imbalance  # 0 = all sell pressure, 1 = all buy pressure
        # Trend agreement between the 1m and 5m windows strengthens conviction
        # toward the imbalance side; disagreement pulls the score to neutral.
        if delta_1m is not None and cumulative_delta_trend_5m in {"RISING", "FALLING"}:
            short_term_buying = delta_1m > 0
            longer_term_buying = cumulative_delta_trend_5m == "RISING"
            if short_term_buying != longer_term_buying:
                score = 0.5 + (score - 0.5) * 0.4
        confirmation_score = max(0.0, min(1.0, score))
        confirmation_state = "TAPE_DATA_OK"

    return {
        "schema_version": SCHEMA_VERSION,
        "computed_at_ms": now,
        "trade_count_5m": trade_count,
        "tape_window_oldest_ms": oldest_ts,
        "tape_window_newest_ms": newest_ts,
        "taker_buy_pct_1m": taker_buy_pct_1m,
        "delta_1m": delta_1m,
        "cumulative_delta_trend_5m": cumulative_delta_trend_5m,
        "cumulative_delta_5m": cumulative_series[-1] if cumulative_series else None,
        "per_minute_delta_5m": deltas_by_minute,
        "large_trade_flag": large_trade_flag,
        "large_trade_count_5m": len(large_trades),
        "large_trade_notional_threshold": large_threshold if large_threshold > 0 else None,
        "aggressive_buy_volume": aggressive_buy_volume,
        "aggressive_sell_volume": aggressive_sell_volume,
        "volume_acceleration": volume_acceleration,
        "trade_tape_confirmation_score": confirmation_score,
        "trade_tape_confirmation_state": confirmation_state,
        "tape_imbalance_5m": imbalance if total_volume > 0 else None,
        "places_real_order": False,
        "writes_legacy_redis": False,
    }


def order_flow_confirms_side(features: Mapping[str, Any], side: str) -> tuple[bool | None, str]:
    """Return (confirms, reason). None = tape data unavailable (fail-closed upstream)."""
    state = str(features.get("trade_tape_confirmation_state") or "")
    score = _finite(features.get("trade_tape_confirmation_score"))
    if state != "TAPE_DATA_OK" or score is None:
        return None, "TAPE_DATA_UNAVAILABLE"
    normalized = side.strip().lower()
    if normalized in {"long", "buy"}:
        if score >= 0.55:
            return True, f"TAPE_CONFIRMS_LONG:{score:.3f}"
        if score <= 0.45:
            return False, f"TAPE_CONTRADICTS_LONG:{score:.3f}"
        return False, f"TAPE_NEUTRAL_NO_CONFIRMATION:{score:.3f}"
    if normalized in {"short", "sell"}:
        if score <= 0.45:
            return True, f"TAPE_CONFIRMS_SHORT:{score:.3f}"
        if score >= 0.55:
            return False, f"TAPE_CONTRADICTS_SHORT:{score:.3f}"
        return False, f"TAPE_NEUTRAL_NO_CONFIRMATION:{score:.3f}"
    return False, f"UNKNOWN_SIDE:{side}"


def trade_tape_blocks_breakout(features: Mapping[str, Any], side: str) -> tuple[bool, str]:
    """Hard rule: no breakout/squeeze trade without tape confirmation.

    Returns (blocked, reason). Missing tape data blocks (fail-closed).
    """
    confirms, reason = order_flow_confirms_side(features, side)
    if confirms is True:
        volume_acceleration = _finite(features.get("volume_acceleration"))
        if volume_acceleration is not None and volume_acceleration < 1.0:
            return True, f"BREAKOUT_WITHOUT_VOLUME_ACCELERATION:{volume_acceleration:.2f}"
        return False, reason
    return True, f"BREAKOUT_TAPE_CONFIRMATION_REQUIRED:{reason}"
