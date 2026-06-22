"""V2 native KuCoin public-data ingestor worker (paper-only).

Emits a config-only payload at
v2/frontend/public/operator_runtime/v2_kucoin_ingestor/latest/
v2_kucoin_ingestor_status.json.

No order placement. No old Redis writes.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_ingestors.kucoin import (
    build_ingestor_config,
    classify_reconnect_attempt,
    kucoin_invariants_snapshot,
    v2_to_kucoin_futures_symbol,
    v2_to_kucoin_spot_symbol,
)
from v2.backend.app.services.v2_symbol_runtime_universe import (
    BASELINE_25_SYMBOLS,
    resolve_symbols,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PAYLOAD_PATH = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime/v2_kucoin_ingestor/latest/v2_kucoin_ingestor_status.json"
)
DEFAULT_SYMBOLS = tuple(BASELINE_25_SYMBOLS)
V2_REDIS_PREFIX = "v2:"
HTTP_TIMEOUT_S = 8.0


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _http_get_json(base: str, path: str, params: dict[str, Any] | None = None) -> tuple[int, Any]:
    query = urllib.parse.urlencode(params or {})
    url = f"{base.rstrip('/')}{path}"
    if query:
        url = f"{url}?{query}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ai-bot-v2-kucoin-ingestor-readonly"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as response:
            body = response.read().decode("utf-8")
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
            data = json.loads(body) if body else None
        except Exception:
            data = None
        return int(exc.code), data
    except Exception:
        return 599, None
    try:
        data = json.loads(body) if body else None
    except Exception:
        data = body
    return status, data


def _kucoin_data(response: Any) -> Any:
    if isinstance(response, dict):
        code = response.get("code")
        if code is not None and str(code) != "200000":
            return None
        if "data" in response:
            return response.get("data")
    return response


def _kucoin_code(response: Any) -> str | None:
    if isinstance(response, dict) and response.get("code") is not None:
        return str(response.get("code"))
    return None


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
        )
        client.ping()
        return client
    except Exception:
        return None


def _safe_write(redis_client: Any, key: str, payload: Any, *, ex: int = 600) -> bool:
    if redis_client is None:
        return False
    if not key.startswith(V2_REDIS_PREFIX):
        raise ValueError(f"refused non-V2 Redis key: {key!r}")
    body = json.dumps(payload, sort_keys=True, default=str)
    redis_client.set(key, body, ex=int(ex))
    return True


def _parse_kline(
    raw: Any,
    *,
    symbol: str,
    kucoin_symbol: str,
    timeframe: str,
    source: str = "kucoin_public_rest",
) -> dict[str, Any] | None:
    if not isinstance(raw, list) or not raw:
        return None
    row = raw[0]
    if not isinstance(row, list) or len(row) < 6:
        return None
    try:
        timestamp_raw = int(float(row[0]))
        timestamp_ms = timestamp_raw if timestamp_raw >= 1_000_000_000_000 else timestamp_raw * 1000
        if "futures" in source:
            open_px = float(row[1])
            high_px = float(row[2])
            low_px = float(row[3])
            close_px = float(row[4])
        else:
            open_px = float(row[1])
            close_px = float(row[2])
            high_px = float(row[3])
            low_px = float(row[4])
        volume = float(row[5])
        if not _valid_ohlc(open_px=open_px, high_px=high_px, low_px=low_px, close_px=close_px, volume=volume):
            return None
        return {
            "symbol": symbol,
            "kucoin_symbol": kucoin_symbol,
            "timeframe": timeframe,
            "timestamp": timestamp_ms,
            "open": open_px,
            "close": close_px,
            "high": high_px,
            "low": low_px,
            "volume": volume,
            "turnover": float(row[6]) if len(row) > 6 and row[6] is not None else None,
            "source": source,
            "feature_eligible": True,
        }
    except Exception:
        return None


def _valid_ohlc(*, open_px: float, high_px: float, low_px: float, close_px: float, volume: float) -> bool:
    values = (open_px, high_px, low_px, close_px, volume)
    if not all(value == value and value not in (float("inf"), float("-inf")) for value in values):
        return False
    if min(open_px, high_px, low_px, close_px) <= 0:
        return False
    if volume < 0:
        return False
    return low_px <= open_px <= high_px and low_px <= close_px <= high_px and low_px <= high_px


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _epoch_ms(value: Any) -> int:
    numeric = _safe_float(value)
    if numeric is None:
        return int(time.time() * 1000)
    if numeric >= 1_000_000_000_000_000:
        return int(numeric / 1_000_000)
    if numeric >= 1_000_000_000_000:
        return int(numeric)
    return int(numeric * 1000)


def _has_any_number(payload: dict[str, Any] | None, keys: tuple[str, ...]) -> bool:
    if not isinstance(payload, dict):
        return False
    return any(_safe_float(payload.get(key)) is not None for key in keys)


def _has_ticker_values(payload: dict[str, Any] | None) -> bool:
    return _has_any_number(payload, ("bid", "ask", "last", "size", "volume_24h"))


def _has_contract_values(payload: dict[str, Any] | None) -> bool:
    return _has_any_number(payload, ("open_interest", "mark_price", "index_price"))


def _has_funding_values(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    return (
        _has_any_number(payload, ("rate", "predicted_rate"))
        or payload.get("next_funding_time") is not None
        or payload.get("funding_time") is not None
    )


def _has_orderbook_values(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("bids")) or bool(payload.get("asks"))


def _row_has_public_data(row: dict[str, Any]) -> bool:
    return (
        _has_ticker_values(row.get("ticker"))
        or bool(row.get("klines"))
        or _has_funding_values(row.get("funding"))
        or _has_contract_values(row.get("contract"))
        or _has_orderbook_values(row.get("orderbook20"))
    )


def _public_rest_summary(fetch_payload: dict[str, Any] | None) -> dict[str, Any]:
    rows = fetch_payload.get("rows", []) if isinstance(fetch_payload, dict) else []
    typed_rows = [row for row in rows if isinstance(row, dict)]
    code_counts: dict[str, int] = {}
    for row in typed_rows:
        endpoint_codes = row.get("endpoint_codes")
        if not isinstance(endpoint_codes, dict):
            continue
        for code in endpoint_codes.values():
            if code is None:
                continue
            text = str(code)
            code_counts[text] = code_counts.get(text, 0) + 1
    return {
        "rows_count": len(typed_rows),
        "row_success_count": sum(1 for row in typed_rows if _row_has_public_data(row)),
        "ticker_rows": sum(1 for row in typed_rows if _has_ticker_values(row.get("ticker"))),
        "kline_rows": sum(1 for row in typed_rows if bool(row.get("klines"))),
        "funding_rows": sum(1 for row in typed_rows if _has_funding_values(row.get("funding"))),
        "contract_rows": sum(1 for row in typed_rows if _has_contract_values(row.get("contract"))),
        "orderbook_rows": sum(1 for row in typed_rows if _has_orderbook_values(row.get("orderbook20"))),
        "endpoint_code_counts": dict(sorted(code_counts.items())),
    }


def _parse_spot_ticker(data: Any, *, symbol: str, spot_symbol: str) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    payload = {
        "symbol": symbol,
        "kucoin_symbol": spot_symbol,
        "bid": _safe_float(data.get("bestBid")),
        "ask": _safe_float(data.get("bestAsk")),
        "last": _safe_float(data.get("price")),
        "size": _safe_float(data.get("size")),
        "volume_24h": _safe_float(data.get("vol")),
        "timestamp": int(time.time() * 1000),
        "source": "kucoin_spot_public_rest",
    }
    return payload if _has_ticker_values(payload) else None


def _parse_futures_ticker(data: Any, *, symbol: str, futures_symbol: str) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    payload = {
        "symbol": symbol,
        "kucoin_symbol": futures_symbol,
        "bid": _safe_float(data.get("bestBidPrice")),
        "ask": _safe_float(data.get("bestAskPrice")),
        "last": _safe_float(data.get("price")),
        "size": _safe_float(data.get("size")),
        "volume_24h": None,
        "timestamp": _epoch_ms(data.get("ts")),
        "source": "kucoin_futures_public_rest",
    }
    return payload if _has_ticker_values(payload) else None


def _parse_funding(data: Any, *, symbol: str, futures_symbol: str, source: str) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    rate = (
        _safe_float(data.get("fundingRate"))
        if data.get("fundingRate") is not None
        else _safe_float(data.get("value") if data.get("value") is not None else data.get("nextFundingRate"))
    )
    predicted = (
        _safe_float(data.get("predictedFundingRate"))
        if data.get("predictedFundingRate") is not None
        else _safe_float(
            data.get("predictedValue")
            if data.get("predictedValue") is not None
            else data.get("predictedFundingRate")
        )
    )
    payload = {
        "symbol": symbol,
        "kucoin_futures_symbol": futures_symbol,
        "rate": rate,
        "predicted_rate": predicted,
        "next_funding_time": data.get("nextFundingTime"),
        "funding_time": data.get("fundingTime"),
        "funding_rate_cap": _safe_float(data.get("fundingRateCap")),
        "funding_rate_floor": _safe_float(data.get("fundingRateFloor")),
        "timestamp": int(time.time() * 1000),
        "source": source,
    }
    return payload if _has_funding_values(payload) else None


def _parse_contract(data: Any, *, symbol: str, futures_symbol: str) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    payload = {
        "symbol": symbol,
        "kucoin_futures_symbol": futures_symbol,
        "open_interest": _safe_float(data.get("openInterest")),
        "mark_price": _safe_float(data.get("markPrice")),
        "index_price": _safe_float(data.get("indexPrice")),
        "timestamp": int(time.time() * 1000),
        "source": "kucoin_futures_public_rest",
    }
    return payload if _has_contract_values(payload) else None


def _parse_orderbook(data: Any, *, symbol: str, kucoin_symbol: str, source: str) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    payload = {
        "symbol": symbol,
        "kucoin_symbol": kucoin_symbol,
        "bids": data.get("bids")[:20] if isinstance(data.get("bids"), list) else [],
        "asks": data.get("asks")[:20] if isinstance(data.get("asks"), list) else [],
        "timestamp": int(time.time() * 1000),
        "source": source,
    }
    return payload if _has_orderbook_values(payload) else None


def fetch_public_rest_for_symbols(
    symbols: tuple[str, ...],
    *,
    timeframes: tuple[str, ...],
    symbol_limit: int | None = None,
) -> dict[str, Any]:
    from v2.backend.app.services.native_ingestors.kucoin import (
        KUCOIN_BASE_FUTURES,
        KUCOIN_BASE_SPOT,
    )

    tf_map = {
        "1m": "1min",
        "5m": "5min",
        "15m": "15min",
        "30m": "30min",
        "1h": "1hour",
        "4h": "4hour",
        "1d": "1day",
    }
    futures_tf_map = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
    }
    started_utc = _utc_iso()
    selected = tuple(symbols[:symbol_limit]) if symbol_limit else tuple(symbols)
    rows: list[dict[str, Any]] = []
    for symbol in selected:
        spot_symbol = v2_to_kucoin_spot_symbol(symbol)
        futures_symbol = v2_to_kucoin_futures_symbol(symbol)
        row: dict[str, Any] = {
            "symbol": symbol,
            "kucoin_spot_symbol": spot_symbol,
            "kucoin_futures_symbol": futures_symbol,
            "ticker": None,
            "klines": {},
            "funding": None,
            "contract": None,
            "orderbook20": None,
            "endpoint_statuses": {},
            "endpoint_codes": {},
        }
        status, body = _http_get_json(
            KUCOIN_BASE_SPOT,
            "/api/v1/market/orderbook/level1",
            {"symbol": spot_symbol},
        )
        row["endpoint_statuses"]["spot_level1"] = status
        row["endpoint_codes"]["spot_level1"] = _kucoin_code(body)
        row["ticker"] = _parse_spot_ticker(_kucoin_data(body), symbol=symbol, spot_symbol=spot_symbol)

        if row["ticker"] is None:
            status, body = _http_get_json(
                KUCOIN_BASE_FUTURES,
                "/api/v1/ticker",
                {"symbol": futures_symbol},
            )
            row["endpoint_statuses"]["futures_ticker"] = status
            row["endpoint_codes"]["futures_ticker"] = _kucoin_code(body)
            row["ticker"] = _parse_futures_ticker(
                _kucoin_data(body),
                symbol=symbol,
                futures_symbol=futures_symbol,
            )

        for tf in timeframes:
            kt = tf_map.get(tf)
            if not kt:
                continue
            status, body = _http_get_json(
                KUCOIN_BASE_SPOT,
                "/api/v1/market/candles",
                {"symbol": spot_symbol, "type": kt, "limit": 1},
            )
            row["endpoint_statuses"][f"kline_{tf}"] = status
            row["endpoint_codes"][f"kline_{tf}"] = _kucoin_code(body)
            parsed = _parse_kline(
                _kucoin_data(body),
                symbol=symbol,
                kucoin_symbol=spot_symbol,
                timeframe=tf,
                source="kucoin_spot_public_rest",
            )
            if parsed is None:
                futures_granularity = futures_tf_map.get(tf)
                if futures_granularity is not None:
                    status, body = _http_get_json(
                        KUCOIN_BASE_FUTURES,
                        "/api/v1/kline/query",
                        {"symbol": futures_symbol, "granularity": futures_granularity},
                    )
                    row["endpoint_statuses"][f"futures_kline_{tf}"] = status
                    row["endpoint_codes"][f"futures_kline_{tf}"] = _kucoin_code(body)
                    parsed = _parse_kline(
                        _kucoin_data(body),
                        symbol=symbol,
                        kucoin_symbol=futures_symbol,
                        timeframe=tf,
                        source="kucoin_futures_public_rest",
                    )
            if parsed is not None:
                row["klines"][tf] = parsed

        status, body = _http_get_json(
            KUCOIN_BASE_SPOT,
            "/api/v1/market/orderbook/level2_20",
            {"symbol": spot_symbol},
        )
        row["endpoint_statuses"]["orderbook20"] = status
        row["endpoint_codes"]["orderbook20"] = _kucoin_code(body)
        row["orderbook20"] = _parse_orderbook(
            _kucoin_data(body),
            symbol=symbol,
            kucoin_symbol=spot_symbol,
            source="kucoin_spot_public_rest",
        )

        if row["orderbook20"] is None:
            status, body = _http_get_json(
                KUCOIN_BASE_FUTURES,
                "/api/v1/level2/snapshot",
                {"symbol": futures_symbol},
            )
            row["endpoint_statuses"]["futures_orderbook20"] = status
            row["endpoint_codes"]["futures_orderbook20"] = _kucoin_code(body)
            row["orderbook20"] = _parse_orderbook(
                _kucoin_data(body),
                symbol=symbol,
                kucoin_symbol=futures_symbol,
                source="kucoin_futures_public_rest",
            )

        status, body = _http_get_json(
            KUCOIN_BASE_SPOT,
            "/api/ua/v1/market/funding-rate",
            {"symbol": futures_symbol},
        )
        row["endpoint_statuses"]["funding_current"] = status
        row["endpoint_codes"]["funding_current"] = _kucoin_code(body)
        row["funding"] = _parse_funding(
            _kucoin_data(body),
            symbol=symbol,
            futures_symbol=futures_symbol,
            source="kucoin_uta_public_rest",
        )

        if row["funding"] is None:
            status, body = _http_get_json(
                KUCOIN_BASE_FUTURES,
                f"/api/v1/funding-rate/{futures_symbol}/current",
            )
            row["endpoint_statuses"]["futures_funding_current"] = status
            row["endpoint_codes"]["futures_funding_current"] = _kucoin_code(body)
            row["funding"] = _parse_funding(
                _kucoin_data(body),
                symbol=symbol,
                futures_symbol=futures_symbol,
                source="kucoin_futures_public_rest",
            )

        status, body = _http_get_json(
            KUCOIN_BASE_FUTURES,
            f"/api/v1/contracts/{futures_symbol}",
        )
        row["endpoint_statuses"]["contract_detail"] = status
        row["endpoint_codes"]["contract_detail"] = _kucoin_code(body)
        row["contract"] = _parse_contract(_kucoin_data(body), symbol=symbol, futures_symbol=futures_symbol)
        rows.append(row)

    return {
        "started_utc": started_utc,
        "finished_utc": _utc_iso(),
        "symbols_requested": len(symbols),
        "symbols_fetched": len(selected),
        "timeframes": list(timeframes),
        "rows": rows,
    }


def persist_fetch_to_v2_redis(redis_client: Any, fetch: dict[str, Any], *, ttl_seconds: int = 600) -> list[str]:
    written: list[str] = []
    if redis_client is None:
        return written
    for row in fetch.get("rows", []):
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        for suffix, payload in (
            (f"v2:market:kucoin:latest:{symbol}", row.get("ticker")),
            (f"v2:market:kucoin:funding:{symbol}", row.get("funding")),
            (f"v2:market:kucoin:contract:{symbol}", row.get("contract")),
            (f"v2:market:kucoin:orderbook20:{symbol}", row.get("orderbook20")),
        ):
            if payload is not None and _safe_write(redis_client, suffix, payload, ex=ttl_seconds):
                written.append(suffix)
        klines = row.get("klines")
        if isinstance(klines, dict):
            for tf, payload in klines.items():
                key = f"v2:market:kucoin:kline:{symbol}:{tf}"
                if _safe_write(redis_client, key, payload, ex=ttl_seconds):
                    written.append(key)
        if not _row_has_public_data(row):
            continue
        feature_payload = {
            "symbol": symbol,
            "source": "kucoin_public_rest",
            "data_available": True,
            "ticker": row.get("ticker"),
            "funding": row.get("funding"),
            "contract": row.get("contract"),
            "orderbook20_present": row.get("orderbook20") is not None,
            "klines_present": sorted((row.get("klines") or {}).keys()),
            "live_gate": "blocked_human_only",
            "live_symbols": [],
        }
        fkey = f"v2:features:kucoin:{symbol}:latest"
        if _safe_write(redis_client, fkey, feature_payload, ex=ttl_seconds):
            written.append(fkey)
    heartbeat = {
        "worker_id": "v2_kucoin_ingestor",
        "source": "kucoin_public_rest",
        "finished_utc": fetch.get("finished_utc"),
        "keys_written_count": len(written),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }
    if _safe_write(redis_client, "v2:market:kucoin:heartbeat", heartbeat, ex=ttl_seconds):
        written.append("v2:market:kucoin:heartbeat")
    return written


def build_payload(
    symbols: tuple[str, ...],
    *,
    fetch_public_rest: bool = False,
    fetch_symbol_limit: int | None = None,
    timeframes: tuple[str, ...] | None = None,
    write_v2_redis: bool = False,
    redis_ttl_seconds: int = 600,
) -> dict:
    cfg = build_ingestor_config(symbols_v2=symbols)
    reconnect_examples = [classify_reconnect_attempt(i) for i in range(0, 10)]
    fetch_payload = (
        fetch_public_rest_for_symbols(
            symbols,
            timeframes=timeframes or tuple(cfg.timeframes[:1]),
            symbol_limit=fetch_symbol_limit,
        )
        if fetch_public_rest
        else None
    )
    redis_keys_written: list[str] = []
    redis_ok = None
    if write_v2_redis:
        redis_client = _connect_redis()
        redis_ok = redis_client is not None
        if fetch_payload is not None:
            redis_keys_written = persist_fetch_to_v2_redis(
                redis_client,
                fetch_payload,
                ttl_seconds=max(60, int(redis_ttl_seconds)),
            )
    classification = cfg.classification
    public_rest_summary = _public_rest_summary(fetch_payload)
    if fetch_public_rest:
        rows = fetch_payload.get("rows", []) if isinstance(fetch_payload, dict) else []
        success = any(isinstance(r, dict) and _row_has_public_data(r) for r in rows)
        classification = "NATIVE_V2_PUBLIC_REST_OK" if success else "BLOCKED_BY_NETWORK_OR_API"
    return {
        "worker_id": "v2_kucoin_ingestor",
        "schema_version": "v2_kucoin_ingestor_status_v1",
        "scope": "PAPER_ONLY_PUBLIC_MARKET_DATA",
        "classification": classification,
        "symbols_v2": list(cfg.symbols_v2),
        "timeframes": list(cfg.timeframes),
        "spot_endpoints": [asdict(e) for e in cfg.spot_endpoints],
        "futures_endpoints": [asdict(e) for e in cfg.futures_endpoints],
        "public_wss_topics": [asdict(t) for t in cfg.public_wss_topics],
        "public_rest_fetch_enabled": bool(fetch_public_rest),
        "public_rest_fetch": fetch_payload,
        "public_rest_summary": public_rest_summary,
        "v2_redis_write_enabled": bool(write_v2_redis),
        "redis_ok": redis_ok,
        "v2_redis_keys_written": redis_keys_written,
        "v2_redis_keys_written_count": len(redis_keys_written),
        "ticker_period_seconds": cfg.ticker_period_seconds,
        "kline_period_seconds": cfg.kline_period_seconds,
        "funding_period_seconds": cfg.funding_period_seconds,
        "orderbook_period_seconds": cfg.orderbook_period_seconds,
        "reconnect_backoff_seconds": list(cfg.reconnect_backoff_seconds),
        "reconnect_examples": reconnect_examples,
        "generated_utc": cfg.generated_utc,
        "invariants": kucoin_invariants_snapshot(),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_kucoin_ingestor_worker")
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated V2 symbols. Default is dynamic universe plus 25-symbol baseline.",
    )
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--write-evidence", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--fetch-public-rest", action="store_true")
    parser.add_argument(
        "--fetch-symbol-limit",
        type=int,
        default=None,
        help="Optional cap for public REST fetch count; omitted fetches all resolved symbols.",
    )
    parser.add_argument(
        "--fetch-timeframes",
        default="1m",
        help="Comma-separated KuCoin kline timeframes to fetch when --fetch-public-rest is set.",
    )
    parser.add_argument("--write-v2-redis", action="store_true")
    parser.add_argument("--v2-redis-ttl-seconds", type=int, default=600)
    args = parser.parse_args(argv)
    explicit = (
        tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
        if args.symbols
        else None
    )
    symbols = tuple(resolve_symbols(explicit=explicit, smoke_test=args.smoke_test))
    fetch_tfs = tuple(s.strip() for s in args.fetch_timeframes.split(",") if s.strip())
    payload = build_payload(
        symbols,
        fetch_public_rest=bool(args.fetch_public_rest),
        fetch_symbol_limit=args.fetch_symbol_limit,
        timeframes=fetch_tfs,
        write_v2_redis=bool(args.write_v2_redis),
        redis_ttl_seconds=max(60, int(args.v2_redis_ttl_seconds)),
    )
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.dry_run and args.write_evidence:
        print("ERROR: --dry-run and --write-evidence are mutually exclusive", file=sys.stderr)
        return 2
    if args.write_evidence:
        dest = args.out or DEFAULT_PAYLOAD_PATH
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body)
        print(f"v2_kucoin_ingestor_status_written path={dest} classification={payload['classification']}")
        return 0
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
