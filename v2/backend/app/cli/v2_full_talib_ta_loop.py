"""Publish fail-closed full TA-Lib candidates from canonical closed OHLCV.

Writes only V2 Redis keys:

* ``v2:features:ta_closed:{symbol}:{timeframe}`` (canonical candidate)
* ``v2:features:ta:{symbol}:{timeframe}``
* ``v2:features:ta_full:{symbol}:{timeframe}``
* ``v2:features:ta:heartbeat``

The compatibility views are explicitly nonconsumable.  This worker does not
write ``v2:technical_analysis:*`` because the native feature pipeline owns that
surface.  A successful Redis SET is not represented as a postcommit
availability observation, trainer admission, or consumer authorization.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from v2.backend.app.services.full_talib_ta.service import (
    FULL_TALIB_TA_CLOSED_CANDIDATE_SCHEMA_VERSION,
    FULL_TALIB_TA_REQUIRED_CONTIGUOUS_ROWS,
    build_full_talib_ta_closed_candidate,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    OHLCVClosedWindowValidationError,
    validate_ohlcv_closed_window,
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
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        # Binary responses preserve the exact source bytes used by the closed
        # window validator and its payload digest.
        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=False)
        client.ping()
        return client
    except Exception:
        return None


def _safe_set_json(redis_client: Any, key: str, payload: dict[str, Any], ttl: int) -> bool:
    if redis_client is None or not key.startswith(V2_REDIS_PREFIX):
        return False
    try:
        return (
            redis_client.set(
                key,
                json.dumps(payload, sort_keys=True),
                ex=int(ttl),
            )
            is True
        )
    except Exception:
        return False


def _read_exact_bytes(redis_client: Any, key: str) -> bytes | None:
    if redis_client is None or not key.startswith(V2_REDIS_PREFIX):
        return None
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if type(raw) is bytes:
        return raw or None
    # A decoded string cannot prove the exact bytes originally stored.  The
    # validator's digest boundary therefore rejects it instead of re-encoding.
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
        keys = list(
            redis_client.scan_iter(
                match="v2:market:ohlcv_closed:binance:*",
                count=500,
            )
        )
    except Exception:
        return discovered
    for key in keys:
        if isinstance(key, bytes):
            try:
                key = key.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                continue
        if not isinstance(key, str):
            continue
        parts = key.split(":")
        if len(parts) != 6:
            continue
        _, market, ohlcv, exchange, symbol, timeframe = parts
        if market != "market" or ohlcv != "ohlcv_closed" or exchange != "binance":
            continue
        if symbol == "heartbeat" or not is_valid_runtime_symbol(symbol):
            continue
        discovered.setdefault(symbol.upper(), set()).add(timeframe)
    return discovered


def _write_status(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _compatibility_view(
    candidate: dict[str, Any],
    *,
    canonical_candidate_key: str,
    publication_key: str,
) -> dict[str, Any]:
    """Return a UI/status compatibility view with every authority held false."""

    payload = dict(candidate)
    payload.update(
        {
            "source_label": "V2_FULL_TALIB_TA_CLOSED_COMPATIBILITY_VIEW",
            "publication_key": publication_key,
            "canonical_candidate_key": canonical_candidate_key,
            "compatibility_view": True,
            "compatibility_unsafe_for_trainer": True,
            "available_at": None,
            "publication_observed_at": None,
            "publication_committed": False,
            "consumer_eligible": False,
            "trainer_consumable": False,
            "trainer_admission_granted": False,
            "live_execution_authorized": False,
        }
    )
    return payload


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
    # Redis discovery is inventory, never symbol authority.  Only the resolved
    # current runtime universe may enter the producer candidate path.
    for symbol in requested_symbols:
        symbol = str(symbol or "").upper()
        if symbol and is_valid_runtime_symbol(symbol) and symbol not in seen:
            seen.add(symbol)
            all_symbols.append(symbol)

    requested_timeframes = _parse_csv(timeframes_arg, upper=False)
    if requested_timeframes:
        all_timeframes = list(requested_timeframes)
    else:
        discovered_tfs = sorted(
            {timeframe for symbol in all_symbols for timeframe in discovered.get(symbol, set())}
        )
        all_timeframes = list(dict.fromkeys(list(DEFAULT_TIMEFRAMES) + discovered_tfs))

    key_results: list[dict[str, Any]] = []
    keys_written: list[str] = []
    missing_ohlcv_keys: list[str] = []
    classifications: dict[str, int] = {}
    max_indicator_count = 0
    min_indicator_count: int | None = None

    for symbol in all_symbols:
        for timeframe in all_timeframes:
            source_key = f"v2:market:ohlcv_closed:binance:{symbol}:{timeframe}"
            source_bytes = _read_exact_bytes(redis_client, source_key)
            if source_bytes is None:
                missing_ohlcv_keys.append(source_key)
                classification = "BLOCKED_CANONICAL_CLOSED_OHLCV_MISSING"
                classifications[classification] = classifications.get(classification, 0) + 1
                key_results.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "source_ohlcv_key": source_key,
                        "classification": classification,
                        "rejection_reason": "exact_source_bytes_missing",
                        "candidate_written": False,
                    }
                )
                continue

            try:
                validated_window = validate_ohlcv_closed_window(
                    source_bytes,
                    symbol=symbol,
                    timeframe=timeframe,
                    required_contiguous_lookback=(FULL_TALIB_TA_REQUIRED_CONTIGUOUS_ROWS),
                )
                payload = build_full_talib_ta_closed_candidate(
                    validated_window=validated_window,
                )
            except OHLCVClosedWindowValidationError as exc:
                classification = "BLOCKED_CANONICAL_CLOSED_OHLCV_INVALID"
                classifications[classification] = classifications.get(classification, 0) + 1
                key_results.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "source_ohlcv_key": source_key,
                        "classification": classification,
                        "rejection_reason": str(exc),
                        "candidate_written": False,
                    }
                )
                continue
            except ValueError as exc:
                classification = "BLOCKED_TA_CLOSED_CANDIDATE_CONTRACT"
                classifications[classification] = classifications.get(classification, 0) + 1
                key_results.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "source_ohlcv_key": source_key,
                        "classification": classification,
                        "rejection_reason": str(exc),
                        "candidate_written": False,
                    }
                )
                continue

            closed_key = f"v2:features:ta_closed:{symbol}:{timeframe}"
            ta_key = f"v2:features:ta:{symbol}:{timeframe}"
            full_key = f"v2:features:ta_full:{symbol}:{timeframe}"
            payload["publication_key"] = closed_key
            payload["compatibility_view"] = False
            payload["compatibility_unsafe_for_trainer"] = False
            candidate_written = _safe_set_json(
                redis_client,
                closed_key,
                payload,
                ttl_seconds,
            )
            if candidate_written:
                keys_written.append(closed_key)

            ta_payload = _compatibility_view(
                payload,
                canonical_candidate_key=closed_key,
                publication_key=ta_key,
            )
            full_payload = _compatibility_view(
                payload,
                canonical_candidate_key=closed_key,
                publication_key=full_key,
            )
            if candidate_written:
                if _safe_set_json(redis_client, ta_key, ta_payload, ttl_seconds):
                    keys_written.append(ta_key)
                if _safe_set_json(redis_client, full_key, full_payload, ttl_seconds):
                    keys_written.append(full_key)
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
                    "ta_closed_key": closed_key,
                    "ta_key": ta_key,
                    "ta_full_key": full_key,
                    "technical_analysis_key": None,
                    "technical_analysis_owner": "v2_feature_pipeline_native_loop",
                    "technical_analysis_write_attempted": False,
                    "classification": payload["classification"],
                    "computation_classification": payload["computation_classification"],
                    "indicator_count": payload["indicator_count"],
                    "computed_function_count": payload["computed_function_count"],
                    "candle_count": payload["candle_count"],
                    "last_candle_ts_ms": payload["last_candle_ts_ms"],
                    "source_exact_payload_sha256": payload["source_exact_payload_sha256"],
                    "calculation_row_count": payload["calculation_row_count"],
                    "candidate_written": candidate_written,
                    "consumer_eligible": False,
                    "trainer_consumable": False,
                }
            )

    status = {
        "schema_version": "v2_full_talib_ta_loop_status_v2",
        "worker_id": WORKER_ID,
        "payload_schema_version": FULL_TALIB_TA_CLOSED_CANDIDATE_SCHEMA_VERSION,
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
        "required_contiguous_source_rows": (FULL_TALIB_TA_REQUIRED_CONTIGUOUS_ROWS),
        "source_key_pattern": ("v2:market:ohlcv_closed:binance:{symbol}:{timeframe}"),
        "reads_live_ohlcv": False,
        "merges_live_ohlcv": False,
        "uses_compact_or_feature_snapshot_fallback": False,
        "technical_analysis_owner": "v2_feature_pipeline_native_loop",
        "technical_analysis_write_attempted": False,
        "derived_record_available_at_published": True,
        "derived_record_available_at_semantics": (
            "MAX_SOURCE_AVAILABLE_AT_PRODUCER_GENERATED_AT"
        ),
        "postcommit_available_at_claimed": False,
        "postcommit_publication_observed": False,
        "consumer_eligible": False,
        "trainer_consumable": False,
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
    candidate_write_count = sum(row.get("candidate_written") is True for row in key_results)
    ignored_discovered_symbols = sorted(set(discovered) - set(all_symbols))
    status["discovered_canonical_symbols"] = sorted(discovered)[:200]
    status["discovered_canonical_symbol_count"] = len(discovered)
    status["unauthorized_discovered_symbols_ignored"] = ignored_discovered_symbols[:200]
    status["unauthorized_discovered_symbol_ignored_count"] = len(ignored_discovered_symbols)
    status["redis_discovery_grants_symbol_authority"] = False
    status["candidate_write_acknowledged_count"] = candidate_write_count
    if redis_client is None:
        status["classification"] = "BLOCKED_REDIS_UNAVAILABLE"
    elif candidate_write_count:
        status["classification"] = "V2_FULL_TALIB_TA_CLOSED_CANDIDATES_WRITTEN_NONCONSUMABLE"
    elif key_results:
        status["classification"] = "BLOCKED_NO_VALID_CLOSED_TA_CANDIDATES"
    else:
        status["classification"] = "BLOCKED_NO_CANONICAL_CLOSED_OHLCV_INPUTS"

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
