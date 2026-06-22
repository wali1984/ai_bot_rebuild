"""Current trade-terminal and derivatives runtime payload builders.

These builders merge existing V2 public-market Redis keys and V2 public
runtime payloads into browser-facing contracts. They are read-only with
respect to Redis and exchanges: no order, test-order, cancel/modify, leverage,
margin, transfer, or legacy Redis path is touched here.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[5]
PUBLIC_ROOT = REPO_ROOT / "v2/frontend/public"
TRADE_OUT = PUBLIC_ROOT / "operator_runtime/v2_trade_terminal/latest"
DERIVATIVES_OUT = PUBLIC_ROOT / "operator_runtime/v2_derivatives/latest"
EST = timezone(timedelta(hours=-4))
ACCEPTED_SYMBOL_FALLBACK = ("BNBUSDT", "BTCUSDT", "ETHUSDT", "PAXGUSDT", "XAUTUSDT", "ZECUSDT")


def est_now() -> str:
    return datetime.now(EST).isoformat(timespec="seconds")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def json_load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def json_parse(raw: Any) -> Any | None:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="ignore")
    try:
        return json.loads(str(raw))
    except Exception:
        return None


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def connect_redis() -> Any:
    try:
        import redis  # type: ignore

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


def redis_json(client: Any, key: str, default: Any = None) -> Any:
    if client is None:
        return default
    try:
        return json_parse(client.get(key)) or default
    except Exception:
        return default


def redis_keys(client: Any, pattern: str, limit: int = 1000) -> list[str]:
    if client is None:
        return []
    keys: list[str] = []
    try:
        for key in client.scan_iter(match=pattern, count=500):
            keys.append(str(key))
            if len(keys) >= limit:
                break
    except Exception:
        return keys
    return sorted(keys)


def stream_len(client: Any, key: str) -> int | None:
    if client is None:
        return None
    try:
        return int(client.xlen(key))
    except Exception:
        return None


def stream_latest_rows(client: Any, key: str, count: int = 50) -> list[dict[str, Any]]:
    if client is None:
        return []
    try:
        rows = client.xrevrange(key, count=count)
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for row_id, fields in rows:
        payload = dict(fields) if isinstance(fields, Mapping) else {}
        payload["_stream_id"] = str(row_id)
        out.append(payload)
    return out


def dict_or_empty(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def to_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def age_from_ms(ms: Any) -> float | None:
    value = to_float(ms)
    if value is None:
        return None
    if value > 10_000_000_000:
        value = value / 1000.0
    return max(0.0, datetime.now(timezone.utc).timestamp() - value)


def age_from_iso(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=EST)
    return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())


def first_number(*values: Any) -> float | None:
    for value in values:
        parsed = to_float(value)
        if parsed is not None:
            return parsed
    return None


def coinank_data(payload: Any) -> Any:
    if not isinstance(payload, Mapping):
        return None
    data: Any = payload.get("data")
    for _ in range(4):
        if isinstance(data, Mapping) and "data" in data and (
            "success" in data or "code" in data or isinstance(data.get("data"), (Mapping, list))
        ):
            data = data.get("data")
            continue
        break
    return data


def coinank_latest(client: Any, family: str, symbol: str, timeframe: str = "15m") -> dict[str, Any]:
    return dict_or_empty(redis_json(client, f"latest:coinank:{family}:{symbol}:{timeframe}", {}) or {})


def coinank_last_row(payload: Any) -> Any:
    data = coinank_data(payload)
    if isinstance(data, list) and data:
        return data[-1]
    return data


def coinank_last_number(payload: Any, names: tuple[str, ...], indexes: tuple[int, ...] = ()) -> float | None:
    row = coinank_last_row(payload)
    if isinstance(row, Mapping):
        for name in names:
            value = row.get(name)
            parsed = first_number(value[-1] if isinstance(value, list) and value else value)
            if parsed is not None:
                return parsed
    if isinstance(row, (list, tuple)):
        for index in indexes:
            if len(row) > index:
                parsed = first_number(row[index])
                if parsed is not None:
                    return parsed
    data = coinank_data(payload)
    if isinstance(data, Mapping):
        for name in names:
            value = data.get(name)
            parsed = first_number(value[-1] if isinstance(value, list) and value else value)
            if parsed is not None:
                return parsed
    return None


def coinank_oi_change_pct(payload: Any) -> float | None:
    data = coinank_data(payload)
    if not isinstance(data, list) or len(data) < 2:
        return None
    first = data[0]
    last = data[-1]
    if not isinstance(first, Mapping) or not isinstance(last, Mapping):
        return None
    first_oi = first_number(first.get("coinValue"), first.get("close"), first.get("volume"))
    last_oi = first_number(last.get("coinValue"), last.get("close"), last.get("volume"))
    if first_oi in (None, 0.0) or last_oi is None:
        return None
    return ((last_oi - float(first_oi)) / float(first_oi)) * 100.0


def coinank_liquidation_turnover(payload: Any) -> float | None:
    row = coinank_last_row(payload)
    if not isinstance(row, Mapping):
        return None
    long_turn = first_number(row.get("longTurnover"))
    short_turn = first_number(row.get("shortTurnover"))
    if long_turn is None and short_turn is None:
        return None
    return float(long_turn or 0.0) + float(short_turn or 0.0)


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def latest_signed_hold_payload() -> dict[str, Any]:
    signed_path = PUBLIC_ROOT / "v2_signed_read_recovered_balance_hold_and_first_order_resume/latest/operator_dashboard_payload.json"
    balance_path = PUBLIC_ROOT / "v2_live_transport_balance_aware_hold_and_first_order_monitor/latest/operator_dashboard_payload.json"
    signed = json_load(signed_path, {}) or {}
    balance = json_load(balance_path, {}) or {}
    payload = signed if signed else balance
    source_path = signed_path if signed else balance_path
    return {
        **payload,
        "_source_path": rel(source_path),
    }


def accepted_symbols() -> list[str]:
    payload = latest_signed_hold_payload()
    symbols = payload.get("accepted_symbols")
    if isinstance(symbols, list) and symbols:
        return [str(item).upper() for item in symbols if str(item or "").strip()]
    return list(ACCEPTED_SYMBOL_FALLBACK)


def load_chart_payload(symbol: str) -> dict[str, Any]:
    path = PUBLIC_ROOT / f"operator_runtime/v2_market_chart/latest/{symbol}_1m_chart.json"
    data = json_load(path, {}) or {}
    if isinstance(data, dict):
        data["_source_path"] = rel(path)
        return data
    return {"_source_path": rel(path)}


def latest_ohlcv_row(client: Any, symbol: str, timeframe: str = "1m") -> list[Any] | None:
    rows = redis_json(client, f"v2:market:ohlcv:binance:{symbol}:{timeframe}", [])
    if isinstance(rows, list) and rows:
        last = rows[-1]
        if isinstance(last, list):
            return last
    return None


def build_trade_terminal_payload(symbol: str = "BTCUSDT", client: Any = None) -> dict[str, Any]:
    client = client or connect_redis()
    symbol = symbol.strip().upper() or "BTCUSDT"
    generated = est_now()
    chart = load_chart_payload(symbol)
    chart_latest = chart.get("latest") if isinstance(chart.get("latest"), Mapping) else {}
    wsds = redis_json(client, f"v2:market:coinapi:wsds:{symbol}", {}) or {}
    wsds_latest = wsds.get("latest") if isinstance(wsds.get("latest"), Mapping) else wsds
    prices = redis_json(client, f"v2:market:prices:{symbol}", {}) or {}
    ticker_24hr = prices.get("ticker_24hr") if isinstance(prices.get("ticker_24hr"), Mapping) else {}
    funding = redis_json(client, f"v2:market:funding:{symbol}", {}) or {}
    oi = redis_json(client, f"v2:market:open_interest:{symbol}", {}) or {}
    coinank_funding = coinank_latest(client, "funding", symbol)
    coinank_oi = coinank_latest(client, "open_interest", symbol)
    coinank_long_short = coinank_latest(client, "long_short", symbol)
    coinank_liquidations = coinank_latest(client, "liquidations", symbol)
    ohlcv_1m = latest_ohlcv_row(client, symbol, "1m")
    ohlcv_5m = latest_ohlcv_row(client, symbol, "5m")
    levels_keys = redis_keys(client, f"v2:liquidations:levels:{symbol}:*", limit=20)
    levels_rows = [redis_json(client, key, {}) for key in levels_keys]
    levels = next((row for row in levels_rows if isinstance(row, dict) and row), {})
    event_count = stream_len(client, "v2:liquidations:events")
    latest_events = stream_latest_rows(client, "v2:liquidations:events", 100)
    symbol_event_count = sum(1 for row in latest_events if str(row.get("symbol") or "").upper() == symbol)
    hold = latest_signed_hold_payload()

    last_price = first_number(
        wsds_latest.get("mid_px") if isinstance(wsds_latest, Mapping) else None,
        chart_latest.get("mid_px"),
        ticker_24hr.get("lastPrice") if isinstance(ticker_24hr, Mapping) else None,
        prices.get("last_price") if isinstance(prices, Mapping) else None,
    )
    bid = first_number(
        wsds_latest.get("best_bid_px") if isinstance(wsds_latest, Mapping) else None,
        chart_latest.get("best_bid_px"),
    )
    ask = first_number(
        wsds_latest.get("best_ask_px") if isinstance(wsds_latest, Mapping) else None,
        chart_latest.get("best_ask_px"),
    )
    spread_bps = first_number(
        wsds_latest.get("spread") if isinstance(wsds_latest, Mapping) else None,
        chart_latest.get("spread"),
    )
    if spread_bps is None and bid and ask and last_price:
        spread_bps = ((ask - bid) / last_price) * 10_000.0
    v2_funding_rate = first_number(funding.get("lastFundingRate"), funding.get("funding_rate"))
    coinank_funding_rate = coinank_last_number(coinank_funding, ("fundingRate", "fr", "funding_rate", "rate"), (1, 2))
    funding_rate = first_number(v2_funding_rate, prices.get("funding_rate"), coinank_funding_rate)
    v2_open_interest = first_number(oi.get("openInterest"), oi.get("open_interest"))
    coinank_open_interest = coinank_last_number(
        coinank_oi,
        ("open_interest", "openInterest", "sumOpenInterest", "coinValue", "close", "volume"),
        (4, 3, 1),
    )
    open_interest = first_number(v2_open_interest, prices.get("open_interest"), coinank_open_interest)
    previous_oi = first_number(prices.get("open_interest_prev"))
    oi_change_pct = coinank_oi_change_pct(coinank_oi)
    if open_interest is not None and previous_oi not in (None, 0.0):
        oi_change_pct = ((open_interest - previous_oi) / previous_oi) * 100.0
    volume_1m = first_number(ohlcv_1m[5] if ohlcv_1m and len(ohlcv_1m) > 5 else None)
    volume_5m = first_number(ohlcv_5m[5] if ohlcv_5m and len(ohlcv_5m) > 5 else None)
    quote_volume_24h = first_number(
        ticker_24hr.get("quoteVolume") if isinstance(ticker_24hr, Mapping) else None,
        prices.get("quote_volume"),
    )
    mark = first_number(funding.get("markPrice"), prices.get("mark_price"))
    index = first_number(funding.get("indexPrice"), prices.get("index_price"))
    basis_bps = ((mark - index) / index) * 10_000.0 if mark is not None and index not in (None, 0.0) else None
    long_short_ratio = coinank_last_number(
        coinank_long_short,
        ("longShortRatio", "long_short_ratio", "longRatio", "ratio", "close"),
        (1,),
    )
    coinank_liq_turnover = coinank_liquidation_turnover(coinank_liquidations)

    liquidation_long = first_number(levels.get("liquidation_long_level"))
    liquidation_short = first_number(levels.get("liquidation_short_level"))
    if liquidation_long is None or liquidation_short is None:
        levels_json = json_parse(levels.get("liquidation_levels_json")) or {}
        long_rows = levels_json.get("top_long") if isinstance(levels_json, Mapping) else None
        short_rows = levels_json.get("top_short") if isinstance(levels_json, Mapping) else None
        if liquidation_long is None and isinstance(long_rows, list) and long_rows:
            liquidation_long = first_number(long_rows[0].get("price") if isinstance(long_rows[0], Mapping) else None)
        if liquidation_short is None and isinstance(short_rows, list) and short_rows:
            liquidation_short = first_number(short_rows[0].get("price") if isinstance(short_rows[0], Mapping) else None)
    distance_values = [
        first_number(levels.get("liquidation_long_distance_pct")),
        first_number(levels.get("liquidation_short_distance_pct")),
        first_number(levels.get("liquidation_distance_pct")),
    ]
    distance_values = [abs(value) for value in distance_values if value is not None]

    return {
        "schema_version": "v2_trade_terminal_payload_v1",
        "generated_est": generated,
        "generated_utc": utc_now(),
        "payload_age_seconds": 0,
        "symbol": symbol,
        "data_status": "CURRENT_RUNTIME_PAYLOAD_BUILT",
        "last_price": last_price,
        "last_price_source": "v2:market:coinapi:wsds" if wsds_latest else chart.get("source_type") or "v2:market:prices",
        "bid": bid,
        "ask": ask,
        "spread_bps": spread_bps,
        "book_bid_5": first_number(
            wsds_latest.get("book_bid_sum_5") if isinstance(wsds_latest, Mapping) else None,
            chart_latest.get("book_bid_sum_5"),
        ),
        "book_ask_5": first_number(
            wsds_latest.get("book_ask_sum_5") if isinstance(wsds_latest, Mapping) else None,
            chart_latest.get("book_ask_sum_5"),
        ),
        "book_imbalance": first_number(
            wsds_latest.get("imbalance_5") if isinstance(wsds_latest, Mapping) else None,
            chart_latest.get("imbalance_5"),
        ),
        "orderbook_source": f"v2:market:coinapi:wsds:{symbol}" if wsds_latest else chart.get("_source_path"),
        "depth_source": f"v2:market:coinapi:wsds:{symbol}" if wsds_latest else chart.get("_source_path"),
        "funding_rate": funding_rate,
        "funding_source": (
            f"v2:market:funding:{symbol}"
            if v2_funding_rate is not None
            else f"latest:coinank:funding:{symbol}:15m" if coinank_funding_rate is not None else "NO_CURRENT_FUNDING_SOURCE"
        ),
        "funding_age_seconds": age_from_ms(funding.get("time")) or age_from_iso(funding.get("generated_est")),
        "mark_price": mark,
        "index_price": index,
        "basis_bps": basis_bps,
        "open_interest": open_interest,
        "open_interest_change_pct": oi_change_pct,
        "oi_source": (
            f"v2:market:open_interest:{symbol}"
            if v2_open_interest is not None
            else f"latest:coinank:open_interest:{symbol}:15m" if coinank_open_interest is not None else "NO_CURRENT_OI_SOURCE"
        ),
        "oi_age_seconds": age_from_ms(oi.get("time")) or age_from_iso(oi.get("generated_est")),
        "long_short_ratio": long_short_ratio,
        "long_short_source": f"latest:coinank:long_short:{symbol}:15m" if long_short_ratio is not None else "NO_CURRENT_LONG_SHORT_SOURCE",
        "volume_1m": volume_1m,
        "volume_5m": volume_5m,
        "quote_volume_24h": quote_volume_24h,
        "volume_source": f"v2:market:ohlcv:binance:{symbol}:1m + v2:market:prices:{symbol}"
        if volume_1m is not None or quote_volume_24h is not None
        else "NO_CURRENT_VOLUME_SOURCE",
        "liquidation_event_count": symbol_event_count,
        "coinank_liquidation_turnover_latest": coinank_liq_turnover,
        "liquidation_stream_xlen": event_count,
        "liquidation_level_count": len(levels_keys),
        "liquidation_long_level": liquidation_long,
        "liquidation_short_level": liquidation_short,
        "liquidation_distance_pct": min(distance_values) if distance_values else None,
        "liquidation_source": (
            f"v2:liquidations:levels:{symbol}:*"
            if levels_keys
            else "v2:liquidations:events" if event_count is not None else "NO_CURRENT_LIQUIDATION_SOURCE"
        ),
        "liquidation_age_seconds": age_from_ms(levels.get("liquidation_updated_ts_ms") or levels.get("updated_ts_ms"))
        or age_from_iso(levels.get("generated_est")),
        "live_gate": hold.get("live_gate"),
        "trader_state": hold.get("trader_state"),
        "transport_bound": hold.get("transport_bound") or hold.get("live_order_transport_bound"),
        "signed_read_classification": hold.get("signed_read_classification"),
        "available_margin": hold.get("available_margin"),
        "required_initial_margin": hold.get("required_initial_margin"),
        "balance_hold_reason": (hold.get("blockers") or ["INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER"])[0],
        "accepted_symbols": hold.get("accepted_symbols") or [],
        "active_risk_profile": hold.get("active_risk_profile"),
        "source_keys": {
            "wsds": f"v2:market:coinapi:wsds:{symbol}",
            "funding": f"v2:market:funding:{symbol} / latest:coinank:funding:{symbol}:15m",
            "open_interest": f"v2:market:open_interest:{symbol} / latest:coinank:open_interest:{symbol}:15m",
            "long_short": f"latest:coinank:long_short:{symbol}:15m",
            "prices": f"v2:market:prices:{symbol}",
            "ohlcv_1m": f"v2:market:ohlcv:binance:{symbol}:1m",
            "liquidation_levels": f"v2:liquidations:levels:{symbol}:*",
            "coinank_liquidations": f"latest:coinank:liquidations:{symbol}:15m",
            "liquidation_events": "v2:liquidations:events",
            "live_hold": hold.get("_source_path"),
        },
        "missing_reason_if_any": {
            "funding": None if funding_rate is not None else "NO_CURRENT_FUNDING_SOURCE",
            "open_interest": None if open_interest is not None else "NO_CURRENT_OI_SOURCE",
            "long_short": None if long_short_ratio is not None else "NO_CURRENT_LONG_SHORT_SOURCE",
            "volume": None if volume_1m is not None or quote_volume_24h is not None else "NO_CURRENT_VOLUME_SOURCE",
            "liquidations": None if levels_keys or event_count is not None else "NO_CURRENT_LIQUIDATION_SOURCE",
        },
        "safety": {
            "real_orders": False,
            "test_order": False,
            "leverage_margin_mutation": False,
            "old_redis_write": False,
            "raw_credentials": False,
        },
    }


def _funding_row(client: Any, symbol: str) -> dict[str, Any]:
    payload = redis_json(client, f"v2:market:funding:{symbol}", {}) or {}
    coinank = coinank_latest(client, "funding", symbol)
    v2_rate = first_number(payload.get("lastFundingRate"), payload.get("funding_rate"))
    coinank_rate = coinank_last_number(coinank, ("fundingRate", "fr", "funding_rate", "rate"), (1, 2))
    rate = first_number(v2_rate, coinank_rate)
    mark = first_number(payload.get("markPrice"), payload.get("mark_price"))
    index = first_number(payload.get("indexPrice"), payload.get("index_price"))
    return {
        "symbol": symbol,
        "funding_rate": rate,
        "mark_price": mark,
        "index_price": index,
        "basis_bps": ((mark - index) / index) * 10_000.0 if mark is not None and index not in (None, 0.0) else None,
        "next_funding_time": payload.get("nextFundingTime") or payload.get("next_funding_time"),
        "age_seconds": age_from_ms(payload.get("time")) or age_from_iso(payload.get("generated_est")),
        "source_key": f"v2:market:funding:{symbol}" if v2_rate is not None else f"latest:coinank:funding:{symbol}:15m",
        "data_status": "CURRENT_OR_RECENT" if rate is not None else "NO_CURRENT_FUNDING_SOURCE",
    }


def _oi_row(client: Any, symbol: str) -> dict[str, Any]:
    payload = redis_json(client, f"v2:market:open_interest:{symbol}", {}) or {}
    coinank = coinank_latest(client, "open_interest", symbol)
    v2_value = first_number(payload.get("openInterest"), payload.get("open_interest"))
    coinank_value = coinank_last_number(
        coinank,
        ("open_interest", "openInterest", "sumOpenInterest", "coinValue", "close", "volume"),
        (4, 3, 1),
    )
    value = first_number(v2_value, coinank_value)
    return {
        "symbol": symbol,
        "open_interest": value,
        "open_interest_change_pct": coinank_oi_change_pct(coinank),
        "age_seconds": age_from_ms(payload.get("time")) or age_from_iso(payload.get("generated_est")),
        "source_key": f"v2:market:open_interest:{symbol}" if v2_value is not None else f"latest:coinank:open_interest:{symbol}:15m",
        "data_status": "CURRENT_OR_RECENT" if value is not None else "NO_CURRENT_OI_SOURCE",
    }


def _long_short_row(client: Any, symbol: str) -> dict[str, Any]:
    payload = redis_json(client, f"v2:market:long_short:{symbol}", {}) or {}
    coinank = coinank_latest(client, "long_short", symbol)
    v2_value = first_number(payload.get("long_short_ratio"), payload.get("longShortRatio"))
    coinank_value = coinank_last_number(
        coinank,
        ("longShortRatio", "long_short_ratio", "longRatio", "ratio", "close"),
        (1,),
    )
    value = first_number(v2_value, coinank_value)
    return {
        "symbol": symbol,
        "long_short_ratio": value,
        "age_seconds": age_from_iso(payload.get("generated_est")),
        "source_key": f"v2:market:long_short:{symbol}" if v2_value is not None else f"latest:coinank:long_short:{symbol}:15m",
        "data_status": "CURRENT_OR_RECENT" if value is not None else "NO_CURRENT_LONG_SHORT_SOURCE",
    }


def _liquidation_row(client: Any, symbol: str) -> dict[str, Any]:
    keys = redis_keys(client, f"v2:liquidations:levels:{symbol}:*", limit=20)
    rows = [redis_json(client, key, {}) for key in keys]
    payload = next((row for row in rows if isinstance(row, dict) and row), {})
    latest_events = stream_latest_rows(client, "v2:liquidations:events", 200)
    symbol_events = [row for row in latest_events if str(row.get("symbol") or "").upper() == symbol]
    long_level = first_number(payload.get("liquidation_long_level"))
    short_level = first_number(payload.get("liquidation_short_level"))
    return {
        "symbol": symbol,
        "event_count_latest_window": len(symbol_events),
        "levels_count": len(keys),
        "long_level": long_level,
        "short_level": short_level,
        "long_distance_pct": first_number(payload.get("liquidation_long_distance_pct")),
        "short_distance_pct": first_number(payload.get("liquidation_short_distance_pct")),
        "source_keys": keys[:8] + ["v2:liquidations:events"],
        "age_seconds": age_from_ms(payload.get("liquidation_updated_ts_ms") or payload.get("updated_ts_ms"))
        or age_from_iso(payload.get("generated_est")),
        "data_status": "LEVELS_PRESENT" if keys else "EVENT_WINDOW_EMPTY_BUT_WSS_ACTIVE" if stream_len(client, "v2:liquidations:events") is not None else "NO_CURRENT_LIQUIDATION_EVENT_WINDOW",
    }


def build_derivatives_payload(client: Any = None, symbols: Iterable[str] | None = None) -> dict[str, Any]:
    client = client or connect_redis()
    selected = [str(item).upper() for item in (symbols or accepted_symbols()) if str(item or "").strip()]
    if not selected:
        selected = list(ACCEPTED_SYMBOL_FALLBACK)
    funding_rows = [_funding_row(client, symbol) for symbol in selected]
    oi_rows = [_oi_row(client, symbol) for symbol in selected]
    long_short_rows = [_long_short_row(client, symbol) for symbol in selected]
    liquidation_rows = [_liquidation_row(client, symbol) for symbol in selected]
    basis_rows = [
        {
            "symbol": row["symbol"],
            "basis_bps": row.get("basis_bps"),
            "mark_price": row.get("mark_price"),
            "index_price": row.get("index_price"),
            "source_key": row.get("source_key"),
            "data_status": "CURRENT_OR_RECENT" if row.get("basis_bps") is not None else "NO_CURRENT_BASIS_SOURCE",
        }
        for row in funding_rows
    ]
    hold = latest_signed_hold_payload()
    modules = {
        "funding": {
            "data_status": "CURRENT_OR_RECENT" if any(row.get("funding_rate") is not None for row in funding_rows) else "NO_CURRENT_FUNDING_SOURCE",
            "rows": funding_rows,
            "missing_reason_if_any": None if any(row.get("funding_rate") is not None for row in funding_rows) else "NO_CURRENT_FUNDING_SOURCE",
        },
        "open_interest": {
            "data_status": "CURRENT_OR_RECENT" if any(row.get("open_interest") is not None for row in oi_rows) else "NO_CURRENT_OI_SOURCE",
            "rows": oi_rows,
            "missing_reason_if_any": None if any(row.get("open_interest") is not None for row in oi_rows) else "NO_CURRENT_OI_SOURCE",
        },
        "long_short": {
            "data_status": "CURRENT_OR_RECENT" if any(row.get("long_short_ratio") is not None for row in long_short_rows) else "NO_CURRENT_LONG_SHORT_SOURCE",
            "rows": long_short_rows,
            "missing_reason_if_any": None if any(row.get("long_short_ratio") is not None for row in long_short_rows) else "NO_CURRENT_LONG_SHORT_SOURCE",
        },
        "basis": {
            "data_status": "CURRENT_OR_RECENT" if any(row.get("basis_bps") is not None for row in basis_rows) else "NO_CURRENT_BASIS_SOURCE",
            "rows": basis_rows,
            "missing_reason_if_any": None if any(row.get("basis_bps") is not None for row in basis_rows) else "NO_CURRENT_BASIS_SOURCE",
        },
        "liquidations": {
            "data_status": "CURRENT_OR_RECENT" if any(row.get("levels_count") for row in liquidation_rows) else "EVENT_WINDOW_EMPTY_BUT_WSS_ACTIVE",
            "rows": liquidation_rows,
            "missing_reason_if_any": None if any(row.get("levels_count") for row in liquidation_rows) else "NO_CURRENT_LIQUIDATION_EVENT_WINDOW",
        },
    }
    return {
        "schema_version": "v2_derivatives_payload_v1",
        "generated_est": est_now(),
        "generated_utc": utc_now(),
        "payload_age_seconds": 0,
        "symbols": selected,
        "source_keys": {
            "funding": "v2:market:funding:{symbol} / latest:coinank:funding:{symbol}:15m",
            "open_interest": "v2:market:open_interest:{symbol} / latest:coinank:open_interest:{symbol}:15m",
            "long_short": "v2:market:long_short:{symbol} / latest:coinank:long_short:{symbol}:15m",
            "basis": "v2:market:funding:{symbol}.markPrice/indexPrice",
            "liquidations": "v2:liquidations:events + v2:liquidations:levels:{symbol}:* + latest:coinank:liquidations:{symbol}:15m",
        },
        "live_gate": hold.get("live_gate"),
        "trader_state": hold.get("trader_state"),
        "binance_private_execution": "SIGNED_READS_RECOVERED_BALANCE_HOLD"
        if hold.get("signed_read_classification") == "NO_451_DETECTED"
        else "COMPLIANCE_HELD_HTTP_451",
        "live_submit_allowed": False,
        "live_submit_blocker": (hold.get("blockers") or ["INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER"])[0],
        "accepted_symbols": hold.get("accepted_symbols") or [],
        "modules": modules,
        "exchanges": {
            "generated_est": est_now(),
            "payload_age_seconds": 0,
            "source_keys": "derived from current V2 public runtime keys",
            "data_status": "CURRENT_RUNTIME_SOURCES_PRESENT",
            "rows": [
                {
                    "exchange": "Binance",
                    "public_data_available": True,
                    "private_account_read_available": hold.get("signed_read_classification") == "NO_451_DETECTED",
                    "order_transport_state": "BALANCE_HELD_NO_SUBMIT",
                    "symbols": selected,
                },
                {
                    "exchange": "CoinAPI",
                    "public_data_available": bool(redis_keys(client, "v2:market:coinapi:wsds:*", limit=1)),
                    "private_account_read_available": False,
                    "order_transport_state": "PUBLIC_DATA_ONLY",
                    "symbols": selected,
                },
            ],
            "missing_reason_if_any": None,
        },
        "safety": {
            "real_orders": False,
            "test_order": False,
            "leverage_margin_mutation": False,
            "old_redis_write": False,
            "raw_credentials": False,
        },
    }


def publish_trade_terminal_payload(symbol: str = "BTCUSDT", client: Any = None) -> dict[str, Any]:
    payload = build_trade_terminal_payload(symbol=symbol, client=client)
    TRADE_OUT.mkdir(parents=True, exist_ok=True)
    atomic_write_json(TRADE_OUT / "trade_terminal_payload.json", payload)
    atomic_write_json(TRADE_OUT / "operator_dashboard_payload.json", payload)
    return payload


def publish_derivatives_payload(client: Any = None, symbols: Iterable[str] | None = None) -> dict[str, Any]:
    payload = build_derivatives_payload(client=client, symbols=symbols)
    DERIVATIVES_OUT.mkdir(parents=True, exist_ok=True)
    atomic_write_json(DERIVATIVES_OUT / "derivatives_payload.json", payload)
    atomic_write_json(DERIVATIVES_OUT / "operator_dashboard_payload.json", payload)
    return payload
