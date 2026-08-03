"""Backfill closed paper-trade path telemetry from final candles.

This module repairs historical paper-only closed rows when real closed candle
history exists for the interval between entry and exit. It deliberately ignores
overlapping or unfinished candles; uncovered rows stay dirty.
"""
from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from v2.backend.app.services.binance_unified_websocket_transport import (
    binance_rest_fallback_allowed,
    require_binance_rest_fallback,
)


SCHEMA_VERSION = "v2_paper_closed_trade_path_telemetry_backfill_v1"
PATH_FIELDS = ("mfe_bps", "mae_bps", "intra_trade_high_price", "intra_trade_low_price")
TIMEFRAME_ORDER = ("1m", "5m", "15m", "1h", "4h")
BINANCE_USDM_KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
BINANCE_USDM_AGG_TRADES_URL = "https://fapi.binance.com/fapi/v1/aggTrades"
BINANCE_USDM_KLINES_LIMIT = 1500
BINANCE_USDM_KLINES_CHUNK_MS = (BINANCE_USDM_KLINES_LIMIT - 2) * 60_000
BINANCE_USDM_AGG_TRADES_LIMIT = 1000
BINANCE_USDM_AGG_TRADES_MAX_PAGES = 50


@dataclass(frozen=True)
class NormalizedCandle:
    open_time_ms: float
    close_time_ms: float
    available_at_ms: float | None
    high: float
    low: float
    source_key: str
    timeframe: str


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def parse_time_ms(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        parsed = float(value)
        if not math.isfinite(parsed):
            return None
        return parsed if parsed > 10_000_000_000 else parsed * 1000.0
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp() * 1000.0
    except (TypeError, ValueError):
        return None


def iso_from_ms(value: float | None) -> str | None:
    if value is None or not math.isfinite(value):
        return None
    return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def safe_load_json(raw: Any) -> Any:
    if raw in (None, ""):
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def rows_from_payload(payload: Any, keys: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    if not keys:
        keys = ("closed_trades", "closed", "closes", "closed_positions", "outcome_labels", "rows")
    for key in keys:
        rows = payload.get(key)
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, dict)]
    return []


def row_identity(row: dict[str, Any]) -> str:
    for key in ("close_id", "outcome_label_id", "trainer_feedback_id", "position_id", "fill_id", "ledger_row_id"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return (
        f"{row.get('symbol')}|{row.get('timeframe')}|{row.get('side')}|"
        f"{row.get('entry_price')}|{row.get('exit_price')}|"
        f"{row.get('exit_time') or row.get('exit_price_utc')}"
    )


def row_match_tokens(row: dict[str, Any]) -> set[str]:
    tokens = {
        str(value)
        for value in (
            row.get("close_id"),
            row.get("outcome_label_id"),
            row.get("trainer_feedback_id"),
        )
        if value not in (None, "")
    }
    tokens.add(row_identity(row))
    return tokens


def has_complete_path(row: dict[str, Any]) -> bool:
    return all(coerce_float(row.get(field)) is not None for field in PATH_FIELDS)


def normalize_candle(raw: Any, *, source_key: str, timeframe: str) -> NormalizedCandle | None:
    if isinstance(raw, list):
        if len(raw) < 7:
            return None
        open_time_ms = coerce_float(raw[0])
        high = coerce_float(raw[2])
        low = coerce_float(raw[3])
        close_time_ms = coerce_float(raw[6])
        available_at_ms = close_time_ms
    elif isinstance(raw, dict):
        if raw.get("is_closed") is False or raw.get("closed_candle") is False:
            return None
        if raw.get("candle_closed_confirmed") is False or raw.get("feature_eligible") is False:
            return None
        ohlcv = raw.get("ohlcv") if isinstance(raw.get("ohlcv"), dict) else {}
        open_time_ms = coerce_float(
            raw.get("candle_open_time") or raw.get("open_time") or raw.get("ts") or raw.get("event_time")
        )
        close_time_ms = coerce_float(raw.get("candle_close_time") or raw.get("close_time") or raw.get("event_time"))
        available_at_ms = coerce_float(raw.get("available_at") or raw.get("ingested_at") or close_time_ms)
        high = coerce_float(raw.get("high") or ohlcv.get("high"))
        low = coerce_float(raw.get("low") or ohlcv.get("low"))
    else:
        return None
    if None in (open_time_ms, close_time_ms, high, low):
        return None
    if close_time_ms < open_time_ms or high <= 0.0 or low <= 0.0:
        return None
    return NormalizedCandle(
        open_time_ms=float(open_time_ms),
        close_time_ms=float(close_time_ms),
        available_at_ms=float(available_at_ms) if available_at_ms is not None else None,
        high=float(high),
        low=float(low),
        source_key=source_key,
        timeframe=timeframe,
    )


def fetch_binance_public_1m_candles(
    symbol: str,
    *,
    start_ms: float,
    end_ms: float,
    timeout_seconds: float = 8.0,
    http_get_json: Callable[[str, float], Any] | None = None,
    fetched_at_ms: float | None = None,
) -> list[NormalizedCandle]:
    """Fetch final public 1m USD-M klines for a closed paper-trade interval."""
    if end_ms <= start_ms:
        return []
    available_at_ms = fetched_at_ms if fetched_at_ms is not None else datetime.now(timezone.utc).timestamp() * 1000.0
    candles: list[NormalizedCandle] = []
    source_key = f"BINANCE_USDM_PUBLIC_KLINES:{symbol.upper()}:1m"
    cursor_ms = int(start_ms)
    final_end_ms = int(end_ms)
    while cursor_ms <= final_end_ms:
        chunk_end_ms = min(final_end_ms, cursor_ms + BINANCE_USDM_KLINES_CHUNK_MS)
        interval_minutes = max(1, int(math.ceil((chunk_end_ms - cursor_ms) / 60_000.0)) + 2)
        params = urllib.parse.urlencode(
            {
                "symbol": symbol.upper(),
                "interval": "1m",
                "startTime": cursor_ms,
                "endTime": chunk_end_ms,
                "limit": min(BINANCE_USDM_KLINES_LIMIT, interval_minutes),
            }
        )
        url = f"{BINANCE_USDM_KLINES_URL}?{params}"
        try:
            if http_get_json is None:
                if not binance_rest_fallback_allowed():
                    return []
                require_binance_rest_fallback(
                    endpoint="/fapi/v1/klines",
                    fallback_reason="paper_path_telemetry_closed_kline_gap",
                    role="paper_path_telemetry_backfill_recovery",
                )
                with urllib.request.urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310 - read-only public market data
                    payload = json.loads(response.read().decode("utf-8"))
            else:
                payload = http_get_json(url, timeout_seconds)
        except Exception:  # noqa: BLE001
            payload = []
        if isinstance(payload, list):
            for raw in payload:
                candle = normalize_candle(raw, source_key=source_key, timeframe="1m")
                if candle is None:
                    continue
                candles.append(
                    NormalizedCandle(
                        open_time_ms=candle.open_time_ms,
                        close_time_ms=candle.close_time_ms,
                        available_at_ms=available_at_ms,
                        high=candle.high,
                        low=candle.low,
                        source_key=candle.source_key,
                        timeframe=candle.timeframe,
                    )
                )
        if chunk_end_ms >= final_end_ms:
            break
        cursor_ms = chunk_end_ms + 1
    deduped = {
        (candle.open_time_ms, candle.close_time_ms, candle.high, candle.low): candle
        for candle in candles
    }
    return sorted(deduped.values(), key=lambda candle: (candle.open_time_ms, candle.close_time_ms))


def fetch_binance_public_agg_trade_samples(
    symbol: str,
    *,
    start_ms: float,
    end_ms: float,
    timeout_seconds: float = 8.0,
    http_get_json: Callable[[str, float], Any] | None = None,
    fetched_at_ms: float | None = None,
) -> list[NormalizedCandle]:
    """Fetch immutable public aggregate trade prices for short paper intervals."""
    if end_ms <= start_ms:
        return []
    available_at_ms = fetched_at_ms if fetched_at_ms is not None else datetime.now(timezone.utc).timestamp() * 1000.0
    source_key = f"BINANCE_USDM_PUBLIC_AGG_TRADES:{symbol.upper()}"
    samples: list[NormalizedCandle] = []
    seen_ids: set[str] = set()
    cursor_ms = int(start_ms)
    final_end_ms = int(end_ms)
    for _ in range(BINANCE_USDM_AGG_TRADES_MAX_PAGES):
        if cursor_ms > final_end_ms:
            break
        params = urllib.parse.urlencode(
            {
                "symbol": symbol.upper(),
                "startTime": cursor_ms,
                "endTime": final_end_ms,
                "limit": BINANCE_USDM_AGG_TRADES_LIMIT,
            }
        )
        url = f"{BINANCE_USDM_AGG_TRADES_URL}?{params}"
        try:
            if http_get_json is None:
                if not binance_rest_fallback_allowed():
                    break
                require_binance_rest_fallback(
                    endpoint="/fapi/v1/aggTrades",
                    fallback_reason="paper_path_telemetry_agg_trade_gap",
                    role="paper_path_telemetry_backfill_recovery",
                )
                with urllib.request.urlopen(url, timeout=timeout_seconds) as response:  # noqa: S310 - read-only public market data
                    payload = json.loads(response.read().decode("utf-8"))
            else:
                payload = http_get_json(url, timeout_seconds)
        except Exception:  # noqa: BLE001
            payload = []
        if not isinstance(payload, list) or not payload:
            break
        latest_time_ms = cursor_ms
        for raw in payload:
            if not isinstance(raw, dict):
                continue
            trade_id = raw.get("a")
            if trade_id not in (None, ""):
                trade_id_key = str(trade_id)
                if trade_id_key in seen_ids:
                    continue
                seen_ids.add(trade_id_key)
            price = coerce_float(raw.get("p"))
            trade_time_ms = coerce_float(raw.get("T"))
            if price is None or price <= 0.0 or trade_time_ms is None:
                continue
            latest_time_ms = max(latest_time_ms, int(trade_time_ms))
            samples.append(
                NormalizedCandle(
                    open_time_ms=float(trade_time_ms),
                    close_time_ms=float(trade_time_ms),
                    available_at_ms=available_at_ms,
                    high=float(price),
                    low=float(price),
                    source_key=source_key,
                    timeframe="aggTrade",
                )
            )
        if len(payload) < BINANCE_USDM_AGG_TRADES_LIMIT or latest_time_ms <= cursor_ms:
            break
        cursor_ms = latest_time_ms + 1
    return sorted(samples, key=lambda sample: (sample.open_time_ms, sample.high, sample.low))


def public_kline_symbol_windows(rows: Iterable[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    windows: dict[str, tuple[float, float]] = {}
    for row in rows:
        if has_complete_path(row):
            continue
        symbol = str(row.get("symbol") or "").upper().strip()
        entry_ms, exit_ms = trade_interval_ms(row)
        if not symbol or entry_ms is None or exit_ms is None:
            continue
        current = windows.get(symbol)
        if current is None:
            windows[symbol] = (entry_ms, exit_ms)
        else:
            windows[symbol] = (min(current[0], entry_ms), max(current[1], exit_ms))
    return windows


def trade_interval_ms(row: dict[str, Any]) -> tuple[float | None, float | None]:
    exit_ms = parse_time_ms(row.get("exit_price_utc") or row.get("exit_time") or row.get("generated_utc"))
    hold_seconds = coerce_float(row.get("hold_time_seconds"))
    if exit_ms is None or hold_seconds is None or hold_seconds < 0.0:
        return None, exit_ms
    return exit_ms - hold_seconds * 1000.0, exit_ms


def contained_candles_for_row(
    row: dict[str, Any],
    candles: Iterable[NormalizedCandle],
) -> list[NormalizedCandle]:
    entry_ms, exit_ms = trade_interval_ms(row)
    if entry_ms is None or exit_ms is None:
        return []
    return [
        candle
        for candle in candles
        if candle.open_time_ms >= entry_ms and candle.close_time_ms <= exit_ms
    ]


def _candidate_redis_keys(symbol: str, timeframe: str) -> tuple[str, str]:
    return (
        f"v2:market:ohlcv_closed:binance:{symbol}:{timeframe}",
        f"v2:market:ohlcv:binance:{symbol}:{timeframe}",
    )


def _read_key(redis_client: Any, key: str) -> Any:
    try:
        return safe_load_json(redis_client.get(key))
    except Exception:  # noqa: BLE001
        return None


def load_normalized_candles(redis_client: Any, symbol: str, timeframe: str) -> list[NormalizedCandle]:
    candles: list[NormalizedCandle] = []
    for key in _candidate_redis_keys(symbol, timeframe):
        payload = _read_key(redis_client, key)
        if not isinstance(payload, list):
            continue
        for raw in payload:
            candle = normalize_candle(raw, source_key=key, timeframe=timeframe)
            if candle is not None:
                candles.append(candle)
    candles.sort(key=lambda candle: (candle.open_time_ms, candle.close_time_ms, candle.source_key))
    return candles


def best_contained_candles(redis_client: Any, row: dict[str, Any]) -> tuple[str | None, list[NormalizedCandle]]:
    symbol = str(row.get("symbol") or "").upper().strip()
    if not symbol:
        return None, []
    for timeframe in TIMEFRAME_ORDER:
        candles = contained_candles_for_row(row, load_normalized_candles(redis_client, symbol, timeframe))
        if candles:
            return timeframe, candles
    return None, []


def best_contained_candles_with_optional_public_fetch(
    redis_client: Any,
    row: dict[str, Any],
    *,
    fetch_binance_public_klines: bool = False,
    fetch_binance_public_agg_trades: bool = False,
    public_cache: dict[str, list[NormalizedCandle]] | None = None,
    public_trade_cache: dict[str, list[NormalizedCandle]] | None = None,
    public_symbol_windows: dict[str, tuple[float, float]] | None = None,
    timeout_seconds: float = 8.0,
    http_get_json: Callable[[str, float], Any] | None = None,
    fetched_at_ms: float | None = None,
) -> tuple[str | None, list[NormalizedCandle], bool]:
    timeframe, candles = best_contained_candles(redis_client, row)
    if candles or (not fetch_binance_public_klines and not fetch_binance_public_agg_trades):
        return timeframe, candles, False
    symbol = str(row.get("symbol") or "").upper().strip()
    entry_ms, exit_ms = trade_interval_ms(row)
    if not symbol or entry_ms is None or exit_ms is None:
        return None, [], False
    used_public = False
    if fetch_binance_public_klines:
        fetch_start_ms, fetch_end_ms = (
            public_symbol_windows.get(symbol, (entry_ms, exit_ms))
            if public_symbol_windows is not None
            else (entry_ms, exit_ms)
        )
        cache_key = f"{symbol}:{int(fetch_start_ms)}:{int(fetch_end_ms)}"
        if public_cache is not None and cache_key in public_cache:
            fetched = public_cache[cache_key]
        else:
            fetched = fetch_binance_public_1m_candles(
                symbol,
                start_ms=fetch_start_ms,
                end_ms=fetch_end_ms,
                timeout_seconds=timeout_seconds,
                http_get_json=http_get_json,
                fetched_at_ms=fetched_at_ms,
            )
            if public_cache is not None:
                public_cache[cache_key] = fetched
        used_public = used_public or bool(fetched)
        contained = contained_candles_for_row(row, fetched)
        if contained:
            return "1m", contained, True
    if fetch_binance_public_agg_trades:
        trade_cache_key = f"{symbol}:{int(entry_ms)}:{int(exit_ms)}"
        if public_trade_cache is not None and trade_cache_key in public_trade_cache:
            trade_samples = public_trade_cache[trade_cache_key]
        else:
            trade_samples = fetch_binance_public_agg_trade_samples(
                symbol,
                start_ms=entry_ms,
                end_ms=exit_ms,
                timeout_seconds=timeout_seconds,
                http_get_json=http_get_json,
                fetched_at_ms=fetched_at_ms,
            )
            if public_trade_cache is not None:
                public_trade_cache[trade_cache_key] = trade_samples
        used_public = used_public or bool(trade_samples)
        contained = contained_candles_for_row(row, trade_samples)
        if contained:
            return "aggTrade", contained, True
    return None, [], used_public


def enriched_path_fields(
    row: dict[str, Any],
    candles: list[NormalizedCandle],
    *,
    generated_at: str,
) -> dict[str, Any] | None:
    if not candles:
        return None
    entry_price = coerce_float(row.get("entry_price"))
    exit_price = coerce_float(row.get("exit_price"))
    quantity = coerce_float(row.get("closed_quantity") or row.get("quantity") or row.get("net_quantity")) or 0.0
    side = str(row.get("side") or row.get("action") or "").lower()
    entry_ms, exit_ms = trade_interval_ms(row)
    if entry_price is None or exit_price is None or entry_price <= 0.0 or side not in {"long", "short"}:
        return None
    highs = [entry_price, exit_price, *(candle.high for candle in candles)]
    lows = [entry_price, exit_price, *(candle.low for candle in candles)]
    high = max(highs)
    low = min(lows)
    if side == "short":
        favorable_delta = max(0.0, entry_price - low)
        adverse_delta = max(0.0, high - entry_price)
    else:
        favorable_delta = max(0.0, high - entry_price)
        adverse_delta = max(0.0, entry_price - low)
    max_available_at = max((candle.available_at_ms for candle in candles if candle.available_at_ms is not None), default=None)
    return {
        "mfe_bps": favorable_delta / entry_price * 10000.0,
        "mae_bps": adverse_delta / entry_price * 10000.0,
        "mfe_usd": favorable_delta * abs(quantity),
        "mae_usd": adverse_delta * abs(quantity),
        "intra_trade_high_price": high,
        "intra_trade_low_price": low,
        "path_telemetry_source": "V2_CLOSED_CANDLE_CONTAINED_PATH_BACKFILL",
        "path_telemetry_quality": "STRICT_CONTAINED_FINAL_CANDLES_PLUS_ENTRY_EXIT_BOUNDARIES",
        "path_telemetry_generated_at": generated_at,
        "path_telemetry_available_at": iso_from_ms(max(exit_ms, max_available_at or exit_ms) if exit_ms is not None else max_available_at),
        "path_telemetry_event_start_time": iso_from_ms(entry_ms),
        "path_telemetry_event_end_time": iso_from_ms(exit_ms),
        "path_telemetry_candle_count": len(candles),
        "path_telemetry_candle_timeframe": candles[0].timeframe,
        "path_telemetry_candle_source_keys": sorted({candle.source_key for candle in candles}),
        "path_telemetry_first_candle_close_time": iso_from_ms(min(candle.close_time_ms for candle in candles)),
        "path_telemetry_last_candle_close_time": iso_from_ms(max(candle.close_time_ms for candle in candles)),
        "path_telemetry_uses_unfinished_candle": False,
        "path_telemetry_uses_overlapping_candle": False,
        "path_telemetry_paper_only": True,
    }


def enrich_closed_trade_row(
    redis_client: Any,
    row: dict[str, Any],
    *,
    generated_at: str,
    fetch_binance_public_klines: bool = False,
    fetch_binance_public_agg_trades: bool = False,
    public_cache: dict[str, list[NormalizedCandle]] | None = None,
    public_trade_cache: dict[str, list[NormalizedCandle]] | None = None,
    public_symbol_windows: dict[str, tuple[float, float]] | None = None,
    timeout_seconds: float = 8.0,
    http_get_json: Callable[[str, float], Any] | None = None,
    fetched_at_ms: float | None = None,
) -> tuple[dict[str, Any], str, bool]:
    if has_complete_path(row):
        return dict(row), "already_complete", False
    timeframe, candles, used_public = best_contained_candles_with_optional_public_fetch(
        redis_client,
        row,
        fetch_binance_public_klines=fetch_binance_public_klines,
        fetch_binance_public_agg_trades=fetch_binance_public_agg_trades,
        public_cache=public_cache,
        public_trade_cache=public_trade_cache,
        public_symbol_windows=public_symbol_windows,
        timeout_seconds=timeout_seconds,
        http_get_json=http_get_json,
        fetched_at_ms=fetched_at_ms,
    )
    fields = enriched_path_fields(row, candles, generated_at=generated_at)
    if fields is None or timeframe is None:
        out = dict(row)
        out.setdefault("path_telemetry_backfill_status", "NO_STRICT_CONTAINED_FINAL_CANDLE_COVERAGE")
        return out, "not_coverable", used_public
    out = dict(row)
    out.update(fields)
    out["path_telemetry_backfill_status"] = "REPAIRED_FROM_STRICT_CONTAINED_FINAL_CANDLES"
    if used_public:
        source_keys = out.get("path_telemetry_candle_source_keys")
        source_key_text = " ".join(str(key) for key in source_keys) if isinstance(source_keys, list) else ""
        out["path_telemetry_public_market_data_readonly"] = True
        if "BINANCE_USDM_PUBLIC_AGG_TRADES" in source_key_text:
            out["path_telemetry_source"] = "BINANCE_USDM_PUBLIC_AGG_TRADES_CONTAINED_PATH_BACKFILL"
            out["path_telemetry_quality"] = "STRICT_CONTAINED_FINAL_AGG_TRADES_PLUS_ENTRY_EXIT_BOUNDARIES"
            out["path_telemetry_public_agg_trades_readonly"] = True
            out["path_telemetry_backfill_status"] = "REPAIRED_FROM_STRICT_CONTAINED_PUBLIC_AGG_TRADES"
        else:
            out["path_telemetry_source"] = "BINANCE_USDM_PUBLIC_KLINES_CONTAINED_PATH_BACKFILL"
            out["path_telemetry_public_klines_readonly"] = True
            out["path_telemetry_backfill_status"] = "REPAIRED_FROM_STRICT_CONTAINED_PUBLIC_KLINES"
    return out, "repaired", used_public


def _update_matching_rows(rows: list[dict[str, Any]], enriched_by_token: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    updated: list[dict[str, Any]] = []
    count = 0
    for row in rows:
        tokens = row_match_tokens(row)
        enriched = next((enriched_by_token[token] for token in tokens if token in enriched_by_token), None)
        if enriched is None:
            updated.append(dict(row))
            continue
        merged = dict(row)
        for key, value in enriched.items():
            if key in PATH_FIELDS or key.startswith("path_telemetry") or key in {"mfe_usd", "mae_usd"}:
                merged[key] = value
        updated.append(merged)
        count += 1
    return updated, count


def build_path_telemetry_backfill_report(
    redis_client: Any,
    *,
    write: bool = False,
    generated_at: str | None = None,
    fetch_binance_public_klines: bool = False,
    fetch_binance_public_agg_trades: bool = False,
    timeout_seconds: float = 8.0,
    http_get_json: Callable[[str, float], Any] | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or utc_iso()
    fetched_at_ms = parse_time_ms(generated_at)
    closed_trades = rows_from_payload(_read_key(redis_client, "v2:paper:closed_trades"))
    outcome_labels = rows_from_payload(_read_key(redis_client, "v2:paper:outcome_labels"))
    ledger = _read_key(redis_client, "v2:paper:ledger")
    ledger = ledger if isinstance(ledger, dict) else {}

    repaired_rows: list[dict[str, Any]] = []
    repaired_by_token: dict[str, dict[str, Any]] = {}
    status_counts = {"already_complete": 0, "repaired": 0, "not_coverable": 0}
    public_symbol_windows = public_kline_symbol_windows(closed_trades) if fetch_binance_public_klines else {}
    public_cache: dict[str, list[NormalizedCandle]] = {}
    public_trade_cache: dict[str, list[NormalizedCandle]] = {}
    public_fetch_used_count = 0
    public_kline_used_count = 0
    public_agg_trade_used_count = 0
    examples: list[dict[str, Any]] = []
    for row in closed_trades:
        enriched, status, used_public = enrich_closed_trade_row(
            redis_client,
            row,
            generated_at=generated_at,
            fetch_binance_public_klines=fetch_binance_public_klines,
            fetch_binance_public_agg_trades=fetch_binance_public_agg_trades,
            public_cache=public_cache,
            public_trade_cache=public_trade_cache,
            public_symbol_windows=public_symbol_windows,
            timeout_seconds=timeout_seconds,
            http_get_json=http_get_json,
            fetched_at_ms=fetched_at_ms,
        )
        status_counts[status] = status_counts.get(status, 0) + 1
        if used_public and status == "repaired":
            public_fetch_used_count += 1
            if enriched.get("path_telemetry_public_agg_trades_readonly") is True:
                public_agg_trade_used_count += 1
            elif enriched.get("path_telemetry_public_klines_readonly") is True:
                public_kline_used_count += 1
        repaired_rows.append(enriched)
        if status == "repaired":
            for token in row_match_tokens(row):
                repaired_by_token[token] = enriched
            if len(examples) < 10:
                examples.append(
                    {
                        "symbol": enriched.get("symbol"),
                        "timeframe": enriched.get("timeframe"),
                        "side": enriched.get("side"),
                        "exit_time": enriched.get("exit_time") or enriched.get("exit_price_utc"),
                        "candle_timeframe": enriched.get("path_telemetry_candle_timeframe"),
                        "candle_count": enriched.get("path_telemetry_candle_count"),
                        "source_keys": enriched.get("path_telemetry_candle_source_keys"),
                    }
                )

    updated_outcomes, outcome_updates = _update_matching_rows(outcome_labels, repaired_by_token)
    ledger_updates: dict[str, int] = {}
    updated_ledger = dict(ledger)
    for key in ("closed_trades", "closes", "closed", "closed_positions"):
        if isinstance(ledger.get(key), list):
            updated_rows, count = _update_matching_rows(rows_from_payload({key: ledger.get(key)}, keys=(key,)), repaired_by_token)
            updated_ledger[key] = updated_rows
            ledger_updates[key] = count
    if isinstance(ledger.get("outcome_labels"), list):
        updated_rows, count = _update_matching_rows(rows_from_payload({"outcome_labels": ledger.get("outcome_labels")}, keys=("outcome_labels",)), repaired_by_token)
        updated_ledger["outcome_labels"] = updated_rows
        ledger_updates["outcome_labels"] = count

    keys_written: list[str] = []
    if write:
        redis_client.set("v2:paper:closed_trades", json.dumps(repaired_rows), ex=1800)
        keys_written.append("v2:paper:closed_trades")
        if outcome_labels:
            redis_client.set("v2:paper:outcome_labels", json.dumps(updated_outcomes), ex=1800)
            keys_written.append("v2:paper:outcome_labels")
        if ledger:
            redis_client.set("v2:paper:ledger", json.dumps(updated_ledger), ex=600)
            keys_written.append("v2:paper:ledger")

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "dry_run": not write,
        "writes_redis": bool(write),
        "writes_exchange_orders": False,
        "places_real_order": False,
        "live_gate": "blocked_human_only",
        "closed_trade_rows_seen": len(closed_trades),
        "already_complete_path_rows": status_counts.get("already_complete", 0),
        "repaired_path_rows": status_counts.get("repaired", 0),
        "not_coverable_path_rows": status_counts.get("not_coverable", 0),
        "post_backfill_path_complete_count": status_counts.get("already_complete", 0) + status_counts.get("repaired", 0),
        "outcome_label_rows_seen": len(outcome_labels),
        "outcome_label_rows_updated": outcome_updates,
        "ledger_rows_updated": ledger_updates,
        "keys_written": keys_written,
        "binance_public_klines_fetch_enabled": bool(fetch_binance_public_klines),
        "binance_public_klines_symbol_windows": len(public_symbol_windows),
        "binance_public_klines_cache_entries": len(public_cache),
        "binance_public_klines_rows_fetched": sum(len(rows) for rows in public_cache.values()),
        "binance_public_agg_trades_fetch_enabled": bool(fetch_binance_public_agg_trades),
        "binance_public_agg_trades_cache_entries": len(public_trade_cache),
        "binance_public_agg_trades_rows_fetched": sum(len(rows) for rows in public_trade_cache.values()),
        "binance_public_market_data_used_for_rows": public_fetch_used_count,
        "binance_public_klines_used_for_rows": public_kline_used_count,
        "binance_public_agg_trades_used_for_rows": public_agg_trade_used_count,
        "path_policy": {
            "uses_only_final_candles": True,
            "uses_only_final_public_aggregate_trades": True,
            "requires_candle_open_time_gte_entry_time": True,
            "requires_candle_close_time_lte_exit_time": True,
            "uses_entry_exit_boundary_prices": True,
            "leaves_uncovered_rows_dirty": True,
            "does_not_create_training_decision_features": True,
            "public_market_data_fetch_is_readonly_and_opt_in": True,
            "public_aggregate_trade_fetch_is_readonly_and_opt_in": True,
        },
        "examples": examples,
    }
