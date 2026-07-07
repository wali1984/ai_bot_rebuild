"""Binance USD-M aggTrades ingestor (public REST, read-only, V2 namespace only).

Fills the gap found by the A+ goal audit: the microstructure trade-tape
pipeline (``v2_microstructure_feed_quality_monitor`` →
``evaluate_trade_tape_confirmation``) reads ``v2:market:agg_trades:{symbol}``
but nothing wrote that key, so every tape confirmation was an all-zero
neutral 0.5. This loop writes raw aggTrades rows plus derived order-flow
features so tape confirmation, delta, and volume-acceleration become real.

Safety: public market data only; no API keys; writes only ``v2:`` keys;
never touches exchange order/leverage/margin endpoints.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from v2.backend.app.services.trade_tape.service import compute_trade_tape_features

REPO_ROOT = Path(__file__).resolve().parents[4]

AGG_TRADES_URL = "https://fapi.binance.com/fapi/v1/aggTrades?symbol={symbol}&limit={limit}"
AGG_TRADES_KEY = "v2:market:agg_trades:{symbol}"
TAPE_FEATURES_KEY = "v2:market:trade_tape_features:{symbol}"
CURSOR_KEY = "v2:market:agg_trades:rotation_cursor"
STATUS_KEY = "v2:market:agg_trades:ingestor_status"
# Binance USD-M aggTrades request weight is 20; keep well inside the shared
# 2400/min IP budget because kline/orderbook ingestors share this host.
DEFAULT_SYMBOLS_PER_CYCLE = 20
DEFAULT_LIMIT = 200
DEFAULT_TTL_SECONDS = 300
MAJORS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _connect_redis() -> Any:
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


def _fetch_agg_trades(symbol: str, *, limit: int, timeout: float = 10.0) -> list[dict[str, Any]]:
    url = AGG_TRADES_URL.format(symbol=symbol, limit=limit)
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "ai-bot-v2-agg-trades-ingestor"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload if isinstance(payload, list) else []


def compute_tape_features(trades: Iterable[Mapping[str, Any]], *, now_ms: int | None = None) -> dict[str, Any]:
    """Derive the A+ order-flow fields from raw Binance aggTrades rows.

    Buyer-maker (``m`` == True) means the aggressor was a SELLER.
    """
    features = compute_trade_tape_features(list(trades), now_ms=now_ms)
    return {
        **features,
        # Backward-compatible aliases used by this older ingestor's status and tests.
        "trade_count": features.get("trade_count_5m"),
        "large_trade_count": features.get("large_trade_count_5m"),
        "window_start_ms": features.get("tape_window_oldest_ms"),
        "window_end_ms": features.get("tape_window_newest_ms"),
    }


def _priority_symbols(client: Any) -> list[str]:
    """Majors + open positions + current intent/signal symbols.

    Tape confirmation is a hard A+/regime condition, so fresh tape must land
    on exactly the symbols the paper loop is currently evaluating, not just
    the rotation slice.
    """
    symbols: list[str] = list(MAJORS)
    if client is None:
        return symbols

    def _extend_from(key: str, *, limit: int) -> None:
        try:
            raw = client.get(key)
            payload = json.loads(raw) if raw else None
        except Exception:
            return
        if isinstance(payload, dict):
            payload = payload.get("positions") or payload.get("rows") or payload.get("intents") or []
        count = 0
        for row in payload or []:
            symbol = str((row or {}).get("symbol") or "").upper()
            if symbol and symbol not in symbols:
                symbols.append(symbol)
                count += 1
                if count >= limit:
                    return

    _extend_from("v2:trainer:hybrid_cuda:paper_positions_preview", limit=15)
    _extend_from("v2:paper:intents", limit=25)
    return symbols


def _universe(client: Any) -> list[str]:
    try:
        from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

        return [str(symbol).upper() for symbol in resolve_symbols()]
    except Exception:
        return list(MAJORS)


def run_cycle(
    *,
    client: Any,
    symbols_per_cycle: int,
    limit: int,
    ttl_seconds: int,
) -> dict[str, Any]:
    generated = _utc_iso()
    priority = _priority_symbols(client)
    universe = [symbol for symbol in _universe(client) if symbol not in priority]
    cursor = 0
    if client is not None:
        try:
            cursor = int(client.get(CURSOR_KEY) or 0)
        except Exception:
            cursor = 0
    rotation: list[str] = []
    if universe:
        cursor = cursor % len(universe)
        take = max(0, symbols_per_cycle - len(priority))
        rotation = [universe[(cursor + offset) % len(universe)] for offset in range(take)]
        next_cursor = (cursor + take) % len(universe)
        if client is not None:
            try:
                client.set(CURSOR_KEY, str(next_cursor))
            except Exception:
                pass
    targets = (priority + rotation)[: max(1, symbols_per_cycle)]
    written = 0
    failures: dict[str, str] = {}
    for symbol in targets:
        try:
            trades = _fetch_agg_trades(symbol, limit=limit)
        except Exception as exc:  # noqa: BLE001
            failures[symbol] = f"{type(exc).__name__}: {exc}"
            continue
        features = compute_tape_features(trades)
        agg_payload = {
            "schema_version": "v2_market_agg_trades_v1",
            "symbol": symbol,
            "source": "binance_fapi_public_agg_trades_rest",
            "generated_utc": generated,
            "trade_count": len(trades),
            "trades": trades,
        }
        feature_payload = {
            "schema_version": "v2_trade_tape_features_v1",
            "symbol": symbol,
            "source": "binance_fapi_public_agg_trades_rest",
            "generated_utc": generated,
            **features,
        }
        if client is not None:
            try:
                client.set(AGG_TRADES_KEY.format(symbol=symbol), json.dumps(agg_payload), ex=ttl_seconds)
                client.set(TAPE_FEATURES_KEY.format(symbol=symbol), json.dumps(feature_payload), ex=ttl_seconds)
                written += 1
            except Exception as exc:  # noqa: BLE001
                failures[symbol] = f"redis:{type(exc).__name__}"
    status = {
        "schema_version": "v2_agg_trades_ingestor_status_v1",
        "generated_utc": generated,
        "targets": targets,
        "symbols_written": written,
        "symbols_failed": failures,
        "symbols_per_cycle": symbols_per_cycle,
        "request_limit": limit,
        "ttl_seconds": ttl_seconds,
        "reads_only_public_market_data": True,
        "writes_v2_namespace_only": True,
        "places_real_order": False,
        "routes_to_live": False,
        "writes_legacy_redis": False,
    }
    if client is not None:
        try:
            client.set(STATUS_KEY, json.dumps(status), ex=max(ttl_seconds, 600))
        except Exception:
            pass
    return status


def main() -> int:
    parser = argparse.ArgumentParser(prog="v2_agg_trades_ingestor_loop")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--symbols-per-cycle", type=int, default=DEFAULT_SYMBOLS_PER_CYCLE)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    parser.add_argument("--max-cycles", type=int, default=0)
    args = parser.parse_args()
    client = _connect_redis()
    cycles = 0
    while True:
        if client is None:
            # F015: at boot this unit can start before Redis accepts
            # connections; a one-shot connect left the loop silently no-op
            # (0 writes, 0 failures) for its whole lifetime. Reconnect each
            # cycle until Redis is reachable.
            client = _connect_redis()
        status = run_cycle(
            client=client,
            symbols_per_cycle=args.symbols_per_cycle,
            limit=args.limit,
            ttl_seconds=args.ttl_seconds,
        )
        print(json.dumps({k: status[k] for k in ("generated_utc", "symbols_written", "symbols_failed")}), flush=True)
        cycles += 1
        if not args.loop or (args.max_cycles and cycles >= args.max_cycles):
            return 0
        time.sleep(max(5, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
