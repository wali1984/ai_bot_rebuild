"""One-shot Binance kline cache backfill for symbols missing closed history.

Reads Binance WebSocket-backed kline cache first and writes to
v2:market:ohlcv_closed:binance:{symbol}:{timeframe} using the canonical format.
Public REST is fallback-only and requires BINANCE_REST_FALLBACK_ALLOWED=true.

Run once to seed missing 1h/4h closed-candle history so the feature pipeline
can compute taker/HTF features for all 87 trainer symbols.

Safe: read-only market data only. No orders. No credentials.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

_repo = Path(__file__).resolve().parents[4]
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))

import redis  # noqa: E402

from v2.backend.app.services.binance_unified_websocket_transport import (  # noqa: E402
    REST_FALLBACK_ENV,
    binance_rest_fallback_allowed,
    require_binance_rest_fallback,
)
from v2.backend.app.services.market_state_integrity.canonical_candles import (  # noqa: E402
    append_closed_candle,
    canonical_from_binance_rest,
    closed_candle_key,
    current_candle_key,
)

BINANCE_FAPI = "https://fapi.binance.com"
BACKFILL_LIMIT = 200
BACKFILL_TIMEFRAMES = ("1h", "4h")
MIN_CANDLES_THRESHOLD = 50


def _redis_client() -> redis.Redis:
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.Redis.from_url(url, decode_responses=True)


def _http_get(url: str, *, retries: int = 3, backoff: float = 2.0) -> list:
    try:
        require_binance_rest_fallback(
            endpoint=urllib.parse.urlparse(url).path or url,
            fallback_reason="operator_requested_kline_gap_backfill",
            role="kline_gap_backfill_recovery",
        )
    except RuntimeError as exc:
        message = str(exc).replace(
            "REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
            "BINANCE_REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
            1,
        )
        raise RuntimeError(message) from exc
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "v2-backfill/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except Exception as exc:
            if attempt < retries - 1:
                time.sleep(backoff * (attempt + 1))
            else:
                raise RuntimeError(f"HTTP failed after {retries} attempts: {url} — {exc}") from exc
    return []


def _read_json(r: redis.Redis, key: str):
    raw = r.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _fetch_klines(r: redis.Redis, symbol: str, interval: str, limit: int = BACKFILL_LIMIT) -> tuple[list, str]:
    for key in (
        closed_candle_key("binance", symbol, interval),
        f"v2:market:ohlcv:binance:{symbol}:{interval}",
    ):
        cached = _read_json(r, key)
        if isinstance(cached, list) and cached:
            return cached[-max(1, min(int(limit), len(cached))) :], "websocket_cache_primary"
    current = _read_json(r, current_candle_key("binance", symbol, interval))
    if isinstance(current, dict) and (
        current.get("is_closed") is True
        or current.get("closed_candle") is True
        or current.get("candle_closed_confirmed") is True
    ):
        return [current], "websocket_cache_primary"
    qs = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "limit": limit})
    url = f"{BINANCE_FAPI}/fapi/v1/klines?{qs}"
    rows = _http_get(url)
    if not isinstance(rows, list):
        raise ValueError(f"Unexpected klines response type for {symbol}/{interval}: {type(rows)}")
    return rows, "rest_fallback"


def _missing_symbols(r: redis.Redis, timeframes: tuple[str, ...]) -> dict[str, list[str]]:
    """Return {symbol: [missing_tfs]} for symbols below threshold."""
    missing: dict[str, list[str]] = {}
    kline_syms: set[str] = set()
    for k in r.keys("v2:market:kline_current:binance:*"):
        parts = k.split(":")
        if len(parts) >= 5:
            kline_syms.add(parts[4])

    for sym in sorted(kline_syms):
        missing_tfs: list[str] = []
        for tf in timeframes:
            key = closed_candle_key("binance", sym, tf)
            raw = r.get(key)
            count = 0
            if raw:
                try:
                    existing = json.loads(raw)
                    count = len(existing) if isinstance(existing, list) else 0
                except Exception:
                    count = 0
            if count < MIN_CANDLES_THRESHOLD:
                missing_tfs.append(tf)
        if missing_tfs:
            missing[sym] = missing_tfs
    return missing


def _backfill_symbol_tf(r: redis.Redis, symbol: str, tf: str) -> dict:
    key = closed_candle_key("binance", symbol, tf)
    raw = r.get(key)
    existing = json.loads(raw) if raw else []

    rows, source_transport = _fetch_klines(r, symbol, tf, BACKFILL_LIMIT)
    now_ms = int(time.time() * 1000)
    closed_rows = []
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) >= 7 and int(row[6]) <= now_ms:
            closed_rows.append(row)
        elif isinstance(row, dict) and (
            row.get("is_closed") is True
            or row.get("closed_candle") is True
            or row.get("candle_closed_confirmed") is True
        ):
            close_ms = row.get("candle_close_time") or row.get("close_time")
            try:
                if close_ms is not None and int(float(close_ms)) <= now_ms:
                    closed_rows.append(row)
            except (TypeError, ValueError):
                continue

    candles_added = 0
    for row in closed_rows:
        if isinstance(row, dict):
            existing = append_closed_candle(existing, row, limit=1500)
            candles_added += 1
        else:
            candle = canonical_from_binance_rest(row, symbol=symbol, timeframe=tf)
            if candle.is_closed:
                existing = append_closed_candle(existing, candle.to_dict(), limit=1500)
                candles_added += 1

    if existing:
        r.set(key, json.dumps(existing, sort_keys=True, default=str))  # no TTL — permanent

    return {
        "symbol": symbol,
        "tf": tf,
        "rows_fetched": len(rows),
        "closed_ingested": candles_added,
        "total_in_key": len(existing),
        "transport": source_transport,
        "rest_fallback_used": source_transport == "rest_fallback",
    }


def main() -> None:
    r = _redis_client()
    print(f"[backfill] Connected to Redis. Scanning for symbols missing {BACKFILL_TIMEFRAMES} ohlcv_closed data...")
    print(f"[backfill] transport=websocket_cache_primary rest_fallback_allowed={binance_rest_fallback_allowed()}")
    missing = _missing_symbols(r, BACKFILL_TIMEFRAMES)
    print(f"[backfill] {len(missing)} symbols need backfill:")
    for sym, tfs in sorted(missing.items()):
        print(f"  {sym}: {tfs}")

    results = []
    total_syms = len(missing)
    for idx, (sym, tfs) in enumerate(sorted(missing.items()), 1):
        for tf in tfs:
            try:
                result = _backfill_symbol_tf(r, sym, tf)
                results.append({**result, "status": "ok"})
                print(f"[{idx}/{total_syms}] {sym}/{tf}: +{result['closed_ingested']} → {result['total_in_key']} total")
            except Exception as exc:
                results.append({"symbol": sym, "tf": tf, "status": "error", "error": str(exc)})
                print(f"[{idx}/{total_syms}] {sym}/{tf}: ERROR — {exc}")
            time.sleep(0.15)

    ok_list = [res for res in results if res["status"] == "ok"]
    err_list = [res for res in results if res["status"] == "error"]
    print(f"\n[backfill] Done. {len(ok_list)} ok, {len(err_list)} errors.")
    if err_list:
        print("Errors:")
        for e in err_list:
            print(f"  {e['symbol']}/{e['tf']}: {e.get('error')}")


if __name__ == "__main__":
    main()
