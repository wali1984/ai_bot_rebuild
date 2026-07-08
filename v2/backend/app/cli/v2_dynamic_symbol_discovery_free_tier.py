"""Free-tier dynamic symbol discovery for the V2 paper/shadow runtime.

This worker expands the non-execution universe from public/free data sources
and writes V2-prefixed Redis keys plus operator-runtime status files. It never
writes old Redis namespaces and never places, cancels, or modifies orders.

Inputs:
- CoinGecko demo/free API: trending + coins/markets.
- Binance USDM public exchangeInfo: tradability confirmation only.
- Surf market price API: tiny sampled probe to preserve free-tier credits.
- CoinGlass v4 supported-coins probe: status-first; no per-symbol calls.

Outputs:
- v2:symbol_universe:dynamic_discovery_status
- v2:symbol_universe:dynamic_discovered_symbols
- v2:altdata:coingecko:*
- v2:altdata:surf:*
- v2:altdata:coinglass:*

The published status includes ``discovered_symbols``, ``training_symbols``, and
``paper_symbols`` so ``symbol_universe_public_payload`` can auto-propagate the
expanded universe to ingestors, feature generation, scoring, and trainer paths.
Execution stays empty: ``live_symbols=[]`` and ``execution_live_symbols=[]``.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from v2.backend.app.services.v2_symbol_runtime_universe import BASELINE_25_SYMBOLS

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
BINANCE_FAPI_BASE = "https://fapi.binance.com"
SURF_BASE = "https://api.asksurf.ai/gateway/v1"
COINGLASS_BASE = "https://open-api-v4.coinglass.com"

DEFAULT_INTERVAL_SECONDS = 21_600
DEFAULT_MAX_SYMBOLS = 80
DEFAULT_COINGECKO_MARKET_ROWS = 100
DEFAULT_SURF_SYMBOL_LIMIT = 3
HTTP_TIMEOUT_SECONDS = 12.0
V2_REDIS_PREFIX = "v2:"

WORKLOG_DIR = Path(
    "claude_worklog/final_readiness/v2_dynamic_symbol_discovery_free_tier_20260604/latest"
)
WORKLOG_STATUS = WORKLOG_DIR / "dynamic_symbol_discovery_status.json"
WORKLOG_REPORT = WORKLOG_DIR / "V2_DYNAMIC_SYMBOL_DISCOVERY_FREE_TIER_REPORT.md"
PUBLIC_OPERATOR_RUNTIME = Path(
    "v2/frontend/public/operator_runtime/v2_dynamic_symbol_discovery/latest/dynamic_symbol_discovery_status.json"
)
PUBLIC_DASHBOARD = Path(
    "v2/frontend/public/v2_dynamic_symbol_discovery/latest/operator_dashboard_payload.json"
)
# Disk-based cache for Binance tradable symbols — used as fallback when Binance
# returns 418 or any temporary error. Written on every successful exchangeInfo
# fetch (24h+ of safety buffer). On 418, CoinGecko discovery continues with the
# cached tradable set instead of producing 0 symbols.
BINANCE_TRADABLE_CACHE = Path(
    "v2/frontend/public/operator_runtime/v2_dynamic_symbol_discovery/latest/binance_usdm_tradable_cache.json"
)

KEY_DISCOVERY_STATUS = "v2:symbol_universe:dynamic_discovery_status"
KEY_DISCOVERED_SYMBOLS = "v2:symbol_universe:dynamic_discovered_symbols"
KEY_COINGECKO_STATUS = "v2:altdata:coingecko:status"
KEY_COINGECKO_SYMBOL_PREFIX = "v2:altdata:coingecko:symbol:"
KEY_SURF_STATUS = "v2:altdata:surf:status"
KEY_SURF_SYMBOL_PREFIX = "v2:altdata:surf:symbol:"
KEY_COINGLASS_STATUS = "v2:altdata:coinglass:status"
KEY_COINGLASS_SYMBOL_PREFIX = "v2:altdata:coinglass:symbol:"

ALLOWED_REDIS_EXACT_KEYS = (
    KEY_DISCOVERY_STATUS,
    KEY_DISCOVERED_SYMBOLS,
    KEY_COINGECKO_STATUS,
    KEY_SURF_STATUS,
    KEY_COINGLASS_STATUS,
)
ALLOWED_REDIS_PREFIXES = (
    KEY_COINGECKO_SYMBOL_PREFIX,
    KEY_SURF_SYMBOL_PREFIX,
    KEY_COINGLASS_SYMBOL_PREFIX,
)

STABLECOIN_TOKENS = frozenset(
    {
        "BUSD",
        "DAI",
        "FDUSD",
        "FRAX",
        "GUSD",
        "PYUSD",
        "TUSD",
        "USDC",
        "USDD",
        "USDE",
        "USDP",
        "USDS",
        "USDT",
    }
)


@dataclass(frozen=True)
class HttpResult:
    status_code: int | None
    body: Any | None
    error: str | None = None
    request_attempted: bool = True


HttpGet = Callable[[str, Mapping[str, str], float], HttpResult]


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis():
    try:
        import redis  # type: ignore

        client = redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
        client.ping()
        return client
    except Exception:
        return None


def _safe_redis_set(redis_client: Any, key: str, payload: Any, *, ex: int = 21_600) -> bool:
    if redis_client is None:
        return False
    if not isinstance(key, str) or not key.startswith(V2_REDIS_PREFIX):
        return False
    if key not in ALLOWED_REDIS_EXACT_KEYS and not any(
        key.startswith(prefix) for prefix in ALLOWED_REDIS_PREFIXES
    ):
        return False
    try:
        redis_client.set(key, json.dumps(payload, sort_keys=True), ex=ex)
        return True
    except Exception:
        return False


def _http_get_json(
    url: str,
    headers: Mapping[str, str] | None = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> HttpResult:
    safe_headers = {"User-Agent": "ai-bot-v2-dynamic-symbol-discovery/1.0"}
    safe_headers.update(dict(headers or {}))
    req = urllib.request.Request(url, headers=safe_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return HttpResult(status_code=int(resp.status), body=json.loads(raw))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body: Any = json.loads(raw)
        except ValueError:
            body = {"body": raw[:200]}
        return HttpResult(status_code=int(exc.code), body=body, error=f"HTTP_{exc.code}")
    except Exception as exc:  # noqa: BLE001 - status payload should capture failures
        return HttpResult(status_code=None, body=None, error=type(exc).__name__)


def _source_status(result: HttpResult, *, provider: str) -> str:
    if not result.request_attempted:
        return "KEY_MISSING_NO_NETWORK"
    if result.status_code is None:
        return f"NETWORK_ERROR_{result.error or 'UNKNOWN'}"
    body = result.body
    if provider == "coinglass" and isinstance(body, Mapping):
        code = str(body.get("code") or "")
        msg = str(body.get("msg") or body.get("message") or "").upper()
        if code == "401" and "UPGRADE" in msg:
            return "API_PLAN_BLOCKED_401_UPGRADE_PLAN"
        if code and code not in ("0", "200", "OK", "SUCCESS"):
            return f"API_CODE_{code}"
    if 200 <= result.status_code < 300:
        return "API_OK"
    if result.status_code == 402:
        return "API_PAYMENT_REQUIRED_402"
    if result.status_code == 401:
        return "API_UNAUTHORIZED_401"
    if result.status_code == 403:
        return "API_FORBIDDEN_403"
    if result.status_code == 429:
        return "API_RATE_LIMITED_429"
    return f"HTTP_{result.status_code}"


def _headers_with_optional_key(provider: str, key: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    if not key:
        return headers
    if provider == "coingecko":
        headers["x-cg-demo-api-key"] = key
    elif provider == "surf":
        headers["Authorization"] = "Bearer " + key
    elif provider == "coinglass":
        headers["CG-API-KEY"] = key
    return headers


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _clamp01(value: float) -> float:
    return _clamp(value, 0.0, 1.0)


def _token_from_symbol(value: Any) -> str:
    token = str(value or "").strip().upper()
    token = token.replace("-", "").replace("_", "")
    if token.endswith("USDT"):
        token = token[:-4]
    return "".join(ch for ch in token if ch.isalnum())


def _symbol_variants_for_token(token: str) -> tuple[str, ...]:
    token = _token_from_symbol(token)
    if not token or token in STABLECOIN_TOKENS:
        return ()
    return (f"{token}USDT", f"1000{token}USDT")


def _map_token_to_usdm_symbol(token: str, tradable: set[str]) -> str | None:
    for variant in _symbol_variants_for_token(token):
        if variant in tradable:
            return variant
    return None


def _fetch_binance_usdm_symbols(http_get: HttpGet) -> tuple[set[str], dict[str, Any]]:
    result = http_get(
        f"{BINANCE_FAPI_BASE}/fapi/v1/exchangeInfo",
        {},
        HTTP_TIMEOUT_SECONDS,
    )
    status = _source_status(result, provider="binance")
    symbols: set[str] = set()
    if status == "API_OK" and isinstance(result.body, Mapping):
        for row in result.body.get("symbols") or []:
            if not isinstance(row, Mapping):
                continue
            symbol = str(row.get("symbol") or "").upper()
            if (
                symbol.endswith("USDT")
                and str(row.get("quoteAsset") or "").upper() == "USDT"
                and str(row.get("contractType") or "").upper() == "PERPETUAL"
                and str(row.get("status") or "").upper() == "TRADING"
            ):
                symbols.add(symbol)
    return symbols, {
        "provider": "binance_usdm_public_exchange_info",
        "source_status": status,
        "http_status": result.status_code,
        "symbol_count": len(symbols),
        "network_call_attempted": result.request_attempted,
    }


def _load_binance_tradable_cache() -> set[str]:
    """Return last-known-good Binance USDM tradable symbols from disk cache.

    Falls back to BASELINE_25_SYMBOLS when the cache file does not exist or is
    unreadable.  Called only when a live Binance exchangeInfo call fails (418,
    network error, etc.) so CoinGecko discovery can still map tokens to symbols
    instead of producing 0 results.
    """
    try:
        data = json.loads(BINANCE_TRADABLE_CACHE.read_text(encoding="utf-8"))
        symbols = {str(s).strip().upper() for s in (data.get("symbols") or [])
                   if str(s).strip().upper().endswith("USDT")}
        if symbols:
            return symbols
    except Exception:
        pass
    return set(BASELINE_25_SYMBOLS)


def _save_binance_tradable_cache(symbols: set[str]) -> None:
    """Persist a fresh Binance tradable set to disk for future fallback use."""
    try:
        _write_json(BINANCE_TRADABLE_CACHE, {
            "generated_utc": utc_iso(),
            "symbols": sorted(symbols),
            "symbol_count": len(symbols),
        })
    except Exception:
        pass


def _parse_coingecko_trending(body: Any) -> dict[str, float]:
    scores: dict[str, float] = {}
    if not isinstance(body, Mapping):
        return scores
    rows = body.get("coins") or []
    for index, row in enumerate(rows):
        item = row.get("item") if isinstance(row, Mapping) else row
        if not isinstance(item, Mapping):
            continue
        token = _token_from_symbol(item.get("symbol"))
        if token:
            scores[token] = max(scores.get(token, 0.0), _clamp01(1.0 - index / 20.0))
    return scores


def _coingecko_market_rows(body: Any) -> list[Mapping[str, Any]]:
    return [row for row in body if isinstance(row, Mapping)] if isinstance(body, list) else []


def _normalise_market_score(value: float | None, max_value: float) -> float | None:
    if value is None or value <= 0 or max_value <= 0:
        return None
    return _clamp01(math.log10(value + 1.0) / math.log10(max_value + 1.0))


def _momentum_score(row: Mapping[str, Any]) -> float:
    p1 = _to_float(row.get("price_change_percentage_1h_in_currency"))
    p24 = _to_float(row.get("price_change_percentage_24h_in_currency"))
    p7 = _to_float(row.get("price_change_percentage_7d_in_currency"))
    values = [v for v in (p1, p24, p7) if v is not None]
    if not values:
        return 0.5
    avg = sum(_clamp(v, -50.0, 50.0) for v in values) / len(values)
    return _clamp01((avg + 50.0) / 100.0)


def _build_coingecko_symbol_payloads(
    *,
    markets_result: HttpResult,
    trending_result: HttpResult,
    tradable_symbols: set[str],
    generated_utc: str,
    key_present: bool,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    market_status = _source_status(markets_result, provider="coingecko")
    trending_status = _source_status(trending_result, provider="coingecko")
    market_rows = _coingecko_market_rows(markets_result.body)
    trending_scores = _parse_coingecko_trending(trending_result.body)
    max_volume = max((_to_float(row.get("total_volume")) or 0.0 for row in market_rows), default=0.0)
    max_market_cap = max((_to_float(row.get("market_cap")) or 0.0 for row in market_rows), default=0.0)
    payloads: dict[str, dict[str, Any]] = {}
    external_count = 0
    for index, row in enumerate(market_rows, start=1):
        token = _token_from_symbol(row.get("symbol"))
        if not token or token in STABLECOIN_TOKENS:
            continue
        external_count += 1
        symbol = _map_token_to_usdm_symbol(token, tradable_symbols)
        if not symbol:
            continue
        liquidity_score = _normalise_market_score(_to_float(row.get("total_volume")), max_volume)
        market_cap_score = _normalise_market_score(_to_float(row.get("market_cap")), max_market_cap)
        trend_score = trending_scores.get(token, 0.0)
        momentum_score = _momentum_score(row)
        discovery_score = sum(
            value * weight
            for value, weight in (
                (liquidity_score or 0.0, 0.40),
                (market_cap_score or 0.0, 0.20),
                (trend_score, 0.20),
                (momentum_score, 0.20),
            )
        )
        payloads[symbol] = {
            "schema_version": "v2_altdata_coingecko_symbol_discovery_v1",
            "generated_utc": generated_utc,
            "provider": "coingecko",
            "source_status": market_status,
            "symbol": symbol,
            "token": token,
            "coingecko_id": row.get("id"),
            "name": row.get("name"),
            "rank": index,
            "current_price": _to_float(row.get("current_price")),
            "total_volume": _to_float(row.get("total_volume")),
            "market_cap": _to_float(row.get("market_cap")),
            "market_cap_rank": row.get("market_cap_rank"),
            "price_change_percentage_1h": _to_float(row.get("price_change_percentage_1h_in_currency")),
            "price_change_percentage_24h": _to_float(row.get("price_change_percentage_24h_in_currency")),
            "price_change_percentage_7d": _to_float(row.get("price_change_percentage_7d_in_currency")),
            "coingecko_liquidity_score": round(liquidity_score or 0.0, 6),
            "coingecko_market_cap_score": round(market_cap_score or 0.0, 6),
            "coingecko_trend_score": round(trend_score, 6),
            "coingecko_momentum_score": round(momentum_score, 6),
            "coingecko_discovery_score": round(_clamp01(discovery_score), 6),
            "provider_freshness_seconds": 0,
            "missing_feature_flags": [],
            "stale_feature_flags": [],
            "network_call_attempted": True,
            "key_present": bool(key_present),
            "credential_value": "NEVER",
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "writes_legacy_redis": False,
            "writes_exchange_orders": False,
        }
    status = {
        "schema_version": "v2_altdata_coingecko_status_v1",
        "generated_utc": generated_utc,
        "provider": "coingecko",
        "key_present": bool(key_present),
        "market_source_status": market_status,
        "trending_source_status": trending_status,
        "source_status_counts": {
            market_status: 1,
            trending_status: 1,
        },
        "external_symbol_count": external_count,
        "successful_symbol_count": len(payloads),
        "symbol_count": len(payloads),
        "network_call_attempted": True,
        "raw_credential_value_exposed": False,
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
    }
    return payloads, status


def _extract_numeric_prices(value: Any) -> list[float]:
    prices: list[float] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key).lower()
            if any(token in key_text for token in ("price", "close", "usd")) or key_text in {
                "first",
                "high",
                "last",
                "low",
                "value",
            }:
                num = _to_float(child)
                if num is not None and num > 0:
                    prices.append(num)
            elif isinstance(child, (Mapping, list, tuple)):
                prices.extend(_extract_numeric_prices(child))
    elif isinstance(value, (list, tuple)):
        for child in value:
            prices.extend(_extract_numeric_prices(child))
    return prices


def _surf_score(body: Any) -> tuple[float | None, int]:
    prices = _extract_numeric_prices(body)
    if not prices:
        return None, 0
    if len(prices) == 1 or prices[0] <= 0:
        return 0.5, len(prices)
    momentum = (prices[-1] - prices[0]) / prices[0]
    return _clamp01((_clamp(momentum, -0.5, 0.5) + 0.5)), len(prices)


def _build_surf_payloads(
    *,
    selected_symbols: Iterable[str],
    symbol_to_token: Mapping[str, str],
    api_key: str | None,
    http_get: HttpGet,
    generated_utc: str,
    symbol_limit: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    if not api_key:
        return {}, {
            "schema_version": "v2_altdata_surf_status_v1",
            "generated_utc": generated_utc,
            "provider": "surf",
            "key_present": False,
            "source_status_counts": {"KEY_MISSING_NO_NETWORK": 1},
            "successful_symbol_count": 0,
            "symbol_count": 0,
            "network_call_attempted": False,
            "raw_credential_value_exposed": False,
            "writes_legacy_redis": False,
            "writes_exchange_orders": False,
        }
    payloads: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    selected_list = list(selected_symbols)
    preferred = [symbol for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT") if symbol in selected_list]
    probe_symbols: list[str] = []
    seen: set[str] = set()
    for symbol in preferred + selected_list:
        if symbol not in seen:
            probe_symbols.append(symbol)
            seen.add(symbol)
        if len(probe_symbols) >= max(0, int(symbol_limit)):
            break
    for symbol in probe_symbols:
        token = symbol_to_token.get(symbol) or symbol.removesuffix("USDT")
        query = urllib.parse.urlencode({"symbol": token})
        result = http_get(
            f"{SURF_BASE}/market/price?{query}",
            _headers_with_optional_key("surf", api_key),
            HTTP_TIMEOUT_SECONDS,
        )
        status = _source_status(result, provider="surf")
        counts[status] = counts.get(status, 0) + 1
        score, observation_count = _surf_score(result.body)
        if status != "API_OK":
            continue
        payloads[symbol] = {
            "schema_version": "v2_altdata_surf_symbol_market_signal_v1",
            "generated_utc": generated_utc,
            "provider": "surf",
            "source_status": status,
            "symbol": symbol,
            "token": token,
            "surf_market_price_signal_score": round(score, 6) if score is not None else None,
            "surf_price_observation_count": observation_count,
            "provider_freshness_seconds": 0,
            "missing_feature_flags": [] if score is not None else ["surf_price_signal_missing"],
            "stale_feature_flags": [],
            "network_call_attempted": True,
            "key_present": True,
            "credential_value": "NEVER",
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "writes_legacy_redis": False,
            "writes_exchange_orders": False,
        }
    return payloads, {
        "schema_version": "v2_altdata_surf_status_v1",
        "generated_utc": generated_utc,
        "provider": "surf",
        "key_present": True,
        "source_status_counts": counts or {"NO_SYMBOLS_PROBED": 1},
        "successful_symbol_count": len(payloads),
        "symbol_count": len(payloads),
        "network_call_attempted": bool(symbol_limit),
        "raw_credential_value_exposed": False,
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "free_tier_budget_guard": {
            "default_cycle_interval_seconds": DEFAULT_INTERVAL_SECONDS,
            "default_symbol_limit_per_cycle": DEFAULT_SURF_SYMBOL_LIMIT,
            "estimated_daily_calls_default": int(
                (86_400 / DEFAULT_INTERVAL_SECONDS) * DEFAULT_SURF_SYMBOL_LIMIT
            ),
        },
    }


def _extract_coinglass_symbols(body: Any, tradable_symbols: set[str]) -> dict[str, dict[str, Any]]:
    rows: list[Any] = []
    if isinstance(body, Mapping):
        data = body.get("data")
        rows = data if isinstance(data, list) else []
    elif isinstance(body, list):
        rows = body
    payloads: dict[str, dict[str, Any]] = {}
    for row in rows:
        token: str = ""
        if isinstance(row, str):
            token = _token_from_symbol(row)
        elif isinstance(row, Mapping):
            token = _token_from_symbol(row.get("symbol") or row.get("coin") or row.get("baseAsset"))
        symbol = _map_token_to_usdm_symbol(token, tradable_symbols)
        if symbol:
            payloads[symbol] = {
                "schema_version": "v2_altdata_coinglass_symbol_derivatives_probe_v1",
                "provider": "coinglass",
                "symbol": symbol,
                "token": token,
                "coinglass_derivatives_score": 0.5,
                "source_status": "API_OK",
                "provider_freshness_seconds": 0,
                "missing_feature_flags": [],
                "stale_feature_flags": [],
                "network_call_attempted": True,
                "credential_value": "NEVER",
                "live_gate": "blocked_human_only",
                "live_symbols": [],
                "writes_legacy_redis": False,
                "writes_exchange_orders": False,
            }
    return payloads


def _build_coinglass_payloads(
    *,
    api_key: str | None,
    http_get: HttpGet,
    tradable_symbols: set[str],
    generated_utc: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    if not api_key:
        return {}, {
            "schema_version": "v2_altdata_coinglass_status_v1",
            "generated_utc": generated_utc,
            "provider": "coinglass",
            "key_present": False,
            "source_status_counts": {"KEY_MISSING_NO_NETWORK": 1},
            "successful_symbol_count": 0,
            "symbol_count": 0,
            "network_call_attempted": False,
            "raw_credential_value_exposed": False,
            "writes_legacy_redis": False,
            "writes_exchange_orders": False,
        }
    result = http_get(
        f"{COINGLASS_BASE}/api/futures/supported-coins",
        _headers_with_optional_key("coinglass", api_key),
        HTTP_TIMEOUT_SECONDS,
    )
    status = _source_status(result, provider="coinglass")
    symbol_payloads = _extract_coinglass_symbols(result.body, tradable_symbols) if status == "API_OK" else {}
    for payload in symbol_payloads.values():
        payload["generated_utc"] = generated_utc
    return symbol_payloads, {
        "schema_version": "v2_altdata_coinglass_status_v1",
        "generated_utc": generated_utc,
        "provider": "coinglass",
        "key_present": True,
        "source_status_counts": {status: 1},
        "successful_symbol_count": len(symbol_payloads),
        "symbol_count": len(symbol_payloads),
        "network_call_attempted": True,
        "http_status": result.status_code,
        "raw_credential_value_exposed": False,
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
    }


def _fetch_coingecko(
    *,
    api_key: str | None,
    http_get: HttpGet,
    per_page: int,
) -> tuple[HttpResult, HttpResult]:
    headers = _headers_with_optional_key("coingecko", api_key)
    market_query = urllib.parse.urlencode(
        {
            "vs_currency": "usd",
            "order": "volume_desc",
            "per_page": max(1, min(250, int(per_page))),
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "1h,24h,7d",
        }
    )
    markets = http_get(
        f"{COINGECKO_BASE}/coins/markets?{market_query}",
        headers,
        HTTP_TIMEOUT_SECONDS,
    )
    trending = http_get(
        f"{COINGECKO_BASE}/search/trending",
        headers,
        HTTP_TIMEOUT_SECONDS,
    )
    return markets, trending


def _sorted_symbols_by_score(payloads: Mapping[str, Mapping[str, Any]], max_symbols: int) -> list[str]:
    rows = sorted(
        payloads.items(),
        key=lambda item: (
            -float(item[1].get("coingecko_discovery_score") or 0.0),
            -float(item[1].get("total_volume") or 0.0),
            item[0],
        ),
    )
    baseline = [symbol for symbol in BASELINE_25_SYMBOLS if symbol in payloads]
    out: list[str] = []
    seen: set[str] = set()
    for symbol in baseline + [symbol for symbol, _payload in rows]:
        if symbol not in seen:
            out.append(symbol)
            seen.add(symbol)
        if len(out) >= max_symbols:
            break
    return out


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_report(payload: Mapping[str, Any]) -> None:
    lines = [
        "# V2 Dynamic Symbol Discovery Free-Tier Report",
        "",
        f"Generated: `{payload['generated_utc']}`",
        "",
        f"GO/NO-GO: `{payload['go_no_go']}`",
        "",
        "## Result",
        "",
        (
            "CoinGecko, Surf, CoinGlass, and Binance public futures metadata "
            "were used only for V2 paper/shadow symbol discovery. Execution remains blocked."
        ),
        "",
        f"- Discovered/training symbols: `{payload['dynamic_symbol_count']}`",
        f"- External CoinGecko symbols observed: `{payload['external_discovered_symbol_count']}`",
        f"- Surf symbols probed this cycle: `{payload['surf_status'].get('symbol_count', 0)}`",
        f"- CoinGlass status: `{next(iter(payload['coinglass_status'].get('source_status_counts', {'unknown': 1}).keys()))}`",
        "",
        "## Safety",
        "",
        "- `LIVE_GATE`: `blocked_human_only`",
        "- `live_symbols`: `[]`",
        "- `execution_live_symbols`: `[]`",
        "- `writes_legacy_redis`: `false`",
        "- `writes_exchange_orders`: `false`",
        "- `raw_credential_value_exposed`: `false`",
        "",
        "## Top Symbols",
        "",
        ", ".join(payload.get("dynamic_discovered_symbols", [])[:30]),
        "",
    ]
    WORKLOG_REPORT.parent.mkdir(parents=True, exist_ok=True)
    WORKLOG_REPORT.write_text("\n".join(lines), encoding="utf-8")


def run_once(
    *,
    redis_client_override: Any | None = None,
    write_redis: bool = True,
    http_get: HttpGet = _http_get_json,
    max_symbols: int = DEFAULT_MAX_SYMBOLS,
    coingecko_market_rows: int = DEFAULT_COINGECKO_MARKET_ROWS,
    surf_symbol_limit: int = DEFAULT_SURF_SYMBOL_LIMIT,
    public_paths: tuple[Path, ...] = (PUBLIC_OPERATOR_RUNTIME, PUBLIC_DASHBOARD),
) -> dict[str, Any]:
    generated_utc = utc_iso()
    redis_client = redis_client_override if redis_client_override is not None else _connect_redis()
    coingecko_key = os.environ.get("COINGECKO_API_KEY") or None
    coinglass_key = os.environ.get("COINGLASS_API_KEY") or None
    surf_key = os.environ.get("ASKSURF_API_KEY") or os.environ.get("SURF_API_KEY") or None

    tradable_symbols, binance_status = _fetch_binance_usdm_symbols(http_get)
    if tradable_symbols:
        # Cache the fresh Binance list so future 418 bans can fall back to it.
        _save_binance_tradable_cache(tradable_symbols)
        binance_status["fallback_used"] = False
    else:
        # Binance returned 418 / network error — load last-known-good list.
        tradable_symbols = _load_binance_tradable_cache()
        binance_status["fallback_used"] = True
        binance_status["fallback_symbol_count"] = len(tradable_symbols)
    markets_result, trending_result = _fetch_coingecko(
        api_key=coingecko_key,
        http_get=http_get,
        per_page=coingecko_market_rows,
    )
    coingecko_payloads, coingecko_status = _build_coingecko_symbol_payloads(
        markets_result=markets_result,
        trending_result=trending_result,
        tradable_symbols=tradable_symbols,
        generated_utc=generated_utc,
        key_present=bool(coingecko_key),
    )
    selected_symbols = _sorted_symbols_by_score(coingecko_payloads, int(max_symbols))
    symbol_to_token = {
        symbol: str(payload.get("token") or symbol.removesuffix("USDT"))
        for symbol, payload in coingecko_payloads.items()
    }
    surf_payloads, surf_status = _build_surf_payloads(
        selected_symbols=selected_symbols,
        symbol_to_token=symbol_to_token,
        api_key=surf_key,
        http_get=http_get,
        generated_utc=generated_utc,
        symbol_limit=surf_symbol_limit,
    )
    coinglass_payloads, coinglass_status = _build_coinglass_payloads(
        api_key=coinglass_key,
        http_get=http_get,
        tradable_symbols=tradable_symbols,
        generated_utc=generated_utc,
    )
    selected_symbols = sorted(
        set(selected_symbols) | set(symbol for symbol in coinglass_payloads if symbol in tradable_symbols),
        key=lambda symbol: selected_symbols.index(symbol) if symbol in selected_symbols else 10_000,
    )[: int(max_symbols)]
    confirmed_runtime_symbols = sorted(
        set(selected_symbols)
        | {symbol for symbol in BASELINE_25_SYMBOLS if symbol in tradable_symbols}
    )

    redis_write_results: dict[str, bool] = {}
    if write_redis and redis_client is not None:
        redis_write_results[KEY_COINGECKO_STATUS] = _safe_redis_set(
            redis_client, KEY_COINGECKO_STATUS, coingecko_status
        )
        for symbol, payload in coingecko_payloads.items():
            if symbol in selected_symbols:
                redis_write_results[f"{KEY_COINGECKO_SYMBOL_PREFIX}{symbol}"] = _safe_redis_set(
                    redis_client, f"{KEY_COINGECKO_SYMBOL_PREFIX}{symbol}", payload
                )
        redis_write_results[KEY_SURF_STATUS] = _safe_redis_set(
            redis_client, KEY_SURF_STATUS, surf_status
        )
        for symbol, payload in surf_payloads.items():
            redis_write_results[f"{KEY_SURF_SYMBOL_PREFIX}{symbol}"] = _safe_redis_set(
                redis_client, f"{KEY_SURF_SYMBOL_PREFIX}{symbol}", payload
            )
        redis_write_results[KEY_COINGLASS_STATUS] = _safe_redis_set(
            redis_client, KEY_COINGLASS_STATUS, coinglass_status
        )
        for symbol, payload in coinglass_payloads.items():
            redis_write_results[f"{KEY_COINGLASS_SYMBOL_PREFIX}{symbol}"] = _safe_redis_set(
                redis_client, f"{KEY_COINGLASS_SYMBOL_PREFIX}{symbol}", payload
            )

    payload = {
        "schema_version": "v2_dynamic_symbol_discovery_free_tier_status_v1",
        "generated_utc": generated_utc,
        "go_no_go": "V2_DYNAMIC_SYMBOL_DISCOVERY_FREE_TIER_LIVE_OK",
        "provider_ids": ["coingecko", "surf", "coinglass", "binance_usdm_public_exchange_info"],
        "binance_usdm_status": binance_status,
        "coingecko_status": coingecko_status,
        "surf_status": surf_status,
        "coinglass_status": coinglass_status,
        "external_discovered_symbols": sorted(coingecko_payloads),
        "external_discovered_symbol_count": len(coingecko_payloads),
        "discovered_symbols": selected_symbols,
        "dynamic_discovered_symbols": selected_symbols,
        "observed_symbols": selected_symbols,
        "training_symbols": selected_symbols,
        "paper_symbols": selected_symbols,
        "live_data_symbols": selected_symbols,
        "trainer_live_symbols": selected_symbols,
        "paper_shadow_live_symbols": selected_symbols,
        "binance_usdm_confirmed_symbols": confirmed_runtime_symbols,
        "tradable_symbols": confirmed_runtime_symbols,
        "binance_usdm_tradable_symbols": sorted(tradable_symbols),
        "binance_usdm_tradable_symbol_count": len(tradable_symbols),
        "dynamic_symbol_count": len(selected_symbols),
        "candidate_symbol_rows": [
            {
                "symbol": symbol,
                "token": symbol_to_token.get(symbol),
                "coingecko_discovery_score": coingecko_payloads.get(symbol, {}).get("coingecko_discovery_score"),
                "surf_market_price_signal_score": surf_payloads.get(symbol, {}).get("surf_market_price_signal_score"),
                "coinglass_derivatives_score": coinglass_payloads.get(symbol, {}).get("coinglass_derivatives_score"),
                "binance_usdm_confirmed": symbol in tradable_symbols,
            }
            for symbol in selected_symbols
        ],
        "auto_update_ingestors": True,
        "auto_update_feature_pipeline": True,
        "auto_update_trainer_symbols": True,
        "free_tier_only": True,
        "paid_tier_enabled": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "execution_live_symbols": [],
        "trade_all_discovered_symbols": False,
        "execution_mutation_enabled": False,
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "writes_legacy_redis": False,
        "writes_old_redis": False,
        "writes_exchange_orders": False,
        "places_exchange_orders": False,
        "raw_credential_value_exposed": False,
        "redis_write_results": redis_write_results,
        "allowed_redis_write_keys": list(ALLOWED_REDIS_EXACT_KEYS),
        "allowed_redis_write_prefixes": list(ALLOWED_REDIS_PREFIXES),
    }
    if write_redis and redis_client is not None:
        redis_write_results[KEY_DISCOVERED_SYMBOLS] = _safe_redis_set(
            redis_client,
            KEY_DISCOVERED_SYMBOLS,
            {"generated_utc": generated_utc, "symbols": selected_symbols},
        )
        redis_write_results[KEY_DISCOVERY_STATUS] = _safe_redis_set(
            redis_client, KEY_DISCOVERY_STATUS, payload
        )
    for path in (WORKLOG_STATUS,) + tuple(public_paths):
        _write_json(path, payload)
    _write_report(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_dynamic_symbol_discovery_free_tier")
    parser.add_argument("--once", action="store_true", default=True)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--max-symbols", type=int, default=DEFAULT_MAX_SYMBOLS)
    parser.add_argument("--coingecko-market-rows", type=int, default=DEFAULT_COINGECKO_MARKET_ROWS)
    parser.add_argument("--surf-symbol-limit", type=int, default=DEFAULT_SURF_SYMBOL_LIMIT)
    parser.add_argument("--no-redis", action="store_true")
    args = parser.parse_args(argv)
    while True:
        payload = run_once(
            write_redis=not args.no_redis,
            max_symbols=args.max_symbols,
            coingecko_market_rows=args.coingecko_market_rows,
            surf_symbol_limit=args.surf_symbol_limit,
        )
        print(
            json.dumps(
                {
                    "go_no_go": payload["go_no_go"],
                    "dynamic_symbol_count": payload["dynamic_symbol_count"],
                    "live_gate": payload["live_gate"],
                    "live_symbols": payload["live_symbols"],
                    "writes_legacy_redis": payload["writes_legacy_redis"],
                    "writes_exchange_orders": payload["writes_exchange_orders"],
                },
                sort_keys=True,
            )
        )
        if not args.loop:
            return 0
        try:
            time.sleep(max(300, int(args.interval_seconds)))
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(main())
