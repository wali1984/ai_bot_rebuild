"""V2 CoinAPI WSDS read-only ingestor loop.

This worker is intentionally V2-only and paper/shadow-only. It never
writes legacy ``msnap:*`` or ``metrics:*`` keys. It only connects when an
operator explicitly opts in with ``V2_COINAPI_WSDS_OPT_IN=true`` and a
CoinAPI key is available by env/local-secret file. Otherwise it runs as a
truthful blocked status publisher so supervision can see why WSDS is not
connected.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_ingestors.coinapi_wsds import (
    DEFAULT_TIMEFRAMES,
    normalize_wsds_snapshot,
)
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

try:
    import websockets  # type: ignore
except Exception:  # pragma: no cover - surfaced in status payload
    websockets = None  # type: ignore


WORKER_ID = "v2_coinapi_wsds_loop"
OPT_IN_ENV_VAR = "V2_COINAPI_WSDS_OPT_IN"
DEFAULT_WS_URL = "wss://ws.coinapi.io/v1/"
DEFAULT_STATUS_PATH = Path(
    "v2/frontend/public/operator_runtime/v2_coinapi_wsds/latest/v2_coinapi_wsds_status.json"
)
DEFAULT_PUBLIC_PAYLOAD_PATH = Path(
    "v2/frontend/public/v2_coinapi_wsds/latest/operator_dashboard_payload.json"
)
DEFAULT_WORKLOG_PATH = Path(
    "claude_worklog/final_readiness/v2_coinapi_wsds_persistent_readonly_stream/latest/v2_coinapi_wsds_status.json"
)
DEFAULT_SECRET_PATHS = (
    Path(".local_secrets/legacy.env"),
    Path(".local_secrets/live_credentials.env"),
    Path("v2/.env.local"),
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _read_secret_value(name: str) -> str:
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
                key = key[len("export ") :].strip()
            if key == name:
                return value.strip().strip('"').strip("'")
    return ""


def _connect_redis():
    try:
        import redis  # type: ignore

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def _safe_set_json(redis_client: Any, key: str, payload: Any, *, ex: int) -> bool:
    if redis_client is None:
        return False
    if not str(key).startswith("v2:"):
        raise ValueError(f"refused non-V2 Redis key: {key!r}")
    redis_client.set(key, json.dumps(payload, sort_keys=True, default=str), ex=int(ex))
    return True


def _coinapi_symbol_id(symbol: str, *, exchange_id: str) -> str:
    base = symbol.upper()
    if base.endswith("USDT"):
        base = base[:-4]
    market_type = "PERP" if exchange_id.upper() == "BINANCEFTS" else "SPOT"
    return f"{exchange_id.upper()}_{market_type}_{base}_USDT"


def _parse_csv(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if not value:
        return default
    parsed = tuple(part.strip() for part in value.split(",") if part.strip())
    return parsed or default


def _subscribe_data_types() -> list[str]:
    raw = [item.lower() for item in _parse_csv(os.getenv("COINAPI_SUBSCRIBE_DATA_TYPES"), ("quote", "book5"))]
    allow_trade = _env_bool("COINAPI_ALLOW_TRADE", False)
    allow_full_book = _env_bool("COINAPI_ALLOW_FULL_BOOK", False)
    out: list[str] = []
    for item in raw:
        if item == "trade" and not allow_trade:
            continue
        if item in {"book", "orderbook", "orderbooks"} and not allow_full_book:
            item = "book5"
        if item not in out:
            out.append(item)
    if "quote" not in out:
        out.insert(0, "quote")
    return out or ["quote", "book5"]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _write_status(payload: dict[str, Any], paths: tuple[Path, ...]) -> None:
    for path in paths:
        _write_json(path, payload)


def _base_status(
    *,
    symbols: tuple[str, ...],
    subscribed_symbols: tuple[str, ...] | None = None,
    max_symbols: int | None = None,
    opt_in: bool,
    credential_present: bool,
    redis_ok: bool,
    stream_connected: bool,
    classification: str,
    blocker: str | None,
    stats: dict[str, Any],
    data_types: list[str],
    ws_url: str,
) -> dict[str, Any]:
    subscribed = subscribed_symbols or symbols
    return {
        "worker_id": WORKER_ID,
        "schema_version": "v2_coinapi_wsds_status_v1",
        "classification": classification,
        "generated_utc": _utc_iso(),
        "heartbeat_at": _utc_iso(),
        "service_active": True,
        "stream_connected": bool(stream_connected),
        "blocked_reason": blocker,
        "operator_opt_in_env_var": OPT_IN_ENV_VAR,
        "operator_opt_in_enabled": bool(opt_in),
        "credential_env_names": ["COINAPI_API_KEY", "COINAPI_KEY"],
        "credential_present": bool(credential_present),
        "credential_value_emitted": False,
        "raw_secret_values_recorded": False,
        "ws_url": ws_url,
        "subscribe_data_types": data_types,
        "symbols": list(symbols),
        "symbols_count": len(symbols),
        "subscribed_symbols": list(subscribed),
        "subscribed_symbols_count": len(subscribed),
        "max_symbols": max_symbols,
        "redis_ok": bool(redis_ok),
        "stats": dict(stats),
        "heartbeat_key": "v2:market:coinapi:wsds:heartbeat",
        "target_redis_key_patterns": [
            "v2:market:coinapi:wsds:{symbol}",
            "v2:features:microfeat:{symbol}:{timeframe}",
            "v2:market:coinapi:wsds:heartbeat",
        ],
        "runtime_mode": "LIVE_DATA_AND_LIVE_DECISION_INPUTS_TRADER_EXECUTION_DISABLED",
        "live_data_enabled": True,
        "live_decision_input_enabled": True,
        "trader_execution_enabled": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "execution_live_symbols": [],
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "places_exchange_orders": False,
        "calls_test_order_endpoint": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "redis_trim_performed": False,
    }


def _blocked_status(
    *,
    symbols: tuple[str, ...],
    opt_in: bool,
    credential_present: bool,
    redis_ok: bool,
    data_types: list[str],
    ws_url: str,
) -> dict[str, Any]:
    if not opt_in:
        blocker = f"{OPT_IN_ENV_VAR} is not true; WSDS connection not opened."
    elif not credential_present:
        blocker = "COINAPI_API_KEY/COINAPI_KEY not available; WSDS connection not opened."
    elif websockets is None:
        blocker = "websockets package unavailable; WSDS connection not opened."
    else:
        blocker = "WSDS blocked before connection."
    return _base_status(
        symbols=symbols,
        subscribed_symbols=(),
        opt_in=opt_in,
        credential_present=credential_present,
        redis_ok=redis_ok,
        stream_connected=False,
        classification="V2_COINAPI_WSDS_BLOCKED",
        blocker=blocker,
        stats={},
        data_types=data_types,
        ws_url=ws_url,
    )


def _message_symbol_id(message: dict[str, Any]) -> str:
    return str(message.get("symbol_id") or message.get("symbol_id_exchange") or "")


def _snapshot_from_message(message: dict[str, Any]) -> dict[str, Any] | None:
    msg_type = str(message.get("type") or "").lower()
    now_ms = int(time.time() * 1000)
    if msg_type == "quote":
        bid = message.get("bid_price")
        ask = message.get("ask_price")
        bid_size = message.get("bid_size")
        ask_size = message.get("ask_size")
        if bid is None or ask is None:
            return None
        bid_f = float(bid)
        ask_f = float(ask)
        if bid_f <= 0 or ask_f <= 0:
            return None
        mid = (bid_f + ask_f) / 2.0
        bid_sz = float(bid_size or 0.0)
        ask_sz = float(ask_size or 0.0)
        total = bid_sz + ask_sz
        return {
            "updated_ts_ms": now_ms,
            "best_bid_px": bid_f,
            "best_ask_px": ask_f,
            "mid_px": mid,
            "spread": ((ask_f - bid_f) / mid * 10_000.0) if mid else None,
            "microprice": ((bid_f * ask_sz) + (ask_f * bid_sz)) / total if total else mid,
            "book_bid_sum_5": bid_sz,
            "book_ask_sum_5": ask_sz,
            "imbalance_5": ((bid_sz - ask_sz) / total) if total else 0.0,
        }
    if msg_type.startswith("book") or msg_type in {"orderbook", "orderbooks"}:
        bids = message.get("bids") if isinstance(message.get("bids"), list) else []
        asks = message.get("asks") if isinstance(message.get("asks"), list) else []
        if not bids or not asks:
            return None

        def price_size(item: Any) -> tuple[float | None, float | None]:
            if isinstance(item, dict):
                return _float(item.get("price")), _float(item.get("size"))
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                return _float(item[0]), _float(item[1])
            return None, None

        bid, bid_sz = price_size(bids[0])
        ask, ask_sz = price_size(asks[0])
        if not bid or not ask:
            return None
        mid = (bid + ask) / 2.0
        bid_sum = sum((price_size(item)[1] or 0.0) for item in bids[:5])
        ask_sum = sum((price_size(item)[1] or 0.0) for item in asks[:5])
        total = bid_sum + ask_sum
        return {
            "updated_ts_ms": now_ms,
            "best_bid_px": bid,
            "best_ask_px": ask,
            "mid_px": mid,
            "spread": ((ask - bid) / mid * 10_000.0) if mid else None,
            "microprice": mid,
            "book_bid_sum_5": bid_sum,
            "book_ask_sum_5": ask_sum,
            "imbalance_5": ((bid_sum - ask_sum) / total) if total else 0.0,
        }
    return None


def _combined_session_stats(
    aggregate_stats: dict[str, Any] | None,
    session_stats: dict[str, Any],
) -> dict[str, Any]:
    base = dict(aggregate_stats or {})
    counters = (
        "sessions",
        "messages_received",
        "messages_parsed",
        "snapshots_written",
        "microfeatures_written",
        "parse_errors",
        "redis_write_failures",
    )
    for key in counters:
        base[key] = int(base.get(key) or 0) + int(session_stats.get(key) or 0)
    for key in ("last_message_utc", "last_snapshot_utc", "last_error_type"):
        base[key] = session_stats.get(key) or base.get(key)
    return base


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


async def _run_session(
    *,
    symbols: tuple[str, ...],
    api_key: str,
    redis_client: Any,
    ttl_seconds: int,
    ws_url: str,
    data_types: list[str],
    max_symbols: int,
    max_seconds_per_session: float,
    max_messages_per_session: int,
    heartbeat_interval_seconds: float,
    status_paths: tuple[Path, ...],
    aggregate_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assert websockets is not None
    selected = symbols if int(max_symbols) <= 0 else symbols[: max(1, int(max_symbols))]
    exchange_id = os.getenv("COINAPI_PRIMARY_EXCHANGE_ID", "BINANCEFTS")
    symbol_map = {
        _coinapi_symbol_id(symbol, exchange_id=exchange_id): symbol
        for symbol in selected
    }
    stats = {
        "sessions": 0,
        "messages_received": 0,
        "messages_parsed": 0,
        "snapshots_written": 0,
        "microfeatures_written": 0,
        "parse_errors": 0,
        "redis_write_failures": 0,
        "last_message_utc": None,
        "last_snapshot_utc": None,
    }
    hello = {
        "type": "hello",
        "apikey": api_key,
        "heartbeat": True,
        "subscribe_data_type": data_types,
        "subscribe_filter_symbol_id": list(symbol_map.keys()),
    }
    started = time.monotonic()
    last_status = 0.0
    async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20, close_timeout=10) as ws:  # type: ignore[attr-defined]
        stats["sessions"] = 1
        await ws.send(json.dumps(hello))
        while time.monotonic() - started < max_seconds_per_session:
            if int(stats["messages_received"]) >= max_messages_per_session:
                break
            if time.monotonic() - last_status >= heartbeat_interval_seconds:
                payload = _base_status(
                    symbols=symbols,
                    subscribed_symbols=selected,
                    max_symbols=int(max_symbols),
                    opt_in=True,
                    credential_present=True,
                    redis_ok=redis_client is not None,
                    stream_connected=True,
                    classification="V2_COINAPI_WSDS_CONNECTED",
                    blocker=None,
                    stats=_combined_session_stats(aggregate_stats, stats),
                    data_types=data_types,
                    ws_url=ws_url,
                )
                _write_status(payload, status_paths)
                _safe_set_json(redis_client, "v2:market:coinapi:wsds:heartbeat", payload, ex=ttl_seconds)
                last_status = time.monotonic()
            raw = await asyncio.wait_for(ws.recv(), timeout=max(5.0, heartbeat_interval_seconds))
            stats["messages_received"] += 1
            stats["last_message_utc"] = _utc_iso()
            try:
                message = json.loads(raw)
                if not isinstance(message, dict):
                    continue
                stats["messages_parsed"] += 1
                symbol = symbol_map.get(_message_symbol_id(message))
                if not symbol:
                    continue
                snapshot = _snapshot_from_message(message)
                if snapshot is None:
                    continue
                normalized = normalize_wsds_snapshot(
                    symbol=symbol,
                    snapshot=snapshot,
                    timeframes=DEFAULT_TIMEFRAMES,
                )
                if _safe_set_json(
                    redis_client,
                    str(normalized["market_key"]),
                    normalized["market_payload"],
                    ex=ttl_seconds,
                ):
                    stats["snapshots_written"] += 1
                for key, payload in normalized["microfeat_payloads"].items():
                    if _safe_set_json(redis_client, str(key), payload, ex=ttl_seconds):
                        stats["microfeatures_written"] += 1
                stats["last_snapshot_utc"] = _utc_iso()
            except Exception:
                stats["parse_errors"] += 1
    return stats


async def _run_connected_loop(args: argparse.Namespace, symbols: tuple[str, ...], api_key: str, redis_client: Any) -> dict[str, Any]:
    data_types = _subscribe_data_types()
    ws_url = os.getenv("COINAPI_WSDS_URL", DEFAULT_WS_URL)
    status_paths = (args.out, args.out_public, args.out_worklog)
    total_started = time.monotonic()
    aggregate = {
        "sessions": 0,
        "messages_received": 0,
        "messages_parsed": 0,
        "snapshots_written": 0,
        "microfeatures_written": 0,
        "parse_errors": 0,
        "redis_write_failures": 0,
        "reconnect_count": 0,
        "last_message_utc": None,
        "last_snapshot_utc": None,
    }
    while time.monotonic() - total_started < args.total_seconds:
        try:
            stats = await _run_session(
                symbols=symbols,
                api_key=api_key,
                redis_client=redis_client,
                ttl_seconds=args.ttl_seconds,
                ws_url=ws_url,
                data_types=data_types,
                max_symbols=args.max_symbols,
                max_seconds_per_session=args.max_seconds_per_session,
                max_messages_per_session=args.max_messages_per_session,
                heartbeat_interval_seconds=args.heartbeat_interval_seconds,
                status_paths=status_paths,
                aggregate_stats=aggregate,
            )
            for key in ("sessions", "messages_received", "messages_parsed", "snapshots_written", "microfeatures_written", "parse_errors", "redis_write_failures"):
                aggregate[key] += int(stats.get(key) or 0)
            for key in ("last_message_utc", "last_snapshot_utc"):
                aggregate[key] = stats.get(key) or aggregate.get(key)
        except Exception as exc:
            aggregate["reconnect_count"] += 1
            aggregate["last_error_type"] = type(exc).__name__
            await asyncio.sleep(min(30.0, 2.0 * int(aggregate["reconnect_count"])))
        payload = _base_status(
            symbols=symbols,
            subscribed_symbols=symbols if int(args.max_symbols) <= 0 else symbols[: max(1, int(args.max_symbols))],
            max_symbols=int(args.max_symbols),
            opt_in=True,
            credential_present=True,
            redis_ok=redis_client is not None,
            stream_connected=False,
            classification="V2_COINAPI_WSDS_RECONNECTING",
            blocker=None,
            stats=aggregate,
            data_types=data_types,
            ws_url=ws_url,
        )
        _write_status(payload, status_paths)
        _safe_set_json(redis_client, "v2:market:coinapi:wsds:heartbeat", payload, ex=args.ttl_seconds)
    return aggregate


def _run_blocked_loop(args: argparse.Namespace, symbols: tuple[str, ...], opt_in: bool, credential_present: bool, redis_client: Any) -> None:
    data_types = _subscribe_data_types()
    ws_url = os.getenv("COINAPI_WSDS_URL", DEFAULT_WS_URL)
    while True:
        payload = _blocked_status(
            symbols=symbols,
            opt_in=opt_in,
            credential_present=credential_present,
            redis_ok=redis_client is not None,
            data_types=data_types,
            ws_url=ws_url,
        )
        paths = (args.out, args.out_public, args.out_worklog)
        _write_status(payload, paths)
        try:
            _safe_set_json(redis_client, "v2:market:coinapi:wsds:heartbeat", payload, ex=args.ttl_seconds)
        except Exception:
            pass
        print(json.dumps({"classification": payload["classification"], "blocked_reason": payload["blocked_reason"]}))
        sys.stdout.flush()
        if not args.loop:
            return
        time.sleep(max(30, int(args.interval_seconds)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--max-symbols", type=int, default=0, help="Maximum symbols to subscribe per WSDS session; 0 means the full V2 symbol universe.")
    parser.add_argument("--ttl-seconds", type=int, default=300)
    parser.add_argument("--heartbeat-interval-seconds", type=float, default=30.0)
    parser.add_argument("--max-seconds-per-session", type=float, default=600.0)
    parser.add_argument("--max-messages-per-session", type=int, default=5000)
    parser.add_argument("--total-seconds", type=float, default=20.0)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--out", type=Path, default=DEFAULT_STATUS_PATH)
    parser.add_argument("--out-public", type=Path, default=DEFAULT_PUBLIC_PAYLOAD_PATH)
    parser.add_argument("--out-worklog", type=Path, default=DEFAULT_WORKLOG_PATH)
    args = parser.parse_args(argv)
    if args.loop and args.once:
        print("ERROR: --loop and --once are mutually exclusive", file=sys.stderr)
        return 2
    symbols = tuple(
        resolve_symbols(
            explicit=args.symbols,
            smoke_test=bool(args.smoke_test),
            include_baseline=True,
        )
    )
    opt_in = _env_bool(OPT_IN_ENV_VAR, False)
    api_key = _read_secret_value("COINAPI_API_KEY") or _read_secret_value("COINAPI_KEY")
    redis_client = _connect_redis()
    if not opt_in or not api_key or websockets is None:
        _run_blocked_loop(args, symbols, opt_in, bool(api_key), redis_client)
        return 0
    aggregate = asyncio.run(_run_connected_loop(args, symbols, api_key, redis_client))
    print(json.dumps({"classification": "V2_COINAPI_WSDS_LOOP_EXITED", **aggregate}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
