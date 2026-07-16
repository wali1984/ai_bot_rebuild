"""V2 Binance USD-M kline websocket loop.

Read-only V2 service. It opens Binance Futures market websocket kline streams
and splits current/open klines from confirmed closed-candle storage.

Safety:
* writes only V2 Redis keys
* writes public status JSON only
* never calls REST
* never places/cancels/modifies orders
* never changes leverage or margin
* never enables live/canary
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    append_closed_candle,
    canonical_from_binance_wss,
    closed_candle_key,
    current_candle_key,
)
from v2.backend.app.services.runtime_clock import est_now_iso
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

try:
    import websockets  # type: ignore
except Exception:  # pragma: no cover
    websockets = None  # type: ignore


WORKER_ID = "v2_binance_kline_wss_loop"
DEFAULT_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
# Operator directive: preferred majors must ride the FIRST websocket
# connection so they stay covered even if later chunks degrade. This only
# reorders the resolved universe; it never adds or removes symbols.
PREFERRED_MAJOR_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
# Volatile keys (current candle, source marker, heartbeat) keep a short TTL
# regardless of --ttl-seconds so stale-freshness detection still works when
# closed-candle history TTL is raised (closed candles are immutable facts).
VOLATILE_TTL_CAP_SECONDS = 900
REDIS_RECONNECT_INTERVAL_SECONDS = 15.0
DEFAULT_WS_BASE = "wss://fstream.binance.com/market/stream?streams="
DEFAULT_STATUS_PATH = Path("v2/frontend/public/operator_runtime/v2_binance_kline_wss/latest/v2_binance_kline_wss_status.json")
DEFAULT_PUBLIC_PATH = Path("v2/frontend/public/v2_binance_kline_wss/latest/operator_dashboard_payload.json")
DEFAULT_WORKLOG_PATH = Path("claude_worklog/final_readiness/v2_binance_kline_wss_runtime/latest/v2_binance_kline_wss_status.json")


def _est_iso() -> str:
    return est_now_iso()


def _connect_redis() -> Any | None:
    try:
        import redis  # type: ignore

        url = os.getenv("V2_REDIS_URL") or os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/0"
        client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=1.0)
        client.ping()
        return client
    except Exception:
        return None


class _RedisHolder:
    """Redis handle that lazily reconnects.

    The loop previously connected exactly once at process start. When Redis
    (or name resolution at boot) was briefly unavailable, the process ran for
    the full --total-seconds window receiving millions of klines while
    persisting none of them (redis_ok=false, ohlcv_keys_written=0). This
    holder retries the connection at a bounded interval and drops broken
    clients so writes recover without a service restart.
    """

    def __init__(self) -> None:
        self._last_attempt = time.time()
        self.client: Any | None = _connect_redis()
        self.reconnects = 0

    @property
    def connected(self) -> bool:
        return self.client is not None

    def ensure(self) -> Any | None:
        if self.client is not None:
            return self.client
        now = time.time()
        if now - self._last_attempt < REDIS_RECONNECT_INTERVAL_SECONDS:
            return None
        self._last_attempt = now
        self.client = _connect_redis()
        if self.client is not None:
            self.reconnects += 1
        return self.client

    def mark_broken(self) -> None:
        client, self.client = self.client, None
        self._last_attempt = time.time()
        try:
            if client is not None:
                client.close()
        except Exception:
            pass


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _write_status(payload: dict[str, Any], paths: tuple[Path, ...]) -> None:
    for path in paths:
        _write_json(path, payload)


def _parse_csv(raw: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        return default
    out = tuple(part.strip() for part in raw.split(",") if part.strip())
    return out or default


def _resolve_symbols(raw: str | None, *, max_symbols: int) -> tuple[str, ...]:
    explicit = None
    if raw and raw.strip().lower() not in {"auto", "all", "universe"}:
        explicit = raw
    symbols = tuple(resolve_symbols(explicit=explicit))
    majors = tuple(symbol for symbol in PREFERRED_MAJOR_SYMBOLS if symbol in symbols)
    symbols = majors + tuple(symbol for symbol in symbols if symbol not in majors)
    if max_symbols > 0:
        symbols = symbols[:max_symbols]
    return symbols


def _ohlcv_key(symbol: str, timeframe: str) -> str:
    return closed_candle_key("binance", symbol, timeframe)


def _current_key(symbol: str, timeframe: str) -> str:
    return current_candle_key("binance", symbol, timeframe)


def _heartbeat_key() -> str:
    return "v2:market:ohlcv:binance:kline_wss:heartbeat"


def _source_key(symbol: str, timeframe: str) -> str:
    return f"v2:market:ohlcv:binance:{symbol}:{timeframe}:source"


def _safe_set_json(redis_client: Any, key: str, payload: Any, *, ex: int) -> bool:
    client = redis_client.ensure() if isinstance(redis_client, _RedisHolder) else redis_client
    if client is None:
        return False
    if not key.startswith("v2:"):
        raise ValueError(f"refused non-V2 Redis key: {key!r}")
    try:
        client.set(key, json.dumps(payload, sort_keys=True, default=str), ex=int(ex))
    except Exception:
        if isinstance(redis_client, _RedisHolder):
            redis_client.mark_broken()
        return False
    return True


def _safe_get_json(redis_client: Any, key: str) -> Any:
    client = redis_client.ensure() if isinstance(redis_client, _RedisHolder) else redis_client
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception:
        if isinstance(redis_client, _RedisHolder):
            redis_client.mark_broken()
        return None
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _to_kline_row(message: dict[str, Any]) -> tuple[str, str, list[Any]] | None:
    kline = message.get("k")
    if not isinstance(kline, dict):
        return None
    symbol = str(kline.get("s") or message.get("s") or "").upper()
    timeframe = str(kline.get("i") or "")
    if not symbol or not timeframe:
        return None
    try:
        open_time = int(kline["t"])
        close_time = int(kline["T"])
    except Exception:
        return None
    row = [
        open_time,
        str(kline.get("o") or "0"),
        str(kline.get("h") or "0"),
        str(kline.get("l") or "0"),
        str(kline.get("c") or "0"),
        str(kline.get("v") or "0"),
        close_time,
        str(kline.get("q") or "0"),
        int(kline.get("n") or 0),
        str(kline.get("V") or "0"),
        str(kline.get("Q") or "0"),
        str(kline.get("B") or "0"),
    ]
    return symbol, timeframe, row


def _merge_row(existing: Any, row: list[Any], *, max_candles: int) -> list[Any]:
    rows = existing if isinstance(existing, list) else []
    by_open: dict[int, Any] = {}
    for item in rows:
        if not isinstance(item, list) or not item:
            continue
        try:
            by_open[int(item[0])] = item
        except Exception:
            continue
    by_open[int(row[0])] = row
    return [by_open[key] for key in sorted(by_open)][-max(1, int(max_candles)) :]


def _stream_chunks(symbols: tuple[str, ...], timeframes: tuple[str, ...], max_streams: int) -> list[tuple[str, ...]]:
    streams = tuple(f"{symbol.lower()}@kline_{timeframe}" for symbol in symbols for timeframe in timeframes)
    chunk_size = max(1, int(max_streams))
    return [streams[index : index + chunk_size] for index in range(0, len(streams), chunk_size)]


def _base_status(
    *,
    symbols: tuple[str, ...],
    timeframes: tuple[str, ...],
    chunks: list[tuple[str, ...]],
    stream_connected_count: int,
    redis_ok: bool,
    stats: dict[str, Any],
    blocker: str | None,
    ws_base: str,
) -> dict[str, Any]:
    status = "V2_BINANCE_KLINE_WSS_CONNECTED" if stream_connected_count > 0 and not blocker else "V2_BINANCE_KLINE_WSS_BLOCKED"
    return {
        "worker_id": WORKER_ID,
        "schema_version": "v2_binance_kline_wss_status_v1",
        "status": status,
        "classification": status,
        "generated_at": _est_iso(),
        "generated_est": _est_iso(),
        "heartbeat_at": _est_iso(),
        "operator_time_zone": "America/New_York",
        "timestamp_contract": "EST_PRIMARY_WITH_PROTOCOL_EPOCH_MS_INTERNAL",
        "service_active": True,
        "stream_connected": stream_connected_count > 0,
        "stream_connected_count": stream_connected_count,
        "connection_count": len(chunks),
        "symbols": list(symbols),
        "symbols_count": len(symbols),
        "timeframes": list(timeframes),
        "stream_count": sum(len(chunk) for chunk in chunks),
        "redis_ok": redis_ok,
        "blocked_reason": blocker,
        "ws_base": ws_base,
        "stats": stats,
        "heartbeat_key": _heartbeat_key(),
        "target_redis_key_pattern": "v2:market:ohlcv_closed:binance:{symbol}:{timeframe}",
        "current_kline_key_pattern": "v2:market:kline_current:binance:{symbol}:{timeframe}",
        "source_type": "EXISTING_BINANCE_KLINE_WEBSOCKET_RUNTIME_FEED",
        "runtime_mode": "LIVE_DATA_AND_LIVE_DECISION_INPUTS_TRADER_EXECUTION_DISABLED",
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "execution_live_symbols": [],
        "writes_legacy_redis": False,
        "writes_old_redis": False,
        "writes_exchange_orders": False,
        "places_exchange_orders": False,
        "calls_test_order_endpoint": False,
        "calls_rest_api": False,
        "calls_binance_rest": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "approves_live": False,
        "approves_canary": False,
        "redis_trim_performed": False,
    }


async def _consume_chunk(
    *,
    chunk_id: int,
    streams: tuple[str, ...],
    redis_client: Any | None,
    stats: dict[str, Any],
    ws_base: str,
    ttl_seconds: int,
    max_candles: int,
    max_seconds_per_session: float,
    stop_at: float,
) -> None:
    url = ws_base + "/".join(streams)
    volatile_ttl = min(int(ttl_seconds), VOLATILE_TTL_CAP_SECONDS)
    while time.time() < stop_at:
        session_deadline = min(stop_at, time.time() + max(10.0, float(max_seconds_per_session)))
        try:
            assert websockets is not None
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, open_timeout=15, close_timeout=5, max_queue=2048) as ws:
                stats["connected_chunks"] = int(stats.get("connected_chunks") or 0) + 1
                while time.time() < session_deadline:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(1.0, session_deadline - time.time()))
                    stats["messages_received"] = int(stats.get("messages_received") or 0) + 1
                    try:
                        packet = json.loads(raw)
                    except Exception:
                        stats["parse_errors"] = int(stats.get("parse_errors") or 0) + 1
                        continue
                    data = packet.get("data") if isinstance(packet, dict) else None
                    if not isinstance(data, dict):
                        continue
                    parsed = _to_kline_row(data)
                    if parsed is None:
                        stats["parse_errors"] = int(stats.get("parse_errors") or 0) + 1
                        continue
                    symbol, timeframe, row = parsed
                    try:
                        canonical = canonical_from_binance_wss(data, symbol=symbol, timeframe=timeframe)
                    except Exception:
                        stats["parse_errors"] = int(stats.get("parse_errors") or 0) + 1
                        continue
                    source_payload = {
                        "source_type": "EXISTING_BINANCE_KLINE_WEBSOCKET_RUNTIME_FEED",
                        "source_stream": f"{symbol.lower()}@kline_{timeframe}",
                        "updated_at": _est_iso(),
                        "updated_est": _est_iso(),
                        "event_time_ms": data.get("E"),
                        "open_time_ms": row[0],
                        "close_time_ms": row[6],
                        "closed_candle": bool((data.get("k") or {}).get("x")) if isinstance(data.get("k"), dict) else False,
                    }
                    if canonical.is_closed:
                        key = _ohlcv_key(symbol, timeframe)
                        existing = _safe_get_json(redis_client, key)
                        merged = append_closed_candle(existing, canonical.to_dict(), limit=max_candles)
                        # Closed-candle HISTORY must outlive the candle interval:
                        # a flat 900s TTL expired 1h/4h keys between closes and
                        # perpetually reset history to a single row (destroying
                        # REST backfills). Keep the CLI TTL as a floor only.
                        interval_seconds = {
                            "1m": 60, "3m": 180, "5m": 300, "15m": 900,
                            "30m": 1800, "1h": 3600, "2h": 7200, "4h": 14400,
                            "6h": 21600, "12h": 43200, "1d": 86400,
                        }.get(str(timeframe), 3600)
                        closed_ttl = max(int(ttl_seconds), interval_seconds * 3)
                        if _safe_set_json(redis_client, key, merged, ex=closed_ttl):
                            stats["ohlcv_closed_keys_written"] = int(stats.get("ohlcv_closed_keys_written") or 0) + 1
                            stats["ohlcv_keys_written"] = int(stats.get("ohlcv_keys_written") or 0) + 1
                    else:
                        key = _current_key(symbol, timeframe)
                        if _safe_set_json(redis_client, key, canonical.to_dict(), ex=volatile_ttl):
                            stats["kline_current_keys_written"] = int(stats.get("kline_current_keys_written") or 0) + 1
                    if _safe_set_json(redis_client, _source_key(symbol, timeframe), source_payload, ex=volatile_ttl):
                        stats["source_keys_written"] = int(stats.get("source_keys_written") or 0) + 1
                    stats["last_symbol"] = symbol
                    stats["last_timeframe"] = timeframe
                    stats["last_event_est"] = _est_iso()
        except asyncio.TimeoutError:
            stats["session_timeouts"] = int(stats.get("session_timeouts") or 0) + 1
        except Exception as exc:
            stats["connection_errors"] = int(stats.get("connection_errors") or 0) + 1
            stats[f"chunk_{chunk_id}_last_error"] = f"{type(exc).__name__}:{str(exc)[:160]}"
            await asyncio.sleep(2.0)


async def run_loop(args: argparse.Namespace) -> int:
    if websockets is None:
        symbols = _resolve_symbols(args.symbols, max_symbols=int(args.max_symbols))
        timeframes = _parse_csv(args.timeframes, DEFAULT_TIMEFRAMES)
        payload = _base_status(
            symbols=symbols,
            timeframes=timeframes,
            chunks=[],
            stream_connected_count=0,
            redis_ok=False,
            stats={},
            blocker="websockets package unavailable",
            ws_base=str(args.ws_base),
        )
        _write_status(payload, (Path(args.status_path), Path(args.public_path), Path(args.worklog_path)))
        print(json.dumps(payload, sort_keys=True), flush=True)
        return 2

    redis_holder = _RedisHolder()
    symbols = _resolve_symbols(args.symbols, max_symbols=int(args.max_symbols))
    timeframes = _parse_csv(args.timeframes, DEFAULT_TIMEFRAMES)
    chunks = _stream_chunks(symbols, timeframes, max_streams=int(args.max_streams_per_connection))
    stats: dict[str, Any] = {
        "messages_received": 0,
        "ohlcv_closed_keys_written": 0,
        "ohlcv_keys_written": 0,
        "kline_current_keys_written": 0,
        "source_keys_written": 0,
        "parse_errors": 0,
        "connection_errors": 0,
        "session_timeouts": 0,
        "connected_chunks": 0,
    }
    status_paths = (Path(args.status_path), Path(args.public_path), Path(args.worklog_path))

    async def status_writer(stop_at: float) -> None:
        while time.time() < stop_at:
            redis_ok = redis_holder.ensure() is not None
            snapshot = dict(stats)
            snapshot["redis_reconnects"] = redis_holder.reconnects
            payload = _base_status(
                symbols=symbols,
                timeframes=timeframes,
                chunks=chunks,
                stream_connected_count=int(stats.get("connected_chunks") or 0),
                redis_ok=redis_ok,
                stats=snapshot,
                blocker=None if redis_ok else "Redis unavailable; websocket data not persisted.",
                ws_base=str(args.ws_base),
            )
            _write_status(payload, status_paths)
            _safe_set_json(redis_holder, _heartbeat_key(), payload, ex=min(int(args.ttl_seconds), VOLATILE_TTL_CAP_SECONDS))
            print(json.dumps({
                "status": payload["status"],
                "generated_est": payload["generated_est"],
                "stream_count": payload["stream_count"],
                "messages_received": stats.get("messages_received"),
                "ohlcv_keys_written": stats.get("ohlcv_keys_written"),
                "live_gate": payload["live_gate"],
            }, sort_keys=True), flush=True)
            await asyncio.sleep(max(1.0, float(args.heartbeat_interval_seconds)))

    while True:
        stop_at = time.time() + max(15.0, float(args.total_seconds))
        stats["connected_chunks"] = 0
        tasks = [
            asyncio.create_task(
                _consume_chunk(
                    chunk_id=index,
                    streams=chunk,
                    redis_client=redis_holder,
                    stats=stats,
                    ws_base=str(args.ws_base),
                    ttl_seconds=int(args.ttl_seconds),
                    max_candles=int(args.max_candles),
                    max_seconds_per_session=float(args.max_seconds_per_session),
                    stop_at=stop_at,
                )
            )
            for index, chunk in enumerate(chunks)
        ]
        tasks.append(asyncio.create_task(status_writer(stop_at)))
        await asyncio.gather(*tasks, return_exceptions=True)
        if not args.loop:
            break
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="auto")
    parser.add_argument("--timeframes", default=",".join(DEFAULT_TIMEFRAMES))
    parser.add_argument("--max-symbols", type=int, default=0)
    parser.add_argument("--max-streams-per-connection", type=int, default=120)
    parser.add_argument("--max-candles", type=int, default=100)
    parser.add_argument("--ttl-seconds", type=int, default=900)
    parser.add_argument("--ws-base", default=DEFAULT_WS_BASE)
    parser.add_argument("--total-seconds", type=float, default=86400.0)
    parser.add_argument("--max-seconds-per-session", type=float, default=600.0)
    parser.add_argument("--heartbeat-interval-seconds", type=float, default=30.0)
    parser.add_argument("--status-path", default=str(DEFAULT_STATUS_PATH))
    parser.add_argument("--public-path", default=str(DEFAULT_PUBLIC_PATH))
    parser.add_argument("--worklog-path", default=str(DEFAULT_WORKLOG_PATH))
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args(argv)
    return asyncio.run(run_loop(args))


if __name__ == "__main__":
    raise SystemExit(main())
