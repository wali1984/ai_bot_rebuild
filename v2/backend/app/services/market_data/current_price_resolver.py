"""Central current-price resolver.

Single authority for "what is the execution-relevant current price of a
symbol". Priority order (highest first):

1. direct live orderbook best bid/ask (binance, then kucoin)
2. mark price where available
3. index price where available
4. latest Binance/KuCoin WSS trade or closed/current 1m kline
5. CoinGlass market snapshot — confirmation-grade fallback only
6. REST fallback only when timestamped fresh enough and marked fallback

Read-only against market keys; publishes v2:market:current_price:{symbol}
and v2:market:current_price_status. Never blocks core trading by itself:
a missing price yields can_size_trade=false with an exact reason.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

CURRENT_PRICE_KEY = "v2:market:current_price:{symbol}"
CURRENT_PRICE_STATUS_KEY = "v2:market:current_price_status"
CURRENT_PRICE_TTL_SECONDS = 120

# Execution-grade staleness bound; older sources become fallback-grade and
# beyond the fallback bound the price is refused entirely.
EXECUTION_MAX_STALENESS_SECONDS = 120.0
FALLBACK_MAX_STALENESS_SECONDS = 900.0

MISSING_REASONS = (
    "SYMBOL_NOT_LISTED",
    "SYMBOL_DISABLED",
    "NO_EXCHANGE_MARKET",
    "FEED_STALE",
    "ORDERBOOK_UNAVAILABLE",
    "KLINE_UNAVAILABLE",
    "EXCLUDED_FROM_LIVE_UNIVERSE",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_ts(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        stamp = float(value)
        if stamp > 1e12:
            stamp /= 1000.0
        try:
            return datetime.fromtimestamp(stamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _read_json(client: Any, key: str) -> Any:
    try:
        raw = client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        return None


def _staleness(now: datetime, stamp: datetime | None) -> float | None:
    if stamp is None:
        return None
    return max(0.0, (now - stamp).total_seconds())


def _timestamp(payload: Mapping[str, Any], *extra_fields: str) -> datetime | None:
    for field in (
        *extra_fields,
        "event_time",
        "event_time_ms",
        "ev_time_ms",
        "transaction_time",
        "transaction_time_ms",
        "available_at",
        "received_at",
        "generated_at",
        "fetched_utc",
        "binance_time_ms",
        "closeTime",
        "ts",
        "time",
    ):
        stamp = _parse_ts(payload.get(field))
        if stamp is not None:
            return stamp
    return None


def _book_top(payload: Mapping[str, Any]) -> tuple[float | None, float | None]:
    bid = _float(_first_present(payload.get("best_bid"), payload.get("bid"), payload.get("bid_price")))
    ask = _float(_first_present(payload.get("best_ask"), payload.get("ask"), payload.get("ask_price")))
    if bid is not None and ask is not None:
        return bid, ask
    bids = payload.get("bids")
    asks = payload.get("asks")
    if isinstance(bids, list) and bids:
        first_bid = bids[0]
        if isinstance(first_bid, (list, tuple)) and first_bid:
            bid = _float(first_bid[0])
        elif isinstance(first_bid, Mapping):
            bid = _float(_first_present(first_bid.get("price"), first_bid.get("bid"), first_bid.get("best_bid")))
    if isinstance(asks, list) and asks:
        first_ask = asks[0]
        if isinstance(first_ask, (list, tuple)) and first_ask:
            ask = _float(first_ask[0])
        elif isinstance(first_ask, Mapping):
            ask = _float(_first_present(first_ask.get("price"), first_ask.get("ask"), first_ask.get("best_ask")))
    return bid, ask


def _price_payload(
    *,
    symbol: str,
    price: float,
    bid: float | None,
    ask: float | None,
    stamp: datetime | None,
    now: datetime,
    source: str,
    source_priority: int,
    fallback_used: bool,
) -> dict[str, Any] | None:
    staleness = _staleness(now, stamp)
    if stamp is None or staleness is None or staleness > FALLBACK_MAX_STALENESS_SECONDS:
        return None
    if not fallback_used and staleness > EXECUTION_MAX_STALENESS_SECONDS:
        return None
    mid = (bid + ask) / 2.0 if bid is not None and ask is not None else price
    return {
        "price": price,
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread_usd": (ask - bid) if bid is not None and ask is not None else None,
        "source": source,
        "source_priority": source_priority,
        "available_at": _iso(stamp),
        "staleness_seconds": staleness,
        "fallback_used": fallback_used,
    }


def _from_orderbook(client: Any, symbol: str, now: datetime) -> dict[str, Any] | None:
    for venue, key, default_fallback in (
        ("binance", f"v2:orderbook:top:binance:{symbol}", False),
        ("binance", f"v2:market:orderbook_top:{symbol}", False),
        ("kucoin", f"v2:orderbook:top:kucoin:{symbol}", False),
    ):
        payload = _read_json(client, key)
        if not isinstance(payload, Mapping):
            continue
        bid, ask = _book_top(payload)
        if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
            continue
        source_text = str(payload.get("source") or payload.get("transport") or "")
        fallback_used = default_fallback or "rest" in source_text.lower()
        resolved = _price_payload(
            symbol=symbol,
            price=(bid + ask) / 2.0,
            bid=bid,
            ask=ask,
            stamp=_timestamp(payload),
            now=now,
            source=f"orderbook_top_{venue}",
            source_priority=1,
            fallback_used=fallback_used,
        )
        if resolved:
            return resolved
    return None


def _from_mark_index(client: Any, symbol: str, now: datetime) -> dict[str, Any] | None:
    payload = _read_json(client, f"v2:market:prices:{symbol}")
    mark_payload = _read_json(client, f"v2:market:mark_price:{symbol}")
    funding_payload = _read_json(client, f"v2:market:funding:{symbol}")
    payloads = [p for p in (payload, mark_payload, funding_payload) if isinstance(p, Mapping)]
    if not payloads:
        return None
    merged: dict[str, Any] = {}
    for item in payloads:
        merged.update(dict(item))
    payload = merged
    if not isinstance(payload, Mapping):
        return None
    funding = payload.get("funding") if isinstance(payload.get("funding"), Mapping) else {}
    for field, label, priority in (
        ("mark_price", "mark_price", 2),
        ("markPrice", "mark_price", 2),
        ("index_price", "index_price", 3),
        ("indexPrice", "index_price", 3),
    ):
        price = _float(_first_present(payload.get(field), funding.get(field)))
        if price is None or price <= 0:
            continue
        source_text = str(payload.get("source") or payload.get("transport") or funding.get("source") or funding.get("transport") or "")
        resolved = _price_payload(
            symbol=symbol,
            price=price,
            bid=None,
            ask=None,
            stamp=_timestamp(payload) or _timestamp(funding),
            now=now,
            source=label,
            source_priority=priority,
            fallback_used="rest" in source_text.lower(),
        )
        if resolved:
            return resolved
    return None


def _from_trade_or_kline(client: Any, symbol: str, now: datetime) -> dict[str, Any] | None:
    for key, source in (
        (f"v2:market:latest_trade:binance:{symbol}", "latest_trade_binance"),
        (f"v2:market:latest_trade:kucoin:{symbol}", "latest_trade_kucoin"),
        (f"v2:market:agg_trades:{symbol}", "agg_trade_binance"),
        (f"v2:market:kline_current:binance:{symbol}:1m", "current_kline_1m_binance"),
        (f"v2:market:kucoin:latest:{symbol}", "latest_trade_kucoin"),
    ):
        payload = _read_json(client, key)
        if isinstance(payload, list) and payload:
            payload = payload[-1]
        if not isinstance(payload, Mapping):
            continue
        price = _float(
            _first_present(
                payload.get("price"),
                payload.get("last_price"),
                payload.get("lastPrice"),
                payload.get("close"),
                payload.get("close_price"),
            )
        )
        if price is None or price <= 0:
            continue
        resolved = _price_payload(
            symbol=symbol,
            price=price,
            bid=None,
            ask=None,
            stamp=_timestamp(payload, "trade_time", "close_time", "closeTime"),
            now=now,
            source=source,
            source_priority=4,
            fallback_used=False,
        )
        if resolved:
            return resolved
    for venue in ("binance", "kucoin"):
        payload = _read_json(client, f"v2:market:ohlcv_closed:{venue}:{symbol}:1m")
        if not isinstance(payload, list) or not payload:
            continue
        last = payload[-1]
        if not isinstance(last, Mapping):
            continue
        price = _float(last.get("close") or last.get("close_price"))
        if price is None or price <= 0:
            continue
        stamp = _timestamp(last, "close_time", "closeTime")
        staleness = _staleness(now, stamp)
        if staleness is not None and staleness > FALLBACK_MAX_STALENESS_SECONDS:
            continue
        execution_grade = staleness is not None and staleness <= EXECUTION_MAX_STALENESS_SECONDS
        return {
            "price": price,
            "bid": None,
            "ask": None,
            "mid": price,
            "spread_usd": None,
            "source": f"closed_kline_1m_{venue}",
            "source_priority": 4,
            "available_at": _iso(stamp) if stamp else None,
            "staleness_seconds": staleness,
            "fallback_used": not execution_grade,
        }
    return None


def _from_coinglass_snapshot(client: Any, symbol: str, now: datetime) -> dict[str, Any] | None:
    payload = _read_json(client, f"v2:coinglass:market_snapshot:{symbol}")
    if not isinstance(payload, Mapping):
        return None
    features = payload.get("features") if isinstance(payload.get("features"), Mapping) else {}
    price = _float(features.get("coinglass_price_usd"))
    if price is None or price <= 0:
        return None
    return _price_payload(
        symbol=symbol,
        price=price,
        bid=None,
        ask=None,
        stamp=_timestamp(payload),
        now=now,
        source="coinglass_market_snapshot_confirmation_only",
        source_priority=5,
        fallback_used=True,
    )


def _from_rest_orderbook(client: Any, symbol: str, now: datetime) -> dict[str, Any] | None:
    for venue, key in (
        ("binance", f"v2:market:orderbook:binance:{symbol}"),
        ("merged", f"v2:market:orderbook:{symbol}"),
    ):
        payload = _read_json(client, key)
        if not isinstance(payload, Mapping):
            continue
        bid, ask = _book_top(payload)
        if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
            continue
        resolved = _price_payload(
            symbol=symbol,
            price=(bid + ask) / 2.0,
            bid=bid,
            ask=ask,
            stamp=_timestamp(payload),
            now=now,
            source=f"rest_orderbook_{venue}_fallback",
            source_priority=6,
            fallback_used=True,
        )
        if resolved:
            return resolved
    return None


def _from_rest_ticker(client: Any, symbol: str, now: datetime) -> dict[str, Any] | None:
    payload = _read_json(client, f"v2:market:prices:{symbol}")
    if not isinstance(payload, Mapping):
        return None
    ticker = payload.get("ticker_24hr") if isinstance(payload.get("ticker_24hr"), Mapping) else {}
    price = _float(payload.get("price") or payload.get("lastPrice") or ticker.get("lastPrice"))
    if price is None or price <= 0:
        return None
    bid = _float(ticker.get("bidPrice"))
    ask = _float(ticker.get("askPrice"))
    return _price_payload(
        symbol=symbol,
        price=price,
        bid=bid,
        ask=ask,
        stamp=_timestamp(ticker, "closeTime") or _timestamp(payload),
        now=now,
        source="rest_ticker_24hr_fallback",
        source_priority=6,
        fallback_used=True,
    )


def resolve_current_price(client: Any, symbol: str) -> dict[str, Any]:
    """Resolve one symbol's current price with exact provenance."""
    symbol = str(symbol or "").upper()
    now = _utc_now()
    resolvers = (
        _from_orderbook,
        _from_mark_index,
        _from_trade_or_kline,
        _from_coinglass_snapshot,
        _from_rest_orderbook,
        _from_rest_ticker,
    )
    resolved: dict[str, Any] | None = None
    for resolver in resolvers:
        try:
            resolved = resolver(client, symbol, now)
        except Exception:
            resolved = None
        if resolved:
            break
    payload: dict[str, Any] = {
        "schema_version": "v2_current_price_v1",
        "symbol": symbol,
        "generated_utc": _iso(now),
        "raw_key_exposed": False,
    }
    if resolved:
        staleness = resolved.get("staleness_seconds")
        execution_grade = not resolved.get("fallback_used") and staleness is not None and staleness <= EXECUTION_MAX_STALENESS_SECONDS
        payload.update(resolved)
        payload.update(
            {
                "decision_time_safe": True,
                "can_size_trade": bool(execution_grade),
                "execution_grade": execution_grade,
                "reason_if_missing": None,
            }
        )
        return payload
    # No source produced a usable price — classify the absence exactly.
    has_any_market_key = any(
        _read_json(client, key) is not None
        for key in (
            f"v2:market:prices:{symbol}",
            f"v2:market:mark_price:{symbol}",
            f"v2:market:funding:{symbol}",
            f"v2:market:ohlcv_closed:binance:{symbol}:1m",
            f"v2:market:ohlcv_closed:kucoin:{symbol}:1m",
            f"v2:orderbook:top:binance:{symbol}",
            f"v2:market:orderbook_top:{symbol}",
        )
    )
    reason = "FEED_STALE" if has_any_market_key else "NO_EXCHANGE_MARKET"
    payload.update(
        {
            "price": None,
            "bid": None,
            "ask": None,
            "mid": None,
            "spread_usd": None,
            "source": None,
            "source_priority": None,
            "available_at": None,
            "staleness_seconds": None,
            "fallback_used": False,
            "decision_time_safe": True,
            "can_size_trade": False,
            "execution_grade": False,
            "reason_if_missing": reason,
        }
    )
    return payload


def publish_current_prices(client: Any, symbols: list[str]) -> dict[str, Any]:
    resolved_count = 0
    missing: dict[str, str] = {}
    for symbol in symbols:
        payload = resolve_current_price(client, symbol)
        client.set(
            CURRENT_PRICE_KEY.format(symbol=payload["symbol"]),
            json.dumps(payload, sort_keys=True, default=str),
            ex=CURRENT_PRICE_TTL_SECONDS,
        )
        if payload.get("price") is not None:
            resolved_count += 1
        else:
            missing[payload["symbol"]] = str(payload.get("reason_if_missing"))
    status = {
        "schema_version": "v2_current_price_status_v1",
        "generated_utc": _iso(_utc_now()),
        "symbol_count": len(symbols),
        "resolved_count": resolved_count,
        "missing_count": len(missing),
        "missing_reasons": missing,
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }
    client.set(CURRENT_PRICE_STATUS_KEY, json.dumps(status, sort_keys=True, default=str), ex=600)
    return status
