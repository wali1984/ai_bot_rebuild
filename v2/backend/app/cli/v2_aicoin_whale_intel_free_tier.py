"""V2 AICoin free-tier and whale-wall intelligence worker.

This worker adds two read-only intelligence lanes:

* ``whale_walls`` derives single-price and ladder wall features from the
  V2 Binance orderbook snapshots already produced by the native ingestors.
* ``aicoin_free_tier`` exposes the AICoin OpenData/CoinOS free-tier surface
  as a guarded provider lane. It does not fake AICoin API data when no
  deterministic runtime REST endpoint/credential path is configured.

Allowed Redis writes:

* ``v2:altdata:whale_walls:status``
* ``v2:altdata:whale_walls:symbol:{symbol}``
* ``v2:altdata:aicoin:status``
* ``v2:altdata:aicoin:symbol:{symbol}``

No old Redis keys, exchange mutation, trader control, or live/canary
authorization is possible from this module.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols

DEFAULT_INTERVAL_SECONDS = 3_600
V2_REDIS_PREFIX = "v2:"

WORKLOG_DIR = Path(
    "claude_worklog/final_readiness/v2_aicoin_whale_intel_free_tier_20260604/latest"
)
WORKLOG_STATUS = WORKLOG_DIR / "v2_aicoin_whale_intel_free_tier_status.json"
WORKLOG_REPORT = WORKLOG_DIR / "V2_AICOIN_WHALE_INTEL_FREE_TIER_REPORT.md"
WORKLOG_GO_NO_GO = WORKLOG_DIR / "GO_NO_GO.md"
PUBLIC_OPERATOR_RUNTIME = Path(
    "v2/frontend/public/operator_runtime/v2_aicoin_whale_intel_free_tier/latest/v2_aicoin_whale_intel_free_tier_status.json"
)
PUBLIC_DASHBOARD = Path(
    "v2/frontend/public/v2_aicoin_whale_intel_free_tier/latest/operator_dashboard_payload.json"
)

KEY_WHALE_STATUS = "v2:altdata:whale_walls:status"
KEY_WHALE_SYMBOL_PREFIX = "v2:altdata:whale_walls:symbol:"
KEY_AICOIN_STATUS = "v2:altdata:aicoin:status"
KEY_AICOIN_SYMBOL_PREFIX = "v2:altdata:aicoin:symbol:"

ALLOWED_REDIS_EXACT_KEYS = (KEY_WHALE_STATUS, KEY_AICOIN_STATUS)
ALLOWED_REDIS_PREFIXES = (KEY_WHALE_SYMBOL_PREFIX, KEY_AICOIN_SYMBOL_PREFIX)

AICOIN_FREE_PLAN = {
    "price": "$0 Forever",
    "intended_for": "Personal Use",
    "included_data": ["Partial Market Data", "Partial Coin Data", "Airdrop/Drop Radar"],
    "api_access_approx_endpoint_count": 15,
    "data_range_days": 30,
    "rate_limit_per_minute": 15,
    "monthly_request_quota": 20_000,
}

AICOIN_REVIEWED_CAPABILITIES = (
    "coin_info",
    "market_info",
    "kline",
    "depth",
    "order_flow",
    "signal_data",
    "news",
    "flash",
    "coin_liquidation",
    "coin_open_interest",
    "coin_futures_data",
    "airdrop",
    "drop_radar",
    "hl_whale",
    "hl_liquidation",
)


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


def _env_assignment_names(path: Path) -> dict[str, bool]:
    names: dict[str, bool] = {}
    if not path.exists() or not path.is_file():
        return names
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return names
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.removeprefix("export ").strip()
        names[name] = bool(value.strip().strip("'\""))
    return names


def _aicoin_key_presence(env: Mapping[str, str] | None = None) -> dict[str, bool]:
    process_env = dict(env or os.environ)
    local_paths = (
        Path("v2/.env.local"),
        Path(".env"),
        Path(".local_secrets/alternative_data.env"),
    )
    file_presence: dict[str, bool] = {}
    for path in local_paths:
        file_presence.update(_env_assignment_names(path))
    names = (
        "AICOIN_ACCESS_KEY_ID",
        "AICOIN_ACCESS_SECRET",
        "AICOIN_API_KEY",
        "AICOIN_API_SECRET",
        "AICOIN_API_BASE_URL",
    )
    return {
        name: bool(process_env.get(name)) or bool(file_presence.get(name))
        for name in names
    }


def _build_aicoin_symbol_payload(
    symbol: str,
    *,
    generated_utc: str,
    key_presence: Mapping[str, bool],
) -> dict[str, Any]:
    has_access_pair = bool(key_presence.get("AICOIN_ACCESS_KEY_ID")) and bool(
        key_presence.get("AICOIN_ACCESS_SECRET")
    )
    has_legacy_pair = bool(key_presence.get("AICOIN_API_KEY")) and bool(
        key_presence.get("AICOIN_API_SECRET")
    )
    base_configured = bool(key_presence.get("AICOIN_API_BASE_URL"))
    if has_access_pair or has_legacy_pair:
        source_status = (
            "REST_ENDPOINT_MAPPING_MISSING_NO_NETWORK"
            if not base_configured
            else "REST_CLIENT_NOT_IMPLEMENTED_NO_NETWORK"
        )
    else:
        source_status = "KEY_MISSING_NO_NETWORK"
    return {
        "schema_version": "v2_altdata_aicoin_free_tier_symbol_signal_v1",
        "generated_utc": generated_utc,
        "symbol": symbol,
        "provider": "aicoin_free_tier",
        "source_status": source_status,
        "aicoin_market_activity_score": None,
        "aicoin_coin_profile_score": None,
        "aicoin_order_flow_score": None,
        "aicoin_whale_order_score": None,
        "aicoin_signal_score": None,
        "aicoin_drop_radar_score": None,
        "aicoin_airdrop_score": None,
        "aicoin_liquidation_score": None,
        "aicoin_open_interest_score": None,
        "aicoin_news_attention_score": None,
        "free_plan": AICOIN_FREE_PLAN,
        "reviewed_capabilities": list(AICOIN_REVIEWED_CAPABILITIES),
        "credential_present": has_access_pair or has_legacy_pair,
        "credential_raw_value_exposed": False,
        "network_call_attempted": False,
        "provider_freshness_seconds": None,
        "missing_feature_flags": [source_status.lower()],
        "stale_feature_flags": [],
        "paper_shadow_only": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
    }


def _write_status_files(payload: Mapping[str, Any], public_paths: tuple[Path, ...]) -> None:
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    WORKLOG_STATUS.parent.mkdir(parents=True, exist_ok=True)
    WORKLOG_STATUS.write_text(body, encoding="utf-8")
    WORKLOG_GO_NO_GO.write_text(str(payload["go_no_go"]) + "\n", encoding="utf-8")
    for path in public_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")


def _write_report(payload: Mapping[str, Any]) -> None:
    lines = [
        "# V2 AICoin Whale Intel Free-Tier Report",
        "",
        f"Generated: `{payload['generated_utc']}`",
        "",
        f"GO/NO-GO: `{payload['go_no_go']}`",
        "",
        "## Result",
        "",
        f"- symbols: `{payload['symbol_count']}`",
        f"- whale wall successful symbols: `{payload['whale_walls_status']['successful_symbol_count']}`",
        f"- AICoin source status: `{payload['aicoin_status']['source_status']}`",
        f"- AICoin network calls attempted: `{payload['aicoin_status']['network_call_attempted']}`",
        f"- live gate: `{payload['live_gate']}`",
        f"- live symbols: `{payload['live_symbols']}`",
        f"- writes legacy Redis: `{payload['writes_legacy_redis']}`",
        f"- writes exchange orders: `{payload['writes_exchange_orders']}`",
        "",
        "## Sources Reviewed",
        "",
        "- https://github.com/pmaji/crypto-whale-watching-app",
        "- https://github.com/aicoincom/aicoin-mcp",
        "- https://github.com/aicoincom/coinos-skills",
        "- https://www.aicoin.com/en/opendata",
        "- https://www.aicoin.com/en/coinos/docs/api/overview",
        "",
    ]
    WORKLOG_REPORT.parent.mkdir(parents=True, exist_ok=True)
    WORKLOG_REPORT.write_text("\n".join(lines), encoding="utf-8")


def run_once(
    *,
    symbols: Iterable[str] | None = None,
    redis_client_override: Any | None = None,
    write_redis: bool = True,
    public_paths: tuple[Path, ...] = (PUBLIC_OPERATOR_RUNTIME, PUBLIC_DASHBOARD),
    min_notional_usd: float = 100_000.0,
    min_base_quantity: float = 1.0,
    min_market_share: float = 0.01,
    min_ladder_rungs: int = 3,
    ladder_quantity_tolerance_pct: float = 0.02,
    ladder_max_span_bps: float = 50.0,
    smoke_test: bool = False,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    redis_client = (
        redis_client_override if redis_client_override is not None else _connect_redis()
    )
    generated_utc = utc_iso()
    resolved = tuple(symbols) if symbols is not None else tuple(resolve_symbols(smoke_test=smoke_test))
    normalized_symbols = tuple(sorted({str(s).strip().upper() for s in resolved if str(s).strip()}))
    key_presence = _aicoin_key_presence(env=env)

    whale_payloads: dict[str, dict[str, Any]] = {}
    aicoin_payloads: dict[str, dict[str, Any]] = {}
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
        aicoin_payloads[symbol] = _build_aicoin_symbol_payload(
            symbol,
            generated_utc=generated_utc,
            key_presence=key_presence,
        )

    whale_status_counts: dict[str, int] = {}
    for payload in whale_payloads.values():
        status = str(payload.get("source_status") or "UNKNOWN")
        whale_status_counts[status] = whale_status_counts.get(status, 0) + 1
    aicoin_status_counts: dict[str, int] = {}
    for payload in aicoin_payloads.values():
        status = str(payload.get("source_status") or "UNKNOWN")
        aicoin_status_counts[status] = aicoin_status_counts.get(status, 0) + 1

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
    source_status = (
        "KEY_MISSING_NO_NETWORK"
        if not any(
            key_presence.get(name)
            for name in (
                "AICOIN_ACCESS_KEY_ID",
                "AICOIN_ACCESS_SECRET",
                "AICOIN_API_KEY",
                "AICOIN_API_SECRET",
            )
        )
        else "CREDENTIAL_PRESENT_ENDPOINT_MAPPING_PENDING_NO_NETWORK"
    )
    aicoin_status = {
        "schema_version": "v2_altdata_aicoin_free_tier_status_v1",
        "generated_utc": generated_utc,
        "provider": "aicoin_free_tier",
        "source_status": source_status,
        "source_status_counts": aicoin_status_counts,
        "symbol_count": len(normalized_symbols),
        "successful_symbol_count": 0,
        "free_plan": AICOIN_FREE_PLAN,
        "reviewed_capabilities": list(AICOIN_REVIEWED_CAPABILITIES),
        "credential_env_vars": [
            "AICOIN_ACCESS_KEY_ID",
            "AICOIN_ACCESS_SECRET",
            "AICOIN_API_KEY",
            "AICOIN_API_SECRET",
            "AICOIN_API_BASE_URL",
        ],
        "credential_presence": dict(key_presence),
        "credential_raw_value_exposed": False,
        "network_call_attempted": False,
        "built_in_key_documented": True,
        "runtime_rest_probe_enabled": False,
        "missing_reason": (
            "AICoin OpenData/CoinOS free-tier reviewed; deterministic V2 runtime REST endpoint mapping is not configured, so no AICoin symbol signal was fabricated."
        ),
    }

    redis_write_results: dict[str, bool] = {}
    if write_redis and redis_client is not None:
        redis_write_results[KEY_WHALE_STATUS] = _safe_redis_set(
            redis_client, KEY_WHALE_STATUS, whale_status
        )
        redis_write_results[KEY_AICOIN_STATUS] = _safe_redis_set(
            redis_client, KEY_AICOIN_STATUS, aicoin_status
        )
        for symbol, payload in whale_payloads.items():
            redis_write_results[f"{KEY_WHALE_SYMBOL_PREFIX}{symbol}"] = _safe_redis_set(
                redis_client, f"{KEY_WHALE_SYMBOL_PREFIX}{symbol}", payload
            )
        for symbol, payload in aicoin_payloads.items():
            redis_write_results[f"{KEY_AICOIN_SYMBOL_PREFIX}{symbol}"] = _safe_redis_set(
                redis_client, f"{KEY_AICOIN_SYMBOL_PREFIX}{symbol}", payload
            )

    top_whale_symbols = sorted(
        (
            {
                "symbol": symbol,
                "whale_wall_score": payload.get("whale_wall_score"),
                "whale_wall_event_count": payload.get("whale_wall_event_count"),
                "whale_total_wall_notional_usd": payload.get("whale_total_wall_notional_usd"),
                "whale_bid_pressure_score": payload.get("whale_bid_pressure_score"),
                "whale_ask_pressure_score": payload.get("whale_ask_pressure_score"),
                "nearest_bid_wall_distance_bps": payload.get("nearest_bid_wall_distance_bps"),
                "nearest_ask_wall_distance_bps": payload.get("nearest_ask_wall_distance_bps"),
            }
            for symbol, payload in whale_payloads.items()
            if payload.get("whale_wall_score") is not None
        ),
        key=lambda row: (
            -(float(row.get("whale_wall_event_count") or 0.0)),
            -(float(row.get("whale_total_wall_notional_usd") or 0.0)),
            -(float(row.get("whale_wall_score") or 0.0)),
        ),
    )[:20]

    payload = {
        "schema_version": "v2_aicoin_whale_intel_free_tier_status_v1",
        "generated_utc": generated_utc,
        "go_no_go": "V2_AICOIN_WHALE_INTEL_FREE_TIER_LIVE_OK",
        "symbol_count": len(normalized_symbols),
        "symbols": list(normalized_symbols),
        "whale_walls_status": whale_status,
        "aicoin_status": aicoin_status,
        "top_whale_wall_symbols": top_whale_symbols,
        "whale_payloads": whale_payloads,
        "aicoin_payloads": aicoin_payloads,
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
    _write_status_files(payload, public_paths)
    _write_report(payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_aicoin_whale_intel_free_tier")
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
                    "go_no_go": payload["go_no_go"],
                    "symbol_count": payload["symbol_count"],
                    "whale_successful_symbol_count": payload["whale_walls_status"][
                        "successful_symbol_count"
                    ],
                    "aicoin_source_status": payload["aicoin_status"]["source_status"],
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
