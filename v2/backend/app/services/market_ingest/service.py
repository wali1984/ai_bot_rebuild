"""V2 market ingest service — legacy-baseline-anchored.

Ports the responsibilities of the legacy startup-baseline ingestors
(`live_binance.py`, `live_kucoin.py`, `live_coinapi_v1.py`,
`live_coinapi_wsds.py`, `realtime_price_provider.py`) into a single V2
service. See
``claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_market_ingestor_from_legacy_baseline_LEGACY_BASELINE_ANALYSIS.md``
for the SHA-cited mapping.

Hard rules:
  - NEVER writes any legacy Redis key. The V2 worker writes only V2-namespaced
    data-plane entries with the ``v2:market:`` prefix into an in-process dict
    that the CLI persists to a file.
  - NEVER calls any exchange mutating method (no order/cancel/leverage/margin).
  - Binance WebSocket/cache sources are primary. Binance public REST GETs are
    fallback-only behind BINANCE_REST_FALLBACK_ALLOWED. No API credentials.
  - Fail-closed on HTTP 5xx: while a backoff window is active, persistence is
    refused and ``rate_limit_state`` reflects the cause.
"""
from __future__ import annotations

import dataclasses
import enum
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from v2.backend.app.services.binance_unified_websocket_transport import (
    REST_FALLBACK_ENV,
    binance_rest_fallback_decision,
)

V2_KEY_PREFIX = "v2:market"


class PriceSourcePriority(enum.Enum):
    """Source priority preserved from
    legacy_preserved/startup_baseline/ingest/realtime_price_provider.py
    (class PriceSource, L99-106). The legacy file documents the failover
    order; the V2 service preserves this enum so the trainer/feature layer
    can read it identically.
    """

    COINAPI_WS = ("coinapi_ws", 1)
    BINANCE_WS = ("binance_ws", 2)
    BINANCE_REST = ("binance_rest", 3)
    CCXT_REST = ("ccxt_rest", 4)
    KUCOIN_REST = ("kucoin_rest", 5)
    REDIS_CACHE = ("redis_cache", 99)

    @property
    def label(self) -> str:
        return self.value[0]

    @property
    def priority(self) -> int:
        return self.value[1]


# Data-source routing table — mirrors the legacy startup script's data-source
# table. Each entry: data_type -> (primary, fallback).
DATA_SOURCE_PRIORITY: Dict[str, Tuple[str, Optional[str]]] = {
    "ohlcv": ("binance_wss_closed_kline_cache", "coinapi_v1_or_binance_rest_fallback"),
    "quote_bbo": ("binance_bookticker_wss_cache", "binance_bookticker_rest_fallback"),
    "microstructure": ("coinapi_ds", None),
    "funding_rate": ("binance_ws", None),
    "mark_price": ("binance_ws", None),
    "premium_index": ("binance_mark_price_wss_cache", "binance_premium_index_rest_fallback"),
    "open_interest": ("market_cache_or_provider_bridge", "binance_open_interest_rest_fallback"),
    "liquidations": ("binance_ws", None),
    "orderbook_depth": ("binance_depth_wss_cache", "binance_depth_rest_fallback"),
}


LEGACY_WS_RECONNECT_POLICY: Dict[str, Any] = {
    "legacy_function": "ws_connect_with_retry",
    "baseline_path": "v2/legacy_preserved/startup_baseline/ingest/live_binance.py",
    "backoff_start_seconds": 1.0,
    "backoff_multiplier": 1.8,
    "backoff_cap_seconds": 15.0,
    "max_retries": 8,
    "v2_market_ingestor_mode": "websocket_cache_primary_rest_fallback_only",
    "v2_owner": "separate_v2_ws_worker",
}

COINAPI_OHLCV_STALE_THRESHOLD_SEC = 120.0


# Rate-limit backoff knobs — preserved from
# legacy_preserved/startup_baseline/ingest/live_binance.py
# (rate-limit ban -1003 branch L2416-2435, geo-block 451 branch L2399-2410,
# outer fetch_loop except L2492-2511). The 5xx branch is intentionally
# **stricter** than legacy and is fail-closed.
RATE_LIMIT_BAN_START_SEC = 60
RATE_LIMIT_BAN_CAP_SEC = 300
GEO_BLOCK_START_SEC = 300
GEO_BLOCK_CAP_SEC = 1800
GEO_BLOCK_ESCALATION_AFTER_N = 3
GEO_BLOCK_ESCALATION_SEC = 3600
HTTP_5XX_START_SEC = 30
HTTP_5XX_CAP_SEC = 300


@dataclass
class IngestResult:
    """Result of a single ingest call.

    Returned to the CLI and embedded in the public status payload.
    """

    symbol: str
    timeframe: str
    klines_persisted: int = 0
    last_kline_ts: Optional[int] = None
    source: str = "unknown"
    rate_limit_state: str = "ok"
    v2_keys_written: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class HealthSnapshot:
    """Health snapshot exposed to the CLI for inclusion in public payload."""

    coinapi_v1_healthy: bool
    coinapi_v1_last_ts: Optional[float]
    binance_rest_healthy: bool
    consecutive_5xx: int
    consecutive_bans: int
    consecutive_geo_blocks: int
    backoff_until: float
    rate_limit_state: str

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


HttpGetCallable = Callable[[str], Tuple[int, Any]]


class MarketIngestService:
    """V2 market ingest service.

    All persistence is into the in-memory ``data_plane`` dict, keyed by
    V2-namespaced strings (``v2:market:*``). The CLI snapshots this dict to a
    JSON file. No legacy Redis key is ever written.
    """

    def __init__(
        self,
        *,
        http_get: Optional[HttpGetCallable] = None,
        clock: Optional[Callable[[], float]] = None,
        data_plane: Optional[Dict[str, Any]] = None,
        enable_kucoin: bool = False,
        coinapi_daily_budget: int = 10000,
        coinapi_v1_budget_pct: float = 0.30,
    ) -> None:
        self._http_get = http_get if http_get is not None else _default_http_get
        self._clock = clock if clock is not None else time.time
        self.data_plane: Dict[str, Any] = data_plane if data_plane is not None else {}
        self._enable_kucoin = enable_kucoin
        self._coinapi_daily_budget = coinapi_daily_budget
        self._coinapi_v1_budget_pct = coinapi_v1_budget_pct
        self._coinapi_v1_msgs_today = 0
        self._coinapi_v1_last_ts: Optional[float] = None
        self._consecutive_5xx = 0
        self._consecutive_bans = 0
        self._consecutive_geo_blocks = 0
        self._backoff_until = 0.0
        self._rate_limit_state = "ok"
        self._klines_persisted_total = 0
        self._last_kline_ts: Optional[int] = None

    # ------------------------------------------------------------------
    # public surface
    # ------------------------------------------------------------------

    @property
    def klines_persisted_total(self) -> int:
        return self._klines_persisted_total

    @property
    def last_kline_ts(self) -> Optional[int]:
        return self._last_kline_ts

    @property
    def rate_limit_state(self) -> str:
        return self._rate_limit_state

    @property
    def backoff_until(self) -> float:
        return self._backoff_until

    def ingest_klines(
        self,
        symbol: str,
        timeframe: str = "1m",
        limit: int = 6,
    ) -> IngestResult:
        """Ingest OHLCV klines using the data-source priority table.

        Binance WSS closed-candle cache is primary. CoinAPI V1 is a non-Binance
        backup, and Binance REST is fallback-only behind the explicit fallback
        flag. Fail-closed on 5xx and during rate-limit backoff windows.
        """
        result = IngestResult(symbol=symbol, timeframe=timeframe)
        now = self._clock()
        if now < self._backoff_until:
            result.rate_limit_state = self._rate_limit_state
            result.errors.append(
                f"backoff_active until {self._backoff_until} ({self._rate_limit_state})"
            )
            return result

        cached_bars = self._wss_cached_klines(symbol, timeframe, limit)
        if cached_bars:
            source = "binance_wss_closed_kline_cache"
            bars = cached_bars
        else:
            bars = None
            source = "coinapi_v1"

        # CoinAPI remains a non-Binance backup. Binance REST is only used as an
        # explicit fallback when the cache and CoinAPI are unavailable.
        if bars is None:
            # Cold start must still attempt CoinAPI first; health only records
            # whether the prior CoinAPI sample was fresh enough.
            bars = self._coinapi_v1_klines(symbol, timeframe, limit)
        if bars is None:
            result.errors.append("coinapi_v1_unavailable_fallback_binance_rest")
            source = "binance_rest_fallback"
            bars = self._binance_rest_klines(symbol, timeframe, limit, result)

        if bars is None:
            result.source = source
            result.rate_limit_state = self._rate_limit_state
            return result

        # Persist into V2 namespace (NEVER legacy Redis).
        bars_key = f"{V2_KEY_PREFIX}:{symbol}:ohlcv:{timeframe}"
        price_key = f"{V2_KEY_PREFIX}:{symbol}:price"
        self.data_plane[bars_key] = bars
        last_bar = bars[-1] if bars else None
        if last_bar is not None:
            close = last_bar.get("close")
            ts = int(last_bar.get("ts", 0))
            self.data_plane[price_key] = {
                "symbol": symbol,
                "price": float(close) if close is not None else None,
                "ts_ms": ts,
                "source": source,
            }
            self._last_kline_ts = ts
        result.klines_persisted = len(bars)
        result.last_kline_ts = self._last_kline_ts
        result.source = source
        self._rate_limit_state = "ok"
        result.rate_limit_state = self._rate_limit_state
        result.v2_keys_written = [bars_key, price_key]
        self._klines_persisted_total += len(bars)
        self._consecutive_5xx = 0
        return result

    def ingest_kucoin_quote(self, symbol: str) -> Dict[str, Any]:
        """Optional KuCoin public quote ingest path.

        Recognized but disabled by default. Mirrors legacy
        live_kucoin.py module flag ``KUCOIN_ENABLED`` (default 0).
        """
        result: Dict[str, Any] = {
            "symbol": symbol,
            "recognized": True,
            "enabled": self._enable_kucoin,
            "v2_key": f"{V2_KEY_PREFIX}:{symbol}:bbo",
            "status": "ok",
        }
        if not self._enable_kucoin:
            result["status"] = "skipped_disabled"
            return result
        status, payload = self._http_get(
            f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={_to_kucoin_symbol(symbol)}"
        )
        if not (200 <= status < 300) or not isinstance(payload, dict):
            result["status"] = "fetch_failed"
            result["http_status"] = status
            return result
        data = payload.get("data") or {}
        bbo = {
            "symbol": symbol,
            "bid": _safe_float(data.get("bestBid")),
            "ask": _safe_float(data.get("bestAsk")),
            "last": _safe_float(data.get("price")),
            "ts_ms": int(data.get("time") or 0),
            "source": "kucoin_rest",
        }
        self.data_plane[result["v2_key"]] = bbo
        return result

    def ingest_bbo(self, symbol: str) -> Dict[str, Any]:
        """Ingest public best bid/offer via Binance bookTicker fallback.

        Binance bookTicker/orderbook WebSocket cache is primary. REST is a
        fallback-only path and is blocked unless the explicit fallback flag is
        set.
        """
        result: Dict[str, Any] = {
            "symbol": symbol,
            "primary": "binance_bookticker_wss_cache",
            "source": "binance_bookticker_wss_cache",
            "v2_key": f"{V2_KEY_PREFIX}:{symbol}:bbo",
            "status": "pending",
            "coinapi_ds_mode": "secondary_microstructure_source",
        }
        cached = self._cached_bbo(symbol)
        if cached is not None:
            self.data_plane[result["v2_key"]] = cached
            result["status"] = "ok"
            result["persisted"] = True
            result["transport"] = "websocket_cache_primary"
            result["rest_fallback_used"] = False
            return result
        if self._blocked_by_backoff(result):
            return result
        if not self._rest_fallback_allowed_result(result, endpoint="/fapi/v1/ticker/bookTicker"):
            return result
        status, payload = self._http_get(
            f"https://fapi.binance.com/fapi/v1/ticker/bookTicker?symbol={symbol}"
        )
        if not self._public_http_ok(status, payload, result):
            return result
        if not isinstance(payload, dict):
            result["status"] = "unexpected_payload"
            return result
        self.data_plane[result["v2_key"]] = {
            "symbol": symbol,
            "bid": _safe_float(payload.get("bidPrice")),
            "ask": _safe_float(payload.get("askPrice")),
            "ts_ms": int(self._clock() * 1000),
            "source": "binance_public_rest_bookticker_fallback",
        }
        result["status"] = "ok"
        result["persisted"] = True
        result["rest_fallback_used"] = True
        return result

    def ingest_mark_premium_funding(self, symbol: str) -> Dict[str, Any]:
        """Ingest public Binance mark/funding data.

        Mark-price/funding WebSocket cache is primary. The premium-index REST
        endpoint is fallback-only.
        """
        mark_key = f"{V2_KEY_PREFIX}:{symbol}:mark"
        funding_key = f"{V2_KEY_PREFIX}:{symbol}:funding"
        result: Dict[str, Any] = {
            "symbol": symbol,
            "source": "binance_mark_price_wss_cache",
            "v2_keys": [mark_key, funding_key],
            "status": "pending",
        }
        cached = self._cached_mark_funding(symbol)
        if cached is not None:
            self.data_plane[mark_key] = cached["mark"]
            self.data_plane[funding_key] = cached["funding"]
            result["status"] = "ok"
            result["persisted"] = True
            result["transport"] = "websocket_cache_primary"
            result["rest_fallback_used"] = False
            return result
        if self._blocked_by_backoff(result):
            return result
        if not self._rest_fallback_allowed_result(result, endpoint="/fapi/v1/premiumIndex"):
            return result
        status, payload = self._http_get(
            f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={symbol}"
        )
        if not self._public_http_ok(status, payload, result):
            return result
        if not isinstance(payload, dict):
            result["status"] = "unexpected_payload"
            return result
        ts_ms = int(payload.get("time") or self._clock() * 1000)
        self.data_plane[mark_key] = {
            "symbol": symbol,
            "mark_price": _safe_float(payload.get("markPrice")),
            "index_price": _safe_float(payload.get("indexPrice")),
            "estimated_settle_price": _safe_float(payload.get("estimatedSettlePrice")),
            "ts_ms": ts_ms,
            "source": "binance_public_rest_premium_index_fallback",
        }
        self.data_plane[funding_key] = {
            "symbol": symbol,
            "funding_rate": _safe_float(payload.get("lastFundingRate")),
            "next_funding_time": int(payload.get("nextFundingTime") or 0),
            "interest_rate": _safe_float(payload.get("interestRate")),
            "ts_ms": ts_ms,
            "source": "binance_public_rest_premium_index_fallback",
        }
        result["status"] = "ok"
        result["persisted"] = True
        result["rest_fallback_used"] = True
        return result

    def ingest_oi(self, symbol: str) -> Dict[str, Any]:
        """Ingest public Binance open-interest data.

        Runtime cache/provider bridge is primary. Binance REST open-interest is
        fallback-only because this worker should not poll Binance REST during
        normal runtime.
        """
        key = f"{V2_KEY_PREFIX}:{symbol}:open_interest"
        result: Dict[str, Any] = {
            "symbol": symbol,
            "primary": "market_cache_or_provider_bridge",
            "fallback": "binance_open_interest_rest_fallback",
            "v2_key": key,
            "status": "pending",
        }
        cached = self._cached_open_interest(symbol)
        if cached is not None:
            self.data_plane[key] = cached
            result["status"] = "ok"
            result["persisted"] = True
            result["transport"] = "websocket_or_provider_cache_primary"
            result["rest_fallback_used"] = False
            return result
        if self._blocked_by_backoff(result):
            return result
        if not self._rest_fallback_allowed_result(result, endpoint="/fapi/v1/openInterest"):
            return result
        status, payload = self._http_get(
            f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}"
        )
        if not self._public_http_ok(status, payload, result):
            return result
        if not isinstance(payload, dict):
            result["status"] = "unexpected_payload"
            return result
        self.data_plane[key] = {
            "symbol": symbol,
            "open_interest": _safe_float(payload.get("openInterest")),
            "ts_ms": int(payload.get("time") or self._clock() * 1000),
            "source": "binance_public_rest_open_interest_fallback",
        }
        result["status"] = "ok"
        result["persisted"] = True
        result["rest_fallback_used"] = True
        return result

    def ingest_depth(self, symbol: str, limit: int = 20) -> Dict[str, Any]:
        """Ingest public Binance depth into the V2 data plane.

        Depth WebSocket cache is primary. REST depth snapshots are fallback-only.
        """
        key = f"{V2_KEY_PREFIX}:{symbol}:depth"
        result: Dict[str, Any] = {
            "symbol": symbol,
            "source": "binance_depth_wss_cache",
            "v2_key": key,
            "status": "pending",
        }
        cached = self._cached_depth(symbol, limit=limit)
        if cached is not None:
            self.data_plane[key] = cached
            result["status"] = "ok"
            result["persisted"] = True
            result["transport"] = "websocket_cache_primary"
            result["rest_fallback_used"] = False
            return result
        if self._blocked_by_backoff(result):
            return result
        if not self._rest_fallback_allowed_result(result, endpoint="/fapi/v1/depth"):
            return result
        status, payload = self._http_get(
            f"https://fapi.binance.com/fapi/v1/depth?symbol={symbol}&limit={int(limit)}"
        )
        if not self._public_http_ok(status, payload, result):
            return result
        if not isinstance(payload, dict):
            result["status"] = "unexpected_payload"
            return result
        self.data_plane[key] = {
            "symbol": symbol,
            "last_update_id": payload.get("lastUpdateId"),
            "bids": payload.get("bids") or [],
            "asks": payload.get("asks") or [],
            "ts_ms": int(self._clock() * 1000),
            "source": "binance_public_rest_depth_snapshot_fallback",
        }
        result["status"] = "ok"
        result["persisted"] = True
        result["rest_fallback_used"] = True
        return result

    def health_snapshot(self) -> HealthSnapshot:
        now = self._clock()
        coinapi_healthy = self._coinapi_v1_healthy(now)
        snap = HealthSnapshot(
            coinapi_v1_healthy=coinapi_healthy,
            coinapi_v1_last_ts=self._coinapi_v1_last_ts,
            binance_rest_healthy=now >= self._backoff_until,
            consecutive_5xx=self._consecutive_5xx,
            consecutive_bans=self._consecutive_bans,
            consecutive_geo_blocks=self._consecutive_geo_blocks,
            backoff_until=self._backoff_until,
            rate_limit_state=self._rate_limit_state,
        )
        self.data_plane[f"{V2_KEY_PREFIX}:source_health"] = snap.to_dict()
        return snap

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _plane_json(self, key: str) -> Any:
        value = self.data_plane.get(key)
        if isinstance(value, str):
            try:
                return json.loads(value)
            except Exception:
                return None
        return value

    def _websocket_or_cache_primary(self, payload: Mapping[str, Any]) -> bool:
        source = str(payload.get("source") or payload.get("transport") or "").lower()
        if "rest" in source:
            return False
        return any(token in source for token in ("wss", "websocket", "ws_cache", "stream", "cache_primary"))

    def _closed_before_now(self, row: Mapping[str, Any]) -> bool:
        if (
            row.get("is_closed") is True
            or row.get("closed_candle") is True
            or row.get("candle_closed_confirmed") is True
        ):
            return True
        close_time = (
            row.get("candle_close_time")
            or row.get("close_time")
            or row.get("closeTime")
        )
        if close_time in (None, ""):
            return False
        try:
            return int(float(close_time)) <= int(self._clock() * 1000)
        except (TypeError, ValueError):
            return False

    def _cache_bar(self, row: Mapping[str, Any], symbol: str, timeframe: str) -> Dict[str, Any] | None:
        if not self._closed_before_now(row):
            return None
        ohlcv = row.get("ohlcv") if isinstance(row.get("ohlcv"), Mapping) else {}
        ts = (
            row.get("ts")
            or row.get("candle_open_time")
            or row.get("open_time")
            or row.get("openTime")
        )
        try:
            ts_ms = int(float(ts or 0))
        except (TypeError, ValueError):
            ts_ms = 0
        if ts_ms <= 0:
            return None
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "ts": ts_ms,
            "open": _safe_float(row.get("open") or ohlcv.get("open")),
            "high": _safe_float(row.get("high") or ohlcv.get("high")),
            "low": _safe_float(row.get("low") or ohlcv.get("low")),
            "close": _safe_float(row.get("close") or ohlcv.get("close")),
            "volume": _safe_float(row.get("volume") or ohlcv.get("volume")),
            "source": "binance_wss_closed_kline_cache",
        }

    def _wss_cached_klines(self, symbol: str, timeframe: str, limit: int) -> Optional[List[Dict[str, Any]]]:
        keys = (
            f"{V2_KEY_PREFIX}:ohlcv_closed:binance:{symbol}:{timeframe}",
            f"{V2_KEY_PREFIX}:kline_closed:binance:{symbol}:{timeframe}",
            f"{V2_KEY_PREFIX}:{symbol}:ohlcv_closed:{timeframe}",
        )
        for key in keys:
            payload = self._plane_json(key)
            if not isinstance(payload, list):
                continue
            bars: list[Dict[str, Any]] = []
            for item in payload:
                if not isinstance(item, Mapping):
                    continue
                if not self._websocket_or_cache_primary(item):
                    continue
                bar = self._cache_bar(item, symbol, timeframe)
                if bar is not None:
                    bars.append(bar)
            if bars:
                bars.sort(key=lambda item: int(item.get("ts") or 0))
                return bars[-max(1, int(limit)) :]
        return None

    def _cached_bbo(self, symbol: str) -> Dict[str, Any] | None:
        for key in (
            f"{V2_KEY_PREFIX}:{symbol}:bbo",
            f"{V2_KEY_PREFIX}:orderbook_top:{symbol}",
            f"{V2_KEY_PREFIX}:orderbook:binance:{symbol}",
            f"{V2_KEY_PREFIX}:orderbook:{symbol}",
        ):
            payload = self._plane_json(key)
            if not isinstance(payload, Mapping) or not self._websocket_or_cache_primary(payload):
                continue
            bids = payload.get("bids") if isinstance(payload.get("bids"), list) else []
            asks = payload.get("asks") if isinstance(payload.get("asks"), list) else []
            bid = _safe_float(
                payload.get("bid")
                or payload.get("best_bid")
                or payload.get("bidPrice")
                or ((bids[0][0] if isinstance(bids[0], (list, tuple)) and bids[0] else None) if bids else None)
            )
            ask = _safe_float(
                payload.get("ask")
                or payload.get("best_ask")
                or payload.get("askPrice")
                or ((asks[0][0] if isinstance(asks[0], (list, tuple)) and asks[0] else None) if asks else None)
            )
            if bid is None and ask is None:
                continue
            return {
                "symbol": symbol,
                "bid": bid,
                "ask": ask,
                "ts_ms": int(payload.get("ts_ms") or payload.get("event_time_ms") or payload.get("E") or self._clock() * 1000),
                "source": payload.get("source") or "binance_bookticker_wss_cache",
            }
        return None

    def _cached_mark_funding(self, symbol: str) -> Dict[str, Dict[str, Any]] | None:
        mark_payload: Mapping[str, Any] = {}
        funding_payload: Mapping[str, Any] = {}
        for key in (
            f"{V2_KEY_PREFIX}:{symbol}:mark",
            f"{V2_KEY_PREFIX}:mark_price:{symbol}",
            f"{V2_KEY_PREFIX}:prices:{symbol}",
        ):
            payload = self._plane_json(key)
            if isinstance(payload, Mapping) and self._websocket_or_cache_primary(payload):
                mark_payload = payload
                break
        for key in (
            f"{V2_KEY_PREFIX}:{symbol}:funding",
            f"{V2_KEY_PREFIX}:funding:{symbol}",
        ):
            payload = self._plane_json(key)
            if isinstance(payload, Mapping) and self._websocket_or_cache_primary(payload):
                funding_payload = payload
                break
        nested_funding = mark_payload.get("funding") if isinstance(mark_payload.get("funding"), Mapping) else {}
        mark_price = _safe_float(mark_payload.get("mark_price") or mark_payload.get("markPrice"))
        index_price = _safe_float(mark_payload.get("index_price") or mark_payload.get("indexPrice"))
        funding_rate = _safe_float(
            funding_payload.get("funding_rate")
            or funding_payload.get("lastFundingRate")
            or nested_funding.get("funding_rate")
            or nested_funding.get("lastFundingRate")
        )
        if mark_price is None and index_price is None and funding_rate is None:
            return None
        ts_ms = int(
            mark_payload.get("ts_ms")
            or mark_payload.get("time")
            or funding_payload.get("ts_ms")
            or funding_payload.get("time")
            or self._clock() * 1000
        )
        mark_source = mark_payload.get("source") or "binance_mark_price_wss_cache"
        funding_source = funding_payload.get("source") or mark_source
        return {
            "mark": {
                "symbol": symbol,
                "mark_price": mark_price,
                "index_price": index_price,
                "estimated_settle_price": _safe_float(
                    mark_payload.get("estimated_settle_price") or mark_payload.get("estimatedSettlePrice")
                ),
                "ts_ms": ts_ms,
                "source": mark_source,
            },
            "funding": {
                "symbol": symbol,
                "funding_rate": funding_rate,
                "next_funding_time": int(
                    funding_payload.get("next_funding_time")
                    or funding_payload.get("nextFundingTime")
                    or nested_funding.get("nextFundingTime")
                    or 0
                ),
                "interest_rate": _safe_float(
                    funding_payload.get("interest_rate")
                    or funding_payload.get("interestRate")
                    or nested_funding.get("interestRate")
                ),
                "ts_ms": ts_ms,
                "source": funding_source,
            },
        }

    def _cached_open_interest(self, symbol: str) -> Dict[str, Any] | None:
        for key in (
            f"{V2_KEY_PREFIX}:{symbol}:open_interest",
            f"{V2_KEY_PREFIX}:open_interest:{symbol}",
        ):
            payload = self._plane_json(key)
            if not isinstance(payload, Mapping):
                continue
            if not self._websocket_or_cache_primary(payload) and "provider" not in str(payload.get("source") or "").lower():
                continue
            value = _safe_float(
                payload.get("open_interest")
                or payload.get("openInterest")
                or payload.get("open_interest_contracts")
            )
            if value is None:
                continue
            return {
                "symbol": symbol,
                "open_interest": value,
                "ts_ms": int(payload.get("ts_ms") or payload.get("time") or self._clock() * 1000),
                "source": payload.get("source") or "market_cache_or_provider_bridge",
            }
        return None

    def _cached_depth(self, symbol: str, *, limit: int) -> Dict[str, Any] | None:
        for key in (
            f"{V2_KEY_PREFIX}:{symbol}:depth",
            f"{V2_KEY_PREFIX}:orderbook:{symbol}",
            f"{V2_KEY_PREFIX}:orderbook_top:{symbol}",
        ):
            payload = self._plane_json(key)
            if not isinstance(payload, Mapping) or not self._websocket_or_cache_primary(payload):
                continue
            bids = payload.get("bids") if isinstance(payload.get("bids"), list) else []
            asks = payload.get("asks") if isinstance(payload.get("asks"), list) else []
            if not bids and payload.get("best_bid") is not None:
                bids = [[payload.get("best_bid"), payload.get("bid_qty") or payload.get("bidQty") or "0"]]
            if not asks and payload.get("best_ask") is not None:
                asks = [[payload.get("best_ask"), payload.get("ask_qty") or payload.get("askQty") or "0"]]
            if not bids and not asks:
                continue
            return {
                "symbol": symbol,
                "last_update_id": payload.get("lastUpdateId") or payload.get("last_update_id") or payload.get("update_id"),
                "bids": bids[: max(1, int(limit))],
                "asks": asks[: max(1, int(limit))],
                "ts_ms": int(payload.get("ts_ms") or payload.get("event_time_ms") or payload.get("E") or self._clock() * 1000),
                "source": payload.get("source") or "binance_depth_wss_cache",
            }
        return None

    def _coinapi_v1_healthy(self, now: float) -> bool:
        """Preserved from
        legacy_preserved/startup_baseline/ingest/live_binance.py
        ``_check_coinapi_ohlcv_healthy`` (L233-291). Considers the source
        healthy when last OHLCV ts is within the legacy 120s threshold.
        """
        if self._coinapi_v1_last_ts is None:
            return False
        return (now - self._coinapi_v1_last_ts) <= COINAPI_OHLCV_STALE_THRESHOLD_SEC

    def _coinapi_v1_klines(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
    ) -> Optional[List[Dict[str, Any]]]:
        """CoinAPI V1 OHLCV pull (primary).

        Per the legacy 30% V1 budget split (``COINAPI_V1_BUDGET_PCT`` in
        live_coinapi_v1.py L58), refuse the call if the local counter has
        exhausted the budget.
        """
        budget = int(self._coinapi_daily_budget * self._coinapi_v1_budget_pct)
        if self._coinapi_v1_msgs_today >= budget:
            return None
        period = _to_coinapi_period(timeframe)
        url = (
            "https://rest.coinapi.io/v1/ohlcv/"
            f"{_to_coinapi_symbol_id(symbol)}/latest?period_id={period}&limit={int(limit)}"
        )
        status, payload = self._http_get(url)
        if 500 <= status < 600:
            self._record_http_5xx()
            return None
        if status == 429:
            self._record_rate_limit_ban()
            return None
        if status == 451:
            self._record_geo_block()
            return None
        if not (200 <= status < 300) or not isinstance(payload, list):
            return None
        self._coinapi_v1_msgs_today += 1
        self._coinapi_v1_last_ts = self._clock()
        return [_coinapi_to_bar(item, symbol, timeframe) for item in payload]

    def _rest_fallback_allowed_result(self, result: Dict[str, Any], *, endpoint: str) -> bool:
        decision = binance_rest_fallback_decision(
            endpoint=endpoint,
            fallback_reason=f"{endpoint.strip('/').replace('/', '_')}_websocket_cache_miss",
            role="market_ingest_public_data_recovery",
        )
        if decision["request_allowed"]:
            result["rest_fallback_reason"] = decision["rest_fallback_reason"]
            result["rest_used_as_primary"] = False
            return True
        result["status"] = "blocked_rest_fallback_disabled"
        result["endpoint"] = endpoint
        result["blocked_reason"] = decision["rest_fallback_blocked_reason"]
        result["required_env"] = f"{REST_FALLBACK_ENV}=true"
        result["transport_policy"] = "binance_websocket_cache_primary_rest_fallback_only"
        result["rest_fallback_used"] = False
        result["rest_used_as_primary"] = False
        return False

    def _binance_rest_klines(
        self,
        symbol: str,
        timeframe: str,
        limit: int,
        result: IngestResult,
    ) -> Optional[List[Dict[str, Any]]]:
        """Binance USD-M public REST klines (fallback)."""
        decision = binance_rest_fallback_decision(
            endpoint="/fapi/v1/klines",
            fallback_reason="ohlcv_websocket_cache_and_coinapi_fallback_missing",
            role="market_ingest_kline_recovery",
        )
        if not decision["request_allowed"]:
            result.errors.append(f"binance_rest_fallback_blocked:{decision['rest_fallback_blocked_reason']}")
            return None
        url = (
            "https://fapi.binance.com/fapi/v1/klines?"
            f"symbol={symbol}&interval={timeframe}&limit={int(limit)}"
        )
        status, payload = self._http_get(url)
        if 500 <= status < 600:
            self._record_http_5xx()
            result.errors.append(f"http_5xx:{status}")
            return None
        if status == 429:
            self._record_rate_limit_ban()
            result.errors.append("http_429_rate_limit")
            return None
        if status == 418 or status == -1003 or _is_minus_1003(payload):
            self._record_rate_limit_ban()
            result.errors.append("binance_minus_1003_rate_limit_ban")
            return None
        if status == 451:
            self._record_geo_block()
            result.errors.append("http_451_geo_block")
            return None
        if not (200 <= status < 300) or not isinstance(payload, list):
            result.errors.append(f"http_unexpected:{status}")
            return None
        return [_binance_kline_to_bar(row, symbol, timeframe) for row in payload]

    # ----- backoff recorders (legacy-anchored) -------------------------

    def _record_rate_limit_ban(self) -> None:
        self._consecutive_bans += 1
        backoff = min(
            RATE_LIMIT_BAN_START_SEC * (2 ** min(self._consecutive_bans - 1, 3)),
            RATE_LIMIT_BAN_CAP_SEC,
        )
        self._backoff_until = self._clock() + backoff
        self._rate_limit_state = "rate_limit_ban"

    def _record_geo_block(self) -> None:
        self._consecutive_geo_blocks += 1
        if self._consecutive_geo_blocks >= GEO_BLOCK_ESCALATION_AFTER_N:
            backoff = GEO_BLOCK_ESCALATION_SEC
        else:
            backoff = min(
                GEO_BLOCK_START_SEC
                * (2 ** min(self._consecutive_geo_blocks - 1, 3)),
                GEO_BLOCK_CAP_SEC,
            )
        self._backoff_until = self._clock() + backoff
        self._rate_limit_state = "geo_blocked"

    def _record_http_5xx(self) -> None:
        """STRICTER than legacy (which used 5s start, 180s cap). V2 starts at
        30s and caps at 300s, and fail-closes (no persistence while window
        active).
        """
        self._consecutive_5xx += 1
        backoff = min(
            HTTP_5XX_START_SEC * (2 ** min(self._consecutive_5xx - 1, 3)),
            HTTP_5XX_CAP_SEC,
        )
        self._backoff_until = self._clock() + backoff
        self._rate_limit_state = "backoff_5xx"

    def _blocked_by_backoff(self, result: Dict[str, Any]) -> bool:
        now = self._clock()
        if now >= self._backoff_until:
            return False
        result["status"] = "blocked_backoff"
        result["rate_limit_state"] = self._rate_limit_state
        result["backoff_until"] = self._backoff_until
        return True

    def _public_http_ok(self, status: int, payload: Any, result: Dict[str, Any]) -> bool:
        if 500 <= status < 600:
            self._record_http_5xx()
            result["status"] = "http_5xx"
            result["http_status"] = status
            return False
        if status == 429 or status == 418 or _is_minus_1003(payload):
            self._record_rate_limit_ban()
            result["status"] = "rate_limit_ban"
            result["http_status"] = status
            return False
        if status == 451:
            self._record_geo_block()
            result["status"] = "geo_blocked"
            result["http_status"] = status
            return False
        if not (200 <= status < 300):
            result["status"] = "http_unexpected"
            result["http_status"] = status
            return False
        return True


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _default_http_get(url: str) -> Tuple[int, Any]:
    """Synchronous public-GET fetch using the stdlib only.

    Returns ``(status_code, parsed_json_or_text)``. The CLI prefers to inject
    its own ``http_get`` so this is only used as a safe last resort.
    """
    import urllib.error
    import urllib.request

    if "binance.com" in url:
        decision = binance_rest_fallback_decision(
            endpoint=url,
            fallback_reason="market_ingest_default_http_cache_miss",
            role="market_ingest_public_data_recovery",
        )
        if not decision["request_allowed"]:
            return 599, {
                "error": "BINANCE_REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
                "blocked_reason": decision["rest_fallback_blocked_reason"],
                "required_env": f"{REST_FALLBACK_ENV}=true",
                "rest_used_as_primary": False,
            }
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"User-Agent": "ai-bot-v2-v2_market_ingestor-readonly"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            body = response.read().decode("utf-8")
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8")
        except Exception:
            body = ""
        return int(exc.code), _try_json(body)
    except Exception:
        return 599, None
    return status, _try_json(body)


def _try_json(body: str) -> Any:
    if not body:
        return None
    try:
        return json.loads(body)
    except Exception:
        return body


def _binance_kline_to_bar(row: List[Any], symbol: str, timeframe: str) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "ts": int(row[0]),
        "open": _safe_float(row[1]),
        "high": _safe_float(row[2]),
        "low": _safe_float(row[3]),
        "close": _safe_float(row[4]),
        "volume": _safe_float(row[5]),
        "source": "binance_rest",
    }


def _coinapi_to_bar(item: Dict[str, Any], symbol: str, timeframe: str) -> Dict[str, Any]:
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "ts": _iso_to_ms(item.get("time_period_start")),
        "open": _safe_float(item.get("price_open")),
        "high": _safe_float(item.get("price_high")),
        "low": _safe_float(item.get("price_low")),
        "close": _safe_float(item.get("price_close")),
        "volume": _safe_float(item.get("volume_traded")),
        "source": "coinapi_v1",
    }


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _iso_to_ms(value: Any) -> int:
    if not value:
        return 0
    try:
        import datetime as dt

        return int(
            dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
            * 1000
        )
    except Exception:
        return 0


def _to_coinapi_period(timeframe: str) -> str:
    mapping = {
        "1m": "1MIN",
        "5m": "5MIN",
        "15m": "15MIN",
        "1h": "1HRS",
        "4h": "4HRS",
        "1d": "1DAY",
    }
    return mapping.get(timeframe, "1MIN")


def _to_coinapi_symbol_id(symbol: str) -> str:
    if symbol.upper().endswith("USDT"):
        base = symbol[:-4].upper()
        return f"BINANCE_FTS_PERP_{base}_USDT"
    return symbol.upper()


def _to_kucoin_symbol(symbol: str) -> str:
    if symbol.upper().endswith("USDT"):
        base = symbol[:-4].upper()
        return f"{base}-USDT"
    return symbol.upper()


def _is_minus_1003(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    code = payload.get("code")
    msg = str(payload.get("msg") or "")
    return code == -1003 or "Way too many requests" in msg


def legacy_ws_reconnect_backoff_schedule(max_retries: Optional[int] = None) -> List[float]:
    """Return the legacy WS reconnect retry schedule this REST worker delegates.

    The market ingestor does not open a websocket, but the schedule is executable
    contract coverage for the separate V2 WS worker that owns that behavior.
    """
    retries = int(max_retries or LEGACY_WS_RECONNECT_POLICY["max_retries"])
    start = float(LEGACY_WS_RECONNECT_POLICY["backoff_start_seconds"])
    multiplier = float(LEGACY_WS_RECONNECT_POLICY["backoff_multiplier"])
    cap = float(LEGACY_WS_RECONNECT_POLICY["backoff_cap_seconds"])
    return [min(start * (multiplier ** i), cap) for i in range(retries)]
