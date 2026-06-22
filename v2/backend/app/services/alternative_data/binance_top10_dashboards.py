"""V2 Top-10 Binance market dashboards (paper/shadow only).

Six dashboards derived from public Binance ticker endpoints:

1. Binance Spot 12h Volume Leaders          (spot_volume_12h)
2. Binance Futures 12h Volume Leaders       (futures_volume_12h)
3. Binance Spot 12h Most Traded             (spot_trades_12h)
4. Binance Futures 12h Most Traded          (futures_trades_12h)
5. Binance Spot 12h Volatility Leaders      (spot_volatility_12h)
6. Binance Futures 12h Volatility Leaders   (futures_volatility_12h)

Metrics:
- volume       -> quoteVolume
- most traded  -> count (trade count over the rolling window)
- volatility   -> abs(priceChangePercent)

Notes on rolling-window asymmetry between Spot and Futures:

- Binance Spot supports an explicit rolling windowSize query
  parameter on the public ticker endpoint, so the spot dashboards
  use a true 12h rolling window.
- Binance Futures only exposes a 24h rolling ticker on its public
  endpoint. The futures dashboards consume that 24h ticker and
  surface the actual window in the payload via
  window_size_requested / window_size_actual fields. No
  per-symbol kline aggregation is performed in this packet.

Allowed V2 Redis writes are constrained at the safe-set boundary to:

- v2:dashboards:binance_top10:spot_volume_12h
- v2:dashboards:binance_top10:futures_volume_12h
- v2:dashboards:binance_top10:spot_trades_12h
- v2:dashboards:binance_top10:futures_trades_12h
- v2:dashboards:binance_top10:spot_volatility_12h
- v2:dashboards:binance_top10:futures_volatility_12h
- v2:dashboards:binance_top10:heartbeat

This module NEVER places, cancels, or modifies any exchange entry.
NEVER changes leverage or margin. NEVER writes old Redis keys. NEVER
calls authenticated endpoints. NEVER imports torch. NEVER
deserializes pickle.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

V2_REDIS_PREFIX = "v2:"
DASHBOARD_KEY_PREFIX = "v2:dashboards:binance_top10:"

KEY_SPOT_VOLUME = "v2:dashboards:binance_top10:spot_volume_12h"
KEY_FUTURES_VOLUME = "v2:dashboards:binance_top10:futures_volume_12h"
KEY_SPOT_TRADES = "v2:dashboards:binance_top10:spot_trades_12h"
KEY_FUTURES_TRADES = "v2:dashboards:binance_top10:futures_trades_12h"
KEY_SPOT_VOLATILITY = "v2:dashboards:binance_top10:spot_volatility_12h"
KEY_FUTURES_VOLATILITY = "v2:dashboards:binance_top10:futures_volatility_12h"
KEY_HEARTBEAT = "v2:dashboards:binance_top10:heartbeat"

ALLOWED_KEYS = frozenset(
    {
        KEY_SPOT_VOLUME,
        KEY_FUTURES_VOLUME,
        KEY_SPOT_TRADES,
        KEY_FUTURES_TRADES,
        KEY_SPOT_VOLATILITY,
        KEY_FUTURES_VOLATILITY,
        KEY_HEARTBEAT,
    }
)

SPOT_ROLLING_TICKER_URL = "https://api.binance.com/api/v3/ticker?windowSize=12h"
FUTURES_24H_TICKER_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"

DEFAULT_HTTP_TIMEOUT_SECONDS = 10
DEFAULT_REDIS_DASHBOARD_TTL_SECONDS = 900
DEFAULT_REDIS_HEARTBEAT_TTL_SECONDS = 180
DEFAULT_TOP_N = 10
DEFAULT_QUOTE_FILTER = "USDT"


def _utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def _coerce_int(value: Any) -> int | None:
    f = _coerce_float(value)
    if f is None:
        return None
    try:
        return int(f)
    except (TypeError, ValueError):
        return None


def _safe_redis_set(redis_client: Any, key: str, value: str, ex: int | None) -> bool:
    if redis_client is None:
        return False
    if not isinstance(key, str):
        return False
    if key not in ALLOWED_KEYS:
        return False
    if not key.startswith(V2_REDIS_PREFIX):
        return False
    try:
        if ex is not None:
            redis_client.set(key, value, ex=int(ex))
        else:
            redis_client.set(key, value)
        return True
    except Exception:
        return False


@dataclass(frozen=True)
class DashboardRow:
    rank: int
    symbol: str
    quote_volume: float | None
    trade_count: int | None
    price_change_percent: float | None
    last_price: float | None

    def as_payload(self) -> dict[str, Any]:
        return {
            "rank": int(self.rank),
            "symbol": self.symbol,
            "quote_volume": self.quote_volume,
            "trade_count": self.trade_count,
            "price_change_percent": self.price_change_percent,
            "last_price": self.last_price,
        }


def filter_symbols(rows: Sequence[dict[str, Any]], quote_filter: str | None) -> list[dict[str, Any]]:
    if not quote_filter:
        return [r for r in rows if isinstance(r, dict) and isinstance(r.get("symbol"), str)]
    return [
        r
        for r in rows
        if isinstance(r, dict)
        and isinstance(r.get("symbol"), str)
        and r["symbol"].upper().endswith(quote_filter.upper())
    ]


def rank_top_n(
    rows: Sequence[dict[str, Any]],
    *,
    metric_field: str,
    metric_transform: Callable[[Any], float | None] = _coerce_float,
    top_n: int = DEFAULT_TOP_N,
) -> list[DashboardRow]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        score = metric_transform(row.get(metric_field))
        if score is None:
            continue
        scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    out: list[DashboardRow] = []
    for rank, (score, row) in enumerate(scored[:top_n], start=1):
        out.append(
            DashboardRow(
                rank=rank,
                symbol=str(row.get("symbol")).upper(),
                quote_volume=_coerce_float(row.get("quoteVolume")),
                trade_count=_coerce_int(row.get("count")),
                price_change_percent=_coerce_float(row.get("priceChangePercent")),
                last_price=_coerce_float(row.get("lastPrice")),
            )
        )
    return out


def _abs_price_change(value: Any) -> float | None:
    raw = _coerce_float(value)
    if raw is None:
        return None
    return abs(raw)


def build_dashboard_payload(
    *,
    dashboard_id: str,
    redis_key: str,
    title: str,
    venue: str,
    metric: str,
    window_size_requested: str,
    window_size_actual: str,
    source_endpoint: str,
    rows: Sequence[DashboardRow],
    source_status: str,
    generated_utc: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "v2_binance_top10_dashboard_v1",
        "generated_utc": generated_utc or _utc_iso(),
        "dashboard_id": dashboard_id,
        "redis_key": redis_key,
        "title": title,
        "venue": venue,
        "metric": metric,
        "window_size_requested": window_size_requested,
        "window_size_actual": window_size_actual,
        "source_endpoint": source_endpoint,
        "source_status": source_status,
        "rank_count": len(rows),
        "rows": [r.as_payload() for r in rows],
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "credential_in_payload": "NEVER",
        "gate": "blocked_human_only",
        "symbols_real": [],
        "approves_real": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def write_dashboard_payload(redis_client: Any, key: str, payload: dict[str, Any]) -> bool:
    return _safe_redis_set(
        redis_client,
        key,
        json.dumps(payload, sort_keys=True),
        ex=DEFAULT_REDIS_DASHBOARD_TTL_SECONDS,
    )


def build_heartbeat_payload(
    *,
    spot_source_status: str,
    futures_source_status: str,
    dashboards: dict[str, dict[str, Any]],
    generated_utc: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "v2_binance_top10_heartbeat_v1",
        "generated_utc": generated_utc or _utc_iso(),
        "heartbeat_at": generated_utc or _utc_iso(),
        "spot_source_status": spot_source_status,
        "futures_source_status": futures_source_status,
        "dashboards_published": list(dashboards.keys()),
        "dashboards_count": len(dashboards),
        "writes_legacy_redis": False,
        "writes_exchange_orders": False,
        "no_synthetic_market_data": True,
        "no_torch_imported": True,
        "no_pickle_loaded": True,
        "no_legacy_filesystem_modified": True,
        "credential_in_payload": "NEVER",
        "auth_required_for_source_endpoints": False,
        "gate": "blocked_human_only",
        "symbols_real": [],
        "approves_real": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def write_heartbeat_payload(redis_client: Any, payload: dict[str, Any]) -> bool:
    return _safe_redis_set(
        redis_client,
        KEY_HEARTBEAT,
        json.dumps(payload, sort_keys=True),
        ex=DEFAULT_REDIS_HEARTBEAT_TTL_SECONDS,
    )


def _default_http_get(
    url: str, headers: dict[str, str], timeout: float
) -> tuple[int, Any]:  # pragma: no cover - real HTTP not exercised in tests
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", resp.getcode() or 0))
            try:
                body = json.loads(resp.read().decode("utf-8"))
            except (ValueError, TypeError):
                body = None
            return status, body
    except urllib.error.HTTPError as e:
        return int(e.code), None
    except TimeoutError:
        raise
    except Exception:
        raise


def fetch_ticker(
    url: str,
    *,
    http_get: Callable[[str, dict[str, str], float], tuple[int, Any]] | None = None,
    timeout: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
) -> tuple[str, list[dict[str, Any]]]:
    """Fetch a public Binance ticker endpoint.

    Returns a tuple (source_status, rows). source_status is one of:
      - API_OK
      - API_RATE_LIMITED_429
      - API_FORBIDDEN_403
      - API_NETWORK_ERROR
      - API_TIMEOUT
      - API_PARSE_ERROR
    """
    fn = http_get or _default_http_get
    try:
        status_code, body = fn(url, {}, timeout)
    except TimeoutError:
        return "API_TIMEOUT", []
    except Exception:
        return "API_NETWORK_ERROR", []
    if status_code == 200:
        if isinstance(body, list):
            return "API_OK", body
        if isinstance(body, dict):
            return "API_OK", [body]
        return "API_PARSE_ERROR", []
    if status_code == 429:
        return "API_RATE_LIMITED_429", []
    if status_code == 403:
        return "API_FORBIDDEN_403", []
    return "API_NETWORK_ERROR", []


def build_dashboards(
    *,
    spot_rows: Sequence[dict[str, Any]],
    futures_rows: Sequence[dict[str, Any]],
    spot_source_status: str,
    futures_source_status: str,
    quote_filter: str | None = DEFAULT_QUOTE_FILTER,
    top_n: int = DEFAULT_TOP_N,
    generated_utc: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Build all six dashboard payloads from already-fetched ticker rows.

    Returns a dict keyed by dashboard_id with the full payload as the
    value. Callers can write each one to its respective Redis key.
    """
    now = generated_utc or _utc_iso()
    spot = filter_symbols(spot_rows, quote_filter)
    futures = filter_symbols(futures_rows, quote_filter)

    dashboards: dict[str, dict[str, Any]] = {}
    dashboards["spot_volume_12h"] = build_dashboard_payload(
        dashboard_id="spot_volume_12h",
        redis_key=KEY_SPOT_VOLUME,
        title="Binance Spot 12h Volume Leaders",
        venue="spot",
        metric="quoteVolume",
        window_size_requested="12h",
        window_size_actual="12h",
        source_endpoint=SPOT_ROLLING_TICKER_URL,
        rows=rank_top_n(spot, metric_field="quoteVolume", top_n=top_n),
        source_status=spot_source_status,
        generated_utc=now,
    )
    dashboards["spot_trades_12h"] = build_dashboard_payload(
        dashboard_id="spot_trades_12h",
        redis_key=KEY_SPOT_TRADES,
        title="Binance Spot 12h Most Traded",
        venue="spot",
        metric="count",
        window_size_requested="12h",
        window_size_actual="12h",
        source_endpoint=SPOT_ROLLING_TICKER_URL,
        rows=rank_top_n(
            spot, metric_field="count", metric_transform=_coerce_float, top_n=top_n
        ),
        source_status=spot_source_status,
        generated_utc=now,
    )
    dashboards["spot_volatility_12h"] = build_dashboard_payload(
        dashboard_id="spot_volatility_12h",
        redis_key=KEY_SPOT_VOLATILITY,
        title="Binance Spot 12h Volatility Leaders",
        venue="spot",
        metric="abs(priceChangePercent)",
        window_size_requested="12h",
        window_size_actual="12h",
        source_endpoint=SPOT_ROLLING_TICKER_URL,
        rows=rank_top_n(
            spot,
            metric_field="priceChangePercent",
            metric_transform=_abs_price_change,
            top_n=top_n,
        ),
        source_status=spot_source_status,
        generated_utc=now,
    )
    dashboards["futures_volume_12h"] = build_dashboard_payload(
        dashboard_id="futures_volume_12h",
        redis_key=KEY_FUTURES_VOLUME,
        title="Binance Futures 12h Volume Leaders",
        venue="futures",
        metric="quoteVolume",
        window_size_requested="12h",
        window_size_actual="24h",
        source_endpoint=FUTURES_24H_TICKER_URL,
        rows=rank_top_n(futures, metric_field="quoteVolume", top_n=top_n),
        source_status=futures_source_status,
        generated_utc=now,
    )
    dashboards["futures_trades_12h"] = build_dashboard_payload(
        dashboard_id="futures_trades_12h",
        redis_key=KEY_FUTURES_TRADES,
        title="Binance Futures 12h Most Traded",
        venue="futures",
        metric="count",
        window_size_requested="12h",
        window_size_actual="24h",
        source_endpoint=FUTURES_24H_TICKER_URL,
        rows=rank_top_n(
            futures, metric_field="count", metric_transform=_coerce_float, top_n=top_n
        ),
        source_status=futures_source_status,
        generated_utc=now,
    )
    dashboards["futures_volatility_12h"] = build_dashboard_payload(
        dashboard_id="futures_volatility_12h",
        redis_key=KEY_FUTURES_VOLATILITY,
        title="Binance Futures 12h Volatility Leaders",
        venue="futures",
        metric="abs(priceChangePercent)",
        window_size_requested="12h",
        window_size_actual="24h",
        source_endpoint=FUTURES_24H_TICKER_URL,
        rows=rank_top_n(
            futures,
            metric_field="priceChangePercent",
            metric_transform=_abs_price_change,
            top_n=top_n,
        ),
        source_status=futures_source_status,
        generated_utc=now,
    )
    return dashboards


def publish_dashboards(
    redis_client: Any,
    dashboards: dict[str, dict[str, Any]],
) -> dict[str, bool]:
    """Write each dashboard payload to its Redis key. Returns a per-key
    result map so callers can detect partial-failure conditions.
    """
    result: dict[str, bool] = {}
    for payload in dashboards.values():
        key = payload.get("redis_key")
        if not isinstance(key, str):
            continue
        result[key] = write_dashboard_payload(redis_client, key, payload)
    return result
