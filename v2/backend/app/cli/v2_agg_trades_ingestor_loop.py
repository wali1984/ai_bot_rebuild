"""Binance USD-M aggTrades ingestor (public WebSocket primary, V2 only).

Fills the gap found by the A+ goal audit: the microstructure trade-tape
pipeline (``v2_microstructure_feed_quality_monitor`` →
``evaluate_trade_tape_confirmation``) reads ``v2:market:agg_trades:{symbol}``
but nothing wrote that key, so every tape confirmation was an all-zero
neutral 0.5. This loop writes raw aggTrades rows plus derived order-flow
features so tape confirmation, delta, and volume-acceleration become real.

Safety: public market data only; no API keys; writes only ``v2:`` keys;
never touches exchange order/leverage/margin endpoints. REST is fallback-only
and requires ``BINANCE_REST_FALLBACK_ALLOWED=true``.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from v2.backend.app.services.binance_unified_websocket_transport import (
    REST_FALLBACK_ENV,
    binance_rest_fallback_allowed,
)
from v2.backend.app.services.trade_tape.service import (
    BinanceAggTradesBatchFetchResult,
    BinanceAggTradesFetchResult,
    WEBSOCKET_PRIMARY_SOURCE,
    compute_trade_tape_features,
    fetch_binance_agg_trades_batch_with_source,
    fetch_binance_agg_trades_with_source,
)

REPO_ROOT = Path(__file__).resolve().parents[4]

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


def _fetch_agg_trades(symbol: str, *, limit: int, timeout: float = 10.0) -> BinanceAggTradesFetchResult:
    return fetch_binance_agg_trades_with_source(symbol, limit=limit, timeout=timeout)


def _fetch_agg_trades_batch(
    symbols: list[str],
    *,
    limit: int,
    timeout: float = 20.0,
) -> BinanceAggTradesBatchFetchResult:
    return fetch_binance_agg_trades_batch_with_source(symbols, limit_per_symbol=limit, timeout=timeout)


def _normalize_fetch_result(fetched: Any, *, symbol: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if isinstance(fetched, BinanceAggTradesFetchResult):
        return fetched.trades, fetched.status()
    if isinstance(fetched, tuple) and len(fetched) == 2:
        trades, source = fetched
        metadata = {
            "symbol": symbol,
            "source": str(source),
            "transport": "test_or_legacy_fetcher",
            "websocket_primary": True,
            "fallback_used": False,
            "fallback_reason": None,
            "rest_fallback_allowed": binance_rest_fallback_allowed(),
            "rest_fallback_env": REST_FALLBACK_ENV,
        }
        return list(trades), metadata
    return list(fetched or []), {
        "symbol": symbol,
        "source": WEBSOCKET_PRIMARY_SOURCE,
        "transport": "websocket_primary_fetcher",
        "websocket_primary": True,
        "fallback_used": False,
        "fallback_reason": None,
        "rest_fallback_allowed": binance_rest_fallback_allowed(),
        "rest_fallback_env": REST_FALLBACK_ENV,
    }


def _write_symbol_tape(
    *,
    client: Any,
    symbol: str,
    trades: list[dict[str, Any]],
    fetch_metadata: Mapping[str, Any],
    generated: str,
    ttl_seconds: int,
) -> bool:
    features = compute_tape_features(trades)
    source = str(fetch_metadata.get("source") or WEBSOCKET_PRIMARY_SOURCE)
    agg_payload = {
        "schema_version": "v2_market_agg_trades_v1",
        "symbol": symbol,
        "source": source,
        "transport": fetch_metadata.get("transport"),
        "websocket_primary": bool(fetch_metadata.get("websocket_primary", True)),
        "fallback_used": bool(fetch_metadata.get("fallback_used", False)),
        "fallback_reason": fetch_metadata.get("fallback_reason"),
        "empty_tape_reason": fetch_metadata.get("empty_tape_reason"),
        "generated_utc": generated,
        "trade_count": len(trades),
        "trades": trades,
    }
    feature_payload = {
        "schema_version": "v2_trade_tape_features_v1",
        "symbol": symbol,
        "source": source,
        "transport": fetch_metadata.get("transport"),
        "websocket_primary": bool(fetch_metadata.get("websocket_primary", True)),
        "fallback_used": bool(fetch_metadata.get("fallback_used", False)),
        "fallback_reason": fetch_metadata.get("fallback_reason"),
        "empty_tape_reason": fetch_metadata.get("empty_tape_reason"),
        "generated_utc": generated,
        **features,
    }
    if client is None:
        return False
    client.set(AGG_TRADES_KEY.format(symbol=symbol), json.dumps(agg_payload), ex=ttl_seconds)
    client.set(TAPE_FEATURES_KEY.format(symbol=symbol), json.dumps(feature_payload), ex=ttl_seconds)
    return True


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
    websocket_batch: bool = True,
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
    no_tape: dict[str, str] = {}
    source_counts: dict[str, int] = {}
    batch_status: dict[str, Any] | None = None
    remaining_targets = list(targets)
    if websocket_batch and targets:
        try:
            batch = _fetch_agg_trades_batch(list(targets), limit=limit)
            batch_status = batch.status()
            remaining_targets = []
            batch_metadata = {
                "source": batch.source,
                "transport": batch.transport,
                "websocket_primary": batch.websocket_primary,
                "fallback_used": batch.fallback_used,
                "fallback_reason": batch.fallback_reason,
                "rest_fallback_allowed": batch.rest_fallback_allowed,
                "rest_fallback_env": REST_FALLBACK_ENV,
            }
            for symbol in targets:
                trades = list(batch.trades_by_symbol.get(symbol) or [])
                reason = (batch.symbol_errors or {}).get(symbol)
                if not trades:
                    reason = reason or "NO_WEBSOCKET_AGG_TRADE_WITHIN_TIMEOUT"
                    no_tape[symbol] = reason
                try:
                    metadata = dict(batch_metadata)
                    if reason:
                        metadata["empty_tape_reason"] = reason
                    if _write_symbol_tape(
                        client=client,
                        symbol=symbol,
                        trades=trades,
                        fetch_metadata=metadata,
                        generated=generated,
                        ttl_seconds=ttl_seconds,
                    ):
                        written += 1
                    source_counts[batch.source] = int(source_counts.get(batch.source) or 0) + 1
                except Exception as exc:  # noqa: BLE001
                    failures[symbol] = f"redis:{type(exc).__name__}"
        except Exception as exc:  # noqa: BLE001
            batch_status = {
                "source": WEBSOCKET_PRIMARY_SOURCE,
                "transport": "websocket_batch",
                "websocket_primary": True,
                "fallback_used": False,
                "fallback_reason": f"{type(exc).__name__}: {exc}",
                "rest_fallback_allowed": binance_rest_fallback_allowed(),
                "rest_fallback_env": REST_FALLBACK_ENV,
                "symbol_count": len(targets),
                "symbols_with_trades": 0,
            }

    for symbol in remaining_targets:
        try:
            fetched = _fetch_agg_trades(symbol, limit=limit)
            trades, fetch_metadata = _normalize_fetch_result(fetched, symbol=symbol)
        except Exception as exc:  # noqa: BLE001
            failures[symbol] = f"{type(exc).__name__}: {exc}"
            continue
        source = str(fetch_metadata.get("source") or WEBSOCKET_PRIMARY_SOURCE)
        source_counts[source] = int(source_counts.get(source) or 0) + 1
        if client is not None:
            try:
                if _write_symbol_tape(
                    client=client,
                    symbol=symbol,
                    trades=trades,
                    fetch_metadata=fetch_metadata,
                    generated=generated,
                    ttl_seconds=ttl_seconds,
                ):
                    written += 1
            except Exception as exc:  # noqa: BLE001
                failures[symbol] = f"redis:{type(exc).__name__}"
    status = {
        "schema_version": "v2_agg_trades_ingestor_status_v1",
        "generated_utc": generated,
        "targets": targets,
        "symbols_written": written,
        "symbols_failed": failures,
        "symbols_without_websocket_tape": no_tape,
        "symbols_per_cycle": symbols_per_cycle,
        "request_limit": limit,
        "ttl_seconds": ttl_seconds,
        "reads_only_public_market_data": True,
        "transport_policy": "binance_public_agg_trade_websocket_primary_rest_fallback_only",
        "websocket_batch_enabled": bool(websocket_batch),
        "websocket_batch_status": batch_status,
        "source_counts": source_counts,
        "rest_fallback_allowed": binance_rest_fallback_allowed(),
        "rest_fallback_env": REST_FALLBACK_ENV,
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
    parser.add_argument(
        "--per-symbol-websocket",
        action="store_true",
        help="Disable combined-stream collection and use one WebSocket per symbol.",
    )
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
            websocket_batch=not args.per_symbol_websocket,
        )
        print(json.dumps({k: status[k] for k in ("generated_utc", "symbols_written", "symbols_failed")}), flush=True)
        cycles += 1
        if not args.loop or (args.max_cycles and cycles >= args.max_cycles):
            return 0
        time.sleep(max(5, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
