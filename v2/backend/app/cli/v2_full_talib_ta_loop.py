"""Publish full TA-Lib compatibility payloads from live V2 OHLCV.

Writes only V2 Redis keys:

* ``v2:features:ta:{symbol}:{timeframe}``
* ``v2:features:ta_full:{symbol}:{timeframe}``
* ``v2:technical_analysis:{symbol}:{timeframe}``
* ``v2:features:ta:heartbeat``

The worker restores the broad legacy TA surface for trainer/readiness parity
without touching legacy Redis keys or exchange mutation paths.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.full_talib_ta.service import (
    FULL_TALIB_TA_SCHEMA_VERSION,
    build_full_talib_ta_payload,
    filter_closed_ohlcv_rows,
)
from v2.backend.app.services.v2_symbol_runtime_universe import (
    is_valid_runtime_symbol,
    resolve_symbols_with_provenance,
)


WORKER_ID = "v2_full_talib_ta_loop"
V2_REDIS_PREFIX = "v2:"
DEFAULT_TIMEFRAMES = ("1m", "5m", "15m", "1h")
DEFAULT_TTL_SECONDS = 900
DEFAULT_INTERVAL_SECONDS = 60
REPO_ROOT = Path(__file__).resolve().parents[4]
PUBLIC_STATUS_PATH = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime/v2_full_talib_ta/latest/v2_full_talib_ta_status.json"
)
LOCAL_STATUS_PATH = REPO_ROOT / "v2/runtime/v2_full_talib_ta/latest/v2_full_talib_ta_status.json"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis():
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


def _safe_set_json(redis_client: Any, key: str, payload: dict[str, Any], ttl: int) -> bool:
    if redis_client is None or not key.startswith(V2_REDIS_PREFIX):
        return False
    try:
        redis_client.set(key, json.dumps(payload, sort_keys=True), ex=int(ttl))
        return True
    except Exception:
        return False


def _read_json(redis_client: Any, key: str) -> Any:
    if redis_client is None or not key.startswith(V2_REDIS_PREFIX):
        return None
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _extract_ohlcv_rows(payload: Any) -> list[Any] | None:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return None
    for field in ("candles", "ohlcv", "ohlcv_list", "rows", "data"):
        rows = payload.get(field)
        if isinstance(rows, list):
            return rows
    latest = payload.get("latest")
    if isinstance(latest, dict):
        return [latest]
    return None


def _copy_compact_ta_payload(
    *,
    symbol: str,
    timeframe: str,
    source_key: str,
    source_payload: dict[str, Any],
) -> dict[str, Any] | None:
    indicators: dict[str, float] = {}
    raw_indicators = source_payload.get("indicators")
    raw_features = source_payload.get("features")
    if isinstance(raw_indicators, dict):
        for name, value in raw_indicators.items():
            try:
                indicators[str(name)] = float(value)
            except (TypeError, ValueError):
                continue
    if isinstance(raw_features, dict):
        aliases = {
            "rsi_14": ("rsi_14", "ta_RSI_14"),
            "macd": ("macd", "ta_MACD_12_26_9_macd"),
            "macd_signal": ("macd_signal", "ta_MACD_12_26_9_signal"),
            "macd_hist": ("macd_hist", "ta_MACD_12_26_9_hist", "ta_MACDhist_12_26_9"),
            "atr_14": ("atr_14", "ta_ATR_14"),
            "ema_12": ("ema_12", "ta_EMA_12"),
            "ema_26": ("ema_26", "ta_EMA_26"),
            "sma_20": ("sma_20", "ta_SMA_20"),
            "bb_width_pct": ("bb_width_pct", "ta_BB_width_pct"),
        }
        for src_name, names in aliases.items():
            if src_name not in raw_features:
                continue
            try:
                value = float(raw_features[src_name])
            except (TypeError, ValueError):
                continue
            for out_name in names:
                indicators[out_name] = value
    if not indicators:
        return None
    return {
        "schema_version": "v2_full_talib_ta_compact_fallback_v1",
        "source_label": "V2_COMPACT_TA_FALLBACK_WHILE_FULL_OHLCV_MISSING",
        "symbol": symbol,
        "timeframe": timeframe,
        "generated_utc": _utc_iso(),
        "source_ohlcv_key": f"v2:market:ohlcv:binance:{symbol}:{timeframe}",
        "source_compact_key": source_key,
        "library_used": source_payload.get("library_used") or "v2_compact_feature_pipeline",
        "talib_function_count": 0,
        "computed_function_count": 0,
        "computed_functions": [],
        "skipped_function_count": 1,
        "skipped_functions": {
            "full_talib": "source_ohlcv_missing_or_unusable_for_full_talib"
        },
        "candle_count": source_payload.get("candle_count"),
        "last_candle_ts_ms": source_payload.get("last_candle_ts_ms"),
        "field_count": len(indicators),
        "indicator_count": len(indicators),
        "indicators": dict(sorted(indicators.items())),
        "families_present": sorted({name.split("_", 2)[1] if name.startswith("ta_") and "_" in name[3:] else name.split("_", 1)[0].upper() for name in indicators}),
        "classification": "V2_FULL_TALIB_TA_BLOCKED_COMPACT_FALLBACK_FRESH",
        "trainer_consumable": True,
        "legacy_ta_field_parity_target": "about_160_fields_from_LEGACY_SYSTEM_FULL_AUDIT",
        "legacy_redis_key_equivalent": f"ta:{symbol}:{timeframe}",
        "v2_only": True,
        "writes_legacy_redis": False,
        "exchange_action_taken": False,
        "places_real_order": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "no_zero_fill": True,
    }


def _fallback_ta_payload(redis_client: Any, symbol: str, timeframe: str) -> dict[str, Any] | None:
    for key in (
        f"v2:technical_analysis:{symbol}:{timeframe}",
        f"v2:features:latest:{symbol}:{timeframe}",
        f"v2:features:ta:{symbol}:{timeframe}",
    ):
        payload = _read_json(redis_client, key)
        if isinstance(payload, dict):
            compact = _copy_compact_ta_payload(
                symbol=symbol,
                timeframe=timeframe,
                source_key=key,
                source_payload=payload,
            )
            if compact is not None:
                return compact
    return None


def _parse_csv(raw: str | None, *, upper: bool = True) -> tuple[str, ...]:
    if not raw:
        return ()
    values: list[str] = []
    for part in raw.split(","):
        value = part.strip()
        if not value:
            continue
        values.append(value.upper() if upper else value)
    return tuple(values)


def _discover_ohlcv_keys(redis_client: Any) -> dict[str, set[str]]:
    discovered: dict[str, set[str]] = {}
    if redis_client is None:
        return discovered
    try:
        keys = list(redis_client.scan_iter(match="v2:market:ohlcv:binance:*", count=500))
    except Exception:
        return discovered
    for key in keys:
        if not isinstance(key, str):
            continue
        parts = key.split(":")
        if len(parts) != 6:
            continue
        _, market, ohlcv, exchange, symbol, timeframe = parts
        if market != "market" or ohlcv != "ohlcv" or exchange != "binance":
            continue
        if symbol == "heartbeat" or not is_valid_runtime_symbol(symbol):
            continue
        discovered.setdefault(symbol.upper(), set()).add(timeframe)
    return discovered


def _write_status(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def run_once(
    *,
    symbols_arg: str | None = None,
    timeframes_arg: str | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    smoke_test: bool = False,
    redis_client: Any = None,
) -> dict[str, Any]:
    started_at = _utc_iso()
    redis_client = redis_client if redis_client is not None else _connect_redis()
    symbol_scope = resolve_symbols_with_provenance(
        explicit=_parse_csv(symbols_arg, upper=True) or None,
        smoke_test=smoke_test,
        include_baseline=True,
    )
    requested_symbols = [str(s).upper() for s in symbol_scope.get("symbols", [])]
    discovered = _discover_ohlcv_keys(redis_client)
    all_symbols: list[str] = []
    seen: set[str] = set()
    for symbol in list(requested_symbols) + sorted(discovered):
        symbol = str(symbol or "").upper()
        if symbol and is_valid_runtime_symbol(symbol) and symbol not in seen:
            seen.add(symbol)
            all_symbols.append(symbol)

    requested_timeframes = _parse_csv(timeframes_arg, upper=False)
    if requested_timeframes:
        all_timeframes = list(requested_timeframes)
    else:
        discovered_tfs = sorted({tf for values in discovered.values() for tf in values})
        all_timeframes = list(dict.fromkeys(list(DEFAULT_TIMEFRAMES) + discovered_tfs))

    key_results: list[dict[str, Any]] = []
    keys_written: list[str] = []
    missing_ohlcv_keys: list[str] = []
    classifications: dict[str, int] = {}
    max_indicator_count = 0
    min_indicator_count: int | None = None

    for symbol in all_symbols:
        for timeframe in all_timeframes:
            source_key = f"v2:market:ohlcv:binance:{symbol}:{timeframe}"
            source_payload = _read_json(redis_client, source_key)
            rows = _extract_ohlcv_rows(source_payload)
            if rows is None:
                missing_ohlcv_keys.append(source_key)
                payload = _fallback_ta_payload(redis_client, symbol, timeframe)
                if payload is None:
                    continue
            else:
                result = build_full_talib_ta_payload(
                    symbol=symbol,
                    timeframe=timeframe,
                    candles=rows,
                    source_ohlcv_key=source_key,
                )
                payload = result.to_payload(source_ohlcv_key=source_key)
                # Confirmed-closed-candle variant: the live payload above
                # includes the in-progress candle, which timestamp-integrity
                # gates (ENTRY_FEATURE_CANDLE_NOT_CONFIRMED_CLOSED) must
                # reject. Consumers that need repaint-free entry features read
                # ta_closed instead; candle_closed_confirmed is only ever
                # stamped here, from raw close-boundary proof.
                closed_rows, closed_meta = filter_closed_ohlcv_rows(
                    rows, timeframe=timeframe
                )
                if closed_rows:
                    closed_result = build_full_talib_ta_payload(
                        symbol=symbol,
                        timeframe=timeframe,
                        candles=closed_rows,
                        source_ohlcv_key=source_key,
                    )
                    closed_payload = closed_result.to_payload(
                        source_ohlcv_key=source_key
                    )
                    closed_payload.update(
                        {
                            "source_label": "V2_FULL_TALIB_TA_CLOSED_CANDLES_ONLY",
                            "closed_candles_only": True,
                            "candle_closed_confirmed": True,
                            "last_closed_candle_open_ts_ms": closed_meta[
                                "last_closed_candle_open_ts_ms"
                            ],
                            "last_closed_candle_close_ts_ms": closed_meta[
                                "last_closed_candle_close_ts_ms"
                            ],
                            "in_progress_candles_dropped": closed_meta[
                                "dropped_unclosed_count"
                            ],
                            "unprovable_candles_dropped": closed_meta[
                                "dropped_unprovable_count"
                            ],
                        }
                    )
                    closed_key = f"v2:features:ta_closed:{symbol}:{timeframe}"
                    if _safe_set_json(
                        redis_client, closed_key, closed_payload, ttl_seconds
                    ):
                        keys_written.append(closed_key)
            ta_key = f"v2:features:ta:{symbol}:{timeframe}"
            full_key = f"v2:features:ta_full:{symbol}:{timeframe}"
            technical_key = f"v2:technical_analysis:{symbol}:{timeframe}"
            if _safe_set_json(redis_client, ta_key, payload, ttl_seconds):
                keys_written.append(ta_key)
            if _safe_set_json(redis_client, full_key, payload, ttl_seconds):
                keys_written.append(full_key)
            if _safe_set_json(redis_client, technical_key, payload, ttl_seconds):
                keys_written.append(technical_key)
            classifications[payload["classification"]] = (
                classifications.get(payload["classification"], 0) + 1
            )
            max_indicator_count = max(max_indicator_count, int(payload["indicator_count"]))
            min_indicator_count = (
                int(payload["indicator_count"])
                if min_indicator_count is None
                else min(min_indicator_count, int(payload["indicator_count"]))
            )
            key_results.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "source_ohlcv_key": source_key,
                    "ta_key": ta_key,
                    "ta_full_key": full_key,
                    "technical_analysis_key": technical_key,
                    "classification": payload["classification"],
                    "indicator_count": payload["indicator_count"],
                    "computed_function_count": payload["computed_function_count"],
                    "candle_count": payload["candle_count"],
                    "last_candle_ts_ms": payload["last_candle_ts_ms"],
                }
            )

    status = {
        "schema_version": "v2_full_talib_ta_loop_status_v1",
        "worker_id": WORKER_ID,
        "payload_schema_version": FULL_TALIB_TA_SCHEMA_VERSION,
        "started_at": started_at,
        "finished_at": _utc_iso(),
        "redis_connected": redis_client is not None,
        "symbols_requested": requested_symbols,
        "symbol_scope": symbol_scope,
        "symbols_processed": sorted({row["symbol"] for row in key_results}),
        "symbols_processed_count": len({row["symbol"] for row in key_results}),
        "timeframes_requested": all_timeframes,
        "timeframes_processed": sorted({row["timeframe"] for row in key_results}),
        "keys_written": keys_written,
        "keys_written_count": len(keys_written),
        "missing_ohlcv_keys": missing_ohlcv_keys[:200],
        "missing_ohlcv_key_count": len(missing_ohlcv_keys),
        "results": key_results[:300],
        "result_count": len(key_results),
        "classification_counts": classifications,
        "max_indicator_count": max_indicator_count,
        "min_indicator_count": min_indicator_count,
        "ttl_seconds": int(ttl_seconds),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "writes_legacy_redis": False,
        "exchange_action_taken": False,
        "places_real_order": False,
    }
    if key_results and max_indicator_count >= 150:
        status["classification"] = "V2_FULL_TALIB_TA_LIVE_OK"
    elif key_results:
        status["classification"] = "V2_FULL_TALIB_TA_LIVE_PARTIAL"
    elif redis_client is None:
        status["classification"] = "BLOCKED_REDIS_UNAVAILABLE"
    else:
        status["classification"] = "BLOCKED_NO_OHLCV_INPUTS"

    _safe_set_json(redis_client, "v2:features:ta:heartbeat", status, min(ttl_seconds, 300))
    _write_status(status, PUBLIC_STATUS_PATH)
    _write_status(status, LOCAL_STATUS_PATH)
    return status


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=WORKER_ID)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--timeframes", default=None)
    parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--loop", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.loop:
        while True:
            run_once(
                symbols_arg=args.symbols,
                timeframes_arg=args.timeframes,
                ttl_seconds=args.ttl_seconds,
                smoke_test=args.smoke_test,
            )
            time.sleep(max(10, int(args.interval_seconds)))
    status = run_once(
        symbols_arg=args.symbols,
        timeframes_arg=args.timeframes,
        ttl_seconds=args.ttl_seconds,
        smoke_test=args.smoke_test,
    )
    print(
        json.dumps(
            {
                "classification": status["classification"],
                "result_count": status["result_count"],
                "keys_written_count": status["keys_written_count"],
                "max_indicator_count": status["max_indicator_count"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
