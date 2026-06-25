"""V2 native ingestors live loop (paper/shadow, V2-namespace only).

Public market data only. Writes to v2:* Redis namespace ONLY.
No exchange mutation. No legacy Redis writes.

Default behavior:
- pulls Binance public REST endpoints (no API key) for a small symbol
  set, writes v2:market:prices:* / v2:market:funding:* /
  v2:market:open_interest:*
- when the network is unavailable, writes the heartbeat with a
  BLOCKED_BY_NETWORK_OR_API status and no price data
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


def _http_get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "v2-native-ingestor/1.0"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
    payload = {
        "symbol": sym,
        "source": "binance_public_rest",
        "ticker_24hr": ticker,
        "funding": funding,
        "open_interest": oi,
        "long_short": long_short,
        "fetched_utc": _utc_iso(),
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


def _fetch_ticker_24hr(symbol: str) -> dict | None:
    try:
        data = _http_get_json(f"{BINANCE_FAPI}/fapi/v1/ticker/24hr?symbol={symbol}")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _fetch_funding(symbol: str) -> dict | None:
    try:
        data = _http_get_json(
            f"{BINANCE_FAPI}/fapi/v1/premiumIndex?symbol={symbol}"
        )
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _fetch_open_interest(symbol: str) -> dict | None:
    try:
        data = _http_get_json(f"{BINANCE_FAPI}/fapi/v1/openInterest?symbol={symbol}")
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _fetch_klines(symbol: str, interval: str = "1m", limit: int = 100) -> list | None:
    """Fetch a small OHLCV history from Binance public REST.

    Returns a list of bars, each: [open_time, open, high, low, close, volume, ...].
    Public endpoint, no key. Used by the feature pipeline to compute real
    TA (RSI/MACD/EMA/ATR/BB) instead of hardcoded constants.
    """
    try:
        data = _http_get_json(
            f"{BINANCE_FAPI}/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={int(limit)}"
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    return data


def _fetch_open_interest_hist(symbol: str, period: str = "5m", limit: int = 13) -> list | None:
    """Fetch recent open-interest history from Binance Futures public data.

    Returns a list of rows, each: {symbol, sumOpenInterest, sumOpenInterestValue,
    timestamp}. Public endpoint (``/futures/data/openInterestHist``), no key.
    Used by the feature pipeline to compute real ``oi_change_pct`` instead of a
    silent zero. ``limit=13`` at 5m spans ~1h.
    """
    try:
        data = _http_get_json(
            f"{BINANCE_FAPI}/futures/data/openInterestHist"
            f"?symbol={symbol}&period={period}&limit={int(limit)}"
        )
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return None
    if not isinstance(data, list):
        return None
    return data


def _fetch_long_short_ratio(symbol: str, period: str = "5m", limit: int = 1) -> dict | None:
    """Fetch Binance Futures global long/short account ratio.

    Endpoint is public and keyless, but may be unavailable from restricted
    jurisdictions. Non-list Binance error payloads intentionally return None so
    downstream code sees a missing source instead of a fabricated neutral value.
    """
    try:
        data = _http_get_json(
            f"{BINANCE_FAPI}/futures/data/globalLongShortAccountRatio?"
            + urlencode({"symbol": symbol, "period": period, "limit": int(limit)})
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
        "source": "binance_global_long_short_account_ratio",
        "fetched_utc": _utc_iso(),
    }


def _fetch_orderbook_top(symbol: str, depth: int = 20) -> dict | None:
    """Fetch a public order-book snapshot from Binance Futures.

    Returns dict with ``bids`` and ``asks`` lists of [price, qty]. Public,
    no key. Used by the feature pipeline for real ``depth_imbalance``.
    """
    try:
        data = _http_get_json(
            f"{BINANCE_FAPI}/fapi/v1/depth?symbol={symbol}&limit={int(depth)}"
        )
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _fetch_symbol_bundle(
    symbol: str,
    *,
    kline_timeframes: tuple[str, ...] = DEFAULT_KLINE_TIMEFRAMES,
) -> dict:
    ticker = _fetch_ticker_24hr(symbol)
    funding = _fetch_funding(symbol)
    oi = _fetch_open_interest(symbol)
    klines_by_timeframe = {
        tf: rows
        for tf in kline_timeframes
        if (rows := _fetch_klines(symbol, interval=tf, limit=100)) is not None
    }
    klines = klines_by_timeframe.get("1m")
    orderbook = _fetch_orderbook_top(symbol, depth=20)
    oi_hist = _fetch_open_interest_hist(symbol, period="5m", limit=13)
    long_short = _fetch_long_short_ratio(symbol, period="5m", limit=1)
    return {
        "symbol": symbol,
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
            executor.submit(_fetch_symbol_bundle, sym, kline_timeframes=kline_timeframes): sym
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
        bundle = fetched_by_symbol.get(sym) or _fetch_symbol_bundle(sym)
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
            "NATIVE_V2_PUBLIC_REST_OK"
            if redis_ok and any(s.get("ticker_present") for s in symbol_results)
            else (
                "BLOCKED_BY_REDIS_UNAVAILABLE"
                if not redis_ok
                else "BLOCKED_BY_NETWORK_OR_API"
            )
        ),
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
        "classification": "NATIVE_V2_PUBLIC_REST_FETCH_IN_PROGRESS",
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
