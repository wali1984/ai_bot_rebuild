"""Seed Binance USD-M mark/index prices from public WebSocket.

Public market data only. REST is not used here. The worker listens to the
all-symbol mark-price stream and writes only ``v2:market:mark_price:{symbol}``
payloads for requested symbols so current-price resolution can remain
WebSocket-primary for low-activity symbols that do not emit bookTicker quickly.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from typing import Any, Mapping

from v2.backend.app.services.binance_unified_websocket_transport import (
    BINANCE_USDM_MARKET_STREAM_URL,
)
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

STREAM_NAME = "!markPrice@arr@1s"
STREAM_URL = f"{BINANCE_USDM_MARKET_STREAM_URL}/market/ws/{STREAM_NAME}"
REDIS_KEY_TEMPLATE = "v2:market:mark_price:{symbol}"
STATUS_KEY = "v2:market:mark_price_wss_status"
DEFAULT_TTL_SECONDS = 180
LIVE_GATE = "blocked_human_only"
MARK_CADENCE_POLICY_VERSION = "BINANCE_USDM_MARK_PRICE_STREAM_1S_CADENCE_V1"
EXPECTED_UPDATE_INTERVAL_SECONDS = 1.0
FRESHNESS_BUDGET_SECONDS = 1.0
MARK_AUTHENTICATION_BOUNDARY = "BINANCE_USDM_TLS_WSS_MARK_PRICE_PUBLIC_STREAM_V1"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _iso_from_ms(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        ms = int(float(value))
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _redis_client(enabled: bool) -> Any:
    if not enabled:
        return None
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def _safe_set(client: Any, key: str, payload: Mapping[str, Any], *, ttl_seconds: int) -> bool:
    if client is None:
        return False
    if not key.startswith("v2:market:"):
        raise ValueError(f"refused_non_market_key:{key}")
    client.set(key, json.dumps(dict(payload), sort_keys=True, separators=(",", ":")), ex=int(ttl_seconds))
    return True


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    material = {key: value for key, value in payload.items() if key != "evidence_sha256"}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _rows_from_message(raw: Any) -> list[Mapping[str, Any]]:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if isinstance(raw, Mapping) and isinstance(raw.get("data"), list):
        raw = raw["data"]
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, Mapping)]
    if isinstance(raw, Mapping):
        return [raw]
    return []


def _normalize_row(
    row: Mapping[str, Any],
    *,
    generated_at: str,
    available_at: str,
) -> dict[str, Any] | None:
    symbol = str(row.get("s") or row.get("symbol") or "").upper()
    mark_price = _float(row.get("p") or row.get("markPrice") or row.get("mark_price"))
    index_price = _float(row.get("i") or row.get("indexPrice") or row.get("index_price"))
    if not symbol or mark_price is None or mark_price <= 0:
        return None
    event_time = _iso_from_ms(row.get("E") or row.get("event_time_ms"))
    if event_time is None:
        # Receipt time is not exchange event time.  A clockless row cannot be
        # promoted to maintenance/liquidation authority by substituting it.
        return None
    payload = {
        "schema_version": "binance_usdm_mark_price_wss_v1",
        "symbol": symbol,
        "mark_price": mark_price,
        "markPrice": mark_price,
        "index_price": index_price,
        "indexPrice": index_price,
        "estimated_settle_price": _float(row.get("P") or row.get("estimatedSettlePrice")),
        "last_funding_rate": _float(row.get("r") or row.get("lastFundingRate")),
        "next_funding_time_ms": row.get("T") or row.get("nextFundingTime"),
        "event_time": event_time,
        "generated_at": generated_at,
        "available_at": available_at,
        "source": "binance_usdm_wss_mark_price_all_symbols",
        "transport": "websocket_primary",
        "stream_name": STREAM_NAME,
        "exchange_source_authenticated": True,
        "authentication_boundary": MARK_AUTHENTICATION_BOUNDARY,
        "cadence_policy_version": MARK_CADENCE_POLICY_VERSION,
        "expected_update_interval_seconds": EXPECTED_UPDATE_INTERVAL_SECONDS,
        "freshness_budget_seconds": FRESHNESS_BUDGET_SECONDS,
        "event_time_semantics": "BINANCE_USDM_WEBSOCKET_EVENT_TIME_E",
        "generated_at_semantics": "LOCAL_NORMALIZATION_COMPLETION_TIME",
        "available_at_semantics": "LOCAL_REDIS_PUBLICATION_RELEASE_TIME",
        "live_gate": LIVE_GATE,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "transfer_or_withdrawal": False,
        "raw_credentials_exposed": False,
    }
    payload["evidence_sha256"] = _payload_sha256(payload)
    return payload


def process_mark_price_message(
    raw: Any,
    *,
    symbols: set[str] | None = None,
    redis_client: Any = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    wanted = {str(symbol).upper() for symbol in symbols or set() if symbol}
    rows: list[dict[str, Any]] = []
    written_keys: list[str] = []
    for row in _rows_from_message(raw):
        generated_at = _utc_now()
        available_at = _utc_now()
        payload = _normalize_row(
            row,
            generated_at=generated_at,
            available_at=available_at,
        )
        if payload is None:
            continue
        symbol = str(payload["symbol"])
        if wanted and symbol not in wanted:
            continue
        key = REDIS_KEY_TEMPLATE.format(symbol=symbol)
        if _safe_set(redis_client, key, payload, ttl_seconds=ttl_seconds):
            written_keys.append(key)
        rows.append(payload)
    return {
        "observed_count": len(rows),
        "symbols_observed": sorted({str(row["symbol"]) for row in rows}),
        "redis_keys_written": written_keys,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "transfer_or_withdrawal": False,
    }


async def _run_ws(
    *,
    symbols: set[str],
    redis_client: Any,
    ttl_seconds: int,
    max_messages: int,
    min_symbols: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    try:
        import websockets  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("websockets package is required for mark-price WSS mode") from exc

    observed: set[str] = set()
    total_rows = 0
    messages = 0
    async with websockets.connect(STREAM_URL, ping_interval=20, close_timeout=1) as ws:
        while messages < max(1, int(max_messages)):
            raw = await asyncio.wait_for(ws.recv(), timeout=max(1.0, float(timeout_seconds)))
            messages += 1
            result = process_mark_price_message(
                raw,
                symbols=symbols,
                redis_client=redis_client,
                ttl_seconds=ttl_seconds,
            )
            total_rows += int(result.get("observed_count") or 0)
            observed.update(str(symbol) for symbol in result.get("symbols_observed") or [])
            if min_symbols > 0 and len(observed) >= min_symbols:
                break
    return {
        "messages_processed": messages,
        "observed_symbol_count": len(observed),
        "observed_symbols": sorted(observed),
        "observed_rows": total_rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_binance_mark_price_wss_seeder")
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--write-redis", action="store_true")
    parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    parser.add_argument("--max-messages", type=int, default=3)
    parser.add_argument("--min-symbols", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    args = parser.parse_args(argv)

    symbols = set(resolve_symbols(explicit=args.symbols, smoke_test=args.smoke_test, include_baseline=True))
    redis_client = _redis_client(bool(args.write_redis))
    status: dict[str, Any] = {
        "schema_version": "binance_usdm_mark_price_wss_seeder_status_v1",
        "generated_utc": _utc_now(),
        "stream_url": STREAM_URL,
        "symbol_count": len(symbols),
        "write_redis": bool(args.write_redis),
        "redis_available": redis_client is not None,
        "live_gate": LIVE_GATE,
        "rest_used": False,
        "rest_fallback_allowed": False,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "transfer_or_withdrawal": False,
        "raw_credentials_exposed": False,
    }
    try:
        run = asyncio.run(
            _run_ws(
                symbols=symbols,
                redis_client=redis_client,
                ttl_seconds=int(args.ttl_seconds),
                max_messages=int(args.max_messages),
                min_symbols=int(args.min_symbols),
                timeout_seconds=float(args.timeout_seconds),
            )
        )
        status.update(run)
        status["status"] = "OK"
    except Exception as exc:  # noqa: BLE001
        status["status"] = "ERROR"
        status["error"] = f"{type(exc).__name__}:{exc}"
    if redis_client is not None:
        _safe_set(redis_client, STATUS_KEY, status, ttl_seconds=600)
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status.get("status") == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
