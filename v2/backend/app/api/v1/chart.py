"""Chart overlay endpoint — serves CoinAnk sub-panel data for ProChart.

All data is read-only from Redis keys populated by the CoinAnk ingestor.
No exchange calls, no order submission, no live-gate mutation.
"""

from __future__ import annotations

import json
import os
import pathlib
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Query

router = APIRouter(prefix="/chart", tags=["chart"])

_SOURCE_PENDING = "SOURCE_PENDING"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _iso_from_seconds(value: int | float | None) -> str | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), UTC).isoformat().replace("+00:00", "Z")
    except (OSError, TypeError, ValueError):
        return None


def _lag_ms(timestamp: str | None) -> int | None:
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((datetime.now(UTC) - parsed).total_seconds() * 1000))


def _latest_series_timestamp_seconds(*series: list[dict[str, float]]) -> int | None:
    values: list[int] = []
    for rows in series:
        for row in rows:
            try:
                values.append(int(row["time"]))
            except (KeyError, TypeError, ValueError):
                continue
    return max(values) if values else None


def _frontend_public_root() -> pathlib.Path:
    repo_root = pathlib.Path(os.environ.get("V2_REPO_ROOT", "/home/wali/Desktop/AI BOT REBUILD"))
    nested = repo_root / "v2" / "frontend" / "public"
    if nested.exists():
        return nested
    return repo_root / "frontend" / "public"


def _get_redis_client():  # type: ignore[return]
    try:
        import redis as _redis
        return _redis.from_url(
            os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    except Exception:
        return None


def _read_coinank_key(r: Any, key_pattern: str) -> Any:
    if r is None:
        return None
    try:
        # Bounded cursor SCAN, never blocking KEYS: this helper is called up to
        # 11x per chart page load against a ~726K-key single-threaded Redis.
        keys: list[str] = []
        cursor = 0
        while True:
            cursor, batch = r.scan(cursor=cursor, match=key_pattern, count=500)
            keys.extend(batch)
            if cursor == 0 or len(keys) > 2000:
                break
        if not keys:
            return None
        raw = r.get(sorted(keys)[-1])
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _normalize_kline(raw: Any) -> list[dict[str, float]]:
    """Convert CoinAnk kline format to [{time: unix_seconds, value: float}]."""
    if not raw:
        return []
    if isinstance(raw, dict):
        raw = raw.get("data") or raw.get("list") or raw.get("klineList") or []
    if not isinstance(raw, list):
        return []
    out = []
    for row in raw:
        if isinstance(row, (list, tuple)) and len(row) >= 5:
            try:
                out.append({"time": int(row[0]) // 1000, "value": float(row[4])})
            except (TypeError, ValueError):
                pass
        elif isinstance(row, dict):
            ts = row.get("time") or row.get("t") or row.get("timestamp")
            val = row.get("value") or row.get("close") or row.get("c") or row.get("v")
            if ts is not None and val is not None:
                try:
                    ts_s = int(ts) // 1000 if int(ts) > 1_000_000_000_000 else int(ts)
                    out.append({"time": ts_s, "value": float(val)})
                except (TypeError, ValueError):
                    pass
    return sorted(out, key=lambda x: x["time"])


def _safe_float(d: Any, *keys: str) -> float | None:
    for k in keys:
        try:
            v = (d or {}).get(k)
            if v is not None:
                return float(v)
        except (TypeError, ValueError):
            pass
    return None


@router.get("/coinank/{symbol}/{timeframe}")
async def get_coinank_overlay(
    symbol: str,
    timeframe: str,
    exchange: str = Query(default="Binance"),
) -> dict[str, Any]:
    """Return CoinAnk overlay data (OI, Long/Short, Funding, CVD) for ProChart sub-panels.

    Reads from Redis keys written by the CoinAnk ingestor (live_coinank.py).
    Returns empty arrays when data is unavailable — never raises 4xx/5xx.
    """
    r = _get_redis_client()
    sym_lower = symbol.lower()
    base_coin = symbol.replace("USDT", "").replace("PERP", "").lower()
    exch_lower = exchange.lower()

    oi_kline = _normalize_kline(
        _read_coinank_key(r, f"v2:coinank:openInterest_kline:*{exch_lower}*{sym_lower}*{timeframe}*")
        or _read_coinank_key(r, f"v2:coinank:openInterest_kline:*{sym_lower}*{timeframe}*"),
    )
    net_long = _normalize_kline(
        _read_coinank_key(r, f"v2:coinank:netPositions_getNetPositions:*{exch_lower}*{sym_lower}*{timeframe}*")
    )
    funding_kline = _normalize_kline(
        _read_coinank_key(r, f"v2:coinank:fundingRate_kline:*{exch_lower}*{sym_lower}*{timeframe}*")
    )
    ls_kline = _normalize_kline(
        _read_coinank_key(r, f"v2:coinank:ls_kline:*{exch_lower}*{sym_lower}*{timeframe}*")
    )
    cvd = _normalize_kline(
        _read_coinank_key(r, f"v2:coinank:marketOrder_getCvd:*{exch_lower}*{sym_lower}*{timeframe}*")
    )

    market_cap_raw = _read_coinank_key(r, f"v2:coinank:instruments_getCoinMarketCap:*{base_coin}*")
    oi_all_raw     = _read_coinank_key(r, f"v2:coinank:openInterest_all:*{sym_lower}*")
    ls_rt_raw      = _read_coinank_key(r, f"v2:coinank:ls_exchange_realtimeAll:*{base_coin}*")
    fund_cur_raw   = _read_coinank_key(r, "v2:coinank:fundingRate_current:*")

    fear_greed: float | None = None
    if r is not None:
        try:
            fg_raw = r.get("features:global_coinank:fear_greed:latest")
            if fg_raw:
                fear_greed = float(json.loads(fg_raw).get("value", 0) or 0)
        except Exception:
            pass

    latest_timestamp = _iso_from_seconds(
        _latest_series_timestamp_seconds(oi_kline, net_long, funding_kline, ls_kline, cvd)
    )
    lag = _lag_ms(latest_timestamp)
    missing_fields = [
        name
        for name, missing in (
            ("oi_kline", not oi_kline),
            ("net_long", not net_long),
            ("funding_kline", not funding_kline),
            ("ls_kline", not ls_kline),
            ("cvd", not cvd),
            ("market_cap", _safe_float(market_cap_raw, "marketCap", "market_cap") is None),
            ("total_oi", _safe_float(oi_all_raw, "openInterest", "oi", "total") is None),
            ("ls_ratio", _safe_float(ls_rt_raw, "ratio", "longShortRatio") is None),
            ("funding_rate", _safe_float(fund_cur_raw, "fundingRate", "rate") is None),
        )
        if missing
    ]
    stale = r is None or latest_timestamp is None or lag is None or lag > 30 * 60 * 1000
    warnings = []
    if r is None:
        warnings.append("CoinAnk overlay source unavailable")
    if stale:
        warnings.append("Overlay data is stale or unavailable")

    return {
        "symbol":    symbol,
        "timeframe": timeframe,
        "exchange":  exchange,
        "status":    "ok" if r is not None else _SOURCE_PENDING,
        "source": "redis_coinank_overlay" if r is not None else "unavailable",
        "source_type": "repository" if r is not None else "unavailable",
        "endpoint": f"/api/v1/chart/coinank/{symbol}/{timeframe}",
        "timestamp": latest_timestamp,
        "received_at": _now(),
        "lag_ms": lag,
        "stale": stale,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "mode": "read_only",
        "live_trading_enabled": False,
        "exchange_mutation_enabled": False,
        "oi_kline":      oi_kline,
        "net_long":      net_long,
        "funding_kline": funding_kline,
        "ls_kline":      ls_kline,
        "cvd":           cvd,
        "stats": {
            "market_cap":   _safe_float(market_cap_raw, "marketCap", "market_cap"),
            "total_oi":     _safe_float(oi_all_raw,     "openInterest", "oi", "total"),
            "ls_ratio":     _safe_float(ls_rt_raw,      "ratio", "longShortRatio"),
            "funding_rate": _safe_float(fund_cur_raw,   "fundingRate", "rate"),
            "fear_greed":   fear_greed,
        },
    }


@router.get("/symbols")
async def get_chart_symbols() -> dict[str, Any]:
    """Return available symbols with latest price for the ProChart watchlist.

    Reads from the chart manifest payload file served by the existing
    chart worker — no Redis or exchange calls needed.
    """
    manifest_path = (
        _frontend_public_root()
        / "operator_runtime"
        / "v2_professional_market_chart"
        / "latest"
        / "operator_dashboard_payload.json"
    )
    try:
        manifest: dict[str, Any] = json.loads(manifest_path.read_text())
        rows = []
        for row in (manifest.get("payloads") or {}).values():
            if row.get("symbol") and row.get("timeframe") == "5m":
                rows.append({
                    "symbol":       row.get("symbol"),
                    "price":        row.get("latest_close") or row.get("latest_mid_px"),
                    "signal":       row.get("signal_action"),
                    "source_age_s": row.get("source_event_age_seconds"),
                })
        age_values = [
            float(row["source_age_s"])
            for row in rows
            if isinstance(row.get("source_age_s"), (int, float)) and row.get("source_age_s") is not None
        ]
        file_timestamp = datetime.fromtimestamp(manifest_path.stat().st_mtime, UTC).isoformat().replace("+00:00", "Z")
        stale = not rows or not age_values or max(age_values) > 120
        warnings = [] if not stale else ["Chart symbol manifest is stale or missing source ages"]
        return {
            "symbols": rows,
            "count": len(rows),
            "status": "ok",
            "source": "professional_market_chart_manifest",
            "source_type": "static_payload",
            "endpoint": "/api/v1/chart/symbols",
            "timestamp": file_timestamp,
            "received_at": _now(),
            "lag_ms": _lag_ms(file_timestamp),
            "stale": stale,
            "missing_fields": [] if rows else ["symbols"],
            "warnings": warnings,
            "mode": "read_only",
            "live_trading_enabled": False,
            "exchange_mutation_enabled": False,
        }
    except FileNotFoundError:
        return {
            "symbols": [],
            "count": 0,
            "status": _SOURCE_PENDING,
            "reason": "manifest not found",
            "source": "unavailable",
            "source_type": "unavailable",
            "endpoint": "/api/v1/chart/symbols",
            "timestamp": None,
            "received_at": _now(),
            "lag_ms": None,
            "stale": True,
            "missing_fields": ["symbols", "manifest"],
            "warnings": ["Chart symbol manifest is unavailable"],
            "mode": "read_only",
            "live_trading_enabled": False,
            "exchange_mutation_enabled": False,
        }
    except Exception as exc:
        return {
            "symbols": [],
            "count": 0,
            "status": _SOURCE_PENDING,
            "reason": str(exc),
            "source": "unavailable",
            "source_type": "unavailable",
            "endpoint": "/api/v1/chart/symbols",
            "timestamp": None,
            "received_at": _now(),
            "lag_ms": None,
            "stale": True,
            "missing_fields": ["symbols"],
            "warnings": ["Chart symbol manifest could not be read"],
            "mode": "read_only",
            "live_trading_enabled": False,
            "exchange_mutation_enabled": False,
        }
