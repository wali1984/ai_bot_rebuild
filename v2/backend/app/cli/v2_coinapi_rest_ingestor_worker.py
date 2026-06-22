"""V2 CoinAPI REST fallback ingestor (paper-only, V2 Redis namespace).

Ports the safe subset of legacy ``ingest/live_coinapi_rest.py`` and
``ingest/live_coinapi_v1.py``:
- keyed REST GETs to CoinAPI orderbook snapshot endpoint
- keyed REST GETs to CoinAPI V1 latest OHLCV endpoint
- bounded/rate-limited polling
- microstructure snapshot normalization
- OHLCV compatibility keys used by the V2 feature pipeline
- V2-only Redis writes

No exchange orders, no leverage/margin changes, no legacy Redis keys.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols


WORKER_ID = "v2_coinapi_rest_ingestor"
V2_REDIS_PREFIX = "v2:"
COINAPI_REST_BASE = "https://rest.coinapi.io"

DEFAULT_SECRET_PATHS = (
    Path(".local_secrets/legacy.env"),
    Path(".local_secrets/live_credentials.env"),
    Path("v2/.env.local"),
)


def _read_secret_value(name: str) -> str:
    """Read a secret from env var first, then from local secret files.
    Mirrors the pattern used by v2_coinapi_wsds_loop so both workers can
    find the API key from the same source.
    """
    if os.getenv(name):
        return str(os.getenv(name) or "")
    for path in DEFAULT_SECRET_PATHS:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key.startswith("export "):
                key = key[len("export "):].strip()
            if key == name:
                v = value.strip().strip('"').strip("'")
                if v:
                    return v
    return ""
COINAPI_PERIOD_MAP = {
    "1m": "1MIN",
    "5m": "5MIN",
    "15m": "15MIN",
    "1h": "1HRS",
    "4h": "4HRS",
    "1d": "1DAY",
}
DEFAULT_OHLCV_TIMEFRAMES = ("1m", "5m")
DEFAULT_OHLCV_SYMBOL_LIMIT = 3
DEFAULT_PAYLOAD_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_coinapi_rest_ingestor/latest/"
    "v2_coinapi_rest_ingestor_status.json"
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _coinapi_symbol_id(symbol: str, *, exchange_id: str = "BINANCEFTS") -> str:
    base = symbol.upper()
    if base.endswith("USDT"):
        base = base[:-4]
    return f"{exchange_id.upper()}_PERP_{base}_USDT"


def _http_get_json(
    base_url: str,
    path: str,
    *,
    api_key: str,
    params: dict[str, Any],
    timeout_seconds: float,
) -> tuple[int, Any]:
    query = urllib.parse.urlencode(params)
    url = f"{base_url.rstrip('/')}{path}"
    if query:
        url = f"{url}?{query}"
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "ai-bot-v2-coinapi-rest-readonly",
            "X-CoinAPI-Key": api_key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8")
            status = int(resp.status)
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read().decode("utf-8")
            data = json.loads(raw) if raw else None
        except Exception:
            data = None
        return int(exc.code), data
    except Exception:
        return 599, None
    try:
        return status, json.loads(raw) if raw else None
    except Exception:
        return status, raw


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except Exception:
        return None


def _normalize_orderbook(symbol: str, coinapi_symbol: str, body: Any) -> dict[str, Any] | None:
    row = body[0] if isinstance(body, list) and body else body
    if not isinstance(row, dict):
        return None
    bids = row.get("bids") if isinstance(row.get("bids"), list) else []
    asks = row.get("asks") if isinstance(row.get("asks"), list) else []
    if not bids or not asks:
        return None

    def _price_size(item: Any) -> tuple[float | None, float | None]:
        if isinstance(item, dict):
            return _safe_float(item.get("price")), _safe_float(item.get("size"))
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            return _safe_float(item[0]), _safe_float(item[1])
        return None, None

    bid_px, bid_sz = _price_size(bids[0])
    ask_px, ask_sz = _price_size(asks[0])
    if not bid_px or not ask_px:
        return None
    mid_px = (bid_px + ask_px) / 2.0
    spread_bps = ((ask_px - bid_px) / mid_px * 10_000.0) if mid_px else None
    bid_sum_5 = sum((_price_size(x)[1] or 0.0) for x in bids[:5])
    ask_sum_5 = sum((_price_size(x)[1] or 0.0) for x in asks[:5])
    total_5 = bid_sum_5 + ask_sum_5
    imbalance_5 = ((bid_sum_5 - ask_sum_5) / total_5) if total_5 else 0.0
    total_top = (bid_sz or 0.0) + (ask_sz or 0.0)
    micro_price = (
        ((bid_px * (ask_sz or 0.0)) + (ask_px * (bid_sz or 0.0))) / total_top
        if total_top
        else mid_px
    )
    return {
        "schema_version": "v2_coinapi_rest_orderbook_v1",
        "symbol": symbol,
        "coinapi_symbol_id": coinapi_symbol,
        "source": "coinapi_rest_orderbooks3_current",
        "generated_utc": _utc_iso(),
        "time_exchange": row.get("time_exchange"),
        "time_coinapi": row.get("time_coinapi"),
        "best_bid_px": bid_px,
        "best_ask_px": ask_px,
        "best_bid_sz": bid_sz,
        "best_ask_sz": ask_sz,
        "mid_px": mid_px,
        "spread_bps": spread_bps,
        "micro_price": micro_price,
        "book_bid_sum_5": bid_sum_5,
        "book_ask_sum_5": ask_sum_5,
        "imbalance_5": imbalance_5,
        "bids_top5": bids[:5],
        "asks_top5": asks[:5],
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }


def _normalize_ohlcv(
    symbol: str,
    coinapi_symbol: str,
    timeframe: str,
    period_id: str,
    body: Any,
) -> dict[str, Any] | None:
    row = body[0] if isinstance(body, list) and body else body
    if not isinstance(row, dict):
        return None
    open_px = _safe_float(row.get("price_open", row.get("open")))
    high_px = _safe_float(row.get("price_high", row.get("high")))
    low_px = _safe_float(row.get("price_low", row.get("low")))
    close_px = _safe_float(row.get("price_close", row.get("close")))
    volume = _safe_float(row.get("volume_traded", row.get("volume")))
    if open_px is None or high_px is None or low_px is None or close_px is None:
        return None
    updated_ts_ms = int(time.time() * 1000)
    return {
        "schema_version": "v2_coinapi_rest_ohlcv_v1",
        "symbol": symbol,
        "coinapi_symbol_id": coinapi_symbol,
        "timeframe": timeframe,
        "period_id": period_id,
        "time_period_start": row.get("time_period_start") or row.get("timestamp") or "",
        "time_period_end": row.get("time_period_end") or "",
        "time_open": row.get("time_open") or "",
        "time_close": row.get("time_close") or "",
        "open": open_px,
        "high": high_px,
        "low": low_px,
        "close": close_px,
        "volume": volume if volume is not None else 0.0,
        "trades_count": _safe_int(row.get("trades_count")) or 0,
        "updated_ts_ms": updated_ts_ms,
        "source": "coinapi_v1",
        "native_worker_id": WORKER_ID,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        r = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
        )
        r.ping()
        return r
    except Exception:
        return None


def _safe_set_json(redis_client: Any, key: str, payload: Any, *, ex: int) -> bool:
    if redis_client is None:
        return False
    if not key.startswith(V2_REDIS_PREFIX):
        raise ValueError(f"refused non-V2 Redis key: {key!r}")
    redis_client.set(key, json.dumps(payload, sort_keys=True, default=str), ex=int(ex))
    return True


def _safe_hset(redis_client: Any, key: str, mapping: dict[str, Any], *, ex: int) -> bool:
    if redis_client is None:
        return False
    if not key.startswith(V2_REDIS_PREFIX):
        raise ValueError(f"refused non-V2 Redis key: {key!r}")
    string_mapping = {
        str(k): "" if v is None else str(v)
        for k, v in mapping.items()
        if isinstance(k, str)
    }
    redis_client.hset(key, mapping=string_mapping)
    redis_client.expire(key, int(ex))
    return True


def _safe_rpush_json(redis_client: Any, key: str, payload: Any, *, ex: int, max_len: int = 2000) -> bool:
    if redis_client is None:
        return False
    if not key.startswith(V2_REDIS_PREFIX):
        raise ValueError(f"refused non-V2 Redis key: {key!r}")
    redis_client.rpush(key, json.dumps(payload, sort_keys=True, default=str))
    redis_client.ltrim(key, -int(max_len), -1)
    redis_client.expire(key, int(ex))
    return True


def _rate_limit_sleep(last_request: float, min_delay: float) -> None:
    wait = min_delay - (time.monotonic() - last_request)
    if wait > 0:
        time.sleep(wait)


def fetch_for_symbols(
    symbols: tuple[str, ...],
    *,
    api_key: str,
    rest_base_url: str,
    exchange_id: str,
    fetch_symbol_limit: int | None,
    fetch_ohlcv: bool,
    ohlcv_timeframes: tuple[str, ...],
    ohlcv_symbol_limit: int | None,
    timeout_seconds: float,
    max_rps: float,
) -> dict[str, Any]:
    started = _utc_iso()
    selected = tuple(symbols[:fetch_symbol_limit]) if fetch_symbol_limit else tuple(symbols)
    ohlcv_selected = (
        tuple(symbols[:ohlcv_symbol_limit])
        if ohlcv_symbol_limit and ohlcv_symbol_limit > 0
        else selected
    )
    ohlcv_selected_set = set(ohlcv_selected)
    rows: list[dict[str, Any]] = []
    min_delay = 1.0 / max(0.05, float(max_rps))
    last_request = 0.0
    for symbol in selected:
        _rate_limit_sleep(last_request, min_delay)
        coinapi_symbol = _coinapi_symbol_id(symbol, exchange_id=exchange_id)
        status, body = _http_get_json(
            rest_base_url,
            "/v1/orderbooks3/current",
            api_key=api_key,
            params={"filter_symbol_id": coinapi_symbol},
            timeout_seconds=timeout_seconds,
        )
        last_request = time.monotonic()
        normalized = _normalize_orderbook(symbol, coinapi_symbol, body)
        ohlcv_rows: dict[str, Any] = {}
        ohlcv_statuses: dict[str, int] = {}
        if fetch_ohlcv and symbol in ohlcv_selected_set:
            for timeframe in ohlcv_timeframes:
                period_id = COINAPI_PERIOD_MAP.get(timeframe)
                if not period_id:
                    ohlcv_statuses[timeframe] = 0
                    continue
                _rate_limit_sleep(last_request, min_delay)
                tf_status, tf_body = _http_get_json(
                    rest_base_url,
                    f"/v1/ohlcv/{urllib.parse.quote(coinapi_symbol, safe='')}/latest",
                    api_key=api_key,
                    params={"period_id": period_id, "limit": 1},
                    timeout_seconds=timeout_seconds,
                )
                last_request = time.monotonic()
                ohlcv_statuses[timeframe] = tf_status
                tf_normalized = _normalize_ohlcv(symbol, coinapi_symbol, timeframe, period_id, tf_body)
                if tf_normalized is not None:
                    ohlcv_rows[timeframe] = tf_normalized
        rows.append({
            "symbol": symbol,
            "coinapi_symbol_id": coinapi_symbol,
            "http_status": status,
            "orderbook": normalized,
            "orderbook_present": normalized is not None,
            "ohlcv_http_statuses": ohlcv_statuses,
            "ohlcv": ohlcv_rows,
            "ohlcv_present_timeframes": sorted(ohlcv_rows.keys()),
        })
    return {
        "started_utc": started,
        "finished_utc": _utc_iso(),
        "symbols_requested": len(symbols),
        "symbols_fetched": len(selected),
        "ohlcv_fetch_enabled": bool(fetch_ohlcv),
        "ohlcv_symbols_fetched": len(ohlcv_selected) if fetch_ohlcv else 0,
        "ohlcv_timeframes": list(ohlcv_timeframes) if fetch_ohlcv else [],
        "rows": rows,
    }


def persist_to_v2_redis(redis_client: Any, fetch: dict[str, Any], *, ttl_seconds: int) -> list[str]:
    written: list[str] = []
    for row in fetch.get("rows", []):
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        orderbook = row.get("orderbook")
        status_key = f"v2:market:coinapi:rest:status:{symbol}"
        if _safe_set_json(redis_client, status_key, row, ex=ttl_seconds):
            written.append(status_key)
        if isinstance(orderbook, dict):
            ob_key = f"v2:market:coinapi:rest:orderbook:{symbol}"
            feat_key = f"v2:features:coinapi_rest:{symbol}:latest"
            if _safe_set_json(redis_client, ob_key, orderbook, ex=ttl_seconds):
                written.append(ob_key)
            feature = {
                "symbol": symbol,
                "source": "coinapi_rest_orderbooks3_current",
                "spread_bps": orderbook.get("spread_bps"),
                "micro_price": orderbook.get("micro_price"),
                "depth_imbalance": orderbook.get("imbalance_5"),
                "book_bid_sum_5": orderbook.get("book_bid_sum_5"),
                "book_ask_sum_5": orderbook.get("book_ask_sum_5"),
                "generated_utc": orderbook.get("generated_utc"),
                "live_gate": "blocked_human_only",
                "live_symbols": [],
            }
            if _safe_set_json(redis_client, feat_key, feature, ex=ttl_seconds):
                written.append(feat_key)
        ohlcv_by_tf = row.get("ohlcv")
        if isinstance(ohlcv_by_tf, dict):
            for timeframe, candle in ohlcv_by_tf.items():
                if not isinstance(candle, dict):
                    continue
                latest_key = f"v2:latest:coinapi:ohlcv:{symbol}:{timeframe}"
                normalized_key = f"v2:normalized:ohlcv:{symbol}:{timeframe}"
                market_key = f"v2:market:{symbol}:{timeframe}"
                latest_binance_key = f"v2:latest:binance:ohlcv:{symbol}:{timeframe}"
                coinapi_market_key = f"v2:market:coinapi:ohlcv:{symbol}:{timeframe}"
                ohlcv_list_key = f"v2:ohlcv:list:coinapi:{symbol}:{timeframe}"
                hash_payload = {
                    "symbol": symbol,
                    "period_id": candle.get("period_id"),
                    "time_period_start": candle.get("time_period_start"),
                    "time_period_end": candle.get("time_period_end"),
                    "time_open": candle.get("time_open"),
                    "time_close": candle.get("time_close"),
                    "open": candle.get("open"),
                    "high": candle.get("high"),
                    "low": candle.get("low"),
                    "close": candle.get("close"),
                    "volume": candle.get("volume"),
                    "trades_count": candle.get("trades_count"),
                    "updated_ts_ms": candle.get("updated_ts_ms"),
                    "source": "coinapi_v1",
                    "native_worker_id": WORKER_ID,
                }
                for key in (latest_key, normalized_key):
                    if _safe_hset(redis_client, key, hash_payload, ex=ttl_seconds):
                        written.append(key)
                market_payload = {
                    "timestamp": candle.get("updated_ts_ms"),
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "open": candle.get("open"),
                    "high": candle.get("high"),
                    "low": candle.get("low"),
                    "close": candle.get("close"),
                    "volume": candle.get("volume"),
                    "source": "coinapi_v1",
                    "native_worker_id": WORKER_ID,
                    "live_gate": "blocked_human_only",
                    "live_symbols": [],
                }
                for key in (market_key, latest_binance_key, coinapi_market_key):
                    if _safe_set_json(redis_client, key, market_payload, ex=ttl_seconds):
                        written.append(key)
                list_payload = {
                    "timestamp": candle.get("updated_ts_ms"),
                    "open": candle.get("open"),
                    "high": candle.get("high"),
                    "low": candle.get("low"),
                    "close": candle.get("close"),
                    "volume": candle.get("volume"),
                    "source": "coinapi_v1",
                    "native_worker_id": WORKER_ID,
                }
                if _safe_rpush_json(redis_client, ohlcv_list_key, list_payload, ex=max(ttl_seconds, 3600)):
                    written.append(ohlcv_list_key)
    heartbeat = {
        "worker_id": WORKER_ID,
        "source": "coinapi_rest",
        "finished_utc": fetch.get("finished_utc"),
        "keys_written_count": len(written),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }
    if _safe_set_json(redis_client, "v2:market:coinapi:rest:heartbeat", heartbeat, ex=ttl_seconds):
        written.append("v2:market:coinapi:rest:heartbeat")
    if _safe_set_json(redis_client, "v2:market:coinapi:ohlcv:heartbeat", heartbeat, ex=ttl_seconds):
        written.append("v2:market:coinapi:ohlcv:heartbeat")
    return written


def build_payload(
    symbols: tuple[str, ...],
    *,
    fetch_symbol_limit: int | None,
    fetch_ohlcv: bool = True,
    ohlcv_timeframes: tuple[str, ...] = DEFAULT_OHLCV_TIMEFRAMES,
    ohlcv_symbol_limit: int | None = DEFAULT_OHLCV_SYMBOL_LIMIT,
    write_v2_redis: bool,
    ttl_seconds: int,
    timeout_seconds: float,
    max_rps: float,
) -> dict[str, Any]:
    api_key = _read_secret_value("COINAPI_API_KEY") or _read_secret_value("COINAPI_KEY")
    rest_base_url = os.getenv("COINAPI_REST_URL", COINAPI_REST_BASE)
    exchange_id = os.getenv("COINAPI_PRIMARY_EXCHANGE_ID", "BINANCEFTS")
    redis_client = _connect_redis() if write_v2_redis else None
    fetch = None
    if api_key:
        fetch = fetch_for_symbols(
            symbols,
            api_key=api_key,
            rest_base_url=rest_base_url,
            exchange_id=exchange_id,
            fetch_symbol_limit=fetch_symbol_limit,
            fetch_ohlcv=fetch_ohlcv,
            ohlcv_timeframes=ohlcv_timeframes,
            ohlcv_symbol_limit=ohlcv_symbol_limit,
            timeout_seconds=timeout_seconds,
            max_rps=max_rps,
        )
    keys_written: list[str] = []
    if fetch is not None and write_v2_redis:
        keys_written = persist_to_v2_redis(redis_client, fetch, ttl_seconds=ttl_seconds)
    rows = fetch.get("rows", []) if isinstance(fetch, dict) else []
    ok_count = sum(1 for row in rows if isinstance(row, dict) and row.get("orderbook_present"))
    ohlcv_count = sum(
        len(row.get("ohlcv_present_timeframes") or [])
        for row in rows
        if isinstance(row, dict)
    )
    classification = (
        "V2_COINAPI_REST_OK"
        if ok_count or ohlcv_count
        else ("BLOCKED_BY_MISSING_COINAPI_API_KEY" if not api_key else "BLOCKED_BY_NETWORK_OR_API")
    )
    return {
        "worker_id": WORKER_ID,
        "schema_version": "v2_coinapi_rest_ingestor_status_v1",
        "classification": classification,
        "scope": "PAPER_ONLY_KEYED_MARKET_DATA",
        "generated_utc": _utc_iso(),
        "symbols": list(symbols),
        "fetch_symbol_limit": fetch_symbol_limit,
        "fetch_ohlcv": bool(fetch_ohlcv),
        "ohlcv_timeframes": list(ohlcv_timeframes),
        "ohlcv_symbol_limit": ohlcv_symbol_limit,
        "fetch": fetch,
        "orderbooks_present_count": ok_count,
        "ohlcv_present_count": ohlcv_count,
        "v2_redis_write_enabled": bool(write_v2_redis),
        "redis_ok": redis_client is not None if write_v2_redis else None,
        "v2_redis_keys_written": keys_written,
        "v2_redis_keys_written_count": len(keys_written),
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
        "live_gate": "blocked_human_only",
        "runtime_mode": "LIVE_DATA_AND_LIVE_DECISION_INPUTS_TRADER_EXECUTION_DISABLED",
        "live_data_enabled": True,
        "live_decision_input_enabled": True,
        "trader_execution_enabled": False,
        "execution_live_symbols": [],
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
    }


def write_payload(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--fetch-symbol-limit", type=int, default=None)
    parser.add_argument("--fetch-ohlcv", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--ohlcv-timeframes", default=",".join(DEFAULT_OHLCV_TIMEFRAMES))
    parser.add_argument("--ohlcv-symbol-limit", type=int, default=DEFAULT_OHLCV_SYMBOL_LIMIT)
    parser.add_argument("--write-v2-redis", action="store_true")
    parser.add_argument("--v2-redis-ttl-seconds", type=int, default=900)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--max-rps", type=float, default=0.5)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--out", type=Path, default=DEFAULT_PAYLOAD_PATH)
    args = parser.parse_args(argv)
    symbols = tuple(resolve_symbols(
        explicit=args.symbols,
        smoke_test=bool(args.smoke_test),
        include_baseline=True,
    ))
    if args.loop and args.once:
        print("ERROR: --loop and --once are mutually exclusive", file=sys.stderr)
        return 2
    ohlcv_timeframes = tuple(
        tf.strip()
        for tf in str(args.ohlcv_timeframes or "").split(",")
        if tf.strip() and tf.strip() in COINAPI_PERIOD_MAP
    )
    while True:
        payload = build_payload(
            symbols,
            fetch_symbol_limit=args.fetch_symbol_limit,
            fetch_ohlcv=bool(args.fetch_ohlcv),
            ohlcv_timeframes=ohlcv_timeframes or DEFAULT_OHLCV_TIMEFRAMES,
            ohlcv_symbol_limit=args.ohlcv_symbol_limit,
            write_v2_redis=bool(args.write_v2_redis),
            ttl_seconds=max(60, int(args.v2_redis_ttl_seconds)),
            timeout_seconds=max(1.0, float(args.timeout_seconds)),
            max_rps=max(0.05, float(args.max_rps)),
        )
        write_payload(payload, args.out)
        sys.stdout.write(json.dumps({
            "classification": payload["classification"],
            "orderbooks_present_count": payload["orderbooks_present_count"],
            "ohlcv_present_count": payload["ohlcv_present_count"],
            "v2_redis_keys_written_count": payload["v2_redis_keys_written_count"],
            "redis_ok": payload["redis_ok"],
        }) + "\n")
        sys.stdout.flush()
        if not args.loop:
            return 0
        time.sleep(max(30, int(args.interval_seconds)))


if __name__ == "__main__":
    raise SystemExit(main())
