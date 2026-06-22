"""Free-tier public intelligence worker for V2 symbol selection.

This worker adds non-duplicative context signals to the existing V2
paper/shadow pipeline. It does not fetch candles, order books, or prices that
the V2 market ingestors already publish. It writes only V2-prefixed Redis keys
for:

- DeFi protocol liquidity context from DeFiLlama.
- Crypto news attention/sentiment from public RSS feeds.
- Global sentiment from Alternative.me Fear & Greed.
- Bitcoin mempool/fee pressure from mempool.space.

The payloads are consumed by ``v2_alt_data_symbol_universe_scoring`` for
training/candidate ranking. Execution remains blocked.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

DEFILLAMA_PROTOCOLS_URL = "https://api.llama.fi/protocols"
ALTERNATIVE_FNG_URL = "https://api.alternative.me/fng/?limit=1"
MEMPOOL_URL = "https://mempool.space/api/mempool"
MEMPOOL_FEES_URL = "https://mempool.space/api/v1/fees/recommended"
NEWS_FEEDS = (
    ("coindesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("cointelegraph", "https://cointelegraph.com/rss"),
    ("decrypt", "https://decrypt.co/feed"),
)
CRYPTOCOMPARE_NEWS_URL = "https://min-api.cryptocompare.com/data/v2/news/"
CRYPTOPANIC_POSTS_URL = "https://cryptopanic.com/api/free/v1/posts/"
CRYPTOCOMPARE_API_KEY_ENV = "CRYPTOCOMPARE_API_KEY"
CRYPTOPANIC_AUTH_TOKEN_ENV = "CRYPTOPANIC_AUTH_TOKEN"

DEFAULT_INTERVAL_SECONDS = 3_600
DEFAULT_MAX_NEWS_ITEMS_PER_FEED = 40
HTTP_TIMEOUT_SECONDS = 12.0
V2_REDIS_PREFIX = "v2:"

WORKLOG_DIR = Path(
    "claude_worklog/final_readiness/v2_crypto_vision_public_intel_free_tier_20260604/latest"
)
WORKLOG_STATUS = WORKLOG_DIR / "v2_public_intel_free_tier_status.json"
WORKLOG_REPORT = WORKLOG_DIR / "V2_CRYPTO_VISION_PUBLIC_INTEL_FREE_TIER_REPORT.md"
PUBLIC_OPERATOR_RUNTIME = Path(
    "v2/frontend/public/operator_runtime/v2_public_intel_free_tier/latest/v2_public_intel_free_tier_status.json"
)
PUBLIC_DASHBOARD = Path(
    "v2/frontend/public/v2_public_intel_free_tier/latest/operator_dashboard_payload.json"
)

KEY_STATUS = "v2:altdata:public_intel:status"
KEY_GLOBAL = "v2:altdata:public_intel:global"
KEY_SYMBOL_PREFIX = "v2:altdata:public_intel:symbol:"

ALLOWED_REDIS_EXACT_KEYS = (KEY_STATUS, KEY_GLOBAL)
ALLOWED_REDIS_PREFIXES = (KEY_SYMBOL_PREFIX,)

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

TOKEN_ALIASES: dict[str, tuple[str, ...]] = {
    "AAVE": ("aave",),
    "ARB": ("arbitrum", "arb"),
    "AVAX": ("avalanche", "avax"),
    "BNB": ("bnb", "binance coin", "bnb chain"),
    "BONK": ("bonk",),
    "BTC": ("btc", "bitcoin"),
    "DOGE": ("doge", "dogecoin"),
    "ENA": ("ethena", "ena"),
    "ETH": ("eth", "ether", "ethereum"),
    "FLOKI": ("floki",),
    "LINK": ("link", "chainlink"),
    "LTC": ("ltc", "litecoin"),
    "NEAR": ("near", "near protocol"),
    "OP": ("optimism", "op"),
    "PEPE": ("pepe",),
    "PENGU": ("pengu", "pudgy penguins"),
    "SHIB": ("shib", "shiba", "shiba inu"),
    "SOL": ("sol", "solana"),
    "SUI": ("sui",),
    "UNI": ("uni", "uniswap"),
    "WIF": ("wif", "dogwifhat"),
    "XRP": ("xrp", "ripple"),
}

POSITIVE_TERMS = frozenset(
    {
        "accumulate",
        "adoption",
        "approval",
        "breakout",
        "bull",
        "bullish",
        "buy",
        "gain",
        "growth",
        "inflow",
        "launch",
        "record",
        "rally",
        "surge",
        "upgrade",
    }
)
NEGATIVE_TERMS = frozenset(
    {
        "ban",
        "bear",
        "bearish",
        "crash",
        "exploit",
        "hack",
        "lawsuit",
        "liquidation",
        "outflow",
        "probe",
        "selloff",
        "slump",
        "suit",
        "vulnerability",
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


def _safe_redis_set(redis_client: Any, key: str, payload: Any, *, ex: int = 3_600) -> bool:
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


def _http_get(
    url: str,
    headers: Mapping[str, str] | None = None,
    timeout: float = HTTP_TIMEOUT_SECONDS,
) -> HttpResult:
    safe_headers = {"User-Agent": "ai-bot-v2-public-intel-free-tier/1.0"}
    safe_headers.update(dict(headers or {}))
    req = urllib.request.Request(url, headers=safe_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            text = raw.strip()
            if text.startswith("{") or text.startswith("["):
                return HttpResult(status_code=int(resp.status), body=json.loads(text))
            return HttpResult(status_code=int(resp.status), body=raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body: Any = json.loads(raw)
        except ValueError:
            body = {"body": raw[:200]}
        return HttpResult(status_code=int(exc.code), body=body, error=f"HTTP_{exc.code}")
    except Exception as exc:  # noqa: BLE001 - status payload captures the failure
        return HttpResult(status_code=None, body=None, error=type(exc).__name__)


def _source_status(result: HttpResult) -> str:
    if not result.request_attempted:
        return "KEY_MISSING_NO_NETWORK"
    if result.status_code is None:
        return f"NETWORK_ERROR_{result.error or 'UNKNOWN'}"
    if 200 <= result.status_code < 300:
        return "API_OK"
    if result.status_code == 401:
        return "API_UNAUTHORIZED_401"
    if result.status_code == 402:
        return "API_PAYMENT_REQUIRED_402"
    if result.status_code == 403:
        return "API_FORBIDDEN_403"
    if result.status_code == 429:
        return "API_RATE_LIMITED_429"
    return f"HTTP_{result.status_code}"


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


def _weighted(values: Iterable[tuple[float | None, float]]) -> float | None:
    numerator = 0.0
    denominator = 0.0
    for value, weight in values:
        if value is None:
            continue
        numerator += float(value) * float(weight)
        denominator += float(weight)
    if denominator <= 0:
        return None
    return _clamp01(numerator / denominator)


def _token_from_symbol(value: Any) -> str:
    token = str(value or "").strip().upper()
    token = token.replace("-", "").replace("_", "").replace("/", "")
    if token.endswith("USDT"):
        token = token[:-4]
    if token.startswith("1000") and len(token) > 4:
        token = token[4:]
    return "".join(ch for ch in token if ch.isalnum())


def _token_aliases(symbol: str) -> tuple[str, ...]:
    token = _token_from_symbol(symbol)
    if not token:
        return ()
    aliases = {token.lower()}
    aliases.update(TOKEN_ALIASES.get(token, ()))
    return tuple(sorted(aliases))


def _token_to_symbol_map(symbols: Iterable[str]) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for symbol in symbols:
        token = _token_from_symbol(symbol)
        if token and token not in STABLECOIN_TOKENS:
            mapped[token] = symbol.upper()
    return mapped


def _normalise_log(value: float | None, max_value: float) -> float | None:
    if value is None or value <= 0 or max_value <= 0:
        return None
    return _clamp01(math.log10(value + 1.0) / math.log10(max_value + 1.0))


def _strip_html(value: str) -> str:
    return re.sub(r"<[^>]+>", " ", html.unescape(value or ""))


def _text_words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9\-']*", value.lower()))


def _parse_rss_items(body: Any, *, source: str, limit: int) -> list[dict[str, str]]:
    if not isinstance(body, str) or not body.strip():
        return []
    try:
        root = ET.fromstring(body.encode("utf-8"))
    except ET.ParseError:
        return []
    rows: list[dict[str, str]] = []
    for item in root.findall(".//item")[: max(0, int(limit))]:
        def child_text(name: str) -> str:
            child = item.find(name)
            return child.text if child is not None and child.text else ""

        title = _strip_html(child_text("title")).strip()
        description = _strip_html(child_text("description")).strip()
        link = child_text("link").strip()
        published = child_text("pubDate").strip()
        if title:
            rows.append(
                {
                    "source": source,
                    "title": title[:240],
                    "description": description[:400],
                    "link": link[:300],
                    "published": published[:120],
                }
            )
    return rows


def _epoch_seconds_to_iso(value: Any) -> str:
    ts = _to_float(value)
    if ts is None or ts <= 0:
        return ""
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (OSError, OverflowError, ValueError):
        return ""


def _parse_cryptocompare_news_items(body: Any, *, limit: int) -> list[dict[str, str]]:
    if not isinstance(body, Mapping):
        return []
    rows = body.get("Data") or []
    if not isinstance(rows, list):
        return []
    out: list[dict[str, str]] = []
    for row in rows[: max(0, int(limit))]:
        if not isinstance(row, Mapping):
            continue
        title = _strip_html(str(row.get("title") or "")).strip()
        description = _strip_html(
            " ".join(
                str(part or "")
                for part in (
                    row.get("body"),
                    row.get("categories"),
                    row.get("tags"),
                )
            )
        ).strip()
        if not title:
            continue
        source_name = str(row.get("source") or "cryptocompare")[:80]
        out.append(
            {
                "source": f"cryptocompare:{source_name}",
                "title": title[:240],
                "description": description[:400],
                "link": str(row.get("url") or "")[:300],
                "published": _epoch_seconds_to_iso(row.get("published_on"))[:120],
            }
        )
    return out


def _parse_cryptopanic_news_items(body: Any, *, limit: int) -> list[dict[str, str]]:
    if not isinstance(body, Mapping):
        return []
    rows = body.get("results") or []
    if not isinstance(rows, list):
        return []
    out: list[dict[str, str]] = []
    for row in rows[: max(0, int(limit))]:
        if not isinstance(row, Mapping):
            continue
        title = _strip_html(str(row.get("title") or "")).strip()
        if not title:
            continue
        currencies = row.get("currencies") or []
        currency_text = ""
        if isinstance(currencies, list):
            currency_text = " ".join(
                str((cur or {}).get("code") or (cur or {}).get("title") or "")
                for cur in currencies
                if isinstance(cur, Mapping)
            )
        votes = row.get("votes") if isinstance(row.get("votes"), Mapping) else {}
        positive_votes = _to_float(votes.get("positive") if isinstance(votes, Mapping) else None) or 0.0
        negative_votes = _to_float(votes.get("negative") if isinstance(votes, Mapping) else None) or 0.0
        sentiment_hint = ""
        if positive_votes > negative_votes:
            sentiment_hint = " bullish"
        elif negative_votes > positive_votes:
            sentiment_hint = " bearish"
        source_payload = row.get("source") if isinstance(row.get("source"), Mapping) else {}
        source_name = str(source_payload.get("title") if isinstance(source_payload, Mapping) else "cryptopanic")
        out.append(
            {
                "source": f"cryptopanic:{source_name[:80] or 'feed'}",
                "title": title[:240],
                "description": f"{currency_text}{sentiment_hint}".strip()[:400],
                "link": str(row.get("url") or "")[:300],
                "published": str(row.get("published_at") or "")[:120],
            }
        )
    return out


def _json_news_status(source: str, result: HttpResult) -> str:
    status = _source_status(result)
    if status != "API_OK":
        return status
    if source == "cryptocompare_news":
        if not isinstance(result.body, Mapping):
            return "UNEXPECTED_PAYLOAD"
        if str(result.body.get("Response") or "").lower() == "error":
            return "API_AUTH_REQUIRED_OR_KEY_INVALID"
        return "API_OK"
    if source == "cryptopanic_news":
        if not isinstance(result.body, Mapping):
            return "UNEXPECTED_PAYLOAD"
        if not isinstance(result.body.get("results"), list):
            return "API_AUTH_REQUIRED_OR_KEY_INVALID"
        return "API_OK"
    return status


def _news_sentiment(text: str) -> float:
    words = _text_words(text)
    positive = len(words & POSITIVE_TERMS)
    negative = len(words & NEGATIVE_TERMS)
    if positive == 0 and negative == 0:
        return 0.0
    return _clamp((positive - negative) / max(1, positive + negative), -1.0, 1.0)


def _build_defillama_payloads(
    *,
    result: HttpResult,
    symbols: tuple[str, ...],
    generated_utc: str,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    status = _source_status(result)
    token_map = _token_to_symbol_map(symbols)
    aggregates: dict[str, dict[str, Any]] = {}
    if status == "API_OK" and isinstance(result.body, list):
        for row in result.body:
            if not isinstance(row, Mapping):
                continue
            token = _token_from_symbol(row.get("symbol"))
            if not token or token in STABLECOIN_TOKENS:
                continue
            symbol = token_map.get(token)
            if not symbol:
                continue
            tvl = _to_float(row.get("tvl")) or 0.0
            change_1d = _to_float(row.get("change_1d"))
            change_7d = _to_float(row.get("change_7d"))
            bucket = aggregates.setdefault(
                symbol,
                {
                    "token": token,
                    "total_tvl_usd": 0.0,
                    "protocols": [],
                    "change_1d_values": [],
                    "change_7d_values": [],
                },
            )
            bucket["total_tvl_usd"] = float(bucket["total_tvl_usd"]) + max(0.0, tvl)
            if change_1d is not None:
                bucket["change_1d_values"].append(change_1d)
            if change_7d is not None:
                bucket["change_7d_values"].append(change_7d)
            protocols = bucket["protocols"]
            if isinstance(protocols, list) and len(protocols) < 5:
                protocols.append(
                    {
                        "name": str(row.get("name") or "")[:80],
                        "slug": str(row.get("slug") or "")[:80],
                        "category": str(row.get("category") or "")[:60],
                        "chain": str(row.get("chain") or "")[:60],
                        "tvl_usd": tvl,
                    }
                )
    max_tvl = max((float(row.get("total_tvl_usd") or 0.0) for row in aggregates.values()), default=0.0)
    payloads: dict[str, dict[str, Any]] = {}
    for symbol, row in aggregates.items():
        one_day_values = [float(v) for v in row.get("change_1d_values", [])]
        seven_day_values = [float(v) for v in row.get("change_7d_values", [])]
        one_day = sum(one_day_values) / len(one_day_values) if one_day_values else None
        seven_day = sum(seven_day_values) / len(seven_day_values) if seven_day_values else None
        liquidity_score = _normalise_log(_to_float(row.get("total_tvl_usd")), max_tvl)
        momentum_values = [v for v in (one_day, seven_day) if v is not None]
        momentum = (
            _clamp01((sum(_clamp(v, -50.0, 50.0) for v in momentum_values) / len(momentum_values) + 50.0) / 100.0)
            if momentum_values
            else None
        )
        payloads[symbol] = {
            "symbol": symbol,
            "token": row.get("token"),
            "defillama_total_tvl_usd": round(float(row.get("total_tvl_usd") or 0.0), 3),
            "defillama_protocol_count": len(row.get("protocols") or []),
            "defillama_top_protocols": row.get("protocols") or [],
            "defillama_change_1d_avg": round(one_day, 6) if one_day is not None else None,
            "defillama_change_7d_avg": round(seven_day, 6) if seven_day is not None else None,
            "defillama_liquidity_score": round(liquidity_score or 0.0, 6),
            "defillama_tvl_momentum_score": round(momentum if momentum is not None else 0.5, 6),
        }
    status_payload = {
        "schema_version": "v2_altdata_defillama_status_v1",
        "generated_utc": generated_utc,
        "provider": "defillama",
        "source_status": status,
        "http_status": result.status_code,
        "symbol_count": len(payloads),
        "successful_symbol_count": len(payloads),
        "network_call_attempted": result.request_attempted,
    }
    return payloads, status_payload


def _build_news_payloads(
    *,
    feed_results: Mapping[str, HttpResult],
    json_news_results: Mapping[str, HttpResult] | None = None,
    symbols: tuple[str, ...],
    generated_utc: str,
    max_items_per_feed: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    items: list[dict[str, str]] = []
    source_status_counts: dict[str, int] = {}
    source_status_by_provider: dict[str, str] = {}
    for source, result in feed_results.items():
        status = _source_status(result)
        source_status_counts[status] = source_status_counts.get(status, 0) + 1
        source_status_by_provider[source] = status
        if status == "API_OK":
            items.extend(_parse_rss_items(result.body, source=source, limit=max_items_per_feed))
    for source, result in (json_news_results or {}).items():
        status = _json_news_status(source, result)
        source_status_counts[status] = source_status_counts.get(status, 0) + 1
        source_status_by_provider[source] = status
        if status != "API_OK":
            continue
        if source == "cryptocompare_news":
            items.extend(_parse_cryptocompare_news_items(result.body, limit=max_items_per_feed))
        elif source == "cryptopanic_news":
            items.extend(_parse_cryptopanic_news_items(result.body, limit=max_items_per_feed))

    per_symbol_matches: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in symbols}
    for item in items:
        searchable = f"{item.get('title', '')} {item.get('description', '')}".lower()
        for symbol in symbols:
            aliases = _token_aliases(symbol)
            if not aliases:
                continue
            if any(re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", searchable) for alias in aliases):
                sentiment = _news_sentiment(searchable)
                per_symbol_matches[symbol].append(
                    {
                        "source": item["source"],
                        "title": item["title"],
                        "link": item["link"],
                        "published": item["published"],
                        "sentiment": round(sentiment, 6),
                    }
                )
    max_count = max((len(rows) for rows in per_symbol_matches.values()), default=0)
    payloads: dict[str, dict[str, Any]] = {}
    for symbol, rows in per_symbol_matches.items():
        if not rows:
            continue
        sentiment_values = [float(row["sentiment"]) for row in rows]
        sentiment = sum(sentiment_values) / len(sentiment_values)
        attention = _normalise_log(float(len(rows)), float(max_count)) or 0.0
        payloads[symbol] = {
            "symbol": symbol,
            "news_article_count": len(rows),
            "news_attention_score": round(attention, 6),
            "news_sentiment_score": round(_clamp(sentiment, -1.0, 1.0), 6),
            "news_sources": sorted({row["source"] for row in rows}),
            "news_sample": rows[:5],
        }
    status_payload = {
        "schema_version": "v2_altdata_public_news_status_v1",
        "generated_utc": generated_utc,
        "provider": "public_rss_news",
        "source_status_counts": source_status_counts,
        "source_status_by_provider": source_status_by_provider,
        "feed_count": len(feed_results),
        "json_feed_count": len(json_news_results or {}),
        "item_count": len(items),
        "symbol_count": len(payloads),
        "successful_symbol_count": len(payloads),
        "network_call_attempted": any(result.request_attempted for result in list(feed_results.values()) + list((json_news_results or {}).values())),
    }
    return payloads, status_payload


def _build_fng_payload(result: HttpResult, generated_utc: str) -> dict[str, Any]:
    status = _source_status(result)
    value: float | None = None
    classification: str | None = None
    next_update: str | None = None
    if status == "API_OK" and isinstance(result.body, Mapping):
        rows = result.body.get("data") or []
        first = rows[0] if isinstance(rows, list) and rows else None
        if isinstance(first, Mapping):
            value = _to_float(first.get("value"))
            classification = str(first.get("value_classification") or "") or None
            next_update = str(first.get("time_until_update") or "") or None
    score = _clamp01(value / 100.0) if value is not None else None
    return {
        "schema_version": "v2_altdata_alternative_me_fng_status_v1",
        "generated_utc": generated_utc,
        "provider": "alternative_me_fear_greed",
        "source_status": status,
        "http_status": result.status_code,
        "fear_greed_value": value,
        "fear_greed_score": round(score, 6) if score is not None else None,
        "fear_greed_classification": classification,
        "time_until_update": next_update,
        "network_call_attempted": result.request_attempted,
    }


def _build_mempool_payload(
    *,
    mempool_result: HttpResult,
    fees_result: HttpResult,
    generated_utc: str,
) -> dict[str, Any]:
    mempool_status = _source_status(mempool_result)
    fees_status = _source_status(fees_result)
    count = None
    vsize = None
    total_fee = None
    if mempool_status == "API_OK" and isinstance(mempool_result.body, Mapping):
        count = _to_float(mempool_result.body.get("count"))
        vsize = _to_float(mempool_result.body.get("vsize"))
        total_fee = _to_float(mempool_result.body.get("total_fee"))
    fastest_fee = None
    hour_fee = None
    economy_fee = None
    if fees_status == "API_OK" and isinstance(fees_result.body, Mapping):
        fastest_fee = _to_float(fees_result.body.get("fastestFee"))
        hour_fee = _to_float(fees_result.body.get("hourFee"))
        economy_fee = _to_float(fees_result.body.get("economyFee"))
    fee_pressure = _clamp01((fastest_fee or 0.0) / 100.0) if fastest_fee is not None else None
    backlog_pressure = _clamp01((vsize or 0.0) / 300_000_000.0) if vsize is not None else None
    pressure = _weighted(((fee_pressure, 0.65), (backlog_pressure, 0.35)))
    return {
        "schema_version": "v2_altdata_mempool_space_status_v1",
        "generated_utc": generated_utc,
        "provider": "mempool_space",
        "source_status": "API_OK" if "API_OK" in {mempool_status, fees_status} else mempool_status,
        "mempool_source_status": mempool_status,
        "fees_source_status": fees_status,
        "mempool_count": count,
        "mempool_vsize": vsize,
        "mempool_total_fee": total_fee,
        "fastest_fee_sat_vb": fastest_fee,
        "hour_fee_sat_vb": hour_fee,
        "economy_fee_sat_vb": economy_fee,
        "btc_mempool_pressure_score": round(pressure, 6) if pressure is not None else None,
        "network_call_attempted": mempool_result.request_attempted or fees_result.request_attempted,
    }


def _combine_symbol_payloads(
    *,
    symbols: tuple[str, ...],
    generated_utc: str,
    defillama_payloads: Mapping[str, Mapping[str, Any]],
    news_payloads: Mapping[str, Mapping[str, Any]],
    fng_payload: Mapping[str, Any],
    mempool_payload: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    fng_score = _to_float(fng_payload.get("fear_greed_score"))
    mempool_pressure = _to_float(mempool_payload.get("btc_mempool_pressure_score"))
    for symbol in symbols:
        token = _token_from_symbol(symbol)
        defi = defillama_payloads.get(symbol, {})
        news = news_payloads.get(symbol, {})
        defillama_liquidity = _to_float(defi.get("defillama_liquidity_score"))
        defillama_momentum = _to_float(defi.get("defillama_tvl_momentum_score"))
        news_attention = _to_float(news.get("news_attention_score"))
        news_sentiment = _to_float(news.get("news_sentiment_score"))
        news_sentiment_component = (
            (news_sentiment + 1.0) / 2.0 if news_sentiment is not None else None
        )
        btc_mempool_health = (
            1.0 - mempool_pressure if token == "BTC" and mempool_pressure is not None else None
        )
        public_score = _weighted(
            (
                (defillama_liquidity, 0.28),
                (defillama_momentum, 0.12),
                (news_attention, 0.22),
                (news_sentiment_component, 0.18),
                (fng_score, 0.08),
                (btc_mempool_health, 0.12),
            )
        )
        missing_flags: list[str] = []
        if symbol not in defillama_payloads:
            missing_flags.append("defillama_protocol_liquidity_missing")
        if symbol not in news_payloads:
            missing_flags.append("public_rss_news_symbol_match_missing")
        if fng_score is None:
            missing_flags.append("alternative_me_fear_greed_missing")
        if token == "BTC" and mempool_pressure is None:
            missing_flags.append("mempool_space_btc_pressure_missing")
        status = "API_OK" if public_score is not None else "MISSING_SYMBOL_SIGNAL"
        payloads[symbol] = {
            "schema_version": "v2_altdata_public_intel_symbol_signal_v1",
            "generated_utc": generated_utc,
            "provider": "public_intel_free_tier",
            "source_status": status,
            "symbol": symbol,
            "token": token,
            "public_intel_score": round(public_score, 6) if public_score is not None else None,
            "defillama_liquidity_score": round(defillama_liquidity, 6) if defillama_liquidity is not None else None,
            "defillama_tvl_momentum_score": round(defillama_momentum, 6) if defillama_momentum is not None else None,
            "defillama_total_tvl_usd": defi.get("defillama_total_tvl_usd"),
            "defillama_protocol_count": defi.get("defillama_protocol_count", 0),
            "defillama_top_protocols": defi.get("defillama_top_protocols", []),
            "news_attention_score": round(news_attention, 6) if news_attention is not None else None,
            "news_sentiment_score": round(news_sentiment, 6) if news_sentiment is not None else None,
            "news_article_count": news.get("news_article_count", 0),
            "news_sources": news.get("news_sources", []),
            "news_sample": news.get("news_sample", []),
            "fear_greed_score": round(fng_score, 6) if fng_score is not None else None,
            "fear_greed_value": fng_payload.get("fear_greed_value"),
            "fear_greed_classification": fng_payload.get("fear_greed_classification"),
            "btc_mempool_pressure_score": (
                round(mempool_pressure, 6) if token == "BTC" and mempool_pressure is not None else None
            ),
            "provider_freshness_seconds": 0,
            "missing_feature_flags": missing_flags,
            "stale_feature_flags": [],
            "network_call_attempted": True,
            "key_present": False,
            "credential_value": "NEVER",
            "raw_credential_value_exposed": False,
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "writes_legacy_redis": False,
            "writes_exchange_orders": False,
        }
    return payloads


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_report(payload: Mapping[str, Any]) -> None:
    lines = [
        "# V2 Crypto-Vision-Inspired Public Intel Free-Tier Report",
        "",
        f"Generated: `{payload['generated_utc']}`",
        "",
        f"GO/NO-GO: `{payload['go_no_go']}`",
        "",
        "## Result",
        "",
        (
            "Reviewed crypto-vision as a broad reference platform and integrated "
            "only non-duplicative free public intelligence lanes into V2: DeFi "
            "TVL/liquidity context, public news attention/sentiment, global "
            "Fear & Greed, and Bitcoin mempool pressure."
        ),
        "",
        f"- Runtime symbols scored: `{payload['symbol_count']}`",
        f"- Symbols with public score: `{payload['successful_symbol_count']}`",
        f"- DeFiLlama symbols: `{payload['defillama_status']['symbol_count']}`",
        f"- News symbols: `{payload['news_status']['symbol_count']}`",
        f"- CryptoCompare news status: `{payload['news_status'].get('source_status_by_provider', {}).get('cryptocompare_news', 'UNKNOWN')}`",
        f"- CryptoPanic news status: `{payload['news_status'].get('source_status_by_provider', {}).get('cryptopanic_news', 'UNKNOWN')}`",
        f"- Fear & Greed status: `{payload['fear_greed_status']['source_status']}`",
        f"- Mempool status: `{payload['mempool_status']['source_status']}`",
        "",
        "## Top Public-Intel Symbols",
        "",
        "| Symbol | Public score | Providers |",
        "| --- | ---: | --- |",
    ]
    for row in payload.get("top_public_intel_symbols", [])[:20]:
        lines.append(
            f"| {row['symbol']} | {row['public_intel_score']} | {','.join(row['providers'])} |"
        )
    lines.extend(
        [
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
        ]
    )
    WORKLOG_REPORT.parent.mkdir(parents=True, exist_ok=True)
    WORKLOG_REPORT.write_text("\n".join(lines), encoding="utf-8")


def run_once(
    *,
    symbols: tuple[str, ...] | None = None,
    redis_client_override: Any | None = None,
    write_redis: bool = True,
    http_get: HttpGet = _http_get,
    max_news_items_per_feed: int = DEFAULT_MAX_NEWS_ITEMS_PER_FEED,
    public_paths: tuple[Path, ...] = (PUBLIC_OPERATOR_RUNTIME, PUBLIC_DASHBOARD),
    smoke_test: bool = False,
) -> dict[str, Any]:
    generated_utc = utc_iso()
    redis_client = redis_client_override if redis_client_override is not None else _connect_redis()
    runtime_symbols = tuple(
        sorted({symbol.strip().upper() for symbol in resolve_symbols(explicit=symbols, smoke_test=smoke_test) if symbol.strip()})
    )

    defillama_result = http_get(DEFILLAMA_PROTOCOLS_URL, {}, HTTP_TIMEOUT_SECONDS)
    fng_result = http_get(ALTERNATIVE_FNG_URL, {}, HTTP_TIMEOUT_SECONDS)
    mempool_result = http_get(MEMPOOL_URL, {}, HTTP_TIMEOUT_SECONDS)
    mempool_fees_result = http_get(MEMPOOL_FEES_URL, {}, HTTP_TIMEOUT_SECONDS)
    news_results = {
        source: http_get(url, {}, HTTP_TIMEOUT_SECONDS)
        for source, url in NEWS_FEEDS
    }
    cryptocompare_api_key = os.environ.get(CRYPTOCOMPARE_API_KEY_ENV, "").strip()
    cryptopanic_auth_token = os.environ.get(CRYPTOPANIC_AUTH_TOKEN_ENV, "").strip()
    cryptocompare_result = (
        http_get(
            CRYPTOCOMPARE_NEWS_URL
            + "?"
            + urllib.parse.urlencode(
                {"lang": "EN", "extraParams": "ai-bot-v2-public-intel"}
            ),
            {"Authorization": f"Apikey {cryptocompare_api_key}"},
            HTTP_TIMEOUT_SECONDS,
        )
        if cryptocompare_api_key
        else HttpResult(
            status_code=None,
            body=None,
            error=f"{CRYPTOCOMPARE_API_KEY_ENV}_MISSING",
            request_attempted=False,
        )
    )
    cryptopanic_result = (
        http_get(
            CRYPTOPANIC_POSTS_URL
            + "?"
            + urllib.parse.urlencode(
                {"auth_token": cryptopanic_auth_token, "public": "true"}
            ),
            {},
            HTTP_TIMEOUT_SECONDS,
        )
        if cryptopanic_auth_token
        else HttpResult(
            status_code=None,
            body=None,
            error=f"{CRYPTOPANIC_AUTH_TOKEN_ENV}_MISSING",
            request_attempted=False,
        )
    )
    json_news_results = {
        "cryptocompare_news": cryptocompare_result,
        "cryptopanic_news": cryptopanic_result,
    }

    defillama_payloads, defillama_status = _build_defillama_payloads(
        result=defillama_result,
        symbols=runtime_symbols,
        generated_utc=generated_utc,
    )
    news_payloads, news_status = _build_news_payloads(
        feed_results=news_results,
        json_news_results=json_news_results,
        symbols=runtime_symbols,
        generated_utc=generated_utc,
        max_items_per_feed=max_news_items_per_feed,
    )
    fng_payload = _build_fng_payload(fng_result, generated_utc)
    mempool_payload = _build_mempool_payload(
        mempool_result=mempool_result,
        fees_result=mempool_fees_result,
        generated_utc=generated_utc,
    )
    symbol_payloads = _combine_symbol_payloads(
        symbols=runtime_symbols,
        generated_utc=generated_utc,
        defillama_payloads=defillama_payloads,
        news_payloads=news_payloads,
        fng_payload=fng_payload,
        mempool_payload=mempool_payload,
    )
    scored_symbols = [
        symbol for symbol, payload in symbol_payloads.items()
        if payload.get("public_intel_score") is not None
    ]
    top_rows = sorted(
        (
            {
                "symbol": symbol,
                "public_intel_score": payload.get("public_intel_score"),
                "defillama_liquidity_score": payload.get("defillama_liquidity_score"),
                "news_attention_score": payload.get("news_attention_score"),
                "news_sentiment_score": payload.get("news_sentiment_score"),
                "providers": [
                    name
                    for name, present in (
                        ("defillama", symbol in defillama_payloads),
                        ("news", symbol in news_payloads),
                        ("fear_greed", payload.get("fear_greed_score") is not None),
                        ("mempool", payload.get("btc_mempool_pressure_score") is not None),
                    )
                    if present
                ],
            }
            for symbol, payload in symbol_payloads.items()
            if payload.get("public_intel_score") is not None
        ),
        key=lambda row: (-(float(row["public_intel_score"] or 0.0)), row["symbol"]),
    )

    redis_write_results: dict[str, bool] = {}
    global_payload = {
        "schema_version": "v2_altdata_public_intel_global_v1",
        "generated_utc": generated_utc,
        "defillama_status": defillama_status,
        "news_status": news_status,
        "fear_greed_status": fng_payload,
        "mempool_status": mempool_payload,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "raw_credential_value_exposed": False,
    }
    if write_redis and redis_client is not None:
        redis_write_results[KEY_GLOBAL] = _safe_redis_set(redis_client, KEY_GLOBAL, global_payload)
        for symbol, payload in symbol_payloads.items():
            redis_write_results[f"{KEY_SYMBOL_PREFIX}{symbol}"] = _safe_redis_set(
                redis_client,
                f"{KEY_SYMBOL_PREFIX}{symbol}",
                payload,
            )

    payload = {
        "schema_version": "v2_public_intel_free_tier_status_v1",
        "generated_utc": generated_utc,
        "go_no_go": "V2_PUBLIC_INTEL_FREE_TIER_LIVE_OK",
        "provider_ids": [
            "crypto_vision_reference",
            "defillama",
            "public_rss_news",
            "cryptocompare_news",
            "cryptopanic_news",
            "alternative_me_fear_greed",
            "mempool_space",
        ],
        "crypto_vision_review": {
            "repository": "https://github.com/nirholas/crypto-vision",
            "integration_mode": "REFERENCE_ARCHITECTURE_ONLY_NO_CODE_COPY",
            "selected_non_duplicative_lanes": [
                "defi_liquidity_context",
                "public_news_attention_sentiment",
                "cryptocompare_json_news_optional_free_key",
                "cryptopanic_json_news_optional_free_token",
                "global_fear_greed",
                "btc_mempool_pressure",
            ],
            "duplicated_market_data_avoided": True,
        },
        "symbols": list(runtime_symbols),
        "symbol_count": len(runtime_symbols),
        "successful_symbol_count": len(scored_symbols),
        "symbols_with_public_intel_score": scored_symbols,
        "top_public_intel_symbols": top_rows[:30],
        "defillama_status": defillama_status,
        "news_status": news_status,
        "json_news_credential_presence": {
            CRYPTOCOMPARE_API_KEY_ENV: bool(cryptocompare_api_key),
            CRYPTOPANIC_AUTH_TOKEN_ENV: bool(cryptopanic_auth_token),
            "raw_credential_value_exposed": False,
        },
        "fear_greed_status": fng_payload,
        "mempool_status": mempool_payload,
        "global_payload": global_payload,
        "auto_updates_symbol_scoring": True,
        "auto_updates_trainer_via_symbol_score": True,
        "auto_updates_trading_candidates_not_execution": True,
        "does_not_duplicate_existing_market_data": True,
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
        redis_write_results[KEY_STATUS] = _safe_redis_set(redis_client, KEY_STATUS, payload)
    for path in (WORKLOG_STATUS,) + tuple(public_paths):
        _write_json(path, payload)
    _write_report(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_public_intel_free_tier")
    parser.add_argument("--once", action="store_true", default=True)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--max-news-items-per-feed", type=int, default=DEFAULT_MAX_NEWS_ITEMS_PER_FEED)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--no-redis", action="store_true")
    args = parser.parse_args(argv)
    symbols = (
        tuple(symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip())
        if args.symbols
        else None
    )
    while True:
        payload = run_once(
            symbols=symbols,
            write_redis=not args.no_redis,
            max_news_items_per_feed=args.max_news_items_per_feed,
            smoke_test=args.smoke_test,
        )
        print(
            json.dumps(
                {
                    "go_no_go": payload["go_no_go"],
                    "symbol_count": payload["symbol_count"],
                    "successful_symbol_count": payload["successful_symbol_count"],
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
