"""V2 Binance public-metadata ingestor (read-only, paper-safe).

Reads Binance WebSocket-backed Redis/cache data first for mark-price /
funding / open-interest / orderbook signals. Public REST is fallback-only and
requires ``BINANCE_REST_FALLBACK_ALLOWED=true``. Writes only ``v2:market:*``
Redis keys and a public payload. Never makes a signed request, never calls a
mutation endpoint, never reads or prints any credential value.

Fallback endpoints (all public, no auth):
  * ``/fapi/v1/premiumIndex`` -> mark price + funding rate per symbol
  * ``/fapi/v1/openInterest`` -> open interest per symbol
  * ``/fapi/v1/depth?limit=20`` -> top-of-book orderbook per symbol

The loop emits a heartbeat per cycle and an aggregated public payload
under ``v2/frontend/public/v2_binance_public_metadata/latest/``.

Hard rules (enforced by code + tests):
  * no ``order``, ``leverage``, ``margin``, ``transfer``, ``withdraw`` token
    in any code path here
  * no signed request
  * ``LIVE_GATE = blocked_human_only`` throughout
  * Redis writes use only the ``v2:market:*`` namespace
  * one TTL applied to every Redis key
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo


EST = ZoneInfo("America/New_York")
REPO = Path("/home/wali/Desktop/AI BOT REBUILD")
FAPI_BASE = "https://fapi.binance.com"

# NOTE: V2_DYNAMIC_SYMBOL_AND_COPIED_COMPONENT_RUNTIME_REMEDIATION removed the
# legacy 3-symbol default; the resolver in
# ``v2.backend.app.services.v2_symbol_runtime_universe`` is the single source
# of truth. The 3 symbols below are smoke-test-only and surfaced only when
# ``--smoke-test`` or ``V2_SYMBOL_PROFILE=smoke_test`` is set.
from v2.backend.app.services.v2_symbol_runtime_universe import (  # noqa: E402
    BASELINE_25_SYMBOLS,
    SMOKE_TEST_SYMBOLS,
    resolve_symbols,
    resolve_symbols_with_provenance,
)
from v2.backend.app.services.binance_unified_websocket_transport import (  # noqa: E402
    REST_FALLBACK_ENV,
    binance_rest_fallback_allowed,
    require_binance_rest_fallback,
)
from v2.backend.app.services.market_data.current_price_resolver import resolve_current_price  # noqa: E402
DEFAULT_INTERVAL_S = 30
DEFAULT_TTL_S = 300
HTTP_TIMEOUT_S = 6.0

LIVE_GATE = "blocked_human_only"

PUBLIC_OUT_DIR = REPO / "v2/frontend/public/v2_binance_public_metadata/latest"


def _est_iso() -> str:
    return datetime.now(EST).strftime("%Y-%m-%dT%H:%M:%S%z")


def _http_get_json(url: str) -> Any:
    try:
        require_binance_rest_fallback(
            endpoint=urllib.parse.urlparse(url).path or url,
            fallback_reason="public_metadata_websocket_cache_missing",
            role="public_metadata_cache_recovery",
        )
    except RuntimeError as exc:
        message = str(exc).replace(
            "REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
            "BINANCE_REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
            1,
        )
        raise RuntimeError(message) from exc
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode())


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


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cache_transport(payload: Any) -> str:
    if not isinstance(payload, dict):
        return "websocket_cache_primary"
    source = str(payload.get("source") or payload.get("transport") or "")
    return "rest_fallback_cache" if "rest" in source.lower() else "websocket_cache_primary"


def fetch_premium_index(symbol: str, *, redis_client: Any = None) -> Dict[str, Any]:
    prices = _read_json(redis_client, f"v2:market:prices:{symbol}")
    funding = _read_json(redis_client, f"v2:market:funding:{symbol}")
    try:
        current = resolve_current_price(redis_client, symbol) if redis_client is not None else {}
    except Exception:
        current = {}
    funding_map = funding if isinstance(funding, dict) else {}
    prices_map = prices if isinstance(prices, dict) else {}
    nested_funding = prices_map.get("funding") if isinstance(prices_map.get("funding"), dict) else {}
    mark_price = _safe_float(
        prices_map.get("mark_price")
        or prices_map.get("markPrice")
        or funding_map.get("mark_price")
        or funding_map.get("markPrice")
        or nested_funding.get("mark_price")
        or nested_funding.get("markPrice")
        or (current.get("price") if isinstance(current, dict) and str(current.get("source") or "").startswith("mark_price") else None)
    )
    index_price = _safe_float(
        prices_map.get("index_price")
        or prices_map.get("indexPrice")
        or funding_map.get("index_price")
        or funding_map.get("indexPrice")
        or nested_funding.get("index_price")
        or nested_funding.get("indexPrice")
    )
    funding_rate = _safe_float(
        funding_map.get("lastFundingRate")
        or funding_map.get("last_funding_rate")
        or funding_map.get("funding_rate")
        or nested_funding.get("lastFundingRate")
        or nested_funding.get("funding_rate")
    )
    if mark_price is not None or index_price is not None or funding_rate is not None:
        source_payload = funding_map or prices_map or (current if isinstance(current, dict) else {})
        return {
            "symbol": symbol,
            "mark_price": mark_price,
            "index_price": index_price,
            "estimated_settle_price": _safe_float(
                funding_map.get("estimatedSettlePrice") or nested_funding.get("estimatedSettlePrice")
            ),
            "last_funding_rate": funding_rate,
            "next_funding_time_ms": funding_map.get("nextFundingTime") or nested_funding.get("nextFundingTime"),
            "interest_rate": _safe_float(funding_map.get("interestRate") or nested_funding.get("interestRate")),
            "binance_time_ms": funding_map.get("time") or nested_funding.get("time"),
            "source": source_payload.get("source") or "binance_public_websocket_cache_primary",
            "transport": _cache_transport(source_payload),
        }
    body = _http_get_json(
        f"{FAPI_BASE}/fapi/v1/premiumIndex?symbol={urllib.parse.quote(symbol)}"
    )
    out: Dict[str, Any] = {
        "symbol": body.get("symbol"),
        "mark_price": float(body.get("markPrice")) if body.get("markPrice") is not None else None,
        "index_price": float(body.get("indexPrice")) if body.get("indexPrice") is not None else None,
        "estimated_settle_price": (
            float(body.get("estimatedSettlePrice"))
            if body.get("estimatedSettlePrice") is not None
            else None
        ),
        "last_funding_rate": (
            float(body.get("lastFundingRate"))
            if body.get("lastFundingRate") is not None
            else None
        ),
        "next_funding_time_ms": body.get("nextFundingTime"),
        "interest_rate": (
            float(body.get("interestRate"))
            if body.get("interestRate") is not None
            else None
        ),
        "binance_time_ms": body.get("time"),
        "source": "binance_public_rest_premium_index_fallback",
        "transport": "rest_fallback",
    }
    return out


def fetch_open_interest(symbol: str, *, redis_client: Any = None) -> Dict[str, Any]:
    cached = _read_json(redis_client, f"v2:market:open_interest:{symbol}")
    if isinstance(cached, dict) and cached:
        value = _safe_float(
            cached.get("open_interest_contracts")
            or cached.get("openInterest")
            or cached.get("open_interest")
        )
        return {
            "symbol": cached.get("symbol") or symbol,
            "open_interest_contracts": value,
            "binance_time_ms": cached.get("time") or cached.get("timestamp"),
            "source": cached.get("source") or "binance_public_websocket_cache_primary",
            "transport": _cache_transport(cached),
        }
    body = _http_get_json(
        f"{FAPI_BASE}/fapi/v1/openInterest?symbol={urllib.parse.quote(symbol)}"
    )
    return {
        "symbol": body.get("symbol"),
        "open_interest_contracts": (
            float(body.get("openInterest"))
            if body.get("openInterest") is not None
            else None
        ),
        "binance_time_ms": body.get("time"),
        "source": "binance_public_rest_open_interest_fallback",
        "transport": "rest_fallback",
    }


def fetch_orderbook(symbol: str, limit: int = 20, *, redis_client: Any = None) -> Dict[str, Any]:
    for key in (
        f"v2:orderbook:top:binance:{symbol}",
        f"v2:market:orderbook:binance:{symbol}",
        f"v2:market:orderbook:{symbol}",
    ):
        cached = _read_json(redis_client, key)
        if not isinstance(cached, dict):
            continue
        bids = cached.get("bids") if isinstance(cached.get("bids"), list) else []
        asks = cached.get("asks") if isinstance(cached.get("asks"), list) else []
        best_bid = _safe_float(cached.get("best_bid") or cached.get("bid"))
        best_ask = _safe_float(cached.get("best_ask") or cached.get("ask"))
        if best_bid is None and bids:
            first = bids[0]
            best_bid = _safe_float(first[0] if isinstance(first, (list, tuple)) and first else None)
        if best_ask is None and asks:
            first = asks[0]
            best_ask = _safe_float(first[0] if isinstance(first, (list, tuple)) and first else None)
        if best_bid is None and best_ask is None:
            continue
        mid = (best_bid + best_ask) / 2 if best_bid is not None and best_ask is not None else None
        spread_bps = ((best_ask - best_bid) / mid) * 1e4 if mid and best_bid is not None and best_ask is not None else None
        return {
            "symbol": symbol,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid": mid,
            "spread_bps": spread_bps,
            "bid_levels": len(bids),
            "ask_levels": len(asks),
            "update_id": cached.get("lastUpdateId") or cached.get("update_id"),
            "ev_time_ms": cached.get("E") or cached.get("event_time"),
            "source": cached.get("source") or "binance_public_websocket_orderbook_cache_primary",
            "transport": _cache_transport(cached),
            "source_key": key,
        }
    body = _http_get_json(
        f"{FAPI_BASE}/fapi/v1/depth?symbol={urllib.parse.quote(symbol)}&limit={limit}"
    )
    bids = [[float(p), float(q)] for p, q in body.get("bids", [])[:limit]]
    asks = [[float(p), float(q)] for p, q in body.get("asks", [])[:limit]]
    best_bid = bids[0][0] if bids else None
    best_ask = asks[0][0] if asks else None
    spread_bps = None
    mid = None
    if best_bid is not None and best_ask is not None and best_ask > 0:
        mid = (best_bid + best_ask) / 2
        spread_bps = ((best_ask - best_bid) / mid) * 1e4 if mid else None
    return {
        "symbol": symbol,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "spread_bps": spread_bps,
        "bid_levels": len(bids),
        "ask_levels": len(asks),
        "update_id": body.get("lastUpdateId"),
        "ev_time_ms": body.get("E"),
        "source": "binance_public_rest_depth_snapshot_fallback",
        "transport": "rest_fallback",
    }


def _rest_endpoint_used(field_name: str, payload: Any) -> str | None:
    if not isinstance(payload, dict) or payload.get("transport") != "rest_fallback":
        return None
    return {
        "premium_index": "/fapi/v1/premiumIndex",
        "open_interest": "/fapi/v1/openInterest",
        "orderbook_top": "/fapi/v1/depth",
    }.get(field_name)


def _rest_fallback_blocked_errors(entry: Dict[str, Any]) -> int:
    count = 0
    for key in ("premium_index_error", "open_interest_error", "orderbook_error"):
        value = entry.get(key)
        if isinstance(value, str) and "BINANCE_REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY" in value:
            count += 1
    return count


def _redis_client():
    try:
        import redis  # type: ignore
    except ImportError:
        return None
    try:
        r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)
        r.ping()
        return r
    except Exception:
        return None


def write_redis(r, symbol: str, *, premium: Dict[str, Any], oi: Dict[str, Any],
                book: Dict[str, Any], ttl_s: int) -> Dict[str, int]:
    """Write three V2 keys per symbol with the configured TTL."""
    if r is None:
        return {"v2:market:mark_price": 0, "v2:market:open_interest": 0, "v2:market:orderbook_top": 0}
    written: Dict[str, int] = {}
    payloads = [
        (f"v2:market:mark_price:{symbol}", premium),
        (f"v2:market:open_interest:{symbol}", oi),
        (f"v2:market:orderbook_top:{symbol}", book),
    ]
    for key, payload in payloads:
        try:
            r.set(key, json.dumps(payload, separators=(",", ":")), ex=ttl_s)
            written[key] = 1
        except Exception:
            written[key] = 0
    return written


def run_once(symbols: List[str], *, ttl_s: int) -> Dict[str, Any]:
    started_at = _est_iso()
    r = _redis_client()
    redis_available = r is not None
    per_symbol: Dict[str, Any] = {}
    error_count = 0
    write_count = 0
    for symbol in symbols:
        entry: Dict[str, Any] = {"symbol": symbol}
        try:
            entry["premium_index"] = fetch_premium_index(symbol, redis_client=r)
        except Exception as e:
            entry["premium_index_error"] = str(e)
            error_count += 1
        try:
            entry["open_interest"] = fetch_open_interest(symbol, redis_client=r)
        except Exception as e:
            entry["open_interest_error"] = str(e)
            error_count += 1
        try:
            entry["orderbook_top"] = fetch_orderbook(symbol, redis_client=r)
        except Exception as e:
            entry["orderbook_error"] = str(e)
            error_count += 1
        wrote = write_redis(
            r,
            symbol,
            premium=entry.get("premium_index", {}),
            oi=entry.get("open_interest", {}),
            book=entry.get("orderbook_top", {}),
            ttl_s=ttl_s,
        )
        entry["redis_keys_written"] = wrote
        write_count += sum(wrote.values())
        per_symbol[symbol] = entry
    cache_primary_count = sum(
        1
        for entry in per_symbol.values()
        for payload in (entry.get("premium_index"), entry.get("open_interest"), entry.get("orderbook_top"))
        if isinstance(payload, dict) and payload.get("transport") in {"websocket_cache_primary", "rest_fallback_cache"}
    )
    rest_fallback_count = sum(
        1
        for entry in per_symbol.values()
        for payload in (entry.get("premium_index"), entry.get("open_interest"), entry.get("orderbook_top"))
        if isinstance(payload, dict) and payload.get("transport") == "rest_fallback"
    )
    endpoints_used_this_cycle = sorted(
        {
            endpoint
            for entry in per_symbol.values()
            for field_name in ("premium_index", "open_interest", "orderbook_top")
            for endpoint in [_rest_endpoint_used(field_name, entry.get(field_name))]
            if endpoint
        }
    )
    rest_fallback_blocked_count = sum(_rest_fallback_blocked_errors(entry) for entry in per_symbol.values())
    finished_at = _est_iso()
    return {
        "started_at_est": started_at,
        "finished_at_est": finished_at,
        "symbols": symbols,
        "redis_available": redis_available,
        "redis_keys_written_total": write_count,
        "errors": error_count,
        "per_symbol": per_symbol,
        "cache_primary_field_count": cache_primary_count,
        "rest_fallback_field_count": rest_fallback_count,
        "live_gate": LIVE_GATE,
        "writes_exchange_orders": False,
        "transport_policy": "binance_public_websocket_cache_primary_rest_fallback_only",
        "rest_fallback_allowed": binance_rest_fallback_allowed(),
        "rest_fallback_env": REST_FALLBACK_ENV,
        "rest_used_as_primary": False,
        "endpoints_used_this_cycle": endpoints_used_this_cycle,
        "rest_fallback_blocked_count": rest_fallback_blocked_count,
        "rest_fallback_endpoints": [
            "/fapi/v1/premiumIndex",
            "/fapi/v1/openInterest",
            "/fapi/v1/depth",
        ],
        "endpoints_never_called": [
            "/fapi/v1/order",
            "/fapi/v1/order/test",
            "/fapi/v1/leverage",
            "/fapi/v1/marginType",
            "/sapi/v1/futures/transfer",
            "/sapi/v1/capital/withdraw",
        ],
    }


def write_public_payload(report: Dict[str, Any]) -> Path:
    PUBLIC_OUT_DIR.mkdir(parents=True, exist_ok=True)
    target = PUBLIC_OUT_DIR / "operator_dashboard_payload.json"
    with target.open("w") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return target


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbols", default=None,
                   help="comma-separated; defaults to dynamic-universe + 25 baseline")
    p.add_argument("--smoke-test", action="store_true",
                   help="opt in to the 3-symbol smoke-test set (never the production default)")
    p.add_argument("--once", action="store_true")
    p.add_argument("--loop", action="store_true")
    p.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_S)
    p.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_S)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    symbols = resolve_symbols(
        explicit=args.symbols, smoke_test=args.smoke_test, include_baseline=True
    )
    if not (args.once or args.loop):
        args.once = True
    if args.loop:
        while True:
            report = run_once(symbols, ttl_s=args.ttl_seconds)
            write_public_payload(report)
            if args.json:
                print(json.dumps(report))
            try:
                time.sleep(max(5, args.interval_seconds))
            except KeyboardInterrupt:
                return 0
    else:
        report = run_once(symbols, ttl_s=args.ttl_seconds)
        write_public_payload(report)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print("WROTE", PUBLIC_OUT_DIR / "operator_dashboard_payload.json")
            print(f"keys_written={report['redis_keys_written_total']}  "
                  f"errors={report['errors']}  redis_available={report['redis_available']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
