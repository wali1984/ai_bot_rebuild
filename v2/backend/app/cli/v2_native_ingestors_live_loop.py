"""V2 native ingestors live loop (paper/shadow, V2-namespace only).

Public market data only. Writes to v2:* Redis namespace ONLY.
No exchange mutation. No legacy Redis writes.

Default behavior:
- reads Binance WebSocket-backed Redis/cache data first for the configured
  symbol set, writes v2:market:prices:* / v2:market:funding:* /
  v2:market:open_interest:*
- public REST is fallback-only and requires BINANCE_REST_FALLBACK_ALLOWED=true
- when WebSocket/cache data and explicit fallback are unavailable, writes the
  heartbeat with a BLOCKED_BY_NETWORK_OR_API status and no price data
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from v2.backend.app.services.binance_unified_websocket_transport import (
    REST_FALLBACK_ENV,
    binance_rest_fallback_allowed,
    require_binance_rest_fallback,
)
from v2.backend.app.services.market_data.current_price_resolver import resolve_current_price
from v2.backend.app.services.market_state_integrity.canonical_candles import (
    closed_candle_key,
    current_candle_key,
)
from v2.backend.app.services.v2_symbol_runtime_universe import is_valid_runtime_symbol, resolve_symbols

V2_REDIS_PREFIX = "v2:"
DEFAULT_PAYLOAD_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_native_ingestors/live/latest/v2_native_ingestors_live_status.json"
)
BINANCE_PUBLIC = "https://api.binance.com"
BINANCE_FAPI = "https://fapi.binance.com"
HTTP_TIMEOUT_S = 2.0
MAX_FETCH_WORKERS = 12
DEFAULT_KLINE_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _http_get_json(url: str, *, fallback_reason: str) -> Any:
    if "binance.com" in url:
        require_binance_rest_fallback(
            endpoint=urllib.parse.urlparse(url).path or url,
            fallback_reason=fallback_reason,
            role="native_ingestor_public_market_data_recovery",
        )
    req = urllib.request.Request(url, headers={"User-Agent": "v2-native-ingestor/1.0"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _rest_fallback_disabled() -> bool:
    return not binance_rest_fallback_allowed()


def _read_json(r: Any, key: str) -> Any:
    if r is None:
        return None
    try:
        raw = r.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw if isinstance(raw, str) else raw.decode("utf-8", errors="ignore"))
    except (TypeError, ValueError):
        return None


def _cache_payload_source(payload: dict | None, *, default: str) -> str:
    if not isinstance(payload, dict):
        return default
    source = str(payload.get("source") or payload.get("transport") or default)
    if "rest" in source.lower():
        return "binance_public_cache_rest_fallback"
    return "binance_public_websocket_cache_primary"


def _is_websocket_cache_payload(payload: dict | None) -> bool:
    if not isinstance(payload, dict):
        return False
    source = str(payload.get("source") or payload.get("transport") or "").lower()
    if "rest" in source:
        return False
    return any(token in source for token in ("wss", "websocket", "ws_cache", "stream", "cache_primary"))


def _connect_redis():
    """Lazy redis import. Returns None when redis is unavailable."""
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
    if r is None:
        return False
    if not key.startswith(V2_REDIS_PREFIX):
        raise ValueError(f"refused: non-V2 namespace key {key!r}")
    try:
        if ex is not None:
            r.set(key, value, ex=int(ex))
        else:
            r.set(key, value)
        return True
    except Exception:
        return False


def _write_symbol_bundle(r: Any, sym: str, bundle: dict, keys_written: list[str]) -> None:
    if r is None:
        return
    ticker = bundle.get("ticker")
    funding = bundle.get("funding")
    oi = bundle.get("open_interest")
    long_short = bundle.get("long_short")
    klines_by_timeframe = bundle.get("klines_by_timeframe") or {}
    orderbook = bundle.get("orderbook")
    oi_hist = bundle.get("open_interest_hist")
    fetched_utc = _utc_iso()
    payload = {
        "symbol": sym,
        "source": bundle.get("source") or "binance_public_websocket_cache_primary",
        "transport": bundle.get("transport") or "websocket_cache_primary",
        "rest_fallback_used": bool(bundle.get("rest_fallback_used")),
        "ticker_24hr": ticker,
        "funding": funding,
        "open_interest": oi,
        "long_short": long_short,
        "fetched_utc": fetched_utc,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }
    writes: list[tuple[str, Any]] = [
        (f"{V2_REDIS_PREFIX}market:prices:{sym}", payload),
    ]
    if funding is not None:
        writes.append((f"{V2_REDIS_PREFIX}market:funding:{sym}", funding))
    if oi is not None:
        writes.append((f"{V2_REDIS_PREFIX}market:open_interest:{sym}", oi))
    if long_short is not None:
        writes.append((f"{V2_REDIS_PREFIX}market:long_short:{sym}", long_short))
    for timeframe, rows in sorted(klines_by_timeframe.items()):
        if rows is not None:
            writes.append((f"{V2_REDIS_PREFIX}market:ohlcv:binance:{sym}:{timeframe}", rows))
    if orderbook is not None:
        orderbook = {
            **orderbook,
            "symbol": sym,
            "source": orderbook.get("source") or _cache_payload_source(
                orderbook,
                default="binance_public_websocket_orderbook_cache_primary",
            ),
            "exchange": "binance",
            "transaction_time": orderbook.get("transaction_time") or fetched_utc,
            "received_at": orderbook.get("received_at") or fetched_utc,
            "available_at": orderbook.get("available_at") or fetched_utc,
            "fetched_utc": orderbook.get("fetched_utc") or fetched_utc,
            "event_time": orderbook.get("event_time"),
            "event_time_missing_reason": (
                orderbook.get("event_time_missing_reason")
                or (
                    "BINANCE_ORDERBOOK_CACHE_EVENT_TIME_MISSING"
                    if not str(orderbook.get("source") or "").lower().startswith("binance_public_rest")
                    else "BINANCE_REST_DEPTH_SNAPSHOT_HAS_NO_EXCHANGE_EVENT_TIME"
                )
            ),
        }
        writes.extend(
            [
                (f"{V2_REDIS_PREFIX}market:orderbook:{sym}", orderbook),
                (f"{V2_REDIS_PREFIX}market:orderbook:binance:{sym}", orderbook),
            ]
        )
    if oi_hist is not None:
        writes.append((f"{V2_REDIS_PREFIX}market:open_interest_hist:{sym}:5m", oi_hist))

    for key, value in writes:
        if _safe_write(r, key, json.dumps(value), ex=600):
            keys_written.append(key)


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fetch_ticker_24hr(symbol: str, *, redis_client: Any = None) -> dict | None:
    cached = _read_json(redis_client, f"{V2_REDIS_PREFIX}market:prices:{symbol}")
    if isinstance(cached, dict):
        ticker = cached.get("ticker_24hr") if isinstance(cached.get("ticker_24hr"), dict) else cached
        last_price = _safe_float(
            ticker.get("lastPrice")
            if isinstance(ticker, dict)
            else None
        )
        if last_price is None:
            try:
                resolved = resolve_current_price(redis_client, symbol)
            except Exception:
                resolved = {}
            last_price = _safe_float(resolved.get("price")) if isinstance(resolved, dict) else None
        if isinstance(ticker, dict) and last_price is not None:
            return {
                **ticker,
                "symbol": symbol,
                "lastPrice": ticker.get("lastPrice") or last_price,
                "source": _cache_payload_source(cached, default="binance_public_websocket_cache_primary"),
                "transport": "websocket_cache_primary",
            }
    try:
        resolved = resolve_current_price(redis_client, symbol) if redis_client is not None else {}
    except Exception:
        resolved = {}
    if isinstance(resolved, dict) and _safe_float(resolved.get("price")) is not None:
        price = _safe_float(resolved.get("price"))
        return {
            "symbol": symbol,
            "lastPrice": price,
            "bidPrice": resolved.get("bid"),
            "askPrice": resolved.get("ask"),
            "closeTime": resolved.get("available_at"),
            "source": resolved.get("source") or "binance_public_websocket_cache_primary",
            "transport": "websocket_cache_primary",
        }
    if _rest_fallback_disabled():
        return None
    try:
        data = _http_get_json(
            f"{BINANCE_FAPI}/fapi/v1/ticker/24hr?symbol={symbol}",
            fallback_reason="ticker_websocket_cache_and_current_price_resolver_missing",
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    data["source"] = "binance_public_rest_ticker_fallback"
    data["transport"] = "rest_fallback"
    return data


def _fetch_funding(symbol: str, *, redis_client: Any = None) -> dict | None:
    cached = _read_json(redis_client, f"{V2_REDIS_PREFIX}market:funding:{symbol}")
    if isinstance(cached, dict) and cached:
        return {
            **cached,
            "symbol": cached.get("symbol") or symbol,
            "source": _cache_payload_source(cached, default="binance_public_websocket_cache_primary"),
            "transport": "websocket_cache_primary",
        }
    prices = _read_json(redis_client, f"{V2_REDIS_PREFIX}market:prices:{symbol}")
    funding = prices.get("funding") if isinstance(prices, dict) and isinstance(prices.get("funding"), dict) else None
    if isinstance(funding, dict) and funding:
        return {
            **funding,
            "symbol": funding.get("symbol") or symbol,
            "source": _cache_payload_source(prices, default="binance_public_websocket_cache_primary"),
            "transport": "websocket_cache_primary",
        }
    if _rest_fallback_disabled():
        return None
    try:
        data = _http_get_json(
            f"{BINANCE_FAPI}/fapi/v1/premiumIndex?symbol={symbol}",
            fallback_reason="funding_websocket_cache_missing",
        )
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    data["source"] = "binance_public_rest_premium_index_fallback"
    data["transport"] = "rest_fallback"
    return data


def _fetch_open_interest(symbol: str, *, redis_client: Any = None) -> dict | None:
    cached = _read_json(redis_client, f"{V2_REDIS_PREFIX}market:open_interest:{symbol}")
    if isinstance(cached, dict) and cached:
        return {
            **cached,
            "symbol": cached.get("symbol") or symbol,
            "source": _cache_payload_source(cached, default="binance_public_websocket_cache_primary"),
            "transport": "websocket_cache_primary",
        }
    if _rest_fallback_disabled():
        return None
    try:
        data = _http_get_json(
            f"{BINANCE_FAPI}/fapi/v1/openInterest?symbol={symbol}",
            fallback_reason="open_interest_websocket_cache_missing",
        )
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    data["source"] = "binance_public_rest_open_interest_fallback"
    data["transport"] = "rest_fallback"
    return data


def _fetch_klines(
    symbol: str,
    interval: str = "1m",
    limit: int = 100,
    *,
    redis_client: Any = None,
) -> list | None:
    """Fetch a small OHLCV history from WebSocket cache, with REST fallback.

    WSS-backed closed-candle Redis keys are primary. Public REST is only used
    when the explicit fallback env flag is enabled.
    """
    for key in (
        closed_candle_key("binance", symbol, interval),
        f"{V2_REDIS_PREFIX}market:ohlcv:binance:{symbol}:{interval}",
    ):
        cached = _read_json(redis_client, key)
        if isinstance(cached, list) and cached:
            websocket_rows = [
                row
                for row in cached
                if isinstance(row, dict) and _is_websocket_cache_payload(row)
            ]
            if websocket_rows:
                return websocket_rows[-max(1, min(int(limit), len(websocket_rows))) :]
    current = _read_json(redis_client, current_candle_key("binance", symbol, interval))
    if (
        isinstance(current, dict)
        and current.get("is_closed") is True
        and _is_websocket_cache_payload(current)
    ):
        return [current]
    if _rest_fallback_disabled():
        return None
    try:
        data = _http_get_json(
            f"{BINANCE_FAPI}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={int(limit)}",
            fallback_reason="closed_kline_websocket_cache_missing_or_stale",
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    return data


def _fetch_open_interest_hist(symbol: str, period: str = "5m", limit: int = 13, *, redis_client: Any = None) -> list | None:
    """Fetch recent open-interest history from Binance Futures public data.

    Returns a list of rows, each: {symbol, sumOpenInterest, sumOpenInterestValue,
    timestamp}. Public endpoint (``/futures/data/openInterestHist``), no key.
    Used by the feature pipeline to compute real ``oi_change_pct`` instead of a
    silent zero. ``limit=13`` at 5m spans ~1h.
    """
    cached = _read_json(redis_client, f"{V2_REDIS_PREFIX}market:open_interest_hist:{symbol}:{period}")
    if isinstance(cached, list) and cached:
        return cached[-max(1, min(int(limit), len(cached))) :]
    if _rest_fallback_disabled():
        return None
    try:
        data = _http_get_json(
            f"{BINANCE_FAPI}/futures/data/openInterestHist"
            f"?symbol={symbol}&period={period}&limit={int(limit)}",
            fallback_reason="open_interest_history_cache_missing",
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    return data


def _fetch_long_short_ratio(symbol: str, period: str = "5m", limit: int = 1, *, redis_client: Any = None) -> dict | None:
    """Fetch Binance Futures global long/short account ratio.

    Endpoint is public and keyless, but may be unavailable from restricted
    jurisdictions. Non-list Binance error payloads intentionally return None so
    downstream code sees a missing source instead of a fabricated neutral value.
    """
    cached = _read_json(redis_client, f"{V2_REDIS_PREFIX}market:long_short:{symbol}")
    if isinstance(cached, dict) and cached:
        return {
            **cached,
            "symbol": str(cached.get("symbol") or symbol).upper(),
            "source": _cache_payload_source(cached, default="binance_public_websocket_cache_primary"),
            "transport": "websocket_cache_primary",
        }
    if _rest_fallback_disabled():
        return None
    try:
        data = _http_get_json(
            f"{BINANCE_FAPI}/futures/data/globalLongShortAccountRatio?"
            + urlencode({"symbol": symbol, "period": period, "limit": int(limit)}),
            fallback_reason="long_short_ratio_cache_missing",
        )
    except Exception:
        return None
    if not isinstance(data, list) or not data:
        return None
    row = data[-1]
    if not isinstance(row, dict):
        return None
    return {
        "symbol": str(row.get("symbol") or symbol).upper(),
        "period": period,
        "longShortRatio": row.get("longShortRatio"),
        "longAccount": row.get("longAccount"),
        "shortAccount": row.get("shortAccount"),
        "timestamp": row.get("timestamp"),
        "long_short_ratio": _safe_float(row.get("longShortRatio")),
        "long_account_ratio": _safe_float(row.get("longAccount")),
        "short_account_ratio": _safe_float(row.get("shortAccount")),
        "source": "binance_global_long_short_account_ratio_rest_fallback",
        "transport": "rest_fallback",
        "fetched_utc": _utc_iso(),
    }


def _fetch_orderbook_top(symbol: str, depth: int = 20, *, redis_client: Any = None) -> dict | None:
    """Fetch public order-book top from WebSocket cache, with REST fallback.

    Returns dict with ``bids`` and ``asks`` lists of [price, qty]. Used by the
    feature pipeline for real ``depth_imbalance``.
    """
    for key in (
        f"{V2_REDIS_PREFIX}orderbook:top:binance:{symbol}",
        f"{V2_REDIS_PREFIX}market:orderbook:binance:{symbol}",
        f"{V2_REDIS_PREFIX}market:orderbook:{symbol}",
    ):
        cached = _read_json(redis_client, key)
        if isinstance(cached, dict) and (
            cached.get("bids")
            or cached.get("asks")
            or cached.get("best_bid")
            or cached.get("best_ask")
        ):
            return {
                **cached,
                "symbol": cached.get("symbol") or symbol,
                "source": _cache_payload_source(cached, default="binance_public_websocket_orderbook_cache_primary"),
                "transport": "websocket_cache_primary",
            }
    if _rest_fallback_disabled():
        return None
    try:
        data = _http_get_json(
            f"{BINANCE_FAPI}/fapi/v1/depth?symbol={symbol}&limit={int(depth)}",
            fallback_reason="orderbook_websocket_cache_missing_or_stale",
        )
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    data["source"] = "binance_public_rest_depth_snapshot_fallback"
    data["transport"] = "rest_fallback"
    return data


def _fetch_symbol_bundle(
    symbol: str,
    *,
    kline_timeframes: tuple[str, ...] = DEFAULT_KLINE_TIMEFRAMES,
    redis_client: Any = None,
) -> dict:
    ticker = _fetch_ticker_24hr(symbol, redis_client=redis_client)
    funding = _fetch_funding(symbol, redis_client=redis_client)
    oi = _fetch_open_interest(symbol, redis_client=redis_client)
    klines_by_timeframe = {
        tf: rows
        for tf in kline_timeframes
        if (rows := _fetch_klines(symbol, interval=tf, limit=100, redis_client=redis_client)) is not None
    }
    klines = klines_by_timeframe.get("1m")
    orderbook = _fetch_orderbook_top(symbol, depth=20, redis_client=redis_client)
    oi_hist = _fetch_open_interest_hist(symbol, period="5m", limit=13, redis_client=redis_client)
    long_short = _fetch_long_short_ratio(symbol, period="5m", limit=1, redis_client=redis_client)
    cache_primary_count = sum(
        1
        for payload in (ticker, funding, oi, orderbook, long_short)
        if isinstance(payload, dict) and str(payload.get("transport") or "").startswith("websocket")
    ) + len(klines_by_timeframe)
    rest_fallback_count = sum(
        1
        for payload in (ticker, funding, oi, orderbook, long_short)
        if isinstance(payload, dict) and str(payload.get("transport") or "") == "rest_fallback"
    )
    return {
        "symbol": symbol,
        "source": "binance_public_websocket_cache_primary",
        "transport": "websocket_cache_primary",
        "rest_fallback_used": rest_fallback_count > 0,
        "ticker": ticker,
        "funding": funding,
        "open_interest": oi,
        "long_short": long_short,
        "klines": klines,
        "klines_by_timeframe": klines_by_timeframe,
        "orderbook": orderbook,
        "open_interest_hist": oi_hist,
        "symbol_info": {
            "symbol": symbol,
            "ticker_present": ticker is not None,
            "funding_present": funding is not None,
            "open_interest_present": oi is not None,
            "long_short_present": long_short is not None,
            "open_interest_hist_present": oi_hist is not None,
            "klines_present": klines is not None,
            "kline_timeframes_present": sorted(klines_by_timeframe),
            "orderbook_present": orderbook is not None,
            "cache_primary_field_count": cache_primary_count,
            "rest_fallback_field_count": rest_fallback_count,
        },
    }


def run_once(
    symbols: tuple[str, ...],
    *,
    kline_timeframes: tuple[str, ...] = DEFAULT_KLINE_TIMEFRAMES,
) -> dict:
    started_at = _utc_iso()
    symbols = tuple(
        symbol
        for symbol in (str(s or "").strip().upper() for s in symbols)
        if is_valid_runtime_symbol(symbol)
    )
    r = _connect_redis()
    redis_ok = r is not None
    keys_written: list[str] = []
    symbol_results: list[dict] = []
    fetched_by_symbol: dict[str, dict] = {}
    max_workers = max(1, min(MAX_FETCH_WORKERS, len(symbols) or 1))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_fetch_symbol_bundle, sym, kline_timeframes=kline_timeframes, redis_client=r): sym
            for sym in symbols
        }
        for future in as_completed(futures):
            sym = futures[future]
            try:
                fetched_by_symbol[sym] = future.result()
            except Exception:
                fetched_by_symbol[sym] = {
                    "symbol": sym,
                    "ticker": None,
                    "funding": None,
                    "open_interest": None,
                    "klines": None,
                    "klines_by_timeframe": {},
                    "orderbook": None,
                    "open_interest_hist": None,
                    "symbol_info": {
                        "symbol": sym,
                        "ticker_present": False,
                    "funding_present": False,
                    "open_interest_present": False,
                    "long_short_present": False,
                    "open_interest_hist_present": False,
                        "klines_present": False,
                        "kline_timeframes_present": [],
                        "orderbook_present": False,
                    },
                }
            _write_symbol_bundle(r, sym, fetched_by_symbol[sym], keys_written)
    for sym in symbols:
        bundle = fetched_by_symbol.get(sym) or _fetch_symbol_bundle(sym, redis_client=r)
        sym_info = bundle.get("symbol_info") or {"symbol": sym}
        if redis_ok and sym not in fetched_by_symbol:
            _write_symbol_bundle(r, sym, bundle, keys_written)
        symbol_results.append(sym_info)
    heartbeat = {
        "worker_id": "v2_native_ingestors_live_loop",
        "schema_version": "v2_native_ingestors_live_v1",
        "started_at": started_at,
        "finished_at": _utc_iso(),
        "symbols": list(symbols),
        "kline_timeframes": list(kline_timeframes),
        "redis_ok": redis_ok,
        "v2_market_keys_written": keys_written,
        "v2_market_keys_written_count": len(keys_written),
        "symbol_results": symbol_results,
        "classification": (
            "NATIVE_V2_PUBLIC_WEBSOCKET_CACHE_OK"
            if redis_ok and any(s.get("cache_primary_field_count", 0) for s in symbol_results)
            else (
                "NATIVE_V2_PUBLIC_REST_FALLBACK_OK"
                if redis_ok and any(s.get("ticker_present") for s in symbol_results) and binance_rest_fallback_allowed()
                else (
                    "BLOCKED_BY_REDIS_UNAVAILABLE"
                    if not redis_ok
                    else "BLOCKED_BY_NETWORK_OR_API"
                )
            )
        ),
        "transport_policy": "binance_public_websocket_cache_primary_rest_fallback_only",
        "rest_fallback_allowed": binance_rest_fallback_allowed(),
        "rest_fallback_env": REST_FALLBACK_ENV,
        "runtime_mode": "LIVE_MARKET_DATA_PAPER_EXECUTION_DISABLED",
        "live_data_enabled": True,
        "live_decision_input_enabled": True,
        "trader_execution_enabled": False,
        "execution_live_symbols": [],
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
    }
    if redis_ok:
        _safe_write(
            r,
            f"{V2_REDIS_PREFIX}market:ingestor:heartbeat",
            json.dumps(heartbeat),
            ex=300,
        )
        _safe_write(
            r,
            f"{V2_REDIS_PREFIX}market:ohlcv:binance:heartbeat",
            json.dumps(heartbeat),
            ex=300,
        )
        _safe_write(
            r,
            f"{V2_REDIS_PREFIX}market:orderbook:binance:heartbeat",
            json.dumps(heartbeat),
            ex=300,
        )
        _safe_write(
            r,
            f"{V2_REDIS_PREFIX}market:ingestor:status",
            heartbeat["classification"],
            ex=300,
        )
    return heartbeat


def write_payload(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    except OSError as exc:
        # Disk full (errno 28) or other IO error — log and continue rather than crash
        import errno as _errno
        print(
            f"[write_payload] WARNING: could not write {path}: {exc}"
            + (" (disk full — check available space)" if exc.errno == _errno.ENOSPC else ""),
            file=sys.stderr,
        )


def _build_fetch_in_progress_payload(symbols: tuple[str, ...]) -> dict:
    return {
        "worker_id": "v2_native_ingestors_live_loop",
        "schema_version": "v2_native_ingestors_live_v1",
        "started_at": _utc_iso(),
        "finished_at": None,
        "symbols": list(symbols),
        "kline_timeframes": list(DEFAULT_KLINE_TIMEFRAMES),
        "redis_ok": None,
        "v2_market_keys_written": [],
        "v2_market_keys_written_count": 0,
        "symbol_results": [],
        "classification": "NATIVE_V2_PUBLIC_WEBSOCKET_CACHE_FETCH_IN_PROGRESS",
        "transport_policy": "binance_public_websocket_cache_primary_rest_fallback_only",
        "rest_fallback_allowed": binance_rest_fallback_allowed(),
        "rest_fallback_env": REST_FALLBACK_ENV,
        "runtime_mode": "LIVE_MARKET_DATA_PAPER_EXECUTION_DISABLED",
        "live_data_enabled": True,
        "live_decision_input_enabled": True,
        "trader_execution_enabled": False,
        "execution_live_symbols": [],
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
    }


def _resolve_runtime_symbols(raw_symbols: str | None, *, smoke_test: bool) -> tuple[str, ...]:
    return tuple(
        symbol
        for symbol in resolve_symbols(
            explicit=raw_symbols,
            smoke_test=smoke_test,
            include_baseline=True,
        )
        if is_valid_runtime_symbol(symbol)
    )


def _parse_csv_timeframes(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return DEFAULT_KLINE_TIMEFRAMES
    out: list[str] = []
    for part in raw.split(","):
        tf = part.strip()
        if tf and tf not in out:
            out.append(tf)
    return tuple(out) or DEFAULT_KLINE_TIMEFRAMES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_native_ingestors_live_loop")
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
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument(
        "--fetch-timeframes",
        default=",".join(DEFAULT_KLINE_TIMEFRAMES),
        help="Comma-separated Binance kline timeframes to fetch for V2 OHLCV/TA.",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_PAYLOAD_PATH)
    args = parser.parse_args(argv)
    if args.loop and args.once:
        print("ERROR: --loop and --once are mutually exclusive", file=sys.stderr)
        return 2
    if args.loop:
        while True:
            symbols = _resolve_runtime_symbols(args.symbols, smoke_test=args.smoke_test)
            write_payload(_build_fetch_in_progress_payload(symbols), args.out)
            hb = run_once(symbols, kline_timeframes=_parse_csv_timeframes(args.fetch_timeframes))
            write_payload(hb, args.out)
            time.sleep(max(5, int(args.interval_seconds)))
    symbols = _resolve_runtime_symbols(args.symbols, smoke_test=args.smoke_test)
    hb = run_once(symbols, kline_timeframes=_parse_csv_timeframes(args.fetch_timeframes))
    write_payload(hb, args.out)
    print(json.dumps({
        "classification": hb["classification"],
        "v2_market_keys_written_count": hb["v2_market_keys_written_count"],
        "redis_ok": hb["redis_ok"],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
