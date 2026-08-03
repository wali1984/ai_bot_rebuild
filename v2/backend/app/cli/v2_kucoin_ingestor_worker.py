"""V2 native KuCoin public-data ingestor worker (paper-only).

Emits a config-only payload at
v2/frontend/public/operator_runtime/v2_kucoin_ingestor/latest/
v2_kucoin_ingestor_status.json.

No order placement. No old Redis writes.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from bisect import bisect_left
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_ingestors.kucoin import (
    build_ingestor_config,
    classify_reconnect_attempt,
    kucoin_invariants_snapshot,
    v2_to_kucoin_futures_symbol,
    v2_to_kucoin_spot_symbol,
)
from v2.backend.app.services.v2_symbol_runtime_universe import (
    BASELINE_25_SYMBOLS,
    resolve_symbols,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_PAYLOAD_PATH = (
    REPO_ROOT
    / "v2/frontend/public/operator_runtime/v2_kucoin_ingestor/latest/v2_kucoin_ingestor_status.json"
)
DEFAULT_SYMBOLS = tuple(BASELINE_25_SYMBOLS)
V2_REDIS_PREFIX = "v2:"
HTTP_TIMEOUT_S = 8.0
DEFAULT_PUBLIC_REST_REQUEST_BUDGET = 240
DEFAULT_PUBLIC_REST_WEIGHT_BUDGET = 1_000
DEFAULT_PUBLIC_REST_CYCLE_DEADLINE_SECONDS = 120
EXPECTED_SERVICE_SLEEP_SECONDS = 300
PREFERRED_EVERY_CYCLE_SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
ROTATION_CURSOR_KEY = "v2:market:kucoin:rotation_cursor"
COVERAGE_LEDGER_KEY = "v2:market:kucoin:coverage_ledger"
ROTATION_STATE_TTL_SECONDS = 7 * 24 * 60 * 60
ROTATION_HISTORY_LIMIT = 12
MAX_COVERAGE_LEDGER_SYMBOLS = 512
SUPPORTED_FUNDING_INTERVAL_HOURS = frozenset({1, 4, 8})
MAX_ABS_FUNDING_RATE_PER_INTERVAL = 0.05
KUCOIN_SPOT_MARKET = "spot"
KUCOIN_FUTURES_MARKET = "linear_perpetual"
TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1_800,
    "1h": 3_600,
    "4h": 14_400,
    "1d": 86_400,
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _iso_from_ms(value: int | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
    except (OSError, OverflowError, ValueError):
        return None


def _observation_clocks(
    *,
    event_time_ms: int | None,
    ingested_at_ms: int,
    feature_cutoff_ms: int | None = None,
) -> dict[str, Any]:
    """Return explicit PIT clocks without inventing a provider event clock."""
    cutoff_ms = feature_cutoff_ms if feature_cutoff_ms is not None else event_time_ms
    if cutoff_ms is None:
        # A provider snapshot with no source event clock only becomes usable when
        # the response is observed locally.  This is not labelled event_time.
        cutoff_ms = ingested_at_ms
    temporal_valid = cutoff_ms <= ingested_at_ms and (
        event_time_ms is None or event_time_ms <= ingested_at_ms
    )
    return {
        "event_time": _iso_from_ms(event_time_ms),
        "event_time_ms": event_time_ms,
        "ingested_at": _iso_from_ms(ingested_at_ms),
        "ingested_at_ms": ingested_at_ms,
        "available_at": _iso_from_ms(ingested_at_ms),
        "available_at_ms": ingested_at_ms,
        "feature_cutoff": _iso_from_ms(cutoff_ms),
        "feature_cutoff_ms": cutoff_ms,
        "temporal_contract_valid": temporal_valid,
    }


def _http_get_json(base: str, path: str, params: dict[str, Any] | None = None) -> tuple[int, Any]:
    query = urllib.parse.urlencode(params or {})
    url = f"{base.rstrip('/')}{path}"
    if query:
        url = f"{url}?{query}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ai-bot-v2-kucoin-ingestor-readonly"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as response:
            body = response.read().decode("utf-8")
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
            data = json.loads(body) if body else None
        except Exception:
            data = None
        return int(exc.code), data
    except Exception:
        return 599, None
    try:
        data = json.loads(body) if body else None
    except Exception:
        data = body
    return status, data


def _kucoin_data(response: Any) -> Any:
    if isinstance(response, dict):
        code = response.get("code")
        if code is not None and str(code) != "200000":
            return None
        if "data" in response:
            return response.get("data")
    return response


def _kucoin_code(response: Any) -> str | None:
    if isinstance(response, dict) and response.get("code") is not None:
        return str(response.get("code"))
    return None


def _connect_redis():
    try:
        import redis  # type: ignore
    except Exception:
        return None
    try:
        client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
        )
        client.ping()
        return client
    except Exception:
        return None


def _safe_write(redis_client: Any, key: str, payload: Any, *, ex: int = 600) -> bool:
    if redis_client is None:
        return False
    if not key.startswith(V2_REDIS_PREFIX):
        raise ValueError(f"refused non-V2 Redis key: {key!r}")
    body = json.dumps(payload, sort_keys=True, default=str)
    redis_client.set(key, body, ex=int(ex))
    return True


def _read_redis_json_object(redis_client: Any, key: str) -> dict[str, Any] | None:
    """Read bounded worker state without allowing malformed Redis data to steer it."""
    if redis_client is None or not key.startswith(V2_REDIS_PREFIX):
        return None
    try:
        raw = redis_client.get(key)
        decoded = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    except Exception:
        return None
    return decoded if isinstance(decoded, dict) else None


def _load_rotation_cursor(redis_client: Any) -> dict[str, Any] | None:
    state = _read_redis_json_object(redis_client, ROTATION_CURSOR_KEY)
    if not isinstance(state, dict):
        return None
    next_symbol = str(state.get("next_symbol") or "").upper()
    last_cycle_started_ms = state.get("last_cycle_started_ms")
    if next_symbol and _v2_usdt_base(next_symbol) is None:
        return None
    if last_cycle_started_ms is not None and (
        not isinstance(last_cycle_started_ms, int) or last_cycle_started_ms <= 0
    ):
        return None
    return state


def _load_coverage_ledger(redis_client: Any) -> dict[str, Any] | None:
    ledger = _read_redis_json_object(redis_client, COVERAGE_LEDGER_KEY)
    if not isinstance(ledger, dict):
        return None
    entries = ledger.get("symbols")
    if not isinstance(entries, dict) or len(entries) > MAX_COVERAGE_LEDGER_SYMBOLS:
        return None
    return ledger


def _parse_kline(
    raw: Any,
    *,
    symbol: str,
    kucoin_symbol: str,
    timeframe: str,
    source: str = "kucoin_public_rest",
    observed_at_ms: int | None = None,
    available_at_ms: int | None = None,
) -> dict[str, Any] | None:
    if not isinstance(raw, list) or not raw:
        return None
    interval_seconds = TIMEFRAME_SECONDS.get(timeframe)
    if interval_seconds is None:
        return None
    finality_cutoff_ms = _now_ms() if observed_at_ms is None else int(observed_at_ms)
    ingested_ms = (
        finality_cutoff_ms if available_at_ms is None else int(available_at_ms)
    )
    interval_ms = interval_seconds * 1000
    closed_candidates: list[tuple[int, list[Any]]] = []
    for candidate in raw:
        if not isinstance(candidate, list) or len(candidate) < 6:
            continue
        timestamp_ms = _epoch_ms(candidate[0])
        if timestamp_ms is None:
            continue
        # KuCoin kline timestamps are bucket-open times.  The newest REST row
        # is commonly still forming and must never become a feature.
        close_ms = timestamp_ms + interval_ms
        if (
            close_ms <= finality_cutoff_ms
            and close_ms >= finality_cutoff_ms - interval_ms
        ):
            closed_candidates.append((timestamp_ms, candidate))
    if not closed_candidates:
        return None
    timestamp_ms, row = max(closed_candidates, key=lambda item: item[0])
    close_time_ms = timestamp_ms + interval_ms
    try:
        futures = "futures" in source
        if futures:
            open_px = float(row[1])
            high_px = float(row[2])
            low_px = float(row[3])
            close_px = float(row[4])
        else:
            open_px = float(row[1])
            close_px = float(row[2])
            high_px = float(row[3])
            low_px = float(row[4])
        volume = float(row[5])
        if not _valid_ohlc(
            open_px=open_px,
            high_px=high_px,
            low_px=low_px,
            close_px=close_px,
            volume=volume,
        ):
            return None
        turnover = _safe_float(row[6]) if len(row) > 6 else None
        clocks = _observation_clocks(
            event_time_ms=close_time_ms,
            ingested_at_ms=ingested_ms,
            feature_cutoff_ms=close_time_ms,
        )
        return {
            "symbol": symbol,
            "kucoin_symbol": kucoin_symbol,
            "venue": "kucoin",
            "market_type": KUCOIN_FUTURES_MARKET if futures else KUCOIN_SPOT_MARKET,
            "instrument_type": "linear_perpetual" if futures else "spot",
            "timeframe": timeframe,
            # Backward-compatible timestamp is explicitly the bar-open clock.
            "timestamp": timestamp_ms,
            "timestamp_semantics": "bar_open_time_ms",
            "bar_open_time": _iso_from_ms(timestamp_ms),
            "bar_open_time_ms": timestamp_ms,
            "bar_close_time": _iso_from_ms(close_time_ms),
            "bar_close_time_ms": close_time_ms,
            "is_final": True,
            "finality_cutoff": _iso_from_ms(finality_cutoff_ms),
            "finality_cutoff_ms": finality_cutoff_ms,
            "closed_bar_age_seconds": round(
                max(0, finality_cutoff_ms - close_time_ms) / 1000.0,
                3,
            ),
            "open": open_px,
            "close": close_px,
            "high": high_px,
            "low": low_px,
            "volume": volume,
            "volume_unit": "contracts" if futures else "base_asset",
            "turnover": turnover,
            "turnover_unit": "quote_asset",
            "source": source,
            "feature_eligible": bool(clocks["temporal_contract_valid"]),
            **clocks,
        }
    except (TypeError, ValueError, OverflowError):
        return None


def _valid_ohlc(*, open_px: float, high_px: float, low_px: float, close_px: float, volume: float) -> bool:
    values = (open_px, high_px, low_px, close_px, volume)
    if not all(value == value and value not in (float("inf"), float("-inf")) for value in values):
        return False
    if min(open_px, high_px, low_px, close_px) <= 0:
        return False
    if volume < 0:
        return False
    return low_px <= open_px <= high_px and low_px <= close_px <= high_px and low_px <= high_px


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _epoch_ms(value: Any) -> int | None:
    numeric = _safe_float(value)
    if numeric is None or numeric <= 0:
        return None
    if numeric >= 1_000_000_000_000_000:
        return int(numeric / 1_000_000)
    if numeric >= 1_000_000_000_000:
        return int(numeric)
    if numeric >= 1_000_000_000:
        return int(numeric * 1000)
    return None


def _has_any_number(payload: dict[str, Any] | None, keys: tuple[str, ...]) -> bool:
    if not isinstance(payload, dict):
        return False
    return any(_safe_float(payload.get(key)) is not None for key in keys)


def _has_ticker_values(payload: dict[str, Any] | None) -> bool:
    return _has_any_number(payload, ("bid", "ask", "last", "size", "volume_24h"))


def _ticker_values_valid(payload: dict[str, Any]) -> bool:
    bid = _safe_float(payload.get("bid"))
    ask = _safe_float(payload.get("ask"))
    last = _safe_float(payload.get("last"))
    size = _safe_float(payload.get("size"))
    volume = _safe_float(payload.get("volume_24h"))
    # A last-trade-only snapshot is valid price evidence, but a partially
    # populated BBO is not an executable spread and must fail closed.
    if (bid is None) != (ask is None):
        return False
    if bid is not None and (bid <= 0 or ask is None or ask <= 0 or bid >= ask):
        return False
    if last is not None and last <= 0:
        return False
    if bid is None and last is None:
        return False
    return not (
        (size is not None and size < 0)
        or (volume is not None and volume < 0)
    )


def _has_contract_values(payload: dict[str, Any] | None) -> bool:
    return _has_any_number(payload, ("open_interest", "mark_price", "index_price"))


def _has_funding_values(payload: dict[str, Any] | None) -> bool:
    return _has_any_number(payload, ("rate", "predicted_rate"))


def _has_orderbook_values(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    return bool(payload.get("bids")) and bool(payload.get("asks"))


def _row_has_public_data(row: dict[str, Any]) -> bool:
    return (
        _has_ticker_values(row.get("ticker"))
        or bool(row.get("klines"))
        or _has_funding_values(row.get("funding"))
        or _has_contract_values(row.get("contract"))
        or _has_orderbook_values(row.get("orderbook20"))
    )


def _public_rest_summary(fetch_payload: dict[str, Any] | None) -> dict[str, Any]:
    rows = fetch_payload.get("rows", []) if isinstance(fetch_payload, dict) else []
    typed_rows = [row for row in rows if isinstance(row, dict)]
    code_counts: dict[str, int] = {}
    for row in typed_rows:
        endpoint_codes = row.get("endpoint_codes")
        if not isinstance(endpoint_codes, dict):
            continue
        for code in endpoint_codes.values():
            if code is None:
                continue
            text = str(code)
            code_counts[text] = code_counts.get(text, 0) + 1
    return {
        "rows_count": len(typed_rows),
        "row_success_count": sum(1 for row in typed_rows if _row_has_public_data(row)),
        "ticker_rows": sum(1 for row in typed_rows if _has_ticker_values(row.get("ticker"))),
        "kline_rows": sum(1 for row in typed_rows if bool(row.get("klines"))),
        "funding_rows": sum(1 for row in typed_rows if _has_funding_values(row.get("funding"))),
        "contract_rows": sum(1 for row in typed_rows if _has_contract_values(row.get("contract"))),
        "orderbook_rows": sum(1 for row in typed_rows if _has_orderbook_values(row.get("orderbook20"))),
        "endpoint_code_counts": dict(sorted(code_counts.items())),
        "request_count": fetch_payload.get("request_count") if isinstance(fetch_payload, dict) else 0,
        "request_budget": fetch_payload.get("request_budget") if isinstance(fetch_payload, dict) else 0,
        "request_budget_exhausted": bool(
            fetch_payload.get("request_budget_exhausted")
        ) if isinstance(fetch_payload, dict) else False,
        "symbols_authorized": fetch_payload.get("symbols_authorized", 0)
        if isinstance(fetch_payload, dict)
        else 0,
        "symbols_skipped_budget_count": fetch_payload.get("symbols_skipped_budget_count", 0)
        if isinstance(fetch_payload, dict)
        else 0,
        "symbols_unsupported_count": fetch_payload.get("symbols_unsupported_count", 0)
        if isinstance(fetch_payload, dict)
        else 0,
    }


def _parse_spot_ticker(
    data: Any,
    *,
    symbol: str,
    spot_symbol: str,
    ingested_at_ms: int | None = None,
) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    observed_ms = _now_ms() if ingested_at_ms is None else int(ingested_at_ms)
    event_ms = _epoch_ms(data.get("time"))
    clocks = _observation_clocks(event_time_ms=event_ms, ingested_at_ms=observed_ms)
    payload = {
        "symbol": symbol,
        "kucoin_symbol": spot_symbol,
        "venue": "kucoin",
        "market_type": KUCOIN_SPOT_MARKET,
        "instrument_type": "spot",
        "bid": _safe_float(data.get("bestBid")),
        "ask": _safe_float(data.get("bestAsk")),
        "last": _safe_float(data.get("price")),
        "size": _safe_float(data.get("size")),
        "volume_24h": _safe_float(data.get("vol")),
        "timestamp": event_ms if event_ms is not None else observed_ms,
        "timestamp_semantics": "provider_event_time_ms" if event_ms is not None else "local_observation_time_ms",
        "source": "kucoin_spot_public_rest",
        "feature_eligible": bool(clocks["temporal_contract_valid"]),
        **clocks,
    }
    return payload if _ticker_values_valid(payload) and clocks["temporal_contract_valid"] else None


def _parse_futures_ticker(
    data: Any,
    *,
    symbol: str,
    futures_symbol: str,
    ingested_at_ms: int | None = None,
) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    observed_ms = _now_ms() if ingested_at_ms is None else int(ingested_at_ms)
    event_ms = _epoch_ms(data.get("ts"))
    clocks = _observation_clocks(event_time_ms=event_ms, ingested_at_ms=observed_ms)
    payload = {
        "symbol": symbol,
        "kucoin_symbol": futures_symbol,
        "venue": "kucoin",
        "market_type": KUCOIN_FUTURES_MARKET,
        "instrument_type": "linear_perpetual",
        "bid": _safe_float(data.get("bestBidPrice")),
        "ask": _safe_float(data.get("bestAskPrice")),
        "last": _safe_float(
            data.get("price")
            if data.get("price") is not None
            else data.get("lastTradePrice")
        ),
        "size": _safe_float(data.get("size")),
        "volume_24h": _safe_float(data.get("volumeOf24h")),
        "timestamp": event_ms if event_ms is not None else observed_ms,
        "timestamp_semantics": "provider_event_time_ms" if event_ms is not None else "local_observation_time_ms",
        "source": "kucoin_futures_public_rest",
        "feature_eligible": bool(clocks["temporal_contract_valid"]),
        **clocks,
    }
    return payload if _ticker_values_valid(payload) and clocks["temporal_contract_valid"] else None


def _funding_interval_hours(data: dict[str, Any]) -> tuple[int, str] | None:
    """Resolve KuCoin's authority interval, which is expressed in milliseconds."""
    source_field = (
        "currentFundingRateGranularity"
        if data.get("currentFundingRateGranularity") is not None
        else "fundingRateGranularity"
    )
    raw = data.get(source_field)
    milliseconds = _safe_float(raw)
    hour_ms = 60 * 60 * 1000
    if (
        milliseconds is None
        or not milliseconds.is_integer()
        or int(milliseconds) % hour_ms != 0
    ):
        return None
    hours = int(milliseconds) // hour_ms
    if hours not in SUPPORTED_FUNDING_INTERVAL_HOURS:
        return None
    return hours, source_field


def _funding_rates_in_domain(
    *,
    rate: float | None,
    predicted: float | None,
    cap: float | None,
    floor: float | None,
    cap_present: bool,
    floor_present: bool,
) -> bool:
    if rate is None and predicted is None:
        return False
    if (cap_present and cap is None) or (floor_present and floor is None):
        return False
    if cap is not None and cap < 0:
        return False
    if floor is not None and floor > 0:
        return False
    if cap is not None and floor is not None and floor > cap:
        return False
    for value in (rate, predicted):
        if value is None:
            continue
        # Apply the same conservative fallback bound used by the provider
        # contract when an authority row omits its tighter instrument bounds.
        if abs(value) > MAX_ABS_FUNDING_RATE_PER_INTERVAL:
            return False
        if cap is not None and value > cap:
            return False
        if floor is not None and value < floor:
            return False
    return True


def _parse_funding(
    data: Any,
    *,
    symbol: str,
    futures_symbol: str,
    source: str,
    ingested_at_ms: int | None = None,
) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    observed_ms = _now_ms() if ingested_at_ms is None else int(ingested_at_ms)
    interval = _funding_interval_hours(data)
    if interval is None:
        return None
    interval_hours, interval_source_field = interval
    rate = (
        _safe_float(data.get("fundingRate"))
        if data.get("fundingRate") is not None
        else _safe_float(
            data.get("value")
            if data.get("value") is not None
            else (
                data.get("fundingFeeRate")
                if data.get("fundingFeeRate") is not None
                else data.get("nextFundingRate")
            )
        )
    )
    predicted = (
        _safe_float(data.get("predictedFundingRate"))
        if data.get("predictedFundingRate") is not None
        else _safe_float(
            data.get("predictedValue")
            if data.get("predictedValue") is not None
            else (
                data.get("predictedFundingFeeRate")
                if data.get("predictedFundingFeeRate") is not None
                else data.get("predictedFundingRate")
            )
        )
    )
    cap_present = data.get("fundingRateCap") is not None
    floor_present = data.get("fundingRateFloor") is not None
    cap = _safe_float(data.get("fundingRateCap"))
    floor = _safe_float(data.get("fundingRateFloor"))
    if not _funding_rates_in_domain(
        rate=rate,
        predicted=predicted,
        cap=cap,
        floor=floor,
        cap_present=cap_present,
        floor_present=floor_present,
    ):
        return None
    event_ms = _epoch_ms(data.get("timePoint") or data.get("timepoint"))
    clocks = _observation_clocks(event_time_ms=event_ms, ingested_at_ms=observed_ms)
    rate_per_hour = rate / interval_hours if rate is not None else None
    predicted_per_hour = predicted / interval_hours if predicted is not None else None
    payload = {
        "symbol": symbol,
        "kucoin_futures_symbol": futures_symbol,
        "venue": "kucoin",
        "market_type": KUCOIN_FUTURES_MARKET,
        "instrument_type": "linear_perpetual",
        "rate": rate,
        "predicted_rate": predicted,
        "rate_unit": "fraction_per_funding_interval",
        "predicted_rate_unit": "fraction_per_funding_interval",
        "funding_interval_hours": interval_hours,
        "funding_interval_unit": "hours",
        "funding_interval_source_field": interval_source_field,
        "funding_interval_source_unit": "milliseconds",
        "rate_per_hour": rate_per_hour,
        "predicted_rate_per_hour": predicted_per_hour,
        "rate_per_hour_unit": "fraction_per_hour",
        "raw_interval_rates_comparable_across_contracts": False,
        "next_funding_time": data.get("nextFundingRateDateTime") or data.get("nextFundingTime"),
        "next_funding_countdown_ms": data.get("nextFundingRateTime"),
        "funding_time": data.get("fundingTime"),
        "funding_rate_cap": cap,
        "funding_rate_floor": floor,
        "funding_rate_bound_unit": "fraction_per_funding_interval",
        "funding_rate_cap_per_hour": cap / interval_hours if cap is not None else None,
        "funding_rate_floor_per_hour": floor / interval_hours if floor is not None else None,
        "timestamp": event_ms if event_ms is not None else observed_ms,
        "timestamp_semantics": "provider_event_time_ms" if event_ms is not None else "local_observation_time_ms",
        "source": source,
        "feature_eligible": bool(clocks["temporal_contract_valid"]),
        **clocks,
    }
    return payload if clocks["temporal_contract_valid"] else None


def _parse_contract(
    data: Any,
    *,
    symbol: str,
    futures_symbol: str,
    ingested_at_ms: int | None = None,
) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    observed_ms = _now_ms() if ingested_at_ms is None else int(ingested_at_ms)
    clocks = _observation_clocks(event_time_ms=None, ingested_at_ms=observed_ms)
    open_interest = _safe_float(data.get("openInterest"))
    mark_price = _safe_float(data.get("markPrice"))
    index_price = _safe_float(data.get("indexPrice"))
    multiplier = _safe_float(data.get("multiplier"))
    for field, parsed in (
        ("openInterest", open_interest),
        ("markPrice", mark_price),
        ("indexPrice", index_price),
        ("multiplier", multiplier),
    ):
        if data.get(field) is not None and parsed is None:
            return None
    # OI is only useful as a validated contract observation when its price
    # references and base-asset multiplier are present in the same authority
    # snapshot. Partial authority rows must not satisfy component coverage.
    if any(
        value is None
        for value in (open_interest, mark_price, index_price, multiplier)
    ):
        return None
    if open_interest < 0:
        return None
    if mark_price <= 0 or index_price <= 0:
        return None
    if multiplier <= 0:
        return None
    payload = {
        "symbol": symbol,
        "kucoin_futures_symbol": futures_symbol,
        "venue": "kucoin",
        "market_type": KUCOIN_FUTURES_MARKET,
        "instrument_type": "linear_perpetual",
        "open_interest": open_interest,
        "open_interest_unit": "contracts",
        "mark_price": mark_price,
        "index_price": index_price,
        "contract_multiplier": multiplier,
        "contract_multiplier_unit": "base_asset_per_contract",
        "contract_multiplier_base_currency": data.get("baseCurrency"),
        "base_currency": data.get("baseCurrency"),
        "quote_currency": data.get("quoteCurrency"),
        "settle_currency": data.get("settleCurrency"),
        "market_stage": data.get("marketStage"),
        "timestamp": observed_ms,
        "timestamp_semantics": "local_observation_time_ms",
        "source": "kucoin_futures_public_rest",
        "feature_eligible": bool(clocks["temporal_contract_valid"]),
        **clocks,
    }
    return payload if _has_contract_values(payload) else None


def _clean_orderbook_levels(value: Any) -> list[list[float]]:
    out: list[list[float]] = []
    if not isinstance(value, list):
        return out
    for row in value[:20]:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        price = _safe_float(row[0])
        size = _safe_float(row[1])
        if price is None or size is None or price <= 0 or size < 0:
            continue
        out.append([price, size])
    return out


def _parse_orderbook(
    data: Any,
    *,
    symbol: str,
    kucoin_symbol: str,
    source: str,
    ingested_at_ms: int | None = None,
) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    observed_ms = _now_ms() if ingested_at_ms is None else int(ingested_at_ms)
    event_ms = _epoch_ms(data.get("time") or data.get("ts"))
    clocks = _observation_clocks(event_time_ms=event_ms, ingested_at_ms=observed_ms)
    bids = _clean_orderbook_levels(data.get("bids"))
    asks = _clean_orderbook_levels(data.get("asks"))
    if bids and asks and max(level[0] for level in bids) >= min(level[0] for level in asks):
        return None
    futures = "futures" in source
    payload = {
        "symbol": symbol,
        "kucoin_symbol": kucoin_symbol,
        "venue": "kucoin",
        "market_type": KUCOIN_FUTURES_MARKET if futures else KUCOIN_SPOT_MARKET,
        "instrument_type": "linear_perpetual" if futures else "spot",
        "bids": bids,
        "asks": asks,
        "timestamp": event_ms if event_ms is not None else observed_ms,
        "timestamp_semantics": "provider_event_time_ms" if event_ms is not None else "local_observation_time_ms",
        "source": source,
        "feature_eligible": bool(clocks["temporal_contract_valid"]),
        **clocks,
    }
    return payload if bids and asks and clocks["temporal_contract_valid"] else None


def _authority_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        for name in ("items", "contracts", "symbols"):
            rows = data.get(name)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        if data.get("symbol"):
            return [data]
    return []


def _v2_usdt_base(symbol: str) -> str | None:
    value = str(symbol or "").strip().upper()
    if not value.endswith("USDT"):
        return None
    base = value[:-4]
    if not base or base.endswith("USDT") or not base.isalnum():
        return None
    return base


def _spot_authority_match(symbol: str, candidate: str, row: dict[str, Any]) -> bool:
    base = _v2_usdt_base(symbol)
    return bool(
        base
        and str(row.get("symbol") or "").upper() == candidate
        and str(row.get("baseCurrency") or "").upper() == base
        and str(row.get("quoteCurrency") or "").upper() == "USDT"
        and row.get("enableTrading") is True
    )


def _futures_authority_match(symbol: str, candidate: str, row: dict[str, Any]) -> bool:
    base = _v2_usdt_base(symbol)
    expected_base = "XBT" if base == "BTC" else base
    stage = str(row.get("marketStage") or "").upper()
    status = str(row.get("status") or "").upper()
    return bool(
        expected_base
        and str(row.get("symbol") or "").upper() == candidate
        and str(row.get("baseCurrency") or "").upper() == expected_base
        and str(row.get("quoteCurrency") or "").upper() == "USDT"
        and str(row.get("settleCurrency") or "").upper() == "USDT"
        and row.get("isInverse") is False
        and stage == "NORMAL"
        and status == "OPEN"
    )


def _kucoin_public_request_weight(path: str) -> int:
    if path == "/api/v2/symbols":
        return 4
    if path == "/api/v1/contracts/active":
        return 3
    if path in {"/api/v1/market/candles", "/api/v1/kline/query"}:
        return 3
    if path == "/api/v1/market/orderbook/level2_20":
        return 2
    if path == "/api/v1/level2/depth20":
        return 5
    if path in {"/api/v1/market/orderbook/level1", "/api/v1/ticker"}:
        return 2
    if path.startswith("/api/v1/funding-rate/"):
        return 2
    return 1


def _bounded_positive_number_history(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    history: list[float] = []
    for item in value[-ROTATION_HISTORY_LIMIT:]:
        parsed = _safe_float(item)
        if parsed is not None and parsed > 0:
            history.append(round(parsed, 3))
    return history


def _rotation_start_index(
    rotating_symbols: list[str],
    rotation_cursor: dict[str, Any] | None,
) -> int:
    if not rotating_symbols:
        return 0
    next_symbol = str((rotation_cursor or {}).get("next_symbol") or "").upper()
    if not next_symbol:
        return 0
    exact_index = {symbol: index for index, symbol in enumerate(rotating_symbols)}.get(
        next_symbol
    )
    if exact_index is not None:
        return exact_index
    # The saved anchor may have left the dynamic universe. Because the rotating
    # universe is sorted, its insertion point is the first not-yet-passed
    # successor and does not reset the cursor to an unrelated wall-clock batch.
    return bisect_left(rotating_symbols, next_symbol) % len(rotating_symbols)


def _component_payloads(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    components: dict[str, dict[str, Any]] = {}
    for name in ("ticker", "funding", "contract", "orderbook20"):
        payload = row.get(name)
        if isinstance(payload, dict) and payload.get("temporal_contract_valid") is True:
            components[name] = payload
    klines = row.get("klines")
    if isinstance(klines, dict):
        for timeframe, payload in klines.items():
            if isinstance(payload, dict) and payload.get("temporal_contract_valid") is True:
                components[f"kline:{timeframe}"] = payload
    return components


def _expected_components(
    *,
    primary_market_type: str,
    timeframes: tuple[str, ...],
) -> list[str]:
    names = ["ticker", "orderbook20"]
    if primary_market_type == KUCOIN_FUTURES_MARKET:
        names.extend(("contract", "funding"))
    names.extend(f"kline:{timeframe}" for timeframe in timeframes if timeframe in TIMEFRAME_SECONDS)
    return sorted(set(names))


def _positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _update_component_success(
    prior: dict[str, Any] | None,
    *,
    success_at_ms: int,
) -> dict[str, Any]:
    previous = prior if isinstance(prior, dict) else {}
    previous_last = _positive_int(previous.get("last_success_at_ms"))
    observation_count = _positive_int(previous.get("successful_observation_count")) or 0
    max_revisit = _safe_float(previous.get("max_observed_revisit_seconds"))
    recent_revisits = _bounded_positive_number_history(
        previous.get("recent_observed_revisit_seconds")
    )
    # Backward-compatible migration: the old schema retained only the latest
    # and lifetime maximum. Seed the rolling window from the latest observation
    # so a genuine slow revisit remains unsafe until timely observations age it
    # out, while an ancient lifetime maximum cannot block recovery forever.
    if not recent_revisits:
        previous_observed = _safe_float(previous.get("observed_revisit_seconds"))
        if previous_observed is not None and previous_observed > 0:
            recent_revisits = [round(previous_observed, 3)]
    if previous_last is not None and success_at_ms < previous_last:
        # Never move a last-success clock backwards if a delayed response or a
        # malformed test fixture arrives out of order.
        return dict(previous)
    out = {
        "last_success_at_ms": success_at_ms,
        "last_success_at": _iso_from_ms(success_at_ms),
        "previous_success_at_ms": previous_last,
        "successful_observation_count": min(observation_count + 1, 1_000_000_000),
        "observed_revisit_seconds": None,
        "max_observed_revisit_seconds": max_revisit,
        "recent_observed_revisit_seconds": recent_revisits,
    }
    if previous_last is not None and success_at_ms > previous_last:
        revisit = round((success_at_ms - previous_last) / 1000.0, 3)
        out["observed_revisit_seconds"] = revisit
        out["max_observed_revisit_seconds"] = max(max_revisit or 0.0, revisit)
        out["recent_observed_revisit_seconds"] = [
            *recent_revisits,
            revisit,
        ][-ROTATION_HISTORY_LIMIT:]
    elif previous_last == success_at_ms:
        # Duplicate authority clocks within one cycle are not a second revisit.
        out["successful_observation_count"] = observation_count
        out["previous_success_at_ms"] = previous.get("previous_success_at_ms")
        out["observed_revisit_seconds"] = previous.get("observed_revisit_seconds")
    return out


def _build_coverage_ledger(
    *,
    previous_ledger: dict[str, Any] | None,
    authorized_products: list[tuple[str, str]],
    rows: list[dict[str, Any]],
    timeframes: tuple[str, ...],
    finished_ms: int,
    redis_ttl_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    previous_symbols = (
        previous_ledger.get("symbols", {})
        if isinstance(previous_ledger, dict)
        and isinstance(previous_ledger.get("symbols"), dict)
        else {}
    )
    bounded_products = sorted(authorized_products)[:MAX_COVERAGE_LEDGER_SYMBOLS]
    truncated = len(authorized_products) > MAX_COVERAGE_LEDGER_SYMBOLS
    rows_by_symbol = {
        str(row.get("symbol") or "").upper(): row
        for row in rows
        if isinstance(row, dict) and row.get("symbol")
    }
    symbol_entries: dict[str, Any] = {}
    for symbol, market_type in bounded_products:
        expected = _expected_components(
            primary_market_type=market_type,
            timeframes=timeframes,
        )
        previous_entry = previous_symbols.get(symbol)
        previous_components = (
            previous_entry.get("components", {})
            if isinstance(previous_entry, dict)
            and isinstance(previous_entry.get("components"), dict)
            else {}
        )
        components = {
            name: value
            for name, value in previous_components.items()
            if name in expected and isinstance(value, dict)
        }
        row = rows_by_symbol.get(symbol)
        if row is not None:
            for name, payload in _component_payloads(row).items():
                if name not in expected:
                    continue
                success_at_ms = _positive_int(payload.get("available_at_ms")) or finished_ms
                components[name] = _update_component_success(
                    components.get(name),
                    success_at_ms=success_at_ms,
                )
        entry = {
            "primary_market_type": market_type,
            "expected_components": expected,
            "components": components,
            "last_attempt_at_ms": (
                finished_ms
                if row is not None
                else (
                    previous_entry.get("last_attempt_at_ms")
                    if isinstance(previous_entry, dict)
                    else None
                )
            ),
            "last_schedule_complete_at_ms": (
                finished_ms
                if row is not None and row.get("rotation_schedule_covered") is True
                else (
                    previous_entry.get("last_schedule_complete_at_ms")
                    if isinstance(previous_entry, dict)
                    else None
                )
            ),
        }
        symbol_entries[symbol] = entry

    total_expected = 0
    success_count = 0
    observed_revisit_count = 0
    expired_count = 0
    max_observed_revisit = 0.0
    max_recent_observed_revisit = 0.0
    oldest_success_age = 0.0
    for entry in symbol_entries.values():
        for name in entry["expected_components"]:
            total_expected += 1
            component = entry["components"].get(name)
            if not isinstance(component, dict):
                continue
            last_success_ms = _positive_int(component.get("last_success_at_ms"))
            if last_success_ms is None:
                continue
            success_count += 1
            age = max(0.0, (finished_ms - last_success_ms) / 1000.0)
            oldest_success_age = max(oldest_success_age, age)
            if age >= redis_ttl_seconds:
                expired_count += 1
            observed = _safe_float(component.get("observed_revisit_seconds"))
            if observed is not None and observed > 0:
                observed_revisit_count += 1
            maximum = _safe_float(component.get("max_observed_revisit_seconds"))
            if maximum is not None:
                max_observed_revisit = max(max_observed_revisit, maximum)
            recent_revisits = _bounded_positive_number_history(
                component.get("recent_observed_revisit_seconds")
            )
            if not recent_revisits:
                latest_revisit = _safe_float(component.get("observed_revisit_seconds"))
                if latest_revisit is not None and latest_revisit > 0:
                    recent_revisits = [latest_revisit]
            if recent_revisits:
                max_recent_observed_revisit = max(
                    max_recent_observed_revisit,
                    max(recent_revisits),
                )

    ledger = {
        "schema_version": "v2_kucoin_component_coverage_v2",
        "updated_at_ms": finished_ms,
        "updated_at": _iso_from_ms(finished_ms),
        "current_authorized_universe_size": len(authorized_products),
        "bounded_symbol_count": len(symbol_entries),
        "truncated": truncated,
        "symbols": symbol_entries,
    }
    summary = {
        "expected_component_count": total_expected,
        "components_with_last_success": success_count,
        "components_with_observed_revisit": observed_revisit_count,
        "missing_component_count": max(0, total_expected - success_count),
        "expired_component_count": expired_count,
        "oldest_success_age_seconds": round(oldest_success_age, 3),
        "max_observed_component_revisit_seconds": round(max_observed_revisit, 3),
        "max_recent_observed_component_revisit_seconds": round(
            max_recent_observed_revisit,
            3,
        ),
        "recent_revisit_window_size": ROTATION_HISTORY_LIMIT,
        "ledger_truncated": truncated,
    }
    return ledger, summary


def _runtime_ttl_assessment(
    *,
    redis_ttl_seconds: int,
    rotating_universe_size: int,
    actual_rotating_rows_covered: int,
    elapsed_seconds: float,
    expected_cycle_sleep_seconds: int,
    interval_history: list[float],
    coverage_history: list[float],
    wrap_count: int,
    universe_changed: bool,
    coverage_summary: dict[str, Any],
) -> dict[str, Any]:
    scheduled_cycle_period = max(
        1.0,
        float(expected_cycle_sleep_seconds) + math.ceil(elapsed_seconds),
        max(interval_history, default=0.0),
    )
    positive_coverage = [int(value) for value in coverage_history if value >= 1]
    conservative_rows_per_cycle = min(positive_coverage, default=0)
    if rotating_universe_size == 0:
        scheduled_revisit = scheduled_cycle_period
    elif conservative_rows_per_cycle:
        scheduled_revisit = (
            math.ceil(rotating_universe_size / conservative_rows_per_cycle)
            * scheduled_cycle_period
        )
    else:
        scheduled_revisit = None

    reason = "observed_and_scheduled_revisit_within_configured_ttl"
    status = "safe"
    if coverage_summary.get("ledger_truncated"):
        status = "unsafe"
        reason = "coverage_ledger_truncated_for_current_universe"
    elif rotating_universe_size and actual_rotating_rows_covered <= 0:
        status = "unsafe"
        reason = "rotation_did_not_advance_this_cycle"
    elif scheduled_revisit is None:
        status = "warming"
        reason = "insufficient_rotation_throughput_history"
    elif scheduled_revisit >= redis_ttl_seconds:
        status = "unsafe"
        reason = "scheduled_or_observed_revisit_not_below_configured_ttl"
    elif coverage_summary.get("oldest_success_age_seconds", 0) >= redis_ttl_seconds:
        status = "unsafe"
        reason = "at_least_one_component_last_success_is_older_than_configured_ttl"
    elif coverage_summary.get("max_recent_observed_component_revisit_seconds", 0) >= redis_ttl_seconds:
        status = "unsafe"
        reason = "recent_observed_component_revisit_not_below_configured_ttl"
    elif rotating_universe_size and (universe_changed or wrap_count < 1):
        status = "warming"
        reason = "current_universe_has_not_completed_a_rotation_wrap"
    elif coverage_summary.get("missing_component_count", 0):
        status = "unsafe"
        reason = "component_success_coverage_incomplete_after_rotation_wrap"
    elif coverage_summary.get("components_with_observed_revisit", 0) < coverage_summary.get(
        "expected_component_count", 0
    ):
        status = "warming"
        reason = "component_revisit_observations_are_still_warming"
    return {
        "status": status,
        "reason": reason,
        "configured_redis_ttl_seconds": redis_ttl_seconds,
        "scheduled_cycle_period_seconds": round(scheduled_cycle_period, 3),
        "scheduled_worst_case_revisit_seconds": (
            round(scheduled_revisit, 3) if scheduled_revisit is not None else None
        ),
        "conservative_rotating_rows_per_cycle": conservative_rows_per_cycle,
    }


def fetch_public_rest_for_symbols(
    symbols: tuple[str, ...],
    *,
    timeframes: tuple[str, ...],
    symbol_limit: int | None = None,
    request_budget: int = DEFAULT_PUBLIC_REST_REQUEST_BUDGET,
    weight_budget: int = DEFAULT_PUBLIC_REST_WEIGHT_BUDGET,
    cycle_deadline_seconds: int = DEFAULT_PUBLIC_REST_CYCLE_DEADLINE_SECONDS,
    cycle_epoch_ms: int | None = None,
    rotation_cursor: dict[str, Any] | None = None,
    coverage_ledger: dict[str, Any] | None = None,
    redis_ttl_seconds: int = 600,
    expected_cycle_sleep_seconds: int = EXPECTED_SERVICE_SLEEP_SECONDS,
) -> dict[str, Any]:
    from v2.backend.app.services.native_ingestors.kucoin import (
        KUCOIN_BASE_FUTURES,
        KUCOIN_BASE_SPOT,
    )

    tf_map = {
        "1m": "1min",
        "5m": "5min",
        "15m": "15min",
        "30m": "30min",
        "1h": "1hour",
        "4h": "4hour",
        "1d": "1day",
    }
    futures_tf_map = {
        # KuCoin Futures expresses kline granularity in minutes, unlike the
        # millisecond `from`/`to` bounds used by the same endpoint.
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "4h": 240,
        "1d": 1440,
    }
    started_ms = _now_ms() if cycle_epoch_ms is None else int(cycle_epoch_ms)
    started_utc = _iso_from_ms(started_ms) or _utc_iso()
    selected = tuple(symbols[:symbol_limit]) if symbol_limit else tuple(symbols)
    budget = max(2, int(request_budget))
    public_weight_budget = max(7, int(weight_budget))
    deadline_seconds = max(10, int(cycle_deadline_seconds))
    cycle_started_monotonic = time.monotonic()
    request_count = 0
    request_weight = 0
    budget_stop_reason: str | None = None

    def request(
        base: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> tuple[int, Any, int]:
        nonlocal request_count, request_weight, budget_stop_reason
        weight = _kucoin_public_request_weight(path)
        if time.monotonic() - cycle_started_monotonic >= deadline_seconds:
            budget_stop_reason = "cycle_deadline_seconds"
            return 597, {"code": "LOCAL_CYCLE_DEADLINE_EXHAUSTED"}, _now_ms()
        if request_count >= budget:
            budget_stop_reason = "request_count"
            return 598, {"code": "LOCAL_REQUEST_BUDGET_EXHAUSTED"}, _now_ms()
        if request_weight + weight > public_weight_budget:
            budget_stop_reason = "official_rate_limit_weight"
            return 596, {"code": "LOCAL_WEIGHT_BUDGET_EXHAUSTED"}, _now_ms()
        request_count += 1
        request_weight += weight
        status, body = _http_get_json(base, path, params)
        return status, body, _now_ms()

    spot_auth_status, spot_auth_body, spot_auth_observed_ms = request(
        KUCOIN_BASE_SPOT, "/api/v2/symbols"
    )
    futures_auth_status, futures_auth_body, futures_auth_observed_ms = request(
        KUCOIN_BASE_FUTURES, "/api/v1/contracts/active"
    )
    spot_authority = {
        str(row.get("symbol") or "").upper(): row
        for row in _authority_rows(_kucoin_data(spot_auth_body))
        if row.get("symbol")
    }
    futures_authority = {
        str(row.get("symbol") or "").upper(): row
        for row in _authority_rows(_kucoin_data(futures_auth_body))
        if row.get("symbol")
    }

    authorized: list[tuple[str, str, str, dict[str, Any] | None, dict[str, Any] | None]] = []
    unsupported_symbols: list[str] = []
    for symbol in selected:
        canonical = str(symbol).upper()
        spot_symbol = v2_to_kucoin_spot_symbol(canonical).upper()
        futures_symbol = v2_to_kucoin_futures_symbol(canonical).upper()
        spot_row = spot_authority.get(spot_symbol)
        futures_row = futures_authority.get(futures_symbol)
        spot_match = spot_row if spot_row and _spot_authority_match(canonical, spot_symbol, spot_row) else None
        futures_match = (
            futures_row
            if futures_row and _futures_authority_match(canonical, futures_symbol, futures_row)
            else None
        )
        if spot_match is None and futures_match is None:
            unsupported_symbols.append(canonical)
            continue
        authorized.append((canonical, spot_symbol, futures_symbol, spot_match, futures_match))

    authorized_count = len(authorized)
    worst_case_calls_per_symbol = 2 + len(timeframes)
    worst_case_weight_per_symbol = max(
        4 + (3 * len(timeframes)),
        5 + (3 * len(timeframes)),
    )
    estimated_rows = max(
        1,
        min(
            (budget - request_count) // max(1, worst_case_calls_per_symbol),
            (public_weight_budget - request_weight)
            // max(1, worst_case_weight_per_symbol),
        ),
    )
    authorized_by_symbol = {item[0]: item for item in authorized}
    preferred = [
        authorized_by_symbol[symbol]
        for symbol in PREFERRED_EVERY_CYCLE_SYMBOLS
        if symbol in authorized_by_symbol
    ]
    rotating_base = sorted(
        (item for item in authorized if item[0] not in PREFERRED_EVERY_CYCLE_SYMBOLS),
        key=lambda item: item[0],
    )
    rotating_symbols = [item[0] for item in rotating_base]
    rotation_start_index = _rotation_start_index(rotating_symbols, rotation_cursor)
    rotating = (
        rotating_base[rotation_start_index:] + rotating_base[:rotation_start_index]
        if rotating_base
        else []
    )
    rotating_capacity = max(0, estimated_rows - len(preferred))
    authorized = preferred + rotating

    rows: list[dict[str, Any]] = []
    budget_skipped_symbols: list[str] = []
    actual_rotating_rows_covered: list[str] = []
    incomplete_attempt_symbols: list[str] = []
    for position, (symbol, spot_symbol, futures_symbol, spot_meta, futures_meta) in enumerate(authorized):
        if request_count >= budget:
            budget_stop_reason = "request_count"
            budget_skipped_symbols.extend(item[0] for item in authorized[position:])
            break
        if request_weight >= public_weight_budget:
            budget_stop_reason = "official_rate_limit_weight"
            budget_skipped_symbols.extend(item[0] for item in authorized[position:])
            break
        if len(rows) >= estimated_rows:
            budget_stop_reason = "rotation_batch_capacity"
            budget_skipped_symbols.extend(item[0] for item in authorized[position:])
            break
        if time.monotonic() - cycle_started_monotonic >= deadline_seconds:
            budget_stop_reason = "cycle_deadline_seconds"
            budget_skipped_symbols.extend(item[0] for item in authorized[position:])
            break
        # Ticker + kline(s) + orderbook + optional futures funding.  Contract
        # detail is reused from the single authoritative active-contract fetch.
        primary_is_spot = futures_meta is None and spot_meta is not None
        required_calls = (2 + len(timeframes)) if primary_is_spot else (1 + len(timeframes))
        if request_count + required_calls > budget:
            budget_stop_reason = "request_count"
            budget_skipped_symbols.extend(item[0] for item in authorized[position:])
            break
        required_weight = (
            (4 + (3 * len(timeframes)))
            if primary_is_spot
            else (5 + (3 * len(timeframes)))
        )
        if request_weight + required_weight > public_weight_budget:
            budget_stop_reason = "official_rate_limit_weight"
            budget_skipped_symbols.extend(item[0] for item in authorized[position:])
            break
        primary_market_type = KUCOIN_SPOT_MARKET if primary_is_spot else KUCOIN_FUTURES_MARKET
        row: dict[str, Any] = {
            "symbol": symbol,
            "kucoin_spot_symbol": spot_symbol,
            "kucoin_futures_symbol": futures_symbol,
            "venue": "kucoin",
            "primary_market_type": primary_market_type,
            "spot_authorized": spot_meta is not None,
            "futures_authorized": futures_meta is not None,
            "authorized_product_coverage": [
                product
                for product, present in (
                    (KUCOIN_SPOT_MARKET, spot_meta is not None),
                    (KUCOIN_FUTURES_MARKET, futures_meta is not None),
                )
                if present
            ],
            "product_coverage": [primary_market_type],
            "rotation_priority": "preferred_every_cycle"
            if symbol in PREFERRED_EVERY_CYCLE_SYMBOLS
            else "rotating",
            "ticker": None,
            "klines": {},
            "funding": None,
            "contract": (
                _parse_contract(
                    futures_meta,
                    symbol=symbol,
                    futures_symbol=futures_symbol,
                    ingested_at_ms=futures_auth_observed_ms,
                )
                if futures_meta is not None
                else None
            ),
            "orderbook20": None,
            "endpoint_statuses": {},
            "endpoint_codes": {},
        }
        if primary_is_spot:
            status, body, observed_ms = request(
                KUCOIN_BASE_SPOT,
                "/api/v1/market/orderbook/level1",
                {"symbol": spot_symbol},
            )
            row["endpoint_statuses"]["spot_level1"] = status
            row["endpoint_codes"]["spot_level1"] = _kucoin_code(body)
            row["ticker"] = _parse_spot_ticker(
                _kucoin_data(body),
                symbol=symbol,
                spot_symbol=spot_symbol,
                ingested_at_ms=observed_ms,
            )
        else:
            row["ticker"] = _parse_futures_ticker(
                futures_meta,
                symbol=symbol,
                futures_symbol=futures_symbol,
                ingested_at_ms=futures_auth_observed_ms,
            )

        for tf in timeframes:
            kt = tf_map.get(tf)
            interval_seconds = TIMEFRAME_SECONDS.get(tf)
            if not kt or interval_seconds is None:
                continue
            query_end_ms = _now_ms()
            query_start_ms = query_end_ms - (interval_seconds * 3 * 1000)
            if primary_is_spot:
                status, body, observed_ms = request(
                    KUCOIN_BASE_SPOT,
                    "/api/v1/market/candles",
                    {
                        "symbol": spot_symbol,
                        "type": kt,
                        "startAt": query_start_ms // 1000,
                        "endAt": query_end_ms // 1000,
                    },
                )
                status_name = f"spot_kline_{tf}"
                parsed = _parse_kline(
                    _kucoin_data(body),
                    symbol=symbol,
                    kucoin_symbol=spot_symbol,
                    timeframe=tf,
                    source="kucoin_spot_public_rest",
                    observed_at_ms=query_end_ms,
                    available_at_ms=observed_ms,
                )
            else:
                futures_granularity = futures_tf_map.get(tf)
                status, body, observed_ms = request(
                    KUCOIN_BASE_FUTURES,
                    "/api/v1/kline/query",
                    {
                        "symbol": futures_symbol,
                        "granularity": futures_granularity,
                        "from": query_start_ms,
                        "to": query_end_ms,
                    },
                )
                status_name = f"futures_kline_{tf}"
                parsed = _parse_kline(
                    _kucoin_data(body),
                    symbol=symbol,
                    kucoin_symbol=futures_symbol,
                    timeframe=tf,
                    source="kucoin_futures_public_rest",
                    observed_at_ms=query_end_ms,
                    available_at_ms=observed_ms,
                )
            row["endpoint_statuses"][status_name] = status
            row["endpoint_codes"][status_name] = _kucoin_code(body)
            if parsed is not None:
                row["klines"][tf] = parsed

        if primary_is_spot:
            status, body, observed_ms = request(
                KUCOIN_BASE_SPOT,
                "/api/v1/market/orderbook/level2_20",
                {"symbol": spot_symbol},
            )
            orderbook_name = "spot_orderbook20"
            orderbook_symbol = spot_symbol
            orderbook_source = "kucoin_spot_public_rest"
        else:
            status, body, observed_ms = request(
                KUCOIN_BASE_FUTURES,
                "/api/v1/level2/depth20",
                {"symbol": futures_symbol},
            )
            orderbook_name = "futures_orderbook20"
            orderbook_symbol = futures_symbol
            orderbook_source = "kucoin_futures_public_rest"
        row["endpoint_statuses"][orderbook_name] = status
        row["endpoint_codes"][orderbook_name] = _kucoin_code(body)
        row["orderbook20"] = _parse_orderbook(
                _kucoin_data(body),
                symbol=symbol,
                kucoin_symbol=orderbook_symbol,
                source=orderbook_source,
                ingested_at_ms=observed_ms,
        )

        if futures_meta is not None:
            row["funding"] = _parse_funding(
                futures_meta,
                symbol=symbol,
                futures_symbol=futures_symbol,
                source="kucoin_futures_contract_authority_snapshot",
                ingested_at_ms=futures_auth_observed_ms,
            )
        local_stop_codes = {
            "LOCAL_CYCLE_DEADLINE_EXHAUSTED",
            "LOCAL_REQUEST_BUDGET_EXHAUSTED",
            "LOCAL_WEIGHT_BUDGET_EXHAUSTED",
        }
        row["rotation_schedule_covered"] = not any(
            code in local_stop_codes for code in row["endpoint_codes"].values()
        )
        if row["rotation_schedule_covered"] is not True:
            incomplete_attempt_symbols.append(symbol)
        elif symbol not in PREFERRED_EVERY_CYCLE_SYMBOLS:
            actual_rotating_rows_covered.append(symbol)
        rows.append(row)

    elapsed_seconds = max(0.0, time.monotonic() - cycle_started_monotonic)
    finished_ms = max(started_ms, _now_ms())
    actual_rotating_count = len(actual_rotating_rows_covered)
    previous_rotating_universe = (
        rotation_cursor.get("rotating_universe", [])
        if isinstance(rotation_cursor, dict)
        and isinstance(rotation_cursor.get("rotating_universe"), list)
        else []
    )
    previous_rotating_universe = [
        str(symbol).upper()
        for symbol in previous_rotating_universe
        if _v2_usdt_base(str(symbol).upper()) is not None
    ]
    universe_changed = previous_rotating_universe != rotating_symbols
    prior_wrap_count = (
        int(rotation_cursor.get("completed_wrap_count", 0))
        if isinstance(rotation_cursor, dict)
        and isinstance(rotation_cursor.get("completed_wrap_count", 0), int)
        and int(rotation_cursor.get("completed_wrap_count", 0)) >= 0
        and not universe_changed
        else 0
    )
    completed_wrap = bool(
        rotating_symbols
        and actual_rotating_count
        and rotation_start_index + actual_rotating_count >= len(rotating_symbols)
    )
    completed_wrap_count = prior_wrap_count + int(completed_wrap)
    next_symbol = (
        rotating_symbols[
            (rotation_start_index + actual_rotating_count) % len(rotating_symbols)
        ]
        if rotating_symbols
        else None
    )
    interval_history = _bounded_positive_number_history(
        (rotation_cursor or {}).get("cycle_start_interval_seconds_history")
    )
    previous_cycle_started_ms = _positive_int(
        (rotation_cursor or {}).get("last_cycle_started_ms")
    )
    if previous_cycle_started_ms is not None and started_ms > previous_cycle_started_ms:
        interval_history.append(
            round((started_ms - previous_cycle_started_ms) / 1000.0, 3)
        )
        interval_history = interval_history[-ROTATION_HISTORY_LIMIT:]
    coverage_history = (
        []
        if universe_changed
        else _bounded_positive_number_history(
            (rotation_cursor or {}).get("rotating_rows_covered_history")
        )
    )
    if actual_rotating_count:
        coverage_history.append(float(actual_rotating_count))
        coverage_history = coverage_history[-ROTATION_HISTORY_LIMIT:]
    cursor_update = {
        "schema_version": "v2_kucoin_rotation_cursor_v1",
        "next_symbol": next_symbol,
        "rotating_universe": rotating_symbols[:MAX_COVERAGE_LEDGER_SYMBOLS],
        "rotating_universe_size": len(rotating_symbols),
        "last_cycle_started_ms": started_ms,
        "last_cycle_started_at": _iso_from_ms(started_ms),
        "last_cycle_finished_ms": finished_ms,
        "last_cycle_finished_at": _iso_from_ms(finished_ms),
        "last_rotation_start_index": rotation_start_index,
        "last_actual_rotating_rows_covered": actual_rotating_rows_covered,
        "last_actual_rotating_rows_covered_count": actual_rotating_count,
        "completed_wrap_count": completed_wrap_count,
        "cycle_start_interval_seconds_history": interval_history,
        "rotating_rows_covered_history": coverage_history,
    }
    authorized_products = [
        (
            symbol,
            KUCOIN_FUTURES_MARKET if futures_meta is not None else KUCOIN_SPOT_MARKET,
        )
        for symbol, _spot_symbol, _futures_symbol, _spot_meta, futures_meta in authorized
    ]
    coverage_ledger_update, coverage_summary = _build_coverage_ledger(
        previous_ledger=coverage_ledger,
        authorized_products=authorized_products,
        rows=rows,
        timeframes=timeframes,
        finished_ms=finished_ms,
        redis_ttl_seconds=max(1, int(redis_ttl_seconds)),
    )
    ttl_assessment = _runtime_ttl_assessment(
        redis_ttl_seconds=max(1, int(redis_ttl_seconds)),
        rotating_universe_size=len(rotating_symbols),
        actual_rotating_rows_covered=actual_rotating_count,
        elapsed_seconds=elapsed_seconds,
        expected_cycle_sleep_seconds=max(0, int(expected_cycle_sleep_seconds)),
        interval_history=interval_history,
        coverage_history=coverage_history,
        wrap_count=completed_wrap_count,
        universe_changed=universe_changed,
        coverage_summary=coverage_summary,
    )
    rotating_batches = (
        math.ceil(len(rotating_symbols) / rotating_capacity)
        if rotating_capacity > 0
        else None
    )
    return {
        "started_utc": started_utc,
        "finished_utc": _utc_iso(),
        "symbols_requested": len(symbols),
        "symbols_selected": len(selected),
        "symbols_authorized": authorized_count,
        "symbols_fetched": len(rows),
        "symbols_unsupported_count": len(unsupported_symbols),
        "symbols_unsupported": unsupported_symbols,
        "symbols_skipped_budget_count": len(budget_skipped_symbols),
        "symbols_skipped_budget": budget_skipped_symbols,
        "symbols_deferred_count": len(budget_skipped_symbols),
        "symbols_deferred": budget_skipped_symbols,
        "symbols_incomplete_attempt_count": len(incomplete_attempt_symbols),
        "symbols_incomplete_attempt": incomplete_attempt_symbols,
        "timeframes": list(timeframes),
        "request_budget": budget,
        "request_budget_unit": "http_requests",
        "request_count": request_count,
        "request_weight_budget": public_weight_budget,
        "request_weight_used": request_weight,
        "request_weight_contract": "kucoin_official_public_endpoint_weights",
        "cycle_deadline_seconds": deadline_seconds,
        "cycle_elapsed_seconds": round(elapsed_seconds, 3),
        "budget_stop_reason": budget_stop_reason,
        "request_budget_exhausted": budget_stop_reason in {
            "request_count",
            "official_rate_limit_weight",
            "cycle_deadline_seconds",
        },
        "coverage_partial": bool(
            budget_skipped_symbols or incomplete_attempt_symbols or unsupported_symbols
        ),
        "preferred_every_cycle_symbols": [item[0] for item in preferred],
        "estimated_symbols_per_cycle": estimated_rows,
        "estimated_rotation_cycles": rotating_batches,
        "rotation_cursor_source": "redis_persisted"
        if isinstance(rotation_cursor, dict)
        else "cold_start",
        "rotation_cursor_loaded": isinstance(rotation_cursor, dict),
        "rotation_cursor_persisted": False,
        "rotation_start_index": rotation_start_index,
        "rotation_next_symbol": next_symbol,
        "rotation_universe_changed": universe_changed,
        "rotation_completed_wrap_count": completed_wrap_count,
        "actual_rotating_rows_covered_count": actual_rotating_count,
        "actual_rotating_rows_covered": actual_rotating_rows_covered,
        "rotation_cycle_start_interval_seconds_history": interval_history,
        "rotation_rows_covered_history": coverage_history,
        "coverage_ledger": coverage_summary,
        "coverage_ledger_persisted": False,
        "redis_ttl_seconds": max(1, int(redis_ttl_seconds)),
        "runtime_ttl_compatibility": ttl_assessment["status"],
        "runtime_ttl_compatibility_reason": ttl_assessment["reason"],
        "scheduled_cycle_period_seconds": ttl_assessment[
            "scheduled_cycle_period_seconds"
        ],
        "scheduled_worst_case_revisit_seconds": ttl_assessment[
            "scheduled_worst_case_revisit_seconds"
        ],
        "conservative_rotating_rows_per_cycle": ttl_assessment[
            "conservative_rotating_rows_per_cycle"
        ],
        "_rotation_cursor_update": cursor_update,
        "_coverage_ledger_update": coverage_ledger_update,
        "authority": {
            "spot": {
                "http_status": spot_auth_status,
                "provider_code": _kucoin_code(spot_auth_body),
                "listed_products": len(spot_authority),
                "observed_at": _iso_from_ms(spot_auth_observed_ms),
            },
            "futures": {
                "http_status": futures_auth_status,
                "provider_code": _kucoin_code(futures_auth_body),
                "listed_products": len(futures_authority),
                "observed_at": _iso_from_ms(futures_auth_observed_ms),
            },
        },
        "rows": rows,
    }


def persist_fetch_to_v2_redis(redis_client: Any, fetch: dict[str, Any], *, ttl_seconds: int = 600) -> list[str]:
    written: list[str] = []
    if redis_client is None:
        return written
    for row in fetch.get("rows", []):
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        for suffix, payload in (
            (f"v2:market:kucoin:latest:{symbol}", row.get("ticker")),
            (f"v2:market:kucoin:funding:{symbol}", row.get("funding")),
            (f"v2:market:kucoin:contract:{symbol}", row.get("contract")),
            (f"v2:market:kucoin:orderbook20:{symbol}", row.get("orderbook20")),
        ):
            if payload is not None and _safe_write(redis_client, suffix, payload, ex=ttl_seconds):
                written.append(suffix)
        klines = row.get("klines")
        if isinstance(klines, dict):
            for tf, payload in klines.items():
                key = f"v2:market:kucoin:kline:{symbol}:{tf}"
                if _safe_write(redis_client, key, payload, ex=ttl_seconds):
                    written.append(key)
        if not _row_has_public_data(row):
            continue
        components = [
            payload
            for payload in (
                row.get("ticker"),
                row.get("funding"),
                row.get("contract"),
                row.get("orderbook20"),
                *((row.get("klines") or {}).values()),
            )
            if isinstance(payload, dict)
        ]
        available_ms_values = [
            int(payload["available_at_ms"])
            for payload in components
            if isinstance(payload.get("available_at_ms"), int)
        ]
        cutoff_ms_values = [
            int(payload["feature_cutoff_ms"])
            for payload in components
            if isinstance(payload.get("feature_cutoff_ms"), int)
        ]
        aggregate_available_ms = max(available_ms_values) if available_ms_values else None
        aggregate_cutoff_ms = max(cutoff_ms_values) if cutoff_ms_values else None
        event_ms_values = [
            int(payload["event_time_ms"])
            for payload in components
            if isinstance(payload.get("event_time_ms"), int)
        ]
        aggregate_event_ms = max(event_ms_values) if event_ms_values else None
        product_coverage = sorted(
            {
                str(payload.get("market_type"))
                for payload in components
                if payload.get("market_type")
            }
        )
        temporal_valid = bool(components) and all(
            payload.get("temporal_contract_valid") is True for payload in components
        ) and (
            aggregate_available_ms is not None
            and aggregate_cutoff_ms is not None
            and aggregate_cutoff_ms <= aggregate_available_ms
        )
        feature_payload = {
            "symbol": symbol,
            "source": "kucoin_public_rest",
            "data_available": True,
            "venue": "kucoin",
            "product_coverage": product_coverage,
            "mixed_products": len(product_coverage) > 1,
            "ticker": row.get("ticker"),
            "funding": row.get("funding"),
            "contract": row.get("contract"),
            "orderbook20_present": row.get("orderbook20") is not None,
            "klines_present": sorted((row.get("klines") or {}).keys()),
            "generated_at": fetch.get("finished_utc"),
            "generated_utc": fetch.get("finished_utc"),
            "event_time": _iso_from_ms(aggregate_event_ms),
            "event_time_ms": aggregate_event_ms,
            "ingested_at": _iso_from_ms(aggregate_available_ms),
            "available_at": _iso_from_ms(aggregate_available_ms),
            "available_at_ms": aggregate_available_ms,
            "feature_cutoff": _iso_from_ms(aggregate_cutoff_ms),
            "feature_cutoff_ms": aggregate_cutoff_ms,
            "temporal_contract_valid": temporal_valid,
            # This is cross-venue observational evidence, not a canonical
            # homogeneous feature vector. Consumers must opt in explicitly.
            "feature_eligible": False,
            "trainer_consumable": False,
            "valid_for_prediction": False,
            "valid_for_paper": False,
            "consumer_hold_reason": "KUCOIN_MIXED_PROVIDER_SNAPSHOT_NOT_CANONICAL_FEATURE",
            "live_gate": "blocked_human_only",
            "live_symbols": [],
        }
        fkey = f"v2:features:kucoin:{symbol}:latest"
        if _safe_write(redis_client, fkey, feature_payload, ex=ttl_seconds):
            written.append(fkey)
    state_ttl_seconds = max(
        ROTATION_STATE_TTL_SECONDS,
        max(60, int(ttl_seconds)) * 4,
    )
    cursor_update = fetch.get("_rotation_cursor_update")
    if isinstance(cursor_update, dict) and _safe_write(
        redis_client,
        ROTATION_CURSOR_KEY,
        cursor_update,
        ex=state_ttl_seconds,
    ):
        written.append(ROTATION_CURSOR_KEY)
        fetch["rotation_cursor_persisted"] = True
    ledger_update = fetch.get("_coverage_ledger_update")
    if isinstance(ledger_update, dict) and _safe_write(
        redis_client,
        COVERAGE_LEDGER_KEY,
        ledger_update,
        ex=state_ttl_seconds,
    ):
        written.append(COVERAGE_LEDGER_KEY)
        fetch["coverage_ledger_persisted"] = True
    heartbeat = {
        "worker_id": "v2_kucoin_ingestor",
        "source": "kucoin_public_rest",
        "finished_utc": fetch.get("finished_utc"),
        "keys_written_count": len(written),
        "request_count": fetch.get("request_count"),
        "request_budget": fetch.get("request_budget"),
        "request_budget_exhausted": fetch.get("request_budget_exhausted"),
        "symbols_requested": fetch.get("symbols_requested"),
        "symbols_authorized": fetch.get("symbols_authorized"),
        "symbols_fetched": fetch.get("symbols_fetched"),
        "symbols_skipped_budget_count": fetch.get("symbols_skipped_budget_count"),
        "symbols_unsupported_count": fetch.get("symbols_unsupported_count"),
        "rotation_cursor_persisted": fetch.get("rotation_cursor_persisted"),
        "coverage_ledger_persisted": fetch.get("coverage_ledger_persisted"),
        "rotation_next_symbol": fetch.get("rotation_next_symbol"),
        "actual_rotating_rows_covered_count": fetch.get(
            "actual_rotating_rows_covered_count"
        ),
        "runtime_ttl_compatibility": fetch.get("runtime_ttl_compatibility"),
        "runtime_ttl_compatibility_reason": fetch.get(
            "runtime_ttl_compatibility_reason"
        ),
        "redis_ttl_seconds": fetch.get("redis_ttl_seconds"),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
    }
    if _safe_write(redis_client, "v2:market:kucoin:heartbeat", heartbeat, ex=ttl_seconds):
        written.append("v2:market:kucoin:heartbeat")
    return written


def build_payload(
    symbols: tuple[str, ...],
    *,
    fetch_public_rest: bool = False,
    fetch_symbol_limit: int | None = None,
    timeframes: tuple[str, ...] | None = None,
    write_v2_redis: bool = False,
    redis_ttl_seconds: int = 600,
    public_rest_request_budget: int = DEFAULT_PUBLIC_REST_REQUEST_BUDGET,
) -> dict:
    cfg = build_ingestor_config(symbols_v2=symbols)
    reconnect_examples = [classify_reconnect_attempt(i) for i in range(0, 10)]
    bounded_redis_ttl_seconds = max(60, int(redis_ttl_seconds))
    redis_client = _connect_redis() if write_v2_redis else None
    redis_ok = redis_client is not None if write_v2_redis else None
    rotation_cursor = _load_rotation_cursor(redis_client)
    coverage_ledger = _load_coverage_ledger(redis_client)
    fetch_payload = (
        fetch_public_rest_for_symbols(
            symbols,
            timeframes=timeframes or tuple(cfg.timeframes[:1]),
            symbol_limit=fetch_symbol_limit,
            request_budget=public_rest_request_budget,
            rotation_cursor=rotation_cursor,
            coverage_ledger=coverage_ledger,
            redis_ttl_seconds=bounded_redis_ttl_seconds,
        )
        if fetch_public_rest
        else None
    )
    redis_keys_written: list[str] = []
    if write_v2_redis:
        if fetch_payload is not None:
            redis_keys_written = persist_fetch_to_v2_redis(
                redis_client,
                fetch_payload,
                ttl_seconds=bounded_redis_ttl_seconds,
            )
    if isinstance(fetch_payload, dict):
        # Persisted state is intentionally omitted from the public status body;
        # only its bounded coverage summary and cursor diagnostics are exposed.
        fetch_payload.pop("_rotation_cursor_update", None)
        fetch_payload.pop("_coverage_ledger_update", None)
    classification = cfg.classification
    public_rest_summary = _public_rest_summary(fetch_payload)
    if fetch_public_rest:
        rows = fetch_payload.get("rows", []) if isinstance(fetch_payload, dict) else []
        success = any(isinstance(r, dict) and _row_has_public_data(r) for r in rows)
        if not success:
            classification = "BLOCKED_BY_NETWORK_OR_API"
        elif fetch_payload.get("request_budget_exhausted"):
            classification = "NATIVE_V2_PUBLIC_REST_PARTIAL_REQUEST_BUDGET"
        elif fetch_payload.get("coverage_partial"):
            classification = "NATIVE_V2_PUBLIC_REST_PARTIAL_ROTATION"
        else:
            classification = "NATIVE_V2_PUBLIC_REST_OK"
    return {
        "worker_id": "v2_kucoin_ingestor",
        "schema_version": "v2_kucoin_ingestor_status_v1",
        "scope": "PAPER_ONLY_PUBLIC_MARKET_DATA",
        "classification": classification,
        "symbols_v2": list(cfg.symbols_v2),
        "timeframes": list(cfg.timeframes),
        "spot_endpoints": [asdict(e) for e in cfg.spot_endpoints],
        "futures_endpoints": [asdict(e) for e in cfg.futures_endpoints],
        "public_wss_topics": [asdict(t) for t in cfg.public_wss_topics],
        "public_rest_fetch_enabled": bool(fetch_public_rest),
        "public_rest_fetch": fetch_payload,
        "public_rest_summary": public_rest_summary,
        "v2_redis_write_enabled": bool(write_v2_redis),
        "redis_ok": redis_ok,
        "v2_redis_keys_written": redis_keys_written,
        "v2_redis_keys_written_count": len(redis_keys_written),
        "ticker_period_seconds": cfg.ticker_period_seconds,
        "kline_period_seconds": cfg.kline_period_seconds,
        "funding_period_seconds": cfg.funding_period_seconds,
        "orderbook_period_seconds": cfg.orderbook_period_seconds,
        "reconnect_backoff_seconds": list(cfg.reconnect_backoff_seconds),
        "reconnect_examples": reconnect_examples,
        "generated_utc": cfg.generated_utc,
        "invariants": kucoin_invariants_snapshot(),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_kucoin_ingestor_worker")
    parser.add_argument(
        "--symbols",
        default=None,
        help="Comma-separated V2 symbols. Default is dynamic universe plus 25-symbol baseline.",
    )
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--write-evidence", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--fetch-public-rest", action="store_true")
    parser.add_argument(
        "--fetch-symbol-limit",
        type=int,
        default=None,
        help="Optional cap for public REST fetch count; omitted fetches all resolved symbols.",
    )
    parser.add_argument(
        "--fetch-timeframes",
        default="1m",
        help="Comma-separated KuCoin kline timeframes to fetch when --fetch-public-rest is set.",
    )
    parser.add_argument("--write-v2-redis", action="store_true")
    parser.add_argument("--v2-redis-ttl-seconds", type=int, default=600)
    parser.add_argument(
        "--max-public-rest-requests",
        type=int,
        default=DEFAULT_PUBLIC_REST_REQUEST_BUDGET,
        help="Hard per-cycle request cap, including the two product-authority requests.",
    )
    args = parser.parse_args(argv)
    explicit = (
        tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
        if args.symbols
        else None
    )
    symbols = tuple(resolve_symbols(explicit=explicit, smoke_test=args.smoke_test))
    fetch_tfs = tuple(s.strip() for s in args.fetch_timeframes.split(",") if s.strip())
    payload = build_payload(
        symbols,
        fetch_public_rest=bool(args.fetch_public_rest),
        fetch_symbol_limit=args.fetch_symbol_limit,
        timeframes=fetch_tfs,
        write_v2_redis=bool(args.write_v2_redis),
        redis_ttl_seconds=max(60, int(args.v2_redis_ttl_seconds)),
        public_rest_request_budget=max(2, int(args.max_public_rest_requests)),
    )
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.dry_run and args.write_evidence:
        print("ERROR: --dry-run and --write-evidence are mutually exclusive", file=sys.stderr)
        return 2
    if args.write_evidence:
        dest = args.out or DEFAULT_PAYLOAD_PATH
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body)
        print(f"v2_kucoin_ingestor_status_written path={dest} classification={payload['classification']}")
        return 0
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
