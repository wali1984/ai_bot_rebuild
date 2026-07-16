"""One-shot Binance kline cache backfill for symbols missing closed history.

Reads Binance WebSocket-backed kline cache first and writes to
v2:market:ohlcv_closed:binance:{symbol}:{timeframe} using the canonical format.
Public REST is fallback-only and requires BINANCE_REST_FALLBACK_ALLOWED=true.

Run once to seed missing 1h/4h closed-candle history so the feature pipeline
can compute taker/HTF features for all 87 trainer symbols.

Safe: read-only market data only. No orders. No credentials.
"""

from __future__ import annotations

import argparse
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
    TIMEFRAME_SECONDS,
    append_closed_candle,
    canonical_from_binance_rest,
    closed_candle_key,
    current_candle_key,
)
from v2.backend.app.services.v2_symbol_runtime_universe import (  # noqa: E402
    is_valid_runtime_symbol,
    resolve_symbols,
)

BINANCE_FAPI = "https://fapi.binance.com"
BACKFILL_LIMIT = 200
BACKFILL_TIMEFRAMES = ("1h", "4h")
MIN_CANDLES_THRESHOLD = 50
CACHE_FRESHNESS_GRACE_SECONDS = 300


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


def _row_close_ms(row) -> int | None:
    close_ms = None
    if isinstance(row, dict):
        close_ms = row.get("candle_close_time") or row.get("close_time")
    elif isinstance(row, (list, tuple)) and len(row) >= 7:
        close_ms = row[6]
    try:
        return int(float(close_ms)) if close_ms is not None else None
    except (TypeError, ValueError):
        return None


def _cache_fresh_and_sufficient(rows: list, interval: str, *, min_rows: int) -> bool:
    """Websocket cache counts only if it is deep enough AND its newest close
    is recent (age < timeframe period + grace). A stale-but-present cache
    previously short-circuited REST and made the backfill a no-op, leaving
    keys like BTCUSDT:4h hundreds of minutes behind."""
    if not isinstance(rows, list) or len(rows) < max(1, int(min_rows)):
        return False
    newest = max((ms for ms in (_row_close_ms(row) for row in rows) if ms is not None), default=None)
    if newest is None:
        return False
    interval_seconds = TIMEFRAME_SECONDS.get(str(interval), 3600)
    age_seconds = time.time() - newest / 1000.0
    return age_seconds < interval_seconds + CACHE_FRESHNESS_GRACE_SECONDS


def _fetch_klines(r: redis.Redis, symbol: str, interval: str, limit: int = BACKFILL_LIMIT) -> tuple[list, str]:
    min_rows = min(int(limit), MIN_CANDLES_THRESHOLD)
    stale_cache: list | None = None
    for key in (
        closed_candle_key("binance", symbol, interval),
        f"v2:market:ohlcv:binance:{symbol}:{interval}",
    ):
        cached = _read_json(r, key)
        if isinstance(cached, list) and cached:
            trimmed = cached[-max(1, min(int(limit), len(cached))) :]
            if _cache_fresh_and_sufficient(trimmed, interval, min_rows=min_rows):
                return trimmed, "websocket_cache_primary"
            if stale_cache is None:
                stale_cache = trimmed
    current = _read_json(r, current_candle_key("binance", symbol, interval))
    current_closed = isinstance(current, dict) and (
        current.get("is_closed") is True
        or current.get("closed_candle") is True
        or current.get("candle_closed_confirmed") is True
    )
    if not binance_rest_fallback_allowed():
        # Websocket-primary posture preserved: without REST permission the
        # old lenient cache behavior still applies (better one stale/shallow
        # candle than nothing), and _http_get below raises the explicit
        # REST-disabled error when there is no cache at all.
        if stale_cache:
            return stale_cache, "websocket_cache_primary"
        if current_closed:
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


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--symbols",
        default=None,
        help=(
            "Comma-separated symbols to backfill (e.g. BTCUSDT,ETHUSDT), or "
            "'auto' for the resolved runtime symbol universe. Default: scan "
            "v2:market:kline_current:binance:* and backfill only symbols "
            "below the closed-candle threshold (legacy behavior)."
        ),
    )
    parser.add_argument(
        "--timeframes",
        default=",".join(BACKFILL_TIMEFRAMES),
        help="Comma-separated timeframes to backfill (default: %(default)s).",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.15,
        help="Sleep between symbol/timeframe requests (rate-limit friendly).",
    )
    return parser.parse_args(argv)


def _resolve_backfill_targets(r: redis.Redis, args: argparse.Namespace) -> dict[str, list[str]]:
    timeframes = tuple(tf.strip() for tf in str(args.timeframes or "").split(",") if tf.strip()) or BACKFILL_TIMEFRAMES
    unknown = [tf for tf in timeframes if tf not in TIMEFRAME_SECONDS]
    if unknown:
        raise SystemExit(f"[backfill] unknown timeframes {unknown}; allowed: {sorted(TIMEFRAME_SECONDS)}")
    raw = (args.symbols or "").strip()
    if not raw:
        return _missing_symbols(r, timeframes)
    if raw.lower() in {"auto", "all", "universe"}:
        symbols = list(resolve_symbols())
    else:
        # One-shot operator-directed target list, parsed locally so an
        # explicit majors-only repair run does not trip the runtime
        # smoke-test drift guard inside resolve_symbols().
        symbols = []
        seen: set[str] = set()
        for part in raw.split(","):
            text = part.strip().upper()
            if not text or text in seen:
                continue
            if not is_valid_runtime_symbol(text):
                print(f"[backfill] skipping invalid symbol {text!r}")
                continue
            seen.add(text)
            symbols.append(text)
    return {sym: list(timeframes) for sym in symbols}


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    r = _redis_client()
    print(f"[backfill] Connected to Redis. transport=websocket_cache_primary rest_fallback_allowed={binance_rest_fallback_allowed()}")
    missing = _resolve_backfill_targets(r, args)
    print(f"[backfill] {len(missing)} symbols to backfill:")
    for sym, tfs in sorted(missing.items()):
        print(f"  {sym}: {tfs}")

    results = []
    sleep_seconds = max(0.0, float(args.sleep_seconds))
    total_syms = len(missing)
    for idx, (sym, tfs) in enumerate(sorted(missing.items()), 1):
        for tf in tfs:
            try:
                result = _backfill_symbol_tf(r, sym, tf)
                results.append({**result, "status": "ok"})
                print(f"[{idx}/{total_syms}] {sym}/{tf}: +{result['closed_ingested']} → {result['total_in_key']} total ({result['transport']})")
            except Exception as exc:
                results.append({"symbol": sym, "tf": tf, "status": "error", "error": str(exc)})
                print(f"[{idx}/{total_syms}] {sym}/{tf}: ERROR — {exc}")
            time.sleep(sleep_seconds)

    ok_list = [res for res in results if res["status"] == "ok"]
    err_list = [res for res in results if res["status"] == "error"]
    print(f"\n[backfill] Done. {len(ok_list)} ok, {len(err_list)} errors.")
    if err_list:
        print("Errors:")
        for e in err_list:
            print(f"  {e['symbol']}/{e['tf']}: {e.get('error')}")


if __name__ == "__main__":
    main()
