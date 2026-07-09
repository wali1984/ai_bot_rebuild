"""Santiment Pro background ingestor for V2 paper/shadow alt-data.

The client is a producer only. It calls Santiment from a background
worker, normalizes scalar features, and writes V2-prefixed Redis keys
that PPO/MASA, symbol scoring, and feature pipelines can read locally.

It never places orders, never mutates exchange state, never writes old
Redis keys, and never returns or persists raw API keys.
"""
from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
import math
import os
import random
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Sequence

V2_REDIS_PREFIX = "v2:"
KEY_STATUS = "v2:altdata:santiment:status"
KEY_STATE = "v2:altdata:santiment:state"
KEY_PER_SYMBOL_PREFIX = "v2:altdata:santiment:symbol:"
KEY_PER_SYMBOL_TEMPLATE = KEY_PER_SYMBOL_PREFIX + "{symbol}"
KEY_FEATURE_PREFIX = "v2:features:santiment:"
KEY_FEATURE_TEMPLATE = KEY_FEATURE_PREFIX + "{symbol}:{timeframe}"
KEY_FEATURE_BRIDGE_STATUS = "v2:provider:santiment:feature_bridge_status"

SANTIMENT_API_URL = "https://api.santiment.net/graphql"
SANTIMENT_API_KEY_NAMES = (
    "SANTIMENT_API_KEY",
    "SANBASE_API_KEY",
    "SANTIMENT_PRO_API_KEY",
)
DEFAULT_VAULT_PATH = Path(".local_secrets/alternative_data.env")
DEFAULT_HTTP_TIMEOUT_SECONDS = 15.0
# SANBASE PRO plan restriction (verified 2026-07-06 against live API): metric
# queries must end >= 30 days in the past ("Allowed time restrictions" GraphQL
# error otherwise), so the default window targets the newest allowed data.
# The payload's feature_cutoff/provider_freshness_seconds expose the ~30-day
# lag; downstream must treat these as slow background context, never as fresh
# signal input. Real-time windows require a higher Santiment tier.
DEFAULT_INTERVAL = "1d"
DEFAULT_LOOKBACK = "utc_now-33d"
DEFAULT_TO = "utc_now-31d"
DEFAULT_EXECUTION_INTERVAL_SECONDS = 21_600
DEFAULT_REDIS_STATUS_TTL_SECONDS = 28_800
DEFAULT_REDIS_SYMBOL_TTL_SECONDS = 28_800
DEFAULT_REDIS_STATE_TTL_SECONDS = 28_800

# Real SANBASE PRO quota from live response headers (X-Ratelimit-Limit-*):
# 100/min, 1000/hour, 5000/month — the older 4k/80k values overstated the
# plan and would have burned the monthly budget in under a day.
PRO_RATE_LIMIT_PER_MINUTE = 100
PRO_RATE_LIMIT_PER_HOUR = 1_000
PRO_RATE_LIMIT_PER_MONTH = 5_000
RATE_LIMIT_SAFETY_FRACTION = 0.10
FRESH_DECISION_MAX_AGE_SECONDS = 1_800

SOURCE_STATUS_KEY_MISSING = "KEY_MISSING_NO_NETWORK"
SOURCE_STATUS_OK = "API_OK"
SOURCE_STATUS_RATE_LIMITED = "API_RATE_LIMITED_429"
SOURCE_STATUS_NETWORK_ERROR = "API_NETWORK_ERROR"
SOURCE_STATUS_PARSE_ERROR = "API_PARSE_ERROR"
SOURCE_STATUS_GRAPHQL_ERROR = "API_GRAPHQL_ERROR"

DEFAULT_METRICS = (
    "social_volume_total",
    "social_dominance_total",
    "sentiment_positive_total",
    "sentiment_negative_total",
    "sentiment_balance_total",
    "sentiment_weighted_total",
    # whale_transaction_count_1m is not a valid API metric ("not supported"
    # GraphQL error); the supported whale-count metric is the 100k+ USD bucket.
    "whale_transaction_count_100k_usd_to_inf",
    "exchange_inflow",
    "exchange_outflow",
    "exchange_balance",
    "percent_of_total_supply_on_exchanges",
    "transaction_volume",
    "active_addresses_24h",
    "network_growth",
    "age_consumed",
    "dormant_circulation_90d",
    "network_profit_loss",
    "mvrv_usd",
    "mvrv_usd_30d",
    "nvt",
    "price_daa_divergence",
    "dev_activity",
)

DEFAULT_SYMBOL_SLUGS = {
    "AAVE": "aave",
    "ADA": "cardano",
    "ARB": "arbitrum",
    "AVAX": "avalanche",
    "BNB": "bnb",
    "BONK": "bonk",
    "BTC": "bitcoin",
    "DOGE": "dogecoin",
    "ENA": "ethena",
    "ETH": "ethereum",
    "FLOKI": "floki",
    "LINK": "chainlink",
    "LTC": "litecoin",
    "NEAR": "near-protocol",
    "OP": "optimism",
    "PEPE": "pepe",
    "PENGU": "pudgy-penguins",
    "SHIB": "shiba-inu",
    "SOL": "solana",
    "SUI": "sui",
    "UNI": "uniswap",
    "WIF": "dogwifhat",
    "XRP": "xrp",
}

_SAFE_METRIC_RE = re.compile(r"^[A-Za-z0-9_]+$")
_SAFE_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        out = float(value)
    elif isinstance(value, str):
        try:
            out = float(value)
        except ValueError:
            return None
    else:
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _clamp01(value: float) -> float:
    return _clamp(value, 0.0, 1.0)


def _round_score(value: float | None) -> float | None:
    return None if value is None else round(float(value), 6)


def _read_env_assignment(path: Path, name: str) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        if key != name:
            continue
        return value.strip().strip("'\"") or None
    return None


def resolve_api_key(*, vault_path: Path = DEFAULT_VAULT_PATH) -> str | None:
    for name in SANTIMENT_API_KEY_NAMES:
        value = os.environ.get(name) or _read_env_assignment(vault_path, name)
        if value:
            return value
    return None


def api_key_present(*, vault_path: Path = DEFAULT_VAULT_PATH) -> bool:
    return bool(resolve_api_key(vault_path=vault_path))


def symbol_to_santiment_slug(symbol: str) -> str:
    text = str(symbol or "").strip().upper()
    for suffix in ("USDT", "USDC", "USD", "BUSD"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    while text.startswith("1000") and len(text) > 4:
        text = text[4:]
    return DEFAULT_SYMBOL_SLUGS.get(text, text.lower().replace("_", "-"))


def normalize_symbols_to_slugs(symbols: Sequence[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for symbol in symbols:
        normalized = str(symbol or "").strip().upper()
        if not normalized:
            continue
        slug = symbol_to_santiment_slug(normalized)
        if _SAFE_SLUG_RE.fullmatch(slug):
            out[normalized] = slug
    return out


def sanitize_metrics(metrics: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for metric in metrics:
        text = str(metric or "").strip()
        if not text or text in seen:
            continue
        if not _SAFE_METRIC_RE.fullmatch(text):
            continue
        seen.add(text)
        out.append(text)
    return tuple(out)


def metric_alias(metric: str) -> str:
    return "m_" + re.sub(r"[^A-Za-z0-9_]", "_", metric)


def build_batch_query(
    *,
    slugs: Sequence[str],
    metrics: Sequence[str],
    interval: str = DEFAULT_INTERVAL,
    from_expr: str = DEFAULT_LOOKBACK,
    to_expr: str = DEFAULT_TO,
    include_incomplete_data: bool = False,
) -> str:
    clean_slugs = tuple(slug for slug in slugs if _SAFE_SLUG_RE.fullmatch(slug))
    clean_metrics = sanitize_metrics(metrics)
    if not clean_slugs or not clean_metrics:
        raise ValueError("Santiment query requires at least one safe slug and metric")
    slug_list = ", ".join(json.dumps(slug) for slug in clean_slugs)
    include_incomplete = "true" if include_incomplete_data else "false"
    lines = ["query SantimentProBatch {"]
    for metric in clean_metrics:
        alias = metric_alias(metric)
        lines.extend(
            [
                f'  {alias}: getMetric(metric: "{metric}") {{',
                "    timeseriesDataPerSlugJson(",
                f"      selector: {{ slugs: [{slug_list}] }}",
                f'      from: "{from_expr}"',
                f'      to: "{to_expr}"',
                f'      interval: "{interval}"',
                f"      includeIncompleteData: {include_incomplete}",
                "    )",
                "  }",
            ]
        )
    lines.append("}")
    return "\n".join(lines)


def estimated_query_cost(metrics: Sequence[str]) -> int:
    # Santiment counts each getMetric GraphQL query as one API call even when
    # many slugs are batched inside the same query.
    return max(1, len(sanitize_metrics(metrics)))


@dataclasses.dataclass(frozen=True)
class SantimentHttpResult:
    status_code: int | None
    body: Any | None
    headers: Mapping[str, str] = dataclasses.field(default_factory=dict)
    error: str | None = None
    request_attempted: bool = True


@dataclasses.dataclass
class RateLimitState:
    minute_limit: int = PRO_RATE_LIMIT_PER_MINUTE
    hour_limit: int = PRO_RATE_LIMIT_PER_HOUR
    month_limit: int = PRO_RATE_LIMIT_PER_MONTH
    remaining_minute: int | None = None
    remaining_hour: int | None = None
    remaining_month: int | None = None
    reset_seconds: int | None = None
    last_request_monotonic: float | None = None
    last_response_status: str | None = None
    consecutive_failures: int = 0
    last_429_monotonic: float | None = None
    local_estimated_cost: int = 0

    def as_payload(self) -> dict[str, Any]:
        return {
            "minute_limit": self.minute_limit,
            "hour_limit": self.hour_limit,
            "month_limit": self.month_limit,
            "remaining_minute": self.remaining_minute,
            "remaining_hour": self.remaining_hour,
            "remaining_month": self.remaining_month,
            "reset_seconds": self.reset_seconds,
            "last_request_monotonic": self.last_request_monotonic,
            "last_response_status": self.last_response_status,
            "consecutive_failures": int(self.consecutive_failures),
            "last_429_monotonic": self.last_429_monotonic,
            "local_estimated_cost": int(self.local_estimated_cost),
        }


class AsyncTokenBucket:
    def __init__(
        self,
        *,
        rate_per_minute: int = PRO_RATE_LIMIT_PER_MINUTE,
        capacity: int = PRO_RATE_LIMIT_PER_MINUTE,
        time_func: Callable[[], float] = time.monotonic,
        sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.rate_per_second = max(1.0, float(rate_per_minute)) / 60.0
        self.capacity = max(1.0, float(capacity))
        self.tokens = self.capacity
        self.updated_at = time_func()
        self.time_func = time_func
        self.sleep_func = sleep_func

    async def consume(self, cost: int = 1) -> None:
        required = max(1.0, float(cost))
        while True:
            now = self.time_func()
            elapsed = max(0.0, now - self.updated_at)
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate_per_second)
            self.updated_at = now
            if self.tokens >= required:
                self.tokens -= required
                return
            await self.sleep_func((required - self.tokens) / self.rate_per_second)


HttpPost = Callable[
    [str, Mapping[str, str], Mapping[str, Any], float],
    SantimentHttpResult | Awaitable[SantimentHttpResult],
]


def _default_http_post(
    url: str,
    headers: Mapping[str, str],
    body: Mapping[str, Any],
    timeout: float,
) -> SantimentHttpResult:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers=dict(headers),
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw.strip() else {}
            return SantimentHttpResult(
                status_code=int(getattr(resp, "status", 200)),
                body=parsed,
                headers={k: v for k, v in resp.headers.items()},
            )
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed: Any = json.loads(raw) if raw.strip() else {}
        except ValueError:
            parsed = {"body": raw[:200]}
        return SantimentHttpResult(
            status_code=int(exc.code),
            body=parsed,
            headers={k: v for k, v in exc.headers.items()},
            error=f"HTTP_{exc.code}",
        )
    except TimeoutError:
        return SantimentHttpResult(
            status_code=None,
            body=None,
            error="TIMEOUT",
        )
    except OSError as exc:
        return SantimentHttpResult(
            status_code=None,
            body=None,
            error=exc.__class__.__name__,
        )


def parse_rate_limit_headers(headers: Mapping[str, str]) -> dict[str, int | None]:
    lower = {str(k).lower(): str(v) for k, v in dict(headers or {}).items()}

    def _int(name: str) -> int | None:
        value = lower.get(name)
        if value is None:
            return None
        try:
            return int(float(value))
        except ValueError:
            return None

    return {
        "remaining_minute": _int("x-ratelimit-remaining-minute"),
        "remaining_hour": _int("x-ratelimit-remaining-hour"),
        "remaining_month": _int("x-ratelimit-remaining-month"),
        "reset": _int("x-ratelimit-reset"),
    }


def _reset_wait_seconds(value: int | None, *, now_epoch: float) -> int:
    if value is None:
        return 60
    if value > 1_000_000_000:
        return max(0, int(value - now_epoch))
    return max(0, int(value))


def _latest_forward_filled(
    points: Sequence[Mapping[str, Any]],
) -> tuple[float | None, str | None, bool]:
    if not points:
        return None, None, False
    latest_datetime = None
    if isinstance(points[-1], Mapping):
        latest_datetime = points[-1].get("datetime") or points[-1].get("time")
    latest_value = _coerce_float(points[-1].get("value")) if isinstance(points[-1], Mapping) else None
    if latest_value is not None:
        return latest_value, str(latest_datetime) if latest_datetime else None, False
    for point in reversed(points[:-1]):
        if not isinstance(point, Mapping):
            continue
        value = _coerce_float(point.get("value"))
        if value is not None:
            dt = point.get("datetime") or point.get("time") or latest_datetime
            return value, str(dt) if dt else None, True
    return None, str(latest_datetime) if latest_datetime else None, False


def _json_payload(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def _extract_per_slug_points(block: Any) -> dict[str, list[Mapping[str, Any]]]:
    if not isinstance(block, Mapping):
        return {}
    raw = (
        block.get("timeseriesDataPerSlugJson")
        or block.get("timeseriesDataPerSlug")
        or block.get("timeseriesDataJson")
        or block.get("timeseriesData")
    )
    parsed = _json_payload(raw)
    out: dict[str, list[Mapping[str, Any]]] = {}
    if isinstance(parsed, Mapping):
        for slug, points in parsed.items():
            if isinstance(points, Sequence) and not isinstance(points, (str, bytes)):
                out[str(slug)] = [p for p in points if isinstance(p, Mapping)]
        return out
    if isinstance(parsed, Sequence) and not isinstance(parsed, (str, bytes)):
        # timeseriesDataPerSlugJson returns time-major rows:
        #   [{"datetime": ..., "data": [{"slug": ..., "value": ...}, ...]}, ...]
        # Pivot them to slug-major point lists so per-slug consumers work.
        time_major: dict[str, list[Mapping[str, Any]]] = {}
        for item in parsed:
            if not isinstance(item, Mapping):
                continue
            dt = item.get("datetime") or item.get("time")
            entries = item.get("data")
            if not dt or not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
                continue
            for entry in entries:
                if isinstance(entry, Mapping) and entry.get("slug") is not None:
                    time_major.setdefault(str(entry["slug"]), []).append(
                        {"datetime": dt, "value": entry.get("value")}
                    )
        if time_major:
            return time_major
        for item in parsed:
            if not isinstance(item, Mapping):
                continue
            slug = item.get("slug") or item.get("projectSlug")
            points = item.get("timeseriesData") or item.get("data") or item.get("values")
            if slug and isinstance(points, Sequence) and not isinstance(points, (str, bytes)):
                out[str(slug)] = [p for p in points if isinstance(p, Mapping)]
        if not out:
            out["__single__"] = [p for p in parsed if isinstance(p, Mapping)]
    return out


def _log_scaled(value: float | None, divisor: float) -> float | None:
    if value is None or value < 0:
        return None
    return _clamp01(math.log10(value + 1.0) / divisor)


def _sentiment_balance(
    positive: float | None,
    negative: float | None,
) -> float | None:
    if positive is None or negative is None:
        return None
    total = positive + negative
    if total <= 0:
        return None
    return _clamp((positive - negative) / total, -1.0, 1.0)


def _percent_supply_score(value: float | None) -> float | None:
    if value is None:
        return None
    pct = value / 100.0 if value > 1.0 else value
    return _clamp01(1.0 - pct)


def _score_from_metrics(values: Mapping[str, float | None]) -> dict[str, float | None]:
    social = _log_scaled(values.get("social_volume_total"), 6.0)
    whale = _log_scaled(
        values.get("whale_transaction_count_1m")
        if values.get("whale_transaction_count_1m") is not None
        else values.get("whale_transaction_count_100k_usd_to_inf"),
        3.0,
    )
    onchain = _log_scaled(values.get("active_addresses_24h"), 6.0)
    tx_volume = _log_scaled(values.get("transaction_volume"), 10.0)
    dev = _log_scaled(values.get("dev_activity"), 4.0)
    exchange_inflow_risk = _log_scaled(values.get("exchange_inflow"), 10.0)
    supply_shock = _percent_supply_score(
        values.get("percent_of_total_supply_on_exchanges")
    )
    sentiment = _sentiment_balance(
        values.get("sentiment_positive_total"),
        values.get("sentiment_negative_total"),
    )
    if sentiment is None and values.get("sentiment_positive_total") is not None:
        positive_score = _log_scaled(values.get("sentiment_positive_total"), 4.0)
        sentiment = None if positive_score is None else (positive_score * 2.0) - 1.0
    return {
        "santiment_social_volume_score": _round_score(social),
        "santiment_whale_activity_score": _round_score(whale),
        "santiment_sentiment_score": _round_score(sentiment),
        "santiment_onchain_activity_score": _round_score(
            _combine_optional((onchain, tx_volume, supply_shock))
        ),
        "santiment_dev_activity_score": _round_score(dev),
        "santiment_exchange_inflow_risk_score": _round_score(exchange_inflow_risk),
        "santiment_supply_on_exchanges_score": _round_score(supply_shock),
    }


def _combine_optional(values: Sequence[float | None]) -> float | None:
    real = [float(v) for v in values if v is not None]
    if not real:
        return None
    return _clamp01(sum(real) / len(real))


def normalize_batch_payload(
    body: Mapping[str, Any],
    *,
    slug_to_symbol: Mapping[str, str],
    metrics: Sequence[str],
    generated_utc: str | None = None,
) -> dict[str, dict[str, Any]]:
    now = generated_utc or utc_iso()
    data = body.get("data") if isinstance(body, Mapping) else None
    if not isinstance(data, Mapping):
        return {}
    clean_metrics = sanitize_metrics(metrics)
    by_symbol: dict[str, dict[str, Any]] = {}
    for symbol in sorted(slug_to_symbol.values()):
        by_symbol[symbol] = {
            "metric_values": {},
            "metric_datetimes": {},
            "forward_filled_metrics": [],
            "missing_feature_flags": [],
        }
    for metric in clean_metrics:
        alias = metric_alias(metric)
        per_slug = _extract_per_slug_points(data.get(alias))
        for slug, symbol in slug_to_symbol.items():
            points = per_slug.get(slug) or per_slug.get("__single__") or []
            value, dt, forward_filled = _latest_forward_filled(points)
            row = by_symbol[symbol]
            row["metric_values"][metric] = value
            row["metric_datetimes"][metric] = dt
            row[f"santiment_{metric}"] = _round_score(value)
            if forward_filled:
                row["forward_filled_metrics"].append(metric)
            if value is None:
                row["missing_feature_flags"].append(f"{metric}_missing")
    out: dict[str, dict[str, Any]] = {}
    for slug, symbol in slug_to_symbol.items():
        row = by_symbol[symbol]
        metric_datetimes = [
            _parse_utc(value) for value in row["metric_datetimes"].values() if value
        ]
        latest_dt = max((dt for dt in metric_datetimes if dt is not None), default=None)
        freshness = None
        if latest_dt is not None:
            now_dt = _parse_utc(now)
            if now_dt is not None:
                freshness = max(0, int((now_dt - latest_dt).total_seconds()))
        stale_flags = []
        data_latency_class = "CURRENT_OR_NEAR_REAL_TIME"
        if freshness is not None and freshness > FRESH_DECISION_MAX_AGE_SECONDS:
            stale_flags.append("sanbase_pro_delayed_data_window")
            data_latency_class = "SANBASE_PRO_DELAYED_NOT_LIVE_DECISION_FRESH"
        scores = _score_from_metrics(row["metric_values"])
        payload: dict[str, Any] = {
            "schema_version": "v2_altdata_santiment_symbol_signal_v1",
            "symbol": symbol,
            "slug": slug,
            "provider": "santiment",
            "source_status": SOURCE_STATUS_OK,
            "generated_utc": now,
            "available_at": now,
            "feature_cutoff": (
                latest_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
                if latest_dt is not None
                else None
            ),
            "provider_freshness_seconds": freshness,
            "data_latency_class": data_latency_class,
            "decision_fresh": not stale_flags,
            "metric_values": dict(row["metric_values"]),
            "metric_datetimes": dict(row["metric_datetimes"]),
            "forward_filled_metrics": sorted(set(row["forward_filled_metrics"])),
            "missing_feature_flags": sorted(set(row["missing_feature_flags"])),
            "stale_feature_flags": stale_flags,
            "source_metric_names": list(clean_metrics),
            "raw_values_exposed": False,
            "paper_shadow_only": True,
            "network_call_attempted": True,
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "may_not_override_strict_paper_fill_gate": True,
            "may_not_authorize_live_or_canary": True,
            "may_not_place_orders": True,
            "places_real_order": False,
            "approves_live": False,
            "approves_canary": False,
            "writes_old_redis": False,
            "exchange_mutation": False,
        }
        payload.update(scores)
        for metric, value in row["metric_values"].items():
            payload[f"santiment_{metric}"] = _round_score(value)
        out[symbol] = payload
    return out


def allowed_santiment_write_key(key: str) -> bool:
    return (
        key == KEY_STATUS
        or key == KEY_STATE
        or key == KEY_FEATURE_BRIDGE_STATUS
        or key.startswith(KEY_PER_SYMBOL_PREFIX)
        or key.startswith(KEY_FEATURE_PREFIX)
    ) and key.startswith(V2_REDIS_PREFIX)


def safe_redis_set(
    redis_client: Any,
    key: str,
    payload: Mapping[str, Any],
    *,
    ex: int = DEFAULT_REDIS_SYMBOL_TTL_SECONDS,
) -> bool:
    if redis_client is None or not allowed_santiment_write_key(key):
        return False
    try:
        redis_client.set(key, json.dumps(payload, sort_keys=True), ex=int(ex))
        return True
    except Exception:
        return False


def build_santiment_feature_payload(
    payload: Mapping[str, Any],
    *,
    timeframe: str = "1h",
) -> dict[str, Any]:
    symbol = str(payload.get("symbol") or "").upper()
    generated = str(payload.get("generated_utc") or utc_iso())
    feature_cutoff = payload.get("feature_cutoff")
    features: dict[str, float] = {}
    for key, value in payload.items():
        if not str(key).startswith("santiment_"):
            continue
        parsed = _coerce_float(value)
        if parsed is not None:
            features[str(key)] = parsed
    metric_values = payload.get("metric_values")
    if isinstance(metric_values, Mapping):
        for key, value in metric_values.items():
            parsed = _coerce_float(value)
            if parsed is not None:
                features[f"santiment_{key}"] = parsed
    missing = sorted(str(item) for item in (payload.get("missing_feature_flags") or []))
    stale = sorted(str(item) for item in (payload.get("stale_feature_flags") or []))
    actual_payload_present = bool(features)
    return {
        "schema_version": "santiment_feature_bridge_v1",
        "provider": "santiment",
        "symbol": symbol,
        "timeframe": timeframe,
        "generated_at": generated,
        "generated_utc": generated,
        "event_time": feature_cutoff,
        "available_at": payload.get("available_at") or generated,
        "feature_cutoff": feature_cutoff,
        "decision_time_safe": bool(feature_cutoff and (payload.get("available_at") or generated)),
        "features": features,
        "feature_names": sorted(features),
        "feature_count": len(features),
        "missing_feature_flags": missing,
        "stale_feature_flags": stale,
        "missing_mask": {name: True for name in missing},
        "missing_mask_true": bool(missing),
        "stale_mask": {name: True for name in stale},
        "stale_mask_true": bool(stale),
        "actual_payload_present": actual_payload_present,
        "heartbeat_only": not actual_payload_present,
        "provider_ready": actual_payload_present,
        "feature_bridge_ready": actual_payload_present,
        "status": "READY" if actual_payload_present else "PAYLOADS_PENDING",
        "data_latency_class": payload.get("data_latency_class"),
        "provider_freshness_seconds": payload.get("provider_freshness_seconds"),
        "trainer_consumption": True,
        "provider_tensor_consumption": True,
        "ppo_consumption": True,
        "masa_consumption": True,
        "risk_consumption": True,
        "orchestrator_consumption": True,
        "allocator_consumption": True,
        "paper_consumption": True,
        "live_dryrun_consumption": True,
        "feedback_attribution": True,
        "santiment_can_approve_trade_alone": False,
        "single_provider_can_approve": False,
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }


def _santiment_feature_bridge_status(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "santiment_feature_bridge_status_v1",
        "provider": "santiment",
        "generated_utc": payload.get("generated_utc") or payload.get("generated_at"),
        "symbol": payload.get("symbol"),
        "timeframe": payload.get("timeframe"),
        "available_at": payload.get("available_at"),
        "feature_cutoff": payload.get("feature_cutoff"),
        "decision_time_safe": payload.get("decision_time_safe"),
        "status": payload.get("status"),
        "feature_bridge_ready": payload.get("feature_bridge_ready"),
        "feature_count": payload.get("feature_count"),
        "missing_feature_flags": payload.get("missing_feature_flags"),
        "stale_feature_flags": payload.get("stale_feature_flags"),
        "missing_mask": payload.get("missing_mask"),
        "missing_mask_true": payload.get("missing_mask_true"),
        "stale_mask": payload.get("stale_mask"),
        "stale_mask_true": payload.get("stale_mask_true"),
        "actual_payload_present": payload.get("actual_payload_present"),
        "heartbeat_only": payload.get("heartbeat_only"),
        "trainer_consumption": payload.get("trainer_consumption"),
        "provider_tensor_consumption": payload.get("provider_tensor_consumption"),
        "ppo_consumption": payload.get("ppo_consumption"),
        "masa_consumption": payload.get("masa_consumption"),
        "risk_consumption": payload.get("risk_consumption"),
        "orchestrator_consumption": payload.get("orchestrator_consumption"),
        "allocator_consumption": payload.get("allocator_consumption"),
        "paper_consumption": payload.get("paper_consumption"),
        "live_dryrun_consumption": payload.get("live_dryrun_consumption"),
        "feedback_attribution": payload.get("feedback_attribution"),
        "single_provider_can_approve": False,
        "core_system_blocked": False,
        "raw_key_exposed": False,
    }


def safe_redis_hset(
    redis_client: Any,
    key: str,
    mapping: Mapping[str, Any],
    *,
    ex: int = DEFAULT_REDIS_STATE_TTL_SECONDS,
) -> bool:
    if redis_client is None or key != KEY_STATE or not allowed_santiment_write_key(key):
        return False
    try:
        encoded = {
            str(k): json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else str(v)
            for k, v in mapping.items()
        }
        redis_client.hset(key, mapping=encoded)
        expire = getattr(redis_client, "expire", None)
        if callable(expire):
            expire(key, int(ex))
        return True
    except Exception:
        return False


class SantimentProClient:
    def __init__(
        self,
        *,
        api_key: str,
        http_post: HttpPost | None = None,
        sleep_func: Callable[[float], Awaitable[None]] = asyncio.sleep,
        time_func: Callable[[], float] = time.monotonic,
        epoch_time_func: Callable[[], float] = time.time,
        timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
        rate_limit_state: RateLimitState | None = None,
        token_bucket: AsyncTokenBucket | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Santiment API key is required")
        self.api_key = api_key
        self.http_post = http_post or _default_http_post
        self.sleep_func = sleep_func
        self.time_func = time_func
        self.epoch_time_func = epoch_time_func
        self.timeout_seconds = float(timeout_seconds)
        self.rate_limit = rate_limit_state or RateLimitState()
        self.token_bucket = token_bucket or AsyncTokenBucket(
            rate_per_minute=PRO_RATE_LIMIT_PER_MINUTE,
            capacity=PRO_RATE_LIMIT_PER_MINUTE,
            time_func=time_func,
            sleep_func=sleep_func,
        )

    async def _call_http(
        self,
        query: str,
    ) -> SantimentHttpResult:
        headers = {
            "Authorization": f"Apikey {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ai-bot-v2-santiment-pro/1.0",
        }
        result = self.http_post(
            SANTIMENT_API_URL,
            headers,
            {"query": query},
            self.timeout_seconds,
        )
        if inspect.isawaitable(result):
            return await result
        return result

    async def _throttle_from_headers(self, headers: Mapping[str, str]) -> None:
        parsed = parse_rate_limit_headers(headers)
        self.rate_limit.remaining_minute = parsed["remaining_minute"]
        self.rate_limit.remaining_hour = parsed["remaining_hour"]
        self.rate_limit.remaining_month = parsed["remaining_month"]
        reset_wait = _reset_wait_seconds(
            parsed["reset"],
            now_epoch=self.epoch_time_func(),
        )
        self.rate_limit.reset_seconds = reset_wait
        checks = (
            (
                parsed["remaining_minute"],
                max(1, int(PRO_RATE_LIMIT_PER_MINUTE * RATE_LIMIT_SAFETY_FRACTION)),
            ),
            (
                parsed["remaining_hour"],
                max(1, int(PRO_RATE_LIMIT_PER_HOUR * RATE_LIMIT_SAFETY_FRACTION)),
            ),
            (
                parsed["remaining_month"],
                max(1, int(PRO_RATE_LIMIT_PER_MONTH * RATE_LIMIT_SAFETY_FRACTION)),
            ),
        )
        if any(remaining is not None and remaining < floor for remaining, floor in checks):
            await self.sleep_func(float(reset_wait + 2))

    async def fetch_batch(
        self,
        *,
        slugs: Sequence[str],
        metrics: Sequence[str],
        interval: str = DEFAULT_INTERVAL,
        from_expr: str = DEFAULT_LOOKBACK,
        to_expr: str = DEFAULT_TO,
        max_attempts: int = 5,
    ) -> SantimentHttpResult:
        clean_metrics = sanitize_metrics(metrics)
        query = build_batch_query(
            slugs=slugs,
            metrics=clean_metrics,
            interval=interval,
            from_expr=from_expr,
            to_expr=to_expr,
        )
        cost = estimated_query_cost(clean_metrics)
        backoff = 2.0
        last_result = SantimentHttpResult(
            status_code=None,
            body=None,
            error=SOURCE_STATUS_NETWORK_ERROR,
            request_attempted=False,
        )
        for _attempt in range(max(1, int(max_attempts))):
            await self.token_bucket.consume(cost)
            self.rate_limit.local_estimated_cost += cost
            self.rate_limit.last_request_monotonic = self.time_func()
            result = await self._call_http(query)
            last_result = result
            await self._throttle_from_headers(result.headers)
            if result.status_code == 429:
                self.rate_limit.last_response_status = SOURCE_STATUS_RATE_LIMITED
                self.rate_limit.last_429_monotonic = self.time_func()
                self.rate_limit.consecutive_failures += 1
                await self.sleep_func(backoff + random.uniform(0.25, 1.25))
                backoff = min(backoff * 2.0, 60.0)
                continue
            if result.status_code is None or result.error:
                self.rate_limit.last_response_status = SOURCE_STATUS_NETWORK_ERROR
                self.rate_limit.consecutive_failures += 1
                await self.sleep_func(backoff + random.uniform(0.25, 1.25))
                backoff = min(backoff * 2.0, 60.0)
                continue
            self.rate_limit.consecutive_failures = 0
            self.rate_limit.last_response_status = SOURCE_STATUS_OK
            return result
        return last_result


async def fetch_normalize_publish_once(
    *,
    client: SantimentProClient,
    redis_client: Any,
    symbols: Sequence[str],
    metrics: Sequence[str] = DEFAULT_METRICS,
    interval: str = DEFAULT_INTERVAL,
    from_expr: str = DEFAULT_LOOKBACK,
    to_expr: str = DEFAULT_TO,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    now = generated_utc or utc_iso()
    symbol_to_slug = normalize_symbols_to_slugs(symbols)
    slug_to_symbol = {slug: symbol for symbol, slug in symbol_to_slug.items()}
    clean_metrics = sanitize_metrics(metrics)
    redis_write_results: dict[str, bool] = {}
    if not slug_to_symbol or not clean_metrics:
        status = build_status_payload(
            go_no_go="V2_SANTIMENT_PRO_INGESTOR_BLOCKED",
            generated_utc=now,
            symbol_count=0,
            successful_symbol_count=0,
            source_status_counts={SOURCE_STATUS_PARSE_ERROR: 1},
            key_present=True,
            network_call_attempted=False,
            rate_limit_state=client.rate_limit,
            redis_write_results=redis_write_results,
            blocked_reason="NO_SAFE_SYMBOLS_OR_METRICS",
        )
        redis_write_results[KEY_STATUS] = safe_redis_set(
            redis_client,
            KEY_STATUS,
            status,
            ex=DEFAULT_REDIS_STATUS_TTL_SECONDS,
        )
        status["redis_write_results"] = redis_write_results
        return {"status_payload": status, "symbol_payloads": {}}
    result = await client.fetch_batch(
        slugs=tuple(slug_to_symbol),
        metrics=clean_metrics,
        interval=interval,
        from_expr=from_expr,
        to_expr=to_expr,
    )
    body = result.body if isinstance(result.body, Mapping) else {}
    source_status = SOURCE_STATUS_OK
    if result.status_code == 429:
        source_status = SOURCE_STATUS_RATE_LIMITED
    elif result.error or result.status_code is None:
        source_status = SOURCE_STATUS_NETWORK_ERROR
    elif isinstance(body, Mapping) and body.get("errors"):
        source_status = SOURCE_STATUS_GRAPHQL_ERROR
    symbol_payloads = (
        normalize_batch_payload(
            body,
            slug_to_symbol=slug_to_symbol,
            metrics=clean_metrics,
            generated_utc=now,
        )
        if source_status == SOURCE_STATUS_OK
        else {}
    )
    for payload in symbol_payloads.values():
        payload["rate_limit_state"] = client.rate_limit.as_payload()
    state_mapping: dict[str, Any] = {
        "generated_utc": now,
        "source_status": source_status,
        "symbol_count": len(symbol_to_slug),
        "successful_symbol_count": len(symbol_payloads),
        "rate_limit_state": client.rate_limit.as_payload(),
    }
    for symbol, payload in symbol_payloads.items():
        redis_key = KEY_PER_SYMBOL_TEMPLATE.format(symbol=symbol)
        redis_write_results[redis_key] = safe_redis_set(redis_client, redis_key, payload)
        feature_payload = build_santiment_feature_payload(payload, timeframe="1h")
        feature_key = KEY_FEATURE_TEMPLATE.format(symbol=symbol, timeframe="1h")
        redis_write_results[feature_key] = safe_redis_set(
            redis_client,
            feature_key,
            feature_payload,
        )
        redis_write_results[KEY_FEATURE_BRIDGE_STATUS] = safe_redis_set(
            redis_client,
            KEY_FEATURE_BRIDGE_STATUS,
            _santiment_feature_bridge_status(feature_payload),
            ex=DEFAULT_REDIS_STATUS_TTL_SECONDS,
        )
        for key, value in payload.items():
            if key.startswith("santiment_") and _coerce_float(value) is not None:
                state_mapping[f"{symbol.lower()}_{key}"] = value
    redis_write_results[KEY_STATE] = safe_redis_hset(
        redis_client,
        KEY_STATE,
        state_mapping,
    )
    status = build_status_payload(
        go_no_go="V2_SANTIMENT_PRO_INGESTOR_READY",
        generated_utc=now,
        symbol_count=len(symbol_to_slug),
        successful_symbol_count=len(symbol_payloads),
        source_status_counts={source_status: max(1, len(symbol_to_slug))},
        key_present=True,
        network_call_attempted=True,
        rate_limit_state=client.rate_limit,
        redis_write_results=redis_write_results,
    )
    redis_write_results[KEY_STATUS] = safe_redis_set(
        redis_client,
        KEY_STATUS,
        status,
        ex=DEFAULT_REDIS_STATUS_TTL_SECONDS,
    )
    status["redis_write_results"] = redis_write_results
    return {"status_payload": status, "symbol_payloads": symbol_payloads}


def build_status_payload(
    *,
    go_no_go: str,
    generated_utc: str,
    symbol_count: int,
    successful_symbol_count: int,
    source_status_counts: Mapping[str, int],
    key_present: bool,
    network_call_attempted: bool,
    rate_limit_state: RateLimitState,
    redis_write_results: Mapping[str, bool],
    blocked_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "v2_santiment_pro_ingestor_status_v1",
        "generated_utc": generated_utc,
        "go_no_go": go_no_go,
        "provider": "santiment",
        "provider_plan": "pro",
        "blocked_reason": blocked_reason,
        "key_present": bool(key_present),
        "credential_env_var_names_documented_only": list(SANTIMENT_API_KEY_NAMES),
        "credential_value": "NEVER",
        "raw_values_exposed": False,
        "provider_network_calls_attempted": bool(network_call_attempted),
        "symbol_count": int(symbol_count),
        "successful_symbol_count": int(successful_symbol_count),
        "source_status_counts": dict(source_status_counts),
        "rate_limit_contract": {
            "requests_per_minute": PRO_RATE_LIMIT_PER_MINUTE,
            "requests_per_hour": PRO_RATE_LIMIT_PER_HOUR,
            "requests_per_month": PRO_RATE_LIMIT_PER_MONTH,
            "local_cost_model": "one_token_per_getMetric_query",
            "header_names_respected": [
                "x-ratelimit-remaining-minute",
                "x-ratelimit-remaining-hour",
                "x-ratelimit-remaining-month",
                "x-ratelimit-reset",
            ],
            "safety_buffer_fraction": RATE_LIMIT_SAFETY_FRACTION,
        },
        "rate_limit_state": rate_limit_state.as_payload(),
        "allowed_redis_write_keys": [KEY_STATUS, KEY_STATE, KEY_FEATURE_BRIDGE_STATUS],
        "allowed_redis_write_prefixes": [KEY_PER_SYMBOL_PREFIX, KEY_FEATURE_PREFIX],
        "redis_write_results": dict(redis_write_results),
        "auto_updates_symbol_selection_via_symbol_score": True,
        "auto_updates_trainer_via_feature_pipeline": True,
        "paper_shadow_only": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "may_not_override_strict_paper_fill_gate": True,
        "may_not_authorize_live_or_canary": True,
        "may_not_place_orders": True,
        "places_real_order": False,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "writes_old_redis": False,
        "exchange_mutation": False,
    }


def build_key_missing_status(
    *,
    generated_utc: str | None = None,
    symbol_count: int = 0,
    redis_write_results: Mapping[str, bool] | None = None,
) -> dict[str, Any]:
    return build_status_payload(
        go_no_go="V2_SANTIMENT_PRO_INGESTOR_READY",
        generated_utc=generated_utc or utc_iso(),
        symbol_count=symbol_count,
        successful_symbol_count=0,
        source_status_counts={SOURCE_STATUS_KEY_MISSING: int(symbol_count)},
        key_present=False,
        network_call_attempted=False,
        rate_limit_state=RateLimitState(
            remaining_minute=PRO_RATE_LIMIT_PER_MINUTE,
            remaining_hour=PRO_RATE_LIMIT_PER_HOUR,
            remaining_month=PRO_RATE_LIMIT_PER_MONTH,
            last_response_status=SOURCE_STATUS_KEY_MISSING,
        ),
        redis_write_results=dict(redis_write_results or {}),
    )
