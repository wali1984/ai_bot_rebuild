"""Publish read-only realtime chart payloads from existing V2 Redis data.

This publisher reads existing V2 Redis snapshots and writes static website
JSON files. CoinAPI WSDS microstructure is preferred. When a symbol has no
WSDS snapshot, the publisher can use the existing read-only V2 market price
snapshot as a labelled fallback so all-symbol website panels stay populated
without fabricating unavailable microstructure fields.

It does not call Binance, KuCoin, CoinAPI, or any exchange API. It does not
write Redis and cannot enable live/canary trading.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


WORKER_ID = "v2_market_chart_payload_publisher"
SMOKE_FALLBACK_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
DEFAULT_TIMEFRAME = "1m"
DEFAULT_OUTPUT_DIR = Path("v2/frontend/public/operator_runtime/v2_market_chart/latest")
V2_WSDS_KEY_TEMPLATE = "v2:market:coinapi:wsds:{symbol}"
V2_PRICE_KEY_TEMPLATE = "v2:market:prices:{symbol}"
REPO_ROOT = Path(__file__).resolve().parents[4]
V2_ROOT = REPO_ROOT / "v2"
DEFAULT_SYMBOL_UNIVERSE_PATHS = (
    Path("v2/frontend/public/operator_runtime/symbol_universe/latest/symbol_universe_status.json"),
    V2_ROOT / "frontend" / "public" / "operator_runtime" / "symbol_universe" / "latest" / "symbol_universe_status.json",
    Path("v2/frontend/public/operator_runtime/v2_kucoin_ingestor/latest/v2_kucoin_ingestor_status.json"),
    V2_ROOT / "frontend" / "public" / "operator_runtime" / "v2_kucoin_ingestor" / "latest" / "v2_kucoin_ingestor_status.json",
)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _est_iso() -> str:
    return datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")


def _connect_redis() -> Any | None:
    try:
        import redis  # type: ignore

        url = os.getenv("V2_REDIS_URL") or os.getenv("REDIS_URL") or "redis://127.0.0.1:6379/0"
        client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=1.0)
        client.ping()
        return client
    except Exception:
        return None


def _json_loads(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        value = json.loads(raw)
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _to_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and abs(out) != float("inf") else None


def _to_int(value: Any) -> int | None:
    try:
        out = int(float(value))
    except (TypeError, ValueError):
        return None
    return out


def _timestamp_ms_from_iso(value: Any) -> int | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    return int(parsed.timestamp() * 1000)


def _read_existing_samples(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    samples = payload.get("samples") if isinstance(payload, dict) else None
    if not isinstance(samples, list):
        return []
    return [item for item in samples if isinstance(item, dict)]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _as_symbol_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    out: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        symbol = item.strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        out.append(symbol)
    return tuple(out)


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _resolve_universe_symbols() -> tuple[str, ...]:
    for path in DEFAULT_SYMBOL_UNIVERSE_PATHS:
        payload = _read_json_file(path)
        if not payload:
            continue
        for field in (
            "live_data_symbols",
            "paper_symbols",
            "discovered_symbols",
            "dynamic_discovered_symbols",
            "training_symbols",
            "binance_usdm_confirmed_symbols",
            "symbols_v2",
        ):
            symbols = _as_symbol_list(payload.get(field))
            if len(symbols) > len(SMOKE_FALLBACK_SYMBOLS):
                return symbols
    return SMOKE_FALLBACK_SYMBOLS


def _sample_from_snapshot(symbol: str, snapshot: dict[str, Any], received_ts_ms: int) -> dict[str, Any] | None:
    mid = _to_float(snapshot.get("mid_px") or snapshot.get("microprice"))
    bid = _to_float(snapshot.get("best_bid_px"))
    ask = _to_float(snapshot.get("best_ask_px"))
    if mid is None and bid is not None and ask is not None:
      mid = (bid + ask) / 2.0
    if mid is None or mid <= 0:
        return None
    event_ts_ms = _to_int(snapshot.get("updated_ts_ms")) or received_ts_ms
    return {
        "symbol": symbol,
        "source": "coinapi_wsds",
        "source_type": "EXISTING_WEBSOCKET_RUNTIME_FEED",
        "event_ts_ms": event_ts_ms,
        "received_ts_ms": received_ts_ms,
        "timestamp_utc": datetime.fromtimestamp(received_ts_ms / 1000.0, tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "mid_px": mid,
        "best_bid_px": bid,
        "best_ask_px": ask,
        "spread": _to_float(snapshot.get("spread")),
        "imbalance_5": _to_float(snapshot.get("imbalance_5")),
        "book_bid_sum_5": _to_float(snapshot.get("book_bid_sum_5")),
        "book_ask_sum_5": _to_float(snapshot.get("book_ask_sum_5")),
    }


def _sample_from_price_snapshot(symbol: str, snapshot: dict[str, Any], received_ts_ms: int) -> dict[str, Any] | None:
    ticker = snapshot.get("ticker_24hr") if isinstance(snapshot.get("ticker_24hr"), dict) else {}
    funding = snapshot.get("funding") if isinstance(snapshot.get("funding"), dict) else {}
    open_interest = snapshot.get("open_interest") if isinstance(snapshot.get("open_interest"), dict) else {}
    mid = (
        _to_float(ticker.get("lastPrice"))
        or _to_float(funding.get("markPrice"))
        or _to_float(ticker.get("weightedAvgPrice"))
    )
    if mid is None or mid <= 0:
        return None
    event_candidates = [
        _to_int(ticker.get("closeTime")),
        _to_int(funding.get("time")),
        _to_int(open_interest.get("time")),
        _timestamp_ms_from_iso(snapshot.get("fetched_utc")),
        _timestamp_ms_from_iso(snapshot.get("generated_utc")),
    ]
    event_ts_ms = max((value for value in event_candidates if value is not None), default=received_ts_ms)
    return {
        "symbol": symbol,
        "source": str(snapshot.get("source") or "v2_market_prices"),
        "source_type": "EXISTING_V2_MARKET_PRICE_FEED",
        "event_ts_ms": event_ts_ms,
        "received_ts_ms": received_ts_ms,
        "timestamp_utc": datetime.fromtimestamp(received_ts_ms / 1000.0, tz=timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "mid_px": mid,
        "best_bid_px": None,
        "best_ask_px": None,
        "spread": None,
        "imbalance_5": None,
        "book_bid_sum_5": None,
        "book_ask_sum_5": None,
        "ticker_last_price": _to_float(ticker.get("lastPrice")),
        "mark_price": _to_float(funding.get("markPrice")),
        "index_price": _to_float(funding.get("indexPrice")),
        "open_interest": _to_float(open_interest.get("openInterest")),
        "price_change_percent_24h": _to_float(ticker.get("priceChangePercent")),
    }


def _build_payload(
    *,
    symbol: str,
    timeframe: str,
    redis_client: Any | None,
    existing_samples: list[dict[str, Any]],
    max_points: int,
    require_wsds: bool,
) -> dict[str, Any]:
    generated_utc = _utc_iso()
    generated_est = _est_iso()
    received_ts_ms = int(time.time() * 1000)
    wsds_key = V2_WSDS_KEY_TEMPLATE.format(symbol=symbol)
    price_key = V2_PRICE_KEY_TEMPLATE.format(symbol=symbol)
    wsds_snapshot = None
    price_snapshot = None
    redis_read_ok = False
    if redis_client is not None:
        try:
            wsds_snapshot = _json_loads(redis_client.get(wsds_key))
            redis_read_ok = True
        except Exception:
            wsds_snapshot = None
        try:
            price_snapshot = _json_loads(redis_client.get(price_key))
            redis_read_ok = True
        except Exception:
            price_snapshot = None
    latest_sample = _sample_from_snapshot(symbol, wsds_snapshot or {}, received_ts_ms) if wsds_snapshot else None
    source_key = wsds_key
    chart_source = "coinapi_wsds"
    source_type = "EXISTING_WEBSOCKET_RUNTIME_FEED"
    if latest_sample is None and price_snapshot and not require_wsds:
        latest_sample = _sample_from_price_snapshot(symbol, price_snapshot, received_ts_ms)
        if latest_sample is not None:
            source_key = price_key
            chart_source = "v2_market_prices"
            source_type = "EXISTING_V2_MARKET_PRICE_FEED"
    samples = [
        sample
        for sample in existing_samples
        if not require_wsds or sample.get("source_type") == "EXISTING_WEBSOCKET_RUNTIME_FEED"
    ]
    if latest_sample is not None:
        samples.append(latest_sample)
    samples = samples[-max(1, int(max_points)) :]
    latest = samples[-1] if samples else None
    source_event_age_seconds = None
    if latest is not None:
        source_event_age_seconds = max(
            0, int((received_ts_ms - int(latest.get("event_ts_ms") or received_ts_ms)) / 1000)
        )
    source_stale_after_seconds = 90 if source_type == "EXISTING_WEBSOCKET_RUNTIME_FEED" else 900
    if not redis_read_ok:
        status = "REDIS_READ_UNAVAILABLE"
        blocker = "Redis read unavailable for V2 chart payload."
    elif latest is None:
        status = "SOURCE_SNAPSHOT_MISSING"
        blocker = (
            f"{wsds_key} missing or did not contain a positive CoinAPI WSDS mid price."
            if require_wsds
            else f"{wsds_key} and {price_key} missing or did not contain a positive price."
        )
    elif source_event_age_seconds is not None and source_event_age_seconds > source_stale_after_seconds:
        status = "STALE_SOURCE_EVENT"
        blocker = f"{source_key} source event older than {source_stale_after_seconds} seconds."
    else:
        status = "CURRENT"
        blocker = None
    return {
        "schema_version": "v2_realtime_market_chart_payload_v1",
        "worker_id": WORKER_ID,
        "status": status,
        "blocker": blocker,
        "generated_utc": generated_utc,
        "generated_est": generated_est,
        "symbol": symbol,
        "timeframe": timeframe,
        "chart_source": chart_source,
        "source_type": source_type,
        "source_redis_key": source_key,
        "preferred_source_redis_key": wsds_key,
        "fallback_source_redis_key": price_key,
        "fallback_allowed": not require_wsds,
        "source_event_age_seconds": source_event_age_seconds,
        "source_stale_after_seconds": source_stale_after_seconds,
        "sample_count": len(samples),
        "latest": latest,
        "samples": samples,
        "redis_read_ok": redis_read_ok,
        "frontend_poll_interval_ms": 2_000,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "execution_live_symbols": [],
        "safety": {
            "calls_exchange_api": False,
            "calls_binance_rest": False,
            "calls_kucoin_rest": False,
            "calls_coinapi_api": False,
            "writes_redis": False,
            "writes_old_redis": False,
            "writes_exchange_orders": False,
            "calls_test_order_endpoint": False,
            "leverage_changed": False,
            "margin_mode_changed": False,
            "approves_live": False,
            "approves_canary": False,
            "redis_trim_performed": False,
        },
    }


def publish(
    *,
    symbols: tuple[str, ...],
    timeframe: str,
    output_dir: Path,
    max_points: int,
    sample_count: int,
    sample_interval_seconds: float,
    require_wsds: bool,
) -> dict[str, Any]:
    redis_client = _connect_redis()
    latest_payloads: dict[str, dict[str, Any]] = {}
    samples_by_symbol = {
        symbol: _read_existing_samples(output_dir / f"{symbol}_{timeframe}_chart.json")
        for symbol in symbols
    }
    for index in range(max(1, int(sample_count))):
        for symbol in symbols:
            payload = _build_payload(
                symbol=symbol,
                timeframe=timeframe,
                redis_client=redis_client,
                existing_samples=samples_by_symbol[symbol],
                max_points=max_points,
                require_wsds=require_wsds,
            )
            samples_by_symbol[symbol] = payload["samples"]
            latest_payloads[symbol] = payload
        if index < sample_count - 1 and sample_interval_seconds > 0:
            time.sleep(sample_interval_seconds)

    for symbol, payload in latest_payloads.items():
        _write_json(output_dir / f"{symbol}_{timeframe}_chart.json", payload)

    status_counts: dict[str, int] = {}
    for payload in latest_payloads.values():
        status_counts[str(payload.get("status") or "UNKNOWN")] = (
            status_counts.get(str(payload.get("status") or "UNKNOWN"), 0) + 1
        )
    current_wsds_count = sum(
        1
        for payload in latest_payloads.values()
        if payload.get("status") == "CURRENT"
        and payload.get("source_type") == "EXISTING_WEBSOCKET_RUNTIME_FEED"
    )
    non_current_symbols = [
        symbol
        for symbol, payload in latest_payloads.items()
        if payload.get("status") != "CURRENT"
    ]
    summary = {
        "schema_version": "v2_market_chart_payload_publisher_status_v1",
        "worker_id": WORKER_ID,
        "generated_utc": _utc_iso(),
        "generated_est": _est_iso(),
        "status": "V2_MARKET_CHART_PAYLOADS_READY"
        if latest_payloads and all(item["status"] == "CURRENT" for item in latest_payloads.values())
        else "V2_MARKET_CHART_PAYLOADS_PARTIAL",
        "symbols": list(symbols),
        "symbols_count": len(symbols),
        "timeframe": timeframe,
        "require_wsds": require_wsds,
        "status_counts": status_counts,
        "current_wsds_count": current_wsds_count,
        "non_current_symbols": non_current_symbols,
        "payloads": {
            symbol: {
                "path": f"/operator_runtime/v2_market_chart/latest/{symbol}_{timeframe}_chart.json",
                "status": payload["status"],
                "sample_count": payload["sample_count"],
                "source_redis_key": payload["source_redis_key"],
                "source_type": payload["source_type"],
                "latest_mid_px": (payload.get("latest") or {}).get("mid_px"),
                "source_event_age_seconds": payload.get("source_event_age_seconds"),
            }
            for symbol, payload in latest_payloads.items()
        },
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "execution_live_symbols": [],
        "safety": {
            "calls_exchange_api": False,
            "writes_redis": False,
            "writes_old_redis": False,
            "writes_exchange_orders": False,
            "approves_live": False,
            "approves_canary": False,
            "redis_trim_performed": False,
        },
    }
    _write_json(output_dir / "operator_dashboard_payload.json", summary)
    return summary


def _parse_symbols(raw: str) -> tuple[str, ...]:
    if raw.strip().lower() in {"", "auto", "all", "universe"}:
        return _resolve_universe_symbols()
    symbols = tuple(part.strip().upper() for part in raw.split(",") if part.strip())
    return symbols or _resolve_universe_symbols()


def _bounded_loop_log_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Return bounded loop telemetry while the full dashboard stays on disk."""

    non_current = summary.get("non_current_symbols")
    non_current_symbols = (
        [symbol for symbol in non_current if isinstance(symbol, str)]
        if isinstance(non_current, list)
        else []
    )
    sample_limit = 16
    return {
        "schema_version": "v2_market_chart_payload_publisher_loop_log_v1",
        "worker_id": WORKER_ID,
        "generated_utc": summary.get("generated_utc"),
        "generated_est": summary.get("generated_est"),
        "status": summary.get("status"),
        "symbols_count": summary.get("symbols_count"),
        "timeframe": summary.get("timeframe"),
        "require_wsds": summary.get("require_wsds"),
        "status_counts": summary.get("status_counts"),
        "current_wsds_count": summary.get("current_wsds_count"),
        "non_current_symbol_count": len(non_current_symbols),
        "non_current_symbols_sample": non_current_symbols[:sample_limit],
        "non_current_symbols_omitted_count": max(
            0,
            len(non_current_symbols) - sample_limit,
        ),
        "full_status_path": (
            "/operator_runtime/v2_market_chart/latest/operator_dashboard_payload.json"
        ),
        "full_payloads_omitted_from_loop_log": True,
        "live_gate": summary.get("live_gate"),
        "writes_exchange_orders": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="auto", help="Comma-separated symbols, or auto/all/universe for the full V2 symbol universe.")
    parser.add_argument("--timeframe", default=DEFAULT_TIMEFRAME)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-points", type=int, default=240)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--sample-interval-seconds", type=float, default=0.0)
    parser.add_argument("--require-wsds", action="store_true", help="Do not fall back to the V2 market price feed when CoinAPI WSDS is unavailable.")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=2.0)
    args = parser.parse_args(argv)
    symbols = _parse_symbols(args.symbols)
    output_dir = Path(args.output_dir)
    if args.loop:
        while True:
            summary = publish(
                symbols=symbols,
                timeframe=str(args.timeframe),
                output_dir=output_dir,
                max_points=int(args.max_points),
                sample_count=max(1, int(args.samples)),
                sample_interval_seconds=float(args.sample_interval_seconds),
                require_wsds=bool(args.require_wsds),
            )
            print(json.dumps(_bounded_loop_log_summary(summary), sort_keys=True), flush=True)
            time.sleep(max(0.5, float(args.interval_seconds)))
    else:
        summary = publish(
            symbols=symbols,
            timeframe=str(args.timeframe),
            output_dir=output_dir,
            max_points=int(args.max_points),
            sample_count=int(args.samples),
            sample_interval_seconds=float(args.sample_interval_seconds),
            require_wsds=bool(args.require_wsds),
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
