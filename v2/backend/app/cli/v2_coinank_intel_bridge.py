"""Bridge fresh legacy CoinAnk intelligence into the V2 namespace.

The legacy CoinAnk runtime (live_coinank.py + live_coinank_global_aggregator.py)
publishes rich, real-time market intelligence onto NON-``v2:``-prefixed keys
(``features:global_coinank:*``, ``latest:coinank:{family}:{symbol}:{tf}``). The
V2 trainer / strategy-supply / confluence consumers only read ``v2:`` keys, so
that intelligence — funding, OI, long/short, liquidations, global regime — was
stranded even though it was fresh. This read-only bridge mirrors it into the
``v2:coinank:*`` and ``v2:features:coinank:*`` keys those consumers scan.

Safety: reads legacy keys, writes only ``v2:`` keys, never touches orders,
leverage, margin, or the live gate.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Mapping

V2_PREFIX = "v2:"
GLOBAL_SNAPSHOT_KEY = "v2:coinank:global:latest"
GLOBAL_MEMBER_KEY = "v2:coinank:global:{name}:latest"
SYMBOL_KEY = "v2:coinank:symbol:{symbol}"
FEATURE_KEY = "v2:features:coinank:{symbol}:{timeframe}"
PROVIDER_HEALTH_KEY = "v2:provider:coinank:health"
PROVIDER_FEATURE_BRIDGE_KEY = "v2:provider:coinank:feature_bridge_status"
STATUS_KEY = "v2:coinank:intel_bridge_status"

TTL_SECONDS = 900
SCAN_CAP = 4000
SCAN_BUDGET_SECONDS = 4.0
GLOBAL_MAX_AGE_SECONDS = 900
SYMBOL_MAX_AGE_SECONDS = 600
MAX_FUTURE_CLOCK_SKEW_SECONDS = 5
TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1_800,
    "1h": 3_600,
    "4h": 14_400,
    "1d": 86_400,
}
_CANONICAL_USDT_RE = re.compile(r"^[A-Z0-9]+USDT$")

GLOBAL_NAMES = (
    "total_oi", "total_volume", "total_liquidations", "long_short_ratio",
    "funding_rate_avg", "btc_dominance", "eth_dominance", "alt_season_index",
    "fear_greed", "market_sentiment", "volatility_index",
)
SUPPORTED_GLOBAL_NAMES = (
    "total_volume",
    "total_liquidations",
    "long_short_ratio",
    "market_sentiment",
)
EXPECTED_GLOBAL_UNITS = {
    "total_volume": "usd",
    "total_liquidations": "usd",
    "long_short_ratio": "ratio",
    "market_sentiment": "ratio_minus1_to_plus1",
}
GLOBAL_MIN_COVERAGE_RATIO = 0.5
FAMILIES = ("funding", "long_short", "open_interest", "liquidations", "market_order_flow")
LEGACY_LATEST = "latest:coinank:{family}:{symbol}:{timeframe}"
ENDPOINT_LATEST = "latest:coinank_endpoint:{endpoint}:{symbol}:{timeframe}"
ENDPOINT_VARIANT_LATEST = (
    "latest:coinank_endpoint:{endpoint}:{variant}:{symbol}:{timeframe}"
)
FAMILY_ENDPOINT = {
    "funding": "fundingRate_kline",
    "long_short": "ls_global_account_ratio",
    "open_interest": "openInterest_kline",
    "liquidations": "liquidation_history",
    "market_order_flow": "marketOrder_getBuySellValue",
}
LONG_SHORT_VARIANTS = {
    "longShortPerson": (
        "coinank_global_account_long_short_ratio_kline",
        "global_account_ratio",
    ),
    "longShortPosition": (
        "coinank_top_trader_position_long_short_ratio_kline",
        "top_trader_position_ratio",
    ),
    "longShortAccount": (
        "coinank_top_trader_account_long_short_ratio_kline",
        "top_trader_account_ratio",
    ),
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _iso_from_ms(value: int | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(value / 1000.0, tz=timezone.utc).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
    except (OSError, OverflowError, ValueError):
        return None


def _epoch_ms(value: Any) -> int | None:
    numeric = _f(value)
    if numeric is None or numeric <= 0:
        return None
    if numeric >= 1_000_000_000_000_000:
        return int(numeric / 1_000_000)
    if numeric >= 1_000_000_000_000:
        return int(numeric)
    if numeric >= 1_000_000_000:
        return int(numeric * 1000)
    return None


def _canonical_symbol(value: Any) -> str | None:
    symbol = str(value or "").strip().upper()
    if not _CANONICAL_USDT_RE.fullmatch(symbol):
        return None
    base = symbol[:-4]
    if not base or base.endswith("USDT"):
        return None
    return symbol


def _global_value_in_domain(
    name: str,
    value: float | None,
    payload: Mapping[str, Any],
) -> bool:
    if name not in SUPPORTED_GLOBAL_NAMES:
        return False
    if (
        payload.get("supported") is not True
        or payload.get("aggregate_valid") is not True
        or payload.get("valid") is not True
        or payload.get("temporal_contract_valid") is not True
        or payload.get("unit") != EXPECTED_GLOBAL_UNITS.get(name)
    ):
        return False
    if value is None:
        return False
    sample_count = _f(payload.get("n"))
    universe_count = _f(payload.get("universe_n"))
    if (
        sample_count is None
        or universe_count is None
        or sample_count <= 0
        or universe_count <= 0
        or sample_count > universe_count
        or not sample_count.is_integer()
        or not universe_count.is_integer()
    ):
        return False
    coverage_ratio = _f(payload.get("coverage_ratio"))
    expected_coverage = sample_count / universe_count
    if (
        coverage_ratio is None
        or coverage_ratio < GLOBAL_MIN_COVERAGE_RATIO
        or abs(coverage_ratio - expected_coverage) > 1e-6
    ):
        return False
    available_ms = _epoch_ms(payload.get("available_at_ms"))
    cutoff_ms = _epoch_ms(payload.get("feature_cutoff_ms"))
    generated_ms = _epoch_ms(payload.get("generated_at_ms"))
    aggregation_cutoff_ms = _epoch_ms(
        payload.get("aggregation_window_feature_cutoff_ms")
    )
    if (
        available_ms is None
        or cutoff_ms is None
        or generated_ms is None
        or aggregation_cutoff_ms != cutoff_ms
        or str(payload.get("aggregation_timeframe") or "") not in TIMEFRAME_SECONDS
        or not (cutoff_ms <= available_ms <= generated_ms)
    ):
        return False
    if name == "long_short_ratio" and (
        payload.get("source_endpoint") != "ls_global_account_ratio"
        or payload.get("semantic") != "global_account_ratio"
    ):
        return False
    if name in {"total_volume", "total_liquidations"}:
        return 0 <= value <= 1e18
    if name == "long_short_ratio":
        return 0 < value <= 100
    if name == "market_sentiment":
        return -1 <= value <= 1
    return False


def _connect_redis():
    try:
        import redis  # type: ignore

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def _get_json(client: Any, key: str) -> Any:
    try:
        raw = client.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _get_endpoint_payload(
    client: Any,
    *,
    family: str,
    symbol: str,
    timeframe: str,
) -> Mapping[str, Any] | None:
    """Read a non-colliding endpoint mirror; generic fallback must self-identify."""
    endpoint = FAMILY_ENDPOINT[family]
    payload = _get_json(
        client,
        ENDPOINT_LATEST.format(endpoint=endpoint, symbol=symbol, timeframe=timeframe),
    )
    if isinstance(payload, Mapping) and str(payload.get("endpoint") or "") == endpoint:
        return payload
    fallback = _get_json(
        client,
        LEGACY_LATEST.format(family=family, symbol=symbol, timeframe=timeframe),
    )
    if isinstance(fallback, Mapping) and str(fallback.get("endpoint") or "") == endpoint:
        return fallback
    return None


def _get_long_short_variant_payload(
    client: Any,
    *,
    variant: str,
    symbol: str,
    timeframe: str,
) -> Mapping[str, Any] | None:
    """Read one explicitly typed CoinAnk long/short series without fallback."""
    payload = _get_json(
        client,
        ENDPOINT_VARIANT_LATEST.format(
            endpoint="ls_kline",
            variant=variant,
            symbol=symbol,
            timeframe=timeframe,
        ),
    )
    if not isinstance(payload, Mapping) or payload.get("endpoint") != "ls_kline":
        return None
    request_parameters = payload.get("request_parameters")
    request_variant = (
        request_parameters.get("type")
        if isinstance(request_parameters, Mapping)
        else None
    )
    payload_variant = payload.get("endpoint_variant") or request_variant
    return payload if str(payload_variant or "") == variant else None


def _set_json(client: Any, key: str, payload: Any, ex: int = TTL_SECONDS) -> bool:
    if not key.startswith(V2_PREFIX):
        return False
    try:
        client.set(key, json.dumps(payload, default=str), ex=ex)
        return True
    except Exception:
        return False


def _f(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n and abs(n) != float("inf") else None


def _series(payload: Mapping[str, Any]) -> list[Any]:
    """Return the CoinAnk time-series list from a latest:coinank:* payload."""
    data: Any = payload.get("data")
    for _ in range(4):
        if isinstance(data, list):
            return data
        if not isinstance(data, Mapping) or "data" not in data:
            break
        data = data.get("data")
    return []


def _inner_data(payload: Mapping[str, Any]) -> Any:
    data: Any = payload.get("data")
    for _ in range(4):
        if not isinstance(data, Mapping) or "data" not in data:
            return data
        data = data.get("data")
    return data


def _row_open_ms(row: Any) -> int | None:
    if isinstance(row, Mapping):
        for field in ("ts", "begin", "time", "timestamp"):
            parsed = _epoch_ms(row.get(field))
            if parsed is not None:
                return parsed
    if isinstance(row, (list, tuple)) and row:
        return _epoch_ms(row[0])
    return None


def _closed_rows(rows: list[Any], timeframe: str, observed_at_ms: int) -> list[Any]:
    interval_seconds = TIMEFRAME_SECONDS.get(timeframe)
    if interval_seconds is None:
        return []
    interval_ms = interval_seconds * 1000
    eligible = [
        row
        for row in rows
        if (open_ms := _row_open_ms(row)) is not None
        and open_ms + interval_ms <= observed_at_ms
    ]
    return sorted(eligible, key=lambda row: _row_open_ms(row) or 0)


def _closed_parallel_value(
    inner: Any,
    timeframe: str,
    observed_at_ms: int,
    *fields: str,
) -> tuple[float | None, int | None]:
    if not isinstance(inner, Mapping):
        return None, None
    timestamps = inner.get("tss") or inner.get("timestamps") or inner.get("times")
    if not isinstance(timestamps, list):
        return None, None
    interval_seconds = TIMEFRAME_SECONDS.get(timeframe)
    if interval_seconds is None:
        return None, None
    interval_ms = interval_seconds * 1000
    for index in range(len(timestamps) - 1, -1, -1):
        open_ms = _epoch_ms(timestamps[index])
        if open_ms is None or open_ms + interval_ms > observed_at_ms:
            continue
        for field in fields:
            values = inner.get(field)
            if isinstance(values, list) and index < len(values):
                parsed = _f(values[index])
                if parsed is not None:
                    return parsed, open_ms
    return None, None


def _latest_closed_open_ms(rows: list[Any]) -> int | None:
    values = [_row_open_ms(row) for row in rows]
    finite = [value for value in values if value is not None]
    return max(finite) if finite else None


def _last_num(rows: list[Any], *fields: str) -> float | None:
    for row in reversed(rows):
        if isinstance(row, Mapping):
            for field in fields:
                v = _f(row.get(field))
                if v is not None:
                    return v
    return None


def _long_short_variant_observation(
    payload: Mapping[str, Any],
    *,
    timeframe: str,
    now_ms: int,
) -> tuple[dict[str, Any] | None, str | None]:
    source_available_ms = _epoch_ms(payload.get("ts_ms") or payload.get("timestamp"))
    if source_available_ms is None:
        return None, "available_at_missing"
    source_age = (now_ms - source_available_ms) / 1000.0
    if source_age < -MAX_FUTURE_CLOCK_SKEW_SECONDS:
        return None, "future_available_at"
    if source_age > SYMBOL_MAX_AGE_SECONDS:
        return None, "stale"
    rows = _closed_rows(_series(payload), timeframe, source_available_ms)
    value, event_open_ms = _closed_parallel_value(
        _inner_data(payload),
        timeframe,
        source_available_ms,
        "longShortRatios",
        "longShortRatio",
        "ratios",
        "values",
    )
    if value is None:
        value = _last_num(rows, "close")
        event_open_ms = _latest_closed_open_ms(rows)
    if value is None or value <= 0 or event_open_ms is None:
        return None, "no_closed_numeric_observation"
    interval_seconds = TIMEFRAME_SECONDS.get(timeframe)
    if interval_seconds is None:
        return None, "unsupported_timeframe"
    cutoff_ms = event_open_ms + (interval_seconds * 1000)
    if cutoff_ms > source_available_ms:
        return None, "unfinished_interval"
    closed_bar_age_ms = source_available_ms - cutoff_ms
    if closed_bar_age_ms > interval_seconds * 1000:
        return None, "stale_closed_bar"
    return {
        "value": value,
        "event_open_ms": event_open_ms,
        "cutoff_ms": cutoff_ms,
        "source_available_ms": source_available_ms,
        "source_age": max(0.0, source_age),
        "closed_bar_age_seconds": closed_bar_age_ms / 1000.0,
    }, None


def _tail_list(inner: Any, *fields: str) -> float | None:
    """Long/short payloads store parallel arrays; return the last element."""
    if isinstance(inner, Mapping):
        for field in fields:
            arr = inner.get(field)
            if isinstance(arr, list) and arr:
                v = _f(arr[-1])
                if v is not None:
                    return v
    return None


def build_global_snapshot(client: Any) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    generated_at = _iso_from_ms(now_ms) or _utc_iso()
    members: dict[str, Any] = {}
    ages: list[float] = []
    available_times: list[int] = []
    cutoff_times: list[int] = []
    present = 0
    for name in GLOBAL_NAMES:
        payload = _get_json(client, f"features:global_coinank:{name}:latest")
        if not isinstance(payload, Mapping):
            members[name] = None
            continue
        value = _f(payload.get("value"))
        source_available_ms = _epoch_ms(payload.get("available_at_ms"))
        feature_cutoff_ms = _epoch_ms(payload.get("feature_cutoff_ms"))
        source_generated_ms = _epoch_ms(payload.get("generated_at_ms"))
        age = (
            round((now_ms - source_available_ms) / 1000.0, 1)
            if source_available_ms is not None
            else None
        )
        valid = bool(
            value is not None
            and _global_value_in_domain(name, value, payload)
            and age is not None
            and -MAX_FUTURE_CLOCK_SKEW_SECONDS <= age <= GLOBAL_MAX_AGE_SECONDS
            and source_generated_ms is not None
            and source_generated_ms <= now_ms + (MAX_FUTURE_CLOCK_SKEW_SECONDS * 1000)
        )
        members[name] = {
            "value": value if valid else None,
            "age_seconds": age,
            "n": payload.get("n"),
            "universe_n": payload.get("universe_n"),
            "coverage_ratio": payload.get("coverage_ratio"),
            "unit": payload.get("unit"),
            "invalid_reason": payload.get("invalid_reason"),
            "source_available_at": _iso_from_ms(source_available_ms),
            "feature_cutoff": _iso_from_ms(feature_cutoff_ms),
            "valid": valid,
        }
        if not valid or source_available_ms is None or feature_cutoff_ms is None:
            continue
        present += 1
        ages.append(max(0.0, age or 0.0))
        available_times.append(source_available_ms)
        cutoff_times.append(feature_cutoff_ms)
        _set_json(
            client,
            GLOBAL_MEMBER_KEY.format(name=name),
            {
                "name": name,
                "value": value,
                "age_seconds": age,
                "source": "coinank_global",
                "event_time": _iso_from_ms(feature_cutoff_ms),
                "ingested_at": _iso_from_ms(source_available_ms),
                "available_at": _iso_from_ms(source_available_ms),
                "feature_cutoff": _iso_from_ms(feature_cutoff_ms),
                "generated_at": generated_at,
                "generated_utc": generated_at,
                "temporal_contract_valid": True,
            },
        )
    freshest = min(ages) if ages else None
    oldest = max(ages) if ages else None
    coverage_complete = present == len(SUPPORTED_GLOBAL_NAMES)
    aggregate_available_ms = max(available_times) if available_times else None
    aggregate_cutoff_ms = max(cutoff_times) if cutoff_times else None
    snapshot = {
        "schema_version": "v2_coinank_global_snapshot_v1",
        "generated_at": generated_at,
        "generated_utc": generated_at,
        "source": "legacy_features_global_coinank",
        "members": members,
        "present_member_count": present,
        "freshest_member_age_seconds": freshest,
        "oldest_member_age_seconds": oldest,
        "coverage_complete": coverage_complete,
        "supported_global_members": list(SUPPORTED_GLOBAL_NAMES),
        "unsupported_global_members": sorted(set(GLOBAL_NAMES) - set(SUPPORTED_GLOBAL_NAMES)),
        "actual_payload_present": present > 0,
        "is_fresh": bool(
            coverage_complete and oldest is not None and oldest <= GLOBAL_MAX_AGE_SECONDS
        ),
        "event_time": _iso_from_ms(aggregate_cutoff_ms),
        "ingested_at": _iso_from_ms(aggregate_available_ms),
        "available_at": _iso_from_ms(aggregate_available_ms),
        "feature_cutoff": _iso_from_ms(aggregate_cutoff_ms),
        "temporal_contract_valid": aggregate_available_ms is not None
        and aggregate_available_ms <= now_ms + (MAX_FUTURE_CLOCK_SKEW_SECONDS * 1000),
        "market_regime_context": {
            "total_open_interest_usd": (members.get("total_oi") or {}).get("value"),
            "aggregate_long_short_ratio": (members.get("long_short_ratio") or {}).get("value"),
            "avg_funding_rate": (members.get("funding_rate_avg") or {}).get("value"),
            "total_liquidations_usd": (members.get("total_liquidations") or {}).get("value"),
            "market_sentiment": (members.get("market_sentiment") or {}).get("value"),
            "fear_greed": (members.get("fear_greed") or {}).get("value"),
            "alt_season_index": (members.get("alt_season_index") or {}).get("value"),
        },
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
    }
    _set_json(client, GLOBAL_SNAPSHOT_KEY, snapshot)
    return snapshot


def _discover_symbol_tf(client: Any) -> dict[str, set[str]]:
    """Bounded scan of latest:coinank:* to find fresh (symbol, timeframe) pairs."""
    out: dict[str, set[str]] = {}
    n = 0
    t0 = time.time()
    try:
        for pattern in ("latest:coinank_endpoint:*", "latest:coinank:*"):
            for key in client.scan_iter(match=pattern, count=1000):
                n += 1
                parts = key.split(":")
                if len(parts) >= 5:
                    symbol = _canonical_symbol(parts[-2])
                    tf = parts[-1]
                    if symbol is not None and tf in TIMEFRAME_SECONDS:
                        out.setdefault(symbol, set()).add(tf)
                if n >= SCAN_CAP or time.time() - t0 > SCAN_BUDGET_SECONDS:
                    break
            if n >= SCAN_CAP or time.time() - t0 > SCAN_BUDGET_SECONDS:
                break
    except Exception:
        pass
    return out


def _extract_symbol_features(client: Any, symbol: str, timeframe: str) -> dict[str, Any] | None:
    symbol = _canonical_symbol(symbol) or ""
    interval_seconds = TIMEFRAME_SECONDS.get(timeframe)
    if not symbol or interval_seconds is None:
        return None
    now_ms = int(time.time() * 1000)
    generated_at = _iso_from_ms(now_ms) or _utc_iso()
    feats: dict[str, Any] = {}
    feature_units: dict[str, str] = {}
    feature_provenance: dict[str, Any] = {}
    source_clocks: dict[str, Any] = {}
    source_ages: list[float] = []
    source_available_times: list[int] = []
    feature_cutoffs: list[int] = []
    families_observed = 0
    families_present: set[str] = set()
    missing_feature_flags: list[str] = []
    stale_feature_flags: list[str] = []
    for family in FAMILIES:
        if family == "long_short":
            primary_payload = _get_endpoint_payload(
                client,
                family=family,
                symbol=symbol,
                timeframe=timeframe,
            )
            variant_payloads = {
                variant: _get_long_short_variant_payload(
                    client,
                    variant=variant,
                    symbol=symbol,
                    timeframe=timeframe,
                )
                for variant in LONG_SHORT_VARIANTS
            }
            if not isinstance(primary_payload, Mapping) and not any(
                isinstance(payload, Mapping) for payload in variant_payloads.values()
            ):
                missing_feature_flags.append("coinank_long_short_missing")
                continue
            families_observed += 1
            family_feats: dict[str, float] = {}
            family_units: dict[str, str] = {}
            admitted_clocks: dict[str, Any] = {}

            def admit_long_short(
                payload: Mapping[str, Any] | None,
                *,
                clock_name: str,
                endpoint: str,
                feature_name: str,
                semantic: str,
                request_type: str | None = None,
            ) -> bool:
                if not isinstance(payload, Mapping):
                    missing_feature_flags.append(
                        f"coinank_long_short_{clock_name}_missing"
                    )
                    return False
                observation, reason = _long_short_variant_observation(
                    payload,
                    timeframe=timeframe,
                    now_ms=now_ms,
                )
                if observation is None:
                    flag = f"coinank_long_short_{clock_name}_{reason or 'invalid'}"
                    if reason in {
                        "future_available_at",
                        "stale",
                        "stale_closed_bar",
                        "unfinished_interval",
                    }:
                        stale_feature_flags.append(flag)
                    else:
                        missing_feature_flags.append(flag)
                    return False
                value = float(observation["value"])
                family_feats[feature_name] = value
                family_units[feature_name] = "ratio"
                feature_provenance[feature_name] = {
                    "endpoint": endpoint,
                    "request_type": request_type,
                    "semantic": semantic,
                }
                source_ages.append(float(observation["source_age"]))
                source_available_times.append(
                    int(observation["source_available_ms"])
                )
                feature_cutoffs.append(int(observation["cutoff_ms"]))
                admitted_clocks[clock_name] = {
                    "endpoint": endpoint,
                    "request_type": request_type,
                    "semantic": semantic,
                    "bar_open_time": _iso_from_ms(
                        int(observation["event_open_ms"])
                    ),
                    "event_time": _iso_from_ms(int(observation["cutoff_ms"])),
                    "available_at": _iso_from_ms(
                        int(observation["source_available_ms"])
                    ),
                    "feature_cutoff": _iso_from_ms(
                        int(observation["cutoff_ms"])
                    ),
                    "source_age_seconds": round(
                        float(observation["source_age"]), 1
                    ),
                    "closed_bar_age_seconds": round(
                        float(observation["closed_bar_age_seconds"]), 1
                    ),
                }
                return True

            primary_present = admit_long_short(
                primary_payload,
                clock_name="global_account_ratio",
                endpoint="ls_global_account_ratio",
                feature_name="coinank_global_account_long_short_ratio",
                semantic="global_account_ratio",
            )
            if primary_present:
                family_feats["coinank_long_short_ratio"] = family_feats[
                    "coinank_global_account_long_short_ratio"
                ]
                family_units["coinank_long_short_ratio"] = "ratio"
                feature_provenance["coinank_long_short_ratio"] = {
                    "endpoint": "ls_global_account_ratio",
                    "request_type": None,
                    "semantic": "global_account_ratio",
                    "alias_of": "coinank_global_account_long_short_ratio",
                }
            for variant, (feature_name, semantic) in LONG_SHORT_VARIANTS.items():
                admit_long_short(
                    variant_payloads[variant],
                    clock_name=variant,
                    endpoint="ls_kline",
                    feature_name=feature_name,
                    semantic=semantic,
                    request_type=variant,
                )
            if not family_feats:
                continue
            feats.update(family_feats)
            feature_units.update(family_units)
            families_present.add(family)
            source_clocks[family] = {
                "generic_alias_source": (
                    "ls_global_account_ratio" if primary_present else None
                ),
                "observations": admitted_clocks,
            }
            continue

        payload = _get_endpoint_payload(
            client,
            family=family,
            symbol=symbol,
            timeframe=timeframe,
        )
        if not isinstance(payload, Mapping):
            missing_feature_flags.append(f"coinank_{family}_missing")
            continue
        families_observed += 1
        source_available_ms = _epoch_ms(payload.get("ts_ms") or payload.get("timestamp"))
        if source_available_ms is None:
            missing_feature_flags.append(f"coinank_{family}_available_at_missing")
            continue
        source_age = (now_ms - source_available_ms) / 1000.0
        if source_age < -MAX_FUTURE_CLOCK_SKEW_SECONDS:
            stale_feature_flags.append(f"coinank_{family}_future_available_at")
            continue
        if source_age > SYMBOL_MAX_AGE_SECONDS:
            stale_feature_flags.append(f"coinank_{family}_stale")
            continue
        rows = _closed_rows(_series(payload), timeframe, source_available_ms)
        event_open_ms: int | None = None
        family_has_numeric_feature = False
        endpoint = str(payload.get("endpoint") or "")
        family_feats: dict[str, float] = {}
        family_units: dict[str, str] = {}
        if family == "funding":
            raw_rate = _last_num(rows, "close")
            event_open_ms = _latest_closed_open_ms(rows)
            if raw_rate is not None and endpoint == "fundingRate_kline":
                # CoinAnk fundingRate/kline is reported in percentage points;
                # system funding contracts use a fractional rate.
                normalized_rate = raw_rate / 100.0
                if abs(normalized_rate) <= 0.05:
                    family_feats["coinank_funding_rate"] = normalized_rate
                    family_feats["coinank_funding_rate_raw_percent_points"] = raw_rate
                    family_units[
                        "coinank_funding_rate"
                    ] = "fraction_per_provider_funding_interval_duration_unknown"
                    family_units[
                        "coinank_funding_rate_raw_percent_points"
                    ] = "percent_points_per_provider_funding_interval_duration_unknown"
                    feature_provenance["coinank_funding_rate"] = {
                        "endpoint": "fundingRate_kline",
                        "provider_unit": "percent_points_per_funding_interval",
                        "normalized_scale": "divide_by_100",
                        "funding_interval_duration_known": False,
                        "cross_symbol_comparable": False,
                    }
                    feature_provenance[
                        "coinank_funding_rate_raw_percent_points"
                    ] = {
                        "endpoint": "fundingRate_kline",
                        "funding_interval_duration_known": False,
                        "cross_symbol_comparable": False,
                    }
                    family_has_numeric_feature = True
                else:
                    stale_feature_flags.append("coinank_funding_rate_out_of_contract_range")
            elif raw_rate is not None:
                missing_feature_flags.append("coinank_funding_rate_unit_ambiguous")
        elif family == "open_interest":
            value = _last_num(
                rows, "openInterest", "coinvalue", "coinValue", "value", "close")
            event_open_ms = _latest_closed_open_ms(rows)
            if value is not None and value >= 0:
                family_feats["coinank_open_interest"] = value
                # The provider endpoint does not carry a machine-readable unit.
                # Preserve the observation but do not call it contracts or USD.
                family_units[
                    "coinank_open_interest"
                ] = "provider_reported_open_interest_unit_unknown"
                family_has_numeric_feature = True
        elif family == "liquidations":
            lt = _last_num(rows, "longTurnover")
            st = _last_num(rows, "shortTurnover")
            event_open_ms = _latest_closed_open_ms(rows)
            if lt is not None and st is not None and lt >= 0 and st >= 0:
                family_feats["coinank_liquidation_long_turnover"] = lt
                family_feats["coinank_liquidation_short_turnover"] = st
                family_feats["coinank_liquidation_imbalance_usd"] = (
                    lt - st
                )
                family_units["coinank_liquidation_long_turnover"] = "usd"
                family_units["coinank_liquidation_short_turnover"] = "usd"
                family_units["coinank_liquidation_imbalance_usd"] = "usd"
                family_has_numeric_feature = True
        elif family == "market_order_flow":
            buy = _last_num(rows, "buy", "buyVol", "takerBuy")
            sell = _last_num(rows, "sell", "sellVol", "takerSell")
            latest_row = rows[-1] if rows else None
            if isinstance(latest_row, (list, tuple)):
                buy = _f(latest_row[1]) if len(latest_row) > 1 else buy
                sell = _f(latest_row[2]) if len(latest_row) > 2 else sell
            event_open_ms = _latest_closed_open_ms(rows)
            if (
                buy is not None
                and sell is not None
                and buy >= 0
                and sell >= 0
            ):
                family_feats["coinank_taker_buy"] = buy
                family_feats["coinank_taker_buy_value_usd"] = buy
                family_feats["coinank_taker_sell"] = sell
                family_feats["coinank_taker_sell_value_usd"] = sell
                family_units["coinank_taker_buy"] = "usd"
                family_units["coinank_taker_buy_value_usd"] = "usd"
                family_units["coinank_taker_sell"] = "usd"
                family_units["coinank_taker_sell_value_usd"] = "usd"
                family_has_numeric_feature = True
        if not family_has_numeric_feature or event_open_ms is None:
            missing_feature_flags.append(f"coinank_{family}_no_closed_numeric_observation")
            continue
        cutoff_ms = event_open_ms + (interval_seconds * 1000)
        if cutoff_ms > source_available_ms:
            stale_feature_flags.append(f"coinank_{family}_unfinished_interval")
            continue
        closed_bar_age_ms = source_available_ms - cutoff_ms
        if closed_bar_age_ms > interval_seconds * 1000:
            stale_feature_flags.append(f"coinank_{family}_stale_closed_bar")
            continue
        feats.update(family_feats)
        feature_units.update(family_units)
        families_present.add(family)
        source_ages.append(max(0.0, source_age))
        source_available_times.append(source_available_ms)
        feature_cutoffs.append(cutoff_ms)
        source_clocks[family] = {
            "endpoint": endpoint or None,
            "bar_open_time": _iso_from_ms(event_open_ms),
            "event_time": _iso_from_ms(cutoff_ms),
            "ingested_at": _iso_from_ms(source_available_ms),
            "available_at": _iso_from_ms(source_available_ms),
            "feature_cutoff": _iso_from_ms(cutoff_ms),
            "source_age_seconds": round(max(0.0, source_age), 1),
            "closed_bar_age_seconds": round(closed_bar_age_ms / 1000.0, 1),
        }
    if not families_present or not feats:
        return None
    # Derived directional sub-score in [-1, 1]: positive funding + long-heavy
    # long/short + long-liquidation dominance => crowded-long risk (bearish
    # squeeze context). Paper/analysis only; never an approval.
    fr = feats.get("coinank_funding_rate")
    ls = feats.get("coinank_long_short_ratio")
    imb = feats.get("coinank_liquidation_imbalance_usd")
    parts, weights = [], []
    if fr is not None and (
        feature_provenance.get("coinank_funding_rate", {}).get(
            "funding_interval_duration_known"
        ) is True
    ):
        parts.append(max(-1.0, min(1.0, fr * 2000.0))); weights.append(1.0)
    if ls is not None:
        parts.append(max(-1.0, min(1.0, (ls - 1.0)))); weights.append(1.0)
    if imb is not None:
        parts.append(max(-1.0, min(1.0, imb / 1_000_000.0))); weights.append(0.5)
    score = round(sum(p * w for p, w in zip(parts, weights)) / sum(weights), 6) if weights else None
    if score is not None:
        feats["coinank_derivatives_score"] = score
        feature_units["coinank_derivatives_score"] = "normalized_score_minus1_to_plus1"
    aggregate_available_ms = max(source_available_times) if source_available_times else None
    aggregate_cutoff_ms = max(feature_cutoffs) if feature_cutoffs else None
    temporal_valid = bool(
        aggregate_available_ms is not None
        and aggregate_cutoff_ms is not None
        and aggregate_cutoff_ms <= aggregate_available_ms <= now_ms + (
            MAX_FUTURE_CLOCK_SKEW_SECONDS * 1000
        )
    )
    if not temporal_valid:
        return None
    return {
        "schema_version": "v2_coinank_symbol_feature_v1",
        "provider": "coinank",
        "symbol": symbol,
        "timeframe": timeframe,
        "generated_at": generated_at,
        "generated_utc": generated_at,
        "event_time": _iso_from_ms(aggregate_cutoff_ms),
        "ingested_at": _iso_from_ms(aggregate_available_ms),
        "available_at": _iso_from_ms(aggregate_available_ms),
        "feature_cutoff": _iso_from_ms(aggregate_cutoff_ms),
        "temporal_contract_valid": temporal_valid,
        "source_freshness_seconds": round(max(source_ages), 1) if source_ages else None,
        "families_observed": families_observed,
        "families_present": len(families_present),
        "family_names_present": sorted(families_present),
        "features": feats,
        "feature_units": feature_units,
        "feature_provenance": feature_provenance,
        "source_clocks": source_clocks,
        "missing_feature_flags": sorted(set(missing_feature_flags)),
        "stale_feature_flags": sorted(set(stale_feature_flags)),
        "numeric_feature_count": len(feats),
        "coinank_derivatives_score": score,
        "actual_payload_present": True,
        "feature_eligible": True,
        "trainer_consumable": False,
        "valid_for_prediction": False,
        "valid_for_paper": False,
        "consumer_hold_reason": "COINANK_FEATURE_NOT_BOUND_TO_TRAINER_PUBLICATION_RECEIPT",
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
    }


def run_once(client: Any = None, *, max_symbols: int = 200) -> dict[str, Any]:
    client = client if client is not None else _connect_redis()
    if client is None:
        return {"status": "NO_REDIS", "written": 0}
    global_snapshot = build_global_snapshot(client)
    discovered = _discover_symbol_tf(client)
    symbol_written = 0
    feature_written = 0
    symbols_covered: list[str] = []
    for symbol in sorted(discovered)[:max_symbols]:
        best_payload = None
        for tf in sorted(discovered[symbol]):
            payload = _extract_symbol_features(client, symbol, tf)
            if payload is None:
                continue
            if _set_json(client, FEATURE_KEY.format(symbol=symbol, timeframe=tf), payload):
                feature_written += 1
            if best_payload is None or (
                payload.get("features")
                and len(payload["features"]) > len(best_payload.get("features") or {})
            ):
                best_payload = payload
        if best_payload is not None:
            consolidated = {
                **best_payload,
                "schema_version": "v2_coinank_symbol_intel_v1",
                "consolidated_timeframe_context_only": True,
                "cross_timeframe_fallback_allowed": False,
            }
            if _set_json(client, SYMBOL_KEY.format(symbol=symbol), consolidated):
                symbol_written += 1
                symbols_covered.append(symbol)
    global_fresh = global_snapshot.get("is_fresh") is True
    actual_payload_present = symbol_written > 0 or bool(
        global_snapshot.get("actual_payload_present")
    )
    if global_fresh and symbol_written > 0:
        provider_status = "ACTIVE"
    elif actual_payload_present:
        provider_status = "PARTIAL"
    else:
        provider_status = "STALE"
    health = {
        "schema_version": "v2_coinank_intel_bridge_health_v1",
        "provider": "coinank",
        "generated_utc": _utc_iso(),
        "status": provider_status,
        "dashboard_color": "green" if provider_status == "ACTIVE" else "yellow",
        "dashboard_color_reason": "coinank_intel_bridge",
        "actual_payload_count": symbol_written + global_snapshot.get("present_member_count", 0),
        "actual_payload_present": actual_payload_present,
        "feature_count": feature_written,
        "consumer_roles": [
            "altdata_confluence",
            "altdata_symbol_scoring",
            "universe_coverage",
            "liquidation_context",
        ],
        "consumer_count": 4,
        "trainer_consumable": False,
        "valid_for_prediction": False,
        "valid_for_paper": False,
        "consumer_hold_reason": "COINANK_FEATURE_NOT_BOUND_TO_TRAINER_PUBLICATION_RECEIPT",
        "symbols_covered": symbols_covered[:20],
        "global_present_members": global_snapshot.get("present_member_count"),
        "global_freshest_age_seconds": global_snapshot.get("freshest_member_age_seconds"),
        "global_oldest_age_seconds": global_snapshot.get("oldest_member_age_seconds"),
        "global_coverage_complete": global_snapshot.get("coverage_complete"),
        "heartbeat_only": False,
        "routes_to_live": False,
        "places_real_order": False,
        "live_gate": "blocked_human_only",
    }
    _set_json(client, PROVIDER_HEALTH_KEY, health, ex=300)
    _set_json(client, PROVIDER_FEATURE_BRIDGE_KEY, {
        **health, "schema_version": "v2_coinank_feature_bridge_status_v1",
        "feature_key_template": FEATURE_KEY,
    }, ex=300)
    status = {
        "schema_version": "v2_coinank_intel_bridge_status_v1",
        "generated_utc": _utc_iso(),
        "global_present_members": global_snapshot.get("present_member_count"),
        "global_is_fresh": global_snapshot.get("is_fresh"),
        "symbols_discovered": len(discovered),
        "symbol_intel_written": symbol_written,
        "feature_payloads_written": feature_written,
        "written": symbol_written + feature_written + 1,
    }
    _set_json(client, STATUS_KEY, status, ex=300)
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--max-symbols", type=int, default=200)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    while True:
        result = run_once(max_symbols=args.max_symbols)
        if args.json:
            print(json.dumps(result, default=str))
        if not args.loop:
            return 0 if result.get("written", 0) > 0 else 1
        time.sleep(max(15, args.interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
