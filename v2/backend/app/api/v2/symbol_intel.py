"""Consolidated per-symbol market intelligence (read-only).

One endpoint that surfaces every rich per-symbol V2 Redis surface the
ingestors already produce, so the market detail page can display all of it:

- microstructure trust (feed quality, cross-venue, trade tape, adversarial)
- alt-data scores + whale walls + public intel
- higher-timeframe context and regime gates (15m/1h/4h)
- liquidation levels per timeframe
- cross-venue KuCoin vs Binance comparison
- orderbook features
- opportunity state

Streamable in realtime via /api/v2/ws/resource?path=/api/v2/market/{symbol}/intel.
Never writes to Redis; never touches the legacy bot.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from app.api.v2._common import get_redis

router = APIRouter(tags=["v2-symbol-intel"])

_SYMBOL_RE = re.compile(r"^[A-Z0-9]{5,20}$")
_TIMEFRAMES = ("15m", "1h", "4h")


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _get_json(r: Any, key: str) -> Any:
    try:
        raw = r.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed not in ({}, []) else None


def _age_seconds(payload: Any) -> float | None:
    """Newest event age from ISO or epoch fields commonly used by V2 writers."""
    if not isinstance(payload, dict):
        return None
    now = datetime.now(UTC)
    best: float | None = None
    for key in ("generated_at", "generated_utc", "fetched_utc", "available_at", "decision_time", "updated_at", "as_of"):
        value = payload.get(key)
        if isinstance(value, str) and len(value) >= 19:
            try:
                stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            age = (now - stamp).total_seconds()
            if best is None or age < best:
                best = age
    for key in ("time", "timestamp", "T", "E"):
        value = payload.get(key)
        if isinstance(value, (int, float)) and value > 0:
            seconds = value / 1000 if value > 10**12 else float(value)
            age = now.timestamp() - seconds
            if best is None or age < best:
                best = age
    return round(best, 1) if best is not None else None


def _section(payload: Any, source_key: str) -> dict[str, Any]:
    return {
        "data": payload,
        "source_key": source_key,
        "age_seconds": _age_seconds(payload),
        "present": payload is not None,
    }


@router.get("/market/{symbol}/intel")
async def get_symbol_intel(symbol: str) -> dict[str, Any]:
    safe = symbol.strip().upper()
    endpoint = f"/api/v2/market/{safe}/intel"
    now = _utc_now()
    base = {
        "source": "redis:v2 per-symbol intelligence surfaces",
        "source_type": "redis_live",
        "endpoint": endpoint,
        "timestamp": now,
        "received_at": now,
        "lag_ms": 0,
        "symbol": safe,
        "mode": "read_only",
    }
    if not _SYMBOL_RE.match(safe):
        return {
            **base,
            "data": None,
            "source_type": "unavailable",
            "stale": True,
            "missing_fields": ["symbol"],
            "warnings": [f"Invalid symbol '{symbol}'"],
        }
    r = get_redis()
    if r is None:
        return {
            **base,
            "data": None,
            "source_type": "unavailable",
            "stale": True,
            "missing_fields": ["redis"],
            "warnings": ["Redis unavailable"],
        }

    sections: dict[str, dict[str, Any]] = {
        "microstructure_feed_quality": _section(
            _get_json(r, f"v2:microstructure:feed_quality:binance:{safe}"),
            f"v2:microstructure:feed_quality:binance:{safe}",
        ),
        "microstructure_cross_venue": _section(
            _get_json(r, f"v2:microstructure:cross_venue_confirmation:{safe}"),
            f"v2:microstructure:cross_venue_confirmation:{safe}",
        ),
        "microstructure_trade_tape": _section(
            _get_json(r, f"v2:microstructure:trade_tape_confirmation:{safe}"),
            f"v2:microstructure:trade_tape_confirmation:{safe}",
        ),
        "microstructure_adversarial": _section(
            _get_json(r, f"v2:microstructure:adversarial_features:binance:{safe}"),
            f"v2:microstructure:adversarial_features:binance:{safe}",
        ),
        "altdata_symbol_score": _section(
            _get_json(r, f"v2:altdata:symbol_score:{safe}"),
            f"v2:altdata:symbol_score:{safe}",
        ),
        "whale_walls": _section(
            _get_json(r, f"v2:altdata:whale_walls:symbol:{safe}"),
            f"v2:altdata:whale_walls:symbol:{safe}",
        ),
        "public_intel": _section(
            _get_json(r, f"v2:altdata:public_intel:symbol:{safe}"),
            f"v2:altdata:public_intel:symbol:{safe}",
        ),
        "htf_context": _section(
            _get_json(r, f"v2:context:htf:{safe}"),
            f"v2:context:htf:{safe}",
        ),
        "opportunity": _section(
            _get_json(r, f"v2:opportunity:{safe}"),
            f"v2:opportunity:{safe}",
        ),
        "orderbook_features": _section(
            _get_json(r, f"v2:orderbook:features:binance:{safe}"),
            f"v2:orderbook:features:binance:{safe}",
        ),
        "kucoin_cross_venue": _section(
            _get_json(r, f"v2:market:kucoin:latest:{safe}"),
            f"v2:market:kucoin:latest:{safe}",
        ),
        "binance_prices": _section(
            _get_json(r, f"v2:market:prices:{safe}"),
            f"v2:market:prices:{safe}",
        ),
    }
    for timeframe in _TIMEFRAMES:
        sections[f"regime_gate_{timeframe}"] = _section(
            _get_json(r, f"v2:regime:gate:{safe}:{timeframe}"),
            f"v2:regime:gate:{safe}:{timeframe}",
        )
        sections[f"liquidation_levels_{timeframe}"] = _section(
            _get_json(r, f"v2:liquidations:levels:{safe}:{timeframe}"),
            f"v2:liquidations:levels:{safe}:{timeframe}",
        )

    missing = [name for name, section in sections.items() if not section["present"]]
    present_count = len(sections) - len(missing)
    return {
        **base,
        "data": {
            "symbol": safe,
            "sections": sections,
            "present_count": present_count,
            "section_count": len(sections),
        },
        "stale": present_count == 0,
        "missing_fields": missing,
        "warnings": [] if present_count else ["No per-symbol intelligence keys present in Redis for this symbol"],
    }
