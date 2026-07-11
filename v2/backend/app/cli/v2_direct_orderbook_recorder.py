"""Zero-budget direct Binance/KuCoin orderbook recorder.

Public market data only:
  - no real orders
  - no test orders
  - no leverage or margin mutation
  - no transfers or withdrawals
  - no legacy Redis writes
  - writes only new v2:orderbook:* keys when Redis output is enabled
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from v2.backend.app.services.binance_unified_websocket_transport import (
    REST_FALLBACK_ENV,
    binance_rest_fallback_allowed,
    require_binance_rest_fallback,
)
from v2.backend.app.services.orderbook_recorder.features import epoch_ms, utc_now_iso
from v2.backend.app.services.orderbook_recorder.local_book import LocalOrderBook
from v2.backend.app.services.orderbook_recorder.providers import (
    build_binance_stream_names,
    build_kucoin_subscription_messages,
    kucoin_v2_symbol_to_futures,
    kucoin_v2_symbol_to_spot,
    parse_binance_message,
    parse_kucoin_message,
)
from v2.backend.app.services.orderbook_recorder.status import (
    GOAL_ID,
    LIVE_GATE,
    consumption_statuses,
    default_universe_gap_status,
    provider_decision_status,
    provider_gap_mapping,
    audit_configured_symbol_feed_coverage,
    replay_engine_status_for_repo,
    status_output_dirs,
    storage_budget_status,
    summarize_direct_feed_coverage,
)
from v2.backend.app.services.orderbook_recorder.store import LocalReplayStore
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_REPLAY_ROOT = REPO_ROOT / "v2/runtime/orderbook_replay"
BINANCE_USDM_COMBINED_WS = "wss://fstream.binance.com/stream?streams="
BINANCE_FAPI_BASE = "https://fapi.binance.com"
KUCOIN_BULLET_PUBLIC_BY_TRADE_TYPE = {
    "FUTURES": "https://api-futures.kucoin.com/api/v1/bullet-public",
    "SPOT": "https://api.kucoin.com/api/v1/bullet-public",
}
NEW_REDIS_PREFIX = "v2:orderbook:"
REDIS_TTL_SECONDS = 30
SYMBOL_FILTER_CACHE_TTL_SECONDS = 24 * 60 * 60
STATUS_WORKER_ID = "v2_direct_orderbook_recorder"


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


def _read_json_payload(client: Any, key: str) -> Any:
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception:
        return None
    if raw in (None, ""):
        return None
    try:
        if isinstance(raw, bytes):
            return json.loads(raw.decode("utf-8", errors="ignore"))
        if isinstance(raw, str):
            return json.loads(raw)
        if isinstance(raw, Mapping):
            return dict(raw)
    except Exception:
        return None
    return None


def _safe_redis_set(client: Any, key: str, payload: dict[str, Any], *, ttl_seconds: int = REDIS_TTL_SECONDS) -> bool:
    if client is None:
        return False
    if not key.startswith(NEW_REDIS_PREFIX):
        raise ValueError(f"refused_non_orderbook_redis_key:{key}")
    client.set(key, json.dumps(payload, sort_keys=True, separators=(",", ":")), ex=int(ttl_seconds))
    return True


def _safe_symbol_filter_cache_set(
    client: Any,
    key: str,
    payload: dict[str, Any],
    *,
    ttl_seconds: int = SYMBOL_FILTER_CACHE_TTL_SECONDS,
) -> bool:
    if client is None:
        return False
    allowed_exact = {
        "v2:exchange:symbol_filters",
        "v2:exchange:binance:exchangeInfo",
        "v2:exchange:binance_usdm:exchangeInfo",
    }
    allowed_prefixes = (
        "v2:exchange:symbol_filters:",
        "v2:symbol_filters:",
        "v2:binance:symbol_filters:",
    )
    if key not in allowed_exact and not key.startswith(allowed_prefixes):
        raise ValueError(f"refused_non_symbol_filter_redis_key:{key}")
    client.set(key, json.dumps(payload, sort_keys=True, separators=(",", ":")), ex=int(ttl_seconds))
    return True


def _write_status_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_goal_statuses(
    *,
    repo_root: Path = REPO_ROOT,
    replay_store: LocalReplayStore | None = None,
    recorder_active: bool = False,
    run_status: dict[str, Any] | None = None,
    provider_symbol_support: dict[str, Any] | None = None,
) -> dict[str, Path]:
    public_dir, goal_dir = status_output_dirs(repo_root)
    store = replay_store or LocalReplayStore(DEFAULT_REPLAY_ROOT)
    replay_status = store.status()
    provider_symbol_support = provider_symbol_support or (run_status or {}).get("provider_symbol_support") or {}
    replay_status.update(
        {
            "goal_id": GOAL_ID,
            "live_gate": LIVE_GATE,
            "recorder_active": bool(recorder_active),
            "run_status": run_status or {},
            "provider_symbol_support": provider_symbol_support,
        }
    )
    replay_status["direct_feed_coverage"] = summarize_direct_feed_coverage(replay_status.get("feed_coverage") or {})
    replay_status["configured_symbol_coverage"] = audit_configured_symbol_feed_coverage(
        feed_coverage=replay_status.get("feed_coverage") or {},
        configured_symbols=list((run_status or {}).get("symbols") or []),
        provider_symbol_support=provider_symbol_support,
    )
    default_symbols: list[str] = []
    try:
        default_symbols = resolve_symbols(explicit=None, smoke_test=False, include_baseline=True)
    except Exception:
        default_symbols = []
    replay_engine_status = replay_engine_status_for_repo(
        repo_root=repo_root,
        replay_root=store.root,
        replay_store_status=replay_status,
    )
    artifacts: dict[str, dict[str, Any]] = {
        "zero_budget_provider_decision_status.json": provider_decision_status(),
        "provider_gap_to_direct_feed_mapping.json": provider_gap_mapping(),
        "local_orderbook_replay_store_status.json": replay_status,
        "direct_provider_symbol_support_status.json": provider_symbol_support_status(provider_symbol_support),
        "orderbook_storage_budget_status.json": storage_budget_status(replay_status),
        "orderbook_default_universe_gap_status.json": default_universe_gap_status(
            feed_coverage=replay_status.get("feed_coverage") or {},
            default_symbols=default_symbols,
            provider_symbol_support=provider_symbol_support,
        ),
    }
    artifacts.update(
        consumption_statuses(
            recorder_active=recorder_active,
            replay_store_status=replay_status,
            local_replay_engine_status=replay_engine_status,
            provider_symbol_support=provider_symbol_support,
        )
    )
    written: dict[str, Path] = {}
    for filename, payload in artifacts.items():
        for directory in (public_dir, goal_dir):
            target = directory / filename
            _write_status_json(target, payload)
            written[str(target)] = target
    return written


def _top_key(exchange: str, symbol: str) -> str:
    return f"{NEW_REDIS_PREFIX}top:{exchange}:{symbol.upper()}"


def _depth_key(exchange: str, symbol: str) -> str:
    return f"{NEW_REDIS_PREFIX}depth:{exchange}:{symbol.upper()}"


def _features_key(exchange: str, symbol: str) -> str:
    return f"{NEW_REDIS_PREFIX}features:{exchange}:{symbol.upper()}"


def _health_key(exchange: str) -> str:
    return f"{NEW_REDIS_PREFIX}health:{exchange}"


def _redis_feature_freshness_status(
    redis_client: Any,
    *,
    exchange_symbols: Mapping[str, list[str]],
    stale_bound_ms: float = 1500.0,
) -> dict[str, Any]:
    generated_at = utc_now_iso()
    now_ms = epoch_ms(generated_at)
    stale_bound = max(0.0, float(stale_bound_ms))
    checked: dict[str, Any] = {}
    fresh_count = 0
    stale_count = 0
    missing_count = 0
    read_error_count = 0
    invalid_payload_count = 0
    feature_keys_read: list[str] = []
    status = {
        "enabled": True,
        "generated_at": generated_at,
        "stale_bound_ms": stale_bound,
        "redis_available": redis_client is not None,
        "feature_key_prefix": f"{NEW_REDIS_PREFIX}features:",
        "symbols_checked": [],
        "feature_keys_read": feature_keys_read,
        "fresh_symbol_count": 0,
        "stale_symbol_count": 0,
        "missing_symbol_count": 0,
        "read_error_count": 0,
        "invalid_payload_count": 0,
        "by_symbol": checked,
        "old_redis_reads": False,
        "old_redis_writes": False,
        "redis_trim": False,
    }
    if redis_client is None:
        status["status"] = "REDIS_UNAVAILABLE"
        return status

    for exchange, symbols in sorted(exchange_symbols.items()):
        normalized_exchange = str(exchange)
        for raw_symbol in sorted({str(symbol).upper() for symbol in symbols if symbol}):
            symbol_key = f"{normalized_exchange}:{raw_symbol}"
            feature_key = _features_key(normalized_exchange, raw_symbol)
            feature_keys_read.append(feature_key)
            status["symbols_checked"].append(symbol_key)
            row: dict[str, Any] = {
                "exchange": normalized_exchange,
                "symbol": raw_symbol,
                "features_key": feature_key,
                "present": False,
                "fresh": False,
                "age_ms": None,
                "freshness_reference_field": None,
                "freshness_reference_time": None,
                "stale_reason": None,
            }
            checked[symbol_key] = row
            try:
                raw_payload = redis_client.get(feature_key)
            except Exception as exc:  # noqa: BLE001
                read_error_count += 1
                row["stale_reason"] = "REDIS_READ_ERROR"
                row["error"] = f"{type(exc).__name__}:{exc}"
                continue
            if raw_payload in (None, ""):
                missing_count += 1
                row["stale_reason"] = "KEY_MISSING"
                continue
            row["present"] = True
            try:
                if isinstance(raw_payload, bytes):
                    payload = json.loads(raw_payload.decode("utf-8"))
                elif isinstance(raw_payload, str):
                    payload = json.loads(raw_payload)
                elif isinstance(raw_payload, Mapping):
                    payload = dict(raw_payload)
                else:
                    payload = {}
            except Exception as exc:  # noqa: BLE001
                invalid_payload_count += 1
                stale_count += 1
                row["stale_reason"] = "INVALID_JSON"
                row["error"] = f"{type(exc).__name__}:{exc}"
                continue
            if not isinstance(payload, dict) or not payload:
                invalid_payload_count += 1
                stale_count += 1
                row["stale_reason"] = "INVALID_PAYLOAD"
                continue
            for field in ("available_at", "received_at", "generated_at"):
                value = payload.get(field)
                if epoch_ms(value) is not None:
                    row["freshness_reference_field"] = field
                    row["freshness_reference_time"] = value
                    break
            reference_ms = epoch_ms(row["freshness_reference_time"])
            row.update(
                {
                    "available_at": payload.get("available_at"),
                    "received_at": payload.get("received_at"),
                    "generated_at": payload.get("generated_at"),
                    "event_time": payload.get("event_time"),
                    "transaction_time": payload.get("transaction_time"),
                    "update_type": payload.get("update_type"),
                    "sequence_gap": bool(payload.get("sequence_gap") or payload.get("sequence_gap_flag")),
                    "sequence_gap_count": int(payload.get("sequence_gap_count") or 0),
                    "source_latency_ms": payload.get("source_latency_ms"),
                    "update_age_ms": payload.get("update_age_ms"),
                }
            )
            if now_ms is None or reference_ms is None:
                stale_count += 1
                row["stale_reason"] = "AVAILABLE_AT_MISSING"
                continue
            age_ms = max(0.0, float(now_ms - reference_ms))
            row["age_ms"] = age_ms
            if age_ms <= stale_bound:
                fresh_count += 1
                row["fresh"] = True
            else:
                stale_count += 1
                row["stale_reason"] = "BOOK_UPDATE_AGE_TOO_HIGH"

    status.update(
        {
            "fresh_symbol_count": fresh_count,
            "stale_symbol_count": stale_count,
            "missing_symbol_count": missing_count,
            "read_error_count": read_error_count,
            "invalid_payload_count": invalid_payload_count,
            "status": "FRESH" if fresh_count > 0 and stale_count == 0 and missing_count == 0 and read_error_count == 0 else "STALE_OR_MISSING",
        }
    )
    return status


def process_event(
    event: dict[str, Any],
    *,
    books: dict[tuple[str, str], LocalOrderBook],
    replay_store: LocalReplayStore,
    redis_client: Any = None,
    persist_raw_delta: bool = True,
    persist_features: bool = True,
) -> dict[str, Any]:
    exchange = str(event["exchange"])
    symbol = str(event["symbol"]).upper()
    key = (exchange, symbol)
    book = books.setdefault(key, LocalOrderBook(exchange=exchange, symbol=symbol))
    received_at = utc_now_iso()
    update_type = str(event.get("type") or "unknown")
    if update_type == "book_ticker" and (book.bids or book.asks):
        book.apply_top_of_book(
            bids=event.get("bids") or [],
            asks=event.get("asks") or [],
        )
    elif event.get("is_snapshot"):
        snapshot_sequence_id = event.get("sequence_id")
        if exchange == "binance" and update_type == "partial_depth":
            snapshot_sequence_id = None
        book.apply_snapshot(
            bids=event.get("bids") or [],
            asks=event.get("asks") or [],
            sequence_id=snapshot_sequence_id,
        )
    else:
        book.apply_absolute_delta(
            bids=event.get("bids") or [],
            asks=event.get("asks") or [],
            first_sequence_id=event.get("first_sequence_id"),
            final_sequence_id=event.get("final_sequence_id"),
            previous_sequence_id=event.get("previous_sequence_id"),
        )
    source_latency_ms = event.get("source_latency_ms")
    if (
        source_latency_ms is None
        and update_type == "rest_snapshot"
        and event.get("event_time_ms") in (None, "")
        and event.get("transaction_time_ms") in (None, "")
    ):
        source_latency_ms = 0.0
    payloads = book.payloads(
        event_time_ms=event.get("event_time_ms"),
        transaction_time_ms=event.get("transaction_time_ms"),
        received_at=received_at,
        available_at=received_at,
        sequence_id=event.get("sequence_id"),
        previous_sequence_id=event.get("previous_sequence_id"),
        source_latency_ms=source_latency_ms,
        update_type=update_type,
        depth_level=event.get("depth_level"),
        feed_speed_ms=event.get("feed_speed_ms"),
    )
    _safe_redis_set(redis_client, _top_key(exchange, symbol), payloads["top"])
    _safe_redis_set(redis_client, _depth_key(exchange, symbol), payloads["depth"])
    _safe_redis_set(redis_client, _features_key(exchange, symbol), payloads["features"])
    _safe_redis_set(
        redis_client,
        _health_key(exchange),
        {
            "worker_id": STATUS_WORKER_ID,
            "exchange": exchange,
            "last_symbol": symbol,
            "last_event_at": received_at,
            "last_sequence_gap": book.last_sequence_gap,
            "sequence_gap_count": book.sequence_gap_count,
            "live_gate": LIVE_GATE,
            "places_real_order": False,
        },
    )
    writes = []
    if persist_raw_delta and not event.get("is_snapshot"):
        writes.append(
            replay_store.append(
                exchange=exchange,
                symbol=symbol,
                record_type="raw_delta",
                payload=event,
                event_time=payloads["features"].get("event_time"),
            )
        )
    if event.get("is_snapshot"):
        writes.append(
            replay_store.append(
                exchange=exchange,
                symbol=symbol,
                record_type="snapshot",
                payload=payloads["depth"],
                event_time=payloads["features"].get("event_time"),
            )
        )
    if persist_features:
        writes.append(
            replay_store.append(
                exchange=exchange,
                symbol=symbol,
                record_type="features",
                payload=payloads["features"],
                event_time=payloads["features"].get("event_time"),
            )
        )
    return {
        "exchange": exchange,
        "symbol": symbol,
        "update_type": update_type,
        "depth_level": event.get("depth_level"),
        "feed_speed_ms": event.get("feed_speed_ms"),
        "sequence_gap": book.last_sequence_gap,
        "sequence_gap_count": book.sequence_gap_count,
        "redis_keys": [_top_key(exchange, symbol), _depth_key(exchange, symbol), _features_key(exchange, symbol), _health_key(exchange)],
        "replay_writes": [str(write.path) for write in writes],
        "features": payloads["features"],
    }


def process_raw_message(
    raw: Any,
    *,
    parser_name: str,
    books: dict[tuple[str, str], LocalOrderBook],
    replay_store: LocalReplayStore,
    redis_client: Any = None,
) -> dict[str, Any] | None:
    parser = parse_binance_message if parser_name == "binance" else parse_kucoin_message
    event = parser(raw)
    if event is None:
        return None
    return process_event(event, books=books, replay_store=replay_store, redis_client=redis_client)


def _binance_snapshot_from_cache(
    symbol: str,
    *,
    redis_client: Any = None,
) -> dict[str, Any] | None:
    normalized = symbol.upper()
    for key in (
        _depth_key("binance", normalized),
        f"v2:market:orderbook:binance:{normalized}",
        f"v2:market:orderbook:{normalized}",
        _top_key("binance", normalized),
    ):
        payload = _read_json_payload(redis_client, key)
        if not isinstance(payload, Mapping):
            continue
        bids = payload.get("bids") if isinstance(payload.get("bids"), list) else []
        asks = payload.get("asks") if isinstance(payload.get("asks"), list) else []
        if not bids and payload.get("bid") not in (None, ""):
            bids = [[payload.get("bid"), payload.get("bid_qty") or payload.get("bid_quantity") or "0"]]
        if not asks and payload.get("ask") not in (None, ""):
            asks = [[payload.get("ask"), payload.get("ask_qty") or payload.get("ask_quantity") or "0"]]
        if not bids or not asks:
            continue
        return {
            "exchange": "binance",
            "symbol": normalized,
            "type": "websocket_cache_snapshot",
            "bids": bids,
            "asks": asks,
            "sequence_id": payload.get("sequence_id") or payload.get("lastUpdateId") or payload.get("update_id"),
            "event_time_ms": payload.get("event_time_ms") or payload.get("event_time"),
            "transaction_time_ms": payload.get("transaction_time_ms") or payload.get("transaction_time"),
            "is_snapshot": True,
            "source_key": key,
            "raw": {
                "source": payload.get("source") or "binance_public_websocket_orderbook_cache_primary",
                "transport": payload.get("transport") or "websocket_cache_primary",
            },
        }
    return None


def fetch_binance_snapshot(
    symbol: str,
    *,
    limit: int = 1000,
    timeout: float = 8.0,
    redis_client: Any = None,
) -> dict[str, Any]:
    cached = _binance_snapshot_from_cache(symbol, redis_client=redis_client)
    if cached is not None:
        return cached
    try:
        require_binance_rest_fallback(
            endpoint="/fapi/v1/depth",
            fallback_reason="direct_orderbook_websocket_snapshot_cache_missing",
            role="direct_orderbook_snapshot_seed_recovery",
        )
    except RuntimeError as exc:
        message = str(exc).replace(
            "REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
            "BINANCE_REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
            1,
        )
        raise RuntimeError(message) from exc
    url = f"{BINANCE_FAPI_BASE}/fapi/v1/depth?symbol={urllib.parse.quote(symbol.upper())}&limit={int(limit)}"
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "ai-bot-v2-direct-orderbook-recorder"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("bids") or not payload.get("asks"):
        raise RuntimeError(f"binance_snapshot_empty_book:{symbol.upper()}")
    return {
        "exchange": "binance",
        "symbol": symbol.upper(),
        "type": "rest_snapshot",
        "bids": payload.get("bids") or [],
        "asks": payload.get("asks") or [],
        "sequence_id": payload.get("lastUpdateId"),
        "is_snapshot": True,
        "raw": payload,
    }


def fetch_kucoin_snapshot(
    symbol: str,
    *,
    trade_type: str = "FUTURES",
    timeout: float = 8.0,
) -> dict[str, Any]:
    normalized_trade_type = trade_type.upper()
    if normalized_trade_type == "FUTURES":
        provider_symbol = kucoin_v2_symbol_to_futures(symbol)
        url = f"https://api-futures.kucoin.com/api/v1/level2/snapshot?symbol={urllib.parse.quote(provider_symbol)}"
    else:
        provider_symbol = kucoin_v2_symbol_to_spot(symbol)
        url = f"https://api.kucoin.com/api/v3/market/orderbook/level2?symbol={urllib.parse.quote(provider_symbol)}"
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "ai-bot-v2-direct-orderbook-recorder"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    code = str(payload.get("code") or "")
    if code and code != "200000":
        raise RuntimeError(f"kucoin_snapshot_error:{provider_symbol}:{code}")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict) or not data.get("bids") or not data.get("asks"):
        raise RuntimeError(f"kucoin_snapshot_empty_book:{provider_symbol}:{code or 'missing_code'}")
    return {
        "exchange": "kucoin",
        "symbol": symbol.upper(),
        "provider_symbol": provider_symbol,
        "type": "rest_snapshot",
        "bids": data.get("bids") or [],
        "asks": data.get("asks") or [],
        "event_time_ms": data.get("time") or data.get("timestamp"),
        "transaction_time_ms": data.get("time") or data.get("timestamp"),
        "sequence_id": data.get("sequence"),
        "is_snapshot": True,
        "raw": payload,
    }


def _iter_fixture_messages(path: Path) -> list[Any]:
    rows: list[Any] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        rows.append(json.loads(stripped))
    return rows


async def _run_binance_ws(
    *,
    symbols: list[str],
    books: dict[tuple[str, str], LocalOrderBook],
    replay_store: LocalReplayStore,
    redis_client: Any,
    max_messages: int,
    speed: str,
    redis_read_client: Any = None,
    include_book_ticker: bool = False,
    include_diff_depth: bool = False,
    partial_levels: list[int] | tuple[int, ...] = (5, 10, 20),
    message_timeout_seconds: float = 30.0,
    websocket_close_timeout_seconds: float = 1.0,
) -> list[dict[str, Any]]:
    try:
        import websockets  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("websockets package is required for live websocket mode") from exc
    streams = build_binance_stream_names(
        symbols,
        partial_levels=partial_levels,
        speed=speed,
        include_book_ticker=include_book_ticker,
        include_diff_depth=include_diff_depth,
    )
    url = BINANCE_USDM_COMBINED_WS + "/".join(streams)
    processed: list[dict[str, Any]] = []
    seed_limit = _binance_snapshot_seed_limit(
        symbol_count=len(symbols),
        max_messages=max_messages,
        include_diff_depth=include_diff_depth,
    )
    for symbol in symbols[:seed_limit]:
        snapshot_event = _binance_snapshot_from_cache(
            symbol,
            redis_client=redis_read_client if redis_read_client is not None else redis_client,
        )
        if snapshot_event is None:
            continue
        seeded = process_event(
            snapshot_event,
            books=books,
            replay_store=replay_store,
            redis_client=redis_client,
            persist_raw_delta=False,
            persist_features=True,
        )
        seeded["update_type"] = "websocket_cache_snapshot_seed"
        seeded["rest_fallback_used"] = False
        processed.append(seeded)
        if len(processed) >= max_messages:
            return processed
    close_timeout = max(0.1, float(websocket_close_timeout_seconds))
    async with websockets.connect(url, ping_interval=20, close_timeout=close_timeout) as ws:  # type: ignore[attr-defined]
        while len(processed) < max_messages:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(1.0, float(message_timeout_seconds)))
            except asyncio.TimeoutError:
                break
            result = process_raw_message(
                raw,
                parser_name="binance",
                books=books,
                replay_store=replay_store,
                redis_client=redis_client,
            )
            if result is not None:
                processed.append(result)
                if result.get("sequence_gap") is True:
                    try:
                        repair_event = fetch_binance_snapshot(
                            str(result.get("symbol") or ""),
                            limit=1000,
                            redis_client=redis_read_client if redis_read_client is not None else redis_client,
                        )
                    except Exception:
                        continue
                    repair = process_event(
                        repair_event,
                        books=books,
                        replay_store=replay_store,
                        redis_client=redis_client,
                        persist_raw_delta=False,
                        persist_features=True,
                    )
                    repair["update_type"] = "rest_snapshot_gap_repair"
                    processed.append(repair)
    return processed


def _kucoin_bullet_endpoint(*, trade_type: str = "FUTURES") -> str:
    token_url = KUCOIN_BULLET_PUBLIC_BY_TRADE_TYPE.get(trade_type.upper(), KUCOIN_BULLET_PUBLIC_BY_TRADE_TYPE["FUTURES"])
    req = urllib.request.Request(
        token_url,
        data=b"",
        method="POST",
        headers={"User-Agent": "ai-bot-v2-direct-orderbook-recorder", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise RuntimeError("kucoin_bullet_public_missing_data")
    token = data.get("token")
    servers = data.get("instanceServers") or []
    if not token or not servers:
        raise RuntimeError("kucoin_bullet_public_missing_token_or_servers")
    endpoint = servers[0].get("endpoint")
    if not endpoint:
        raise RuntimeError("kucoin_bullet_public_missing_endpoint")
    return f"{endpoint}?token={urllib.parse.quote(str(token))}&connectId=v2-direct-orderbook-recorder"


async def _run_kucoin_ws(
    *,
    symbols: list[str],
    books: dict[tuple[str, str], LocalOrderBook],
    replay_store: LocalReplayStore,
    redis_client: Any,
    max_messages: int,
    depth: str,
    trade_type: str = "FUTURES",
    message_timeout_seconds: float = 30.0,
    websocket_close_timeout_seconds: float = 1.0,
) -> list[dict[str, Any]]:
    try:
        import websockets  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("websockets package is required for live websocket mode") from exc
    url = _kucoin_bullet_endpoint(trade_type=trade_type)
    processed: list[dict[str, Any]] = []
    if depth in {"increment@10ms", "all"}:
        seed_limit = _snapshot_seed_limit(symbol_count=len(symbols), max_messages=max_messages)
        for symbol in symbols[:seed_limit]:
            try:
                snapshot_event = fetch_kucoin_snapshot(symbol, trade_type=trade_type)
            except Exception:
                continue
            seeded = process_event(
                snapshot_event,
                books=books,
                replay_store=replay_store,
                redis_client=redis_client,
                persist_raw_delta=False,
                persist_features=True,
            )
            seeded["update_type"] = "rest_snapshot_seed"
            processed.append(seeded)
            if len(processed) >= max_messages:
                return processed
    close_timeout = max(0.1, float(websocket_close_timeout_seconds))
    async with websockets.connect(url, ping_interval=20, close_timeout=close_timeout) as ws:  # type: ignore[attr-defined]
        for message in build_kucoin_subscription_messages(symbols, trade_type=trade_type, depth=depth):
            await ws.send(json.dumps(message, separators=(",", ":")))
        while len(processed) < max_messages:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(1.0, float(message_timeout_seconds)))
            except asyncio.TimeoutError:
                break
            result = process_raw_message(
                raw,
                parser_name="kucoin",
                books=books,
                replay_store=replay_store,
                redis_client=redis_client,
            )
            if result is not None:
                processed.append(result)
                if result.get("sequence_gap") is True:
                    try:
                        repair_event = fetch_kucoin_snapshot(
                            str(result.get("symbol") or ""),
                            trade_type=trade_type,
                        )
                    except Exception:
                        continue
                    repair = process_event(
                        repair_event,
                        books=books,
                        replay_store=replay_store,
                        redis_client=redis_client,
                        persist_raw_delta=False,
                        persist_features=True,
                    )
                    repair["update_type"] = "rest_snapshot_gap_repair"
                    processed.append(repair)
    return processed


def _snapshot_seed_limit(*, symbol_count: int, max_messages: int) -> int:
    if symbol_count <= 0 or max_messages <= 0:
        return 0
    if max_messages <= 1:
        return 1
    return min(int(symbol_count), max(1, int(max_messages) // 2))


def _binance_snapshot_seed_limit(*, symbol_count: int, max_messages: int, include_diff_depth: bool) -> int:
    if not include_diff_depth:
        return 0
    return _snapshot_seed_limit(symbol_count=symbol_count, max_messages=max_messages)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=STATUS_WORKER_ID)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--exchange", choices=("binance", "kucoin", "both"), default="binance")
    parser.add_argument("--speed", choices=("100ms", "250ms", "500ms"), default="100ms")
    parser.add_argument("--binance-include-book-ticker", action="store_true")
    parser.add_argument("--binance-include-diff-depth", action="store_true")
    parser.add_argument(
        "--binance-book-ticker-only",
        action="store_true",
        help=(
            "Use Binance @bookTicker streams only. Intended for broad current-price "
            "coverage; writes top-of-book cache and does not seed REST snapshots."
        ),
    )
    parser.add_argument("--kucoin-depth", choices=("5", "50", "increment@10ms", "all"), default="all")
    parser.add_argument("--kucoin-trade-type", choices=("SPOT", "FUTURES"), default="FUTURES")
    parser.add_argument("--max-messages", type=int, default=25)
    parser.add_argument("--venue-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--ws-close-timeout-seconds", type=float, default=1.0)
    parser.add_argument("--fixture-jsonl", default=None)
    parser.add_argument("--fixture-parser", choices=("binance", "kucoin"), default="binance")
    parser.add_argument("--write-redis", action="store_true")
    parser.add_argument("--verify-redis-freshness", action="store_true")
    parser.add_argument("--freshness-stale-bound-ms", type=float, default=1500.0)
    parser.add_argument("--write-status", action="store_true")
    parser.add_argument(
        "--seed-symbol-filter-cache-from-rest-fallback",
        action="store_true",
        help=(
            "When Binance WebSocket/cache metadata is missing and "
            "BINANCE_REST_FALLBACK_ALLOWED=true, seed v2:exchange:symbol_filters* "
            "from the public exchangeInfo fallback for later cache-primary reads."
        ),
    )
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--loop-max-runs", type=int, default=0)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--replay-root", default=str(DEFAULT_REPLAY_ROOT))
    return parser.parse_args(argv)


def _resolved_symbols(args: argparse.Namespace) -> list[str]:
    return resolve_symbols(explicit=args.symbols, smoke_test=args.smoke_test, include_baseline=True)


def summarize_processed_feed_coverage(processed: list[dict[str, Any]]) -> dict[str, Any]:
    coverage: dict[str, Any] = {}
    update_type_counts: dict[str, int] = {}
    for row in processed:
        exchange = str(row.get("exchange") or "unknown")
        symbol = str(row.get("symbol") or "unknown").upper()
        update_type = str(row.get("update_type") or "unknown")
        depth_level = row.get("depth_level")
        feed_speed_ms = row.get("feed_speed_ms")
        key = f"{exchange}:{symbol}"
        item = coverage.setdefault(
            key,
            {
                "exchange": exchange,
                "symbol": symbol,
                "update_types": {},
                "depth_levels": [],
                "feed_speeds_ms": [],
                "has_book_ticker": False,
                "has_diff_depth": False,
                "has_partial_depth": False,
                "has_kucoin_increment_best_500": False,
            },
        )
        item["update_types"][update_type] = int(item["update_types"].get(update_type, 0)) + 1
        update_type_counts[f"{exchange}:{update_type}"] = update_type_counts.get(f"{exchange}:{update_type}", 0) + 1
        if depth_level is not None and depth_level not in item["depth_levels"]:
            item["depth_levels"].append(depth_level)
        if feed_speed_ms is not None and feed_speed_ms not in item["feed_speeds_ms"]:
            item["feed_speeds_ms"].append(feed_speed_ms)
        if update_type == "book_ticker":
            item["has_book_ticker"] = True
        if update_type == "diff_depth":
            item["has_diff_depth"] = True
        if update_type == "partial_depth":
            item["has_partial_depth"] = True
        if depth_level == "increment_best_500" or update_type in {"obu_increment", "obu_increment@10ms"}:
            item["has_kucoin_increment_best_500"] = True
    for item in coverage.values():
        item["depth_levels"] = sorted(item["depth_levels"], key=lambda value: str(value))
        item["feed_speeds_ms"] = sorted(item["feed_speeds_ms"])
    return {
        "by_exchange_symbol": dict(sorted(coverage.items())),
        "update_type_counts": dict(sorted(update_type_counts.items())),
    }


def supported_symbols_for_exchange(
    symbols: list[str],
    provider_symbol_support: dict[str, Any] | None,
    exchange: str,
) -> list[str]:
    """Filter symbols that public metadata proves unsupported on one venue."""
    if not isinstance(provider_symbol_support, dict):
        return list(symbols)
    by_exchange = provider_symbol_support.get(exchange)
    if not isinstance(by_exchange, dict):
        return list(symbols)
    filtered: list[str] = []
    for symbol in symbols:
        row = by_exchange.get(str(symbol).upper())
        if isinstance(row, dict) and row.get("orderbook_supported") is False:
            continue
        filtered.append(symbol)
    return filtered


def active_direct_orderbook_symbols(
    symbols: list[str],
    provider_symbol_support: dict[str, Any] | None,
) -> list[str]:
    """Return symbols with at least one supported direct orderbook provider."""
    binance_symbols = set(supported_symbols_for_exchange(symbols, provider_symbol_support, "binance"))
    kucoin_symbols = set(supported_symbols_for_exchange(symbols, provider_symbol_support, "kucoin"))
    return [symbol for symbol in symbols if symbol in binance_symbols or symbol in kucoin_symbols]


def provider_symbol_support_status(provider_symbol_support: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "goal_id": GOAL_ID,
        "generated_at": utc_now_iso(),
        "source": "public_exchange_metadata_only",
        "provider_symbol_support": provider_symbol_support or {},
        "live_gate": LIVE_GATE,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "transfer_or_withdrawal": False,
    }


def _filter_row_from_cached_metadata(payload: Any, symbol: str) -> Mapping[str, Any] | None:
    normalized = str(symbol).upper()
    if not isinstance(payload, Mapping):
        return None
    if isinstance(payload.get(normalized), Mapping):
        return payload[normalized]
    if isinstance(payload.get("filters"), Mapping) and isinstance(payload["filters"].get(normalized), Mapping):
        return payload["filters"][normalized]
    for row in payload.get("symbols") or []:
        if isinstance(row, Mapping) and str(row.get("symbol") or "").upper() == normalized:
            return row
    if str(payload.get("symbol") or "").upper() == normalized:
        return payload
    return None


def _binance_symbol_support_from_cache(
    symbols: list[str],
    *,
    redis_client: Any = None,
) -> tuple[dict[str, Any], set[str]]:
    out: dict[str, Any] = {}
    found: set[str] = set()
    shared_payloads = [
        _read_json_payload(redis_client, "v2:exchange:symbol_filters"),
        _read_json_payload(redis_client, "v2:binance:exchange_info"),
        _read_json_payload(redis_client, "v2:exchange:binance:exchangeInfo"),
    ]
    for symbol in symbols:
        normalized = str(symbol).upper()
        candidates = [
            _read_json_payload(redis_client, f"v2:exchange:symbol_filters:{normalized}"),
            _read_json_payload(redis_client, f"v2:symbol_filters:{normalized}"),
            _read_json_payload(redis_client, f"v2:binance:symbol_filters:{normalized}"),
            *shared_payloads,
        ]
        row: Mapping[str, Any] | None = None
        for payload in candidates:
            row = _filter_row_from_cached_metadata(payload, normalized)
            if row is not None:
                break
        if row is None:
            continue
        status = str(row.get("status") or "TRADING")
        contract_type = str(row.get("contractType") or row.get("contract_type") or "PERPETUAL")
        listed = row.get("listed")
        if listed is None:
            listed = True
        out[normalized] = {
            "provider_symbol": normalized,
            "listed": bool(listed),
            "status": status,
            "contract_type": contract_type,
            "base_asset": row.get("baseAsset") or row.get("base_asset"),
            "quote_asset": row.get("quoteAsset") or row.get("quote_asset"),
            "orderbook_supported": bool(listed and status == "TRADING" and contract_type == "PERPETUAL"),
            "source": "binance_symbol_metadata_cache_primary",
            "transport": "websocket_cache_primary",
        }
        found.add(normalized)
    return out, found


def fetch_provider_symbol_support(
    symbols: list[str],
    *,
    timeout: float = 12.0,
    redis_client: Any = None,
    seed_cache_from_rest_fallback: bool = False,
) -> dict[str, Any]:
    normalized_symbols = sorted({str(symbol).upper() for symbol in symbols if symbol})
    cached_binance, cached_symbols = _binance_symbol_support_from_cache(
        normalized_symbols,
        redis_client=redis_client,
    )
    support: dict[str, Any] = {
        "generated_at": utc_now_iso(),
        "source": "public_exchange_metadata_cache_primary_rest_fallback_only",
        "binance_endpoint": f"{BINANCE_FAPI_BASE}/fapi/v1/exchangeInfo",
        "binance_cache_primary_count": len(cached_symbols),
        "binance_rest_fallback_allowed": binance_rest_fallback_allowed(),
        "kucoin_endpoint": "https://api-futures.kucoin.com/api/v1/contracts/active",
        "binance": dict(cached_binance),
        "kucoin": {},
        "fetch_errors": [],
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "transfer_or_withdrawal": False,
        "symbol_filter_cache_seed": {
            "requested": bool(seed_cache_from_rest_fallback),
            "attempted": False,
            "written_keys": [],
            "write_errors": [],
            "ttl_seconds": SYMBOL_FILTER_CACHE_TTL_SECONDS,
            "transport": "rest_fallback_to_websocket_cache_seed",
        },
    }
    missing_binance_symbols = [symbol for symbol in normalized_symbols if symbol not in cached_symbols]
    try:
        if not missing_binance_symbols:
            raise StopIteration("BINANCE_SYMBOL_METADATA_CACHE_COVERED_ALL_SYMBOLS")
        try:
            require_binance_rest_fallback(
                endpoint="/fapi/v1/exchangeInfo",
                fallback_reason="symbol_filter_cache_missing_for_requested_symbols",
                role="symbol_metadata_cache_seed_recovery",
            )
        except RuntimeError as exc:
            message = str(exc).replace(
                "REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
                "BINANCE_REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
                1,
            )
            raise RuntimeError(message) from exc
        req = urllib.request.Request(
            f"{BINANCE_FAPI_BASE}/fapi/v1/exchangeInfo",
            method="GET",
            headers={"User-Agent": "ai-bot-v2-direct-orderbook-recorder"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        by_symbol = {str(row.get("symbol") or "").upper(): row for row in payload.get("symbols") or []}
        if seed_cache_from_rest_fallback and redis_client is not None and isinstance(payload, dict):
            seed_status = support["symbol_filter_cache_seed"]
            seed_status["attempted"] = True
            for key, cache_payload in (
                ("v2:exchange:binance:exchangeInfo", payload),
                ("v2:exchange:symbol_filters", payload),
            ):
                try:
                    if _safe_symbol_filter_cache_set(redis_client, key, cache_payload):
                        seed_status["written_keys"].append(key)
                except Exception as exc:  # noqa: BLE001
                    seed_status["write_errors"].append(f"{key}:{type(exc).__name__}")
        for symbol in missing_binance_symbols:
            row = by_symbol.get(symbol)
            status = str((row or {}).get("status") or "MISSING")
            contract_type = str((row or {}).get("contractType") or "")
            if seed_cache_from_rest_fallback and redis_client is not None and isinstance(row, dict):
                key = f"v2:exchange:symbol_filters:{symbol}"
                try:
                    if _safe_symbol_filter_cache_set(redis_client, key, row):
                        support["symbol_filter_cache_seed"]["written_keys"].append(key)
                except Exception as exc:  # noqa: BLE001
                    support["symbol_filter_cache_seed"]["write_errors"].append(
                        f"{key}:{type(exc).__name__}"
                    )
            support["binance"][symbol] = {
                "provider_symbol": symbol,
                "listed": row is not None,
                "status": status,
                "contract_type": contract_type,
                "base_asset": (row or {}).get("baseAsset"),
                "quote_asset": (row or {}).get("quoteAsset"),
                "orderbook_supported": bool(row and status == "TRADING" and contract_type == "PERPETUAL"),
                "source": "binance_exchangeInfo_rest_fallback",
                "transport": "rest_fallback",
            }
    except StopIteration:
        pass
    except Exception as exc:  # noqa: BLE001
        support["fetch_errors"].append({"exchange": "binance", "error": f"{type(exc).__name__}:{exc}"})
        for symbol in missing_binance_symbols:
            support["binance"].setdefault(symbol, {
                "provider_symbol": symbol,
                "listed": None,
                "status": "UNKNOWN_FETCH_FAILED",
                "orderbook_supported": None,
                "source": "binance_symbol_metadata_missing_rest_fallback_unavailable",
                "transport": "missing",
            })
    try:
        req = urllib.request.Request(
            "https://api-futures.kucoin.com/api/v1/contracts/active",
            method="GET",
            headers={"User-Agent": "ai-bot-v2-direct-orderbook-recorder"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        contracts = payload.get("data") or []
        by_symbol = {str(row.get("symbol") or "").upper(): row for row in contracts if isinstance(row, dict)}
        for symbol in normalized_symbols:
            provider_symbol = kucoin_v2_symbol_to_futures(symbol)
            row = by_symbol.get(provider_symbol.upper())
            status = str((row or {}).get("status") or "MISSING")
            support["kucoin"][symbol] = {
                "provider_symbol": provider_symbol,
                "listed": row is not None,
                "status": status,
                "contract_type": (row or {}).get("type"),
                "base_currency": (row or {}).get("baseCurrency"),
                "quote_currency": (row or {}).get("quoteCurrency"),
                "orderbook_supported": bool(row and status.lower() == "open"),
            }
    except Exception as exc:  # noqa: BLE001
        support["fetch_errors"].append({"exchange": "kucoin", "error": f"{type(exc).__name__}:{exc}"})
        for symbol in normalized_symbols:
            support["kucoin"][symbol] = {
                "provider_symbol": kucoin_v2_symbol_to_futures(symbol),
                "listed": None,
                "status": "UNKNOWN_FETCH_FAILED",
                "orderbook_supported": None,
            }
    return support


def _run_once(args: argparse.Namespace, *, loop_run_index: int | None = None) -> dict[str, Any]:
    requested_symbols = _resolved_symbols(args)
    redis_read_client = _redis_client(bool(args.write_redis or args.write_status or args.plan_only or args.verify_redis_freshness))
    redis_client = redis_read_client if args.write_redis else None
    if args.write_status or args.plan_only:
        try:
            provider_symbol_support = fetch_provider_symbol_support(
                requested_symbols,
                redis_client=redis_read_client,
                seed_cache_from_rest_fallback=bool(
                    args.seed_symbol_filter_cache_from_rest_fallback
                ),
            )
        except TypeError:
            provider_symbol_support = fetch_provider_symbol_support(requested_symbols)
    else:
        provider_symbol_support = {}
    binance_symbols = supported_symbols_for_exchange(requested_symbols, provider_symbol_support, "binance")
    kucoin_symbols = supported_symbols_for_exchange(requested_symbols, provider_symbol_support, "kucoin")
    symbols = active_direct_orderbook_symbols(requested_symbols, provider_symbol_support)
    exchange_symbols = {
        "binance": binance_symbols if args.exchange in {"binance", "both"} else [],
        "kucoin": kucoin_symbols if args.exchange in {"kucoin", "both"} else [],
    }
    replay_store = LocalReplayStore(Path(args.replay_root))
    books: dict[tuple[str, str], LocalOrderBook] = {}
    processed: list[dict[str, Any]] = []
    run_errors: list[dict[str, str]] = []
    started_at = utc_now_iso()
    max_messages = max(1, int(args.max_messages))
    binance_book_ticker_only = bool(args.binance_book_ticker_only)
    binance_include_book_ticker = bool(args.binance_include_book_ticker or binance_book_ticker_only)
    binance_partial_levels: tuple[int, ...] = () if binance_book_ticker_only else (5, 10, 20)
    if args.fixture_jsonl:
        for raw in _iter_fixture_messages(Path(args.fixture_jsonl)):
            result = process_raw_message(
                raw,
                parser_name=args.fixture_parser,
                books=books,
                replay_store=replay_store,
                redis_client=redis_client,
            )
            if result is not None:
                processed.append(result)
    elif not args.plan_only:
        if args.exchange in {"binance", "both"} and binance_symbols:
            binance_budget = max_messages if args.exchange == "binance" else max(1, max_messages // 2)
            try:
                processed.extend(
                    asyncio.run(
                        _run_binance_ws(
                            symbols=binance_symbols,
                            books=books,
                            replay_store=replay_store,
                            redis_client=redis_client,
                            max_messages=binance_budget,
                            redis_read_client=redis_read_client,
                            speed=args.speed,
                            include_book_ticker=binance_include_book_ticker,
                            include_diff_depth=bool(args.binance_include_diff_depth),
                            partial_levels=binance_partial_levels,
                            message_timeout_seconds=float(args.venue_timeout_seconds),
                            websocket_close_timeout_seconds=float(args.ws_close_timeout_seconds),
                        )
                    )
                )
            except Exception as exc:  # noqa: BLE001
                run_errors.append({"exchange": "binance", "error": f"{type(exc).__name__}:{exc}"})
        elif args.exchange in {"binance", "both"}:
            run_errors.append({"exchange": "binance", "error": "no_supported_orderbook_symbols"})
        if args.exchange in {"kucoin", "both"} and kucoin_symbols and len(processed) < max_messages:
            try:
                processed.extend(
                    asyncio.run(
                        _run_kucoin_ws(
                            symbols=kucoin_symbols,
                            books=books,
                            replay_store=replay_store,
                            redis_client=redis_client,
                            max_messages=max(1, max_messages - len(processed)),
                            depth=args.kucoin_depth,
                            trade_type=args.kucoin_trade_type,
                            message_timeout_seconds=float(args.venue_timeout_seconds),
                            websocket_close_timeout_seconds=float(args.ws_close_timeout_seconds),
                        )
                    )
                )
            except Exception as exc:  # noqa: BLE001
                run_errors.append({"exchange": "kucoin", "error": f"{type(exc).__name__}:{exc}"})
        elif args.exchange in {"kucoin", "both"} and len(processed) < max_messages:
            run_errors.append({"exchange": "kucoin", "error": "no_supported_orderbook_symbols"})
    processed_exchanges = sorted({str(row.get("exchange")) for row in processed if row.get("exchange")})
    observed_feed_coverage = summarize_processed_feed_coverage(processed)
    run_status = {
        "worker_id": STATUS_WORKER_ID,
        "goal_id": GOAL_ID,
        "started_at": started_at,
        "finished_at": utc_now_iso(),
        "loop": bool(args.loop),
        "loop_run_index": loop_run_index,
        "interval_seconds": float(args.interval_seconds),
        "loop_max_runs": int(args.loop_max_runs),
        "ws_close_timeout_seconds": float(args.ws_close_timeout_seconds),
        "plan_only": bool(args.plan_only),
        "fixture_mode": bool(args.fixture_jsonl),
        "requested_symbols": requested_symbols,
        "requested_symbol_count": len(requested_symbols),
        "symbols": symbols,
        "symbol_count": len(symbols),
        "provider_filtered_symbols": sorted(set(requested_symbols) - set(symbols)),
        "exchange_symbols": exchange_symbols,
        "exchange": args.exchange,
        "binance_streams": build_binance_stream_names(
            binance_symbols[: min(5, len(binance_symbols))],
            partial_levels=binance_partial_levels,
            speed=args.speed,
            include_book_ticker=binance_include_book_ticker,
            include_diff_depth=bool(args.binance_include_diff_depth),
        ),
        "binance_include_book_ticker": binance_include_book_ticker,
        "binance_book_ticker_only": binance_book_ticker_only,
        "binance_partial_depth_levels": list(binance_partial_levels),
        "binance_include_diff_depth": bool(args.binance_include_diff_depth),
        "kucoin_trade_type": args.kucoin_trade_type,
        "kucoin_subscriptions_sample": build_kucoin_subscription_messages(
            kucoin_symbols[: min(5, len(kucoin_symbols))],
            trade_type=args.kucoin_trade_type,
            depth=args.kucoin_depth,
        ),
        "processed_messages": len(processed),
        "processed_exchanges": processed_exchanges,
        "observed_feed_coverage": observed_feed_coverage,
        "provider_symbol_support": provider_symbol_support,
        "run_errors": run_errors,
        "direct_binance_active": "binance" in processed_exchanges,
        "direct_kucoin_active": "kucoin" in processed_exchanges,
        "direct_binance_kucoin_active": {"binance", "kucoin"}.issubset(processed_exchanges),
        "redis_enabled": bool(args.write_redis),
        "redis_available": redis_client is not None,
        "redis_freshness_check": _redis_feature_freshness_status(
            redis_read_client,
            exchange_symbols=exchange_symbols,
            stale_bound_ms=float(args.freshness_stale_bound_ms),
        )
        if args.verify_redis_freshness
        else {
            "enabled": False,
            "reason": "verify_redis_freshness_not_requested",
            "stale_bound_ms": float(args.freshness_stale_bound_ms),
        },
        "redis_key_prefix": NEW_REDIS_PREFIX,
        "old_redis_writes": False,
        "places_real_order": False,
        "test_orders": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "transfer_or_withdrawal": False,
        "live_gate": LIVE_GATE,
        "sample_processed": processed[:5],
    }
    if args.write_status or args.plan_only or args.fixture_jsonl:
        write_goal_statuses(
            replay_store=replay_store,
            recorder_active=bool(processed),
            run_status=run_status,
            provider_symbol_support=provider_symbol_support,
        )
    return run_status


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.loop:
        print(json.dumps(_run_once(args), indent=2, sort_keys=True))
        return 0
    run_index = 0
    max_runs = int(args.loop_max_runs)
    interval_seconds = max(0.0, float(args.interval_seconds))
    while max_runs <= 0 or run_index < max_runs:
        run_index += 1
        payload = _run_once(args, loop_run_index=run_index)
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)
        if max_runs > 0 and run_index >= max_runs:
            break
        time.sleep(interval_seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
