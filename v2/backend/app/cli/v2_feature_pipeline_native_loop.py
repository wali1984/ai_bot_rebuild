"""V2 native feature pipeline live loop (paper/shadow, V2 namespace).

Consumes v2:market:prices:* / v2:market:funding:* /
v2:market:open_interest:* / v2:market:long_short:*
and emits v2:features:latest:{symbol}:{tf} + v2:features:snapshots
and the on-disk trainer-consumable snapshot.

Writes V2 namespace ONLY. No legacy Redis. No exchange mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols
from v2.backend.app.services.feature_pipeline_and_ta.service import (
    _rsi as _ta_rsi,
    _macd as _ta_macd,
    _ema as _ta_ema,
    _sma as _ta_sma,
    _atr as _ta_atr,
    _orderbook_imbalance as _ta_orderbook_imbalance,
)

V2_REDIS_PREFIX = "v2:"
DEFAULT_TF = "1m"
DEFAULT_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
FEATURE_LATEST_TTL_SECONDS = 600
FEATURE_SNAPSHOT_ARCHIVE_TTL_SECONDS = 24 * 60 * 60  # 24h; 30d caused Redis OOM at 370K keys
REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PAYLOAD_PATH = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime/v2_feature_pipeline_native/live/latest/v2_feature_pipeline_native_live_status.json"
)
SNAPSHOT_PATH = REPO_ROOT / "v2/runtime/v2_feature_pipeline_native/latest/latest_feature_snapshot.json"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _ms_to_utc_iso(value: int | float) -> str:
    return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _parse_time_ms(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = int(value)
        return numeric * 1000 if abs(numeric) < 10_000_000_000 else numeric
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            numeric = int(float(text))
            return numeric * 1000 if abs(numeric) < 10_000_000_000 else numeric
        except ValueError:
            try:
                return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
            except ValueError:
                return None
    return None


def _timeframe_ms(value: str) -> int:
    text = str(value or "").strip().lower()
    if not text:
        return 60_000
    unit = text[-1]
    try:
        amount = int(text[:-1])
    except ValueError:
        return 60_000
    if unit == "m":
        return amount * 60_000
    if unit == "h":
        return amount * 3_600_000
    if unit == "d":
        return amount * 86_400_000
    return 60_000


def _closed_candle_is_stale(*, close_ms: int | None, decision_ms: int, timeframe: str) -> bool:
    if close_ms is None:
        return True
    max_age_ms = _timeframe_ms(timeframe) + 120_000
    return int(decision_ms) - int(close_ms) > max_age_ms


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        r = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def _safe_write(r, key: str, value: str, ex: int | None = None) -> bool:
    if r is None or not key.startswith(V2_REDIS_PREFIX):
        return False
    try:
        if ex is not None:
            r.set(key, value, ex=int(ex))
        else:
            r.set(key, value)
        return True
    except Exception:
        return False


def _read_market(r, symbol: str) -> dict | None:
    if r is None:
        return None
    raw = r.get(f"{V2_REDIS_PREFIX}market:prices:{symbol}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _market_from_closed_klines(klines: list | None) -> dict | None:
    if not isinstance(klines, list) or not klines:
        return None
    latest = klines[-1]
    try:
        if isinstance(latest, dict):
            close = float(latest.get("close"))
            open_price = float(latest.get("open", close))
            high = float(latest.get("high", close))
            low = float(latest.get("low", close))
            quote_volume = float(latest.get("quote_volume") or latest.get("quoteVolume") or 0.0)
        elif isinstance(latest, (list, tuple)) and len(latest) >= 7:
            open_price = float(latest[1])
            high = float(latest[2])
            low = float(latest[3])
            close = float(latest[4])
            quote_volume = float(latest[7]) if len(latest) > 7 else 0.0
        else:
            return None
    except (TypeError, ValueError):
        return None
    return {
        "price": close,
        "last_price": close,
        "ticker_24hr": {
            "lastPrice": close,
            "openPrice": open_price,
            "highPrice": high,
            "lowPrice": low,
            "prevClosePrice": open_price,
            "quoteVolume": quote_volume,
        },
        "funding": {},
        "open_interest": {},
        "source": "v2:market:ohlcv_closed:binance",
    }


def _load_json_list_key(r, key: str) -> list | None:
    raw = r.get(key)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else None
    except (ValueError, TypeError):
        return None


def _latest_closed_close_ms(klines: list | None, *, decision_ms: int) -> int | None:
    latest: int | None = None
    closed, _ = _closed_klines(klines, decision_ms=decision_ms)
    for row in closed:
        try:
            if isinstance(row, dict):
                close_ms = int(float(row.get("candle_close_time") or row.get("close_time")))
            elif isinstance(row, (list, tuple)) and len(row) >= 7:
                close_ms = int(float(row[6]))
            else:
                continue
        except (TypeError, ValueError):
            continue
        latest = close_ms if latest is None else max(latest, close_ms)
    return latest


def _read_klines(r, symbol: str, interval: str = "1m", *, decision_ms: int | None = None) -> list | None:
    if r is None:
        return None
    current_decision_ms = int(decision_ms if decision_ms is not None else time.time() * 1000)
    closed_key = f"{V2_REDIS_PREFIX}market:ohlcv_closed:binance:{symbol}:{interval}"
    raw_key = f"{V2_REDIS_PREFIX}market:ohlcv:binance:{symbol}:{interval}"
    closed_rows = _load_json_list_key(r, closed_key)
    raw_rows = _load_json_list_key(r, raw_key)
    closed_latest = _latest_closed_close_ms(closed_rows, decision_ms=current_decision_ms)
    raw_latest = _latest_closed_close_ms(raw_rows, decision_ms=current_decision_ms)
    if raw_latest is not None and (closed_latest is None or raw_latest > closed_latest):
        return raw_rows
    return closed_rows


def _closed_klines(klines: list | None, *, decision_ms: int) -> tuple[list, list | None]:
    closed: list = []
    if not isinstance(klines, list):
        return closed, None
    for row in klines:
        if isinstance(row, dict):
            if row.get("is_closed") is not True and row.get("closed_candle") is not True and row.get("candle_closed_confirmed") is not True:
                continue
            try:
                close_ms = int(float(row.get("candle_close_time") or row.get("close_time")))
            except (TypeError, ValueError):
                continue
            available_raw = row.get("available_at") or row.get("source_available_time") or row.get("ingested_at")
            available_ms = _parse_time_ms(available_raw) if available_raw not in (None, "") else None
            if available_ms is not None and available_ms > decision_ms:
                continue
        elif isinstance(row, (list, tuple)) and len(row) >= 7:
            try:
                close_ms = int(float(row[6]))
            except (TypeError, ValueError):
                continue
        else:
            continue
        if close_ms <= decision_ms:
            closed.append(row)
    return closed, closed[-1] if closed else None


def _read_orderbook(r, symbol: str) -> dict | None:
    if r is None:
        return None
    raw = r.get(f"{V2_REDIS_PREFIX}market:orderbook:{symbol}")
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError):
        return None


def _read_oi_hist(r, symbol: str) -> list | None:
    """Open-interest history rows written by the native ingestor loop."""
    if r is None:
        return None
    raw = r.get(f"{V2_REDIS_PREFIX}market:open_interest_hist:{symbol}:5m")
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) and data else None
    except (ValueError, TypeError):
        return None


def _read_long_short(r, symbol: str) -> dict | None:
    if r is None:
        return None
    raw = r.get(f"{V2_REDIS_PREFIX}market:long_short:{symbol}")
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError):
        return None


def _read_json_key(r, key: str) -> dict | list | None:
    if r is None or not key.startswith(V2_REDIS_PREFIX):
        return None
    try:
        raw = r.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, (dict, list)) else None


def _read_hash_key(r, key: str) -> dict | None:
    if r is None or not key.startswith(V2_REDIS_PREFIX):
        return None
    try:
        data = r.hgetall(key) or {}
    except Exception:
        return None
    return dict(data) if isinstance(data, dict) and data else None


def _coerce_numeric(value):
    if isinstance(value, bool):
        return int(value)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


def _merge_numeric_features(target: dict, source: dict | None, *, prefix: str | None = None) -> int:
    if not isinstance(source, dict):
        return 0
    ignored = {
        "schema_version",
        "worker_id",
        "source",
        "source_label",
        "symbol",
        "timeframe",
        "generated_at",
        "generated_utc",
        "generated_est",
        "timestamp",
        "live_gate",
        "live_symbols",
        "approves_live",
        "approves_canary",
        "writes_legacy_redis",
        "exchange_action_taken",
        "places_real_order",
        "no_zero_fill",
        "classification",
    }
    merged = 0
    for raw_name, raw_value in source.items():
        name = str(raw_name)
        if name in ignored:
            continue
        value = _coerce_numeric(raw_value)
        if value is None:
            continue
        out_name = f"{prefix}{name}" if prefix else name
        if target.get(out_name) is None:
            target[out_name] = value
            merged += 1
    return merged


def _merge_external_v2_features(r, symbol: str, timeframe: str, features: dict) -> dict:
    """Merge real V2 feature surfaces into the live feature mirror."""
    sources_present: list[str] = []
    fields_merged = 0

    ta_full = _read_json_key(r, f"v2:features:ta_full:{symbol}:{timeframe}")
    if isinstance(ta_full, dict):
        indicators = ta_full.get("indicators")
        if isinstance(indicators, dict):
            fields_merged += _merge_numeric_features(features, indicators)
            sources_present.append("v2:features:ta_full")

    liq = _read_hash_key(r, f"v2:liquidations:levels:{symbol}:{timeframe}")
    if isinstance(liq, dict):
        fields_merged += _merge_numeric_features(features, liq)
        sources_present.append("v2:liquidations:levels")

    unified = _read_hash_key(r, f"v2:unified_features:{symbol}:{timeframe}")
    if isinstance(unified, dict):
        fields_merged += _merge_numeric_features(features, unified)
        sources_present.append("v2:unified_features")

    wsds = _read_json_key(r, f"v2:market:coinapi:wsds:{symbol}")
    if isinstance(wsds, dict):
        wsds_features = {
            "microprice": wsds.get("microprice"),
            "spread": wsds.get("spread"),
            "coinapi_mid_px": wsds.get("mid_px"),
            "coinapi_best_bid_px": wsds.get("best_bid_px"),
            "coinapi_best_ask_px": wsds.get("best_ask_px"),
            "coinapi_book_bid_sum_5": wsds.get("book_bid_sum_5"),
            "coinapi_book_ask_sum_5": wsds.get("book_ask_sum_5"),
            "coinapi_imbalance_5": wsds.get("imbalance_5"),
        }
        imbalance = _coerce_numeric(wsds.get("imbalance_5"))
        if imbalance is not None:
            wsds_features["toxicity_proxy"] = abs(float(imbalance))
        fields_merged += _merge_numeric_features(features, wsds_features)
        sources_present.append("v2:market:coinapi:wsds")

    microfeat = _read_json_key(r, f"v2:features:microfeat:{symbol}:{timeframe}")
    if isinstance(microfeat, dict) and isinstance(microfeat.get("features"), dict):
        merged = _merge_numeric_features(features, microfeat.get("features"))
        if merged:
            fields_merged += merged
            sources_present.append("v2:features:microfeat")

    return {
        "sources_present": sorted(set(sources_present)),
        "fields_merged": fields_merged,
    }


def _read_liq_notional_24h(r, symbol: str) -> float | None:
    """Resolve 24h liquidation notional (USD) for ``symbol``.

    Source priority:
      1. ``v2:market:liquidations:aggregate:{symbol}`` (rolling aggregate from
         the WSS client) — authoritative when present.
      2. ``v2:liquidations:events`` stream scanned over the last 24h — used when
         no aggregate exists but the stream is live (present even if empty).
    Returns 0.0 when a live source exists but reports no liquidations (a real
    zero), or ``None`` when no liquidation source is observable at all.
    """
    if r is None:
        return None
    agg_raw = r.get(f"{V2_REDIS_PREFIX}market:liquidations:aggregate:{symbol}")
    if agg_raw:
        try:
            agg = json.loads(agg_raw)
            if isinstance(agg, dict) and "notional_24h" in agg:
                return float(agg.get("notional_24h") or 0.0)
        except (ValueError, TypeError):
            pass
    # Fall back to the global events stream if it exists at all.
    try:
        if not r.exists(f"{V2_REDIS_PREFIX}liquidations:events"):
            return None
        entries = r.xrange(f"{V2_REDIS_PREFIX}liquidations:events", min="-", max="+")
    except Exception:
        return None
    total = 0.0
    for _eid, fields in entries or []:
        if (fields.get("symbol") or "").upper() != symbol.upper():
            continue
        try:
            total += float(fields.get("notional") or 0.0)
        except (TypeError, ValueError):
            continue
    return total


def _klines_to_ohlc_series(klines: list) -> tuple[list[float], list[float], list[float], list[float]]:
    """Binance kline row: [open_time, open, high, low, close, volume, ...]."""
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    for row in klines:
        try:
            if isinstance(row, dict):
                opens.append(float(row["open"]))
                highs.append(float(row["high"]))
                lows.append(float(row["low"]))
                closes.append(float(row["close"]))
            elif isinstance(row, (list, tuple)) and len(row) >= 5:
                opens.append(float(row[1]))
                highs.append(float(row[2]))
                lows.append(float(row[3]))
                closes.append(float(row[4]))
        except (TypeError, ValueError):
            continue
    return opens, highs, lows, closes


def _f(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _first_numeric(*values) -> float | None:
    for value in values:
        parsed = _coerce_numeric(value)
        if parsed is not None:
            return float(parsed)
    return None


def _top_depth_notional_usd(levels, *, depth: int = 5) -> float | None:
    if not isinstance(levels, list) or not levels:
        return None
    total = 0.0
    seen = 0
    for row in levels[:depth]:
        price = None
        qty = None
        if isinstance(row, (list, tuple)) and len(row) > 1:
            price = _coerce_numeric(row[0])
            qty = _coerce_numeric(row[1])
        elif isinstance(row, dict):
            price = _coerce_numeric(row.get("price") or row.get("p"))
            qty = _coerce_numeric(row.get("quantity") or row.get("qty") or row.get("q"))
        if price is None or qty is None or price <= 0 or qty <= 0:
            continue
        total += float(price) * float(qty)
        seen += 1
    return total if seen else None


def _features_from_market(market: dict) -> dict:
    """Build a feature record. Pure-computed values from real OHLCV when present.

    For each TA field, either return a real computation result, or return
    ``None`` (which the caller will record as MISSING in
    ``missing_feature_flags`` so the trainer never sees a silent zero).
    """
    t = market.get("ticker_24hr") or {}
    f = market.get("funding") or {}
    oi = market.get("open_interest") or {}
    last = _f(t.get("lastPrice"))
    open_p = _f(t.get("openPrice"))
    high = _f(t.get("highPrice"))
    low = _f(t.get("lowPrice"))
    prev_close = _f(t.get("prevClosePrice"))
    ret_pct = (last - open_p) / open_p if open_p > 0 else 0.0
    range_pct = (high - low) / open_p if open_p > 0 else 0.0
    gap_pct = (open_p - prev_close) / prev_close if prev_close > 0 else 0.0
    raw_funding_rate = _first_numeric(f.get("lastFundingRate"), f.get("fundingRate"))
    funding_rate = raw_funding_rate if raw_funding_rate is not None else 0.0
    mark_price = _coerce_numeric(f.get("markPrice") or f.get("mark_price") or last)
    index_price = _coerce_numeric(f.get("indexPrice") or f.get("index_price") or last)
    basis_pct = None
    if mark_price is not None and index_price not in (None, 0.0):
        basis_pct = (float(mark_price) - float(index_price)) / float(index_price)
    long_short = market.get("_long_short") or {}
    long_short_ratio = None
    long_account_ratio = None
    short_account_ratio = None
    if isinstance(long_short, dict):
        long_short_ratio = _coerce_numeric(
            long_short.get("long_short_ratio", long_short.get("longShortRatio"))
        )
        long_account_ratio = _coerce_numeric(
            long_short.get("long_account_ratio", long_short.get("longAccount"))
        )
        short_account_ratio = _coerce_numeric(
            long_short.get("short_account_ratio", long_short.get("shortAccount"))
        )

    klines = market.get("_klines") or []
    orderbook = market.get("_orderbook") or {}
    opens, highs, lows, closes = _klines_to_ohlc_series(klines)
    latest_kline = klines[-1] if isinstance(klines, list) and klines else None
    k_open = k_high = k_low = k_close = k_volume = k_quote_volume = None
    k_num_trades = k_taker_buy_base = k_taker_buy_quote = None
    if isinstance(latest_kline, dict):
        k_open = _coerce_numeric(latest_kline.get("open"))
        k_high = _coerce_numeric(latest_kline.get("high"))
        k_low = _coerce_numeric(latest_kline.get("low"))
        k_close = _coerce_numeric(latest_kline.get("close"))
        k_volume = _coerce_numeric(latest_kline.get("volume"))
        k_quote_volume = _coerce_numeric(latest_kline.get("quote_volume") or latest_kline.get("quoteVolume"))
        k_num_trades = _coerce_numeric(latest_kline.get("num_trades") or latest_kline.get("number_of_trades"))
        k_taker_buy_base = _coerce_numeric(latest_kline.get("taker_buy_base_vol") or latest_kline.get("taker_buy_base_volume"))
        k_taker_buy_quote = _coerce_numeric(latest_kline.get("taker_buy_quote_vol") or latest_kline.get("taker_buy_quote_volume"))
    elif isinstance(latest_kline, (list, tuple)) and len(latest_kline) >= 11:
        k_open = _coerce_numeric(latest_kline[1])
        k_high = _coerce_numeric(latest_kline[2])
        k_low = _coerce_numeric(latest_kline[3])
        k_close = _coerce_numeric(latest_kline[4])
        k_volume = _coerce_numeric(latest_kline[5])
        k_quote_volume = _coerce_numeric(latest_kline[7])
        k_num_trades = _coerce_numeric(latest_kline[8])
        k_taker_buy_base = _coerce_numeric(latest_kline[9])
        k_taker_buy_quote = _coerce_numeric(latest_kline[10])

    rsi_14 = _ta_rsi(closes, 14) if closes else None
    macd_line, macd_signal_v, macd_hist = (None, None, None)
    if closes:
        macd_line, macd_signal_v, macd_hist = _ta_macd(closes, 12, 26, 9)
    ema_12 = _ta_ema(closes, 12) if closes else None
    ema_26 = _ta_ema(closes, 26) if closes else None
    sma_20 = _ta_sma(closes, 20) if closes else None
    atr_14 = _ta_atr(highs, lows, closes, 14) if (highs and lows and closes) else None

    # Bollinger band width (sigma over 20-period closes / mean) — only
    # if we have at least 20 closes; otherwise None.
    bb_width_pct: float | None = None
    if len(closes) >= 20 and sma_20 and sma_20 > 0:
        window = closes[-20:]
        mean = sma_20
        var = sum((c - mean) ** 2 for c in window) / 20.0
        std = var ** 0.5
        bb_width_pct = (2.0 * std) / mean

    htf_rsi_14: float | None = None
    if len(closes) >= 60:
        # 5x downsampled higher-timeframe RSI proxy from the 1m series
        htf_closes = closes[::5]
        htf_rsi_14 = _ta_rsi(htf_closes, 14)
    htf_ret_pct = (closes[-1] / closes[-5] - 1.0) if len(closes) >= 5 and closes[-5] > 0 else None

    depth_imbalance = _ta_orderbook_imbalance(orderbook) if orderbook else None

    # toxicity_proxy: directional order-flow toxicity from book imbalance.
    # depth_imbalance is signed (bid-ask)/(bid+ask) in [-1, 1]; its magnitude is
    # the toxicity proxy: 0.0 = perfectly balanced book (benign flow), 1.0 =
    # fully one-sided (toxic / adverse-selection risk). Real only with a book.
    toxicity_proxy: float | None = None
    if depth_imbalance is not None:
        toxicity_proxy = abs(depth_imbalance)

    # oi_change_pct: 1h open-interest change from Binance public OI history.
    oi_change_pct: float | None = None
    oi_hist = market.get("_oi_hist") or []
    if isinstance(oi_hist, list) and len(oi_hist) >= 2:
        try:
            first_oi = float(oi_hist[0].get("sumOpenInterest"))
            last_oi = float(oi_hist[-1].get("sumOpenInterest"))
            if first_oi > 0:
                oi_change_pct = (last_oi - first_oi) / first_oi
        except (TypeError, ValueError, AttributeError):
            oi_change_pct = None

    # last_liq_bps_24h: 24h liquidation notional as bps of 24h quote volume.
    last_liq_bps_24h: float | None = None
    liq_notional_24h = market.get("_liq_notional_24h")
    quote_vol_24h = _f(t.get("quoteVolume"))
    if liq_notional_24h is not None and quote_vol_24h > 0:
        last_liq_bps_24h = (float(liq_notional_24h) / quote_vol_24h) * 10000.0

    # Market-cost evidence from explicit V2 market inputs. Missing upstream
    # evidence stays None so replay remains fail-closed instead of defaulted.
    bid_ask_spread_bps: float | None = None
    bid_depth_usd: float | None = None
    ask_depth_usd: float | None = None
    orderbook_depth_usd: float | None = None
    if orderbook:
        bid_ask_spread_bps = _first_numeric(
            orderbook.get("actual_observed_spread_entry_bps"),
            orderbook.get("bid_ask_spread_bps"),
            orderbook.get("ob_spread_bps"),
            orderbook.get("orderbook_spread_bps"),
            orderbook.get("spread_bps"),
        )
        bids = orderbook.get("bids") or []
        asks = orderbook.get("asks") or []
        if (
            bid_ask_spread_bps is None
            and bids and asks
            and isinstance(bids[0], (list, tuple)) and isinstance(asks[0], (list, tuple))
        ):
            try:
                bid_p = float(bids[0][0])
                ask_p = float(asks[0][0])
                if bid_p > 0 and ask_p > 0:
                    mid = (bid_p + ask_p) / 2.0
                    bid_ask_spread_bps = ((ask_p - bid_p) / mid) * 10000.0
            except (TypeError, ValueError):
                bid_ask_spread_bps = None
        bid_depth_usd = _first_numeric(
            orderbook.get("bid_depth_usd"),
            orderbook.get("book_bid_depth_usd"),
        )
        ask_depth_usd = _first_numeric(
            orderbook.get("ask_depth_usd"),
            orderbook.get("book_ask_depth_usd"),
        )
        if bid_depth_usd is None:
            bid_depth_usd = _top_depth_notional_usd(bids)
        if ask_depth_usd is None:
            ask_depth_usd = _top_depth_notional_usd(asks)
        orderbook_depth_usd = _first_numeric(
            orderbook.get("orderbook_depth_usd"),
            orderbook.get("market_depth_usd"),
            orderbook.get("depth_usd"),
            orderbook.get("depth_total_usd"),
            orderbook.get("available_depth_usd"),
            orderbook.get("top_of_book_depth_usd"),
        )
        if orderbook_depth_usd is None and bid_depth_usd is not None and ask_depth_usd is not None:
            orderbook_depth_usd = min(bid_depth_usd, ask_depth_usd)
    fee_bps = _first_numeric(
        market.get("fee_bps"),
        market.get("taker_fee_bps"),
        market.get("expected_fee_bps"),
        t.get("fee_bps"),
        t.get("taker_fee_bps"),
        orderbook.get("fee_bps") if isinstance(orderbook, dict) else None,
        orderbook.get("taker_fee_bps") if isinstance(orderbook, dict) else None,
    )
    expected_slippage_bps = _first_numeric(
        market.get("expected_slippage_bps"),
        market.get("actual_observed_slippage_bps"),
        market.get("actual_slippage_bps"),
        market.get("realized_slippage_bps"),
        market.get("slippage_bps"),
        t.get("expected_slippage_bps"),
        t.get("slippage_bps"),
        orderbook.get("expected_slippage_bps") if isinstance(orderbook, dict) else None,
        orderbook.get("slippage_bps") if isinstance(orderbook, dict) else None,
    )
    expected_funding_bps = _first_numeric(
        market.get("expected_funding_bps"),
        market.get("funding_bps"),
        f.get("expected_funding_bps"),
        f.get("funding_bps"),
        f.get("funding_rate_bps"),
    )
    if expected_funding_bps is None and raw_funding_rate is not None:
        expected_funding_bps = float(raw_funding_rate) * 10000.0

    return {
        "open": k_open,
        "high": k_high,
        "low": k_low,
        "close": k_close,
        "last_price": last if last > 0 else k_close,
        "mark_price": mark_price,
        "index_price": index_price,
        "basis_pct": basis_pct,
        "volume": k_volume,
        "quote_volume": k_quote_volume,
        "num_trades": k_num_trades,
        "taker_buy_base_vol": k_taker_buy_base,
        "taker_buy_quote_vol": k_taker_buy_quote,
        "ret_pct": ret_pct,
        "log_return": 0.0 if open_p <= 0 else (last / open_p - 1.0),
        "range_pct": range_pct,
        "body_pct": (last - open_p) / open_p if open_p > 0 else 0.0,
        "true_range_pct": range_pct,
        "gap_pct": gap_pct,
        "ema_12": ema_12,
        "ema_26": ema_26,
        "sma_20": sma_20,
        "rsi_14": rsi_14,
        "macd": macd_line,
        "macd_signal": macd_signal_v,
        "macd_hist": macd_hist,
        "atr_14": atr_14,
        "bb_width_pct": bb_width_pct,
        "htf_ret_pct": htf_ret_pct,
        "htf_rsi_14": htf_rsi_14,
        "bid_ask_spread_bps": bid_ask_spread_bps,
        "actual_observed_spread_entry_bps": bid_ask_spread_bps,
        "bid_depth_usd": bid_depth_usd,
        "ask_depth_usd": ask_depth_usd,
        "orderbook_depth_usd": orderbook_depth_usd,
        "fee_bps": fee_bps,
        "expected_slippage_bps": expected_slippage_bps,
        "expected_funding_bps": expected_funding_bps,
        "depth_imbalance": depth_imbalance,
        "micro_price": last,
        "toxicity_proxy": toxicity_proxy,
        "funding_rate": funding_rate,
        "long_short_ratio": long_short_ratio,
        "long_account_ratio": long_account_ratio,
        "short_account_ratio": short_account_ratio,
        "oi_change_pct": oi_change_pct,
        "last_liq_bps_24h": last_liq_bps_24h,
        "paper_position_present": 0,
    }


def _snapshot_id(payload: dict) -> str:
    h = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    return f"v2_fsnap_{h}"


def _feature_snapshot_archive_key(snapshot_id: str) -> str:
    return f"{V2_REDIS_PREFIX}features:snapshot:{snapshot_id}"


def run_once(symbols: tuple[str, ...], timeframe: str, *, write_trainer_snapshot: bool = True) -> dict:
    started_at = _utc_iso()
    decision_ms = int(time.time() * 1000)
    r = _connect_redis()
    keys_written: list[str] = []
    snapshots: list[dict] = []
    missing: list[str] = []
    for sym in symbols:
        # Attach klines + orderbook + OI history + liquidation notional so the
        # feature builder can compute real TA (no silent zeros).
        raw_klines = _read_klines(r, sym, timeframe)
        closed_klines, latest_closed_kline = _closed_klines(raw_klines, decision_ms=decision_ms)
        m = _read_market(r, sym) or _market_from_closed_klines(closed_klines)
        if not m:
            missing.append(sym)
            continue
        m["_klines"] = closed_klines
        m["_orderbook"] = _read_orderbook(r, sym)
        m["_oi_hist"] = _read_oi_hist(r, sym)
        m["_long_short"] = _read_long_short(r, sym)
        m["_liq_notional_24h"] = _read_liq_notional_24h(r, sym)
        feats = _features_from_market(m)
        external = _merge_external_v2_features(r, sym, timeframe, feats)
        missing_feature_flags = sorted(k for k, v in feats.items() if v is None)
        candle_open_time = None
        candle_close_time = None
        candle_close_ms = None
        closed_candle_available = latest_closed_kline is not None
        if isinstance(latest_closed_kline, dict):
            candle_open_ms = int(float(latest_closed_kline.get("candle_open_time") or latest_closed_kline.get("open_time")))
            candle_close_ms = int(float(latest_closed_kline.get("candle_close_time") or latest_closed_kline.get("close_time")))
            candle_open_time = _ms_to_utc_iso(candle_open_ms)
            candle_close_time = _ms_to_utc_iso(candle_close_ms)
        elif isinstance(latest_closed_kline, (list, tuple)) and len(latest_closed_kline) >= 7:
            candle_open_time = _ms_to_utc_iso(int(float(latest_closed_kline[0])))
            candle_close_ms = int(float(latest_closed_kline[6]))
            candle_close_time = _ms_to_utc_iso(candle_close_ms)
        closed_candle_stale = (
            closed_candle_available
            and _closed_candle_is_stale(
                close_ms=candle_close_ms,
                decision_ms=decision_ms,
                timeframe=timeframe,
            )
        )
        if not closed_candle_available:
            missing_feature_flags = sorted(set(missing_feature_flags) | {
                "ohlcv_closed_window",
                "candle_closed_confirmed",
                "feature_cutoff",
            })
        if closed_candle_stale:
            missing_feature_flags = sorted(set(missing_feature_flags) | {
                "ohlcv_closed_window_stale",
            })
        generated_at = _utc_iso()
        trainer_consumable = closed_candle_available and not closed_candle_stale
        if not closed_candle_available:
            feature_freshness_state = "MISSING_CLOSED_OHLCV"
        elif closed_candle_stale:
            feature_freshness_state = "STALE_CLOSED_OHLCV"
        else:
            feature_freshness_state = "CURRENT"
        snap = {
            "schema_version": "v2_native_feature_snapshot_v1",
            "worker_id": "v2_feature_pipeline_native_loop",
            "symbol": sym,
            "timeframe": timeframe,
            "features": feats,
            "feature_count": len(feats),
            "real_feature_count": sum(1 for v in feats.values() if v is not None),
            "placeholder_feature_count": 0,
            "missing_feature_count": len(missing_feature_flags),
            "categories_present": [
                "ohlcv_derived", "ta_indicators", "multi_timeframe",
                "microstructure", "funding_oi_liquidation", "portfolio_aware", "freshness",
            ],
            "missing_feature_flags": missing_feature_flags,
            "stale_feature_flags": ["ohlcv_closed_window"] if closed_candle_stale else [],
            "feature_freshness_state": feature_freshness_state,
            "trainer_consumable": trainer_consumable,
            "valid_for_prediction": trainer_consumable,
            "valid_for_paper": trainer_consumable,
            "candle_closed_confirmed": closed_candle_available,
            "candle_open_time": candle_open_time,
            "candle_close_time": candle_close_time,
            "source_event_time_est": candle_close_time,
            "source_received_time_est": generated_at,
            "source_available_time": generated_at,
            "available_at": generated_at,
            "feature_cutoff": candle_close_time,
            "decision_time_est": generated_at,
            "decision_cutoff_time_est": generated_at,
            "source_ohlcv_key": f"v2:market:ohlcv_closed:binance:{sym}:{timeframe}",
            "external_v2_sources_present": external["sources_present"],
            "external_v2_feature_fields_merged": external["fields_merged"],
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "ohlcv_history_present": bool(closed_klines),
            "ohlcv_raw_row_count": len(raw_klines or []),
            "ohlcv_closed_row_count": len(closed_klines),
            "ohlcv_closed_age_seconds": (
                None if candle_close_ms is None else max(0, int((decision_ms - candle_close_ms) / 1000))
            ),
            "latest_unclosed_kline_excluded": bool(raw_klines and closed_klines and len(raw_klines) != len(closed_klines)),
            "orderbook_present": bool(m.get("_orderbook")),
            "long_short_present": bool(m.get("_long_short")),
            "generated_at": generated_at,
            "generated_utc": generated_at,
        }
        snap["feature_snapshot_id"] = _snapshot_id(snap)
        snapshots.append(snap)
        if r is not None:
            k = f"{V2_REDIS_PREFIX}features:latest:{sym}:{timeframe}"
            snap_payload = json.dumps(snap)
            if _safe_write(r, k, snap_payload, ex=FEATURE_LATEST_TTL_SECONDS):
                keys_written.append(k)
            archive_key = _feature_snapshot_archive_key(str(snap["feature_snapshot_id"]))
            if _safe_write(r, archive_key, snap_payload, ex=FEATURE_SNAPSHOT_ARCHIVE_TTL_SECONDS):
                keys_written.append(archive_key)
            # Also write v2:technical_analysis:{sym}:{tf} so the TA page has fresh
            # live values with proper TTL. Mirrors the TA subset from features.
            ta_families: list[str] = []
            ta_indicators: dict = {}
            f = feats
            if f.get("rsi_14") is not None:
                ta_indicators["ta_RSI_14"] = f["rsi_14"]
                ta_families.append("RSI")
            if f.get("macd") is not None:
                ta_indicators["ta_MACD_12_26_9_macd"] = f["macd"]
                ta_indicators["ta_MACD_12_26_9_signal"] = f.get("macd_signal")
                ta_indicators["ta_MACD_12_26_9_hist"] = f.get("macd_hist")
                ta_indicators["ta_MACDhist_12_26_9"] = f.get("macd_hist")
                ta_families.append("MACD")
            if f.get("atr_14") is not None:
                ta_indicators["ta_ATR_14"] = f["atr_14"]
                ta_families.append("ATR")
            if f.get("sma_20") is not None:
                ta_indicators["ta_SMA_20"] = f["sma_20"]
                ta_families.append("SMA")
            if f.get("ema_12") is not None:
                ta_indicators["ta_EMA_12"] = f["ema_12"]
                ta_families.append("EMA")
            if f.get("ema_26") is not None:
                ta_indicators["ta_EMA_26"] = f["ema_26"]
            if f.get("bb_width_pct") is not None:
                ta_indicators["ta_BB_width_pct"] = f["bb_width_pct"]
                ta_families.append("BB")
            if f.get("htf_rsi_14") is not None:
                ta_indicators["ta_HTF_RSI_14"] = f["htf_rsi_14"]
            ta_indicators["timestamp"] = time.time() * 1000
            ta_payload = {
                "symbol": sym,
                "timeframe": timeframe,
                "generated_utc": _utc_iso(),
                "schema_version": "v2_native_feature_pipeline_ta_v2",
                "source_label": "V2_NATIVE_FEATURE_PIPELINE_LIVE",
                "source_ohlcv_key": f"v2:market:ohlcv_closed:binance:{sym}:{timeframe}",
                "families_present": list(dict.fromkeys(ta_families)),
                "indicators": ta_indicators,
                "live_gate": "blocked_human_only",
                "live_symbols": [],
                "no_zero_fill": True,
            }
            ta_key = f"{V2_REDIS_PREFIX}technical_analysis:{sym}:{timeframe}"
            if _safe_write(r, ta_key, json.dumps(ta_payload), ex=600):
                keys_written.append(ta_key)
    if r is not None and snapshots:
        ids_payload = json.dumps([s["feature_snapshot_id"] for s in snapshots])
        if _safe_write(r, f"{V2_REDIS_PREFIX}features:snapshots", ids_payload, ex=FEATURE_SNAPSHOT_ARCHIVE_TTL_SECONDS):
            keys_written.append(f"{V2_REDIS_PREFIX}features:snapshots")
    # On-disk trainer-consumable snapshot mirrors the first symbol's record
    # so the existing P0.2A/B/F/G workers can consume it.
    if snapshots and write_trainer_snapshot:
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(json.dumps(snapshots[0], indent=2, sort_keys=True) + "\n")
    classification = (
        "NATIVE_V2_FEATURES_OK" if snapshots else
        ("BLOCKED_BY_MISSING_MARKET_INPUTS" if missing else "BLOCKED_BY_REDIS_UNAVAILABLE")
    )
    hb = {
        "worker_id": "v2_feature_pipeline_native_loop",
        "schema_version": "v2_feature_pipeline_native_live_v1",
        "started_at": started_at,
        "finished_at": _utc_iso(),
        "symbols": list(symbols),
        "timeframe": timeframe,
        "snapshots_built": len(snapshots),
        "missing_symbols": missing,
        "v2_features_keys_written": keys_written,
        "v2_features_keys_written_count": len(keys_written),
        "classification": classification,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_legacy_shutdown": False,
        "writes_legacy_redis": False,
    }
    if r is not None:
        _safe_write(
            r,
            f"{V2_REDIS_PREFIX}features:pipeline:heartbeat",
            json.dumps(hb),
            ex=300,
        )
    return hb


def run_timeframes(symbols: tuple[str, ...], timeframes: tuple[str, ...]) -> dict:
    per_timeframe: list[dict] = []
    aggregate_keys: list[str] = []
    write_trainer_snapshot = True
    for timeframe in timeframes:
        hb = run_once(
            symbols,
            timeframe,
            write_trainer_snapshot=write_trainer_snapshot,
        )
        write_trainer_snapshot = False
        per_timeframe.append(hb)
        aggregate_keys.extend(hb.get("v2_features_keys_written") or [])
    snapshots_built = sum(int(row.get("snapshots_built") or 0) for row in per_timeframe)
    missing_symbols = sorted({
        symbol
        for row in per_timeframe
        for symbol in (row.get("missing_symbols") or [])
    })
    if per_timeframe and all(row.get("classification") == "NATIVE_V2_FEATURES_OK" for row in per_timeframe):
        classification = "NATIVE_V2_FEATURES_OK"
    elif snapshots_built:
        classification = "NATIVE_V2_FEATURES_PARTIAL"
    else:
        classification = "BLOCKED_BY_MISSING_MARKET_INPUTS"
    aggregate = {
        "worker_id": "v2_feature_pipeline_native_loop",
        "schema_version": "v2_feature_pipeline_native_live_v2",
        "started_at": per_timeframe[0]["started_at"] if per_timeframe else _utc_iso(),
        "finished_at": _utc_iso(),
        "symbols": list(symbols),
        "timeframe": ",".join(timeframes),
        "timeframes": list(timeframes),
        "snapshots_built": snapshots_built,
        "snapshots_built_by_timeframe": {
            row.get("timeframe"): row.get("snapshots_built") for row in per_timeframe
        },
        "missing_symbols": missing_symbols,
        "v2_features_keys_written": aggregate_keys,
        "v2_features_keys_written_count": len(aggregate_keys),
        "per_timeframe": per_timeframe,
        "classification": classification,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_legacy_shutdown": False,
        "writes_legacy_redis": False,
    }
    r = _connect_redis()
    if r is not None:
        _safe_write(
            r,
            f"{V2_REDIS_PREFIX}features:pipeline:heartbeat",
            json.dumps(aggregate),
            ex=300,
        )
    return aggregate


def write_payload(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _resolve_runtime_symbols(raw_symbols: str | None, *, smoke_test: bool) -> tuple[str, ...]:
    return tuple(
        resolve_symbols(
            explicit=raw_symbols,
            smoke_test=smoke_test,
            include_baseline=True,
        )
    )


def _parse_timeframes(raw_timeframe: str | None, raw_timeframes: str | None) -> tuple[str, ...]:
    raw = raw_timeframes or raw_timeframe
    if not raw:
        return DEFAULT_TIMEFRAMES
    out: list[str] = []
    for part in raw.split(","):
        timeframe = part.strip()
        if timeframe and timeframe not in out:
            out.append(timeframe)
    return tuple(out or DEFAULT_TIMEFRAMES)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_feature_pipeline_native_loop")
    parser.add_argument(
        "--symbols",
        default=None,
        help="Explicit comma-separated symbols. Omit for dynamic universe plus 25-symbol baseline.",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Use the BTC/ETH/SOL smoke-test set; never the default.",
    )
    parser.add_argument("--timeframe", default=None)
    parser.add_argument("--timeframes", default=None)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--out", type=Path, default=DEFAULT_PAYLOAD_PATH)
    args = parser.parse_args(argv)
    if args.loop:
        while True:
            symbols = _resolve_runtime_symbols(args.symbols, smoke_test=args.smoke_test)
            hb = run_timeframes(symbols, _parse_timeframes(args.timeframe, args.timeframes))
            write_payload(hb, args.out)
            time.sleep(max(5, int(args.interval_seconds)))
    symbols = _resolve_runtime_symbols(args.symbols, smoke_test=args.smoke_test)
    hb = run_timeframes(symbols, _parse_timeframes(args.timeframe, args.timeframes))
    write_payload(hb, args.out)
    print(json.dumps({
        "classification": hb["classification"],
        "snapshots_built": hb["snapshots_built"],
        "v2_features_keys_written_count": hb["v2_features_keys_written_count"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
