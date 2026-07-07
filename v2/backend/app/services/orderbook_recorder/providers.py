"""Provider-specific direct public orderbook message adapters."""
from __future__ import annotations

import json
import re
from typing import Any


KUCOIN_FUTURES_SYMBOL_ALIASES = {
    "BTCUSDT": "XBTUSDTM",
    # KuCoin futures publishes these under base-token contracts with multipliers,
    # while Binance and the V2 universe use 1000-prefixed symbols.
    "1000FLOKIUSDT": "FLOKIUSDTM",
    "1000PEPEUSDT": "PEPEUSDTM",
    "1000SHIBUSDT": "SHIBUSDTM",
}
KUCOIN_FUTURES_REVERSE_ALIASES = {
    provider_symbol: v2_symbol
    for v2_symbol, provider_symbol in KUCOIN_FUTURES_SYMBOL_ALIASES.items()
}


def build_binance_stream_names(
    symbols: list[str],
    *,
    partial_levels: int | list[int] | tuple[int, ...] = (5, 10, 20),
    speed: str = "100ms",
    include_book_ticker: bool = True,
    include_diff_depth: bool = True,
) -> list[str]:
    streams: list[str] = []
    suffix = f"@{speed}" if speed in {"100ms", "500ms"} else ""
    if isinstance(partial_levels, int):
        levels = [partial_levels]
    else:
        levels = [int(level) for level in partial_levels]
    for symbol in symbols:
        normalized = symbol.strip().lower()
        if not normalized:
            continue
        if include_book_ticker:
            streams.append(f"{normalized}@bookTicker")
        for level in levels:
            streams.append(f"{normalized}@depth{int(level)}{suffix}")
        if include_diff_depth:
            streams.append(f"{normalized}@depth{suffix}")
    return streams


def parse_binance_message(raw: Any) -> dict[str, Any] | None:
    payload = _loads(raw)
    if not isinstance(payload, dict):
        return None
    stream = str(payload.get("stream") or "")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return None
    event_type = str(data.get("e") or "")
    symbol = str(data.get("s") or stream.split("@", 1)[0]).upper()
    if not symbol:
        return None
    if event_type == "bookTicker" or {"b", "B", "a", "A"}.issubset(data.keys()):
        return {
            "exchange": "binance",
            "symbol": symbol,
            "type": "book_ticker",
            "bids": [[data.get("b"), data.get("B")]],
            "asks": [[data.get("a"), data.get("A")]],
            "event_time_ms": data.get("E") or data.get("T"),
            "transaction_time_ms": data.get("T"),
            "sequence_id": data.get("u"),
            "previous_sequence_id": None,
            "first_sequence_id": data.get("u"),
            "final_sequence_id": data.get("u"),
            "is_snapshot": True,
            "depth_level": 1,
            "feed_speed_ms": None,
            "raw": data,
        }
    if event_type == "depthUpdate" or "depth" in stream:
        is_partial = "@depth" in stream and "@depth@" not in stream and any(token in stream for token in ("depth5", "depth10", "depth20"))
        if "depth5" in stream or "depth10" in stream or "depth20" in stream:
            is_partial = True
        depth_level = _binance_depth_level_from_stream(stream) if is_partial else None
        return {
            "exchange": "binance",
            "symbol": symbol,
            "type": "partial_depth" if is_partial else "diff_depth",
            "bids": data.get("b") or [],
            "asks": data.get("a") or [],
            "event_time_ms": data.get("E"),
            "transaction_time_ms": data.get("T"),
            "first_sequence_id": data.get("U"),
            "final_sequence_id": data.get("u"),
            "sequence_id": data.get("u"),
            "previous_sequence_id": data.get("pu"),
            "is_snapshot": is_partial,
            "depth_level": depth_level,
            "feed_speed_ms": _binance_speed_ms_from_stream(stream),
            "raw": data,
        }
    return None


def kucoin_v2_symbol_to_spot(symbol: str) -> str:
    normalized = symbol.upper().replace("-", "")
    if normalized.endswith("USDT"):
        return f"{normalized[:-4]}-USDT"
    if normalized.endswith("BTC"):
        return f"{normalized[:-3]}-BTC"
    return normalized


def kucoin_v2_symbol_to_futures(symbol: str) -> str:
    normalized = symbol.upper().replace("-", "")
    if normalized in KUCOIN_FUTURES_SYMBOL_ALIASES:
        return KUCOIN_FUTURES_SYMBOL_ALIASES[normalized]
    if normalized.endswith("USDTM"):
        return normalized
    if normalized.endswith("USDT"):
        return f"{normalized}M"
    return normalized


def build_kucoin_subscription_messages(
    symbols: list[str],
    *,
    trade_type: str = "FUTURES",
    depth: str = "all",
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    normalized_trade_type = trade_type.upper()
    for index, symbol in enumerate(symbols):
        kucoin_symbol = (
            kucoin_v2_symbol_to_futures(symbol)
            if normalized_trade_type == "FUTURES"
            else kucoin_v2_symbol_to_spot(symbol)
        )
        depths = ["5", "50", "increment@10ms"] if depth == "all" else [depth]
        for depth_index, selected_depth in enumerate(depths):
            topic = _kucoin_orderbook_topic(kucoin_symbol, trade_type=normalized_trade_type, depth=selected_depth)
            messages.append(
                {
                    "id": f"v2-direct-orderbook-{index}-{depth_index}",
                    "type": "subscribe",
                    "topic": topic,
                    "response": True,
                }
            )
    return messages


def parse_kucoin_message(raw: Any) -> dict[str, Any] | None:
    payload = _loads(raw)
    if not isinstance(payload, dict):
        return None
    data = payload.get("d") if isinstance(payload.get("d"), dict) else payload.get("data")
    if not isinstance(data, dict):
        return None
    topic = str(payload.get("topic") or "")
    symbol = str(data.get("s") or payload.get("symbol") or _kucoin_symbol_from_topic(topic) or "").upper()
    if not symbol:
        return None
    event_type = str(payload.get("t") or data.get("type") or "").lower()
    depth = str(payload.get("dp") or payload.get("depth") or "")
    if not depth:
        depth = _kucoin_depth_from_topic(topic)
    bids, asks = _kucoin_book_changes(data)
    is_snapshot = (
        event_type == "snapshot"
        or depth in {"1", "5", "50"}
        or "level2Depth5" in topic
        or "level2Depth50" in topic
        or (not event_type and not data.get("change") and not data.get("changes"))
    )
    return {
        "exchange": "kucoin",
        "symbol": _kucoin_symbol_to_v2(symbol),
        "provider_symbol": symbol,
        "type": f"obu_{depth or 'unknown'}",
        "bids": bids,
        "asks": asks,
        "event_time_ms": data.get("M") or data.get("ts") or data.get("timestamp") or payload.get("P") or payload.get("sn"),
        "transaction_time_ms": data.get("M") or data.get("ts") or data.get("timestamp"),
        "first_sequence_id": data.get("O") or data.get("sequenceStart") or data.get("sequence"),
        "final_sequence_id": data.get("C") or data.get("sequenceEnd") or data.get("sequence") or payload.get("sn"),
        "sequence_id": data.get("C") or data.get("sequence") or payload.get("sn"),
        "previous_sequence_id": None,
        "is_snapshot": is_snapshot,
        "depth_level": _kucoin_depth_level(depth),
        "feed_speed_ms": _kucoin_speed_ms(depth),
        "raw": payload,
    }


def _kucoin_orderbook_topic(symbol: str, *, trade_type: str, depth: str) -> str:
    if trade_type.upper() == "FUTURES":
        if depth == "5":
            return f"/contractMarket/level2Depth5:{symbol}"
        if depth == "50":
            return f"/contractMarket/level2Depth50:{symbol}"
        return f"/contractMarket/level2:{symbol}"
    if depth == "5":
        return f"/spotMarket/level2Depth5:{symbol}"
    if depth == "50":
        return f"/spotMarket/level2Depth50:{symbol}"
    return f"/market/level2:{symbol}"


def _kucoin_symbol_from_topic(topic: str) -> str:
    if ":" not in topic:
        return ""
    tail = topic.split(":", 1)[1]
    return tail.split(",", 1)[0].replace("#", "").strip()


def _kucoin_depth_from_topic(topic: str) -> str:
    if "Depth50" in topic:
        return "50"
    if "Depth5" in topic:
        return "5"
    if "level2" in topic:
        return "increment"
    return ""


def _kucoin_depth_level(depth: str) -> int | str | None:
    if depth in {"5", "50"}:
        return int(depth)
    if depth in {"increment", "increment@10ms"}:
        return "increment_best_500"
    return None


def _kucoin_speed_ms(depth: str) -> int | None:
    if depth in {"5", "50"}:
        return 100
    if depth in {"increment", "increment@10ms"}:
        return 10
    return None


def _kucoin_book_changes(data: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    bids = data.get("bids") or data.get("b") or []
    asks = data.get("asks") or data.get("a") or []
    changes = data.get("changes")
    if isinstance(changes, dict):
        bids = changes.get("bids") or changes.get("buy") or bids
        asks = changes.get("asks") or changes.get("sell") or asks
    change = data.get("change")
    if isinstance(change, str):
        parts = [part.strip() for part in change.split(",")]
        if len(parts) >= 3:
            price, side, size = parts[0], parts[1].lower(), parts[2]
            if side in {"buy", "bid", "bids"}:
                bids = [[price, size]]
                asks = []
            elif side in {"sell", "ask", "asks"}:
                asks = [[price, size]]
                bids = []
    return list(bids or []), list(asks or [])


def _binance_depth_level_from_stream(stream: str) -> int | None:
    match = re.search(r"depth(5|10|20)", stream)
    return int(match.group(1)) if match else None


def _binance_speed_ms_from_stream(stream: str) -> int:
    if "@100ms" in stream:
        return 100
    if "@500ms" in stream:
        return 500
    return 250


def _kucoin_symbol_to_v2(symbol: str) -> str:
    normalized = symbol.upper().replace("-", "")
    if normalized in KUCOIN_FUTURES_REVERSE_ALIASES:
        return KUCOIN_FUTURES_REVERSE_ALIASES[normalized]
    if symbol == "XBTUSDTM":
        return "BTCUSDT"
    if normalized.endswith("USDTM"):
        return normalized[:-1]
    return normalized


def _loads(raw: Any) -> Any:
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return None
    return raw
