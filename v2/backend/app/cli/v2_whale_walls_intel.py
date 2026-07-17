"""V2 whale-wall intelligence worker.

Derives single-price and ladder wall features from the V2 Binance orderbook
snapshots already produced by the native ingestors. This lane is fully
native/derived — no external provider API is involved.

(History: this derivation previously lived inside the combined AICoin
free-tier worker; the AICoin provider was removed system-wide by operator
directive on 2026-07-16 and the whale-wall lane was extracted unchanged.)

Allowed Redis writes:

* ``v2:altdata:whale_walls:status``
* ``v2:altdata:whale_walls:symbol:{symbol}``

No old Redis keys, exchange mutation, trader control, or live/canary
authorization is possible from this module.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

DEFAULT_INTERVAL_SECONDS = 3_600
V2_REDIS_PREFIX = "v2:"

KEY_WHALE_STATUS = "v2:altdata:whale_walls:status"
KEY_WHALE_SYMBOL_PREFIX = "v2:altdata:whale_walls:symbol:"

ALLOWED_REDIS_EXACT_KEYS = (KEY_WHALE_STATUS,)
ALLOWED_REDIS_PREFIXES = (KEY_WHALE_SYMBOL_PREFIX,)


@dataclass(frozen=True)
class WallLevel:
    price: float
    quantity: float
    notional_usd: float
    distance_bps: float | None


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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


def _json_loads(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _redis_get_json(redis_client: Any, key: str) -> dict[str, Any] | None:
    if redis_client is None:
        return None
    try:
        return _json_loads(redis_client.get(key))
    except Exception:
        return None


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
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


def _round(value: float | None, places: int = 6) -> float | None:
    return round(value, places) if value is not None else None


def _book_event_age_seconds(book: Mapping[str, Any], generated_utc: str) -> int | None:
    event_ms = _to_float(book.get("E") or book.get("T") or book.get("event_time_ms"))
    if event_ms is None:
        return None
    now = _parse_utc(generated_utc)
    if now is None:
        return None
    event = datetime.fromtimestamp(event_ms / 1000.0, tz=timezone.utc)
    return max(0, int((now - event).total_seconds()))


def _level_tuple(raw: Any) -> tuple[float, float] | None:
    if isinstance(raw, Mapping):
        price = _to_float(raw.get("price") or raw.get("p"))
        qty = _to_float(raw.get("quantity") or raw.get("qty") or raw.get("q") or raw.get("size"))
    elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
        price = _to_float(raw[0])
        qty = _to_float(raw[1])
    else:
        return None
    if price is None or qty is None or price <= 0 or qty <= 0:
        return None
    return price, qty


def _levels(raw_levels: Any, *, mid_price: float | None) -> list[WallLevel]:
    out: list[WallLevel] = []
    if not isinstance(raw_levels, list):
        return out
    for raw in raw_levels:
        pair = _level_tuple(raw)
        if pair is None:
            continue
        price, qty = pair
        distance_bps = None
        if mid_price and mid_price > 0:
            distance_bps = abs(price - mid_price) / mid_price * 10_000.0
        out.append(
            WallLevel(
                price=price,
                quantity=qty,
                notional_usd=price * qty,
                distance_bps=distance_bps,
            )
        )
    return out


def _mid_price(book: Mapping[str, Any]) -> float | None:
    bid = _level_tuple((book.get("bids") or [None])[0]) if book.get("bids") else None
    ask = _level_tuple((book.get("asks") or [None])[0]) if book.get("asks") else None
    if bid and ask:
        return (bid[0] + ask[0]) / 2.0
    price = _to_float(book.get("price") or book.get("last") or book.get("last_price"))
    return price if price and price > 0 else None


def _wall_floor(
    levels: list[WallLevel],
    *,
    mid_price: float | None,
    min_notional_usd: float,
    min_base_quantity: float,
    min_market_share: float,
) -> float:
    side_notional = sum(level.notional_usd for level in levels)
    qty_floor = (mid_price or 0.0) * max(0.0, min_base_quantity)
    share_floor = side_notional * max(0.0, min_market_share)
    return max(0.0, min_notional_usd, qty_floor, share_floor)


def _single_price_walls(levels: list[WallLevel], floor: float) -> list[WallLevel]:
    return [level for level in levels if level.notional_usd >= floor]


def _ladder_clusters(
    levels: list[WallLevel],
    *,
    floor: float,
    min_rungs: int,
    quantity_tolerance_pct: float,
    max_span_bps: float,
) -> list[dict[str, Any]]:
    clusters: list[list[WallLevel]] = []
    current: list[WallLevel] = []
    for level in levels:
        if not current:
            current = [level]
            continue
        first = current[0]
        prev = current[-1]
        qty_base = max(abs(prev.quantity), abs(level.quantity), 1e-12)
        qty_close = abs(level.quantity - prev.quantity) / qty_base <= quantity_tolerance_pct
        span_bps = None
        if first.distance_bps is not None and level.distance_bps is not None:
            span_bps = abs(first.distance_bps - level.distance_bps)
        price_close = span_bps is None or span_bps <= max_span_bps
        if qty_close and price_close:
            current.append(level)
        else:
            if len(current) >= min_rungs:
                clusters.append(current)
            current = [level]
    if len(current) >= min_rungs:
        clusters.append(current)

    out: list[dict[str, Any]] = []
    for cluster in clusters:
        total = sum(level.notional_usd for level in cluster)
        if total < floor:
            continue
        out.append(
            {
                "rungs": len(cluster),
                "price_min": min(level.price for level in cluster),
                "price_max": max(level.price for level in cluster),
                "quantity_min": min(level.quantity for level in cluster),
                "quantity_max": max(level.quantity for level in cluster),
                "total_notional_usd": round(total, 3),
                "nearest_distance_bps": _round(
                    min(
                        (
                            level.distance_bps
                            for level in cluster
                            if level.distance_bps is not None
                        ),
                        default=None,
                    )
                ),
            }
        )
    return out


def _summarize_side(
    levels: list[WallLevel],
    *,
    floor: float,
    min_ladder_rungs: int,
    ladder_quantity_tolerance_pct: float,
    ladder_max_span_bps: float,
) -> dict[str, Any]:
    singles = _single_price_walls(levels, floor)
    ladders = _ladder_clusters(
        levels,
        floor=floor,
        min_rungs=min_ladder_rungs,
        quantity_tolerance_pct=ladder_quantity_tolerance_pct,
        max_span_bps=ladder_max_span_bps,
    )
    single_notional = sum(level.notional_usd for level in singles)
    ladder_notional = sum(float(cluster["total_notional_usd"]) for cluster in ladders)
    wall_notional = max(single_notional, ladder_notional)
    nearest = min(
        (level.distance_bps for level in singles if level.distance_bps is not None),
        default=None,
    )
    if nearest is None:
        nearest = min(
            (
                float(cluster["nearest_distance_bps"])
                for cluster in ladders
                if cluster.get("nearest_distance_bps") is not None
            ),
            default=None,
        )
    return {
        "level_count": len(levels),
        "market_notional_usd": round(sum(level.notional_usd for level in levels), 3),
        "wall_floor_usd": round(floor, 3),
        "single_price_wall_count": len(singles),
        "ladder_wall_count": len(ladders),
        "wall_count": len(singles) + len(ladders),
        "wall_notional_usd": round(wall_notional, 3),
        "max_single_wall_notional_usd": round(max((l.notional_usd for l in singles), default=0.0), 3),
        "nearest_wall_distance_bps": _round(nearest),
        "single_price_walls": [
            {
                "price": level.price,
                "quantity": level.quantity,
                "notional_usd": round(level.notional_usd, 3),
                "distance_bps": _round(level.distance_bps),
            }
            for level in singles[:10]
        ],
        "ladder_walls": ladders[:10],
    }


def _build_whale_payload(
    symbol: str,
    book: Mapping[str, Any] | None,
    *,
    generated_utc: str,
    min_notional_usd: float,
    min_base_quantity: float,
    min_market_share: float,
    min_ladder_rungs: int,
    ladder_quantity_tolerance_pct: float,
    ladder_max_span_bps: float,
) -> dict[str, Any]:
    if not isinstance(book, Mapping):
        return {
            "schema_version": "v2_altdata_whale_wall_symbol_signal_v1",
            "generated_utc": generated_utc,
            "symbol": symbol,
            "provider": "whale_walls",
            "source_status": "MISSING_ORDERBOOK_INPUT",
            "whale_wall_score": None,
            "provider_freshness_seconds": None,
            "missing_feature_flags": ["v2_market_orderbook_missing"],
            "stale_feature_flags": [],
            "network_call_attempted": False,
            "paper_shadow_only": True,
        }

    mid = _mid_price(book)
    bids = _levels(book.get("bids"), mid_price=mid)
    asks = _levels(book.get("asks"), mid_price=mid)
    bid_floor = _wall_floor(
        bids,
        mid_price=mid,
        min_notional_usd=min_notional_usd,
        min_base_quantity=min_base_quantity,
        min_market_share=min_market_share,
    )
    ask_floor = _wall_floor(
        asks,
        mid_price=mid,
        min_notional_usd=min_notional_usd,
        min_base_quantity=min_base_quantity,
        min_market_share=min_market_share,
    )
    bid_summary = _summarize_side(
        bids,
        floor=bid_floor,
        min_ladder_rungs=min_ladder_rungs,
        ladder_quantity_tolerance_pct=ladder_quantity_tolerance_pct,
        ladder_max_span_bps=ladder_max_span_bps,
    )
    ask_summary = _summarize_side(
        asks,
        floor=ask_floor,
        min_ladder_rungs=min_ladder_rungs,
        ladder_quantity_tolerance_pct=ladder_quantity_tolerance_pct,
        ladder_max_span_bps=ladder_max_span_bps,
    )
    bid_wall_notional = float(bid_summary["wall_notional_usd"])
    ask_wall_notional = float(ask_summary["wall_notional_usd"])
    total_wall_notional = bid_wall_notional + ask_wall_notional
    if total_wall_notional > 0:
        imbalance = (bid_wall_notional - ask_wall_notional) / total_wall_notional
        score = (imbalance + 1.0) / 2.0
        bid_pressure = bid_wall_notional / total_wall_notional
        ask_pressure = ask_wall_notional / total_wall_notional
    else:
        imbalance = 0.0
        score = 0.5
        bid_pressure = 0.0
        ask_pressure = 0.0
    wall_count = int(bid_summary["wall_count"]) + int(ask_summary["wall_count"])
    age = _book_event_age_seconds(book, generated_utc)
    missing_flags: list[str] = []
    if not bids:
        missing_flags.append("orderbook_bids_missing")
    if not asks:
        missing_flags.append("orderbook_asks_missing")
    source_status = "DERIVED_OK" if not missing_flags else "MISSING_ORDERBOOK_SIDE"
    return {
        "schema_version": "v2_altdata_whale_wall_symbol_signal_v1",
        "generated_utc": generated_utc,
        "symbol": symbol,
        "provider": "whale_walls",
        "source_status": source_status,
        "reference_repository": "https://github.com/pmaji/crypto-whale-watching-app",
        "methodology": "single_price_point_and_ladder_wall_detection_from_v2_orderbook",
        "mid_price": _round(mid),
        "orderbook_level_count": len(bids) + len(asks),
        "orderbook_event_age_seconds": age,
        "provider_freshness_seconds": age,
        "whale_wall_score": _round(_clamp01(score)),
        "whale_bid_pressure_score": _round(_clamp01(bid_pressure)),
        "whale_ask_pressure_score": _round(_clamp01(ask_pressure)),
        "whale_wall_imbalance_score": _round(_clamp(imbalance, -1.0, 1.0)),
        "whale_wall_count_score": _round(_clamp01(wall_count / 8.0)),
        "whale_wall_event_count": wall_count,
        "whale_wall_detected": wall_count > 0,
        "whale_bid_wall_notional_usd": bid_wall_notional,
        "whale_ask_wall_notional_usd": ask_wall_notional,
        "whale_total_wall_notional_usd": round(total_wall_notional, 3),
        "nearest_bid_wall_distance_bps": bid_summary["nearest_wall_distance_bps"],
        "nearest_ask_wall_distance_bps": ask_summary["nearest_wall_distance_bps"],
        "bid_wall_summary": bid_summary,
        "ask_wall_summary": ask_summary,
        "thresholds": {
            "min_notional_usd": min_notional_usd,
            "min_base_quantity": min_base_quantity,
            "min_market_share": min_market_share,
            "min_ladder_rungs": min_ladder_rungs,
            "ladder_quantity_tolerance_pct": ladder_quantity_tolerance_pct,
            "ladder_max_span_bps": ladder_max_span_bps,
        },
        "missing_feature_flags": missing_flags,
        "stale_feature_flags": [],
        "network_call_attempted": False,
        "paper_shadow_only": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
    }


def run_once(
    *,
    symbols: Iterable[str] | None = None,
    redis_client_override: Any | None = None,
    write_redis: bool = True,
    min_notional_usd: float = 100_000.0,
    min_base_quantity: float = 1.0,
    min_market_share: float = 0.01,
    min_ladder_rungs: int = 3,
    ladder_quantity_tolerance_pct: float = 0.02,
    ladder_max_span_bps: float = 50.0,
    smoke_test: bool = False,
) -> dict[str, Any]:
    redis_client = (
        redis_client_override if redis_client_override is not None else _connect_redis()
    )
    generated_utc = utc_iso()
    resolved = tuple(symbols) if symbols is not None else tuple(resolve_symbols(smoke_test=smoke_test))
    normalized_symbols = tuple(sorted({str(s).strip().upper() for s in resolved if str(s).strip()}))

    whale_payloads: dict[str, dict[str, Any]] = {}
    for symbol in normalized_symbols:
        book = _redis_get_json(redis_client, f"v2:market:orderbook:{symbol}")
        if book is None:
            book = _redis_get_json(redis_client, f"v2:market:orderbook:binance:{symbol}")
        whale_payloads[symbol] = _build_whale_payload(
            symbol,
            book,
            generated_utc=generated_utc,
            min_notional_usd=min_notional_usd,
            min_base_quantity=min_base_quantity,
            min_market_share=min_market_share,
            min_ladder_rungs=min_ladder_rungs,
            ladder_quantity_tolerance_pct=ladder_quantity_tolerance_pct,
            ladder_max_span_bps=ladder_max_span_bps,
        )

    whale_status_counts: dict[str, int] = {}
    for payload in whale_payloads.values():
        status = str(payload.get("source_status") or "UNKNOWN")
        whale_status_counts[status] = whale_status_counts.get(status, 0) + 1

    whale_status = {
        "schema_version": "v2_altdata_whale_walls_status_v1",
        "generated_utc": generated_utc,
        "provider": "whale_walls",
        "source_status_counts": whale_status_counts,
        "symbol_count": len(normalized_symbols),
        "successful_symbol_count": sum(
            1 for p in whale_payloads.values() if p.get("source_status") == "DERIVED_OK"
        ),
        "wall_detected_symbol_count": sum(
            1 for p in whale_payloads.values() if p.get("whale_wall_detected") is True
        ),
        "network_call_attempted": False,
        "reference_repository": "https://github.com/pmaji/crypto-whale-watching-app",
    }

    redis_write_results: dict[str, bool] = {}
    if write_redis and redis_client is not None:
        redis_write_results[KEY_WHALE_STATUS] = _safe_redis_set(
            redis_client, KEY_WHALE_STATUS, whale_status
        )
        for symbol, payload in whale_payloads.items():
            redis_write_results[f"{KEY_WHALE_SYMBOL_PREFIX}{symbol}"] = _safe_redis_set(
                redis_client, f"{KEY_WHALE_SYMBOL_PREFIX}{symbol}", payload
            )

    return {
        "schema_version": "v2_whale_walls_intel_status_v1",
        "generated_utc": generated_utc,
        "symbol_count": len(normalized_symbols),
        "symbols": list(normalized_symbols),
        "whale_walls_status": whale_status,
        "whale_payloads": whale_payloads,
        "redis_write_results": redis_write_results,
        "auto_updates_symbol_scoring": True,
        "auto_updates_trainer_via_symbol_score": True,
        "auto_updates_trading_candidates_not_execution": True,
        "dynamic_symbol_refresh_without_restart": True,
        "provider_network_calls_attempted": False,
        "paper_shadow_only": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "execution_live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "exchange_mutation": False,
        "raw_credential_value_exposed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_whale_walls_intel")
    parser.add_argument("--once", action="store_true", default=True)
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--no-redis", action="store_true")
    parser.add_argument("--min-notional-usd", type=float, default=100_000.0)
    parser.add_argument("--min-base-quantity", type=float, default=1.0)
    parser.add_argument("--min-market-share", type=float, default=0.01)
    args = parser.parse_args(argv)
    symbols = (
        tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
        if args.symbols
        else None
    )
    while True:
        payload = run_once(
            symbols=symbols,
            write_redis=not args.no_redis,
            min_notional_usd=args.min_notional_usd,
            min_base_quantity=args.min_base_quantity,
            min_market_share=args.min_market_share,
            smoke_test=args.smoke_test,
        )
        print(
            json.dumps(
                {
                    "symbol_count": payload["symbol_count"],
                    "whale_successful_symbol_count": payload["whale_walls_status"][
                        "successful_symbol_count"
                    ],
                    "wall_detected_symbol_count": payload["whale_walls_status"][
                        "wall_detected_symbol_count"
                    ],
                    "live_symbols": payload["live_symbols"],
                    "writes_legacy_redis": payload["writes_legacy_redis"],
                    "writes_exchange_orders": payload["writes_exchange_orders"],
                },
                sort_keys=True,
            )
        )
        if not args.loop:
            return 0
        time.sleep(max(1, int(args.interval_seconds)))


if __name__ == "__main__":
    sys.exit(main())
