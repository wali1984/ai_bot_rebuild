"""One-shot V2 closed-candle resampler.

Builds higher-timeframe closed candles only from complete lower-timeframe
closed-candle slots. It never reads current/partial candles and never touches
order or exchange mutation paths.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_repo = Path(__file__).resolve().parents[4]
if str(_repo) not in sys.path:
    sys.path.insert(0, str(_repo))

import redis  # noqa: E402

from v2.backend.app.services.market_state_integrity.canonical_candles import (  # noqa: E402
    aggregate_closed_candles,
    append_closed_candle,
    canonical_from_binance_rest,
    closed_candle_key,
    now_ms,
)

DEFAULT_SOURCE_TIMEFRAME = "5m"
DEFAULT_TARGET_TIMEFRAMES = ("1h", "4h")


def _redis_client() -> redis.Redis:
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    return redis.Redis.from_url(url, decode_responses=True)


def _load_json_list(raw: Any) -> list[Any]:
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except Exception:
        return []
    if not isinstance(decoded, list):
        return []
    return [row for row in decoded if isinstance(row, (dict, list, tuple))]


def _rest_row_from_payload(row: Any) -> list[Any]:
    if isinstance(row, (list, tuple)):
        return list(row)
    if not isinstance(row, dict):
        raise ValueError("unsupported_ohlcv_row")
    return [
        row.get("candle_open_time") or row.get("open_time"),
        row.get("open"),
        row.get("high"),
        row.get("low"),
        row.get("close"),
        row.get("volume"),
        row.get("candle_close_time") or row.get("close_time"),
        row.get("quote_volume"),
        row.get("num_trades"),
        row.get("taker_buy_base_vol"),
        row.get("taker_buy_quote_vol"),
        row.get("ignore", "0"),
    ]


def _symbols_from_redis(r: redis.Redis, source_timeframe: str) -> list[str]:
    symbols: set[str] = set()
    for key in r.scan_iter(match=f"v2:market:ohlcv_closed:binance:*:{source_timeframe}", count=1000):
        parts = str(key).split(":")
        if len(parts) >= 6 and parts[4]:
            symbols.add(parts[4].upper())
    return sorted(symbols)


def _symbols_from_raw_ohlcv(r: redis.Redis, timeframe: str) -> list[str]:
    symbols: set[str] = set()
    for key in r.scan_iter(match=f"v2:market:ohlcv:binance:*:{timeframe}", count=1000):
        parts = str(key).split(":")
        if len(parts) >= 6 and parts[4]:
            symbols.add(parts[4].upper())
    return sorted(symbols)


def copy_finalized_raw_ohlcv(
    r: redis.Redis,
    *,
    symbol: str,
    timeframe: str,
    limit: int = 1500,
    now_ms_value: int | None = None,
) -> dict[str, Any]:
    raw_key = f"v2:market:ohlcv:binance:{symbol}:{timeframe}"
    target_key = closed_candle_key("binance", symbol, timeframe)
    raw_rows = _load_json_list(r.get(raw_key))
    existing = _load_json_list(r.get(target_key))
    current_ms = int(now_ms_value if now_ms_value is not None else now_ms())
    merged = existing
    imported = 0
    skipped_future_or_open = 0
    invalid_rows = 0
    for row in raw_rows:
        try:
            candle = canonical_from_binance_rest(
                _rest_row_from_payload(row),
                symbol=symbol,
                timeframe=timeframe,
                ingested_at=current_ms,
            )
        except Exception:
            invalid_rows += 1
            continue
        if not candle.is_closed or not candle.feature_eligible:
            skipped_future_or_open += 1
            continue
        before = len(merged)
        merged = append_closed_candle(merged, candle.to_dict(), limit=limit)
        imported += int(len(merged) >= before)
    if merged != existing:
        r.set(target_key, json.dumps(merged, sort_keys=True, default=str))
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source_key": raw_key,
        "redis_key": target_key,
        "raw_rows": len(raw_rows),
        "rows_before": len(existing),
        "rows_after": len(merged),
        "finalized_rows_seen": imported,
        "skipped_future_or_open_rows": skipped_future_or_open,
        "invalid_rows": invalid_rows,
    }


def resample_symbol(
    r: redis.Redis,
    *,
    symbol: str,
    source_timeframe: str,
    target_timeframes: tuple[str, ...],
    limit: int = 1500,
) -> list[dict[str, Any]]:
    source_key = closed_candle_key("binance", symbol, source_timeframe)
    source_rows = _load_json_list(r.get(source_key))
    results: list[dict[str, Any]] = []
    for target_timeframe in target_timeframes:
        target_key = closed_candle_key("binance", symbol, target_timeframe)
        existing = _load_json_list(r.get(target_key))
        before = len(existing)
        aggregates = aggregate_closed_candles(
            source_rows,
            symbol=symbol,
            source_timeframe=source_timeframe,
            target_timeframe=target_timeframe,
        )
        merged = existing
        for candle in aggregates:
            merged = append_closed_candle(merged, candle, limit=limit)
        after = len(merged)
        if after != before or aggregates:
            r.set(target_key, json.dumps(merged, sort_keys=True, default=str))
        results.append(
            {
                "symbol": symbol,
                "source_timeframe": source_timeframe,
                "target_timeframe": target_timeframe,
                "source_rows": len(source_rows),
                "aggregates_built": len(aggregates),
                "rows_before": before,
                "rows_after": after,
                "redis_key": target_key,
            }
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Resample complete V2 closed candles into higher timeframes.")
    parser.add_argument("--source-timeframe", default=DEFAULT_SOURCE_TIMEFRAME)
    parser.add_argument("--target-timeframe", action="append", dest="target_timeframes")
    parser.add_argument("--symbol", action="append", dest="symbols")
    parser.add_argument("--limit", type=int, default=1500)
    parser.add_argument(
        "--copy-finalized-raw",
        action="store_true",
        help="Copy finalized v2:market:ohlcv raw rows into the closed-candle namespace.",
    )
    parser.add_argument("--raw-timeframe", action="append", dest="raw_timeframes")
    args = parser.parse_args()

    r = _redis_client()
    if args.copy_finalized_raw:
        raw_timeframes = tuple(args.raw_timeframes or args.target_timeframes or (args.source_timeframe,))
        if args.symbols:
            symbols_by_timeframe = {
                timeframe: sorted({str(symbol).upper() for symbol in args.symbols})
                for timeframe in raw_timeframes
            }
        else:
            symbols_by_timeframe = {
                timeframe: _symbols_from_raw_ohlcv(r, timeframe)
                for timeframe in raw_timeframes
            }
        all_results: list[dict[str, Any]] = []
        for timeframe, symbols in symbols_by_timeframe.items():
            for symbol in symbols:
                all_results.append(
                    copy_finalized_raw_ohlcv(
                        r,
                        symbol=symbol,
                        timeframe=timeframe,
                        limit=args.limit,
                    )
                )
        written = [row for row in all_results if int(row.get("rows_after") or 0) > int(row.get("rows_before") or 0)]
        print(
            json.dumps(
                {
                    "mode": "copy_finalized_raw",
                    "raw_timeframes": list(raw_timeframes),
                    "symbols_scanned": sum(len(symbols) for symbols in symbols_by_timeframe.values()),
                    "result_rows": len(all_results),
                    "keys_with_new_rows": len(written),
                    "new_rows_written": sum(
                        int(row.get("rows_after") or 0) - int(row.get("rows_before") or 0)
                        for row in all_results
                    ),
                    "skipped_future_or_open_rows": sum(
                        int(row.get("skipped_future_or_open_rows") or 0)
                        for row in all_results
                    ),
                    "sample_results": all_results[:20],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    target_timeframes = tuple(args.target_timeframes or DEFAULT_TARGET_TIMEFRAMES)
    symbols = sorted({str(symbol).upper() for symbol in (args.symbols or _symbols_from_redis(r, args.source_timeframe))})
    all_results: list[dict[str, Any]] = []
    for symbol in symbols:
        all_results.extend(
            resample_symbol(
                r,
                symbol=symbol,
                source_timeframe=args.source_timeframe,
                target_timeframes=target_timeframes,
                limit=args.limit,
            )
        )
    written = [row for row in all_results if int(row.get("rows_after") or 0) > int(row.get("rows_before") or 0)]
    print(
        json.dumps(
            {
                "symbols_scanned": len(symbols),
                "source_timeframe": args.source_timeframe,
                "target_timeframes": list(target_timeframes),
                "result_rows": len(all_results),
                "keys_with_new_rows": len(written),
                "new_rows_written": sum(
                    int(row.get("rows_after") or 0) - int(row.get("rows_before") or 0)
                    for row in all_results
                ),
                "sample_results": all_results[:20],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
