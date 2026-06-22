"""V2 Binance public-metadata ingestor (read-only, paper-safe).

Pulls Binance USD-M public endpoints that the legacy bot used to power
mark-price / funding / open-interest / orderbook signals. Writes only
``v2:market:*`` Redis keys and a public payload. Never makes a signed
request, never calls a mutation endpoint, never reads or prints any
credential value.

Endpoints used (all public, no auth):
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
import urllib.error
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
DEFAULT_INTERVAL_S = 30
DEFAULT_TTL_S = 300
HTTP_TIMEOUT_S = 6.0

LIVE_GATE = "blocked_human_only"

PUBLIC_OUT_DIR = REPO / "v2/frontend/public/v2_binance_public_metadata/latest"


def _est_iso() -> str:
    return datetime.now(EST).strftime("%Y-%m-%dT%H:%M:%S%z")


def _http_get_json(url: str) -> Any:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
        return json.loads(resp.read().decode())


def fetch_premium_index(symbol: str) -> Dict[str, Any]:
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
    }
    return out


def fetch_open_interest(symbol: str) -> Dict[str, Any]:
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
    }


def fetch_orderbook(symbol: str, limit: int = 20) -> Dict[str, Any]:
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
    }


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
            entry["premium_index"] = fetch_premium_index(symbol)
        except Exception as e:
            entry["premium_index_error"] = str(e)
            error_count += 1
        try:
            entry["open_interest"] = fetch_open_interest(symbol)
        except Exception as e:
            entry["open_interest_error"] = str(e)
            error_count += 1
        try:
            entry["orderbook_top"] = fetch_orderbook(symbol)
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
    finished_at = _est_iso()
    return {
        "started_at_est": started_at,
        "finished_at_est": finished_at,
        "symbols": symbols,
        "redis_available": redis_available,
        "redis_keys_written_total": write_count,
        "errors": error_count,
        "per_symbol": per_symbol,
        "live_gate": LIVE_GATE,
        "writes_exchange_orders": False,
        "endpoints_used": [
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
